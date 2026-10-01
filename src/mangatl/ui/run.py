"""A run of the chapter, off the GUI thread (MT-059 C-1).

`architecture.md` §6: "`ui` -> `pipeline`: commands ... returns immediately;
the work runs on a worker thread", and "`pipeline` -> `ui`: an event stream ...
Qt signals at the boundary". `RunController` is that thread and that boundary.

The worker opens its **own** `Project` and closes it before it ends: sqlite's
`check_same_thread` means a `Project` crosses no thread, so the one the GUI
thread created is closed there and never handed over. `open_project` is called
by this module's name for it, which is the seam the tests observe.

`event` and `ended` are emitted from the worker. A receiver living on the GUI
thread gets them through Qt's queued connection, so they arrive there, in
emission order, and `ended` after the last `event`. `domain.events` are frozen
dataclasses, so nothing a receiver holds is shared mutable state.

The stages arrive already built (`RunSetup.build_stages`, injected by the
composition root `mangatl.app`): `ui` never imports `mangatl.compose`, so the
window never constructs an inference session or an API client itself.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from mangatl.domain.events import RunEvent
from mangatl.pipeline.runner import run_chapter
from mangatl.pipeline.stage import Stage
from mangatl.store.project import open_project

__all__ = ["NO_MODELS", "ModelsResolver", "RunController", "RunSetup", "StageBuilder"]

#: AC-7, the Lead PO's wording. It names the variable and not `--models`,
#: which a window user cannot pass (PO-4).
NO_MODELS: str = (
    "No models folder: set MANGATL_MODELS to the folder holding the model"
    " weights, then start the app again."
)

#: The models folder, or `None` when there is none.
ModelsResolver = Callable[[], Path | None]
#: The stage list for a models folder.
StageBuilder = Callable[[Path], Sequence[Stage]]


@dataclass(frozen=True)
class RunSetup:
    """What the composition root gives the window to start a run with."""

    resolve_models: ModelsResolver
    build_stages: StageBuilder


class RunController(QObject):
    """One run of the chapter in `project_dir` through `stages`, on a worker."""

    #: Each `RunEvent`, in emission order. The contract names it `event`, and the
    #: tests connect to it so; it shadows `QObject.event()`, which Qt calls from
    #: C++ (PySide dispatches to a Python override only when it is a method) and
    #: nothing in this app calls on a controller.
    event = Signal(object)  # type: ignore[assignment]
    #: The `RunOutcome` `run_chapter` returned, after the last `event`.
    ended = Signal(object)

    def __init__(
        self,
        project_dir: Path,
        stages: Sequence[Stage],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_dir = project_dir
        self._stages = tuple(stages)
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the worker and return at once."""
        self._thread = threading.Thread(target=self._work, name="mangatl-run", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Ask the run to stop at its next stage boundary. Thread-safe."""
        self._cancel.set()

    def wait(self) -> None:
        """Block until the worker has returned and closed its project; a no-op
        when it never started."""
        if self._thread is not None:
            self._thread.join()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _work(self) -> None:
        with open_project(self._project_dir) as project:
            outcome = run_chapter(project, self._stages, self._emit, self._cancel.is_set)
        self.ended.emit(outcome)

    def _emit(self, event: RunEvent) -> None:
        self.event.emit(event)
