"""The folder intake: `FolderDropTarget` and the folder dialog (MT-055).

`components.md` §2 makes the whole region one control - role Button, accessible
name "Choose chapter folder" (`accessibility.md` A-08) - and PO-5 keeps it the
*only* one: the "Choose folder…" affordance inside it is a label, clicked
through to the region, never a second focus stop or a second Button. So the
target is a `QAbstractButton` holding three plain, unselectable `QLabel`s. A
left click on any of them reaches the button; Space activates it as it does any
button; Return and Enter do not activate a bare `QAbstractButton`, so they are
handled here.

The target knows nothing about folders: it emits `activated`, and whoever owns
it (`MainWindow`) asks the chooser. Drag-and-drop is MT-056.

`choose_folder_dialog` is the real chooser. It reads `QFileDialog` through this
module's namespace at call time, so a test can stand in for the native dialog.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainter, QPaintEvent
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

EMPTY = "empty"
ERROR = "error"

_ACTIVATION_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


class FolderDropTarget(QAbstractButton):
    """The intake region: one control, in the **empty** or **error** state."""

    activated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(TARGET_OBJECT_NAME)
        self.setAccessibleName(TARGET_ACCESSIBLE_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        self._show(HEADLINE_EMPTY, BODY_EMPTY, AFFORDANCE_EMPTY)

    def show_error(self, text: str) -> None:
        """The error state (PO-8): the reason is the headline, verbatim."""
        self.state = ERROR
        self._show(text, "", AFFORDANCE_ERROR)

    def _show(self, headline: str, body: str, affordance: str) -> None:
        self.headline.setText(headline)
        self.body.setText(body)
        self.body.setVisible(bool(body))
        self.affordance.setText(affordance)
        # The visible words are the description, so a screen reader hears the
        # reason (and the command) the error state carries.
        self.setAccessibleDescription("\n".join(t for t in (headline, body) if t))

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
