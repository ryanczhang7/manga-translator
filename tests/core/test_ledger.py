"""`mangatl.store.ledger` and the v3 `llm_call` table: the append-only ledger.

Covers **AC-2** (a recorded call carries the run, the page ordinal, the request
id, the model, all four token counts, the cost and the rate-table version),
**AC-3** (a chapter total over twenty calls equal to the exact sum, with no
floating-point tolerance), **AC-4** (a real `UPDATE` and a real `DELETE` against
an existing row fail at the *schema* level), the store half of **AC-5** (nothing
is recorded when pricing raises) and **AC-6** (a resumed chapter's total spans
both runs). The pricing half of AC-1, AC-5 and AC-7 is
`tests/core/test_rates.py`.

It also covers PO-5's schema bump and the **v2 -> v3 migration**, which no
acceptance criterion names but which AC-2, AC-3 and AC-4 are unsatisfiable
without: `SCHEMA_VERSION == 2` has a `REAL` cost, no version column and no
triggers. A v2 file is the case nothing in this repository tests today - the v1
fixture in `test_line_store.py` exercises `_MIGRATE_TO_V2`, and
`_migrate_to_current` runs that statement unconditionally, so a v2 file opened
by a v3 build would hit `duplicate column name: ocr_empty` unless GREEN makes
the migration version-aware. See `## Handoff: RED -> GREEN`, finding F-4.

Four conventions here are inherited from MT-005's, MT-007's and MT-010's suites
because their reasons were measured, not stylistic:

- **The stored rows are observed with a plain `sqlite3` connection.** "A codec
  that is uniformly wrong round-trips through itself perfectly" (`tdd-cycle`),
  so `record_call`'s writes are read back by something that imports nothing from
  `mangatl.store`. That is what makes AC-2 an assertion about *columns* and not
  about a Python attribute, and it is what makes AC-4 an assertion about the
  database rather than about which functions `ledger.py` happens to export.
- **AC-4 executes the real statements.** `## Model guidance` is explicit: "AC-4's
  test attempts a real `UPDATE` against the database and asserts it raises,
  rather than asserting that no update function is exported. Either weaker form
  has failed RED." It comes with a negative control - the same statement shape
  against `page`, which must succeed - because a test that only shows an
  `UPDATE` failing cannot tell an append-only trigger from a read-only file.
- **AC-3 carries no tolerance of any kind.** `chapter_total` sums stored
  integers and a sum of integers is exact, so the assertion is `==` on `Usd`,
  whose `amount` is a `Decimal`. The twenty costs below were chosen so their
  exact decimal sum, $0.27928, is **not representable as an IEEE-754 double**:
  `Decimal(float(Decimal("0.27928")))` is `0.27927999999999997...`. A
  `record_call` that stored `float(record.cost.amount)` into the old `REAL`
  column therefore cannot reach the asserted value (`## Deferred
  verifications`, condition 4).
- **The v2 fixture DDL is a historical artefact.** `_V2_DDL` is `schema.py` as
  it shipped at MT-010, transcribed in RED with its comments dropped, and like
  `test_line_store.py`'s `_V1_DDL` it **must never be updated to track
  `schema.py`**. The day someone "fixes" it to match the current schema is the
  day the migration tests stop testing a migration.

**Timing.** There is no `pytest-timeout` in this project and no per-test
timeout, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. Every test builds a four-page chapter of
tiny PNGs on `tmp_path` and touches at most twenty-one rows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from functools import reduce
from operator import add
from pathlib import Path
from typing import NamedTuple

import pytest

from mangatl.domain.money import Usd
from mangatl.domain.rates import RATE_TABLE_VERSION, UnknownModel, price
from mangatl.domain.translation import TokenUsage
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import chapter_total, record_call, run_total
from mangatl.store.project import (
    SCHEMA_VERSION,
    Project,
    create_project,
    open_project,
    project_dir_for,
)

_PAGE_W, _PAGE_H = 40, 30
_PAGE_FILENAMES = ("p1.png", "p2.png", "p3.png", "p4.png")

_INSERT_RUN = "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)"

#: The v3 column list for `llm_call`, as `## Contract` states it: `cost_usd` is
#: **gone** and two columns arrive. Written out here rather than derived from
#: `schema.py`, because a set derived from the thing under test agrees with it
#: by construction.
_LLM_CALL_COLUMNS_V3 = frozenset(
    {
        "id",
        "run_id",
        "page_id",
        "request_id",
        "model_id",
        "input_tokens",
        "output_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
        "cost_micro_usd",
        "rate_table_version",
        "at",
    }
)


class _Call(NamedTuple):
    """One priced call: what to price, and the micro-dollars it must come to.

    `micro` is **not** recomputed from the rates here. It is read out of RED's
    own out-of-framework run of the `## Contract` arithmetic, recorded in
    `## Handoff: RED -> GREEN`; a test that re-derived the expected value from
    the same formula the implementation uses would agree with any formula.
    """

    model_id: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    micro: int


#: AC-3's twenty calls. Two models, so the total cannot be produced by pricing
#: everything at one rate; eighteen of the twenty have a **fractional** exact
#: cost, so the single end-of-calculation quantisation of PO-4 is exercised
#: twenty times over; and the exact total, $0.27928, is not a dyadic rational.
_TWENTY_CALLS: tuple[_Call, ...] = (
    _Call("claude-opus-5", 1000, 400, 1, 0, 15006),  # exact 15006.25
    _Call("claude-sonnet-5", 1037, 413, 4, 7, 6215),  # exact  6215.40
    _Call("claude-opus-5", 1074, 426, 7, 14, 16071),  # exact 16070.75
    _Call("claude-sonnet-5", 1111, 439, 10, 21, 6641),  # exact  6641.20
    _Call("claude-opus-5", 1148, 452, 13, 28, 17135),  # exact 17135.25
    _Call("claude-sonnet-5", 1185, 465, 16, 35, 7067),  # exact  7067.00
    _Call("claude-opus-5", 1222, 478, 19, 42, 18200),  # exact 18199.75
    _Call("claude-sonnet-5", 1259, 491, 22, 49, 7493),  # exact  7492.80
    _Call("claude-opus-5", 1296, 504, 25, 56, 19264),  # exact 19264.25
    _Call("claude-sonnet-5", 1333, 517, 28, 63, 7919),  # exact  7918.60
    _Call("claude-opus-5", 1370, 530, 31, 70, 20329),  # exact 20328.75
    _Call("claude-sonnet-5", 1407, 543, 34, 77, 8344),  # exact  8344.40
    _Call("claude-opus-5", 1444, 556, 37, 84, 21393),  # exact 21393.25
    _Call("claude-sonnet-5", 1481, 569, 40, 91, 8770),  # exact  8770.20
    _Call("claude-opus-5", 1518, 582, 43, 98, 22458),  # exact 22457.75
    _Call("claude-sonnet-5", 1555, 595, 46, 105, 9196),  # exact  9196.00
    _Call("claude-opus-5", 1592, 608, 49, 112, 23522),  # exact 23522.25
    _Call("claude-sonnet-5", 1629, 621, 52, 119, 9622),  # exact  9621.80
    _Call("claude-opus-5", 1666, 634, 55, 126, 24587),  # exact 24586.75
    _Call("claude-sonnet-5", 1703, 647, 58, 133, 10048),  # exact 10047.60
)

#: The exact sum of the twenty above, in micro-dollars: $0.27928.
_TWENTY_TOTAL_MICRO = 279280

#: The schema **as it shipped at version 2**, transcribed in RED from
#: `src/mangatl/store/schema.py` before this story changed it. Comments are
#: dropped; every statement, column, type, constraint and cascade is
#: byte-faithful to what MT-005 wrote, MT-007 extended with `region.merged_from`
#: and MT-010 extended with `line.ocr_empty`.
#:
#: DO NOT UPDATE THIS WHEN `schema.py` CHANGES, for the reason
#: `test_line_store.py` gives about `_V1_DDL`: a copy that tracks the current
#: schema turns a migration test into a tautology.
_V2_DDL = """
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
    cost_usd           REAL    NOT NULL,
    at                 TEXT    NOT NULL
);

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

#: Two `llm_call` rows a v2 file already holds: `(request_id, cost_usd,
#: expected micro-dollars after the migration)`. Both dollar figures convert
#: without ambiguity - RED checked that `round(float(v) * 1e6)` and
#: `Decimal(str(v)) * 10**6` agree for each - so the assertion is about the
#: migration converting at all, not about how it rounds a hard case.
_V2_LEDGER_ROWS: tuple[tuple[str, float, int], ...] = (
    ("req-v2-a", 0.0123, 12300),
    ("req-v2-b", 0.064875, 64875),
)


# -- helpers -------------------------------------------------------------------


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Run `sql` through a plain `sqlite3` connection that knows nothing of
    `mangatl.store`."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _columns(db_path: Path, table: str) -> list[str]:
    """The table's columns **in declaration order**."""
    return [str(row[1]) for row in _raw(db_path, f"PRAGMA table_info({table})")]


def _user_version(db_path: Path) -> int:
    return int(_raw(db_path, "PRAGMA user_version")[0][0])


def _ledger_rows(db_path: Path) -> int:
    return int(_raw(db_path, "SELECT COUNT(*) FROM llm_call")[0][0])


def _usage(call: _Call) -> TokenUsage:
    """`_Call` as the domain type `price` takes. Keyword arguments, because
    `TokenUsage` orders the two cache counts read-then-write and `_Call`,
    following the `llm_call` column order, writes them write-then-read."""
    return TokenUsage(
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cache_read_tokens=call.cache_read_tokens,
        cache_write_tokens=call.cache_write_tokens,
    )


def _plain_usage() -> TokenUsage:
    """1,000 input and 500 output tokens on opus: 5,000 + 12,500 = 17,500
    micro-dollars. No cache traffic, so the figure is legible in an assertion."""
    return TokenUsage(
        input_tokens=1000, output_tokens=500, cache_read_tokens=0, cache_write_tokens=0
    )


def _freeze_one_call(project: Project, run_id: int) -> None:
    """One recorded call, `req-frozen`, costing 17,500 micro-dollars."""
    record_call(project, run_id, 0, "req-frozen", price("claude-opus-5", _plain_usage()))


def _open_run(project: Project, started_at: str) -> int:
    """A `run` row for the chapter, written the way MT-006's runner writes one.

    Raw SQL rather than `pipeline.runner`: `store` sits below `pipeline` in the
    layers contract, and a store test that reached up into the orchestrator to
    make a fixture would be asserting the wrong thing when it broke.
    """
    with project.transaction() as cursor:
        chapter_id = cursor.execute("SELECT id FROM chapter").fetchone()[0]
        cursor.execute(_INSERT_RUN, (chapter_id, started_at))
        return int(cursor.lastrowid or 0)


def _record(project: Project, run_id: int, ordinal: int, call: _Call) -> Usd:
    """Price `call` and record it against `(run_id, ordinal)`; return its cost."""
    record = price(call.model_id, _usage(call))
    record_call(project, run_id, ordinal, f"req-{run_id}-{ordinal}-{call.micro}", record)
    return record.cost


def _build_v2_file(source_dir: Path) -> Path:
    """A schema-version-2 project file, built with `_V2_DDL` and nothing else.

    No `create_project`, no `Project`, no `schema.DDL` - so the file this
    function produces cannot silently acquire a v3 column when `schema.py`
    changes. It carries a chapter, four pages, one run and the two `llm_call`
    rows of `_V2_LEDGER_ROWS`, because "the costs it already held survive" needs
    money in the table the migration rebuilds.
    """
    project_dir = project_dir_for(source_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V2_DDL)
        connection.execute("PRAGMA user_version = 2")
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version)"
            " VALUES (?, ?, ?, ?)",
            (str(source_dir), str(source_dir) + "_en", "2026-09-15T00:00:00+00:00", 2),
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
        cursor.execute(_INSERT_RUN, (chapter_id, "2026-09-15T00:00:00+00:00"))
        run_id = cursor.lastrowid
        page_id = cursor.execute("SELECT id FROM page WHERE ordinal = 0").fetchone()[0]
        for request_id, cost_usd, _micro in _V2_LEDGER_ROWS:
            cursor.execute(
                "INSERT INTO llm_call (run_id, page_id, request_id, model_id, input_tokens,"
                " output_tokens, cache_write_tokens, cache_read_tokens, cost_usd, at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    page_id,
                    request_id,
                    "claude-opus-5",
                    1000,
                    500,
                    10,
                    20,
                    cost_usd,
                    "2026-09-15T00:00:01+00:00",
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return db_path


# -- fixtures ------------------------------------------------------------------


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    """A four-page chapter, so calls can be spread across page ordinals."""
    folder = tmp_path / "chapter"
    folder.mkdir()
    for index, name in enumerate(_PAGE_FILENAMES):
        (folder / name).write_bytes(png_bytes(_PAGE_W, _PAGE_H, (index * 40, 0, 0)))
    return folder


@pytest.fixture
def project(source_dir: Path) -> Iterator[Project]:
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as opened:
        yield opened


@pytest.fixture
def db_path(source_dir: Path) -> Path:
    return project_dir_for(source_dir) / "project.db"


@pytest.fixture
def run_id(project: Project) -> int:
    return _open_run(project, "2026-09-18T09:00:00+00:00")


# -- PO-5: the schema this story requires --------------------------------------


def test_this_build_writes_and_reads_schema_version_four(project: Project, db_path: Path) -> None:
    """PO-5's bump, stated once, where a reader looks for it.

    AC-2 (a version per row), AC-3 (no float on disk) and AC-4 (a trigger) are
    all unsatisfiable against version 2, so the number moving is the story.
    Both records of it, because MT-005 PO-7 required both and a migration that
    updated one of them is a file that disagrees with itself.

    **MT-044 C-12 takes it to 4** - `chapter.budget_ceiling_usd REAL` becomes
    `budget_ceiling_micro_usd INTEGER`, because AC-5 reads a ceiling out of the
    chapter row and MT-012 PO-2 already settled that money on disk is an
    integer count of micro-dollars.
    """
    assert SCHEMA_VERSION == 4
    assert _user_version(db_path) == 4
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(4,)]


def test_the_ledger_stores_integer_micro_dollars_and_carries_no_real_cost_column(
    project: Project, db_path: Path
) -> None:
    """PO-2: the float to remove is the one in SQLite.

    `cost_usd REAL` is an IEEE-754 double and it is where AC-3's drift would
    actually come from. Asserted as an absence as well as a presence, because
    a schema that grew `cost_micro_usd` beside `cost_usd` would satisfy every
    other assertion in this file while still holding the float.
    """
    columns = _columns(db_path, "llm_call")

    assert "cost_usd" not in columns, f"the REAL cost column is still there: {columns}"
    assert set(columns) == _LLM_CALL_COLUMNS_V3, f"llm_call has {sorted(columns)}"

    declared = {str(row[1]): row for row in _raw(db_path, "PRAGMA table_info(llm_call)")}
    _cid, _name, cost_type, cost_notnull, _default, _pk = declared["cost_micro_usd"]
    assert str(cost_type).upper() == "INTEGER", f"cost_micro_usd is {cost_type}"
    assert int(cost_notnull) == 1, "cost_micro_usd is nullable, so a call can have no price"


def test_the_rate_table_version_column_is_not_null_and_defaults_to_the_empty_string(
    project: Project, db_path: Path
) -> None:
    """`## Callers of changed signatures`, trap 2. The `DEFAULT ''` is not
    decoration: `test_project.py`'s frozen `_INSERT_LLM_CALL` does not supply
    this column, and without a default it would fail `NOT NULL` and take an
    unrelated MT-005 test down with it."""
    declared = {str(row[1]): row for row in _raw(db_path, "PRAGMA table_info(llm_call)")}

    assert "rate_table_version" in declared, f"llm_call has {sorted(declared)}"
    _cid, _name, declared_type, notnull, default, _pk = declared["rate_table_version"]
    assert str(declared_type).upper() == "TEXT"
    assert int(notnull) == 1, "rate_table_version is nullable, so a row can decline to say"
    assert str(default) == "''", f"the default is {default!r}"


# -- AC-2: what one recorded call carries --------------------------------------


def test_a_recorded_call_carries_the_run_page_request_model_counts_cost_and_version(
    project: Project, db_path: Path, run_id: int
) -> None:
    """AC-2, every clause of it, read back through a plain sqlite connection.

    The **page ordinal** is asserted through a join to `page`, not by reading
    `llm_call.page_id` and hoping: `record_call` takes an ordinal and the column
    is a foreign key to `page.id`, so an implementation that stored the ordinal
    straight into `page_id` would agree with itself and point at the wrong page
    on every chapter whose first page id is not 0.
    """
    record = price(
        "claude-opus-5",
        TokenUsage(
            input_tokens=3600, output_tokens=1500, cache_read_tokens=0, cache_write_tokens=1500
        ),
    )

    record_call(project, run_id, 2, "req-ac2", record)

    rows = _raw(
        db_path,
        "SELECT llm_call.run_id, page.ordinal, llm_call.request_id, llm_call.model_id,"
        " llm_call.input_tokens, llm_call.output_tokens, llm_call.cache_write_tokens,"
        " llm_call.cache_read_tokens, llm_call.cost_micro_usd, llm_call.rate_table_version"
        " FROM llm_call JOIN page ON page.id = llm_call.page_id",
    )

    assert rows == [
        (run_id, 2, "req-ac2", "claude-opus-5", 3600, 1500, 1500, 0, 64875, RATE_TABLE_VERSION)
    ]


def test_a_recorded_call_is_stamped_with_the_time_it_was_recorded(
    project: Project, db_path: Path, run_id: int
) -> None:
    """`llm_call.at` is `NOT NULL` and `record_call` takes no timestamp, so it
    stamps one. An ISO-8601 instant **with an offset**, the same shape
    `create_project` and `pipeline.runner` write, because a naive local
    timestamp in a ledger cannot be ordered against one from another machine."""
    before = datetime.now(UTC)

    record_call(project, run_id, 0, "req-at", price("claude-opus-5", _plain_usage()))

    after = datetime.now(UTC)
    stamped = datetime.fromisoformat(str(_raw(db_path, "SELECT at FROM llm_call")[0][0]))
    assert stamped.tzinfo is not None, f"{stamped!r} has no offset"
    assert before <= stamped <= after


def test_a_second_identical_call_is_a_second_bill_rather_than_a_duplicate(
    project: Project, db_path: Path, run_id: int
) -> None:
    """`schema.py`: "the same page retried with the same model and the same
    token counts is a second *bill*, not a duplicate row". The v2 table carried
    no UNIQUE key for that reason and the v3 one must not acquire one - a
    rebuild-style migration is exactly where one would arrive by accident."""
    record = price("claude-opus-5", _plain_usage())
    for _ in range(2):
        record_call(project, run_id, 0, "req-identical", record)

    assert _ledger_rows(db_path) == 2
    assert chapter_total(project) == Usd.from_micro(2 * record.cost.micro())


# -- AC-3: twenty calls, summed exactly ----------------------------------------


def test_the_chapter_total_over_twenty_calls_is_the_exact_sum_of_their_costs(
    project: Project, db_path: Path, run_id: int
) -> None:
    """AC-3, with no tolerance of any kind.

    Three assertions, and each catches something the others do not: the total
    against the folded sum of the individual `Usd` values (a total that
    re-derived the price from the rates would agree with itself); the total
    against the pinned integer 279,280 (a fold that was wrong in the same way
    as the store would agree with itself); and the total's `Decimal` against
    `Decimal("0.27928")` exactly, which is the assertion a `REAL` column cannot
    satisfy, because `Decimal(float(Decimal("0.27928")))` is
    `0.27927999999999997...` and `Usd` compares its `Decimal` exactly.
    """
    costs = [
        _record(project, run_id, index % len(_PAGE_FILENAMES), call)
        for index, call in enumerate(_TWENTY_CALLS)
    ]

    assert _ledger_rows(db_path) == 20
    assert [cost.micro() for cost in costs] == [call.micro for call in _TWENTY_CALLS]

    total = chapter_total(project)
    assert total == reduce(add, costs)
    assert total.micro() == _TWENTY_TOTAL_MICRO
    assert total.amount == Decimal("0.27928")
    assert total == Usd(Decimal("0.27928"))


def test_an_empty_ledger_totals_zero_rather_than_raising(project: Project, run_id: int) -> None:
    """The zero end of zero/one/many. A chapter that has not called the model
    has spent nothing, and `SUM()` over no rows is SQL NULL - which is the one
    place this returns `None` instead of a `Usd` if nobody thought about it."""
    assert chapter_total(project) == Usd(Decimal(0))
    assert run_total(project, run_id) == Usd(Decimal(0))


def test_a_ledger_of_one_call_totals_that_call(project: Project, run_id: int) -> None:
    """The one end of zero/one/many, and the cheapest guard against a
    `chapter_total` that divides, averages or drops the first row."""
    cost = _record(project, run_id, 0, _TWENTY_CALLS[0])

    assert chapter_total(project) == cost
    assert chapter_total(project).micro() == 15006


# -- AC-4: the ledger is append-only at the schema level -----------------------


def test_updating_an_existing_ledger_row_is_refused_by_the_database(
    project: Project, db_path: Path, run_id: int
) -> None:
    """AC-4's first half, as a real `UPDATE` through a connection that has never
    heard of `mangatl.store`.

    Asserting that `ledger.py` exports no update function is the weaker form and
    `## Model guidance` rules it out: a trigger survives the next agent, an
    absent function does not.
    """
    _freeze_one_call(project, run_id)

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _raw(
            db_path,
            "UPDATE llm_call SET cost_micro_usd = 1 WHERE request_id = ?",
            ("req-frozen",),
        )

    assert "append-only" in str(excinfo.value), str(excinfo.value)
    assert _raw(db_path, "SELECT cost_micro_usd FROM llm_call") == [(17500,)]


def test_deleting_an_existing_ledger_row_is_refused_by_the_database(
    project: Project, db_path: Path, run_id: int
) -> None:
    """AC-4's second half. A run's spend cannot be quietly rewritten, and
    "quietly" includes rewriting it to nothing."""
    _freeze_one_call(project, run_id)

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _raw(db_path, "DELETE FROM llm_call WHERE request_id = ?", ("req-frozen",))

    assert "append-only" in str(excinfo.value), str(excinfo.value)
    assert _ledger_rows(db_path) == 1


def test_a_blanket_delete_of_the_whole_ledger_is_refused_too(
    project: Project, db_path: Path, run_id: int
) -> None:
    """`DELETE FROM llm_call` with no `WHERE`. SQLite optimises an unqualified
    delete into a truncate that skips row triggers unless one exists, so this is
    a genuinely different statement from the one above and not a restatement of
    it."""
    _freeze_one_call(project, run_id)

    with pytest.raises(sqlite3.IntegrityError):
        _raw(db_path, "DELETE FROM llm_call")

    assert _ledger_rows(db_path) == 1


def test_the_same_statements_against_another_table_still_succeed(
    project: Project, db_path: Path
) -> None:
    """AC-4's **negative control**, and without it the three tests above prove
    only that *something* refuses an `UPDATE`.

    A read-only file, a locked database or a blanket trigger on every table
    would make them all pass. `page` is a table the product updates constantly -
    `refresh_from_source` marks pages stale - so an `UPDATE` and a `DELETE`
    against it must go through untouched. What AC-4 claims is that the ledger
    specifically is append-only, and that is a difference between two tables.
    """
    _raw(db_path, "UPDATE page SET status = 'stale' WHERE ordinal = 0")
    assert _raw(db_path, "SELECT status FROM page WHERE ordinal = 0") == [("stale",)]

    _raw(db_path, "DELETE FROM page WHERE ordinal = 3")
    assert _raw(db_path, "SELECT COUNT(*) FROM page") == [(3,)]


# -- AC-5's store half: a refusal records nothing ------------------------------


def test_a_call_whose_model_is_not_in_the_rate_table_leaves_the_ledger_untouched(
    project: Project, db_path: Path, run_id: int
) -> None:
    """AC-5's second clause: "and nothing is recorded".

    The whole point of the criterion is that the failure is *loud and empty*
    rather than quiet and zero-priced, so the row count is asserted on both
    sides of the refusal. One row is recorded first, so "unchanged" is a real
    number rather than zero - a `record_call` that wiped the table on the way to
    raising would pass an assertion against an empty ledger.
    """
    record_call(project, run_id, 0, "req-good", price("claude-opus-5", _plain_usage()))
    before = _ledger_rows(db_path)
    total_before = chapter_total(project)

    with pytest.raises(UnknownModel) as excinfo:
        record_call(
            project,
            run_id,
            1,
            "req-unknown",
            price("claude-haiku-9", _plain_usage()),
        )

    assert "claude-haiku-9" in str(excinfo.value)
    assert _ledger_rows(db_path) == before == 1
    assert chapter_total(project) == total_before


# -- AC-6: a resumed chapter totals across both runs ---------------------------


def test_a_resumed_chapters_total_includes_the_calls_of_both_runs(
    project: Project, db_path: Path
) -> None:
    """AC-6. A resume is a second `run` row against one chapter
    (`schema.py`: "runs are events"), and the chapter total is the question the
    $2 ceiling is actually about.

    The last two assertions are what stop a `chapter_total` that filters by the
    newest run id from passing: the two run totals are deliberately unequal and
    both non-zero, so the chapter total differs from either of them.
    """
    first = _open_run(project, "2026-09-18T09:00:00+00:00")
    first_costs = [_record(project, first, index, _TWENTY_CALLS[index]) for index in range(2)]

    second = _open_run(project, "2026-09-18T11:00:00+00:00")
    second_costs = [
        _record(project, second, index % len(_PAGE_FILENAMES), _TWENTY_CALLS[index])
        for index in range(2, 5)
    ]

    assert _ledger_rows(db_path) == 5
    assert run_total(project, first) == reduce(add, first_costs)
    assert run_total(project, first).micro() == 21221
    assert run_total(project, second) == reduce(add, second_costs)
    assert run_total(project, second).micro() == 39847

    total = chapter_total(project)
    assert total.micro() == 61068
    assert total == reduce(add, first_costs + second_costs)
    assert total != run_total(project, second), "the total is only the current run's"
    assert total != run_total(project, first), "the total is only the first run's"


# -- PO-5: a version-2 file on disk still opens --------------------------------


def test_a_version_two_file_is_migrated_to_version_four_when_it_is_opened(
    source_dir: Path,
) -> None:
    """In place, on open, with no separate command - MT-010's precedent.

    This is the case nothing in the repository covers today: `_migrate_to_current`
    runs `_MIGRATE_TO_V2` unconditionally, so a v2 file opened by a v3 build
    fails with `duplicate column name: ocr_empty` unless the migration becomes
    version-aware. The v1 fixture in `test_line_store.py` cannot catch it,
    because a v1 file legitimately needs that statement.

    **MT-044 C-12 makes this a two-step chain again** - a v2 file now runs the
    v3 step *and* the v4 step in one open - so `SCHEMA_VERSION` is the oracle
    rather than a literal 3. The v2 fixture below is a historical artefact and
    is deliberately **not** updated: the day someone "fixes" it to track
    `schema.py` is the day this stops testing a migration.
    """
    db_path = _build_v2_file(source_dir)
    assert _user_version(db_path) == 2
    assert "cost_usd" in _columns(db_path, "llm_call"), "the v2 fixture is already v3"

    with open_project(project_dir_for(source_dir)):
        pass

    assert _user_version(db_path) == 4
    assert _raw(db_path, "SELECT schema_version FROM chapter") == [(4,)]
    assert set(_columns(db_path, "llm_call")) == _LLM_CALL_COLUMNS_V3
    # The v4 step rebuilds `chapter`, not `llm_call`. A v2 file's ledger rows
    # must survive the *second* rebuild untouched, and the two tests below say
    # so about their contents; this says so about the table's shape.
    assert _ledger_rows(db_path) == len(_V2_LEDGER_ROWS)


def test_the_costs_a_version_two_file_already_held_survive_as_micro_dollars(
    source_dir: Path,
) -> None:
    """The clause that costs a user their audit trail if it is wrong.

    Dropping `cost_usd` without converting what was in it throws away every
    dollar figure the ledger held, and §4 calls this table append-only. The two
    stored floats convert to 12,300 and 64,875 micro-dollars. `rate_table_version`
    reads back as the empty string its `DEFAULT` supplies: a v2 row genuinely
    does not know which table priced it, and inventing today's version for it
    would be a lie in the one column that exists to prevent lies.
    """
    db_path = _build_v2_file(source_dir)

    with open_project(project_dir_for(source_dir)):
        pass

    assert _raw(
        db_path,
        "SELECT request_id, cost_micro_usd, rate_table_version FROM llm_call ORDER BY id",
    ) == [(request_id, micro, "") for request_id, _cost, micro in _V2_LEDGER_ROWS]


def test_a_migrated_file_is_append_only_too(source_dir: Path) -> None:
    """A migration that adds the columns and forgets the triggers leaves AC-4
    false for every project a user already has, and nothing else in this file
    would notice: a fresh v3 file gets its triggers from `DDL`."""
    db_path = _build_v2_file(source_dir)

    with open_project(project_dir_for(source_dir)):
        pass

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _raw(db_path, "UPDATE llm_call SET cost_micro_usd = 1")
    assert "append-only" in str(excinfo.value), str(excinfo.value)

    with pytest.raises(sqlite3.IntegrityError):
        _raw(db_path, "DELETE FROM llm_call")
    assert _ledger_rows(db_path) == len(_V2_LEDGER_ROWS)


def test_a_migrated_ledger_has_the_columns_in_the_same_order_as_a_fresh_one(
    tmp_path: Path, png_bytes: Callable[..., bytes], source_dir: Path
) -> None:
    """MT-010's invariant, applied to `llm_call`.

    `schema.py` declares `line.ocr_empty` last *because* `ALTER TABLE ... ADD
    COLUMN` appends, "so this is the only position in which a file created at
    version 2 and a version 1 file migrated to it have the same table, rather
    than the same columns in a different order". The same has to hold here, or
    a `SELECT *` and every positional row unpack behaves differently on a
    migrated project than on a new one.
    """
    migrated = _build_v2_file(source_dir)
    with open_project(project_dir_for(source_dir)):
        pass

    fresh_source = tmp_path / "fresh"
    fresh_source.mkdir()
    for index, name in enumerate(_PAGE_FILENAMES):
        (fresh_source / name).write_bytes(png_bytes(_PAGE_W, _PAGE_H, (index * 40, 0, 0)))
    with create_project(read_chapter(fresh_source), project_dir_for(fresh_source)):
        pass
    fresh = project_dir_for(fresh_source) / "project.db"

    assert _columns(migrated, "llm_call") == _columns(fresh, "llm_call")


def test_a_migrated_file_records_and_totals_a_new_call(source_dir: Path) -> None:
    """The round trip through a migrated file, which is the only thing that
    proves the rebuilt table is still writable and still summable. A migration
    that produced a table with the right columns and a broken foreign key would
    pass every assertion above."""
    _build_v2_file(source_dir)

    with open_project(project_dir_for(source_dir)) as project:
        run = _open_run(project, "2026-09-18T12:00:00+00:00")
        cost = _record(project, run, 0, _TWENTY_CALLS[0])

        assert run_total(project, run) == cost
        assert chapter_total(project).micro() == 12300 + 64875 + 15006
