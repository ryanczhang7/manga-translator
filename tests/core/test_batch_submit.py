"""MT-111 AC-4..AC-9: `pipeline.batch.submit_volume`, a volume guarded as a whole
and submitted as the inline jobs that fit.

EPIC-09 PO-5 and D6 applied to a batch: **the guard judges the whole volume
before anything is submitted**, and a refused batch submits nothing and spends
nothing. After detect, clean and OCR have run on every page and the glossary
pre-pass has proposed terms, `submit_volume` builds every page's input in
`neighbours` context (MT-107), splits them into jobs (`plan_batches`, AC-3),
projects and checks the whole volume **once**, submits each job through the
bound submitter, records one `batch_job` row per job (MT-137), and emits
`BatchSubmitted`.

**Oracle partition: mechanical.** The page estimate handed in is $0.02, the
figure AC-1 settles for gemini-3.1-pro-preview at the batch tier, written out
here as 20,000 micro-dollars rather than computed through `page_estimate`, so
these tests do not go red for AC-1's reason. Three pages are $0.06: a stored
ceiling of $0.06 permits (inclusive), $0.05 refuses.

**The world is real**: a `.mtproj` on `tmp_path` with three tiny PNG pages,
regions and OCR lines seeded through the store, a glossary written through
`store.glossary.write_proposed_glossary` (so the `neighbours` context has a
non-empty glossary block *and* a non-empty neighbours block - a context
built in `rolling` mode, or not at all, cannot compare equal), a `run` row and
a stored ceiling. The two doubles are the submitter (`_Submitter`, standing
where `compose`'s bound `submit_batch` stands, returning `batches/a`,
`batches/b`, ...) and the request-size function (a constant, so the split is
chosen by integers: 1 byte a page fits one job at any limit; 10 bytes a page
against `limit=20` forces `[0, 1]` then `[2]`).

**The order of the guard and the submits is observed, not inferred.**
`Budget.check` is wrapped on the class (`guard` fixture) so every consultation
- through `pipeline.translate_stage.budget_for` or any other route to a
`Budget` - appends to the same log the submitter appends to. "Consulted once,
before the first submit" is then an equality on one ordered list.

**Rows are read through `store.batch.pending_jobs`** (MT-137's own reader,
already shipped and tested against raw sqlite in `test_batch_store.py`), and
the ledger through a plain `sqlite3` reader.

**Imports of the module under test are inside helpers** (`_submit_volume`,
`_batch_page_input`, `_batch_submitted`), so in RED each test fails on the
named absence and the file is never dark at collection.

**What these tests do NOT constrain**, so it stays GREEN's choice: how
`submit_volume` reads the pages or the images (only that the bytes are the
source file's), whether it calls `request_size` once per page or more, the
wording of any message beyond the needles named, and whether the RunAborted
text for AC-8 names the pending range. `limit` is passed by keyword
(`limit=20`) and every other argument after `project, run_id` by its Contract
name.

**AC-6 is as amended (story `## Amendments` A-1, the user, 2026-11-03):** a
refused volume emits exactly two events, in order - `CallPriced(ordinal=None,
spent, ceiling, projection)` carrying the decision's numbers, then
`RunAborted(reason="budget", ordinal=None)` with the reason **exactly** the
runner's `BUDGET`, which the window's over-budget state matches with `==`
(`ui/progress.py:319`). Both are pinned as literal event lists.

**Timing.** No `pytest-timeout` in this project; every test builds a
three-page chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import dataclasses
import re
import sqlite3
import typing
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from mangatl.domain.budget import Budget, Projection
from mangatl.domain.events import CallPriced, RunAborted, RunEvent
from mangatl.domain.glossary import EMPTY_CONTEXT, GlossaryEntry
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.rates import price
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import TokenUsage
from mangatl.pipeline.continuity import build_prompt_context
from mangatl.pipeline.runner import BUDGET
from mangatl.store.batch import pending_jobs, record_submission
from mangatl.store.glossary import write_proposed_glossary
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import chapter_total, record_call
from mangatl.store.project import Project, create_project, project_dir_for

# -- the numbers ---------------------------------------------------------------

_MODEL = "gemini-3.1-pro-preview"

#: AC-1's settled batch page estimate, written out: $0.02.
_ESTIMATE = Usd.from_micro(20_000)

#: 3 pages x $0.02, the whole volume as one decision.
_VOLUME = Usd.from_micro(60_000)

#: AC-5's projection, written out.
_PROJECTION = Projection(
    next_call=_VOLUME, remaining_chapter=_VOLUME, basis="estimate", sample_count=0
)

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

#: OCR seeded on every page: AC-4's "OCR done on three pages".
_LINES: dict[int, tuple[OcrResult, ...]] = {
    0: (OcrResult("ケンジ、待って"), OcrResult("先輩…")),
    1: (OcrResult("どこへ行くの"),),
    2: (OcrResult("ケンジ先輩"), OcrResult("", ocr_empty=True)),
}

#: The glossary the pre-pass proposed (AC-4's "a glossary proposed").
_GLOSSARY = [GlossaryEntry("ケンジ", "Kenji", "name", 0, 2, "model")]


def _number(value: int) -> re.Pattern[str]:
    """`value` as a whole number: `1` does not match inside `11`, `10` or `-1`."""
    return re.compile(rf"(?<![\d-]){value}(?!\d)")


# -- doubles -------------------------------------------------------------------


class _Submitter:
    """Stands where `compose`'s bound `submit_batch` stands: one call is one
    job. Records each call's inputs and appends `("submit", k)` to the shared
    log; returns `batches/a`, `batches/b`, ... - or raises `raises` on call
    `fail_on`."""

    def __init__(
        self, log: list[object], *, fail_on: int | None = None, raises: Exception | None = None
    ) -> None:
        self.log = log
        self.fail_on = fail_on
        self.raises = raises
        self.calls: list[list[Any]] = []

    def __call__(self, inputs: Sequence[Any]) -> str:
        self.calls.append(list(inputs))
        k = len(self.calls)
        self.log.append(("submit", k))
        if k == self.fail_on and self.raises is not None:
            raise self.raises
        return f"batches/{chr(ord('a') + k - 1)}"


def _size(value: int) -> Callable[[Any], int]:
    def request_size(page_input: Any) -> int:
        return value

    return request_size


# -- the world -----------------------------------------------------------------


@dataclass
class _World:
    project: Project
    db_path: Path
    source_dir: Path
    run_id: int
    log: list[object] = field(default_factory=list)
    events: list[RunEvent] = field(default_factory=list)

    def set_ceiling(self, micro: int) -> None:
        """Raw SQL, as `test_glossary_prelude.py` does: no shipped writer exists."""
        with self.project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))

    def checks(self) -> list[object]:
        return [entry for entry in self.log if isinstance(entry, tuple) and entry[0] == "check"]

    def ledger(self) -> list[tuple[object, ...]]:
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(
                "SELECT page_id, cost_micro_usd, request_id FROM llm_call ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

    def expected_inputs(self) -> list[Any]:
        """What AC-4 says the submitter is handed, built independently: the
        page's source bytes, its stored lines, and its `neighbours` context."""
        return [
            _batch_page_input(
                page.ordinal,
                (self.source_dir / page.filename).read_bytes(),
                self.project.read_lines(page.ordinal),
                build_prompt_context(self.project, page.ordinal, mode="neighbours"),
            )
            for page in self.project.pages()
        ]

    def submit(
        self, submitter: _Submitter, *, size: int = 1, limit: int | None = None
    ) -> tuple[int, ...]:
        extra: dict[str, int] = {} if limit is None else {"limit": limit}
        return _submit_volume(
            self.project,
            self.run_id,
            submit=submitter,
            request_size=_size(size),
            model_id=_MODEL,
            page_estimate=_ESTIMATE,
            emit=self.events.append,
            **extra,
        )


def _submit_volume(project: Project, run_id: int, **kwargs: Any) -> tuple[int, ...]:
    from mangatl.pipeline.batch import submit_volume  # type: ignore[import-not-found]

    ids: tuple[int, ...] = submit_volume(project, run_id, **kwargs)
    return ids


def _batch_page_input(ordinal: int, image: bytes, lines: Any, context: Any) -> Any:
    from mangatl.domain.batch import BatchPageInput  # type: ignore[attr-defined]

    return BatchPageInput(
        ordinal=ordinal, page_image=image, ocr_results=tuple(lines), context=context
    )


def _batch_submitted(**kwargs: Any) -> Any:
    from mangatl.domain.events import BatchSubmitted  # type: ignore[attr-defined]

    return BatchSubmitted(**kwargs)


def _ring(x: int) -> tuple[tuple[int, int], ...]:
    return ((x, 0), (x + 4, 0), (x + 4, 4), (x, 4), (x, 0))


def _make_world(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    lines: dict[int, tuple[OcrResult, ...]],
) -> Iterator[_World]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir(parents=True)
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        mask = one_bit_png(8, 8, [(0, 0, 4, 4)])
        for ordinal, results in lines.items():
            project.write_regions(
                ordinal,
                [
                    RawRegion(polygon=_ring(i * 10), mask=mask, confidence=1.0, kind="bubble")
                    for i in range(len(results))
                ],
            )
            project.write_lines(ordinal, results)
        write_proposed_glossary(project, _GLOSSARY)
        with project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-11-03T09:00:00+00:00"),
            )
            run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
        world = _World(project, project_dir_for(source_dir) / "project.db", source_dir, run_id)
        world.set_ceiling(_VOLUME.micro())
        yield world


@pytest.fixture
def world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """Three pages, OCR on all three, a glossary proposed, a $0.06 ceiling."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, _LINES)


@pytest.fixture
def unread_world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """The same, with no lines stored on page 1 (AC-9)."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, {0: _LINES[0], 2: _LINES[2]})


@pytest.fixture
def guard(world: _World, monkeypatch: pytest.MonkeyPatch) -> _World:
    """`Budget.check` wrapped on the class so every consultation is logged, in
    order with the submitter's calls, with the projection it judged."""
    _wrap_check(world, monkeypatch)
    return world


@pytest.fixture
def unread_guard(unread_world: _World, monkeypatch: pytest.MonkeyPatch) -> _World:
    _wrap_check(unread_world, monkeypatch)
    return unread_world


def _wrap_check(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Budget.check

    def check(self: Budget, spent: Usd, projection: Projection) -> Any:
        world.log.append(("check", projection))
        return original(self, spent, projection)

    monkeypatch.setattr(Budget, "check", check)


# -- preconditions the assertions below lean on ---------------------------------


def test_the_world_makes_neighbours_context_distinguishable(world: _World) -> None:
    """Not a criterion: if `neighbours` and `rolling` contexts were equal here,
    AC-4's context assertion could not tell them apart."""
    for page in world.project.pages():
        neighbours = build_prompt_context(world.project, page.ordinal, mode="neighbours")
        assert neighbours.glossary_block != "", f"page {page.ordinal}: empty glossary block"
        assert neighbours.rolling_block != "", f"page {page.ordinal}: no neighbours block"
        assert neighbours != build_prompt_context(world.project, page.ordinal, mode="rolling")
    assert build_prompt_context(world.project, 0) == EMPTY_CONTEXT


# -- the module's surface --------------------------------------------------------


def test_the_batch_pipeline_module_exports_exactly_its_contract() -> None:
    import mangatl.pipeline.batch as module  # type: ignore[import-not-found]

    # MT-112 adds the collector, its refusal and `collect_volume`, in RUF022's order.
    assert module.__all__ == [
        "AlreadyCollected",
        "BatchCollector",
        "BatchSubmitter",
        "RequestSize",
        "collect_volume",
        "submit_volume",
    ]


def test_batch_submitted_is_a_run_event_and_is_exported() -> None:
    from mangatl.domain import events

    submitted = events.BatchSubmitted  # type: ignore[attr-defined]
    assert submitted in typing.get_args(RunEvent), "BatchSubmitted is not in the RunEvent union"
    assert "BatchSubmitted" in events.__all__


def test_batch_submitted_carries_the_run_its_jobs_its_page_count_and_its_projection() -> None:
    from mangatl.domain.events import BatchSubmitted  # type: ignore[attr-defined]

    assert [f.name for f in dataclasses.fields(BatchSubmitted)] == [
        "run_id",
        "job_ids",
        "page_count",
        "projection",
    ]
    event = BatchSubmitted(run_id=1, job_ids=(4, 5), page_count=3, projection=_PROJECTION)
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.page_count = 4  # type: ignore[misc]


def test_the_domain_batch_module_exports_the_page_input_the_limit_and_the_planner() -> None:
    from mangatl.domain import batch

    # MT-112 adds the collector's answer types, in RUF022's order.
    assert batch.__all__ == [
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


def test_a_batch_page_input_is_a_frozen_ordinal_image_ocr_and_context() -> None:
    from mangatl.domain.batch import BatchPageInput  # type: ignore[attr-defined]

    assert [f.name for f in dataclasses.fields(BatchPageInput)] == [
        "ordinal",
        "page_image",
        "ocr_results",
        "context",
    ]
    page_input = BatchPageInput(0, b"png", (OcrResult("あ"),), EMPTY_CONTEXT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        page_input.ordinal = 1  # type: ignore[misc]


# -- AC-4: the volume fits one job --------------------------------------------------


def test_a_volume_that_fits_one_job_is_submitted_once_with_every_page_in_order(
    guard: _World,
) -> None:
    """AC-4: one submit call, handed the three pages in ordinal order, each
    with its source image, its stored lines and its `neighbours` context."""
    submitter = _Submitter(guard.log)

    guard.submit(submitter)

    assert len(submitter.calls) == 1, f"the submitter was called {len(submitter.calls)} times"
    assert submitter.calls[0] == guard.expected_inputs()


def test_a_volume_that_fits_one_job_records_one_pending_row_over_every_page(
    guard: _World,
) -> None:
    submitter = _Submitter(guard.log)

    returned = guard.submit(submitter)

    rows = pending_jobs(guard.project)
    assert [
        (r.first_ordinal, r.last_ordinal, r.provider_job_id, r.model_id, r.run_id) for r in rows
    ] == [(0, 2, "batches/a", _MODEL, guard.run_id)]
    assert returned == (rows[0].id,), f"submit_volume returned {returned}, not the row's id"


def test_a_volume_that_fits_one_job_emits_one_batch_submitted_and_nothing_else(
    guard: _World,
) -> None:
    submitter = _Submitter(guard.log)

    guard.submit(submitter)

    (row,) = pending_jobs(guard.project)
    assert guard.events == [
        _batch_submitted(
            run_id=guard.run_id, job_ids=(row.id,), page_count=3, projection=_PROJECTION
        )
    ]


def test_with_no_limit_given_the_inline_limit_is_twenty_million_bytes(guard: _World) -> None:
    """The `limit` default is `INLINE_REQUEST_LIMIT_BYTES`: three pages of
    6,700,000 bytes are 20,100,000 together - over 20 MB, under 20 MiB - so the
    default splits them `[0, 1]`, `[2]`."""
    submitter = _Submitter(guard.log)

    guard.submit(submitter, size=6_700_000)

    assert [[i.ordinal for i in call] for call in submitter.calls] == [[0, 1], [2]]


# -- AC-5: the volume needs two jobs, and is guarded once ----------------------------


def test_a_volume_split_in_two_is_submitted_as_pages_0_1_then_page_2(guard: _World) -> None:
    """AC-5: 10 bytes a page against a 20-byte limit."""
    submitter = _Submitter(guard.log)

    guard.submit(submitter, size=10, limit=20)

    expected = guard.expected_inputs()
    assert submitter.calls == [expected[0:2], expected[2:3]], (
        f"submit calls were {[[i.ordinal for i in c] for c in submitter.calls]}, not [[0, 1], [2]]"
    )


def test_a_volume_split_in_two_records_two_rows_in_page_order(guard: _World) -> None:
    submitter = _Submitter(guard.log)

    returned = guard.submit(submitter, size=10, limit=20)

    rows = pending_jobs(guard.project)
    assert [(r.first_ordinal, r.last_ordinal, r.provider_job_id) for r in rows] == [
        (0, 1, "batches/a"),
        (2, 2, "batches/b"),
    ]
    assert returned == tuple(r.id for r in rows)


def test_a_volume_split_in_two_is_guarded_once_before_the_first_submit(guard: _World) -> None:
    """AC-5: the guard is consulted exactly once, on the whole volume, and the
    first submit comes after it - one ordered log, not two counters."""
    submitter = _Submitter(guard.log)

    guard.submit(submitter, size=10, limit=20)

    assert guard.log == [("check", _PROJECTION), ("submit", 1), ("submit", 2)], (
        f"expected one check on the whole volume ($0.06) and then two submits; log: {guard.log}"
    )


def test_a_volume_split_in_two_projects_the_whole_volume_not_one_job(guard: _World) -> None:
    """AC-5, and DV-2's target: `BatchSubmitted.projection.next_call` is
    3 x $0.02 = $0.06. Guarding per job would project $0.04 then $0.02."""
    submitter = _Submitter(guard.log)

    guard.submit(submitter, size=10, limit=20)

    rows = pending_jobs(guard.project)
    assert len(guard.events) == 1, f"expected one event, got {guard.events}"
    (event,) = guard.events
    assert event.projection.next_call == _VOLUME, (  # type: ignore[union-attr]
        f"the projection judged {event.projection.next_call}, not the whole volume's $0.0600"  # type: ignore[union-attr]
    )
    assert event == _batch_submitted(
        run_id=guard.run_id, job_ids=tuple(r.id for r in rows), page_count=3, projection=_PROJECTION
    )


# -- AC-6: the volume does not fit the ceiling -----------------------------------------


def test_a_volume_over_the_ceiling_submits_nothing_and_records_nothing(guard: _World) -> None:
    """AC-6, and DV-1's target: a $0.05 ceiling against a $0.06 volume. The
    submitter is never called, no row exists, and nothing is returned."""
    guard.set_ceiling(50_000)
    submitter = _Submitter(guard.log)

    returned = guard.submit(submitter)

    assert submitter.calls == [], "the submitter was called on a refused volume"
    assert pending_jobs(guard.project) == ()
    assert returned == ()
    assert guard.checks() == [("check", _PROJECTION)], "the guard judged something else"


def test_a_volume_over_the_ceiling_prices_the_decision_then_aborts_on_the_budget(
    guard: _World,
) -> None:
    """AC-6 (as amended, A-1): exactly two events, in order - a
    `CallPriced(ordinal=None)` carrying the decision's numbers ($0.00 spent,
    the $0.05 ceiling, the whole volume's $0.06 projection), then
    `RunAborted(reason="budget", ordinal=None)`, the reason **exactly** the
    runner's `BUDGET`, the string the window's over-budget state matches."""
    guard.set_ceiling(50_000)

    guard.submit(_Submitter(guard.log))

    assert BUDGET == "budget", "precondition: the runner's word"
    assert guard.events == [
        CallPriced(
            ordinal=None,
            spent=Usd.from_micro(0),
            ceiling=Usd.from_micro(50_000),
            projection=_PROJECTION,
        ),
        RunAborted(reason="budget", ordinal=None),
    ], f"a refused volume emitted {guard.events}"


def test_a_refusal_after_earlier_spend_prices_three_different_numbers(guard: _World) -> None:
    """AC-6 with the numbers made distinct: $0.01 already spent, $0.06 ceiling,
    so $0.01 + $0.06 = $0.07 is over. An implementation that ignored the
    chapter's spend would permit this volume; one that reported the batch's
    cost as the spend, or the default ceiling, would not match the literal."""
    record_call(
        guard.project, guard.run_id, None, "req-earlier", price(_MODEL, TokenUsage(5_000, 0, 0, 0))
    )
    assert chapter_total(guard.project) == Usd.from_micro(10_000), "precondition: $0.01 spent"
    submitter = _Submitter(guard.log)

    returned = guard.submit(submitter)

    assert submitter.calls == []
    assert pending_jobs(guard.project) == ()
    assert returned == ()
    assert guard.events == [
        CallPriced(
            ordinal=None,
            spent=Usd.from_micro(10_000),
            ceiling=Usd.from_micro(60_000),
            projection=_PROJECTION,
        ),
        RunAborted(reason="budget", ordinal=None),
    ], f"a refused volume emitted {guard.events}"
    assert chapter_total(guard.project) == Usd.from_micro(10_000), "the refusal spent money"


def test_a_refused_volume_leaves_the_ledger_unchanged(guard: _World) -> None:
    guard.set_ceiling(50_000)
    before = guard.ledger()

    guard.submit(_Submitter(guard.log))

    assert guard.ledger() == before
    assert chapter_total(guard.project) == Usd.from_micro(0)


def test_a_volume_exactly_at_the_ceiling_is_permitted(guard: _World) -> None:
    """The inclusive edge: $0.00 + $0.06 on a $0.06 ceiling submits."""
    assert guard.project.budget_ceiling() == _VOLUME, "precondition"
    submitter = _Submitter(guard.log)

    guard.submit(submitter)

    assert len(submitter.calls) == 1


# -- AC-7: a job refused part-way ---------------------------------------------------


def test_a_second_job_refused_leaves_the_first_recorded_and_aborts_naming_job_2_of_2(
    guard: _World,
) -> None:
    """AC-7: the submitter raises on its second call. Job 1's row exists and is
    pending, job 2 has none, `RunAborted(ordinal=None)` names `job 2 of 2` and
    the exception's message, the return is job 1's id, and nothing is retried."""
    submitter = _Submitter(guard.log, fail_on=2, raises=RuntimeError("quota"))

    returned = guard.submit(submitter, size=10, limit=20)

    rows = pending_jobs(guard.project)
    assert [(r.first_ordinal, r.last_ordinal, r.provider_job_id) for r in rows] == [
        (0, 1, "batches/a")
    ]
    assert returned == (rows[0].id,)
    assert len(submitter.calls) == 2, f"{len(submitter.calls)} submit calls: a retry, or a stop"
    assert len(guard.events) == 1 and isinstance(guard.events[0], RunAborted), guard.events
    (aborted,) = guard.events
    assert aborted.ordinal is None  # type: ignore[union-attr]
    reason = aborted.reason  # type: ignore[union-attr]
    assert re.search(r"\bjob 2 of 2\b", reason), f"the abort does not name job 2 of 2: {reason!r}"
    assert "quota" in reason, f"the abort does not carry the exception's message: {reason!r}"


def test_a_first_job_refused_records_nothing_and_aborts_naming_job_1_of_2(
    guard: _World,
) -> None:
    submitter = _Submitter(guard.log, fail_on=1, raises=RuntimeError("quota"))

    returned = guard.submit(submitter, size=10, limit=20)

    assert pending_jobs(guard.project) == ()
    assert returned == ()
    assert len(submitter.calls) == 1, "the second job was submitted after the first was refused"
    (aborted,) = guard.events
    assert isinstance(aborted, RunAborted)
    assert re.search(r"\bjob 1 of 2\b", aborted.reason), aborted.reason


# -- AC-8: a pending job already holds a page ------------------------------------------


def test_a_pending_job_over_a_page_of_the_volume_blocks_before_the_guard(guard: _World) -> None:
    """AC-8: a job still pending over page 1. No submit, no guard, a
    `RunAborted` naming its provider id, and the pending row untouched."""
    record_submission(guard.project, guard.run_id, "batches/earlier", _MODEL, 1, 1)
    submitter = _Submitter(guard.log)

    returned = guard.submit(submitter)

    assert submitter.calls == []
    assert guard.checks() == [], "the guard was consulted for a volume already pending"
    assert returned == ()
    assert len(guard.events) == 1 and isinstance(guard.events[0], RunAborted), guard.events
    (aborted,) = guard.events
    assert aborted.ordinal is None  # type: ignore[union-attr]
    assert "batches/earlier" in aborted.reason, aborted.reason  # type: ignore[union-attr]
    assert [r.provider_job_id for r in pending_jobs(guard.project)] == ["batches/earlier"]


def test_a_pending_job_overlapping_only_the_last_page_still_blocks(guard: _World) -> None:
    record_submission(guard.project, guard.run_id, "batches/tail", _MODEL, 2, 5)
    submitter = _Submitter(guard.log)

    assert guard.submit(submitter) == ()
    assert submitter.calls == []


@pytest.mark.parametrize(
    ("first", "last"),
    [
        pytest.param(7, 9, id="far-past-the-volume"),
        pytest.param(3, 3, id="just-past-the-last-page"),
    ],
)
def test_a_pending_job_over_pages_the_volume_does_not_have_does_not_block(
    guard: _World, first: int, last: int
) -> None:
    """AC-8's other half: the volume is ordinals 0..2, so a job over 3.. holds
    none of its pages."""
    record_submission(guard.project, guard.run_id, "batches/elsewhere", _MODEL, first, last)
    submitter = _Submitter(guard.log)

    returned = guard.submit(submitter)

    assert len(submitter.calls) == 1, "a pending job over other pages blocked the volume"
    rows = pending_jobs(guard.project)
    assert [(r.first_ordinal, r.last_ordinal, r.provider_job_id) for r in rows] == [
        (0, 2, "batches/a"),
        (first, last, "batches/elsewhere"),
    ]
    assert returned == (rows[0].id,)


# -- AC-9: a page whose OCR has not run --------------------------------------------------


def test_a_page_with_no_stored_lines_refuses_before_the_guard_and_any_submit(
    unread_guard: _World,
) -> None:
    """AC-9: page 1 has no lines. Refused before the guard and before any
    submit, with `RunAborted` naming ordinal 1 - in the text and as `ordinal`."""
    submitter = _Submitter(unread_guard.log)

    returned = unread_guard.submit(submitter)

    assert submitter.calls == []
    assert unread_guard.checks() == [], "the guard was consulted for a volume with no OCR"
    assert pending_jobs(unread_guard.project) == ()
    assert returned == ()
    assert len(unread_guard.events) == 1, unread_guard.events
    (aborted,) = unread_guard.events
    assert aborted == RunAborted(reason=aborted.reason, ordinal=1), aborted  # type: ignore[union-attr]
    assert _number(1).search(aborted.reason), aborted.reason  # type: ignore[union-attr]
