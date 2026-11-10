"""MT-137 AC-1 and AC-2: schema version 11, and the v10 -> v11 step.

MT-103 built `batch_job` for one job per volume, and a row did not say which
pages it held because "all of them" was the answer. MT-111 PO-1 splits a volume
into several inline jobs, so a row now carries `first_ordinal` and
`last_ordinal`, the consecutive run of pages it holds, under
`CHECK (first_ordinal >= 0 AND first_ordinal <= last_ordinal)`.

The step **rebuilds** `batch_job` from the fresh DDL (`## Contract`), so a fresh
file and a migrated one store the same `sqlite_master.sql`; and the one row
shape a v10 file can hold - a job that could only ever have held the whole
chapter - is copied as `0 .. page_count - 1`. This suite pins what a rebuild can
get silently wrong: a column list, a CHECK, the copied range, a renumbered id,
a column dropped on the way through, and any object outside `batch_job`.

**Where the v10 file comes from.** `_V10_DDL` below, built in the test with
`sqlite3` and nothing else - every earlier `test_schema_v*.py`'s precedent. No
binary fixture is committed.

**`_V10_DDL` is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v10.py`'s `_V9_DDL` carries the same instruction
for the same reason: the day it is "fixed" to match the current schema is the
day this suite stops testing a migration. Transcribed in RED on 2026-11-03 from
`mangatl.store.schema.DDL` as it shipped at version 10 (MT-103, last changed in
commit 5e78dc7), by printing the module's `DDL` with every line whose first
non-blank characters are `--` removed and runs of blank lines squeezed to one,
so the transcription is mechanical rather than retyped. `chapter`'s
`glossary_proposed_at` and `cleaned_page`'s `erased` are `ALTER TABLE`s because
that is how `DDL` itself builds them.

**Timing.** No `pytest-timeout` in this project; each test builds a chapter of
four tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from mangatl.store.intake import read_chapter
from mangatl.store.project import (
    SCHEMA_VERSION,
    SchemaTooNew,
    create_project,
    open_project,
    project_dir_for,
)

#: Four pages, so a v10 job over "the whole chapter" is pages 0..3. Four rather
#: than one or two so that `COUNT(*)` (4), `COUNT(*) - 1` (3) and a constant `0`
#: are three different answers.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 5),
    ("p4.png", 9, 4),
)

#: `batch_job` at version 11, as AC-1 and `## Contract` write it, in declaration
#: order: (name, type, NOT NULL, default, pk). Written out here rather than read
#: off `schema.py`, because a shape derived from the thing under test agrees with
#: it by construction.
_BATCH_JOB_V11_COLUMNS: list[tuple[object, ...]] = [
    ("id", "INTEGER", 0, None, 1),
    ("run_id", "INTEGER", 1, None, 0),
    ("provider_job_id", "TEXT", 1, None, 0),
    ("model_id", "TEXT", 1, None, 0),
    ("state", "TEXT", 1, None, 0),
    ("submitted_at", "TEXT", 1, None, 0),
    ("collected_at", "TEXT", 0, None, 0),
    ("failure", "TEXT", 0, None, 0),
    ("first_ordinal", "INTEGER", 1, None, 0),
    ("last_ordinal", "INTEGER", 1, None, 0),
]

#: AC-1's CHECK, whitespace collapsed, as it must appear in the stored
#: declaration.
_ORDINAL_CHECK = "CHECK (first_ordinal >= 0 AND first_ordinal <= last_ordinal)"

#: The jobs the v10 file holds: (id, provider_job_id, model_id, state,
#: submitted_at, collected_at, failure). One per state, so "every row is
#: copied" covers both settled shapes as well as the pending one; ids are
#: sparse, so a copy that let `INTEGER PRIMARY KEY` renumber is caught.
_V10_JOBS: tuple[tuple[object, ...], ...] = (
    (3, "batches/v10-collected", "gemini-3.1-pro-preview", "collected",
     "2026-11-01T08:00:00+00:00", "2026-11-01T09:30:00+00:00", None),
    (8, "batches/v10-failed", "gemini-3.1-flash", "failed",
     "2026-11-01T10:00:00+00:00", None, "JOB_STATE_EXPIRED: not collected within 48h"),
    (12, "batches/v10-submitted", "gemini-3.1-pro-preview", "submitted",
     "2026-11-02T07:15:00+00:00", None, None),
)  # fmt: skip

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V10_DDL = """
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
ALTER TABLE chapter ADD COLUMN glossary_proposed_at TEXT;

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
    page_id            INTEGER REFERENCES page(id),
    request_id         TEXT    NOT NULL,
    model_id           TEXT    NOT NULL,
    input_tokens       INTEGER NOT NULL,
    output_tokens      INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    cache_read_tokens  INTEGER NOT NULL,
    cost_micro_usd     INTEGER NOT NULL,
    rate_table_version TEXT    NOT NULL DEFAULT '',
    at                 TEXT    NOT NULL,
    pricing            TEXT    NOT NULL DEFAULT 'standard'
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

CREATE TABLE batch_job (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES run(id),
    provider_job_id TEXT    NOT NULL,
    model_id        TEXT    NOT NULL,
    state           TEXT    NOT NULL CHECK (state IN ('submitted', 'collected', 'failed')),
    submitted_at    TEXT    NOT NULL,
    collected_at    TEXT,
    failure         TEXT
);

CREATE TABLE correction (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES run(id),
    page_id       INTEGER NOT NULL REFERENCES page(id),
    reading_index INTEGER NOT NULL,
    before_en     TEXT    NOT NULL,
    after_en      TEXT    NOT NULL,
    reason        TEXT    NOT NULL,
    at            TEXT    NOT NULL
);

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


def _sources(tmp_path: Path, png_bytes: Callable[..., bytes], name: str) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    for filename, width, height in _SOURCE_PAGES:
        (directory / filename).write_bytes(png_bytes(width, height))
    return directory


def _fresh(source_dir: Path) -> Path:
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)):
        pass
    return project_dir_for(source_dir) / "project.db"


def _fresh_run(db_path: Path) -> int:
    """A `run` row on a fresh file, for raw `batch_job` inserts to reference."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            cursor = connection.execute(
                "INSERT INTO run (chapter_id, started_at)"
                " SELECT id, '2026-11-03T09:00:00+00:00' FROM chapter"
            )
            return int(cursor.lastrowid or 0)
    finally:
        connection.close()


def _raw_job(db_path: Path, run_id: int, first: int, last: int) -> None:
    _raw(
        db_path,
        "INSERT INTO batch_job (run_id, provider_job_id, model_id, state, submitted_at,"
        " first_ordinal, last_ordinal) VALUES (?, ?, ?, 'submitted', ?, ?, ?)",
        (run_id, "batches/raw", "gemini-3.1-pro-preview", "2026-11-03T09:01:00+00:00", first, last),
    )


def _build_v10_file(source_dir: Path) -> Path:
    """A schema-version-10 file built with `_V10_DDL` and nothing else: four
    pages, one run, the three jobs of `_V10_JOBS`, and one row in every other
    table that can hold one - a ledger call, a correction, a glossary term, a
    region with its line, a cleaned image - so "the step touches nothing
    else" has rows to be wrong about."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V10_DDL)
        connection.execute("PRAGMA user_version = 10")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version,"
            " budget_ceiling_micro_usd, model_id, rate_table_version, glossary_proposed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(source_dir),
                str(source_dir) + "_en",
                "2026-11-01T00:00:00+00:00",
                10,
                3_000_000,
                "gemini-3.1-pro-preview",
                "2026-10-01",
                "2026-11-01T00:00:30+00:00",
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
            (chapter_id, "2026-11-01T00:00:01+00:00", "2026-11-01T00:05:00+00:00", "completed"),
        )
        run_id = cursor.lastrowid
        for job in _V10_JOBS:
            cursor.execute(
                "INSERT INTO batch_job (id, run_id, provider_job_id, model_id, state,"
                " submitted_at, collected_at, failure) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job[0], run_id, *job[1:]),
            )
        cursor.execute(
            "INSERT INTO llm_call (run_id, page_id, request_id, model_id, input_tokens,"
            " output_tokens, cache_write_tokens, cache_read_tokens, cost_micro_usd,"
            " rate_table_version, at, pricing) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, page_ids[1], "req-v10", "gemini-3.1-pro-preview", 1200, 340, 0, 0, 27_500,
             "2026-10-01", "2026-11-01T00:02:00+00:00", "batch"),
        )  # fmt: skip
        cursor.execute(
            "INSERT INTO correction (run_id, page_id, reading_index, before_en, after_en,"
            " reason, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, page_ids[2], 0, "Senpai!", "Sempai!", "consistency",
             "2026-11-01T00:04:00+00:00"),
        )  # fmt: skip
        cursor.execute(
            "INSERT INTO glossary (chapter_id, term_ja, term_en, first_seen_page,"
            " last_seen_page, source) VALUES (?, ?, ?, ?, ?, ?)",
            (chapter_id, "先輩", "senpai", 0, 2, "model"),
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
    """Build a v10 file and open it once, asserting a migration RAN - without
    which every assertion downstream is about a file nobody touched."""
    db_path = _build_v10_file(source_dir)
    assert _user_version(db_path) == 10
    assert "first_ordinal" not in _declaration(db_path, "batch_job"), (
        "the v10 fixture is already v11"
    )

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 13, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


# -- AC-1: the version, and the fresh table ------------------------------------------


def test_this_build_writes_and_reads_the_current_schema_version(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: MT-137's bump, in both records of it (MT-005 PO-7). MT-115
    takes it to 12 (`test_schema_v12.py`), MT-146 to 13 (`test_schema_v13.py`)."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert SCHEMA_VERSION == 13
    assert _user_version(db_path) == 13
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(13,)]


def test_a_fresh_batch_job_has_exactly_the_ten_contracted_columns_in_order(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: `id, run_id, provider_job_id, model_id, state, submitted_at,
    collected_at, failure, first_ordinal, last_ordinal` - type, NOT NULL,
    default and primary key, in that order. The two ordinals are `INTEGER NOT
    NULL` with no default: a row that does not say which pages it holds is
    exactly what this story removes."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _table_info(db_path, "batch_job") == _BATCH_JOB_V11_COLUMNS


def test_a_fresh_batch_job_declares_the_ordinal_check(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: the CHECK is in the stored declaration, verbatim once
    whitespace is collapsed - not an equivalent spelling a later comparison
    would have to guess at."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _ORDINAL_CHECK in _declaration(db_path, "batch_job"), _declaration(db_path, "batch_job")


@pytest.mark.parametrize(
    ("first", "last"),
    [(3, 2), (1, 0), (-1, 0), (-1, -1), (-2, 5)],
    ids=["first-past-last", "one-past", "negative-first", "both-negative", "negative-wide"],
)
def test_a_fresh_file_refuses_a_raw_row_the_ordinal_check_forbids(
    tmp_path: Path, png_bytes: Callable[..., bytes], first: int, last: int
) -> None:
    """**AC-1**: the CHECK is enforced by SQLite itself, beneath any store
    function - a raw `INSERT` with `first_ordinal > last_ordinal` or
    `first_ordinal < 0` raises `IntegrityError` naming the CHECK, and leaves
    no row."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))
    run_id = _fresh_run(db_path)

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _raw_job(db_path, run_id, first, last)

    assert "CHECK constraint failed" in str(excinfo.value), str(excinfo.value)
    assert "first_ordinal" in str(excinfo.value), str(excinfo.value)
    assert _raw(db_path, "SELECT COUNT(*) FROM batch_job") == [(0,)]


def test_a_fresh_file_accepts_the_raw_rows_the_ordinal_check_allows(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The **negative control** for the refusals above: a CHECK that refused
    every row - or `first < last` where AC-1 says `<=` - would pass them. A
    one-page job at page 0, a one-page job further in, and a wide run are all
    recorded."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))
    run_id = _fresh_run(db_path)

    for first, last in ((0, 0), (3, 3), (0, 199)):
        _raw_job(db_path, run_id, first, last)

    assert _raw(db_path, "SELECT first_ordinal, last_ordinal FROM batch_job ORDER BY id") == [
        (0, 0),
        (3, 3),
        (0, 199),
    ]


# -- AC-1: the v10 -> v11 step -------------------------------------------------------


def test_a_version_ten_file_is_migrated_to_eleven_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-2**: "reads `user_version` 11" - in both records of the version."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(13,)]


def test_a_fresh_file_and_a_migrated_one_store_the_same_batch_job_declaration(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: `sqlite_master.sql` for `batch_job`, whitespace collapsed, is
    the same on both - present on both, so two files cannot agree on an
    absence - and the column lists agree in order, so a `SELECT *` reads the
    same on both. The migrated file carries the CHECK too."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"))
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))

    assert _declaration(fresh, "batch_job"), "a fresh file has no batch_job"
    assert _declaration(migrated, "batch_job") == _declaration(fresh, "batch_job")
    assert _ORDINAL_CHECK in _declaration(migrated, "batch_job")
    assert _table_info(migrated, "batch_job") == _BATCH_JOB_V11_COLUMNS
    assert _table_info(migrated, "batch_job") == _table_info(fresh, "batch_job")


def test_a_migrated_file_refuses_a_raw_row_the_ordinal_check_forbids(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1** on the migrated file, in fact and not only in its declaration:
    `first > last` and `first < 0` are both refused there too."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    for first, last in ((3, 2), (-1, 0)):
        with pytest.raises(sqlite3.IntegrityError) as excinfo:
            _raw_job(db_path, 1, first, last)
        assert "first_ordinal" in str(excinfo.value), (first, last, str(excinfo.value))
    assert _raw(db_path, "SELECT COUNT(*) FROM batch_job") == [(len(_V10_JOBS),)]


def test_the_v11_step_changes_nothing_outside_batch_job(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**: "the v11 step changes no object outside `batch_job`". Every
    other `sqlite_master` entry - tables, both triggers, every autoindex -
    comes through byte for byte, and every row of every other table is
    unchanged. `chapter` is read on every column but `schema_version`, which
    the step moves from 10 to 11 on purpose (asserted elsewhere).

    Since MT-115 the open walks on to 12, whose step ALTERs `chapter`: its
    declaration is excluded from the comparison for that reason, and
    `test_schema_v12.py` owns what that step does. Its rows are still
    compared, column by column, below. Since MT-146 it walks on to 13, whose
    step rebuilds `region` (C-1): its declaration is excluded for the same
    reason, `test_schema_v13.py` owns that step, and its rows are compared."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v10_file(source_dir)
    schema = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name != 'batch_job'"
    schema += " AND tbl_name != 'batch_job' AND name != 'chapter' AND name != 'region'"
    schema += " ORDER BY name"
    tables = ("page", "region", "line", "run", "llm_call", "correction", "glossary", "cleaned_page")
    chapter = (
        "SELECT id, source_dir, output_dir, created_at, budget_ceiling_micro_usd, model_id,"
        " rate_table_version, glossary_proposed_at FROM chapter"
    )

    def rows() -> dict[str, list[tuple[object, ...]]]:
        return {table: _raw(db_path, f"SELECT * FROM {table} ORDER BY rowid") for table in tables}

    before = (_raw(db_path, schema), rows(), _raw(db_path, chapter))
    assert all(before[1][table] for table in tables), "the v10 fixture has an empty table"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 13
    assert _raw(db_path, schema) == before[0]
    assert rows() == before[1]
    assert _raw(db_path, chapter) == before[2]
    assert _raw(db_path, "SELECT name FROM sqlite_master WHERE name LIKE 'batch_job_%'") == [], (
        "the step left its renamed v10 table behind"
    )


# -- AC-2: the rows a v10 file held --------------------------------------------------


def test_a_v10_submitted_job_over_a_four_page_chapter_reads_back_over_pages_zero_to_three(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-2**: the v10 `submitted` job reads back with `first_ordinal 0,
    last_ordinal 3` - the whole four-page chapter, the only thing a v10 job
    could have held - and every other column unchanged, id included. Read by
    a plain `sqlite3` reader."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    row = _raw(
        db_path,
        "SELECT id, provider_job_id, model_id, state, submitted_at, collected_at, failure,"
        " first_ordinal, last_ordinal FROM batch_job WHERE state = 'submitted'",
    )
    assert row == [
        (12, "batches/v10-submitted", "gemini-3.1-pro-preview", "submitted",
         "2026-11-02T07:15:00+00:00", None, None, 0, 3),
    ]  # fmt: skip


def test_every_job_a_v10_file_held_is_copied_with_the_whole_chapter_and_every_column_kept(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-2** for every row, not only the pending one: the collected and the
    failed job come through too, each over `0 .. 3`, with its own `id`, run,
    provider id, model, state, both timestamps and failure text. A copy that
    filtered on state, renumbered ids, or shifted a column fails here."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))
    run_id = _raw(db_path, "SELECT id FROM run")[0][0]

    assert _raw(
        db_path,
        "SELECT id, run_id, provider_job_id, model_id, state, submitted_at, collected_at,"
        " failure, first_ordinal, last_ordinal FROM batch_job ORDER BY id",
    ) == [(job[0], run_id, *job[1:], 0, 3) for job in _V10_JOBS]


# -- AC-1: a version-14 file (12 when written; MT-115 moved it to 13, MT-146 to 14) --


def test_a_file_one_version_newer_than_the_current_one_is_refused(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """A file at version 14 - one newer than this build since MT-146 - raises
    `SchemaTooNew` naming both numbers, and is left at 14."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    _raw(db_path, "PRAGMA user_version = 14")
    assert _user_version(db_path) == 14

    with pytest.raises(SchemaTooNew) as excinfo:
        open_project(project_dir_for(source_dir))

    # Anchored to the words around each number: the message also carries the
    # file's path, and a bare `11` or `12` can match a pytest temp dir.
    message = str(excinfo.value)
    assert re.search(r"\bversion 14(?!\d)", message), message
    assert re.search(r"\bsupports 13(?!\d)", message), message
    assert _user_version(db_path) == 14


def test_the_same_file_at_the_current_version_opens(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The control for the refusal above: a store that raised `SchemaTooNew`
    for every file - or for every file at 11 - would pass it."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    assert _user_version(db_path) == 13

    with open_project(project_dir_for(source_dir)) as project:
        assert len(project.pages()) == len(_SOURCE_PAGES)
    assert _user_version(db_path) == 13
