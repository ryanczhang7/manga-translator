"""Cleaning one page: erase the mask and let LaMa reconstruct it (MT-019 C-4).

**One model call per 8-connected component of the erase mask, never tiles**
(PO-5). A component inpainted in one call has no tile boundary inside its hole,
so the seam failure MT-002 DV-1 names cannot occur, and two overlapping regions
are one component - which is what makes AC-3 hold by construction.

* **Native path** - a component whose bbox leaves `MIN_CONTEXT_PX` on every side
  inside 512 is cut as a 512x512 window at native resolution, centred on the
  bbox and clamped into the page. An axis shorter than 512 is the whole axis,
  edge-padded bottom/right to 512.
* **Downscale path** - otherwise the bbox plus `MIN_CONTEXT_PX` is resized so its
  long side is 512 (`INTER_AREA`), the hole thresholded `> 0` so that no hole
  pixel can survive as visible context, and the patch resized back
  (`INTER_LINEAR`). A correctness fallback: no component on the fixture pages
  takes it.

Components are processed in ascending label order, each window cut from the
working result, and **only the component's own pixels are written back** - the
one line ending `# write-back`. Nothing outside the erase mask is modified
(AC-4); the brief's firmest non-goal.

The session convention (RGB, `[0, 1]` in, `1.0` = hole, `[0, 255]` out) is
`mangatl.clean.session`'s, settled in C-2.
"""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from mangatl.clean.session import MODEL_INPUT_SIDE, InpaintSession

__all__ = [
    "INPAINT_MAX_RESIDUAL",
    "MIN_CONTEXT_PX",
    "TONE_VARIANCE_TOLERANCE",
    "clean_page",
]

#: AC-6's bound: mean absolute residual, in 8-bit levels, over the pixels the
#: rendered text changed, cleaned composite against the untouched scan (C-5,
#: C-9). Measured in MT-019 GREEN at `MASK_DILATION_PX = 2`: cleaned **1.003**
#: (0.96-1.17 across `r = 0..12`), uncleaned control **145.37**. Set at about 4x
#: the cleaned value for headroom; the control then scores 36x the bound against
#: the 4x AC-6 demands (PO-8: at most a quarter of the control, 36.34). Leaving
#: roughly 2.8 % of the text's pixels unerased would already exceed it.
INPAINT_MAX_RESIDUAL: float = 4.0

#: AC-7's bound on `|ratio - 1|`, `ratio` being local variance inside the
#: reconstructed area over local variance in an annulus around it (C-5, C-9).
#: Measured in MT-019 GREEN at `MASK_DILATION_PX = 2`: cleaned ratio **0.836**
#: (deviation 0.164; 0.14-0.19 across `r = 0..12`), the untouched reference
#: deviates by at most 0.058, a flat white fill scores **0.000** (deviation 1.0).
#: 0.3 gives 0.136 of headroom over the cleaned deviation, and the flat fill
#: misses by 3.3 tolerances against the 2 AC-7 demands.
TONE_VARIANCE_TOLERANCE: float = 0.3

#: The guaranteed floor of context on every side of a component on the native
#: path (PO decision, not tuned): any component that fits gets far more except at
#: a page edge, and at 64 the 420-px component on `015.jpg` would already fall to
#: the lossy downscale path.
MIN_CONTEXT_PX: int = 32

_SIDE = MODEL_INPUT_SIDE


def clean_page(
    page: NDArray[np.uint8], mask: NDArray[np.bool_], session: InpaintSession
) -> NDArray[np.uint8]:
    """A new copy of the RGB `page` with every `mask` pixel inpainted by `session`.

    Neither input is mutated. An all-`False` mask returns a copy without calling
    the model. `ValueError` if `page` is not `(H, W, 3)` uint8, `mask` is not a
    2-D bool array, or their shapes disagree.
    """
    _validate(page, mask)
    result = page.copy()
    if not mask.any():
        return result
    height, width = mask.shape
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    for label in range(1, count):
        bx, by, bw, bh = (int(v) for v in stats[label, :4])
        if bw + 2 * MIN_CONTEXT_PX <= _SIDE and bh + 2 * MIN_CONTEXT_PX <= _SIDE:
            x0, x1 = _native_span(bx, bw, width)
            y0, y1 = _native_span(by, bh, height)
            target = result[y0:y1, x0:x1]
            hole = labels[y0:y1, x0:x1] == label
            patch = _inpaint(target, hole, session)
        else:
            x0, x1 = max(bx - MIN_CONTEXT_PX, 0), min(bx + bw + MIN_CONTEXT_PX, width)
            y0, y1 = max(by - MIN_CONTEXT_PX, 0), min(by + bh + MIN_CONTEXT_PX, height)
            target = result[y0:y1, x0:x1]
            hole = labels[y0:y1, x0:x1] == label
            patch = _inpaint_downscaled(target, hole, session)
        target[hole] = patch[hole]  # write-back
    return result


def _validate(page: NDArray[np.uint8], mask: NDArray[np.bool_]) -> None:
    if page.ndim != 3 or page.shape[2] != 3 or page.dtype != np.uint8:
        raise ValueError(f"page must be (H, W, 3) uint8; got {page.shape} {page.dtype}")
    if mask.ndim != 2 or mask.dtype != np.bool_:
        raise ValueError(f"mask must be a 2-D bool array; got {mask.shape} {mask.dtype}")
    if mask.shape != page.shape[:2]:
        raise ValueError(f"mask shape {mask.shape} does not match page shape {page.shape[:2]}")


def _native_span(start: int, length: int, limit: int) -> tuple[int, int]:
    """A 512-long span centred on `[start, start + length)`, clamped into `[0, limit)`.

    On an axis shorter than 512 the span is the whole axis (padded later).
    """
    centre = start + length // 2
    lo = min(max(centre - _SIDE // 2, 0), max(limit - _SIDE, 0))
    return lo, min(lo + _SIDE, limit)


def _inpaint_downscaled(
    crop: NDArray[np.uint8], hole: NDArray[np.bool_], session: InpaintSession
) -> NDArray[np.uint8]:
    """C-4 step 4: shrink the crop to 512 on its long side, inpaint, grow back."""
    crop_h, crop_w = hole.shape
    scale = _SIDE / max(crop_w, crop_h)
    size = (max(1, round(crop_w * scale)), max(1, round(crop_h * scale)))
    small = np.asarray(
        cv2.resize(np.ascontiguousarray(crop), size, interpolation=cv2.INTER_AREA), dtype=np.uint8
    )
    # Conservative: any model pixel a hole pixel contributed to is itself a hole,
    # so no ink is shown to the model as context and copied back as text.
    small_hole = cv2.resize(hole.astype(np.float32), size, interpolation=cv2.INTER_AREA) > 0
    small_patch = _inpaint(small, np.asarray(small_hole, dtype=bool), session)
    return np.asarray(
        cv2.resize(small_patch, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR), dtype=np.uint8
    )


def _inpaint(
    window: NDArray[np.uint8], hole: NDArray[np.bool_], session: InpaintSession
) -> NDArray[np.uint8]:
    """One model call on a window of at most 512x512: edge-pad, run, crop back."""
    h, w = hole.shape
    pad = ((0, _SIDE - h), (0, _SIDE - w))
    padded = np.pad(window, (*pad, (0, 0)), mode="edge")
    padded_hole = np.pad(hole, pad, mode="constant", constant_values=False)
    image = (padded.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
    model_mask = padded_hole[None, None].astype(np.float32)  # model-mask
    out = session.run(np.ascontiguousarray(image), model_mask)
    patch: NDArray[np.uint8] = np.clip(np.rint(out[0].transpose(1, 2, 0)), 0, 255).astype(np.uint8)
    return patch[:h, :w]
