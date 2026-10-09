"""`mangatl.bench.s2`: recall and residual ink reported as one pair.

MT-023 AC-7 (for `measure_s2` and the command), AC-8, and the
`python -m mangatl.bench.s2` entry point, `## Contract` block 3 as amended in
RED (A-2: the names `s2` reads at call time; A-3: the rendered lines). All
mechanical.

**Never a partial pass (AC-8, PO-3).** `recall_ok` is "nothing missed and
nothing spurious", `residual_ok` is "every measured fraction at most
`RESIDUAL_INK_MAX`", and `passed` is their conjunction. All four combinations
are asserted twice: on constructed reports handed to `measure_s2` through its
own module names (so the rule is pinned independently of either measurement),
and on real projects of `_s2_world`'s chapter.

**The command's report** is pinned line by line with `re.fullmatch` on each
stripped line. The numbers in it are formatted from the report `measure_s2`
returns for the same project, never from a value RED computed, so these tests
pin the rendering and the residual tests pin the metric.
"""

from __future__ import annotations

import dataclasses
import math
import re
import runpy
import sys
import warnings
from collections.abc import Callable
from pathlib import Path

import _s2_world as w
import pytest

import mangatl.bench.s2 as s2_module
from mangatl.bench.recall import PageRecall, RecallReport, measure_recall
from mangatl.bench.residual import (
    RESIDUAL_INK_MAX,
    RegionResidual,
    ResidualReport,
    measure_residual,
)
from mangatl.bench.s2 import S2Report, main, measure_s2
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    load_ground_truth,
    truth_path_for,
    validate,
)
from mangatl.domain.page import Chapter
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, open_project, project_dir_for

_PROG = "python -m mangatl.bench.s2"


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
    tmp_path: Path,
    chapter: Chapter,
    truth: GroundTruth,
    detections: dict[int, list[RawRegion]],
    cleaned: dict[int, bytes] | None,
) -> S2Report:
    with w.project(tmp_path, chapter, detections, cleaned) as project:
        return measure_s2(project, truth)


def _verdict(report: S2Report) -> tuple[bool, bool, bool]:
    return (report.recall_ok, report.residual_ok, report.passed)


# -- the report -----------------------------------------------------------------


def test_the_s2_report_has_exactly_these_five_fields_in_order() -> None:
    assert [f.name for f in dataclasses.fields(S2Report)] == [
        "recall",
        "residual",
        "recall_ok",
        "residual_ok",
        "passed",
    ]


def test_measure_s2_carries_both_measurements_of_the_same_project_unchanged(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    detections = w.all_pages()
    del detections[1][2]
    with w.project(tmp_path, chapter, detections, {0: w.cleaned_page(0, w.WHITE)}) as project:
        report = measure_s2(project, truth)
        assert report.recall == measure_recall(project, truth)
        assert report.residual == measure_residual(project, truth)

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.passed = True  # type: ignore[misc]


# -- AC-8: the verdict is a pair, never a partial pass ---------------------------


def _recall(missed: tuple[tuple[int, int], ...] = (), spurious: int = 0) -> RecallReport:
    matched = w.GROUND_TRUTH - len(missed)
    return RecallReport(
        matched=matched,
        missed=missed,
        spurious=spurious,
        ground_truth=w.GROUND_TRUTH,
        recall=matched / w.GROUND_TRUTH,
        pages=(PageRecall(ordinal=0, matched=matched, missed=(), spurious=spurious),),
    )


def _residual(*fractions: float) -> ResidualReport:
    return ResidualReport(
        regions=tuple(RegionResidual(0, i, f) for i, f in enumerate(fractions)),
        worst=max(fractions, default=0.0),
        uncleaned_pages=(),
    )


def _with_reports(
    monkeypatch: pytest.MonkeyPatch, recall: RecallReport, residual: ResidualReport
) -> None:
    """Amendment A-2: `measure_s2` calls the names `measure_recall` and
    `measure_residual` from its own module's namespace."""
    monkeypatch.setattr(s2_module, "measure_recall", lambda project, truth: recall)
    monkeypatch.setattr(s2_module, "measure_residual", lambda project, truth: residual)


_OVER = math.nextafter(RESIDUAL_INK_MAX, 1.0)


@pytest.mark.parametrize(
    ("recall", "residual", "expected"),
    [
        (_recall(), _residual(0.0, RESIDUAL_INK_MAX), (True, True, True)),
        (_recall(missed=((0, 1),)), _residual(0.0), (False, True, False)),
        (_recall(spurious=1), _residual(0.0), (False, True, False)),
        (_recall(), _residual(0.0, _OVER), (True, False, False)),
        (_recall(missed=((0, 1),), spurious=3), _residual(_OVER, 0.9), (False, False, False)),
        (_recall(missed=((0, 0),)), _residual(), (False, True, False)),
    ],
    ids=[
        "both-pass-at-the-threshold",
        "missed-only",
        "spurious-only",
        "residual-just-over-only",
        "both-fail",
        "no-region-measured-is-vacuously-clean",
    ],
)
def test_ac8_s2_passes_only_when_recall_and_residual_ink_both_pass(
    tmp_path: Path,
    chapter: Chapter,
    truth: GroundTruth,
    monkeypatch: pytest.MonkeyPatch,
    recall: RecallReport,
    residual: ResidualReport,
    expected: tuple[bool, bool, bool],
) -> None:
    _with_reports(monkeypatch, recall, residual)

    with w.project(tmp_path, chapter, {}) as project:
        report = measure_s2(project, truth)

    assert (report.recall, report.residual) == (recall, residual)
    assert _verdict(report) == expected


def test_ac8_every_region_found_and_cleaned_white_passes_s2(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, w.all_pages(), w.all_cleaned(w.WHITE))

    assert _verdict(report) == (True, True, True)


def test_ac8_a_missed_region_with_a_perfect_clean_fails_s2_on_recall_alone(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    detections = w.all_pages()
    del detections[1][1]

    report = _measure(tmp_path, chapter, truth, detections, w.all_cleaned(w.WHITE))

    assert report.recall.missed == ((1, 1),)
    assert _verdict(report) == (False, True, False)


def test_ac8_po3_a_spurious_detection_with_every_region_found_fails_s2_on_recall(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    detections = w.all_pages()
    detections[0].append(w.region(w.spurious_rects(1)[0]))

    report = _measure(tmp_path, chapter, truth, detections, w.all_cleaned(w.WHITE))

    assert (report.recall.missed, report.recall.spurious) == ((), 1)
    assert _verdict(report) == (False, True, False)


def test_ac8_every_region_found_with_cleaning_skipped_fails_s2_on_residual_ink_alone(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, w.all_pages(), None)

    assert report.residual.uncleaned_pages == (0, 1)
    assert _verdict(report) == (True, False, False)


def test_ac8_a_missed_region_and_cleaning_skipped_fail_s2_on_both(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    detections = w.all_pages()
    del detections[0][0]

    report = _measure(tmp_path, chapter, truth, detections, None)

    assert _verdict(report) == (False, False, False)


def test_ac8_with_nothing_detected_residual_is_vacuously_clean_and_s2_still_fails(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    report = _measure(tmp_path, chapter, truth, {}, None)

    assert report.residual.regions == ()
    assert _verdict(report) == (False, True, False)


# -- AC-7: refusals ----------------------------------------------------------------


def test_ac7_a_development_use_truth_reaching_measure_s2_directly_is_refused_before_measuring(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth, monkeypatch: pytest.MonkeyPatch
) -> None:
    flagged = w.flagged(tmp_path, truth)
    with w.project(tmp_path, chapter, w.all_pages()) as project:
        monkeypatch.setattr(Project, "read_regions", w.boom)
        monkeypatch.setattr(Project, "read_cleaned", w.boom)
        with pytest.raises(BenchmarkChapterUsedInDevelopment) as refused:
            measure_s2(project, flagged)

    assert w.CHAPTER in str(refused.value)


def test_ac7_a_truth_failing_its_validator_is_refused_by_measure_s2_with_every_error_line(
    tmp_path: Path, chapter: Chapter, truth: GroundTruth
) -> None:
    loaded = w.stale(tmp_path, truth)
    errors = validate(loaded, chapter).errors
    assert len(errors) == 2

    with (
        w.project(tmp_path, chapter, w.all_pages()) as project,
        pytest.raises(InvalidGroundTruth) as refused,
    ):
        measure_s2(project, loaded)

    assert all(error in str(refused.value) for error in errors), (errors, str(refused.value))


# -- main -------------------------------------------------------------------------


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _arrange(
    folder: Path, detections: dict[int, list[RawRegion]], cleaned: dict[int, bytes]
) -> S2Report:
    """Rewrite the baseline project at `project_dir_for(folder)`, which the
    command opens, and return what `measure_s2` reports for it."""
    with open_project(project_dir_for(folder)) as project:
        for ordinal, page_regions in detections.items():
            project.write_regions(ordinal, page_regions)
        for ordinal, image in cleaned.items():
            project.write_cleaned(ordinal, image)
        return measure_s2(project, load_ground_truth(truth_path_for(folder)))


def _expected(report: S2Report) -> list[str]:
    """Amendment A-3, the report's lines in order, as regular expressions."""
    r, s = report.recall, report.residual
    missed = ", ".join(f"page {o} region {i}" for o, i in r.missed) or "none"
    lines = [
        rf"recall\s+{re.escape(f'{r.recall:.1%}')}\s+"
        rf"matched {r.matched} / ground truth {r.ground_truth}",
        rf"missed\s+{re.escape(missed)}",
        rf"spurious\s+{r.spurious}",
        rf"residual ink\s+worst {s.worst:.4f} / max {RESIDUAL_INK_MAX:.4f}",
        *(rf"page {x.page_ordinal} region {x.truth_index}\s+{x.fraction:.4f}" for x in s.regions),
    ]
    if s.uncleaned_pages:
        pages = ", ".join(f"page {o}" for o in s.uncleaned_pages)
        lines.append(rf"uncleaned\s+{re.escape(pages)} \(measured on the source scan\)")
    halves = (("recall", report.recall_ok), ("residual ink", report.residual_ok))
    failed = [name for name, ok in halves if not ok]
    lines.append("S2 PASS" if not failed else re.escape("S2 FAIL: " + ", ".join(failed)))
    return lines


def _assert_report(out: list[str], report: S2Report) -> None:
    patterns = _expected(report)
    tail = out[-len(patterns) :]
    assert len(tail) == len(patterns), out
    for pattern, line in zip(patterns, tail, strict=True):
        assert re.fullmatch(pattern, line), (pattern, line)


def test_main_prints_the_warnings_then_the_report_ending_s2_pass_and_returns_zero(
    folder: Path, chapter: Chapter, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _arrange(folder, {}, w.all_cleaned(w.WHITE))
    assert report.passed
    warnings_ = validate(truth, chapter).warnings
    assert warnings_

    status = main([str(folder)])

    out = _lines(capsys.readouterr().out)
    assert status == 0
    assert out[: len(warnings_)] == [line.strip() for line in warnings_]
    assert len(out) == len(warnings_) + 4 + w.GROUND_TRUTH + 1, out
    _assert_report(out, report)
    assert out[-1] == "S2 PASS"
    assert re.fullmatch(r"page 1 region 2\s+0\.0000", out[-2])


@pytest.mark.parametrize(
    ("arrange", "last"),
    [
        ("missed", "S2 FAIL: recall"),
        ("spurious", "S2 FAIL: recall"),
        ("uncleaned", "S2 FAIL: residual ink"),
        ("both", "S2 FAIL: recall, residual ink"),
    ],
)
def test_main_ends_its_report_naming_the_half_or_halves_of_s2_that_failed(
    folder: Path,
    truth: GroundTruth,
    capsys: pytest.CaptureFixture[str],
    arrange: str,
    last: str,
) -> None:
    white = w.all_cleaned(w.WHITE)
    without_1_0 = w.baseline()[1:]
    setups: dict[str, Callable[[], S2Report]] = {
        "missed": lambda: _arrange(folder, {1: without_1_0}, white),
        "spurious": lambda: _arrange(
            folder, {1: [*w.baseline(), *w.regions(w.spurious_rects(2))]}, white
        ),
        "uncleaned": lambda: _arrange(folder, {}, {0: white[0]}),
        "both": lambda: _arrange(
            folder, {1: [*without_1_0, *w.regions(w.spurious_rects(2))]}, {0: white[0]}
        ),
    }
    report = setups[arrange]()

    status = main([str(folder)])

    out = _lines(capsys.readouterr().out)
    assert status == 0  # a failing S2 is a measurement, not an error
    assert out[-1] == last
    _assert_report(out, report)


def test_main_names_every_missed_region_by_page_and_index_and_counts_spurious(
    folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _arrange(
        folder,
        {0: w.baseline()[:2], 1: [*w.baseline()[1:], *w.regions(w.spurious_rects(2))]},
        {},
    )

    main([str(folder)])

    out = _lines(capsys.readouterr().out)
    assert re.fullmatch(r"recall\s+66\.7%\s+matched 4 / ground truth 6", out[-10]), out
    assert re.fullmatch(r"missed\s+page 0 region 2, page 1 region 0", out[-9])
    assert re.fullmatch(r"spurious\s+2", out[-8])
    assert re.fullmatch(r"uncleaned\s+page 0, page 1 \(measured on the source scan\)", out[-2])
    _assert_report(out, report)


def test_main_reads_the_document_named_by_the_truth_option(
    tmp_path: Path, folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    _arrange(folder, {}, w.all_cleaned(w.WHITE))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = elsewhere / "annotation.json"
    truth_path_for(folder).rename(path)

    status = main([str(folder), "--truth", str(path)])

    assert status == 0
    assert _lines(capsys.readouterr().out)[-1] == "S2 PASS"


def _no_folder(tmp_path: Path, folder: Path) -> list[str]:
    return [str(tmp_path / "never-existed")]


def _no_project(tmp_path: Path, folder: Path) -> list[str]:
    other = tmp_path / "chapter-two"
    other.mkdir()
    for filename in w.FILENAMES:
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
    w.write_doc(
        truth_path_for(folder),
        dataclasses.replace(
            loaded, pages=tuple(dataclasses.replace(p, sha256="0" * 64) for p in loaded.pages)
        ),
    )
    return [str(folder)]


def _development_document(tmp_path: Path, folder: Path) -> list[str]:
    loaded = load_ground_truth(truth_path_for(folder))
    w.write_doc(truth_path_for(folder), dataclasses.replace(loaded, development_use=True))
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
def test_main_returns_two_with_a_prefixed_message_on_stderr_when_it_cannot_measure(
    tmp_path: Path,
    folder: Path,
    truth: GroundTruth,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[Path, Path], list[str]],
) -> None:
    argv = arrange(tmp_path, folder)

    status = main(argv)

    captured = capsys.readouterr()
    err = _lines(captured.err)
    assert status == 2
    assert err, "no message on stderr"
    assert err[0].startswith(f"{_PROG}: "), err
    assert "Traceback" not in captured.out + captured.err
    assert not any(line.startswith(("S2", "recall")) for line in _lines(captured.out))
    if arrange is _development_document:
        assert w.CHAPTER in captured.err
    if arrange is _stale_document:
        assert "sha256" in captured.err


def test_python_dash_m_runs_main_and_exits_with_its_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PO-5: `python -m mangatl.bench.s2 FOLDER` is the entry point."""
    monkeypatch.setattr(sys, "argv", [_PROG, str(tmp_path / "never-existed")])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # runpy: already imported
        with pytest.raises(SystemExit) as exited:
            runpy.run_module("mangatl.bench.s2", run_name="__main__")

    assert exited.value.code == 2
    assert capsys.readouterr().err.startswith(f"{_PROG}: ")
