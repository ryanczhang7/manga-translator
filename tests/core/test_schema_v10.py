"""MT-103 AC-1 and AC-6: schema version 10, and the v9 -> v10 step.

Five additions arrive in one step (MT-103 `## Context`), and this suite pins
the ones a migration can get silently wrong:

1. **`llm_call.page_id` becomes nullable** - a chapter-level call (the glossary
   pre-pass, the consistency pass) has no page. SQLite cannot drop a NOT NULL
   in place, so the step **rebuilds** `llm_call`, and a rebuild is exactly
   where the two append-only triggers are lost without a sound (PO-1). So the
   migrated file is asked to refuse a real `UPDATE` and a real `DELETE`, with
   `page` as the control that still accepts both.
2. **`llm_call.pricing`**, `NOT NULL DEFAULT 'standard'`: every row a v9 file
   held was priced at the interactive rate - batch pricing did not exist - so
   `'standard'` is the truth about it, not a placeholder.
3. **`batch_job` and `correction`**, two new tables, and
4. **`chapter.glossary_proposed_at`**, NULL on every migrated chapter: no v9
   file ever ran the pre-pass.
5. **A fresh file and a migrated one store the same declarations** in
   `sqlite_master.sql`, whitespace collapsed - `llm_call`, its two triggers,
   `batch_job`, `correction` and `chapter` - the `test_schema_v9.py`
   comparison.

**The shared-string trap, one version further back than usual.**
`schema.LLM_CALL_DDL` is run verbatim by the v2 -> v3 step and
`schema.CHAPTER_DDL` by the v3 -> v4 step (`project.py`). A column written
into either string is created by that old step and then added again by the v10
step: `duplicate column name`. A v6 or v8 file runs neither old step and cannot
see it, so the walk-all-the-way test here starts from **version 2**, using
`test_ledger.py`'s own v2 builder.

AC-6 (`glossary_proposed_at` / `mark_glossary_proposed`) lives here too: it is
the marker this step adds, read on a fresh file and on a migrated one. They are
**`Project` methods** (MT-103 `## Contract`, RED amendment R-1), for
`Project.budget_ceiling`'s reason: a chapter-level value read off the one
`chapter` row.

**Where the v9 file comes from.** `_V9_DDL` below, built in the test with
`sqlite3` and nothing else - every earlier `test_schema_v*.py`'s precedent
(PO-2). No binary fixture is committed.

**`_V9_DDL` is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v9.py`'s `_V8_DDL` carries the same instruction for
the same reason: the day it is "fixed" to match the current schema is the day
this suite stops testing a migration. Transcribed in RED on 2026-10-31 from
`mangatl.store.schema.DDL` as it shipped at version 9 (MT-119, commit e5297b4),
by printing the module's `DDL` with every line whose first non-blank characters
are `--` removed and runs of blank lines squeezed to one, so the transcription is
mechanical rather than retyped. Its last statement is `CLEANED_ERASED_DDL`'s
`ALTER TABLE`, because that is how `DDL` itself builds `cleaned_page`.

**Timing.** No `pytest-timeout` in this project; each test builds a chapter of
three or four tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_ledger import _PAGE_FILENAMES, _V2_LEDGER_ROWS, _build_v2_file

from mangatl.domain.money import Usd
from mangatl.domain.rates import RATE_TABLE_VERSION, CostRecord
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.project import (
    SCHEMA_VERSION,
    SchemaTooNew,
    create_project,
    open_project,
    project_dir_for,
)

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 5),
)

#: The two priced calls the v9 file holds: (request_id, page ordinal, micro).
#: Different pages and different costs, so a migration that copied rows into
#: the wrong columns, or onto the wrong page, cannot agree with this by luck.
_V9_CALLS: tuple[tuple[str, int, int], ...] = (
    ("req-v9-a", 0, 30_000),
    ("req-v9-b", 1, 45_125),
)

#: The v9 rows' `rate_table_version`, deliberately not today's.
_V9_RATE_VERSION = "2026-10-01"

#: Every schema object the v10 step may touch. Everything else in
#: `sqlite_master` must come through byte for byte.
_V10_OBJECTS: tuple[str, ...] = (
    "chapter",
    "llm_call",
    "llm_call_no_update",
    "llm_call_no_delete",
    "batch_job",
    "correction",
)

#: `batch_job` and `correction` at version 10, as `## Contract` writes them:
#: name -> (type, NOT NULL, pk). Written out here rather than read off
#: `schema.py`, because a shape derived from the thing under test agrees with
#: it by construction.
_BATCH_JOB_SHAPE: dict[str, tuple[str, int, int]] = {
    "id": ("INTEGER", 0, 1),
    "run_id": ("INTEGER", 1, 0),
    "provider_job_id": ("TEXT", 1, 0),
    "model_id": ("TEXT", 1, 0),
    "state": ("TEXT", 1, 0),
    "submitted_at": ("TEXT", 1, 0),
    "collected_at": ("TEXT", 0, 0),
    "failure": ("TEXT", 0, 0),
}
_CORRECTION_SHAPE: dict[str, tuple[str, int, int]] = {
    "id": ("INTEGER", 0, 1),
    "run_id": ("INTEGER", 1, 0),
    "page_id": ("INTEGER", 1, 0),
    "reading_index": ("INTEGER", 1, 0),
    "before_en": ("TEXT", 1, 0),
    "after_en": ("TEXT", 1, 0),
    "reason": ("TEXT", 1, 0),
    "at": ("TEXT", 1, 0),
}

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V9_DDL = """
CREATE TABLE chapter (
    id                       INTEGER PRIMARY KEY,
    source_dir               TEXT    NOT NULL,
    output_dir               TEXT    NOT NULL,
    created_at               TEXT    NOT NULL,
    schema_version           INTEGER NOT NULL,
    budget_ceiling_micro_usd INTEGER,
    model_id                 TEXT,
    rate_table_version       TEXT
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
    excluded      TEXT CHECK (excluded IS NULL OR excluded IN ('watermark', 'user')),
    UNIQUE (page_id, reading_index)
);

CREATE TABLE line (
    id          INTEGER PRIMARY KEY,
    region_id   INTEGER NOT NULL UNIQUE REFERENCES region(id) ON DELETE CASCADE,
    source_ja   TEXT    NOT NULL,
    proposed_en TEXT,
    final_en    TEXT,
    edited_at   TEXT,
    viewed_at   TEXT,
    ocr_empty   INTEGER NOT NULL DEFAULT 0,
    status      TEXT CHECK (status IS NULL OR status IN ('accepted', 'edited', 'reverted'))
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
    cost_micro_usd     INTEGER NOT NULL,
    rate_table_version TEXT    NOT NULL DEFAULT '',
    at                 TEXT    NOT NULL
);

CREATE TRIGGER llm_call_no_update
BEFORE UPDATE ON llm_call
BEGIN
    SELECT RAISE(ABORT, 'llm_call is append-only');
END;

CREATE TRIGGER llm_call_no_delete
BEFORE DELETE ON llm_call
BEGIN
    SELECT RAISE(ABORT, 'llm_call is append-only');
END;

CREATE TABLE glossary (
    id              INTEGER PRIMARY KEY,
    chapter_id      INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
    term_ja         TEXT    NOT NULL,
    term_en         TEXT    NOT NULL,
    note            TEXT,
    first_seen_page INTEGER NOT NULL,
    last_seen_page  INTEGER NOT NULL DEFAULT 0,
    source          TEXT    NOT NULL DEFAULT 'model' CHECK (source IN ('model', 'user')),
    UNIQUE (chapter_id, term_ja)
);

CREATE TABLE cleaned_page (
    page_id    INTEGER PRIMARY KEY REFERENCES page(id) ON DELETE CASCADE,
    image_blob BLOB    NOT NULL
);
ALTER TABLE cleaned_page ADD COLUMN erased TEXT NOT NULL DEFAULT '[]';
"""


# -- helpers -------------------------------------------------------------------------


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Run `sql` through a plain `sqlite3` connection that knows nothing of
    `mangatl.store`, committing on success."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _user_version(db_path: Path) -> int:
    return int(str(_raw(db_path, "PRAGMA user_version")[0][0]))


def _declaration(db_path: Path, name: str) -> str:
    """`name`'s stored `CREATE` statement, runs of whitespace collapsed; `""`
    when the object does not exist, so a comparison of two absences cannot
    pass for agreement (every caller also asserts it is non-empty)."""
    rows = _raw(db_path, "SELECT sql FROM sqlite_master WHERE name = ?", (name,))
    return " ".join(str(rows[0][0]).split()) if rows else ""


def _table_info(db_path: Path, table: str) -> list[tuple[object, ...]]:
    """(name, type, notnull, dflt_value, pk) in declaration order."""
    return _raw(
        db_path,
        'SELECT name, type, "notnull", dflt_value, pk FROM pragma_table_info(?)',
        (table,),
    )


def _shape(db_path: Path, table: str) -> dict[str, tuple[str, int, int]]:
    return {
        str(name): (str(kind).upper(), int(str(notnull)), int(str(pk)))
        for name, kind, notnull, _default, pk in _table_info(db_path, table)
    }


def _triggers_on_llm_call(db_path: Path) -> set[str]:
    return {
        str(name)
        for (name,) in _raw(
            db_path,
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'llm_call'",
        )
    }


def _sources(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    name: str,
    pages: tuple[tuple[str, int, int], ...] = _SOURCE_PAGES,
) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    for filename, width, height in pages:
        (directory / filename).write_bytes(png_bytes(width, height))
    return directory


def _fresh(source_dir: Path) -> Path:
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)):
        pass
    return project_dir_for(source_dir) / "project.db"


def _build_v9_file(source_dir: Path) -> Path:
    """A schema-version-9 file built with `_V9_DDL` and nothing else: every page
    `done`, one run, the two priced calls of `_V9_CALLS`, one glossary term, a
    region with its line on page 0 and page 0's cleaned image - a run v9
    chapter, so "the step touches nothing else" has rows to be wrong about."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V9_DDL)
        connection.execute("PRAGMA user_version = 9")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version,"
            " budget_ceiling_micro_usd, model_id, rate_table_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(source_dir),
                str(source_dir) + "_en",
                "2026-10-31T00:00:00+00:00",
                9,
                2_000_000,
                "gemini-3.1-pro-preview",
                _V9_RATE_VERSION,
            ),
        )
        chapter_id = cursor.lastrowid
        page_ids: list[int] = []
        for page in read_chapter(source_dir).pages:
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
                    "done",
                ),
            )
            page_ids.append(int(cursor.lastrowid or 0))
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at, ended_at, outcome) VALUES (?, ?, ?, ?)",
            (chapter_id, "2026-10-31T00:00:01+00:00", "2026-10-31T00:05:00+00:00", "completed"),
        )
        run_id = cursor.lastrowid
        for request_id, ordinal, micro in _V9_CALLS:
            cursor.execute(
                "INSERT INTO llm_call (run_id, page_id, request_id, model_id, input_tokens,"
                " output_tokens, cache_write_tokens, cache_read_tokens, cost_micro_usd,"
                " rate_table_version, at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    page_ids[ordinal],
                    request_id,
                    "gemini-3.1-pro-preview",
                    1000 + ordinal,
                    400 + ordinal,
                    ordinal,
                    2 * ordinal,
                    micro,
                    _V9_RATE_VERSION,
                    f"2026-10-31T00:0{ordinal + 2}:00+00:00",
                ),
            )
        cursor.execute(
            "INSERT INTO glossary (chapter_id, term_ja, term_en, first_seen_page,"
            " last_seen_page, source) VALUES (?, ?, ?, ?, ?, ?)",
            (chapter_id, "先輩", "senpai", 0, 1, "model"),
        )
        cursor.execute(
            "INSERT INTO region"
            " (page_id, reading_index, polygon, mask_blob, kind, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (page_ids[0], 0, "[[0,0],[2,0],[2,2],[0,2],[0,0]]", b"mask", "bubble", 0.5),
        )
        cursor.execute(
            "INSERT INTO line (region_id, source_ja, proposed_en) VALUES (?, ?, ?)",
            (cursor.lastrowid, "せりふ", "A line."),
        )
        cursor.execute(
            "INSERT INTO cleaned_page (page_id, image_blob, erased) VALUES (?, ?, ?)",
            (page_ids[0], b"page zero cleaned", "[0]"),
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


def _migrated(source_dir: Path) -> Path:
    """Build a v9 file and open it once, asserting a migration RAN - without
    which every assertion downstream is about a file nobody touched."""
    db_path = _build_v9_file(source_dir)
    assert _user_version(db_path) == 9
    assert "pricing" not in _declaration(db_path, "llm_call"), "the v9 fixture is already v10"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 10, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


def _chapter_call(micro: int) -> CostRecord:
    return CostRecord(
        model_id="gemini-3.1-pro-preview",
        input_tokens=20_000,
        output_tokens=3_000,
        cache_write_tokens=0,
        cache_read_tokens=0,
        cost=Usd.from_micro(micro),
        rate_table_version=RATE_TABLE_VERSION,
    )


# -- the version, and the fresh tables -----------------------------------------------


def test_this_build_writes_and_reads_schema_version_ten(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """MT-103's bump (PO-1), in both records of it (MT-005 PO-7)."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert SCHEMA_VERSION == 10
    assert _user_version(db_path) == 10
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(10,)]


def test_a_fresh_ledger_has_a_nullable_page_and_a_not_null_standard_pricing_column(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """`page_id` NOT NULL is 0 (a chapter row has no page) and is still a
    foreign key to `page`; `pricing` is `TEXT NOT NULL DEFAULT 'standard'`.
    Every other column keeps its v9 declaration."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))
    declared = {str(row[0]): row for row in _table_info(db_path, "llm_call")}

    assert declared["page_id"][1:4] == ("INTEGER", 0, None), declared["page_id"]
    assert declared["pricing"][1:4] == ("TEXT", 1, "'standard'"), declared.get("pricing")
    assert ("page", "page_id", "id") in {
        (str(row[2]), str(row[3]), str(row[4]))
        for row in _raw(db_path, "SELECT * FROM pragma_foreign_key_list('llm_call')")
    }
    assert declared["run_id"][1:3] == ("INTEGER", 1)
    assert declared["cost_micro_usd"][1:3] == ("INTEGER", 1)


def test_a_fresh_file_has_the_batch_job_and_correction_tables_as_contracted(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """`## Contract`'s two CREATE TABLEs, column for column: type, NOT NULL and
    primary key. `collected_at` and `failure` are the only nullable columns a
    job has - a submitted job has neither."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _shape(db_path, "batch_job") == _BATCH_JOB_SHAPE
    assert _shape(db_path, "correction") == _CORRECTION_SHAPE


def test_a_fresh_chapter_has_a_nullable_glossary_proposed_at_column(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _shape(db_path, "chapter")["glossary_proposed_at"] == ("TEXT", 0, 0)
    assert _raw(db_path, "SELECT glossary_proposed_at FROM chapter") == [(None,)]


# -- AC-1: the v9 -> v10 step --------------------------------------------------------


def test_a_version_nine_file_is_migrated_to_ten_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: "its `schema_version` is 10" - in both records of it."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(10,)]


def test_both_calls_a_version_nine_file_held_read_back_standard_on_their_page_at_their_cost(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: both v9 calls read back `pricing == "standard"`, on the page
    they were billed to (joined to its ordinal, so a copy that shifted
    `page_id` is caught) and at their cost, with every other column of theirs
    as it was. Read by a plain `sqlite3` reader."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    rows = _raw(
        db_path,
        "SELECT llm_call.request_id, page.ordinal, llm_call.cost_micro_usd, llm_call.pricing,"
        " llm_call.rate_table_version FROM llm_call JOIN page ON page.id = llm_call.page_id"
        " ORDER BY llm_call.id",
    )
    assert rows == [
        (request_id, ordinal, micro, "standard", _V9_RATE_VERSION)
        for request_id, ordinal, micro in _V9_CALLS
    ]


def test_a_migrated_ledger_still_refuses_update_and_delete(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: the `llm_call` rebuild keeps both append-only triggers - by
    name, and by refusing a real `UPDATE`, a real `DELETE` and a blanket
    `DELETE` (SQLite truncates an unqualified delete past row triggers unless a
    delete trigger exists). Nothing changes underneath the refusals."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _triggers_on_llm_call(db_path) == {"llm_call_no_update", "llm_call_no_delete"}

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _raw(db_path, "UPDATE llm_call SET cost_micro_usd = 1 WHERE request_id = 'req-v9-a'")
    assert "append-only" in str(excinfo.value), str(excinfo.value)

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _raw(db_path, "UPDATE llm_call SET pricing = 'batch'")
    assert "append-only" in str(excinfo.value), str(excinfo.value)

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _raw(db_path, "DELETE FROM llm_call WHERE request_id = 'req-v9-b'")
    assert "append-only" in str(excinfo.value), str(excinfo.value)

    with pytest.raises(sqlite3.IntegrityError):
        _raw(db_path, "DELETE FROM llm_call")

    assert _raw(db_path, "SELECT request_id, cost_micro_usd FROM llm_call ORDER BY id") == [
        (request_id, micro) for request_id, _ordinal, micro in _V9_CALLS
    ]


def test_the_same_statements_against_the_migrated_page_table_still_succeed(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The **negative control** for the test above: a migration that left the
    file read-only, or a trigger on every table, would make every refusal
    there pass. `page` is updated by the product all the time and must still
    take an `UPDATE` and a `DELETE` (page 2 has no ledger row, region or image,
    so nothing references it)."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    _raw(db_path, "UPDATE page SET status = 'stale' WHERE ordinal = 0")
    assert _raw(db_path, "SELECT status FROM page WHERE ordinal = 0") == [("stale",)]

    _raw(db_path, "DELETE FROM page WHERE ordinal = 2")
    assert _raw(db_path, "SELECT COUNT(*) FROM page") == [(2,)]


def test_a_migrated_ledger_takes_a_chapter_level_call(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1 with AC-2**: on a migrated file `page_id` is nullable in fact,
    not just in a fresh declaration - a chapter row is recorded, totalled, and
    kept out of the page samples alongside the two v9 rows."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _migrated(source_dir)
    assert [row[2] for row in _table_info(db_path, "llm_call") if row[0] == "page_id"] == [0]

    with open_project(project_dir_for(source_dir)) as project:
        record_call(project, 1, None, "req-glossary", _chapter_call(500_000))

        assert chapter_call_costs(project) == (Usd.from_micro(30_000), Usd.from_micro(45_125))
        assert chapter_total(project) == Usd.from_micro(30_000 + 45_125 + 500_000)
    assert _raw(db_path, "SELECT page_id FROM llm_call WHERE request_id = 'req-glossary'") == [
        (None,)
    ]


def test_a_migrated_chapter_has_glossary_proposed_at_null(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: the column exists on the migrated `chapter` and is NULL - no
    v9 file ever ran the pre-pass - and the store reads it as `None`. The
    chapter's other values survive the step."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _migrated(source_dir)

    assert _shape(db_path, "chapter")["glossary_proposed_at"] == ("TEXT", 0, 0)
    assert _raw(
        db_path,
        "SELECT glossary_proposed_at, budget_ceiling_micro_usd, model_id, rate_table_version"
        " FROM chapter",
    ) == [(None, 2_000_000, "gemini-3.1-pro-preview", _V9_RATE_VERSION)]
    with open_project(project_dir_for(source_dir)) as project:
        assert project.glossary_proposed_at() is None


def test_a_migrated_file_has_empty_batch_job_and_correction_tables_as_contracted(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _shape(db_path, "batch_job") == _BATCH_JOB_SHAPE
    assert _shape(db_path, "correction") == _CORRECTION_SHAPE
    assert _raw(db_path, "SELECT COUNT(*) FROM batch_job") == [(0,)]
    assert _raw(db_path, "SELECT COUNT(*) FROM correction") == [(0,)]


def test_a_fresh_file_and_a_migrated_one_store_the_same_declarations(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: `sqlite_master.sql`, whitespace collapsed, for `llm_call`,
    `batch_job` and `correction` - and for the two triggers and `chapter`,
    which the same step rebuilds or alters. Each must be present, so two files
    cannot agree on an absence; and the column lists agree in order, so a
    `SELECT *` reads the same on both."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"))
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))

    for name in _V10_OBJECTS:
        assert _declaration(fresh, name), f"a fresh file has no {name}"
        assert _declaration(migrated, name) == _declaration(fresh, name), name
    for table in ("chapter", "llm_call", "batch_job", "correction"):
        assert _table_info(migrated, table) == _table_info(fresh, table), table


def test_the_v10_step_changes_nothing_outside_the_objects_it_owns(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The step rebuilds `llm_call`, alters `chapter` and creates two tables.
    No other schema object changes, no row of any other table changes, and the
    ledger's rows keep every v9 column's value."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v9_file(source_dir)
    owned = ", ".join(f"'{name}'" for name in _V10_OBJECTS)
    schema = f"SELECT type, name, sql FROM sqlite_master WHERE name NOT IN ({owned}) ORDER BY name"
    tables = ("page", "region", "line", "run", "glossary", "cleaned_page")
    v9_ledger = (
        "SELECT id, run_id, page_id, request_id, model_id, input_tokens, output_tokens,"
        " cache_write_tokens, cache_read_tokens, cost_micro_usd, rate_table_version, at"
        " FROM llm_call ORDER BY id"
    )
    v9_chapter = (
        "SELECT id, source_dir, output_dir, created_at, budget_ceiling_micro_usd, model_id,"
        " rate_table_version FROM chapter"
    )

    def rows() -> dict[str, list[tuple[object, ...]]]:
        return {table: _raw(db_path, f"SELECT * FROM {table} ORDER BY rowid") for table in tables}

    before = (_raw(db_path, schema), rows(), _raw(db_path, v9_ledger), _raw(db_path, v9_chapter))
    assert before[1]["region"] != [], "the v9 fixture has no regions to preserve"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 10
    assert _raw(db_path, schema) == before[0]
    assert rows() == before[1]
    assert _raw(db_path, v9_ledger) == before[2]
    assert _raw(db_path, v9_chapter) == before[3]


def test_a_version_two_file_migrates_all_the_way_to_ten(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The shared-string trap: a v2 file runs the v2 -> v3 step (which runs
    `LLM_CALL_DDL`) and the v3 -> v4 step (which runs `CHAPTER_DDL`) before
    the v10 step. With `pricing` or `glossary_proposed_at` written into either
    string, this open dies on `duplicate column name`. It arrives at 10 with
    the fresh file's declarations and the v2 ledger's costs, now `standard`."""
    pages = tuple((name, 40, 30) for name in _PAGE_FILENAMES)
    source_dir = _sources(tmp_path, png_bytes, "v2", pages)
    db_path = _build_v2_file(source_dir)
    assert _user_version(db_path) == 2

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 10
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh", pages))
    for name in _V10_OBJECTS:
        assert _declaration(db_path, name) == _declaration(fresh, name), name
    assert _raw(
        db_path, "SELECT request_id, cost_micro_usd, pricing FROM llm_call ORDER BY id"
    ) == [(request_id, micro, "standard") for request_id, _cost, micro in _V2_LEDGER_ROWS]


# -- AC-1: a version-11 file ---------------------------------------------------------


def test_a_file_one_version_newer_than_ten_is_refused(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: a file at version 11 raises `SchemaTooNew` naming both
    numbers, and is left at 11 - the refusal migrates nothing."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    _raw(db_path, "PRAGMA user_version = 11")
    assert _user_version(db_path) == 11

    with pytest.raises(SchemaTooNew) as excinfo:
        open_project(project_dir_for(source_dir))

    # Anchored to the words around each number: the message also carries the
    # file's path, and a bare `10` or `11` can match a pytest temp dir.
    message = str(excinfo.value)
    assert re.search(r"\bversion 11\b", message), message
    assert re.search(r"\bsupports 10\b", message), message
    assert _user_version(db_path) == 11


def test_the_same_file_at_version_ten_opens(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The control for the refusal above: a store that raised `SchemaTooNew`
    for every file - or for every file at 10 - would pass it."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    assert _user_version(db_path) == 10

    with open_project(project_dir_for(source_dir)) as project:
        assert len(project.pages()) == len(_SOURCE_PAGES)


# -- AC-6: the glossary pre-pass marker ----------------------------------------------


def test_a_fresh_project_has_not_proposed_its_glossary(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-6**: `None`, not an empty string and not a timestamp of creation."""
    with create_project(
        read_chapter(_sources(tmp_path, png_bytes, "scans")),
        project_dir_for(tmp_path / "scans"),
    ) as project:
        assert project.glossary_proposed_at() is None


def test_marking_the_glossary_proposed_stores_a_utc_iso_timestamp_of_now(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-6**: the value is an ISO-8601 instant that parses, is aware, is UTC
    (offset zero) and falls between the clock before and after the call - and
    it is what is on disk, read by a plain `sqlite3` reader."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        before = datetime.now(UTC)
        project.mark_glossary_proposed()
        after = datetime.now(UTC)
        stored = project.glossary_proposed_at()

    assert isinstance(stored, str), stored
    stamped = datetime.fromisoformat(stored)
    assert stamped.utcoffset() is not None, f"{stored} is a naive timestamp"
    assert stamped.utcoffset() == UTC.utcoffset(None), f"{stored} is not UTC"
    assert before <= stamped <= after, (before, stored, after)
    assert _raw(
        project_dir_for(source_dir) / "project.db", "SELECT glossary_proposed_at FROM chapter"
    ) == [(stored,)]


def test_the_glossary_marker_reads_back_the_same_value_twice_and_after_a_reopen(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-6**: "a second read returns the same value" - in the same session
    and in the next one, which is the crash between the pre-pass and page 1
    that MT-103 `## Context` (5) names. A marker that lived in memory, or that
    re-stamped itself on every read, fails one half or the other."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        project.mark_glossary_proposed()
        first = project.glossary_proposed_at()
        second = project.glossary_proposed_at()

    with open_project(project_dir_for(source_dir)) as reopened:
        third = reopened.glossary_proposed_at()

    assert first is not None
    assert first == second == third
