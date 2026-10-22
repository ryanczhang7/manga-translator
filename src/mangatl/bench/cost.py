"""S5: the chapter's cost, read out of the project's ledger.

MT-075 `## Contract` blocks 1-3. The brief's S5 is *"a benchmark chapter run
costs under $2, as reported by the app"*: the denominator is the chapter, and
this module prints the chapter figure the bar attaches to, with a per-page
figure beside it as a diagnostic that makes two chapters comparable. It
reports a number; it does not judge the bar, project a spend or read the
budget ceiling (block 3).

**The number is the ledger's, and nothing here prices a call.** Every priced
call is a row in `store.ledger` (MT-012), append-only by schema trigger and
stored as integer micro-dollars, so the fold below is exact. The read is
`chapter_call_costs` rather than `chapter_total` because S5 needs to know
whether *any* call exists as well as what they sum to: `chapter_total` is
`Usd` zero for an empty ledger, which cannot tell "nothing priced" from "priced
at zero". Both are unqualified by run, so a resumed chapter - two `run` rows -
is one spend. The fold is `reduce(add, ...)` because `sum()` starts from the
integer `0` and `Usd` does not add to an `int` (`domain.money`).

**`$—`, never `$0.00`** (MT-018 AC-5, AC-9). A chapter with no priced call is
unmeasured, not free, so the report holds `None` and the command prints the
dash; the dash is keyed on a call existing, never on the total being non-zero.
`bench` may not import `ui`, so the glyph is spelled here.

**The per-page rule** (PO-4) divides by the chapter's page count - not by the
pages that carry a call - and quantises once to a micro-dollar, the ledger's
own unit, rounding half up as `Usd.micro()` does. Figures print as `str(Usd)`,
four decimals, not the app's rounded-up `format_usd` (PO-3). There is no
`--truth` option: the cost of a chapter is a fact of its ledger whether or
not it is held out (PO-2).

`python -m mangatl.bench.cost FOLDER` prints the two lines.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import reduce
from operator import add
from pathlib import Path

from mangatl.domain.money import Usd
from mangatl.store.ledger import chapter_call_costs
from mangatl.store.project import Project, SchemaTooNew, open_project, project_dir_for

__all__ = ["DASH", "CostReport", "main", "measure_cost", "render"]

#: What the figure reads when no call was priced. MT-018 AC-5's glyph, spelled
#: here because `bench` may not import `mangatl.ui`.
DASH: str = "$\N{EM DASH}"

_PROG = "python -m mangatl.bench.cost"
_OK = 0
_CANNOT_MEASURE = 2
_MICRO_DOLLAR = Decimal("0.000001")


@dataclass(frozen=True)
class CostReport:
    """One read-out of the ledger. `None` means no call was priced."""

    total: Usd | None
    calls: int
    pages: int
    per_page: Usd | None


def measure_cost(project: Project) -> CostReport:
    """The chapter's spend over every run, and that spend per page."""
    costs = chapter_call_costs(project)
    pages = len(project.pages())
    if not costs:
        return CostReport(total=None, calls=0, pages=pages, per_page=None)
    total: Usd = reduce(add, costs)
    per_page = Usd((total.amount / pages).quantize(_MICRO_DOLLAR, rounding=ROUND_HALF_UP))
    return CostReport(total=total, calls=len(costs), pages=pages, per_page=per_page)


def render(report: CostReport) -> tuple[str, str]:
    if report.total is None or report.per_page is None:
        return (
            f"S5 chapter cost  {DASH}  no priced calls",
            f"per page         {DASH}  {report.pages} pages",
        )
    return (
        f"S5 chapter cost  {report.total}  {report.calls} priced calls",
        f"per page         {report.per_page}  {report.pages} pages",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Read a chapter's cost out of its ledger. `0` measured, `2` cannot measure."""
    parser = argparse.ArgumentParser(
        prog=_PROG, description="Print S5, the chapter's cost, from the project's ledger."
    )
    parser.add_argument("folder", type=Path, help="the chapter's folder of page scans")
    arguments = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    folder: Path = arguments.folder

    if not folder.is_dir():
        return _fail(f"no such folder: {folder}")
    try:
        project = open_project(project_dir_for(folder))
    except (FileNotFoundError, SchemaTooNew) as error:
        return _fail(str(error))
    with project:
        report = measure_cost(project)

    for line in render(report):
        print(line)
    return _OK


def _fail(message: str) -> int:
    print(f"{_PROG}: {message}", file=sys.stderr)
    return _CANNOT_MEASURE


if __name__ == "__main__":
    raise SystemExit(main())
