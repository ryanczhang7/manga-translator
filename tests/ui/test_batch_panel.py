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
from PySide6.QtWidgets import QLabel

from mangatl.domain.batch import BatchJob
from mangatl.domain.budget import Projection
from mangatl.domain.events import (
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
from mangatl.ui.progress import PageStageStepper, RunProgressPanel

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


def test_a_batch_budget_refusal_names_the_ceiling_offers_nothing_and_claims_no_page(
    qtbot: Any,
) -> None:
    """AC-4 and PO-6: after three pages of local stages the per-page banner
    would offer "Review pages 1-2"; a batch translated none of them."""
    panel = _run_panel(qtbot)
    _local_stages(panel)
    panel.on_event(_priced(usd("0.05")))

    panel.on_event(RunAborted(reason=BUDGET, ordinal=None))

    banner = panel.banner
    assert banner is not None, "no banner after a batch budget refusal"
    assert banner.headline.text() == f"Batch not submitted {EM} the $0.05 budget would be exceeded."
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
