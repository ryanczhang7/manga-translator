"""The crop handed to the OCR encoder, and the tensor it is turned into.

Two rules, both of them about what this module must *not* do.

**It does not rotate, deskew or transpose** (MT-010 AC-1/C-2). `manga-ocr` is
trained on manga crops in their native orientation - vertical columns included -
so `stack.md` §5/O6 handles vertical Japanese by *model choice*, and the failure
mode it names is a helpful pre-processing step that turns readable input into
out-of-distribution garbage. `crop_for_region` is therefore a slice of the page
and nothing else, and `tests/integration/test_ocr_session.py` measures what
rotating costs: the same nine crops turned 90 degrees score a mean character
accuracy of 0.0947 against 1.0000 upright.

**It does not preserve aspect ratio** (MT-010 AC-2, as amended by A-1). The
export ships its own `preprocessor_config.json`:

    {"image_processor_type": "ViTImageProcessor", "do_resize": true,
     "size": {"height": 224, "width": 224},
     "image_mean": [0.5,0.5,0.5], "image_std": [0.5,0.5,0.5], "resample": 2}

A `ViTImageProcessor` given an explicit height *and* width resizes to exactly
that and does not letterbox, so upstream trains and infers by **stretching** and
a stretched column is in distribution while a padded one is not. There is no
`PAD_VALUE` here and there must not be one. That is the same argument as the
no-rotation rule above - do not help the model with pre-processing it was not
trained on - and it reaches the opposite conclusion from
`detect.postprocess.letterbox`, which remains right for the *detector*, whose
graph is a square-input YOLO trained on letterboxed pages.

`resample: 2` is PIL's `BILINEAR`, and `img.convert("L").convert("RGB")` before
the resize is upstream's own (`spikes/MT-002/ocr.py`, the script that scored
10/12 against the author's ground truth). Both are reproduced exactly, because
every accuracy number in `docs/wiki/audits/MT-002-model-runtime.md` was measured
through them.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from mangatl.domain.region import RawRegion

__all__ = [
    "CROP_PADDING_PX",
    "MODEL_INPUT_SIZE",
    "PIXEL_MEAN",
    "PIXEL_STD",
    "crop_for_region",
    "to_model_input",
]

#: Pixels added on every side of a region's bounding box before the crop is
#: taken, **in page pixels at a scan width of 1125** - the resolution of every
#: page under `spikes/MT-002/pages/`, which is the only resolution this corpus
#: has (MT-010 C-6). It scales with the scan, so a 300-dpi rescan would want it
#: re-measured rather than inherited.
#:
#: A margin, not a second detector. RED measured the nine boxes the real detector
#: finds on `014.jpg` at 52-194 px wide and transcription **byte-identical at 0,
#: 4 and 8 px** of padding on all nine, so this value is chosen from the middle
#: of a measured plateau; at 48 px the narrowest box would grow to 148 and
#: swallow its neighbouring column.
CROP_PADDING_PX: int = 4

#: `(width, height)`, from the export's `preprocessor_config.json` and confirmed
#: by the encoder's own signature: `last_hidden_state [batch, 197, 768]`, and
#: 197 is `(224/16)^2 + 1` - the DeiT patch grid plus its class token. So 224 is
#: fixed by the graph rather than configurable.
MODEL_INPUT_SIZE: tuple[int, int] = (224, 224)

#: `image_mean` and `image_std` from the same file: the normalisation is
#: `(x / 255 - 0.5) / 0.5`, which takes [0, 255] onto [-1, 1].
PIXEL_MEAN: float = 0.5
PIXEL_STD: float = 0.5


def crop_for_region(page: NDArray[np.uint8], region: RawRegion) -> NDArray[np.uint8]:
    """The page's own pixels under `region`, padded by `CROP_PADDING_PX` and
    clipped to the page.

    The extent is the **polygon's bounding box**, not its first two vertices: a
    region's ring can be any shape the detector traced, and a crop taken from two
    of its vertices is a different rectangle.

    Clipping is `max(0, ...)` and `min(edge, ...)` rather than a bare slice, and
    that is not defensive style. A region flush against an edge is ordinary - the
    detector clips its own boxes to the page - and `page[-2:6]` is *empty* rather
    than out of range, so an unclipped negative start produces a wrong-sized crop
    with no exception anywhere.

    Returns a **copy**. A numpy slice is a view onto its base, and the scans are
    read-only to this app (`architecture.md` §5): a page array is handed to nine
    regions in a row, and "nothing writes through the crop today" is not a
    property a user's only copy of a scan should depend on.
    """
    height, width = page.shape[:2]
    xs = [x for x, _y in region.polygon]
    ys = [y for _x, y in region.polygon]
    x0 = max(0, min(xs) - CROP_PADDING_PX)
    y0 = max(0, min(ys) - CROP_PADDING_PX)
    x1 = min(width, max(xs) + CROP_PADDING_PX)
    y1 = min(height, max(ys) + CROP_PADDING_PX)
    return page[y0:y1, x0:x1].copy()


def to_model_input(crop: NDArray[np.uint8], size: tuple[int, int]) -> NDArray[np.float32]:
    """`crop` as the encoder's `pixel_values`: `(1, 3, height, width)` float32 in
    [-1, 1].

    Three steps, in upstream's order, none of them this project's invention:

    1. `convert("L").convert("RGB")` - the encoder never sees colour, so the
       three channels come out equal. Every number MT-002 E5 measured was
       measured through this.
    2. `resize(size, BILINEAR)` - straight to `size`, aspect ratio not preserved
       (AC-2 as amended by A-1). `size` is `(width, height)`, which is PIL's
       order and `MODEL_INPUT_SIZE`'s.
    3. `(x / 255 - PIXEL_MEAN) / PIXEL_STD`, then `HWC -> CHW` with a batch axis.
    """
    image = Image.fromarray(crop)
    resized = image.convert("L").convert("RGB").resize(size, Image.Resampling.BILINEAR)
    pixels = np.asarray(resized, dtype=np.float32) / 255.0
    normalised = (pixels - PIXEL_MEAN) / PIXEL_STD
    return np.ascontiguousarray(normalised.transpose(2, 0, 1)[None], dtype=np.float32)
