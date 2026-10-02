"""MT-063 AC-1: a priced call emits `CallPriced`, carrying the ledger's numbers.

Everything here is the **mechanical** half of the story's oracle partition and is
pinned exactly: the event's shape (`domain.events`), `PageContext.emit` being
required, *when* `TranslateStage.run` emits (one per priced page, none for a page
with no call, a refused page or an unpriceable model), *where* the event lands in
the stream (after `PageStarted(k)`, before `StageFinished(k, "translate")`), and
*which* numbers it carries - the ledger's, read **after** this call's row was
written. The panel -> readout half is `tests/ui/test_run_progress_cost.py`.

**The expected numbers are literals, worked by hand from the token counts and the
published rates**, not re-read through the functions the stage itself calls. A
test that computed its oracle with `chapter_total` and `budget.project` would
agree with any implementation that called them at the wrong moment with the
wrong page count - which is exactly what the story's deferred mutations do. The
arithmetic, once (rates from `domain/rates.py` table 2026-09-12, per million
tokens, so `tokens x rate` is micro-dollars):

    opus-5   2000 in x $5.00  + 1200 out x $25.00 = 10,000 + 30,000 = 40,000
    sonnet-5 2000 in x $2.00  + 5600 out x $10.00 =  4,000 + 56,000 = 60,000

and the projection is `Budget.project` (MT-013): fewer than two samples project
`BOOTSTRAP_PAGE_ESTIMATE` ($0.06 = 60,000); from two on, the mean rounded **up**
to the micro-dollar; `remaining_chapter = next_call x (pages after this one)`.
Each test additionally cross-checks the *last* event against the ledger read
after the run, so the literals and the store cannot drift apart unnoticed.

**RED:** `from mangatl.domain.events import CallPriced` fails, so this file fails
at import and not one assertion in it has run. The expected values are recorded
in MT-063's `## Handoff: RED -> GREEN`; confirming them against the shipped code
is GREEN's job.

**Timing.** No `pytest-timeout` in this project, so there is no budget to size.
Every test builds a three-page chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, get_args

import pytest

import mangatl.domain.events as events_module
from mangatl.domain.budget import DEFAULT_CEILING, Projection
from mangatl.domain.events import (
    CallPriced,
    PageStarted,
    RunAborted,
    RunEvent,
    RunFinished,
    StageFinished,
)
from mangatl.domain.glossary import ProposedTerm
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.rates import price
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.pipeline.runner import BUDGET, run_chapter
from mangatl.pipeline.stage import PageContext
from mangatl.pipeline.stages import build_stages
from mangatl.pipeline.translate_stage import TranslateStage, budget_for
from mangatl.store.glossary import read_entries
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.project import Project, create_project, project_dir_for

if TYPE_CHECKING:
    from mangatl.domain.glossary import PromptContext

# -- the fixture chapter -------------------------------------------------------

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)
_PAGE_COUNT = len(_SOURCE_PAGES)
_REGIONS_PER_PAGE = 2
_TRANSLATE = "translate"

_OPUS = "claude-opus-5"
_SONNET = "claude-sonnet-5"
#: Not in the rate table: `price` raises `UnknownModel` for it (MT-012 C-5).
_UNPRICED = "claude-opus-4"

_OPUS_USAGE = TokenUsage(
    input_tokens=2000, output_tokens=1200, cache_read_tokens=0, cache_write_tokens=0
)
_SONNET_USAGE = TokenUsage(
    input_tokens=2000, output_tokens=5600, cache_read_tokens=0, cache_write_tokens=0
)

#: Worked by hand in the module docstring - not read out of `price`.
_OPUS_MICRO = 40_000
_SONNET_MICRO = 60_000

#: `BOOTSTRAP_PAGE_ESTIMATE`, $0.06, as micro-dollars - MT-013's settled value,
#: spelled here so the projection literals below are arithmetic a reader can do.
_ESTIMATE_MICRO = 60_000


def _usd(micro: int) -> Usd:
    return Usd.from_micro(micro)


def _projection(next_micro: int, pages_after: int, basis: str, samples: int) -> Projection:
    """A `Projection` from hand-worked numbers: `remaining = next x pages_after`."""
    return Projection(
        next_call=_usd(next_micro),
        remaining_chapter=_usd(next_micro * pages_after),
        basis=basis,  # type: ignore[arg-type]
        sample_count=samples,
    )


def _ring(x: int, y: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4), (x, y))


# -- doubles -------------------------------------------------------------------


class _Detector:
    def __init__(self, mask: bytes) -> None:
        self._mask = mask

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        return tuple(
            RawRegion(polygon=_ring(index * 10, 0), mask=self._mask, confidence=1.0, kind="bubble")
            for index in range(_REGIONS_PER_PAGE)
        )


#: MT-065 C-1 (a): `build_stages` takes a required cleaner, second. The page's
#: own bytes are a decodable image of the page's own size, which is all
#: `Project.write_cleaned` checks; nothing in this file is about cleaning.
def _cleaner(image_bytes: bytes, regions: Sequence[RawRegion]) -> bytes:
    return image_bytes


def _transcriber(image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
    return tuple(OcrResult(text=f"ja-{index}") for index in range(len(regions)))


@dataclass(frozen=True)
class _Reply:
    """One page's fake response. `model_id is None` means no API call was made."""

    model_id: str | None
    usage: TokenUsage
    terms: tuple[ProposedTerm, ...] = ()


_PRICED_OPUS = _Reply(_OPUS, _OPUS_USAGE)
_PRICED_SONNET = _Reply(_SONNET, _SONNET_USAGE)
_NO_CALL = _Reply(None, TokenUsage(0, 0, 0, 0))

#: The default script: opus, sonnet, opus - two models so "the call's own cost"
#: and "the mean" are different numbers on every page.
_SCRIPT: tuple[_Reply, ...] = (_PRICED_OPUS, _PRICED_SONNET, _PRICED_OPUS)


class _Translator:
    """A `PageTranslator` answering page by page from a script."""

    def __init__(self, script: Sequence[_Reply] = _SCRIPT) -> None:
        self._script = tuple(script)
        self.calls = 0

    def __call__(
        self, image: bytes, results: Sequence[OcrResult], context: PromptContext
    ) -> TranslationResult:
        reply = self._script[self.calls]
        self.calls += 1
        return TranslationResult(
            lines={index: f"EN({result.text})" for index, result in enumerate(results)},
            usage=reply.usage,
            call=(
                None
                if reply.model_id is None
                else CallInfo(request_id=f"msg_{self.calls}", model_id=reply.model_id)
            ),
            proposed_terms=reply.terms,
        )


def _never() -> bool:
    return False


# -- fixture -------------------------------------------------------------------


@dataclass(frozen=True)
class _Fixture:
    project: Project
    db_path: Path
    mask: bytes

    def open_run(self) -> int:
        with self.project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-10-01T09:00:00+00:00"),
            )
            return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])

    def set_ceiling(self, micro: int | None) -> None:
        """Raw SQL, as `test_budget_run.py` does: no shipped writer exists."""
        with self.project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))

    def run(self, script: Sequence[_Reply] = _SCRIPT) -> list[RunEvent]:
        """One whole run through the **real** `build_stages` list."""
        events: list[RunEvent] = []
        run_chapter(
            self.project,
            build_stages(_Detector(self.mask), _cleaner, _transcriber, _Translator(script)),
            events.append,
            _never,
        )
        return events


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
            project=project,
            db_path=project_dir_for(source_dir) / "project.db",
            mask=one_bit_png(8, 8, [(0, 0, 4, 4)]),
        )


def _priced(events: Sequence[RunEvent]) -> list[CallPriced]:
    return [event for event in events if isinstance(event, CallPriced)]


def _ledger_micro(db_path: Path) -> list[int]:
    """Every ledger cost, oldest first, through a connection that knows nothing
    of `mangatl.store`."""
    connection = sqlite3.connect(db_path)
    try:
        return [int(row[0]) for row in connection.execute("SELECT cost_micro_usd FROM llm_call")]
    finally:
        connection.close()


# =============================================================================
# The event's shape: `domain.events.CallPriced` (contract block 1)
# =============================================================================


def test_call_priced_carries_exactly_ordinal_spent_ceiling_and_projection_in_that_order() -> None:
    names = [field.name for field in dataclasses.fields(CallPriced)]

    assert names == ["ordinal", "spent", "ceiling", "projection"]


def test_call_priced_has_no_default_on_any_field() -> None:
    """`domain/events.py` stays data (PO-4): no default, so no event can be built
    that silently claims $0 spent."""
    for field in dataclasses.fields(CallPriced):
        assert field.default is dataclasses.MISSING, f"CallPriced.{field.name} has a default"
        assert field.default_factory is dataclasses.MISSING, (
            f"CallPriced.{field.name} has a default factory"
        )


def test_call_priced_has_no_post_init_and_no_methods_of_its_own() -> None:
    """PO-4: `domain` sits under `coverage-core`'s 100% bar, so a validation
    branch no test reaches fails a required gate. Data and nothing else."""
    own = {
        name
        for name, value in vars(CallPriced).items()
        if callable(value) and not name.startswith("__")
    }

    assert own == set()
    assert "__post_init__" not in vars(CallPriced)


def test_a_call_priced_event_cannot_be_mutated_after_it_is_emitted() -> None:
    event = CallPriced(
        ordinal=0,
        spent=_usd(_OPUS_MICRO),
        ceiling=DEFAULT_CEILING,
        projection=_projection(_ESTIMATE_MICRO, 2, "estimate", 1),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.spent = _usd(0)  # type: ignore[misc]


def test_call_priced_is_a_run_event_and_is_exported() -> None:
    assert CallPriced in get_args(RunEvent), "CallPriced is not in the RunEvent union"
    assert "CallPriced" in events_module.__all__, "CallPriced is not in domain.events.__all__"


# =============================================================================
# `PageContext.emit`: required, no default (contract block 2)
# =============================================================================


def test_a_page_context_cannot_be_built_without_an_emit(fixture: _Fixture) -> None:
    """A default no-op `emit` would let a stage built or tested without one stay
    silent, and the readout would read `$-` through a whole paid run with every
    test green (MT-044 C-1's reasoning for `run_id`)."""
    page = fixture.project.pages()[0]

    with pytest.raises(TypeError, match="emit"):
        PageContext(project=fixture.project, page=page, run_id=fixture.open_run())  # type: ignore[call-arg]


def test_the_page_context_emit_field_comes_after_run_id_and_has_no_default() -> None:
    fields = dataclasses.fields(PageContext)

    assert [field.name for field in fields] == ["project", "page", "run_id", "emit"]
    emit = fields[-1]
    assert emit.default is dataclasses.MISSING, "PageContext.emit has a default"
    assert emit.default_factory is dataclasses.MISSING, "PageContext.emit has a default factory"


def test_the_runner_hands_every_stage_its_own_emit(fixture: _Fixture) -> None:
    """Contract block 3: `run_chapter` passes its own `emit` into every
    `PageContext`. Pinned with a stage that emits a marker of its own through
    `ctx.emit`, independently of the translate stage: the marker must land in the
    run's one stream, for every page, between that page's `PageStarted` and its
    `StageFinished`."""

    class _Marker:
        name = "marker"

        def run(self, ctx: PageContext) -> None:
            ctx.emit(
                CallPriced(
                    ordinal=ctx.page.ordinal,
                    spent=_usd(ctx.page.ordinal),
                    ceiling=DEFAULT_CEILING,
                    projection=_projection(0, 0, "estimate", 0),
                )
            )

        def is_done(self, ctx: PageContext) -> bool:
            return False

    events: list[RunEvent] = []
    run_chapter(fixture.project, [_Marker()], events.append, _never)

    shape = [
        (type(event).__name__, getattr(event, "ordinal", None))
        for event in events
        if isinstance(event, PageStarted | CallPriced | StageFinished)
    ]
    assert shape == [
        (kind, ordinal)
        for ordinal in range(_PAGE_COUNT)
        for kind in ("PageStarted", "CallPriced", "StageFinished")
    ], "a stage's ctx.emit does not reach the run's own stream, page by page"


# =============================================================================
# When it is emitted, and where it lands (contract block 4, "When.")
# =============================================================================


def test_each_priced_page_emits_one_call_priced_after_its_start_and_before_translate_finishes(
    fixture: _Fixture,
) -> None:
    """AC-1's "when the call is recorded, then an event ... is emitted", as the
    stream a real run produces. Per page k the order is exactly PageStarted(k),
    detect, clean, ocr, CallPriced(k), translate - `clean` since MT-065 C-6,
    which puts it after detect and before OCR (PO-3)."""
    events = fixture.run()

    per_page = [
        (type(event).__name__, event.ordinal, getattr(event, "stage", None))
        for event in events
        if isinstance(event, PageStarted | StageFinished | CallPriced)
    ]
    assert per_page == [
        row
        for k in range(_PAGE_COUNT)
        for row in (
            ("PageStarted", k, None),
            ("StageFinished", k, "detect"),
            ("StageFinished", k, "clean"),
            ("StageFinished", k, "ocr"),
            ("CallPriced", k, None),
            ("StageFinished", k, _TRANSLATE),
        )
    ]
    assert isinstance(events[-1], RunFinished)


def test_the_numbers_on_each_event_are_the_ledgers_after_that_calls_row_was_written(
    fixture: _Fixture,
) -> None:
    """The heart of AC-1, with the default ceiling (the chapter row's is NULL).

    Hand-worked (module docstring): costs 40,000 / 60,000 / 40,000.

    | page | spent   | samples | basis    | next   | pages after | remaining |
    |------|---------|---------|----------|--------|-------------|-----------|
    | 0    |  40,000 | 1       | estimate | 60,000 | 2           | 120,000   |
    | 1    | 100,000 | 2       | observed | 50,000 | 1           |  50,000   |
    | 2    | 140,000 | 3       | observed | 46,667 | 0           |       0   |

    46,667 is 140,000 / 3 rounded **up**. Emitting before `record_call` would
    carry 0 / 40,000 / 100,000 and one sample fewer; counting this page among
    those remaining would carry 180,000 / 100,000 / 46,667 remaining.
    """
    assert fixture.project.budget_ceiling() is None

    priced = _priced(fixture.run())

    assert priced == [
        CallPriced(
            ordinal=0,
            spent=_usd(40_000),
            ceiling=DEFAULT_CEILING,
            projection=_projection(_ESTIMATE_MICRO, 2, "estimate", 1),
        ),
        CallPriced(
            ordinal=1,
            spent=_usd(100_000),
            ceiling=DEFAULT_CEILING,
            projection=_projection(50_000, 1, "observed", 2),
        ),
        CallPriced(
            ordinal=2,
            spent=_usd(140_000),
            ceiling=DEFAULT_CEILING,
            projection=_projection(46_667, 0, "observed", 3),
        ),
    ]


def test_on_the_last_page_nothing_remains_so_the_projected_total_is_the_spend(
    fixture: _Fixture,
) -> None:
    """The contract's "on the last page `remaining_chapter` is $0" - the readout's
    projected total then equals `spent`."""
    last = _priced(fixture.run())[-1]

    assert last.ordinal == _PAGE_COUNT - 1
    assert last.projection.remaining_chapter == _usd(0), (
        "the last page's projection still counts a page after it: pages_remaining(ctx)"
        " includes this page, and the projection is for the pages AFTER it"
    )
    assert last.spent + last.projection.remaining_chapter == last.spent


def test_the_last_event_agrees_with_the_ledger_read_after_the_run(fixture: _Fixture) -> None:
    """The cross-check: the hand-worked literals above and the store must agree.
    Read through `chapter_total` / `chapter_call_costs` / `budget_for` **and** a
    plain `sqlite3` connection."""
    last = _priced(fixture.run())[-1]

    assert _ledger_micro(fixture.db_path) == [_OPUS_MICRO, _SONNET_MICRO, _OPUS_MICRO]
    assert [
        price(m, u).cost.micro() for m, u in ((_OPUS, _OPUS_USAGE), (_SONNET, _SONNET_USAGE))
    ] == [
        _OPUS_MICRO,
        _SONNET_MICRO,
    ], "the rate table changed under this file's hand-worked literals"
    assert last.spent == chapter_total(fixture.project) == _usd(sum(_ledger_micro(fixture.db_path)))
    assert last.ceiling == budget_for(fixture.project).ceiling
    assert last.projection == budget_for(fixture.project).project(
        chapter_call_costs(fixture.project), 0
    )


def test_spent_includes_what_an_earlier_run_of_the_chapter_already_spent(
    fixture: _Fixture,
) -> None:
    """`spent` is `chapter_total` - every run of the chapter - and the samples
    span every run too (MT-012 AC-6, MT-044 C-9). One sonnet call (60,000) is
    already in the ledger from an earlier run when this run starts.

    | page | spent   | samples | next                       | after | remaining |
    |------|---------|---------|----------------------------|-------|-----------|
    | 0    | 100,000 | 2       | 50,000                     | 2     | 100,000   |
    | 1    | 160,000 | 3       | 53,334 (160,000/3, up)     | 1     |  53,334   |
    | 2    | 200,000 | 4       | 50,000                     | 0     |       0   |

    A per-run `spent` would read 40,000 / 100,000 / 140,000 here.
    """
    earlier = fixture.open_run()
    record_call(fixture.project, earlier, 0, "msg_earlier", price(_SONNET, _SONNET_USAGE))

    priced = _priced(fixture.run())

    assert priced == [
        CallPriced(
            ordinal=0,
            spent=_usd(100_000),
            ceiling=DEFAULT_CEILING,
            projection=_projection(50_000, 2, "observed", 2),
        ),
        CallPriced(
            ordinal=1,
            spent=_usd(160_000),
            ceiling=DEFAULT_CEILING,
            projection=_projection(53_334, 1, "observed", 3),
        ),
        CallPriced(
            ordinal=2,
            spent=_usd(200_000),
            ceiling=DEFAULT_CEILING,
            projection=_projection(50_000, 0, "observed", 4),
        ),
    ]


def test_the_ceiling_on_the_event_is_the_chapters_stored_ceiling(fixture: _Fixture) -> None:
    """`budget_for(project).ceiling`: the stored value when there is one. $1.50
    is high enough to permit all three pages (worst check: 100,000 + 50,000 on
    page 2) and is not `DEFAULT_CEILING`, so this is a claim."""
    fixture.set_ceiling(1_500_000)

    priced = _priced(fixture.run())

    assert len(priced) == _PAGE_COUNT
    assert {event.ceiling for event in priced} == {_usd(1_500_000)}
    assert _usd(1_500_000) != DEFAULT_CEILING


# =============================================================================
# When it is NOT emitted - each with a priced page in the same run as control
# =============================================================================


def test_a_page_whose_result_reports_no_call_emits_no_call_priced(fixture: _Fixture) -> None:
    """MT-011 AC-7's wordless page: `call is None`, no `record_call`, no event.
    Pages 0 and 2 are priced in the same run, so "none" is not "never".

    Page 2: spent 80,000, two samples of 40,000 -> next 40,000, nothing after.
    """
    priced = _priced(fixture.run((_PRICED_OPUS, _NO_CALL, _PRICED_OPUS)))

    assert [event.ordinal for event in priced] == [0, 2], (
        "a page with no API call emitted CallPriced, or a priced page did not"
    )
    assert priced[-1] == CallPriced(
        ordinal=2,
        spent=_usd(80_000),
        ceiling=DEFAULT_CEILING,
        projection=_projection(40_000, 0, "observed", 2),
    )


def test_a_page_the_budget_refuses_emits_no_call_priced(fixture: _Fixture) -> None:
    """A refused page makes no call and records nothing, so emits nothing. Under
    a stored $0.12 ceiling MT-044 measured the refusal on page 2 (100,000 spent
    + 50,000 observed > 120,000); pages 0 and 1 are priced and are the control,
    and carry the stored ceiling."""
    fixture.set_ceiling(120_000)

    events = fixture.run()
    priced = _priced(events)
    (aborted,) = [event for event in events if isinstance(event, RunAborted)]

    assert aborted.reason == BUDGET
    assert aborted.ordinal == 2
    assert priced == [
        CallPriced(
            ordinal=0,
            spent=_usd(40_000),
            ceiling=_usd(120_000),
            projection=_projection(_ESTIMATE_MICRO, 2, "estimate", 1),
        ),
        CallPriced(
            ordinal=1,
            spent=_usd(100_000),
            ceiling=_usd(120_000),
            projection=_projection(50_000, 1, "observed", 2),
        ),
    ]


def test_an_unpriceable_model_emits_no_call_priced(fixture: _Fixture) -> None:
    """`price` raises `UnknownModel` inside `record_call`'s argument list, so
    `record_call` never ran and there is nothing to report (MT-044 C-7 clause 3).
    Page 0 is priced first in the same run as the control."""
    events = fixture.run((_PRICED_OPUS, _Reply(_UNPRICED, _OPUS_USAGE), _PRICED_OPUS))
    (aborted,) = [event for event in events if isinstance(event, RunAborted)]

    assert aborted.ordinal == 1
    assert aborted.reason.startswith("UnknownModel"), aborted.reason
    assert [event.ordinal for event in _priced(events)] == [0], (
        "an unpriceable call emitted CallPriced, though no ledger row was written"
    )
    assert _ledger_micro(fixture.db_path) == [_OPUS_MICRO]


# =============================================================================
# The stage on its own: through ctx.emit, before the glossary and proposals
# =============================================================================


def test_the_stage_emits_through_its_context_after_the_bill_and_before_the_proposals(
    fixture: _Fixture,
) -> None:
    """`TranslateStage.run` called directly, with a recording `emit` that looks
    at the store **at the moment it is called**: the ledger row is already there,
    and neither the glossary term nor the proposals are yet ("immediately after
    `record_call` and before the glossary and proposal writes"). After `run`
    returns, both are there - the control that the snapshot could see them."""
    fixture.project.write_regions(0, _Detector(fixture.mask)(b""))
    fixture.project.write_lines(0, (OcrResult(text="ja-0"), OcrResult(text="ja-1")))
    run_id = fixture.open_run()
    term = ProposedTerm("さくら", "Sakura", "name")
    seen: list[tuple[RunEvent, list[int], tuple[str | None, ...], int]] = []

    def emit(event: RunEvent) -> None:
        seen.append(
            (
                event,
                _ledger_micro(fixture.db_path),
                fixture.project.read_proposed(0),
                len(read_entries(fixture.project)),
            )
        )

    page = fixture.project.pages()[0]
    stage = TranslateStage(translate=_Translator((_Reply(_OPUS, _OPUS_USAGE, (term,)),)))
    stage.run(PageContext(project=fixture.project, page=page, run_id=run_id, emit=emit))

    assert len(seen) == 1, f"the stage emitted {len(seen)} events for one priced call"
    event, ledger_then, proposed_then, glossary_then = seen[0]
    assert event == CallPriced(
        ordinal=0,
        spent=_usd(_OPUS_MICRO),
        ceiling=DEFAULT_CEILING,
        projection=_projection(_ESTIMATE_MICRO, 2, "estimate", 1),
    )
    assert ledger_then == [_OPUS_MICRO], "CallPriced was emitted before record_call"
    assert proposed_then == (None, None), "CallPriced was emitted after write_proposed"
    assert glossary_then == 0, "CallPriced was emitted after the glossary write"
    # The control: the snapshot could have seen them.
    assert fixture.project.read_proposed(0) == ("EN(ja-0)", "EN(ja-1)")
    assert len(read_entries(fixture.project)) == 1


def test_the_stage_emits_nothing_for_a_result_with_no_call(fixture: _Fixture) -> None:
    fixture.project.write_regions(0, _Detector(fixture.mask)(b""))
    fixture.project.write_lines(0, (OcrResult(text="ja-0"), OcrResult(text="ja-1")))
    seen: list[RunEvent] = []
    page = fixture.project.pages()[0]

    TranslateStage(translate=_Translator((_NO_CALL,))).run(
        PageContext(project=fixture.project, page=page, run_id=fixture.open_run(), emit=seen.append)
    )

    assert seen == []
    assert fixture.project.read_proposed(0) == ("EN(ja-0)", "EN(ja-1)"), "the stage did not run"
