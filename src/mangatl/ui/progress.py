"""Run progress, driven by `RunEvent`s and nothing else (MT-018).

`components.md` §8 `RunProgressPanel` and `PageStageStepper`, and §9
`ErrorBanner` for the budget abort. The panel is fed the run's typed events
(`architecture.md` §6) through `on_event` and never calls into the pipeline,
the translator or the store; the only names it takes from `pipeline` are the
abort reasons `BUDGET` and `CANCELLED` and the pass names `READING` and
`TRANSLATING`, imported so they cannot drift from the runner's spelling.

**A two-pass run** (MT-139) announces each pass with `PassStarted`: the label
names the pass (`Reading page n of m`, `Translating page n of m`), and the bar,
the stepper and the estimate's counters start again for each pass - the passes
run at different rates - while elapsed stays the run's. A reading-pass abort
has translated nothing; a chapter-step abort stops the run "before page 1".
Each page's last regions are kept and shown again when it starts translating.
A run with no `PassStarted` reads exactly as before.

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

**Any other abort but a cancel is the failed state** (MT-059 C-5, D-3): the
same banner, naming the page that failed and holding the runner's reason
verbatim, and the cost readout left exactly as it was. A cancel - only ever
the window closing - shows nothing (D-4). Whenever a banner has an action, the
action takes focus and activates on Return and Enter as well as Space.

**The current page is shown when the panel is given the `Chapter`** (MT-062):
a `RunThumbnail` beside the stepper, fed the page image from the chapter's own
folder on `PageStarted` and its region outlines on a `RegionsDetected` for that
page. The `Chapter` is domain data; the panel still reads nothing from the store.

**A batch run's panel** (MT-113 C-5, `batch=True`) shows only the local stages
- three steps, `BATCH_STAGE_STEPS`, finishing OCR makes `Done` done - and an
abort under it never claims a page translated and offers no action (PO-6): no
page is translated until the batch is collected. A budget refusal names the
refused `CallPriced`'s projection and ceiling (AM-1), or the panel's own
ceiling when no `CallPriced` arrived; the readout is marked aborted as a
per-page budget stop marks it.

**The consistency pass** (MT-141 AC-4) runs after the last page. A
`RunAborted` with no ordinal that arrives once every page of the pass has
started or been skipped is that pass refused or failed - never a stop at a
page: its banner says the pass was not run, that every page survived
(`PASS_SURVIVED`), and offers `REVIEW_CHAPTER` for all `page_count` pages.
The waiting panel shows the same banner, through `pass_banner_text`.

Every colour and type size comes from the application stylesheet by object
name and dynamic property (MT-061's rule); spacing comes from the tokens.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QObject, Qt, Signal
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
    CallPriced,
    PageSkipped,
    PageStarted,
    PassStarted,
    RegionsDetected,
    RunAborted,
    RunEvent,
    RunFinished,
    RunStarted,
    StageFinished,
)
from mangatl.domain.money import Usd
from mangatl.domain.page import Chapter
from mangatl.pipeline.runner import BUDGET, CANCELLED, READING, TRANSLATING
from mangatl.ui import tokens_gen
from mangatl.ui.buttons import ActivatedByEnter
from mangatl.ui.cost_estimate import format_usd
from mangatl.ui.cost_readout import CostReadout
from mangatl.ui.labels import plain_label
from mangatl.ui.run_thumbnail import RunThumbnail

__all__ = [
    "BATCH_STAGE_STEPS",
    "ESTIMATING",
    "MIN_PAGES_FOR_ETA",
    "PASS_SURVIVED",
    "REVIEW_CHAPTER",
    "STAGE_STEPS",
    "ErrorBanner",
    "PageStageStepper",
    "RunProgressPanel",
    "StepState",
    "format_duration",
    "pass_banner_text",
]

#: §8: a remaining time from fewer completed pages than this is confidently wrong.
MIN_PAGES_FOR_ETA: int = 3
#: §8: the four labelled steps of the current page, in order.
STAGE_STEPS: tuple[str, ...] = ("Detecting", "Reading", "Translating", "Done")
#: MT-113 C-5: a batch run's local stages - no page is translated before Done.
BATCH_STAGE_STEPS: tuple[str, ...] = ("Detecting", "Reading", "Done")

StepState = Literal["pending", "active", "done"]

#: The stage names the pipeline reports (`detect_stage.py`, `ocr_stage.py`,
#: `translate_stage.py`), each finishing the step at its index. Spelled here
#: because the panel may not import the stages; a test pins that they agree.
_STAGE_INDEX: dict[str, int] = {"detect": 0, "ocr": 1, "translate": 2}

ESTIMATING = "Remaining estimating\N{HORIZONTAL ELLIPSIS}"

#: MT-141 D-3: the consistency-pass banner's body and its one action, shared
#: with the waiting panel so the two banners cannot drift.
PASS_SURVIVED = "Every page is translated and can be reviewed and rendered."
REVIEW_CHAPTER = "Review the chapter"


def pass_banner_text(reason: str) -> tuple[str, str]:
    """The consistency-pass banner's headline and body for an abort `reason`
    other than a cancel (MT-141 D-3): a refusal says the pass was not run, any
    other reason leads the body on its own line."""
    if reason == BUDGET:
        return "Consistency pass not run \N{EM DASH} the budget would be exceeded.", PASS_SURVIVED
    return "Consistency pass failed.", f"{reason}\n{PASS_SURVIVED}"


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
    """Labelled steps for the current page - not one spinner. `steps` is
    `STAGE_STEPS`, or `BATCH_STAGE_STEPS` for a batch run (MT-113 C-5)."""

    def __init__(
        self, parent: QWidget | None = None, *, steps: tuple[str, ...] = STAGE_STEPS
    ) -> None:
        super().__init__(parent)
        self.setObjectName("stage-stepper")
        self._steps = steps
        self._states: list[StepState] = ["pending"] * len(steps)
        self._labels = [plain_label("stage-step", step) for step in steps]
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens_gen.SPACE_S3)
        for label in self._labels:
            label.setWordWrap(False)
            row.addWidget(label)
        row.addStretch(1)
        self._render()

    def step_states(self) -> tuple[StepState, ...]:
        """One state per step, in order."""
        return tuple(self._states)

    def start(self, *, active: int = 0) -> None:
        """A page has started: steps before `active` are done, `active` is
        active, the rest pending. The translating pass starts at 2 - Detecting
        and Reading were done for this page in the reading pass (MT-139)."""
        self._states = ["pending"] * len(self._steps)
        for index in range(active):
            self._states[index] = "done"
        self._states[active] = "active"
        self._render()

    def reset(self) -> None:
        """Every step pending: between passes, before the next page starts."""
        self._states = ["pending"] * len(self._steps)
        self._render()

    def finish(self, stage: str) -> None:
        """`stage` finished: its step is done and the next is active - or, after
        the last stage, done. A stage the stepper does not know changes nothing."""
        index = _STAGE_INDEX.get(stage)
        last = len(self._steps) - 1
        if index is None:
            return
        self._states[index] = "done"
        following = index + 1
        self._states[following] = "done" if following == last else "active"
        self._render()

    def _render(self) -> None:
        for label, step, state in zip(self._labels, self._steps, self._states, strict=True):
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
            ActivatedByEnter(text) for text in actions
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

    def __init__(
        self,
        ceiling: Usd = DEFAULT_CEILING,
        parent: QWidget | None = None,
        *,
        chapter: Chapter | None = None,
        batch: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("run-progress")
        self._ceiling = ceiling
        self._chapter = chapter
        #: A batch run's panel (MT-113 C-5): its steps and its aborts differ.
        self._batch = batch
        #: The last `CallPriced`: a batch budget refusal names its figures (AM-1).
        self._priced: CallPriced | None = None
        #: The ordinal of the last `PageStarted`: the page the thumbnail shows.
        self._shown: int | None = None
        self._page_count = 0
        self._current: int | None = None
        self._current_ms = 0
        self._completed = 0
        self._completed_ms = 0
        self._skipped = 0
        self._elapsed_ms = 0
        #: The pass in progress (MT-139): `READING`, `TRANSLATING`, or `None`
        #: for a single-pass run, which reads exactly as before.
        self._pass: str | None = None
        #: Each page's last `RegionsDetected`, re-applied when the page starts
        #: in the translating pass (AC-9, PO-7).
        self._regions: dict[int, tuple[tuple[tuple[int, int], ...], ...]] = {}
        self.banner: ErrorBanner | None = None

        self.overall = QProgressBar()
        self.overall.setObjectName("run-overall")
        self.overall.setRange(0, 1)
        self.overall.setValue(0)
        self.overall.setTextVisible(False)
        self.overall_label = plain_label("run-overall-label", "")
        self.stepper = PageStageStepper(steps=BATCH_STAGE_STEPS if batch else STAGE_STEPS)
        #: The current page and its markers (MT-062); `None` without a chapter,
        #: which has no page images to show.
        self.thumbnail: RunThumbnail | None = None if chapter is None else RunThumbnail()
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
        current_page = QHBoxLayout()
        current_page.setObjectName("run-current-page")
        current_page.setSpacing(tokens_gen.SPACE_S4)
        if self.thumbnail is not None:
            current_page.addWidget(self.thumbnail)
        current_page.addWidget(self.stepper, 0, Qt.AlignmentFlag.AlignTop)
        self._column.addLayout(current_page)
        self._column.addLayout(times)
        self._column.addWidget(self.cost_readout)
        self._column.addStretch(1)
        self._show_times()

    def on_event(self, event: RunEvent) -> None:
        """Advance the panel by one event of the run."""
        if isinstance(event, RunStarted):
            self._start(event.page_count)
        elif isinstance(event, PassStarted):
            # Before the `RunAborted` fall-through below, which reads `reason`.
            self._pass = event.name
            self._reset_pass()
            self.overall_label.setText(
                "Reading pages" if event.name == READING else "Translating pages"
            )
        elif isinstance(event, PageStarted):
            self._complete_current()
            self._current = event.ordinal
            self.overall.setValue(event.ordinal)
            self.overall_label.setText(self._page_label(event.ordinal))
            self.stepper.start(active=2 if self._pass == TRANSLATING else 0)
            self._show_page(event.ordinal)
            regions = self._regions.get(event.ordinal)
            if self.thumbnail is not None and regions is not None:
                self.thumbnail.set_regions(regions)
        elif isinstance(event, RegionsDetected):
            # Before the `RunAborted` fall-through below, which reads `reason`.
            self._regions[event.ordinal] = event.polygons
            if self.thumbnail is not None and event.ordinal == self._shown:
                self.thumbnail.set_regions(event.polygons)
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
        elif isinstance(event, CallPriced):
            self._priced = event
            self.cost_readout.set_state(event.spent, event.ceiling, event.projection)
        elif isinstance(event, RunAborted):
            # Narrowed rather than a bare fall-through since MT-111 added
            # `BatchSubmitted` to the union; the batch events are the waiting
            # panel's (MT-113 C-4), so here they are inert.
            if self._batch:
                self._batch_abort(event)
            elif event.ordinal is None and self._after_every_page():
                self._pass_abort(event)
            elif event.reason == BUDGET:
                self._budget_abort(event)
            elif event.reason != CANCELLED:
                self._failed(event)
        self._show_times()

    def _show_page(self, ordinal: int) -> None:
        """The thumbnail shows page `ordinal`, read from the chapter's own folder."""
        if self._chapter is None or self.thumbnail is None:
            return
        page = next(page for page in self._chapter.pages if page.ordinal == ordinal)
        self._shown = ordinal
        self.thumbnail.show_page(
            ordinal, self._chapter.source_dir / page.filename, page.width, page.height
        )

    def _start(self, page_count: int) -> None:
        self._page_count = page_count
        self._current = None
        self._current_ms = self._completed = self._completed_ms = 0
        self._skipped = self._elapsed_ms = 0
        self._pass = None
        self._regions = {}
        self.overall.setRange(0, page_count)
        self.overall.setValue(0)
        self.overall_label.setText(f"{page_count} pages")

    def _reset_pass(self) -> None:
        """A pass begins (MT-139): the bar, the stepper and the counters the
        estimate reads start again; elapsed, the regions and the cost do not."""
        self._current = None
        self._current_ms = self._completed = self._completed_ms = 0
        self._skipped = 0
        self.overall.setValue(0)
        self.stepper.reset()

    def _page_label(self, ordinal: int) -> str:
        page = f"page {ordinal + 1} of {self._page_count}"
        if self._pass == READING:
            return f"Reading {page}"
        if self._pass == TRANSLATING:
            return f"Translating {page}"
        return f"Page {ordinal + 1} of {self._page_count}"

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

    def _kept(self, event: RunAborted) -> int:
        # A reading-pass abort has translated nothing this run (MT-139 PO-5).
        if self._pass == READING:
            return 0
        # The stopped page is `ordinal`; every page before it was kept.
        return event.ordinal if event.ordinal is not None else self._completed + self._skipped

    def _stopped_at(self, event: RunAborted, kept: int) -> str:
        """The headline's position: the page the run stopped at, or - when the
        chapter step stopped a two-pass run (no ordinal) - before page 1."""
        if event.ordinal is None and self._pass == TRANSLATING:
            return f"Run stopped before page 1 of {self._page_count}"
        page = event.ordinal if event.ordinal is not None else kept
        return f"Run stopped at page {page + 1} of {self._page_count}"

    def _budget_abort(self, event: RunAborted) -> None:
        kept = self._kept(event)
        headline = (
            f"{self._stopped_at(event, kept)} \N{EM DASH} "
            f"the {format_usd(self._ceiling)} budget was reached."
        )
        self._show_banner(headline, "", kept)
        self.cost_readout.mark_aborted()

    def _failed(self, event: RunAborted) -> None:
        """D-3: the runner's reason verbatim; the cost readout is not touched -
        `aborted` means the budget was reached and nothing else. The page is
        the event's `ordinal` when it has one; a chapter step that failed a
        two-pass run is "the glossary step" (MT-139 PO-6)."""
        kept = self._kept(event)
        if event.ordinal is None and self._pass == TRANSLATING:
            what = "the glossary step failed."
        else:
            page = event.ordinal if event.ordinal is not None else kept
            what = f"page {page + 1} failed."
        headline = f"{self._stopped_at(event, kept)} \N{EM DASH} {what}"
        self._show_banner(headline, event.reason + "\n", kept)

    def _batch_abort(self, event: RunAborted) -> None:
        """MT-113 C-5: a batch abort never claims a page and offers nothing
        (PO-6). A cancel shows nothing, as a per-page one does (D-4)."""
        if event.reason == CANCELLED:
            return
        if event.reason == BUDGET:
            if self._priced is not None:
                projected = format_usd(self._priced.projection.next_call)
                ceiling = format_usd(self._priced.ceiling)
                headline = (
                    f"Batch not submitted \N{EM DASH} projected {projected} exceeds"
                    f" the {ceiling} budget."
                )
            else:
                headline = (
                    f"Batch not submitted \N{EM DASH} the {format_usd(self._ceiling)}"
                    " budget would be exceeded."
                )
            self._show_banner(headline, "", 0)
            self.cost_readout.mark_aborted()
            return
        if event.ordinal is not None:
            headline = f"Batch not submitted \N{EM DASH} page {event.ordinal + 1} failed."
        else:
            headline = "Batch not submitted."
        self._show_banner(headline, event.reason + "\n", 0)

    def _after_every_page(self) -> bool:
        """The run reached its postlude: every page of the pass in progress has
        started or been skipped. `_current` counts, because nothing but the next
        `PageStarted` or `RunFinished` completes the last page, and the postlude
        runs only once every page completed."""
        started = self._completed + self._skipped + (1 if self._current is not None else 0)
        return self._page_count > 0 and started == self._page_count

    def _pass_abort(self, event: RunAborted) -> None:
        """MT-141 AC-4: the consistency pass refused or failed after the last
        page. Every page survived; the readout is marked only for a refusal."""
        self._complete_current()  # the last page did complete
        if event.reason == CANCELLED:
            return
        headline, body = pass_banner_text(event.reason)
        self._put_banner(headline, body, (REVIEW_CHAPTER,), self._page_count)
        if event.reason == BUDGET:
            self.cost_readout.mark_aborted()

    def _show_banner(self, headline: str, lead: str, kept: int) -> None:
        """The banner at the top of the panel: `lead`, then what survived, and
        - when a page did - the one action, which takes focus (D-3). A batch
        abort passes `kept=0`: nothing survived it as a translation."""
        if kept:
            body = f"Pages 1\N{EN DASH}{kept} are translated and can be reviewed and rendered."
            actions: tuple[str, ...] = (f"Review pages 1\N{EN DASH}{kept}",)
        else:
            body, actions = "No pages were translated.", ()
        self._put_banner(headline, lead + body, actions, kept)

    def _put_banner(self, headline: str, body: str, actions: tuple[str, ...], kept: int) -> None:
        """Insert, announce and focus the banner; its action asks to review
        pages 1..`kept`."""
        banner = ErrorBanner(headline, body, actions, self)
        for button in banner.actions:
            button.clicked.connect(lambda: self.review_requested.emit(kept))
        self._column.insertWidget(0, banner)
        banner.show()
        self.banner = banner
        banner.announce()
        if banner.actions:
            banner.actions[0].setFocus(Qt.FocusReason.OtherFocusReason)
