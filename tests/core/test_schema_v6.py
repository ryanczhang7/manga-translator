"""MT-017 C-5: schema version 6, and the v5 -> v6 step that gives `line` its
`status` column.

`status` is where a user's act lives: `accepted`, `edited` or `reverted`, and
NULL for "no act" (C-2: `proposed` and `failed` are derived, never stored). C-5
asks for the same three things MT-014 asked of its columns, each silent if got
wrong:

1. **a migrated `line` table is the same table as a fresh one** - the column
   declared last, so `ALTER TABLE ... ADD COLUMN` (which appends) and a fresh
   `CREATE TABLE` agree on order, type, NOT NULL and DEFAULT;
2. **existing rows read NULL** - a v5 file's lines have had no user act, so
   they must come back as derived statuses, not as some default;
3. **the CHECK arrives with the column on both paths**, so a file can never
   hold `'proposed'` or `'banana'` in it.

**`_V5_DDL` below is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v5.py`'s `_V4_DDL` and its predecessors carry the
same instruction for the same reason. Transcribed in RED on 2026-09-30 from
`mangatl.store.schema.DDL` as it shipped at version 5 (MT-014), comments
dropped - by printing the module's `DDL` with its `--` lines removed, so the
transcription is mechanical rather than retyped.

**Timing.** No `pytest-timeout` in this project; each test builds a two-page
chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import SCHEMA_VERSION, create_project, open_project, project_dir_for

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
)

#: `line`'s columns in declaration order at version 6 (C-5: `status` last).
_LINE_COLUMNS_V6: tuple[str, ...] = (
    "id",
    "region_id",
    "source_ja",
    "proposed_en",
    "final_en",
    "edited_at",
    "viewed_at",
    "ocr_empty",
    "status",
)

#: The v5 fixture's lines, reading index order: `(source_ja, proposed_en,
#: final_en, ocr_empty)`. One translated, one untranslated, one ocr_empty, and
#: one carrying a `final_en` - a v5 file cannot hold a status, but it can hold
#: text, and the migration must not invent a status for it.
_V5_LINES: tuple[tuple[str, str | None, str | None, int], ...] = (
    ("こんにちは", "Hello.", None, 0),
    ("さようなら", None, None, 0),
    ("", None, None, 1),
    ("またね", "See you.", "Later.", 0),
)

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V5_DDL = """
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
    last_seen_page  INTEGER NOT NULL DEFAULT 0,
    source          TEXT    NOT NULL DEFAULT 'model' CHECK (source IN ('model', 'user')),
    UNIQUE (chapter_id, term_ja)
);
"""

#: One row per column: name, type, NOT NULL, DEFAULT. CHECK constraints are not
#: in `table_info`, which is why `_check_refuses_uncommitted_statuses` exists.
_SHAPE = "SELECT name, type, \"notnull\", dflt_value FROM pragma_table_info('line')"


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
    return tuple(str(row[1]) for row in _raw(db_path, "PRAGMA table_info(line)"))


def _sources(tmp_path: Path, png_bytes: Callable[..., bytes], name: str) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    for filename, width, height in _SOURCE_PAGES:
        (directory / filename).write_bytes(png_bytes(width, height))
    return directory


def _fresh(source_dir: Path, mask: bytes) -> Path:
    """A fresh current-version file with one page of four regions and lines."""
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        ring = ((0, 0), (2, 0), (2, 2), (0, 2), (0, 0))
        project.write_regions(
            0,
            [RawRegion(polygon=ring, mask=mask, confidence=0.9, kind="bubble")] * len(_V5_LINES),
        )
        project.write_lines(
            0, [OcrResult(source_ja, ocr_empty=bool(empty)) for source_ja, _, _, empty in _V5_LINES]
        )
    return project_dir_for(source_dir) / "project.db"


def _build_v5_file(source_dir: Path, mask: bytes) -> Path:
    """A schema-version-5 file built with `_V5_DDL` and nothing else, page 0
    carrying one region per `_V5_LINES` entry and its line."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V5_DDL)
        connection.execute("PRAGMA user_version = 5")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version)"
            " VALUES (?, ?, ?, ?)",
            (str(source_dir), str(source_dir) + "_en", "2026-09-30T00:00:00+00:00", 5),
        )
        chapter_id = cursor.lastrowid
        page_ids = []
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
            page_ids.append(cursor.lastrowid)
        for reading_index, (source_ja, proposed_en, final_en, ocr_empty) in enumerate(_V5_LINES):
            cursor.execute(
                "INSERT INTO region (page_id, reading_index, polygon, mask_blob, kind, confidence)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    page_ids[0],
                    reading_index,
                    "[[0,0],[2,0],[2,2],[0,2],[0,0]]",
                    mask,
                    "bubble",
                    0.9,
                ),
            )
            cursor.execute(
                "INSERT INTO line (region_id, source_ja, proposed_en, final_en, ocr_empty)"
                " VALUES (?, ?, ?, ?, ?)",
                (cursor.lastrowid, source_ja, proposed_en, final_en, ocr_empty),
            )
        connection.commit()
    finally:
        connection.close()
    return db_path


def _migrated(source_dir: Path, mask: bytes) -> Path:
    """Build a v5 file and open it once, asserting a migration RAN - without
    which every assertion downstream is about a file nobody touched."""
    db_path = _build_v5_file(source_dir, mask)
    assert _user_version(db_path) == 5
    assert "status" not in _columns(db_path), "the v5 fixture is already v6"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 6, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


def _check_refuses_uncommitted_statuses(db_path: Path) -> None:
    """C-5's CHECK: NULL and the three committed statuses only."""
    connection = sqlite3.connect(db_path)
    try:
        line_id = connection.execute("SELECT id FROM line ORDER BY id").fetchone()[0]
        for bad in ("proposed", "failed", "banana", ""):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                connection.execute("UPDATE line SET status = ? WHERE id = ?", (bad, line_id))
        # The legal values are accepted, so the refusal is about the value and
        # not about the column being unwritable.
        for good in ("accepted", "edited", "reverted", None):
            connection.execute("UPDATE line SET status = ? WHERE id = ?", (good, line_id))
        connection.rollback()
    finally:
        connection.close()


@pytest.fixture
def mask(one_bit_png: Callable[..., bytes]) -> bytes:
    """A real 1-bit PNG, because `RawRegion` refuses anything else (MT-007 C-7)."""
    return one_bit_png(7, 3, [(0, 0, 2, 2)])


# -- the version, and the fresh table --------------------------------------------


def test_this_build_writes_and_reads_schema_version_six(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"), mask)

    assert SCHEMA_VERSION == 6
    assert _user_version(db_path) == 6
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(6,)]


def test_a_fresh_line_table_has_a_nullable_status_column_declared_last(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"), mask)

    assert _columns(db_path) == _LINE_COLUMNS_V6
    shape = {str(row[0]): row[1:] for row in _raw(db_path, _SHAPE)}
    assert shape["status"] == ("TEXT", 0, None), "C-5: nullable, no DEFAULT"


def test_a_fresh_file_refuses_a_status_that_is_not_a_user_act(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    _check_refuses_uncommitted_statuses(_fresh(_sources(tmp_path, png_bytes, "scans"), mask))


def test_a_freshly_written_line_has_no_status_until_a_user_acts(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"), mask)

    assert _raw(db_path, "SELECT status FROM line") == [(None,)] * len(_V5_LINES)


# -- the v5 -> v6 step -------------------------------------------------------------


def test_a_version_five_file_is_migrated_to_six_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"), mask)

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(6,)]
    assert _columns(db_path) == _LINE_COLUMNS_V6


def test_a_migrated_line_table_is_the_same_table_as_a_fresh_one(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"), mask)
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"), mask)

    assert _raw(migrated, _SHAPE) == _raw(fresh, _SHAPE)


def test_a_migrated_file_refuses_a_status_that_is_not_a_user_act(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """The CHECK arrives with the column on the migration path too."""
    _check_refuses_uncommitted_statuses(_migrated(_sources(tmp_path, png_bytes, "scans"), mask))


def test_every_line_a_version_five_file_held_survives_with_a_null_status(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"), mask)

    rows = _raw(
        db_path,
        "SELECT line.source_ja, line.proposed_en, line.final_en, line.ocr_empty, line.status"
        " FROM line JOIN region ON region.id = line.region_id ORDER BY region.reading_index",
    )
    assert rows == [(*entry, None) for entry in _V5_LINES]


def test_a_migrated_files_lines_read_back_with_derived_statuses(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """NULL is "no user act", so a v5 line reads as derived (C-2): the page is
    `pending`, so the translated and untranslated lines are `proposed`, and the
    ocr_empty one is `failed`. The v5 `final_en` is carried, and it does not
    make the line `edited` - a status is only ever written by a user act.

    Imported here, not at module level, so that while `store.lines` does not
    exist only this test fails at import and the schema tests above fail on
    their own assertions."""
    from mangatl.store.lines import read_review_lines

    source_dir = _sources(tmp_path, png_bytes, "scans")
    _migrated(source_dir, mask)

    with open_project(project_dir_for(source_dir)) as project:
        lines = read_review_lines(project, 0)

    assert [line.status if line else None for line in lines] == [
        "proposed",
        "proposed",
        "failed",
        "proposed",
    ]
    assert [line.final_en if line else None for line in lines] == [None, None, None, "Later."]


def test_the_v6_step_changes_only_the_line_table(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-5 is one `ADD COLUMN`; nothing else in the file has any business
    changing. Compared on `sqlite_master`, so a migration written as a rebuild
    of anything else - or a re-run of an earlier step - is caught."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v5_file(source_dir, mask)
    query = "SELECT type, name, sql FROM sqlite_master WHERE name != 'line' ORDER BY name"
    before = _raw(db_path, query)

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 6
    assert _raw(db_path, query) == before
