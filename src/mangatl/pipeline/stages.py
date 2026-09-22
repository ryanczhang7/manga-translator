"""The pipeline's stage list: detect, then OCR, then translate.

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

The return type is `tuple[Stage, ...]` rather than a tuple of concrete classes,
so the story that adds a stage changes one line here and nothing anywhere else.
**MT-044 is that story**, and the reason it is a story rather than a line MT-011
wrote: wiring `TranslateStage` in before the ledger (MT-012) and the budget
guard (MT-013) existed would have made every `mangatl-run` spend real money
with neither, which is the precise failure EPIC-04 exists to prevent. All three
arrive together here.

Importing `pipeline.translate_stage` is what makes the *list* translate, and it
is still nothing heavier: that module names its collaborator behind
`PageTranslator` and imports nothing under `mangatl.translate`, so AC-4 stays
assertable in `tests/core` with no client, no key and no network.
"""

from __future__ import annotations

from mangatl.pipeline.detect_stage import DetectStage, PageDetector
from mangatl.pipeline.ocr_stage import OcrStage, PageTranscriber
from mangatl.pipeline.stage import Stage
from mangatl.pipeline.translate_stage import PageTranslator, TranslateStage

__all__ = ["build_stages"]


def build_stages(
    detect: PageDetector, transcribe: PageTranscriber, translate: PageTranslator | None
) -> tuple[Stage, ...]:
    """The pipeline's stage list: detect, then OCR, and translate unless asked not to.

    Each stage holds the callable it was given and binds nothing of its own: a
    builder that constructed its own detector would be a second composition root
    in the module that exists to have none.

    **`translate` is required and has no default** (MT-044 C-6, amended in
    GREEN for AC-6). A *default* would give the project two stage lists - one
    that translates and one that silently does not - and the one a forgetful
    composition root gets is the second. Required-and-nullable keeps that
    protection whole: there is no list a caller gets by saying nothing, and
    `None` is a sentence the caller had to type.

    `None` is `mangatl-run --no-translate` (AC-6), which is the opposite of
    silent: the user asked for detect and OCR only, the composition root
    constructs no API client at all, and the short list is built **here**, so
    the story that adds a fourth stage changes this module and no other. A
    composition root that assembled its own two-tuple would be the second stage
    list MT-036 C-1 exists to prevent, and nothing in `tests/core` would notice
    when the two drifted apart.
    """
    stages: tuple[Stage, ...] = (DetectStage(detect=detect), OcrStage(transcribe=transcribe))
    if translate is None:
        return stages
    return (*stages, TranslateStage(translate=translate))
