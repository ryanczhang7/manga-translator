"""Suite-wide isolation from the machine the tests run on.

MT-027 (`## Contract`, "Test isolation"): `bake_chapter` and `preview_bake` now
read `%APPDATA%\\mangatl\\settings.json` (`mangatl.app_paths.settings_path`), so a
developer whose real settings file names a lettering font would bake every
existing bake test in that font - and `tests/core/test_bake.py`'s pixel and
`BakeReport` equality assertions would fail on that machine alone, or worse,
pass on it for the wrong reason.

So every test, in every folder, runs with `APPDATA` pointed at a fresh empty
directory of its own. It is `tmp_path_factory.mktemp`, not `tmp_path`: a test's
own `tmp_path` stays exactly as empty as it was before this fixture existed,
which several suites assert on (`world.contents(...)`, `snapshot(...)`).

`appdata` hands the same directory to a test that wants to write a settings
file into it (`tests/core/_font_fixtures.write_settings`).
**Qt's last words reach the gate log (MT-138, after MT-112 `## Notes` PO-5).**
Three `unit` runs aborted with `Fatal Python error: Aborted` and no Qt message,
and pytest-qt's capture is why a Qt message could not have shown: its handler
stores each message in a per-test list printed only in a failure report, which
an aborting process never writes, and Qt's default handler on Windows writes to
the debugger, not to a redirected stderr. So every `QtFatalMsg` and
`QtCriticalMsg` is also written, as it happens and in one `os.write`, to the
process's real stderr - the fd 2 of `pytest_configure`, before pytest's capture
redirects it, as `_pytest/faulthandler.py` does - as one line
`qt-message: <FATAL|CRITICAL> in <nodeid or "no test">: <message>`. Two layers:
`qInstallMessageHandler(_tee)` holds the handler slot outside a test, and a
class-level wrap of pytest-qt's `_QtMessageCapture._handle_with_context` covers
the span setup -> teardown, where pytest-qt's own handler is installed and does
not call the previous one. pytest-qt's records and reports are unchanged.
Warnings are not teed (MT-138 PO-2).
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import Any

import pytest
import pytestqt.logging
from PySide6 import QtCore

_LAST_WORDS_FD: int | None = None
_CURRENT_NODEID: str | None = None

_TEED_LEVELS = {
    QtCore.QtMsgType.QtFatalMsg: "FATAL",
    QtCore.QtMsgType.QtCriticalMsg: "CRITICAL",
}


def _tee(msg_type: Any, context: Any, message: Any) -> None:
    """Write a fatal or critical Qt message to the real stderr; never raise."""
    try:
        level = _TEED_LEVELS.get(msg_type)
        fd = _LAST_WORDS_FD
        if level is None or fd is None:
            return
        if isinstance(message, bytes):
            message = message.decode("utf-8", "replace")
        where = _CURRENT_NODEID if _CURRENT_NODEID is not None else "no test"
        line = f"qt-message: {level} in {where}: {message}\n"
        os.write(fd, line.encode("utf-8", errors="replace"))
    except Exception:
        # An exception inside a Qt message handler is undefined behaviour, and this
        # handler runs inside the thing being diagnosed: swallow everything.
        pass


# Layer 2. pytest-qt 4.5.0 (pinned in uv.lock) installs this bound method for
# every test's setup -> teardown and does not forward to the previous handler.
# Fail the whole run loudly if a pytest-qt bump renames it.
assert hasattr(pytestqt.logging._QtMessageCapture, "_handle_with_context"), (
    "pytest-qt no longer has _QtMessageCapture._handle_with_context; MT-138's tee"
    " in tests/conftest.py must be re-derived against the new version"
)
_original_handle_with_context = pytestqt.logging._QtMessageCapture._handle_with_context


def _handle_with_context_and_tee(self: Any, msg_type: Any, context: Any, message: Any) -> None:
    _tee(msg_type, context, message)
    _original_handle_with_context(self, msg_type, context, message)


pytestqt.logging._QtMessageCapture._handle_with_context = _handle_with_context_and_tee  # type: ignore[method-assign]


def pytest_configure(config: pytest.Config) -> None:
    """Keep the real stderr's fd, and hold Qt's handler slot outside a test."""
    global _LAST_WORDS_FD
    try:
        fileno = sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):
        fileno = sys.__stderr__.fileno() if sys.__stderr__ is not None else 2
    _LAST_WORDS_FD = os.dup(fileno)
    QtCore.qInstallMessageHandler(_tee)


def pytest_unconfigure(config: pytest.Config) -> None:
    global _LAST_WORDS_FD
    fd, _LAST_WORDS_FD = _LAST_WORDS_FD, None
    if fd is not None:
        with contextlib.suppress(OSError):
            os.close(fd)


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    global _CURRENT_NODEID
    _CURRENT_NODEID = nodeid


def pytest_runtest_logfinish(nodeid: str, location: tuple[str, int | None, str]) -> None:
    global _CURRENT_NODEID
    _CURRENT_NODEID = None


@pytest.fixture(autouse=True)
def appdata(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`APPDATA` for this test: a new, empty directory under pytest's basetemp."""
    directory = tmp_path_factory.mktemp("appdata")
    monkeypatch.setenv("APPDATA", str(directory))
    return directory
