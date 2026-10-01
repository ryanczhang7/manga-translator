"""MT-054: the app opens a chapter in the review workspace.

`mangatl.app.build_window(arguments)` is the seam (C-1): it returns the window,
not shown, for the command line without the program name. `main` is a shell
over it, driven here with a fake `QApplication` whose `exec()` runs a test
callback - only one real `QApplication` exists per process, and qtbot made it.

Everything here is mechanical (story, "Oracle partition"): no settled numbers,
no invented metrics.

- **AC-1 / C-2 case 4** - a `Workspace`, the strip listing the page filenames in
  ordinal order, row 0 current, the canvas LOADED and the column holding page
  0's rows. The two pages have different filenames *and* different region
  counts (5 against 1), and the filenames are in reverse alphabetical order, so
  "the first page" cannot be confused with "some page" or "the first by name".
- **AC-2** - a real round trip through `main`: edit through the editor's keys,
  `Enter`, close at once (inside the 500 ms debounce, so only C-4's
  flush-then-close saves it), read the project file with a plain `sqlite3`
  connection, then `main` again with the same folder.
- **AC-3 / C-3** - superseded by MT-057 (its PO-3): a folder with no project
  is no longer a notice naming `mangatl-run`; it is read as a chapter, and
  `mangatl <folder>` shows the intake window with the summary or an intake
  error. The two AC-3 tests below are MT-057's rewrites (its `## Contract`,
  "Callers and tests this story rewrites"): an undecodable page is its AC-6
  error; a bare `.mtproj` with no `project.db`, over a folder with no page
  images, is its AC-2 error. The texts are spelled out HERE, never read back
  from the app. "Not silently" is a snapshot of every path under `tmp_path`.
- **AC-4 / C-2 case 1** - the no-argument `MainWindow`. MT-055 changed it
  deliberately (MT-055 PO-1): it is now the folder intake, pinned here by
  `_assert_intake_window` and in full in `test_folder_intake.py`.
- **C-4** - `Workspace.closed`, once per close, after the flush; and the
  window `build_window` made closes its project.
- **C-5** - `MainWindow(notice=...)`.

**`<` in a folder name.** The CI gates run on `windows-latest`, where `<` cannot
appear in a file name at all (WinError 123), so the AC-3 folder that must exist
carries a space and an `&` only. C-5's "a `<` is not parsed as markup" is pinned
on case 2 (a folder that does not exist, so it is never created) whose name holds
`<b>`, on case 6 (`USAGE_NOTICE` itself contains `<folder>`), and directly on
`MainWindow(notice=...)`.

**Timing.** Nothing here waits real time: the only waits are for window
activation and focus, as the MT-017 tests do. No `pytest-timeout` exists.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

from mangatl import app as app_module
from mangatl.domain.line import OcrResult
from mangatl.domain.page import Chapter, Page
from mangatl.domain.region import RawRegion
from mangatl.store.project import (
    SCHEMA_VERSION,
    Project,
    SchemaTooNew,
    create_project,
    open_project,
)
from mangatl.ui import main_window as main_window_module
from mangatl.ui import tokens_gen
from mangatl.ui.canvas import EMPTY, LOADED
from mangatl.ui.main_window import WINDOW_TITLE, MainWindow
from mangatl.ui.workspace import Workspace

# --- The chapter on disk -----------------------------------------------------------
#: Ordinal order, deliberately NOT alphabetical: a strip sorted by name fails.
PAGES = ("b-first.png", "a-second.png")
PAGE = QSize(600, 800)
#: Page 0 has five regions, page 1 one: the column's row count tells them apart.
PAGE0_OCR = (("一", False), ("二", False), ("三", False), ("四", False), ("", True))
PAGE0_PROPOSED = {0: "Hello.", 1: "Fine.", 2: "Wait!", 3: "Coffee."}
PAGE1_OCR = (("五", False),)
PAGE1_PROPOSED = {0: "Next page."}

#: What AC-2 types into page 0's first row.
NEW_TEXT = "Hi there"

# --- C-3, spelled out (never read back from the constants) ---------------------------
EDITED_GLYPH = "✎"  # ✎, components.md §5 / MT-017 C-8


def _no_pages(folder: Path) -> str:
    """MT-057 AC-2's headline, the folder resolved."""
    return f"No page images in {folder}. This tool reads .png and .jpg files."


def _undecodable(filename: str) -> str:
    """MT-057 AC-6's sentence (the Lead Designer's)."""
    return (
        f"{filename} could not be opened as a page image."
        " Remove or replace it, then choose the folder again."
    )


def _no_folder_notice(folder: Path) -> str:
    return f"No such folder: {folder}"


USAGE_TEXT = "mangatl opens one chapter folder:  mangatl <folder>"

SELECTABLE = (
    Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
)


# --- Helpers -------------------------------------------------------------------------


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _png(size: QSize) -> bytes:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


@pytest.fixture(scope="module")
def page_png() -> bytes:
    return _png(PAGE)


@pytest.fixture(scope="module")
def mask_png() -> bytes:
    return _png(QSize(4, 4))


def _ring(i: int) -> tuple[tuple[int, int], ...]:
    x, y = 60, 60 + 140 * i
    return ((x, y), (x + 200, y), (x + 200, y + 100), (x, y + 100), (x, y))


def _store(
    project: Project,
    ordinal: int,
    ocr: tuple[tuple[str, bool], ...],
    proposed: dict[int, str],
    mask: bytes,
) -> None:
    project.write_regions(
        ordinal,
        [
            RawRegion(polygon=_ring(i), mask=mask, confidence=0.9, kind="bubble")
            for i in range(len(ocr))
        ],
    )
    project.write_lines(ordinal, [OcrResult(ja, ocr_empty=empty) for ja, empty in ocr])
    project.write_proposed(ordinal, proposed)


@pytest.fixture
def source(tmp_path: Path, page_png: bytes, mask_png: bytes) -> Path:
    """A chapter folder whose sibling `.mtproj` project exists, CLOSED.

    The folder name carries a space: C-3's quoting is for exactly that."""
    folder = tmp_path / "my chapter"
    folder.mkdir()
    for name in PAGES:
        (folder / name).write_bytes(page_png)
    chapter = Chapter(
        source_dir=folder,
        pages=tuple(
            Page(
                ordinal=i,
                filename=name,
                width=PAGE.width(),
                height=PAGE.height(),
                sha256=f"{i}" * 64,
            )
            for i, name in enumerate(PAGES)
        ),
    )
    with create_project(chapter, tmp_path / "my chapter.mtproj") as project:
        _store(project, 0, PAGE0_OCR, PAGE0_PROPOSED, mask_png)
        _store(project, 1, PAGE1_OCR, PAGE1_PROPOSED, mask_png)
    return folder


def _project_file(folder: Path) -> Path:
    return folder.with_name(folder.name + ".mtproj") / "project.db"


def _on_disk(folder: Path, ordinal: int) -> list[tuple[Any, Any]]:
    """`(final_en, status)` per line of a page, read by a separate connection."""
    connection = sqlite3.connect(_project_file(folder))
    try:
        return list(
            connection.execute(
                "SELECT line.final_en, line.status"
                " FROM line JOIN region ON region.id = line.region_id"
                " JOIN page ON page.id = region.page_id"
                " WHERE page.ordinal = ? ORDER BY region.reading_index",
                (ordinal,),
            )
        )
    finally:
        connection.close()


def _tree(root: Path) -> list[Path]:
    return sorted(root.rglob("*"))


def _build(qtbot, arguments: list[str]) -> QMainWindow:  # type: ignore[no-untyped-def]
    window = app_module.build_window(arguments)
    qtbot.addWidget(window)
    return window


def _capture_projects(monkeypatch: pytest.MonkeyPatch) -> list[Project]:
    """Every `Project` `mangatl.app` opens (C-1 RED amendment: `open_project`
    is a name in `mangatl.app`'s namespace, called through it)."""
    opened: list[Project] = []
    real = app_module.open_project

    def capture(project_dir: Path) -> Project:
        project = real(project_dir)
        opened.append(project)
        return project

    monkeypatch.setattr(app_module, "open_project", capture)
    return opened


def _capture_windows(qtbot, monkeypatch: pytest.MonkeyPatch) -> list[QMainWindow]:  # type: ignore[no-untyped-def]
    """Every window `main` builds, through the real `build_window`."""
    built: list[QMainWindow] = []
    real = app_module.build_window

    def capture(arguments: list[str]) -> QMainWindow:
        window = real(arguments)
        qtbot.addWidget(window)
        built.append(window)
        return window

    monkeypatch.setattr(app_module, "build_window", capture)
    return built


def _fake_qapplication(
    monkeypatch: pytest.MonkeyPatch, on_exec: Callable[[], int]
) -> list[list[str]]:
    """Replace `QApplication` in `mangatl.app` with one whose `exec()` runs
    `on_exec`. Returns the argv each construction received."""
    argvs: list[list[str]] = []

    class _FakeQApplication:
        def __init__(self, argv: list[str]) -> None:
            argvs.append(list(argv))
            #: Every sheet `main` sets (MT-061 C-2: it applies the theme first).
            self.sheets: list[str] = []

        def setStyleSheet(self, sheet: str) -> None:
            self.sheets.append(sheet)

        def exec(self) -> int:
            return on_exec()

    monkeypatch.setattr(app_module, "QApplication", _FakeQApplication)
    return argvs


def _activate(qtbot, window: QWidget) -> None:  # type: ignore[no-untyped-def]
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()


def _focus(qtbot, widget: QWidget) -> None:  # type: ignore[no-untyped-def]
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(widget.hasFocus)
    _settle()


def _notice(window: QMainWindow) -> QLabel:
    central = window.centralWidget()
    assert isinstance(central, QLabel), f"central widget is {type(central).__name__}"
    return central


def _assert_notice_label(label: QLabel, text: str) -> None:
    """C-5: the whole window content, readable, copyable, plain text."""
    assert label.objectName() == "notice"
    assert label.text() == text
    assert label.accessibleName() == text
    assert label.wordWrap()
    assert label.textInteractionFlags() & SELECTABLE == SELECTABLE
    assert label.textFormat() == Qt.TextFormat.PlainText


def _assert_intake_window(window: QMainWindow) -> None:
    """AC-4 as MT-055 changed it (MT-055 AC-1, C-2): the no-argument window is
    the folder intake in its empty state, with no notice. Imported here, not at
    module level, so that MT-054's other tests in this file keep running while
    `mangatl.ui.intake` does not exist."""
    from mangatl.ui.intake import FolderDropTarget

    assert type(window) is MainWindow
    assert window.windowTitle() == WINDOW_TITLE
    central = window.centralWidget()
    assert isinstance(central, FolderDropTarget), f"central widget is {type(central).__name__}"
    assert central.objectName() == "folder-drop-target"
    assert central.state == "empty"
    headline = central.findChild(QLabel, "headline")
    assert headline is not None
    assert headline.text() == "Drop a chapter folder here"
    assert window.findChild(QObject, "notice") is None


# =============================================================================
# AC-4 / C-2 case 1: no argument, the folder intake (MT-055)
# =============================================================================


def test_no_argument_builds_the_folder_intake_window(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _build(qtbot, [])

    _assert_intake_window(window)


def test_the_window_is_returned_not_shown(qtbot, source: Path, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """C-1: `build_window` never shows; `main` does."""
    for arguments in ([], [str(source)], [str(tmp_path / "absent")], ["a", "b"]):
        window = _build(qtbot, arguments)
        assert not window.isVisible(), f"build_window({arguments!r}) showed its window"


def test_launched_with_no_argument_the_app_shows_the_folder_intake(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """AC-4 through `main`: argv is the program name only."""
    built = _capture_windows(qtbot, monkeypatch)
    seen: list[bool] = []

    def on_exec() -> int:
        seen.append(built[-1].isVisible())
        return 3

    argvs = _fake_qapplication(monkeypatch, on_exec)

    assert app_module.main(["mangatl"]) == 3
    assert argvs == [["mangatl"]]
    assert len(built) == 1
    _assert_intake_window(built[0])
    assert seen == [True], "main did not show the window before exec"


# =============================================================================
# AC-1 / C-2 case 4: a folder with a project opens the review workspace
# =============================================================================


def test_a_folder_with_a_project_opens_the_review_workspace(qtbot, source: Path) -> None:  # type: ignore[no-untyped-def]
    window = _build(qtbot, [str(source)])

    assert isinstance(window, Workspace)


def test_the_chapters_pages_are_listed_by_filename_in_ordinal_order(qtbot, source: Path) -> None:  # type: ignore[no-untyped-def]
    window = _build(qtbot, [str(source)])
    assert isinstance(window, Workspace)
    strip = window.page_strip

    assert [strip.item(i).text() for i in range(strip.count())] == list(PAGES)


def test_the_first_page_is_current_and_shown_with_its_own_rows(qtbot, source: Path) -> None:  # type: ignore[no-untyped-def]
    """D-1's target: without `setCurrentRow(0)` the row is -1 and the canvas
    EMPTY. Page 0 has 5 regions and page 1 has 1, so the row count is page 0's."""
    window = _build(qtbot, [str(source)])
    assert isinstance(window, Workspace)

    assert window.page_strip.currentRow() == 0
    assert window.page_canvas.state() == LOADED, f"canvas is {window.page_canvas.state()!r}"
    assert window.page_canvas.state() != EMPTY
    assert window.translation_column.list.count() == len(PAGE0_OCR)
    assert [window.translation_column.row(i).editor.text() for i in range(len(PAGE0_OCR) - 1)] == [
        PAGE0_PROPOSED[i] for i in range(len(PAGE0_OCR) - 1)
    ]


def test_a_relative_folder_argument_is_resolved(qtbot, source: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(source.parent)

    window = _build(qtbot, [source.name])

    assert isinstance(window, Workspace)
    assert window.page_strip.currentRow() == 0


# =============================================================================
# AC-2: an edit survives closing the app and launching it again
# =============================================================================


def _edit_first_line_and_close_at_once(qtbot, window: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    """Every act through the editor's keys; `close()` right after `Enter`, with
    no event processing between - inside the 500 ms debounce."""
    assert isinstance(window, Workspace), f"main built a {type(window).__name__}"
    assert window.isVisible(), "main did not show the window before exec"
    _activate(qtbot, window)
    editor = window.translation_column.row(0).editor
    _focus(qtbot, editor)
    editor.selectAll()
    QTest.keyClicks(editor, NEW_TEXT)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    window.close()


def test_an_edit_survives_closing_the_app_and_launching_it_again(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
) -> None:
    """EPIC-05's done-when, end to end through `mangatl.app.main`."""
    built = _capture_windows(qtbot, monkeypatch)
    reopened: list[tuple[str, str, str, str]] = []

    def first_launch() -> int:
        _edit_first_line_and_close_at_once(qtbot, built[-1])
        return 0

    argvs = _fake_qapplication(monkeypatch, first_launch)
    assert app_module.main(["mangatl", str(source)]) == 0
    assert argvs == [["mangatl", str(source)]]

    assert _on_disk(source, 0)[0] == (NEW_TEXT, "edited")

    def second_launch() -> int:
        window = built[-1]
        assert isinstance(window, Workspace), f"second launch built a {type(window).__name__}"
        row = window.translation_column.row(0)
        item = window.translation_column.list.item(0)
        reopened.append(
            (
                row.editor.text(),
                row.editor.status,
                row.gutter.text(),
                item.data(Qt.ItemDataRole.AccessibleTextRole),
            )
        )
        window.close()
        return 0

    _fake_qapplication(monkeypatch, second_launch)
    assert app_module.main(["mangatl", str(source)]) == 0

    assert len(built) == 2
    assert built[1] is not built[0]
    assert reopened == [
        (
            NEW_TEXT,
            "edited",
            EDITED_GLYPH,
            f"Bubble 1 of 5. Japanese: 一. English: {NEW_TEXT}. edited.",
        )
    ]


# =============================================================================
# C-4: closing the window closes the project, after the pending save
# =============================================================================


def test_closing_the_app_window_closes_its_project(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
) -> None:
    """C-4 / PO-4 through `main`: an abandoned handle is a file lock on Windows.
    D-2's target - and kept apart from AC-2's round trip, which must still pass
    under D-2 (the data is committed; only the lifetime is wrong)."""
    opened = _capture_projects(monkeypatch)
    built = _capture_windows(qtbot, monkeypatch)

    def launch() -> int:
        _edit_first_line_and_close_at_once(qtbot, built[-1])
        return 0

    _fake_qapplication(monkeypatch, launch)
    app_module.main(["mangatl", str(source)])

    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].select("SELECT 1")


def test_the_project_stays_open_while_the_window_is_open(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
) -> None:
    """The other side of C-4: the project is not closed early (a close wired to
    something other than the window closing)."""
    opened = _capture_projects(monkeypatch)
    window = _build(qtbot, [str(source)])
    assert isinstance(window, Workspace)
    window.show()
    _settle()

    assert len(opened) == 1
    assert opened[0].select("SELECT 1") == [(1,)]

    window.close()
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].select("SELECT 1")


def test_closed_is_emitted_once_per_close_and_after_the_pending_save(
    qtbot,  # type: ignore[no-untyped-def]
    source: Path,
) -> None:
    """C-4's ordering, on a bare `Workspace`: a slot on `closed` reads the
    project file through a second connection and must find the edit already
    there. D-3's target (emitting before the flush)."""
    with open_project(_project_file(source).parent) as project:
        window = Workspace()
        qtbot.addWidget(window)
        window.resize(1100, 720)
        with qtbot.waitExposed(window):
            window.show()
        window.load_chapter(project)
        window.page_strip.setCurrentRow(0)
        _settle()
        seen_at_emission: list[list[tuple[Any, Any]]] = []
        window.closed.connect(lambda: seen_at_emission.append(_on_disk(source, 0)))

        _edit_first_line_and_close_at_once(qtbot, window)

        assert len(seen_at_emission) == 1, f"closed emitted {len(seen_at_emission)} times"
        assert seen_at_emission[0][0] == (NEW_TEXT, "edited")


# =============================================================================
# AC-3 / C-2 case 3, as MT-057 rewrote it: no project -> the folder is read
# =============================================================================


def _assert_intake_error(window: QMainWindow, text: str) -> None:
    """MT-057 C-3: the intake window, its drop target in the error state with
    `text` as the headline - not MT-054's notice window."""
    from mangatl.ui.intake import FolderDropTarget

    assert type(window) is MainWindow, f"build_window returned a {type(window).__name__}"
    assert window.windowTitle() == WINDOW_TITLE
    assert window.findChild(QObject, "notice") is None, "MT-054's notice window was built"
    central = window.centralWidget()
    assert isinstance(central, FolderDropTarget), f"central widget is {type(central).__name__}"
    headline = central.findChild(QLabel, "headline")
    assert headline is not None
    assert (central.state, headline.text()) == ("error", text)


def test_a_folder_with_no_project_and_an_undecodable_page_shows_the_intake_error_naming_it(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MT-057 AC-6 on the command line (was MT-054 AC-3's notice). Given
    relatively; nothing written - no `.mtproj`, every byte as it was."""
    folder = tmp_path / "Vol 1 & 2"
    folder.mkdir()
    (folder / "001.png").write_bytes(b"not read")
    monkeypatch.chdir(tmp_path)
    before = _tree(tmp_path)

    window = _build(qtbot, ["Vol 1 & 2"])

    _assert_intake_error(window, _undecodable("001.png"))
    assert _tree(tmp_path) == before, "launching on a folder with no project wrote something"
    assert (folder / "001.png").read_bytes() == b"not read"


def test_an_empty_project_directory_without_a_project_file_is_no_project(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """C-2 case 3 is decided by `project.db`, not by the `.mtproj` directory:
    a bare `.mtproj` over a folder with no page images is MT-057 AC-2, and the
    `.mtproj` still holds nothing afterwards."""
    folder = tmp_path / "chapter"
    folder.mkdir()
    (tmp_path / "chapter.mtproj").mkdir()
    before = _tree(tmp_path)

    window = _build(qtbot, [str(folder)])

    _assert_intake_error(window, _no_pages(folder.resolve()))
    assert _tree(tmp_path) == before
    assert list((tmp_path / "chapter.mtproj").iterdir()) == []


def test_the_no_project_notice_is_gone_from_the_app_module() -> None:
    """MT-057 C-2 / PO-3: `NO_PROJECT_NOTICE` is deleted, not left unused."""
    assert not hasattr(app_module, "NO_PROJECT_NOTICE"), "NO_PROJECT_NOTICE still exists"


def test_the_app_module_does_not_import_create_project() -> None:
    """C-2: `create_project` is not imported by `mangatl.app`."""
    assert not hasattr(app_module, "create_project")


# =============================================================================
# C-2 cases 2, 5, 6 (PO-3)
# =============================================================================


def test_a_folder_that_does_not_exist_is_named_as_plain_text(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """Case 2. The name holds `<b>`: parsed as markup it would vanish from the
    rendering, so the label must be plain text (C-5). Never created."""
    missing = tmp_path / "x <b>vol 1"
    before = _tree(tmp_path)

    window = _build(qtbot, [str(missing)])

    assert type(window) is MainWindow
    _assert_notice_label(_notice(window), _no_folder_notice(missing.resolve()))
    assert _tree(tmp_path) == before


def test_a_file_given_as_the_folder_is_no_such_folder(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Case 2 is "not a directory", not "does not exist"."""
    a_file = tmp_path / "page.png"
    a_file.write_bytes(b"x")

    window = _build(qtbot, [str(a_file)])

    _assert_notice_label(_notice(window), _no_folder_notice(a_file.resolve()))


def test_a_project_from_a_newer_build_shows_its_message_not_a_traceback(
    qtbot,  # type: ignore[no-untyped-def]
    source: Path,
) -> None:
    """Case 5: `SchemaTooNew`'s own message, shown in the notice."""
    connection = sqlite3.connect(_project_file(source))
    try:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1:d}")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchemaTooNew) as raised:
        open_project(_project_file(source).parent)
    expected = str(raised.value)
    assert "upgrade mangatl" in expected

    window = _build(qtbot, [str(source)])

    assert type(window) is MainWindow
    _assert_notice_label(_notice(window), expected)


def test_two_arguments_show_the_usage(qtbot, source: Path) -> None:  # type: ignore[no-untyped-def]
    """Case 6. `<folder>` survives only as plain text."""
    window = _build(qtbot, [str(source), str(source)])

    assert type(window) is MainWindow
    _assert_notice_label(_notice(window), USAGE_TEXT)


# =============================================================================
# C-5: MainWindow(notice=...)
# =============================================================================


def test_a_notice_window_is_one_selectable_plain_text_label(qtbot) -> None:  # type: ignore[no-untyped-def]
    text = "Line one <b>not bold</b>\nLine two & more"
    window = MainWindow(notice=text)
    qtbot.addWidget(window)

    assert window.windowTitle() == WINDOW_TITLE
    _assert_notice_label(_notice(window), text)


def test_the_notice_object_name_is_exported() -> None:
    assert main_window_module.NOTICE_OBJECT_NAME == "notice"


def test_notice_none_with_an_opener_is_the_folder_intake(qtbot) -> None:  # type: ignore[no-untyped-def]
    """MT-055 C-2: `notice=None` needs an `open_folder`; given one, the window
    is the intake. (Without one it is a TypeError: `test_folder_intake.py`.)"""

    def never_opens(folder: Path) -> str:
        raise AssertionError(f"no folder should be opened here, got {folder}")

    window = MainWindow(notice=None, open_folder=never_opens)
    qtbot.addWidget(window)

    _assert_intake_window(window)
