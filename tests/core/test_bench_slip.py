"""MT-150: `mangatl.bench.slip` - neighbouring regions that received identical
English from different Japanese (a "slip").

`## Contract` C-1 and C-2. Every criterion is **mechanical** (the story's oracle
partition): the pairs are pinned as exact tuples, the rendered lines byte for
byte. There is no threshold and no invented metric.

**The fixture is a real project on `tmp_path`**, built through the store's own
writers (`write_regions`, `write_lines`, `write_proposed`, `set_excluded`,
`commit_line`) - never by raw SQL - so `count_slips` reads exactly what the
pipeline and the review screen would have left there. Each page is described
as a list of `_R` (one region: its Japanese, its proposal, and whatever else
happened to it); an `int` instead of a list is a page with that many regions
whose OCR has not run, which `read_review_lines` reads back as `None` entries.

**The negative controls** are AC-2, AC-3 and AC-4's skipped regions, plus the
normalisation and AC-6 cases. Each is arranged so that one plausible wrong
implementation reports a pair the right one does not (the handoff lists them,
with the value each expects):

- ignores the Japanese                       -> AC-2 repeated dialogue
- compares Japanese un-normalised            -> whitespace / NFD Japanese
- compares English un-normalised             -> (the positive side) misses a slip
- counts empty English                       -> two empty proposals
- compares non-neighbours / across pages     -> AC-3
- does not skip excluded / unproposed lines  -> AC-4, the skipped region's own English
- reads `final_en`                           -> AC-6, both directions

**Timing.** No `pytest-timeout` in this project and no per-test budget: every
test builds one chapter of at most three 30 x 20 pages with one 4 x 4 mask,
encoded once per test.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

import mangatl.bench.slip as slip
from mangatl.bench.slip import SlipReport, count_slips, render
from mangatl.domain.line import OcrResult
from mangatl.domain.region import ExclusionReason, RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.lines import commit_line, read_review_lines
from mangatl.store.project import Project, create_project, project_dir_for

_HEADER = "slips (identical English, different Japanese)"

_RING = ((0, 0), (4, 0), (4, 4), (0, 4), (0, 0))

#: Copy A's p017 Japanese (MT-150 `## Context`).
_TSU = "っ"
_ITAI = "いてーよー\uff01\uff01"  # two FULLWIDTH EXCLAMATION MARKs, as OCR read them
_BATTLEFIELD = "戦場だぞ"


@dataclasses.dataclass(frozen=True)
class _R:
    """One region of a page, as the pipeline and the reviewer left it.

    `en` is `proposed_en` (`None`: never proposed); `misaligned` flags it the way
    MT-149 does (this run's answer dropped). A misaligned region with `en` set
    is the re-run case (D-3): `en` is written by an *earlier* `write_proposed`,
    then the flagging call names it in `misaligned`, so it keeps that stale
    English with `misaligned = 1`. `excluded` removes it from translation;
    `final` is a reviewer's edit committed over it (`final_en`).
    """

    ja: str
    en: str | None
    excluded: ExclusionReason | None = None
    misaligned: bool = False
    final: str | None = None
    ocr_empty: bool = False


#: A page: its regions, or the number of regions on a page whose OCR has not run.
_Page = Sequence[_R] | int

Build = Callable[[Sequence[_Page]], Project]


def _distinct(count: int) -> list[_R]:
    """`count` regions whose Japanese and English are all different."""
    return [_R(f"せりふ{i}", f"Line number {i}.") for i in range(count)]


@pytest.fixture
def build(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> Iterator[Build]:
    """A builder: `build([page, ...])` -> the project, open, with those pages."""
    opened: list[Project] = []
    mask = one_bit_png(30, 20, [(0, 0, 4, 4)])
    region = RawRegion(polygon=_RING, mask=mask, confidence=0.9, kind="bubble")

    def _build(pages: Sequence[_Page]) -> Project:
        source = tmp_path / "scans"
        source.mkdir()
        for ordinal in range(len(pages)):
            (source / f"{ordinal + 1:03d}.png").write_bytes(png_bytes(30, 20))
        project = create_project(read_chapter(source), project_dir_for(source))
        opened.append(project)
        for ordinal, page in enumerate(pages):
            if isinstance(page, int):
                project.write_regions(ordinal, [region] * page)
                continue
            if not page:
                continue
            project.write_regions(ordinal, [region] * len(page))
            project.write_lines(ordinal, [OcrResult(r.ja, ocr_empty=r.ocr_empty) for r in page])
            stale = {i: r.en for i, r in enumerate(page) if r.en is not None and r.misaligned}
            if stale:
                project.write_proposed(ordinal, stale)  # the earlier run
            project.write_proposed(
                ordinal,
                {i: r.en for i, r in enumerate(page) if r.en is not None and not r.misaligned},
                misaligned=[i for i, r in enumerate(page) if r.misaligned],
            )
            for index, r in enumerate(page):
                if r.final is not None:
                    commit_line(project, ordinal, index, r.final, "edited")
            for index, r in enumerate(page):
                if r.excluded is not None:
                    project.set_excluded(ordinal, index, r.excluded)
        return project

    yield _build
    for project in opened:
        project.__exit__(None, None, None)


def _pairs(project: Project) -> tuple[tuple[int, int, int], ...]:
    report = count_slips(project)
    assert isinstance(report, SlipReport), report
    return report.pairs


# -- the module's shape (C-1) ----------------------------------------------------


def test_the_module_exports_exactly_slipreport_count_slips_and_render() -> None:
    assert slip.__all__ == ["SlipReport", "count_slips", "render"]


def test_a_slip_report_is_a_frozen_value_holding_its_pairs() -> None:
    report = SlipReport(pairs=((17, 4, 5),))

    assert report.pairs == ((17, 4, 5),)
    assert report == SlipReport(pairs=((17, 4, 5),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.pairs = ()  # type: ignore[misc]


def test_count_slips_returns_its_pairs_as_a_tuple_of_integer_triples(build: Build) -> None:
    project = build([[_R(_TSU, "WEE"), _R(_ITAI, "WEE")]])

    report = count_slips(project)

    assert type(report) is SlipReport
    assert type(report.pairs) is tuple
    assert all(type(pair) is tuple for pair in report.pairs), report.pairs
    assert report.pairs == ((0, 0, 1),)


# -- AC-1: identical English, different Japanese, neighbours ---------------------


def test_ac1_two_neighbours_with_the_same_english_from_different_japanese_are_one_slip(
    build: Build,
) -> None:
    project = build([[_R(_TSU, "WEE"), _R(_ITAI, "WEE")]])

    assert _pairs(project) == ((0, 0, 1),)


def test_ac1_copy_a_p017_reports_regions_4_5_and_6_7_on_their_own_page_ordinal(
    build: Build,
) -> None:
    """Copy A's slip, on the third page so the ordinal is not confused with an
    index: 4/5 "WEE" for `っ` and `_ITAI`, 6/7 "It hurts!!" for
    `_ITAI` and the battlefield line. A page with no regions sits between."""
    p017 = [
        *_distinct(4),
        _R(_TSU, "WEE"),
        _R(_ITAI, "WEE"),
        _R(_ITAI, "It hurts!!"),
        _R(_BATTLEFIELD, "It hurts!!"),
        _R("最後", "The last line."),
    ]
    project = build([_distinct(2), [], p017])

    assert _pairs(project) == ((2, 4, 5), (2, 6, 7))
    assert render(count_slips(project)) == [
        f"{_HEADER}  2",
        "page 2 regions 4/5, page 2 regions 6/7",
    ]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("It  hurts!! ", " It hurts!!"),
        ("It hurts!!", "It\u3000hurts!!"),
        ("Cafe\u0301!", "Café!"),
    ],
    ids=["spaces", "ideographic-space", "nfd-accent"],
)
def test_ac1_english_is_compared_in_its_o2_normalised_form(
    build: Build, first: str, second: str
) -> None:
    assert first != second, "fixture: the raw strings must differ"
    project = build([[_R(_TSU, first), _R(_ITAI, second)]])

    assert _pairs(project) == ((0, 0, 1),)


def test_ac1_three_regions_in_a_row_with_one_english_and_three_japanese_are_two_pairs(
    build: Build,
) -> None:
    project = build([[_R(_TSU, "WEE"), _R(_ITAI, "WEE"), _R(_BATTLEFIELD, "WEE")]])

    assert _pairs(project) == ((0, 0, 1), (0, 1, 2))


def test_ac1_pairs_are_ordered_by_page_ordinal_then_first_reading_index(build: Build) -> None:
    page0 = [*_distinct(2), _R(_TSU, "WEE"), _R(_ITAI, "WEE")]
    page1 = [_R(_ITAI, "Ow."), _R(_BATTLEFIELD, "Ow."), _R("最後", "Fine.")]
    page2 = [
        _R("一", "Go."),
        _R("二", "Stop."),
        _R("三", "Stop."),
        _R("四", "Go."),
        _R("五", "Go."),
    ]
    project = build([page0, page1, page2])

    assert _pairs(project) == ((0, 2, 3), (1, 0, 1), (2, 1, 2), (2, 3, 4))


def test_ac1_a_page_with_no_slip_reports_no_pairs(build: Build) -> None:
    project = build([_distinct(5)])

    assert _pairs(project) == ()
    assert render(count_slips(project)) == [f"{_HEADER}  0"]


# -- AC-2: repeated dialogue is not a slip (control) -----------------------------


def test_ac2_copy_b_repeated_dialogue_with_identical_japanese_is_not_a_slip(
    build: Build,
) -> None:
    """Copy B: `_ITAI` -> "It huuurts!!" twice. An implementation that
    ignores the Japanese reports `(0, 0, 1)`."""
    project = build([[_R(_ITAI, "It huuurts!!"), _R(_ITAI, "It huuurts!!")]])

    assert _pairs(project) == ()


def test_ac2_repeated_dialogue_is_passed_over_while_a_real_slip_beside_it_is_reported(
    build: Build,
) -> None:
    project = build(
        [
            [
                _R(_ITAI, "It huuurts!!"),
                _R(_ITAI, "It huuurts!!"),
                _R(_TSU, "WEE"),
                _R(_BATTLEFIELD, "WEE"),
            ]
        ]
    )

    assert _pairs(project) == ((0, 2, 3),)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (_ITAI, f"{_ITAI} "),
        ("いてー よー", "いてー\u3000よー"),
        ("が", "か\u3099"),
    ],
    ids=["trailing-space", "ideographic-space", "nfd-dakuten"],
)
def test_ac2_japanese_is_compared_in_its_o2_normalised_form_so_equal_japanese_is_no_slip(
    build: Build, first: str, second: str
) -> None:
    """An implementation comparing the raw `source_ja` reports `(0, 0, 1)`."""
    assert first != second, "fixture: the raw strings must differ"
    project = build([[_R(first, "It huuurts!!"), _R(second, "It huuurts!!")]])

    assert _pairs(project) == ()


def test_ac2_two_regions_whose_ocr_read_nothing_have_equal_japanese_and_are_no_slip(
    build: Build,
) -> None:
    project = build([[_R("", "...", ocr_empty=True), _R("", "...", ocr_empty=True)]])

    assert _pairs(project) == ()


# -- AC-3: neighbours only (control) ---------------------------------------------


def test_ac3_equal_english_from_different_japanese_two_regions_apart_is_not_a_slip(
    build: Build,
) -> None:
    project = build([[_R(_TSU, "WEE"), _R(_ITAI, "Ow."), _R(_BATTLEFIELD, "WEE")]])

    assert _pairs(project) == ()


def test_ac3_equal_english_from_different_japanese_across_a_page_break_is_not_a_slip(
    build: Build,
) -> None:
    """The last region of page 0 and the first of page 1."""
    project = build(
        [
            [_R("一", "Go."), _R(_TSU, "WEE")],
            [_R(_ITAI, "WEE"), _R("二", "Stop.")],
        ]
    )

    assert _pairs(project) == ()


@pytest.mark.parametrize(
    ("first", "second"),
    [("", ""), ("", " "), ("  ", "\u3000")],
    ids=["both-empty", "empty-and-space", "whitespace-only"],
)
def test_ac3_two_neighbours_proposed_empty_english_are_not_a_slip(
    build: Build, first: str, second: str
) -> None:
    """An empty proposal (raw or after O2) is equal to every other empty one; an
    implementation that does not refuse `""` reports `(0, 0, 1)`."""
    project = build([[_R(_TSU, first), _R(_ITAI, second)]])

    assert _pairs(project) == ()


# -- AC-4: excluded and unproposed regions are skipped ---------------------------


def test_ac4_an_excluded_region_between_two_equal_neighbours_makes_them_neighbours_4_6(
    build: Build,
) -> None:
    """Region 5 is excluded and carries the same English from its own Japanese:
    an implementation that does not skip it reports `4/5, 5/6` instead."""
    page = [
        *_distinct(4),
        _R(_TSU, "WEE"),
        _R(_BATTLEFIELD, "WEE", excluded="watermark"),
        _R(_ITAI, "WEE"),
    ]
    project = build([page])
    excluded = read_review_lines(project, 0)[5]
    assert excluded is not None and excluded.excluded == "watermark", excluded
    assert excluded.proposed_en == "WEE", "fixture: the excluded region keeps its English"

    assert _pairs(project) == ((0, 4, 6),)
    assert render(count_slips(project)) == [f"{_HEADER}  1", "page 0 regions 4/6"]


@pytest.mark.parametrize("reason", ["watermark", "user", "art"])
def test_ac4_an_excluded_region_is_never_half_of_a_pair(
    build: Build, reason: ExclusionReason
) -> None:
    project = build([[_R(_TSU, "WEE", excluded=reason), _R(_ITAI, "WEE")]])

    assert _pairs(project) == ()


@pytest.mark.parametrize("misaligned", [False, True], ids=["never-proposed", "misaligned"])
def test_ac4_a_region_with_no_proposal_between_two_equal_neighbours_makes_them_neighbours(
    build: Build, misaligned: bool
) -> None:
    project = build(
        [[_R(_TSU, "WEE"), _R(_BATTLEFIELD, None, misaligned=misaligned), _R(_ITAI, "WEE")]]
    )
    middle = read_review_lines(project, 0)[1]
    assert middle is not None and middle.proposed_en is None, middle
    assert middle.misaligned is misaligned, middle

    assert _pairs(project) == ((0, 0, 2),)


def _assert_stale(project: Project, index: int, english: str) -> None:
    """Fixture check: region `index` of page 0 is misaligned AND still holds `english`."""
    line = read_review_lines(project, 0)[index]
    assert line is not None, "fixture: the region has a line"
    assert line.misaligned is True, line
    assert line.proposed_en == english, ("fixture: the earlier run's English survives", line)


def test_d3_a_misaligned_region_holding_stale_english_is_never_half_of_a_pair(
    build: Build,
) -> None:
    """D-3: region 1 kept "WEE" from an earlier run when this run flagged it
    misaligned. An implementation that skips only `proposed_en is None` reports
    `(0, 0, 1)`."""
    project = build([[_R(_TSU, "WEE"), _R(_ITAI, "WEE", misaligned=True)]])
    _assert_stale(project, 1, "WEE")

    assert _pairs(project) == ()


def test_d3_a_misaligned_region_with_stale_english_between_two_equal_neighbours_bridges_them(
    build: Build,
) -> None:
    """D-3, as the excluded case: region 5 is misaligned and still says "WEE" from
    its own Japanese. Not skipping it gives `4/5, 5/6`; skipping it gives `4/6`."""
    page = [
        *_distinct(4),
        _R(_TSU, "WEE"),
        _R(_BATTLEFIELD, "WEE", misaligned=True),
        _R(_ITAI, "WEE"),
    ]
    project = build([page])
    _assert_stale(project, 5, "WEE")

    assert _pairs(project) == ((0, 4, 6),)
    assert render(count_slips(project)) == [f"{_HEADER}  1", "page 0 regions 4/6"]


def test_ac4_a_page_whose_ocr_has_not_run_and_a_page_with_no_regions_are_passed_over(
    build: Build,
) -> None:
    project = build([3, [], [_R(_TSU, "WEE"), _R(_ITAI, "WEE")]])
    assert read_review_lines(project, 0) == (None, None, None), "fixture: OCR has not run"
    assert read_review_lines(project, 1) == (), "fixture: no regions"

    assert _pairs(project) == ((2, 0, 1),)


def test_ac4_a_chapter_with_nothing_proposed_anywhere_reports_no_slip(build: Build) -> None:
    project = build([2, [], [_R(_TSU, None), _R(_ITAI, None)]])

    assert _pairs(project) == ()
    assert render(count_slips(project)) == [f"{_HEADER}  0"]


# -- AC-6: the pipeline's proposal, never the reviewer's final text --------------


def test_ac6_a_slip_the_reviewer_fixed_by_hand_is_still_the_pipelines_slip(
    build: Build,
) -> None:
    """Both regions' `final_en` differ; their proposals are the slip."""
    project = build(
        [
            [
                _R(_TSU, "WEE", final="Ngh!"),
                _R(_ITAI, "WEE", final="It hurts!!"),
            ]
        ]
    )
    lines = read_review_lines(project, 0)
    assert [line.final_en for line in lines if line] == ["Ngh!", "It hurts!!"]

    assert _pairs(project) == ((0, 0, 1),)


def test_ac6_two_lines_made_equal_only_by_the_reviewers_final_text_are_not_a_slip(
    build: Build,
) -> None:
    project = build(
        [
            [
                _R(_TSU, "Ngh!", final="It hurts!!"),
                _R(_ITAI, "It hurts!!", final="It hurts!!"),
            ]
        ]
    )
    lines = read_review_lines(project, 0)
    assert [line.final_en for line in lines if line] == ["It hurts!!", "It hurts!!"]

    assert _pairs(project) == ()


# -- C-2: the rendered lines -----------------------------------------------------


def test_c2_no_pairs_render_as_one_line_with_two_spaces_before_the_zero() -> None:
    assert render(SlipReport(pairs=())) == ["slips (identical English, different Japanese)  0"]


def test_c2_one_pair_renders_the_count_and_the_page_and_both_reading_indices() -> None:
    assert render(SlipReport(pairs=((0, 4, 6),))) == [
        "slips (identical English, different Japanese)  1",
        "page 0 regions 4/6",
    ]


def test_c2_two_pairs_render_on_one_second_line_joined_by_a_comma_and_a_space() -> None:
    assert render(SlipReport(pairs=((17, 4, 5), (17, 6, 7)))) == [
        "slips (identical English, different Japanese)  2",
        "page 17 regions 4/5, page 17 regions 6/7",
    ]


def test_c2_pairs_render_in_the_reports_own_order_as_stored_not_renumbered() -> None:
    assert render(SlipReport(pairs=((3, 10, 12), (1, 0, 1), (0, 0, 1)))) == [
        "slips (identical English, different Japanese)  3",
        "page 3 regions 10/12, page 1 regions 0/1, page 0 regions 0/1",
    ]
