"""The budget guard: a projection, a ceiling, and the basis the projection has.

`architecture.md` D6 - budget enforcement is a domain rule, not a warning - and
MT-013's decisive design point: **the guard runs before the call, on a
projection, not after it on a total.** A guard that notices the overrun after
paying for it has not guarded anything.

Pure arithmetic over `Usd`. This module imports nothing of ours outside
`domain` - `domain.money`, and since MT-100 `domain.rates` and
`domain.translation` to price the per-page estimate - which the `domain is
independent` import contract requires and which is also why the ceiling is a
default *argument* rather than a lookup: where a real ceiling comes from is
MT-044's question. The domain knows *models* (the rate table keys on them) but
not *providers*: which model a provider calls is `translate.provider`'s fact,
and the caller passes `page_estimate(model_id)` in (MT-100 C-1).

**It raises nothing.** A refusal is a `Decision` with `permitted=False`, not an
exception - an exception can be swallowed by a caller, and a returned decision
carries the three numbers that justify it to MT-018.

Three judgements are settled in MT-013's `## Contract` and are implemented here
rather than re-decided:

- The comparison is ``spent + projection.next_call <= ceiling``, **inclusive**:
  landing exactly on the ceiling is permitted.
- The per-page estimate is `page_estimate(model_id)`: the design-A page
  (`docs/wiki/cost-model.awk`) priced at that model's rates and rounded **up**
  to the cent - $0.06 on claude-opus-5 ($0.05673), $0.03 on
  gemini-3.1-pro-preview ($0.025692). An estimate that errs low lets a run
  start that it cannot finish. `BOOTSTRAP_PAGE_ESTIMATE`, what `Budget()`
  projects when no model is named, is the dearest listed model's figure, so an
  unnamed model errs high (MT-100 AC-7).
- The observed mean rounds **up** to the micro-dollar, for that same reason.
  It is the first division this product performs on money.

**No defensive branches, by design.** A $0.00 ceiling, an empty `priced_calls`
and a `pages_remaining` of 0 all fall out of the arithmetic: the zero ceiling
refuses because $0.00 + $0.06 is not <= $0.00, and the estimate branch already
keeps `reduce` from ever seeing an empty sequence. `domain` sits under
`coverage-core`'s `--cov-fail-under=100` with branch coverage on, and
`mypy --strict` runs with `warn_unreachable`, so an unreachable arm fails two
gates - the same rule `money.py` and `events.py` record in their own docstrings.

**`Usd` is not extended by this module** (MT-013 `## Contract` RED-A1). Every
figure is reachable with the existing API: fold with
`functools.reduce(operator.add, ...)` (`sum()` does not work on `Usd`), take
`.micro()` to get integers, divide with integer ceiling division, and come back
through `Usd.from_micro`.
"""

from __future__ import annotations

import functools
import operator
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from mangatl.domain.money import Usd
from mangatl.domain.rates import RATES, price
from mangatl.domain.translation import TokenUsage

__all__ = [
    "BOOTSTRAP_PAGE_ESTIMATE",
    "DEFAULT_CEILING",
    "DESIGN_A_PAGE_TOKENS",
    "MIN_SAMPLES_FOR_PROJECTION",
    "Budget",
    "Decision",
    "Projection",
    "page_estimate",
]

#: The brief's hard budget: under $2 per ~20-page chapter (AC-8).
DEFAULT_CEILING: Usd = Usd(Decimal("2.00"))

#: cost-model.awk design A, per page: 2,296 image + 500 OCR + 900 rolling
#: context as uncached input; the 1,500-token prefix as a cache READ (the awk
#: writes it once a chapter and reads it 19 times - per page that is a read);
#: 700 visible + 800 thinking as output; no cache write.
DESIGN_A_PAGE_TOKENS: TokenUsage = TokenUsage(
    input_tokens=3696, output_tokens=1500, cache_read_tokens=1500, cache_write_tokens=0
)

#: One cent, in micro-dollars: the unit `page_estimate` rounds up to.
_CENT_MICRO: int = 10_000


def page_estimate(model_id: str) -> Usd:
    """What one page is assumed to cost on `model_id` before any call is priced.

    `price(model_id, DESIGN_A_PAGE_TOKENS).cost` rounded **up** to the cent,
    with exact integer ceiling division. Priced at call time against
    `domain.rates.RATES`, so it always reads the table `price` reads. Raises
    `domain.rates.UnknownModel` (from `price`, unchanged) for an id the table
    does not list. Strictly positive for every listed model, which is what
    makes a $0.00 ceiling refuse its very first consultation (MT-013 AC-7)
    without a special case for zero.
    """
    cost = price(model_id, DESIGN_A_PAGE_TOKENS).cost
    return Usd.from_micro(-(-cost.micro() // _CENT_MICRO) * _CENT_MICRO)


#: What `Budget()` projects when no model is named: the dearest listed model's
#: `page_estimate`, so an unnamed model errs high. $0.06 today (claude-opus-5).
BOOTSTRAP_PAGE_ESTIMATE: Usd = max(page_estimate(model_id) for model_id in RATES)

#: How many priced calls it takes before the projection extrapolates from them
#: instead of from the estimate. A **floor**, which two meets: one page is not a
#: sample, and a single wordless page would project the rest of the chapter at
#: nearly zero and switch the guard off for every page after it.
MIN_SAMPLES_FOR_PROJECTION: int = 2


@dataclass(frozen=True)
class Projection:
    """What the next call, and the rest of the chapter, are expected to cost.

    `basis` is **reported, not inferred**: MT-018 shows the user "projected
    $1.30 (estimated)" against "(from 5 pages)", and those are different claims
    about the same number. `sample_count` is how many priced calls were
    available, whichever basis was used.

    Frozen for `events.py`'s reason: MT-015 hands the run's stream to a UI
    thread, and a consumer that can rewrite a projection can rewrite the
    evidence a refusal was based on.
    """

    next_call: Usd
    remaining_chapter: Usd
    basis: Literal["estimate", "observed"]
    sample_count: int


@dataclass(frozen=True)
class Decision:
    """The guard's answer, carrying everything needed to explain it.

    `reason` is the refusal's explanation and is `None` on a permit. A decision
    that carried only a boolean would force every caller to keep the three
    inputs alive to render it.
    """

    permitted: bool
    reason: str | None
    spent: Usd
    ceiling: Usd
    projection: Projection


class Budget:
    """A chapter ceiling, and the two questions asked against it."""

    def __init__(
        self, ceiling: Usd = DEFAULT_CEILING, *, page_estimate: Usd = BOOTSTRAP_PAGE_ESTIMATE
    ) -> None:
        self.ceiling = ceiling
        #: What one page is projected at while fewer than
        #: `MIN_SAMPLES_FOR_PROJECTION` calls are priced (MT-100 C-1).
        self.page_estimate = page_estimate

    def project(self, priced_calls: Sequence[Usd], pages_remaining: int) -> Projection:
        """Project the next call and the rest of the chapter (AC-5, AC-6).

        Fewer than `MIN_SAMPLES_FOR_PROJECTION` priced calls project from
        this budget's `page_estimate` and say so; from there on the projection is
        the mean of the observed costs, rounded **up** to the micro-dollar.
        `priced_calls` is read and never mutated, so a tuple and a list are
        equally welcome.

        The remainder is the **rounded** mean times the pages left, not the
        remainder of an unrounded mean: the figure a caller sees for one page
        and the figure it sees for the chapter have to be the same arithmetic.
        """
        sample_count = len(priced_calls)
        basis: Literal["estimate", "observed"]
        if sample_count < MIN_SAMPLES_FOR_PROJECTION:
            next_call = self.page_estimate
            basis = "estimate"
        else:
            total = functools.reduce(operator.add, priced_calls)
            # Integer ceiling division: exact, no `Decimal` context, no
            # rounding mode, no float. Every `Usd` the ledger produces is
            # already a whole number of micro-dollars.
            next_call = Usd.from_micro(-(-total.micro() // sample_count))
            basis = "observed"
        return Projection(
            next_call=next_call,
            remaining_chapter=Usd.from_micro(next_call.micro() * pages_remaining),
            basis=basis,
            sample_count=sample_count,
        )

    def check(self, spent: Usd, projection: Projection) -> Decision:
        """Permit or refuse the next call, **before** it is made (AC-1, AC-2).

        The comparison is inclusive: a call that lands exactly on the ceiling is
        the last one the chapter can afford, and it is affordable. A refusal
        names the projection, the spend and the ceiling, because a refusal that
        does not say why is not actionable.
        """
        projected_total = spent + projection.next_call
        permitted = projected_total <= self.ceiling
        reason: str | None = None
        if not permitted:
            reason = (
                f"the projected next call of {projection.next_call} on top of"
                f" {spent} already spent would reach {projected_total},"
                f" over the {self.ceiling} ceiling for this chapter"
            )
        return Decision(
            permitted=permitted,
            reason=reason,
            spent=spent,
            ceiling=self.ceiling,
            projection=projection,
        )
