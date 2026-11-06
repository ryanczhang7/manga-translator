"""The run: walk the chapter's pages in order, emit events, record the outcome.

`architecture.md` §6 and D8. Commands in - `stages`, `emit`, `cancelled` - and
typed events out. Nothing here knows what a widget is, which is what AC-9
asserts and what keeps MT-018's readout testable without a GPU and an API key:
the UI adapts a Qt signal to `emit` and a thread's interruption flag to
`cancelled`, and that adaptation lives in `ui`.

Four decisions are load-bearing, and each is a test away from being wrong:

1. **`cancelled()` is consulted at the top of the page loop and at the top of
   the stage loop, and nowhere else.** A half-done stage must be re-run, and for
   the translation stage half-done means money already spent - so the boundary
   is the stage, and the granularity of loss is one stage of one page. A page
   whose stages have all completed is marked done *before* the next boundary is
   consulted, which is what gives "cancel during page 2" its exact event stream.
2. **The runner holds no transaction across a call into a stage.**
   `Project.transaction()` is deliberately not reentrant (MT-005 PO-5) and every
   real stage writes through `ctx.project.transaction()`, so a runner that
   wrapped the page in one would turn all of them into `RuntimeError`.
3. **The skip predicate is `stages and all(...)`, not `all(...)`.** `all([])` is
   `True`, so a zero-stage run would otherwise report every page as already
   done and skip the chapter. **There are two skips and the second did not
   replace the first** (MT-036 C-4): a page every stage of which is done is
   skipped before it is started, and inside a page that *is* started, a stage
   that is done is not run. Replacing the page-level check with the per-stage
   one satisfies "resume at OCR" and turns every fully-done page from a
   `PageSkipped` into a `PageStarted` with no stages in it.
4. **`pages_done` is how many pages are complete when the run ends** - the ones
   this run processed *plus* the ones it skipped as already done - and never the
   page an abort happened on. The alternative reading makes a fully translated
   chapter report zero. In a two-pass run "complete" means through the final
   pass (MT-130 PO-6), so a run that never reaches it reports zero.

**Two passes (MT-130 C-1).** With `after_prelude` non-empty the run walks every
page through `stages` (the reading pass), consults `cancelled()` once, runs the
chapter step, then walks every page through `after_prelude` (the translating
pass), each pass announced by `PassStarted`. Only the final pass marks a page
done (PO-7): `PAGE_DONE` reads as "every stage done" everywhere it is read. With
`after_prelude=()` and no prelude the run is the single pass above, its stream
unchanged and no `PassStarted` in it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from mangatl.domain.events import (
    PageSkipped,
    PageStarted,
    PassStarted,
    RunAborted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.domain.page import Page
from mangatl.pipeline.prelude import ChapterStep
from mangatl.pipeline.stage import BudgetRefused, PageContext, Stage
from mangatl.store.project import PAGE_DONE, Project

__all__ = [
    "BUDGET",
    "READING",
    "RUN_ABORTED",
    "RUN_FINISHED",
    "TRANSLATING",
    "RunOutcome",
    "run_chapter",
]

#: `PassStarted.name` for the two passes. Constants beside BUDGET/CANCELLED
#: for their reason: the panel and the CLI import them rather than re-spell.
READING = "reading"
TRANSLATING = "translating"

#: The two values written to the `run` row's `outcome` column, and carried on
#: `RunOutcome.outcome`. One value in two places, so AC-1's "ends with outcome
#: `finished`" can be asserted against the store as well as against the return.
RUN_FINISHED = "finished"
RUN_ABORTED = "aborted"

#: `RunAborted.reason` for a cancellation. A cancel is not an error, so it reads
#: as itself rather than as an exception message, and it names no page.
CANCELLED = "cancelled"

#: `RunAborted.reason` for a budget refusal. MT-044 AC-1 pins this exact string,
#: and it is a constant here beside `RUN_ABORTED` and `RUN_FINISHED` for their
#: reason: the criterion asserts the value and a test should not re-spell it.
BUDGET = "budget"

#: `PageSkipped.reason`. Free text for the user, not a code anything branches on.
ALREADY_DONE = "already done"

_INSERT_RUN = "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)"
_FINISH_RUN = "UPDATE run SET ended_at = ?, outcome = ?, aborted_reason = ? WHERE id = ?"


@dataclass(frozen=True)
class RunOutcome:
    """What a finished or aborted run reports back to whoever started it."""

    run_id: int
    outcome: str
    pages_done: int
    aborted_reason: str | None


@dataclass
class _Progress:
    """The runner's own bookkeeping while it walks the chapter.

    A mutable record rather than four locals threaded through a helper: the page
    walk has two exits (a cancel and a raise) and both have to leave the same
    four facts behind.
    """

    pages_done: int = 0
    reason: str | None = None
    ordinal: int | None = None


def run_chapter(
    project: Project,
    stages: Sequence[Stage],
    emit: Callable[[RunEvent], None],
    cancelled: Callable[[], bool],
    *,
    prelude: ChapterStep | None = None,
    after_prelude: Sequence[Stage] = (),
    postlude: ChapterStep | None = None,
) -> RunOutcome:
    """Walk every page of `project`'s chapter through `stages`, in ordinal order,
    then - in a two-pass run - every page through `after_prelude`.

    Returns rather than raises on a stage failure: AC-4 says the run *emits*
    `RunAborted`, and a runner that let the exception through would leave
    MT-015's worker thread dead with the progress readout stuck on the page that
    failed.

    `stages` is the pass before the prelude's slot and `after_prelude` the pass
    after it (MT-130 C-1). Two-pass mode is `bool(after_prelude)`: emit
    `PassStarted(READING)`, walk `stages` marking no page done, consult
    `cancelled()` once, emit `PassStarted(TRANSLATING)`, run `prelude`, walk
    `after_prelude` marking each page done.

    `prelude` (MT-105) is the chapter step, run once with the run's id and its
    own `emit`. It fails as a stage fails - `BudgetRefused` as
    `reason="budget"`, anything else as its type and message - except that it
    names no page (`ordinal=None`), and the run then starts no page of the
    pass after it. A prelude with `after_prelude=()` (MT-130 A-R1, no caller
    does this) runs after the one pass, behind the same single `cancelled()`
    check, with no `PassStarted` emitted.

    `postlude` (MT-115) is the chapter step run once after the final pass -
    after `after_prelude` in a two-pass run, after `stages` in a one-pass run -
    and before the run ends; only when every page completed, so never after a
    failed prelude, a failed page or a cancel. It fails as the prelude fails,
    naming no page, and the run then ends `RunAborted` with every page done
    and no `RunFinished`: `RunFinished` means the pages **and** the step are
    done (AC-6, PO-3).
    """
    pages = project.pages()
    run_id = _start_run(project)
    emit(RunStarted(run_id=run_id, page_count=len(pages)))

    progress = _Progress()
    two_pass = bool(after_prelude)
    if two_pass:
        emit(PassStarted(name=READING))
    _run_pass(project, pages, stages, run_id, emit, cancelled, progress, final=not two_pass)
    if progress.reason is None and (two_pass or prelude is not None):
        # C-1 step 4 (PO-8): the one boundary between the passes, before the
        # first paid call of the run. A cancel set *during* the prelude is
        # honoured at the next pass's first page-loop check.
        if cancelled():
            progress.reason = CANCELLED
        else:
            if two_pass:
                emit(PassStarted(name=TRANSLATING))
            if prelude is not None:
                _run_prelude(prelude, project, run_id, emit, progress)
    if two_pass and progress.reason is None:
        _run_pass(project, pages, after_prelude, run_id, emit, cancelled, progress, final=True)
    if progress.reason is None and postlude is not None:
        _run_prelude(postlude, project, run_id, emit, progress)

    outcome = RUN_FINISHED if progress.reason is None else RUN_ABORTED
    _end_run(project, run_id, outcome, progress.reason)
    if progress.reason is None:
        emit(RunFinished(run_id=run_id, pages_done=progress.pages_done))
    else:
        emit(RunAborted(reason=progress.reason, ordinal=progress.ordinal))
    return RunOutcome(
        run_id=run_id,
        outcome=outcome,
        pages_done=progress.pages_done,
        aborted_reason=progress.reason,
    )


def _run_pass(
    project: Project,
    pages: Sequence[Page],
    stages: Sequence[Stage],
    run_id: int,
    emit: Callable[[RunEvent], None],
    cancelled: Callable[[], bool],
    progress: _Progress,
    *,
    final: bool,
) -> None:
    """Walk every page through `stages`, stopping at a cancel or a failure.

    Only the `final` pass marks pages done and counts them (PO-6, PO-7).
    """
    for page in pages:
        if cancelled():
            progress.reason = CANCELLED
            return
        ctx = PageContext(project=project, page=page, run_id=run_id, emit=emit)
        if not _run_page(project, ctx, stages, emit, cancelled, progress, mark_done=final):
            return
        if final:
            progress.pages_done += 1


def _run_prelude(
    prelude: ChapterStep,
    project: Project,
    run_id: int,
    emit: Callable[[RunEvent], None],
    progress: _Progress,
) -> None:
    """Run the chapter step, turning a failure into the run's abort reason.

    `BudgetRefused` before the general arm, for `_run_page`'s reason: it *is*
    an `Exception`. `progress.ordinal` stays `None` - the step is no page's.
    """
    try:
        prelude(project, run_id, emit)
    except BudgetRefused:
        progress.reason = BUDGET
    except Exception as error:
        progress.reason = f"{type(error).__name__}: {error}"


def _run_page(
    project: Project,
    ctx: PageContext,
    stages: Sequence[Stage],
    emit: Callable[[RunEvent], None],
    cancelled: Callable[[], bool],
    progress: _Progress,
    *,
    mark_done: bool,
) -> bool:
    """Take one page through every stage. `False` means the run must stop.

    A page that was already complete is skipped and still counts towards
    `pages_done`: it is done, whoever did it. `mark_done` is `False` in the
    reading pass of a two-pass run, which marks nothing (PO-7).
    """
    ordinal = ctx.page.ordinal
    if stages and all(stage.is_done(ctx) for stage in stages):
        emit(PageSkipped(ordinal=ordinal, reason=ALREADY_DONE))
        return True

    emit(PageStarted(ordinal=ordinal))
    for stage in stages:
        if cancelled():
            progress.reason = CANCELLED
            return False
        if stage.is_done(ctx):
            # Per stage per page (MT-036 C-4), which is what `Stage.is_done`'s
            # docstring has always claimed: a page that has regions but no
            # transcriptions resumes at OCR and does not detect again. **After**
            # the cancel check, so the cancel boundary does not move - a skipped
            # stage is still a boundary the user's cancel is honoured at. No
            # event is emitted: `StageFinished.elapsed_ms` is a measured
            # duration and emitting one for work that did not happen would be a
            # lie (PO-6).
            continue
        started_ns = time.perf_counter_ns()
        try:
            stage.run(ctx)
        except BudgetRefused:
            # **Before** the general arm, and that order is load-bearing:
            # `BudgetRefused` *is* an `Exception`, so the general arm placed
            # first swallows it and produces
            # `reason="BudgetRefused: the projected next call of ..."` - a
            # plausible string that fails AC-1's exact comparison and passes
            # any substring check. The decision on the exception is not read
            # here: MT-018 renders it, and `RunAborted` carries a reason and an
            # ordinal.
            progress.reason = BUDGET
            progress.ordinal = ordinal
            return False
        except Exception as error:
            progress.reason = f"{type(error).__name__}: {error}"
            progress.ordinal = ordinal
            return False
        emit(
            StageFinished(
                ordinal=ordinal,
                stage=stage.name,
                elapsed_ms=(time.perf_counter_ns() - started_ns) // 1_000_000,
            )
        )

    if mark_done:
        _mark_done(project, ordinal)
    return True


def _mark_done(project: Project, ordinal: int) -> None:
    """Mirror a completed page to the store (`architecture.md` §5).

    The runner's job and not the stage's: `PassThroughStage.run` is a no-op by
    definition, so there is nothing else that could do it - and it is what every
    stage's `is_done` reads back on the next run. Its own transaction, opened
    only once no stage is on the stack.
    """
    with project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ? WHERE ordinal = ?", (PAGE_DONE, ordinal))


def _start_run(project: Project) -> int:
    """Insert the `run` row and return its id - the run's identity, emitted on
    `RunStarted` before any page is touched."""
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(_INSERT_RUN, (chapter_id, _now()))
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


def _end_run(project: Project, run_id: int, outcome: str, reason: str | None) -> None:
    with project.transaction() as cursor:
        cursor.execute(_FINISH_RUN, (_now(), outcome, reason, run_id))


def _now() -> str:
    return datetime.now(UTC).isoformat()
