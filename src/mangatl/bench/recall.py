"""S2, first half: detection recall against the benchmark ground truth.

MT-023 `## Contract` block 1. Three counts on every run, per page and in total
(AC-1): **matched** truth regions, **missed** truth regions named by
`(page ordinal, truth index)` (AC-2), and **spurious** proposals that match no
truth region (AC-3). `recall` is matched / ground truth and nothing else:
spurious never enters it, which is exactly why it is reported beside it - a
detector that emits a thousand boxes scores no higher recall, and the thousand
boxes are counted where the reader sees them.

**Nothing is re-defined here.** Pairing is `bench.matching`'s mask IoU,
one-to-one, at `IOU_MATCH_THRESHOLD`, never by index or by polygon. The
document, its validator and the development-use refusal are MT-029's; the
refusal order is `bench.acceptance.measure`'s (MT-022 PO-3/PO-4), and the counts
are this module's own, never read from `bench.acceptance`.

**Why `IOU_MATCH_THRESHOLD` is imported though `match_regions` applies it.**
The contract pins one threshold, imported, never copied, and a source check in
`tests/core/test_bench_recall.py` holds `recall.py` to it. The import is spelled
as an explicit re-export (`X as X`) rather than with `# noqa: F401`: the threshold
is part of what this module's numbers mean, so `recall.IOU_MATCH_THRESHOLD` is
offered to a reader as the value the report was measured under, and the spelling
is one ruff and mypy both read as deliberate - where a `noqa` would also silence
a genuinely dead import on the same line later.
"""

from __future__ import annotations

from dataclasses import dataclass

from mangatl.bench.matching import IOU_MATCH_THRESHOLD as IOU_MATCH_THRESHOLD
from mangatl.bench.matching import match_regions
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    validate,
)
from mangatl.store.project import Project

__all__ = ["PageRecall", "RecallReport", "measure_recall"]


@dataclass(frozen=True)
class PageRecall:
    """One truth page's share of the counts."""

    ordinal: int
    matched: int
    missed: tuple[int, ...]  # truth indices on this page, ascending
    spurious: int


@dataclass(frozen=True)
class RecallReport:
    """One measurement; the page breakdown sums to the totals."""

    matched: int
    missed: tuple[tuple[int, int], ...]  # (page ordinal, truth index), page then index order
    spurious: int
    ground_truth: int  # len(truth.regions)
    recall: float  # matched / ground_truth; 0.0 when ground_truth == 0
    pages: tuple[PageRecall, ...]  # one per truth page, in truth page order


def measure_recall(project: Project, truth: GroundTruth) -> RecallReport:
    """Match `project`'s proposals against `truth`, every page of `truth` and nothing else.

    Raises `BenchmarkChapterUsedInDevelopment` for a document flagged
    `development_use`, and `InvalidGroundTruth` carrying every error line for
    one that fails `validate` against the project's chapter - both before any
    page is read. Warnings do not stop it.
    """
    if truth.development_use:
        raise BenchmarkChapterUsedInDevelopment(
            f"chapter {truth.chapter_name!r} is flagged development_use, so it is not"
            " held out and cannot be a benchmark"
        )
    report = validate(truth, project.chapter)
    if not report.ok:
        raise InvalidGroundTruth("\n".join(report.errors))

    pages: list[PageRecall] = []
    for page in truth.pages:
        matches = match_regions(
            project.read_regions(page.ordinal), page.regions, width=page.width, height=page.height
        )
        pages.append(
            PageRecall(
                ordinal=page.ordinal,
                matched=sum(m.truth_index is not None and m.region_id is not None for m in matches),
                missed=tuple(
                    m.truth_index
                    for m in matches
                    if m.truth_index is not None and m.region_id is None
                ),
                spurious=sum(m.truth_index is None for m in matches),
            )
        )

    matched = sum(page.matched for page in pages)
    ground_truth = len(truth.regions)
    return RecallReport(
        matched=matched,
        missed=tuple((page.ordinal, index) for page in pages for index in page.missed),
        spurious=sum(page.spurious for page in pages),
        ground_truth=ground_truth,
        recall=matched / ground_truth if ground_truth else 0.0,
        pages=tuple(pages),
    )
