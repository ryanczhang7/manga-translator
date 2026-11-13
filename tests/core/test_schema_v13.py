"""MT-146: schema version 13, and the v12 -> v13 step - `art` as an exclusion reason.

`region.excluded` gains a third value, `'art'`: the page answer's call that a
region is drawn art text (MT-147 writes it). SQLite cannot change a CHECK in
place, so the v12 -> v13 step **rebuilds `region`** - and `region` is a
*parent*: `line.region_id ... REFERENCES region(id) ON DELETE CASCADE`. The
story's pinned `## Contract` C-1 therefore takes `_MIGRATE_TO_V4`'s recipe
(`PRAGMA foreign_keys = OFF` and `PRAGMA legacy_alter_table = ON` first), not
`_MIGRATE_TO_V10`'s, and the fresh schema and the migration share one string,
`schema.REGION_DDL`, so their declarations cannot drift.

**AC-3** is the migration keeping everything: every region, line and cleaned
page comes through with the same ids, in the same order, with the same blobs.
The fixture's ids are deliberately **not** `1..n` and not in reading order, so a
copy that let SQLite renumber the rows (an `INSERT ... SELECT` without `id`)
is caught, and so is one that lost the link from a line to its region.

**AC-4** is the control `_MIGRATE_TO_V4`'s docstring measured the need for, on
the same file: deleting a page still cascades to its regions and their lines,
`PRAGMA foreign_key_check` is **empty** - asserted `== []`, never as a length,
because the violation count is one per surviving child row, a property of the
fixture - and `line`'s foreign key names `region`, not the aside table. These
pass on a correct migration; the story's `## Handoff` records what each shows
under the plain `_MIGRATE_TO_V10` recipe, measured on a candidate outside the
tree.

**Where the v12 file comes from.** `_V12_DDL` below, built in the test with
`sqlite3` and nothing else - every earlier `test_schema_v*.py`'s precedent. No
binary fixture is committed.

**`_V12_DDL` is a historical artefact and must never be updated to track
`schema.py`** - `test_schema_v12.py`'s `_V11_DDL` carries the same instruction
for the same reason: the day it is "fixed" to match the current schema is the
day this suite stops testing a migration. Transcribed in RED on 2026-11-10 from
`mangatl.store.schema.DDL` as it shipped at version 12 (MT-115; `schema.py` at
commit 57fc63d), by executing that revision's module and printing its `DDL`
with every line whose first non-blank characters are `--` removed and runs of
blank lines squeezed to one, so the transcription is mechanical rather than
retyped. Its `region` CHECK is the two-value one, and that is the point.

**RED.** `SCHEMA_VERSION` is 12, no step to 13 exists and the CHECK refuses
`'art'`, so every test here fails on the version, on the CHECK, or on
`EXCLUSION_REASONS` refusing `"art"` - except AC-4's controls and the
"unchanged" comparisons, which hold of a file that was never migrated and are
guarded by `_migrated`'s assertion that a migration ran.

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

#: The `excluded` declaration a version 13 file stores, whitespace collapsed
#: (C-1). Written out rather than read off `schema.py`, because a declaration
#: derived from the thing under test agrees with it by construction.
_EXCLUDED_V13 = "excluded TEXT CHECK (excluded IS NULL OR excluded IN ('watermark', 'user', 'art'))"

#: The 8 bytes `RawRegion` checks a mask begins with; the rest of each fixture
#: mask is distinct, so a blob copied to the wrong row shows.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: The v12 fixture's regions: (id, page index, reading_index, excluded,
#: merged_from JSON or NULL). Ids are neither `1..n` nor in reading order, so a
#: rebuild that renumbered rows cannot reproduce them. Page 0 holds the three
#: stored values a version 12 file can hold - NULL, `watermark`, `user` - in
#: reading order; page 1 holds one included region, the bystander of AC-4's
#: delete.
_V12_REGIONS: tuple[tuple[int, int, int, str | None, str | None], ...] = (
    (17, 0, 0, None, None),
    (4, 0, 1, "watermark", "[0, 2]"),
    (29, 0, 2, "user", None),
    (11, 1, 0, None, None),
)

#: The v12 fixture's lines: (id, region id, source_ja, proposed_en, final_en,
#: status). One per region, ids again out of step with the regions'.
_V12_LINES: tuple[tuple[int, int, str, str | None, str | None, str | None], ...] = (
    (90, 17, "一つ目", "First.", None, None),
    (73, 4, "二つ目", "Second.", "Second!", "edited"),
    (81, 29, "三つ目", None, None, None),
    (66, 11, "四つ目", "Fourth.", "Fourth.", "accepted"),
)

#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V12_DDL = """
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


def _region_sql(db_path: Path) -> str:
    """`region`'s stored `CREATE TABLE`, byte for byte as SQLite holds it."""
    rows = _raw(db_path, "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'region'")
    assert len(rows) == 1, f"expected one `region` table, found {rows}"
    return str(rows[0][0])


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


def _ring(i: int) -> str:
    return f"[[{i}, 0], [{i + 2}, 0], [{i + 2}, 2], [{i}, 2], [{i}, 0]]"


def _mask(region_id: int) -> bytes:
    return _PNG_SIGNATURE + f"mask of region {region_id}".encode()


def _build_v12_file(source_dir: Path) -> Path:
    """A schema-version-12 file built with `_V12_DDL` and nothing else: four
    pages, `_V12_REGIONS` with `_V12_LINES`, a cleaned image on each of the two
    pages that have regions, and a glossary term - AC-3's inventory."""
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V12_DDL)
        connection.execute("PRAGMA user_version = 12")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version,"
            " budget_ceiling_micro_usd, model_id, rate_table_version, glossary_proposed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(source_dir),
                str(source_dir) + "_en",
                "2026-11-09T00:00:00+00:00",
                12,
                3_000_000,
                "gemini-3.1-pro-preview",
                "2026-10-01",
                "2026-11-09T00:00:30+00:00",
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
        for region_id, page, reading_index, excluded, merged_from in _V12_REGIONS:
            cursor.execute(
                "INSERT INTO region (id, page_id, reading_index, polygon, mask_blob, kind,"
                " confidence, merged_from, excluded) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    region_id,
                    page_ids[page],
                    reading_index,
                    _ring(region_id),
                    _mask(region_id),
                    "box" if region_id % 2 else "bubble",
                    region_id / 100,
                    merged_from,
                    excluded,
                ),
            )
        for line_id, region_id, source_ja, proposed_en, final_en, status in _V12_LINES:
            cursor.execute(
                "INSERT INTO line (id, region_id, source_ja, proposed_en, final_en, status)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (line_id, region_id, source_ja, proposed_en, final_en, status),
            )
        cursor.execute(
            "INSERT INTO cleaned_page (page_id, image_blob, erased) VALUES (?, ?, ?)",
            (page_ids[0], b"page zero cleaned", "[0, 2]"),
        )
        cursor.execute(
            "INSERT INTO cleaned_page (page_id, image_blob, erased) VALUES (?, ?, ?)",
            (page_ids[1], b"page one cleaned", "[0]"),
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


def _migrated(source_dir: Path) -> Path:
    """Build a v12 file and open it once, asserting a migration RAN - without
    which every "unchanged" assertion downstream is about a file nobody
    touched, and every AC-4 control holds vacuously."""
    db_path = _build_v12_file(source_dir)
    assert _user_version(db_path) == 12
    assert "'art'" not in _region_sql(db_path), "the v12 fixture is already v13"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 14, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )
    return db_path


#: Every table AC-3 names, read whole, in id order (`cleaned_page`'s key is its
#: `page_id`).
_KEPT = {
    "region": "SELECT * FROM region ORDER BY id",
    "line": "SELECT * FROM line ORDER BY id",
    "cleaned_page": "SELECT * FROM cleaned_page ORDER BY page_id",
    "glossary": "SELECT * FROM glossary ORDER BY id",
    "page": "SELECT * FROM page ORDER BY id",
}


def _kept(db_path: Path) -> dict[str, list[tuple[object, ...]]]:
    return {table: _raw(db_path, sql) for table, sql in _KEPT.items()}


# -- the version ---------------------------------------------------------------------


def test_this_build_writes_and_reads_the_current_schema_version(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """MT-146's bump, in both records of it (MT-005 PO-7)."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert SCHEMA_VERSION == 14
    assert _user_version(db_path) == 14
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(14,)]


# -- the fresh file ------------------------------------------------------------------


def test_a_fresh_region_table_declares_the_three_reasons(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-1's CHECK, read back from the file rather than from `schema.py`'s
    text, so it is the CHECK SQLite actually holds."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))

    assert _EXCLUDED_V13 in " ".join(_region_sql(db_path).split())


def test_the_region_ddl_is_its_own_exported_string_inside_the_schema() -> None:
    """C-1: one definition with two callers - `DDL` and the v13 rebuild - the
    `CHAPTER_DDL` precedent, so a fresh file and a migrated one cannot build two
    different `region` tables. Exported, carried verbatim by `DDL` exactly once,
    and declaring the three reasons. Imported inside the test so that, while
    the name does not exist, only this test fails at the import."""
    import mangatl.store.schema as module

    assert "REGION_DDL" in module.__all__
    assert module.DDL.count(module.REGION_DDL) == 1
    assert module.DDL.count("CREATE TABLE region (") == 1
    assert _EXCLUDED_V13 in " ".join(module.REGION_DDL.split())


def test_a_fresh_file_stores_art_and_still_refuses_any_other_reason(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The CHECK in effect: `'art'` is written and read back by a plain
    connection, and its near misses are refused - so a CHECK widened to
    anything rather than to the one value is caught."""
    db_path = _fresh(_sources(tmp_path, png_bytes, "scans"))
    page_id = _raw(db_path, "SELECT id FROM page ORDER BY ordinal")[0][0]
    insert = (
        "INSERT INTO region (page_id, reading_index, polygon, mask_blob, kind, confidence,"
        " excluded) VALUES (?, ?, '[]', x'00', 'bubble', 0.5, ?)"
    )

    _raw(db_path, insert, (page_id, 0, "art"))
    assert _raw(db_path, "SELECT excluded FROM region") == [("art",)]

    for index, bad in enumerate(("artwork", "Art", "ART", "", "art "), start=1):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            _raw(db_path, insert, (page_id, index, bad))
    assert _raw(db_path, "SELECT excluded FROM region") == [("art",)]


# -- AC-3: the v12 -> v13 step -------------------------------------------------------


def test_a_version_twelve_file_is_migrated_to_thirteen_when_it_is_opened(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """AC-3: "it is version 13" - in both records of the version."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(14,)]


def test_every_region_line_cleaned_page_and_glossary_row_comes_through_unchanged(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """AC-3: "every region, line and cleaned page is unchanged: same ids, same
    order, same blobs" - every column of every row, raw, before and after, the
    glossary and the pages with them. A line cascade-deleted by the rebuild, a
    region renumbered, or a blob swapped all show here."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _build_v12_file(source_dir)
    before = _kept(db_path)
    assert all(before.values()), f"the v12 fixture has an empty table: {before}"
    assert [row[0] for row in before["region"]] == [4, 11, 17, 29]
    assert [row[0] for row in before["line"]] == [66, 73, 81, 90]

    _migrated_in_place(source_dir, db_path)

    # MT-149: the open walks on through the v13 -> v14 step, which appends
    # `line.misaligned` (DEFAULT 0) and nothing else. Every row this file held
    # comes through with that one trailing 0; `test_schema_v14.py` owns the step.
    before["line"] = [(*row, 0) for row in before["line"]]
    after = _kept(db_path)
    for table in _KEPT:
        assert after[table] == before[table], f"`{table}` changed in the v13 step"


def _migrated_in_place(source_dir: Path, db_path: Path) -> None:
    """Open an already-built v12 file once and require that it migrated."""
    with open_project(project_dir_for(source_dir)):
        pass
    assert _user_version(db_path) == 14, (
        f"the file is still at version {_user_version(db_path)} after open_project"
    )


def test_regions_keep_their_reading_order_and_their_reasons_through_the_store(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """AC-3's "same order", as the store reads it: page 0's regions in reading
    order are NULL, `watermark`, `user`, each with its own mask and
    `merged_from` - the reading order the ids above are deliberately out of
    step with."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    _migrated(source_dir)

    with open_project(project_dir_for(source_dir)) as project:
        regions = project.read_regions(0)

    assert [region.excluded for region in regions] == [None, "watermark", "user"]
    assert [region.mask for region in regions] == [_mask(17), _mask(4), _mask(29)]
    assert [region.merged_from for region in regions] == [(), (0, 2), ()]


def test_art_can_be_written_to_a_migrated_file_and_reads_back(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """AC-3: "`art` can now be written" - through `Project.set_excluded`, on
    the migrated file, observed by a plain connection and by a reopened
    store. Only the target row's `excluded` moves."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _migrated(source_dir)
    before = _raw(db_path, "SELECT id, excluded FROM region ORDER BY id")

    with open_project(project_dir_for(source_dir)) as project:
        project.set_excluded(0, 0, "art")

    expected = [(rid, "art" if rid == 17 else value) for rid, value in before]
    assert _raw(db_path, "SELECT id, excluded FROM region ORDER BY id") == expected
    with open_project(project_dir_for(source_dir)) as reopened:
        assert [r.excluded for r in reopened.read_regions(0)] == ["art", "watermark", "user"]


def test_a_migrated_file_still_refuses_a_reason_outside_the_three(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """The control for the widening: the rebuilt CHECK is not dropped or
    loosened, it admits exactly one more value."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    for bad in ("artwork", "Art", "banana", ""):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            _raw(db_path, "UPDATE region SET excluded = ? WHERE id = 17", (bad,))
    assert _raw(db_path, "SELECT excluded FROM region WHERE id = 17") == [(None,)]


def test_a_migrated_region_table_is_declared_exactly_as_a_fresh_one(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """AC-3: "`sqlite_master.sql` for `region` is identical to a fresh version
    13 file's" - byte for byte, not whitespace-collapsed, and both hold C-1's
    three-value CHECK, so the pair cannot agree on the old one. Every other
    `sqlite_master` entry agrees too: the rebuild leaves no aside table and no
    stray index behind."""
    migrated = _migrated(_sources(tmp_path, png_bytes, "migrated"))
    fresh = _fresh(_sources(tmp_path, png_bytes, "fresh"))

    assert _region_sql(migrated) == _region_sql(fresh)
    assert _EXCLUDED_V13 in " ".join(_region_sql(fresh).split())
    assert _schema(migrated) == _schema(fresh)


def test_the_rebuild_leaves_no_aside_table_and_only_the_unique_keys_index(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """C-1: `region`'s one index is the automatic one behind `UNIQUE
    (page_id, reading_index)` - the region writer's upsert depends on it - and
    nothing named for version 12 survives."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    indexes = _raw(
        db_path,
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'region'",
    )
    assert indexes == [("sqlite_autoindex_region_1",)]
    assert _raw(db_path, "SELECT name FROM sqlite_master WHERE name LIKE '%v12%'") == []


# -- AC-4: the rebuild keeps its foreign keys (control) --------------------------------


def test_deleting_a_migrated_page_cascades_to_its_regions_and_their_lines(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """AC-4: page 0's three regions and their three lines go with it; page 1's
    region and line stay. The precondition matters: a rebuild that had already
    cascade-deleted every line would pass "no line is left" vacuously."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))
    lines_of_page_zero = (
        "SELECT line.id FROM line JOIN region ON region.id = line.region_id"
        " JOIN page ON page.id = region.page_id WHERE page.ordinal = 0 ORDER BY line.id"
    )
    assert _raw(db_path, lines_of_page_zero) == [(73,), (81,), (90,)], (
        "precondition: page 0's lines did not survive the migration"
    )

    _raw(db_path, "DELETE FROM page WHERE ordinal = 0")

    assert _raw(db_path, "SELECT id FROM region ORDER BY id") == [(11,)]
    assert _raw(db_path, "SELECT id, region_id FROM line ORDER BY id") == [(66, 11)]


def test_a_migrated_file_has_no_foreign_key_violations(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """AC-4: `PRAGMA foreign_key_check` reports nothing - asserted empty, never
    as a count (`_MIGRATE_TO_V4`'s note: the count is one per surviving child
    row, a property of the fixture, not of the recipe)."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    assert _raw(db_path, "PRAGMA foreign_key_check") == []


def test_a_migrated_lines_foreign_key_names_region_not_the_aside_table(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """AC-4 / C-1: (table, from, to, on_delete) of `line`'s one foreign key.
    Without `legacy_alter_table = ON` the rename repoints it at `region_v12`,
    and the rows survive with a reference to a table that no longer exists."""
    db_path = _migrated(_sources(tmp_path, png_bytes, "scans"))

    keys = [
        (table, source, target, on_delete)
        for _id, _seq, table, source, target, _update, on_delete, _match in _raw(
            db_path, "SELECT * FROM pragma_foreign_key_list('line')"
        )
    ]
    assert keys == [("region", "region_id", "id", "CASCADE")], keys


# -- a version-15 file (14 when MT-146 wrote it; MT-149 moved it to 15) -------


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
    """The control for the refusal above."""
    source_dir = _sources(tmp_path, png_bytes, "scans")
    db_path = _fresh(source_dir)
    assert _user_version(db_path) == 14

    with open_project(project_dir_for(source_dir)) as project:
        assert len(project.pages()) == len(_SOURCE_PAGES)
    assert _user_version(db_path) == 14
