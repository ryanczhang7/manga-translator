"""The whole OCR chain for one page: encoded bytes and regions in, text out.

`preprocess`, `session`, `generate` and `decode` are each correct on their own;
this is the one place they are composed, and it mirrors `detect.page` for the
same reason MT-035 C-1 gives - the composition lives in the package that is
allowed to name a session, because `pyproject.toml`'s contract *"Only detect, ocr
and clean import onnxruntime"* lists `mangatl.pipeline` among its
`source_modules` with no `allow_indirect_imports`. The stage that calls this one
takes it injected behind a plain `Callable` (`pipeline.ocr_stage.PageTranscriber`).

**Every region is encoded from its own crop and decoded against its own hidden
state.** With no KV cache the hidden state is the only thing carrying which crop
is being read, so a loop that encoded nine regions and then decoded them all
against the last hidden state produces one plausible Japanese sentence nine
times, and nothing but an assertion on that wire would notice.

**OCR may not decide whether a region contains text.** MT-002 E5 Test 3 measured
this export producing a confident `それは、` on a blank white margin, and it
exposes no score at all. So nothing here thresholds, and `ocr_empty` records what
the model *did* - emitted no tokens - rather than a judgement about the crop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial
from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.ocr.decode import decode
from mangatl.ocr.generate import greedy_generate
from mangatl.ocr.preprocess import MODEL_INPUT_SIZE, crop_for_region, to_model_input
from mangatl.ocr.session import OcrSession

__all__ = ["OCR_MIN_ACCURACY", "transcribe_page_regions"]

#: The character-level accuracy - `1 - normalised Levenshtein distance` against a
#: hand annotation - every crop of vertical Japanese must reach (MT-010 AC-6/C-8).
#:
#: **Measured in GREEN**, through this module, on the nine regions the real
#: detector finds on `spikes/MT-002/pages/014.jpg`: **1.0000 on every one of the
#: nine**. The threshold is set 5 points below that, which is headroom for a crop
#: this corpus does not contain rather than a number the implementation scored.
#:
#: It is bounded below by a second measurement, and that is what makes it a
#: threshold rather than taste: with `decode`'s h2z normalisation removed the same
#: nine score a mean of 0.9222, the worst of them 0.4000 and the next 0.9000. A
#: threshold at or below 0.9000 would let that step be deleted without AC-6
#: noticing (MT-010 C-7), so the band is (0.9000, 1.0000) and 0.95 sits in the
#: middle of it. The rotated-crop control scores a mean of 0.0947.
OCR_MIN_ACCURACY: float = 0.95


def transcribe_page_regions(
    session: OcrSession,
    vocab: Mapping[int, str],
    image_bytes: bytes,
    regions: Sequence[RawRegion],
) -> list[OcrResult]:
    """One result per region, in the order the regions were handed over.

    Position is the mapping: `results[i]` belongs to `regions[i]`, because a
    `RawRegion` carries no id of its own (MT-009 PO-1). Reading order is already
    fixed by the time these arrive, and nothing here sorts.

    `session` comes first because it is the argument a caller binds once:
    `partial(transcribe_page_regions, session, vocab)` is a `PageTranscriber`,
    which is what `pipeline.ocr_stage.OcrStage` wants.

    A page with no regions performs no inference at all - the loop simply does
    not run - which is the honest cost of a page the detector found no text on
    (MT-035 AC-5).
    """
    page = _decoded_page(image_bytes)
    results: list[OcrResult] = []
    for region in regions:
        hidden = session.encode(to_model_input(crop_for_region(page, region), MODEL_INPUT_SIZE))
        # This crop's hidden state bound into the step, so the loop in
        # `generate` stays pure and this region's decode cannot reach another
        # region's encode.
        generated = greedy_generate(partial(session.decode_step, hidden))
        results.append(OcrResult(text=decode(generated, vocab), ocr_empty=not generated))
    return results


def _decoded_page(image_bytes: bytes) -> NDArray[np.uint8]:
    """`image_bytes` as an `(height, width, 3)` RGB `uint8` array.

    Bytes rather than an array is the boundary `detect.page.detect_page_regions`
    already draws: the decode belongs to the adapter, and `domain` may not import
    PIL (`architecture.md` §3 contract 2).

    **`.convert("RGB")` is load-bearing** (MT-035 amendment R-2): a greyscale
    scan - which for manga is not the corner case - decodes to PIL mode `L` and
    `np.asarray` of it is two-dimensional, which would make every crop below
    two-dimensional too.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)
