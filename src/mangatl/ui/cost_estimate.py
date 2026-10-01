"""`CostEstimate`: what a chapter is expected to cost, against its budget (MT-058).

`components.md` §2 `CostEstimate`, as amended for PO-1/PO-2: `ChapterSummary`'s
part 5, the *before* to `CostReadout`'s *during*. One line for the estimate, one
for the budget, and - above 200 pages - a warning that this is more pages than a
chapter. Nothing here blocks anything; the Start button is MT-059's.

**The figure is the guard's own.** The estimate is
`Budget().project((), pages).remaining_chapter`, asked at construction: the
number the budget guard itself uses before any call is priced, so the screen
and the guard cannot disagree about whether a chapter fits. No money arithmetic
happens here beyond the one comparison, `estimate > ceiling`, which is inclusive
as `Budget.check` is: an estimate exactly on the ceiling is within budget.

**`format_usd` rounds a fraction of a cent up**, `budget.py`'s direction: the
shown figure exceeds the shown budget exactly when the estimate does, and an
estimate of one or more pages can never read `$0.00` (AC-5). It is exact
`Decimal` throughout - no float.

The over-budget state is carried by the sentence on the budget line
(`accessibility.md` A-10) and by the frame's warning border; there is no glyph.
Text colour is left to the application palette, as in `summary.py`, for the
reason given there.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Context, Decimal

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from mangatl.domain.budget import Budget
from mangatl.domain.money import Usd
from mangatl.ui import tokens_gen
from mangatl.ui.labels import BODY, BODY_STRONG, plain_label

__all__ = ["CostEstimate", "format_usd"]

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


class CostEstimate(QFrame):
    """The estimate for `pages` pages and the budget it is held to."""

    def __init__(self, pages: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(OBJECT_NAME)

        budget = Budget()
        estimate = budget.project((), pages).remaining_chapter
        self._over_budget = estimate > budget.ceiling
        shown = format_usd(estimate)

        noun = "page" if pages == 1 else "pages"
        budget_line = f"Budget {format_usd(budget.ceiling)}."
        if self._over_budget:
            budget_line = f"{budget_line} {OVER_BUDGET}"
        parts = [
            ("cost-estimate", f"Estimated for {pages} {noun}: {shown}.", BODY_STRONG),
            ("cost-budget", budget_line, BODY),
        ]
        if pages > CHAPTER_PAGE_LIMIT:
            parts.append(
                (
                    "cost-page-warning",
                    f"That is more pages than a chapter. Estimated cost is {shown}.",
                    BODY,
                )
            )

        column = QVBoxLayout(self)
        pad = tokens_gen.SPACE_S3
        column.setContentsMargins(pad, pad, pad, pad)
        column.setSpacing(tokens_gen.SPACE_S1)
        for name, text, type_ in parts:
            column.addWidget(plain_label(name, text, type_))
        self.lines = tuple(text for _, text, _ in parts)
        self.setAccessibleName("\n".join(self.lines))

        border = tokens_gen.COLOR_BORDER_SUBTLE
        if self._over_budget:
            border = tokens_gen.COLOR_STATUS_WARNING
        self.setStyleSheet(
            f"QFrame#{OBJECT_NAME} {{"
            f" border: {tokens_gen.BORDER_WIDTH_HAIRLINE}px solid {border};"
            f" border-radius: {tokens_gen.RADIUS_SM}px; }}"
        )

    @property
    def over_budget(self) -> bool:
        """The estimate exceeds the budget (inclusive ceiling); MT-059 reads it."""
        return self._over_budget
