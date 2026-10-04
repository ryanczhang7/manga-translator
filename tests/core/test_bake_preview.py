"""MT-066 C-1: `mangatl.pipeline.bake.preview_bake`, the counts the dialog states.

AC-1 asks the Render dialog to state the output folder, the page count, the
unreviewed lines with their pages, and the `failed` and overflowing lines. Those
numbers are computed here, before the bake, by `preview_bake`; the dialog
(`tests/ui/test_bake_dialog.py`) only presents them.

**Oracle: settled numbers, derived by hand from the seeded statuses** (C-6). The
chapter below is seeded with `_bake_world.seed_page`, and every expected tuple is
written out from the table in `mixed_chapter`'s docstring, not computed by any
code under test. Overflow uses MT-021's known geometry: `world.OVERFLOW` is the
small region a long line cannot fit, region 0 holds a short line. Measured in
RED against `typeset` + `load_faces` directly (story `## Handoff`): on the
160x120 page `LONG` overflows region 3, and `HELLO`/`THERE`/`OK!` fit regions
0-2.

**The cross-check needs no oracle** (C-1): `len(preview.unreviewed)` equals
`bake_chapter(...).unreviewed_lines` on the same seeded chapter.

**`<source>_en` is spelled out**, never read from `output_dir_for`.

RED: `preview_bake`, `BakePreview`, `LineRef` and `output_dir_for` do not exist
in `mangatl.pipeline.bake`, so this file fails at import and no assertion in it
has run. Pages are 160x120 and there are at most six: no `pytest-timeout`
exists, and the coverage gate runs this file instrumented.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import _bake_world as world
import pytest
from _bake_world import Spec

import mangatl.pipeline.bake as bake_module
from mangatl.pipeline.bake import (
    BakePreview,
    LineRef,
    bake_chapter,
    output_dir_for,
    preview_bake,
)
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for

SIZE = (world.PAGE_W, world.PAGE_H)

#: Overflows every region of the 160x120 page (measured in RED), and region 3
#: (`world.OVERFLOW`) in particular - MT-021's `_SHORT[OVERFLOW]`.
LONG = "A LOT OF WORDS FOR A TINY BOX"


def _ref(page: int, index: int) -> LineRef:
    return LineRef(page_ordinal=page, reading_index=index)


def _source(tmp_path: Path, count: int) -> Path:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for i in range(count):
        data = world.encode(world.texture(*SIZE, salt=i), "PNG")
        (source_dir / f"p{i + 1}.png").write_bytes(data)
    return source_dir


def _seed(source_dir: Path, pages: Sequence[tuple[Sequence[Spec] | None, bool] | None]) -> None:
    """One entry per page: `None` = no regions at all; otherwise `(specs,
    cleaned)` over the four regions, `specs=None` meaning OCR never ran."""
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        for page, entry in zip(project.pages(), pages, strict=True):
            if entry is None:
                continue
            specs, cleaned = entry
            page_regions = world.regions()
            source = world.decode_rgb((source_dir / page.filename).read_bytes())
            image = (
                world.encode(world.cleaned_from(source, page_regions), "PNG") if cleaned else None
            )
            world.seed_page(project, page.ordinal, page_regions, specs, image)


def _open(source_dir: Path) -> Project:
    return open_project(project_dir_for(source_dir))


@pytest.fixture
def mixed_chapter(tmp_path: Path) -> Path:
    """Six pages. Statuses, by hand (r0..r3 are the four regions):

    ord  page  cleaned  r0                r1             r2                  r3
    0    p1    yes      proposed HELLO    accepted       failed (ocr_empty)  proposed LONG
    1    p2    yes      -- regions, OCR never ran: four `None` lines --
    2    p3    NO       proposed OK!      reverted       failed (ocr_empty)  proposed LONG
    3    p4    -        -- no regions at all --
    4    p5    yes      proposed "   "    edited to ""   accepted            failed, proposal LONG
    5    p6    yes      accepted HELLO    accepted       accepted            edited to LONG

    total_lines  = 4 + 0 + 4 + 0 + 4 + 4                        = 16
    unreviewed   = (0,0) (0,3) (2,0) (2,3) (4,0)                -> 5
    failed       = (0,2) (2,2) (4,3)                            -> 3
    overflowing  = (0,3) (5,3)                                  -> 2
      not (2,3): p3 is uncleaned, so it is never baked;
      not (4,3): failed lines are never set;
      not (4,0)/(4,1): blank effective text is never set;
      (5,3): the EDITED text is what is set, not the short proposal.
    """
    source_dir = _source(tmp_path, 6)
    _seed(
        source_dir,
        [
            (
                [
                    Spec(proposed="HELLO"),
                    Spec(proposed="THERE", commit=("accepted", None)),
                    Spec(proposed="HELLO", ocr_empty=True),
                    Spec(proposed=LONG),
                ],
                True,
            ),
            (None, True),
            (
                [
                    Spec(proposed="OK!"),
                    Spec(proposed="NO", commit=("reverted", "NO")),
                    Spec(proposed="OK!", ocr_empty=True),
                    Spec(proposed=LONG),
                ],
                False,
            ),
            None,
            (
                [
                    Spec(proposed="   "),
                    Spec(proposed="THERE", commit=("edited", "")),
                    Spec(proposed="OK!", commit=("accepted", None)),
                    Spec(proposed=LONG, ocr_empty=True),
                ],
                True,
            ),
            (
                [
                    Spec(proposed="HELLO", commit=("accepted", None)),
                    Spec(proposed="THERE", commit=("accepted", None)),
                    Spec(proposed="OK!", commit=("accepted", None)),
                    Spec(proposed="OK", commit=("edited", LONG)),
                ],
                True,
            ),
        ],
    )
    return source_dir


# -- the exports -----------------------------------------------------------------


def test_the_preview_names_are_exported_beside_bake_chapter() -> None:
    for name in ("BakePreview", "LineRef", "output_dir_for", "preview_bake"):
        assert name in bake_module.__all__, f"{name} is missing from mangatl.pipeline.bake.__all__"
    assert {"BakeReport", "bake_chapter"} <= set(bake_module.__all__)


def test_the_output_folder_is_the_source_folder_name_with_en_appended() -> None:
    assert output_dir_for(Path("/library/ch 01")) == Path("/library/ch 01_en")
    assert output_dir_for(Path("/library/scans")) == Path("/library/scans_en")


# -- AC-1: the counts, exactly ---------------------------------------------------


def test_the_preview_states_every_count_of_a_mixed_chapter_exactly(mixed_chapter: Path) -> None:
    with _open(mixed_chapter) as project:
        preview = preview_bake(project)

    assert preview == BakePreview(
        output_dir=mixed_chapter.with_name("scans_en"),
        page_count=6,
        total_lines=16,
        unreviewed=(_ref(0, 0), _ref(0, 3), _ref(2, 0), _ref(2, 3), _ref(4, 0)),
        failed=(_ref(0, 2), _ref(2, 2), _ref(4, 3)),
        overflowing=(_ref(0, 3), _ref(5, 3)),
    )


def test_the_output_folder_is_spelled_source_underscore_en_beside_the_source(
    mixed_chapter: Path,
) -> None:
    with _open(mixed_chapter) as project:
        preview = preview_bake(project)

    assert preview.output_dir == mixed_chapter.parent / "scans_en"


def test_page_count_counts_pages_without_regions_and_pages_never_read(mixed_chapter: Path) -> None:
    with _open(mixed_chapter) as project:
        assert preview_bake(project).page_count == 6


def test_total_lines_leaves_out_regions_whose_ocr_never_ran(mixed_chapter: Path) -> None:
    # p2's four regions have no line rows (`None`), and p4 has no regions.
    with _open(mixed_chapter) as project:
        assert preview_bake(project).total_lines == 16


def test_unreviewed_is_every_proposed_line_and_not_a_reverted_or_failed_one(
    mixed_chapter: Path,
) -> None:
    # (2,1) is `reverted` - a user act, not unreviewed. (0,2) is failed WITH a
    # proposal. (4,0)'s whitespace proposal is still `proposed`.
    with _open(mixed_chapter) as project:
        unreviewed = preview_bake(project).unreviewed

    assert unreviewed == (_ref(0, 0), _ref(0, 3), _ref(2, 0), _ref(2, 3), _ref(4, 0))


def test_failed_is_every_failed_line_in_page_then_reading_order(mixed_chapter: Path) -> None:
    with _open(mixed_chapter) as project:
        assert preview_bake(project).failed == (_ref(0, 2), _ref(2, 2), _ref(4, 3))


def test_the_unreviewed_count_agrees_with_what_bake_chapter_reports(mixed_chapter: Path) -> None:
    # C-1: one definition of unreviewed. No oracle: the two must agree.
    output_dir = world.output_dir_for(mixed_chapter)
    with _open(mixed_chapter) as project:
        preview = preview_bake(project)
        report = bake_chapter(project, output_dir)

    assert len(preview.unreviewed) == report.unreviewed_lines
    assert preview.page_count == report.pages_written


# -- AC-1: overflow is the lines bake_chapter would set that do not fit ----------


def _one_page(tmp_path: Path, specs: Sequence[Spec], *, cleaned: bool) -> Path:
    source_dir = _source(tmp_path, 1)
    _seed(source_dir, [(specs, cleaned)])
    return source_dir


_FITTING = [Spec(proposed="HELLO"), Spec(proposed="THERE"), Spec(proposed="OK!")]


def test_a_long_line_in_the_tiny_bubble_of_a_cleaned_page_overflows(tmp_path: Path) -> None:
    source_dir = _one_page(tmp_path, [*_FITTING, Spec(proposed=LONG)], cleaned=True)

    with _open(source_dir) as project:
        preview = preview_bake(project)

    assert preview.overflowing == (_ref(0, world.OVERFLOW),)


def test_a_short_line_in_a_roomy_bubble_does_not_overflow(tmp_path: Path) -> None:
    # Region 0 with "HELLO" fits (measured in RED). An implementation that calls
    # every set line overflowing reports (0,0), (0,1), (0,2) here.
    source_dir = _one_page(tmp_path, [*_FITTING, Spec(proposed="OK!")], cleaned=True)

    with _open(source_dir) as project:
        preview = preview_bake(project)

    assert preview.overflowing == ()
    assert _ref(0, 0) not in preview.overflowing


def test_a_line_on_an_uncleaned_page_never_overflows_because_it_is_never_baked(
    tmp_path: Path,
) -> None:
    source_dir = _one_page(tmp_path, [*_FITTING, Spec(proposed=LONG)], cleaned=False)

    with _open(source_dir) as project:
        preview = preview_bake(project)

    assert preview.overflowing == ()
    assert preview.unreviewed == (_ref(0, 0), _ref(0, 1), _ref(0, 2), _ref(0, 3))


def test_a_failed_line_is_failed_and_not_overflowing_however_long_its_proposal(
    tmp_path: Path,
) -> None:
    source_dir = _one_page(tmp_path, [*_FITTING, Spec(proposed=LONG, ocr_empty=True)], cleaned=True)

    with _open(source_dir) as project:
        preview = preview_bake(project)

    assert preview.failed == (_ref(0, world.OVERFLOW),)
    assert preview.overflowing == ()


def test_overflow_is_measured_on_the_edited_text_not_the_proposal(tmp_path: Path) -> None:
    source_dir = _one_page(
        tmp_path,
        [*_FITTING, Spec(proposed="OK", commit=("edited", LONG))],
        cleaned=True,
    )

    with _open(source_dir) as project:
        preview = preview_bake(project)

    assert preview.overflowing == (_ref(0, world.OVERFLOW),)
    assert preview.unreviewed == (_ref(0, 0), _ref(0, 1), _ref(0, 2))


# -- zero, one -------------------------------------------------------------------


def test_a_chapter_with_no_regions_previews_one_page_and_nothing_else(tmp_path: Path) -> None:
    source_dir = _source(tmp_path, 1)
    _seed(source_dir, [None])

    with _open(source_dir) as project:
        preview = preview_bake(project)

    assert preview == BakePreview(
        output_dir=tmp_path / "scans_en",
        page_count=1,
        total_lines=0,
        unreviewed=(),
        failed=(),
        overflowing=(),
    )


# -- C-1: it only reads ----------------------------------------------------------


def test_previewing_creates_no_output_folder_and_touches_no_source_file(
    mixed_chapter: Path,
) -> None:
    output_dir = mixed_chapter.parent / "scans_en"
    before = world.snapshot(mixed_chapter)

    with _open(mixed_chapter) as project:
        preview_bake(project)

    assert not output_dir.exists(), "preview_bake created the output folder"
    assert world.snapshot(mixed_chapter) == before
