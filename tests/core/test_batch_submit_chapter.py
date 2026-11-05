"""MT-113 C-1: `pipeline.batch.submit_chapter`, the batch run's whole Start.

The batch path's order, which `run_chapter` cannot give it (PO-5): the LOCAL
stages first, through `run_chapter` with **no** prelude; then the glossary
pre-pass with the local run's id, once every page's OCR exists; then a cancel
check; then `submit_volume`. `RunFinished` from the local stages is **not**
forwarded - the window opens the review on it, and the local stages finishing
is not the run finishing.

**Oracle partition: mechanical.** Event lists compared exactly (with
`StageFinished.elapsed_ms`, a measured duration, zeroed), call order read off
one shared log, `RunAborted` reasons compared with `==` against the runner's
own constants and the runner's own wording for a failed prelude.

**The world is real**: a `.mtproj` on `tmp_path` with three tiny PNG pages, a
`run_chapter` and a `submit_volume` that are the shipped ones. The doubles are
the two local stages (`detect` writes one region, `ocr` writes one line - so
`submit_volume`'s "every page has OCR" precondition is met only if the stages
really ran first), the prelude (records what it saw) and the submitter
(returns `batches/a`, `batches/b`, ...).

**RED:** `submit_chapter` is imported inside `_submit_chapter`, so each test
fails on the named absence and the file still collects.

**Timing.** No waits; three tiny pages per test.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from mangatl.domain.budget import Decision, Projection
from mangatl.domain.events import (
    BatchSubmitted,
    CallPriced,
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
from mangatl.pipeline.runner import BUDGET, CANCELLED
from mangatl.pipeline.stage import BudgetRefused, PageContext
from mangatl.store.batch import pending_jobs
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

_MODEL = "gemini-3.1-pro-preview"
#: MT-111 AC-1's batch page estimate, written out: $0.02.
_ESTIMATE = Usd.from_micro(20_000)
#: A ceiling three pages at $0.02 fit under.
_ROOMY_CEILING_MICRO = 1_000_000
#: Three pages over a $0.05 ceiling: refused (3 x $0.02 = $0.06).
_TIGHT_CEILING_MICRO = 50_000
#: A request size that puts two pages in one 20 MB job and the third in a
#: second: 16 MB fits, 24 MB does not.
_EIGHT_MB = 8_000_000

_PAGES = ("p1.png", "p2.png", "p3.png")


# -- doubles -------------------------------------------------------------------


@dataclass
class _Log:
    """Every call any double made, in order, on one list."""

    entries: list[tuple[Any, ...]] = field(default_factory=list)

    def kinds(self) -> list[str]:
        return [str(entry[0]) for entry in self.entries]


class _Detect:
    """`detect`: one region on the page, so `ocr` has something to write against."""

    name = "detect"

    def __init__(self, log: _Log, mask: bytes) -> None:
        self._log = log
        self._mask = mask

    def run(self, ctx: PageContext) -> None:
        self._log.entries.append(("stage", "detect", ctx.page.ordinal))
        ring = ((0, 0), (4, 0), (4, 4), (0, 4), (0, 0))
        ctx.project.write_regions(
            ctx.page.ordinal,
            [RawRegion(polygon=ring, mask=self._mask, confidence=1.0, kind="bubble")],
        )

    def is_done(self, ctx: PageContext) -> bool:
        return False


class _Ocr:
    """`ocr`: one line per page. Optionally fails on one page, or sets the
    cancel flag after the last page's OCR (the run itself then finishes)."""

    name = "ocr"

    def __init__(
        self,
        log: _Log,
        *,
        fail_on: int | None = None,
        cancel_after_last: list[bool] | None = None,
    ) -> None:
        self._log = log
        self._fail_on = fail_on
        self._cancel_after_last = cancel_after_last

    def run(self, ctx: PageContext) -> None:
        n = ctx.page.ordinal
        self._log.entries.append(("stage", "ocr", n))
        if n == self._fail_on:
            raise RuntimeError(f"ocr broke on page {n}")
        ctx.project.write_lines(n, [OcrResult(f"line {n}")])
        if self._cancel_after_last is not None and n == len(_PAGES) - 1:
            self._cancel_after_last.append(True)

    def is_done(self, ctx: PageContext) -> bool:
        return False


class _Prelude:
    """A `ChapterStep`: records the run id it was handed and whether every page
    had OCR when it ran; then emits `emits`, raises `raises`, or sets the
    cancel flag."""

    def __init__(
        self,
        log: _Log,
        *,
        emits: Sequence[RunEvent] = (),
        raises: Exception | None = None,
        cancel: list[bool] | None = None,
    ) -> None:
        self._log = log
        self._emits = tuple(emits)
        self._raises = raises
        self._cancel = cancel

    def __call__(self, project: Project, run_id: int, emit: Callable[[RunEvent], None]) -> None:
        every_page_read = all(project.read_lines(p.ordinal) for p in project.pages())
        self._log.entries.append(("prelude", run_id, every_page_read))
        for event in self._emits:
            emit(event)
        if self._cancel is not None:
            self._cancel.append(True)
        if self._raises is not None:
            raise self._raises


class _Submitter:
    """Stands where `compose`'s bound `submit_batch` stands: one call, one job."""

    def __init__(self, log: _Log) -> None:
        self._log = log
        self.calls = 0

    def __call__(self, inputs: Sequence[Any]) -> str:
        self.calls += 1
        self._log.entries.append(("submit", [i.ordinal for i in inputs]))
        return f"batches/{chr(ord('a') + self.calls - 1)}"


def _size(value: int) -> Callable[[Any], int]:
    return lambda page_input: value


def _refusal() -> BudgetRefused:
    projection = Projection(
        next_call=Usd.from_micro(60_000),
        remaining_chapter=Usd.from_micro(60_000),
        basis="estimate",
        sample_count=0,
    )
    return BudgetRefused(
        Decision(
            permitted=False,
            reason="the glossary pass would exceed the budget",
            spent=Usd.from_micro(0),
            ceiling=Usd.from_micro(_TIGHT_CEILING_MICRO),
            projection=projection,
        )
    )


# -- the world -----------------------------------------------------------------


@dataclass
class _World:
    project: Project
    db_path: Path
    mask: bytes
    log: _Log = field(default_factory=_Log)
    events: list[RunEvent] = field(default_factory=list)

    def set_ceiling(self, micro: int) -> None:
        with self.project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))

    def runs(self) -> list[tuple[Any, ...]]:
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(
                "SELECT id, outcome, aborted_reason FROM run ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

    def submit(
        self,
        *,
        prelude: Any = None,
        ocr: _Ocr | None = None,
        size: int = 1,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> tuple[int, ...]:
        submitter = _Submitter(self.log)
        stages = (_Detect(self.log, self.mask), ocr if ocr is not None else _Ocr(self.log))
        return _submit_chapter(
            self.project,
            stages=stages,
            prelude=prelude,
            submit=submitter,
            request_size=_size(size),
            model_id=_MODEL,
            page_estimate=_ESTIMATE,
            emit=self.events.append,
            cancelled=cancelled,
        )


def _submit_chapter(project: Project, **kwargs: Any) -> tuple[int, ...]:
    from mangatl.pipeline.batch import submit_chapter  # type: ignore[attr-defined]

    ids: tuple[int, ...] = submit_chapter(project, **kwargs)
    return ids


@pytest.fixture
def world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, filename in enumerate(_PAGES):
        (source_dir / filename).write_bytes(png_bytes(20 + index, 16, (index * 40, 0, 0)))
    project_dir = project_dir_for(source_dir)
    with create_project(read_chapter(source_dir), project_dir) as project:
        made = _World(project, project_dir / "project.db", one_bit_png(8, 8, [(0, 0, 4, 4)]))
        made.set_ceiling(_ROOMY_CEILING_MICRO)
        yield made


def _normalised(events: Sequence[RunEvent]) -> list[RunEvent]:
    return [
        dataclasses.replace(e, elapsed_ms=0) if isinstance(e, StageFinished) else e for e in events
    ]


def _local_events(run_id: int) -> list[RunEvent]:
    """What the local stages emit for three pages, `RunFinished` excluded."""
    events: list[RunEvent] = [RunStarted(run_id=run_id, page_count=3)]
    for n in range(3):
        events += [
            PageStarted(ordinal=n),
            StageFinished(ordinal=n, stage="detect", elapsed_ms=0),
            StageFinished(ordinal=n, stage="ocr", elapsed_ms=0),
        ]
    return events


def _run_id(world: _World) -> int:
    started = [e for e in world.events if isinstance(e, RunStarted)]
    assert len(started) == 1, f"{len(started)} RunStarted events; the local run starts once"
    return started[0].run_id


# -- step 1: the local stages, without RunFinished ------------------------------


def test_the_local_stages_run_on_every_page_before_the_prelude_and_the_submission(
    world: _World,
) -> None:
    prelude = _Prelude(world.log)

    world.submit(prelude=prelude)

    stages = [("stage", name, n) for n in range(3) for name in ("detect", "ocr")]
    run_id = _run_id(world)
    assert world.log.entries == [*stages, ("prelude", run_id, True), ("submit", [0, 1, 2])], (
        "C-1's order is the local stages on every page, then the prelude with the"
        " local run's id (every page read by then, PO-5), then one submission"
    )


def test_the_local_runs_run_finished_is_not_forwarded_and_the_stream_ends_submitted(
    world: _World,
) -> None:
    ids = world.submit()

    run_id = _run_id(world)
    assert not any(isinstance(e, RunFinished) for e in world.events), (
        "RunFinished reached emit: the window would open the review before anything"
        " was submitted (C-1 step 1)"
    )
    *local, last = _normalised(world.events)
    assert local == _local_events(run_id)
    assert isinstance(last, BatchSubmitted), f"the stream ended with {last!r}"
    assert (last.run_id, last.job_ids, last.page_count) == (run_id, ids, 3)


def test_the_local_run_row_is_finished_and_every_job_carries_its_id(world: _World) -> None:
    ids = world.submit(size=_EIGHT_MB)

    run_id = _run_id(world)
    assert world.runs() == [(run_id, "finished", None)], (
        "the run row is the local stages', ended by run_chapter as finished"
    )
    jobs = pending_jobs(world.project)
    assert tuple(job.id for job in jobs) == ids
    assert [(job.first_ordinal, job.last_ordinal) for job in jobs] == [(0, 1), (2, 2)]
    assert {job.run_id for job in jobs} == {run_id}
    assert {job.model_id for job in jobs} == {_MODEL}


def test_without_a_prelude_the_volume_is_submitted_straight_after_the_local_stages(
    world: _World,
) -> None:
    ids = world.submit(prelude=None)

    assert world.log.kinds() == ["stage"] * 6 + ["submit"]
    assert len(ids) == 1


def test_a_local_stage_failure_returns_nothing_and_its_abort_has_reached_emit(
    world: _World,
) -> None:
    prelude = _Prelude(world.log)

    ids = world.submit(prelude=prelude, ocr=_Ocr(world.log, fail_on=1))

    assert ids == ()
    assert world.events[-1] == RunAborted(reason="RuntimeError: ocr broke on page 1", ordinal=1)
    assert [e for e in world.events if isinstance(e, RunAborted)] == [world.events[-1]], (
        "the local stages' abort must reach emit exactly once"
    )
    assert "prelude" not in world.log.kinds(), "the prelude ran after a failed local stage"
    assert "submit" not in world.log.kinds(), "a job was submitted after a failed local stage"
    assert pending_jobs(world.project) == ()


# -- step 2: the prelude ---------------------------------------------------------


def test_the_preludes_own_events_reach_emit_between_the_local_stages_and_the_submission(
    world: _World,
) -> None:
    priced = CallPriced(
        ordinal=None,
        spent=Usd.from_micro(1_000),
        ceiling=Usd.from_micro(_ROOMY_CEILING_MICRO),
        projection=Projection(
            next_call=_ESTIMATE, remaining_chapter=_ESTIMATE, basis="estimate", sample_count=0
        ),
    )

    world.submit(prelude=_Prelude(world.log, emits=[priced]))

    events = _normalised(world.events)
    assert events[:-1] == [*_local_events(_run_id(world)), priced]
    assert isinstance(events[-1], BatchSubmitted)


def test_a_prelude_refused_by_the_budget_aborts_on_budget_and_submits_nothing(
    world: _World,
) -> None:
    ids = world.submit(prelude=_Prelude(world.log, raises=_refusal()))

    assert ids == ()
    assert BUDGET == "budget"
    assert world.events[-1] == RunAborted(reason=BUDGET, ordinal=None)
    assert "submit" not in world.log.kinds()
    assert pending_jobs(world.project) == ()


def test_a_prelude_that_raises_aborts_with_the_runners_wording_and_submits_nothing(
    world: _World,
) -> None:
    ids = world.submit(prelude=_Prelude(world.log, raises=ValueError("listing too long")))

    assert ids == ()
    assert world.events[-1] == RunAborted(reason="ValueError: listing too long", ordinal=None)
    assert "submit" not in world.log.kinds()
    assert pending_jobs(world.project) == ()


# -- step 3: a cancel after the local stages --------------------------------------


def test_a_cancel_raised_during_the_prelude_aborts_as_cancelled_before_submitting(
    world: _World,
) -> None:
    flag: list[bool] = []

    ids = world.submit(prelude=_Prelude(world.log, cancel=flag), cancelled=lambda: bool(flag))

    assert ids == ()
    assert CANCELLED == "cancelled"
    assert world.events[-1] == RunAborted(reason=CANCELLED, ordinal=None)
    assert "submit" not in world.log.kinds()
    assert pending_jobs(world.project) == ()


def test_a_cancel_raised_by_the_last_local_stage_is_honoured_before_submitting(
    world: _World,
) -> None:
    """`run_chapter` consults `cancelled` only at stage boundaries, so a cancel
    set inside the last page's last stage lets the local run finish; C-1 step 3
    is what catches it."""
    flag: list[bool] = []

    ids = world.submit(ocr=_Ocr(world.log, cancel_after_last=flag), cancelled=lambda: bool(flag))

    assert world.runs()[0][1] == "finished", "precondition: the local run itself finished"
    assert ids == ()
    assert world.events[-1] == RunAborted(reason=CANCELLED, ordinal=None)
    assert "submit" not in world.log.kinds()


# -- step 4: submit_volume's own refusal passes straight through -------------------


def test_a_volume_over_the_stored_ceiling_is_refused_by_submit_volume_and_nothing_is_pending(
    world: _World,
) -> None:
    world.set_ceiling(_TIGHT_CEILING_MICRO)

    ids = world.submit()

    assert ids == ()
    priced, aborted = world.events[-2:]
    assert aborted == RunAborted(reason=BUDGET, ordinal=None)
    assert isinstance(priced, CallPriced), f"the refusal was preceded by {priced!r}"
    assert (priced.ordinal, priced.spent, priced.ceiling, priced.projection.next_call) == (
        None,
        Usd.from_micro(0),
        Usd.from_micro(_TIGHT_CEILING_MICRO),
        Usd.from_micro(60_000),
    )
    assert "submit" not in world.log.kinds()
    assert pending_jobs(world.project) == ()
