"""MT-071: `clean_page` survives a lost thread-pool completion port, inpaint alone.

MT-069 put `cv2.setNumThreads(-1)` beside every `import cv2`, so that parallel
cv2 survives a process whose default Windows thread pool has lost its I/O
completion port (audit MT-068). Its tests call `erase_mask` and `letterbox`, and
either module's line protects the whole process. `mangatl.clean.inpaint` imports
neither `mangatl.clean.mask` nor `mangatl.detect.postprocess`, so in a process
that imports only `inpaint`, `inpaint.py`'s own line is the only containment.
This file pins it (AC-1).

House style of `test_cv2_lost_completion_port.py` (MT-069), re-derived here and
not imported from it. One *clean* and one *induced* fresh `sys.executable -c`
child run side by side. Both build the page (seeded RNG) and the mask before
anything is closed (MT-068 PO-7). The induced child then walks handle values
4, 8, ... 0x8000, asks `NtQueryObject(ObjectTypeInformation)` for each one's type
name and closes the lowest-valued `IoCompletion` handle. Only then does either
child import `mangatl.clean.inpaint` and call `clean_page` with a deterministic
numpy-only stub session. The mask has four 8-connected blobs - three that take
the native 512 path and one too large for it, which takes the downscale path
(`cv2.resize`) - so `cv2.connectedComponentsWithStats` runs on a non-trivial
mask.

Three checks keep the equality from being vacuous:

- **The import set.** After `clean_page`, the child reports whether
  `mangatl.clean.mask` or `mangatl.detect.postprocess` is in `sys.modules`; the
  test fails if either is, because then their containment line, not inpaint's,
  could be what kept the process alive.
- **The vacuity canary** (MT-069 C-4 as amended). After the production call,
  on a fresh thread, `CreateThreadpoolWait` + `SetThreadpoolWait` on an
  unsignalled event, through ctypes - the call ConcRT's attach makes. In the
  induced child it must raise `OSError` with `winerror` `0xC000070A`, or the
  port was never lost and the test fails as VACUOUS. In the clean child it must
  succeed.
- **The earning mutation** (story contract): with `cv2.setNumThreads(-1)` in
  `inpaint.py` replaced by `pass`, this test goes red with `Unknown C++
  exception` from the induced child. Recorded in the story's handoff.
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

# The pair measured about 2-3 s locally (see the story's handoff). CI's
# windows-latest runner is taken as several times slower; the coverage gate
# instruments the parent, not these children. 60 s is generous and finite.
_CHILD_TIMEOUT_S = 60.0

# STATUS_THREADPOOL_HANDLE_EXCEPTION (audit MT-068 E1), as ctypes reports it from
# SetThreadpoolWait when the default pool's completion port is gone (audit E4).
_THREADPOOL_HANDLE_EXCEPTION = 0xC000070A

_REPORT_PREFIX = "MT071-REPORT "

# The modules whose own containment line would protect the process if loaded.
_OTHER_CONTAINMENT = ("mangatl.clean.mask", "mangatl.detect.postprocess")

_PAGE_SHAPE = (1125, 1600, 3)

_CHILD = r"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import threading

import numpy as np

MODE = sys.argv[1]  # "clean" or "induced"
OUT = sys.argv[2]
OTHERS = ("mangatl.clean.mask", "mangatl.detect.postprocess")

report = {
    "python": sys.version,
    "mode": MODE,
    "closed_handle": None,
    "close_ok": None,
    "close_error": None,
    "call": None,
    "model_calls": 0,
    "others_loaded": None,
    "mangatl_modules": None,
    "canary": None,
}

# --- every input, before anything is closed (MT-068 PO-7) -------------------------
HEIGHT, WIDTH = 1125, 1600
rng = np.random.default_rng(71)
page = rng.integers(0, 256, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)
yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
mask = np.zeros((HEIGHT, WIDTH), dtype=bool)
# three blobs that fit the native 512 path ...
mask |= (yy - 200) ** 2 / 80**2 + (xx - 260) ** 2 / 110**2 <= 1.0
mask |= (yy >= 620) & (yy < 760) & (xx >= 300) & (xx < 520)
mask |= (yy - 950) ** 2 / 90**2 + (xx - 1450) ** 2 / 70**2 <= 1.0
# ... and one too large for it, which takes the downscale path (cv2.resize)
mask |= (yy >= 150) & (yy < 750) & (xx >= 800) & (xx < 1350)
del yy, xx


class StubSession:
    # Deterministic and numpy-only: the inverted image, in 8-bit scale.
    def __init__(self):
        self.calls = 0

    def run(self, image, mask):
        self.calls += 1
        return (255.0 - 255.0 * image).astype(np.float32)

    def get_providers(self):
        return ["StubExecutionProvider"]


session = StubSession()

# --- close the lowest-valued IoCompletion handle ---------------------------------
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

# --- the production call: inpaint, and nothing else of mangatl's -----------------
results = {}
try:
    from mangatl.clean.inpaint import clean_page

    results["cleaned"] = clean_page(page, mask, session)
    report["call"] = {"ok": True, "error": None}
except Exception as error:
    kind = f"{type(error).__module__}.{type(error).__name__}"
    report["call"] = {"ok": False, "error": f"{kind}: {error}".strip()}
report["model_calls"] = session.calls
report["others_loaded"] = {name: name in sys.modules for name in OTHERS}
report["mangatl_modules"] = sorted(m for m in sys.modules if m.split(".")[0] == "mangatl")

# --- the vacuity canary, on a fresh thread (MT-069 C-4 as amended) ---------------
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
print("MT071-REPORT " + json.dumps(report), flush=True)
"""


@contextmanager
def _children(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[str], ...]]:
    """Start a clean and an induced child side by side; kill any still running on exit."""
    procs = tuple(
        subprocess.Popen(
            [sys.executable, "-c", _CHILD, mode, str(tmp_path / f"{mode}.npz")],
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


def _import_problems(report: dict[str, Any], label: str) -> list[str]:
    """The child must have loaded neither module whose own containment would protect it."""
    problems: list[str] = []
    loaded = report["others_loaded"]
    for name in _OTHER_CONTAINMENT:
        if loaded.get(name) is not False:
            problems.append(
                f"the {label} child loaded {name} (sys.modules has {report['mangatl_modules']}),"
                " so its containment line, not inpaint's, may be what kept the process alive"
            )
    return problems


def test_clean_page_in_an_inpaint_only_process_survives_a_closed_completion_port(
    tmp_path: Path,
) -> None:
    """AC-1: with only inpaint imported and the port closed, clean_page equals a clean run."""
    with _children(tmp_path) as (clean_proc, induced_proc):
        clean = _report(clean_proc, "clean")
        induced = _report(induced_proc, "induced")
    problems: list[str] = []

    # The reference: the clean child must produce it, and its canary must succeed,
    # so that the induced canary's failure is about the port and nothing else.
    if clean["call"]["ok"] is not True:
        problems.append(f"the clean reference child's clean_page failed: {clean['call']['error']}")
    if clean["canary"]["ok"] is not True:
        problems.append(
            f"the clean child's canary SetThreadpoolWait failed: {clean['canary']['error']}"
        )
    problems += _import_problems(clean, "clean")
    problems += _import_problems(induced, "induced")

    # The state must really have been induced, and still hold after the call.
    if induced["close_error"] is not None or induced["close_ok"] is not True:
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

    # AC-1: clean_page does not raise ...
    port = f"{induced['closed_handle']:#x}" if induced["closed_handle"] is not None else "?"
    if induced["call"]["ok"] is not True:
        problems.append(
            "AC-1: clean_page raised in a process importing only mangatl.clean.inpaint, with"
            f" the default thread pool's completion port ({port}) closed:"
            f" {induced['call']['error']}"
        )
    # ... the mask really reached the model, on every component ...
    if clean["model_calls"] != 4 or induced["model_calls"] != clean["model_calls"]:
        problems.append(
            f"AC-1: expected 4 model calls (one per component) in each child; clean made"
            f" {clean['model_calls']}, induced {induced['model_calls']}"
        )
    assert not problems, "\n".join(problems)

    # ... and returns exactly what a process with nothing closed returns.
    with (
        np.load(tmp_path / "clean.npz") as reference,
        np.load(tmp_path / "induced.npz") as observed,
    ):
        expected, actual = reference["cleaned"], observed["cleaned"]
        assert expected.shape == _PAGE_SHAPE and expected.dtype == np.uint8, (
            f"the clean reference is {expected.dtype} {expected.shape}, not uint8 {_PAGE_SHAPE}"
        )
        assert np.array_equal(actual, expected), (
            "AC-1: clean_page in the induced process differs from the clean process's result"
            f" ({int((actual != expected).any(axis=-1).sum())} pixels differ)"
        )
