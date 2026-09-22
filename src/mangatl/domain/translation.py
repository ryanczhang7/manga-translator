"""What a translated page is, as plain values: the lines, and what it cost.

**These types live in `domain` and that is forced rather than chosen** (MT-011
C-1/C-2, measured by the PO in PO-3/PO-4 with throwaway probe modules and
`uv run lint-imports`). `pipeline/translate_stage.py` names its collaborator
behind `PageTranslator`, whose return type is `TranslationResult` - so that name
is written down inside `mangatl.pipeline`, and two contracts then decide where
it may live:

* the **layers** contract puts `mangatl.translate` *below* `mangatl.pipeline`;
* *"Only translate imports anthropic"* lists `mangatl.pipeline` among its
  `source_modules` with **no** `allow_indirect_imports`, so `pipeline` may not
  reach `mangatl.translate` at all - not under `TYPE_CHECKING`, not inside a
  function body.

`domain` is the only layer both `pipeline` and `translate` may import, and the
*"domain is independent"* contract forbids `domain` from importing `anthropic`.
Hence **plain values, not the SDK's `Message` or `Usage` objects**: the
conversion happens at the boundary, in `translate/client.py`, and nowhere else.

**`TokenUsage` is four ints and not one dollar figure** because MT-012 prices
them and **rates change**; a ledger of dollars alone cannot be re-priced.
`store/schema.py`'s `llm_call` table already has exactly these four columns.
This story records them; it does not price them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["CallInfo", "TokenUsage", "TranslationResult"]


@dataclass(frozen=True)
class TokenUsage:
    """What one page's call consumed, in the four counts the ledger stores.

    The names are shortened from the SDK's: `usage.cache_read_input_tokens` and
    `usage.cache_creation_input_tokens` become `cache_read_tokens` and
    `cache_write_tokens`, and `translate/client.py` is where that mapping
    happens. The **order** of the fields is part of the type - a page that made
    no call is written `TokenUsage(0, 0, 0, 0)` positionally - and a swap of the
    two cache fields is a factor-of-12.5 pricing error (0.1x against 1.25x of
    the base input rate) that nothing downstream could notice.

    Frozen because it is a value: nothing mutates a usage after it is built, and
    the ledger appends rows.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


@dataclass(frozen=True)
class CallInfo:
    """The identity of one API call, for the row the ledger writes about it.

    Two required strings rather than two optionals on `TranslationResult`: a
    request id without a model id, or the other way round, is a state nothing
    could enforce. One optional field holding two required strings has no
    disagreeing state, and `call is None` then *means* "no call was made"
    rather than being inferred from four zero token counts - an inference that
    would drop a real call legitimately reporting zeroes out of the ledger.

    Deliberately branch-free: no `__post_init__`, no validation. It is inside
    `coverage-core`'s `--cov-fail-under=100` with branch coverage, and a branch
    here would owe a test per arm (MT-044 C-4, F-3).
    """

    request_id: str
    model_id: str


@dataclass(frozen=True)
class TranslationResult:
    """One page's proposed English, and what the page cost.

    `lines` is **sparse and keyed by reading index**, not a positional sequence.
    AC-5 needs "region 3 was omitted" to be distinguishable from "region 3 was
    translated as the empty string", and a sequence cannot say the difference
    without a sentinel: an index absent from this mapping is AC-5's untranslated
    region, and `Project.write_proposed` leaves its `proposed_en` NULL.

    An **empty** mapping is AC-7's page of wordless art - a legal result with
    nothing in it, carrying `TokenUsage(0, 0, 0, 0)` and `call=None` because no
    call was made.

    **`call` has no default** (MT-044 C-4). A default of `None` would make
    "record nothing in the ledger" the behaviour a caller gets by saying
    nothing, which is exactly the vacuous implementation AC-2 warns about,
    arriving through a default argument instead of through a missing line.
    """

    lines: Mapping[int, str]
    usage: TokenUsage
    call: CallInfo | None
