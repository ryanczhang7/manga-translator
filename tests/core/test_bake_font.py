"""MT-027 AC-7, AC-8, AC-9 and PO-3: the bake letters in the face the settings name.

`bake_chapter(project, output_dir)` and `preview_bake(project)` keep their
signatures and read `%APPDATA%\\mangatl\\settings.json` themselves (PO-1),
EXACTLY ONCE, at the start of the call (`## Contract`). `tests/conftest.py`
points `APPDATA` at an empty directory per test; `appdata` is that directory.

**What a page is compared against.** `_expected` letters each page with
`typeset` + `bake_page` over a `Faces` built by `load_faces(dir)` from an
"oracle" copy of the family written under the SHIPPED file names - so the
expected pixels never pass through `resolve_faces` or `validate_faces`, and a
resolver that picked the wrong file for a style disagrees with them.

**Why the faces are boxes.** `_font_fixtures.BOXY`, `_font_fixtures.WIDE` and
Shantell Sans letter the same lines differently (sizes measured in RED on
MT-021's 160x120 page, regions 0-2: HELLO 18 / 23 / 14-overflowed px; THERE
18-17 / 23-22 / 14-overflowed; OK! 35 / 35 / 20-19). Every test that relies on
two faces differing ASSERTS that they differ, on the pixels, before relying on
it: a discriminator that silently stopped discriminating would turn AC-8 into a
test that cannot fail.

**AC-8 is the falsifiable condition 3 fixture.** The settings file is rewritten
the moment the first page lands (`os.replace` onto `p1.png`, wrapped), during a
real `bake_chapter`. A bake that resolves once letters all three pages in the
starting face; one that resolves per page or per region letters pages 2-3 in the
other, and the pixel comparison names them.

RED: `BakeReport` has no `font_*` fields yet and `bake_chapter` reads no
settings, so these tests fail on construction or on their first assertion.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import _bake_world as world
import _font_fixtures as ff
import numpy as np
import pytest
from _bake_world import Spec
from _font_fixtures import BOXY, ELLIPSIS, EM_DASH, NOT_A_FONT, WIDE, Family
from numpy.typing import NDArray

import mangatl.pipeline.bake as bake_module
from mangatl.domain.line import effective_text
from mangatl.pipeline.bake import BakeReport, LineRef, bake_chapter, preview_bake
from mangatl.store.intake import read_chapter
from mangatl.store.lines import read_review_lines
from mangatl.store.project import create_project, open_project, project_dir_for
from mangatl.typeset.fit import typeset
from mangatl.typeset.font import FACE_FILENAMES, FONT_FAMILY, Faces, load_faces
from mangatl.typeset.render import bake_page

SIZE = (world.PAGE_W, world.PAGE_H)

#: Three regions (MT-021's 0-2), three proposed lines: every one is set.
TEXTS = ("HELLO", "THERE", "OK!")
REGION_COUNT = len(TEXTS)


#: `BakeReport`'s four counts for an n-page chapter of this shape.
def _counts(pages: int) -> dict[str, int]:
    return {
        "pages_written": pages,
        "regions_empty": 0,
        "unreviewed_lines": REGION_COUNT * pages,
        "pages_uncleaned": 0,
    }


# -- the world -----------------------------------------------------------------


def _chapter(tmp_path: Path, pages: int) -> tuple[Path, list[str]]:
    """`pages` cleaned pages, each with three proposed lines, in `tmp_path/scans`."""
    names = [f"p{i}.png" for i in range(1, pages + 1)]
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for i, name in enumerate(names):
        (source_dir / name).write_bytes(world.encode(world.texture(*SIZE, salt=i), "PNG"))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        for page in project.pages():
            source = world.decode_rgb((source_dir / page.filename).read_bytes())
            page_regions = world.regions(REGION_COUNT)
            cleaned = world.cleaned_from(source, page_regions)
            world.seed_page(
                project,
                page.ordinal,
                page_regions,
                [Spec(proposed=text) for text in TEXTS],
                world.encode(cleaned, "PNG"),
            )
    return source_dir, names


def _oracle_faces(tmp_path: Path, family: Family | None) -> Faces:
    """`family`'s faces read by MT-020's `load_faces`, or the shipped ones."""
    if family is None:
        return load_faces()
    directory = tmp_path / "oracle" / family.family
    ff.write_family(directory, family, names=dict(FACE_FILENAMES))
    return load_faces(directory)


def _expected(source_dir: Path, faces: Faces) -> dict[str, NDArray[np.uint8]]:
    """Each page as MT-021 bakes it, lettered in `faces`."""
    out = {}
    with open_project(project_dir_for(source_dir)) as project:
        for page in project.pages():
            page_regions = project.read_regions(page.ordinal)
            lines = read_review_lines(project, page.ordinal)
            blocks = [
                typeset(effective_text(line), region.polygon, faces)
                for region, line in zip(page_regions, lines, strict=True)
                if line is not None and line.status != "failed" and effective_text(line).strip()
            ]
            assert len(blocks) == REGION_COUNT
            cleaned = world.decode_rgb(project.read_cleaned(page.ordinal) or b"")
            out[page.filename] = bake_page(cleaned, blocks, world.bake_area(page_regions, SIZE))
    return out


def _baked(output_dir: Path, names: list[str]) -> dict[str, NDArray[np.uint8]]:
    return {name: world.decode_rgb((output_dir / name).read_bytes()) for name in names}


def _differing(
    actual: dict[str, NDArray[np.uint8]], expected: dict[str, NDArray[np.uint8]]
) -> list[str]:
    """The pages whose pixels are not exactly the expected ones."""
    return [name for name in expected if not np.array_equal(actual[name], expected[name])]


def _bake(source_dir: Path) -> BakeReport:
    with open_project(project_dir_for(source_dir)) as project:
        return bake_chapter(project, world.output_dir_for(source_dir))


def _family_dir(tmp_path: Path, family: Family) -> Path:
    directory = tmp_path / "user fonts" / family.family
    ff.write_family(directory, family)
    return directory


def _settings(appdata: Path) -> Path:
    return ff.settings_file(appdata)


# -- BakeReport's new fields default to "no override, nothing went wrong" ---------


def test_a_bake_report_built_from_its_four_counts_says_shantell_and_no_fallback() -> None:
    report = BakeReport(pages_written=1, regions_empty=0, unreviewed_lines=0, pages_uncleaned=0)

    assert report.font_family == FONT_FAMILY == "Shantell Sans"
    assert report.font_fallback == "none"
    assert report.font_detail == ""


def test_with_no_settings_file_the_bake_is_lettered_in_shantell_and_reports_no_fallback(
    tmp_path: Path,
) -> None:
    source_dir, names = _chapter(tmp_path, 1)

    report = _bake(source_dir)

    assert report == BakeReport(**_counts(1))
    assert (report.font_family, report.font_fallback, report.font_detail) == (
        FONT_FAMILY,
        "none",
        "",
    )
    expected = _expected(source_dir, load_faces())
    assert _differing(_baked(world.output_dir_for(source_dir), names), expected) == []


def test_a_valid_override_letters_the_bake_and_the_report_names_its_family(
    tmp_path: Path, appdata: Path
) -> None:
    source_dir, names = _chapter(tmp_path, 1)
    ff.write_settings(appdata, str(_family_dir(tmp_path, BOXY)))
    expected = _expected(source_dir, _oracle_faces(tmp_path, BOXY))
    shantell = _expected(source_dir, load_faces())
    assert _differing(expected, shantell) == names, "precondition: BOXY must differ from Shantell"

    report = _bake(source_dir)

    assert report == BakeReport(
        **_counts(1), font_family="Boxy Lettering", font_fallback="none", font_detail=""
    )
    assert _differing(_baked(world.output_dir_for(source_dir), names), expected) == []


# -- AC-7: every fallback is recorded on the BakeReport, and the bake proceeds -----

FallbackCase = Callable[[Path, Path], tuple[str, str]]


def _missing_path(tmp_path: Path, appdata: Path) -> tuple[str, str]:
    gone = tmp_path / "user fonts" / "Deleted"
    ff.write_settings(appdata, str(gone))
    return "missing_path", f"{gone} does not exist"


def _unparseable(tmp_path: Path, appdata: Path) -> tuple[str, str]:
    folder = _family_dir(tmp_path, BOXY)
    bad = folder / "f0.ttf"
    bad.write_bytes(NOT_A_FONT)
    ff.write_settings(appdata, str(folder))
    return "unparseable", f"{bad} is not a font: {ff.parse_error(NOT_A_FONT)}"


def _missing_glyphs(tmp_path: Path, appdata: Path) -> tuple[str, str]:
    # All four styles present; every face lacks the ellipsis and the em dash.
    folder = tmp_path / "user fonts" / "Gappy"
    written = ff.write_family(folder, BOXY, omit={k: (ELLIPSIS, EM_DASH) for k in ff.STYLE_KEYS})
    ff.write_settings(appdata, str(folder))
    return "missing_glyphs", f"{written['regular']} lacks U+2014, U+2026"


def _missing_style(tmp_path: Path, appdata: Path) -> tuple[str, str]:
    # Full coverage in every face; there is no bold.
    folder = tmp_path / "user fonts" / "No bold"
    ff.write_family(folder, BOXY, styles=("regular", "italic", "bold_italic"))
    ff.write_settings(appdata, str(folder))
    return "missing_style", f"{folder} has no bold face"


def _settings_unreadable(tmp_path: Path, appdata: Path) -> tuple[str, str]:
    # Row 1b, PO-4: the user's hand-edited JSON has a trailing comma.
    folder = _family_dir(tmp_path, BOXY)
    text = json.dumps({"lettering_font_dir": str(folder)})[:-1] + ",}"
    settings = ff.write_settings(appdata, None, raw=text)
    with pytest.raises(json.JSONDecodeError) as caught:
        json.loads(text)
    return "missing_path", f"{settings} could not be read: {caught.value}"


FALLBACKS: dict[str, FallbackCase] = {
    "missing_path": _missing_path,
    "unparseable": _unparseable,
    "missing_glyphs": _missing_glyphs,
    "missing_style": _missing_style,
    "settings_unreadable": _settings_unreadable,
}


@pytest.mark.parametrize("case", list(FALLBACKS))
def test_a_fallback_is_recorded_on_the_bake_report_with_its_reason_and_detail(
    tmp_path: Path, appdata: Path, case: str
) -> None:
    source_dir, _ = _chapter(tmp_path, 1)
    reason, detail = FALLBACKS[case](tmp_path, appdata)

    report = _bake(source_dir)

    assert (report.font_fallback, report.font_detail) == (reason, detail)
    assert report == BakeReport(
        **_counts(1), font_family=FONT_FAMILY, font_fallback=reason, font_detail=detail
    )


@pytest.mark.parametrize("case", list(FALLBACKS))
def test_a_fallback_never_blocks_the_bake_and_letters_every_page_in_shantell(
    tmp_path: Path, appdata: Path, case: str
) -> None:
    source_dir, names = _chapter(tmp_path, 2)
    FALLBACKS[case](tmp_path, appdata)

    _bake(source_dir)

    output_dir = world.output_dir_for(source_dir)
    assert world.contents(output_dir) == names
    assert _differing(_baked(output_dir, names), _expected(source_dir, load_faces())) == []


# -- AC-8: one face for every page and every region of a bake ----------------------

Start = Family | None


def _switch_after_first_page(
    monkeypatch: pytest.MonkeyPatch, output_dir: Path, switch: Callable[[], None]
) -> list[str]:
    """Run `switch` once, right after the first page is renamed into place."""
    real_replace = os.replace
    switched: list[str] = []

    def replace(src: str | Path, dst: str | Path) -> None:
        real_replace(src, dst)
        if not switched and Path(dst).parent == output_dir:
            switched.append(Path(dst).name)
            switch()

    monkeypatch.setattr(os, "replace", replace)
    return switched


@pytest.mark.parametrize(
    ("start", "then"),
    [(BOXY, WIDE), (BOXY, None), (None, BOXY)],
    ids=["override-then-another", "override-then-removed", "none-then-override"],
)
def test_every_page_of_a_bake_is_lettered_in_the_face_resolved_when_it_started(
    tmp_path: Path,
    appdata: Path,
    monkeypatch: pytest.MonkeyPatch,
    start: Start,
    then: Start,
) -> None:
    source_dir, names = _chapter(tmp_path, 3)
    output_dir = world.output_dir_for(source_dir)
    if start is not None:
        ff.write_settings(appdata, str(_family_dir(tmp_path, start)))
    then_dir = _family_dir(tmp_path, then) if then is not None else None
    expected = _expected(source_dir, _oracle_faces(tmp_path, start))
    other = _expected(source_dir, _oracle_faces(tmp_path, then))
    assert _differing(expected, other) == names, "precondition: the two faces must differ"

    def switch() -> None:
        if then_dir is None:
            _settings(appdata).unlink()
        else:
            ff.write_settings(appdata, str(then_dir))

    switched = _switch_after_first_page(monkeypatch, output_dir, switch)
    report = _bake(source_dir)

    assert switched == ["p1.png"], "precondition: the settings changed after page 1 was written"
    assert _differing(_baked(output_dir, names), expected) == [], (
        "these pages were not lettered in the face the bake started with"
    )
    assert report.font_family == (start.reported if start is not None else FONT_FAMILY)
    assert report.font_fallback == "none"


# -- AC-9: removing the override leaves no residue ---------------------------------


def _remove(appdata: Path, how: str) -> None:
    settings = _settings(appdata)
    if how == "file-deleted":
        settings.unlink()
    else:
        value = {"key-absent": {}, "null": {"lettering_font_dir": None}}.get(
            how, {"lettering_font_dir": ""}
        )
        settings.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("how", ["file-deleted", "key-absent", "null", "empty-string"])
def test_after_the_override_is_removed_the_next_bake_is_shantell_with_no_residue(
    tmp_path: Path, appdata: Path, how: str
) -> None:
    source_dir, names = _chapter(tmp_path, 1)
    output_dir = world.output_dir_for(source_dir)
    ff.write_settings(appdata, str(_family_dir(tmp_path, BOXY)))
    boxy = _expected(source_dir, _oracle_faces(tmp_path, BOXY))
    shantell = _expected(source_dir, load_faces())
    assert _differing(boxy, shantell) == names, "precondition: BOXY must differ from Shantell"

    first = _bake(source_dir)
    assert first.font_family == "Boxy Lettering"
    assert _differing(_baked(output_dir, names), boxy) == []

    _remove(appdata, how)
    second = _bake(source_dir)

    assert second == BakeReport(**_counts(1))
    assert (second.font_family, second.font_fallback, second.font_detail) == (
        FONT_FAMILY,
        "none",
        "",
    )
    assert _differing(_baked(output_dir, names), shantell) == []


def test_changing_the_override_between_bakes_letters_the_next_bake_in_the_new_one(
    tmp_path: Path, appdata: Path
) -> None:
    source_dir, names = _chapter(tmp_path, 1)
    output_dir = world.output_dir_for(source_dir)
    ff.write_settings(appdata, str(_family_dir(tmp_path, BOXY)))
    _bake(source_dir)

    ff.write_settings(appdata, str(_family_dir(tmp_path, WIDE)))
    report = _bake(source_dir)

    wide = _expected(source_dir, _oracle_faces(tmp_path, WIDE))
    assert report.font_family == "Wide Lettering"
    assert _differing(_baked(output_dir, names), wide) == []


# -- PO-3: the Render dialog's preview honours the same override -------------------

#: WIDE's boxes are too wide for HELLO and THERE in regions 0 and 1 even at the
#: minimum size; OK! fits region 2. Shantell and BOXY fit all three (RED).
WIDE_OVERFLOWS = (0, 1)


def test_the_preview_counts_the_lines_that_overflow_in_the_override_face(
    tmp_path: Path, appdata: Path
) -> None:
    source_dir, _ = _chapter(tmp_path, 1)
    with open_project(project_dir_for(source_dir)) as project:
        default = preview_bake(project)
    ff.write_settings(appdata, str(_family_dir(tmp_path, WIDE)))

    with open_project(project_dir_for(source_dir)) as project:
        wide = preview_bake(project)

    assert default.overflowing == ()
    assert wide.overflowing == tuple(LineRef(0, i) for i in WIDE_OVERFLOWS)


@pytest.mark.parametrize("case", list(FALLBACKS))
def test_a_preview_with_an_unusable_override_does_not_raise_and_states_the_shantell_preview(
    tmp_path: Path, appdata: Path, case: str
) -> None:
    source_dir, _ = _chapter(tmp_path, 1)
    with open_project(project_dir_for(source_dir)) as project:
        default = preview_bake(project)
    FALLBACKS[case](tmp_path, appdata)

    with open_project(project_dir_for(source_dir)) as project:
        assert preview_bake(project) == default


@pytest.mark.parametrize(
    ("start", "then", "overflowing"),
    [
        (None, WIDE, ()),
        (WIDE, None, tuple(LineRef(p, i) for p in range(3) for i in WIDE_OVERFLOWS)),
    ],
    ids=["none-then-wide", "wide-then-removed"],
)
def test_the_preview_reads_the_settings_once_not_once_per_page(
    tmp_path: Path,
    appdata: Path,
    monkeypatch: pytest.MonkeyPatch,
    start: Start,
    then: Start,
    overflowing: tuple[LineRef, ...],
) -> None:
    source_dir, _ = _chapter(tmp_path, 3)
    if start is not None:
        ff.write_settings(appdata, str(_family_dir(tmp_path, start)))
    then_dir = _family_dir(tmp_path, then) if then is not None else None
    real_read = bake_module.read_review_lines
    calls: list[int] = []

    def read_then_switch(project, ordinal):  # type: ignore[no-untyped-def]
        result = real_read(project, ordinal)
        calls.append(ordinal)
        if len(calls) == 1:
            if then_dir is None:
                _settings(appdata).unlink()
            else:
                ff.write_settings(appdata, str(then_dir))
        return result

    monkeypatch.setattr(bake_module, "read_review_lines", read_then_switch)
    with open_project(project_dir_for(source_dir)) as project:
        preview = preview_bake(project)

    assert calls == [0, 1, 2], "precondition: the preview read page 1's lines first"
    assert preview.overflowing == overflowing
