"""Adjacent columns of one utterance, merged into one region (MT-008).

A region is an utterance: one line on the review screen, one translation, one
bubble marker. Measured on `spikes/MT-002/pages/011-014.jpg`, **7 of 25** boxes
the detector fences come back as two regions - the vertical columns of one text
block - so one sentence becomes two review lines and two translations. This
module puts them back together.

**The rule, and both geometric halves of each clause are necessary** (MT-008
C-5, MT-145). Two regions merge when they lie in the **same fence box** - the
box head's own judgement that they are one text block - and either clause
holds:

- **side by side** (adjacent columns): the **gap** between their extents
  across the run direction is at most `COLUMN_MAX_GAP_PX`, and their
  **overlap** along the run direction is at least `COLUMN_MIN_OVERLAP` of the
  shorter of the two;
- **stacked** (pieces of one column, MT-145): the **gap** between their
  extents along the run direction is at most `COLUMN_MAX_RUN_GAP_PX`, and
  their **overlap** across the run direction is at least `COLUMN_MIN_OVERLAP`
  of the narrower of the two.

Neither geometric half suffices alone, and the corpora hold a counter-example
to each: `011.jpg` box 4 fences two separate bubbles 3px apart, which only the
overlap rejects, and box 7 of the same page fences a separate bubble whose
overlap is complete, which only the gap rejects; on the MT-143 development set,
p075 fences two balloons that touch (gap 0 both ways) and share too little in
either direction, which only the overlaps reject.

**Every quantity here is half-open**, the convention `regions_from_detection`
already uses for box membership (MT-007 amendment A-6). A region's *extent* is
the half-open bounding box `(x0, y0, x1, y1)` of its set mask pixels, covering
`x0 <= x < x1` and `y0 <= y < y1`. With `axis="vertical"`:

    gap     = max(0, max(ax0, bx0) - min(ax1, bx1))     empty pixel COLUMNS
    overlap = max(0, min(ay1, by1) - max(ay0, by0))     shared pixel ROWS
              as a fraction of min(ay1 - ay0, by1 - by0), the SHORTER height

and the stacked clause is the same two quantities with x and y exchanged
(`run gap` in empty ROWS, `run overlap` in shared COLUMNS of the NARROWER
width). Extents that touch and extents that overlap both score gap 0.
`axis="horizontal"` transposes the two axes and nothing else, so both clauses
are written once, for vertical text.

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

__all__ = ["COLUMN_MAX_GAP_PX", "COLUMN_MAX_RUN_GAP_PX", "COLUMN_MIN_OVERLAP", "merge_columns"]

#: The widest empty channel ACROSS the run between two side-by-side column
#: extents that is still one utterance, in page pixels (MT-008 C-4, re-derived
#: in MT-145).
#:
#: Re-derived on the MT-143 development set (`blackjack-v1-ep02-03`, 46 pages
#: at 1414 px wide; never the benchmark), in this module's half-open
#: convention. Adjacent columns of one balloon in one fence box sit 12, 13, 14,
#: 14, 20 and 25 px apart, plus one at 38 (p104); different balloons in one
#: fence box sit 37-71 px apart (median 53). MT-008's corpus (`011/012/014.jpg`,
#: 1125 px wide) adds merges at 1-8 and a separate bubble at 54, and the chain
#: test in `test_detect_page.py` keeps a pair 42 px apart. So the admissible
#: band is `25 <= value <= 36`, and p104's 38 px pair stays split by choice.
#: Swept over 25..36 with `COLUMN_MAX_RUN_GAP_PX` (MT-145 `## Notes`): no value
#: in the band joins two user-confirmed regions; 26 is the smallest that, with
#: the run limit below it, leaves the fewest balloon pieces. Separation from
#: the nearest different balloon is 37 / 25 = 1.5x; it was 6.1x on MT-008's
#: corpus alone.
#:
#: **It is a pixel count and therefore scales with scan resolution.** Two
#: corpora at two widths are not evidence for expressing it as a fraction of
#: page width, nor against it; MT-008 `## Notes` records that as a limitation.
COLUMN_MAX_GAP_PX: int = 26

#: The widest empty gap ALONG the run between two pieces stacked in one column
#: that is still one utterance, in page pixels (MT-145). A pixel count, with
#: the same resolution limit as `COLUMN_MAX_GAP_PX`.
#:
#: Measured on the MT-143 development set: adjacent pieces of one balloon along
#: one column sit 0-17 px apart (57 of 65 pairs), then 24, 25, 26, 29, 29, 59
#: and 116. The one different-utterance pair stacked in a fence box (p075 seeds
#: 2/3) touches, gap 0, sharing 0.156 of the narrower width - the overlap
#: clause separates it, not the gap, so no measured negative bounds the gap
#: from above: the band is `25 <= value < COLUMN_MAX_GAP_PX`, the lower end
#: being where the balloon pieces bottom out and the upper end MT-145 A-1's
#: pin, which keeps the axis readable between the two limits. Swept over 6..35:
#: no value joins two user-confirmed regions; 25 is the smallest that leaves
#: the fewest balloon pieces (10 of MT-143's 41, against 11 at 10-24).
COLUMN_MAX_RUN_GAP_PX: int = 25

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
    """Side by side or stacked, on extents already oriented for vertical text."""
    gap = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    shared = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    shorter = min(a[3] - a[1], b[3] - b[1])
    side_by_side = gap <= COLUMN_MAX_GAP_PX and shared / shorter >= COLUMN_MIN_OVERLAP

    run_gap = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    run_shared = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    narrower = min(a[2] - a[0], b[2] - b[0])
    stacked = run_gap <= COLUMN_MAX_RUN_GAP_PX and run_shared / narrower >= COLUMN_MIN_OVERLAP
    return side_by_side or stacked


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
