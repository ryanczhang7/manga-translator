"""MT-070: an abandoned `_wmi` query closes no handle it does not own.

The defect (audit MT-068, Decided 2, E7): on CPython 3.12.14 `_wmi.exec_query`
hands its worker thread a pointer to a struct on the caller's stack. If the
connect step is slow the caller times out and returns, and the worker, when it
finally finishes, calls `CloseHandle` on whatever value now sits in the dead
stack slot - in the audit's probes `0x0`, the default thread pool's completion
port `0x20`, or the current-thread pseudo-handle. `onnxruntime`'s import reaches
that query through `platform.system()`.

Each case runs a fresh child interpreter (`sys.executable`, this process's
environment), so this pytest process - which has long since called
`platform.system()` - is never the subject. The child, before anything calls
`platform.system()`, redirects four of `_wmi.pyd`'s import-address-table entries
(`CreatePipe`, `CreateThread`, `SetEvent`, `CloseHandle`) to ctypes callbacks
(contract C-3, re-derived here, not copied from `spikes/`):

- `CreatePipe` remembers the write end it returned to `exec_query`;
- `CreateThread` maps the new worker's thread id to that write end and opens a
  SYNCHRONIZE handle on the worker so the child can wait for it to finish;
- `SetEvent` on a worker holds the worker's *second* call (the connect event)
  for `hold_ms`, once - the stand-in for a slow `ConnectServer`;
- `CloseHandle` on a worker records the handle and its object type, queried
  *before* the close.

Then it imports `mangatl.detect.session` (which imports `onnxruntime`), waits at
most 5 s for every worker to finish, and prints one JSON line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="CPython's _wmi module and its worker thread exist on Windows"
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The connect-event hold of AC-1. Audit E8: >= 300 ms gave a foreign close in
# 21 of 21 runs on the `import onnxruntime` path.
_HOLD_MS = 400
# AC-1 / C-4: three fresh children, every one must be clean.
_CHILDREN = 3
# Generous but finite. One child measured ~2-3 s locally (see the story's
# handoff); CI's windows-latest runner is taken as ~4x slower, and the coverage
# gate adds its own overhead to the parent only.
_CHILD_TIMEOUT_S = 60.0

_CHILD = r'''
import ctypes
import ctypes.wintypes as wt
import json
import struct
import sys
import threading
import time

HOLD_S = int(sys.argv[1]) / 1000.0

import _wmi  # loaded first, so its import table exists before platform runs a query

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
k32.GetModuleHandleW.restype = ctypes.c_void_p
k32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
k32.VirtualProtect.restype = wt.BOOL
k32.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.GetCurrentThreadId.restype = wt.DWORD
k32.GetThreadId.restype = wt.DWORD
k32.GetThreadId.argtypes = [ctypes.c_void_p]
k32.OpenThread.restype = ctypes.c_void_p
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.WaitForSingleObject.restype = wt.DWORD
k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
ntdll.NtQueryObject.restype = ctypes.c_long
ntdll.NtQueryObject.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)
]

MAIN_TID = k32.GetCurrentThreadId()
SYNCHRONIZE = 0x00100000


def object_type(handle):
    """The kernel object type name of `handle`, or None if it names no object."""
    buf = ctypes.create_string_buffer(1024)
    got = ctypes.c_ulong(0)
    status = ntdll.NtQueryObject(handle, 2, buf, len(buf), ctypes.byref(got))
    if status < 0:
        return None
    length = struct.unpack_from("<H", buf.raw, 0)[0]
    pointer = struct.unpack_from("<Q", buf.raw, 8)[0]
    return ctypes.wstring_at(pointer, length // 2)


def iat_slots(base, dll_name, wanted):
    """Address of each wanted import's IAT slot in the module mapped at `base`."""
    read = ctypes.string_at
    nt = struct.unpack("<I", read(base + 0x3C, 4))[0]
    # PE32+ optional header: data directory 1 (imports) at offset 112 + 8.
    descriptor = base + struct.unpack("<I", read(base + nt + 24 + 120, 4))[0]
    slots = {}
    while True:
        lookup, _, _, name, thunks = struct.unpack("<IIIII", read(descriptor, 20))
        if name == 0:
            break
        if ctypes.string_at(base + name).decode().lower() == dll_name.lower():
            i = 0
            while True:
                entry = struct.unpack("<Q", read(base + lookup + 8 * i, 8))[0]
                if entry == 0:
                    break
                if not entry >> 63:
                    fn = ctypes.string_at(base + (entry & 0x7FFFFFFF) + 2).decode()
                    if fn in wanted:
                        slots[fn] = base + thunks + 8 * i
                i += 1
        descriptor += 20
    return slots


report = {
    "python": sys.version,
    "hold_ms": int(HOLD_S * 1000),
    "hooks_installed": False,
    "hooks_failure": None,
    "exec_query_calls": 0,
    "exec_query_errors": [],
    "held": False,
    "workers": {},
    "worker_closes": [],
    "workers_finished": None,
    "import_ok": False,
    "import_error": None,
    "system": None,
}
lock = threading.Lock()
pending_write_end = [None]
worker_waits = []
worker_set_events = [0]

U64 = ctypes.c_uint64
originals = {}


def on_create_pipe(read_ptr, write_ptr, attrs, size):
    ok = originals["CreatePipe"](read_ptr, write_ptr, attrs, size)
    if ok and write_ptr:
        pending_write_end[0] = U64.from_address(write_ptr).value
    return ok


def on_create_thread(attrs, stack, start, param, flags, tid_ptr):
    handle = originals["CreateThread"](attrs, stack, start, param, flags, tid_ptr)
    if handle:
        tid = k32.GetThreadId(handle)
        with lock:
            report["workers"][str(tid)] = pending_write_end[0]
        waitable = k32.OpenThread(SYNCHRONIZE, False, tid)
        if waitable:
            worker_waits.append(waitable)
    return handle


def on_set_event(handle):
    if k32.GetCurrentThreadId() != MAIN_TID:
        with lock:
            worker_set_events[0] += 1
            hold = worker_set_events[0] == 2 and HOLD_S > 0 and not report["held"]
            if hold:
                report["held"] = True
        if hold:
            time.sleep(HOLD_S)
    return originals["SetEvent"](handle)


def on_close_handle(handle):
    tid = k32.GetCurrentThreadId()
    if tid != MAIN_TID:
        kind = object_type(handle)
        closed = originals["CloseHandle"](handle)
        with lock:
            report["worker_closes"].append(
                {"tid": tid, "handle": handle, "type": kind, "closed": bool(closed)}
            )
        return closed
    return originals["CloseHandle"](handle)


PROTOS = {
    "CreatePipe": ctypes.WINFUNCTYPE(wt.BOOL, U64, U64, U64, wt.DWORD),
    "CreateThread": ctypes.WINFUNCTYPE(U64, U64, U64, U64, U64, wt.DWORD, U64),
    "SetEvent": ctypes.WINFUNCTYPE(wt.BOOL, U64),
    "CloseHandle": ctypes.WINFUNCTYPE(wt.BOOL, U64),
}
HOOKS = {
    "CreatePipe": on_create_pipe,
    "CreateThread": on_create_thread,
    "SetEvent": on_set_event,
    "CloseHandle": on_close_handle,
}
callbacks = []


def install():
    base = k32.GetModuleHandleW("_wmi.pyd")
    if not base:
        report["hooks_failure"] = "_wmi.pyd is not loaded"
        return False
    slots = iat_slots(base, "KERNEL32.dll", set(HOOKS))
    missing = sorted(set(HOOKS) - set(slots))
    if missing:
        report["hooks_failure"] = f"no KERNEL32 import slot for {missing}"
        return False
    for name, slot in slots.items():
        cell = U64.from_address(slot)
        originals[name] = PROTOS[name](cell.value)
        callback = PROTOS[name](HOOKS[name])
        callbacks.append(callback)
        target = ctypes.cast(callback, ctypes.c_void_p).value
        old = wt.DWORD(0)
        if not k32.VirtualProtect(slot, 8, 0x04, ctypes.byref(old)):
            report["hooks_failure"] = f"VirtualProtect refused the {name} slot"
            return False
        cell.value = target
        k32.VirtualProtect(slot, 8, old.value, ctypes.byref(old))
        if U64.from_address(slot).value != target:
            report["hooks_failure"] = f"the {name} slot did not take the redirect"
            return False
    return True


real_exec_query = _wmi.exec_query


def counting_exec_query(*args, **kwargs):
    report["exec_query_calls"] += 1
    try:
        return real_exec_query(*args, **kwargs)
    except OSError as error:
        report["exec_query_errors"].append(repr(error))
        raise


report["hooks_installed"] = install()
_wmi.exec_query = counting_exec_query

try:
    import mangatl.detect.session  # noqa: F401  (imports onnxruntime -> platform.system())

    report["import_ok"] = True
except BaseException as error:
    report["import_error"] = repr(error)

deadline = time.monotonic() + 5.0
finished = True
for waitable in list(worker_waits):
    left = max(0, int((deadline - time.monotonic()) * 1000))
    if k32.WaitForSingleObject(waitable, left) != 0:
        finished = False
report["workers_finished"] = finished

import platform

report["system"] = platform.system()
print("MT070-REPORT " + json.dumps(report), flush=True)
'''


def _run_child(hold_ms: int) -> dict[str, Any]:
    """Run one fresh child with the given connect-event hold; return its report."""
    done = subprocess.run(
        [sys.executable, "-c", _CHILD, str(hold_ms)],
        cwd=_REPO_ROOT,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_S,
        check=False,
    )
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("MT070-REPORT ")]
    assert done.returncode == 0 and len(lines) == 1, (
        f"the child interpreter did not report (exit {done.returncode})\n"
        f"stdout:\n{done.stdout}\nstderr:\n{done.stderr}"
    )
    report: dict[str, Any] = json.loads(lines[0].removeprefix("MT070-REPORT "))
    return report


def _foreign_closes(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Worker closes of anything but the pipe write end `exec_query` made for that worker."""
    own = report["workers"]
    return [c for c in report["worker_closes"] if own.get(str(c["tid"])) != c["handle"]]


def _describe(close: dict[str, Any]) -> str:
    outcome = "closed" if close["closed"] else "close failed"
    kind = close["type"] or "no object"
    return f"{close['handle']:#x} ({kind}, {outcome}) on thread {close['tid']}"


def _vacuity_problems(report: dict[str, Any]) -> list[str]:
    """Why this child's clean result would prove nothing; empty when it is meaningful."""
    problems: list[str] = []
    if not report["hooks_installed"]:
        problems.append(f"hooks did not install: {report['hooks_failure']}")
    worker_seen = bool(report["workers"])
    if worker_seen:
        if not report["held"]:
            problems.append("a worker ran but its connect event was never held")
        if not report["exec_query_errors"]:
            problems.append("a worker was held but no exec_query caller timed out")
        if not report["workers_finished"]:
            problems.append("a worker did not finish within 5 s")
    elif report["exec_query_calls"] != 0:
        problems.append(
            f"exec_query ran {report['exec_query_calls']} time(s) but no worker was observed"
        )
    return problems


def test_an_abandoned_wmi_worker_closes_no_handle_it_did_not_create() -> None:
    """AC-1: with the connect step held 400 ms, the worker closes only its own pipe end."""
    failures: list[str] = []
    for child in range(_CHILDREN):
        report = _run_child(_HOLD_MS)
        vacuous = _vacuity_problems(report)
        if vacuous:
            failures.append(f"child {child}: not a valid observation: {'; '.join(vacuous)}")
        if not report["import_ok"]:
            failures.append(f"child {child}: the import failed: {report['import_error']}")
        foreign = _foreign_closes(report)
        if foreign:
            failures.append(
                f"child {child}: the abandoned worker closed handle(s) it did not create: "
                + ", ".join(_describe(c) for c in foreign)
                + f" (its own pipe ends: {report['workers']})"
            )
    assert not failures, "\n".join(failures)


def test_an_unheld_wmi_query_lets_the_import_succeed_and_reports_windows() -> None:
    """AC-2, the negative control: no hold, the import works and platform says Windows."""
    report = _run_child(0)
    assert report["hooks_installed"], f"hooks did not install: {report['hooks_failure']}"
    assert report["import_ok"], f"importing mangatl.detect.session failed: {report['import_error']}"
    assert report["system"] == "Windows", f"platform.system() returned {report['system']!r}"
    assert not report["held"], "the control held the worker; it must not"
