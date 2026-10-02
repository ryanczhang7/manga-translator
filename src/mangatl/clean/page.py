"""One page's encoded image and its regions in, the cleaned page out (MT-065 C-4).

The cleaner the composition root binds: `partial(clean_page_image, session)` is
a `pipeline.clean_stage.PageCleaner`, the pattern of
`detect.page.detect_page_regions` and `ocr.page.transcribe_page_regions` -
the session first, and the decode belonging to the adapter, so that `pipeline`
handles bytes and never imports numpy, PIL or the inference runtime.

Four steps and nothing else: decode, MT-019's `erase_mask`, MT-019's
`clean_page`, encode. **The encode is PNG, never JPEG**: MT-019 AC-4's byte
identity outside the mask has to survive it, and a lossy encode would move
every pixel of the page the cleaner did not touch.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from mangatl.clean.inpaint import clean_page
from mangatl.clean.mask import erase_mask
from mangatl.clean.session import InpaintSession
from mangatl.domain.region import RawRegion

__all__ = ["clean_page_image"]


def clean_page_image(
    session: InpaintSession, image_bytes: bytes, regions: Sequence[RawRegion]
) -> bytes:
    """One page's encoded image and its regions in, the cleaned page out as PNG bytes.

    With no regions the mask is all `False`, `clean_page` does not call the
    session, and the page comes back re-encoded; `CleanStage` never calls it so
    (AC-2), storing the source bytes instead.
    """
    page = _decoded_page(image_bytes)
    height, width = page.shape[:2]
    mask = erase_mask(regions, (width, height))
    cleaned = clean_page(page, mask, session)
    buffer = BytesIO()
    Image.fromarray(cleaned, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _decoded_page(image_bytes: bytes) -> NDArray[np.uint8]:
    """`image_bytes` as an `(height, width, 3)` RGB `uint8` array.

    **`.convert("RGB")` is load-bearing** (MT-035 amendment R-2): a greyscale
    scan decodes to mode `L`, and `clean_page` refuses a 2-D array. Not shared
    with `detect.page._decoded_page`: `clean` may not import `detect`.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)
