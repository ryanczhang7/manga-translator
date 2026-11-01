"""MT-103 AC-5: `mangatl.store.corrections`, what the consistency pass changed.

The consistency pass (MT-115) rereads a chapter's translation and changes
lines that disagree with each other. The user must be able to see what it
changed, from what, and why, so each change is a `correction` row: the run, the
page, the line's reading index, the English before and after, and the reason.
Applying a correction to `line.proposed_en` is MT-115's, not this story's
(`## Out of scope`).

Two things are silent if got wrong, and both are pinned:

- **the page is stored as `page.id` and read back as the ordinal.** The ordinal
  is the page's identity for the whole product (MT-004) and is what callers
  hold; `correction.page_id` is a foreign key. Ordinal 0 is `page.id` 1 on a
  fresh project, so a store that wrote the ordinal into `page_id` points at the
  wrong page - read here with a plain `sqlite3` reader - and on the last page
  points at none.
- **`reading_index` order, not insertion order.** The corrections below are
  recorded out of order, so a SELECT without an `ORDER BY` - which happens to
  come back in rowid order - cannot pass.

**Timing.** No `pytest-timeout` in this project; each test builds a three-page
chapter on `tmp_path`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mangatl.domain.correction import Correction
from mangatl.store.corrections import corrections_for, record_correction
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for

#: Page 1's corrections, recorded in THIS order - not reading order:
#: (reading_index, before_en, after_en, reason).
_PAGE_ONE: tuple[tuple[int, str, str, str], ...] = (
    (2, "Senpai!", "Senpai!!", "matches the shout on page 0"),
    (0, "Tanaka-san", "Tanaka", "honorific dropped consistently after page 0"),
    (1, "It's the guild.", "It's the Guild.", "glossary: ギルド -> Guild"),
)


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    folder = tmp_path / "chapter"
    folder.mkdir()
    for name in ("p1.png", "p2.png", "p3.png"):
        (folder / name).write_bytes(png_bytes(8, 6))
    return folder


@pytest.fixture
def project(source_dir: Path) -> Iterator[Project]:
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as opened:
        yield opened


@pytest.fixture
def db_path(source_dir: Path) -> Path:
    return project_dir_for(source_dir) / "project.db"


@pytest.fixture
def run_id(project: Project) -> int:
    with project.transaction() as cursor:
        chapter_id = cursor.execute("SELECT id FROM chapter").fetchone()[0]
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-10-31T09:00:00+00:00"),
        )
        return int(cursor.lastrowid or 0)


def _record_page_one(project: Project, run_id: int) -> None:
    for reading_index, before_en, after_en, reason in _PAGE_ONE:
        record_correction(project, run_id, 1, reading_index, before_en, after_en, reason)


def test_a_recorded_correction_is_a_row_on_that_page(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**AC-5**: `record_correction` writes a row - against `page.id` of
    ordinal 1, not the number 1 - carrying the run, the reading index, the
    four strings and a UTC timestamp of now."""
    before = datetime.now(UTC)
    record_correction(project, run_id, 1, 0, "Tanaka-san", "Tanaka", "honorific")
    after = datetime.now(UTC)

    rows = _raw(
        db_path,
        "SELECT correction.run_id, page.ordinal, correction.reading_index,"
        " correction.before_en, correction.after_en, correction.reason, correction.at"
        " FROM correction JOIN page ON page.id = correction.page_id",
    )
    assert [row[:6] for row in rows] == [(run_id, 1, 0, "Tanaka-san", "Tanaka", "honorific")]
    stamped = datetime.fromisoformat(str(rows[0][6]))
    assert stamped.utcoffset() == UTC.utcoffset(None), rows[0][6]
    assert before <= stamped <= after


def test_a_pages_corrections_come_back_in_reading_order_with_the_run_and_all_four_strings(
    project: Project, run_id: int
) -> None:
    """**AC-5**: `corrections_for(project, 1)` is page 1's corrections in
    `reading_index` order - recorded 2, 0, 1 - each a `Correction` carrying the
    run id, the page ordinal, and before, after and reason verbatim."""
    _record_page_one(project, run_id)

    assert corrections_for(project, 1) == tuple(
        Correction(
            run_id=run_id,
            page_ordinal=1,
            reading_index=reading_index,
            before_en=before_en,
            after_en=after_en,
            reason=reason,
        )
        for reading_index, before_en, after_en, reason in sorted(_PAGE_ONE)
    )


def test_a_pages_corrections_exclude_every_other_pages(project: Project, run_id: int) -> None:
    """Many pages: corrections on pages 0 and 2 do not leak into page 1's, and
    page 1's do not leak into theirs."""
    record_correction(project, run_id, 0, 0, "Hey.", "Hey!", "page 0's own")
    _record_page_one(project, run_id)
    record_correction(project, run_id, 2, 3, "Bye.", "Later.", "page 2's own")

    assert [c.reading_index for c in corrections_for(project, 1)] == [0, 1, 2]
    assert corrections_for(project, 0) == (
        Correction(run_id, 0, 0, "Hey.", "Hey!", "page 0's own"),
    )
    assert corrections_for(project, 2) == (
        Correction(run_id, 2, 3, "Bye.", "Later.", "page 2's own"),
    )


def test_a_page_with_no_corrections_returns_an_empty_tuple(project: Project, run_id: int) -> None:
    """**AC-5**: `()`, not `None` and not a list - on an empty table and on a
    page that has none while another page does."""
    assert corrections_for(project, 0) == ()

    _record_page_one(project, run_id)

    assert corrections_for(project, 0) == ()
    assert corrections_for(project, 2) == ()


def test_a_correction_carries_the_run_that_made_it(project: Project, run_id: int) -> None:
    """Two runs correct the same page: each correction keeps its own run id,
    so a reader can tell this run's changes from a previous one's."""
    _record_page_one(project, run_id)
    with project.transaction() as cursor:
        chapter_id = cursor.execute("SELECT id FROM chapter").fetchone()[0]
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-10-31T11:00:00+00:00"),
        )
        later = int(cursor.lastrowid or 0)
    record_correction(project, later, 1, 5, "Run.", "Run!", "second pass")

    assert [(c.run_id, c.reading_index) for c in corrections_for(project, 1)] == [
        (run_id, 0),
        (run_id, 1),
        (run_id, 2),
        (later, 5),
    ]


def test_corrections_survive_a_reopen(project: Project, source_dir: Path, run_id: int) -> None:
    """They are on disk, not in memory: a second connection to the same file
    reads them back while the first is still open."""
    _record_page_one(project, run_id)
    expected = corrections_for(project, 1)

    with open_project(project_dir_for(source_dir)) as reopened:
        assert corrections_for(reopened, 1) == expected
    assert len(expected) == len(_PAGE_ONE)
