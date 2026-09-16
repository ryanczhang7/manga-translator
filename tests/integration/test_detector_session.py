"""AC-7 and AC-8: the real detector, the real pages, on the machine with the GPU.

**The first test in this directory** (MT-002 PO-1, inherited note 1). Everything
here is marked `gpu` and never runs on CI; the `integration` gate is optional
for that reason, and MT-007 escalates it to required on the machine running the
loop only. The `waiver | integration` line in `.claude/harness/project.conf`
must come out now that this file exists - `gates.sh` fails a required gate that
carries a waiver, and a waiver over a gate that can now really fail is a bypass.

**Why these two criteria cannot be met anywhere else.** AC-7's subject is the
model: that the provider actually selected is the one reported, that the graph
returns the three heads at the shapes MT-002 measured, and that its box head
covers 0.000 of the six annotated SFX areas. AC-8's subject is recall against
nine regions MT-002 confirmed as real text by reading them back through
manga-ocr and MT-030 re-measured byte-identically. Neither is a property of this
repository's code; a synthetic fixture would make both true by construction, and
PO-3 records that being considered and rejected.

**The data is gitignored and the tests skip cleanly without it.** The pages, the
model and the frozen reference all live under `spikes/**`, which `.gitignore`
covers: they are non-redistributable scans of a commercial release and a
GPL-3.0 model's weights (MT-007 C-9 / PO-2). A checkout without them skips.

Timings measured in RED on this machine, so GATES is not surprised: one
inference is 29.5 ms mean / 28.3 ms min over 10 runs on `CUDAExecutionProvider`,
and building the session costs a few seconds once, which is why the session is a
module-scoped fixture. `pytest-timeout` is not a dependency of this project and
no per-test timeout exists, so there is no budget in this file to size - if a
later story adds one, every hook here needs one too.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.detect.postprocess import (
    decode_boxes,
    letterbox,
    probability_to_page,
    regions_from_detection,
)
from mangatl.detect.session import (
    MODEL_INPUT_SIDE,
    DetectorSession,
    RawDetectorOutput,
    load_detector,
    selected_provider,
)

pytestmark = pytest.mark.gpu

_SPIKES = Path(__file__).resolve().parents[2] / "spikes"
_MODEL = _SPIKES / "MT-002" / "models" / "comic-text-detector-onnx" / "comic-text-detector.onnx"
_PAGES = _SPIKES / "MT-002" / "pages"
_REFERENCE_014 = _SPIKES / "MT-030" / "out" / "w2-reference-014.json"

_PROVIDERS = ("CUDAExecutionProvider", "CPUExecutionProvider")

# The six art-integrated SFX rectangles MT-030 annotated on `012.jpg` at full
# resolution, transcribed from `spikes/MT-030/sfx.py` (gitignored, so they are
# written out here rather than imported). `x0, y0, x1, y1` on the 1125x1600 scan,
# tight on the glyph strokes so that no rectangle can be satisfied by an adjacent
# speech bubble.
_SFX_012: dict[str, tuple[int, int, int, int]] = {
    "S1 left-panel left": (85, 480, 145, 600),
    "S2 left-panel right": (378, 486, 438, 612),
    "S3 mid-panel upper": (543, 458, 612, 570),
    "S4 mid-panel lower": (503, 562, 570, 665),
    "S5 inset pa": (393, 733, 452, 792),
    "S6 inset chi": (698, 743, 748, 792),
}


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path} is not present: gitignored spike data, see the module docstring")


@pytest.fixture(scope="module")
def session() -> Iterator[DetectorSession]:
    _require(_MODEL)
    yield load_detector(_MODEL, _PROVIDERS)


def _page(name: str) -> NDArray[np.uint8]:
    _require(_PAGES / name)
    with Image.open(_PAGES / name) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _detect(session: DetectorSession, name: str) -> tuple[Any, ...]:
    """Letterbox, run, and post-process one real page - the whole path AC-7 walks."""
    page = _page(name)
    height, width = page.shape[:2]
    canvas, transform = letterbox(page)
    raw = session.run(canvas)
    boxes = decode_boxes(raw.blk, transform, (width, height))
    prob = probability_to_page(raw.seg, transform, (width, height))
    regions = regions_from_detection(prob, boxes, (width, height))
    return raw, boxes, prob, regions, (width, height)


def _mask_array(region: Any, size: tuple[int, int]) -> NDArray[np.bool_]:
    with Image.open(BytesIO(region.mask)) as image:
        array = np.array(image, dtype=bool)
    assert array.shape == (size[1], size[0])
    return array


class _ProviderProxy:
    """A session that answers `get_providers()` and refuses the dishonest call.

    MT-002 E2/PO-3 measured that `get_available_providers()` advertises CUDA
    identically whether or not the DLLs loaded, and that asking for CUDA does not
    raise when onnxruntime silently falls back to CPU - 578 ms against 23 ms, a
    wrong answer with no error anywhere. `selected_provider` must therefore read
    `get_providers()`, and this proxy is how that is asserted rather than
    assumed.
    """

    def __init__(self, inner: DetectorSession) -> None:
        self._inner = inner

    def get_providers(self) -> Sequence[str]:
        return self._inner.get_providers()

    def get_available_providers(self) -> Sequence[str]:
        raise AssertionError(
            "selected_provider called get_available_providers(), which MT-002 E2"
            " measured to be dishonest: it advertises CUDA whether or not the"
            " DLLs loaded"
        )

    def run(self, canvas: NDArray[np.float32]) -> RawDetectorOutput:
        return self._inner.run(canvas)


def test_the_provider_actually_selected_is_the_one_the_session_reports(
    session: DetectorSession,
) -> None:
    """AC-7's first clause."""
    reported = session.get_providers()

    assert selected_provider(session) == reported[0]
    assert selected_provider(_ProviderProxy(session)) == reported[0]
    assert reported[0] == "CUDAExecutionProvider", (
        f"CUDAExecutionProvider is not in available provider names: {list(reported)}."
        " Either ort.preload_dlls(cuda=True, cudnn=True, msvc=True) did not run"
        " before the first InferenceSession, or this machine has no CUDA."
    )


def test_the_graph_returns_blk_seg_and_det_at_the_shapes_the_audit_measured(
    session: DetectorSession,
) -> None:
    """AC-7's second clause, against MT-002 E3's measured I/O signature -
    re-verified in MT-007 RED, on this machine, against this file."""
    page = _page("012.jpg")
    canvas, _transform = letterbox(page)

    raw = session.run(canvas)

    assert canvas.shape == (1, 3, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE)
    assert raw.blk.shape == (1, 64512, 7)
    assert raw.seg.shape == (1, 1, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE)
    assert raw.det.shape == (1, 2, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE)
    assert raw.blk.dtype == np.float32
    assert raw.seg.dtype == np.float32
    assert raw.det.dtype == np.float32
    assert float(raw.seg.min()) >= 0.0
    assert float(raw.seg.max()) <= 1.0


def test_post_processing_a_real_page_yields_regions_with_masks(
    session: DetectorSession,
) -> None:
    """AC-7's third clause. "At least one region" is the criterion's word; AC-8
    is what stops that being a detector which found one blob."""
    _raw, boxes, _prob, regions, size = _detect(session, "012.jpg")

    assert len(boxes) >= 1
    assert len(regions) >= 1
    for region in regions:
        assert _mask_array(region, size).any()
        assert region.kind in {"bubble", "box"}
        assert 0.0 <= region.confidence <= 1.0


def test_the_decoded_box_head_covers_none_of_the_six_annotated_sfx_areas(
    session: DetectorSession,
) -> None:
    """AC-7's fourth clause, and the mechanism the whole story rests on.

    MT-030 E6 and MT-007 PO-1 both measured 0.000 for all six while the mask head
    covers 27-59% of them; MT-007 RED reproduced it a third time, independently,
    on this machine. If this ever fails, AC-6 has lost its mechanism and MT-019
    has lost `seg n accepted boxes` - see the story's licence note.
    """
    _raw, boxes, _prob, _regions, (width, height) = _detect(session, "012.jpg")

    covered = np.zeros((height, width), dtype=bool)
    for x0, y0, x1, y1 in boxes[:, :4].astype(int):
        covered[y0:y1, x0:x1] = True

    coverage = {
        name: float(covered[y0:y1, x0:x1].sum()) / ((x1 - x0) * (y1 - y0))
        for name, (x0, y0, x1, y1) in _SFX_012.items()
    }
    assert coverage == {name: pytest.approx(0.0, abs=5e-4) for name in _SFX_012}


def test_every_one_of_the_nine_frozen_reference_boxes_is_overlapped_by_a_region(
    session: DetectorSession,
) -> None:
    """AC-8, and EPIC-03's done-when: on the fixture pages every text-bearing
    bubble is found.

    The nine were measured by MT-002 E5, independently re-measured by MT-030 E3
    byte-identically, and their OCR is recorded alongside them - so they are real
    text rather than a count. RED measured every one of them overlapped by at
    least 2590 mask pixels at thresholds 0.30, 0.50 and 0.772; the assertion is
    the criterion's own "at least one pixel", and the measured margin is three
    orders of magnitude clear of it.
    """
    _require(_REFERENCE_014)
    reference = json.loads(_REFERENCE_014.read_text(encoding="utf-8"))
    frozen = [tuple(int(v) for v in row["box"]) for row in reference["regions"]]
    assert len(frozen) == 9, "the frozen reference set is nine boxes"

    _raw, _boxes, _prob, regions, size = _detect(session, "014.jpg")
    masks = [_mask_array(region, size) for region in regions]

    missed = [
        (index, box)
        for index, box in enumerate(frozen)
        if not any(mask[box[1] : box[3], box[0] : box[2]].any() for mask in masks)
    ]
    assert missed == [], f"{len(missed)} of 9 reference boxes have no region: {missed}"
