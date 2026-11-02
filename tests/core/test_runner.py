"""MT-105: `run_chapter`'s chapter step - the `prelude` keyword.

The runner half of the story, with the prelude replaced by a recording
`ChapterStep` so these tests say nothing about glossaries: *when* the step runs
(after `RunStarted`, before the first `PageStarted`), *what* it is handed (the
project, the run's id, the run's own `emit`), and how its two kinds of failure
are reported (`BudgetRefused` -> `RunAborted(reason="budget", ordinal=None)`;
anything else -> `RunAborted` with `"{type}: {message}"`, `ordinal=None`, as a
page failure is reported today).

**AC-6 is not here.** "Without `prelude`, behaves exactly as before" is every
existing runner test passing unchanged - `tests/core/test_pipeline.py` and the
other `run_chapter` suites - and none of them is edited by this story. The one
assertion here about the default is on the signature, and one control that an
explicit `prelude=None` and no keyword at all produce the same stream.

**RED:** `run_chapter` has no `prelude` keyword, so every call that passes one
is a `TypeError`. The `type: ignore[call-arg]` comments go with it; mypy does
not read `tests/`.

**Timing.** No `pytest-timeout` in this project, so there is no budget to size.
"""

from __future__ import annotations

import inspect
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from mangatl.domain.budget import Budget, Projection
from mangatl.domain.events import (
    CallPriced,
    PageStarted,
    RunAborted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.domain.money import Usd
from mangatl.pipeline.runner import BUDGET, RUN_ABORTED, RUN_FINISHED, RunOutcome, run_chapter
from mangatl.pipeline.stage import BudgetRefused, PageContext
from mangatl.store.intake import read_chapter
from mangatl.store.project import PAGE_DONE, PAGE_PENDING, Project, create_project, project_dir_for

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)
_STAGE = "recorded"

#: What the recording step emits, so its place in the stream is observable.
_STEP_EVENT = CallPriced(
    ordinal=None,  # type: ignore[arg-type]
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


@dataclass
class _Step:
    """A `ChapterStep`: `(project, run_id, emit) -> None`, recorded."""

    log: list[object]
    raises: Exception | None = None
    calls: list[tuple[Project, int, Callable[[RunEvent], None]]] = field(default_factory=list)

    def __call__(self, project: Project, run_id: int, emit: Callable[[RunEvent], None]) -> None:
        self.calls.append((project, run_id, emit))
        self.log.append("prelude")
        if self.raises is not None:
            raise self.raises
        emit(_STEP_EVENT)


@dataclass
class _Stage:
    log: list[object]
    name: str = _STAGE

    def run(self, ctx: PageContext) -> None:
        self.log.append(("stage", ctx.page.ordinal))

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


@dataclass
class _World:
    project: Project
    db_path: Path
    log: list[object] = field(default_factory=list)

    def run(
        self, step: Any = None, *, pass_keyword: bool = True
    ) -> tuple[list[RunEvent], RunOutcome]:
        events: list[RunEvent] = []
        stages = (_Stage(self.log),)
        if pass_keyword:
            outcome = run_chapter(self.project, stages, events.append, _never, prelude=step)  # type: ignore[call-arg]
        else:
            outcome = run_chapter(self.project, stages, events.append, _never)
        return events, outcome

    def run_rows(self) -> list[tuple[object, ...]]:
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(
                "SELECT outcome, aborted_reason FROM run ORDER BY id"
            ).fetchall()
        finally:
            connection.close()


@pytest.fixture
def world(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Iterator[_World]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for filename, width, height in _SOURCE_PAGES:
        (source_dir / filename).write_bytes(png_bytes(width, height))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _World(project, project_dir_for(source_dir) / "project.db")


def _refusal() -> BudgetRefused:
    budget = Budget(Usd(Decimal("0.00")))
    return BudgetRefused(budget.check(Usd(Decimal("0.00")), budget.project((), 1)))


def _shape(events: Sequence[RunEvent]) -> list[tuple[str, object]]:
    """The stream without durations or run ids."""
    return [(type(e).__name__, getattr(e, "ordinal", None)) for e in events]


# -- the signature -------------------------------------------------------------


def test_run_chapter_takes_prelude_as_a_keyword_only_argument_defaulting_to_none() -> None:
    parameter = inspect.signature(run_chapter).parameters.get("prelude")

    assert parameter is not None, "run_chapter has no prelude parameter"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None


def test_an_explicit_none_prelude_runs_exactly_as_no_keyword_at_all(world: _World) -> None:
    events_none, outcome_none = world.run(None)
    world.log.clear()
    with world.project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ?", (PAGE_PENDING,))

    events_bare, outcome_bare = world.run(pass_keyword=False)

    assert _shape(events_none) == _shape(events_bare)
    assert outcome_none.outcome == outcome_bare.outcome == RUN_FINISHED


# -- when it runs, and what it is handed ----------------------------------------


def test_the_prelude_runs_once_before_any_page_stage(world: _World) -> None:
    step = _Step(world.log)

    world.run(step)

    assert world.log == ["prelude", ("stage", 0), ("stage", 1), ("stage", 2)], (
        f"the run's order was {world.log}; the prelude runs once, before page 1"
    )


def test_the_prelude_runs_after_run_started_and_before_the_first_page_started(
    world: _World,
) -> None:
    events, _ = world.run(_Step(world.log))

    assert _shape(events)[:3] == [
        ("RunStarted", None),
        ("CallPriced", None),
        ("PageStarted", 0),
    ], f"the stream opened {_shape(events)[:3]}"
    assert isinstance(events[-1], RunFinished) and events[-1].pages_done == 3


def test_the_prelude_is_handed_the_project_the_runs_id_and_the_runs_own_emit(
    world: _World,
) -> None:
    step = _Step(world.log)

    events, outcome = world.run(step)

    ((project, run_id, emit),) = step.calls
    (started,) = [e for e in events if isinstance(e, RunStarted)]
    assert project is world.project
    assert run_id == started.run_id == outcome.run_id
    assert _STEP_EVENT in events, "what the prelude emitted did not reach the run's stream"
    assert callable(emit)


# -- how its failures are reported ---------------------------------------------


def test_a_budget_refusal_in_the_prelude_aborts_with_reason_budget_naming_no_page(
    world: _World,
) -> None:
    events, outcome = world.run(_Step(world.log, raises=_refusal()))

    assert events[-1] == RunAborted(reason=BUDGET, ordinal=None), (
        f"the run ended with {events[-1]!r}; a refused prelude is"
        " RunAborted(reason='budget', ordinal=None)"
    )
    assert outcome.outcome == RUN_ABORTED and outcome.aborted_reason == BUDGET
    assert outcome.pages_done == 0


def test_a_budget_refusal_in_the_prelude_starts_no_page_and_runs_no_stage(world: _World) -> None:
    events, _ = world.run(_Step(world.log, raises=_refusal()))

    assert world.log == ["prelude"]
    assert not [e for e in events if isinstance(e, (PageStarted, StageFinished))]
    assert _shape(events) == [("RunStarted", None), ("RunAborted", None)]


def test_a_refused_prelude_is_recorded_as_an_aborted_run(world: _World) -> None:
    world.run(_Step(world.log, raises=_refusal()))

    assert world.run_rows() == [(RUN_ABORTED, BUDGET)]


def test_any_other_prelude_failure_aborts_with_its_type_and_message_naming_no_page(
    world: _World,
) -> None:
    events, outcome = world.run(_Step(world.log, raises=ValueError("the answer had no key")))

    assert events[-1] == RunAborted(reason="ValueError: the answer had no key", ordinal=None), (
        f"the run ended with {events[-1]!r}"
    )
    assert outcome.aborted_reason == "ValueError: the answer had no key"
    assert world.log == ["prelude"]
    assert world.run_rows() == [(RUN_ABORTED, "ValueError: the answer had no key")]


def test_a_prelude_failure_does_not_escape_the_runner(world: _World) -> None:
    """A raise through `run_chapter` would leave the window's worker dead with
    the readout stuck, which is why a page failure is returned, not raised."""
    try:
        world.run(_Step(world.log, raises=RuntimeError("boom")))
    except RuntimeError as error:  # pragma: no cover - the failure being pinned
        pytest.fail(f"the prelude's exception escaped run_chapter: {error!r}")
