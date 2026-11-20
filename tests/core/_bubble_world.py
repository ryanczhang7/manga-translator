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


# -- MT-154: a closed balloon larger than the window ---------------------------------
#
# MT-154 Contract C-4. A development-scan-sized page (1414 x 2000) holding one tall
# closed balloon, 360 x 770 on its outline's outer edge, and a 98 x 185 region at
# its top: the window (bbox grown by 1.0 x 185 per side) ends at y = 1030, far
# above the balloon's bottom at y = 1385, so the flood is NOT strictly inside it
# and today's clause 5a cannot accept it. Three controls vary that page so that
# exactly one clause of the new 5b rejects each; their tests assert which, with
# the arithmetic below and never with the module's.

#: MT-154 Contract C-2, written out. Not imported: the test must disagree with an
#: implementation that changed one.
PINNED_INTERIOR_MIN_SOLIDITY = 0.96
PINNED_INTERIOR_MAX_PAGE_FRACTION = 0.25

TALL_W, TALL_H = 1414, 2000
TALL_SHAPE = (TALL_H, TALL_W)
TALL_CX, TALL_CY = 707, 1000
TALL_OUTER_A, TALL_OUTER_B = 180.0, 385.0  # 360 x 770 on the outer edge
TALL_INNER_A, TALL_INNER_B = TALL_OUTER_A - OUTLINE_PX, TALL_OUTER_B - OUTLINE_PX
TALL_REGION_W, TALL_REGION_H = 98, 185
TALL_REGION_TOP = 660  # 41 px under the interior's top (y = 619)

#: AC-3: the balloon's centre moved right until the page's right edge cuts it
#: (the outer edge would end at x = 1494, the page at x = 1413).
EDGE_CUT_CX = TALL_W - 100

#: AC-4: a closed white panel, half-open `(x0, y0, x1, y1)` interior, 1000 x 1000 =
#: 0.354 of the page, with a 4 px outline and the AC-1 region inside it.
PANEL_INTERIOR: world.Rect = (207, 600, 1207, 1600)

#: AC-5: the balloon's outline opened on the right over rows `|y - 1200| < 30`, a
#: white band through the gap, and a white rectangle of panel art beside it.
ART_GAP_Y = 1200
ART_RECT: world.Rect = (920, 1100, 1300, 1700)


def tall_polygon(centre_x: int = TALL_CX) -> Ring:
    """The 98 x 185 region at the top of the tall balloon centred on `centre_x`."""
    x0 = centre_x - TALL_REGION_W // 2
    return ring(x0, TALL_REGION_TOP, x0 + TALL_REGION_W, TALL_REGION_TOP + TALL_REGION_H)


def _tall_ellipse(centre_x: int, a: float, b: float) -> NDArray[np.bool_]:
    y, x = np.mgrid[0:TALL_H, 0:TALL_W]
    return np.asarray(((x - centre_x) / a) ** 2 + ((y - TALL_CY) / b) ** 2 <= 1.0)


def tall_balloon_page(*, centre_x: int = TALL_CX, open_into_art: bool = False) -> BubblePage:
    """AC-1's tall closed balloon (centred on `centre_x`; `EDGE_CUT_CX` is AC-3's),
    or with `open_into_art` AC-5's, opened into a white rectangle of panel art.
    `interior` is the balloon's own white, clipped to the page; `band` is the
    light that is not the balloon (the gap's band and the art)."""
    inner = _tall_ellipse(centre_x, TALL_INNER_A, TALL_INNER_B)
    outline = _tall_ellipse(centre_x, TALL_OUTER_A, TALL_OUTER_B) & ~inner
    rgb = dark_texture(TALL_W, TALL_H)
    rgb[inner] = 255
    rgb[outline] = 0
    band = np.zeros(TALL_SHAPE, dtype=bool)
    if open_into_art:
        y, x = np.mgrid[0:TALL_H, 0:TALL_W]
        ax0, ay0, ax1, ay1 = ART_RECT
        gap = (np.abs(y - ART_GAP_Y) < GAP_PX // 2) & (x >= centre_x) & (x < ax0)
        art = (x >= ax0) & (x < ax1) & (y >= ay0) & (y < ay1)
        band = np.asarray(gap | art) & ~inner
        rgb[band] = 255
        outline = outline & ~band
    return BubblePage(rgb, grey_of(rgb), inner, outline, band)


def white_panel_page() -> BubblePage:
    """AC-4's closed white panel, `PANEL_INTERIOR` inside a 4 px outline."""
    x0, y0, x1, y1 = PANEL_INTERIOR
    inner = np.zeros(TALL_SHAPE, dtype=bool)
    inner[y0:y1, x0:x1] = True
    outer = np.zeros(TALL_SHAPE, dtype=bool)
    outer[y0 - OUTLINE_PX : y1 + OUTLINE_PX, x0 - OUTLINE_PX : x1 + OUTLINE_PX] = True
    outline = outer & ~inner
    rgb = dark_texture(TALL_W, TALL_H)
    rgb[inner] = 255
    rgb[outline] = 0
    return BubblePage(rgb, grey_of(rgb), inner, outline, np.zeros(TALL_SHAPE, dtype=bool))


def page_fraction(mask: NDArray[np.bool_]) -> float:
    """C-1 clause 5b.2's ratio: the mask's pixel count over the page's."""
    return float(mask.sum()) / mask.size


def solidity(mask: NDArray[np.bool_]) -> float:
    """C-1 clause 5b.3's ratio, computed here: pixel count over the area of the
    convex hull of the mask's largest external contour, the hull floored at 1."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outer = max(contours, key=cv2.contourArea)
    return float(mask.sum()) / max(1.0, float(cv2.contourArea(cv2.convexHull(outer))))


def strictly_inside(mask: NDArray[np.bool_], bounds: tuple[int, int, int, int]) -> bool:
    """Clause 5a: the mask's bbox strictly inside the inclusive window `bounds`."""
    x0, y0, x1, y1 = bounds
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    return bool(x0 < cols[0] and cols[-1] < x1 and y0 < rows[0] and rows[-1] < y1)


def centroid(mask: NDArray[np.bool_]) -> tuple[float, float]:
    """The mean `(x, y)` of the mask's pixels."""
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


# -- MT-154 R-1: the other three page edges, and a zero-area hull --------------------
#
# AC-3's fixture cuts the balloon with the right page edge only, so clause 5b.1's
# top, bottom and left checks went untested (diff review round 1, finding 2). These
# pages cut the same closed balloon with each other edge by the same 81 px: the
# outer edge would run past the page by 81 px, exactly as `EDGE_CUT_CX` does on the
# right (1494 - 1413). Left is the right-edge page mirrored, which for the analytic
# ellipse is `tall_balloon_page` centred on `TALL_W - 1 - EDGE_CUT_CX`; top and
# bottom move the centre vertically instead, the region 41 px under the page edge
# that cuts the balloon (as `TALL_REGION_TOP` is 41 px under the interior's top),
# and bottom is top mirrored about the page's middle row.

EDGE_OVERHANG_PX = (EDGE_CUT_CX + int(TALL_OUTER_A)) - (TALL_W - 1)  # 81
#: The balloon centre for a balloon cut by the top edge, and its mirror.
TOP_CUT_CY = int(TALL_OUTER_B) - EDGE_OVERHANG_PX  # 304: outer edge from y = -81
BOTTOM_CUT_CY = TALL_H - 1 - TOP_CUT_CY  # 1695: outer edge to y = 2080
EDGE_REGION_INSET = 41  # px between the cutting page edge and the region


def _ellipse_at(cx: int, cy: int, a: float, b: float) -> NDArray[np.bool_]:
    y, x = np.mgrid[0:TALL_H, 0:TALL_W]
    return np.asarray(((x - cx) / a) ** 2 + ((y - cy) / b) ** 2 <= 1.0)


def _closed_balloon_at(cx: int, cy: int) -> BubblePage:
    inner = _ellipse_at(cx, cy, TALL_INNER_A, TALL_INNER_B)
    outline = _ellipse_at(cx, cy, TALL_OUTER_A, TALL_OUTER_B) & ~inner
    rgb = dark_texture(TALL_W, TALL_H)
    rgb[inner] = 255
    rgb[outline] = 0
    return BubblePage(rgb, grey_of(rgb), inner, outline, np.zeros(TALL_SHAPE, dtype=bool))


def edge_cut_balloon(edge: str) -> tuple[BubblePage, Ring]:
    """AC-3's balloon cut by the page's `edge` ("top", "bottom" or "left") instead
    of its right, with the 98 x 185 region inside it: `(page, polygon)`."""
    x0 = TALL_CX - TALL_REGION_W // 2
    if edge == "left":
        centre_x = TALL_W - 1 - EDGE_CUT_CX
        return tall_balloon_page(centre_x=centre_x), tall_polygon(centre_x)
    if edge == "top":
        y0 = EDGE_REGION_INSET
        page = _closed_balloon_at(TALL_CX, TOP_CUT_CY)
    elif edge == "bottom":
        y0 = TALL_H - 1 - EDGE_REGION_INSET - TALL_REGION_H
        page = _closed_balloon_at(TALL_CX, BOTTOM_CUT_CY)
    else:
        raise ValueError(f"no edge-cut balloon for edge {edge!r}")
    return page, ring(x0, y0, x0 + TALL_REGION_W, y0 + TALL_REGION_H)


def edges_touched(mask: NDArray[np.bool_]) -> set[str]:
    """Which page edges the mask has a pixel on, by name."""
    rows = {"top": mask[0, :], "bottom": mask[-1, :], "left": mask[:, 0], "right": mask[:, -1]}
    return {name for name, line in rows.items() if bool(line.any())}


#: Diff review round 1, finding 3: a 1 px tall white strip, 360 px long, on row
#: `STRIP_Y` of the dark tall page, under a 15 x 20 region. Its external contour
#: is a line, so its convex hull's area is 0.0 and 5b.3's ratio needs the floor.
STRIP_Y = TALL_CY
STRIP_X0, STRIP_LEN = TALL_CX - 180, 360  # x 527..886, off every edge
STRIP_POLYGON: Ring = ring(TALL_CX - 7, STRIP_Y - 10, TALL_CX + 8, STRIP_Y + 10)


def strip_page() -> BubblePage:
    """The 1 px strip page; `interior` is the strip, `outline` empty."""
    strip = np.zeros(TALL_SHAPE, dtype=bool)
    strip[STRIP_Y, STRIP_X0 : STRIP_X0 + STRIP_LEN] = True
    rgb = dark_texture(TALL_W, TALL_H)
    rgb[strip] = 255
    empty = np.zeros(TALL_SHAPE, dtype=bool)
    return BubblePage(rgb, grey_of(rgb), strip, empty, empty)
