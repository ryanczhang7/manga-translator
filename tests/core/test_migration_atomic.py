"""MT-157: an interrupted schema upgrade leaves the project file as it was.

`open_project` upgrades an older file in place through `_migrate_to_current`.
Before this story every statement of every step autocommitted, so a failure part
way through the chain left the file half-upgraded at its old `user_version`: a
rebuild interrupted after its copy kept its aside table (and every later open
died on the rename), and a file more than one version behind kept the earlier
steps' `ADD COLUMN`s (and the next open died on `duplicate column name`). The
story makes the whole chain one transaction, rolled back, closed and re-raised
on failure.

**The seam (`## Contract`).** A step is interrupted by monkeypatching the
module-level `project._MIGRATIONS` with one rebuild's script altered:
`INSERT INTO __interrupted__ VALUES (1);` inserted immediately before its
`DROP TABLE <aside>;`, so the rename, the create and the copy have run and the
drop has not. `__interrupted__` is a table no schema has, so the statement
raises `OperationalError: no such table: __interrupted__`. **Every test asserts
its replace changed the script** - a `str.replace` that matches nothing
interrupts nothing, and the test would then pass against any code.

**Builders are imported, not moved** (`## Contract`, "Builders"): each per-version
suite's own `_build_vN_file`, fed that suite's own page set, so the files here
are exactly the ones those suites migrate.

**"An identical file" (AC-2) is a byte copy** of the built file, taken before the
interrupted open, rather than a second build: a byte copy cannot differ in a
timestamp or a source path, so any difference after the two upgrades is the
migration's.

**Timing.** No `pytest-timeout` in this project; each test builds one chapter of
at most four tiny PNGs on `tmp_path` and opens it once or twice.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_ledger import _PAGE_FILENAMES, _build_v2_file
from test_schema_v4 import _SOURCE_PAGES as _V4_PAGES
from test_schema_v4 import _build_v3_file
from test_schema_v10 import _SOURCE_PAGES as _V10_PAGES
from test_schema_v10 import _build_v9_file
from test_schema_v11 import _SOURCE_PAGES as _V11_PAGES
from test_schema_v11 import _build_v10_file
from test_schema_v12 import _SOURCE_PAGES as _V12_PAGES
from test_schema_v12 import _build_v11_file
from test_schema_v13 import _SOURCE_PAGES as _V13_PAGES
from test_schema_v13 import _build_v12_file

from mangatl.store import project
from mangatl.store.project import SCHEMA_VERSION, open_project

#: The statement the tests inject, and the table it names. No schema has it.
_INTERRUPT = "INSERT INTO __interrupted__ VALUES (1);"
_NEEDLE = "__interrupted__"

#: v2 pages, as `test_schema_v10.py` builds them for `_build_v2_file`.
_V2_PAGES: tuple[tuple[str, int, int], ...] = tuple((name, 40, 30) for name in _PAGE_FILENAMES)


@dataclass(frozen=True)
class _Rebuild:
    """One of the five table rebuilds, and the file just before it."""

    found: int  # the version of the file built
    step: int  # the `_MIGRATIONS` key of the rebuild it reaches first
    aside: str  # the table the rebuild renames aside and then drops
    copied: str  # the table the rebuild copies, which must hold a row
    pages: tuple[tuple[str, int, int], ...]
    build: Callable[[Path], Path]

    @property
    def id(self) -> str:
        return f"v{self.found}-to-v{self.step}-{self.aside}"


def _build_v3(source_dir: Path) -> Path:
    return _build_v3_file(source_dir, ceiling_usd=1.25)


_REBUILDS: tuple[_Rebuild, ...] = (
    _Rebuild(2, 3, "llm_call_v2", "llm_call", _V2_PAGES, _build_v2_file),
    _Rebuild(3, 4, "chapter_v3", "chapter", _V4_PAGES, _build_v3),
    _Rebuild(9, 10, "llm_call_v9", "llm_call", _V10_PAGES, _build_v9_file),
    _Rebuild(10, 11, "batch_job_v10", "batch_job", _V11_PAGES, _build_v10_file),
    _Rebuild(12, 13, "region_v12", "region", _V13_PAGES, _build_v12_file),
)

#: AC-3's file: version 11, interrupted in the v12 -> v13 rebuild, so
#: `_MIGRATE_TO_V12`'s `ADD COLUMN` has run in the same open before the failure.
_V11_INTO_V13 = _Rebuild(11, 13, "region_v12", "region", _V12_PAGES, _build_v11_file)

_rebuilds = pytest.mark.parametrize("rebuild", _REBUILDS, ids=[r.id for r in _REBUILDS])


# -- helpers -------------------------------------------------------------------


def _sources(tmp_path: Path, png_bytes: Callable[..., bytes], rebuild: _Rebuild) -> Path:
    directory = tmp_path / "scans"
    directory.mkdir()
    for filename, width, height in rebuild.pages:
        (directory / filename).write_bytes(png_bytes(width, height))
    return directory


def _built(tmp_path: Path, png_bytes: Callable[..., bytes], rebuild: _Rebuild) -> Path:
    """The file `rebuild` starts from, checked to be what the test needs."""
    db_path = rebuild.build(_sources(tmp_path, png_bytes, rebuild))
    assert _user_version(db_path) == rebuild.found, "the builder built the wrong version"
    rows = _raw(db_path, f'SELECT COUNT(*) FROM "{rebuild.copied}"')[0][0]
    assert isinstance(rows, int)
    assert rows > 0, (
        f"the v{rebuild.found} fixture's {rebuild.copied} is empty: the rebuild has"
        " nothing to copy, so interrupting it after the copy checks nothing"
    )
    return db_path


def _twin(db_path: Path, tmp_path: Path) -> Path:
    """A byte copy of `db_path` in a project directory of its own."""
    twin_dir = tmp_path / "twin.mtproj"
    twin_dir.mkdir()
    shutil.copyfile(db_path, twin_dir / db_path.name)
    return twin_dir / db_path.name


def _raw(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    """`sql` against `db_path` through plain `sqlite3`, with nothing of `project`."""
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute(sql).fetchall()


def _user_version(db_path: Path) -> int:
    version = _raw(db_path, "PRAGMA user_version")[0][0]
    assert isinstance(version, int)
    return version


def _tables(db_path: Path) -> list[str]:
    return [
        str(name)
        for (name,) in _raw(db_path, "SELECT name FROM sqlite_master WHERE type = 'table'")
    ]


def _columns(db_path: Path, table: str) -> list[str]:
    return [str(row[1]) for row in _raw(db_path, f'PRAGMA table_info("{table}")')]


def _snapshot(db_path: Path) -> dict[str, object]:
    """Everything AC-1 says must be unchanged: version, declarations, rows."""
    return {
        "user_version": _user_version(db_path),
        "sqlite_master": _raw(
            db_path, "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ),
        "rows": {
            table: _raw(db_path, f'SELECT * FROM "{table}" ORDER BY rowid')
            for table in sorted(_tables(db_path))
        },
    }


def _interrupt(monkeypatch: pytest.MonkeyPatch, step: int, aside: str) -> None:
    """Patch `project._MIGRATIONS` so step `step` fails just before its drop.

    The asserts are the needle rule: the altered script must differ from the
    original, and the injected statement must appear in it exactly once.
    """
    drop = f"DROP TABLE {aside};"
    original = dict(project._MIGRATIONS)[step]
    assert original.count(drop) == 1, f"step {step} no longer carries {drop!r} exactly once"
    altered = original.replace(drop, f"{_INTERRUPT}\n{drop}")
    assert altered != original, f"the replace changed nothing in step {step}"
    assert altered.count(_NEEDLE) == 1, f"{_NEEDLE} is not in step {step} exactly once"
    patched = tuple(
        (version, altered if version == step else script) for version, script in project._MIGRATIONS
    )
    assert sum(script.count(_NEEDLE) for _, script in patched) == 1
    monkeypatch.setattr(project, "_MIGRATIONS", patched)


def _expected_error() -> sqlite3.OperationalError:
    """What the injected statement raises on its own, measured, not transcribed."""
    with closing(sqlite3.connect(":memory:")) as connection:
        try:
            connection.execute(_INTERRUPT)
        except sqlite3.OperationalError as error:
            return error
    raise AssertionError(f"{_INTERRUPT!r} did not raise on an empty database")


def _fail_open(db_path: Path) -> pytest.ExceptionInfo[sqlite3.OperationalError]:
    """`open_project` on the interrupted chain; it must raise."""
    with pytest.raises(sqlite3.OperationalError) as excinfo:
        open_project(db_path.parent).__exit__(None, None, None)
    return excinfo


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[sqlite3.Connection]]:
    """Every connection `project._connect` hands out, in order."""
    seen: list[sqlite3.Connection] = []
    real = project._connect

    def recording(db_path: Path) -> sqlite3.Connection:
        connection = real(db_path)
        seen.append(connection)
        return connection

    monkeypatch.setattr(project, "_connect", recording)
    yield seen


# -- AC-1: an interrupted rebuild leaves the file exactly as it was ------------


@_rebuilds
def test_an_upgrade_interrupted_before_the_aside_drop_leaves_the_file_as_it_was(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    rebuild: _Rebuild,
) -> None:
    db_path = _built(tmp_path, png_bytes, rebuild)
    before = _snapshot(db_path)
    _interrupt(monkeypatch, rebuild.step, rebuild.aside)

    excinfo = _fail_open(db_path)

    assert rebuild.aside not in _tables(db_path), (
        f"the interrupted v{rebuild.step} rebuild left its aside table {rebuild.aside}"
        " in the file: the upgrade committed part way"
    )
    after = _snapshot(db_path)
    assert after["user_version"] == before["user_version"]
    assert after["sqlite_master"] == before["sqlite_master"], (
        "the file's declarations changed although the upgrade failed"
    )
    assert after["rows"] == before["rows"], "the file's rows changed although the upgrade failed"
    del excinfo


# -- AC-2: the file left by the failure then upgrades as if nothing happened ---


@_rebuilds
def test_a_file_left_by_an_interrupted_upgrade_opens_next_time_as_an_uninterrupted_one_does(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    rebuild: _Rebuild,
) -> None:
    db_path = _built(tmp_path, png_bytes, rebuild)
    twin = _twin(db_path, tmp_path)
    _interrupt(monkeypatch, rebuild.step, rebuild.aside)
    excinfo = _fail_open(db_path)
    del excinfo
    monkeypatch.undo()

    with open_project(db_path.parent):
        pass
    with open_project(twin.parent):
        pass

    assert _user_version(db_path) == SCHEMA_VERSION
    assert _snapshot(db_path) == _snapshot(twin), (
        "after the failed upgrade, the next upgrade produced a different file from an"
        " uninterrupted upgrade of the identical file"
    )


# -- AC-3: the whole chain is the unit, not each rebuild -----------------------


def test_a_v11_file_failing_in_the_v13_rebuild_keeps_no_v12_column_and_opens_next_time(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rebuild = _V11_INTO_V13
    db_path = _built(tmp_path, png_bytes, rebuild)
    assert "consistency_run_id" not in _columns(db_path, "chapter"), "the v11 fixture is v12"
    before = _snapshot(db_path)
    _interrupt(monkeypatch, rebuild.step, rebuild.aside)

    excinfo = _fail_open(db_path)
    del excinfo

    assert _user_version(db_path) == 11
    assert "consistency_run_id" not in _columns(db_path, "chapter"), (
        "the v12 step's ADD COLUMN committed although the v13 step after it failed:"
        " the next open re-runs it at version 11 and dies on `duplicate column name`"
    )
    assert _snapshot(db_path) == before

    monkeypatch.undo()
    with open_project(db_path.parent):
        pass
    assert _user_version(db_path) == SCHEMA_VERSION


# -- AC-4: the original exception, and the handle released ---------------------


@_rebuilds
def test_a_failed_upgrade_raises_the_failing_statements_own_error(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    rebuild: _Rebuild,
) -> None:
    db_path = _built(tmp_path, png_bytes, rebuild)
    expected = _expected_error()
    _interrupt(monkeypatch, rebuild.step, rebuild.aside)

    excinfo = _fail_open(db_path)

    assert type(excinfo.value) is type(expected), "the failure was wrapped or replaced"
    assert str(excinfo.value) == str(expected)


@_rebuilds
def test_a_failed_upgrade_releases_the_project_file_so_it_can_be_renamed(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    connections: list[sqlite3.Connection],
    rebuild: _Rebuild,
) -> None:
    db_path = _built(tmp_path, png_bytes, rebuild)
    _interrupt(monkeypatch, rebuild.step, rebuild.aside)

    # Held, not discarded: a caller that keeps the exception (a log handler, a
    # dialog) keeps its traceback, and the handle must not live on in it.
    excinfo = _fail_open(db_path)

    moved = db_path.with_name("moved.db")
    try:
        os.rename(db_path, moved)
    except PermissionError as error:
        pytest.fail(f"the project file is still held open after the failed upgrade: {error}")
    assert moved.is_file()

    assert len(connections) == 1, f"open_project connected {len(connections)} times"
    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute("SELECT 1")
    del excinfo


# -- AC-5: a successful upgrade still hands back a connection in its normal state


@pytest.mark.parametrize(
    "rebuild", (*_REBUILDS, _V11_INTO_V13), ids=[r.id for r in (*_REBUILDS, _V11_INTO_V13)]
)
def test_a_successful_upgrade_returns_a_connection_with_foreign_keys_on_and_no_transaction(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    connections: list[sqlite3.Connection],
    rebuild: _Rebuild,
) -> None:
    db_path = _built(tmp_path, png_bytes, rebuild)

    with open_project(db_path.parent):
        assert len(connections) == 1, f"open_project connected {len(connections)} times"
        connection = connections[0]
        assert connection.in_transaction is False, "the upgrade left a transaction open"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA legacy_alter_table").fetchone()[0] == 0

    assert _user_version(db_path) == SCHEMA_VERSION
