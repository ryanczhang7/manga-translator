"""MT-113 AC-1, AC-2, AC-4, AC-5, AC-6 through the window: Start on Gemini
submits the batch and the window waits for it.

`MainWindow._start` (C-6): after the models folder, `RunSetup.build_batch()`.
A `BatchSetup` back is the batch path - the project, a
`RunProgressPanel(batch=True)` and a `BatchController(project_dir, batch,
models)` held on `window.batch_run` (C-6 as amended in RED, A-R2); on
`waiting` the central widget becomes a `BatchWaitingPanel`; `ended
("collected")` opens the review. `None` back is today's per-page path,
untouched (AC-5).

**The batch run here is the real one up to the provider.** The `ChapterSubmit`
each test injects calls the REAL `pipeline.batch.submit_chapter` with fake
local stages (`detect` writes one region, `ocr` one line), a fake prelude and
a fake submitter, so the REAL `run_chapter` and `submit_volume` decide what the
window sees: the stepper's steps, the jobs recorded, the budget refusal. The
collector is a fake writing through the real `mark_collected` / `mark_failed`.
Nothing constructs a client or loads a weight.

**Times.** The window injects no clock into its controller or panel, so a
line's `{time}` is checked against the local `HH:MM` of the instants just
before and just after the event that sets it: one of the two, exactly.

**The timer is never waited for**: `_elapse` asserts `poll_timer` is armed,
stops it and emits its `timeout`, as Qt would sixty seconds later.

**RED:** the window has no batch path, `RunSetup` no `build_batch` and
`ui.batch_panel` does not exist. Each is reached inside a test body or helper,
so the file collects and each test fails on its own.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton

from mangatl import app as app_module
from mangatl.domain.batch import BatchJob, BatchJobState, BatchResults
from mangatl.domain.events import BatchCollected, BatchFailed, BatchWaiting, RunEvent
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.page import Chapter
from mangatl.domain.region import RawRegion
from mangatl.pipeline.prelude import Pipeline
from mangatl.pipeline.stage import PageContext
from mangatl.pipeline.translate_stage import budget_for
from mangatl.store.batch import mark_collected, mark_failed, pending_jobs
from mangatl.store.project import Project, open_project, project_dir_for
from mangatl.translate.provider import NoApiKey
from mangatl.ui import tokens_gen
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.main_window import MainWindow
from mangatl.ui.progress import ErrorBanner, RunProgressPanel
from mangatl.ui.run import RunController, RunSetup
from mangatl.ui.summary import ChapterSummary
from mangatl.ui.workspace import Workspace

EM = "\N{EM DASH}"
MODEL = "gemini-3.1-pro-preview"
#: MT-111 AC-1's batch page estimate, written out: $0.02 a page, $0.06 for three.
ESTIMATE = Usd.from_micro(20_000)
#: The stored ceiling the guard judges, set before the guard runs.
CEILING_MICRO = 1_500_000
TIGHT_CEILING_MICRO = 50_000
#: Two pages fit one 20 MB inline job and the third goes in a second.
EIGHT_MB = 8_000_000

#: Liveness bounds: a fake three-page batch run is a few sqlite writes.
WAIT_MS = 10_000
GATE_S = 10.0
HOLD_S = 0.3


def hhmm(moment: datetime) -> str:
    return moment.astimezone().strftime("%H:%M")


def _now() -> datetime:
    return datetime.now().astimezone()


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _batch_panel_type() -> Any:
    from mangatl.ui.batch_panel import BatchWaitingPanel  # type: ignore[import-not-found]

    return BatchWaitingPanel


def _batch_setup(**fields: Any) -> Any:
    from mangatl.ui.run import BatchSetup  # type: ignore[attr-defined]

    return BatchSetup(**fields)


def _submit_chapter(*args: Any, **kwargs: Any) -> tuple[int, ...]:
    from mangatl.pipeline.batch import submit_chapter  # type: ignore[attr-defined]

    ids: tuple[int, ...] = submit_chapter(*args, **kwargs)
    return ids


# =============================================================================
# The chapter, the local stages, the batch fakes
# =============================================================================


def _png(size: QSize) -> bytes:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def _folder(tmp_path: Path, pages: int = 3) -> Path:
    folder = tmp_path / "Chapter 9"
    folder.mkdir()
    png = _png(QSize(60, 80))
    for index in range(pages):
        (folder / f"{index + 1:02d}.png").write_bytes(png)
    return folder.resolve()


class _Detect:
    name = "detect"

    def __init__(self, mask: bytes) -> None:
        self._mask = mask

    def run(self, ctx: PageContext) -> None:
        ring = ((5, 5), (20, 5), (20, 20), (5, 20), (5, 5))
        ctx.project.write_regions(
            ctx.page.ordinal,
            [RawRegion(polygon=ring, mask=self._mask, confidence=1.0, kind="bubble")],
        )

    def is_done(self, ctx: PageContext) -> bool:
        return False


class _Ocr:
    name = "ocr"

    def run(self, ctx: PageContext) -> None:
        ctx.project.write_lines(ctx.page.ordinal, [OcrResult(f"line {ctx.page.ordinal}")])

    def is_done(self, ctx: PageContext) -> bool:
        return False


class _Gate:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait(self) -> None:
        self.entered.set()
        self.release.wait(GATE_S)


@dataclass
class ChapterSubmit:
    """The `ChapterSubmit` `compose.build_batch_submit` would bind, with fakes
    at the provider: the real `submit_chapter` over fake local stages."""

    ceiling_micro: int = CEILING_MICRO
    size: int = 1
    prelude_gate: _Gate | None = None
    models: list[Path] = field(default_factory=list)
    submitted: list[list[int]] = field(default_factory=list)

    def __call__(
        self,
        project: Project,
        models_dir: Path,
        emit: Callable[[RunEvent], None],
        cancelled: Callable[[], bool],
    ) -> tuple[int, ...]:
        self.models.append(models_dir)
        with project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (self.ceiling_micro,))
        gate = self.prelude_gate

        def prelude(p: Project, run_id: int, emit_: Callable[[RunEvent], None]) -> None:
            if gate is not None:
                gate.wait()

        def submit(inputs: Sequence[Any]) -> str:
            self.submitted.append([i.ordinal for i in inputs])
            return f"batches/job-{len(self.submitted)}"

        return _submit_chapter(
            project,
            stages=(_Detect(_png(QSize(4, 4))), _Ocr()),
            prelude=prelude,
            submit=submit,
            request_size=lambda page_input: self.size,
            model_id=MODEL,
            page_estimate=ESTIMATE,
            emit=emit,
            cancelled=cancelled,
        )


class FakeCollect:
    """`(project, job, emit) -> BatchAnswer` from a plan; the last answer repeats."""

    def __init__(self, *plan: str, gate: threading.Event | None = None) -> None:
        self.plan = list(plan) or ["pending"]
        self.gate = gate
        self.calls: list[int] = []
        self.returned = 0

    def __call__(self, project: Project, job: BatchJob, emit: Callable[[RunEvent], None]) -> Any:
        self.calls.append(job.id)
        answer = self.plan[min(len(self.calls) - 1, len(self.plan) - 1)]
        if self.gate is not None:
            self.gate.wait(GATE_S)
        try:
            if answer == "raise":
                raise ConnectionError("the network is unreachable")
            if answer == "pending":
                emit(BatchWaiting(job_id=job.id, state="pending"))
                return BatchJobState("pending")
            if answer == "collected":
                mark_collected(project, job.id)
                emit(BatchCollected(job.id, len(job.ordinals), 0, ()))
                return BatchResults({})
            mark_failed(project, job.id, answer)
            emit(BatchFailed(job_id=job.id, state=answer))
            return BatchJobState(answer)  # type: ignore[arg-type]
        finally:
            self.returned += 1


class Builder:
    """`build_stages`: records each call. The batch path must never call it."""

    def __init__(self, stages: Sequence[Any] = ()) -> None:
        self.calls: list[Path] = []
        self._stages = tuple(stages)

    def __call__(self, models_dir: Path) -> Pipeline:
        # MT-139 C-1: a `StageBuilder` returns a `Pipeline`; never called here.
        self.calls.append(models_dir)
        return Pipeline(stages=self._stages, prelude=None)


@dataclass
class BatchBuilder:
    """`RunSetup.build_batch`: records each call and returns `setup`."""

    setup: Any = None
    raises: Exception | None = None
    calls: int = 0
    on_call: Callable[[], None] | None = None

    def __call__(self) -> Any:
        self.calls += 1
        if self.on_call is not None:
            self.on_call()
        if self.raises is not None:
            raise self.raises
        return self.setup


def _ceiling(project: Project) -> Usd:
    """The stored ceiling the guard used: `budget_for` at the batch estimate."""
    return budget_for(project, ESTIMATE).ceiling


def _gemini() -> str:
    return MODEL


# =============================================================================
# The window
# =============================================================================


@dataclass
class World:
    windows: list[QMainWindow] = field(default_factory=list)
    gates: list[threading.Event] = field(default_factory=list)


@pytest.fixture
def world(qtbot: Any) -> Iterator[World]:
    made = World()
    yield made
    for gate in made.gates:
        gate.set()
    for window in made.windows:
        batch = getattr(window, "batch_run", None)
        if batch is not None:
            batch.stop()
        run = getattr(window, "run", None)
        if isinstance(run, RunController):
            run.cancel()
            run.wait()
    _settle()
    for window in made.windows:
        opened = getattr(window, "opened", None)
        if isinstance(opened, QMainWindow):
            opened.close()
        window.close()
    _settle()


def _window(qtbot: Any, world: World, folder: Path, setup: RunSetup) -> MainWindow:
    window = MainWindow(open_folder=app_module.open_folder, run_setup=setup)
    qtbot.addWidget(window)
    world.windows.append(window)
    window.resize(900, 600)
    with qtbot.waitExposed(window):
        window.show()
    chapter = app_module.open_folder(folder)
    assert isinstance(chapter, Chapter), f"precondition: {folder} opened as {chapter!r}"
    window.show_summary(chapter)
    _settle()
    return window


def _setup(tmp_path: Path, build_batch: Any, builder: Builder | None = None) -> RunSetup:
    models = tmp_path / "models"
    return RunSetup(  # type: ignore[call-arg]
        lambda: models,
        builder if builder is not None else Builder(),
        _gemini,
        build_batch=build_batch,
    )


def _press_start(window: MainWindow) -> None:
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary), f"central widget is {summary!r}"
    button = summary.findChild(QPushButton, "summary-start")
    assert button is not None
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    _settle()


def _until(qtbot: Any, condition: Callable[[], bool], what: str, timeout: int = WAIT_MS) -> None:
    try:
        qtbot.waitUntil(condition, timeout=timeout)
    except Exception:
        pytest.fail(f"after {timeout} ms: {what}")


def _waiting_panel(qtbot: Any, window: MainWindow) -> Any:
    panel_type = _batch_panel_type()
    _until(
        qtbot,
        lambda: isinstance(window.centralWidget(), panel_type),
        "the window never showed the BatchWaitingPanel",
    )
    _settle()
    return window.centralWidget()


def _batch_run(window: MainWindow) -> Any:
    controller = getattr(window, "batch_run", None)
    assert controller is not None, "window.batch_run is None after a batch Start (C-6, A-R2)"
    return controller


def _elapse(window: MainWindow) -> None:
    timer = _batch_run(window).poll_timer
    assert timer.isActive(), "the poll timer is not armed, so it would never fire"
    timer.stop()
    timer.timeout.emit()


def _steps(panel: RunProgressPanel) -> list[str]:
    return [label.accessibleName() for label in panel.stepper.findChildren(QLabel, "stage-step")]


def _pending(folder: Path) -> tuple[BatchJob, ...]:
    with open_project(project_dir_for(folder)) as project:
        return pending_jobs(project)


def _started_batch(
    qtbot: Any,
    world: World,
    tmp_path: Path,
    collect: FakeCollect,
    submit: ChapterSubmit | None = None,
) -> tuple[MainWindow, Any, Path]:
    """Start pressed on a three-page chapter, waited until the waiting panel."""
    folder = _folder(tmp_path)
    batch = _batch_setup(
        submit=submit if submit is not None else ChapterSubmit(), collect=collect, ceiling=_ceiling
    )
    window = _window(qtbot, world, folder, _setup(tmp_path, BatchBuilder(batch)))
    _press_start(window)
    return window, _waiting_panel(qtbot, window), folder


# =============================================================================
# AC-1: Start on Gemini - local stages, then the waiting panel
# =============================================================================


def test_start_on_gemini_shows_the_local_stages_with_the_batch_stepper(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    gate = _Gate()
    world.gates.append(gate.release)
    submit = ChapterSubmit(prelude_gate=gate)
    batch = _batch_setup(submit=submit, collect=FakeCollect(), ceiling=_ceiling)
    builder = Builder()
    window = _window(
        qtbot, world, _folder(tmp_path), _setup(tmp_path, BatchBuilder(batch), builder)
    )

    _press_start(window)
    _until(qtbot, gate.entered.is_set, "the run never reached the glossary pass")
    _settle()

    panel = window.centralWidget()
    assert isinstance(panel, RunProgressPanel), f"while the batch runs the window shows {panel!r}"
    _until(
        qtbot,
        lambda: _steps(panel) == ["Detecting: done", "Reading: done", "Done: done"],
        f"the stepper reads {_steps(panel)}; AC-1 is Detecting, Reading, Done - no Translating",
    )
    assert panel.overall_label.text() == "Page 3 of 3"
    gate.release.set()
    _waiting_panel(qtbot, window)
    assert builder.calls == [], "the batch path built the per-page stage list"
    assert submit.models == [tmp_path / "models"], "the batch submit was not given the models"


def test_on_batch_submitted_the_window_shows_what_was_submitted_and_when(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    gate = _Gate()
    world.gates.append(gate.release)
    batch = _batch_setup(
        submit=ChapterSubmit(prelude_gate=gate), collect=FakeCollect(), ceiling=_ceiling
    )
    folder = _folder(tmp_path)
    window = _window(qtbot, world, folder, _setup(tmp_path, BatchBuilder(batch)))
    _press_start(window)
    _until(qtbot, gate.entered.is_set, "the run never reached the glossary pass")

    before = _now()
    gate.release.set()
    panel = _waiting_panel(qtbot, window)
    after = _now()

    assert panel.submitted.text() in {
        f"Submitted 3 pages as one batch at {t}; waiting for Gemini."
        for t in (hhmm(before), hhmm(after))
    }, f"the waiting panel reads {panel.submitted.text()!r}"
    assert panel.projection.text() == "Projected $0.06 of $1.50", (
        "the projection is BatchSubmitted's next_call against the stored ceiling"
    )
    assert not panel.projection.isHidden()
    assert panel.last_checked.text() == ""
    assert [(j.first_ordinal, j.last_ordinal) for j in _pending(folder)] == [(0, 2)]


def test_a_volume_sent_as_two_jobs_reads_as_two_batches(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    before = _now()
    _win, panel, folder = _started_batch(
        qtbot, world, tmp_path, FakeCollect(), ChapterSubmit(size=EIGHT_MB)
    )
    after = _now()

    assert panel.submitted.text() in {
        f"Submitted 3 pages as 2 batches at {t}; waiting for Gemini."
        for t in (hhmm(before), hhmm(after))
    }
    assert [(j.first_ordinal, j.last_ordinal) for j in _pending(folder)] == [(0, 1), (2, 2)]


def test_start_asks_for_the_batch_after_the_models_and_before_creating_the_project(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    database = project_dir_for(folder) / "project.db"
    order: list[str] = []
    models = tmp_path / "models"

    def resolve() -> Path:
        order.append(f"models (project exists: {database.exists()})")
        return models

    batch = _batch_setup(submit=ChapterSubmit(), collect=FakeCollect(), ceiling=_ceiling)
    builder = BatchBuilder(
        batch, on_call=lambda: order.append(f"batch (project exists: {database.exists()})")
    )
    setup = RunSetup(resolve, Builder(), _gemini, build_batch=builder)  # type: ignore[call-arg]
    window = _window(qtbot, world, folder, setup)

    _press_start(window)
    _waiting_panel(qtbot, window)

    assert order == ["models (project exists: False)", "batch (project exists: False)"]
    assert builder.calls == 1
    assert database.is_file(), "the batch Start created no project"


def test_a_provider_error_from_the_batch_builder_is_shown_and_creates_nothing(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    error = NoApiKey("no API key is set: set GEMINI_API_KEY")
    window = _window(qtbot, world, folder, _setup(tmp_path, BatchBuilder(raises=error)))

    _press_start(window)

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget), f"after the refusal the window shows {target!r}"
    assert target.headline.text() == str(error)
    assert not project_dir_for(folder).exists(), "a refused batch Start created a project"


# =============================================================================
# AC-2 through the window: the poll's lines and the review
# =============================================================================


def test_a_poll_that_leaves_the_job_pending_shows_when_it_was_checked(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    window, panel, _folder = _started_batch(qtbot, world, tmp_path, FakeCollect("pending"))

    before = _now()
    _elapse(window)
    _until(qtbot, lambda: panel.last_checked.text() != "", "the poll never reported back")
    after = _now()

    assert panel.last_checked.text() in {f"Last checked {t}." for t in (hhmm(before), hhmm(after))}
    _until(
        qtbot,
        lambda: _batch_run(window).poll_timer.isActive(),
        "the window's poll timer was not armed again",
    )
    assert window.opened is None


def test_a_poll_that_collects_every_job_opens_the_review(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    window, _panel, folder = _started_batch(qtbot, world, tmp_path, FakeCollect("collected"))

    _elapse(window)
    _until(qtbot, lambda: isinstance(window.opened, Workspace), "the review never opened")
    _settle()

    workspace = window.opened
    assert isinstance(workspace, Workspace)
    qtbot.addWidget(workspace)
    assert workspace.page_strip.count() == 3
    assert not window.isVisible(), "the intake window is still open after the review opened"
    assert _pending(folder) == ()


@pytest.mark.parametrize("state", ["failed", "expired"])
def test_a_failed_job_shows_the_banner_and_polling_stops(
    qtbot: Any, world: World, tmp_path: Path, state: str
) -> None:
    window, panel, _folder = _started_batch(qtbot, world, tmp_path, FakeCollect(state))

    _elapse(window)
    _until(qtbot, lambda: panel.banner is not None, "a failed job showed no banner")
    _settle()

    banner = panel.banner
    assert isinstance(banner, ErrorBanner)
    assert banner.headline.text() == f"Batch job failed {EM} Gemini reports it {state}."
    assert banner.body.text() == "Its pages were not translated."
    assert banner.actions == ()
    assert window.centralWidget() is panel, "a failed job left the waiting panel"
    assert not _batch_run(window).poll_timer.isActive(), "polling continued after a failed job"
    assert window.opened is None


def test_a_poll_that_raises_shows_the_error_with_the_time_and_polling_continues(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    window, panel, _folder = _started_batch(qtbot, world, tmp_path, FakeCollect("raise"))

    before = _now()
    _elapse(window)
    _until(qtbot, lambda: panel.last_checked.text() != "", "the failed poll was never shown")
    after = _now()

    assert panel.last_checked.text() in {
        f"Last checked {t}: ConnectionError: the network is unreachable"
        for t in (hhmm(before), hhmm(after))
    }
    _until(
        qtbot,
        lambda: _batch_run(window).poll_timer.isActive(),
        "polling stopped after a poll raised",
    )
    assert panel.banner is None


# =============================================================================
# AC-4: the budget refusal
# =============================================================================


def test_a_volume_over_the_stored_ceiling_is_refused_after_the_local_stages(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    submit = ChapterSubmit(ceiling_micro=TIGHT_CEILING_MICRO)
    collect = FakeCollect()
    batch = _batch_setup(submit=submit, collect=collect, ceiling=_ceiling)
    window = _window(qtbot, world, folder, _setup(tmp_path, BatchBuilder(batch)))

    _press_start(window)
    panel = window.centralWidget()
    assert isinstance(panel, RunProgressPanel), f"the batch Start shows {panel!r}"
    _until(qtbot, lambda: panel.banner is not None, "the refused batch showed no banner")
    _settle()

    banner = panel.banner
    assert isinstance(banner, ErrorBanner)
    # AM-1: the refusal names what the batch would have cost. That is
    # submit_volume's own projection of the whole volume: 3 pages x $0.02 (the
    # batch estimate), $0.06, against the stored $0.05.
    assert banner.headline.text() == (
        f"Batch not submitted {EM} projected $0.06 exceeds the $0.05 budget."
    )
    assert banner.body.text() == "No pages were translated."
    assert banner.actions == (), "a refused batch offers an action"
    readout = panel.cost_readout
    assert (readout.figure.text(), readout.budget_label.text(), readout.state()) == (
        "$0.00",
        "of $0.05",
        "aborted",
    )
    assert _steps(panel) == ["Detecting: done", "Reading: done", "Done: done"], (
        "the local stages did not run before the refusal"
    )
    assert submit.submitted == [], "a refused volume was handed to the provider"
    assert _pending(folder) == (), "a job is pending after the refusal"
    assert window.centralWidget() is panel, "the refusal left the run panel"
    assert collect.calls == []


# =============================================================================
# AC-5: no batch - today's per-page run, untouched
# =============================================================================


class _PerPage:
    def __init__(self, name: str, calls: list[tuple[str, int]]) -> None:
        self.name = name
        self._calls = calls

    def run(self, ctx: PageContext) -> None:
        self._calls.append((self.name, ctx.page.ordinal))

    def is_done(self, ctx: PageContext) -> bool:
        return False


def test_a_provider_with_no_batch_runs_the_per_page_pipeline_as_before(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    calls: list[tuple[str, int]] = []
    builder = Builder([_PerPage("detect", calls), _PerPage("translate", calls)])
    batch_builder = BatchBuilder(None)
    folder = _folder(tmp_path)
    window = _window(qtbot, world, folder, _setup(tmp_path, batch_builder, builder))

    _press_start(window)

    assert batch_builder.calls == 1
    assert builder.calls == [tmp_path / "models"], "no batch: the per-page stages are built"
    assert isinstance(window.run, RunController)
    assert getattr(window, "batch_run", None) is None
    panel = window.centralWidget()
    assert isinstance(panel, RunProgressPanel)
    assert len(panel.stepper.step_states()) == 4, "the per-page run lost its Translating step"
    _until(qtbot, lambda: isinstance(window.opened, Workspace), "the per-page run never finished")
    assert calls == [(name, n) for n in range(3) for name in ("detect", "translate")]
    assert _pending(folder) == ()


def test_a_setup_with_no_batch_builder_runs_the_per_page_pipeline(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    """PO-1: `build_batch` defaulted to `None` means "no batch"."""
    calls: list[tuple[str, int]] = []
    builder = Builder([_PerPage("detect", calls)])
    models = tmp_path / "models"
    window = _window(qtbot, world, _folder(tmp_path), RunSetup(lambda: models, builder, _gemini))

    _press_start(window)

    assert builder.calls == [models]
    assert isinstance(window.run, RunController)
    _until(qtbot, lambda: isinstance(window.opened, Workspace), "the per-page run never finished")


# =============================================================================
# AC-6: closing the window while waiting
# =============================================================================


def test_closing_while_a_poll_is_in_flight_waits_for_it_and_leaves_the_job_pending(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    gate = threading.Event()
    world.gates.append(gate)
    collect = FakeCollect("pending", gate=gate)
    window, _panel, folder = _started_batch(qtbot, world, tmp_path, collect)
    controller = _batch_run(window)
    _elapse(window)
    _until(qtbot, lambda: len(collect.calls) == 1, "the poll never started")

    release = threading.Timer(HOLD_S, gate.set)
    release.start()
    started = time.perf_counter()
    window.close()
    held = time.perf_counter() - started
    release.join()
    _settle()

    assert collect.returned == 1, "the window closed while its poll was still in flight"
    assert held >= HOLD_S * 0.5, f"close() returned after {held:.3f} s, before the poll did"
    assert not controller.poll_timer.isActive(), "the poll timer is armed after the close"
    assert collect.calls == [_pending(folder)[0].id], "closing polled or settled the job"
    assert window.opened is None


def test_closing_while_waiting_stops_the_timer_and_polls_nothing_more(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    collect = FakeCollect("pending")
    window, _panel, folder = _started_batch(qtbot, world, tmp_path, collect)
    controller = _batch_run(window)

    window.close()
    _settle()

    assert not controller.poll_timer.isActive()
    assert collect.calls == []
    assert len(_pending(folder)) == 1, "closing the window settled the job"
