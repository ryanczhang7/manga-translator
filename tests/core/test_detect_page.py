"""`mangatl.detect.page`: the seven-step detect chain for one page (MT-035).

Covers AC-7 (the session sees the letterboxed canvas and sees it once), AC-8
(the MT-008 merge is in the chain, with a two-region baseline from the *same*
session output as its control) and AC-9 (the map came back through the letterbox
transform into page coordinates).

**Nothing here loads a model.** `architecture.md` §2 splits an inference stage
into *logic* - pure functions over arrays, driven by a fake session here, read
by the `unit` and `coverage` gates which really run on CI - and a *session*,
smoke-tested against the real `.onnx` in `tests/integration/`. AC-10 is the
real-detector half and lives there.

**The fake session paints in PAGE coordinates and re-derives the letterbox
geometry itself** (`_geometry` below), instead of calling `postprocess.letterbox`
to find out where to paint. That is deliberate: `tdd-cycle` says a mutation is
only as informative as the independence of what observes it, and a fake that
asked the production transform where to put its rectangles would land them
correctly against *any* transform, right or wrong. The two derivations are
asserted to agree in `test_the_session_is_handed_the_letterboxed_canvas_exactly_once`,
so a disagreement is reported once, by name, rather than as a mysterious region
count three tests later.

**Every number in this file was measured before the module existed**, by
performing the seven steps inline the way
`tests/integration/test_column_merge_pages.py`'s `detected` fixture does. The
story's `## Handoff: RED -> GREEN` carries the table; the short version is:

* baseline `regions_from_detection` on the AC-8 fixture: **2** regions, extents
  `(74, 54, 92, 126)` and `(98, 54, 116, 126)`, gap **6** px, y-overlap
  **1.0000** - both clauses of MT-008's rule satisfied with room to spare;
* `merge_columns` on those two: **1** region, `merged_from == (0, 1)`, extent
  `(74, 54, 116, 126)`;
* the negative control, the same fixture with the columns 54 px apart instead of
  18: **2** regions before *and* 2 after, gap **42** px, no `merged_from`.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size. If a later story adds one,
every test and hook here needs one: each `detect_page_regions` call allocates a
1024-square `seg` and a 2x1024-square `det` (12 MB of zeros) and runs two
`cv2.resize` calls, measured at well under 100 ms per test on this machine.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from mangatl.detect.columns import COLUMN_MAX_GAP_PX, COLUMN_MIN_OVERLAP
from mangatl.detect.page import detect_page_regions
from mangatl.detect.postprocess import (
    DILATE_ITERATIONS,
    DILATE_KERNEL_SIDE,
    decode_boxes,
    letterbox,
    probability_to_page,
    regions_from_detection,
)
from mangatl.detect.session import (
    MODEL_INPUT_SIDE,
    PAD_VALUE,
    RawDetectorOutput,
)
from mangatl.domain.region import RawRegion

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray

# -- the fixture geometry ------------------------------------------------------
#
# All coordinates are half-open `(x0, y0, x1, y1)` PAGE rectangles, the
# convention `fixtures/detect/README.md` pins and `regions_from_detection` uses
# for box membership (MT-007 amendment A-6).

#: The one accepted box, and the fence both columns fall inside. Wide enough
#: that the dilation never reaches its edge, so no extent below is clipped.
_FENCE: tuple[int, int, int, int] = (60, 40, 180, 140)

#: Two columns of one utterance: 6 px wide, 60 px tall, **18 px apart**.
#:
#: 18 is chosen against two settled constants and is the whole reason this
#: fixture merges rather than happening to. `regions_from_detection` dilates by
#: `_REACH` = 6 px in every direction before its second fence, so a painted gap
#: of `g` arrives at `merge_columns` as `g - 12`:
#:
#:   * to stay TWO components through the dilation, `g - 12 >= 1`, so `g >= 13`;
#:   * to merge under `COLUMN_MAX_GAP_PX` = 12, `g - 12 <= 12`, so `g <= 24`.
#:
#: 18 is the middle of `[13, 24]`. Measured, the pair arrives at gap 6 against a
#: limit of 12, and their y-overlap is 1.0000 against a limit of 0.50.
_MERGING_COLUMNS: tuple[tuple[int, int, int, int], ...] = (
    (80, 60, 86, 120),
    (104, 60, 110, 120),
)

#: The negative control: the same two columns **54 px apart** - the gap of the
#: separate bubble `011.jpg` box 7 fences, which MT-008 measured as the nearest
#: thing that must stay apart. Arrives at gap 42 against a limit of 12, so a
#: chain that called `merge_columns` still returns two regions. Without this, a
#: merge that fused everything in a fence box would pass the AC-8 test above.
_SEPARATE_COLUMNS: tuple[tuple[int, int, int, int], ...] = (
    (80, 60, 86, 120),
    (140, 60, 146, 120),
)

#: How far the dilation carries a component beyond its own ink, in page pixels.
#: Read from the shipped constants, so a story that changes the dilation moves
#: the extents this file expects with it - the same way
#: `tests/integration/test_column_merge_pages.py` reads its `_REACH`.
_REACH = DILATE_ITERATIONS * (DILATE_KERNEL_SIDE // 2)

#: Slack on a mask extent, in page pixels. The probability map crosses two
#: bilinear resizes (page -> canvas -> page), so a rectangle edge can land on
#: either side of `MASK_THRESHOLD` in the boundary pixel. Measured, every extent
#: below is exact; 1 px of slack is there so a sub-pixel difference in someone
#: else's OpenCV is not a story bounce. It does not weaken the control: the
#: failure this assertion exists to catch - a chain that resized the map without
#: cropping the letterbox padding - shifts the extent by **15 px** in y
#: (measured: y0 69 instead of 54).
_EXTENT_SLACK = 1

#: Two non-square page sizes, each the other's transposition, so a chain that
#: swapped `(width, height)` for `(height, width)` cannot pass both. AC-9's
#: `W != H` is load-bearing: on a square page an unscaled or transposed mask has
#: the right shape and the criterion goes blind.
_PAGE_SIZES: tuple[tuple[int, int], ...] = ((320, 240), (240, 320))

#: The one colour the fixture page is filled with. Deliberately not `PAD_VALUE`:
#: AC-7's control is that the canvas carries grey `PAD_VALUE` padding a plain
#: resize would not produce, and a page already painted that grey makes it
#: vacuous. 0 is as far from 114 as the range allows.
_PAGE_VALUE = 0


# -- the fake session ----------------------------------------------------------


def _geometry(page_size: tuple[int, int]) -> tuple[float, int, int]:
    """`(ratio, pad_x, pad_y)` for `page_size`, re-derived rather than imported.

    An independent observer (see the module docstring): this is the arithmetic
    `architecture.md`'s letterbox describes, written out from
    `MODEL_INPUT_SIDE` alone, so the fake does not learn where to paint from the
    code under test.
    """
    width, height = page_size
    ratio = MODEL_INPUT_SIDE / float(max(width, height))
    pad_x = (MODEL_INPUT_SIDE - round(width * ratio)) // 2
    pad_y = (MODEL_INPUT_SIDE - round(height * ratio)) // 2
    return ratio, pad_x, pad_y


class _FakeSession:
    """A `DetectorSession` that answers with a hand-painted `seg` and one box.

    It records every call so AC-7 can assert the count and inspect the argument,
    and it keeps the `RawDetectorOutput` it returned so AC-8 can compute its
    two-region baseline from **the same session output** rather than from a
    second run.
    """

    def __init__(
        self,
        page_size: tuple[int, int],
        columns: Sequence[tuple[int, int, int, int]],
        fence: tuple[int, int, int, int] = _FENCE,
    ) -> None:
        self._page_size = page_size
        self._columns = tuple(columns)
        self._fence = fence
        self.canvases: list[NDArray[np.float32]] = []
        self.output: RawDetectorOutput | None = None

    @property
    def calls(self) -> int:
        return len(self.canvases)

    def run(self, canvas: NDArray[np.float32]) -> RawDetectorOutput:
        self.canvases.append(canvas)
        ratio, pad_x, pad_y = _geometry(self._page_size)

        seg = np.zeros((1, 1, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE), dtype=np.float32)
        for x0, y0, x1, y1 in self._columns:
            seg[
                0,
                0,
                round(y0 * ratio + pad_y) : round(y1 * ratio + pad_y),
                round(x0 * ratio + pad_x) : round(x1 * ratio + pad_x),
            ] = 1.0

        fx0, fy0, fx1, fy1 = self._fence
        blk = np.array(
            [
                [
                    [
                        (fx0 + fx1) / 2.0 * ratio + pad_x,
                        (fy0 + fy1) / 2.0 * ratio + pad_y,
                        (fx1 - fx0) * ratio,
                        (fy1 - fy0) * ratio,
                        # obj, class 0, class 1: confidence 0.9, class 1, which
                        # `postprocess._kind` reads as `bubble` (MT-007 A-4).
                        1.0,
                        0.0,
                        0.9,
                    ]
                ]
            ],
            dtype=np.float32,
        )
        # `det` is carried and never read (MT-007 amendment A-1), at the shape
        # the real graph declares so the fake is not lying about it.
        det = np.zeros((1, 2, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE), dtype=np.float32)

        self.output = RawDetectorOutput(blk=blk, seg=seg, det=det)
        return self.output

    def get_providers(self) -> Sequence[str]:
        """Declared because `DetectorSession` declares it (MT-007 A-2).
        `detect_page_regions` has no business calling it, and a fake that
        answered a question nobody asked would hide that."""
        return ("FakeExecutionProvider",)


# -- helpers -------------------------------------------------------------------


def _page_bytes(page_size: tuple[int, int], png_bytes: Callable[..., bytes]) -> bytes:
    width, height = page_size
    return png_bytes(width, height, (_PAGE_VALUE, _PAGE_VALUE, _PAGE_VALUE))


def _decoded(region: RawRegion) -> NDArray[np.bool_]:
    """The region's mask as a boolean array, decoded by PIL rather than by us.

    An independent observer on purpose: a mask encoder that is uniformly wrong
    decodes perfectly through its own inverse (`tdd-cycle`).
    """
    with Image.open(BytesIO(region.mask)) as image:
        assert image.mode == "1", f"mask is {image.mode}, not a 1-bit image"
        return np.array(image, dtype=bool)


def _extent(region: RawRegion) -> tuple[int, int, int, int]:
    """The half-open bounding box of the region's set mask pixels."""
    ys, xs = np.nonzero(_decoded(region))
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _grown(rects: Sequence[tuple[int, int, int, int]], reach: int) -> tuple[int, int, int, int]:
    """The union of `rects`, grown by `reach` in every direction."""
    return (
        min(rect[0] for rect in rects) - reach,
        min(rect[1] for rect in rects) - reach,
        max(rect[2] for rect in rects) + reach,
        max(rect[3] for rect in rects) + reach,
    )


def _unmerged_baseline(
    output: RawDetectorOutput,
    image_bytes: bytes,
    page_size: tuple[int, int],
) -> list[RawRegion]:
    """Steps 1 to 6 of C-2 on an already-computed session output: no merge.

    AC-8's control. It runs on the very `RawDetectorOutput` object the session
    handed to `detect_page_regions`, so "one region here, two regions there" is
    a statement about the chain and not about two different inferences.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        page = np.asarray(image.convert("RGB"), dtype=np.uint8)
    _canvas, transform = letterbox(page)
    boxes = decode_boxes(output.blk, transform, page_size)
    prob = probability_to_page(output.seg, transform, page_size)
    return regions_from_detection(prob, boxes, page_size)


def _merge_clauses(
    regions: Sequence[RawRegion],
) -> tuple[int, float]:
    """`(gap, overlap fraction)` for a pair, in MT-008's half-open convention.

    Written out here rather than imported from `detect.columns._is_one_utterance`
    for the same reason `_geometry` is: the point is to show that the *fixture*
    satisfies the shipped rule, and a check that borrowed the rule's own private
    arithmetic could not show that.
    """
    assert len(regions) == 2, f"the clause check is for a pair, got {len(regions)}"
    a, b = (_extent(region) for region in regions)
    gap = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    shared = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    shorter = min(a[3] - a[1], b[3] - b[1])
    return gap, shared / shorter


# -- the module's shape --------------------------------------------------------


def test_the_chain_is_exported_from_mangatl_detect_page_under_that_name() -> None:
    """C-2's module path and `__all__`, pinned so GREEN does not have to guess.

    `mangatl.pipeline` may not import any of this (C-1), which is exactly why
    the composition has to live here and be named here.
    """
    import mangatl.detect.page as module

    assert module.__all__ == ["detect_page_regions"]
    assert module.detect_page_regions is detect_page_regions


def test_the_chain_returns_a_list_of_raw_regions(png_bytes: Callable[..., bytes]) -> None:
    """C-2's return type: `list[RawRegion]`, which is `merge_columns`' own."""
    page_size = _PAGE_SIZES[0]
    session = _FakeSession(page_size, _MERGING_COLUMNS)

    regions = detect_page_regions(session, _page_bytes(page_size, png_bytes))

    assert isinstance(regions, list)
    assert all(isinstance(region, RawRegion) for region in regions)


# -- AC-7: the session sees the letterboxed canvas, once -----------------------


@pytest.mark.parametrize("page_size", _PAGE_SIZES, ids=str)
def test_the_session_is_handed_the_letterboxed_canvas_exactly_once(
    page_size: tuple[int, int],
    png_bytes: Callable[..., bytes],
) -> None:
    """AC-7. One inference per page, on the 1024-square float32 canvas.

    The shape assertion *is* the control, as AC-7 says: a chain that handed the
    decoded page straight to the session passes an array of the page's own
    shape. The grey-padding assertions are the second half of it - a plain
    `cv2.resize` to 1024 square has the right shape and no padding at all, so
    shape alone cannot tell a letterbox from a squash.
    """
    width, height = page_size
    ratio, pad_x, pad_y = _geometry(page_size)
    session = _FakeSession(page_size, _MERGING_COLUMNS)

    detect_page_regions(session, _page_bytes(page_size, png_bytes))

    assert session.calls == 1, f"the session ran {session.calls} times, not once"
    canvas = session.canvases[0]
    assert canvas.shape == (1, 3, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE), (
        f"the session was handed {canvas.shape}; the page is {(height, width)}, so an"
        " array of the page's own dimensions means the letterbox was skipped"
    )
    assert canvas.dtype == np.float32
    assert (height, width) != (MODEL_INPUT_SIDE, MODEL_INPUT_SIDE), (
        "the fixture page must not be model-sized, or the shape assertion above"
        " cannot tell a letterboxed canvas from the page itself"
    )

    # The transform the fake painted against is the transform the chain used.
    # Asserted here, once, so a disagreement is named rather than showing up as
    # a region count in AC-8.
    with Image.open(BytesIO(_page_bytes(page_size, png_bytes))) as image:
        page = np.asarray(image.convert("RGB"), dtype=np.uint8)
    _canvas, transform = letterbox(page)
    assert (transform.ratio, transform.pad_x, transform.pad_y) == (ratio, pad_x, pad_y)

    grey = np.float32(PAD_VALUE / 255.0)
    assert pad_x + pad_y > 0, (
        f"page {page_size} letterboxes with no padding at all, so the two grey"
        " assertions below are vacuous; AC-7 needs a page whose aspect is not 1:1"
    )
    assert np.all(canvas[0, :, :pad_y, :] == grey), "the top margin is not grey PAD_VALUE"
    assert np.all(canvas[0, :, :, :pad_x] == grey), "the left margin is not grey PAD_VALUE"
    centre = MODEL_INPUT_SIDE // 2
    assert np.all(canvas[0, :, centre, centre] == np.float32(_PAGE_VALUE / 255.0)), (
        "the middle of the canvas is not the page's own pixels, normalised"
    )


# -- AC-8: the MT-008 merge is in the chain ------------------------------------


@pytest.mark.parametrize("page_size", _PAGE_SIZES, ids=str)
def test_two_columns_of_one_utterance_in_one_box_come_back_as_a_single_region(
    page_size: tuple[int, int],
    png_bytes: Callable[..., bytes],
) -> None:
    """AC-8, with its two-region baseline computed on the same session output.

    MT-008 proved `merge_columns` merges the rule; nothing yet proves this
    chain calls it. The baseline is what makes that a measurement: without it,
    "one region" is satisfied by a synthetic page the detector only ever found
    one region on, which measures nothing.

    Measured before the module existed: baseline **2**, merged **1**,
    `merged_from == (0, 1)`, gap **6** px against a limit of 12, y-overlap
    **1.0000** against a limit of 0.50.
    """
    image_bytes = _page_bytes(page_size, png_bytes)
    session = _FakeSession(page_size, _MERGING_COLUMNS)

    merged = detect_page_regions(session, image_bytes)

    assert session.calls == 1
    assert session.output is not None
    baseline = _unmerged_baseline(session.output, image_bytes, page_size)

    assert len(baseline) == 2, (
        f"the control failed, not the criterion: `regions_from_detection` found"
        f" {len(baseline)} regions on this session output, so the fixture does not"
        " present two columns to be merged and AC-8 would pass vacuously"
    )
    gap, overlap = _merge_clauses(baseline)
    assert gap <= COLUMN_MAX_GAP_PX, (
        f"the fixture's columns arrive {gap} px apart, past MT-008's"
        f" COLUMN_MAX_GAP_PX of {COLUMN_MAX_GAP_PX}, so they must NOT merge"
    )
    assert overlap >= COLUMN_MIN_OVERLAP, (
        f"the fixture's columns share {overlap:.4f} of the shorter extent, under"
        f" MT-008's COLUMN_MIN_OVERLAP of {COLUMN_MIN_OVERLAP}"
    )

    assert len(merged) == 1, (
        f"{len(baseline)} regions before merging and {len(merged)} after; the"
        " chain does not call merge_columns"
    )
    assert merged[0].merged_from == (0, 1), (
        "the surviving region does not record both inputs, so the count did not"
        " drop because two columns were joined"
    )


@pytest.mark.parametrize("page_size", _PAGE_SIZES, ids=str)
def test_two_separate_bubbles_in_one_box_are_not_merged_by_the_chain(
    page_size: tuple[int, int],
    png_bytes: Callable[..., bytes],
) -> None:
    """AC-8's hard negative control: the merge is MT-008's rule, not a fuse.

    Same fence box, same y-overlap, columns 54 px apart instead of 18 - the gap
    of the separate bubble `011.jpg` box 7 fences, which MT-008 measured as the
    nearest thing that must stay apart. Measured: gap 42 px, 2 regions in and 2
    out, neither recording a merge. A chain that merged everything sharing a
    fence box passes the test above and fails this one.
    """
    image_bytes = _page_bytes(page_size, png_bytes)
    session = _FakeSession(page_size, _SEPARATE_COLUMNS)

    regions = detect_page_regions(session, image_bytes)

    assert session.output is not None
    baseline = _unmerged_baseline(session.output, image_bytes, page_size)
    assert len(baseline) == 2, f"the control needs two inputs, got {len(baseline)}"
    gap, overlap = _merge_clauses(baseline)
    assert gap > COLUMN_MAX_GAP_PX, (
        f"these columns arrive only {gap} px apart, within MT-008's"
        f" COLUMN_MAX_GAP_PX of {COLUMN_MAX_GAP_PX}, so this fixture is not a"
        " negative control at all"
    )
    assert overlap >= COLUMN_MIN_OVERLAP, (
        "the overlap clause must still hold, or the gap clause is not the thing"
        f" keeping them apart; got {overlap:.4f}"
    )

    assert len(regions) == 2
    assert [region.merged_from for region in regions] == [(), ()]


# -- AC-9: the map came back into page coordinates -----------------------------


@pytest.mark.parametrize("page_size", _PAGE_SIZES, ids=str)
def test_every_region_of_a_non_square_page_is_masked_and_drawn_in_page_pixels(
    page_size: tuple[int, int],
    png_bytes: Callable[..., bytes],
) -> None:
    """AC-9. Masks decode to exactly `(H, W)`; every vertex is on the page.

    A chain that skipped `probability_to_page` hands `regions_from_detection` a
    `MODEL_INPUT_SIDE`-square map, which raises rather than returning masks at
    model scale (measured: `ValueError: prob.shape is (1024, 1024), which is not
    (height, width) = (240, 320) ...`). A chain that resized the map but forgot
    to crop the letterbox padding returns masks of the right shape in the wrong
    place, which the extent assertion catches: measured, it puts the extent's
    `y0` at 69 instead of 54.
    """
    width, height = page_size
    session = _FakeSession(page_size, _MERGING_COLUMNS)

    regions = detect_page_regions(session, _page_bytes(page_size, png_bytes))

    assert height != width, (
        "AC-9 needs W != H: on a square page a transposed or unscaled mask has"
        " the right shape and this test goes blind"
    )
    assert (height, width) != (MODEL_INPUT_SIDE, MODEL_INPUT_SIDE)
    assert len(regions) == 1, (
        f"{len(regions)} regions, so there is nothing to check the coordinates of"
    )

    # Violations are accumulated and asserted once (`tdd-cycle`): a failure
    # should read out every wrong mask, not stop at the first.
    wrong_shape = {
        index: _decoded(region).shape
        for index, region in enumerate(regions)
        if _decoded(region).shape != (height, width)
    }
    assert wrong_shape == {}, (
        f"masks decode to {wrong_shape}, not to the page's (height, width) ="
        f" {(height, width)}; at model scale they would be"
        f" {(MODEL_INPUT_SIDE, MODEL_INPUT_SIDE)}"
    )

    off_page = {
        index: [
            vertex
            for vertex in region.polygon
            if not (0 <= vertex[0] < width and 0 <= vertex[1] < height)
        ]
        for index, region in enumerate(regions)
    }
    assert {index: bad for index, bad in off_page.items() if bad} == {}, (
        f"polygon vertices outside the page rectangle (0, 0, {width}, {height}): {off_page}"
    )

    expected = _grown(_MERGING_COLUMNS, _REACH)
    measured = _extent(regions[0])
    assert all(abs(a - b) <= _EXTENT_SLACK for a, b in zip(measured, expected, strict=True)), (
        f"the region's mask covers {measured}; the painted columns"
        f" {_MERGING_COLUMNS} grown by the {_REACH} px dilation reach are"
        f" {expected}. A map resized without cropping the letterbox padding"
        " lands about 15 px out in y."
    )
