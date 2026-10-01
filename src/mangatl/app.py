"""Entry point: `mangatl [<folder>]`.

With no argument it opens the folder intake (MT-055): a window that asks for a
chapter folder. With a chapter folder whose sibling `<folder>.mtproj` project
exists it opens the review `Workspace` on that chapter, first page shown
(MT-054). A folder of pages with no project opens the intake window showing
that chapter's summary - what a run would read - and a folder that cannot be
read as a chapter (no page images, not listable, a page that will not decode)
opens the intake window in its error state saying why (MT-057, PO-3/PO-8).
Anything else - a path that is not a folder, a project from a newer build, too
many arguments - opens a window with a notice saying what is wrong. Nothing
here creates a project or writes anything.

**The composition root for the window (MT-059, PO-3).** Every intake window is
given a `RunSetup`: `resolve_models` (`$MANGATL_MODELS`, read when Start is
pressed) and `build_stages` (`mangatl.compose.build_pipeline`, translation
on). Both import `mangatl.compose` inside their bodies, so a launch that only
reviews never loads `onnxruntime` or `anthropic`; import-linter counts those
imports all the same, which is why this module is exempt from the two
contracts that confine them, as `mangatl.cli` is. The window - `mangatl.ui` -
never imports `compose`; the run itself, and creating the project, are the
window's (`mangatl.ui.main_window`, `mangatl.ui.run`), never this module's.

`open_folder` is the one folder -> outcome decision. The command line calls it
and the intake window is handed it, so a folder picked or dropped in the window
behaves exactly as the same folder named on the command line.

`build_window` is the seam and is tested in process; `main` is a shell over it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow

from mangatl.domain.page import Chapter
from mangatl.pipeline.stage import Stage
from mangatl.store.intake import NoPagesFound, UnreadablePage, read_chapter
from mangatl.store.project import SchemaTooNew, open_project, project_dir_for
from mangatl.ui.main_window import MainWindow
from mangatl.ui.run import RunSetup
from mangatl.ui.stylesheet import apply_base_stylesheet
from mangatl.ui.workspace import Workspace

__all__ = [
    "IntakeError",
    "build_stages",
    "build_window",
    "main",
    "open_folder",
    "resolve_models",
]

# The folder is always resolved, so the text names it the same way from any
# working directory.
NO_FOLDER_NOTICE = "No such folder: {folder}"
USAGE_NOTICE = "mangatl opens one chapter folder:  mangatl <folder>"
NO_PAGES_ERROR = "No page images in {folder}. This tool reads .png and .jpg files."
UNREADABLE_PAGE_ERROR = (
    "{filename} could not be opened as a page image."
    " Remove or replace it, then choose the folder again."
)
UNLISTABLE_ERROR = "Windows would not let this app read {folder}.\n{os_error}"


class IntakeError(str):
    """An outcome that is the intake's own error state (AC-2, AC-3, AC-6),
    as opposed to a notice (no such folder, a newer build's project).

    A `str` subclass so every caller that shows a reason keeps working; only
    the command line needs the difference, to pick the intake window over the
    notice window (MT-057 PO-8)."""

    __slots__ = ()


def open_folder(folder: Path) -> QMainWindow | Chapter | str:
    """What `folder` opens as: its project's `Workspace` NOT shown, the
    `Chapter` a run would read when it has no project, or the reason it is
    neither - an `IntakeError` when the folder itself cannot be read as a
    chapter, a plain notice otherwise."""
    folder = folder.resolve()
    if not folder.is_dir():
        return NO_FOLDER_NOTICE.format(folder=folder)
    try:
        # `open_project` checks the path before sqlite can create anything, so
        # a folder with no project writes nothing.
        project = open_project(project_dir_for(folder))
    except FileNotFoundError:
        return _read(folder)
    except SchemaTooNew as error:
        return str(error)
    window = Workspace()
    window.load_chapter(project)
    window.page_strip.setCurrentRow(0)
    # The window owns the project from here: closed after the pending saves.
    window.closed.connect(lambda: project.__exit__(None, None, None))
    return window


def _read(folder: Path) -> Chapter | IntakeError:
    """`folder` read by the store, in the order a run will use - one listing,
    one sort, both `read_chapter`'s (MT-057 C-2). Reads only."""
    try:
        return read_chapter(folder)
    except NoPagesFound:
        return IntakeError(NO_PAGES_ERROR.format(folder=folder))
    except UnreadablePage as error:
        # Named from the attribute, never parsed out of the message (C-1).
        return IntakeError(UNREADABLE_PAGE_ERROR.format(filename=error.filename))
    except OSError as error:
        # The operating system's own words, passed through, not paraphrased.
        os_error = error.strerror if error.strerror is not None else str(error)
        return IntakeError(UNLISTABLE_ERROR.format(folder=folder, os_error=os_error))


def resolve_models() -> Path | None:
    """The models folder `$MANGATL_MODELS` names, read now, or `None` when it
    names none (PO-4: the environment is the only source until MT-024)."""
    from mangatl.compose import ModelsNotFound, resolve_models_dir

    try:
        return resolve_models_dir(None, os.environ)
    except ModelsNotFound:
        return None


def build_stages(models_dir: Path) -> tuple[Stage, ...]:
    """The real stage list, translation on - what `mangatl-run` runs."""
    from mangatl.compose import build_pipeline

    return build_pipeline(models_dir, translate=True)


def build_window(arguments: Sequence[str], *, run_setup: RunSetup | None = None) -> QMainWindow:
    """The window for a command line without the program name, NOT shown.

    Every intake window gets `run_setup`, by default the real one - looked up
    when this runs, so it is this module's `resolve_models` and `build_stages`
    as they are then."""
    if run_setup is None:
        run_setup = RunSetup(resolve_models, build_stages)
    if not arguments:
        return MainWindow(open_folder=open_folder, run_setup=run_setup)
    if len(arguments) > 1:
        return MainWindow(notice=USAGE_NOTICE)
    outcome = open_folder(Path(arguments[0]))
    if isinstance(outcome, Chapter):
        intake = MainWindow(open_folder=open_folder, run_setup=run_setup)
        intake.show_summary(outcome)
        return intake
    if isinstance(outcome, IntakeError):
        intake = MainWindow(open_folder=open_folder, run_setup=run_setup)
        intake.show_error(outcome)
        return intake
    if isinstance(outcome, str):
        return MainWindow(notice=outcome)
    return outcome


def main(argv: list[str] | None = None) -> int:
    """Run the application. Returns the Qt exit code."""
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    # Before any window is built, so none is ever shown unthemed (MT-061).
    apply_base_stylesheet(app)
    window = build_window(argv[1:])
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
