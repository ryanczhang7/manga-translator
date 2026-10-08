"""A small benchmark chapter for MT-023's S2 suites: geometry, glyphs, cleanings.

Shared by `test_bench_recall.py`, `test_bench_residual.py` and
`test_bench_s2.py`. Nothing here imports `mangatl.bench.recall`,
`mangatl.bench.residual` or `mangatl.bench.s2`, so every helper can be driven in
a plain interpreter while those modules do not exist - which is how RED measured
the control values recorded in the story's `## Handoff`.

**The page.** Two 200 x 200 pages. Each carries `PER_PAGE` = 3 truth regions,
`TRUTH_RECTS`: 40 x 40 px squares (corners inclusive, as Pillow's polygon fill
is) along the top, 20 px apart and 10 px from the page edge. 1,600 px each, so a
proposal mask of exactly 800 px inside one sits at IoU exactly 0.5 and one of 799
px just below it. The bottom half (y >= 100) holds nothing and is where
spurious proposals go.

**The glyphs.** Every truth region of the *source scan* holds glyph-like
strokes, `GLYPH_STROKES`: black (luma 0) 1-3 px bars and lines drawn with
`PIL.ImageDraw` on white, inset 4 px from the region's edge so no stroke touches
it. Thin and dense, because the ink metric counts a stroke's edge band, not its
area (MT-023 `## Contract` block 2). Page 1's strokes are page 0's shifted one
pixel right, so the two scans differ (distinct sha256) and still hold the same
amount of ink.

**The cleanings** (`cleaned_page`) replace each truth polygon's pixels exactly:
`WHITE` (255, a correct clean), `FLAT_GREY` (128, AC-6's flat mid-grey - inside
the luma band on purpose) or nothing written at all (AC-5: the source scan is
what gets measured).
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Iterable, Mapping, Sequence
from io import BytesIO
from pathlib import Path

import _bake_world as world
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from mangatl.bench.seed import seed_ground_truth
from mangatl.bench.truth import GroundTruth, dump_ground_truth, load_ground_truth, truth_path_for
from mangatl.domain.page import Chapter
from mangatl.domain.region import RawRegion
from mangatl.store.project import Project, create_project, project_dir_for

W, H = 200, 200
CHAPTER = "chapter-s2"
FILENAMES = ("001.png", "002.png")
PER_PAGE = 3
GROUND_TRUTH = len(FILENAMES) * PER_PAGE

Rect = tuple[int, int, int, int]  # x0, y0, x1, y1 - INCLUSIVE corners

#: Three 40 x 40 px squares per page, inclusive corners.
TRUTH_RECTS: tuple[Rect, ...] = tuple((10 + 60 * c, 10, 49 + 60 * c, 49) for c in range(PER_PAGE))
REGION_AREA = 40 * 40

WHITE = 255
#: AC-6's fill. Below `INK_LUMA_MAX` (160) so the luma test passes it, and at
#: least `INK_CONTRAST_MIN` (64) below paper white, so a "difference from paper"
#: metric counts every pixel of it. Only local contrast can score it zero.
FLAT_GREY = 128

#: Strokes inside one region, relative to the region's top-left corner, as
#: inclusive `(x0, y0, x1, y1)` boxes, all within `4..35` of a 40 px region:
#: five 2 px vertical bars, four 1 px horizontal lines, one 3 px block stroke.
GLYPH_STROKES: tuple[Rect, ...] = (
    (6, 5, 7, 34),
    (13, 5, 14, 20),
    (20, 8, 21, 34),
    (27, 5, 28, 26),
    (33, 12, 34, 34),
    (4, 9, 35, 9),
    (4, 17, 30, 17),
    (8, 25, 35, 25),
    (4, 31, 26, 31),
    (9, 13, 11, 15),
)


def ring(rect: Rect) -> tuple[tuple[int, int], ...]:
    return world.ring(*rect)


def shifted(rect: Rect, dx: int, dy: int) -> Rect:
    x0, y0, x1, y1 = rect
    return (x0 + dx, y0 + dy, x1 + dx, y1 + dy)


def spurious_rects(count: int) -> list[Rect]:
    """`count` 2 x 2 px squares in the bottom half (y >= 100): IoU 0 with every truth region."""
    assert count <= 1000
    return [
        (4 * (k % 50), 100 + 5 * (k // 50), 4 * (k % 50) + 1, 101 + 5 * (k // 50))
        for k in range(count)
    ]


def region(rect: Rect, mask_rects: Sequence[Rect] | None = None) -> RawRegion:
    """A proposal whose polygon is `rect` and whose mask is `mask_rects` (default:
    exactly `rect`'s inclusive pixels). Mask rects are INCLUSIVE here too."""
    rects = [rect] if mask_rects is None else list(mask_rects)
    return RawRegion(
        polygon=ring(rect),
        mask=world.mask_png(W, H, [(x0, y0, x1 + 1, y1 + 1) for x0, y0, x1, y1 in rects]),
        confidence=0.9,
        kind="bubble",
    )


def regions(rects: Iterable[Rect]) -> list[RawRegion]:
    return [region(rect) for rect in rects]


def baseline() -> list[RawRegion]:
    """One exact proposal per truth region of a page, in truth order."""
    return regions(TRUTH_RECTS)


def draw_glyphs(image: Image.Image, rects: Iterable[Rect], dx: int = 0) -> None:
    """Black glyph strokes inside each of `rects` (inclusive region corners)."""
    draw = ImageDraw.Draw(image)
    for x0, y0, _x1, _y1 in rects:
        for sx0, sy0, sx1, sy1 in GLYPH_STROKES:
            draw.rectangle((x0 + sx0 + dx, y0 + sy0, x0 + sx1 + dx, y0 + sy1), fill=(0, 0, 0))


def png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def source_image(ordinal: int) -> Image.Image:
    """The scan of page `ordinal`: white paper, glyphs in every truth region."""
    image = Image.new("RGB", (W, H), (WHITE, WHITE, WHITE))
    draw_glyphs(image, TRUTH_RECTS, dx=ordinal)
    return image


def write_chapter(folder: Path) -> Path:
    folder.mkdir()
    for ordinal, filename in enumerate(FILENAMES):
        (folder / filename).write_bytes(png(source_image(ordinal)))
    return folder


def cleaned_page(
    ordinal: int,
    fill: int,
    rects: Iterable[Rect] = TRUTH_RECTS,
    extra_ink: Iterable[Rect] = (),
) -> bytes:
    """The source scan with each of `rects` (inclusive) replaced by flat `fill`,
    then black ink drawn at `extra_ink` (inclusive boxes), as an RGB PNG."""
    image = source_image(ordinal)
    draw = ImageDraw.Draw(image)
    for rect in rects:
        draw.rectangle(rect, fill=(fill, fill, fill))
    for box in extra_ink:
        draw.rectangle(box, fill=(0, 0, 0))
    return png(image)


_made = itertools.count()


def project(
    tmp_path: Path,
    chapter: Chapter,
    detections: Mapping[int, Sequence[RawRegion]],
    cleaned: Mapping[int, bytes] | None = None,
) -> Project:
    """A fresh project of the chapter, open: regions first, then cleaned images
    (`write_regions` invalidates a cleaned image). Pages not named in
    `detections` have no regions; pages not named in `cleaned` have no cleaned
    image."""
    made = create_project(chapter, tmp_path / f"s2-control-{next(_made)}.mtproj")
    for ordinal, page_regions in detections.items():
        made.write_regions(ordinal, page_regions)
    for ordinal, image in (cleaned or {}).items():
        made.write_cleaned(ordinal, image)
    return made


def all_pages(page_regions: Sequence[RawRegion] | None = None) -> dict[int, list[RawRegion]]:
    return {
        ordinal: list(baseline() if page_regions is None else page_regions)
        for ordinal in range(len(FILENAMES))
    }


def all_cleaned(fill: int) -> dict[int, bytes]:
    return {ordinal: cleaned_page(ordinal, fill) for ordinal in range(len(FILENAMES))}


def seeded_truth(folder: Path, chapter: Chapter) -> GroundTruth:
    """The baseline project at `project_dir_for(folder)` - one exact proposal per
    truth region, nothing cleaned - and its seeded truth, loaded in benchmark mode."""
    with create_project(chapter, project_dir_for(folder)) as made:
        for ordinal, page_regions in all_pages().items():
            made.write_regions(ordinal, page_regions)
        seed_ground_truth(made, truth_path_for(folder))
    return load_ground_truth(truth_path_for(folder))


def write_doc(path: Path, truth: GroundTruth) -> Path:
    path.write_text(dump_ground_truth(truth), encoding="utf-8", newline="\n")
    return path


def flagged(tmp_path: Path, truth: GroundTruth) -> GroundTruth:
    """`truth` flagged `development_use`, loaded with `benchmark=False` so it gets
    past the loader and reaches a measurement directly."""
    path = write_doc(tmp_path / "dev.truth.json", dataclasses.replace(truth, development_use=True))
    loaded = load_ground_truth(path, benchmark=False)
    assert loaded.development_use
    return loaded


def stale(tmp_path: Path, truth: GroundTruth) -> GroundTruth:
    """`truth` with every page's sha256 wrong: two validator errors, loaded."""
    bad = dataclasses.replace(
        truth, pages=tuple(dataclasses.replace(page, sha256="0" * 64) for page in truth.pages)
    )
    return load_ground_truth(write_doc(tmp_path / "stale.truth.json", bad), benchmark=False)


def luma(data: bytes) -> NDArray[np.uint8]:
    with Image.open(BytesIO(data)) as image:
        return np.asarray(image.convert("L"))


def boom(*args: object, **kwargs: object) -> object:
    """A stand-in for a project read: a refusal must come before any of them."""
    raise AssertionError(f"measured before refusing: called with {args!r} {kwargs!r}")
