"""The application's one window.

MT-001's walking skeleton: it opens, it is identifiable, and it closes. The
real workspace - the page canvas with the lines docked beside it - is MT-015.

With a `notice` (MT-054 C-5) the window says one thing instead: why no chapter
could be opened, and what to do about it. The notice is the whole content of
the window, so it is its accessible name, plain text (a folder name holding
`<` is not markup) and selectable, so the command it names can be copied.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget

__all__ = ["CANVAS_ACCESSIBLE_NAME", "NOTICE_OBJECT_NAME", "WINDOW_TITLE", "MainWindow"]

WINDOW_TITLE = "mangatl"
CANVAS_ACCESSIBLE_NAME = "Page canvas"
NOTICE_OBJECT_NAME = "notice"


class MainWindow(QMainWindow):
    """The single top-level window."""

    def __init__(self, notice: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        if notice is not None:
            self.setCentralWidget(_notice_label(notice, self))
            return
        canvas = QWidget(self)
        # An accessible name from the first commit, not retrofitted: the
        # accessibility floor in docs/wiki/design/accessibility.md applies to
        # every widget the user can reach, and the canvas is the whole product.
        canvas.setAccessibleName(CANVAS_ACCESSIBLE_NAME)
        self.setCentralWidget(canvas)


def _notice_label(notice: str, parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName(NOTICE_OBJECT_NAME)
    # Before the text, so it is never interpreted as rich text.
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(notice)
    label.setAccessibleName(notice)
    label.setWordWrap(True)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    return label
