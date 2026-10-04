"""`mangatl.typeset.render.bake_page`: typeset English composited onto a cleaned page.

MT-021 C-1, C-2, C-3 and the array half of AC-2. `bake_chapter` (and the file
half of AC-2) is `test_bake.py`'s.

**The positional oracle, and why it is exact without depending on the
rasteriser.** Each glyph here is placed by hand so that the LEFT and TOP edges
of its ink box - read with fontTools by `_typeset_oracle`, which imports nothing
from `mangatl` - fall on a half pixel (`.5`), and the size is chosen (and checked,
`_case`) so that the RIGHT and BOTTOM edges fall between `.3` and `.7` of a pixel.
An anti-aliased rasteriser that draws the outline where C-2 says gives every
pixel the ink box touches by at least `.3` px a coverage well above `1/255`, and
every pixel it does not touch a coverage of exactly zero. So the set of
pixels the bake changed, per glyph, has as its bounding box EXACTLY the ink box
rounded outward - with no tolerance, and with no dependence on hinting,
anti-aliasing filter or supersampling factor below about 0.3 px of error.
Shift the composite by one pixel in x or in y and every one of the eight
bounding boxes is wrong (MT-021 deferred condition 3).

RED measured the oracle against Pillow two ways (story `## Handoff`): plain
`ImageDraw.text(..., anchor="ls")` at the glyph's own size is off by a pixel on
476 of 900 glyph/size/offset cases (hinting and integer placement), so C-2's
suggested mechanism does NOT hit the positions as written; the same call at 16x
the size, downsampled by a 16x16 box mean, matched every half-pixel edge. That
is GREEN's to choose; what is pinned is the position.

**Changed means `out != cleaned` in any channel**, and the cleaned page keeps
every channel at or above 128, where a coverage of 1 already changes the value
under C-2's formula (`round(dst * 254 / 255) < dst` iff `dst >= 128`). So
"changed" and "a > 0" are the same set here.

**The composite formula is checked without knowing `a`**: the cleaned page's
three channels differ, so a pixel is consistent with C-2 only if ONE `a` in
0..255 gives `round(dst_c * (255 - a) / 255)` for all three channels at once.
Ink that is not black, or an alpha applied per channel, breaks that.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import _typeset_oracle as oracle
import numpy as np
import pytest
from numpy.typing import NDArray

from mangatl.typeset.fit import Line, PlacedGlyph, TypesetBlock
from mangatl.typeset.render import bake_page

W, H = 160, 100


def _cleaned() -> NDArray[np.uint8]:
    """Every channel >= 128 and the three channels different everywhere."""
    y, x = np.mgrid[0:H, 0:W]
    rgb = np.stack([255 - (x % 16), 200 + (y % 32), 140 + ((x + y) % 50)], axis=-1)
    return rgb.astype(np.uint8)


@dataclass(frozen=True)
class _Case:
    char: str
    key: str
    size_px: float
    left: float  # ink x0, a half pixel
    top: float  # ink y0, a half pixel


def _glyph(case: _Case) -> PlacedGlyph:
    """A PlacedGlyph whose ink box starts exactly at (left, top) in page px."""
    ink = oracle.ink_px(case.char, case.key, case.size_px)
    assert ink is not None
    x0, y0, x1, y1 = ink
    x, baseline = case.left - x0, case.top - y0
    return PlacedGlyph(
        char=case.char,
        font_path=oracle.FONT_DIR / oracle.FILENAMES[case.key],
        size_px=case.size_px,
        x=x,
        baseline_y=baseline,
        advance=oracle.advance_px(case.char, case.key, case.size_px),
        ink=(x0 + x, y0 + baseline, x1 + x, y1 + baseline),
    )


def _space(after: PlacedGlyph) -> PlacedGlyph:
    """A blank glyph: no ink, and nothing may be drawn for it."""
    key = "regular"
    return PlacedGlyph(
        " ",
        oracle.FONT_DIR / oracle.FILENAMES[key],
        after.size_px,
        after.x + after.advance,
        after.baseline_y,
        oracle.advance_px(" ", key, after.size_px),
        None,
    )


def _outward(glyph: PlacedGlyph) -> tuple[int, int, int, int]:
    """The ink box rounded outward to pixels, inclusive: (x0, y0, x1, y1)."""
    assert glyph.ink is not None
    x0, y0, x1, y1 = glyph.ink
    return math.floor(x0), math.floor(y0), math.ceil(x1) - 1, math.ceil(y1) - 1


#: Eight glyphs on a 4x2 grid of 40x50 cells: all four faces, a descender, a
#: bowl, diagonals, and three fractional sizes (C-2: "no rounding of size_px").
#: Chosen by searching the fontTools ink boxes for far edges in [.3, .7].
_CASES: tuple[_Case, ...] = (
    _Case("H", "regular", 33.25, 4.5, 6.5),
    _Case("O", "regular", 23.5, 44.5, 6.5),
    _Case("W", "italic", 19.5, 84.5, 6.5),
    _Case("A", "italic", 33.25, 124.5, 6.5),
    _Case("I", "bold", 28.0, 4.5, 56.5),
    _Case("T", "bold", 23.5, 44.5, 56.5),
    _Case("A", "bold_italic", 23.5, 84.5, 56.5),
    _Case("g", "regular", 19.5, 124.5, 56.5),
)


def _glyphs() -> list[PlacedGlyph]:
    return [_glyph(case) for case in _CASES]


def _line(glyphs: Sequence[PlacedGlyph]) -> Line:
    return Line(
        tuple(glyphs),
        sum(g.advance for g in glyphs),
        glyphs[0].x,
        glyphs[0].baseline_y - glyphs[0].size_px,
        glyphs[0].size_px * 1.08,
    )


def _blocks(glyphs: Sequence[PlacedGlyph]) -> list[TypesetBlock]:
    """Two blocks; the first has two lines and a blank glyph inside one of them."""
    g = list(glyphs)
    first = TypesetBlock((_line([g[0], _space(g[0]), g[1]]), _line(g[2:4])), 33.25, False, "H O WA")
    second = TypesetBlock((_line(g[4:8]),), 40.0, False, "ITAg")
    return [first, second]


def _changed(out: NDArray[np.uint8], cleaned: NDArray[np.uint8]) -> NDArray[np.bool_]:
    return np.asarray((out != cleaned).any(axis=-1))


def _bbox(mask: NDArray[np.bool_]) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _everywhere() -> NDArray[np.bool_]:
    return np.ones((H, W), dtype=bool)


# -- preconditions the oracle rests on ------------------------------------------


def test_every_case_has_its_far_ink_edges_well_inside_a_pixel() -> None:
    # The exactness argument in the module docstring needs every edge of every
    # ink box at least 0.3 px from a pixel boundary. If a font update moves an
    # ink box, this fails first and names the case, rather than letting the
    # positional test fail as though bake_page were wrong.
    bad = []
    for case, glyph in zip(_CASES, _glyphs(), strict=True):
        assert glyph.ink is not None
        fracs = [v % 1 for v in glyph.ink]
        if not all(0.3 <= f <= 0.7 for f in fracs):
            bad.append((case, [round(f, 3) for f in fracs]))
    assert bad == []


def test_the_cleaned_page_keeps_every_channel_where_one_level_of_coverage_shows() -> None:
    cleaned = _cleaned()
    assert int(cleaned.min()) >= 128
    assert not np.any(cleaned[..., 0] == cleaned[..., 1])
    assert not np.any(cleaned[..., 1] == cleaned[..., 2])


# -- AC-2, positional half: the ink lands where the glyphs are -----------------


def test_each_glyph_darkens_exactly_the_pixels_its_ink_box_covers() -> None:
    # Deferred condition 3: a composite offset by one pixel in x or y moves every
    # one of these boxes. No tolerance: the comparison is of integer boxes.
    cleaned = _cleaned()
    glyphs = _glyphs()

    out = bake_page(cleaned, _blocks(glyphs), _everywhere())

    changed = _changed(out, cleaned)
    got: dict[str, tuple[int, int, int, int] | None] = {}
    expected: dict[str, tuple[int, int, int, int] | None] = {}
    for case, glyph in zip(_CASES, glyphs, strict=True):
        name = f"{case.char}/{case.key}/{case.size_px}"
        expected[name] = _outward(glyph)
        x0, y0, x1, y1 = expected[name]
        neighbourhood = np.zeros_like(changed)
        neighbourhood[max(0, y0 - 3) : y1 + 4, max(0, x0 - 3) : x1 + 4] = True
        got[name] = _bbox(changed & neighbourhood)
    assert got == expected


def test_nothing_is_drawn_outside_the_glyphs_ink_boxes() -> None:
    # The other direction: no stray ink - not for the blank glyph between H and
    # O, not from a glyph drawn twice at a second position, not a background.
    cleaned = _cleaned()
    glyphs = _glyphs()

    out = bake_page(cleaned, _blocks(glyphs), _everywhere())

    boxes = np.zeros((H, W), dtype=bool)
    for glyph in glyphs:
        x0, y0, x1, y1 = _outward(glyph)
        boxes[y0 : y1 + 1, x0 : x1 + 1] = True
    stray = np.argwhere(_changed(out, cleaned) & ~boxes)
    assert stray.tolist() == []


def test_a_glyph_partly_off_the_page_is_drawn_where_it_lands_without_error() -> None:
    # An overflowed block near the page edge can put ink past the page. Its
    # on-page part is drawn at the right place; nothing raises.
    cleaned = _cleaned()
    off_left = _glyph(_Case("I", "bold", 40.0, -8.5, 30.5))
    off_right_bottom = _glyph(_Case("H", "regular", 33.25, W - 10.5, H - 20.5))
    blocks = [TypesetBlock((_line([off_left]), _line([off_right_bottom])), 40.0, True, "I H")]

    out = bake_page(cleaned, blocks, _everywhere())

    changed = _changed(out, cleaned)
    left_box = _outward(off_left)
    right_box = _outward(off_right_bottom)
    left_half = np.zeros_like(changed)
    left_half[:, : W // 2] = True
    assert _bbox(changed & left_half) == (0, left_box[1], left_box[2], left_box[3])
    assert _bbox(changed & ~left_half) == (right_box[0], right_box[1], W - 1, H - 1)


@pytest.mark.parametrize(
    ("left", "top"),
    [(-60.5, 30.5), (W + 5.5, 30.5), (60.5, -70.5), (60.5, H + 5.5)],
    ids=["left", "right", "above", "below"],
)
def test_a_glyph_wholly_off_the_page_draws_nothing_and_does_not_raise(
    left: float, top: float
) -> None:
    cleaned = _cleaned()
    off = _glyph(_Case("H", "regular", 33.25, left, top))

    out = bake_page(cleaned, [TypesetBlock((_line([off]),), 33.25, True, "H")], _everywhere())

    assert np.array_equal(out, cleaned)


# -- C-2: the composite --------------------------------------------------------


def test_every_pixel_is_black_ink_over_the_cleaned_pixel_at_one_coverage() -> None:
    # For each pixel, some single a in 0..255 must reproduce all three channels
    # as round(dst * (255 - a) / 255). Black ink and one alpha per pixel.
    cleaned = _cleaned()

    out = bake_page(cleaned, _blocks(_glyphs()), _everywhere())

    dst = cleaned.astype(np.float64)
    consistent = np.zeros((H, W), dtype=bool)
    for a in range(256):
        predicted = np.rint(dst * (255 - a) / 255).astype(np.int64)
        consistent |= (predicted == out).all(axis=-1)
    assert np.argwhere(~consistent).tolist() == []


def test_a_pixel_wholly_inside_a_stroke_is_exactly_black() -> None:
    # a == 255 gives out == 0 exactly (C-2). The bold I at 28 px has a stem
    # several pixels wide, so some pixel is fully covered.
    cleaned = _cleaned()

    out = bake_page(cleaned, _blocks(_glyphs()), _everywhere())

    assert bool((out == 0).all(axis=-1).any())


def test_the_ink_is_anti_aliased_not_a_hard_mask() -> None:
    # C-2: coverage is the rasteriser's 8-bit alpha. Some changed pixel must be
    # neither the cleaned value nor black.
    cleaned = _cleaned()

    out = bake_page(cleaned, _blocks(_glyphs()), _everywhere())

    partial = _changed(out, cleaned) & ~(out == 0).all(axis=-1)
    assert int(partial.sum()) > 0


def test_bake_page_returns_a_new_array_and_leaves_the_cleaned_page_untouched() -> None:
    cleaned = _cleaned()
    before = cleaned.copy()

    out = bake_page(cleaned, _blocks(_glyphs()), _everywhere())

    assert out is not cleaned
    assert not np.shares_memory(out, cleaned)
    assert np.array_equal(cleaned, before)
    assert out.shape == (H, W, 3)
    assert out.dtype == np.uint8


@pytest.mark.parametrize(
    "blocks",
    [[], [TypesetBlock((), 42.0, False, "")]],
    ids=["no blocks", "a block with no lines"],
)
def test_nothing_to_draw_returns_the_cleaned_page_exactly_as_a_new_array(
    blocks: list[TypesetBlock],
) -> None:
    cleaned = _cleaned()

    out = bake_page(cleaned, blocks, _everywhere())

    assert out is not cleaned
    assert np.array_equal(out, cleaned)


# -- C-3: the clip -------------------------------------------------------------


def test_an_all_false_clip_leaves_every_pixel_as_cleaned() -> None:
    cleaned = _cleaned()

    out = bake_page(cleaned, _blocks(_glyphs()), np.zeros((H, W), dtype=bool))

    assert np.array_equal(out, cleaned)


def test_ink_past_the_clip_is_dropped_and_ink_inside_it_is_unchanged() -> None:
    # Deferred condition 4: the overflow case. The clip edge runs through the
    # middle of the bold I and the bold T; to its right nothing may change, and
    # to its left the page must be exactly what an unclipped bake gives -
    # a = 0 outside the clip, not "skip any glyph that crosses it".
    cleaned = _cleaned()
    glyphs = _glyphs()
    overflowed = [
        TypesetBlock(block.lines, block.size_px, True, block.text) for block in _blocks(glyphs)
    ]
    i_box, t_box = _outward(glyphs[4]), _outward(glyphs[5])
    cut = (t_box[0] + t_box[2]) // 2
    clip = np.zeros((H, W), dtype=bool)
    clip[:, :cut] = True
    assert i_box[2] < cut, "precondition: the I is wholly inside the clip"
    unclipped = bake_page(cleaned, overflowed, _everywhere())
    assert _changed(unclipped, cleaned)[:, cut:].any(), "precondition: ink lies past the clip"

    out = bake_page(cleaned, overflowed, clip)

    assert np.array_equal(out[~clip], cleaned[~clip])
    assert np.array_equal(out[clip], unclipped[clip])
    t_left = _changed(out, cleaned)[t_box[1] : t_box[3] + 1, t_box[0] : cut]
    assert bool(t_left.any()), "the part of the T inside the clip is still drawn"
