"""MT-128: Run again and Render pages each refuse to start while the other is in flight.

Four guards in `mangatl.ui.workspace` that are correct today and that no test
pinned before this file (EPIC-11 mutation audit, survivors W01, W03, W02, W26):

- `_rerun`'s ``or self.render_button.property("loading")`` (W01, AC-1);
- `_render_pages`'s ``or self.run is not None`` (W03, AC-2);
- `_rerun`'s ``or self.run is not None`` (W02, AC-3);
- `_rerun`'s ``or self._project is None`` (W26, AC-4).

Oracle partition: all four are mechanical. The oracle is the production guard
itself, and the negative control is the mutation each AC names, run through
`scripts/mutate.sh` against this file only (story `## Handoff: RED -> GREEN`
pastes each red). AC-1 and AC-2 also carry an in-file control: the same window
with the other action finished, where the action DOES start - so a test that
asserts "nothing happened" is not satisfied by a setup in which nothing could.

**The render step in flight (AC-1)** is a real bake on a real `BakeController`,
with `preview_bake` / `bake_chapter` replaced at their seam in `mangatl.ui.bake`
by fakes; the bake fake blocks on an event until released. The loading state is
therefore the one `_on_bake_dialog_finished` leaves while a bake runs, and the
control clears it the same way - by letting that bake finish. This also observes
the audit's reachability claim rather than trusting it: Run again is asserted
ENABLED while the bake is held.

**The run in progress (AC-2, AC-3)** is started through Run again's own dialog,
over a fake stage held on a gate at page 3, as `test_rerun_workspace.py` does.

**Exceptions in slots (AC-4).** W26's mutant would raise inside
`rerun_preview(None, ...)`, in a slot Qt calls. `qtbot.capture_exceptions()`
collects what pytest-qt's excepthook sees there, and the test asserts that
list is empty - a real assertion, not a logged-and-ignored traceback.

**Threads and time.** Every wait is a bounded `qtbot.waitUntil`; a blocked fake
gives up after `GATE_S`. The `world` fixture releases every gate and every bake
fake, waits (bounded) for each to return, cancels and waits for every run, closes
any dialog left open, then closes every window - no worker outlives its test.
The bounds are liveness bounds (a fake step returns in microseconds once
released), copied from `test_rerun_workspace.py` / `test_bake_render.py`, not
cost estimates. No timing here comes from CI.

Fixtures are copied from those two files, not imported: `tests` is not a package.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget
from shiboken6 import isValid

import mangatl.ui.bake as bake_ui
import mangatl.ui.workspace as workspace_module
from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.bake import BakePreview, BakeReport, LineRef
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.store.intake import read_chapter
from mangatl.store.project import PAGE_DONE, Project, create_project, open_project, project_dir_for
from mangatl.ui.bake import BakeController
from mangatl.ui.bake_dialog import BakeConfirmDialog
from mangatl.ui.run import RunController, RunSetup
from mangatl.ui.workspace import Workspace

MODEL = "claude-sonnet-5"
#: What a Run again press that got all the way to its dialog logged, in order.
FULL_PRESS = ["resolve", "build", "select"]

# --- Liveness bounds (module docstring) ------------------------------------------
RUN_MS = 20_000
WAIT_MS = 10_000
GATE_S = 10.0

PAGES = 4
#: Pages 1-2 (ordinals 0, 1) are done before any run here.
DONE = (0, 1)
#: The page whose detect the gated run blocks on.
HELD_PAGE = 2


# =============================================================================
# Folders, projects and pages (test_rerun_workspace.py's)
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


def _mask() -> bytes:
    return _png(QSize(4, 4), QColor(255, 255, 255))


def _region(i: int) -> RawRegion:
    x, y = 4, 4 + 30 * i
    ring = ((x, y), (x + 40, y), (x + 40, y + 20), (x, y + 20), (x, y))
    return RawRegion(polygon=ring, mask=_mask(), confidence=0.9, kind="bubble")


def _mark_done(project: Project, ordinal: int) -> None:
    with project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ? WHERE ordinal = ?", (PAGE_DONE, ordinal))


@pytest.fixture
def chapter(tmp_path: Path) -> Path:
    """Four pages; pages 1-2 done, page 1 carrying one line with a proposal.
    CLOSED. Returns the project directory."""
    folder = tmp_path / "ch"
    folder.mkdir()
    for ordinal in range(PAGES):
        image = _png(QSize(60, 80), QColor(40 + 50 * ordinal, 90, 120))
        (folder / f"{ordinal + 1:02d}.png").write_bytes(image)
    folder = folder.resolve()
    project_dir = project_dir_for(folder)
    with create_project(read_chapter(folder), project_dir) as project:
        project.write_regions(0, [_region(0)])
        project.write_lines(0, [OcrResult("一")])
        project.write_proposed(0, {0: "Hello."})
        for ordinal in DONE:
            _mark_done(project, ordinal)
    return project_dir


def _run_rows(project_dir: Path) -> list[tuple[Any, ...]]:
    with open_project(project_dir) as project:
        return project.select("SELECT outcome, aborted_reason FROM run ORDER BY id")


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# Fake stages, the gate and the logging setup (test_rerun_workspace.py's)
# =============================================================================


class Gate:
    """Blocks the stage that calls it until `release` is set, for at most `GATE_S`."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, ctx: PageContext) -> None:
        if ctx.page.ordinal == HELD_PAGE:
            self.entered.set()
            self.release.wait(GATE_S)


class FakeStage:
    """Does `action(ctx)`; done exactly when the store says the page is done."""

    def __init__(self, name: str, action: Callable[[PageContext], None] | None = None) -> None:
        self.name = name
        self._action = action

    def run(self, ctx: PageContext) -> None:
        if self._action is not None:
            self._action(ctx)

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


class Setup:
    """A `RunSetup` whose three callables log their calls, in order."""

    def __init__(self, stages: Sequence[Stage] = ()) -> None:
        self.log: list[str] = []
        self.stages = tuple(stages)

    def resolve_models(self) -> Path | None:
        self.log.append("resolve")
        return Path("models")

    def build_stages(self, models_dir: Path) -> Sequence[Stage]:
        self.log.append("build")
        return self.stages

    def select_model(self) -> str:
        self.log.append("select")
        return MODEL

    def run_setup(self) -> RunSetup:
        return RunSetup(self.resolve_models, self.build_stages, self.select_model)


# =============================================================================
# Bake fakes at the `mangatl.ui.bake` seam (test_bake_render.py's `Step`)
# =============================================================================


@dataclass
class Step:
    """A fake `preview_bake` / `bake_chapter`: records, maybe blocks (at most
    `GATE_S`), then returns `result`."""

    result: Any
    block: bool = False
    args: list[tuple[Any, ...]] = field(default_factory=list)
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self, *args: Any) -> Any:
        with self._lock:
            self._in_flight += 1
            self.args.append(args)
        try:
            self.entered.set()
            if self.block:
                self.release.wait(GATE_S)
            return self.result
        finally:
            with self._lock:
                self._in_flight -= 1

    @property
    def calls(self) -> int:
        return len(self.args)

    def idle(self) -> bool:
        with self._lock:
            return self._in_flight == 0


@dataclass
class Bakes:
    preview: Step
    bake: Step
    #: Every `BakeController` the workspace constructed, in order.
    built: list[BakeController] = field(default_factory=list)


# =============================================================================
# The world: every gate, fake, run and window, torn down bounded
# =============================================================================


@dataclass
class World:
    gates: list[Gate] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    windows: list[Workspace] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)


@pytest.fixture
def world(qtbot) -> Iterator[World]:  # type: ignore[no-untyped-def]
    made = World()
    yield made
    for gate in made.gates:
        gate.release.set()
    for step in made.steps:
        step.release.set()
    for step in made.steps:
        qtbot.waitUntil(step.idle, timeout=int(GATE_S * 1000) + WAIT_MS)
    for window in made.windows:
        run = getattr(window, "run", None)
        if isinstance(run, RunController):
            run.cancel()
            qtbot.waitUntil(lambda run=run: not run.is_running(), timeout=RUN_MS)
            run.wait()
    _settle()
    for window in made.windows:
        if not isValid(window):  # a failing test may have lost it already
            continue
        for name in ("bake_dialog", "rerun_dialog"):
            dialog = getattr(window, name, None)
            if isinstance(dialog, QWidget) and isValid(dialog) and dialog.isVisible():
                dialog.close()
        window.close()
    _settle()
    for project in made.projects:
        try:
            project.select("SELECT 1")
        except sqlite3.ProgrammingError:
            continue
        project.__exit__(None, None, None)


@pytest.fixture
def bakes(monkeypatch: pytest.MonkeyPatch, world: World, tmp_path: Path) -> Bakes:
    """`preview_bake` answers at once (one unreviewed line, so the dialog has a
    confirm); `bake_chapter` BLOCKS until released. `BakeController` is recorded
    where the workspace names it, and still built for real."""
    output_dir = tmp_path / "ch_en"
    preview = Step(
        BakePreview(
            output_dir=output_dir,
            page_count=PAGES,
            total_lines=1,
            unreviewed=(LineRef(page_ordinal=0, reading_index=0),),
            failed=(),
            overflowing=(),
        )
    )
    bake = Step(
        BakeReport(pages_written=PAGES, regions_empty=0, unreviewed_lines=1, pages_uncleaned=0),
        block=True,
    )
    made = Bakes(preview, bake)
    world.steps += [preview, bake]
    monkeypatch.setattr(bake_ui, "preview_bake", preview)
    monkeypatch.setattr(bake_ui, "bake_chapter", bake)
    real = workspace_module.BakeController

    def build(*args: Any, **kwargs: Any) -> BakeController:
        controller = real(*args, **kwargs)
        made.built.append(controller)
        return controller

    monkeypatch.setattr(workspace_module, "BakeController", build)
    return made


def _window(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    setup: Setup,
    project_dir: Path | None,
) -> Workspace:
    """The workspace as `mangatl.app.open_folder` builds it, shown; the chapter
    loaded only when `project_dir` is given."""
    window = Workspace(run_setup=setup.run_setup())
    # Closed by `world`, NOT registered with `qtbot.addWidget`: pytest-qt closes
    # its widgets before any fixture is torn down, and `closeEvent` waits for a
    # held bake or run - so it would wait out `GATE_S` before `world` released it.
    world.windows.append(window)
    window.resize(1100, 720)
    with qtbot.waitExposed(window):
        window.show()
    if project_dir is not None:
        project = open_project(project_dir)
        world.projects.append(project)
        window.closed.connect(lambda: project.__exit__(None, None, None))
        window.load_chapter(project)
        window.page_strip.setCurrentRow(0)
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()
    return window


def _rerun_button(window: Workspace) -> QPushButton:
    button = window.rerun_button
    assert isinstance(button, QPushButton), f"rerun_button is {button!r}"
    return button


def _rerun_dialogs_shown(window: Workspace) -> list[QDialog]:
    return [
        d
        for d in window.findChildren(QDialog)
        if type(d).__name__ == "RerunDialog" and d.isVisible()
    ]


def _bake_held(qtbot, window: Workspace, bakes: Bakes) -> None:  # type: ignore[no-untyped-def]
    """Render pages, confirm its dialog, and hold the bake on its worker."""
    window.render_button.click()
    qtbot.waitUntil(
        lambda: (
            isinstance(window.bake_dialog, BakeConfirmDialog) and window.bake_dialog.isVisible()
        ),
        timeout=WAIT_MS,
    )
    dialog = window.bake_dialog
    assert isinstance(dialog, BakeConfirmDialog)
    _settle()
    QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    _settle()
    qtbot.waitUntil(bakes.bake.entered.is_set, timeout=WAIT_MS)
    _settle()


def _run_held(qtbot, window: Workspace, gate: Gate) -> RunController:  # type: ignore[no-untyped-def]
    """Run again, confirm, and hold the run on page 3's detect."""
    _rerun_button(window).click()
    _settle()
    dialog = window.rerun_dialog
    assert isinstance(dialog, QDialog) and dialog.isVisible(), "Run again opened no dialog"
    primary = getattr(dialog, "run_button", None)
    assert isinstance(primary, QPushButton), f"the dialog's run_button is {primary!r}"
    primary.click()
    _settle()
    run = window.run
    assert isinstance(run, RunController), f"window.run is {run!r} after the confirm"
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    _settle()
    return run


def _gated_setup(world: World) -> tuple[Setup, Gate]:
    gate = Gate()
    world.gates.append(gate)
    return Setup([FakeStage("detect", gate), FakeStage("translate")]), gate


# =============================================================================
# AC-1 (W01): Run again refuses while a render step is loading
# =============================================================================


def test_run_again_during_a_bake_starts_nothing_although_the_button_is_enabled(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
    bakes: Bakes,
) -> None:
    setup, _ = _gated_setup(world)
    window = _window(qtbot, world, setup, chapter)
    _bake_held(qtbot, window, bakes)
    assert window.render_button.property("loading") is True, (
        "precondition: Render pages is not in its loading state while the bake is held"
    )
    button = _rerun_button(window)
    assert button.isEnabled(), (
        "W01's reachability claim did not hold: Run again is disabled during a bake"
    )

    button.click()
    _settle()

    assert setup.log == [], f"Run again during a bake called the run setup: {setup.log}"
    assert window.rerun_dialog is None, "Run again during a bake opened a RerunDialog"
    assert _rerun_dialogs_shown(window) == []
    assert window.run is None, "Run again during a bake started a run"
    assert _run_rows(chapter) == [], "Run again during a bake wrote a run row"


def test_control_once_the_bake_has_finished_run_again_resolves_and_opens_its_dialog(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
    bakes: Bakes,
) -> None:
    """AC-1's control: the same bake, cleared the way it was set - by finishing."""
    setup, _ = _gated_setup(world)
    window = _window(qtbot, world, setup, chapter)
    _bake_held(qtbot, window, bakes)
    assert window.render_button.property("loading") is True, "precondition: loading"

    bakes.bake.release.set()
    qtbot.waitUntil(lambda: window.render_button.property("loading") is False, timeout=WAIT_MS)
    _settle()
    _rerun_button(window).click()
    _settle()

    assert setup.log == FULL_PRESS, f"Run again after the bake called {setup.log}"
    assert type(window.rerun_dialog).__name__ == "RerunDialog"
    assert len(_rerun_dialogs_shown(window)) == 1, "Run again after the bake opened no dialog"


# =============================================================================
# AC-2 (W03): render() refuses while a run is on
# =============================================================================


def test_render_called_during_a_run_starts_no_render(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
    bakes: Bakes,
) -> None:
    setup, gate = _gated_setup(world)
    window = _window(qtbot, world, setup, chapter)
    _run_held(qtbot, window, gate)
    assert not window.render_button.isEnabled(), "precondition: the run disabled Render pages"

    window.render()
    _settle()

    assert bakes.built == [], "render() during a run built a BakeController"
    assert window.render_button.property("loading") is not True, (
        "render() during a run put Render pages in its loading state"
    )
    QTest.qWait(50)
    _settle()
    assert bakes.preview.calls == 0, "render() during a run requested a bake preview"
    assert window.bake_dialog is None, "render() during a run opened a BakeConfirmDialog"


def test_control_once_the_run_has_returned_render_starts_a_preview(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
    bakes: Bakes,
) -> None:
    """AC-2's control: the same run, released and returned; render() then starts."""
    setup, gate = _gated_setup(world)
    window = _window(qtbot, world, setup, chapter)
    _run_held(qtbot, window, gate)

    gate.release.set()
    qtbot.waitUntil(lambda: window.run is None, timeout=RUN_MS)
    _settle()
    window.render()

    assert len(bakes.built) == 1, f"render() after the run built {len(bakes.built)} controllers"
    qtbot.waitUntil(lambda: bakes.preview.calls == 1, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: isinstance(window.bake_dialog, BakeConfirmDialog), timeout=WAIT_MS)


# =============================================================================
# AC-3 (W02): a clicked emission reaches Run again's slot during a run, and is refused
# =============================================================================


def test_a_clicked_emission_during_a_run_starts_no_second_run(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    setup, gate = _gated_setup(world)
    window = _window(qtbot, world, setup, chapter)
    first = _run_held(qtbot, window, gate)
    first_dialog = window.rerun_dialog
    button = _rerun_button(window)
    assert not button.isEnabled(), (
        "precondition: Run again is disabled during a run - which is why the signal is emitted"
    )
    assert setup.log == FULL_PRESS, f"precondition: the first run's press logged {setup.log}"

    button.clicked.emit()
    _settle()

    assert setup.log == FULL_PRESS, f"a clicked emission during a run called {setup.log[3:]}"
    assert window.rerun_dialog is first_dialog, "a clicked emission during a run built a dialog"
    assert _rerun_dialogs_shown(window) == [], "a second Run again dialog is open"
    assert window.run is first, "window.run is no longer the first RunController"


# =============================================================================
# AC-4 (W26): Run again before a chapter is loaded does nothing, and raises nothing
# =============================================================================


def test_run_again_before_a_chapter_is_loaded_does_nothing_and_raises_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
) -> None:
    setup = Setup()
    window = _window(qtbot, world, setup, None)
    button = _rerun_button(window)
    assert button.isEnabled(), "precondition: Run again is activatable before load_chapter"

    with qtbot.capture_exceptions() as raised:
        button.click()
        _settle()

    assert [repr(e[1]) for e in raised] == [], "Run again before load_chapter raised"
    assert setup.log == [], f"Run again before load_chapter called {setup.log}"
    assert window.rerun_dialog is None, "Run again before load_chapter opened a dialog"
    assert _rerun_dialogs_shown(window) == []
    assert window.run is None
