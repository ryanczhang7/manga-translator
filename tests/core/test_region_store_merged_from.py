"""AC-9: a merged region written to a project and read back keeps `merged_from`.

**Why this is not ceremony** (C-6). `merged_from` defaults to `()`, so every
round-trip equality assertion MT-007 wrote in `tests/core/test_region_store.py`
- lines 146, 150, 151, 162, 174 and 219 - passes whether or not the column is
written, read, or even present. AC-9 is the only thing standing between MT-008
and a silent data-loss path that MT-009 would inherit, and it only does that job
if the region it writes carries a **non-empty** merge.

**Three conventions inherited from MT-005 and MT-007, each measured there:**

- the stored value is observed through a plain `sqlite3` connection, never
  through `Project` - "a codec that is uniformly wrong round-trips through
  itself perfectly" (`tdd-cycle`);
- the round trip is asserted against a project reopened from its path, with the
  writing object closed first;
- `write_regions` upserts. The `ON CONFLICT ... DO UPDATE SET` clause has to
  carry `merged_from` too (PO-2): the pipeline order is detect -> merge ->
  write, so a re-detection produces a fresh merge set and the previous one is
  stale rather than precious.

**An empty merge is stored as SQL NULL, not as `[]`.** That is C-6 as amended in
RED, and it is not a preference: `tests/core/test_region_store.py` line 130 is a
frozen MT-007 assertion that three regions written with no merge read back as
`[None, None, None]` through plain sqlite. A writer that stored `"[]"` would
fail it, in a file this story may not edit.
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
    confidence: float = 0.5,
    kind: str = "bubble",
    merged_from: tuple[int, ...] = (),
) -> RawRegion:
    x0, y0, x1, y1 = rect
    return RawRegion(
        polygon=((x0, y0), (x1 - 1, y0), (x1 - 1, y1 - 1), (x0, y1 - 1), (x0, y0)),
        mask=one_bit_png(_PAGE_W, _PAGE_H, [rect]),
        confidence=confidence,
        kind=kind,  # type: ignore[arg-type]
        merged_from=merged_from,
    )


def _merged_and_unmerged(one_bit_png: Callable[..., bytes]) -> tuple[RawRegion, ...]:
    """One region that absorbed two others and one that absorbed nothing.

    Both are needed: the first is what AC-9 is about, and the second is what
    proves the column is written per row rather than filled in once.
    """
    return (
        _region(one_bit_png, (10, 10, 60, 40), 0.81, "bubble", merged_from=(0, 2)),
        _region(one_bit_png, (100, 50, 180, 120), 0.42, "box"),
    )


def test_a_merged_region_read_back_from_a_reopened_project_still_names_its_inputs(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-9. Equality covers every field, and `merged_from` is asserted on its
    own as well, because that is the field this story added and the one whose
    loss the other assertions would not notice."""
    regions = _merged_and_unmerged(one_bit_png)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        writer.write_regions(0, regions)

    with open_project(project_dir_for(source_dir)) as reopened:
        read_back = reopened.read_regions(0)

    assert read_back == regions
    assert [region.merged_from for region in read_back] == [(0, 2), ()]
    assert all(isinstance(region.merged_from, tuple) for region in read_back)


def test_the_merge_on_disk_is_json_and_an_absent_merge_is_null(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-9, observed by a reader that imports nothing from `mangatl.store`.

    NULL for the unmerged row is C-6 as amended: MT-007's
    `test_region_store.py` line 130 asserts exactly that through this same
    plain-sqlite view, and it is frozen.
    """
    regions = _merged_and_unmerged(one_bit_png)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        writer.write_regions(1, regions)

    connection = sqlite3.connect(project_dir_for(source_dir) / "project.db")
    try:
        rows = connection.execute(
            "SELECT region.reading_index, region.merged_from"
            " FROM region JOIN page ON page.id = region.page_id"
            " WHERE page.ordinal = 1 ORDER BY region.reading_index"
        ).fetchall()
    finally:
        connection.close()

    assert [row[0] for row in rows] == [0, 1]
    assert json.loads(str(rows[0][1])) == [0, 2]
    assert rows[1][1] is None, "a region that absorbed nothing stores NULL, not '[]'"


def test_rewriting_a_page_replaces_the_merge_a_previous_detection_recorded(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-9 through the upsert, which is where the column is easiest to forget:
    an `ON CONFLICT ... DO UPDATE SET` that omits `merged_from` leaves the first
    run's merge attached to regions the second run no longer believes in (PO-2).
    """
    merged, unmerged = _merged_and_unmerged(one_bit_png)
    project.write_regions(0, (merged, unmerged))

    rerun = (
        _region(one_bit_png, (10, 10, 60, 40), 0.81, "bubble"),
        _region(one_bit_png, (100, 50, 180, 120), 0.42, "box", merged_from=(1, 3)),
    )
    project.write_regions(0, rerun)

    assert [region.merged_from for region in project.read_regions(0)] == [(), (1, 3)]


def test_a_row_written_before_this_story_reads_back_as_no_merge(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """C-6's compatibility clause. Every region row MT-005 and MT-007 wrote left
    `merged_from` NULL, and `read_regions` has to load those rather than raise -
    the read path reads what it writes (`architecture.md` D12), including what
    an earlier version of it wrote."""
    region = _region(one_bit_png, (10, 10, 60, 40), 0.81, "bubble")
    with project.transaction() as cursor:
        page_id = cursor.execute("SELECT id FROM page WHERE ordinal = 0").fetchone()[0]
        cursor.execute(
            "INSERT INTO region (page_id, reading_index, polygon, mask_blob, kind, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                page_id,
                0,
                json.dumps([list(vertex) for vertex in region.polygon]),
                region.mask,
                region.kind,
                region.confidence,
            ),
        )

    assert project.read_regions(0) == (region,)
    assert project.read_regions(0)[0].merged_from == ()
