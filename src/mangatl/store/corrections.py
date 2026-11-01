"""What the consistency pass changed, from what, and why (MT-103 AC-5; MT-115).

Corrections are addressed as every line address in the store is -
`(page_ordinal, reading_index)` - and `correction.page_id` is `page.id`,
resolved from the ordinal here, for `store.ledger.record_call`'s reason: an
ordinal stored where a page id belongs agrees with itself on a chapter whose
first page id happens to be 0 and is wrong everywhere else.

This module records a correction; it does not apply one. Writing the corrected
English onto `line` is MT-115's.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mangatl.domain.correction import Correction
from mangatl.store.project import Project

__all__ = ["corrections_for", "record_correction"]

_SELECT_PAGE_ID = "SELECT id FROM page WHERE ordinal = ?"
_INSERT_CORRECTION = (
    "INSERT INTO correction (run_id, page_id, reading_index, before_en, after_en, reason, at)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)
# Reading order, then the order recorded: `ORDER BY` is explicit for the reason
# `project._SELECT_PAGES` gives.
_SELECT_CORRECTIONS = (
    "SELECT correction.run_id, page.ordinal, correction.reading_index,"
    " correction.before_en, correction.after_en, correction.reason"
    " FROM correction JOIN page ON page.id = correction.page_id"
    " WHERE page.ordinal = ? ORDER BY correction.reading_index, correction.id"
)


def record_correction(
    project: Project,
    run_id: int,
    ordinal: int,
    reading_index: int,
    before_en: str,
    after_en: str,
    reason: str,
) -> None:
    """Record that run `run_id` changed one line's English, stamped now in UTC.
    The strings are stored as given, character for character."""
    with project.transaction() as cursor:
        page_id = cursor.execute(_SELECT_PAGE_ID, (ordinal,)).fetchone()[0]
        cursor.execute(
            _INSERT_CORRECTION,
            (
                run_id,
                page_id,
                reading_index,
                before_en,
                after_en,
                reason,
                datetime.now(UTC).isoformat(),
            ),
        )


def corrections_for(project: Project, ordinal: int) -> tuple[Correction, ...]:
    """One page's corrections in reading order; `()` for a page with none.
    Opens no transaction, `Project.select`'s rule."""
    return tuple(
        Correction(
            run_id=int(run_id),
            page_ordinal=int(page_ordinal),
            reading_index=int(reading_index),
            before_en=str(before_en),
            after_en=str(after_en),
            reason=str(reason),
        )
        for run_id, page_ordinal, reading_index, before_en, after_en, reason in project.select(
            _SELECT_CORRECTIONS, (ordinal,)
        )
    )
