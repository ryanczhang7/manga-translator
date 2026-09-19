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


# -- MT-012: the additive half. `Usd` itself is unchanged (PO-2) ----------------
#
# The seven tests above are MT-001's and are untouched: `Usd` still holds a
# `Decimal` and still renders four places. PO-2 is explicit that the float to
# remove is `llm_call.cost_usd REAL`, not this type - `Decimal("0.1") +
# Decimal("0.2") == Decimal("0.3")` exactly, so the argument the micro-dollar
# rule was written against never applied here.
#
# What MT-012 adds is the bridge to the ledger's integers: `from_micro`,
# `from_tokens`, `micro` and `__add__`. Every number below is read out of
# MT-012's `## Contract`.


def test_a_whole_number_of_micro_dollars_becomes_an_exact_decimal_amount() -> None:
    # AC-1's figure, arriving from the ledger side.
    assert Usd.from_micro(64875).amount == Decimal("0.064875")
    assert str(Usd.from_micro(64875)) == "$0.0649"


def test_zero_micro_dollars_is_zero_dollars() -> None:
    assert Usd.from_micro(0) == Usd(Decimal(0))


def test_a_negative_number_of_micro_dollars_is_refused_like_any_other_amount() -> None:
    # The one rule `Usd` carries has to survive the new constructor: a ledger
    # row with a negative cost would silently buy headroom against the ceiling.
    with pytest.raises(ValueError, match="must not be negative"):
        Usd.from_micro(-1)


def test_micro_dollars_round_trip_through_the_amount_without_loss() -> None:
    for micro in (0, 1, 13, 9381, 64875, 279280, 2_000_000):
        assert Usd.from_micro(micro).micro() == micro


def test_pricing_one_category_multiplies_tokens_by_the_rate_per_million() -> None:
    # 1,500 cache-write tokens at $6.25/MTok are 9,375 micro-dollars: the
    # per-million cancels, so tokens x rate is already micro-dollars.
    assert Usd.from_tokens(1500, Decimal("6.25")).amount == Decimal("0.009375")
    assert Usd.from_tokens(3600, Decimal("5.00")).amount == Decimal("0.018")
    assert Usd.from_tokens(0, Decimal("25.00")) == Usd(Decimal(0))


def test_one_category_is_kept_exactly_rather_than_rounded_on_the_way_in() -> None:
    """PO-4: never quantise per category.

    1,501 cache-write tokens at $6.25/MTok are 9,381.25 micro-dollars, and the
    quarter has to survive until the four categories have been summed.
    """
    kept = Usd.from_tokens(1501, Decimal("6.25"))

    assert kept.amount == Decimal("0.00938125")
    assert kept.amount * 1_000_000 == Decimal("9381.25")


def test_converting_to_micro_dollars_rounds_half_up_rather_than_to_even() -> None:
    """PO-4's single, final quantisation, at the one place it happens.

    `Decimal.quantize` rounds half to **even** unless told otherwise, so an
    amount of exactly 12.5 micro-dollars is where the two rules disagree: 13
    under `ROUND_HALF_UP`, 12 under the default.
    """
    assert Usd(Decimal("0.0000125")).micro() == 13
    assert Usd(Decimal("0.00938125")).micro() == 9381
    assert Usd(Decimal("0.0000005")).micro() == 1


def test_two_amounts_add_to_their_exact_decimal_sum() -> None:
    # PO-2's own claim, pinned: `Decimal` does not have the property the
    # micro-dollar rule was written to avoid.
    assert Usd(Decimal("0.1")) + Usd(Decimal("0.2")) == Usd(Decimal("0.3"))
    assert (Usd(Decimal("0.1")) + Usd(Decimal("0.2"))).amount == Decimal("0.3")


def test_adding_produces_a_usd_and_leaves_both_operands_alone() -> None:
    left, right = Usd(Decimal("0.015006")), Usd(Decimal("0.006215"))

    total = left + right

    assert isinstance(total, Usd)
    assert total == Usd(Decimal("0.021221"))
    assert total.micro() == 21221
    assert (left.amount, right.amount) == (Decimal("0.015006"), Decimal("0.006215"))


def test_adding_zero_changes_nothing() -> None:
    assert Usd(Decimal("2.00")) + Usd(Decimal(0)) == Usd(Decimal("2.00"))
