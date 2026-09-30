"""MT-052: the off-screen indicator on the canvas, and bringing the region back.

`components.md` §4.6 (normative), `accessibility.md` A-07 (`Ctrl+9` must never
regress) and A-08 (the accessible name). The indicator is a child WIDGET of
`canvas.viewport()` (A-13.1: graphics items are invisible to UI Automation).

"Fully visible" (Q4, story AC preamble) is B2 exactly: the region's mapped
bounding rect `QRectF(canvas.mapFromScene(region.bounds()).boundingRect())`
lies entirely inside `QRectF(canvas.viewport().rect())`, with NO margin.
`_fully_visible` below is that predicate, and every fixture asserts which side
of it the region is on before the behaviour under test runs.

Oracle partition (story `## Contract`):
- AC-1..AC-4 MECHANICAL: `isVisible()`, the count of `OffscreenIndicator`
  children, the predicate. AC-3's boundary control is in `test_offscreen.py`
  (local predicates, runs in RED); the canvas-level boundary cases are here.
- AC-5 SETTLED: B3/B4 by hand, re-asserted after a SECOND pan - one pan along
  the edge (the expected position moves) and one pan perpendicular to it (the
  expected position does NOT move, but a child widget that is not re-pinned
  after `scrollContentsBy` is carried along by the scroll: measured in RED,
  a +50 px vertical scroll moved a plain viewport child from y 0 to y -50).
- AC-8 SETTLED (Q1): centre; zoom out only if the region does not fit the 24 px
  inset at the current zoom, to exactly B8's target; NEVER zoom in. m11 and m22
  are asserted with `==` where the zoom must not change.
- AC-9 MECHANICAL: real `QTest` clicks and moves on the indicator.

Offscreen mechanics measured in RED (PySide6, QT_QPA_PLATFORM=offscreen; story
Handoff): a bare 600 x 500 PageCanvas has a 598 x 498 viewport; a real
`QTest.mouseMove` from the viewport onto a child widget of it delivers `Enter`
to the child and NOTHING to the viewport - no `Leave`, so MT-049's handler
alone does not clear hover there (Contract B6 amended by RED).

`mangatl.ui.offscreen` is imported inside test bodies, so the file collects
while the module does not exist.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QAccessible, QColor, QImage, QKeyEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from mangatl.domain.page import Chapter, Page
from mangatl.store.project import Project, create_project
from mangatl.ui.canvas import PageCanvas
from mangatl.ui.link import SELECTION_MARGIN_PX, LinkState, OrderedRegion
from mangatl.ui.workspace import Workspace

# --- Settled numbers, read out ------------------------------------------------
MARGIN = SELECTION_MARGIN_PX  # components.md §4.5 `space.6`
assert MARGIN == 24
TARGET = 28  # accessibility.md A-05
H = TARGET // 2
ZOOM_MIN = 0.10  # components.md §3: "Zoom range 10%-800%"

# --- Fixture geometry ---------------------------------------------------------
PAGE_SIDE = 2000  # the bare canvas's page: 2000 x 2000
CANVAS = QSize(600, 500)  # viewport measured 598 x 498 offscreen


def _ring(x: int, y: int, w: int, h: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y))


# 99 px regions map to a 100 px inclusive QRect at zoom 1, so every centre in
# the AC-5 cases is a whole pixel (B4: rounding is never what a test turns on).
# Every region is >= 1 px from the page's right and bottom edges (Contract).
SMALL = OrderedRegion(region_id=0, polygon=_ring(900, 900, 99, 99))
OTHER = OrderedRegion(region_id=1, polygon=_ring(300, 300, 99, 99))
UNDER = OrderedRegion(region_id=2, polygon=_ring(850, 1190, 200, 210))  # AC-9: under the indicator
WIDE = OrderedRegion(region_id=3, polygon=_ring(500, 1500, 900, 99))  # wider than the viewport
TALL = OrderedRegion(region_id=4, polygon=_ring(1300, 400, 99, 800))  # taller than the viewport
REGIONS = [SMALL, OTHER, UNDER, WIDE, TALL]
HUGE = OrderedRegion(region_id=6, polygon=_ring(50, 950, 1900, 99))  # AC-8: 10% clamp


def _off() -> ModuleType:
    return importlib.import_module("mangatl.ui.offscreen")


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


class KeyRecorder(QWidget):
    """The canvas's parent: records every key that propagates out of the canvas."""

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[tuple[int, Any]] = []

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.keys.append((event.key(), event.modifiers()))
        super().keyPressEvent(event)


@pytest.fixture(scope="session")
def page_image(qapp) -> QImage:  # type: ignore[no-untyped-def]
    image = QImage(QSize(PAGE_SIDE, PAGE_SIDE), QImage.Format.Format_RGB32)
    image.fill(QColor(128, 128, 128))
    return image


@pytest.fixture
def canvas(qtbot, page_image: QImage) -> Iterator[PageCanvas]:  # type: ignore[no-untyped-def]
    """A PageCanvas (598 x 498 viewport) in a key-recording parent, showing a
    2000 x 2000 page with REGIONS and nothing selected, zoom 1, scrolled to 700.

    A generator, so `parent` stays referenced for the whole test: qtbot does
    not keep the Python wrapper alive, and a collected parent deletes the canvas.
    """
    parent = KeyRecorder()
    qtbot.addWidget(parent)
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    view = PageCanvas()
    layout.addWidget(view)
    parent.resize(CANVAS)
    view.set_page(QPixmap.fromImage(page_image))
    view.set_regions(REGIONS)
    with qtbot.waitExposed(parent):
        parent.show()
    view.horizontalScrollBar().setValue(700)
    view.verticalScrollBar().setValue(700)
    _settle()
    yield view
    del parent


# --- Helpers ------------------------------------------------------------------


def _region_rect(view: PageCanvas, region: OrderedRegion) -> QRectF:
    """B2's region_rect, exactly as `reveal` computes it."""
    return QRectF(view.mapFromScene(region.bounds()).boundingRect())


def _view_rect(view: PageCanvas) -> QRectF:
    return QRectF(view.viewport().rect())


def _fully_visible(view: PageCanvas, region: OrderedRegion) -> bool:
    """B2 / Q4: entirely inside the viewport, NO margin."""
    r, v = _region_rect(view, region), _view_rect(view)
    return (
        r.left() >= v.left()
        and r.top() >= v.top()
        and r.right() <= v.right()
        and (r.bottom() <= v.bottom())
    )


def _place(view: PageCanvas, region: OrderedRegion, left: int, top: int) -> None:
    """Scroll so the region's mapped rect starts at (left, top) in the viewport."""
    zoom = view.transform().m11()
    bounds = region.bounds()
    view.horizontalScrollBar().setValue(round(zoom * bounds.left()) - left)
    view.verticalScrollBar().setValue(round(zoom * bounds.top()) - top)
    _settle()
    got = view.mapFromScene(region.bounds()).boundingRect().topLeft()
    assert got == QPoint(left, top), f"fixture: scroll range ({got})"


def _select(view: PageCanvas, region_id: int | None, *, reveal: bool = True) -> None:
    """What Workspace._on_selection_changed does: restyle, then MT-016's pan."""
    view.set_link_state(LinkState(selected_region_id=region_id))
    if reveal and region_id is not None:
        view.reveal(region_id)
    _settle()


def _indicators(view: PageCanvas) -> list[Any]:
    return list(view.findChildren(_off().OffscreenIndicator))


def _shown(view: PageCanvas) -> bool:
    return bool(view.offscreen_indicator.isVisible())


def _canvas_view(view: PageCanvas) -> tuple[Any, ...]:
    t = view.transform()
    return (
        view.horizontalScrollBar().value(),
        view.verticalScrollBar().value(),
        (t.m11(), t.m12(), t.m13(), t.m21(), t.m22(), t.m23(), t.m31(), t.m32(), t.m33()),
    )


def _off_screen_and_shown(view: PageCanvas, region: OrderedRegion) -> None:
    """Select `region` (no pan) with it placed well beyond the left edge."""
    _select(view, region.region_id, reveal=False)
    _place(view, region, -300, 100)
    assert not _fully_visible(view, region), "fixture: region is visible"
    assert _shown(view), "fixture: the indicator is not shown for an off-screen selection"


# =============================================================================
# B1/B6 - one indicator, created once, a child of the viewport outside its layout
# =============================================================================


def test_the_canvas_has_exactly_one_indicator_a_child_of_the_viewport_outside_its_layout(
    canvas: PageCanvas,
) -> None:
    indicator = canvas.offscreen_indicator
    assert _indicators(canvas) == [indicator]
    assert indicator.parentWidget() is canvas.viewport()
    assert canvas.viewport().layout().indexOf(indicator) == -1, "it is not the message's layout"
    assert not _shown(canvas), "nothing is selected: no indicator"


# =============================================================================
# AC-1 - a region that cannot fit: after the MT-016 pan, one indicator with its ordinal
# =============================================================================


@pytest.mark.parametrize("region", [WIDE, TALL], ids=["wider", "taller"])
def test_a_selected_region_too_big_for_the_viewport_shows_one_indicator_with_its_ordinal(
    canvas: PageCanvas,
    region: OrderedRegion,
) -> None:
    _select(canvas, region.region_id)  # reveal has centred it on the overflowing axis
    assert not _fully_visible(canvas, region), "fixture: region fits"

    assert _shown(canvas), "no indicator for a selected region larger than the viewport"
    assert [i for i in _indicators(canvas) if i.isVisible()] == [canvas.offscreen_indicator]
    assert canvas.offscreen_indicator.ordinal() == region.ordinal


def test_a_selected_region_the_pan_brings_fully_in_shows_no_indicator(canvas: PageCanvas) -> None:
    canvas.horizontalScrollBar().setValue(0)
    canvas.verticalScrollBar().setValue(0)
    _settle()
    assert not _fully_visible(canvas, SMALL), "fixture"

    _select(canvas, SMALL.region_id)

    assert _fully_visible(canvas, SMALL), "fixture: MT-016's reveal did not bring it in"
    assert not _shown(canvas)


# =============================================================================
# AC-2 - fully visible, then a pan, a zoom or a resize takes it out: shown
# =============================================================================

# (left, top) as functions of the viewport size; each straddles one edge.
PAN_OUT: dict[str, Callable[[int, int], tuple[int, int]]] = {
    "past-left": lambda vw, vh: (-50, 150),
    "past-right": lambda vw, vh: (vw - 50, 150),
    "past-top": lambda vw, vh: (200, -50),
    "past-bottom": lambda vw, vh: (200, vh - 50),
}


def _visible_and_hidden(view: PageCanvas, left: int = 200, top: int = 150) -> None:
    _select(view, SMALL.region_id, reveal=False)
    _place(view, SMALL, left, top)
    assert _fully_visible(view, SMALL), "fixture"
    assert not _shown(view), "fixture: indicator shown for a fully visible region"


@pytest.mark.parametrize("pan", sorted(PAN_OUT))
def test_panning_a_fully_visible_selected_region_partly_out_shows_the_indicator(
    canvas: PageCanvas,
    pan: str,
) -> None:
    _visible_and_hidden(canvas)
    vw, vh = canvas.viewport().width(), canvas.viewport().height()

    _place(canvas, SMALL, *PAN_OUT[pan](vw, vh))

    assert not _fully_visible(canvas, SMALL), "fixture"
    assert _shown(canvas), f"no indicator after a pan {pan} left the region not fully visible"
    assert canvas.offscreen_indicator.ordinal() == SMALL.ordinal


def test_zooming_in_until_the_selected_region_is_no_longer_fully_visible_shows_the_indicator(
    canvas: PageCanvas,
) -> None:
    vw = canvas.viewport().width()
    _visible_and_hidden(canvas, vw - 150, 150)

    canvas.set_zoom(2.0)
    _settle()

    assert not _fully_visible(canvas, SMALL), "fixture: the zoom left it visible"
    assert _shown(canvas)


def test_shrinking_the_window_until_the_selected_region_is_cut_off_shows_the_indicator(
    canvas: PageCanvas,
) -> None:
    vw, vh = canvas.viewport().width(), canvas.viewport().height()
    _visible_and_hidden(canvas, vw - 150, vh - 150)

    canvas.parentWidget().resize(400, 350)
    _settle()

    assert not _fully_visible(canvas, SMALL), "fixture: the resize left it visible"
    assert _shown(canvas)


# =============================================================================
# AC-3 - fully visible again, or nothing to point at: hidden
# =============================================================================


def test_panning_the_region_back_fully_into_view_hides_the_indicator(canvas: PageCanvas) -> None:
    _off_screen_and_shown(canvas, SMALL)

    _place(canvas, SMALL, 200, 150)

    assert _fully_visible(canvas, SMALL), "fixture"
    assert not _shown(canvas)


def test_zooming_out_until_the_region_is_fully_visible_hides_the_indicator(
    canvas: PageCanvas,
) -> None:
    vw = canvas.viewport().width()
    _select(canvas, SMALL.region_id, reveal=False)
    _place(canvas, SMALL, vw - 50, 150)  # straddles the right edge
    assert _shown(canvas), "fixture"

    canvas.set_zoom(0.5)
    _settle()

    assert _fully_visible(canvas, SMALL), "fixture: the zoom left it cut off"
    assert not _shown(canvas)


def test_selecting_a_different_fully_visible_region_hides_the_indicator(canvas: PageCanvas) -> None:
    _off_screen_and_shown(canvas, SMALL)
    _place(canvas, OTHER, 200, 150)
    assert not _fully_visible(canvas, SMALL) and _fully_visible(canvas, OTHER), "fixture"
    assert _shown(canvas), "fixture"

    _select(canvas, OTHER.region_id, reveal=False)

    assert not _shown(canvas)


def test_selecting_nothing_hides_the_indicator(canvas: PageCanvas) -> None:
    _off_screen_and_shown(canvas, SMALL)

    _select(canvas, None)

    assert not _shown(canvas)


def test_a_selection_naming_no_region_on_the_page_shows_no_indicator(canvas: PageCanvas) -> None:
    _off_screen_and_shown(canvas, SMALL)

    _select(canvas, 99, reveal=False)

    assert not _shown(canvas)


PAGE_CHANGES: dict[str, Callable[[PageCanvas, QImage], None]] = {
    "regions-cleared": lambda view, image: view.set_regions([]),
    "new-page-no-regions": lambda view, image: view.set_page(QPixmap.fromImage(image)),
    "failed-page": lambda view, image: view.set_page(None, error="003.png"),
    "empty-canvas": lambda view, image: view.set_page(None),
}


@pytest.mark.parametrize("change", sorted(PAGE_CHANGES))
def test_a_page_with_no_regions_a_failed_page_or_no_page_hides_the_indicator_and_keeps_it(
    canvas: PageCanvas,
    page_image: QImage,
    change: str,
) -> None:
    _off_screen_and_shown(canvas, SMALL)
    indicator = canvas.offscreen_indicator

    PAGE_CHANGES[change](canvas, page_image)
    _settle()

    assert not _shown(canvas), f"indicator still shown after {change}"
    assert canvas.offscreen_indicator is indicator, "the indicator was replaced"
    assert _indicators(canvas) == [indicator]


# Q4: inside the viewport but within 24 px of its edge. Placements as functions
# of the viewport size; SMALL is 100 x 100 inclusive, so left = vw - 100 puts
# its QRectF right exactly on the viewport's right.
BOUNDARY: dict[str, Callable[[int, int], tuple[int, int]]] = {
    "touching-top-left": lambda vw, vh: (0, 0),
    "within-margin-of-top-left": lambda vw, vh: (5, 5),
    "within-margin-of-bottom-right": lambda vw, vh: (vw - 100 - 10, vh - 100 - 10),
    "touching-bottom-right": lambda vw, vh: (vw - 100, vh - 100),
    "within-margin-of-top-right": lambda vw, vh: (vw - 100 - 3, 12),
}


@pytest.mark.parametrize("placement", sorted(BOUNDARY))
def test_a_region_fully_inside_the_viewport_but_within_24_px_of_its_edge_has_no_indicator(
    canvas: PageCanvas,
    placement: str,
) -> None:
    _off_screen_and_shown(canvas, SMALL)  # shown first, so hiding is observable
    vw, vh = canvas.viewport().width(), canvas.viewport().height()

    _place(canvas, SMALL, *BOUNDARY[placement](vw, vh))

    inset = _view_rect(canvas).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
    assert _fully_visible(canvas, SMALL), "fixture: not fully visible"
    assert not inset.contains(_region_rect(canvas, SMALL)), "fixture: not within the margin"
    assert not _shown(canvas), (
        f"{placement}: the region is fully visible (Q4) but the indicator is shown - "
        "is visibility tested against the 24 px selection margin?"
    )


# =============================================================================
# AC-4 - only ever the selected region's; at most one, whatever happens
# =============================================================================


def test_regions_other_than_the_selected_one_off_screen_get_no_indicator(
    canvas: PageCanvas,
) -> None:
    _select(canvas, OTHER.region_id)
    others_off = [r for r in REGIONS if r is not OTHER and not _fully_visible(canvas, r)]
    assert _fully_visible(canvas, OTHER) and len(others_off) >= 3, "fixture"

    assert not _shown(canvas)
    assert _indicators(canvas) == [canvas.offscreen_indicator]


def test_twenty_consecutive_selection_changes_never_make_a_second_indicator(
    canvas: PageCanvas,
) -> None:
    first = canvas.offscreen_indicator
    ids = [REGIONS[(i * 3) % len(REGIONS)].region_id for i in range(20)]
    problems: list[str] = []
    shown_states: set[bool] = set()

    for step, region_id in enumerate(ids):
        _select(canvas, region_id)
        found = _indicators(canvas)
        shown = _shown(canvas)
        shown_states.add(shown)
        if len(found) > 1:
            problems.append(f"step {step} (region {region_id}): {len(found)} indicators")
        if canvas.offscreen_indicator is not first:
            problems.append(f"step {step}: the indicator was replaced")
        if shown and canvas.offscreen_indicator.ordinal() != region_id + 1:
            problems.append(
                f"step {step}: indicator shows {canvas.offscreen_indicator.ordinal()}, "
                f"selected is {region_id + 1}"
            )

    assert shown_states == {True, False}, "fixture: the sequence must show AND hide it"
    assert problems == []


# =============================================================================
# AC-5 - pinned to the edge nearest the centre, and STILL pinned after more pans
# =============================================================================
# SMALL maps to a 100 x 100 QRect, so c = (left + 50, top + 50). Each case:
# (first placement, pan perpendicular to the edge, pan along the edge) and the
# expected indicator centre for each, by hand (B3, B4). The perpendicular pan
# must leave the indicator EXACTLY where it was: the scroll moves a child widget
# with the content, so only a re-pin after scrollContentsBy keeps it there.

Placement = Callable[[int, int], tuple[int, int]]
EDGE_CASES: dict[str, tuple[str, list[tuple[str, Placement, Placement]]]] = {
    # c = (250, -250): TOP -250 < LEFT 250.
    "TOP": (
        "TOP",
        [
            ("first", lambda vw, vh: (200, -300), lambda vw, vh: (250, H)),
            ("perpendicular", lambda vw, vh: (200, -350), lambda vw, vh: (250, H)),
            ("along", lambda vw, vh: (300, -300), lambda vw, vh: (350, H)),
        ],
    ),
    # c = (vw + 150, 200): RIGHT -150 < TOP 200.
    "RIGHT": (
        "RIGHT",
        [
            ("first", lambda vw, vh: (vw + 100, 150), lambda vw, vh: (vw - H, 200)),
            ("perpendicular", lambda vw, vh: (vw + 150, 150), lambda vw, vh: (vw - H, 200)),
            ("along", lambda vw, vh: (vw + 100, 250), lambda vw, vh: (vw - H, 300)),
        ],
    ),
    # c = (200, vh + 150): BOTTOM -150 < LEFT 200.
    "BOTTOM": (
        "BOTTOM",
        [
            ("first", lambda vw, vh: (150, vh + 100), lambda vw, vh: (200, vh - H)),
            ("perpendicular", lambda vw, vh: (150, vh + 150), lambda vw, vh: (200, vh - H)),
            ("along", lambda vw, vh: (250, vh + 100), lambda vw, vh: (300, vh - H)),
        ],
    ),
    # c = (-250, 150): LEFT -250 < TOP 150.
    "LEFT": (
        "LEFT",
        [
            ("first", lambda vw, vh: (-300, 100), lambda vw, vh: (H, 150)),
            ("perpendicular", lambda vw, vh: (-350, 100), lambda vw, vh: (H, 150)),
            ("along", lambda vw, vh: (-300, 200), lambda vw, vh: (H, 250)),
        ],
    ),
}


def _expected_geometry(centre: tuple[int, int]) -> QRect:
    return QRect(centre[0] - H, centre[1] - H, TARGET, TARGET)


@pytest.mark.parametrize("edge", sorted(EDGE_CASES))
def test_the_indicator_is_pinned_to_the_nearest_edge_and_stays_pinned_after_two_more_pans(
    canvas: PageCanvas,
    edge: str,
) -> None:
    expected_edge, steps = EDGE_CASES[edge]
    _select(canvas, SMALL.region_id, reveal=False)
    vw, vh = canvas.viewport().width(), canvas.viewport().height()
    indicator = canvas.offscreen_indicator
    problems: list[str] = []

    for label, placement, centre in steps:
        _place(canvas, SMALL, *placement(vw, vh))
        want = _expected_geometry(centre(vw, vh))
        got_edge = indicator.edge()
        if not indicator.isVisible():
            problems.append(f"{label}: indicator hidden")
        if got_edge is None or got_edge.name != expected_edge:
            problems.append(f"{label}: edge {got_edge}, expected {expected_edge}")
        if indicator.geometry() != want:
            problems.append(f"{label}: geometry {indicator.geometry()}, expected {want}")

    assert problems == [], f"{edge}: " + "; ".join(problems)


def test_the_indicator_is_pinned_after_a_zoom_as_well_as_a_pan(canvas: PageCanvas) -> None:
    # SMALL straddles the right edge at zoom 1; after set_zoom(2.0) it is placed
    # afresh by hand: 199 x 199 at zoom 2 maps to a 200 px inclusive rect.
    _select(canvas, SMALL.region_id, reveal=False)
    canvas.set_zoom(2.0)
    _settle()
    vw = canvas.viewport().width()
    _place(canvas, SMALL, vw + 40, 100)  # c = (vw + 140, 200): RIGHT -140 < TOP 200

    assert canvas.offscreen_indicator.edge() == _off().Edge.RIGHT
    assert canvas.offscreen_indicator.geometry() == _expected_geometry((vw - H, 200))


# =============================================================================
# AC-6 - the indicator on the canvas paints through paint_indicator
# =============================================================================


def test_the_indicator_on_the_canvas_paints_the_selected_ordinal_at_its_edge(
    canvas: PageCanvas,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    off = _off()
    seen: list[tuple[int, Any]] = []
    real = off.paint_indicator

    def recording(painter: Any, ordinal: int, edge: Any) -> None:
        seen.append((ordinal, edge))
        real(painter, ordinal, edge)

    monkeypatch.setattr(off, "paint_indicator", recording)
    _off_screen_and_shown(canvas, SMALL)  # beyond the left edge

    canvas.offscreen_indicator.grab()

    assert seen and set(seen) == {(SMALL.ordinal, off.Edge.LEFT)}, seen


# =============================================================================
# AC-7 - role Button, A-08's name, following the selection
# =============================================================================


def _name(ordinal: int) -> str:
    return f"Bubble {ordinal} is off screen. Activate to show it."


def test_the_shown_indicator_is_a_button_named_for_the_selected_ordinal_and_follows_it(
    canvas: PageCanvas,
) -> None:
    _select(canvas, WIDE.region_id)
    assert _shown(canvas), "fixture"
    iface = QAccessible.queryAccessibleInterface(canvas.offscreen_indicator)
    assert iface is not None, "the indicator is not in the accessibility tree"
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Text.Name) == _name(4)

    _select(canvas, TALL.region_id)
    assert _shown(canvas), "fixture"

    iface = QAccessible.queryAccessibleInterface(canvas.offscreen_indicator)
    assert iface.text(QAccessible.Text.Name) == _name(5)


# =============================================================================
# AC-8 - the click and Ctrl+9: centre, zoom out only if it must, never in (Q1)
# =============================================================================

CTRL = Qt.KeyboardModifier.ControlModifier
KEYPAD = Qt.KeyboardModifier.KeypadModifier


def _activate(view: PageCanvas, how: str) -> None:
    if how == "click":
        QTest.mouseClick(
            view.offscreen_indicator,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(H, H),
        )
    elif how == "ctrl+9":
        QTest.keyClick(view, Qt.Key.Key_9, CTRL)
    else:  # "ctrl+keypad-9"
        QTest.keyClick(view, Qt.Key.Key_9, CTRL | KEYPAD)
    _settle()


TRIGGERS = ["click", "ctrl+9", "ctrl+keypad-9"]


class Spy:
    """Every canvas signal bring_into_view must not emit."""

    def __init__(self, view: PageCanvas) -> None:
        self.clicked: list[int] = []
        self.hovered: list[object] = []
        self.steps: list[str] = []
        view.regionClicked.connect(self.clicked.append)
        view.regionHovered.connect(self.hovered.append)
        view.selectionStepRequested.connect(self.steps.append)


def _pan_away(view: PageCanvas, region: OrderedRegion) -> None:
    for value in (0, None):
        h, v = view.horizontalScrollBar(), view.verticalScrollBar()
        h.setValue(h.maximum() if value is None else value)
        v.setValue(v.maximum() if value is None else value)
        _settle()
        if not _fully_visible(view, region):
            break
    assert not _fully_visible(view, region), "fixture: could not pan the region away"
    assert _shown(view), "fixture: no indicator to activate"


def _centre_offset(view: PageCanvas, region: OrderedRegion) -> tuple[float, float]:
    got, want = _region_rect(view, region).center(), _view_rect(view).center()
    return (got.x() - want.x(), got.y() - want.y())


def _b8_target(view: PageCanvas, region: OrderedRegion, zoom: float) -> float:
    """B8 step 2, by hand: the largest zoom <= the current one at which the
    region's scene bounds fit the viewport inset by 24 px."""
    b = region.bounds()
    vw, vh = view.viewport().width(), view.viewport().height()
    terms = [zoom]
    if b.width() > 0:
        terms.append((vw - 2 * MARGIN) / b.width())
    if b.height() > 0:
        terms.append((vh - 2 * MARGIN) / b.height())
    return min(terms)


@pytest.mark.parametrize("how", TRIGGERS)
@pytest.mark.parametrize("zoom", [0.5, 1.0, 2.0])
def test_bringing_a_region_that_fits_into_view_centres_it_and_leaves_the_zoom_exactly_alone(
    canvas: PageCanvas,
    zoom: float,
    how: str,
) -> None:
    # Q1: never zoom in. A "helpful" fit-to-region would take this 99 px bubble
    # to several hundred percent; B8 must not call set_zoom at all.
    canvas.set_zoom(zoom)
    _select(canvas, SMALL.region_id)
    _pan_away(canvas, SMALL)
    before = canvas.transform()
    spy = Spy(canvas)

    _activate(canvas, how)

    after = canvas.transform()
    assert after.m11() == before.m11(), f"{how} changed the zoom: {before.m11()} -> {after.m11()}"
    assert after.m22() == before.m22(), f"{how} changed the zoom: {before.m22()} -> {after.m22()}"
    dx, dy = _centre_offset(canvas, SMALL)
    assert abs(dx) <= 1 and abs(dy) <= 1, f"{how} did not centre the region: offset {(dx, dy)}"
    assert not _shown(canvas), "the region is fully visible: the indicator must hide"
    assert spy.clicked == [] and spy.steps == [], "bring into view selected or stepped"
    assert [h for h in spy.hovered if h is not None] == [], "bring into view hovered a region"


@pytest.mark.parametrize("how", TRIGGERS)
@pytest.mark.parametrize(
    ("region", "zoom"),
    [(WIDE, 1.0), (WIDE, 2.0), (TALL, 1.0)],
    ids=["wide-at-1", "wide-at-2", "tall-at-1"],
)
def test_bringing_a_region_too_big_for_the_inset_zooms_out_to_exactly_the_b8_target(
    canvas: PageCanvas,
    region: OrderedRegion,
    zoom: float,
    how: str,
) -> None:
    canvas.set_zoom(zoom)
    _select(canvas, region.region_id)
    assert _shown(canvas), "fixture: the region fits"
    target = _b8_target(canvas, region, zoom)
    assert target < zoom, "fixture: B8 would not zoom"

    _activate(canvas, how)

    t = canvas.transform()
    assert t.m11() == pytest.approx(target), f"zoom {t.m11()}, B8 target {target}"
    assert t.m22() == pytest.approx(target), f"zoom {t.m22()}, B8 target {target}"
    dx, dy = _centre_offset(canvas, region)
    assert abs(dx) <= 1 and abs(dy) <= 1, f"not centred: offset {(dx, dy)}"
    assert _fully_visible(canvas, region)
    assert not _shown(canvas)


def test_a_region_that_does_not_fit_even_at_10_percent_zooms_to_10_percent_and_keeps_its_indicator(
    canvas: PageCanvas,
) -> None:
    canvas.parentWidget().resize(160, 160)
    canvas.set_regions([*REGIONS, HUGE])
    _select(canvas, HUGE.region_id)
    assert _shown(canvas), "fixture"
    assert _b8_target(canvas, HUGE, 1.0) < ZOOM_MIN, "fixture: HUGE would fit above 10%"

    _activate(canvas, "ctrl+9")

    assert canvas.transform().m11() == ZOOM_MIN
    assert canvas.transform().m22() == ZOOM_MIN
    dx, dy = _centre_offset(canvas, HUGE)
    assert abs(dx) <= 1 and abs(dy) <= 1, f"not centred: offset {(dx, dy)}"
    assert not _fully_visible(canvas, HUGE), "fixture: HUGE fits at 10%"
    assert _shown(canvas), "the region is still not fully visible: the indicator stays"
    assert canvas.offscreen_indicator.ordinal() == HUGE.ordinal


@pytest.mark.parametrize("modifier", [CTRL, CTRL | KEYPAD], ids=["main", "keypad"])
def test_ctrl_9_with_nothing_selected_changes_nothing_and_goes_no_further_than_the_canvas(
    canvas: PageCanvas,
    modifier: Qt.KeyboardModifier,
) -> None:
    _select(canvas, None)
    before = _canvas_view(canvas)
    spy = Spy(canvas)
    parent = canvas.parentWidget()
    assert isinstance(parent, KeyRecorder)

    QTest.keyClick(canvas, Qt.Key.Key_9, modifier)
    _settle()

    assert _canvas_view(canvas) == before
    assert (spy.clicked, spy.hovered, spy.steps) == ([], [], [])
    # Before any indicator attribute is touched, so this runs - and is red - in RED.
    assert [k for k, _ in parent.keys if k == Qt.Key.Key_9] == [], "Ctrl+9 left the canvas"
    assert not _shown(canvas)


def test_ctrl_9_with_a_selection_is_consumed_by_the_canvas(canvas: PageCanvas) -> None:
    _off_screen_and_shown(canvas, SMALL)
    parent = canvas.parentWidget()
    assert isinstance(parent, KeyRecorder)

    _activate(canvas, "ctrl+9")

    assert [k for k, _ in parent.keys if k == Qt.Key.Key_9] == [], "Ctrl+9 left the canvas"


@pytest.mark.parametrize(
    "modifier",
    [Qt.KeyboardModifier.NoModifier, CTRL | Qt.KeyboardModifier.ShiftModifier],
    ids=["9", "Ctrl+Shift+9"],
)
def test_9_without_exactly_ctrl_does_not_bring_the_region_into_view(
    canvas: PageCanvas,
    modifier: Qt.KeyboardModifier,
) -> None:
    _off_screen_and_shown(canvas, SMALL)
    before = _canvas_view(canvas)

    QTest.keyClick(canvas, Qt.Key.Key_9, modifier)
    _settle()

    assert _canvas_view(canvas) == before
    assert _shown(canvas)


def test_bring_into_view_of_an_unknown_region_changes_nothing(canvas: PageCanvas) -> None:
    _off_screen_and_shown(canvas, SMALL)
    before = _canvas_view(canvas)
    spy = Spy(canvas)

    canvas.bring_into_view(99)
    _settle()

    assert _canvas_view(canvas) == before
    assert (spy.clicked, spy.hovered, spy.steps) == ([], [], [])
    assert _shown(canvas)


def test_activating_the_indicator_hides_it_once_the_region_is_fully_visible(
    canvas: PageCanvas,
) -> None:
    # AC-3's "the indicator's own activation", on its own.
    _off_screen_and_shown(canvas, SMALL)

    _activate(canvas, "click")

    assert _fully_visible(canvas, SMALL)
    assert not _shown(canvas)


# =============================================================================
# AC-9 - the indicator over the art: clicks and moves stop at it
# =============================================================================


def _indicator_over_under(view: PageCanvas) -> QPoint:
    """SMALL selected beyond the top edge; UNDER lies beneath the indicator.
    Returns a viewport point on UNDER that is NOT under the indicator."""
    _select(view, SMALL.region_id, reveal=False)
    _place(view, SMALL, 200, -300)  # c = (250, -250): TOP, indicator centre (250, 14)
    indicator = view.offscreen_indicator
    assert _shown(view), "fixture"
    under = view.mapFromScene(UNDER.bounds()).boundingRect()
    assert under.contains(indicator.geometry()), f"fixture: {under} vs {indicator.geometry()}"
    point = QPoint(250, 120)
    assert under.contains(point) and not indicator.geometry().contains(point), "fixture"
    return point


def test_a_click_on_the_indicator_over_a_region_selects_and_cycles_nothing(
    canvas: PageCanvas,
) -> None:
    _indicator_over_under(canvas)
    spy = Spy(canvas)

    QTest.mouseClick(
        canvas.offscreen_indicator,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(H, H),
    )
    _settle()

    assert spy.clicked == [], f"the click fell through to the canvas: regionClicked {spy.clicked}"


def test_moving_from_a_hovered_region_onto_the_indicator_clears_hover_and_never_hovers_under_it(
    canvas: PageCanvas,
) -> None:
    point = _indicator_over_under(canvas)
    spy = Spy(canvas)
    QTest.mouseMove(canvas.viewport(), point - QPoint(1, 1))
    QTest.mouseMove(canvas.viewport(), point)
    _settle()
    assert spy.hovered and spy.hovered[-1] == UNDER.region_id, f"fixture: {spy.hovered}"
    spy.hovered.clear()

    indicator = canvas.offscreen_indicator
    for at in (QPoint(H - 1, H - 1), QPoint(H, H), QPoint(6, 6), QPoint(22, 22)):
        QTest.mouseMove(indicator, at)
        _settle()

    assert spy.hovered, "moving onto the indicator did not clear canvas hover"
    assert spy.hovered[-1] is None, f"hover not cleared: last regionHovered {spy.hovered[-1]}"
    assert [h for h in spy.hovered if h is not None] == [], (
        f"a move over the indicator hovered the region beneath it: {spy.hovered}"
    )


# =============================================================================
# Through the real Workspace (AC-1, AC-3, AC-7, AC-8): no new wiring
# =============================================================================

WS_PAGE = QSize(3000, 4000)
WINDOW = QSize(1100, 720)
PAGES = ("001.png", "002.png", "003.png")
SHOWN_PAGE = 1
# Region 0 (selected first by set_regions) is wider than any canvas viewport at
# the workspace minimum; region 1 is small and fits.
WS_REGIONS = [
    OrderedRegion(region_id=0, polygon=_ring(300, 1950, 2400, 100)),
    OrderedRegion(region_id=1, polygon=_ring(400, 400, 120, 90)),
]


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
    return _png_bytes(WS_PAGE)


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
                width=WS_PAGE.width(),
                height=WS_PAGE.height(),
                sha256=f"{i}" * 64,
            )
            for i, name in enumerate(PAGES)
        ),
    )
    with create_project(chapter, tmp_path / "chapter.mtproj") as opened:
        yield opened


def _workspace(qtbot, project: Project, regions: Sequence[OrderedRegion]) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.resize(WINDOW)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(SHOWN_PAGE)
    _settle()
    window.set_regions(
        regions,
        [f"ja {r.region_id}" for r in regions],
        [f"en {r.region_id}" for r in regions],
    )
    _settle()
    return window


def test_in_the_workspace_selecting_a_region_too_wide_for_the_canvas_shows_its_indicator(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _workspace(qtbot, project, WS_REGIONS)  # set_regions selects region 0
    canvas = window.page_canvas
    assert window.link.state.selected_region_id == 0, "fixture"
    assert not _fully_visible(canvas, WS_REGIONS[0]), "fixture: region 0 fits"

    assert _shown(canvas)
    assert _indicators(canvas) == [canvas.offscreen_indicator]
    assert canvas.offscreen_indicator.ordinal() == 1
    iface = QAccessible.queryAccessibleInterface(canvas.offscreen_indicator)
    assert iface.text(QAccessible.Text.Name) == _name(1)

    window.translation_column.list.setCurrentRow(1)
    _settle()

    assert window.link.state.selected_region_id == 1, "fixture"
    assert _fully_visible(canvas, WS_REGIONS[1]), "fixture: the pan did not bring it in"
    assert not _shown(canvas)


@pytest.mark.parametrize("how", ["click", "ctrl+9"])
def test_in_the_workspace_bringing_the_region_into_view_changes_no_selection(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    how: str,
) -> None:
    window = _workspace(qtbot, project, WS_REGIONS)
    canvas = window.page_canvas
    assert _shown(canvas), "fixture"
    target = _b8_target(canvas, WS_REGIONS[0], canvas.transform().m11())
    canvas.setFocus(Qt.FocusReason.OtherFocusReason)
    _settle()
    assert QApplication.focusWidget() is canvas, "fixture: canvas does not have focus"

    if how == "click":
        _activate(canvas, "click")
    else:
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_9, CTRL)
        _settle()

    assert window.link.state.selected_region_id == 0, "bringing into view changed the selection"
    assert window.translation_column.list.currentRow() == 0
    assert canvas.transform().m11() == pytest.approx(target)
    assert canvas.transform().m22() == pytest.approx(target)
    assert _fully_visible(canvas, WS_REGIONS[0])
    assert not _shown(canvas)
