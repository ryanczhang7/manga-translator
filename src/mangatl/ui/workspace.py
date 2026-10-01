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
it never pans the canvas and never scrolls the list (§4.4). Up/Down/Home/End on
the canvas (MT-050, §4.7) step the selection through the same controller,
without wrapping and without moving focus.

**Review** (MT-017, `components.md` §5-§7). Each row is a `LineEditor` under a
status gutter - a glyph *and* a colour per status, never colour alone - with
its Revert / Accept / Retry line controls always visible when they apply, never
revealed by hover. A row built from a stored line saves through
`store.lines.commit_line`; replacing the rows (a page change) and closing the
window both write any pending save first, so neither drops the user's work.
MT-016 PO-1's read-only editor is superseded: every line is editable (PO-5).

The 1440 px breakpoint in `layout.md` is not built yet (MT-015 PO-1, MT-048).
Header and footer content are later stories. `mangatl.app` opens this window on
a chapter folder (MT-054) and closes the project on `closed`, which is emitted
after the pending saves are written.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QEnterEvent, QPalette, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mangatl.domain.budget import DEFAULT_CEILING
from mangatl.domain.line import Line, LineStatus, effective_text, failure_reason
from mangatl.domain.page import Chapter
from mangatl.store import ledger
from mangatl.store.lines import commit_line, read_review_lines
from mangatl.store.project import Project
from mangatl.ui import tokens_gen
from mangatl.ui.canvas import PageCanvas
from mangatl.ui.cost_readout import CostReadout
from mangatl.ui.line_editor import LineEditor, SaveFn
from mangatl.ui.link import LinkController, LiveRegion, OrderedRegion

__all__ = [
    "CANVAS_MIN_WIDTH",
    "COLUMN_DEFAULT_WIDTH",
    "COLUMN_MAX_WIDTH",
    "COLUMN_MIN_WIDTH",
    "FOOTER_HEIGHT",
    "HEADER_HEIGHT",
    "STATUS_COLOR_TOKENS",
    "STATUS_GLYPHS",
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

#: `components.md` §5's gutter glyphs; `reverted` is a return arrow alone (PO-2).
#: Pairwise distinct, so colour is never the only cue (accessibility.md A-15.7).
STATUS_GLYPHS: dict[LineStatus, str] = {
    "proposed": "\N{WHITE CIRCLE}",
    "accepted": "\N{HEAVY CHECK MARK}",
    "edited": "\N{LOWER RIGHT PENCIL}",
    "reverted": "\N{LEFTWARDS ARROW WITH HOOK}",
    "failed": "\N{WARNING SIGN}",
}

#: `components.md` §5's glyph colours, as tokens: resolved through
#: `tokens_gen.TOKENS`, never spelled here (MT-015 AC-7).
STATUS_COLOR_TOKENS: dict[LineStatus, str] = {
    "proposed": "color.text.muted",
    "accepted": "color.status.success",
    "edited": "color.accent.base",
    "reverted": "color.text.secondary",
    "failed": "color.status.danger",
}

#: `components.md` §5's per-status phrase in the row's accessible name.
_STATUS_PHRASES: dict[LineStatus, str] = {
    "proposed": "machine proposal",
    "accepted": "accepted",
    "edited": "edited",
    "reverted": "edited, then returned to the proposal",
}


class PageStrip(QListWidget):
    """The chapter's pages, one item per page in ordinal order, by filename."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageStrip")
        self.setAccessibleName("Pages")
        self.setFixedWidth(STRIP_WIDTH)


def _row_accessible_text(ordinal: int, total: int, japanese: str | None, line: Line) -> str:
    """`components.md` §5: the row's accessible name, ordinal first, status last.

    `English:` is the row's shown text, and reads "not translated" exactly when
    there is neither a proposal nor committed text (MT-016's rule, C-8's RED
    amendment).
    """
    ja = japanese if japanese is not None else "not read"
    if line.proposed_en is None and line.final_en is None:
        en = "not translated"
    else:
        en = effective_text(line)
    reason = failure_reason(line)
    phrase = f"translation failed: {reason}" if reason is not None else _STATUS_PHRASES[line.status]
    return f"Bubble {ordinal} of {total}. Japanese: {ja}. English: {en}. {phrase}."


def _unsaved_line(reading_index: int, japanese: str | None, english: str | None) -> Line:
    """The line MT-016's three-argument rows stand for: a proposal, unreviewed."""
    return Line(
        reading_index=reading_index,
        source_ja=japanese or "",
        proposed_en=english,
        final_en=None,
        status="proposed",
        edited_at=None,
    )


class TranslationRow(QWidget):
    """One line: `[status gutter][ordinal badge][editor][actions]` (§5 anatomy).

    The gutter, the controls and the caption are the row's and follow the
    editor's state: re-rendered on every commit and on every save outcome.
    Which control shows depends on status only - Revert on `edited`, Accept on
    `proposed`, Retry line on `failed` - and never on hover or selection.

    The pointer entering or leaving the row is reported, not acted on; the row's
    hover ground is the dynamic property `hovered`, set from the link state.
    (`QListWidget.itemEntered` never fires for an item-widget row: the row takes
    the pointer. MT-016 Contract, RED amendment.)
    """

    entered = Signal(int)
    left = Signal(int)
    #: Retry line was pressed (PO-4: nothing is connected to it yet).
    retryRequested = Signal(int)
    #: The row re-rendered after a commit or a save outcome.
    rendered = Signal()

    def __init__(
        self, region_id: int, line: Line, save: SaveFn | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("translationRow")
        self.region_id = region_id
        self.setProperty("hovered", False)
        self._save_error: str | None = None

        self.gutter = QLabel()
        self.gutter.setObjectName("rowGutter")
        self.gutter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge = QLabel(str(region_id + 1))
        self.badge.setObjectName("rowBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor = LineEditor(line, save)
        self.editor.setObjectName("rowEditor")
        self.error_caption = QLabel()
        self.error_caption.setObjectName("rowErrorCaption")
        self.revert_button = self._action("Revert", self.editor.revert)
        self.accept_button = self._action("Accept", self.editor.accept_line)
        self.retry_button = self._action("Retry line", self._request_retry)

        # The row must hint no wider than the column (C-8's RED amendment): the
        # editor takes whatever width is left and claims none, and the caption
        # sits under the line at the row's full width, clipped rather than
        # widening the row.
        self.editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.error_caption.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        line_layout = QHBoxLayout()
        line_layout.setContentsMargins(0, 0, 0, 0)
        line_layout.addWidget(self.gutter)
        line_layout.addWidget(self.badge)
        line_layout.addWidget(self.editor, 1)
        line_layout.addWidget(self.revert_button)
        line_layout.addWidget(self.accept_button)
        line_layout.addWidget(self.retry_button)
        layout = QVBoxLayout(self)
        layout.setSpacing(2)
        layout.addLayout(line_layout)
        layout.addWidget(self.error_caption)

        self.editor.statusChanged.connect(self._render)
        self.editor.saveFailed.connect(self._on_save_failed)
        self.editor.saveSucceeded.connect(self._on_save_succeeded)
        self._render()

    def _action(self, label: str, act: Callable[[], None]) -> QPushButton:
        button = QPushButton(label)
        button.setAccessibleName(label)
        # The editor takes the whole of any spare width; a control never grows.
        button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        button.clicked.connect(act)
        return button

    def _request_retry(self) -> None:
        self.retryRequested.emit(self.region_id)

    def _on_save_failed(self, reason: str) -> None:
        self._save_error = reason
        self._render()

    def _on_save_succeeded(self) -> None:
        self._save_error = None
        self._render()

    def _render(self) -> None:
        status = self.editor.status
        self.gutter.setText(STATUS_GLYPHS[status])
        self.gutter.setProperty("status", status)
        # theme.qss colours the glyph by `status` (MT-061); without a re-polish
        # a status change keeps the old rule's colour.
        self.gutter.style().unpolish(self.gutter)
        self.gutter.style().polish(self.gutter)
        # Inert for painting under the application sheet, which wins; kept as
        # the palette record MT-017's tests and MT-028's High Contrast read.
        palette = self.gutter.palette()
        palette.setColor(
            QPalette.ColorRole.WindowText,
            QColor(tokens_gen.TOKENS[STATUS_COLOR_TOKENS[status]]),
        )
        self.gutter.setPalette(palette)
        self.revert_button.setVisible(status == "edited")
        self.accept_button.setVisible(status == "proposed")
        self.retry_button.setVisible(status == "failed")
        caption = self._save_error or failure_reason(self.editor.line)
        self.error_caption.setText(caption or "")
        self.error_caption.setVisible(caption is not None)
        self.rendered.emit()

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
        lines: Sequence[Line | None] | None = None,
        saves: Sequence[SaveFn | None] | None = None,
    ) -> None:
        """Replace every row, writing the old rows' pending saves first.

        The sequences are parallel. Without `lines` every row is MT-016's: an
        unreviewed proposal with nothing behind it to save to. A `None` entry
        in `lines` is that same line; `saves` defaults to no save for every row.
        """
        self.flush()
        with QSignalBlocker(self.list):
            self.list.clear()
            self._rows = []
            total = len(regions)
            given = lines if lines is not None else [None] * total
            savers = saves if saves is not None else [None] * total
            for region, ja, en, line, save in zip(
                regions, japanese, english, given, savers, strict=True
            ):
                shown = line if line is not None else _unsaved_line(region.region_id, ja, en)
                row = TranslationRow(region.region_id, shown, save)
                row.entered.connect(self.rowEntered.emit)
                row.left.connect(self.rowLeft.emit)
                item = QListWidgetItem()
                self.list.addItem(item)
                self.list.setItemWidget(item, row)
                self._rows.append(row)
                self._describe(item, row, region.ordinal, total, ja)
                row.rendered.connect(
                    lambda item=item, row=row, ordinal=region.ordinal, ja=ja: self._describe(
                        item, row, ordinal, total, ja
                    )
                )

    def _describe(
        self, item: QListWidgetItem, row: TranslationRow, ordinal: int, total: int, ja: str | None
    ) -> None:
        """The item's accessible name and size, from the row's current state."""
        item.setData(
            Qt.ItemDataRole.AccessibleTextRole,
            _row_accessible_text(ordinal, total, ja, row.editor.line),
        )
        # Recomputed on every render: the caption coming or going changes the
        # row's height.
        item.setSizeHint(row.sizeHint())

    def flush(self) -> None:
        """Write every row's pending save now. A field being typed in is left
        first, which commits it as leaving it would (C-7 row 11)."""
        for row in self._rows:
            if row.editor.hasFocus():
                row.editor.clearFocus()
            row.editor.flush()

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


def _saver(project: Project, page_ordinal: int, reading_index: int) -> SaveFn:
    """A row's save: its own line, on the page it was loaded from - not
    whichever page is shown when the save finally runs."""

    def save(text: str | None, status: LineStatus) -> None:
        commit_line(project, page_ordinal, reading_index, text, status)

    return save


class Workspace(QMainWindow):
    """The window a chapter is reviewed in."""

    #: `layout.md` "Window": the minimum is enforced, not advisory (AC-4).
    MIN_SIZE: tuple[int, int] = (1100, 720)

    #: Emitted once per close, after every pending save is written (MT-054
    #: C-4): whoever opened the project closes it on this, never before.
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(*self.MIN_SIZE)
        self._chapter: Chapter | None = None
        self._project: Project | None = None
        self._page_ordinal: int | None = None

        self.header = QWidget()
        self.header.setObjectName("workspaceHeader")
        self.header.setFixedHeight(HEADER_HEIGHT)
        # The chapter's cost after the run (MT-018 AC-9), at the header's end.
        self.cost_readout = CostReadout()
        header_row = QHBoxLayout(self.header)
        header_row.setContentsMargins(tokens_gen.SPACE_S4, 0, tokens_gen.SPACE_S4, 0)
        header_row.addStretch(1)
        header_row.addWidget(self.cost_readout)
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
        self.page_canvas.selectionStepRequested.connect(self._on_selection_step)
        self.translation_column.list.currentRowChanged.connect(self._on_current_row_changed)
        self.translation_column.rowEntered.connect(self.link.hover)
        self.translation_column.rowLeft.connect(self._on_row_left)

    def load_chapter(self, project: Project) -> None:
        """List the project's pages in the strip; nothing is selected yet.

        The header's cost readout shows the chapter's total as final, or `$—`
        when no call was priced - keyed on a call existing, not on the total
        being non-zero (MT-018 AC-9)."""
        spent = ledger.chapter_total(project) if ledger.chapter_call_costs(project) else None
        self.cost_readout.show_final(spent, project.budget_ceiling() or DEFAULT_CEILING)
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
        lines: Sequence[Line | None] | None = None,
    ) -> None:
        """Populate the canvas and the column; hover cleared, and the first
        region selected (§4.1), or nothing on a page with no regions.

        Rows set here have nothing behind them to save to; a page shown from
        the project (`show_page`) saves through the store."""
        self._set_regions(regions, japanese, english, lines, None)

    def _set_regions(
        self,
        regions: Sequence[OrderedRegion],
        japanese: Sequence[str | None],
        english: Sequence[str | None],
        lines: Sequence[Line | None] | None,
        saves: Sequence[SaveFn | None] | None,
    ) -> None:
        self.link.hover(None)
        self.link.select(None)
        self.page_canvas.set_regions(regions)
        self.translation_column.set_rows(regions, japanese, english, lines=lines, saves=saves)
        if regions:
            self.link.select(0)

    def _load_regions(self, ordinal: int) -> None:
        """PO-2: the page's regions and their review lines (`None` where OCR has
        not run), each row saving to its own line of *this* page."""
        assert self._project is not None
        # Pending saves first, so what is read below includes them.
        self.translation_column.flush()
        project = self._project
        stored = project.read_regions(ordinal)
        review = read_review_lines(project, ordinal)
        regions = [
            OrderedRegion(region_id=index, polygon=region.polygon)
            for index, region in enumerate(stored)
        ]
        lines = [review[index] if index < len(review) else None for index in range(len(regions))]
        japanese = [None if line is None or line.ocr_empty else line.source_ja for line in lines]
        english = [None if line is None else line.proposed_en for line in lines]
        saves = [_saver(project, ordinal, index) for index in range(len(regions))]
        self._set_regions(regions, japanese, english, lines, saves)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Write every pending save before the window goes (C-7), then close.

        `closed` is the last thing done: a slot that closes the project must
        find nothing left to write (MT-054 C-4)."""
        self.translation_column.flush()
        super().closeEvent(event)
        self.closed.emit()

    def _on_current_row_changed(self, row: int) -> None:
        self.link.select(row if row >= 0 else None)

    def _on_selection_step(self, step: str) -> None:
        """Up/Down/Home/End on the canvas (MT-050). Clamped, never wrapped; the
        restyle, reveal, row and announcement follow from `_on_selection_changed`."""
        count = len(self.page_canvas.markers)
        current = self.link.state.selected_region_id
        if count == 0 or current is None:
            return
        targets = {
            "previous": max(current - 1, 0),
            "next": min(current + 1, count - 1),
            "first": 0,
            "last": count - 1,
        }
        self.link.select(targets[step])

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
