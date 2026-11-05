"""`run_chapter`'s two passes and the chapter step between them (MT-130, MT-105).

**MT-130** splits the run: the reading stages (`stages`) run for every page
first, then the chapter step (`prelude`), then the translating stages
(`after_prelude`) page by page - so the glossary pre-pass always sees every
page's Japanese (EPIC-09 PO-2). **MT-105**'s "the prelude runs before the first
page" is superseded (MT-130 PO-5): every MT-105 test below that pinned that
order is rewritten to "after the reading pass, before the translating pass".

The fakes are the criteria's: recording stages that append `(name, ordinal)`
to one shared log, a writing detect fake that stores one region per page, a
writing OCR fake that stores one distinct line per page through
`project.write_lines`, a translate fake that stores a proposal through
`project.write_proposed`, and a chapter step that appends `"prelude"`. AC-1,
AC-4, AC-7, AC-8 and AC-9 bind the **real** `glossary_prelude` around a
recording proposer, so "the proposer is called once with every page's lines"
is observed through the step that ships.

**Oracle partition (MT-130 C-8):** every criterion is mechanical and pinned
exactly - the stream by `==` on a projection that keeps every field but
`elapsed_ms` and the run id, never a "contains". The prelude's own behaviour
is MT-105's and is not re-tested here beyond what AC-1/AC-8 need.

**Contract names are imported inside the tests** (`PassStarted`, `READING`,
`TRANSLATING`), so that while they do not exist each test fails on its own and
the one-pass guards (AC-5) still run. A two-pass call is a `TypeError` in RED:
`run_chapter` has no `after_prelude` keyword. The `type: ignore[call-arg]`
comments go with it; mypy does not read `tests/`.

**Timing.** No `pytest-timeout` in this project, so there is no budget to size.
Every test builds a two- or three-page chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import dataclasses
import inspect
import sqlite3
import typing
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from mangatl.domain.budget import Budget, Projection
from mangatl.domain.events import (
    CallPriced,
    PageSkipped,
    PageStarted,
    RunAborted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, GlossaryProposal, TokenUsage
from mangatl.pipeline.prelude import glossary_prelude
from mangatl.pipeline.runner import BUDGET, RUN_ABORTED, RUN_FINISHED, RunOutcome, run_chapter
from mangatl.pipeline.stage import BudgetRefused, PageContext
from mangatl.store.intake import read_chapter
from mangatl.store.project import PAGE_DONE, PAGE_PENDING, Project, create_project, project_dir_for
from mangatl.translate.glossary_pass import GLOSSARY_PASS_MAX_OUTPUT_TOKENS, glossary_pass_text

_THREE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)
_TWO_PAGES = _THREE_PAGES[:2]

_GEMINI = "gemini-3.1-pro-preview"
_CANCELLED = "cancelled"
_ALREADY_DONE = "already done"

#: What the emitting recording step emits, so its place in the stream is observable.
_STEP_EVENT = CallPriced(
    ordinal=None,
    spent=Usd(Decimal("0.10")),
    ceiling=Usd(Decimal("2.00")),
    projection=Projection(
        next_call=Usd(Decimal("0.03")),
        remaining_chapter=Usd(Decimal("0.09")),
        basis="estimate",
        sample_count=0,
    ),
)


def _never() -> bool:
    return False


def _line_for(ordinal: int) -> OcrResult:
    """The one distinct line the OCR fake writes for a page (AC-1)."""
    return OcrResult(f"ページ{ordinal}のせりふ")


def _english_for(ordinal: int) -> str:
    return f"EN page {ordinal}"


# -- doubles -------------------------------------------------------------------


@dataclass
class _Flag:
    """The run's cancel flag: `cancelled` reads it, a fake sets it."""

    value: bool = False

    def __call__(self) -> bool:
        return self.value


@dataclass
class _Detect:
    """A reading stage: stores one region per page. Done when the page has regions."""

    log: list[object]
    mask: bytes
    name: str = "detect"

    def run(self, ctx: PageContext) -> None:
        self.log.append((self.name, ctx.page.ordinal))
        ctx.project.write_regions(ctx.page.ordinal, [_region(self.mask)])

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.read_regions(ctx.page.ordinal) != ()


@dataclass
class _Ocr:
    """The writing OCR fake: one distinct line per page through `write_lines`.
    Sets `flag` after writing page `cancel_on`'s line - AC-8's "first returns
    `True` after the last reading stage of the last page has run"."""

    log: list[object]
    flag: _Flag | None = None
    cancel_on: int | None = None
    name: str = "ocr"

    def run(self, ctx: PageContext) -> None:
        self.log.append((self.name, ctx.page.ordinal))
        ctx.project.write_lines(ctx.page.ordinal, [_line_for(ctx.page.ordinal)])
        if self.flag is not None and ctx.page.ordinal == self.cancel_on:
            self.flag.value = True

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.read_lines(ctx.page.ordinal) != ()


@dataclass
class _Translate:
    """The translating stage: stores a proposal; done when the page is done.
    Raises `raises` on page `raise_on` (AC-11)."""

    log: list[object]
    raises: Exception | None = None
    raise_on: int | None = None
    name: str = "translate"

    def run(self, ctx: PageContext) -> None:
        self.log.append((self.name, ctx.page.ordinal))
        if self.raises is not None and ctx.page.ordinal == self.raise_on:
            raise self.raises
        ctx.project.write_proposed(ctx.page.ordinal, {0: _english_for(ctx.page.ordinal)})

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


@dataclass
class _Step:
    """A `ChapterStep`: `(project, run_id, emit) -> None`, recorded. Emits
    `_STEP_EVENT` when `emits`; sets `flag` while it runs when given one."""

    log: list[object]
    raises: Exception | None = None
    emits: bool = True
    flag: _Flag | None = None
    calls: list[tuple[Project, int, Callable[[RunEvent], None]]] = field(default_factory=list)
    statuses: list[list[str]] = field(default_factory=list)

    def __call__(self, project: Project, run_id: int, emit: Callable[[RunEvent], None]) -> None:
        self.calls.append((project, run_id, emit))
        self.statuses.append([project.page_status(page.ordinal) for page in project.pages()])
        self.log.append("prelude")
        if self.flag is not None:
            self.flag.value = True
        if self.raises is not None:
            raise self.raises
        if self.emits:
            emit(_STEP_EVENT)


class _Proposer:
    """Stands where `partial(gemini.propose_glossary, client)` stands. Appends
    `"prelude"` to the shared log (AC-2), records the pages it was handed and
    every page's status at that moment (AC-7), and sets `flag` when given one
    (AC-9: the cancel arrives while the prelude runs)."""

    def __init__(self, world: _World, *, flag: _Flag | None = None) -> None:
        self.world = world
        self.flag = flag
        self.received: list[list[tuple[OcrResult, ...]]] = []
        self.statuses: list[list[str]] = []

    def __call__(self, pages: Sequence[Sequence[OcrResult]]) -> GlossaryProposal:
        self.received.append([tuple(page) for page in pages])
        project = self.world.project
        self.statuses.append([project.page_status(page.ordinal) for page in project.pages()])
        self.world.log.append("prelude")
        if self.flag is not None:
            self.flag.value = True
        return GlossaryProposal(
            terms=(),
            usage=TokenUsage(1_000, 100, 0, 0),
            call=CallInfo(request_id="req-glossary-1", model_id=_GEMINI),
        )


def _glossary(proposer: _Proposer) -> Any:
    """`glossary_prelude` bound as `compose` binds it for Gemini."""
    return glossary_prelude(
        proposer,
        _GEMINI,
        listing=glossary_pass_text,
        max_output_tokens=GLOSSARY_PASS_MAX_OUTPUT_TOKENS,
    )


def _region(mask: bytes) -> RawRegion:
    ring = ((0, 0), (4, 0), (4, 4), (0, 4), (0, 0))
    return RawRegion(polygon=ring, mask=mask, confidence=1.0, kind="bubble")


# -- the world -------------------------------------------------------------------


@dataclass
class _World:
    project: Project
    db_path: Path
    mask: bytes
    log: list[object] = field(default_factory=list)

    def reading(
        self, *, flag: _Flag | None = None, cancel_on: int | None = None
    ) -> tuple[Any, ...]:
        return (_Detect(self.log, self.mask), _Ocr(self.log, flag, cancel_on))

    def translating(
        self, *, raises: Exception | None = None, raise_on: int | None = None
    ) -> tuple[Any, ...]:
        return (_Translate(self.log, raises, raise_on),)

    def run(
        self,
        stages: Sequence[Any],
        *,
        prelude: Any = None,
        after: Sequence[Any] = (),
        cancelled: Callable[[], bool] = _never,
    ) -> tuple[list[RunEvent], RunOutcome]:
        """One whole run through the real runner, two-pass."""
        events: list[RunEvent] = []
        outcome = run_chapter(  # type: ignore[call-arg]
            self.project, stages, events.append, cancelled, prelude=prelude, after_prelude=after
        )
        return events, outcome

    def run_one_pass(
        self, stages: Sequence[Any], *, pass_keyword: bool = False
    ) -> tuple[list[RunEvent], RunOutcome]:
        """A run with no `after_prelude` keyword at all: MT-130 AC-5's shape."""
        events: list[RunEvent] = []
        if pass_keyword:
            outcome = run_chapter(self.project, stages, events.append, _never, prelude=None)
        else:
            outcome = run_chapter(self.project, stages, events.append, _never)
        return events, outcome

    def seed_read(self, ordinal: int) -> None:
        """A page whose reading stages are all done: region and line stored."""
        self.project.write_regions(ordinal, [_region(self.mask)])
        self.project.write_lines(ordinal, [_line_for(ordinal)])

    def statuses(self) -> list[str]:
        return [self.project.page_status(page.ordinal) for page in self.project.pages()]

    def lines(self) -> list[tuple[OcrResult, ...]]:
        return [self.project.read_lines(page.ordinal) for page in self.project.pages()]

    def raw(self, sql: str) -> list[tuple[object, ...]]:
        """Read the file through a connection that knows nothing of `mangatl.store`."""
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()

    def run_rows(self) -> list[tuple[object, ...]]:
        return self.raw("SELECT outcome, aborted_reason FROM run ORDER BY id")

    def ledger_count(self) -> int:
        return int(self.raw("SELECT COUNT(*) FROM llm_call")[0][0])

    def store_rows(self) -> dict[str, list[tuple[object, ...]]]:
        """What AC-6 compares: page status, line and proposal rows, by ordinal."""
        return {
            "page": self.raw("SELECT ordinal, status FROM page ORDER BY ordinal"),
            "line": self.raw(
                "SELECT p.ordinal, r.reading_index, l.source_ja, l.proposed_en"
                " FROM line l JOIN region r ON r.id = l.region_id"
                " JOIN page p ON p.id = r.page_id ORDER BY p.ordinal, r.reading_index"
            ),
            "llm_call": self.raw("SELECT page_id, request_id FROM llm_call ORDER BY id"),
        }


def _make_world(
    root: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    pages: Sequence[tuple[str, int, int]],
) -> Iterator[_World]:
    source_dir = root / "scans"
    source_dir.mkdir(parents=True)
    for index, (filename, width, height) in enumerate(pages):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _World(
            project,
            project_dir_for(source_dir) / "project.db",
            one_bit_png(8, 8, [(0, 0, 4, 4)]),
        )


@pytest.fixture
def world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """A fresh three-page chapter: no regions, no lines, marker unset (AC-1)."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, _THREE_PAGES)


@pytest.fixture
def world2(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """A fresh two-page chapter (AC-3, AC-4)."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, _TWO_PAGES)


def _refusal() -> BudgetRefused:
    budget = Budget(Usd(Decimal("0.00")))
    return BudgetRefused(budget.check(Usd(Decimal("0.00")), budget.project((), 1)))


def _shape(events: Sequence[RunEvent]) -> list[tuple[object, ...]]:
    """The stream with every field but durations and run ids, exactly."""
    shaped: list[tuple[object, ...]] = []
    for e in events:
        kind = type(e).__name__
        if isinstance(e, RunStarted):
            shaped.append((kind, e.page_count))
        elif isinstance(e, PageStarted):
            shaped.append((kind, e.ordinal))
        elif isinstance(e, StageFinished):
            shaped.append((kind, e.ordinal, e.stage))
        elif isinstance(e, PageSkipped):
            shaped.append((kind, e.ordinal, e.reason))
        elif isinstance(e, CallPriced):
            shaped.append((kind, e.ordinal))
        elif isinstance(e, RunAborted):
            shaped.append((kind, e.reason, e.ordinal))
        elif isinstance(e, RunFinished):
            shaped.append((kind, e.pages_done))
        else:
            # `PassStarted`, by its one field: `.name`, as C-2 spells it.
            shaped.append((kind, e.name))  # type: ignore[union-attr]
    return shaped


def _reading_events(
    pages: int, stages: Sequence[str] = ("detect", "ocr")
) -> list[tuple[object, ...]]:
    out: list[tuple[object, ...]] = []
    for ordinal in range(pages):
        out.append(("PageStarted", ordinal))
        out.extend(("StageFinished", ordinal, name) for name in stages)
    return out


def _translating_events(pages: int) -> list[tuple[object, ...]]:
    out: list[tuple[object, ...]] = []
    for ordinal in range(pages):
        out.extend([("PageStarted", ordinal), ("StageFinished", ordinal, "translate")])
    return out


_READ = ("PassStarted", "reading")
_TRANSLATE = ("PassStarted", "translating")


# =============================================================================
# The shapes the Contract fixes (C-1, C-2)
# =============================================================================


def test_run_chapter_takes_prelude_as_a_keyword_only_argument_defaulting_to_none() -> None:
    parameter = inspect.signature(run_chapter).parameters.get("prelude")

    assert parameter is not None, "run_chapter has no prelude parameter"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None


def test_run_chapter_takes_after_prelude_as_a_keyword_only_argument_defaulting_to_empty() -> None:
    """MT-130 C-1: the pass after the prelude's slot, `()` by default so every
    one-pass caller in the tree is unchanged (AC-5)."""
    parameters = inspect.signature(run_chapter).parameters
    parameter = parameters.get("after_prelude")

    assert parameter is not None, "run_chapter has no after_prelude parameter"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default == ()
    assert list(parameters) == [
        "project",
        "stages",
        "emit",
        "cancelled",
        "prelude",
        "after_prelude",
    ]


def test_the_two_pass_names_are_reading_and_translating() -> None:
    """MT-130 C-1: the constants `PassStarted.name` carries, beside `BUDGET`."""
    from mangatl.pipeline import runner

    assert runner.READING == "reading"  # type: ignore[attr-defined]
    assert runner.TRANSLATING == "translating"  # type: ignore[attr-defined]
    assert runner.__all__ == [
        "BUDGET",
        "READING",
        "RUN_ABORTED",
        "RUN_FINISHED",
        "TRANSLATING",
        "RunOutcome",
        "run_chapter",
    ]


def test_pass_started_is_a_frozen_run_event_carrying_only_the_pass_name() -> None:
    """MT-130 C-2: data only (`domain` carries the 100% bar), frozen, in the union."""
    from mangatl.domain.events import PassStarted  # type: ignore[attr-defined]

    assert [f.name for f in dataclasses.fields(PassStarted)] == ["name"]
    assert typing.get_type_hints(PassStarted) == {"name": str}
    assert PassStarted.__dataclass_params__.frozen
    assert PassStarted in typing.get_args(RunEvent)
    with pytest.raises(dataclasses.FrozenInstanceError):
        PassStarted("reading").name = "translating"  # type: ignore[misc]


# =============================================================================
# AC-1, AC-2, AC-7: one proposal over every page's freshly read lines
# =============================================================================


def test_a_fresh_chapters_prelude_proposes_once_over_every_pages_freshly_read_lines(
    world: _World,
) -> None:
    """**AC-1** - the story's central claim. A prelude run before the reading
    pass (MT-105's order) sees an empty listing and skips: no call at all."""
    proposer = _Proposer(world)

    _, outcome = world.run(world.reading(), prelude=_glossary(proposer), after=world.translating())

    assert outcome.outcome == RUN_FINISHED, f"the run did not finish: {outcome}"
    assert proposer.received == [[(_line_for(0),), (_line_for(1),), (_line_for(2),)]], (
        f"the proposer was handed {proposer.received}; AC-1 is exactly one call with"
        " pages 0, 1, 2's freshly read lines, in order"
    )


def test_every_reading_stage_of_every_page_runs_then_the_prelude_then_translation_page_by_page(
    world: _World,
) -> None:
    """**AC-2**: the shared log, exactly."""
    proposer = _Proposer(world)

    world.run(world.reading(), prelude=_glossary(proposer), after=world.translating())

    assert world.log == [
        ("detect", 0),
        ("ocr", 0),
        ("detect", 1),
        ("ocr", 1),
        ("detect", 2),
        ("ocr", 2),
        "prelude",
        ("translate", 0),
        ("translate", 1),
        ("translate", 2),
    ], f"the run's order was {world.log}"


def test_the_reading_pass_marks_no_page_done_and_the_translating_pass_marks_every_one(
    world: _World,
) -> None:
    """**AC-7** (PO-7): seen from inside the prelude, no page is `PAGE_DONE`;
    after `RunFinished`, every page is."""
    proposer = _Proposer(world)

    events, outcome = world.run(
        world.reading(), prelude=_glossary(proposer), after=world.translating()
    )

    assert len(proposer.statuses) == 1, "the proposer was not called exactly once"
    (seen,) = proposer.statuses
    assert all(status != PAGE_DONE for status in seen), (
        f"the prelude saw page statuses {seen}; the reading pass marks nothing done"
    )
    assert isinstance(events[-1], RunFinished) and outcome.pages_done == 3
    assert world.statuses() == [PAGE_DONE] * 3


# =============================================================================
# AC-3, AC-4: the exact streams (C-7)
# =============================================================================


def test_a_fresh_two_page_run_emits_c7s_fresh_run_stream_exactly(world2: _World) -> None:
    """**AC-3**: `PassStarted("reading")`, both pages' reading events,
    `PassStarted("translating")`, the prelude's events (none here), both pages'
    translating events, `RunFinished(pages_done=2)`."""
    step = _Step(world2.log, emits=False)

    events, _ = world2.run(world2.reading(), prelude=step, after=world2.translating())

    assert _shape(events) == [
        ("RunStarted", 2),
        _READ,
        *_reading_events(2),
        _TRANSLATE,
        *_translating_events(2),
        ("RunFinished", 2),
    ], f"the stream was {_shape(events)}"


def test_pass_started_is_emitted_as_the_runners_own_reading_and_translating_constants(
    world2: _World,
) -> None:
    """AC-3, by value rather than by projection: the two events are
    `PassStarted(READING)` and `PassStarted(TRANSLATING)`."""
    from mangatl.domain.events import PassStarted  # type: ignore[attr-defined]
    from mangatl.pipeline.runner import READING, TRANSLATING  # type: ignore[attr-defined]

    events, _ = world2.run(
        world2.reading(), prelude=_Step(world2.log, emits=False), after=world2.translating()
    )

    passes = [e for e in events if isinstance(e, PassStarted)]
    assert passes == [PassStarted(READING), PassStarted(TRANSLATING)]


def test_the_preludes_own_events_land_between_the_translating_pass_start_and_its_first_page(
    world2: _World,
) -> None:
    """C-7's `<the prelude's own events>`: after `PassStarted("translating")`,
    before `PageStarted(0)` of the translating pass."""
    events, _ = world2.run(world2.reading(), prelude=_Step(world2.log), after=world2.translating())

    shaped = _shape(events)
    at = shaped.index(_TRANSLATE)
    assert shaped[at : at + 3] == [_TRANSLATE, ("CallPriced", None), ("PageStarted", 0)], (
        f"the stream around the translating pass was {shaped[at - 1 : at + 3]}"
    )
    assert events[at + 1] is _STEP_EVENT


def test_a_resumed_run_skips_the_read_page_reads_the_other_and_proposes_over_both(
    world2: _World,
) -> None:
    """**AC-4**, C-7's resume stream: page 0 read, page 1 not, marker unset."""
    world2.seed_read(0)
    proposer = _Proposer(world2)

    events, outcome = world2.run(
        world2.reading(), prelude=_glossary(proposer), after=world2.translating()
    )

    assert _shape(events) == [
        ("RunStarted", 2),
        _READ,
        ("PageSkipped", 0, _ALREADY_DONE),
        ("PageStarted", 1),
        ("StageFinished", 1, "detect"),
        ("StageFinished", 1, "ocr"),
        _TRANSLATE,
        ("CallPriced", None),
        *_translating_events(2),
        ("RunFinished", 2),
    ], f"the stream was {_shape(events)}"
    assert proposer.received == [[(_line_for(0),), (_line_for(1),)]], (
        f"the proposer was handed {proposer.received}; AC-4 is both pages' lines"
    )
    assert outcome.pages_done == 2


# =============================================================================
# AC-5: one pass, exactly as before
# =============================================================================


def _one_pass_stream(pages: int) -> list[tuple[object, ...]]:
    return [
        ("RunStarted", pages),
        *_reading_events(pages, ("detect", "ocr", "translate")),
        ("RunFinished", pages),
    ]


@pytest.mark.parametrize("pass_keyword", [False, True], ids=["no-keyword", "prelude-none"])
def test_a_one_pass_run_emits_no_pass_started_and_todays_stream(
    world: _World, pass_keyword: bool
) -> None:
    """**AC-5**: no `after_prelude`, no prelude - today's stream, event for
    event, and no `PassStarted` anywhere (PO-11)."""
    events, outcome = world.run_one_pass(
        (*world.reading(), *world.translating()), pass_keyword=pass_keyword
    )

    assert _shape(events) == _one_pass_stream(3), f"the stream was {_shape(events)}"
    assert not [e for e in events if type(e).__name__ == "PassStarted"]
    assert outcome.pages_done == 3


def test_a_one_pass_run_marks_each_page_done_as_it_completes(world: _World) -> None:
    """**AC-5**: when page n's first stage runs, page n-1 is already done."""
    seen: list[list[str]] = []

    @dataclass
    class _Watch:
        name: str = "watch"

        def run(self, ctx: PageContext) -> None:
            seen.append(world.statuses())

        def is_done(self, ctx: PageContext) -> bool:
            return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE

    world.run_one_pass((_Watch(), *world.reading(), *world.translating()))

    assert seen == [
        [PAGE_PENDING, PAGE_PENDING, PAGE_PENDING],
        [PAGE_DONE, PAGE_PENDING, PAGE_PENDING],
        [PAGE_DONE, PAGE_DONE, PAGE_PENDING],
    ], f"the page statuses as each page started were {seen}"


def test_an_explicit_none_prelude_runs_exactly_as_no_keyword_at_all(world: _World) -> None:
    events_none, outcome_none = world.run_one_pass(world.reading(), pass_keyword=True)
    world.log.clear()
    with world.project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ?", (PAGE_PENDING,))
        cursor.execute("DELETE FROM region")

    events_bare, outcome_bare = world.run_one_pass(world.reading())

    assert _shape(events_none) == _shape(events_bare)
    assert outcome_none.outcome == outcome_bare.outcome == RUN_FINISHED


# =============================================================================
# AC-6: no prelude, but a translating pass - two passes, nothing between
# =============================================================================


def test_with_no_prelude_but_a_translating_pass_the_run_has_two_passes_and_nothing_between(
    world: _World,
) -> None:
    """**AC-6** (PO-2, the Anthropic shape)."""
    events, _ = world.run(world.reading(), prelude=None, after=world.translating())

    assert _shape(events) == [
        ("RunStarted", 3),
        _READ,
        *_reading_events(3),
        _TRANSLATE,
        *_translating_events(3),
        ("RunFinished", 3),
    ], f"the stream was {_shape(events)}"
    assert not [e for e in events if isinstance(e, CallPriced)]


def test_two_passes_with_no_prelude_leave_the_same_rows_as_one_pass_over_the_same_chapter(
    world: _World,
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> None:
    """**AC-6**: `page.status`, `line` and proposal rows (and the ledger, empty
    both sides) equal a single-pass run's over an identically seeded project."""
    world.run(world.reading(), prelude=None, after=world.translating())
    single = _make_world(tmp_path / "single", png_bytes, one_bit_png, _THREE_PAGES)
    try:
        other = next(single)
        other.run_one_pass((*other.reading(), *other.translating()))
        expected = other.store_rows()
    finally:
        single.close()

    assert expected["page"] == [(0, PAGE_DONE), (1, PAGE_DONE), (2, PAGE_DONE)], (
        "the control is broken: the single-pass run did not finish every page"
    )
    assert world.store_rows() == expected


# =============================================================================
# AC-8: a cancel during the last reading stage
# =============================================================================


def test_a_cancel_during_the_last_reading_stage_aborts_before_the_translating_pass(
    world: _World,
) -> None:
    """**AC-8**, C-7's cancel stream: the last page's last `StageFinished`,
    then `RunAborted("cancelled", None)`; no `PassStarted("translating")`."""
    flag = _Flag()
    proposer = _Proposer(world)

    events, outcome = world.run(
        world.reading(flag=flag, cancel_on=2),
        prelude=_glossary(proposer),
        after=world.translating(),
        cancelled=flag,
    )

    assert _shape(events) == [
        ("RunStarted", 3),
        _READ,
        *_reading_events(3),
        ("RunAborted", _CANCELLED, None),
    ], f"the stream was {_shape(events)}"
    assert proposer.received == [], "the proposer was called after the cancel"
    assert outcome.pages_done == 0
    assert outcome.outcome == RUN_ABORTED and outcome.aborted_reason == _CANCELLED


def test_a_cancel_during_the_reading_pass_keeps_the_reading_and_spends_nothing(
    world: _World,
) -> None:
    """**AC-8**, the store: no ledger row, marker unset, every page's lines
    kept, no page done, the `run` row `aborted`/`cancelled`."""
    flag = _Flag()

    world.run(
        world.reading(flag=flag, cancel_on=2),
        prelude=_glossary(_Proposer(world)),
        after=world.translating(),
        cancelled=flag,
    )

    assert world.ledger_count() == 0
    assert world.project.glossary_proposed_at() is None
    assert world.lines() == [(_line_for(0),), (_line_for(1),), (_line_for(2),)]
    assert all(status != PAGE_DONE for status in world.statuses()), world.statuses()
    assert world.run_rows() == [(RUN_ABORTED, _CANCELLED)]


def test_the_run_after_a_reading_pass_cancel_skips_reading_proposes_and_translates(
    world: _World,
) -> None:
    """**AC-8**, the second run: `PageSkipped` for every page in the reading
    pass, one proposal over every page's lines, every page translated."""
    flag = _Flag()
    world.run(
        world.reading(flag=flag, cancel_on=2),
        prelude=_glossary(_Proposer(world)),
        after=world.translating(),
        cancelled=flag,
    )
    world.log.clear()
    proposer = _Proposer(world)

    events, outcome = world.run(
        world.reading(), prelude=_glossary(proposer), after=world.translating()
    )

    assert _shape(events) == [
        ("RunStarted", 3),
        _READ,
        ("PageSkipped", 0, _ALREADY_DONE),
        ("PageSkipped", 1, _ALREADY_DONE),
        ("PageSkipped", 2, _ALREADY_DONE),
        _TRANSLATE,
        ("CallPriced", None),
        *_translating_events(3),
        ("RunFinished", 3),
    ], f"the second run's stream was {_shape(events)}"
    assert proposer.received == [[(_line_for(0),), (_line_for(1),), (_line_for(2),)]]
    assert world.statuses() == [PAGE_DONE] * 3
    assert outcome.pages_done == 3


# =============================================================================
# AC-9: a cancel during the prelude
# =============================================================================


def test_a_cancel_set_while_the_prelude_runs_lets_it_finish_and_starts_no_translating_page(
    world: _World,
) -> None:
    """**AC-9** (PO-8): the prelude completes - its bill and its marker stand -
    and the translating pass's first page-loop check honours the cancel."""
    flag = _Flag()
    proposer = _Proposer(world, flag=flag)

    events, outcome = world.run(
        world.reading(), prelude=_glossary(proposer), after=world.translating(), cancelled=flag
    )

    assert _shape(events) == [
        ("RunStarted", 3),
        _READ,
        *_reading_events(3),
        _TRANSLATE,
        ("CallPriced", None),
        ("RunAborted", _CANCELLED, None),
    ], f"the stream was {_shape(events)}"
    assert len(proposer.received) == 1
    assert world.ledger_count() == 1, "the prelude's bill did not stand"
    assert world.project.glossary_proposed_at() is not None, "the prelude's marker did not stand"
    assert outcome.pages_done == 0
    assert "translate" not in [entry[0] for entry in world.log if isinstance(entry, tuple)]


# =============================================================================
# AC-10: the prelude fails after the reading pass
# =============================================================================


def test_a_prelude_refused_by_the_budget_aborts_after_the_whole_reading_pass(
    world: _World,
) -> None:
    """**AC-10**, C-7's budget stream: every reading stage ran,
    `PassStarted("translating")`, then `RunAborted("budget", None)`."""
    step = _Step(world.log, raises=_refusal())

    events, outcome = world.run(world.reading(), prelude=step, after=world.translating())

    assert _shape(events) == [
        ("RunStarted", 3),
        _READ,
        *_reading_events(3),
        _TRANSLATE,
        ("RunAborted", BUDGET, None),
    ], f"the stream was {_shape(events)}"
    assert world.log == [
        ("detect", 0),
        ("ocr", 0),
        ("detect", 1),
        ("ocr", 1),
        ("detect", 2),
        ("ocr", 2),
        "prelude",
    ], f"the run's order was {world.log}; no after_prelude stage may run"
    assert outcome.outcome == RUN_ABORTED and outcome.aborted_reason == BUDGET
    assert outcome.pages_done == 0


def test_a_refused_prelude_keeps_every_pages_reading_and_is_recorded_as_a_budget_abort(
    world: _World,
) -> None:
    world.run(
        world.reading(), prelude=_Step(world.log, raises=_refusal()), after=world.translating()
    )

    assert world.lines() == [(_line_for(0),), (_line_for(1),), (_line_for(2),)]
    assert all(status != PAGE_DONE for status in world.statuses()), world.statuses()
    assert world.run_rows() == [(RUN_ABORTED, BUDGET)]


def test_any_other_prelude_failure_aborts_with_its_type_and_message_after_the_reading_pass(
    world: _World,
) -> None:
    """**AC-10**, second half: `RuntimeError("x")` -> `"RuntimeError: x"`, no page."""
    step = _Step(world.log, raises=RuntimeError("x"))

    events, outcome = world.run(world.reading(), prelude=step, after=world.translating())

    assert _shape(events) == [
        ("RunStarted", 3),
        _READ,
        *_reading_events(3),
        _TRANSLATE,
        ("RunAborted", "RuntimeError: x", None),
    ], f"the stream was {_shape(events)}"
    assert events[-1] == RunAborted(reason="RuntimeError: x", ordinal=None)
    assert outcome.aborted_reason == "RuntimeError: x"
    assert world.lines() == [(_line_for(0),), (_line_for(1),), (_line_for(2),)]
    assert world.run_rows() == [(RUN_ABORTED, "RuntimeError: x")]


def test_a_prelude_failure_does_not_escape_the_runner(world: _World) -> None:
    """A raise through `run_chapter` would leave the window's worker dead with
    the readout stuck, which is why a failure is returned, not raised."""
    try:
        world.run(
            world.reading(),
            prelude=_Step(world.log, raises=RuntimeError("boom")),
            after=world.translating(),
        )
    except RuntimeError as error:  # pragma: no cover - the failure being pinned
        pytest.fail(f"the prelude's exception escaped run_chapter: {error!r}")


def test_the_prelude_is_handed_the_project_the_runs_id_and_the_runs_own_emit(
    world: _World,
) -> None:
    """MT-105's hand-off, unchanged by the move to between the passes."""
    step = _Step(world.log)

    events, outcome = world.run(world.reading(), prelude=step, after=world.translating())

    ((project, run_id, emit),) = step.calls
    (started,) = [e for e in events if isinstance(e, RunStarted)]
    assert project is world.project
    assert run_id == started.run_id == outcome.run_id
    assert _STEP_EVENT in events, "what the prelude emitted did not reach the run's stream"
    assert callable(emit)


# =============================================================================
# AC-11: a budget refusal in the translating pass
# =============================================================================


def test_a_budget_refusal_on_translating_page_one_aborts_naming_it_with_page_zero_done(
    world: _World,
) -> None:
    """**AC-11**: `RunAborted("budget", 1)`, page 0 done, pages 1 and 2 read
    and not done, `pages_done == 1`."""
    events, outcome = world.run(
        world.reading(),
        prelude=_Step(world.log, emits=False),
        after=world.translating(raises=_refusal(), raise_on=1),
    )

    assert events[-1] == RunAborted(reason=BUDGET, ordinal=1), f"the run ended {events[-1]!r}"
    assert _shape(events) == [
        ("RunStarted", 3),
        _READ,
        *_reading_events(3),
        _TRANSLATE,
        ("PageStarted", 0),
        ("StageFinished", 0, "translate"),
        ("PageStarted", 1),
        ("RunAborted", BUDGET, 1),
    ], f"the stream was {_shape(events)}"
    assert world.statuses()[0] == PAGE_DONE
    assert world.statuses()[1:] == [PAGE_PENDING, PAGE_PENDING], world.statuses()
    assert world.lines()[1:] == [(_line_for(1),), (_line_for(2),)]
    assert outcome.pages_done == 1
    assert world.run_rows() == [(RUN_ABORTED, BUDGET)]
