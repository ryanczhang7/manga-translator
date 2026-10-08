"""S2, second half: residual ink - whether Japanese pixels survive a clean.

MT-023 `## Contract` block 2, as amended in RED (A-1). Per matched truth region,
the fraction of its pixels that are still **ink-like** in the cleaned page
(AC-4). Two controls make the threshold mean something: cleaning skipped scores
at least ten times `RESIDUAL_INK_MAX` (AC-5), and a region filled flat with
mid-grey scores below it (AC-6).

**Ink-like is two conditions, not one.** A pixel is ink when it is darker than
`INK_LUMA_MAX` **and** its local contrast - max minus min over the
`(2 * CONTRAST_RADIUS + 1)` square around it - is at least `INK_CONTRAST_MIN`.
Brightness alone counts screentone and dark art as surviving text; "different
from the source" or "different from paper" rewards a cleaner that paints the
region any flat colour. A glyph is a high-frequency structure, and local
contrast is the two-point quantity that sees it. The metric therefore counts a
stroke's edge band rather than its area, which is why `RESIDUAL_INK_MAX` was
measured, not reasoned.

**The contrast window is restricted to the measured mask (A-1).** A flat fill
meets the paper outside its polygon; over a whole-page window its edge band
reads as contrast and the fill scores as ink, which is not ink left *inside*
the region. Restricted, a glyph keeps its contrast against the white inside the
region and a flat fill has none. Implemented with sentinels: outside the mask a
pixel stands in as `-1` for the max and `256` for the min, so it never wins
either, and the result is zeroed outside the mask.

**Which pixels, which image (PO-1, PO-2).** The truth polygon of each **matched**
truth region - not the detector's mask, which cannot see glyphs a too-tight mask
left behind. Missed regions are recall's failure and spurious proposals have no
polygon, so neither is measured here; the matching is `measure_recall`'s, reused
rather than repeated, which also makes the refusals its refusals. The image is
the stored cleaned page, or - when none is stored - the source scan, with the
page listed in `uncleaned_pages`. A page with no matched region is not read at
all, so it is never listed as measured on its source scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from PIL import Image

from mangatl.bench.matching import polygon_mask
from mangatl.bench.recall import measure_recall
from mangatl.bench.truth import GroundTruth
from mangatl.store.project import Project

__all__ = [
    "CONTRAST_RADIUS",
    "INK_CONTRAST_MIN",
    "INK_LUMA_MAX",
    "RESIDUAL_INK_MAX",
    "RegionResidual",
    "ResidualReport",
    "ink_fraction",
    "local_contrast",
    "measure_residual",
    "page_luma",
]

#: A pixel darker than this MAY be ink. Deliberately generous: AC-6's luma-128
#: fill sits inside it, so it is the contrast test that AC-6 exercises.
INK_LUMA_MAX: int = 160

#: ... and is ink only if its local contrast is at least this.
INK_CONTRAST_MIN: int = 64

#: The contrast neighbourhood is (2r+1) x (2r+1) = 5 x 5, edge-padded.
CONTRAST_RADIUS: int = 2

#: A region passes when at most this fraction of its pixels is still ink.
#: Measured, not reasoned (the metric counts stroke edge bands, so its scale
#: depends on stroke width). Through this module, on MT-023's fixture
#: (`tests/core/_s2_world.py`: 40 x 40 px regions, 1-3 px black strokes):
#: cleaning skipped 0.205625 (329 / 1600) per region; flat luma-128 fill 0.0;
#: white clean 0.0; a too-tight detector leaving 13 of 40 columns 0.065.
#: Headroom: AC-5 needs skipped >= 10x this, i.e. at most 0.0205625; 0.01 leaves
#: that requirement met twice over (skipped is 20.6x), sits above both clean
#: runs, and still flags the tight-detector case at 6.5x. To revisit when the
#: benchmark chapter's real pages are measured - not tuned against them.
RESIDUAL_INK_MAX: float = 0.01


@dataclass(frozen=True)
class RegionResidual:
    """One matched truth region's surviving ink, as a fraction of its pixels."""

    page_ordinal: int
    truth_index: int
    fraction: float


@dataclass(frozen=True)
class ResidualReport:
    """One measurement of every matched truth region."""

    regions: tuple[RegionResidual, ...]  # page order, then index order
    worst: float  # max fraction; 0.0 when regions == ()
    uncleaned_pages: tuple[int, ...]  # measured on the source scan: no cleaned image stored


def page_luma(image: bytes) -> NDArray[np.uint8]:
    """An encoded page as (height, width) luma, Pillow's convert("L") (ITU-R 601-2)."""
    with Image.open(BytesIO(image)) as decoded:
        return np.asarray(decoded.convert("L"))


def local_contrast(
    luma: NDArray[np.uint8], *, within: NDArray[np.bool_] | None = None
) -> NDArray[np.uint8]:
    """Per pixel: max minus min of luma over the (2r+1)^2 window centred on it,
    `np.pad(mode="edge")` at the borders, so the output has the input's shape.

    With `within` (same shape; amendment A-1) the max and min are taken only over
    window pixels where `within` is True, and every pixel where it is False is 0.
    Edge padding never changes a window's extremes - the replicated pixel is
    already in the window - so padding the sentinels the same way is consistent.
    """
    inside = np.ones(luma.shape, dtype=bool) if within is None else within
    values = luma.astype(np.int16)
    side = 2 * CONTRAST_RADIUS + 1
    highs = np.pad(np.where(inside, values, -1), CONTRAST_RADIUS, mode="edge")
    lows = np.pad(np.where(inside, values, 256), CONTRAST_RADIUS, mode="edge")
    high = sliding_window_view(highs, (side, side)).max(axis=(-2, -1))
    low = sliding_window_view(lows, (side, side)).min(axis=(-2, -1))
    return np.where(inside, high - low, 0).astype(np.uint8)


def ink_fraction(cleaned: NDArray[np.uint8], mask: NDArray[np.bool_]) -> float:
    """Fraction of `mask`'s pixels that are ink-like in `cleaned` (a luma array of
    the same shape): luma < INK_LUMA_MAX and
    local_contrast(cleaned, within=mask) >= INK_CONTRAST_MIN.

    0.0 for an empty mask. ValueError on a shape mismatch.
    """
    if cleaned.shape != mask.shape:
        raise ValueError(f"page and mask have different shapes: {cleaned.shape} and {mask.shape}")
    area = int(mask.sum())
    if area == 0:
        return 0.0
    contrast = local_contrast(cleaned, within=mask)
    ink = mask & (cleaned < INK_LUMA_MAX) & (contrast >= INK_CONTRAST_MIN)
    return int(ink.sum()) / area


def measure_residual(project: Project, truth: GroundTruth) -> ResidualReport:
    """Measure surviving ink inside every matched truth region of `truth`.

    Refuses exactly as `measure_recall` does, before anything is read, because
    the matching is `measure_recall`'s.
    """
    recall = measure_recall(project, truth)
    regions: list[RegionResidual] = []
    uncleaned: list[int] = []
    for page, page_recall in zip(truth.pages, recall.pages, strict=True):
        matched = [region for region in page.regions if region.index not in page_recall.missed]
        if not matched:
            continue
        image = project.read_cleaned(page.ordinal)
        if image is None:
            image = (project.chapter.source_dir / page.filename).read_bytes()
            uncleaned.append(page.ordinal)
        luma = page_luma(image)
        regions.extend(
            RegionResidual(
                page.ordinal,
                region.index,
                ink_fraction(luma, polygon_mask(region.polygon, page.width, page.height)),
            )
            for region in matched
        )
    return ResidualReport(
        regions=tuple(regions),
        worst=max((region.fraction for region in regions), default=0.0),
        uncleaned_pages=tuple(uncleaned),
    )
