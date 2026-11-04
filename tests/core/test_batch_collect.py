"""MT-112 AC-1..AC-5: `pipeline.batch.collect_volume`, a submitted job collected
into the same store path the per-page call writes.

**Oracle partition: mechanical.** Every criterion pins an exact value or an
exact event list, so every expectation below is a literal: the ledger rows, the
micro-dollar costs, the `CallPriced` numbers and the glossary entries are
written out, never recomputed through the code under test.

**The world is real**: a `.mtproj` on `tmp_path` with three tiny PNG pages,
regions and OCR lines seeded through the store, a one-entry glossary written
through `store.glossary.write_proposed_glossary`, two `run` rows (the job's,
then a later one, so "the job's `run_id`" is distinguishable from "the latest
run") and a $0.06 ceiling. The job is recorded through
`store.batch.record_submission` and read back through `pending_jobs` (MT-137,
shipped). The one double is the collector (`_Collector`), standing where
`compose.build_batch_collector`'s bound callable stands: it records every call
and answers what the test configured.

**The numbers (AC-2).** Each page's item reports its own usage, priced at the
Gemini 3.1 Pro Preview **batch** row ($1.00 / $6.00 per Mtok in/out):

    page 0  TokenUsage(1000, 500, 0, 0)   1000 + 3000 =  4000 micro  (standard: 8000)
    page 1  TokenUsage(2000, 500, 0, 0)   2000 + 3000 =  5000 micro  (standard: 10000)
    page 2  TokenUsage(1000, 1000, 0, 0)  1000 + 6000 =  7000 micro  (standard: 14000)

`test_the_batch_row_prices_the_three_usages_at_the_written_out_figures` checks
the literals against `price(..., pricing="batch")` once, as a precondition;
the collection tests compare against the literals alone, so DV-1 (the keyword
dropped) turns them red with the standard figures in the message.

**`CallPriced` (AC-2)**, with a $0.02 batch page estimate and the stored
$0.06 ceiling, each read after its page's row is written. The projection
covers the pages AFTER this one (the event's documented meaning,
`domain/events.py`, and `translate_stage`'s `pages_remaining(ctx) - 1`) - see
the story's Contract amendment R-C1:

    page 0  spent  4000  1 sample  estimate  next 20000  remaining 40000 (x2)
    page 1  spent  9000  2 samples observed  next  4500  remaining  4500 (x1)
    page 2  spent 16000  3 samples observed  next  5334  remaining     0 (x0)

`5334` is `ceil(16000 / 3)`, `Budget.project`'s rounding up.

**Batch answers are keyed by reading index (PO-2)**: `result.lines` go to
`write_proposed` as they are.

**Imports of the names MT-112 adds are inside helpers** (`_collect_volume`,
`_already_collected`, `_results`, `_state`, `_failure`, `_waiting`,
`_collected`, `_failed`), so in RED each test fails on the named absence and
the file is never dark at collection.

**How a page is marked done is not constrained**: the tests observe
`project.page_status(n) == PAGE_DONE` and the line statuses `read_review_lines`
derives from it, nothing else.

What these tests do NOT constrain: the wording of `AlreadyCollected`'s message
beyond naming the job's id and provider id; whether the collector's pages are a
list or a tuple; the return value on a `BatchResults` answer beyond it being
the answer; and anything written before a `KeyError` on an answer missing a
page, beyond the job staying pending.

**Timing.** No `pytest-timeout` in this project; every test builds a
three-page chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import dataclasses
import re
import sqlite3
import typing
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from mangatl.domain.batch import BatchJob, BatchPageInput
from mangatl.domain.budget import Projection
from mangatl.domain.events import CallPriced, RunEvent
from mangatl.domain.glossary import EMPTY_CONTEXT, GlossaryEntry, ProposedTerm
from mangatl.domain.line import OcrResult, failure_reason
from mangatl.domain.money import Usd
from mangatl.domain.rates import RATE_TABLE_VERSION, price
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.store.batch import pending_jobs, record_submission
from mangatl.store.glossary import read_entries, write_proposed_glossary
from mangatl.store.intake import read_chapter
from mangatl.store.lines import read_review_lines
from mangatl.store.project import (
    PAGE_DONE,
    PAGE_PENDING,
    Project,
    create_project,
    project_dir_for,
)

# -- the numbers ---------------------------------------------------------------

_MODEL = "gemini-3.1-pro-preview"
_JOB = "batches/a"

#: MT-111 AC-1's settled batch page estimate, written out: $0.02.
_ESTIMATE = Usd.from_micro(20_000)

#: The stored ceiling: $0.06.
_CEILING = Usd.from_micro(60_000)

_USAGE: dict[int, TokenUsage] = {
    0: TokenUsage(1000, 500, 0, 0),
    1: TokenUsage(2000, 500, 0, 0),
    2: TokenUsage(1000, 1000, 0, 0),
}

#: Each usage at the batch row, in micro-dollars, written out (DV-1's target).
_BATCH_MICRO: dict[int, int] = {0: 4_000, 1: 5_000, 2: 7_000}

#: The same usages at the interactive row - what DV-1's mutant would record.
_STANDARD_MICRO: dict[int, int] = {0: 8_000, 1: 10_000, 2: 14_000}

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

#: OCR seeded on every page. Page 0 names ケンジ and 先輩; page 2 names both in
#: one line, so `mark_seen` moves both to page 2.
_LINES: dict[int, tuple[OcrResult, ...]] = {
    0: (OcrResult("ケンジ、待って"), OcrResult("先輩…")),
    1: (OcrResult("どこへ行くの"),),
    2: (OcrResult("ケンジ先輩"), OcrResult("", ocr_empty=True)),
}

#: The glossary before collection: ケンジ, seen on page 0 only. Never proposed
#: below, so its `last_seen_page` moving to 2 is `mark_seen`'s doing alone.
_GLOSSARY = [GlossaryEntry("ケンジ", "Kenji", "name", 0, 0, "model")]

#: Each page's answer. `lines` keyed by reading index (PO-2); page 2 omits its
#: `ocr_empty` region. Page 2 re-proposes 先輩 with another rendering, which
#: `merge` must ignore (first rendering wins). `CallInfo.request_id` is
#: deliberately NOT the ledger's spelling, so a collector that stored the
#: item's own id rather than `f"{provider_job_id}#{ordinal}"` fails.
_RESULTS: dict[int, TranslationResult] = {
    0: TranslationResult(
        lines={0: "Kenji, wait", 1: "Senpai..."},
        usage=_USAGE[0],
        call=CallInfo("item-response-0", _MODEL),
        proposed_terms=(ProposedTerm("先輩", "senpai", "honorific"),),
    ),
    1: TranslationResult(
        lines={0: "Where are you going"},
        usage=_USAGE[1],
        call=CallInfo("item-response-1", _MODEL),
        proposed_terms=(ProposedTerm("どこ", "where", ""),),
    ),
    2: TranslationResult(
        lines={0: "Kenji-senpai"},
        usage=_USAGE[2],
        call=CallInfo("item-response-2", _MODEL),
        proposed_terms=(ProposedTerm("先輩", "senior", "other"),),
    ),
}

#: AC-2's glossary after collection, in `read_entries`' (first-written) order.
_GLOSSARY_AFTER_ALL = [
    GlossaryEntry("ケンジ", "Kenji", "name", 0, 2, "model"),
    GlossaryEntry("先輩", "senpai", "honorific", 0, 2, "model"),
    GlossaryEntry("どこ", "where", "", 1, 1, "model"),
]

#: AC-3's: page 1 failed, so どこ was never proposed.
_GLOSSARY_AFTER_FAILURE = [
    GlossaryEntry("ケンジ", "Kenji", "name", 0, 2, "model"),
    GlossaryEntry("先輩", "senpai", "honorific", 0, 2, "model"),
]

#: `read_proposed` after AC-2, page by page.
_PROPOSED_AFTER_ALL: dict[int, tuple[str | None, ...]] = {
    0: ("Kenji, wait", "Senpai..."),
    1: ("Where are you going",),
    2: ("Kenji-senpai", None),
}


def _projection(next_micro: int, remaining_micro: int, basis: str, samples: int) -> Projection:
    return Projection(
        next_call=Usd.from_micro(next_micro),
        remaining_chapter=Usd.from_micro(remaining_micro),
        basis=basis,  # type: ignore[arg-type]
        sample_count=samples,
    )


#: AC-2's three `CallPriced`, written out (module docstring's table).
_PRICED_ALL = [
    CallPriced(0, Usd.from_micro(4_000), _CEILING, _projection(20_000, 40_000, "estimate", 1)),
    CallPriced(1, Usd.from_micro(9_000), _CEILING, _projection(4_500, 4_500, "observed", 2)),
    CallPriced(2, Usd.from_micro(16_000), _CEILING, _projection(5_334, 0, "observed", 3)),
]

#: AC-3's two: page 1 priced nothing. Page 2's samples are 4000 and 7000.
_PRICED_WITH_FAILURE = [
    CallPriced(0, Usd.from_micro(4_000), _CEILING, _projection(20_000, 40_000, "estimate", 1)),
    CallPriced(2, Usd.from_micro(11_000), _CEILING, _projection(5_500, 0, "observed", 2)),
]


# -- the names MT-112 adds, imported lazily --------------------------------------


def _collect_volume(*args: Any, **kwargs: Any) -> Any:
    from mangatl.pipeline.batch import collect_volume  # type: ignore[attr-defined]

    return collect_volume(*args, **kwargs)


def _already_collected() -> type[Exception]:
    from mangatl.pipeline.batch import AlreadyCollected  # type: ignore[attr-defined]

    return typing.cast(type[Exception], AlreadyCollected)


def _results(results: Mapping[int, Any]) -> Any:
    from mangatl.domain.batch import BatchResults  # type: ignore[attr-defined]

    return BatchResults(results)


def _state(state: str) -> Any:
    from mangatl.domain.batch import BatchJobState  # type: ignore[attr-defined]

    return BatchJobState(state)


def _failure(ordinal: int, message: str) -> Any:
    from mangatl.domain.batch import BatchItemFailure  # type: ignore[attr-defined]

    return BatchItemFailure(ordinal, message)


def _waiting(job_id: int, state: str) -> Any:
    from mangatl.domain.events import BatchWaiting  # type: ignore[attr-defined]

    return BatchWaiting(job_id=job_id, state=state)


def _collected(
    job_id: int, pages_done: int, pages_failed: int, failures: tuple[tuple[int, str], ...]
) -> Any:
    from mangatl.domain.events import BatchCollected  # type: ignore[attr-defined]

    return BatchCollected(
        job_id=job_id, pages_done=pages_done, pages_failed=pages_failed, failures=failures
    )


def _failed(job_id: int, state: str) -> Any:
    from mangatl.domain.events import BatchFailed  # type: ignore[attr-defined]

    return BatchFailed(job_id=job_id, state=state)


# -- the double ------------------------------------------------------------------


class _Collector:
    """Stands where `compose.build_batch_collector`'s callable stands: records
    `(provider_job_id, pages)` per call and answers `answer`."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls: list[tuple[str, list[Any]]] = []

    def __call__(self, provider_job_id: str, pages: Sequence[Any]) -> Any:
        self.calls.append((provider_job_id, list(pages)))
        return self.answer


# -- the world -----------------------------------------------------------------


@dataclass
class _World:
    project: Project
    db_path: Path
    run_id: int
    later_run_id: int
    events: list[RunEvent] = field(default_factory=list)

    def job(self, first: int = 0, last: int = 2, name: str = _JOB) -> BatchJob:
        """Record a job over `first..last` against the job's run, and return it
        as `pending_jobs` reads it back."""
        job_id = record_submission(self.project, self.run_id, name, _MODEL, first, last)
        (job,) = [j for j in pending_jobs(self.project) if j.id == job_id]
        return job

    def collect(self, job: BatchJob, collector: _Collector) -> Any:
        return _collect_volume(self.project, job, collector, _ESTIMATE, self.events.append)

    def ledger(self) -> list[tuple[object, ...]]:
        """Every ledger row, oldest first, with its page as an ORDINAL (a LEFT
        JOIN, so a chapter-level row would read `None`)."""
        return self._raw(
            "SELECT llm_call.run_id, page.ordinal, llm_call.request_id, llm_call.model_id,"
            " llm_call.input_tokens, llm_call.output_tokens, llm_call.cache_write_tokens,"
            " llm_call.cache_read_tokens, llm_call.cost_micro_usd, llm_call.rate_table_version,"
            " llm_call.pricing"
            " FROM llm_call LEFT JOIN page ON page.id = llm_call.page_id ORDER BY llm_call.id"
        )

    def ledger_count(self) -> int:
        ((count,),) = self._raw("SELECT COUNT(*) FROM llm_call")
        return int(typing.cast(int, count))

    def job_row(self, job_id: int) -> tuple[object, ...]:
        """`(state, collected_at is set, failure)` straight off the table."""
        ((state, collected_at, failure),) = self._raw(
            f"SELECT state, collected_at, failure FROM batch_job WHERE id = {int(job_id)}"
        )
        return (state, collected_at is not None, failure)

    def read_back(self, job_id: int) -> BatchJob:
        """The job's row as a `BatchJob`, whatever its state - `pending_jobs`
        returns only `submitted` rows."""
        (row,) = self._raw(
            "SELECT id, run_id, provider_job_id, model_id, state, submitted_at, collected_at,"
            f" failure, first_ordinal, last_ordinal FROM batch_job WHERE id = {int(job_id)}"
        )
        values = list(row)
        return BatchJob(
            id=int(typing.cast(int, values[0])),
            run_id=int(typing.cast(int, values[1])),
            provider_job_id=str(values[2]),
            model_id=str(values[3]),
            state=typing.cast(Any, str(values[4])),
            submitted_at=str(values[5]),
            collected_at=typing.cast("str | None", values[6]),
            failure=typing.cast("str | None", values[7]),
            first_ordinal=int(typing.cast(int, values[8])),
            last_ordinal=int(typing.cast(int, values[9])),
        )

    def statuses(self) -> list[str]:
        return [self.project.page_status(n) for n in range(len(_SOURCE_PAGES))]

    def proposed(self) -> dict[int, tuple[str | None, ...]]:
        return {n: self.project.read_proposed(n) for n in range(len(_SOURCE_PAGES))}

    def expected_pages(self, ordinals: Sequence[int]) -> list[BatchPageInput]:
        """AC-2 / PO-3: what the collector is handed, built independently."""
        return [BatchPageInput(n, b"", self.project.read_lines(n), EMPTY_CONTEXT) for n in ordinals]

    def _raw(self, sql: str) -> list[tuple[object, ...]]:
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()


def _ring(x: int) -> tuple[tuple[int, int], ...]:
    return ((x, 0), (x + 4, 0), (x + 4, 4), (x, 4), (x, 0))


def _insert_run(project: Project, started_at: str) -> int:
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)", (chapter_id, started_at)
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


@pytest.fixture
def world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """Three pages, OCR on all three, a one-entry glossary, two runs, $0.06."""
    source_dir = tmp_path / "scans"
    source_dir.mkdir(parents=True)
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        mask = one_bit_png(8, 8, [(0, 0, 4, 4)])
        for ordinal, results in _LINES.items():
            project.write_regions(
                ordinal,
                [
                    RawRegion(polygon=_ring(i * 10), mask=mask, confidence=1.0, kind="bubble")
                    for i in range(len(results))
                ],
            )
            project.write_lines(ordinal, results)
        write_proposed_glossary(project, _GLOSSARY)
        run_id = _insert_run(project, "2026-11-03T09:00:00+00:00")
        later_run_id = _insert_run(project, "2026-11-04T09:00:00+00:00")
        with project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (_CEILING.micro(),))
        yield _World(project, project_dir_for(source_dir) / "project.db", run_id, later_run_id)


def _row(world: _World, ordinal: int) -> tuple[object, ...]:
    """AC-2's ledger row for `ordinal`, written out."""
    usage = _USAGE[ordinal]
    return (
        world.run_id,
        ordinal,
        f"{_JOB}#{ordinal}",
        _MODEL,
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_write_tokens,
        usage.cache_read_tokens,
        _BATCH_MICRO[ordinal],
        RATE_TABLE_VERSION,
        "batch",
    )


# -- preconditions the assertions below lean on ---------------------------------


def test_the_batch_row_prices_the_three_usages_at_the_written_out_figures() -> None:
    """Not a criterion: the literals `_BATCH_MICRO` against the shipped batch
    row, and the standard figures DV-1's mutant would record, so the two are
    known to differ on every page."""
    for ordinal, usage in _USAGE.items():
        assert price(_MODEL, usage, pricing="batch").cost.micro() == _BATCH_MICRO[ordinal]
        assert price(_MODEL, usage).cost.micro() == _STANDARD_MICRO[ordinal]
        assert _BATCH_MICRO[ordinal] != _STANDARD_MICRO[ordinal]


def test_the_world_has_two_runs_and_the_jobs_run_is_not_the_latest(world: _World) -> None:
    """Not a criterion: "against the job's `run_id`" is only observable if the
    job's run is not the most recent one."""
    assert world.run_id < world.later_run_id


def test_before_collection_page_1s_lines_read_proposed_not_failed(world: _World) -> None:
    """Not a criterion: AC-3's `failed` is caused by the page being marked done
    with no proposal - before collection the same lines read `proposed`."""
    assert [line.status for line in read_review_lines(world.project, 1) if line] == ["proposed"]


# -- the module's surface ----------------------------------------------------------


def test_the_batch_pipeline_module_exports_the_collector_its_refusal_and_collect_volume() -> None:
    import mangatl.pipeline.batch as module

    missing = [
        name
        for name in ("AlreadyCollected", "BatchCollector", "collect_volume")
        if name not in module.__all__
    ]
    assert missing == [], f"pipeline.batch.__all__ lacks {missing}"


def test_a_batch_collector_takes_a_job_name_and_its_pages_and_answers_a_batch_answer() -> None:
    from mangatl.domain.batch import BatchAnswer  # type: ignore[attr-defined]
    from mangatl.pipeline.batch import BatchCollector  # type: ignore[attr-defined]

    parameters, returned = typing.get_args(BatchCollector)
    assert parameters == [str, Sequence[BatchPageInput]]
    assert returned == BatchAnswer


def test_already_collected_is_an_exception() -> None:
    assert issubclass(_already_collected(), Exception)


def test_the_domain_batch_answer_is_a_state_or_the_results() -> None:
    from mangatl.domain.batch import (  # type: ignore[attr-defined]
        BatchAnswer,
        BatchJobState,
        BatchResults,
    )

    assert set(typing.get_args(BatchAnswer)) == {BatchJobState, BatchResults}


@pytest.mark.parametrize(
    ("name", "fields"),
    [
        pytest.param("BatchItemFailure", ["ordinal", "message"], id="item-failure"),
        pytest.param("BatchJobState", ["state"], id="job-state"),
        pytest.param("BatchResults", ["results"], id="results"),
    ],
)
def test_the_domain_batch_answer_types_are_frozen_with_the_contracts_fields(
    name: str, fields: list[str]
) -> None:
    from mangatl.domain import batch

    cls = getattr(batch, name)
    assert [f.name for f in dataclasses.fields(cls)] == fields
    assert cls.__dataclass_params__.frozen, f"{name} is not frozen"


def test_a_batch_job_state_answers_the_four_unsettled_words() -> None:
    from mangatl.domain.batch import BatchJobState  # type: ignore[attr-defined]

    hints = typing.get_type_hints(BatchJobState)
    assert typing.get_args(hints["state"]) == ("pending", "failed", "cancelled", "expired")


@pytest.mark.parametrize(
    ("name", "fields"),
    [
        pytest.param("BatchWaiting", ["job_id", "state"], id="waiting"),
        pytest.param(
            "BatchCollected", ["job_id", "pages_done", "pages_failed", "failures"], id="collected"
        ),
        pytest.param("BatchFailed", ["job_id", "state"], id="failed"),
    ],
)
def test_the_three_collection_events_are_frozen_run_events_with_the_contracts_fields(
    name: str, fields: list[str]
) -> None:
    from mangatl.domain import events

    cls = getattr(events, name)
    assert [f.name for f in dataclasses.fields(cls)] == fields
    assert cls.__dataclass_params__.frozen, f"{name} is not frozen"
    assert cls in typing.get_args(RunEvent), f"{name} is not in the RunEvent union"


def test_the_domain_events_module_exports_exactly_its_thirteen_names() -> None:
    from mangatl.domain import events

    assert events.__all__ == [
        "BatchCollected",
        "BatchFailed",
        "BatchSubmitted",
        "BatchWaiting",
        "CallPriced",
        "PageSkipped",
        "PageStarted",
        "RegionsDetected",
        "RunAborted",
        "RunEvent",
        "RunFinished",
        "RunStarted",
        "StageFinished",
    ]


# -- AC-1: the job is still pending ----------------------------------------------


def test_a_pending_job_emits_one_batch_waiting_and_returns_the_answer(world: _World) -> None:
    """AC-1: exactly `[BatchWaiting(job_id, state="pending")]`."""
    job = world.job()
    answer = _state("pending")

    returned = world.collect(job, _Collector(answer))

    assert world.events == [_waiting(job.id, "pending")], f"emitted {world.events}"
    assert returned == answer


def test_a_pending_job_writes_nothing_and_stays_pending(world: _World) -> None:
    """AC-1: no proposal, no ledger row, no page status change, the glossary as
    it was, and the job still in `pending_jobs`."""
    job = world.job()

    world.collect(job, _Collector(_state("pending")))

    assert world.ledger() == [], "a pending job wrote a ledger row"
    assert world.proposed() == {0: (None, None), 1: (None,), 2: (None, None)}
    assert world.statuses() == [PAGE_PENDING] * 3
    assert read_entries(world.project) == _GLOSSARY
    assert pending_jobs(world.project) == (job,)


# -- AC-2: every page answered ----------------------------------------------------


def _all_answered() -> Any:
    """The three results, deliberately not in ordinal order in the mapping, so
    an implementation that walked the answer rather than the job's ordinals
    emits out of order."""
    return _results({2: _RESULTS[2], 0: _RESULTS[0], 1: _RESULTS[1]})


def test_the_collector_is_handed_the_jobs_pages_with_no_image_and_no_context(
    world: _World,
) -> None:
    """AC-2 / PO-3: one call, `(provider_job_id, [BatchPageInput(n, b"",
    read_lines(n), EMPTY_CONTEXT) for n in job.ordinals])`."""
    job = world.job()
    collector = _Collector(_all_answered())

    world.collect(job, collector)

    assert collector.calls == [(_JOB, world.expected_pages([0, 1, 2]))]


def test_a_collected_job_writes_each_pages_proposals_by_reading_index(world: _World) -> None:
    job = world.job()

    world.collect(job, _Collector(_all_answered()))

    assert world.proposed() == _PROPOSED_AFTER_ALL


def test_a_collected_job_bills_one_batch_row_per_page_against_the_jobs_run(
    world: _World,
) -> None:
    """AC-2, and DV-1's target: one row per page, the job's `run_id` (not the
    later run), `request_id` `batches/a#n`, the item's usage, the batch-tier
    cost written out (4000 / 5000 / 7000 micro; the standard tier would be
    8000 / 10000 / 14000), the shipped rate table and `pricing == "batch"`."""
    job = world.job()

    world.collect(job, _Collector(_all_answered()))

    assert world.ledger() == [_row(world, 0), _row(world, 1), _row(world, 2)], (
        f"ledger rows {world.ledger()}"
    )


def test_a_collected_job_folds_proposals_and_sightings_into_the_glossary(world: _World) -> None:
    """AC-2: `merge` then `mark_seen` per page, as the translate stage does.
    ケンジ moves to page 2 by sighting alone; 先輩 keeps page 0's rendering;
    どこ is new on page 1."""
    job = world.job()

    world.collect(job, _Collector(_all_answered()))

    assert read_entries(world.project) == _GLOSSARY_AFTER_ALL


def test_a_collected_job_marks_every_page_done(world: _World) -> None:
    job = world.job()

    world.collect(job, _Collector(_all_answered()))

    assert world.statuses() == [PAGE_DONE] * 3


def test_a_collected_job_prices_each_page_in_order_then_reports_the_collection(
    world: _World,
) -> None:
    """AC-2: exactly three `CallPriced`, in ordinal order, with the numbers
    written out, then `BatchCollected(job_id, 3, 0, ())`."""
    job = world.job()

    world.collect(job, _Collector(_all_answered()))

    assert world.events == [*_PRICED_ALL, _collected(job.id, 3, 0, ())], f"emitted {world.events}"


def test_a_collected_job_is_no_longer_pending_and_reads_back_collected(world: _World) -> None:
    job = world.job()

    returned = world.collect(job, _Collector(_all_answered()))

    assert pending_jobs(world.project) == ()
    assert world.job_row(job.id) == ("collected", True, None)
    assert returned == _all_answered()


def test_collecting_one_job_of_two_touches_only_its_own_pages(world: _World) -> None:
    """AC-2 over several jobs per volume (MT-137): a job over page 2 alone is
    handed page 2 alone, writes and bills page 2 alone, and leaves the job
    over pages 0..1 pending."""
    first = world.job(0, 1, "batches/first")
    last = world.job(2, 2, "batches/last")
    collector = _Collector(_results({2: _RESULTS[2]}))

    world.collect(last, collector)

    assert collector.calls == [("batches/last", world.expected_pages([2]))]
    assert world.proposed() == {0: (None, None), 1: (None,), 2: ("Kenji-senpai", None)}
    assert [(row[1], row[2], row[8]) for row in world.ledger()] == [(2, "batches/last#2", 7_000)]
    assert world.statuses() == [PAGE_PENDING, PAGE_PENDING, PAGE_DONE]
    assert pending_jobs(world.project) == (first,)
    assert world.events == [
        CallPriced(2, Usd.from_micro(7_000), _CEILING, _projection(20_000, 0, "estimate", 1)),
        _collected(last.id, 1, 0, ()),
    ], f"emitted {world.events}"


def test_an_answer_missing_a_page_of_the_job_raises_and_leaves_the_job_pending(
    world: _World,
) -> None:
    """Contract step 5: an answer missing one of the job's ordinals is a
    `KeyError` (the adapter guarantees the shape), and the job is not marked
    collected."""
    job = world.job()

    with pytest.raises(KeyError):
        world.collect(job, _Collector(_results({0: _RESULTS[0], 2: _RESULTS[2]})))

    assert pending_jobs(world.project) == (job,)


# -- AC-3: one item failed -----------------------------------------------------------


def _middle_failed() -> Any:
    return _results({0: _RESULTS[0], 1: _failure(1, "quota"), 2: _RESULTS[2]})


def test_a_failed_item_writes_and_bills_only_the_other_pages(world: _World) -> None:
    """AC-3: pages 0 and 2 as in AC-2; page 1 no proposal and no ledger row."""
    job = world.job()

    world.collect(job, _Collector(_middle_failed()))

    assert world.proposed() == {0: _PROPOSED_AFTER_ALL[0], 1: (None,), 2: _PROPOSED_AFTER_ALL[2]}
    assert world.ledger() == [_row(world, 0), _row(world, 2)]
    assert read_entries(world.project) == _GLOSSARY_AFTER_FAILURE


def test_a_failed_items_page_is_done_so_its_lines_read_failed_untranslated(
    world: _World,
) -> None:
    """AC-3 / PO-1: page 1 is marked done with no proposal, so its line reads
    `failed` with the existing reason - the item's message is not stored."""
    job = world.job()

    world.collect(job, _Collector(_middle_failed()))

    assert world.statuses() == [PAGE_DONE] * 3
    lines = [line for line in read_review_lines(world.project, 1) if line is not None]
    assert [(line.status, failure_reason(line)) for line in lines] == [
        ("failed", "no translation was returned")
    ]


def test_a_failed_item_prices_two_pages_and_carries_its_message_on_the_event(
    world: _World,
) -> None:
    """AC-3: two `CallPriced` (pages 0 and 2), then `BatchCollected(job_id,
    pages_done=2, pages_failed=1, failures=((1, "quota"),))`."""
    job = world.job()

    world.collect(job, _Collector(_middle_failed()))

    assert world.events == [*_PRICED_WITH_FAILURE, _collected(job.id, 2, 1, ((1, "quota"),))], (
        f"emitted {world.events}"
    )
    assert pending_jobs(world.project) == ()
    assert world.job_row(job.id) == ("collected", True, None)


# -- AC-4: the job failed, was cancelled or expired -----------------------------------


@pytest.mark.parametrize("state", ["failed", "cancelled", "expired"])
def test_a_job_that_will_never_finish_is_marked_failed_and_writes_nothing(
    world: _World, state: str
) -> None:
    """AC-4: the job is `failed` with the state as its `failure` text, nothing
    reaches a page or the ledger, and exactly `[BatchFailed(job_id, state)]`."""
    job = world.job()

    world.collect(job, _Collector(_state(state)))

    assert world.events == [_failed(job.id, state)], f"emitted {world.events}"
    assert world.job_row(job.id) == ("failed", False, state)
    assert pending_jobs(world.project) == ()
    assert world.ledger() == []
    assert world.proposed() == {0: (None, None), 1: (None,), 2: (None, None)}
    assert world.statuses() == [PAGE_PENDING] * 3
    assert read_entries(world.project) == _GLOSSARY


# -- AC-5: a job already settled ---------------------------------------------------------


@pytest.mark.parametrize("state", ["collected", "failed"])
def test_a_settled_job_is_refused_by_name_before_the_collector_is_called(
    world: _World, state: str
) -> None:
    """AC-5: `AlreadyCollected` naming the job's id and provider id; the
    collector is never called and nothing is emitted or billed."""
    job = dataclasses.replace(world.job(), state=state)  # type: ignore[arg-type]
    collector = _Collector(_all_answered())

    with pytest.raises(_already_collected()) as raised:
        world.collect(job, collector)

    message = str(raised.value)
    assert re.search(rf"(?<!\d){job.id}(?!\d)", message), f"the job id is not named: {message!r}"
    assert _JOB in message, f"the provider job id is not named: {message!r}"
    assert collector.calls == [], "the collector was called for a settled job"
    assert world.events == []
    assert world.ledger_count() == 0


def test_collecting_the_same_job_twice_never_writes_a_second_bill(world: _World) -> None:
    """AC-5, and DV-2's target: one collection, then the job read back from the
    table (state `collected`) handed to `collect_volume` again. The ledger
    still holds exactly three rows - counted BEFORE the refusal is asserted,
    so with the check removed this fails on the six-row double bill rather
    than on a missing exception."""
    job = world.job()
    world.collect(job, _Collector(_all_answered()))
    again = world.read_back(job.id)
    assert again.state == "collected", f"precondition: the job reads back {again.state!r}"

    refused: Exception | None = None
    try:
        world.collect(again, _Collector(_all_answered()))
    except _already_collected() as error:
        refused = error

    rows = world.ledger_count()
    assert rows == 3, f"a second collection of one job wrote a second bill: {rows} ledger rows"
    assert refused is not None, "collecting a collected job a second time was not refused"
