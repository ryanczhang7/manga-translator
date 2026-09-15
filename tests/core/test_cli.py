"""`mangatl.cli`: pointing the app at a folder of scans, headlessly.

Covers AC-10 (the whole walk: create the project beside the folder, run every
page, write `<folder>_en/` with one identically named file per page in the same
order, one line of progress per page, exit `0`) and the two branches `## Contract`
PO-1 asks for as ordinary tests rather than as criteria - a second invocation
that reopens and resumes, and a folder with no page scans that exits non-zero
with a named message rather than a traceback.

Two conventions here are load-bearing rather than stylistic:

- **`main([...])` is called directly, in process.** A test that shells out to
  the `mangatl-run` console script is testing the installer: it passes when the
  entry point is registered and the code is broken, and fails when the code is
  right and the wheel was not reinstalled. `## Contract` PO-5.
- **`<folder>_en` is spelled out rather than derived from the implementation.**
  It is the path AC-10 promises the user; computing it with the same helper the
  writer uses would make the assertion agree with the code by construction.

A note on what these tests do NOT constrain: whether `main` refreshes the
project from the source folder on reopen, which stream the progress lines go to,
and what `main(None)` reads out of `sys.argv`. Those are the implementer's.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from mangatl.cli import main
from mangatl.store.project import project_dir_for

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 11),
    ("p4.png", 23, 17),
)
_FILENAMES: list[str] = [name for name, _, _ in _SOURCE_PAGES]

# -- helpers -------------------------------------------------------------------


def _build_source(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    pages: Sequence[tuple[str, int, int]] = _SOURCE_PAGES,
) -> Path:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for filename, width, height in pages:
        (source_dir / filename).write_bytes(png_bytes(width, height))
    return source_dir


def _output_dir_for(source_dir: Path) -> Path:
    """`<source>_en`. AC-10's promise, spelled out rather than derived."""
    return source_dir.with_name(source_dir.name + "_en")


def _contents(root: Path) -> list[str]:
    return sorted(entry.relative_to(root).as_posix() for entry in root.rglob("*"))


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of file contents, or None for a directory."""
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _lines_naming(lines: Sequence[str], filename: str) -> list[str]:
    return [line for line in lines if filename in line]


# -- AC-10: the whole walk ----------------------------------------------------


def test_pointing_the_cli_at_a_folder_creates_the_project_beside_it(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    code = main([str(source_dir)])

    assert code == 0
    project_dir = project_dir_for(source_dir)
    assert project_dir.parent == source_dir.parent, "the project is a sibling, not a child"
    assert (project_dir / "project.db").is_file()


def test_pointing_the_cli_at_a_folder_writes_the_sibling_output_folder(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)

    assert main([str(source_dir)]) == 0

    assert output_dir.parent == source_dir.parent, "the output folder is a sibling, not a child"
    assert _contents(output_dir) == sorted(_FILENAMES)
    mismatched = [
        name
        for name in _FILENAMES
        if _sha256_of(output_dir / name) != _sha256_of(source_dir / name)
    ]
    assert mismatched == [], f"output bytes differ from the input scan for: {mismatched}"


def test_the_cli_ran_every_page_and_recorded_a_finished_run(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    assert main([str(source_dir)]) == 0

    db_path = project_dir_for(source_dir) / "project.db"
    assert [row[0] for row in _raw(db_path, "SELECT outcome FROM run ORDER BY id")] == ["finished"]
    assert len(_raw(db_path, "SELECT ordinal FROM page")) == len(_SOURCE_PAGES)


def test_the_cli_emits_exactly_one_line_of_progress_per_page(
    tmp_path: Path, png_bytes: Callable[..., bytes], capsys: pytest.CaptureFixture[str]
) -> None:
    # "one line of progress output per page" (AC-10). Asserted by counting the
    # lines that name each page's own filename, which pins the *shape* of the
    # output - one line, one page, identified by something the user recognises -
    # without pinning a format nobody has designed yet. A run that printed one
    # summary line, or one line per stage, fails here.
    source_dir = _build_source(tmp_path, png_bytes)

    assert main([str(source_dir)]) == 0

    lines = _lines(capsys.readouterr().out)
    counted = {name: len(_lines_naming(lines, name)) for name in _FILENAMES}
    assert counted == dict.fromkeys(_FILENAMES, 1)


def test_the_cli_never_writes_inside_the_folder_of_scans(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # AC-8 end to end. The project and the output folder are both siblings, so
    # after a whole CLI run the user's scans must be byte-for-byte what they
    # were, with no directory added underneath them either.
    source_dir = _build_source(tmp_path, png_bytes)
    before = _snapshot(source_dir)
    assert sum(1 for value in before.values() if value is not None) == len(_SOURCE_PAGES)

    assert main([str(source_dir)]) == 0

    assert _snapshot(source_dir) == before


# -- PO-1's first extra branch: a second invocation reopens and resumes --------


def test_a_second_invocation_reopens_the_project_rather_than_recreating_it(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # `create_project` refuses an existing `project.db` with `ProjectExists`
    # rather than clobbering hours of edits (MT-005), so a CLI that always
    # creates cannot even return here. Two `run` rows in one project file is
    # what "reopened and ran again" looks like from outside; one row would mean
    # the file was rebuilt from scratch and the first run's work thrown away.
    source_dir = _build_source(tmp_path, png_bytes)
    assert main([str(source_dir)]) == 0

    assert main([str(source_dir)]) == 0

    db_path = project_dir_for(source_dir) / "project.db"
    assert [row[0] for row in _raw(db_path, "SELECT outcome FROM run ORDER BY id")] == [
        "finished",
        "finished",
    ]
    assert len(_raw(db_path, "SELECT id FROM chapter")) == 1


def test_a_second_invocation_skips_the_pages_the_first_one_finished(
    tmp_path: Path, png_bytes: Callable[..., bytes], capsys: pytest.CaptureFixture[str]
) -> None:
    # EPIC-02's done-when, through the entry point: starting again resumes
    # rather than restarting. Progress is still one line per page - a skipped
    # page is progress the user wants to see - and the output folder still holds
    # exactly the chapter.
    source_dir = _build_source(tmp_path, png_bytes)
    assert main([str(source_dir)]) == 0
    capsys.readouterr()

    assert main([str(source_dir)]) == 0

    lines = _lines(capsys.readouterr().out)
    counted = {name: len(_lines_naming(lines, name)) for name in _FILENAMES}
    assert counted == dict.fromkeys(_FILENAMES, 1)
    assert _contents(_output_dir_for(source_dir)) == sorted(_FILENAMES)


# -- PO-1's second extra branch: nothing to do, said plainly ------------------


def test_a_folder_with_no_page_scans_exits_non_zero_with_a_named_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    (source_dir / "notes.txt").write_text("not a scan\n", encoding="utf-8")

    code = main([str(source_dir)])

    assert code != 0, "a folder with nothing to translate reported success"
    captured = capsys.readouterr()
    message = captured.err + captured.out
    assert "no pages" in message.lower(), f"the message does not say what went wrong: {message!r}"
    assert source_dir.name in message, "the message does not say which folder"
    assert "Traceback" not in message, "the CLI let a traceback reach the user"
    assert not project_dir_for(source_dir).exists(), "a project was created for an empty chapter"
    assert not _output_dir_for(source_dir).exists()


def test_a_folder_that_is_not_there_exits_non_zero_with_a_named_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The likeliest user error of all: a typo in a path. It must read as a
    # message, not as an unhandled `FileNotFoundError` from `Path.iterdir`.
    missing = tmp_path / "not-a-folder"

    code = main([str(missing)])

    assert code != 0, "a folder that does not exist reported success"
    captured = capsys.readouterr()
    message = captured.err + captured.out
    assert missing.name in message, "the message does not say which folder"
    assert "Traceback" not in message, "the CLI let a traceback reach the user"
