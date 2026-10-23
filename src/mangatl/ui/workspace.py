"""The review workspace: the page large, the lines docked beside it.

`layout.md` ("Review workspace", "Window") and `components.md` §3 settle every
number here; they are read out, not tuned. Three regions sit in one horizontal
splitter - `PageStrip` (a 28 px rail below 1440 px, 96 px at or above),
`PageCanvas` (all remaining width) and `TranslationColumn` (300 px below 1440,
380 at or above, user-resizable 280-560) - between a 48 px header and a 44 px
footer.

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

**Render** (MT-066, `components.md` §3, §7, §9). The footer holds the render
status and, at its right end, the primary "Render pages". Render writes any
pending save, then counts on a worker (`BakeController.preview`) and opens
`BakeConfirmDialog` on the result; confirming writes pending saves again and
renders on a worker. While either step runs the button is *loading* (§1): it
keeps its width and its focus and ignores activation. Focus returns to it
explicitly whenever the dialog closes, because the offscreen platform does not
reactivate the window by itself. The end of a render, finished or failed, is
stated in the footer and announced.

**The 1440 px breakpoint** (MT-048, `layout.md` "The one breakpoint"). Judged
on the window's width on every resize: below it the strip is a rail of 1-based
page indices and the header hides the chapter name; at or above it the strip
shows filenames and the name is shown. Only a resize that CROSSES the line
reallocates the splitter, and then only if the user has not dragged the column
since the chapter was opened; a resize on one side gives the whole delta to the
canvas, as before.

**Page status** (MT-086, `components.md` §`PageStrip`). Each strip row carries
a glyph for its page's `domain.page_status` derivation, coloured by `theme.qss`
through the glyph's `status` property. A line committed in the column re-derives
the shown page's row in place (`linesChanged`); the chapter is never reloaded.
`mangatl.app` opens this window on a chapter folder (MT-054) and closes the
project on `closed`, which is emitted after a render in flight has finished and
the pending saves are written.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QEnterEvent,
    QGuiApplication,
    QMoveEvent,
    QPainter,
    QPalette,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from mangatl.domain.budget import DEFAULT_CEILING
from mangatl.domain.line import Line, LineStatus, effective_text, failure_reason
from mangatl.domain.page import Chapter
from mangatl.domain.page_status import PageProgress, PageStatus, page_progress
from mangatl.pipeline.bake import BakePreview, BakeReport
from mangatl.store import ledger
from mangatl.store.lines import commit_line, read_review_lines
from mangatl.store.project import PAGE_DONE, PAGE_STALE, Project, project_dir_for
from mangatl.ui import tokens_gen
from mangatl.ui.bake import BakeController
from mangatl.ui.bake_dialog import BakeConfirmDialog
from mangatl.ui.buttons import ActivatedByEnter
from mangatl.ui.canvas import PageCanvas
from mangatl.ui.cost_readout import CostReadout
from mangatl.ui.intake import display_name
from mangatl.ui.labels import plain_label
from mangatl.ui.line_editor import LineEditor, SaveFn
from mangatl.ui.link import LinkController, LiveRegion, OrderedRegion
from mangatl.ui.theme import ThemeController
from mangatl.ui.thumbnail import decode_thumbnail, thumbnail_size
from mangatl.ui.workspace_state import (
    Rect,
    WorkspaceState,
    clamp_state,
    first_run_size,
    read_state,
    write_state,
)

#: Where a remembered layout must fit: `(x, y, width, height)`, asked when applied.
WorkArea = Callable[[], Rect]

__all__ = [
    "BREAKPOINT_WIDTH",
    "CANVAS_MIN_WIDTH",
    "COLUMN_DEFAULT_NARROW",
    "COLUMN_DEFAULT_WIDE",
    "COLUMN_MAX_WIDTH",
    "COLUMN_MIN_WIDTH",
    "FOOTER_HEIGHT",
    "HEADER_HEIGHT",
    "PAGE_STATUS_COLOR_TOKENS",
    "PAGE_STATUS_GLYPHS",
    "STATUS_COLOR_TOKENS",
    "STATUS_GLYPHS",
    "STRIP_RAIL_WIDTH",
    "STRIP_WIDTH",
    "THUMBNAIL_BATCH",
    "PageStrip",
    "TranslationColumn",
    "TranslationRow",
    "Workspace",
    "page_accessible_text",
    "page_tooltip_text",
]

#: Judged on `Workspace.width()`: `>=` is the wide layout (layout.md).
BREAKPOINT_WIDTH = 1440
#: The full strip, at or above the breakpoint.
STRIP_WIDTH = 96
#: The rail of page indices, below the breakpoint.
STRIP_RAIL_WIDTH = 28
#: Strip thumbnails decoded per event-loop tick (MT-087 PO-2): opening a chapter
#: never waits on them, and no tick holds the loop for long.
THUMBNAIL_BATCH = 4
#: A row's thumbnail area before `PageStrip.set_thumbnails` sizes it (72 x 96).
_DEFAULT_THUMBNAIL_AREA = QSize(72, 96)

ThumbnailState = Literal["pending", "shown", "failed"]
COLUMN_DEFAULT_NARROW = 300
COLUMN_DEFAULT_WIDE = 380
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

#: `components.md` §`PageStrip`'s glyphs (PO-1): circles for the run, diamonds
#: for the review. Pairwise distinct code points (A-15.7), keyed in
#: `PAGE_STATUSES` order.
PAGE_STATUS_GLYPHS: dict[PageStatus, str] = {
    "pending": "\N{WHITE CIRCLE}",
    "running": "\N{CIRCLE WITH LEFT HALF BLACK}",
    "translated": "\N{WHITE DIAMOND}",
    "partly_reviewed": "\N{WHITE DIAMOND CONTAINING BLACK SMALL DIAMOND}",
    "fully_reviewed": "\N{BLACK DIAMOND}",
    "failed": "\N{WARNING SIGN}",
    "skipped": "\N{BLACK RECTANGLE}",
}

#: `components.md` §`PageStrip`'s glyph colours, as tokens. The colour itself
#: lives only in `theme.qss` (`QLabel#pageGlyph[status=...]`, MT-086 AC-3).
PAGE_STATUS_COLOR_TOKENS: dict[PageStatus, str] = {
    "pending": "color.text.muted",
    "running": "color.accent.base",
    "translated": "color.text.secondary",
    "partly_reviewed": "color.status.success",
    "fully_reviewed": "color.status.success",
    "failed": "color.status.danger",
    "skipped": "color.text.disabled",
}

#: `components.md` §5's per-status phrase in the row's accessible name.
_STATUS_PHRASES: dict[LineStatus, str] = {
    "proposed": "machine proposal",
    "accepted": "accepted",
    "edited": "edited",
    "reverted": "edited, then returned to the proposal",
}

#: `components.md` §3's primary footer action, and its §1 loading state.
_RENDER_TEXT = "Render pages"
_RENDER_LOADING_TEXT = "\N{MIDDLE DOT}" * 3
_RENDER_LOADING_NAME = "Render pages, working"


def page_accessible_text(
    index: int, total_pages: int, filename: str, progress: PageProgress
) -> str:
    """`components.md` §`PageStrip`: a strip item's accessible name (PO-4).

    `index` is 0-based; the name numbers pages from one."""
    status = progress.status
    if status == "pending":
        phrase = "not translated yet"
    elif status == "running":
        phrase = "translating"
    elif status == "skipped":
        phrase = "skipped, source changed"
    else:
        phrase = f"{progress.reviewed} of {progress.total} lines reviewed"
        if status == "failed":
            phrase += f", {progress.failed} failed"
    return f"Page {index + 1} of {total_pages}, {filename}, {phrase}"


def page_tooltip_text(index: int, total_pages: int, filename: str) -> str:
    """MT-090: the tooltip of a rail row whose index does not fit the rail.

    `index` is 0-based; the text numbers pages from one, then the filename
    after a spaced em dash (voice.md's dash form)."""
    return f"Page {index + 1} of {total_pages} \N{EM DASH} {filename}"


class _NoTextDelegate(QStyledItemDelegate):
    """Paints an item's ground (hover, current, selection) but not its text.

    The strip's items keep their text (the 1-based index, MT-087 PO-1) for
    whoever reads it, and the item widget shows it; painting it too would
    draw it twice, under the widget."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""  # type: ignore[attr-defined]
        widget = opt.widget  # type: ignore[attr-defined]
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)


class _PageRow(QWidget):
    """One strip row: the page's thumbnail above a footer of the status glyph
    and the page's 1-based index (MT-087, `components.md` §`PageStrip`).

    In the full strip the thumbnail sits centred between `space.3` margins
    (12 + 72 + 12 = 96) and the footer lays glyph beside index; in the rail the
    thumbnail is hidden and the footer stacks glyph over index, which is what
    fits two characters' width into 28 px (MT-086).

    In the rail the index is drawn only when it fits (MT-090): a row whose
    index is wider than the rail hides it, keeping its height, and the strip
    moves the number into the item's tooltip. `fitChanged` asks the strip to
    re-read this row after a font change, which can change the answer."""

    fitChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageRow")
        self._rail = False
        self.thumb = QLabel()
        self.thumb.setObjectName("pageThumbnail")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.glyph = QLabel()
        self.glyph.setObjectName("pageGlyph")
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel()
        self.label.setObjectName("pageLabel")
        self.outer = QVBoxLayout(self)
        self.outer.setSpacing(tokens_gen.SPACE_S1)
        self.outer.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)
        self.box.addWidget(self.glyph)
        self.box.addWidget(self.label, 1)
        self.outer.addLayout(self.box)
        self.set_thumbnail_area(_DEFAULT_THUMBNAIL_AREA)
        self.set_thumbnail("pending", None)

    def set_rail(self, rail: bool) -> None:
        self._rail = rail
        margin = 0 if rail else tokens_gen.SPACE_S3
        vertical = 0 if rail else tokens_gen.SPACE_S1
        self.outer.setContentsMargins(margin, vertical, margin, vertical)
        self.thumb.setVisible(not rail)
        self.box.setDirection(
            QBoxLayout.Direction.TopToBottom if rail else QBoxLayout.Direction.LeftToRight
        )
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
            if rail
            else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.fit_index()

    def index_fits(self) -> bool:
        """Whether the index fits the rail: the rail row has zero contents
        margins, so the label's own hint is the whole horizontal cost."""
        return self.label.sizeHint().width() <= STRIP_RAIL_WIDTH

    def index_drawn(self) -> bool:
        """Whether the index is drawn: always in the full strip, and in the
        rail only when it fits. Judged afresh on every call."""
        return not self._rail or self.index_fits()

    def fit_index(self) -> bool:
        """Show or hide the index by `index_drawn`, and return the answer.

        A drawn index in the rail counts its width, so the row's hint is
        honest against 28 px; in the full strip the 96 px strip sets the
        width. A hidden index keeps its height, so every rail row is as tall
        as every other, and gives up its width, so the row fits the rail."""
        drawn = self.index_drawn()
        policy = QSizePolicy(
            QSizePolicy.Policy.Preferred if self._rail and drawn else QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        policy.setRetainSizeWhenHidden(not drawn)
        self.label.setSizePolicy(policy)
        self.label.setVisible(drawn)
        return drawn

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.fitChanged.emit()

    def set_thumbnail_area(self, size: QSize) -> None:
        """Fix the thumbnail area now, so the row does not reflow when the
        image lands."""
        self.thumb.setFixedSize(size)

    def set_thumbnail(self, state: ThumbnailState, pixmap: QPixmap | None) -> None:
        if pixmap is None:
            self.thumb.clear()
        else:
            self.thumb.setPixmap(pixmap)
        self.thumb.setProperty("state", state)
        self.thumb.style().unpolish(self.thumb)
        self.thumb.style().polish(self.thumb)

    def set_status(self, status: PageStatus) -> None:
        self.glyph.setText(PAGE_STATUS_GLYPHS[status])
        self.glyph.setProperty("status", status)
        # theme.qss colours the glyph by `status`, as the gutter: without a
        # re-polish a status change keeps the old rule's colour.
        self.glyph.style().unpolish(self.glyph)
        self.glyph.style().polish(self.glyph)


class PageStrip(QListWidget):
    """The chapter's pages, one item per page in ordinal order.

    Full (96 px) each row shows the page's thumbnail above its status glyph and
    1-based index; as a rail (28 px) the glyph above the index (MT-048, MT-086,
    MT-087). The item's text is the index in both modes, its tooltip the
    filename, and every item reads "Page N of M, <filename>, <progress>".

    Thumbnails decode lazily (MT-087 PO-2): `set_thumbnails` only queues them,
    and a zero-interval timer decodes `THUMBNAIL_BATCH` per event-loop tick,
    only while the full strip is shown. Each page is decoded at most once until
    the next `set_pages`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageStrip")
        self.setAccessibleName("Pages")
        self.setItemDelegate(_NoTextDelegate(self))
        self._filenames: list[str] = []
        self._progress: list[PageProgress] = []
        self._rows: list[_PageRow] = []
        self._rail = False
        self._source_dir: Path | None = None
        self._thumbnails: list[QPixmap | None] = []
        self._thumbnail_states: list[ThumbnailState] = []
        self._thumbnail_sizes: list[QSize] = []
        self._queue: deque[int] = deque()
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._decode_batch)
        self.setFixedWidth(STRIP_WIDTH)

    @property
    def is_rail(self) -> bool:
        return self._rail

    def set_pages(self, filenames: Sequence[str], progress: Sequence[PageProgress]) -> None:
        """Replace every item: one per filename, labelled with its index and
        showing its page's progress. Forgets every thumbnail and the queue."""
        self._timer.stop()
        self._queue.clear()
        self._source_dir = None
        self._filenames = list(filenames)
        self._progress = list(progress)
        self._thumbnails = [None] * len(self._filenames)
        self._thumbnail_states = ["pending"] * len(self._filenames)
        self._thumbnail_sizes = [_DEFAULT_THUMBNAIL_AREA] * len(self._filenames)
        self.clear()
        self._rows = []
        for index, filename in enumerate(self._filenames):
            item = QListWidgetItem()
            item.setToolTip(filename)
            self.addItem(item)
            row = _PageRow()
            row.set_rail(self._rail)
            row.fitChanged.connect(partial(self._refit_row, index))
            self.setItemWidget(item, row)
            self._rows.append(row)
        for index in range(len(self._filenames)):
            self._show_progress(index)
        self._relabel()

    def set_thumbnails(self, source_dir: Path, sizes: Sequence[tuple[int, int]]) -> None:
        """Queue every page's thumbnail, `sizes` being each page's stored
        `(width, height)` in the order of `set_pages`' filenames. Each area is
        sized now; nothing is decoded inside this call."""
        self._timer.stop()
        self._source_dir = source_dir
        self._thumbnail_sizes = [thumbnail_size(width, height) for width, height in sizes]
        self._thumbnails = [None] * len(self._thumbnail_sizes)
        self._thumbnail_states = ["pending"] * len(self._thumbnail_sizes)
        self._queue = deque(range(len(self._thumbnail_sizes)))
        for index, row in enumerate(self._rows):
            row.set_thumbnail_area(self._thumbnail_sizes[index])
            row.set_thumbnail("pending", None)
        self._resize_items()
        if not self._rail:
            self._timer.start()

    def thumbnail(self, index: int) -> QPixmap | None:
        """Row `index`'s decoded thumbnail, or None while pending or failed."""
        return self._thumbnails[index]

    def thumbnail_state(self, index: int) -> ThumbnailState:
        return self._thumbnail_states[index]

    def pending_thumbnails(self) -> int:
        """How many thumbnails are still queued."""
        return len(self._queue)

    def _decode_batch(self) -> None:
        """One tick of the queue: up to `THUMBNAIL_BATCH` pages, in order."""
        source_dir = self._source_dir
        for _ in range(THUMBNAIL_BATCH):
            if not self._queue or source_dir is None:
                break
            index = self._queue.popleft()
            # Looked up on this module per call, so the decode can be counted.
            image = decode_thumbnail(
                source_dir / self._filenames[index], self._thumbnail_sizes[index]
            )
            if image is None:
                self._thumbnail_states[index] = "failed"
            else:
                self._thumbnails[index] = QPixmap.fromImage(image)
                self._thumbnail_states[index] = "shown"
            self._rows[index].set_thumbnail(self._thumbnail_states[index], self._thumbnails[index])
        if not self._queue:
            self._timer.stop()

    def set_progress(self, index: int, progress: PageProgress) -> None:
        """Show `progress` on row `index`, in place: the item is not rebuilt, so
        the current row and the selection survive."""
        self._progress[index] = progress
        self._show_progress(index)

    def progress(self, index: int) -> PageProgress:
        """What row `index` shows."""
        return self._progress[index]

    def _show_progress(self, index: int) -> None:
        progress = self._progress[index]
        self._rows[index].set_status(progress.status)
        self.item(index).setData(
            Qt.ItemDataRole.AccessibleTextRole,
            page_accessible_text(index, len(self._filenames), self._filenames[index], progress),
        )

    def set_rail(self, rail: bool) -> None:
        """Switch between the rail and the full strip in place, so the current
        row, the selection and the decoded thumbnails survive. The rail pauses
        the thumbnail queue; the full strip resumes it."""
        if rail == self._rail:
            return
        self._rail = rail
        if rail:
            self._timer.stop()
        elif self._queue:
            self._timer.start()
        self.setFixedWidth(STRIP_RAIL_WIDTH if rail else STRIP_WIDTH)
        for row in self._rows:
            row.set_rail(rail)
        self._refit()

    def _relabel(self) -> None:
        for index in range(len(self._filenames)):
            text = str(index + 1)
            self.item(index).setText(text)
            self._rows[index].label.setText(text)
        self._refit()

    def _refit(self) -> None:
        """Re-judge every row's index against the rail (MT-090), then size
        every item to its row."""
        for index in range(len(self._rows)):
            self._apply_fit(index)
        self._resize_items()

    def _refit_row(self, index: int) -> None:
        """Row `index`'s font changed: re-judge it and re-size its item."""
        if index >= len(self._rows):
            return
        self._apply_fit(index)
        self.item(index).setSizeHint(self._rows[index].sizeHint())

    def _apply_fit(self, index: int) -> None:
        """Show or hide row `index`'s index, and give its item the tooltip
        that goes with the answer: the filename when the index is drawn, the
        page number and filename when it is not."""
        filename = self._filenames[index]
        drawn = self._rows[index].fit_index()
        self.item(index).setToolTip(
            filename if drawn else page_tooltip_text(index, len(self._filenames), filename)
        )

    def _resize_items(self) -> None:
        for index, row in enumerate(self._rows):
            self.item(index).setSizeHint(row.sizeHint())


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
    #: A row re-rendered after a commit or a save outcome: a line's status may
    #: have changed (MT-086 block 6). Not emitted by `set_rows`.
    linesChanged = Signal()

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
                    lambda item=item, row=row, ordinal=region.ordinal, ja=ja: self._on_rendered(
                        item, row, ordinal, total, ja
                    )
                )

    def _on_rendered(
        self, item: QListWidgetItem, row: TranslationRow, ordinal: int, total: int, ja: str | None
    ) -> None:
        self._describe(item, row, ordinal, total, ja)
        self.linesChanged.emit()

    def statuses(self) -> tuple[LineStatus, ...]:
        """Each row's line status, in row order."""
        return tuple(row.editor.line.status for row in self._rows)

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


def _stored_progress(project: Project, ordinal: int) -> PageProgress:
    """One page's progress as the store has it (MT-086 block 6). `running` is
    never set: the workspace is not open during a run."""
    status = project.page_status(ordinal)
    lines = [None if line is None else line.status for line in read_review_lines(project, ordinal)]
    return page_progress(lines, page_done=status == PAGE_DONE, stale=status == PAGE_STALE)


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
        self._render_controller: BakeController | None = None
        self._render_output = ""
        #: The theme controller the canvas follows; `None` until `follow_theme`.
        self._theme: ThemeController | None = None
        #: The Render dialog last opened, kept after it closes; `None` before.
        self.bake_dialog: BakeConfirmDialog | None = None
        #: The side of the breakpoint last laid out; `None` before the first resize.
        self._wide: bool | None = None
        #: The user dragged the column since the chapter was opened (Block 4).
        self._column_dragged = False
        #: Set while the breakpoint itself moves the splitter.
        self._reallocating = False
        #: Where the layout is remembered; `None` until `remember_layout` arms it.
        self._state_path: Path | None = None
        #: The remembered column width, applied once the window is laid out.
        self._pending_column: int | None = None
        #: The last normal (not maximised) `(width, height, x, y)`, in `pos()`
        #: terms - `normalGeometry()` is the client top-left once shown (A-2).
        self._normal = (self.width(), self.height(), self.x(), self.y())

        self.header = QWidget()
        self.header.setObjectName("workspaceHeader")
        self.header.setFixedHeight(HEADER_HEIGHT)
        # The chapter's cost after the run (MT-018 AC-9), at the header's end.
        self.cost_readout = CostReadout()
        # The chapter's name, leading the header at or above the breakpoint;
        # hidden, never removed, below it (MT-048 AC-5). The window opens narrow.
        self.chapter_name = plain_label("chapterName", "")
        self.chapter_name.setWordWrap(False)
        self.chapter_name.setVisible(False)
        header_row = QHBoxLayout(self.header)
        header_row.setContentsMargins(tokens_gen.SPACE_S4, 0, tokens_gen.SPACE_S4, 0)
        header_row.addWidget(self.chapter_name)
        header_row.addStretch(1)
        header_row.addWidget(self.cost_readout)
        self.footer = QWidget()
        self.footer.setObjectName("workspaceFooter")
        self.footer.setFixedHeight(FOOTER_HEIGHT)
        # How the last render ended, then Render pages at the footer's end (§3).
        self.render_status = plain_label("renderStatus", "")
        self.render_button = ActivatedByEnter(_RENDER_TEXT)
        self.render_button.setObjectName("renderButton")
        self.render_button.setProperty("variant", "primary")
        self._set_render_loading(False)
        footer_row = QHBoxLayout(self.footer)
        footer_row.setContentsMargins(tokens_gen.SPACE_S4, 0, tokens_gen.SPACE_S4, 0)
        footer_row.addWidget(self.render_status, 1)
        footer_row.addWidget(self.render_button)

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
        self.splitter.setSizes([STRIP_WIDTH, CANVAS_MIN_WIDTH, COLUMN_DEFAULT_NARROW])
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

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
        self.translation_column.linesChanged.connect(self._refresh_page_progress)
        self.render_button.clicked.connect(self._render_pages)

    def follow_theme(self, controller: ThemeController) -> None:
        """Put the canvas in `controller`'s mode now, and again on every apply (MT-073).

        The canvas reads the palette from the controller, so `themeApplied(bool)`
        keeps its signature."""
        self._theme = controller
        self._on_theme_applied(controller.high_contrast)
        controller.themeApplied.connect(self._on_theme_applied)

    def remember_layout(self, path: Path, *, work_area: WorkArea | None = None) -> None:
        """Apply the layout remembered in `path` now, and write it back on close (MT-088).

        Called before `show()`. With no usable file the window takes
        `first_run_size`; otherwise the file, fitted to `work_area()` by
        `clamp_state`, sets the size, the position, the maximised state and a
        dragged column's width. `work_area` defaults to this window's screen's
        available geometry. A window never armed reads and writes nothing."""
        self._state_path = path
        area = (work_area or self._screen_work_area)()
        state = read_state(path)
        if state is None:
            self.resize(*first_run_size(area, self.MIN_SIZE))
            return
        state = clamp_state(state, area, self.MIN_SIZE, (COLUMN_MIN_WIDTH, COLUMN_MAX_WIDTH))
        self.resize(state.width, state.height)
        self.move(state.x, state.y)
        self._normal = (state.width, state.height, state.x, state.y)
        if state.maximized:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        if state.column_width is not None:
            # A remembered drag is a drag: the breakpoint leaves it alone (MT-048).
            self._column_dragged = True
            self._pending_column = state.column_width

    def _screen_work_area(self) -> Rect:
        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        return (area.x(), area.y(), area.width(), area.height())

    def layout_state(self) -> WorkspaceState:
        """What closing would remember now: the normal size and position (in
        `pos()` terms even while maximised, A-2), the maximised flag, and the
        column's width if the user dragged it."""
        maximized = self.isMaximized()
        if maximized:
            width, height, x, y = self._normal
        else:
            width, height, x, y = self.width(), self.height(), self.pos().x(), self.pos().y()
        return WorkspaceState(
            width=width,
            height=height,
            x=x,
            y=y,
            maximized=maximized,
            column_width=self.splitter.sizes()[2] if self._column_dragged else None,
        )

    def _on_theme_applied(self, high_contrast: bool) -> None:
        if self._theme is not None:
            self.page_canvas.set_high_contrast(high_contrast, self._theme.palette)

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
        self._column_dragged = False
        name = display_name(self._chapter.source_dir)
        self.chapter_name.setText(name)
        self.chapter_name.setAccessibleName(f"Chapter {name}")
        progress = [_stored_progress(project, page.ordinal) for page in self._chapter.pages]
        with QSignalBlocker(self.page_strip):
            self.page_strip.set_pages([page.filename for page in self._chapter.pages], progress)
            self.page_strip.set_thumbnails(
                self._chapter.source_dir, [(p.width, p.height) for p in self._chapter.pages]
            )
        self.page_canvas.set_page(None)
        self.set_regions([], [], [])

    def _refresh_page_progress(self) -> None:
        """The shown page's strip row, re-derived from the column's lines and
        the page's stored state - in place, never by reloading (MT-086 AC-4)."""
        if self._project is None or self._page_ordinal is None:
            return
        status = self._project.page_status(self._page_ordinal)
        progress = page_progress(
            self.translation_column.statuses(),
            page_done=status == PAGE_DONE,
            stale=status == PAGE_STALE,
        )
        self.page_strip.set_progress(self._page_ordinal, progress)

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

    def render(self, *args: Any, **kwargs: Any) -> None:
        """Render pages (MT-066 C-4) when called bare; `QWidget.render` otherwise.

        The contract names the command `render()`, which shadows Qt's
        paint-into-a-device `render(target, ...)` - a call the theme tests make
        on this window. Any argument at all means Qt's."""
        if args or kwargs:
            super().render(*args, **kwargs)
            return
        self._render_pages()

    def _render_pages(self) -> None:
        """Write pending saves, then count on a worker; the dialog opens when
        the counts arrive. Before `load_chapter`, and while a step is running,
        it does nothing."""
        if self._chapter is None or self.render_button.property("loading"):
            return
        # First, so an edit typed and not yet saved is counted as reviewed.
        self.translation_column.flush()
        controller = BakeController(project_dir_for(self._chapter.source_dir), self)
        controller.previewed.connect(self._on_render_previewed)
        controller.baked.connect(self._on_render_baked)
        controller.failed.connect(self._on_render_failed)
        self._render_controller = controller
        self._set_render_loading(True)
        controller.preview()

    def _set_render_loading(self, loading: bool) -> None:
        """§1's loading state: `···` at the rest width, focus kept, ", working"."""
        button = self.render_button
        # The rest width, held while the shorter indicator shows (no reflow).
        button.setMinimumWidth(button.width() if loading else 0)
        button.setProperty("loading", loading)
        button.setText(_RENDER_LOADING_TEXT if loading else _RENDER_TEXT)
        button.setAccessibleName(_RENDER_LOADING_NAME if loading else _RENDER_TEXT)
        button.style().unpolish(button)
        button.style().polish(button)

    def _on_render_previewed(self, preview: BakePreview) -> None:
        self._set_render_loading(False)
        self._render_output = str(preview.output_dir)
        if self.bake_dialog is not None:
            self.bake_dialog.deleteLater()
        self.bake_dialog = BakeConfirmDialog(preview, self)
        self.bake_dialog.finished.connect(self._on_bake_dialog_finished)
        self.bake_dialog.open()

    def _on_bake_dialog_finished(self, result: int) -> None:
        # Explicitly, and the window first: offscreen, nothing is active once
        # the dialog hides, and setFocus alone lands nowhere (C-2's amendment).
        self.activateWindow()
        self.render_button.setFocus(Qt.FocusReason.OtherFocusReason)
        if result != QDialog.DialogCode.Accepted.value or self._render_controller is None:
            return
        self.translation_column.flush()
        self._set_render_loading(True)
        self._render_controller.bake()

    def _on_render_baked(self, report: BakeReport) -> None:
        pages = report.pages_written
        noun = "page" if pages == 1 else "pages"
        sentence = f"Rendered {pages} {noun} to {self._render_output}."
        if report.font_fallback != "none":
            # MT-027 PO-2: said beside the render, not in a banner.
            sentence += (
                f" Lettered in {report.font_family} because the font folder in settings"
                f" could not be used: {report.font_detail}."
            )
        self._end_render(sentence)

    def _on_render_failed(self, reason: str) -> None:
        self._end_render(f"Render failed: {reason}")

    def _end_render(self, sentence: str) -> None:
        self.render_status.setText(sentence)
        self.live_region.announce(sentence)
        self._set_render_loading(False)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._track_normal()
        self._apply_breakpoint()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._track_normal()

    def _track_normal(self) -> None:
        """Record the normal geometry in `pos()` terms while the window is in it."""
        abnormal = (
            Qt.WindowState.WindowMaximized
            | Qt.WindowState.WindowMinimized
            | Qt.WindowState.WindowFullScreen
        )
        if not self.windowState() & abnormal:
            self._normal = (self.width(), self.height(), self.pos().x(), self.pos().y())

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._pending_column is not None:
            # Splitter sizes are unreliable until the window is laid out.
            column, self._pending_column = self._pending_column, None
            QTimer.singleShot(0, self, partial(self._apply_remembered_column, column))

    def _apply_remembered_column(self, column: int) -> None:
        strip, canvas, current = self.splitter.sizes()
        self._reallocating = True
        try:
            self.splitter.setSizes([strip, canvas + current - column, column])
        finally:
            self._reallocating = False

    def _apply_breakpoint(self) -> None:
        """Lay out the side of the breakpoint the window is on.

        The splitter is reallocated only when the side CHANGES, and only if the
        column was not dragged: a resize on one side leaves every size to the
        canvas's stretch, so the art takes the whole delta."""
        wide = self.width() >= BREAKPOINT_WIDTH
        self.page_strip.set_rail(not wide)
        self.chapter_name.setVisible(wide)
        if wide == self._wide:
            return
        self._wide = wide
        if not self._column_dragged:
            strip = STRIP_WIDTH if wide else STRIP_RAIL_WIDTH
            column = COLUMN_DEFAULT_WIDE if wide else COLUMN_DEFAULT_NARROW
            remaining = self.splitter.width() - strip - column - 2 * self.splitter.handleWidth()
            self._reallocating = True
            try:
                self.splitter.setSizes([strip, remaining, column])
            finally:
                self._reallocating = False

    def _on_splitter_moved(self, _pos: int, index: int) -> None:
        if not self._reallocating and index == 2:
            self._column_dragged = True

    def closeEvent(self, event: QCloseEvent) -> None:
        """Wait for a render in flight, write every pending save (C-7), then close.

        A render cannot be cancelled, and the project is closed on `closed`,
        so the wait comes first. `closed` is the last thing done: a slot that
        closes the project must find nothing left to write (MT-054 C-4). An
        armed window (`remember_layout`) writes its layout just before it."""
        if self._render_controller is not None:
            self._render_controller.wait()
        self.translation_column.flush()
        if self._state_path is not None:
            # A failed write is not a reason to keep the window open (AC-4).
            write_state(self._state_path, self.layout_state())
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
