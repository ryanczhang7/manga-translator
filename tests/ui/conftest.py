"""MT-072: every window `mangatl.app.build_window` returns in a UI test is closed
at teardown, and every Project `mangatl.app` opened is closed with it.

`mangatl.app.open_folder` hands the project to the `Workspace` it builds and
closes it only when that window's `closed` signal fires, which happens only from
`Workspace.closeEvent` (MT-054 C-4). A test that builds a Workspace and lets it
die without `close()` leaves the sqlite connection open - and `qtbot.addWidget`
does not prevent that: pytest-qt keeps a weakref only, the test function's locals
are released when it returns, and by the time pytest-qt closes its widgets the
parentless window is already destroyed and its weakref dead.

Not autouse: only the files that opt in with
``pytestmark = pytest.mark.usefixtures("every_opened_project_is_closed",
"every_built_window_is_closed")`` use them (MT-072, `## Contract` - other
`build_window` callers are out of scope).

**Teardown order, as pytest and pytest-qt run it** (verified with
``--setup-show`` and a probe, MT-072 `## Handoff`):

1. the test function returns; its locals are released;
2. pytest-qt's ``pytest_runtest_teardown`` hook closes every widget registered
   with ``qtbot.addWidget`` whose weakref is still alive - BEFORE any fixture is
   torn down;
3. fixtures are torn down, each before the fixtures it requested:
   ``every_built_window_is_closed`` first, then
   ``every_opened_project_is_closed``.

**The close mechanism, `every_built_window_is_closed`.** One for both files: it
wraps `mangatl.app.build_window` and holds every window it returns in a list, so
step 1 releases nothing - each window is still alive at step 2, where pytest-qt
closes the ones it was given, and at step 3, where this fixture closes every one
of them itself (a second `close()` only re-flushes, and the explicit close covers
a window nobody passed to qtbot). `_build`, `_built`, `_workspace_with_rows` and
the windows `main` builds all go through it, with no `close()` in a test body.

**AC-2's check, `every_opened_project_is_closed`.** It records every Project
`mangatl.app.open_project` returns and, at its teardown - after the mechanism's,
because the mechanism requests it - asserts each one's connection refuses
`SELECT 1` with `sqlite3.ProgrammingError`. It does not collect garbage or watch
for destruction: holding the Project does not keep its window alive, so a window
that died unclosed leaves an open Project behind and the check fails on every
run. A failure is reported as an ERROR at teardown of the test that opened it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QMainWindow

from mangatl import app as app_module
from mangatl.store.project import Project

#: Where the UI tests' bundled models live: nowhere (MT-024).
_NO_BUNDLE = "no bundled models here"


def bundle_models_at(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    """`bundled_models_dir()` answers `directory` for `mangatl.app`, at both
    names it could reach it by - the name `mangatl.app` binds and the module
    `mangatl.app_paths` (MT-024 C-3, C-5). `raising=False`: neither exists
    before MT-024's GREEN."""
    monkeypatch.setattr("mangatl.app.bundled_models_dir", lambda: directory, raising=False)
    monkeypatch.setattr("mangatl.app_paths.bundled_models_dir", lambda: directory, raising=False)


@pytest.fixture(autouse=True)
def original_check_bundled_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> object:
    """MT-024 suite isolation, for every UI test.

    Once a developer has run `packaging/fetch_models.py`, a real
    `packaging/models/` holds 728 MB of weights. Without this, every `main()`
    in the suite would hash all of it at startup (`check_bundled_models`, C-6),
    and every real `resolve_models()` would answer that directory where the
    tests expect `None` (AC-9) - green on CI, red on the developer's machine.

    So `mangatl.app.check_bundled_models` is replaced with `lambda: None` and
    `bundled_models_dir()` points at a directory that does not exist.
    `test_app_startup_check.py` overrides either per test. The original
    function (or `None`, before GREEN) is the fixture's value, for the tests
    that exercise the real one."""
    original = getattr(app_module, "check_bundled_models", None)
    monkeypatch.setattr(app_module, "check_bundled_models", lambda: None, raising=False)
    bundle_models_at(monkeypatch, tmp_path_factory.mktemp("bundle") / _NO_BUNDLE)
    return original


@pytest.fixture
def every_opened_project_is_closed(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Project]]:
    """AC-2: every Project `mangatl.app` opened during the test is closed once
    the test's windows have been torn down. Yields the list it records into.

    The spy is installed before the test body runs, so a test that wraps
    `app_module.open_project` itself (`_capture_projects`) wraps this spy, and
    both see every project."""
    opened: list[Project] = []
    real = app_module.open_project

    def record(project_dir: Path) -> Project:
        project = real(project_dir)
        opened.append(project)
        return project

    monkeypatch.setattr(app_module, "open_project", record)
    yield opened

    still_open = []
    for project in opened:
        try:
            project.select("SELECT 1")
        except sqlite3.ProgrammingError:
            continue
        still_open.append(project)
    assert still_open == [], (
        f"{len(still_open)} of {len(opened)} project(s) mangatl.app opened in this test"
        " are still open after teardown: a window build_window returned was never"
        " closed, so its `closed` signal never closed its project"
    )


@pytest.fixture
def every_built_window_is_closed(
    every_opened_project_is_closed: list[Project],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[QMainWindow]]:
    """The close mechanism: every window `mangatl.app.build_window` returns
    during the test is held here, strongly, and closed at teardown.

    The strong reference is the point - it keeps each window alive past the
    test body, so `close()` reaches a live window and its `closeEvent` emits
    `closed`. Closing at teardown, never earlier, keeps
    `test_the_project_stays_open_while_the_window_is_open` meaningful.

    It requests `every_opened_project_is_closed`, so pytest tears it down
    FIRST: the windows are closed before the check reads the projects. Installed
    before the test body, so `_capture_windows` (which wraps whatever
    `app_module.build_window` is) wraps this, and `main`'s windows are held too."""
    built: list[QMainWindow] = []
    real = app_module.build_window

    def hold(arguments: Sequence[str], **options: Any) -> QMainWindow:
        window = real(arguments, **options)
        built.append(window)
        return window

    monkeypatch.setattr(app_module, "build_window", hold)
    yield built

    for window in built:
        window.close()
    built.clear()
