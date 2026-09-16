"""`mangatl.detect.columns`: adjacent columns of one utterance become one region.

Covers AC-1 to AC-7 of MT-008, which the story's oracle partition classes as
**mechanical**: every fixture here is built by hand, so the right answer is
arithmetic on rectangles rather than a judgement about a page. AC-8 is
oracle-free and lives in `tests/integration/test_column_merge_pages.py`; AC-9 is
a round trip and lives in `tests/core/test_region_store_merged_from.py`; the
`merged_from` field itself is pinned in `tests/core/test_region_merged_from.py`.

**The conventions every number here depends on** (C-1, sharpened by RED because
a rule stated to the pixel cannot be tested at its boundary otherwise):

- A region's *extent* is the **half-open** bounding box of its set mask pixels,
  `(x0, y0, x1, y1)` covering `x0 <= x < x1` and `y0 <= y < y1` - the same
  half-open rule `regions_from_detection` uses for box membership (MT-007
  amendment A-6). For everything that function emits the extent is also the
  bounding box of the polygon, because `_polygon` is the contour of those same
  pixels; every fixture below is built so that the two agree.
- With `axis="vertical"` the **gap** is the number of empty pixel COLUMNS
  strictly between the two extents, `max(0, max(ax0, bx0) - min(ax1, bx1))`, and
  the **overlap** is the number of shared pixel ROWS as a fraction of the
  *shorter* region's height. `axis="horizontal"` transposes both.
- Extents that touch, and extents that overlap, both have gap 0.

**Why the boundary cases are written against the constants rather than against
numbers.** C-4 measured the bounds and GREEN picks the values inside them, so a
case written at `COLUMN_MAX_GAP_PX + 1` is still a boundary case whatever GREEN
picks, while a case written at `55` would quietly stop being one.

**`_MEASURED_PAIRS` is real geometry, transcribed.** Every same-box region pair
the shipped `regions_from_detection` produces on `011/012/014.jpg` - the seven
of C-4's table, with C-4's MERGE/KEEP column as the expectation. The extents,
the fences and the page size are the real ones, re-measured in MT-008 RED on
`CUDAExecutionProvider` (see the story's `## Handoff`); only the masks are
synthetic, because this rule reads extents and running the model in `tests/core`
is exactly what the oracle partition forbids.

**One transcription correction, recorded rather than silently applied.** C-4's
`gapx`/`ovl_y`/`frac` columns were measured with *inclusive* bounding-box
endpoints, so each of its gaps is one larger, each of its overlaps one smaller
and each of its widths one smaller than the half-open numbers used here. The
MERGE/KEEP decision, the 6.1x and 3.2x separations and the admissible band for
each constant are unchanged by that - `9 <= gap <= 54` inclusive is the same set
of pixel distances as `8 <= gap <= 53` half-open. See the story's `## Handoff`
for the pair-by-pair comparison.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from io import BytesIO

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.detect.columns import COLUMN_MAX_GAP_PX, COLUMN_MIN_OVERLAP, merge_columns
from mangatl.detect.postprocess import integer_boxes
from mangatl.domain.region import RawRegion

#: The synthetic page the vertical cases are drawn on, and its transpose for the
#: horizontal ones. Both are tall enough for a 500px extent, which is what the
#: overlap boundary needs to land exactly on a threshold C-4 bounds below 1.0.
_PAGE = (240, 1000)
_WIDE = (1000, 240)

#: The real scans C-4 was measured on.
_REAL = (1125, 1600)

_COL_W = 40
_LEFT_X = 40
_TOP_Y = 60
_ROW_H = 40
_LONG = 500

Rect = tuple[int, int, int, int]


# -- building regions ----------------------------------------------------------


def _rect_region(
    one_bit_png: Callable[..., bytes],
    page: tuple[int, int],
    rect: Rect,
    confidence: float = 0.5,
    kind: str = "bubble",
) -> RawRegion:
    """One rectangular region: its mask is `rect`, its polygon traces `rect`."""
    x0, y0, x1, y1 = rect
    return RawRegion(
        polygon=((x0, y0), (x1 - 1, y0), (x1 - 1, y1 - 1), (x0, y1 - 1), (x0, y0)),
        mask=one_bit_png(page[0], page[1], [rect]),
        confidence=confidence,
        kind=kind,  # type: ignore[arg-type]
    )


def _column_pair(
    one_bit_png: Callable[..., bytes],
    *,
    gap: int,
    overlap: int,
    height_a: int = 200,
    height_b: int = 200,
) -> tuple[RawRegion, RawRegion]:
    """Two vertical columns with exactly `gap` empty columns between them and
    `overlap` rows in common."""
    ax1 = _LEFT_X + _COL_W
    ay1 = _TOP_Y + height_a
    by0 = ay1 - overlap
    return (
        _rect_region(one_bit_png, _PAGE, (_LEFT_X, _TOP_Y, ax1, ay1)),
        _rect_region(one_bit_png, _PAGE, (ax1 + gap, by0, ax1 + gap + _COL_W, by0 + height_b)),
    )


def _row_pair(
    one_bit_png: Callable[..., bytes],
    *,
    gap: int,
    overlap: int,
    length_a: int = 200,
    length_b: int = 200,
) -> tuple[RawRegion, RawRegion]:
    """`_column_pair` transposed: two horizontal rows, `gap` empty ROWS between
    them and `overlap` COLUMNS in common."""
    ax1 = _LEFT_X + length_a
    ay1 = _TOP_Y + _ROW_H
    bx0 = ax1 - overlap
    return (
        _rect_region(one_bit_png, _WIDE, (_LEFT_X, _TOP_Y, ax1, ay1)),
        _rect_region(one_bit_png, _WIDE, (bx0, ay1 + gap, bx0 + length_b, ay1 + gap + _ROW_H)),
    )


# -- reading regions back ------------------------------------------------------


def _mask(region: RawRegion) -> NDArray[np.bool_]:
    """The region's mask decoded by PIL rather than by us - an independent
    observer, for the reason `tdd-cycle` gives: an encoder that is uniformly
    wrong decodes perfectly through its own inverse."""
    with Image.open(BytesIO(region.mask)) as image:
        assert image.mode == "1", f"mask is {image.mode}, not a 1-bit image"
        return np.array(image, dtype=bool)


def _set_pixels(region: RawRegion) -> set[tuple[int, int]]:
    ys, xs = np.nonzero(_mask(region))
    return {(int(x), int(y)) for x, y in zip(xs, ys, strict=True)}


def _mask_bbox(region: RawRegion) -> Rect:
    ys, xs = np.nonzero(_mask(region))
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _polygon_bbox(region: RawRegion) -> Rect:
    xs = [x for x, _y in region.polygon]
    ys = [y for _x, y in region.polygon]
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _png_header(region: RawRegion) -> tuple[int, int, int, int]:
    """`(width, height, bit_depth, colour_type)` straight out of IHDR."""
    length, tag = struct.unpack(">I4s", region.mask[8:16])
    assert tag == b"IHDR" and length == 13
    width, height, depth, colour = struct.unpack(">IIBB", region.mask[16:26])
    return int(width), int(height), int(depth), int(colour)


def _union(*boxes: Rect) -> Rect:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _fence_around(*regions: RawRegion, margin: int = 10) -> Rect:
    x0, y0, x1, y1 = _union(*(_polygon_bbox(region) for region in regions))
    return (x0 - margin, y0 - margin, x1 + margin, y1 + margin)


def _rows_at_least(height: int) -> int:
    """The smallest shared-row count that reaches `COLUMN_MIN_OVERLAP` at
    `height`, and therefore the boundary case *at* the threshold."""
    for rows in range(height + 1):
        if rows / height >= COLUMN_MIN_OVERLAP:
            return rows
    raise AssertionError(
        f"COLUMN_MIN_OVERLAP is {COLUMN_MIN_OVERLAP}, which no overlap of a"
        f" {height}px extent can reach; C-4 bounds it at or below 1.0"
    )


def _kept_apart(result: list[RawRegion], first: RawRegion, second: RawRegion) -> None:
    """Both regions came through, neither recording a merge."""
    assert len(result) == 2, f"expected two regions, got {len(result)}"
    assert [region.merged_from for region in result] == [(), ()]
    assert {_mask_bbox(region) for region in result} == {_mask_bbox(first), _mask_bbox(second)}


# -- AC-1: two columns of one utterance become one region ----------------------


def test_two_columns_in_one_fence_box_become_one_region_covering_both(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1. One region out, its polygon spanning both inputs, `merged_from`
    naming both input indices."""
    first, second = _column_pair(one_bit_png, gap=1, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)])

    assert len(result) == 1
    assert result[0].merged_from == (0, 1)
    both = _union(_polygon_bbox(first), _polygon_bbox(second))
    assert _polygon_bbox(result[0]) == both
    assert _mask_bbox(result[0]) == both


@pytest.mark.parametrize("gap", [0, 1])
def test_columns_that_touch_or_nearly_touch_merge(
    gap: int, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-1, the small end. Gap 0 is two extents sharing an edge; gap 1 is the
    `012` box 1 and box 3 case measured on the real scans."""
    first, second = _column_pair(one_bit_png, gap=gap, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)])

    assert len(result) == 1
    assert result[0].merged_from == (0, 1)


@pytest.mark.parametrize("delta", [-1, 0])
def test_a_gap_at_or_below_the_maximum_merges(
    delta: int, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-1's boundary, on the legal side: *at most* `COLUMN_MAX_GAP_PX`, so the
    threshold value itself merges and so does one pixel inside it."""
    first, second = _column_pair(one_bit_png, gap=COLUMN_MAX_GAP_PX + delta, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)])

    assert len(result) == 1, f"gap {COLUMN_MAX_GAP_PX + delta} <= {COLUMN_MAX_GAP_PX} must merge"
    assert result[0].merged_from == (0, 1)


def test_an_overlap_exactly_at_the_minimum_merges(one_bit_png: Callable[..., bytes]) -> None:
    """AC-1's other boundary, on the legal side: *at least* `COLUMN_MIN_OVERLAP`
    of the shorter extent."""
    rows = _rows_at_least(_LONG)
    first, second = _column_pair(one_bit_png, gap=0, overlap=rows, height_a=_LONG, height_b=_LONG)

    result = merge_columns([first, second], [_fence_around(first, second)])

    assert len(result) == 1, (
        f"{rows}/{_LONG} = {rows / _LONG} is at or above COLUMN_MIN_OVERLAP"
        f" = {COLUMN_MIN_OVERLAP} and must merge"
    )
    assert result[0].merged_from == (0, 1)


def test_the_overlap_is_a_fraction_of_the_shorter_extent_not_the_longer(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1. A short column wholly inside a long one overlaps it completely -
    the `014` box 5 case, where a 54px extent sits beside a 97px one. Measured
    against the LONGER extent the same pair scores 0.1, below every value C-4
    admits, so this discriminates whatever constant GREEN chooses."""
    short = 50
    first, second = _column_pair(one_bit_png, gap=1, overlap=short, height_a=_LONG, height_b=short)

    result = merge_columns([first, second], [_fence_around(first, second)])

    assert len(result) == 1, (
        f"the shorter extent is {short}px and all of it overlaps, which is 1.0;"
        f" against the longer it is {short / _LONG}, which is not the rule"
    )
    assert result[0].merged_from == (0, 1)


# -- AC-2: too little overlap keeps them apart, however small the gap ----------


def test_an_overlap_one_row_below_the_minimum_keeps_two_regions(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-2's boundary, on the illegal side, with the gap at **zero** so that
    only the overlap clause can reject it. This is the assertion C-5 predicts
    fails when the overlap clause is dropped and survives when the gap clause
    is."""
    rows = _rows_at_least(_LONG) - 1
    first, second = _column_pair(one_bit_png, gap=0, overlap=rows, height_a=_LONG, height_b=_LONG)

    result = merge_columns([first, second], [_fence_around(first, second)])

    _kept_apart(result, first, second)


def test_two_bubbles_that_barely_overlap_are_not_merged_however_small_the_gap(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-2 in the shape the corpus found it: `011` box 4 fences two separate
    bubbles 3px apart whose extents share less than a third of the shorter one.
    A rule that read the gap alone would make two utterances into one."""
    first, second = _column_pair(one_bit_png, gap=1, overlap=50, height_a=205, height_b=157)

    result = merge_columns([first, second], [_fence_around(first, second)])

    _kept_apart(result, first, second)


# -- AC-3: too large a gap keeps them apart, however complete the overlap ------


def test_a_gap_one_pixel_above_the_maximum_keeps_two_regions(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-3's boundary, on the illegal side, with the overlap **complete** so
    that only the gap clause can reject it. This is the assertion C-5 predicts
    fails when the gap clause is dropped and survives when the overlap clause
    is."""
    first, second = _column_pair(one_bit_png, gap=COLUMN_MAX_GAP_PX + 1, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)])

    _kept_apart(result, first, second)


def test_a_separate_bubble_across_the_box_is_not_merged_however_complete_the_overlap(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-3 in the shape the corpus found it: the separate bubble of `011` box 7
    sits 54px from its neighbour and overlaps it completely."""
    first, second = _column_pair(one_bit_png, gap=54, overlap=68, height_a=174, height_b=68)

    result = merge_columns([first, second], [_fence_around(first, second)])

    _kept_apart(result, first, second)


# -- AC-1 to AC-3 against the seven real pairs ---------------------------------

#: `(label, fence, extent A, extent B, gap, shared rows, frac, merges)` for every
#: same-box region pair the shipped detector produces on `011/012/014.jpg`.
#: Extents and fences are half-open page pixels on a 1125x1600 scan. The
#: MERGE/KEEP column is C-4's; see this module's docstring for the one-pixel
#: convention correction between C-4's printed numbers and these.
_MEASURED_PAIRS: tuple[tuple[str, Rect, Rect, Rect, int, int, float, bool], ...] = (
    (
        "011-box3 tokoroga / gyakuni",
        (435, 1146, 518, 1283),
        (435, 1146, 478, 1219),
        (480, 1146, 518, 1283),
        2,
        73,
        1.000,
        True,
    ),
    (
        "011-box4 two separate bubbles",
        (49, 720, 369, 1032),
        (234, 720, 369, 925),
        (49, 875, 231, 1032),
        3,
        50,
        0.318,
        False,
    ),
    (
        "011-box7 a separate bubble",
        (591, 1378, 739, 1552),
        (591, 1378, 657, 1552),
        (711, 1444, 739, 1512),
        54,
        68,
        1.000,
        False,
    ),
    (
        "012-box1 kami wa sono chikara wo / mitometa",
        (973, 773, 1065, 1007),
        (973, 773, 1020, 894),
        (1021, 773, 1065, 1007),
        1,
        121,
        1.000,
        True,
    ),
    (
        "012-box2 dakara / kousan suru",
        (129, 1180, 241, 1363),
        (129, 1180, 184, 1363),
        (192, 1180, 241, 1323),
        8,
        143,
        1.000,
        True,
    ),
    (
        "012-box3 sugoi yo / jinrui",
        (974, 501, 1071, 618),
        (974, 501, 1023, 586),
        (1024, 501, 1071, 618),
        1,
        85,
        1.000,
        True,
    ),
    (
        "014-box5 tenten / naruhodo",
        (232, 549, 285, 646),
        (232, 549, 261, 646),
        (269, 549, 285, 603),
        8,
        54,
        1.000,
        True,
    ),
)


@pytest.mark.parametrize(
    ("label", "fence", "extent_a", "extent_b", "gap", "rows", "frac", "merges"),
    _MEASURED_PAIRS,
    ids=[pair[0].split()[0] for pair in _MEASURED_PAIRS],
)
def test_the_rule_agrees_with_every_same_box_pair_the_detector_really_produces(
    label: str,
    fence: Rect,
    extent_a: Rect,
    extent_b: Rect,
    gap: int,
    rows: int,
    frac: float,
    merges: bool,
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1, AC-2 and AC-3 against the geometry the real detector produced.

    The first three assertions re-derive `gap`, `rows` and `frac` from the
    transcribed extents, so a typo in the table above is reported as a typo
    rather than as a broken rule.
    """
    assert max(0, max(extent_a[0], extent_b[0]) - min(extent_a[2], extent_b[2])) == gap
    shared = max(0, min(extent_a[3], extent_b[3]) - max(extent_a[1], extent_b[1]))
    shorter = min(extent_a[3] - extent_a[1], extent_b[3] - extent_b[1])
    assert shared == rows
    assert shared / shorter == pytest.approx(frac, abs=5e-4)

    first = _rect_region(one_bit_png, _REAL, extent_a)
    second = _rect_region(one_bit_png, _REAL, extent_b)

    result = merge_columns([first, second], [fence])

    if merges:
        assert len(result) == 1, f"{label}: gap {gap}, overlap {frac} is one utterance"
        assert result[0].merged_from == (0, 1)
    else:
        assert len(result) == 2, f"{label}: gap {gap}, overlap {frac} is two utterances"
        assert [region.merged_from for region in result] == [(), ()]


def test_both_constants_sit_inside_the_bounds_the_corpus_measured() -> None:
    """C-4's bounds, in this file's half-open convention. Below 8 the `012` box 2
    and `014` box 5 merges are lost; at 54 or above the separate bubble of `011`
    box 7 is absorbed; at or below 50/157 the two bubbles of `011` box 4 become
    one utterance."""
    assert 8 <= COLUMN_MAX_GAP_PX <= 53
    assert 50 / 157 < COLUMN_MIN_OVERLAP <= 1.0


# -- AC-4: the fence box is part of the rule -----------------------------------


def test_two_columns_in_different_fence_boxes_are_not_merged(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-4. The geometry says merge and the box head says two text blocks; the
    box head wins. Every one of the 30 regions on the corpus falls inside exactly
    one box, so two boxes is the detector's own judgement that these are
    different blocks (PO-1 finding 3)."""
    first, second = _column_pair(one_bit_png, gap=0, overlap=200)

    result = merge_columns([first, second], [_polygon_bbox(first), _polygon_bbox(second)])

    _kept_apart(result, first, second)


def test_the_same_two_columns_under_one_fence_box_do_merge(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-4's control. Without it the test above would pass against an
    implementation that merges nothing at all."""
    first, second = _column_pair(one_bit_png, gap=0, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)])

    assert len(result) == 1
    assert result[0].merged_from == (0, 1)


# -- AC-5: a region in no fence box is left exactly as it was -------------------


def test_a_region_in_no_fence_box_survives_unmerged_and_unmodified(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-5. `RawRegion` is a frozen value, so equality is the whole assertion:
    same polygon, same mask bytes, same confidence, same kind, and `merged_from`
    still empty."""
    first, second = _column_pair(one_bit_png, gap=1, overlap=200)
    lone = _rect_region(one_bit_png, _PAGE, (160, 700, 200, 900), confidence=0.75, kind="box")

    result = merge_columns([first, second, lone], [_fence_around(first, second)])

    assert len(result) == 2
    assert lone in result, "the unfenced region came back changed"


def test_every_region_survives_when_there_are_no_fence_boxes_at_all(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-5, the zero case: a page whose box head accepted nothing merges
    nothing, rather than treating the whole page as one fence."""
    first, second = _column_pair(one_bit_png, gap=0, overlap=200)

    result = merge_columns([first, second], [])

    _kept_apart(result, first, second)


def test_no_regions_produce_no_regions(one_bit_png: Callable[..., bytes]) -> None:
    """The empty case. A page the detector finds nothing on is a real path -
    `write_regions(n, ())` exists for it (MT-007 A-11) - so it reaches here."""
    first, second = _column_pair(one_bit_png, gap=0, overlap=200)

    assert merge_columns([], [_fence_around(first, second)]) == []


def test_one_region_alone_in_its_fence_box_comes_back_unmerged(
    one_bit_png: Callable[..., bytes],
) -> None:
    """The one case: 18 of the 25 boxes on the corpus fence exactly one region."""
    lone = _rect_region(one_bit_png, _PAGE, (60, 100, 100, 300))

    result = merge_columns([lone], [_fence_around(lone)])

    assert result == [lone]
    assert result[0].merged_from == ()


# -- AC-6: the merged mask and the merged confidence ---------------------------


def test_a_merged_mask_is_the_union_of_the_merged_masks_and_nothing_else(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-6. Pixel-exact, so an implementation that filled the gap between the
    columns - or that returned the union's bounding rectangle - fails here. The
    gap pixels are named separately because filling them is the plausible
    mistake."""
    first, second = _column_pair(one_bit_png, gap=COLUMN_MAX_GAP_PX, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)])

    assert len(result) == 1
    assert _set_pixels(result[0]) == _set_pixels(first) | _set_pixels(second)
    between = {
        (x, y)
        for x in range(_LEFT_X + _COL_W, _LEFT_X + _COL_W + COLUMN_MAX_GAP_PX)
        for y in range(_TOP_Y, _TOP_Y + 200)
    }
    assert between and not (_set_pixels(result[0]) & between)
    assert _png_header(result[0]) == (_PAGE[0], _PAGE[1], 1, 0)


def test_a_merged_confidence_is_the_mean_weighted_by_the_masks_own_pixel_counts(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-6's second clause. `confidence` is the mean probability inside the mask
    (MT-007 C-7), so the mean over the union is the two means weighted by how
    many pixels each contributed: 2000 at 0.8 and 1000 at 0.3 is 0.6333.

    The first fixture is L-shaped on purpose. Its mask covers 2000 pixels inside
    a 2400-pixel bounding box, so weighting by bounding-box area would give
    0.65294 and an unweighted mean would give 0.55. All three are distinct, and
    only one of them is the mean over the union.
    """
    upper, foot = (100, 100, 140, 140), (100, 140, 120, 160)
    first = RawRegion(
        polygon=(
            (100, 100),
            (139, 100),
            (139, 139),
            (119, 139),
            (119, 159),
            (100, 159),
            (100, 100),
        ),
        mask=one_bit_png(_PAGE[0], _PAGE[1], [upper, foot]),
        confidence=0.8,
        kind="bubble",
    )
    second = _rect_region(one_bit_png, _PAGE, (141, 100, 161, 150), confidence=0.3)
    assert len(_set_pixels(first)) == 2000
    assert len(_set_pixels(second)) == 1000

    result = merge_columns([first, second], [_fence_around(first, second)])

    assert len(result) == 1
    assert result[0].confidence == pytest.approx((0.8 * 2000 + 0.3 * 1000) / 3000)


def test_a_merged_region_takes_the_kind_of_its_lowest_indexed_input(
    one_bit_png: Callable[..., bytes],
) -> None:
    """C-1. In the pipeline the question never arises - `kind` comes from the
    fencing box and columns of one box share it - but the function must still
    answer it, and a deterministic answer is what stops two runs disagreeing."""
    first, second = _column_pair(one_bit_png, gap=1, overlap=200)
    as_box = _rect_region(one_bit_png, _PAGE, _polygon_bbox(first), kind="box")

    result = merge_columns([as_box, second], [_fence_around(first, second)])

    assert len(result) == 1
    assert result[0].kind == "box"


# -- AC-7: axis="horizontal" transposes every rule -----------------------------


def test_two_rows_a_gap_apart_merge_on_the_horizontal_axis(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-7. The gap is measured vertically now, and the overlap horizontally."""
    first, second = _row_pair(one_bit_png, gap=COLUMN_MAX_GAP_PX, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)], axis="horizontal")

    assert len(result) == 1
    assert result[0].merged_from == (0, 1)


def test_two_rows_further_apart_than_the_maximum_gap_stay_apart_on_the_horizontal_axis(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-7, AC-3 transposed."""
    first, second = _row_pair(one_bit_png, gap=COLUMN_MAX_GAP_PX + 1, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)], axis="horizontal")

    _kept_apart(result, first, second)


def test_two_rows_overlapping_too_little_stay_apart_on_the_horizontal_axis(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-7, AC-2 transposed: the overlap is measured along `x` here."""
    columns = _rows_at_least(_LONG) - 1
    first, second = _row_pair(one_bit_png, gap=0, overlap=columns, length_a=_LONG, length_b=_LONG)

    result = merge_columns([first, second], [_fence_around(first, second)], axis="horizontal")

    _kept_apart(result, first, second)


def test_a_pair_that_merges_vertically_is_left_alone_on_the_horizontal_axis(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-7, and the transposition detector. These two columns sit side by side:
    on the vertical axis the gap is 1 and the overlap is complete, and on the
    horizontal axis the gap is 0 and the overlap is nil. A `merge_columns` that
    read `y` where it should read `x` would merge them here."""
    first, second = _column_pair(one_bit_png, gap=1, overlap=200)

    assert len(merge_columns([first, second], [_fence_around(first, second)])) == 1

    result = merge_columns([first, second], [_fence_around(first, second)], axis="horizontal")

    _kept_apart(result, first, second)


def test_a_pair_that_merges_horizontally_is_left_alone_on_the_default_axis(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-7's mirror, so that neither direction of the transposition passes. The
    default is `vertical`, which is what the pipeline passes."""
    first, second = _row_pair(one_bit_png, gap=1, overlap=200)

    result = merge_columns([first, second], [_fence_around(first, second)])

    _kept_apart(result, first, second)


# -- C-1: transitivity, order, and the indices merged_from carries -------------


def test_three_columns_of_one_bubble_become_one_region_not_two(
    one_bit_png: Callable[..., bytes],
) -> None:
    """C-1's transitivity. The outer two columns are 62px apart - further than
    any value C-4 admits - so a rule that judged only the pair it had not
    already merged would leave two regions where the page has one utterance."""
    left = _rect_region(one_bit_png, _PAGE, (20, 60, 80, 260))
    middle = _rect_region(one_bit_png, _PAGE, (81, 60, 141, 260))
    right = _rect_region(one_bit_png, _PAGE, (142, 60, 202, 260))
    assert COLUMN_MAX_GAP_PX < 142 - 80, "the outer two must not be adjacent"

    result = merge_columns([left, middle, right], [_fence_around(left, middle, right)])

    assert len(result) == 1
    assert result[0].merged_from == (0, 1, 2)
    assert _mask_bbox(result[0]) == (20, 60, 202, 260)


def test_merged_from_carries_indices_into_the_input_sequence(
    one_bit_png: Callable[..., bytes],
) -> None:
    """C-1. Indices, not identifiers: regions have no database identity until
    they are written, and `merged_from` is computed before the write."""
    lone = _rect_region(one_bit_png, _PAGE, (150, 700, 190, 800))
    first, second = _column_pair(one_bit_png, gap=1, overlap=200)

    result = merge_columns([lone, first, second], [_fence_around(first, second)])

    assert sorted(region.merged_from for region in result) == [(), (1, 2)]


def test_the_output_is_ordered_by_bounding_box_top_then_left(
    one_bit_png: Callable[..., bytes],
) -> None:
    """C-1. `regions_from_detection`'s emission order, preserved: sorted by
    `(y0, x0)`. It is not a reading order - MT-009 owns that, and for Japanese it
    runs right to left."""
    lower_left, lower_right = _column_pair(one_bit_png, gap=1, overlap=200)
    upper = _rect_region(one_bit_png, _PAGE, (150, 10, 190, 40))

    result = merge_columns(
        [lower_left, lower_right, upper], [_fence_around(lower_left, lower_right)]
    )

    assert [_mask_bbox(region)[1::-1] for region in result] == [(10, 150), (60, 40)]


def test_the_boxes_the_detector_fences_with_are_the_rectangles_this_function_takes() -> None:
    """C-1's claim, checked rather than assumed: `postprocess.integer_boxes` is
    public, is exported, and produces exactly the half-open integer rectangles
    `merge_columns` takes - which is what keeps `numpy` out of this signature."""
    from mangatl.detect import postprocess

    boxes = np.array(
        [[10.7, 20.2, 50.9, 80.4, 0.9, 1.0], [-5.0, 0.0, 2000.0, 90.6, 0.8, 0.0]],
        dtype=np.float32,
    )

    fences = integer_boxes(boxes, 1125, 1600)

    assert "integer_boxes" in postprocess.__all__
    assert fences == [(10, 20, 50, 80), (0, 0, 1125, 90)]
    assert all(isinstance(value, int) for fence in fences for value in fence)
