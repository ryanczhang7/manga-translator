"""MT-017 C-6: `mangatl.store.lines` - reading a page's lines for review, and
committing a user's act to one of them.

Two conventions inherited from MT-005/MT-007/MT-010's store suites, because
their reasons were measured:

- **What `commit_line` wrote is observed with a plain `sqlite3` connection**,
  which imports nothing from `mangatl.store`. A codec that is uniformly wrong
  round-trips through itself perfectly; a second connection seeing the row is
  also what "on disk" means for AC-1 and AC-6.
- **The round trip is asserted against a project reopened from the path**, the
  writer closed first.

AC-2's "exactly" reaches the store too (C-6: "does not normalise or otherwise
alter `text`"), so the committed strings here deliberately differ from their own
O2-normalised form - a double space, a trailing space, an NFD accent.

The MT-014 obligation (`## Notes`): a commit that carries text must call
`store.glossary.reconcile_from_edit`, **after** its own transaction has
committed (`Project.transaction()` is not reentrant, so calling it inside would
raise). Asserted by its effect - the glossary entry takes the user's wording and
`source="user"` - never by spying on the call.

**Timing.** No `pytest-timeout` in this project; tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mangatl.domain.glossary import GlossaryEntry
from mangatl.domain.line import Line, OcrResult
from mangatl.domain.region import RawRegion
from mangatl.store.glossary import read_entries, upsert
from mangatl.store.intake import read_chapter
from mangatl.store.lines import commit_line, read_review_lines
from mangatl.store.project import (
    PAGE_DONE,
    Project,
    create_project,
    open_project,
    project_dir_for,
)

_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 30, 20),
    ("p3.png", 30, 20),
)

#: Page 0's lines, in reading order: `(source_ja, ocr_empty, proposed_en)`.
#: Translated; untranslated; ocr_empty; translated with a proposal whose O2
#: form differs from itself (double space, trailing space).
_PAGE0: tuple[tuple[str, bool, str | None], ...] = (
    ("さくら、待って!", False, "Sakura, wait!"),
    ("なるほど", False, None),
    ("", True, None),
    ("またね", False, "See  you. "),
)

#: A string whose O2-normalised form is not itself: a character-for-character
#: store is the only one that returns it unchanged.
_UNNORMAL = "  Cafe\u0301  au  lait "


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    directory = tmp_path / "scans"
    directory.mkdir()
    for filename, width, height in _PAGES:
        (directory / filename).write_bytes(png_bytes(width, height))
    return directory


@pytest.fixture
def project(source_dir: Path, one_bit_png: Callable[..., bytes]) -> Iterator[Project]:
    """Page 0: four regions with lines (`_PAGE0`). Page 1: two regions, no
    lines (OCR has not run). Page 2: no regions."""
    mask = one_bit_png(30, 20, [(0, 0, 4, 4)])
    ring = ((0, 0), (4, 0), (4, 4), (0, 4), (0, 0))
    region = RawRegion(polygon=ring, mask=mask, confidence=0.9, kind="bubble")
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as opened:
        opened.write_regions(0, [region] * len(_PAGE0))
        opened.write_lines(0, [OcrResult(ja, ocr_empty=empty) for ja, empty, _ in _PAGE0])
        opened.write_proposed(0, {i: en for i, (_, _, en) in enumerate(_PAGE0) if en is not None})
        opened.write_regions(1, [region, region])
        yield opened


def _db(source_dir: Path) -> Path:
    return project_dir_for(source_dir) / "project.db"


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _stored(source_dir: Path, ordinal: int = 0) -> list[tuple[object, ...]]:
    """`(reading_index, final_en, status, edited_at)` for every line of a page,
    read by a connection that is not the project's."""
    return _raw(
        _db(source_dir),
        "SELECT region.reading_index, line.final_en, line.status, line.edited_at"
        " FROM line JOIN region ON region.id = line.region_id"
        " JOIN page ON page.id = region.page_id"
        " WHERE page.ordinal = ? ORDER BY region.reading_index",
        (ordinal,),
    )


def _mark_done(project: Project, ordinal: int) -> None:
    with project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ? WHERE ordinal = ?", (PAGE_DONE, ordinal))


# =============================================================================
# read_review_lines
# =============================================================================


def test_a_page_reads_back_one_line_per_region_in_reading_order_with_every_field(
    project: Project,
) -> None:
    lines = read_review_lines(project, 0)

    assert lines == (
        Line(0, "さくら、待って!", "Sakura, wait!", None, "proposed", None, False),
        Line(1, "なるほど", None, None, "proposed", None, False),
        Line(2, "", None, None, "failed", None, True),
        Line(3, "またね", "See  you. ", None, "proposed", None, False),
    )


def test_an_untranslated_line_is_failed_only_once_the_run_has_finished_its_page(
    project: Project,
) -> None:
    """C-2 rule 3 / PO-3: NULL `proposed_en` on a page the run has not reached is
    `proposed`; on a `done` page it is MT-011 AC-5's untranslated region."""
    before = [line.status for line in read_review_lines(project, 0) if line]
    _mark_done(project, 0)
    after = [line.status for line in read_review_lines(project, 0) if line]

    assert before == ["proposed", "proposed", "failed", "proposed"]
    assert after == ["proposed", "failed", "failed", "proposed"]


def test_a_region_whose_ocr_has_not_run_reads_back_as_none(project: Project) -> None:
    assert read_review_lines(project, 1) == (None, None)


def test_a_page_with_no_regions_reads_back_empty(project: Project) -> None:
    assert read_review_lines(project, 2) == ()


def test_reading_lines_opens_no_transaction(project: Project) -> None:
    """A caller already holding one can still ask what is stored."""
    with project.transaction():
        assert len(read_review_lines(project, 0)) == len(_PAGE0)


# =============================================================================
# commit_line - what lands on disk
# =============================================================================


def test_an_edit_is_on_disk_character_for_character_with_its_status_and_a_utc_time(
    project: Project, source_dir: Path
) -> None:
    before = datetime.now(UTC)
    commit_line(project, 0, 1, _UNNORMAL, "edited")
    after = datetime.now(UTC)

    reading_index, final_en, status, edited_at = _stored(source_dir)[1]
    assert (reading_index, final_en, status) == (1, _UNNORMAL, "edited")
    stamp = datetime.fromisoformat(str(edited_at))
    assert stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0
    assert before <= stamp <= after


def test_an_accept_stores_a_null_final_text_and_the_accepted_status(
    project: Project, source_dir: Path
) -> None:
    commit_line(project, 0, 0, None, "accepted")

    _index, final_en, status, edited_at = _stored(source_dir)[0]
    assert (final_en, status) == (None, "accepted")
    assert edited_at is not None, "C-6: edited_at is the time of the last commit, any status"


def test_a_revert_stores_the_proposal_exactly_and_the_reverted_status(
    project: Project, source_dir: Path
) -> None:
    commit_line(project, 0, 3, "See you.", "edited")
    commit_line(project, 0, 3, "See  you. ", "reverted")

    assert _stored(source_dir)[3][1:3] == ("See  you. ", "reverted")


def test_a_commit_touches_only_its_own_line(project: Project, source_dir: Path) -> None:
    commit_line(project, 0, 1, "Mine.", "edited")

    rows = _stored(source_dir)
    assert [row[1:3] for row in rows] == [
        (None, None),
        ("Mine.", "edited"),
        (None, None),
        (None, None),
    ]


def test_every_committed_status_and_text_comes_back_from_a_reopened_project(
    project: Project, source_dir: Path
) -> None:
    """The store half of AC-6: every status a user can write, plus a derived
    `proposed` and a derived `failed`, survive closing and reopening."""
    commit_line(project, 0, 0, None, "accepted")
    commit_line(project, 0, 1, _UNNORMAL, "edited")
    commit_line(project, 0, 3, "See  you. ", "reverted")
    project.__exit__(None, None, None)

    with open_project(project_dir_for(source_dir)) as reopened:
        lines = read_review_lines(reopened, 0)

    assert [(line.status, line.final_en) for line in lines if line] == [
        ("accepted", None),
        ("edited", _UNNORMAL),
        ("failed", None),
        ("reverted", "See  you. "),
    ]
    stamps = [line.edited_at for line in lines if line]
    assert stamps[2] is None
    for stamp in (stamps[0], stamps[1], stamps[3]):
        assert stamp is not None
        assert stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0


def test_a_user_edit_on_an_ocr_empty_line_reads_back_as_edited_not_failed(
    project: Project,
) -> None:
    """C-2 rule 1 / PO-5: the user's act outranks the pipeline's flag."""
    commit_line(project, 0, 2, "Hmph.", "edited")

    line = read_review_lines(project, 0)[2]
    assert line is not None
    assert (line.status, line.final_en, line.ocr_empty) == ("edited", "Hmph.", True)


# =============================================================================
# commit_line - refusals, all before anything is written
# =============================================================================


@pytest.mark.parametrize("status", ["proposed", "failed", "banana"])
def test_committing_a_status_that_is_not_a_user_act_is_refused_and_writes_nothing(
    project: Project, source_dir: Path, status: str
) -> None:
    before = _stored(source_dir)
    with pytest.raises(ValueError):
        commit_line(project, 0, 0, "Anything.", status)  # type: ignore[arg-type]
    assert _stored(source_dir) == before


@pytest.mark.parametrize("reading_index", [-1, len(_PAGE0)])
def test_committing_to_a_reading_index_not_on_the_page_is_refused_and_writes_nothing(
    project: Project, source_dir: Path, reading_index: int
) -> None:
    before = _stored(source_dir)
    with pytest.raises(ValueError):
        commit_line(project, 0, reading_index, "Anything.", "edited")
    assert _stored(source_dir) == before


def test_committing_to_a_region_with_no_line_row_is_a_lookup_error(
    project: Project, source_dir: Path
) -> None:
    with pytest.raises(LookupError):
        commit_line(project, 1, 0, "Anything.", "edited")
    assert _raw(_db(source_dir), "SELECT count(*) FROM line") == [(len(_PAGE0),)]


# =============================================================================
# The MT-014 obligation: a committed rewording reaches the glossary
# =============================================================================


def test_a_commit_that_renames_a_glossary_term_gives_the_entry_the_users_wording(
    project: Project,
) -> None:
    """MT-014 AC-2 made true of the app: `commit_line` calls
    `reconcile_from_edit` after its transaction commits. Line 0 proposes
    "Sakura, wait!" for "さくら、待って!"; the user writes "Sakura-chan"."""
    upsert(project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))

    commit_line(project, 0, 0, "Sakura-chan, wait!", "edited")

    assert read_entries(project) == [GlossaryEntry("さくら", "Sakura-chan", "name", 0, 0, "user")]


def test_an_accept_carries_no_text_and_leaves_the_glossary_alone(project: Project) -> None:
    upsert(project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))

    commit_line(project, 0, 0, None, "accepted")

    assert read_entries(project) == [GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model")]
