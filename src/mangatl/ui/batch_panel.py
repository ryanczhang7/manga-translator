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

**The consistency pass** (MT-141) runs in the poll that collects the last job:
once every job of the state is `BatchCollected` the `batch-pass` line says so
(`CHECKING`); a `RunAborted` other than a cancel - the pass refused or failed -
clears it and shows the run panel's pass banner, whose action emits
`review_requested`.

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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from mangatl.domain.batch import BatchJob
from mangatl.domain.events import BatchCollected, BatchFailed, BatchWaiting, RunAborted, RunEvent
from mangatl.pipeline.runner import CANCELLED
from mangatl.ui import tokens_gen
from mangatl.ui.cost_estimate import format_usd
from mangatl.ui.labels import plain_label
from mangatl.ui.progress import REVIEW_CHAPTER, ErrorBanner, pass_banner_text
from mangatl.ui.run import WaitingState

__all__ = ["CHECKING", "BatchWaitingPanel", "PendingBatch"]

#: MT-141 D-4: the waiting panel's line while the consistency pass runs.
CHECKING = "Checking the chapter for consistency\N{HORIZONTAL ELLIPSIS}"


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

    #: The pass banner's one action was activated: open the review (MT-141 AC-5).
    review_requested = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, now: Callable[[], datetime] = _local_now
    ) -> None:
        super().__init__(parent)
        self.setObjectName("batch-waiting")
        self._now = now
        self.submitted = plain_label("batch-submitted", "")
        self.projection = plain_label("batch-projection", "")
        self.last_checked = plain_label("batch-last-checked", "")
        self.pass_line = plain_label("batch-pass", "")
        self.pass_line.hide()
        self.banner: ErrorBanner | None = None
        self._job_count = 0
        self._collected = 0

        self._column = QVBoxLayout(self)
        pad = tokens_gen.SPACE_S4
        self._column.setContentsMargins(pad, pad, pad, pad)
        self._column.setSpacing(tokens_gen.SPACE_S3)
        self._column.addWidget(self.submitted)
        self._column.addWidget(self.projection)
        self._column.addWidget(self.last_checked)
        self._column.addWidget(self.pass_line)
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
        self._job_count = state.job_count
        self._collected = 0
        self._name()

    def on_event(self, event: RunEvent) -> None:
        """A poll's event: a job still waiting sets the time it was asked; a
        failed job shows the banner. The last job collected shows the pass
        line (MT-141 AC-3); the pass refused or failed replaces it with the
        pass banner (AC-5). Every other event changes nothing."""
        if isinstance(event, BatchWaiting):
            self.last_checked.setText(f"Last checked {_hhmm(self._now())}.")
            self._name()
        elif isinstance(event, BatchFailed):
            self._failed(event.state)
        elif isinstance(event, BatchCollected):
            self._collected += 1
            if self._collected >= self._job_count:
                self.pass_line.setText(CHECKING)
                self.pass_line.show()
                self._name()
        elif isinstance(event, RunAborted) and event.reason != CANCELLED:
            self.pass_line.setText("")
            self.pass_line.hide()
            self._pass_not_run(event.reason)
            self._name()

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

    def _pass_not_run(self, reason: str) -> None:
        """The run panel's consistency-pass banner (MT-141 D-3); its action
        asks for the review, and takes focus."""
        headline, body = pass_banner_text(reason)
        banner = ErrorBanner(headline, body, (REVIEW_CHAPTER,), self)
        banner.actions[0].clicked.connect(self.review_requested.emit)
        self._column.insertWidget(0, banner)
        banner.show()
        self.banner = banner
        banner.announce()
        banner.actions[0].setFocus(Qt.FocusReason.OtherFocusReason)

    def _name(self) -> None:
        """The accessible name is the visible lines, in order (C-4), the pass
        line last (MT-141 AC-3)."""
        lines = [self.submitted.text()]
        if not self.projection.isHidden():
            lines.append(self.projection.text())
        if self.last_checked.text():
            lines.append(self.last_checked.text())
        if not self.pass_line.isHidden():
            lines.append(self.pass_line.text())
        self.setAccessibleName(" ".join(lines))
