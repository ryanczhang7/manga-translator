"""The one rule `Usd` carries: spend is never negative."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mangatl.domain.money import Usd


def test_a_non_negative_amount_is_accepted_and_kept_exactly() -> None:
    assert Usd(Decimal("1.9375")).amount == Decimal("1.9375")


def test_zero_is_accepted() -> None:
    assert Usd(Decimal("0")).amount == Decimal("0")


def test_a_negative_amount_is_refused() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        Usd(Decimal("-0.0001"))


def test_the_refusal_message_names_the_offending_amount() -> None:
    with pytest.raises(ValueError) as excinfo:
        Usd(Decimal("-2.50"))
    assert "-2.50" in str(excinfo.value)


def test_amounts_order_by_value() -> None:
    assert Usd(Decimal("0.50")) < Usd(Decimal("2.00"))


def test_amounts_are_equal_by_value_and_hashable() -> None:
    assert Usd(Decimal("2.00")) == Usd(Decimal("2.00"))
    assert len({Usd(Decimal("2.00")), Usd(Decimal("2.00"))}) == 1


def test_str_renders_four_decimal_places() -> None:
    # Four, not two: a single page's API cost is a fraction of a cent, and a
    # ledger that rounds each entry to two places sums to the wrong total.
    assert str(Usd(Decimal("0.00035"))) == "$0.0004"
    assert str(Usd(Decimal("2"))) == "$2.0000"
