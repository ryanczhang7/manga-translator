"""MT-147 AC-6, end to end and headless: a region the model calls art comes
back from the bake exactly as the scan drew it (C-6).

The chain under test is four stories long and this is the only file that walks
it whole: the cleaner erases every region it is handed (it runs before the
model has answered, so the art region is erased too - `## Out of scope`), the
translate stage marks the region `art` (this story), and the bake pastes the
source back over an excluded region's erased area (MT-119, MT-152). Each link
has its own suite; this one asserts the pixels a reader sees.

**The world.** A one-page chapter on `tmp_path`, run through
`pipeline.stages.build_stages` from four doubles (the shape
`tests/core/test_stages.py` uses) and `run_chapter`, then baked with
`pipeline.bake.bake_chapter`.

- **The page is a texture** (`_bake_world.texture`), so "equals the source"
  and "is white" are different observations: no channel of the texture
  reaches 255.
- **The cleaner double paints only each handed region's mask pixels white**
  and leaves every other pixel the source's. Bake's restore pastes the source
  over the region's grown erase mask, which contains the mask; a double that
  whitened the whole polygon would leave white the restore never claims to
  cover (C-6).
- **The art region sits clear of the dialogue region**: 40 px apart on a
  160x120 page, far beyond the erase mask's growth and dilation and the
  typeset block, so no included region's mask or glyph reaches it.
- **The dialogue region carries a proposal and is typeset**, so the page is
  really baked and not copied; `regions_empty == 0` and ink inside the
  dialogue polygon say so.
- **Which region is art is decided by what the region says, not by its
  index**: the transcriber reads the art polygon as `ドドド`, and the
  translator lists whichever index in its listing reads that. Reading order is
  `sort_regions`' to compute, and this file does not re-derive it.

**The control** (AC-6's second sentence) is the same run with the translator
listing nothing: the art region is then included and has no line, so nothing
is set and nothing is restored, and every one of its mask pixels is still the
cleaner's white in the baked page. Without it, a fixture whose cleaner never
whitened anything would make the equality hold for free. It runs - and passes -
in RED, because it builds its `TranslationResult` without `art_text`.

**RED.** The art run builds `TranslationResult(..., art_text=...)`, which does
not exist yet, so it fails on a `TypeError` naming `art_text` inside the
translate stage; `run_chapter` turns that into an aborted run, and the test
checks the run finished before it looks at a pixel, so the failure reads as
the abort rather than as a pixel count.

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so no
budget to size and no hook to budget. One 160x120 page, masks built with numpy
(not `conftest.one_bit_png`'s per-pixel loop), one bake with the shipped faces:
measured locally in RED at well under a second per test (see the story's
handoff for the number).
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from _bake_world import decode_mask, decode_rgb, encode, mask_png, ring, texture
from numpy.typing import NDArray
from PIL import Image

from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import TokenUsage, TranslationResult
from mangatl.pipeline.bake import BakeReport, bake_chapter
from mangatl.pipeline.runner import RUN_FINISHED, run_chapter
from mangatl.pipeline.stages import build_stages
from mangatl.store.intake import read_chapter
from mangatl.store.project import create_project, project_dir_for

if TYPE_CHECKING:
    from mangatl.domain.glossary import PromptContext

_PAGE_W, _PAGE_H = 160, 120
_FILENAME = "p1.png"

#: The dialogue region: a bubble on the left, two text strokes inside it.
_DIALOGUE_BOX = (6, 6, 78, 56)
_DIALOGUE_STROKES = ((20, 14, 26, 48), (44, 14, 50, 48))

#: The art region: a drawn sign on the right, 40 px clear of the bubble.
_ART_BOX = (118, 70, 154, 112)
_ART_STROKES = ((126, 80, 134, 102), (140, 80, 146, 102))

_ART_TEXT = "ドドド"
_DIALOGUE_TEXT = "どうして君がここに"
_ENGLISH = "Why?"

#: MT-100 C-3: a per-page estimate for the stage; no call is priced here.
_ESTIMATE = Usd.from_micro(30_000)


def _region(
    box: tuple[int, int, int, int], strokes: Sequence[tuple[int, int, int, int]]
) -> RawRegion:
    return RawRegion(
        polygon=ring(*box),
        mask=mask_png(_PAGE_W, _PAGE_H, strokes),
        confidence=0.9,
        kind="bubble",
    )


_DIALOGUE = _region(_DIALOGUE_BOX, _DIALOGUE_STROKES)
_ART = _region(_ART_BOX, _ART_STROKES)


# -- the doubles -------------------------------------------------------------------


class _Detector:
    """A `PageDetector`: the two regions, art first, so the stored reading
    order is `sort_regions`' and not the order given."""

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        return (_ART, _DIALOGUE)


class _MaskWhitener:
    """A `PageCleaner` that paints each handed region's **mask** pixels white
    and leaves every other pixel the source's (C-6), returned as PNG."""

    def __init__(self) -> None:
        self.handed: list[int] = []

    def __call__(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> bytes:
        self.handed.append(len(regions))
        rgb = decode_rgb(image_bytes).copy()
        for region in regions:
            rgb[decode_mask(region.mask)] = 255
        buffer = BytesIO()
        Image.fromarray(rgb, "RGB").save(buffer, format="PNG")
        return buffer.getvalue()


class _Transcriber:
    """A `PageTranscriber` reading the art polygon as `ドドド` and any other as
    the dialogue line."""

    def __call__(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
        return tuple(
            OcrResult(text=_ART_TEXT if region.polygon == _ART.polygon else _DIALOGUE_TEXT)
            for region in regions
        )


class _Translator:
    """A `PageTranslator` lining every region except the art one and, when
    `mark_art`, listing the art one under `art_text`. Keys are indices into
    the listing it was handed. `call=None`: nothing is priced."""

    def __init__(self, *, mark_art: bool) -> None:
        self.mark_art = mark_art

    def __call__(
        self, image_bytes: bytes, results: Sequence[OcrResult], context: PromptContext
    ) -> TranslationResult:
        art = frozenset(i for i, result in enumerate(results) if result.text == _ART_TEXT)
        extra: dict[str, Any] = {"art_text": art} if self.mark_art else {}
        return TranslationResult(
            lines={i: _ENGLISH for i in range(len(results)) if i not in art},
            usage=TokenUsage(0, 0, 0, 0),
            call=None,
            proposed_terms=(),
            **extra,
        )


# -- the run -----------------------------------------------------------------------


def _polygon_mask(box: tuple[int, int, int, int]) -> NDArray[np.bool_]:
    filled = np.zeros((_PAGE_H, _PAGE_W), dtype=np.uint8)
    cv2.fillPoly(filled, [np.array(ring(*box), dtype=np.int32)], 1)
    return filled.astype(bool)


def _run_and_bake(
    tmp_path: Path, *, mark_art: bool
) -> tuple[NDArray[np.uint8], NDArray[np.uint8], BakeReport, tuple[str | None, ...]]:
    """`(source, baked, report, excluded)`: the chapter run through the four
    stages and baked; `excluded` is the stored reason per region."""
    source = texture(_PAGE_W, _PAGE_H, salt=3)
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    (source_dir / _FILENAME).write_bytes(encode(source, "PNG"))
    cleaner = _MaskWhitener()

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        outcome = run_chapter(
            project,
            build_stages(
                _Detector(), cleaner, _Transcriber(), _Translator(mark_art=mark_art), _ESTIMATE
            ),
            lambda event: None,
            lambda: False,
        )
        assert outcome.outcome == RUN_FINISHED, (
            f"the chapter run ended {outcome!r}, so nothing was translated to bake"
        )
        assert cleaner.handed == [2], "the precondition: both regions were cleaned"
        excluded = tuple(region.excluded for region in project.read_regions(0))
        output_dir = tmp_path / "out"
        report = bake_chapter(project, output_dir)

    baked = decode_rgb((output_dir / _FILENAME).read_bytes())
    return source, baked, report, excluded


def _differs(a: NDArray[np.uint8], b: NDArray[np.uint8], where: NDArray[np.bool_]) -> int:
    """Pixels inside `where` at which `a` and `b` differ in any channel."""
    return int(np.count_nonzero(np.any(a != b, axis=-1) & where))


# -- AC-6 ----------------------------------------------------------------------------


def test_a_region_the_model_calls_art_bakes_back_to_the_source_scan_pixel_for_pixel(
    tmp_path: Path,
) -> None:
    """**AC-6**: the art region was erased by the cleaner, marked `art` by the
    translate stage, and in the baked page every pixel inside its polygon
    equals the source scan's - MT-119's restore - so no glyph and no white is
    left there. The dialogue region is typeset, so the page was really baked."""
    source, baked, report, excluded = _run_and_bake(tmp_path, mark_art=True)
    art_polygon = _polygon_mask(_ART_BOX)

    assert sorted(excluded, key=str) == ["art", None], (
        f"the regions read excluded {excluded}; the art region should be `art`"
    )
    assert _differs(baked, source, art_polygon) == 0, (
        f"{_differs(baked, source, art_polygon)} pixel(s) inside the art region's polygon"
        " differ from the source scan in the baked page; AC-6 says none may"
    )
    assert report.regions_empty == 0, f"regions left without text: {report.regions_empty}"
    dialogue_outside_mask = _polygon_mask(_DIALOGUE_BOX) & ~decode_mask(_DIALOGUE.mask)
    assert _differs(baked, source, dialogue_outside_mask) > 0, (
        "nothing was typeset in the dialogue region, so the page was not really baked"
    )


def test_control_with_nothing_marked_art_the_regions_mask_pixels_stay_white(
    tmp_path: Path,
) -> None:
    """**AC-6's control**: the same run with the translator listing nothing.
    The region is included and has no line, so nothing restores it and nothing
    is set there: every one of its mask pixels is the cleaner's white in the
    baked page, and those pixels differ from the source. So the equality above
    is about the exclusion and not about the page.

    Expected values (measured in RED outside pytest, see the handoff): the art
    mask has 308 pixels; all 308 are white here and all 308 differ from the
    source; in the art run 0 polygon pixels differ."""
    source, baked, report, excluded = _run_and_bake(tmp_path, mark_art=False)
    art_mask = decode_mask(_ART.mask)
    mask_pixels = int(np.count_nonzero(art_mask))
    white = np.all(baked == 255, axis=-1) & art_mask

    assert excluded == (None, None)
    assert mask_pixels == 308, "the precondition: the art mask's two strokes"
    assert int(np.count_nonzero(white)) == mask_pixels, (
        f"only {int(np.count_nonzero(white))} of {mask_pixels} art mask pixels are white"
        " with nothing marked art; the control does not see the erase"
    )
    assert _differs(baked, source, art_mask) == mask_pixels
    assert report.regions_empty == 1, "the art region is included and left without text"
