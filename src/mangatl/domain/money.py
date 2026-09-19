"""US dollar amounts, as a value type with one rule.

MT-001's walking skeleton needs one real pure function for `tests/core/` to
test and for the `coverage-core` gate to hold at 100%. `Usd` is that, and it is
not a throwaway: the brief's budget ceiling is in dollars and every API call is
priced into a ledger, so a money type that refuses nonsense is load-bearing
later. **MT-012 owns the cost ledger and MT-013 the budget ceiling**; either may
extend this type. Neither should have to fix it.

**MT-012 extended it and changed nothing** (PO-2). The float the ledger had to
lose was `llm_call.cost_usd REAL`, an IEEE-754 double, not this type: `Decimal`
never had the `0.1 + 0.2 != 0.3` property the micro-dollar rule was written
against. So `amount` is still an exact `Decimal`, `__str__` still renders four
places, and what arrived is the **bridge to the ledger's integers** -
`from_micro`, `from_tokens`, `micro` and `__add__`.

`micro()` is the single place MT-012's PO-4 quantisation happens: every
category is multiplied out exactly, the categories are summed exactly, and the
total is rounded **once**, `ROUND_HALF_UP`. Rounding per category turns 12.50 +
0.50 into 14 rather than 13, and Python's own default - `ROUND_HALF_EVEN` -
turns 12.50 into 12.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

__all__ = ["Usd"]

#: Dollars are stored on disk as a whole number of millionths of a dollar, so
#: every conversion in this module is a shift of the decimal point by six
#: places. `scaleb` shifts the exponent rather than dividing, so it introduces
#: no rounding of its own.
_MICRO_EXPONENT = 6

#: The quantum `micro()` rounds to: one whole micro-dollar.
_ONE = Decimal(1)


@dataclass(frozen=True, order=True)
class Usd:
    """A non-negative amount of US dollars.

    The rule: spend is never negative. A negative cost record is not a refund,
    it is a bug in whoever computed it, and it would silently buy headroom
    against the budget ceiling the whole product is built around.
    """

    amount: Decimal

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Usd amount must not be negative, got {self.amount}")

    def __str__(self) -> str:
        return f"${self.amount:.4f}"

    @classmethod
    def from_micro(cls, micro: int) -> Usd:
        """The amount a ledger row holds: a whole number of micro-dollars.

        The inverse of `micro()` for every value `micro()` can produce, which is
        what lets a chapter total be summed as integers in SQL and come back as
        a `Usd` without a rounding step. The one rule still applies - a negative
        count raises, from `__post_init__`, rather than quietly becoming a
        credit.
        """
        return cls(Decimal(micro).scaleb(-_MICRO_EXPONENT))

    @classmethod
    def from_tokens(cls, tokens: int, rate_per_mtok: Decimal) -> Usd:
        """One category's cost: `tokens x rate_per_mtok`, **not** rounded.

        The per-million in the rate and the per-million in a micro-dollar
        cancel, so `tokens x rate` is already a count of micro-dollars and the
        only arithmetic left is the shift. The result is deliberately not
        quantised: 1,501 cache-write tokens at $6.25/MTok are 9,381.25
        micro-dollars, and that quarter has to survive until the four
        categories have been added up (MT-012 PO-4).
        """
        return cls((Decimal(tokens) * rate_per_mtok).scaleb(-_MICRO_EXPONENT))

    def micro(self) -> int:
        """This amount as a whole number of micro-dollars, for the ledger.

        **The one place rounding happens** (MT-012 RED-A2). `ROUND_HALF_UP` is
        passed explicitly because `Decimal.quantize` rounds half to *even* when
        nothing says otherwise, and the two rules disagree on exactly the
        amounts a per-token rate produces: 12.5 micro-dollars is 13 here and 12
        under the default. Lossless for any amount that is already a whole
        number of micro-dollars, which is every amount `from_micro` and
        `rates.price` produce.
        """
        return int(self.amount.scaleb(_MICRO_EXPONENT).quantize(_ONE, rounding=ROUND_HALF_UP))

    def __add__(self, other: Usd) -> Usd:
        """The exact decimal sum, as a new `Usd`; neither operand is touched.

        **No `isinstance` guard and no `return NotImplemented`** (MT-012
        RED-A6). `Usd` lives under `coverage-core`'s `--cov-fail-under=100` with
        branch coverage on and nothing in this product adds a non-`Usd` to one,
        so a guard's false branch would be unreachable - and `mypy --strict`
        with `warn_unreachable` says so too. The consequence is real and worth
        stating: `sum()` starts from the int `0`, so it does **not** work on
        `Usd`. Fold with `functools.reduce(operator.add, ...)`.
        """
        return Usd(self.amount + other.amount)
