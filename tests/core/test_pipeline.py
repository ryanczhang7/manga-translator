"""`mangatl.pipeline`: the run that walks the pages and the events it emits.

Covers AC-1 (every page processed once, in ordinal order, outcome `finished`),
AC-2 (the complete ordered event stream, as a projection), AC-3 (cancellation
between stages, never inside one), AC-4 (a stage that raises), AC-5 (resume,
including PO-6's composition of AC-4 with AC-5), AC-8 (the source folder is
never written to) and AC-9 (the run is headless).

Four conventions here are load-bearing rather than stylistic:

- **The event stream is asserted as an ordered PROJECTION, never as a list of
  dataclasses** (`## Contract` PO-7). `StageFinished.elapsed_ms` is a measured
  duration, so dataclass equality would pass on this machine and fail on a
  slower one, and the fix under pressure is to stop asserting the list at all.
  `_projected` throws the duration away; `elapsed_ms` is asserted separately and
  only as "an `int` that is not negative", which is the only claim true of a
  clock.
- **The zero-stage run is exercised as well as the one-stage run.** It is what
  catches a runner that emits `StageFinished` from the page loop instead of the
  stage loop, and a runner that reads `all(... for stage in [])` as "this page
  is already done" and emits `PageSkipped` where PO-7 pins `PageStarted`.
- **Cancellation is tested with TWO stages as well as one.** A one-stage list
  cannot tell "checked between stages" from "checked between pages" - both stop
  in the same place. The two-stage test is the one that discriminates, and its
  whole assertion is the projection.
- **The `run` row is read with a plain `sqlite3` connection**, never through
  `Project`, for the reason `test_project.py` gives: a write path and a read
  path that are wrong in the same direction cannot hide from an observer that
  shares neither's assumptions.

Import layout note: `known-first-party = ["mangatl"]` in `pyproject.toml`
(MT-005 PO-9) means the single first-party block below classifies correctly even
while `mangatl.pipeline.runner` does not exist, so no RED-only `I001` is
expected here. If one appears, the MT-005 fix does not cover this case.
"""

from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import get_args

import pytest
from PySide6.QtWidgets import QApplication

from mangatl.domain.events import (
    PageSkipped,
    PageStarted,
    RunAborted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.detect_stage import DetectStage
from mangatl.pipeline.ocr_stage import OcrStage
from mangatl.pipeline.runner import RUN_ABORTED, RUN_FINISHED, RunOutcome, run_chapter
from mangatl.pipeline.stage import PageContext, PassThroughStage, Stage
from mangatl.store.intake import read_chapter
from mangatl.store.project import (
    PAGE_DONE,
    PAGE_PENDING,
    Project,
    create_project,
    open_project,
    project_dir_for,
)

# -- the fixture chapter -------------------------------------------------------

# Four pages, four distinct non-square sizes, no size another's transposition -
# the same chapter `test_project.py` uses, so a page mixed up by the runner is
# visible in the store as well as in the events.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 11),
    ("p4.png", 23, 17),
)
_PAGE_COUNT = len(_SOURCE_PAGES)

#: `PassThroughStage.name`. Pinned, because PO-7 writes the expected projection
#: out with this literal in it.
_PASSTHROUGH = "passthrough"

#: The message the injected stage failure carries. Deliberately not a substring
#: of anything else in this file, so "the reason names the error" cannot pass by
#: accident.
_BOOM = "boom-on-page-3"

# A fresh interpreter importing `mangatl.pipeline.runner` is one process start
# and one import. Measured in RED on this machine at 0.13-0.25 s over three
# spawns, and by the PO before dispatch at 0.387 s; at MT-005's observed ~3.3x
# for an instrumented CI run that is ~1.3 s. 60 s is ~46x that headroom, which
# is the right shape for a budget whose failure mode is a wedged subprocess
# rather than a slow one. Nothing about the chapter scales this, so it is a
# constant rather than an expression over the page count.
_SUBPROCESS_TIMEOUT_S = 60.0

# -- projection ----------------------------------------------------------------

_Projected = tuple[str, int | None, str | None]

_ONE_STAGE_PROJECTION: list[_Projected] = [
    ("RunStarted", None, None),
    ("PageStarted", 0, None),
    ("StageFinished", 0, _PASSTHROUGH),
    ("PageStarted", 1, None),
    ("StageFinished", 1, _PASSTHROUGH),
    ("PageStarted", 2, None),
    ("StageFinished", 2, _PASSTHROUGH),
    ("PageStarted", 3, None),
    ("StageFinished", 3, _PASSTHROUGH),
    ("RunFinished", None, None),
]

_ZERO_STAGE_PROJECTION: list[_Projected] = [
    ("RunStarted", None, None),
    ("PageStarted", 0, None),
    ("PageStarted", 1, None),
    ("PageStarted", 2, None),
    ("PageStarted", 3, None),
    ("RunFinished", None, None),
]

_RESUMED_PROJECTION: list[_Projected] = [
    ("RunStarted", None, None),
    ("PageSkipped", 0, None),
    ("PageSkipped", 1, None),
    ("PageStarted", 2, None),
    ("StageFinished", 2, _PASSTHROUGH),
    ("PageStarted", 3, None),
    ("StageFinished", 3, _PASSTHROUGH),
    ("RunFinished", None, None),
]


def _projected(events: Sequence[RunEvent]) -> list[_Projected]:
    """Each event as `(type name, ordinal or None, stage or None)`.

    The measured duration on `StageFinished` is thrown away here on purpose
    (PO-7): it is the one field of the stream that cannot be asserted as a value
    without buying a timing flake, and it is asserted separately.
    """
    return [
        (type(event).__name__, getattr(event, "ordinal", None), getattr(event, "stage", None))
        for event in events
    ]


def _of_kind[E](events: Sequence[RunEvent], kind: type[E]) -> list[E]:
    return [event for event in events if isinstance(event, kind)]


def _only[E](events: Sequence[RunEvent], kind: type[E]) -> E:
    found = _of_kind(events, kind)
    assert len(found) == 1, f"expected exactly one {kind.__name__}, got {len(found)}"
    return found[0]


# -- stage doubles -------------------------------------------------------------


class _StageExploded(Exception):
    """AC-4's injected stage failure.

    A bespoke type, so the test cannot pass by catching a real error raised
    somewhere else for another reason.
    """


class _RecordingStage:
    """A `Stage` that records the ordinals it ran and reads done-ness from the
    store.

    `is_done` asks the store the same question `PassThroughStage` asks - is this
    page's `status` the done marker - so PO-6's composition can abort with this
    stage and resume with the real one without the two disagreeing about what
    "already done" means. It is a double for `run`, not for `is_done`: the
    resume decision stays a question about persisted state, which is the whole
    of AC-5.

    **MT-036 added `done`, and it defaults to that same page-status question**,
    so every call site written before this story behaves exactly as it did. The
    override exists because MT-036 AC-5 needs two stages that disagree about
    done-ness on the *same* page - which page status cannot express, being one
    value per page (`architecture.md` §5) - and that is the state a real resume
    is in: `DetectStage.is_done` reads regions, `OcrStage.is_done` reads lines.
    """

    def __init__(
        self,
        name: str = _PASSTHROUGH,
        *,
        raise_on: int | None = None,
        on_run: Callable[[PageContext], None] | None = None,
        done: Callable[[PageContext], bool] | None = None,
    ) -> None:
        self.name = name
        self.ran: list[int] = []
        self._raise_on = raise_on
        self._on_run = on_run
        self._done = done

    def run(self, ctx: PageContext) -> None:
        self.ran.append(ctx.page.ordinal)
        if self._on_run is not None:
            self._on_run(ctx)
        if self._raise_on == ctx.page.ordinal:
            raise _StageExploded(_BOOM)

    def is_done(self, ctx: PageContext) -> bool:
        if self._done is not None:
            return self._done(ctx)
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


class _WritingStage:
    """A `Stage` whose `run` writes through `ctx.project.transaction()`.

    `Project.transaction()` is deliberately not reentrant (MT-005 PO-5), so this
    stage raises `RuntimeError` against any runner that holds a transaction open
    across the call into a stage - the shape `architecture.md` §6 forbids ("one
    transaction per page per stage") and which nothing else here would notice.
    """

    def __init__(self) -> None:
        self.name = "writing"

    def run(self, ctx: PageContext) -> None:
        with ctx.project.transaction() as cursor:
            row = cursor.execute(
                "SELECT id FROM page WHERE ordinal = ?", (ctx.page.ordinal,)
            ).fetchone()
            cursor.execute(
                "INSERT INTO region (page_id, reading_index, polygon, mask_blob, kind,"
                " confidence, merged_from) VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (int(row[0]), 0, "[[0,0]]", b"\x00mask", "bubble", 1.0),
            )

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


class _Flag:
    """A `cancelled` predicate a stage can flip while the run is in flight.

    A plain callable, which is the point of the signature: no Qt, no threading
    primitive, no queue (`## Contract`).
    """

    def __init__(self) -> None:
        self.value = False

    def raise_it(self) -> None:
        self.value = True

    def __call__(self) -> bool:
        return self.value


def _cancel_when_reaching(flag: _Flag, ordinal: int) -> Callable[[PageContext], None]:
    """A stage hook that cancels the run from *inside* the given page's stage.

    Cancelling from inside a stage is the realistic shape - the user clicks
    Cancel while a page is in flight - and it is what makes "the run stops after
    that stage completes" a claim with something to be false about.
    """

    def hook(ctx: PageContext) -> None:
        if ctx.page.ordinal == ordinal:
            flag.raise_it()

    return hook


def _never() -> bool:
    return False


def _always() -> bool:
    return True


# -- helpers -------------------------------------------------------------------


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of file contents, or None for a directory.

    The same shape as `test_intake.py`'s and `test_project.py`'s, and duplicated
    for the same reason: directories are included, over `rglob("*")`, so AC-8
    catches a *directory* appearing under the source folder as well as a file
    being created, edited or removed.
    """
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


def _build_source(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    pages: Sequence[tuple[str, int, int]] = _SOURCE_PAGES,
) -> Path:
    """Write the fixture scans into a fresh `scans/` folder under `tmp_path`.

    A subfolder rather than `tmp_path` itself, so `<source>.mtproj` and
    `<source>_en` are also inside `tmp_path` and the test leaves nothing outside
    its own directory.
    """
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for filename, width, height in pages:
        (source_dir / filename).write_bytes(png_bytes(width, height))
    return source_dir


def _new_project(source_dir: Path) -> Project:
    return create_project(read_chapter(source_dir), project_dir_for(source_dir))


def _reopened(project_dir: Path) -> Project:
    """Open the project from its path, the way a second process would.

    Named rather than inlined so PO-6's "a fresh call, not a resumed object" is
    legible at the call site.
    """
    return open_project(project_dir)


def _raw(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    """Read the project file with a plain `sqlite3` connection.

    Deliberately not through `Project`: the `run` row is where AC-1's "ends with
    outcome `finished`" is asserted a second time, and an observer that shares
    the store's assumptions is not a second place.
    """
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _open_run(project: Project) -> int:
    """A real `run` row, for MT-044 C-1's `PageContext.run_id`.

    The runner opens its own, so this exists only for the two tests below that
    build a context by hand. Raw SQL through `project.transaction()`, the same
    convention `_mark_done` follows and for its reason: this story ships no
    "start a run" helper on `Project` and the test must not invent one.
    """
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-09-21T09:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


def _mark_done(project: Project, *ordinals: int) -> None:
    """Set `page.status` to the done marker, the way a finished run leaves it.

    Raw SQL through `project.transaction()`, the convention `test_project.py`
    set for a stage-shaped write: this story ships no "mark a page done" helper
    and the test must not invent one.
    """
    with project.transaction() as cursor:
        for ordinal in ordinals:
            cursor.execute("UPDATE page SET status = ? WHERE ordinal = ?", (PAGE_DONE, ordinal))


def _statuses(project: Project) -> list[str]:
    return [project.page_status(ordinal) for ordinal in range(_PAGE_COUNT)]


def _run(
    project: Project,
    stages: Sequence[Stage],
    cancelled: Callable[[], bool] = _never,
) -> tuple[list[RunEvent], RunOutcome]:
    events: list[RunEvent] = []
    outcome = run_chapter(project, stages, events.append, cancelled)
    return events, outcome


# -- the events themselves: AC-2's vocabulary, and PO-4's "data, no methods" ----


def test_every_event_carries_exactly_the_fields_the_contract_names() -> None:
    started = RunStarted(run_id=1, page_count=4)
    page = PageStarted(ordinal=2)
    stage = StageFinished(ordinal=2, stage=_PASSTHROUGH, elapsed_ms=0)
    skipped = PageSkipped(ordinal=0, reason="already done")
    aborted = RunAborted(reason="cancelled", ordinal=None)
    finished = RunFinished(run_id=1, pages_done=4)

    assert (started.run_id, started.page_count) == (1, 4)
    assert page.ordinal == 2
    assert (stage.ordinal, stage.stage, stage.elapsed_ms) == (2, _PASSTHROUGH, 0)
    assert (skipped.ordinal, skipped.reason) == (0, "already done")
    assert (aborted.reason, aborted.ordinal) == ("cancelled", None)
    assert (finished.run_id, finished.pages_done) == (1, 4)


def test_an_event_cannot_be_mutated_after_it_is_emitted() -> None:
    # Frozen because MT-015 hands this stream to a UI thread, and a consumer
    # that can rewrite an ordinal is a consumer that can rewrite history.
    # `## Contract` PO-4 forbids anything else on these classes - no methods, no
    # `__post_init__`, no validation - because `domain` carries a 100%
    # line-and-branch bar and a defensive branch no test reaches fails it.
    event = PageStarted(ordinal=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.ordinal = 2  # type: ignore[misc]


def test_the_run_event_union_names_all_six_event_types_and_no_others() -> None:
    assert set(get_args(RunEvent)) == {
        RunStarted,
        PageStarted,
        StageFinished,
        PageSkipped,
        RunAborted,
        RunFinished,
    }


# -- AC-1: every page once, in ordinal order, ending `finished` ----------------


def test_every_page_is_processed_once_and_in_ordinal_order(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    stage = _RecordingStage()

    with _new_project(source_dir) as project:
        _, outcome = _run(project, [stage])

    assert stage.ran == [0, 1, 2, 3]
    assert outcome.outcome == RUN_FINISHED
    assert outcome.pages_done == _PAGE_COUNT
    assert outcome.aborted_reason is None


def test_a_finished_run_records_outcome_finished_on_its_own_run_row(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # AC-1's "ends with outcome `finished`" is one value in two places
    # (`## Contract` PO-2): the returned `RunOutcome` and the `run` row. This is
    # the second place, read with a connection that knows nothing of `Project`.
    source_dir = _build_source(tmp_path, png_bytes)
    db_path = project_dir_for(source_dir) / "project.db"

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [PassThroughStage()])

    rows = _raw(db_path, "SELECT id, ended_at, outcome, aborted_reason FROM run")
    assert len(rows) == 1
    run_id, ended_at, db_outcome, db_reason = rows[0]
    assert int(run_id) == outcome.run_id == _only(events, RunStarted).run_id
    assert db_outcome == RUN_FINISHED == outcome.outcome
    assert db_reason is None
    assert ended_at is not None, "a finished run left `run.ended_at` NULL"


def test_a_finished_run_leaves_every_page_marked_done(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        assert _statuses(project) == [PAGE_PENDING] * _PAGE_COUNT
        _run(project, [PassThroughStage()])
        assert _statuses(project) == [PAGE_DONE] * _PAGE_COUNT


# -- AC-2: the complete ordered event stream ----------------------------------


def test_a_four_page_one_stage_run_emits_exactly_the_stream_the_contract_pins(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [PassThroughStage()])

    assert _projected(events) == _ONE_STAGE_PROJECTION
    assert _only(events, RunStarted).page_count == _PAGE_COUNT
    finished = _only(events, RunFinished)
    assert (finished.run_id, finished.pages_done) == (outcome.run_id, _PAGE_COUNT)


def test_a_zero_stage_run_starts_every_page_and_finishes_none_of_its_stages(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # The case that catches a runner emitting `StageFinished` from the page loop
    # rather than the stage loop, and a runner reading `all(stage.is_done(...)
    # for stage in [])` as "this page is already done" and emitting
    # `PageSkipped` where PO-7 pins `PageStarted`.
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [])

    assert _projected(events) == _ZERO_STAGE_PROJECTION
    assert outcome.outcome == RUN_FINISHED
    assert _only(events, RunFinished).pages_done == _PAGE_COUNT


def test_a_single_page_chapter_emits_one_page_started_and_one_stage_finished(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes, pages=_SOURCE_PAGES[:1])

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [PassThroughStage()])

    assert _projected(events) == [
        ("RunStarted", None, None),
        ("PageStarted", 0, None),
        ("StageFinished", 0, _PASSTHROUGH),
        ("RunFinished", None, None),
    ]
    assert outcome.pages_done == 1


def test_every_stage_finished_carries_a_non_negative_integer_duration(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # PO-7: never a value and never an upper bound. `>= 0` is not a weakened
    # assertion, it is the only one true of a clock - and `bool` is excluded
    # explicitly because `isinstance(True, int)` is `True`, so a runner emitting
    # a flag where a duration belongs would otherwise pass.
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        events, _ = _run(project, [PassThroughStage()])

    durations = [event.elapsed_ms for event in _of_kind(events, StageFinished)]
    assert len(durations) == _PAGE_COUNT
    wrong = [value for value in durations if type(value) is not int or value < 0]
    assert wrong == [], f"elapsed_ms must be a non-negative int; offenders: {wrong}"


def test_no_event_names_a_page_that_is_not_in_the_chapter(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        events, _ = _run(project, [PassThroughStage()])

    named = {ordinal for _, ordinal, _ in _projected(events) if ordinal is not None}
    assert named == set(range(_PAGE_COUNT))


# -- AC-3: cancellation, between stages and never inside one ------------------


def test_cancelling_during_page_two_stops_the_run_once_that_stage_completes(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    flag = _Flag()
    stage = _RecordingStage(on_run=_cancel_when_reaching(flag, 1))

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [stage], cancelled=flag)
        statuses = _statuses(project)

    assert _projected(events) == [
        ("RunStarted", None, None),
        ("PageStarted", 0, None),
        ("StageFinished", 0, _PASSTHROUGH),
        ("PageStarted", 1, None),
        ("StageFinished", 1, _PASSTHROUGH),
        ("RunAborted", None, None),
    ]
    assert stage.ran == [0, 1], "a cancelled run started a page it should never have reached"
    assert statuses == [PAGE_DONE, PAGE_DONE, PAGE_PENDING, PAGE_PENDING]
    assert outcome.outcome == RUN_ABORTED
    assert outcome.pages_done == 2


def test_a_cancel_names_no_page_because_no_page_is_at_fault(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # `RunAborted.ordinal` is `None` for a cancel and the failing page's ordinal
    # for an error. That distinction is the whole of what MT-018 shows the user,
    # so it is asserted on its own rather than folded into the projection.
    source_dir = _build_source(tmp_path, png_bytes)
    flag = _Flag()
    stage = _RecordingStage(on_run=_cancel_when_reaching(flag, 1))

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [stage], cancelled=flag)

    aborted = _only(events, RunAborted)
    assert aborted.ordinal is None
    assert aborted.reason == "cancelled"
    assert outcome.aborted_reason == "cancelled"


def test_cancelling_during_a_pages_first_stage_does_not_run_its_second(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # The discriminating case. With one stage per page, "checked between stages"
    # and "checked between pages" stop in exactly the same place; with two, a
    # runner that only checks between pages runs `beta` on page 2 and this
    # projection grows a `("StageFinished", 1, "beta")` row.
    source_dir = _build_source(tmp_path, png_bytes)
    flag = _Flag()
    alpha = _RecordingStage("alpha", on_run=_cancel_when_reaching(flag, 1))
    beta = _RecordingStage("beta")

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [alpha, beta], cancelled=flag)
        statuses = _statuses(project)

    assert _projected(events) == [
        ("RunStarted", None, None),
        ("PageStarted", 0, None),
        ("StageFinished", 0, "alpha"),
        ("StageFinished", 0, "beta"),
        ("PageStarted", 1, None),
        ("StageFinished", 1, "alpha"),
        ("RunAborted", None, None),
    ]
    assert beta.ran == [0], "cancellation was checked between pages, not between stages"
    assert statuses == [PAGE_DONE, PAGE_PENDING, PAGE_PENDING, PAGE_PENDING]
    assert outcome.pages_done == 1


def test_a_run_cancelled_before_it_starts_touches_no_page_at_all(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    stage = _RecordingStage()

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [stage], cancelled=_always)
        statuses = _statuses(project)

    assert _projected(events) == [("RunStarted", None, None), ("RunAborted", None, None)]
    assert stage.ran == []
    assert statuses == [PAGE_PENDING] * _PAGE_COUNT
    assert (outcome.outcome, outcome.pages_done) == (RUN_ABORTED, 0)


# -- AC-4: a stage that raises ------------------------------------------------


def test_a_stage_that_raises_on_page_three_aborts_naming_that_page_and_the_error(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    stage = _RecordingStage(raise_on=2)

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [stage])
        statuses = _statuses(project)

    aborted = _only(events, RunAborted)
    assert aborted.ordinal == 2, "an error abort must name the failing page, not None"
    assert _BOOM in aborted.reason, f"the abort reason does not name the error: {aborted.reason!r}"
    assert outcome.outcome == RUN_ABORTED
    assert outcome.aborted_reason == aborted.reason
    assert stage.ran == [0, 1, 2], "the run carried on past the page that raised"
    assert statuses == [PAGE_DONE, PAGE_DONE, PAGE_PENDING, PAGE_PENDING]
    assert outcome.pages_done == 2


def test_a_stage_that_raises_leaves_the_pages_before_it_complete_and_persisted(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # Read back through a plain connection after the project is closed, not from
    # the object the run held: an implementation that never wrote the status
    # through would pass a same-object assertion (`test_project.py`'s second
    # convention).
    source_dir = _build_source(tmp_path, png_bytes)
    db_path = project_dir_for(source_dir) / "project.db"

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [_RecordingStage(raise_on=2)])

    assert _raw(db_path, "SELECT ordinal, status FROM page ORDER BY ordinal") == [
        (0, PAGE_DONE),
        (1, PAGE_DONE),
        (2, PAGE_PENDING),
        (3, PAGE_PENDING),
    ]

    run_rows = _raw(db_path, "SELECT ended_at, outcome, aborted_reason FROM run")
    assert len(run_rows) == 1
    ended_at, db_outcome, db_reason = run_rows[0]
    assert db_outcome == RUN_ABORTED == outcome.outcome
    assert db_reason == _only(events, RunAborted).reason
    assert ended_at is not None, "an aborted run left `run.ended_at` NULL"


def test_a_stage_that_raises_does_not_let_the_exception_escape_the_runner(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # AC-4 says the run *emits* `RunAborted`. A runner that lets the stage's
    # exception propagate emits nothing at all, and MT-015's worker thread would
    # die with the progress readout stuck on page 3 forever.
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [_RecordingStage(raise_on=2)])

    assert outcome.outcome == RUN_ABORTED
    assert len(_of_kind(events, RunAborted)) == 1


# -- AC-5: resume ------------------------------------------------------------


def test_pages_already_done_are_skipped_and_work_begins_at_the_first_that_is_not(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    stage = _RecordingStage()

    with _new_project(source_dir) as project:
        _mark_done(project, 0, 1)
        events, outcome = _run(project, [stage])

    assert _projected(events) == _RESUMED_PROJECTION
    assert stage.ran == [2, 3], "a page that was already done was processed again"
    assert outcome.pages_done == _PAGE_COUNT


def test_a_skip_carries_a_reason_the_user_could_be_shown(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        _mark_done(project, 0, 1)
        events, _ = _run(project, [PassThroughStage()])

    reasons = [event.reason for event in _of_kind(events, PageSkipped)]
    assert len(reasons) == 2
    assert all(isinstance(reason, str) and reason.strip() for reason in reasons)


def test_a_fresh_run_after_an_abort_resumes_at_the_page_that_failed(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # PO-6: EPIC-02's done-when, composed. AC-4 covers the abort and AC-5 covers
    # the skip; nothing else asserts the two together, which is the behaviour
    # the epic actually promises. The process boundary is the one thing an
    # in-process test cannot have, and MT-005's AC-5 already proved the store
    # survives an injected failure - so this is the epic's sentence minus the
    # kill, and an `os._exit` here would prove nothing extra.
    source_dir = _build_source(tmp_path, png_bytes)
    project_dir = project_dir_for(source_dir)

    with _new_project(source_dir) as project:
        first_events, first = _run(project, [_RecordingStage(raise_on=2)])

    assert first.outcome == RUN_ABORTED
    assert _only(first_events, RunAborted).ordinal == 2

    # A fresh call on a freshly opened project. The only thing carried across is
    # what the store holds.
    with _reopened(project_dir) as project:
        second_stage = _RecordingStage()
        second_events, second = _run(project, [second_stage])

    assert _projected(second_events) == _RESUMED_PROJECTION
    assert second_stage.ran == [2, 3], "the resumed run re-did work the first run had paid for"
    assert second.outcome == RUN_FINISHED
    assert second.pages_done == _PAGE_COUNT

    runs = _raw(project_dir / "project.db", "SELECT id, outcome FROM run ORDER BY id")
    assert [row[1] for row in runs] == [RUN_ABORTED, RUN_FINISHED]
    assert {int(row[0]) for row in runs} == {first.run_id, second.run_id}
    assert first.run_id != second.run_id, "the resumed run reused the aborted run's row"


# -- MT-036 AC-5: `is_done` is per stage per page ------------------------------
#
# MEASURED AT PLANNING, 2026-09-17, and reproduced by this file's own red run:
# the runner consults `is_done` **only** in the page-level `all(...)` check and
# then runs every stage unconditionally. So `Stage`'s own docstring - "`is_done`
# is per stage per page ... a page that has regions but no translations resumes
# at translation" - is a claim no code makes true, and MT-036 C-4 makes it true.
#
# The trap C-4 records, and the reason these tests are written the way they are:
# the obvious implementation *replaces* the page-level skip with a per-stage one,
# which satisfies AC-5 and breaks `_RESUMED_PROJECTION` above and
# `tests/core/test_detect_stage.py`'s "a fully detected page is skipped rather
# than started". **Both behaviours, not one replacing the other** - so the last
# two tests in this section pin the page-level skip and the cancel boundary from
# the other side, with stages whose done-ness is NOT page status.

#: Four pages, a `detect` stage already done on every one of them and an `ocr`
#: stage done on none. Every page is started - it is not fully done - and only
#: the stage with work to do reports a `StageFinished`. PO-6: a skipped stage
#: emits no event at all, because `StageFinished.elapsed_ms` is a *measured*
#: duration and emitting one for work that did not happen would be a lie.
_PER_STAGE_SKIP_PROJECTION: list[_Projected] = [
    ("RunStarted", None, None),
    ("PageStarted", 0, None),
    ("StageFinished", 0, "ocr"),
    ("PageStarted", 1, None),
    ("StageFinished", 1, "ocr"),
    ("PageStarted", 2, None),
    ("StageFinished", 2, "ocr"),
    ("PageStarted", 3, None),
    ("StageFinished", 3, "ocr"),
    ("RunFinished", None, None),
]

#: Four pages on which every stage reports itself done, while `page.status` is
#: still pending. The page-level skip is what produces this, and nothing else
#: can: a per-stage skip alone would emit `PageStarted` for all four.
_ALL_STAGES_DONE_PROJECTION: list[_Projected] = [
    ("RunStarted", None, None),
    ("PageSkipped", 0, None),
    ("PageSkipped", 1, None),
    ("PageSkipped", 2, None),
    ("PageSkipped", 3, None),
    ("RunFinished", None, None),
]


class _SeededDetector:
    """A `PageDetector` that records which page it was asked about.

    `PageDetector` is handed bytes, not an ordinal, so the ordinal is recovered
    through an index of the fixture scans - which is only possible because the
    four fixture pages have four distinct sizes and therefore four distinct
    encodings. That is the same property `_SOURCE_PAGES` was chosen for.
    """

    def __init__(self, index: dict[bytes, int], mask: bytes) -> None:
        self._index = index
        self._mask = mask
        self.pages: list[int] = []

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        ordinal = self._index[image_bytes]
        self.pages.append(ordinal)
        return (_region(self._mask, 50, 50),)


class _SeededTranscriber:
    """A `PageTranscriber` that records the page and how many regions it saw."""

    def __init__(self, index: dict[bytes, int]) -> None:
        self._index = index
        self.pages: list[int] = []
        self.region_counts: list[int] = []

    def __call__(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
        self.pages.append(self._index[image_bytes])
        self.region_counts.append(len(regions))
        return tuple(OcrResult(text=f"line-{index}") for index in range(len(regions)))


def _region(mask: bytes, x: int, y: int) -> RawRegion:
    """A closed-ring square region with its top-left corner at `(x, y)`."""
    ring = ((x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4), (x, y))
    return RawRegion(polygon=ring, mask=mask, confidence=1.0, kind="bubble")


def _page_index(source_dir: Path) -> dict[bytes, int]:
    return {
        (source_dir / filename).read_bytes(): ordinal
        for ordinal, (filename, _width, _height) in enumerate(_SOURCE_PAGES)
    }


def _done(ctx: PageContext) -> bool:
    return True


def _not_done(ctx: PageContext) -> bool:
    return False


def test_a_stage_that_is_already_done_for_a_page_is_neither_run_nor_reported(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-5**, at the runner, with two stages that disagree about done-ness.

    This is the shape a real resume is in and the shape page status cannot
    express: `detect` has already written its regions, `ocr` has written no
    lines, and the page as a whole is not done. The stage with nothing to do
    must not be run and - PO-6 - must not report a `StageFinished` it did not
    earn.
    """
    source_dir = _build_source(tmp_path, png_bytes)
    detect = _RecordingStage("detect", done=_done)
    ocr = _RecordingStage("ocr", done=_not_done)

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [detect, ocr])
        statuses = _statuses(project)

    assert detect.ran == [], (
        f"the detect stage ran on pages {detect.ran} that it reported itself already"
        " done for; is_done is per stage per page (C-4), and on a real chapter each"
        " of those is a GPU inference the user already paid for"
    )
    assert ocr.ran == [0, 1, 2, 3], "the stage with work to do was skipped as well"
    assert _projected(events) == _PER_STAGE_SKIP_PROJECTION
    assert outcome.outcome == RUN_FINISHED
    assert outcome.pages_done == _PAGE_COUNT
    # C-4 clause 4: `_mark_done` still runs at the end of a page that was not
    # page-skipped, even though one of its two stages never ran.
    assert statuses == [PAGE_DONE] * _PAGE_COUNT


def test_a_page_interrupted_after_detection_resumes_into_ocr_without_detecting_again(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> None:
    """**AC-5**, in the words the criterion is written in, with the real stages.

    Page 0's regions are already in the store - the state a run killed between
    detection and OCR leaves behind - and no page is marked done. `DetectStage`
    reads its done-ness off the regions (MT-035 C-6) and `OcrStage` reads its
    own off the lines (MT-010), so the two genuinely disagree about page 0 and
    nothing here has to stub `is_done` to make them.

    The store is the second observer: page 0's regions must be the *seeded*
    ones afterwards. A detector that ran anyway would replace them with its own
    and the region count alone would not notice.
    """
    source_dir = _build_source(tmp_path, png_bytes)
    mask = one_bit_png(8, 8, [(0, 0, 4, 4)])
    seeded = (_region(mask, 100, 100), _region(mask, 200, 200))
    index = _page_index(source_dir)
    detector = _SeededDetector(index, mask)
    transcriber = _SeededTranscriber(index)

    with _new_project(source_dir) as project:
        project.write_regions(0, seeded)
        stages = [DetectStage(detect=detector), OcrStage(transcribe=transcriber)]
        events, outcome = _run(project, stages)
        regions_on_page_zero = project.read_regions(0)
        lines_on_page_zero = project.read_lines(0)

    assert detector.pages == [1, 2, 3], (
        f"the detector ran on pages {detector.pages}; page 0 already had regions,"
        " so AC-5 says detection is skipped there and nowhere else"
    )
    assert transcriber.pages == [0, 1, 2, 3], (
        f"the transcriber ran on pages {transcriber.pages}; AC-5 says OCR is *not*"
        " skipped on the page whose detection was already done"
    )
    assert transcriber.region_counts[0] == len(seeded), (
        "the transcriber was handed the wrong number of regions for page 0, so it"
        " did not transcribe what the interrupted run had detected"
    )
    assert regions_on_page_zero == seeded, "the skipped detect stage rewrote the page anyway"
    assert [result.text for result in lines_on_page_zero] == ["line-0", "line-1"]
    assert _projected(events) == [
        ("RunStarted", None, None),
        ("PageStarted", 0, None),
        ("StageFinished", 0, "ocr"),
        ("PageStarted", 1, None),
        ("StageFinished", 1, "detect"),
        ("StageFinished", 1, "ocr"),
        ("PageStarted", 2, None),
        ("StageFinished", 2, "detect"),
        ("StageFinished", 2, "ocr"),
        ("PageStarted", 3, None),
        ("StageFinished", 3, "detect"),
        ("StageFinished", 3, "ocr"),
        ("RunFinished", None, None),
    ]
    assert outcome.outcome == RUN_FINISHED


def test_a_page_every_stage_of_which_is_done_is_skipped_before_it_is_started(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**C-4 clause 2**, from the side `_RESUMED_PROJECTION` cannot see.

    Every existing resume test in this file marks `page.status` done, so the
    page-level skip and a per-stage skip would agree there. Here the page status
    is untouched and the *stages* report themselves done, which is what the real
    stages do after this story - and a runner that replaced the page-level
    `all(...)` check with a per-stage one emits four `PageStarted` events instead
    of four `PageSkipped` ones. That is the regression C-4 exists to prevent and
    it is the one this suite would otherwise meet in
    `tests/core/test_detect_stage.py` rather than here.
    """
    source_dir = _build_source(tmp_path, png_bytes)
    detect = _RecordingStage("detect", done=_done)
    ocr = _RecordingStage("ocr", done=_done)

    with _new_project(source_dir) as project:
        events, outcome = _run(project, [detect, ocr])
        statuses = _statuses(project)

    assert _projected(events) == _ALL_STAGES_DONE_PROJECTION
    assert (detect.ran, ocr.ran) == ([], [])
    assert outcome.pages_done == _PAGE_COUNT
    # A page-skipped page is not marked done by this run: it is done already,
    # whoever did it, and `_mark_done` is for pages this run walked (C-4).
    assert statuses == [PAGE_PENDING] * _PAGE_COUNT


def test_the_cancel_check_is_consulted_for_a_stage_even_when_that_stage_is_skipped(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**C-4 clause 3**: the cancel boundary does not move.

    `runner.py`'s own docstring says `cancelled()` is consulted at the top of
    the page loop and at the top of the stage loop *and nowhere else*, and the
    per-stage skip goes **after** it. Counting the consultations is the only
    thing that can tell the two orderings apart: the event stream, the store and
    the outcome are identical either way, because a cancel and a skip both end
    with the stage not running.

    Four pages, two stages, every page started: four page-loop checks and eight
    stage-loop checks. If the skip were hoisted above the check, the four
    skipped stages would never consult it and the count would be eight.
    """
    source_dir = _build_source(tmp_path, png_bytes)
    consultations: list[None] = []

    def counting_cancelled() -> bool:
        consultations.append(None)
        return False

    stages = [_RecordingStage("detect", done=_done), _RecordingStage("ocr", done=_not_done)]

    with _new_project(source_dir) as project:
        _, outcome = _run(project, stages, counting_cancelled)

    assert outcome.outcome == RUN_FINISHED
    assert len(consultations) == _PAGE_COUNT + _PAGE_COUNT * len(stages), (
        f"cancelled() was consulted {len(consultations)} times for {_PAGE_COUNT} pages"
        f" of {len(stages)} stages. Once per page and once per stage is"
        f" {_PAGE_COUNT + _PAGE_COUNT * len(stages)}; {_PAGE_COUNT + _PAGE_COUNT} means"
        " the is_done check was hoisted above the cancel check and the cancel"
        " boundary moved (C-4 clause 3)"
    )


# -- the pass-through stage: the identity element ------------------------------


def test_the_pass_through_stage_is_named_in_the_events_it_produces() -> None:
    assert PassThroughStage().name == _PASSTHROUGH


def test_the_pass_through_stage_asks_the_store_whether_a_page_is_already_done(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # The mechanism AC-5 rests on: `is_done` is per stage per page and is a
    # question about persisted state, not about anything the runner is holding
    # in memory.
    source_dir = _build_source(tmp_path, png_bytes)
    stage = PassThroughStage()

    with _new_project(source_dir) as project:
        pages = project.pages()
        run_id = _open_run(project)
        assert stage.is_done(PageContext(project=project, page=pages[0], run_id=run_id)) is False
        _mark_done(project, 0)
        assert stage.is_done(PageContext(project=project, page=pages[0], run_id=run_id)) is True
        assert stage.is_done(PageContext(project=project, page=pages[1], run_id=run_id)) is False


def test_the_pass_through_stage_writes_nothing_of_its_own(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    db_path = project_dir_for(source_dir) / "project.db"

    with _new_project(source_dir) as project:
        page = project.pages()[0]
        context = PageContext(project=project, page=page, run_id=_open_run(project))
        assert PassThroughStage().run(context) is None
        assert project.page_status(0) == PAGE_PENDING

    assert _raw(db_path, "SELECT id FROM region") == []


def test_a_stage_may_open_its_own_transaction_while_the_runner_drives_it(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # `architecture.md` §6: one transaction per page per stage, and the stage
    # owns it. `Project.transaction()` refuses to nest, so a runner holding one
    # open across the call into `stage.run` turns every real stage into a
    # `RuntimeError` - a failure this suite would otherwise meet for the first
    # time in MT-007.
    source_dir = _build_source(tmp_path, png_bytes)
    db_path = project_dir_for(source_dir) / "project.db"

    with _new_project(source_dir) as project:
        _, outcome = _run(project, [_WritingStage()])

    assert outcome.outcome == RUN_FINISHED
    assert len(_raw(db_path, "SELECT page_id FROM region")) == _PAGE_COUNT


# -- AC-8: the source folder is read, never written ---------------------------


def test_a_whole_run_creates_modifies_and_deletes_nothing_in_the_source_folder(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        before = _snapshot(source_dir)
        # The non-emptiness this AC depends on: a hash comparison over an empty
        # or mis-rooted file list would be satisfied vacuously.
        assert sum(1 for value in before.values() if value is not None) == _PAGE_COUNT
        _run(project, [PassThroughStage()])
        after = _snapshot(source_dir)

    assert after == before


def test_a_run_that_aborts_also_leaves_the_source_folder_untouched(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    with _new_project(source_dir) as project:
        before = _snapshot(source_dir)
        assert sum(1 for value in before.values() if value is not None) == _PAGE_COUNT
        _run(project, [_RecordingStage(raise_on=2)])
        after = _snapshot(source_dir)

    assert after == before


# -- AC-9: the run is headless ------------------------------------------------


def test_a_whole_run_executes_with_no_qt_application_in_existence(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # Mechanism 1 of `## Contract` PO-3. NOT "PySide6 is absent from
    # sys.modules": `pytest-qt` loads 18 PySide6 modules at plugin load for
    # every pytest session, including a Qt-free file under `tests/core`
    # (measured by the PO before dispatch, re-measured in RED: 18 modules,
    # `pytestqt loaded: True`). What is measurably false here and measurably
    # true under `tests/ui` is that a QApplication has been *constructed*.
    #
    # ORDER-DEPENDENT, measured in RED: `QApplication.instance()` is `None`
    # under `pytest tests/core tests/ui` - the order every gate command in
    # project.conf uses - and is NOT None under `pytest tests/ui tests/core`,
    # because pytest-qt's application outlives the suite that built it. That is
    # exactly what makes the assertion discriminate rather than be trivially
    # true everywhere, and it is why the subprocess test below exists as the
    # order-independent half.
    source_dir = _build_source(tmp_path, png_bytes)
    seen: list[object] = []

    assert QApplication.instance() is None, (
        "a QApplication already existed before this run; if `tests/ui` now runs"
        " first, fix the ordering rather than deleting this assertion"
    )
    with _new_project(source_dir) as project:
        stage = _RecordingStage(on_run=lambda _ctx: seen.append(QApplication.instance()))
        events, outcome = _run(project, [stage])

    assert seen == [None] * _PAGE_COUNT, "the run constructed a Qt application object"
    assert QApplication.instance() is None
    assert _projected(events) == _ONE_STAGE_PROJECTION
    assert outcome.outcome == RUN_FINISHED


def test_a_fresh_interpreter_importing_the_runner_loads_no_pyside_module() -> None:
    # Mechanism 2 of `## Contract` PO-3, and exactly one such test: measured at
    # 0.387 s per spawn by the PO and 0.13-0.25 s in RED on this machine, which
    # is ~1.3 s instrumented on CI. One is affordable; one per module is not.
    #
    # Not redundant with `lint-imports` contract 3: that contract forbids
    # importing OUR `ui` package, and this catches an import of Qt by any route
    # at all - a stage reaching for `QImage` to decode a page, say.
    program = (
        "import sys;"
        " import mangatl.pipeline.runner;"
        " print(len([m for m in sys.modules"
        " if m == 'PySide6' or m.startswith('PySide6.')]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
        check=False,
    )

    assert result.returncode == 0, f"the import itself failed:\n{result.stderr}"
    assert result.stdout.strip() == "0", (
        f"the runner pulled PySide6 in:\n{result.stdout}\n{result.stderr}"
    )
