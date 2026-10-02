"""AC-6 and AC-7: the real detector and the real LaMa on synthetic composites (MT-019).

**Everything here is marked `gpu` and never runs on CI** (MT-002 PO-1). The pages
and both models live under `spikes/**`, which `.gitignore` covers - a
non-redistributable commercial scan and third-party weights - and a checkout
without them skips. So does a machine without the rendering font, Yu Gothic
Medium (`C:/Windows/Fonts/YuGothM.ttc`, face 0): an environment gap, which the
integration gate's `skipped-when` line reports as `BLOCKED` for this story,
never a pass.

**The composites are built at test time, in memory, and never written** (PO-1,
C-9). Japanese text is rendered onto a text-free area of a fixture scan; the
untouched scan is the exact reference. Nothing derived from the scans is written
anywhere - not even under `tmp_path` - and the page is handed to the detector as
PNG bytes in memory.

**Rendering, pinned by C-9.** Pillow here has no libraqm, so `direction="ttb"` is
unavailable: one glyph per `ImageDraw.text` call, black, default anchor and
anti-aliasing; glyph `j` of a column at `y = top + j * size`; columns right to
left, the first rightmost, pitch `round(1.25 * size)`; the block centred in the
source rect with integer division.

**The pipeline under test is production's:** PNG bytes ->
`detect_page_regions(load_detector(...))` -> `erase_mask(all regions, (W, H))` ->
`clean_page(composite, mask, load_inpainter(...))`. Every region on the page is
cleaned; only the metric is local.

**The metrics are C-9's, unchanged.** AC-6: mean absolute residual over the
pixels the rendered text changed (`F`), all three channels, against the
reference. AC-7: `ratio = mean(V[I]) / mean(V[A])` where `V` is the 5x5 local
variance of the grey image, `I` the erase-mask components touching `F` eroded by
a 5x5 square, `A` a 12 px annulus around them inside the tone rect (eroded 2 px).

**What RED measured on this machine (`CUDAExecutionProvider`, 2026-10-02)**, the
detector being real and only `clean.*` missing - the story's handoff has the
full table:

* AC-6 (`012.jpg`, white): 1,686 changed pixels, detector coverage **0.9982**,
  uncleaned residual **145.37**;
* AC-7 (`011.jpg`, tone): 1,157 changed pixels, coverage **1.0000**; with the
  erase mask at `r = 0 / 2 / 4 / 8`: flat-fill ratio **0.000000** at every `r`,
  uncleaned ratio **3.04 / 2.78 / 2.54 / 2.20**, and the untouched reference
  scored over the same `I` and `A` **1.058 / 1.052 / 1.039 / 1.018**;
* the cleaned values are claims until GREEN: the PO pre-measured AC-6 cleaned
  1.00-1.17 and AC-7 cleaned ratio 0.82-0.86.

**The session convention check is amended (C-9, RED):** scoring against Carve's
published reference over the hole does not discriminate - measured, the output
scores 46.66 and the *input* 52.42, a ratio of 1.12 against the 3x the contract
asked for (the 3.96 of MT-002 E4 is a whole-image number, 92% of it outside the
hole where the export copies its input). The check below instead reads C-2's
settled facts out of the shipped session: outside the hole the output is exactly
`255 * image` (measured max deviation **0.0**), inside it the output differs
from `255 * image` (measured mean **38.91**), and the control - the same call
with the mask inverted - scores **0.00** inside the hole and **150.86** max
outside.

**Timings.** One LaMa call is tens of milliseconds on CUDA and each session costs
a few seconds to build, so both sessions are module-scoped and each composite is
detected and cleaned once into a module-scoped fixture that every test reads.
`pytest-timeout` is not a dependency of this project and no per-test timeout
exists, so there is no budget in this file to size - if a later story adds one,
every hook here needs one too.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from mangatl.clean.inpaint import INPAINT_MAX_RESIDUAL, TONE_VARIANCE_TOLERANCE, clean_page
from mangatl.clean.mask import erase_mask
from mangatl.clean.session import (
    MODEL_INPUT_SIDE,
    InpaintSession,
    load_inpainter,
    selected_provider,
)
from mangatl.detect.page import detect_page_regions
from mangatl.detect.session import DetectorSession, load_detector

pytestmark = pytest.mark.gpu

_SPIKES = Path(__file__).resolve().parents[2] / "spikes"
_DETECTOR = _SPIKES / "MT-002" / "models" / "comic-text-detector-onnx" / "comic-text-detector.onnx"
_LAMA_DIR = _SPIKES / "MT-002" / "models" / "LaMa-ONNX"
_LAMA = _LAMA_DIR / "lama_fp32.onnx"
_PAGES = _SPIKES / "MT-002" / "pages"
_FONT = Path("C:/Windows/Fonts/YuGothM.ttc")
_PROVIDERS = ("CUDAExecutionProvider", "CPUExecutionProvider")

#: C-9's test constants. Not production constants: they define the metric.
LOCAL_VARIANCE_WINDOW = 5
ANNULUS_PX = 12
MIN_DETECTOR_COVERAGE = 0.95

#: The convention check's bounds (amended C-9). Outside the hole C-2 says the
#: export returns its input at scale 255 exactly; half an 8-bit level allows
#: nothing but float rounding. Inside the hole an inpainted output must differ
#: from its input; 10 levels is about a quarter of the 38.91 measured. The
#: inverted-mask control measured 150.86 outside and 0.00 inside, so it misses
#: both bounds by far more than the 4x its test demands.
_OUTSIDE_HOLE_MAX_DEVIATION = 0.5
_INSIDE_HOLE_MIN_MEAN_DEVIATION = 10.0


@dataclass(frozen=True)
class _Fixture:
    """One composite, the reference it was rendered over, and its cleaning."""

    name: str
    rect: tuple[int, int, int, int]  # x, y, w, h
    reference: NDArray[np.uint8]
    composite: NDArray[np.uint8]
    changed: NDArray[np.bool_]  # F
    detected: NDArray[np.bool_]  # union of the detector's region masks
    erase: NDArray[np.bool_]  # erase_mask(...)
    cleaned: NDArray[np.uint8]


#: C-9's two composites: page, source rect `(x, y, w, h)`, columns, glyph size.
_SPECS: dict[str, tuple[str, tuple[int, int, int, int], tuple[str, ...], int]] = {
    "white": ("012.jpg", (80, 720, 160, 160), ("今日は本当に", "ありがとう"), 24),
    "tone": ("011.jpg", (432, 224, 128, 128), ("雨が降る", "夜の街"), 20),
}


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path} is not present: gitignored spike data, see the module docstring")


def _require_font() -> None:
    if not _FONT.exists():
        pytest.skip(
            f"{_FONT} (Yu Gothic Medium) is not present: the rendering font C-9 pins,"
            " recorded in docs/wiki/environment.md"
        )


def _scan(name: str) -> NDArray[np.uint8]:
    _require(_PAGES / name)
    with Image.open(_PAGES / name) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def _render(
    page: NDArray[np.uint8], rect: tuple[int, int, int, int], columns: Sequence[str], size: int
) -> NDArray[np.uint8]:
    """C-9's vertical layout, one glyph per call, onto a copy of `page`."""
    image = Image.fromarray(page)
    font = ImageFont.truetype(str(_FONT), size, index=0)
    draw = ImageDraw.Draw(image)
    x, y, w, h = rect
    pitch = round(1.25 * size)
    count = len(columns)
    block_w = (count - 1) * pitch + size
    block_h = max(len(column) for column in columns) * size
    left = x + (w - block_w) // 2
    top = y + (h - block_h) // 2
    for index, column in enumerate(columns):
        column_x = left + (count - 1 - index) * pitch
        for j, glyph in enumerate(column):
            draw.text((column_x, top + j * size), glyph, font=font, fill=(0, 0, 0))
    return np.asarray(image, dtype=np.uint8).copy()


def _png(page: NDArray[np.uint8]) -> bytes:
    buffer = BytesIO()
    Image.fromarray(page).save(buffer, format="PNG")
    return buffer.getvalue()


def _union(masks: Sequence[bytes], size: tuple[int, int]) -> NDArray[np.bool_]:
    width, height = size
    union = np.zeros((height, width), dtype=bool)
    for data in masks:
        with Image.open(BytesIO(data)) as image:
            union |= np.array(image, dtype=bool)
    return union


def _rect_mask(shape: tuple[int, int], rect: tuple[int, int, int, int]) -> NDArray[np.bool_]:
    x, y, w, h = rect
    mask = np.zeros(shape, dtype=bool)
    mask[y : y + h, x : x + w] = True
    return mask


@pytest.fixture(scope="module")
def detector() -> Iterator[DetectorSession]:
    _require(_DETECTOR)
    yield load_detector(_DETECTOR, _PROVIDERS)


@pytest.fixture(scope="module")
def inpainter() -> Iterator[InpaintSession]:
    _require(_LAMA)
    yield load_inpainter(_LAMA, _PROVIDERS)


@pytest.fixture(scope="module")
def fixtures(detector: DetectorSession, inpainter: InpaintSession) -> dict[str, _Fixture]:
    """Each composite detected and cleaned exactly once, through production's path."""
    _require_font()
    out: dict[str, _Fixture] = {}
    for key, (name, rect, columns, size) in _SPECS.items():
        reference = _scan(name)
        height, width = reference.shape[:2]
        composite = _render(reference, rect, columns, size)
        regions = detect_page_regions(detector, _png(composite))
        erase = erase_mask(regions, (width, height))
        cleaned = clean_page(composite, erase, inpainter)
        out[key] = _Fixture(
            name=name,
            rect=rect,
            reference=reference,
            composite=composite,
            changed=(composite != reference).any(axis=2),
            detected=_union([region.mask for region in regions], (width, height)),
            erase=erase,
            cleaned=cleaned,
        )
    return out


# -- the session: provider, shape, and C-2's convention ----------------------------


def _carve_inputs() -> tuple[NDArray[np.uint8], NDArray[np.bool_]]:
    """Carve's `image.jpg` and `mask.png` at 512: image `INTER_AREA`, mask
    `INTER_NEAREST` thresholded `> 127` (C-9)."""
    _require(_LAMA_DIR / "image.jpg")
    _require(_LAMA_DIR / "mask.png")
    with Image.open(_LAMA_DIR / "image.jpg") as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    with Image.open(_LAMA_DIR / "mask.png") as image:
        grey = np.asarray(image.convert("L"), dtype=np.uint8)
    side = (MODEL_INPUT_SIDE, MODEL_INPUT_SIDE)
    image512 = np.asarray(cv2.resize(rgb, side, interpolation=cv2.INTER_AREA), dtype=np.uint8)
    hole = np.asarray(cv2.resize(grey, side, interpolation=cv2.INTER_NEAREST) > 127, dtype=bool)
    return image512, hole


def _run(
    session: InpaintSession, image: NDArray[np.uint8], hole: NDArray[np.bool_]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """`session.run` with C-2's convention; `(output HWC, 255 * input HWC)`."""
    x = (image.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
    m = hole[None, None].astype(np.float32)
    out = session.run(np.ascontiguousarray(x), m)
    assert out.dtype == np.float32
    assert out.shape == (1, 3, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE)
    scaled_input = 255.0 * x[0].transpose(1, 2, 0).astype(np.float64)
    return out[0].transpose(1, 2, 0).astype(np.float64), scaled_input


def test_the_inpainter_runs_on_cuda_and_returns_float32_at_512(
    inpainter: InpaintSession,
) -> None:
    """C-9's smoke: the provider actually selected is CUDA, read through
    `selected_provider`, and `run` returns `float32 (1, 3, 512, 512)`."""
    assert selected_provider(inpainter) == inpainter.get_providers()[0]
    assert selected_provider(inpainter) == "CUDAExecutionProvider", (
        f"providers {list(inpainter.get_providers())}: either ort.preload_dlls(...) did not"
        " run before the InferenceSession, or this machine has no CUDA"
    )
    image, hole = _carve_inputs()
    _run(inpainter, image, hole)


def test_the_session_returns_the_input_at_scale_255_outside_the_hole_and_inpaints_inside(
    inpainter: InpaintSession,
) -> None:
    """C-2, read out of the shipped session (amended C-9): `1.0` is a hole, the
    output is in 8-bit scale, and the session hands `output` back unchanged.
    A session that divided by 255, swapped the inputs, or fed the mask
    inverted fails one of the two assertions."""
    image, hole = _carve_inputs()
    out, scaled_input = _run(inpainter, image, hole)

    outside = float(np.abs(out[~hole] - scaled_input[~hole]).max())
    inside = float(np.abs(out[hole] - scaled_input[hole]).mean())
    assert outside <= _OUTSIDE_HOLE_MAX_DEVIATION, (
        f"outside the hole the output deviates from 255 * input by up to {outside:.2f}"
    )
    assert inside >= _INSIDE_HOLE_MIN_MEAN_DEVIATION, (
        f"inside the hole the output is within {inside:.2f} of the input: nothing was inpainted"
    )


def test_the_convention_check_fires_when_the_mask_polarity_is_inverted(
    inpainter: InpaintSession,
) -> None:
    """The control for the test above: the same call with `1.0` meaning *keep*
    must fail both of its bounds, or the check cannot see a polarity error."""
    image, hole = _carve_inputs()
    out, scaled_input = _run(inpainter, image, ~hole)

    outside = float(np.abs(out[~hole] - scaled_input[~hole]).max())
    inside = float(np.abs(out[hole] - scaled_input[hole]).mean())
    assert outside > 4 * _OUTSIDE_HOLE_MAX_DEVIATION
    assert inside < _INSIDE_HOLE_MIN_MEAN_DEVIATION / 4


# -- fixture validity: the detector really found the text ---------------------------


@pytest.mark.parametrize("key", sorted(_SPECS))
def test_the_detector_covers_at_least_95_percent_of_the_rendered_text(
    key: str, fixtures: dict[str, _Fixture]
) -> None:
    """C-9's precondition, a failure and not a skip: if the detector missed the
    text, AC-6 and AC-7 are measuring something other than cleaning."""
    fixture = fixtures[key]
    changed = int(fixture.changed.sum())
    coverage = float((fixture.detected & fixture.changed).sum()) / changed

    assert changed > 0, f"{fixture.name}: rendering changed no pixel"
    assert not (fixture.changed & ~_rect_mask(fixture.changed.shape, fixture.rect)).any(), (
        f"{fixture.name}: the rendered text spills out of the source rect"
    )
    assert coverage >= MIN_DETECTOR_COVERAGE, (
        f"{fixture.name}: the detector's regions cover {coverage:.4f} of the"
        f" {changed} changed pixels, below {MIN_DETECTOR_COVERAGE}"
    )


@pytest.mark.parametrize("key", sorted(_SPECS))
def test_on_a_real_page_no_pixel_outside_the_erase_mask_changes(
    key: str, fixtures: dict[str, _Fixture]
) -> None:
    """AC-4 with the real model, the real session and every region on the page:
    exact equality outside the erase mask."""
    fixture = fixtures[key]
    outside = ~fixture.erase

    assert np.array_equal(fixture.cleaned[outside], fixture.composite[outside])


# -- AC-6: the text is gone -------------------------------------------------------


def _residual(fixture: _Fixture, page: NDArray[np.uint8]) -> float:
    changed = fixture.changed
    diff = page[changed].astype(np.float64) - fixture.reference[changed].astype(np.float64)
    return float(np.abs(diff).mean())


def test_cleaning_removes_the_rendered_text_down_to_the_residual_bound(
    fixtures: dict[str, _Fixture],
) -> None:
    """AC-6: over the pixels the text changed, the cleaned composite is within
    `INPAINT_MAX_RESIDUAL` of the untouched scan."""
    fixture = fixtures["white"]
    cleaned = _residual(fixture, fixture.cleaned)

    assert cleaned < INPAINT_MAX_RESIDUAL, (
        f"{fixture.name}: cleaned residual {cleaned:.2f} >= INPAINT_MAX_RESIDUAL"
        f" {INPAINT_MAX_RESIDUAL}"
    )


def test_the_uncleaned_composite_scores_at_least_four_times_the_residual_bound(
    fixtures: dict[str, _Fixture],
) -> None:
    """AC-6's control: the text still there must score >= 4 x the bound, or the
    metric cannot tell cleaning from not cleaning. RED measured 145.37."""
    fixture = fixtures["white"]
    uncleaned = _residual(fixture, fixture.composite)

    assert uncleaned >= 4 * INPAINT_MAX_RESIDUAL, (
        f"{fixture.name}: uncleaned residual {uncleaned:.2f} < 4 x {INPAINT_MAX_RESIDUAL}"
    )


# -- AC-7: the tone is reconstructed, not painted flat -----------------------------


@dataclass(frozen=True)
class _ToneRegions:
    hole: NDArray[np.bool_]  # S
    inside: NDArray[np.bool_]  # I
    annulus: NDArray[np.bool_]  # A


def _tone_regions(fixture: _Fixture) -> _ToneRegions:
    """C-9's `S`, `I` and `A` for one fixture."""
    _count, labels = cv2.connectedComponents(fixture.erase.astype(np.uint8), connectivity=8)
    touching = np.unique(labels[fixture.erase & fixture.changed])
    touching = touching[touching != 0]
    hole = np.isin(labels, touching)

    square5 = np.ones((5, 5), dtype=np.uint8)
    inside = cv2.erode(hole.astype(np.uint8), square5, borderValue=0).astype(bool)
    rect = _rect_mask(hole.shape, fixture.rect)
    tone = cv2.erode(rect.astype(np.uint8), square5, borderValue=0).astype(bool)
    side = 2 * (2 + ANNULUS_PX) + 1
    outer = cv2.dilate(hole.astype(np.uint8), np.ones((side, side), dtype=np.uint8)).astype(bool)
    near = cv2.dilate(hole.astype(np.uint8), square5).astype(bool)
    return _ToneRegions(hole=hole, inside=inside, annulus=outer & ~near & tone)


def _ratio(page: NDArray[np.uint8], regions: _ToneRegions) -> float:
    grey = cv2.cvtColor(page, cv2.COLOR_RGB2GRAY).astype(np.float64)
    k = (LOCAL_VARIANCE_WINDOW, LOCAL_VARIANCE_WINDOW)
    variance = cv2.blur(grey * grey, k) - cv2.blur(grey, k) ** 2
    return float(variance[regions.inside].mean() / variance[regions.annulus].mean())


def test_the_tone_fixtures_hole_lies_inside_the_screentone_rect(
    fixtures: dict[str, _Fixture],
) -> None:
    """C-9: `S` within the rect, with a non-empty interior and annulus - else
    the fixture is invalid and AC-7 would be measuring the page's art."""
    fixture = fixtures["tone"]
    regions = _tone_regions(fixture)

    assert regions.hole.any(), "no erase-mask component touches the rendered text"
    assert not (regions.hole & ~_rect_mask(regions.hole.shape, fixture.rect)).any(), (
        f"{fixture.name}: the erase-mask components touching the text leave the tone rect"
    )
    assert regions.inside.sum() > 0
    assert regions.annulus.sum() > 0


def test_the_reconstructed_tone_has_the_local_variance_of_the_tone_around_it(
    fixtures: dict[str, _Fixture],
) -> None:
    """AC-7: `|ratio(cleaned) - 1| <= TONE_VARIANCE_TOLERANCE`. PO pre-measured
    0.82-0.86."""
    fixture = fixtures["tone"]
    ratio = _ratio(fixture.cleaned, _tone_regions(fixture))

    assert abs(ratio - 1.0) <= TONE_VARIANCE_TOLERANCE, (
        f"{fixture.name}: local-variance ratio {ratio:.3f}, |ratio - 1| > {TONE_VARIANCE_TOLERANCE}"
    )


def test_a_flat_white_fill_misses_the_tone_ratio_by_at_least_twice_the_tolerance(
    fixtures: dict[str, _Fixture],
) -> None:
    """AC-7's control, the one this criterion exists for: the hole painted white
    must miss 1 by >= 2 x the tolerance. RED measured ratio 0.000000."""
    fixture = fixtures["tone"]
    regions = _tone_regions(fixture)
    flat = fixture.composite.copy()
    flat[regions.hole] = 255
    ratio = _ratio(flat, regions)

    assert abs(ratio - 1.0) >= 2 * TONE_VARIANCE_TOLERANCE, (
        f"{fixture.name}: flat fill scores ratio {ratio:.3f}, within"
        f" 2 x {TONE_VARIANCE_TOLERANCE} of 1 - the metric cannot see a flat fill"
    )


def test_the_untouched_scan_scores_within_the_tone_tolerance(
    fixtures: dict[str, _Fixture],
) -> None:
    """The metric's positive control: the reference itself - a perfect
    reconstruction - is within tolerance over the same `I` and `A`. RED
    measured 1.018-1.058 across `r = 0..8`. Without this a tolerance could be
    met only by an implementation biased the same way as the metric."""
    fixture = fixtures["tone"]
    ratio = _ratio(fixture.reference, _tone_regions(fixture))

    assert abs(ratio - 1.0) <= TONE_VARIANCE_TOLERANCE, (
        f"{fixture.name}: the reference scores {ratio:.3f}"
    )
