"""MT-056: a chapter folder can be dropped onto the window.

`FolderDropTarget` (`components.md` §2, MT-055) becomes a drop target in fact:
it classifies a drag at enter, says before the drop whether it is acceptable,
restores what it showed on leave, and hands one dropped folder to the same
`open_folder` the chooser uses.

Oracle partition (story `## Contract`):

- **Settled - spelled out here, never imported:** every string in the story's
  `## Design notes` table ("Release to load", "Drop a folder, not files",
  "Drop one folder" and the body forms with their singulars), the truncation
  rule (first 20 + U+2026 + last 19, only above 40 characters), the drive-root
  name (`str(path)`, PO-3), the accessible name "Choose chapter folder"
  (A-08), MT-055's empty and error texts, MT-057's AC-6 sentence (which
  replaced MT-054's no-project text for a dropped folder with no project, per
  MT-057's `## Contract` rewrite list) and the `SchemaTooNew` message (read
  from the exception, as MT-055's tests do). MT-057 also adds the dropped path
  of its AC-1: a dropped folder of pages shows the chapter summary.
- **Mechanical:** `acceptDrops()`; `isAccepted()` after every enter and drop;
  `state`; restore of every observable on leave and after an invalid drop,
  from the empty AND the error state; `dropped` emissions (one per valid drop,
  with the dropped `Path` un-resolved); `open_folder` calls; chooser calls (0).

**How a drag is driven (Contract C-3, re-probed in RED on PySide6 6.9.3,
offscreen).** Enter and leave go through `QApplication.sendEvent`. A valid drop
goes through `sendEvent` after an accepted enter, as a real drag does. An
*invalid* drop is delivered straight to the widget with `target.event(drop)`:
`sendEvent` does not deliver a `QDropEvent` after a refused enter at all, so a
"dropping changes nothing" test through `sendEvent` passes against a target that
opens every drop (DV-2). Every event is `setAccepted(False)` before delivery so
`isAccepted()` afterwards is the handler's decision.

Every drag helper first asserts `acceptDrops()`: without it Qt never delivers a
drag event to the target, and the "nothing changes" tests (AC-5, the leave
tests) would pass against a target that is not a drop target at all.

**Timing.** No real-time waits: only window exposure and event delivery.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEvent,
    QIODevice,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QAccessible,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QImage,
)
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

from mangatl import app as app_module
from mangatl.domain.page import Chapter, Page
from mangatl.store.project import SCHEMA_VERSION, SchemaTooNew, create_project, open_project
from mangatl.ui import tokens_gen
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.main_window import MainWindow
from mangatl.ui.workspace import Workspace

# --- Settled strings, spelled out (never read back from the module under test) ------
HEADLINE_EMPTY = "Drop a chapter folder here"
BODY_EMPTY = "Or choose a folder. Pages are processed in filename order."
AFFORDANCE_EMPTY = "Choose folder\u2026"  # "Choose folder…", U+2026 one character
AFFORDANCE_ERROR = "Choose a different folder"
TARGET_NAME = "Choose chapter folder"  # accessibility.md A-08

RELEASE = "Release to load"
NOT_FILES = "Drop a folder, not files"
ONE_FOLDER = "Drop one folder"

#: The error state a drag may start from: MT-057 AC-3's shape, two lines (it
#: was MT-054's retired no-project notice; any two-line reason would do).
ERROR_TEXT = "Windows would not let this app read C:\\manga\\Vol 3.\nAccess is denied."

WEB = "https://example.com/page.png"

#: 41 distinct characters; the first 39 / 40 / 41 of it are the boundary names.
LONG = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNO"
#: LONG cut per the design: its first 20, U+2026, its last 19 (40 characters).
LONG_CUT = "abcdefghijklmnopqrst\u2026wxyzABCDEFGHIJKLMNO"
# The spelled-out cut is checked against the rule once, at import, so a typo in
# it cannot pass for the rule (and does not depend on the module under test).
assert (len(LONG), len(LONG_CUT)) == (41, 40)
assert LONG[:20] + "\u2026" + LONG[-19:] == LONG_CUT


def _undecodable(filename: str) -> str:
    """MT-057 AC-6's sentence (the Lead Designer's)."""
    return (
        f"{filename} could not be opened as a page image."
        " Remove or replace it, then choose the folder again."
    )


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# --- The chapter on disk (MT-055's fixture shape) -------------------------------------
PAGES = ("b-first.png", "a-second.png")
PAGE = QSize(600, 800)


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


@pytest.fixture
def source(tmp_path: Path, page_png: bytes) -> Path:
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
    with create_project(chapter, tmp_path / "my chapter.mtproj"):
        pass
    return folder


@pytest.fixture
def undecodable(tmp_path: Path) -> Path:
    """A folder with no project whose one page will not decode (MT-057 AC-6);
    `&` and a space in its name."""
    folder = tmp_path / "Vol 1 & 2"
    folder.mkdir()
    (folder / "001.png").write_bytes(b"not read")
    return folder


def _make_too_new(folder: Path) -> str:
    """Bump the project's schema past this build's; return `SchemaTooNew`'s own
    message, read from the exception, never spelled out."""
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


def _folder(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    return path


def _file(root: Path, name: str) -> Path:
    path = root / name
    path.write_bytes(b"x")
    return path


# --- Recorders ------------------------------------------------------------------------


class Chooser:
    """A `FolderChooser` that records every call and never chooses."""

    def __init__(self) -> None:
        self.parents: list[QWidget] = []

    def __call__(self, parent: QWidget) -> Path | None:
        self.parents.append(parent)
        return None


class Opener:
    """A `FolderOpener` that records every path and delegates to `delegate`,
    or returns `reason` when there is none."""

    def __init__(
        self,
        delegate: Callable[[Path], QMainWindow | Chapter | str] | None = None,
        reason: str = "stub opener: no folder expected",
    ) -> None:
        self.delegate = delegate
        self.reason = reason
        self.calls: list[Path] = []

    def __call__(self, folder: Path) -> QMainWindow | Chapter | str:
        self.calls.append(folder)
        if self.delegate is None:
            return self.reason
        return self.delegate(folder)


# --- The target, bare and in its window -----------------------------------------------


@pytest.fixture(params=["empty", "error"])
def pre(request: pytest.FixtureRequest) -> str:
    """The state a drag starts from: AC-1, AC-2 and AC-5 hold from both."""
    return str(request.param)


@pytest.fixture
def target(qtbot, pre: str) -> FolderDropTarget:  # type: ignore[no-untyped-def]
    """A bare, shown drop target in the `pre` state."""
    widget = FolderDropTarget()
    qtbot.addWidget(widget, before_close_func=_release_drag)
    widget.resize(500, 300)
    with qtbot.waitExposed(widget):
        widget.show()
    if pre == "error":
        widget.show_error(ERROR_TEXT)
    _settle()
    return widget


@pytest.fixture
def windows(qtbot) -> Iterator[list[QMainWindow]]:  # type: ignore[no-untyped-def]
    """Every window a test makes, and every window it hands over to, closed at
    teardown - an open `Workspace` holds its project file on Windows."""
    made: list[QMainWindow] = []
    yield made
    for window in made:
        opened = getattr(window, "opened", None)
        if isinstance(opened, QMainWindow):
            opened.close()
        window.close()


def _show(qtbot, windows: list[QMainWindow], window: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.addWidget(window, before_close_func=_release_drag)
    windows.append(window)
    window.resize(900, 600)
    with qtbot.waitExposed(window):
        window.show()
    _settle()


def _intake(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    opener: Callable[[Path], QMainWindow | Chapter | str],
    chooser: Chooser,
) -> MainWindow:
    window = MainWindow(open_folder=opener, choose_folder=chooser)
    _show(qtbot, windows, window)
    return window


def _target(window: QMainWindow) -> FolderDropTarget:
    central = window.centralWidget()
    assert isinstance(central, FolderDropTarget), (
        f"central widget is {type(central).__name__}, not the FolderDropTarget"
    )
    return central


def _part(target: QWidget, name: str) -> QLabel:
    part = target.findChild(QLabel, name)
    assert part is not None, f"the drop target has no QLabel named {name!r}"
    return part


def _snapshot(target: QWidget) -> dict[str, Any]:
    """Every observable the design's Restore rule names, plus what a screen
    reader hears: state, the three texts and their visibility, the accessible
    name and description."""
    interface = QAccessible.queryAccessibleInterface(target)
    shot: dict[str, Any] = {"state": getattr(target, "state", None)}
    for name in ("headline", "body", "affordance"):
        part = _part(target, name)
        shot[name] = part.text()
        shot[f"{name} visible"] = part.isVisibleTo(target)
    shot["name"] = interface.text(QAccessible.Text.Name)
    shot["description"] = interface.text(QAccessible.Text.Description)
    return shot


def _expected_pre(pre: str) -> dict[str, Any]:
    """MT-055's empty and error states, spelled out."""
    if pre == "empty":
        return {
            "state": "empty",
            "headline": HEADLINE_EMPTY,
            "headline visible": True,
            "body": BODY_EMPTY,
            "body visible": True,
            "affordance": AFFORDANCE_EMPTY,
            "affordance visible": True,
            "name": TARGET_NAME,
            "description": f"{HEADLINE_EMPTY}\n{BODY_EMPTY}",
        }
    return {
        "state": "error",
        "headline": ERROR_TEXT,
        "headline visible": True,
        "body": "",
        "body visible": False,
        "affordance": AFFORDANCE_ERROR,
        "affordance visible": True,
        "name": TARGET_NAME,
        "description": ERROR_TEXT,
    }


def _assert_pre(target: QWidget, pre: str) -> dict[str, Any]:
    shot = _snapshot(target)
    assert shot == _expected_pre(pre), "precondition: the target is not in MT-055's state"
    return shot


# --- Synthesised drags (C-3) ----------------------------------------------------------


def _mime(*urls: QUrl) -> QMimeData:
    mime = QMimeData()
    mime.setUrls(list(urls))
    return mime


def _local(*paths: Path) -> QMimeData:
    return _mime(*(QUrl.fromLocalFile(str(p)) for p in paths))


def _assert_drop_target(target: QWidget) -> None:
    assert target.acceptDrops(), (
        "the drop target does not accept drops: Qt never delivers a drag to it"
    )


#: Every `QMimeData` a synthesised drag used, alive until the process ends. A
#: precaution, not a measured need: an event holds a raw pointer to its mime
#: data, and a collected one would be a crash rather than a failure.
_ALIVE: list[QMimeData] = []


def _release_drag(_: QWidget) -> None:
    """End any drag Qt still thinks is in progress. MEASURED in RED (PySide6
    6.9.3, offscreen): `QApplication.sendEvent` routes a `QDragLeaveEvent` (and
    a `QDropEvent`) to the widget whose enter was last ACCEPTED - Qt's drag
    manager keeps a raw pointer to it until a leave or a drop - NOT to the
    receiver. A test that ends in hover-valid leaves that pointer set; the next
    test's leave went to the deleted widget and crashed the interpreter
    (access violation). Run before every widget here is closed and deleted;
    with no drag in progress the leave lands on a throwaway widget."""
    QApplication.sendEvent(QWidget(), QDragLeaveEvent())


def _enter(target: QWidget, mime: QMimeData) -> QDragEnterEvent:
    _ALIVE.append(mime)
    _assert_drop_target(target)
    event = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.setAccepted(False)
    QApplication.sendEvent(target, event)
    return event


def _leave(target: QWidget) -> None:
    QApplication.sendEvent(target, QDragLeaveEvent())


def _drop_event(mime: QMimeData) -> QDropEvent:
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.setAccepted(False)
    return event


def _drop_as_qt_would(target: QWidget, mime: QMimeData) -> QDropEvent:
    """A drop after an accepted enter: the route a real drag takes."""
    event = _drop_event(mime)
    QApplication.sendEvent(target, event)
    return event


def _drop_directly(target: QWidget, mime: QMimeData) -> QDropEvent:
    """A drop delivered to the widget itself, past Qt's routing (C-3's trap):
    the only way to see what the target's own handler does with a drop it
    should refuse."""
    event = _drop_event(mime)
    target.event(event)
    return event


def _record(target: FolderDropTarget) -> tuple[list[Any], list[bool]]:
    """Every `dropped` emission and every `activated` emission."""
    dropped: list[Any] = []
    activated: list[bool] = []
    target.dropped.connect(dropped.append)
    target.activated.connect(lambda: activated.append(True))
    return dropped, activated


def _hover(state: str, headline: str, body: str) -> dict[str, Any]:
    """A hover state per the Design notes table: affordance "", the accessible
    name unchanged, the description the headline and body on two lines."""
    return {
        "state": state,
        "headline": headline,
        "body": body,
        "affordance": "",
        "name": TARGET_NAME,
        "description": f"{headline}\n{body}",
    }


def _hover_shot(target: QWidget) -> dict[str, Any]:
    shot = _snapshot(target)
    return {k: shot[k] for k in ("state", "headline", "body", "affordance", "name", "description")}


# =============================================================================
# AC-1: one local folder is hover-valid; leaving restores the previous state
# =============================================================================


def test_the_drop_target_accepts_drops_from_construction(qtbot) -> None:  # type: ignore[no-untyped-def]
    widget = FolderDropTarget()
    qtbot.addWidget(widget)

    assert widget.acceptDrops(), "a new FolderDropTarget does not accept drops"


def test_one_local_folder_entering_says_release_to_load_and_accepts_the_drag(
    target: FolderDropTarget, pre: str, tmp_path: Path
) -> None:
    _assert_pre(target, pre)
    folder = _folder(tmp_path, "Chapter 12")

    event = _enter(target, _local(folder))

    assert event.isAccepted(), "a drag of one local folder was refused"
    assert _hover_shot(target) == _hover("hover-valid", RELEASE, "Chapter 12")
    assert _part(target, "headline").isVisibleTo(target), "the hover-valid headline is hidden"
    assert _part(target, "body").isVisibleTo(target), "the folder's name is hidden"


def test_a_valid_drag_that_leaves_restores_the_previous_state_unchanged(
    target: FolderDropTarget, pre: str, tmp_path: Path
) -> None:
    before = _assert_pre(target, pre)
    _enter(target, _local(_folder(tmp_path, "Chapter 12")))
    assert target.state == "hover-valid", "precondition: the drag did not enter hover-valid"

    _leave(target)

    assert _snapshot(target) == before


@pytest.mark.parametrize(
    ("length", "shown"),
    [(39, LONG[:39]), (40, LONG[:40]), (41, LONG_CUT)],
    ids=["39-whole", "40-whole", "41-cut"],
)
def test_a_folder_name_is_cut_in_the_middle_only_above_forty_characters(
    target: FolderDropTarget, tmp_path: Path, length: int, shown: str
) -> None:
    folder = _folder(tmp_path, LONG[:length])

    _enter(target, _local(folder))

    assert target.state == "hover-valid"
    assert _part(target, "body").text() == shown
    assert target.accessibleDescription() == f"{RELEASE}\n{shown}"


def test_a_drive_root_is_named_by_its_path(target: FolderDropTarget, tmp_path: Path) -> None:
    """PO-3: a drive root's base name is empty; it shows as `str(path)` - on
    Windows `C:\\`, on POSIX `/`."""
    root = Path(tmp_path.anchor)
    assert root.name == "", f"precondition: {root!r} has a base name"
    assert root.is_dir()

    event = _enter(target, _local(root))

    assert event.isAccepted(), "a drag of a drive root was refused"
    assert _hover_shot(target) == _hover("hover-valid", RELEASE, str(root))


# =============================================================================
# AC-2: files, or several items, are hover-invalid; refused; restored
# =============================================================================


def _items(tmp_path: Path, spec: str) -> list[Path]:
    """`spec` is a string of `f` (file), `d` (folder) and `m` (missing path),
    in drag order."""
    made: list[Path] = []
    for i, kind in enumerate(spec):
        if kind == "d":
            made.append(_folder(tmp_path, f"folder {i}"))
        elif kind == "f":
            made.append(_file(tmp_path, f"page {i:03d}.png"))
        else:
            made.append(tmp_path / f"ghost {i}.png")
    return made


INVALID = [
    ("f", NOT_FILES, "You are dragging a file: page 000.png."),
    ("m", NOT_FILES, "You are dragging a file: ghost 0.png."),
    ("ff", NOT_FILES, "You are dragging 2 files."),
    ("fff", NOT_FILES, "You are dragging 3 files."),
    ("dd", ONE_FOLDER, "You are dragging 2 folders. Drop them one at a time."),
    ("ddd", ONE_FOLDER, "You are dragging 3 folders. Drop them one at a time."),
    ("fd", NOT_FILES, "You are dragging 1 file and 1 folder."),
    ("dfd", NOT_FILES, "You are dragging 1 file and 2 folders."),
    ("dfff", NOT_FILES, "You are dragging 3 files and 1 folder."),
    ("ddff", NOT_FILES, "You are dragging 2 files and 2 folders."),
]
INVALID_IDS = [
    "one-file",
    "one-missing-path-is-a-file",
    "two-files",
    "three-files",
    "two-folders",
    "three-folders",
    "one-file-one-folder",
    "one-file-two-folders",
    "three-files-one-folder",
    "two-files-two-folders",
]


@pytest.mark.parametrize(("spec", "headline", "body"), INVALID, ids=INVALID_IDS)
def test_a_drag_of_files_or_several_items_is_refused_and_says_what_was_dragged(
    target: FolderDropTarget, pre: str, tmp_path: Path, spec: str, headline: str, body: str
) -> None:
    _assert_pre(target, pre)

    event = _enter(target, _local(*_items(tmp_path, spec)))

    assert not event.isAccepted(), f"a drag of {spec!r} was accepted"
    assert _hover_shot(target) == _hover("hover-invalid", headline, body)
    assert _part(target, "headline").isVisibleTo(target), "the hover-invalid headline is hidden"
    assert _part(target, "body").isVisibleTo(target), "what was dragged is not shown"


def test_a_long_file_name_is_cut_like_a_folder_name(
    target: FolderDropTarget, tmp_path: Path
) -> None:
    """The truncation rule applies to both `{name}` slots."""
    _enter(target, _local(_file(tmp_path, LONG)))

    assert target.state == "hover-invalid"
    assert _part(target, "body").text() == f"You are dragging a file: {LONG_CUT}."


@pytest.mark.parametrize("spec", ["f", "dd", "fd"], ids=["one-file", "two-folders", "mixed"])
def test_an_invalid_drag_that_leaves_restores_the_previous_state_unchanged(
    target: FolderDropTarget, pre: str, tmp_path: Path, spec: str
) -> None:
    before = _assert_pre(target, pre)
    _enter(target, _local(*_items(tmp_path, spec)))
    assert target.state == "hover-invalid", "precondition: the drag did not enter hover-invalid"

    _leave(target)

    assert _snapshot(target) == before


@pytest.mark.parametrize("spec", ["f", "dd", "fd"], ids=["one-file", "two-folders", "mixed"])
def test_dropping_an_invalid_drag_is_refused_emits_nothing_and_restores_the_state(
    target: FolderDropTarget, pre: str, tmp_path: Path, spec: str
) -> None:
    """Delivered straight to the widget (C-3): through `sendEvent` this drop
    would never reach the handler and the test would prove nothing (DV-2)."""
    before = _assert_pre(target, pre)
    dropped, activated = _record(target)
    mime = _local(*_items(tmp_path, spec))
    assert not _enter(target, mime).isAccepted(), "precondition: the drag was accepted"
    assert target.state == "hover-invalid", "precondition: the drag did not enter hover-invalid"

    drop = _drop_directly(target, mime)

    assert dropped == [], f"an invalid drop emitted dropped{dropped!r}"
    assert not drop.isAccepted(), "an invalid drop was accepted"
    assert activated == [], "a drop activated the target"
    assert _snapshot(target) == before


def test_an_invalid_drop_on_the_window_opens_nothing_and_writes_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    tmp_path: Path,
    undecodable: Path,
    source: Path,
) -> None:
    """Two folders, each of which would do something if handed over."""
    opener = Opener(app_module.open_folder)
    chooser = Chooser()
    window = _intake(qtbot, windows, opener, chooser)
    target = _target(window)
    before = _snapshot(target)
    tree = _tree(tmp_path)
    mime = _local(source, undecodable)
    assert not _enter(target, mime).isAccepted(), "precondition: two folders were accepted"

    _drop_directly(target, mime)
    _settle()

    assert opener.calls == [], f"an invalid drop called open_folder with {opener.calls!r}"
    assert chooser.parents == [], "an invalid drop asked the chooser"
    assert window.opened is None
    assert window.isVisible(), "the intake window closed on an invalid drop"
    assert _snapshot(target) == before
    assert _tree(tmp_path) == tree, "an invalid drop wrote something"


# =============================================================================
# AC-3: one dropped folder has the outcome of choosing it
# =============================================================================


def test_a_valid_drop_is_accepted_and_emits_the_dropped_path_once_unresolved(
    target: FolderDropTarget, tmp_path: Path
) -> None:
    """`Path(url.toLocalFile())` as dropped - `..` and all; resolving is
    `open_folder`'s job (MT-055 C-1)."""
    _folder(tmp_path, "sibling")
    folder = _folder(tmp_path, "Chapter 12")
    dotted = tmp_path / "sibling" / ".." / "Chapter 12"
    assert dotted.is_dir() and dotted != folder
    dropped, activated = _record(target)
    mime = _local(dotted)
    assert _enter(target, mime).isAccepted(), "precondition: the folder was refused"

    drop = _drop_as_qt_would(target, mime)

    assert drop.isAccepted(), "a valid drop was not accepted"
    assert dropped == [dotted], f"dropped emitted {dropped!r}"
    assert all(type(p) is type(dotted) for p in dropped), "dropped did not carry a Path"
    assert activated == [], "a drop activated the target"


def test_a_valid_drop_restores_the_pre_drag_state(
    target: FolderDropTarget, pre: str, tmp_path: Path
) -> None:
    """Qt sends no leave after a drop: the drop handler restores (C-1)."""
    before = _assert_pre(target, pre)
    mime = _local(_folder(tmp_path, "Chapter 12"))
    _enter(target, mime)
    assert target.state == "hover-valid", "precondition: the drag did not enter hover-valid"

    _drop_as_qt_would(target, mime)

    assert _snapshot(target) == before


def test_a_dropped_folder_goes_to_open_folder_once_and_never_to_the_chooser(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    tmp_path: Path,
) -> None:
    folder = _folder(tmp_path, "Chapter 12")
    opener = Opener(reason="the stub's reason")
    chooser = Chooser()
    window = _intake(qtbot, windows, opener, chooser)
    target = _target(window)
    mime = _local(folder)
    assert _enter(target, mime).isAccepted(), "precondition: the folder was refused"

    drop = _drop_as_qt_would(target, mime)
    _settle()

    assert drop.isAccepted()
    assert opener.calls == [folder], f"open_folder was called with {opener.calls!r}"
    assert chooser.parents == [], "a drop asked the chooser"
    assert window.opened is None
    assert window.isVisible()
    snap = _snapshot(target)
    assert snap["state"] == "error"
    assert snap["headline"] == "the stub's reason"
    assert snap["body"] == ""
    assert snap["affordance"] == AFFORDANCE_ERROR
    assert snap["description"] == "the stub's reason"


def test_a_dropped_folder_whose_opener_returns_a_window_shows_it_then_closes(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    tmp_path: Path,
) -> None:
    folder = _folder(tmp_path, "Chapter 12")
    handed = QMainWindow()
    qtbot.addWidget(handed)
    opener = Opener(lambda _: handed)
    window = _intake(qtbot, windows, opener, Chooser())
    at_close: list[bool] = []

    class CloseWatch(QObject):
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.Close:
                at_close.append(handed.isVisible())
            return False

    watch = CloseWatch(window)
    window.installEventFilter(watch)
    target = _target(window)
    mime = _local(folder)
    assert _enter(target, mime).isAccepted(), "precondition: the folder was refused"

    _drop_as_qt_would(target, mime)
    _settle()

    assert opener.calls == [folder]
    assert window.opened is handed
    assert handed.isVisible(), "the opened window was not shown"
    assert not window.isVisible(), "the intake window is still open"
    assert at_close == [True], f"Close events, and whether `opened` was visible: {at_close!r}"


def _real_intake(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MainWindow, Opener]:
    """`build_window([])` - the real `mangatl.app.open_folder` behind a recorder
    put into `mangatl.app`'s own namespace, so the window is handed exactly what
    the command line uses."""
    opener = Opener(app_module.open_folder)
    monkeypatch.setattr(app_module, "open_folder", opener)
    window = app_module.build_window([])
    assert isinstance(window, MainWindow)
    _show(qtbot, windows, window)
    return window, opener


def _drop_folder(target: QWidget, folder: Path) -> None:
    mime = _local(folder)
    assert _enter(target, mime).isAccepted(), "precondition: the folder was refused"
    _drop_as_qt_would(target, mime)
    _settle()


def test_a_dropped_folder_with_a_project_opens_the_review_workspace(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
) -> None:
    window, opener = _real_intake(qtbot, windows, monkeypatch)

    _drop_folder(_target(window), source)

    assert opener.calls == [source], f"open_folder was called with {opener.calls!r}"
    assert isinstance(window.opened, Workspace), f"opened is {type(window.opened).__name__}"
    qtbot.addWidget(window.opened)
    assert window.opened.isVisible(), "the Workspace was not shown"
    strip = window.opened.page_strip
    assert [strip.item(i).text() for i in range(strip.count())] == list(PAGES)
    assert strip.currentRow() == 0
    assert not window.isVisible(), "the intake window is still open"


def test_a_dropped_folder_with_an_undecodable_page_names_it_and_writes_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    undecodable: Path,
) -> None:
    """MT-057 AC-6, dropped path (was MT-054's no-project text)."""
    tree = _tree(tmp_path)
    window, opener = _real_intake(qtbot, windows, monkeypatch)
    target = _target(window)

    _drop_folder(target, undecodable)

    assert opener.calls == [undecodable]
    assert window.opened is None
    assert window.isVisible(), "the intake window closed on a folder with no project"
    assert window.findChild(QWidget, "chapter-summary") is None, "a summary was created"
    text = _undecodable("001.png")
    snap = _snapshot(target)
    assert snap["state"] == "error"
    assert snap["headline"] == text
    assert snap["body"] == ""
    assert snap["affordance"] == AFFORDANCE_ERROR
    assert snap["description"] == text
    assert _tree(tmp_path) == tree, "dropping a folder with no project wrote something"


def test_a_dropped_folder_of_pages_shows_its_chapter_summary_and_writes_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    """MT-057 AC-1, dropped path: the drop shares the chooser's hand-over.
    Natural order (`p9, p10`) differs from lexical and listing order."""
    from mangatl.ui.summary import ChapterSummary  # MT-057; absent until its GREEN

    folder = _folder(tmp_path, "Chapter 12")
    for name in ("p10.png", "p9.png"):
        (folder / name).write_bytes(page_png)
    tree = _tree(tmp_path)
    window, opener = _real_intake(qtbot, windows, monkeypatch)

    _drop_folder(_target(window), folder)

    assert opener.calls == [folder]
    assert window.opened is None
    assert window.isVisible(), "the intake window closed on a folder of pages"
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary), f"central widget is {type(summary).__name__}"
    texts = [
        label.text() if label is not None else None
        for label in (
            summary.findChild(QLabel, name)
            for name in ("summary-name", "summary-count", "summary-first", "summary-last")
        )
    ]
    assert texts == ["Chapter 12", "2 pages", "First page: p9.png", "Last page: p10.png"]
    assert _tree(tmp_path) == tree, "dropping a folder of pages wrote something"
    assert not folder.with_name("Chapter 12.mtproj").exists()


def test_a_dropped_project_from_a_newer_build_shows_its_message(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: Path,
) -> None:
    expected = _make_too_new(source)
    assert "upgrade mangatl" in expected
    tree = _tree(tmp_path)
    window, _ = _real_intake(qtbot, windows, monkeypatch)
    target = _target(window)

    _drop_folder(target, source)

    assert window.opened is None
    snap = _snapshot(target)
    assert snap["state"] == "error"
    assert snap["headline"] == expected
    assert snap["affordance"] == AFFORDANCE_ERROR
    assert _tree(tmp_path) == tree, "dropping a too-new project wrote something"


# =============================================================================
# AC-4: every state change changes the headline wording (A-10)
# =============================================================================


@pytest.mark.parametrize("spec", ["d", "f", "dd", "fd"], ids=["valid", "file", "folders", "mixed"])
def test_every_hover_state_changes_the_headline_wording(
    target: FolderDropTarget, pre: str, tmp_path: Path, spec: str
) -> None:
    before = _assert_pre(target, pre)["headline"]

    _enter(target, _local(*_items(tmp_path, spec)))
    during = _part(target, "headline").text()
    _leave(target)
    after = _part(target, "headline").text()

    assert target.state == pre
    assert during not in ("", before), f"the headline stayed {during!r} while the state changed"
    assert during in (RELEASE, NOT_FILES, ONE_FOLDER), f"unexpected headline {during!r}"
    assert after == before, f"the headline did not return: {after!r}"


def test_valid_and_invalid_hover_are_told_apart_by_the_headline(
    target: FolderDropTarget, tmp_path: Path
) -> None:
    valid, invalid = _folder(tmp_path, "one"), _file(tmp_path, "one.png")

    _enter(target, _local(valid))
    valid_headline = _part(target, "headline").text()
    _leave(target)
    _enter(target, _local(invalid))
    invalid_headline = _part(target, "headline").text()

    assert (valid_headline, invalid_headline) == (RELEASE, NOT_FILES)


# =============================================================================
# AC-5: a non-local or URL-less drag is ignored - nothing changes
# =============================================================================


def _ignored(tmp_path: Path, case: str) -> QMimeData:
    if case == "web":
        return _mime(QUrl(WEB))
    if case == "folder-and-web":
        return _mime(QUrl.fromLocalFile(str(_folder(tmp_path, "Chapter 12"))), QUrl(WEB))
    if case == "web-and-file":
        return _mime(QUrl(WEB), QUrl.fromLocalFile(str(_file(tmp_path, "page.png"))))
    mime = QMimeData()
    if case == "text-only":
        mime.setText("x")
    return mime


IGNORED = ["web", "folder-and-web", "web-and-file", "text-only", "empty"]


@pytest.mark.parametrize("case", IGNORED)
def test_a_drag_with_a_non_local_url_or_no_urls_changes_nothing_and_is_refused(
    target: FolderDropTarget, pre: str, tmp_path: Path, case: str
) -> None:
    before = _assert_pre(target, pre)
    mime = _ignored(tmp_path, case)

    event = _enter(target, mime)

    assert not event.isAccepted(), f"a {case} drag was accepted"
    assert _snapshot(target) == before, f"a {case} drag changed the target"


@pytest.mark.parametrize("case", IGNORED)
def test_an_ignored_drag_dropped_anyway_emits_nothing_and_changes_nothing(
    target: FolderDropTarget, pre: str, tmp_path: Path, case: str
) -> None:
    before = _assert_pre(target, pre)
    dropped, _ = _record(target)
    mime = _ignored(tmp_path, case)
    _enter(target, mime)

    drop = _drop_directly(target, mime)
    _leave(target)

    assert dropped == [], f"a {case} drop emitted dropped{dropped!r}"
    assert not drop.isAccepted(), f"a {case} drop was accepted"
    assert _snapshot(target) == before
