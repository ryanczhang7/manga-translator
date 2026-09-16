"""Reading order: right to left, top to bottom (MT-009).

Japanese reads right to left, so the region with the **greatest** x-centre comes
first; y increases downward with the page's top-left at `(0, 0)`, so the smaller
y-top comes first. Getting the x direction backwards produces a chapter that
reads perfectly and is entirely wrong, and no type checker notices - hence the
direction is stated here, in `docs/backlog/stories/MT-009.md` `## Contract`, and
in the tests, rather than inferred from a comparator.

**How a page is ordered.** Regions are grouped into horizontal *bands*, the
bands are emitted top to bottom, and each band is read right to left. Two
regions share a band when their vertical extents overlap by at least
`BAND_OVERLAP_FRACTION` of the **shorter** extent, and banding is **transitive**:
A-B and B-C chained put A, B and C in one band even when A and C do not overlap
at all. Pairwise banding instead of transitive banding makes the result depend on
the order the regions arrived in, which MT-009 AC-5's determinism property
catches.

**Why the fraction is of the shorter extent.** A one-word bubble beside a long
column should band with it when it sits inside that column's span. Measured
against the taller extent it would not, and the two would be read top to bottom
instead of right to left.

**No panel segmentation.** `architecture.md` D10: v1 orders by geometry alone and
accepts being wrong on layouts that need panel borders to read - the two
`unusual` pages under `fixtures/reading-order/` record exactly that loss.

**No text.** MT-009 `## Out of scope`: what a region *says* never decides where
it goes. This module reads `polygon` and nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence

from mangatl.domain.region import RawRegion

__all__ = ["BAND_OVERLAP_FRACTION", "order_regions", "sort_regions"]

#: The fraction of the **shorter** region's vertical extent that must overlap the
#: other's for the two to count as one band. The comparison is `>=`: at exactly
#: this fraction, the two band (MT-009 C-A1).
#:
#: SETTLED IN GREEN FROM THE FIXTURES, 2026-09-16. Measured over all 78 region
#: pairs of `fixtures/reading-order/*.json`, split by the hand annotation's
#: art-derived grouping (not by any ordering):
#:
#: * every pair the art puts in **different** groups on a `conventional` page has
#:   **no vertical overlap at all** (fraction <= 0), so no positive value of this
#:   constant merges two tiers that should stay apart;
#: * every pair the art puts in the **same** group overlaps by **>= 0.527** of the
#:   shorter extent - 0.527, 0.543, 0.634, 0.680, 0.854, 0.915, 0.919, 0.941,
#:   0.966, 0.990 and nine pairs at 1.0 - with a single outlier at **0.084**
#:   (011's splash pair, 16 px of a 190 px column) which no usable value can band
#:   and which reads correctly on y alone anyway.
#:
#: So the admissible interval measured on real pages is `(0.084, 0.527)`, and 0.3
#: is its midpoint to the nearest exactly-representable two-decimal value: 0.216
#: above the "these merely clip" datum and 0.227 below the tightest pair that must
#: band. It is also 0.38 below the 0.679 at which page 015's top pair stops
#: banding and AC-6's left-to-right control stops discriminating.
BAND_OVERLAP_FRACTION = 0.3


def _vertical_extent(region: RawRegion) -> tuple[int, int]:
    """`[min y, max y]` over the polygon's vertices (MT-009 C-A2).

    The ring is closed, so its repeated last vertex cannot change either bound.
    """
    ys = [y for _, y in region.polygon]
    return min(ys), max(ys)


def _x_centre(region: RawRegion) -> float:
    """The centre of the polygon's bounding box in x.

    The bounding-box centre rather than the mean of the vertices: the two differ
    on a non-convex polygon, and the bounding box is what "how far right this
    region sits" means for a text block.
    """
    xs = [x for x, _ in region.polygon]
    return (min(xs) + max(xs)) / 2


def _bands_together(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Do these two vertical extents belong to the same band?

    The overlap length is `min(maxA, maxB) - max(minA, minB)`, which is negative
    for extents that do not reach each other. It is deliberately **not** clamped
    to zero before dividing (C-A3): clamping would make a fraction of 0.0 band
    every region on the page with every other, which is a different rule wearing
    the same constant.

    A zero-length extent is the one case the division cannot express, and it is a
    real detector output if `MIN_REGION_AREA_PX` is ever wrong. C-A4 defines it:
    it bands when the closed extents **touch**, i.e. when the overlap is not
    negative. That also makes two distinct bands unable to share a minimum y-top,
    which is what makes the between-band order independent of the input order.
    """
    overlap = min(a[1], b[1]) - max(a[0], b[0])
    shorter = min(a[1] - a[0], b[1] - b[0])
    if shorter == 0:
        return overlap >= 0
    return overlap / shorter >= BAND_OVERLAP_FRACTION


def _bands(extents: Sequence[tuple[int, int]]) -> list[list[int]]:
    """Group indices into bands, transitively, by union-find over every pair.

    Quadratic in the number of regions and deliberately so: a page carries tens of
    regions, and a union-find over all pairs is the shortest statement of "banding
    is transitive" that has no dependence on the input order at all.
    """
    parent = list(range(len(extents)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(extents)):
        for j in range(i + 1, len(extents)):
            if _bands_together(extents[i], extents[j]):
                left, right = root(i), root(j)
                if left != right:
                    parent[left] = right

    grouped: dict[int, list[int]] = {}
    for i in range(len(extents)):
        grouped.setdefault(root(i), []).append(i)
    return list(grouped.values())


def order_regions(regions: Sequence[RawRegion]) -> list[int]:
    """The input indices of `regions`, in reading order.

    A permutation of `range(len(regions))`: every index once, none repeated, none
    invented. Bands are emitted by ascending minimum y-top (C-A5) and each band is
    read by descending x-centre, ties broken on the input index so that the order
    is total. The sequence handed in is not mutated.
    """
    extents = [_vertical_extent(region) for region in regions]
    centres = [_x_centre(region) for region in regions]

    bands = _bands(extents)
    bands.sort(key=lambda band: min(extents[index][0] for index in band))

    order: list[int] = []
    for band in bands:
        order.extend(sorted(band, key=lambda index: (-centres[index], index)))
    return order


def sort_regions(regions: Sequence[RawRegion]) -> list[RawRegion]:
    """The same regions, reordered - `[regions[i] for i in order_regions(regions)]`.

    Position is the only carrier of reading order (MT-009 PO-1): no region holds a
    `reading_index` of its own, because `store.project.write_regions` derives that
    number from the position of each region in the sequence it is given, and a
    second copy of it in the region would be a second source of truth.
    """
    return [regions[index] for index in order_regions(regions)]
