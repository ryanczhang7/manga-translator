"""`mangatl.clean.page.clean_page_image`: the cleaner the composition root binds (MT-065 C-4).

One page's encoded image and its regions in, the cleaned page out as PNG bytes.
The four steps are C-4's - decode with `.convert("RGB")`, MT-019's
`erase_mask`, MT-019's `clean_page`, encode as PNG - and **the oracle is read
out of MT-019, never re-derived** (C-8, AC-1 "settled"): the decoded output
must equal `clean_page(decoded_source, erase_mask(regions, size), session)`
called directly with an identical fake. Nothing here re-implements inpainting.

**The fake inverts** (`_InvertingSession`): it returns `255 - 255 * image`,
which differs from the input at every pixel (`255 - v == v` has no integer
solution). So the oracle is not the identity - inside the erase mask the
cleaned page differs from the source everywhere - and "outside the mask the
output is byte-identical to the source" is a statement about the encode, not
about a fake that changed nothing. The same discriminating choice MT-019's
`test_clean_inpaint.py` made, for the same reason.

**The page encodes its own coordinates** (`_coded_page`), so a lossy encode
moves pixels: JPEG on a uniform page could round-trip exactly and hide DV-8's
mutation. The lossless test below is the one DV-8 (`format="PNG"` ->
`format="JPEG"`) must turn red.

**Timing.** No `pytest-timeout` in this project. Every page is 64x48 and every
component takes the native path, one 512x512 float call each.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from io import BytesIO

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.clean.inpaint import clean_page
from mangatl.clean.mask import erase_mask
from mangatl.clean.page import clean_page_image
from mangatl.domain.region import RawRegion

_WIDTH, _HEIGHT = 64, 48

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass
class _InvertingSession:
    """An `InpaintSession` returning `255 - 255 * image` in model scale (C-2),
    and counting its calls."""

    calls: int = 0
    shapes: list[tuple[int, ...]] = field(default_factory=list)

    def run(self, image: NDArray[np.float32], mask: NDArray[np.float32]) -> NDArray[np.float32]:
        self.calls += 1
        self.shapes.append(tuple(image.shape))
        return (255.0 - 255.0 * image).astype(np.float32)

    def get_providers(self) -> Sequence[str]:
        return ["CPUExecutionProvider"]


def _coded_page(width: int = _WIDTH, height: int = _HEIGHT) -> NDArray[np.uint8]:
    """An RGB page whose every pixel encodes its own `(x, y)`."""
    ys, xs = np.mgrid[0:height, 0:width]
    page = np.empty((height, width, 3), dtype=np.uint8)
    page[..., 0] = (xs * 4) % 256
    page[..., 1] = (ys * 5) % 256
    page[..., 2] = (xs * 3 + ys * 7) % 256
    return page


def _encode(page: NDArray[np.uint8], fmt: str = "PNG", mode: str = "RGB") -> bytes:
    buffer = BytesIO()
    Image.fromarray(page, mode=mode).save(buffer, format=fmt)
    return buffer.getvalue()


def _decode(image_bytes: bytes) -> NDArray[np.uint8]:
    with Image.open(BytesIO(image_bytes)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@pytest.fixture
def regions(one_bit_png: Callable[..., bytes]) -> tuple[RawRegion, ...]:
    """Two regions with page-sized masks, apart from each other: two
    components, two model calls."""
    return (
        RawRegion(
            polygon=_ring(40, 6, 56, 20),
            mask=one_bit_png(_WIDTH, _HEIGHT, [(42, 8, 54, 18)]),
            confidence=0.5,
            kind="bubble",
        ),
        RawRegion(
            polygon=_ring(4, 26, 20, 42),
            mask=one_bit_png(_WIDTH, _HEIGHT, [(6, 28, 18, 40)]),
            confidence=0.75,
            kind="box",
        ),
    )


# -- the module's shape --------------------------------------------------------


def test_the_module_exports_the_cleaner_and_nothing_else() -> None:
    import mangatl.clean.page as module

    assert module.__all__ == ["clean_page_image"]


# -- AC-1: the composed cleaner is MT-019's, through a lossless encode ---------


def test_the_cleaned_page_is_mt019s_clean_page_of_the_decoded_source_and_its_erase_mask(
    regions: tuple[RawRegion, ...],
) -> None:
    """**AC-1**, settled half (C-8): the decoded output equals `clean_page`
    on the decoded source and `erase_mask(regions, (width, height))`, run
    directly with an identical fake. Exact equality, no tolerance."""
    page = _coded_page()
    session = _InvertingSession()

    cleaned = clean_page_image(session, _encode(page), regions)

    expected = clean_page(page, erase_mask(regions, (_WIDTH, _HEIGHT)), _InvertingSession())
    assert np.array_equal(_decode(cleaned), expected), (
        "the composed cleaner's output is not MT-019's clean_page of the decoded"
        " page and the erase mask of its regions"
    )
    assert session.calls >= 1, "the session handed to the cleaner was never run"


def test_the_cleaned_page_is_a_png_the_size_of_the_source(
    regions: tuple[RawRegion, ...],
) -> None:
    """C-4 step 4: PNG, never JPEG; the size is the page's (AC-1)."""
    cleaned = clean_page_image(_InvertingSession(), _encode(_coded_page()), regions)

    assert cleaned[:8] == _PNG_SIGNATURE, "the cleaned page is not PNG-encoded"
    with Image.open(BytesIO(cleaned)) as image:
        assert image.size == (_WIDTH, _HEIGHT)
        assert image.mode == "RGB"


def test_every_pixel_outside_the_erase_mask_survives_the_encode_byte_for_byte(
    regions: tuple[RawRegion, ...],
) -> None:
    """MT-019 AC-4 must survive the encode (C-4, C-8): outside the erase mask
    the decoded output is the decoded source exactly. Inside it, the inverting
    fake guarantees a difference at every pixel - the control that the
    comparison is not between two copies of the source. DV-8 turns this red."""
    page = _coded_page()
    mask = erase_mask(regions, (_WIDTH, _HEIGHT))

    decoded = _decode(clean_page_image(_InvertingSession(), _encode(page), regions))

    changed_outside = int(np.count_nonzero((decoded != page).any(axis=2) & ~mask))
    assert changed_outside == 0, (
        f"{changed_outside} pixels outside the erase mask differ from the source;"
        " the encode is lossy or the write-back leaked"
    )
    unchanged_inside = int(np.count_nonzero((decoded == page).all(axis=2) & mask))
    assert unchanged_inside == 0, f"{unchanged_inside} erase-mask pixels were not inpainted"
    assert int(mask.sum()) > 0


def test_a_greyscale_source_page_is_cleaned_as_rgb(
    regions: tuple[RawRegion, ...],
) -> None:
    """C-4 step 1, MT-035 R-2: a greyscale scan decodes to mode `L`, and
    `clean_page` refuses a 2-D array, so the decode must `.convert("RGB")`."""
    grey = _coded_page()[..., 0].copy()
    source = _encode(grey, mode="L")
    as_rgb = _decode(source)

    cleaned = clean_page_image(_InvertingSession(), source, regions)

    expected = clean_page(as_rgb, erase_mask(regions, (_WIDTH, _HEIGHT)), _InvertingSession())
    assert np.array_equal(_decode(cleaned), expected)


def test_a_jpeg_source_page_is_cleaned_from_its_decoded_pixels(
    regions: tuple[RawRegion, ...],
) -> None:
    """The fixture scans are JPEGs. Outside the mask the output is the JPEG's
    *decoded* pixels exactly - lossless with respect to what it stands for."""
    source = _encode(_coded_page(), fmt="JPEG")
    decoded_source = _decode(source)

    cleaned = clean_page_image(_InvertingSession(), source, regions)

    expected = clean_page(
        decoded_source, erase_mask(regions, (_WIDTH, _HEIGHT)), _InvertingSession()
    )
    assert np.array_equal(_decode(cleaned), expected)


def test_with_no_regions_the_page_comes_back_unchanged_without_calling_the_session() -> None:
    """C-4: callable with no regions (`CleanStage` never does so - AC-2)."""
    page = _coded_page()
    session = _InvertingSession()

    cleaned = clean_page_image(session, _encode(page), ())

    assert session.calls == 0
    assert np.array_equal(_decode(cleaned), page)


def test_every_model_call_is_c2s_fixed_512_input(regions: tuple[RawRegion, ...]) -> None:
    """The session is the one handed in, called through `clean_page`'s own
    windowing: one call per component, each `(1, 3, 512, 512)`."""
    session = _InvertingSession()

    clean_page_image(session, _encode(_coded_page()), regions)

    assert session.shapes == [(1, 3, 512, 512)] * 2
