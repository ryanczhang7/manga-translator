"""MT-119 C-4 / AC-6: schema version 9, and the v8 -> v9 step that gives
`cleaned_page` its `erased` column.

`erased` is the reading indices of the regions the cleaner was handed when the
stored image was written, as a JSON array. MT-119's restore rule (AC-5) reads
it: restoring a region the image never erased is the one toggle that deletes
the image. Four things are asked of the step, each silent if got wrong:

1. **a v8 row reads `erased` = every reading index of its page.** That is the
   truth about a row a v8 cleaner wrote - `CleanStage` before MT-119 handed the
   cleaner every region, excluded ones included, and `write_regions` deletes
   the image, so the regions stored now are the ones it was handed. A row left
   at the column's `DEFAULT '[]'` would say "erased nothing", and the first
   restore of a v8 watermark would then delete a good image;
2. **a fresh file and a migrated one store the same `cleaned_page`
   declaration** in `sqlite_master.sql`, whitespace collapsed (the
   `test_schema_v8.py` comparison);
3. **the trap C-4 names does not fire**: `CLEANED_PAGE_DDL` IS
   `_MIGRATE_TO_V7` (`project.py`), so a column written into that string would
   be created by the v6 -> v7 step and then added again by v8 -> v9 -
   `duplicate column name`. A v6 file is therefore opened here too, all the way
   to 9;
4. **the step touches nothing else**: no other schema object and no other
   table's rows, and of `cleaned_page` only the new column.

**Where the v8 file comes from.** `_V8_DDL` below, built in the test with
`sqlite3` and nothing else - every earlier `test_schema_v*.py`'s precedent.

**`_V8_DDL` is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v8.py`'s `_V7_DDL` carries the same instruction for
the same reason. Transcribed in RED on 2026-10-30 from
`mangatl.store.schema.DDL` as it shipped at version 8 (MT-118), by printing the
module's `DDL` with its `--` lines removed, so the transcription is mechanical
rather than retyped.

**Timing.** No `pytest-timeout` in this project; each test builds a chapter of
three tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from test_schema_v7 import _build_v6_file

import mangatl.store.project as project_module
import mangatl.store.schema as schema_module
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import (
    SCHEMA_VERSION,
    SchemaTooNew,
    create_project,
    open_project,
    project_dir_for,
)

#: Three pages: page 0 has three regions and a cleaned image, page 1 a cleaned
#: image and no regions (its source bytes, MT-065 PO-4), page 2 regions and no
#: cleaned image. The first two sizes are `test_schema_v7.py`'s, which the v6
#: builder imported below writes against.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 5),
)

#: `cleaned_page` at version 9: name, type, NOT NULL, DEFAULT, pk position.
#: C-4: `erased TEXT NOT NULL DEFAULT '[]'`, appended last by `ADD COLUMN`.
_CLEANED_PAGE_SHAPE_V9: list[tuple[object, ...]] = [
    ("page_id", "INTEGER", 0, None, 1),
    ("image_blob", "BLOB", 1, None, 0),
    ("erased", "TEXT", 1, "'[]'", 0),
]
_SHAPE = "SELECT name, type, \"notnull\", dflt_value, pk FROM pragma_table_info('cleaned_page')"

#: Page 0's regions in the v8 file, INSERTED in this order - not reading order,
#: so a migration that read them without `ORDER BY reading_index` stores them
#: in rowid order: `(reading_index, excluded)`. The excluded one is the v8
#: watermark the old cleaner was handed all the same.
_V8_REGIONS: tuple[tuple[int, str | None], ...] = ((2, None), (0, None), (1, "watermark"))

_V8_IMAGES = {0: b"page zero cleaned", 1: b"page one source bytes"}

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V8_DDL = """
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
"""


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _user_version(db_path: Path) -> int:
    return int(str(_raw(db_path, "PRAGMA user_version")[0][0]))


def _cleaned_page_sql(db_path: Path) -> str:
    """`cleaned_page`'s stored `CREATE TABLE`, runs of whitespace collapsed."""
    rows = _raw(db_path, "SELECT sql FROM sqlite_master WHERE name = 'cleaned_page'")
    assert rows, "no cleaned_page table in the file"
    return " ".join(str(rows[0][0]).split())


def _erased_by_ordinal(db_path: Path) -> dict[int, object]:
    """ordinal -> `cleaned_page.erased` parsed as JSON, read by a reader that
    imports nothing from `mangatl.store`."""
    return {
        int(str(ordinal)): json.loads(str(erased))
        for ordinal, erased in _raw(
            db_path,
            "SELECT page.ordinal, cleaned_page.erased FROM cleaned_page"
            " JOIN page ON page.id = cleaned_page.page_id ORDER BY page.ordinal",
        )
    }


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


def _build_v8_file(source_dir: Path, mask: bytes) -> Path:
    """A schema-version-8 file built with `_V8_DDL` and nothing else: every page
    `done`, page 0 carrying `_V8_REGIONS` (one excluded) and their lines, pages
    0 and 1 a cleaned image, page 2 a region and no cleaned image - a run v8
    chapter whose watermark the user had not yet seen."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V8_DDL)
        connection.execute("PRAGMA user_version = 8")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version)"
            " VALUES (?, ?, ?, ?)",
            (str(source_dir), str(source_dir) + "_en", "2026-10-30T00:00:00+00:00", 8),
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
        ring = "[[0,0],[2,0],[2,2],[0,2],[0,0]]"
        for reading_index, excluded in _V8_REGIONS:
            cursor.execute(
                "INSERT INTO region"
                " (page_id, reading_index, polygon, mask_blob, kind, confidence, excluded)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (page_ids[0], reading_index, ring, mask, "bubble", 0.5, excluded),
            )
            cursor.execute(
                "INSERT INTO line (region_id, source_ja, proposed_en) VALUES (?, ?, ?)",
                (cursor.lastrowid, f"せりふ{reading_index}", f"Line {reading_index}."),
            )
        cursor.execute(
            "INSERT INTO region"
            " (page_id, reading_index, polygon, mask_blob, kind, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (page_ids[2], 0, ring, mask, "box", 0.75),
        )
        for ordinal, image in _V8_IMAGES.items():
            cursor.execute(
                "INSERT INTO cleaned_page (page_id, image_blob) VALUES (?, ?)",
                (page_ids[ordinal], image),
            )
        connection.commit()
    finally:
        connection.close()
    return db_path


def _migrated(source_dir: Path, mask: bytes) -> Path:
    """Build a v8 file and open it once, asserting a migration RAN - without
    which every assertion downstream is about a file nobody touched."""
    db_path = _build_v8_file(source_dir, mask)
    assert _user_version(db_path) == 8
    assert "erased" not in _cleaned_page_sql(db_path), "the v8 fixture is already v9"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 10, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


@pytest.fixture
def mask(one_bit_png: Callable[..., bytes]) -> bytes:
    """A real 1-bit PNG, because `RawRegion` refuses anything else (MT-007 C-7)."""
    return one_bit_png(7, 3, [(0, 0, 2, 2)])


# -- the version, the shared string, and the fresh table -----------------------------


def test_this_build_writes_and_reads_schema_version_nine(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-4's bump, in both records of it (MT-005 PO-7)."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert SCHEMA_VERSION == 10
    assert _user_version(db_path) == 10
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(10,)]


def test_the_erased_column_is_a_shared_string_appended_after_the_cleaned_page_table() -> None:
    """C-4: one new exported string, `CLEANED_ERASED_DDL`, appended to `DDL`
    directly after `CLEANED_PAGE_DDL` and run by the v8 -> v9 step as well -
    and NOT written into `CLEANED_PAGE_DDL`, which the v6 -> v7 step runs
    verbatim (the trap; `test_a_version_six_file_migrates_all_the_way_to_nine`
    is its behavioural half)."""
    assert "CLEANED_ERASED_DDL" in schema_module.__all__
    assert re.search(r"\bADD COLUMN erased\b", schema_module.CLEANED_ERASED_DDL)
    assert "erased" not in schema_module.CLEANED_PAGE_DDL
    assert schema_module.DDL.rstrip().endswith(
        (schema_module.CLEANED_PAGE_DDL + schema_module.CLEANED_ERASED_DDL).strip()
    )


def test_a_fresh_cleaned_page_table_has_a_not_null_erased_column_declared_last(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, _SHAPE) == _CLEANED_PAGE_SHAPE_V9


# -- AC-6: the v8 -> v9 step ---------------------------------------------------------


def test_a_version_eight_file_is_migrated_to_nine_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """**AC-6**: "a version 8 file opens at 9" - in both records of it."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"), mask)

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(10,)]
    assert _raw(db_path, _SHAPE) == _CLEANED_PAGE_SHAPE_V9


def test_every_cleaned_row_a_version_eight_file_held_erased_every_region_of_its_page(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """**AC-6**: every `cleaned_page` row reads `erased` == every reading index
    of its page - `[0, 1, 2]` in reading order on page 0, the excluded
    watermark at 1 included (a v8 cleaner was handed it), and `[]` on page 1,
    which has no regions. Page 2 has regions and no image, and still has no
    row: the step fills a column, it creates nothing. Read through a plain
    sqlite reader and through the store."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _migrated(source_dir, mask)

    assert _erased_by_ordinal(db_path) == {0: [0, 1, 2], 1: []}
    with open_project(project_dir_for(source_dir)) as project:
        assert [project.read_erased(ordinal) for ordinal in (0, 1, 2)] == [
            frozenset({0, 1, 2}),
            frozenset(),
            None,
        ]


def test_a_fresh_file_and_a_migrated_one_store_the_same_cleaned_page_declaration(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """**AC-6**: `sqlite_master.sql` for `cleaned_page`, whitespace collapsed,
    is the same on both paths - and carries the column, so the pair cannot
    agree on a table without it."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"), mask)
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))

    assert _cleaned_page_sql(migrated) == _cleaned_page_sql(fresh)
    assert re.search(r"\berased TEXT NOT NULL DEFAULT '\[\]'", _cleaned_page_sql(fresh)), (
        _cleaned_page_sql(fresh)
    )
    assert _raw(migrated, _SHAPE) == _raw(fresh, _SHAPE)


def test_the_v9_step_changes_only_the_cleaned_page_erased_column(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-4 is one `ADD COLUMN` and one `UPDATE` of it: no other schema object
    changes, no row of any other table changes, and `cleaned_page`'s own
    `page_id` and `image_blob` are byte for byte what they were."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v8_file(source_dir, mask)
    # `batch_job`, `chapter`, `correction` and `llm_call` excluded since MT-103: the
    # v9 -> v10 step creates the first and third, ALTERs `chapter` and rebuilds
    # `llm_call` on purpose; `test_schema_v10.py` owns what that step does.
    schema = (
        "SELECT type, name, sql FROM sqlite_master"
        " WHERE name NOT IN ('batch_job', 'chapter', 'cleaned_page', 'correction',"
        " 'llm_call') ORDER BY name"
    )
    tables = ("page", "region", "line", "run", "glossary")

    def rows() -> dict[str, list[tuple[object, ...]]]:
        found = {t: _raw(db_path, f"SELECT * FROM {t} ORDER BY rowid") for t in tables}
        # `chapter` and `llm_call` are read on their pre-v10 columns since MT-103:
        # the v9 -> v10 step adds `glossary_proposed_at` and `pricing` on purpose.
        found["chapter"] = _raw(
            db_path,
            "SELECT id, source_dir, output_dir, created_at, schema_version,"
            " budget_ceiling_micro_usd, model_id, rate_table_version FROM chapter ORDER BY rowid",
        )
        found["llm_call"] = _raw(
            db_path,
            "SELECT id, run_id, page_id, request_id, model_id, input_tokens, output_tokens,"
            " cache_write_tokens, cache_read_tokens, cost_micro_usd, rate_table_version, at"
            " FROM llm_call ORDER BY rowid",
        )
        return found

    def images() -> list[tuple[object, ...]]:
        return _raw(db_path, "SELECT page_id, image_blob FROM cleaned_page ORDER BY page_id")

    schema_before, rows_before, images_before = _raw(db_path, schema), rows(), images()
    assert rows_before["region"] != [], "the v8 fixture has no regions to preserve"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 10
    assert _raw(db_path, schema) == schema_before
    assert images() == images_before
    rows_after = rows()
    # The chapter row's `schema_version` is the one cell outside the column
    # the step must change.
    assert [row[:4] + row[5:] for row in rows_after["chapter"]] == [
        row[:4] + row[5:] for row in rows_before["chapter"]
    ]
    assert {t: r for t, r in rows_after.items() if t != "chapter"} == {
        t: r for t, r in rows_before.items() if t != "chapter"
    }


def test_a_version_six_file_migrates_all_the_way_to_nine(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-4's trap, behaviourally: a v6 file runs the v6 -> v7 step (which
    creates `cleaned_page` from `CLEANED_PAGE_DDL`) and then v8 -> v9 (which
    adds `erased`). With the column written into `CLEANED_PAGE_DDL` this open
    dies on `duplicate column name`. It arrives at 9 with the fresh file's
    declaration, and its (empty) table accepts a cleaned image with `erased`."""
    source_dir = _sources(tmp_path, png_bytes, "v6")
    db_path = _build_v6_file(source_dir, mask)
    assert _user_version(db_path) == 6

    with open_project(project_dir_for(source_dir)) as project:
        project.write_cleaned(0, png_bytes(7, 3, (1, 2, 3)), erased=[0])
        assert project.read_erased(0) == frozenset({0})

    assert _user_version(db_path) == 10
    assert _cleaned_page_sql(db_path) == _cleaned_page_sql(
        _fresh(_sources(tmp_path, png_bytes, "fresh"))
    )


def test_a_migrated_v8_watermark_restored_keeps_its_page_image(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """Why "every reading index" is the truth that matters: the v8 watermark
    on page 0 was erased by the v8 cleaner, so restoring it in the workspace
    is AC-5 (b), and the image stays. A migration that left `erased` at its
    `DEFAULT '[]'` would make this AC-5 (c), and delete it."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _migrated(source_dir, mask)

    with open_project(project_dir_for(source_dir)) as project:
        project.set_excluded(0, 1, None)
        assert project.has_cleaned(0) is True

    assert _raw(db_path, "SELECT image_blob FROM cleaned_page ORDER BY page_id") == [
        (_V8_IMAGES[0],),
        (_V8_IMAGES[1],),
    ]


# -- AC-6: a version-9 file and an older reader -------------------------------------


def test_a_version_nine_file_is_refused_by_a_reader_that_supports_eight(
    tmp_path: Path, png_bytes: Callable[..., bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**AC-6**: a v9 file handed to a build whose `SCHEMA_VERSION` is 8
    raises `SchemaTooNew` naming both numbers, before any read - an older
    build would read `erased` as absent and restore regions it cannot reason
    about. `open_project` reads the module's constant at call time."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    # MT-103 PO-3: a fresh file is version 10 now. The refusal comes before any
    # read, so the file is stamped 9 - the version this test is about - with a
    # plain connection; what its tables hold beyond that is never reached
    # (`test_schema_v8.py`'s version-8 refusal, the same move).
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA user_version = 9")
    finally:
        connection.close()
    assert _user_version(db_path) == 9, "the fixture is not a version-9 file"

    monkeypatch.setattr(project_module, "SCHEMA_VERSION", 8)
    with pytest.raises(SchemaTooNew) as excinfo:
        open_project(project_dir_for(source_dir))

    # Anchored to the words around each number: the message also carries the
    # file's path, and a bare `8` matches a `pytest-8` temp dir.
    message = str(excinfo.value)
    assert re.search(r"\bversion 9\b", message), message
    assert re.search(r"\bsupports 8\b", message), message
    assert _user_version(db_path) == 9, "the refusal must not have migrated anything"


def test_the_same_version_nine_file_opens_in_this_build(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> None:
    """The control for the refusal above: a store that raised `SchemaTooNew`
    for every file would pass it."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    _fresh(source_dir)
    region = RawRegion(
        polygon=((0, 0), (2, 0), (2, 2), (0, 2), (0, 0)),
        mask=one_bit_png(7, 3, [(0, 0, 2, 2)]),
        confidence=0.9,
        kind="bubble",
    )

    with open_project(project_dir_for(source_dir)) as project:
        project.write_regions(0, [region])
        assert len(project.read_regions(0)) == 1
