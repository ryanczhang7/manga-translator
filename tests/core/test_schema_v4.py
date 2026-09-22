"""MT-044 C-12: schema version 4, and the v3 -> v4 rebuild of `chapter`.

`chapter.budget_ceiling_usd REAL` becomes `budget_ceiling_micro_usd INTEGER`,
in the same column position, so AC-5 can read a ceiling off the chapter row as
the integer micro-dollars MT-012 PO-2 settled money on. This file also covers
**C-10**, `Project.budget_ceiling()`, which is the reader AC-5 is asserted
through.

**Why this migration gets a file of its own.** Every migration before it
rebuilt or altered a *leaf* table - `line` (v2) and `llm_call` (v3). `chapter`
is a **parent** with three cascading children, `page`, `run` and `glossary`, and
MT-012's rebuild recipe applied here destroys the project in two different ways,
**neither of which raises**.

**"The rebuild preserved the project" has no settled oracle, and the obvious
metric is the wrong one.** The metric used here is four things together, and
each one alone is green against a database that is broken in a different way:

1. row counts in `page`, `run` and `glossary` unchanged across the migration;
2. `PRAGMA foreign_key_check` returns empty;
3. no child table's DDL in `sqlite_master` names `chapter_v3`;
4. `PRAGMA foreign_keys` reads `1` on the `Project` returned by the
   `open_project` call **that ran the migration** - never on a later one. The
   pragma is connection state, so a reopen of an already-migrated file reports
   `_connect`'s own `PRAGMA foreign_keys = ON` and discriminates nothing; that
   was R-9, and `_migrating` below exists to make the right session reachable.

MEASURED by RED out of the test framework on **2026-09-21**, sqlite 3.53.1, on a
fixture of 1 chapter, 2 pages, 1 run and 1 glossary row - a plain `sqlite3`
script with no `mangatl` import at all, because these are claims about SQLite
and not about anything this story builds:

    recipe                               child FK  pages runs gloss fk_check   pragma
    A  no pragmas (MT-012's, literally)  chapter_v3    0    0     0  []          1
    C  foreign_keys=OFF only             chapter_v3    2    1     1  4 rows      0->1
    D/E both pragmas (the pinned recipe) chapter       2    1     1  []          0->1

Read that carefully, because it is why the metric is a conjunction:

* **Recipe C's row counts are identical to the correct recipe's.** A migration
  test that counts rows is green against a database whose every foreign key
  points at a dropped table. Only metrics 2 and 3 separate them. This is
  **DV-2**.
* **Recipe A's `foreign_key_check` is empty.** A test that only checks foreign
  keys is green against a database with **no pages and no runs in it** - the
  `DROP TABLE chapter_v3` cascaded and deleted the project. Only metrics 1 and 3
  separate them. This is **DV-3**'s first half.
* **Recipe A's `PRAGMA foreign_keys` reads 1 too**, because it never turned the
  pragma off. Metric 4 catches neither A nor C; what it catches is the
  *restore's placement*, measured separately below. This is **DV-3**'s second
  half.

**The restore's placement, measured 2026-09-21 on the same script:**

    restore before commit ->  0      # silent no-op; still 0 after the commit
      after commit        ->  0
    restore after commit  ->  1

`project.py`'s own docstring already records the general form - "the pragma set
*inside* an explicit transaction is a silent no-op that reads back `0`" - and
the `UPDATE chapter SET schema_version = ?` opens exactly such a transaction
under sqlite3's legacy isolation handling. A migration that left foreign keys
off would silently disable MT-007's per-page invalidation for the rest of the
session, and every row count would still look right.

**`_V3_DDL` below is a historical artefact and must never be updated to track
`schema.py`** - `test_ledger.py`'s `_V2_DDL` and `test_line_store.py`'s `_V1_DDL`
carry the same instruction, for the same reason. The day someone "fixes" it to
match the current schema is the day this stops testing a migration.

**Timing.** There is no `pytest-timeout` in this project and no per-test
timeout, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. Every test builds a two-page chapter of tiny
PNGs on `tmp_path`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from mangatl.domain.money import Usd
from mangatl.store.intake import read_chapter
from mangatl.store.project import (
    SCHEMA_VERSION,
    Project,
    create_project,
    open_project,
    project_dir_for,
)

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
)

#: The `chapter` table's columns **in declaration order** at version 4. The
#: order is the criterion, not the set: C-12 puts `budget_ceiling_micro_usd` in
#: the same (sixth) position the REAL column held, so a `SELECT *` behaves the
#: same on a migrated file as on a new one - MT-010's ordering invariant, which
#: `schema.py` already states in general terms about `line.ocr_empty`.
_CHAPTER_COLUMNS_V4: tuple[str, ...] = (
    "id",
    "source_dir",
    "output_dir",
    "created_at",
    "schema_version",
    "budget_ceiling_micro_usd",
    "model_id",
    "rate_table_version",
)

#: The three tables that cascade off `chapter`. Named explicitly rather than
#: discovered, because a migration that dropped one of them entirely would make
#: a discovered list agree with the damage.
_CHILDREN: tuple[str, ...] = ("page", "run", "glossary")

#: The ceiling the v3 fixture already holds, as a REAL, and what it must become.
#: `1.5` is exactly representable as a double, so the conversion has nothing to
#: round and the assertion is about the migration converting **at all** rather
#: than about how it rounds a hard case.
_V3_CEILING_USD = 1.5
_V4_CEILING_MICRO = 1_500_000

#: The schema **as it shipped at version 3**, transcribed in RED from
#: `src/mangatl/store/schema.py` before this story changed it. Comments dropped;
#: every statement, column, type, constraint, cascade and trigger is faithful to
#: what MT-005 wrote and MT-007, MT-010 and MT-012 extended.
#:
#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES. See the module docstring.
_V3_DDL = """
CREATE TABLE chapter (
    id                 INTEGER PRIMARY KEY,
    source_dir         TEXT    NOT NULL,
    output_dir         TEXT    NOT NULL,
    created_at         TEXT    NOT NULL,
    schema_version     INTEGER NOT NULL,
    budget_ceiling_usd REAL,
    model_id           TEXT,
    rate_table_version TEXT
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


# -- helpers -------------------------------------------------------------------


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _columns(db_path: Path, table: str) -> tuple[str, ...]:
    """The table's columns **in declaration order**."""
    return tuple(str(row[1]) for row in _raw(db_path, f"PRAGMA table_info({table})"))


def _user_version(db_path: Path) -> int:
    return int(_raw(db_path, "PRAGMA user_version")[0][0])


def _counts(db_path: Path) -> dict[str, int]:
    """Metric 1: one row count per cascading child, plus the parent itself."""
    return {
        table: int(_raw(db_path, f"SELECT count(*) FROM {table}")[0][0])
        for table in ("chapter", *_CHILDREN)
    }


def _tables_naming(db_path: Path, name: str) -> list[str]:
    """Metric 3: every table whose stored DDL mentions `name`.

    Read out of `sqlite_master`, which is where the damage recipe C leaves
    actually lives: the rows survive, the counts agree with a correct
    migration's, and every child still declares a foreign key into a table that
    no longer exists.
    """
    return sorted(
        str(row[0])
        for row in _raw(db_path, "SELECT name, sql FROM sqlite_master WHERE type = 'table'")
        if name in str(row[1] or "")
    )


def _fk_violations(db_path: Path) -> list[tuple[object, ...]]:
    """Metric 2: `PRAGMA foreign_key_check`, which must come back empty."""
    return _raw(db_path, "PRAGMA foreign_key_check")


def _build_v3_file(source_dir: Path, *, ceiling_usd: float | None) -> Path:
    """A schema-version-3 project file, built with `_V3_DDL` and nothing else.

    No `create_project`, no `Project`, no `schema.DDL` - so the file this
    function produces cannot silently acquire a v4 column when `schema.py`
    changes. It carries one chapter, two pages, one run and one glossary row,
    because "the rebuild preserved the project" needs a project to preserve and
    all three of those tables cascade off `chapter`.
    """
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V3_DDL)
        connection.execute("PRAGMA user_version = 3")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version,"
            " budget_ceiling_usd) VALUES (?, ?, ?, ?, ?)",
            (
                str(source_dir),
                str(source_dir) + "_en",
                "2026-09-18T00:00:00+00:00",
                3,
                ceiling_usd,
            ),
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
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at, ended_at, outcome) VALUES (?, ?, ?, ?)",
            (chapter_id, "2026-09-18T00:00:00+00:00", "2026-09-18T00:10:00+00:00", "finished"),
        )
        cursor.execute(
            "INSERT INTO glossary (chapter_id, term_ja, term_en, first_seen_page)"
            " VALUES (?, ?, ?, ?)",
            (chapter_id, "醜鬼", "Ugly Ogre", 0),
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


@contextmanager
def _migrating(
    source_dir: Path, *, ceiling_usd: float | None = _V3_CEILING_USD
) -> Iterator[tuple[Project, Path, dict[str, int]]]:
    """Build a v3 file, open it, and yield **the session that migrated it**.

    This guard is not decoration, and RED measured why: with `SCHEMA_VERSION`
    still at 3, `open_project` takes neither the `found > SCHEMA_VERSION` nor
    the `found < SCHEMA_VERSION` branch, so it migrates **nothing** - and a
    file that was never touched trivially satisfies every one of the four
    metrics below. Row counts unchanged, `foreign_key_check` empty, no
    `chapter_v3` anywhere, foreign keys on. Three of the tests in this file
    passed on arrival for exactly that reason before this function existed.

    So every migration test goes through here, and the assertions around the
    `yield` are the precondition that makes the rest of it a claim about a
    rebuild rather than about a file nobody opened.

    **The `Project` yielded is the one `open_project` returned from the call
    that ran `_migrate_to_current`, and metric 4 may be read from no other**
    (R-9). `PRAGMA foreign_keys` is a property of a *connection*, not of the
    file: once `user_version` is 4, a second `open_project` skips the migration
    entirely and reports the `PRAGMA foreign_keys = ON` that `_connect` sets on
    every connection ever made - which is true of a file nobody migrated, and
    true under every broken recipe. That is this helper's own stated hazard
    ("a file that was never touched trivially satisfies every one of the four
    metrics ... foreign keys on") recurring one level up, in session state
    instead of in file state.
    """
    db_path = _build_v3_file(source_dir, ceiling_usd=ceiling_usd)
    assert _user_version(db_path) == 3
    assert "budget_ceiling_usd" in _columns(db_path, "chapter"), "the v3 fixture is already v4"
    before = _counts(db_path)
    assert before == {"chapter": 1, "page": len(_SOURCE_PAGES), "run": 1, "glossary": 1}, (
        f"the v3 fixture holds {before}; there is nothing for the migration to"
        " preserve and every row-count assertion downstream is vacuous"
    )

    with open_project(project_dir_for(source_dir)) as project:
        assert _user_version(db_path) == 4, (
            f"the file is still at version {_user_version(db_path)} after open_project:"
            " no migration ran, and every metric below is vacuously satisfied by a"
            " file nobody rebuilt"
        )
        assert _columns(db_path, "chapter") == _CHAPTER_COLUMNS_V4
        yield project, db_path, before


def _migrated(
    source_dir: Path, *, ceiling_usd: float | None = _V3_CEILING_USD
) -> tuple[Path, dict[str, int]]:
    """`_migrating`, for the tests that assert about **the file on disk**.

    The migrating session is opened, checked and closed here, so what a caller
    gets back is a path and the row counts the fixture went in with. That is
    the right shape for every assertion about persisted state - a column list, a
    converted ceiling, `sqlite_master`, `foreign_key_check` - because those are
    facts about the file and are equally true through any connection.

    It is the wrong shape for anything about the migrating **connection**, and
    a caller that reaches for `open_project` again to get one has thrown the
    evidence away. Use `_migrating` for that; see its docstring and R-9.
    """
    with _migrating(source_dir, ceiling_usd=ceiling_usd) as (_project, db_path, before):
        return db_path, before


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    directory = tmp_path / "scans"
    directory.mkdir()
    for filename, width, height in _SOURCE_PAGES:
        (directory / filename).write_bytes(png_bytes(width, height))
    return directory


@pytest.fixture
def fresh(source_dir: Path) -> Iterator[Project]:
    """A project `create_project` built at the current version."""
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield project


# -- the version, and the fresh table ------------------------------------------


def test_this_build_writes_and_reads_schema_version_four(fresh: Project, source_dir: Path) -> None:
    """C-12's bump, stated once where a reader looks for it.

    AC-5 is unsatisfiable against version 3 - `budget_ceiling_usd` is a REAL,
    and MT-012 PO-2 already settled that money on disk is an integer count of
    micro-dollars because a double cannot hold an exact decimal amount.
    """
    db_path = project_dir_for(source_dir) / "project.db"

    assert SCHEMA_VERSION == 4
    assert _user_version(db_path) == 4
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(4,)]


def test_a_freshly_created_chapter_table_has_the_ceiling_column_in_position_six(
    fresh: Project, source_dir: Path
) -> None:
    """C-12's column **order**, not merely its column set.

    `budget_ceiling_micro_usd` replaces `budget_ceiling_usd` in the same
    position, so a `SELECT *` behaves the same on a migrated file as on a new
    one. Appending it at the end instead would satisfy every column-set
    assertion and give a migrated project a differently shaped table - MT-010's
    ordering invariant, which `schema.py` states in general terms.
    """
    db_path = project_dir_for(source_dir) / "project.db"

    assert _columns(db_path, "chapter") == _CHAPTER_COLUMNS_V4
    assert _columns(db_path, "chapter")[5] == "budget_ceiling_micro_usd"
    assert "budget_ceiling_usd" not in _columns(db_path, "chapter")
    assert _raw(
        db_path,
        "SELECT type FROM pragma_table_info('chapter') WHERE name = ?",
        ("budget_ceiling_micro_usd",),
    ) == [("INTEGER",)]


def test_the_chapter_ddl_is_its_own_string_with_two_callers(fresh: Project) -> None:
    """C-12's extraction, for MT-012 RED-A5's reason: **two** callers build this
    table - a fresh file and the migration - and a migrated table has to be the
    same table as a fresh one. The cheapest way to guarantee that is for there
    to be only one definition of it.
    """
    import mangatl.store.schema as module

    assert module.__all__ == ["CHAPTER_DDL", "DDL", "LLM_CALL_DDL"]
    assert "budget_ceiling_micro_usd" in module.CHAPTER_DDL
    assert "budget_ceiling_usd" not in module.DDL, (
        "the REAL ceiling column is still in the shipped schema; C-12 replaces"
        " it rather than adding beside it"
    )
    assert module.CHAPTER_DDL in module.DDL, (
        "DDL does not contain CHAPTER_DDL verbatim, so a fresh file and the"
        " migration can build two different chapter tables (MT-012 RED-A5)"
    )


# -- the v3 -> v4 migration: the four-part metric ------------------------------


def test_a_version_three_file_is_migrated_to_version_four_when_it_is_opened(
    source_dir: Path,
) -> None:
    """In place, on open, with no separate command - MT-010's precedent, and the
    third time this project has done it."""
    db_path = _build_v3_file(source_dir, ceiling_usd=_V3_CEILING_USD)
    assert _user_version(db_path) == 3
    assert "budget_ceiling_usd" in _columns(db_path, "chapter"), "the v3 fixture is already v4"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 4
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(4,)]
    assert _columns(db_path, "chapter") == _CHAPTER_COLUMNS_V4


def test_the_rebuild_preserves_the_project_on_all_four_counts(source_dir: Path) -> None:
    """**The metric, as the conjunction it has to be.**

    Each of these four alone is green against a database broken in a way the
    others catch, and the module docstring carries the measurements that say so.
    In particular: the row counts below are **identical** under the recipe that
    omits `legacy_alter_table` (recipe C), and `foreign_key_check` below is
    **empty** under the recipe that omits `foreign_keys = OFF` (recipe A, which
    cascades every page and run out of the file). Asserting either on its own is
    asserting nothing.

    This is **DV-2** and the first half of **DV-3**.
    """
    # Metric 4: foreign-key enforcement is back on for the caller that gets the
    # project, which is the session every cascade in `schema.py` depends on -
    # and it is read off the session that **performed** the migration, because
    # that is the only connection whose pragma the restore ever touched. A
    # second `open_project` finds `user_version` already 4, runs no migration,
    # and reports `_connect`'s own `PRAGMA foreign_keys = ON`: vacuously 1 under
    # every recipe, correct and broken alike (R-9).
    # Read through `transaction()` - "reading a pragma inside a transaction
    # returns the true value; only *setting* one there is a no-op" (project.py).
    with _migrating(source_dir) as (project, db_path, before), project.transaction() as cursor:
        pragma = int(cursor.execute("PRAGMA foreign_keys").fetchone()[0])

    # Metric 1: nothing was cascaded away. Recipe A reports 0, 0, 0 here.
    assert _counts(db_path) == before, (
        f"the migration changed the row counts from {before} to {_counts(db_path)};"
        " without `PRAGMA foreign_keys = OFF` the ALTER TABLE repoints every"
        " child at chapter_v3 and the DROP TABLE then cascades the whole project"
        " away - silently, with no error anywhere"
    )
    # Metric 2: every foreign key still resolves. Recipe C reports four
    # violations here and identical row counts above.
    assert _fk_violations(db_path) == [], (
        f"PRAGMA foreign_key_check reports {_fk_violations(db_path)}; without"
        " `PRAGMA legacy_alter_table = ON` the rows survive and every one of"
        " them points at a table that no longer exists"
    )
    # Metric 3: and the *declarations* name the real table, which is the defect
    # itself rather than a symptom of it.
    assert _tables_naming(db_path, "chapter_v3") == [], (
        f"{_tables_naming(db_path, 'chapter_v3')} still declare a foreign key"
        " into chapter_v3, the scratch name the rebuild renamed the old table to"
    )
    assert "chapter_v3" not in [
        str(row[0]) for row in _raw(db_path, "SELECT name FROM sqlite_master")
    ], "the scratch table chapter_v3 was left behind"
    for child in _CHILDREN:
        declaration = str(
            _raw(db_path, "SELECT sql FROM sqlite_master WHERE name = ?", (child,))[0][0]
        )
        assert "chapter_v3" not in declaration, f"{child} still declares {declaration}"
        assert "REFERENCES chapter(id)" in declaration, (
            f"{child} no longer declares a foreign key into chapter: {declaration}"
        )
    # Metric 4, and the restore's placement with it: measured at 0 when the
    # restore runs before `connection.commit()` and at 1 when it runs after.
    assert pragma == 1, (
        "PRAGMA foreign_keys reads 0 on the project open_project returned: the"
        " restore ran before connection.commit() and was a silent no-op, so"
        " MT-007's per-page invalidation is switched off for this whole session"
    )


def test_foreign_key_enforcement_actually_bites_on_a_migrated_project(
    source_dir: Path,
) -> None:
    """The negative control for metric 4, and the reason it is not just a pragma
    read.

    `PRAGMA foreign_keys` reading `1` is a claim about a flag; this is the
    consequence the flag exists for. A child row pointing at a chapter that does
    not exist must be refused, and a cascade must cascade - both are what
    `schema.py` calls load-bearing, and both are invisible in a row count.

    **Driven through `_migrating`, on the session that ran the migration** - the
    same correction R-9 makes to metric 4 itself, and for the same reason. This
    test took a *second* `open_project` until then, and a second connection has
    foreign keys on whatever the migration did or failed to undo, so the control
    was as vacuous as the assertion it was controlling: it bit on the flag
    `_connect` sets rather than on the one `_migrate_to_current` restores.
    """
    with _migrating(source_dir) as (project, _db_path, _before):
        with pytest.raises(sqlite3.IntegrityError), project.transaction() as cursor:
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (9999, "2026-09-21T00:00:00+00:00"),
            )
        # And a legitimate child still inserts, so the assertion above is about
        # the foreign key rather than about the table being unwritable.
        with project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-09-21T00:00:00+00:00"),
            )


def test_the_ceiling_a_version_three_file_held_survives_as_micro_dollars(
    source_dir: Path,
) -> None:
    """The clause that costs a user their budget if it is wrong.

    Dropping `budget_ceiling_usd` without converting what was in it throws the
    ceiling away, and the chapter silently reverts to `DEFAULT_CEILING` - a
    user who set $0.50 gets $2.00 and finds out from their bill.
    `CAST(ROUND(... * 1000000) AS INTEGER)` is MT-012's conversion and its
    reason: the value still *is* a double at that point, and rounding it to the
    nearest micro-dollar is what turns it back into the exact decimal it was
    written from.
    """
    db_path, _ = _migrated(source_dir, ceiling_usd=_V3_CEILING_USD)

    with open_project(project_dir_for(source_dir)) as project:
        assert project.budget_ceiling() == Usd.from_micro(_V4_CEILING_MICRO)

    assert _raw(db_path, "SELECT budget_ceiling_micro_usd FROM chapter") == [(_V4_CEILING_MICRO,)]


def test_a_version_three_file_with_no_ceiling_still_has_none_afterwards(
    source_dir: Path,
) -> None:
    """The **other** half of the conversion, and AC-5's second half at rest.

    A NULL arithmetics to NULL in SQL and stays NULL, which is what AC-5's
    fallback needs. An implementation that coalesced it to 0 would turn every
    existing project into MT-013 AC-7's "refuses everything, forever" - the
    loudest possible way to get this wrong, and one a row count cannot see.
    """
    db_path, _ = _migrated(source_dir, ceiling_usd=None)

    with open_project(project_dir_for(source_dir)) as project:
        assert project.budget_ceiling() is None

    assert _raw(db_path, "SELECT budget_ceiling_micro_usd FROM chapter") == [(None,)]


def test_a_migrated_chapter_table_is_the_same_table_as_a_freshly_created_one(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """MT-012 RED-A5's invariant, applied to `chapter`: a migrated table has the
    same columns, in the same order, with the same types and the same
    nullability as one a fresh file gets.

    Two projects under one `tmp_path`, so nothing about the comparison depends
    on either path.
    """
    migrated_source = tmp_path / "migrated"
    migrated_source.mkdir()
    fresh_source = tmp_path / "fresh"
    fresh_source.mkdir()
    for filename, width, height in _SOURCE_PAGES:
        (migrated_source / filename).write_bytes(png_bytes(width, height))
        (fresh_source / filename).write_bytes(png_bytes(width, height))

    migrated_db, _ = _migrated(migrated_source)
    with create_project(read_chapter(fresh_source), project_dir_for(fresh_source)):
        pass
    fresh_db = project_dir_for(fresh_source) / "project.db"

    shape = "SELECT name, type, \"notnull\", dflt_value FROM pragma_table_info('chapter')"
    assert _raw(migrated_db, shape) == _raw(fresh_db, shape)
    assert _columns(migrated_db, "chapter") == _CHAPTER_COLUMNS_V4


def test_the_migration_leaves_the_tables_it_does_not_rebuild_alone(
    source_dir: Path,
) -> None:
    """A rebuild of `chapter` must not disturb `llm_call`'s append-only
    triggers, `region`'s UNIQUE key or `line`'s cascade.

    Cheap, and it is the assertion that would catch a migration written as
    "drop everything and re-run `DDL`" - which preserves every column, passes
    `foreign_key_check`, and destroys every row in the project.
    """
    db_path = _build_v3_file(source_dir, ceiling_usd=_V3_CEILING_USD)
    before = {
        str(row[0]): str(row[1] or "")
        for row in _raw(db_path, "SELECT name, sql FROM sqlite_master WHERE name != 'chapter'")
    }
    assert "llm_call_no_update" in before, "the v3 fixture has no triggers to preserve"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 4, (
        "no migration ran, so 'the tables it does not rebuild are unchanged' is"
        " a claim about a file nobody opened"
    )
    after = {
        str(row[0]): str(row[1] or "")
        for row in _raw(db_path, "SELECT name, sql FROM sqlite_master WHERE name != 'chapter'")
    }
    assert after == before, (
        "the v4 migration rewrote a table it has no business touching:"
        f" {sorted(set(before) ^ set(after))} differ"
    )
    assert "llm_call_no_update" in after
    assert "llm_call_no_delete" in after


# -- C-10: Project.budget_ceiling ----------------------------------------------


def test_a_fresh_project_reports_no_ceiling_at_all(fresh: Project) -> None:
    """C-10, and MT-005 PO-8: `create_project` has no business inventing a
    ceiling, so the column is NULL and the reader says `None`.

    **`None` and not `DEFAULT_CEILING`**: the store reports what is stored, and
    the default is a *domain* constant. A store that substituted it would put
    half of AC-5 in the layer that cannot import `domain.budget` to spell it.
    """
    assert fresh.budget_ceiling() is None


def test_a_stored_ceiling_comes_back_as_the_exact_micro_dollar_amount(
    fresh: Project,
) -> None:
    """C-10's round trip, over a value that is **not** a dyadic rational.

    $0.27928 cannot be held exactly by an IEEE-754 double, which is the whole of
    MT-012 PO-2. The column is an INTEGER and `Usd.micro()` is the only bridge,
    so this is exact by construction rather than by tolerance - and there is no
    tolerance in the assertion to give it away.
    """
    with fresh.transaction() as cursor:
        cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (279_280,))

    ceiling = fresh.budget_ceiling()

    assert ceiling == Usd.from_micro(279_280)
    assert ceiling is not None
    assert ceiling.micro() == 279_280


def test_a_stored_ceiling_of_zero_comes_back_as_zero_and_not_as_none(
    fresh: Project,
) -> None:
    """The **zero** of zero-one-many, and the boundary C-11's `is None` spelling
    turns on.

    A stored $0.00 is a real ceiling - MT-013 AC-7's "refuses everything,
    forever" - and a reader that collapsed it to `None` would hand the guard
    `DEFAULT_CEILING` and spend $2.00 on a chapter the user had switched off.
    `is not None` before `== Usd.from_micro(0)`, because `None == Usd(...)` is
    merely `False` and would not say which of the two went wrong.
    """
    with fresh.transaction() as cursor:
        cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (0,))

    ceiling = fresh.budget_ceiling()

    assert ceiling is not None, "a stored $0.00 ceiling was reported as no ceiling at all"
    assert ceiling == Usd.from_micro(0)
