"""The record of submitted Batch API jobs, and the one question a resume asks
of them: which jobs are still pending? (MT-103 AC-4; MT-137; MT-111, MT-112.)

**No two pending jobs share a page, by refusal.** A volume is submitted as
several jobs, each over a consecutive run of pages (MT-137), so several may be
`submitted` at once - but never two over the same page, because that page
would be billed twice and collected twice. `record_submission` refuses a range
that overlaps a pending job's, raising `BatchPending` naming the job in the
way, and writes nothing. An index cannot express an overlap, and a constraint
would answer with an `IntegrityError` that cannot say which job blocked it.

`pending_jobs` is every `submitted` row, in page order: a resume collects each.

Timestamps are stamped here as aware UTC ISO-8601 instants, `store.ledger`'s
shape and for its reason.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from mangatl.domain.batch import BatchJob, BatchState
from mangatl.store.project import Project

__all__ = ["BatchPending", "mark_collected", "mark_failed", "pending_jobs", "record_submission"]

_SELECT_PENDING = (
    "SELECT id, run_id, provider_job_id, model_id, state, submitted_at, collected_at, failure,"
    " first_ordinal, last_ordinal"
    " FROM batch_job WHERE state = 'submitted' ORDER BY first_ordinal, id"
)
# Two inclusive ranges share a page exactly when each starts no later than the
# other ends.
_SELECT_OVERLAPPING = (
    "SELECT id, provider_job_id, first_ordinal, last_ordinal FROM batch_job"
    " WHERE state = 'submitted' AND ? <= last_ordinal AND ? >= first_ordinal"
    " ORDER BY first_ordinal, id LIMIT 1"
)
_INSERT_JOB = (
    "INSERT INTO batch_job"
    " (run_id, provider_job_id, model_id, state, submitted_at, first_ordinal, last_ordinal)"
    " VALUES (?, ?, ?, 'submitted', ?, ?, ?)"
)
# `WHERE id = ?` on both: settling one job must leave every other row alone.
_MARK_COLLECTED = "UPDATE batch_job SET state = 'collected', collected_at = ? WHERE id = ?"
_MARK_FAILED = "UPDATE batch_job SET state = 'failed', failure = ? WHERE id = ?"


class BatchPending(Exception):
    """A batch job is still `submitted` over a page being submitted again;
    collect it or mark it failed first.

    The message names the pending job's id and provider id, because "a job is
    pending" alone does not say which one to go and collect.
    """


def record_submission(
    project: Project,
    run_id: int,
    provider_job_id: str,
    model_id: str,
    first_ordinal: int,
    last_ordinal: int,
) -> int:
    """Record a job just submitted by run `run_id` over pages
    `first_ordinal .. last_ordinal` (inclusive), and return its id.

    Raises `ValueError` for an impossible range before touching the file -
    not the schema CHECK's `IntegrityError`, and not `BatchPending` even while
    a job is pending. Raises `BatchPending` if a pending job holds any of the
    pages. The check and the insert share one transaction, so the refusal and
    the write cannot interleave with another writer's.
    """
    if first_ordinal < 0 or first_ordinal > last_ordinal:
        raise ValueError(
            f"pages {first_ordinal} .. {last_ordinal} are not a range of pages:"
            " the first must not be negative, nor after the last"
        )
    with project.transaction() as cursor:
        pending = cursor.execute(_SELECT_OVERLAPPING, (first_ordinal, last_ordinal)).fetchone()
        if pending is not None:
            job_id, pending_provider_id, pending_first, pending_last = pending
            raise BatchPending(
                f"batch job {job_id} ({pending_provider_id}) is still submitted over pages"
                f" {pending_first}..{pending_last}; collect it or mark it failed before"
                f" submitting pages {first_ordinal}..{last_ordinal}"
            )
        cursor.execute(
            _INSERT_JOB,
            (
                run_id,
                provider_job_id,
                model_id,
                datetime.now(UTC).isoformat(),
                first_ordinal,
                last_ordinal,
            ),
        )
        return cast(int, cursor.lastrowid)


def pending_jobs(project: Project) -> tuple[BatchJob, ...]:
    """Every job a resume should collect, in page order - `()` for almost
    every project, which has never submitted a batch. Opens no transaction,
    `Project.select`'s rule."""
    return tuple(
        BatchJob(
            id=int(job_id),
            run_id=int(run_id),
            provider_job_id=str(provider_job_id),
            model_id=str(model_id),
            state=cast(BatchState, state),
            submitted_at=str(submitted_at),
            collected_at=collected_at,
            failure=failure,
            first_ordinal=int(first_ordinal),
            last_ordinal=int(last_ordinal),
        )
        for (
            job_id,
            run_id,
            provider_job_id,
            model_id,
            state,
            submitted_at,
            collected_at,
            failure,
            first_ordinal,
            last_ordinal,
        ) in project.select(_SELECT_PENDING)
    )


def mark_collected(project: Project, job_id: int) -> None:
    """Job `job_id`'s results are in: `collected`, stamped now."""
    with project.transaction() as cursor:
        cursor.execute(_MARK_COLLECTED, (datetime.now(UTC).isoformat(), job_id))


def mark_failed(project: Project, job_id: int, failure: str) -> None:
    """Job `job_id` will never be collected: `failed`, with `failure` verbatim."""
    with project.transaction() as cursor:
        cursor.execute(_MARK_FAILED, (failure, job_id))
