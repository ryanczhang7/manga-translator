"""MT-051 AC-1..AC-6: where ordinal badges are placed so they never overlap.

`components.md` §4.2 is normative; the story's `## Contract` reads every number
out of it and out of the user's Q2/Q3 answers (2026-09-29):

- size 18 and gap 4 (`overlay.badge.size`, `overlay.badge.gap`, from tokens_gen);
- nominal centre = bounding-rect top-right (R, T) + (gap + size/2, -(gap + size/2))
  = (R + 13, T - 13) - MT-016's circle;
- "intersects" = centre distance STRICTLY less than size; touching is free;
- the walk starts at the outline point nearest (R, T), advances 9 px of outline
  length per step, clockwise AS SEEN ON SCREEN (y down), and each candidate
  centre sits 13 px outward along the normal of the edge that point lies on; at a
  vertex exactly, the edge being ENTERED;
- a full circuit with nothing free -> the AREA centroid (shoelace);
- all of it in zoomed-scene units: page px x zoom.

The oracle partition is honoured as follows. AC-1, AC-3, AC-4 and AC-5 are
SETTLED: every expected coordinate below is a literal worked out by hand in the
comment beside it, never obtained from a helper that walks the outline. AC-2 and
AC-6 are MECHANICAL: properties over generated pages (hypothesis), whose domain is
the story's, simple polygons with >= 3 distinct vertices and non-zero area.

`mangatl.ui.badges` is imported inside each test, never at module level, so the
controls at the top of this file - which check that the disjointness checker
rejects MT-016's all-nominal placement - run while the module does not exist.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import random
from collections.abc import Sequence
from types import ModuleType
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from mangatl.ui import tokens_gen

Point = tuple[float, float]
Polygon = Sequence[Point]

SIZE = tokens_gen.OVERLAY_BADGE_SIZE  # 18
GAP = tokens_gen.OVERLAY_BADGE_GAP  # 4
#: Contract rule 6: expected coordinates are compared with approx(abs=1e-6).
ABS = 1e-6


def _badges() -> ModuleType:
    return importlib.import_module("mangatl.ui.badges")


def _place(regions: Sequence[tuple[int, Polygon]], zoom: float = 1.0) -> dict[int, Any]:
    result: dict[int, Any] = _badges().place_badges(regions, zoom=zoom, size=SIZE, gap=GAP)
    return result


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    """Screen-clockwise: top edge rightwards, right edge down, bottom left, left up."""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _assert_at(result: dict[int, Any], region_id: int, centre: Point, placement: str) -> None:
    badge = result[region_id]
    assert badge.placement.name == placement, (
        f"region {region_id}: placed {badge.placement.name} at {badge.centre},"
        f" expected {placement} at {centre}"
    )
    assert badge.centre == pytest.approx(centre, abs=ABS), (
        f"region {region_id} ({placement}): badge centre {badge.centre}, expected {centre}"
    )


def test_the_tokens_this_file_computes_by_hand_are_size_18_and_gap_4() -> None:
    # Every literal below is worked out with these two numbers. If a token moves,
    # the literals are stale rather than wrong, and this says which.
    assert (SIZE, GAP) == (18, 4)


# =============================================================================
# The disjointness checker (AC-2) and its control - run in RED
# =============================================================================


def _overlaps(
    centres: Sequence[tuple[int, Point, bool]], size: float = SIZE
) -> list[tuple[int, int, float]]:
    """(later id, earlier id, distance) for every badge that intersects an earlier one.

    `centres` is (region_id, centre, exempt) in placement order; an exempt badge
    (the centroid fallback) is not itself checked, but still counts as placed.
    The ABS slack is Contract rule 6's comparison tolerance, nothing wider: a
    touching pair computed as 17.9999999999 is touching.
    """
    found: list[tuple[int, int, float]] = []
    for index, (region_id, centre, exempt) in enumerate(centres):
        if exempt:
            continue
        for earlier_id, earlier, _ in centres[:index]:
            distance = math.dist(centre, earlier)
            if distance < size - ABS:
                found.append((region_id, earlier_id, distance))
    return found


def _mt016_nominal(polygon: Polygon, zoom: float = 1.0) -> Point:
    """MT-016's badge centre: the circle QRectF(gap, -gap - size, size, size) about
    the bounding-rect top-right corner, i.e. (R + gap + size/2, T - gap - size/2)."""
    right = max(x for x, _ in polygon) * zoom
    top = min(y for _, y in polygon) * zoom
    return (right + GAP + SIZE / 2, top - GAP - SIZE / 2)


# Two regions whose bounding-rect top-right corners coincide at (130, 100).
CORNER_FIXTURE: list[tuple[int, Polygon]] = [
    (0, _rect(80, 100, 130, 140)),
    (1, _rect(100, 100, 130, 109)),
]


def test_control_mt016_all_nominal_placement_fails_ac2_when_two_top_right_corners_coincide() -> (
    None
):
    # AC-2's control. MT-016 draws both badges at (130 + 13, 100 - 13) = (143, 87):
    # centre distance 0 < 18.
    centres = [(rid, _mt016_nominal(poly), False) for rid, poly in CORNER_FIXTURE]
    assert centres[0][1] == centres[1][1] == (143.0, 87.0)
    assert _overlaps(centres) == [(1, 0, 0.0)]


def test_control_the_checker_treats_touching_badges_as_disjoint_and_17_apart_as_overlapping() -> (
    None
):
    touching = [(0, (0.0, 0.0), False), (1, (18.0, 0.0), False)]
    overlapping = [(0, (0.0, 0.0), False), (1, (17.0, 0.0), False)]
    assert _overlaps(touching) == []
    assert _overlaps(overlapping) == [(1, 0, 17.0)]


def test_control_the_checker_exempts_a_centroid_badge_but_still_counts_it_as_placed() -> None:
    centres = [(0, (0.0, 0.0), False), (1, (5.0, 0.0), True), (2, (20.0, 0.0), False)]
    # 1 overlaps 0 but is exempt; 2 is 15 from 1, which still counts.
    assert _overlaps(centres) == [(2, 1, 15.0)]


# =============================================================================
# Module shape
# =============================================================================


def test_place_badges_on_an_empty_page_places_nothing() -> None:
    assert _place([]) == {}


def test_placement_has_exactly_nominal_slid_and_centroid() -> None:
    placement = _badges().Placement
    assert [(m.name, m.value) for m in placement] == [
        ("NOMINAL", "nominal"),
        ("SLID", "slid"),
        ("CENTROID", "centroid"),
    ]


def test_badges_module_imports_nothing_from_qt_or_the_rest_of_the_ui() -> None:
    # Contract: "Qt-free: imports nothing from PySide6 or mangatl.ui.*".
    source = importlib.util.find_spec("mangatl.ui.badges")
    assert source is not None and source.origin is not None
    with open(source.origin, encoding="utf-8") as handle:
        text = handle.read()
    offenders = [
        line.strip()
        for line in text.splitlines()
        if line.lstrip().startswith(("import ", "from "))
        and ("PySide6" in line or "mangatl.ui" in line or "from mangatl import ui" in line)
    ]
    assert offenders == []


# =============================================================================
# AC-1 - nothing moves when nothing collides
# =============================================================================


def test_a_lone_region_gets_its_badge_at_the_nominal_position_off_the_top_right_corner() -> None:
    # R = 50, T = 20 -> (50 + 13, 20 - 13) = (63, 7).
    result = _place([(4, _rect(10, 20, 50, 60))])
    assert list(result) == [4]
    _assert_at(result, 4, (63.0, 7.0), "NOMINAL")


def test_badges_that_do_not_collide_all_stay_nominal_in_zoomed_scene_units() -> None:
    # Zoom 2, so every coordinate is page px x 2 before the +13 / -13.
    #   0: rect R 140, T 100 -> (280 + 13, 200 - 13) = (293, 187)
    #   1: the irregular pentagon below; its top-right corner (48, 0) is NOT a
    #      vertex, which does not matter for the nominal: (96 + 13, 0 - 13) = (109, -13)
    #   2: rect R 300, T 10 -> (600 + 13, 20 - 13) = (613, 7)
    # Pairwise distances: 0-1 = hypot(184, 200) = 271.8, 0-2 = hypot(320, 180) = 367.2,
    # 1-2 = hypot(504, 20) = 504.4 - all >= 18, so nothing may move.
    result = _place(
        [(0, _rect(100, 100, 140, 130)), (1, IRREGULAR), (2, _rect(250, 10, 300, 40))],
        zoom=2.0,
    )
    _assert_at(result, 0, (293.0, 187.0), "NOMINAL")
    _assert_at(result, 1, (109.0, -13.0), "NOMINAL")
    _assert_at(result, 2, (613.0, 7.0), "NOMINAL")


def test_a_badge_exactly_touching_an_earlier_one_is_not_moved() -> None:
    # Contract rule 3: intersects <=> distance < size; touching (= 18) is free.
    #   0: R 112, T 100 -> (125, 87)
    #   1: R 130, T 100 -> (143, 87); distance to 0 = 18 exactly.
    result = _place([(0, _rect(90, 100, 112, 130)), (1, _rect(100, 100, 130, 130))])
    _assert_at(result, 0, (125.0, 87.0), "NOMINAL")
    _assert_at(result, 1, (143.0, 87.0), "NOMINAL")


def test_a_badge_17_px_from_an_earlier_one_is_moved_off_its_nominal() -> None:
    #   0: R 113, T 100 -> (126, 87); 1: R 130, T 100 -> (143, 87); distance 17 < 18.
    result = _place([(0, _rect(90, 100, 113, 130)), (1, _rect(100, 100, 130, 130))])
    _assert_at(result, 0, (126.0, 87.0), "NOMINAL")
    assert result[1].placement.name != "NOMINAL"


# =============================================================================
# AC-3 - the first free candidate clockwise, 9 px steps, 13 px outward
# =============================================================================

# --- Rectangle -----------------------------------------------------------------
#
# Region 2 is the rectangle x 100..130, y 100..110 (R 130, T 100). Regions 0 and 1
# are small rects placed only so that their nominal badges sit where the walk
# needs a blocker:
#   0: R 130, T 113 -> badge (143, 100)
#   1: R 119, T 136 -> badge (132, 123)   (0-1 distance hypot(11, 23) = 25.5: both nominal)
#
# Region 2, by hand. Nominal (143, 87): distance to (143, 100) is 13 < 18, taken.
# Start S = the vertex (130, 100) itself (distance 0 from the corner, so no tie).
# Clockwise on screen from S: right edge down (len 10, normal +x), bottom edge
# left (len 30, normal +y), left edge up (len 10, normal -x), top edge right
# (len 30, normal -y). Perimeter 80, so k = 1..8.
#   k=1  arc  9: right edge (130, 109)          -> +13x -> (143, 109)
#        to (143, 100): 9 < 18                  taken
#   k=2  arc 18: 8 along bottom, (122, 110)     -> +13y -> (122, 123)
#        to (132, 123): 10 < 18                 taken
#   k=3  arc 27: 17 along bottom, (113, 110)    -> +13y -> (113, 123)
#        to (132, 123): 19; to (143, 100): hypot(30, 23) = 37.8   FREE
# Expected: (113, 123), SLID - three steps along, across the bottom-right vertex.
#
# The controls (scratch computation, recorded in the handoff):
#   steps of 18 instead of 9: arc 18 (122, 123) taken, arc 36 (104, 123) free
#                             -> (104, 123)
#   counter-clockwise, normals still outward: arc 9 on the top edge leftwards
#                             (121, 100) -> (121, 87), free -> (121, 87)
#   counter-clockwise by flipping the winding test (normals then point inward):
#                             -> (112, 113)
RECT_FIXTURE: list[tuple[int, Polygon]] = [
    (0, _rect(120, 113, 130, 140)),
    (1, _rect(60, 136, 119, 160)),
    (2, _rect(100, 100, 130, 110)),
]
RECT_EXPECTED: dict[int, tuple[Point, str]] = {
    0: ((143.0, 100.0), "NOMINAL"),
    1: ((132.0, 123.0), "NOMINAL"),
    2: ((113.0, 123.0), "SLID"),
}


def _assert_expected(result: dict[int, Any], expected: dict[int, tuple[Point, str]]) -> None:
    assert sorted(result) == sorted(expected)
    for region_id, (centre, placement) in expected.items():
        _assert_at(result, region_id, centre, placement)


def test_a_colliding_rectangle_badge_takes_the_first_free_9px_step_clockwise_past_the_corner() -> (
    None
):
    _assert_expected(_place(RECT_FIXTURE), RECT_EXPECTED)


# --- Irregular pentagon ----------------------------------------------------------
#
# Screen-clockwise, as stored:
#   V0 (0, 0) -> V1 (24, 0) -> V2 (48, 32) -> V3 (48, 60) -> V4 (0, 60)
# Shoelace sum 0 + 768 + 1344 + 2880 + 0 = 4992 > 0: screen-clockwise.
# Edges: e0 V0-V1 len 24, normal (0, -1)
#        e1 V1-V2 d = (24, 32), len 40, unit (0.6, 0.8), normal (dy, -dx) = (0.8, -0.6)
#        e2 V2-V3 len 28, normal (1, 0)
#        e3 V3-V4 len 48, normal (0, 1)
#        e4 V4-V0 len 60, normal (-1, 0)
# Perimeter 200, so k = 1..22.
#
# Bounding rect R 48, T 0; the corner (48, 0) is not on the outline.
# Nearest outline point: on e1, t = (24, 0) . (0.6, 0.8) = 14.4 from V1,
#   S = (24 + 8.64, 11.52) = (32.64, 11.52), distance |24 * 0.8| = 19.2.
#   (e0's nearest is V1 at 24; e2's is V2 at 32: S is unique.)
# Region 0 is a blocker: R 44, T 16 -> badge (57, 3).
#
# Region 1, by hand. Nominal (48 + 13, 0 - 13) = (61, -13): to (57, 3) is
# hypot(4, 16) = 16.49 < 18, taken. 25.6 of e1 remains after S.
#   k=1 arc  9: e1 at 23.4 from V1 = (38.04, 18.72)
#               + 13 * (0.8, -0.6) = (48.44, 10.92); to (57, 3): 11.66   taken
#   k=2 arc 18: e1 at 32.4 = (43.44, 25.92) -> (53.84, 18.12); 15.45     taken
#   k=3 arc 27: 27 - 25.6 = 1.4 down e2 from V2 = (48, 33.4)
#               + 13 * (1, 0) = (61, 33.4); to (57, 3): 30.66           FREE
# Expected: (61, 33.4), SLID - three steps, across vertex V2, off a sloped edge.
#
# Controls (scratch computation, recorded in the handoff):
#   steps of 18:            arc 18 taken, arc 36 = 10.4 down e2 -> (61, 42.4)
#   CCW, normals outward:   arc 9 back along e1 = (27.24, 4.32) -> (37.64, -3.48)
#   CCW by flipped winding: -> (16.84, 12.12)
IRREGULAR: list[Point] = [(0, 0), (24, 0), (48, 32), (48, 60), (0, 60)]
IRREGULAR_FIXTURE: list[tuple[int, Polygon]] = [(0, _rect(30, 16, 44, 30)), (1, IRREGULAR)]
IRREGULAR_EXPECTED: dict[int, tuple[Point, str]] = {
    0: ((57.0, 3.0), "NOMINAL"),
    1: ((61.0, 33.4), "SLID"),
}


def test_a_colliding_irregular_badge_walks_from_the_nearest_outline_point_along_a_sloped_edge() -> (
    None
):
    _assert_expected(_place(IRREGULAR_FIXTURE), IRREGULAR_EXPECTED)


# --- A candidate exactly on a vertex ------------------------------------------------
#
# CORNER_FIXTURE: both nominals are (143, 87). Region 1 is x 100..130, y 100..109;
# its right edge is 9 long, so k=1 (arc 9) lands exactly on the bottom-right vertex
# (130, 109). The edge being ENTERED is the bottom edge, walking left, whose outward
# normal is (0, +1): centre (130, 109 + 13) = (130, 122). To (143, 87): 37.3, free.
# The edge being LEFT (right edge, normal +x) would give (143, 109) instead.
# Steps of 18 would give arc 18 = 9 along the bottom -> (121, 122).


def test_a_candidate_exactly_on_a_vertex_is_pushed_out_along_the_edge_being_entered() -> None:
    _assert_expected(
        _place(CORNER_FIXTURE),
        {0: ((143.0, 87.0), "NOMINAL"), 1: ((130.0, 122.0), "SLID")},
    )


# --- Zoom: the walk is in screen px -------------------------------------------------
#
# Region 0: x 0..40, y 0..40; region 1: x 0..70, y 0..40.
# Zoom 1: nominals (53, -13) and (83, -13), 30 apart: both NOMINAL.
# Zoom 0.5: region 0 is x 0..20, y 0..20 -> (33, -13); region 1 is x 0..35,
#   y 0..20 -> (48, -13), 15 from (33, -13): taken. S = the vertex (35, 0).
#   k=1 arc 9 (screen px, not page px): right edge (35, 9) -> (48, 9);
#   to (33, -13): hypot(15, 22) = 26.6, free -> (48, 9), SLID.
#   (A walk measured in page px would step 4.5 screen px: (48, 4.5).)
ZOOM_FIXTURE: list[tuple[int, Polygon]] = [(0, _rect(0, 0, 40, 40)), (1, _rect(0, 0, 70, 40))]


def test_badges_apart_at_100_percent_stay_nominal() -> None:
    _assert_expected(
        _place(ZOOM_FIXTURE, zoom=1.0),
        {0: ((53.0, -13.0), "NOMINAL"), 1: ((83.0, -13.0), "NOMINAL")},
    )


def test_the_same_badges_collide_at_50_percent_and_the_walk_steps_9_screen_px() -> None:
    _assert_expected(
        _place(ZOOM_FIXTURE, zoom=0.5),
        {0: ((33.0, -13.0), "NOMINAL"), 1: ((48.0, 9.0), "SLID")},
    )


def test_the_rectangle_fixture_in_page_px_x2_at_50_percent_places_exactly_as_at_100_percent() -> (
    None
):
    doubled = [(rid, [(2 * x, 2 * y) for x, y in poly]) for rid, poly in RECT_FIXTURE]
    _assert_expected(_place(doubled, zoom=0.5), RECT_EXPECTED)


# =============================================================================
# AC-4 - stored winding never matters; clockwise is judged on screen
# =============================================================================


def _stored_variants(polygon: Polygon) -> dict[str, list[Point]]:
    ring = list(polygon)
    return {
        "screen-clockwise": ring,
        "counter-clockwise": ring[::-1],
        "counter-clockwise, other first vertex": (ring[::-1])[2:] + (ring[::-1])[:2],
        "clockwise closed ring": [*ring, ring[0]],
        "counter-clockwise closed ring": [*ring[::-1], ring[-1]],
    }


@pytest.mark.parametrize(
    "variant",
    [
        "screen-clockwise",
        "counter-clockwise",
        "counter-clockwise, other first vertex",
        "clockwise closed ring",
        "counter-clockwise closed ring",
    ],
)
def test_the_rectangle_walk_is_screen_clockwise_whatever_the_stored_winding(variant: str) -> None:
    fixture = [*RECT_FIXTURE[:2], (2, _stored_variants(RECT_FIXTURE[2][1])[variant])]
    _assert_expected(_place(fixture), RECT_EXPECTED)


@pytest.mark.parametrize(
    "variant",
    [
        "screen-clockwise",
        "counter-clockwise",
        "counter-clockwise, other first vertex",
        "clockwise closed ring",
        "counter-clockwise closed ring",
    ],
)
def test_the_irregular_walk_is_screen_clockwise_whatever_the_stored_winding(variant: str) -> None:
    fixture = [IRREGULAR_FIXTURE[0], (1, _stored_variants(IRREGULAR)[variant])]
    _assert_expected(_place(fixture), IRREGULAR_EXPECTED)


def test_a_region_stored_both_ways_is_placed_identically_including_the_vertex_case() -> None:
    clockwise = _place(CORNER_FIXTURE)
    counter = _place([(rid, list(poly)[::-1]) for rid, poly in CORNER_FIXTURE])
    assert counter == clockwise


# =============================================================================
# AC-5 - a full circuit with nothing free -> the AREA centroid
# =============================================================================
#
# The target polygon, screen-clockwise (a 60 x 20 bar with two notches cut into
# its right end):
#   (0, 0) (60, 0) (56, 5) (60, 10) (56, 15) (60, 20) (0, 20)
# Area: rect 1200 minus two triangles (60,0)(56,5)(60,10) and (60,10)(56,15)(60,20),
#   4 x 10 / 2 = 20 each -> 1160. (Shoelace sum 2320.)
# Area centroid: rect centroid (30, 10) x 1200, minus triangle centroids
#   (58 2/3, 5) and (58 2/3, 15) x 20 each:
#   x = (36000 - 20 * 176/3 * 2) / 1160 = (36000 - 7040/3) / 1160 = 100960 / 3480
#     = 2524 / 87 = 29.0114942...
#   y = (12000 - 100 - 300) / 1160 = 11600 / 1160 = 10
# Vertex mean: x = (0 + 60 + 56 + 60 + 56 + 60 + 0) / 7 = 292 / 7 = 41.714...,
#   y = 70 / 7 = 10 -> 12.70 from the area centroid, >= size / 2 = 9 (the control).
#   (Over the closed ring, 8 vertices, the mean is x = 36.5: 7.49 away, still wrong.)
#
# The blockers: 24 regions whose nominal badges form a 20 px lattice, x in
# {-20, 0, ..., 80}, y in {-20, 0, 20, 40}. Adjacent lattice badges are 20 apart,
# so all 24 stay NOMINAL. Every candidate of the target - the nominal (73, -13)
# and every walk point, which lie within 13 of an outline inside x 0..60,
# y 0..20 - lies in x -13..73, y -13..33, inside the lattice's hull, and so
# within 20 / sqrt(2) = 14.14 < 18 of a lattice badge. Nothing is free.
NOTCHED_BAR: list[Point] = [(0, 0), (60, 0), (56, 5), (60, 10), (56, 15), (60, 20), (0, 20)]
NOTCHED_BAR_CENTROID: Point = (2524 / 87, 10.0)
NOTCHED_BAR_VERTEX_MEAN: Point = (292 / 7, 10.0)
LATTICE_XS = (-20, 0, 20, 40, 60, 80)
LATTICE_YS = (-20, 0, 20, 40)


def _blocker(cx: float, cy: float) -> list[Point]:
    """A 4 x 4 rect whose nominal badge is centred on (cx, cy): R = cx - 13, T = cy + 13."""
    return _rect(cx - 17, cy + 13, cx - 13, cy + 17)


LATTICE: list[tuple[int, Polygon]] = [
    (index, _blocker(cx, cy))
    for index, (cx, cy) in enumerate((cx, cy) for cy in LATTICE_YS for cx in LATTICE_XS)
]
TARGET_ID = len(LATTICE)  # 24


def test_control_the_notched_bar_vertex_mean_is_at_least_half_a_badge_from_its_area_centroid() -> (
    None
):
    mean = (
        sum(x for x, _ in NOTCHED_BAR) / len(NOTCHED_BAR),
        sum(y for _, y in NOTCHED_BAR) / len(NOTCHED_BAR),
    )
    assert mean == pytest.approx(NOTCHED_BAR_VERTEX_MEAN, abs=ABS)
    assert math.dist(mean, NOTCHED_BAR_CENTROID) >= SIZE / 2


def test_a_region_with_no_free_candidate_on_its_whole_circuit_is_badged_at_its_area_centroid() -> (
    None
):
    result = _place([*LATTICE, (TARGET_ID, NOTCHED_BAR)])
    blocked_ids = [rid for rid, _ in LATTICE]
    assert [rid for rid in blocked_ids if result[rid].placement.name != "NOMINAL"] == [], (
        "the lattice blockers must all stay nominal, or the fixture is not what it claims"
    )
    _assert_at(result, TARGET_ID, NOTCHED_BAR_CENTROID, "CENTROID")


def test_the_centroid_fallback_is_the_same_point_whatever_the_stored_winding() -> None:
    result = _place([*LATTICE, (TARGET_ID, NOTCHED_BAR[::-1])])
    _assert_at(result, TARGET_ID, NOTCHED_BAR_CENTROID, "CENTROID")


def test_the_centroid_fallback_is_in_zoomed_scene_units() -> None:
    # Page px x 2 at zoom 0.5: the same screen geometry, the same centroid.
    doubled = [
        (rid, [(2 * x, 2 * y) for x, y in poly])
        for rid, poly in [*LATTICE, (TARGET_ID, NOTCHED_BAR)]
    ]
    _assert_at(_place(doubled, zoom=0.5), TARGET_ID, NOTCHED_BAR_CENTROID, "CENTROID")


# --- area_centroid directly -------------------------------------------------------


@pytest.mark.parametrize(
    ("polygon", "expected"),
    [
        # rectangle 10..50 x 20..60: its centre
        (_rect(10, 20, 50, 60), (30.0, 40.0)),
        # triangle: area centroid = vertex mean = (0 + 30 + 0, 0 + 0 + 12) / 3
        ([(0, 0), (30, 0), (0, 12)], (10.0, 4.0)),
        # the notched bar, worked out above
        (NOTCHED_BAR, NOTCHED_BAR_CENTROID),
        (NOTCHED_BAR[::-1], NOTCHED_BAR_CENTROID),
        ([*NOTCHED_BAR, NOTCHED_BAR[0]], NOTCHED_BAR_CENTROID),
    ],
    ids=["rectangle", "triangle", "notched-bar", "notched-bar-ccw", "notched-bar-closed-ring"],
)
def test_area_centroid_is_the_shoelace_centroid_in_the_units_of_its_input(
    polygon: Polygon, expected: Point
) -> None:
    assert _badges().area_centroid(polygon) == pytest.approx(expected, abs=ABS)


# =============================================================================
# AC-5, Amendment 1 - zero-area rings: no walk, bounding-rect centre
# =============================================================================
#
# Contract rule 1 (amended): zero area <=> the shoelace sum of the input page-px
# ring is exactly 0. Rule 5 (amended): nominal if free -> NOMINAL; otherwise no
# walk, and the badge goes to the bounding-rect centre ((L + R)/2, (T + B)/2) in
# zoomed-scene units -> CENTROID. It still counts as placed.
#
# The blocker: region 0, x 60..100, y 100..130 (R 100, T 100), nominal (113, 87);
# at zoom 2, R 200, T 200 -> (213, 187).
#
# The single point: (100, 100) stored five times (a closed ring of 4 + 1).
#   R = L = 100, T = B = 100 -> nominal (113, 87): distance 0 to the blocker.
#   Bounding-rect centre: (100, 100); at zoom 2, (200, 200).
#   (The shipped walk divides by the zero edge length: ZeroDivisionError.)
#
# The collinear ring: (40, 140) (55, 130) (100, 100), closed. Every step is a
#   multiple of (15, -10), so it is collinear, with shoelace sum
#   40*130 - 55*140 + 55*100 - 100*130 + 100*140 - 40*100
#   = 5200 - 7700 + 5500 - 13000 + 14000 - 4000 = 0.
#   L 40, R 100, T 100, B 140 -> nominal (113, 87): distance 0 to the blocker.
#   Bounding-rect centre ((40 + 100)/2, (100 + 140)/2) = (70, 120); at zoom 2,
#   (140, 240). The vertex mean would be (65, 123.33); the walk (shipped code,
#   no guard) gives a SLID point instead.
BLOCKER_AT_100_100: Polygon = _rect(60, 100, 100, 130)
SINGLE_POINT: list[Point] = [(100, 100)] * 5
COLLINEAR: list[Point] = [(40, 140), (55, 130), (100, 100), (40, 140)]


@pytest.mark.parametrize(
    ("ring", "zoom", "expected"),
    [
        (SINGLE_POINT, 1.0, (100.0, 100.0)),
        (SINGLE_POINT, 2.0, (200.0, 200.0)),
        (COLLINEAR, 1.0, (70.0, 120.0)),
        (COLLINEAR, 2.0, (140.0, 240.0)),
    ],
    ids=["single-point-zoom-1", "single-point-zoom-2", "collinear-zoom-1", "collinear-zoom-2"],
)
def test_a_zero_area_ring_whose_nominal_collides_is_badged_at_its_bounding_rect_centre(
    ring: Polygon, zoom: float, expected: Point
) -> None:
    result = _place([(0, BLOCKER_AT_100_100), (1, ring)], zoom=zoom)
    _assert_at(result, 0, (100.0 * zoom + 13, 100.0 * zoom - 13), "NOMINAL")
    _assert_at(result, 1, expected, "CENTROID")


@pytest.mark.parametrize(
    ("ring", "zoom", "expected"),
    [
        # R 100, T 100 for both rings: (113, 87); at zoom 2, (213, 187).
        (SINGLE_POINT, 1.0, (113.0, 87.0)),
        (SINGLE_POINT, 2.0, (213.0, 187.0)),
        (COLLINEAR, 1.0, (113.0, 87.0)),
        (COLLINEAR, 2.0, (213.0, 187.0)),
    ],
    ids=["single-point-zoom-1", "single-point-zoom-2", "collinear-zoom-1", "collinear-zoom-2"],
)
def test_a_zero_area_ring_whose_nominal_is_free_keeps_its_nominal_badge(
    ring: Polygon, zoom: float, expected: Point
) -> None:
    _assert_expected(_place([(0, ring)], zoom=zoom), {0: (expected, "NOMINAL")})


def test_a_later_region_avoids_a_zero_area_rings_centroid_badge_which_counts_as_placed() -> None:
    # 0: the blocker, NOMINAL (113, 87).
    # 1: the single point, nominal (113, 87) taken -> CENTROID (100, 100).
    # 2: x 57..87, y 113..123 (R 87, T 113) -> nominal (100, 100): 18.38 from
    #    (113, 87), so free of the blocker, but 0 from region 1's badge: taken.
    #    S = the vertex (87, 113); k=1, arc 9 down the right edge (87, 122)
    #    -> +13x -> (100, 122). To (100, 100): 22; to (113, 87): 37.3. FREE.
    #    If the centroid badge did not count as placed, region 2 would stay
    #    NOMINAL at (100, 100), on top of region 1's badge.
    result = _place([(0, BLOCKER_AT_100_100), (1, SINGLE_POINT), (2, _rect(57, 113, 87, 123))])
    _assert_expected(
        result,
        {
            0: ((113.0, 87.0), "NOMINAL"),
            1: ((100.0, 100.0), "CENTROID"),
            2: ((100.0, 122.0), "SLID"),
        },
    )


# =============================================================================
# AC-6 - hand fixtures: input order and higher ordinals never matter
# =============================================================================


def test_the_rectangle_fixture_supplied_in_reverse_order_places_exactly_the_same() -> None:
    # Placed in INPUT order, region 2 would go first and stay nominal at (143, 87).
    _assert_expected(_place(RECT_FIXTURE[::-1]), RECT_EXPECTED)


def test_removing_the_higher_ordinal_of_two_coincident_corners_leaves_the_lower_one_nominal() -> (
    None
):
    # Placed in DESCENDING ordinal, region 1 would take (143, 87) and push region 0.
    both = _place(CORNER_FIXTURE[::-1])
    alone = _place(CORNER_FIXTURE[:1])
    _assert_at(both, 0, (143.0, 87.0), "NOMINAL")
    assert alone == {0: both[0]}


# =============================================================================
# AC-2 and AC-6 as properties over generated pages
# =============================================================================
#
# The domain is the Contract's as amended (Amendment 1): every ring RawRegion
# accepts, in page px, zero area included. Three sources, none narrower than that
# (the third, `_zero_area_ring`, draws collinear and single-point rings):
#   - free polygons: 3..7 random integer points, untangled by 2-opt (reversing
#     the run between two properly crossing edges strictly shortens the ring, so
#     it terminates), then kept only if simple, with distinct vertices and
#     non-zero area. Stored in either winding, sometimes as a closed ring.
#   - boxes on a coarse grid, which share corners often - the collision-heavy
#     case the story is about. Uniform points alone rarely collide.
# The page is kept small (0..160) so that badges collide on most examples.


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _properly_cross(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def _segments_touch(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """Any shared point at all, collinear overlap included."""

    def on(a: Point, b: Point, c: Point) -> bool:
        return (
            _cross(a, b, c) == 0
            and min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])
        )

    if _properly_cross(p1, p2, q1, q2):
        return True
    return on(p1, p2, q1) or on(p1, p2, q2) or on(q1, q2, p1) or on(q1, q2, p2)


def _is_simple(ring: list[Point]) -> bool:
    n = len(ring)
    if n < 3 or len(set(ring)) != n:
        return False
    twice_area = sum(_cross((0, 0), ring[i], ring[(i + 1) % n]) for i in range(n))
    if twice_area == 0:
        return False
    for i in range(n):
        for j in range(i + 1, n):
            adjacent = j == i + 1 or (i == 0 and j == n - 1)
            a1, a2 = ring[i], ring[(i + 1) % n]
            b1, b2 = ring[j], ring[(j + 1) % n]
            if adjacent:
                # Adjacent edges share one vertex; they must not fold back onto each other.
                shared = a2 if j == i + 1 else a1
                other_a = a1 if j == i + 1 else a2
                other_b = b2 if j == i + 1 else b1
                if _cross(shared, other_a, other_b) == 0 and (
                    (other_a[0] - shared[0]) * (other_b[0] - shared[0])
                    + (other_a[1] - shared[1]) * (other_b[1] - shared[1])
                    > 0
                ):
                    return False
            elif _segments_touch(a1, a2, b1, b2):
                return False
    return True


def _untangle(ring: list[Point]) -> list[Point]:
    ring = list(ring)
    n = len(ring)
    for _ in range(200):
        for i in range(n):
            for j in range(i + 2, n):
                if i == 0 and j == n - 1:
                    continue
                if _properly_cross(ring[i], ring[i + 1], ring[j], ring[(j + 1) % n]):
                    ring[i + 1 : j + 1] = ring[i + 1 : j + 1][::-1]
                    break
            else:
                continue
            break
        else:
            return ring
    return ring


_coordinate = st.integers(min_value=0, max_value=160)


@st.composite
def _free_polygon(draw: st.DrawFn) -> list[Point]:
    points = draw(st.lists(st.tuples(_coordinate, _coordinate), min_size=3, max_size=7))
    ring: list[Point] = _untangle([(float(x), float(y)) for x, y in points])
    assume(_is_simple(ring))
    if draw(st.booleans()):
        ring = ring[::-1]
    if draw(st.booleans()):
        ring = [*ring, ring[0]]
    return ring


@st.composite
def _grid_box(draw: st.DrawFn) -> list[Point]:
    x0 = draw(st.sampled_from([0, 20, 40, 60, 80]))
    y0 = draw(st.sampled_from([0, 20, 40, 60, 80]))
    width = draw(st.sampled_from([10, 20, 40, 60]))
    height = draw(st.sampled_from([8, 20, 40]))
    box = _rect(x0, y0, x0 + width, y0 + height)
    return box[::-1] if draw(st.booleans()) else box


@st.composite
def _zero_area_ring(draw: st.DrawFn) -> list[Point]:
    """Amendment 1: a closed ring of >= 4 stored vertices with shoelace sum exactly 0.

    Every vertex is `origin + m * direction` for integer m, so the ring is collinear
    (in any order, repeats included) or, when every m is equal, a single point - both
    of which `RawRegion` accepts. Integer coordinates keep the zero exact.
    """
    x0, y0 = draw(_coordinate), draw(_coordinate)
    dx = draw(st.integers(min_value=-3, max_value=3))
    dy = draw(st.integers(min_value=-3, max_value=3))
    steps = draw(st.lists(st.integers(min_value=0, max_value=12), min_size=3, max_size=6))
    if draw(st.booleans()):
        steps = [steps[0]] * len(steps)  # a single repeated point
    ring = [(float(x0 + m * dx), float(y0 + m * dy)) for m in steps]
    assume(all(x >= 0 and y >= 0 for x, y in ring))
    return [*ring, ring[0]]


# Amendment 1 widens the domain to every ring RawRegion accepts; zero-area rings are
# added to what is drawn, and nothing that was drawn before is removed.
_polygon = st.one_of(_free_polygon(), _grid_box(), _zero_area_ring())
_zoom = st.sampled_from([0.1, 0.25, 0.5, 1.0, 2.0, 8.0])


@st.composite
def _page(draw: st.DrawFn) -> list[tuple[int, Polygon]]:
    polygons = draw(st.lists(_polygon, min_size=1, max_size=8))
    # Region ids need not be contiguous or 0-based for the rule to hold; spacing
    # them out catches an implementation that keys by position.
    ids = draw(st.permutations([3 * i + 1 for i in range(len(polygons))]))
    return list(zip(ids, polygons, strict=True))


def _twice_page_area(polygon: Polygon) -> float:
    """Contract rule 1 (Amendment 1): the shoelace sum of the input page-px ring."""
    ring = list(polygon)
    return sum(_cross((0, 0), ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring)))


def _bbox_centre(polygon: Polygon) -> Point:
    xs = [x for x, _ in polygon]
    ys = [y for _, y in polygon]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def _nominal_is_free(nominal: Point, earlier: Sequence[Point]) -> bool:
    return all(math.dist(nominal, centre) >= SIZE - ABS for centre in earlier)


@given(page=_page(), zoom=_zoom)
@settings(deadline=None, max_examples=150)
def test_every_badge_not_at_its_centroid_is_disjoint_from_every_badge_placed_before_it(
    page: list[tuple[int, Polygon]], zoom: float
) -> None:
    result = _place(page, zoom=zoom)
    assert sorted(result) == sorted(rid for rid, _ in page)

    polygons = dict(page)
    in_order = sorted(result)
    centres = [
        (rid, tuple(result[rid].centre), result[rid].placement.name == "CENTROID")
        for rid in in_order
    ]
    overlaps = _overlaps(centres)  # type: ignore[arg-type]
    assert overlaps == [], (
        f"badges overlapping an earlier one (later, earlier, distance): {overlaps}"
    )

    # AC-1 as a property: a badge whose nominal is free is never moved, and a
    # NOMINAL badge is exactly MT-016's position.
    problems: list[str] = []
    for index, rid in enumerate(in_order):
        nominal = _mt016_nominal(polygons[rid], zoom)
        earlier = [result[e].centre for e in in_order[:index]]
        name = result[rid].placement.name
        if _nominal_is_free(nominal, earlier) and name != "NOMINAL":
            problems.append(f"{rid}: nominal {nominal} was free but badge was {name}")
        if name == "NOMINAL" and result[rid].centre != pytest.approx(nominal, abs=ABS):
            problems.append(f"{rid}: NOMINAL badge at {result[rid].centre}, nominal is {nominal}")
        degenerate = _twice_page_area(polygons[rid]) == 0
        if degenerate and name == "SLID":
            problems.append(f"{rid}: zero-area ring was SLID; Amendment 1 says it never walks")
        if name == "CENTROID":
            scaled = [(x * zoom, y * zoom) for x, y in polygons[rid]]
            # Amendment 1: a zero-area ring has no area centroid; its fallback is the
            # bounding-rect centre. Every other ring keeps the area centroid.
            centroid = _bbox_centre(scaled) if degenerate else _badges().area_centroid(scaled)
            if result[rid].centre != pytest.approx(centroid, abs=ABS):
                problems.append(f"{rid}: CENTROID badge at {result[rid].centre}, not {centroid}")
    assert problems == []


@given(page=_page(), zoom=_zoom, rnd=st.randoms(use_true_random=False))
@settings(deadline=None, max_examples=100)
def test_placement_ignores_input_order_and_never_depends_on_a_higher_ordinal(
    page: list[tuple[int, Polygon]], zoom: float, rnd: random.Random
) -> None:
    result = _place(page, zoom=zoom)
    assert _place(page, zoom=zoom) == result, "the same page twice must place identically"

    shuffled = list(page)
    rnd.shuffle(shuffled)
    assert _place(shuffled, zoom=zoom) == result, "input order changed the placement"

    highest = max(rid for rid, _ in page)
    without = [(rid, poly) for rid, poly in page if rid != highest]
    expected = {rid: badge for rid, badge in result.items() if rid != highest}
    assert _place(without, zoom=zoom) == expected, (
        f"removing the highest-ordinal region ({highest}) moved a lower one"
    )
