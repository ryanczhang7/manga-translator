"""The application's window when no chapter is open.

With no `notice` it is the folder intake (MT-055): its whole content is one
view, `centralWidget()`, which is either a `FolderDropTarget` or - once a
folder of pages with no project has been read (MT-057) - that chapter's
`ChapterSummary`. Activating the target asks `choose_folder` for a folder,
dropping one folder on it (MT-056) supplies one directly, and the summary's
"Choose a different folder" asks the same chooser; every way, the folder goes
down one path to `open_folder`. The window does not decide what a folder means
- `mangatl.app` injects that function, the same one `mangatl <folder>` runs, so
the picker, the drop and the command line cannot drift apart. A window back
from it is the opened chapter: it is shown, then this window closes. A
`Chapter` back is a folder with no project: its summary is shown. A string back
is the reason nothing opened, shown in the target's error state.

The summary's "Start run" (MT-059) runs the chapter, in `mangatl-run`'s order:
the models folder from the injected `RunSetup` (none: AC-7's sentence, and
nothing is created), the project beside the folder, the stage list, then a
`RunController` on a worker thread whose events drive the `RunProgressPanel`
that becomes the window's content. A finished run - or "Review pages 1-N"
after an abort - goes down the same folder path to the `Workspace`. Closing
the window mid-run cancels the run and waits for the worker first. The window
never imports the composition root: `mangatl.app` injects the stage builder.

**A batch Start** (MT-113 C-6): after the models folder the window asks
`RunSetup.build_batch()`. A `BatchSetup` back is the batch path - the project,
a `RunProgressPanel(batch=True)` for the local stages, and a `BatchController`
held on `batch_run`; when the wait begins the content becomes a
`BatchWaitingPanel`, and a collected batch opens the review down the same
folder path. `None` back is the per-page run above, untouched (AC-5). A folder
whose project has a pending job comes back from `open_folder` as a
`PendingBatch`, and `show_waiting` opens the waiting panel straight away and
polls - or, with no batch to collect it with, says which job needs the Gemini
key (AC-3). Closing the window stops the wait and leaves the job pending (AC-6).

With a `notice` (MT-054 C-5) the window says one thing instead: why no chapter
could be opened, and what to do about it. The notice is the whole content of
the window, so it is its accessible name, plain text (a folder name holding
`<` is not markup) and selectable, so the command it names can be copied.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget

from mangatl.domain.events import RunEvent
from mangatl.domain.glossary import UnknownContextMode
from mangatl.domain.page import Chapter
from mangatl.pipeline.runner import RUN_FINISHED, RunOutcome
from mangatl.store.project import create_project, project_dir_for
from mangatl.translate.provider import ProviderError
from mangatl.ui.batch_panel import BatchWaitingPanel, PendingBatch
from mangatl.ui.cost_estimate import NoProvider
from mangatl.ui.intake import FolderDropTarget, choose_folder_dialog
from mangatl.ui.progress import RunProgressPanel
from mangatl.ui.run import (
    NO_MODELS,
    BatchController,
    BatchEnd,
    BatchSetup,
    RunController,
    RunSetup,
    WaitingState,
)
from mangatl.ui.summary import ChapterSummary

__all__ = [
    "NOTICE_OBJECT_NAME",
    "WINDOW_TITLE",
    "FolderChooser",
    "FolderOpener",
    "MainWindow",
]

WINDOW_TITLE = "mangatl"
NOTICE_OBJECT_NAME = "notice"

#: AC-3's sentence: a pending job, and no Gemini selection to collect it with.
NO_BATCH_TO_COLLECT = (
    "Batch job {provider_job_id} is still pending, and collecting it needs the"
    " Gemini key that submitted it."
)

#: A folder to the window that opened it, the chapter it would become, its
#: pending batch (MT-113), or the reason it is none of those.
FolderOpener = Callable[[Path], QMainWindow | Chapter | PendingBatch | str]
#: The chosen folder, or `None` when the choice was dismissed.
FolderChooser = Callable[[QWidget], Path | None]


class MainWindow(QMainWindow):
    """The single top-level window before a chapter is open."""

    def __init__(
        self,
        notice: str | None = None,
        *,
        open_folder: FolderOpener | None = None,
        choose_folder: FolderChooser | None = None,
        run_setup: RunSetup | None = None,
    ) -> None:
        if notice is None and open_folder is None:
            # A window that can choose a folder and do nothing with it is not
            # a state this app has (MT-055 C-2).
            raise TypeError("MainWindow needs a notice or an open_folder")
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.open_folder = open_folder
        self.opened: QMainWindow | None = None
        # `None`: a window nobody gave a models folder has none (C-3).
        self._run_setup = run_setup
        self._run_folder: Path | None = None
        self.run: RunController | None = None
        self.run_panel: RunProgressPanel | None = None
        #: The batch run, from a batch Start or a pending reopen (C-6, A-R2).
        self.batch_run: BatchController | None = None
        self._closed = False
        if notice is not None:
            self.setCentralWidget(_notice_label(notice, self))
            return
        assert open_folder is not None  # the TypeError above
        self._open: FolderOpener = open_folder
        self._choose_folder = choose_folder or choose_folder_dialog
        self.setCentralWidget(self._new_target())

    def show_summary(self, chapter: Chapter) -> None:
        """Replace the current view with `chapter`'s summary, focus on its
        scroll area so arrows and Page keys read it at once."""
        summary = ChapterSummary(chapter, self, model=self._selected_model())
        summary.choose_other.connect(self._choose)
        summary.start_requested.connect(lambda: self._start(chapter))
        self.setCentralWidget(summary)
        summary.scroll_area.setFocus(Qt.FocusReason.OtherFocusReason)

    def _selected_model(self) -> str | NoProvider:
        """The model the summary's estimate is priced on (MT-100 C-6): the one
        Start would call, or `NoProvider` saying why there is none - Start's own
        sentence, `NO_MODELS` with no setup, else the `ProviderError`'s."""
        setup = self._run_setup
        if setup is None:
            return NoProvider(NO_MODELS)
        try:
            return setup.select_model()
        except ProviderError as error:
            return NoProvider(str(error))

    def closeEvent(self, event: QCloseEvent) -> None:
        """A run in progress is cancelled and waited for before the window
        goes, so its worker has closed its project (C-4, AC-6). A batch run is
        stopped - its timer, and a poll in flight waited for - and nothing is
        cancelled at the provider (MT-113 AC-6)."""
        self._closed = True
        if self.run is not None and self.run.is_running():
            self.run.cancel()
            self.run.wait()
        if self.batch_run is not None and self.batch_run.is_running():
            self.batch_run.stop()
        super().closeEvent(event)

    def _start(self, chapter: Chapter) -> None:
        """The Start sequence: models, then build, then create, then run -
        "read" is `chapter`, already read. Nothing is created without a models
        folder (AC-7), nor when the stages cannot be built: a `ProviderError`
        (no key, several keys, no adapter yet) or an `UnknownContextMode`
        (MT-107 PO-2) is shown as the window's error
        and leaves no project behind, matching `mangatl-run` (MT-078 C-4, A-1).
        Any other exception from the builder propagates."""
        setup = self._run_setup
        models = setup.resolve_models() if setup is not None else None
        if setup is None or models is None:
            self.show_error(NO_MODELS)
            return
        try:
            batch = setup.build_batch() if setup.build_batch is not None else None
        except ProviderError as error:
            self.show_error(str(error))
            return
        if batch is not None:
            self._start_batch(chapter, batch, models)
            return
        try:
            stages = setup.build_stages(models)
        except (ProviderError, UnknownContextMode) as error:
            self.show_error(str(error))
            return
        project_dir = project_dir_for(chapter.source_dir)
        # Closed again here: the worker opens its own, as a `Project` crosses
        # no thread (C-1).
        with create_project(chapter, project_dir):
            pass

        panel = RunProgressPanel(chapter=chapter)
        # The summary is deleted with its focused button; focus must not be
        # left on it (D-2). The panel has no focus stop while running, so the
        # window itself holds focus until a banner's action takes it.
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setCentralWidget(panel)
        self.run_panel = panel
        self._run_folder = chapter.source_dir
        self.run = RunController(project_dir, stages, self)
        self.run.event.connect(panel.on_event)
        self.run.ended.connect(self._run_ended)
        panel.review_requested.connect(self._review)
        self.run.start()

    def _start_batch(self, chapter: Chapter, batch: BatchSetup, models: Path) -> None:
        """MT-113 C-6: the project, the local stages' panel under the batch
        stepper, and the controller that submits and then waits."""
        project_dir = project_dir_for(chapter.source_dir)
        with create_project(chapter, project_dir):
            pass

        panel = RunProgressPanel(chapter=chapter, batch=True)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setCentralWidget(panel)
        self.run_panel = panel
        self._run_folder = chapter.source_dir
        self._watch(BatchController(project_dir, batch, models, self)).start()

    def show_waiting(self, pending: PendingBatch) -> None:
        """A folder with a pending batch job (AC-3): the waiting panel and the
        first poll at once - or, with no batch setup to collect it with, the
        sentence naming the job."""
        setup = self._run_setup
        try:
            batch = setup.build_batch() if setup is not None and setup.build_batch else None
        except ProviderError:
            batch = None
        if batch is None:
            self.show_error(
                NO_BATCH_TO_COLLECT.format(provider_job_id=pending.jobs[0].provider_job_id)
            )
            return
        self._run_folder = pending.source_dir
        self._watch(BatchController(pending.project_dir, batch, None, self)).start()

    def _watch(self, controller: BatchController) -> BatchController:
        """Hold `controller` and wire it to the window, which hands each event
        to whichever panel is showing - the run panel during the local stages,
        the waiting panel once the wait begins."""
        self.batch_run = controller
        controller.event.connect(self._batch_event)
        controller.poll_failed.connect(self._poll_failed)
        controller.waiting.connect(self._waiting)
        controller.ended.connect(self._batch_ended)
        return controller

    @Slot(object)
    def _batch_event(self, event: RunEvent) -> None:
        current = self.centralWidget()
        if isinstance(current, RunProgressPanel | BatchWaitingPanel):
            current.on_event(event)

    @Slot(object)
    def _poll_failed(self, error: BaseException) -> None:
        current = self.centralWidget()
        if isinstance(current, BatchWaitingPanel):
            current.poll_error(error)

    @Slot(object)
    def _waiting(self, state: WaitingState) -> None:
        """The wait has begun: the waiting panel, filled, becomes the content
        in place of the run panel or the drop target (AC-1, AC-3)."""
        panel = BatchWaitingPanel(self)
        panel.show_state(state)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setCentralWidget(panel)

    @Slot(object)
    def _batch_ended(self, end: BatchEnd) -> None:
        """A collected batch opens the review; a failed one leaves the waiting
        panel's banner, a refused one the run panel's."""
        if end == "collected":
            self._review()

    @Slot(object)
    def _run_ended(self, outcome: RunOutcome) -> None:
        """A finished run opens the review; any other outcome leaves the panel
        saying why (C-3)."""
        if outcome.outcome == RUN_FINISHED:
            self._review()

    @Slot()
    def _review(self) -> None:
        """The chapter's `Workspace`, down the one folder path (MT-056 C-2) -
        unless the window has closed, after which nothing opens (C-4)."""
        if not self._closed:
            assert self._run_folder is not None  # set by _start, the only way here
            self._hand_over(self._run_folder)

    def show_error(self, text: str) -> None:
        """The drop target's error state with `text` as its headline: the
        target already showing, or a new one in place of a summary."""
        target = self.centralWidget()
        if not isinstance(target, FolderDropTarget):
            target = self._new_target()
            self.setCentralWidget(target)
        target.show_error(text)

    def _new_target(self) -> FolderDropTarget:
        """A drop target wired to the chooser and to the hand-over - the same
        wiring whether it is the first view or one put back after a summary."""
        target = FolderDropTarget(self)
        target.activated.connect(self._choose)
        target.dropped.connect(self._hand_over)
        return target

    def _choose(self) -> None:
        folder = self._choose_folder(self)
        if folder is None:
            # Dismissed: nothing changes, and a summary's button gets focus
            # back from wherever the dialog left it.
            current = self.centralWidget()
            if isinstance(current, ChapterSummary):
                current.choose.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self._hand_over(folder)

    def _hand_over(self, folder: Path) -> None:
        """The one path a folder takes, chosen, dropped or chosen from a
        summary (MT-056 C-2, MT-057 C-4)."""
        outcome = self._open(folder)
        if isinstance(outcome, Chapter):
            self.show_summary(outcome)
            return
        if isinstance(outcome, PendingBatch):
            self.show_waiting(outcome)
            return
        if isinstance(outcome, str):
            self.show_error(outcome)
            return
        self.opened = outcome
        # Shown first, so quit-on-last-window-closed never sees zero windows.
        outcome.show()
        self.close()


def _notice_label(notice: str, parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName(NOTICE_OBJECT_NAME)
    # Before the text, so it is never interpreted as rich text.
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(notice)
    label.setAccessibleName(notice)
    label.setWordWrap(True)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    return label
