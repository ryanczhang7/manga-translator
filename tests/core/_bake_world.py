"""A seeded chapter for MT-021's bake suites, and the bake area computed by hand.

Shared by `test_bake.py` (AC-1..AC-8, against `bake_chapter`) and
`test_cli_bake.py` (AC-9, through `mangatl.cli.main`). Nothing here imports
`mangatl.pipeline.bake`, `mangatl.typeset.render` or `mangatl.clean`, so every
helper can be driven in a plain interpreter while those modules do not exist -
which is how RED measured the negative controls recorded in the story.

**The bake area is computed from the pinned radius, not from `erase_mask`**
(MT-021 C-3). `PINNED_DILATION_PX` is the literal `2` of MT-019's
`MASK_DILATION_PX`, spelled out here, and the disk is `cv2`'s elliptical
structuring element of side `2r + 1` - the shape MT-019 C-3 names. A bake area
grown by the implementation is then disagreed with rather than agreed with by
construction.

**The cleaned page is built by the test, and it differs from the source inside
the erase mask** (`cleaned_from`): the source is a texture, the erase area of
the cleaned page is flat white. So "the output is the cleaned page" and "the
output is the source page" are different observations - an implementation that
composited onto the source fails - while outside the bake area the two agree,
which is what makes AC-2's complement assertion ("equals the source page
exactly") an assertion about the bake and not about this fixture.

Pages are small (at most 160x120) and masks are built with numpy and Pillow, not
`conftest.one_bit_png`'s per-pixel loop: there is no `pytest-timeout` in this
project, but the coverage gate runs this suite instrumented on CI.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.store.lines import commit_line
from mangatl.store.project import Project

#: MT-019 `MASK_DILATION_PX`, written out (C-3). Not imported: an implementation
#: that dilated by a different radius must disagree with this file.
PINNED_DILATION_PX = 2

#: The page every multi-region test bakes. Four regions, two of them able to hold
#: a short line at the minimum size; `OVERFLOW` is too small for anything long.
PAGE_W, PAGE_H = 160, 120

Rect = tuple[int, int, int, int]  # x0, y0, x1, y1, half-open


def ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    """A closed rectangular ring - RawRegion's polygon shape (MT-007 C-7)."""
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


#: Region polygons on the 160x120 page, in reading order. Each mask is a few
#: "stroke" rects strictly inside its polygon - a real mask hugs the Japanese
#: text and covers a small part of the bubble, so most of where English lands is
#: in the polygon fill and NOT in the mask (PO-5). An implementation that clipped
#: to the erase mask alone would cut most of every glyph away.
REGION_GEOMETRY: tuple[tuple[tuple[int, int, int, int], tuple[Rect, ...]], ...] = (
    ((6, 6, 78, 56), ((20, 14, 26, 48), (44, 14, 50, 48))),
    ((84, 6, 154, 56), ((100, 14, 106, 48), (130, 14, 136, 48))),
    ((6, 64, 78, 114), ((24, 72, 30, 106),)),
    ((96, 78, 132, 98), ((108, 84, 114, 92),)),  # OVERFLOW: small on purpose
)
OVERFLOW = 3


def mask_png(width: int, height: int, rects: Sequence[Rect]) -> bytes:
    """A page-sized 1-bit PNG with every half-open rect set (MT-007 C-7)."""
    bits = np.zeros((height, width), dtype=bool)
    for x0, y0, x1, y1 in rects:
        bits[y0:y1, x0:x1] = True
    buffer = BytesIO()
    Image.fromarray(bits).convert("1").save(buffer, format="PNG")
    return buffer.getvalue()


def regions(
    count: int = len(REGION_GEOMETRY), width: int = PAGE_W, height: int = PAGE_H
) -> tuple[RawRegion, ...]:
    """The first `count` regions of `REGION_GEOMETRY`, with real masks."""
    return tuple(
        RawRegion(
            polygon=ring(*box), mask=mask_png(width, height, rects), confidence=0.9, kind="bubble"
        )
        for box, rects in REGION_GEOMETRY[:count]
    )


def decode_mask(mask: bytes) -> NDArray[np.bool_]:
    with Image.open(BytesIO(mask)) as image:
        return np.asarray(image.convert("L")) != 0


def dilated_masks(page_regions: Sequence[RawRegion], size: tuple[int, int]) -> NDArray[np.bool_]:
    """MT-019's erase mask, from the pinned radius: union of masks, dilated."""
    width, height = size
    union = np.zeros((height, width), dtype=bool)
    for region in page_regions:
        union |= decode_mask(region.mask)
    side = 2 * PINNED_DILATION_PX + 1
    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
    return np.asarray(cv2.dilate(union.astype(np.uint8), disk), dtype=bool)


def bake_area(page_regions: Sequence[RawRegion], size: tuple[int, int]) -> NDArray[np.bool_]:
    """C-3's `A`: the dilated mask union, united with every polygon filled."""
    width, height = size
    filled = np.zeros((height, width), dtype=np.uint8)
    for region in page_regions:
        cv2.fillPoly(filled, [np.array(region.polygon, dtype=np.int32)], 1)
    return dilated_masks(page_regions, size) | filled.astype(bool)


def texture(width: int, height: int, salt: int = 0) -> NDArray[np.uint8]:
    """A deterministic RGB texture: no two neighbouring pixels alike, so a
    shifted, re-encoded or substituted page cannot coincide with it."""
    y, x = np.mgrid[0:height, 0:width]
    rgb = np.stack(
        [
            (x * 37 + y * 11 + salt * 7) % 200 + 20,
            (x * 13 + y * 29 + salt * 3) % 200 + 30,
            (x * 5 + y * 47 + salt) % 200 + 40,
        ],
        axis=-1,
    )
    return rgb.astype(np.uint8)


def cleaned_from(source: NDArray[np.uint8], page_regions: Sequence[RawRegion]) -> NDArray[np.uint8]:
    """What a cleaner would store: the source, flat white inside the erase mask."""
    height, width, _ = source.shape
    cleaned = source.copy()
    cleaned[dilated_masks(page_regions, (width, height))] = 255
    return cleaned


def encode(rgb: NDArray[np.uint8], fmt: str) -> bytes:
    buffer = BytesIO()
    image = Image.fromarray(rgb, "RGB")
    if fmt == "JPEG":
        image.save(buffer, format="JPEG", quality=90)
    else:
        image.save(buffer, format=fmt)
    return buffer.getvalue()


def decode_rgb(data: bytes) -> NDArray[np.uint8]:
    """C-5's decode, used for the source, the cleaned page and the output."""
    with Image.open(BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"))


# -- lines ---------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    """One region's line, as the pipeline and the user would have left it.

    `ocr_empty` makes the line `failed` whatever its proposal (MT-017 C-2);
    `commit` is a user act (`accepted`/`edited`/`reverted`) with its text.
    """

    proposed: str | None = None
    ocr_empty: bool = False
    commit: tuple[str, str | None] | None = None


def seed_page(
    project: Project,
    ordinal: int,
    page_regions: Sequence[RawRegion],
    specs: Sequence[Spec] | None,
    cleaned: bytes | None,
) -> None:
    """Regions, then lines (`None` = OCR never ran), then the cleaned image.

    The cleaned image goes last: `write_regions` invalidates it (MT-065 C-3).
    """
    project.write_regions(ordinal, page_regions)
    if specs is not None:
        project.write_lines(
            ordinal,
            [
                OcrResult(text="" if s.ocr_empty else "テキスト", ocr_empty=s.ocr_empty)
                for s in specs
            ],
        )
        project.write_proposed(
            ordinal, {i: s.proposed for i, s in enumerate(specs) if s.proposed is not None}
        )
        for i, s in enumerate(specs):
            if s.commit is not None:
                status, text = s.commit
                commit_line(project, ordinal, i, text, status)  # type: ignore[arg-type]
    if cleaned is not None:
        project.write_cleaned(ordinal, cleaned)


# -- folders -------------------------------------------------------------------


def output_dir_for(source_dir: Path) -> Path:
    """`<source>_en`, spelled out (architecture.md §5), never derived."""
    return source_dir.with_name(source_dir.name + "_en")


def contents(root: Path) -> list[str]:
    """Every path under `root`, relative and sorted - files, dirs and temps alike."""
    return sorted(entry.relative_to(root).as_posix() for entry in root.rglob("*"))


def snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256, or None for a directory (MT-006's shape)."""
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
