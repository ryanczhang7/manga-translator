"""US dollar amounts, as a value type with one rule.

MT-001's walking skeleton needs one real pure function for `tests/core/` to
test and for the `coverage-core` gate to hold at 100%. `Usd` is that, and it is
not a throwaway: the brief's budget ceiling is in dollars and every API call is
priced into a ledger, so a money type that refuses nonsense is load-bearing
later. **MT-012 owns the cost ledger and MT-013 the budget ceiling**; either may
extend this type. Neither should have to fix it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = ["Usd"]


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
