"""The typed events a run emits: commands in, events out (`architecture.md` §6).

The pipeline reports progress by handing one of these to a plain callable. It
never calls into a widget, which is what makes AC-9 true and what keeps
MT-018's cost readout testable without a GPU and an API key.

**These are data and nothing else** (`## Contract` PO-4). No methods, no
`__post_init__`, no validation, no properties: `domain` is inside
`coverage-core`'s `--cov-fail-under=100` set, so a defensive branch no test
reaches fails a required gate. Validation would also have no home here - the
runner produces these, not a user.

Frozen, because MT-015 hands the stream to a UI thread and a consumer that can
rewrite an ordinal is a consumer that can rewrite history.
"""

from __future__ import annotations

from dataclasses import dataclass

from mangatl.domain.budget import Projection
from mangatl.domain.money import Usd

__all__ = [
    "CallPriced",
    "PageSkipped",
    "PageStarted",
    "RegionsDetected",
    "RunAborted",
    "RunEvent",
    "RunFinished",
    "RunStarted",
    "StageFinished",
]


@dataclass(frozen=True)
class RunStarted:
    """A run has begun. `run_id` is the `run` row the runner inserted first."""

    run_id: int
    page_count: int


@dataclass(frozen=True)
class PageStarted:
    """Work has begun on the page with this ordinal."""

    ordinal: int


@dataclass(frozen=True)
class StageFinished:
    """One stage of one page completed. `elapsed_ms` is a measured duration."""

    ordinal: int
    stage: str
    elapsed_ms: int


@dataclass(frozen=True)
class PageSkipped:
    """The page was already complete, so no stage ran for it."""

    ordinal: int
    reason: str


@dataclass(frozen=True)
class CallPriced:
    """The page with this ordinal made a priced call, and the bill is recorded.

    The numbers are the ledger's, read after the call's row was written (MT-063):
    `spent` is the chapter's total across every run, `ceiling` the chapter's
    ceiling, and `projection` covers the pages *after* this one.
    """

    ordinal: int
    spent: Usd
    ceiling: Usd
    projection: Projection


@dataclass(frozen=True)
class RegionsDetected:
    """The page with this ordinal has been detected and its regions stored.

    `polygons` are the regions' outlines in page pixels, closed rings, in the
    reading order they were stored in (MT-062). Polygons rather than
    `RawRegion`s: a region's mask is a page-sized image, and this crosses a
    thread to a widget that only draws outlines.
    """

    ordinal: int
    polygons: tuple[tuple[tuple[int, int], ...], ...]


@dataclass(frozen=True)
class RunAborted:
    """The run stopped early.

    `ordinal` is `None` for a cancellation - no page is at fault - and the
    failing page's ordinal for an error. That distinction is what MT-018 shows
    the user.
    """

    reason: str
    ordinal: int | None


@dataclass(frozen=True)
class RunFinished:
    """Every page of the chapter is complete."""

    run_id: int
    pages_done: int


#: Every event a run can emit. A plain union alias: a `TYPE_CHECKING` guard or a
#: `sys.version_info` branch here would be an uncovered branch in a module that
#: carries a 100% line-and-branch bar.
RunEvent = (
    RunStarted
    | PageStarted
    | RegionsDetected
    | StageFinished
    | CallPriced
    | PageSkipped
    | RunAborted
    | RunFinished
)
