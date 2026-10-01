"""MT-061 AC-1 and C-1: the app applies its packaged theme once, before any window.

**AC-1 (mechanical, pinned exactly).** `mangatl.app.main` is run in process
with a recording stand-in for `QApplication` (C-2): only one real
`QApplication` exists per process and qtbot made it, and a real `exec()`
blocks. The stand-in records every `setStyleSheet` call into one event log,
and `build_window` is wrapped to record itself into the same log, so "exactly
once", "the packaged bytes" and "before `build_window`" are each one assertion
over that log. The three launch shapes are the three AC-1 names: no argument,
a folder of pages with no project, a folder with a project.

The expected text is the **package resource** `mangatl.ui/theme.qss`, read
here through `importlib.resources` as UTF-8 - never `docs/wiki/design/` and
never a path built from the source tree (tokens.md section 12.1).

**C-1 (the loader).** `mangatl.ui.stylesheet` does not exist in RED. It is
imported *inside* each loader test, so its absence fails those tests one by
one instead of failing this file's collection - which would take AC-1's
tests, and every other file in the run, down with it.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QMainWindow

from mangatl import app as app_module
from mangatl.domain.page import Chapter, Page
from mangatl.store.project import create_project
from mangatl.ui import tokens_gen
from mangatl.ui.main_window import MainWindow
from mangatl.ui.workspace import Workspace

#: Natural order differs from text order, so the summary path is the real one.
PAGES = ("page 10.png", "page 11.png", "page 9.png")


def _packaged_theme_bytes() -> bytes:
    """The shipped artefact, as the package carries it."""
    return files("mangatl.ui").joinpath("theme.qss").read_bytes()


def _packaged_theme() -> str:
    return _packaged_theme_bytes().decode("utf-8")


def _png() -> bytes:
    image = QImage(QSize(60, 80), QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def _pages_folder(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir()
    png = _png()
    for page in PAGES:
        (folder / page).write_bytes(png)
    return folder


def _project_folder(root: Path) -> Path:
    """A chapter folder whose sibling `.mtproj` exists, closed."""
    folder = _pages_folder(root, "with project")
    chapter = Chapter(
        source_dir=folder,
        pages=tuple(
            Page(ordinal=i, filename=name, width=60, height=80, sha256=f"{i}" * 64)
            for i, name in enumerate(PAGES)
        ),
    )
    with create_project(chapter, root / "with project.mtproj"):
        pass
    return folder


#: AC-1's three launch shapes: argv after the program name, and the window
#: type `build_window` must return for it (so a shape cannot silently become
#: another one).
LAUNCHES: dict[str, tuple[Callable[[Path], list[str]], type[QMainWindow]]] = {
    "no argument": (lambda root: [], MainWindow),
    "a folder of pages with no project": (
        lambda root: [str(_pages_folder(root, "no project"))],
        MainWindow,
    ),
    "a folder with a project": (lambda root: [str(_project_folder(root))], Workspace),
}


def _run_main(qtbot, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> list[tuple[str, object]]:  # type: ignore[no-untyped-def]
    """`main(argv)` with the recording stand-in; returns the event log."""
    events: list[tuple[str, object]] = []
    built: list[QMainWindow] = []
    real_build = app_module.build_window

    def recording_build(arguments: list[str]) -> QMainWindow:
        events.append(("build_window", list(arguments)))
        window = real_build(arguments)
        qtbot.addWidget(window)
        built.append(window)
        return window

    class _RecordingQApplication:
        def __init__(self, argv: list[str]) -> None:
            events.append(("QApplication", list(argv)))

        def setStyleSheet(self, sheet: str) -> None:
            events.append(("setStyleSheet", sheet))

        def exec(self) -> int:
            events.append(("exec", None))
            for window in built:
                window.close()  # a Workspace closes its project on close
            return 0

    monkeypatch.setattr(app_module, "build_window", recording_build)
    monkeypatch.setattr(app_module, "QApplication", _RecordingQApplication)
    assert app_module.main(argv) == 0
    assert len(built) == 1, f"main built {len(built)} windows"
    return events


@pytest.mark.parametrize("launch", list(LAUNCHES))
def test_main_sets_the_application_stylesheet_exactly_once(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launch: str,
) -> None:
    arguments, _ = LAUNCHES[launch]
    events = _run_main(qtbot, monkeypatch, ["mangatl", *arguments(tmp_path)])

    calls = [name for name, _ in events if name == "setStyleSheet"]
    assert len(calls) == 1, (
        f"launched with {launch}, the application stylesheet was set {len(calls)} times,"
        f" not once; events: {[name for name, _ in events]}"
    )


@pytest.mark.parametrize("launch", list(LAUNCHES))
def test_main_sets_the_packaged_theme_byte_for_byte(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launch: str,
) -> None:
    arguments, _ = LAUNCHES[launch]
    events = _run_main(qtbot, monkeypatch, ["mangatl", *arguments(tmp_path)])

    sheets = [value for name, value in events if name == "setStyleSheet"]
    expected = _packaged_theme_bytes()
    assert sheets, f"launched with {launch}, the application stylesheet was never set"
    for sheet in sheets:
        assert isinstance(sheet, str)
        assert sheet.encode("utf-8") == expected, (
            f"launched with {launch}, the sheet set ({len(sheet)} chars) is not the packaged"
            f" mangatl.ui/theme.qss ({len(expected)} bytes)"
        )


@pytest.mark.parametrize("launch", list(LAUNCHES))
def test_main_sets_the_stylesheet_before_any_window_is_built(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launch: str,
) -> None:
    arguments, _ = LAUNCHES[launch]
    events = _run_main(qtbot, monkeypatch, ["mangatl", *arguments(tmp_path)])

    names = [name for name, _ in events]
    assert "setStyleSheet" in names, f"launched with {launch}, no stylesheet was set: {names}"
    assert names.index("QApplication") < names.index("setStyleSheet"), names
    assert names.index("setStyleSheet") < names.index("build_window"), (
        f"launched with {launch}, a window was built before the theme was set: {names}"
    )
    assert names[-1] == "exec", names


@pytest.mark.parametrize("launch", list(LAUNCHES))
def test_each_launch_shape_builds_the_window_it_names(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    launch: str,
) -> None:
    """Fixture check: the three shapes really are the three AC-1 names. It
    passes on arrival - `build_window` is MT-054/MT-057's - and is here so a
    fixture that drifted (a project that failed to open, say) cannot quietly
    test one shape three times."""
    arguments, window_type = LAUNCHES[launch]
    window = app_module.build_window(arguments(tmp_path))
    qtbot.addWidget(window)
    assert type(window) is window_type, f"{launch} built a {type(window).__name__}"
    window.close()


# =============================================================================
# C-1: the loader, `mangatl.ui.stylesheet`
# =============================================================================


def _loader():  # type: ignore[no-untyped-def]
    return importlib.import_module("mangatl.ui.stylesheet")


def test_the_loader_names_the_packaged_theme_resource() -> None:
    assert _loader().THEME_RESOURCE == "theme.qss"


def test_the_base_stylesheet_is_the_packaged_theme_read_as_utf8() -> None:
    sheet = _loader().base_stylesheet()

    assert isinstance(sheet, str)
    assert sheet.encode("utf-8") == _packaged_theme_bytes()
    assert sheet == _packaged_theme()


def test_applying_the_base_stylesheet_sets_it_on_the_application_and_does_nothing_else() -> None:
    """A stand-in with only `setStyleSheet`: touching anything else on the
    application raises AttributeError."""
    loader = _loader()
    sheets: list[str] = []

    class _OnlySetStyleSheet:
        __slots__ = ()

        def setStyleSheet(self, sheet: str) -> None:
            sheets.append(sheet)

    result = loader.apply_base_stylesheet(_OnlySetStyleSheet())

    assert result is None
    assert sheets == [loader.base_stylesheet()]
    assert sheets[0].encode("utf-8") == _packaged_theme_bytes()
