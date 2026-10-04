"""A render of the chapter, off the GUI thread (MT-066 C-3).

Two steps, each a worker of its own: `preview()` computes the counts the Render
dialog states (`preview_bake` typesets every line it would set, ~18 ms each, so
it is not done on the GUI thread either), and `bake()` writes the pages
(`bake_chapter`) to `<source>_en`. It follows `RunController` (`ui/run.py`) for
the same reasons:

- Each step opens its **own** `Project` and closes it before the thread ends.
  Under `check_same_thread`, a `Project` never crosses threads.
- `open_project`, `preview_bake`, `bake_chapter` and `output_dir_for` are called
  as attributes of this module, which is the seam the tests patch.
- `previewed`, `baked` and `failed` are emitted from the worker; a receiver on
  the GUI thread gets them through Qt's queued connection.
- Any exception from either step is emitted as `failed(str(error))`. Nothing
  propagates out of the thread.

This is the only window module that names `bake_chapter` and `preview_bake`
(C-5).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from mangatl.pipeline.bake import bake_chapter, output_dir_for, preview_bake
from mangatl.store.project import Project, open_project

__all__ = ["BakeController"]


class BakeController(QObject):
    """The two steps of a render of the chapter in `project_dir`, each on a worker."""

    #: The `BakePreview` of `preview()`.
    previewed = Signal(object)
    #: The `BakeReport` of `bake()`.
    baked = Signal(object)
    #: `str(exception)`, from either step.
    failed = Signal(str)

    def __init__(self, project_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project_dir = project_dir
        self._thread: threading.Thread | None = None

    def preview(self) -> None:
        """Compute the counts on a worker and return at once."""
        self._start(self._preview, "mangatl-render-preview")

    def bake(self) -> None:
        """Write the pages on a worker and return at once."""
        self._start(self._bake, "mangatl-render")

    def wait(self) -> None:
        """Block until the current worker has returned and closed its project;
        a no-op when none started."""
        if self._thread is not None:
            self._thread.join()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _start(self, step: Callable[[Project], Callable[[], None]], name: str) -> None:
        self._thread = threading.Thread(target=self._work, args=(step,), name=name, daemon=True)
        self._thread.start()

    def _work(self, step: Callable[[Project], Callable[[], None]]) -> None:
        # The step's result is emitted after its project is closed, so a
        # receiver that starts the next step finds this worker all but done.
        try:
            with open_project(self._project_dir) as project:
                emit = step(project)
        except Exception as error:  # every failure is reported; none escapes the thread
            self.failed.emit(str(error))
            return
        emit()

    def _preview(self, project: Project) -> Callable[[], None]:
        preview = preview_bake(project)
        return lambda: self.previewed.emit(preview)

    def _bake(self, project: Project) -> Callable[[], None]:
        report = bake_chapter(project, output_dir_for(project.chapter.source_dir))
        return lambda: self.baked.emit(report)
