"""The erase mask: the only pixels cleaning may touch (MT-019 C-3, AC-1, AC-5).

The union of every region's own mask (`RawRegion.mask`, MT-007's 1-bit,
page-sized PNG - the detector's `seg` intersected with its accepted boxes, MT-002
E6), dilated once by an elliptical kernel of radius `MASK_DILATION_PX`. The array
is page-sized from the start, so `cv2.dilate` has no pixel outside the page to
set: that *is* "clipped to the page".

**Grown over the glyphs it cuts** (MT-152 C-3). Given the source page as grey
(`source_grey`), every 8-connected component of ink (`<= GLYPH_INK_GREY`) that
the raw union touches is added whole before the dilation, when it is glyph-sized
(bounding box at most `GLYPH_MAX_SIDE_PX` on both sides) and stands on paper (at
least `GLYPH_PAPER_RING_FRACTION` of the ring `GLYPH_RING_PX` around it is
`>= GLYPH_PAPER_GREY`; off-page pixels are not counted, an empty ring is not
paper). Whether a component is a glyph depends on the page alone, so the growth
distributes over union, as the dilation does. The constants are for a 1414 px
wide scan and are not scaled to other widths.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from mangatl.domain.region import RawRegion

__all__ = [
    "GLYPH_INK_GREY",
    "GLYPH_MAX_SIDE_PX",
    "GLYPH_PAPER_GREY",
    "GLYPH_PAPER_RING_FRACTION",
    "GLYPH_RING_PX",
    "MASK_DILATION_PX",
    "erase_mask",
    "source_grey",
]

# MT-069: survive a lost thread-pool completion port. OpenCV's ConcRT backend
# attaches a thread on its first parallel call through the *default* scheduler,
# and that attach calls `SetThreadpoolWait`, which raises 0xC000070A for the life
# of the process once the default Windows thread pool has lost its I/O completion
# port (audit MT-068, Decided 1, E3-E5). Any explicit `setNumThreads` before the
# first parallel call makes OpenCV create and attach to a scheduler of its own,
# which never takes that path (E9; MT-069 C-4 amended, PO-3). `-1` is OpenCV's
# "reset to the system default": the explicit scheduler, at exactly the thread
# count OpenCV would have chosen on this machine, so nothing goes serial. It is
# process-wide and idempotent; every module that imports cv2 makes the same call
# so that no import order leaves a cv2 caller uncontained.
cv2.setNumThreads(-1)

#: Radius, in pixels, of the elliptical dilation applied to the union of region
#: masks: a mask that hugs the glyphs leaves an anti-aliased halo; too wide and
#: the bubble's outline is eaten. Measured in MT-019 GREEN (`## Notes`, C-7)
#: with the real detector and `lama_fp32.onnx`. **Too small:** at `r = 0` three
#: rendered-text pixels on the AC-6 composite lie outside the erase mask and
#: survive cleaning (up to 47 levels off the reference) and the AC-6 residual is
#: 1.17 against 0.96-1.03 at `r = 1..12`; at `r = 1` every changed pixel is
#: erased. **Too large:** on the real bubble of MT-002 E7 case 1 (`012.jpg`) the
#: dilation band first reaches outline ink (grey < 100) at `r = 31`; zero dark
#: pixels through `r = 30`. 2 is the smallest radius that erased everything,
#: plus one pixel of headroom for a detector or fence change.
MASK_DILATION_PX: int = 2

# MT-152 C-6: the glyph growth's limits, derived on the development set (46
# pages of a 1414 px wide scan, never the benchmark; the story's `## Notes`,
# "GREEN: the constants"). Where no setting grew every glyph and no outline,
# the outline and the art won: a broken balloon outline leaves fragments of
# glyph size on paper (a 72x60 arc, a 29x12 curve), so the size limit sits
# below the arc and the ring is wider and stricter than the planning probe's,
# at the cost of the two longest dashes (73 and 74 px) and a few glyphs.

#: A source pixel at or below this grey is ink.
GLYPH_INK_GREY: int = 128
#: A component wider or taller than this is not a glyph (an outline, a frame).
GLYPH_MAX_SIDE_PX: int = 71
#: Radius of the ring looked at around a component.
GLYPH_RING_PX: int = 3
#: A ring pixel at or above this grey is paper.
GLYPH_PAPER_GREY: int = 225
#: The share of the ring that must be paper for a component to be a glyph.
GLYPH_PAPER_RING_FRACTION: float = 0.84


def source_grey(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """The decoded `(H, W, 3)` RGB source as the `(H, W)` grey `erase_mask` reads.

    PIL's ITU-R 601-2 luma (`convert("L")`): the one place a source scan becomes
    grey for the mask (MT-152 C-2).
    """
    return np.asarray(Image.fromarray(rgb, "RGB").convert("L"), dtype=np.uint8)


def erase_mask(
    regions: Sequence[RawRegion],
    page_size: tuple[int, int],
    page: NDArray[np.uint8] | None = None,
) -> NDArray[np.bool_]:
    """The `(height, width)` boolean mask of pixels to erase on a `(width, height)` page.

    With `page` (`source_grey` of the source scan) the union of masks is first
    grown over every glyph it touches (MT-152 C-3); without it, it is not.

    Raises `ValueError` naming the region's index if a decoded mask is not
    page-sized, and, before any mask is decoded, if `page` is not a
    `(height, width)` `uint8` array: neither is ever resized, transposed, cropped
    or cast silently.
    """
    width, height = page_size
    if page is not None:
        if page.dtype != np.uint8:
            raise ValueError(f"page is {page.dtype}, not uint8")
        if page.shape != (height, width):
            raise ValueError(
                f"page has shape {page.shape}, the page is {width}x{height}"
                f" (expected shape {(height, width)})"
            )
    union = np.zeros((height, width), dtype=bool)
    for index, region in enumerate(regions):
        with Image.open(BytesIO(region.mask)) as image:
            decoded = np.asarray(image) != 0
        if decoded.shape != (height, width):
            raise ValueError(
                f"region {index}: mask is {decoded.shape[1]}x{decoded.shape[0]},"
                f" the page is {width}x{height}"
            )
        union |= decoded
    grown = union if page is None else union | _glyphs_touched(union, page)
    # Read at call time, never bound at import: tests pin the disk per radius.
    return _dilated(grown, MASK_DILATION_PX)


def _dilated(mask: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    """`mask` dilated by the elliptical kernel of side `2 * radius + 1`."""
    if radius == 0:
        return mask
    side = 2 * radius + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
    return np.asarray(cv2.dilate(mask.astype(np.uint8), kernel), dtype=bool)


def _glyphs_touched(union: NDArray[np.bool_], page: NDArray[np.uint8]) -> NDArray[np.bool_]:
    """Every whole 8-connected ink component of `page` that `union` touches and
    that is a glyph by size and ring (MT-152 C-3 steps 1 to 5)."""
    # Every limit read at call time, never bound at import (C-1).
    max_side = GLYPH_MAX_SIDE_PX
    ring_px = GLYPH_RING_PX
    paper_grey = GLYPH_PAPER_GREY
    fraction = GLYPH_PAPER_RING_FRACTION
    ink = (page <= GLYPH_INK_GREY).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    height, width = page.shape
    glyphs = np.zeros((height, width), dtype=bool)
    for label in np.unique(labels[union & (ink != 0)]):
        left, top, box_w, box_h = (int(v) for v in stats[label, :4])
        if box_w > max_side or box_h > max_side:
            continue
        # The ring lies within `ring_px` of the box; clipping the crop to the
        # page is what leaves off-page pixels out of both sides of the fraction.
        y0, y1 = max(top - ring_px, 0), min(top + box_h + ring_px, height)
        x0, x1 = max(left - ring_px, 0), min(left + box_w + ring_px, width)
        component = labels[y0:y1, x0:x1] == label
        ring = _dilated(component, ring_px) & ~component
        ring_count = int(ring.sum())
        if ring_count == 0:
            continue
        paper_count = int((page[y0:y1, x0:x1][ring] >= paper_grey).sum())
        if paper_count / ring_count >= fraction:
            glyphs[y0:y1, x0:x1] |= component
    return glyphs
