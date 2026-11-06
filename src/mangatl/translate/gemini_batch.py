"""Many pages, one Gemini batch job: build, submit, poll and collect it.

MT-110, EPIC-09 PO-1. The batch twin of `translate/gemini.py`: each page's
request is **exactly** the one `build_request` builds for an interactive call
- same capped image, system prompt, schema and thinking level - so a batch asks
the same question, only at the batch price. Everything SDK-shaped is cited
from MT-101 `## Decided`, checked against `google-genai` 2.29.0:

- **Submit** (D-5): one `client.batches.create(model=MODEL_ID, src=[...],
  config=types.CreateBatchJobConfig(display_name=...))`, the requests inline.
  The model goes on the job, so each `InlinedRequest.model` stays `None`. A
  create-time refusal (D-4's `400`) propagates unwrapped: there is nothing to
  retry that the caller cannot see better.
- **States** (D-6): six `JobState` members belong to the Gemini API and map to
  five names (`PENDING` and `RUNNING` are both "pending"). The other six are
  Vertex-only, and a state this table does not know - or no state at all -
  raises `UnknownBatchState` rather than reading as "pending", because a
  poller that treats the unknown as pending waits forever.
  `UnknownBatchState` deliberately does **not** derive from
  `BatchNotFinished`, which a caller retries.
- **Pair by key** (D-7): the response order is not documented, so each item is
  matched to its page by `metadata["key"] == str(ordinal)`, never by position.
  Position would put one page's words on another page's bubbles, silently. The
  item count is checked first (PO-4): a job that answers more items than it was
  asked is a shape error whatever its keys say.
- **Per-item errors** (D-8): an item carrying `.error` fails only its own page,
  as a `BatchItemError`; the pipeline decides what a failed page means
  (MT-112).
- **Parse through the parser** (D-14): an answer is parsed by
  `parse_lines_text` and priced by `_usage_of`, exactly as
  `translate_page` does - the live probe answered an index the page does not
  have, and the parser is the defence. Any exception there fails that page with
  `"<Type>: <message>"` and the other pages still parse.

`collect_batch` makes one `batches.get` and reads nothing from `dest` unless
the job succeeded: a pending job can carry a stale destination.

This module never decides which pages a batch holds (PO-2, MT-111) and never
constructs a client (the caller's, as in `gemini.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from google.genai import Client, types

from mangatl.domain.glossary import PromptContext
from mangatl.domain.line import OcrResult
from mangatl.domain.translation import CallInfo, TranslationResult
from mangatl.translate.gemini import MODEL_ID, _usage_of, build_request
from mangatl.translate.parse import parse_lines_text

__all__ = [
    "BatchItemError",
    "BatchNotFinished",
    "BatchPage",
    "BatchShapeError",
    "BatchStateName",
    "UnknownBatchState",
    "batch_state",
    "build_batch_requests",
    "collect_batch",
    "submit_batch",
]

BatchStateName = Literal["pending", "succeeded", "failed", "cancelled", "expired"]

#: AC-3. Everything not a key here raises UnknownBatchState (MT-101 D-6).
_STATES: dict[str, BatchStateName] = {
    "JOB_STATE_PENDING": "pending",
    "JOB_STATE_RUNNING": "pending",
    "JOB_STATE_SUCCEEDED": "succeeded",
    "JOB_STATE_FAILED": "failed",
    "JOB_STATE_CANCELLED": "cancelled",
    "JOB_STATE_EXPIRED": "expired",
}


@dataclass(frozen=True)
class BatchPage:
    """One page of a batch: its ordinal is its key (D-7)."""

    ordinal: int
    page_image: bytes
    ocr_results: tuple[OcrResult, ...]
    context: PromptContext


@dataclass(frozen=True)
class BatchItemError:
    """One page the batch did not answer usably (D-8, D-14).

    `message` is the item's `error.message` verbatim, or
    `f"{type(exc).__name__}: {exc}"` for an answer that failed to parse.
    """

    ordinal: int
    message: str


class UnknownBatchState(Exception):
    """A job state outside the Gemini API's six, or none at all (AC-3)."""


class BatchNotFinished(Exception):
    """A job collected before it succeeded; the message names the mapped state (AC-5)."""


class BatchShapeError(Exception):
    """A response whose items cannot be paired one-to-one with the pages (AC-4)."""


def build_batch_requests(pages: Sequence[BatchPage]) -> list[types.InlinedRequest]:
    """One `InlinedRequest` per page, sorted by ordinal (AC-1).

    `contents` and `config` are `build_request`'s; `metadata` carries the
    ordinal as the key; `model` is left `None` because it goes on
    `batches.create`. Two pages sharing an ordinal raise `ValueError` naming it.
    """
    seen: set[int] = set()
    for page in pages:
        if page.ordinal in seen:
            raise ValueError(f"two pages share the ordinal {page.ordinal}")
        seen.add(page.ordinal)

    requests: list[types.InlinedRequest] = []
    for page in sorted(pages, key=lambda p: p.ordinal):
        request = build_request(page.page_image, page.ocr_results, page.context)
        requests.append(
            types.InlinedRequest(
                contents=request["contents"],
                config=request["config"],
                metadata={"key": str(page.ordinal)},
            )
        )
    return requests


def submit_batch(
    client: Client, requests: Sequence[types.InlinedRequest], display_name: str
) -> str:
    """Create one inline batch job and return its name (AC-2, D-5).

    No `try`: a create-time refusal propagates unwrapped (D-4).
    """
    job = client.batches.create(
        model=MODEL_ID,
        src=list(requests),
        config=types.CreateBatchJobConfig(display_name=display_name),
    )
    return str(job.name)


def batch_state(client: Client, job_name: str) -> BatchStateName:
    """The job's state as one of five names, from one `batches.get` (AC-3, D-6)."""
    return _state_of(client.batches.get(name=job_name))


def collect_batch(
    client: Client, job_name: str, pages: Sequence[BatchPage]
) -> dict[int, TranslationResult | BatchItemError]:
    """Every page's answer from a succeeded job, keyed by ordinal (AC-4, AC-5).

    One `batches.get`. A job that has not succeeded raises `BatchNotFinished`
    before its `dest` is read. Items are paired to pages by key (D-7); a count
    mismatch, or an item with no key, an unknown key or a repeated one, raises
    `BatchShapeError`. Each item is a `TranslationResult` or a `BatchItemError`.
    """
    job = client.batches.get(name=job_name)
    state = _state_of(job)
    if state != "succeeded":
        raise BatchNotFinished(f"batch {job_name} is {state}, not succeeded")

    items = (job.dest or types.BatchJobDestination()).inlined_responses or []
    if len(items) != len(pages):
        raise BatchShapeError(f"the batch answered {len(items)} items for {len(pages)} pages")

    by_key = {str(page.ordinal): page for page in pages}
    paired: dict[int, tuple[BatchPage, types.InlinedResponse]] = {}
    for item in items:
        key = (item.metadata or {}).get("key")
        if key is None:
            raise BatchShapeError("a batch item carries no key")
        page = by_key.get(key)
        if page is None:
            raise BatchShapeError(f"a batch item is keyed {key}, which no page has")
        if page.ordinal in paired:
            raise BatchShapeError(f"two batch items share the key {key}")
        paired[page.ordinal] = (page, item)

    return {
        ordinal: _result_of(job_name, page, item)
        for ordinal, (page, item) in sorted(paired.items())
    }


def _state_of(job: types.BatchJob) -> BatchStateName:
    """`job.state` through `_STATES`; anything else is `UnknownBatchState`."""
    name = job.state.name if job.state is not None else None
    mapped = _STATES.get(name) if name is not None else None
    if mapped is None:
        raise UnknownBatchState(f"the batch job's state {name!r} is not a Gemini API state")
    return mapped


def _result_of(
    job_name: str, page: BatchPage, item: types.InlinedResponse
) -> TranslationResult | BatchItemError:
    """One item as its page's result, or the error that fails only that page."""
    if item.error is not None:
        return BatchItemError(page.ordinal, item.error.message or "")
    try:
        # An item with neither a response nor an error reads as an empty
        # response, which fails its page in `json.loads` like any empty body.
        response = item.response or types.GenerateContentResponse()
        text = response.text or ""
        return TranslationResult(
            lines=parse_lines_text(text, range(len(page.ocr_results))),
            usage=_usage_of(response.usage_metadata),
            call=CallInfo(
                request_id=f"{job_name}#{page.ordinal}",
                model_id=response.model_version or MODEL_ID,
            ),
            proposed_terms=(),
        )
    except Exception as exc:
        return BatchItemError(page.ordinal, f"{type(exc).__name__}: {exc}")
