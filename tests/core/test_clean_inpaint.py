"""`mangatl.clean.inpaint.clean_page`: one page cleaned through a fake inpainter (MT-019).

Covers AC-2 (the inpainter's patch lands exactly inside the erase mask, on both
the native and the downscale path), AC-3 (every erase-mask pixel is a hole in
exactly one call, and a connected component never spans two calls), AC-4
(every pixel outside the erase mask is byte-identical to the source - exact
equality, no tolerance, no `allclose`) and the window half of AC-5 (masks at the
page edges and pages smaller than 512 px on an axis, without an index error and
with AC-4 intact).

**The fake is a discriminating double, not a mirror** (C-6):

* it checks the calling convention on **every** call - `image` is `float32`
  `(1, 3, 512, 512)` in `[0, 1]`, `mask` is `float32` `(1, 1, 512, 512)` with
  values in `{0.0, 1.0}` - records the violation and raises, so a breach fails
  the test that caused it rather than a later assertion about pixels;
* in **constant** mode it returns `(17, 34, 51)` everywhere in model scale
  (`[0, 255]`, C-2), so the 8-bit result is exactly that colour - AC-2;
* in **inverted** mode it returns `255 - 255 * image`, which differs from the
  source at **every** pixel of the window, hole or not (`255 - v == v` has no
  integer solution). A clean_page that pasted the whole window back, rather than
  only the hole, changes pixels outside the mask and fails AC-4. A fake that
  preserved non-hole pixels - as the real export does, C-2 - would let that
  defect through.

**The page encodes its own coordinates** (`_coded_page`): `R = x mod 256`,
`G = y mod 256`, `B = 16 * (x // 256) + y // 256`, unique for pages up to
4096 px a side. So every recorded call can be decoded without knowing where
the implementation placed its window, and two things become observable that a
uniform page hides: (1) that the pixels the model is told are holes are
**exactly** the component's page pixels (`_hole_page_indices`), and (2) that the
inverted patch written back lands on the pixel it was computed from
(`result == 255 - page` inside the mask). Hole pixels are never modified before
their own call, so their decoded coordinates are always the original ones.

**Masks are handed to `clean_page` directly** for AC-3/AC-4/AC-5, built by hand
from rectangles, so the component structure is known exactly. The AC-2 headline
test and one AC-4 test go through `erase_mask` from region PNGs, as production
will.

**MT-151 adds a third path, strips** (C-2, C-3): a component long on exactly
one axis is cleaned at native resolution in overlapping 512-px windows along
that axis, each cut from the working result. Its tests use the **stamped**
fake, which fills every call with a colour unique to that call (`_stamp`), so
the result shows which call wrote each pixel and a later window shows which
earlier call's output it was cut from. Every window origin, mask and
write-back band is a pinned number worked from C-3's rule (`_STRIP_CASES`),
never re-derived from it here. AC-3 of MT-019 ("a component never spans two
calls") now holds for the native and downscale paths only; C-3 makes a strip
component span several calls by design, and AC-1's "written exactly once" is
the property that replaces it there. Holes long on **both** axes keep the
downscale tests (C-6).

**MT-153 adds the flat-paper fill** (C-2), ahead of the three paths: a
component whose ring - its elliptical dilation by `FLAT_RING_PX`, minus the
whole erase mask, clipped to the page - has a per-channel spread at or under
`FLAT_MAX_SPREAD` is filled with the ring's lower median and never shown to the
model. Its tests are the last block of this file. Both constants are read late
(`_shipped`) or set with `monkeypatch(raising=False)`, so the file imports
before GREEN; the AC fixtures hold for any `FLAT_RING_PX` in 1..16 and
`FLAT_MAX_SPREAD` in 4..64 (C-6), and the boundary tests set their own values.
The ring, spread, median and `ghost` they judge by are computed here from the
rectangles and the element, never by production's helper (C-4). Tests above
whose hole sits on uniform paper carry C-5's one-line off switch,
`FLAT_MAX_SPREAD = -1`, so they keep testing the model's path.

Nothing here loads a model. No per-test timeout exists in this project
(`pytest-timeout` is not a dependency), so there is no budget to size; the
largest page here is 2000x1414 and every call is one 512x512 float array.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from io import BytesIO
from itertools import pairwise
from typing import Any, Literal

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.clean import inpaint as inpaint_module
from mangatl.clean.inpaint import MIN_CONTEXT_PX, clean_page
from mangatl.clean.mask import erase_mask
from mangatl.clean.session import MODEL_INPUT_SIDE, InpaintSession
from mangatl.domain.region import RawRegion

_SIDE = 512

#: The constant patch, in model scale. Distinct per channel so a channel swap
#: on the way back (RGB read as BGR) is a different colour, not the same one.
_PATCH = (17, 34, 51)

#: The largest bbox side the native path takes: `512 - 2 * MIN_CONTEXT_PX`.
_NATIVE_LIMIT = _SIDE - 2 * 32


def _stamp(call: int) -> tuple[int, int, int]:
    """The stamped fake's colour for its `call`-th call (0-based): distinct per
    call and per channel, and never white, so it cannot pass for the white page
    of the context test or for a neighbouring call's output."""
    return (8 + 16 * call, 200 - 16 * call, 100 + call)


# -- the fake session ----------------------------------------------------------


@dataclass
class FakeInpaintSession:
    """An `InpaintSession` that checks C-2's convention and records every call."""

    mode: Literal["constant", "inverted", "stamped"]
    calls: list[tuple[NDArray[np.float32], NDArray[np.float32]]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def run(self, image: NDArray[np.float32], mask: NDArray[np.float32]) -> NDArray[np.float32]:
        problems = _convention_problems(image, mask)
        if problems:
            self.violations.extend(problems)
            raise AssertionError(f"C-2 calling convention violated: {problems}")
        self.calls.append((image.copy(), mask.copy()))
        if self.mode in ("constant", "stamped"):
            colour = _PATCH if self.mode == "constant" else _stamp(len(self.calls) - 1)
            out = np.empty((1, 3, _SIDE, _SIDE), dtype=np.float32)
            for channel, value in enumerate(colour):
                out[0, channel] = value
            return out
        return (255.0 - 255.0 * image).astype(np.float32)

    def get_providers(self) -> Sequence[str]:
        return ["FakeExecutionProvider"]

    def hole_counts(self) -> list[int]:
        return [int((mask == 1.0).sum()) for _image, mask in self.calls]


def _convention_problems(image: object, mask: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(image, np.ndarray):
        return [f"image is a {type(image).__name__}, not an ndarray"]
    if not isinstance(mask, np.ndarray):
        return [f"mask is a {type(mask).__name__}, not an ndarray"]
    if image.dtype != np.float32:
        problems.append(f"image dtype {image.dtype}, expected float32")
    if image.shape != (1, 3, _SIDE, _SIDE):
        problems.append(f"image shape {image.shape}, expected (1, 3, 512, 512)")
    if image.size and (float(image.min()) < 0.0 or float(image.max()) > 1.0):
        problems.append(
            f"image range [{float(image.min())}, {float(image.max())}], expected within [0, 1]"
        )
    if mask.dtype != np.float32:
        problems.append(f"mask dtype {mask.dtype}, expected float32")
    if mask.shape != (1, 1, _SIDE, _SIDE):
        problems.append(f"mask shape {mask.shape}, expected (1, 1, 512, 512)")
    values = set(np.unique(mask).tolist())
    if not values <= {0.0, 1.0}:
        problems.append(f"mask values {sorted(values)[:5]}, expected only 0.0 and 1.0")
    return problems


# -- page and mask builders ------------------------------------------------------


def _coded_page(width: int, height: int) -> NDArray[np.uint8]:
    """An RGB page whose every pixel encodes its own `(x, y)`. See the docstring."""
    ys, xs = np.mgrid[0:height, 0:width]
    page = np.empty((height, width, 3), dtype=np.uint8)
    page[..., 0] = xs % 256
    page[..., 1] = ys % 256
    page[..., 2] = 16 * (xs // 256) + ys // 256
    return page


def _decode(image: NDArray[np.float32]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """The page `(x, y)` each pixel of a recorded `(1, 3, H, W)` image came from."""
    v = np.rint(image[0].astype(np.float64) * 255.0).astype(np.int64)
    xs = 256 * (v[2] // 16) + v[0]
    ys = 256 * (v[2] % 16) + v[1]
    return xs, ys


def _hole_page_indices(
    call: tuple[NDArray[np.float32], NDArray[np.float32]], width: int
) -> NDArray[np.int64]:
    """Sorted flat page indices `y * width + x` of the pixels a call marked as holes."""
    image, mask = call
    xs, ys = _decode(image)
    holes = mask[0, 0] == 1.0
    return np.sort(ys[holes] * width + xs[holes])


def _indices(mask: NDArray[np.bool_]) -> NDArray[np.int64]:
    """Sorted flat indices of a page mask's set pixels."""
    return np.flatnonzero(mask).astype(np.int64)


def _mask(size: tuple[int, int], *rects: tuple[int, int, int, int]) -> NDArray[np.bool_]:
    """A `(height, width)` mask with every half-open `(x0, y0, x1, y1)` set."""
    width, height = size
    mask = np.zeros((height, width), dtype=bool)
    for x0, y0, x1, y1 in rects:
        mask[y0:y1, x0:x1] = True
    return mask


def _region(mask: NDArray[np.bool_]) -> RawRegion:
    buffer = BytesIO()
    Image.fromarray(mask).save(buffer, format="PNG")
    return RawRegion(
        polygon=((0, 0), (1, 0), (1, 1), (0, 0)),
        mask=buffer.getvalue(),
        confidence=0.9,
        kind="bubble",
    )


def _components(mask: NDArray[np.bool_]) -> list[NDArray[np.bool_]]:
    """The 8-connected components of `mask`, in ascending label order."""
    count, labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    return [labels == label for label in range(1, count)]


def _window_origin(image: NDArray[np.float32]) -> tuple[int, int]:
    """The page `(x0, y0)` of a recorded native window: the most common
    `decoded - position` offset, so pixels an earlier call rewrote are outvoted."""
    xs, ys = _decode(image)
    rows, cols = np.mgrid[0 : xs.shape[0], 0 : xs.shape[1]]
    dx, dy = (xs - cols).ravel(), (ys - rows).ravel()
    pairs, counts = np.unique(np.stack([dx, dy], axis=1), axis=0, return_counts=True)
    x0, y0 = pairs[int(np.argmax(counts))]
    return int(x0), int(y0)


def _assert_outside_untouched(
    result: NDArray[np.uint8], page: NDArray[np.uint8], mask: NDArray[np.bool_]
) -> None:
    """AC-4, exactly: every pixel outside `mask` is byte-identical."""
    outside = ~mask
    changed = int((result[outside] != page[outside]).any(axis=1).sum())
    assert changed == 0, f"{changed} pixels outside the erase mask were modified"
    assert np.array_equal(result[outside], page[outside])


# -- the pinned constants ----------------------------------------------------------


def test_the_model_input_side_and_minimum_context_are_the_pinned_values() -> None:
    """C-2 (`lama_fp32.onnx` takes 512x512, MT-002 E3) and C-4 (PO decision 32)."""
    assert MODEL_INPUT_SIDE == 512
    assert MIN_CONTEXT_PX == 32


def test_the_fake_satisfies_the_inpaint_session_protocol() -> None:
    """The double is typed against the shipped Protocol, so a drift in `run`'s
    signature is a mypy error here rather than a silent mismatch."""
    session: InpaintSession = FakeInpaintSession("constant")
    assert list(session.get_providers()) == ["FakeExecutionProvider"]


# -- input validation and the empty mask -----------------------------------------


def test_an_all_false_mask_returns_an_equal_copy_without_calling_the_model() -> None:
    """C-4: nothing to erase means zero calls, and a new array, not the input."""
    page = _coded_page(300, 200)
    fake = FakeInpaintSession("inverted")

    result = clean_page(page, np.zeros((200, 300), dtype=bool), fake)

    assert fake.calls == []
    assert result is not page
    assert result.dtype == np.uint8
    assert np.array_equal(result, page)


@pytest.mark.parametrize(
    ("label", "page", "mask"),
    [
        ("page is 2-D", np.zeros((200, 300), np.uint8), np.zeros((200, 300), bool)),
        ("page has 4 channels", np.zeros((200, 300, 4), np.uint8), np.zeros((200, 300), bool)),
        ("page is float", np.zeros((200, 300, 3), np.float32), np.zeros((200, 300), bool)),
        ("mask is uint8", np.zeros((200, 300, 3), np.uint8), np.zeros((200, 300), np.uint8)),
        ("mask is 3-D", np.zeros((200, 300, 3), np.uint8), np.zeros((200, 300, 1), bool)),
        ("mask is transposed", np.zeros((200, 300, 3), np.uint8), np.zeros((300, 200), bool)),
    ],
)
def test_a_malformed_page_or_mask_is_refused(label: str, page: Any, mask: Any) -> None:
    """C-4: `ValueError` for a page that is not `(H, W, 3)` uint8, a mask that is
    not 2-D bool, or shapes that disagree - never a silent transpose."""
    with pytest.raises(ValueError):
        clean_page(page, mask, FakeInpaintSession("constant"))


def test_neither_input_is_mutated() -> None:
    """C-4: a new array is returned; page and mask are left as they were."""
    page = _coded_page(800, 600)
    mask = _mask((800, 600), (100, 100, 160, 140), (500, 300, 540, 420))
    page_before, mask_before = page.copy(), mask.copy()

    result = clean_page(page, mask, FakeInpaintSession("inverted"))

    assert np.array_equal(page, page_before)
    assert np.array_equal(mask, mask_before)
    assert result.shape == page.shape
    assert result.dtype == np.uint8
    assert not np.shares_memory(result, page)


# -- the calling convention, observed ----------------------------------------------


def test_the_model_sees_the_window_in_rgb_order_scaled_to_the_unit_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-6: on a page whose R, G and B differ, channel `c` of the model input is
    the page's channel `c` / 255 - RGB order and normalisation, without a model.

    The page is uniform per channel, so the assertion holds wherever the window
    was placed; placement is pinned by the coded-page tests below.
    """
    monkeypatch.setattr(inpaint_module, "FLAT_MAX_SPREAD", -1, raising=False)  # MT-153 C-5
    page = np.empty((700, 900, 3), dtype=np.uint8)
    page[..., 0], page[..., 1], page[..., 2] = 10, 100, 200
    mask = _mask((900, 700), (400, 300, 440, 360))
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == 1
    image, _mask_in = fake.calls[0]
    # A tolerance of 1e-6 absorbs only the last-ulp difference between dividing
    # in float32 and in float64; a channel swap moves a value by >= 90/255 and a
    # missing normalisation by a factor of 255.
    for channel, value in enumerate((10, 100, 200)):
        np.testing.assert_allclose(
            image[0, channel], np.full((_SIDE, _SIDE), value / 255.0), rtol=0, atol=1e-6
        )


def test_the_hole_the_model_is_given_is_exactly_the_components_page_pixels() -> None:
    """C-4 step 5 and C-2: `1.0` = hole, and the holes are this component's own
    pixels, at their own page positions - not shifted, flipped or inverted."""
    size = (1000, 800)
    page = _coded_page(*size)
    mask = _mask(size, (420, 330, 470, 420), (470, 380, 520, 400))
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == 1
    assert np.array_equal(_hole_page_indices(fake.calls[0], size[0]), _indices(mask))


def test_a_native_window_is_an_unresampled_512_square_of_the_page() -> None:
    """C-4 step 3: native resolution, centred on the component, inside the page.

    Every pixel of the window decodes to `(x0 + col, y0 + row)` - no resize, no
    flip - and `x0, y0` is the bbox centre minus 256, give or take the rounding
    of a centre (1 px).
    """
    size = (1200, 1000)
    page = _coded_page(*size)
    bbox = (580, 470, 620, 530)  # centre (600, 500)
    mask = _mask(size, bbox)
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    image, _ = fake.calls[0]
    xs, ys = _decode(image)
    x0, y0 = int(xs[0, 0]), int(ys[0, 0])
    rows, cols = np.mgrid[0:_SIDE, 0:_SIDE]
    assert np.array_equal(xs, x0 + cols), "the window's columns are not consecutive page columns"
    assert np.array_equal(ys, y0 + rows), "the window's rows are not consecutive page rows"
    assert abs(x0 - (600 - 256)) <= 1
    assert abs(y0 - (500 - 256)) <= 1


# -- AC-2: the patch lands exactly inside the erase mask ----------------------------


def test_the_inpainters_patch_fills_exactly_the_dilated_region_masks() -> None:
    """AC-2, as production will run it: regions -> `erase_mask` -> `clean_page`.
    Inside the erase mask every pixel is the fake's `(17, 34, 51)`; outside,
    nothing moved."""
    size = (1125, 1600)
    page = _coded_page(*size)
    regions = [
        _region(_mask(size, (100, 120, 180, 300))),
        _region(_mask(size, (700, 900, 760, 1100))),
        _region(_mask(size, (720, 1050, 820, 1150))),
    ]
    mask = erase_mask(regions, size)
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert fake.violations == []
    assert np.array_equal(
        result[mask], np.broadcast_to(np.array(_PATCH, dtype=np.uint8), (int(mask.sum()), 3))
    )
    _assert_outside_untouched(result, page, mask)


def test_inside_the_mask_each_pixel_is_the_model_output_for_that_same_pixel() -> None:
    """AC-2 with a patch that varies: the inverted fake's output is `255 - v`, so
    `result == 255 - page` inside the mask only if the patch was written back to
    the pixel it was computed from, in the same channel order, at scale 255."""
    size = (1200, 1000)
    page = _coded_page(*size)
    mask = _mask(size, (100, 100, 200, 180), (900, 700, 1000, 820), (600, 120, 640, 400))
    fake = FakeInpaintSession("inverted")

    result = clean_page(page, mask, fake)

    assert fake.violations == []
    assert np.array_equal(result[mask], 255 - page[mask])


#: MT-151 C-6: a hole long on **both** axes, so it still takes the downscale
#: path (a hole long on one axis now takes strips). 460 x 600 on an 800 x 1000
#: page; the crop is bbox + 32 a side, `[138, 662) x [168, 832)`, 524 x 664.
_DOWNSCALE_RECT = (170, 200, 630, 800)


def test_the_downscale_path_also_fills_exactly_the_mask_with_the_patch() -> None:
    """AC-2, C-6: a component past 448 px on both axes goes through the downscale
    path, and the patch still covers every mask pixel exactly - resized back,
    cropped, and written only into the hole."""
    size = (800, 1000)
    page = _coded_page(*size)
    mask = _mask(size, _DOWNSCALE_RECT)  # 460 x 600: past the native limit on both axes
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == 1
    assert np.array_equal(
        result[mask], np.broadcast_to(np.array(_PATCH, dtype=np.uint8), (int(mask.sum()), 3))
    )
    _assert_outside_untouched(result, page, mask)


def test_the_downscale_path_scales_the_crop_to_512_on_its_long_side_and_edge_pads() -> None:
    """C-4 step 4: crop = bbox + 32 px a side (524 x 664 here), scaled by
    512 / 664 to 404 x 512 with `INTER_AREA` (measured in MT-151 RED with a
    standalone resize: `round(524 * 512 / 664) = 404`), padded right to 512 with
    the edge column. Columns 404..511 of the model input all repeat column 403."""
    size = (800, 1000)
    page = _coded_page(*size)
    mask = _mask(size, _DOWNSCALE_RECT)
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert len(fake.calls) == 1
    image, model_mask = fake.calls[0]
    assert np.array_equal(
        image[0, :, :, 404:], np.repeat(image[0, :, :, 403:404], _SIDE - 404, axis=2)
    )
    assert not np.array_equal(image[0, :, :, 403], image[0, :, :, 402]), (
        "column 403 must still be real page content, not padding"
    )
    assert not model_mask[0, 0, :, 404:].any(), "the mask is padded with False"


def test_on_the_downscale_path_no_hole_pixel_survives_as_visible_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-4 step 4: the resized hole is thresholded `> 0`, so every model pixel
    that a hole pixel contributed to is itself a hole. On a white page with a
    black hole, every model pixel left visible is pure white.

    Measured in MT-151 RED with a standalone resize of this exact fixture (the
    460 x 600 hole): `> 0` leaves 0 non-white visible pixels; `> 0.5` would
    leave 1636, minimum 171.
    """
    monkeypatch.setattr(inpaint_module, "FLAT_MAX_SPREAD", -1, raising=False)  # MT-153 C-5
    size = (800, 1000)
    page = np.full((1000, 800, 3), 255, dtype=np.uint8)
    mask = _mask(size, _DOWNSCALE_RECT)
    page[mask] = 0
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert len(fake.calls) == 1
    image, model_mask = fake.calls[0]
    visible = image[0][:, model_mask[0, 0] == 0.0]
    assert np.array_equal(visible, np.ones_like(visible)), (
        f"{int((visible < 1.0).any(axis=0).sum())} visible model pixels carry ink from the hole"
    )


def _is_unresampled_crop(image: NDArray[np.float32], mask: NDArray[np.bool_]) -> bool:
    """Whether a recorded window is an unresampled crop of the coded page: at
    every window position whose page pixel lies inside the page and outside
    the erase mask - pixels no call ever rewrites - the decoded coordinate is
    the window origin plus the position. A resized crop fails it."""
    x0, y0 = _window_origin(image)
    xs, ys = _decode(image)
    rows, cols = np.mgrid[0:_SIDE, 0:_SIDE]
    px, py = x0 + cols, y0 + rows
    height, width = mask.shape
    inside = (px >= 0) & (px < width) & (py >= 0) & (py < height)
    check = inside.copy()
    check[inside] = ~mask[py[inside], px[inside]]
    return bool(check.any() and (xs[check] == px[check]).all() and (ys[check] == py[check]).all())


@pytest.mark.parametrize(
    ("bbox", "calls", "unresampled"),
    [
        ((20, _NATIVE_LIMIT), 1, True),  # native
        ((_NATIVE_LIMIT, _NATIVE_LIMIT), 1, True),  # native, at the limit on both axes
        ((20, _NATIVE_LIMIT + 1), 2, True),  # strips along y
        ((_NATIVE_LIMIT + 1, 20), 2, True),  # strips along x
        ((_NATIVE_LIMIT, _NATIVE_LIMIT + 1), 2, True),  # strips along y, 448 wide
        ((_NATIVE_LIMIT + 1, _NATIVE_LIMIT + 1), 1, False),  # downscale
    ],
    ids=["20x448", "448x448", "20x449", "449x20", "448x449", "449x449"],
)
def test_the_native_path_ends_at_a_bbox_side_of_448(
    bbox: tuple[int, int], calls: int, unresampled: bool
) -> None:
    """C-4 step 3's boundary, as MT-151 C-2 and C-6 restate it: a bbox side of
    448 is native in one call; 449 on one axis is strips, unresampled, in two
    calls (C-3: on this page the second window clamps to the page end); 449 on
    both axes is the downscale path, one resized call."""
    size = (800, 1000)
    page = _coded_page(*size)
    bw, bh = bbox
    mask = _mask(size, (200, 200, 200 + bw, 200 + bh))
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == calls, f"bbox {bw} x {bh}: {len(fake.calls)} calls, wanted {calls}"
    seen = [_is_unresampled_crop(image, mask) for image, _ in fake.calls]
    assert seen == [unresampled] * calls, f"bbox {bw} x {bh}: unresampled per call {seen}"


# -- AC-3: one call per component, never a pixel in two calls ----------------------


def test_two_overlapping_regions_are_inpainted_in_one_call() -> None:
    """AC-3, as stated: two overlapping region masks become one component, and
    its pixels are holes in exactly one call. A per-region loop makes two calls
    whose hole counts sum to more than the union - that is the defect."""
    size = (1000, 800)
    page = _coded_page(*size)
    regions = [
        _region(_mask(size, (400, 300, 500, 400))),
        _region(_mask(size, (450, 350, 550, 450))),
    ]
    mask = erase_mask(regions, size)
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == 1
    assert sum(fake.hole_counts()) == int(mask.sum())
    assert np.array_equal(_hole_page_indices(fake.calls[0], size[0]), _indices(mask))


def test_every_erase_mask_pixel_is_a_hole_in_exactly_one_call() -> None:
    """AC-3 over several components: one call each, the holes of each call are
    exactly one component's pixels, and together they partition the mask - no
    pixel twice, none missed."""
    size = (1200, 1000)
    page = _coded_page(*size)
    mask = _mask(
        size,
        (100, 100, 160, 160),
        (140, 140, 220, 200),  # overlaps the first: one component
        (700, 120, 760, 300),
        (300, 700, 500, 760),
        (1000, 800, 1100, 900),
    )
    components = _components(mask)
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == len(components) == 4
    assert sum(fake.hole_counts()) == int(mask.sum())
    holes = [_hole_page_indices(call, size[0]) for call in fake.calls]
    assert np.array_equal(np.sort(np.concatenate(holes)), _indices(mask))
    for component in components:
        expected = _indices(component)
        assert any(np.array_equal(h, expected) for h in holes), (
            f"no single call holds all {expected.size} pixels of a component"
        )


def test_components_touching_only_at_a_corner_are_one_component() -> None:
    """C-4 step 1: components are 8-connected, so two rectangles meeting at a
    single diagonal pixel are one call."""
    size = (1000, 800)
    page = _coded_page(*size)
    mask = _mask(size, (400, 300, 450, 350), (450, 350, 500, 400))
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert len(fake.calls) == 1
    assert fake.hole_counts() == [int(mask.sum())]


def test_a_component_on_the_downscale_path_is_still_a_single_call() -> None:
    """AC-3's component clause on the fallback path: a large component is
    shrunk, never tiled."""
    size = (800, 1000)
    page = _coded_page(*size)
    mask = _mask(size, (100, 100, 700, 900))
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 1
    assert np.array_equal(
        result[mask], np.broadcast_to(np.array(_PATCH, dtype=np.uint8), (int(mask.sum()), 3))
    )


def test_components_are_cleaned_in_raster_order_each_seeing_the_earlier_ones_cleaned() -> None:
    """C-4 step 2: ascending label order (raster order of each component's first
    pixel), and each window is cut from the working result - so the second
    component's window shows the first one already inverted."""
    size = (1000, 800)
    page = _coded_page(*size)
    first = _mask(size, (400, 200, 440, 240))
    second = _mask(size, (420, 400, 460, 440))  # same window neighbourhood, lower
    fake = FakeInpaintSession("inverted")

    clean_page(page, first | second, fake)

    assert len(fake.calls) == 2
    assert np.array_equal(_hole_page_indices(fake.calls[0], size[0]), _indices(first))
    assert np.array_equal(_hole_page_indices(fake.calls[1], size[0]), _indices(second))
    image, _ = fake.calls[1]
    x0, y0 = _window_origin(image)
    seen = np.rint(image[0, :, 200 - y0 : 240 - y0, 400 - x0 : 440 - x0] * 255.0).astype(np.uint8)
    expected = (255 - page[200:240, 400:440]).transpose(2, 0, 1)
    assert np.array_equal(seen, expected), "the second window was not cut from the working result"


# -- AC-4: nothing outside the erase mask changes -----------------------------------


def test_every_pixel_outside_the_dilated_region_masks_is_byte_identical() -> None:
    """AC-4, through `erase_mask`, with the inverted fake - which changes every
    window pixel, so a whole-window paste-back changes pixels outside the mask."""
    size = (1125, 1600)
    page = _coded_page(*size)
    regions = [
        _region(_mask(size, (100, 120, 180, 300))),
        _region(_mask(size, (140, 280, 260, 340))),
        _region(_mask(size, (700, 900, 760, 1100))),
        _region(_mask(size, (500, 1400, 900, 1450))),
    ]
    mask = erase_mask(regions, size)

    result = clean_page(page, mask, FakeInpaintSession("inverted"))

    _assert_outside_untouched(result, page, mask)
    assert (result[mask] != page[mask]).any(axis=1).all(), "every mask pixel was inpainted"


def test_nothing_outside_the_mask_changes_on_the_downscale_path() -> None:
    """AC-4 on the fallback path, where the patch is resized back to the crop:
    the resize must not leak into the crop's non-hole pixels. MT-151 C-6: one
    component is long on both axes (500 x 550) and takes the downscale path;
    the 40 x 600 and 600 x 70 components that stood for it before now take
    strips, and AC-4 must hold there too; one more is native."""
    size = (1600, 1000)
    page = _coded_page(*size)
    mask = _mask(size, (380, 200, 420, 800), (100, 50, 700, 120), (900, 200, 1400, 750))
    mask[900:920, 200:600] = True  # joined to none: four components, one native
    result = clean_page(page, mask, FakeInpaintSession("inverted"))

    _assert_outside_untouched(result, page, mask)


# -- AC-5: page edges and pages smaller than the model input ---------------------------


_CORNERS = {
    "top-left": (0, 0, 40, 30),
    "top-right": (1160, 0, 1200, 30),
    "bottom-left": (0, 970, 40, 1000),
    "bottom-right": (1160, 970, 1200, 1000),
}


@pytest.mark.parametrize("corner", sorted(_CORNERS))
def test_a_region_touching_a_page_corner_is_cleaned_without_error(corner: str) -> None:
    """AC-5: a component in each corner - its window clamps to the page on both
    axes - is cleaned with no index error, its holes are exactly its pixels, and
    AC-4 holds."""
    size = (1200, 1000)
    page = _coded_page(*size)
    regions = [_region(_mask(size, _CORNERS[corner]))]
    mask = erase_mask(regions, size)
    fake = FakeInpaintSession("inverted")

    result = clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == 1
    assert np.array_equal(_hole_page_indices(fake.calls[0], size[0]), _indices(mask))
    assert np.array_equal(result[mask], 255 - page[mask])
    _assert_outside_untouched(result, page, mask)


@pytest.mark.parametrize(
    ("edge", "rect", "expected_origin"),
    [
        ("left", (10, 480, 30, 520), (0, None)),
        ("right", (1170, 480, 1190, 520), (1200 - 512, None)),
        ("top", (580, 10, 620, 30), (None, 0)),
        ("bottom", (580, 970, 620, 990), (None, 1000 - 512)),
    ],
)
def test_a_window_near_an_edge_is_clamped_into_the_page(
    edge: str,
    rect: tuple[int, int, int, int],
    expected_origin: tuple[int | None, int | None],
) -> None:
    """AC-5, C-4 step 3: a component within 256 px of an edge has its window
    clamped flush with that edge, so it never reads past the page."""
    size = (1200, 1000)
    page = _coded_page(*size)
    mask = _mask(size, rect)
    fake = FakeInpaintSession("inverted")

    result = clean_page(page, mask, fake)

    image, _ = fake.calls[0]
    x0, y0 = _window_origin(image)
    want_x, want_y = expected_origin
    if want_x is not None:
        assert x0 == want_x, f"{edge}: window x0 {x0}"
    if want_y is not None:
        assert y0 == want_y, f"{edge}: window y0 {y0}"
    assert np.array_equal(_hole_page_indices(fake.calls[0], size[0]), _indices(mask))
    _assert_outside_untouched(result, page, mask)


def test_a_page_smaller_than_512_on_both_axes_is_edge_padded_and_cleaned() -> None:
    """AC-5: a 300 x 200 page. The window is the whole page, padded bottom and
    right to 512 by repeating the edge; the mask is padded with holes nowhere;
    the padding is cropped off; AC-4 holds."""
    size = (300, 200)
    page = _coded_page(*size)
    mask = _mask(size, (0, 0, 30, 20), (250, 150, 300, 200))  # two corners
    fake = FakeInpaintSession("inverted")

    result = clean_page(page, mask, fake)

    assert result.shape == (200, 300, 3)
    assert fake.violations == []
    assert len(fake.calls) == 2
    for image, model_mask in fake.calls:
        seen = np.rint(image[0] * 255.0).astype(np.uint8).transpose(1, 2, 0)
        # The real part of the window is the page (as cleaned so far) at origin 0.
        assert np.array_equal(seen[:200, :300][~mask], page[~mask])
        assert np.array_equal(seen[200:, :300], np.repeat(seen[199:200, :300], 312, axis=0))
        assert np.array_equal(seen[:, 300:], np.repeat(seen[:, 299:300], 212, axis=1))
        assert not model_mask[0, 0, 200:, :].any()
        assert not model_mask[0, 0, :, 300:].any()
    assert np.array_equal(result[mask], 255 - page[mask])
    _assert_outside_untouched(result, page, mask)


def test_a_page_shorter_than_512_but_wider_is_padded_on_one_axis_only() -> None:
    """AC-5: a 1000 x 400 page. Height is padded; width is a clamped native
    window. A region on the right edge exercises both at once."""
    size = (1000, 400)
    page = _coded_page(*size)
    mask = _mask(size, (950, 300, 1000, 400), (100, 10, 160, 60))
    fake = FakeInpaintSession("inverted")

    result = clean_page(page, mask, fake)

    assert result.shape == (400, 1000, 3)
    assert fake.violations == []
    assert len(fake.calls) == 2
    for image, model_mask in fake.calls:
        seen = np.rint(image[0] * 255.0).astype(np.uint8).transpose(1, 2, 0)
        assert np.array_equal(seen[400:], np.repeat(seen[399:400], 112, axis=0))
        assert not model_mask[0, 0, 400:, :].any()
    assert sum(fake.hole_counts()) == int(mask.sum())
    assert np.array_equal(result[mask], 255 - page[mask])
    _assert_outside_untouched(result, page, mask)


def test_an_erase_mask_dilated_past_the_edge_is_cleaned_with_ac4_intact() -> None:
    """AC-5 end to end: regions flush with all four edges of a small page go
    through `erase_mask` (whose dilation runs off the page) and `clean_page`."""
    size = (300, 200)
    page = _coded_page(*size)
    regions = [
        _region(_mask(size, (0, 80, 6, 120))),
        _region(_mask(size, (294, 80, 300, 120))),
        _region(_mask(size, (130, 0, 170, 4))),
        _region(_mask(size, (130, 196, 170, 200))),
    ]
    mask = erase_mask(regions, size)

    result = clean_page(page, mask, FakeInpaintSession("constant"))

    assert result.shape == (200, 300, 3)
    assert np.array_equal(
        result[mask], np.broadcast_to(np.array(_PATCH, dtype=np.uint8), (int(mask.sum()), 3))
    )
    _assert_outside_untouched(result, page, mask)


# -- MT-151: the strips path ------------------------------------------------------
#
# Every number below is worked from C-3's rule by hand and cross-checked in RED
# against a standalone transcription of it (the handoff has the output). The
# rule, for reference: on the long axis `t`, cursor `c` starts at the bbox start
# `b`; `lo = clamp(c - 64, 0, max(N - 512, 0))`, `hi = min(lo + 512, N)`; the
# call masks the component's pixels in the window with `t >= c`; the window is
# the last if `b + L <= hi - 32` or `hi == N`, writing `[c, b + L)`, else it
# writes `[c, hi - 32)` and the cursor moves there. The short axis is the native
# path's centred 512 span of the bbox.

Rect = tuple[int, int, int, int]
Span = tuple[int, int]


@dataclass(frozen=True)
class _StripCase:
    """One component on the strips path and the calls C-3 makes for it.

    `origins` are the page `(x0, y0)` of each window; `masked` is the long-axis
    `[lo, hi)` each call masks (cursor to window end; intersected with the
    component); `written` is the long-axis band each call's patch is written to.
    """

    size: tuple[int, int]  # (width, height)
    rects: tuple[Rect, ...]  # one 8-connected component between them
    axis: Literal["x", "y"]
    origins: tuple[tuple[int, int], ...]
    masked: tuple[Span, ...]
    written: tuple[Span, ...]


_STRIP_CASES = {
    # AC-1 as stated: 60 x 1000 on 1414 x 2000, hole y [500, 1500). C-3's own
    # worked example: windows [436, 948), [852, 1364), [1268, 1780).
    "ac1-vertical-60x1000": _StripCase(
        size=(1414, 2000),
        rects=((600, 500, 660, 1500),),
        axis="y",
        origins=((374, 436), (374, 852), (374, 1268)),
        masked=((500, 948), (916, 1364), (1332, 1780)),
        written=((500, 916), (916, 1332), (1332, 1500)),
    ),
    # AC-5: the same hole turned on its side, 1000 x 60 on 2000 x 1414.
    "ac5-horizontal-1000x60": _StripCase(
        size=(2000, 1414),
        rects=((500, 600, 1500, 660),),
        axis="x",
        origins=((436, 374), (852, 374), (1268, 374)),
        masked=((500, 948), (916, 1364), (1332, 1780)),
        written=((500, 916), (916, 1332), (1332, 1500)),
    ),
    # Touching the start of the long axis: the first window clamps to 0.
    "touching-the-top": _StripCase(
        size=(1414, 2000),
        rects=((600, 0, 660, 600),),
        axis="y",
        origins=((374, 0), (374, 416)),
        masked=((0, 512), (480, 928)),
        written=((0, 480), (480, 600)),
    ),
    # Touching the end: the second window clamps to N - 512 and is the last by
    # `hi == N`, not by `b + L <= hi - 32` (2000 > 1968).
    "touching-the-bottom": _StripCase(
        size=(1414, 2000),
        rects=((600, 1400, 660, 2000),),
        axis="y",
        origins=((374, 1336), (374, 1488)),
        masked=((1400, 1848), (1816, 2000)),
        written=((1400, 1816), (1816, 2000)),
    ),
    "touching-the-right-edge": _StripCase(
        size=(2000, 1414),
        rects=((1400, 600, 2000, 660),),
        axis="x",
        origins=((1336, 374), (1488, 374)),
        masked=((1400, 1848), (1816, 2000)),
        written=((1400, 1816), (1816, 2000)),
    ),
    # A page 480 tall with a 460-tall component: one window, the whole axis,
    # edge-padded to 512 (`hi == N` at once).
    "page-shorter-than-512-on-the-long-axis": _StripCase(
        size=(1414, 480),
        rects=((600, 10, 660, 470),),
        axis="y",
        origins=((374, 0),),
        masked=((10, 480),),
        written=((10, 470),),
    ),
    # A page 400 tall under a horizontal strip: the short-axis span is the whole
    # axis, edge-padded, on every window.
    "page-shorter-than-512-on-the-short-axis": _StripCase(
        size=(2000, 400),
        rects=((500, 170, 1500, 230),),
        axis="x",
        origins=((436, 0), (852, 0), (1268, 0)),
        masked=((500, 948), (916, 1364), (1332, 1780)),
        written=((500, 916), (916, 1332), (1332, 1500)),
    ),
    # Not a rectangle: two bars joined at [640, 660) x [980, 1000), bbox
    # 100 x 1000, so the short-axis span centres on x = 650.
    "non-rectangular-component": _StripCase(
        size=(1414, 2000),
        rects=((600, 500, 660, 1000), (640, 980, 700, 1500)),
        axis="y",
        origins=((394, 436), (394, 852), (394, 1268)),
        masked=((500, 948), (916, 1364), (1332, 1780)),
        written=((500, 916), (916, 1332), (1332, 1500)),
    ),
    # One past the native limit: the first window ends at 648 and the hole at
    # 649, so its last row lies outside the first window and is masked only by
    # the second.
    "449-tall": _StripCase(
        size=(800, 1000),
        rects=((380, 200, 400, 649),),
        axis="y",
        origins=((134, 136), (134, 488)),
        masked=((200, 648), (616, 1000)),
        written=((200, 616), (616, 649)),
    ),
}

_STRIP_IDS = sorted(_STRIP_CASES)
_ORIENTATIONS = ["ac1-vertical-60x1000", "ac5-horizontal-1000x60"]


def _strip_overlap_px() -> int:
    """`STRIP_OVERLAP_PX`, read late so that its absence fails the test that
    needs it, on an assertion, rather than the whole file at import."""
    value = getattr(inpaint_module, "STRIP_OVERLAP_PX", None)
    assert isinstance(value, int), "mangatl.clean.inpaint.STRIP_OVERLAP_PX is not defined"
    return value


def _band(size: tuple[int, int], axis: str, span: Span) -> NDArray[np.bool_]:
    """The page pixels whose long-axis coordinate lies in the half-open `span`."""
    width, height = size
    ys, xs = np.ogrid[0:height, 0:width]
    t = ys if axis == "y" else xs
    lo, hi = span
    return np.broadcast_to((t >= lo) & (t < hi), (height, width))


def _cut(array: NDArray[Any], origin: tuple[int, int]) -> NDArray[Any]:
    """The 512 x 512 window at page `origin`, edge-padded bottom/right where the
    page ends (as `_inpaint` pads; a bool mask is padded with `False`)."""
    x0, y0 = origin
    crop = array[y0 : y0 + _SIDE, x0 : x0 + _SIDE]
    pad = [(0, _SIDE - crop.shape[0]), (0, _SIDE - crop.shape[1])]
    if array.dtype == np.bool_:
        return np.pad(crop, pad, mode="constant", constant_values=False)
    return np.pad(crop, [*pad, (0, 0)], mode="edge")


def _seen(image: NDArray[np.float32]) -> NDArray[np.uint8]:
    """A recorded model input back in page form: `(512, 512, 3)` uint8."""
    seen: NDArray[np.uint8] = np.rint(image[0] * 255.0).astype(np.uint8).transpose(1, 2, 0)
    return seen


@dataclass(frozen=True)
class _Expected:
    """What C-3 says each call sees, and the result after every call."""

    windows: list[NDArray[np.uint8]]  # the working page, cut at each origin
    originals: list[NDArray[np.uint8]]  # the untouched page, cut at each origin
    masks: list[NDArray[np.bool_]]  # each call's exact hole, window coordinates
    result: NDArray[np.uint8]  # the page after every band is stamped


def _expected(case: _StripCase, page: NDArray[np.uint8]) -> _Expected:
    """Replays the pinned `case` on `page` with the stamped fake's colours."""
    component = _mask(case.size, *case.rects)
    working = page.copy()
    windows: list[NDArray[np.uint8]] = []
    originals: list[NDArray[np.uint8]] = []
    masks: list[NDArray[np.bool_]] = []
    steps = zip(case.origins, case.masked, case.written, strict=True)
    for k, (origin, masked, written) in enumerate(steps):
        windows.append(_cut(working, origin))
        originals.append(_cut(page, origin))
        masks.append(_cut(component & _band(case.size, case.axis, masked), origin))
        working[component & _band(case.size, case.axis, written)] = _stamp(k)
    return _Expected(windows, originals, masks, working)


def _run_case(
    case: _StripCase,
    page: NDArray[np.uint8],
    mode: Literal["inverted", "stamped"] = "stamped",
    *,
    check_count: bool = True,
) -> tuple[FakeInpaintSession, NDArray[np.uint8], NDArray[np.bool_]]:
    mask = _mask(case.size, *case.rects)
    fake = FakeInpaintSession(mode)
    result = clean_page(page, mask, fake)
    assert fake.violations == []
    if check_count:
        _assert_strip_count(fake, case)
    return fake, result, mask


def _assert_strip_count(fake: FakeInpaintSession, case: _StripCase) -> None:
    assert len(fake.calls) == len(case.origins), (
        f"{len(fake.calls)} calls for a component C-3 cleans in {len(case.origins)} strips"
    )


def test_the_strip_overlap_starts_at_min_context_and_is_exported() -> None:
    """MT-151 C-1, C-4: `STRIP_OVERLAP_PX` is public and starts at
    `MIN_CONTEXT_PX` (32); it changes only on DV-2's evidence."""
    assert _strip_overlap_px() == MIN_CONTEXT_PX == 32
    assert "STRIP_OVERLAP_PX" in inpaint_module.__all__


@pytest.mark.parametrize("name", _STRIP_IDS)
def test_a_component_long_on_one_axis_is_cut_into_windows_advancing_along_that_axis(
    name: str,
) -> None:
    """AC-1 / AC-5 "the calls advance down the long axis": the windows sit at
    exactly the origins C-3 gives, the short-axis origin never moves, and the
    long-axis origin strictly increases."""
    case = _STRIP_CASES[name]
    page = _coded_page(*case.size)

    fake, _result, _page_mask = _run_case(case, page)

    origins = [_window_origin(image) for image, _ in fake.calls]
    assert origins == list(case.origins), f"window origins {origins}, wanted {list(case.origins)}"
    long_i, short_i = (1, 0) if case.axis == "y" else (0, 1)
    assert len({o[short_i] for o in origins}) == 1, "the short-axis span moved between windows"
    assert all(a[long_i] < b[long_i] for a, b in pairwise(origins))


@pytest.mark.parametrize("name", _STRIP_IDS)
def test_every_strip_window_is_an_unresampled_crop_of_the_working_page(name: str) -> None:
    """AC-1 / AC-5: every non-hole pixel of every 512 x 512 window is,
    byte-exactly, the **working** page at that position - the original page,
    except where an earlier call of this component already wrote its band. A
    window cut from the source would show the original page in those rows; a
    resized window would match nowhere. "No resize" is asserted first, before
    the call count, so the downscale path standing in for strips (DV-1) fails
    on exactly that."""
    case = _STRIP_CASES[name]
    page = _coded_page(*case.size)
    expected = _expected(case, page)

    fake, _result, page_mask = _run_case(case, page, check_count=False)

    resized = [
        k for k, (image, _) in enumerate(fake.calls) if not _is_unresampled_crop(image, page_mask)
    ]
    assert resized == [], f"calls {resized} saw a resized crop, not a native window"
    _assert_strip_count(fake, case)
    for k, (image, model_mask) in enumerate(fake.calls):
        context = model_mask[0, 0] == 0.0
        seen = _seen(image)
        wrong = int((seen[context] != expected.windows[k][context]).any(axis=1).sum())
        assert wrong == 0, f"call {k}: {wrong} context pixels are not the working page"


@pytest.mark.parametrize("name", _STRIP_IDS)
def test_each_strip_call_masks_only_the_part_of_the_component_not_yet_filled(name: str) -> None:
    """AC-2: each call's mask is exactly the component's pixels inside its
    window from the cursor on - every unfilled pixel the window shows, including
    the 32-px trail it will not write, and no pixel an earlier call wrote."""
    case = _STRIP_CASES[name]
    page = _coded_page(*case.size)
    expected = _expected(case, page)

    fake, _result, _page_mask = _run_case(case, page)

    for k, (_image, model_mask) in enumerate(fake.calls):
        got = model_mask[0, 0] == 1.0
        want = expected.masks[k]
        assert np.array_equal(got, want), (
            f"call {k}: mask has {int(got.sum())} pixels, wanted {int(want.sum())}; "
            f"{int((got & ~want).sum())} extra, {int((want & ~got).sum())} missing"
        )


@pytest.mark.parametrize("name", _STRIP_IDS)
def test_every_strip_pixel_is_written_exactly_once_from_the_call_whose_band_holds_it(
    name: str,
) -> None:
    """AC-1 "every hole pixel is written exactly once", AC-4: the result carries
    each band in the colour of the call that owns it, and nothing outside the
    erase mask moved. And no hole pixel is written early: under every call's
    mask the window still shows the untouched page, so a pixel in a window's
    32-px trail was not written by that window and then again by the next."""
    case = _STRIP_CASES[name]
    page = _coded_page(*case.size)
    expected = _expected(case, page)

    fake, result, mask = _run_case(case, page)

    for k, (image, model_mask) in enumerate(fake.calls):
        holes = model_mask[0, 0] == 1.0
        early = int((_seen(image)[holes] != expected.originals[k][holes]).any(axis=1).sum())
        assert early == 0, f"call {k}: {early} masked pixels were already written"
    wrong = int((result[mask] != expected.result[mask]).any(axis=1).sum())
    assert wrong == 0, (
        f"{wrong} hole pixels do not carry the stamp of the call whose band holds them"
    )
    _assert_outside_untouched(result, page, mask)


@pytest.mark.parametrize("name", _STRIP_IDS)
def test_a_strip_patch_lands_on_the_pixel_it_was_computed_from(name: str) -> None:
    """AC-1, AC-4 with the inverted fake: every hole pixel is `255 - page`, so
    each band was written from its own call's patch at the right offset, and
    nothing outside the mask moved although the fake changed every pixel."""
    case = _STRIP_CASES[name]
    page = _coded_page(*case.size)

    _fake, result, mask = _run_case(case, page, mode="inverted")

    assert np.array_equal(result[mask], 255 - page[mask])
    _assert_outside_untouched(result, page, mask)


@pytest.mark.parametrize("name", _ORIENTATIONS)
def test_consecutive_strip_windows_overlap_by_at_least_strip_overlap_px(name: str) -> None:
    """AC-2: consecutive windows of one component share at least
    `STRIP_OVERLAP_PX` along the long axis. Away from the page ends C-3 makes
    that exactly `2 * MIN_CONTEXT_PX + STRIP_OVERLAP_PX` (96): a 512 window
    advancing 416 a call."""
    case = _STRIP_CASES[name]
    page = _coded_page(*case.size)
    overlap_px = _strip_overlap_px()

    fake, _result, _page_mask = _run_case(case, page)

    long_i = 1 if case.axis == "y" else 0
    starts = [_window_origin(image)[long_i] for image, _ in fake.calls]
    overlaps = [a + _SIDE - b for a, b in pairwise(starts)]
    assert overlaps, "one window: nothing overlaps"
    assert all(o >= overlap_px for o in overlaps), f"overlaps {overlaps} < {overlap_px}"
    assert overlaps == [2 * MIN_CONTEXT_PX + overlap_px] * len(overlaps)


@pytest.mark.parametrize("name", _ORIENTATIONS)
def test_no_unfilled_hole_pixel_is_shown_to_the_model_as_context(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-3 step 3: on a white page with a black hole, every unmasked pixel of
    every window is white or an earlier call's fill - never the black of a hole
    pixel left unmasked."""
    monkeypatch.setattr(inpaint_module, "FLAT_MAX_SPREAD", -1, raising=False)  # MT-153 C-5
    case = _STRIP_CASES[name]
    page = np.full((case.size[1], case.size[0], 3), 255, dtype=np.uint8)
    page[_mask(case.size, *case.rects)] = 0

    fake, _result, _page_mask = _run_case(case, page)

    for k, (image, model_mask) in enumerate(fake.calls):
        visible = _seen(image)[model_mask[0, 0] == 0.0]
        allowed = np.array([(255, 255, 255), *(_stamp(j) for j in range(k))], dtype=np.uint8)
        ok = (visible[:, None, :] == allowed[None, :, :]).all(axis=2).any(axis=1)
        assert ok.all(), f"call {k}: {int((~ok).sum())} visible pixels show an unfilled hole"


def test_a_strip_call_masks_none_of_another_components_pixels() -> None:
    """AC-2 "the part of **the** hole": a native component inside the strip's
    first window is context there, never a hole, and is cleaned in its own
    call afterwards (ascending label order: the strip starts higher)."""
    case = _STRIP_CASES["ac1-vertical-60x1000"]
    size = case.size
    page = _coded_page(*size)
    strip = _mask(size, *case.rects)
    blob = _mask(size, (800, 700, 820, 720))
    fake = FakeInpaintSession("stamped")

    result = clean_page(page, strip | blob, fake)

    assert len(fake.calls) == len(case.origins) + 1
    width = size[0]
    for k in range(len(case.origins)):
        holes = _hole_page_indices(fake.calls[k], width)
        assert not np.isin(holes, _indices(blob)).any(), f"strip call {k} masked the blob"
    assert np.array_equal(_hole_page_indices(fake.calls[-1], width), _indices(blob))
    assert (result[blob] == _stamp(len(case.origins))).all()
    _assert_outside_untouched(result, page, strip | blob)


def test_a_hole_long_on_both_axes_still_takes_one_resized_call() -> None:
    """AC-3, the control: a 600 x 600 hole on a 1414 x 2000 page is the
    downscale path as before - one call, a crop that is not an unresampled
    window, a hole shrunk with it (the 664 px crop becomes 512, so the 600 px
    hole is under 600 px a side in the model mask) - and AC-4 holds."""
    size = (1414, 2000)
    page = _coded_page(*size)
    mask = _mask(size, (400, 500, 1000, 1100))
    fake = FakeInpaintSession("inverted")

    result = clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == 1
    image, model_mask = fake.calls[0]
    assert not _is_unresampled_crop(image, mask), "the session saw a native crop, not a resized one"
    holes = model_mask[0, 0] == 1.0
    rows, cols = np.flatnonzero(holes.any(axis=1)), np.flatnonzero(holes.any(axis=0))
    assert rows.size < 600 and cols.size < 600, f"hole is {cols.size} x {rows.size} in the model"
    _assert_outside_untouched(result, page, mask)


# -- MT-153: a component on flat paper is filled with the paper -------------------
#
# Every fixture below is built so that its verdict holds for any `FLAT_RING_PX`
# in 1..16 and any `FLAT_MAX_SPREAD` in 4..64 (C-6), unless the test sets the
# constants itself with `monkeypatch` - the boundary tests (C-7) do, and build
# their geometry from the values they set. Holes sit at least 16 px from every
# page edge unless the edge is the point. Ink is drawn inside each hole, inset
# from the mask's edge as text sits inside its erase mask, so a hole that comes
# back as nothing but paper can only have been filled (AC-1, PO-1).

#: The fixture paper (C-3): not 255, so a fill that writes white instead of the
#: ring's own colour fails.
_PAPER = 252

#: AC-5's double: a faint tint `_TINT` levels under the paper.
_TINT = 6

#: The band C-6 says every AC fixture holds over.
_RING_BAND = range(1, 17)
_SPREAD_BAND = range(4, 65)

#: C-2.4's off switch, as C-5 spells it.
_OFF = -1

#: A hole per path (C-2.6 "on any path"): `(page size, hole rect)`. Native fits
#: on both axes; strips is long on y only (600 > 448); downscale is long on both.
_PATH_HOLES: dict[str, tuple[tuple[int, int], Rect]] = {
    "native": ((400, 300), (180, 130, 220, 160)),
    "strips": ((300, 800), (120, 100, 180, 700)),
    "downscale": ((800, 1000), _DOWNSCALE_RECT),
}

#: The native hole of AC-1, AC-4 and AC-5: 40 x 30 on a 400 x 300 page.
_NATIVE_SIZE, _NATIVE_HOLE = _PATH_HOLES["native"]

#: AC-4's outline pixel: the first column right of the hole, at mid-height -
#: 1 px from the component, so in the ring for every `FLAT_RING_PX >= 1`.
_OUTLINE_Y = (_NATIVE_HOLE[1] + _NATIVE_HOLE[3]) // 2
_OUTLINE_IN_REACH = (_NATIVE_HOLE[2], _OUTLINE_Y)

_WHITE_PAPER = (_PAPER, _PAPER, _PAPER)


def _shipped(name: str) -> int:
    """A shipped flat constant, read late so its absence fails the test that
    needs it on an assertion, not the whole file at import."""
    value = getattr(inpaint_module, name, None)
    assert type(value) is int, f"mangatl.clean.inpaint.{name} is not defined as an int (C-1)"
    return value


def _set_flat(monkeypatch: pytest.MonkeyPatch, *, ring_px: int, max_spread: int) -> None:
    """C-7's boundary tests set both constants. `raising=False`: in RED neither
    exists; C-1 has `clean_page` read them at call time."""
    monkeypatch.setattr(inpaint_module, "FLAT_RING_PX", ring_px, raising=False)
    monkeypatch.setattr(inpaint_module, "FLAT_MAX_SPREAD", max_spread, raising=False)


def _paper_page(
    size: tuple[int, int], colour: tuple[int, int, int] = _WHITE_PAPER
) -> NDArray[np.uint8]:
    width, height = size
    page = np.empty((height, width, 3), dtype=np.uint8)
    page[...] = colour
    return page


def _ink(page: NDArray[np.uint8], rect: Rect, inset: int = 4) -> None:
    """Black ink inside `rect`, `inset` px in from its edge, in place."""
    x0, y0, x1, y1 = rect
    page[y0 + inset : y1 - inset, x0 + inset : x1 - inset] = 0


def _screentone(size: tuple[int, int]) -> NDArray[np.uint8]:
    """A dot screen: 2 x 2 dots of 40 every 4 px on `_PAPER`. Any ring of
    radius 1 or more round a hole crosses dots, so its spread is 212 (> 64)."""
    width, height = size
    ys, xs = np.mgrid[0:height, 0:width]
    page = _paper_page(size)
    page[(xs % 4 < 2) & (ys % 4 < 2)] = 40
    return page


def _flat_ring(mask: NDArray[np.bool_], ring_px: int) -> NDArray[np.bool_]:
    """C-2.1, computed here (C-4): `mask` dilated by the elliptical element of
    side `2 * ring_px + 1`, minus `mask`. `cv2.dilate` never reads off the page."""
    side = 2 * ring_px + 1
    element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
    grown = np.asarray(cv2.dilate(mask.astype(np.uint8), element), dtype=bool)
    return grown & ~mask


def _spread(page: NDArray[np.uint8], ring: NDArray[np.bool_]) -> int:
    """C-2.3: the largest, over the channels, of max minus min over the ring."""
    values = page[ring].astype(np.int64)
    return int((values.max(axis=0) - values.min(axis=0)).max())


def _lower_median(page: NDArray[np.uint8], ring: NDArray[np.bool_]) -> NDArray[np.uint8]:
    """C-2.5: per channel, index `(n - 1) // 2` of the ring's values sorted."""
    values = np.sort(page[ring], axis=0)
    median: NDArray[np.uint8] = values[(values.shape[0] - 1) // 2]
    return median


def ghost(page: NDArray[np.uint8], mask: NDArray[np.bool_], *, ring_px: int = 4) -> int:
    """AC-5's metric: the maximum, over `mask`'s pixels and the three channels,
    of the absolute difference from the ring's lower median.

    Built from the element and the mask (C-4), never from production. On AC-5's
    pages the paper is constant `_PAPER` and AC-4's single outlier cannot move
    the lower median of a ring of over a hundred pixels, so the score is the
    same for every `ring_px` in 1..16; 4 is C-6's provisional radius.
    """
    median = _lower_median(page, _flat_ring(mask, ring_px)).astype(np.int64)
    return int(np.abs(page[mask].astype(np.int64) - median).max())


@dataclass
class _TintSession:
    """AC-5's double: returns the paper minus `_TINT` everywhere (model scale),
    the kind of faint tint LaMa leaves on flat paper. Checks C-2's convention."""

    level: int = _PAPER - _TINT
    calls: int = 0

    def run(self, image: NDArray[np.float32], mask: NDArray[np.float32]) -> NDArray[np.float32]:
        problems = _convention_problems(image, mask)
        assert not problems, f"C-2 calling convention violated: {problems}"
        self.calls += 1
        return np.full((1, 3, _SIDE, _SIDE), float(self.level), dtype=np.float32)

    def get_providers(self) -> Sequence[str]:
        return ["FakeExecutionProvider"]


def _ac1_page() -> tuple[NDArray[np.uint8], NDArray[np.bool_]]:
    """AC-1's native page: constant 252 paper, black ink inside the 40 x 30 hole."""
    page = _paper_page(_NATIVE_SIZE)
    _ink(page, _NATIVE_HOLE)
    return page, _mask(_NATIVE_SIZE, _NATIVE_HOLE)


def _ac4_page(
    dark: tuple[int, int] = _OUTLINE_IN_REACH,
) -> tuple[NDArray[np.uint8], NDArray[np.bool_]]:
    """AC-1's page with one black outline pixel at page `(x, y)` = `dark`."""
    page, mask = _ac1_page()
    x, y = dark
    page[y, x] = 0
    return page, mask


def _on_outermost_reach(ring_px: int) -> tuple[int, int]:
    """The element's middle row reaches `ring_px` columns, so from the hole's
    last column `x1 - 1` the ring ends at `x1 - 1 + ring_px` (C-3)."""
    return (_NATIVE_HOLE[2] - 1 + ring_px, _OUTLINE_Y)


def _just_beyond(ring_px: int) -> tuple[int, int]:
    """AC-4's control: the outline pixel one column past the ring's reach."""
    return (_NATIVE_HOLE[2] + ring_px, _OUTLINE_Y)


def _assert_filled_with(
    result: NDArray[np.uint8], mask: NDArray[np.bool_], colour: Sequence[int], what: str
) -> None:
    want = np.array(colour, dtype=np.uint8)
    wrong = int((result[mask] != want).any(axis=1).sum())
    first = tuple(int(v) for v in result[mask][0])
    assert wrong == 0, (
        f"{what}: {wrong} of {int(mask.sum())} hole pixels are not"
        f" {tuple(int(v) for v in want)}; the first hole pixel is {first}"
    )


def test_the_flat_constants_are_exported_ints_inside_the_band_the_fixtures_hold_for() -> None:
    """C-1: `FLAT_RING_PX` and `FLAT_MAX_SPREAD` are public ints. C-6: the AC
    fixtures here hold only for a ring of 1..16 and a limit of 4..64 (AC-2
    puts the floor at 4); a derivation outside that stops GREEN rather than
    moving a fixture. The value inside the band is not pinned (C-7)."""
    ring_px, max_spread = _shipped("FLAT_RING_PX"), _shipped("FLAT_MAX_SPREAD")
    assert {"FLAT_RING_PX", "FLAT_MAX_SPREAD"} <= set(inpaint_module.__all__)
    assert ring_px in _RING_BAND, f"FLAT_RING_PX = {ring_px}, outside C-6's 1..16"
    assert max_spread in _SPREAD_BAND, f"FLAT_MAX_SPREAD = {max_spread}, outside C-6's 4..64"


# -- AC-1: a hole on constant paper is the paper, on every path ------------------


@pytest.mark.parametrize("path", sorted(_PATH_HOLES))
def test_a_hole_on_constant_paper_is_filled_with_the_paper_without_calling_the_model(
    path: str,
) -> None:
    """**AC-1**: black ink in a hole on constant 252 paper. Every hole pixel
    comes back exactly 252, the session is never called, nothing outside the
    mask moves and the input is not mutated - whichever path the hole's size
    would have taken (C-2.6: the check comes before the path is chosen)."""
    size, hole = _PATH_HOLES[path]
    page = _paper_page(size)
    _ink(page, hole)
    mask = _mask(size, hole)
    page_before = page.copy()
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 0, (
        f"{path}: the session was called {len(fake.calls)} times for a hole whose ring is"
        f" all {_PAPER}; a component on flat paper is filled without the model"
    )
    _assert_filled_with(result, mask, _WHITE_PAPER, path)
    _assert_outside_untouched(result, page, mask)
    assert np.array_equal(page, page_before), "the input page was mutated"


def test_a_hole_on_coloured_paper_is_filled_with_that_colour_channel_by_channel() -> None:
    """C-7 "the fill is the ring's colour per channel, on paper that is not
    grey": on (30, 120, 220) paper the hole is (30, 120, 220) - not a grey, not
    white, not the channels swapped."""
    paper = (30, 120, 220)
    page = _paper_page(_NATIVE_SIZE, paper)
    _ink(page, _NATIVE_HOLE)
    mask = _mask(_NATIVE_SIZE, _NATIVE_HOLE)
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 0, f"the session was called {len(fake.calls)} times on flat paper"
    _assert_filled_with(result, mask, paper, "coloured paper")


def test_a_hole_touching_the_page_corner_on_flat_paper_is_still_flat() -> None:
    """C-2.1 "clipped to the page. Off-page pixels are not counted": a corner
    hole's ring lies only on the page side, and it is all paper. A ring padded
    past the edge, with black or with anything that is not the page, is not."""
    hole = (0, 0, 30, 20)
    page = _paper_page(_NATIVE_SIZE)
    _ink(page, hole)
    mask = _mask(_NATIVE_SIZE, hole)
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 0, f"the session was called {len(fake.calls)} times for a corner hole"
    _assert_filled_with(result, mask, _WHITE_PAPER, "corner hole")
    _assert_outside_untouched(result, page, mask)


# -- AC-2: JPEG-like noise round the paper is still paper (settled: 4) -----------


def _noisy_page(seed: int = 153) -> tuple[NDArray[np.uint8], NDArray[np.bool_]]:
    """AC-2's page: 252 +/- 2 per channel, seeded, ink in the native hole. Both
    extremes are forced 1 px from the hole (in every ring of radius >= 1), in
    every channel: 250 left of it, 254 right of it."""
    rng = np.random.default_rng(seed)
    width, height = _NATIVE_SIZE
    noise = rng.integers(-2, 3, size=(height, width, 3))
    page = (_PAPER + noise).astype(np.uint8)
    x0, _y0, x1, _y1 = _NATIVE_HOLE
    page[_OUTLINE_Y, x0 - 1] = _PAPER - 2
    page[_OUTLINE_Y, x1] = _PAPER + 2
    _ink(page, _NATIVE_HOLE)
    return page, _mask(_NATIVE_SIZE, _NATIVE_HOLE)


def test_paper_with_jpeg_noise_of_two_levels_is_flat_and_filled_with_the_ring_median() -> None:
    """**AC-2** (settled, read out): every ring value in 250..254 with both
    extremes present, so the ring's spread is exactly 4 - at or under
    `FLAT_MAX_SPREAD`, whose floor AC-2 sets at 4. The session is not called,
    and the fill is the ring's lower median at the shipped radius: maximum
    absolute difference 0."""
    page, mask = _noisy_page()
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 0, (
        f"the session was called {len(fake.calls)} times for paper with +/-2 noise"
    )
    ring_px, max_spread = _shipped("FLAT_RING_PX"), _shipped("FLAT_MAX_SPREAD")
    ring = _flat_ring(mask, ring_px)
    values = page[ring]
    assert (int(values.min()), int(values.max())) == (_PAPER - 2, _PAPER + 2), "the Given"
    assert _spread(page, ring) == 4 <= max_spread
    median = _lower_median(page, ring).astype(np.int64)
    worst = int(np.abs(result[mask].astype(np.int64) - median).max())
    assert worst == 0, f"the fill is up to {worst} levels off the ring median {tuple(median)}"


# -- AC-3: screentone is texture, and goes to the model --------------------------


def test_a_hole_on_screentone_goes_to_the_model_and_holds_its_output() -> None:
    """**AC-3** (control: texture): on a dot screen the ring's spread is 212,
    over any limit in 4..64, so the session is called once, as today, and the
    hole holds the session's `(17, 34, 51)`."""
    page = _screentone(_NATIVE_SIZE)
    _ink(page, _NATIVE_HOLE)
    mask = _mask(_NATIVE_SIZE, _NATIVE_HOLE)
    assert _spread(page, _flat_ring(mask, 1)) == 212, "the Given: the tone is in every ring"
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert fake.violations == []
    assert len(fake.calls) == 1, f"{len(fake.calls)} calls for a screentone hole, wanted 1"
    _assert_filled_with(result, mask, _PATCH, "screentone")
    _assert_outside_untouched(result, page, mask)


# -- AC-4: one dark pixel in the ring defeats "flat" -----------------------------


def test_an_outline_pixel_in_the_ring_sends_the_hole_to_the_model() -> None:
    """**AC-4**: AC-1's page with one black outline pixel 1 px right of the
    hole - in the ring at every radius. Spread is measured over the whole ring,
    so that one pixel makes it 252 and the session is called."""
    page, mask = _ac4_page()
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 1, (
        f"{len(fake.calls)} calls: one dark pixel in the ring must defeat 'flat'"
    )
    _assert_filled_with(result, mask, _PATCH, "outline in the ring")


def test_the_same_outline_pixel_just_beyond_the_ring_leaves_the_hole_flat() -> None:
    """**AC-4's control**: the pixel moved one column past the ring's reach at
    the shipped `FLAT_RING_PX` leaves the component flat, filled as in AC-1."""
    ring_px = _shipped("FLAT_RING_PX")
    page, mask = _ac4_page(_just_beyond(ring_px))
    assert _spread(page, _flat_ring(mask, ring_px)) == 0, "the Given: the pixel is off the ring"
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 0, f"{len(fake.calls)} calls for a hole whose ring is all paper"
    _assert_filled_with(result, mask, _WHITE_PAPER, "outline beyond the ring")


@pytest.mark.parametrize("ring_px", [1, 4, 9])
@pytest.mark.parametrize("where", ["outermost-reach", "one-beyond"])
def test_the_ring_ends_where_the_elliptical_element_stops_reaching(
    ring_px: int, where: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-7, C-3: a dark pixel on the ring's outermost reach (`ring_px` columns
    from the hole, along the element's middle row) defeats "flat"; the same
    pixel one column further does not. The radius is set here, so this also
    shows `FLAT_RING_PX` is read at the call, not bound at import (C-1)."""
    _set_flat(monkeypatch, ring_px=ring_px, max_spread=8)
    in_ring = where == "outermost-reach"
    dark = _on_outermost_reach(ring_px) if in_ring else _just_beyond(ring_px)
    page, mask = _ac4_page(dark)
    assert bool(_flat_ring(mask, ring_px)[dark[1], dark[0]]) == in_ring, "the Given"
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    want_calls = 1 if in_ring else 0
    assert len(fake.calls) == want_calls, (
        f"ring {ring_px}, dark pixel {where}: {len(fake.calls)} calls, wanted {want_calls}"
    )
    _assert_filled_with(result, mask, _PATCH if in_ring else _WHITE_PAPER, where)


@pytest.mark.parametrize(
    ("offset", "in_ring"),
    [((3, 3), True), ((4, 4), False)],
    ids=["diagonal-3-3-in-the-ellipse", "diagonal-4-4-in-a-square-only"],
)
def test_the_ring_is_the_elliptical_element_not_a_square_or_a_euclidean_disk(
    offset: tuple[int, int], in_ring: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.1, C-3 "read off that element, not off a Euclidean distance": at
    radius 4, `cv2.MORPH_ELLIPSE`'s 9 x 9 element holds the offset (3, 3) and
    not (4, 4). A dark pixel (3, 3) diagonally past the hole's corner is in the
    ring - a Euclidean radius of 4 misses it (4.24) - and at (4, 4) it is out,
    where a square element would catch it."""
    _set_flat(monkeypatch, ring_px=4, max_spread=8)
    dx, dy = offset
    dark = (_NATIVE_HOLE[2] - 1 + dx, _NATIVE_HOLE[3] - 1 + dy)
    page, mask = _ac4_page(dark)
    assert bool(_flat_ring(mask, 4)[dark[1], dark[0]]) == in_ring, "the Given"
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    want_calls = 1 if in_ring else 0
    assert len(fake.calls) == want_calls, (
        f"dark pixel {offset} past the corner: {len(fake.calls)} calls, wanted {want_calls}"
    )


# -- C-2's other rules, pinned with the constants set here -----------------------


@pytest.mark.parametrize(
    ("max_spread", "outlier", "flat"),
    [
        (8, _PAPER - 8, True),  # spread 8 = limit 8: filled
        (8, _PAPER - 9, False),  # spread 9 > limit 8: the model
        (0, _PAPER, True),  # spread 0 = limit 0: filled
        (_OFF, _PAPER, False),  # a negative limit is the off switch
    ],
    ids=["spread-8-limit-8", "spread-9-limit-8", "spread-0-limit-0", "spread-0-limit-minus-1"],
)
def test_a_ring_whose_spread_equals_the_limit_is_flat_and_one_more_is_not(
    max_spread: int, outlier: int, flat: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.4: flat means `spread <= FLAT_MAX_SPREAD`, inclusive, so a negative
    limit switches the fill off. One ring pixel at `outlier` (1 px right of the
    hole) sets the spread; the lower median stays 252. The limit is set here,
    so this also shows `FLAT_MAX_SPREAD` is read at the call (C-1)."""
    _set_flat(monkeypatch, ring_px=4, max_spread=max_spread)
    page, mask = _ac1_page()
    x, y = _OUTLINE_IN_REACH
    page[y, x] = outlier
    assert _spread(page, _flat_ring(mask, 4)) == _PAPER - outlier, "the Given"
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == (0 if flat else 1), (
        f"spread {_PAPER - outlier}, limit {max_spread}: {len(fake.calls)} calls"
    )
    _assert_filled_with(result, mask, _WHITE_PAPER if flat else _PATCH, "at the limit")


def test_a_colour_cast_of_constant_luma_is_a_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.3: spread is per channel, never grey. A ring pixel of (220, 186, 220)
    on (200, 200, 200) paper has the paper's luma - PIL's `L` and OpenCV's grey
    both give 200 - but is 20 off in red and blue, so at a limit of 8 the ring
    is not flat and the session is called."""
    _set_flat(monkeypatch, ring_px=4, max_spread=8)
    page = _paper_page(_NATIVE_SIZE, (200, 200, 200))
    _ink(page, _NATIVE_HOLE)
    x, y = _OUTLINE_IN_REACH
    page[y, x] = (220, 186, 220)
    mask = _mask(_NATIVE_SIZE, _NATIVE_HOLE)
    cast = np.array([[[220, 186, 220]]], dtype=np.uint8)
    pil_grey = int(np.asarray(Image.fromarray(cast).convert("L"))[0, 0])
    cv2_grey = int(cv2.cvtColor(cast, cv2.COLOR_RGB2GRAY)[0, 0])
    assert (pil_grey, cv2_grey) == (200, 200), "the Given: the cast has the paper's luma"
    fake = FakeInpaintSession("constant")

    clean_page(page, mask, fake)

    assert len(fake.calls) == 1, (
        f"{len(fake.calls)} calls: a 20-level colour cast in the ring is not flat paper"
    )


def test_an_even_ring_takes_the_lower_median(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.5: per channel, the value at index `(n - 1) // 2` of the `n` ring
    values sorted - never a `.5`, never the upper one. A 1-px hole at radius 1
    has a ring of exactly 4 (the 3 x 3 element is a plus): two pixels of
    (250, 100, 30) above and left, two of (252, 102, 34) right and below. The
    lower median is (250, 100, 30); the upper is (252, 102, 34), the mean
    (251, 101, 32). Spread 4, under the limit of 8."""
    _set_flat(monkeypatch, ring_px=1, max_spread=8)
    page = _paper_page((200, 200), (251, 101, 31))
    page[100, 100] = 0
    page[99, 100] = page[100, 99] = (250, 100, 30)
    page[100, 101] = page[101, 100] = (252, 102, 34)
    mask = _mask((200, 200), (100, 100, 101, 101))
    ring = _flat_ring(mask, 1)
    assert int(ring.sum()) == 4 and _spread(page, ring) == 4, "the Given"
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 0, f"{len(fake.calls)} calls for a ring of spread 4 at limit 8"
    _assert_filled_with(result, mask, (250, 100, 30), "even ring")


def test_an_empty_ring_is_not_flat_and_takes_the_model() -> None:
    """C-2.2: a component that is the whole page has no ring, at any radius,
    so it is not flat and takes the model as today: one call, the model's
    output in every pixel."""
    page = _paper_page((64, 48))
    mask = np.ones((48, 64), dtype=bool)
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 1, f"{len(fake.calls)} calls for a whole-page component"
    _assert_filled_with(result, mask, _PATCH, "whole page")


def test_a_ring_radius_of_zero_switches_the_fill_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.2: `FLAT_RING_PX = 0` leaves every ring empty, so AC-1's page, which
    the fill would otherwise take, goes to the model."""
    _set_flat(monkeypatch, ring_px=0, max_spread=8)
    page, mask = _ac1_page()
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 1, f"{len(fake.calls)} calls with a ring radius of 0"
    _assert_filled_with(result, mask, _PATCH, "ring radius 0")


def test_a_neighbouring_components_ink_in_reach_does_not_defeat_flat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.1 "minus every pixel of the whole erase mask": two holes of solid
    black ink 3 px apart, each inside the other's ring at radius 4. The
    neighbour's ink is about to be erased, so it is not counted: both are
    flat, both are paper, and the model is never called - in either label
    order, since the ring holds only pixels `clean_page` never writes."""
    _set_flat(monkeypatch, ring_px=4, max_spread=8)
    first, second = (150, 130, 190, 160), (193, 130, 233, 160)
    page = _paper_page(_NATIVE_SIZE)
    _ink(page, first, inset=0)
    _ink(page, second, inset=0)
    mask = _mask(_NATIVE_SIZE, first, second)
    assert len(_components(mask)) == 2, "the Given: two components"
    alone = _flat_ring(_mask(_NATIVE_SIZE, first), 4)
    assert bool((alone & _mask(_NATIVE_SIZE, second)).any()), "the Given: in each other's reach"
    fake = FakeInpaintSession("constant")

    result = clean_page(page, mask, fake)

    assert len(fake.calls) == 0, (
        f"{len(fake.calls)} calls: a neighbour's ink inside the erase mask counted as ring"
    )
    _assert_filled_with(result, mask, _WHITE_PAPER, "two neighbours")
    _assert_outside_untouched(result, page, mask)


# -- AC-5: the ghost, measured -----------------------------------------------------


def test_the_ghost_metric_sees_a_difference_from_the_ring_median_in_any_channel() -> None:
    """The instrument, checked before it judges (C-4): `ghost` is 0 on a hole
    of paper, 252 on the uncleaned AC-1 page (its ink), and 3 on a hole of paper
    with one pixel 3 levels off in green alone - the maximum is over the
    channels, not of a grey."""
    page, mask = _ac1_page()
    assert ghost(page, mask) == _PAPER, "the uncleaned page's ink"
    paper = page.copy()
    paper[mask] = _PAPER
    assert ghost(paper, mask) == 0, "a hole of paper"
    paper[_NATIVE_HOLE[1] + 5, _NATIVE_HOLE[0] + 5, 1] = _PAPER - 3
    assert ghost(paper, mask) == 3, "one pixel 3 off in green"


def test_the_flat_fill_leaves_no_ghost_where_the_model_would_have_tinted_the_paper() -> None:
    """**AC-5**: with a session double that returns the paper minus 6, the
    cleaned AC-1 page scores a ghost of 0 - the model is not asked, so its tint
    never lands."""
    page, mask = _ac1_page()
    session = _TintSession()

    result = clean_page(page, mask, session)

    score = ghost(result, mask)
    assert score == 0, (
        f"ghost {score} on flat paper ({session.calls} model calls): the model's tint landed"
        " where the paper's own colour should have been written"
    )


def test_with_the_fill_switched_off_the_tint_is_a_ghost_of_six(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-5's first control**, that the metric can see a ghost: AC-1's page
    with the fill off (`FLAT_MAX_SPREAD = -1`, C-2.4) goes to the double, and
    scores 6."""
    monkeypatch.setattr(inpaint_module, "FLAT_MAX_SPREAD", _OFF, raising=False)
    page, mask = _ac1_page()
    session = _TintSession()

    result = clean_page(page, mask, session)

    assert session.calls == 1, f"{session.calls} model calls with the fill off"
    assert ghost(result, mask) == _TINT


def test_a_hole_that_is_not_flat_keeps_the_models_tint_with_the_fill_on() -> None:
    """**AC-5's second control**: AC-4's page, whose ring holds an outline
    pixel, is not flat, so with the fill on it still goes to the double and
    scores 6 - the fill does not reach a component it may not take."""
    page, mask = _ac4_page()
    session = _TintSession()

    result = clean_page(page, mask, session)

    assert session.calls == 1, f"{session.calls} model calls for a ring with an outline in it"
    assert ghost(result, mask) == _TINT


# -- AC-6: one page, both kinds ----------------------------------------------------

#: A 500 x 400 page, so every window is the whole page at origin (0, 0): flat
#: paper left of x = 250, screentone from x = 250. The flat hole is first in
#: label order; each hole's ring, at any radius up to 16, stays on its own side.
_BOTH_SIZE = (500, 400)
_BOTH_FLAT_HOLE = (60, 60, 100, 90)
_BOTH_TONE_HOLE = (340, 200, 380, 230)


def _both_page() -> tuple[NDArray[np.uint8], NDArray[np.bool_], NDArray[np.bool_]]:
    page = _screentone(_BOTH_SIZE)
    page[:, :250] = _PAPER
    _ink(page, _BOTH_FLAT_HOLE)
    _ink(page, _BOTH_TONE_HOLE)
    return page, _mask(_BOTH_SIZE, _BOTH_FLAT_HOLE), _mask(_BOTH_SIZE, _BOTH_TONE_HOLE)


def test_on_a_page_with_both_kinds_only_the_screentone_hole_goes_to_the_model() -> None:
    """**AC-6**: one call, for the screentone hole; its mask is exactly that
    hole's pixels and none of the flat hole's; the flat hole is filled as in
    AC-1, the tone hole holds the model's output, and no pixel outside the
    erase mask changes."""
    page, flat, tone = _both_page()
    fake = FakeInpaintSession("constant")

    result = clean_page(page, flat | tone, fake)

    assert fake.violations == []
    assert len(fake.calls) == 1, f"{len(fake.calls)} calls, wanted 1: the screentone hole's"
    _image, model_mask = fake.calls[0]
    holes = model_mask[0, 0] == 1.0
    height, width = flat.shape
    assert not holes[height:, :].any() and not holes[:, width:].any()
    masked_flat = int((holes[:height, :width] & flat).sum())
    assert masked_flat == 0, f"the call masked {masked_flat} pixels of the flat hole"
    assert np.array_equal(holes[:height, :width], tone), "the call's mask is not the tone hole"
    _assert_filled_with(result, flat, _WHITE_PAPER, "the flat hole")
    _assert_filled_with(result, tone, _PATCH, "the screentone hole")
    _assert_outside_untouched(result, page, flat | tone)


def test_a_later_window_shows_an_earlier_flat_component_as_filled_paper() -> None:
    """C-2.6's consequence: a later component's window is cut from the working
    result, so the screentone hole's window shows the flat hole, cleaned
    earlier in label order, as 252 paper rather than its ink."""
    page, flat, tone = _both_page()
    fake = FakeInpaintSession("constant")

    clean_page(page, flat | tone, fake)

    assert len(fake.calls) == 1, f"{len(fake.calls)} calls, wanted 1"
    image, _ = fake.calls[0]
    height, width = flat.shape
    seen = _seen(image)[:height, :width]
    _assert_filled_with(seen, flat, _WHITE_PAPER, "the flat hole as the model sees it")
