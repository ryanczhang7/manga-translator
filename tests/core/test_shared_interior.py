"""MT-155: `shared_parts`, the rule that splits a balloon two regions share.

Contract C-1, observed on the function directly (C-5, "How the tests observe"):
it is public and pure, so every ring claim of AC-1, AC-3 and AC-6 is asserted
here, and what the bake does with the rings is `test_bake_interior.py`'s.

**The interiors are `bubble_interior`'s own answer** on each `_bubble_world`
page, as `_set_blocks` computes them, so the input is exactly what the bake
hands over. The **oracles are the test's**: the analytic interior
(`BubblePage.interior`), `_bubble_world.fill` for a ring's pixels, and
`_bubble_world.rect_distance` for "nearer" - each pixel's distance to a
rectangle computed from its coordinates, never `cv2.distanceTransform`, which is
what the implementation uses (C-6).

**In RED every test here fails before its first assertion**: `shared_parts`
does not exist, so each call raises `AttributeError`. It is read off the module
(`interior_module.shared_parts`) rather than imported by name so that the
missing name fails each test, not the collection of the whole `tests/core` run -
a collection error would interrupt pytest and hide every other suite's result.
Not one assertion below has run in RED. The numbers each test's preconditions and messages
cite were measured in RED with a scratch reference of C-1 outside the tree; the
story's handoff has them, and GREEN confirms them against the shipped module.

Every page is 640 x 560 and each test calls `shared_parts` once or twice; no
`pytest-timeout` exists in this project, so there is no per-test budget to size.
"""

from __future__ import annotations

from collections.abc import Sequence

import _bubble_world as bw
import numpy as np
import pytest
from numpy.typing import NDArray

from mangatl.typeset import interior as interior_module
from mangatl.typeset.interior import Ring, bubble_interior

SHAPE = (bw.PAGE_H, bw.PAGE_W)


def _fill(ring: Sequence[tuple[int, int]]) -> NDArray[np.bool_]:
    return bw.fill(ring, SHAPE)


def _holds(mask: NDArray[np.bool_], point: tuple[int, int]) -> bool:
    x, y = point
    return bool(mask[y, x])


def _lobe_interiors() -> tuple[Ring, Ring]:
    page = bw.two_lobed_page()
    return (
        bubble_interior(page.grey, bw.LEFT_LOBE_POLYGON, "bubble"),
        bubble_interior(page.grey, bw.RIGHT_LOBE_POLYGON, "bubble"),
    )


def _lobe_parts() -> list[Ring]:
    return list(
        interior_module.shared_parts(
            list(_lobe_interiors()), [bw.LEFT_LOBE_POLYGON, bw.RIGHT_LOBE_POLYGON], SHAPE
        )
    )


# -- the fixture's givens (C-5) -------------------------------------------------------


def test_both_lobe_regions_find_the_whole_two_lobed_balloon_as_their_interior() -> None:
    # C-5: both windows hold the balloon strictly, so both interiors are the
    # flood, the whole 62,301 px balloon. A fixture that fell to the star
    # (solidity 0.9374 < 0.96) would be a different test.
    page = bw.two_lobed_page()
    left, right = _lobe_interiors()

    assert int(page.interior.sum()) == 62_301
    assert bw.strictly_inside(page.interior, bw.window(bw.LEFT_LOBE_POLYGON, SHAPE))
    assert bw.strictly_inside(page.interior, bw.window(bw.RIGHT_LOBE_POLYGON, SHAPE))
    assert np.array_equal(_fill(left), page.interior)
    assert np.array_equal(_fill(right), page.interior)


# -- AC-1: each region keeps the part of the balloon nearer its own polygon -----------


def test_the_two_lobe_parts_are_disjoint_and_together_are_the_whole_balloon() -> None:
    left, right = (_fill(part) for part in _lobe_parts())
    interior = bw.two_lobed_page().interior

    overlap = int((left & right).sum())
    assert overlap == 0, f"the two parts share {overlap} px: one balloon was handed out twice"
    missing = int((interior & ~(left | right)).sum())
    extra = int(((left | right) & ~interior).sum())
    assert (missing, extra) == (0, 0), (
        f"the parts leave {missing} px of the balloon to nobody and reach {extra} px past it"
    )


def test_every_pixel_of_a_lobe_part_is_nearer_its_own_polygon_than_the_other() -> None:
    # C-6: no farther from its own polygon than from the other's by more than
    # 1 px, the distances from the rectangles' coordinates.
    left, right = (_fill(part) for part in _lobe_parts())
    to_left = bw.rect_distance(bw.LEFT_LOBE_POLYGON, SHAPE)
    to_right = bw.rect_distance(bw.RIGHT_LOBE_POLYGON, SHAPE)

    wrong_left = int((left & (to_left > to_right + 1)).sum())
    wrong_right = int((right & (to_right > to_left + 1)).sum())
    assert (wrong_left, wrong_right) == (0, 0), (
        f"{wrong_left} px of the left part are nearer the right polygon, and"
        f" {wrong_right} px of the right part nearer the left one"
    )


def test_the_cut_between_the_lobes_is_the_midline_and_its_tie_column_goes_to_reading_index_0() -> (
    None
):
    # C-1 step 4: x = 320 is 50 px from both polygons; a tie goes to the earlier
    # region. Measured in RED: left part x <= 320, right part x >= 321.
    left, right = (_fill(part) for part in _lobe_parts())

    assert int(np.flatnonzero(left.any(axis=0))[-1]) == bw.MIDLINE_X
    assert int(np.flatnonzero(right.any(axis=0))[0]) == bw.MIDLINE_X + 1


def test_each_lobe_part_still_holds_its_own_polygon() -> None:
    # C-1, "the floor is the polygon": a part is a superset of its polygon fill.
    parts = _lobe_parts()
    for part, polygon in zip(parts, [bw.LEFT_LOBE_POLYGON, bw.RIGHT_LOBE_POLYGON], strict=True):
        outside = int((_fill(polygon) & ~_fill(part)).sum())
        assert outside == 0, f"{outside} px of {polygon[0]}'s polygon lie outside its part"


def test_a_shared_part_is_a_closed_ring_of_python_ints() -> None:
    for part in _lobe_parts():
        assert part[0] == part[-1], "a part's ring must be closed, as every interior is"
        assert all(type(v) is int for point in part for v in point)


# -- AC-3: nothing shared, nothing changed --------------------------------------------


def test_two_regions_in_two_separate_balloons_get_their_interiors_back_unchanged() -> None:
    page = bw.separate_balloons_page()
    polygons = [bw.SEPARATE_LEFT_POLYGON, bw.SEPARATE_RIGHT_POLYGON]
    interiors = [bubble_interior(page.grey, p, "bubble") for p in polygons]
    # Measured in RED: each interior is one 53,189 px balloon; they do not meet,
    # and neither holds the other polygon's centre.
    assert not (_fill(interiors[0]) & _fill(interiors[1])).any()
    assert not _holds(_fill(interiors[0]), bw.polygon_centre(polygons[1]))
    assert not _holds(_fill(interiors[1]), bw.polygon_centre(polygons[0]))

    assert list(interior_module.shared_parts(interiors, polygons, SHAPE)) == interiors


def test_a_box_straddling_the_balloon_outline_shares_nothing_and_both_rings_are_unchanged() -> None:
    page = bw.bubble_page()
    polygons = [bw.BALLOON_A_POLYGON, bw.STRADDLING_BOX_POLYGON]
    interiors = [
        bubble_interior(page.grey, bw.BALLOON_A_POLYGON, "bubble"),
        bubble_interior(page.grey, bw.STRADDLING_BOX_POLYGON, "box"),
    ]
    # C-5, measured in RED: 1,509 px of C's polygon lie in A's interior, yet
    # C's centre (480, 280) does not, and A's centre is not in C's polygon.
    overlap = int((_fill(interiors[0]) & _fill(interiors[1])).sum())
    assert overlap == 1_509, f"precondition: the interiors overlap by {overlap} px, not 1,509"
    assert not _holds(_fill(interiors[0]), bw.polygon_centre(polygons[1]))
    assert not _holds(_fill(interiors[1]), bw.polygon_centre(polygons[0]))

    assert list(interior_module.shared_parts(interiors, polygons, SHAPE)) == interiors


def test_a_page_with_one_region_gets_its_interior_back_and_an_empty_page_gets_nothing() -> None:
    page = bw.bubble_page()
    interior = bubble_interior(page.grey, bw.BALLOON_A_POLYGON, "bubble")

    assert list(interior_module.shared_parts([interior], [bw.BALLOON_A_POLYGON], SHAPE)) == [
        interior
    ]
    assert list(interior_module.shared_parts([], [], SHAPE)) == []


def test_interiors_and_polygons_of_different_lengths_are_refused() -> None:
    # C-1: the two sequences are zipped with `strict=True`.
    interior = bubble_interior(bw.bubble_page().grey, bw.BALLOON_A_POLYGON, "bubble")
    with pytest.raises(ValueError):
        interior_module.shared_parts(
            [interior], [bw.BALLOON_A_POLYGON, bw.INNER_BOX_POLYGON], SHAPE
        )


# -- AC-6: one-way sharing - a box inside the balloon ---------------------------------


def _box_inside_case() -> tuple[list[Ring], list[Ring]]:
    page = bw.bubble_page()
    interiors = [
        bubble_interior(page.grey, bw.BALLOON_A_POLYGON, "bubble"),
        bubble_interior(page.grey, bw.INNER_BOX_POLYGON, "box"),
    ]
    return interiors, list(
        interior_module.shared_parts(interiors, [bw.BALLOON_A_POLYGON, bw.INNER_BOX_POLYGON], SHAPE)
    )


def test_a_balloon_holding_a_box_gives_up_the_part_nearer_the_box_and_the_box_is_unchanged() -> (
    None
):
    interiors, parts = _box_inside_case()
    # C-5's givens: B's centre is in A's interior, A's centre is not in B.
    assert _holds(_fill(interiors[0]), bw.polygon_centre(bw.INNER_BOX_POLYGON))
    assert not _holds(_fill(interiors[1]), bw.polygon_centre(bw.BALLOON_A_POLYGON))

    a_part = _fill(parts[0])
    assert parts[0] != interiors[0], "A was set in its whole interior, over the box"
    held = int((a_part & _fill(bw.INNER_BOX_POLYGON)).sum())
    assert held == 0, f"A's part still holds {held} px of the box's polygon"
    assert parts[1] == bw.INNER_BOX_POLYGON, "the box's ring is its polygon, unchanged"


def test_the_part_a_balloon_keeps_beside_a_box_is_nearer_its_own_polygon() -> None:
    _, parts = _box_inside_case()
    a_part = _fill(parts[0])
    to_a = bw.rect_distance(bw.BALLOON_A_POLYGON, SHAPE)
    to_b = bw.rect_distance(bw.INNER_BOX_POLYGON, SHAPE)

    wrong = int((a_part & (to_a > to_b + 1)).sum())
    assert wrong == 0, f"{wrong} px of A's part are nearer the box than A's own polygon"
    inside = int((a_part & ~bw.bubble_page().interior).sum())
    assert inside == 0, f"A's part reaches {inside} px past the balloon's interior"
    assert not (_fill(bw.BALLOON_A_POLYGON) & ~a_part).any(), "A's part lost A's own polygon"
