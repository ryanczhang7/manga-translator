"""A run of the chapter, off the GUI thread (MT-059 C-1).

`architecture.md` §6: "`ui` -> `pipeline`: commands ... returns immediately;
the work runs on a worker thread", and "`pipeline` -> `ui`: an event stream ...
Qt signals at the boundary". `RunController` is that thread and that boundary.

The worker opens its **own** `Project` and closes it before it ends: sqlite's
`check_same_thread` means a `Project` crosses no thread, so the one the GUI
thread created is closed there and never handed over. `open_project` is called
by this module's name for it, which is the seam the tests observe.

`event` and `ended` are emitted from the worker. A receiver living on the GUI
thread gets them through Qt's queued connection, so they arrive there, in
emission order, and `ended` after the last `event`. `domain.events` are frozen
dataclasses, so nothing a receiver holds is shared mutable state.

The stages arrive already built (`RunSetup.build_stages`, injected by the
composition root `mangatl.app`): `ui` never imports `mangatl.compose`, so the
window never constructs an inference session or an API client itself.

**The batch run** (MT-113 C-3) is `BatchController`, built from a `BatchSetup`
the composition root binds (`RunSetup.build_batch`, asked at Start, PO-2). It
keeps `RunController`'s rules - every worker opens its own `Project` through
this module's `open_project`, events cross to the GUI thread as queued
signals - and adds the wait: a **single-shot** `poll_timer` of
`BATCH_POLL_SECONDS`, re-armed on the GUI thread after each poll that leaves a
job pending (a `QTimer` belongs to its thread), never a thread sleep (AC-2).
Each poll runs on a worker and asks every pending job once. A `BatchFailed`
ends the run `failed` and polling stops; no job left pending ends it
`collected`; a poll that raises is reported on `poll_failed` and the timer is
armed again. `stop()` stops the timer and joins a worker in flight; nothing is
cancelled at the provider, so the jobs stay pending for a reopen (AC-6).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from mangatl.domain.batch import BatchAnswer, BatchJob
from mangatl.domain.events import BatchFailed, BatchSubmitted, RunEvent
from mangatl.domain.money import Usd
from mangatl.pipeline.batch import ChapterSubmit
from mangatl.pipeline.runner import run_chapter
from mangatl.pipeline.stage import Stage
from mangatl.store.batch import pending_jobs
from mangatl.store.project import Project, open_project

__all__ = [
    "BATCH_POLL_SECONDS",
    "NO_MODELS",
    "BatchBuilder",
    "BatchController",
    "BatchEnd",
    "BatchSetup",
    "ModelSelector",
    "ModelsResolver",
    "RunController",
    "RunSetup",
    "StageBuilder",
    "WaitingState",
]

#: AC-2: how long the wait sleeps on its timer between two polls.
BATCH_POLL_SECONDS: int = 60

#: AC-7, the Lead PO's wording. It names the variable and not `--models`,
#: which a window user cannot pass (PO-4).
NO_MODELS: str = (
    "No models folder: set MANGATL_MODELS to the folder holding the model"
    " weights, then start the app again."
)

#: The models folder, or `None` when there is none.
ModelsResolver = Callable[[], Path | None]
#: The stage list for a models folder.
StageBuilder = Callable[[Path], Sequence[Stage]]
#: The model the run would call, or a `ProviderError` saying why none can be
#: chosen (MT-100 C-5). What the summary's estimate is priced on.
ModelSelector = Callable[[], str]


@dataclass(frozen=True)
class BatchSetup:
    """The batch half of a Start, bound by the composition root (MT-113 C-3):
    the whole submission (`pipeline.batch.ChapterSubmit`), one poll of one job,
    and the stored ceiling the guard judged against."""

    submit: ChapterSubmit
    collect: Callable[[Project, BatchJob, Callable[[RunEvent], None]], BatchAnswer]
    ceiling: Callable[[Project], Usd]


#: The batch setup for the provider a Start would use now; `None` when it has
#: no batch; raises `ProviderError` when no provider can be selected.
BatchBuilder = Callable[[], BatchSetup | None]


@dataclass(frozen=True)
class RunSetup:
    """What the composition root gives the window to start a run with.

    `build_batch` is defaulted (MT-113 PO-1): a setup without one has no
    batch, and Start runs per page as it always has."""

    resolve_models: ModelsResolver
    build_stages: StageBuilder
    select_model: ModelSelector
    build_batch: BatchBuilder | None = None


@dataclass(frozen=True)
class WaitingState:
    """What the waiting panel shows once the wait begins (MT-113 C-3).

    `submitted_at` is aware. `projection` and `ceiling` are the guard's after a
    submission and `None` on a reopen, where no projection is stored (PO-4)."""

    page_count: int
    job_count: int
    submitted_at: datetime
    projection: Usd | None
    ceiling: Usd | None


#: How a batch run ends, emitted once on `BatchController.ended`.
BatchEnd = Literal["collected", "failed", "not_submitted"]

#: What one poll found: a `BatchEnd`, `"pending"`, or the exception it raised.
_PollResult = Literal["collected", "failed", "pending"] | BaseException


class RunController(QObject):
    """One run of the chapter in `project_dir` through `stages`, on a worker."""

    #: Each `RunEvent`, in emission order. The contract names it `event`, and the
    #: tests connect to it so; it shadows `QObject.event()`, which Qt calls from
    #: C++ (PySide dispatches to a Python override only when it is a method) and
    #: nothing in this app calls on a controller.
    event = Signal(object)  # type: ignore[assignment]
    #: The `RunOutcome` `run_chapter` returned, after the last `event`.
    ended = Signal(object)

    def __init__(
        self,
        project_dir: Path,
        stages: Sequence[Stage],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_dir = project_dir
        self._stages = tuple(stages)
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the worker and return at once."""
        self._thread = threading.Thread(target=self._work, name="mangatl-run", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Ask the run to stop at its next stage boundary. Thread-safe."""
        self._cancel.set()

    def wait(self) -> None:
        """Block until the worker has returned and closed its project; a no-op
        when it never started."""
        if self._thread is not None:
            self._thread.join()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _work(self) -> None:
        with open_project(self._project_dir) as project:
            outcome = run_chapter(project, self._stages, self._emit, self._cancel.is_set)
        self.ended.emit(outcome)

    def _emit(self, event: RunEvent) -> None:
        self.event.emit(event)


def _local_now() -> datetime:
    """The aware local time: the waiting panel's lines are local `HH:MM`."""
    return datetime.now().astimezone()


class BatchController(QObject):
    """One batch run of the chapter in `project_dir`: the submission or the
    reopen, then the wait (module docstring, "The batch run").

    `models_dir` given, `start()` runs `batch.submit` on a worker and the wait
    begins after its `BatchSubmitted`; `None` is the reopen, which begins the
    wait from the pending jobs and polls at once."""

    #: Every `RunEvent` of the submission and of each poll, in order. It shadows
    #: `QObject.event()` for `RunController.event`'s reason.
    event = Signal(object)  # type: ignore[assignment]
    #: The `WaitingState`, once, when the wait begins.
    waiting = Signal(object)
    #: The `BatchEnd`, once.
    ended = Signal(object)
    #: The exception a poll raised, once per failed poll (C-3 as amended, A-R1).
    poll_failed = Signal(object)

    # Worker -> GUI thread. Queued, because the controller lives on the GUI
    # thread, so each slot runs there - after the events emitted before it.
    _began = Signal(object)
    _polled = Signal(object)

    def __init__(
        self,
        project_dir: Path,
        batch: BatchSetup,
        models_dir: Path | None,
        parent: QObject | None = None,
        *,
        now: Callable[[], datetime] = _local_now,
    ) -> None:
        super().__init__(parent)
        self._project_dir = project_dir
        self._batch = batch
        self._models_dir = models_dir
        self._now = now
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self.poll_timer = QTimer(self)
        self.poll_timer.setSingleShot(True)
        self.poll_timer.setInterval(BATCH_POLL_SECONDS * 1000)
        self.poll_timer.timeout.connect(self._poll)
        self._began.connect(self._on_began)
        self._polled.connect(self._on_polled)

    def start(self) -> None:
        """Start the submission - or, on a reopen, the first poll - on a worker
        and return at once."""
        self._running = True
        if self._models_dir is None:
            self._spawn(self._poll_work, True)
        else:
            self._spawn(self._submit_work, self._models_dir)

    def stop(self) -> None:
        """Stop the timer and wait for a worker in flight; nothing is cancelled
        at the provider, so every job stays pending (AC-6)."""
        self._running = False
        self._cancel.set()
        self.poll_timer.stop()
        if self._thread is not None:
            self._thread.join()

    def is_running(self) -> bool:
        """`True` from `start()` until `ended` or `stop()`, waiting included
        (C-3 as amended, A-R4)."""
        return self._running

    def _spawn(self, target: Callable[..., None], *args: object) -> None:
        self._thread = threading.Thread(target=target, args=args, name="mangatl-batch", daemon=True)
        self._thread.start()

    def _submit_work(self, models_dir: Path) -> None:
        submitted: list[BatchSubmitted] = []

        def emit(event: RunEvent) -> None:
            if isinstance(event, BatchSubmitted):
                submitted.append(event)
            self.event.emit(event)

        state: WaitingState | None = None
        with open_project(self._project_dir) as project:
            self._batch.submit(project, models_dir, emit, self._cancel.is_set)
            if submitted:
                done = submitted[-1]
                state = WaitingState(
                    page_count=done.page_count,
                    job_count=len(done.job_ids),
                    submitted_at=self._now(),
                    projection=done.projection.next_call,
                    ceiling=self._batch.ceiling(project),
                )
        self._began.emit(state)

    def _poll_work(self, reopen: bool) -> None:
        failed: list[BatchFailed] = []

        def emit(event: RunEvent) -> None:
            if isinstance(event, BatchFailed):
                failed.append(event)
            self.event.emit(event)

        result: _PollResult
        with open_project(self._project_dir) as project:
            jobs = pending_jobs(project)
            if reopen:
                self._began.emit(_reopened(jobs))
            try:
                for job in jobs:
                    self._batch.collect(project, job, emit)
                left = pending_jobs(project)
            except Exception as error:  # reported on poll_failed; the wait goes on
                result = error
            else:
                result = "failed" if failed else "pending" if left else "collected"
        self._polled.emit(result)

    @Slot()
    def _poll(self) -> None:
        if self._running:
            self._spawn(self._poll_work, False)

    @Slot(object)
    def _on_began(self, state: WaitingState | None) -> None:
        if not self._running:
            return
        if state is None:
            self._end("not_submitted")
            return
        self.waiting.emit(state)
        if self._models_dir is not None:
            # After a submission the first poll waits its interval; a reopen's
            # first poll is already in flight.
            self.poll_timer.start()

    @Slot(object)
    def _on_polled(self, result: _PollResult) -> None:
        if not self._running:
            return
        if isinstance(result, BaseException):
            self.poll_failed.emit(result)
            self.poll_timer.start()
        elif result == "pending":
            self.poll_timer.start()
        else:
            self._end(result)

    def _end(self, end: BatchEnd) -> None:
        self._running = False
        self.ended.emit(end)


def _reopened(jobs: Sequence[BatchJob]) -> WaitingState:
    """AC-3: the pending jobs' pages and count, at the earliest `submitted_at`,
    with no projection (PO-4)."""
    return WaitingState(
        page_count=sum(len(job.ordinals) for job in jobs),
        job_count=len(jobs),
        submitted_at=min(datetime.fromisoformat(job.submitted_at) for job in jobs),
        projection=None,
        ceiling=None,
    )
