"""MT-049: hover does not persist after the pointer leaves the canvas.

`components.md` §4.4 (normative): hover "never persists after the pointer
leaves". MT-016 shipped hover reported only from `mouseMoveEvent`, so leaving
the canvas while over a region at the viewport EDGE left that region hovered:
the last move inside the viewport reported it, and nothing later reported
"nothing". Every fixture below puts the hovered region across a viewport edge
and the pointer's last position inside the viewport ON that region, so the
exit is straight off the region. A fixture where the pointer crossed empty art
on the way out would be green against the defect.

Offscreen mechanics, measured in RED (PySide6 6.9.3, QT_QPA_PLATFORM=offscreen;
story Handoff):
- A real `QTest.mouseMove` from the canvas viewport onto the page strip DOES
  deliver `Leave` to `canvas.viewport()` (then to the canvas), followed by
  `Enter` on the strip, all synchronously inside the one `mouseMove` call.
  AC-1 therefore uses real input.
- A real move from the canvas viewport onto a translation row delivers
  `Leave` to the viewport BEFORE `Enter` to the row. AC-4 depends on that order.
- AC-2 ("Leave and no Enter") is `QApplication.sendEvent(viewport, QEvent(Leave))`
  by the story's definition.
- A move to the position the pointer already has is dropped (MT-016 quirk 3),
  so every move goes through `_pointer_to`, arriving from 1 px away.

AC-3 is SETTLED, read out of §4.4 ("purely visual") and §4.1 ("hover never
changes selection, and selection is never lost by moving the mouse"): scroll
values and the transform are compared EXACTLY.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from mangatl.domain.page import Chapter, Page
from mangatl.store.project import Project, create_project
from mangatl.ui import tokens_gen
from mangatl.ui.canvas import PageCanvas
from mangatl.ui.link import OrderedRegion
from mangatl.ui.markers import MarkerState
from mangatl.ui.workspace import Workspace

# --- Settled numbers, read out ------------------------------------------------
DIM = tokens_gen.OVERLAY_DIM_OPACITY  # components.md §4.3

# --- Fixture geometry (copied from tests/ui/test_link_workspace.py) -----------
PAGE = QSize(3000, 4000)
WINDOW = QSize(1100, 720)  # the workspace minimum; the canvas shows part of the page
GRID_COLUMNS = 5
REGION_W, REGION_H = 120, 90
MANY = 40  # enough rows that the last is out of the list's view
SHOWN_PAGE = 1  # page 2 of 3 has no stored regions; the tests set their own
PAGES = ("001.png", "002.png", "003.png")

HOVERED = 2  # never the selected region, so its marker can show HOVER
OTHER_ROW = 3  # AC-4: the row the pointer moves onto
OVERHANG = 60  # px of the hovered region that lie OUTSIDE the viewport edge
POINTER_Y = 20  # px below the region's mapped top: well inside it vertically


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
    return _png_bytes(PAGE)


@pytest.fixture
def project(tmp_path: Path, page_png: bytes) -> Iterator[Project]:
    source = tmp_path / "chapter"
    source.mkdir()
    for name in PAGES:
        (source / name).write_bytes(page_png)
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


def _place(canvas: PageCanvas, region: OrderedRegion, left: int, top: int) -> None:
    """Scroll so the region's mapped rect starts at (left, top) in the viewport."""
    zoom = canvas.transform().m11()
    bounds = region.bounds()
    canvas.horizontalScrollBar().setValue(round(zoom * bounds.left()) - left)
    canvas.verticalScrollBar().setValue(round(zoom * bounds.top()) - top)
    _settle()
    assert _mapped(canvas, region).topLeft() == QPoint(left, top), "fixture: scroll range"


def _hovered_markers(window: Workspace) -> list[int]:
    return [
        marker.region.region_id
        for marker in window.page_canvas.markers
        if marker.state() == MarkerState.HOVER
    ]


def _hovered_rows(window: Workspace, count: int) -> list[int]:
    return [
        region_id
        for region_id in range(count)
        if window.translation_column.row(region_id).property("hovered")
    ]


def _pointer_to(widget: QWidget, point: QPoint) -> None:
    """Real pointer input, arriving from 1 px away (MT-016 quirk 3)."""
    QTest.mouseMove(widget, point - QPoint(1, 1))
    QTest.mouseMove(widget, point)
    _settle()


def _hover_at_edge(window: Workspace, regions: Sequence[OrderedRegion], edge: str) -> None:
    """Hover HOVERED with the region straddling the viewport's `edge` ("left" or
    "right") and the pointer's last position in the viewport on the region, 1 px
    from that edge. Asserts the hovered starting state every AC shares."""
    canvas = window.page_canvas
    vw = canvas.viewport().width()
    region = regions[HOVERED]
    top = 200
    if edge == "left":
        _place(canvas, region, -OVERHANG, top)
        point = QPoint(1, top + POINTER_Y)
    else:
        _place(canvas, region, vw - (REGION_W - OVERHANG), top)
        point = QPoint(vw - 2, top + POINTER_Y)
    mapped = _mapped(canvas, region)
    assert mapped.contains(point), f"fixture: pointer {point} is not over the region {mapped}"
    assert not canvas.viewport().rect().contains(mapped), "fixture: region is not at the edge"

    _pointer_to(canvas.viewport(), point)

    assert window.link.state.hovered_region_id == HOVERED, "fixture: region not hovered"
    assert canvas.markers[HOVERED].state() == MarkerState.HOVER, "fixture: marker not HOVER"
    assert window.translation_column.row(HOVERED).property("hovered"), "fixture: row not hovered"


def _leave_onto_strip(window: Workspace) -> None:
    """Real input: the pointer goes from the canvas viewport onto the page strip."""
    _pointer_to(window.page_strip.viewport(), QPoint(50, 220))


def _leave_to_nowhere(window: Workspace) -> None:
    """The viewport gets Leave and nothing gets Enter (AC-2, by definition)."""
    QApplication.sendEvent(window.page_canvas.viewport(), QEvent(QEvent.Type.Leave))
    _settle()


LEAVES = {"onto-page-strip": _leave_onto_strip, "to-no-widget": _leave_to_nowhere}


def _assert_no_hover_anywhere(window: Workspace, count: int, how: str) -> None:
    stale = window.link.state.hovered_region_id
    assert stale is None, (
        f"hover persisted after the pointer left the canvas ({how}): "
        f"hovered_region_id is still {stale}"
    )
    assert _hovered_markers(window) == [], (
        f"a marker stayed in HOVER after the pointer left the canvas ({how}): "
        f"regions {_hovered_markers(window)}"
    )
    assert _hovered_rows(window, count) == [], (
        f"a row kept its hover ground after the pointer left the canvas ({how}): "
        f"rows {_hovered_rows(window, count)}"
    )


# =============================================================================
# AC-1 - leaving the viewport onto another widget (the page strip) clears hover
# =============================================================================


def test_hover_clears_when_the_pointer_leaves_the_canvas_from_a_region_onto_the_page_strip(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(5)
    _populate(window, regions)
    _hover_at_edge(window, regions, "left")  # the strip is to the canvas's left

    _leave_onto_strip(window)

    _assert_no_hover_anywhere(window, len(regions), "onto the page strip")


# =============================================================================
# AC-2 - leaving the viewport without entering any widget clears hover
# =============================================================================


@pytest.mark.parametrize("edge", ["left", "right"])
def test_hover_clears_when_the_viewport_gets_leave_and_no_widget_gets_enter(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    edge: str,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(5)
    _populate(window, regions)
    _hover_at_edge(window, regions, edge)

    _leave_to_nowhere(window)

    _assert_no_hover_anywhere(window, len(regions), "Leave with no Enter")


# =============================================================================
# AC-3 - leaving changes neither the selection nor any viewport (§4.4, §4.1)
# =============================================================================


@pytest.mark.parametrize("leave", sorted(LEAVES))
def test_leaving_the_canvas_keeps_the_selection_its_dimming_and_both_viewports_exactly(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    leave: str,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    lst = window.translation_column.list
    selected = MANY - 1
    lst.setCurrentRow(selected)  # pans the canvas to it and scrolls the list down
    _settle()
    _hover_at_edge(window, regions, "left")
    # A reveal of the selection on Leave WOULD pan (it is now off-screen), and a
    # scrollToItem of the hovered row WOULD scroll (the list is at the bottom).
    assert not canvas.viewport().rect().intersects(_mapped(canvas, regions[selected])), "fixture"
    assert lst.verticalScrollBar().value() > 0, "fixture: list is not scrolled"
    before_canvas = _canvas_view(canvas)
    before_list = lst.verticalScrollBar().value()

    LEAVES[leave](window)

    assert window.link.state.selected_region_id == selected, "leaving the canvas changed selection"
    assert lst.currentRow() == selected, "leaving the canvas changed the current row"
    assert canvas.markers[selected].state() == MarkerState.SELECTED
    assert canvas.markers[selected].opacity() == 1.0
    others = [m for m in canvas.markers if m.region.region_id != selected]
    assert [m.opacity() for m in others] == [DIM] * (MANY - 1), "an unselected marker undimmed"
    assert _canvas_view(canvas) == before_canvas, "leaving the canvas moved the canvas viewport"
    assert lst.verticalScrollBar().value() == before_list, "leaving the canvas scrolled the list"


# =============================================================================
# AC-4 - canvas -> a different region's row: the row's hover survives the leave
# =============================================================================


def test_moving_from_a_hovered_region_straight_onto_another_regions_row_hovers_that_row(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(5)
    _populate(window, regions)
    _hover_at_edge(window, regions, "right")  # the column is to the canvas's right
    row = window.translation_column.row(OTHER_ROW)
    lst = window.translation_column.list
    assert lst.viewport().rect().contains(lst.visualItemRect(lst.item(OTHER_ROW))), "fixture"

    _pointer_to(row, QPoint(5, 5))
    # Run the event loop again: a clear the canvas deferred to a later turn of
    # the loop (QTimer.singleShot(0, ...)) lands here, after the row's Enter.
    qtbot.wait(0)
    _settle()

    got = window.link.state.hovered_region_id
    assert got == OTHER_ROW, (
        f"the canvas leaving wiped the hover the row set: hovered_region_id is {got}, "
        f"expected {OTHER_ROW}"
    )
    assert _hovered_markers(window) == [OTHER_ROW]
    assert _hovered_rows(window, len(regions)) == [OTHER_ROW]
    assert window.page_canvas.markers[HOVERED].state() == MarkerState.IDLE
