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

Nothing here loads a model. No per-test timeout exists in this project
(`pytest-timeout` is not a dependency), so there is no budget to size; every
test here is a handful of page-sized boolean arrays.
"""

from __future__ import annotations

from io import BytesIO

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
