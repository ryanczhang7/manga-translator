"""The batch run's waiting state (MT-113 C-4).

A batch is submitted, then waited for - for minutes or hours, across the window
being closed and the folder opened again. `BatchWaitingPanel` is what the
window shows meanwhile: what was submitted and when, the projection against
the ceiling (only after a submission: a reopen has no stored projection,
PO-4), when the jobs were last asked and what that poll raised, and - when the
provider reports a job failed, cancelled or expired - `progress.ErrorBanner`,
reused, with no action.

The panel is fed by the window: `show_state` with the controller's
`WaitingState`, `on_event` with every `RunEvent` of a poll (`BatchWaiting` sets
the time, `BatchFailed` the banner), and `poll_error` with what a poll raised.
It never polls, and never reads the store.

**Times are local `HH:MM`**, `t.astimezone().strftime("%H:%M")`, from the
state's aware `submitted_at` and the injected `now` for each poll.

`PendingBatch` is what `app.open_folder` returns for a project with a pending
job: the window opens this panel rather than the summary or the review (AC-3).
It lives here, beside the panel it opens, so `ui.main_window` can name it
without importing `mangatl.app`.

Every colour and type size comes from the application stylesheet by object
name (MT-061's rule); spacing comes from the tokens.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QVBoxLayout, QWidget

from mangatl.domain.batch import BatchJob
from mangatl.domain.events import BatchFailed, BatchWaiting, RunEvent
from mangatl.ui import tokens_gen
from mangatl.ui.cost_estimate import format_usd
from mangatl.ui.labels import plain_label
from mangatl.ui.progress import ErrorBanner
from mangatl.ui.run import WaitingState

__all__ = ["BatchWaitingPanel", "PendingBatch"]


@dataclass(frozen=True)
class PendingBatch:
    """A chapter folder whose project has a pending batch job (MT-113 C-6):
    its folder, its project folder and the pending jobs, in page order."""

    source_dir: Path
    project_dir: Path
    jobs: tuple[BatchJob, ...]


def _hhmm(moment: datetime) -> str:
    return moment.astimezone().strftime("%H:%M")


def _local_now() -> datetime:
    return datetime.now().astimezone()


class BatchWaitingPanel(QWidget):
    """What was submitted, when, and the last time it was asked for."""

    def __init__(
        self, parent: QWidget | None = None, *, now: Callable[[], datetime] = _local_now
    ) -> None:
        super().__init__(parent)
        self.setObjectName("batch-waiting")
        self._now = now
        self.submitted = plain_label("batch-submitted", "")
        self.projection = plain_label("batch-projection", "")
        self.last_checked = plain_label("batch-last-checked", "")
        self.banner: ErrorBanner | None = None

        self._column = QVBoxLayout(self)
        pad = tokens_gen.SPACE_S4
        self._column.setContentsMargins(pad, pad, pad, pad)
        self._column.setSpacing(tokens_gen.SPACE_S3)
        self._column.addWidget(self.submitted)
        self._column.addWidget(self.projection)
        self._column.addWidget(self.last_checked)
        self._column.addStretch(1)

    def show_state(self, state: WaitingState) -> None:
        """The submission's lines: `one batch` or `{k} batches`, and the
        projection line only when there is a projection (PO-4)."""
        batches = "one batch" if state.job_count == 1 else f"{state.job_count} batches"
        self.submitted.setText(
            f"Submitted {state.page_count} pages as {batches} at"
            f" {_hhmm(state.submitted_at)}; waiting for Gemini."
        )
        if state.projection is None or state.ceiling is None:
            self.projection.setText("")
            self.projection.hide()
        else:
            self.projection.setText(
                f"Projected {format_usd(state.projection)} of {format_usd(state.ceiling)}"
            )
            self.projection.show()
        self._name()

    def on_event(self, event: RunEvent) -> None:
        """A poll's event: a job still waiting sets the time it was asked; a
        failed job shows the banner. Every other event changes nothing."""
        if isinstance(event, BatchWaiting):
            self.last_checked.setText(f"Last checked {_hhmm(self._now())}.")
            self._name()
        elif isinstance(event, BatchFailed):
            self._failed(event.state)

    def poll_error(self, error: BaseException) -> None:
        """A poll that raised: its type and message beside the time. Not a
        failed job, so no banner - the wait goes on."""
        self.last_checked.setText(
            f"Last checked {_hhmm(self._now())}: {type(error).__name__}: {error}"
        )
        self._name()

    def _failed(self, state: str) -> None:
        banner = ErrorBanner(
            f"Batch job failed \N{EM DASH} Gemini reports it {state}.",
            "Its pages were not translated.",
            (),
            self,
        )
        self._column.insertWidget(0, banner)
        banner.show()
        self.banner = banner
        banner.announce()

    def _name(self) -> None:
        """The accessible name is the visible lines, in order (C-4)."""
        lines = [self.submitted.text()]
        if not self.projection.isHidden():
            lines.append(self.projection.text())
        if self.last_checked.text():
            lines.append(self.last_checked.text())
        self.setAccessibleName(" ".join(lines))
