"""S2: recall and residual ink, reported as one pair.

MT-023 `## Contract` block 3, as amended in RED (A-2, A-3). The brief's S2 is
"every text-bearing bubble is found, and no Japanese pixels survive inside a
cleaned region", so the verdict is a conjunction and never a partial pass (AC-8,
PO-3):

- `recall_ok` - nothing missed **and nothing spurious**: a phantom bubble gets
  inpainted, which damages the art, so a spurious detection fails S2 rather than
  merely appearing beside it;
- `residual_ok` - every measured fraction at most `RESIDUAL_INK_MAX`
  (vacuously true when nothing was measured; recall has failed then anyway);
- `passed` - both.

**Why the collaborators are bare names (A-2).** `measure_s2` calls
`measure_recall` and `measure_residual` through this module's own globals, so
the verdict rule can be pinned on constructed reports, independently of either
measurement.

`python -m mangatl.bench.s2 FOLDER [--truth PATH]` prints the report, shaped as
`bench.acceptance`'s command is (MT-022 PO-5): exit `0` when measured - a
failing S2 is a measurement - and `2`, with the message on stderr, when it
cannot measure.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mangatl.bench.recall import RecallReport, measure_recall
from mangatl.bench.residual import RESIDUAL_INK_MAX, ResidualReport, measure_residual
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    load_ground_truth,
    truth_path_for,
    validate,
)
from mangatl.store.project import Project, SchemaTooNew, open_project, project_dir_for

__all__ = ["S2Report", "main", "measure_s2"]

_PROG = "python -m mangatl.bench.s2"
_OK = 0
_CANNOT_MEASURE = 2


@dataclass(frozen=True)
class S2Report:
    """Both measurements and the verdict on them."""

    recall: RecallReport
    residual: ResidualReport
    recall_ok: bool  # recall.missed == () and recall.spurious == 0
    residual_ok: bool  # every residual fraction <= RESIDUAL_INK_MAX (vacuously True with none)
    passed: bool  # recall_ok and residual_ok - never a partial pass (AC-8)


def measure_s2(project: Project, truth: GroundTruth) -> S2Report:
    """Measure recall, then residual ink, and judge the pair.

    Refuses as `measure_recall` does, before anything is measured.
    """
    recall = measure_recall(project, truth)
    residual = measure_residual(project, truth)
    recall_ok = not recall.missed and recall.spurious == 0
    residual_ok = all(region.fraction <= RESIDUAL_INK_MAX for region in residual.regions)
    return S2Report(
        recall=recall,
        residual=residual,
        recall_ok=recall_ok,
        residual_ok=residual_ok,
        passed=recall_ok and residual_ok,
    )


def _render(report: S2Report) -> list[str]:
    recall, residual = report.recall, report.residual
    missed = ", ".join(f"page {o} region {i}" for o, i in recall.missed) or "none"
    lines = [
        f"recall        {recall.recall:.1%}  matched {recall.matched}"
        f" / ground truth {recall.ground_truth}",
        f"missed        {missed}",
        f"spurious      {recall.spurious}",
        f"residual ink  worst {residual.worst:.4f} / max {RESIDUAL_INK_MAX:.4f}",
        *(
            f"  page {region.page_ordinal} region {region.truth_index}  {region.fraction:.4f}"
            for region in residual.regions
        ),
    ]
    if residual.uncleaned_pages:
        pages = ", ".join(f"page {o}" for o in residual.uncleaned_pages)
        lines.append(f"uncleaned     {pages} (measured on the source scan)")
    halves = (("recall", report.recall_ok), ("residual ink", report.residual_ok))
    failed = [name for name, ok in halves if not ok]
    lines.append("S2 FAIL: " + ", ".join(failed) if failed else "S2 PASS")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Measure a chapter's S2 against its ground truth. `0` measured, `2` cannot measure."""
    parser = argparse.ArgumentParser(
        prog=_PROG, description="Measure S2 - recall and residual ink - against the ground truth."
    )
    parser.add_argument("folder", type=Path, help="the chapter's folder of page scans")
    parser.add_argument(
        "--truth", type=Path, default=None, help="the document (default: <folder>.truth.json)"
    )
    arguments = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    folder: Path = arguments.folder
    path: Path = arguments.truth or truth_path_for(folder)

    if not folder.is_dir():
        return _fail(f"no such folder: {folder}")
    try:
        project = open_project(project_dir_for(folder))
    except (FileNotFoundError, SchemaTooNew) as error:
        return _fail(str(error))
    with project:
        if not path.is_file():
            return _fail(f"no ground-truth document at {path}")
        try:
            truth = load_ground_truth(path)
            report = measure_s2(project, truth)
        except (InvalidGroundTruth, BenchmarkChapterUsedInDevelopment) as error:
            return _fail(str(error))
        warnings = validate(truth, project.chapter).warnings

    for line in (*warnings, *_render(report)):
        print(line)
    return _OK


def _fail(message: str) -> int:
    print(f"{_PROG}: {message}", file=sys.stderr)
    return _CANNOT_MEASURE


if __name__ == "__main__":
    raise SystemExit(main())
