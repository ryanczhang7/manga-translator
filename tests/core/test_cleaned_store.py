"""`Project.write_cleaned` / `read_cleaned` / `has_cleaned`, and invalidation (MT-065).

Covers AC-5 (a stored cleaned image survives close and reopen with the same
bytes, read through the store and through a plain `sqlite3` connection), C-3's
refusals (an image that does not decode, or is not the page's stored size, is a
`ValueError` naming the ordinal with nothing written - the mechanism behind
AC-1's "the size of the source page") and the store half of AC-4: re-detection
(`write_regions`, including `write_regions(n, ())` and a re-write of identical
regions) and a refresh after a scan changed or vanished each remove **that
page's** cleaned image and no other page's, and a `write_regions` that fails
inside its transaction removes nothing.

**"No other page's cleaned image is touched" is read byte for byte through a
plain `sqlite3` connection** (`_stored`), not through `read_cleaned`: a write
path and a read path wrong in the same direction cannot hide from an observer
that shares neither's assumptions (`test_pipeline.py`'s convention).

**Every page holds a distinct image**, so a `DELETE` keyed on the wrong page, or
an upsert that wrote one page's bytes against another, changes a value rather
than leaving three identical rows identical.

**Timing.** No `pytest-timeout` in this project; three tiny pages per test.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for

#: Three pages, three sizes, one of them a JPEG (C-2: the column holds the
#: source's own bytes for a page with no regions, and that may be a JPEG).
_PNG_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
)
_JPEG_PAGE = "p3.jpg"
_JPEG_ORDINAL = 2
_ORDINALS = (0, 1, 2)

#: The page under test, not ordinal 0 (MT-035 DV-3's reason).
_TARGET = 1
_TARGET_SIZE = (40, 30)

#: A standalone `1`, so "the message names the ordinal" is not satisfied by a
#: `1` inside `41` or `2026`. C-11 leaves the wording otherwise free.
_NAMES_TARGET = rf"(?<!\d){_TARGET}(?!\d)"


def _ring(x: int, y: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4), (x, y))


@dataclass(frozen=True)
class _Fixture:
    source_dir: Path
    project_dir: Path
    db_path: Path
    project: Project
    mask: bytes
    #: One distinct, correctly-sized cleaned image per ordinal.
    images: dict[int, bytes]

    def region(self, index: int) -> RawRegion:
        return RawRegion(polygon=_ring(4 * index, 0), mask=self.mask, confidence=0.5, kind="bubble")

    def clean_all(self) -> None:
        for ordinal, image in self.images.items():
            self.project.write_cleaned(ordinal, image)

    def stored(self) -> dict[int, bytes]:
        """ordinal -> blob, through a plain `sqlite3` connection."""
        connection = sqlite3.connect(self.db_path)
        try:
            return {
                int(ordinal): bytes(blob)
                for ordinal, blob in connection.execute(
                    "SELECT page.ordinal, cleaned_page.image_blob"
                    " FROM cleaned_page JOIN page ON page.id = cleaned_page.page_id"
                )
            }
        finally:
            connection.close()

    def others(self) -> dict[int, bytes]:
        return {ordinal: image for ordinal, image in self.images.items() if ordinal != _TARGET}


@pytest.fixture
def fixture(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    jpeg_7x3_bytes: bytes,
) -> Iterator[_Fixture]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_PNG_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 7, 0)))
    (source_dir / _JPEG_PAGE).write_bytes(jpeg_7x3_bytes)
    project_dir = project_dir_for(source_dir)

    images = {
        0: png_bytes(30, 20, (1, 2, 3)),
        1: png_bytes(40, 30, (4, 5, 6)),
        # The JPEG page's "cleaned" image is its own bytes (PO-4), which is
        # also the proof that a JPEG of the right size is accepted.
        2: jpeg_7x3_bytes,
    }
    with create_project(read_chapter(source_dir), project_dir) as project:
        yield _Fixture(
            source_dir=source_dir,
            project_dir=project_dir,
            db_path=project_dir / "project.db",
            project=project,
            mask=one_bit_png(*_TARGET_SIZE, [(0, 0, 4, 4)]),
            images=images,
        )


# -- write, read, has ----------------------------------------------------------


def test_a_written_cleaned_image_reads_back_as_the_same_bytes(fixture: _Fixture) -> None:
    fixture.project.write_cleaned(_TARGET, fixture.images[_TARGET])

    assert fixture.project.read_cleaned(_TARGET) == fixture.images[_TARGET]
    assert fixture.stored() == {_TARGET: fixture.images[_TARGET]}


def test_a_page_with_no_cleaned_image_reads_none_and_has_cleaned_is_false(
    fixture: _Fixture,
) -> None:
    assert fixture.project.read_cleaned(_TARGET) is None
    assert fixture.project.has_cleaned(_TARGET) is False

    fixture.project.write_cleaned(_TARGET, fixture.images[_TARGET])

    assert fixture.project.has_cleaned(_TARGET) is True
    assert fixture.project.has_cleaned(0) is False
    assert fixture.project.read_cleaned(0) is None


def test_a_second_write_replaces_the_first_and_leaves_one_row(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """C-3: "replacing any previous one" - an upsert on the page, never a
    second row."""
    replacement = png_bytes(40, 30, (200, 100, 50))
    fixture.project.write_cleaned(_TARGET, fixture.images[_TARGET])

    fixture.project.write_cleaned(_TARGET, replacement)

    assert fixture.project.read_cleaned(_TARGET) == replacement
    assert fixture.stored() == {_TARGET: replacement}


def test_a_jpeg_of_the_pages_size_is_accepted_verbatim(
    fixture: _Fixture, jpeg_7x3_bytes: bytes
) -> None:
    """C-2/PO-4: the column is an encoded image, not always a PNG."""
    fixture.project.write_cleaned(_JPEG_ORDINAL, jpeg_7x3_bytes)

    assert fixture.project.read_cleaned(_JPEG_ORDINAL) == jpeg_7x3_bytes


def test_write_cleaned_opens_its_own_transaction_and_refuses_a_caller_holding_one(
    fixture: _Fixture,
) -> None:
    """C-3: like `write_regions`, `transaction()` is not reentrant (MT-005 PO-5)."""
    with pytest.raises(RuntimeError, match="reentrant"), fixture.project.transaction():
        fixture.project.write_cleaned(_TARGET, fixture.images[_TARGET])

    assert fixture.project.read_cleaned(_TARGET) is None


# -- C-3's refusals: not an image, not the page's size -------------------------


@pytest.mark.parametrize(
    "size",
    [(50, 30), (40, 20), (30, 40)],
    ids=["too-wide", "too-short", "transposed"],
)
def test_an_image_that_is_not_the_pages_size_is_refused_by_ordinal_and_not_stored(
    fixture: _Fixture, png_bytes: Callable[..., bytes], size: tuple[int, int]
) -> None:
    """**AC-1**'s "the size of the source page", given a mechanism (C-3). The
    transposed case is the `(height, width)` slip numpy invites."""
    with pytest.raises(ValueError, match=_NAMES_TARGET):
        fixture.project.write_cleaned(_TARGET, png_bytes(*size))

    assert fixture.project.has_cleaned(_TARGET) is False
    assert fixture.stored() == {}


def test_a_refused_image_leaves_the_previous_cleaned_image_in_place(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """ "With nothing written" includes not deleting what was there."""
    fixture.project.write_cleaned(_TARGET, fixture.images[_TARGET])

    with pytest.raises(ValueError, match=_NAMES_TARGET):
        fixture.project.write_cleaned(_TARGET, png_bytes(50, 30))

    assert fixture.stored() == {_TARGET: fixture.images[_TARGET]}


def test_bytes_that_are_not_an_image_are_refused_by_ordinal_and_not_stored(
    fixture: _Fixture, garbage_bytes: bytes
) -> None:
    with pytest.raises(ValueError, match=_NAMES_TARGET):
        fixture.project.write_cleaned(_TARGET, garbage_bytes)

    assert fixture.project.read_cleaned(_TARGET) is None


# -- AC-5: survives close and reopen -------------------------------------------


def test_a_stored_cleaned_image_survives_close_and_reopen_with_the_same_bytes(
    fixture: _Fixture,
) -> None:
    """**AC-5.** Every page's image, after the connection that wrote it is
    closed, through `open_project` and through a plain connection."""
    fixture.clean_all()
    fixture.project.__exit__(None, None, None)

    with open_project(fixture.project_dir) as reopened:
        read_back = {ordinal: reopened.read_cleaned(ordinal) for ordinal in _ORDINALS}
        flags = {ordinal: reopened.has_cleaned(ordinal) for ordinal in _ORDINALS}

    assert read_back == fixture.images
    assert flags == dict.fromkeys(_ORDINALS, True)
    assert fixture.stored() == fixture.images


def test_a_deleted_cleaned_image_reads_back_as_none_and_not_as_the_source(
    fixture: _Fixture,
) -> None:
    """**AC-5**'s negative control: the read path consumes `image_blob` and
    nothing else. With the row gone there is nothing to regenerate it from, and
    a reader that fell back to the source scan would answer here."""
    fixture.clean_all()
    fixture.project.__exit__(None, None, None)
    connection = sqlite3.connect(fixture.db_path)
    try:
        with connection:
            connection.execute(
                "DELETE FROM cleaned_page WHERE page_id = (SELECT id FROM page WHERE ordinal = ?)",
                (_JPEG_ORDINAL,),
            )
    finally:
        connection.close()

    with open_project(fixture.project_dir) as reopened:
        assert reopened.read_cleaned(_JPEG_ORDINAL) is None
        assert reopened.has_cleaned(_JPEG_ORDINAL) is False
        assert reopened.read_cleaned(_TARGET) == fixture.images[_TARGET]


# -- AC-4: re-detection invalidates that page, and only that page --------------


def test_writing_a_pages_regions_removes_its_cleaned_image_and_no_other(
    fixture: _Fixture,
) -> None:
    """**AC-4**, re-detection: `write_regions` deletes this page's row in its
    own transaction (C-3), and every other page's bytes are unchanged."""
    fixture.clean_all()

    fixture.project.write_regions(_TARGET, [fixture.region(0), fixture.region(1)])

    assert fixture.project.has_cleaned(_TARGET) is False
    assert fixture.project.read_cleaned(_TARGET) is None
    assert fixture.stored() == fixture.others()


def test_rewriting_identical_regions_still_invalidates_the_cleaned_image(
    fixture: _Fixture,
) -> None:
    """C-3: unconditional. A re-detection that finds the same regions cannot
    know the cleaner would agree."""
    regions = [fixture.region(0)]
    fixture.project.write_regions(_TARGET, regions)
    fixture.clean_all()

    fixture.project.write_regions(_TARGET, regions)

    assert fixture.project.has_cleaned(_TARGET) is False
    assert fixture.stored() == fixture.others()


def test_writing_no_regions_for_a_page_invalidates_its_cleaned_image_too(
    fixture: _Fixture,
) -> None:
    """C-3: `write_regions(n, ())` invalidates - the page's last region going
    is exactly the case a cascade from `region` could not see (PO-5)."""
    fixture.project.write_regions(_TARGET, [fixture.region(0)])
    fixture.clean_all()

    fixture.project.write_regions(_TARGET, ())

    assert fixture.project.has_cleaned(_TARGET) is False
    assert fixture.stored() == fixture.others()


def test_a_write_regions_that_fails_inside_its_transaction_leaves_the_cleaned_image(
    fixture: _Fixture,
) -> None:
    """**AC-4** atomicity (C-8): the invalidating `DELETE` sits in the same
    transaction as the write that makes the image stale, so a write that rolls
    back takes the `DELETE` with it.

    The failing region is a valid `RawRegion` whose `mask` is then replaced by
    something `sqlite3` cannot bind - the domain refuses a non-PNG mask at
    construction, so the defect has to be introduced after it.
    """
    fixture.clean_all()
    broken = fixture.region(0)
    object.__setattr__(broken, "mask", object())

    with pytest.raises(sqlite3.Error):
        fixture.project.write_regions(_TARGET, [broken])

    assert fixture.stored() == fixture.images
    assert fixture.project.has_cleaned(_TARGET) is True


# -- AC-4: a changed or vanished scan, after a refresh -------------------------


def test_a_refresh_after_a_scan_changed_removes_that_pages_cleaned_image_and_no_other(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-4**, the second trigger: the scan's bytes change (same size, new
    content) and the project is refreshed."""
    fixture.clean_all()
    filename = _PNG_PAGES[_TARGET][0]
    (fixture.source_dir / filename).write_bytes(png_bytes(*_TARGET_SIZE, (250, 250, 250)))

    stale = fixture.project.refresh_from_source()

    assert stale == (_TARGET,)
    assert fixture.project.has_cleaned(_TARGET) is False
    assert fixture.stored() == fixture.others()


def test_a_refresh_after_a_scan_was_deleted_removes_that_pages_cleaned_image_and_no_other(
    fixture: _Fixture,
) -> None:
    """C-3: "including one whose file is gone"."""
    fixture.clean_all()
    (fixture.source_dir / _PNG_PAGES[_TARGET][0]).unlink()

    stale = fixture.project.refresh_from_source()

    assert stale == (_TARGET,)
    assert fixture.project.has_cleaned(_TARGET) is False
    assert fixture.stored() == fixture.others()


def test_a_refresh_after_a_regionless_scan_changed_removes_its_cleaned_image(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """C-3: "and one with no regions" - the stored image is the old scan's own
    bytes (PO-4), so leaving it would show the user a page that no longer
    exists. No region row exists here, so only the explicit `DELETE` can go."""
    fixture.project.write_cleaned(_TARGET, fixture.images[_TARGET])
    (fixture.source_dir / _PNG_PAGES[_TARGET][0]).write_bytes(png_bytes(*_TARGET_SIZE, (9, 9, 9)))

    fixture.project.refresh_from_source()

    assert fixture.project.read_cleaned(_TARGET) is None


def test_a_refresh_with_nothing_changed_removes_no_cleaned_image(fixture: _Fixture) -> None:
    """The control on the two refresh tests above: a refresh that deleted every
    page's image would pass them both."""
    fixture.clean_all()

    assert fixture.project.refresh_from_source() == ()
    assert fixture.stored() == fixture.images
