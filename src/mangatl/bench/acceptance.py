"""S1: the acceptance rate, measured against the benchmark ground truth.

MT-022 `## Contract` block 2. Two numbers, both on every run, neither ever
suppressed (`docs/wiki/stack.md` §5/O2):

- **S1b**, chapter acceptance = accepted / ground-truth regions. **The headline;
  the 80 % bar attaches here** (the user, 2026-09-12). A missed region adds 0 to
  the numerator and 1 to the denominator.
- **S1a**, translation acceptance = accepted / proposed. A diagnostic: of what
  the detector found, how much of the translation was kept.

**`accepted` counts truth regions whose matched proposal carries a line that
is accepted as-is** (PO-1). A spurious proposal's line never counts, whatever it
says, so with no spurious proposals `S1b == S1a x recall` exactly, and with them
the identity fails while S1b does not move. All three ratios are computed from
the counts independently - never one from another - which is what makes that
identity a check on the data rather than a tautology.

**Nothing is re-defined here.** "Accepted as-is" is O2's predicate,
`domain.line.is_accepted_as_is` (PO-2), and pairing is `bench.matching`'s mask
IoU, one-to-one, never by index. The document, its validator and the
development-use refusal are MT-029's; `measure` validates first and refuses a
flagged document itself as well (PO-3, PO-4).

`python -m mangatl.bench.acceptance FOLDER [--truth PATH]` prints the report
(PO-5). It reports a number; it does not judge the bar.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mangatl.bench.matching import match_regions
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    load_ground_truth,
    truth_path_for,
    validate,
)
from mangatl.domain.line import is_accepted_as_is
from mangatl.store.lines import read_review_lines
from mangatl.store.project import Project, SchemaTooNew, open_project, project_dir_for

__all__ = ["AcceptanceReport", "main", "measure"]

_PROG = "python -m mangatl.bench.acceptance"
_OK = 0
_CANNOT_MEASURE = 2


@dataclass(frozen=True)
class AcceptanceReport:
    """One measurement. There is no validity flag: every field, every run."""

    s1b: float  # HEADLINE: accepted / ground_truth (0.0 when ground_truth == 0)
    s1a: float  # diagnostic: accepted / proposed (0.0 when proposed == 0)
    recall: float  # matched / ground_truth (0.0 when ground_truth == 0)
    accepted: int
    proposed: int
    matched: int
    spurious: int
    ground_truth: int


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def measure(project: Project, truth: GroundTruth) -> AcceptanceReport:
    """Score `project` against `truth`, every page of `truth` and nothing else.

    Raises `BenchmarkChapterUsedInDevelopment` for a document flagged
    `development_use`, and `InvalidGroundTruth` carrying every error line for
    one that fails `validate` against the project's chapter. Warnings do not
    stop it.
    """
    if truth.development_use:
        raise BenchmarkChapterUsedInDevelopment(
            f"chapter {truth.chapter_name!r} is flagged development_use, so it is not"
            " held out and cannot be a benchmark"
        )
    report = validate(truth, project.chapter)
    if not report.ok:
        raise InvalidGroundTruth("\n".join(report.errors))

    accepted = proposed = matched = spurious = ground_truth = 0
    for page in truth.pages:
        proposals = project.read_regions(page.ordinal)
        lines = read_review_lines(project, page.ordinal)
        ground_truth += len(page.regions)
        proposed += len(proposals)
        for match in match_regions(proposals, page.regions, width=page.width, height=page.height):
            if match.truth_index is None:
                spurious += 1
            elif match.region_id is not None:
                matched += 1
                line = lines[match.region_id]
                if line is not None and is_accepted_as_is(line):
                    accepted += 1

    return AcceptanceReport(
        s1b=_ratio(accepted, ground_truth),
        s1a=_ratio(accepted, proposed),
        recall=_ratio(matched, ground_truth),
        accepted=accepted,
        proposed=proposed,
        matched=matched,
        spurious=spurious,
        ground_truth=ground_truth,
    )


def _render(report: AcceptanceReport) -> list[str]:
    identity = "holds" if report.spurious == 0 else "does not hold (spurious present)"
    return [
        f"S1b chapter acceptance      {report.s1b:.1%}  accepted {report.accepted}"
        f" / ground truth {report.ground_truth}   <- headline",
        f"S1a translation acceptance  {report.s1a:.1%}  accepted {report.accepted}"
        f" / proposed {report.proposed}",
        f"recall                      {report.recall:.1%}  matched {report.matched}"
        f" / ground truth {report.ground_truth}",
        f"spurious                    {report.spurious}",
        f"identity S1b = S1a x recall {identity}",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Measure a chapter against its ground truth. `0` measured, `2` cannot measure."""
    parser = argparse.ArgumentParser(
        prog=_PROG, description="Measure S1b and S1a against the benchmark ground truth."
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
            report = measure(project, truth)
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
