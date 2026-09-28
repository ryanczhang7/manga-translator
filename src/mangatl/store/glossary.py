"""The chapter's glossary on disk, and the user's edit reaching it (MT-014 C-6).

One project file is one chapter, so nothing here filters on `chapter_id` - the
same reason `store.ledger`'s totals carry no `WHERE chapter_id`. Each function
opens its own `project.transaction()` and none calls another inside one:
`Project.transaction()` is not reentrant (MT-005 PO-5).

**`reconcile_from_edit` is PO-2's single-span rule, and it is conservative on
purpose.** A wrong update is worse than none: it is stored as `source="user"`,
outlives every model entry (PO-3) and is never overridden by a later proposal
(`domain.glossary.merge`). So the entry takes the user's wording only when the
edit is one `replace` whose proposed-side range is exactly the name's tokens;
anything else - the name twice, the name kept, a rewrite wider or narrower than
it, an insertion inside it, a deletion - leaves the entry alone.
"""

from __future__ import annotations

import re
import sqlite3
from difflib import SequenceMatcher

from mangatl.domain.glossary import GlossaryEntry, Source
from mangatl.store.project import Project

__all__ = ["read_entries", "reconcile_from_edit", "upsert"]

#: C-6 step 1. A word with internal hyphens or apostrophes is one token -
#: "Sakura-chan" - and every other non-space character is a token of its own,
#: so "Sakura," is `["Sakura", ","]`. The joiners are C-6's hyphen, apostrophe
#: and typographic apostrophe (U+2019), the last written as a regex escape so
#: that it cannot be mistaken for a grave accent.
_TOKEN = re.compile(r"\w+(?:[-'\N{RIGHT SINGLE QUOTATION MARK}]\w+)*|[^\w\s]")

# `ORDER BY id`: first written first, which a SELECT without it only happens
# to return.
_SELECT_ENTRIES = (
    "SELECT term_ja, term_en, note, first_seen_page, last_seen_page, source"
    " FROM glossary ORDER BY id"
)

# `ON CONFLICT (chapter_id, term_ja)` matches the table's UNIQUE key, and an
# update rather than `INSERT OR REPLACE` keeps the row's id - and so its place
# in `ORDER BY id`.
_UPSERT_ENTRY = (
    "INSERT INTO glossary"
    " (chapter_id, term_ja, term_en, note, first_seen_page, last_seen_page, source)"
    " VALUES ((SELECT id FROM chapter), ?, ?, ?, ?, ?, ?)"
    " ON CONFLICT (chapter_id, term_ja) DO UPDATE SET"
    " term_en = excluded.term_en, note = excluded.note,"
    " first_seen_page = excluded.first_seen_page,"
    " last_seen_page = excluded.last_seen_page, source = excluded.source"
)

_SELECT_LINE = (
    "SELECT line.source_ja, line.proposed_en"
    " FROM line JOIN region ON region.id = line.region_id"
    " JOIN page ON page.id = region.page_id"
    " WHERE page.ordinal = ? AND region.reading_index = ?"
)


def read_entries(project: Project) -> list[GlossaryEntry]:
    """Every entry, in the order it was first written. A NULL `note` - every
    row a pre-MT-014 writer left it out of - reads as `""`."""
    with project.transaction() as cursor:
        return _entries(cursor)


def upsert(project: Project, entry: GlossaryEntry) -> None:
    """Write `entry`, replacing the row for its `term_ja` in place if there is
    one."""
    with project.transaction() as cursor:
        _upsert(cursor, entry)


def reconcile_from_edit(
    project: Project, page_ordinal: int, reading_index: int, final_en: str
) -> None:
    """Give every glossary term in the edited line the user's wording, where
    the single-span rule can read it (AC-2, PO-2).

    The line is addressed as `write_proposed` and `read_proposed` address it.
    It is only *given* `final_en`: writing the edit to the line is MT-017's.
    """
    with project.transaction() as cursor:
        source_ja, proposed_en = cursor.execute(
            _SELECT_LINE, (page_ordinal, reading_index)
        ).fetchone()
        if proposed_en is None:
            return
        for entry in _entries(cursor):
            if entry.term_ja not in source_ja:
                continue
            term_en = _renamed(entry.term_en, str(proposed_en), final_en)
            if term_en is not None:
                _upsert(
                    cursor,
                    GlossaryEntry(
                        entry.term_ja,
                        term_en,
                        entry.note,
                        entry.first_seen_page,
                        entry.last_seen_page,
                        "user",
                    ),
                )


def _renamed(term_en: str, proposed_en: str, final_en: str) -> str | None:
    """The user's rendering of `term_en`, or `None` when the edit is not one
    replaced span exactly over it (C-6 steps 2-5)."""
    name = _TOKEN.findall(term_en)
    proposed = _TOKEN.findall(proposed_en)
    final = list(_TOKEN.finditer(final_en))
    final_tokens = [match.group() for match in final]

    # Step 2: the name occurs exactly once in what the model proposed.
    starts = _occurrences(name, proposed)
    if len(starts) != 1:
        return None
    # Step 3: the user kept it.
    if _occurrences(name, final_tokens):
        return None
    # Step 4: one non-`equal` opcode touches the name, a `replace` over exactly it.
    start, end = starts[0], starts[0] + len(name)
    touching = [
        opcode
        for opcode in SequenceMatcher(None, proposed, final_tokens, autojunk=False).get_opcodes()
        if opcode[0] != "equal" and opcode[1] < end and start < opcode[2]
    ]
    if len(touching) != 1:
        return None
    tag, i1, i2, j1, j2 = touching[0]
    if tag != "replace" or (i1, i2) != (start, end):
        return None
    # Step 5: the substring, so "Mr. Tanaka" keeps its spacing.
    return final_en[final[j1].start() : final[j2 - 1].end()]


def _occurrences(needle: list[str], haystack: list[str]) -> list[int]:
    width = len(needle)
    return [
        index
        for index in range(len(haystack) - width + 1)
        if haystack[index : index + width] == needle
    ]


def _entries(cursor: sqlite3.Cursor) -> list[GlossaryEntry]:
    return [
        GlossaryEntry(
            term_ja=str(term_ja),
            term_en=str(term_en),
            note="" if note is None else str(note),
            first_seen_page=int(first_seen_page),
            last_seen_page=int(last_seen_page),
            source=_source(str(source)),
        )
        for term_ja, term_en, note, first_seen_page, last_seen_page, source in cursor.execute(
            _SELECT_ENTRIES
        ).fetchall()
    ]


def _source(value: str) -> Source:
    # The column's CHECK admits only these two values.
    return "user" if value == "user" else "model"


def _upsert(cursor: sqlite3.Cursor, entry: GlossaryEntry) -> None:
    cursor.execute(
        _UPSERT_ENTRY,
        (
            entry.term_ja,
            entry.term_en,
            entry.note,
            entry.first_seen_page,
            entry.last_seen_page,
            entry.source,
        ),
    )
