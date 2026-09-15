"""`mangatl.store.intake.read_chapter`: turning a folder into a `Chapter`.

Covers AC-1 (order, at the filesystem boundary), AC-2 (suffix filtering, exact
membership, no descent into subdirectories), AC-3 (`NoPagesFound`), AC-4 (the
`Page` fields, from real bytes), AC-5 (`UnreadablePage`, both PO-3 fixtures)
and AC-6 (the input folder is never written to). AC-7 is a `domain` test and
lives in `test_page.py` (`## Contract` PO-4).

Every fixture byte string used here is a plain `bytes` value from `conftest.py`
or written inline; nothing here imports `PIL` -- Pillow is not a dependency
during RED (`## Contract` PO-1) and does not arrive until GREEN.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from mangatl.store.intake import NoPagesFound, UnreadablePage, read_chapter


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of file contents, or None for a directory.

    Directories are included (not just files) so that AC-6 also catches a
    directory being created or removed under the input folder, not only a file
    being edited.
    """
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


# -- AC-1: filename order, not lexicographic order -----------------------------


def test_pages_are_ordered_p1_p2_p10_not_lexicographically(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    (tmp_path / "p2.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "p10.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "p1.png").write_bytes(png_bytes(7, 3))

    chapter = read_chapter(tmp_path)

    assert [page.filename for page in chapter.pages] == ["p1.png", "p2.png", "p10.png"]


# -- AC-2: exact membership, case-insensitive suffix, no subdirectory descent --


def test_only_recognised_suffixes_become_pages_and_nothing_else_does(
    tmp_path: Path, png_bytes: Callable[..., bytes], jpeg_7x3_bytes: bytes
) -> None:
    (tmp_path / "a.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "b.JPG").write_bytes(jpeg_7x3_bytes)
    (tmp_path / "c.jpeg").write_bytes(jpeg_7x3_bytes)
    (tmp_path / "notes.txt").write_bytes(b"not an image")
    (tmp_path / "thumbs.db").write_bytes(b"\x00\x01\x02")
    subdir = tmp_path / "sub"
    subdir.mkdir()
    # An image with a recognised suffix, but inside a subdirectory: "a
    # subdirectory is not descended into" (`## Contract`) means this must NOT
    # become a page, even though its bytes and suffix are otherwise fine.
    (subdir / "d.png").write_bytes(png_bytes(7, 3))

    chapter = read_chapter(tmp_path)

    # The full list, not just membership: "nothing else is" is half of AC-2.
    assert [page.filename for page in chapter.pages] == ["a.png", "b.JPG", "c.jpeg"]


# -- AC-3: an empty folder is a named error, not an empty chapter --------------


def test_a_folder_with_no_files_at_all_raises_nopagesfound_naming_the_folder(
    tmp_path: Path,
) -> None:
    with pytest.raises(NoPagesFound) as excinfo:
        read_chapter(tmp_path)

    message = str(excinfo.value)
    assert str(tmp_path) in message
    assert "no pages" in message.lower()


def test_a_folder_with_only_non_image_content_raises_nopagesfound(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    (tmp_path / "notes.txt").write_bytes(b"just notes")
    subdir = tmp_path / "sub"
    subdir.mkdir()
    # A real image, but inside a subdirectory -- still zero pages at this level.
    (subdir / "hidden.png").write_bytes(png_bytes(7, 3))

    with pytest.raises(NoPagesFound) as excinfo:
        read_chapter(tmp_path)

    assert str(tmp_path) in str(excinfo.value)


# -- AC-4: ordinal, basename, width/height (not transposed), sha256 -----------


def test_each_page_carries_its_ordinal_basename_dimensions_and_sha256(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # Distinct, NON-SQUARE sizes: a transposed (height, width) must fail this,
    # not pass it. `## Contract` PO-2.
    first_bytes = png_bytes(7, 3)
    second_bytes = png_bytes(13, 29)
    (tmp_path / "p1.png").write_bytes(first_bytes)
    (tmp_path / "p2.png").write_bytes(second_bytes)

    chapter = read_chapter(tmp_path)
    first, second = chapter.pages

    assert first.ordinal == 0
    assert second.ordinal == 1

    # Basename only, never a path: tmp_path itself is a deep, multi-segment
    # absolute path (pytest always builds one), so this also pins that a page
    # filename never carries any part of it.
    assert first.filename == "p1.png"
    assert second.filename == "p2.png"

    assert (first.width, first.height) == (7, 3)
    assert (second.width, second.height) == (13, 29)

    # sha256 over the RAW BYTES of the file, not decoded pixels -- computed
    # here with hashlib over the exact bytes written above.
    assert first.sha256 == hashlib.sha256(first_bytes).hexdigest()
    assert second.sha256 == hashlib.sha256(second_bytes).hexdigest()
    for page in (first, second):
        assert len(page.sha256) == 64
        assert page.sha256 == page.sha256.lower()


def test_the_jpeg_fixture_bytes_match_their_pinned_sha256(
    jpeg_7x3_bytes: bytes, jpeg_7x3_sha256: str
) -> None:
    # A self-check of the fixture recipe itself (`## Contract` PO-2(b)), not of
    # read_chapter: if this ever fails, the base64 constant was mistyped, not
    # the implementation.
    assert len(jpeg_7x3_bytes) == 286
    assert hashlib.sha256(jpeg_7x3_bytes).hexdigest() == jpeg_7x3_sha256


# -- AC-5: two fixtures, per PO-3 ----------------------------------------------


def test_a_file_that_is_not_an_image_at_all_is_reported_as_unreadable(
    tmp_path: Path, png_bytes: Callable[..., bytes], garbage_bytes: bytes
) -> None:
    (tmp_path / "p1.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "p2.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "p3.png").write_bytes(garbage_bytes)

    with pytest.raises(UnreadablePage) as excinfo:
        read_chapter(tmp_path)

    assert "p3.png" in str(excinfo.value)


def test_a_file_with_a_valid_header_and_a_corrupt_body_is_also_reported_as_unreadable(
    tmp_path: Path, png_bytes: Callable[..., bytes], corrupt_png_13x29_bytes: bytes
) -> None:
    # PO-3's second, load-bearing fixture: `Image.open()` accepts this header,
    # only `img.load()` rejects it. A reader built on `open()` alone (or
    # `open()` + `verify()`) would accept this file and pass a test that used
    # only the garbage fixture above -- this is the case that makes AC-5 mean
    # something (`## Contract` PO-1, PO-3; DV-1/DV-2, owned by GATES).
    (tmp_path / "p1.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "p2.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "p4.png").write_bytes(corrupt_png_13x29_bytes)

    with pytest.raises(UnreadablePage) as excinfo:
        read_chapter(tmp_path)

    assert "p4.png" in str(excinfo.value)


@pytest.mark.parametrize(
    ("corrupt_name", "corrupt_fixture"),
    [
        pytest.param("p3.png", "garbage_bytes", id="rejected-at-open"),
        pytest.param("p4.png", "corrupt_png_13x29_bytes", id="rejected-only-at-load"),
    ],
)
def test_the_raise_names_the_specific_corrupt_file_not_the_first_file_in_the_folder(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    corrupt_name: str,
    corrupt_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    # p1 sorts before the corrupt file under natural_key either way; if
    # read_chapter reported "the first file it tried" rather than the file
    # that actually failed, this would name p1.png instead.
    (tmp_path / "p1.png").write_bytes(png_bytes(7, 3))
    (tmp_path / corrupt_name).write_bytes(request.getfixturevalue(corrupt_fixture))

    with pytest.raises(UnreadablePage) as excinfo:
        read_chapter(tmp_path)

    assert corrupt_name in str(excinfo.value)
    assert "p1.png" not in str(excinfo.value)


def test_the_raise_names_the_underlying_decode_failure_not_only_the_filename(
    tmp_path: Path, garbage_bytes: bytes
) -> None:
    # PO-3: the message must name "that filename and the underlying decode
    # failure". Pinned as exception chaining (`raise ... from decode_error`)
    # rather than a specific wording of Pillow's own message, since PO-1
    # explicitly leaves the exact call open ("if RED or GREEN finds a cheaper
    # call that also rejects the fixture, say so").
    (tmp_path / "p1.png").write_bytes(garbage_bytes)

    with pytest.raises(UnreadablePage) as excinfo:
        read_chapter(tmp_path)

    assert excinfo.value.__cause__ is not None


def test_removing_the_corrupt_file_lets_the_remaining_pages_still_load(
    tmp_path: Path, png_bytes: Callable[..., bytes], garbage_bytes: bytes
) -> None:
    first_bytes = png_bytes(7, 3)
    second_bytes = png_bytes(13, 29)
    (tmp_path / "p1.png").write_bytes(first_bytes)
    (tmp_path / "p2.png").write_bytes(second_bytes)
    (tmp_path / "p3.png").write_bytes(garbage_bytes)

    with pytest.raises(UnreadablePage):
        read_chapter(tmp_path)

    (tmp_path / "p3.png").unlink()
    chapter = read_chapter(tmp_path)

    assert [page.filename for page in chapter.pages] == ["p1.png", "p2.png"]
    assert chapter.pages[0].sha256 == hashlib.sha256(first_bytes).hexdigest()
    assert chapter.pages[1].sha256 == hashlib.sha256(second_bytes).hexdigest()


# -- AC-6: the input folder is never written to --------------------------------


def test_reading_a_chapter_never_creates_modifies_or_deletes_anything_in_the_input_folder(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    (tmp_path / "p1.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "p2.png").write_bytes(png_bytes(13, 29))

    before = _snapshot(tmp_path)
    # The non-emptiness this AC depends on: a hash comparison over an empty or
    # mis-rooted file list would be satisfied vacuously.
    assert sum(1 for value in before.values() if value is not None) == 2

    read_chapter(tmp_path)

    after = _snapshot(tmp_path)
    assert after == before


def test_a_chapter_read_that_raises_still_leaves_the_input_folder_untouched(
    tmp_path: Path, png_bytes: Callable[..., bytes], garbage_bytes: bytes
) -> None:
    (tmp_path / "p1.png").write_bytes(png_bytes(7, 3))
    (tmp_path / "p2.png").write_bytes(garbage_bytes)

    before = _snapshot(tmp_path)
    assert sum(1 for value in before.values() if value is not None) == 2

    with pytest.raises(UnreadablePage):
        read_chapter(tmp_path)

    after = _snapshot(tmp_path)
    assert after == before
