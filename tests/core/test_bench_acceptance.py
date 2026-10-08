"""`mangatl.bench.acceptance`: S1b, S1a, recall and spurious, with their controls.

MT-022, every acceptance criterion and `## Contract` block 2. The metric, its
two numbers, the identity `S1b = S1a x recall` and the five negative controls
are settled in `docs/wiki/stack.md` §5/O2; this file reads their required values
out and designs none of them.

**The fixture.** A two-page chapter in `tmp_path/chapter-one`, both pages
200 x 200 PNGs (white and off-white, so their sha256 differ). Each page carries
ten regions, `_TRUTH_RECTS`: 30 x 30 squares (31 x 31 px, Pillow's polygon fill is
inclusive) on a 5 x 2 grid in the top 81 rows, separated by 9 px or more. Every
mask is exactly its polygon's pixels, so a proposal at its own place matches its
truth region at IoU 1.0 and every other truth region at IoU 0.

The **baseline** project (`project_dir_for(folder)`) stores all twenty, each with
an OCR line, a proposal `_proposal(ordinal, i)` and a committed final equal to
it. The ground truth is `seed_ground_truth` of that project, loaded back with
`load_ground_truth` - and it is the **constant**: every control builds a fresh
project of the same chapter (`_project`) and measures it against the same
`truth`. The bottom half of each page (y >= 100) is free for regions that match
nothing: AC-9's 1,000 spurious 2 x 2 squares, and the misplaced/extra regions of
the IoU and AC-4 cases.

Proposals are pairwise distinct after `normalise`, contain a composed `é` (so NFD
changes them), interior spaces (so doubling them changes them) and end in `.`
(so AC-6's `.` -> `!` changes every one).

**Timing.** No `pytest-timeout` in this project and no per-test budget. AC-9 is
the only large case; its wall time against a throwaway candidate is recorded in
the story's handoff.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import itertools
import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import _bake_world as world
import pytest

import mangatl.bench.acceptance as acceptance_module
from mangatl.bench.acceptance import AcceptanceReport, main, measure
from mangatl.bench.seed import seed_ground_truth
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    dump_ground_truth,
    load_ground_truth,
    truth_path_for,
    validate,
)
from mangatl.domain.line import OcrResult, normalise
from mangatl.domain.page import Chapter
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.lines import commit_line
from mangatl.store.project import Project, create_project, open_project, project_dir_for

_W, _H = 200, 200
_CHAPTER = "chapter-one"
_PAGES = (("001.png", (255, 255, 255)), ("002.png", (250, 250, 250)))
_PER_PAGE = 10
_GROUND_TRUTH = 2 * _PER_PAGE

#: `(x0, y0, x1, y1)` polygon corners, inclusive: ten 31 x 31 px squares.
_TRUTH_RECTS: tuple[tuple[int, int, int, int], ...] = tuple(
    (5 + 39 * c, 5 + 45 * r, 35 + 39 * c, 35 + 45 * r) for r in range(2) for c in range(5)
)


def _spurious_rects(count: int) -> list[tuple[int, int, int, int]]:
    """`count` 2 x 2 px squares in the bottom half (y >= 100): IoU 0 with every truth region."""
    assert count <= 1000
    return [
        (4 * (k % 50), 100 + 5 * (k // 50), 4 * (k % 50) + 1, 101 + 5 * (k // 50))
        for k in range(count)
    ]


def _proposal(ordinal: int, index: int) -> str:
    return f"The café on street {10 * ordinal + index} is open."


@dataclass(frozen=True)
class Spot:
    """One stored region: where it is, what was proposed, what was committed.

    `final is None` commits nothing (the line shows its proposal);
    `proposal is None` leaves the line untranslated.
    """

    rect: tuple[int, int, int, int]
    proposal: str | None
    final: str | None


def _baseline(ordinal: int) -> list[Spot]:
    return [
        Spot(rect, _proposal(ordinal, i), _proposal(ordinal, i))
        for i, rect in enumerate(_TRUTH_RECTS)
    ]


def _with_finals(ordinal: int, finals: Mapping[int, str]) -> list[Spot]:
    """The baseline page with the committed finals at `finals`' indices replaced."""
    return [
        dataclasses.replace(spot, final=finals[i]) if i in finals else spot
        for i, spot in enumerate(_baseline(ordinal))
    ]


def _regions(rects: Iterable[tuple[int, int, int, int]]) -> list[RawRegion]:
    """Regions whose masks are exactly their polygons' (inclusive) pixels."""
    return [
        RawRegion(
            polygon=world.ring(x0, y0, x1, y1),
            mask=world.mask_png(_W, _H, [(x0, y0, x1 + 1, y1 + 1)]),
            confidence=0.9,
            kind="bubble",
        )
        for x0, y0, x1, y1 in rects
    ]


def _store(project: Project, ordinal: int, spots: Sequence[Spot]) -> None:
    """Detection, OCR, translation and review for one page, by the routes the app uses."""
    project.write_regions(ordinal, _regions(s.rect for s in spots))
    project.write_lines(ordinal, [OcrResult(f"せりふ{i}") for i in range(len(spots))])
    project.write_proposed(
        ordinal, {i: s.proposal for i, s in enumerate(spots) if s.proposal is not None}
    )
    for i, s in enumerate(spots):
        if s.final is not None:
            status = "accepted" if s.final == s.proposal else "edited"
            commit_line(project, ordinal, i, s.final, status)


@pytest.fixture
def folder(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    source = tmp_path / _CHAPTER
    source.mkdir()
    for filename, rgb in _PAGES:
        (source / filename).write_bytes(png_bytes(_W, _H, rgb))
    return source


@pytest.fixture
def chapter(folder: Path) -> Chapter:
    return read_chapter(folder)


@pytest.fixture
def truth(folder: Path, chapter: Chapter) -> GroundTruth:
    """The baseline project at `project_dir_for(folder)`, and its seeded truth, loaded."""
    with create_project(chapter, project_dir_for(folder)) as project:
        for ordinal in range(len(_PAGES)):
            _store(project, ordinal, _baseline(ordinal))
        seed_ground_truth(project, truth_path_for(folder))
    return load_ground_truth(truth_path_for(folder))


_made = itertools.count()


def _project(tmp_path: Path, chapter: Chapter, pages: Mapping[int, Sequence[Spot]]) -> Project:
    """A fresh project of the same chapter, open; pages not named have no regions."""
    project = create_project(chapter, tmp_path / f"control-{next(_made)}.mtproj")
    for ordinal, spots in pages.items():
        _store(project, ordinal, spots)
    return project


def _measure(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth, pages: Mapping[int, Sequence[Spot]]
) -> AcceptanceReport:
    with _project(tmp_path, chapter, pages) as project:
        return measure(project, truth)


def _all(build: Callable[[int], list[Spot]]) -> dict[int, list[Spot]]:
    return {ordinal: build(ordinal) for ordinal in range(len(_PAGES))}


def _baseline_report(tmp_path: Path, chapter: Chapter, truth: GroundTruth) -> AcceptanceReport:
    return _measure(tmp_path, chapter, truth, _all(_baseline))


def _counts(report: AcceptanceReport) -> tuple[int, int, int, int, int]:
    return (report.accepted, report.proposed, report.matched, report.spurious, report.ground_truth)


def _drop(spots: Sequence[Spot], indices: Iterable[int]) -> list[Spot]:
    gone = set(indices)
    return [s for i, s in enumerate(spots) if i not in gone]


# -- AC-1: the report, every field, every run ---------------------------------


def test_ac1_the_report_has_exactly_these_eight_fields_in_order_and_no_validity_flag() -> None:
    assert [f.name for f in dataclasses.fields(AcceptanceReport)] == [
        "s1b",
        "s1a",
        "recall",
        "accepted",
        "proposed",
        "matched",
        "spurious",
        "ground_truth",
    ]


def test_ac1_the_report_is_frozen(tmp_path: Path, chapter: Chapter, truth: GroundTruth) -> None:
    report = _baseline_report(tmp_path, chapter, truth)

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.s1b = 0.5  # type: ignore[misc]


def test_ac1_the_baseline_reports_s1b_s1a_and_recall_at_one_with_every_count(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _baseline_report(tmp_path, chapter, truth)

    assert report == AcceptanceReport(
        s1b=1.0,
        s1a=1.0,
        recall=1.0,
        accepted=20,
        proposed=20,
        matched=20,
        spurious=0,
        ground_truth=20,
    )


def _is_number(value: object) -> bool:
    return type(value) is float and not math.isnan(value)


def test_ac1_a_project_with_no_regions_reports_zero_on_all_three_numbers_and_does_not_raise(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, {})

    assert _counts(report) == (0, 0, 0, 0, 20)
    assert (report.s1b, report.s1a, report.recall) == (0.0, 0.0, 0.0)
    assert all(_is_number(x) for x in (report.s1b, report.s1a, report.recall))


def test_ac1_a_truth_with_no_regions_reports_zero_s1b_and_recall_and_does_not_raise(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    empty = dataclasses.replace(
        truth, pages=tuple(dataclasses.replace(page, regions=()) for page in truth.pages)
    )
    assert validate(empty, chapter).ok  # a warning, not an error

    report = _measure(tmp_path, chapter, empty, _all(_baseline))

    assert _counts(report) == (0, 20, 0, 20, 0)
    assert (report.s1b, report.s1a, report.recall) == (0.0, 0.0, 0.0)
    assert all(_is_number(x) for x in (report.s1b, report.s1a, report.recall))


def test_ac1_a_matched_region_with_no_line_or_no_proposal_is_not_accepted(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Contract block 2: a `None` line, or `proposed_en is None`, is not accepted.

    Page 0's region 9 is stored after OCR ran on 0..8, so it has no `line` row;
    page 1's region 4 has a line and no proposal.
    """
    page1 = _baseline(1)
    page1[4] = Spot(page1[4].rect, None, None)
    with _project(tmp_path, chapter, {0: _baseline(0)[:9], 1: page1}) as project:
        project.write_regions(0, _regions(_TRUTH_RECTS))  # region 9: no OCR, no line
        report = measure(project, truth)

    assert _counts(report) == (18, 20, 20, 0, 20)
    assert report.s1b == pytest.approx(0.9, abs=1e-12)


def test_matching_is_by_mask_iou_so_a_region_in_the_wrong_place_is_spurious_not_matched(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Contract, settled: IoU >= IOU_MATCH_THRESHOLD, never by index.

    Page 0's region 0 keeps its reading index and its unedited line but sits in
    the empty bottom half. By IoU it is spurious and truth 0 is missed; by index
    it would pair with truth 0 and score an acceptance.
    """
    page0 = _baseline(0)
    page0[0] = dataclasses.replace(page0[0], rect=(5, 120, 35, 150))

    report = _measure(tmp_path, chapter, truth, {0: page0, 1: _baseline(1)})

    assert _counts(report) == (19, 20, 19, 1, 20)
    assert report.recall == pytest.approx(19 / 20, abs=1e-12)
    assert report.s1b == pytest.approx(19 / 20, abs=1e-12)
    assert report.s1a == pytest.approx(19 / 20, abs=1e-12)


def test_the_predicate_is_the_imported_is_accepted_as_is(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PO-2: `acceptance` calls `domain.line.is_accepted_as_is`; it spells no comparison."""
    monkeypatch.setattr(acceptance_module, "is_accepted_as_is", lambda line: False)

    report = _baseline_report(tmp_path, chapter, truth)

    assert report.accepted == 0
    assert (report.s1b, report.s1a) == (0.0, 0.0)


# -- AC-2 / AC-3: what counts as an acceptance --------------------------------


@pytest.mark.parametrize(
    ("final_0", "final_1"),
    [
        ("The café on street 3 is shut.", "The café on street 16 is shut."),
        ("The café, on street 3 is open.", "The café, on street 16 is open."),
        ("The Café on street 3 is open.", "The Café on street 16 is open."),
        ("", ""),
    ],
    ids=["one-word", "punctuation-only", "capitalisation-only", "deleted"],
)
def test_ac2_a_final_differing_from_its_proposal_by_a_word_a_comma_or_a_capital_is_a_rejection(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth, final_0: str, final_1: str
) -> None:
    pages = {0: _with_finals(0, {3: final_0}), 1: _with_finals(1, {6: final_1})}

    report = _measure(tmp_path, chapter, truth, pages)

    assert _counts(report) == (18, 20, 20, 0, 20)
    assert report.s1b == pytest.approx(18 / 20, abs=1e-12)
    assert report.s1a == pytest.approx(18 / 20, abs=1e-12)


def test_ac3_a_line_edited_and_then_restored_character_for_character_is_an_acceptance(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    with _project(tmp_path, chapter, _all(_baseline)) as project:
        commit_line(project, 0, 3, "Something else entirely.", "edited")
        commit_line(project, 1, 6, "Another rewrite.", "edited")
        edited = measure(project, truth)
        commit_line(project, 0, 3, _proposal(0, 3), "edited")
        commit_line(project, 1, 6, _proposal(1, 6), "edited")
        restored = measure(project, truth)

    assert edited.accepted == 18  # the edit was seen
    assert restored.accepted == 20
    assert (restored.s1b, restored.s1a) == (1.0, 1.0)


# -- AC-4: the identity, both ways ---------------------------------------------

#: Page 0 drops regions 1 and 6 and rejects 0, 3, 8; page 1 drops 4 and rejects
#: 2, 9. 17 proposed, 17 matched, 12 accepted, 20 in the truth.
_AC4_REJECTED = {0: (0, 3, 8), 1: (2, 9)}
_AC4_DROPPED = {0: (1, 6), 1: (4,)}


def _ac4_page(ordinal: int) -> list[Spot]:
    finals = {i: f"Rejected line {ordinal}-{i}." for i in _AC4_REJECTED[ordinal]}
    return _drop(_with_finals(ordinal, finals), _AC4_DROPPED[ordinal])


def test_ac4_with_no_spurious_detections_s1b_equals_s1a_times_recall_on_a_non_trivial_run(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, _all(_ac4_page))

    assert _counts(report) == (12, 17, 17, 0, 20)
    assert report.s1b == pytest.approx(12 / 20, abs=1e-12)
    assert report.s1a == pytest.approx(12 / 17, abs=1e-12)
    assert report.recall == pytest.approx(17 / 20, abs=1e-12)
    assert all(0.0 < x < 1.0 for x in (report.s1b, report.s1a, report.recall))
    assert math.isclose(report.s1b, report.s1a * report.recall, rel_tol=1e-9, abs_tol=1e-12)


def test_ac4_with_spurious_detections_the_identity_does_not_hold_and_spurious_is_non_zero(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    pages = _all(_ac4_page)
    pages[1] = [Spot(r, f"Phantom {k}.", None) for k, r in enumerate(_spurious_rects(5))] + pages[1]

    report = _measure(tmp_path, chapter, truth, pages)

    assert _counts(report) == (12, 22, 17, 5, 20)
    assert report.spurious > 0
    assert report.s1b == pytest.approx(12 / 20, abs=1e-12)
    assert report.s1a == pytest.approx(12 / 22, abs=1e-12)
    assert report.recall == pytest.approx(17 / 20, abs=1e-12)
    assert not math.isclose(report.s1b, report.s1a * report.recall, rel_tol=1e-9, abs_tol=1e-12)


# -- AC-5..AC-7, AC-9: the controls of stack.md §5/O2 --------------------------


def test_ac5_control_proposals_rotated_by_one_region_score_zero_on_both_numbers(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    proposals = [_proposal(o, i) for o in range(len(_PAGES)) for i in range(_PER_PAGE)]
    assert len({normalise(p) for p in proposals}) == _GROUND_TRUTH  # rotation changes every line

    def rotated(ordinal: int) -> list[Spot]:
        return [
            Spot(rect, _proposal(ordinal, (i + 1) % _PER_PAGE), _proposal(ordinal, i))
            for i, rect in enumerate(_TRUTH_RECTS)
        ]

    report = _measure(tmp_path, chapter, truth, _all(rotated))

    assert _counts(report) == (0, 20, 20, 0, 20)
    assert report.s1a == 0.0
    assert report.s1b == 0.0


def test_ac6_control_every_final_in_nfd_with_doubled_interior_spaces_is_accepted_in_full(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    def decomposed(ordinal: int) -> list[Spot]:
        spots = _baseline(ordinal)
        out = []
        for s in spots:
            assert s.proposal is not None
            final = unicodedata.normalize("NFD", s.proposal).replace(" ", "  ")
            assert final != s.proposal and final.count("  ") == s.proposal.count(" ")
            out.append(dataclasses.replace(s, final=final))
        return out

    report = _measure(tmp_path, chapter, truth, _all(decomposed))

    assert _counts(report) == (20, 20, 20, 0, 20)
    assert report.s1a == 1.0
    assert report.s1b == 1.0


def test_ac6_control_every_final_with_its_full_stop_made_an_exclamation_is_accepted_nowhere(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    def exclaimed(ordinal: int) -> list[Spot]:
        return [
            dataclasses.replace(s, final=s.proposal.replace(".", "!"))
            for s in _baseline(ordinal)
            if s.proposal is not None
        ]

    report = _measure(tmp_path, chapter, truth, _all(exclaimed))

    assert _counts(report) == (0, 20, 20, 0, 20)
    assert report.s1a == 0.0
    assert report.s1b == 0.0


#: Half rejected, so "S1a unchanged" is not the trivial 1.0: page 0 rejects the
#: even indices, page 1 the odd ones.
_AC7_REJECTED = {0: (0, 2, 4, 6, 8), 1: (1, 3, 5, 7, 9)}
#: 30 % of 20 = 6 dropped, three accepted and three rejected, from the middle of
#: the reading order so every later index shifts: page 0 drops 2 (rejected), 3, 7;
#: page 1 drops 1, 5 (rejected) and 4.
_AC7_DROPPED = {0: (2, 3, 7), 1: (1, 4, 5)}


def _ac7_page(ordinal: int) -> list[Spot]:
    return _with_finals(ordinal, {i: f"Rewritten {ordinal}-{i}." for i in _AC7_REJECTED[ordinal]})


def test_ac7_control_thirty_percent_of_regions_dropped_keeps_s1a_and_takes_s1b_down_30_percent(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    before = _measure(tmp_path, chapter, truth, _all(_ac7_page))
    after = _measure(
        tmp_path,
        chapter,
        truth,
        {o: _drop(_ac7_page(o), _AC7_DROPPED[o]) for o in range(len(_PAGES))},
    )

    assert _counts(before) == (10, 20, 20, 0, 20)
    assert (before.s1a, before.s1b, before.recall) == (0.5, 0.5, 1.0)
    assert _counts(after) == (7, 14, 14, 0, 20)
    assert math.isclose(after.s1a, before.s1a, rel_tol=1e-9)
    assert math.isclose(after.s1b, 0.7 * before.s1b, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(after.recall, 0.7, rel_tol=0.0, abs_tol=1e-12)
    assert after.matched == 14


def test_ac9_control_a_thousand_spurious_regions_leave_s1b_exactly_unchanged_and_are_counted(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    """Every phantom carries an OCR line and a proposal. 990 are left unedited, so
    their lines *are* accepted as-is - and must still not count (PO-1). The first
    ten in reading order were edited: an index-based pairing would hand page 0's
    ten truth regions to those ten rejections. They all come before the real
    regions, so every real region's reading index shifts by 1,000."""
    baseline = _baseline_report(tmp_path, chapter, truth)
    phantoms = [
        Spot(r, f"Phantom number {k}.", "An edited phantom." if k < _PER_PAGE else None)
        for k, r in enumerate(_spurious_rects(1000))
    ]

    report = _measure(tmp_path, chapter, truth, {0: phantoms + _baseline(0), 1: _baseline(1)})

    assert report.spurious == 1000
    assert report.s1b == baseline.s1b
    assert report.s1a < baseline.s1a
    assert report.proposed == report.matched + 1000
    assert _counts(report) == (20, 1020, 20, 1000, 20)
    assert report.s1a == pytest.approx(20 / 1020, abs=1e-12)


# -- AC-8 and the validator: refusals -----------------------------------------


def _write_doc(path: Path, truth: GroundTruth) -> Path:
    path.write_text(dump_ground_truth(truth), encoding="utf-8", newline="\n")
    return path


def test_ac8_a_development_use_document_is_refused_by_the_loader_in_benchmark_mode(
    tmp_path: Path, truth: GroundTruth
) -> None:
    path = _write_doc(tmp_path / "dev.truth.json", dataclasses.replace(truth, development_use=True))

    with pytest.raises(BenchmarkChapterUsedInDevelopment, match=_CHAPTER):
        load_ground_truth(path)


def test_ac8_a_development_use_truth_reaching_measure_directly_is_refused_naming_the_chapter(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    path = _write_doc(tmp_path / "dev.truth.json", dataclasses.replace(truth, development_use=True))
    flagged = load_ground_truth(path, benchmark=False)
    assert flagged.development_use

    with (
        _project(tmp_path, chapter, _all(_baseline)) as project,
        pytest.raises(BenchmarkChapterUsedInDevelopment) as refused,
    ):
        measure(project, flagged)

    assert _CHAPTER in str(refused.value)


def test_a_truth_failing_its_validator_is_refused_with_every_error_line(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    stale = dataclasses.replace(
        truth,
        pages=tuple(dataclasses.replace(page, sha256="0" * 64) for page in truth.pages),
    )
    loaded = load_ground_truth(_write_doc(tmp_path / "stale.truth.json", stale), benchmark=False)
    errors = validate(loaded, chapter).errors
    assert len(errors) == 2

    with (
        _project(tmp_path, chapter, _all(_baseline)) as project,
        pytest.raises(InvalidGroundTruth) as refused,
    ):
        measure(project, loaded)

    assert all(error in str(refused.value) for error in errors), (errors, str(refused.value))


def test_the_validators_warnings_do_not_stop_a_measurement(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = validate(truth, chapter)
    assert report.ok and report.warnings  # the seeded truth is all seed: it warns

    assert _baseline_report(tmp_path, chapter, truth).s1b == 1.0


# -- main ---------------------------------------------------------------------


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def test_main_prints_the_warnings_then_the_five_lines_with_identity_holding_and_returns_zero(
    folder: Path, chapter: Chapter, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    warnings = validate(truth, chapter).warnings

    status = main([str(folder)])

    out = _lines(capsys.readouterr().out)
    assert status == 0
    assert out[: len(warnings)] == list(warnings)
    patterns = [
        r"S1b chapter acceptance\s+100\.0%\s+accepted 20 / ground truth 20\s+<- headline",
        r"S1a translation acceptance\s+100\.0%\s+accepted 20 / proposed 20",
        r"recall\s+100\.0%\s+matched 20 / ground truth 20",
        r"spurious\s+0",
        r"identity S1b = S1a x recall\s+holds",
    ]
    report = out[len(warnings) :]
    assert len(report) == 5, out
    for pattern, line in zip(patterns, report, strict=True):
        assert re.fullmatch(pattern, line.strip()), (pattern, line)


def test_main_with_rejections_and_spurious_regions_prints_its_numbers_and_the_identity_failing(
    folder: Path, chapter: Chapter, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    """15 of 20 accepted; two phantoms appended to page 1 (no OCR line): 22 proposed."""
    with open_project(project_dir_for(folder)) as project:
        for ordinal, index in ((0, 1), (0, 5), (1, 0), (1, 2), (1, 8)):
            commit_line(project, ordinal, index, "A different line.", "edited")
        project.write_regions(1, _regions([*_TRUTH_RECTS, *_spurious_rects(2)]))

    status = main([str(folder)])

    out = _lines(capsys.readouterr().out)
    assert status == 0
    report = out[-5:]
    patterns = [
        r"S1b chapter acceptance\s+75\.0%\s+accepted 15 / ground truth 20\s+<- headline",
        r"S1a translation acceptance\s+68\.2%\s+accepted 15 / proposed 22",
        r"recall\s+100\.0%\s+matched 20 / ground truth 20",
        r"spurious\s+2",
        r"identity S1b = S1a x recall\s+does not hold \(spurious present\)",
    ]
    for pattern, line in zip(patterns, report, strict=True):
        assert re.fullmatch(pattern, line.strip()), (pattern, line)


def test_main_reads_the_document_named_by_the_truth_option(
    tmp_path: Path, folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = elsewhere / "annotation.json"
    truth_path_for(folder).rename(path)

    status = main([str(folder), "--truth", str(path)])

    assert status == 0
    assert re.fullmatch(r"spurious\s+0", _lines(capsys.readouterr().out)[-2].strip())


def _no_folder(tmp_path: Path, folder: Path) -> list[str]:
    return [str(tmp_path / "never-existed")]


def _no_project(tmp_path: Path, folder: Path) -> list[str]:
    other = tmp_path / "chapter-two"
    other.mkdir()
    for filename, _ in _PAGES:
        (other / filename).write_bytes((folder / filename).read_bytes())
    return [str(other)]


def _no_document(tmp_path: Path, folder: Path) -> list[str]:
    truth_path_for(folder).unlink()
    return [str(folder)]


def _malformed_document(tmp_path: Path, folder: Path) -> list[str]:
    truth_path_for(folder).write_text("{not json", encoding="utf-8")
    return [str(folder)]


def _stale_document(tmp_path: Path, folder: Path) -> list[str]:
    loaded = load_ground_truth(truth_path_for(folder))
    _write_doc(
        truth_path_for(folder),
        dataclasses.replace(
            loaded, pages=tuple(dataclasses.replace(p, sha256="0" * 64) for p in loaded.pages)
        ),
    )
    return [str(folder)]


def _development_document(tmp_path: Path, folder: Path) -> list[str]:
    loaded = load_ground_truth(truth_path_for(folder))
    _write_doc(truth_path_for(folder), dataclasses.replace(loaded, development_use=True))
    return [str(folder)]


@pytest.mark.parametrize(
    "arrange",
    [
        _no_folder,
        _no_project,
        _no_document,
        _malformed_document,
        _stale_document,
        _development_document,
    ],
    ids=[
        "no-such-folder",
        "no-project",
        "no-document",
        "malformed-document",
        "invalid-document",
        "development-use",
    ],
)
def test_main_returns_two_with_a_message_and_no_traceback_when_it_cannot_measure(
    tmp_path: Path,
    folder: Path,
    truth: GroundTruth,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[Path, Path], list[str]],
) -> None:
    argv = arrange(tmp_path, folder)

    status = main(argv)

    captured = capsys.readouterr()
    both = captured.out + captured.err
    assert status == 2
    assert _lines(both), "no message at all"
    assert "Traceback" not in both
    assert not any(line.startswith("S1b") for line in _lines(captured.out))
    if arrange is _development_document:
        assert _CHAPTER in both


# -- no second copy -------------------------------------------------------------


def _imports(tree: ast.Module, module: str, name: str) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(alias.name == name for alias in node.names)
        for node in ast.walk(tree)
    )


def test_acceptance_imports_o2s_predicate_and_the_matcher_and_normalises_nothing_itself() -> None:
    """Contract, settled: one `normalise`, one matcher. A source check, as
    `test_bench_truth.py` checks the overlap threshold, because the property is
    where the definition comes from - a private copy passes every behavioural
    test today and drifts the day `domain.line` changes."""
    tree = ast.parse(Path(inspect.getfile(acceptance_module)).read_text("utf-8"))

    assert _imports(tree, "mangatl.domain.line", "is_accepted_as_is")
    assert _imports(tree, "mangatl.bench.matching", "match_regions")
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert not defined & {"normalise", "normalize", "is_accepted_as_is", "match_regions", "iou"}
    assert not any(
        isinstance(node, ast.Import | ast.ImportFrom)
        and (
            any(alias.name == "unicodedata" for alias in node.names)
            or getattr(node, "module", None) == "unicodedata"
        )
        for node in ast.walk(tree)
    ), "acceptance.py imports unicodedata"
    assert not any(
        isinstance(node, ast.Attribute) and node.attr in {"normalize", "split"}
        for node in ast.walk(tree)
    ), "acceptance.py normalises or splits text itself"
