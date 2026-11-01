"""A provider Batch API job, as the store records it (MT-103 AC-4).

A batch job outlives the process that submitted it - the provider holds the
requests for up to a day - so a closed app has to find the job it left running
and resume collecting it (MT-111, MT-112). `store.batch` keeps one row per job;
this is that row as a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["BatchJob", "BatchState"]

#: A job is `submitted` until it is settled, one way or the other. The same
#: three words as `store.schema.BATCH_JOB_DDL`'s CHECK.
BatchState = Literal["submitted", "collected", "failed"]


@dataclass(frozen=True)
class BatchJob:
    """One submitted job. `provider_job_id` is the provider's name for it
    (`batches/...`); `collected_at` is set once it is collected and `failure`
    once it has failed, so a `submitted` job has neither."""

    id: int
    run_id: int
    provider_job_id: str
    model_id: str
    state: BatchState
    submitted_at: str
    collected_at: str | None
    failure: str | None
