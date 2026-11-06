"""MT-018: run progress is visible during a run, driven by `RunEvent`s alone.

`RunProgressPanel`, `PageStageStepper` and `ErrorBanner` (new,
`mangatl.ui.progress`) are `components.md` §8. The panel is fed synthetic
event sequences - `mangatl.domain.events` dataclasses, built here by hand - so
nothing in this file needs a GPU, an API key or a clock (`architecture.md` §6).

Oracle partition (story `## Contract`):

- **Mechanical, pinned exactly:** AC-1 (the overall bar and "Page 7 of 20"),
  AC-2 (the stepper's state per stage event, using the real stage names read
  from the stage classes), AC-4 in **both** halves - "Remaining estimating…"
  with no digit after 0, 1 and 2 completed pages, and the exact
  "Remaining about m:ss" from the contract formula at the third - plus the
  completed-page definition (a `PageSkipped` page is not a completion) and
  `format_duration`.
- **Settled, read out of §8:** AC-8's banner - not a modal, the exact copy,
  exactly one action and **no** "Change budget…" (A-2). The abort reason is
  `pipeline.runner.BUDGET`, imported rather than re-spelled.

The AC-4 numbers are chosen so the contract's order of operations is visible:
three pages totalling 38,648 ms leave 17 pages, and `(38_648 // 3) * 17` is
218,994 ms ("3:38") while `38_648 * 17 // 3` is 219,005 ms ("3:39").

**RED:** fails at import (`mangatl.ui.progress` does not exist), so no
assertion here has run yet. No real-time waits anywhere.
"""

from __future__ import annotations

import ast
import re
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtGui import QAccessible, QColor, QImage
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDialog,
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
)

import mangatl.ui.progress as progress_module
from mangatl.domain.budget import DEFAULT_CEILING, Projection
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
from mangatl.domain.page import Chapter, Page
from mangatl.pipeline.detect_stage import DetectStage
from mangatl.pipeline.ocr_stage import OcrStage
from mangatl.pipeline.runner import BUDGET, CANCELLED, READING, TRANSLATING
from mangatl.pipeline.translate_stage import TranslateStage
from mangatl.ui.cost_readout import CostReadout
from mangatl.ui.progress import (
    MIN_PAGES_FOR_ETA,
    STAGE_STEPS,
    ErrorBanner,
    PageStageStepper,
    RunProgressPanel,
    format_duration,
)

# --- The real stage names, read from the stages that emit them -------------------
DETECT = DetectStage.name
OCR = OcrStage.name
TRANSLATE = TranslateStage.name

ESTIMATING = "Remaining estimating\N{HORIZONTAL ELLIPSIS}"  # U+2026, the single-character ellipsis
EN = "\N{EN DASH}"  # en dash, "pages 1-13" in the design copy
EM = "\N{EM DASH}"  # em dash

PENDING, ACTIVE, DONE = "pending", "active", "done"


def _panel(qtbot, **kwargs) -> RunProgressPanel:  # type: ignore[no-untyped-def]
    panel = RunProgressPanel(**kwargs)
    qtbot.addWidget(panel)
    panel.show()
    return panel


def _feed(panel: RunProgressPanel, *events: RunEvent) -> None:
    for event in events:
        panel.on_event(event)


def _page(ordinal: int, detect: int, ocr: int, translate: int) -> list[RunEvent]:
    """One page, start to its last stage. Its completion is the NEXT event."""
    return [
        PageStarted(ordinal=ordinal),
        StageFinished(ordinal=ordinal, stage=DETECT, elapsed_ms=detect),
        StageFinished(ordinal=ordinal, stage=OCR, elapsed_ms=ocr),
        StageFinished(ordinal=ordinal, stage=TRANSLATE, elapsed_ms=translate),
    ]


# =============================================================================
# The settled constants and the export shape
# =============================================================================


def test_the_eta_waits_for_three_completed_pages() -> None:
    assert MIN_PAGES_FOR_ETA == 3


def test_the_stepper_has_the_four_steps_components_md_names_in_order() -> None:
    assert STAGE_STEPS == ("Detecting", "Reading", "Translating", "Done")


def test_the_stage_names_the_stepper_listens_for_are_the_real_ones() -> None:
    """The contract spells them; the stages define them. If a stage is renamed the
    stepper stops advancing silently, so pin that they still agree."""
    assert (DETECT, OCR, TRANSLATE) == ("detect", "ocr", "translate")


def test_the_panel_exposes_the_widgets_the_contract_names(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)

    assert isinstance(panel.overall, QProgressBar)
    assert isinstance(panel.overall_label, QLabel)
    assert isinstance(panel.stepper, PageStageStepper)
    assert isinstance(panel.elapsed_label, QLabel)
    assert isinstance(panel.remaining_label, QLabel)
    assert isinstance(panel.cost_readout, CostReadout)
    assert panel.banner is None


# =============================================================================
# format_duration: "m:ss", truncated to whole seconds
# =============================================================================


@pytest.mark.parametrize(
    ("ms", "text"),
    [
        (0, "0:00"),
        (999, "0:00"),
        (1_000, "0:01"),
        (5_000, "0:05"),
        (59_999, "0:59"),
        (60_000, "1:00"),
        (83_000, "1:23"),
        (83_999, "1:23"),
        (218_994, "3:38"),
        (3_599_999, "59:59"),
        (3_600_000, "60:00"),
    ],
)
def test_a_duration_reads_minutes_and_two_digit_seconds_truncated(ms: int, text: str) -> None:
    assert format_duration(ms) == text


# =============================================================================
# AC-1: a determinate overall bar reading "Page 7 of 20"
# =============================================================================


def test_page_started_6_of_a_20_page_run_reads_page_7_of_20_on_a_determinate_bar(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    panel = _panel(qtbot)

    _feed(panel, RunStarted(run_id=1, page_count=20), PageStarted(ordinal=6))

    assert panel.overall_label.text() == "Page 7 of 20"
    assert (panel.overall.minimum(), panel.overall.maximum()) == (0, 20), (
        "the overall bar is not determinate over 0..20 (0..0 is Qt's busy indicator)"
    )
    assert panel.overall.value() == 6


def test_the_first_page_reads_page_1_not_page_0(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)

    _feed(panel, RunStarted(run_id=1, page_count=20), PageStarted(ordinal=0))

    assert panel.overall_label.text() == "Page 1 of 20"
    assert panel.overall.value() == 0


def test_the_bar_follows_each_page_and_is_full_when_the_run_finishes(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=3, page_count=3))

    for ordinal in range(3):
        _feed(panel, *_page(ordinal, 100, 100, 100))
        assert panel.overall_label.text() == f"Page {ordinal + 1} of 3"
        assert panel.overall.value() == ordinal

    _feed(panel, RunFinished(run_id=3, pages_done=3))
    assert panel.overall.value() == 3 == panel.overall.maximum()


# =============================================================================
# AC-2: the stepper advances Detecting -> Reading -> Translating -> Done
# =============================================================================


def test_the_stepper_advances_one_step_per_stage_event(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=20))

    _feed(panel, PageStarted(ordinal=6))
    assert panel.stepper.step_states() == (ACTIVE, PENDING, PENDING, PENDING)

    _feed(panel, StageFinished(ordinal=6, stage=DETECT, elapsed_ms=1_200))
    assert panel.stepper.step_states() == (DONE, ACTIVE, PENDING, PENDING)

    _feed(panel, StageFinished(ordinal=6, stage=OCR, elapsed_ms=800))
    assert panel.stepper.step_states() == (DONE, DONE, ACTIVE, PENDING)

    _feed(panel, StageFinished(ordinal=6, stage=TRANSLATE, elapsed_ms=9_000))
    assert panel.stepper.step_states() == (DONE, DONE, DONE, DONE)


def test_the_next_page_starts_the_stepper_over(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=20), *_page(0, 1, 1, 1))
    assert panel.stepper.step_states() == (DONE, DONE, DONE, DONE)

    _feed(panel, PageStarted(ordinal=1))

    assert panel.stepper.step_states() == (ACTIVE, PENDING, PENDING, PENDING)


def test_a_stage_the_stepper_does_not_know_changes_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=20),
        PageStarted(ordinal=0),
        StageFinished(ordinal=0, stage=DETECT, elapsed_ms=10),
    )
    before = panel.stepper.step_states()

    _feed(panel, StageFinished(ordinal=0, stage="clean", elapsed_ms=10))

    assert panel.stepper.step_states() == before == (DONE, ACTIVE, PENDING, PENDING)


def test_the_stepper_has_one_state_per_step_and_labels_each_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=20), PageStarted(ordinal=0))

    assert len(panel.stepper.step_states()) == len(STAGE_STEPS)
    texts = [label.text() for label in panel.stepper.findChildren(QLabel)]
    for step in STAGE_STEPS:
        assert any(step in text for text in texts), f"no label in the stepper reads {step!r}"


# =============================================================================
# AC-4: no remaining time before three completed pages; then exactly the formula
# =============================================================================


def _assert_estimating(panel: RunProgressPanel, when: str) -> None:
    text = panel.remaining_label.text()
    assert text == ESTIMATING, f"{when}: remaining reads {text!r}, not {ESTIMATING!r}"
    assert not re.search(r"\d", text), f"{when}: a remaining time was shown: {text!r}"


def test_no_remaining_time_is_shown_after_zero_one_or_two_completed_pages(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-4, the absence half: checked after EVERY event before the third
    completion, including mid-page and with two pages complete."""
    panel = _panel(qtbot)
    events: list[RunEvent] = [
        RunStarted(run_id=1, page_count=20),
        *_page(0, 1_000, 2_000, 9_000),
        *_page(1, 4_000, 3_000, 5_000),
        *_page(2, 3_000, 2_648, 9_000),
    ]
    for index, event in enumerate(events):
        panel.on_event(event)
        _assert_estimating(panel, f"after event {index} ({event!r})")


def test_the_third_completed_page_shows_remaining_time_by_the_contract_formula(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-4, the presence half. Completed pages total 38,648 ms over 3; 17 pages
    are left; (38_648 // 3) * 17 = 218,994 ms -> "3:38"."""
    panel = _panel(qtbot)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=20),
        *_page(0, 1_000, 2_000, 9_000),
        *_page(1, 4_000, 3_000, 5_000),
        *_page(2, 3_000, 2_648, 9_000),
    )
    _assert_estimating(panel, "with page 3 still in progress")

    _feed(panel, PageStarted(ordinal=3))  # completes page index 2, the third

    assert panel.remaining_label.text() == "Remaining about 3:38"
    assert panel.elapsed_label.text() == "Elapsed 0:38"


def test_elapsed_is_the_sum_of_every_stage_duration_including_the_page_in_progress(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=20))
    assert panel.elapsed_label.text() == "Elapsed 0:00"

    _feed(panel, *_page(0, 30_000, 20_000, 33_000))
    assert panel.elapsed_label.text() == "Elapsed 1:23"

    _feed(panel, PageStarted(ordinal=1), StageFinished(ordinal=1, stage=DETECT, elapsed_ms=999))
    assert panel.elapsed_label.text() == "Elapsed 1:23", "elapsed must truncate, not round"

    _feed(panel, StageFinished(ordinal=1, stage=OCR, elapsed_ms=1))
    assert panel.elapsed_label.text() == "Elapsed 1:24"


def test_skipped_pages_are_not_completed_pages_and_do_not_start_the_estimate(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """A skipped page ran nothing, so it is not a rate sample."""
    panel = _panel(qtbot)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=5),
        PageSkipped(ordinal=0, reason="already done"),
        PageSkipped(ordinal=1, reason="already done"),
        PageSkipped(ordinal=2, reason="already done"),
        *_page(3, 1_000, 1_000, 1_000),
    )
    _assert_estimating(panel, "after three skipped pages and one in progress")

    _feed(panel, PageStarted(ordinal=4))  # one completed page, three skipped

    _assert_estimating(panel, "with one completed page and three skipped")


def test_a_skip_completes_the_page_before_it_and_shrinks_the_pages_left(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """Completion is signalled by the next PageStarted, PageSkipped or
    RunFinished. Pages 0 and 1 run (12 s each), page 2 is skipped - which
    completes page 1 - and page 3 runs 15 s, completed by PageStarted(4).
    Completed 3, skipped 1, P=20: (39_000 // 3) * (20 - 3 - 1) = 208,000 ms."""
    panel = _panel(qtbot)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=20),
        *_page(0, 2_000, 2_000, 8_000),
        PageStarted(ordinal=1),
    )
    _assert_estimating(panel, "with one completed page")
    _feed(
        panel,
        StageFinished(ordinal=1, stage=DETECT, elapsed_ms=2_000),
        StageFinished(ordinal=1, stage=OCR, elapsed_ms=2_000),
        StageFinished(ordinal=1, stage=TRANSLATE, elapsed_ms=8_000),
        PageSkipped(ordinal=2, reason="already done"),
        *_page(3, 3_000, 3_000, 9_000),
    )
    _assert_estimating(panel, "with two completed pages, one skipped, one in progress")

    _feed(panel, PageStarted(ordinal=4))

    assert panel.remaining_label.text() == "Remaining about 3:28"


def test_run_finished_completes_the_last_page_and_leaves_nothing_remaining(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    panel = _panel(qtbot)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=3),
        *_page(0, 1_000, 1_000, 1_000),
        *_page(1, 1_000, 1_000, 1_000),
        *_page(2, 1_000, 1_000, 1_000),
    )
    _assert_estimating(panel, "two completed, the last in progress")

    _feed(panel, RunFinished(run_id=1, pages_done=3))

    assert panel.remaining_label.text() == "Remaining about 0:00"


def test_the_remaining_time_keeps_updating_after_the_fourth_page(qtbot) -> None:  # type: ignore[no-untyped-def]
    """4 pages of 10 s each, P=10: (40_000 // 4) * 6 = 60,000 ms -> "1:00"."""
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=10))
    for ordinal in range(4):
        _feed(panel, *_page(ordinal, 2_000, 3_000, 5_000))
    _feed(panel, PageStarted(ordinal=4))

    assert panel.remaining_label.text() == "Remaining about 1:00"


# =============================================================================
# AC-5 in the panel: nothing drives the readout during a run yet (PO-2)
# =============================================================================


def test_the_panels_cost_readout_starts_unknown_and_shows_a_dash(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=20), PageStarted(ordinal=0))

    assert panel.cost_readout.state() == "unknown"
    assert panel.cost_readout.figure.text() == "$\N{EM DASH}"


# =============================================================================
# AC-8: a budget abort is an ErrorBanner, not a modal
# =============================================================================


def _abort_at(panel: RunProgressPanel, ordinal: int, page_count: int = 20) -> ErrorBanner:
    _feed(
        panel,
        RunStarted(run_id=1, page_count=page_count),
        PageStarted(ordinal=ordinal),
        RunAborted(reason=BUDGET, ordinal=ordinal),
    )
    banner = panel.banner
    assert isinstance(banner, ErrorBanner), f"no ErrorBanner after a budget abort: {banner!r}"
    return banner


def test_the_budget_abort_reason_is_the_runners_constant() -> None:
    assert BUDGET == "budget"


def test_a_budget_abort_shows_a_banner_inside_the_panel_not_a_modal(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)

    banner = _abort_at(panel, 13)

    assert isinstance(banner, QFrame)
    assert not isinstance(banner, QDialog), "the budget abort is a modal dialog"
    assert not banner.isWindow(), "the banner is a top-level window"
    assert panel.isAncestorOf(banner), "the banner is not inside the panel"
    assert banner.isVisibleTo(panel)
    assert QApplication.activeModalWidget() is None
    assert not [
        w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()
    ]


def test_the_banner_names_where_it_stopped_and_what_survived(qtbot) -> None:  # type: ignore[no-untyped-def]
    """§8's worked example, verbatim: stopped at page 14 of 20, pages 1 to 13 kept."""
    panel = _panel(qtbot)

    banner = _abort_at(panel, 13)

    assert banner.headline.text() == (
        f"Run stopped at page 14 of 20 {EM} the $2.00 budget was reached."
    )
    assert banner.body.text() == f"Pages 1{EN}13 are translated and can be reviewed and rendered."


def test_the_banner_offers_review_and_nothing_else(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A-2: no "Change budget…" until a budget setting exists - an action that
    does nothing is not an honest action."""
    panel = _panel(qtbot)

    banner = _abort_at(panel, 13)

    assert [button.text() for button in banner.actions] == [f"Review pages 1{EN}13"]
    assert all(isinstance(button, QPushButton) for button in banner.actions)
    buttons = [button.text() for button in banner.findChildren(QAbstractButton)]
    assert buttons == [f"Review pages 1{EN}13"], f"the banner has other buttons: {buttons}"
    texts = [label.text() for label in panel.findChildren(QLabel)] + buttons
    assert not any("Change budget" in text for text in texts)


def test_clicking_review_asks_to_review_the_kept_pages(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    banner = _abort_at(panel, 13)
    requested: list[int] = []
    panel.review_requested.connect(requested.append)

    banner.actions[0].click()

    assert requested == [13]


def test_the_banner_uses_the_ceiling_the_panel_was_given(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot, ceiling=Usd(Decimal("5.00")))

    banner = _abort_at(panel, 4, page_count=9)

    assert (
        banner.headline.text() == f"Run stopped at page 5 of 9 {EM} the $5.00 budget was reached."
    )
    assert [button.text() for button in banner.actions] == [f"Review pages 1{EN}4"]


def test_a_budget_abort_on_the_first_page_has_nothing_to_review(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)

    banner = _abort_at(panel, 0)

    assert banner.headline.text() == (
        f"Run stopped at page 1 of 20 {EM} the $2.00 budget was reached."
    )
    assert banner.body.text() == "No pages were translated."
    assert banner.actions == ()
    assert banner.findChildren(QAbstractButton) == []


def test_the_banner_is_an_alert_to_assistive_technology(qtbot) -> None:  # type: ignore[no-untyped-def]
    """§9 ErrorBanner: role Alert."""
    panel = _panel(qtbot)
    banner = _abort_at(panel, 13)

    interface = QAccessible.queryAccessibleInterface(banner)

    assert interface is not None
    assert interface.role() == QAccessible.Role.AlertMessage, f"role is {interface.role()!r}"


def test_a_budget_abort_puts_the_cost_readout_in_its_aborted_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)

    _abort_at(panel, 13)

    assert panel.cost_readout.state() == "aborted"


def test_a_cancelled_run_shows_no_banner(qtbot) -> None:  # type: ignore[no-untyped-def]
    """MT-059 D-4: a cancel (only ever a window close) shows nothing."""
    panel = _panel(qtbot)

    _feed(
        panel,
        RunStarted(run_id=1, page_count=20),
        PageStarted(ordinal=4),
        RunAborted(reason=CANCELLED, ordinal=None),
    )

    assert panel.banner is None
    assert panel.findChildren(ErrorBanner) == []


def test_a_failed_run_shows_the_failed_banner_not_the_budget_one(qtbot) -> None:  # type: ignore[no-untyped-def]
    """MT-059 C-5 rewrote this case, which MT-018 pinned as "no banner" because
    the failed state was MT-059's. It is now built (copy in
    `test_run_failed_state.py`); what stays from MT-018 is that it is not the
    budget banner and does not put the readout in the budget's `aborted` state."""
    panel = _panel(qtbot)

    _feed(
        panel,
        RunStarted(run_id=1, page_count=20),
        PageStarted(ordinal=4),
        RunAborted(reason="RuntimeError: the model returned nothing", ordinal=4),
    )

    banner = panel.banner
    assert isinstance(banner, ErrorBanner), "no banner for a failed run"
    assert "budget" not in banner.headline.text(), banner.headline.text()
    assert panel.cost_readout.state() != "aborted"


# =============================================================================
# The boundary: the panel and the readout are driven by events alone
# =============================================================================

_UI = Path(progress_module.__file__).parent

#: The abort reasons the panel branches on (MT-059 C-5 added CANCELLED to
#: MT-018's BUDGET) and, since MT-139 C-10, the pass names `PassStarted`
#: carries (MT-130 C-1: "the panel and the CLI import them rather than
#: re-spell"); the runner's constants, never re-spelled.
_REASONS = {"BUDGET", "CANCELLED", "READING", "TRANSLATING"}


def _reaching_past_the_stream(source: str) -> list[str]:
    tree = ast.parse(source)
    offending: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
            offending += [
                n
                for n in names
                if n.startswith(("mangatl.store", "mangatl.translate", "mangatl.pipeline"))
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(("mangatl.store", "mangatl.translate")):
                offending.append(node.module)
            elif node.module.startswith("mangatl.pipeline"):
                imported = [alias.name for alias in node.names]
                if node.module != "mangatl.pipeline.runner" or not set(imported) <= _REASONS:
                    offending.append(f"from {node.module} import {', '.join(imported)}")
    return offending


def test_control_the_boundary_check_flags_anything_but_the_reasons_and_the_pass_names() -> None:
    planted = "\n".join(
        (
            "from mangatl.pipeline.runner import BUDGET, CANCELLED",
            "from mangatl.pipeline.runner import BUDGET, CANCELLED, READING, TRANSLATING",
            "from mangatl.pipeline.runner import BUDGET, run_chapter",
            "from mangatl.pipeline.runner import READING, run_chapter",
            "from mangatl.pipeline.stage import Stage",
            "import mangatl.store.project",
        )
    )

    assert _reaching_past_the_stream(planted) == [
        "from mangatl.pipeline.runner import BUDGET, run_chapter",
        "from mangatl.pipeline.runner import READING, run_chapter",
        "from mangatl.pipeline.stage import Stage",
        "mangatl.store.project",
    ]


#: MT-062 AC-4 added `run_thumbnail.py`: the thumbnail reads the page image from
#: the `Chapter`'s folder, never from the project store.
@pytest.mark.parametrize("module", ["progress.py", "cost_readout.py", "run_thumbnail.py"])
def test_the_run_widgets_import_nothing_from_store_or_translate_and_only_reasons_from_pipeline(
    module: str,
) -> None:
    offending = _reaching_past_the_stream((_UI / module).read_text(encoding="utf-8"))
    assert offending == [], f"{module} reaches past the event stream: {offending}"


# =============================================================================
# MT-139: the panel reads the pass - a two-pass run (reading, the chapter
# step, translating), fed directly. Every string, bar value, stepper tuple and
# figure here is MECHANICAL (story C-8), its wording SETTLED by MT-130 PO-4 and
# MT-139 PO-6 (the user, 2026-11-05); C-7 is the exact table walked below.
# Without any `PassStarted` the panel is the single-pass panel above, byte for
# byte: every test above this section is that half of AC-5.
# =============================================================================

#: `components.md` §8 / MT-130 PO-4, spelled out (never read from the module).
READING_PAGES = "Reading pages"
TRANSLATING_PAGES = "Translating pages"

ALL_PENDING = (PENDING, PENDING, PENDING, PENDING)
ALL_DONE = (DONE, DONE, DONE, DONE)


def _reading_page(ordinal: int, detect: int = 1, ocr: int = 1) -> list[RunEvent]:
    """One page of the reading pass: `PageStarted`, detect, OCR. No translate."""
    return [
        PageStarted(ordinal=ordinal),
        StageFinished(ordinal=ordinal, stage=DETECT, elapsed_ms=detect),
        StageFinished(ordinal=ordinal, stage=OCR, elapsed_ms=ocr),
    ]


def _translating_page(ordinal: int, translate: int = 1) -> list[RunEvent]:
    """One page of the translating pass: `PageStarted`, translate."""
    return [
        PageStarted(ordinal=ordinal),
        StageFinished(ordinal=ordinal, stage=TRANSLATE, elapsed_ms=translate),
    ]


def _read_every_page(page_count: int) -> list[RunEvent]:
    """`RunStarted`, the reading pass over every page - nothing after it."""
    events: list[RunEvent] = [
        RunStarted(run_id=1, page_count=page_count),
        PassStarted(name=READING),
    ]
    for ordinal in range(page_count):
        events += _reading_page(ordinal)
    return events


def _chapter_priced(cents: int) -> CallPriced:
    """The chapter step's bill: `ordinal=None` (MT-105)."""
    return CallPriced(
        ordinal=None,
        spent=Usd(Decimal(cents) / 100),
        ceiling=DEFAULT_CEILING,
        projection=Projection(
            next_call=Usd(Decimal("0.06")),
            remaining_chapter=Usd(Decimal("0.18")),
            basis="estimate",
            sample_count=0,
        ),
    )


def _reading(panel: RunProgressPanel) -> tuple[str, int, tuple[str, ...]]:
    return (panel.overall_label.text(), panel.overall.value(), panel.stepper.step_states())


# --- AC-5 / AC-6: C-7's table, row by row ----------------------------------------


def test_a_two_pass_run_reads_each_row_of_the_contract_table(qtbot) -> None:  # type: ignore[no-untyped-def]
    """C-7, every row, m = 3: the label names the pass, the bar restarts at 0
    for the translating pass, and the stepper starts each translating page with
    Detecting and Reading already done."""
    panel = _panel(qtbot)

    _feed(panel, RunStarted(run_id=1, page_count=3))
    assert _reading(panel) == ("3 pages", 0, ALL_PENDING)

    _feed(panel, PassStarted(name=READING))
    assert _reading(panel) == (READING_PAGES, 0, ALL_PENDING)

    _feed(panel, PageStarted(ordinal=0))
    assert _reading(panel) == ("Reading page 1 of 3", 0, (ACTIVE, PENDING, PENDING, PENDING))
    _feed(panel, StageFinished(ordinal=0, stage=DETECT, elapsed_ms=1))
    assert _reading(panel) == ("Reading page 1 of 3", 0, (DONE, ACTIVE, PENDING, PENDING))
    _feed(panel, StageFinished(ordinal=0, stage=OCR, elapsed_ms=1))
    assert _reading(panel) == ("Reading page 1 of 3", 0, (DONE, DONE, ACTIVE, PENDING))

    _feed(panel, *_reading_page(1), PageStarted(ordinal=2))
    assert _reading(panel) == ("Reading page 3 of 3", 2, (ACTIVE, PENDING, PENDING, PENDING))
    _feed(
        panel,
        StageFinished(ordinal=2, stage=DETECT, elapsed_ms=1),
        StageFinished(ordinal=2, stage=OCR, elapsed_ms=1),
    )

    _feed(panel, PassStarted(name=TRANSLATING))
    assert _reading(panel) == (TRANSLATING_PAGES, 0, ALL_PENDING), (
        "the translating pass did not restart the bar at 0 with every step pending"
    )
    assert panel.remaining_label.text() == ESTIMATING

    _feed(panel, _chapter_priced(5))
    assert _reading(panel) == (TRANSLATING_PAGES, 0, ALL_PENDING)
    assert panel.cost_readout.figure.text() == "$0.05", "the chapter step's spend is not shown"

    _feed(panel, PageStarted(ordinal=0))
    assert _reading(panel) == ("Translating page 1 of 3", 0, (DONE, DONE, ACTIVE, PENDING))
    _feed(panel, StageFinished(ordinal=0, stage=TRANSLATE, elapsed_ms=1))
    assert _reading(panel) == ("Translating page 1 of 3", 0, ALL_DONE)

    _feed(panel, *_translating_page(1), PageStarted(ordinal=2))
    assert _reading(panel) == ("Translating page 3 of 3", 2, (DONE, DONE, ACTIVE, PENDING))
    _feed(panel, StageFinished(ordinal=2, stage=TRANSLATE, elapsed_ms=1))

    _feed(panel, RunFinished(run_id=1, pages_done=3))
    assert _reading(panel) == ("Translating page 3 of 3", 3, ALL_DONE)
    assert (panel.overall.minimum(), panel.overall.maximum()) == (0, 3)


def test_each_reading_page_reads_reading_page_n_of_m_on_the_bar_at_n(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-5: `PageStarted(n)` in the reading pass, every n of a 5-page run."""
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=5), PassStarted(name=READING))

    for ordinal in range(5):
        _feed(panel, *_reading_page(ordinal))
        assert panel.overall_label.text() == f"Reading page {ordinal + 1} of 5"
        assert panel.overall.value() == ordinal


def test_each_translating_page_reads_translating_page_n_of_m_on_the_bar_at_n(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-5: `PageStarted(n)` in the translating pass, every n of a 5-page run."""
    panel = _panel(qtbot)
    _feed(panel, *_read_every_page(5), PassStarted(name=TRANSLATING))

    for ordinal in range(5):
        _feed(panel, *_translating_page(ordinal))
        assert panel.overall_label.text() == f"Translating page {ordinal + 1} of 5"
        assert panel.overall.value() == ordinal


def test_elapsed_is_every_stage_of_both_passes_and_is_never_reset(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-5, PO-4: the reading pass is 3 x (10 s + 5 s) = 45 s and the
    translating pass 3 x 20 s = 60 s; the run's elapsed is 1:45, and the
    translating pass starts it at 0:45, not 0:00."""
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=3), PassStarted(name=READING))
    for ordinal in range(3):
        _feed(panel, *_reading_page(ordinal, detect=10_000, ocr=5_000))
    assert panel.elapsed_label.text() == "Elapsed 0:45"

    _feed(panel, PassStarted(name=TRANSLATING))
    assert panel.elapsed_label.text() == "Elapsed 0:45", "the translating pass reset elapsed"

    for ordinal in range(3):
        _feed(panel, *_translating_page(ordinal, translate=20_000))
    _feed(panel, RunFinished(run_id=1, pages_done=3))
    assert panel.elapsed_label.text() == "Elapsed 1:45"


# --- AC-6: the stepper's two new entry points -----------------------------------


def test_the_stepper_started_at_translating_has_detecting_and_reading_done(qtbot) -> None:  # type: ignore[no-untyped-def]
    """C-6: `start(active=2)` - steps before 2 done, 2 active, the rest pending."""
    stepper = PageStageStepper()
    qtbot.addWidget(stepper)

    stepper.start(active=2)

    assert stepper.step_states() == (DONE, DONE, ACTIVE, PENDING)
    names = [label.accessibleName() for label in stepper.findChildren(QLabel)]
    assert names == [
        "Detecting: done",
        "Reading: done",
        "Translating: active",
        "Done: pending",
    ]


def test_the_stepper_reset_makes_every_step_pending(qtbot) -> None:  # type: ignore[no-untyped-def]
    """C-6: `reset()`, between passes - after a page that had finished."""
    stepper = PageStageStepper()
    qtbot.addWidget(stepper)
    stepper.start()
    for stage in (DETECT, OCR, TRANSLATE):
        stepper.finish(stage)
    assert stepper.step_states() == ALL_DONE, "precondition: the page finished"

    stepper.reset()

    assert stepper.step_states() == ALL_PENDING
    names = [label.accessibleName() for label in stepper.findChildren(QLabel)]
    assert names == [f"{step}: pending" for step in STAGE_STEPS]


def test_a_translating_page_finishing_translate_makes_every_step_done(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-6: in the translating pass, `PageStarted` gives (done, done, active,
    pending) and `StageFinished("translate")` (done, done, done, done) - for
    every page, not only the first."""
    panel = _panel(qtbot)
    _feed(panel, *_read_every_page(3), PassStarted(name=TRANSLATING))

    for ordinal in range(3):
        _feed(panel, PageStarted(ordinal=ordinal))
        assert panel.stepper.step_states() == (DONE, DONE, ACTIVE, PENDING), f"page {ordinal}"
        _feed(panel, StageFinished(ordinal=ordinal, stage=TRANSLATE, elapsed_ms=1))
        assert panel.stepper.step_states() == ALL_DONE, f"page {ordinal}"


# --- AC-7: the remaining time is per pass ---------------------------------------


def test_the_remaining_time_is_estimated_per_pass_never_from_both(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-7, m = 5. Reading pages of 1,000 ms: after three, (3_000 // 3) * 2 =
    2,000 ms. The translating pass starts estimating again, and after three
    translating pages of 20,000 ms it is (60_000 // 3) * 2 = 40,000 ms - the
    reading pass's 5,000 ms excluded. Counters carried across the passes
    read "Remaining about 0:01" at `PassStarted` (4 completed, 1 left) and
    "Remaining about 0:00" at the end (8 completed of 5, none left)."""
    panel = _panel(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=5), PassStarted(name=READING))
    for ordinal in range(3):
        _feed(panel, *_reading_page(ordinal, detect=400, ocr=600))
    _assert_estimating(panel, "two reading pages completed, the third in progress")

    _feed(panel, PageStarted(ordinal=3))
    assert panel.remaining_label.text() == "Remaining about 0:02"

    _feed(
        panel,
        StageFinished(ordinal=3, stage=DETECT, elapsed_ms=400),
        StageFinished(ordinal=3, stage=OCR, elapsed_ms=600),
        *_reading_page(4, detect=400, ocr=600),
        PassStarted(name=TRANSLATING),
    )
    _assert_estimating(panel, "after PassStarted(translating)")

    for ordinal in range(3):
        _feed(panel, *_translating_page(ordinal, translate=20_000))
        _assert_estimating(panel, f"translating page {ordinal + 1} in progress")

    _feed(panel, PageStarted(ordinal=3))
    assert panel.remaining_label.text() == "Remaining about 0:40"


# --- AC-8: aborts, by pass (m = 5) ----------------------------------------------


def _banner(panel: RunProgressPanel) -> ErrorBanner:
    banner = panel.banner
    assert isinstance(banner, ErrorBanner), f"no ErrorBanner after the abort: {banner!r}"
    return banner


def test_a_reading_pass_failure_names_the_page_and_says_no_pages_were_translated(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-8 (a), PO-3 / PO-5: pages 0-1 were READ, not translated. Today's
    panel says `Pages 1-2 are translated` here - the lie DV-2 puts back."""
    panel = _panel(qtbot)
    _feed(
        panel,
        RunStarted(run_id=1, page_count=5),
        PassStarted(name=READING),
        *_reading_page(0),
        *_reading_page(1),
        PageStarted(ordinal=2),
        RunAborted(reason="RuntimeError: x", ordinal=2),
    )

    banner = _banner(panel)
    assert banner.headline.text() == f"Run stopped at page 3 of 5 {EM} page 3 failed."
    assert banner.body.text() == "RuntimeError: x\nNo pages were translated."
    assert banner.actions == ()
    assert banner.findChildren(QAbstractButton) == []
    assert panel.cost_readout.state() != "aborted"


def test_a_refused_chapter_step_stops_the_run_before_page_1(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-8 (b), PO-6: the budget refused the glossary step, after every page
    was read and before any page was translated."""
    panel = _panel(qtbot)
    _feed(
        panel,
        *_read_every_page(5),
        PassStarted(name=TRANSLATING),
        RunAborted(reason=BUDGET, ordinal=None),
    )

    banner = _banner(panel)
    assert banner.headline.text() == (
        f"Run stopped before page 1 of 5 {EM} the $2.00 budget was reached."
    )
    assert banner.body.text() == "No pages were translated."
    assert banner.actions == ()
    assert banner.findChildren(QAbstractButton) == []
    assert panel.cost_readout.state() == "aborted"


def test_a_refused_chapter_step_names_the_panels_own_ceiling(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-8 (b): the ceiling in the PO-6 headline is the panel's, as today's
    budget headline's is (`format_usd(self._ceiling)`)."""
    panel = _panel(qtbot, ceiling=Usd(Decimal("5.00")))
    _feed(
        panel,
        *_read_every_page(5),
        PassStarted(name=TRANSLATING),
        RunAborted(reason=BUDGET, ordinal=None),
    )

    assert _banner(panel).headline.text() == (
        f"Run stopped before page 1 of 5 {EM} the $5.00 budget was reached."
    )


def test_a_failed_chapter_step_says_the_glossary_step_failed(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-8 (c), PO-6: the reason verbatim, nothing translated, no action, and
    the cost readout exactly as it was (only the budget marks it aborted)."""
    panel = _panel(qtbot)
    _feed(panel, *_read_every_page(5), PassStarted(name=TRANSLATING), _chapter_priced(5))
    readout_before = (panel.cost_readout.state(), panel.cost_readout.figure.text())

    _feed(panel, RunAborted(reason="RuntimeError: x", ordinal=None))

    banner = _banner(panel)
    assert banner.headline.text() == (
        f"Run stopped before page 1 of 5 {EM} the glossary step failed."
    )
    assert banner.body.text() == "RuntimeError: x\nNo pages were translated."
    assert banner.actions == ()
    assert banner.findChildren(QAbstractButton) == []
    assert (panel.cost_readout.state(), panel.cost_readout.figure.text()) == readout_before
    assert panel.cost_readout.state() != "aborted"


def test_a_translating_pass_budget_abort_reads_exactly_as_today(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-8 (d): two pages translated, the budget stops page 3. The five
    reading-pass completions count for nothing; `ordinal` says what was kept."""
    panel = _panel(qtbot)
    _feed(
        panel,
        *_read_every_page(5),
        PassStarted(name=TRANSLATING),
        *_translating_page(0),
        *_translating_page(1),
        PageStarted(ordinal=2),
        RunAborted(reason=BUDGET, ordinal=2),
    )
    requested: list[int] = []
    panel.review_requested.connect(requested.append)

    banner = _banner(panel)
    assert banner.headline.text() == (
        f"Run stopped at page 3 of 5 {EM} the $2.00 budget was reached."
    )
    assert banner.body.text() == f"Pages 1{EN}2 are translated and can be reviewed and rendered."
    assert [button.text() for button in banner.actions] == [f"Review pages 1{EN}2"]

    banner.actions[0].click()

    assert requested == [2]


@pytest.mark.parametrize("in_pass", [READING, TRANSLATING])
def test_a_cancel_in_either_pass_shows_no_banner(qtbot, in_pass: str) -> None:  # type: ignore[no-untyped-def]
    """AC-8 (e), MT-059 D-4: a cancel (only ever the window closing) shows nothing."""
    panel = _panel(qtbot)
    if in_pass == READING:
        events: list[RunEvent] = [
            RunStarted(run_id=1, page_count=5),
            PassStarted(name=READING),
            *_reading_page(0),
            PageStarted(ordinal=1),
        ]
    else:
        events = [*_read_every_page(5), PassStarted(name=TRANSLATING), PageStarted(ordinal=0)]

    _feed(panel, *events, RunAborted(reason=CANCELLED, ordinal=None))

    assert panel.banner is None
    assert panel.findChildren(ErrorBanner) == []


# --- AC-9: the thumbnail keeps each page's markers through the translating pass --


def _chapter_of(tmp_path: Path, count: int) -> Chapter:
    """`count` pages of 300 x 400, each a small PNG of that aspect."""
    folder = tmp_path / "Chapter 9"
    folder.mkdir()
    pages = []
    for ordinal in range(count):
        filename = f"{ordinal + 1:02d}.png"
        image = QImage(30, 40, QImage.Format.Format_RGB32)
        image.fill(QColor("#3060c0"))
        assert image.save(str(folder / filename), "PNG"), "precondition: the page was written"
        pages.append(Page(ordinal, filename, 300, 400, f"{ordinal:064d}"))
    return Chapter(source_dir=folder, pages=tuple(pages))


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def _marker_points(panel: RunProgressPanel) -> list[list[tuple[float, float]]]:
    assert panel.thumbnail is not None, "a panel given a Chapter has no thumbnail"
    return [[(p.x(), p.y()) for p in marker] for marker in panel.thumbnail.markers()]


def test_a_page_starting_in_the_translating_pass_shows_its_own_markers_again(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """AC-9, PO-7: page 0 had two regions and page 1 one in the reading pass.
    When page 0 starts translating, the thumbnail shows page 0 WITH page 0's
    two markers - not page 1's, not none - and says so to assistive
    technology, rather than "detecting text regions..." for the whole call."""
    panel = _panel(qtbot, chapter=_chapter_of(tmp_path, 3))
    thumb = panel.thumbnail
    assert thumb is not None
    page_0 = (_ring(10, 10, 100, 100), _ring(150, 200, 250, 350))
    page_1 = (_ring(20, 30, 40, 50),)

    _feed(
        panel,
        RunStarted(run_id=1, page_count=3),
        PassStarted(name=READING),
        PageStarted(ordinal=0),
        RegionsDetected(ordinal=0, polygons=page_0),
    )
    page_0_markers = _marker_points(panel)
    assert len(page_0_markers) == 2, "precondition: the reading pass showed page 0's markers"
    _feed(panel, PageStarted(ordinal=1), RegionsDetected(ordinal=1, polygons=page_1))
    page_1_markers = _marker_points(panel)
    assert thumb.accessibleName() == "Page 2: 1 text region found", "precondition"

    _feed(panel, PassStarted(name=TRANSLATING), PageStarted(ordinal=0))

    assert thumb.accessibleName() == "Page 1: 2 text regions found", (
        "page 0 started translating with its markers forgotten"
    )
    assert _marker_points(panel) == page_0_markers

    _feed(panel, PageStarted(ordinal=1))

    assert thumb.accessibleName() == "Page 2: 1 text region found"
    assert _marker_points(panel) == page_1_markers
