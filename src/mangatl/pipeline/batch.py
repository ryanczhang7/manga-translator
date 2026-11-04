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
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from mangatl.domain.batch import INLINE_REQUEST_LIMIT_BYTES, BatchPageInput, plan_batches
from mangatl.domain.events import BatchSubmitted, CallPriced, RunAborted, RunEvent
from mangatl.domain.money import Usd
from mangatl.pipeline.continuity import build_prompt_context
from mangatl.pipeline.runner import BUDGET
from mangatl.pipeline.translate_stage import budget_for
from mangatl.store.batch import pending_jobs, record_submission
from mangatl.store.ledger import chapter_total
from mangatl.store.project import Project

__all__ = ["BatchSubmitter", "RequestSize", "submit_volume"]

#: One job: the pages it holds, in ordinal order, to the provider's job name.
BatchSubmitter = Callable[[Sequence[BatchPageInput]], str]

#: The bytes one page's request would occupy in an inline job.
RequestSize = Callable[[BatchPageInput], int]


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
