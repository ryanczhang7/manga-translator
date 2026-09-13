"""The application's one window.

MT-001's walking skeleton: it opens, it is identifiable, and it closes. The
real workspace - the page canvas with the lines docked beside it - is MT-015.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QWidget

__all__ = ["CANVAS_ACCESSIBLE_NAME", "WINDOW_TITLE", "MainWindow"]

WINDOW_TITLE = "mangatl"
CANVAS_ACCESSIBLE_NAME = "Page canvas"


class MainWindow(QMainWindow):
    """The single top-level window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        canvas = QWidget(self)
        # An accessible name from the first commit, not retrofitted: the
        # accessibility floor in docs/wiki/design/accessibility.md applies to
        # every widget the user can reach, and the canvas is the whole product.
        canvas.setAccessibleName(CANVAS_ACCESSIBLE_NAME)
        self.setCentralWidget(canvas)
