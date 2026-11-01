"""MT-118 C-2: schema version 8, and the v7 -> v8 step that gives `region` its
`excluded` column (AC-4).

`excluded` is why a region is out of translation: `'watermark'` (the detector's
rule, MT-121), `'user'` (the workspace's, MT-120), or NULL for "included". C-2
asks for the same things MT-014 and MT-017 asked of their columns, each silent
if got wrong:

1. **a migrated `region` table is the same table as a fresh one** - the column
   declared last among the columns, so `ALTER TABLE ... ADD COLUMN` (which
   appends) and a fresh `CREATE TABLE` agree on order, type, NOT NULL and
   DEFAULT;
2. **existing rows read NULL** - a v7 file's regions were never excluded, so
   they come back included, and every other column comes back as it was
   (DV-2 changes the migration to `DEFAULT 'user'` and expects this to fail);
3. **the CHECK arrives with the column on both paths** - and, because the fresh
   `schema.py` text and the `ALTER` text are two strings rather than one shared
   constant, the two stored declarations are held to each other through
   `sqlite_master.sql`, the way `test_schema_v7.py` holds `cleaned_page`.

**Where the v7 file comes from (C-6 as amended in RED).** `_V7_DDL` below, built
in the test with `sqlite3` and nothing else - the precedent of every earlier
`test_schema_v*.py` - and not a committed binary fixture: no
`tests/core/fixtures/` exists, a `.sqlite` blob cannot be reviewed in a diff,
and the DDL can.

**`_V7_DDL` is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v7.py`'s `_V6_DDL` carries the same instruction for
the same reason. Transcribed in RED on 2026-10-29 from
`mangatl.store.schema.DDL` as it shipped at version 7 (MT-065), comments
dropped - by printing the module's `DDL` with its `--` lines removed, so the
transcription is mechanical rather than retyped.

**One measured fact the comparison depends on** (sqlite 3.53.1, measured in
RED): `ADD COLUMN` splices the new declaration into the stored `CREATE TABLE`
text directly after the last column, *before* the `UNIQUE (...)` table
constraint, as `merged_from   TEXT, excluded TEXT CHECK (...)`. A fresh file
stores it on its own line with `schema.py`'s alignment. So the two `region`
declarations differ in whitespace by construction, and the comparison below is
of the `excluded` clause with runs of whitespace collapsed - the CHECK's words,
not its indentation.

**Timing.** No `pytest-timeout` in this project; each test builds a two-page
chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

import mangatl.store.project as project_module
from mangatl.domain.region import RawRegion
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
)

#: `region`'s columns in declaration order at version 8 (C-2: `excluded` last).
_REGION_COLUMNS_V8: tuple[str, ...] = (
    "id",
    "page_id",
    "reading_index",
    "polygon",
    "mask_blob",
    "kind",
    "confidence",
    "merged_from",
    "excluded",
)

#: C-2's column declaration, whitespace collapsed to single spaces. The one
#: literal both stored declarations are compared against.
_EXCLUDED_DECLARATION = (
    "excluded TEXT CHECK (excluded IS NULL OR excluded IN ('watermark', 'user'))"
)

_SHAPE = "SELECT name, type, \"notnull\", dflt_value, pk FROM pragma_table_info('region')"

#: The v7 fixture's regions on page 0, reading order: `(polygon JSON, kind,
#: confidence, merged_from JSON or NULL)`. Distinct in every column, one merged.
_V7_REGIONS: tuple[tuple[str, str, float, str | None], ...] = (
    ("[[0,0],[2,0],[2,2],[0,2],[0,0]]", "bubble", 0.5, None),
    ("[[3,0],[5,0],[5,2],[3,2],[3,0]]", "box", 0.25, "[0,2]"),
    ("[[0,1],[6,1],[6,2],[0,2],[0,1]]", "bubble", 1.0, None),
)

#: Their lines: `(source_ja, proposed_en, ocr_empty, status)`.
_V7_LINES: tuple[tuple[str, str | None, int, str | None], ...] = (
    ("こんにちは", "Hello.", 0, "accepted"),
    ("透かし", "Watermark text.", 0, None),
    ("", None, 1, None),
)

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V7_DDL = """
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
    return int(_raw(db_path, "PRAGMA user_version")[0][0])


def _columns(db_path: Path) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in _raw(db_path, "PRAGMA table_info(region)"))


def _region_sql(db_path: Path) -> str:
    return str(_raw(db_path, "SELECT sql FROM sqlite_master WHERE name = 'region'")[0][0])


def _excluded_declaration(db_path: Path) -> str:
    """The `excluded` clause of `region`'s stored `CREATE TABLE`, whitespace
    collapsed: from the column name to the paren that closes its CHECK."""
    sql = " ".join(_region_sql(db_path).split())
    match = re.search(r"\bexcluded TEXT\b.*?\)\)", sql)
    assert match is not None, f"no `excluded` declaration in the stored region DDL: {sql}"
    return match.group(0)


def _sources(tmp_path: Path, png_bytes: Callable[..., bytes], name: str) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    for filename, width, height in _SOURCE_PAGES:
        (directory / filename).write_bytes(png_bytes(width, height))
    return directory


def _fresh(source_dir: Path, mask: bytes) -> Path:
    """A fresh current-version file with page 0 carrying three regions."""
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        ring = ((0, 0), (2, 0), (2, 2), (0, 2), (0, 0))
        project.write_regions(
            0, [RawRegion(polygon=ring, mask=mask, confidence=0.9, kind="bubble")] * 3
        )
    return project_dir_for(source_dir) / "project.db"


def _build_v7_file(source_dir: Path, mask: bytes) -> Path:
    """A schema-version-7 file built with `_V7_DDL` and nothing else: both pages
    `done`, page 0 carrying `_V7_REGIONS` and `_V7_LINES` and a cleaned image -
    a fully run v7 chapter, the file every existing user has."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V7_DDL)
        connection.execute("PRAGMA user_version = 7")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version)"
            " VALUES (?, ?, ?, ?)",
            (str(source_dir), str(source_dir) + "_en", "2026-10-29T00:00:00+00:00", 7),
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
        for reading_index, ((polygon, kind, confidence, merged_from), line) in enumerate(
            zip(_V7_REGIONS, _V7_LINES, strict=True)
        ):
            cursor.execute(
                "INSERT INTO region"
                " (page_id, reading_index, polygon, mask_blob, kind, confidence, merged_from)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (page_ids[0], reading_index, polygon, mask, kind, confidence, merged_from),
            )
            source_ja, proposed_en, ocr_empty, status = line
            cursor.execute(
                "INSERT INTO line (region_id, source_ja, proposed_en, ocr_empty, status)"
                " VALUES (?, ?, ?, ?, ?)",
                (cursor.lastrowid, source_ja, proposed_en, ocr_empty, status),
            )
        cursor.execute(
            "INSERT INTO cleaned_page (page_id, image_blob) VALUES (?, ?)",
            (page_ids[0], b"cleaned image"),
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


def _migrated(source_dir: Path, mask: bytes) -> Path:
    """Build a v7 file and open it once, asserting a migration RAN - without
    which every assertion downstream is about a file nobody touched."""
    db_path = _build_v7_file(source_dir, mask)
    assert _user_version(db_path) == 7
    assert "excluded" not in _columns(db_path), "the v7 fixture is already v8"

    with open_project(project_dir_for(source_dir)):
        pass

    # 9 since MT-119 C-4: opening a v7 file runs the v8 -> v9 step as well.
    assert _user_version(db_path) == 10, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


def _check_refuses_reasons_outside_the_two(db_path: Path) -> None:
    """C-2's CHECK: NULL, `'watermark'` and `'user'`, and nothing else."""
    connection = sqlite3.connect(db_path)
    try:
        region_id = connection.execute("SELECT id FROM region ORDER BY id").fetchone()[0]
        for bad in ("banana", "Watermark", "USER", "", "none"):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                connection.execute("UPDATE region SET excluded = ? WHERE id = ?", (bad, region_id))
        # The legal values are accepted, so the refusal is about the value and
        # not about the column being unwritable.
        for good in ("watermark", "user", None):
            connection.execute("UPDATE region SET excluded = ? WHERE id = ?", (good, region_id))
        connection.rollback()
    finally:
        connection.close()


@pytest.fixture
def mask(one_bit_png: Callable[..., bytes]) -> bytes:
    """A real 1-bit PNG, because `RawRegion` refuses anything else (MT-007 C-7)."""
    return one_bit_png(7, 3, [(0, 0, 2, 2)])


# -- the version, and the fresh table --------------------------------------------


def test_this_build_writes_and_reads_the_current_schema_version(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-2's bump, in both records of it (MT-005 PO-7)."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"), mask)

    # MT-119 C-4 takes it to 9: `cleaned_page.erased`. `test_schema_v9.py` owns it.
    assert SCHEMA_VERSION == 10
    assert _user_version(db_path) == 10
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(10,)]


def test_a_fresh_region_table_has_a_nullable_excluded_column_declared_last(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"), mask)

    assert _columns(db_path) == _REGION_COLUMNS_V8
    shape = {str(row[0]): row[1:] for row in _raw(db_path, _SHAPE)}
    assert shape["excluded"] == ("TEXT", 0, None, 0), "C-2: nullable, no DEFAULT"


def test_a_fresh_file_declares_the_check_c2_writes(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-2's declaration, read back from the file rather than from `schema.py`'s
    text, so it is the CHECK SQLite actually holds."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"), mask)

    assert _excluded_declaration(db_path) == _EXCLUDED_DECLARATION


def test_a_fresh_file_refuses_a_reason_outside_the_two(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    _check_refuses_reasons_outside_the_two(_fresh(_sources(tmp_path, png_bytes, "scans"), mask))


def test_a_freshly_written_region_is_included(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"), mask)

    assert _raw(db_path, "SELECT excluded FROM region") == [(None,)] * 3


# -- AC-4: the v7 -> v8 step ---------------------------------------------------------


def test_a_version_seven_file_is_migrated_to_eight_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """AC-4: "`schema_version` is 8" - in both records of it."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"), mask)

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(10,)]  # MT-103 PO-3
    assert _columns(db_path) == _REGION_COLUMNS_V8


def test_a_migrated_region_table_is_the_same_table_as_a_fresh_one(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"), mask)
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"), mask)

    assert _raw(migrated, _SHAPE) == _raw(fresh, _SHAPE)


def test_the_migration_and_the_fresh_schema_store_the_same_check(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-2: the `schema.py` text and the `ALTER` text are two strings, and this
    is what holds them to each other - through `sqlite_master.sql`, as
    `test_schema_v7.py` holds `cleaned_page`. Both are also held to C-2's
    literal, so the pair cannot agree on a different CHECK.

    `table_info` does not report a CHECK at all, which is why the shape test
    above cannot see this and the refusal tests below see only its effect."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"), mask)
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"), mask)

    assert _excluded_declaration(migrated) == _excluded_declaration(fresh)
    assert _excluded_declaration(migrated) == _EXCLUDED_DECLARATION


def test_a_migrated_file_refuses_a_reason_outside_the_two(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """The CHECK arrives with the column on the migration path too."""
    _check_refuses_reasons_outside_the_two(_migrated(_sources(tmp_path, png_bytes, "scans"), mask))


def test_every_region_a_version_seven_file_held_reads_back_included_and_unchanged(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """**AC-4**: "every region reads back with `excluded is None` and every
    other column unchanged". Both through a plain sqlite reader - NULL on disk,
    and every v7 column byte-for-byte - and through the store, which is what the
    pipeline reads. DV-2 (`DEFAULT 'user'` in the migration) is aimed here."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v7_file(source_dir, mask)
    v7_columns = "id, page_id, reading_index, polygon, mask_blob, kind, confidence, merged_from"
    before = _raw(db_path, f"SELECT {v7_columns} FROM region ORDER BY id")

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 10  # MT-103 PO-3
    assert _raw(db_path, f"SELECT {v7_columns} FROM region ORDER BY id") == before
    assert _raw(db_path, "SELECT excluded FROM region ORDER BY id") == [(None,)] * 3

    with open_project(project_dir_for(source_dir)) as project:
        regions = project.read_regions(0)
    assert [region.excluded for region in regions] == [None, None, None]
    assert [(region.kind, region.confidence, region.merged_from) for region in regions] == [
        ("bubble", 0.5, ()),
        ("box", 0.25, (0, 2)),
        ("bubble", 1.0, ()),
    ]
    assert all(region.mask == mask for region in regions)


def test_the_v8_step_changes_only_the_region_table(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """C-2 is one `ADD COLUMN`; nothing else in the file has any business
    changing - no other schema object, and no row of any other table. A
    migration written as a rebuild of `region` would take its `line` rows with
    it by cascade and show here as well as above."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v7_file(source_dir, mask)
    # `cleaned_page` excluded since MT-119: a v7 file opened today also runs the
    # v8 -> v9 step, which ALTERs `cleaned_page` on purpose (C-4) and so rewrites
    # its stored DDL and gives every row an `erased` cell; `test_schema_v9.py`
    # owns what that step does. Its two v7 columns are still compared, below.
    # `batch_job`, `chapter`, `correction` and `llm_call` excluded since MT-103: the
    # v9 -> v10 step creates the first and third, ALTERs `chapter` and rebuilds
    # `llm_call` on purpose; `test_schema_v10.py` owns what that step does.
    schema = (
        "SELECT type, name, sql FROM sqlite_master"
        " WHERE name NOT IN ('batch_job', 'chapter', 'cleaned_page', 'correction',"
        " 'llm_call', 'region') ORDER BY name"
    )
    tables = ("page", "line", "run", "glossary")

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
        found["cleaned_page"] = _raw(
            db_path, "SELECT page_id, image_blob FROM cleaned_page ORDER BY rowid"
        )
        return found

    schema_before = _raw(db_path, schema)
    rows_before = rows()
    assert rows_before["line"] != [], "the v7 fixture has no lines to preserve"
    assert rows_before["cleaned_page"] != [], "the v7 fixture has no cleaned image to preserve"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 10  # MT-103 PO-3
    assert _raw(db_path, schema) == schema_before
    rows_after = rows()
    # The chapter row's `schema_version` is the one cell the step must change.
    assert [row[:4] + row[5:] for row in rows_after["chapter"]] == [
        row[:4] + row[5:] for row in rows_before["chapter"]
    ]
    assert {t: r for t, r in rows_after.items() if t != "chapter"} == {
        t: r for t, r in rows_before.items() if t != "chapter"
    }


def test_a_migrated_project_accepts_an_exclusion(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    source_dir = _sources(tmp_path, png_bytes, "scans")
    _migrated(source_dir, mask)

    with open_project(project_dir_for(source_dir)) as project:
        project.set_excluded(0, 1, "watermark")
        assert [region.excluded for region in project.read_regions(0)] == [
            None,
            "watermark",
            None,
        ]


# -- AC-4: a version-8 file and an older reader -------------------------------------


def test_a_version_eight_file_is_refused_by_a_reader_that_supports_seven(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    mask: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-4**'s last clause: a v8 file handed to a build whose
    `SCHEMA_VERSION` is 7 raises `SchemaTooNew` naming both numbers, before
    any read - the excluded regions of a newer file are not quietly read as
    included by an older build. `open_project` reads the module's
    `SCHEMA_VERSION` at call time, so a v7 reader is this build with the
    constant set back to 7."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir, mask)
    # MT-119 C-4: a fresh file is version 9 now. The refusal comes before any
    # read, so the file is stamped 8 - the version this test is about - with a
    # plain connection; what its tables hold beyond that is never reached.
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA user_version = 8")
    finally:
        connection.close()
    assert _user_version(db_path) == 8, "the fixture is not a version-8 file"

    monkeypatch.setattr(project_module, "SCHEMA_VERSION", 7)
    with pytest.raises(SchemaTooNew) as excinfo:
        open_project(project_dir_for(source_dir))

    # Anchored to the words around each number, because the message also
    # carries the file's path and a bare `7` matches a `pytest-7` temp dir.
    message = str(excinfo.value)
    assert re.search(r"\bversion 8\b", message), message
    assert re.search(r"\bsupports 7\b", message), message
    assert _user_version(db_path) == 8, "the refusal must not have migrated anything"


def test_the_same_version_eight_file_opens_in_this_build(
    tmp_path: Path, png_bytes: Callable[..., bytes], mask: bytes
) -> None:
    """The control for the refusal above: without it, a store that raised
    `SchemaTooNew` for every file would pass it. (Since MT-119 the fresh file
    is version 9, which is this build's; `test_schema_v9.py` holds the same
    control for the version-9 refusal.)"""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    _fresh(source_dir, mask)

    with open_project(project_dir_for(source_dir)) as project:
        assert len(project.read_regions(0)) == 3
