"""`mangatl.pipeline.export`: the sibling output folder, written atomically.

Covers AC-6 (one file per page, same filenames, same order, the page's current
bytes, and contents *replaced* rather than merged), AC-7 (a write that fails
partway leaves neither a partial page nor a stray temp file) and AC-8 for the
write path (nothing under the source folder is created, modified or deleted).

Two conventions here are load-bearing rather than stylistic:

- **The output folder is asserted by its EXACT contents**, over `rglob("*")`,
  never as "the expected files are present" and never as "no `p3.png` exists"
  (`## Contract` PO-8). One assertion then catches three different defects: a
  page missing, a partial page, and a leftover temp file from a write that
  raised between the temp and the rename. The last of those is the half that a
  "no `p3.png`" assertion misses entirely, and it is the half that leaves
  rubbish in the user's folder forever.
- **AC-7's failure is injected by monkeypatching `os.replace`**, not by making a
  directory read-only. A read-only directory behaves differently on Windows and
  POSIX, and a test built on one asserts the filesystem's permission model
  rather than the writer's. `_fail_replace_onto` therefore patches the attribute
  on the `os` module, which means `export` must call `os.replace(...)` and not
  `from os import replace` - that is a constraint on the implementation, and it
  is recorded in `## Handoff`.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from mangatl.domain.page import order_filenames
from mangatl.pipeline.export import write_output_folder
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

# The same four pages the rest of this story's suites use: four distinct
# non-square sizes, none another's transposition, so a page written under the
# wrong name is visible in the bytes as well as in the listing.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 11),
    ("p4.png", 23, 17),
)
_FILENAMES: list[str] = [name for name, _, _ in _SOURCE_PAGES]

#: The page AC-7 fails on. `p3.png` is the third page, ordinal 2 - AC-7 and AC-4
#: both count pages from one in prose and the store counts ordinals from zero.
_FAILS_ON = "p3.png"

#: A file already in `<source>_en/` whose name is no longer in the chapter.
#: AC-6's "replaced, not merged" is about exactly this file: left behind, it is
#: a page the user cannot account for sitting in a folder that promises "the
#: same filenames as the input".
_STALE_NAME = "p9-from-a-previous-chapter.png"


class _InjectedWriteFailure(OSError):
    """AC-7's injected rename failure.

    An `OSError` subclass, because that is what a real `os.replace` raises and a
    writer that catches `OSError` to clean up its temp file must not be able to
    tell this apart from the real thing. Bespoke, so the test cannot pass on an
    unrelated error raised somewhere else.
    """


# -- helpers -------------------------------------------------------------------


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of file contents, or None for a directory.

    The same shape as `test_intake.py`'s and `test_project.py`'s, and duplicated
    for the same reason: directories are included, over `rglob("*")`, so AC-8
    catches a *directory* appearing under the source folder as well as a file
    being created, edited or removed.
    """
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


def _contents(root: Path) -> list[str]:
    """Every path under `root`, relative, slash-normalised and sorted.

    `rglob("*")` rather than `iterdir()` so a temp file the writer hid in a
    subdirectory, and a subdirectory that should not be there at all, are caught
    by the same equality this file asserts everywhere.
    """
    return sorted(entry.relative_to(root).as_posix() for entry in root.rglob("*"))


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


def _new_project(source_dir: Path) -> Project:
    return create_project(read_chapter(source_dir), project_dir_for(source_dir))


def _output_dir_for(source_dir: Path) -> Path:
    """`<source>_en`, computed here rather than read from the store.

    AC-6 and AC-10 promise this literal path to the user. Deriving it in the
    test from the same helper the implementation uses would make the assertion
    agree with the code by construction; `architecture.md` §5 names the shape,
    so the test spells it out.
    """
    return source_dir.with_name(source_dir.name + "_en")


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fail_replace_onto(target: str) -> Callable[..., None]:
    """An `os.replace` that raises when the destination is named `target`.

    Every other rename is delegated to the real one, captured before the patch,
    so the pages before the failing page are written exactly as they would have
    been. That is what makes "the folder holds p1 and p2 and nothing else" an
    assertion about the writer rather than about the double.
    """
    real_replace = os.replace

    def replace(src: str | Path, dst: str | Path) -> None:
        if Path(dst).name == target:
            raise _InjectedWriteFailure(f"injected failure renaming onto {dst}")
        real_replace(src, dst)

    return replace


# -- AC-6: one file per page, same names, same order, the page's bytes ---------


def test_the_output_folder_holds_exactly_one_file_per_page_and_nothing_else(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)

    with _new_project(source_dir) as project:
        write_output_folder(project, output_dir)

    assert _contents(output_dir) == sorted(_FILENAMES)


def test_the_output_folder_is_created_when_it_does_not_exist_yet(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)
    assert not output_dir.exists()

    with _new_project(source_dir) as project:
        write_output_folder(project, output_dir)

    assert output_dir.is_dir()


def test_each_output_file_carries_the_pages_own_bytes_unchanged(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # "the page's current rendered output (for this story: the input bytes,
    # unchanged)". Compared by hash against the scan the page was read from, so
    # a writer that wrote every page the same bytes - four distinct sizes, so
    # they cannot coincide - fails on three of the four.
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)

    with _new_project(source_dir) as project:
        write_output_folder(project, output_dir)

    mismatched = [
        name
        for name in _FILENAMES
        if _sha256_of(output_dir / name) != _sha256_of(source_dir / name)
    ]
    assert mismatched == [], f"output bytes differ from the input scan for: {mismatched}"


def test_the_output_files_carry_the_same_names_in_the_same_reading_order(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # "the same order as the input" is a claim about the ordering rule, not
    # about directory iteration: put the output names through the chapter's own
    # `order_filenames` and they must come out as the chapter's ordinals do.
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)

    with _new_project(source_dir) as project:
        write_output_folder(project, output_dir)
        expected = [page.filename for page in project.pages()]

    assert order_filenames(_contents(output_dir)) == expected


def test_a_second_write_replaces_the_output_folder_rather_than_merging_into_it(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # Seeded with a stale page whose name is no longer in the chapter, and with
    # a wrong-bytes `p1.png`. Left behind, the stale file breaks the "same
    # filenames as the input" promise with a page the user cannot account for.
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)
    output_dir.mkdir()
    (output_dir / _STALE_NAME).write_bytes(png_bytes(3, 3))
    (output_dir / "p1.png").write_bytes(b"stale bytes from a previous bake\n")

    with _new_project(source_dir) as project:
        write_output_folder(project, output_dir)

    assert _contents(output_dir) == sorted(_FILENAMES)
    assert _sha256_of(output_dir / "p1.png") == _sha256_of(source_dir / "p1.png")


def test_a_single_page_chapter_writes_a_single_file(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes, pages=_SOURCE_PAGES[:1])
    output_dir = _output_dir_for(source_dir)

    with _new_project(source_dir) as project:
        write_output_folder(project, output_dir)

    assert _contents(output_dir) == ["p1.png"]


# -- AC-7: a write that fails partway -----------------------------------------


def test_a_rename_that_fails_on_page_three_leaves_no_partial_page_and_no_temp_file(
    tmp_path: Path, png_bytes: Callable[..., bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The exact-contents form is the whole assertion (`## Contract` PO-8): it
    # fails on a partial `p3.png` written straight to its final name, AND on a
    # temp file left behind because the raise happened between the write and the
    # rename. Those are two different defects and DV-2 mutates for both.
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)
    monkeypatch.setattr(os, "replace", _fail_replace_onto(_FAILS_ON))

    with _new_project(source_dir) as project, pytest.raises(_InjectedWriteFailure):
        write_output_folder(project, output_dir)

    assert _contents(output_dir) == ["p1.png", "p2.png"]


def test_the_pages_written_before_the_failure_are_whole(
    tmp_path: Path, png_bytes: Callable[..., bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)
    monkeypatch.setattr(os, "replace", _fail_replace_onto(_FAILS_ON))

    with _new_project(source_dir) as project, pytest.raises(_InjectedWriteFailure):
        write_output_folder(project, output_dir)

    for name in ("p1.png", "p2.png"):
        assert _sha256_of(output_dir / name) == _sha256_of(source_dir / name)


def test_a_failed_write_onto_the_first_page_leaves_the_output_folder_empty(
    tmp_path: Path, png_bytes: Callable[..., bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The zero case. An empty folder is the one listing a `finally` that deletes
    # the wrong path, or no `finally` at all, cannot produce.
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)
    monkeypatch.setattr(os, "replace", _fail_replace_onto("p1.png"))

    with _new_project(source_dir) as project, pytest.raises(_InjectedWriteFailure):
        write_output_folder(project, output_dir)

    assert _contents(output_dir) == []


# -- AC-8: the source folder is read, never written ---------------------------


def test_writing_the_output_folder_touches_nothing_in_the_source_folder(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)

    with _new_project(source_dir) as project:
        before = _snapshot(source_dir)
        # The non-emptiness this AC depends on: a hash comparison over an empty
        # or mis-rooted file list would be satisfied vacuously.
        assert sum(1 for value in before.values() if value is not None) == len(_SOURCE_PAGES)
        write_output_folder(project, output_dir)
        after = _snapshot(source_dir)

    assert after == before
    assert output_dir.parent == source_dir.parent, "the output folder is a sibling, not a child"


def test_a_write_that_fails_partway_still_touches_nothing_in_the_source_folder(
    tmp_path: Path, png_bytes: Callable[..., bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The temp file lives in the OUTPUT folder, never beside the scans. A writer
    # that staged its temp next to the source - on the same filesystem, which is
    # the tempting way to keep `os.replace` atomic - would fail here and nowhere
    # else.
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)

    with _new_project(source_dir) as project:
        before = _snapshot(source_dir)
        assert sum(1 for value in before.values() if value is not None) == len(_SOURCE_PAGES)
        monkeypatch.setattr(os, "replace", _fail_replace_onto(_FAILS_ON))
        with pytest.raises(_InjectedWriteFailure):
            write_output_folder(project, output_dir)
        after = _snapshot(source_dir)

    assert after == before
