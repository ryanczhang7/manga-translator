"""A provider Batch API job, as the store records it (MT-103 AC-4), and the
shape of a volume about to become several of them (MT-111).

A batch job outlives the process that submitted it - the provider holds the
requests for up to a day - so a closed app has to find the job it left running
and resume collecting it (MT-111, MT-112). `store.batch` keeps one row per job;
`BatchJob` is that row as a value.

**One volume, several jobs** (EPIC-09 PO-1, MT-111 AC-3). MT-101 D-9: 200
capped pages are ~24 MB of base64 against Gemini's 20 MB inline limit, so one
inline job cannot hold a volume. `plan_batches` splits the pages' request sizes
into consecutive runs that fit `INLINE_REQUEST_LIMIT_BYTES`, and
`BatchPageInput` is one page of such a run: it lives here, not in `translate`,
because `pipeline` builds it and may not import `translate` - `compose`
converts it to `translate.gemini_batch.BatchPage`.

**What collecting a job answers** (MT-112). `BatchAnswer` is either a
`BatchJobState` - the job is still running, or it failed, was cancelled or
expired - or the `BatchResults` of a succeeded job, one `TranslationResult` or
`BatchItemFailure` per page. They live here for the same reason
`BatchPageInput` does: `pipeline.batch.collect_volume` reads them and may not
import `translate`, so `compose.build_batch_collector` converts MT-110's
`gemini_batch` answers into these.

**Branch-free apart from `plan_batches`.** `domain` sits under
`coverage-core`'s 100 % line-and-branch floor, so every branch below is one a
test reaches.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from mangatl.domain.glossary import PromptContext
from mangatl.domain.line import OcrResult
from mangatl.domain.translation import TranslationResult

__all__ = [
    "INLINE_REQUEST_LIMIT_BYTES",
    "BatchAnswer",
    "BatchItemFailure",
    "BatchJob",
    "BatchJobState",
    "BatchPageInput",
    "BatchResults",
    "BatchState",
    "plan_batches",
]

#: A job is `submitted` until it is settled, one way or the other. The same
#: three words as `store.schema.BATCH_JOB_DDL`'s CHECK.
BatchState = Literal["submitted", "collected", "failed"]

#: Gemini's inline batch request limit, MT-101 D-9's "20 MB" at its smaller,
#: decimal reading (not 20 MiB): a plan that fits this fits either reading.
INLINE_REQUEST_LIMIT_BYTES: int = 20_000_000


@dataclass(frozen=True)
class BatchJob:
    """One submitted job. `provider_job_id` is the provider's name for it
    (`batches/...`); `collected_at` is set once it is collected and `failure`
    once it has failed, so a `submitted` job has neither.

    `first_ordinal .. last_ordinal` (inclusive) are the pages the job holds
    (MT-137): a volume is submitted as several jobs over consecutive runs of
    pages, so collecting one fills exactly those."""

    id: int
    run_id: int
    provider_job_id: str
    model_id: str
    state: BatchState
    submitted_at: str
    collected_at: str | None
    failure: str | None
    first_ordinal: int
    last_ordinal: int

    @property
    def ordinals(self) -> range:
        """The page ordinals this job holds, in order."""
        return range(self.first_ordinal, self.last_ordinal + 1)


@dataclass(frozen=True)
class BatchPageInput:
    """One page of a batch as `pipeline` builds it (MT-111 AC-4): its ordinal,
    its source image bytes, its stored OCR lines and its `neighbours` prompt
    context (MT-107). The same four fields as `translate.gemini_batch.BatchPage`,
    deliberately: `pipeline` may not import `translate`."""

    ordinal: int
    page_image: bytes
    ocr_results: tuple[OcrResult, ...]
    context: PromptContext


@dataclass(frozen=True)
class BatchItemFailure:
    """One page a collected job did not answer usably (MT-112 AC-3).

    The domain's copy of `translate.gemini_batch.BatchItemError` (MT-110 D-8),
    because `pipeline` may not import `translate`: `compose` converts one to the
    other. `message` is the item's own text, verbatim; it rides
    `events.BatchCollected.failures` rather than the line, which has no column
    for it (PO-1)."""

    ordinal: int
    message: str


@dataclass(frozen=True)
class BatchJobState:
    """A collector's answer for a job that has not succeeded (MT-112 AC-1, AC-4).

    `"pending"` is still running - try again later; the other three are settled
    and the job will never be collected. Never `"succeeded"`: a succeeded job
    answers `BatchResults` instead. A value, not `store.batch.BatchPending`
    (which is an exception)."""

    state: Literal["pending", "failed", "cancelled", "expired"]


@dataclass(frozen=True)
class BatchResults:
    """A succeeded job's answer, every page of it keyed by ordinal (MT-112
    AC-2, AC-3): a `TranslationResult` whose `lines` are keyed by reading index
    (PO-2), or a `BatchItemFailure`."""

    results: Mapping[int, TranslationResult | BatchItemFailure]


#: What a `pipeline.batch.BatchCollector` answers for one job. A plain union
#: alias, as `events.RunEvent` is: no branch in a 100 %-branch module.
BatchAnswer = BatchJobState | BatchResults


def plan_batches(sizes: Sequence[int], limit: int) -> list[tuple[int, int]]:
    """Split page request sizes (bytes, in ordinal order) into jobs (AC-3).

    Consecutive inclusive `(first, last)` ranges whose sizes sum to `<= limit`,
    **greedily from the first page**: a job takes every page that still fits
    before the next job starts. `[]` plans no jobs. A page bigger than `limit`
    fits no job at all, so the whole plan is refused with a `ValueError` naming
    its ordinal, its size and the limit - no partial plan is returned.
    """
    ranges: list[tuple[int, int]] = []
    first = 0
    total = 0
    for ordinal, size in enumerate(sizes):
        if size > limit:
            raise ValueError(
                f"page {ordinal}'s request is {size} bytes, over the {limit}-byte"
                " limit of one batch job: no job can hold it"
            )
        if total + size > limit:
            ranges.append((first, ordinal - 1))
            first, total = ordinal, 0
        total += size
    if sizes:
        ranges.append((first, len(sizes) - 1))
    return ranges
