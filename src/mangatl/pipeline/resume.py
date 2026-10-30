"""A re-run stated before it runs: the pages each stage would redo, and the cost.

EPIC-11 PO-1 and PO-2, MT-124. The workspace's "Run again" (MT-125) needs to say
what a run would do *before* it does it, the way "Render pages" has
`preview_bake`. The statement is computed by the runner's own rule, so the two
cannot disagree: **each stage's own `is_done`**, consulted through a
`PageContext` exactly as `runner._run_page` consults it - never `page_status`,
which calls a page `done` that a later story has since emptied of its cleaned
image (MT-119 AC-5c, MT-124 AC-6).

**One `is_done` per stage per page** (AC-5). The runner asks `all(...)` and then
asks again per stage; a preview has no reason to, and a 200-page chapter
previews in one pass. A page is one the run would *start* exactly when some
stage on it is not done - which for an empty stage list is never, so the
preview says 0 for a zero-stage run, stated rather than stumbled into (AC-1).

**The money is the guard's own** (PO-2): `budget_for` and `Budget.project`,
the very calls `TranslateStage.run` makes before every page, over the
chapter's priced calls. Nothing is priced here and nothing is re-derived: the
estimate is the projection's `remaining_chapter` for the pages the translate
stage would run, and `within_budget` is `Budget.check`'s inclusive comparison
applied to that whole figure.

**It writes nothing and runs nothing.** No transaction is opened, no `run` is
called, and the context handed to `is_done` carries no run (`_NO_RUN`) and an
`emit` that refuses (C-2): a stage that wrote or emitted from `is_done` fails
loudly rather than mis-filing a bill against a run that does not exist.

This module imports nothing under `mangatl.detect`, `mangatl.clean`,
`mangatl.ocr` or `mangatl.translate`: the stages arrive already built.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mangatl.domain.events import RunEvent
from mangatl.domain.money import Usd
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.pipeline.translate_stage import budget_for
from mangatl.store.ledger import chapter_call_costs, chapter_total
from mangatl.store.project import Project

__all__ = ["RerunPreview", "rerun_preview"]

#: No run exists yet. Rowids start at 1, so `0` is no run's id, and the
#: `llm_call.run_id` foreign key would refuse a row carrying it (C-2).
_NO_RUN = 0

#: The stage name whose pending count is the number of pages to translate.
_TRANSLATE = "translate"


def _refuse(event: RunEvent) -> None:
    raise RuntimeError("a stage emitted an event from is_done; a preview runs nothing")


@dataclass(frozen=True)
class RerunPreview:
    """What a run of `stages` over the project would do now, stated before
    it runs, from each stage's own `is_done` (EPIC-11 PO-1)."""

    page_count: int
    pages_to_run: int
    pending: Mapping[str, int]
    pages_to_translate: int
    spent: Usd
    ceiling: Usd
    estimate: Usd
    within_budget: bool


def rerun_preview(project: Project, stages: Sequence[Stage], page_estimate: Usd) -> RerunPreview:
    """Consult every stage's `is_done` once per page, through a `PageContext`
    as the runner would, and price the pages the translate stage would run.
    Opens no transaction, writes nothing, calls no `run`."""
    pages = project.pages()
    pending: dict[str, int] = {stage.name: 0 for stage in stages}
    pages_to_run = 0
    for page in pages:
        ctx = PageContext(project=project, page=page, run_id=_NO_RUN, emit=_refuse)
        page_pending = False
        for stage in stages:
            if not stage.is_done(ctx):
                pending[stage.name] += 1
                page_pending = True
        if page_pending:
            pages_to_run += 1

    pages_to_translate = pending.get(_TRANSLATE, 0)
    budget = budget_for(project, page_estimate)
    estimate = budget.project(chapter_call_costs(project), pages_to_translate).remaining_chapter
    spent = chapter_total(project)
    return RerunPreview(
        page_count=len(pages),
        pages_to_run=pages_to_run,
        pending=pending,
        pages_to_translate=pages_to_translate,
        spent=spent,
        ceiling=budget.ceiling,
        estimate=estimate,
        within_budget=bool(spent + estimate <= budget.ceiling),
    )
