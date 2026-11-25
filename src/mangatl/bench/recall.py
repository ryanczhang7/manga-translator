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

**What the bench scores** (MT-148). A region the pipeline itself set aside -
`excluded` in `PIPELINE_EXCLUSIONS`, `art` or `watermark` - is neither matched
nor spurious; it is counted as **left_as_art**. A region the user excluded is
still scored. `proposal_indices` is the one rule, and it returns positions so a
caller holding per-stored-region data (`acceptance`'s lines) can map back.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mangatl.bench.matching import IOU_MATCH_THRESHOLD as IOU_MATCH_THRESHOLD
from mangatl.bench.matching import match_regions
from mangatl.bench.truth import (
    GroundTruth,
    InvalidGroundTruth,
    check_mode,
    validate,
)
from mangatl.domain.region import ExclusionReason, RawRegion
from mangatl.store.project import Project

__all__ = [
    "PIPELINE_EXCLUSIONS",
    "PageRecall",
    "RecallReport",
    "measure_recall",
    "proposal_indices",
]

#: The exclusions that are the pipeline's own call, not the user's (MT-148 PO-2).
PIPELINE_EXCLUSIONS: frozenset[ExclusionReason] = frozenset({"art", "watermark"})


def proposal_indices(regions: Sequence[RawRegion]) -> tuple[int, ...]:
    """The positions in `regions` of the regions the bench scores, ascending:
    every region whose `excluded` is not in PIPELINE_EXCLUSIONS. `None` and
    `user` are scored."""
    return tuple(
        i for i, region in enumerate(regions) if region.excluded not in PIPELINE_EXCLUSIONS
    )


@dataclass(frozen=True)
class PageRecall:
    """One truth page's share of the counts."""

    ordinal: int
    matched: int
    missed: tuple[int, ...]  # truth indices on this page, ascending
    spurious: int
    left_as_art: int = 0  # stored regions whose `excluded` is in PIPELINE_EXCLUSIONS


@dataclass(frozen=True)
class RecallReport:
    """One measurement; the page breakdown sums to the totals."""

    matched: int
    missed: tuple[tuple[int, int], ...]  # (page ordinal, truth index), page then index order
    spurious: int
    ground_truth: int  # len(truth.regions)
    recall: float  # matched / ground_truth; 0.0 when ground_truth == 0
    pages: tuple[PageRecall, ...]  # one per truth page, in truth page order
    left_as_art: int = 0  # sum of the pages'


def measure_recall(
    project: Project, truth: GroundTruth, *, development: bool = False
) -> RecallReport:
    """Match `project`'s proposals against `truth`, every page of `truth` and nothing else.

    Refuses first by `check_mode`: `BenchmarkChapterUsedInDevelopment` for a
    document flagged `development_use` unless `development` is set, and
    `NotADevelopmentSet` for an unflagged one when it is (MT-142). Then raises
    `InvalidGroundTruth` carrying every error line for a document that fails
    `validate` against the project's chapter - all before any page is read.
    Warnings do not stop it.
    """
    check_mode(truth, development=development)
    report = validate(truth, project.chapter)
    if not report.ok:
        raise InvalidGroundTruth("\n".join(report.errors))

    pages: list[PageRecall] = []
    for page in truth.pages:
        regions = project.read_regions(page.ordinal)
        kept = proposal_indices(regions)
        matches = match_regions(
            [regions[i] for i in kept], page.regions, width=page.width, height=page.height
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
                left_as_art=len(regions) - len(kept),
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
        left_as_art=sum(page.left_as_art for page in pages),
    )
