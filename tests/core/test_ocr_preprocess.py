"""`mangatl.ocr.preprocess`: the crop, and the tensor the encoder is handed.

Covers **AC-1** in full (the crop covers the polygon's bounding box plus
`CROP_PADDING_PX`, clipped to the page, at the region's own orientation) and
**AC-2** in full (224 x 224, stretched, normalised with the export's own
constants).

**AC-2 was amended during RED - see `## Amendments` A-1.** As filed it required
the crop to be *"resized preserving aspect ratio, padded rather than
stretched"*. It now requires the resize the export's own
`preprocessor_config.json` specifies: a `ViTImageProcessor` with `do_resize` and
an explicit height *and* width, which does **not** preserve aspect ratio.
`PAD_VALUE` left the contract with the amendment; there is no pad.

**`test_a_twenty_by_four_hundred_column_is_stretched_to_fill_the_whole_input` is
the assertion that discriminates the two rules**, and it is the reason this file
is not vacuous. Shape and dtype are identical under both geometries, so a test
pinning only those would have passed against the rule the amendment
*removed*. The discriminator is the **absence of a constant-valued border**: a
20 x 400 column fitted to 224 while preserving its aspect ratio is 11 px wide,
leaving 106 columns of pad down each side, and every one of those columns is
constant. Stretched, the content reaches all four corners and no row or column
of the output is constant at all.

That is why the fixture crop is a two-axis gradient rather than glyph-shaped
ink on a background: a crop whose own edges are blank has constant border
columns *before* any resize, and the discriminator would fire against a correct
implementation.

What else this file pins of AC-2:

* the output's shape, dtype and rank;
* `MODEL_INPUT_SIZE`, `PIXEL_MEAN` and `PIXEL_STD`, against the values RED read
  out of `preprocessor_config.json` - the documentary evidence A-1 rests on;
* the normalisation arithmetic, asserted on a crop that is **already
  224 x 224**, so the geometry cannot influence the result and a failure names
  the arithmetic rather than the resize;
* the greyscale collapse - `convert("L").convert("RGB")` - which upstream
  `manga-ocr` performs and `spikes/MT-002/ocr.py` reproduced, and which is a
  per-pixel property independent of any resize.

**What these tests are NOT evidence of.** They pin the geometry against the
export's shipped configuration, which is what A-1 decided on. They are not
evidence that stretching transcribes this corpus better: the orchestrator
measured 34 of 37 real pipeline regions transcribing byte-identically under
both geometries, and deferred verification 2 may legitimately not move. A
passing test here means "the pipeline does what the model's own processor
specifies", and nothing more.

**Nothing here loads a model** (`architecture.md` §2: logic is driven by fakes
in `tests/core` and read by the `unit` and `coverage` gates; the real weights
are `tests/integration`'s). `preprocess` owns arithmetic and no session, so it
needs no fake at all.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size. If a later story adds one,
every test and hook here needs one. The largest array built below is a
224 x 224 x 3 float crop; the dominant cost is `conftest._one_bit_png`, a
per-pixel Python loop, which is why the fixture page is 60 x 40 rather than
page-sized (MT-009 measured 281 ms for a 1125x1600 mask and 7 ms for a small
one, and a crop never looks at mask pixels).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from mangatl.domain.region import RawRegion
from mangatl.ocr.preprocess import (
    CROP_PADDING_PX,
    MODEL_INPUT_SIZE,
    PIXEL_MEAN,
    PIXEL_STD,
    crop_for_region,
    to_model_input,
)

# -- the fixture page ----------------------------------------------------------
#
# Small, and every pixel distinguishable from every other. That second property
# is the whole of AC-1's mechanism: a transpose, a flip or an off-by-one in
# either axis has to change at least one value, so `np.array_equal` against a
# hand-computed slice catches all of them without a model.

_PAGE_W, _PAGE_H = 60, 40


def _page() -> NDArray[np.uint8]:
    """A `(40, 60, 3)` uint8 page in which every pixel is unique.

    `page[y, x] == (index // 256, index % 256, 7)` for `index = y * 60 + x`.
    The largest index is 2399, so the first two channels together identify the
    pixel exactly, and the constant third channel is there so a test that
    accidentally compared only one channel would still be comparing an array of
    the right shape. Uniqueness is asserted in
    `test_the_fixture_page_distinguishes_every_pixel_from_every_other`, which is
    the control on the fixture itself.
    """
    index = np.arange(_PAGE_H * _PAGE_W, dtype=np.int32).reshape(_PAGE_H, _PAGE_W)
    page = np.empty((_PAGE_H, _PAGE_W, 3), dtype=np.uint8)
    page[:, :, 0] = (index // 256).astype(np.uint8)
    page[:, :, 1] = (index % 256).astype(np.uint8)
    page[:, :, 2] = 7
    return page


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    """A closed rectangular ring, which is what `RawRegion.polygon` requires."""
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def _region(mask: bytes, x0: int, y0: int, x1: int, y1: int) -> RawRegion:
    return RawRegion(polygon=_ring(x0, y0, x1, y1), mask=mask, confidence=0.5, kind="bubble")


# -- the fixture's own control -------------------------------------------------


def test_the_fixture_page_distinguishes_every_pixel_from_every_other() -> None:
    """The control on the fixture, not on the code.

    Without it, every AC-1 assertion below could be satisfied by a crop that had
    been transposed, flipped or shifted - because on a page with repeated values
    `np.array_equal` stops being able to tell those apart. This is the assertion
    that makes AC-1's "orientation unchanged" falsifiable at all.
    """
    page = _page()
    flat = page.reshape(-1, 3)

    assert len({tuple(int(v) for v in pixel) for pixel in flat}) == _PAGE_W * _PAGE_H
    # And the page is not square, so a whole-array transpose is not even
    # shape-compatible - which is a second, independent way the same mistake is
    # caught.
    assert page.shape[0] != page.shape[1]


# -- AC-1: the crop, its extent, and its orientation ---------------------------


def test_the_crop_is_the_pages_own_slice_at_the_regions_own_orientation(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1's core, and C-2's rule made enforceable without a model.

    `manga-ocr` is trained on vertical crops in their native orientation
    (`stack.md` §5/O6, confirmed by MT-002 E5 Test 2 box 02), so a
    "helpful" rotate, deskew or transpose in here turns readable input into
    out-of-distribution garbage. The four negative assertions are what make the
    positive one mean something: on a page whose every pixel is unique, a
    transpose, either flip or a 90-degree rotation all produce a different
    array, and each is named so a failure reads as a bug report.
    """

    page = _page()
    mask = one_bit_png(_PAGE_W, _PAGE_H, [(20, 12, 34, 30)])
    # Deliberately not square, and well inside the page, so `CROP_PADDING_PX`
    # applies on all four sides with no clipping.
    x0, y0, x1, y1 = 20, 12, 34, 30
    pad = CROP_PADDING_PX

    crop = crop_for_region(page, _region(mask, x0, y0, x1, y1))

    expected = page[y0 - pad : y1 + pad, x0 - pad : x1 + pad]
    assert crop.shape == expected.shape
    assert crop.dtype == np.uint8
    assert np.array_equal(crop, expected), (
        "the crop is not the page's slice at the region's own orientation"
    )
    # C-2, as four assertions rather than as a comment. Each of these is a
    # transformation some "tidy the input up" step would apply, and each is
    # forbidden.
    assert not np.array_equal(crop, np.transpose(expected, (1, 0, 2))), "the crop is transposed"
    assert not np.array_equal(crop, expected[::-1, :, :]), "the crop is flipped vertically"
    assert not np.array_equal(crop, expected[:, ::-1, :]), "the crop is flipped horizontally"
    assert not np.array_equal(crop, np.rot90(expected, 1)), "the crop is rotated 90 degrees"


def test_the_crop_covers_the_polygons_bounding_box_plus_the_padding(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1's extent clause, on a polygon that is **not** a rectangle.

    A non-convex ring whose bounding box is larger than any of its edges: a crop
    taken from the first two vertices, or from the polygon's mean, is a
    different rectangle and fails here. `CROP_PADDING_PX` is asserted as a
    *number of pixels added on each side*, so a constant read as a fraction, or
    applied on two sides only, is caught by the shape alone.
    """

    page = _page()
    mask = one_bit_png(_PAGE_W, _PAGE_H, [(18, 10, 40, 28)])
    # A zig-zag whose bounding box is (18, 10) - (40, 28).
    polygon = ((18, 10), (30, 14), (40, 10), (36, 28), (24, 20), (18, 28), (18, 10))
    region = RawRegion(polygon=polygon, mask=mask, confidence=0.25, kind="box")
    pad = CROP_PADDING_PX

    crop = crop_for_region(page, region)

    assert crop.shape == (28 - 10 + 2 * pad, 40 - 18 + 2 * pad, 3)
    assert np.array_equal(crop, page[10 - pad : 28 + pad, 18 - pad : 40 + pad])


def test_the_padding_is_clipped_to_the_page_at_every_edge(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1's "clipped to the page" clause, at all four edges and both corners.

    A region flush against an edge is not exotic: MT-002 E5 Test 2's box 00 is
    white text on solid black running to the panel border, and the detector's
    own boxes are clipped to the page by `decode_boxes`. An implementation that
    sliced with a negative start would silently take pixels from the *opposite*
    edge - `page[-2:6]` is empty, and `page[:, -2:40]` is empty too - so the
    consequence is an empty or wrong-sized crop rather than an exception.
    """

    page = _page()
    mask = one_bit_png(_PAGE_W, _PAGE_H, [(0, 0, 8, 8)])
    pad = CROP_PADDING_PX
    cases: tuple[tuple[str, tuple[int, int, int, int]], ...] = (
        ("top-left corner", (0, 0, 10, 8)),
        ("top edge", (20, 0, 32, 9)),
        ("left edge", (0, 15, 11, 27)),
        ("bottom-right corner", (_PAGE_W - 9, _PAGE_H - 7, _PAGE_W, _PAGE_H)),
        ("right edge", (_PAGE_W - 6, 14, _PAGE_W, 25)),
        ("bottom edge", (17, _PAGE_H - 5, 29, _PAGE_H)),
        ("the whole page", (0, 0, _PAGE_W, _PAGE_H)),
    )

    wrong: list[str] = []
    for name, (x0, y0, x1, y1) in cases:
        crop = crop_for_region(page, _region(mask, x0, y0, x1, y1))
        expected = page[
            max(0, y0 - pad) : min(_PAGE_H, y1 + pad),
            max(0, x0 - pad) : min(_PAGE_W, x1 + pad),
        ]
        if crop.shape != expected.shape or not np.array_equal(crop, expected):
            wrong.append(f"{name}: got shape {crop.shape}, want {expected.shape}")

    assert wrong == [], f"clipping is wrong at {len(wrong)} of {len(cases)} edges: {wrong}"


def test_the_crop_does_not_alias_the_page_so_a_later_write_cannot_reach_back(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1's quiet half: the scans are read-only to this app (`architecture.md`
    §5), and a crop that is a *view* onto the page makes that a matter of luck.

    A numpy slice shares memory with its base. `to_model_input` does not write
    through it today, but "does not today" is not a property anyone can rely on,
    and a page array is handed to nine regions in a row. Asserted by writing to
    the crop and reading the page back, which is the observable consequence
    rather than a claim about `.base`.
    """

    page = _page()
    mask = one_bit_png(_PAGE_W, _PAGE_H, [(20, 12, 34, 30)])
    before = page.copy()

    crop = crop_for_region(page, _region(mask, 20, 12, 34, 30))
    crop[:] = 0

    assert np.array_equal(page, before), "the crop aliases the page: writing to it changed the scan"


def test_the_crop_padding_is_a_positive_pixel_count_small_against_a_real_bubble() -> None:
    """C-6: `CROP_PADDING_PX` is a pixel count at a stated scan resolution, and
    it is a margin rather than a second detector.

    The bounds are measured, not taste. RED ran the real detector over
    `spikes/MT-002/pages/014.jpg` (1125 x 1600) and its nine boxes are between
    52 and 194 px wide and 96 and 225 px tall; transcription was **byte
    identical at 0, 4 and 8 px of padding** on all nine. So any value in this
    range is defensible and a value near a whole bubble is not: at 48 px, the
    narrowest box grows from 52 to 148 px and swallows its neighbouring column,
    which is the failure E5's method note warns about from the other direction.
    """
    assert isinstance(CROP_PADDING_PX, int)
    assert not isinstance(CROP_PADDING_PX, bool)
    assert 0 < CROP_PADDING_PX <= 32, (
        f"CROP_PADDING_PX is {CROP_PADDING_PX}: at a scan width of 1125 the detector's"
        " own boxes are 52-194 px wide, so this is not a margin"
    )


# -- AC-2, the part that does not depend on the escalated geometry clause ------


def test_the_model_input_size_and_normalisation_constants_are_the_exports_own() -> None:
    """AC-2's "the constants the audit records", read out of the export itself.

    MEASURED IN RED from
    `spikes/MT-002/models/manga-ocr-base-ONNX/preprocessor_config.json`, which is
    a file rather than an inference:

        "image_mean": [0.5, 0.5, 0.5], "image_std": [0.5, 0.5, 0.5],
        "rescale_factor": 0.00392156862745098, "resample": 2,
        "size": {"height": 224, "width": 224}

    and confirmed against the graph's own signature, also measured in RED:
    `encoder_model.onnx` takes `pixel_values [batch, num_channels, height,
    width]` and returns `last_hidden_state [batch, 197, 768]` - 197 being
    `(224/16)^2 + 1`, the DeiT patch grid plus its class token, which is what
    fixes 224 rather than leaves it configurable.

    `MODEL_INPUT_SIZE` is `(width, height)` per C-1. It is square, so no test can
    tell the two orders apart here; the order is pinned by the contract and by
    `to_model_input`'s call site, and is restated in the handoff.
    """
    assert MODEL_INPUT_SIZE == (224, 224)
    assert PIXEL_MEAN == 0.5
    assert PIXEL_STD == 0.5


def test_a_crop_already_at_the_model_size_is_normalised_pixel_for_pixel() -> None:
    """AC-2's normalisation, on the one crop shape where the escalated geometry
    clause cannot change the answer.

    The crop is **exactly** `MODEL_INPUT_SIZE`, so "pad to the model's aspect
    ratio then resize" and "resize to the model's size" are the identical
    operation and this assertion holds under either resolution of AC-2. What it
    pins is the arithmetic: rescale by 1/255 to [0, 1], then `(x - PIXEL_MEAN) /
    PIXEL_STD` to [-1, 1]. The three grey levels are chosen so that an
    implementation which skipped the rescale, skipped the shift, or divided by
    255 twice lands somewhere visibly different at each of them.
    """
    width, height = MODEL_INPUT_SIZE
    for level in (0, 128, 255):
        crop = np.full((height, width, 3), level, dtype=np.uint8)

        tensor = to_model_input(crop, MODEL_INPUT_SIZE)

        expected = (level / 255.0 - PIXEL_MEAN) / PIXEL_STD
        assert tensor.shape == (1, 3, height, width)
        assert tensor.dtype == np.float32
        assert np.allclose(tensor, expected, atol=1e-5), (
            f"a uniform crop of {level} normalised to {float(tensor.flat[0])}, not {expected}"
        )
    # The endpoints of the range, stated as themselves: 0 -> -1 and 255 -> +1 is
    # what "[-1, 1]" means, and a mean or std of anything but 0.5 breaks it.
    assert np.allclose(
        to_model_input(np.zeros((height, width, 3), np.uint8), MODEL_INPUT_SIZE), -1.0
    )
    assert np.allclose(
        to_model_input(np.full((height, width, 3), 255, np.uint8), MODEL_INPUT_SIZE), 1.0
    )


def test_the_three_channels_come_out_equal_because_the_crop_is_read_as_greyscale() -> None:
    """AC-2's channel handling, and it is a per-pixel property with no geometry
    in it, so it holds under either resolution of the escalated clause.

    Upstream `manga-ocr` does `img.convert("L").convert("RGB")` before the
    processor sees it, and `spikes/MT-002/ocr.py` - the script that measured
    10/12 against the author's own ground truth - reproduces exactly that. The
    encoder therefore never sees colour, and a three-channel tensor whose
    channels differ is a different input from the one every number in MT-002 E5
    was measured on.

    The crop is strongly coloured and **asymmetric between channels**, so an
    implementation that merely transposed RGB into CHW without the greyscale
    collapse fails, and one that dropped two channels fails on the value.
    """
    width, height = MODEL_INPUT_SIZE
    crop = np.empty((height, width, 3), dtype=np.uint8)
    crop[:, :, 0] = 200
    crop[:, :, 1] = 60
    crop[:, :, 2] = 10

    tensor = to_model_input(crop, MODEL_INPUT_SIZE)

    assert tensor.shape == (1, 3, height, width)
    assert np.array_equal(tensor[0, 0], tensor[0, 1]), "channels R and G differ: no greyscale step"
    assert np.array_equal(tensor[0, 1], tensor[0, 2]), "channels G and B differ: no greyscale step"


def _gradient(width: int, height: int) -> NDArray[np.uint8]:
    """A crop with a two-axis gradient and **no constant row or column anywhere**.

    `value(y, x) = 10 + (y * 180) // height + (x * 60) // width`, replicated
    across three channels so the greyscale collapse is the identity on it and
    the expected corner values can be written down exactly.

    Why a gradient and not ink on a background: the geometry assertion below
    fires on a **constant-valued border**, and a crop shaped like real text has
    blank margins, so its own border rows and columns are constant before any
    resize touches them. Against such a crop the discriminator would fail on a
    correct implementation, which is the trap this helper exists to avoid.

    Range is 10 to 246 - inside `uint8` at both ends, so nothing clips and the
    corner values are exact rather than saturated.
    """
    ys = (np.arange(height, dtype=np.int32) * 180) // height
    xs = (np.arange(width, dtype=np.int32) * 60) // width
    values = (10 + ys[:, None] + xs[None, :]).astype(np.uint8)
    return np.repeat(values[:, :, None], 3, axis=2)


def _normalise(level: int) -> float:
    """One grey level through AC-2's normalisation, as a plain float."""
    return (level / 255.0 - PIXEL_MEAN) / PIXEL_STD


def _constant_border(plane: NDArray[np.float32]) -> dict[str, int]:
    """How many constant rows and columns run in from each edge of `plane`.

    All four counts are zero for a stretched gradient. For a crop fitted to 224
    while preserving a 1:20 aspect ratio, the content is 11 px wide and two of
    these counts are about 106 - which is the number the failure message needs
    to carry, because it names the padding directly.
    """
    rows_constant = [bool(np.ptp(row) == 0.0) for row in plane]
    cols_constant = [bool(np.ptp(column) == 0.0) for column in plane.T]

    def run(flags: list[bool]) -> int:
        count = 0
        for flag in flags:
            if not flag:
                break
            count += 1
        return count

    return {
        "top": run(rows_constant),
        "bottom": run(rows_constant[::-1]),
        "left": run(cols_constant),
        "right": run(cols_constant[::-1]),
    }


def test_a_twenty_by_four_hundred_column_is_stretched_to_fill_the_whole_input() -> None:
    """**AC-2's geometry, as amended by A-1**, on the aspect ratio that occurs.

    A 20 x 400 column is the shape a tight vertical Japanese crop really has.
    The export's `preprocessor_config.json` is a `ViTImageProcessor` with
    `do_resize: true` and `size: {height: 224, width: 224}` - an explicit height
    *and* width, which resizes to exactly that and does **not** preserve aspect
    ratio. So the column's content must reach all four corners of the tensor.

    **This is the assertion that discriminates the amended rule from the one it
    replaced, and shape and dtype are not it.** Both geometries return
    `(1, 3, 224, 224)` float32 in [-1, 1]; a test pinning only that would pass
    against padding and prove nothing. What separates them is the border: fitting
    20 x 400 inside 224 while preserving the ratio gives 11 content columns and
    **106 constant pad columns down each side**, whichever value the pad takes and
    wherever the content is aligned. Stretched, no row or column of the output is
    constant at all.

    The corner assertion is the positive half of the same claim, and it is
    interpolation-independent to within its tolerance: output pixel (0, 0) samples
    the crop within a fraction of an input pixel of crop (0, 0) under bilinear
    upscaling, area downscaling or nearest. The crop's corners are 10, 67, 189 and
    246, which span the range, so no single pad value can be within tolerance of
    all four - the tolerance is 0.10 on the [-1, 1] scale, about 13 grey levels,
    and the closest pair of corners is 57 levels apart.
    """
    width, height = MODEL_INPUT_SIZE
    column = _gradient(20, 400)
    # The fixture's own control. If this ever fails the discriminator below is
    # measuring the crop's blank margins rather than the resize's padding.
    assert _constant_border(column[:, :, 0].astype(np.float32)) == {
        "top": 0,
        "bottom": 0,
        "left": 0,
        "right": 0,
    }, "the fixture crop has a constant border of its own, so it cannot discriminate"

    tensor = to_model_input(column, MODEL_INPUT_SIZE)

    assert tensor.shape == (1, 3, height, width)
    assert tensor.dtype == np.float32
    assert float(tensor.min()) >= -1.0
    assert float(tensor.max()) <= 1.0

    plane = tensor[0, 0]
    assert _constant_border(plane) == {"top": 0, "bottom": 0, "left": 0, "right": 0}, (
        "the tensor has a constant-valued border, which is what padding to the"
        " model's aspect ratio produces - a 20x400 column fitted inside 224 is 11 px"
        " wide with 106 pad columns each side. AC-2 as amended (A-1) specifies the"
        " resize the export's own ViTImageProcessor performs, which stretches."
    )
    # And not only at the edges: a stretched gradient has no constant line
    # anywhere, so a pad band placed off-centre is caught too.
    assert not any(bool(np.ptp(row) == 0.0) for row in plane), "a row of the tensor is constant"
    assert not any(bool(np.ptp(col) == 0.0) for col in plane.T), (
        "a column of the tensor is constant"
    )

    corners = {
        "top-left": (float(plane[0, 0]), _normalise(10)),
        "top-right": (float(plane[0, -1]), _normalise(67)),
        "bottom-left": (float(plane[-1, 0]), _normalise(189)),
        "bottom-right": (float(plane[-1, -1]), _normalise(246)),
    }
    wrong = {
        name: (round(got, 4), round(want, 4))
        for name, (got, want) in corners.items()
        if abs(got - want) > 0.10
    }
    assert wrong == {}, (
        f"{len(wrong)} of the tensor's four corners do not carry the crop's own"
        f" corners: {wrong}. The content does not reach the edge of the input, so it"
        " was fitted inside rather than stretched across."
    )
