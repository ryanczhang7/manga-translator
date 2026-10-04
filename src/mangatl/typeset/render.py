"""Drawing typeset English onto a cleaned page (MT-021 C-1, C-2, C-3).

Every `PlacedGlyph` is drawn alone, in its own face at its own size, with its
left-baseline at exactly the `(x, baseline_y)` that `fit` emitted - "what is
measured is what is drawn" (`measure.py`). Ink is black; coverage is an 8-bit
alpha; the composite is alpha-over, `out = round(dst * (255 - a) / 255)`,
exact at `a == 0` and `a == 255`.

**Supersampled, not drawn at the glyph's own size.** Measured in MT-021 RED and
again in GREEN: Pillow's `ImageDraw.text(..., anchor="ls")` at the glyph's own
size misses the fontTools ink box by a pixel on a large share of glyphs (hinting
and integer placement), so C-2's suggested call does not hit the pinned
position. Drawn at `SUPERSAMPLE` times the size and position and reduced by a
box mean over each `SUPERSAMPLE x SUPERSAMPLE` block, the error is a fraction of
a pixel and every position the tests pin is hit.

`clip` is the page's bake area (C-3): coverage is zeroed wherever it is
`False`, so an overflowed block cannot reach the art.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from mangatl.typeset.fit import PlacedGlyph, TypesetBlock

__all__ = ["SUPERSAMPLE", "bake_page"]

#: Rasterisation factor. RED measured 4, 8 and 16 all hitting every pinned
#: position; 8 keeps the per-glyph layer small.
SUPERSAMPLE: int = 8

#: Pixels of slack around Pillow's own bbox, so no anti-aliased fringe is cut.
_MARGIN_PX: int = 1


@lru_cache(maxsize=64)
def _font(path: Path, size_px: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size_px * SUPERSAMPLE)


def bake_page(
    cleaned: NDArray[np.uint8],
    blocks: Sequence[TypesetBlock],
    clip: NDArray[np.bool_],
) -> NDArray[np.uint8]:
    """`cleaned` with every block's glyphs composited in black, clipped to `clip`.

    Returns a new `(H, W, 3)` uint8 array; `cleaned` is never written to.
    Blocks are composited in the order given, each over the previous result.
    """
    out = cleaned.astype(np.int64)
    for block in blocks:
        for line in block.lines:
            for glyph in line.glyphs:
                _composite(out, glyph, clip)
    return out.astype(np.uint8)


def _composite(out: NDArray[np.int64], glyph: PlacedGlyph, clip: NDArray[np.bool_]) -> None:
    """Alpha-over one glyph's black ink onto `out`, in place, within the page and clip."""
    s = SUPERSAMPLE
    font = _font(glyph.font_path, glyph.size_px)
    x, y = glyph.x * s, glyph.baseline_y * s
    left, top, right, bottom = font.getbbox(glyph.char, anchor="ls")
    px0 = math.floor((x + left) / s) - _MARGIN_PX
    py0 = math.floor((y + top) / s) - _MARGIN_PX
    px1 = math.ceil((x + right) / s) + _MARGIN_PX
    py1 = math.ceil((y + bottom) / s) + _MARGIN_PX

    layer = Image.new("L", ((px1 - px0) * s, (py1 - py0) * s), 0)
    ImageDraw.Draw(layer).text(
        (x - px0 * s, y - py0 * s), glyph.char, fill=255, font=font, anchor="ls"
    )
    sums = np.asarray(layer, dtype=np.int64).reshape(py1 - py0, s, px1 - px0, s).sum(axis=(1, 3))
    alpha = (sums + s * s // 2) // (s * s)  # box mean, rounded: 0..255

    # The part of the glyph's box that is on the page; empty, never negative.
    height, width = clip.shape
    x0, y0 = min(max(px0, 0), width), min(max(py0, 0), height)
    x1, y1 = max(min(px1, width), x0), max(min(py1, height), y0)
    a = alpha[y0 - py0 : y1 - py0, x0 - px0 : x1 - px0] * clip[y0:y1, x0:x1]
    dst = out[y0:y1, x0:x1]
    # round(dst * (255 - a) / 255) in integers. No ties: n / 255 == k + 0.5 would
    # need 2n == 255 * (2k + 1), an even number equal to an odd one.
    out[y0:y1, x0:x1] = (dst * (255 - a[..., None]) + 127) // 255
