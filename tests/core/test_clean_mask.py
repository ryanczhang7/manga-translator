"""`mangatl.clean.mask.erase_mask`: the pixels cleaning is allowed to touch (MT-019).

Covers AC-1 (the erase mask is the region masks dilated by `MASK_DILATION_PX`
and clipped to the page) and the mask half of AC-5 (a dilation that would run
past the page edge is clipped, without an index error).

**The oracle is C-3's, read out, not a re-derived kernel.** C-3 pins the exact
structuring element - `cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2r+1,
2r+1))` - so the neighbourhood a single set pixel grows into is compared with
that element exactly; beside it stand the three facts C-3 states in words (the
pixel at distance `r` along an axis is set, the one at `r + 1` is not, and for
`r >= 2` the diagonal corner `(y + r, x + r)` is not - a disk, not a square),
so a reader does not have to trust the element to know what is being asserted.

**How the disk is pinned independently of the shipped value** (C-3 asked RED to
say). `MASK_DILATION_PX` is measured in GREEN and may legitimately come out as
0, at which point every axis assertion against the shipped value degrades to the
identity. So the shape tests set the constant with `monkeypatch.setattr` on the
module, for `r in {0, 1, 2, 3}`, and C-3 is amended to say `erase_mask` reads
`MASK_DILATION_PX` from its module at call time (never captured as a default
argument or a precomputed kernel at import). One further test runs against the
shipped value untouched, so the constant GREEN chooses is exercised as shipped.

Masks are built with PIL (`Image.fromarray(bool array)` saves a mode-`1`, 1-bit
PNG - the encoding MT-007 C-7 writes) rather than `conftest.one_bit_png`, whose
per-pixel loop costs ~280 ms for a page-sized mask (measured in MT-009).

**MT-152** adds the growth into cut glyphs (AC-1..AC-4, AC-7, C-1..C-4) below
the `== MT-152` line; its own header says how the constants and the oracle are
handled. The tests above it call `erase_mask` with two arguments and are AC-4's
evidence that a caller passing no page is unchanged.

Nothing here loads a model. No per-test timeout exists in this project
(`pytest-timeout` is not a dependency), so there is no budget to size; every
test here is a handful of page-sized boolean arrays.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Sequence
from fractions import Fraction
from io import BytesIO
from typing import cast

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

import mangatl.clean.mask as mask_module
from mangatl.clean.mask import MASK_DILATION_PX, erase_mask
from mangatl.domain.region import RawRegion

#: A non-square page, `(width, height)`. W != H so that a `(width, height)` /
#: `(height, width)` confusion produces the wrong shape instead of passing.
_PAGE = (240, 160)

#: The dilation radii the disk is pinned at, independently of the shipped value.
_RADII = (0, 1, 2, 3)


def _png(mask: NDArray[np.bool_]) -> bytes:
    """A boolean `(height, width)` array as a 1-bit PNG, MT-007's encoding."""
    buffer = BytesIO()
    Image.fromarray(mask).save(buffer, format="PNG")
    return buffer.getvalue()


def _region(mask: NDArray[np.bool_]) -> RawRegion:
    """A `RawRegion` carrying `mask`. The polygon is irrelevant to `erase_mask`."""
    return RawRegion(
        polygon=((0, 0), (1, 0), (1, 1), (0, 0)),
        mask=_png(mask),
        confidence=0.9,
        kind="bubble",
    )


def _blank(size: tuple[int, int]) -> NDArray[np.bool_]:
    width, height = size
    return np.zeros((height, width), dtype=bool)


def _point_region(size: tuple[int, int], y: int, x: int) -> RawRegion:
    mask = _blank(size)
    mask[y, x] = True
    return _region(mask)


def _rect_region(size: tuple[int, int], rect: tuple[int, int, int, int]) -> RawRegion:
    """A region whose mask is the half-open page rectangle `(x0, y0, x1, y1)`."""
    x0, y0, x1, y1 = rect
    mask = _blank(size)
    mask[y0:y1, x0:x1] = True
    return _region(mask)


def _kernel(radius: int) -> NDArray[np.bool_]:
    """C-3's structuring element, read out of the contract."""
    side = 2 * radius + 1
    element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
    return np.asarray(element, dtype=bool)


# -- shape, dtype and the empty case -------------------------------------------


def test_the_erase_mask_is_a_height_by_width_boolean_array_for_a_width_height_page_size() -> None:
    """C-3: `page_size` is `(width, height)`, the result is `(height, width)`."""
    width, height = _PAGE
    result = erase_mask([_point_region(_PAGE, 10, 20)], _PAGE)

    assert result.shape == (height, width)
    assert result.dtype == np.bool_


def test_no_regions_gives_an_all_false_mask_of_the_page_shape() -> None:
    """C-3: `regions == []` is not an error; it is a page with nothing to erase."""
    width, height = _PAGE
    result = erase_mask([], _PAGE)

    assert result.shape == (height, width)
    assert result.dtype == np.bool_
    assert not result.any()


# -- AC-1: dilation by MASK_DILATION_PX, the disk pinned per radius --------------


@pytest.mark.parametrize("radius", _RADII)
def test_a_single_mask_pixel_dilates_to_the_elliptical_kernel_centred_on_it(
    radius: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1: a lone pixel well inside the page grows into exactly C-3's element.

    The 9x9 neighbourhood is compared, not just the element's own footprint, so
    a dilation that reached further than `r` is caught as well as one that fell
    short.
    """
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", radius)
    y, x = 80, 120
    result = erase_mask([_point_region(_PAGE, y, x)], _PAGE)

    expected = np.zeros((9, 9), dtype=bool)
    expected[4 - radius : 5 + radius, 4 - radius : 5 + radius] = _kernel(radius)
    assert np.array_equal(result[y - 4 : y + 5, x - 4 : x + 5], expected), (
        f"r={radius}: the neighbourhood of the dilated pixel is not the"
        f" MORPH_ELLIPSE element of side {2 * radius + 1}"
    )
    assert int(result.sum()) == int(_kernel(radius).sum()), (
        "pixels were set away from the dilated point"
    )


@pytest.mark.parametrize("radius", [r for r in _RADII if r >= 1])
def test_the_dilation_reaches_exactly_r_pixels_along_each_axis(
    radius: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1, C-3's oracle in words: distance `r` along an axis is set, `r + 1`
    is not, in all four directions."""
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", radius)
    y, x = 80, 120
    result = erase_mask([_point_region(_PAGE, y, x)], _PAGE)

    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        assert result[y + dy * radius, x + dx * radius], (
            f"r={radius}: the pixel {radius} px away along ({dy}, {dx}) is not set"
        )
        assert not result[y + dy * (radius + 1), x + dx * (radius + 1)], (
            f"r={radius}: the pixel {radius + 1} px away along ({dy}, {dx}) is set"
        )


@pytest.mark.parametrize("radius", [r for r in _RADII if r >= 2])
def test_the_dilation_is_a_disk_and_not_a_square(
    radius: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1, C-3: for `r >= 2` the diagonal corner `(y + r, x + r)` is not set."""
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", radius)
    y, x = 80, 120
    result = erase_mask([_point_region(_PAGE, y, x)], _PAGE)

    for dy, dx in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        assert not result[y + dy * radius, x + dx * radius], (
            f"r={radius}: the corner ({dy * radius}, {dx * radius}) is set - a square"
            " kernel, not the ellipse"
        )


def test_radius_zero_is_the_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-3: `r = 0` returns the union of the masks unchanged."""
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", 0)
    mask = _blank(_PAGE)
    mask[30:50, 40:90] = True
    mask[100, 200] = True

    result = erase_mask([_region(mask)], _PAGE)

    assert np.array_equal(result, mask)


def test_the_shipped_dilation_constant_is_what_erase_mask_applies() -> None:
    """AC-1 against the value GREEN ships, untouched: a lone pixel grows into
    the element of radius `MASK_DILATION_PX`, read from the module."""
    assert isinstance(MASK_DILATION_PX, int)
    assert MASK_DILATION_PX >= 0
    y, x = 80, 120
    result = erase_mask([_point_region(_PAGE, y, x)], _PAGE)

    r = MASK_DILATION_PX
    assert np.array_equal(result[y - r : y + r + 1, x - r : x + r + 1], _kernel(r))
    assert int(result.sum()) == int(_kernel(r).sum())


# -- AC-1: the union ------------------------------------------------------------


def test_the_erase_mask_is_the_union_of_every_regions_dilated_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: two separate regions both appear, each dilated; nothing else does."""
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", 2)
    first = (20, 20, 40, 30)
    second = (150, 100, 170, 140)

    both = erase_mask([_rect_region(_PAGE, first), _rect_region(_PAGE, second)], _PAGE)
    only_first = erase_mask([_rect_region(_PAGE, first)], _PAGE)
    only_second = erase_mask([_rect_region(_PAGE, second)], _PAGE)

    assert np.array_equal(both, only_first | only_second)
    assert only_first.any()
    assert only_second.any()
    assert not (only_first & only_second).any(), "the fixture regions must not touch"


def test_overlapping_regions_are_unioned_rather_than_counted_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: the overlap is one set of pixels; a bool mask cannot hold a count."""
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", 0)
    a = (20, 20, 60, 60)
    b = (40, 40, 80, 80)

    result = erase_mask([_rect_region(_PAGE, a), _rect_region(_PAGE, b)], _PAGE)

    assert int(result.sum()) == 40 * 40 + 40 * 40 - 20 * 20


# -- the decode: nonzero is in the mask, a wrong size is refused ------------------


def test_any_nonzero_pixel_of_an_eight_bit_mask_counts_as_in_the_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3: "nonzero = in the mask". A greyscale PNG with value 1 is a mask
    pixel, not a near-black background pixel."""
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", 0)
    width, height = _PAGE
    grey = np.zeros((height, width), dtype=np.uint8)
    grey[10:20, 30:40] = 1
    buffer = BytesIO()
    Image.fromarray(grey, mode="L").save(buffer, format="PNG")
    region = RawRegion(
        polygon=((0, 0), (1, 0), (1, 1), (0, 0)),
        mask=buffer.getvalue(),
        confidence=0.9,
        kind="box",
    )

    result = erase_mask([region], _PAGE)

    assert np.array_equal(result, grey != 0)


def test_a_region_mask_of_the_wrong_size_is_refused_naming_its_index() -> None:
    """C-3: never resize, transpose or crop a mask silently.

    The third region's mask is the page **transposed** - the most plausible way
    to get a wrong size, and the one a silent `.T` would "fix". The message must
    name index 2, the offending region's position in the sequence.
    """
    width, height = _PAGE
    good = _rect_region(_PAGE, (10, 10, 20, 20))
    transposed = _region(np.zeros((width, height), dtype=bool))

    with pytest.raises(ValueError, match=r"\b2\b"):
        erase_mask([good, good, transposed], _PAGE)


# -- AC-5 (mask half): a dilation running past the edge is clipped ------------------


@pytest.mark.parametrize(
    ("corner", "y", "x"),
    [
        ("top-left", 0, 0),
        ("top-right", 0, _PAGE[0] - 1),
        ("bottom-left", _PAGE[1] - 1, 0),
        ("bottom-right", _PAGE[1] - 1, _PAGE[0] - 1),
    ],
)
@pytest.mark.parametrize("radius", [1, 3])
def test_a_dilation_past_a_page_corner_is_clipped_to_the_page(
    corner: str, y: int, x: int, radius: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1 and AC-5: a mask pixel on a corner dilates without an index error,
    the result keeps the page's shape, and exactly the in-page quarter of the
    element is set - nothing wraps round to the opposite edge."""
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", radius)
    width, height = _PAGE

    result = erase_mask([_point_region(_PAGE, y, x)], _PAGE)

    assert result.shape == (height, width), corner
    element = _kernel(radius)
    # The quarter of the element centred at (y, x) that lies inside the page.
    ky0 = radius - min(radius, y)
    ky1 = radius + min(radius, height - 1 - y) + 1
    kx0 = radius - min(radius, x)
    kx1 = radius + min(radius, width - 1 - x) + 1
    inside = element[ky0:ky1, kx0:kx1]
    assert int(result.sum()) == int(inside.sum()), (
        f"{corner}, r={radius}: {int(result.sum())} pixels set, expected the"
        f" {int(inside.sum())} of the element that lie inside the page"
    )
    py0, px0 = y - (radius - ky0), x - (radius - kx0)
    window = result[py0 : py0 + inside.shape[0], px0 : px0 + inside.shape[1]]
    assert np.array_equal(window, inside), corner


def test_a_region_along_a_whole_edge_is_clipped_and_keeps_the_page_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5: a region spanning the full top edge dilates downwards only."""
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", 3)
    width, height = _PAGE

    result = erase_mask([_rect_region(_PAGE, (0, 0, width, 2))], _PAGE)

    assert result.shape == (height, width)
    assert result[: 2 + 3, :].all()
    assert not result[2 + 3 :, :].any()


# == MT-152: a glyph the erase mask cuts is erased whole, on paper ===============
#
# Synthetic pages, `(height, width)` grey `uint8`: white paper (255), black glyph
# blobs (0), a balloon outline, a tone patch. "The mask" of a region is its own
# stored mask, before dilation.
#
# **The oracle is built here, never by the code under test** (C-7): every
# expected mask is a union of rectangles dilated by `_dilate`, C-3's elliptical
# element written out. Where a criterion says "equals `erase_mask(regions,
# size)`" the two-argument call is compared as the criterion says, and beside it
# the independent `_dilate(union)`.
#
# **The constants are set, never read** (C-1, C-6): `_glyph_constants` sets all
# five on the module with `monkeypatch` (`raising=False`, so the file runs before
# GREEN adds them) and the geometry is built from the values as set. The size and
# ring rules run across a band of each constant. Only three tests read the
# shipped values: the C-7 sanity bounds, a page-shaped page accepted, and one
# 10 px dot (a C-6 positive) that any acceptable derivation must grow.
#
# **Every call that passes a page goes through `_grown`**, which first asserts
# that `erase_mask` has C-1's `page` parameter. Before GREEN each such test fails
# on that assertion, naming what is missing, rather than on a `TypeError`.

_PAPER = 255
_BLACK = 0

#: C-6's provisional values. A starting point only: each test sets its own.
_PROVISIONAL: dict[str, float] = {
    "GLYPH_INK_GREY": 128,
    "GLYPH_MAX_SIDE_PX": 80,
    "GLYPH_RING_PX": 2,
    "GLYPH_PAPER_GREY": 200,
    "GLYPH_PAPER_RING_FRACTION": 0.8,
}

_GLYPH_NAMES = tuple(_PROVISIONAL)

#: Three settings of all five constants: C-6's, a tight one and a loose one.
#: AC-1's outcome must not depend on which a derivation lands on.
_CONSTANT_BANDS: dict[str, dict[str, float]] = {
    "provisional": dict(_PROVISIONAL),
    "tight": {
        "GLYPH_INK_GREY": 64,
        "GLYPH_MAX_SIDE_PX": 30,
        "GLYPH_RING_PX": 1,
        "GLYPH_PAPER_GREY": 240,
        "GLYPH_PAPER_RING_FRACTION": 0.95,
    },
    "loose": {
        "GLYPH_INK_GREY": 160,
        "GLYPH_MAX_SIDE_PX": 200,
        "GLYPH_RING_PX": 3,
        "GLYPH_PAPER_GREY": 170,
        "GLYPH_PAPER_RING_FRACTION": 0.5,
    },
}

Rect = tuple[int, int, int, int]  # x0, y0, x1, y1, half-open

#: AC-1's glyph: 20 wide, 30 tall. The region's mask covers its top 60 % (rows
#: 50..67 of 50..79) and 3 px of paper on three sides, as a real mask does.
_BLOB: Rect = (100, 50, 120, 80)
_TOP_60: Rect = (97, 47, 123, 68)
#: A second glyph on the same page, which no mask overlaps.
_UNTOUCHED: Rect = (170, 60, 185, 80)


def _glyph_constants(
    monkeypatch: pytest.MonkeyPatch, *, dilation: int = 2, **overrides: float
) -> dict[str, float]:
    """Set the five glyph constants and `MASK_DILATION_PX` on the module and
    return the values set. `raising=False`: before GREEN they do not exist."""
    values = {**_PROVISIONAL, **overrides}
    for name, value in values.items():
        monkeypatch.setattr(mask_module, name, value, raising=False)
    monkeypatch.setattr(mask_module, "MASK_DILATION_PX", dilation)
    return values


def _grown(regions: Sequence[RawRegion], size: tuple[int, int], page: object) -> NDArray[np.bool_]:
    """`erase_mask(regions, size, page)`, after checking C-1's signature."""
    parameters = inspect.signature(erase_mask).parameters
    assert "page" in parameters, (
        "erase_mask takes no `page` argument: C-1's third parameter"
        f" (`page: NDArray[np.uint8] | None = None`) is missing; it takes {list(parameters)}"
    )
    grow: Callable[..., NDArray[np.bool_]] = erase_mask
    return grow(regions, size, page)


def _paper(size: tuple[int, int] = _PAGE) -> NDArray[np.uint8]:
    width, height = size
    return np.full((height, width), _PAPER, dtype=np.uint8)


def _box(size: tuple[int, int], *rects: Rect) -> NDArray[np.bool_]:
    mask = _blank(size)
    for x0, y0, x1, y1 in rects:
        mask[y0:y1, x0:x1] = True
    return mask


def _ink(page: NDArray[np.uint8], rect: Rect, value: int = _BLACK) -> None:
    x0, y0, x1, y1 = rect
    page[y0:y1, x0:x1] = value


def _dilate(mask: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    """C-3 step 7, written out: the elliptical element of side `2r + 1`; `r = 0`
    is the identity. Off-page pixels contribute nothing (cv2's default border)."""
    if radius == 0:
        return mask.copy()
    side = 2 * radius + 1
    element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
    return np.asarray(cv2.dilate(mask.astype(np.uint8), element), dtype=bool)


def _differs(result: NDArray[np.bool_], expected: NDArray[np.bool_]) -> str:
    """One line a failure can be read from: what is missing, what is extra."""
    missing = int((expected & ~result).sum())
    extra = int((result & ~expected).sum())
    return f"{missing} expected pixels missing, {extra} unexpected pixels set"


def _ac1_world() -> tuple[NDArray[np.uint8], list[RawRegion], NDArray[np.bool_], NDArray[np.bool_]]:
    """AC-1's page, its one region, the region's mask and the blob."""
    page = _paper()
    _ink(page, _BLOB)
    _ink(page, _UNTOUCHED)
    mask = _box(_PAGE, _TOP_60)
    return page, [_region(mask)], mask, _box(_PAGE, _BLOB)


# -- C-1: the names -------------------------------------------------------------


def test_the_five_glyph_constants_and_source_grey_are_exported_beside_the_old_names() -> None:
    """C-1: all five constants and `source_grey` are in `__all__`, and
    `MASK_DILATION_PX` and `erase_mask` still are."""
    exported = set(mask_module.__all__)
    missing = [
        name
        for name in (*_GLYPH_NAMES, "source_grey", "MASK_DILATION_PX", "erase_mask")
        if name not in exported or not hasattr(mask_module, name)
    ]
    assert missing == [], f"mangatl.clean.mask does not define and export {missing}"


def test_the_shipped_glyph_constants_satisfy_what_any_derivation_must() -> None:
    """C-7, oracle-free: never a value, only what every derivation must hold -
    `0 < INK < PAPER <= 255`, `0 < FRACTION <= 1`, `MAX_SIDE >= 1`, `RING >= 1`."""
    values = {name: getattr(mask_module, name, None) for name in _GLYPH_NAMES}
    assert None not in values.values(), f"not defined yet: {values}"
    for name in ("GLYPH_INK_GREY", "GLYPH_MAX_SIDE_PX", "GLYPH_RING_PX", "GLYPH_PAPER_GREY"):
        value = values[name]
        assert isinstance(value, int) and not isinstance(value, bool), f"{name} = {value!r}"
    fraction = values["GLYPH_PAPER_RING_FRACTION"]
    assert isinstance(fraction, float), f"GLYPH_PAPER_RING_FRACTION = {fraction!r}"
    ink, paper = int(values["GLYPH_INK_GREY"]), int(values["GLYPH_PAPER_GREY"])
    assert 0 < ink < paper <= 255, f"GLYPH_INK_GREY {ink}, GLYPH_PAPER_GREY {paper}"
    assert 0 < fraction <= 1, f"GLYPH_PAPER_RING_FRACTION {fraction}"
    assert int(values["GLYPH_MAX_SIDE_PX"]) >= 1, values["GLYPH_MAX_SIDE_PX"]
    assert int(values["GLYPH_RING_PX"]) >= 1, values["GLYPH_RING_PX"]


# -- C-2: the one grey conversion -------------------------------------------------


def _source_grey() -> Callable[[NDArray[np.uint8]], NDArray[np.uint8]]:
    """`mangatl.clean.mask.source_grey`, read late so this file imports before GREEN."""
    function = getattr(mask_module, "source_grey", None)
    assert callable(function), "mangatl.clean.mask.source_grey does not exist (C-1, C-2)"
    return cast("Callable[[NDArray[np.uint8]], NDArray[np.uint8]]", function)


def test_source_grey_is_pils_601_luma_of_the_rgb_page() -> None:
    """C-2: `np.asarray(Image.fromarray(rgb, "RGB").convert("L"))`, exactly, as
    an `(H, W)` `uint8` array. Every channel varies independently, so a mean, a
    single channel or a BGR reading differs from it somewhere."""
    source_grey = _source_grey()
    rng = np.random.default_rng(152)
    rgb = rng.integers(0, 256, size=(37, 53, 3), dtype=np.uint8)

    grey = source_grey(rgb)

    expected = np.asarray(Image.fromarray(rgb, "RGB").convert("L"))
    assert grey.shape == (37, 53), grey.shape
    assert grey.dtype == np.uint8, grey.dtype
    assert np.array_equal(grey, expected), (
        f"{int((grey != expected).sum())} of {expected.size} pixels are not PIL's L of the page"
    )


def test_source_grey_of_a_greyscale_scan_is_the_grey_itself() -> None:
    """C-2: for a greyscale scan the round trip is exact, at all 256 levels."""
    source_grey = _source_grey()
    levels = np.arange(256, dtype=np.uint8).reshape(16, 16)

    grey = source_grey(np.stack([levels] * 3, axis=-1))

    assert np.array_equal(grey, levels)


# -- AC-1: a cut glyph is erased whole -------------------------------------------


@pytest.mark.parametrize("band", sorted(_CONSTANT_BANDS))
@pytest.mark.parametrize("radius", [0, 2, 3])
def test_a_glyph_whose_top_60_percent_is_masked_is_erased_whole_and_nothing_else_is_added(
    band: str, radius: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**AC-1**: the result is exactly `(mask | whole blob)` dilated by
    `MASK_DILATION_PX` - the lower 40 % of the blob is in it, and nothing else
    is: not the second glyph on the page, which no mask overlaps."""
    _glyph_constants(monkeypatch, dilation=radius, **_CONSTANT_BANDS[band])
    page, regions, mask, blob = _ac1_world()

    result = _grown(regions, _PAGE, page)

    expected = _dilate(mask | blob, radius)
    lower = blob & ~mask
    assert result.shape == mask.shape and result.dtype == np.bool_
    assert bool(result[lower].all()), (
        f"{int((lower & ~result).sum())} of {int(lower.sum())} pixels of the glyph's"
        " unmasked lower 40 % are not in the erase mask; AC-1 erases the glyph whole"
    )
    assert np.array_equal(result, expected), (
        f"band {band}, r={radius}: {_differs(result, expected)}"
    )


def test_a_glyph_is_touched_only_by_the_raw_mask_never_by_its_dilation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3 step 3: a glyph one paper row below the mask is inside the
    *dilated* mask's reach (r = 2) but overlaps no raw mask pixel, so it is not
    grown into: only the dilation's own reach of it is in the result."""
    _glyph_constants(monkeypatch, dilation=2)
    page = _paper()
    near: Rect = (100, 69, 120, 90)  # row 68 is paper; the mask ends at row 67
    _ink(page, near)
    mask = _box(_PAGE, (97, 47, 123, 68))

    result = _grown([_region(mask)], _PAGE, page)

    expected = _dilate(mask, 2)
    assert bool((expected & _box(_PAGE, near)).any()), "the fixture: the dilation reaches it"
    assert np.array_equal(result, expected), _differs(result, expected)
    assert np.array_equal(result, erase_mask([_region(mask)], _PAGE))


def test_a_glyph_is_not_grown_into_because_a_grown_glyph_reaches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3: growth happens once. The cut glyph is grown whole; a second glyph
    two paper rows below it is within the dilation of the GROWN pixels, and
    outside the ring (`GLYPH_RING_PX = 1`), but no mask overlaps it: only the
    dilation's reach of it is in the result, never the whole of it."""
    _glyph_constants(monkeypatch, dilation=2, GLYPH_RING_PX=1)
    page = _paper()
    _ink(page, _BLOB)
    below: Rect = (100, 82, 120, 100)  # rows 80 and 81 are paper
    _ink(page, below)
    mask = _box(_PAGE, _TOP_60)

    result = _grown([_region(mask)], _PAGE, page)

    expected = _dilate(mask | _box(_PAGE, _BLOB), 2)
    assert np.array_equal(result, expected), _differs(result, expected)


def test_components_are_eight_connected_so_a_diagonal_join_is_one_glyph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3 step 2: two strokes meeting only corner to corner are one
    8-connected component. The mask covers part of the upper stroke; the
    lower stroke is grown too. A 4-connected labelling leaves it out."""
    _glyph_constants(monkeypatch, dilation=2)
    page = _paper()
    upper: Rect = (100, 50, 110, 60)
    lower: Rect = (110, 60, 120, 75)  # (109, 59) and (110, 60) touch diagonally
    _ink(page, upper)
    _ink(page, lower)
    mask = _box(_PAGE, (98, 48, 112, 55))

    result = _grown([_region(mask)], _PAGE, page)

    expected = _dilate(mask | _box(_PAGE, upper, lower), 2)
    assert np.array_equal(result, expected), _differs(result, expected)


@pytest.mark.parametrize("ink_grey", [64, 128, 160])
def test_a_pixel_at_the_ink_limit_is_ink_and_one_level_lighter_is_not(
    ink_grey: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-3 step 1, `page <= GLYPH_INK_GREY`, across a band of the constant: the
    glyph's unmasked lower 40 % at exactly the limit is part of it and is
    grown; one level lighter it is not ink, so nothing is added."""
    _glyph_constants(monkeypatch, dilation=2, GLYPH_INK_GREY=ink_grey, GLYPH_PAPER_GREY=230)
    mask = _box(_PAGE, _TOP_60)
    blob = _box(_PAGE, _BLOB)
    lower = blob & ~mask

    at_limit = _paper()
    at_limit[mask & blob] = _BLACK
    at_limit[lower] = ink_grey
    lighter = at_limit.copy()
    lighter[lower] = ink_grey + 1

    grown = _grown([_region(mask)], _PAGE, at_limit)
    not_grown = _grown([_region(mask)], _PAGE, lighter)

    expected = _dilate(mask | blob, 2)
    assert np.array_equal(grown, expected), f"at the limit: {_differs(grown, expected)}"
    assert np.array_equal(not_grown, _dilate(mask, 2)), (
        f"one level lighter: {_differs(not_grown, _dilate(mask, 2))}"
    )


# -- AC-1 and AC-2's rule: the size limit, equal is a glyph ----------------------


def _bar(orientation: str, side: int) -> tuple[Rect, Rect]:
    """A solid 8 px bar `side` long from (20, 20), and a mask over its first 6 px
    along its length (2 px of paper round it)."""
    x0, y0 = 20, 20
    if orientation == "wide":
        return (x0, y0, x0 + side, y0 + 8), (x0 - 2, y0 - 2, x0 + 6, y0 + 10)
    return (x0, y0, x0 + 8, y0 + side), (x0 - 2, y0 - 2, x0 + 10, y0 + 6)


@pytest.mark.parametrize("orientation", ["wide", "tall"])
@pytest.mark.parametrize("max_side", [12, 40, 80, 120])
def test_a_solid_glyph_exactly_at_the_size_limit_is_grown_and_one_pixel_over_is_not(
    max_side: int, orientation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-3 step 4, across a band of `GLYPH_MAX_SIDE_PX`: a bounding box exactly
    the limit wide (or tall) is a glyph; one pixel more is not, whichever
    side it is."""
    _glyph_constants(monkeypatch, dilation=2, GLYPH_MAX_SIDE_PX=max_side)
    for side, is_glyph in ((max_side, True), (max_side + 1, False)):
        bar, cover = _bar(orientation, side)
        page = _paper()
        _ink(page, bar)
        mask = _box(_PAGE, cover)

        result = _grown([_region(mask)], _PAGE, page)

        expected = _dilate(mask | _box(_PAGE, bar), 2) if is_glyph else _dilate(mask, 2)
        assert np.array_equal(result, expected), (
            f"{orientation} side {side} against GLYPH_MAX_SIDE_PX {max_side}"
            f" ({'a glyph' if is_glyph else 'not a glyph'}): {_differs(result, expected)}"
        )


# -- AC-2: a balloon's outline is never grown into ------------------------------


def _outline_world(
    longer_side: int, orientation: str
) -> tuple[NDArray[np.uint8], NDArray[np.bool_], NDArray[np.bool_]]:
    """A 2 px balloon outline on white paper, `longer_side` along one axis and
    40 px along the other, and a region mask overlapping its left edge and
    some of the balloon's inside. Returns the page, the mask and the outline."""
    x0, y0 = 8, 8
    width, height = (longer_side, 40) if orientation == "wide" else (40, longer_side)
    outline = _box(_PAGE, (x0, y0, x0 + width, y0 + height))
    outline &= ~_box(_PAGE, (x0 + 2, y0 + 2, x0 + width - 2, y0 + height - 2))
    page = _paper()
    page[outline] = _BLACK
    mask = _box(_PAGE, (x0 - 1, y0 + 12, x0 + 12, y0 + 26))
    return page, mask, outline


@pytest.mark.parametrize("orientation", ["wide", "tall"])
@pytest.mark.parametrize("max_side", [30, 80, 120])
def test_a_balloon_outline_the_mask_overlaps_is_not_added(
    max_side: int, orientation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**AC-2**, across a band of `GLYPH_MAX_SIDE_PX`: the outline is one
    component one pixel longer than the limit, on paper (its ring is all
    white, so only the size rule can hold it back). The result equals
    `erase_mask(regions, size)`: no outline pixel is added."""
    _glyph_constants(monkeypatch, dilation=2, GLYPH_MAX_SIDE_PX=max_side)
    page, mask, _outline = _outline_world(max_side + 1, orientation)
    regions = [_region(mask)]

    result = _grown(regions, _PAGE, page)

    today = erase_mask(regions, _PAGE)
    added = int((result & ~today).sum())
    assert added == 0, (
        f"{added} pixels were added past erase_mask(regions, size); an outline"
        f" {max_side + 1} px long is not a glyph under GLYPH_MAX_SIDE_PX {max_side}"
    )
    assert np.array_equal(result, today), _differs(result, today)
    assert np.array_equal(today, _dilate(mask, 2))


@pytest.mark.parametrize("orientation", ["wide", "tall"])
@pytest.mark.parametrize("raised_by", [0, 1, 50])
def test_the_same_outline_is_added_once_the_size_limit_is_raised_above_it(
    raised_by: int, orientation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**AC-2's control**: the same page and mask with `GLYPH_MAX_SIDE_PX`
    raised to the outline's longer side (equal is a glyph), or above it, DOES
    add the whole outline - so the size rule is what held it back above."""
    longer_side = 81
    _glyph_constants(monkeypatch, dilation=2, GLYPH_MAX_SIDE_PX=longer_side + raised_by)
    page, mask, outline = _outline_world(longer_side, orientation)

    result = _grown([_region(mask)], _PAGE, page)

    expected = _dilate(mask | outline, 2)
    assert bool(result[outline].all()), (
        f"{int((outline & ~result).sum())} of {int(outline.sum())} outline pixels are"
        f" not added with GLYPH_MAX_SIDE_PX {longer_side + raised_by}"
    )
    assert np.array_equal(result, expected), _differs(result, expected)


# -- AC-3: a glyph-sized blob in screentone is not grown into ---------------------


def _tone_world(
    tone: int | None,
) -> tuple[NDArray[np.uint8], NDArray[np.bool_], NDArray[np.bool_]]:
    """AC-1's blob and mask; with `tone`, inside a 120x100 tone patch of that
    grey (lighter than ink, darker than paper, so the blob is its own
    component and its whole ring is not paper). `None` is white paper."""
    page = _paper()
    if tone is not None:
        _ink(page, (60, 20, 180, 120), tone)
    _ink(page, _BLOB)
    return page, _box(_PAGE, _TOP_60), _box(_PAGE, _BLOB)


@pytest.mark.parametrize("fraction", [0.05, 0.5, 0.8, 1.0])
@pytest.mark.parametrize("ring_px", [1, 2, 3])
@pytest.mark.parametrize("shade", ["darkest", "middle", "lightest"])
def test_a_glyph_sized_blob_inside_screentone_is_not_added(
    shade: str, ring_px: int, fraction: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**AC-3**, across a band of `GLYPH_PAPER_RING_FRACTION` and
    `GLYPH_RING_PX`: the blob sits in a tone patch whose grey runs from one
    level above the ink limit to one level under the paper limit. Its ring holds
    no paper, under any fraction, so the result equals `erase_mask(regions, size)`."""
    values = _glyph_constants(
        monkeypatch, dilation=2, GLYPH_RING_PX=ring_px, GLYPH_PAPER_RING_FRACTION=fraction
    )
    ink, paper = int(values["GLYPH_INK_GREY"]), int(values["GLYPH_PAPER_GREY"])
    tone = {"darkest": ink + 1, "middle": (ink + paper) // 2, "lightest": paper - 1}[shade]
    page, mask, _blob = _tone_world(tone)
    regions = [_region(mask)]

    result = _grown(regions, _PAGE, page)

    today = erase_mask(regions, _PAGE)
    assert np.array_equal(result, today), (
        f"tone {tone}, ring {ring_px} px, fraction {fraction}: {_differs(result, today)}"
        " against erase_mask(regions, size)"
    )


@pytest.mark.parametrize("fraction", [0.05, 0.5, 0.8, 1.0])
@pytest.mark.parametrize("ring_px", [1, 2, 3])
def test_the_same_blob_and_mask_on_white_paper_is_added_whole(
    ring_px: int, fraction: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**AC-3's control**: the same blob and mask with the tone patch gone is
    added whole, under every setting the test above runs - so the ring is what
    held it back there."""
    _glyph_constants(
        monkeypatch, dilation=2, GLYPH_RING_PX=ring_px, GLYPH_PAPER_RING_FRACTION=fraction
    )
    page, mask, blob = _tone_world(None)

    result = _grown([_region(mask)], _PAGE, page)

    expected = _dilate(mask | blob, 2)
    assert np.array_equal(result, expected), _differs(result, expected)


# -- C-3 step 5: the ring, exactly ------------------------------------------------

#: Dyadic fractions, so `k / n == fraction` is exact in binary floating point and
#: "equal to the limit is a glyph" is a statement about the rule, not about
#: rounding.
_DYADIC_FRACTIONS = (0.5, 0.75, 0.875, 1.0)


def _ring_of(component: NDArray[np.bool_], ring_px: int) -> NDArray[np.bool_]:
    """C-3 step 5, on the page: the component dilated by the element of side
    `2 x ring + 1`, minus the component. Off-page pixels are not in it."""
    return _dilate(component, ring_px) & ~component


def _ring_page(
    component: NDArray[np.bool_], ring: NDArray[np.bool_], paper_count: int, paper: int
) -> NDArray[np.uint8]:
    """A page where the component is black and exactly `paper_count` of its ring
    pixels (the first in raster order) are paper at exactly `paper`; every other
    pixel is one level darker than paper - not paper, not ink."""
    page = np.full(component.shape, paper - 1, dtype=np.uint8)
    page[component] = _BLACK
    ys, xs = np.nonzero(ring)
    page[ys[:paper_count], xs[:paper_count]] = paper
    return page


def _limit_count(fraction: float, ring_size: int) -> int:
    """The fewest paper pixels whose share of the ring is at least `fraction`."""
    return math.ceil(Fraction(fraction) * ring_size)


@pytest.mark.parametrize("fraction", _DYADIC_FRACTIONS)
@pytest.mark.parametrize("ring_px", [1, 2, 3])
def test_a_ring_exactly_at_the_paper_fraction_is_a_glyph_and_one_paper_pixel_fewer_is_not(
    ring_px: int, fraction: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-3 steps 4 and 5, across a band of both constants: with `k` the fewest
    paper pixels reaching `GLYPH_PAPER_RING_FRACTION` of the ring, `k` paper
    pixels (each at exactly `GLYPH_PAPER_GREY`) make the cut blob a glyph and
    `k - 1` do not. Everything else in the ring is one level under paper."""
    values = _glyph_constants(
        monkeypatch, dilation=2, GLYPH_RING_PX=ring_px, GLYPH_PAPER_RING_FRACTION=fraction
    )
    paper = int(values["GLYPH_PAPER_GREY"])
    blob = _box(_PAGE, (100, 50, 112, 64))
    ring = _ring_of(blob, ring_px)
    k = _limit_count(fraction, int(ring.sum()))
    mask = _box(_PAGE, (98, 48, 114, 58))
    regions = [_region(mask)]

    at_limit = _grown(regions, _PAGE, _ring_page(blob, ring, k, paper))
    under = _grown(regions, _PAGE, _ring_page(blob, ring, k - 1, paper))

    grown, today = _dilate(mask | blob, 2), _dilate(mask, 2)
    assert np.array_equal(at_limit, grown), (
        f"{k} of {int(ring.sum())} ring pixels paper (fraction {fraction}, ring {ring_px} px)"
        f" is a glyph: {_differs(at_limit, grown)}"
    )
    assert np.array_equal(under, today), (
        f"{k - 1} of {int(ring.sum())} ring pixels paper (fraction {fraction}, ring"
        f" {ring_px} px) is not a glyph: {_differs(under, today)}"
    )


def test_a_component_with_no_ring_on_the_page_is_not_a_glyph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3 step 5: "an empty ring is not paper". A page that is all ink is one
    component of glyph size whose ring lies wholly off the page; it is not
    grown into, even under a fraction of 0.05."""
    small = (12, 10)
    _glyph_constants(monkeypatch, dilation=1, GLYPH_PAPER_RING_FRACTION=0.05)
    page = np.zeros((small[1], small[0]), dtype=np.uint8)
    mask = _box(small, (0, 0, 5, 4))

    result = _grown([_region(mask)], small, page)

    expected = _dilate(mask, 1)
    assert np.array_equal(result, expected), _differs(result, expected)


def _corner_ring_counts(blob: NDArray[np.bool_], ring_px: int) -> tuple[int, int]:
    """`(on the page, off the page)` ring pixel counts of a component, the
    second from the component dilated inside a frame padded by `ring_px`."""
    on_page = int(_ring_of(blob, ring_px).sum())
    padded = np.pad(blob, ring_px)
    whole = int((_dilate(padded, ring_px) & ~padded).sum())
    return on_page, whole - on_page


def test_off_page_ring_pixels_do_not_count_as_not_paper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3 step 5: pixels off the page are not counted. A glyph in the page's
    top-left corner on white paper has an all-paper ring on the page, so under
    a fraction of 1.0 it is grown. Counting the off-page part as not paper (a
    zero-padded page, say) holds it back."""
    _glyph_constants(monkeypatch, dilation=2, GLYPH_RING_PX=3, GLYPH_PAPER_RING_FRACTION=1.0)
    page = _paper()
    corner: Rect = (0, 0, 10, 12)
    _ink(page, corner)
    mask = _box(_PAGE, (0, 0, 12, 7))

    result = _grown([_region(mask)], _PAGE, page)

    expected = _dilate(mask | _box(_PAGE, corner), 2)
    assert np.array_equal(result, expected), _differs(result, expected)


def test_off_page_ring_pixels_do_not_count_as_paper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3 step 5, the other side: the corner glyph's on-page ring is one paper
    pixel short of a 0.5 fraction, so it is not a glyph. Counting the off-page
    part as paper (a white-padded page, say) would lift it over the limit -
    the fixture asserts that it would."""
    values = _glyph_constants(
        monkeypatch, dilation=2, GLYPH_RING_PX=3, GLYPH_PAPER_RING_FRACTION=0.5
    )
    paper = int(values["GLYPH_PAPER_GREY"])
    blob = _box(_PAGE, (0, 0, 10, 12))
    ring = _ring_of(blob, 3)
    on_page, off_page = _corner_ring_counts(blob, 3)
    k = _limit_count(0.5, on_page)
    assert Fraction(k - 1 + off_page, on_page + off_page) >= Fraction(1, 2), (
        "the fixture does not discriminate: off-page-as-paper would not reach 0.5"
    )
    page = _ring_page(blob, ring, k - 1, paper)
    mask = _box(_PAGE, (0, 0, 12, 7))

    result = _grown([_region(mask)], _PAGE, page)

    expected = _dilate(mask, 2)
    assert np.array_equal(result, expected), _differs(result, expected)


# -- C-3: growth distributes over union ------------------------------------------


def _distributive_cases() -> dict[str, tuple[NDArray[np.uint8], Rect, Rect]]:
    """Pages and two region rects, each a way a mask-dependent design breaks
    `erase_mask(A + B) == erase_mask(A) | erase_mask(B)`."""
    cases: dict[str, tuple[NDArray[np.uint8], Rect, Rect]] = {}
    page = _paper()
    _ink(page, _BLOB)
    _ink(page, _UNTOUCHED)
    cases["two regions, two glyphs"] = (page, _TOP_60, (168, 58, 187, 66))
    page = _paper()
    _ink(page, _BLOB)
    cases["two regions cut one glyph from both ends"] = (page, (98, 48, 122, 56), (98, 74, 122, 82))
    page = _paper()
    _ink(page, _BLOB)
    cases["one region splits a glyph, the other is paper"] = (
        page,
        (98, 60, 122, 66),
        (150, 20, 170, 40),
    )
    page = _paper()
    _ink(page, _BLOB)
    cases["the second region lies over the first glyph's ring"] = (
        page,
        (100, 50, 120, 68),
        (96, 80, 124, 83),
    )
    return cases


@pytest.mark.parametrize("case", sorted(_distributive_cases()))
def test_growth_distributes_over_the_union_of_regions(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-3: whether a component is a glyph depends on the page alone, so
    `erase_mask(A + B, size, page) == erase_mask(A, ...) | erase_mask(B, ...)`.
    `_restore_excluded` relies on it. A design that subtracts the mask before
    labelling, or reads the ring against the mask, breaks one of these."""
    _glyph_constants(monkeypatch, dilation=2)
    page, rect_a, rect_b = _distributive_cases()[case]
    a, b = _rect_region(_PAGE, rect_a), _rect_region(_PAGE, rect_b)

    together = _grown([a, b], _PAGE, page)
    apart = _grown([a], _PAGE, page) | _grown([b], _PAGE, page)

    assert np.array_equal(together, apart), f"{case}: {_differs(together, apart)}"
    blob = _box(_PAGE, _BLOB)
    assert bool(together[blob].all()), f"{case}: the cut glyph is not wholly in the mask"


# -- AC-4: no page, today's mask -------------------------------------------------


def test_with_page_none_or_no_page_the_mask_is_todays_union_dilated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-4**: on AC-1's page, `page=None` and no `page` both give exactly
    the union of the masks dilated - the blob's lower part is not in it. The
    control: the same call with the page does add it, so the page is what the
    growth reads."""
    _glyph_constants(monkeypatch, dilation=2)
    page, regions, mask, blob = _ac1_world()

    with_none = _grown(regions, _PAGE, None)
    keyword: Callable[..., NDArray[np.bool_]] = erase_mask
    by_keyword = keyword(regions, _PAGE, page=None)
    without = erase_mask(regions, _PAGE)

    today = _dilate(mask, 2)
    assert np.array_equal(with_none, today), f"page=None: {_differs(with_none, today)}"
    assert np.array_equal(by_keyword, today), f"page=None by keyword: {_differs(by_keyword, today)}"
    assert np.array_equal(without, today), f"no page: {_differs(without, today)}"
    assert bool((blob & ~today).any()), "the fixture: today's mask leaves part of the blob"
    assert not np.array_equal(_grown(regions, _PAGE, page), today), (
        "the control: with the page, AC-1's blob must be added"
    )


# -- AC-7: a page of the wrong shape or dtype is refused --------------------------

_W, _H = _PAGE


@pytest.mark.parametrize("with_region", [False, True])
@pytest.mark.parametrize(
    ("name", "page", "needles"),
    [
        ("three channels", np.full((_H, _W, 3), 255, np.uint8), ("240x160",)),
        ("transposed", np.full((_W, _H), 255, np.uint8), ("240x160",)),
        ("another size", np.full((_H + 3, _W + 1), 255, np.uint8), ("240x160", "163", "241")),
        ("float", np.full((_H, _W), 255.0, np.float32), ("float32",)),
        ("boolean", np.ones((_H, _W), dtype=bool), ("bool",)),
        ("sixteen bit", np.full((_H, _W), 255, np.uint16), ("uint16",)),
    ],
)
def test_a_page_of_the_wrong_shape_or_dtype_is_refused_naming_it(
    name: str,
    page: NDArray[np.generic],
    needles: tuple[str, ...],
    with_region: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-7**, C-4: never resized, transposed, cropped or cast. The message
    names the expected `width x height` and the page's own size, or the
    dtype. With no regions as well, so a check that only runs per region
    cannot pass it."""
    _glyph_constants(monkeypatch, dilation=2)
    regions = [_rect_region(_PAGE, _TOP_60)] if with_region else []

    with pytest.raises(ValueError) as caught:
        _grown(regions, _PAGE, page)

    message = str(caught.value)
    absent = [needle for needle in needles if needle not in message]
    assert absent == [], f"{name}: the message {message!r} does not name {absent}"


@pytest.mark.parametrize(
    ("page", "needle"),
    [
        (np.full((_H + 3, _W + 1), 255, np.uint8), "241"),
        (np.full((_H, _W), 255.0, np.float32), "float32"),
    ],
)
def test_the_page_is_refused_before_any_region_mask_is_decoded(
    page: NDArray[np.generic], needle: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-4: the page is checked before any mask is decoded. The only region's
    mask is 10x10, which would raise its own error naming region 0; the error
    raised is the page's."""
    _glyph_constants(monkeypatch, dilation=2)
    wrong_mask = _region(np.zeros((10, 10), dtype=bool))

    with pytest.raises(ValueError) as caught:
        _grown([wrong_mask], _PAGE, page)

    assert needle in str(caught.value), f"{caught.value!s} is not the page's error"


def test_a_page_sized_uint8_page_is_accepted() -> None:
    """AC-7's control: a `(height, width)` `uint8` page raises nothing, with
    the shipped constants untouched."""
    page, regions, _mask, _blob = _ac1_world()

    result = _grown(regions, _PAGE, page)

    assert result.shape == (_H, _W)


# -- the shipped constants, untouched ------------------------------------------------


def test_with_the_shipped_constants_a_cut_10px_dot_on_white_paper_is_erased_whole() -> None:
    """C-6: every positive the probe names must be grown by the derived
    values, and the `!!` dots on p084 are 10x10 with a ring of 0.887. A black
    10x10 dot on white paper, its top 6 rows masked, is the easiest of them:
    any derivation C-6 accepts grows it whole. The constants are not touched."""
    page = _paper()
    dot: Rect = (100, 50, 110, 60)
    _ink(page, dot)
    mask = _box(_PAGE, (98, 48, 112, 56))

    result = _grown([_region(mask)], _PAGE, page)

    dot_mask = _box(_PAGE, dot)
    assert bool(result[dot_mask].all()), (
        f"{int((dot_mask & ~result).sum())} of 100 dot pixels are not erased with the"
        " shipped constants"
    )
