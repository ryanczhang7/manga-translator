"""`mangatl.bench.matching`: the rasteriser, the IoU and the one-to-one matcher.

MT-029 `## Contract` block 1. Nothing here is an acceptance criterion on its own;
it is the instrument AC-4 is defined against (a pair of truth regions is
ambiguous exactly when *this* matcher could pair a proposal with either), and
the instrument MT-022 and MT-023 import. So the threshold is pinned to its
value, and the matcher's order, tie-break and greedy rule are pinned to the
cases where a plausible wrong implementation gives a different answer.

**How the expected pixel counts were computed.** A truth polygon is rasterised
by Pillow's `ImageDraw.polygon(fill=1)`, which for an axis-aligned rectangle
with corners `(x0, y0)` and `(x1, y1)` sets the **inclusive** range
`x0..x1, y0..y1` - `(x1 - x0 + 1) * (y1 - y0 + 1)` pixels. That was measured in
RED on Pillow 12.3.0 outside the test framework (MT-029 `## Handoff`), and the
first test below pins it. A proposal mask comes from `one_bit_png`, whose
rectangles are **half-open**. Every IoU in this file is exact rectangle
arithmetic over those two conventions, written out beside the fixture.

`TruthRegion` is imported from `mangatl.bench.truth` because `match_regions`
takes truth regions; this file imports `matching` first, so in RED it fails at
collection naming `mangatl.bench.matching`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import FrozenInstanceError, fields

import numpy as np
import pytest

from mangatl.bench.matching import (
    IOU_MATCH_THRESHOLD,
    Match,
    decode_mask,
    iou,
    match_regions,
    polygon_mask,
)
from mangatl.bench.truth import TruthRegion
from mangatl.domain.region import RawRegion

OneBitPng = Callable[[int, int, Sequence[tuple[int, int, int, int]]], bytes]

# Every match_regions case runs on one small page, so every mask is cheap.
_W, _H = 40, 10


def _truth(index: int, x0: int, y0: int, x1: int, y1: int) -> TruthRegion:
    """A truth rectangle with INCLUSIVE corners, as Pillow rasterises it."""
    return TruthRegion(
        page_ordinal=0,
        index=index,
        polygon=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
        kind="bubble",
        source="human",
        note="",
    )


def _proposal(one_bit_png: OneBitPng, rects: Sequence[tuple[int, int, int, int]]) -> RawRegion:
    """A detector region whose mask is the HALF-OPEN `rects` over the page.

    Its polygon is a closed ring that deliberately describes nothing like the
    mask: `match_regions` reads masks, never proposal polygons (block 1), so a
    matcher that read this polygon would get every case below wrong.
    """
    return RawRegion(
        polygon=((0, 0), (1, 0), (1, 1), (0, 0)),
        mask=one_bit_png(_W, _H, rects),
        confidence=0.9,
        kind="bubble",
    )


# -- the threshold ------------------------------------------------------------


def test_the_matching_threshold_is_one_half() -> None:
    assert IOU_MATCH_THRESHOLD == 0.5


# -- polygon_mask -------------------------------------------------------------


def test_a_rectangle_rasterises_to_its_inclusive_pixel_range_as_a_height_by_width_bool_array() -> (
    None
):
    mask = polygon_mask(((2, 1), (5, 1), (5, 3), (2, 3)), 8, 6)

    expected = np.zeros((6, 8), dtype=bool)
    expected[1:4, 2:6] = True
    assert mask.shape == (6, 8)
    assert mask.dtype == np.bool_
    assert np.array_equal(mask, expected)
    assert int(mask.sum()) == 12


def test_an_open_vertex_list_is_closed_implicitly_so_a_triangle_is_filled() -> None:
    """The first vertex is NOT repeated (AC-1, PO-1); the last joins the first."""
    mask = polygon_mask(((0, 0), (4, 0), (0, 4)), 6, 6)

    expected = np.zeros((6, 6), dtype=bool)
    for y in range(5):
        expected[y, 0 : 5 - y] = True
    assert np.array_equal(mask, expected)


def test_a_polygon_running_off_the_page_is_clipped_to_it_and_keeps_the_page_shape() -> None:
    mask = polygon_mask(((5, 4), (10, 4), (10, 10), (5, 10)), 8, 6)

    expected = np.zeros((6, 8), dtype=bool)
    expected[4:6, 5:8] = True
    assert mask.shape == (6, 8)
    assert np.array_equal(mask, expected)


# -- decode_mask --------------------------------------------------------------


def test_a_one_bit_png_mask_decodes_to_exactly_the_rectangles_it_was_drawn_with(
    one_bit_png: OneBitPng,
) -> None:
    decoded = decode_mask(one_bit_png(8, 6, [(1, 1, 4, 3), (6, 4, 8, 6)]))

    expected = np.zeros((6, 8), dtype=bool)
    expected[1:3, 1:4] = True
    expected[4:6, 6:8] = True
    assert decoded.shape == (6, 8)
    assert decoded.dtype == np.bool_
    assert np.array_equal(decoded, expected)


def test_an_empty_one_bit_png_mask_decodes_to_all_false(one_bit_png: OneBitPng) -> None:
    decoded = decode_mask(one_bit_png(5, 3, []))

    assert decoded.shape == (3, 5)
    assert not decoded.any()


# -- iou ----------------------------------------------------------------------


def _box(height: int, width: int, rows: slice, cols: slice) -> np.ndarray:
    array = np.zeros((height, width), dtype=bool)
    array[rows, cols] = True
    return array


def test_identical_masks_have_an_iou_of_exactly_one() -> None:
    a = _box(4, 6, slice(0, 2), slice(0, 4))
    assert iou(a, a.copy()) == 1.0


def test_disjoint_masks_have_an_iou_of_exactly_zero() -> None:
    a = _box(4, 6, slice(0, 2), slice(0, 2))
    b = _box(4, 6, slice(2, 4), slice(3, 6))
    assert iou(a, b) == 0.0


def test_two_empty_masks_have_an_iou_of_zero_rather_than_dividing_by_zero() -> None:
    empty = np.zeros((4, 6), dtype=bool)
    assert iou(empty, empty.copy()) == 0.0


def test_iou_is_the_intersection_over_the_union() -> None:
    # 2x4 and 2x4 sharing a 2x2 square: 4 / (8 + 8 - 4) = 4 / 12.
    a = _box(4, 6, slice(0, 2), slice(0, 4))
    b = _box(4, 6, slice(0, 2), slice(2, 6))
    assert iou(a, b) == 4 / 12
    assert iou(b, a) == 4 / 12


def test_masks_of_different_shapes_are_refused_with_a_value_error() -> None:
    with pytest.raises(ValueError):
        iou(np.zeros((4, 6), dtype=bool), np.zeros((6, 4), dtype=bool))


# -- Match --------------------------------------------------------------------


def test_a_match_is_a_frozen_record_of_truth_index_region_id_and_iou() -> None:
    match = Match(truth_index=0, region_id=None, iou=0.0)

    assert [field.name for field in fields(Match)] == ["truth_index", "region_id", "iou"]
    with pytest.raises(FrozenInstanceError):
        match.iou = 1.0  # type: ignore[misc]


# -- match_regions ------------------------------------------------------------


def test_a_pair_at_exactly_the_threshold_matches(one_bit_png: OneBitPng) -> None:
    # Truth: columns 0..9, rows 0..9 inclusive = 100 px. Proposal: [0,10) x [0,5)
    # = 50 px inside it. IoU = 50 / 100 = 0.5, and the comparison is >=.
    truth = [_truth(0, 0, 0, 9, 9)]
    proposals = [_proposal(one_bit_png, [(0, 0, 10, 5)])]

    result = match_regions(proposals, truth, width=_W, height=_H)

    assert result == [Match(truth_index=0, region_id=0, iou=0.5)]


def test_a_pair_just_below_the_threshold_does_not_match_and_both_sides_are_reported(
    one_bit_png: OneBitPng,
) -> None:
    # Proposal: [0,10) x [0,4) plus [0,9) x [4,5) = 40 + 9 = 49 px inside a
    # 100 px truth. IoU = 49 / 100 = 0.49 < 0.5.
    truth = [_truth(0, 0, 0, 9, 9)]
    proposals = [_proposal(one_bit_png, [(0, 0, 10, 4), (0, 4, 9, 5)])]

    result = match_regions(proposals, truth, width=_W, height=_H)

    assert result == [
        Match(truth_index=0, region_id=None, iou=0.0),
        Match(truth_index=None, region_id=0, iou=0.0),
    ]


def test_results_list_every_truth_in_truth_order_then_unmatched_proposals_in_proposal_order(
    one_bit_png: OneBitPng,
) -> None:
    # Truth 0 = columns 0..9, truth 1 = columns 20..29 (full height, 100 px each).
    # Proposal 0 is spurious (columns 35..37), proposal 1 is exactly truth 1,
    # proposal 2 is exactly truth 0, proposal 3 is spurious (columns 12..14).
    truth = [_truth(0, 0, 0, 9, 9), _truth(1, 20, 0, 29, 9)]
    proposals = [
        _proposal(one_bit_png, [(35, 0, 38, 10)]),
        _proposal(one_bit_png, [(20, 0, 30, 10)]),
        _proposal(one_bit_png, [(0, 0, 10, 10)]),
        _proposal(one_bit_png, [(12, 0, 15, 10)]),
    ]

    result = match_regions(proposals, truth, width=_W, height=_H)

    assert result == [
        Match(truth_index=0, region_id=2, iou=1.0),
        Match(truth_index=1, region_id=1, iou=1.0),
        Match(truth_index=None, region_id=0, iou=0.0),
        Match(truth_index=None, region_id=3, iou=0.0),
    ]
    assert len(result) == len(truth) + 2


def test_one_proposal_over_two_truths_goes_to_the_higher_iou_and_the_other_truth_is_missed(
    one_bit_png: OneBitPng,
) -> None:
    # Truth 0 = columns 0..14 (150 px), truth 1 = columns 0..9 (100 px).
    # Proposal = [0,9) full height = 90 px, inside both.
    #   IoU with truth 0 = 90 / 150 = 0.6   (above threshold)
    #   IoU with truth 1 = 90 / 100 = 0.9   (higher - greedy takes this one)
    # A matcher that walks truths in order and gives each its best free proposal
    # would pair truth 0 at 0.6 and miss truth 1 instead.
    truth = [_truth(0, 0, 0, 14, 9), _truth(1, 0, 0, 9, 9)]
    proposals = [_proposal(one_bit_png, [(0, 0, 9, 10)])]

    result = match_regions(proposals, truth, width=_W, height=_H)

    assert result == [
        Match(truth_index=0, region_id=None, iou=0.0),
        Match(truth_index=1, region_id=0, iou=0.9),
    ]


def test_two_proposals_each_close_to_both_truths_are_paired_one_to_one(
    one_bit_png: OneBitPng,
) -> None:
    # Truth 0 = columns 0..9 (100 px), truth 1 = columns 0..14 (150 px).
    # Proposal 0 = [0,10) (100 px): IoU 1.0 with truth 0, 100/150 with truth 1.
    # Proposal 1 = [0,15) (150 px): IoU 100/150 with truth 0, 1.0 with truth 1.
    # Descending IoU pairs (p0, t0) and (p1, t1) at 1.0 each. A matcher that
    # walks proposals in order and gives each its best free truth gets the same
    # answer here, so the case that separates them is the one above; this one
    # pins that a proposal is never matched twice and a truth never twice.
    truth = [_truth(0, 0, 0, 9, 9), _truth(1, 0, 0, 14, 9)]
    proposals = [
        _proposal(one_bit_png, [(0, 0, 10, 10)]),
        _proposal(one_bit_png, [(0, 0, 15, 10)]),
    ]

    result = match_regions(proposals, truth, width=_W, height=_H)

    assert result == [
        Match(truth_index=0, region_id=0, iou=1.0),
        Match(truth_index=1, region_id=1, iou=1.0),
    ]


def test_two_proposals_tied_on_one_truth_resolve_to_the_earlier_proposal(
    one_bit_png: OneBitPng,
) -> None:
    truth = [_truth(0, 0, 0, 9, 9)]
    proposals = [
        _proposal(one_bit_png, [(0, 0, 10, 10)]),
        _proposal(one_bit_png, [(0, 0, 10, 10)]),
    ]

    result = match_regions(proposals, truth, width=_W, height=_H)

    assert result == [
        Match(truth_index=0, region_id=0, iou=1.0),
        Match(truth_index=None, region_id=1, iou=0.0),
    ]


def test_one_proposal_tied_on_two_truths_resolves_to_the_earlier_truth(
    one_bit_png: OneBitPng,
) -> None:
    truth = [_truth(0, 0, 0, 9, 9), _truth(1, 0, 0, 9, 9)]
    proposals = [_proposal(one_bit_png, [(0, 0, 10, 10)])]

    result = match_regions(proposals, truth, width=_W, height=_H)

    assert result == [
        Match(truth_index=0, region_id=0, iou=1.0),
        Match(truth_index=1, region_id=None, iou=0.0),
    ]


def test_no_proposals_and_no_truth_give_no_matches() -> None:
    assert match_regions([], [], width=_W, height=_H) == []


def test_with_no_proposals_every_truth_region_is_missed() -> None:
    truth = [_truth(0, 0, 0, 9, 9), _truth(1, 20, 0, 29, 9)]

    assert match_regions([], truth, width=_W, height=_H) == [
        Match(truth_index=0, region_id=None, iou=0.0),
        Match(truth_index=1, region_id=None, iou=0.0),
    ]


def test_with_no_truth_every_proposal_is_spurious(one_bit_png: OneBitPng) -> None:
    proposals = [
        _proposal(one_bit_png, [(0, 0, 10, 10)]),
        _proposal(one_bit_png, [(20, 0, 30, 10)]),
    ]

    assert match_regions(proposals, [], width=_W, height=_H) == [
        Match(truth_index=None, region_id=0, iou=0.0),
        Match(truth_index=None, region_id=1, iou=0.0),
    ]


def test_the_page_size_is_keyword_only_so_width_and_height_cannot_be_swapped_by_position() -> None:
    with pytest.raises(TypeError):
        match_regions([], [], _W, _H)  # type: ignore[misc]
