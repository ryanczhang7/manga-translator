"""`mangatl.bench.recall`: matched, missed and spurious, per page and in total.

MT-023 AC-1, AC-2, AC-3 and AC-7 (for `measure_recall`), `## Contract` block 1.
Every criterion here is mechanical: constructed detections against a constructed
truth, exact counts, nothing tuned.

**The fixture** is `_s2_world`'s: a two-page chapter of 200 x 200 scans with
three 40 x 40 px truth regions each (1,600 px, inclusive corners), seeded from a
baseline project whose proposals are exactly their polygons. Every control
builds a fresh project of the same chapter and measures it against the same
`truth`. Each proposal's mask is exactly its rectangle, so a proposal at its own
place matches at IoU 1.0 and every other truth region at IoU 0. The bottom half
(y >= 100) is free for proposals that match nothing.

**The threshold is not restated.** The pairing is `bench.matching`'s; the 0.5
boundary cases below are built so that they are exact rectangle arithmetic
(800 / 1600 and 799 / 1600), and a source check asserts `recall.py` imports
the threshold and the matcher rather than carrying a copy.

**Timing.** AC-3's thousand spurious squares are the only large case; the
suite's wall time is in the story's handoff.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import _s2_world as w
import pytest

import mangatl.bench.recall as recall_module
from mangatl.bench.recall import PageRecall, RecallReport, measure_recall
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    validate,
)
from mangatl.domain.page import Chapter
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter

Detections = dict[int, list[RawRegion]]


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return w.write_chapter(tmp_path / w.CHAPTER)


@pytest.fixture
def chapter(folder: Path) -> Chapter:
    return read_chapter(folder)


@pytest.fixture
def truth(folder: Path, chapter: Chapter) -> GroundTruth:
    return w.seeded_truth(folder, chapter)


def _measure(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth, detections: Detections
) -> RecallReport:
    with w.project(tmp_path, chapter, detections) as project:
        return measure_recall(project, truth)


def _without(indices: tuple[int, ...]) -> list[RawRegion]:
    """The baseline page with the proposals for truth `indices` removed."""
    return [r for i, r in enumerate(w.baseline()) if i not in indices]


def _assert_page_sums(report: RecallReport) -> None:
    assert sum(p.matched for p in report.pages) == report.matched
    assert sum(p.spurious for p in report.pages) == report.spurious
    assert sum(len(p.missed) for p in report.pages) == len(report.missed)
    assert [(p.ordinal, i) for p in report.pages for i in p.missed] == list(report.missed)
    assert report.matched + len(report.missed) == report.ground_truth


# -- AC-1: the report's shape -------------------------------------------------


def test_ac1_a_page_breakdown_has_exactly_ordinal_matched_missed_and_spurious_in_order() -> None:
    assert [f.name for f in dataclasses.fields(PageRecall)] == [
        "ordinal",
        "matched",
        "missed",
        "spurious",
    ]


def test_ac1_the_report_has_exactly_these_six_fields_in_order() -> None:
    assert [f.name for f in dataclasses.fields(RecallReport)] == [
        "matched",
        "missed",
        "spurious",
        "ground_truth",
        "recall",
        "pages",
    ]


def test_ac1_the_report_and_its_page_breakdown_are_frozen(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, w.all_pages())

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.matched = 0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.pages[0].matched = 0  # type: ignore[misc]


def test_ac1_a_detection_of_every_region_reports_full_recall_with_every_count_and_each_page(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, w.all_pages())

    assert report == RecallReport(
        matched=6,
        missed=(),
        spurious=0,
        ground_truth=6,
        recall=1.0,
        pages=(
            PageRecall(ordinal=0, matched=3, missed=(), spurious=0),
            PageRecall(ordinal=1, matched=3, missed=(), spurious=0),
        ),
    )
    assert type(report.recall) is float


def test_ac1_the_per_page_breakdown_follows_the_truths_page_order_not_the_projects(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """One `PageRecall` per truth page, in truth page order: a truth listing its
    pages in reverse gets its breakdown in reverse."""
    reversed_truth = dataclasses.replace(truth, pages=tuple(reversed(truth.pages)))
    detections = {0: _without((1,)), 1: w.baseline()}

    report = _measure(tmp_path, chapter, reversed_truth, detections)

    assert [p.ordinal for p in report.pages] == [1, 0]
    assert report.pages == (
        PageRecall(ordinal=1, matched=3, missed=(), spurious=0),
        PageRecall(ordinal=0, matched=2, missed=(1,), spurious=0),
    )
    assert report.missed == ((0, 1),)


def test_ac1_recall_is_matched_over_ground_truth_on_a_non_trivial_run(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, {0: _without((2,)), 1: _without((0, 1))})

    assert (report.matched, report.ground_truth) == (3, 6)
    assert report.recall == pytest.approx(3 / 6, abs=1e-12)
    _assert_page_sums(report)


def test_ac1_a_project_with_no_detections_reports_zero_recall_and_every_region_missed(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, {})

    assert report == RecallReport(
        matched=0,
        missed=((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)),
        spurious=0,
        ground_truth=6,
        recall=0.0,
        pages=(
            PageRecall(ordinal=0, matched=0, missed=(0, 1, 2), spurious=0),
            PageRecall(ordinal=1, matched=0, missed=(0, 1, 2), spurious=0),
        ),
    )
    assert type(report.recall) is float


def test_ac1_a_truth_with_no_regions_reports_zero_recall_without_dividing_by_zero(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    empty = dataclasses.replace(
        truth, pages=tuple(dataclasses.replace(page, regions=()) for page in truth.pages)
    )
    assert validate(empty, chapter).ok  # a warning, not an error

    report = _measure(tmp_path, chapter, empty, w.all_pages())

    assert (report.matched, report.missed, report.spurious, report.ground_truth) == (0, (), 6, 0)
    assert report.recall == 0.0
    assert type(report.recall) is float
    assert [p.spurious for p in report.pages] == [3, 3]


def test_ac1_a_proposal_at_iou_exactly_one_half_matches(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Truth 0 is 40 x 40 = 1,600 px; the proposal is its top 40 x 20 = 800 px.
    IoU = 800 / 1600 = 0.5, and the comparison is >=."""
    x0, y0, x1, _ = w.TRUTH_RECTS[0]
    half = w.region(w.TRUTH_RECTS[0], [(x0, y0, x1, y0 + 19)])
    detections = {0: [half, *w.baseline()[1:]], 1: w.baseline()}

    report = _measure(tmp_path, chapter, truth, detections)

    assert (report.matched, report.missed, report.spurious) == (6, (), 0)


def test_ac1_a_proposal_just_below_iou_one_half_is_both_a_miss_and_a_spurious_detection(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """The top 40 x 19 = 760 px plus 39 px of the next row: 799 / 1600 < 0.5."""
    x0, y0, x1, _ = w.TRUTH_RECTS[0]
    short = w.region(w.TRUTH_RECTS[0], [(x0, y0, x1, y0 + 18), (x0, y0 + 19, x1 - 1, y0 + 19)])
    detections = {0: [short, *w.baseline()[1:]], 1: w.baseline()}

    report = _measure(tmp_path, chapter, truth, detections)

    assert (report.matched, report.missed, report.spurious) == (5, ((0, 0),), 1)
    assert report.pages[0] == PageRecall(ordinal=0, matched=2, missed=(0,), spurious=1)


def test_ac1_matching_reads_the_proposals_mask_so_a_region_in_the_wrong_place_is_not_matched(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Proposal 0 keeps its reading position and truth 0's polygon, but its mask
    sits in the empty bottom half. By mask IoU it is spurious and truth 0 is
    missed; by index, or by polygon, it would match."""
    misplaced = w.region(w.TRUTH_RECTS[0], [(10, 120, 49, 159)])
    detections = {0: [misplaced, *w.baseline()[1:]], 1: w.baseline()}

    report = _measure(tmp_path, chapter, truth, detections)

    assert (report.matched, report.missed, report.spurious) == (5, ((0, 0),), 1)
    assert report.recall == pytest.approx(5 / 6, abs=1e-12)


def test_ac1_recall_imports_the_threshold_and_the_matcher_and_defines_neither() -> None:
    """Contract block 1: one threshold, one matcher, imported from
    `bench.matching`; and `recall` is computed here, never read from
    `bench.acceptance`. A source check, as MT-022 checks its own imports."""
    tree = ast.parse(Path(inspect.getfile(recall_module)).read_text("utf-8"))

    def imports(module: str, name: str) -> bool:
        return any(
            isinstance(node, ast.ImportFrom)
            and node.module == module
            and any(alias.name == name for alias in node.names)
            for node in ast.walk(tree)
        )

    assert imports("mangatl.bench.matching", "IOU_MATCH_THRESHOLD")
    assert imports("mangatl.bench.matching", "match_regions")
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert not defined & {"match_regions", "iou", "polygon_mask", "decode_mask"}
    module_level = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }
    assert not any("THRESHOLD" in name or name.startswith("IOU") for name in module_level)
    assert not any(
        isinstance(node, ast.Constant) and node.value == 0.5 for node in ast.walk(tree)
    ), "recall.py spells the matching threshold as a literal"
    assert not any(
        isinstance(node, ast.ImportFrom | ast.Import)
        and (
            getattr(node, "module", None) == "mangatl.bench.acceptance"
            or any(alias.name == "mangatl.bench.acceptance" for alias in node.names)
        )
        for node in ast.walk(tree)
    ), "recall.py reads its numbers from bench.acceptance"


# -- AC-2: a missed region is counted and its page named -----------------------


def test_ac2_an_undetected_region_is_missed_and_named_by_page_ordinal_and_truth_index(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, {0: _without((2,)), 1: _without((0,))})

    assert report.missed == ((0, 2), (1, 0))
    assert report.pages[0] == PageRecall(ordinal=0, matched=2, missed=(2,), spurious=0)
    assert report.pages[1] == PageRecall(ordinal=1, matched=2, missed=(0,), spurious=0)
    assert (report.matched, report.spurious, report.ground_truth) == (4, 0, 6)
    _assert_page_sums(report)


def test_ac2_missed_regions_are_listed_in_page_order_then_index_order_whatever_the_reading_order(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Proposals stored in reverse reading order; page 1 misses 0 and 2, page 0 misses 1."""
    detections = {
        0: list(reversed(_without((1,)))),
        1: list(reversed(_without((0, 2)))),
    }

    report = _measure(tmp_path, chapter, truth, detections)

    assert report.missed == ((0, 1), (1, 0), (1, 2))
    assert report.pages[1].missed == (0, 2)
    _assert_page_sums(report)


def test_ac2_a_detection_elsewhere_on_the_page_does_not_stand_in_for_a_missed_region(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Page 0 has no detection of region 1 and one detection in the empty bottom
    half, IoU 0 with everything: region 1 is missed and the stray is spurious,
    never paired with each other."""
    detections = {0: [*_without((1,)), w.region((10, 120, 49, 159))], 1: w.baseline()}

    report = _measure(tmp_path, chapter, truth, detections)

    assert report.missed == ((0, 1),)
    assert report.pages[0] == PageRecall(ordinal=0, matched=2, missed=(1,), spurious=1)
    assert (report.matched, report.spurious) == (5, 1)


def test_ac2_a_page_with_no_detections_at_all_names_every_region_on_that_page_only(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, {0: w.baseline()})

    assert report.missed == ((1, 0), (1, 1), (1, 2))
    assert report.pages[0] == PageRecall(ordinal=0, matched=3, missed=(), spurious=0)
    assert report.pages[1] == PageRecall(ordinal=1, matched=0, missed=(0, 1, 2), spurious=0)
    assert report.recall == pytest.approx(3 / 6, abs=1e-12)


# -- AC-3: a spurious detection is counted and never enters recall -------------


def test_ac3_a_detection_matching_no_region_is_spurious_on_its_page(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    detections = w.all_pages()
    detections[1] = [*w.regions(w.spurious_rects(2)), *detections[1]]

    report = _measure(tmp_path, chapter, truth, detections)

    assert (report.matched, report.missed, report.spurious) == (6, (), 2)
    assert [p.spurious for p in report.pages] == [0, 2]
    assert report.recall == 1.0


def test_ac3_control_a_thousand_spurious_detections_leave_recall_and_matched_exactly_unchanged(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """A detector that emits a thousand boxes must not score 100% recall
    unremarked: the boxes are counted, and recall - with a miss present, so it is
    not the trivial 1.0 - does not move. The phantoms come first in reading order,
    so every real region's index shifts by 1,000."""
    detections = {0: _without((1,)), 1: w.baseline()}
    before = _measure(tmp_path, chapter, truth, detections)
    detections[0] = [*w.regions(w.spurious_rects(1000)), *detections[0]]

    after = _measure(tmp_path, chapter, truth, detections)

    assert after.spurious == 1000
    assert [p.spurious for p in after.pages] == [1000, 0]
    assert after.recall == before.recall == pytest.approx(5 / 6, abs=1e-12)
    assert (after.matched, after.missed) == (before.matched, before.missed) == (5, ((0, 1),))
    _assert_page_sums(after)


# -- AC-7: refusals ------------------------------------------------------------


def test_ac7_a_development_use_truth_reaching_measure_recall_directly_is_refused_naming_it(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused before anything is measured: reading a page's regions would fail."""
    flagged = w.flagged(tmp_path, truth)
    with w.project(tmp_path, chapter, w.all_pages()) as project:
        monkeypatch.setattr(type(project), "read_regions", w.boom)
        with pytest.raises(BenchmarkChapterUsedInDevelopment) as refused:
            measure_recall(project, flagged)

    assert w.CHAPTER in str(refused.value)


def test_ac7_a_truth_failing_its_validator_is_refused_with_every_error_line(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    loaded = w.stale(tmp_path, truth)
    errors = validate(loaded, chapter).errors
    assert len(errors) == 2

    with (
        w.project(tmp_path, chapter, w.all_pages()) as project,
        pytest.raises(InvalidGroundTruth) as refused,
    ):
        measure_recall(project, loaded)

    assert all(error in str(refused.value) for error in errors), (errors, str(refused.value))


def test_ac7_the_validators_warnings_do_not_stop_a_measurement(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = validate(truth, chapter)
    assert report.ok and report.warnings  # the seeded truth is all seed: it warns

    assert _measure(tmp_path, chapter, truth, w.all_pages()).recall == 1.0
