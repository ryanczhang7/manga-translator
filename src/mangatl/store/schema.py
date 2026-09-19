"""The chapter project's SQL schema, as one executable string.

`architecture.md` §4 writes the data model out in full; this is that model in
SQL. All seven tables are created at once - including the ones later stories
fill - because a migration on story three is cheap and a migration on story
fifteen is not (MT-005 `## Context`). Nothing here gives a later stage a reason
to exist: the columns are empty until a stage writes them.

`DDL` is a *schema*, not half of a build procedure: `executescript(DDL)` on a
bare connection creates every table, with no help from `store.project`. That
split is what lets a reader check the shape without running the store, and it
is asserted directly.

**`ON DELETE CASCADE` is load-bearing, not tidiness.** AC-4's per-page
invalidation is one statement - `DELETE FROM region WHERE page_id = ?` - and it
carries the regions' `line` rows away with it only because the cascade is
declared here *and* `PRAGMA foreign_keys` is on. Measured on sqlite 3.53.1:
SQLite's default is `0`, so the pragma is set immediately after every
`connect()` (see `project.py`), and with it off the identical DELETE leaves
every `line` row behind. A cascade that does not cascade is invisible in a row
count of the parent table, which is why the store pins the pragma directly.

**What is deliberately absent:**

- **`PRAGMA user_version` is not in here.** The version is a fact about one
  file, written by `create_project` and read by `open_project` (PO-7); putting
  it in the schema would stamp it onto any connection that merely wants the
  shape, including an in-memory one.
- **No UNIQUE key on `llm_call` or `run`.** §4 calls the ledger append-only: the
  same page retried with the same model and the same token counts is a second
  *bill*, not a duplicate row, and a UNIQUE key here would silently drop it and
  stop the money adding up with no error anywhere. Runs are events for the same
  reason - a resume is a second run of one chapter.
- **No `CHECK` on `page.status`.** The vocabulary is two values today
  (`project.PAGE_PENDING`, `project.PAGE_STALE`) and MT-006 adds more; a CHECK
  here would force exactly the migration this story exists to avoid (PO-2).
- **No foreign key on `glossary.first_seen_page`.** It is a page *ordinal*
  (0-based, MT-004), not a `page.id`, so an FK would reject ordinal 0 outright.

**Nullability is a decision per column, not transcription.** NOT NULL wherever
the story that creates the row knows the value; nullable wherever a later stage
supplies it, because a writer forced to invent a value stores a lie:

- `chapter.budget_ceiling_usd`, `model_id`, `rate_table_version` - MT-012 and
  MT-013 own these; `create_project` has no business inventing them (PO-8).
- `line.final_en` - §4's own rule, "NULL `final_en` means unedited", which is
  what makes "accepted as-is" a query rather than a diff of an event log.
  `edited_at` and `viewed_at` follow: an unedited, unviewed line has no such
  timestamp. `proposed_en` too, because OCR writes `source_ja` before
  translation exists to propose anything.
- `run.ended_at`, `outcome`, `aborted_reason` - a run in flight has not ended.
- `region.merged_from` - most regions have no furigana merged into them (O6).
"""

from __future__ import annotations

__all__ = ["DDL", "LLM_CALL_DDL"]

#: The ledger table and the two triggers that make it append-only, as their own
#: string because **two** callers create it: `DDL` below, for a fresh file, and
#: `store.project._MIGRATE_TO_V3`, which rebuilds it in a version 2 file
#: (MT-012 RED-A5). A migrated table has to be the same table as a fresh one -
#: same columns, in the same order, with the same triggers - and the cheapest
#: way to guarantee that is for there to be only one definition of it.
#:
#: `page_id` deliberately carries no `ON DELETE` action: a bill that disappears
#: when its page row does would make the ledger unauditable, and §4 says
#: append-only. Token counts as well as dollars, because rates change and a
#: ledger of dollars alone cannot be re-priced (§4, S5).
#:
#: **`cost_micro_usd INTEGER`, not `cost_usd REAL`** (MT-012 PO-2). A REAL
#: column is an IEEE-754 double, and AC-3 asks for a chapter total that is the
#: exact sum of its calls: $0.27928 is not a dyadic rational, so a double
#: cannot hold it. Integers sum exactly in SQL, `Usd.micro()` is the only
#: bridge, and `NOT NULL` with no DEFAULT means a row cannot arrive unpriced.
#:
#: **`rate_table_version` carries `DEFAULT ''`** for two reasons, both real: an
#: `INSERT` written before this column existed must keep working, and a row
#: migrated from version 2 genuinely does not know which table priced it.
#: Inventing today's version for it would be a lie in the one column that
#: exists to prevent lies.
#:
#: **The triggers are the whole of AC-4.** "Append-only" enforced by the
#: absence of an update function lasts until the next agent writes one; a
#: `BEFORE UPDATE`/`BEFORE DELETE` trigger survives. Both are needed and so is
#: the unqualified case: SQLite optimises `DELETE FROM llm_call` with no
#: `WHERE` into a truncate that skips row triggers *unless* a delete trigger
#: exists, which is exactly why one does.
LLM_CALL_DDL: str = """
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
"""

#: Every table of `architecture.md` §4, its foreign keys, and the UNIQUE keys
#: `store.project` and the stage writers depend on. Executed with
#: `Connection.executescript`, so statements are separated by semicolons and
#: nothing here is parameterised.
#:
#: Concatenated rather than written as one literal only because `LLM_CALL_DDL`
#: above has a second caller. It is still one string and still the whole
#: schema: `executescript(DDL)` on a bare connection creates every table.
DDL: str = (
    """
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

-- `ordinal` is filename order at intake and never changes: it is the page's
-- identity for the rest of the product (MT-004), which is why it is unique
-- within the chapter rather than merely indexed. `filename` is unique for a
-- second reason: it is how `refresh_from_source` matches a stored page to a
-- freshly read one, and that match must be one-to-one.
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

-- `UNIQUE (page_id, reading_index)` is a schema dependency of the region
-- writer, not only a constraint: the upsert form
-- `INSERT ... ON CONFLICT (page_id, reading_index) DO UPDATE` raises
-- `OperationalError: ON CONFLICT clause does not match any PRIMARY KEY or
-- UNIQUE constraint` unless a unique key covers exactly these columns
-- (measured, including against a key on the wrong columns). A later story that
-- "tidies" this into a plain index breaks the writer, not just the constraint.
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

-- `ocr_empty` is MT-010's column and the reason this schema is at version 2. It
-- means "the model emitted no tokens", NOT "source_ja is empty" (MT-010 C-5):
-- a specials-only decode is a successful read of nothing printable and stores
-- `0` with an empty `source_ja`. NOT NULL keeps it a boolean - a nullable flag
-- has three states and the review screen has two - and `DEFAULT 0` is what lets
-- every `INSERT INTO line (...)` written before this column existed keep
-- working, in `store.project`, in the migration, and in three test suites.
--
-- It is declared **last**, after the nullable translation columns it has
-- nothing to do with, for one reason: `ALTER TABLE ... ADD COLUMN` appends, so
-- this is the only position in which a file created at version 2 and a version
-- 1 file migrated to it have the *same* table, rather than the same columns in
-- a different order (`store.project._migrate_to_current`).
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

-- The ledger, and the triggers that make it append-only: `LLM_CALL_DDL` above.
"""
    + LLM_CALL_DDL
    + """
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
)
