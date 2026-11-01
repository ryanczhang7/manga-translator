"""The record of a submitted Batch API job, and the one question a resume asks
of it: which job is still pending? (MT-103 AC-4; MT-111, MT-112.)

**At most one job is pending, by refusal.** `pending_job` is the one row with
state `submitted`, and that is only an answer while there is at most one: two
would make "which job does a resume collect?" unanswerable. So
`record_submission` raises `BatchPending`, naming the job in the way, and
writes nothing. A partial unique index would refuse too, but with an
`IntegrityError` that cannot say which job blocked it.

Timestamps are stamped here as aware UTC ISO-8601 instants, `store.ledger`'s
shape and for its reason.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from mangatl.domain.batch import BatchJob, BatchState
from mangatl.store.project import Project

__all__ = ["BatchPending", "mark_collected", "mark_failed", "pending_job", "record_submission"]

_SELECT_PENDING = (
    "SELECT id, run_id, provider_job_id, model_id, state, submitted_at, collected_at, failure"
    " FROM batch_job WHERE state = 'submitted' ORDER BY id LIMIT 1"
)
_INSERT_JOB = (
    "INSERT INTO batch_job (run_id, provider_job_id, model_id, state, submitted_at)"
    " VALUES (?, ?, ?, 'submitted', ?)"
)
# `WHERE id = ?` on both: settling one job must leave every other row alone.
_MARK_COLLECTED = "UPDATE batch_job SET state = 'collected', collected_at = ? WHERE id = ?"
_MARK_FAILED = "UPDATE batch_job SET state = 'failed', failure = ? WHERE id = ?"


class BatchPending(Exception):
    """A batch job is still `submitted`; collect it or mark it failed first.

    The message names the pending job's provider id, because "a job is
    pending" alone does not say which one to go and collect.
    """


def record_submission(project: Project, run_id: int, provider_job_id: str, model_id: str) -> int:
    """Record a job just submitted by run `run_id`, and return its id.

    Raises `BatchPending` if a job is already pending. The check and the insert
    share one transaction, so the refusal and the write cannot interleave with
    another writer's.
    """
    with project.transaction() as cursor:
        pending = cursor.execute(_SELECT_PENDING).fetchone()
        if pending is not None:
            raise BatchPending(
                f"batch job {pending[0]} ({pending[2]}) is still submitted;"
                " collect it or mark it failed before submitting another"
            )
        cursor.execute(
            _INSERT_JOB, (run_id, provider_job_id, model_id, datetime.now(UTC).isoformat())
        )
        return cast(int, cursor.lastrowid)


def pending_job(project: Project) -> BatchJob | None:
    """The job a resume should collect, or `None` - almost every project has
    never submitted a batch. Opens no transaction, `Project.select`'s rule."""
    rows = project.select(_SELECT_PENDING)
    if not rows:
        return None
    job_id, run_id, provider_job_id, model_id, state, submitted_at, collected_at, failure = rows[0]
    return BatchJob(
        id=int(job_id),
        run_id=int(run_id),
        provider_job_id=str(provider_job_id),
        model_id=str(model_id),
        state=cast(BatchState, state),
        submitted_at=str(submitted_at),
        collected_at=collected_at,
        failure=failure,
    )


def mark_collected(project: Project, job_id: int) -> None:
    """Job `job_id`'s results are in: `collected`, stamped now."""
    with project.transaction() as cursor:
        cursor.execute(_MARK_COLLECTED, (datetime.now(UTC).isoformat(), job_id))


def mark_failed(project: Project, job_id: int, failure: str) -> None:
    """Job `job_id` will never be collected: `failed`, with `failure` verbatim."""
    with project.transaction() as cursor:
        cursor.execute(_MARK_FAILED, (failure, job_id))
