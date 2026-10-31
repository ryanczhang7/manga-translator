"""MT-125: the workspace runs the chapter again, resuming where it stopped.

`Workspace(run_setup=...)` (C-1) carries a "Run again" header button that
states the run in a `RerunDialog` (C-2, `test_rerun_dialog.py` pins its copy)
and, on confirm, swaps the body for MT-059's `RunProgressPanel` driven by a
`RunController` over the project's folder, then swaps it back and reloads the
chapter from the SAME open project.

Oracle partition (story `## Contract` C-4):

- **Settled, read out and spelled here:** "Run again", its two tooltips, the
  dialog lines the workspace's own preview produces, the two return sentences
  ("Run finished. {d} of {m} pages done." / "Run stopped. ..."), `NO_MODELS`
  character for character, and the panel's banner copy exactly as
  `test_run_failed_state.py` / `test_start_run.py` pin it.
- **Mechanical, each with its control:** the call order `resolve_models ->
  build_stages -> select_model`, each once (the `ProviderError` cases stop it
  part-way: their logs are the controls); the pending save on disk at the
  moment `resolve_models` is called; a fake stage records its thread, which
  must not be the main thread; a 110-event stream reaches the panel exactly in
  order, every receipt on the main thread; the body swap (splitter hidden,
  panel between header and footer, both buttons disabled - DV-2 is the
  control); the return (same `Project` handed to `load_chapter`, no
  `open_project` on the main thread - the recorder's own control is the
  worker's call - `closed` not emitted, the page shown before restored); the
  resume (`PageStarted` ordinals of the second run are `[2, 3]`; a fresh
  project would give `[0, 1, 2, 3]` - DV-1); close mid-run (a fake stage that
  keeps working `AFTER_CANCEL_S` after the cancel, so a close that does not
  wait emits `closed` while the worker is still alive).
- **AC-9** uses the REAL `mangatl.pipeline.stages.build_stages` over recording
  engines, as `tests/core/test_resume.py` AC-6 does, with page 2's cleaned
  image invalidated by `Project.set_excluded` restoring a region the cleaner
  never erased (MT-119 C-4). Control: the same project without the restore.

No test loads weights, builds a client or touches the network.

**Threads and time.** Every wait is a bounded `qtbot.waitUntil`; a blocked fake
stage gives up after `GATE_S`. The `world` fixture releases every gate, cancels
and waits for every run, then closes every window (which closes its project on
`closed`) - no worker outlives its test. The bounds are `test_start_run.py`'s
liveness bounds (a 4-page fake run takes milliseconds), not cost estimates.
pytest has no hook timeouts here (no `pytest-timeout`), so the fixture's waits
are bounded by `RUN_MS` too.

**RED:** `Workspace` takes no `run_setup` and has no `rerun_button`, so every
test fails on that `TypeError` / `AttributeError`. `mangatl.ui.rerun_dialog` is
deliberately NOT imported here, so this file loads in RED; the dialog is read
through `Workspace.rerun_dialog` and its labels' object names.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QWidget

import mangatl.app as app_module
import mangatl.store.project as project_module
import mangatl.ui.run as run_module
import mangatl.ui.workspace as workspace_module
from mangatl.domain.budget import DEFAULT_CEILING, Decision, Projection
from mangatl.domain.events import (
    CallPriced,
    PageSkipped,
    PageStarted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.rates import CostRecord
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import TranslationResult
from mangatl.pipeline.runner import RUN_ABORTED, RUN_FINISHED
from mangatl.pipeline.stage import BudgetRefused, PageContext, Stage
from mangatl.pipeline.stages import build_stages
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import record_call
from mangatl.store.project import PAGE_DONE, Project, create_project, open_project, project_dir_for
from mangatl.translate.provider import ProviderError
from mangatl.ui.canvas import LOADED
from mangatl.ui.progress import ErrorBanner, RunProgressPanel
from mangatl.ui.run import RunController, RunSetup
from mangatl.ui.workspace import Workspace

# --- Settled copy, spelled out (never read back from the module under test) -----
RUN_AGAIN = "Run again"
TOOLTIP_AT_REST = "Run what is not done yet. Pages already done are kept."
TOOLTIP_DISABLED = "A run is on."
NO_MODELS_TEXT = (
    "No models folder: set MANGATL_MODELS to the folder holding the model"
    " weights, then start the app again."
)
NOTHING_TO_RUN = "Every page is done. Nothing to run."
EM = "\N{EM DASH}"
EN = "\N{EN DASH}"
#: `CostReadout`'s figure with nothing priced (`cost_readout.DASH`).
NO_FIGURE = "$\N{EM DASH}"
#: What `PageSkipped.reason` says (`runner.ALREADY_DONE`).
ALREADY_DONE = "already done"

LINE_NAMES = ("rerunPages", "rerunStages", "rerunEstimate", "rerunBudget")

#: The model `select_model` answers: $0.03 a page, so two pages are $0.06 - and a
#: workspace that ignored `select_model` and priced at `Budget()`'s bootstrap
#: ($0.06 a page, claude-opus-5) would say $0.12.
MODEL = "claude-sonnet-5"

# --- Liveness bounds (test_start_run.py's) ---------------------------------------
RUN_MS = 20_000
GATE_S = 10.0
FOCUS_MS = 2_000
#: AC-6: how long the blocked stage keeps working after the cancel.
AFTER_CANCEL_S = 0.2
#: CallPriced events per translated page in the order test: 2 x 50 + 10 = 110.
BURST = 50

PAGES = 4
#: Pages 1-2 (ordinals 0, 1) are done before any run here.
DONE = (0, 1)
NEW_TEXT = "Hi there"


# =============================================================================
# Folders, projects and pages
# =============================================================================


def _png(size: QSize, colour: QColor) -> bytes:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(colour)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


PAGE_SIZE = QSize(60, 80)


def _page_png(ordinal: int) -> bytes:
    """A different colour per page, so an engine handed a page's bytes says which."""
    return _png(PAGE_SIZE, QColor(40 + 50 * ordinal, 90, 120))


def _mask() -> bytes:
    return _png(QSize(4, 4), QColor(255, 255, 255))


def _ring(i: int) -> tuple[tuple[int, int], ...]:
    x, y = 4, 4 + 30 * i
    return ((x, y), (x + 40, y), (x + 40, y + 20), (x, y + 20), (x, y))


def _region(i: int) -> RawRegion:
    return RawRegion(polygon=_ring(i), mask=_mask(), confidence=0.9, kind="bubble")


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / "ch"
    folder.mkdir()
    for ordinal in range(PAGES):
        (folder / f"{ordinal + 1:02d}.png").write_bytes(_page_png(ordinal))
    return folder.resolve()


def _mark_done(project: Project, ordinal: int) -> None:
    with project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ? WHERE ordinal = ?", (PAGE_DONE, ordinal))


def _set_ceiling(project_dir: Path, micro: int) -> None:
    """`test_workspace_cost.py`'s convention: raw SQL, the store has no writer."""
    with open_project(project_dir) as project, project.transaction() as cursor:
        cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))


@pytest.fixture
def chapter(tmp_path: Path) -> Path:
    """Four pages; pages 1-2 done, page 1 carrying one line with a proposal (so
    there is a row to edit). CLOSED. Returns the project directory."""
    folder = _folder(tmp_path)
    project_dir = project_dir_for(folder)
    with create_project(read_chapter(folder), project_dir) as project:
        project.write_regions(0, [_region(0)])
        project.write_lines(0, [OcrResult("一")])
        project.write_proposed(0, {0: "Hello."})
        for ordinal in DONE:
            _mark_done(project, ordinal)
    return project_dir


def _statuses(project_dir: Path) -> list[str]:
    with open_project(project_dir) as project:
        return [project.page_status(page.ordinal) for page in project.pages()]


def _run_rows(project_dir: Path) -> list[tuple[Any, ...]]:
    with open_project(project_dir) as project:
        return project.select("SELECT outcome, aborted_reason FROM run ORDER BY id")


def _cost_rows(project_dir: Path) -> int:
    with open_project(project_dir) as project:
        return int(project.select("SELECT count(*) FROM llm_call")[0][0])


def _on_disk(project_dir: Path, ordinal: int) -> list[tuple[Any, Any]]:
    """`(final_en, status)` per line of a page, read by a plain sqlite3 connection."""
    connection = sqlite3.connect(project_dir / "project.db")
    try:
        return list(
            connection.execute(
                "SELECT line.final_en, line.status"
                " FROM line JOIN region ON region.id = line.region_id"
                " JOIN page ON page.id = region.page_id"
                " WHERE page.ordinal = ? ORDER BY region.reading_index",
                (ordinal,),
            )
        )
    finally:
        connection.close()


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# Fake stages and the setup
# =============================================================================


@dataclass
class Calls:
    made: list[tuple[str, int]] = field(default_factory=list)
    threads: list[threading.Thread] = field(default_factory=list)


class FakeStage:
    """Records each call, then does `action(ctx)`. Done exactly when the store
    says the page is done - the runner's own mirror, as `PassThroughStage`."""

    def __init__(
        self, name: str, calls: Calls, action: Callable[[PageContext], None] | None = None
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
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


def _on_page(ordinal: int, action: Callable[[PageContext], None]) -> Callable[[PageContext], None]:
    def act(ctx: PageContext) -> None:
        if ctx.page.ordinal == ordinal:
            action(ctx)

    return act


def _once(error: Exception) -> Callable[[PageContext], None]:
    """Raise `error` the first time only: a second run of the same stage succeeds."""
    raised: list[bool] = []

    def act(ctx: PageContext) -> None:
        if not raised:
            raised.append(True)
            raise error

    return act


def _price(cents: int) -> Callable[[PageContext], None]:
    """Record one priced call of `cents` against the run, on the worker's project."""

    def act(ctx: PageContext) -> None:
        record = CostRecord(
            model_id=MODEL,
            input_tokens=1,
            output_tokens=1,
            cache_write_tokens=0,
            cache_read_tokens=0,
            cost=Usd(Decimal(cents) / 100),
            rate_table_version="test",
        )
        record_call(
            ctx.project,
            ctx.run_id,
            ctx.page.ordinal,
            f"req-{ctx.run_id}-{ctx.page.ordinal}",
            record,
        )

    return act


PROJ = Projection(
    next_call=Usd(Decimal("0.01")),
    remaining_chapter=Usd(Decimal("0.02")),
    basis="estimate",
    sample_count=0,
)


def _priced(ordinal: int, index: int) -> CallPriced:
    return CallPriced(
        ordinal=ordinal,
        spent=Usd(Decimal(ordinal * BURST + index + 1) / 100),
        ceiling=DEFAULT_CEILING,
        projection=PROJ,
    )


def _burst(ctx: PageContext) -> None:
    for index in range(BURST):
        ctx.emit(_priced(ctx.page.ordinal, index))


def _refusal() -> BudgetRefused:
    projection = Projection(
        next_call=Usd(Decimal("0.10")),
        remaining_chapter=Usd(Decimal("0.20")),
        basis="observed",
        sample_count=3,
    )
    return BudgetRefused(
        Decision(
            permitted=False,
            reason="the projected next call would exceed the budget",
            spent=Usd(Decimal("1.95")),
            ceiling=DEFAULT_CEILING,
            projection=projection,
        )
    )


class Gate:
    """Blocks the stage that calls it until `release` is set, for at most `GATE_S`."""

    def __init__(self, release: threading.Event | None = None, linger_s: float = 0.0) -> None:
        self.entered = threading.Event()
        self.release = release if release is not None else threading.Event()
        self._linger_s = linger_s

    def __call__(self, ctx: PageContext) -> None:
        self.entered.set()
        self.release.wait(GATE_S)
        if self._linger_s:
            time.sleep(self._linger_s)


class Setup:
    """A `RunSetup` whose three callables log their calls, in order."""

    def __init__(
        self,
        stages: Sequence[Stage] = (),
        *,
        models: Path | None = Path("models"),
        build_error: Exception | None = None,
        select_error: Exception | None = None,
        on_resolve: Callable[[], None] | None = None,
    ) -> None:
        self.log: list[str] = []
        self.stages = tuple(stages)
        self._models = models
        self._build_error = build_error
        self._select_error = select_error
        self._on_resolve = on_resolve

    def resolve_models(self) -> Path | None:
        self.log.append("resolve")
        if self._on_resolve is not None:
            self._on_resolve()
        return self._models

    def build_stages(self, models_dir: Path) -> Sequence[Stage]:
        self.log.append("build")
        if self._build_error is not None:
            raise self._build_error
        return self.stages

    def select_model(self) -> str:
        self.log.append("select")
        if self._select_error is not None:
            raise self._select_error
        return MODEL

    def run_setup(self) -> RunSetup:
        return RunSetup(self.resolve_models, self.build_stages, self.select_model)


# =============================================================================
# The world, the window and the panel's receipts
# =============================================================================


@dataclass
class World:
    gates: list[Gate] = field(default_factory=list)
    windows: list[Workspace] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)


@pytest.fixture
def world(qtbot) -> Iterator[World]:  # type: ignore[no-untyped-def]
    made = World()
    yield made
    for gate in made.gates:
        gate.release.set()
    for window in made.windows:
        run = getattr(window, "run", None)
        if isinstance(run, RunController):
            run.cancel()
            qtbot.waitUntil(lambda run=run: not run.is_running(), timeout=RUN_MS)
            run.wait()
    _settle()
    for window in made.windows:
        window.close()
    _settle()
    for project in made.projects:
        try:
            project.select("SELECT 1")
        except sqlite3.ProgrammingError:
            continue
        project.__exit__(None, None, None)


def _workspace(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    project_dir: Path,
    setup: Setup | None,
    *,
    row: int = 0,
) -> tuple[Workspace, Project]:
    """The workspace as `mangatl.app.open_folder` builds it, shown, on `row`."""
    window = Workspace() if setup is None else Workspace(run_setup=setup.run_setup())
    world.windows.append(window)
    qtbot.addWidget(window)
    project = open_project(project_dir)
    world.projects.append(project)
    window.closed.connect(lambda: project.__exit__(None, None, None))
    window.resize(1100, 720)
    with qtbot.waitExposed(window):
        window.show()
    window.load_chapter(project)
    window.page_strip.setCurrentRow(row)
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()
    return window, project


def _button(window: Workspace) -> QPushButton:
    button = window.rerun_button
    assert isinstance(button, QPushButton), f"rerun_button is {button!r}"
    return button


def _press(window: Workspace) -> QDialog | None:
    """Activate "Run again"; the dialog it opened, if any."""
    _button(window).click()
    _settle()
    dialog = window.rerun_dialog
    return dialog if isinstance(dialog, QDialog) else None


def _dialog(window: Workspace) -> QDialog:
    dialog = _press(window)
    assert dialog is not None, "activating Run again opened no dialog"
    assert type(dialog).__name__ == "RerunDialog", f"the dialog is a {type(dialog).__name__}"
    assert dialog.isVisible(), "the dialog was built and not opened"
    return dialog


def _shown_lines(dialog: QDialog) -> list[str]:
    lines: list[str] = []
    for name in LINE_NAMES:
        label = dialog.findChild(QLabel, name)
        if isinstance(label, QLabel) and not label.isHidden():
            lines.append(label.text())
    return lines


def _confirm(window: Workspace) -> RunController:
    """Open the dialog, accept it; the run it started."""
    dialog = _dialog(window)
    primary = getattr(dialog, "run_button", None)
    assert isinstance(primary, QPushButton), f"the dialog's run_button is {primary!r}"
    primary.click()
    _settle()
    run = window.run
    assert isinstance(run, RunController), f"window.run is {run!r} after the confirm"
    return run


def _wait_returned(qtbot, window: Workspace) -> None:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(lambda: window.run is None, timeout=RUN_MS)
    _settle()


def _wait_stopped(qtbot, run: RunController) -> None:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(lambda: not run.is_running(), timeout=RUN_MS)
    run.wait()
    _settle()


def _panel(window: Workspace) -> RunProgressPanel:
    panel = window.run_panel
    assert isinstance(panel, RunProgressPanel), f"run_panel is {panel!r}"
    return panel


def _record_panel(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, bool]]:
    """Every event any `RunProgressPanel` receives, with whether it was received
    on the main thread. Patched on the class, so the panel the workspace builds
    is recorded however it is connected."""
    log: list[tuple[object, bool]] = []
    real = RunProgressPanel.on_event

    def on_event(self: RunProgressPanel, event: RunEvent) -> None:
        log.append((event, threading.current_thread() is threading.main_thread()))
        real(self, event)

    monkeypatch.setattr(RunProgressPanel, "on_event", on_event)
    return log


def _runs(log: Sequence[tuple[object, bool]]) -> list[list[object]]:
    """The panel's receipts split into one list per run, at each `RunStarted`."""
    runs: list[list[object]] = []
    for event, _ in log:
        if isinstance(event, RunStarted):
            runs.append([])
        if runs:
            runs[-1].append(event)
    return runs


def _started(events: Sequence[object]) -> list[int]:
    return [e.ordinal for e in events if isinstance(e, PageStarted)]


def _normalised(events: Sequence[object]) -> list[object]:
    return [replace(e, elapsed_ms=0) if isinstance(e, StageFinished) else e for e in events]


def _strip(window: Workspace) -> list[str]:
    return [window.page_strip.progress(i).status for i in range(window.page_strip.count())]


def _hook_cancel(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    called = threading.Event()
    real = RunController.cancel

    def cancel(self: RunController) -> None:
        real(self)
        called.set()

    monkeypatch.setattr(RunController, "cancel", cancel)
    return called


def _record_open_project(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Every `open_project` call by the code under test, by whether it was made
    on the main thread. This module's own `open_project` is bound at import and
    is not recorded."""
    calls: list[bool] = []
    real = project_module.open_project

    def record(project_dir: Path) -> Project:
        calls.append(threading.current_thread() is threading.main_thread())
        return real(project_dir)

    for module in (project_module, run_module, workspace_module, app_module):
        monkeypatch.setattr(module, "open_project", record, raising=False)
    return calls


def _quick(calls: Calls) -> list[Stage]:
    return [FakeStage("detect", calls), FakeStage("translate", calls, _price(25))]


# =============================================================================
# AC-1: the button
# =============================================================================


def test_with_a_run_setup_the_header_carries_run_again(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    window, _ = _workspace(qtbot, world, chapter, Setup())

    button = _button(window)
    assert button.text() == RUN_AGAIN
    assert button.accessibleName() == RUN_AGAIN
    assert button.toolTip() == TOOLTIP_AT_REST
    assert button.isVisible() and button.isEnabled()
    assert window.header.isAncestorOf(button), "Run again is not in the header"


def test_run_again_is_activated_by_return_as_render_pages_is(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    """§1's `ActivatedByEnter`: a secondary button outside a dialog takes Return.
    Activation is observed through the setup's log (no models: no dialog)."""
    setup = Setup(models=None)
    window, _ = _workspace(qtbot, world, chapter, setup)
    button = _button(window)
    button.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(button.hasFocus, timeout=FOCUS_MS)

    QTest.keyClick(button, Qt.Key.Key_Return)
    _settle()

    assert setup.log == ["resolve"], f"Return on Run again made {setup.log}"


def test_run_again_sits_immediately_before_the_cost_readout_after_the_stretch(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    window, _ = _workspace(qtbot, world, chapter, Setup())
    row = window.header.layout()
    assert row is not None

    at_button = row.indexOf(_button(window))
    at_cost = row.indexOf(window.cost_readout)
    at_name = row.indexOf(window.chapter_name)

    assert at_button >= 0, "Run again is not in the header's own row"
    assert at_button == at_cost - 1, (
        f"Run again is item {at_button}, the cost readout {at_cost}: not immediately before it"
    )
    stretches = [k for k in range(at_name + 1, at_button) if row.itemAt(k).spacerItem() is not None]
    assert stretches, "Run again is not after the stretch that follows the chapter name"


def _tab_stops(window: QWidget) -> list[QWidget]:
    """Qt's Tab order through the window: the focus chain, as Tab walks it."""
    stops: list[QWidget] = []
    widget = window.nextInFocusChain()
    tab = Qt.FocusPolicy.TabFocus.value
    while widget is not window and len(stops) < 500:
        if (
            widget.focusPolicy().value & tab == tab
            and widget.isVisible()
            and widget.isEnabled()
            and widget.window() is window
        ):
            stops.append(widget)
        widget = widget.nextInFocusChain()
    return stops


def test_run_again_is_a_tab_stop_before_anything_in_the_body(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    window, _ = _workspace(qtbot, world, chapter, Setup())

    stops = _tab_stops(window)
    button = _button(window)
    assert button in stops, "Run again is not a Tab stop"
    body = [i for i, w in enumerate(stops) if window.splitter.isAncestorOf(w)]
    assert body, "precondition: the body has Tab stops"
    assert stops.index(button) < body[0], "Tab reaches the body before Run again"


def test_without_a_run_setup_there_is_no_run_again_at_all(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    """Absent, not disabled (MainWindow C-3's rule)."""
    window, _ = _workspace(qtbot, world, chapter, None)

    assert window.rerun_button is None
    texts = [b.text() for b in window.findChildren(QPushButton)]
    assert RUN_AGAIN not in texts, "a window with no run setup has a Run again button"


def test_control_with_a_run_setup_the_scan_finds_the_button(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    window, _ = _workspace(qtbot, world, chapter, Setup())

    assert RUN_AGAIN in [b.text() for b in window.findChildren(QPushButton)]


# =============================================================================
# AC-2: the statement before the run
# =============================================================================


def test_activating_run_again_resolves_builds_and_selects_in_that_order_once_each(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    calls = Calls()
    setup = Setup(_quick(calls))
    window, _ = _workspace(qtbot, world, chapter, setup)

    _dialog(window)

    assert setup.log == ["resolve", "build", "select"]
    assert calls.made == [], "a stage ran before the dialog was confirmed"


def test_a_pending_line_save_is_on_disk_before_the_models_are_resolved(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    """Typed, `Enter`, and Run again at once - inside the 500 ms debounce, so only
    the flush the slot does first can have written it."""
    seen: list[list[tuple[Any, Any]]] = []
    setup = Setup(_quick(Calls()), on_resolve=lambda: seen.append(_on_disk(chapter, 0)))
    window, _ = _workspace(qtbot, world, chapter, setup)
    editor = window.translation_column.row(0).editor
    editor.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(editor.hasFocus, timeout=FOCUS_MS)
    editor.selectAll()
    QTest.keyClicks(editor, NEW_TEXT)
    QTest.keyClick(editor, Qt.Key.Key_Return)

    _button(window).click()

    assert seen == [[(NEW_TEXT, "edited")]], f"at resolve_models the line on disk was {seen}"


def test_the_dialog_states_the_workspaces_own_preview(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    """Two of four pages to run through a fake `detect` and `translate`; priced
    on `select_model`'s model ($0.03 a page), nothing spent, the default $2.00."""
    window, _ = _workspace(qtbot, world, chapter, Setup(_quick(Calls())))

    dialog = _dialog(window)

    assert dialog.isModal()
    assert _shown_lines(dialog) == [
        "2 of 4 pages still to run.",
        "2 to detect, 2 to translate.",
        "Estimated cost to translate 2 pages: $0.06.",
        "Nothing spent yet of the $2.00 budget.",
    ]
    primary = getattr(dialog, "run_button", None)
    assert isinstance(primary, QPushButton)
    assert primary.text() == "Run 2 pages"


def test_over_the_projects_ceiling_the_dialog_says_the_estimate_is_over_budget(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    """$0.06 against a $0.05 ceiling: `within_budget` is false."""
    _set_ceiling(chapter, 50_000)
    window, _ = _workspace(qtbot, world, chapter, Setup(_quick(Calls())))

    dialog = _dialog(window)

    assert _shown_lines(dialog)[-1] == (
        "Nothing spent yet of the $0.05 budget. The estimate is over budget."
    )


def _cancel(dialog: QDialog) -> None:
    QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]


def _escape(dialog: QDialog) -> None:
    QTest.keyClick(dialog, Qt.Key.Key_Escape)


@pytest.mark.parametrize("dismiss", [_cancel, _escape], ids=["cancel", "escape"])
def test_cancel_and_escape_reject_the_dialog_and_write_no_run(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
    dismiss: Callable[[QDialog], None],
) -> None:
    calls = Calls()
    window, _ = _workspace(qtbot, world, chapter, Setup(_quick(calls)))
    dialog = _dialog(window)

    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS) as finished:
        dismiss(dialog)
    _settle()
    QTest.qWait(50)

    assert finished.args == [QDialog.DialogCode.Rejected.value]
    assert window.run is None
    assert calls.made == []
    assert _run_rows(chapter) == [], "a dismissed dialog wrote a run row"
    assert window.splitter.isVisible(), "a dismissed dialog swapped the body"


def test_focus_returns_to_run_again_when_the_dialog_closes(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    window, _ = _workspace(qtbot, world, chapter, Setup(_quick(Calls())))
    dialog = _dialog(window)

    _cancel(dialog)

    qtbot.waitUntil(lambda: QApplication.focusWidget() is window.rerun_button, timeout=FOCUS_MS)


def test_control_with_every_page_done_the_dialog_says_nothing_is_left_to_run(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    with open_project(chapter) as project:
        for ordinal in range(PAGES):
            _mark_done(project, ordinal)
    calls = Calls()
    window, _ = _workspace(qtbot, world, chapter, Setup(_quick(calls)))

    dialog = _dialog(window)

    assert _shown_lines(dialog)[0] == NOTHING_TO_RUN
    assert getattr(dialog, "run_button", "missing") is None, "nothing to run has a primary action"
    buttons = [b.text() for b in dialog.findChildren(QPushButton) if not b.isHidden()]
    assert buttons == ["Close"]
    _cancel(dialog)
    _settle()
    assert window.run is None and calls.made == [] and _run_rows(chapter) == []


# =============================================================================
# AC-3: the run, in the workspace body
# =============================================================================


def test_confirming_swaps_the_body_for_the_progress_panel_and_disables_both_actions(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    """Mid-run (page 3's detect blocked): splitter hidden, the panel between the
    header and the footer, both still shown; Render pages and Run again not
    activatable and saying why. DV-2's target."""
    gate = Gate()
    world.gates.append(gate)
    calls = Calls()
    stages = [FakeStage("detect", calls, _on_page(2, gate)), FakeStage("translate", calls)]
    window, _ = _workspace(qtbot, world, chapter, Setup(stages))

    _confirm(window)
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    _settle()

    panel = _panel(window)
    assert panel.isVisible(), "the run panel is not shown"
    assert window.splitter.isHidden(), "the strip, canvas and column are still in the body"
    assert window.header.isVisible() and window.footer.isVisible()
    body = window.centralWidget().layout()
    assert body is not None
    at_header, at_panel, at_footer = (
        body.indexOf(window.header),
        body.indexOf(panel),
        body.indexOf(window.footer),
    )
    assert at_header < at_panel < at_footer, (
        f"header {at_header}, panel {at_panel}, footer {at_footer}: not in the body's place"
    )
    assert panel.thumbnail is not None, "the panel was built without the chapter"
    for button in (window.render_button, _button(window)):
        assert not button.isEnabled(), f"{button.text()!r} is activatable during the run"
        assert button.toolTip() == TOOLTIP_DISABLED, f"{button.text()!r} does not say why"

    gate.release.set()
    _wait_returned(qtbot, window)


def test_the_stages_run_off_the_gui_thread_and_the_run_row_ends_finished(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    calls = Calls()
    window, _ = _workspace(qtbot, world, chapter, Setup(_quick(calls)))

    _confirm(window)
    _wait_returned(qtbot, window)

    assert calls.made == [("detect", 2), ("translate", 2), ("detect", 3), ("translate", 3)]
    on_main = [t for t in calls.threads if t is threading.main_thread()]
    assert on_main == [], f"{len(on_main)} stage calls ran on the GUI thread"
    assert _run_rows(chapter) == [(RUN_FINISHED, None)]


def test_the_panel_receives_every_event_in_order_on_the_gui_thread(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    chapter: Path,
) -> None:
    """110 events: the two done pages are `PageSkipped`, the other two
    `PageStarted` with a burst of 50 `CallPriced` each."""
    log = _record_panel(monkeypatch)
    calls = Calls()
    stages = [FakeStage("detect", calls), FakeStage("translate", calls, _burst)]
    window, _ = _workspace(qtbot, world, chapter, Setup(stages))

    _confirm(window)
    _wait_returned(qtbot, window)

    expected: list[object] = [
        RunStarted(run_id=1, page_count=PAGES),
        PageSkipped(ordinal=0, reason=ALREADY_DONE),
        PageSkipped(ordinal=1, reason=ALREADY_DONE),
    ]
    for ordinal in (2, 3):
        expected += [
            PageStarted(ordinal=ordinal),
            StageFinished(ordinal=ordinal, stage="detect", elapsed_ms=0),
            *[_priced(ordinal, index) for index in range(BURST)],
            StageFinished(ordinal=ordinal, stage="translate", elapsed_ms=0),
        ]
    expected.append(RunFinished(run_id=1, pages_done=PAGES))
    assert len(expected) == 110
    assert _normalised([event for event, _ in log]) == expected
    off_main = [event for event, on_main in log if not on_main]
    assert off_main == [], f"{len(off_main)} receipts were not on the main thread"


# =============================================================================
# AC-4: a finished run returns the body, reloaded from the same project
# =============================================================================


def test_a_finished_run_returns_the_body_reloaded_from_the_same_open_project(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    chapter: Path,
) -> None:
    opens = _record_open_project(monkeypatch)
    calls = Calls()
    window, project = _workspace(qtbot, world, chapter, Setup(_quick(calls)), row=1)
    closed: list[bool] = []
    window.closed.connect(lambda: closed.append(True))
    loads: list[Project] = []
    real_load = Workspace.load_chapter

    def load(given: Project) -> None:
        loads.append(given)
        real_load(window, given)

    monkeypatch.setattr(window, "load_chapter", load)
    assert _strip(window) == ["translated", "translated", "pending", "pending"]
    assert window.cost_readout.figure.text() == NO_FIGURE

    _confirm(window)
    _wait_returned(qtbot, window)

    assert window.splitter.isVisible(), "the body did not come back"
    assert window.run_panel is None
    shown = [p for p in window.findChildren(RunProgressPanel) if p.isVisible()]
    assert shown == [], "a progress panel is still showing after the return"
    assert loads == [project], f"load_chapter was given {loads!r}, not the open project"
    assert closed == [], "the window emitted closed during the run or the return"
    assert opens, "precondition: the recorder saw the worker's open_project"
    assert all(not on_main for on_main in opens), "open_project was called on the GUI thread"
    assert _strip(window) == ["translated"] * PAGES
    assert window.cost_readout.figure.text() == "$0.50"
    assert window.page_strip.currentRow() == 1, "the page shown before the run is not shown"
    assert window.page_canvas.state() == LOADED
    assert window.live_region.text() == "Run finished. 4 of 4 pages done."
    assert window.render_button.isEnabled() and _button(window).isEnabled()
    assert _button(window).toolTip() == TOOLTIP_AT_REST


def test_after_the_return_focus_is_on_run_again(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    window, _ = _workspace(qtbot, world, chapter, Setup(_quick(Calls())))

    _confirm(window)
    _wait_returned(qtbot, window)

    qtbot.waitUntil(lambda: QApplication.focusWidget() is window.rerun_button, timeout=FOCUS_MS)


# =============================================================================
# AC-5: an aborted run keeps its panel; Review returns; Run again resumes
# =============================================================================


@pytest.mark.parametrize(
    ("error", "ceiling_micro", "headline", "body", "reason"),
    [
        (
            _refusal(),
            5_000_000,
            f"Run stopped at page 3 of 4 {EM} the $5.00 budget was reached.",
            f"Pages 1{EN}2 are translated and can be reviewed and rendered.",
            "budget",
        ),
        (
            RuntimeError("the model returned nothing"),
            None,
            f"Run stopped at page 3 of 4 {EM} page 3 failed.",
            "RuntimeError: the model returned nothing\n"
            f"Pages 1{EN}2 are translated and can be reviewed and rendered.",
            "RuntimeError: the model returned nothing",
        ),
    ],
    ids=["budget", "error"],
)
def test_an_aborted_run_shows_its_banner_review_returns_and_run_again_resumes_at_the_failed_page(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    chapter: Path,
    error: Exception,
    ceiling_micro: int | None,
    headline: str,
    body: str,
    reason: str,
) -> None:
    """The budget case's ceiling is $5.00, so its headline names the project's
    ceiling only if the panel was built with it. DV-1's target: a workspace that
    ran over a fresh project starts the second run at page 1."""
    if ceiling_micro is not None:
        _set_ceiling(chapter, ceiling_micro)
    log = _record_panel(monkeypatch)
    calls = Calls()
    stages = [
        FakeStage("detect", calls),
        FakeStage("translate", calls, _on_page(2, _once(error))),
    ]
    window, _ = _workspace(qtbot, world, chapter, Setup(stages))

    run = _confirm(window)
    _wait_stopped(qtbot, run)

    panel = _panel(window)
    assert window.splitter.isHidden(), "an aborted run returned the body by itself"
    banner = panel.banner
    assert isinstance(banner, ErrorBanner), "no banner after the abort"
    assert (banner.headline.text(), banner.body.text()) == (headline, body)
    assert [b.text() for b in banner.actions] == [f"Review pages 1{EN}2"]
    assert _statuses(chapter) == [PAGE_DONE, PAGE_DONE, "pending", "pending"]

    banner.actions[0].click()
    _wait_returned(qtbot, window)

    assert window.splitter.isVisible(), "Review pages did not return the body"
    assert _strip(window) == ["translated", "translated", "pending", "pending"]
    assert window.live_region.text() == "Run stopped. 2 of 4 pages done."
    assert _button(window).isEnabled()

    dialog = _dialog(window)
    assert _shown_lines(dialog)[0] == "2 of 4 pages still to run."
    primary = getattr(dialog, "run_button", None)
    assert isinstance(primary, QPushButton)
    primary.click()
    _wait_returned(qtbot, window)

    first, second = _runs(log)
    assert _started(first) == [2]
    assert _started(second) == [2, 3], (
        f"the second run started pages {_started(second)}: it did not resume at page 3"
    )
    assert _run_rows(chapter) == [(RUN_ABORTED, reason), (RUN_FINISHED, None)]
    assert _statuses(chapter) == [PAGE_DONE] * PAGES
    assert window.live_region.text() == "Run finished. 4 of 4 pages done."


# =============================================================================
# AC-6: closing the window during a run cancels it and waits for the worker
# =============================================================================


def test_closing_the_window_mid_run_cancels_waits_and_emits_closed_after_the_worker(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    chapter: Path,
) -> None:
    """Page 3's detect blocks until `cancel()` and keeps working `AFTER_CANCEL_S`
    after it: a close that does not wait emits `closed` with the worker alive."""
    cancelled = _hook_cancel(monkeypatch)
    gate = Gate(release=cancelled, linger_s=AFTER_CANCEL_S)
    world.gates.append(gate)
    calls = Calls()
    stages = [FakeStage("detect", calls, _on_page(2, gate)), FakeStage("translate", calls)]
    window, _ = _workspace(qtbot, world, chapter, Setup(stages))
    run = _confirm(window)
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    alive_at_closed: list[bool] = []
    window.closed.connect(lambda: alive_at_closed.append(run.is_running()))

    window.close()

    assert cancelled.is_set(), "closing the window did not call run.cancel()"
    assert not run.is_running(), "close() returned before the worker did"
    assert alive_at_closed == [False], f"closed emitted with the worker alive: {alive_at_closed}"
    assert _run_rows(chapter) == [(RUN_ABORTED, "cancelled")]
    assert _statuses(chapter) == [PAGE_DONE, PAGE_DONE, "pending", "pending"]
    assert calls.made == [("detect", 2)]


# =============================================================================
# AC-7: no models folder, or a provider refusal, is said in the footer
# =============================================================================


@pytest.mark.parametrize(
    ("setup_kwargs", "message", "log"),
    [
        ({"models": None}, NO_MODELS_TEXT, ["resolve"]),
        (
            {"build_error": ProviderError("no API key is set: set GEMINI_API_KEY")},
            "no API key is set: set GEMINI_API_KEY",
            ["resolve", "build"],
        ),
        (
            {"select_error": ProviderError("API keys are set for more than one provider")},
            "API keys are set for more than one provider",
            ["resolve", "build", "select"],
        ),
    ],
    ids=["no-models", "build-refused", "select-refused"],
)
def test_a_refusal_is_said_in_the_footer_and_announced_and_nothing_opens_or_runs(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
    setup_kwargs: dict[str, Any],
    message: str,
    log: list[str],
) -> None:
    calls = Calls()
    setup = Setup(_quick(calls), **setup_kwargs)
    window, _ = _workspace(qtbot, world, chapter, setup)

    dialog = _press(window)

    assert setup.log == log
    assert dialog is None, "a refused Run again opened a dialog"
    assert window.render_status.text() == message
    assert window.live_region.text() == message
    assert window.run is None
    assert calls.made == []
    assert _run_rows(chapter) == []


# =============================================================================
# AC-9: the real stage list re-cleans the one invalidated page
# =============================================================================


@dataclass
class Engines:
    """Engines for the real `build_stages` that record each call. `clean`
    answers the page's own bytes (the page's size); the other three refuse."""

    detect: list[bytes] = field(default_factory=list)
    clean: list[bytes] = field(default_factory=list)
    read: list[bytes] = field(default_factory=list)
    translate: list[bytes] = field(default_factory=list)

    def on_detect(self, image_bytes: bytes) -> Sequence[RawRegion]:
        self.detect.append(image_bytes)
        raise AssertionError("the detector was called")

    def on_clean(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> bytes:
        self.clean.append(image_bytes)
        return image_bytes

    def on_read(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
        self.read.append(image_bytes)
        raise AssertionError("the transcriber was called")

    def on_translate(
        self, image_bytes: bytes, results: Sequence[OcrResult], context: Any
    ) -> TranslationResult:
        self.translate.append(image_bytes)
        raise AssertionError("the translator was called")

    def stages(self) -> tuple[Stage, ...]:
        return build_stages(
            self.on_detect, self.on_clean, self.on_read, self.on_translate, Usd(Decimal("0.03"))
        )

    def pages(self, calls: Sequence[bytes]) -> list[int]:
        by_bytes = {_page_png(ordinal): ordinal for ordinal in range(PAGES)}
        return [by_bytes.get(image, -1) for image in calls]


@pytest.fixture
def every_page_done(tmp_path: Path) -> Path:
    """Four pages, each detected, read, translated, cleaned and `done`. Page 2
    has two regions, the second excluded when the page was cleaned, so its
    cleaned image erased only region 0 (MT-119 C-4). CLOSED; the project dir."""
    folder = _folder(tmp_path)
    project_dir = project_dir_for(folder)
    with create_project(read_chapter(folder), project_dir) as project:
        for ordinal in range(PAGES):
            count = 2 if ordinal == 1 else 1
            project.write_regions(ordinal, [_region(i) for i in range(count)])
            project.write_lines(ordinal, [OcrResult(f"ja-{ordinal}-{i}") for i in range(count)])
            project.write_proposed(ordinal, {0: f"EN-{ordinal}"})
            if ordinal == 1:
                project.set_excluded(1, 1, "user")
            project.write_cleaned(ordinal, _page_png(ordinal), erased=(0,))
            _mark_done(project, ordinal)
    return project_dir


def _invalidate_page_2(project_dir: Path) -> None:
    """MT-119's restore of a region the cleaner never erased: the cleaned image goes."""
    with open_project(project_dir) as project:
        project.set_excluded(1, 1, None)
        assert not project.has_cleaned(1), "precondition: the restore invalidated page 2"
        assert project.page_status(1) == PAGE_DONE, "precondition: the store still says done"


def test_run_again_after_a_restore_recleans_that_one_page_and_nothing_else(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    every_page_done: Path,
) -> None:
    _invalidate_page_2(every_page_done)
    engines = Engines()
    window, _ = _workspace(qtbot, world, every_page_done, Setup(engines.stages()))
    costs_before = _cost_rows(every_page_done)

    dialog = _dialog(window)
    lines = _shown_lines(dialog)
    assert lines[:2] == ["1 of 4 pages still to run.", "1 to clean."]
    assert not any(line.startswith("Estimated cost") for line in lines), (
        f"nothing is to be translated, yet the dialog shows an estimate: {lines}"
    )
    primary = getattr(dialog, "run_button", None)
    assert isinstance(primary, QPushButton)
    primary.click()
    _wait_returned(qtbot, window)

    assert engines.pages(engines.clean) == [1], "the cleaner was not called for page 2 alone"
    assert (engines.detect, engines.read, engines.translate) == ([], [], [])
    assert _cost_rows(every_page_done) == costs_before, "a cost row was added"
    assert _run_rows(every_page_done) == [(RUN_FINISHED, None)]
    with open_project(every_page_done) as project:
        assert project.page_status(1) == PAGE_DONE
        assert project.has_cleaned(1), "page 2 has no cleaned image after the run"
        assert project.read_erased(1) == frozenset({0, 1})


def test_control_without_the_restore_there_is_nothing_to_run_and_no_engine_is_called(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    every_page_done: Path,
) -> None:
    engines = Engines()
    window, _ = _workspace(qtbot, world, every_page_done, Setup(engines.stages()))

    dialog = _dialog(window)

    assert _shown_lines(dialog)[0] == NOTHING_TO_RUN
    assert getattr(dialog, "run_button", "missing") is None
    _cancel(dialog)
    _settle()
    assert (engines.detect, engines.clean, engines.read, engines.translate) == ([], [], [], [])
    assert _run_rows(every_page_done) == []
