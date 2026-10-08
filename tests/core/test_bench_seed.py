"""`mangatl.bench.seed`: a DRAFT ground truth from the detector's stored regions.

MT-029 AC-7, `## Contract` block 3, and the seed half of PO-5: the reminder that
every seed region is unreviewed and the human pass must look for the regions
the detector **missed**, printed at the moment the draft is written.

The fixture is a three-page chapter in `tmp_path/chapter-one`, a project made
with `create_project` beside it (`project_dir_for`), and regions stored with
`Project.write_regions` - the same route detection takes:

    ordinal  filename  size       stored regions
    0        001.png   120 x 100  a rectangle (bubble), a pentagon (box)
    1        002.png   130 x 110  a rectangle (bubble)
    2        003.png   140 x 120  none - "has detection run?"

`RawRegion.polygon` is a closed ring (first vertex repeated); the document's is
not (AC-1, PO-1). The pentagon is there so that "drop the closing vertex" is
told apart from "keep the first four".
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from mangatl.bench.seed import GroundTruthExists, main, seed_ground_truth
from mangatl.bench.truth import (
    GroundTruth,
    TruthPage,
    TruthRegion,
    dump_ground_truth,
    load_ground_truth,
    validate,
)
from mangatl.domain.page import Chapter
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for

OneBitPng = Callable[[int, int, Sequence[tuple[int, int, int, int]]], bytes]

_PAGES = (("001.png", 120, 100), ("002.png", 130, 110), ("003.png", 140, 120))

_RECT_RING = ((10, 10), (30, 10), (30, 20), (10, 20), (10, 10))
_PENTAGON_RING = ((40, 30), (60, 30), (70, 45), (50, 60), (40, 45), (40, 30))
_OTHER_RECT_RING = ((15, 50), (45, 50), (45, 70), (15, 70), (15, 50))


@pytest.fixture
def folder(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    source = tmp_path / "chapter-one"
    source.mkdir()
    for filename, width, height in _PAGES:
        (source / filename).write_bytes(png_bytes(width, height))
    return source


@pytest.fixture
def chapter(folder: Path, one_bit_png: OneBitPng) -> Chapter:
    """The chapter, with its project created and regions stored, then closed."""
    chapter = read_chapter(folder)
    with create_project(chapter, project_dir_for(folder)) as project:
        project.write_regions(
            0,
            [
                RawRegion(_RECT_RING, one_bit_png(120, 100, [(10, 10, 31, 21)]), 0.9, "bubble"),
                RawRegion(_PENTAGON_RING, one_bit_png(120, 100, [(40, 30, 71, 61)]), 0.8, "box"),
            ],
        )
        project.write_regions(
            1,
            [RawRegion(_OTHER_RECT_RING, one_bit_png(130, 110, [(15, 50, 46, 71)]), 0.7, "bubble")],
        )
    return chapter


def _expected(chapter: Chapter) -> GroundTruth:
    page0, page1, page2 = chapter.pages
    return GroundTruth(
        schema_version=1,
        chapter_name="chapter-one",
        development_use=False,
        pages=(
            TruthPage(
                0,
                "001.png",
                120,
                100,
                page0.sha256,
                (
                    TruthRegion(0, 0, _RECT_RING[:-1], "bubble", "seed", ""),
                    TruthRegion(0, 1, _PENTAGON_RING[:-1], "box", "seed", ""),
                ),
            ),
            TruthPage(
                1,
                "002.png",
                130,
                110,
                page1.sha256,
                (TruthRegion(1, 0, _OTHER_RECT_RING[:-1], "bubble", "seed", ""),),
            ),
            TruthPage(2, "003.png", 140, 120, page2.sha256, ()),
        ),
    )


def _open(folder: Path) -> Project:
    return open_project(project_dir_for(folder))


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


# -- seed_ground_truth --------------------------------------------------------


def test_ac7_seeding_writes_every_stored_region_as_an_unreviewed_seed_with_an_open_polygon(
    tmp_path: Path, folder: Path, chapter: Chapter
) -> None:
    out = tmp_path / "draft.truth.json"

    with _open(folder) as project:
        seeded = seed_ground_truth(project, out)

    assert seeded == _expected(chapter)
    assert all(region.source == "seed" for region in seeded.regions)
    assert all(region.polygon[0] != region.polygon[-1] for region in seeded.regions)


def test_ac7_the_draft_on_disk_is_the_dumped_document_and_loads_back_equal(
    tmp_path: Path, folder: Path, chapter: Chapter
) -> None:
    out = tmp_path / "draft.truth.json"

    with _open(folder) as project:
        seeded = seed_ground_truth(project, out)

    assert out.read_text(encoding="utf-8") == dump_ground_truth(seeded)
    assert load_ground_truth(out, benchmark=False) == seeded
    assert load_ground_truth(out) == seeded  # development_use is false


def test_ac7_a_fresh_draft_validates_against_its_chapter_and_warns_that_it_is_all_seed(
    tmp_path: Path, folder: Path, chapter: Chapter
) -> None:
    out = tmp_path / "draft.truth.json"
    with _open(folder) as project:
        seeded = seed_ground_truth(project, out)

    report = validate(seeded, chapter)

    assert report.ok, report.errors
    assert len(report.warnings) == 1, report.warnings
    assert report.warnings[0].startswith("WARNING:")
    assert re.search(r"(?<![\w.])100 ?%", report.warnings[0]), report.warnings


def test_ac7_seeding_refuses_to_overwrite_an_existing_document_and_leaves_it_byte_identical(
    tmp_path: Path, folder: Path, chapter: Chapter
) -> None:
    out = tmp_path / "draft.truth.json"
    out.write_bytes(b'{"hand": "annotated", "hours": 4}\n')
    before = out.read_bytes()

    with _open(folder) as project, pytest.raises(GroundTruthExists) as raised:
        seed_ground_truth(project, out)

    assert str(out) in str(raised.value)
    assert out.read_bytes() == before


def test_ac7_the_overwrite_check_comes_before_anything_is_read_from_the_project(
    tmp_path: Path, folder: Path, chapter: Chapter
) -> None:
    """Block 3: refuse 'before reading anything'. The project here is closed, so
    any `read_regions` would raise a sqlite error instead of the refusal."""
    out = tmp_path / "draft.truth.json"
    out.write_text("{}", encoding="utf-8")
    with _open(folder) as project:
        pass

    with pytest.raises(GroundTruthExists):
        seed_ground_truth(project, out)


# -- main: python -m mangatl.bench.seed FOLDER [--out PATH] -------------------


def test_main_writes_the_sibling_document_and_reports_each_page_the_path_and_the_reminder(
    tmp_path: Path, folder: Path, chapter: Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "chapter-one.truth.json"

    status = main([str(folder)])

    captured = capsys.readouterr()
    lines = _lines(captured.out)
    assert status == 0
    assert "page 0 (001.png): 2 region(s)" in lines
    assert "page 1 (002.png): 1 region(s)" in lines
    assert "page 2 (003.png): 0 region(s)" in lines
    warnings = [line for line in _lines(captured.out + captured.err) if line.startswith("warning:")]
    assert len(warnings) == 1, warnings
    assert "003.png" in warnings[0]
    assert any(str(out) in line for line in lines), lines
    assert any("missed" in line for line in lines), lines
    assert "Traceback" not in captured.out + captured.err
    assert load_ground_truth(out, benchmark=False) == _expected(chapter)


def test_main_writes_where_the_out_option_says(
    tmp_path: Path, folder: Path, chapter: Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "elsewhere.json"

    status = main([str(folder), "--out", str(out)])

    assert status == 0
    assert load_ground_truth(out, benchmark=False) == _expected(chapter)
    assert not (tmp_path / "chapter-one.truth.json").exists()
    assert any(str(out) in line for line in _lines(capsys.readouterr().out))


def test_main_refuses_a_second_run_with_one_sentence_and_leaves_the_document_untouched(
    tmp_path: Path, folder: Path, chapter: Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "chapter-one.truth.json"
    assert main([str(folder)]) == 0
    before = out.read_bytes()
    capsys.readouterr()

    status = main([str(folder)])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert status == 1
    assert len(_lines(combined)) == 1, combined
    assert str(out) in combined
    assert "Traceback" not in combined
    assert out.read_bytes() == before


def test_main_on_a_folder_with_no_project_returns_one_with_one_sentence(
    tmp_path: Path, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = main([str(folder)])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert status == 1
    assert len(_lines(combined)) == 1, combined
    assert "Traceback" not in combined
    assert not (tmp_path / "chapter-one.truth.json").exists()
