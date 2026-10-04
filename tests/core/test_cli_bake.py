"""`mangatl <folder>` bakes: MT-021 AC-9 and C-7, through `mangatl.cli.main`.

A separate file so that `test_cli.py`'s existing assertions stay untouched
(C-7: its stage list detects nothing, so its pages are written verbatim and its
byte-identity test stays true). Its conventions are kept: `main([...])` in
process, `--models` with an empty directory, the composition root replaced at
the `mangatl.cli.build_pipeline` seam, `MANGATL_MODELS` out of the environment,
and `<folder>_en` spelled out.

**The stage here writes what the real pipeline would**, so pass-through output
fails: on `p1.png` three regions, their lines (two proposals and one failed
read), and a cleaned page that differs from the scan inside the erase mask; on
`p2.png` regions and accepted lines but no cleaned image (C-5 row 2). `p3` and
`p4` get nothing. The summary line's numbers follow:

| count | value | why |
|---|---|---|
| pages written | 4 | every page |
| regions left empty | 1 | p1's failed line |
| lines unreviewed | 2 | p1's two proposals (the page is done, so `proposed`) |
| pages not cleaned | 1 | p2 |
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import _bake_world as world
import numpy as np
import pytest
from _bake_world import Spec

from mangatl.cli import main
from mangatl.domain.line import effective_text
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.store.lines import read_review_lines
from mangatl.store.project import PAGE_DONE, open_project, project_dir_for
from mangatl.typeset.fit import typeset
from mangatl.typeset.font import load_faces
from mangatl.typeset.render import bake_page

_MODELS_ENV = "MANGATL_MODELS"
_NAMES = ["p1.png", "p2.png", "p3.png", "p4.png"]


class _SeedingStage:
    """Writes regions, lines and a cleaned page as detect/OCR/translate/clean would."""

    name = "seeding"

    def run(self, ctx: PageContext) -> None:
        source_bytes = (ctx.project.chapter.source_dir / ctx.page.filename).read_bytes()
        if ctx.page.ordinal == 0:
            page_regions = world.regions(3)
            cleaned = world.cleaned_from(world.decode_rgb(source_bytes), page_regions)
            specs = [Spec(proposed="HELLO"), Spec(proposed="THERE"), Spec(ocr_empty=True)]
            world.seed_page(ctx.project, 0, page_regions, specs, world.encode(cleaned, "PNG"))
        elif ctx.page.ordinal == 1:
            accepted = [Spec(proposed="OK!", commit=("accepted", None))] * 2
            world.seed_page(ctx.project, 1, world.regions(2), accepted, cleaned=None)

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


@pytest.fixture(autouse=True)
def _no_ambient_models_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_MODELS_ENV, raising=False)


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "models"
    directory.mkdir()
    return directory


@pytest.fixture
def seeding_root(monkeypatch: pytest.MonkeyPatch) -> None:
    def build(models_dir: Path, *, translate: bool | None = None) -> tuple[Stage, ...]:
        return (_SeedingStage(),)

    monkeypatch.setattr("mangatl.cli.build_pipeline", build)


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    directory = tmp_path / "scans"
    directory.mkdir()
    size = (world.PAGE_W, world.PAGE_H)
    (directory / "p1.png").write_bytes(world.encode(world.texture(*size, salt=1), "PNG"))
    (directory / "p2.png").write_bytes(world.encode(world.texture(*size, salt=2), "PNG"))
    (directory / "p3.png").write_bytes(png_bytes(5, 11))
    (directory / "p4.png").write_bytes(png_bytes(23, 17))
    return directory


def test_the_cli_writes_the_baked_page_not_a_copy_of_the_scan(
    source_dir: Path, models_dir: Path, seeding_root: None
) -> None:
    output_dir = world.output_dir_for(source_dir)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    with open_project(project_dir_for(source_dir)) as project:
        page_regions = project.read_regions(0)
        cleaned = world.decode_rgb(project.read_cleaned(0) or b"")
        faces = load_faces()
        blocks = [
            typeset(effective_text(line), region.polygon, faces)
            for region, line in zip(page_regions, read_review_lines(project, 0), strict=True)
            if line is not None and line.status != "failed" and effective_text(line).strip()
        ]
    area = world.bake_area(page_regions, (world.PAGE_W, world.PAGE_H))
    out = world.decode_rgb((output_dir / "p1.png").read_bytes())

    assert len(blocks) == 2
    assert world.sha256_of(output_dir / "p1.png") != world.sha256_of(source_dir / "p1.png")
    assert np.array_equal(out, bake_page(cleaned, blocks, area))


def test_the_cli_writes_pages_with_nothing_to_bake_as_their_scans(
    source_dir: Path, models_dir: Path, seeding_root: None
) -> None:
    # p2 has regions but no cleaned image (C-5 row 2); p3 and p4 have none.
    output_dir = world.output_dir_for(source_dir)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert world.contents(output_dir) == _NAMES
    assert {n: world.sha256_of(output_dir / n) for n in _NAMES[1:]} == {
        n: world.sha256_of(source_dir / n) for n in _NAMES[1:]
    }


def test_the_cli_prints_one_summary_line_carrying_the_bake_reports_counts(
    source_dir: Path,
    models_dir: Path,
    seeding_root: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = world.output_dir_for(source_dir)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    summaries = [line for line in lines if "pages written to" in line]
    assert summaries == [
        f"4 pages written to {output_dir}; 1 regions left empty;"
        f" 2 lines unreviewed; 1 pages not cleaned"
    ]
    assert lines[-1] == summaries[0], "the summary is the last thing printed"
