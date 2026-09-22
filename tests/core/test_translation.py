"""`mangatl.domain.translation`: what a translated page is, as plain values.

C-2. These types live in `domain` and not in `mangatl.translate`, and that is
**forced** rather than chosen (C-1, C-2, measured by the PO in PO-3/PO-4 with
throwaway probe modules and `uv run lint-imports`):

* `PageTranslator` - the `Callable` alias `pipeline/translate_stage.py` names its
  collaborator behind - has `TranslationResult` as its return type, so that name
  is written down inside `mangatl.pipeline`;
* the **layers** contract puts `mangatl.translate` *below* `mangatl.pipeline`,
  and the *"Only translate imports anthropic"* contract lists `mangatl.pipeline`
  among its `source_modules` with **no** `allow_indirect_imports`. So `pipeline`
  may not name anything in `mangatl.translate` - not under `TYPE_CHECKING`, not
  inside a function body, because import-linter reports those too.

`domain` is the only layer both `pipeline` and `translate` may import, and the
*"domain is independent"* contract forbids `domain` from importing `anthropic`.
Hence: **plain values, not the SDK's `Message` or `Usage` objects.** Whoever
calls the SDK converts at the boundary, which is `translate/client.py`.

**Why `TokenUsage` is four ints and not one dollar figure.** MT-012 prices them
and **rates change**; a ledger of dollars alone cannot be re-priced.
`store/schema.py`'s `llm_call` table already has exactly these four columns.
This story records them; it does not price them.

`coverage-core` holds `src/mangatl/domain/**` at **100%**, so every branch these
types have is exercised here rather than incidentally from a stage test.
"""

from __future__ import annotations

import dataclasses
from typing import get_type_hints

import pytest

from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult


def _call() -> CallInfo:
    """MT-044 C-4's `CallInfo`: the identity of one API call.

    Two **different** strings, so a constructor that assigned `model_id` from
    `request_id` (or the reverse) is caught. `msg_...` and `claude-opus-5` are
    the shapes the SDK actually returns - `Message.id` and `Message.model` -
    which is where C-5 reads them from.
    """
    return CallInfo(request_id="msg_01RedFixture", model_id="claude-opus-5")


def _usage() -> TokenUsage:
    """Four **distinct** values, so a constructor that swapped two is caught.

    Four zeroes, or four of the same number, would let any permutation pass -
    and a swap of `cache_read` and `cache_write` is a factor-of-12.5 pricing
    error (0.1x against 1.25x of the base input rate) that MT-012 would then
    carry into every report.
    """
    return TokenUsage(
        input_tokens=3011,
        output_tokens=712,
        cache_read_tokens=1499,
        cache_write_tokens=1873,
    )


def test_the_module_exports_the_three_value_types_and_nothing_else() -> None:
    import mangatl.domain.translation as module

    # MT-044 C-4 adds `CallInfo`. `call is None` <=> no API call was made <=> no
    # `llm_call` row: today that fact is only *inferable*, from
    # `usage == TokenUsage(0, 0, 0, 0)`, and an inference is the wrong basis for
    # a decision about money - a real call that legitimately reported four
    # zeroes would be dropped from the ledger by it.
    assert module.__all__ == ["CallInfo", "TokenUsage", "TranslationResult"]


def test_token_usage_carries_the_four_counts_the_llm_call_table_has() -> None:
    """C-2 and `schema.py`. The names are the contract: MT-012 reads them.

    `usage.cache_read_input_tokens` and `usage.cache_creation_input_tokens` are
    what the SDK calls them (C-5); the domain shortens both, and the conversion
    is `translate/client.py`'s job - see `test_translate_client.py`.
    """
    usage = _usage()

    assert usage.input_tokens == 3011
    assert usage.output_tokens == 712
    assert usage.cache_read_tokens == 1499
    assert usage.cache_write_tokens == 1873


def test_token_usage_is_a_frozen_value() -> None:
    """Two usages with the same four counts *are* the same usage, and nothing
    downstream mutates one after it is built - the ledger appends rows."""
    assert dataclasses.is_dataclass(TokenUsage)

    with pytest.raises(dataclasses.FrozenInstanceError):
        _usage().input_tokens = 0  # type: ignore[misc]

    assert _usage() == _usage()


def test_a_translation_result_carries_the_lines_and_the_usage() -> None:
    """C-2. `lines` is a **`Mapping[int, str]`** keyed by reading index, not a
    positional sequence: AC-5 needs "region 3 was omitted" to be distinguishable
    from "region 3 was translated as the empty string", and a sequence cannot
    express the difference without a sentinel."""
    result = TranslationResult(lines={0: "Hello.", 2: "Goodbye."}, usage=_usage(), call=_call())

    assert result.lines == {0: "Hello.", 2: "Goodbye."}
    assert result.usage == _usage()
    assert result.call == _call()


def test_a_translation_result_is_a_frozen_value() -> None:
    result = TranslationResult(lines={}, usage=_usage(), call=_call())

    assert dataclasses.is_dataclass(TranslationResult)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.usage = _usage()  # type: ignore[misc]

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.call = None  # type: ignore[misc]


def test_an_empty_mapping_is_a_legal_result_and_is_the_no_call_page() -> None:
    """C-2 in terms: "an EMPTY mapping is AC-7's no-call page". A page of
    wordless art is not an error and is not a missing result - it is a result
    with nothing in it, and it must be constructible without a sentinel."""
    result = TranslationResult(lines={}, usage=TokenUsage(0, 0, 0, 0), call=None)

    assert result.lines == {}
    assert not result.lines
    # MT-044 C-4: `call is None` is the no-call statement itself, and the four
    # zeroes are now corroboration rather than the evidence.
    assert result.call is None


def test_the_sparse_mapping_distinguishes_an_omission_from_an_empty_string() -> None:
    """AC-5's reason for the shape, stated as the thing it has to be able to
    say. Region 3 is absent; region 2 was translated as `""`."""
    result = TranslationResult(lines={2: ""}, usage=_usage(), call=_call())

    assert 2 in result.lines
    assert result.lines[2] == ""
    assert 3 not in result.lines


def test_neither_type_names_anything_the_domain_may_not_import() -> None:
    """The *"domain is independent"* contract, as a `unit` tripwire.

    `lint` catches this too, and later - a contract broken here is found by
    `lint-imports` on a whole-tree run, while this names the field. Both halves
    matter: `TokenUsage` must not be the SDK's `Usage`, and `TranslationResult`
    must not carry a `Message`.
    """
    annotations = {
        **get_type_hints(TokenUsage),
        **get_type_hints(TranslationResult),
        **get_type_hints(CallInfo),
    }

    for name, annotation in annotations.items():
        module = getattr(annotation, "__module__", "builtins")
        assert not module.startswith("anthropic"), f"{name} is an SDK type: {annotation!r}"
        assert not module.startswith("mangatl.translate"), f"{name} is below domain: {annotation!r}"
        assert not module.startswith("mangatl.pipeline"), f"{name} is above domain: {annotation!r}"


# -- MT-044 C-4: CallInfo ------------------------------------------------------


def test_a_call_info_carries_the_request_id_and_the_model_that_served_it() -> None:
    """MT-044 C-4. Two required strings on one optional field.

    **Not two optional fields on `TranslationResult`.** `model_id: str | None`
    beside `request_id: str | None` is an invariant nothing enforces - the two
    must agree about whether a call happened, and nothing makes them. One
    optional field holding two required strings has no disagreeing state.

    The two values are deliberately different strings, so a constructor that
    assigned one field from the other is caught.
    """
    call = CallInfo(request_id="msg_01RedFixture", model_id="claude-opus-5")

    assert call.request_id == "msg_01RedFixture"
    assert call.model_id == "claude-opus-5"
    assert call != CallInfo(request_id="claude-opus-5", model_id="msg_01RedFixture")


def test_a_call_info_is_a_frozen_value_like_every_other_type_here() -> None:
    """`domain` sits under `coverage-core`'s `--cov-fail-under=100` with branch
    coverage on, so this construction is not free and MT-044's RED spends it
    deliberately (C-4)."""
    call = _call()

    assert dataclasses.is_dataclass(CallInfo)
    assert call == _call()

    with pytest.raises(dataclasses.FrozenInstanceError):
        call.model_id = "claude-sonnet-5"  # type: ignore[misc]


def test_a_result_that_made_a_call_and_one_that_did_not_are_distinguishable() -> None:
    """C-4's whole reason, stated as the discrimination it buys.

    A real call that legitimately reported four zero token counts is
    **indistinguishable** from a wordless page under the old inference
    (`usage == TokenUsage(0, 0, 0, 0)`), and under it the ledger would drop the
    bill. With `call` the two differ in the field that says so, while their
    usages are identical.
    """
    zero = TokenUsage(0, 0, 0, 0)
    billed = TranslationResult(lines={}, usage=zero, call=_call())
    wordless = TranslationResult(lines={}, usage=zero, call=None)

    assert billed.usage == wordless.usage
    assert billed.call is not None
    assert wordless.call is None
    assert billed != wordless


def test_the_call_field_has_no_default_so_a_caller_cannot_forget_it() -> None:
    """C-4's pin, and it is the one AC-2 depends on.

    `call: CallInfo | None = None` would make "record nothing" the behaviour a
    caller gets **by saying nothing** - which is exactly the vacuous
    implementation AC-2's note warns about, arriving through a default argument
    instead of through a missing line. Read off the dataclass fields rather than
    off a `TypeError`, so the failure message names the field.
    """
    fields = {field.name: field for field in dataclasses.fields(TranslationResult)}

    assert fields["call"].default is dataclasses.MISSING, (
        "TranslationResult.call has a default, so `TranslationResult(lines=..., usage=...)`"
        " silently means 'no call was made' and the ledger stays empty (C-4)"
    )
    assert fields["call"].default_factory is dataclasses.MISSING
    assert [field.name for field in dataclasses.fields(TranslationResult)] == [
        "lines",
        "usage",
        "call",
    ]
