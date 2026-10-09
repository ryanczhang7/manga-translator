"""MT-059: "Start run" translates the chapter from the window.

`mangatl.ui.run` (new, C-1) is the worker thread `architecture.md` §6 promised
and no story built: a `RunController` that runs `run_chapter` off the GUI
thread on its own `Project` and delivers every `RunEvent` back to the GUI
thread, in order. `MainWindow` (C-3, C-4) runs the Start sequence in
`mangatl-run`'s order and hands over to the review `Workspace`; `mangatl.app`
(C-6) is the composition root that resolves `MANGATL_MODELS` and builds the
stage list, injected into the window as a `RunSetup`.

Oracle partition (story `## Contract` C-9):

- **Settled, read out and spelled here:** "Start run" / "Start run anyway"
  (`test_start_button.py` pins the button itself), the `cli.main` call order
  (models, create, build, run), `NO_MODELS` character for character, no
  `<folder>_en`, the failed banner's copy (`test_run_failed_state.py` in full).
- **Mechanical, each with its control:**
  AC-2 - a fake stage records its thread, which must not be the main thread;
  and a GUI `QTimer` must fire while a fake stage is blocked on a
  `threading.Event` that only that timer sets. AC-3 - a fake stage list
  emitting a known 100+ event sequence is received as exactly that sequence,
  every receipt on the main thread. AC-6 - a fake stage blocked until
  `RunController.cancel` has been called; after `close()` returns the worker
  has returned and closed its project, the run row is `aborted`/`cancelled`,
  earlier pages are `done` and the project reopens and resumes. AC-7 - the
  REAL `mangatl.app.resolve_models` with `MANGATL_MODELS` unset / empty / a
  file / a missing path, and the control: an existing directory reaches the
  builder exactly once, exactly. AC-8 - a keyless and a keyed run record the
  same stage calls up to the fake translate stage that raises; the banner holds
  the reason; and a recording `os.environ` sees `MANGATL_MODELS` read (the
  recorder's own control) and `ANTHROPIC_API_KEY` never.

No test loads weights, builds an Anthropic client or touches the network: every
stage list here is a fake implementing `mangatl.pipeline.stage.Stage`.

**Threads.** Every wait is bounded and fails loudly; nothing here can hang the
suite if the worker runs on the GUI thread instead (DV-1): a blocked fake stage
gives up after `GATE_S`, and every wait for the GUI is a `qtbot.waitUntil` with
a timeout. The `world` fixture releases every gate, cancels every controller,
waits (bounded) for it to stop and then `wait()`s it, so no worker outlives
its test. The budgets are liveness bounds, not cost estimates: a fake run of
five pages takes milliseconds (measured in RED, see the story's `## Handoff`),
so 10 s is two orders of magnitude of headroom for the coverage-instrumented
run on CI hardware.

**RED:** this file fails at import (`mangatl.ui.run` does not exist), so no
assertion in it has run; the story's handoff records each control's expected
value.
"""

from __future__ import annotations

import ast
import hashlib
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton

import mangatl.compose as compose_module
import mangatl.store.project as project_module
import mangatl.ui.run as run_module
from mangatl import app as app_module
from mangatl.domain.budget import DEFAULT_CEILING, Decision, Projection
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
from mangatl.domain.money import Usd
from mangatl.domain.page import Chapter
from mangatl.domain.region import RawRegion
from mangatl.pipeline.runner import RUN_ABORTED, RUN_FINISHED, RunOutcome, run_chapter
from mangatl.pipeline.stage import BudgetRefused, PageContext, PassThroughStage, Stage
from mangatl.store.intake import read_chapter
from mangatl.store.project import PAGE_DONE, Project, create_project, open_project, project_dir_for
from mangatl.ui import tokens_gen
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.main_window import WINDOW_TITLE, MainWindow
from mangatl.ui.progress import ErrorBanner, RunProgressPanel
from mangatl.ui.run import NO_MODELS, RunController, RunSetup
from mangatl.ui.summary import ChapterSummary
from mangatl.ui.workspace import Workspace

# --- Settled copy, spelled out (never read back from the module under test) -----
NO_MODELS_TEXT = (
    "No models folder: set MANGATL_MODELS to the folder holding the model"
    " weights, then start the app again."
)
EM = "\N{EM DASH}"
EN = "\N{EN DASH}"
KEY = "ANTHROPIC_API_KEY"
MODELS = "MANGATL_MODELS"

# --- Liveness bounds (see the module docstring) ----------------------------------
#: How long the GUI waits for a run of up to `PAGES_AT_BASE` pages to reach a
#: state. Measured in RED (local, Windows, against a scratch candidate, under
#: `--cov`): every test of 5 pages or fewer took <= 1.4 s whole, the 34-page
#: one 3.25 s; plain, <= 0.33 s. Not yet measured on CI - GREEN's first CI run
#: is the first CI number, and the story's handoff says so.
BASE_RUN_MS = 20_000
PAGES_AT_BASE = 5
RUN_MS = BASE_RUN_MS
#: The longest any fake stage blocks before giving up on its gate. Also what a
#: worker run on the GUI thread (DV-1) costs a failing test, instead of a hang.
GATE_S = 10.0


def _run_ms(pages: int) -> int:
    """`BASE_RUN_MS` scaled by the run's size, never below it."""
    return int(BASE_RUN_MS * max(1.0, pages / PAGES_AT_BASE))


#: AC-6: how long the blocked stage keeps working after the cancel, so a
#: `closeEvent` that does not wait for the worker returns visibly before it.
AFTER_CANCEL_S = 0.2

#: Captured before any test can replace it: the fake translate stage stands in
#: for the Anthropic client, which reads the key itself at request time.
_REAL_ENVIRON = os.environ


# =============================================================================
# Folders, projects and pages
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


@pytest.fixture(scope="module")
def page_png() -> bytes:
    return _png(QSize(60, 80))


@pytest.fixture(scope="module")
def mask_png() -> bytes:
    return _png(QSize(4, 4))


def _pages_folder(root: Path, name: str, count: int, png: bytes) -> Path:
    folder = root / name
    folder.mkdir()
    for index in range(count):
        (folder / f"{index + 1:02d}.png").write_bytes(png)
    return folder.resolve()


def _hashes(folder: Path) -> dict[str, str | None]:
    """Every path under `folder`, with the SHA-256 of every file."""
    return {
        str(p.relative_to(folder)): (
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        )
        for p in sorted(folder.rglob("*"))
    }


def _project_dir(folder: Path) -> Path:
    return project_dir_for(folder)


def _created(folder: Path) -> Path:
    """A closed project for `folder`, as Start would leave it before the run."""
    project_dir = _project_dir(folder)
    with create_project(read_chapter(folder), project_dir):
        pass
    return project_dir


def _statuses(project_dir: Path) -> list[str]:
    with open_project(project_dir) as project:
        return [project.page_status(page.ordinal) for page in project.pages()]


def _run_rows(project_dir: Path) -> list[tuple[Any, ...]]:
    with open_project(project_dir) as project:
        return project.select("SELECT outcome, aborted_reason FROM run ORDER BY id")


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# Fake stages (the `Stage` protocol: name, run(ctx), is_done(ctx))
# =============================================================================


@dataclass
class Calls:
    """What every fake stage did, in order, from whichever thread ran it."""

    made: list[tuple[str, int]] = field(default_factory=list)
    threads: list[threading.Thread] = field(default_factory=list)


class FakeStage:
    """A stage that records each call and then does `action(ctx)`, if any."""

    def __init__(
        self,
        name: str,
        calls: Calls,
        action: Callable[[PageContext], None] | None = None,
    ) -> None:
        self.name = name
        self._calls = calls
        self._action = action

    def run(self, ctx: PageContext) -> None:
        self._calls.made.append((self.name, ctx.page.ordinal))
        self._calls.threads.append(threading.current_thread())
        if self._action is not None:
            self._action(ctx)

    def is_done(self, ctx: PageContext) -> bool:
        return False


def _on_page(ordinal: int, action: Callable[[PageContext], None]) -> Callable[[PageContext], None]:
    def act(ctx: PageContext) -> None:
        if ctx.page.ordinal == ordinal:
            action(ctx)

    return act


class Gate:
    """Blocks the stage that calls it until `release` is set, for at most
    `GATE_S`; `opened` says whether it was released or gave up."""

    def __init__(self, release: threading.Event | None = None, linger_s: float = 0.0) -> None:
        self.entered = threading.Event()
        self.release = release if release is not None else threading.Event()
        self.opened: bool | None = None
        self._linger_s = linger_s

    def __call__(self, ctx: PageContext) -> None:
        self.entered.set()
        self.opened = self.release.wait(GATE_S)
        if self._linger_s:
            time.sleep(self._linger_s)


def _raise(error: Exception) -> Callable[[PageContext], None]:
    def act(ctx: PageContext) -> None:
        raise error

    return act


def usd(text: str) -> Usd:
    return Usd(Decimal(text))


def _refusal() -> BudgetRefused:
    projection = Projection(
        next_call=usd("0.10"), remaining_chapter=usd("0.20"), basis="observed", sample_count=3
    )
    return BudgetRefused(
        Decision(
            permitted=False,
            reason="the projected next call would exceed the budget",
            spent=usd("1.95"),
            ceiling=DEFAULT_CEILING,
            projection=projection,
        )
    )


class Builder:
    """A `StageBuilder` that records every call and returns `stages`."""

    def __init__(self, stages: Sequence[Stage] = (), on_call: Callable[[], None] | None = None):
        self.calls: list[Path] = []
        self._stages = tuple(stages)
        self._on_call = on_call

    def __call__(self, models_dir: Path) -> Sequence[Stage]:
        self.calls.append(models_dir)
        if self._on_call is not None:
            self._on_call()
        return self._stages


def _models(path: Path) -> Callable[[], Path | None]:
    return lambda: path


# =============================================================================
# Receiving the stream, and cleaning up after it
# =============================================================================


class Recorder(QObject):
    """A GUI-thread receiver: every `event` and `ended`, in arrival order, with
    whether it arrived on the main thread. A `QObject` with slots, as the
    window's own receivers are, so delivery is Qt's queued connection."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[str, object, bool]] = []

    @Slot(object)
    def on_event(self, event: object) -> None:
        self.log.append(("event", event, threading.current_thread() is threading.main_thread()))

    @Slot(object)
    def on_ended(self, outcome: object) -> None:
        self.log.append(("ended", outcome, threading.current_thread() is threading.main_thread()))

    @property
    def events(self) -> list[object]:
        return [item for kind, item, _ in self.log if kind == "event"]

    @property
    def outcome(self) -> RunOutcome | None:
        ended = [item for kind, item, _ in self.log if kind == "ended"]
        assert len(ended) <= 1, f"ended was emitted {len(ended)} times"
        return ended[0] if ended else None  # type: ignore[return-value]


@dataclass
class World:
    """Everything a test started, so teardown can stop all of it."""

    gates: list[Gate] = field(default_factory=list)
    runs: list[RunController] = field(default_factory=list)
    windows: list[QMainWindow] = field(default_factory=list)


@pytest.fixture
def world(qtbot) -> Iterator[World]:  # type: ignore[no-untyped-def]
    made = World()
    yield made
    for gate in made.gates:
        gate.release.set()
    runs = list(made.runs) + [getattr(w, "run", None) for w in made.windows]
    for run in runs:
        if not isinstance(run, RunController):
            continue
        run.cancel()
        qtbot.waitUntil(lambda run=run: not run.is_running(), timeout=RUN_MS)
        run.wait()
    _settle()
    for window in made.windows:
        opened = getattr(window, "opened", None)
        if isinstance(opened, QMainWindow):
            opened.close()
        window.close()
    _settle()


def _controller(
    world: World, project_dir: Path, stages: Sequence[Stage]
) -> tuple[RunController, Recorder]:
    run = RunController(project_dir, stages)
    world.runs.append(run)
    recorder = Recorder()
    run.event.connect(recorder.on_event)
    run.ended.connect(recorder.on_ended)
    return run, recorder


def _wait_ended(qtbot, recorder: Recorder) -> RunOutcome:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(lambda: recorder.outcome is not None, timeout=RUN_MS)
    outcome = recorder.outcome
    assert isinstance(outcome, RunOutcome), f"ended carried {outcome!r}, not a RunOutcome"
    return outcome


def _normalised(events: Sequence[object]) -> list[object]:
    """`StageFinished.elapsed_ms` is a measured duration; everything else is exact."""
    return [replace(e, elapsed_ms=0) if isinstance(e, StageFinished) else e for e in events]


# =============================================================================
# The window and the Start press
# =============================================================================


def _show(qtbot, world: World, window: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.addWidget(window)
    world.windows.append(window)
    window.resize(900, 600)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()


def _window(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    folder: Path,
    run_setup: RunSetup | None,
) -> MainWindow:
    """The intake window showing `folder`'s summary, as `mangatl <folder>` builds it."""
    window = (
        MainWindow(open_folder=app_module.open_folder)
        if run_setup is None
        else MainWindow(open_folder=app_module.open_folder, run_setup=run_setup)
    )
    _show(qtbot, world, window)
    chapter = app_module.open_folder(folder)
    assert isinstance(chapter, Chapter), f"precondition: {folder} opened as {chapter!r}"
    window.show_summary(chapter)
    _settle()
    return window


def _start_button(window: QMainWindow) -> QPushButton:
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary), (
        f"central widget is {type(summary).__name__}, not the ChapterSummary"
    )
    button = summary.findChild(QPushButton, "summary-start")
    assert button is not None, "the summary has no QPushButton named 'summary-start'"
    return button


def _press_start(window: QMainWindow) -> None:
    QTest.mouseClick(_start_button(window), Qt.MouseButton.LeftButton)
    _settle()


def _panel(window: MainWindow) -> RunProgressPanel:
    panel = window.run_panel
    assert isinstance(panel, RunProgressPanel), f"run_panel is {panel!r}"
    assert window.centralWidget() is panel, (
        f"the central widget is {type(window.centralWidget()).__name__}, not the run panel"
    )
    return panel


def _wait_run_ended(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    run = window.run
    assert isinstance(run, RunController), f"window.run is {run!r} after Start"
    qtbot.waitUntil(lambda: not run.is_running(), timeout=RUN_MS)
    run.wait()
    _settle()


def _wait_workspace(qtbot, window: MainWindow, pages: int = PAGES_AT_BASE) -> Workspace:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(lambda: isinstance(window.opened, Workspace), timeout=_run_ms(pages))
    opened = window.opened
    assert isinstance(opened, Workspace)
    qtbot.addWidget(opened)
    _settle()
    return opened


def _capture_app_projects(monkeypatch: pytest.MonkeyPatch) -> list[Project]:
    """Every `Project` `mangatl.app.open_folder` opens for the `Workspace`."""
    opened: list[Project] = []
    real = app_module.open_project

    def capture(project_dir: Path) -> Project:
        project = real(project_dir)
        opened.append(project)
        return project

    monkeypatch.setattr(app_module, "open_project", capture)
    return opened


def _quick_stages(calls: Calls) -> tuple[Stage, ...]:
    return (FakeStage("detect", calls), FakeStage("translate", calls))


# =============================================================================
# C-1: the constants and the export shape
# =============================================================================


def test_the_no_models_sentence_is_the_po_wording_character_for_character() -> None:
    assert NO_MODELS == NO_MODELS_TEXT
    assert "--models" not in NO_MODELS


def test_run_setup_is_a_frozen_pair_of_a_resolver_and_a_builder(tmp_path: Path) -> None:
    builder = Builder()
    setup = RunSetup(resolve_models=_models(tmp_path), build_stages=builder)

    assert setup.resolve_models() == tmp_path
    assert setup.build_stages(tmp_path) == ()
    with pytest.raises(AttributeError):
        setup.resolve_models = _models(tmp_path)  # type: ignore[misc]


# =============================================================================
# AC-2: the stages run off the GUI thread, and the GUI keeps processing events
# =============================================================================


def test_start_returns_at_once_while_a_stage_is_still_running(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    gate = Gate()
    world.gates.append(gate)
    calls = Calls()
    run, recorder = _controller(
        world,
        _created(_pages_folder(tmp_path, "ch", 2, page_png)),
        [FakeStage("detect", calls, gate)],
    )

    run.start()

    assert gate.opened is None, "start() returned only after the blocked stage gave up"
    assert run.is_running(), "start() returned and the run is not running"
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    gate.release.set()
    assert _wait_ended(qtbot, recorder).outcome == RUN_FINISHED


def test_the_stages_run_on_a_thread_that_is_not_the_gui_thread(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    calls = Calls()
    run, recorder = _controller(
        world, _created(_pages_folder(tmp_path, "ch", 3, page_png)), _quick_stages(calls)
    )

    run.start()
    _wait_ended(qtbot, recorder)

    assert len(calls.threads) == 6, f"{len(calls.threads)} stage calls, expected 3 pages x 2"
    on_gui = [t.name for t in calls.threads if t is threading.main_thread()]
    assert on_gui == [], f"stages ran on the GUI thread: {on_gui}"


def test_a_gui_timer_fires_while_a_stage_is_blocked_on_an_event_only_it_sets(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    """The stage blocks until the GUI's timer releases it, and the timer only
    releases it once the stage has said it is blocked. A worker run on the GUI
    thread starves the timer: the stage gives up after `GATE_S` and `opened` is
    False (DV-1 - a bounded failure, never a hang)."""
    gate = Gate()
    world.gates.append(gate)
    ticks_while_blocked: list[bool] = []

    def tick() -> None:
        if gate.entered.is_set() and not gate.release.is_set():
            ticks_while_blocked.append(threading.current_thread() is threading.main_thread())
            gate.release.set()

    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(tick)
    timer.start()
    try:
        calls = Calls()
        run, recorder = _controller(
            world,
            _created(_pages_folder(tmp_path, "ch", 1, page_png)),
            [FakeStage("detect", calls, gate)],
        )
        run.start()
        _wait_ended(qtbot, recorder)
    finally:
        timer.stop()

    assert gate.opened is True, (
        "the stage was never released: the GUI timer did not fire while it was blocked"
    )
    assert ticks_while_blocked == [True], (
        f"releasing ticks (on main thread?): {ticks_while_blocked}"
    )


# =============================================================================
# AC-3: every event reaches the GUI thread, in emission order
# =============================================================================

#: AC-3's known sequence: each page's translate stage emits a burst of priced
#: calls, so a bridge that reorders or drops under load is visible.
BURST = 20
PROJ = Projection(
    next_call=usd("0.01"), remaining_chapter=usd("0.02"), basis="estimate", sample_count=0
)


def _priced(ordinal: int, index: int) -> CallPriced:
    cents = ordinal * BURST + index + 1
    return CallPriced(
        ordinal=ordinal, spent=Usd(Decimal(cents) / 100), ceiling=DEFAULT_CEILING, projection=PROJ
    )


def _burst(ctx: PageContext) -> None:
    for index in range(BURST):
        ctx.emit(_priced(ctx.page.ordinal, index))


def _expected_sequence(pages: int) -> list[RunEvent]:
    expected: list[RunEvent] = [RunStarted(run_id=1, page_count=pages)]
    for ordinal in range(pages):
        expected += [
            PageStarted(ordinal=ordinal),
            StageFinished(ordinal=ordinal, stage="detect", elapsed_ms=0),
            *[_priced(ordinal, index) for index in range(BURST)],
            StageFinished(ordinal=ordinal, stage="translate", elapsed_ms=0),
        ]
    expected.append(RunFinished(run_id=1, pages_done=pages))
    return expected


def test_a_known_event_sequence_is_received_exactly_in_order_on_the_main_thread(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    calls = Calls()
    stages = (FakeStage("detect", calls), FakeStage("translate", calls, _burst))
    run, recorder = _controller(world, _created(_pages_folder(tmp_path, "ch", 5, page_png)), stages)

    run.start()
    outcome = _wait_ended(qtbot, recorder)

    expected = _expected_sequence(5)
    assert len(expected) == 117
    assert _normalised(recorder.events) == expected
    off_main = [kind for kind, _, on_main in recorder.log if not on_main]
    assert off_main == [], f"{len(off_main)} receipts were not on the main thread"
    assert recorder.log[-1][0] == "ended", "ended was not the last thing received"
    assert outcome == RunOutcome(run_id=1, outcome=RUN_FINISHED, pages_done=5, aborted_reason=None)


def test_the_stream_drives_the_progress_panel_and_the_cost_readout(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    calls = Calls()
    stages = (FakeStage("detect", calls), FakeStage("translate", calls, _burst))
    run, recorder = _controller(world, _created(_pages_folder(tmp_path, "ch", 3, page_png)), stages)
    panel = RunProgressPanel()
    qtbot.addWidget(panel)
    run.event.connect(panel.on_event)

    run.start()
    _wait_ended(qtbot, recorder)

    assert (panel.overall.maximum(), panel.overall.value()) == (3, 3)
    assert panel.overall_label.text() == "Page 3 of 3"
    assert panel.cost_readout.figure.text() == "$0.60", "the last CallPriced is not shown"
    assert panel.cost_readout.state() == "normal"


# =============================================================================
# C-1: the worker's own Project, cancel and wait
# =============================================================================


def _capture_worker_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[Project, threading.Thread]], list[Project]]:
    """Every `Project` the worker opens through `mangatl.ui.run`, with its
    thread, and every `Project` closed anywhere (`__exit__`)."""
    opened: list[tuple[Project, threading.Thread]] = []
    exited: list[Project] = []
    real_open = run_module.open_project
    real_exit = project_module.Project.__exit__

    def capture(project_dir: Path) -> Project:
        project = real_open(project_dir)
        opened.append((project, threading.current_thread()))
        return project

    def record_exit(self: Project, *exc: object) -> None:
        real_exit(self, *exc)
        exited.append(self)

    monkeypatch.setattr(run_module, "open_project", capture)
    monkeypatch.setattr(project_module.Project, "__exit__", record_exit)
    return opened, exited


def test_the_worker_opens_its_own_project_on_its_own_thread_and_closes_it(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    project_dir = _created(_pages_folder(tmp_path, "ch", 2, page_png))
    opened, exited = _capture_worker_projects(monkeypatch)
    calls = Calls()
    run, recorder = _controller(world, project_dir, _quick_stages(calls))

    run.start()
    _wait_ended(qtbot, recorder)
    run.wait()

    assert len(opened) == 1, f"the worker opened {len(opened)} projects"
    project, thread = opened[0]
    assert thread is not threading.main_thread(), (
        "the worker's project was opened on the GUI thread"
    )
    assert thread is calls.threads[0], "the project was opened on another thread than the stages'"
    assert any(p is project for p in exited), "the worker never closed its project"


def test_cancel_stops_the_run_at_the_next_stage_boundary_through_cancelled(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    project_dir = _created(_pages_folder(tmp_path, "ch", 3, page_png))
    gate = Gate()
    world.gates.append(gate)
    calls = Calls()
    stages = (FakeStage("detect", calls, _on_page(1, gate)), FakeStage("translate", calls))
    run, recorder = _controller(world, project_dir, stages)

    run.start()
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    run.cancel()
    gate.release.set()
    outcome = _wait_ended(qtbot, recorder)

    assert (outcome.outcome, outcome.aborted_reason, outcome.pages_done) == (
        RUN_ABORTED,
        "cancelled",
        1,
    )
    assert recorder.events[-1] == RunAborted(reason="cancelled", ordinal=None)
    assert calls.made == [("detect", 0), ("translate", 0), ("detect", 1)]
    assert _statuses(project_dir) == [PAGE_DONE, "pending", "pending"]


def test_wait_blocks_until_the_worker_has_returned_and_closed_its_project(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    project_dir = _created(_pages_folder(tmp_path, "ch", 2, page_png))
    opened, exited = _capture_worker_projects(monkeypatch)
    gate = Gate(linger_s=AFTER_CANCEL_S)
    world.gates.append(gate)
    calls = Calls()
    run, _recorder = _controller(world, project_dir, [FakeStage("detect", calls, gate)])
    run.start()
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)

    run.cancel()
    gate.release.set()
    run.wait()  # no event loop: the worker must not need the GUI thread to finish

    assert not run.is_running(), "wait() returned while the run is still running"
    assert [p for p, _ in opened if any(p is e for e in exited)] == [p for p, _ in opened], (
        "wait() returned before the worker closed its project"
    )
    assert _run_rows(project_dir) == [(RUN_ABORTED, "cancelled")]


def test_wait_is_a_no_op_on_a_controller_that_never_started(
    world: World, tmp_path: Path, page_png: bytes
) -> None:
    run, _recorder = _controller(world, _created(_pages_folder(tmp_path, "ch", 1, page_png)), [])

    started = time.perf_counter()
    run.wait()

    assert time.perf_counter() - started < 1.0
    assert not run.is_running()


# =============================================================================
# AC-1: Start creates the project beside the folder and the run begins
# =============================================================================


def test_start_run_creates_the_project_beside_the_folder_and_the_run_begins(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    folder = _pages_folder(tmp_path, "Chapter 12", 3, page_png)
    before = _hashes(folder)
    gate = Gate()
    world.gates.append(gate)
    calls = Calls()
    builder = Builder(
        [FakeStage("detect", calls, _on_page(0, gate)), FakeStage("translate", calls)]
    )
    window = _window(qtbot, world, folder, RunSetup(_models(tmp_path), builder))
    assert window.run is None and window.run_panel is None, "a run exists before Start"
    assert _start_button(window).text() == "Start run"

    _press_start(window)

    assert (tmp_path / "Chapter 12.mtproj" / "project.db").is_file(), "no Chapter 12.mtproj"
    with open_project(tmp_path / "Chapter 12.mtproj") as project:
        assert [p.filename for p in project.pages()] == ["01.png", "02.png", "03.png"]
    panel = _panel(window)
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    qtbot.waitUntil(lambda: panel.overall_label.text() == "Page 1 of 3", timeout=RUN_MS)
    assert window.run is not None and window.run.is_running()
    assert _hashes(folder) == before, "Start wrote into the input folder"

    gate.release.set()
    _wait_workspace(qtbot, window)
    assert _hashes(folder) == before, "the run wrote into the input folder"


def test_start_run_anyway_on_an_over_budget_chapter_does_the_same(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    """34 pages at $0.06 is $2.04 against $2.00 (MT-058's boundary)."""
    folder = _pages_folder(tmp_path, "Long", 34, page_png)
    before = _hashes(folder)
    calls = Calls()
    builder = Builder(_quick_stages(calls))
    window = _window(qtbot, world, folder, RunSetup(_models(tmp_path), builder))
    assert _start_button(window).text() == "Start run anyway"

    _press_start(window)

    assert builder.calls == [tmp_path]
    assert (tmp_path / "Long.mtproj" / "project.db").is_file(), "no Long.mtproj"
    workspace = _wait_workspace(qtbot, window, pages=34)
    assert workspace.page_strip.count() == 34
    assert len(calls.made) == 68
    assert _hashes(folder) == before


def test_start_follows_mangatl_runs_order_models_then_create_then_build_then_run(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    folder = _pages_folder(tmp_path, "ch", 2, page_png)
    database = _project_dir(folder) / "project.db"
    order: list[str] = []

    def resolve() -> Path | None:
        order.append(f"models (project exists: {database.exists()})")
        return tmp_path

    def first_stage(ctx: PageContext) -> None:
        if not order[-1].startswith("run"):
            order.append(
                f"run on the GUI thread: {threading.current_thread() is threading.main_thread()}"
            )

    calls = Calls()
    builder = Builder(
        [FakeStage("detect", calls, first_stage)],
        on_call=lambda: order.append(f"build (project exists: {database.exists()})"),
    )
    window = _window(qtbot, world, folder, RunSetup(resolve, builder))

    _press_start(window)
    _wait_workspace(qtbot, window)

    assert order == [
        "models (project exists: False)",
        "build (project exists: True)",
        "run on the GUI thread: False",
    ]
    assert builder.calls == [tmp_path], "the builder was not called exactly once with the models"


def test_the_run_screen_is_the_progress_panel_alone_under_the_same_title(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    """D-2: the panel replaces the summary; focus is not left on a summary widget."""
    gate = Gate()
    world.gates.append(gate)
    calls = Calls()
    builder = Builder([FakeStage("detect", calls, gate)])
    window = _window(
        qtbot,
        world,
        _pages_folder(tmp_path, "ch", 1, page_png),
        RunSetup(_models(tmp_path), builder),
    )

    _press_start(window)

    panel = _panel(window)
    assert panel.objectName() == "run-progress"
    assert window.windowTitle() == WINDOW_TITLE == "mangatl"
    focus = QApplication.focusWidget()
    widget: QObject | None = focus
    while widget is not None:
        assert not isinstance(widget, ChapterSummary), f"focus was left on {focus!r} in the summary"
        widget = widget.parent()
    gate.release.set()


def test_the_run_screen_shows_the_chapters_page_and_its_markers_once_detected(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    mask_png: bytes,
) -> None:
    """**MT-062 AC-4** (with AC-1 end to end), through this file's real Start
    path: `MainWindow` builds the panel with the summary's `Chapter` (MT-062
    C-5), and the stage list holds a REAL `DetectStage` over a fake detector, so
    the `RegionsDetected` crossing the thread is the one the stage emits.

    The run is held on page 0's second stage (after detection) so the run
    screen is still up when it is looked at. The detector hands the regions over
    left first; reading order is right first (MT-009), so the first marker is
    the right-hand ring.

    Geometry, by hand: the pages are 60 x 80, so s = min(118/60, 158/80) = 59/30;
    the page is 118 x 157.333.., at (1, 1.333..). Page point (40, 5) maps to
    (1 + 40 * 59/30, 4/3 + 5 * 59/30) = (79.666.., 11.1666..).

    Imported inside the test (the precedent is `test_pipeline.py`'s union test)
    so that while `mangatl.ui.run_thumbnail` does not exist only this test fails,
    not the whole of MT-059's file.
    """
    from mangatl.pipeline.detect_stage import DetectStage
    from mangatl.ui.run_thumbnail import RunThumbnail

    page_colour = "#3060c0"
    folder = tmp_path / "Chapter 7"
    folder.mkdir()
    for index in range(2):
        image = QImage(60, 80, QImage.Format.Format_RGB32)
        image.fill(QColor(page_colour if index == 0 else "#30a050"))
        assert image.save(str(folder / f"{index + 1:02d}.png"), "PNG")
    right = ((40, 5), (55, 5), (55, 20), (40, 20), (40, 5))
    left = ((5, 5), (20, 5), (20, 20), (5, 20), (5, 5))

    def detector(image_bytes: bytes) -> Sequence[RawRegion]:
        return [
            RawRegion(polygon=ring, mask=mask_png, confidence=1.0, kind="bubble")
            for ring in (left, right)
        ]

    gate = Gate()
    world.gates.append(gate)
    calls = Calls()
    builder = Builder(
        [DetectStage(detect=detector), FakeStage("translate", calls, _on_page(0, gate))]
    )
    window = _window(qtbot, world, folder.resolve(), RunSetup(_models(tmp_path), builder))

    _press_start(window)

    panel = _panel(window)
    thumb = getattr(panel, "thumbnail", None)
    assert isinstance(thumb, RunThumbnail), (
        f"the run screen's panel has thumbnail {thumb!r}: the window did not hand it the chapter"
    )
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    qtbot.waitUntil(lambda: len(thumb.markers()) == 2, timeout=RUN_MS)

    assert thumb.accessibleName() == "Page 1: 2 text regions found"
    first = thumb.markers()[0][0]
    assert (first.x(), first.y()) == pytest.approx((239 / 3, 67 / 6), abs=1e-9), (
        "the first marker is not the right-hand ring mapped onto the 60 x 80 page's rect"
    )
    rendered = QImage(120, 160, QImage.Format.Format_ARGB32)
    rendered.setDevicePixelRatio(1.0)
    rendered.fill(QColor("#ff00ff"))
    thumb.render(rendered)
    assert QColor(rendered.pixel(60, 120)).name() == page_colour, (
        "the thumbnail is not showing page 1 of the chapter that was started"
    )

    gate.release.set()
    _wait_workspace(qtbot, window)


# =============================================================================
# AC-4: RunFinished opens the Workspace; nothing is rendered
# =============================================================================


def test_a_finished_run_opens_the_workspace_on_the_first_page_and_closes_the_intake(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    folder = _pages_folder(tmp_path, "Chapter 12", 3, page_png)
    projects = _capture_app_projects(monkeypatch)
    calls = Calls()
    window = _window(
        qtbot, world, folder, RunSetup(_models(tmp_path), Builder(_quick_stages(calls)))
    )

    _press_start(window)
    workspace = _wait_workspace(qtbot, window)

    assert workspace.isVisible(), "the Workspace was not shown"
    assert not window.isVisible(), "the intake window is still open"
    assert workspace.page_strip.count() == 3
    assert workspace.page_strip.currentRow() == 0, "the first page is not the one shown"
    assert _statuses(_project_dir(folder)) == [PAGE_DONE] * 3
    assert not (tmp_path / "Chapter 12_en").exists(), "the window wrote an output folder"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Chapter 12", "Chapter 12.mtproj"]

    assert len(projects) == 1, f"the hand-over opened {len(projects)} projects"
    assert projects[0].select("SELECT 1") == [(1,)], "the Workspace's project is not open"
    workspace.close()
    _settle()
    with pytest.raises(Exception, match="closed"):
        projects[0].select("SELECT 1")


# =============================================================================
# AC-5: an aborted run keeps what it did, and "Review pages 1-N" opens it
# =============================================================================


@pytest.mark.parametrize(
    ("error", "headline", "body"),
    [
        (
            _refusal(),
            f"Run stopped at page 3 of 4 {EM} the $2.00 budget was reached.",
            f"Pages 1{EN}2 are translated and can be reviewed and rendered.",
        ),
        (
            RuntimeError("the model returned nothing"),
            f"Run stopped at page 3 of 4 {EM} page 3 failed.",
            "RuntimeError: the model returned nothing\n"
            f"Pages 1{EN}2 are translated and can be reviewed and rendered.",
        ),
    ],
    ids=["budget", "error"],
)
def test_an_aborted_run_keeps_its_pages_and_review_opens_the_workspace(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
    error: Exception,
    headline: str,
    body: str,
) -> None:
    folder = _pages_folder(tmp_path, "ch", 4, page_png)
    calls = Calls()
    stages = [FakeStage("detect", calls), FakeStage("translate", calls, _on_page(2, _raise(error)))]
    window = _window(qtbot, world, folder, RunSetup(_models(tmp_path), Builder(stages)))

    _press_start(window)
    _wait_run_ended(qtbot, window)

    assert window.opened is None, "an aborted run opened something by itself"
    panel = _panel(window)
    banner = panel.banner
    assert isinstance(banner, ErrorBanner), "no banner after the abort"
    assert (banner.headline.text(), banner.body.text()) == (headline, body)
    assert _statuses(_project_dir(folder)) == [PAGE_DONE, PAGE_DONE, "pending", "pending"]
    assert [b.text() for b in banner.actions] == [f"Review pages 1{EN}2"]

    banner.actions[0].click()
    workspace = _wait_workspace(qtbot, window)

    assert workspace.page_strip.currentRow() == 0
    assert workspace.page_strip.count() == 4
    assert not window.isVisible(), "the intake window is still open after Review"


# =============================================================================
# AC-6: closing the window during a run cancels it and waits for the worker
# =============================================================================


def _hook_cancel(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Set once `RunController.cancel` has been called (C-4: closeEvent cancels)."""
    called = threading.Event()
    real = RunController.cancel

    def cancel(self: RunController) -> None:
        real(self)
        called.set()

    monkeypatch.setattr(RunController, "cancel", cancel)
    return called


def test_closing_the_window_mid_run_cancels_waits_and_keeps_the_pages_done(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    """Page 0 completes; page 1's first stage blocks until `cancel()` has been
    called and then keeps working for `AFTER_CANCEL_S`, so a close that does not
    wait returns before the worker does. DV-2: without the cancel the gate gives
    up after `GATE_S`, the run finishes and the outcome is `finished`."""
    folder = _pages_folder(tmp_path, "ch", 3, page_png)
    project_dir = _project_dir(folder)
    cancelled = _hook_cancel(monkeypatch)
    opened, exited = _capture_worker_projects(monkeypatch)
    gate = Gate(release=cancelled, linger_s=AFTER_CANCEL_S)
    world.gates.append(gate)
    calls = Calls()
    stages = [FakeStage("detect", calls, _on_page(1, gate)), FakeStage("translate", calls)]
    window = _window(qtbot, world, folder, RunSetup(_models(tmp_path), Builder(stages)))
    _press_start(window)
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    run = window.run
    assert isinstance(run, RunController)

    window.close()

    assert cancelled.is_set(), "closing the window did not call run.cancel()"
    assert not run.is_running(), "close() returned before the worker did"
    assert len(opened) == 1 and any(opened[0][0] is p for p in exited), (
        "close() returned before the worker closed its project"
    )
    assert _run_rows(project_dir) == [(RUN_ABORTED, "cancelled")]
    assert _statuses(project_dir) == [PAGE_DONE, "pending", "pending"]
    assert calls.made == [("detect", 0), ("translate", 0), ("detect", 1)]

    _settle()
    assert window.opened is None, "a cancelled run opened the Workspace after the close"
    with open_project(project_dir) as project:
        resumed: list[RunEvent] = []
        run_chapter(project, [PassThroughStage()], resumed.append, lambda: False)
    assert PageSkipped(ordinal=0, reason="already done") in resumed, "page 0 was not kept"


def test_a_run_that_finishes_after_the_close_opens_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    """C-4: the close lands during the LAST stage of the LAST page, so the runner
    marks it done and reports `finished` - a late `ended` the window must ignore."""
    folder = _pages_folder(tmp_path, "ch", 2, page_png)
    cancelled = _hook_cancel(monkeypatch)
    gate = Gate(release=cancelled)
    world.gates.append(gate)
    calls = Calls()
    window = _window(
        qtbot,
        world,
        folder,
        RunSetup(_models(tmp_path), Builder([FakeStage("translate", calls, _on_page(1, gate))])),
    )
    _press_start(window)
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)

    window.close()
    _settle()
    QTest.qWait(50)
    _settle()

    assert _run_rows(_project_dir(folder)) == [(RUN_FINISHED, None)], "precondition: finished"
    assert window.opened is None, "a run finishing after the close opened the Workspace"
    shown = [
        w for w in QApplication.topLevelWidgets() if isinstance(w, Workspace) and w.isVisible()
    ]
    assert shown == [], "a Workspace is showing after the window closed"


def test_closing_the_window_with_no_run_closes_it_at_once(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    window = _window(
        qtbot,
        world,
        _pages_folder(tmp_path, "ch", 1, page_png),
        RunSetup(_models(tmp_path), Builder()),
    )

    window.close()

    assert not window.isVisible()
    assert window.run is None


# =============================================================================
# AC-7: no models folder -> the sentence, and nothing is created
# =============================================================================


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "models"
    folder.mkdir()
    return folder


def _set_models(monkeypatch: pytest.MonkeyPatch, case: str, tmp_path: Path) -> None:
    if case == "unset":
        monkeypatch.delenv(MODELS, raising=False)
    elif case == "empty":
        monkeypatch.setenv(MODELS, "")
    elif case == "a file":
        weights = tmp_path / "weights.onnx"
        weights.write_bytes(b"not a folder")
        monkeypatch.setenv(MODELS, str(weights))
    else:
        monkeypatch.setenv(MODELS, str(tmp_path / "no such folder"))


@pytest.mark.parametrize("case", ["unset", "empty", "a file", "missing"])
def test_without_a_models_folder_start_shows_the_sentence_and_creates_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
    case: str,
) -> None:
    folder = _pages_folder(tmp_path, "ch", 2, page_png)
    _set_models(monkeypatch, case, tmp_path)
    builder = Builder()
    window = _window(qtbot, world, folder, RunSetup(app_module.resolve_models, builder))
    before = _hashes(tmp_path)

    _press_start(window)

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget), (
        f"central widget is {type(target).__name__}, not the drop target's error state"
    )
    assert target.state == "error"
    assert target.headline.text() == NO_MODELS_TEXT
    assert not _project_dir(folder).exists(), f"{case}: ch.mtproj was created"
    assert _hashes(tmp_path) == before, f"{case}: something was written"
    assert builder.calls == [], f"{case}: the builder was called with {builder.calls}"
    assert window.run is None and window.run_panel is None


def test_control_with_an_existing_models_folder_the_builder_gets_exactly_that_path(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
    models_dir: Path,
) -> None:
    monkeypatch.setenv(MODELS, str(models_dir))
    calls = Calls()
    builder = Builder(_quick_stages(calls))
    window = _window(
        qtbot,
        world,
        _pages_folder(tmp_path, "ch", 2, page_png),
        RunSetup(app_module.resolve_models, builder),
    )

    _press_start(window)
    _wait_workspace(qtbot, window)

    assert builder.calls == [models_dir]
    assert calls.made == [("detect", 0), ("translate", 0), ("detect", 1), ("translate", 1)]


def test_a_window_given_no_run_setup_has_no_models_folder(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
    models_dir: Path,
) -> None:
    """C-3: `run_setup=None` is a resolver that returns None, whatever the
    environment says."""
    monkeypatch.setenv(MODELS, str(models_dir))
    folder = _pages_folder(tmp_path, "ch", 1, page_png)
    window = _window(qtbot, world, folder, None)

    _press_start(window)

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget)
    assert target.headline.text() == NO_MODELS_TEXT
    assert not _project_dir(folder).exists()


# =============================================================================
# AC-8: no API key -> the run starts all the same and fails at the call
# =============================================================================

#: What the client says with no key; the fake raises it as the client would.
NO_KEY_MESSAGE = "Could not resolve authentication method. Expected the api_key to be set."


class RecordingEnviron(Mapping[str, str]):
    """`os.environ`, recording every key looked up by name. Iteration is
    passed through and counted, not judged: a whole-environment copy is not a
    read of the key by this code, and nothing here claims otherwise."""

    def __init__(self, inner: Mapping[str, str]) -> None:
        self._inner = inner
        self.keys_read: list[str] = []
        self.iterated = 0

    def __getitem__(self, key: str) -> str:
        self.keys_read.append(key)
        return self._inner[key]

    def __contains__(self, key: object) -> bool:
        self.keys_read.append(str(key))
        return key in self._inner

    def __iter__(self) -> Iterator[str]:
        self.iterated += 1
        return iter(self._inner)

    def __len__(self) -> int:
        return len(self._inner)


def _keyed_run(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    root: Path,
    page_png: bytes,
    mask_png: bytes,
    key: str | None,
) -> tuple[MainWindow, Calls, Builder, RecordingEnviron, Path]:
    """A 3-page run whose page 0 needs no call (no text) and whose translate
    stage, like the client, fails for want of a key at its first request."""
    root.mkdir()
    folder = _pages_folder(root, "ch", 3, page_png)
    models = root / "models"
    models.mkdir()
    monkeypatch.setenv(MODELS, str(models))
    if key is None:
        monkeypatch.delenv(KEY, raising=False)
    else:
        monkeypatch.setenv(KEY, key)

    def detect(ctx: PageContext) -> None:
        ring = ((10, 10), (30, 10), (30, 30), (10, 30), (10, 10))
        ctx.project.write_regions(
            ctx.page.ordinal,
            [RawRegion(polygon=ring, mask=mask_png, confidence=0.9, kind="bubble")],
        )

    def translate(ctx: PageContext) -> None:
        if ctx.page.ordinal == 0:
            return  # a cover with no text makes no call
        if not _REAL_ENVIRON.get(KEY):
            raise TypeError(NO_KEY_MESSAGE)

    calls = Calls()
    builder = Builder(
        [
            FakeStage("detect", calls, detect),
            FakeStage("ocr", calls),
            FakeStage("translate", calls, translate),
        ]
    )
    window = _window(qtbot, world, folder, RunSetup(app_module.resolve_models, builder))
    environ = RecordingEnviron(_REAL_ENVIRON)
    monkeypatch.setattr(os, "environ", environ)
    _press_start(window)
    _wait_run_ended(qtbot, window)
    monkeypatch.setattr(os, "environ", _REAL_ENVIRON)
    return window, calls, builder, environ, folder


def test_a_keyless_run_starts_as_a_keyed_one_and_aborts_at_the_first_call(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
    mask_png: bytes,
) -> None:
    keyless, keyless_calls, keyless_builder, keyless_env, folder = _keyed_run(
        qtbot, monkeypatch, world, tmp_path / "keyless", page_png, mask_png, None
    )
    keyed, keyed_calls, keyed_builder, keyed_env, _ = _keyed_run(
        qtbot, monkeypatch, world, tmp_path / "keyed", page_png, mask_png, "sk-test-not-a-key"
    )

    # The window refused nothing up front: both runs started, built once, ran.
    assert len(keyless_builder.calls) == len(keyed_builder.calls) == 1
    assert len(keyed_calls.made) == 9, "precondition: the keyed run went to the end"
    failing = ("translate", 1)
    assert keyless_calls.made[-1] == failing, f"keyless calls: {keyless_calls.made}"
    assert keyless_calls.made == keyed_calls.made[: len(keyless_calls.made)]

    # The recorder saw this code read the environment, and never the key.
    assert MODELS in keyless_env.keys_read and MODELS in keyed_env.keys_read, (
        "control: the recording environ saw no MANGATL_MODELS read, so it was not in the path"
    )
    assert KEY not in keyless_env.keys_read + keyed_env.keys_read, "window code read the API key"

    # The failed state, with the reason verbatim; what completed is kept.
    banner = _panel(keyless).banner
    assert isinstance(banner, ErrorBanner)
    assert banner.headline.text() == f"Run stopped at page 2 of 3 {EM} page 2 failed."
    assert banner.body.text() == (
        f"TypeError: {NO_KEY_MESSAGE}\n"
        f"Pages 1{EN}1 are translated and can be reviewed and rendered."
    )
    project_dir = _project_dir(folder)
    assert _statuses(project_dir) == [PAGE_DONE, "pending", "pending"]
    with open_project(project_dir) as project:
        assert len(project.read_regions(1)) == 1, "page 2's completed detect stage was not kept"
    assert _run_rows(project_dir) == [(RUN_ABORTED, f"TypeError: {NO_KEY_MESSAGE}")]
    assert keyless.opened is None
    assert isinstance(_wait_workspace(qtbot, keyed), Workspace)


# =============================================================================
# C-6: mangatl.app is the composition root
# =============================================================================


@pytest.mark.parametrize("case", ["unset", "empty", "a file", "missing"])
def test_resolve_models_is_none_without_a_models_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:
    _set_models(monkeypatch, case, tmp_path)

    assert app_module.resolve_models() is None


def test_resolve_models_reads_the_environment_at_call_time(
    monkeypatch: pytest.MonkeyPatch, models_dir: Path
) -> None:
    monkeypatch.delenv(MODELS, raising=False)
    assert app_module.resolve_models() is None

    monkeypatch.setenv(MODELS, str(models_dir))

    assert app_module.resolve_models() == models_dir


# MT-024 AC-9: `app.resolve_models()` passes the bundled directory
# (`resolve_models_dir(None, os.environ, bundled_models_dir())`, C-5). The two
# tests above stay true on a developer machine that has fetched the weights
# because `tests/ui/conftest.py` points `bundled_models_dir` at a missing
# directory for every UI test; these point it somewhere of their own.


def _bundle_at(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    """`bundled_models_dir()` answers `directory`, at the name `mangatl.app`
    binds and at `mangatl.app_paths` (C-3, C-5); `raising=False` until GREEN."""
    monkeypatch.setattr("mangatl.app.bundled_models_dir", lambda: directory, raising=False)
    monkeypatch.setattr("mangatl.app_paths.bundled_models_dir", lambda: directory, raising=False)


def test_resolve_models_finds_the_bundled_weights_when_nothing_else_names_a_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundled = tmp_path / "bundled-models"
    bundled.mkdir()
    _bundle_at(monkeypatch, bundled)
    monkeypatch.delenv(MODELS, raising=False)

    assert app_module.resolve_models() == bundled


def test_resolve_models_prefers_the_variable_to_the_bundled_weights(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, models_dir: Path
) -> None:
    bundled = tmp_path / "bundled-models"
    bundled.mkdir()
    _bundle_at(monkeypatch, bundled)
    monkeypatch.setenv(MODELS, str(models_dir))

    assert app_module.resolve_models() == models_dir


def test_resolve_models_is_none_when_the_bundled_folder_is_missing_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _bundle_at(monkeypatch, tmp_path / "packaging" / "models")
    monkeypatch.delenv(MODELS, raising=False)

    assert app_module.resolve_models() is None


def test_build_stages_is_build_pipeline_with_translation_on(
    monkeypatch: pytest.MonkeyPatch, models_dir: Path
) -> None:
    """`translate=` has no default in the fake: the call must say it (MT-044 C-14)."""
    seen: list[tuple[Path, bool]] = []
    stage = PassThroughStage()

    def fake_build_pipeline(models_dir: Path, *, translate: bool) -> tuple[Stage, ...]:
        seen.append((models_dir, translate))
        return (stage,)

    monkeypatch.setattr(compose_module, "build_pipeline", fake_build_pipeline)

    stages = app_module.build_stages(models_dir)

    assert seen == [(models_dir, True)]
    assert tuple(stages) == (stage,)


def _top_level_imports(source: str) -> list[str]:
    modules: list[str] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_control_a_top_level_compose_import_is_seen() -> None:
    planted = "import os\nfrom mangatl.compose import build_pipeline\n\ndef f():\n    import x\n"

    assert _top_level_imports(planted) == ["os", "mangatl.compose"]


def test_the_app_module_imports_compose_only_inside_a_function() -> None:
    """A launch that only reviews must not load onnxruntime (Direction, PO-3)."""
    source = Path(app_module.__file__).read_text(encoding="utf-8")

    assert not [m for m in _top_level_imports(source) if m.startswith("mangatl.compose")]


def _press_start_on_summary_of(qtbot, world: World, window: QMainWindow, folder: Path) -> None:  # type: ignore[no-untyped-def]
    _show(qtbot, world, window)
    assert isinstance(window, MainWindow)
    if not isinstance(window.centralWidget(), ChapterSummary):
        chapter = app_module.open_folder(folder)
        assert isinstance(chapter, Chapter)
        window.show_summary(chapter)
        _settle()
    _press_start(window)


@pytest.mark.parametrize("arguments", ["folder", "none"])
def test_every_window_build_window_makes_gets_the_real_setup(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
    models_dir: Path,
    arguments: str,
) -> None:
    """`mangatl <folder>` and bare `mangatl` both start through
    `app.resolve_models` and `app.build_stages`."""
    folder = _pages_folder(tmp_path, "ch", 1, page_png)
    monkeypatch.setenv(MODELS, str(models_dir))
    calls = Calls()
    builder = Builder(_quick_stages(calls))
    monkeypatch.setattr(app_module, "build_stages", builder)

    window = app_module.build_window([str(folder)] if arguments == "folder" else [])
    _press_start_on_summary_of(qtbot, world, window, folder)

    assert builder.calls == [models_dir]
    assert isinstance(window, MainWindow)
    _wait_workspace(qtbot, window)


def test_build_window_without_a_models_folder_refuses_with_the_sentence(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    folder = _pages_folder(tmp_path, "ch", 1, page_png)
    monkeypatch.delenv(MODELS, raising=False)

    window = app_module.build_window([str(folder)])
    _press_start_on_summary_of(qtbot, world, window, folder)

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget)
    assert target.headline.text() == NO_MODELS_TEXT
    assert not _project_dir(folder).exists()


def test_build_window_uses_an_injected_run_setup(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    folder = _pages_folder(tmp_path, "ch", 1, page_png)
    calls = Calls()
    builder = Builder(_quick_stages(calls))

    window = app_module.build_window([str(folder)], run_setup=RunSetup(_models(tmp_path), builder))
    _press_start_on_summary_of(qtbot, world, window, folder)

    assert builder.calls == [tmp_path]
    assert isinstance(window, MainWindow)
    _wait_workspace(qtbot, window)


# =============================================================================
# C-3 / C-6: nothing in ui or app renders, or reads the API key
# =============================================================================

_SRC = Path(app_module.__file__).parent


def _mentions(paths: Sequence[Path], name: str) -> list[str]:
    return [p.name for p in paths if name in p.read_text(encoding="utf-8")]


def _window_code() -> list[Path]:
    return [*sorted((_SRC / "ui").glob("*.py")), _SRC / "app.py"]


def test_control_the_scan_finds_a_planted_name(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(f'import os\nos.environ.get("{KEY}")\n', encoding="utf-8")

    assert _mentions([planted], KEY) == ["planted.py"]


@pytest.mark.parametrize("name", [KEY])
def test_no_window_code_names_the_api_key_or_the_output_writer(name: str) -> None:
    paths = _window_code()
    assert any(p.name == "run.py" for p in paths), "precondition: mangatl/ui/run.py is scanned"

    assert _mentions(paths, name) == []


@pytest.mark.parametrize("name", ["bake_chapter", "preview_bake"])
def test_only_the_render_controller_names_the_bake(name: str) -> None:
    """MT-066 C-5 (PO-3), replacing MT-059's retired `write_output_folder` case:
    Start run still renders nothing, and `mangatl/ui/bake.py` is the only window
    code that names the bake - in `ui/*.py` and `app.py`."""
    paths = _window_code()
    assert any(p.name == "run.py" for p in paths), "precondition: mangatl/ui/run.py is scanned"

    assert _mentions(paths, name) == ["bake.py"]


def test_a_fake_stage_list_satisfies_the_stage_protocol() -> None:
    """The fakes here are `Stage`s, so the window cannot depend on anything else."""
    calls = Calls()
    stages: Sequence[Stage] = (FakeStage("detect", calls), PassThroughStage())

    assert [s.name for s in stages] == ["detect", "passthrough"]
