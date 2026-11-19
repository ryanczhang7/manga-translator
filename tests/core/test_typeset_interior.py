"""MT-123 AC-1..AC-3: `mangatl.typeset.interior.bubble_interior`, the bubble found
on the cleaned page.

**Oracle: mechanical** (Contract block 4). Every number is read out of blocks
1-3: the ring's shape, the `>= 95%` cover, the window, the identity fallbacks.
The page is `_bubble_world.bubble_page`, whose interior, outline and band are
exact sets the test built; the window is `_bubble_world.window`, computed from
the pinned `CAP_RATIO`, never from the module.

**AC-3(b) is asserted on the real bake world**, `_bake_world.texture` +
`cleaned_from` at every salt the bake suites use and more, with every region of
`REGION_GEOMETRY` - not on a page shaped for this file. That world is what
`test_bake.py`, `test_bake_font.py` and `test_cli_bake.py` pin bytes against,
with `typeset(..., region.polygon, ...)`: they stay correct only while the
interior there IS the polygon. Measured in RED (no module): the largest light
component a region's fill seeds holds 372-377 px against fills of 3,621-3,723
(regions 0-2), and 114-116 against 777 (region 3) - rule 4 returns the polygon.

RED: `mangatl.typeset.interior` does not exist, so this file fails at import and
no assertion in it has run. The fixture-only controls (the page is light only in
the bubble; the plain flood of the open page leaks to the edge) are in
`test_bake_interior.py`, which does not import the module at top level, so they
run in RED.
"""

from __future__ import annotations

import _bake_world as world
import _bubble_world as bw
import numpy as np
import pytest

from mangatl.typeset.fit import MIN_SIZE_PX, typeset
from mangatl.typeset.font import load_faces
from mangatl.typeset.interior import (
    CAP_RATIO,
    DARK_GREY,
    LIGHT_GREY,
    RAY_COUNT,
    bubble_interior,
)

SHAPE = (bw.PAGE_H, bw.PAGE_W)

#: Overflows the 60 x 200 column at MIN_SIZE_PX; set at 30 px in the ellipse's
#: interior (measured in RED against the analytic inner ellipse's contour).
#: The user's own line, 007.jpg region 1.
FITS_THE_BUBBLE = "YOU WANT TO COEXIST WITH HUMANS... HUH?"


def _assert_is_a_ring(ring: object) -> None:
    assert isinstance(ring, tuple), f"the interior must be a tuple ring, got {type(ring)}"
    assert len(ring) >= 4, f"a ring has at least 4 vertices, got {len(ring)}"
    assert ring[0] == ring[-1], "the ring must be closed: its last vertex repeats its first"
    bad = [v for point in ring for v in point if type(v) is not int or v < 0]
    assert not bad, f"vertices must be non-negative Python ints (RawRegion's rule), got {bad[:3]}"


# -- block 1: the numbers ---------------------------------------------------------


def test_the_interior_thresholds_are_the_contracts_numbers() -> None:
    assert (LIGHT_GREY, DARK_GREY, CAP_RATIO, RAY_COUNT) == (
        bw.PINNED_LIGHT_GREY,
        bw.PINNED_DARK_GREY,
        bw.PINNED_CAP_RATIO,
        bw.PINNED_RAY_COUNT,
    )


# -- AC-1: a closed bubble ------------------------------------------------------------


def test_a_closed_bubbles_interior_is_found_covering_its_white_and_none_of_its_outline() -> None:
    page = bw.bubble_page()

    found = bubble_interior(page.grey, bw.POLYGON, "bubble")

    _assert_is_a_ring(found)
    filled = bw.fill(found, SHAPE)
    cover = (filled & page.interior).sum() / page.interior.sum()
    assert cover >= 0.95, f"the ring covers {cover:.4f} of the bubble's white interior, < 0.95"
    on_outline = int((filled & page.outline).sum())
    assert on_outline == 0, f"the ring's fill holds {on_outline} outline pixels"


def test_a_line_that_overflows_the_column_is_set_in_the_bubble_at_twice_the_minimum() -> None:
    faces = load_faces()
    page = bw.bubble_page()
    column = typeset(FITS_THE_BUBBLE, bw.POLYGON, faces)
    assert column.overflowed and column.size_px == MIN_SIZE_PX, (
        "precondition: the line must overflow the bare column at the minimum size"
    )

    block = typeset(FITS_THE_BUBBLE, bubble_interior(page.grey, bw.POLYGON, "bubble"), faces)

    assert not block.overflowed, "the line still overflows inside the bubble's interior"
    assert block.size_px >= 2 * MIN_SIZE_PX, (
        f"set at {block.size_px} px in the bubble, under 2 x MIN_SIZE_PX = {2 * MIN_SIZE_PX}"
    )


# -- AC-2: an open bubble is bounded, not leaked --------------------------------------------


def test_an_open_bubbles_interior_holds_no_outline_pixel() -> None:
    page = bw.bubble_page(open_gap=True)

    found = bubble_interior(page.grey, bw.POLYGON, "bubble")

    _assert_is_a_ring(found)
    on_outline = int((bw.fill(found, SHAPE) & page.outline).sum())
    assert on_outline == 0, f"the ring's fill holds {on_outline} outline pixels of the open bubble"


def test_an_open_bubbles_interior_stays_inside_the_window_and_off_the_page_edge() -> None:
    page = bw.bubble_page(open_gap=True)
    x0, y0, x1, y1 = bw.window(bw.POLYGON, SHAPE)

    found = bubble_interior(page.grey, bw.POLYGON, "bubble")

    outside = [(x, y) for x, y in found if not (x0 <= x <= x1 and y0 <= y <= y1)]
    assert not outside, f"vertices outside the window {(x0, y0, x1, y1)}: {outside[:5]}"
    on_edge = [(x, y) for x, y in found if x in (0, bw.PAGE_W - 1) or y in (0, bw.PAGE_H - 1)]
    assert not on_edge, f"vertices on the page edge - the flood leaked: {on_edge[:5]}"


def test_an_open_bubbles_interior_is_still_the_bubble_not_the_column() -> None:
    # Beyond AC-2's letter, pinning Contract block 1 rule 6: the identity also
    # holds no outline pixel and stays in the window, so without this AC-2 is
    # satisfied by returning the polygon. Measured in RED with the amended rule
    # (star fill minus the closed dark mask): cover 0.9957.
    page = bw.bubble_page(open_gap=True)

    filled = bw.fill(bubble_interior(page.grey, bw.POLYGON, "bubble"), SHAPE)

    cover = (filled & page.interior).sum() / page.interior.sum()
    assert cover >= 0.95, f"the open bubble's ring covers {cover:.4f} of its white interior"


# -- AC-3: the fallbacks are the identity ------------------------------------------------------


@pytest.mark.parametrize("open_gap", [False, True], ids=["closed", "open"])
def test_a_box_region_keeps_its_polygon_unchanged(open_gap: bool) -> None:
    page = bw.bubble_page(open_gap=open_gap)

    assert bubble_interior(page.grey, bw.POLYGON, "box") == bw.POLYGON


@pytest.mark.parametrize("salt", range(10))
def test_on_the_bake_suites_world_every_region_keeps_its_polygon(salt: int) -> None:
    # The light component inside each polygon is the flat-white erase mask,
    # smaller than the polygon's fill (rule 4).
    page_regions = world.regions()
    cleaned = world.cleaned_from(world.texture(world.PAGE_W, world.PAGE_H, salt), page_regions)
    grey = bw.grey_of(cleaned)

    found = [bubble_interior(grey, region.polygon, region.kind) for region in page_regions]

    assert found == [region.polygon for region in page_regions]


def test_a_polygon_with_no_light_pixel_keeps_its_polygon_unchanged() -> None:
    # A white bubble elsewhere on the page, but none of it under the polygon.
    grey = np.full(SHAPE, 150, dtype=np.uint8)
    grey[20:120, 20:200] = 255
    polygon = bw.ring(300, 300, 360, 500)

    assert bubble_interior(grey, polygon, "bubble") == polygon


# -- MT-154: a closed balloon larger than the window ------------------------------------------
#
# Oracle: C-2's two numbers are settled and read out; AC-1..AC-5 are mechanical
# (C-6). The new names are imported inside each test that needs them, not at the
# top, so that the MT-123 cases above still run while they do not exist (C-5).
# Every precondition below is the test's own arithmetic (`_bubble_world`), never
# the module's (C-4).

TALL = bw.TALL_SHAPE

#: Breaks into three lines in the tall balloon's interior (measured in RED on the
#: outer ring of the balloon's flood: 'WHERE' / 'ARE YOU' / 'GOING?' at 42 px).
THREE_LINES = "WHERE ARE YOU GOING?"


def test_the_shape_test_thresholds_are_the_contracts_numbers_and_are_exported() -> None:
    from mangatl.typeset import interior

    assert (interior.INTERIOR_MIN_SOLIDITY, interior.INTERIOR_MAX_PAGE_FRACTION) == (
        bw.PINNED_INTERIOR_MIN_SOLIDITY,
        bw.PINNED_INTERIOR_MAX_PAGE_FRACTION,
    )
    missing = {"INTERIOR_MIN_SOLIDITY", "INTERIOR_MAX_PAGE_FRACTION"} - set(interior.__all__)
    assert not missing, f"not exported in __all__: {sorted(missing)}"


def _assert_the_window_cannot_decide(page: bw.BubblePage, polygon: bw.Ring) -> None:
    flood = bw.plain_flood(page.grey, polygon)
    window = bw.window(polygon, TALL)
    assert flood.any(), "precondition: the polygon must seed a light flood"
    assert not bw.strictly_inside(flood, window), (
        f"precondition: the flood must not be strictly inside the window {window}, "
        "or clause 5a decides this page and 5b is not tested"
    )


def _assert_no_vertex_outside_the_window(found: object, polygon: bw.Ring) -> None:
    _assert_is_a_ring(found)
    assert isinstance(found, tuple)
    x0, y0, x1, y1 = bw.window(polygon, TALL)
    outside = [(x, y) for x, y in found if not (x0 <= x <= x1 and y0 <= y <= y1)]
    assert not outside, (
        f"{len(outside)} vertices outside the window {(x0, y0, x1, y1)} - the flood was "
        f"accepted as the balloon: {outside[:5]}"
    )


# -- AC-1 / AC-2: a closed balloon larger than the window is found whole ----------------------


def test_a_closed_balloon_taller_than_the_window_is_found_whole_and_centred() -> None:
    page = bw.tall_balloon_page()
    polygon = bw.tall_polygon()
    _assert_the_window_cannot_decide(page, polygon)
    flood = bw.plain_flood(page.grey, polygon)
    assert not bw.touches_page_edge(flood), "precondition: the balloon touches no page edge"
    assert bw.page_fraction(flood) <= bw.PINNED_INTERIOR_MAX_PAGE_FRACTION
    assert bw.solidity(flood) >= bw.PINNED_INTERIOR_MIN_SOLIDITY

    found = bubble_interior(page.grey, polygon, "bubble")

    _assert_is_a_ring(found)
    filled = bw.fill(found, TALL)
    cover = (filled & page.interior).sum() / page.interior.sum()
    assert cover >= 0.95, f"the ring covers {cover:.4f} of the balloon's white interior, < 0.95"
    on_outline = int((filled & page.outline).sum())
    assert on_outline == 0, f"the ring's fill holds {on_outline} outline pixels"
    (fx, fy), (ix, iy) = bw.centroid(filled), bw.centroid(page.interior)
    width, height = 2 * bw.TALL_OUTER_A, 2 * bw.TALL_OUTER_B
    assert abs(fx - ix) <= 0.02 * width, (
        f"the ring's centroid is {fx - ix:+.1f} px across from the interior's, "
        f"beyond 2% of the balloon's width ({0.02 * width:.1f} px)"
    )
    assert abs(fy - iy) <= 0.02 * height, (
        f"the ring's centroid is {fy - iy:+.1f} px ({(fy - iy) / height:+.1%} of the balloon's "
        f"height) from the interior's, beyond 2% ({0.02 * height:.1f} px)"
    )


def test_three_lines_in_a_balloon_taller_than_the_window_are_centred_in_the_balloon() -> None:
    faces = load_faces()
    page = bw.tall_balloon_page()
    polygon = bw.tall_polygon()

    block = typeset(THREE_LINES, bubble_interior(page.grey, polygon, "bubble"), faces)

    assert block.lines and not block.overflowed, "the line must set without overflowing"
    middle = (block.lines[0].top + block.lines[-1].top + block.lines[-1].height) / 2
    height = 2 * bw.TALL_OUTER_B
    off = middle - bw.TALL_CY
    assert abs(off) <= 0.05 * height, (
        f"the block's vertical centre is {off:+.1f} px ({off / height:+.1%} of the balloon's "
        f"height) from the balloon's centre, beyond 5% ({0.05 * height:.1f} px)"
    )
    assert len(block.lines) == 3, (
        f"the string must break into three lines, got {len(block.lines)}: "
        f"{[''.join(g.char for g in line.glyphs) for line in block.lines]}"
    )


# -- AC-3..AC-5: each clause of 5b alone still sends a flood to the star ---------------------


def test_a_balloon_cut_by_the_page_edge_still_falls_back_inside_the_window() -> None:
    page = bw.tall_balloon_page(centre_x=bw.EDGE_CUT_CX)
    polygon = bw.tall_polygon(bw.EDGE_CUT_CX)
    _assert_the_window_cannot_decide(page, polygon)
    flood = bw.plain_flood(page.grey, polygon)
    # Fails clause 5b.1 only.
    assert bw.touches_page_edge(flood), "precondition: the balloon's white reaches the edge"
    assert bw.page_fraction(flood) <= bw.PINNED_INTERIOR_MAX_PAGE_FRACTION, (
        f"precondition: fraction {bw.page_fraction(flood):.4f} must be within the limit"
    )
    assert bw.solidity(flood) >= 0.97, f"precondition: solidity {bw.solidity(flood):.4f}"

    found = bubble_interior(page.grey, polygon, "bubble")

    _assert_no_vertex_outside_the_window(found, polygon)


def test_a_closed_white_panel_over_a_quarter_of_the_page_is_not_taken_for_a_balloon() -> None:
    page = bw.white_panel_page()
    polygon = bw.tall_polygon()
    _assert_the_window_cannot_decide(page, polygon)
    flood = bw.plain_flood(page.grey, polygon)
    # Fails clause 5b.2 only.
    assert not bw.touches_page_edge(flood), "precondition: the panel touches no page edge"
    assert bw.page_fraction(flood) > bw.PINNED_INTERIOR_MAX_PAGE_FRACTION, (
        f"precondition: fraction {bw.page_fraction(flood):.4f} must exceed the limit"
    )
    assert bw.solidity(flood) >= 0.97, f"precondition: solidity {bw.solidity(flood):.4f}"

    found = bubble_interior(page.grey, polygon, "bubble")

    _assert_no_vertex_outside_the_window(found, polygon)


def test_a_balloon_open_into_light_art_is_not_found_whole() -> None:
    page = bw.tall_balloon_page(open_into_art=True)
    polygon = bw.tall_polygon()
    _assert_the_window_cannot_decide(page, polygon)
    flood = bw.plain_flood(page.grey, polygon)
    # Fails clause 5b.3 only.
    assert int((flood & page.band).sum()) > 0, "precondition: the flood runs into the art"
    assert not bw.touches_page_edge(flood), "precondition: the flood touches no page edge"
    assert bw.page_fraction(flood) <= bw.PINNED_INTERIOR_MAX_PAGE_FRACTION, (
        f"precondition: fraction {bw.page_fraction(flood):.4f} must be within the limit"
    )
    assert bw.solidity(flood) <= 0.85, f"precondition: solidity {bw.solidity(flood):.4f}"

    found = bubble_interior(page.grey, polygon, "bubble")

    _assert_no_vertex_outside_the_window(found, polygon)
