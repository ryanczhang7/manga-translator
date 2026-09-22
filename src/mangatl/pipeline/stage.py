"""What a stage is, and the identity element that proves the runner sequences.

A stage is a protocol, not a base class: `architecture.md` §2 puts each real
stage behind an adapter with its own dependencies, and inheritance would drag
the orchestrator's imports into every one of them.

`PageContext` carries the `Project` because `is_done` must consult the store -
that is the whole of AC-5 - and because a stage writes its results through
`ctx.project.transaction()`. It carries the `Page` rather than the ordinal so a
stage that needs the filename or the dimensions does not have to re-query.

**`Project.transaction()` is not reentrant** (MT-005 PO-5), so the runner never
holds one open across a call into `run` or `is_done`: the stage owns its
transaction, one per page per stage (§6).

**`BudgetRefused` lives here and not in `translate_stage.py`** (MT-044 C-2).
`runner.py` must catch it and already imports this module; a runner importing
`pipeline.translate_stage` to name an exception would drag the translate stage
into the import graph of every run, including the zero-stage ones
`tests/core/test_pipeline.py` uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mangatl.domain.budget import Decision
from mangatl.domain.page import Page
from mangatl.store.project import PAGE_DONE, Project

__all__ = ["BudgetRefused", "PageContext", "PassThroughStage", "Stage"]


@dataclass(frozen=True)
class PageContext:
    """Everything a stage is given about the page it is working on.

    `run_id` is **required and has no default** (MT-044 C-1). A default of `0`
    would let a stage record a ledger row against a run that does not exist,
    and `llm_call.run_id` is a NOT NULL foreign key to `run(id)` - so a wrong
    value is caught only if no run happens to have that id, and run 1 always
    does. `DetectStage`, `OcrStage` and `PassThroughStage` do not read it; the
    field is here because this is what the runner hands every stage, and a
    second context type for one stage would be worse.
    """

    project: Project
    page: Page
    run_id: int


class BudgetRefused(Exception):
    """The budget guard refused the call this page was about to make.

    An exception rather than a return value, although `domain/budget.py` says a
    refusal "is a `Decision` with `permitted=False`, not an exception". That is
    a rule about the *domain guard* and it still holds - `Budget.check` returns
    a `Decision` here as everywhere. This is the *pipeline's* way of turning
    that decision into a stop, and `Stage.run` returns `None`: there is no
    other channel out of it. The `Decision` travels on the exception so MT-018
    can render the three numbers that justified the refusal.
    """

    def __init__(self, decision: Decision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class Stage(Protocol):
    """One step of the pipeline for one page.

    `is_done` is what makes resume work, and it is per stage per page rather
    than per page: a page that has regions but no translations resumes at
    translation.
    """

    name: str

    def run(self, ctx: PageContext) -> None: ...

    def is_done(self, ctx: PageContext) -> bool: ...


class PassThroughStage:
    """The identity element: a stage that does nothing, correctly.

    Not a placeholder to be deleted when the real stages land. It is what lets
    the runner be exercised with a one-stage list as well as a zero-stage one,
    and it is what AC-5's skip logic has to skip.

    `run` writes nothing at all, so the only question it could answer about
    done-ness is the one the *runner* records: `page.status`. That mirroring is
    the runner's job (`architecture.md` §5), not this stage's.
    """

    name = "passthrough"

    def run(self, ctx: PageContext) -> None:
        """Nothing. A no-op is the whole behaviour of the identity element."""

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE
