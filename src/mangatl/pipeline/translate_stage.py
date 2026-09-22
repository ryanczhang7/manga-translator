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
and it is assembled by whoever builds the stage list. **MT-044 is the story that
wired it**: MT-011 deferred that to the story with the ledger and the guard in
it, because wiring this stage in before them would make every `mangatl-run`
spend real money with neither, the precise failure EPIC-04 exists to prevent.
This module imports `domain.budget`, `domain.rates` and `store.ledger` - all
down the layers - and still imports nothing under `mangatl.translate`.

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

from mangatl.domain.budget import Budget
from mangatl.domain.line import OcrResult
from mangatl.domain.rates import price
from mangatl.domain.translation import TranslationResult
from mangatl.pipeline.stage import BudgetRefused, PageContext
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.project import Project

__all__ = ["PageTranslator", "TranslateStage", "budget_for", "pages_remaining"]

#: Page image bytes and the page's OCR results in, one result out.
#: Every half is stdlib or domain. It must NOT name anything in
#: mangatl.translate - that is the contract C-1 is about. A `Callable` rather
#: than a `Protocol` because any callable will do - a bound
#: `partial(translate_page, client)`, a class with `__call__`, a function.
PageTranslator = Callable[[bytes, Sequence[OcrResult]], TranslationResult]


def budget_for(project: Project) -> Budget:
    """The guard for this chapter's run: the stored ceiling, or the default.

    MT-044 AC-5, both halves, and the seam between the two layers that each own
    one of them: the *store* reports what is stored and `None` when nothing is
    (C-10), and `DEFAULT_CEILING` is a *domain* constant the store may not
    import. This function is where they meet, which is `pipeline`'s job.

    **`if ceiling is None` and never `ceiling or Budget()`.** `Usd` is a
    dataclass with no `__bool__`, so `Usd(Decimal("0.00"))` is truthy and the
    `or` spelling happens to work - until someone gives `Usd` a `__bool__` or a
    `__len__`, at which point a stored $0.00 ceiling (MT-013 AC-7's "refuses
    everything, forever") silently becomes $2.00. The two spellings are one
    word apart in a diff.
    """
    ceiling = project.budget_ceiling()
    if ceiling is None:
        return Budget()
    return Budget(ceiling)


def pages_remaining(ctx: PageContext) -> int:
    """Pages from this one to the end of the chapter, this one included.

    Ordinals are contiguous from 0 (MT-004), so this is exact: on the first page
    of a 20-page chapter it is 20, on the last it is 1, and it is never 0.

    **It feeds `Projection.remaining_chapter` only.** `Budget.check` compares
    `spent + projection.next_call` against the ceiling and never reads
    `remaining_chapter`, so an off-by-one here changes a number MT-018 displays
    and changes no permit or refusal. Pinned anyway, because "it does not affect
    the decision" is a reason to get it right once rather than to leave it.
    """
    return len(ctx.project.pages()) - ctx.page.ordinal


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
        """Guard, call, record the bill, write the proposals - in that order.

        One write of the proposals, at the end, and never a clearing write
        first: `write_proposed` updates only the rows the result names, so a
        region the model omitted keeps its NULL (AC-5) and a page that came back
        with nothing keeps the English an earlier run paid for (AC-7's resume
        case). A translator that raises - AC-6's unknown region index -
        therefore leaves the page exactly as it was, and the exception reaches
        the runner, which is what turns one bad page into one failed page rather
        than a silent one.

        The scans are read-only to this app (`architecture.md` §5): the page file
        is read and nothing beside it is written.

        **Four orderings here are the substance of MT-044 C-7, not its shape.**

        1. **The guard is before `self.translate(...)`**, which is AC-2 and the
           whole of `architecture.md` D6: "a guard that notices the overrun
           after paying for it has not guarded anything". The refusal leaves the
           page untouched - no call, no ledger row, no proposals - and reaches
           the runner as `BudgetRefused`, which maps it to `reason="budget"`.
        2. **`record_call` before `write_proposed`.** Both open their own
           transaction and `Project.transaction()` is not reentrant (MT-005
           PO-5), so they are two commits with a window between them, and a
           crash in that window resolves differently depending on the order.
           Proposals-first loses the *bill*: the page reads `is_done` on the
           next run, is never re-translated, and the spend is missing from
           `chapter_total` **for the life of the chapter** - the guard goes
           quietly inert, which is the exact failure this story ends.
           Ledger-first loses the *proposals*: the page is re-translated and
           billed twice, and both bills are in the ledger. Over-reporting spend
           is recoverable; under-reporting it is not.
        3. **`price(...)` sits inside the `record_call` argument list**, so an
           `UnknownModel` (C-5's named cost) raises before *either* write. A
           page whose model cannot be priced writes nothing and aborts the run
           through the runner's general arm. The trade-off is accepted and
           named: a paid-for translation is lost. `rates.py` already decided it.
        4. **No transaction is opened here.** Unchanged from MT-011 and for its
           reason: `write_proposed` and `record_call` each open their own, and a
           stage that wrapped them would turn both into `RuntimeError`.

        `chapter_call_costs` is read **per page and is deliberately not cached**
        (F-4): a cached sample set is a guard reading a stale spend, which is
        this story's whole subject. One `SELECT` a page is nothing at 20 pages.
        """
        ocr_results = ctx.project.read_lines(ctx.page.ordinal)
        budget = budget_for(ctx.project)
        projection = budget.project(chapter_call_costs(ctx.project), pages_remaining(ctx))
        decision = budget.check(chapter_total(ctx.project), projection)
        if not decision.permitted:
            raise BudgetRefused(decision)

        image_bytes = (ctx.project.chapter.source_dir / ctx.page.filename).read_bytes()
        result = self.translate(image_bytes, ocr_results)
        if result.call is not None:
            record_call(
                ctx.project,
                ctx.run_id,
                ctx.page.ordinal,
                result.call.request_id,
                price(result.call.model_id, result.usage),
            )
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
