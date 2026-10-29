"""A page's status in the strip, derived from its lines (MT-086 block 1).

The store knows a page's run state (`pending`, `stale`, `done`) and each line's
`LineStatus`; the seven statuses `components.md` §`PageStrip` draws are a
derivation over those. The rules apply in order, first match wins:

1. `running` -> `running`;
2. `stale` -> `skipped` (PO-3: the source changed or is gone);
3. not `page_done` -> `pending`;
4. any failed line -> `failed`;
4a. a non-empty page whose every region is `excluded` -> `fully_reviewed`
   (MT-120 AC-5: nothing is left to review; an empty page still falls to 5);
5. nothing reviewed -> `translated` (this includes a page with no lines, PO-3);
6. some lines unreviewed -> `partly_reviewed`;
7. otherwise `fully_reviewed`.

The counts are computed on every call, whatever the status. "Reviewed" is a
line in `COMMITTED_STATUSES` (PO-2). A `None` entry is a region with no line
row: it counts in `total` and is neither reviewed nor failed. An `excluded`
entry (MT-120) counts in none of `total`, `reviewed` or `failed`.

`domain` imports nothing of ours but `domain.line`, and nothing third-party.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from mangatl.domain.line import COMMITTED_STATUSES, LineStatus

__all__ = ["PAGE_STATUSES", "PageProgress", "PageStatus", "page_progress"]

PageStatus = Literal[
    "pending",
    "running",
    "translated",
    "partly_reviewed",
    "fully_reviewed",
    "failed",
    "skipped",
]

#: The seven, in the design table's order.
PAGE_STATUSES: tuple[PageStatus, ...] = (
    "pending",
    "running",
    "translated",
    "partly_reviewed",
    "fully_reviewed",
    "failed",
    "skipped",
)


@dataclass(frozen=True)
class PageProgress:
    """What the strip shows for one page: its status and its line counts."""

    status: PageStatus
    reviewed: int
    total: int
    failed: int


def page_progress(
    lines: Sequence[LineStatus | None],
    *,
    page_done: bool,
    stale: bool = False,
    running: bool = False,
) -> PageProgress:
    """Derive one page's progress from its line statuses and run flags."""
    reviewed = sum(1 for s in lines if s in COMMITTED_STATUSES)
    failed = sum(1 for s in lines if s == "failed")
    total = sum(1 for s in lines if s != "excluded")
    status: PageStatus
    if running:
        status = "running"
    elif stale:
        status = "skipped"
    elif not page_done:
        status = "pending"
    elif failed > 0:
        status = "failed"
    elif lines and total == 0:
        status = "fully_reviewed"
    elif reviewed == 0:
        status = "translated"
    elif reviewed < total:
        status = "partly_reviewed"
    else:
        status = "fully_reviewed"
    return PageProgress(status, reviewed, total, failed)
