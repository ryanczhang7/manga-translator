"""Creating, reopening and resuming a chapter project.

One chapter project is one SQLite file at `<source>.mtproj/project.db`, a
*sibling* of the user's scans and never inside them (`architecture.md` §4/§5,
D7). A 20-page run takes minutes and costs real money, so it has to survive a
crash: that is why the project is a database rather than a JSON sidecar, why
every write goes through `Project.transaction()`, and why each page carries the
sha256 of the file it was read from.

**The source folder is opened for reading and nothing else, for the whole life
of the project** - `refresh_from_source` re-reads it through
`store.intake.read_chapter`, which decodes from bytes already in memory, and no
other function here touches it at all.

Four things here were measured rather than assumed, each because the obvious
implementation is silently wrong:

1. **`PRAGMA foreign_keys = ON` goes immediately after `connect()`.** SQLite's
   default is `0`, and the pragma set *inside* an explicit transaction is a
   silent no-op that reads back `0` (measured: default `0`, inside `BEGIN` `0`,
   before any transaction `1`). Every cascade in `schema.py` depends on it, so
   `_connect` is the only way this module opens a file.
2. **`transaction()` is not reentrant, and the guard is an instance flag.**
   `with conn:` does not nest - the inner block's exit commits, so an outer
   raise leaves the inner writes behind (measured: `rows persisted: [4, 5]`) -
   and `Connection.in_transaction` cannot be the guard because it is `False`
   until the first DML statement inside the block (measured). Without the
   guard, "writes are atomic" quietly means "atomic unless somebody nests".
3. **`transaction()` commits on a clean exit.** A DML statement followed by
   `close()` with no commit persists nothing (measured: `rows persisted: 0`), so
   a forgotten commit loses a stage's work with no error anywhere.
4. **`open_project` reads `PRAGMA user_version` before any `SELECT`.** Reading a
   *column* out of a table whose shape is not yet trusted is the
   "read with the wrong schema" that AC-3 forbids; `user_version` is
   schema-independent. `chapter.schema_version` is written too, for fidelity to
   §4, and is informational.

And two places where the standard library creates a file behind you:
`sqlite3.connect` *creates* a missing database, so `open_project` checks the
path first and raises `FileNotFoundError` rather than reporting a stranger error
later against an empty file it made itself; and `create_project` refuses an
existing `project.db` with `ProjectExists` rather than clobbering a project that
may hold hours of edits.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from mangatl.domain.page import Chapter, Page
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.schema import DDL

__all__ = [
    "PAGE_DONE",
    "PAGE_PENDING",
    "PAGE_STALE",
    "SCHEMA_VERSION",
    "Project",
    "ProjectExists",
    "SchemaTooNew",
    "create_project",
    "open_project",
    "project_dir_for",
]

#: The schema version this code writes and is willing to read. Stored in the
#: file as `PRAGMA user_version`. A *newer* file is refused (`SchemaTooNew`); an
#: older one would be a migration and there are none, so a v1 file opened by v1
#: code is the only case that exists today.
SCHEMA_VERSION: int = 1

#: `page.status` as `create_project` writes it: read, hashed, nothing done yet.
PAGE_PENDING: str = "pending"

#: `page.status` after `refresh_from_source` finds the scan changed or gone. The
#: marker is stored rather than derived so that it survives a reopen - "marked
#: stale" means nothing if the mark lives in memory. MT-006 adds more values,
#: which is why `schema.py` puts no `CHECK` on the column.
PAGE_STALE: str = "stale"

#: `page.status` once every stage of a run has completed for that page. Added by
#: MT-006, which is the case `PAGE_STALE`'s note above anticipated: the column's
#: vocabulary belongs to the store, so a magic `"done"` in an `UPDATE` inside
#: `pipeline` would put half of it somewhere else. Written by the *runner* after
#: a page's stages have all completed (`architecture.md` §5), and read by every
#: stage's `is_done` - which is what makes a killed run resume rather than
#: restart.
PAGE_DONE: str = "done"

_DB_NAME = "project.db"
_PROJECT_SUFFIX = ".mtproj"
_OUTPUT_SUFFIX = "_en"

# `ORDER BY ordinal` is explicit and is not decoration: `create_project` inserts
# pages in ordinal order, so rowid order agrees with ordinal order and a SELECT
# with no ORDER BY looks correct on a freshly created project. It stops looking
# correct the moment anything rewrites an ordinal, and a SELECT without one is
# nondeterministic by contract even when it happens to come back sorted.
_SELECT_PAGES = "SELECT ordinal, filename, width, height, sha256 FROM page ORDER BY ordinal"

_INSERT_CHAPTER = (
    "INSERT INTO chapter (source_dir, output_dir, created_at, schema_version,"
    " budget_ceiling_usd, model_id, rate_table_version)"
    # The three NULLs are named rather than left out of the column list, so that
    # PO-8's decision - MT-012 and MT-013 own these, this story does not invent
    # them - is visible in the statement and not only in a comment.
    " VALUES (?, ?, ?, ?, NULL, NULL, NULL)"
)
# The upsert MT-007 A-11 requires, and the one form of it that is safe. It
# depends on `UNIQUE (page_id, reading_index)` being declared over exactly these
# two columns: `ON CONFLICT (page_id, reading_index)` raises `OperationalError:
# ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint`
# without it (measured by MT-005, including against a key on the wrong columns).
# `INSERT OR REPLACE` is the form that must NOT be used: it deletes the row, and
# the live `ON DELETE CASCADE` takes the region's translated `line` with it.
# `merged_from` is left out of the statement entirely, so a re-detection cannot
# clear a merge MT-008 recorded.
_UPSERT_REGION = (
    "INSERT INTO region (page_id, reading_index, polygon, mask_blob, kind, confidence)"
    " VALUES (?, ?, ?, ?, ?, ?)"
    " ON CONFLICT (page_id, reading_index) DO UPDATE SET"
    " polygon = excluded.polygon, mask_blob = excluded.mask_blob,"
    " kind = excluded.kind, confidence = excluded.confidence"
)
_SELECT_REGIONS = (
    "SELECT region.polygon, region.mask_blob, region.kind, region.confidence"
    " FROM region JOIN page ON page.id = region.page_id"
    " WHERE page.ordinal = ? ORDER BY region.reading_index"
)

_INSERT_PAGE = (
    "INSERT INTO page (chapter_id, ordinal, filename, width, height, sha256, status)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)


class SchemaTooNew(Exception):
    """The project file was written by a newer version of this code.

    Refusing is the cheap failure; reading a newer file with older code is the
    silent-corruption path. The message carries both numbers, found and
    supported, because "too new" alone tells the user nothing to do about it.
    """


class ProjectExists(Exception):
    """A `project.db` is already there, and it may hold hours of edits."""


def project_dir_for(source_dir: Path) -> Path:
    """The project directory for a folder of scans: `<source>.mtproj`.

    A sibling of the source folder, never a child of it (§4: "the input folder
    is the user's scans and the tool does not write there"). `create_project`
    still takes its directory as an argument - the caller chooses, and this is
    what a caller uses to choose correctly.
    """
    return source_dir.with_name(source_dir.name + _PROJECT_SUFFIX)


def create_project(chapter: Chapter, project_dir: Path) -> Project:
    """Write `chapter` into a new `<project_dir>/project.db` and return it open.

    Raises `ProjectExists` if a project file is already there - checked before
    anything is opened or created, so a refused create leaves the existing
    project untouched byte for byte.
    """
    db_path = project_dir / _DB_NAME
    if db_path.exists():
        raise ProjectExists(f"refusing to overwrite an existing project at {db_path}")

    project_dir.mkdir(parents=True, exist_ok=True)
    connection = _connect(db_path)
    connection.executescript(DDL)
    # Not parameterisable: a PRAGMA value cannot be bound. `SCHEMA_VERSION` is
    # this module's own int, formatted as one, so there is nothing to inject.
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION:d}")

    project = Project(connection, chapter)
    with project.transaction() as cursor:
        cursor.execute(
            _INSERT_CHAPTER,
            (
                str(chapter.source_dir),
                str(chapter.source_dir.with_name(chapter.source_dir.name + _OUTPUT_SUFFIX)),
                datetime.now(UTC).isoformat(),
                SCHEMA_VERSION,
            ),
        )
        chapter_id = cursor.lastrowid
        for page in chapter.pages:
            cursor.execute(
                _INSERT_PAGE,
                (
                    chapter_id,
                    page.ordinal,
                    page.filename,
                    page.width,
                    page.height,
                    page.sha256,
                    PAGE_PENDING,
                ),
            )
    return project


def open_project(project_dir: Path) -> Project:
    """Open an existing `<project_dir>/project.db` and return it open.

    Raises `FileNotFoundError` if there is no project file - checked on the path
    rather than discovered from sqlite3, which would *create* the file and fail
    later with the wrong error - and `SchemaTooNew` if the file's version
    exceeds `SCHEMA_VERSION`, before a single `SELECT` is issued against it.
    """
    db_path = project_dir / _DB_NAME
    if not db_path.is_file():
        raise FileNotFoundError(f"no project file at {db_path}")

    connection = _connect(db_path)
    found = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if found > SCHEMA_VERSION:
        # Closed before raising: on Windows an abandoned handle keeps a lock on
        # a file the caller may now want to move out of the way.
        connection.close()
        raise SchemaTooNew(
            f"{db_path} has schema version {found}, but this build supports"
            f" {SCHEMA_VERSION}; upgrade mangatl to open it"
        )
    return Project(connection, _read_chapter(connection))


def _connect(db_path: Path) -> sqlite3.Connection:
    """Connect to `db_path` with foreign-key enforcement actually switched on.

    The only way this module opens a file, so that the pragma cannot be
    forgotten on one path and set on another. Its placement - immediately after
    `connect()`, before any transaction - is the point: set inside an explicit
    transaction the pragma is a silent no-op (measured, reads back `0`), and
    SQLite's default is off, so every cascade in `schema.py` would quietly stop
    cascading while every row count still looked right.
    """
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _read_chapter(connection: sqlite3.Connection) -> Chapter:
    """Rebuild the `Chapter` from the file, reading every field it stores."""
    row = connection.execute("SELECT source_dir FROM chapter").fetchone()
    return Chapter(source_dir=Path(str(row[0])), pages=_read_pages(connection))


def _read_pages(connection: sqlite3.Connection) -> tuple[Page, ...]:
    return tuple(
        Page(
            ordinal=int(ordinal),
            filename=str(filename),
            width=int(width),
            height=int(height),
            sha256=str(sha256),
        )
        for ordinal, filename, width, height, sha256 in connection.execute(_SELECT_PAGES)
    )


class Project:
    """An open chapter project: the connection, and the chapter it holds.

    A context manager whose `__exit__` closes the connection. Closing is
    contract rather than courtesy: an abandoned handle is a file lock on
    Windows, and on any platform it is a commit nobody made.
    """

    def __init__(self, connection: sqlite3.Connection, chapter: Chapter) -> None:
        self._connection = connection
        self._chapter = chapter
        # PO-5's guard. An instance flag rather than `Connection.in_transaction`,
        # which is `False` until the first DML inside the block and so cannot
        # tell "no transaction" from "a transaction that has not written yet".
        self._in_transaction = False

    @property
    def chapter(self) -> Chapter:
        """The chapter this project holds, with `chapter.pages == pages()`.

        A property because `refresh_from_source` re-derives it: a stale scan
        changes a page's stored hash and size, and a `Chapter` still describing
        the old bytes would be a second, disagreeing answer to one question.
        """
        return self._chapter

    def pages(self) -> tuple[Page, ...]:
        """Every page of the chapter, ordered by `ordinal` in SQL.

        A query, not a cached tuple. The distinction is what makes the round
        trip worth asserting: an implementation that answered from memory would
        agree with itself about a field it never actually stored.
        """
        return _read_pages(self._connection)

    def page_status(self, ordinal: int) -> str:
        """`page.status` for one page: `PAGE_PENDING`, `PAGE_STALE` or
        `PAGE_DONE`.

        Progress through a run is the *store's* business, not the domain's - a
        `Page` describes a scan, so it carries no status and this reads it
        separately. Deliberately no branch for an ordinal that does not exist:
        the contract does not say what that would mean, and inventing an answer
        would add a path nothing ever takes.
        """
        row = self._connection.execute(
            "SELECT status FROM page WHERE ordinal = ?", (ordinal,)
        ).fetchone()
        return str(row[0])

    def write_regions(self, page_ordinal: int, regions: Sequence[RawRegion]) -> None:
        """Replace one page's regions with `regions`, in the order handed over.

        A **page-level replace**, not an append (MT-007 amendment A-11), and four
        things about it are load-bearing:

        1. `reading_index` is the region's position in `regions`, 0 upwards.
           Nothing here sorts: reading order is MT-009's and for Japanese it runs
           right to left, so a store that invented one would be inventing the
           wrong one. What arrives is `postprocess`'s emission order.
        2. The write **upserts** on `(page_id, reading_index)` - `ON CONFLICT ...
           DO UPDATE`, never `INSERT OR REPLACE`. MT-005 measured that `OR
           REPLACE` deletes the row and the live `ON DELETE CASCADE` takes its
           `line` with it, so a second run of detection would silently destroy
           every translation on the page with no row count to show it.
        3. Rows at or past `len(regions)` are **deleted**, so a re-run that finds
           fewer regions leaves no stragglers for MT-009 to read.
           `write_regions(n, ())` therefore clears the page, which is the honest
           answer for a page the detector now finds nothing on.
        4. It opens its own `transaction()`, so it is atomic on its own - and
           `transaction()`'s non-reentrancy guard then refuses a caller that had
           already opened one.

        `merged_from` stays NULL: furigana merging is MT-008's. Following
        `page_status`'s precedent, there is deliberately no branch for an ordinal
        that does not exist.
        """
        with self.transaction() as cursor:
            page_id = cursor.execute(
                "SELECT id FROM page WHERE ordinal = ?", (page_ordinal,)
            ).fetchone()[0]
            for reading_index, region in enumerate(regions):
                cursor.execute(
                    _UPSERT_REGION,
                    (
                        page_id,
                        reading_index,
                        json.dumps([list(vertex) for vertex in region.polygon]),
                        region.mask,
                        region.kind,
                        region.confidence,
                    ),
                )
            cursor.execute(
                "DELETE FROM region WHERE page_id = ? AND reading_index >= ?",
                (page_id, len(regions)),
            )

    def read_regions(self, page_ordinal: int) -> tuple[RawRegion, ...]:
        """One page's regions, ordered by `reading_index`; empty if there are
        none.

        `ORDER BY` is explicit for the reason `_SELECT_PAGES` gives: rowid order
        agrees with `reading_index` only until something rewrites a page, and a
        SELECT without one is nondeterministic by contract even when it happens
        to come back sorted.
        """
        return tuple(
            RawRegion(
                polygon=tuple((int(x), int(y)) for x, y in json.loads(str(polygon))),
                mask=bytes(mask_blob),
                confidence=float(confidence),
                kind=cast(Literal["bubble", "box"], str(kind)),
            )
            for polygon, mask_blob, kind, confidence in self._connection.execute(
                _SELECT_REGIONS, (page_ordinal,)
            )
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """One atomic unit of work: commits on a clean exit, rolls back on any
        exception, and lets that exception propagate.

        This is the resume granularity of `architecture.md` §6 - one transaction
        per page per stage, so a crash costs at most one page of one stage and
        at most one page of API spend.

        **Not reentrant**, by `RuntimeError`. `with conn:` does not nest: the
        inner block's exit commits, so an outer raise would leave the inner
        writes behind and "atomic" would hold only until somebody nested two.
        Refusing loudly is one `if`; the alternative is a rollback that
        sometimes is not one. The flag is cleared however the block ends, so a
        refused nesting does not poison the project.

        Usable for reads with no DML at all - reading a pragma inside a
        transaction returns the true value; only *setting* one there is a no-op.
        """
        if self._in_transaction:
            raise RuntimeError(
                "Project.transaction() is not reentrant: a nested transaction"
                " would commit at the inner exit and defeat the outer rollback"
            )
        cursor = self._connection.cursor()
        self._in_transaction = True
        try:
            with self._connection:
                yield cursor
        finally:
            self._in_transaction = False
            cursor.close()

    def refresh_from_source(self) -> tuple[int, ...]:
        """Re-read the source folder and invalidate the pages that changed.

        Returns the stale ordinals, ascending - empty if nothing changed - so a
        caller can report "1 page changed" without re-querying.

        Matching is **by filename, not by ordinal**. A file added to or removed
        from the folder shifts every later ordinal in the fresh read, so ordinal
        matching would compare one page's bytes against another page's row and
        report a chapter's worth of false staleness. A page whose file is gone
        is stale with its stored hash and size left alone, there being nothing
        to update them to; a file in the folder that the project does not know
        is **ignored**, because adding pages to an existing project is out of
        scope and renumbering to absorb it would break the identity MT-004 gave
        every other page.

        Invalidation cascades **down, never up**: the page's row stays, with its
        hash and its dimensions brought up to date (leaving the old size behind
        would be storing a known-wrong value), and `DELETE FROM region` takes
        that page's regions, lines and masks with it by cascade. No other page
        is touched - which is the entire point of storing a per-page hash.

        `NoPagesFound` and `FileNotFoundError` from the re-read propagate:
        repairing a source folder the user emptied is not this function's job.
        """
        # Before the transaction, so a folder the user emptied or deleted fails
        # without a write lock held over the filesystem read.
        fresh = {page.filename: page for page in read_chapter(self._chapter.source_dir).pages}

        stale: list[int] = []
        with self.transaction() as cursor:
            stored = cursor.execute(
                "SELECT id, ordinal, filename, sha256 FROM page ORDER BY ordinal"
            ).fetchall()
            for page_id, ordinal, filename, sha256 in stored:
                current = fresh.get(str(filename))
                if current is not None and current.sha256 == str(sha256):
                    continue
                # Ascending because the SELECT above orders by ordinal.
                stale.append(int(ordinal))
                if current is None:
                    cursor.execute("UPDATE page SET status = ? WHERE id = ?", (PAGE_STALE, page_id))
                else:
                    cursor.execute(
                        "UPDATE page SET sha256 = ?, width = ?, height = ?, status = ?"
                        " WHERE id = ?",
                        (current.sha256, current.width, current.height, PAGE_STALE, page_id),
                    )
                cursor.execute("DELETE FROM region WHERE page_id = ?", (page_id,))

        self._chapter = _read_chapter(self._connection)
        return tuple(stale)

    def __enter__(self) -> Project:
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the connection. Returns `None`, so nothing is ever swallowed."""
        self._connection.close()
