"""The pipeline's stage list: detect, then OCR.

**MT-036 C-1.** MT-035 shipped `DetectStage` and MT-010 shipped `OcrStage`, both
correct and neither in any stage list. This module is the list, and it is a
module of `pipeline` rather than four lines of the composition root because *the
list is a pipeline fact and the sessions are not*: it imports
`pipeline.detect_stage` and `pipeline.ocr_stage` and nothing heavier, so AC-2 is
assertable in `tests/core` with no weights, no GPU and no `onnxruntime`. The
sessions are `mangatl.compose`'s, which is the one module allowed to build them.

**The order is semantic, not stylistic.** `OcrStage.run` reads
`ctx.project.read_regions(...)`, so OCR before detect transcribes the *previous*
run's regions on a resume and nothing at all on a fresh page - a full, plausible
and empty `line` table rather than a crash.

The return type is `tuple[Stage, ...]` rather than a two-tuple of concrete
classes, so the story that adds a translate stage changes one line here and
nothing anywhere else.
"""

from __future__ import annotations

from mangatl.pipeline.detect_stage import DetectStage, PageDetector
from mangatl.pipeline.ocr_stage import OcrStage, PageTranscriber
from mangatl.pipeline.stage import Stage

__all__ = ["build_stages"]


def build_stages(detect: PageDetector, transcribe: PageTranscriber) -> tuple[Stage, ...]:
    """The pipeline's stage list: detect, then OCR.

    Each stage holds the callable it was given and binds nothing of its own: a
    builder that constructed its own detector would be a second composition root
    in the module that exists to have none.
    """
    return (DetectStage(detect=detect), OcrStage(transcribe=transcribe))
