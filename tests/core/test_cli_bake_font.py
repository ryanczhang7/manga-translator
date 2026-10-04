"""MT-027 PO-2 on the command line: a font fallback is said out loud, once.

`mangatl <folder>` prints MT-021's summary line, and - only when the bake's
`BakeReport.font_fallback != "none"` - one more line straight after it:

    font override not used: {detail}; lettered in Shantell Sans

on stdout, and the exit status is still 0: a fallback never blocks the bake.
With no override, or a valid one, the output is exactly MT-021's.

Driven in process through `mangatl.cli.main`, with the composition root
replaced at the `mangatl.cli.build_pipeline` seam by a stage that seeds one
cleaned page with two proposed lines - `tests/core/test_cli_bake.py`'s
conventions, in a separate file so that file stays untouched.

RED: `bake_chapter` reads no settings, so the fallback line is never printed.
"""

from __future__ import annotations

from pathlib import Path

import _bake_world as world
import _font_fixtures as ff
import pytest
from _bake_world import Spec
from _font_fixtures import BOXY

from mangatl.cli import main
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.store.project import PAGE_DONE

_MODELS_ENV = "MANGATL_MODELS"
_PREFIX = "font override not used: "


class _SeedingStage:
    """One cleaned page, two proposed lines: something for the font to letter."""

    name = "seeding"

    def run(self, ctx: PageContext) -> None:
        source_bytes = (ctx.project.chapter.source_dir / ctx.page.filename).read_bytes()
        page_regions = world.regions(2)
        cleaned = world.cleaned_from(world.decode_rgb(source_bytes), page_regions)
        specs = [Spec(proposed="HELLO"), Spec(proposed="THERE")]
        world.seed_page(ctx.project, 0, page_regions, specs, world.encode(cleaned, "PNG"))

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


@pytest.fixture(autouse=True)
def _no_ambient_models_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_MODELS_ENV, raising=False)


@pytest.fixture(autouse=True)
def _seeding_root(monkeypatch: pytest.MonkeyPatch) -> None:
    def build(models_dir: Path, *, translate: bool | None = None) -> tuple[Stage, ...]:
        return (_SeedingStage(),)

    monkeypatch.setattr("mangatl.cli.build_pipeline", build)


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "models"
    directory.mkdir()
    return directory


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "scans"
    directory.mkdir()
    texture = world.texture(world.PAGE_W, world.PAGE_H, salt=1)
    (directory / "p1.png").write_bytes(world.encode(texture, "PNG"))
    return directory


def _summary(source_dir: Path) -> str:
    output_dir = world.output_dir_for(source_dir)
    return (
        f"1 pages written to {output_dir}; 0 regions left empty;"
        f" 2 lines unreviewed; 0 pages not cleaned"
    )


def _run(source_dir: Path, models_dir: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert main([str(source_dir), "--models", str(models_dir)]) == 0, "the bake was blocked"
    out = capsys.readouterr().out
    return [line for line in out.splitlines() if line.strip()]


def test_a_font_fallback_prints_one_line_after_the_summary_naming_what_went_wrong(
    tmp_path: Path,
    appdata: Path,
    source_dir: Path,
    models_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gone = tmp_path / "Fonts I deleted"
    ff.write_settings(appdata, str(gone))

    lines = _run(source_dir, models_dir, capsys)

    assert lines[-2:] == [
        _summary(source_dir),
        f"font override not used: {gone} does not exist; lettered in Shantell Sans",
    ]
    assert [line for line in lines if line.startswith(_PREFIX)] == [lines[-1]]


def test_the_fallback_line_carries_the_reports_detail_verbatim_for_a_missing_style(
    tmp_path: Path,
    appdata: Path,
    source_dir: Path,
    models_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = tmp_path / "No bold"
    ff.write_family(folder, BOXY, styles=("regular", "italic", "bold_italic"))
    ff.write_settings(appdata, str(folder))

    lines = _run(source_dir, models_dir, capsys)

    assert lines[-1] == (
        f"font override not used: {folder} has no bold face; lettered in Shantell Sans"
    )


def test_the_fallback_line_goes_to_stdout_not_stderr(
    tmp_path: Path,
    appdata: Path,
    source_dir: Path,
    models_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ff.write_settings(appdata, str(tmp_path / "gone"))

    assert main([str(source_dir), "--models", str(models_dir)]) == 0
    captured = capsys.readouterr()

    assert _PREFIX in captured.out
    assert _PREFIX not in captured.err


def test_with_no_override_the_cli_prints_exactly_mt021s_summary_last(
    source_dir: Path, models_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _run(source_dir, models_dir, capsys)

    assert lines[-1] == _summary(source_dir)
    assert not any(_PREFIX in line or "Shantell" in line for line in lines)


def test_with_a_valid_override_the_cli_prints_no_font_line(
    tmp_path: Path,
    appdata: Path,
    source_dir: Path,
    models_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = tmp_path / "Boxy"
    ff.write_family(folder, BOXY)
    ff.write_settings(appdata, str(folder))

    lines = _run(source_dir, models_dir, capsys)

    assert lines[-1] == _summary(source_dir)
    assert not any(_PREFIX in line for line in lines)
