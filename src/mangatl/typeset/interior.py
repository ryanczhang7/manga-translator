"""The bubble's interior, found on the cleaned page (MT-123 Contract block 1).

The region polygon is the detector's text region - the outer contour of the
Japanese column - never the bubble, and nothing stored knows where the bubble
is. On the cleaned page the Japanese is erased and the interior is flat white
inside a dark outline, so it can be found there:

1. `kind == "box"`: the polygon, unchanged - text on art stays where the
   detector put it.
2. The *window* is the polygon's bounding box grown by `CAP_RATIO x max(w, h)`
   on every side, clipped to the page. Nothing returned leaves it.
3. The *flood*: the 4-connected component of light pixels holding the most
   light pixels of the polygon's fill. None under the polygon: the polygon.
4. A component smaller than the polygon's fill is noise, a dark background or a
   flat-white erase mask: the polygon.
5. A component strictly inside the window (so off the page edge, the window
   being clipped to the page) is the interior, united with the polygon fill.
6. Otherwise the flood leaked through an open outline, and the interior is a
   *star*: `RAY_COUNT` rays from the bbox centre, each stopping before a dark
   pixel (the dark mask closed once by a 3 x 3 kernel), the page edge or the
   cap; the star's fill minus that dark mask, united with the polygon fill.
7. The interior's outer contour, as a closed ring of Python `int`s.

The union with the polygon fill in 5 and 6 is what keeps the interior a
superset of the polygon, so the bake area that is clipped to it only grows.
Imports `numpy` and `cv2` only from outside this package - nothing of `detect`
or `clean` (`architecture.md` §3).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

__all__ = ["CAP_RATIO", "DARK_GREY", "LIGHT_GREY", "RAY_COUNT", "Ring", "bubble_interior"]

# MT-069: survive a lost thread-pool completion port - see `mangatl.clean.mask`.
cv2.setNumThreads(-1)

LIGHT_GREY: int = 200  # a cleaned-page pixel at or above this is bubble white
DARK_GREY: int = 120  # a pixel at or below this is outline ink
CAP_RATIO: float = 1.0  # the window grows the polygon's bbox by this x max(w, h) per side
RAY_COUNT: int = 72  # rays of the fallback star, at equal angles from the bbox centre

#: Closed: the last vertex repeats the first. `RawRegion.polygon`'s conventions.
Ring = tuple[tuple[int, int], ...]

_CLOSE_KERNEL = np.ones((3, 3), dtype=np.uint8)


def bubble_interior(
    cleaned: NDArray[np.uint8],
    polygon: Sequence[tuple[int, int]],
    kind: Literal["bubble", "box"],
) -> Ring:
    """The ring to fit English into: the bubble's interior around `polygon`
    on the `(H, W)` grey `cleaned` page, or `polygon` itself where there is no
    bubble to find (module docstring, rules 1-7)."""
    if kind == "box":
        return tuple(polygon)
    height, width = cleaned.shape
    fill = _fill(polygon, (height, width))
    light = cleaned >= LIGHT_GREY
    seed = light & fill
    if not seed.any():
        return tuple(polygon)
    count, found = cv2.connectedComponents(light.astype(np.uint8), connectivity=4)
    labels = np.asarray(found, dtype=np.int32)
    # Every seed pixel is light, so none carries the background label 0.
    votes = np.bincount(labels[seed], minlength=count)
    component: NDArray[np.bool_] = np.asarray(labels == int(votes.argmax()))
    if int(component.sum()) < int(fill.sum()):
        return tuple(polygon)

    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    reach = CAP_RATIO * max(x1 - x0, y1 - y0)
    wx0, wy0 = max(0, math.floor(x0 - reach)), max(0, math.floor(y0 - reach))
    wx1 = min(width - 1, math.ceil(x1 + reach))
    wy1 = min(height - 1, math.ceil(y1 + reach))

    rows = np.flatnonzero(component.any(axis=1))
    cols = np.flatnonzero(component.any(axis=0))
    # The window is clipped to the page, so strictly inside it is off the edge.
    if wx0 < cols[0] and cols[-1] < wx1 and wy0 < rows[0] and rows[-1] < wy1:
        interior = component | fill
    else:
        dark = cv2.morphologyEx(
            (cleaned <= DARK_GREY).astype(np.uint8), cv2.MORPH_CLOSE, _CLOSE_KERNEL
        ).astype(bool)
        star = _star(dark, ((x0 + x1) / 2, (y0 + y1) / 2), reach)
        interior = (_fill(star, (height, width)) & ~dark) | fill
    return _outer_ring(interior)


def _fill(polygon: Sequence[tuple[int, int]], shape: tuple[int, int]) -> NDArray[np.bool_]:
    filled = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(filled, [np.array(polygon, dtype=np.int32)], 1)
    return filled.astype(bool)


def _star(
    dark: NDArray[np.bool_], centre: tuple[float, float], cap: float
) -> list[tuple[int, int]]:
    """One vertex per ray: the last on-page, not-dark pixel before the ray meets
    a dark pixel, leaves the page, or reaches `cap` px from `centre`."""
    height, width = dark.shape
    cx, cy = centre
    vertices: list[tuple[int, int]] = []
    for k in range(RAY_COUNT):
        angle = 2 * math.pi * k / RAY_COUNT
        dx, dy = math.cos(angle), math.sin(angle)
        last = (round(cx), round(cy))
        for step in range(1, math.floor(cap) + 1):
            x, y = round(cx + step * dx), round(cy + step * dy)
            if not (0 <= x < width and 0 <= y < height) or dark[y, x]:
                break
            last = (x, y)
        vertices.append(last)
    return vertices


def _outer_ring(interior: NDArray[np.bool_]) -> Ring:
    contours, _ = cv2.findContours(
        interior.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    outer = max(contours, key=cv2.contourArea)
    points = [(int(x), int(y)) for x, y in outer.reshape(-1, 2)]
    return (*points, points[0])
