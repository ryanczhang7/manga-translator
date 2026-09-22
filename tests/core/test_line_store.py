"""`line` rows: writing them, reading them back, and the project's first migration.

Covers **AC-10** in full (a schema-version-1 file is migrated to 2 in place, its
rows survive, and `write_lines`/`read_lines` round-trip through it, `ocr_empty`
included) and the store half of **AC-5** (each region's text lands against its
own `reading_index`).

**This is the project's first migration, and it is not optional tidiness**
(PO-3). `open_project` today opens a v1 file without complaint and would then
fail on the first `write_lines` - a project a user created yesterday, reopened
after an update, that breaks on the OCR stage rather than on the open.

Three conventions here are inherited from MT-005's and MT-007's suites because
their reasons were measured, not stylistic:

- **The stored rows are observed with a plain `sqlite3` connection.** "A codec
  that is uniformly wrong round-trips through itself perfectly" (`tdd-cycle`), so
  the write path is read back by something that imports nothing from
  `mangatl.store`. That is what makes `ocr_empty` an assertion about a column and
  not about a Python attribute.
- **The round trip is asserted against a project reopened from the path.** The
  object that did the writing is closed first and never consulted again.
- **The v1 file is built by executing a transcribed copy of the v1 DDL**, never
  by calling `create_project` and undoing part of it. `_V1_DDL` below is the
  schema as `src/mangatl/store/schema.py` shipped it at MT-005, copied here
  verbatim of statement (comments dropped) in RED. It is a **historical
  artefact** and must never be updated to track `schema.py`: the day someone
  "fixes" it to match the current schema is the day AC-10 stops testing a
  migration and starts testing that v2 opens v2.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. Every test builds a two-page chapter of
tiny PNGs on `tmp_path` and touches a handful of rows.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import (
    SCHEMA_VERSION,
    Project,
    SchemaTooNew,
    create_project,
    open_project,
    project_dir_for,
)

_PAGE_W, _PAGE_H = 40, 30

#: The schema **as it shipped at version 1**, transcribed in RED from
#: `src/mangatl/store/schema.py` before this story changed it. Comments are
#: dropped; every statement, column, type, constraint and cascade is byte-faithful
#: to what MT-005 wrote and MT-007 extended with `region.merged_from`.
#:
#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. It is the input to AC-10, and a
#: copy that tracks the current schema turns a migration test into a tautology.
_V1_DDL = """
CREATE TABLE chapter (
    id                 INTEGER PRIMARY KEY,
    source_dir         TEXT    NOT NULL,
    output_dir         TEXT    NOT NULL,
    created_at         TEXT    NOT NULL,
    schema_version     INTEGER NOT NULL,
    budget_ceiling_usd REAL,
    model_id           TEXT,
    rate_table_version TEXT
);

CREATE TABLE page (
    id         INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
    ordinal    INTEGER NOT NULL,
    filename   TEXT    NOT NULL,
    width      INTEGER NOT NULL,
    height     INTEGER NOT NULL,
    sha256     TEXT    NOT NULL,
    status     TEXT    NOT NULL,
    UNIQUE (chapter_id, ordinal),
    UNIQUE (chapter_id, filename)
);

CREATE TABLE region (
    id            INTEGER PRIMARY KEY,
    page_id       INTEGER NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    reading_index INTEGER NOT NULL,
    polygon       TEXT    NOT NULL,
    mask_blob     BLOB    NOT NULL,
    kind          TEXT    NOT NULL,
    confidence    REAL    NOT NULL,
    merged_from   TEXT,
    UNIQUE (page_id, reading_index)
);

CREATE TABLE line (
    id          INTEGER PRIMARY KEY,
    region_id   INTEGER NOT NULL UNIQUE REFERENCES region(id) ON DELETE CASCADE,
    source_ja   TEXT    NOT NULL,
    proposed_en TEXT,
    final_en    TEXT,
    edited_at   TEXT,
    viewed_at   TEXT
);

CREATE TABLE run (
    id             INTEGER PRIMARY KEY,
    chapter_id     INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
    started_at     TEXT    NOT NULL,
    ended_at       TEXT,
    outcome        TEXT,
    aborted_reason TEXT
);

CREATE TABLE llm_call (
    id                 INTEGER PRIMARY KEY,
    run_id             INTEGER NOT NULL REFERENCES run(id),
    page_id            INTEGER NOT NULL REFERENCES page(id),
    request_id         TEXT    NOT NULL,
    model_id           TEXT    NOT NULL,
    input_tokens       INTEGER NOT NULL,
    output_tokens      INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    cache_read_tokens  INTEGER NOT NULL,
    cost_usd           REAL    NOT NULL,
    at                 TEXT    NOT NULL
);

CREATE TABLE glossary (
    id              INTEGER PRIMARY KEY,
    chapter_id      INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
    term_ja         TEXT    NOT NULL,
    term_en         TEXT    NOT NULL,
    note            TEXT,
    first_seen_page INTEGER NOT NULL,
    UNIQUE (chapter_id, term_ja)
);
"""

#: Two `line` rows a v1 file already holds, to be found intact after the
#: migration. Japanese, because a migration that rebuilt the table through a
#: text round trip with the wrong encoding damages exactly this and nothing else.
_V1_LINES: tuple[tuple[int, str, str | None], ...] = (
    (0, "醜鬼が人間の言う通りに動いたりね", "as the humans tell them to"),
    (1, "……なるほど", None),
)


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    """A two-page chapter, so a write to page 0 can be shown not to touch page 1."""
    folder = tmp_path / "chapter"
    folder.mkdir()
    for name in ("p1.png", "p2.png"):
        (folder / name).write_bytes(png_bytes(_PAGE_W, _PAGE_H))
    return folder


@pytest.fixture
def project(source_dir: Path) -> Iterator[Project]:
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as opened:
        yield opened


@pytest.fixture
def regions(one_bit_png: Callable[..., bytes]) -> tuple[RawRegion, ...]:
    """Three regions, already in reading order, with distinct geometry."""
    mask = one_bit_png(_PAGE_W, _PAGE_H, [(0, 0, 4, 4)])
    return (
        RawRegion(polygon=_ring(28, 2, 38, 8), mask=mask, confidence=0.5, kind="bubble"),
        RawRegion(polygon=_ring(2, 2, 12, 8), mask=mask, confidence=0.75, kind="bubble"),
        RawRegion(polygon=_ring(2, 20, 12, 28), mask=mask, confidence=0.25, kind="box"),
    )


#: Three results whose texts are distinct and in no sorted order, so a writer
#: that sorted, reversed or reused one of them is caught on content.
_RESULTS: tuple[OcrResult, ...] = (
    OcrResult(text="醜鬼が人間の言う通りに動いたりね"),
    OcrResult(text="", ocr_empty=True),
    OcrResult(text="……なるほど"),
)


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Run `sql` through a plain `sqlite3` connection that knows nothing of
    `mangatl.store`."""
    connection = sqlite3.connect(db_path)
    try:
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _user_version(db_path: Path) -> int:
    return int(_raw(db_path, "PRAGMA user_version")[0][0])


def _v1_regions(one_bit_png: Callable[..., bytes]) -> tuple[RawRegion, ...]:
    """The three regions a v1 file holds, and they are **valid `RawRegion`s**.

    CORRECTED ON A RETURN TO RED (`## Regressions`, defect 2). The first version
    of `_build_v1_file` wrote `polygon = "[[0, 0], [1, 1]]"` and
    `mask_blob = b"\\x89PNG-fake"` straight into the table, on the reasoning that
    AC-10 is about SQL rows and the values were never read. They are read:
    `read_regions` builds a `RawRegion` out of every row, and `__post_init__`
    refuses a polygon that is not a closed ring of at least four vertices and a
    mask that does not open with the PNG signature (MT-007). So the fixture wrote
    a v1 file no version of this code could ever have written, and AC-10's "its
    existing rows survive" was unsatisfiable without weakening a domain
    invariant.

    The shape is `test_region_store_merged_from.py::_region`'s, which is the
    pattern this should have followed in the first place: a closed rectangular
    ring, and a real 1-bit PNG from `conftest.one_bit_png`.

    Confidences are exactly representable in binary, so the rows round-trip
    bit-identically and the regions can be compared with `==`.
    """
    rects: tuple[tuple[int, int, int, int], ...] = (
        (2, 2, 12, 8),
        (14, 2, 24, 8),
        (2, 12, 12, 20),
    )
    return tuple(
        RawRegion(
            polygon=_ring(x0, y0, x1 - 1, y1 - 1),
            mask=one_bit_png(_PAGE_W, _PAGE_H, [(x0, y0, x1, y1)]),
            confidence=confidence,
            kind="bubble",
        )
        for (x0, y0, x1, y1), confidence in zip(rects, (0.5, 0.75, 0.25), strict=True)
    )


def _build_v1_file(source_dir: Path, one_bit_png: Callable[..., bytes]) -> Path:
    """A schema-version-1 project file, built with `_V1_DDL` and nothing else.

    No `create_project`, no `Project`, no `schema.DDL` - so the file this
    function produces cannot silently acquire a v2 column when `schema.py`
    changes. It carries a chapter, two pages, three regions on page 0 and the two
    `line` rows of `_V1_LINES`, because "its existing rows survive" needs rows in
    every table the migration could plausibly rebuild.
    """
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V1_DDL)
        connection.execute("PRAGMA user_version = 1")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version)"
            " VALUES (?, ?, ?, ?)",
            (str(source_dir), str(source_dir) + "_en", "2026-09-15T00:00:00+00:00", 1),
        )
        chapter_id = cursor.lastrowid
        chapter = read_chapter(source_dir)
        for page in chapter.pages:
            cursor.execute(
                "INSERT INTO page (chapter_id, ordinal, filename, width, height, sha256, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chapter_id,
                    page.ordinal,
                    page.filename,
                    page.width,
                    page.height,
                    page.sha256,
                    "pending",
                ),
            )
        page_id = cursor.execute("SELECT id FROM page WHERE ordinal = 0").fetchone()[0]
        for index, region in enumerate(_v1_regions(one_bit_png)):
            cursor.execute(
                "INSERT INTO region (page_id, reading_index, polygon, mask_blob, kind,"
                " confidence, merged_from) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    page_id,
                    index,
                    json.dumps([list(vertex) for vertex in region.polygon]),
                    region.mask,
                    region.kind,
                    region.confidence,
                    None,
                ),
            )
        for reading_index, source_ja, proposed_en in _V1_LINES:
            region_id = cursor.execute(
                "SELECT id FROM region WHERE page_id = ? AND reading_index = ?",
                (page_id, reading_index),
            ).fetchone()[0]
            cursor.execute(
                "INSERT INTO line (region_id, source_ja, proposed_en) VALUES (?, ?, ?)",
                (region_id, source_ja, proposed_en),
            )
        connection.commit()
    finally:
        connection.close()
    return db_path


# -- the constant, and the column ----------------------------------------------


def test_this_build_writes_and_reads_the_current_schema_version() -> None:
    """PO-3's schema bump, stated once, where a reader looks for it.

    A store that agreed with itself but not with the contract would pass every
    round trip in this file and still write a file no other version recognises.

    **Moved to 3 by MT-012 (PO-5)**, which is the second migration: `llm_call`
    loses `cost_usd REAL`, gains `cost_micro_usd INTEGER` and
    `rate_table_version`, and gains the two append-only triggers AC-4 needs.
    AC-10's migration below is unaffected in substance - a v1 file is now
    brought to 3 rather than to 2, through both steps - and `_V1_DDL` above is
    still the v1 schema and must stay that way.

    **Moved to 4 by MT-044 (C-12)**: `chapter.budget_ceiling_usd REAL` becomes
    `budget_ceiling_micro_usd INTEGER`, so AC-5 can read a ceiling off the
    chapter row as the integer micro-dollars MT-012 PO-2 settled money on.
    A v1 file now runs three steps in one open, and `_V1_DDL` above is still the
    v1 schema and must still stay that way.
    """
    assert SCHEMA_VERSION == 4


def test_a_freshly_created_project_is_a_current_version_file_with_the_new_column(
    source_dir: Path,
) -> None:
    """The other half of AC-10: the current version is what `create_project`
    writes now - 2 at MT-010, 3 since MT-012 (PO-5).

    Both places the version is recorded - the schema-independent pragma
    `open_project` actually checks, and the `chapter.schema_version` column §4
    keeps for fidelity - because MT-005 PO-7 required both and a migration that
    updated one of them is a file that disagrees with itself.
    """
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)):
        pass
    db_path = project_dir_for(source_dir) / "project.db"

    assert _user_version(db_path) == 4
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(4,)]
    columns = {str(row[1]) for row in _raw(db_path, "PRAGMA table_info(line)")}
    assert "ocr_empty" in columns, f"the line table has {sorted(columns)}"


def test_the_new_column_is_not_null_and_defaults_to_zero(source_dir: Path) -> None:
    """C-1's `ocr_empty INTEGER NOT NULL DEFAULT 0`, read off the table itself.

    The DEFAULT is what keeps every existing `INSERT INTO line (...)` in this
    repository working - `tests/core/test_project.py` names six columns and
    `tests/core/test_region_store.py` names three, and RED re-checked both
    against the tree. NOT NULL is what keeps the flag a boolean: a nullable flag
    has three states and the review screen has two.
    """
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)):
        pass
    db_path = project_dir_for(source_dir) / "project.db"

    rows = {str(row[1]): row for row in _raw(db_path, "PRAGMA table_info(line)")}

    assert "ocr_empty" in rows
    _cid, _name, declared_type, notnull, default, _pk = rows["ocr_empty"]
    assert str(declared_type).upper() == "INTEGER"
    assert int(notnull) == 1, "ocr_empty is nullable, so the flag has three states"
    assert str(default) == "0"


# -- AC-5's store half: text against the right reading_index -------------------


def test_each_results_text_lands_against_its_own_regions_reading_index(
    project: Project, regions: tuple[RawRegion, ...]
) -> None:
    """AC-5's store half, observed through plain sqlite rather than `read_lines`.

    `write_lines` is positional in exactly the way `write_regions` is (MT-007
    A-11): `results[i]` belongs to the region at `reading_index == i`. Nothing
    sorts, because reading order is already fixed by the time the regions were
    written and a store that re-derived it would be inventing a second answer.

    The join is written out here rather than taken from `read_lines`, so a
    `read_lines` that reversed the rows and a `write_lines` that reversed them
    cannot cancel out.
    """
    project.write_regions(0, regions)

    project.write_lines(0, _RESULTS)

    db_path = project_dir_for(project.chapter.source_dir) / "project.db"
    rows = _raw(
        db_path,
        "SELECT region.reading_index, line.source_ja, line.ocr_empty"
        " FROM line JOIN region ON region.id = line.region_id"
        " JOIN page ON page.id = region.page_id"
        " WHERE page.ordinal = 0 ORDER BY region.reading_index",
    )

    assert rows == [
        (0, "醜鬼が人間の言う通りに動いたりね", 0),
        (1, "", 1),
        (2, "……なるほど", 0),
    ]


def test_lines_written_to_one_page_come_back_from_a_reopened_project(
    source_dir: Path, regions: tuple[RawRegion, ...]
) -> None:
    """AC-5 and AC-10's round trip, against a project reopened from the path.

    The writer is closed before anything is asserted, so an implementation that
    answered `read_lines` from memory - agreeing with itself about a field it
    never stored - fails here. `ocr_empty` is carried across the reopen, which is
    the whole of PO-3: the three states the review screen distinguishes are **no
    row**, **row with the flag**, and **row with text**, and only a stored flag
    can tell the middle one from the others after a restart.
    """
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        writer.write_regions(0, regions)
        writer.write_lines(0, _RESULTS)

    with open_project(project_dir_for(source_dir)) as reopened:
        read_back = reopened.read_lines(0)
        untouched = reopened.read_lines(1)

    assert read_back == _RESULTS
    assert [r.ocr_empty for r in read_back] == [False, True, False]
    assert untouched == (), "writing page 0's lines put rows on page 1"


def test_a_page_with_no_lines_reads_back_empty_rather_than_raising(
    project: Project, regions: tuple[RawRegion, ...]
) -> None:
    """AC-9's `is_done` depends on this being `()` and not an exception.

    A page whose regions are stored but whose OCR has not run is the normal state
    of every page between the detect stage and this one, so it is the *common*
    case rather than an edge.
    """
    project.write_regions(0, regions)

    assert project.read_lines(0) == ()
    assert project.read_lines(1) == ()


def test_writing_a_pages_lines_twice_leaves_one_line_per_region(
    project: Project, regions: tuple[RawRegion, ...]
) -> None:
    """A resumed or re-run page must not raise, and must not double up.

    `line.region_id` is `UNIQUE` in the schema, so a second plain INSERT raises
    `IntegrityError` - which would turn "re-run this chapter" into a crash rather
    than into work redone. The second write's text is what survives, because the
    second run is the more recent read of the page.
    """
    project.write_regions(0, regions)
    project.write_lines(0, _RESULTS)

    second = (OcrResult(text="一"), OcrResult(text="二"), OcrResult(text="三"))
    project.write_lines(0, second)

    db_path = project_dir_for(project.chapter.source_dir) / "project.db"
    assert _raw(db_path, "SELECT count(*) FROM line") == [(3,)]
    assert project.read_lines(0) == second


def test_a_re_detection_takes_the_pages_lines_with_it_by_cascade(
    project: Project, regions: tuple[RawRegion, ...]
) -> None:
    """The cascade `schema.py` declares, exercised through the new writer.

    `line.region_id` is `ON DELETE CASCADE` and `write_regions` deletes rows at
    `reading_index >= len(regions)` (MT-007 A-11), so a re-detection that finds
    fewer regions must not leave a `line` row attached to a region that no longer
    exists. MT-005 measured that the cascade is silently inert unless
    `PRAGMA foreign_keys` is on, and that a row count of the parent table cannot
    see the difference - so this counts the child.
    """
    project.write_regions(0, regions)
    project.write_lines(0, _RESULTS)
    db_path = project_dir_for(project.chapter.source_dir) / "project.db"
    assert _raw(db_path, "SELECT count(*) FROM line") == [(3,)]

    project.write_regions(0, regions[:1])

    assert _raw(db_path, "SELECT count(*) FROM line") == [(1,)], (
        "a line row survived the region it belonged to: either line.region_id is"
        " not ON DELETE CASCADE, or PRAGMA foreign_keys is off"
    )
    assert len(project.read_lines(0)) == 1


# -- AC-10: the migration ------------------------------------------------------


def test_a_version_one_file_is_migrated_in_place_when_it_is_opened(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-10's first clause: in place, on open, with no separate command.

    "In place" is asserted as a property of the file on disk after the project is
    closed, not of the open connection: a migration held in memory is not a
    migration, and the next process to open the file would do the whole thing
    again - or, worse, would find a v1 file that the last run had already written
    v2 rows into.
    """
    db_path = _build_v1_file(source_dir, one_bit_png)
    assert _user_version(db_path) == 1
    before = {str(row[1]) for row in _raw(db_path, "PRAGMA table_info(line)")}
    assert "ocr_empty" not in before, "the v1 fixture already has the v2 column"

    with open_project(project_dir_for(source_dir)):
        pass

    # 4, not 2: MT-012's v2 -> v3 step and MT-044's v3 -> v4 step both run
    # immediately after MT-010's, so a v1 file arrives at the current version in
    # one open. `test_ledger.py` covers the v2 -> v3 step on a file that starts
    # at 2, and `test_schema_v4.py` the v3 -> v4 step on one that starts at 3.
    assert _user_version(db_path) == 4
    after = {str(row[1]) for row in _raw(db_path, "PRAGMA table_info(line)")}
    assert "ocr_empty" in after
    assert before <= after, f"the migration dropped {sorted(before - after)} from the line table"


def test_the_rows_a_version_one_file_already_held_all_survive_the_migration(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-10's second clause, and the one that costs a user their work if it is
    wrong.

    Every table the v1 fixture populated is counted and the `line` rows are
    compared field for field, including the `NULL` `proposed_en` that §4 says is
    what "not yet translated" means. A migration that rebuilt `line` by
    `CREATE TABLE ... AS SELECT` would pass a row count and quietly turn that
    NULL into something else, or lose the UNIQUE key it depends on.

    The regions are compared as `RawRegion`s and not merely counted (corrected on
    a return to RED - `## Regressions`, defect 2). That is the assertion the
    original fixture made impossible: it wrote rows the domain refuses, so the
    only thing that could be asserted about them was a row count, which is
    exactly the weak observation `tdd-cycle` warns about. Read back through
    `read_regions` they pass MT-007's `__post_init__` and compare field for
    field, mask bytes included.
    """
    db_path = _build_v1_file(source_dir, one_bit_png)
    counts_before = {
        table: _raw(db_path, f"SELECT count(*) FROM {table}")[0][0]
        for table in ("chapter", "page", "region", "line")
    }
    assert counts_before == {"chapter": 1, "page": 2, "region": 3, "line": 2}

    with open_project(project_dir_for(source_dir)) as migrated:
        assert len(migrated.chapter.pages) == 2
        assert migrated.read_regions(0) == _v1_regions(one_bit_png)

    rows = _raw(
        db_path,
        "SELECT region.reading_index, line.source_ja, line.proposed_en, line.ocr_empty"
        " FROM line JOIN region ON region.id = line.region_id"
        " ORDER BY region.reading_index",
    )
    assert rows == [
        (0, "醜鬼が人間の言う通りに動いたりね", "as the humans tell them to", 0),
        (1, "……なるほど", None, 0),
    ]
    counts_after = {
        table: _raw(db_path, f"SELECT count(*) FROM {table}")[0][0]
        for table in ("chapter", "page", "region", "line")
    }
    assert counts_after == counts_before


def test_the_unique_key_on_region_id_survives_the_migration(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-10's rows-survive clause, extended to the constraint the writer needs.

    A migration written as "make a new table, copy the rows, drop the old one" is
    the standard sqlite recipe and it is exactly where a constraint gets lost.
    `line.region_id UNIQUE` is what makes `write_lines` able to upsert instead of
    raising on a re-run, so losing it produces two lines per region on the second
    run of a resumed chapter - with every row count still looking plausible.
    """
    db_path = _build_v1_file(source_dir, one_bit_png)

    with open_project(project_dir_for(source_dir)):
        pass

    connection = sqlite3.connect(db_path)
    try:
        region_id = connection.execute("SELECT region_id FROM line LIMIT 1").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO line (region_id, source_ja) VALUES (?, ?)", (region_id, "duplicate")
            )
    finally:
        connection.close()


def test_a_migrated_file_round_trips_write_lines_and_read_lines(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-10's third clause. The migrated file is a working v2 file, flag and all.

    Not the same assertion as the round trip on a freshly created project above:
    a migration that added the column but left the `line` table without its
    DEFAULT, or that forgot to bump `chapter.schema_version`, produces a file
    that opens and then fails on the first write - which is the exact failure
    PO-3 says AC-10 exists to prevent, one release later.
    """
    _build_v1_file(source_dir, one_bit_png)

    with open_project(project_dir_for(source_dir)) as migrated:
        migrated.write_lines(0, _RESULTS)

    with open_project(project_dir_for(source_dir)) as reopened:
        assert reopened.read_lines(0) == _RESULTS
        assert [r.ocr_empty for r in reopened.read_lines(0)] == [False, True, False]


def test_a_file_newer_than_this_build_is_still_refused_after_the_migration_lands(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """The migration must not be mistaken for "open anything".

    MT-005 AC-3's refusal is now a refusal of version 3 and upward rather than of
    version 2, and an `open_project` that migrated whatever it found would turn a
    loud, recoverable error into silent corruption of a file written by a build
    this one does not understand. Both numbers stay in the message.
    """
    db_path = _build_v1_file(source_dir, one_bit_png)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1:d}")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchemaTooNew) as excinfo:
        open_project(project_dir_for(source_dir))

    message = str(excinfo.value)
    assert str(SCHEMA_VERSION + 1) in message, message
    assert str(SCHEMA_VERSION) in message, message
