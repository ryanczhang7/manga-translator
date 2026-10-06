"""MT-069: parallel cv2 calls survive a lost thread-pool completion port.

The state (audit MT-068, Decided 1, E3-E5, E9): OpenCV 5.0.0 runs its parallel
calls on a statically linked MSVC Concurrency Runtime. A thread's first parallel
cv2 call attaches it to ConcRT, and the attach calls `SetThreadpoolWait`. If the
process's default Windows thread pool has lost its I/O completion port, that
raises `0xC000070A` on the calling thread, cv2 reports it as
`cv2.error: Unknown C++ exception from OpenCV code`, and it happens again on
every parallel call that thread makes.

Every case runs fresh child interpreters (`sys.executable`, this process's
environment), so this pytest process - which has long since attached its own
threads to ConcRT - is never the subject. For each criterion there is one
*clean* child and one *induced* child, run side by side. Both build every input
first (contract C-2: no RNG after the close, MT-068 PO-7). The induced child then
(contract C-3, re-derived here, not copied from `spikes/`):

- walks the handle values 4, 8, ... 0x8000 and asks `NtQueryObject` with
  `ObjectTypeInformation` for each one's type name;
- closes the lowest-valued handle whose type is `IoCompletion`, and reports the
  value and `CloseHandle`'s result.

Only then does either child import the production modules and call
`erase_mask(regions, (1600, 1125))` and `letterbox(page)` - on its main thread
(AC-1) or on a `threading.Thread` started after the close (AC-2). Each writes its
arrays to an `.npz` under `tmp_path` and prints one JSON line.

The vacuity canary (contract C-4 as amended in RED, binding): after the
production calls, each child makes, on a fresh thread, the very call ConcRT's
attach makes (audit E3) - `CreateThreadpoolWait` then `SetThreadpoolWait` on an
unsignalled event, through ctypes. In the induced child it must raise
`0xC000070A` (`STATUS_THREADPOOL_HANDLE_EXCEPTION`, audit E1), which ctypes
surfaces as `OSError` with that `winerror` (audit E4); if it does not, the port
was never lost and an equal result would prove nothing, so the test fails. In the
clean child it must succeed, so its failure is about the port and nothing else.

Why not the `cv2.setNumThreads(4)` + `GaussianBlur` canary C-4 first named: RED
measured that it *succeeds* in an induced process. Any `cv2.setNumThreads`
call, with any value (-1, 0, 4, 12), keeps every later cv2 call in that process
alive on a closed port, so no cv2-level canary can fire after a containment that
calls it. The thread-pool call does not depend on anything cv2 has done.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the default Windows thread pool and its completion port exist on Windows only",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# One child measured about 1.5-2.5 s locally, two of them running side by side
# (see the story's handoff). CI's windows-latest runner is taken as ~4x slower;
# the coverage gate instruments the parent, not these children. 60 s is generous
# and finite.
_CHILD_TIMEOUT_S = 60.0

# STATUS_THREADPOOL_HANDLE_EXCEPTION (audit E1), as ctypes reports it from
# SetThreadpoolWait when the default pool's completion port is gone (audit E4).
_THREADPOOL_HANDLE_EXCEPTION = 0xC000070A

_REPORT_PREFIX = "MT069-REPORT "

_THREAD = {"main": "the main thread", "thread": "a threading.Thread started after the close"}

_CHILD = r"""
import ctypes
import ctypes.wintypes as wt
import io
import json
import sys
import threading

import numpy as np
from PIL import Image

from mangatl.domain.region import RawRegion

MODE = sys.argv[1]  # "clean" or "induced"
WHERE = sys.argv[2]  # "main" or "thread"
OUT = sys.argv[3]

report = {
    "python": sys.version,
    "mode": MODE,
    "where": WHERE,
    "closed_handle": None,
    "close_ok": None,
    "close_error": None,
    "calls": {},
    "transform": None,
    "canary": None,
}

# --- C-2: every input, before anything is closed ---------------------------------
HEIGHT, WIDTH = 1125, 1600
rng = np.random.default_rng(69)
page = rng.integers(0, 256, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)

yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
shapes = [
    ("bubble", (120, 90, 420, 330), (yy - 210) ** 2 / 90**2 + (xx - 270) ** 2 / 120**2 <= 1.0),
    ("box", (900, 600, 1300, 760), (yy >= 600) & (yy < 760) & (xx >= 900) & (xx < 1300)),
    ("bubble", (1350, 820, 1560, 1100), (yy - 960) ** 2 / 130**2 + (xx - 1455) ** 2 / 95**2 <= 1),
    # a striped column: many thin runs, so the dilation joins them
    ("box", (40, 980, 70, 1100), (xx % 6 < 3) & (yy >= 980) & (yy < 1100) & (xx >= 40) & (xx < 70)),
]
regions = []
for kind, (x0, y0, x1, y1), pixels in shapes:
    buffer = io.BytesIO()
    Image.fromarray(pixels.astype(np.uint8) * 255).convert("1").save(buffer, format="PNG")
    ring = ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))
    regions.append(RawRegion(polygon=ring, mask=buffer.getvalue(), confidence=0.9, kind=kind))
del yy, xx, shapes

# --- C-3: close the lowest-valued IoCompletion handle -----------------------------
if MODE == "induced":

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", ctypes.c_ushort),
            ("MaximumLength", ctypes.c_ushort),
            ("Buffer", ctypes.c_void_p),
        ]

    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtQueryObject.restype = ctypes.c_long
    ntdll.NtQueryObject.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p
    ]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    OBJECT_TYPE_INFORMATION = 2
    info = ctypes.create_string_buffer(4096)

    def type_name(value):
        status = ntdll.NtQueryObject(value, OBJECT_TYPE_INFORMATION, info, len(info), None)
        if status < 0:
            return None
        name = UnicodeString.from_buffer(info)
        return ctypes.wstring_at(name.Buffer, name.Length // 2) if name.Buffer else None

    target = next((v for v in range(4, 0x8000, 4) if type_name(v) == "IoCompletion"), None)
    if target is None:
        report["close_error"] = "no handle of type IoCompletion in handle values 4..0x8000"
    else:
        report["closed_handle"] = target
        report["close_ok"] = bool(kernel32.CloseHandle(target))
        if not report["close_ok"]:
            failure = ctypes.get_last_error()
            report["close_error"] = f"CloseHandle({target:#x}) failed, error {failure}"

# --- the production calls ---------------------------------------------------------
from mangatl.clean.mask import erase_mask
from mangatl.detect.postprocess import letterbox

results = {}


def outcome(error):
    kind = f"{type(error).__module__}.{type(error).__name__}"
    return {"ok": False, "error": f"{kind}: {error}".strip()}


def production_calls():
    try:
        results["mask"] = erase_mask(regions, (WIDTH, HEIGHT))
        report["calls"]["erase_mask"] = {"ok": True, "error": None}
    except Exception as error:
        report["calls"]["erase_mask"] = outcome(error)
    try:
        canvas, transform = letterbox(page)
        results["canvas"] = canvas
        report["transform"] = {
            "ratio": transform.ratio, "pad_x": transform.pad_x, "pad_y": transform.pad_y
        }
        report["calls"]["letterbox"] = {"ok": True, "error": None}
    except Exception as error:
        report["calls"]["letterbox"] = outcome(error)


if WHERE == "main":
    production_calls()
else:
    worker = threading.Thread(target=production_calls)
    worker.start()
    worker.join()


# --- C-4 (amended): the vacuity canary, on a fresh thread ------------------------
# The call ConcRT's attach makes (audit E3): register a thread-pool wait. With the
# default pool's port gone it raises 0xC000070A, which ctypes turns into OSError.
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
VOIDP = ctypes.c_void_p
WAIT_CALLBACK = ctypes.WINFUNCTYPE(None, VOIDP, VOIDP, VOIDP, wt.DWORD)
k32.CreateEventW.restype = ctypes.c_void_p
k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, ctypes.c_void_p]
k32.CreateThreadpoolWait.restype = ctypes.c_void_p
k32.CreateThreadpoolWait.argtypes = [WAIT_CALLBACK, ctypes.c_void_p, ctypes.c_void_p]
k32.SetThreadpoolWait.restype = None
k32.SetThreadpoolWait.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
k32.WaitForThreadpoolWaitCallbacks.restype = None
k32.WaitForThreadpoolWaitCallbacks.argtypes = [ctypes.c_void_p, wt.BOOL]
k32.CloseThreadpoolWait.restype = None
k32.CloseThreadpoolWait.argtypes = [ctypes.c_void_p]
k32.CloseHandle.restype = wt.BOOL
k32.CloseHandle.argtypes = [ctypes.c_void_p]
never_called = WAIT_CALLBACK(lambda *_: None)


def canary():
    event = k32.CreateEventW(None, True, False, None)
    wait = k32.CreateThreadpoolWait(never_called, None, None)
    if not event or not wait:
        failure = ctypes.get_last_error()
        report["canary"] = {"ok": False, "winerror": None, "error": f"setup failed: {failure}"}
        return
    try:
        k32.SetThreadpoolWait(wait, event, None)
    except OSError as error:
        code = error.winerror & 0xFFFFFFFF if error.winerror is not None else None
        report["canary"] = {"ok": False, "winerror": code, "error": f"OSError: {error}"}
        return
    k32.SetThreadpoolWait(wait, None, None)
    k32.WaitForThreadpoolWaitCallbacks(wait, True)
    k32.CloseThreadpoolWait(wait)
    k32.CloseHandle(event)
    report["canary"] = {"ok": True, "winerror": None, "error": None}


fresh = threading.Thread(target=canary)
fresh.start()
fresh.join()

np.savez(OUT, **results)
print("MT069-REPORT " + json.dumps(report), flush=True)
"""


@contextmanager
def _children(tmp_path: Path, where: str) -> Iterator[tuple[subprocess.Popen[str], ...]]:
    """Start a clean and an induced child side by side; kill any still running on exit."""
    procs = tuple(
        subprocess.Popen(
            [sys.executable, "-c", _CHILD, mode, where, str(tmp_path / f"{mode}-{where}.npz")],
            cwd=_REPO_ROOT,
            env=dict(os.environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for mode in ("clean", "induced")
    )
    try:
        yield procs
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


def _report(proc: subprocess.Popen[str], label: str) -> dict[str, Any]:
    """Wait for one child and return its JSON report, or fail saying why it gave none."""
    stdout, stderr = proc.communicate(timeout=_CHILD_TIMEOUT_S)
    lines = [ln for ln in stdout.splitlines() if ln.startswith(_REPORT_PREFIX)]
    assert proc.returncode == 0 and len(lines) == 1, (
        f"the {label} child did not report (exit {proc.returncode:#x})\n"
        f"stdout:\n{stdout}\nstderr:\n{stderr}"
    )
    report: dict[str, Any] = json.loads(lines[0].removeprefix(_REPORT_PREFIX))
    return report


def _run_pair(tmp_path: Path, where: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with _children(tmp_path, where) as (clean_proc, induced_proc):
        clean = _report(clean_proc, f"clean ({where})")
        induced = _report(induced_proc, f"induced ({where})")
    return clean, induced


def _problems(tmp_path: Path, where: str, label: str) -> list[str]:
    """Every way the induced child differs from the clean one, plus every vacuity failure."""
    clean, induced = _run_pair(tmp_path, where)
    problems: list[str] = []

    # The reference: the clean child must produce it, and its canary must succeed,
    # so that the induced canary's failure is about the port and nothing else.
    for name, call in clean["calls"].items():
        if not call["ok"]:
            problems.append(f"the clean reference child's {name} failed: {call['error']}")
    if not clean["canary"]["ok"]:
        problems.append(
            f"the clean child's canary SetThreadpoolWait failed: {clean['canary']['error']}"
        )

    # C-3 and the C-4 canary: the state must really have been induced, and still hold
    # after the production calls.
    if induced["close_error"] is not None or not induced["close_ok"]:
        problems.append(
            f"the induced child did not close the completion port: {induced['close_error']}"
        )
    canary = induced["canary"]
    if canary["ok"]:
        problems.append(
            "VACUOUS: the canary SetThreadpoolWait on a fresh thread succeeded in the induced"
            " child, so the default thread pool's completion port was never lost"
        )
    elif canary["winerror"] != _THREADPOOL_HANDLE_EXCEPTION:
        problems.append(
            f"the induced canary failed, but not with {_THREADPOOL_HANDLE_EXCEPTION:#x}:"
            f" {canary['error']}"
        )

    # AC-1 / AC-2: neither call raises, and both equal the clean reference.
    port = f"{induced['closed_handle']:#x}" if induced["closed_handle"] is not None else "?"
    for name in ("erase_mask", "letterbox"):
        call = induced["calls"][name]
        if not call["ok"]:
            problems.append(
                f"{label}: {name} raised on {_THREAD[where]}, with the default thread"
                f" pool's completion port ({port}) closed: {call['error']}"
            )
    if problems:
        return problems

    with (
        np.load(tmp_path / f"clean-{where}.npz") as reference,
        np.load(tmp_path / f"induced-{where}.npz") as observed,
    ):
        if not np.array_equal(observed["mask"], reference["mask"]):
            problems.append(f"{label}: erase_mask differs from the clean process's mask")
        if observed["mask"].dtype != np.bool_ or observed["mask"].shape != (1125, 1600):
            problems.append(
                f"{label}: erase_mask is {observed['mask'].dtype} {observed['mask'].shape}"
            )
        if not np.array_equal(observed["canvas"], reference["canvas"]):
            problems.append(f"{label}: letterbox's canvas differs from the clean process's canvas")
        if observed["canvas"].dtype != reference["canvas"].dtype:
            problems.append(f"{label}: letterbox's canvas dtype is {observed['canvas'].dtype}")
    if induced["transform"] != clean["transform"]:
        problems.append(
            f"{label}: letterbox's transform {induced['transform']} differs from the clean"
            f" process's {clean['transform']}"
        )
    return problems


def test_erase_mask_and_letterbox_on_the_main_thread_survive_a_closed_completion_port(
    tmp_path: Path,
) -> None:
    """AC-1: main-thread calls after the close equal a clean process's, and do not raise."""
    problems = _problems(tmp_path, "main", "AC-1")
    assert not problems, "\n".join(problems)


def test_erase_mask_and_letterbox_on_a_thread_started_after_the_port_closed_survive(
    tmp_path: Path,
) -> None:
    """AC-2: the same calls on a thread started after the close equal the clean results."""
    problems = _problems(tmp_path, "thread", "AC-2")
    assert not problems, "\n".join(problems)
