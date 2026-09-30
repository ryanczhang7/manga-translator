"""The folder intake: `FolderDropTarget` and the folder dialog (MT-055, MT-056).

`components.md` §2 makes the whole region one control - role Button, accessible
name "Choose chapter folder" (`accessibility.md` A-08) - and PO-5 keeps it the
*only* one: the "Choose folder…" affordance inside it is a label, clicked
through to the region, never a second focus stop or a second Button. So the
target is a `QAbstractButton` holding three plain, unselectable `QLabel`s. A
left click on any of them reaches the button; Space activates it as it does any
button; Return and Enter do not activate a bare `QAbstractButton`, so they are
handled here.

The target knows nothing about what a folder means: it emits `activated`, and
whoever owns it (`MainWindow`) asks the chooser; or, when one local folder is
dropped on it, it emits `dropped` with that folder's `Path` as dropped (MT-056).

A drag is classified when it enters (`components.md` §2 "Drag copy"): one
existing local directory is **hover-valid** and accepted; files, or several
items, are **hover-invalid** and refused, with a headline and body saying what
was dragged; a drag with no URLs, or with any non-local URL, is ignored and
changes nothing. The state before the drag is remembered and put back on leave
and on drop - Qt sends no leave after a drop.

`choose_folder_dialog` is the real chooser. It reads `QFileDialog` through this
module's namespace at call time, so a test can stand in for the native dialog.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QKeyEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFileDialog,
    QLabel,
    QStyle,
    QStyleOption,
    QStyleOptionFocusRect,
    QVBoxLayout,
    QWidget,
)

__all__ = ["DIALOG_CAPTION", "FolderDropTarget", "choose_folder_dialog"]

TARGET_OBJECT_NAME = "folder-drop-target"
TARGET_ACCESSIBLE_NAME = "Choose chapter folder"  # accessibility.md A-08
DIALOG_CAPTION = "Choose chapter folder"

HEADLINE_EMPTY = "Drop a chapter folder here"  # components.md §2, empty row
BODY_EMPTY = "Or choose a folder. Pages are processed in filename order."
AFFORDANCE_EMPTY = "Choose folder…"
AFFORDANCE_ERROR = "Choose a different folder"  # components.md §2, error row

HEADLINE_VALID = "Release to load"  # components.md §2, "Drag copy"
HEADLINE_NOT_FILES = "Drop a folder, not files"
HEADLINE_ONE_FOLDER = "Drop one folder"

#: A `{name}` longer than this is cut in the middle (components.md §2).
NAME_LIMIT = 40

EMPTY = "empty"
ERROR = "error"
HOVER_VALID = "hover-valid"
HOVER_INVALID = "hover-invalid"

_ACTIVATION_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


@dataclass(frozen=True)
class _Shown:
    """What the target shows in one state: enough to put that state back."""

    state: str
    headline: str
    body: str
    affordance: str


class FolderDropTarget(QAbstractButton):
    """The intake region: one control, **empty** or **error** at rest, and
    **hover-valid** or **hover-invalid** while a drag is over it."""

    activated = Signal()
    #: One dropped local folder, exactly as dropped (not resolved).
    dropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(TARGET_OBJECT_NAME)
        self.setAccessibleName(TARGET_ACCESSIBLE_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.headline = _part("headline", self)
        self.body = _part("body", self)
        self.affordance = _part("affordance", self)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        for part in (self.headline, self.body, self.affordance):
            layout.addWidget(part)
        layout.addStretch(1)
        self.clicked.connect(self.activated.emit)
        self.state = EMPTY
        #: The state before the drag in progress; `None` when there is none.
        self._before_drag: _Shown | None = None
        #: The folder a hover-valid drag carries.
        self._drag_folder: Path | None = None
        self._show(_Shown(EMPTY, HEADLINE_EMPTY, BODY_EMPTY, AFFORDANCE_EMPTY))

    def show_error(self, text: str) -> None:
        """The error state (PO-8): the reason is the headline, verbatim."""
        self._show(_Shown(ERROR, text, "", AFFORDANCE_ERROR))

    def _show(self, shown: _Shown) -> None:
        self.state = shown.state
        self.headline.setText(shown.headline)
        self.body.setText(shown.body)
        self.body.setVisible(bool(shown.body))
        self.affordance.setText(shown.affordance)
        self.affordance.setVisible(bool(shown.affordance))
        # The visible words are the description, so a screen reader hears the
        # reason (and the command) the error state carries.
        self.setAccessibleDescription("\n".join(t for t in (shown.headline, shown.body) if t))

    def _current(self) -> _Shown:
        return _Shown(self.state, self.headline.text(), self.body.text(), self.affordance.text())

    def _end_drag(self) -> None:
        """Put back the state from before the drag, if one is in progress."""
        if self._before_drag is not None:
            self._show(self._before_drag)
        self._before_drag = None
        self._drag_folder = None

    # --- drag and drop (MT-056) -------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._end_drag()  # a stale drag Qt never ended must not become "before"
        paths = _local_paths(event.mimeData())
        if paths is None:
            event.ignore()  # AC-5: nothing about the target changes
            return
        self._before_drag = self._current()
        if len(paths) == 1 and paths[0].is_dir():
            self._drag_folder = paths[0]
            self._show(_Shown(HOVER_VALID, HEADLINE_VALID, _display_name(paths[0]), ""))
            event.acceptProposedAction()
            return
        headline, body = _refusal(paths)
        self._show(_Shown(HOVER_INVALID, headline, body, ""))
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._end_drag()

    def dropEvent(self, event: QDropEvent) -> None:
        folder = self._drag_folder if self.state == HOVER_VALID else None
        self._end_drag()  # Qt sends no leave after a drop
        if folder is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.dropped.emit(folder)

    # --- keyboard and painting (MT-055) -----------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in _ACTIVATION_KEYS and not event.isAutoRepeat():
            self.click()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        # QAbstractButton paints nothing itself. The style's widget primitive
        # lets a stylesheet rule for the target draw its ground and border.
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        if self.hasFocus():
            focus = QStyleOptionFocusRect()
            focus.initFrom(self)
            self.style().drawPrimitive(
                QStyle.PrimitiveElement.PE_FrameFocusRect, focus, painter, self
            )


def _local_paths(mime: QMimeData) -> list[Path] | None:
    """The drag's local paths, or `None` when it is to be ignored: no URLs, or
    any URL that is not a local file. The check comes before any `Path` is
    built - a web URL's `toLocalFile()` is `""`, and `Path("")` is the working
    directory, which is a folder."""
    urls = mime.urls()
    if not urls or not all(url.isLocalFile() for url in urls):
        return None
    return [Path(url.toLocalFile()) for url in urls]


def _refusal(paths: list[Path]) -> tuple[str, str]:
    """The hover-invalid headline and body for a drag that is not one folder."""
    folders = sum(1 for path in paths if path.is_dir())
    files = len(paths) - folders
    if folders == 0:
        if files == 1:
            return HEADLINE_NOT_FILES, f"You are dragging a file: {_display_name(paths[0])}."
        return HEADLINE_NOT_FILES, f"You are dragging {files} files."
    if files == 0:
        return HEADLINE_ONE_FOLDER, f"You are dragging {folders} folders. Drop them one at a time."
    return (
        HEADLINE_NOT_FILES,
        f"You are dragging {_count(files, 'file')} and {_count(folders, 'folder')}.",
    )


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _display_name(path: Path) -> str:
    """The base name - the path itself for a drive root (PO-3) - cut in the
    middle when longer than `NAME_LIMIT` characters: first 20, `…`, last 19."""
    name = path.name or str(path)
    if len(name) > NAME_LIMIT:
        return name[:20] + "…" + name[-19:]
    return name


def _part(name: str, parent: QWidget) -> QLabel:
    """A plain, unselectable label: its clicks belong to the region."""
    label = QLabel(parent)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return label


def choose_folder_dialog(parent: QWidget) -> Path | None:
    """Ask the native dialog for one folder; `None` when it is dismissed."""
    chosen = QFileDialog.getExistingDirectory(parent, DIALOG_CAPTION)
    return Path(chosen) if chosen else None
