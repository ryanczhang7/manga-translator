"""`CostEstimate`: what a chapter is expected to cost, against its budget (MT-058).

`components.md` §2 `CostEstimate`, as amended for PO-1/PO-2: `ChapterSummary`'s
part 5, the *before* to `CostReadout`'s *during*. One line for the estimate, one
for the budget, and - above 200 pages - a warning that this is more pages than a
chapter. Nothing here blocks anything; the Start button is MT-059's.

**The figure is the guard's own.** The estimate is
`Budget(page_estimate=page_estimate(model)).project((), pages).remaining_chapter`,
asked at construction: the number the budget guard itself uses before any call
is priced on that model (MT-100), so the screen and the guard cannot disagree
about whether a chapter fits. `model` is the id the run would call; when none
can be chosen it is `NoProvider(reason)` and the widget shows no figure, only
why, and is never over budget. No money arithmetic
happens here beyond the one comparison, `estimate > ceiling`, which is inclusive
as `Budget.check` is: an estimate exactly on the ceiling is within budget.

**`format_usd` rounds a fraction of a cent up**, `budget.py`'s direction: the
shown figure exceeds the shown budget exactly when the estimate does, and an
estimate of one or more pages can never read `$0.00` (AC-5). It is exact
`Decimal` throughout - no float.

The over-budget state is carried by the sentence on the budget line
(`accessibility.md` A-10) and by the frame's warning border; there is no glyph.

Spacing comes from the design tokens (`tokens_gen`) and is set here. Every
colour, ground, border and type size comes from the application stylesheet
(`theme.qss`, applied at startup - MT-061), by object name, and from nowhere
else, as in `summary.py` and for the reason given there. The one thing the
widget tells the sheet is its state: the dynamic property `overBudget`, set
before the frame is first polished and never changed, which the sheet's
`[overBudget="true"]` rule turns into the warning border.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Context, Decimal

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from mangatl.domain.budget import Budget, page_estimate
from mangatl.domain.money import Usd
from mangatl.ui import tokens_gen
from mangatl.ui.labels import plain_label

__all__ = ["CostEstimate", "NoProvider", "format_usd"]

OBJECT_NAME = "summary-cost-estimate"
OVER_BUDGET = "The estimate is over budget."
#: More pages than this is "more pages than a chapter" (AC-4); exactly this is not.
CHAPTER_PAGE_LIMIT = 200

_CENT = Decimal("0.01")


def format_usd(amount: Usd) -> str:
    """`$1,234.57`: dollars with thousands commas and exactly two decimals.

    A fraction of a cent rounds **up**; a whole number of cents is unchanged.
    The context's precision is widened to the amount's own size, so no amount
    is too large to quantize exactly.
    """
    context = Context(prec=max(28, amount.amount.adjusted() + 3))
    cents = amount.amount.quantize(_CENT, rounding=ROUND_CEILING, context=context)
    return f"${cents:,.2f}"


@dataclass(frozen=True)
class NoProvider:
    """No model to price against (MT-100 C-6); `reason` is the
    `ProviderError`'s message - or `NO_MODELS` - saying why."""

    reason: str


class CostEstimate(QFrame):
    """The estimate for `pages` pages on `model`, and the budget it is held to.

    `model` is a `domain.rates.RATES` id, or `NoProvider` when none can be
    chosen: then there is no figure, nothing is over budget, and the estimate
    line says why.
    """

    def __init__(self, pages: int, model: str | NoProvider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        noun = "page" if pages == 1 else "pages"
        if isinstance(model, NoProvider):
            budget = Budget()
            self._over_budget = False
            stop = "" if model.reason.endswith(".") else "."
            estimate_line = f"No estimate: {model.reason}{stop}"
            warning = "That is more pages than a chapter."
        else:
            budget = Budget(page_estimate=page_estimate(model))
            estimate = budget.project((), pages).remaining_chapter
            self._over_budget = estimate > budget.ceiling
            shown = format_usd(estimate)
            estimate_line = f"Estimated for {pages} {noun} with {model}: {shown}."
            warning = f"That is more pages than a chapter. Estimated cost is {shown}."

        self.setObjectName(OBJECT_NAME)
        # Read by theme.qss's [overBudget="true"] rule; set before first polish
        # and never changed, so no re-polish is needed.
        self.setProperty("overBudget", self._over_budget)

        budget_line = f"Budget {format_usd(budget.ceiling)}."
        if self._over_budget:
            budget_line = f"{budget_line} {OVER_BUDGET}"
        parts = [
            ("cost-estimate", estimate_line),
            ("cost-budget", budget_line),
        ]
        if pages > CHAPTER_PAGE_LIMIT:
            parts.append(("cost-page-warning", warning))

        column = QVBoxLayout(self)
        pad = tokens_gen.SPACE_S3
        column.setContentsMargins(pad, pad, pad, pad)
        column.setSpacing(tokens_gen.SPACE_S1)
        for name, text in parts:
            column.addWidget(plain_label(name, text))
        self.lines = tuple(text for _, text in parts)
        self.setAccessibleName("\n".join(self.lines))

    @property
    def over_budget(self) -> bool:
        """The estimate exceeds the budget (inclusive ceiling); MT-059 reads it."""
        return self._over_budget
