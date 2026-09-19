"""What one API call costs, and the published table that says so.

MT-012: "show what the run cost, per chapter and running, so the $2/chapter
constraint is observable rather than assumed". This module is the arithmetic
half - `store/ledger.py` is the half that writes it down.

**Token counts in, an exact `Usd` out.** `price` takes
`mangatl.domain.translation.TokenUsage` and never the SDK's
`anthropic.types.Usage` (MT-012 PO-3): `translate/client.py` is where the SDK
type is mapped to the domain one and its docstring says the SDK type "must not
travel past this function", and the *"domain is independent"* import contract
would refuse the import anyway.

**The rounding rule is PO-4 and it lives in one place.** Each category is
`tokens x rate_per_mtok` as an exact `Decimal` (the per-million cancels, so the
units are micro-dollars directly), the four are summed **exactly**, and the
total is quantised **once** by `Usd.micro()` with `ROUND_HALF_UP`. Never per
category: 2 cache-write tokens (12.50) plus 1 cache-read token (0.50) is 13
micro-dollars summed first and 14 rounded first.

**`RATES` is the loader's own output** (RED-A1), not a literal the loader
merely knows how to validate. AC-7 asks for a loader that rejects a table
missing a category for a listed model; a loader only the tests call would leave
the *shipped* table unguarded, which is the table that matters. So this module
cannot import unless the published rates are complete.

**A missing model raises rather than pricing at zero** (AC-5). A silently
zero-priced call is the worst failure this module has: it spends real money and
reports none, and the budget ceiling MT-013 builds on top of this would never
fire. The error names the id, because "unknown model" without it tells the user
nothing to do.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from mangatl.domain.money import Usd
from mangatl.domain.translation import TokenUsage

__all__ = [
    "RATES",
    "RATE_TABLE_VERSION",
    "CostRecord",
    "IncompleteRateTable",
    "ModelRates",
    "UnknownModel",
    "load_rates",
    "price",
]

#: The identifier of the table below, stored on **every** ledger row. Rates
#: change; a ledger that cannot say which table priced a call cannot be
#: reconciled against the provider's bill, which is what the brief's S5 asks
#: for. Bump it in the same commit as any number in `_PUBLISHED`.
RATE_TABLE_VERSION: str = "2026-09-12"


@dataclass(frozen=True)
class ModelRates:
    """One model's four prices, in **dollars per million tokens**.

    The field names are the category keys `load_rates` reads, so the loader's
    complaint about a missing category names something a reader can find in
    both the code and the table.
    """

    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cache_write_per_mtok: Decimal
    cache_read_per_mtok: Decimal


@dataclass(frozen=True)
class CostRecord:
    """One priced call: what it used, what it cost, and what priced it.

    The two cache counts are ordered **write before read**, matching the
    `llm_call` columns - while `TokenUsage` orders them **read before write**
    (RED-A3). The two types are *not* positionally interchangeable and a swap
    is a factor-of-12.5 pricing error, so build either one by keyword.

    `cost` is already quantised to a whole number of micro-dollars: `price`
    does PO-4's single rounding, and `store/ledger.py` stores `cost.micro()`
    without rounding again.
    """

    model_id: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    cost: Usd
    rate_table_version: str


class UnknownModel(Exception):
    """A call was priced against a model id the rate table does not list.

    AC-5. Raised instead of falling back to a neighbouring model or to zero:
    `claude-opus-4` is the id a stale config actually produces, and pricing it
    at opus-5's rates would be wrong by a plausible-looking amount. The message
    carries the id verbatim.
    """


class IncompleteRateTable(Exception):
    """A rate table lists a model without all four of its categories.

    AC-7. The message carries the model id **and** the missing key, because the
    actionable fact is which line of the table to fix. The alternative - a
    category defaulting to zero - is AC-5's silent under-pricing arriving
    through the loader instead of through the caller.
    """


#: The four categories AC-7 means by "all four". Read as keys out of a raw
#: table and set as fields on `ModelRates`, so the two cannot drift.
_CATEGORIES: tuple[str, ...] = (
    "input_per_mtok",
    "output_per_mtok",
    "cache_write_per_mtok",
    "cache_read_per_mtok",
)


def load_rates(table: Mapping[str, Mapping[str, Decimal]]) -> Mapping[str, ModelRates]:
    """Validate a raw rate table and return it as `ModelRates` per model.

    Every listed model must carry all four categories; a gap raises
    `IncompleteRateTable` naming the model and the key. Nothing else is
    checked - not an unknown extra key, not the type of a value, not an empty
    table - and that is deliberate rather than an oversight (MT-012 F-6): this
    module sits under a 100% branch-coverage gate, and a validation branch no
    test can reach fails it. One loop over the models, one over the four
    categories, one `raise`.
    """
    loaded: dict[str, ModelRates] = {}
    for model_id, rates in table.items():
        for category in _CATEGORIES:
            if category not in rates:
                raise IncompleteRateTable(
                    f"the rate table entry for {model_id} has no {category};"
                    f" every listed model needs all of {', '.join(_CATEGORIES)}"
                )
        loaded[model_id] = ModelRates(
            input_per_mtok=rates["input_per_mtok"],
            output_per_mtok=rates["output_per_mtok"],
            cache_write_per_mtok=rates["cache_write_per_mtok"],
            cache_read_per_mtok=rates["cache_read_per_mtok"],
        )
    return loaded


#: The rates as published, in dollars per million tokens, transcribed from
#: `docs/wiki/stack.md` section 3 line 330 by way of MT-012's `## Contract`:
#: cache write is 1.25x the input rate and cache read is 0.1x of it. `Decimal`
#: and never `float`, so that a rate is the number it is written as.
#:
#: **Thinking tokens are not a category.** The API reports them inside
#: `output_tokens`, so they bill as output and inventing a fifth rate here
#: would double-count them.
_PUBLISHED: Mapping[str, Mapping[str, Decimal]] = {
    "claude-opus-5": {
        "input_per_mtok": Decimal("5.00"),
        "output_per_mtok": Decimal("25.00"),
        "cache_write_per_mtok": Decimal("6.25"),
        "cache_read_per_mtok": Decimal("0.50"),
    },
    "claude-sonnet-5": {
        "input_per_mtok": Decimal("2.00"),
        "output_per_mtok": Decimal("10.00"),
        "cache_write_per_mtok": Decimal("2.50"),
        "cache_read_per_mtok": Decimal("0.20"),
    },
}

#: The shipped table, built by the loader that guards it (RED-A1). If a rate is
#: ever deleted from `_PUBLISHED`, this module raises at import rather than
#: pricing that category at nothing.
RATES: Mapping[str, ModelRates] = load_rates(_PUBLISHED)


def price(model_id: str, usage: TokenUsage) -> CostRecord:
    """Price one call's token usage, exactly, against `RATES`.

    Raises `UnknownModel`, naming the id, if the table does not list it -
    AC-5's "and nothing is recorded" follows from that, because the caller
    never reaches `store.ledger.record_call`.

    A page that made no call is `TokenUsage(0, 0, 0, 0)` and prices to zero:
    wordless art is a legal outcome, not an error.
    """
    rates = RATES.get(model_id)
    if rates is None:
        raise UnknownModel(
            f"no rates for model {model_id!r} in rate table {RATE_TABLE_VERSION};"
            f" the table lists {', '.join(sorted(RATES))}"
        )
    # Summed as `Usd` - exact `Decimal` throughout - and quantised once, here,
    # by `micro()`. PO-4.
    exact = (
        Usd.from_tokens(usage.input_tokens, rates.input_per_mtok)
        + Usd.from_tokens(usage.output_tokens, rates.output_per_mtok)
        + Usd.from_tokens(usage.cache_write_tokens, rates.cache_write_per_mtok)
        + Usd.from_tokens(usage.cache_read_tokens, rates.cache_read_per_mtok)
    )
    return CostRecord(
        model_id=model_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cost=Usd.from_micro(exact.micro()),
        rate_table_version=RATE_TABLE_VERSION,
    )
