"""MT-161: a run started on page 1 returns to page 1; Cancel returns focus to Run again.

Two behaviours of MT-125's run hand-over in `mangatl.ui.workspace` that are
correct today and that no test pinned before this file:

- `_return_from_run`'s ``if 0 <= self._run_row < self.page_strip.count():``
  (N09, AC-1): `load_chapter` leaves the strip with no current row, and the
  row the run started on is put back - row 0 included. Every earlier test
  started its run on a later row, so ``0 <`` survived;
- `_on_rerun_dialog_finished`'s ``self._focus_rerun()`` on a cancel (N07,
  AC-2): focus is returned to Run again even when activating it did not move
  focus there (``click()``, as an accessibility default action does). The
  earlier test activated it with a key, which focuses the button first.

Oracle partition: both mechanical. The row and the focus widget are pinned
exactly; the negative control is the mutation each AC names, run through
`scripts/mutate.sh` against this file only (story `## Deferred verifications`
pastes each red).

**Threads and time.** Every wait is a bounded `qtbot.waitUntil` /
`qtbot.waitSignal`. The runs here are quick (fake stages with no action), and
the `world` fixture cancels and waits for any run still on, closes any dialog
left open, then closes every window - no worker outlives its test. The bounds
are liveness bounds copied from `test_rerun_handover.py`, not cost estimates.
No timing here comes from CI.

Fixtures are copied from `test_rerun_handover.py`, not imported: `tests` is not
a package.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget
from shiboken6 import isValid

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.prelude import Pipeline
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.store.intake import read_chapter
from mangatl.store.project import PAGE_DONE, Project, create_project, open_project, project_dir_for
from mangatl.ui.run import RunController, RunSetup
from mangatl.ui.workspace import Workspace

MODEL = "claude-sonnet-5"

# --- Liveness bounds (module docstring) ------------------------------------------
RUN_MS = 20_000
FOCUS_MS = 2_000

PAGES = 4
#: Pages 1-2 (ordinals 0, 1) are done before any run here.
DONE = (0, 1)


# =============================================================================
# Folders, projects and pages (test_rerun_handover.py's)
# =============================================================================


def _page_colour(ordinal: int) -> QColor:
    """Each page is one flat colour, distinct per page, so a pixel names the page."""
    return QColor(40 + 50 * ordinal, 90, 120)


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
        image = _png(QSize(60, 80), _page_colour(ordinal))
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
    """Four pages; pages 1-2 done (test_rerun_handover.py's)."""
    return _project(tmp_path, PAGES, DONE)


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# Fake stages and the logging setup (test_rerun_handover.py's)
# =============================================================================


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

    def build_stages(self, models_dir: Path) -> Pipeline:
        self.log.append("build")
        return Pipeline(stages=self.stages, prelude=None)

    def select_model(self) -> str:
        self.log.append("select")
        return MODEL

    def run_setup(self) -> RunSetup:
        return RunSetup(self.resolve_models, self.build_stages, self.select_model)


# =============================================================================
# The world: every run and window, torn down bounded
# =============================================================================


@dataclass
class World:
    windows: list[Workspace] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)


@pytest.fixture
def world(qtbot) -> Iterator[World]:  # type: ignore[no-untyped-def]
    made = World()
    yield made
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
    """The workspace as `mangatl.app.open_folder` builds it, shown, chapter
    loaded, row 0 current (as `open_folder` leaves it)."""
    window = Workspace(run_setup=setup.run_setup())
    # Closed by `world`, NOT registered with `qtbot.addWidget` (MT-128's handoff).
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
    """Activate Run again with `click()` - focus is NOT moved to it; the
    RerunDialog it opened."""
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


def _describe(widget: QWidget | None) -> str:
    """The measured focus widget, for a failure message that reads as a bug report."""
    if widget is None:
        return "None"
    return f"{type(widget).__name__} objectName={widget.objectName()!r}"


def _shown_page_pixel(window: Workspace) -> QColor | None:
    """The centre pixel of the page the canvas shows, or None if it shows none."""
    item = window.page_canvas.page_item
    if item is None:
        return None
    image = item.pixmap().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2)


# =============================================================================
# AC-1 (N09): a run started on row 0 returns to row 0, page 1 shown
# =============================================================================


def test_a_run_started_on_page_1_returns_the_strip_to_row_0_and_the_canvas_to_page_1(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    setup = Setup([FakeStage("detect"), FakeStage("translate")])
    window = _window(qtbot, world, setup, chapter)
    assert window.page_strip.currentRow() == 0, "precondition: row 0 is current"
    assert _shown_page_pixel(window) == _page_colour(0), "precondition: page 1 is shown"

    _primary(_open_dialog(window)).click()
    _settle()
    assert isinstance(window.run, RunController), "the confirm started no run"
    qtbot.waitUntil(lambda: window.run is None and window.run_panel is None, timeout=RUN_MS)
    _settle()

    row = window.page_strip.currentRow()
    assert row == 0, (
        f"a run started on page 1 (row 0) returned with the strip's current row {row}"
        f" of {window.page_strip.count()} (-1 is no row): page 1 was not put back"
    )
    state = window.page_canvas.state()
    assert state == "loaded", f"after the return the canvas is {state!r}, not showing page 1"
    pixel = _shown_page_pixel(window)
    assert pixel == _page_colour(0), (
        f"after the return the canvas shows a page coloured {pixel!r},"
        f" not page 1's {_page_colour(0)!r}"
    )


# =============================================================================
# AC-2 (N07): Cancel returns focus to Run again even when click() never moved it
# =============================================================================


def test_cancelling_run_again_activated_without_focus_returns_focus_to_run_again(
    qtbot,  # type: ignore[no-untyped-def]
    world: World,
    chapter: Path,
) -> None:
    setup = Setup([FakeStage("detect"), FakeStage("translate")])
    window = _window(qtbot, world, setup, chapter)
    button = _rerun_button(window)
    window.page_strip.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(lambda: QApplication.focusWidget() is window.page_strip, timeout=FOCUS_MS)
    before = QApplication.focusWidget()
    assert before is window.page_strip and before is not button, (
        f"precondition: focus is on the page strip, not on Run again: {_describe(before)}"
    )

    dialog = _open_dialog(window)
    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS):
        dialog.reject()
    _settle()

    with contextlib.suppress(qtbot.TimeoutError):
        qtbot.waitUntil(lambda: QApplication.focusWidget() is button, timeout=FOCUS_MS)
    focused = QApplication.focusWidget()
    assert focused is button, (
        f"after Cancel focus is on {_describe(focused)}, not on Run again (rerunButton)"
    )
