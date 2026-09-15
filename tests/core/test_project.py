"""`mangatl.store.project`: creating, reopening and resuming a chapter project.

Covers AC-1 (the file, its version and every page row written exactly), AC-2
(the round trip, asserted only against a fresh `open_project`), AC-3
(`SchemaTooNew`, plus the two ways sqlite3 creates a file behind you), AC-4
(per-page invalidation, and the three pages that must survive it), AC-5
(rollback on an injected failure, and the non-reentrancy guard that makes it
mean something), AC-6 (the region upsert and the live cascade it depends on)
and AC-7 (the sibling location, and that nothing in the source folder moves).

Three conventions here are load-bearing rather than stylistic:

- **AC-1's assertions are taken with a plain `sqlite3` connection**, never
  through `Project`. A codec that is uniformly wrong round-trips through itself
  perfectly (`tdd-cycle`, "a mutation is only as informative as the
  independence of what observes it"), so the write path is observed by a reader
  that imports nothing from `mangatl.store`.
- **AC-2, AC-4 and AC-5 assert against a project reopened from the path.** The
  object `create_project` returned is closed first and never consulted
  afterwards; `story-authoring`'s warning about round trips is that an
  implementation which never reads back part of what it wrote passes a
  same-object assertion.
- **Every stage-shaped write is raw SQL through `project.transaction()`.** This
  story ships no stage-write helper and deliberately so (`## Contract` PO-3),
  so the column lists below are this suite's statement of the schema §4 and
  PO-3 require.

Import layout note (`## Contract` PO-9): `mangatl.store.project` and
`mangatl.store.schema` do not exist during RED, so ruff reads them as
third-party and raises I001 against the single first-party block below. That is
the expected, named, RED-only lint failure recorded in `## Handoff`; GREEN's
`known-first-party = ["mangatl"]` removes it. The block is written in its
post-fix form on purpose and must not be reflowed.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import pytest

from mangatl.domain.page import Chapter
from mangatl.store.intake import NoPagesFound, read_chapter
from mangatl.store.project import (
    PAGE_PENDING,
    PAGE_STALE,
    SCHEMA_VERSION,
    Project,
    ProjectExists,
    SchemaTooNew,
    create_project,
    open_project,
    project_dir_for,
)
from mangatl.store.schema import DDL

# -- the fixture chapter -------------------------------------------------------

# Four pages, four DISTINCT non-square sizes, and no size that is another's
# transposition: a width/height swap, or a value read from the wrong column,
# cannot survive AC-1 against this chapter. `## Contract` PO-2 of MT-004 pins
# the recipe; `conftest.py` builds the bytes with the standard library only.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 11),
    ("p4.png", 23, 17),
)

# The scan that replaces p3.png in AC-4. A different size as well as different
# bytes, so PO-6's "its sha256 AND its width/height are updated" has two
# independent things to be true about.
_REPLACEMENT_SIZE = (31, 7)

# The seven tables of `architecture.md` §4 and the columns it names. Asserted as
# a SUBSET of what the schema carries: an extra column is the implementer's
# choice, a missing one is a defect that AC-4 and AC-6 would otherwise report as
# an OperationalError from somewhere unrelated.
_SCHEMA_COLUMNS: dict[str, frozenset[str]] = {
    "chapter": frozenset(
        {
            "id",
            "source_dir",
            "output_dir",
            "created_at",
            "schema_version",
            "budget_ceiling_usd",
            "model_id",
            "rate_table_version",
        }
    ),
    "page": frozenset(
        {"id", "chapter_id", "ordinal", "filename", "width", "height", "sha256", "status"}
    ),
    "region": frozenset(
        {
            "id",
            "page_id",
            "reading_index",
            "polygon",
            "mask_blob",
            "kind",
            "confidence",
            "merged_from",
        }
    ),
    "line": frozenset(
        {"id", "region_id", "source_ja", "proposed_en", "final_en", "edited_at", "viewed_at"}
    ),
    "run": frozenset({"id", "chapter_id", "started_at", "ended_at", "outcome", "aborted_reason"}),
    "llm_call": frozenset(
        {
            "id",
            "run_id",
            "page_id",
            "request_id",
            "model_id",
            "input_tokens",
            "output_tokens",
            "cache_write_tokens",
            "cache_read_tokens",
            "cost_usd",
            "at",
        }
    ),
    "glossary": frozenset({"id", "chapter_id", "term_ja", "term_en", "note", "first_seen_page"}),
}

_TABLES: tuple[str, ...] = tuple(_SCHEMA_COLUMNS)

# -- the stage-shaped write statements ----------------------------------------

# The three region writes differ ONLY in their conflict handling, which is
# exactly the contrast `## Contract` PO-3 measured: against a region with a line
# attached, `OR REPLACE` leaves `line rows: 0` and the upsert leaves
# `line rows: 1`.
_REGION_COLUMNS = (
    " (page_id, reading_index, polygon, mask_blob, kind, confidence, merged_from)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)
_INSERT_REGION = "INSERT INTO region" + _REGION_COLUMNS
_REPLACE_REGION = "INSERT OR REPLACE INTO region" + _REGION_COLUMNS
_UPSERT_REGION = (
    "INSERT INTO region" + _REGION_COLUMNS + " ON CONFLICT (page_id, reading_index) DO UPDATE SET"
    "   polygon = excluded.polygon,"
    "   mask_blob = excluded.mask_blob,"
    "   kind = excluded.kind,"
    "   confidence = excluded.confidence,"
    "   merged_from = excluded.merged_from"
)

# `final_en`, `edited_at` and `viewed_at` are passed as NULL: §4 says a NULL
# `final_en` is what "unedited" means, and an unedited line has no edit time and
# no view time either, so a writer forced to invent one would be storing a lie.
# All three must therefore be nullable.
_INSERT_LINE = (
    "INSERT INTO line (region_id, source_ja, proposed_en, final_en, edited_at, viewed_at)"
    " VALUES (?, ?, ?, ?, ?, ?)"
)
_INSERT_PAGE = (
    "INSERT INTO page (chapter_id, ordinal, filename, width, height, sha256, status)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)
_INSERT_GLOSSARY = (
    "INSERT INTO glossary (chapter_id, term_ja, term_en, note, first_seen_page)"
    " VALUES (?, ?, ?, ?, ?)"
)
_INSERT_RUN = (
    "INSERT INTO run (chapter_id, started_at, ended_at, outcome, aborted_reason)"
    " VALUES (?, ?, ?, ?, ?)"
)
_INSERT_LLM_CALL = (
    "INSERT INTO llm_call (run_id, page_id, request_id, model_id, input_tokens,"
    " output_tokens, cache_write_tokens, cache_read_tokens, cost_usd, at)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


class _InjectedFailure(Exception):
    """AC-5's simulated crash. A bespoke type so the test cannot pass by
    catching a real `sqlite3` error raised for some other reason."""


class _Built(NamedTuple):
    """A source folder read into a `Chapter`, with nowhere created yet."""

    source_dir: Path
    project_dir: Path
    chapter: Chapter

    @property
    def db_path(self) -> Path:
        return self.project_dir / "project.db"


# -- helpers -------------------------------------------------------------------


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of file contents, or None for a directory.

    The same shape as `test_intake.py`'s, and duplicated rather than shared for
    the same reason it was written there: directories are included, not just
    files, so AC-7 catches a *directory* appearing under the source folder as
    well as a file being created, edited or removed.
    """
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


def _raw(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    """Read the project file with a plain `sqlite3` connection.

    Deliberately not through `Project`: this is the observer that shares none of
    the store's assumptions, so a write path and a read path that are wrong in
    the same direction cannot hide from it.
    """
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _raw_user_version(db_path: Path) -> int:
    return int(_raw(db_path, "PRAGMA user_version")[0][0])


def _set_raw_user_version(db_path: Path, version: int) -> None:
    """Forge a file's schema version, AC-3's fixture.

    `PRAGMA user_version` is schema-independent (`## Contract` PO-7), so this
    needs to know nothing at all about the table layout.
    """
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(f"PRAGMA user_version = {version:d}")
        connection.commit()
    finally:
        connection.close()
    assert _raw_user_version(db_path) == version, "the AC-3 fixture did not take"


def _pragma(project: Project, name: str) -> int:
    with project.transaction() as cur:
        return int(cur.execute(f"PRAGMA {name}").fetchone()[0])


def _chapter_id(cur: sqlite3.Cursor) -> int:
    rows = cur.execute("SELECT id FROM chapter").fetchall()
    assert len(rows) == 1, f"expected exactly one chapter row, found {len(rows)}"
    return int(rows[0][0])


def _page_id(cur: sqlite3.Cursor, ordinal: int) -> int:
    row = cur.execute("SELECT id FROM page WHERE ordinal = ?", (ordinal,)).fetchone()
    assert row is not None, f"no page row at ordinal {ordinal}"
    return int(row[0])


def _mask_for(ordinal: int, reading_index: int) -> bytes:
    """A distinct, non-textual blob per region, so a mix-up is visible.

    NUL bytes and a 0xFF are in there on purpose: AC-4 asserts the surviving
    pages' masks come back *byte-for-byte*, and a blob that is only ASCII makes
    that a weaker claim than it reads as.
    """
    return b"\x89PNG\x00mask\x00" + bytes([ordinal, reading_index, 0xFF])


def _build_source(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    """Write `_SOURCE_PAGES` into a fresh `scans/` folder under `tmp_path`.

    A subfolder rather than `tmp_path` itself, so that `<source>.mtproj` is also
    inside `tmp_path` and the test leaves nothing outside its own directory.
    """
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for filename, width, height in _SOURCE_PAGES:
        (source_dir / filename).write_bytes(png_bytes(width, height))
    return source_dir


def _write_artefacts_for_every_page(project: Project) -> None:
    """Give every page two regions, each with a mask and a line.

    AC-4's "pages 1, 2 and 4 are untouched" needs every page to have something
    to lose; two regions per page rather than one so a count assertion of 6
    surviving against 8 written is not a coincidence away from correct.
    """
    # `pages()` is read OUTSIDE the transaction on purpose: PO-5 makes
    # `transaction()` non-reentrant, and nothing in the contract requires
    # `pages()` to be callable from inside one.
    pages = project.pages()
    with project.transaction() as cur:
        for page in pages:
            page_id = _page_id(cur, page.ordinal)
            for reading_index in (0, 1):
                cur.execute(
                    _INSERT_REGION,
                    (
                        page_id,
                        reading_index,
                        f"[[0,0],[{page.width},{page.height}]]",
                        _mask_for(page.ordinal, reading_index),
                        "bubble",
                        0.5 + reading_index / 10,
                        None,
                    ),
                )
                cur.execute(
                    _INSERT_LINE,
                    (
                        cur.lastrowid,
                        f"ページ{page.ordinal}-{reading_index}",
                        f"page {page.ordinal} line {reading_index}",
                        None,
                        None,
                        None,
                    ),
                )


def _artefacts_by_ordinal(project: Project) -> dict[int, list[tuple[int, bytes, str | None]]]:
    """ordinal -> [(reading_index, mask_blob, line.source_ja), ...].

    A LEFT JOIN, so a region whose line was destroyed comes back as
    `(index, mask, None)` rather than vanishing. That is what makes "the line
    attached to that region is still there" (PO-3) an assertion rather than a
    row count.
    """
    artefacts: dict[int, list[tuple[int, bytes, str | None]]] = {}
    ordinals = [page.ordinal for page in project.pages()]
    with project.transaction() as cur:
        for ordinal in ordinals:
            rows = cur.execute(
                "SELECT region.reading_index, region.mask_blob, line.source_ja"
                " FROM region LEFT JOIN line ON line.region_id = region.id"
                " WHERE region.page_id = ?"
                " ORDER BY region.reading_index",
                (_page_id(cur, ordinal),),
            ).fetchall()
            artefacts[ordinal] = [(int(index), mask, source_ja) for index, mask, source_ja in rows]
    return artefacts


def _table_counts(project: Project) -> dict[str, int]:
    """Row counts for all seven tables, so an orphan row anywhere is visible.

    AC-5 needs this rather than a per-page query: a region written against a
    page row that was itself rolled back belongs to no page, so nothing keyed by
    ordinal would ever look at it.
    """
    with project.transaction() as cur:
        return {
            table: int(cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in _TABLES
        }


def _swap_ordinals(project: Project, first: int, second: int) -> None:
    """Exchange two page rows' `ordinal` values, parking one at -1 en route.

    `UNIQUE (chapter_id, ordinal)` forbids the naive two-statement swap. The
    point of doing it at all is to break the coincidence between rowid order and
    ordinal order that `create_project` otherwise leaves in place.
    """
    with project.transaction() as cur:
        cur.execute("UPDATE page SET ordinal = -1 WHERE ordinal = ?", (first,))
        cur.execute("UPDATE page SET ordinal = ? WHERE ordinal = ?", (first, second))
        cur.execute("UPDATE page SET ordinal = ? WHERE ordinal = -1", (second,))


@pytest.fixture
def built(tmp_path: Path, png_bytes: Callable[..., bytes]) -> _Built:
    """A source folder and its `Chapter`. No project has been created yet."""
    source_dir = _build_source(tmp_path, png_bytes)
    return _Built(source_dir, project_dir_for(source_dir), read_chapter(source_dir))


@pytest.fixture
def live_project(built: _Built) -> Iterator[Project]:
    """An open project over `built`, closed when the test ends."""
    with create_project(built.chapter, built.project_dir) as project:
        yield project


# -- the module's own constants ------------------------------------------------


def test_the_schema_version_and_the_two_page_status_values_are_the_pinned_ones() -> None:
    # `## Contract` PO-2 and the story's `SCHEMA_VERSION: int # starts at 1`.
    # A store that agreed with itself but not with the contract would pass every
    # round trip below and still write a file no later version can recognise.
    assert SCHEMA_VERSION == 1
    assert PAGE_PENDING == "pending"
    assert PAGE_STALE == "stale"
    assert PAGE_PENDING != PAGE_STALE


def test_the_schema_ddl_alone_creates_every_table_of_the_data_model() -> None:
    """`DDL` is "the full schema, one string" — checked without `project.py`.

    Executed against a bare in-memory connection, so this fails if the schema
    only becomes complete once `create_project` runs some extra statement of its
    own. That is the difference between a schema and a build procedure.
    """
    connection = sqlite3.connect(":memory:")
    try:
        assert isinstance(DDL, str)
        connection.executescript(DDL)
        names = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()

    assert set(_TABLES) <= names, f"missing tables: {sorted(set(_TABLES) - names)}"


def test_every_table_carries_the_columns_the_data_model_names(built: _Built) -> None:
    with create_project(built.chapter, built.project_dir):
        pass

    for table, expected in _SCHEMA_COLUMNS.items():
        actual = {str(row[1]) for row in _raw(built.db_path, f"PRAGMA table_info({table})")}
        assert expected <= actual, f"{table} is missing {sorted(expected - actual)}"


# -- AC-1: the file, its version, and every row written exactly ----------------


def test_creating_a_project_writes_the_file_its_version_and_one_row_per_page(
    tmp_path: Path, png_bytes: Callable[..., bytes], jpeg_7x3_bytes: bytes
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    # A fifth page that is not a PNG: the store must not be quietly
    # format-specific, and a JPEG's bytes and dimensions round-trip the same way.
    (source_dir / "p5.jpg").write_bytes(jpeg_7x3_bytes)
    chapter = read_chapter(source_dir)
    project_dir = project_dir_for(source_dir)

    with create_project(chapter, project_dir):
        pass

    db_path = project_dir / "project.db"
    assert db_path.is_file()

    # The version, from BOTH places PO-7 requires it: the schema-independent
    # pragma AC-3 actually checks, and the §4 column kept for fidelity.
    assert _raw_user_version(db_path) == SCHEMA_VERSION
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(SCHEMA_VERSION,)]

    # One chapter row, exactly one page row per page. Not "at least".
    assert _raw(db_path, "SELECT count(*) FROM chapter") == [(1,)]
    assert _raw(db_path, "SELECT count(*) FROM page") == [(len(chapter.pages),)]
    assert len(chapter.pages) == 5

    # Every field of every page, read by a plain sqlite3 connection rather than
    # by the store's own read path.
    rows = _raw(
        db_path,
        "SELECT ordinal, filename, width, height, sha256, status FROM page ORDER BY ordinal",
    )
    assert rows == [
        (page.ordinal, page.filename, page.width, page.height, page.sha256, PAGE_PENDING)
        for page in chapter.pages
    ]

    # Non-vacuity: four distinct sizes and five distinct hashes, so a transposed
    # width/height or a value read from the wrong column has nowhere to hide.
    assert len({(page.width, page.height) for page in chapter.pages}) == 4
    assert len({page.sha256 for page in chapter.pages}) == 5


def test_the_chapter_row_carries_the_paths_and_leaves_the_later_stories_columns_null(
    built: _Built,
) -> None:
    # `## Contract` PO-8: source_dir, output_dir per §5, an ISO-8601 UTC
    # created_at, and three columns that belong to MT-012/MT-013 and must not be
    # invented here.
    with create_project(built.chapter, built.project_dir):
        pass

    rows = _raw(
        built.db_path,
        "SELECT source_dir, output_dir, created_at, budget_ceiling_usd, model_id,"
        " rate_table_version FROM chapter",
    )
    assert len(rows) == 1
    source_dir, output_dir, created_at, ceiling, model_id, rate_table_version = rows[0]

    assert source_dir == str(built.source_dir)
    assert Path(str(source_dir)) == built.source_dir
    assert output_dir == str(built.source_dir.with_name(built.source_dir.name + "_en"))

    assert isinstance(created_at, str)
    stamped = datetime.fromisoformat(created_at)
    assert stamped.utcoffset() == timedelta(0), f"created_at is not UTC: {created_at!r}"

    assert (ceiling, model_id, rate_table_version) == (None, None, None)


# -- AC-2: the round trip, against a reopened project only ---------------------


def test_reopening_a_project_returns_the_chapter_and_every_page_identically(
    built: _Built,
) -> None:
    with create_project(built.chapter, built.project_dir) as created:
        # Cheap and true of any implementation; recorded as context, not as the
        # criterion. The assertions that matter are the ones after this block.
        assert created.chapter == built.chapter

    # A FRESH open on the path. `created` is closed and is never read again:
    # an implementation that reconstructs a field it never stored passes a
    # same-object round trip and fails here.
    with open_project(built.project_dir) as reopened:
        reopened_chapter = reopened.chapter
        reopened_pages = reopened.pages()

    assert reopened_chapter == built.chapter
    assert reopened_chapter.source_dir == built.source_dir
    assert reopened_pages == built.chapter.pages
    assert reopened_chapter.pages == reopened_pages
    assert len(reopened_pages) == len(_SOURCE_PAGES)


def test_pages_come_back_ordered_by_ordinal_and_not_by_insertion_order(
    built: _Built,
) -> None:
    """`pages()` must `ORDER BY ordinal` in SQL (`## Contract` PO-8).

    `create_project` inserts in ordinal order, so rowid order and ordinal order
    coincide and a `SELECT` with no `ORDER BY` looks correct on every other test
    in this file. Swapping two rows' ordinals in place breaks that coincidence,
    and no amount of sorting on insert can put it back.
    """
    with create_project(built.chapter, built.project_dir) as project:
        _swap_ordinals(project, 0, 3)

    with open_project(built.project_dir) as reopened:
        pages = reopened.pages()
        chapter_pages = reopened.chapter.pages

    assert [page.ordinal for page in pages] == [0, 1, 2, 3]
    # p1 and p4 have exchanged ordinals, so ordinal order is now the reverse of
    # insertion order at both ends.
    assert [page.filename for page in pages] == ["p4.png", "p2.png", "p3.png", "p1.png"]
    assert chapter_pages == pages


def test_a_project_is_a_context_manager_whose_exit_closes_the_connection(
    built: _Built,
) -> None:
    created = create_project(built.chapter, built.project_dir)
    with created as entered:
        assert entered is created
        assert entered.pages() == built.chapter.pages

    # Two things at once. A forgotten close is a file lock on Windows and a lost
    # commit anywhere, so `__exit__` closing is contract rather than courtesy --
    # and because `pages()` raises here, `pages()` must be a query rather than a
    # cached tuple, which is what makes AC-2's round trip above non-vacuous.
    with pytest.raises(sqlite3.ProgrammingError):
        created.pages()


# -- AC-3: a newer file is refused, and sqlite3 is not allowed to create one ---


@pytest.mark.parametrize("bump", [1, 41])
def test_opening_a_file_whose_schema_version_is_newer_raises_naming_both_numbers(
    built: _Built, bump: int
) -> None:
    with create_project(built.chapter, built.project_dir):
        pass
    _set_raw_user_version(built.db_path, SCHEMA_VERSION + bump)

    with pytest.raises(SchemaTooNew) as excinfo:
        open_project(built.project_dir)

    # A bare `raises` passes against a `raise SchemaTooNew()` triggered by
    # something else entirely. Both numbers, found and supported, or the message
    # cannot tell the user what to do.
    message = str(excinfo.value)
    assert str(SCHEMA_VERSION + bump) in message, message
    assert str(SCHEMA_VERSION) in message, message


def test_a_version_one_file_opened_by_version_one_code_opens_normally(built: _Built) -> None:
    # The only case this story handles (`## Contract` PO-7). Without it, a store
    # that raised SchemaTooNew unconditionally would pass the test above.
    with create_project(built.chapter, built.project_dir):
        pass
    assert _raw_user_version(built.db_path) == SCHEMA_VERSION

    with open_project(built.project_dir) as reopened:
        assert reopened.pages() == built.chapter.pages


def test_opening_a_directory_with_no_project_file_raises_filenotfounderror(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "scans.mtproj"
    empty.mkdir()

    with pytest.raises(FileNotFoundError):
        open_project(empty)

    # The discriminating half: `sqlite3.connect` CREATES the file, so a store
    # without an explicit existence check leaves an empty database behind and
    # fails later with the wrong error (`## Contract` PO-7).
    assert not (empty / "project.db").exists()

    with pytest.raises(FileNotFoundError):
        open_project(tmp_path / "never-existed.mtproj")


def test_creating_a_project_where_one_already_exists_refuses_without_clobbering_it(
    built: _Built,
) -> None:
    with create_project(built.chapter, built.project_dir) as project:
        _write_artefacts_for_every_page(project)
        counts_before = _table_counts(project)

    with pytest.raises(ProjectExists) as excinfo:
        create_project(built.chapter, built.project_dir)

    assert "project.db" in str(excinfo.value), str(excinfo.value)

    # "Rather than clobbering a project that may hold hours of edits" is a claim
    # about the contents, so that is what is asserted.
    with open_project(built.project_dir) as reopened:
        assert _table_counts(reopened) == counts_before
        assert reopened.pages() == built.chapter.pages
    assert counts_before["region"] == 8
    assert counts_before["line"] == 8


# -- AC-4 / PO-4: the cascade is live, and it goes down only -------------------


def test_both_constructors_leave_foreign_key_enforcement_switched_on(built: _Built) -> None:
    """`PRAGMA foreign_keys` must read 1 (`## Contract` PO-4).

    Measured on this machine, sqlite 3.53.1: the default is `0`, and setting the
    pragma inside an explicit transaction is a silent no-op that reads back `0`.
    A cascade that does not cascade is the bug AC-4 exists to catch, and it is
    invisible in every other assertion in this file.
    """
    with create_project(built.chapter, built.project_dir) as created:
        assert _pragma(created, "foreign_keys") == 1
    with open_project(built.project_dir) as reopened:
        assert _pragma(reopened, "foreign_keys") == 1


def test_replacing_one_scan_invalidates_that_page_only_and_leaves_the_others_intact(
    built: _Built, png_bytes: Callable[..., bytes]
) -> None:
    """AC-4, and the story's own falsifiable success condition for RED.

    A store that wipes the whole chapter on any hash change must fail this: the
    assertions are that pages 0, 1 and 3 keep their rows, their stored
    dimensions and hashes, and their regions, lines and mask blobs
    byte-for-byte — not merely that page 2's are gone.
    """
    with create_project(built.chapter, built.project_dir) as project:
        _write_artefacts_for_every_page(project)
        before = _artefacts_by_ordinal(project)
        counts_before = _table_counts(project)

    # Non-vacuity: every page really did have two regions, each with a mask and
    # a line, or "untouched" below would be true of nothing.
    assert sorted(before) == [0, 1, 2, 3]
    assert counts_before["region"] == 8
    assert counts_before["line"] == 8
    assert all(len(rows) == 2 for rows in before.values())
    assert all(source_ja is not None for rows in before.values() for _, _, source_ja in rows)

    replacement = png_bytes(*_REPLACEMENT_SIZE)
    (built.source_dir / "p3.png").write_bytes(replacement)

    with open_project(built.project_dir) as project:
        stale = project.refresh_from_source()

    # Ordinals are 0-based from MT-004, so the AC's "page 3" is ordinal 2.
    assert stale == (2,)

    with open_project(built.project_dir) as reopened:
        statuses = {page.ordinal: reopened.page_status(page.ordinal) for page in reopened.pages()}
        pages = {page.ordinal: page for page in reopened.pages()}
        after = _artefacts_by_ordinal(reopened)
        counts_after = _table_counts(reopened)

    # The row stays; invalidation cascades down, never up.
    assert sorted(pages) == [0, 1, 2, 3]
    assert statuses == {0: PAGE_PENDING, 1: PAGE_PENDING, 2: PAGE_STALE, 3: PAGE_PENDING}

    # PO-6: the hash AND the dimensions are updated, because the file changed
    # and a known-wrong stored size is worse than no size.
    assert pages[2].filename == "p3.png"
    assert pages[2].sha256 == hashlib.sha256(replacement).hexdigest()
    assert (pages[2].width, pages[2].height) == _REPLACEMENT_SIZE

    # The other three pages come back exactly as they were written.
    original = {page.ordinal: page for page in built.chapter.pages}
    for ordinal in (0, 1, 3):
        assert pages[ordinal] == original[ordinal]
        assert after[ordinal] == before[ordinal]

    assert after[2] == []
    assert counts_after["region"] == 6
    assert counts_after["line"] == 6
    assert counts_after["page"] == counts_before["page"]


def test_a_page_whose_file_has_gone_is_stale_with_its_stored_values_left_alone(
    built: _Built,
) -> None:
    """PO-6's absent-file branch, and the filename-versus-ordinal discriminator.

    Removing p3.png shifts every later page's ordinal in the fresh read. Matched
    by filename, exactly ordinal 2 is stale and p4.png is untouched; matched by
    ordinal, p4.png's bytes would be compared against p3.png's row and the
    answer would be `(2, 3)` with page 2's size overwritten with p4's.
    """
    with create_project(built.chapter, built.project_dir) as project:
        _write_artefacts_for_every_page(project)

    (built.source_dir / "p3.png").unlink()

    with open_project(built.project_dir) as project:
        stale = project.refresh_from_source()

    assert stale == (2,)

    with open_project(built.project_dir) as reopened:
        pages = {page.ordinal: page for page in reopened.pages()}
        statuses = {ordinal: reopened.page_status(ordinal) for ordinal in pages}
        after = _artefacts_by_ordinal(reopened)

    original = {page.ordinal: page for page in built.chapter.pages}
    # "Its stored hash and dimensions are left as they are, there being nothing
    # to update them to."
    assert pages[2] == original[2]
    assert statuses == {0: PAGE_PENDING, 1: PAGE_PENDING, 2: PAGE_STALE, 3: PAGE_PENDING}
    assert after[2] == []
    for ordinal in (0, 1, 3):
        assert pages[ordinal] == original[ordinal]


def test_a_new_file_in_the_source_folder_is_ignored_even_when_it_sorts_first(
    built: _Built, png_bytes: Callable[..., bytes]
) -> None:
    """PO-6: adding pages to an existing project is out of scope.

    `p0.png` sorts before every stored page, so the fresh read gives all four of
    them a different ordinal. Matched by filename, nothing is stale; matched by
    ordinal, every page in the chapter would be.
    """
    with create_project(built.chapter, built.project_dir) as project:
        _write_artefacts_for_every_page(project)
        counts_before = _table_counts(project)

    (built.source_dir / "p0.png").write_bytes(png_bytes(9, 19))

    with open_project(built.project_dir) as project:
        assert project.refresh_from_source() == ()

    with open_project(built.project_dir) as reopened:
        assert reopened.pages() == built.chapter.pages
        assert _table_counts(reopened) == counts_before
        assert all(reopened.page_status(page.ordinal) == PAGE_PENDING for page in reopened.pages())


def test_an_unchanged_source_folder_invalidates_nothing(built: _Built) -> None:
    with create_project(built.chapter, built.project_dir) as project:
        _write_artefacts_for_every_page(project)
        before = _artefacts_by_ordinal(project)

    with open_project(built.project_dir) as project:
        assert project.refresh_from_source() == ()

    with open_project(built.project_dir) as reopened:
        assert _artefacts_by_ordinal(reopened) == before
        assert reopened.pages() == built.chapter.pages


def test_a_second_refresh_reports_nothing_new_but_the_stale_mark_survives(
    built: _Built, png_bytes: Callable[..., bytes]
) -> None:
    # The mark must survive a reopen or "marked stale" means nothing (PO-2), and
    # the second refresh must not re-report a page whose hash it already caught
    # up with (PO-6).
    with create_project(built.chapter, built.project_dir):
        pass
    (built.source_dir / "p3.png").write_bytes(png_bytes(*_REPLACEMENT_SIZE))

    with open_project(built.project_dir) as project:
        assert project.refresh_from_source() == (2,)

    with open_project(built.project_dir) as project:
        assert project.refresh_from_source() == ()

    with open_project(built.project_dir) as reopened:
        assert reopened.page_status(2) == PAGE_STALE


def test_refresh_propagates_nopagesfound_when_the_user_emptied_the_folder(
    built: _Built,
) -> None:
    # PO-6: "Repairing a source folder the user emptied is not this story."
    with create_project(built.chapter, built.project_dir):
        pass
    for filename, _, _ in _SOURCE_PAGES:
        (built.source_dir / filename).unlink()

    with open_project(built.project_dir) as project, pytest.raises(NoPagesFound):
        project.refresh_from_source()


def test_refresh_propagates_filenotfounderror_when_the_folder_itself_has_gone(
    built: _Built,
) -> None:
    with create_project(built.chapter, built.project_dir):
        pass
    shutil.rmtree(built.source_dir)

    with open_project(built.project_dir) as project, pytest.raises(FileNotFoundError):
        project.refresh_from_source()


# -- AC-5: an injected failure rolls back, and nesting is refused --------------


def test_a_raise_inside_a_transaction_leaves_the_project_in_its_pre_write_state(
    built: _Built,
) -> None:
    with create_project(built.chapter, built.project_dir) as project:
        _write_artefacts_for_every_page(project)
        before = _artefacts_by_ordinal(project)
        counts_before = _table_counts(project)

        # A page-level row and two region-level rows, all real `execute` calls,
        # then a raise. No mock of the store, the connection or sqlite3: a
        # simulated rollback would prove the simulation atomic, not the store.
        with pytest.raises(_InjectedFailure), project.transaction() as cur:
            chapter_id = _chapter_id(cur)
            cur.execute(_INSERT_PAGE, (chapter_id, 4, "p5.png", 9, 19, "f" * 64, PAGE_PENDING))
            partial_page_id = cur.lastrowid
            cur.execute(
                _INSERT_REGION,
                (partial_page_id, 0, "[]", b"orphan", "bubble", 0.9, None),
            )
            cur.execute(
                _INSERT_REGION,
                (_page_id(cur, 0), 7, "[]", b"extra", "bubble", 0.9, None),
            )
            raise _InjectedFailure("simulated crash halfway through a stage write")

    with open_project(built.project_dir) as reopened:
        ordinals = [page.ordinal for page in reopened.pages()]
        after = _artefacts_by_ordinal(reopened)
        counts_after = _table_counts(reopened)
        filenames = [page.filename for page in reopened.pages()]

    # No partial page ...
    assert ordinals == [0, 1, 2, 3]
    assert "p5.png" not in filenames
    # ... and no orphan region. The row counts catch the region written against
    # the rolled-back page, which nothing keyed by ordinal could ever see.
    assert counts_after == counts_before
    assert after == before


def test_entering_a_transaction_inside_a_transaction_is_refused_loudly(
    live_project: Project,
) -> None:
    """`## Contract` PO-5, and without it AC-5 means "atomic unless nested".

    Measured on this machine: `with conn:` is not nestable — the inner block's
    exit commits, so an outer raise leaves `rows persisted: [4, 5]`. And
    `Connection.in_transaction` is False until the first DML inside the block,
    so it cannot be the guard.
    """
    with pytest.raises(RuntimeError), live_project.transaction(), live_project.transaction():
        pass  # unreachable: the second __enter__ is what raises

    # The guard must not latch. A flag the outer exit forgets to clear turns the
    # first nested attempt into a dead project.
    with live_project.transaction() as cur:
        cur.execute(_INSERT_GLOSSARY, (_chapter_id(cur), "名前", "name", None, 0))
    assert _table_counts(live_project)["glossary"] == 1


# -- AC-6: the second write of a region replaces it and keeps its line ---------


def test_writing_the_same_region_twice_leaves_one_row_and_keeps_its_line(
    built: _Built,
) -> None:
    """AC-6, both halves (`## Contract` PO-3).

    The second write is the upsert form, which **only parses against a schema
    carrying `UNIQUE (page_id, reading_index)`**: sqlite otherwise raises
    `OperationalError: ON CONFLICT clause does not match any PRIMARY KEY or
    UNIQUE constraint` (measured here, sqlite 3.53.1). So this test fails
    against a schema with no such key, with the wrong columns in it, or with it
    declared on the wrong table.
    """
    with create_project(built.chapter, built.project_dir) as project:
        with project.transaction() as cur:
            page_id = _page_id(cur, 0)
            cur.execute(_INSERT_REGION, (page_id, 0, "first", b"mask-1", "bubble", 0.5, None))
            cur.execute(_INSERT_LINE, (cur.lastrowid, "最初", "the first one", None, None, None))
        with project.transaction() as cur:
            cur.execute(_UPSERT_REGION, (page_id, 0, "second", b"mask-2", "bubble", 0.9, None))

    with open_project(built.project_dir) as reopened:
        counts = _table_counts(reopened)
        artefacts = _artefacts_by_ordinal(reopened)
    polygons = _raw(built.db_path, "SELECT polygon FROM region")

    # (1) no duplicate row survives ...
    assert counts["region"] == 1
    assert polygons == [("second",)]
    # ... and (2) the line attached to that region is still there. This is the
    # half that discriminates: under `INSERT OR REPLACE` the cascade takes it,
    # and a suite without this assertion passes against a store that destroys a
    # page's translations every time detection re-runs.
    assert counts["line"] == 1
    assert artefacts[0] == [(0, b"mask-2", "最初")]


def test_an_or_replace_write_destroys_the_line_because_the_cascade_is_live(
    built: _Built,
) -> None:
    """The negative control for the test above, and for PO-4's pragma.

    Measured here on sqlite 3.53.1: with `foreign_keys = ON`, `INSERT OR
    REPLACE` on a region leaves `line rows: 0`; with the pragma at its default
    `0`, the identical statement leaves `line rows: 1`. So this asserts the
    unwanted behaviour on purpose — it is the only assertion in the file that
    fails when `line.region_id` is declared without `ON DELETE CASCADE`, and
    without it the upsert test above would pass against a schema in which
    nothing cascades and AC-4's invalidation silently does nothing.
    """
    with create_project(built.chapter, built.project_dir) as project:
        with project.transaction() as cur:
            page_id = _page_id(cur, 0)
            cur.execute(_INSERT_REGION, (page_id, 0, "first", b"mask-1", "bubble", 0.5, None))
            cur.execute(_INSERT_LINE, (cur.lastrowid, "最初", "the first one", None, None, None))
        with project.transaction() as cur:
            cur.execute(_REPLACE_REGION, (page_id, 0, "second", b"mask-2", "bubble", 0.9, None))

    with open_project(built.project_dir) as reopened:
        counts = _table_counts(reopened)
        artefacts = _artefacts_by_ordinal(reopened)

    assert counts["region"] == 1
    assert counts["line"] == 0, "line.region_id is not ON DELETE CASCADE, or foreign_keys is off"
    assert artefacts[0] == [(0, b"mask-2", None)]


# -- the UNIQUE keys AC-4 and AC-6 rest on, and the one table without any ------


def test_two_pages_cannot_share_an_ordinal_within_a_chapter(live_project: Project) -> None:
    with pytest.raises(sqlite3.IntegrityError) as excinfo, live_project.transaction() as cur:
        cur.execute(
            _INSERT_PAGE, (_chapter_id(cur), 0, "different.png", 1, 1, "0" * 64, PAGE_PENDING)
        )

    # The columns, not merely "some IntegrityError": a NOT NULL violation is
    # also an IntegrityError, and sqlite names the columns whether the key is
    # declared inline or as a separate CREATE UNIQUE INDEX (both measured).
    message = str(excinfo.value)
    assert "page.chapter_id" in message, message
    assert "page.ordinal" in message, message


def test_two_pages_cannot_share_a_filename_within_a_chapter(live_project: Project) -> None:
    with pytest.raises(sqlite3.IntegrityError) as excinfo, live_project.transaction() as cur:
        cur.execute(_INSERT_PAGE, (_chapter_id(cur), 99, "p1.png", 1, 1, "0" * 64, PAGE_PENDING))

    message = str(excinfo.value)
    assert "page.chapter_id" in message, message
    assert "page.filename" in message, message


def test_two_regions_cannot_share_a_reading_index_on_one_page(live_project: Project) -> None:
    with live_project.transaction() as cur:
        page_id = _page_id(cur, 0)
        cur.execute(_INSERT_REGION, (page_id, 0, "[]", b"mask", "bubble", 0.5, None))

    with pytest.raises(sqlite3.IntegrityError) as excinfo, live_project.transaction() as cur:
        cur.execute(_INSERT_REGION, (page_id, 0, "[]", b"other", "bubble", 0.5, None))

    message = str(excinfo.value)
    assert "region.page_id" in message, message
    assert "region.reading_index" in message, message


def test_a_region_cannot_carry_two_lines(live_project: Project) -> None:
    with live_project.transaction() as cur:
        cur.execute(_INSERT_REGION, (_page_id(cur, 0), 0, "[]", b"mask", "bubble", 0.5, None))
        region_id = cur.lastrowid
        cur.execute(_INSERT_LINE, (region_id, "一", "one", None, None, None))

    with pytest.raises(sqlite3.IntegrityError) as excinfo, live_project.transaction() as cur:
        cur.execute(_INSERT_LINE, (region_id, "二", "two", None, None, None))

    assert "line.region_id" in str(excinfo.value), str(excinfo.value)


def test_a_chapter_cannot_carry_one_japanese_term_twice(live_project: Project) -> None:
    with live_project.transaction() as cur:
        chapter_id = _chapter_id(cur)
        cur.execute(_INSERT_GLOSSARY, (chapter_id, "先輩", "senpai", None, 0))

    with pytest.raises(sqlite3.IntegrityError) as excinfo, live_project.transaction() as cur:
        cur.execute(_INSERT_GLOSSARY, (_chapter_id(cur), "先輩", "upperclassman", None, 1))

    message = str(excinfo.value)
    assert "glossary.chapter_id" in message, message
    assert "glossary.term_ja" in message, message


def test_the_llm_call_ledger_accepts_two_identical_calls(live_project: Project) -> None:
    """`llm_call` carries **no** UNIQUE constraint, deliberately (PO-3).

    §4: the ledger is append-only. A UNIQUE key here would silently drop a real
    second call — the same page retried with the same model and the same token
    counts is a second bill, not a duplicate row — and the money would stop
    adding up with no error anywhere.
    """
    with live_project.transaction() as cur:
        chapter_id = _chapter_id(cur)
        page_id = _page_id(cur, 0)
        cur.execute(_INSERT_RUN, (chapter_id, "2026-09-15T00:00:00+00:00", None, None, None))
        run_id = cur.lastrowid
        for _ in range(2):
            cur.execute(
                _INSERT_LLM_CALL,
                (
                    run_id,
                    page_id,
                    "req-identical",
                    "claude-x",
                    1000,
                    500,
                    0,
                    0,
                    0.0123,
                    "2026-09-15T00:00:01+00:00",
                ),
            )

    assert _table_counts(live_project)["llm_call"] == 2


def test_a_chapter_can_carry_more_than_one_run(live_project: Project) -> None:
    # PO-3: runs are events, so `run` carries no UNIQUE either. A resume is a
    # second run of the same chapter.
    with live_project.transaction() as cur:
        chapter_id = _chapter_id(cur)
        cur.execute(_INSERT_RUN, (chapter_id, "2026-09-15T00:00:00+00:00", None, None, None))
        cur.execute(_INSERT_RUN, (chapter_id, "2026-09-15T01:00:00+00:00", None, None, None))

    assert _table_counts(live_project)["run"] == 2


# -- AC-7: a sibling of the source folder, and nothing inside it moves ---------


def test_the_project_directory_is_the_source_folders_mtproj_sibling(tmp_path: Path) -> None:
    # Asserted against code rather than against the test's own arithmetic
    # (`## Contract` PO-1): `project_dir_for` is what decides the location.
    source_dir = tmp_path / "scans"
    assert project_dir_for(source_dir) == source_dir.parent / (source_dir.name + ".mtproj")
    assert project_dir_for(source_dir).name == "scans.mtproj"
    assert project_dir_for(source_dir).parent == source_dir.parent
    # Not inside the source folder: §4, "Not inside it: the input folder is the
    # user's scans and the tool does not write there."
    assert source_dir not in project_dir_for(source_dir).parents


def test_creating_a_project_writes_its_file_outside_and_touches_nothing_inside(
    built: _Built,
) -> None:
    assert not built.project_dir.exists(), "create_project must make it (PO-1), not the test"

    before = _snapshot(built.source_dir)
    # Non-vacuity: a hash comparison over an empty or mis-rooted listing would
    # be satisfied by doing nothing at all.
    assert sum(1 for digest in before.values() if digest is not None) == len(_SOURCE_PAGES)

    with create_project(built.chapter, built.project_dir) as project:
        _write_artefacts_for_every_page(project)

    assert built.db_path.is_file()
    assert _snapshot(built.source_dir) == before


def test_reopening_and_refreshing_a_project_also_touches_nothing_inside_the_source(
    built: _Built, png_bytes: Callable[..., bytes]
) -> None:
    # AC-7 is written about creation, but `refresh_from_source` is the other
    # operation that opens the user's folder, and §5 makes the folder read-only
    # to this app for the whole life of the project, not just at create time.
    with create_project(built.chapter, built.project_dir) as project:
        _write_artefacts_for_every_page(project)

    (built.source_dir / "p3.png").write_bytes(png_bytes(*_REPLACEMENT_SIZE))
    before = _snapshot(built.source_dir)
    assert sum(1 for digest in before.values() if digest is not None) == len(_SOURCE_PAGES)

    with open_project(built.project_dir) as project:
        assert project.refresh_from_source() == (2,)

    assert _snapshot(built.source_dir) == before
