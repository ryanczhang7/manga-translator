"""MT-015: the workspace shows the page large, with the lines docked beside it.

Every layout number here is READ OUT of `docs/wiki/design/layout.md` ("Review
workspace" and "Window") and `docs/wiki/design/components.md` §3. None of them
is derived from what the widgets happen to measure, and none is tuned:

    PageStrip          96 px fixed
    PageCanvas         everything remaining; stretch 1; minimumWidth 520
    TranslationColumn  340 px, user-resizable 280-560
    header 48 px, footer 44 px, both full width
    window minimum     1100 x 720, enforced with setMinimumSize
    zoom range         10%-800%

The 1440 px breakpoint in layout.md is deliberately NOT tested: it was deferred
by the user (MT-015 PO-1) and is MT-047.

"The remaining width" is measured, never assumed (Contract, geometry
semantics): the canvas is whatever the splitter has left after the two side
regions and its two handles. AC-2 is asserted as a DELTA.

AC-7 (no colour literals) lives in `test_workspace_colour_literals.py`, which
does not import the workspace, so its scanner and negative controls execute
even while `workspace.py` and `canvas.py` do not exist.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsView, QListWidget, QMainWindow, QSplitter

from mangatl.domain.page import Chapter, Page
from mangatl.store.project import Project, create_project
from mangatl.ui import tokens_gen
from mangatl.ui.canvas import (
    EMPTY,
    EMPTY_ACTION,
    EMPTY_TITLE,
    FAILED,
    FAILED_MESSAGE,
    LOADED,
    PageCanvas,
)
from mangatl.ui.workspace import (
    CANVAS_MIN_WIDTH,
    COLUMN_DEFAULT_WIDTH,
    COLUMN_MAX_WIDTH,
    COLUMN_MIN_WIDTH,
    FOOTER_HEIGHT,
    HEADER_HEIGHT,
    STRIP_WIDTH,
    PageStrip,
    TranslationColumn,
    Workspace,
)

# --- Settled numbers, read out of layout.md / components.md §3 ---------------
LAYOUT_STRIP = 96
LAYOUT_COLUMN_DEFAULT = 340
LAYOUT_COLUMN_MIN = 280
LAYOUT_COLUMN_MAX = 560
LAYOUT_CANVAS_MIN = 520
LAYOUT_HEADER = 48
LAYOUT_FOOTER = 44
LAYOUT_WINDOW_MIN = QSize(1100, 720)
DESIGN_ZOOM_MIN = 0.10  # "Zoom range 10%-800%"
DESIGN_ZOOM_MAX = 8.0

# --- The widths the acceptance criteria name --------------------------------
NARROW = 1100  # AC-1, and the start of AC-2
WIDE = 1900  # the end of AC-2, and where AC-3's 560 end is observable
HEIGHT = 720

# Floating-point slack for a zoom read back through QTransform. A zoom is a
# ratio, not a pixel count; this does not loosen any layout assertion.
ZOOM_EPS = 1e-9

GOOD_PAGE = "001.png"
JUNK_PAGE = "002.png"
GOOD_SIZE = QSize(64, 96)


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _open(qtbot, width: int = NARROW, height: int = HEIGHT) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.resize(width, height)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    return window


def _remaining(window: Workspace) -> int:
    splitter = window.splitter
    return (
        splitter.width()
        - window.page_strip.width()
        - window.translation_column.width()
        - 2 * splitter.handleWidth()
    )


def _drag_column_to(window: Workspace, splitter_pos: int) -> None:
    """Drag the divider between canvas and column (handle index 2)."""
    window.splitter.moveSplitter(splitter_pos, 2)
    _settle()


def _top_in_window(window: QMainWindow, widget) -> int:  # type: ignore[no-untyped-def]
    return widget.mapTo(window, QPoint(0, 0)).y()


# =============================================================================
# The constants are the design's numbers
# =============================================================================


def test_the_workspace_layout_constants_are_the_numbers_layout_md_settles() -> None:
    assert STRIP_WIDTH == LAYOUT_STRIP
    assert COLUMN_DEFAULT_WIDTH == LAYOUT_COLUMN_DEFAULT
    assert COLUMN_MIN_WIDTH == LAYOUT_COLUMN_MIN
    assert COLUMN_MAX_WIDTH == LAYOUT_COLUMN_MAX
    assert CANVAS_MIN_WIDTH == LAYOUT_CANVAS_MIN
    assert HEADER_HEIGHT == LAYOUT_HEADER
    assert FOOTER_HEIGHT == LAYOUT_FOOTER
    min_size = Workspace.MIN_SIZE
    assert min_size == (LAYOUT_WINDOW_MIN.width(), LAYOUT_WINDOW_MIN.height())


def test_the_zoom_range_is_the_10_to_800_percent_components_md_settles() -> None:
    assert PageCanvas.ZOOM_MIN == DESIGN_ZOOM_MIN
    assert PageCanvas.ZOOM_MAX == DESIGN_ZOOM_MAX


# =============================================================================
# AC-1: at 1100 px the regions have their settled sizes
# =============================================================================


def test_the_three_regions_sit_in_a_horizontal_splitter_strip_canvas_column(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot)

    assert isinstance(window, QMainWindow)
    assert isinstance(window.splitter, QSplitter)
    assert window.splitter.orientation() == Qt.Orientation.Horizontal
    assert window.splitter.count() == 3
    assert window.splitter.widget(0) is window.page_strip
    assert window.splitter.widget(1) is window.page_canvas
    assert window.splitter.widget(2) is window.translation_column
    assert isinstance(window.page_strip, PageStrip)
    assert isinstance(window.page_strip, QListWidget)
    assert isinstance(window.page_canvas, PageCanvas)
    assert isinstance(window.page_canvas, QGraphicsView)
    assert isinstance(window.translation_column, TranslationColumn)


def test_the_canvas_carries_the_only_non_zero_splitter_stretch(qtbot) -> None:  # type: ignore[no-untyped-def]
    # QSplitter.setStretchFactor writes the widget's horizontal stretch.
    window = _open(qtbot)

    assert window.page_strip.sizePolicy().horizontalStretch() == 0
    assert window.page_canvas.sizePolicy().horizontalStretch() > 0
    assert window.translation_column.sizePolicy().horizontalStretch() == 0


def test_at_1100_px_the_page_strip_is_96_px_wide(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    assert window.width() == NARROW
    assert window.page_strip.width() == LAYOUT_STRIP


def test_at_1100_px_the_translation_column_is_340_px_wide(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    assert window.width() == NARROW
    assert window.translation_column.width() == LAYOUT_COLUMN_DEFAULT


def test_at_1100_px_the_canvas_takes_every_pixel_the_side_regions_leave(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    # The splitter spans the window, so "remaining" is remaining of the window.
    assert window.splitter.width() == NARROW
    assert window.page_canvas.width() == _remaining(window)
    assert window.page_canvas.width() >= LAYOUT_CANVAS_MIN


def test_the_header_is_48_px_tall_and_full_width(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    assert window.header.height() == LAYOUT_HEADER
    assert window.header.width() == NARROW


def test_the_footer_is_44_px_tall_and_full_width(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    assert window.footer.height() == LAYOUT_FOOTER
    assert window.footer.width() == NARROW


def test_the_header_is_above_the_regions_and_the_footer_below_them(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    header_top = _top_in_window(window, window.header)
    splitter_top = _top_in_window(window, window.splitter)
    footer_top = _top_in_window(window, window.footer)
    assert header_top < splitter_top < footer_top
    assert footer_top + window.footer.height() == window.height()


# =============================================================================
# AC-2: widening the window widens only the art
# =============================================================================


def test_widening_the_window_by_800_px_widens_the_canvas_by_all_800(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)
    # AC-2 starts from AC-1's layout. Without this, a column that carried the
    # stretch but started pinned at its 280 floor passes the delta vacuously
    # (measured in RED against a stand-in: 280 -> 280, canvas +800).
    assert window.translation_column.width() == LAYOUT_COLUMN_DEFAULT
    canvas_before = window.page_canvas.width()

    window.resize(WIDE, HEIGHT)
    _settle()

    assert window.width() == WIDE
    assert window.page_canvas.width() - canvas_before == WIDE - NARROW


def test_widening_after_the_column_was_dragged_still_gives_the_whole_delta_to_the_canvas(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    # A column resized by the user, with room left below its 560 maximum, is
    # where a misplaced stretch factor shows: it would grow and the art would not.
    window = _open(qtbot, NARROW)
    dragged = 400
    _drag_column_to(window, window.splitter.width() - window.splitter.handleWidth() - dragged)
    assert window.translation_column.width() == dragged
    canvas_before = window.page_canvas.width()

    window.resize(WIDE, HEIGHT)
    _settle()

    assert window.page_canvas.width() - canvas_before == WIDE - NARROW
    assert window.translation_column.width() == dragged
    assert window.page_strip.width() == LAYOUT_STRIP


def test_widening_the_window_leaves_the_page_strip_and_column_widths_unchanged(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)
    strip_before = window.page_strip.width()
    column_before = window.translation_column.width()
    assert column_before == LAYOUT_COLUMN_DEFAULT

    window.resize(WIDE, HEIGHT)
    _settle()

    assert window.width() == WIDE
    assert window.page_strip.width() == strip_before
    assert window.translation_column.width() == column_before


# =============================================================================
# AC-3: the column divider clamps to 280-560
# =============================================================================


def test_dragging_the_column_divider_far_right_clamps_the_column_at_280_px(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, WIDE)

    _drag_column_to(window, 10 * WIDE)

    assert window.translation_column.width() == LAYOUT_COLUMN_MIN


def test_dragging_the_column_divider_far_left_clamps_the_column_at_560_px(qtbot) -> None:  # type: ignore[no-untyped-def]
    # At 1900 px the canvas floor (520) leaves room for far more than 560, so
    # what stops the drag here is the column's own maximum (Contract, AC-3).
    window = _open(qtbot, WIDE)

    _drag_column_to(window, 0)

    assert window.translation_column.width() == LAYOUT_COLUMN_MAX
    assert window.page_strip.width() == LAYOUT_STRIP


def test_a_drag_inside_the_range_leaves_the_column_where_it_was_dropped(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, WIDE)
    target = 400
    position = window.splitter.width() - window.splitter.handleWidth() - target

    _drag_column_to(window, position)

    assert window.translation_column.width() == target
    assert window.page_canvas.width() == _remaining(window)


def test_the_column_advertises_the_280_to_560_clamp_as_its_size_limits(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot)

    assert window.translation_column.minimumWidth() == LAYOUT_COLUMN_MIN
    assert window.translation_column.maximumWidth() == LAYOUT_COLUMN_MAX
    assert window.page_canvas.minimumWidth() == LAYOUT_CANVAS_MIN


# =============================================================================
# AC-4: the minimum window size is enforced
# =============================================================================


def test_a_window_requested_at_800_by_600_opens_at_1100_by_720(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, 800, 600)

    assert window.size() == LAYOUT_WINDOW_MIN
    assert window.minimumSize() == LAYOUT_WINDOW_MIN


def test_a_window_too_narrow_but_tall_enough_is_widened_to_1100(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, 1000, 900)

    assert window.size() == QSize(1100, 900)


def test_a_window_wide_enough_but_too_short_is_heightened_to_720(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, 1300, 500)

    assert window.size() == QSize(1300, 720)


# =============================================================================
# AC-5: no chapter -> the empty state, not a blank canvas
# =============================================================================


def test_the_empty_state_copy_is_the_one_components_md_specifies() -> None:
    assert EMPTY_TITLE == "No chapter loaded"
    assert EMPTY_ACTION == "Open a folder"


def test_a_workspace_with_no_chapter_shows_the_empty_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot)
    canvas = window.page_canvas

    assert canvas.state() == EMPTY
    assert canvas.page_item is None
    assert canvas.message.isVisible()
    assert EMPTY_TITLE in canvas.message.text()
    assert EMPTY_ACTION in canvas.message.text()
    assert canvas.message.accessibleName() == EMPTY_TITLE


def test_a_chapter_with_zero_pages_shows_the_empty_state(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "chapter"
    source.mkdir()
    window = _open(qtbot)

    with create_project(Chapter(source_dir=source, pages=()), tmp_path / "p.mtproj") as project:
        window.load_chapter(project)
        _settle()

        assert window.page_strip.count() == 0
        assert window.page_canvas.state() == EMPTY
        assert window.page_canvas.page_item is None
        assert window.page_canvas.message.isVisible()
        assert window.page_canvas.message.accessibleName() == EMPTY_TITLE


def test_a_canvas_given_neither_page_nor_error_is_empty(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = PageCanvas()
    qtbot.addWidget(canvas)

    canvas.set_page(QPixmap(_good_image()))
    canvas.set_page(None)

    assert canvas.state() == EMPTY
    assert canvas.page_item is None


# =============================================================================
# AC-6: an undecodable page fails loudly and alone
# =============================================================================


def _good_image() -> QImage:
    image = QImage(GOOD_SIZE, QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.COLOR_TEXT_PRIMARY))
    return image


@pytest.fixture
def two_page_project(tmp_path: Path) -> Iterator[Project]:
    """A real project: one genuine PNG and one junk-bytes `*.png`."""
    source = tmp_path / "chapter"
    source.mkdir()
    assert _good_image().save(str(source / GOOD_PAGE), "PNG")
    (source / JUNK_PAGE).write_bytes(b"these bytes are not a PNG, or any image at all")
    chapter = Chapter(
        source_dir=source,
        pages=(
            Page(ordinal=0, filename=GOOD_PAGE, width=64, height=96, sha256="0" * 64),
            Page(ordinal=1, filename=JUNK_PAGE, width=64, height=96, sha256="1" * 64),
        ),
    )
    with create_project(chapter, tmp_path / "chapter.mtproj") as project:
        yield project


def test_the_page_strip_lists_every_page_by_filename_in_ordinal_order(
    qtbot,  # type: ignore[no-untyped-def]
    two_page_project: Project,
) -> None:
    window = _open(qtbot)

    window.load_chapter(two_page_project)
    _settle()

    assert window.page_strip.count() == 2
    assert window.page_strip.item(0).text() == GOOD_PAGE
    assert window.page_strip.item(1).text() == JUNK_PAGE


def test_the_page_failed_copy_is_the_one_components_md_specifies() -> None:
    assert FAILED_MESSAGE == (
        "This page could not be opened. It will be copied to the output folder unchanged."
    )


def test_selecting_an_undecodable_page_shows_the_failed_state_naming_the_file(
    qtbot,  # type: ignore[no-untyped-def]
    two_page_project: Project,
) -> None:
    window = _open(qtbot)
    window.load_chapter(two_page_project)
    _settle()

    window.page_strip.setCurrentRow(1)
    _settle()

    canvas = window.page_canvas
    assert canvas.state() == FAILED
    assert canvas.page_item is None
    assert canvas.message.isVisible()
    assert JUNK_PAGE in canvas.message.text()
    assert FAILED_MESSAGE in canvas.message.text()
    assert JUNK_PAGE in canvas.message.accessibleName()


def test_after_a_failed_page_selecting_a_good_page_loads_it(
    qtbot,  # type: ignore[no-untyped-def]
    two_page_project: Project,
) -> None:
    window = _open(qtbot)
    window.load_chapter(two_page_project)
    _settle()
    window.page_strip.setCurrentRow(1)
    _settle()
    assert window.page_canvas.state() == FAILED

    window.page_strip.setCurrentRow(0)
    _settle()

    canvas = window.page_canvas
    assert canvas.state() == LOADED
    assert canvas.page_item is not None
    assert not canvas.page_item.pixmap().isNull()
    assert canvas.page_item.pixmap().size() == GOOD_SIZE
    assert not canvas.message.isVisible()


def test_a_failed_page_does_not_leave_the_previous_page_on_the_canvas(
    qtbot,  # type: ignore[no-untyped-def]
    two_page_project: Project,
) -> None:
    window = _open(qtbot)
    window.load_chapter(two_page_project)
    _settle()
    window.page_strip.setCurrentRow(1)
    _settle()
    window.page_strip.setCurrentRow(0)
    _settle()
    assert window.page_canvas.state() == LOADED

    window.page_strip.setCurrentRow(1)
    _settle()

    assert window.page_canvas.state() == FAILED
    assert window.page_canvas.page_item is None
    assert window.page_canvas.page_edge_item is None


# =============================================================================
# AC-8: the mat, the page edge, and the zoom range
# =============================================================================


@pytest.fixture
def loaded_canvas(qtbot) -> PageCanvas:  # type: ignore[no-untyped-def]
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    with qtbot.waitExposed(canvas):
        canvas.show()
    pixmap = QPixmap(800, 1200)
    pixmap.fill(QColor(tokens_gen.COLOR_TEXT_PRIMARY))
    canvas.set_page(pixmap)
    _settle()
    return canvas


def test_a_loaded_page_is_outlined_by_a_1_px_cosmetic_page_edge_pen(
    loaded_canvas: PageCanvas,
) -> None:
    edge = loaded_canvas.page_edge_item
    assert loaded_canvas.state() == LOADED
    assert edge is not None
    pen = edge.pen()
    assert pen.color() == QColor(tokens_gen.COLOR_CANVAS_PAGE_EDGE)
    assert pen.width() == 1
    assert pen.isCosmetic()


def test_the_page_edge_outline_goes_round_the_page_pixmap(loaded_canvas: PageCanvas) -> None:
    page = loaded_canvas.page_item
    edge = loaded_canvas.page_edge_item
    assert page is not None
    assert edge is not None

    page_rect = page.sceneBoundingRect()
    edge_rect = edge.mapRectToScene(edge.rect())
    # Round the page: it contains the pixmap and is no more than 1 px larger on
    # any side (a 1 px line may sit on or just outside the pixmap's edge).
    assert edge_rect.contains(page_rect)
    grown = QRectF(page_rect).adjusted(-1, -1, 1, 1)
    assert grown.contains(edge_rect)
    assert page.isVisible()
    assert edge.isVisible()


def test_the_mat_is_the_canvas_surround_colour_in_every_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    surround = QColor(tokens_gen.COLOR_CANVAS_SURROUND)
    seen: dict[str, QColor] = {}

    seen[canvas.state()] = canvas.backgroundBrush().color()
    canvas.set_page(QPixmap(_good_image()))
    seen[canvas.state()] = canvas.backgroundBrush().color()
    canvas.set_page(None, error=JUNK_PAGE)
    seen[canvas.state()] = canvas.backgroundBrush().color()

    assert set(seen) == {EMPTY, LOADED, FAILED}
    assert all(colour == surround for colour in seen.values()), seen
    assert canvas.backgroundBrush().style() == Qt.BrushStyle.SolidPattern


def test_the_message_is_hidden_while_a_page_is_loaded(loaded_canvas: PageCanvas) -> None:
    assert not loaded_canvas.message.isVisible()


def test_the_canvas_pans_rather_than_scrolls(loaded_canvas: PageCanvas) -> None:
    off = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert loaded_canvas.horizontalScrollBarPolicy() == off
    assert loaded_canvas.verticalScrollBarPolicy() == off


def test_zoom_is_clamped_to_800_percent(loaded_canvas: PageCanvas) -> None:
    loaded_canvas.set_zoom(100.0)

    assert loaded_canvas.zoom() == pytest.approx(DESIGN_ZOOM_MAX, abs=ZOOM_EPS)
    assert loaded_canvas.transform().m11() == pytest.approx(DESIGN_ZOOM_MAX, abs=ZOOM_EPS)


def test_zoom_is_clamped_to_10_percent(loaded_canvas: PageCanvas) -> None:
    loaded_canvas.set_zoom(0.0001)

    assert loaded_canvas.zoom() == pytest.approx(DESIGN_ZOOM_MIN, abs=ZOOM_EPS)
    assert loaded_canvas.transform().m11() == pytest.approx(DESIGN_ZOOM_MIN, abs=ZOOM_EPS)


def test_zoom_exactly_on_either_bound_is_kept(loaded_canvas: PageCanvas) -> None:
    loaded_canvas.set_zoom(DESIGN_ZOOM_MAX)
    at_max = loaded_canvas.zoom()
    loaded_canvas.set_zoom(DESIGN_ZOOM_MIN)
    at_min = loaded_canvas.zoom()

    assert at_max == pytest.approx(DESIGN_ZOOM_MAX, abs=ZOOM_EPS)
    assert at_min == pytest.approx(DESIGN_ZOOM_MIN, abs=ZOOM_EPS)


def test_a_zoom_inside_the_range_is_applied_uniformly_as_given(loaded_canvas: PageCanvas) -> None:
    loaded_canvas.set_zoom(2.0)

    assert loaded_canvas.zoom() == pytest.approx(2.0, abs=ZOOM_EPS)
    assert loaded_canvas.transform().m11() == pytest.approx(2.0, abs=ZOOM_EPS)
    assert loaded_canvas.transform().m22() == pytest.approx(2.0, abs=ZOOM_EPS)


def test_set_zoom_sets_an_absolute_factor_rather_than_compounding(
    loaded_canvas: PageCanvas,
) -> None:
    loaded_canvas.set_zoom(2.0)
    loaded_canvas.set_zoom(2.0)

    assert loaded_canvas.zoom() == pytest.approx(2.0, abs=ZOOM_EPS)


def test_panning_a_zoomed_page_keeps_the_page_edge_and_the_mat(loaded_canvas: PageCanvas) -> None:
    loaded_canvas.set_zoom(4.0)
    _settle()
    horizontal = loaded_canvas.horizontalScrollBar()
    vertical = loaded_canvas.verticalScrollBar()
    assert horizontal.maximum() > horizontal.minimum(), "nowhere to pan to horizontally"
    assert vertical.maximum() > vertical.minimum(), "nowhere to pan to vertically"
    edge = loaded_canvas.page_edge_item
    assert edge is not None
    pen_before = QColor(edge.pen().color()), edge.pen().width(), edge.pen().isCosmetic()
    rect_before = edge.mapRectToScene(edge.rect())
    h_before, v_before = horizontal.value(), vertical.value()

    horizontal.setValue(horizontal.maximum())
    vertical.setValue(vertical.maximum())
    _settle()

    assert (horizontal.value(), vertical.value()) != (h_before, v_before), "the pan did not move"
    assert loaded_canvas.page_edge_item is edge
    assert (edge.pen().color(), edge.pen().width(), edge.pen().isCosmetic()) == pen_before
    assert edge.mapRectToScene(edge.rect()) == rect_before
    assert loaded_canvas.backgroundBrush().color() == QColor(tokens_gen.COLOR_CANVAS_SURROUND)
    assert loaded_canvas.zoom() == pytest.approx(4.0, abs=ZOOM_EPS)
