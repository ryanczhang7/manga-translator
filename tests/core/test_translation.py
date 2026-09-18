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

from mangatl.domain.translation import TokenUsage, TranslationResult


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


def test_the_module_exports_the_two_value_types_and_nothing_else() -> None:
    import mangatl.domain.translation as module

    assert module.__all__ == ["TokenUsage", "TranslationResult"]


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
    result = TranslationResult(lines={0: "Hello.", 2: "Goodbye."}, usage=_usage())

    assert result.lines == {0: "Hello.", 2: "Goodbye."}
    assert result.usage == _usage()


def test_a_translation_result_is_a_frozen_value() -> None:
    result = TranslationResult(lines={}, usage=_usage())

    assert dataclasses.is_dataclass(TranslationResult)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.usage = _usage()  # type: ignore[misc]


def test_an_empty_mapping_is_a_legal_result_and_is_the_no_call_page() -> None:
    """C-2 in terms: "an EMPTY mapping is AC-7's no-call page". A page of
    wordless art is not an error and is not a missing result - it is a result
    with nothing in it, and it must be constructible without a sentinel."""
    result = TranslationResult(lines={}, usage=TokenUsage(0, 0, 0, 0))

    assert result.lines == {}
    assert not result.lines


def test_the_sparse_mapping_distinguishes_an_omission_from_an_empty_string() -> None:
    """AC-5's reason for the shape, stated as the thing it has to be able to
    say. Region 3 is absent; region 2 was translated as `""`."""
    result = TranslationResult(lines={2: ""}, usage=_usage())

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
    }

    for name, annotation in annotations.items():
        module = getattr(annotation, "__module__", "builtins")
        assert not module.startswith("anthropic"), f"{name} is an SDK type: {annotation!r}"
        assert not module.startswith("mangatl.translate"), f"{name} is below domain: {annotation!r}"
        assert not module.startswith("mangatl.pipeline"), f"{name} is above domain: {annotation!r}"
