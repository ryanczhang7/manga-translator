"""The whole detect chain for one page: encoded bytes in, regions out (MT-035).

MT-007 shipped `letterbox`, `decode_boxes`, `probability_to_page`,
`regions_from_detection` and `integer_boxes`; MT-008 shipped `merge_columns`.
Each is correct and tested on its own, and until this module existed the only
place they were composed was a fixture in `tests/integration/`. This is that
composition, moved into shipped source so a caller can have the chain without
re-deriving it.

**The composition lives here because it may not live anywhere else** (MT-035
C-1, measured rather than assumed). `pyproject.toml`'s contract *"Only detect,
ocr and clean import onnxruntime"* is a `forbidden` contract that lists
`mangatl.pipeline` among its `source_modules` and sets no
`allow_indirect_imports`, so import-linter reports transitive chains - and every
module in `mangatl.detect` reaches `onnxruntime` through
`columns -> postprocess -> session`. `mangatl.detect` is therefore the only
package allowed to hold a function that names `DetectorSession`, and the stage
that calls this one takes it injected behind a plain `Callable`
(`pipeline.detect_stage.PageDetector`).

**The order of the seven steps is MT-007 C-4's, read out of `postprocess`'s
module docstring rather than re-derived.** Two of them are worth naming here
because getting either wrong produces masks that look plausible:

* `probability_to_page` crops the letterbox padding off the map *before*
  resizing it to the page, and `regions_from_detection` thresholds after that
  resize and never before it. A chain that resized without cropping lands a
  region's extent ~15 px out in y on a 4:3 page.
* `page_size` is `(width, height)` while a probability map's shape is
  `(height, width)`. `regions_from_detection` raises on a mismatch instead of
  transposing a page silently (MT-007 amendment A-6), so the reversal below is
  deliberate at every call site.

**This module does not order.** `architecture.md` §2 says `detect` "explicitly
does not own: reading order", and `merge_columns`' own docstring says its result
is bounding-box `(y0, x0)` order and not a reading order. Reading order is
`domain.reading_order`'s, applied by the stage.

Production wiring, which no module in `src` performs today (MT-035
`## Out of scope`): `partial(detect_page_regions, load_detector(path, providers))`.
"""

from __future__ import annotations

from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from mangatl.detect.columns import merge_columns
from mangatl.detect.postprocess import (
    decode_boxes,
    integer_boxes,
    letterbox,
    probability_to_page,
    regions_from_detection,
)

# Imported at runtime rather than under a `TYPE_CHECKING` guard. The guard costs
# an uncovered branch in a package the `coverage` gate reads, and
# `domain/events.py` records that this project would rather pay the import -
# which here is free, because `postprocess` already imports both.
from mangatl.detect.session import DetectorSession
from mangatl.domain.region import RawRegion

__all__ = ["detect_page_regions"]


def detect_page_regions(
    session: DetectorSession,
    image_bytes: bytes,
) -> list[RawRegion]:
    """One page's encoded image to its regions, in `merge_columns`' order.

    `session` comes first because that is the argument a caller binds once:
    `partial(detect_page_regions, session)` is a `PageDetector`, which is what
    the stage wants (MT-035 C-3). The only thing asked of it is `run`.

    The return is `merge_columns`' bounding-box `(y0, x0)` order, **not** reading
    order - see the module docstring.
    """
    page = _decoded_page(image_bytes)
    height, width = page.shape[:2]
    page_size = (width, height)

    canvas, transform = letterbox(page)
    raw = session.run(canvas)

    boxes = decode_boxes(raw.blk, transform, page_size)
    prob = probability_to_page(raw.seg, transform, page_size)
    regions = regions_from_detection(prob, boxes, page_size)
    return merge_columns(regions, integer_boxes(boxes, width, height))


def _decoded_page(image_bytes: bytes) -> NDArray[np.uint8]:
    """`image_bytes` as an `(height, width, 3)` RGB `uint8` array.

    **`.convert("RGB")` is load-bearing** (MT-035 amendment R-2, reproduced
    twice). A greyscale scan - which for manga is not the corner case - decodes
    to PIL mode `L`, `np.asarray` of it is two-dimensional, and `letterbox`'s
    `canvas[y0:y1, x0:x1] = resized` then raises
    `ValueError: could not broadcast input array from shape (680,1024) into
    shape (680,1024,3)`. The spike corpus happens to decode as RGB, so a user's
    scan would have found this and the corpus would not.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)
