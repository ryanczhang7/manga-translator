"""The stage that writes one page's proposed English (MT-011 AC-4..AC-7).

**This module is `pipeline/translate_stage.py` and not `translate/stage.py`, and
that is forced by a required gate rather than chosen for taste** (MT-011 C-1,
measured in PLANNED with throwaway probe modules - PO-3 and PO-4). It is MT-010
C-1 and MT-035 C-1 recurring for the third time, and two of `pyproject.toml`'s
contracts bite at once, from opposite sides:

* the **layers** contract puts `mangatl.translate` *below* `mangatl.pipeline`,
  so a stage living in `mangatl.translate` may not import `PageContext` at all -

      mangatl.translate is not allowed to import mangatl.pipeline:
      - mangatl.translate._probe_layers -> mangatl.pipeline.stage (l.1)

* and the *"Only translate imports anthropic"* contract lists `mangatl.pipeline`
  among its `source_modules` with **no** `allow_indirect_imports`, so this
  module may not import `mangatl.translate` either - not under `TYPE_CHECKING`,
  and not inside a function body, because import-linter reports those too -

      mangatl.pipeline is not allowed to import anthropic:
      -   mangatl.pipeline._probe_chain -> mangatl.translate._probe_client (l.1)
          mangatl.translate._probe_client -> anthropic (l.1)

So `TranslateStage` names its collaborator behind `PageTranslator`, whose every
half is stdlib or `domain`, exactly as `OcrStage` names `PageTranscriber` and
`DetectStage` names `PageDetector`. `partial(translate_page, client)` is one,
and it is assembled by whoever builds the stage list - which is **MT-013's**,
not this story's (C-8, PO-6): wiring this stage into `build_stages` now would
make every `mangatl-run` spend real money with no ledger (MT-012) and no budget
guard (MT-013), the precise failure EPIC-04 exists to prevent.

**The regions and their text come from the store, not from a fresh OCR pass.**
Translation runs over what the OCR stage already wrote, in the order it was
written, so a resumed run translates the same bubbles the user will see
highlighted.

**AC-7's "no API call is made" is not here.** It lives in
`translate/client.py`, where the client is (C-5's RED amendment): this stage has
no client and could not count calls on one. What the stage does for a wordless
page is what it does for any page whose result has no lines - writes nothing,
completes, and leaves whatever an earlier run proposed alone.

**No transaction is opened here.** `write_proposed` opens its own and
`Project.transaction()` is deliberately not reentrant (MT-005 PO-5), so a stage
that wrapped the write would turn it into a `RuntimeError`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mangatl.domain.line import OcrResult
from mangatl.domain.translation import TranslationResult
from mangatl.pipeline.stage import PageContext

__all__ = ["PageTranslator", "TranslateStage"]

#: Page image bytes and the page's OCR results in, one result out.
#: Every half is stdlib or domain. It must NOT name anything in
#: mangatl.translate - that is the contract C-1 is about. A `Callable` rather
#: than a `Protocol` because any callable will do - a bound
#: `partial(translate_page, client)`, a class with `__call__`, a function.
PageTranslator = Callable[[bytes, Sequence[OcrResult]], TranslationResult]


@dataclass
class TranslateStage:
    """Translate one page's stored lines and store the English against them.

    Not `frozen=True` (MT-035 amendment R-1, measured twice there). `Stage.name`
    is declared `name: str`, an instance attribute, and mypy holds an
    implementation to that: a frozen field is a *read-only* attribute and a
    `ClassVar` is a *class* variable, so neither spelling of a frozen dataclass
    satisfies the protocol.
    """

    translate: PageTranslator
    name: str = "translate"

    def run(self, ctx: PageContext) -> None:
        """Translate `ctx.page`'s stored lines and write the proposals.

        One write, at the end, and never a clearing write first: `write_proposed`
        updates only the rows the result names, so a region the model omitted
        keeps its NULL (AC-5) and a page that came back with nothing keeps the
        English an earlier run paid for (AC-7's resume case). A translator that
        raises - AC-6's unknown region index - therefore leaves the page exactly
        as it was, and the exception reaches the runner, which is what turns one
        bad page into one failed page rather than a silent one.

        The scans are read-only to this app (`architecture.md` §5): the page file
        is read and nothing beside it is written.
        """
        ocr_results = ctx.project.read_lines(ctx.page.ordinal)
        image_bytes = (ctx.project.chapter.source_dir / ctx.page.filename).read_bytes()
        result = self.translate(image_bytes, ocr_results)
        ctx.project.write_proposed(ctx.page.ordinal, result.lines)

    def is_done(self, ctx: PageContext) -> bool:
        """Whether this page already carries a **proposal**.

        Proposals and not lines: lines are what the *OCR* stage writes and
        `OcrStage.is_done` reads (MT-010 C-6), and a page with lines and no
        proposals is exactly the state a resumed run must pick up at - the same
        reasoning one stage along. A page with no regions at all is never done,
        matching what `DetectStage` and `OcrStage` both decide for it.

        The consequence, decided rather than stumbled into (MT-011 PO-10): a
        page the model returned no line at all for is re-translated on the next
        run, and that costs money. It is also the only behaviour that lets a
        failed page ever recover, and MT-013's budget guard is what bounds it.
        AC-7's all-empty page is never done either, and re-running it is free -
        `translate_page` makes no call for it.
        """
        return any(proposed is not None for proposed in ctx.project.read_proposed(ctx.page.ordinal))
