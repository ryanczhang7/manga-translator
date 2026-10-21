"""MT-086 Contract block 1: a page's status, derived from its lines.

`mangatl.domain.page_status.page_progress` is a pure rule over the page's line
statuses and three flags. Everything below is MECHANICAL, read out of block 1:

- the seven statuses, in the design table's order (`components.md` §PageStrip);
- the counts, computed on every call whatever the status: `reviewed` is the
  number of lines in `COMMITTED_STATUSES` (PO-2: accepted, edited, reverted),
  `failed` the number whose status is `failed`, `total` is `len(lines)`; a
  `None` entry (a region with no line row) counts in `total` only;
- the precedence, first match wins: running -> stale (skipped) -> not done
  (pending) -> any failed -> none reviewed (translated, which includes
  `total == 0`, PO-3) -> some unreviewed (partly) -> fully reviewed.

**Every rule decides a case where the next rule would answer differently.**
That is what makes the order observable: each `test_..._before_...` case is
built so that deleting or swapping the named rule changes the answer.

**The properties** run over the whole input domain - any list of `None` or any
`LineStatus`, any three booleans - with no generator narrowed. Together they
characterise the status completely, so an implementation that passes the
examples by special-casing them still fails here.

**RED.** The module does not exist: this file fails at collection with
`ModuleNotFoundError: No module named 'mangatl.domain.page_status'`, and no
assertion in it has run. Expected values are recorded in the story's handoff.

**Timing.** Nothing waits; the properties run 200 short examples each.
"""

from __future__ import annotations

import dataclasses
import typing

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mangatl.domain.line import COMMITTED_STATUSES, LINE_STATUSES
from mangatl.domain.page_status import (
    PAGE_STATUSES,
    PageProgress,
    PageStatus,
    page_progress,
)

# --- Settled: components.md §PageStrip's seven rows, in order (block 1) -------
DESIGN_PAGE_STATUSES = (
    "pending",
    "running",
    "translated",
    "partly_reviewed",
    "fully_reviewed",
    "failed",
    "skipped",
)
# --- Settled: PO-2's "reviewed" -------------------------------------------------
DESIGN_REVIEWED = frozenset({"accepted", "edited", "reverted"})


# =============================================================================
# The vocabulary and the value
# =============================================================================


def test_the_seven_page_statuses_are_the_design_table_in_order() -> None:
    assert PAGE_STATUSES == DESIGN_PAGE_STATUSES


def test_the_page_status_type_names_exactly_the_seven_statuses_in_order() -> None:
    assert typing.get_args(PageStatus) == DESIGN_PAGE_STATUSES


def test_reviewed_means_a_committed_user_act_accepted_edited_or_reverted() -> None:
    # PO-2 reads COMMITTED_STATUSES; pinned here so a change to it is noticed.
    assert frozenset(COMMITTED_STATUSES) == DESIGN_REVIEWED


def test_page_progress_carries_status_reviewed_total_failed_in_that_order() -> None:
    assert [field.name for field in dataclasses.fields(PageProgress)] == [
        "status",
        "reviewed",
        "total",
        "failed",
    ]


def test_page_progress_is_a_frozen_value() -> None:
    progress = PageProgress("translated", 0, 3, 0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        progress.reviewed = 1  # type: ignore[misc]
    assert progress == PageProgress(status="translated", reviewed=0, total=3, failed=0)


def test_the_flags_are_keyword_only() -> None:
    with pytest.raises(TypeError):
        page_progress(["proposed"], True)  # type: ignore[misc]


def test_stale_and_running_default_to_false() -> None:
    lines = ["accepted", "proposed"]
    assert page_progress(lines, page_done=True) == page_progress(
        lines, page_done=True, stale=False, running=False
    )
    assert page_progress(lines, page_done=True) == PageProgress("partly_reviewed", 1, 2, 0)


# =============================================================================
# Every status reachable, and the precedence: each rule decides a case the
# next rule would have answered differently
# =============================================================================


def test_running_wins_over_stale() -> None:
    assert page_progress(["proposed"], page_done=True, stale=True, running=True).status == (
        "running"
    )


def test_running_wins_over_a_page_that_is_not_done() -> None:
    assert page_progress([], page_done=False, running=True) == PageProgress("running", 0, 0, 0)


def test_running_still_counts_the_lines() -> None:
    lines = ["accepted", "failed", None, "proposed", "edited"]
    assert page_progress(lines, page_done=True, running=True) == PageProgress("running", 2, 5, 1)


def test_stale_is_skipped_before_a_page_that_is_not_done_is_pending() -> None:
    assert page_progress(["proposed"], page_done=False, stale=True) == PageProgress(
        "skipped", 0, 1, 0
    )


def test_stale_is_skipped_even_on_a_done_page_with_a_failed_line() -> None:
    lines = ["failed", "accepted"]
    assert page_progress(lines, page_done=True, stale=True) == PageProgress("skipped", 1, 2, 1)


def test_a_page_that_is_not_done_is_pending_before_a_failed_line_counts() -> None:
    lines = ["failed", "proposed"]
    assert page_progress(lines, page_done=False) == PageProgress("pending", 0, 2, 1)


def test_a_page_that_is_not_done_is_pending_even_when_every_line_is_reviewed() -> None:
    lines = ["accepted", "edited"]
    assert page_progress(lines, page_done=False) == PageProgress("pending", 2, 2, 0)


def test_a_not_done_page_with_no_regions_is_pending() -> None:
    assert page_progress([], page_done=False) == PageProgress("pending", 0, 0, 0)


def test_a_failed_line_makes_the_page_failed_before_none_reviewed_is_translated() -> None:
    lines = ["proposed", "failed", "proposed"]
    assert page_progress(lines, page_done=True) == PageProgress("failed", 0, 3, 1)


def test_a_failed_line_makes_the_page_failed_even_when_every_other_line_is_reviewed() -> None:
    lines = ["accepted", "edited", "reverted", "failed", "failed"]
    assert page_progress(lines, page_done=True) == PageProgress("failed", 3, 5, 2)


def test_a_done_page_with_nothing_reviewed_is_translated() -> None:
    lines = ["proposed", "proposed", "proposed"]
    assert page_progress(lines, page_done=True) == PageProgress("translated", 0, 3, 0)


def test_a_done_page_with_no_lines_is_translated_not_vacuously_fully_reviewed() -> None:
    """PO-3: `reviewed == 0` decides before `reviewed < total` would say
    fully reviewed (0 < 0 is false)."""
    assert page_progress([], page_done=True) == PageProgress("translated", 0, 0, 0)


def test_a_done_page_with_some_lines_unreviewed_is_partly_reviewed() -> None:
    lines = ["accepted", "proposed", "proposed"]
    assert page_progress(lines, page_done=True) == PageProgress("partly_reviewed", 1, 3, 0)


def test_a_done_page_with_every_line_reviewed_is_fully_reviewed() -> None:
    lines = ["accepted", "edited", "reverted"]
    assert page_progress(lines, page_done=True) == PageProgress("fully_reviewed", 3, 3, 0)


def test_every_page_status_is_reachable() -> None:
    reached = {
        page_progress([], page_done=False).status,
        page_progress([], page_done=False, running=True).status,
        page_progress(["proposed"], page_done=True).status,
        page_progress(["accepted", "proposed"], page_done=True).status,
        page_progress(["accepted"], page_done=True).status,
        page_progress(["failed"], page_done=True).status,
        page_progress([], page_done=True, stale=True).status,
    }
    assert reached == set(DESIGN_PAGE_STATUSES)


# =============================================================================
# The counts: each committed status counts as reviewed, `None` in total only
# =============================================================================


@pytest.mark.parametrize("status", ["accepted", "edited", "reverted"])
def test_each_committed_status_alone_makes_a_one_line_page_fully_reviewed(status: str) -> None:
    assert page_progress([status], page_done=True) == PageProgress("fully_reviewed", 1, 1, 0)


def test_a_proposed_line_is_not_reviewed() -> None:
    assert page_progress(["proposed"], page_done=True) == PageProgress("translated", 0, 1, 0)


def test_a_region_with_no_line_counts_in_total_and_is_neither_reviewed_nor_failed() -> None:
    assert page_progress([None, "accepted"], page_done=True) == PageProgress(
        "partly_reviewed", 1, 2, 0
    )


def test_a_page_of_regions_with_no_lines_is_translated() -> None:
    assert page_progress([None, None], page_done=True) == PageProgress("translated", 0, 2, 0)


def test_the_design_example_twelve_of_eighteen_is_partly_reviewed() -> None:
    """AC-2's page: 12 committed (4 accepted, 4 edited, 4 reverted), 6 proposed."""
    lines = ["accepted"] * 4 + ["edited"] * 4 + ["reverted"] * 4 + ["proposed"] * 6
    assert page_progress(lines, page_done=True) == PageProgress("partly_reviewed", 12, 18, 0)


def test_any_sequence_is_accepted_and_left_unchanged() -> None:
    lines = ("accepted", None, "failed")
    assert page_progress(lines, page_done=True) == PageProgress("failed", 1, 3, 1)
    assert lines == ("accepted", None, "failed")


# =============================================================================
# Properties over the whole domain (no generator narrowed)
# =============================================================================

line_lists = st.lists(st.one_of(st.none(), st.sampled_from(LINE_STATUSES)), max_size=30)


@settings(deadline=None, max_examples=200)
@given(lines=line_lists, page_done=st.booleans(), stale=st.booleans(), running=st.booleans())
def test_the_counts_are_the_lines_whatever_the_flags(
    lines: list[str | None], page_done: bool, stale: bool, running: bool
) -> None:
    got = page_progress(lines, page_done=page_done, stale=stale, running=running)
    reviewed = sum(1 for line in lines if line in DESIGN_REVIEWED)
    failed = sum(1 for line in lines if line == "failed")
    assert (got.reviewed, got.total, got.failed) == (reviewed, len(lines), failed)
    assert got.reviewed + got.failed <= got.total
    assert got.status in DESIGN_PAGE_STATUSES


@settings(deadline=None, max_examples=200)
@given(lines=line_lists, page_done=st.booleans(), stale=st.booleans())
def test_running_always_wins(lines: list[str | None], page_done: bool, stale: bool) -> None:
    assert page_progress(lines, page_done=page_done, stale=stale, running=True).status == (
        "running"
    )


@settings(deadline=None, max_examples=200)
@given(lines=line_lists, page_done=st.booleans())
def test_stale_is_always_skipped_unless_running(lines: list[str | None], page_done: bool) -> None:
    assert page_progress(lines, page_done=page_done, stale=True).status == "skipped"


@settings(deadline=None, max_examples=200)
@given(lines=line_lists)
def test_a_page_that_is_not_done_is_always_pending_unless_stale_or_running(
    lines: list[str | None],
) -> None:
    assert page_progress(lines, page_done=False).status == "pending"


@settings(deadline=None, max_examples=200)
@given(lines=line_lists)
def test_a_done_pages_status_is_decided_by_its_counts_alone(lines: list[str | None]) -> None:
    got = page_progress(lines, page_done=True)
    if got.failed > 0:
        expected = "failed"
    elif got.reviewed == 0:
        expected = "translated"
    elif got.reviewed < got.total:
        expected = "partly_reviewed"
    else:
        expected = "fully_reviewed"
    assert got.status == expected, got
