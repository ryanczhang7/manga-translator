"""`python -m mangatl.bench`: S1b, S1a, recall, spurious, S2 and S5 in one report.

MT-089 `## Contract` block 2. EPIC-07's `bench` is one command; the numbers
are the three measurement commands' own, by construction: this module calls
`bench.acceptance.measure`, `bench.s2.measure_s2` and `bench.cost.measure_cost`
on one opened project and one loaded document, and prints each module's
public `render` of its report. It computes nothing and re-renders nothing.

The arguments, the refusal order and the refusal texts are the acceptance
command's (PO-3). All three measurements complete before the first line is
printed, so a refusal from any of them - a `development_use` document
included - leaves stdout empty: S5 is not printed for a chapter the harness
refuses. Exit `0` measured (an `S2 FAIL` is a measurement), `2` cannot measure.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from mangatl.bench.acceptance import measure
from mangatl.bench.acceptance import render as render_acceptance
from mangatl.bench.cost import measure_cost
from mangatl.bench.cost import render as render_cost
from mangatl.bench.s2 import measure_s2
from mangatl.bench.s2 import render as render_s2
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    InvalidGroundTruth,
    load_ground_truth,
    truth_path_for,
    validate,
)
from mangatl.store.project import SchemaTooNew, open_project, project_dir_for

__all__ = ["main"]

_PROG = "python -m mangatl.bench"
_OK = 0
_CANNOT_MEASURE = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Measure a chapter's six numbers in one report. `0` measured, `2` cannot measure."""
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description="Measure S1b, S1a, recall, spurious, S2 and S5 against the ground truth.",
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
            acceptance = measure(project, truth)
            s2 = measure_s2(project, truth)
            cost = measure_cost(project)
        except (InvalidGroundTruth, BenchmarkChapterUsedInDevelopment) as error:
            return _fail(str(error))
        warnings = validate(truth, project.chapter).warnings

    for line in (
        *warnings,
        *render_acceptance(acceptance),
        *render_s2(s2),
        *render_cost(cost),
    ):
        print(line)
    return _OK


def _fail(message: str) -> int:
    print(f"{_PROG}: {message}", file=sys.stderr)
    return _CANNOT_MEASURE


if __name__ == "__main__":
    raise SystemExit(main())
