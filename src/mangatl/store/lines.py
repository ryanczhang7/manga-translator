"""A page's lines as the review screen reads them, and a user's act written back
(MT-017 C-6).

Lines are addressed as every other line address in the store is -
`(page_ordinal, reading_index)` - and the database's `region.id` never leaves
this module.

**`commit_line` stores what it is given, character for character.** No
`normalise`, no strip: AC-2's "exactly" is a promise about the file, and O2's
normalisation belongs to measurement (MT-022), not to storage.

**The MT-014 obligation.** A commit carrying text calls
`store.glossary.reconcile_from_edit` so a user's rewording of a name reaches the
glossary before the next page is translated (MT-014 AC-2). It runs *after* this
module's own transaction has committed, because `Project.transaction()` is not
reentrant - and because the line is on disk whether or not the glossary agrees.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mangatl.domain.line import COMMITTED_STATUSES, Line, LineStatus, derive_status
from mangatl.store.glossary import reconcile_from_edit
from mangatl.store.project import PAGE_DONE, Project

__all__ = ["commit_line", "read_review_lines"]

# One entry per **region**, hence the LEFT JOIN from `region`, as
# `project._SELECT_PROPOSED` does: a region whose OCR has not run has no `line`
# row and reads back as NULLs (`line.id IS NULL`). `ORDER BY` is explicit for
# the reason `project._SELECT_PAGES` gives.
_SELECT_REVIEW = (
    "SELECT region.reading_index, line.id, line.source_ja, line.proposed_en,"
    " line.final_en, line.status, line.edited_at, line.ocr_empty"
    " FROM region LEFT JOIN line ON line.region_id = region.id"
    " JOIN page ON page.id = region.page_id"
    " WHERE page.ordinal = ? ORDER BY region.reading_index"
)

# The line hung off each region of one page, in reading order; `NULL` where
# the region has no line row.
_SELECT_LINE_IDS = (
    "SELECT line.id FROM region LEFT JOIN line ON line.region_id = region.id"
    " JOIN page ON page.id = region.page_id"
    " WHERE page.ordinal = ? ORDER BY region.reading_index"
)

_UPDATE_LINE = "UPDATE line SET final_en = ?, status = ?, edited_at = ? WHERE id = ?"


def read_review_lines(project: Project, page_ordinal: int) -> tuple[Line | None, ...]:
    """One entry per region of the page, in reading order; `None` for a region
    with no `line` row; `()` for a page with no regions. Opens no transaction.

    Each status is `derive_status` of the stored one, with `page_done` read
    from the page (C-2 rule 3, PO-3).
    """
    rows = project.select(_SELECT_REVIEW, (page_ordinal,))
    if not rows:
        return ()
    page_done = project.page_status(page_ordinal) == PAGE_DONE
    return tuple(
        None
        if line_id is None
        else Line(
            reading_index=int(reading_index),
            source_ja=str(source_ja),
            proposed_en=None if proposed_en is None else str(proposed_en),
            final_en=None if final_en is None else str(final_en),
            status=derive_status(
                None if status is None else str(status),
                ocr_empty=bool(ocr_empty),
                proposed_en=proposed_en,
                page_done=page_done,
            ),
            edited_at=None if edited_at is None else datetime.fromisoformat(str(edited_at)),
            ocr_empty=bool(ocr_empty),
        )
        for (
            reading_index,
            line_id,
            source_ja,
            proposed_en,
            final_en,
            status,
            edited_at,
            ocr_empty,
        ) in rows
    )


def commit_line(
    project: Project,
    page_ordinal: int,
    reading_index: int,
    text: str | None,
    status: LineStatus,
) -> None:
    """Write a user's act to one line: `final_en = text` (`None` is NULL), the
    status, and `edited_at` = now in UTC - in one transaction.

    Refused before anything is written: a status that is not a user act
    (`ValueError`), a reading index not on the page (`ValueError`), and a
    region with no `line` row (`LookupError`). Then, if `text` is not `None`,
    the glossary is reconciled against it (see the module docstring).
    """
    if status not in COMMITTED_STATUSES:
        raise ValueError(
            f"{status!r} is not a user act; commit one of {sorted(COMMITTED_STATUSES)}"
        )
    with project.transaction() as cursor:
        line_ids = [row[0] for row in cursor.execute(_SELECT_LINE_IDS, (page_ordinal,))]
        if not 0 <= reading_index < len(line_ids):
            raise ValueError(
                f"reading index {reading_index} is not on page {page_ordinal}:"
                f" the page has {len(line_ids)} region(s)"
            )
        line_id = line_ids[reading_index]
        if line_id is None:
            raise LookupError(
                f"region {reading_index} of page {page_ordinal} has no line: OCR has not run"
            )
        cursor.execute(_UPDATE_LINE, (text, status, datetime.now(UTC).isoformat(), line_id))
    if text is not None:
        reconcile_from_edit(project, page_ordinal, reading_index, text)
