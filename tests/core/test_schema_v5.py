"""MT-014 C-7: schema version 5, and the v4 -> v5 step that gives `glossary`
the two columns AC-2 and AC-3 read.

`last_seen_page` is what "least-recently-**seen**" eviction sorts on (AC-3), and
`source` is what lets a user's rendering outlive every model one (PO-3). Both
are appended with `ALTER TABLE ... ADD COLUMN`, and C-7 asks for three things of
the result, each of which is silent if it is got wrong:

1. **a migrated table is the same table as a fresh one** - same columns, same
   order, same types, same NOT NULL, same DEFAULT - because a `SELECT *` must not
   behave differently on a project a user created last month (MT-010's ordering
   invariant, the fourth time this project has needed it);
2. **a migrated row's `last_seen_page` is its `first_seen_page`**, not the
   column's `DEFAULT 0`. The fixture's rows are deliberately first seen on pages
   3 and 7: a fixture first seen on page 0 - as MT-044's v3 fixture happens to
   be - cannot tell the `UPDATE` from the default, and every existing entry
   would read as last seen on page 0, the stalest possible, and be evicted first;
3. **the CHECK arrives with the column** on both paths, so `source` is `'model'`
   or `'user'` and nothing else in a migrated file as in a fresh one.

The v1 -> v5 walk (C-7: "a v1 file walks to v5 in one open") is asserted in
`tests/core/test_line_store.py`, beside the v1 fixture it needs.

**`_V4_DDL` below is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v4.py`'s `_V3_DDL`, `test_ledger.py`'s `_V2_DDL`
and `test_line_store.py`'s `_V1_DDL` carry the same instruction, for the same
reason. The day someone "fixes" it to match the current schema is the day this
stops testing a migration. Transcribed in RED from `src/mangatl/store/schema.py`
as it shipped at version 4 (MT-044), comments dropped.

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so
there is no budget in this file to size. Each test builds a two-page chapter of
tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from mangatl.domain.glossary import GlossaryEntry
from mangatl.store.glossary import read_entries
from mangatl.store.intake import read_chapter
from mangatl.store.project import SCHEMA_VERSION, create_project, open_project, project_dir_for

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
)

#: `glossary`'s columns **in declaration order** at version 5 (C-7: "appended
#: last").
_GLOSSARY_COLUMNS_V5: tuple[str, ...] = (
    "id",
    "chapter_id",
    "term_ja",
    "term_en",
    "note",
    "first_seen_page",
    "last_seen_page",
    "source",
)

#: The v4 fixture's glossary rows: `(term_ja, term_en, note, first_seen_page)`.
#: Neither is first seen on page 0 - see the module docstring, point 2 - and one
#: has a NULL note, which the store must read as `""`.
_V4_ROWS: tuple[tuple[str, str, str | None, int], ...] = (
    ("さくら", "Sakura", "name", 3),
    ("醜鬼", "Ugly Ogre", None, 7),
)

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V4_DDL = """
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
    ocr_empty   INTEGER NOT NULL DEFAULT 0
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
    UNIQUE (chapter_id, term_ja)
);
"""

#: One row per column: name, type, NOT NULL, DEFAULT. The shape a migrated
#: table has to share with a fresh one. CHECK constraints are not in
#: `table_info`, which is why `_check_rejects_other_sources` exists.
_SHAPE = "SELECT name, type, \"notnull\", dflt_value FROM pragma_table_info('glossary')"


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _user_version(db_path: Path) -> int:
    return int(_raw(db_path, "PRAGMA user_version")[0][0])


def _columns(db_path: Path) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in _raw(db_path, "PRAGMA table_info(glossary)"))


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


def _build_v4_file(source_dir: Path) -> Path:
    """A schema-version-4 file, built with `_V4_DDL` and nothing else, carrying
    `_V4_ROWS` in its glossary."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V4_DDL)
        connection.execute("PRAGMA user_version = 4")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version)"
            " VALUES (?, ?, ?, ?)",
            (str(source_dir), str(source_dir) + "_en", "2026-09-28T00:00:00+00:00", 4),
        )
        chapter_id = cursor.lastrowid
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
                    "pending",
                ),
            )
        for term_ja, term_en, note, first_seen_page in _V4_ROWS:
            cursor.execute(
                "INSERT INTO glossary (chapter_id, term_ja, term_en, note, first_seen_page)"
                " VALUES (?, ?, ?, ?, ?)",
                (chapter_id, term_ja, term_en, note, first_seen_page),
            )
        connection.commit()
    finally:
        connection.close()
    return db_path


def _migrated(source_dir: Path) -> Path:
    """Build a v4 file and open it once, asserting that a migration **ran** -
    without which every assertion downstream is about a file nobody touched
    (MT-044 R-9's lesson, one version on)."""
    db_path = _build_v4_file(source_dir)
    assert _user_version(db_path) == 4
    assert "last_seen_page" not in _columns(db_path), "the v4 fixture is already v5"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 5, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


def _check_rejects_other_sources(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        chapter_id = connection.execute("SELECT id FROM chapter").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO glossary (chapter_id, term_ja, term_en, first_seen_page, source)"
                " VALUES (?, ?, ?, ?, ?)",
                (chapter_id, "ロボ", "Robo", 1, "robot"),
            )
        # And the two legal values are accepted, so the refusal above is about
        # the value and not about the table being unwritable.
        for term_ja, source in (("ゆき", "user"), ("けんじ", "model")):
            connection.execute(
                "INSERT INTO glossary (chapter_id, term_ja, term_en, first_seen_page, source)"
                " VALUES (?, ?, ?, ?, ?)",
                (chapter_id, term_ja, term_ja, 1, source),
            )
        connection.rollback()
    finally:
        connection.close()


# -- the version, and the fresh table --------------------------------------------


def test_this_build_writes_and_reads_schema_version_five(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-7's bump, stated where a reader looks for it, in both records of it."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert SCHEMA_VERSION == 5
    assert _user_version(db_path) == 5
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(5,)]


def test_a_fresh_glossary_table_has_the_two_new_columns_last_and_typed_as_c7_says(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-7's DDL, read off the table: `last_seen_page INTEGER NOT NULL DEFAULT
    0` and `source TEXT NOT NULL DEFAULT 'model'`, appended after
    `first_seen_page` - the only position in which a fresh file and an
    `ADD COLUMN`-migrated one can agree."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _columns(db_path) == _GLOSSARY_COLUMNS_V5
    shape = {str(row[0]): row[1:] for row in _raw(db_path, _SHAPE)}
    assert shape["last_seen_page"] == ("INTEGER", 1, "0")
    assert shape["source"] == ("TEXT", 1, "'model'")
    assert shape["note"] == ("TEXT", 0, None), "C-7: note stays nullable"


def test_a_fresh_file_refuses_a_source_that_is_neither_model_nor_user(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-7's `CHECK (source IN ('model', 'user'))`."""
    _check_rejects_other_sources(_fresh(_sources(tmp_path, png_bytes, "scans")))


# -- the v4 -> v5 step ------------------------------------------------------------


def test_a_version_four_file_is_migrated_to_five_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """In place, on open, with no separate command - the fifth time."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(5,)]
    assert _columns(db_path) == _GLOSSARY_COLUMNS_V5


def test_a_migrated_glossary_table_is_the_same_table_as_a_fresh_one(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-7: "identical in a fresh file and a migrated one" - every column's
    name, type, NOT NULL and DEFAULT, in the same order. Two projects under one
    `tmp_path`, so nothing about the comparison depends on either path."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"))
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))

    assert _raw(migrated, _SHAPE) == _raw(fresh, _SHAPE)


def test_a_migrated_row_was_last_seen_on_the_page_it_was_first_seen_on(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-7's `UPDATE glossary SET last_seen_page = first_seen_page`, and the
    reason the fixture's rows are first seen on pages 3 and 7: without the
    `UPDATE` they read back as last seen on page 0 - the column default - and
    are the first thing AC-3 evicts. Every existing row is a model's, because
    no user edit could reach the glossary before this story."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(
        db_path,
        "SELECT term_ja, term_en, note, first_seen_page, last_seen_page, source"
        " FROM glossary ORDER BY id",
    ) == [
        ("さくら", "Sakura", "name", 3, 3, "model"),
        ("醜鬼", "Ugly Ogre", None, 7, 7, "model"),
    ]


def test_a_migrated_glossary_reads_back_through_the_store(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The same rows through `read_entries`, including C-7's "the store reads
    NULL as `""`" on a row written before this story existed."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    _migrated(source_dir)

    with open_project(project_dir_for(source_dir)) as project:
        assert read_entries(project) == [
            GlossaryEntry("さくら", "Sakura", "name", 3, 3, "model"),
            GlossaryEntry("醜鬼", "Ugly Ogre", "", 7, 7, "model"),
        ]


def test_a_migrated_file_refuses_a_source_that_is_neither_model_nor_user(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The CHECK arrives with the column on the migration path too - which
    `table_info` cannot show, so it is asserted by what the file refuses."""
    _check_rejects_other_sources(_migrated(_sources(tmp_path, png_bytes, "scans")))


def test_the_v5_step_leaves_every_other_table_alone(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-7 is two `ADD COLUMN`s and an `UPDATE`; nothing else in the file has
    any business changing. Compared on `sqlite_master`, so a migration written
    as a rebuild of anything else - or a re-run of an earlier step - is caught."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v4_file(source_dir)
    query = "SELECT type, name, sql FROM sqlite_master WHERE name != 'glossary' ORDER BY name"
    before = _raw(db_path, query)

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 5
    assert _raw(db_path, query) == before
