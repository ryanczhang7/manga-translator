"""`mangatl.domain.rates`: what one call costs, and the table that says so.

Covers **AC-1** (the worked example prices to exactly 64,875 micro-dollars),
the pricing half of **AC-5** (an unknown model id raises a named error that
identifies it) and **AC-7** (the table carries a version and both models in all
four categories, and the loader rejects a table missing any of them). The
store-side halves - "nothing is recorded", the ledger columns, the append-only
triggers, the chapter total - are in `tests/core/test_ledger.py`.

**Oracle partition: entirely mechanical.** Every number below is *read out of*
MT-012's `## Contract`, never re-derived here:

- opus-5: input 5.00, output 25.00, cache write 6.25, cache read 0.50 per MTok;
  sonnet-5: 2.00 / 10.00 / 2.50 / 0.20 (`## Contract`, "Rates as published",
  transcribed there from `docs/wiki/stack.md` §3 line 330).
- AC-1's figure is `3600x5 + 1500x25 + 1500x6.25 + 0x0.50` = **64,875**
  micro-dollars (PO-1). Asserted as that integer and as `Decimal("0.064875")` -
  never as a sign, a range or a `pytest.approx`.
- The rounding rule is PO-4: each category exact as a `Decimal`, the four summed
  **exactly**, quantised **once** at the end with `ROUND_HALF_UP`.

RED verified the arithmetic outside this framework before the module existed
(see `## Handoff: RED -> GREEN`, "Control expected values"); the figures are
claims until GREEN runs them against the shipped `rates.py`.

**`price` takes `TokenUsage`, never the SDK's `Usage`** (PO-3). Every
`TokenUsage` below is built with keyword arguments on purpose: the field order
is `(input, output, cache_read, cache_write)` - **read before write** - while
`llm_call` and `CostRecord` order them **write before read**, and that
asymmetry is the factor-of-12.5 error `domain/translation.py` warns about.
`test_swapping_the_two_cache_counts...` is what makes the swap observable.

**Timing.** There is no `pytest-timeout` in this project and no per-test
timeout, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. Nothing here touches the filesystem,
sqlite, the network or a model - it is `Decimal` arithmetic over a mapping of
eight rates.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from mangatl.domain.money import Usd
from mangatl.domain.rates import (
    RATE_TABLE_VERSION,
    RATES,
    CostRecord,
    IncompleteRateTable,
    ModelRates,
    UnknownModel,
    load_rates,
    price,
)
from mangatl.domain.translation import TokenUsage

#: AC-1's usage, exactly as the criterion states it: input 3,600; output 1,500;
#: cache-write 1,500; cache-read 0.
_AC1_USAGE = TokenUsage(
    input_tokens=3600, output_tokens=1500, cache_read_tokens=0, cache_write_tokens=1500
)

#: The four category keys AC-7 means by "all four categories". They are the
#: `ModelRates` field names, so the loader's error message names something a
#: reader can find in the code.
_CATEGORIES = (
    "input_per_mtok",
    "output_per_mtok",
    "cache_write_per_mtok",
    "cache_read_per_mtok",
)

#: A complete, *made-up* table for the loader tests. Deliberately not the
#: published rates: AC-7 is about the loader, and a fixture that happened to
#: equal `RATES` would let a `load_rates` that ignored its argument pass.
_COMPLETE_TABLE: dict[str, dict[str, Decimal]] = {
    "model-under-test": {
        "input_per_mtok": Decimal("1.00"),
        "output_per_mtok": Decimal("3.00"),
        "cache_write_per_mtok": Decimal("1.25"),
        "cache_read_per_mtok": Decimal("0.10"),
    }
}


def _without(category: str) -> dict[str, dict[str, Decimal]]:
    """`_COMPLETE_TABLE` with one category removed from its one model."""
    rates = dict(_COMPLETE_TABLE["model-under-test"])
    del rates[category]
    return {"model-under-test": rates}


# -- AC-1: the worked example, to the micro-dollar -----------------------------


def test_the_worked_example_prices_to_exactly_64875_micro_dollars() -> None:
    """AC-1, PO-1. `3600x5 + 1500x25 + 1500x6.25 + 0x0.50` per million.

    The criterion read $0.0555 in PLANNED - the same formula with the
    `1500x6.25` cache-write term dropped - and PO-1 fixed it to the formula.
    This is the one assertion in the repository that would notice it drifting
    back, so it pins the integer, the exact `Decimal` and the rendered string
    rather than any one of them.
    """
    record = price("claude-opus-5", _AC1_USAGE)

    assert record.cost.micro() == 64875
    assert record.cost.amount == Decimal("0.064875")
    assert record.cost == Usd(Decimal("0.064875"))
    assert str(record.cost) == "$0.0649"


def test_swapping_the_two_cache_counts_changes_the_price_by_8625_micro_dollars() -> None:
    """The factor-of-12.5 error `TokenUsage`'s docstring warns about, priced.

    Cache **write** is 1.25x the input rate and cache **read** is 0.1x, so the
    identical four counts with the two cache fields exchanged cost
    `1500 x (6.25 - 0.50)` = 8,625 micro-dollars less. A rate table that had
    them the wrong way round, or a `price` that read the wrong field, still
    produces a plausible positive number - it produces *this* one.
    """
    swapped = TokenUsage(
        input_tokens=3600, output_tokens=1500, cache_read_tokens=1500, cache_write_tokens=0
    )

    assert price("claude-opus-5", swapped).cost.micro() == 56250
    assert price("claude-opus-5", _AC1_USAGE).cost.micro() - 56250 == 8625


def test_the_same_usage_on_sonnet_prices_at_the_published_sonnet_rates() -> None:
    """`3600x2 + 1500x10 + 1500x2.50 + 0x0.20` = 25,950 micro-dollars.

    AC-7 requires sonnet-5 in the table; this is what makes its presence mean
    the right eight digits rather than merely "a key exists".
    """
    assert price("claude-sonnet-5", _AC1_USAGE).cost.micro() == 25950


# -- PO-4: sum the four exactly, quantise once ---------------------------------


def test_the_four_categories_are_summed_exactly_before_anything_is_rounded() -> None:
    """PO-4, stated as the case where the two orders disagree.

    2 cache-write tokens on opus are `2 x 6.25` = 12.50 micro-dollars and 1
    cache-read token is 0.50. Summed exactly the total is 13.00, which needs no
    rounding at all. Quantising **per category** first gives `13 + 1` = 14.
    """
    usage = TokenUsage(input_tokens=0, output_tokens=0, cache_read_tokens=1, cache_write_tokens=2)

    assert price("claude-opus-5", usage).cost.micro() == 13


def test_a_total_of_exactly_half_a_micro_dollar_rounds_up_rather_than_to_even() -> None:
    """PO-4's `ROUND_HALF_UP`, against Python's `Decimal` default.

    2 cache-write tokens on opus are exactly 12.5 micro-dollars.
    `ROUND_HALF_UP` gives 13; `ROUND_HALF_EVEN` - which is what
    `Decimal.quantize` does when nothing says otherwise - gives 12.
    """
    usage = TokenUsage(input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=2)

    assert price("claude-opus-5", usage).cost.micro() == 13


def test_the_contracts_own_rounding_example_of_1501_cache_write_tokens() -> None:
    """`## Contract`, PO-4: "1501 x 6.25 = 9,381.25 -> 9,381"."""
    usage = TokenUsage(
        input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=1501
    )

    assert price("claude-opus-5", usage).cost.micro() == 9381


def test_a_page_that_made_no_call_prices_to_zero_rather_than_raising() -> None:
    """The empty end of zero/one/many. `TokenUsage(0, 0, 0, 0)` is what
    `domain/translation.py` says a page of wordless art carries, and it has to
    be a legal thing to price."""
    record = price("claude-opus-5", TokenUsage(0, 0, 0, 0))

    assert record.cost == Usd(Decimal(0))
    assert record.cost.micro() == 0


# -- AC-2's domain half: what a priced record carries ---------------------------


def test_a_priced_record_carries_the_model_all_four_counts_and_the_table_version() -> None:
    """AC-2, the half that exists before anything is written down.

    The four counts are echoed **by name**, so a record that swapped
    `cache_write_tokens` and `cache_read_tokens` on the way into the ledger is
    caught here and not only in the price.
    """
    record = price("claude-opus-5", _AC1_USAGE)

    assert isinstance(record, CostRecord)
    assert record.model_id == "claude-opus-5"
    assert record.input_tokens == 3600
    assert record.output_tokens == 1500
    assert record.cache_write_tokens == 1500
    assert record.cache_read_tokens == 0
    assert record.rate_table_version == RATE_TABLE_VERSION


# -- AC-5: an unknown model is named, loudly ------------------------------------


@pytest.mark.parametrize("model_id", ["claude-haiku-9", "gpt-9", "claude-opus-4"])
def test_pricing_a_model_absent_from_the_table_raises_unknown_model_naming_it(
    model_id: str,
) -> None:
    """AC-5. "A silently-zero-priced call is the worst possible failure of this
    module" - so the error is a named type, and it carries the model id,
    because "unknown model" without the id tells the user nothing to do.

    `claude-opus-4` is in the list on purpose: it is the near miss, the id a
    stale config or a typo actually produces, and a `price` that fell back to
    the nearest key or to opus-5's rates would pass the other two.
    """
    with pytest.raises(UnknownModel) as excinfo:
        price(model_id, _AC1_USAGE)

    assert model_id in str(excinfo.value), str(excinfo.value)


def test_an_empty_model_id_is_refused_rather_than_priced_at_zero() -> None:
    """The degenerate id, which no message can usefully quote - so this asserts
    only that it raises. An empty `chapter.model_id` is NULL until MT-013
    writes one (`store/schema.py`, PO-8), so this is a reachable state."""
    with pytest.raises(UnknownModel):
        price("", _AC1_USAGE)


# -- AC-7: the table, its version, and the loader that refuses a gap ------------


def test_the_rate_table_carries_the_version_identifier_the_contract_pins() -> None:
    """AC-2's last clause depends on this existing at all: a ledger that cannot
    say which table priced a call cannot be reconciled against a bill."""
    assert RATE_TABLE_VERSION == "2026-09-12"


def test_the_shipped_table_carries_both_models_in_all_four_categories() -> None:
    """AC-7's first clause, read off the shipped mapping."""
    for model_id in ("claude-opus-5", "claude-sonnet-5"):
        assert model_id in RATES, f"the rate table has {sorted(RATES)}"
        rates = RATES[model_id]
        for category in _CATEGORIES:
            value = getattr(rates, category)
            assert isinstance(value, Decimal), f"{model_id}.{category} is {type(value).__name__}"


def test_the_shipped_rates_are_the_published_ones_to_the_cent() -> None:
    """The eight numbers, transcribed from `## Contract` and asserted exactly.

    `isinstance(..., Decimal)` above would pass against a table of zeroes, and
    a table of zeroes is exactly the silent failure AC-5 is written against.
    """
    opus = RATES["claude-opus-5"]
    assert opus.input_per_mtok == Decimal("5.00")
    assert opus.output_per_mtok == Decimal("25.00")
    assert opus.cache_write_per_mtok == Decimal("6.25")
    assert opus.cache_read_per_mtok == Decimal("0.50")

    sonnet = RATES["claude-sonnet-5"]
    assert sonnet.input_per_mtok == Decimal("2.00")
    assert sonnet.output_per_mtok == Decimal("10.00")
    assert sonnet.cache_write_per_mtok == Decimal("2.50")
    assert sonnet.cache_read_per_mtok == Decimal("0.20")


def test_the_loader_accepts_a_complete_table_and_keeps_the_rates_it_was_given() -> None:
    """AC-7's **negative control**, and it is not optional.

    "The loader rejects an incomplete table" proves nothing on its own - a
    loader that rejected everything would pass it. This is the other half of
    the pair: the same shape, complete, is accepted, and the four values come
    back unchanged rather than defaulted.
    """
    loaded = load_rates(_COMPLETE_TABLE)

    assert set(loaded) == {"model-under-test"}
    assert loaded["model-under-test"] == ModelRates(
        input_per_mtok=Decimal("1.00"),
        output_per_mtok=Decimal("3.00"),
        cache_write_per_mtok=Decimal("1.25"),
        cache_read_per_mtok=Decimal("0.10"),
    )


@pytest.mark.parametrize("missing", _CATEGORIES)
def test_the_loader_rejects_a_table_missing_any_category_for_a_listed_model(
    missing: str,
) -> None:
    """AC-7's second clause, once per category.

    Parametrised rather than written once against a single omission: a loader
    that checked only `input_per_mtok` would pass a single-case test and ship a
    table whose cache rates default to zero - the silent under-pricing AC-5
    exists to prevent, arriving through the loader instead.

    The message names the model **and** the missing category, because the
    actionable fact is which line of the table to fix.
    """
    with pytest.raises(IncompleteRateTable) as excinfo:
        load_rates(_without(missing))

    message = str(excinfo.value)
    assert "model-under-test" in message, message
    assert missing in message, message
