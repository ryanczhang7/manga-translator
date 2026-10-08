"""The rasteriser, the IoU and the one region-matching rule the benchmark uses.

MT-029 `## Contract` block 1. MT-022 (S1b, acceptance) and MT-023 (S2,
detection recall) both import `match_regions` and `IOU_MATCH_THRESHOLD` from
here, and `bench.truth` imports the threshold for AC-4 - so "two truth regions
are ambiguous" and "a proposal matches a truth region" are one question asked
with one number (`architecture.md` §2, the `bench` row).

**Why this is not borrowed from `detect/postprocess.py`.** `bench` may not
import `mangatl.detect` (layers contract) or `onnxruntime` (confinement
contract), `architecture.md` §3; and a box IoU is not a polygon IoU anyway. The
rasteriser is Pillow's `ImageDraw.polygon`, which fills an axis-aligned
rectangle's **inclusive** pixel range - pinned by `tests/core/test_bench_matching.py`.

**Two polygon conventions never meet.** A truth polygon is an open vertex list
(MT-029 PO-1); `RawRegion.polygon` is a closed ring. `match_regions` reads a
proposal's **mask**, never its polygon, so neither convention leaks into the
other.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from mangatl.domain.region import RawRegion

if TYPE_CHECKING:
    from mangatl.bench.truth import TruthRegion

__all__ = [
    "IOU_MATCH_THRESHOLD",
    "Match",
    "Polygon",
    "decode_mask",
    "iou",
    "match_regions",
    "polygon_mask",
]

#: A proposal and a truth region pair when their IoU is at least this. AC-4 of
#: MT-029 rejects two truth regions overlapping at this value or above, because
#: a single proposal could then match either.
IOU_MATCH_THRESHOLD: float = 0.5

#: At least three vertices in page pixel coordinates, the first NOT repeated.
Polygon = tuple[tuple[int, int], ...]


def polygon_mask(polygon: Polygon, width: int, height: int) -> NDArray[np.bool_]:
    """Rasterise `polygon` onto a `width` x `height` page: shape `(height, width)`.

    The polygon is closed implicitly. Anything off the page is clipped.
    """
    image = Image.new("L", (width, height), 0)
    ImageDraw.Draw(image).polygon(list(polygon), fill=1)
    return np.asarray(image) > 0


def decode_mask(png: bytes) -> NDArray[np.bool_]:
    """A `RawRegion.mask` - a 1-bit PNG over the whole page - as a bool array."""
    with Image.open(BytesIO(png)) as image:
        return np.asarray(image.convert("L")) > 0


def iou(a: NDArray[np.bool_], b: NDArray[np.bool_]) -> float:
    """Intersection over union of two same-shaped masks; `0.0` if both are empty."""
    if a.shape != b.shape:
        raise ValueError(f"masks of different shapes cannot be compared: {a.shape} and {b.shape}")
    union = int(np.logical_or(a, b).sum())
    if union == 0:
        return 0.0
    return int(np.logical_and(a, b).sum()) / union


@dataclass(frozen=True)
class Match:
    """One line of a matching: a truth region, a proposal, or a pair of them.

    `truth_index` is `None` for a spurious proposal; `region_id` is `None` for
    a missed truth region; `iou` is `0.0` whenever either side is `None`.
    """

    truth_index: int | None
    region_id: int | None
    iou: float


def match_regions(
    proposals: Sequence[RawRegion],
    truth: Sequence[TruthRegion],
    *,
    width: int,
    height: int,
) -> list[Match]:
    """Pair proposals with truth regions one-to-one, greedily by descending IoU.

    Ties go to the lower `(truth index, proposal position)`, so the result is
    deterministic. Returns one `Match` per truth region in truth order, then one
    per unmatched proposal in proposal order.
    """
    truth_masks = [polygon_mask(region.polygon, width, height) for region in truth]
    proposal_masks = [decode_mask(region.mask) for region in proposals]
    candidates = sorted(
        (-value, t, p)
        for t, truth_mask in enumerate(truth_masks)
        for p, proposal_mask in enumerate(proposal_masks)
        if (value := iou(proposal_mask, truth_mask)) >= IOU_MATCH_THRESHOLD
    )

    paired: dict[int, tuple[int, float]] = {}
    taken: set[int] = set()
    for negated, t, p in candidates:
        if t in paired or p in taken:
            continue
        paired[t] = (p, -negated)
        taken.add(p)

    result = [
        Match(truth_index=t, region_id=paired[t][0], iou=paired[t][1])
        if t in paired
        else Match(truth_index=t, region_id=None, iou=0.0)
        for t in range(len(truth))
    ]
    result.extend(
        Match(truth_index=None, region_id=p, iou=0.0)
        for p in range(len(proposals))
        if p not in taken
    )
    return result
