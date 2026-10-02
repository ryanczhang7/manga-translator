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

from mangatl.domain.page import Chapter
from mangatl.pipeline.runner import RUN_FINISHED, RunOutcome
from mangatl.store.project import create_project, project_dir_for
from mangatl.ui.intake import FolderDropTarget, choose_folder_dialog
from mangatl.ui.progress import RunProgressPanel
from mangatl.ui.run import NO_MODELS, RunController, RunSetup
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

#: A folder to the window that opened it, the chapter it would become, or the
#: reason it is neither.
FolderOpener = Callable[[Path], QMainWindow | Chapter | str]
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
        summary = ChapterSummary(chapter, self)
        summary.choose_other.connect(self._choose)
        summary.start_requested.connect(lambda: self._start(chapter))
        self.setCentralWidget(summary)
        summary.scroll_area.setFocus(Qt.FocusReason.OtherFocusReason)

    def closeEvent(self, event: QCloseEvent) -> None:
        """A run in progress is cancelled and waited for before the window
        goes, so its worker has closed its project (C-4, AC-6)."""
        self._closed = True
        if self.run is not None and self.run.is_running():
            self.run.cancel()
            self.run.wait()
        super().closeEvent(event)

    def _start(self, chapter: Chapter) -> None:
        """The Start sequence, in `mangatl-run`'s order: models, then create,
        then build, then run (C-3) - "read" is `chapter`, already read. Nothing
        is created without a models folder (AC-7)."""
        setup = self._run_setup
        models = setup.resolve_models() if setup is not None else None
        if setup is None or models is None:
            self.show_error(NO_MODELS)
            return
        project_dir = project_dir_for(chapter.source_dir)
        # Closed again here: the worker opens its own, as a `Project` crosses
        # no thread (C-1).
        with create_project(chapter, project_dir):
            pass
        stages = setup.build_stages(models)

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
