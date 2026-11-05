"""A volume guarded as a whole and submitted as the inline jobs that fit (MT-111).

EPIC-09 PO-5 (as amended 2026-11-03) and D6 applied to a batch: **the guard
judges the whole volume before anything is submitted**, and a refused volume
submits nothing and spends nothing. PO-1: a volume is split into as many
inline jobs as fit MT-101 D-9's 20 MB limit (`domain.batch.plan_batches`),
each recorded as one `batch_job` row over its pages (MT-137) - and still
guarded **once**.

**This module may not import `mangatl.translate`** (the layers contract), so
the submitter and the request-size function are `Callable`s `compose` binds
(`compose.build_batch_binding`, AC-10), and the page input is
`domain.batch.BatchPageInput`.

`submit_volume`'s steps are ordered, and each refusal emits one `RunAborted`
and returns before the next step runs:

1. **Every page has stored lines** (AC-9): a batch is built from finished OCR
   or not at all.
2. **No pending job holds a page of the volume** (AC-8), checked here, before
   the guard and any submit: `store.batch.record_submission` refuses an
   overlap itself, but only after the provider has been handed the job.
3. Every page's input, in `neighbours` context (MT-107).
4. The split (AC-3).
5. **The guard, once, on the whole volume** (AC-5, AC-6 as amended by A-1): a
   refusal emits `CallPriced(ordinal=None)` carrying the decision's spent,
   ceiling and projection, then `RunAborted(reason=BUDGET)` - the runner's
   word exactly, which the window's over-budget state matches.
6. **Each job submitted, then recorded** (AC-7): a submit that raises stops the
   volume there, naming `job k of m`, and the jobs already recorded stand.
   Nothing is retried.
7. `BatchSubmitted` with every row's id, in page order.

**Collection** (MT-112) writes a job's answer into the **same** store path the
per-page call writes, and guards nothing: the volume was judged whole before it
was submitted and the bill is already incurred (EPIC-09 PO-5), so collection
records what it cost. `collect_volume`:

1. **Refuses a job that is not `submitted`** with `AlreadyCollected`, before
   the collector is called (AC-5): a second collection of one job can never
   write a second bill.
2. Hands the collector the job's pages as `BatchPageInput(n, b"",
   read_lines(n), EMPTY_CONTEXT)` - no image is re-read (PO-3).
3. A `"pending"` state emits `BatchWaiting` and writes nothing (AC-1);
   `"failed"`, `"cancelled"` or `"expired"` marks the job failed with that word
   and emits `BatchFailed` (AC-4).
4. Results, page by page in **the job's** ordinal order (AC-2): one ledger row
   against the job's `run_id`, request id `f"{provider_job_id}#{n}"` (MT-110),
   priced at the batch tier; its `CallPriced`; the glossary folded as the
   translate stage folds it; the proposals by reading index (PO-2); the page
   marked done. A page whose item failed is marked done with nothing written or
   billed, so its lines read `failed` (AC-3), and its message rides
   `BatchCollected.failures` (PO-1).
5. The job marked collected, then `BatchCollected`.

MT-137 records a volume as several jobs over consecutive page ranges, so one
collection fills exactly its own job's pages.

**The batch run's whole Start** (MT-113 C-1) is `submit_chapter`, and it owns
an order `run_chapter` cannot give it (PO-5): `run_chapter`'s prelude runs
before page 1, before any OCR exists, so the glossary pre-pass cannot ride it.

1. The LOCAL stages, through `run_chapter` with **no** prelude. Every event is
   forwarded except `RunFinished`: the local stages finishing is not the run
   finishing, and the window opens the review on it. An aborted local run
   returns `()`, its `RunAborted` already emitted.
2. The prelude, with the local run's id, once every page's OCR exists. It
   fails as the runner's prelude fails: `BudgetRefused` as `BUDGET`, anything
   else as its type and message, never naming a page.
3. A cancel set during the local stages' last stage or the prelude is honoured
   here, before anything is handed to the provider.
4. `submit_volume`, whose own refusals pass straight through.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from mangatl.domain.batch import (
    INLINE_REQUEST_LIMIT_BYTES,
    BatchAnswer,
    BatchItemFailure,
    BatchJob,
    BatchJobState,
    BatchPageInput,
    plan_batches,
)
from mangatl.domain.events import (
    BatchCollected,
    BatchFailed,
    BatchSubmitted,
    BatchWaiting,
    CallPriced,
    RunAborted,
    RunEvent,
    RunFinished,
)
from mangatl.domain.glossary import EMPTY_CONTEXT, mark_seen, merge
from mangatl.domain.money import Usd
from mangatl.domain.rates import price
from mangatl.domain.translation import TranslationResult
from mangatl.pipeline.continuity import build_prompt_context
from mangatl.pipeline.prelude import ChapterStep
from mangatl.pipeline.runner import BUDGET, CANCELLED, RUN_ABORTED, run_chapter
from mangatl.pipeline.stage import BudgetRefused, Stage
from mangatl.pipeline.translate_stage import budget_for
from mangatl.store.batch import mark_collected, mark_failed, pending_jobs, record_submission
from mangatl.store.glossary import read_entries, upsert
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.project import PAGE_DONE, Project

# MT-113's `ChapterSubmit` and `submit_chapter` are public by name but not listed:
# `tests/core/test_batch_submit.py` pins this list exactly, and changing it is RED's.
__all__ = [
    "AlreadyCollected",
    "BatchCollector",
    "BatchSubmitter",
    "RequestSize",
    "collect_volume",
    "submit_volume",
]

#: One job: the pages it holds, in ordinal order, to the provider's job name.
BatchSubmitter = Callable[[Sequence[BatchPageInput]], str]

#: The bytes one page's request would occupy in an inline job.
RequestSize = Callable[[BatchPageInput], int]

#: One job's answer (MT-112): the provider's job name and the job's pages, in
#: ordinal order, to the job's state or its results. Bound by
#: `compose.build_batch_collector`, because this module may not import
#: `translate`.
BatchCollector = Callable[[str, Sequence[BatchPageInput]], BatchAnswer]

#: The batch path's whole Start once the window has a models folder (MT-113
#: C-1): `(project, models_dir, emit, cancelled)` to the `batch_job` ids
#: recorded. `compose.build_batch_submit` binds it around `submit_chapter`.
ChapterSubmit = Callable[
    [Project, Path, Callable[[RunEvent], None], Callable[[], bool]], tuple[int, ...]
]


class AlreadyCollected(Exception):
    """`collect_volume` was handed a job that is no longer `submitted` (MT-112
    AC-5): it was collected or it failed, and collecting it again would write a
    second bill for one job."""


def submit_chapter(
    project: Project,
    stages: Sequence[Stage],
    prelude: ChapterStep | None,
    submit: BatchSubmitter,
    request_size: RequestSize,
    model_id: str,
    page_estimate: Usd,
    emit: Callable[[RunEvent], None],
    cancelled: Callable[[], bool],
) -> tuple[int, ...]:
    """The local stages, the prelude, a cancel check, then `submit_volume`
    (module docstring, "The batch run's whole Start"); return the `batch_job`
    ids recorded, `()` on any abort.

    `stages` are the LOCAL ones (`build_pipeline(..., translate=False)`), and
    the `run` row is theirs, ended by `run_chapter`; the prelude's ledger row
    and every `batch_job` row carry its id. `page_estimate` is the batch tier.
    """

    def local_emit(event: RunEvent) -> None:
        if not isinstance(event, RunFinished):
            emit(event)

    outcome = run_chapter(project, stages, local_emit, cancelled)
    if outcome.outcome == RUN_ABORTED:
        return ()
    if prelude is not None:
        try:
            prelude(project, outcome.run_id, emit)
        except BudgetRefused:
            emit(RunAborted(reason=BUDGET, ordinal=None))
            return ()
        except Exception as error:  # the runner's own wording for a failed prelude
            emit(RunAborted(reason=f"{type(error).__name__}: {error}", ordinal=None))
            return ()
    if cancelled():
        emit(RunAborted(reason=CANCELLED, ordinal=None))
        return ()
    return submit_volume(
        project, outcome.run_id, submit, request_size, model_id, page_estimate, emit
    )


def submit_volume(
    project: Project,
    run_id: int,
    submit: BatchSubmitter,
    request_size: RequestSize,
    model_id: str,
    page_estimate: Usd,
    emit: Callable[[RunEvent], None],
    *,
    limit: int = INLINE_REQUEST_LIMIT_BYTES,
) -> tuple[int, ...]:
    """Guard the volume once and submit it as the jobs that fit (module
    docstring, steps 1-7); return the `batch_job` ids recorded, in page order.

    `page_estimate` is the batch-tier figure (`page_estimate(model_id,
    pricing="batch")`, AC-1) and `model_id` is stored on every row. A refusal
    returns `()` - or, when a job part-way is refused, the ids recorded before
    it. A page too big for any job raises `plan_batches`' `ValueError`.
    """
    pages = project.pages()
    lines = {page.ordinal: project.read_lines(page.ordinal) for page in pages}
    for page in pages:
        if not lines[page.ordinal]:
            emit(
                RunAborted(
                    reason=f"page {page.ordinal} has no OCR yet: a batch is built from"
                    " finished OCR, so run OCR on every page first",
                    ordinal=page.ordinal,
                )
            )
            return ()

    ordinals = set(lines)
    for job in pending_jobs(project):
        if ordinals.intersection(job.ordinals):
            emit(
                RunAborted(
                    reason=f"batch job {job.provider_job_id} is still pending over pages"
                    f" {job.first_ordinal}..{job.last_ordinal}; collect it first",
                    ordinal=None,
                )
            )
            return ()

    source_dir = project.chapter.source_dir
    inputs = [
        BatchPageInput(
            ordinal=page.ordinal,
            page_image=(source_dir / page.filename).read_bytes(),
            ocr_results=lines[page.ordinal],
            context=build_prompt_context(project, page.ordinal, mode="neighbours"),
        )
        for page in pages
    ]
    ranges = plan_batches([request_size(page_input) for page_input in inputs], limit)

    budget = budget_for(project, page_estimate)
    spent = chapter_total(project)
    projection = budget.project_batch(len(inputs), page_estimate)
    decision = budget.check(spent, projection)
    if not decision.permitted:
        emit(
            CallPriced(
                ordinal=None,
                spent=decision.spent,
                ceiling=decision.ceiling,
                projection=decision.projection,
            )
        )
        emit(RunAborted(reason=BUDGET, ordinal=None))
        return ()

    ids: list[int] = []
    for k, (first, last) in enumerate(ranges, 1):
        try:
            name = submit(inputs[first : last + 1])
        except Exception as exc:  # any refusal stops the volume, reported, never retried
            emit(
                RunAborted(
                    reason=f"batch job {k} of {len(ranges)} was refused: {exc}",
                    ordinal=None,
                )
            )
            return tuple(ids)
        ids.append(record_submission(project, run_id, name, model_id, first, last))

    emit(BatchSubmitted(run_id, tuple(ids), len(inputs), projection))
    return tuple(ids)


def collect_volume(
    project: Project,
    job: BatchJob,
    collect: BatchCollector,
    page_estimate: Usd,
    emit: Callable[[RunEvent], None],
) -> BatchAnswer:
    """Ask for one submitted job's answer and write it where the per-page call
    would have (MT-112, module docstring "Collection"); return the answer.

    `page_estimate` is the batch-tier figure (`page_estimate(model_id,
    pricing="batch")`), read only by the `CallPriced` projections. Raises
    `AlreadyCollected` for a job that is not `submitted`, before `collect` is
    called (AC-5), and `KeyError` for an answer missing one of the job's pages,
    with the job left pending.
    """
    if job.state != "submitted":
        raise AlreadyCollected(
            f"batch job {job.id} ({job.provider_job_id}) is already {job.state}:"
            " collecting it again would bill it twice"
        )

    pages = [BatchPageInput(n, b"", project.read_lines(n), EMPTY_CONTEXT) for n in job.ordinals]
    answer = collect(job.provider_job_id, pages)

    if isinstance(answer, BatchJobState):
        if answer.state == "pending":
            emit(BatchWaiting(job.id, answer.state))
        else:
            mark_failed(project, job.id, answer.state)
            emit(BatchFailed(job.id, answer.state))
        return answer

    page_count = len(project.pages())
    failures: list[tuple[int, str]] = []
    done = 0
    # The job's ordinals, never the answer's keys: the order of the events and
    # the writes is page order whatever order the mapping holds, and a page the
    # answer lacks is a `KeyError` here, before the job is marked collected.
    for n in job.ordinals:
        item = answer.results[n]
        if isinstance(item, BatchItemFailure):
            failures.append((n, item.message))
        else:
            _write_page(project, job, n, item, page_estimate, page_count, emit)
            done += 1
        _mark_done(project, n)

    mark_collected(project, job.id)
    emit(BatchCollected(job.id, done, len(failures), tuple(failures)))
    return answer


def _write_page(
    project: Project,
    job: BatchJob,
    n: int,
    result: TranslationResult,
    page_estimate: Usd,
    page_count: int,
    emit: Callable[[RunEvent], None],
) -> None:
    """One answered page, in the translate stage's order: the bill, its
    `CallPriced`, the glossary, the proposals.

    The ledger row is the **job's** run (`job.run_id`, the run that submitted
    it, not the latest), the request id MT-110's `f"{job}#{ordinal}"` - never
    the item's own id - and the usage priced at the **batch** tier. The
    projection covers the pages after this one, as the stage's does (R-C1).
    `result.lines` are keyed by reading index already (PO-2).
    """
    model_id = result.call.model_id if result.call is not None else job.model_id
    record_call(
        project,
        job.run_id,
        n,
        f"{job.provider_job_id}#{n}",
        price(model_id, result.usage, pricing="batch"),
    )
    budget = budget_for(project, page_estimate)
    emit(
        CallPriced(
            ordinal=n,
            spent=chapter_total(project),
            ceiling=budget.ceiling,
            projection=budget.project(chapter_call_costs(project), page_count - n - 1),
        )
    )
    _update_glossary(project, n, result)
    project.write_proposed(n, result.lines)


def _update_glossary(project: Project, n: int, result: TranslationResult) -> None:
    """`translate_stage._update_glossary`, exactly: `merge` the page's proposals,
    `mark_seen` its stored lines, and `upsert` only the entries that changed.
    The lines are every stored line of the page, because a batch sends every
    one (PO-2)."""
    before = read_entries(project)
    after = mark_seen(
        merge(before, result.proposed_terms, n),
        [line.text for line in project.read_lines(n)],
        n,
    )
    unchanged = set(before)
    for entry in after:
        if entry not in unchanged:
            upsert(project, entry)


def _mark_done(project: Project, ordinal: int) -> None:
    """The runner's `_mark_done`, copied (R-C2: it is private, and
    `store/project.py` is not this story's to change). A page whose item failed
    is marked done too, with no proposal, so its lines read `failed` with the
    existing untranslated reason (PO-1) rather than waiting for a run."""
    with project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ? WHERE ordinal = ?", (PAGE_DONE, ordinal))
