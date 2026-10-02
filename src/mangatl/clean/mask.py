"""The erase mask: the only pixels cleaning may touch (MT-019 C-3, AC-1, AC-5).

The union of every region's own mask (`RawRegion.mask`, MT-007's 1-bit,
page-sized PNG - the detector's `seg` intersected with its accepted boxes, MT-002
E6), dilated once by an elliptical kernel of radius `MASK_DILATION_PX`. The array
is page-sized from the start, so `cv2.dilate` has no pixel outside the page to
set: that *is* "clipped to the page".
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from mangatl.domain.region import RawRegion

__all__ = ["MASK_DILATION_PX", "erase_mask"]

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


def erase_mask(regions: Sequence[RawRegion], page_size: tuple[int, int]) -> NDArray[np.bool_]:
    """The `(height, width)` boolean mask of pixels to erase on a `(width, height)` page.

    Raises `ValueError` naming the region's index if a decoded mask is not
    page-sized: a mask is never resized, transposed or cropped silently.
    """
    width, height = page_size
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
    # Read at call time, never bound at import: tests pin the disk per radius.
    radius = MASK_DILATION_PX
    if radius == 0:
        return union
    side = 2 * radius + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
    return np.asarray(cv2.dilate(union.astype(np.uint8), kernel), dtype=bool)
