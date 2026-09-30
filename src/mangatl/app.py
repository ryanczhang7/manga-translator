"""Entry point: `mangatl [<folder>]`.

With no argument it opens MT-001's empty window. With a chapter folder whose
sibling `<folder>.mtproj` project exists it opens the review `Workspace` on that
chapter, first page shown (MT-054). Anything else - a folder with no project, a
path that is not a folder, a project from a newer build, too many arguments -
opens the same window with a notice saying what is wrong and, where there is
one, the command that fixes it. Nothing here creates a project: `mangatl-run`
(MT-006) is the only thing that does.

`build_window` is the seam and is tested in process; `main` is a shell over it.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow

from mangatl.store.project import SchemaTooNew, open_project, project_dir_for
from mangatl.ui.main_window import MainWindow
from mangatl.ui.workspace import Workspace

__all__ = ["build_window", "main"]

# The folder is always resolved: the command must work pasted into any shell,
# from any directory; double quotes because Windows paths carry spaces.
NO_PROJECT_NOTICE = (
    'No project exists for {folder}.\nCreate one by running:  mangatl-run "{folder}"'
)
NO_FOLDER_NOTICE = "No such folder: {folder}"
USAGE_NOTICE = "mangatl opens one chapter folder:  mangatl <folder>"


def build_window(arguments: Sequence[str]) -> QMainWindow:
    """The window for a command line without the program name, NOT shown."""
    if not arguments:
        return MainWindow()
    if len(arguments) > 1:
        return MainWindow(notice=USAGE_NOTICE)
    folder = Path(arguments[0]).resolve()
    if not folder.is_dir():
        return MainWindow(notice=NO_FOLDER_NOTICE.format(folder=folder))
    try:
        # `open_project` checks the path before sqlite can create anything, so
        # a folder with no project writes nothing.
        project = open_project(project_dir_for(folder))
    except FileNotFoundError:
        return MainWindow(notice=NO_PROJECT_NOTICE.format(folder=folder))
    except SchemaTooNew as error:
        return MainWindow(notice=str(error))
    window = Workspace()
    window.load_chapter(project)
    window.page_strip.setCurrentRow(0)
    # The window owns the project from here: closed after the pending saves.
    window.closed.connect(lambda: project.__exit__(None, None, None))
    return window


def main(argv: list[str] | None = None) -> int:
    """Run the application. Returns the Qt exit code."""
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    window = build_window(argv[1:])
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
