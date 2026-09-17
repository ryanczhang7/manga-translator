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
   chapter report zero.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from mangatl.domain.events import (
    PageSkipped,
    PageStarted,
    RunAborted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.store.project import PAGE_DONE, Project

__all__ = ["RUN_ABORTED", "RUN_FINISHED", "RunOutcome", "run_chapter"]

#: The two values written to the `run` row's `outcome` column, and carried on
#: `RunOutcome.outcome`. One value in two places, so AC-1's "ends with outcome
#: `finished`" can be asserted against the store as well as against the return.
RUN_FINISHED = "finished"
RUN_ABORTED = "aborted"

#: `RunAborted.reason` for a cancellation. A cancel is not an error, so it reads
#: as itself rather than as an exception message, and it names no page.
CANCELLED = "cancelled"

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
) -> RunOutcome:
    """Walk every page of `project`'s chapter through `stages`, in ordinal order.

    Returns rather than raises on a stage failure: AC-4 says the run *emits*
    `RunAborted`, and a runner that let the exception through would leave
    MT-015's worker thread dead with the progress readout stuck on the page that
    failed.
    """
    pages = project.pages()
    run_id = _start_run(project)
    emit(RunStarted(run_id=run_id, page_count=len(pages)))

    progress = _Progress()
    for page in pages:
        if cancelled():
            progress.reason = CANCELLED
            break
        ctx = PageContext(project=project, page=page)
        if not _run_page(project, ctx, stages, emit, cancelled, progress):
            break
        progress.pages_done += 1

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


def _run_page(
    project: Project,
    ctx: PageContext,
    stages: Sequence[Stage],
    emit: Callable[[RunEvent], None],
    cancelled: Callable[[], bool],
    progress: _Progress,
) -> bool:
    """Take one page through every stage. `False` means the run must stop.

    A page that was already complete is skipped and still counts towards
    `pages_done`: it is done, whoever did it.
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
