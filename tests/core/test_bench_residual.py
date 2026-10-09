"""`mangatl.bench.residual`: ink left inside a cleaned region, with both controls.

MT-023 AC-4, AC-5, AC-6 and AC-7 (for `measure_residual`), `## Contract`
block 2 as amended in RED (A-1: the contrast window is restricted to the
measured mask). The metric is **oracle-free**: its shape is pinned here on
arrays small enough to count by hand, its values on the chapter are not, and
the two negative controls are what make `RESIDUAL_INK_MAX` mean anything:

- **AC-5** (the metric sees surviving glyphs): cleaning skipped entirely, so the
  source scan is measured. Must score at least ten times the threshold.
- **AC-6** (the metric is about ink, not difference): each region filled with a
  flat luma-128 grey, which is inside the luma band and far from paper white.
  Must score *below* the threshold. A luma-only metric, or a "difference from
  paper" metric, passes AC-5 and fails this one.

**The fixture** is `_s2_world`'s two-page chapter: three 40 x 40 px truth
regions per page, each holding black 1-3 px glyph strokes on white. RED measured
it against a throwaway reference implementation of block 2 (never in `src/`) at
a skipped-cleaning fraction of 329 / 1600 = 0.2056 per region, 0.0 for the white
clean and 0.0 for the flat fill; GREEN confirms those against the shipped module
and sets `RESIDUAL_INK_MAX` from them. The numbers are in the story's handoff.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import _s2_world as w
import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.bench.residual import (
    CONTRAST_RADIUS,
    INK_CONTRAST_MIN,
    INK_LUMA_MAX,
    RESIDUAL_INK_MAX,
    RegionResidual,
    ResidualReport,
    ink_fraction,
    local_contrast,
    measure_residual,
    page_luma,
)
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    validate,
)
from mangatl.domain.page import Chapter
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter

_ALL_REGIONS = tuple((o, i) for o in range(len(w.FILENAMES)) for i in range(w.PER_PAGE))


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return w.write_chapter(tmp_path / w.CHAPTER)


@pytest.fixture
def chapter(folder: Path) -> Chapter:
    return read_chapter(folder)


@pytest.fixture
def truth(folder: Path, chapter: Chapter) -> GroundTruth:
    return w.seeded_truth(folder, chapter)


def _measure(
    tmp_path: Path,
    chapter: Chapter,
    truth: GroundTruth,
    cleaned: dict[int, bytes] | None,
    detections: dict[int, list[RawRegion]] | None = None,
) -> ResidualReport:
    with w.project(
        tmp_path, chapter, w.all_pages() if detections is None else detections, cleaned
    ) as project:
        return measure_residual(project, truth)


def _keys(report: ResidualReport) -> list[tuple[int, int]]:
    return [(r.page_ordinal, r.truth_index) for r in report.regions]


def _gray(rows: list[list[int]]) -> NDArray[np.uint8]:
    return np.array(rows, dtype=np.uint8)


# -- the constants ---------------------------------------------------------------


def test_the_ink_constants_are_luma_below_160_and_contrast_at_least_64_over_a_5x5_window() -> None:
    assert INK_LUMA_MAX == 160
    assert INK_CONTRAST_MIN == 64
    assert CONTRAST_RADIUS == 2


def test_the_residual_threshold_is_a_fraction_strictly_between_zero_and_one() -> None:
    assert type(RESIDUAL_INK_MAX) is float
    assert 0.0 < RESIDUAL_INK_MAX < 1.0


def test_the_flat_fill_sits_inside_the_luma_band_and_far_enough_from_paper_to_look_changed() -> (
    None
):
    """Contract block 2's invariant, kept: AC-6's fill passes the luma test, so the
    contrast test is the one AC-6 exercises; and it is at least INK_CONTRAST_MIN
    below paper white, so a "difference from paper" metric counts all of it."""
    assert w.FLAT_GREY < INK_LUMA_MAX
    assert 255 - w.FLAT_GREY >= INK_CONTRAST_MIN


# -- AC-4: page_luma ----------------------------------------------------------------


def test_ac4_page_luma_decodes_an_encoded_page_to_height_by_width_uint8_with_pillows_weights() -> (
    None
):
    image = Image.new("RGB", (5, 3), (128, 128, 128))
    image.putpixel((4, 0), (255, 0, 0))
    image.putpixel((0, 2), (0, 0, 255))

    luma = page_luma(w.png(image))

    assert luma.shape == (3, 5)
    assert luma.dtype == np.uint8
    assert luma[1, 1] == 128
    assert luma[0, 4] == 76  # Pillow's convert("L"), ITU-R 601-2: 255 * 0.299, truncated
    assert luma[2, 0] == 29  # 255 * 0.114
    assert np.array_equal(luma, w.luma(w.png(image)))


# -- AC-4: local_contrast ---------------------------------------------------------


def test_ac4_local_contrast_of_a_flat_array_is_zero_everywhere_including_the_borders() -> None:
    """Edge padding, not zero padding: zero padding would give 200 on every border pixel."""
    flat = np.full((7, 5), 200, dtype=np.uint8)

    contrast = local_contrast(flat)

    assert contrast.shape == (7, 5)
    assert contrast.dtype == np.uint8
    assert not contrast.any()


def test_ac4_one_dark_pixel_in_a_3x3_gives_every_pixel_its_full_contrast() -> None:
    patch = _gray([[255, 255, 255], [255, 0, 255], [255, 255, 255]])

    assert np.array_equal(local_contrast(patch), np.full((3, 3), 255, dtype=np.uint8))


def test_ac4_the_contrast_window_is_exactly_5x5_centred_on_the_pixel() -> None:
    """A dark pixel at (4, 4) of a 9 x 9 lies in the window of exactly the 25
    pixels within two of it: radius 1 would give 9, radius 3 would give 49."""
    patch = np.full((9, 9), 255, dtype=np.uint8)
    patch[4, 4] = 55

    contrast = local_contrast(patch)

    expected = np.zeros((9, 9), dtype=np.uint8)
    expected[2:7, 2:7] = 200
    assert np.array_equal(contrast, expected)


def test_ac4_the_contrast_at_a_border_sees_only_pixels_on_the_page() -> None:
    row = _gray([[0, 255, 255, 255, 255, 255, 255, 255, 255]])

    assert local_contrast(row).tolist() == [[255, 255, 255, 0, 0, 0, 0, 0, 0]]


def test_ac4_restricted_to_a_mask_the_contrast_ignores_every_pixel_outside_it() -> None:
    """Amendment A-1: `within` restricts the window to the mask and zeroes every
    pixel outside it. A flat fill inside the mask next to white paper outside it
    has no contrast at all; unrestricted, its two-pixel border band would."""
    row = _gray([[255, 255, 255, 255, 255, 128, 128, 128, 128, 128]])
    inside = np.array([[False] * 5 + [True] * 5])

    assert local_contrast(row).tolist() == [[0, 0, 0, 127, 127, 127, 127, 0, 0, 0]]
    assert local_contrast(row, within=inside).tolist() == [[0] * 10]


def test_ac4_restricted_to_a_mask_the_contrast_inside_it_is_unchanged_by_the_restriction() -> None:
    patch = np.full((9, 9), 255, dtype=np.uint8)
    patch[4, 4] = 0
    patch[0, 0] = 0  # outside the mask, and within two of (1..2, 1..2)
    inside = np.zeros((9, 9), dtype=bool)
    inside[1:8, 1:8] = True

    contrast = local_contrast(patch, within=inside)

    expected = np.zeros((9, 9), dtype=np.uint8)
    expected[2:7, 2:7] = 255
    assert np.array_equal(contrast, expected)


# -- AC-4: ink_fraction -------------------------------------------------------------


def test_ac4_ink_fraction_counts_dark_high_contrast_pixels_inside_the_mask_over_its_area() -> None:
    """A 6 x 6 mask (36 px) on white holding three black pixels: 3 / 36. A fourth
    black pixel outside the mask is not counted."""
    page = np.full((10, 10), 255, dtype=np.uint8)
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:8, 2:8] = True
    for y, x in ((2, 2), (4, 6), (7, 3)):
        page[y, x] = 0
    page[0, 9] = 0

    fraction = ink_fraction(page, mask)

    assert fraction == pytest.approx(3 / 36, abs=1e-12)
    assert type(fraction) is float


@pytest.mark.parametrize(
    ("dark", "paper", "is_ink"),
    [
        (159, 255, True),  # luma just inside the band, contrast 96
        (160, 255, False),  # luma at INK_LUMA_MAX: not dark enough (strict <)
        (100, 164, True),  # contrast exactly INK_CONTRAST_MIN (>=)
        (100, 163, False),  # contrast one short
    ],
    ids=["luma-159", "luma-160", "contrast-64", "contrast-63"],
)
def test_ac4_ink_needs_luma_below_160_and_contrast_of_at_least_64_together(
    dark: int, paper: int, is_ink: bool
) -> None:
    page = np.full((5, 5), paper, dtype=np.uint8)
    page[2, 2] = dark
    mask = np.ones((5, 5), dtype=bool)

    assert ink_fraction(page, mask) == (1 / 25 if is_ink else 0.0)


def test_ac4_a_dark_area_with_no_structure_is_not_ink() -> None:
    """Dense dark artwork, flat at luma 30: dark, but no glyph edges."""
    page = np.full((12, 12), 30, dtype=np.uint8)

    assert ink_fraction(page, np.ones((12, 12), dtype=bool)) == 0.0


def test_ac4_an_empty_mask_has_no_ink_and_does_not_divide_by_zero() -> None:
    page = np.zeros((4, 4), dtype=np.uint8)
    page[1, 1] = 255

    fraction = ink_fraction(page, np.zeros((4, 4), dtype=bool))

    assert fraction == 0.0
    assert type(fraction) is float


def test_ac4_a_mask_of_a_different_shape_from_the_page_is_refused() -> None:
    with pytest.raises(ValueError):
        ink_fraction(np.zeros((4, 5), dtype=np.uint8), np.ones((5, 4), dtype=bool))


# -- AC-4: measure_residual -----------------------------------------------------------


def test_ac4_the_report_shapes_are_exactly_these_fields_in_order() -> None:
    assert [f.name for f in dataclasses.fields(RegionResidual)] == [
        "page_ordinal",
        "truth_index",
        "fraction",
    ]
    assert [f.name for f in dataclasses.fields(ResidualReport)] == [
        "regions",
        "worst",
        "uncleaned_pages",
    ]


def test_ac4_a_correct_white_clean_reports_zero_ink_for_every_matched_region_in_order(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, w.all_cleaned(w.WHITE))

    assert report == ResidualReport(
        regions=tuple(RegionResidual(o, i, 0.0) for o, i in _ALL_REGIONS),
        worst=0.0,
        uncleaned_pages=(),
    )
    assert all(type(r.fraction) is float for r in report.regions)
    assert type(report.worst) is float
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.worst = 1.0  # type: ignore[misc]


def test_ac4_ink_outside_every_truth_polygon_is_not_measured(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Black strokes in the bottom half and just outside region 0's right edge."""
    _, y0, x1, y1 = w.TRUTH_RECTS[0]
    outside = [(10, 120, 60, 122), (30, 150, 31, 190), (x1 + 1, y0, x1 + 2, y1)]
    cleaned = {o: w.cleaned_page(o, w.WHITE, extra_ink=outside) for o in range(len(w.FILENAMES))}

    report = _measure(tmp_path, chapter, truth, cleaned)

    assert [r.fraction for r in report.regions] == [0.0] * w.GROUND_TRUTH
    assert report.worst == 0.0


def test_ac4_po1_ink_inside_the_truth_polygon_but_outside_a_tight_detection_is_measured(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """PO-1: page 0's region 0 is detected by a mask covering only its left 27
    columns (IoU 1080 / 1600, a match), and the cleaner whitened only that mask.
    The glyph strokes in the right 13 columns survive, inside the human-marked
    region and outside the detector's mask - and they are what gets measured."""
    x0, y0, _, y1 = w.TRUTH_RECTS[0]
    tight = (x0, y0, x0 + 26, y1)
    detections = w.all_pages()
    detections[0][0] = w.region(w.TRUTH_RECTS[0], [tight])
    cleaned = w.all_cleaned(w.WHITE)
    cleaned[0] = w.cleaned_page(0, w.WHITE, rects=[tight, *w.TRUTH_RECTS[1:]])

    report = _measure(tmp_path, chapter, truth, cleaned, detections)

    assert _keys(report) == list(_ALL_REGIONS)
    assert report.regions[0].fraction > RESIDUAL_INK_MAX
    assert [r.fraction for r in report.regions[1:]] == [0.0] * (w.GROUND_TRUTH - 1)
    assert report.worst == report.regions[0].fraction


def test_ac4_po1_a_missed_region_is_not_measured_and_neither_is_a_spurious_detection(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Nothing is cleaned, so every region measured scores high: page 1's region 1
    has no detection and is absent; the spurious detection over inked paper in
    the bottom half has no truth polygon and is absent."""
    detections = w.all_pages()
    del detections[1][1]
    detections[0].append(w.region((10, 120, 49, 159)))

    report = _measure(tmp_path, chapter, truth, None, detections)

    assert _keys(report) == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 2)]


def test_ac4_with_no_matched_region_nothing_is_measured_and_the_worst_is_zero(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, None, {})

    assert report.regions == ()
    assert report.worst == 0.0
    assert type(report.worst) is float


def test_ac4_po2_a_page_with_no_cleaned_image_is_measured_on_its_source_scan_and_listed(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Page 0 cleaned white, page 1 never cleaned."""
    report = _measure(tmp_path, chapter, truth, {0: w.cleaned_page(0, w.WHITE)})

    assert report.uncleaned_pages == (1,)
    assert [r.fraction for r in report.regions[:3]] == [0.0, 0.0, 0.0]
    assert all(r.fraction >= 10 * RESIDUAL_INK_MAX for r in report.regions[3:])
    assert report.worst == max(r.fraction for r in report.regions)


def test_ac4_the_stored_cleaned_image_is_what_is_measured_not_the_source_scan(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Page 1 is cleaned with only region 2 left as the source had it."""
    cleaned = w.all_cleaned(w.WHITE)
    cleaned[1] = w.cleaned_page(1, w.WHITE, rects=w.TRUTH_RECTS[:2])

    report = _measure(tmp_path, chapter, truth, cleaned)

    assert report.uncleaned_pages == ()
    assert [r.fraction for r in report.regions[:5]] == [0.0] * 5
    assert report.regions[5].fraction >= 10 * RESIDUAL_INK_MAX
    assert report.worst == report.regions[5].fraction


# -- AC-5 / AC-6: the two controls -----------------------------------------------------


def test_ac5_control_with_cleaning_skipped_every_region_scores_ten_times_the_threshold(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, None)

    assert report.uncleaned_pages == (0, 1)
    assert _keys(report) == list(_ALL_REGIONS)
    fractions = [r.fraction for r in report.regions]
    assert all(f >= 10 * RESIDUAL_INK_MAX for f in fractions), (fractions, RESIDUAL_INK_MAX)
    assert report.worst == max(fractions)


def test_ac5_control_a_cleaned_image_identical_to_the_source_scores_as_cleaning_skipped(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """The same skipped cleaning by the other route: a stored "cleaned" image that
    is the source scan's own bytes. Nothing is listed uncleaned."""
    stored = {o: w.png(w.source_image(o)) for o in range(len(w.FILENAMES))}

    report = _measure(tmp_path, chapter, truth, stored)

    assert report.uncleaned_pages == ()
    assert all(r.fraction >= 10 * RESIDUAL_INK_MAX for r in report.regions)


def test_ac6_control_a_flat_mid_grey_fill_of_every_region_scores_below_the_threshold(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Every pixel of the fill is darker than INK_LUMA_MAX and differs from paper
    by more than INK_CONTRAST_MIN. A metric of "how dark" or "how changed" scores
    it near 1.0; an ink metric scores it as no ink, edges against the paper
    outside the polygon included."""
    for ordinal in range(len(w.FILENAMES)):
        luma = w.luma(w.cleaned_page(ordinal, w.FLAT_GREY))
        x0, y0, x1, y1 = w.TRUTH_RECTS[0]
        assert (luma[y0 : y1 + 1, x0 : x1 + 1] == w.FLAT_GREY).all()

    report = _measure(tmp_path, chapter, truth, w.all_cleaned(w.FLAT_GREY))

    assert _keys(report) == list(_ALL_REGIONS)
    fractions = [r.fraction for r in report.regions]
    assert all(f < RESIDUAL_INK_MAX for f in fractions), (fractions, RESIDUAL_INK_MAX)
    assert report.worst < RESIDUAL_INK_MAX


# -- AC-7: refusals -------------------------------------------------------------------


def test_ac7_a_development_use_truth_reaching_measure_residual_directly_is_refused_naming_it(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth, monkeypatch: pytest.MonkeyPatch
) -> None:
    flagged = w.flagged(tmp_path, truth)
    with w.project(tmp_path, chapter, w.all_pages()) as project:
        monkeypatch.setattr(type(project), "read_regions", w.boom)
        monkeypatch.setattr(type(project), "read_cleaned", w.boom)
        with pytest.raises(BenchmarkChapterUsedInDevelopment) as refused:
            measure_residual(project, flagged)

    assert w.CHAPTER in str(refused.value)


def test_ac7_a_truth_failing_its_validator_is_refused_by_measure_residual_with_every_error_line(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    loaded = w.stale(tmp_path, truth)
    errors = validate(loaded, chapter).errors
    assert len(errors) == 2

    with (
        w.project(tmp_path, chapter, w.all_pages()) as project,
        pytest.raises(InvalidGroundTruth) as refused,
    ):
        measure_residual(project, loaded)

    assert all(error in str(refused.value) for error in errors), (errors, str(refused.value))
