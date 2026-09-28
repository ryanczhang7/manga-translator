"""`mangatl.store.glossary`: the chapter's glossary on disk, and AC-2.

MT-014 C-6. `read_entries`, `upsert` and `reconcile_from_edit` - the last of
which is **AC-2**: when the user edits a line, the glossary entry it came from
takes the user's wording, *before the next page is translated*. "Before the next
page" is asserted the way the next page would see it, through
`pipeline.continuity.build_prompt_context`.

**The rule is PO-2's single-span diff, and most of this file is its "leave
alone" arms.** A wrong update is worse than no update: it is written with
`source="user"`, outlives every model entry (PO-3) and is never overridden by a
later proposal (C-1's `merge`). So each arm of C-6 that declines to update has
a case here, and most of them would *update* under a looser rule that simply
took the edited line's first changed span:

- step 1, `term_ja` not in `source_ja`: `term-not-in-this-lines-source`;
- step 2, `term_en` occurs 0 or 2+ times: `name-twice-in-proposed`,
  `name-only-inside-a-longer-token`;
- step 3, `term_en` still in the final: `name-kept-other-words-edited`,
  `no-edit-at-all`;
- step 4, not exactly one `replace` equal to the name's range:
  `rewrite-wider-than-the-name`, `rewrite-inside-a-two-word-name`,
  `insertion-inside-a-two-word-name` (an `insert` opcode has an empty
  a-range; whether or not it counts as intersecting, it is not a `replace`),
  `two-replacements-over-one-name`, `name-deleted-outright`,
  `name-deleted-with-its-comma`;
- NULL `proposed_en`: `untranslated-line`.

C-6's tokeniser claims were checked in RED with plain `re` and `difflib` in a
scratch `uv run python` (the module does not exist yet): `"Sakura, wait!"` is
`["Sakura", ",", "wait", "!"]`, `"Sakura-chan, wait!"` is
`["Sakura-chan", ",", "wait", "!"]`, and every case below produces the opcodes
its name says - see the story's `## Handoff: RED -> GREEN` for the table.

The stored rows are read back through `read_entries` *and*, where the column is
the claim, through a plain `sqlite3` connection that imports nothing from
`mangatl.store` (MT-005's convention: a codec that is uniformly wrong round-trips
through itself).

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so
there is no budget in this file to size. Each test builds a two-page chapter of
tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from mangatl.domain.glossary import GlossaryEntry
from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.continuity import build_prompt_context
from mangatl.store.glossary import read_entries, reconcile_from_edit, upsert
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@dataclass(frozen=True)
class _Chapter:
    source_dir: Path
    project: Project
    mask: bytes

    @property
    def db_path(self) -> Path:
        return project_dir_for(self.source_dir) / "project.db"

    def lines(self, ordinal: int, rows: Sequence[tuple[str, str | None]]) -> None:
        """Give page `ordinal` one region per row, its `source_ja`, and its
        `proposed_en` where that is not None (None stays NULL)."""
        regions = tuple(
            RawRegion(
                polygon=_ring(2, 2 + 6 * index, 12, 6 + 6 * index),
                mask=self.mask,
                confidence=0.5,
                kind="bubble",
            )
            for index in range(len(rows))
        )
        self.project.write_regions(ordinal, regions)
        self.project.write_lines(ordinal, [OcrResult(text=source_ja) for source_ja, _ in rows])
        self.project.write_proposed(
            ordinal, {index: english for index, (_, english) in enumerate(rows) if english}
        )


@pytest.fixture
def chapter(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_Chapter]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _Chapter(source_dir, project, one_bit_png(30, 20, [(0, 0, 4, 4)]))


def _raw(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        return list(connection.execute(sql))
    finally:
        connection.close()


# -- read_entries and upsert ---------------------------------------------------


def test_a_new_chapter_has_an_empty_glossary(chapter: _Chapter) -> None:
    """The zero case, and AC-5's store half: page 1 has nothing to read."""
    assert read_entries(chapter.project) == []


def test_an_upserted_entry_reads_back_exactly_with_every_field(chapter: _Chapter) -> None:
    """C-6's round trip. Distinct values in `first_seen_page` and
    `last_seen_page`, so a store that wrote one column into the other is
    caught; `"user"` rather than the column default, so a store that dropped
    `source` on the way in is caught too."""
    entry = GlossaryEntry("さくら", "Sakura-chan", "name", 2, 11, "user")

    upsert(chapter.project, entry)

    assert read_entries(chapter.project) == [entry]
    assert _raw(
        chapter.db_path,
        "SELECT term_ja, term_en, note, first_seen_page, last_seen_page, source FROM glossary",
    ) == [("さくら", "Sakura-chan", "name", 2, 11, "user")]


def test_upserting_an_existing_term_replaces_it_in_place(chapter: _Chapter) -> None:
    """`ON CONFLICT (chapter_id, term_ja)`: one row per term, updated rather
    than duplicated (the UNIQUE key would otherwise raise), and it keeps its
    place in `ORDER BY id`."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))
    upsert(chapter.project, GlossaryEntry("けんじ", "Kenji", "name", 1, 1, "model"))

    upsert(chapter.project, GlossaryEntry("さくら", "Sakura-chan", "honorific", 0, 4, "user"))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura-chan", "honorific", 0, 4, "user"),
        GlossaryEntry("けんじ", "Kenji", "name", 1, 1, "model"),
    ]


def test_entries_come_back_in_the_order_they_were_first_written(chapter: _Chapter) -> None:
    """C-6: `ORDER BY id`. Written in an order that is neither alphabetical nor
    by page, so a store that sorted on either is caught."""
    for entry in (
        GlossaryEntry("東京", "Tokyo", "place", 4, 4, "model"),
        GlossaryEntry("あ組", "Class A", "", 9, 9, "model"),
        GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"),
    ):
        upsert(chapter.project, entry)

    assert [entry.term_ja for entry in read_entries(chapter.project)] == ["東京", "あ組", "さくら"]


def test_a_null_note_reads_back_as_the_empty_note(chapter: _Chapter) -> None:
    """C-7: "`note` stays nullable in SQL; the store reads NULL as `""`." Every
    row written before MT-014 by a writer that left `note` out has NULL there,
    and `render_block` must not print `(None)` for it."""
    with chapter.project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            # `last_seen_page` explicit (R-1): every v5 writer supplies it, and
            # this test is about the NULL `note`, which is left out.
            "INSERT INTO glossary (chapter_id, term_ja, term_en, first_seen_page, last_seen_page)"
            " VALUES (?, ?, ?, ?, ?)",
            (chapter_id, "醜鬼", "Ugly Ogre", 3, 3),
        )

    assert read_entries(chapter.project) == [GlossaryEntry("醜鬼", "Ugly Ogre", "", 3, 3, "model")]


def test_the_glossary_survives_closing_and_reopening_the_project(
    chapter: _Chapter,
) -> None:
    """A glossary held in memory is not a glossary: page 17 of a resumed run
    has to see the names page 3 introduced."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 3, "model"))
    chapter.project.__exit__(None, None, None)  # closes it; closing twice is harmless

    with open_project(project_dir_for(chapter.source_dir)) as reopened:
        assert read_entries(reopened) == [GlossaryEntry("さくら", "Sakura", "name", 0, 3, "model")]


def test_upsert_opens_its_own_transaction_and_refuses_to_nest(chapter: _Chapter) -> None:
    """C-6: "Each function opens its own `project.transaction()`; none is
    called inside another's." `Project.transaction()` is not reentrant
    (MT-005 PO-5), so an upsert inside an open one is a `RuntimeError` - which
    is the observable half of "opens its own"."""
    with pytest.raises(RuntimeError), chapter.project.transaction():
        upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))

    assert read_entries(chapter.project) == []


# -- AC-2: the user's edit becomes the glossary entry ---------------------------


def test_editing_a_name_updates_the_entry_to_the_users_wording(chapter: _Chapter) -> None:
    """**AC-2**, the case the story is written around: "Sakura, wait!" edited
    to "Sakura-chan, wait!". The entry takes "Sakura-chan", becomes a `"user"`
    entry, keeps its note and both of its page numbers (C-6 step 5) - and the
    **next page's** request carries it, which is the criterion's "before the
    next page is translated". DV-3 is this test going red when
    `reconcile_from_edit` is made a no-op.
    """
    chapter.lines(0, [("さくら、待って!", "Sakura, wait!")])
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 3, "model"))

    reconcile_from_edit(chapter.project, 0, 0, "Sakura-chan, wait!")

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura-chan", "name", 0, 3, "user")
    ]
    assert "さくら = Sakura-chan (name)" in build_prompt_context(chapter.project, 1).glossary_block


@pytest.mark.parametrize(
    ("source_ja", "proposed_en", "final_en", "term_ja", "term_en", "expected_en"),
    [
        pytest.param(
            "けんじ、逃げろ!",
            "Kenji, run!",
            "Mr. Tanaka, run!",
            "けんじ",
            "Kenji",
            "Mr. Tanaka",
            id="one-word-name-becomes-two-and-keeps-its-spacing",
        ),
        pytest.param(
            "姉さん、見て!",
            "Big Sis, look!",
            "Onee-chan, look!",
            "姉さん",
            "Big Sis",
            "Onee-chan",
            id="two-word-name-becomes-one",
        ),
        pytest.param(
            "さくら、待って!",
            "Sakura, wait!",
            "Sakura-chan, wait for me!",
            "さくら",
            "Sakura",
            "Sakura-chan",
            id="edits-elsewhere-in-the-line-do-not-block-it",
        ),
        pytest.param(
            "さくら、待って!",
            "Sakura, wait!",
            "Sakura-chan, hold on!",
            "さくら",
            "Sakura",
            "Sakura-chan",
            id="a-second-replacement-elsewhere-does-not-block-it",
        ),
    ],
)
def test_one_replaced_span_exactly_over_the_name_becomes_the_new_rendering(
    chapter: _Chapter,
    source_ja: str,
    proposed_en: str,
    final_en: str,
    term_ja: str,
    term_en: str,
    expected_en: str,
) -> None:
    """C-6 step 5: the new `term_en` is `final_en[start:end]`, from the first
    replacement token's start to the last one's end - so "Mr. Tanaka" keeps
    its full stop and its space rather than being rebuilt as "Mr . Tanaka" or
    "Mr.Tanaka" from tokens. And "edits elsewhere in the line do not block the
    rule; only the opcode touching the name matters"."""
    chapter.lines(0, [(source_ja, proposed_en)])
    upsert(chapter.project, GlossaryEntry(term_ja, term_en, "name", 1, 2, "model"))

    reconcile_from_edit(chapter.project, 0, 0, final_en)

    assert read_entries(chapter.project) == [
        GlossaryEntry(term_ja, expected_en, "name", 1, 2, "user")
    ]


def test_one_edit_can_update_two_names_in_the_same_line(chapter: _Chapter) -> None:
    """C-6: "for **every** entry whose `term_ja` is a substring of
    `source_ja`". Two names, two replacements, each exactly over its own name;
    the entry not in this line is untouched and stays a model entry."""
    chapter.lines(0, [("さくらとけんじは帰った。", "Sakura and Kenji left.")])
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))
    upsert(chapter.project, GlossaryEntry("東京", "Tokyo", "place", 0, 0, "model"))
    upsert(chapter.project, GlossaryEntry("けんじ", "Kenji", "name", 0, 0, "model"))

    reconcile_from_edit(chapter.project, 0, 0, "Sakura-chan and Kenji-kun left.")

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura-chan", "name", 0, 0, "user"),
        GlossaryEntry("東京", "Tokyo", "place", 0, 0, "model"),
        GlossaryEntry("けんじ", "Kenji-kun", "name", 0, 0, "user"),
    ]


def test_the_edit_is_read_from_the_line_it_addresses_and_no_other(chapter: _Chapter) -> None:
    """C-6's `(page_ordinal, reading_index)` addressing. Three lines mention
    さくら; only page 1, reading index 0 is edited, and its proposed English is
    the only one against which "Where is Sakura-chan going?" is a single
    replacement over the name. Reading page 0's first line instead - the
    `0` typo MT-035 DV-3 warns about - diffs against "Sakura, wait!" and
    leaves the entry alone."""
    chapter.lines(0, [("さくら、待って!", "Sakura, wait!"), ("さくら?違う。", "Sakura? No.")])
    chapter.lines(1, [("さくらはどこへ?", "Where is Sakura going?")])
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 1, "model"))

    reconcile_from_edit(chapter.project, 1, 0, "Where is Sakura-chan going?")

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura-chan", "name", 0, 1, "user")
    ]


def test_the_reading_index_is_honoured_as_well_as_the_page(chapter: _Chapter) -> None:
    """The same, on the other coordinate: page 0, reading index **1**."""
    chapter.lines(0, [("さくら、待って!", "Sakura, wait!"), ("さくら?違う。", "Sakura? No.")])
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))

    reconcile_from_edit(chapter.project, 0, 1, "Sakura-san? No.")

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura-san", "name", 0, 0, "user")
    ]


@pytest.mark.parametrize(
    ("source_ja", "proposed_en", "final_en", "term_ja", "term_en"),
    [
        pytest.param(
            "さくら、待って!",
            "Kenji, wait!",
            "Kenji-kun, wait!",
            "けんじ",
            "Kenji",
            id="term-not-in-this-lines-source",
        ),
        pytest.param(
            "さくら?さくら!",
            "Sakura? Sakura!",
            "Sakura-chan? Sakura!",
            "さくら",
            "Sakura",
            id="name-twice-in-proposed",
        ),
        pytest.param(
            "さくら、待って!",
            "Sakura-chan, wait!",
            "Sakura-san, wait!",
            "さくら",
            "Sakura",
            id="name-only-inside-a-longer-token",
        ),
        pytest.param(
            "さくら、待って!",
            "Sakura, wait!",
            "Sakura, wait up!",
            "さくら",
            "Sakura",
            id="name-kept-other-words-edited",
        ),
        pytest.param(
            "さくら、待って!",
            "Sakura, wait!",
            "Sakura, wait!",
            "さくら",
            "Sakura",
            id="no-edit-at-all",
        ),
        pytest.param(
            "さくら待って!",
            "Sakura wait!",
            "Stop right there!",
            "さくら",
            "Sakura",
            id="rewrite-wider-than-the-name",
        ),
        pytest.param(
            "姉さん、見て!",
            "Big Sis, look!",
            "Big dear Sister, look!",
            "姉さん",
            "Big Sis",
            id="rewrite-inside-a-two-word-name",
        ),
        pytest.param(
            "姉さん、見て!",
            "Big Sis, look!",
            "Big dear Sis, look!",
            "姉さん",
            "Big Sis",
            id="insertion-inside-a-two-word-name",
        ),
        pytest.param(
            "姉さんアイ、見て!",
            "Big Sis Ai, look!",
            "Great Sis Aiko, look!",
            "姉さんアイ",
            "Big Sis Ai",
            id="two-replacements-over-one-name",
        ),
        pytest.param(
            "さくら、待って!",
            "Sakura, wait!",
            ", wait!",
            "さくら",
            "Sakura",
            id="name-deleted-outright",
        ),
        pytest.param(
            "さくら、待って!",
            "Sakura, wait!",
            "wait!",
            "さくら",
            "Sakura",
            id="name-deleted-with-its-comma",
        ),
        pytest.param(
            "さくら、待って!",
            None,
            "Sakura-chan, wait!",
            "さくら",
            "Sakura",
            id="untranslated-line",
        ),
    ],
)
def test_an_edit_the_single_span_rule_cannot_read_leaves_the_entry_alone(
    chapter: _Chapter,
    source_ja: str,
    proposed_en: str | None,
    final_en: str,
    term_ja: str,
    term_en: str,
) -> None:
    """PO-2: "The rule updates only when one replaced span maps exactly onto
    the name, and leaves the entry alone otherwise. A wrong update would be
    worse than no update." Each case is one arm of C-6 (see the module
    docstring's table); the entry must come back **exactly** as it went in -
    same rendering, still `"model"`, same pages - and nothing must raise."""
    chapter.lines(0, [(source_ja, proposed_en)])
    before = GlossaryEntry(term_ja, term_en, "name", 0, 2, "model")
    upsert(chapter.project, before)

    reconcile_from_edit(chapter.project, 0, 0, final_en)

    assert read_entries(chapter.project) == [before]
