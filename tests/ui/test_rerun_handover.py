"""MT-129: the run hand-over keeps focus, says one page singular and keeps one dialog.

Three behaviours of MT-125's run hand-over in `mangatl.ui.workspace` that are
correct today and that no test pinned before this file (EPIC-11 mutation audit,
survivors W19, W15, W20):

- `_start_run`'s ``self.setFocus(Qt.FocusReason.OtherFocusReason)`` (W19, AC-1):
  focus is parked on the window before the body is hidden and both actions are
  disabled, so it is never left on a hidden or disabled control;
- `_return_sentence`'s ``"page" if len(pages) == 1 else "pages"`` (W15, AC-2):
  a one-page chapter is announced ``Run finished. 1 of 1 page done.``;
- `_rerun`'s ``self.rerun_dialog.deleteLater()`` (W20, AC-3): a second Run again
  replaces the first dialog rather than leaking it.

Oracle partition: all three are mechanical. The oracle is the production
behaviour itself, pinned exactly, and the negative control is the mutation each
AC names, run through `scripts/mutate.sh` against this file only (story
`## Handoff: RED -> GREEN` pastes each red).

**The run in progress (AC-1)** is started through Run again's own dialog, over a
fake stage held on a gate at page 3, as `test_rerun_guards.py` does.

**Threads and time.** Every wait is a bounded `qtbot.waitUntil`; a blocked fake
gives up after `GATE_S`. The `world` fixture releases every gate, cancels and
waits for every run, closes any dialog left open, then closes every window - no
worker outlives its test. The bounds are liveness bounds (a fake step returns in
microseconds once released), copied from `test_rerun_guards.py` /
`test_rerun_workspace.py`, not cost estimates. No timing here comes from CI.

Fixtures are copied from those two files, not imported: `tests` is not a package.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QEvent, QIODevice, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget
from shiboken6 import isValid

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.store.intake import read_chapter
from mangatl.store.project import PAGE_DONE, Project, create_project, open_project, project_dir_for
from mangatl.ui.run import RunController, RunSetup
from mangatl.ui.workspace import Workspace

MODEL = "claude-sonnet-5"

# --- Liveness bounds (module docstring) ------------------------------------------
RUN_MS = 20_000
WAIT_MS = 10_000
GATE_S = 10.0
FOCUS_MS = 2_000

PAGES = 4
#: Pages 1-2 (ordinals 0, 1) are done before any run here.
DONE = (0, 1)
#: The page whose detect the gated run blocks on.
HELD_PAGE = 2


# =============================================================================
# Folders, projects and pages (test_rerun_guards.py's)
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


def _project(tmp_path: Path, pages: int, done: Sequence[int]) -> Path:
    """`pages` pages; those in `done` done, page 1 carrying one line with a
    proposal. CLOSED. Returns the project directory."""
    folder = tmp_path / "ch"
    folder.mkdir()
    for ordinal in range(pages):
        image = _png(QSize(60, 80), QColor(40 + 50 * ordinal, 90, 120))
        (folder / f"{ordinal + 1:02d}.png").write_bytes(image)
    folder = folder.resolve()
    project_dir = project_dir_for(folder)
    with create_project(read_chapter(folder), project_dir) as project:
        project.write_regions(0, [_region(0)])
        project.write_lines(0, [OcrResult("一")])
        project.write_proposed(0, {0: "Hello."})
        for ordinal in done:
            _mark_done(project, ordinal)
    return project_dir


@pytest.fixture
def chapter(tmp_path: Path) -> Path:
    """Four pages; pages 1-2 done (test_rerun_guards.py's)."""
    return _project(tmp_path, PAGES, DONE)


@pytest.fixture
def one_page_chapter(tmp_path: Path) -> Path:
    """ONE page, not done: every other fixture has four, so the singular is
    never read (AC-2)."""
    return _project(tmp_path, 1, ())


def _statuses(project_dir: Path) -> list[str]:
    with open_project(project_dir) as project:
        return [project.page_status(page.ordinal) for page in project.pages()]


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# Fake stages, the gate and the logging setup (test_rerun_guards.py's)
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
# The world: every gate, run and window, torn down bounded
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


def _window(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    setup: Setup,
    project_dir: Path,
) -> Workspace:
    """The workspace as `mangatl.app.open_folder` builds it, shown, chapter loaded."""
    window = Workspace(run_setup=setup.run_setup())
    # Closed by `world`, NOT registered with `qtbot.addWidget`: pytest-qt closes
    # its widgets before any fixture is torn down, and `closeEvent` waits for a
    # held run - so it would wait out `GATE_S` before `world` released it.
    world.windows.append(window)
    window.resize(1100, 720)
    with qtbot.waitExposed(window):
        window.show()
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


def _open_dialog(window: Workspace) -> QDialog:
    """Activate Run again; the RerunDialog it opened."""
    _rerun_button(window).click()
    _settle()
    dialog = window.rerun_dialog
    assert isinstance(dialog, QDialog) and dialog.isVisible(), "Run again opened no dialog"
    assert type(dialog).__name__ == "RerunDialog", f"the dialog is a {type(dialog).__name__}"
    return dialog


def _primary(dialog: QDialog) -> QPushButton:
    primary = getattr(dialog, "run_button", None)
    assert isinstance(primary, QPushButton), f"the dialog's run_button is {primary!r}"
    return primary


def _rerun_dialogs(window: Workspace) -> list[QDialog]:
    """Every RerunDialog child of the window, shown OR hidden: a leaked dialog is hidden."""
    return [d for d in window.findChildren(QDialog) if type(d).__name__ == "RerunDialog"]


def _process_deferred_deletes() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    _settle()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _describe(widget: QWidget | None, window: QWidget) -> str:
    """The measured focus widget, for a failure message that reads as a bug report."""
    if widget is None:
        return "None"
    chain: list[str] = []
    parent = widget.parentWidget()
    while parent is not None:
        chain.append(f"{type(parent).__name__}({parent.objectName()!r})")
        parent = parent.parentWidget()
    return (
        f"{widget!r} objectName={widget.objectName()!r} isVisible={widget.isVisible()}"
        f" isEnabled={widget.isEnabled()} isVisibleTo(window)={widget.isVisibleTo(window)}"
        f" parents={' > '.join(chain) or '-'}"
    )


def _is_window_or_descendant(widget: QWidget, window: QWidget) -> bool:
    return widget is window or window.isAncestorOf(widget)


# =============================================================================
# AC-1 (W19): confirming the dialog leaves focus on nothing hidden or disabled
# =============================================================================


def test_confirming_run_again_leaves_focus_on_the_window_not_on_a_hidden_or_disabled_control(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    gate = Gate()
    world.gates.append(gate)
    setup = Setup([FakeStage("detect", gate), FakeStage("translate")])
    window = _window(qtbot, world, setup, chapter)
    dialog = _open_dialog(window)
    primary = _primary(dialog)
    qtbot.waitUntil(lambda: QApplication.focusWidget() is primary, timeout=FOCUS_MS)

    primary.click()
    _settle()
    run = window.run
    assert isinstance(run, RunController), f"window.run is {run!r} after the confirm"
    qtbot.waitUntil(gate.entered.is_set, timeout=RUN_MS)
    _settle()
    assert run.is_running(), "precondition: the run is on, held on page 3"

    focused = QApplication.focusWidget()
    measured = _describe(focused, window)
    assert focused is not None, f"while the run is on nothing has focus: {measured}"
    assert _is_window_or_descendant(focused, window), (
        f"while the run is on focus is outside the workspace: {measured}"
    )
    assert focused is window or (focused.isVisible() and focused.isEnabled()), (
        f"while the run is on focus is left on a hidden or disabled control: {measured}"
    )


# =============================================================================
# AC-2 (W15): a one-page chapter's return is announced in the singular
# =============================================================================


def test_a_finished_run_over_a_one_page_chapter_announces_1_of_1_page_done(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    one_page_chapter: Path,
) -> None:
    setup = Setup([FakeStage("detect"), FakeStage("translate")])
    window = _window(qtbot, world, setup, one_page_chapter)
    assert _statuses(one_page_chapter) != [PAGE_DONE], "precondition: the one page is not done"

    _primary(_open_dialog(window)).click()
    _settle()
    assert isinstance(window.run, RunController), "the confirm started no run"
    qtbot.waitUntil(lambda: window.run is None, timeout=RUN_MS)
    _settle()

    assert _statuses(one_page_chapter) == [PAGE_DONE], "precondition: the run finished the page"
    assert window.live_region.text() == "Run finished. 1 of 1 page done."


# =============================================================================
# AC-3 (W20): Run again twice leaves exactly one RerunDialog
# =============================================================================


def test_run_again_cancelled_then_activated_again_leaves_exactly_one_rerun_dialog(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    setup = Setup([FakeStage("detect"), FakeStage("translate")])
    window = _window(qtbot, world, setup, chapter)
    first = _open_dialog(window)
    with qtbot.waitSignal(first.finished, timeout=FOCUS_MS):
        first.reject()
    _settle()

    second = _open_dialog(window)
    assert second is not first, "precondition: the second Run again built a new dialog"
    _process_deferred_deletes()

    left = _rerun_dialogs(window)
    assert len(left) == 1, (
        f"after Run again twice the window holds {len(left)} RerunDialogs"
        f" (visible: {[d.isVisible() for d in left]}): the first was not deleted"
    )
    assert left[0] is window.rerun_dialog
