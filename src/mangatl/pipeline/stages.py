"""The pipeline's stage list: detect, then clean, then OCR, then translate.

**MT-036 C-1.** MT-035 shipped `DetectStage` and MT-010 shipped `OcrStage`, both
correct and neither in any stage list. This module is the list, and it is a
module of `pipeline` rather than four lines of the composition root because *the
list is a pipeline fact and the sessions are not*: it imports the stage modules
of `pipeline` and nothing heavier, so the list is assertable in `tests/core`
with no weights, no GPU and no `onnxruntime`. The sessions are
`mangatl.compose`'s, which is the one module allowed to build them.

**The order is semantic, not stylistic.** `OcrStage.run` reads
`ctx.project.read_regions(...)`, so OCR before detect transcribes the *previous*
run's regions on a resume and nothing at all on a fresh page - a full, plausible
and empty `line` table rather than a crash. `CleanStage.run` reads them too, so
it comes after detect as well (MT-065).

**Clean comes before OCR** (MT-065 PO-3). OCR reads the *source scan*, never the
cleaned page, so the position does not change what OCR reads; it keeps every
local, free stage ahead of the paid one, keeps the `--no-translate` list a
prefix of the full one, and keeps the progress stepper on "Reading" rather than
"Translating" while a page is cleaned.

The return type is `tuple[Stage, ...]` rather than a tuple of concrete classes,
so the story that adds a stage changes one line here and nothing anywhere else.
**MT-044 is that story** for translate, and the reason it is a story rather
than a line MT-011 wrote: wiring `TranslateStage` in before the ledger (MT-012)
and the budget guard (MT-013) existed would have made every `mangatl-run` spend
real money with neither, which is the precise failure EPIC-04 exists to
prevent. **MT-065 is that story** for clean.

Importing `pipeline.translate_stage` and `pipeline.clean_stage` is still nothing
heavier: each names its collaborator behind a `Callable` alias and imports
nothing under `mangatl.translate` or `mangatl.clean`, so the list stays
assertable in `tests/core` with no client, no key, no network and no model.
"""

from __future__ import annotations

from mangatl.pipeline.clean_stage import CleanStage, PageCleaner
from mangatl.pipeline.detect_stage import DetectStage, PageDetector
from mangatl.pipeline.ocr_stage import OcrStage, PageTranscriber
from mangatl.pipeline.stage import Stage
from mangatl.pipeline.translate_stage import PageTranslator, TranslateStage

__all__ = ["build_stages"]


def build_stages(
    detect: PageDetector,
    clean: PageCleaner,
    transcribe: PageTranscriber,
    translate: PageTranslator | None,
) -> tuple[Stage, ...]:
    """The pipeline's stage list: detect, clean, OCR, and translate unless asked not to.

    Each stage holds the callable it was given and binds nothing of its own: a
    builder that constructed its own detector would be a second composition root
    in the module that exists to have none.

    **`clean` and `translate` are required and have no default** (MT-044 C-6,
    MT-065 C-6). A *default* would give the project two stage lists - one that
    does the work and one that silently does not - and the one a forgetful
    composition root gets is the second. Required-and-nullable keeps that
    protection whole for `translate`: there is no list a caller gets by saying
    nothing, and `None` is a sentence the caller had to type.

    `None` is `mangatl-run --no-translate` (MT-044 AC-6, MT-065 AC-7): detect,
    clean and OCR, with no API client constructed at all - cleaning is local and
    free, and the flag is about the paid API (MT-065 PO-1). The short list is
    built **here**, as a prefix of the full one, so a composition root never
    assembles its own and the two cannot drift apart.
    """
    stages: tuple[Stage, ...] = (
        DetectStage(detect=detect),
        CleanStage(clean=clean),
        OcrStage(transcribe=transcribe),
    )
    if translate is None:
        return stages
    return (*stages, TranslateStage(translate=translate))
