"""MT-115: schema version 12, and the v11 -> v12 step - the consistency marker.

The pass runs once per chapter (AC-6), and what says it ran is one nullable
column, `chapter.consistency_run_id INTEGER REFERENCES run(id)` (the story's
pinned `## Contract`): `NULL` until a pass completes, then the `run` that ran
it. Added by `ALTER TABLE ... ADD COLUMN` - in the fresh DDL as
`glossary_proposed_at` is, and as `_MIGRATE_TO_V12` in `_MIGRATIONS` - so a
fresh file and a migrated one store the same `sqlite_master.sql`. Every
migrated chapter reads `NULL`, "the pass has not run", which is the truth about
a file no earlier version could run it on.

`Project.consistency_run_id()` is a read with no transaction
(`glossary_proposed_at`'s shape); `Project.mark_consistency_run(run_id)` writes
it in its own transaction, committed before it returns.

**Where the v11 file comes from.** `_V11_DDL` below, built in the test with
`sqlite3` and nothing else - every earlier `test_schema_v*.py`'s precedent. No
binary fixture is committed.

**`_V11_DDL` is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v11.py`'s `_V10_DDL` carries the same instruction
for the same reason: the day it is "fixed" to match the current schema is the
day this suite stops testing a migration. Transcribed in RED on 2026-11-05 from
`mangatl.store.schema.DDL` as it shipped at version 11 (MT-137, last changed in
commit 591136b), by printing the module's `DDL` with every line whose first
non-blank characters are `--` removed and runs of blank lines squeezed to one,
so the transcription is mechanical rather than retyped.

**RED.** `SCHEMA_VERSION` is 11 and no step to 12 exists, so every test here
fails on the version, the absent column, or the absent `Project` methods.

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

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 5),
    ("p4.png", 9, 4),
)

#: `chapter` at version 12, in declaration order: (name, type, NOT NULL,
#: default, pk). Written out here rather than read off `schema.py`, because a
#: shape derived from the thing under test agrees with it by construction.
_CHAPTER_V12_COLUMNS: list[tuple[object, ...]] = [
    ("id", "INTEGER", 0, None, 1),
    ("source_dir", "TEXT", 1, None, 0),
    ("output_dir", "TEXT", 1, None, 0),
    ("created_at", "TEXT", 1, None, 0),
    ("schema_version", "INTEGER", 1, None, 0),
    ("budget_ceiling_micro_usd", "INTEGER", 0, None, 0),
    ("model_id", "TEXT", 0, None, 0),
    ("rate_table_version", "TEXT", 0, None, 0),
    ("glossary_proposed_at", "TEXT", 0, None, 0),
    ("consistency_run_id", "INTEGER", 0, None, 0),
]

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V11_DDL = """
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
    failure         TEXT,
    first_ordinal   INTEGER NOT NULL,
    last_ordinal    INTEGER NOT NULL,
    CHECK (first_ordinal >= 0 AND first_ordinal <= last_ordinal)
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
    `mangatl.store`, with foreign keys on, committing on success."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _user_version(db_path: Path) -> int:
    return int(str(_raw(db_path, "PRAGMA user_version")[0][0]))


def _schema(db_path: Path) -> list[tuple[object, ...]]:
    """Every `sqlite_master` entry, its `sql` with runs of whitespace
    collapsed, by name."""
    return [
        (kind, name, table, None if sql is None else " ".join(str(sql).split()))
        for kind, name, table, sql in _raw(
            db_path, "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
        )
    ]


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


def _insert_run(db_path: Path) -> int:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            cursor = connection.execute(
                "INSERT INTO run (chapter_id, started_at)"
                " SELECT id, '2026-11-05T09:00:00+00:00' FROM chapter"
            )
            return int(cursor.lastrowid or 0)
    finally:
        connection.close()


def _build_v11_file(source_dir: Path) -> Path:
    """A schema-version-11 file built with `_V11_DDL` and nothing else: four
    pages, one run, and one row in every other table that can hold one - a
    ledger call, a batch job, a correction, a glossary term, a region with its
    line, a cleaned image - so "the step touches nothing else" has rows to be
    wrong about."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V11_DDL)
        connection.execute("PRAGMA user_version = 11")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version,"
            " budget_ceiling_micro_usd, model_id, rate_table_version, glossary_proposed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(source_dir),
                str(source_dir) + "_en",
                "2026-11-04T00:00:00+00:00",
                11,
                3_000_000,
                "gemini-3.1-pro-preview",
                "2026-10-01",
                "2026-11-04T00:00:30+00:00",
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
            (chapter_id, "2026-11-04T00:00:01+00:00", "2026-11-04T00:05:00+00:00", "finished"),
        )
        run_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO batch_job (run_id, provider_job_id, model_id, state, submitted_at,"
            " collected_at, failure, first_ordinal, last_ordinal)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, "batches/v11", "gemini-3.1-pro-preview", "collected",
             "2026-11-04T00:01:00+00:00", "2026-11-04T00:03:00+00:00", None, 0, 3),
        )  # fmt: skip
        cursor.execute(
            "INSERT INTO llm_call (run_id, page_id, request_id, model_id, input_tokens,"
            " output_tokens, cache_write_tokens, cache_read_tokens, cost_micro_usd,"
            " rate_table_version, at, pricing) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, None, "req-v11", "gemini-3.1-pro-preview", 1200, 340, 0, 0, 6_480,
             "2026-10-01", "2026-11-04T00:02:00+00:00", "standard"),
        )  # fmt: skip
        cursor.execute(
            "INSERT INTO correction (run_id, page_id, reading_index, before_en, after_en,"
            " reason, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, page_ids[2], 0, "Senpai!", "Sempai!", "consistency",
             "2026-11-04T00:04:00+00:00"),
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
    """Build a v11 file and open it once, asserting a migration RAN - without
    which every assertion downstream is about a file nobody touched."""
    db_path = _build_v11_file(source_dir)
    assert _user_version(db_path) == 11
    assert "consistency_run_id" not in [row[0] for row in _table_info(db_path, "chapter")], (
        "the v11 fixture is already v12"
    )

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 14, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


# -- the version, and the fresh column -----------------------------------------------


def test_this_build_writes_and_reads_the_current_schema_version(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """MT-115's bump, in both records of it (MT-005 PO-7)."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert SCHEMA_VERSION == 14
    assert _user_version(db_path) == 14
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(14,)]


def test_a_fresh_chapter_has_a_nullable_consistency_run_id_last(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """`INTEGER`, nullable, no default, after `glossary_proposed_at` - where
    `ALTER TABLE ... ADD COLUMN` splices it into a migrated file."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _table_info(db_path, "chapter") == _CHAPTER_V12_COLUMNS


def test_a_fresh_chapters_consistency_run_id_is_null(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "SELECT consistency_run_id FROM chapter") == [(None,)]


def test_the_column_references_the_run_table(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """(table, from, to) of the column's one foreign key: `run(id)`."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    keys = [
        (table, source, target)
        for _id, _seq, table, source, target, *_rest in _raw(
            db_path, "SELECT * FROM pragma_foreign_key_list('chapter')"
        )
    ]
    assert keys == [("run", "consistency_run_id", "id")], keys


def test_a_raw_marker_naming_no_run_is_refused_and_one_naming_a_run_is_kept(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The reference in fact, not only in the declaration - and its control:
    a real run id is accepted."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))
    run_id = _insert_run(db_path)

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _raw(db_path, "UPDATE chapter SET consistency_run_id = ?", (run_id + 100,))
    assert "FOREIGN KEY" in str(excinfo.value), str(excinfo.value)

    _raw(db_path, "UPDATE chapter SET consistency_run_id = ?", (run_id,))
    assert _raw(db_path, "SELECT consistency_run_id FROM chapter") == [(run_id,)]


# -- the store's read and write -----------------------------------------------------


def test_a_fresh_project_reports_no_consistency_run(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _sources(tmp_path, png_bytes, "scans")

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        assert project.consistency_run_id() is None  # type: ignore[attr-defined]


def test_marking_the_consistency_run_reads_back_the_run_and_survives_a_reopen(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """Committed before it returns: a plain reader sees it, and so does the
    store after the file is closed and opened again."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = project_dir_for(source_dir) / "project.db"
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        run_id = _insert_run(db_path)
        project.mark_consistency_run(run_id)  # type: ignore[attr-defined]

        assert project.consistency_run_id() == run_id  # type: ignore[attr-defined]
        assert _raw(db_path, "SELECT consistency_run_id FROM chapter") == [(run_id,)]

    with open_project(project_dir_for(source_dir)) as reopened:
        assert reopened.consistency_run_id() == run_id  # type: ignore[attr-defined]


def test_the_marker_holds_the_run_it_was_given_not_the_first_or_the_latest(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = project_dir_for(source_dir) / "project.db"
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        _insert_run(db_path)
        middle = _insert_run(db_path)
        _insert_run(db_path)

        project.mark_consistency_run(middle)  # type: ignore[attr-defined]

        assert project.consistency_run_id() == middle  # type: ignore[attr-defined]


def test_reading_the_marker_opens_no_transaction(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """`glossary_proposed_at`'s shape: a read inside a caller's transaction
    does not trip `transaction()`'s refusal to nest."""
    source_dir = _sources(tmp_path, png_bytes, "scans")

    project_dir = project_dir_for(source_dir)
    with create_project(read_chapter(source_dir), project_dir) as project, project.transaction():
        assert project.consistency_run_id() is None  # type: ignore[attr-defined]


# -- the v11 -> v12 step -------------------------------------------------------------


def test_a_version_eleven_file_is_migrated_to_twelve_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(14,)]


def test_a_fresh_file_and_a_migrated_one_store_the_same_schema(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """Every `sqlite_master` entry agrees, `chapter`'s declaration included -
    present on both, so two files cannot agree on an absence - and the column
    lists agree in order."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"))
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))

    chapter = [entry for entry in _schema(fresh) if entry[1] == "chapter"]
    assert chapter and "consistency_run_id" in str(chapter[0][3]), chapter
    assert _schema(migrated) == _schema(fresh)
    assert _table_info(migrated, "chapter") == _CHAPTER_V12_COLUMNS


def test_a_migrated_chapter_has_not_run_the_pass(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _migrated(source_dir)

    assert _raw(db_path, "SELECT consistency_run_id FROM chapter") == [(None,)]
    with open_project(project_dir_for(source_dir)) as project:
        assert project.consistency_run_id() is None  # type: ignore[attr-defined]


def test_the_v12_step_changes_nothing_but_the_new_column_and_the_version(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """Every other `sqlite_master` entry comes through byte for byte, every
    row of every other table is unchanged, and `chapter` keeps every column
    it had but `schema_version`, which moves from 11 to 12 on purpose.

    Since MT-146 the open walks on to 13, whose step rebuilds `region` with a
    third reason (C-1): its declaration is excluded from the comparison for
    that reason, and `test_schema_v13.py` owns what that step does. Its rows
    are still compared below."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v11_file(source_dir)
    schema = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name != 'chapter'"
    schema += " AND name != 'region' ORDER BY name"
    tables = (
        "page",
        "region",
        "line",
        "run",
        "llm_call",
        "batch_job",
        "correction",
        "glossary",
        "cleaned_page",
    )
    chapter = (
        "SELECT id, source_dir, output_dir, created_at, budget_ceiling_micro_usd, model_id,"
        " rate_table_version, glossary_proposed_at FROM chapter"
    )

    def rows() -> dict[str, list[tuple[object, ...]]]:
        return {table: _raw(db_path, f"SELECT * FROM {table} ORDER BY rowid") for table in tables}

    before = (_raw(db_path, schema), rows(), _raw(db_path, chapter))
    assert all(before[1][table] for table in tables), "the v11 fixture has an empty table"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 14
    assert _raw(db_path, schema) == before[0]
    assert rows() == before[1]
    assert _raw(db_path, chapter) == before[2]


# -- a file one version newer (13 when written; MT-146 moved it to 14, MT-149 to 15) ---


def test_a_file_one_version_newer_than_the_current_one_is_refused(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    _raw(db_path, "PRAGMA user_version = 15")

    with pytest.raises(SchemaTooNew) as excinfo:
        open_project(project_dir_for(source_dir))

    message = str(excinfo.value)
    assert re.search(r"\bversion 15(?!\d)", message), message
    assert re.search(r"\bsupports 14(?!\d)", message), message
    assert _user_version(db_path) == 15


def test_the_same_file_at_the_current_version_opens(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    assert _user_version(db_path) == 14

    with open_project(project_dir_for(source_dir)) as project:
        assert len(project.pages()) == len(_SOURCE_PAGES)
    assert _user_version(db_path) == 14
