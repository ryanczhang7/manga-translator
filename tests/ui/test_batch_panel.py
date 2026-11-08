"""MT-113 C-4 and C-5: the waiting panel, and the run panel under a batch.

- `ui.batch_panel.BatchWaitingPanel` (C-4): what was submitted and when, the
  projection against the ceiling (hidden on a reopen, PO-4), the last poll's
  time or error, and the failure banner. Driven here by `show_state`,
  `on_event` and `poll_error` directly - no controller, no thread.
- `ui.batch_panel.PendingBatch` (C-4): what `app.open_folder` returns for a
  project with a pending job.
- `ui.progress` under `batch=True` (C-5): three steps, `Detecting`, `Reading`,
  `Done`; and an abort that never claims a page translated and offers no
  action (PO-6).

**Oracle: mechanical.** Every line is spelled out here character for
character from the story's Contract, never read back from the module under
test. Times are `HH:MM` **local** - `t.astimezone().strftime("%H:%M")` - from an
injected `now` or a fixed aware `submitted_at`; on this machine (UTC-6 when
written) the UTC and the local reading differ, so a panel formatting UTC fails.

**RED:** `mangatl.ui.batch_panel` does not exist and `BATCH_STAGE_STEPS` is not
in `ui.progress`; both are reached inside helpers, so the file collects and
each test fails on its own named absence.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel

from mangatl.domain.batch import BatchJob
from mangatl.domain.budget import Projection
from mangatl.domain.events import (
    BatchCollected,
    BatchFailed,
    BatchWaiting,
    CallPriced,
    PageStarted,
    RunAborted,
    RunStarted,
    StageFinished,
)
from mangatl.domain.money import Usd
from mangatl.pipeline.runner import BUDGET, CANCELLED
from mangatl.ui.progress import ErrorBanner, PageStageStepper, RunProgressPanel

EM = "\N{EM DASH}"

#: The poll's clock, and the submission's instant: different minutes, both aware.
NOW = datetime(2026, 11, 4, 15, 7, tzinfo=UTC)
SUBMITTED = datetime(2026, 11, 4, 14, 52, tzinfo=UTC)


def hhmm(moment: datetime) -> str:
    return moment.astimezone().strftime("%H:%M")


def usd(text: str) -> Usd:
    return Usd(Decimal(text))


def _batch_panel() -> Any:
    import mangatl.ui.batch_panel as module  # type: ignore[import-not-found]

    return module


def _waiting_state(**fields: Any) -> Any:
    from mangatl.ui.run import WaitingState  # type: ignore[attr-defined]

    return WaitingState(**fields)


def _panel(qtbot: Any) -> Any:
    panel = _batch_panel().BatchWaitingPanel(now=lambda: NOW)
    qtbot.addWidget(panel)
    return panel


def _state(
    pages: int = 3, jobs: int = 1, projection: Usd | None = None, ceiling: Usd | None = None
) -> Any:
    return _waiting_state(
        page_count=pages,
        job_count=jobs,
        submitted_at=SUBMITTED,
        projection=projection,
        ceiling=ceiling,
    )


# =============================================================================
# C-4: BatchWaitingPanel
# =============================================================================


def test_the_waiting_panel_and_its_lines_carry_their_object_names(qtbot: Any) -> None:
    panel = _panel(qtbot)

    assert panel.objectName() == "batch-waiting"
    assert isinstance(panel.submitted, QLabel) and panel.submitted.objectName() == (
        "batch-submitted"
    )
    assert isinstance(panel.projection, QLabel)
    assert panel.projection.objectName() == "batch-projection"
    assert isinstance(panel.last_checked, QLabel)
    assert panel.last_checked.objectName() == "batch-last-checked"
    assert panel.banner is None


def test_one_job_reads_as_one_batch_at_the_local_submission_time(qtbot: Any) -> None:
    panel = _panel(qtbot)

    panel.show_state(_state(pages=3, jobs=1, projection=usd("0.06"), ceiling=usd("1.50")))

    assert panel.submitted.text() == (
        f"Submitted 3 pages as one batch at {hhmm(SUBMITTED)}; waiting for Gemini."
    )


def test_several_jobs_read_as_that_many_batches(qtbot: Any) -> None:
    panel = _panel(qtbot)

    panel.show_state(_state(pages=200, jobs=2, projection=usd("4.00"), ceiling=usd("5.00")))

    assert panel.submitted.text() == (
        f"Submitted 200 pages as 2 batches at {hhmm(SUBMITTED)}; waiting for Gemini."
    )


def test_the_projection_line_is_the_projection_of_the_ceiling_in_dollars(qtbot: Any) -> None:
    panel = _panel(qtbot)

    panel.show_state(_state(projection=usd("0.06"), ceiling=usd("1.50")))

    assert panel.projection.text() == "Projected $0.06 of $1.50"
    assert not panel.projection.isHidden(), "the projection line is hidden after a submit"


def test_a_fraction_of_a_cent_in_the_projection_rounds_up_as_format_usd_does(
    qtbot: Any,
) -> None:
    panel = _panel(qtbot)

    panel.show_state(_state(projection=Usd(Decimal("0.0601")), ceiling=usd("2")))

    assert panel.projection.text() == "Projected $0.07 of $2.00"


def test_with_no_projection_the_projection_line_is_hidden(qtbot: Any) -> None:
    """PO-4: a reopened panel shows what was submitted and when, not a cost."""
    panel = _panel(qtbot)

    panel.show_state(_state(projection=None, ceiling=None))

    assert panel.projection.isHidden(), "the projection line shows on a reopen (PO-4)"


def test_last_checked_is_empty_until_the_first_poll(qtbot: Any) -> None:
    panel = _panel(qtbot)

    panel.show_state(_state(projection=usd("0.06"), ceiling=usd("1.50")))

    assert panel.last_checked.text() == ""


def test_a_job_still_waiting_sets_last_checked_to_the_local_time_of_the_poll(
    qtbot: Any,
) -> None:
    panel = _panel(qtbot)
    panel.show_state(_state(projection=usd("0.06"), ceiling=usd("1.50")))

    panel.on_event(BatchWaiting(job_id=1, state="pending"))

    assert panel.last_checked.text() == f"Last checked {hhmm(NOW)}."
    assert panel.banner is None


def test_a_poll_that_raised_shows_its_type_and_message_beside_the_time(qtbot: Any) -> None:
    panel = _panel(qtbot)
    panel.show_state(_state(projection=usd("0.06"), ceiling=usd("1.50")))

    panel.poll_error(ConnectionError("the network is unreachable"))

    assert panel.last_checked.text() == (
        f"Last checked {hhmm(NOW)}: ConnectionError: the network is unreachable"
    )
    assert panel.banner is None, "a failed poll is not a failed job: no banner"


def test_a_later_good_poll_replaces_the_error_line(qtbot: Any) -> None:
    panel = _panel(qtbot)
    panel.show_state(_state())
    panel.poll_error(TimeoutError("read timed out"))

    panel.on_event(BatchWaiting(job_id=1, state="pending"))

    assert panel.last_checked.text() == f"Last checked {hhmm(NOW)}."


@pytest.mark.parametrize("state", ["failed", "cancelled", "expired"])
def test_a_failed_job_shows_the_banner_naming_its_state_with_no_action(
    qtbot: Any, state: str
) -> None:
    from mangatl.ui.progress import ErrorBanner

    panel = _panel(qtbot)
    panel.show_state(_state(projection=usd("0.06"), ceiling=usd("1.50")))

    panel.on_event(BatchFailed(job_id=1, state=state))

    banner = panel.banner
    assert isinstance(banner, ErrorBanner), f"the panel's banner is {banner!r}"
    assert banner.headline.text() == f"Batch job failed {EM} Gemini reports it {state}."
    assert banner.body.text() == "Its pages were not translated."
    assert banner.actions == (), "the failure banner offers an action"


def test_the_accessible_name_is_the_visible_lines_in_order_recomputed_on_each_change(
    qtbot: Any,
) -> None:
    panel = _panel(qtbot)
    panel.show_state(_state(projection=usd("0.06"), ceiling=usd("1.50")))
    submitted = f"Submitted 3 pages as one batch at {hhmm(SUBMITTED)}; waiting for Gemini."

    assert panel.accessibleName() == f"{submitted} Projected $0.06 of $1.50"

    panel.on_event(BatchWaiting(job_id=1, state="pending"))

    assert panel.accessibleName() == (
        f"{submitted} Projected $0.06 of $1.50 Last checked {hhmm(NOW)}."
    )


def test_a_hidden_projection_is_not_part_of_the_accessible_name(qtbot: Any) -> None:
    panel = _panel(qtbot)

    panel.show_state(_state(projection=None, ceiling=None))

    assert panel.accessibleName() == (
        f"Submitted 3 pages as one batch at {hhmm(SUBMITTED)}; waiting for Gemini."
    )


def test_pending_batch_is_a_frozen_source_project_and_jobs_triple(tmp_path: Path) -> None:
    job = BatchJob(
        id=1,
        run_id=1,
        provider_job_id="batches/a",
        model_id="gemini-3.1-pro-preview",
        state="submitted",
        submitted_at=SUBMITTED.isoformat(),
        collected_at=None,
        failure=None,
        first_ordinal=0,
        last_ordinal=2,
    )
    pending = _batch_panel().PendingBatch(
        source_dir=tmp_path / "ch", project_dir=tmp_path / "ch.mtproj", jobs=(job,)
    )

    assert [f.name for f in dataclasses.fields(pending)] == ["source_dir", "project_dir", "jobs"]
    assert pending.jobs == (job,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        pending.jobs = ()


# =============================================================================
# C-5: the run panel under a batch
# =============================================================================


def _steps(stepper: PageStageStepper) -> list[str]:
    """Each step's accessible name, `"{step}: {state}"`, in order."""
    return [label.accessibleName() for label in stepper.findChildren(QLabel, "stage-step")]


def test_the_batch_stage_steps_are_detecting_reading_done() -> None:
    from mangatl.ui.progress import BATCH_STAGE_STEPS  # type: ignore[attr-defined]

    assert BATCH_STAGE_STEPS == ("Detecting", "Reading", "Done")


def test_a_batch_stepper_shows_three_steps_and_no_translating(qtbot: Any) -> None:
    from mangatl.ui.progress import BATCH_STAGE_STEPS  # type: ignore[attr-defined]

    stepper = PageStageStepper(steps=BATCH_STAGE_STEPS)  # type: ignore[call-arg]
    qtbot.addWidget(stepper)

    assert _steps(stepper) == ["Detecting: pending", "Reading: pending", "Done: pending"]


def test_finishing_ocr_under_the_batch_steps_makes_done_done(qtbot: Any) -> None:
    from mangatl.ui.progress import BATCH_STAGE_STEPS  # type: ignore[attr-defined]

    stepper = PageStageStepper(steps=BATCH_STAGE_STEPS)  # type: ignore[call-arg]
    qtbot.addWidget(stepper)

    stepper.start()
    assert _steps(stepper) == ["Detecting: active", "Reading: pending", "Done: pending"]
    stepper.finish("detect")
    assert _steps(stepper) == ["Detecting: done", "Reading: active", "Done: pending"]
    stepper.finish("ocr")
    assert _steps(stepper) == ["Detecting: done", "Reading: done", "Done: done"]
    assert stepper.step_states() == ("done", "done", "done")


def test_the_default_stepper_still_has_four_steps_with_translating(qtbot: Any) -> None:
    stepper = PageStageStepper()
    qtbot.addWidget(stepper)

    stepper.start()
    stepper.finish("detect")
    stepper.finish("ocr")

    assert _steps(stepper) == [
        "Detecting: done",
        "Reading: done",
        "Translating: active",
        "Done: pending",
    ]


def _run_panel(qtbot: Any, ceiling: Usd | None = None) -> RunProgressPanel:
    options: dict[str, Any] = {"batch": True}
    if ceiling is not None:
        options["ceiling"] = ceiling
    panel = RunProgressPanel(**options)
    qtbot.addWidget(panel)
    return panel


def _local_stages(panel: RunProgressPanel, pages: int = 3) -> None:
    """Three pages through detect and OCR, as `submit_chapter` forwards them:
    no `RunFinished`."""
    panel.on_event(RunStarted(run_id=1, page_count=pages))
    for n in range(pages):
        panel.on_event(PageStarted(ordinal=n))
        panel.on_event(StageFinished(ordinal=n, stage="detect", elapsed_ms=5))
        panel.on_event(StageFinished(ordinal=n, stage="ocr", elapsed_ms=5))


def _priced(ceiling: Usd) -> CallPriced:
    volume = usd("0.06")
    return CallPriced(
        ordinal=None,
        spent=usd("0.00"),
        ceiling=ceiling,
        projection=Projection(
            next_call=volume, remaining_chapter=volume, basis="estimate", sample_count=0
        ),
    )


def test_a_batch_run_panel_steps_through_detecting_reading_done(qtbot: Any) -> None:
    panel = _run_panel(qtbot)

    _local_stages(panel)

    assert _steps(panel.stepper) == ["Detecting: done", "Reading: done", "Done: done"]


def test_a_batch_budget_refusal_names_the_projection_and_ceiling_offers_nothing_and_claims_no_page(
    qtbot: Any,
) -> None:
    """AC-4 as amended (AM-1) and PO-6: the headline names the refused
    `CallPriced`'s `projection.next_call` and its `ceiling`. `next_call` and
    `remaining_chapter` differ here, so a headline built from the wrong field
    fails. And after three pages of local stages the per-page banner would
    offer "Review pages 1-2", but a batch translated none of them."""
    panel = _run_panel(qtbot)
    _local_stages(panel)
    panel.on_event(
        CallPriced(
            ordinal=None,
            spent=usd("0.00"),
            ceiling=usd("0.05"),
            projection=Projection(
                next_call=usd("0.06"),
                remaining_chapter=usd("0.09"),
                basis="estimate",
                sample_count=0,
            ),
        )
    )

    panel.on_event(RunAborted(reason=BUDGET, ordinal=None))

    banner = panel.banner
    assert banner is not None, "no banner after a batch budget refusal"
    assert banner.headline.text() == (
        f"Batch not submitted {EM} projected $0.06 exceeds the $0.05 budget."
    )
    assert banner.body.text() == "No pages were translated."
    assert banner.actions == (), "a batch refusal offers an action: no page was translated"


def test_a_batch_budget_refusal_shows_the_readout_of_the_refused_decision_marked_aborted(
    qtbot: Any,
) -> None:
    """AC-4's three numbers, from `CallPriced`: the readout is exactly what a
    readout fed that `CallPriced` and then marked aborted shows (a batch
    projection has no samples, so `CostReadout` itself does not print it)."""
    from mangatl.ui.cost_readout import CostReadout

    panel = _run_panel(qtbot)
    _local_stages(panel)
    priced = _priced(usd("0.05"))
    panel.on_event(priced)

    panel.on_event(RunAborted(reason=BUDGET, ordinal=None))

    reference = CostReadout()
    qtbot.addWidget(reference)
    reference.set_state(priced.spent, priced.ceiling, priced.projection)
    reference.mark_aborted()
    readout = panel.cost_readout
    assert readout.figure.text() == "$0.00"
    assert readout.budget_label.text() == "of $0.05"
    assert readout.state() == "aborted"
    assert readout.triple() == reference.triple()


def test_with_no_call_priced_the_refusal_names_the_panels_own_ceiling(qtbot: Any) -> None:
    panel = _run_panel(qtbot, ceiling=usd("3.00"))
    _local_stages(panel)

    panel.on_event(RunAborted(reason=BUDGET, ordinal=None))

    assert panel.banner is not None
    assert panel.banner.headline.text() == (
        f"Batch not submitted {EM} the $3.00 budget would be exceeded."
    )


def test_a_batch_page_failure_names_the_page_and_leads_with_the_reason(qtbot: Any) -> None:
    panel = _run_panel(qtbot)
    panel.on_event(RunStarted(run_id=1, page_count=3))
    panel.on_event(PageStarted(ordinal=0))
    panel.on_event(StageFinished(ordinal=0, stage="detect", elapsed_ms=5))
    panel.on_event(StageFinished(ordinal=0, stage="ocr", elapsed_ms=5))
    panel.on_event(PageStarted(ordinal=1))

    panel.on_event(RunAborted(reason="RuntimeError: ocr broke", ordinal=1))

    banner = panel.banner
    assert banner is not None
    assert banner.headline.text() == f"Batch not submitted {EM} page 2 failed."
    assert banner.body.text() == "RuntimeError: ocr broke\nNo pages were translated."
    assert banner.actions == ()
    assert panel.cost_readout.state() != "aborted", "a page failure is not the budget"


def test_a_batch_failure_on_no_page_is_not_submitted_and_leads_with_the_reason(
    qtbot: Any,
) -> None:
    reason = "batch job 1 of 2 was refused: 429 RESOURCE_EXHAUSTED"
    panel = _run_panel(qtbot)
    _local_stages(panel)

    panel.on_event(RunAborted(reason=reason, ordinal=None))

    banner = panel.banner
    assert banner is not None
    assert banner.headline.text() == "Batch not submitted."
    assert banner.body.text() == f"{reason}\nNo pages were translated."
    assert banner.actions == ()


def test_a_cancelled_batch_shows_no_banner(qtbot: Any) -> None:
    panel = _run_panel(qtbot)
    _local_stages(panel)

    panel.on_event(RunAborted(reason=CANCELLED, ordinal=None))

    assert panel.banner is None


# =============================================================================
# MT-141 AC-3 and AC-5: the pass line, and the banner when the pass did not run
# =============================================================================
#
# `collect_volume` runs the consistency pass after the `BatchCollected` of the
# volume's last job, on the poll's own stream, so the waiting panel is what is
# on screen while it runs (D-4) - and, when it is refused or fails, the
# `RunAborted(reason, ordinal=None)` that reports it is the panel's (D-2).
# Every string is the story's D-3 / D-4, spelled out here.

CHECKING = "Checking the chapter for consistency\N{HORIZONTAL ELLIPSIS}"  # U+2026
PASS_REFUSED = f"Consistency pass not run {EM} the budget would be exceeded."
PASS_FAILED = "Consistency pass failed."
PASS_SURVIVED = "Every page is translated and can be reviewed and rendered."
REVIEW_CHAPTER = "Review the chapter"
PASS_REASON = "RuntimeError: the consistency call returned nothing"


def _collected(job_id: int, pages: int = 3) -> BatchCollected:
    return BatchCollected(job_id, pages, 0, ())


def _submitted_line(pages: int = 3, jobs: int = 1) -> str:
    batches = "one batch" if jobs == 1 else f"{jobs} batches"
    return f"Submitted {pages} pages as {batches} at {hhmm(SUBMITTED)}; waiting for Gemini."


def test_the_pass_line_is_named_batch_pass_and_starts_empty_and_hidden(qtbot: Any) -> None:
    """AC-3 / D-4: a plain label `batch-pass`, nothing on it until the pass runs."""
    panel = _panel(qtbot)
    panel.show_state(_state(jobs=1))

    line = panel.pass_line
    assert isinstance(line, QLabel)
    assert line.objectName() == "batch-pass"
    assert line.text() == ""
    assert line.isHidden(), "the pass line shows before any job is collected"
    assert panel.accessibleName() == _submitted_line()


def test_the_last_jobs_collection_shows_the_pass_line_last_in_the_accessible_name(
    qtbot: Any,
) -> None:
    """AC-3: one job, collected - the pass runs now, after today's lines."""
    panel = _panel(qtbot)
    panel.show_state(_state(jobs=1, projection=usd("0.06"), ceiling=usd("1.50")))
    panel.on_event(BatchWaiting(job_id=1, state="pending"))

    panel.on_event(_collected(1))

    assert panel.pass_line.text() == CHECKING
    assert not panel.pass_line.isHidden(), "the pass line is hidden while the pass runs"
    assert panel.accessibleName() == (
        f"{_submitted_line()} Projected $0.06 of $1.50 Last checked {hhmm(NOW)}. {CHECKING}"
    )


def test_before_the_last_of_several_jobs_is_collected_the_pass_line_stays_hidden(
    qtbot: Any,
) -> None:
    """AC-3: `job_count` from `show_state` - the first of three collections
    and the second leave the line empty, hidden and out of the name; the
    third shows it."""
    panel = _panel(qtbot)
    panel.show_state(_state(pages=5, jobs=3))
    today = _submitted_line(pages=5, jobs=3)

    for job_id in (1, 2):
        panel.on_event(_collected(job_id))
        assert panel.pass_line.text() == "", f"after {job_id} of 3 collected"
        assert panel.pass_line.isHidden(), f"after {job_id} of 3 collected"
        assert panel.accessibleName() == today, f"after {job_id} of 3 collected"

    panel.on_event(_collected(3))

    assert panel.pass_line.text() == CHECKING
    assert not panel.pass_line.isHidden()
    assert panel.accessibleName() == f"{today} {CHECKING}"


def test_show_state_starts_the_count_of_collected_jobs_again(qtbot: Any) -> None:
    """AC-3: the count is counted from `show_state` - one collection before a
    second `show_state(jobs=2)` does not count towards it."""
    panel = _panel(qtbot)
    panel.show_state(_state(jobs=2))
    panel.on_event(_collected(1))

    panel.show_state(_state(jobs=2))
    panel.on_event(_collected(2))

    assert panel.pass_line.text() == ""
    assert panel.pass_line.isHidden(), "a collection before show_state counted"

    panel.on_event(_collected(3))

    assert panel.pass_line.text() == CHECKING


@pytest.mark.parametrize(
    ("reason", "headline", "body"),
    [
        (BUDGET, PASS_REFUSED, PASS_SURVIVED),
        (PASS_REASON, PASS_FAILED, f"{PASS_REASON}\n{PASS_SURVIVED}"),
    ],
    ids=["refused", "failed"],
)
def test_a_pass_that_did_not_run_shows_the_pass_banner_and_clears_the_pass_line(
    qtbot: Any, reason: str, headline: str, body: str
) -> None:
    """AC-5 / D-2: the per-page panel's banner, word for word, at the top of
    the waiting panel; the pass line is cleared, hidden and out of the name,
    because the banner says what happened to the check (D-4)."""
    panel = _panel(qtbot)
    panel.show_state(_state(jobs=1))
    panel.on_event(_collected(1))
    assert panel.pass_line.text() == CHECKING, "precondition: the pass was running"

    panel.on_event(RunAborted(reason=reason, ordinal=None))

    banner = panel.banner
    assert isinstance(banner, ErrorBanner), f"the panel's banner is {banner!r}"
    assert banner.headline.text() == headline
    assert banner.body.text() == body
    assert [button.text() for button in banner.actions] == [REVIEW_CHAPTER]
    assert [b.text() for b in banner.findChildren(QAbstractButton)] == [REVIEW_CHAPTER]
    assert panel.pass_line.text() == ""
    assert panel.pass_line.isHidden()
    assert panel.accessibleName() == _submitted_line()
    texts = [label.text() for label in panel.findChildren(QLabel)]
    assert not any("Run stopped" in text for text in texts), texts


def test_the_pass_banners_action_asks_for_the_review(qtbot: Any) -> None:
    """AC-5: `review_requested`, a signal with no argument - the window
    connects it to its own `_review`."""
    panel = _panel(qtbot)
    panel.show_state(_state(jobs=1))
    panel.on_event(_collected(1))
    panel.on_event(RunAborted(reason=BUDGET, ordinal=None))
    asked: list[tuple[object, ...]] = []
    panel.review_requested.connect(lambda *args: asked.append(args))

    banner = panel.banner
    assert isinstance(banner, ErrorBanner), f"the panel's banner is {banner!r}"
    banner.actions[0].click()

    assert asked == [()]


def test_the_waiting_panels_pass_banner_takes_focus_and_is_announced(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-5 / C-5: posted once to assistive technology, its action focused."""
    announced: list[object] = []
    monkeypatch.setattr(ErrorBanner, "announce", lambda self: announced.append(self))
    panel = _panel(qtbot)
    panel.resize(800, 500)
    with qtbot.waitExposed(panel):
        panel.show()
    panel.activateWindow()
    qtbot.waitUntil(panel.isActiveWindow)
    panel.show_state(_state(jobs=1))
    panel.on_event(_collected(1))

    panel.on_event(RunAborted(reason=BUDGET, ordinal=None))
    QApplication.processEvents()

    banner = panel.banner
    assert isinstance(banner, ErrorBanner), f"the panel's banner is {banner!r}"
    assert announced == [banner], f"announced {announced!r}"
    qtbot.waitUntil(banner.actions[0].hasFocus, timeout=2_000)


def test_a_cancelled_pass_on_the_waiting_panel_shows_no_banner(qtbot: Any) -> None:
    """AC-5: `CANCELLED` shows nothing, as on the run panel (MT-059 D-4). A
    control: it passes today, and must still pass with the pass banner."""
    panel = _panel(qtbot)
    panel.show_state(_state(jobs=1))
    panel.on_event(_collected(1))

    panel.on_event(RunAborted(reason=CANCELLED, ordinal=None))

    assert panel.banner is None
    assert panel.findChildren(ErrorBanner) == []
