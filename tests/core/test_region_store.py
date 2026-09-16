"""AC-5: regions round-trip through MT-005's store with bit-identical masks.

MT-005 created the `region` table and **no code reads or writes it** (MT-007
C-8, verified against the tree again in RED: `src/mangatl/store/project.py`
exposes `chapter`, `pages`, `page_status`, `transaction` and
`refresh_from_source`, and nothing region-shaped). So AC-5 is not a round trip
through an existing API - this story writes that API, and this file is its
specification.

Three conventions here are load-bearing rather than stylistic, and two of them
are inherited from MT-005's own suite because its warnings were measured:

- **The stored bytes are observed with a plain `sqlite3` connection**, never
  through `Project`. "A codec that is uniformly wrong round-trips through itself
  perfectly" (`tdd-cycle`), and AC-5's word is *bit-identical*, which is a claim
  about what is on disk.
- **The round trip is asserted against a project reopened from the path.** The
  object that did the writing is closed first and never consulted again.
- **`write_regions` must upsert, not `INSERT OR REPLACE`.** MT-005 measured that
  `OR REPLACE` deletes the row and the `ON DELETE CASCADE` carries its `line`
  away with it; a re-run of detection that silently destroyed every translated
  line would be a data-loss bug no row count would show. The test that pins it
  attaches a line and re-writes the page.

`reading_index` is **emission order** here, and emission order only. MT-009 owns
reading order and will reassign it; this story must not invent one (MT-007 C-8).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for

_PAGE_W, _PAGE_H = 320, 240


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    """A two-page chapter. Two pages, so a write to page 0 can be shown not to
    touch page 1."""
    folder = tmp_path / "chapter"
    folder.mkdir()
    for name in ("p1.png", "p2.png"):
        (folder / name).write_bytes(png_bytes(_PAGE_W, _PAGE_H))
    return folder


@pytest.fixture
def project(source_dir: Path) -> Iterator[Project]:
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as opened:
        yield opened


def _region(
    one_bit_png: Callable[..., bytes],
    rect: tuple[int, int, int, int],
    confidence: float,
    kind: str,
) -> RawRegion:
    x0, y0, x1, y1 = rect
    return RawRegion(
        polygon=((x0, y0), (x1 - 1, y0), (x1 - 1, y1 - 1), (x0, y1 - 1), (x0, y0)),
        mask=one_bit_png(_PAGE_W, _PAGE_H, [rect]),
        confidence=confidence,
        kind=kind,  # type: ignore[arg-type]
    )


def _three_regions(one_bit_png: Callable[..., bytes]) -> tuple[RawRegion, ...]:
    """Three regions with three DISTINCT masks, confidences and kinds.

    Distinct masks are the point: a writer that stored the first region's blob
    three times would satisfy "the masks come back as PNG bytes" and fail this.
    """
    return (
        _region(one_bit_png, (10, 10, 60, 40), 0.81, "bubble"),
        _region(one_bit_png, (100, 50, 180, 120), 0.42, "box"),
        _region(one_bit_png, (200, 150, 300, 220), 1.0, "bubble"),
    )


def test_regions_written_to_a_page_come_back_bit_identical_from_a_reopened_project(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-5. Every field, and the mask compared as bytes rather than as an image."""
    regions = _three_regions(one_bit_png)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        writer.write_regions(0, regions)

    with open_project(project_dir_for(source_dir)) as reopened:
        read_back = reopened.read_regions(0)

    assert read_back == regions
    for stored, original in zip(read_back, regions, strict=True):
        assert stored.mask == original.mask
        assert len(stored.mask) == len(original.mask)


def test_the_mask_on_disk_is_the_regions_own_bytes_read_through_plain_sqlite(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-5, observed by a reader that imports nothing from `mangatl.store`."""
    regions = _three_regions(one_bit_png)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        writer.write_regions(1, regions)

    connection = sqlite3.connect(project_dir_for(source_dir) / "project.db")
    try:
        rows = connection.execute(
            "SELECT region.reading_index, region.polygon, region.mask_blob,"
            " region.kind, region.confidence, region.merged_from"
            " FROM region JOIN page ON page.id = region.page_id"
            " WHERE page.ordinal = 1 ORDER BY region.reading_index"
        ).fetchall()
    finally:
        connection.close()

    assert [row[0] for row in rows] == [0, 1, 2]
    assert [row[2] for row in rows] == [region.mask for region in regions]
    assert [row[3] for row in rows] == ["bubble", "box", "bubble"]
    assert [row[4] for row in rows] == pytest.approx([0.81, 0.42, 1.0])
    assert [row[5] for row in rows] == [None, None, None], "merged_from is MT-008's"
    for row, region in zip(rows, regions, strict=True):
        assert json.loads(row[1]) == [list(vertex) for vertex in region.polygon]


def test_regions_are_stored_at_reading_index_zero_upwards_in_emission_order(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """`reading_index` is the position in the sequence handed over, nothing more.

    MT-009 assigns the real reading order - right-to-left for Japanese - and
    will rewrite these. A store that sorted on its own here would be inventing
    an order this story is forbidden to invent."""
    regions = _three_regions(one_bit_png)
    project.write_regions(0, regions)

    assert project.read_regions(0) == regions


def test_a_page_nothing_was_written_for_reads_back_empty(project: Project) -> None:
    assert project.read_regions(0) == ()
    assert project.read_regions(1) == ()


def test_writing_an_empty_sequence_clears_the_page(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """The zero case that matters: a re-run on a page where the detector now
    finds nothing must leave nothing behind, not the previous run's regions."""
    project.write_regions(0, _three_regions(one_bit_png))
    project.write_regions(0, ())

    assert project.read_regions(0) == ()


def test_rewriting_a_page_with_fewer_regions_leaves_no_stragglers(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """An upsert alone would leave reading_index 2 behind, and MT-009 would read
    a region the detector no longer believes in."""
    project.write_regions(0, _three_regions(one_bit_png))
    fewer = _three_regions(one_bit_png)[:2]
    project.write_regions(0, fewer)

    assert project.read_regions(0) == fewer


def test_rewriting_a_page_keeps_the_line_attached_to_a_region_that_survived(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """The upsert, pinned by its consequence rather than by its SQL.

    MT-005 measured that `INSERT OR REPLACE` deletes the region row and the live
    `ON DELETE CASCADE` takes its `line` with it. Both forms leave the same three
    regions readable; only one of them keeps the translation.
    """
    regions = _three_regions(one_bit_png)
    project.write_regions(0, regions)
    with project.transaction() as cursor:
        region_id = cursor.execute(
            "SELECT region.id FROM region JOIN page ON page.id = region.page_id"
            " WHERE page.ordinal = 0 AND region.reading_index = 0"
        ).fetchone()[0]
        cursor.execute(
            "INSERT INTO line (region_id, source_ja, proposed_en) VALUES (?, ?, ?)",
            (region_id, "こんにちは", "hello"),
        )

    project.write_regions(0, regions)

    with project.transaction() as cursor:
        lines = cursor.execute(
            "SELECT line.source_ja FROM line JOIN region ON region.id = line.region_id"
            " JOIN page ON page.id = region.page_id"
            " WHERE page.ordinal = 0 AND region.reading_index = 0"
        ).fetchall()
    assert [row[0] for row in lines] == ["こんにちは"]


def test_writing_one_pages_regions_does_not_disturb_another_pages(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    first = _three_regions(one_bit_png)
    second = (_region(one_bit_png, (5, 5, 25, 25), 0.55, "box"),)
    project.write_regions(0, first)
    project.write_regions(1, second)

    project.write_regions(0, first[:1])

    assert project.read_regions(1) == second


def test_write_regions_is_its_own_transaction_and_refuses_to_nest(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """`write_regions` is atomic on its own (MT-007 amendment A-11), so it opens
    `transaction()` itself - and MT-005's non-reentrancy guard then refuses a
    caller that had already opened one. Pinning it here means the pipeline story
    finds out from a test rather than from a half-written page."""
    with pytest.raises(RuntimeError, match="not reentrant"), project.transaction():
        project.write_regions(0, _three_regions(one_bit_png))
