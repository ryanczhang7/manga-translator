"""The letterbox, the box decode and the regions: everything the detector does
that is arithmetic rather than inference.

**Why the boxes are a parameter and not an implementation detail** (MT-007 C-3).
AC-6 forbids a region from touching an art-integrated sound effect, and that is a
property of the **box head**, not of the mask head: measured on
`spikes/MT-002/pages/012.jpg`, the `seg` head covers 27-59% of every annotated
SFX area at every threshold from 0.10 to 0.999, while the decoded box head covers
**0.000** of all six. A function that cannot see the boxes cannot implement the
criterion, so `regions_from_detection` takes them.

**The order of operations, each step of which was measured** (MT-007 C-4):

1. letterbox the page into 1024 square, grey 114, aspect preserved;
2. resize the probability map to page size and leave it a probability - MT-030
   E4 measured resize-then-threshold at recall 0.9658 / IoU 0.5657 against
   threshold-then-resize's 0.9492 / 0.5847;
3. threshold at `MASK_THRESHOLD`;
4. intersect with the accepted boxes;
5. connected components, **discarding those below `MIN_REGION_AREA_PX`** - the
   floor runs here, *before* the dilation, because a 4 px speckle dilated by two
   iterations of a 7x7 kernel is 196 px and would clear every floor C-6
   contemplates (amendment A-7);
6. dilate the survivors;
7. **intersect with the accepted boxes again.** The boxes are a fence, not a
   filter applied once: a dilation after the only intersection walks the mask
   back out over the SFX and silently breaks AC-6;
8. connected components again - dilation merges neighbours, and that merging is
   the point of step 6. Components thinner than two pixels in either direction
   are dropped: `findContours` returns two points for a one-pixel-tall run, so it
   has no polygon, and a 1x300 scanline is nothing MT-016 can typeset into
   anyway (amendment A-12);
9. one `RawRegion` per survivor, emitted sorted by bounding-box `(y0, x0)`. That
   is an **emission** order, chosen because it is deterministic. It is not a
   reading order - MT-009 owns that and for Japanese it runs right to left.

**Two conventions every pixel count here depends on** (amendment A-6).
`page_size` is `(width, height)` while `prob.shape` is `(height, width)`, and a
mismatch raises rather than transposing a page silently. Box membership is
half-open: `(x, y)` is inside `(x0, y0, x1, y1)` when `floor(x0) <= x < floor(x1)`
and `floor(y0) <= y < floor(y1)`, so a box of integer coordinates covers exactly
`(x1 - x0) * (y1 - y0)` pixels.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from mangatl.detect.session import MODEL_INPUT_SIDE, PAD_VALUE
from mangatl.domain.region import RawRegion

__all__ = [
    "BOX_CONFIDENCE",
    "DILATE_ITERATIONS",
    "DILATE_KERNEL_SIDE",
    "MASK_THRESHOLD",
    "MIN_REGION_AREA_PX",
    "NMS_IOU",
    "LetterboxTransform",
    "decode_boxes",
    "letterbox",
    "probability_to_page",
    "regions_from_detection",
]

#: The probability above which a pixel is text.
#:
#: Derived in MT-007 GREEN against the real `seg` head, measured **inside the
#: accepted boxes** - the only place this pipeline ever looks - on the author's
#: own refined reference mask (`spikes/MT-002/oracle/ctd/ref-mask.png`):
#:
#:     threshold   0.10    0.30    0.50    0.60    0.70   0.772    0.90
#:     recall    0.9998  0.9981  0.9917  0.9832  0.9671  0.9428  0.8357
#:     bleed %    32.16   22.98   15.85   12.70    9.43    7.09    3.40
#:
#: 0.50 is the knee: recall is flat to within 0.8 points from 0.10 to 0.50 while
#: the bleed halves, and past 0.50 recall starts paying for it. Raising it loses
#: faint text and fragments strokes (components under 21 px: 23 at 0.50, 50 at
#: 0.70, 86 at 0.90 - a high threshold manufactures the very speckle the area
#: floor then deletes); lowering it bleeds into screentone. See MT-007 `## Notes`
#: for both directions in full.
MASK_THRESHOLD: float = 0.50

#: The speckle floor: a connected component smaller than this, measured **before
#: the dilation**, is noise and produces no region. It is not a size filter - the
#: 252 px single-kana bubble of `fixtures/detect/single-kana.json` is what pins
#: the ceiling, and it must survive.
#:
#: Derived in MT-007 GREEN from every fenced component under 60 px on
#: `011-015.jpg` at `MASK_THRESHOLD`: each of the 8 components of 20 px or fewer
#: has mean probability <= 0.632 and **max <= 0.776** - not one confident pixel
#: in any of them - while every component of 22 px or more has max >= 0.809 and
#: all but two reach 1.000. The floor goes in that gap, at the smallest value
#: that clears it.
MIN_REGION_AREA_PX: int = 21

#: `obj * max(cls)` at or above which a decoded anchor is an accepted box.
BOX_CONFIDENCE: float = 0.40

#: The IoU at which greedy non-maximum suppression drops the weaker of two
#: overlapping anchors. Class-agnostic: two anchors on one bubble disagreeing
#: about its class are still one bubble.
NMS_IOU: float = 0.45

#: How many times the surviving components are dilated before the second fence.
DILATE_ITERATIONS: int = 2

#: The side of the square structuring element. A 7x7 element grows a component by
#: three pixels in every direction per iteration, so two iterations close a
#: 12-pixel gap and no more - which is what the 16-pixel clearance in
#: `overlapping-bubbles.json` and the 4-pixel gap in `sfx.json` are sized against
#: (amendment A-8).
DILATE_KERNEL_SIDE: int = 7

#: A component narrower or shorter than this has no interior, so `findContours`
#: cannot give it a polygon of four vertices (amendment A-12).
_MIN_REGION_SIDE_PX = 2

#: The class the detector's box head gives a speech bubble. Measured across
#: `011-015.jpg`: every OCR-confirmed bubble is class 1, and the rare class 0 is
#: the free-floating scanlation watermark - text on art rather than text in a
#: bubble (amendment A-4). This is the opposite of the obvious guess.
_BUBBLE_CLASS = 1

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class LetterboxTransform:
    """How a page was fitted into the model's square canvas.

    `ratio` scales page pixels to canvas pixels; `pad_x` and `pad_y` are the grey
    margins on the **left** and **top** (padding is centred, so the right and
    bottom margins differ by at most one pixel).
    """

    ratio: float
    pad_x: int
    pad_y: int


def letterbox(
    page: NDArray[np.uint8],
    side: int = MODEL_INPUT_SIDE,
    pad: int = PAD_VALUE,
) -> tuple[NDArray[np.float32], LetterboxTransform]:
    """Fit `page` `(height, width, 3)` into a `(1, 3, side, side)` float canvas.

    Aspect ratio preserved, the remainder filled with grey `pad`, and the whole
    thing divided by 255 - which is the canvas the graph's `images` input wants.
    """
    height, width = page.shape[:2]
    ratio = side / float(max(height, width))
    scaled_width = round(width * ratio)
    scaled_height = round(height * ratio)
    resized = cv2.resize(
        page,
        (scaled_width, scaled_height),
        interpolation=cv2.INTER_AREA if ratio < 1.0 else cv2.INTER_LINEAR,
    )

    pad_x = (side - scaled_width) // 2
    pad_y = (side - scaled_height) // 2
    canvas = np.full((side, side, 3), pad, dtype=np.uint8)
    canvas[pad_y : pad_y + scaled_height, pad_x : pad_x + scaled_width] = resized

    normalised = np.ascontiguousarray(
        (canvas.astype(np.float32) / 255.0).transpose(2, 0, 1)[np.newaxis]
    )
    return normalised, LetterboxTransform(ratio=ratio, pad_x=pad_x, pad_y=pad_y)


def decode_boxes(
    blk: NDArray[np.float32],
    transform: LetterboxTransform,
    page_size: tuple[int, int],
) -> NDArray[np.float32]:
    """The box head to accepted boxes in **page** pixels, descending confidence.

    `(N, 6)`: `x0 y0 x1 y1 conf cls`. `conf` is `obj * max(cls)` and `cls` is
    `argmax(cls)` kept as a float so the array stays one dtype - `RawRegion.kind`
    has no other source in the pipeline (amendment A-3). Anchors below
    `BOX_CONFIDENCE` are dropped, the survivors are clipped to the page, and
    greedy NMS at `NMS_IOU` reduces the duplicates.

    The anchor count is never assumed: the real graph gives 64512 rows and the
    unit tests give five.
    """
    width, height = page_size
    anchors = np.asarray(blk, dtype=np.float64).reshape(-1, blk.shape[-1])
    classes = anchors[:, 5:]
    confidence = anchors[:, 4] * classes.max(axis=1)

    accepted = confidence >= BOX_CONFIDENCE
    anchors, confidence, classes = anchors[accepted], confidence[accepted], classes[accepted]

    half_width, half_height = anchors[:, 2] / 2.0, anchors[:, 3] / 2.0
    x0 = np.clip((anchors[:, 0] - half_width - transform.pad_x) / transform.ratio, 0.0, width)
    x1 = np.clip((anchors[:, 0] + half_width - transform.pad_x) / transform.ratio, 0.0, width)
    y0 = np.clip((anchors[:, 1] - half_height - transform.pad_y) / transform.ratio, 0.0, height)
    y1 = np.clip((anchors[:, 1] + half_height - transform.pad_y) / transform.ratio, 0.0, height)

    decoded = np.stack([x0, y0, x1, y1, confidence, classes.argmax(axis=1)], axis=1)
    decoded = decoded[np.argsort(-confidence, kind="stable")]
    return decoded[_suppress_overlaps(decoded)].astype(np.float32).reshape(-1, 6)


def _suppress_overlaps(decoded: NDArray[np.float64]) -> list[int]:
    """Greedy non-maximum suppression over rows already sorted by confidence.

    Class-agnostic on purpose: two anchors on one bubble that disagree about its
    class are still one bubble, and the survivor's class is the more confident
    one's.
    """
    areas = (decoded[:, 2] - decoded[:, 0]) * (decoded[:, 3] - decoded[:, 1])
    kept: list[int] = []
    for index in range(len(decoded)):
        if all(_iou(decoded, areas, index, other) <= NMS_IOU for other in kept):
            kept.append(index)
    return kept


def _iou(decoded: NDArray[np.float64], areas: NDArray[np.float64], a: int, b: int) -> float:
    overlap_w = min(decoded[a, 2], decoded[b, 2]) - max(decoded[a, 0], decoded[b, 0])
    overlap_h = min(decoded[a, 3], decoded[b, 3]) - max(decoded[a, 1], decoded[b, 1])
    if overlap_w <= 0.0 or overlap_h <= 0.0:
        return 0.0
    overlap = float(overlap_w * overlap_h)
    return overlap / float(areas[a] + areas[b] - overlap)


def probability_to_page(
    seg: NDArray[np.float32],
    transform: LetterboxTransform,
    page_size: tuple[int, int],
) -> NDArray[np.float32]:
    """Crop the letterbox padding off `seg` and resize it to the page.

    Still a **probability** when it comes back: thresholding happens in
    `regions_from_detection`, after this resize and never before it (C-4 step 2).
    """
    width, height = page_size
    canvas = np.asarray(seg, dtype=np.float32).reshape(seg.shape[-2], seg.shape[-1])
    content = canvas[
        transform.pad_y : transform.pad_y + round(height * transform.ratio),
        transform.pad_x : transform.pad_x + round(width * transform.ratio),
    ]
    resized = cv2.resize(
        np.ascontiguousarray(content), (width, height), interpolation=cv2.INTER_LINEAR
    )
    return np.asarray(resized, dtype=np.float32)


def regions_from_detection(
    prob: NDArray[np.float32],
    boxes: NDArray[np.float32],
    page_size: tuple[int, int],
    *,
    threshold: float = MASK_THRESHOLD,
    dilate_iterations: int = DILATE_ITERATIONS,
) -> list[RawRegion]:
    """Steps 3 to 9 of the module docstring: a page map and its boxes to regions.

    `threshold` and `dilate_iterations` are parameters because AC-6 sweeps them;
    their defaults are the shipped constants, read at definition time, so a
    mutation of `MASK_THRESHOLD` still moves the default.
    """
    width, height = page_size
    if prob.shape != (height, width):
        raise ValueError(
            f"prob.shape is {tuple(prob.shape)}, which is not (height, width) ="
            f" {(height, width)} for page_size (width, height) = {(width, height)}"
        )

    fences = _integer_boxes(boxes, width, height)
    fence = np.zeros((height, width), dtype=bool)
    for x0, y0, x1, y1 in fences:
        fence[y0:y1, x0:x1] = True

    survivors = _components_above_floor(np.asarray(prob >= threshold) & fence)
    refenced = _dilate(survivors, dilate_iterations) & fence

    found: list[tuple[int, int, RawRegion]] = []
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        refenced.astype(np.uint8), connectivity=8
    )
    for label in range(1, count):
        if (
            int(stats[label, cv2.CC_STAT_WIDTH]) < _MIN_REGION_SIDE_PX
            or int(stats[label, cv2.CC_STAT_HEIGHT]) < _MIN_REGION_SIDE_PX
        ):
            continue
        component = labels == label
        found.append(
            (
                int(stats[label, cv2.CC_STAT_TOP]),
                int(stats[label, cv2.CC_STAT_LEFT]),
                _region(component, prob, boxes, fences),
            )
        )

    return [region for _y0, _x0, region in sorted(found, key=lambda entry: entry[:2])]


def _integer_boxes(
    boxes: NDArray[np.float32], width: int, height: int
) -> list[tuple[int, int, int, int]]:
    """Accepted boxes as half-open integer pixel ranges, clipped to the page."""
    rows = np.asarray(boxes, dtype=np.float64).reshape(-1, 6)
    return [
        (
            int(np.clip(np.floor(row[0]), 0, width)),
            int(np.clip(np.floor(row[1]), 0, height)),
            int(np.clip(np.floor(row[2]), 0, width)),
            int(np.clip(np.floor(row[3]), 0, height)),
        )
        for row in rows
    ]


def _components_above_floor(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Drop every 8-connected component smaller than `MIN_REGION_AREA_PX`.

    Applied to the **fenced** mask and before the dilation, which is what makes
    it a speckle floor rather than a size filter (amendment A-7).
    """
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    kept = [
        label
        for label in range(1, count)
        if int(stats[label, cv2.CC_STAT_AREA]) >= MIN_REGION_AREA_PX
    ]
    return np.isin(labels, kept)


def _dilate(mask: NDArray[np.bool_], iterations: int) -> NDArray[np.bool_]:
    if iterations <= 0:
        return mask
    kernel = np.ones((DILATE_KERNEL_SIDE, DILATE_KERNEL_SIDE), dtype=np.uint8)
    return np.asarray(cv2.dilate(mask.astype(np.uint8), kernel, iterations=iterations).astype(bool))


def _region(
    component: NDArray[np.bool_],
    prob: NDArray[np.float32],
    boxes: NDArray[np.float32],
    fences: list[tuple[int, int, int, int]],
) -> RawRegion:
    return RawRegion(
        polygon=_polygon(component),
        mask=_encode_one_bit_png(component),
        confidence=float(prob[component].mean()),
        kind=_kind(component, boxes, fences),
    )


def _polygon(component: NDArray[np.bool_]) -> tuple[tuple[int, int], ...]:
    """The component's outer contour as a closed ring of page pixel coordinates.

    Contour points are `numpy.int32`, which is not a subclass of `int` and which
    `json.dumps` refuses, so they are converted here rather than in the store.
    """
    contours, _hierarchy = cv2.findContours(
        component.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    ring = [(int(point[0][0]), int(point[0][1])) for point in max(contours, key=cv2.contourArea)]
    return (*ring, ring[0])


def _kind(
    component: NDArray[np.bool_],
    boxes: NDArray[np.float32],
    fences: list[tuple[int, int, int, int]],
) -> Literal["bubble", "box"]:
    """The class of the box that fenced this region, by greatest pixel overlap.

    Ties go to the lower row index, which is the more confident box:
    `decode_boxes` returns rows in descending confidence.
    """
    overlaps = [int(component[y0:y1, x0:x1].sum()) for x0, y0, x1, y1 in fences]
    index = max(range(len(overlaps)), key=lambda row: (overlaps[row], -row))
    return "bubble" if round(float(boxes[index][5])) == _BUBBLE_CLASS else "box"


def _encode_one_bit_png(mask: NDArray[np.bool_]) -> bytes:
    """`mask` as a PNG of bit depth 1 and colour type 0, the size of the page.

    Written with `zlib` and `struct` rather than through an imaging library so
    that "1-bit" is a property of the bytes this function emits and not of what
    an encoder chose - a mask widened to 8 bits is eight times the size of every
    page in the project file, and reads back looking identical.
    """
    height, width = mask.shape
    packed = np.packbits(mask.astype(np.uint8), axis=1)
    raw = b"".join(b"\x00" + row.tobytes() for row in packed)
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )
