"""Where ordinal badges go so that no two overlap (MT-051, `components.md` §4.2).

Qt-free on purpose: the rule is geometry, and its oracle is a hand computation.
Everything is in ZOOMED-SCENE units (page px x zoom, one screen pixel each),
because the badge is a constant 18 px on screen and so collides on screen.

The rule, as the story's Contract numbers it:

1. A closed ring's repeated first vertex is dropped and zero-length edges are
   skipped. Screen-clockwise (y down) is the traversal whose shoelace sum is
   positive; a ring with a negative sum is walked in reverse.
2. Candidate 0 is the nominal position, MT-016's: `(R + gap + size/2,
   T - gap - size/2)` about the bounding rect's top-right corner `(R, T)`.
3. Two badges intersect when their centres are strictly less than `size` apart.
4. Candidate k >= 1 (while k * size/2 < perimeter) is the outline point k * size/2
   of arc length clockwise from the outline point nearest `(R, T)`, pushed
   `gap + size/2` out along the outward normal `(dy, -dx)/|d|` of the edge that
   point lies on - at a vertex, the edge being entered.
5. The nominal if free, else the first free candidate, else the area centroid.
   A zero-area ring (shoelace sum exactly 0 on the page-px input) whose nominal is
   taken skips the walk and goes to its bounding-rect centre (Amendment 1).
   Every badge, the centroid one included, counts as placed for later ordinals.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

__all__ = ["BadgePlacement", "Placement", "Point", "area_centroid", "place_badges"]

Point = tuple[float, float]


class Placement(Enum):
    """How a badge came to be where it is."""

    NOMINAL = "nominal"
    SLID = "slid"
    CENTROID = "centroid"


@dataclass(frozen=True)
class BadgePlacement:
    """A badge's centre, in zoomed-scene units, and which rule put it there."""

    centre: Point
    placement: Placement


def _ring(polygon: Iterable[Sequence[float]]) -> list[Point]:
    """The polygon's vertices as floats, with no repeated consecutive vertex."""
    ring: list[Point] = []
    for x, y in polygon:
        point = (float(x), float(y))
        if not ring or point != ring[-1]:
            ring.append(point)
    while len(ring) > 1 and ring[-1] == ring[0]:
        ring.pop()
    return ring


def _twice_signed_area(ring: Sequence[Point]) -> float:
    """The shoelace sum; positive for a screen-clockwise ring (y down)."""
    return sum(
        x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, [*ring[1:], ring[0]], strict=True)
    )


def area_centroid(polygon: Sequence[Point]) -> Point:
    """The polygon's area centroid (shoelace), in the units of its input."""
    ring = _ring(polygon)
    twice_area = _twice_signed_area(ring)
    cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, [*ring[1:], ring[0]], strict=True):
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    return (cx / (3.0 * twice_area), cy / (3.0 * twice_area))


def _clockwise(ring: list[Point]) -> list[Point]:
    """`ring` in screen-clockwise order (Contract rule 1)."""
    if _twice_signed_area(ring) < 0:
        return ring[::-1]
    return ring


def _is_free(centre: Point, placed: Sequence[Point], size: float) -> bool:
    """True when `centre` intersects no placed badge; touching is free (rule 3)."""
    return all(math.dist(centre, other) >= size for other in placed)


def _walk(ring: Sequence[Point], corner: Point, size: float, gap: float) -> list[Point]:
    """Candidates 1, 2, ... of Contract rule 4, in order, for a clockwise ring."""
    edges: list[tuple[Point, float, float, float]] = []  # (start, ux, uy, length)
    for (x0, y0), (x1, y1) in zip(ring, [*ring[1:], ring[0]], strict=True):
        length = math.hypot(x1 - x0, y1 - y0)
        edges.append(((x0, y0), (x1 - x0) / length, (y1 - y0) / length, length))
    starts = [0.0]
    for *_, length in edges:
        starts.append(starts[-1] + length)
    perimeter = starts[-1]

    # The start point: the outline point nearest the corner, first found wins ties.
    best_distance = math.inf
    start_arc = 0.0
    for index, ((x0, y0), ux, uy, length) in enumerate(edges):
        t = min(max((corner[0] - x0) * ux + (corner[1] - y0) * uy, 0.0), length)
        distance = math.dist(corner, (x0 + t * ux, y0 + t * uy))
        if distance < best_distance:
            best_distance, start_arc = distance, starts[index] + t

    # An arc position within `eps` of a vertex is that vertex, on the edge entered.
    eps = 1e-9 * max(1.0, perimeter)
    step = size / 2
    offset = gap + size / 2
    candidates: list[Point] = []
    k = 1
    while k * step < perimeter:
        arc = math.fmod(start_arc + k * step, perimeter)
        if arc > perimeter - eps:
            arc = 0.0
        index = max(i for i in range(len(edges)) if starts[i] - eps <= arc)
        (x0, y0), ux, uy, _ = edges[index]
        t = max(arc - starts[index], 0.0)
        candidates.append((x0 + t * ux + offset * uy, y0 + t * uy - offset * ux))
        k += 1
    return candidates


def place_badges(
    regions: Iterable[tuple[int, Sequence[Point]]],
    *,
    zoom: float,
    size: float,
    gap: float,
) -> dict[int, BadgePlacement]:
    """Every region's badge, keyed by region_id, placed in ordinal order."""
    result: dict[int, BadgePlacement] = {}
    placed: list[Point] = []
    for region_id, polygon in sorted(regions, key=lambda item: item[0]):
        ring = _clockwise(_ring((x * zoom, y * zoom) for x, y in polygon))
        right = max(x for x, _ in ring)
        top = min(y for _, y in ring)
        nominal = (right + gap + size / 2, top - gap - size / 2)
        if _is_free(nominal, placed, size):
            badge = BadgePlacement(nominal, Placement.NOMINAL)
        elif _twice_signed_area(_ring(polygon)) == 0:
            # Zero area, judged on the page-px input (Amendment 1): no clockwise, no
            # area centroid, so no walk - the bounding-rect centre.
            left, bottom = min(x for x, _ in ring), max(y for _, y in ring)
            badge = BadgePlacement(((left + right) / 2, (top + bottom) / 2), Placement.CENTROID)
        else:
            slid = next(
                (c for c in _walk(ring, (right, top), size, gap) if _is_free(c, placed, size)),
                None,
            )
            if slid is not None:
                badge = BadgePlacement(slid, Placement.SLID)
            else:
                badge = BadgePlacement(area_centroid(ring), Placement.CENTROID)
        result[region_id] = badge
        placed.append(badge.centre)
    return result
