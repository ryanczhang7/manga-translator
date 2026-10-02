"""MT-065 C-2: schema version 7, and the v6 -> v7 step that adds `cleaned_page`.

`cleaned_page` holds one encoded image per page - the cleaner's PNG for a page
with regions, the source scan's own bytes for a page without (PO-4). C-2 asks
for three things, each silent if got wrong:

1. **a migrated file and a fresh one hold the same table**, down to the stored
   `sqlite_master.sql` - which is why the migration and the fresh schema share
   one constant, `CLEANED_PAGE_DDL`;
2. **a migrated file's table is empty**: every page of a v6 project is
   not-yet-cleaned, and the next run cleans it without re-running any other
   stage (AC-3, C-9 - `test_clean_stage.py` runs that resume);
3. **the v7 step adds that one table and touches nothing else**. The three
   older "this step touches nothing else" comparisons in `test_schema_v4.py`,
   `_v5.py` and `_v6.py` now exclude `cleaned_page`, and this file owns what the
   v7 step does instead (DV-5 earns all four by mutation at GATES).

**`_V6_DDL` below is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v6.py`'s `_V5_DDL` carries the same instruction for
the same reason. Transcribed in RED on 2026-10-02 from
`mangatl.store.schema.DDL` as it shipped at version 6 (MT-017), comments
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

from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import SCHEMA_VERSION, create_project, open_project, project_dir_for

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
)

#: `cleaned_page`'s shape: name, type, NOT NULL, DEFAULT, primary-key position.
#: `INTEGER PRIMARY KEY` is the rowid alias, which `table_info` reports as
#: nullable; that is SQLite's report, and the rowid can never be NULL.
_CLEANED_PAGE_SHAPE: list[tuple[object, ...]] = [
    ("page_id", "INTEGER", 0, None, 1),
    ("image_blob", "BLOB", 1, None, 0),
]
_SHAPE = "SELECT name, type, \"notnull\", dflt_value, pk FROM pragma_table_info('cleaned_page')"

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V6_DDL = """
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
"""

_RING = ((0, 0), (2, 0), (2, 2), (0, 2), (0, 0))


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _user_version(db_path: Path) -> int:
    return int(_raw(db_path, "PRAGMA user_version")[0][0])


def _tables(db_path: Path) -> set[str]:
    rows = _raw(db_path, "SELECT name FROM sqlite_master WHERE type = 'table'")
    return {str(row[0]) for row in rows}


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


def _build_v6_file(source_dir: Path, mask: bytes) -> Path:
    """A schema-version-6 file built with `_V6_DDL` and nothing else: both
    pages `done` (a fully run v6 chapter), page 0 carrying one region and its
    translated line."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V6_DDL)
        connection.execute("PRAGMA user_version = 6")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version)"
            " VALUES (?, ?, ?, ?)",
            (str(source_dir), str(source_dir) + "_en", "2026-10-02T00:00:00+00:00", 6),
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
                    "done",
                ),
            )
            page_ids.append(cursor.lastrowid)
        cursor.execute(
            "INSERT INTO region (page_id, reading_index, polygon, mask_blob, kind, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (page_ids[0], 0, "[[0,0],[2,0],[2,2],[0,2],[0,0]]", mask, "bubble", 0.5),
        )
        cursor.execute(
            "INSERT INTO line (region_id, source_ja, proposed_en) VALUES (?, ?, ?)",
            (cursor.lastrowid, "こんにちは", "Hello."),
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


def _migrated(source_dir: Path, mask: bytes) -> Path:
    """Build a v6 file and open it once, asserting a migration RAN - without
    which every assertion downstream is about a file nobody touched."""
    db_path = _build_v6_file(source_dir, mask)
    assert _user_version(db_path) == 6
    assert "cleaned_page" not in _tables(db_path), "the v6 fixture is already v7"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 7, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


@pytest.fixture
def mask(one_bit_png: Callable[..., bytes]) -> bytes:
    """A real 1-bit PNG, because `RawRegion` refuses anything else (MT-007 C-7)."""
    return one_bit_png(7, 3, [(0, 0, 2, 2)])


# -- the version, the constant, and the fresh table ------------------------------


def test_this_build_writes_and_reads_schema_version_seven(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-2's bump, in both records of it (MT-005 PO-7)."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert SCHEMA_VERSION == 7
    assert _user_version(db_path) == 7
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(7,)]


def test_the_cleaned_page_ddl_is_its_own_exported_string_appended_last() -> None:
    """C-2: one constant, two callers (the fresh schema and the migration), and
    `DDL` appends it **last**, after `glossary`, so a fresh file and a migrated
    one create it in the same position."""
    import mangatl.store.schema as module

    assert module.__all__ == ["CHAPTER_DDL", "CLEANED_PAGE_DDL", "DDL", "LLM_CALL_DDL"]
    assert "CREATE TABLE cleaned_page" in module.CLEANED_PAGE_DDL
    assert module.DDL.rstrip().endswith(module.CLEANED_PAGE_DDL.strip()), (
        "DDL does not end with CLEANED_PAGE_DDL verbatim; C-2 appends it last"
    )
    assert module.DDL.index("CREATE TABLE glossary") < module.DDL.index("CREATE TABLE cleaned_page")


def test_a_fresh_cleaned_page_table_has_the_shape_c2_draws(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, _SHAPE) == _CLEANED_PAGE_SHAPE
    assert _raw(db_path, "PRAGMA foreign_key_list(cleaned_page)") == [
        (0, 0, "page", "page_id", "id", "NO ACTION", "CASCADE", "NONE")
    ]
    # `page_id` is a rowid alias, so no autoindex - and nothing else - exists
    # for this table (C-2).
    objects = _raw(db_path, "SELECT type, name FROM sqlite_master WHERE tbl_name = 'cleaned_page'")
    assert objects == [("table", "cleaned_page")]


def test_a_page_row_deleted_takes_its_cleaned_image_with_it(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-2's `ON DELETE CASCADE` from `page`: the one cascade this table has."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        page_ids = [
            int(row[0]) for row in connection.execute("SELECT id FROM page ORDER BY ordinal")
        ]
        with connection:
            for page_id in page_ids:
                connection.execute(
                    "INSERT INTO cleaned_page (page_id, image_blob) VALUES (?, ?)",
                    (page_id, b"image"),
                )
            connection.execute("DELETE FROM page WHERE ordinal = 0")
        remaining = list(connection.execute("SELECT page_id FROM cleaned_page"))
    finally:
        connection.close()

    assert remaining == [(page_ids[1],)]


def test_a_cleaned_page_row_must_name_a_page_and_carry_an_image(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        page_id = int(connection.execute("SELECT min(id) FROM page").fetchone()[0])
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                "INSERT INTO cleaned_page (page_id, image_blob) VALUES (?, ?)",
                (page_id + 99, b"x"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            connection.execute(
                "INSERT INTO cleaned_page (page_id, image_blob) VALUES (?, ?)", (page_id, None)
            )
        connection.rollback()
    finally:
        connection.close()


# -- the v6 -> v7 step -------------------------------------------------------------


def test_a_version_six_file_is_migrated_to_seven_with_an_empty_cleaned_page_table(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """**AC-5**'s migration clause (C-8): a v6 file opens as v7, `cleaned_page`
    present and empty, and every page reads not-cleaned through the store."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _migrated(source_dir, mask)

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(7,)]
    assert _raw(db_path, _SHAPE) == _CLEANED_PAGE_SHAPE
    assert _raw(db_path, "SELECT count(*) FROM cleaned_page") == [(0,)]
    with open_project(project_dir_for(source_dir)) as project:
        ordinals = [page.ordinal for page in project.pages()]
        assert [project.has_cleaned(ordinal) for ordinal in ordinals] == [False, False]
        assert [project.read_cleaned(ordinal) for ordinal in ordinals] == [None, None]


def test_a_migrated_cleaned_page_table_is_stored_exactly_as_a_fresh_one(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-2: the shared constant makes `sqlite_master.sql` byte-identical between
    a fresh v7 file and a migrated one."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"), mask)
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))
    query = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE tbl_name = 'cleaned_page'"

    assert _raw(fresh, query) != [], "the control: the fresh file has the table"
    assert _raw(migrated, query) == _raw(fresh, query)


def test_the_v7_step_adds_only_cleaned_page(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-2 is one `CREATE TABLE`; nothing else in the file has any business
    changing. Compared on all of `sqlite_master`, so a stray index, a rebuilt
    table or a re-run earlier step is caught (DV-5)."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v6_file(source_dir, mask)
    query = "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    before = _raw(db_path, query)

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 7
    after = _raw(db_path, query)
    added = [row[:3] for row in after if row not in before]
    assert added == [("table", "cleaned_page", "cleaned_page")], (
        f"the v7 step added {added}; C-2 adds cleaned_page and nothing else"
    )
    assert [row for row in after if row[1] != "cleaned_page"] == before


def test_every_row_a_version_six_file_held_survives_the_v7_step(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """Regions, lines, proposals and page statuses are untouched: a v6 project
    is a translated one, and the next run must find it so (C-9)."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _migrated(source_dir, mask)

    assert _raw(db_path, "SELECT ordinal, status FROM page ORDER BY ordinal") == [
        (0, "done"),
        (1, "done"),
    ]
    assert _raw(db_path, "SELECT source_ja, proposed_en FROM line") == [("こんにちは", "Hello.")]
    with open_project(project_dir_for(source_dir)) as project:
        regions = project.read_regions(0)
    assert regions == (RawRegion(polygon=_RING, mask=mask, confidence=0.5, kind="bubble"),)


def test_a_migrated_project_accepts_a_cleaned_image(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    source_dir = _sources(tmp_path, png_bytes, "scans")
    _migrated(source_dir, mask)
    image = png_bytes(7, 3, (1, 2, 3))

    with open_project(project_dir_for(source_dir)) as project:
        project.write_cleaned(0, image)
        assert project.read_cleaned(0) == image
