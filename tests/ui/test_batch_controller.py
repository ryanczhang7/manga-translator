"""MT-113 C-3 and AC-2, AC-6: `ui.run.BatchController`, the batch run off the GUI
thread and the wait on a timer.

`start()` with a models folder runs `BatchSetup.submit` on a worker; a
`BatchSubmitted` among its events begins the wait (`waiting`, once, with a
`WaitingState`) and arms a **single-shot** `poll_timer` of
`BATCH_POLL_SECONDS * 1000` ms. Each time it fires, a worker asks
`BatchSetup.collect` for every pending job's answer; a job still pending
re-arms the timer, no job pending ends the run `collected`, a `BatchFailed`
ends it `failed` with no re-arm, and a poll that raises is reported on
`poll_failed` (Contract C-3 as amended in RED, A-R1) and re-arms. `start()`
with no models folder is the reopen: the wait at once from `pending_jobs`,
the first poll immediately. `stop()` stops the timer and joins a worker in
flight, and cancels nothing at the provider.

**The time is never waited for.** The timer is "fired" by `_elapse`: it
asserts the timer is armed, stops it and emits its `timeout` - exactly what
Qt does when the interval elapses, sixty seconds sooner. A controller that
stopped re-arming leaves the timer inactive, and `_elapse` and DV-1's
assertion (`test_a_poll_that_leaves_a_job_pending_arms_the_timer_again`) say
so by name.

**Fakes, not the network.** `FakeSubmit` stands where
`compose.build_batch_submit`'s closure stands: it records a `run` row and the
jobs through the real `store.batch.record_submission` on the project it is
handed, and emits what `submit_chapter` would. `FakeCollect` stands where
`partial(collect_volume, ...)` stands: it answers each job from a plan,
writing through the real `mark_collected` / `mark_failed`, so `pending_jobs`
- which the controller reads - is the real store's answer.

**Threads.** Every wait is a bounded `qtbot.waitUntil`; a gated fake gives up
after `GATE_S`. The `world` fixture releases every gate and stops every
controller, so no worker outlives its test. A fake submit or poll is a few
sqlite writes on a tiny project: milliseconds, so `WAIT_MS` is liveness
headroom, not a cost estimate (measured: see the story's handoff).

**RED:** `BatchController`, `BatchSetup`, `WaitingState` and
`BATCH_POLL_SECONDS` are reached through `_run()`, so the file collects and
every test fails on the named absence.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Slot
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import mangatl.ui.run as run_module
from mangatl.domain.batch import BatchJob, BatchJobState, BatchResults
from mangatl.domain.budget import Projection
from mangatl.domain.events import (
    BatchCollected,
    BatchFailed,
    BatchSubmitted,
    BatchWaiting,
    CallPriced,
    RunAborted,
    RunEvent,
    RunStarted,
)
from mangatl.domain.money import Usd
from mangatl.pipeline.runner import BUDGET
from mangatl.store.batch import mark_collected, mark_failed, pending_jobs, record_submission
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for
from mangatl.ui import tokens_gen
from mangatl.ui.run import RunSetup

#: Liveness bound for a worker to finish a fake submit or poll.
WAIT_MS = 10_000
#: How long a gated fake blocks before giving up.
GATE_S = 10.0
#: How long the gate in the stop tests holds a poll in flight after `stop()`
#: is called, so a `stop()` that does not join returns visibly before it.
HOLD_S = 0.3

#: The controller's injected clock.
NOW = datetime(2026, 11, 4, 15, 7, tzinfo=UTC)
MODEL = "gemini-3.1-pro-preview"


def usd(text: str) -> Usd:
    return Usd(Decimal(text))


VOLUME = Projection(
    next_call=usd("0.06"), remaining_chapter=usd("0.06"), basis="estimate", sample_count=0
)
CEILING = usd("1.50")
#: MT-141: a failed consistency pass, as `_run_postlude` reports one.
PASS_REASON = "RuntimeError: the consistency call returned nothing"


def _run() -> Any:
    """`mangatl.ui.run`, for the names this story adds to it."""
    return run_module


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# Folders, projects and jobs
# =============================================================================


def _png() -> bytes:
    image = QImage(QSize(30, 40), QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def _project(tmp_path: Path, pages: int = 3) -> Path:
    folder = tmp_path / "ch"
    folder.mkdir()
    png = _png()
    for index in range(pages):
        (folder / f"{index + 1:02d}.png").write_bytes(png)
    project_dir = project_dir_for(folder.resolve())
    with create_project(read_chapter(folder.resolve()), project_dir):
        pass
    return project_dir


def _insert_run(project: Project) -> int:
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-11-04T14:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


def _record(project: Project, ranges: Sequence[tuple[int, int]]) -> tuple[int, ...]:
    run_id = _insert_run(project)
    return tuple(
        record_submission(project, run_id, f"batches/{chr(ord('a') + k)}", MODEL, first, last)
        for k, (first, last) in enumerate(ranges)
    )


def _pending(project_dir: Path) -> tuple[BatchJob, ...]:
    with open_project(project_dir) as project:
        return pending_jobs(project)


def _stamp(project_dir: Path, job_id: int, submitted_at: str) -> None:
    with open_project(project_dir) as project, project.transaction() as cursor:
        cursor.execute("UPDATE batch_job SET submitted_at = ? WHERE id = ?", (submitted_at, job_id))


# =============================================================================
# Fakes
# =============================================================================


@dataclass
class FakeSubmit:
    """A `ChapterSubmit`: `(project, models_dir, emit, cancelled) -> job ids`."""

    ranges: tuple[tuple[int, int], ...] = ((0, 2),)
    refuse: bool = False
    calls: list[tuple[Path, bool]] = field(default_factory=list)

    def __call__(
        self,
        project: Project,
        models_dir: Path,
        emit: Callable[[RunEvent], None],
        cancelled: Callable[[], bool],
    ) -> tuple[int, ...]:
        self.calls.append((models_dir, threading.current_thread() is threading.main_thread()))
        pages = len(project.pages())
        run_id = _insert_run(project)
        emit(RunStarted(run_id=run_id, page_count=pages))
        if self.refuse:
            emit(CallPriced(ordinal=None, spent=usd("0"), ceiling=usd("0.05"), projection=VOLUME))
            emit(RunAborted(reason=BUDGET, ordinal=None))
            return ()
        ids = tuple(
            record_submission(project, run_id, f"batches/{k}", MODEL, first, last)
            for k, (first, last) in enumerate(self.ranges)
        )
        emit(BatchSubmitted(run_id=run_id, job_ids=ids, page_count=pages, projection=VOLUME))
        return ids


class FakeCollect:
    """`(project, job, emit) -> BatchAnswer`, one job one poll, from a plan.

    `plan` is consumed one answer per call and its last answer repeats:
    `"pending"`, `"collected"`, a settled state (`"failed"`, `"expired"`, ...),
    or `"raise"`. With `gate`, every call blocks until it is released.

    MT-141: `"pass_refused"` and `"pass_failed"` collect the job as
    `"collected"` does and then report the consistency pass that
    `collect_volume` runs after the volume's last job as not run - exactly
    `_run_postlude`'s spelling, `RunAborted(reason, ordinal=None)`, after the
    job's `BatchCollected` - and return the answer, the job collected."""

    def __init__(self, *plan: str, gate: threading.Event | None = None) -> None:
        self.plan = list(plan) or ["pending"]
        self.gate = gate
        self.calls: list[tuple[int, bool]] = []
        self.returned = 0
        self.cancels: list[object] = []  # nothing ever appends: there is no cancel to call

    def __call__(self, project: Project, job: BatchJob, emit: Callable[[RunEvent], None]) -> Any:
        self.calls.append((job.id, threading.current_thread() is threading.main_thread()))
        answer = self.plan[min(len(self.calls) - 1, len(self.plan) - 1)]
        if self.gate is not None:
            self.gate.wait(GATE_S)
        try:
            if answer == "raise":
                raise ConnectionError("the network is unreachable")
            if answer == "pending":
                emit(BatchWaiting(job_id=job.id, state="pending"))
                return BatchJobState("pending")
            if answer in {"collected", "pass_refused", "pass_failed"}:
                mark_collected(project, job.id)
                emit(BatchCollected(job.id, len(job.ordinals), 0, ()))
                if answer == "pass_refused":
                    emit(RunAborted(reason=BUDGET, ordinal=None))
                elif answer == "pass_failed":
                    emit(RunAborted(reason=PASS_REASON, ordinal=None))
                return BatchResults({})
            mark_failed(project, job.id, answer)
            emit(BatchFailed(job_id=job.id, state=answer))
            return BatchJobState(answer)  # type: ignore[arg-type]
        finally:
            self.returned += 1

    def polled(self) -> list[int]:
        return [job_id for job_id, _ in self.calls]


def _setup(submit: Any, collect: Any, ceilings: list[object] | None = None) -> Any:
    def ceiling(project: Project) -> Usd:
        if ceilings is not None:
            ceilings.append(project)
        return CEILING

    return _run().BatchSetup(submit=submit, collect=collect, ceiling=ceiling)


class Recorder(QObject):
    """Every signal the controller emits, in arrival order, on the GUI thread."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[object] = []
        self.waits: list[object] = []
        self.ends: list[object] = []
        self.poll_errors: list[BaseException] = []
        self.threads: list[bool] = []

    @Slot(object)
    def on_event(self, event: object) -> None:
        self.threads.append(threading.current_thread() is threading.main_thread())
        self.events.append(event)

    @Slot(object)
    def on_waiting(self, state: object) -> None:
        self.waits.append(state)

    @Slot(object)
    def on_ended(self, end: object) -> None:
        self.ends.append(end)

    @Slot(object)
    def on_poll_failed(self, error: object) -> None:
        assert isinstance(error, BaseException)
        self.poll_errors.append(error)


@dataclass
class World:
    controllers: list[Any] = field(default_factory=list)
    gates: list[threading.Event] = field(default_factory=list)
    keep: list[object] = field(default_factory=list)


@pytest.fixture
def world(qtbot: Any) -> Iterator[World]:
    made = World()
    yield made
    for gate in made.gates:
        gate.set()
    for controller in made.controllers:
        controller.stop()
    _settle()


def _controller(
    world: World, project_dir: Path, setup: Any, models: Path | None
) -> tuple[Any, Recorder]:
    controller = _run().BatchController(project_dir, setup, models, now=lambda: NOW)
    world.controllers.append(controller)
    recorder = Recorder()
    world.keep.append(recorder)
    controller.event.connect(recorder.on_event)
    controller.waiting.connect(recorder.on_waiting)
    controller.ended.connect(recorder.on_ended)
    controller.poll_failed.connect(recorder.on_poll_failed)
    return controller, recorder


def _until(qtbot: Any, condition: Callable[[], bool], what: str, timeout: int = WAIT_MS) -> None:
    try:
        qtbot.waitUntil(condition, timeout=timeout)
    except Exception:
        pytest.fail(f"after {timeout} ms: {what}")


def _elapse(controller: Any) -> None:
    """The poll timer's interval elapses: Qt's own `timeout`, sooner."""
    timer = controller.poll_timer
    assert timer.isActive(), "the poll timer is not armed, so it would never fire"
    timer.stop()
    timer.timeout.emit()


def _submitted(qtbot: Any, world: World, tmp_path: Path, collect: FakeCollect, **submit: Any):  # type: ignore[no-untyped-def]
    """A controller started with a models folder, waited until the wait begins."""
    project_dir = _project(tmp_path)
    fake = FakeSubmit(**submit)
    controller, recorder = _controller(
        world, project_dir, _setup(fake, collect), tmp_path / "models"
    )
    controller.start()
    _until(qtbot, lambda: recorder.waits != [], "the wait never began after the submission")
    _settle()
    return controller, recorder, project_dir, fake


# =============================================================================
# The shapes
# =============================================================================


def test_the_poll_interval_is_sixty_seconds() -> None:
    assert _run().BATCH_POLL_SECONDS == 60


def test_batch_setup_is_a_frozen_submit_collect_and_ceiling() -> None:
    setup = _setup(FakeSubmit(), FakeCollect())

    assert [f.name for f in dataclasses.fields(setup)] == ["submit", "collect", "ceiling"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setup.submit = FakeSubmit()


def test_run_setup_gains_a_batch_builder_defaulted_to_none(tmp_path: Path) -> None:
    """PO-1: defaulted, so every existing `RunSetup(` call means "no batch"."""
    three = RunSetup(lambda: tmp_path, lambda models: (), lambda: MODEL)
    assert three.build_batch is None  # type: ignore[attr-defined]

    def build() -> Any:
        return None

    four = RunSetup(lambda: tmp_path, lambda models: (), lambda: MODEL, build_batch=build)  # type: ignore[call-arg]
    assert four.build_batch is build  # type: ignore[attr-defined]


def test_waiting_state_carries_pages_jobs_time_projection_and_ceiling() -> None:
    state = _run().WaitingState(
        page_count=3, job_count=2, submitted_at=NOW, projection=None, ceiling=None
    )

    assert [f.name for f in dataclasses.fields(state)] == [
        "page_count",
        "job_count",
        "submitted_at",
        "projection",
        "ceiling",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.page_count = 4


def test_the_controller_never_sleeps_a_thread() -> None:
    """AC-2: "a single-shot Qt timer ... never a thread sleep". No `sleep` is
    named anywhere in `ui/run.py` - not `time.sleep`, not an imported `sleep`.
    Green on arrival in RED (`ui/run.py` exists and does not sleep); earned by
    the probe in the story's `## Handoff`, which puts a `time.sleep` into it."""
    tree = ast.parse(inspect.getsource(run_module))
    sleeps = [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Attribute) and node.attr == "sleep")
        or (isinstance(node, ast.Name) and node.id == "sleep")
        or (isinstance(node, ast.alias) and node.name == "sleep")
    ]
    assert sleeps == [], f"ui/run.py names `sleep` on lines {sleeps}: a poll waits on a QTimer"


# =============================================================================
# start() with a models folder: the submission, on a worker
# =============================================================================


def test_start_returns_at_once_and_submits_on_a_worker_with_the_models_folder(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    gate = threading.Event()
    world.gates.append(gate)
    project_dir = _project(tmp_path)
    fake = FakeSubmit()

    def gated(*args: Any) -> tuple[int, ...]:
        gate.wait(GATE_S)
        return fake(*args)

    controller, recorder = _controller(
        world, project_dir, _setup(gated, FakeCollect()), tmp_path / "models"
    )

    controller.start()
    assert fake.calls == [], "start() returned only after the submission had run"
    gate.set()
    _until(qtbot, lambda: recorder.waits != [], "the wait never began")

    assert fake.calls == [(tmp_path / "models", False)], (
        f"submit was called {fake.calls}; C-3 is once, with the models folder, on a worker"
    )


def test_every_worker_opens_its_own_project_and_closes_it(
    qtbot: Any, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[tuple[Project, bool]] = []
    real = run_module.open_project

    def spy(project_dir: Path) -> Project:
        project = real(project_dir)
        opened.append((project, threading.current_thread() is threading.main_thread()))
        return project

    monkeypatch.setattr(run_module, "open_project", spy)
    collect = FakeCollect("collected")
    controller, recorder, _dir, _fake = _submitted(qtbot, world, tmp_path, collect)
    _elapse(controller)
    _until(qtbot, lambda: recorder.ends != [], "the poll never ended the run")

    assert len(opened) >= 2, f"{len(opened)} projects opened for a submit and a poll"
    assert [on_gui for _, on_gui in opened] == [False] * len(opened), (
        "a project was opened on the GUI thread: a Project crosses no thread"
    )
    still_open = []
    for project, _ in opened:
        try:
            project.select("SELECT 1")
        except sqlite3.ProgrammingError:
            continue
        still_open.append(project)
    assert still_open == [], f"{len(still_open)} worker project(s) left open"


def test_a_submission_begins_the_wait_once_with_what_was_submitted(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    project_dir = _project(tmp_path)
    ceilings: list[object] = []
    controller, recorder = _controller(
        world,
        project_dir,
        _setup(FakeSubmit(ranges=((0, 1), (2, 2))), FakeCollect(), ceilings),
        tmp_path / "models",
    )

    controller.start()
    _until(qtbot, lambda: recorder.waits != [], "the wait never began")
    _settle()

    assert recorder.waits == [
        _run().WaitingState(
            page_count=3, job_count=2, submitted_at=NOW, projection=usd("0.06"), ceiling=CEILING
        )
    ]
    assert len(ceilings) == 1 and isinstance(ceilings[0], Project), (
        f"ceiling was asked {len(ceilings)} times; C-3 is once, of the project"
    )
    assert recorder.ends == []


def test_every_event_of_the_submission_is_forwarded_in_order_to_the_gui_thread(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    _ctl, recorder, _dir, _fake = _submitted(qtbot, world, tmp_path, FakeCollect())

    assert [type(e).__name__ for e in recorder.events] == ["RunStarted", "BatchSubmitted"]
    assert recorder.threads == [True, True], "an event was delivered off the GUI thread"


def test_the_wait_arms_a_single_shot_timer_of_sixty_seconds_and_polls_nothing_yet(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    collect = FakeCollect()
    controller, _recorder, _dir, _fake = _submitted(qtbot, world, tmp_path, collect)

    timer = controller.poll_timer
    assert timer.isSingleShot(), "the poll timer repeats: AC-2 re-arms a single shot"
    assert timer.interval() == 60_000
    assert timer.isActive(), "the poll timer is not armed once the wait begins"
    assert collect.calls == [], "a fresh submission was polled at once; the first poll waits"
    assert controller.is_running(), "a waiting controller does not report itself running"


def test_a_submission_that_emits_no_batch_submitted_ends_not_submitted(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    project_dir = _project(tmp_path)
    collect = FakeCollect()
    controller, recorder = _controller(
        world, project_dir, _setup(FakeSubmit(refuse=True), collect), tmp_path / "models"
    )

    controller.start()
    _until(qtbot, lambda: recorder.ends != [], "a refused submission never ended")
    _settle()

    assert recorder.ends == ["not_submitted"]
    assert recorder.waits == [], "a refused submission began a wait"
    assert not controller.poll_timer.isActive()
    assert collect.calls == []
    assert [type(e).__name__ for e in recorder.events] == ["RunStarted", "CallPriced", "RunAborted"]
    _until(qtbot, lambda: not controller.is_running(), "the controller still runs after ending")


# =============================================================================
# AC-2: the poll
# =============================================================================


def test_firing_the_timer_asks_every_pending_job_in_page_order_on_a_worker(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    collect = FakeCollect("pending")
    controller, _recorder, project_dir, _fake = _submitted(
        qtbot, world, tmp_path, collect, ranges=((0, 1), (2, 2))
    )
    ids = [job.id for job in _pending(project_dir)]

    _elapse(controller)
    _until(qtbot, lambda: len(collect.calls) == 2, "the poll did not ask both pending jobs")

    assert collect.polled() == ids
    assert [on_gui for _, on_gui in collect.calls] == [False, False], (
        "a poll ran on the GUI thread: AC-2 polls on a worker"
    )


def test_a_poll_that_leaves_a_job_pending_arms_the_timer_again(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    """**DV-1's assertion** (the story's central claim): with the re-arm
    removed, the timer stays inactive after the poll and this goes red."""
    collect = FakeCollect("pending")
    controller, recorder, _dir, _fake = _submitted(qtbot, world, tmp_path, collect)

    _elapse(controller)
    _until(qtbot, lambda: len(collect.calls) == 1, "the first poll never ran")

    _until(
        qtbot,
        lambda: controller.poll_timer.isActive(),
        "a poll left the job pending and the poll timer was not armed again (AC-2)",
    )
    assert controller.poll_timer.interval() == 60_000
    assert recorder.ends == []


def test_a_rearmed_timer_polls_again_when_it_fires(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    collect = FakeCollect("pending")
    controller, _recorder, _dir, _fake = _submitted(qtbot, world, tmp_path, collect)

    for poll in (1, 2, 3):
        _until(qtbot, lambda: controller.poll_timer.isActive(), f"not re-armed before poll {poll}")
        _elapse(controller)
        _until(qtbot, lambda poll=poll: len(collect.calls) == poll, f"poll {poll} never ran")


def test_a_poll_forwards_each_jobs_waiting_event(qtbot: Any, world: World, tmp_path: Path) -> None:
    collect = FakeCollect("pending")
    controller, recorder, project_dir, _fake = _submitted(
        qtbot, world, tmp_path, collect, ranges=((0, 1), (2, 2))
    )
    ids = [job.id for job in _pending(project_dir)]

    _elapse(controller)
    _until(qtbot, lambda: len(recorder.events) == 4, "the poll's events never arrived")

    assert recorder.events[2:] == [BatchWaiting(job_id=i, state="pending") for i in ids]


def test_a_poll_that_leaves_no_job_pending_ends_collected_and_stops(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    collect = FakeCollect("collected")
    controller, recorder, project_dir, _fake = _submitted(
        qtbot, world, tmp_path, collect, ranges=((0, 1), (2, 2))
    )

    _elapse(controller)
    _until(qtbot, lambda: recorder.ends != [], "a poll that collected everything never ended")
    _settle()

    assert recorder.ends == ["collected"]
    assert len(collect.calls) == 2
    assert not controller.poll_timer.isActive(), "the timer was re-armed with nothing pending"
    assert _pending(project_dir) == ()
    _until(qtbot, lambda: not controller.is_running(), "the controller still runs after ending")


def test_a_poll_that_collects_one_job_of_two_waits_on_for_the_other(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    collect = FakeCollect("collected", "pending")
    controller, recorder, project_dir, _fake = _submitted(
        qtbot, world, tmp_path, collect, ranges=((0, 1), (2, 2))
    )

    _elapse(controller)
    _until(qtbot, lambda: len(collect.calls) == 2, "the poll did not ask both jobs")
    _until(qtbot, lambda: controller.poll_timer.isActive(), "not re-armed with one job pending")

    assert recorder.ends == []
    assert len(_pending(project_dir)) == 1


@pytest.mark.parametrize("state", ["failed", "expired"])
def test_a_failed_job_ends_failed_and_the_timer_is_not_armed_again(
    qtbot: Any, world: World, tmp_path: Path, state: str
) -> None:
    collect = FakeCollect(state)
    controller, recorder, _dir, _fake = _submitted(qtbot, world, tmp_path, collect)

    _elapse(controller)
    _until(qtbot, lambda: recorder.ends != [], "a failed job never ended the run")
    _settle()

    assert recorder.ends == ["failed"]
    assert BatchFailed(job_id=collect.polled()[0], state=state) in recorder.events
    assert not controller.poll_timer.isActive(), "the timer was re-armed after a failed job"


def test_a_failed_job_of_two_ends_failed_and_leaves_the_other_pending(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    """PO-3: one failed job stops polling; a job still pending stays pending."""
    collect = FakeCollect("failed", "pending")
    controller, recorder, project_dir, _fake = _submitted(
        qtbot, world, tmp_path, collect, ranges=((0, 1), (2, 2))
    )

    _elapse(controller)
    _until(qtbot, lambda: recorder.ends != [], "a failed job never ended the run")
    _settle()

    assert recorder.ends == ["failed"]
    assert not controller.poll_timer.isActive()
    assert [(j.first_ordinal, j.last_ordinal) for j in _pending(project_dir)] == [(2, 2)]


def test_a_poll_that_raises_is_reported_as_no_event_and_the_timer_is_armed_again(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    collect = FakeCollect("raise")
    controller, recorder, project_dir, _fake = _submitted(qtbot, world, tmp_path, collect)
    before = list(recorder.events)

    _elapse(controller)
    _until(qtbot, lambda: recorder.poll_errors != [], "a poll that raised was never reported")
    _until(qtbot, lambda: controller.poll_timer.isActive(), "not re-armed after a poll raised")

    (error,) = recorder.poll_errors
    assert type(error) is ConnectionError
    assert str(error) == "the network is unreachable"
    assert recorder.events == before, "a poll that raised was emitted as an event"
    assert recorder.ends == []
    assert len(_pending(project_dir)) == 1


# =============================================================================
# AC-3 at the controller: start() with no models folder is the reopen
# =============================================================================


def test_a_reopen_begins_the_wait_from_the_pending_jobs_and_polls_at_once(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    project_dir = _project(tmp_path, pages=6)
    with open_project(project_dir) as project:
        first, second = _record(project, ((1, 2), (3, 5)))
    # The later page range was submitted earlier: the line takes the earliest.
    _stamp(project_dir, first, "2026-11-04T09:15:00+00:00")
    _stamp(project_dir, second, "2026-11-04T08:40:00+00:00")
    submit = FakeSubmit()
    collect = FakeCollect("pending")
    controller, recorder = _controller(world, project_dir, _setup(submit, collect), None)

    controller.start()
    _until(qtbot, lambda: len(collect.calls) == 2, "a reopen did not poll every job at once")
    _until(qtbot, lambda: recorder.waits != [], "a reopen never began the wait")

    (state,) = recorder.waits
    assert (state.page_count, state.job_count) == (5, 2), (
        f"the wait counts {state.page_count} pages in {state.job_count} jobs; AC-3 is the"
        " pending jobs' pages (5 of the chapter's 6) in their 2 jobs"
    )
    assert state.submitted_at == datetime(2026, 11, 4, 8, 40, tzinfo=UTC)
    assert state.projection is None, "a reopen showed a projection (PO-4)"
    assert submit.calls == [], "a reopen submitted again"
    assert collect.polled() == [first, second]
    _until(qtbot, lambda: controller.poll_timer.isActive(), "a reopen's poll did not re-arm")


# =============================================================================
# AC-6 at the controller: stop()
# =============================================================================


def test_stop_joins_a_poll_in_flight_and_leaves_the_job_pending(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    gate = threading.Event()
    world.gates.append(gate)
    collect = FakeCollect("pending", gate=gate)
    controller, recorder, project_dir, _fake = _submitted(qtbot, world, tmp_path, collect)
    _elapse(controller)
    _until(qtbot, lambda: len(collect.calls) == 1, "the poll never started")

    release = threading.Timer(HOLD_S, gate.set)
    release.start()
    started = time.perf_counter()
    controller.stop()
    held = time.perf_counter() - started
    release.join()
    _settle()

    assert collect.returned == 1, "stop() returned while the poll was still in flight"
    assert held >= HOLD_S * 0.5, f"stop() returned after {held:.3f} s, before the poll did"
    assert not controller.poll_timer.isActive(), "the timer is armed after stop()"
    assert len(collect.calls) == 1
    assert collect.cancels == []
    assert len(_pending(project_dir)) == 1, "stop() settled the job: it must stay pending"
    assert recorder.ends == []
    assert not controller.is_running()


def test_stop_while_waiting_stops_the_timer_and_nothing_polls_after_it(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    collect = FakeCollect("pending")
    controller, _recorder, project_dir, _fake = _submitted(qtbot, world, tmp_path, collect)

    controller.stop()
    _settle()

    assert not controller.poll_timer.isActive()
    assert collect.calls == []
    assert len(_pending(project_dir)) == 1
    assert not controller.is_running()


# =============================================================================
# MT-141 AC-5: a poll during which the consistency pass did not run
# =============================================================================
#
# `collect_volume` runs the pass after the volume's last `BatchCollected` and
# reports a refused or failed one as `RunAborted(reason, ordinal=None)` on the
# poll's stream, the job collected. Only the controller sees the poll's whole
# stream, so it decides the end: `"pass_not_run"` (Contract C-1, PO-4).


def test_batch_end_has_pass_not_run_beside_the_three_it_had() -> None:
    """C-1: `BatchEnd` grows by exactly one literal."""
    import typing

    assert set(typing.get_args(run_module.BatchEnd)) == {
        "collected",
        "failed",
        "not_submitted",
        "pass_not_run",
    }


def test_the_postlude_builder_is_exported_from_ui_run() -> None:
    """C-1: `PostludeBuilder` is a public name of `mangatl.ui.run`."""
    assert "PostludeBuilder" in run_module.__all__
    from mangatl.ui.run import PostludeBuilder  # type: ignore[attr-defined]

    assert PostludeBuilder is not None


def test_run_setup_gains_a_postlude_builder_last_and_defaulted_to_none(tmp_path: Path) -> None:
    """AC-2 / C-1 (PO-1): a fifth field, last, defaulted - so every existing
    `RunSetup(` means "no pass" - and, as amended in RED (2026-11-08), left
    out of the setup's equality, so a default setup compared by value
    (`test_chapter_summary.py`, `test_folder_intake.py`,
    `test_intake_errors.py`) still equals the one those tests spell."""
    names = [f.name for f in dataclasses.fields(RunSetup)]
    assert names == [
        "resolve_models",
        "build_stages",
        "select_model",
        "build_batch",
        "build_postlude",
    ]

    def resolve() -> Path:
        return tmp_path

    def stages(models: Path) -> Any:
        return ()

    def select() -> str:
        return MODEL

    def postlude() -> Any:
        return None

    three = RunSetup(resolve, stages, select)
    assert three.build_postlude is None  # type: ignore[attr-defined]
    five = RunSetup(resolve, stages, select, build_postlude=postlude)  # type: ignore[call-arg]
    assert five.build_postlude is postlude  # type: ignore[attr-defined]
    assert five == three, "build_postlude takes part in RunSetup's equality (C-1 as amended)"


@pytest.mark.parametrize("answer", ["pass_refused", "pass_failed"])
def test_a_poll_whose_pass_did_not_run_ends_pass_not_run_and_stops(
    qtbot: Any, world: World, tmp_path: Path, answer: str
) -> None:
    """AC-5: both jobs collected, the pass then refused (or failed) after the
    last one - the run ends `pass_not_run`, never `collected`, and the timer
    is not armed again."""
    collect = FakeCollect("collected", answer)
    controller, recorder, project_dir, _fake = _submitted(
        qtbot, world, tmp_path, collect, ranges=((0, 1), (2, 2))
    )

    _elapse(controller)
    _until(qtbot, lambda: recorder.ends != [], "a poll whose pass did not run never ended")
    _settle()

    assert recorder.ends == ["pass_not_run"]
    aborted = [e for e in recorder.events if isinstance(e, RunAborted)]
    assert [e.ordinal for e in aborted] == [None], f"the poll's stream carried {aborted}"
    assert not controller.poll_timer.isActive(), "the timer was re-armed after the pass"
    assert _pending(project_dir) == ()
    _until(qtbot, lambda: not controller.is_running(), "the controller still runs after ending")


def test_a_failed_job_in_the_poll_where_the_pass_did_not_run_still_ends_failed(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    """AC-5: a `BatchFailed` wins - its pages were not translated, which is
    the worse news. A control: it ends `failed` today, and must go on doing so."""
    collect = FakeCollect("failed", "pass_refused")
    controller, recorder, _dir, _fake = _submitted(
        qtbot, world, tmp_path, collect, ranges=((0, 1), (2, 2))
    )

    _elapse(controller)
    _until(qtbot, lambda: recorder.ends != [], "the poll never ended")
    _settle()

    assert recorder.ends == ["failed"]
    assert RunAborted(reason=BUDGET, ordinal=None) in recorder.events, "precondition"
    assert not controller.poll_timer.isActive()
