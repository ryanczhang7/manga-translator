"""Adjacent columns of one utterance, merged into one region (MT-008).

A region is an utterance: one line on the review screen, one translation, one
bubble marker. Measured on `spikes/MT-002/pages/011-014.jpg`, **7 of 25** boxes
the detector fences come back as two regions - the vertical columns of one text
block - so one sentence becomes two review lines and two translations. This
module puts them back together.

**The rule, and both geometric halves of it are necessary** (MT-008 C-5). Two
regions merge when all three hold:

1. they lie in the **same fence box** - the box head's own judgement that they
   are one text block;
2. the **gap** between their extents across the run direction is at most
   `COLUMN_MAX_GAP_PX`;
3. their **overlap** along the run direction is at least `COLUMN_MIN_OVERLAP`
   of the shorter of the two.

Neither geometric clause suffices alone, and the corpus holds a counter-example
to each: `011.jpg` box 4 fences two separate bubbles 3px apart, which only the
overlap clause rejects, and box 7 of the same page fences a separate bubble
whose overlap is complete, which only the gap clause rejects.

**Every quantity here is half-open**, the convention `regions_from_detection`
already uses for box membership (MT-007 amendment A-6). A region's *extent* is
the half-open bounding box `(x0, y0, x1, y1)` of its set mask pixels, covering
`x0 <= x < x1` and `y0 <= y < y1`. With `axis="vertical"`:

    gap     = max(0, max(ax0, bx0) - min(ax1, bx1))     empty pixel COLUMNS
    overlap = max(0, min(ay1, by1) - max(ay0, by0))     shared pixel ROWS
              as a fraction of min(ay1 - ay0, by1 - by0), the SHORTER height

so extents that touch and extents that overlap both score gap 0.
`axis="horizontal"` transposes the two axes and nothing else.

**Run direction is a parameter, not an inference** (C-3). The corpus is 100%
vertical text and carries no evidence for any inference rule; aspect ratio in
particular cannot carry it, since `011.jpg` box 4 holds a taller region beside a
wider one inside one box on a page that is vertical throughout.

**Merging is transitive within a fence box**, evaluated on the *input* extents:
the output is one region per connected component of the pairwise relation, so
three columns of one bubble produce one region and the answer does not depend on
the order the pairs were visited.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image

# `_encode_one_bit_png` is imported rather than reimplemented: `detect` is one
# layer, and a second encoder would be a second thing to keep at bit depth 1,
# colour type 0 and page size - which is exactly what MT-007 C-7 pins.
from mangatl.detect.postprocess import _encode_one_bit_png
from mangatl.domain.region import RawRegion

__all__ = ["COLUMN_MAX_GAP_PX", "COLUMN_MIN_OVERLAP", "merge_columns"]

#: The widest empty channel between two column extents that is still one
#: utterance, in **page pixels at a scan width of 1125** (MT-008 C-4).
#:
#: Measured over every same-box region pair of `011/012/014.jpg`, in this
#: module's half-open convention: the merges run from gap 1 to gap 8, and the
#: nearest thing that must stay apart is the separate bubble of `011` box 7 at
#: gap 54 - so the admissible band is `8 <= value <= 53` and the separation is
#: 6.1x. 12 sits in that band at the end the evidence is on: raising it towards
#: 53 buys nothing the corpus asks for and walks towards the one measured
#: negative.
#:
#: **It is a pixel count and therefore scales with scan resolution.** The corpus
#: is single-resolution (1125x1600, three pages, one artist), so there is no
#: evidence for expressing it as a fraction of page width and none against it;
#: MT-008 `## Notes` records that as a limitation rather than resolving it.
COLUMN_MAX_GAP_PX: int = 12

#: How much of the shorter extent two columns must share along the run
#: direction to be one utterance (MT-008 C-4).
#:
#: Every measured merge overlaps completely (1.000); the one same-box pair that
#: must stay apart - the two separate bubbles `011` box 4 fences - shares 50 of
#: 157 rows, 0.3185. The admissible band is `0.3185 < value <= 1.0`, the
#: separation is 3.2x, and 0.50 sits in the middle of it.
COLUMN_MIN_OVERLAP: float = 0.50

#: A half-open `(x0, y0, x1, y1)` rectangle in page pixels.
Rect = tuple[int, int, int, int]


def merge_columns(
    regions: Sequence[RawRegion],
    fences: Sequence[Rect],
    *,
    axis: Literal["vertical", "horizontal"] = "vertical",
) -> list[RawRegion]:
    """Merge the columns of one utterance, fenced by `fences`.

    `fences` are the half-open integer rectangles `postprocess.integer_boxes`
    produces from the accepted boxes. A region that lies in no fence survives
    untouched - the safe direction is to keep an unexplained region rather than
    to attach it to a neighbour - and so does a region alone in its fence.

    The result is ordered by bounding box `(y0, x0)`, which is
    `regions_from_detection`'s emission order. It is not a reading order:
    MT-009 owns that, and for Japanese it runs right to left.
    """
    masks = [_decode(region.mask) for region in regions]
    extents = [_extent(mask) for mask in masks]
    fenced = [_fence_of(extent, fences) for extent in extents]

    merged = [
        (extents[members[0]], regions[members[0]])
        if len(members) == 1
        else _merge(regions, masks, members)
        for members in _components(extents, fenced, axis)
    ]
    return [region for _bounds, region in sorted(merged, key=lambda pair: pair[0][1::-1])]


def _components(
    extents: Sequence[Rect],
    fenced: Sequence[int | None],
    axis: Literal["vertical", "horizontal"],
) -> list[list[int]]:
    """The connected components of "is one utterance with", as index lists.

    The relation is evaluated on the **input** extents and only then closed
    transitively (C-1): re-evaluating it against a growing merged extent would
    make the result depend on the order the pairs were visited.
    """
    parent = list(range(len(extents)))
    for a in range(len(extents)):
        for b in range(a + 1, len(extents)):
            if fenced[a] is None or fenced[a] != fenced[b]:
                continue
            if _is_one_utterance(_oriented(extents[a], axis), _oriented(extents[b], axis)):
                parent[_root(parent, b)] = _root(parent, a)

    groups: dict[int, list[int]] = {}
    for index in range(len(extents)):
        groups.setdefault(_root(parent, index), []).append(index)
    return list(groups.values())


def _root(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _oriented(extent: Rect, axis: Literal["vertical", "horizontal"]) -> Rect:
    """`extent` with its two axes swapped when the text runs horizontally, so
    that the rule below is always written for vertical columns."""
    x0, y0, x1, y1 = extent
    return (y0, x0, y1, x1) if axis == "horizontal" else extent


def _is_one_utterance(a: Rect, b: Rect) -> bool:
    """Both geometric clauses, on extents already oriented for vertical text."""
    gap = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    shared = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    shorter = min(a[3] - a[1], b[3] - b[1])
    return gap <= COLUMN_MAX_GAP_PX and shared / shorter >= COLUMN_MIN_OVERLAP


def _fence_of(extent: Rect, fences: Sequence[Rect]) -> int | None:
    """The fence box a region belongs to, or `None` when it belongs to none.

    The rectangle with the greatest area of intersection; ties to the lowest
    index, which is `decode_boxes`'s most confident box and the tie-break
    `postprocess._kind` already makes. Measured on the corpus, containment,
    greatest mask overlap and greatest extent overlap agree on all 30 regions,
    so this is a choice between rules nothing distinguishes.
    """
    best: int | None = None
    best_area = 0
    for index, fence in enumerate(fences):
        width = min(extent[2], fence[2]) - max(extent[0], fence[0])
        height = min(extent[3], fence[3]) - max(extent[1], fence[1])
        area = max(0, width) * max(0, height)
        if area > best_area:
            best, best_area = index, area
    return best


def _merge(
    regions: Sequence[RawRegion],
    masks: Sequence[NDArray[np.bool_]],
    members: list[int],
) -> tuple[Rect, RawRegion]:
    """Several regions into one: the union of their masks, and nothing else.

    The polygon is the ring of that union's bounding box. The detail stays in
    the mask, because a single contour cannot describe two disjoint columns and
    the largest of several would describe only one of them (C-1 item 5).

    `confidence` is the mean probability inside the mask (MT-007 C-7), so the
    merged confidence is the inputs' means weighted by **their own set-pixel
    counts** - the one combination that equals the mean over the union.
    """
    union = np.zeros_like(masks[members[0]])
    for index in members:
        union |= masks[index]
    x0, y0, x1, y1 = _extent(union)

    weights = [int(masks[index].sum()) for index in members]
    weighted = sum(
        regions[index].confidence * weight for index, weight in zip(members, weights, strict=True)
    )

    return (x0, y0, x1, y1), RawRegion(
        polygon=((x0, y0), (x1 - 1, y0), (x1 - 1, y1 - 1), (x0, y1 - 1), (x0, y0)),
        mask=_encode_one_bit_png(union),
        confidence=weighted / sum(weights),
        kind=regions[members[0]].kind,
        merged_from=tuple(members),
    )


def _decode(mask: bytes) -> NDArray[np.bool_]:
    """A region's PNG mask as a page-sized boolean array."""
    with Image.open(BytesIO(mask)) as image:
        decoded: NDArray[np.bool_] = np.array(image, dtype=bool)
    return decoded


def _extent(mask: NDArray[np.bool_]) -> Rect:
    """The half-open bounding box of the set pixels of `mask`."""
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
