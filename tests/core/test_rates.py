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

**MT-102** adds the batch tier at the end of this file - its own oracle note
is there. AC-2 of that story is the rule for everything above it: every cost
assertion holds unchanged, and only the two version-string assertions moved,
from `2026-10-12` to `2026-10-28`.

**Timing.** There is no `pytest-timeout` in this project and no per-test
timeout, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. Nothing here touches the filesystem,
sqlite, the network or a model - it is `Decimal` arithmetic over a mapping of
eight rates.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import get_args

import pytest

from mangatl.domain import rates as rates_module
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
    # MT-080 C-4/V-2: bumped in the same commit as the Gemini row. MT-102 AC-4:
    # bumped again with the batch table, to MT-101 D-1's read date.
    assert RATE_TABLE_VERSION == "2026-10-28"


def test_the_shipped_table_carries_both_models_in_all_four_categories() -> None:
    """AC-7's first clause, read off the shipped mapping. MT-080 AC-7 adds
    `gemini-3.1-pro-preview` (V-1: the API's spelling of Gemini 3.1 Pro)."""
    for model_id in ("claude-opus-5", "claude-sonnet-5", "gemini-3.1-pro-preview"):
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


def test_the_gemini_row_is_the_published_paid_tier_under_200k() -> None:
    """MT-080 AC-7, **settled** by V-2 - read out, not derived: the pricing page
    (`ai.google.dev/gemini-api/docs/pricing`, "Last updated 2026-10-09"),
    Gemini 3.1 Pro Preview, paid tier, prompts <=200k: input $2.00, output
    $12.00 (thinking included), cached input $0.20. Cache write is $2.00 = the
    input rate: implicit caching has no write surcharge and the adapter always
    reports `cache_write_tokens=0` (C-3), so the figure is never multiplied and
    carries no invented number.
    """
    row = RATES["gemini-3.1-pro-preview"]
    assert row.input_per_mtok == Decimal("2.00")
    assert row.output_per_mtok == Decimal("12.00")
    assert row.cache_write_per_mtok == Decimal("2.00")
    assert row.cache_read_per_mtok == Decimal("0.20")


#: MT-080 AC-4's fixture usage as `gemini._usage_of` converts it (P=3200, C=700,
#: K=450, T=1300 -> input 2500, output 1750, cache read 700, cache write 0).
_GEMINI_USAGE = TokenUsage(
    input_tokens=2500, output_tokens=1750, cache_read_tokens=700, cache_write_tokens=0
)


def test_a_gemini_call_prices_to_the_hand_computed_figure() -> None:
    """MT-080 AC-7's hand-computed figure, in micro-dollars (tokens x $/MTok):

        input       2500 x  2.00 =  5000
        output      1750 x 12.00 = 21000
        cache write    0 x  2.00 =     0
        cache read   700 x  0.20 =   140
                                  -----
                                  26140   ->  $0.026140

    Every term is already a whole number of micro-dollars, so PO-4's single
    `ROUND_HALF_UP` changes nothing here. DV-2's control: swapping input and
    cache read in `_usage_of` gives 700x2.00 + 1750x12.00 + 2500x0.20 =
    1400 + 21000 + 500 = 22900, so the figure moves.
    """
    record = price("gemini-3.1-pro-preview", _GEMINI_USAGE)

    assert record.cost.micro() == 26140
    assert record.cost == Usd.from_micro(26140)
    assert record.model_id == "gemini-3.1-pro-preview"
    assert record.rate_table_version == "2026-10-28"


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


# == MT-102: the batch tier ===================================================
#
# **Oracle partition** (MT-102 `## Contract`): AC-1 to AC-4 are **settled** -
# every batch figure is read out of MT-101 `## Decided` D-1
# (`docs/wiki/audits/MT-101-gemini-batch.md`, source S2, read 2026-10-28):
# Gemini 3.1 Pro Preview batch, prompts <= 200k: input 1.00, output 6.00
# (thinking included), cache write 1.00, cache read 0.20 ("Same as Standard").
# No figure below is computed as "half the interactive rate": a discount
# derived here would agree with a transcription made by the same derivation.
# AC-5 is **mechanical** and has its control pinned exactly.
#
# The two names this story adds, `BATCH_RATES` and `Pricing`, are read off the
# module object inside each test rather than imported at the top. A top-level
# import of a name that does not exist yet stops the whole file collecting, and
# then not one of the pre-existing assertions above - the ones AC-2 says must
# hold unchanged - would run in RED to show that they still do.


def _batch_rates() -> Mapping[str, ModelRates]:
    """`rates.BATCH_RATES`, looked up when called (see the note above)."""
    table: Mapping[str, ModelRates] = rates_module.BATCH_RATES
    return table


#: A batch-shaped table for the loader test: D-1's row, typed out again from the
#: audit rather than imported, so the test does not lean on the table it guards.
_D1_BATCH_TABLE: dict[str, dict[str, Decimal]] = {
    "gemini-3.1-pro-preview": {
        "input_per_mtok": Decimal("1.00"),
        "output_per_mtok": Decimal("6.00"),
        "cache_write_per_mtok": Decimal("1.00"),
        "cache_read_per_mtok": Decimal("0.20"),
    }
}

_ONE_MILLION_INPUT = TokenUsage(
    input_tokens=1_000_000, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0
)
_ONE_MILLION_OUTPUT = TokenUsage(
    input_tokens=0, output_tokens=1_000_000, cache_read_tokens=0, cache_write_tokens=0
)


# -- AC-1: a batch call is priced at the batch row ------------------------------


def test_a_million_batch_input_tokens_on_gemini_cost_exactly_the_batch_input_rate() -> None:
    """AC-1: `TokenUsage(1_000_000, 0, 0, 0)` at batch is D-1's $1.00 - not the
    interactive $2.00, which is what a `price` ignoring `pricing` returns."""
    record = price("gemini-3.1-pro-preview", _ONE_MILLION_INPUT, pricing="batch")

    assert record.cost == Usd(Decimal("1.00")), str(record.cost)
    assert record.cost.micro() == 1_000_000


def test_a_million_batch_output_tokens_on_gemini_cost_exactly_the_batch_output_rate() -> None:
    """AC-1: `TokenUsage(0, 1_000_000, 0, 0)` at batch is D-1's $6.00 (thinking
    tokens included in output) - not the interactive $12.00."""
    record = price("gemini-3.1-pro-preview", _ONE_MILLION_OUTPUT, pricing="batch")

    assert record.cost == Usd(Decimal("6.00")), str(record.cost)
    assert record.cost.micro() == 6_000_000


def test_a_batch_priced_record_says_batch_and_carries_the_new_table_version() -> None:
    """AC-1's last clause: the tier is on the record, so the ledger (MT-103) can
    say which row priced the call, and the version is the one D-1 dates."""
    record = price("gemini-3.1-pro-preview", _ONE_MILLION_INPUT, pricing="batch")

    assert record.pricing == "batch"
    assert record.rate_table_version == "2026-10-28"
    assert record.model_id == "gemini-3.1-pro-preview"
    assert record.input_tokens == 1_000_000


def test_a_mixed_gemini_page_at_batch_prices_every_category_from_the_batch_row() -> None:
    """AC-1 across all four categories, MT-080's fixture usage at D-1's figures:

        input       2500 x 1.00 =  2500
        output      1750 x 6.00 = 10500
        cache write    0 x 1.00 =     0
        cache read   700 x 0.20 =   140
                                 -----
                                 13140   ->  $0.013140

    The cache-read term is the one D-1 does *not* discount; a batch row that
    halved it (the story's first-draft 0.10) prices this page at 13070.
    """
    record = price("gemini-3.1-pro-preview", _GEMINI_USAGE, pricing="batch")

    assert record.cost.micro() == 13140


# -- AC-2: the default is the interactive tier, unchanged ----------------------


def test_pricing_with_no_tier_argument_records_the_standard_tier() -> None:
    """AC-2: every caller that predates this story passes no `pricing`, and its
    record must say `"standard"` - and cost what it cost before (the cost
    assertions above are AC-2's other half, unchanged)."""
    record = price("gemini-3.1-pro-preview", _GEMINI_USAGE)

    assert record.pricing == "standard"
    assert record.cost.micro() == 26140


def test_asking_for_the_standard_tier_explicitly_is_the_same_record_as_the_default() -> None:
    """AC-2: `pricing="standard"` and no argument are one tier, not two paths."""
    for model_id in ("claude-opus-5", "claude-sonnet-5", "gemini-3.1-pro-preview"):
        assert price(model_id, _AC1_USAGE, pricing="standard") == price(model_id, _AC1_USAGE)


# -- AC-3: a model with no batch row cannot be batch-priced ---------------------


def test_batch_pricing_a_claude_model_raises_unknown_model_naming_model_tier_and_table() -> None:
    """AC-3. `claude-opus-5` has an interactive row and no batch row, so a
    `price` that fell back to `RATES` would price it - at the interactive rate,
    silently, under a record saying "batch".

    The message names the model, the tier (the contract's ` at batch rates`),
    and the **batch** table's models. `claude-sonnet-5` must be absent: it is in
    `RATES` and not in `BATCH_RATES`, so a message that listed the interactive
    table - which also contains gemini - is told apart from the right one.
    """
    with pytest.raises(UnknownModel) as excinfo:
        price("claude-opus-5", _AC1_USAGE, pricing="batch")

    message = str(excinfo.value)
    assert "'claude-opus-5'" in message, message
    assert " at batch rates" in message, message
    assert "gemini-3.1-pro-preview" in message, message
    assert "claude-sonnet-5" not in message, message


def test_an_unknown_model_at_the_standard_tier_says_standard_not_batch() -> None:
    """The contract's ` at {pricing} rates`, from the other side: a message that
    hard-coded "batch" would pass AC-3's test and mislabel every interactive
    miss."""
    with pytest.raises(UnknownModel) as excinfo:
        price("claude-opus-4", _AC1_USAGE)

    message = str(excinfo.value)
    assert " at standard rates" in message, message
    assert " at batch rates" not in message, message


def test_a_model_in_neither_table_is_refused_at_batch_too() -> None:
    """AC-3's general case: an id no table lists raises at the batch tier."""
    with pytest.raises(UnknownModel) as excinfo:
        price("gpt-9", _AC1_USAGE, pricing="batch")

    assert "'gpt-9'" in str(excinfo.value), str(excinfo.value)


# -- AC-4: a new version, and the batch table built by the guarding loader -----


def test_the_rate_table_version_is_later_than_the_one_before_the_batch_rows() -> None:
    """AC-4: a ledger row priced by the new table must not carry the old id."""
    assert date.fromisoformat(RATE_TABLE_VERSION) > date(2026, 10, 12), RATE_TABLE_VERSION


def test_the_shipped_batch_table_is_d1s_row_exactly() -> None:
    """AC-1/AC-4, settled: the one batch row, read out of D-1. Also pins that the
    batch table lists **only** gemini (Claude batch rows are out of scope)."""
    batch = _batch_rates()

    assert set(batch) == {"gemini-3.1-pro-preview"}
    assert batch["gemini-3.1-pro-preview"] == ModelRates(
        input_per_mtok=Decimal("1.00"),
        output_per_mtok=Decimal("6.00"),
        cache_write_per_mtok=Decimal("1.00"),
        cache_read_per_mtok=Decimal("0.20"),
    )


@pytest.mark.parametrize("missing", _CATEGORIES)
def test_the_loader_rejects_a_batch_shaped_table_missing_any_category(missing: str) -> None:
    """AC-4: the loader that guards `RATES` guards a batch-shaped table too.

    **Green on arrival** - `load_rates` already exists (MT-012 AC-7) - so it is
    earned by a probe recorded in the story's handoff, not by RED's import
    failure.
    """
    rates = dict(_D1_BATCH_TABLE["gemini-3.1-pro-preview"])
    del rates[missing]

    with pytest.raises(IncompleteRateTable) as excinfo:
        load_rates({"gemini-3.1-pro-preview": rates})

    message = str(excinfo.value)
    assert "gemini-3.1-pro-preview" in message, message
    assert missing in message, message


# -- AC-5: a batch row is a discount, or a transcription error -----------------


def _batch_violations(
    batch: Mapping[str, ModelRates], interactive: Mapping[str, ModelRates]
) -> list[str]:
    """AC-5's rule, as a list of what breaks it (empty means it holds).

    Input and output **strictly** less; cache write and cache read **no
    greater** - cache read is "Same as Standard" (D-1), so equality there is the
    published figure, not an error. A batch model with no interactive row is a
    violation too: it has nothing to be a discount on.
    """
    violations: list[str] = []
    for model_id, row in batch.items():
        base = interactive.get(model_id)
        if base is None:
            violations.append(f"{model_id}: no interactive row")
            continue
        for category in ("input_per_mtok", "output_per_mtok"):
            if not getattr(row, category) < getattr(base, category):
                violations.append(f"{model_id}.{category} is not a discount")
        for category in ("cache_write_per_mtok", "cache_read_per_mtok"):
            if getattr(row, category) > getattr(base, category):
                violations.append(f"{model_id}.{category} is dearer than interactive")
    return violations


def test_every_batch_row_is_cheaper_on_input_and_output_and_never_dearer_on_cache() -> None:
    """AC-5 over the shipped tables. Non-vacuous: the batch table must not be
    empty, or the loop would hold over nothing."""
    batch = _batch_rates()

    assert batch, "BATCH_RATES is empty"
    assert _batch_violations(batch, RATES) == []


def test_the_gemini_batch_cache_read_rate_equals_the_interactive_one() -> None:
    """AC-5's control, pinned exactly: D-1's "Same as Standard". This is the
    figure a "strictly less on all four" rule would reject, and the story's
    first-draft 0.10 would have passed."""
    batch_read = _batch_rates()["gemini-3.1-pro-preview"].cache_read_per_mtok

    assert batch_read == RATES["gemini-3.1-pro-preview"].cache_read_per_mtok
    assert batch_read == Decimal("0.20")


def test_the_ac5_rule_rejects_a_dearer_or_undiscounted_row_and_accepts_d1s() -> None:
    """The negative control for `_batch_violations` itself, which runs without
    `BATCH_RATES`: a rule that never fires makes AC-5's test pass on any table.

    Fed D-1's row against MT-080's interactive row it reports nothing; fed a
    row whose input is not discounted, whose output is dearer, whose cache read
    is dearer, and a model with no interactive row, it reports each of them.
    """
    interactive = load_rates(
        {
            "gemini-3.1-pro-preview": {
                "input_per_mtok": Decimal("2.00"),
                "output_per_mtok": Decimal("12.00"),
                "cache_write_per_mtok": Decimal("2.00"),
                "cache_read_per_mtok": Decimal("0.20"),
            }
        }
    )
    assert _batch_violations(load_rates(_D1_BATCH_TABLE), interactive) == []

    wrong = load_rates(
        {
            "gemini-3.1-pro-preview": {
                "input_per_mtok": Decimal("2.00"),
                "output_per_mtok": Decimal("12.01"),
                "cache_write_per_mtok": Decimal("1.00"),
                "cache_read_per_mtok": Decimal("0.21"),
            },
            "claude-opus-5": dict(_D1_BATCH_TABLE["gemini-3.1-pro-preview"]),
        }
    )
    assert _batch_violations(wrong, interactive) == [
        "gemini-3.1-pro-preview.input_per_mtok is not a discount",
        "gemini-3.1-pro-preview.output_per_mtok is not a discount",
        "gemini-3.1-pro-preview.cache_read_per_mtok is dearer than interactive",
        "claude-opus-5: no interactive row",
    ]


# -- The contract's shape ------------------------------------------------------


def test_the_module_exports_the_batch_table_and_the_tier_type() -> None:
    """`## Contract`: `__all__` gains `BATCH_RATES` and `Pricing`, and the tier
    type is exactly the two tiers."""
    assert "BATCH_RATES" in rates_module.__all__
    assert "Pricing" in rates_module.__all__
    assert get_args(rates_module.Pricing) == ("standard", "batch")


def test_cost_record_gains_pricing_as_its_last_field_defaulting_to_standard() -> None:
    """`## Contract`: existing fields unchanged and in order, `pricing` last and
    defaulted, so the three tests that build `CostRecord` by keyword get
    `"standard"` without being edited."""
    fields = dataclasses.fields(CostRecord)

    assert [f.name for f in fields] == [
        "model_id",
        "input_tokens",
        "output_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
        "cost",
        "rate_table_version",
        "pricing",
    ]
    assert fields[-1].default == "standard"

    record = CostRecord(
        model_id="claude-opus-5",
        input_tokens=1,
        output_tokens=1,
        cache_write_tokens=0,
        cache_read_tokens=0,
        cost=Usd.from_micro(30),
        rate_table_version="test",
    )
    assert record.pricing == "standard"
