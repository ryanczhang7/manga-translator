"""Run progress, driven by `RunEvent`s and nothing else (MT-018).

`components.md` §8 `RunProgressPanel` and `PageStageStepper`, and §9
`ErrorBanner` for the budget abort. The panel is fed the run's typed events
(`architecture.md` §6) through `on_event` and never calls into the pipeline,
the translator or the store; the one name it takes from `pipeline` is the abort
reason `BUDGET`, imported so it cannot drift from the runner's spelling.

**Pages are 0-based ordinals** (`domain/page.py`) and shown 1-based. A page is
*completed* when, after its `PageStarted`, the next `PageStarted`, `PageSkipped`
or `RunFinished` arrives; a skipped page ran nothing and is not a rate sample.

**Time comes from the events, not a clock.** Elapsed is the sum of every
`StageFinished.elapsed_ms`. The remaining time appears only from
`MIN_PAGES_FOR_ETA` completed pages on - two pages is not a rate, and the first
carries the warm-up - and is `(completed pages' ms // completed) * pages left`,
pages left being those neither completed nor skipped, the one in progress
included.

**A budget abort is a banner inside the panel, never a modal**: the user must
be able to go straight to reviewing what did complete. It has one action,
"Review pages 1-N" (en dash); "Change budget…" waits for a budget setting to exist (A-2).
Its accessible role is `Alert` (§9), given through an accessibility factory
because a `QFrame` has no way to declare a role of its own.

Every colour and type size comes from the application stylesheet by object
name and dynamic property (MT-061's rule); spacing comes from the tokens.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent, QAccessibleInterface
from PySide6.QtWidgets import (
    QAccessibleWidget,
    QFrame,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mangatl.domain.budget import DEFAULT_CEILING
from mangatl.domain.events import (
    PageSkipped,
    PageStarted,
    RunAborted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.domain.money import Usd
from mangatl.pipeline.runner import BUDGET
from mangatl.ui import tokens_gen
from mangatl.ui.cost_estimate import format_usd
from mangatl.ui.cost_readout import CostReadout
from mangatl.ui.labels import plain_label

__all__ = [
    "ESTIMATING",
    "MIN_PAGES_FOR_ETA",
    "STAGE_STEPS",
    "ErrorBanner",
    "PageStageStepper",
    "RunProgressPanel",
    "StepState",
    "format_duration",
]

#: §8: a remaining time from fewer completed pages than this is confidently wrong.
MIN_PAGES_FOR_ETA: int = 3
#: §8: the four labelled steps of the current page, in order.
STAGE_STEPS: tuple[str, ...] = ("Detecting", "Reading", "Translating", "Done")

StepState = Literal["pending", "active", "done"]

#: The stage names the pipeline reports (`detect_stage.py`, `ocr_stage.py`,
#: `translate_stage.py`), each finishing the step at its index. Spelled here
#: because the panel may not import the stages; a test pins that they agree.
_STAGE_INDEX: dict[str, int] = {"detect": 0, "ocr": 1, "translate": 2}

ESTIMATING = "Remaining estimating\N{HORIZONTAL ELLIPSIS}"
_STEP_MARK: dict[StepState, str] = {
    "pending": "",
    "active": "\N{BLACK RIGHT-POINTING SMALL TRIANGLE} ",
    "done": "\N{CHECK MARK} ",
}


def format_duration(ms: int) -> str:
    """`m:ss`, truncated to whole seconds; minutes are not folded into hours."""
    seconds = ms // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


class PageStageStepper(QWidget):
    """Four labelled steps for the current page - not one spinner."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stage-stepper")
        self._states: list[StepState] = ["pending"] * len(STAGE_STEPS)
        self._labels = [plain_label("stage-step", step) for step in STAGE_STEPS]
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens_gen.SPACE_S3)
        for label in self._labels:
            label.setWordWrap(False)
            row.addWidget(label)
        row.addStretch(1)
        self._render()

    def step_states(self) -> tuple[StepState, ...]:
        """One state per `STAGE_STEPS` entry, in order."""
        return tuple(self._states)

    def start(self) -> None:
        """A page has started: Detecting is active, the rest pending."""
        self._states = ["pending"] * len(STAGE_STEPS)
        self._states[0] = "active"
        self._render()

    def finish(self, stage: str) -> None:
        """`stage` finished: its step is done and the next is active - or, after
        the last stage, done. A stage the stepper does not know changes nothing."""
        index = _STAGE_INDEX.get(stage)
        if index is None:
            return
        self._states[index] = "done"
        following = index + 1
        self._states[following] = "done" if following == len(STAGE_STEPS) - 1 else "active"
        self._render()

    def _render(self) -> None:
        for label, step, state in zip(self._labels, STAGE_STEPS, self._states, strict=True):
            label.setText(f"{_STEP_MARK[state]}{step}")
            label.setAccessibleName(f"{step}: {state}")
            label.setProperty("stepState", state)
            label.style().unpolish(label)
            label.style().polish(label)


def _alert_factory(key: str, obj: QObject) -> QAccessibleInterface | None:
    """Give every `ErrorBanner` the `Alert` role (§9)."""
    if isinstance(obj, ErrorBanner):
        return QAccessibleWidget(obj, QAccessible.Role.AlertMessage)
    return None


_factory_installed = False


class ErrorBanner(QFrame):
    """A full-width banner in the flow of the window, never a dialog (§9)."""

    def __init__(
        self,
        headline: str,
        body: str,
        actions: tuple[str, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        global _factory_installed
        if not _factory_installed:
            QAccessible.installFactory(_alert_factory)
            _factory_installed = True
        super().__init__(parent)
        self.setObjectName("error-banner")
        self.glyph = plain_label("banner-glyph", "\N{WARNING SIGN}")
        self.glyph.setWordWrap(False)
        self.headline = plain_label("banner-headline", headline)
        self.body = plain_label("banner-body", body)
        # The contract names this `actions`, a tuple in display order, and the
        # tests read it so; it shadows `QWidget.actions()` (the QAction list),
        # which nothing in this app calls on a banner and Qt never calls from Python.
        self.actions: tuple[QPushButton, ...] = tuple(  # type: ignore[assignment]
            QPushButton(text) for text in actions
        )
        self.setAccessibleName(f"{headline} {body}")

        text = QVBoxLayout()
        text.setSpacing(tokens_gen.SPACE_S1)
        text.addWidget(self.headline)
        text.addWidget(self.body)
        if self.actions:
            buttons = QHBoxLayout()
            buttons.setSpacing(tokens_gen.SPACE_S2)
            for button in self.actions:
                buttons.addWidget(button)
            buttons.addStretch(1)
            text.addLayout(buttons)

        row = QHBoxLayout(self)
        pad = tokens_gen.SPACE_S3
        row.setContentsMargins(pad, pad, pad, pad)
        row.setSpacing(tokens_gen.SPACE_S2)
        row.addWidget(self.glyph)
        row.addLayout(text, 1)

    def announce(self) -> None:
        """Post the banner once to assistive technology, as an Alert (§9)."""
        QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.Alert))


class RunProgressPanel(QWidget):
    """A run's progress, cost and - on a budget abort - what survived."""

    #: The count N of kept pages, pages 1..N, when the user asks to review them.
    review_requested = Signal(int)

    def __init__(self, ceiling: Usd = DEFAULT_CEILING, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("run-progress")
        self._ceiling = ceiling
        self._page_count = 0
        self._current: int | None = None
        self._current_ms = 0
        self._completed = 0
        self._completed_ms = 0
        self._skipped = 0
        self._elapsed_ms = 0
        self.banner: ErrorBanner | None = None

        self.overall = QProgressBar()
        self.overall.setObjectName("run-overall")
        self.overall.setRange(0, 1)
        self.overall.setValue(0)
        self.overall.setTextVisible(False)
        self.overall_label = plain_label("run-overall-label", "")
        self.stepper = PageStageStepper()
        self.elapsed_label = plain_label("run-elapsed", "")
        self.remaining_label = plain_label("run-remaining", "")
        self.cost_readout = CostReadout()

        times = QHBoxLayout()
        times.setSpacing(tokens_gen.SPACE_S4)
        times.addWidget(self.elapsed_label)
        times.addWidget(self.remaining_label)
        times.addStretch(1)

        self._column = QVBoxLayout(self)
        pad = tokens_gen.SPACE_S4
        self._column.setContentsMargins(pad, pad, pad, pad)
        self._column.setSpacing(tokens_gen.SPACE_S3)
        self._column.addWidget(self.overall_label)
        self._column.addWidget(self.overall)
        self._column.addWidget(self.stepper)
        self._column.addLayout(times)
        self._column.addWidget(self.cost_readout)
        self._column.addStretch(1)
        self._show_times()

    def on_event(self, event: RunEvent) -> None:
        """Advance the panel by one event of the run."""
        if isinstance(event, RunStarted):
            self._start(event.page_count)
        elif isinstance(event, PageStarted):
            self._complete_current()
            self._current = event.ordinal
            self.overall.setValue(event.ordinal)
            self.overall_label.setText(f"Page {event.ordinal + 1} of {self._page_count}")
            self.stepper.start()
        elif isinstance(event, StageFinished):
            self._elapsed_ms += event.elapsed_ms
            self._current_ms += event.elapsed_ms
            self.stepper.finish(event.stage)
        elif isinstance(event, PageSkipped):
            self._complete_current()
            self._skipped += 1
        elif isinstance(event, RunFinished):
            self._complete_current()
            self.overall.setValue(self._page_count)
        elif event.reason == BUDGET:
            self._budget_abort(event)
        self._show_times()

    def _start(self, page_count: int) -> None:
        self._page_count = page_count
        self._current = None
        self._current_ms = self._completed = self._completed_ms = 0
        self._skipped = self._elapsed_ms = 0
        self.overall.setRange(0, page_count)
        self.overall.setValue(0)
        self.overall_label.setText(f"{page_count} pages")

    def _complete_current(self) -> None:
        if self._current is None:
            return
        self._completed += 1
        self._completed_ms += self._current_ms
        self._current = None
        self._current_ms = 0

    def _show_times(self) -> None:
        self.elapsed_label.setText(f"Elapsed {format_duration(self._elapsed_ms)}")
        if self._completed < MIN_PAGES_FOR_ETA:
            self.remaining_label.setText(ESTIMATING)
            return
        left = max(self._page_count - self._completed - self._skipped, 0)
        remaining = (self._completed_ms // self._completed) * left
        self.remaining_label.setText(f"Remaining about {format_duration(remaining)}")

    def _budget_abort(self, event: RunAborted) -> None:
        # The refused page is `ordinal`; every page before it was kept.
        kept = event.ordinal if event.ordinal is not None else self._completed + self._skipped
        headline = (
            f"Run stopped at page {kept + 1} of {self._page_count} \N{EM DASH} "
            f"the {format_usd(self._ceiling)} budget was reached."
        )
        if kept:
            body = f"Pages 1\N{EN DASH}{kept} are translated and can be reviewed and rendered."
            actions: tuple[str, ...] = (f"Review pages 1\N{EN DASH}{kept}",)
        else:
            body, actions = "No pages were translated.", ()
        banner = ErrorBanner(headline, body, actions, self)
        for button in banner.actions:
            button.clicked.connect(lambda: self.review_requested.emit(kept))
        self._column.insertWidget(0, banner)
        banner.show()
        self.banner = banner
        banner.announce()
        self.cost_readout.mark_aborted()
