"""Baking a chapter: every page, finished, written to the sibling output folder.

MT-021 C-3..C-6. For each page, in the chapter's reading order:

| Page | Bytes written |
|---|---|
| no regions | the source file's bytes, verbatim |
| regions, no cleaned image | the source file's bytes, verbatim; counted in `pages_uncleaned` |
| regions and a cleaned image | `bake_page(cleaned, blocks, bake area)`, in the source's format |

The **bake area** is MT-019's erase mask united with every region's polygon
filled (C-3): the cleaner touches the dilation ring, and English is fitted
inside the polygon, whose fill covers the holes in a mask. Ink is clipped to it,
so an overflowed block never reaches the art.

**Written atomically, kept from MT-006.** The output folder is created if absent
and emptied first - "overwritten on each bake" (`architecture.md` §5), which is
also how a page that no longer exists is removed. Each page goes to a `.part`
temp inside the output folder and is renamed onto its name with `os.replace`,
called as an attribute of `os` so a test patching it reaches this call. The temp
is removed in a `finally`. Any exception propagates unwrapped: no report is
returned for a failed bake, and what was written before it stays whole.

The source folder is only ever read (AC-7).

**Before the bake** (MT-066 C-1), `preview_bake` states what the Render dialog
says: the output folder, the page count, and which lines are unreviewed,
`failed` or overflowing. It only reads. Which lines get set - and so which can
overflow - is decided by `_set_blocks`, the one rule `bake_chapter` sets them
by, so the dialog and the output cannot disagree.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from mangatl.app_paths import settings_path
from mangatl.clean.mask import erase_mask
from mangatl.domain.line import Line, effective_text
from mangatl.domain.region import RawRegion
from mangatl.store.lines import read_review_lines
from mangatl.store.project import Project
from mangatl.store.settings import lettering_font_dir
from mangatl.typeset.fit import TypesetBlock, typeset
from mangatl.typeset.font import FONT_FAMILY, Faces, FallbackReason, load_faces
from mangatl.typeset.render import bake_page
from mangatl.typeset.resolve import FaceResolution, resolve_faces

__all__ = [
    "BakePreview",
    "BakeReport",
    "LineRef",
    "bake_chapter",
    "output_dir_for",
    "preview_bake",
]

#: `<source>_en` (`architecture.md` §5).
_OUTPUT_SUFFIX = "_en"

#: Suffix of the half-written file, inside the output folder so that
#: `os.replace` stays a same-filesystem rename.
_TEMP_SUFFIX = ".part"

#: C-5: a baked JPEG keeps its name at the cost of one lossy encode (PO-1).
_JPEG_QUALITY = 95
_JPEG_SUBSAMPLING_444 = 0


@dataclass(frozen=True)
class BakeReport:
    """What a finished bake did. `pages_written` is every page of the chapter."""

    pages_written: int
    regions_empty: int
    unreviewed_lines: int
    pages_uncleaned: int
    #: MT-027 AC-7: the family the chapter was lettered in, and - when a
    #: configured font folder could not be used - why. The defaults are "no
    #: override, nothing went wrong", so a report of the four counts alone
    #: still means what it meant before.
    font_family: str = FONT_FAMILY
    font_fallback: FallbackReason = "none"
    font_detail: str = ""


@dataclass(frozen=True)
class LineRef:
    """One line of the chapter: its page's 0-based ordinal and its 0-based
    place in reading order."""

    page_ordinal: int
    reading_index: int


@dataclass(frozen=True)
class BakePreview:
    """What a bake of the chapter would do, stated before it runs (MT-066 C-1).

    Every tuple is in `(page_ordinal, reading_index)` order. `unreviewed`
    agrees with `BakeReport.unreviewed_lines`, and `page_count` with
    `BakeReport.pages_written`.
    """

    output_dir: Path
    page_count: int
    total_lines: int
    unreviewed: tuple[LineRef, ...]
    failed: tuple[LineRef, ...]
    overflowing: tuple[LineRef, ...]


def output_dir_for(source_dir: Path) -> Path:
    """The folder a chapter bakes into: `<source>_en`, beside the source."""
    return source_dir.with_name(source_dir.name + _OUTPUT_SUFFIX)


def preview_bake(project: Project) -> BakePreview:
    """State what `bake_chapter` would do to `project`, writing nothing.

    A line overflows when `bake_chapter` would set it (`_set_blocks`) and its
    block does not fit; a line on an uncleaned page is never set, so never
    overflows.

    Lines are measured in the faces the settings name when the call starts
    (MT-027 PO-3), as `bake_chapter` would letter them.
    """
    faces = _resolve_faces().faces
    pages = project.pages()
    total = 0
    unreviewed: list[LineRef] = []
    failed: list[LineRef] = []
    overflowing: list[LineRef] = []
    for page in pages:
        page_regions = project.read_regions(page.ordinal)
        lines = read_review_lines(project, page.ordinal)
        present = [(index, line) for index, line in enumerate(lines) if line is not None]
        total += len(present)
        unreviewed += [LineRef(page.ordinal, i) for i, line in present if line.status == "proposed"]
        failed += [LineRef(page.ordinal, i) for i, line in present if line.status == "failed"]
        if page_regions and project.has_cleaned(page.ordinal):
            overflowing += [
                LineRef(page.ordinal, index)
                for index, block in _set_blocks(page_regions, lines, faces)
                if block.overflowed
            ]
    return BakePreview(
        output_dir=output_dir_for(project.chapter.source_dir),
        page_count=len(pages),
        total_lines=total,
        unreviewed=tuple(unreviewed),
        failed=tuple(failed),
        overflowing=tuple(overflowing),
    )


def bake_chapter(project: Project, output_dir: Path) -> BakeReport:
    """Bake every page of `project` into `output_dir`, emptied first.

    `unreviewed_lines` counts every `proposed` line in the chapter;
    `regions_empty` counts regions left without text on pages actually baked
    (C-4, PO-6). Exceptions - an `OSError`, a `MissingGlyph` - propagate.

    The faces are resolved once, before anything is written, and letter every
    page and region (MT-027 AC-8); a configured font folder that cannot be
    used falls back to the shipped faces and is recorded on the report, never
    raised (AC-7).
    """
    resolution = _resolve_faces()
    faces = resolution.faces
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    source_dir = project.chapter.source_dir
    written = regions_empty = unreviewed = uncleaned = 0
    for page in project.pages():
        page_regions = project.read_regions(page.ordinal)
        lines = read_review_lines(project, page.ordinal)
        unreviewed += sum(1 for line in lines if line is not None and line.status == "proposed")
        payload = (source_dir / page.filename).read_bytes()
        cleaned = project.read_cleaned(page.ordinal) if page_regions else None
        if page_regions and cleaned is None:
            uncleaned += 1
        if cleaned is not None:
            blocks = [block for _, block in _set_blocks(page_regions, lines, faces)]
            regions_empty += len(page_regions) - len(blocks)
            payload = _bake(cleaned, page_regions, blocks, page.filename)
        _write_atomically(output_dir / page.filename, payload)
        written += 1

    return BakeReport(
        pages_written=written,
        regions_empty=regions_empty,
        unreviewed_lines=unreviewed,
        pages_uncleaned=uncleaned,
        font_family=resolution.family,
        font_fallback=resolution.fallback,
        font_detail=resolution.detail,
    )


def _resolve_faces() -> FaceResolution:
    """The faces `settings.json` names, read now (MT-027 PO-1).

    A settings file that cannot be read is a loud fallback, reusing
    `missing_path` (row 1b, PO-4): the shipped faces, and the reason why.
    """
    configured = lettering_font_dir(settings_path())
    if isinstance(configured, str):
        return FaceResolution(load_faces(), "default", FONT_FAMILY, "missing_path", configured)
    return resolve_faces(configured)


def _set_blocks(
    page_regions: Sequence[RawRegion], lines: Sequence[Line | None], faces: Faces
) -> list[tuple[int, TypesetBlock]]:
    """`(reading_index, block)` for each region with text to set, in reading
    order (C-4). The one rule for which lines a bake sets: `preview_bake`'s
    overflow count reads it too (MT-066 C-1)."""
    return [
        (index, typeset(effective_text(line), region.polygon, faces))
        for index, (region, line) in enumerate(zip(page_regions, lines, strict=True))
        if line is not None and line.status != "failed" and effective_text(line).strip()
    ]


def _bake_area(page_regions: Sequence[RawRegion], size: tuple[int, int]) -> NDArray[np.bool_]:
    """C-3: the erase mask united with every region's polygon, filled."""
    width, height = size
    filled = np.zeros((height, width), dtype=np.uint8)
    for region in page_regions:
        cv2.fillPoly(filled, [np.array(region.polygon, dtype=np.int32)], 1)
    return np.asarray(erase_mask(page_regions, size) | filled.astype(bool))


def _bake(
    cleaned: bytes,
    page_regions: Sequence[RawRegion],
    blocks: Sequence[TypesetBlock],
    filename: str,
) -> bytes:
    """The cleaned page with `blocks` composited, encoded as `filename`'s format (C-5)."""
    with Image.open(BytesIO(cleaned)) as image:
        rgb = np.asarray(image.convert("RGB"))
    height, width, _ = rgb.shape
    baked = bake_page(rgb, blocks, _bake_area(page_regions, (width, height)))
    buffer = BytesIO()
    if Path(filename).suffix.lower() == ".png":
        Image.fromarray(baked, "RGB").save(buffer, format="PNG")
    else:
        # Intake accepts only PAGE_SUFFIXES, so anything else is .jpg/.jpeg.
        Image.fromarray(baked, "RGB").save(
            buffer, format="JPEG", quality=_JPEG_QUALITY, subsampling=_JPEG_SUBSAMPLING_444
        )
    return buffer.getvalue()


def _write_atomically(destination: Path, payload: bytes) -> None:
    """Write `payload` to a temp file beside `destination`, then rename onto it."""
    temporary = destination.with_name(destination.name + _TEMP_SUFFIX)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        # A no-op after a successful rename, the cleanup after a failed one.
        temporary.unlink(missing_ok=True)
