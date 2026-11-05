"""MT-113 AC-3 and C-6: a folder whose project has a pending batch job opens
straight to the waiting panel - dropped, chosen or named on the command line.

`app.open_folder` (C-6): a project with `pending_jobs` is closed again and
returned as `ui.batch_panel.PendingBatch`, before any `Workspace` is built.
`MainWindow._hand_over` and `app.build_window` hand that to
`MainWindow.show_waiting(pending)`, which asks `RunSetup.build_batch()`: a
`BatchSetup` shows a `BatchWaitingPanel` and starts a
`BatchController(project_dir, batch, None)` - the wait at once, the first poll
immediately; no batch setup (no builder, `None`, or a `ProviderError`) shows
AC-3's sentence and polls nothing.

**The jobs are real rows**: a project created on `tmp_path`, a `run` row and
`store.batch.record_submission`, with `submitted_at` re-stamped to fixed UTC
instants so "the earliest" and "local time" are exact. The pending jobs cover
fewer pages than the chapter has, so `n` is told apart from the page count.

**RED:** `PendingBatch`, `show_waiting`, `RunSetup.build_batch`, `BatchSetup`
and the waiting panel do not exist; each is reached inside a test or helper,
so the file collects and each test fails on its own.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMainWindow

from mangatl import app as app_module
from mangatl.domain.batch import BatchJob, BatchJobState, BatchResults
from mangatl.domain.events import BatchCollected, BatchWaiting, RunEvent
from mangatl.store.batch import mark_collected, pending_jobs, record_submission
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for
from mangatl.translate.provider import NoApiKey
from mangatl.ui import tokens_gen
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.main_window import MainWindow
from mangatl.ui.run import RunSetup
from mangatl.ui.summary import ChapterSummary
from mangatl.ui.workspace import Workspace

MODEL = "gemini-3.1-pro-preview"
WAIT_MS = 10_000
GATE_S = 10.0

#: The two jobs' submission instants: the LATER page range went first.
FIRST_RANGE_AT = "2026-11-04T09:15:00+00:00"
SECOND_RANGE_AT = "2026-11-04T08:40:00+00:00"


def hhmm(moment: datetime) -> str:
    return moment.astimezone().strftime("%H:%M")


def _now() -> datetime:
    return datetime.now().astimezone()


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _pending_batch_type() -> Any:
    from mangatl.ui.batch_panel import PendingBatch  # type: ignore[import-not-found]

    return PendingBatch


def _batch_panel_type() -> Any:
    from mangatl.ui.batch_panel import BatchWaitingPanel  # type: ignore[import-not-found]

    return BatchWaitingPanel


def _batch_setup(**fields: Any) -> Any:
    from mangatl.ui.run import BatchSetup  # type: ignore[attr-defined]

    return BatchSetup(**fields)


def _unkeyed(provider_job_id: str) -> str:
    """AC-3's sentence, spelled out."""
    return (
        f"Batch job {provider_job_id} is still pending, and collecting it needs the"
        " Gemini key that submitted it."
    )


# =============================================================================
# A folder with a project and pending jobs
# =============================================================================


def _png() -> bytes:
    image = QImage(QSize(60, 80), QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def _pending_folder(
    tmp_path: Path, ranges: tuple[tuple[int, int], ...] = ((2, 4),), pages: int = 6
) -> tuple[Path, tuple[int, ...]]:
    """A `pages`-page chapter whose project has one pending job per range."""
    folder = tmp_path / "Chapter 4"
    folder.mkdir()
    png = _png()
    for index in range(pages):
        (folder / f"{index + 1:02d}.png").write_bytes(png)
    folder = folder.resolve()
    with create_project(read_chapter(folder), project_dir_for(folder)) as project:
        with project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-11-04T08:00:00+00:00"),
            )
            run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
        ids = tuple(
            record_submission(project, run_id, f"batches/job-{k}", MODEL, first, last)
            for k, (first, last) in enumerate(ranges, 1)
        )
        stamps = (FIRST_RANGE_AT, SECOND_RANGE_AT)
        with project.transaction() as cursor:
            for job_id, stamp in zip(ids, stamps, strict=False):
                cursor.execute(
                    "UPDATE batch_job SET submitted_at = ? WHERE id = ?", (stamp, job_id)
                )
    return folder, ids


def _pending(folder: Path) -> tuple[BatchJob, ...]:
    with open_project(project_dir_for(folder)) as project:
        return pending_jobs(project)


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
            if answer == "collected":
                mark_collected(project, job.id)
                emit(BatchCollected(job.id, len(job.ordinals), 0, ()))
                return BatchResults({})
            emit(BatchWaiting(job_id=job.id, state="pending"))
            return BatchJobState("pending")
        finally:
            self.returned += 1


def _refuses() -> Any:
    raise NoApiKey("no API key is set")


def _never_submit(*args: Any) -> tuple[int, ...]:
    raise AssertionError("a reopen submitted the chapter again")


def _ceiling(project: Project) -> Any:
    from mangatl.domain.budget import DEFAULT_CEILING

    return DEFAULT_CEILING


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
    _settle()
    for window in made.windows:
        opened = getattr(window, "opened", None)
        if isinstance(opened, QMainWindow):
            opened.close()
        window.close()
    _settle()


def _setup(tmp_path: Path, build_batch: Any) -> RunSetup:
    models = tmp_path / "models"
    return RunSetup(  # type: ignore[call-arg]
        lambda: models, lambda m: (), lambda: MODEL, build_batch=build_batch
    )


def _gemini(collect: FakeCollect) -> Callable[[], Any]:
    batch = _batch_setup(submit=_never_submit, collect=collect, ceiling=_ceiling)
    return lambda: batch


def _intake(qtbot: Any, world: World, setup: RunSetup | None, chooser: Any = None) -> MainWindow:
    opener = (
        app_module.open_folder
        if setup is None
        else lambda folder: app_module.open_folder(folder, run_setup=setup)
    )
    window = MainWindow(open_folder=opener, run_setup=setup, choose_folder=chooser)
    qtbot.addWidget(window)
    world.windows.append(window)
    window.show()
    _settle()
    return window


def _drop(window: MainWindow, folder: Path) -> None:
    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget)
    target.dropped.emit(folder)
    _settle()


def _until(qtbot: Any, condition: Callable[[], bool], what: str, timeout: int = WAIT_MS) -> None:
    try:
        qtbot.waitUntil(condition, timeout=timeout)
    except Exception:
        pytest.fail(f"after {timeout} ms: {what}")


def _waiting_panel(qtbot: Any, window: QMainWindow) -> Any:
    panel_type = _batch_panel_type()
    _until(
        qtbot,
        lambda: isinstance(window.centralWidget(), panel_type),
        f"the window shows {type(window.centralWidget()).__name__}, not the waiting panel",
    )
    return window.centralWidget()


# =============================================================================
# app.open_folder
# =============================================================================


def test_open_folder_returns_a_pending_batch_for_a_project_with_a_pending_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, _ids = _pending_folder(tmp_path, ((0, 1), (2, 4)))
    opened: list[Project] = []
    real = app_module.open_project

    def spy(project_dir: Path) -> Project:
        project = real(project_dir)
        opened.append(project)
        return project

    monkeypatch.setattr(app_module, "open_project", spy)

    outcome = app_module.open_folder(folder)

    pending_type = _pending_batch_type()
    assert isinstance(outcome, pending_type), f"open_folder returned {outcome!r}"
    assert outcome == pending_type(
        source_dir=folder, project_dir=project_dir_for(folder), jobs=_pending(folder)
    )
    assert opened, "open_folder did not open the project to look for pending jobs"
    for project in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            project.select("SELECT 1")


def test_open_folder_still_opens_the_review_once_no_job_is_pending(
    qtbot: Any, tmp_path: Path
) -> None:
    folder, ids = _pending_folder(tmp_path)
    with open_project(project_dir_for(folder)) as project:
        mark_collected(project, ids[0])

    outcome = app_module.open_folder(folder)

    assert isinstance(outcome, Workspace), f"open_folder returned {outcome!r}"
    qtbot.addWidget(outcome)
    outcome.close()


# =============================================================================
# AC-3: dropped, chosen, named on the command line
# =============================================================================


def _assert_reopened_waiting(qtbot: Any, window: QMainWindow, collect: FakeCollect) -> Any:
    panel = _waiting_panel(qtbot, window)
    assert panel.submitted.text() == (
        f"Submitted 3 pages as one batch at {hhmm(datetime(2026, 11, 4, 9, 15, tzinfo=UTC))};"
        " waiting for Gemini."
    ), "AC-3: n is the pending job's 3 pages (not the chapter's 6), the time its submitted_at"
    assert panel.projection.isHidden(), "a reopen showed a projection (PO-4)"
    _until(qtbot, lambda: len(collect.calls) == 1, "a reopen did not poll at once")
    assert not isinstance(window.centralWidget(), ChapterSummary)
    assert getattr(window, "opened", None) is None, "a pending folder opened the review"
    return panel


def test_a_dropped_folder_with_a_pending_job_shows_the_waiting_panel_and_polls_at_once(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder, _ids = _pending_folder(tmp_path)
    collect = FakeCollect("pending")
    window = _intake(qtbot, world, _setup(tmp_path, _gemini(collect)))

    _drop(window, folder)

    _assert_reopened_waiting(qtbot, window, collect)


def test_a_chosen_folder_with_a_pending_job_shows_the_waiting_panel(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder, _ids = _pending_folder(tmp_path)
    collect = FakeCollect("pending")
    window = _intake(
        qtbot, world, _setup(tmp_path, _gemini(collect)), chooser=lambda parent: folder
    )

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget)
    target.activated.emit()
    _settle()

    _assert_reopened_waiting(qtbot, window, collect)


def test_a_folder_named_on_the_command_line_with_a_pending_job_opens_waiting(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder, _ids = _pending_folder(tmp_path)
    collect = FakeCollect("pending")

    window = app_module.build_window([str(folder)], run_setup=_setup(tmp_path, _gemini(collect)))
    qtbot.addWidget(window)
    world.windows.append(window)

    assert isinstance(window, MainWindow), f"build_window returned {window!r}"
    _assert_reopened_waiting(qtbot, window, collect)


def test_several_pending_jobs_read_as_their_pages_in_that_many_batches_at_the_earliest(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder, ids = _pending_folder(tmp_path, ((1, 2), (3, 5)))
    collect = FakeCollect("pending")
    window = _intake(qtbot, world, _setup(tmp_path, _gemini(collect)))

    _drop(window, folder)

    panel = _waiting_panel(qtbot, window)
    earliest = hhmm(datetime(2026, 11, 4, 8, 40, tzinfo=UTC))
    assert panel.submitted.text() == (
        f"Submitted 5 pages as 2 batches at {earliest}; waiting for Gemini."
    ), "AC-3: the jobs' 5 pages, their count, and the EARLIEST submitted_at (the second job's)"
    _until(qtbot, lambda: len(collect.calls) == 2, "a reopen did not poll every pending job")
    assert collect.calls == list(ids)


def test_a_reopened_wait_polls_on_with_the_time_of_each_check(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder, _ids = _pending_folder(tmp_path)
    collect = FakeCollect("pending")
    before = _now()
    window = _intake(qtbot, world, _setup(tmp_path, _gemini(collect)))
    _drop(window, folder)
    panel = _waiting_panel(qtbot, window)

    _until(qtbot, lambda: panel.last_checked.text() != "", "the first poll never reported")
    after = _now()

    assert panel.last_checked.text() in {f"Last checked {t}." for t in (hhmm(before), hhmm(after))}
    controller = getattr(window, "batch_run", None)
    assert controller is not None, "window.batch_run is None while waiting on a reopen"
    _until(qtbot, lambda: controller.poll_timer.isActive(), "a reopen's poll was not re-armed")


def test_a_reopened_job_that_is_collected_opens_the_review(
    qtbot: Any, world: World, tmp_path: Path
) -> None:
    folder, _ids = _pending_folder(tmp_path)
    collect = FakeCollect("collected")
    window = _intake(qtbot, world, _setup(tmp_path, _gemini(collect)))

    _drop(window, folder)

    _until(qtbot, lambda: isinstance(window.opened, Workspace), "the review never opened")
    workspace = window.opened
    assert isinstance(workspace, Workspace)
    qtbot.addWidget(workspace)
    assert workspace.page_strip.count() == 6
    assert _pending(folder) == ()


# =============================================================================
# AC-3: without a Gemini selection
# =============================================================================


@pytest.mark.parametrize(
    "build_batch",
    [
        pytest.param(lambda: None, id="no-batch-provider"),
        pytest.param("raise", id="provider-error"),
        pytest.param(None, id="no-batch-builder"),
    ],
)
def test_without_a_gemini_selection_the_reopen_says_so_and_polls_nothing(
    qtbot: Any, world: World, tmp_path: Path, build_batch: Any
) -> None:
    folder, _ids = _pending_folder(tmp_path)
    if build_batch == "raise":
        build_batch = _refuses
    window = _intake(qtbot, world, _setup(tmp_path, build_batch))

    _drop(window, folder)

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget), (
        f"a pending folder with no Gemini selection shows {type(target).__name__}"
    )
    assert target.headline.text() == _unkeyed("batches/job-1")
    assert getattr(window, "opened", None) is None
    assert getattr(window, "batch_run", None) is None, "a controller was started with no batch"
    assert len(_pending(folder)) == 1
