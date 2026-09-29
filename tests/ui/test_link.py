"""MT-016: the pure half of the bubble <-> line link.

`mangatl.ui.link` holds the rules the canvas and the column both render from
(components.md §4.1): the ordered region, the pan rule (§4.5), the hit test
(§4.8), the one controller that owns selection and hover, and the live region
(§4.9). Everything here is a unit test of a pure function or of one QObject, so
the exact deltas below are computed BY HAND from the Contract's definition of
`pan_to_contain` and never read back from an implementation.

Settled numbers, read out rather than tuned:

    SELECTION_MARGIN_PX  24   components.md §4.5 `space.6`
    SAME_POINT_PX         3   components.md §4.8 "within 3px of the first click"
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QAccessible

from mangatl.ui import link as link_module
from mangatl.ui import tokens_gen
from mangatl.ui.link import (
    SAME_POINT_PX,
    SELECTION_MARGIN_PX,
    LinkController,
    LinkState,
    LiveRegion,
    OrderedRegion,
    hit_test,
    pan_to_contain,
)

DESIGN_MARGIN = 24  # components.md §4.5: `space.6`
DESIGN_SAME_POINT = 3  # components.md §4.8

# A view rect at the origin, the shape a viewport has. Inset by 24 it is
# [24, 976] x [24, 776]: 952 x 752 of room.
VIEW = QRectF(0, 0, 1000, 800)
M = DESIGN_MARGIN


def _rect_region(region_id: int, x: int, y: int, w: int, h: int) -> OrderedRegion:
    """An axis-aligned region as the store delivers it: a closed ring."""
    ring = ((x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y))
    return OrderedRegion(region_id=region_id, polygon=ring)


def _point(d: QPointF | None) -> tuple[float, float] | None:
    return None if d is None else (d.x(), d.y())


# =============================================================================
# Settled constants
# =============================================================================


def test_the_selection_margin_is_space_6_which_is_24_px() -> None:
    assert SELECTION_MARGIN_PX == DESIGN_MARGIN
    assert tokens_gen.SPACE_S6 == DESIGN_MARGIN


def test_a_click_counts_as_the_same_point_within_3_px() -> None:
    assert SAME_POINT_PX == DESIGN_SAME_POINT


# =============================================================================
# OrderedRegion
# =============================================================================


def test_a_regions_badge_ordinal_is_its_zero_based_reading_index_plus_one() -> None:
    assert _rect_region(0, 0, 0, 10, 10).ordinal == 1
    assert _rect_region(11, 0, 0, 10, 10).ordinal == 12


def test_a_regions_bounds_are_the_bounding_rect_of_its_polygon_vertices() -> None:
    triangle = OrderedRegion(region_id=0, polygon=((100, 50), (300, 80), (160, 250), (100, 50)))
    assert triangle.bounds() == QRectF(100, 50, 200, 200)


def test_a_regions_area_is_the_shoelace_area_of_its_polygon_not_of_its_bounds() -> None:
    # Right triangle with legs 100 and 60: area 3000, bounding box 6000.
    triangle = OrderedRegion(region_id=0, polygon=((0, 0), (100, 0), (0, 60), (0, 0)))
    assert triangle.area() == pytest.approx(3000.0)
    # The same triangle wound the other way has the same, positive, area.
    reversed_triangle = OrderedRegion(region_id=0, polygon=((0, 0), (0, 60), (100, 0), (0, 0)))
    assert reversed_triangle.area() == pytest.approx(3000.0)


def test_an_l_shaped_regions_area_excludes_the_notch() -> None:
    # 100x100 square minus a 50x50 notch at its top-right: 7500.
    ell = OrderedRegion(
        region_id=0,
        polygon=((0, 0), (50, 0), (50, 50), (100, 50), (100, 100), (0, 100), (0, 0)),
    )
    assert ell.area() == pytest.approx(7500.0)


def test_ordered_region_is_a_frozen_value() -> None:
    region = _rect_region(0, 0, 0, 10, 10)
    with pytest.raises(AttributeError):
        region.region_id = 3  # type: ignore[misc]
    assert region == _rect_region(0, 0, 0, 10, 10)


# =============================================================================
# pan_to_contain - None means "no pan"; otherwise the exact minimal delta
# =============================================================================


@pytest.mark.parametrize(
    "region",
    [
        pytest.param(QRectF(200, 200, 100, 100), id="well-inside"),
        pytest.param(QRectF(5, 300, 100, 100), id="inside-but-within-margin-of-left-edge"),
        pytest.param(QRectF(300, 790, 100, 10), id="touching-bottom-edge"),
        pytest.param(QRectF(0, 0, 1000, 800), id="exactly-the-view"),
    ],
)
def test_a_region_entirely_inside_the_view_needs_no_pan_even_without_margin(
    region: QRectF,
) -> None:
    assert pan_to_contain(VIEW, region, M) is None


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        # left edge 1 px outside: left -> 24 (d.x = 25); y already in the inset.
        pytest.param(QRectF(-1, 100, 100, 100), (25.0, 0.0), id="one-px-past-left"),
        # right 1050 -> 976.
        pytest.param(QRectF(950, 100, 100, 100), (-74.0, 0.0), id="past-right"),
        # bottom 850 -> 776.
        pytest.param(QRectF(100, 750, 100, 100), (0.0, -74.0), id="past-bottom"),
        # top -30 -> 24.
        pytest.param(QRectF(100, -30, 100, 100), (0.0, 54.0), id="past-top"),
        # both axes out.
        pytest.param(QRectF(-50, -50, 100, 100), (74.0, 74.0), id="past-top-left"),
        # x out; y INSIDE the view but not the inset (top 5): once a pan
        # happens the margin applies on both axes, so y moves 19.
        pytest.param(QRectF(-10, 5, 100, 100), (34.0, 19.0), id="x-out-y-within-margin"),
        # exactly the inset's width (952): fits, so minimal, not centred.
        pytest.param(QRectF(-10, 100, 952, 100), (34.0, 0.0), id="exactly-fits-inset"),
    ],
)
def test_a_region_outside_the_view_pans_by_the_minimal_delta_into_the_24_px_inset(
    region: QRectF, expected: tuple[float, float]
) -> None:
    assert _point(pan_to_contain(VIEW, region, M)) == expected


def test_a_region_too_wide_for_the_inset_is_centred_on_that_axis_only() -> None:
    # 953 wide > 952 of room: centre x (region centre 20.5 -> view centre 500).
    # y 100..200 is inside the inset, so 0 on y.
    d = pan_to_contain(VIEW, QRectF(-456, 100, 953, 100), M)
    assert _point(d) == (479.5, 0.0)


def test_a_region_wider_than_the_view_itself_is_centred() -> None:
    # centre x = -500 + 1400/2 = 200; view centre 500 -> d.x = 300.
    # bottom 850 > 776 and it fits on y: minimal, -74.
    d = pan_to_contain(VIEW, QRectF(-500, 750, 1400, 100), M)
    assert _point(d) == (300.0, -74.0)


def test_a_region_covering_the_whole_view_and_already_centred_returns_a_zero_pan_not_none() -> None:
    # Not entirely inside, so the answer is a pan - which happens to be zero.
    # None is reserved for "entirely inside" (Contract).
    d = pan_to_contain(VIEW, QRectF(-100, -100, 1200, 1000), M)
    assert d is not None
    assert _point(d) == (0.0, 0.0)


def test_pan_to_contain_works_in_the_view_rects_own_coordinates_not_from_the_origin() -> None:
    view = QRectF(100, 200, 500, 400)  # inset [124, 576] x [224, 576]
    assert pan_to_contain(view, QRectF(150, 250, 50, 50), M) is None
    # left 90 -> 124, top 250 already in the inset.
    assert _point(pan_to_contain(view, QRectF(90, 250, 50, 50), M)) == (34.0, 0.0)
    # bottom 620 -> 576.
    assert _point(pan_to_contain(view, QRectF(300, 570, 50, 50), M)) == (0.0, -44.0)


def test_the_margin_argument_is_honoured_not_hard_coded() -> None:
    # Same geometry as "one-px-past-left" with margin 0 and 10.
    assert _point(pan_to_contain(VIEW, QRectF(-1, 100, 100, 100), 0)) == (1.0, 0.0)
    assert _point(pan_to_contain(VIEW, QRectF(-1, 100, 100, 100), 10)) == (11.0, 0.0)


# =============================================================================
# hit_test - polygon containment, smallest area wins, same point cycles
# =============================================================================

BIG = _rect_region(0, 0, 0, 400, 400)  # area 160000
MID = _rect_region(1, 50, 50, 200, 200)  # area 40000
SMALL = _rect_region(2, 100, 100, 50, 50)  # area 2500
INSIDE_ALL = QPointF(120, 120)


def test_a_click_on_no_region_hits_nothing() -> None:
    assert hit_test([BIG, MID, SMALL], QPointF(900, 900), None) is None
    assert hit_test([], QPointF(0, 0), None) is None


def test_a_click_inside_one_region_hits_it() -> None:
    assert hit_test([BIG, MID, SMALL], QPointF(350, 350), None) == 0


def test_the_smallest_area_region_containing_the_point_wins() -> None:
    assert hit_test([BIG, MID, SMALL], INSIDE_ALL, None) == 2
    # List order is not the rule: the same regions in any order give the same.
    assert hit_test([SMALL, BIG, MID], INSIDE_ALL, None) == 2


def test_equal_areas_tie_break_to_the_lowest_region_id_not_the_first_listed() -> None:
    a = _rect_region(3, 0, 0, 100, 100)
    b = _rect_region(7, 0, 0, 100, 100)
    assert hit_test([b, a], QPointF(50, 50), None) == 3
    assert hit_test([a, b], QPointF(50, 50), None) == 3


def test_a_previous_that_is_not_a_candidate_is_ignored_and_smallest_wins() -> None:
    far = _rect_region(9, 1000, 1000, 10, 10)
    assert hit_test([BIG, MID, SMALL, far], INSIDE_ALL, 9) == 2


def test_repeated_clicks_cycle_every_candidate_in_ascending_id_and_wrap() -> None:
    regions = [SMALL, BIG, MID]  # deliberately not in id order
    first = hit_test(regions, INSIDE_ALL, None)
    assert first == 2
    visited = [first]
    for _ in range(3):
        visited.append(hit_test(regions, INSIDE_ALL, visited[-1]))
    # after 2 -> wraps to 0 -> 1 -> 2
    assert visited == [2, 0, 1, 2]


def test_containment_is_by_polygon_not_by_bounding_box() -> None:
    # Right triangle (0,0) (200,0) (0,200): (150,150) is inside its bbox and
    # outside the triangle.
    triangle = OrderedRegion(region_id=0, polygon=((0, 0), (200, 0), (0, 200), (0, 0)))
    assert hit_test([triangle], QPointF(150, 150), None) is None
    assert hit_test([triangle], QPointF(40, 40), None) == 0


def test_a_point_in_an_l_shapes_notch_hits_the_region_behind_it_not_the_l() -> None:
    # (75, 25) is in the L's bounding box but in its notch. The L's area (7500)
    # is smaller than `behind`'s (90000), so a bbox hit test would pick the L.
    ell = OrderedRegion(
        region_id=0,
        polygon=((0, 0), (50, 0), (50, 50), (100, 50), (100, 100), (0, 100), (0, 0)),
    )
    behind = _rect_region(1, 60, 0, 300, 300)
    assert hit_test([ell, behind], QPointF(75, 25), None) == 1


# =============================================================================
# LinkController - the one owner of LinkState
# =============================================================================


def test_link_state_starts_with_nothing_selected_or_hovered() -> None:
    state = LinkState()
    assert state.selected_region_id is None
    assert state.hovered_region_id is None


def test_select_changes_the_selection_and_emits_it_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = LinkController()
    seen: list[Any] = []
    controller.selectionChanged.connect(seen.append)

    controller.select(3)
    controller.select(3)  # no change -> no emission
    controller.select(None)

    assert seen == [3, None]
    assert controller.state.selected_region_id is None


def test_hover_changes_only_hover_and_emits_only_on_change(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = LinkController()
    controller.select(1)
    selections: list[Any] = []
    hovers: list[Any] = []
    controller.selectionChanged.connect(selections.append)
    controller.hoverChanged.connect(hovers.append)

    controller.hover(4)
    controller.hover(4)
    controller.hover(1)  # hovering the selected region
    controller.hover(None)

    assert hovers == [4, 1, None]
    assert selections == []
    assert controller.state.selected_region_id == 1
    assert controller.state.hovered_region_id is None


def test_selecting_never_touches_hover(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = LinkController()
    controller.hover(2)
    controller.select(5)
    assert controller.state.hovered_region_id == 2
    assert controller.state.selected_region_id == 5


# =============================================================================
# LiveRegion - the Alert that stands in for ARIA-live (components.md §4.9)
# =============================================================================


@pytest.fixture
def recorded_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """Replace `mangatl.ui.link.QAccessible` (Contract: imported BY NAME) with a
    stand-in that records (event type, event object) for every update posted.

    The real `QAccessible.Event` enum is kept, so `QAccessible.Event.Alert`
    inside `link.py` still resolves to the genuine value.
    """
    posted: list[tuple[Any, Any]] = []
    stand_in = SimpleNamespace(
        Event=QAccessible.Event,
        updateAccessibility=lambda event: posted.append((event.type(), event.object())),
    )
    monkeypatch.setattr(link_module, "QAccessible", stand_in)
    return posted


def test_announcing_rewrites_the_live_regions_name_and_text_and_posts_an_alert(
    qtbot,  # type: ignore[no-untyped-def]
    recorded_alerts: list[tuple[Any, Any]],
) -> None:
    live = LiveRegion()
    qtbot.addWidget(live)

    live.announce("Bubble 4 of 12 selected. Page 3 of 20.")

    assert live.accessibleName() == "Bubble 4 of 12 selected. Page 3 of 20."
    assert live.text() == "Bubble 4 of 12 selected. Page 3 of 20."
    assert recorded_alerts == [(QAccessible.Event.Alert, live)]
