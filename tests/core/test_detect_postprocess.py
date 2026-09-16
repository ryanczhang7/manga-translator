"""`mangatl.detect.postprocess`: the letterbox, the decode and the regions.

Covers AC-1, AC-2, AC-3, AC-4 and AC-6 against a probability map and a box list
this file builds itself. Nothing here loads a model: `architecture.md` §2 splits
each inference stage into *logic* - pure functions over arrays, tested here -
and a *session*, smoke-tested in `tests/integration/` against the real `.onnx`.
AC-7 and AC-8 are the session half and live there.

**The oracle partition (MT-007 C-10) decides how each test below is written.**
AC-1 to AC-4 are mechanical: every fixture is hand-built so the right answer is
arithmetic, and the assertions are pixel-exact. AC-6 has no settled metric, so
this file invents one - *how many set mask pixels fall inside an annotated SFX
rectangle* - and ships the controls that make the number mean something. A
metric that reads zero against a detector which finds nothing at all is the
failure AC-6 exists to prevent, so every sweep point also asserts that regions
were produced.

**The fixtures are declarative.** `fixtures/detect/*.json` holds rectangles, not
arrays; `_render` below turns a spec into the `(H, W) float32` map and the
`(N, 6)` box array. See `fixtures/detect/README.md` for the format and the
provenance. Every rectangle is half-open - `x0 <= x < x1` - which is also the
box-membership rule `regions_from_detection` uses (MT-007 amendment A-6), so
every area in this file is exactly `(x1 - x0) * (y1 - y0)`.

**What this file deliberately does not assert.** Reading order: MT-009 owns it,
and for Japanese it is right-to-left, which is not the order asserted here.
`test_regions_are_emitted_top_to_bottom_then_left_to_right` pins an *emission*
order - a deterministic, reproducible sequence - and nothing more.
"""

from __future__ import annotations

import json
import struct
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.detect.postprocess import (
    BOX_CONFIDENCE,
    DILATE_ITERATIONS,
    MASK_THRESHOLD,
    MIN_REGION_AREA_PX,
    NMS_IOU,
    LetterboxTransform,
    decode_boxes,
    letterbox,
    probability_to_page,
    regions_from_detection,
)
from mangatl.detect.session import MODEL_INPUT_SIDE, PAD_VALUE
from mangatl.domain.region import RawRegion

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "detect"

# The sweep AC-6 means by "every threshold in the swept range and every dilation
# setting". The low end is what matters: MT-007 PO-1 measured that the *mask*
# head covers 27-59% of every annotated SFX area at every threshold from 0.10 to
# 0.999, so a fixture that only passed at a high threshold would be proving
# nothing about the mechanism.
_SWEPT_THRESHOLDS = (0.05, 0.10, 0.30, 0.50, 0.772, 0.90, 0.95, MASK_THRESHOLD)
_SWEPT_DILATIONS = (0, 1, 2, 3, DILATE_ITERATIONS)

# Fixtures whose blobs are painted at 1.0 are safe at any threshold in (0, 1] and
# are therefore exercised at the SHIPPED configuration. `clean-bubbles` is not:
# it paints 0.6 and 0.9 on purpose, so that the mean-not-max confidence of C-7 is
# observable - which means a threshold GREEN derives above 0.6 would change what
# that fixture means. Its tests pass an explicit threshold for exactly that
# reason, and it is a fixture property rather than a weakened assertion.
_EXPLICIT = 0.5


# -- the fixture renderer ------------------------------------------------------


def _spec(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _render(spec: dict[str, Any]) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """A spec -> the `(H, W) float32` probability map and the `(N, 6)` box array."""
    width, height = spec["page_size"]
    prob = np.full((height, width), spec["background"], dtype=np.float32)
    for painted in spec["paint"]:
        x0, y0, x1, y1 = painted["rect"]
        prob[y0:y1, x0:x1] = painted["value"]
    return prob, _boxes(spec["boxes"])


def _boxes(rows: list[dict[str, Any]]) -> NDArray[np.float32]:
    return np.array(
        [[*row["rect"], row["conf"], row["cls"]] for row in rows],
        dtype=np.float32,
    ).reshape(-1, 6)


def _page_size(spec: dict[str, Any]) -> tuple[int, int]:
    width, height = spec["page_size"]
    return int(width), int(height)


def _rects(spec: dict[str, Any], key: str = "sfx_rects") -> list[tuple[int, int, int, int]]:
    return [tuple(int(v) for v in entry["rect"]) for entry in spec[key]]  # type: ignore[misc]


def _painted(spec: dict[str, Any], ident: str) -> tuple[int, int, int, int]:
    for entry in spec["paint"]:
        if entry["id"] == ident:
            return tuple(int(v) for v in entry["rect"])  # type: ignore[return-value]
    raise AssertionError(f"no rectangle {ident!r} in fixture {spec['name']!r}")


# -- reading a region back -----------------------------------------------------


def _mask(region: RawRegion) -> NDArray[np.bool_]:
    """The region's mask decoded to a boolean array, by PIL rather than by us.

    An independent observer on purpose: a mask encoder that is uniformly wrong
    decodes perfectly through its own inverse (`tdd-cycle`).
    """
    with Image.open(BytesIO(region.mask)) as image:
        assert image.mode == "1", f"mask is {image.mode}, not a 1-bit image"
        return np.array(image, dtype=bool)


def _png_header(region: RawRegion) -> tuple[int, int, int, int]:
    """`(width, height, bit_depth, colour_type)` straight out of IHDR.

    Parsed with `struct` so that "1-bit" is asserted against the file format
    rather than against whatever PIL chose to widen it to on the way in.
    """
    assert region.mask[:8] == b"\x89PNG\r\n\x1a\n"
    length, tag = struct.unpack(">I4s", region.mask[8:16])
    assert tag == b"IHDR" and length == 13
    width, height, depth, colour = struct.unpack(">IIBB", region.mask[16:26])
    return int(width), int(height), int(depth), int(colour)


def _set_pixels(region: RawRegion) -> set[tuple[int, int]]:
    mask = _mask(region)
    ys, xs = np.nonzero(mask)
    return {(int(x), int(y)) for x, y in zip(xs, ys, strict=True)}


def _every(array: NDArray[np.float32], value: float, *, tol: float = 1e-6) -> None:
    """Assert every element of `array` is `value`, via its min and its max.

    `array == pytest.approx(v)` over a (1, 3, 1024, 1024) canvas costs 1.12s in a
    plain run and more again under the coverage gate's instrumentation, because
    approx walks three million elements in Python. The min and the max say the
    same thing about a constant array and are vectorised: measured 1.12s -> 0.01s
    for the same assertion.
    """
    low, high = float(np.min(array)), float(np.max(array))
    assert low == pytest.approx(value, abs=tol), f"array spans {low}..{high}, wanted {value}"
    assert high == pytest.approx(value, abs=tol), f"array spans {low}..{high}, wanted {value}"


def _rect_pixels(rect: tuple[int, int, int, int]) -> set[tuple[int, int]]:
    x0, y0, x1, y1 = rect
    return {(x, y) for y in range(y0, y1) for x in range(x0, x1)}


def _bbox(region: RawRegion) -> tuple[int, int, int, int]:
    """The inclusive `(x0, y0, x1, y1)` bounding box of the set mask pixels."""
    mask = _mask(region)
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _in_emission_order(regions: list[RawRegion]) -> list[tuple[int, int]]:
    return [(_bbox(region)[1], _bbox(region)[0]) for region in regions]


def _sfx_pixels(regions: list[RawRegion], rects: list[tuple[int, int, int, int]]) -> int:
    """AC-6's metric: set mask pixels of any region inside any annotated area.

    Counted over the union of the rectangles, so a pixel in two overlapping
    annotations counts once. Accumulated rather than asserted per region: a
    sweep that asserted inside the loop would stop at the first violation and
    hide how far off the mechanism is.
    """
    annotated = set().union(*(_rect_pixels(rect) for rect in rects)) if rects else set()
    return sum(len(_set_pixels(region) & annotated) for region in regions)


# -- letterbox -----------------------------------------------------------------


def test_letterbox_gives_the_model_a_normalised_square_canvas_with_grey_padding() -> None:
    """The real page shape, so the numbers are the ones AC-7 will meet.

    1125x1600 -> ratio 0.64, 720x1024 of content, 152px of grey 114 either side.
    """
    page = np.full((1600, 1125, 3), 200, dtype=np.uint8)

    canvas, transform = letterbox(page)

    assert canvas.shape == (1, 3, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE)
    assert canvas.dtype == np.float32
    assert transform == LetterboxTransform(ratio=pytest.approx(0.64), pad_x=152, pad_y=0)
    assert canvas.min() >= 0.0
    assert canvas.max() <= 1.0
    _every(canvas[0, :, :, :152], PAD_VALUE / 255.0)
    _every(canvas[0, :, :, 872:], PAD_VALUE / 255.0)
    assert canvas[0, :, 300, 400] == pytest.approx(200 / 255.0)


def test_a_square_page_is_letterboxed_with_no_padding_at_all() -> None:
    page = np.full((256, 256, 3), 255, dtype=np.uint8)

    canvas, transform = letterbox(page)

    assert transform == LetterboxTransform(ratio=pytest.approx(4.0), pad_x=0, pad_y=0)
    _every(canvas, 1.0)


def test_a_page_wider_than_it_is_tall_is_padded_top_and_bottom() -> None:
    """The other orientation, because a letterbox that only ever saw portrait
    pages can have its two padding axes the wrong way round and never show it."""
    page = np.full((512, 1024, 3), 0, dtype=np.uint8)

    _canvas, transform = letterbox(page)

    assert transform == LetterboxTransform(ratio=pytest.approx(1.0), pad_x=0, pad_y=256)


# -- decode_boxes --------------------------------------------------------------


def _anchor(
    cx: float, cy: float, w: float, h: float, obj: float, c0: float, c1: float
) -> list[float]:
    return [cx, cy, w, h, obj, c0, c1]


_TRANSFORM = LetterboxTransform(ratio=0.64, pad_x=152, pad_y=0)
_REAL_PAGE = (1125, 1600)


def test_the_box_head_is_decoded_to_page_coordinates_with_a_confidence_and_a_class() -> None:
    """AC-1's "accepted box", mechanically.

    Five anchors: one strong, one that overlaps it too much to survive NMS, one
    far away, one below the confidence floor, and one that falls off the left of
    the page and must be clipped. Scores are `obj * max(cls)` and rows come back
    in descending confidence, so the whole expected array is arithmetic.
    """
    blk = np.array(
        [
            [
                _anchor(452, 320, 64, 128, 0.90, 0.20, 0.80),  # A: 0.72, class 1
                _anchor(456, 324, 64, 128, 0.90, 0.70, 0.10),  # B: 0.63, IoU 0.83 with A
                _anchor(700, 700, 100, 100, 0.95, 0.10, 0.60),  # C: 0.57, class 1
                _anchor(300, 300, 40, 40, 0.50, 0.30, 0.50),  # D: 0.25, below the floor
                _anchor(160, 40, 200, 200, 0.88, 0.05, 0.90),  # E: 0.792, clipped
            ]
        ],
        dtype=np.float32,
    )

    boxes = decode_boxes(blk, _TRANSFORM, _REAL_PAGE)

    assert boxes.shape == (3, 6)
    assert boxes[:, 4] == pytest.approx([0.792, 0.72, 0.57], abs=1e-5)
    assert boxes[:, 5].tolist() == [1.0, 1.0, 1.0]
    assert boxes[0, :4] == pytest.approx([0.0, 0.0, 168.75, 218.75], abs=1e-3)
    assert boxes[1, :4] == pytest.approx([418.75, 400.0, 518.75, 600.0], abs=1e-3)
    assert boxes[2, :4] == pytest.approx([778.125, 1015.625, 934.375, 1171.875], abs=1e-3)


def test_an_anchor_the_detector_is_unsure_of_is_not_an_accepted_box() -> None:
    """The floor is `BOX_CONFIDENCE`, and it is `obj * max(cls)` that meets it."""
    just_under = np.array(
        [
            [
                _anchor(452, 320, 64, 128, BOX_CONFIDENCE, 0.99, 0.999),
            ]
        ],
        dtype=np.float32,
    )
    just_over = np.array(
        [[_anchor(452, 320, 64, 128, 1.0, 0.0, BOX_CONFIDENCE + 0.01)]], dtype=np.float32
    )

    assert decode_boxes(just_under, _TRANSFORM, _REAL_PAGE).shape == (0, 6)
    assert decode_boxes(just_over, _TRANSFORM, _REAL_PAGE).shape == (1, 6)


def test_a_page_the_detector_found_no_text_on_decodes_to_an_empty_box_array() -> None:
    """The zero case, shaped: `(0, 6)` and not `(0,)`, because
    `regions_from_detection` indexes columns of whatever it is handed."""
    blk = np.zeros((1, 32, 7), dtype=np.float32)

    boxes = decode_boxes(blk, _TRANSFORM, _REAL_PAGE)

    assert boxes.shape == (0, 6)
    assert boxes.dtype == np.float32


def test_two_anchors_on_one_bubble_are_reduced_to_the_more_confident_one() -> None:
    """Non-maximum suppression at `NMS_IOU`, pinned by the class of the survivor.

    The two anchors carry different classes, so a suppression that kept the
    wrong one is visible in column 5 rather than only in the row count.
    """
    blk = np.array(
        [
            [
                _anchor(452, 320, 64, 128, 0.90, 0.20, 0.80),  # 0.72, class 1
                _anchor(456, 324, 64, 128, 0.90, 0.70, 0.10),  # 0.63, class 0, IoU 0.83
            ]
        ],
        dtype=np.float32,
    )

    boxes = decode_boxes(blk, _TRANSFORM, _REAL_PAGE)

    assert boxes.shape == (1, 6)
    assert boxes[0, 5] == 1.0
    assert NMS_IOU < 0.83, "the fixture's overlap must exceed the threshold under test"


def test_two_anchors_that_barely_overlap_are_both_kept() -> None:
    """The other side of the same boundary: these two overlap at IoU 0.093, which
    is two neighbouring bubbles rather than one bubble found twice."""
    blk = np.array(
        [
            [
                _anchor(400, 320, 100, 100, 0.90, 0.20, 0.80),
                _anchor(483, 320, 100, 100, 0.90, 0.20, 0.70),
            ]
        ],
        dtype=np.float32,
    )

    boxes = decode_boxes(blk, _TRANSFORM, _REAL_PAGE)

    assert boxes.shape == (2, 6)


# -- probability_to_page -------------------------------------------------------


def test_the_letterbox_padding_is_cropped_before_the_map_reaches_the_page() -> None:
    """Grey padding is not text. A map that kept it would light up 152 columns
    of certainty down each edge of every portrait page."""
    seg = np.ones((1, 1, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE), dtype=np.float32)
    seg[0, 0, :, 152:872] = 0.0

    prob = probability_to_page(seg, _TRANSFORM, _REAL_PAGE)

    assert prob.shape == (1600, 1125)
    assert prob.dtype == np.float32
    assert prob.max() == pytest.approx(0.0, abs=1e-3)


def test_the_probability_map_is_resized_to_the_page_and_left_as_probabilities() -> None:
    """C-4 step 2: resize THEN threshold, never the other way round.

    MT-030 E4 measured both orderings - resize-then-threshold gives recall
    0.9658 / IoU 0.5657 against threshold-then-resize's 0.9492 / 0.5847 - and a
    nearest-neighbour resize of an already-thresholded mask throws the sub-pixel
    evidence away. A function that returned 0/1 here has done the thresholding.
    """
    seg = np.full((1, 1, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE), 0.3, dtype=np.float32)

    prob = probability_to_page(seg, _TRANSFORM, _REAL_PAGE)

    _every(prob, 0.3, tol=1e-3)


def test_the_content_of_the_map_lands_where_the_letterbox_put_it() -> None:
    """A square page, so the transform is a pure scale and the arithmetic is
    checkable by eye: the canvas's top-left quadrant is the page's top-left
    quadrant."""
    seg = np.zeros((1, 1, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE), dtype=np.float32)
    seg[0, 0, :512, :512] = 1.0
    transform = LetterboxTransform(ratio=2.0, pad_x=0, pad_y=0)

    prob = probability_to_page(seg, transform, (512, 512))

    assert prob.shape == (512, 512)
    _every(prob[:250, :250], 1.0)
    _every(prob[262:, :250], 0.0)
    _every(prob[:250, 262:], 0.0)


# -- AC-1: a region per component inside an accepted box -----------------------


def test_each_component_inside_an_accepted_box_becomes_one_region() -> None:
    """AC-1, pixel-exact.

    Each box in `clean-bubbles` is exactly its blob, so the fence clips the
    dilation straight back and the mask must equal the blob to the pixel - which
    makes this an assertion about the whole of C-4, not only about the count.
    """
    spec = _spec("clean-bubbles")
    prob, boxes = _render(spec)
    width, height = _page_size(spec)

    regions = regions_from_detection(prob, boxes, (width, height), threshold=_EXPLICIT)

    assert len(regions) == 3
    expected = [
        _rect_pixels((180, 30, 260, 80)),
        _rect_pixels((40, 40, 100, 90)),
        _rect_pixels((120, 150, 200, 210)),
    ]
    assert [_set_pixels(region) for region in regions] == expected


def test_every_mask_is_a_one_bit_png_the_size_of_the_page() -> None:
    """AC-1's "1-bit mask of the same dimensions as the page", asserted against
    the PNG header rather than against a decoder that would widen it."""
    spec = _spec("clean-bubbles")
    prob, boxes = _render(spec)
    width, height = _page_size(spec)

    regions = regions_from_detection(prob, boxes, (width, height), threshold=_EXPLICIT)

    for region in regions:
        assert _png_header(region) == (width, height, 1, 0)
        assert _mask(region).shape == (height, width)


def test_regions_are_emitted_top_to_bottom_then_left_to_right() -> None:
    """The EMISSION order, which is not a reading order.

    MT-009 owns reading order and for Japanese it runs right-to-left; this story
    must not invent one (MT-007 C-8). What it must do is be deterministic, so
    that `reading_index` means the same thing on two runs of the same page. The
    fixture's boxes are listed B1, B2, B3 and its blobs run left to right, so
    the expected order below is neither of those.
    """
    spec = _spec("clean-bubbles")
    prob, boxes = _render(spec)

    regions = regions_from_detection(prob, boxes, _page_size(spec), threshold=_EXPLICIT)

    assert _in_emission_order(regions) == [(30, 180), (40, 40), (150, 120)]


def test_the_emission_order_is_the_bounding_box_not_the_first_pixel_found() -> None:
    """The same rule where the two plausible answers disagree.

    Connected-component labelling numbers components by the first pixel a raster
    scan reaches - the topmost row, then the leftmost pixel *in that row*. Sorting
    by the bounding box's `(y0, x0)` uses the leftmost pixel of the *whole*
    component. On most pages the two agree, and RED measured that the test above
    passes even with the sort deleted.

    Here they disagree. `A` is a wide bar at x>=120 whose body reaches left to
    x=20 two rows lower; `B` is a rectangle at x=40 on the same top row. Raster
    order finds B first; the bounding-box order puts A first.
    """
    prob = np.zeros((240, 320), np.float32)
    prob[20:26, 120:200] = 1.0  # A, the bar: first pixel (20, 120)
    prob[26:60, 20:200] = 1.0  # A, the body: reaches out to x = 20
    prob[20:24, 40:110] = 1.0  # B: first pixel (20, 40), clear of both
    boxes = np.array([[0, 0, 320, 240, 0.9, 1]], dtype=np.float32)

    regions = regions_from_detection(
        prob, boxes, (320, 240), threshold=_EXPLICIT, dilate_iterations=0
    )

    assert len(regions) == 2
    assert _in_emission_order(regions) == [(20, 20), (20, 40)]


def test_a_speckle_that_touches_a_blob_outside_the_box_is_still_speckle() -> None:
    """The area floor is applied to the FENCED component, not the raw one.

    Two pixels of noise inside an accepted box, touching a large blob that lies
    entirely outside it. Intersect first and the component is 4px and dies;
    intersect only after dilating and the component is thousands of pixels,
    sails over the floor, and leaves a region behind when the fence is finally
    applied. RED measured that without this test, removing the FIRST box
    intersection breaks nothing in the suite.
    """
    prob = np.zeros((240, 320), np.float32)
    prob[60:62, 78:80] = 1.0  # 4px, inside the box, at its right edge
    prob[55:120, 80:200] = 1.0  # a large blob, wholly outside the box, adjacent
    boxes = np.array([[50, 50, 80, 80, 0.9, 1]], dtype=np.float32)

    regions = regions_from_detection(prob, boxes, (320, 240))

    assert regions == []


def test_a_regions_confidence_is_the_mean_probability_inside_it_not_the_max() -> None:
    """C-7, pinned by a blob built of two values.

    B1 is half 1.0 and half 0.6, so its mean is exactly 0.8 and its max is
    exactly 1.0. The max carries no information - the `seg` head's measured range
    on `012.jpg` is exactly [0.0, 1.0] and almost every region touches the top of
    it - which is why the contract asks for the mean.
    """
    spec = _spec("clean-bubbles")
    prob, boxes = _render(spec)

    regions = regions_from_detection(prob, boxes, _page_size(spec), threshold=_EXPLICIT)

    assert [region.confidence for region in regions] == pytest.approx([1.0, 0.8, 0.9], abs=1e-6)


def test_a_regions_kind_comes_from_the_class_of_the_box_that_fenced_it() -> None:
    """Measured in RED (MT-007 amendment A-4): on `011-015.jpg` the box head
    emits class 1 for every speech bubble and class 0 for the free-floating
    scanlation watermark, which is text on art rather than text in a bubble.
    The fixture's B2 carries class 0 and the other two carry class 1."""
    spec = _spec("clean-bubbles")
    prob, boxes = _render(spec)

    regions = regions_from_detection(prob, boxes, _page_size(spec), threshold=_EXPLICIT)

    assert [region.kind for region in regions] == ["box", "bubble", "bubble"]


def test_a_component_outside_every_accepted_box_produces_no_region() -> None:
    """AC-1's "that lies inside an accepted box", stated positively and
    negatively at once: the `sfx` fixture's two SFX blobs are as strong a signal
    in the probability map as the two text blobs, and the only difference between
    them is whether a box covers them."""
    spec = _spec("sfx")
    prob, boxes = _render(spec)

    regions = regions_from_detection(prob, boxes, _page_size(spec))

    assert len(regions) == 2
    assert {frozenset(_set_pixels(region)) for region in regions} == {
        frozenset(_rect_pixels(_painted(spec, "T1"))),
        frozenset(_rect_pixels(_painted(spec, "T2"))),
    }


def test_a_page_with_no_accepted_boxes_produces_no_regions_at_all() -> None:
    """The zero case. An empty box list is not a licence to fall back on the
    probability map - it is a page the box head found no text on."""
    spec = _spec("clean-bubbles")
    prob, _boxes = _render(spec)

    regions = regions_from_detection(
        prob, np.zeros((0, 6), np.float32), _page_size(spec), threshold=_EXPLICIT
    )

    assert regions == []


# -- AC-2: the speckle floor ---------------------------------------------------


def test_a_speckle_inside_an_accepted_box_produces_no_region() -> None:
    """AC-2 at the shipped configuration.

    The speckle is 4px and sits inside its own accepted box, so the fence cannot
    be what discards it - only the area floor can. It also pins WHERE the floor
    is applied: dilated first, those 4px become 14x14 = 196px and survive any
    floor below 196 (measured in RED, MT-007 amendment A-7), which is exactly
    what AC-2 forbids.
    """
    spec = _spec("single-kana")
    prob, boxes = _render(spec)

    regions = regions_from_detection(prob, boxes, _page_size(spec))

    assert len(regions) == 1
    assert _set_pixels(regions[0]) & _rect_pixels(_painted(spec, "speckle")) == set()


def test_a_single_kana_bubble_is_small_but_it_is_not_speckle() -> None:
    """C-6: the floor discards speckle, it does not discard small bubbles. The
    kana is 252px and must survive at the shipped configuration."""
    spec = _spec("single-kana")
    prob, boxes = _render(spec)

    regions = regions_from_detection(prob, boxes, _page_size(spec))

    assert len(regions) == 1
    assert _set_pixels(regions[0]) >= _rect_pixels(_painted(spec, "kana"))


def test_a_component_of_exactly_the_floor_area_survives_and_one_pixel_less_does_not() -> None:
    """The boundary, either side of it, built from the constant itself.

    Two blobs in two boxes: one of exactly `MIN_REGION_AREA_PX` pixels and one of
    a single pixel fewer. Dilation is off so that the component area is the blob
    area and nothing else.

    Each blob is painted over two rows rather than one. A one-pixel-tall
    component has no interior and no polygon - `findContours` returns two points
    for it - and `RawRegion` refuses a ring of fewer than four vertices. That is
    the sliver rule of amendment A-12, pinned by its own test below; here it
    would only get in the way of the boundary this test is about.
    """
    width, height = 320, 240
    floor = MIN_REGION_AREA_PX
    prob = np.zeros((height, width), np.float32)
    for row, area in ((20, floor), (120, floor - 1)):
        prob[row, 20 : 20 + area - area // 2] = 1.0
        prob[row + 1, 20 : 20 + area // 2] = 1.0
    boxes = np.array(
        [
            [10, 10, 10 + floor + 20, 30, 0.9, 1],
            [10, 110, 10 + floor + 20, 130, 0.9, 1],
        ],
        dtype=np.float32,
    )

    regions = regions_from_detection(
        prob, boxes, (width, height), threshold=_EXPLICIT, dilate_iterations=0
    )

    assert len(regions) == 1
    assert _bbox(regions[0])[1] == 20


def test_a_component_one_pixel_thin_is_discarded_however_long_it_is() -> None:
    """Amendment A-12: a sliver is not a region, whatever its area.

    A 1x300 scanline of certainty is 300px - above any floor `single-kana`
    permits - and it is still not something MT-016 can typeset into or MT-019 can
    inpaint: it has no interior, so it has no polygon either, and `RawRegion`
    refuses a ring of fewer than four vertices. Discarding it with the speckle is
    the only answer that is not a crash at the page boundary of a real scan.

    Found in RED by running this suite against a reference implementation of the
    contract: the boundary test above produced exactly this shape and the domain
    type rejected it.
    """
    prob = np.zeros((240, 320), np.float32)
    prob[20, 10:310] = 1.0
    boxes = np.array([[0, 10, 320, 30, 0.9, 1]], dtype=np.float32)

    regions = regions_from_detection(
        prob, boxes, (320, 240), threshold=_EXPLICIT, dilate_iterations=0
    )

    assert regions == []


def test_the_shipped_threshold_is_a_probability_and_the_floor_is_a_speckle_floor() -> None:
    """The two constants GREEN derives, bracketed by the fixtures that pin them.

    `MASK_THRESHOLD` at 0.0 makes every pixel text and every page one region -
    the mutation D-1 names. The floor's bracket is `single-kana`'s own geometry:
    above 4 so the speckle dies, at most 252 so the kana lives.
    """
    assert 0.0 < MASK_THRESHOLD < 1.0
    assert 4 < MIN_REGION_AREA_PX <= 252
    assert DILATE_ITERATIONS >= 1


# -- AC-3: two components whose bounding boxes overlap -------------------------


def test_two_components_with_overlapping_bounding_boxes_stay_two_regions() -> None:
    """AC-3 at the shipped configuration.

    Two components can never share a pixel - that is what makes them one
    component - so "two components whose masks overlap" is the case where one
    bounding box lies inside the other. `B` sits in the notch of the L-shaped
    `A`, 16px clear, and one box covers them both: the count is a claim about
    connected components, not about boxes.
    """
    spec = _spec("overlapping-bubbles")
    prob, boxes = _render(spec)

    regions = regions_from_detection(prob, boxes, _page_size(spec))

    assert len(regions) == 2
    first, second = (_bbox(region) for region in regions)
    assert first[0] <= second[0] and first[1] <= second[1]
    assert first[2] >= second[2] and first[3] >= second[3], "B's bbox is inside A's"
    assert _set_pixels(regions[0]) & _set_pixels(regions[1]) == set()
    assert _set_pixels(regions[0]) & _rect_pixels((60, 60, 120, 120)) == set()
    assert _set_pixels(regions[1]) & _rect_pixels((20, 20, 140, 44)) == set()


def test_with_dilation_off_each_mask_is_exactly_its_own_component() -> None:
    """AC-3's "only its own pixels", at its strictest: set equality against the
    rectangles the fixture painted."""
    spec = _spec("overlapping-bubbles")
    prob, boxes = _render(spec)

    regions = regions_from_detection(
        prob, boxes, _page_size(spec), threshold=_EXPLICIT, dilate_iterations=0
    )

    the_l = _rect_pixels((20, 20, 140, 44)) | _rect_pixels((20, 44, 44, 140))
    assert [_set_pixels(region) for region in regions] == [the_l, _rect_pixels((60, 60, 120, 120))]


# -- AC-4: the page boundary ---------------------------------------------------


def test_every_polygon_lies_inside_the_page() -> None:
    """AC-4. The fixture's blobs are flush with x=0, y=0 and with the far corner,
    so a polygon written in exclusive-end coordinates puts a vertex at x=320 on a
    320px-wide page."""
    spec = _spec("page-edge")
    prob, boxes = _render(spec)
    width, height = _page_size(spec)

    regions = regions_from_detection(prob, boxes, (width, height))

    assert len(regions) == 2
    for region in regions:
        assert len(region.polygon) >= 4
        assert region.polygon[0] == region.polygon[-1], "the polygon is a closed ring"
        assert all(0 <= x < width and 0 <= y < height for x, y in region.polygon)
    assert {_bbox(region) for region in regions} == {(0, 0, 59, 49), (280, 200, 319, 239)}


def test_no_mask_pixel_lies_outside_its_polygons_bounding_box() -> None:
    """AC-4's second half, on a fixture where the two regions are at opposite
    corners: a mask that carried another region's pixels fails this by 1600px."""
    spec = _spec("page-edge")
    prob, boxes = _render(spec)

    regions = regions_from_detection(prob, boxes, _page_size(spec))

    for region in regions:
        xs = [x for x, _y in region.polygon]
        ys = [y for _x, y in region.polygon]
        outside = {
            (x, y)
            for x, y in _set_pixels(region)
            if not (min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys))
        }
        assert outside == set()


def test_dilation_grows_a_region_by_three_pixels_an_iteration_and_no_further() -> None:
    """C-4 step 5 is a 7x7 kernel, so one iteration grows a component by 3px in
    every direction and N iterations by 3N.

    This is what makes the 16px clearance in `overlapping-bubbles` and the 4px
    gap in `sfx` arithmetic rather than hope, so it is asserted directly instead
    of being inferred from them.
    """
    prob = np.zeros((240, 320), np.float32)
    prob[100:120, 100:130] = 1.0
    boxes = np.array([[0, 0, 320, 240, 0.9, 1]], dtype=np.float32)

    for iterations, grown in ((0, 0), (1, 3), (2, 6)):
        regions = regions_from_detection(
            prob, boxes, (320, 240), threshold=_EXPLICIT, dilate_iterations=iterations
        )
        assert len(regions) == 1, f"at {iterations} iterations"
        assert _bbox(regions[0]) == (
            100 - grown,
            100 - grown,
            129 + grown,
            119 + grown,
        ), f"at {iterations} iterations"


# -- AC-6: no region may touch an annotated SFX area ---------------------------


def test_no_region_touches_an_annotated_sfx_area_at_any_threshold_or_dilation() -> None:
    """AC-6, swept.

    The fixture carries two unboxed SFX blobs, a screentone field at 0.25 that a
    low threshold floods, and a boxed text blob whose box's exclusive right edge
    is the left edge of an annotated rectangle - so the mechanism is under
    pressure from three directions at once.

    Every sweep point also asserts that regions WERE produced. Measured in RED
    against the real page (MT-007 PO-1): the mask head alone covers 27-59% of
    every annotated SFX area at every threshold from 0.10 to 0.999, so zero SFX
    pixels is only meaningful alongside evidence that the detector found the
    text. Violations are accumulated and asserted once, so the failure message
    names every sweep point rather than the first.
    """
    spec = _spec("sfx")
    prob, boxes = _render(spec)
    rects = _rects(spec)
    page = _page_size(spec)

    violations: list[str] = []
    for threshold in _SWEPT_THRESHOLDS:
        for dilation in _SWEPT_DILATIONS:
            regions = regions_from_detection(
                prob, boxes, page, threshold=threshold, dilate_iterations=dilation
            )
            touched = _sfx_pixels(regions, rects)
            if touched or len(regions) != 2:
                violations.append(
                    f"threshold={threshold} dilation={dilation}:"
                    f" {touched} SFX px across {len(regions)} regions (want 0 across 2)"
                )

    assert violations == []


def test_the_same_fixture_with_the_sfx_rectangle_boxed_does_produce_a_region_there() -> None:
    """AC-6's named control, and the one the criterion insists on.

    Without it the assertion above passes against a detector that returns
    nothing. The control box is exactly the SFX blob's rectangle, so the region
    it produces is exactly 3600px at every threshold and every dilation: the blob
    fills the box, dilation grows it, and the second intersection clips it back.

    RED measured 3600 against 0 with a standard-library reference implementation
    of C-4 - the separation the orchestrator's probe on the real page measured as
    0px against 2319px. Confirming 3600 against the shipped module is GREEN's
    job: in RED this file did not load.
    """
    spec = _spec("sfx")
    prob, boxes = _render(spec)
    controlled = np.concatenate([boxes, _boxes(spec["control_boxes"])])
    rects = _rects(spec)
    page = _page_size(spec)

    measured: list[tuple[float, int, int]] = []
    for threshold in (0.05, 0.50, 0.95):
        for dilation in (0, 2):
            regions = regions_from_detection(
                prob, controlled, page, threshold=threshold, dilate_iterations=dilation
            )
            measured.append((threshold, dilation, _sfx_pixels(regions, rects)))

    assert [row[2] for row in measured] == [3600] * 6, measured


def test_the_metric_counts_thousands_of_pixels_when_nothing_fences_the_mask() -> None:
    """The control on the METRIC rather than on the pipeline.

    `_sfx_pixels` is what every assertion above leans on, and a metric that
    measured the wrong thing would make each of them look calibrated while
    proving nothing. This is the same count taken over the thresholded
    probability map with no box fence at all - the detector AC-6 exists to rule
    out - and it must be in the thousands.

    It touches no production code, so it passes the moment the imports resolve.
    It is kept because it is the negative half of a pair: on its own,
    "0 SFX pixels" is a statement about a metric nobody has seen return anything
    else.
    """
    spec = _spec("sfx")
    prob, _unused_boxes = _render(spec)
    annotated = set().union(*(_rect_pixels(rect) for rect in _rects(spec)))

    unfenced = {
        (int(x), int(y)) for y, x in zip(*np.nonzero(prob >= 0.50), strict=True)
    } & annotated
    flooded = {(int(x), int(y)) for y, x in zip(*np.nonzero(prob >= 0.05), strict=True)} & annotated

    assert len(unfenced) == 6000
    assert len(flooded) == 7024
