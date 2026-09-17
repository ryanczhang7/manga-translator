"""The stage that writes one page's transcriptions (MT-010 AC-9).

**This module is `pipeline/ocr_stage.py` and not `ocr/stage.py`, and that is
forced by a required gate rather than chosen for taste** (MT-010 C-1, measured in
PLANNED with a throwaway module). Two of `pyproject.toml`'s contracts bite at
once:

* the `layers` contract puts `mangatl.ocr` *below* `mangatl.pipeline`, so a stage
  living in `mangatl.ocr` may not import `PageContext` at all -

      mangatl.ocr is not allowed to import mangatl.pipeline:
      - mangatl.ocr._probe_layers -> mangatl.pipeline.stage (l.2)

* and the `forbidden` contract *"Only detect, ocr and clean import onnxruntime"*
  lists `mangatl.pipeline` among its `source_modules` with **no**
  `allow_indirect_imports`, while `ocr.page` reaches `onnxruntime` through
  `ocr.session`. So this module may not import `mangatl.ocr` either - not under
  `TYPE_CHECKING`, and not inside a function body, because import-linter reports
  those too (measured on `cli.py` in MT-010 PO-4).

So `OcrStage` names its collaborator behind `PageTranscriber`, whose three halves
are stdlib, `domain` and `domain`, exactly as `DetectStage` names `PageDetector`.
`partial(transcribe_page_regions, session, vocab)` is one, and it is assembled by
whoever builds the stage list - which is MT-036's, not this story's.

**The regions come from the store, not from a fresh detection.** OCR runs over
what the detect stage already wrote, in the order it was written, so a resumed run
transcribes the same regions the user will see highlighted - and a stage that
re-detected would need a detector and would put `onnxruntime` back inside
`pipeline`.

**One write, at the end, and never a clearing write first.** `write_lines`
upserts a page's rows in one transaction, so a transcriber that raises leaves the
previous run's lines exactly where they were. By the time a user re-runs a
chapter those `line` rows may carry `proposed_en` and `final_en` that cost real
money (`architecture.md` §4/§6).

**No transaction is opened here.** `write_lines` opens its own and
`Project.transaction()` is deliberately not reentrant (MT-005 PO-5), so a stage
that wrapped the write would turn it into a `RuntimeError`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.stage import PageContext

__all__ = ["OcrStage", "PageTranscriber"]

#: One page's encoded bytes and its stored regions in, one result per region out.
#: A `Callable` rather than a `Protocol` because any callable will do - a bound
#: `partial`, a class with `__call__`, a function.
PageTranscriber = Callable[[bytes, Sequence[RawRegion]], Sequence[OcrResult]]


@dataclass
class OcrStage:
    """Transcribe one page's stored regions and store the text against them.

    Not `frozen=True` (MT-035 amendment R-1, measured twice there). `Stage.name`
    is declared `name: str`, an instance attribute, and mypy holds an
    implementation to that: a frozen field is a *read-only* attribute and a
    `ClassVar` is a *class* variable, so neither spelling of a frozen dataclass
    satisfies the protocol.
    """

    transcribe: PageTranscriber
    name: str = "ocr"

    def run(self, ctx: PageContext) -> None:
        """Transcribe `ctx.page`'s stored regions and write one line per region.

        The scans are read-only to this app (`architecture.md` §5): the page file
        is read and nothing beside it is written.
        """
        regions = ctx.project.read_regions(ctx.page.ordinal)
        image_bytes = (ctx.project.chapter.source_dir / ctx.page.filename).read_bytes()
        results = self.transcribe(image_bytes, regions)
        ctx.project.write_lines(ctx.page.ordinal, results)

    def is_done(self, ctx: PageContext) -> bool:
        """Whether this page already has **lines** in the store.

        Lines and not regions: regions are what the *detect* stage writes and
        `DetectStage.is_done` reads (MT-035 C-6), and a page with regions and no
        lines is exactly the state a resumed run must pick up at. A page every
        region of which read empty still has rows and is therefore done - which is
        the other half of why `ocr_empty` is stored (MT-010 PO-3). A page with no
        regions at all writes nothing and is never done, matching `DetectStage`'s
        own decision for the same page.
        """
        return bool(ctx.project.read_lines(ctx.page.ordinal))
