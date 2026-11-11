"""MT-149: schema version 14, and the v13 -> v14 step - `line.misaligned`.

A region whose answer entry echoed Japanese that does not match its listing is
**misaligned** (MT-149 AC-3, C-1a): its English is dropped and the line row is
flagged, so that the review row can say *why* it is `failed` (AC-5). The flag
is `line.misaligned INTEGER NOT NULL DEFAULT 0`, and the v13 -> v14 step is one
`ALTER TABLE line ADD COLUMN misaligned INTEGER NOT NULL DEFAULT 0` (C-1).

What this file pins, each against a file read through plain `sqlite3`:

* the version, in both of its records (`PRAGMA user_version` and
  `chapter.schema_version`, MT-005 PO-7);
* the fresh column: INTEGER, NOT NULL, DEFAULT 0, declared last;
* the step: a v13 file opened once is version 14, gains exactly that column,
  every existing line reads `misaligned = 0`, and every row of every table the
  fixture populated comes through otherwise unchanged (ids deliberately out of
  step with reading order, as `test_schema_v13.py`'s are);
* the migrated `line` table has the same shape as a fresh one;
* a file one version newer (15) is refused, and the current one opens.

**Where the v13 file comes from.** `_V13_DDL` below, built with `sqlite3` and
nothing else. **It is a historical artefact and must never be updated to track
`schema.py`** - the day it is "fixed" to match the current schema is the day
this suite stops testing a migration. Transcribed in RED on 2026-11-11 from
`mangatl.store.schema.DDL` as it shipped at version 13 (MT-146; commit
db4e385), by importing that module and printing its `DDL` with every line whose
first non-blank characters are `--` removed and runs of blank lines squeezed to
one - mechanical, not retyped.

**RED.** `SCHEMA_VERSION` is 13 and no step to 14 exists, so every test here
fails on the version or on the missing column - except the refusal control,
and the "unchanged" comparison, which `_open_once`'s assertion that a
migration ran guards.

**Timing.** No `pytest-timeout` in this project; each test builds a chapter of
three tiny PNGs on `tmp_path`.
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
)

#: (name, type, notnull, dflt_value) of the new column, as `table_info` reports
#: it. Written out rather than read off `schema.py`.
_MISALIGNED_SHAPE: tuple[object, ...] = ("misaligned", "INTEGER", 1, "0")

#: The v13 fixture's regions: (id, page index, reading_index, excluded). Ids are
#: neither `1..n` nor in reading order.
_V13_REGIONS: tuple[tuple[int, int, int, str | None], ...] = (
    (21, 0, 0, None),
    (8, 0, 1, "art"),
    (14, 0, 2, None),
    (5, 1, 0, None),
)

#: The v13 fixture's lines: (id, region id, source_ja, proposed_en, final_en,
#: status, ocr_empty). One translated, one edited, one untranslated, one
#: ocr_empty - every kind of row a v13 file can hold before the flag existed.
_V13_LINES: tuple[tuple[int, int, str, str | None, str | None, str | None, int], ...] = (
    (52, 21, "一つ目", "First.", None, None, 0),
    (37, 8, "二つ目", "Second.", "Second!", "edited", 0),
    (44, 14, "三つ目", None, None, None, 0),
    (61, 5, "", None, None, None, 1),
)

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V13_DDL = """
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
ALTER TABLE chapter ADD COLUMN consistency_run_id INTEGER REFERENCES run(id);

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
    excluded      TEXT CHECK (excluded IS NULL OR excluded IN ('watermark', 'user', 'art')),
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


#: One row per `line` column: name, type, NOT NULL, DEFAULT.
_LINE_SHAPE = "SELECT name, type, \"notnull\", dflt_value FROM pragma_table_info('line')"


def _line_columns(db_path: Path) -> list[str]:
    return [str(row[0]) for row in _raw(db_path, _LINE_SHAPE)]


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


def _build_v13_file(source_dir: Path) -> Path:
    """A schema-version-13 file built with `_V13_DDL` and nothing else: three
    pages, `_V13_REGIONS` with `_V13_LINES`, a cleaned image and a glossary
    term."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V13_DDL)
        connection.execute("PRAGMA user_version = 13")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version)"
            " VALUES (?, ?, ?, ?)",
            (str(source_dir), str(source_dir) + "_en", "2026-11-11T00:00:00+00:00", 13),
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
        for region_id, page, reading_index, excluded in _V13_REGIONS:
            cursor.execute(
                "INSERT INTO region (id, page_id, reading_index, polygon, mask_blob, kind,"
                " confidence, excluded) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    region_id,
                    page_ids[page],
                    reading_index,
                    f"[[{region_id}, 0], [{region_id + 2}, 0], [{region_id}, 2]]",
                    b"\x89PNG\r\n\x1a\n" + f"mask of region {region_id}".encode(),
                    "bubble",
                    region_id / 100,
                    excluded,
                ),
            )
        for row in _V13_LINES:
            cursor.execute(
                "INSERT INTO line (id, region_id, source_ja, proposed_en, final_en, status,"
                " ocr_empty) VALUES (?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        cursor.execute(
            "INSERT INTO cleaned_page (page_id, image_blob, erased) VALUES (?, ?, ?)",
            (page_ids[0], b"page zero cleaned", "[1]"),
        )
        cursor.execute(
            "INSERT INTO glossary (chapter_id, term_ja, term_en, first_seen_page,"
            " last_seen_page, source) VALUES (?, ?, ?, ?, ?, ?)",
            (chapter_id, "先輩", "senpai", 0, 1, "user"),
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


def _open_once(source_dir: Path, db_path: Path) -> None:
    """Open the file once and require that a migration RAN - without which every
    "unchanged" assertion is about a file nobody touched."""
    with open_project(project_dir_for(source_dir)):
        pass
    assert _user_version(db_path) == 14, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )


def _migrated(source_dir: Path) -> Path:
    db_path = _build_v13_file(source_dir)
    assert _user_version(db_path) == 13
    assert "misaligned" not in _line_columns(db_path), "the v13 fixture is already v14"
    _open_once(source_dir, db_path)
    return db_path


#: Every table the fixture populated, read whole, in id order. `chapter` minus
#: `schema_version`, which the step is required to change.
_KEPT = {
    "chapter": "SELECT id, source_dir, output_dir, created_at FROM chapter ORDER BY id",
    "page": "SELECT * FROM page ORDER BY id",
    "region": "SELECT * FROM region ORDER BY id",
    "line": "SELECT * FROM line ORDER BY id",
    "cleaned_page": "SELECT * FROM cleaned_page ORDER BY page_id",
    "glossary": "SELECT * FROM glossary ORDER BY id",
}


def _kept(db_path: Path) -> dict[str, list[tuple[object, ...]]]:
    return {table: _raw(db_path, sql) for table, sql in _KEPT.items()}


# -- the version ---------------------------------------------------------------------


def test_this_build_writes_and_reads_schema_version_fourteen(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """MT-149's bump, in both records of it (MT-005 PO-7)."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert SCHEMA_VERSION == 14
    assert _user_version(db_path) == 14
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(14,)]


# -- the fresh file ------------------------------------------------------------------


def test_a_fresh_line_table_declares_misaligned_last_as_not_null_integer_default_0(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-1: `misaligned INTEGER NOT NULL DEFAULT 0`. NOT NULL keeps the flag a
    boolean; the DEFAULT keeps every existing `INSERT INTO line (...)` working."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    shape = _raw(db_path, _LINE_SHAPE)

    assert shape[-1] == _MISALIGNED_SHAPE, f"line's last column is {shape[-1]}"


# -- the v13 -> v14 step -------------------------------------------------------------


def test_a_version_thirteen_file_is_migrated_to_fourteen_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The step, in both records of the version."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(14,)]


def test_every_line_a_version_thirteen_file_held_reads_misaligned_0(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """A line written before the check existed was never found misaligned: the
    DEFAULT is the truth about it, row by row, ocr_empty and edited rows too."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "SELECT id, misaligned FROM line ORDER BY id") == [
        (37, 0),
        (44, 0),
        (52, 0),
        (61, 0),
    ]


def test_a_migrated_file_refuses_a_null_flag(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """NOT NULL arrives on the migration path too: a nullable flag has three
    states and the review row has two."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    with pytest.raises(sqlite3.IntegrityError, match="misaligned"):
        _raw(db_path, "UPDATE line SET misaligned = NULL WHERE id = 52")


def test_every_row_comes_through_unchanged_but_for_the_one_appended_column(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """Every column of every row the fixture populated, raw, before and after:
    the step adds `misaligned = 0` at the end of each line row and touches
    nothing else - no row renumbered, no row lost, no blob swapped."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v13_file(source_dir)
    before = _kept(db_path)
    assert all(before.values()), f"the v13 fixture has an empty table: {before}"
    assert [row[0] for row in before["line"]] == [37, 44, 52, 61]

    _open_once(source_dir, db_path)

    after = _kept(db_path)
    expected = {**before, "line": [(*row, 0) for row in before["line"]]}
    for table in _KEPT:
        assert after[table] == expected[table], f"`{table}` changed in the v14 step"


def test_the_step_adds_only_the_one_column_to_line(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-1: one `ALTER TABLE ... ADD COLUMN` - the v13 columns, in their order,
    then `misaligned`, and nothing else."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v13_file(source_dir)
    before = _line_columns(db_path)

    _open_once(source_dir, db_path)

    assert _line_columns(db_path) == [*before, "misaligned"]


def test_a_migrated_line_table_has_the_same_shape_as_a_fresh_one(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The migration and the fresh schema declare the same column: name, type,
    NOT NULL and DEFAULT, in the same position."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"))
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))

    assert _raw(migrated, _LINE_SHAPE) == _raw(fresh, _LINE_SHAPE)
    assert _raw(migrated, _LINE_SHAPE)[-1] == _MISALIGNED_SHAPE


def _line_sql(db_path: Path) -> str:
    """`line`'s stored `CREATE TABLE`, runs of whitespace collapsed."""
    rows = _raw(db_path, "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'line'")
    assert len(rows) == 1, f"expected one `line` table, found {rows}"
    return " ".join(str(rows[0][0]).split())


def test_a_migrated_line_table_is_declared_as_a_fresh_one(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """`sqlite_master.sql` for `line` agrees, whitespace collapsed - the form
    `test_schema_v13.py`'s whole-schema comparison already holds every table
    to. `ALTER TABLE ... ADD COLUMN` splices `, misaligned ...` before the
    closing parenthesis, so a fresh file agrees only if it is built the same
    way: the one `ALTER` string run by both (the `CLEANED_ERASED_DDL`
    precedent in `schema.py`)."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"))
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))

    assert _line_sql(migrated) == _line_sql(fresh)
    assert "misaligned INTEGER NOT NULL DEFAULT 0" in _line_sql(fresh)


def test_a_migrated_file_has_no_foreign_key_violations(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "PRAGMA foreign_key_check") == []


# -- a version-15 file ---------------------------------------------------------------


def test_a_file_one_version_newer_than_fourteen_is_refused(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """A file at 15 raises `SchemaTooNew` naming both numbers, and is left at 15."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    _raw(db_path, "PRAGMA user_version = 15")

    with pytest.raises(SchemaTooNew) as excinfo:
        open_project(project_dir_for(source_dir))

    message = str(excinfo.value)
    assert re.search(r"\bversion 15(?!\d)", message), message
    assert re.search(r"\bsupports 14(?!\d)", message), message
    assert _user_version(db_path) == 15


def test_the_same_file_at_version_fourteen_opens(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The control for the refusal above."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    assert _user_version(db_path) == 14

    with open_project(project_dir_for(source_dir)) as project:
        assert len(project.pages()) == len(_SOURCE_PAGES)
    assert _user_version(db_path) == 14
