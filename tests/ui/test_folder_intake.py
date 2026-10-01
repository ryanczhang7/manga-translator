"""MT-055: a chapter folder can be chosen from the window.

The no-argument window is `FolderDropTarget` (`components.md` §2) in a
`MainWindow` built with an injected `open_folder` (C-1/C-2). The chooser is
injected too (`choose_folder`), so no native dialog ever opens here; C-4's real
dialog is driven through a stand-in for `mangatl.ui.intake.QFileDialog`.

Oracle partition (story `## Contract`):

- **Settled - spelled out here, never imported:** the three empty-state strings
  (`components.md` §2 empty row), "Choose a different folder" (§2 error row),
  role Button and name "Choose chapter folder" (`accessibility.md` A-08), and
  AC-4's error text, or `SchemaTooNew`'s own message, read from the exception
  as MT-054's tests do. MT-057 (its PO-3) retired AC-4's no-project text, the
  `mangatl-run` notice: a folder with no project is now read as a chapter, and
  the AC-4 tests below are MT-057's rewrites (its `## Contract`, "Callers and
  tests this story rewrites") - an undecodable page is its AC-6 error, and the
  "named resolved" test uses its AC-2 folder, where `{folder}` appears. Both
  texts are spelled out here, never read from `mangatl.app`.
- **Mechanical:** one focus stop and one accessible Button over the target's
  subtree; one chooser call per activation, zero for a right click, `Key_A`,
  `Key_Escape`; one `open_folder` call with the chosen `Path`; the opened window
  shown before the intake window closes; the project closed with the
  `Workspace`; the tree under `tmp_path` unchanged for AC-4 and AC-5.

The parts of the target are found by object name (`folder-drop-target`,
`headline`, `body`, `affordance`), never through a constant. `FolderDropTarget`
is never constructed here: its constructor is GREEN's choice.

Measured 2026-09-30 (PySide6, offscreen), and why the test shapes are what they
are: `QAccessible.Role.Button` and `PushButton` are both 43, so a `QPushButton`
affordance fails AC-1; a `QAbstractButton` subclass reports role Button and
exposes a child `QLabel` as StaticText (41); a left click delivered to a child
`QLabel` reaches the button; and a bare `QAbstractButton` activates on Space
but NOT on Return - so the Enter tests below are not satisfied for free (DV-3).

**Timing.** No real-time waits: only window exposure, activation and focus.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage
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
from mangatl.ui import intake, tokens_gen
from mangatl.ui.canvas import LOADED
from mangatl.ui.intake import FolderDropTarget, choose_folder_dialog
from mangatl.ui.main_window import WINDOW_TITLE, MainWindow
from mangatl.ui.workspace import Workspace

# --- Settled strings, spelled out (never read back from the module under test) ------
HEADLINE_EMPTY = "Drop a chapter folder here"
BODY_EMPTY = "Or choose a folder. Pages are processed in filename order."
AFFORDANCE_EMPTY = "Choose folder\u2026"  # "Choose folder…", U+2026 one character
AFFORDANCE_ERROR = "Choose a different folder"
TARGET_NAME = "Choose chapter folder"  # accessibility.md A-08
DIALOG_CAPTION = "Choose chapter folder"  # C-4


def _no_pages(folder: Path) -> str:
    """MT-057 AC-2's headline, the folder resolved."""
    return f"No page images in {folder}. This tool reads .png and .jpg files."


def _undecodable(filename: str) -> str:
    """MT-057 AC-6's sentence (the Lead Designer's)."""
    return (
        f"{filename} could not be opened as a page image."
        " Remove or replace it, then choose the folder again."
    )


SELECTABLE = (
    Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
)

# --- The chapter on disk (the shape MT-054's tests use) -------------------------------
#: Ordinal order, deliberately NOT alphabetical: a strip sorted by name fails.
PAGES = ("b-first.png", "a-second.png")
PAGE = QSize(600, 800)
#: Page 0 has three regions, page 1 one: the column's row count tells them apart.
PAGE0_OCR = (("一", False), ("二", False), ("三", False))
PAGE1_OCR = (("四", False),)


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


def _store(project: Project, ordinal: int, ocr: tuple[tuple[str, bool], ...], mask: bytes) -> None:
    project.write_regions(
        ordinal,
        [
            RawRegion(polygon=_ring(i), mask=mask, confidence=0.9, kind="bubble")
            for i in range(len(ocr))
        ],
    )
    project.write_lines(ordinal, [OcrResult(ja, ocr_empty=empty) for ja, empty in ocr])


@pytest.fixture
def source(tmp_path: Path, page_png: bytes, mask_png: bytes) -> Path:
    """A chapter folder whose sibling `.mtproj` project exists, CLOSED."""
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
        _store(project, 0, PAGE0_OCR, mask_png)
        _store(project, 1, PAGE1_OCR, mask_png)
    return folder


@pytest.fixture
def undecodable(tmp_path: Path) -> Path:
    """A folder with no project whose one page will not decode: MT-057 AC-6's
    error state. `&` and a space in its name: plain text. (No `<`: CI runs on
    Windows.)"""
    folder = tmp_path / "Vol 1 & 2"
    folder.mkdir()
    (folder / "001.png").write_bytes(b"not read")
    return folder


@pytest.fixture
def no_pages(tmp_path: Path) -> Path:
    """A folder with no project and no page images: MT-057 AC-2's error state,
    whose text names the folder."""
    folder = tmp_path / "Vol 5 & 6"
    folder.mkdir()
    (folder / "notes.txt").write_bytes(b"not a page")
    return folder


def _make_too_new(folder: Path) -> str:
    """Bump the project's schema past this build's; return `SchemaTooNew`'s own
    message, read from the exception (MT-054 C-2 case 5), never spelled out."""
    project_file = folder.with_name(folder.name + ".mtproj") / "project.db"
    connection = sqlite3.connect(project_file)
    try:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1:d}")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchemaTooNew) as raised:
        open_project(project_file.parent)
    return str(raised.value)


def _tree(root: Path) -> list[Path]:
    return sorted(root.rglob("*"))


# --- Recorders ------------------------------------------------------------------------


class Chooser:
    """A `FolderChooser` that returns the queued answers in order and records
    the parent of every call."""

    def __init__(self, *answers: Path | None) -> None:
        self.answers = list(answers)
        self.parents: list[QWidget] = []

    def __call__(self, parent: QWidget) -> Path | None:
        self.parents.append(parent)
        return self.answers.pop(0) if self.answers else None


class Opener:
    """A `FolderOpener` that records every path and delegates to `delegate`."""

    def __init__(
        self, delegate: Callable[[Path], QMainWindow | Chapter | str] | None = None
    ) -> None:
        self.delegate = delegate
        self.calls: list[Path] = []

    def __call__(self, folder: Path) -> QMainWindow | Chapter | str:
        self.calls.append(folder)
        if self.delegate is None:
            return "stub opener: no folder expected"
        return self.delegate(folder)


def _capture_projects(monkeypatch: pytest.MonkeyPatch) -> list[Project]:
    """Every `Project` `mangatl.app` opens, through its own namespace (C-1)."""
    opened: list[Project] = []
    real = app_module.open_project

    def capture(project_dir: Path) -> Project:
        project = real(project_dir)
        opened.append(project)
        return project

    monkeypatch.setattr(app_module, "open_project", capture)
    return opened


@pytest.fixture
def windows(qtbot) -> Iterator[list[QMainWindow]]:  # type: ignore[no-untyped-def]
    """Every window a test makes, and every window those windows hand over to,
    closed at teardown - an open `Workspace` holds its project file, and on
    Windows an open file cannot be removed with `tmp_path`."""
    made: list[QMainWindow] = []
    yield made
    for window in made:
        opened = getattr(window, "opened", None)
        if isinstance(opened, QMainWindow):
            opened.close()
        window.close()


def _intake(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    chooser: Chooser,
    opener: Callable[[Path], QMainWindow | Chapter | str],
) -> MainWindow:
    """The intake window, shown, exposed and active."""
    window = MainWindow(open_folder=opener, choose_folder=chooser)
    qtbot.addWidget(window)
    windows.append(window)
    window.resize(900, 600)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()
    return window


def _target(window: QMainWindow) -> FolderDropTarget:
    central = window.centralWidget()
    assert isinstance(central, FolderDropTarget), (
        f"central widget is {type(central).__name__}, not the FolderDropTarget"
    )
    assert central.objectName() == "folder-drop-target"
    return central


def _part(target: QWidget, name: str) -> QLabel:
    part = target.findChild(QLabel, name)
    assert part is not None, f"the drop target has no QLabel named {name!r}"
    return part


def _focus(qtbot, widget: QWidget) -> None:  # type: ignore[no-untyped-def]
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(widget.hasFocus)
    _settle()


def _subtree(target: QWidget) -> list[QWidget]:
    return [target, *target.findChildren(QWidget)]


def _focus_stops(target: QWidget) -> list[QWidget]:
    """Widgets in the subtree that Tab can reach (their policy includes TabFocus)."""
    tab = Qt.FocusPolicy.TabFocus.value
    return [w for w in _subtree(target) if w.focusPolicy().value & tab == tab]


def _accessible_buttons_in_tree(target: QWidget) -> list[str]:
    """Names of every accessible Button in the accessible tree walked from the
    target's own interface (A-08: queried by role and name)."""
    found: list[str] = []

    def walk(interface: Any, depth: int) -> None:
        if interface is None or not interface.isValid() or depth > 8:
            return
        if interface.role() == QAccessible.Role.Button:
            found.append(interface.text(QAccessible.Text.Name))
        for i in range(interface.childCount()):
            walk(interface.child(i), depth + 1)

    walk(QAccessible.queryAccessibleInterface(target), 0)
    return found


def _descendant_widgets_with_button_role(target: QWidget) -> list[str]:
    """Descendant widgets whose own interface reports role Button - a widget can
    be missing from the walked tree and still be announced when focused."""
    named: list[str] = []
    for widget in target.findChildren(QWidget):
        interface = QAccessible.queryAccessibleInterface(widget)
        if interface is not None and interface.role() == QAccessible.Role.Button:
            named.append(widget.objectName() or type(widget).__name__)
    return named


def _assert_one_control(target: QWidget) -> None:
    """AC-1 / PO-5 / C-3: the region is the only focus stop and the only
    accessible Button, named per A-08, described by its visible text."""
    stops = _focus_stops(target)
    assert stops == [target], (
        f"focus stops in the drop target: {[w.objectName() or type(w).__name__ for w in stops]}"
    )
    interface = QAccessible.queryAccessibleInterface(target)
    assert interface is not None
    assert interface.role() == QAccessible.Role.Button, f"target role is {interface.role()!r}"
    assert interface.text(QAccessible.Text.Name) == TARGET_NAME
    buttons = _accessible_buttons_in_tree(target)
    assert buttons == [TARGET_NAME], f"accessible Buttons in the drop target: {buttons}"
    inner = _descendant_widgets_with_button_role(target)
    assert inner == [], f"widgets inside the drop target with role Button: {inner}"
    parts = [_part(target, n) for n in ("headline", "body", "affordance")]
    for part in parts:
        assert part.focusPolicy() == Qt.FocusPolicy.NoFocus, f"{part.objectName()} takes focus"
        part_interface = QAccessible.queryAccessibleInterface(part)
        assert part_interface.role() != QAccessible.Role.Button, (
            f"{part.objectName()} is an accessible Button"
        )
        assert part.textFormat() == Qt.TextFormat.PlainText, f"{part.objectName()} is not plain"
        assert not (part.textInteractionFlags() & SELECTABLE), (
            f"{part.objectName()} is selectable and would swallow the click"
        )
    headline, body = parts[0], parts[1]
    expected = "\n".join(t for t in (headline.text(), body.text()) if t)
    assert interface.text(QAccessible.Text.Description) == expected


def _assert_empty(target: QWidget) -> None:
    assert target.state == "empty"  # type: ignore[attr-defined]
    headline, body, affordance = (_part(target, n) for n in ("headline", "body", "affordance"))
    assert headline.text() == HEADLINE_EMPTY
    assert body.text() == BODY_EMPTY
    assert affordance.text() == AFFORDANCE_EMPTY
    for part in (headline, body, affordance):
        assert part.isVisibleTo(target), f"{part.objectName()} is hidden in the empty state"


def _assert_error(target: QWidget, text: str) -> None:
    """C-3 error state (PO-8): the reason is the headline, verbatim; the body is
    empty and hidden; the affordance offers another folder."""
    assert target.state == "error"  # type: ignore[attr-defined]
    headline, body, affordance = (_part(target, n) for n in ("headline", "body", "affordance"))
    assert headline.text() == text
    assert body.text() == ""
    assert not body.isVisibleTo(target), "the body is still shown in the error state"
    assert affordance.text() == AFFORDANCE_ERROR
    assert headline.isVisibleTo(target)
    assert affordance.isVisibleTo(target)


def _visible_top_levels() -> set[int]:
    return {id(w) for w in QApplication.topLevelWidgets() if w.isVisible()}


# =============================================================================
# AC-1: the no-argument window is the empty drop target, one control
# =============================================================================


def test_the_no_argument_window_shows_the_empty_drop_target_texts(qtbot, windows) -> None:  # type: ignore[no-untyped-def]
    window = _intake(qtbot, windows, Chooser(), Opener())

    assert window.windowTitle() == WINDOW_TITLE
    _assert_empty(_target(window))


def test_the_drop_target_is_the_only_focus_stop_and_the_only_accessible_button(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
) -> None:
    window = _intake(qtbot, windows, Chooser(), Opener())

    _assert_one_control(_target(window))


def test_the_drop_target_accepts_tab_focus(qtbot, windows) -> None:  # type: ignore[no-untyped-def]
    window = _intake(qtbot, windows, Chooser(), Opener())
    target = _target(window)

    tab = Qt.FocusPolicy.TabFocus.value
    assert target.focusPolicy().value & tab == tab, f"policy {target.focusPolicy()!r}"
    _focus(qtbot, target)
    assert target.hasFocus()


def test_the_empty_drop_target_is_described_by_its_headline_and_body(qtbot, windows) -> None:  # type: ignore[no-untyped-def]
    window = _intake(qtbot, windows, Chooser(), Opener())

    interface = QAccessible.queryAccessibleInterface(_target(window))
    assert interface.text(QAccessible.Text.Description) == f"{HEADLINE_EMPTY}\n{BODY_EMPTY}"


def test_the_no_argument_window_shows_no_notice(qtbot, windows) -> None:  # type: ignore[no-untyped-def]
    window = _intake(qtbot, windows, Chooser(), Opener())

    assert window.findChild(QObject, "notice") is None


# =============================================================================
# AC-2: Enter, Space and a left click anywhere ask the chooser once each
# =============================================================================


@pytest.mark.parametrize(
    "key",
    [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space],
    ids=["Return", "Enter", "Space"],
)
def test_a_key_activation_asks_the_chooser_once_with_the_window_as_parent(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    key: Qt.Key,
) -> None:
    chooser = Chooser()
    opener = Opener()
    window = _intake(qtbot, windows, chooser, opener)
    target = _target(window)
    _focus(qtbot, target)

    QTest.keyClick(target, key)
    _settle()

    assert len(chooser.parents) == 1, f"{key!r} asked the chooser {len(chooser.parents)} times"
    assert chooser.parents[0] is window, "the chooser's parent is not the intake window"

    QTest.keyClick(target, key)
    _settle()
    assert len(chooser.parents) == 2, "a second activation did not ask again"
    assert opener.calls == [], "a dismissed chooser reached open_folder"


@pytest.mark.parametrize("part", ["target", "headline", "body", "affordance"])
def test_a_left_click_anywhere_on_the_region_asks_the_chooser_once(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    part: str,
) -> None:
    chooser = Chooser()
    window = _intake(qtbot, windows, chooser, Opener())
    target = _target(window)
    widget = target if part == "target" else _part(target, part)

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    _settle()

    assert len(chooser.parents) == 1, (
        f"a left click on {part} asked the chooser {len(chooser.parents)} times"
    )
    assert chooser.parents[0] is window


@pytest.mark.parametrize(
    "key", [Qt.Key.Key_A, Qt.Key.Key_Escape, Qt.Key.Key_Tab], ids=["A", "Escape", "Tab"]
)
def test_other_keys_do_not_ask_the_chooser(qtbot, windows, key: Qt.Key) -> None:  # type: ignore[no-untyped-def]
    """Negative control for AC-2's key tests: expected 0 calls."""
    chooser = Chooser()
    window = _intake(qtbot, windows, chooser, Opener())
    target = _target(window)
    _focus(qtbot, target)

    QTest.keyClick(target, key)
    _settle()

    assert chooser.parents == [], f"{key!r} asked the chooser"


@pytest.mark.parametrize("part", ["target", "affordance"])
def test_a_right_click_does_not_ask_the_chooser(qtbot, windows, part: str) -> None:  # type: ignore[no-untyped-def]
    """Negative control for AC-2's click tests: expected 0 calls."""
    chooser = Chooser()
    window = _intake(qtbot, windows, chooser, Opener())
    target = _target(window)
    widget = target if part == "target" else _part(target, part)

    QTest.mouseClick(widget, Qt.MouseButton.RightButton)
    _settle()

    assert chooser.parents == [], f"a right click on {part} asked the chooser"


def test_activation_emits_activated_once(qtbot, windows) -> None:  # type: ignore[no-untyped-def]
    """C-3: the target's `activated` signal, once per activation."""
    window = _intake(qtbot, windows, Chooser(), Opener())
    target = _target(window)
    seen: list[int] = []
    target.activated.connect(lambda: seen.append(1))

    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()
    _focus(qtbot, target)
    QTest.keyClick(target, Qt.Key.Key_Return)
    _settle()

    assert seen == [1, 1]


# =============================================================================
# AC-3: a folder with a project opens the review Workspace, as `mangatl <folder>`
# =============================================================================


def _pick_and_capture_order(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    folder: Path,
) -> tuple[MainWindow, Opener, list[bool]]:
    """Activate the intake window with a chooser that returns `folder`, the real
    `open_folder` behind a recorder. Returns the window, the recorder, and, for
    every Close event the intake window received, whether `opened` was already
    visible at that moment (C-2: shown first, then this window closes)."""
    opener = Opener(app_module.open_folder)
    window = _intake(qtbot, windows, Chooser(folder), opener)
    at_close: list[bool] = []

    class CloseWatch(QObject):
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.Close:
                opened = getattr(window, "opened", None)
                at_close.append(isinstance(opened, QWidget) and opened.isVisible())
            return False

    watch = CloseWatch(window)
    window.installEventFilter(watch)
    QTest.mouseClick(_target(window), Qt.MouseButton.LeftButton)
    _settle()
    if isinstance(window.opened, QWidget):
        qtbot.addWidget(window.opened)
    return window, opener, at_close


def test_a_picked_folder_with_a_project_opens_the_review_workspace(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    source: Path,
) -> None:
    window, opener, _ = _pick_and_capture_order(qtbot, windows, source)

    assert opener.calls == [source], f"open_folder was called with {opener.calls!r}"
    assert isinstance(window.opened, Workspace), f"opened is {type(window.opened).__name__}"
    assert window.opened.isVisible(), "the Workspace was not shown"


def test_the_opened_workspace_lists_the_pages_and_shows_the_first(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    source: Path,
) -> None:
    window, _, _ = _pick_and_capture_order(qtbot, windows, source)
    workspace = window.opened
    assert isinstance(workspace, Workspace)
    strip = workspace.page_strip

    assert [strip.item(i).text() for i in range(strip.count())] == list(PAGES)
    assert strip.currentRow() == 0
    assert workspace.page_canvas.state() == LOADED, f"canvas is {workspace.page_canvas.state()!r}"
    assert workspace.translation_column.list.count() == len(PAGE0_OCR)


def test_the_intake_window_closes_after_the_workspace_is_shown(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    source: Path,
) -> None:
    window, _, at_close = _pick_and_capture_order(qtbot, windows, source)

    assert not window.isVisible(), "the intake window is still open"
    assert at_close == [True], (
        f"Close events seen, and whether the Workspace was visible at each: {at_close!r}"
    )


def test_closing_the_picked_workspace_closes_its_project(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
) -> None:
    """MT-054 C-4 on the picker's path, and the picker resolves the project
    through `mangatl.app.open_project` (C-1): one resolution."""
    projects = _capture_projects(monkeypatch)
    window, _, _ = _pick_and_capture_order(qtbot, windows, source)
    assert isinstance(window.opened, Workspace)

    assert len(projects) == 1, f"mangatl.app.open_project was called {len(projects)} times"
    assert projects[0].select("SELECT 1") == [(1,)], "the project was closed early"

    window.opened.close()

    with pytest.raises(sqlite3.ProgrammingError):
        projects[0].select("SELECT 1")


def test_the_no_argument_window_opens_folders_with_the_command_lines_function(qtbot) -> None:  # type: ignore[no-untyped-def]
    """C-1: one function object, two callers - not a copy."""
    window = app_module.build_window([])
    qtbot.addWidget(window)

    assert isinstance(window, MainWindow)
    assert window.open_folder is app_module.open_folder
    _assert_empty(_target(window))


def test_the_real_dialog_path_opens_a_picked_chapter_end_to_end(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
) -> None:
    """`build_window([])` with no injected chooser: the default is C-4's dialog,
    driven through a stand-in for `intake.QFileDialog`."""
    asked: list[tuple[Any, ...]] = []

    class FakeDialog:
        @staticmethod
        def getExistingDirectory(*args: Any, **kwargs: Any) -> str:
            asked.append(args)
            return str(source)

    monkeypatch.setattr(intake, "QFileDialog", FakeDialog)
    window = app_module.build_window([])
    assert isinstance(window, MainWindow)
    qtbot.addWidget(window)
    windows.append(window)
    with qtbot.waitExposed(window):
        window.show()

    QTest.mouseClick(_target(window), Qt.MouseButton.LeftButton)
    _settle()

    assert asked == [(window, DIALOG_CAPTION)]
    assert isinstance(window.opened, Workspace)
    qtbot.addWidget(window.opened)
    assert window.opened.isVisible()
    assert window.opened.page_strip.currentRow() == 0
    assert not window.isVisible()


# =============================================================================
# AC-4: a folder that cannot be opened is the error state (texts per MT-057)
# =============================================================================


def test_a_picked_folder_with_an_undecodable_page_names_it_and_writes_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    undecodable: Path,
) -> None:
    """Was "shows the command line's text" (MT-054's notice); MT-057 AC-6."""
    before = _tree(tmp_path)
    opener = Opener(app_module.open_folder)
    window = _intake(qtbot, windows, Chooser(undecodable), opener)
    target = _target(window)

    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()

    assert opener.calls == [undecodable]
    assert window.opened is None
    assert window.isVisible(), "the intake window closed on a folder with no project"
    _assert_error(target, _undecodable("001.png"))
    assert _tree(tmp_path) == before, "choosing a folder with no project wrote something"


def test_a_relative_picked_folder_is_named_resolved(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    no_pages: Path,
) -> None:
    """The folder is named whole and resolved, wherever the app was started
    (MT-057 AC-2, whose text carries `{folder}`)."""
    monkeypatch.chdir(tmp_path)
    window = _intake(qtbot, windows, Chooser(Path(no_pages.name)), app_module.open_folder)
    target = _target(window)

    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()

    _assert_error(target, _no_pages(no_pages.resolve()))


def test_the_error_state_keeps_one_control_described_by_the_reason(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    undecodable: Path,
) -> None:
    window = _intake(qtbot, windows, Chooser(undecodable), app_module.open_folder)
    target = _target(window)
    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()

    _assert_one_control(target)
    interface = QAccessible.queryAccessibleInterface(target)
    assert interface.text(QAccessible.Text.Description) == _undecodable("001.png")


@pytest.mark.parametrize("how", ["click", "Return", "Space"])
def test_activating_the_error_state_asks_the_chooser_again(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    undecodable: Path,
    how: str,
) -> None:
    chooser = Chooser(undecodable)
    window = _intake(qtbot, windows, chooser, app_module.open_folder)
    target = _target(window)
    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()
    assert target.state == "error"

    if how == "click":
        QTest.mouseClick(_part(target, "affordance"), Qt.MouseButton.LeftButton)
    else:
        _focus(qtbot, target)
        key = Qt.Key.Key_Return if how == "Return" else Qt.Key.Key_Space
        QTest.keyClick(target, key)
    _settle()

    assert len(chooser.parents) == 2, f"{how} on the error state did not ask the chooser again"
    assert chooser.parents[1] is window


def test_a_different_folder_chosen_from_the_error_state_opens_it(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    undecodable: Path,
    source: Path,
) -> None:
    opener = Opener(app_module.open_folder)
    window = _intake(qtbot, windows, Chooser(undecodable, source), opener)
    target = _target(window)

    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()
    QTest.mouseClick(_part(target, "affordance"), Qt.MouseButton.LeftButton)
    _settle()

    assert opener.calls == [undecodable, source]
    assert isinstance(window.opened, Workspace)
    qtbot.addWidget(window.opened)
    assert window.opened.isVisible()
    assert not window.isVisible()


def test_show_error_replaces_the_text(qtbot, windows) -> None:  # type: ignore[no-untyped-def]
    window = _intake(qtbot, windows, Chooser(), Opener())
    target = _target(window)

    target.show_error("First reason & <b>not markup</b>")
    _assert_error(target, "First reason & <b>not markup</b>")
    target.show_error("Second reason")

    _assert_error(target, "Second reason")
    _assert_one_control(target)


def test_a_picked_project_from_a_newer_build_shows_its_message(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    source: Path,
) -> None:
    """AC-4, MT-054 C-2 case 5: `SchemaTooNew`'s own message, in the error state."""
    expected = _make_too_new(source)
    assert "upgrade mangatl" in expected
    before = _tree(tmp_path)
    window = _intake(qtbot, windows, Chooser(source), app_module.open_folder)
    target = _target(window)

    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()

    assert window.opened is None
    _assert_error(target, expected)
    _assert_one_control(target)
    assert _tree(tmp_path) == before


# =============================================================================
# AC-5: a dismissed chooser changes nothing
# =============================================================================


def test_dismissing_the_chooser_from_the_empty_state_changes_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    source: Path,
) -> None:
    """Negative control for AC-3: a `None` treated as a folder would call the
    opener (expected 0 calls) - DV-4's target."""
    before = _tree(tmp_path)
    opener = Opener(app_module.open_folder)
    chooser = Chooser(None)
    window = _intake(qtbot, windows, chooser, opener)
    target = _target(window)
    top_levels = _visible_top_levels()

    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()

    assert len(chooser.parents) == 1
    assert opener.calls == [], f"a dismissed chooser called open_folder with {opener.calls!r}"
    assert window.opened is None
    assert window.isVisible()
    _assert_empty(target)
    assert _visible_top_levels() == top_levels, "another window opened"
    assert _tree(tmp_path) == before


def test_dismissing_the_chooser_from_the_error_state_keeps_the_error(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    undecodable: Path,
) -> None:
    opener = Opener(app_module.open_folder)
    window = _intake(qtbot, windows, Chooser(undecodable, None), opener)
    target = _target(window)
    QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    _settle()
    expected = _undecodable("001.png")
    _assert_error(target, expected)
    before = _tree(tmp_path)
    top_levels = _visible_top_levels()

    QTest.mouseClick(_part(target, "affordance"), Qt.MouseButton.LeftButton)
    _settle()

    assert opener.calls == [undecodable], "the dismissal reached open_folder"
    assert window.opened is None
    assert window.isVisible()
    _assert_error(target, expected)
    assert _visible_top_levels() == top_levels, "another window opened"
    assert _tree(tmp_path) == before


# =============================================================================
# C-2: MainWindow's constructor
# =============================================================================


def test_a_window_that_could_choose_a_folder_but_not_open_it_is_refused() -> None:
    with pytest.raises(TypeError):
        MainWindow()
    with pytest.raises(TypeError):
        MainWindow(notice=None)
    with pytest.raises(TypeError):
        MainWindow(choose_folder=Chooser())


def test_the_window_keeps_the_opener_it_was_given_and_has_opened_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    opener = Opener()
    window = MainWindow(open_folder=opener, choose_folder=Chooser())
    qtbot.addWidget(window)

    assert window.open_folder is opener
    assert window.opened is None


def test_a_notice_window_has_no_drop_target_and_needs_no_opener(qtbot) -> None:  # type: ignore[no-untyped-def]
    """C-2: `notice` given is MT-054 C-5 unchanged; the opener is ignored."""
    plain = MainWindow(notice="Something is wrong")
    qtbot.addWidget(plain)
    with_opener = MainWindow(
        notice="Something is wrong", open_folder=Opener(), choose_folder=Chooser()
    )
    qtbot.addWidget(with_opener)

    for window in (plain, with_opener):
        assert window.findChild(QWidget, "folder-drop-target") is None
        central = window.centralWidget()
        assert isinstance(central, QLabel)
        assert central.objectName() == "notice"
        assert central.text() == "Something is wrong"


def test_the_canvas_accessible_name_constant_is_gone() -> None:
    """C-2 / PO-9: nothing in the window is a canvas any more."""
    from mangatl.ui import main_window as main_window_module

    assert not hasattr(main_window_module, "CANVAS_ACCESSIBLE_NAME")
    assert "CANVAS_ACCESSIBLE_NAME" not in main_window_module.__all__


# =============================================================================
# C-4: the real folder dialog, through a stand-in
# =============================================================================


@pytest.mark.parametrize(
    ("returned", "expected"),
    [("", None), ("X", Path("X")), ("C:/some chapter", Path("C:/some chapter"))],
    ids=["dismissed", "relative", "absolute-with-space"],
)
def test_the_folder_dialog_maps_its_answer_to_a_path_or_none(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    returned: str,
    expected: Path | None,
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class FakeDialog:
        @staticmethod
        def getExistingDirectory(*args: Any, **kwargs: Any) -> str:
            calls.append((args, kwargs))
            return returned

    monkeypatch.setattr(intake, "QFileDialog", FakeDialog)
    parent = QWidget()
    qtbot.addWidget(parent)

    result = choose_folder_dialog(parent)

    assert result == expected
    assert calls == [((parent, DIALOG_CAPTION), {})]


# =============================================================================
# C-5: the no-argument window through `main`
# =============================================================================


def test_launched_with_no_argument_main_shows_the_empty_drop_target(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[QMainWindow] = []
    real = app_module.build_window

    def capture(arguments: list[str]) -> QMainWindow:
        window = real(arguments)
        qtbot.addWidget(window)
        built.append(window)
        return window

    monkeypatch.setattr(app_module, "build_window", capture)
    seen: list[bool] = []

    class FakeQApplication:
        def __init__(self, argv: list[str]) -> None:
            self.argv = argv

        def exec(self) -> int:
            seen.append(built[-1].isVisible())
            return 0

    monkeypatch.setattr(app_module, "QApplication", FakeQApplication)

    assert app_module.main(["mangatl"]) == 0

    assert len(built) == 1
    window = built[0]
    assert type(window) is MainWindow
    assert window.open_folder is app_module.open_folder
    _assert_empty(_target(window))
    assert seen == [True]
