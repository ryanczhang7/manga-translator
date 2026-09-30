"""MT-016: the translation line and its bubble, linked in the real workspace.

Widget-level criteria, driven through the real `Workspace` over a real project
(`create_project` on `tmp_path`, genuine PNG pages). Every number is READ OUT:

    SELECTION_MARGIN_PX  24 px, components.md §4.5 `space.6`
    zoom                 never changed by selection (§4.5) - m11 AND m22
    hover                never pans the canvas, never scrolls the list (§4.4)
    dimming              tokens_gen.OVERLAY_DIM_OPACITY (§4.3)
    accessible text      components.md §5; live region text §4.9

AC-3 is measured exactly as the Contract pins it: `m = canvas.mapFromScene(
region.bounds()).boundingRect()` (a QRect, whose right() is the last covered
pixel), then m.left() >= 24, m.top() >= 24, m.right() <= vw - 1 - 24,
m.bottom() <= vh - 1 - 24. The fixture page is 3000 x 4000 with every region at
least 200 px from every page edge (PO-3), so the scroll range can always reach
the pan.

Offscreen mechanics this file relies on, each measured in RED (story Handoff):
- `QTest.mouseMove` on the canvas viewport is delivered ONLY if the viewport
  has mouse tracking on - which is exactly what real hover needs, so it is used.
- `QListWidget.itemEntered` does NOT fire for rows shown with setItemWidget,
  offscreen or through real input; the row widget itself receives Enter/Leave.
  Row hover is therefore driven by `QTest.mouseMove` onto the row widget
  (Contract amended by RED).
- Focus is observable offscreen once the window is active.
- `QAccessible.queryAccessibleInterface` returns the list's interface offscreen,
  and its children carry AccessibleTextRole as their Name and the Selected
  state; it is asserted in addition to the item data.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from mangatl.domain.line import OcrResult
from mangatl.domain.page import Chapter, Page
from mangatl.domain.region import RawRegion
from mangatl.store.project import Project, create_project
from mangatl.ui import link as link_module
from mangatl.ui import tokens_gen
from mangatl.ui.canvas import PageCanvas
from mangatl.ui.link import OrderedRegion
from mangatl.ui.markers import MarkerState
from mangatl.ui.workspace import Workspace

# --- Settled numbers, read out ------------------------------------------------
MARGIN = 24  # components.md §4.5 `space.6`
DIM = tokens_gen.OVERLAY_DIM_OPACITY  # components.md §4.3

# --- Fixture geometry ---------------------------------------------------------
PAGE = QSize(3000, 4000)
WINDOW = QSize(1100, 720)  # the workspace minimum; the canvas shows part of the page
GRID_COLUMNS = 5
REGION_W, REGION_H = 120, 90
MANY = 40  # enough rows that the last is out of the list's view
SHOWN_PAGE = 1  # 0-based ordinal of the page the tests work on: "Page 2 of 3"
PAGES = ("001.png", "002.png", "003.png")
JUNK_PAGE_ORDINAL = 2  # 003.png does not decode


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _png_bytes(size: QSize) -> bytes:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(128, 128, 128))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


@pytest.fixture(scope="session")
def page_png() -> bytes:
    """One 3000 x 4000 PNG, encoded once for the whole session (~0.25 s)."""
    return _png_bytes(PAGE)


@pytest.fixture
def project(tmp_path: Path, page_png: bytes) -> Iterator[Project]:
    """Three pages: two genuine 3000 x 4000 PNGs and one junk-bytes `*.png`."""
    source = tmp_path / "chapter"
    source.mkdir()
    for ordinal, name in enumerate(PAGES):
        payload = b"not a PNG at all" if ordinal == JUNK_PAGE_ORDINAL else page_png
        (source / name).write_bytes(payload)
    chapter = Chapter(
        source_dir=source,
        pages=tuple(
            Page(
                ordinal=i,
                filename=name,
                width=PAGE.width(),
                height=PAGE.height(),
                sha256=f"{i}" * 64,
            )
            for i, name in enumerate(PAGES)
        ),
    )
    with create_project(chapter, tmp_path / "chapter.mtproj") as opened:
        yield opened


def _open(qtbot) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.resize(WINDOW)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()
    return window


def _on_page(qtbot, project: Project) -> Workspace:  # type: ignore[no-untyped-def]
    """The workspace with page 2 of 3 showing (it has no stored regions)."""
    window = _open(qtbot)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(SHOWN_PAGE)
    _settle()
    return window


def _grid(count: int) -> list[OrderedRegion]:
    """`count` 120 x 90 regions on a 500 x 450 grid, >= 200 px from every edge."""
    regions = []
    for region_id in range(count):
        row, col = divmod(region_id, GRID_COLUMNS)
        x, y = 300 + col * 500, 300 + row * 450
        ring = ((x, y), (x + REGION_W, y), (x + REGION_W, y + REGION_H), (x, y + REGION_H), (x, y))
        regions.append(OrderedRegion(region_id=region_id, polygon=ring))
    return regions


def _populate(window: Workspace, regions: Sequence[OrderedRegion]) -> None:
    window.set_regions(
        regions,
        [f"ja {r.region_id}" for r in regions],
        [f"en {r.region_id}" for r in regions],
    )
    _settle()


def _canvas_view(canvas: PageCanvas) -> tuple[Any, ...]:
    """Everything that says where the canvas is looking: scroll and transform."""
    t = canvas.transform()
    return (
        canvas.horizontalScrollBar().value(),
        canvas.verticalScrollBar().value(),
        (t.m11(), t.m12(), t.m13(), t.m21(), t.m22(), t.m23(), t.m31(), t.m32(), t.m33()),
    )


def _mapped(canvas: PageCanvas, region: OrderedRegion) -> QRect:
    return canvas.mapFromScene(region.bounds()).boundingRect()


def _viewport_rect(canvas: PageCanvas) -> QRect:
    return canvas.viewport().rect()


def _place(canvas: PageCanvas, region: OrderedRegion, left: int, top: int) -> None:
    """Scroll so the region's mapped rect starts at (left, top) in the viewport."""
    zoom = canvas.transform().m11()
    bounds = region.bounds()
    canvas.horizontalScrollBar().setValue(round(zoom * bounds.left()) - left)
    canvas.verticalScrollBar().setValue(round(zoom * bounds.top()) - top)
    _settle()
    assert _mapped(canvas, region).topLeft() == QPoint(left, top), "fixture: scroll range"


def _states(window: Workspace) -> list[MarkerState]:
    return [marker.state() for marker in window.page_canvas.markers]


def _row_visible(window: Workspace, row: int) -> bool:
    lst = window.translation_column.list
    return lst.viewport().rect().contains(lst.visualItemRect(lst.item(row)))


def _row_hovered(window: Workspace, region_id: int) -> bool:
    return bool(window.translation_column.row(region_id).property("hovered"))


def _pointer_to(widget: QWidget, point: QPoint) -> None:
    """Real pointer input, arriving from 1 px away.

    Offscreen, a move to the position the pointer was ALREADY at (where an
    earlier test left it) is dropped, so a single `QTest.mouseMove` can
    silently deliver nothing. Two moves always deliver the second.
    """
    QTest.mouseMove(widget, point - QPoint(1, 1))
    QTest.mouseMove(widget, point)
    _settle()


@pytest.fixture
def recorded_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """Replace `mangatl.ui.link.QAccessible` (imported BY NAME, Contract) with a
    recorder of (event type, event object). The real Event enum is kept."""
    posted: list[tuple[Any, Any]] = []
    stand_in = SimpleNamespace(
        Event=QAccessible.Event,
        updateAccessibility=lambda event: posted.append((event.type(), event.object())),
    )
    monkeypatch.setattr(link_module, "QAccessible", stand_in)
    return posted


# =============================================================================
# Populating: region 0 selected on show (components.md §4.1)
# =============================================================================


def test_setting_regions_selects_the_first_and_populates_one_marker_and_row_each(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(5))

    assert [m.region.region_id for m in window.page_canvas.markers] == [0, 1, 2, 3, 4]
    assert window.translation_column.list.count() == 5
    assert window.link.state.selected_region_id == 0
    assert window.link.state.hovered_region_id is None
    assert window.translation_column.list.currentRow() == 0
    assert _states(window) == [MarkerState.SELECTED] + [MarkerState.IDLE] * 4


def test_setting_no_regions_leaves_nothing_selected_and_no_markers_or_rows(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(3))
    _populate(window, [])

    assert window.page_canvas.markers == []
    assert window.translation_column.list.count() == 0
    assert window.link.state.selected_region_id is None


def test_each_row_leads_with_its_ordinal_badge_and_has_an_editable_editor(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(3))

    for region_id in range(3):
        row = window.translation_column.row(region_id)
        assert row.region_id == region_id
        assert row.badge.text() == str(region_id + 1)
        assert row.badge.geometry().x() < row.editor.geometry().x(), "badge is not leading"
        assert row.editor.text() == f"en {region_id}"
        # MT-016 PO-1 (read-only) is superseded by MT-017 C-8 / PO-5.
        assert not row.editor.isReadOnly()


# =============================================================================
# AC-1 - selecting a row marks exactly that row's region
# =============================================================================


def test_selecting_a_row_marks_exactly_one_region_selected_and_it_is_that_rows(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(5))
    lst = window.translation_column.list

    lst.setCurrentRow(3)
    _settle()
    assert window.link.state.selected_region_id == 3
    assert _states(window) == [MarkerState.IDLE] * 3 + [MarkerState.SELECTED, MarkerState.IDLE]
    assert window.page_canvas.markers[3].region.region_id == 3

    lst.setCurrentRow(1)
    _settle()
    assert _states(window).count(MarkerState.SELECTED) == 1
    assert window.page_canvas.markers[1].state() == MarkerState.SELECTED


def test_clicking_a_rows_badge_selects_that_row_and_marks_its_region(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(5))
    badge = window.translation_column.row(2).badge

    QTest.mouseClick(
        badge, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, badge.rect().center()
    )
    _settle()

    assert window.translation_column.list.currentRow() == 2
    assert window.link.state.selected_region_id == 2
    assert _states(window).count(MarkerState.SELECTED) == 1
    assert window.page_canvas.markers[2].state() == MarkerState.SELECTED


# =============================================================================
# AC-2 - clicking a region selects its row and scrolls the row into view
# =============================================================================


def test_clicking_a_region_on_the_canvas_selects_its_row_and_scrolls_it_into_view(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    target = regions[MANY - 1]
    centre = target.bounds().center()
    canvas.centerOn(centre)
    _settle()
    click = canvas.mapFromScene(centre)
    assert _viewport_rect(canvas).contains(click), "fixture: target not on screen"
    assert not _row_visible(window, MANY - 1), "fixture: last row already in view"

    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click
    )
    _settle()

    assert window.link.state.selected_region_id == MANY - 1
    assert window.translation_column.list.currentRow() == MANY - 1
    assert _row_visible(window, MANY - 1), "the selected row was not scrolled into view"
    assert canvas.markers[MANY - 1].state() == MarkerState.SELECTED


def test_a_drag_on_the_canvas_pans_and_does_not_select(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(5)
    _populate(window, regions)
    canvas = window.page_canvas
    centre = regions[2].bounds().center()
    canvas.centerOn(centre)
    _settle()
    start = canvas.mapFromScene(centre)
    end = start + QPoint(40, 30)

    QTest.mousePress(
        canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start
    )
    QTest.mouseMove(canvas.viewport(), end)
    QTest.mouseRelease(
        canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end
    )
    _settle()

    assert window.link.state.selected_region_id == 0


# =============================================================================
# AC-3 - off-screen selection pans with >= 24 px margin; zoom is untouched
# =============================================================================


def _select_off_screen(window: Workspace, regions: list[OrderedRegion], case: str) -> OrderedRegion:
    """Arrange a selected region that lies outside the viewport; return it."""
    canvas = window.page_canvas
    lst = window.translation_column.list
    if case == "down-right":
        canvas.centerOn(regions[0].bounds().center())
        _settle()
        target = regions[MANY - 1]
    else:  # "up-left"
        lst.setCurrentRow(MANY - 1)
        _settle()
        target = regions[0]
    mapped = _mapped(canvas, target)
    assert not _viewport_rect(canvas).intersects(mapped), "fixture: target already visible"
    lst.setCurrentRow(target.region_id)
    _settle()
    return target


@pytest.mark.parametrize("zoom", [1.0, 2.0])
@pytest.mark.parametrize("case", ["down-right", "up-left"])
def test_selecting_an_off_screen_region_pans_it_fully_in_with_24_px_margin_without_zooming(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    zoom: float,
    case: str,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    canvas.set_zoom(zoom)
    _settle()
    m11, m22 = canvas.transform().m11(), canvas.transform().m22()

    target = _select_off_screen(window, regions, case)

    assert (canvas.transform().m11(), canvas.transform().m22()) == (m11, m22), "selection zoomed"
    m = _mapped(canvas, target)
    vw, vh = canvas.viewport().width(), canvas.viewport().height()
    assert m.left() >= MARGIN, m
    assert m.top() >= MARGIN, m
    assert m.right() <= vw - 1 - MARGIN, (m, vw)
    assert m.bottom() <= vh - 1 - MARGIN, (m, vh)


@pytest.mark.parametrize("zoom", [1.0, 2.0])
@pytest.mark.parametrize("case", ["down-right", "up-left"])
def test_the_pan_is_the_minimum_that_brings_the_region_in_not_a_recentre(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    zoom: float,
    case: str,
) -> None:
    # components.md §4.5: "pans by the MINIMUM translation". Both axes are out
    # in both cases, so the region lands exactly on the margin it came in by.
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    canvas.set_zoom(zoom)
    _settle()

    target = _select_off_screen(window, regions, case)

    m = _mapped(canvas, target)
    vw, vh = canvas.viewport().width(), canvas.viewport().height()
    if case == "down-right":
        assert (m.right(), m.bottom()) == (vw - 1 - MARGIN, vh - 1 - MARGIN), (m, vw, vh)
    else:
        assert (m.left(), m.top()) == (MARGIN, MARGIN), m


# =============================================================================
# AC-4 - a region already fully visible: the viewport does not change at all
# =============================================================================

VISIBLE_TARGET = 7  # grid (col 2, row 1): scene (1300, 750) - reachable everywhere below


def _visible_placements(canvas: PageCanvas, zoom: float) -> dict[str, tuple[int, int]]:
    vw, vh = canvas.viewport().width(), canvas.viewport().height()
    w, h = round(zoom * REGION_W), round(zoom * REGION_H)
    return {
        "well-inside": (200, 150),
        "within-margin-of-top-left": (5, 5),
        "within-margin-of-bottom-right": (vw - 1 - 10 - w, vh - 1 - 10 - h),
        "touching-bottom-right-edges": (vw - 1 - w, vh - 1 - h),
    }


@pytest.mark.parametrize("zoom", [1.0, 2.0])
@pytest.mark.parametrize(
    "placement",
    [
        "well-inside",
        "within-margin-of-top-left",
        "within-margin-of-bottom-right",
        "touching-bottom-right-edges",
    ],
)
def test_selecting_a_region_already_fully_visible_leaves_the_viewport_exactly_as_it_was(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    zoom: float,
    placement: str,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    canvas.set_zoom(zoom)
    _settle()
    target = regions[VISIBLE_TARGET]
    _place(canvas, target, *_visible_placements(canvas, zoom)[placement])
    assert _viewport_rect(canvas).contains(_mapped(canvas, target)), "fixture: not fully visible"
    before = _canvas_view(canvas)

    window.translation_column.list.setCurrentRow(VISIBLE_TARGET)
    _settle()

    assert window.link.state.selected_region_id == VISIBLE_TARGET
    assert _canvas_view(canvas) == before


# =============================================================================
# AC-5 - hover: both sides show it, and nothing moves
# =============================================================================


def test_hovering_a_region_marks_it_and_its_row_and_moves_neither_viewport(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    lst = window.translation_column.list
    hovered = MANY - 1
    vw = canvas.viewport().width()
    # Half on screen: a reveal on hover WOULD pan, and its row is out of the
    # list's view: a scrollToItem on hover WOULD scroll.
    _place(canvas, regions[hovered], vw - 60, 200)
    assert not _viewport_rect(canvas).contains(_mapped(canvas, regions[hovered]))
    assert not _row_visible(window, hovered)
    before = (_canvas_view(canvas), lst.verticalScrollBar().value())

    _pointer_to(canvas.viewport(), QPoint(vw - 40, 220))
    _settle()

    assert window.link.state.hovered_region_id == hovered
    assert canvas.markers[hovered].state() == MarkerState.HOVER
    assert _row_hovered(window, hovered), "the row did not take its hover ground"
    assert (_canvas_view(canvas), lst.verticalScrollBar().value()) == before
    assert window.link.state.selected_region_id == 0
    assert canvas.markers[0].state() == MarkerState.SELECTED


def test_hover_does_not_persist_after_the_pointer_leaves_the_region(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    _place(canvas, regions[6], 200, 200)  # scene (800, 750)
    _pointer_to(canvas.viewport(), QPoint(220, 220))
    _settle()
    assert window.link.state.hovered_region_id == 6

    _pointer_to(canvas.viewport(), QPoint(100, 220))  # scene x 700: between regions
    _settle()

    assert window.link.state.hovered_region_id is None
    assert canvas.markers[6].state() == MarkerState.IDLE
    assert not _row_hovered(window, 6)


def test_hovering_a_row_marks_its_region_and_does_not_pan_the_canvas(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    lst = window.translation_column.list
    canvas.horizontalScrollBar().setValue(canvas.horizontalScrollBar().maximum())
    canvas.verticalScrollBar().setValue(canvas.verticalScrollBar().maximum())
    _settle()
    assert not _viewport_rect(canvas).intersects(_mapped(canvas, regions[3])), "fixture"
    before = (_canvas_view(canvas), lst.verticalScrollBar().value())

    _pointer_to(window.translation_column.row(3), QPoint(5, 5))
    _settle()

    assert window.link.state.hovered_region_id == 3
    assert canvas.markers[3].state() == MarkerState.HOVER
    assert _row_hovered(window, 3)
    assert (_canvas_view(canvas), lst.verticalScrollBar().value()) == before
    assert window.link.state.selected_region_id == 0

    _pointer_to(window.translation_column.row(4), QPoint(5, 5))
    _settle()

    assert window.link.state.hovered_region_id == 4
    assert canvas.markers[3].state() == MarkerState.IDLE
    assert not _row_hovered(window, 3)
    assert canvas.markers[4].state() == MarkerState.HOVER


def test_hovering_the_selected_region_does_not_change_its_selected_appearance(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    # components.md §4.4: hover "never changes the selected marker's appearance".
    window = _on_page(qtbot, project)
    regions = _grid(5)
    _populate(window, regions)
    canvas = window.page_canvas
    _place(canvas, regions[0], 200, 200)

    _pointer_to(canvas.viewport(), QPoint(220, 220))
    _settle()

    assert window.link.state.hovered_region_id == 0
    assert canvas.markers[0].state() == MarkerState.SELECTED
    assert window.link.state.selected_region_id == 0


# =============================================================================
# AC-6 - overlapping regions: smallest wins, the same point cycles
# =============================================================================


def _overlapping(window: Workspace) -> tuple[PageCanvas, QPoint]:
    big = OrderedRegion(
        region_id=0, polygon=((500, 500), (800, 500), (800, 800), (500, 800), (500, 500))
    )
    small = OrderedRegion(
        region_id=1, polygon=((600, 600), (700, 600), (700, 700), (600, 700), (600, 600))
    )
    _populate(window, [big, small])
    canvas = window.page_canvas
    canvas.centerOn(QPointF(650, 650))
    _settle()
    # Both fit on screen, so no selection below pans and a screen point stays
    # the same scene point.
    for region in (big, small):
        assert _viewport_rect(canvas).contains(_mapped(canvas, region)), "fixture"
    return canvas, canvas.mapFromScene(QPointF(650, 650))


def _click(canvas: PageCanvas, at: QPoint) -> None:
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at
    )
    _settle()


def test_clicking_an_overlap_selects_the_smaller_then_cycles_to_the_other_and_back(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    canvas, point = _overlapping(window)
    view = _canvas_view(canvas)

    selections = []
    for _ in range(3):
        _click(canvas, point)
        selections.append(window.link.state.selected_region_id)

    assert selections == [1, 0, 1]
    assert _canvas_view(canvas) == view


def test_a_click_more_than_3_px_away_starts_over_at_the_smallest_and_within_3_px_cycles(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    canvas, point = _overlapping(window)
    _click(canvas, point)
    assert window.link.state.selected_region_id == 1

    _click(canvas, point + QPoint(10, 0))  # not the same point: smallest again
    assert window.link.state.selected_region_id == 1

    _click(canvas, point + QPoint(12, 0))  # 2 px from the previous click: cycles
    assert window.link.state.selected_region_id == 0


# =============================================================================
# AC-7 - dimming (the badge half is in test_markers.py)
# =============================================================================


def _opacities(window: Workspace) -> list[float]:
    return [marker.opacity() for marker in window.page_canvas.markers]


def test_with_a_selection_every_other_marker_is_dimmed_to_the_token_opacity(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(5))

    window.translation_column.list.setCurrentRow(2)
    _settle()

    assert _opacities(window) == [DIM, DIM, 1.0, DIM, DIM]


def test_with_no_selection_no_marker_is_dimmed_and_hover_dims_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(5)
    _populate(window, regions)

    window.link.select(None)
    _settle()
    assert _opacities(window) == [1.0] * 5
    assert MarkerState.SELECTED not in _states(window)

    _place(window.page_canvas, regions[1], 200, 200)
    _pointer_to(window.page_canvas.viewport(), QPoint(220, 220))
    _settle()
    assert window.link.state.hovered_region_id == 1
    assert _opacities(window) == [1.0] * 5


# =============================================================================
# AC-9 - keyboard: Up/Down in the column; Enter on the canvas
# =============================================================================


def test_down_and_up_in_the_column_move_the_selection_between_rows(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(5))
    lst = window.translation_column.list
    lst.setFocus()
    _settle()
    assert lst.hasFocus()

    QTest.keyClick(lst, Qt.Key.Key_Down)
    _settle()
    assert window.link.state.selected_region_id == 1
    assert window.page_canvas.markers[1].state() == MarkerState.SELECTED

    QTest.keyClick(lst, Qt.Key.Key_Down)
    _settle()
    assert window.link.state.selected_region_id == 2

    QTest.keyClick(lst, Qt.Key.Key_Up)
    _settle()
    assert window.link.state.selected_region_id == 1
    assert lst.currentRow() == 1


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["Return", "Enter"])
def test_enter_on_the_canvas_moves_focus_into_the_selected_rows_editor(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    key: Qt.Key,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(10))
    window.translation_column.list.setCurrentRow(7)
    _settle()
    canvas = window.page_canvas
    canvas.setFocus()
    _settle()
    assert canvas.hasFocus()

    QTest.keyClick(canvas, key)
    _settle()

    editor = window.translation_column.row(7).editor
    assert QApplication.focusWidget() is editor
    assert window.link.state.selected_region_id == 7


# =============================================================================
# AC-10 - accessible names and the live region
# =============================================================================

JAPANESE = ["こんにちは", None, "さようなら"]
ENGLISH = ["Hello", "Bye", None]
EXPECTED_ROW_TEXT = [
    "Bubble 1 of 3. Japanese: こんにちは. English: Hello. machine proposal.",
    "Bubble 2 of 3. Japanese: not read. English: Bye. machine proposal.",
    "Bubble 3 of 3. Japanese: さようなら. English: not translated. machine proposal.",
]


def test_every_rows_accessible_text_leads_with_its_ordinal_in_the_components_md_format(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    window.set_regions(_grid(3), JAPANESE, ENGLISH)
    _settle()
    lst = window.translation_column.list

    item_texts = [lst.item(i).data(Qt.ItemDataRole.AccessibleTextRole) for i in range(3)]
    assert item_texts == EXPECTED_ROW_TEXT

    interface = QAccessible.queryAccessibleInterface(lst)
    assert interface is not None
    names = [interface.child(i).text(QAccessible.Text.Name) for i in range(3)]
    assert names == EXPECTED_ROW_TEXT


def test_the_selected_row_is_the_one_the_accessibility_tree_reports_selected(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    window.set_regions(_grid(3), JAPANESE, ENGLISH)
    _settle()

    window.link.select(2)
    _settle()

    interface = QAccessible.queryAccessibleInterface(window.translation_column.list)
    assert [bool(interface.child(i).state().selected) for i in range(3)] == [False, False, True]
    selected_name = interface.child(2).text(QAccessible.Text.Name)
    assert selected_name.startswith("Bubble 3 of 3.")


def test_a_selection_change_announces_bubble_and_page_through_the_live_region(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    recorded_alerts: list[tuple[Any, Any]],
) -> None:
    window = _on_page(qtbot, project)
    window.set_regions(_grid(3), JAPANESE, ENGLISH)
    _settle()
    live = window.live_region
    recorded_alerts.clear()

    window.translation_column.list.setCurrentRow(2)
    _settle()

    expected = "Bubble 3 of 3 selected. Page 2 of 3."
    assert live.accessibleName() == expected
    assert live.text() == expected
    live_interface = QAccessible.queryAccessibleInterface(live)
    assert live_interface.text(QAccessible.Text.Name) == expected
    assert recorded_alerts == [(QAccessible.Event.Alert, live)]

    window.link.select(0)
    _settle()
    assert live.accessibleName() == "Bubble 1 of 3 selected. Page 2 of 3."
    assert len(recorded_alerts) == 2


# =============================================================================
# PO-2 - show_page reads the page's regions and lines from the project
# =============================================================================


def _ring(x: int, y: int, w: int, h: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y))


STORED_RINGS = (_ring(2400, 300, 200, 150), _ring(1500, 900, 160, 160), _ring(400, 2000, 300, 90))


def _store_page(project: Project, ordinal: int, *, with_lines: bool) -> None:
    mask = _png_bytes(QSize(4, 4))
    project.write_regions(
        ordinal,
        [
            RawRegion(polygon=ring, mask=mask, confidence=0.9, kind="bubble")
            for ring in STORED_RINGS
        ],
    )
    if with_lines:
        project.write_lines(
            ordinal,
            [OcrResult("こんにちは"), OcrResult("", ocr_empty=True), OcrResult("さようなら")],
        )
        project.write_proposed(ordinal, {0: "Hello", 2: "Goodbye"})


def test_showing_a_page_loads_its_stored_regions_as_markers_and_its_lines_as_rows(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    _store_page(project, 0, with_lines=True)
    window = _open(qtbot)
    window.load_chapter(project)

    window.page_strip.setCurrentRow(0)
    _settle()

    markers = window.page_canvas.markers
    assert [m.region.region_id for m in markers] == [0, 1, 2]
    assert [m.region.bounds() for m in markers] == [
        QRectF(2400, 300, 200, 150),
        QRectF(1500, 900, 160, 160),
        QRectF(400, 2000, 300, 90),
    ]
    lst = window.translation_column.list
    assert [lst.item(i).data(Qt.ItemDataRole.AccessibleTextRole) for i in range(lst.count())] == [
        "Bubble 1 of 3. Japanese: こんにちは. English: Hello. machine proposal.",
        # an ocr_empty line is "not read"; an absent proposal is "not translated";
        # and since MT-017 (C-2 rule 2, AC-8) an ocr_empty line is failed.
        "Bubble 2 of 3. Japanese: not read. English: not translated."
        " translation failed: no text was read in this bubble.",
        "Bubble 3 of 3. Japanese: さようなら. English: Goodbye. machine proposal.",
    ]
    assert window.link.state.selected_region_id == 0
    assert markers[0].state() == MarkerState.SELECTED
    assert window.live_region.accessibleName() == "Bubble 1 of 3 selected. Page 1 of 3."


def test_a_page_with_regions_but_no_lines_yet_shows_rows_not_read_and_not_translated(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    _store_page(project, 0, with_lines=False)
    window = _open(qtbot)
    window.load_chapter(project)

    window.page_strip.setCurrentRow(0)
    _settle()

    lst = window.translation_column.list
    assert lst.count() == 3
    assert lst.item(1).data(Qt.ItemDataRole.AccessibleTextRole) == (
        "Bubble 2 of 3. Japanese: not read. English: not translated. machine proposal."
    )


def test_changing_page_clears_hover_and_selects_the_new_pages_first_region(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    _store_page(project, 0, with_lines=True)
    window = _open(qtbot)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(0)
    _settle()
    window.link.select(2)
    window.link.hover(1)
    _settle()

    window.page_strip.setCurrentRow(SHOWN_PAGE)  # a page with no stored regions
    _settle()
    assert window.page_canvas.markers == []
    assert window.translation_column.list.count() == 0
    assert window.link.state.selected_region_id is None
    assert window.link.state.hovered_region_id is None

    window.page_strip.setCurrentRow(0)
    _settle()
    assert window.link.state.selected_region_id == 0
    assert window.link.state.hovered_region_id is None
    assert len(window.page_canvas.markers) == 3


def test_a_page_that_fails_to_decode_shows_no_markers_and_no_rows(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    _store_page(project, 0, with_lines=True)
    _store_page(project, JUNK_PAGE_ORDINAL, with_lines=True)
    window = _open(qtbot)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(0)
    _settle()

    window.page_strip.setCurrentRow(JUNK_PAGE_ORDINAL)
    _settle()

    assert window.page_canvas.markers == []
    assert window.translation_column.list.count() == 0
    assert window.link.state.selected_region_id is None
