"""MT-123's synthetic bubble page (Contract block 3), and the test's own geometry.

Shared by `test_typeset_interior.py` (AC-1..AC-3, against `bubble_interior`) and
`test_bake_interior.py` (AC-4, against `bake_chapter` / `preview_bake`). Nothing
here imports `mangatl.typeset.interior` or `mangatl.pipeline.bake`, so every
helper runs in a plain interpreter while the module under test does not exist -
which is how RED measured the numbers recorded in the story's handoff.

**The page.** 640 x 560 px. One ellipse centred at (320, 280), 300 x 240 px on
its outer edge, drawn as a 4 px outline at grey 0 around a 255 interior: the
outline is the outer ellipse (semi-axes 150 x 120) minus the inner one (146 x
116), computed analytically rather than with `cv2.ellipse`, so "the interior"
and "the outline" are exact sets the test owns. The region polygon is the
60 x 200 rectangle centred in it; the mask strokes are two rects inside it, as
`_bake_world.REGION_GEOMETRY` does.

**The texture is `_bake_world.texture` clipped to 199 per channel (Contract
block 3, amended in RED).** AC-1 needs a page that is non-light (grey < 200)
everywhere outside the bubble. Block 3 said `_bake_world.texture` already is;
measured, it is not: its luma (PIL `convert("L")`, production's `_grey`) runs
28..225, with 2.3-2.7% of pixels at or above 200 at every size and salt tried.
Clipping each channel at 199 bounds the luma at 199 and keeps the texture's
pixel-to-pixel variation. `the_synthetic_page_is_light_only_inside_the_bubble`
asserts the property on the page itself, once.

**The open bubble (AC-2)** breaks the outline with a 60 px gap on the right -
the rows `|y - 280| < 30` - and paints a 255 band through it from the ellipse to
the page's right edge. The ray cap is 200 px (CAP_RATIO 1.0 x max(60, 200)) and
the page edge is 319 px from the centre on that side, so a correct star stops
short of it while a plain flood reaches it.

**The window is spelled out** (`window`, Contract block 1 rule 2) from the
pinned `CAP_RATIO = 1.0`, never read from the module, so an implementation with
a different cap disagrees with it rather than agreeing by construction.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import _bake_world as world
import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

#: Contract block 1, written out. Not imported: the test must disagree with an
#: implementation that changed one.
PINNED_LIGHT_GREY = 200
PINNED_DARK_GREY = 120
PINNED_CAP_RATIO = 1.0
PINNED_RAY_COUNT = 72

PAGE_W, PAGE_H = 640, 560
CENTRE_X, CENTRE_Y = 320, 280
OUTER_A, OUTER_B = 150.0, 120.0  # 300 x 240 on the outer edge
OUTLINE_PX = 4
INNER_A, INNER_B = OUTER_A - OUTLINE_PX, OUTER_B - OUTLINE_PX
GAP_PX = 60

Ring = tuple[tuple[int, int], ...]


def ring(x0: int, y0: int, x1: int, y1: int) -> Ring:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


#: The 60 x 200 region polygon, centred on the ellipse.
POLYGON: Ring = ring(CENTRE_X - 30, CENTRE_Y - 100, CENTRE_X + 30, CENTRE_Y + 100)

#: Mask strokes strictly inside the polygon (two "columns" of Japanese).
STROKES: tuple[world.Rect, ...] = (
    (CENTRE_X - 20, CENTRE_Y - 80, CENTRE_X - 14, CENTRE_Y + 80),
    (CENTRE_X + 14, CENTRE_Y - 80, CENTRE_X + 20, CENTRE_Y + 80),
)


@dataclass(frozen=True)
class BubblePage:
    """One synthetic cleaned page and the sets the test owns on it."""

    rgb: NDArray[np.uint8]  # (H, W, 3)
    grey: NDArray[np.uint8]  # (H, W), PIL convert("L") of rgb
    interior: NDArray[np.bool_]  # the ellipse's 255 interior
    outline: NDArray[np.bool_]  # the drawn outline pixels (grey 0)
    band: NDArray[np.bool_]  # the 255 band through the gap (empty when closed)


def _ellipse(a: float, b: float) -> NDArray[np.bool_]:
    y, x = np.mgrid[0:PAGE_H, 0:PAGE_W]
    return np.asarray(((x - CENTRE_X) / a) ** 2 + ((y - CENTRE_Y) / b) ** 2 <= 1.0)


def grey_of(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Production's grey (Contract block 2, `_grey`): PIL `convert("L")`."""
    return np.asarray(Image.fromarray(rgb, "RGB").convert("L"))


def dark_texture(width: int = PAGE_W, height: int = PAGE_H) -> NDArray[np.uint8]:
    """`_bake_world.texture`, clipped to 199 per channel: luma < 200 everywhere."""
    return np.minimum(world.texture(width, height), 199).astype(np.uint8)


def bubble_page(*, open_gap: bool = False) -> BubblePage:
    """AC-1's closed bubble, or with `open_gap` AC-2's open one."""
    inner = _ellipse(INNER_A, INNER_B)
    outline = _ellipse(OUTER_A, OUTER_B) & ~inner
    rgb = dark_texture()
    rgb[inner] = 255
    rgb[outline] = 0
    band = np.zeros((PAGE_H, PAGE_W), dtype=bool)
    if open_gap:
        y, x = np.mgrid[0:PAGE_H, 0:PAGE_W]
        band = np.asarray((np.abs(y - CENTRE_Y) < GAP_PX // 2) & (x >= CENTRE_X)) & ~inner
        rgb[band] = 255
        outline = outline & ~band
    return BubblePage(rgb, grey_of(rgb), inner, outline, band)


def fill(polygon: Sequence[tuple[int, int]], shape: tuple[int, int]) -> NDArray[np.bool_]:
    """`cv2.fillPoly` of a ring, as a boolean mask of `shape` (H, W)."""
    filled = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(filled, [np.array(polygon, dtype=np.int32)], 1)
    return filled.astype(bool)


def window(polygon: Sequence[tuple[int, int]], shape: tuple[int, int]) -> tuple[int, int, int, int]:
    """Contract block 1 rule 2, inclusive pixel bounds `(x0, y0, x1, y1)`: the
    polygon's bbox grown by `CAP_RATIO x max(w, h)` per side, clipped to the page."""
    height, width = shape
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    grow = PINNED_CAP_RATIO * max(x1 - x0, y1 - y0)
    return (
        max(0, math.floor(x0 - grow)),
        max(0, math.floor(y0 - grow)),
        min(width - 1, math.ceil(x1 + grow)),
        min(height - 1, math.ceil(y1 + grow)),
    )


def plain_flood(grey: NDArray[np.uint8], polygon: Sequence[tuple[int, int]]) -> NDArray[np.bool_]:
    """The test's own oracle (Contract block 6, unclipped): the 4-connected
    component of `grey >= 200` holding the most light pixels of the polygon's
    fill. Empty when the polygon holds no light pixel."""
    light = grey >= PINNED_LIGHT_GREY
    seed = light & fill(polygon, grey.shape)
    if not seed.any():
        return np.zeros_like(light)
    count, labels = cv2.connectedComponents(light.astype(np.uint8), connectivity=4)
    votes = np.bincount(labels[seed], minlength=count)
    votes[0] = 0  # label 0 is the non-light background
    return np.asarray(labels == int(votes.argmax()))


def touches_page_edge(mask: NDArray[np.bool_]) -> bool:
    return bool(mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any())
