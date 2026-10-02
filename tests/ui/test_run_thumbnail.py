"""MT-062: markers appear on the current-page thumbnail as regions are found.

`RunThumbnail` (new, `mangatl.ui.run_thumbnail`, `## Contract` C-3) and its place
in `RunProgressPanel` (C-4). AC-1 and AC-3 live here; AC-2 (the event and its
emitter) is `tests/core/test_regions_detected.py`; AC-4 (the window's Start
path) is `tests/ui/test_start_run.py`, and AC-4's "reads nothing from the store"
is the boundary test in `tests/ui/test_run_progress.py`, extended to this module.

Oracle partition (C-7):

- **Settled, read out of `## Design notes`:** object names `run-thumbnail` and
  `run-current-page`; the fixed 120 x 160 size; the halo `#0B0B0B` 6 px and core
  `#D6DCE2` 2 px pens; the frame `#333333` and ground `#141414` from the
  stylesheet; the five accessible names (U+2026, the singular, "no text
  regions") and the undecodable description; role `Graphic`; `NoFocus`. Colours
  are spelled as literals here, not read back from `tokens_gen`, so a token
  that drifted would be caught rather than followed.
- **Mechanical, hand-computed:** `image_rect()` and marker vertices for the
  worked 1000 x 1500 page (`## Design notes`: `(7.3333.., 1, 105.3333.., 158)`,
  `(300, 600) -> (38.9333.., 64.2)`) and for a wide 2000 x 1000 page
  (`s = min(118/2000, 158/1000) = 0.059`, so `(1, 50.5, 118, 59)`, and
  `(500, 400) -> (30.5, 74.1)`). Worked out in the comments beside each.
- **Paint, observed in pixels rather than in captured calls.** The widget makes
  its own `QPainter` in `paintEvent`, so a recording painter cannot be handed
  in without pinning how it paints. Instead the thumbnail is rendered into a
  120 x 160 `QImage` at device pixel ratio 1 and pixels are read at points where
  the design leaves exactly one possible colour: a 2 px core centred on an
  integer column covers exactly two pixel columns, a 6 px halo two more on each
  side. The page is drawn at `s = 0.5` (236 x 316 into 118 x 158) so a
  non-cosmetic pen scaled with the page would be 1 px and 3 px and miss those
  columns. The expected values of the controls - what each wrong painter gives
  at each probe pixel - are tabled in the story's `## Handoff`.

**RED:** fails at import (`mangatl.ui.run_thumbnail` does not exist), so no
assertion here has run. No waits anywhere: every test is synchronous.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage, QPolygonF, QRegion
from PySide6.QtWidgets import QHBoxLayout, QLayout, QWidget

from mangatl.domain.budget import DEFAULT_CEILING
from mangatl.domain.events import (
    PageSkipped,
    PageStarted,
    RegionsDetected,
    RunAborted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.domain.page import Chapter, Page
from mangatl.pipeline.runner import BUDGET, CANCELLED
from mangatl.ui.progress import PageStageStepper, RunProgressPanel
from mangatl.ui.run_thumbnail import RunThumbnail
from mangatl.ui.stylesheet import base_stylesheet

# --- Settled, read out of `## Design notes` (never from the module under test) ---
THUMB_SIZE = QSize(120, 160)
HALO = "#0b0b0b"  # overlay.halo
CORE = "#d6dce2"  # overlay.bubble.idle
FRAME = "#333333"  # color.border.subtle, border.width.hairline
GROUND = "#141414"  # color.surface.sunken
ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
NO_PAGE = "No page started"
UNDECODABLE = "The page image could not be opened."

#: Page fills for rendered images: far from the halo, the core, the frame and
#: the ground, and from one another.
PAGE_BLUE = "#3060c0"
PAGE_GREEN = "#30a050"
PAGE_ORANGE = "#d07020"
#: What the render target is filled with before the widget paints into it, so
#: a pixel the widget never touched is recognisable.
UNTOUCHED = "#ff00ff"


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def _png(path: Path, width: int, height: int, colour: str) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    assert image.save(str(path), "PNG"), f"precondition: could not write {path}"
    return path


def _thumb(qtbot) -> RunThumbnail:  # type: ignore[no-untyped-def]
    thumb = RunThumbnail()
    qtbot.addWidget(thumb)
    return thumb


def _render(widget: QWidget) -> QImage:
    """The widget painted into a 120 x 160 image at device pixel ratio 1."""
    image = QImage(THUMB_SIZE, QImage.Format.Format_ARGB32)
    image.setDevicePixelRatio(1.0)
    image.fill(QColor(UNTOUCHED))
    widget.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawWindowBackground)
    return image


def _at(image: QImage, x: int, y: int) -> str:
    return QColor(image.pixel(x, y)).name()


def _points(polygon: QPolygonF) -> list[tuple[float, float]]:
    return [(point.x(), point.y()) for point in polygon]


def _flat(points: list[tuple[float, float]]) -> list[float]:
    return [coordinate for point in points for coordinate in point]


def _flat_approx(points: list[tuple[float, float]]) -> object:
    """`pytest.approx` does not recurse into a list of tuples, so compare flat."""
    return pytest.approx(_flat(points), abs=1e-9)


def _rect(rect: QRectF) -> tuple[float, float, float, float]:
    return (rect.x(), rect.y(), rect.width(), rect.height())


def _name(widget: QWidget) -> str:
    return widget.accessibleName()


# =============================================================================
# The settled box: name, size, focus, role, first state
# =============================================================================


def test_the_thumbnail_is_named_run_thumbnail_and_is_fixed_at_120_by_160(qtbot) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    thumb.show()

    assert thumb.objectName() == "run-thumbnail"
    assert thumb.size() == THUMB_SIZE
    assert thumb.minimumSize() == THUMB_SIZE and thumb.maximumSize() == THUMB_SIZE, (
        "the size is not fixed: a layout could stretch the thumbnail"
    )


def test_the_thumbnail_is_not_a_focus_stop(qtbot) -> None:  # type: ignore[no-untyped-def]
    assert _thumb(qtbot).focusPolicy() == Qt.FocusPolicy.NoFocus


def test_the_thumbnail_is_a_graphic_to_assistive_technology(qtbot) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    interface = QAccessible.queryAccessibleInterface(thumb)

    assert interface is not None
    role = interface.role()
    assert role == QAccessible.Role.Graphic, f"role is {role!r}"


def test_a_new_thumbnail_is_an_empty_frame_named_no_page_started(qtbot) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)

    assert _name(thumb) == NO_PAGE
    assert thumb.accessibleDescription() == ""
    assert thumb.markers() == ()


# =============================================================================
# C-3 geometry: hand-computed, the worked case and the other aspect
# =============================================================================


def test_a_tall_page_is_drawn_into_the_rect_the_design_works_out(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """1000 x 1500: s = min(118/1000, 158/1500) = 158/1500 = 0.10533..; the page
    is 105.333.. x 158, centred in (1, 1, 118, 158): x = 1 + (118 - 105.333..)/2
    = 7.333.., y = 1. The image file is 50 x 20 - another aspect entirely - so
    a rect derived from the decoded image instead of the `Page` is visible."""
    thumb = _thumb(qtbot)

    thumb.show_page(0, _png(tmp_path / "p.png", 50, 20, PAGE_BLUE), 1000, 1500)

    assert _rect(thumb.image_rect()) == pytest.approx((22 / 3, 1.0, 316 / 3, 158.0), abs=1e-9)


def test_a_marker_vertex_lands_where_the_design_works_out_on_a_tall_page(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """DV-4's test. (300, 600) -> (7.333.. + 300 * 0.10533.., 1 + 600 * 0.10533..)
    = (38.9333.., 64.2). With the vertical scale taken from the width instead of
    the height, y would be 1 + 600 * 158/1000 = 95.8."""
    thumb = _thumb(qtbot)
    thumb.show_page(0, _png(tmp_path / "p.png", 10, 15, PAGE_BLUE), 1000, 1500)

    thumb.set_regions([((300, 600), (900, 600), (900, 1500), (300, 600))])

    (marker,) = thumb.markers()
    assert _flat(_points(marker)) == _flat_approx(
        [(584 / 15, 64.2), (1532 / 15, 64.2), (1532 / 15, 159.0), (584 / 15, 64.2)]
    )


def test_a_wide_page_is_letterboxed_top_and_bottom_with_markers_scaled_alike(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """2000 x 1000: s = min(118/2000, 158/1000) = 0.059; the page is 118 x 59,
    centred vertically: y = 1 + (158 - 59)/2 = 50.5, so (1, 50.5, 118, 59).
    (500, 400) -> (1 + 29.5, 50.5 + 23.6) = (30.5, 74.1); (2000, 1000) is the
    rect's bottom-right corner, (119, 109.5)."""
    thumb = _thumb(qtbot)
    thumb.show_page(0, _png(tmp_path / "p.png", 20, 10, PAGE_BLUE), 2000, 1000)

    thumb.set_regions([((0, 0), (500, 400), (2000, 1000), (0, 0))])

    assert _rect(thumb.image_rect()) == pytest.approx((1.0, 50.5, 118.0, 59.0), abs=1e-9)
    (marker,) = thumb.markers()
    assert _flat(_points(marker)) == _flat_approx(
        [(1.0, 50.5), (30.5, 74.1), (119.0, 109.5), (1.0, 50.5)]
    )


def test_markers_keep_every_polygon_and_every_vertex_in_the_order_given(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """118 x 158 is drawn at s = 1 in (1, 1, 118, 158), so every vertex is
    simply shifted by (1, 1)."""
    thumb = _thumb(qtbot)
    thumb.show_page(0, _png(tmp_path / "p.png", 118, 158, PAGE_BLUE), 118, 158)
    first, second = _ring(80, 10, 110, 40), _ring(5, 100, 30, 150)

    thumb.set_regions([first, second])

    assert [_points(m) for m in thumb.markers()] == [
        [(x + 1.0, y + 1.0) for x, y in first],
        [(x + 1.0, y + 1.0) for x, y in second],
    ]


# =============================================================================
# AC-1 / AC-3 at the widget: replace, clear, name
# =============================================================================


def test_a_second_set_of_regions_replaces_the_markers_rather_than_adding_to_them(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    thumb.show_page(0, _png(tmp_path / "p.png", 118, 158, PAGE_BLUE), 118, 158)
    thumb.set_regions([_ring(1, 1, 10, 10), _ring(20, 20, 30, 30)])

    thumb.set_regions([_ring(50, 50, 60, 60)])

    assert [_points(m) for m in thumb.markers()] == [
        [(x + 1.0, y + 1.0) for x, y in _ring(50, 50, 60, 60)]
    ]


def test_showing_a_page_clears_the_previous_pages_markers(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    thumb.show_page(0, _png(tmp_path / "a.png", 118, 158, PAGE_BLUE), 118, 158)
    thumb.set_regions([_ring(1, 1, 10, 10)])

    thumb.show_page(1, _png(tmp_path / "b.png", 118, 158, PAGE_GREEN), 118, 158)

    assert thumb.markers() == ()


def test_showing_a_page_names_it_one_based_and_says_detection_is_under_way(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)

    thumb.show_page(4, _png(tmp_path / "p.png", 10, 10, PAGE_BLUE), 10, 10)

    assert _name(thumb) == f"Page 5: detecting text regions{ELLIPSIS}"
    assert _name(thumb) == "Page 5: detecting text regions…"


@pytest.mark.parametrize(
    ("count", "tail"),
    [
        (0, "no text regions found"),
        (1, "1 text region found"),
        (2, "2 text regions found"),
        (12, "12 text regions found"),
    ],
)
def test_found_regions_are_counted_in_the_name_with_the_singular_and_none_spelled_out(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    count: int,
    tail: str,
) -> None:
    thumb = _thumb(qtbot)
    thumb.show_page(6, _png(tmp_path / "p.png", 118, 158, PAGE_BLUE), 118, 158)

    thumb.set_regions([_ring(i, i, i + 5, i + 5) for i in range(count)])

    assert _name(thumb) == f"Page 7: {tail}"
    assert len(thumb.markers()) == count


def test_a_page_that_decodes_has_no_description(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)

    thumb.show_page(0, _png(tmp_path / "p.png", 10, 10, PAGE_BLUE), 10, 10)

    assert thumb.accessibleDescription() == ""


# =============================================================================
# The undecodable image: never raises, frame stays, markers still drawn
# =============================================================================


@pytest.mark.parametrize("case", ["garbage bytes", "missing file"])
def test_an_image_that_will_not_open_raises_nothing_and_says_so(
    qtbot, tmp_path: Path, case: str
) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    path = tmp_path / "broken.png"
    if case == "garbage bytes":
        path.write_bytes(b"\x89PNG\r\n\x1a\nthis is not an image")

    thumb.show_page(2, path, 1000, 1500)

    assert thumb.accessibleDescription() == UNDECODABLE
    assert _name(thumb) == f"Page 3: detecting text regions{ELLIPSIS}"
    # The rect is still the page's, from width x height.
    assert _rect(thumb.image_rect()) == pytest.approx((22 / 3, 1.0, 316 / 3, 158.0), abs=1e-9)
    thumb.set_regions([((300, 600), (900, 600), (900, 1500), (300, 600))])
    assert _points(thumb.markers()[0])[0] == pytest.approx((584 / 15, 64.2), abs=1e-9)
    assert _name(thumb) == "Page 3: 1 text region found"
    _render(thumb)  # painting with no image must not raise either


def test_a_page_that_decodes_after_one_that_did_not_clears_the_description(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    thumb.show_page(0, tmp_path / "missing.png", 10, 10)

    thumb.show_page(1, _png(tmp_path / "p.png", 10, 10, PAGE_BLUE), 10, 10)

    assert thumb.accessibleDescription() == ""


# =============================================================================
# Paint, in pixels
# =============================================================================
#
# Page 236 x 316 at s = 0.5 fills (1, 1, 118, 158). Two polygons, in widget
# pixels after mapping (page / 2 + 1):
#   LEFT  page (40, 60)-(120, 200)  -> widget x 21 .. 61, y 31 .. 101
#   RIGHT page (126, 60)-(200, 200) -> widget x 64 .. 101, y 31 .. 101
# On row y = 65, a vertical edge at column c has its 2 px core over pixel
# columns c-1 and c, and its 6 px halo over c-3, c-2 and c+1, c+2.
#   LEFT's left edge c = 21:  halo 18 19 | core 20 21 | halo 22 23; page at 16.
#   LEFT's right edge c = 61: core 60 61. RIGHT's left edge c = 64 has its halo
#   over 61..66 - so column 61 is core only if every halo was stroked before
#   every core ("a later halo never cuts an earlier core").

_PAINT_PAGE = (236, 316)
_LEFT = _ring(40, 60, 120, 200)
_RIGHT = _ring(126, 60, 200, 200)
_ROW = 65


def _painted(qtbot, tmp_path: Path) -> QImage:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    width, height = _PAINT_PAGE
    thumb.show_page(0, _png(tmp_path / "p.png", width, height, PAGE_BLUE), width, height)
    thumb.set_regions([_LEFT, _RIGHT])
    return _render(thumb)


def test_the_page_image_is_drawn_into_the_thumbnail(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    image = _painted(qtbot, tmp_path)

    assert _at(image, 40, _ROW) == PAGE_BLUE, "the page is not drawn inside a marker"
    assert _at(image, 110, 140) == PAGE_BLUE, "the page is not drawn outside the markers"


def test_a_marker_is_a_2px_core_stroke_over_a_6px_halo_both_cosmetic(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    image = _painted(qtbot, tmp_path)

    row = {x: _at(image, x, _ROW) for x in range(16, 25)}
    assert row == {
        16: PAGE_BLUE,
        17: PAGE_BLUE,
        18: HALO,
        19: HALO,
        20: CORE,
        21: CORE,
        22: HALO,
        23: HALO,
        24: PAGE_BLUE,
    }, f"row {_ROW} across LEFT's left edge (x = 21) reads {row}"


def test_a_later_markers_halo_never_cuts_an_earlier_markers_core(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    image = _painted(qtbot, tmp_path)

    assert (_at(image, 60, _ROW), _at(image, 61, _ROW)) == (CORE, CORE), (
        "LEFT's right-edge core at columns 60-61 was overdrawn by RIGHT's halo:"
        " strokes were not all halos first, then all cores"
    )
    assert (_at(image, 63, _ROW), _at(image, 64, _ROW)) == (CORE, CORE)


def test_a_new_page_paints_no_marker_from_the_page_before(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    width, height = _PAINT_PAGE
    thumb.show_page(0, _png(tmp_path / "a.png", width, height, PAGE_BLUE), width, height)
    thumb.set_regions([_LEFT])

    thumb.show_page(1, _png(tmp_path / "b.png", width, height, PAGE_GREEN), width, height)
    image = _render(thumb)

    assert [_at(image, x, _ROW) for x in range(18, 24)] == [PAGE_GREEN] * 6


def test_the_frame_and_ground_come_from_the_stylesheet(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """The packaged base sheet's `#run-thumbnail` rule: a 1 px `#333333` frame
    around a `#141414` ground. A wide page (letterboxed from y = 50.5) leaves
    the ground showing above it."""
    thumb = _thumb(qtbot)
    thumb.setStyleSheet(base_stylesheet())
    thumb.show_page(0, _png(tmp_path / "p.png", 20, 10, PAGE_ORANGE), 2000, 1000)

    image = _render(thumb)

    assert [_at(image, 0, 80), _at(image, 119, 80), _at(image, 60, 0), _at(image, 60, 159)] == [
        FRAME
    ] * 4, "the 1 px frame is not color.border.subtle on all four sides"
    assert _at(image, 60, 20) == GROUND, "the ground above a letterboxed page is not sunken"
    assert _at(image, 60, 80) == PAGE_ORANGE


def test_an_empty_or_undecodable_thumbnail_is_the_frame_and_ground_alone(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    thumb = _thumb(qtbot)
    thumb.setStyleSheet(base_stylesheet())
    assert _at(_render(thumb), 60, 80) == GROUND, "the empty frame has no ground"

    thumb.show_page(0, tmp_path / "missing.png", 118, 158)
    image = _render(thumb)

    assert (_at(image, 0, 80), _at(image, 60, 80)) == (FRAME, GROUND)


def test_markers_are_clipped_to_the_content_box_and_never_paint_over_the_frame(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """A region along the page's own edge maps onto columns 1 and 119; its halo
    reaches columns -2 .. 4 and 116 .. 122, so only the clip keeps the frame."""
    thumb = _thumb(qtbot)
    thumb.setStyleSheet(base_stylesheet())
    thumb.show_page(0, _png(tmp_path / "p.png", 118, 158, PAGE_BLUE), 118, 158)
    thumb.set_regions([_ring(0, 0, 118, 158)])

    image = _render(thumb)

    assert (_at(image, 0, 80), _at(image, 119, 80)) == (FRAME, FRAME)
    assert (_at(image, 60, 0), _at(image, 60, 159)) == (FRAME, FRAME)


# =============================================================================
# C-4: the panel carries the thumbnail in the run-current-page row
# =============================================================================

#: Three pages, three sizes, three colours. The image files are small and of
#: the page's aspect; the panel passes the `Page`'s own width and height.
_CHAPTER_PAGES: tuple[tuple[str, int, int, tuple[int, int], str], ...] = (
    ("01.png", 1000, 1500, (20, 30), PAGE_BLUE),
    ("02.png", 2000, 1000, (40, 20), PAGE_GREEN),
    ("03.png", 900, 1200, (30, 40), PAGE_ORANGE),
)


def _chapter(tmp_path: Path) -> Chapter:
    folder = tmp_path / "Chapter 3"
    folder.mkdir()
    pages = []
    for ordinal, (filename, width, height, (fw, fh), colour) in enumerate(_CHAPTER_PAGES):
        _png(folder / filename, fw, fh, colour)
        pages.append(Page(ordinal, filename, width, height, f"{ordinal:064d}"))
    return Chapter(source_dir=folder, pages=tuple(pages))


def _panel(qtbot, chapter: Chapter | None = None) -> RunProgressPanel:  # type: ignore[no-untyped-def]
    panel = (
        RunProgressPanel()
        if chapter is None
        else RunProgressPanel(DEFAULT_CEILING, None, chapter=chapter)
    )
    qtbot.addWidget(panel)
    panel.show()
    return panel


def _feed(panel: RunProgressPanel, *events: RunEvent) -> None:
    for event in events:
        panel.on_event(event)


def _row(panel: RunProgressPanel) -> QHBoxLayout:
    row = panel.findChild(QHBoxLayout, "run-current-page")
    assert row is not None, "the panel has no QHBoxLayout named 'run-current-page'"
    return row


def _row_widgets(row: QLayout) -> list[QWidget]:
    found = [row.itemAt(i).widget() for i in range(row.count())]
    return [widget for widget in found if widget is not None]


def _thumbnail(panel: RunProgressPanel) -> RunThumbnail:
    thumb = panel.thumbnail
    assert isinstance(thumb, RunThumbnail), f"panel.thumbnail is {thumb!r}"
    return thumb


def test_a_panel_given_no_chapter_has_no_thumbnail_and_the_stepper_alone_in_its_row(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)

    assert panel.thumbnail is None
    assert panel.findChildren(RunThumbnail) == []
    assert _row_widgets(_row(panel)) == [panel.stepper]


def test_a_panel_given_a_chapter_shows_the_thumbnail_left_of_the_stepper(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot, _chapter(tmp_path))
    row = _row(panel)

    assert _row_widgets(row) == [_thumbnail(panel), panel.stepper]
    assert row.spacing() == 16, "the thumbnail and stepper are not space.4 apart"
    stepper_item = row.itemAt(row.indexOf(panel.stepper))
    assert stepper_item.alignment() & Qt.AlignmentFlag.AlignTop, "the stepper is not top-aligned"
    assert isinstance(panel.stepper, PageStageStepper)
    assert _thumbnail(panel).isVisible(), "the empty frame is not visible before the first page"
    assert _name(_thumbnail(panel)) == NO_PAGE


def test_the_current_page_row_sits_after_the_overall_bar_and_before_the_times(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot, _chapter(tmp_path))
    column = panel.layout()
    assert column is not None
    items = [column.itemAt(i) for i in range(column.count())]
    owners: list[object] = [item.widget() or item.layout() for item in items]

    row_at = owners.index(_row(panel))
    overall_at = owners.index(panel.overall)
    times_at = next(
        i
        for i, owner in enumerate(owners)
        if isinstance(owner, QLayout) and panel.elapsed_label in _row_widgets(owner)
    )
    assert overall_at + 1 == row_at < times_at, (
        f"run-current-page is item {row_at}; run-overall is {overall_at}, the times row {times_at}"
    )


def test_page_started_shows_that_pages_image_from_the_chapter_folder_with_no_markers(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """AC-3. Page 1 is 2000 x 1000 and green: rect (1, 50.5, 118, 59)."""
    panel = _panel(qtbot, _chapter(tmp_path))
    thumb = _thumbnail(panel)

    _feed(panel, RunStarted(run_id=1, page_count=3), PageStarted(ordinal=1))

    assert _rect(thumb.image_rect()) == pytest.approx((1.0, 50.5, 118.0, 59.0), abs=1e-9)
    assert thumb.markers() == ()
    assert _name(thumb) == f"Page 2: detecting text regions{ELLIPSIS}"
    assert thumb.accessibleDescription() == ""
    assert _at(_render(thumb), 60, 80) == PAGE_GREEN, "page 1's own image is not the one shown"


def test_regions_detected_for_the_current_page_put_its_markers_on_the_thumbnail(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """AC-1. Page 0 is 1000 x 1500: (300, 600) -> (38.9333.., 64.2)."""
    panel = _panel(qtbot, _chapter(tmp_path))
    thumb = _thumbnail(panel)
    _feed(panel, RunStarted(run_id=1, page_count=3), PageStarted(ordinal=0))

    _feed(
        panel,
        RegionsDetected(
            ordinal=0,
            polygons=(((300, 600), (900, 600), (900, 1500), (300, 600)), _ring(10, 10, 50, 50)),
        ),
    )

    assert len(thumb.markers()) == 2
    assert _points(thumb.markers()[0])[0] == pytest.approx((584 / 15, 64.2), abs=1e-9)
    assert _name(thumb) == "Page 1: 2 text regions found"


def test_regions_detected_for_any_other_page_changes_nothing(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """AC-3, DV-3's test."""
    panel = _panel(qtbot, _chapter(tmp_path))
    thumb = _thumbnail(panel)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=3),
        PageStarted(ordinal=0),
        RegionsDetected(ordinal=0, polygons=(_ring(10, 10, 50, 50),)),
    )
    before = ([_points(m) for m in thumb.markers()], _name(thumb), _rect(thumb.image_rect()))

    _feed(panel, RegionsDetected(ordinal=2, polygons=(_ring(1, 1, 5, 5), _ring(6, 6, 9, 9))))
    _feed(panel, RegionsDetected(ordinal=1, polygons=()))

    after = ([_points(m) for m in thumb.markers()], _name(thumb), _rect(thumb.image_rect()))
    assert after == before


def test_regions_detected_before_any_page_has_started_changes_nothing(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot, _chapter(tmp_path))
    thumb = _thumbnail(panel)

    _feed(panel, RunStarted(run_id=1, page_count=3))
    _feed(panel, RegionsDetected(ordinal=0, polygons=(_ring(1, 1, 5, 5),)))

    assert thumb.markers() == ()
    assert _name(thumb) == NO_PAGE


def test_the_next_page_started_replaces_the_image_and_clears_the_markers(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot, _chapter(tmp_path))
    thumb = _thumbnail(panel)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=3),
        PageStarted(ordinal=0),
        RegionsDetected(ordinal=0, polygons=(_ring(10, 10, 50, 50),)),
        StageFinished(ordinal=0, stage="detect", elapsed_ms=5),
    )

    _feed(panel, PageStarted(ordinal=2))

    assert thumb.markers() == ()
    assert _name(thumb) == f"Page 3: detecting text regions{ELLIPSIS}"
    assert _at(_render(thumb), 60, 80) == PAGE_ORANGE


@pytest.mark.parametrize(
    "event",
    [
        StageFinished(ordinal=1, stage="detect", elapsed_ms=7),
        PageSkipped(ordinal=2, reason="already done"),
        RunFinished(run_id=1, pages_done=3),
        RunAborted(reason=BUDGET, ordinal=2),
        RunAborted(reason=CANCELLED, ordinal=None),
        RunAborted(reason="boom", ordinal=1),
    ],
    ids=["stage-finished", "page-skipped", "run-finished", "budget", "cancelled", "failed"],
)
def test_events_other_than_page_started_and_regions_detected_leave_the_thumbnail_as_it_was(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    event: RunEvent,
) -> None:
    """A finished, aborted or skipping run leaves the last page and its markers in view."""
    panel = _panel(qtbot, _chapter(tmp_path))
    thumb = _thumbnail(panel)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=3),
        PageStarted(ordinal=1),
        RegionsDetected(ordinal=1, polygons=(_ring(100, 100, 900, 600),)),
    )
    before = ([_points(m) for m in thumb.markers()], _name(thumb), _rect(thumb.image_rect()))

    _feed(panel, event)

    after = ([_points(m) for m in thumb.markers()], _name(thumb), _rect(thumb.image_rect()))
    assert after == before
    assert before[1] == "Page 2: 1 text region found"


# --- PO-4: the dispatch order. `RegionsDetected` must not fall through to the
# --- `RunAborted` arm, which reads `event.reason`.


def test_a_panel_with_no_chapter_takes_regions_detected_without_raising(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=3), PageStarted(ordinal=0))

    panel.on_event(RegionsDetected(ordinal=0, polygons=(_ring(1, 1, 5, 5),)))
    panel.on_event(RegionsDetected(ordinal=1, polygons=()))

    assert panel.banner is None
    assert panel.overall_label.text() == "Page 1 of 3"


def test_a_panel_with_a_chapter_takes_regions_detected_without_raising_or_a_banner(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot, _chapter(tmp_path))
    _feed(panel, RunStarted(run_id=1, page_count=3), PageStarted(ordinal=0))

    panel.on_event(RegionsDetected(ordinal=0, polygons=()))
    panel.on_event(RegionsDetected(ordinal=2, polygons=()))

    assert panel.banner is None
    assert _name(_thumbnail(panel)) == "Page 1: no text regions found"


def test_the_stylesheet_has_a_rule_for_the_thumbnail_by_object_name() -> None:
    """The ground and frame are the stylesheet's (MT-061's rule: colours by
    object name), not literals in the widget."""
    sheet = base_stylesheet()
    rules = re.findall(r"#run-thumbnail\s*\{([^}]*)\}", sheet)

    assert rules, "the base stylesheet has no #run-thumbnail rule"
    body = " ".join(rules).lower()
    assert re.search(r"background(-color)?\s*:\s*#141414", body), body
    assert re.search(r"border\s*:\s*1px\s+solid\s+#333333", body), body
