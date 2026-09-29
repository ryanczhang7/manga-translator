"""The review workspace: the page large, the lines docked beside it.

`layout.md` ("Review workspace", "Window") and `components.md` §3 settle every
number here; they are read out, not tuned. Three regions sit in one horizontal
splitter - `PageStrip` (96 px fixed), `PageCanvas` (all remaining width) and
`TranslationColumn` (340 px, user-resizable 280-560) - between a 48 px header
and a 44 px footer.

**The canvas carries the entire splitter stretch factor.** That is the brief's
"the art is the largest thing on screen at all times" made mechanical:
enlarging the window enlarges only the art (MT-015 AC-2).

**The bubble <-> line link** (MT-016, `components.md` §4) is wired here. One
`LinkController` owns selection and hover; the canvas and the column both render
from it and neither owns it. Selection restyles the markers, pans the canvas
by the minimum (never zooming), selects and scrolls to the row and is announced
through the live region. Hover restyles the markers and the row's ground ONLY:
it never pans the canvas and never scrolls the list (§4.4).

The 1440 px breakpoint in `layout.md` is not built yet (MT-015 PO-1, MT-048).
Header and footer content and wiring this window into `mangatl.app` are later
stories; row editing is MT-017 (the editor is read-only, MT-016 PO-1).
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QEnterEvent, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mangatl.domain.page import Chapter
from mangatl.store.project import Project
from mangatl.ui.canvas import PageCanvas
from mangatl.ui.link import LinkController, LiveRegion, OrderedRegion

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
    "TranslationRow",
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


def _row_accessible_text(
    ordinal: int, total: int, japanese: str | None, english: str | None
) -> str:
    """`components.md` §5: the row's accessible name, ordinal first."""
    ja = japanese if japanese is not None else "not read"
    en = english if english is not None else "not translated"
    return f"Bubble {ordinal} of {total}. Japanese: {ja}. English: {en}. machine proposal."


class TranslationRow(QWidget):
    """One line: its ordinal badge leading, then its (read-only, PO-1) editor.

    The pointer entering or leaving the row is reported, not acted on; the row's
    hover ground is the dynamic property `hovered`, set from the link state.
    (`QListWidget.itemEntered` never fires for an item-widget row: the row takes
    the pointer. MT-016 Contract, RED amendment.)
    """

    entered = Signal(int)
    left = Signal(int)

    def __init__(self, region_id: int, english: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("translationRow")
        self.region_id = region_id
        self.setProperty("hovered", False)
        self.badge = QLabel(str(region_id + 1))
        self.badge.setObjectName("rowBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor = QLineEdit(english or "")
        self.editor.setObjectName("rowEditor")
        self.editor.setReadOnly(True)
        layout = QHBoxLayout(self)
        layout.addWidget(self.badge)
        layout.addWidget(self.editor, 1)

    def set_hovered(self, hovered: bool) -> None:
        """Take or drop the hover ground (re-polished so theme.qss sees it)."""
        if bool(self.property("hovered")) == hovered:
            return
        self.setProperty("hovered", hovered)
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event: QEnterEvent) -> None:
        self.entered.emit(self.region_id)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.left.emit(self.region_id)
        super().leaveEvent(event)


class TranslationColumn(QWidget):
    """The docked column of lines: one row per region, in region_id order."""

    #: The pointer entered a row (its region_id) or left one (the region_id it left).
    rowEntered = Signal(int)
    rowLeft = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("translationColumn")
        self.setAccessibleName("Translations")
        self.setMinimumWidth(COLUMN_MIN_WIDTH)
        self.setMaximumWidth(COLUMN_MAX_WIDTH)
        self.list = QListWidget()
        self.list.setObjectName("translationList")
        self.list.setAccessibleName("Lines")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        self._rows: list[TranslationRow] = []

    def set_rows(
        self,
        regions: Sequence[OrderedRegion],
        japanese: Sequence[str | None],
        english: Sequence[str | None],
    ) -> None:
        """Replace every row. The three sequences are parallel."""
        with QSignalBlocker(self.list):
            self.list.clear()
            self._rows = []
            total = len(regions)
            for region, ja, en in zip(regions, japanese, english, strict=True):
                row = TranslationRow(region.region_id, en)
                row.entered.connect(self.rowEntered.emit)
                row.left.connect(self.rowLeft.emit)
                item = QListWidgetItem()
                item.setData(
                    Qt.ItemDataRole.AccessibleTextRole,
                    _row_accessible_text(region.ordinal, total, ja, en),
                )
                item.setSizeHint(row.sizeHint())
                self.list.addItem(item)
                self.list.setItemWidget(item, row)
                self._rows.append(row)

    def row(self, region_id: int) -> TranslationRow:
        return self._rows[region_id]

    def select(self, region_id: int | None) -> None:
        """Make `region_id`'s row current and scroll it into view (None clears)."""
        if region_id is None:
            self.list.setCurrentRow(-1)
            return
        self.list.setCurrentRow(region_id)
        self.list.scrollToItem(self.list.item(region_id))

    def set_hovered(self, region_id: int | None) -> None:
        """Give only `region_id`'s row its hover ground. Never scrolls."""
        for row in self._rows:
            row.set_hovered(row.region_id == region_id)


class Workspace(QMainWindow):
    """The window a chapter is reviewed in."""

    #: `layout.md` "Window": the minimum is enforced, not advisory (AC-4).
    MIN_SIZE: tuple[int, int] = (1100, 720)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(*self.MIN_SIZE)
        self._chapter: Chapter | None = None
        self._project: Project | None = None
        self._page_ordinal: int | None = None

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

        self.link = LinkController(self)
        # Outside every layout and off-screen: read, never seen (§4.9).
        self.live_region = LiveRegion(body)

        self.page_strip.currentRowChanged.connect(self.show_page)
        self.link.selectionChanged.connect(self._on_selection_changed)
        self.link.hoverChanged.connect(self._on_hover_changed)
        self.page_canvas.regionClicked.connect(self.link.select)
        self.page_canvas.regionHovered.connect(self.link.hover)
        self.page_canvas.editRequested.connect(self._edit_selected)
        self.translation_column.list.currentRowChanged.connect(self._on_current_row_changed)
        self.translation_column.rowEntered.connect(self.link.hover)
        self.translation_column.rowLeft.connect(self._on_row_left)

    def load_chapter(self, project: Project) -> None:
        """List the project's pages in the strip; nothing is selected yet."""
        self._project = project
        self._chapter = project.chapter
        self._page_ordinal = None
        with QSignalBlocker(self.page_strip):
            self.page_strip.clear()
            for page in self._chapter.pages:
                self.page_strip.addItem(page.filename)
        self.page_canvas.set_page(None)
        self.set_regions([], [], [])

    def show_page(self, ordinal: int) -> None:
        """Decode page `ordinal` synchronously and show it with its stored
        regions and lines (MT-016 PO-2), or show why it failed."""
        assert self._chapter is not None, "show_page before load_chapter"
        self._page_ordinal = ordinal
        page = self._chapter.pages[ordinal]
        pixmap = QPixmap(str(self._chapter.source_dir / page.filename))
        if pixmap.isNull():
            self.page_canvas.set_page(None, error=page.filename)
            self.set_regions([], [], [])
            return
        self.page_canvas.set_page(pixmap)
        self._load_regions(ordinal)

    def set_regions(
        self,
        regions: Sequence[OrderedRegion],
        japanese: Sequence[str | None],
        english: Sequence[str | None],
    ) -> None:
        """Populate the canvas and the column; hover cleared, and the first
        region selected (§4.1), or nothing on a page with no regions."""
        self.link.hover(None)
        self.link.select(None)
        self.page_canvas.set_regions(regions)
        self.translation_column.set_rows(regions, japanese, english)
        if regions:
            self.link.select(0)

    def _load_regions(self, ordinal: int) -> None:
        """PO-2: the page's regions, lines and proposals, padded with None."""
        assert self._project is not None
        stored = self._project.read_regions(ordinal)
        lines = self._project.read_lines(ordinal)
        proposed = self._project.read_proposed(ordinal)
        regions = [
            OrderedRegion(region_id=index, polygon=region.polygon)
            for index, region in enumerate(stored)
        ]
        japanese: list[str | None] = []
        english: list[str | None] = []
        for index in range(len(regions)):
            line = lines[index] if index < len(lines) else None
            japanese.append(None if line is None or line.ocr_empty else line.text)
            english.append(proposed[index] if index < len(proposed) else None)
        self.set_regions(regions, japanese, english)

    def _on_current_row_changed(self, row: int) -> None:
        self.link.select(row if row >= 0 else None)

    def _on_row_left(self, region_id: int) -> None:
        # Only the row that is hovered may clear it: leaving one row for the
        # next must not wipe the next row's hover.
        if self.link.state.hovered_region_id == region_id:
            self.link.hover(None)

    def _on_selection_changed(self, region_id: int | None) -> None:
        self.page_canvas.set_link_state(self.link.state)
        with QSignalBlocker(self.translation_column.list):
            self.translation_column.select(region_id)
        if region_id is None:
            return
        self.page_canvas.reveal(region_id)
        announcement = f"Bubble {region_id + 1} of {len(self.page_canvas.markers)} selected."
        if self._chapter is not None and self._page_ordinal is not None:
            announcement += f" Page {self._page_ordinal + 1} of {len(self._chapter.pages)}."
        self.live_region.announce(announcement)

    def _on_hover_changed(self, region_id: int | None) -> None:
        self.page_canvas.set_link_state(self.link.state)
        self.translation_column.set_hovered(region_id)

    def _edit_selected(self) -> None:
        selected = self.link.state.selected_region_id
        if selected is not None:
            self.translation_column.row(selected).editor.setFocus(Qt.FocusReason.OtherFocusReason)
