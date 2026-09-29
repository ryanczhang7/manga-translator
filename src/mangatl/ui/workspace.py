"""The review workspace: the page large, the lines docked beside it.

`layout.md` ("Review workspace", "Window") and `components.md` §3 settle every
number here; they are read out, not tuned. Three regions sit in one horizontal
splitter - `PageStrip` (96 px fixed), `PageCanvas` (all remaining width) and
`TranslationColumn` (340 px, user-resizable 280-560) - between a 48 px header
and a 44 px footer.

**The canvas carries the entire splitter stretch factor.** That is the brief's
"the art is the largest thing on screen at all times" made mechanical:
enlarging the window enlarges only the art (MT-015 AC-2).

The 1440 px breakpoint in `layout.md` is not built yet (MT-015 PO-1, MT-048).
Header and footer content, the column's rows, and wiring this window into
`mangatl.app` are later stories (PO-4).
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QListWidget, QMainWindow, QSplitter, QVBoxLayout, QWidget

from mangatl.domain.page import Chapter
from mangatl.store.project import Project
from mangatl.ui.canvas import PageCanvas

__all__ = [
    "CANVAS_MIN_WIDTH",
    "COLUMN_DEFAULT_WIDTH",
    "COLUMN_MAX_WIDTH",
    "COLUMN_MIN_WIDTH",
    "FOOTER_HEIGHT",
    "HEADER_HEIGHT",
    "STRIP_WIDTH",
    "PageStrip",
    "TranslationColumn",
    "Workspace",
]

STRIP_WIDTH = 96
COLUMN_DEFAULT_WIDTH = 340
COLUMN_MIN_WIDTH = 280
COLUMN_MAX_WIDTH = 560
CANVAS_MIN_WIDTH = 520
HEADER_HEIGHT = 48
FOOTER_HEIGHT = 44


class PageStrip(QListWidget):
    """The chapter's pages, one item per page in ordinal order, by filename."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageStrip")
        self.setAccessibleName("Pages")
        self.setFixedWidth(STRIP_WIDTH)


class TranslationColumn(QWidget):
    """The docked column of lines. Empty in MT-015; its rows are MT-016."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("translationColumn")
        self.setAccessibleName("Translations")
        self.setMinimumWidth(COLUMN_MIN_WIDTH)
        self.setMaximumWidth(COLUMN_MAX_WIDTH)


class Workspace(QMainWindow):
    """The window a chapter is reviewed in."""

    #: `layout.md` "Window": the minimum is enforced, not advisory (AC-4).
    MIN_SIZE: tuple[int, int] = (1100, 720)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(*self.MIN_SIZE)
        self._chapter: Chapter | None = None

        self.header = QWidget()
        self.header.setObjectName("workspaceHeader")
        self.header.setFixedHeight(HEADER_HEIGHT)
        self.footer = QWidget()
        self.footer.setObjectName("workspaceFooter")
        self.footer.setFixedHeight(FOOTER_HEIGHT)

        self.page_strip = PageStrip()
        self.page_canvas = PageCanvas()
        self.page_canvas.setMinimumWidth(CANVAS_MIN_WIDTH)
        self.translation_column = TranslationColumn()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.page_strip)
        self.splitter.addWidget(self.page_canvas)
        self.splitter.addWidget(self.translation_column)
        # The ONLY non-zero stretch: a wider window widens the art and nothing else.
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([STRIP_WIDTH, CANVAS_MIN_WIDTH, COLUMN_DEFAULT_WIDTH])

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.footer)
        self.setCentralWidget(body)

        self.page_strip.currentRowChanged.connect(self.show_page)

    def load_chapter(self, project: Project) -> None:
        """List the project's pages in the strip; nothing is selected yet."""
        self._chapter = project.chapter
        with QSignalBlocker(self.page_strip):
            self.page_strip.clear()
            for page in self._chapter.pages:
                self.page_strip.addItem(page.filename)
        self.page_canvas.set_page(None)

    def show_page(self, ordinal: int) -> None:
        """Decode page `ordinal` synchronously and show it, or show why it failed."""
        assert self._chapter is not None, "show_page before load_chapter"
        page = self._chapter.pages[ordinal]
        pixmap = QPixmap(str(self._chapter.source_dir / page.filename))
        if pixmap.isNull():
            self.page_canvas.set_page(None, error=page.filename)
        else:
            self.page_canvas.set_page(pixmap)
