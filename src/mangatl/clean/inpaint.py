"""Cleaning one page: erase the mask and let LaMa reconstruct it (MT-019 C-4).

Each 8-connected component of the erase mask takes one of three paths, chosen
from its bbox against `512 - 2 * MIN_CONTEXT_PX` (MT-151 C-2):

* **Native** - fits on both axes: one call on a 512x512 window at native
  resolution, centred on the bbox and clamped into the page. An axis shorter
  than 512 is the whole axis, edge-padded bottom/right to 512.
* **Strips** - too long on exactly one axis: native-resolution 512 windows
  advancing along that axis, each cut from the working result (MT-151 C-3).
  A call masks every unfilled component pixel in its window but writes back
  only up to `MIN_CONTEXT_PX` short of the window's far edge, so each band is
  reconstructed with context on both sides; every pixel is written once.
* **Downscale** - too long on both axes: one call on the bbox plus
  `MIN_CONTEXT_PX`, resized so its long side is 512 (`INTER_AREA`), the hole
  thresholded `> 0` so that no hole pixel survives as visible context, and the
  patch resized back (`INTER_LINEAR`).

Components are processed in ascending label order, each window cut from the
working result, and **only the component's own pixels are written back** - the
lines ending `# write-back`. Nothing outside the erase mask is modified
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
    "STRIP_OVERLAP_PX",
    "TONE_VARIANCE_TOLERANCE",
    "clean_page",
]

# MT-069: survive a lost thread-pool completion port - see `mangatl.clean.mask`.
cv2.setNumThreads(-1)

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

#: The minimum overlap, along the long axis, of consecutive windows on the
#: strips path (MT-151 C-3, C-4). It starts at `MIN_CONTEXT_PX` and is not
#: tuned: it changes only on the evidence of MT-151 DV-2 (residual ink on the
#: tall regions of the development set, real LaMa), recorded here when it does.
STRIP_OVERLAP_PX: int = MIN_CONTEXT_PX

_SIDE = MODEL_INPUT_SIDE
_LIMIT = _SIDE - 2 * MIN_CONTEXT_PX
_LEAD = MIN_CONTEXT_PX + STRIP_OVERLAP_PX
_TRAIL = MIN_CONTEXT_PX


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
    count, found, stats, _centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    labels = np.asarray(found, dtype=np.int32)
    for label in range(1, count):
        bx, by, bw, bh = (int(v) for v in stats[label, :4])
        fits_x, fits_y = bw <= _LIMIT, bh <= _LIMIT
        if fits_x and fits_y:
            x0, x1 = _native_span(bx, bw, width)
            y0, y1 = _native_span(by, bh, height)
            target = result[y0:y1, x0:x1]
            hole = labels[y0:y1, x0:x1] == label
            patch = _inpaint(target, hole, session)
        elif fits_x != fits_y:
            _clean_strips(result, labels, label, (bx, by, bw, bh), fits_x, session)
            continue
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


def _clean_strips(
    result: NDArray[np.uint8],
    labels: NDArray[np.int32],
    label: int,
    bbox: tuple[int, int, int, int],
    along_y: bool,
    session: InpaintSession,
) -> None:
    """MT-151 C-3: clean one component in native windows along its long axis, in place."""
    bx, by, bw, bh = bbox
    height, width = labels.shape
    if along_y:
        x0, x1 = _native_span(bx, bw, width)
        b, length, n = by, bh, height
    else:
        y0, y1 = _native_span(by, bh, height)
        b, length, n = bx, bw, width
    stop = b + length
    c = b
    while True:
        lo = min(max(c - _LEAD, 0), max(n - _SIDE, 0))
        hi = min(lo + _SIDE, n)
        last = stop <= hi - _TRAIL or hi == n
        end = stop if last else hi - _TRAIL
        if along_y:
            y0, y1 = lo, hi
            t = np.arange(lo, hi)[:, None]
        else:
            x0, x1 = lo, hi
            t = np.arange(lo, hi)[None, :]
        target = result[y0:y1, x0:x1]
        comp = labels[y0:y1, x0:x1] == label
        hole = comp & (t >= c)
        patch = _inpaint(target, hole, session)
        write = hole & (t < end)
        target[write] = patch[write]  # write-back
        if last:
            return
        c = end


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
