"""MT-044: a run translates, prices every call, and stops at the ceiling.

Covers **AC-1**, **AC-2**, **AC-3** and **AC-5**, and AC-4's run half from the
budget side. AC-4's stage-list half is `tests/core/test_stages.py`; the stage's
own store behaviour is `tests/core/test_translate_stage.py`; the budget
arithmetic is MT-013's `tests/core/test_budget.py` and the pricing is MT-012's
`tests/core/test_rates.py`, and **neither is re-derived here**.

This file is the seam. MT-011 shipped `TranslateStage` in no stage list, MT-012
shipped `record_call` with no production caller, and MT-013 shipped a correct
guard reading a ledger nothing writes - so `spent` was permanently $0 and the
guard was inert in the running app, however correct its arithmetic. Everything
below is a claim about the three of them joined up.

Five conventions, each with a reason that was paid for somewhere:

- **The oracles are imported, not re-derived.** `DEFAULT_CEILING`,
  `BOOTSTRAP_PAGE_ESTIMATE` and `MIN_SAMPLES_FOR_PROJECTION` are MT-013's and are
  already tested in `tests/core/test_budget.py`; `price` is MT-012's and is
  already tested in `tests/core/test_rates.py`. A second copy of that arithmetic
  here would be a second thing to keep in step, and it would agree with any
  formula the implementation happened to use. What *is* written down as a
  literal is the **outcome** - which page is refused, how many rows exist - read
  out of RED's own out-of-framework run of the shipped `Budget` and `price` and
  recorded in MT-044's `## Handoff: RED -> GREEN`.

- **AC-2 and AC-3 are asserted against one fixture, in one test.** An
  implementation that records nothing for *any* page satisfies "no row for the
  refused page" trivially. "No row here" is only a claim because "exactly one
  row there" is true at the same time, of the same run, in the same table. That
  asymmetry is DV-4, and the test that has to show it is
  `test_the_refused_page_has_no_ledger_row_and_the_pages_before_it_have_one_each`.

- **`reason` is compared with `==`, never `in`.** C-3: `BudgetRefused` **is** an
  `Exception`, so a general `except Exception` placed before the specific arm
  swallows it and produces `reason="BudgetRefused: the projected next call of
  ..."` - a plausible string that fails an exact comparison and **passes any
  substring check**. The mistake is one line of ordering.

- **The store is observed with a plain `sqlite3` connection.** MT-005's and
  MT-012's convention: "a codec that is uniformly wrong round-trips through
  itself perfectly" (`tdd-cycle`), so the ledger rows this seam writes are read
  back by something that imports nothing from `mangatl.store`.

- **No GPU, no network, no API key.** The three stage callables are doubles, as
  `tests/core/test_stages.py` and `test_cli.py` already do. `architecture.md`
  §6: commands in, typed events out, and the runner never calls a widget.

**Timing.** There is no `pytest-timeout` in this project and no per-test
timeout, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. Every test builds a three-page chapter of
tiny PNGs on `tmp_path` and touches at most nine rows.
"""

from __future__ import annotations

import ast
import dataclasses
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from mangatl.domain.budget import (
    BOOTSTRAP_PAGE_ESTIMATE,
    DEFAULT_CEILING,
    MIN_SAMPLES_FOR_PROJECTION,
    Budget,
    Decision,
)
from mangatl.domain.events import RunAborted, RunEvent, RunFinished
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.rates import price
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.pipeline.runner import BUDGET, RUN_ABORTED, RUN_FINISHED, run_chapter
from mangatl.pipeline.stage import BudgetRefused, PageContext
from mangatl.pipeline.stages import build_stages
from mangatl.pipeline.translate_stage import TranslateStage, budget_for, pages_remaining
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.project import (
    PAGE_DONE,
    PAGE_PENDING,
    Project,
    create_project,
    project_dir_for,
)

# -- the fixture chapter -------------------------------------------------------

#: Three pages at three distinct sizes, so "this page's own bytes" stays
#: falsifiable and the fixture is the smallest one in which a run can be
#: permitted, permitted and then refused.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)
_PAGE_COUNT = len(_SOURCE_PAGES)

#: The regions the fake detector finds on every page, and therefore the number
#: of OCR results and proposals a page carries.
_REGIONS_PER_PAGE = 2


@dataclass(frozen=True)
class _Call:
    """What one page's fake translator reports, and what it must cost.

    `micro` is **not** recomputed from the rates here - `test_rates.py` owns
    that arithmetic and this file would agree with any formula if it re-derived
    it. The number is read out of RED's own out-of-framework run of the shipped
    `domain.rates.price`, recorded in `## Handoff: RED -> GREEN`. The assertions
    check the stored value against `price(...)` **and** against this literal, so
    a rate table that silently changed shows up as a disagreement rather than as
    two things moving together.
    """

    request_id: str
    model_id: str
    usage: TokenUsage
    micro: int


#: Two models, so "priced by the model the response names" is falsifiable: an
#: implementation that pinned `prompt.MODEL_ID` would price page 1 at opus rates
#: and store 150,000 instead of 60,000.
#:
#: MEASURED out of framework, 2026-09-21, against the shipped
#: `domain.rates.price` and `RATE_TABLE_VERSION` 2026-09-12:
#:   page 0  claude-opus-5    2000 in, 1200 out ->  40000 micro  ($0.0400)
#:   page 1  claude-sonnet-5  2000 in, 5600 out ->  60000 micro  ($0.0600)
#:   page 2  claude-opus-5    2000 in, 1200 out ->  40000 micro  ($0.0400)
_CALLS: tuple[_Call, ...] = (
    _Call(
        request_id="msg_page0",
        model_id="claude-opus-5",
        usage=TokenUsage(
            input_tokens=2000, output_tokens=1200, cache_read_tokens=0, cache_write_tokens=0
        ),
        micro=40_000,
    ),
    _Call(
        request_id="msg_page1",
        model_id="claude-sonnet-5",
        usage=TokenUsage(
            input_tokens=2000, output_tokens=5600, cache_read_tokens=0, cache_write_tokens=0
        ),
        micro=60_000,
    ),
    _Call(
        request_id="msg_page2",
        model_id="claude-opus-5",
        usage=TokenUsage(
            input_tokens=2000, output_tokens=1200, cache_read_tokens=0, cache_write_tokens=0
        ),
        micro=40_000,
    ),
)

#: The ceiling written into the `chapter` row for the refusal fixture: $0.12.
#:
#: Chosen so the guard permits two pages and refuses the third, and MEASURED out
#: of framework on 2026-09-21 against the shipped `Budget` rather than derived
#: here (`## Handoff`):
#:
#:   page 0: 0 samples, spent      0, next 60000 (estimate) -> 60000 <= 120000  PERMIT
#:   page 1: 1 sample,  spent  40000, next 60000 (estimate) -> 100000 <= 120000 PERMIT
#:   page 2: 2 samples, spent 100000, next 50000 (observed) -> 150000 > 120000  REFUSE
#:
#: Two pages rather than one because AC-1 says *"every page already translated
#: is persisted"* and "every" over a single page is not a claim about many. The
#: crossover is on page 2 rather than page 1 because the observed mean (50,000)
#: is **below** the bootstrap estimate (60,000), so a ceiling that refused
#: earlier would refuse on the estimate and never exercise the observed basis at
#: all - and switching basis is what makes the guard bite on real spend.
_CEILING_MICRO = 120_000

#: The ordinal the run must stop before, under `_CEILING_MICRO`. Measured, above.
_REFUSED_ORDINAL = 2

#: A ceiling of $0.00 - MT-013 AC-7's "refuses everything, forever". The first
#: consultation projects the bootstrap estimate on top of nothing spent, and
#: $0.00 + $0.06 is not <= $0.00, so page 0 is refused and the ledger stays
#: empty. Measured out of framework on 2026-09-21.
_ZERO_CEILING_REFUSED_ORDINAL = 0


def _ring(x: int, y: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4), (x, y))


# -- doubles -------------------------------------------------------------------


class _Detector:
    """A `PageDetector`: page bytes in, two fixed regions out."""

    def __init__(self, mask: bytes) -> None:
        self._mask = mask
        self.calls = 0

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        self.calls += 1
        return tuple(
            RawRegion(polygon=_ring(index * 10, 0), mask=self._mask, confidence=1.0, kind="bubble")
            for index in range(_REGIONS_PER_PAGE)
        )


class _Transcriber:
    """A `PageTranscriber`: two OCR results per page, neither of them empty."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
        self.calls += 1
        return tuple(OcrResult(text=f"ja-{index}") for index in range(len(regions)))


class _Translator:
    """A `PageTranslator` that reports one `_CALLS` entry per invocation.

    **It counts its own invocations**, and that count is what makes AC-2's "the
    call was never made" a claim about the *call* rather than only about the
    ledger: an implementation that called the model and then declined to record
    the row would leave the ledger looking identical and this counter at three.
    """

    def __init__(self, calls: Sequence[_Call] = _CALLS) -> None:
        self._calls = tuple(calls)
        self.seen: list[tuple[bytes, tuple[OcrResult, ...]]] = []

    @property
    def calls(self) -> int:
        return len(self.seen)

    def __call__(self, image: bytes, results: Sequence[OcrResult]) -> TranslationResult:
        call = self._calls[len(self.seen)]
        self.seen.append((image, tuple(results)))
        return TranslationResult(
            lines={index: f"EN({result.text})" for index, result in enumerate(results)},
            usage=call.usage,
            call=CallInfo(request_id=call.request_id, model_id=call.model_id),
        )


class _RaisingStage:
    """A `Stage` that raises whatever it was handed, on the page it was told to.

    The runner's two `except` arms are one line of ordering apart (C-3), and the
    only way to tell them apart is to raise both kinds of exception through the
    real `run_chapter` and read `RunAborted.reason` back.
    """

    name = "raiser"

    def __init__(self, error: BaseException, ordinal: int) -> None:
        self._error = error
        self._ordinal = ordinal
        self.ran: list[int] = []

    def run(self, ctx: PageContext) -> None:
        self.ran.append(ctx.page.ordinal)
        if ctx.page.ordinal == self._ordinal:
            raise self._error

    def is_done(self, ctx: PageContext) -> bool:
        return False


def _never() -> bool:
    return False


# -- helpers -------------------------------------------------------------------


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Read the project file with a plain `sqlite3` connection that knows
    nothing of `mangatl.store`."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _ledger(db_path: Path) -> list[tuple[object, ...]]:
    """Every ledger row, by page **ordinal**, oldest first.

    The ordinal and not the `page_id`: the ordinal is the page's identity for
    the whole product (MT-004), and a `record_call` that stored one where the
    other belongs agrees with itself on any chapter whose first page id happens
    to be 0 (MT-012 RED-A4).
    """
    return _raw(
        db_path,
        "SELECT page.ordinal, llm_call.run_id, llm_call.request_id, llm_call.model_id,"
        " llm_call.cost_micro_usd"
        " FROM llm_call JOIN page ON page.id = llm_call.page_id"
        " ORDER BY llm_call.id",
    )


def _rows_for(db_path: Path, ordinal: int) -> int:
    return int(
        _raw(
            db_path,
            "SELECT count(*) FROM llm_call JOIN page ON page.id = llm_call.page_id"
            " WHERE page.ordinal = ?",
            (ordinal,),
        )[0][0]
    )


def _seed_page_zero(fixture: _Fixture) -> int:
    """Page 0 as the detect and OCR stages would leave it, and an open run.

    Two regions and two non-empty lines, written through the store's own
    writers: the three tests below are about `TranslateStage.run` in isolation,
    so they stand the page up rather than walking a whole chapter to reach it.
    """
    fixture.project.write_regions(0, _Detector(fixture.mask)(b""))
    fixture.project.write_lines(0, (OcrResult(text="ja-0"), OcrResult(text="ja-1")))
    return fixture.open_run()


def _set_ceiling(project: Project, micro: int | None) -> None:
    """Write the chapter's budget ceiling, the way MT-024's settings file will.

    Raw SQL through `project.transaction()`, the convention `test_project.py`
    set for a write no shipped helper performs: this story adds a *reader*
    (`Project.budget_ceiling`) and no writer, and the test must not invent one.
    """
    with project.transaction() as cursor:
        cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))


@dataclass(frozen=True)
class _Fixture:
    source_dir: Path
    project: Project
    db_path: Path
    mask: bytes

    def context(self, ordinal: int, run_id: int) -> PageContext:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return PageContext(project=self.project, page=page, run_id=run_id)

    def open_run(self) -> int:
        with self.project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-09-21T09:00:00+00:00"),
            )
            return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


@pytest.fixture
def fixture(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> Iterator[_Fixture]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _Fixture(
            source_dir=source_dir,
            project=project,
            db_path=project_dir_for(source_dir) / "project.db",
            mask=one_bit_png(8, 8, [(0, 0, 4, 4)]),
        )


@dataclass(frozen=True)
class _Run:
    """One whole run of the fixture chapter, and everything observed about it."""

    events: list[RunEvent]
    outcome: object
    translator: _Translator
    detector: _Detector
    transcriber: _Transcriber


def _run_chapter(fixture: _Fixture, *, ceiling_micro: int | None) -> _Run:
    """Walk the fixture chapter through the **real** `build_stages` list.

    The stage list is built by `build_stages`, not assembled here, so AC-4's
    "the stage list contains the translate stage" is load-bearing for every
    assertion below: a list without it proposes nothing and bills nothing, and
    these tests go red rather than passing over a pipeline that does neither.
    """
    _set_ceiling(fixture.project, ceiling_micro)
    detector = _Detector(fixture.mask)
    transcriber = _Transcriber()
    translator = _Translator()
    events: list[RunEvent] = []

    outcome = run_chapter(
        fixture.project,
        build_stages(detector, transcriber, translator),
        events.append,
        _never,
    )
    return _Run(
        events=events,
        outcome=outcome,
        translator=translator,
        detector=detector,
        transcriber=transcriber,
    )


@pytest.fixture
def refused(fixture: _Fixture) -> _Run:
    """The run AC-1 and AC-2 are about: a $0.12 ceiling, refused on page 2.

    One fixture shared by the criteria that have to be read together - AC-1's
    abort, AC-2's absent row and AC-3's present ones are three questions about
    the same run, and asking them of three different runs is what would let the
    vacuous implementation through.
    """
    return _run_chapter(fixture, ceiling_micro=_CEILING_MICRO)


# -- AC-1: the abort names the page, and the pages before it survive -----------


def test_a_refused_run_ends_with_run_aborted_reason_budget_naming_the_stopped_page(
    refused: _Run,
) -> None:
    """**AC-1**, first clause, and C-3's ordering with it.

    `== BUDGET` and never `in`: `BudgetRefused` **is** an `Exception`, so the
    runner's general arm placed before the specific one swallows it and produces

        reason="BudgetRefused: the projected next call of $0.0500 on top of ..."

    which fails this comparison and passes any substring check. `BUDGET` is
    imported from `runner` rather than spelled `"budget"` here, because AC-1
    asserts the value and a test should not re-spell a constant the module
    exports - but the literal is pinned once, below, so the constant cannot be
    quietly redefined.
    """
    aborted = [event for event in refused.events if isinstance(event, RunAborted)]

    assert len(aborted) == 1, f"the run emitted {len(aborted)} RunAborted events, not one"
    assert aborted[0].reason == BUDGET
    assert aborted[0].ordinal == _REFUSED_ORDINAL, (
        f"the run reported stopping before page {aborted[0].ordinal}; the guard"
        f" refuses page {_REFUSED_ORDINAL} under a ${_CEILING_MICRO / 1e6:.2f} ceiling"
    )
    assert not [event for event in refused.events if isinstance(event, RunFinished)]
    assert refused.outcome.outcome == RUN_ABORTED
    assert refused.outcome.aborted_reason == BUDGET


def test_the_reason_string_a_budget_refusal_reports_is_exactly_budget() -> None:
    """C-3's constant, pinned as a literal exactly once in this suite.

    Everything else imports `BUDGET`. If this line and that constant ever
    disagree, this is the test that says so, rather than every assertion above
    silently agreeing with a renamed value.
    """
    import mangatl.pipeline.runner as module

    assert BUDGET == "budget"
    assert "BUDGET" in module.__all__, (
        "`BUDGET` is not exported from mangatl.pipeline.runner; AC-1 asserts the"
        " value and a test should not have to re-spell it (C-3)"
    )


def test_every_page_translated_before_the_refusal_keeps_its_lines_intact(
    fixture: _Fixture, refused: _Run
) -> None:
    """**AC-1**, second clause: *"every page already translated is persisted
    with its lines intact"*.

    This is the clause that makes a budget abort survivable rather than a lost
    chapter. Each earlier page committed its own writes in its own transaction
    (`Project.transaction()` is not reentrant, MT-005 PO-5), so an abort on page
    2 cannot roll back page 0 or page 1.

    Read with a plain `sqlite3` connection: an observer that shares the store's
    assumptions cannot tell a persisted row from a cached one.
    """
    stored = _raw(
        fixture.db_path,
        "SELECT page.ordinal, region.reading_index, line.source_ja, line.proposed_en"
        " FROM line JOIN region ON region.id = line.region_id"
        " JOIN page ON page.id = region.page_id"
        " ORDER BY page.ordinal, region.reading_index",
    )

    assert stored == [
        (0, 0, "ja-0", "EN(ja-0)"),
        (0, 1, "ja-1", "EN(ja-1)"),
        (1, 0, "ja-0", "EN(ja-0)"),
        (1, 1, "ja-1", "EN(ja-1)"),
        # Page 2 ran detect and OCR - the guard is inside the *translate* stage,
        # so the two stages before it did their work and committed it - and then
        # the run stopped before the call. Its lines exist with NULL proposals.
        (2, 0, "ja-0", None),
        (2, 1, "ja-1", None),
    ]
    assert fixture.project.read_proposed(0) == ("EN(ja-0)", "EN(ja-1)")
    assert fixture.project.read_proposed(1) == ("EN(ja-0)", "EN(ja-1)")
    assert fixture.project.read_proposed(_REFUSED_ORDINAL) == (None, None)


def test_the_refused_page_is_not_marked_done_and_is_not_counted_as_done(
    fixture: _Fixture, refused: _Run
) -> None:
    """AC-1's bookkeeping, which C-3 says already works and must not be
    re-implemented: `_run_page` returns `False` *before* `progress.pages_done +=
    1`, so the refused page does not count, and `_mark_done` is never reached
    for it, so `page.status` stays what it was.

    `pages_done == 2` and not 3 is the number MT-018 shows a user, and a
    fully-translated chapter reporting the wrong one is the failure the
    runner's own docstring warns about from the other direction.
    """
    assert refused.outcome.pages_done == _REFUSED_ORDINAL
    assert fixture.project.page_status(0) == PAGE_DONE
    assert fixture.project.page_status(1) == PAGE_DONE
    assert fixture.project.page_status(_REFUSED_ORDINAL) == PAGE_PENDING
    assert _raw(fixture.db_path, "SELECT outcome, aborted_reason FROM run ORDER BY id") == [
        (RUN_ABORTED, BUDGET)
    ]


# -- AC-2 with AC-3 as its control, over one fixture ---------------------------


def test_the_refused_page_has_no_ledger_row_and_the_pages_before_it_have_one_each(
    fixture: _Fixture, refused: _Run
) -> None:
    """**AC-2 and AC-3 together**, and they are together on purpose.

    AC-2 alone is satisfiable by an implementation that records **nothing, for
    any page** - "no `llm_call` row exists for the refused page" is then true
    and means nothing. AC-3 is its positive control: *exactly one* row exists
    for each permitted page, priced from that response's own usage by
    `domain.rates.price`. So "no row here" is a claim only because "one row
    there" holds of the same run, in the same table, at the same moment.

    This asymmetry is **DV-4**. Deleting `record_call(...)` from
    `TranslateStage.run` must leave the AC-2 assertion passing and turn the AC-3
    assertions red; if both go red, the pairing has not been achieved and the
    control is not a control.

    The cost is asserted twice over: against `price(...)`, which is the oracle
    AC-3 names, and against the micro-dollar literal RED measured out of
    framework. Two models, so a stage that priced every call against a hardcoded
    model id stores 150,000 for page 1 instead of 60,000 and is caught.
    """
    # AC-2 - the refused page. The `== 0` is an exact count, not an absence
    # check: a row with a NULL cost is still a row.
    assert _rows_for(fixture.db_path, _REFUSED_ORDINAL) == 0, (
        f"page {_REFUSED_ORDINAL} was refused and still has a ledger row: the"
        " guard ran after the call rather than before it, which is the whole of"
        " D6 - a guard that notices the overrun after paying for it has not"
        " guarded anything"
    )
    # AC-2's other half, and the one the ledger cannot see: the call was never
    # *made*. An implementation that called the model and declined to record it
    # leaves the assertion above true and this one false.
    assert refused.translator.calls == _REFUSED_ORDINAL, (
        f"the translator was called {refused.translator.calls} times for"
        f" {_REFUSED_ORDINAL} permitted pages; the refused page reached the model"
    )

    # AC-3 - the permitted pages. Exactly one row each, in order, carrying the
    # run that made them and the request id the response reported.
    assert _rows_for(fixture.db_path, 0) == 1
    assert _rows_for(fixture.db_path, 1) == 1
    assert _ledger(fixture.db_path) == [
        (0, refused.outcome.run_id, "msg_page0", "claude-opus-5", 40_000),
        (1, refused.outcome.run_id, "msg_page1", "claude-sonnet-5", 60_000),
    ]
    # The same two costs, read out of MT-012's own pricing function rather than
    # re-derived here.
    assert [row[4] for row in _ledger(fixture.db_path)] == [
        price(call.model_id, call.usage).cost.micro() for call in _CALLS[:2]
    ]


def test_the_ledger_carries_the_four_token_counts_and_the_rate_table_that_priced_them(
    fixture: _Fixture, refused: _Run
) -> None:
    """**AC-3**'s "priced from the response's own usage", read column by column.

    The two cache counts are ordered **write before read** in `llm_call`, while
    `TokenUsage` orders them read before write, and a swap is a factor-of-12.5
    pricing error that nothing downstream could notice (MT-012 RED-A3). Asserted
    against `price(...)`'s `CostRecord`, which is the one place that mapping is
    settled.
    """
    stored = _raw(
        fixture.db_path,
        "SELECT input_tokens, output_tokens, cache_write_tokens, cache_read_tokens,"
        " rate_table_version FROM llm_call ORDER BY id",
    )
    expected = [
        (
            record.input_tokens,
            record.output_tokens,
            record.cache_write_tokens,
            record.cache_read_tokens,
            record.rate_table_version,
        )
        for record in (price(call.model_id, call.usage) for call in _CALLS[:2])
    ]

    assert stored == expected
    assert all(row[4] for row in stored), "a freshly priced call knows its rate table"


def test_the_chapter_total_after_a_refusal_is_what_the_permitted_pages_cost(
    fixture: _Fixture, refused: _Run
) -> None:
    """The guard's own input, closing the loop: `chapter_total` now reads
    something, which it did not before this story.

    Before MT-044 nothing in production wrote a ledger row, so `spent` was
    permanently $0 and the guard was inert however correct its arithmetic. This
    is that sentence made falsifiable.
    """
    assert chapter_total(fixture.project) == Usd.from_micro(40_000 + 60_000)
    assert chapter_total(fixture.project).micro() == 100_000


# -- the controls that make the refusal mean something -------------------------


def test_the_same_chapter_under_the_default_ceiling_finishes_and_bills_every_page(
    fixture: _Fixture,
) -> None:
    """**The negative control for every assertion above, and AC-5's second
    half.**

    Identical fixture, identical doubles, identical costs - only the ceiling
    differs, and the chapter row carries none, so the guard falls back to
    `DEFAULT_CEILING` ($2.00). The run must finish, all three pages must be
    proposed, and all three calls must be billed.

    Without this, "the run aborted on page 2" is satisfied by an implementation
    that aborts on page 2 unconditionally, and "no row for page 2" by one that
    never records anything. Measured out of framework on 2026-09-21: under the
    default ceiling every page is permitted and the chapter costs 140,000
    micro-dollars.
    """
    run = _run_chapter(fixture, ceiling_micro=None)

    assert run.outcome.outcome == RUN_FINISHED
    assert run.outcome.aborted_reason is None
    assert run.outcome.pages_done == _PAGE_COUNT
    assert [event for event in run.events if isinstance(event, RunFinished)]
    assert not [event for event in run.events if isinstance(event, RunAborted)]

    assert run.translator.calls == _PAGE_COUNT
    assert _ledger(fixture.db_path) == [
        (ordinal, run.outcome.run_id, call.request_id, call.model_id, call.micro)
        for ordinal, call in enumerate(_CALLS)
    ]
    assert chapter_total(fixture.project).micro() == 140_000
    for ordinal in range(_PAGE_COUNT):
        assert fixture.project.read_proposed(ordinal) == ("EN(ja-0)", "EN(ja-1)")
        assert fixture.project.page_status(ordinal) == PAGE_DONE


def test_a_stored_zero_ceiling_refuses_the_very_first_page_and_bills_nothing(
    fixture: _Fixture,
) -> None:
    """The **zero** of zero-one-many, and MT-013 AC-7's "refuses everything,
    forever", reached through a whole run.

    A stored $0.00 is a real ceiling and not an absent one: the first
    consultation projects `BOOTSTRAP_PAGE_ESTIMATE` on top of nothing spent, and
    $0.00 + $0.06 is not <= $0.00. So the run stops before page 0, the ledger is
    empty, and *no page* is proposed - which is the one case where "no ledger
    row for the refused page" is true of every page and the control above is the
    only thing separating it from a broken implementation.
    """
    run = _run_chapter(fixture, ceiling_micro=0)

    aborted = [event for event in run.events if isinstance(event, RunAborted)]
    assert len(aborted) == 1
    assert aborted[0].reason == BUDGET
    assert aborted[0].ordinal == _ZERO_CEILING_REFUSED_ORDINAL
    assert run.outcome.pages_done == 0
    assert run.translator.calls == 0
    assert _ledger(fixture.db_path) == []
    assert fixture.project.read_proposed(0) == (None, None)
    # Detect and OCR still ran on page 0: the guard lives in the translate
    # stage, not in the runner, so the free work happens and only the paid work
    # is refused.
    assert run.detector.calls == 1
    assert run.transcriber.calls == 1


# -- C-3: the two except arms are one line of ordering apart -------------------


def test_a_budget_refusal_and_an_ordinary_failure_report_different_reasons(
    fixture: _Fixture,
) -> None:
    """**C-3**, as the discrimination the ordering buys.

    `BudgetRefused` is an `Exception`. With the general arm first, both halves
    of this test report `"BudgetRefused: ..."` and `"ValueError: ..."` - two
    strings that differ, so a test comparing them to *each other* would pass.
    The refusal half is compared to the exact constant, which is the only form
    that fails.

    The `ValueError` half is the control in the other direction: an
    implementation that mapped **every** exception to `"budget"` would satisfy
    AC-1 and quietly report a crashed run as an affordability problem.
    """
    decision = Budget().check(Usd.from_micro(0), Budget().project((), _PAGE_COUNT))

    refusal_events: list[RunEvent] = []
    run_chapter(
        fixture.project,
        [_RaisingStage(BudgetRefused(decision), ordinal=1)],
        refusal_events.append,
        _never,
    )
    (refusal,) = [event for event in refusal_events if isinstance(event, RunAborted)]

    assert refusal.reason == BUDGET
    assert refusal.ordinal == 1

    failure_events: list[RunEvent] = []
    run_chapter(
        fixture.project,
        [_RaisingStage(ValueError("the page is upside down"), ordinal=1)],
        failure_events.append,
        _never,
    )
    (failure,) = [event for event in failure_events if isinstance(event, RunAborted)]

    assert failure.reason == "ValueError: the page is upside down"
    assert failure.reason != BUDGET
    assert failure.ordinal == 1


# -- C-2: BudgetRefused ---------------------------------------------------------


def test_budget_refused_is_an_exception_that_carries_the_decision_it_came_from() -> None:
    """**C-2**. The `Decision` travels on the exception so MT-018 can render the
    three numbers that justified the refusal - a refusal that does not say why
    is not actionable, which is `domain/budget.py`'s own rule.

    `str(exception)` is the decision's `reason`, so a traceback anyone sees
    carries the explanation rather than an empty exception name.
    """
    import mangatl.pipeline.stage as module

    budget = Budget(Usd.from_micro(_CEILING_MICRO))
    decision = budget.check(Usd.from_micro(_CEILING_MICRO), budget.project((), 1))
    assert decision.permitted is False, "the fixture decision is not a refusal"

    error = BudgetRefused(decision)

    assert isinstance(error, Exception)
    assert error.decision is decision
    assert isinstance(error.decision, Decision)
    assert str(error) == decision.reason
    assert module.__all__ == ["BudgetRefused", "PageContext", "PassThroughStage", "Stage"]


def test_the_stage_module_names_the_exception_and_not_the_translate_stage() -> None:
    """**C-2**'s placement, as a unit tripwire.

    `stage.py` and not `translate_stage.py`, because `runner.py` must catch this
    and already imports `stage.py`. A runner importing `pipeline.translate_stage`
    to name an exception would put the translate stage - and through it
    `domain.rates`, `domain.budget` and `store.ledger` - into the import graph of
    **every** run, including the zero-stage ones `tests/core/test_pipeline.py`
    uses.
    """
    import mangatl.pipeline.runner as runner

    tree = ast.parse(Path(runner.__file__ or "").read_text(encoding="utf-8"))
    imported = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ]

    assert "mangatl.pipeline.stage" in imported
    assert "mangatl.pipeline.translate_stage" not in imported, (
        "runner.py imports the translate stage to name BudgetRefused; C-2 puts"
        " the exception in stage.py precisely so that it does not have to"
    )


# -- C-1: PageContext.run_id ----------------------------------------------------


def test_the_page_context_carries_the_run_and_has_no_default_for_it(
    fixture: _Fixture,
) -> None:
    """**C-1**. Third and last, after `project` and `page`, and **no default**.

    A default of `0` would let a stage record a ledger row against a run that
    does not exist - and `llm_call.run_id` is a NOT NULL foreign key to
    `run(id)`, so a wrong value is caught only if no run happens to have that
    id, and run 1 always does. Read off the dataclass fields rather than off a
    `TypeError`, so the failure message names the field.
    """
    fields = dataclasses.fields(PageContext)

    assert [field.name for field in fields] == ["project", "page", "run_id"]
    run_id_field = next(field for field in fields if field.name == "run_id")
    assert run_id_field.default is dataclasses.MISSING, (
        "PageContext.run_id has a default, so a stage can record a ledger row"
        " against a run that does not exist (C-1)"
    )
    assert run_id_field.default_factory is dataclasses.MISSING

    run_id = fixture.open_run()
    assert fixture.context(0, run_id).run_id == run_id


def test_the_ledger_rows_a_run_writes_all_carry_that_runs_own_id(
    fixture: _Fixture, refused: _Run
) -> None:
    """C-1's reason, made observable. Two runs of one chapter are two `run`
    rows, and the ledger has to be able to say which run spent what - that is
    `run_total` against `chapter_total` (MT-012 AC-6).
    """
    run_ids = {row[1] for row in _ledger(fixture.db_path)}

    assert run_ids == {refused.outcome.run_id}
    assert _raw(fixture.db_path, "SELECT id FROM run ORDER BY id") == [(refused.outcome.run_id,)]


# -- AC-5: budget_for reads the chapter row ------------------------------------


def test_a_chapter_row_carrying_a_ceiling_builds_the_guard_with_that_ceiling(
    fixture: _Fixture,
) -> None:
    """**AC-5**, first half, asserted against `budget_for` directly.

    C-11: *"the guard is constructed with the right ceiling" is one fact and "a
    run refuses at the right point" is another*, so both are asserted - this
    one here and the other one at the top of the file.

    `!= DEFAULT_CEILING` is what makes it a claim: a `budget_for` that ignored
    the row entirely and always returned `Budget()` would satisfy an assertion
    that only compared against something.
    """
    _set_ceiling(fixture.project, _CEILING_MICRO)

    budget = budget_for(fixture.project)

    assert isinstance(budget, Budget)
    assert budget.ceiling == Usd.from_micro(_CEILING_MICRO)
    assert budget.ceiling != DEFAULT_CEILING


def test_a_chapter_row_with_no_ceiling_builds_the_guard_with_the_default(
    fixture: _Fixture,
) -> None:
    """**AC-5**, second half. `create_project` writes the column NULL (MT-005
    PO-8) - it has no business inventing a ceiling - so every project a user has
    today takes this branch.

    `DEFAULT_CEILING` is **imported**, not re-spelled as `$2.00`: it is MT-013's
    constant, `tests/core/test_budget.py` already pins its value, and a second
    literal here would be a second place to keep in step.
    """
    assert fixture.project.budget_ceiling() is None, "create_project invented a ceiling"

    assert budget_for(fixture.project).ceiling == DEFAULT_CEILING


def test_a_stored_ceiling_of_zero_is_a_ceiling_and_not_an_absent_one(
    fixture: _Fixture,
) -> None:
    """AC-5's boundary, and C-11's `if ceiling is None` spelling.

    `Usd` is a dataclass with no `__bool__`, so `Usd(Decimal("0.00"))` is truthy
    and `ceiling or Budget()` happens to work **today** - the two spellings are
    one word apart in a diff and this test cannot separate them on its own. What
    it does pin is the behaviour that would change the day someone gives `Usd` a
    `__bool__` or a `__len__`: a stored $0.00 ceiling is MT-013 AC-7's "refuses
    everything, forever", and silently becoming $2.00 would spend real money on
    a chapter the user had switched off.
    """
    _set_ceiling(fixture.project, 0)

    budget = budget_for(fixture.project)

    assert budget.ceiling == Usd.from_micro(0)
    assert budget.ceiling != DEFAULT_CEILING
    assert budget.check(Usd.from_micro(0), budget.project((), 1)).permitted is False


# -- C-8: pages_remaining -------------------------------------------------------


def test_pages_remaining_counts_this_page_and_every_page_after_it(
    fixture: _Fixture,
) -> None:
    """**C-8**. Ordinals are contiguous from 0 (MT-004), so this is exact: on the
    first page of a three-page chapter it is 3, on the last it is 1, and it is
    never 0.

    It feeds `Projection.remaining_chapter` only - `Budget.check` never reads
    that field - so an off-by-one changes a number MT-018 displays and changes
    no permit or refusal. Pinned anyway, because "it does not affect the
    decision" is a reason to get it right once rather than to leave it to GREEN.
    """
    run_id = fixture.open_run()

    remaining = [
        pages_remaining(fixture.context(ordinal, run_id)) for ordinal in range(_PAGE_COUNT)
    ]

    assert remaining == [3, 2, 1]
    assert 0 not in remaining


# -- C-9: chapter_call_costs ----------------------------------------------------


def test_chapter_call_costs_is_empty_before_any_call_is_priced(fixture: _Fixture) -> None:
    """The **zero** of C-9, and the case that puts the projection on its
    bootstrap basis: fewer than `MIN_SAMPLES_FOR_PROJECTION` priced calls project
    from `BOOTSTRAP_PAGE_ESTIMATE` and say so.

    Both constants are imported from MT-013 rather than re-spelled - the values
    are already pinned in `tests/core/test_budget.py`.
    """
    costs = chapter_call_costs(fixture.project)

    assert costs == ()
    assert len(costs) < MIN_SAMPLES_FOR_PROJECTION
    assert Budget().project(costs, _PAGE_COUNT).basis == "estimate"
    assert Budget().project(costs, _PAGE_COUNT).next_call == BOOTSTRAP_PAGE_ESTIMATE


def test_chapter_call_costs_returns_every_priced_call_oldest_first(
    fixture: _Fixture, refused: _Run
) -> None:
    """**C-9**, over the refused run: the guard's samples are the calls the
    chapter actually made, in the order it made them.

    `ORDER BY id` and not unordered: `Budget.project` takes a mean and is
    order-insensitive *today*, and a SELECT without an ORDER BY is
    nondeterministic by contract even when it happens to come back sorted
    (`_SELECT_PAGES`' reason, inherited). The two costs are deliberately
    **different**, so the order is something the assertion can be wrong about.
    """
    costs = chapter_call_costs(fixture.project)

    assert costs == (Usd.from_micro(40_000), Usd.from_micro(60_000))
    assert costs != (Usd.from_micro(60_000), Usd.from_micro(40_000))
    assert len(costs) >= MIN_SAMPLES_FOR_PROJECTION
    # And the projection they produce is the observed one, which is what turned
    # page 2 from permitted into refused: 50,000 micro-dollars, the mean.
    projection = Budget(Usd.from_micro(_CEILING_MICRO)).project(costs, 1)
    assert projection.basis == "observed"
    assert projection.next_call == Usd.from_micro(50_000)
    assert projection.sample_count == 2


def test_chapter_call_costs_spans_every_run_of_the_chapter(fixture: _Fixture) -> None:
    """**C-9**'s "no `WHERE run_id`", for `chapter_total`'s stated reason
    (MT-012 AC-6): a resume is a second `run` row against one chapter, and the
    ceiling is a question about the **chapter**.

    A per-run sample set would reset the projection's basis to `estimate` on
    every resume - which is the guard going quietly inert exactly when a user
    resumes a chapter they have already spent money on.
    """
    first = fixture.open_run()
    second = fixture.open_run()
    assert first != second

    record_call(
        fixture.project, first, 0, _CALLS[0].request_id, price(_CALLS[0].model_id, _CALLS[0].usage)
    )
    record_call(
        fixture.project, second, 1, _CALLS[1].request_id, price(_CALLS[1].model_id, _CALLS[1].usage)
    )

    costs = chapter_call_costs(fixture.project)

    assert costs == (Usd.from_micro(40_000), Usd.from_micro(60_000))
    assert len(costs) == 2, (
        "chapter_call_costs filtered by run: a resumed chapter would project from"
        " an estimate again and the guard would stop seeing what it already spent"
    )


def test_the_ledger_module_exports_the_new_reader_beside_the_old_ones() -> None:
    """C-9's `__all__`. Exact, because a reader that exists but is not exported
    is a reader the next story writes a second copy of."""
    import mangatl.store.ledger as module

    assert module.__all__ == ["chapter_call_costs", "chapter_total", "record_call", "run_total"]


# -- C-7: the stage's own ordering ---------------------------------------------


def test_the_stage_records_the_bill_before_it_writes_the_proposals(
    fixture: _Fixture,
) -> None:
    """**C-7 clause 2**, as the outcome of the crash it protects against.

    `record_call` and `write_proposed` each open their own transaction
    (`Project.transaction()` is not reentrant, MT-005 PO-5), so they are two
    commits with a window between them and a crash in that window resolves
    differently depending on the order:

    * **proposals first** loses the *bill*. The page reads `is_done` on the next
      run, is never re-translated, and the spend is missing from `chapter_total`
      **for the life of the chapter** - the guard goes quietly inert, which is
      the exact failure this story exists to end.
    * **ledger first** loses the *proposals*. The page is re-translated and
      billed twice, and both bills are in the ledger.

    Over-reporting spend is recoverable; under-reporting it is not. Asserted by
    crashing the write: `write_proposed` raises `ValueError` for a reading index
    the page does not have (MT-011 C-6's RED amendment), **with nothing
    written** - so the ledger row can only still be there if it was committed
    first.
    """
    run_id = _seed_page_zero(fixture)

    class _NamesAMissingRegion:
        """A translator whose result names a region index that does not exist,
        so `write_proposed` raises **after** the call has been priced."""

        def __call__(self, image: bytes, results: Sequence[OcrResult]) -> TranslationResult:
            call = _CALLS[0]
            return TranslationResult(
                lines={99: "a region that is not on this page"},
                usage=call.usage,
                call=CallInfo(request_id=call.request_id, model_id=call.model_id),
            )

    with pytest.raises(ValueError, match=r"\b99\b"):
        TranslateStage(translate=_NamesAMissingRegion()).run(fixture.context(0, run_id))

    assert _rows_for(fixture.db_path, 0) == 1, (
        "the proposals were written before the bill: a crash between the two"
        " commits loses the spend from chapter_total for the life of the"
        " chapter, and the guard goes inert (C-7 clause 2)"
    )
    assert fixture.project.read_proposed(0) == (None, None)


def test_a_result_that_reports_no_call_writes_proposals_and_no_ledger_row(
    fixture: _Fixture,
) -> None:
    """**C-7**'s `if result.call is not None` arm, and AC-7's wordless page one
    story on.

    `call is None` <=> no API call was made <=> no `llm_call` row (C-4). A page
    of wordless art is a legal result with nothing in it and it costs nothing,
    so billing it would put a row in the ledger for a call the provider never
    saw - and reconciling the ledger against the bill is what it is for.

    **Inverting the condition is DV-4's second mutation**: with
    `if result.call is None`, this test still passes and AC-3's does not.
    """
    run_id = _seed_page_zero(fixture)

    class _NoCall:
        def __call__(self, image: bytes, results: Sequence[OcrResult]) -> TranslationResult:
            return TranslationResult(
                lines={index: f"EN({result.text})" for index, result in enumerate(results)},
                usage=TokenUsage(0, 0, 0, 0),
                call=None,
            )

    TranslateStage(translate=_NoCall()).run(fixture.context(0, run_id))

    assert fixture.project.read_proposed(0) == ("EN(ja-0)", "EN(ja-1)")
    assert _rows_for(fixture.db_path, 0) == 0
    assert chapter_total(fixture.project) == Usd.from_micro(0)


def test_the_guard_refuses_before_the_translator_is_ever_called(
    fixture: _Fixture,
) -> None:
    """**DV-1**'s condition, asserted at the stage rather than through a run.

    This is AC-2 and the whole of D6: *"a guard that notices the overrun after
    paying for it has not guarded anything"* (`domain/budget.py`). Moving the
    `raise BudgetRefused(...)` to after `self.translate(...)` must turn this red
    - the translator would have been called, and an `llm_call` row would exist
    for a page the budget refused.
    """
    _set_ceiling(fixture.project, 0)
    run_id = _seed_page_zero(fixture)
    translator = _Translator()

    with pytest.raises(BudgetRefused) as excinfo:
        TranslateStage(translate=translator).run(fixture.context(0, run_id))

    assert translator.calls == 0, (
        "the translator was called for a page the guard refused: the check runs"
        " after the call, which is the one ordering D6 forbids"
    )
    assert excinfo.value.decision.permitted is False
    assert excinfo.value.decision.ceiling == Usd.from_micro(0)
    assert _rows_for(fixture.db_path, 0) == 0
    assert fixture.project.read_proposed(0) == (None, None)
