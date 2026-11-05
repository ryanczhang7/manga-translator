"""`mangatl.translate.consistency`: what the consistency pass reads, how its
answer is parsed, and how a volume is cut into requests.

MT-114. Covers **AC-1** (the text), **AC-2** (the schema), **AC-3** (the parse)
and **AC-4** (the chunking), plus the module's SDK-free import. AC-5 (the
request on Gemini) and the three domain dataclasses are in
`test_gemini_consistency.py`.

**Oracle partition: entirely mechanical** (the story's `## Contract`). Every
number and every byte is read out of the Contract's "Semantics, pinned at
PLANNED" list: the text's exact layout, the 1-based `page` against the 0-based
`page_ordinal`, the limits 180,000 / 8,192 (MT-101 D-12), and the greedy
`<=` fit. Nothing here is calibrated.

**Byte arithmetic.** `estimate_tokens` is `ceil(utf8_bytes / 3)`. The
chunking fixtures are ASCII, so a text's byte count is its length, and every
boundary below is computed by hand in the comment beside it - and checked
against `consistency_text` inside the test, so a boundary that drifted by a
byte fails as a precondition rather than as a wrong partition.

**The modules are imported per test, not at the top** (`test_glossary_pass.py`'s
`gp` fixture): in RED `translate.consistency` does not exist and
`domain.correction` lacks the new classes, and a top-level import would be a
COLLECTION error taking the whole `pytest tests/core tests/ui` session dark.

**Timing.** No per-test timeout in this project. The largest fixture is 200
pages x 20 lines (~645 kB of text); a greedy chunker that rebuilds the chunk's
text per page is quadratic in pages, a few hundred ms at worst. The SDK-free
check spawns one interpreter (about a second).
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

from mangatl.domain.glossary import estimate_tokens


@pytest.fixture
def cp() -> ModuleType:
    """`mangatl.translate.consistency`, imported per test (see the docstring)."""
    from mangatl.translate import consistency as module

    return module


@pytest.fixture
def proposed() -> type:
    from mangatl.domain.correction import ProposedCorrection

    return ProposedCorrection


@pytest.fixture
def parsed() -> type:
    from mangatl.domain.correction import ParsedCorrections

    return ParsedCorrections


# -- AC-1: the text ---------------------------------------------------------------

_GLOSSARY = "Glossary:\nさくら = Sakura (name)\n先輩 = senpai (honorific)"


def _pages(cp: ModuleType) -> tuple[Any, ...]:
    """Three pages with every control AC-1 needs in one fixture:

    - page 0 holds its lines in an order that is NOT reading-index order
      (2, 1, 0), so an implementation that sorts by index fails, and its
      middle line has `en is None`, so skipping by position fails;
    - page 1 has no English at all, so it is dropped header and all;
    - page 2 is still `Page 3:` after the gap (ordinal-based, not a counter).
    """
    return (
        cp.PageLines(
            ordinal=0,
            lines=(
                (2, "待って、さくら!", "Wait, Sakura!"),
                (1, "……", None),
                (0, "さくら先輩!", "Sakura-senpai!"),
            ),
        ),
        cp.PageLines(ordinal=1, lines=((0, "ドン", None), (1, "ゴゴゴ", None))),
        cp.PageLines(ordinal=2, lines=((0, "東京駅で会おう", "Let's meet at Tokyo Station."),)),
    )


#: The exact bytes the Contract pins for `_pages` under `_GLOSSARY`, written out
#: by hand: glossary, one blank line, page blocks separated by one blank line,
#: `[{reading_index}] {ja}` then four spaces and the English, no trailing newline.
_TEXT = (
    "Glossary:\nさくら = Sakura (name)\n先輩 = senpai (honorific)"
    "\n\n"
    "Page 1:\n"
    "[2] 待って、さくら!\n"
    "    Wait, Sakura!\n"
    "[0] さくら先輩!\n"
    "    Sakura-senpai!"
    "\n\n"
    "Page 3:\n"
    "[0] 東京駅で会おう\n"
    "    Let's meet at Tokyo Station."
)


def test_the_text_is_the_glossary_then_each_page_block_byte_for_byte(cp: ModuleType) -> None:
    """AC-1: the whole layout at once, against bytes written out by hand - the
    tuple's line order kept, the `None` line skipped, the English-less page
    dropped and the page after it still numbered by its ordinal."""
    assert cp.consistency_text(_pages(cp), _GLOSSARY) == _TEXT


def test_lines_keep_the_order_the_tuple_holds_and_are_not_sorted_by_reading_index(
    cp: ModuleType,
) -> None:
    """The Contract: "lines are in the order the tuple holds them (reading
    order is the caller's)". `[2]` precedes `[0]` because the tuple says so."""
    text = cp.consistency_text(_pages(cp), _GLOSSARY)

    assert text.index("[2] 待って、さくら!") < text.index("[0] さくら先輩!"), text


def test_a_line_with_no_english_contributes_nothing_not_even_its_japanese(
    cp: ModuleType,
) -> None:
    """AC-1's skip: a line with `en is None` has no English to correct, so
    neither its `[i] ja` line nor an empty English line appears."""
    text = cp.consistency_text(_pages(cp), _GLOSSARY)

    assert "[1]" not in text, text
    assert "……" not in text, text
    assert "None" not in text, text


def test_a_page_with_no_english_is_dropped_and_the_next_page_keeps_its_ordinal_number(
    cp: ModuleType,
) -> None:
    """The Contract's gap rule (MT-104's): no `Page 2:` header for the
    English-less page, and the page after it is `Page 3:` - a counter of
    rendered pages would print `Page 2:` and point the model's `page` at the
    wrong page."""
    text = cp.consistency_text(_pages(cp), _GLOSSARY)

    assert "Page 2:" not in text, text
    assert "ドン" not in text and "ゴゴゴ" not in text, text
    assert "\nPage 3:\n" in text, text


def test_the_page_number_is_the_ordinal_plus_one_not_the_position(cp: ModuleType) -> None:
    """`Page {ordinal + 1}:` for a page whose ordinal is not its position in
    the sequence - a chunk that starts mid-volume."""
    page = cp.PageLines(ordinal=41, lines=((3, "行くぞ", "Let's go"),))

    assert cp.consistency_text((page,), "") == "Page 42:\n[3] 行くぞ\n    Let's go"


def test_pages_are_rendered_in_the_order_given_not_sorted_by_ordinal(cp: ModuleType) -> None:
    """The Contract: "Pages are rendered in the order given"."""
    later = cp.PageLines(ordinal=3, lines=((0, "四", "four"),))
    earlier = cp.PageLines(ordinal=1, lines=((0, "二", "two"),))

    assert cp.consistency_text((later, earlier), "") == (
        "Page 4:\n[0] 四\n    four\n\nPage 2:\n[0] 二\n    two"
    )


def test_with_an_empty_glossary_the_first_page_block_starts_at_byte_zero(
    cp: ModuleType,
) -> None:
    """The Contract: `glossary_block == ""` means no leading blank line."""
    text = cp.consistency_text(_pages(cp), "")

    assert text == _TEXT[len(_GLOSSARY) + 2 :]
    assert text.startswith("Page 1:\n"), repr(text[:20])


def test_the_text_has_no_trailing_newline(cp: ModuleType) -> None:
    text = cp.consistency_text(_pages(cp), _GLOSSARY)

    assert not text.endswith("\n"), repr(text[-20:])


def test_an_empty_english_string_is_english_and_is_rendered(cp: ModuleType) -> None:
    """The Contract's test is `en is not None`, not truthiness: a line whose
    English is `""` is a line the pass may correct, so it is listed."""
    page = cp.PageLines(ordinal=0, lines=((0, "……", ""),))

    assert cp.consistency_text((page,), "") == "Page 1:\n[0] ……\n    "


def test_japanese_and_english_are_rendered_verbatim(cp: ModuleType) -> None:
    """No strip, no normalisation - the pass's `corrected_en` is compared to
    the stored English exactly (AC-3), so the text must show it exactly."""
    page = cp.PageLines(ordinal=0, lines=((5, "  ｻｸﾗ  先輩　", " Sakura  "),))

    assert cp.consistency_text((page,), "") == "Page 1:\n[5]   ｻｸﾗ  先輩　\n     Sakura  "


@pytest.mark.parametrize(
    ("glossary", "expected"),
    [("", ""), (_GLOSSARY, _GLOSSARY)],
    ids=["nothing-at-all", "glossary-only"],
)
def test_with_no_page_to_render_the_text_is_the_glossary_alone(
    cp: ModuleType, glossary: str, expected: str
) -> None:
    """Contract amendment (RED, 2026-11-05): with no page block the text is
    `glossary_block` alone - no dangling blank line, consistent with "no
    trailing newline" - and `""` when both are empty."""
    no_english = cp.PageLines(ordinal=0, lines=((0, "ドン", None),))

    assert cp.consistency_text((), glossary) == expected
    assert cp.consistency_text((no_english,), glossary) == expected


def test_two_calls_with_the_same_pages_are_byte_identical(cp: ModuleType) -> None:
    """AC-1's determinism, against a separately built equal input too."""
    first = cp.consistency_text(_pages(cp), _GLOSSARY)
    second = cp.consistency_text(_pages(cp), _GLOSSARY)
    third = cp.consistency_text(list(_pages(cp)), _GLOSSARY)

    assert first.encode("utf-8") == second.encode("utf-8") == third.encode("utf-8")


def test_page_lines_is_a_frozen_value_of_ordinal_and_lines(cp: ModuleType) -> None:
    """The Contract's `PageLines`: two fields in that order, frozen."""
    from dataclasses import FrozenInstanceError, fields

    page = cp.PageLines(0, ((0, "一", "one"),))

    assert [field.name for field in fields(page)] == ["ordinal", "lines"]
    assert page == cp.PageLines(ordinal=0, lines=((0, "一", "one"),))
    with pytest.raises(FrozenInstanceError):
        page.ordinal = 1


# -- AC-2: the schema -------------------------------------------------------------


def test_the_schema_is_an_object_requiring_only_a_corrections_array(cp: ModuleType) -> None:
    """AC-2, top level: `corrections` is the one property, required, and
    nothing else is allowed."""
    schema = cp.CORRECTIONS_SCHEMA

    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"corrections"}
    assert schema["required"] == ["corrections"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["corrections"]["type"] == "array"


def test_each_correction_requires_exactly_page_index_english_and_reason(cp: ModuleType) -> None:
    """AC-2, item level: the four keys with their types, all required, no
    additional properties."""
    items = cp.CORRECTIONS_SCHEMA["properties"]["corrections"]["items"]

    assert items["type"] == "object"
    assert {name: prop["type"] for name, prop in items["properties"].items()} == {
        "page": "integer",
        "reading_index": "integer",
        "corrected_en": "string",
        "reason": "string",
    }
    assert set(items["required"]) == {"page", "reading_index", "corrected_en", "reason"}
    assert len(items["required"]) == 4
    assert items["additionalProperties"] is False


def _properties(schema: dict[str, Any], path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every property schema anywhere in `schema`, with its dotted path."""
    found: list[tuple[str, dict[str, Any]]] = []
    for name, prop in schema.get("properties", {}).items():
        found.append((f"{path}{name}", prop))
        found.extend(_properties(prop, f"{path}{name}."))
    if "items" in schema:
        found.extend(_properties(schema["items"], f"{path}[]."))
    return found


def test_no_property_of_the_schema_can_carry_a_full_page(cp: ModuleType) -> None:
    """AC-2's "no property can carry a full page": apart from the
    `corrections` array itself, every property anywhere in the schema is a
    scalar - an integer or a string - so there is no list of lines, no page
    object, nowhere a rewrite of the page could go. And no property is named
    as a page's text."""
    props = _properties(cp.CORRECTIONS_SCHEMA)
    non_scalar = [
        (path, prop.get("type"))
        for path, prop in props
        if path != "corrections" and prop.get("type") not in ("integer", "string")
    ]
    named_as_text = [
        path
        for path, _ in props
        if any(word in path.lower() for word in ("text", "lines", "page_en", "full", "original"))
    ]

    assert len(props) == 5, [path for path, _ in props]
    assert non_scalar == []
    assert named_as_text == []


# -- AC-3: the parse --------------------------------------------------------------

#: `current` is keyed by the store's 0-based `(page_ordinal, reading_index)`.
#: The response speaks 1-based `page`. Controls built in:
#: - `(1, 0)` exists, `(2, 0)` does NOT: the response's `page: 2, index 0` is
#:   ordinal 1; a parse that forgets `- 1` looks up `(2, 0)` and raises.
#: - `(0, 2)` exists, `(1, 2)` does NOT: the same, for `page: 1`.
_CURRENT: dict[tuple[int, int], str] = {
    (0, 0): "Sakura-senpai!",
    (0, 2): "Wait!",
    (1, 0): "Let's go.",
    (1, 1): "Tokyo Station.",
}


def _body(*items: dict[str, Any]) -> str:
    return json.dumps({"corrections": list(items)}, ensure_ascii=False)


def _item(page: Any, index: Any, en: Any, reason: Any = "consistency") -> dict[str, Any]:
    return {"page": page, "reading_index": index, "corrected_en": en, "reason": reason}


def test_changed_items_parse_to_proposed_corrections_on_zero_based_pages_in_response_order(
    cp: ModuleType, proposed: type, parsed: type
) -> None:
    """AC-3: `page - 1` is the ordinal; response order is kept (page 2 before
    page 1 here, which no sort produces); the unchanged item in between is
    dropped and counted; `"Wait! "` differs from `"Wait!"` by one trailing
    space and so IS a change - equality is exact, no normalisation."""
    body = _body(
        _item(2, 0, "Let's go!", "tone matches page 1"),
        _item(1, 0, "Sakura-senpai!", "no change"),
        _item(1, 2, "Wait! ", "spacing"),
    )

    result = cp.parse_corrections(body, _CURRENT)

    assert result == parsed(
        corrections=(
            proposed(
                page_ordinal=1,
                reading_index=0,
                corrected_en="Let's go!",
                reason="tone matches page 1",
            ),
            proposed(page_ordinal=0, reading_index=2, corrected_en="Wait! ", reason="spacing"),
        ),
        unchanged_returned=1,
    )
    assert type(result) is parsed
    assert type(result.corrections) is tuple
    assert all(type(c) is proposed for c in result.corrections)


def test_every_unchanged_item_is_counted_not_just_flagged(cp: ModuleType, parsed: type) -> None:
    """AC-3's count: two items equal to `current` are 2, not 1 or `True` -
    the count is the observable that says whether the model obeys
    "corrections only" (`## Notes`)."""
    body = _body(_item(1, 0, "Sakura-senpai!"), _item(2, 1, "Tokyo Station."))

    assert cp.parse_corrections(body, _CURRENT) == parsed(corrections=(), unchanged_returned=2)


def test_an_empty_corrections_array_is_no_corrections_and_not_an_error(
    cp: ModuleType, parsed: type
) -> None:
    """A legal answer: the chunk is already consistent."""
    assert cp.parse_corrections('{"corrections": []}', _CURRENT) == parsed((), 0)


@pytest.mark.parametrize(
    ("page", "index"),
    [(3, 7), (9, 14), (0, 0)],
    ids=["page-past-the-end", "both-unknown", "page-0-is-not-a-1-based-page"],
)
def test_an_item_naming_a_line_not_in_current_raises_unknown_line_with_both_numbers(
    cp: ModuleType, page: int, index: int
) -> None:
    """AC-3: `UnknownLine`, its message carrying `page` and `reading_index`
    as the response wrote them (1-based page), as plain integers. A valid item
    before it does not save the chunk."""
    body = _body(_item(2, 0, "Let's go!"), _item(page, index, "Huh?"))

    with pytest.raises(cp.UnknownLine) as raised:
        cp.parse_corrections(body, _CURRENT)

    message = str(raised.value)
    assert re.search(rf"\b{page}\b", message), message
    assert re.search(rf"\b{index}\b", message), message


def test_unknown_line_names_the_response_page_not_the_ordinal(cp: ModuleType) -> None:
    """The Contract: the message carries `page` as the response wrote it. A
    response `page: 5` is ordinal 4; the message must say 5 (and an
    implementation that printed only the ordinal would print 4)."""
    with pytest.raises(cp.UnknownLine) as raised:
        cp.parse_corrections(_body(_item(5, 11, "x")), _CURRENT)

    message = str(raised.value)
    assert re.search(r"\b5\b", message), message
    assert re.search(r"\b11\b", message), message


def test_a_line_shown_without_english_is_not_correctable(cp: ModuleType) -> None:
    """The Contract: a line with `en is None` is never in `current`, so a
    correction to it is `UnknownLine` - here `[1]` on page 1, which `_pages`
    lists with no English and `_CURRENT` therefore lacks."""
    with pytest.raises(cp.UnknownLine):
        cp.parse_corrections(_body(_item(1, 1, "...")), _CURRENT)


def test_a_body_without_the_corrections_key_raises_value_error_naming_the_key(
    cp: ModuleType,
) -> None:
    """MT-104's rule: the required key missing is the model disobeying the
    schema, and the message names `corrections`."""
    with pytest.raises(ValueError, match=r"\bcorrections\b"):
        cp.parse_corrections('{"lines": []}', _CURRENT)


@pytest.mark.parametrize(
    "bad",
    [
        {"reading_index": 0, "corrected_en": "x", "reason": "r"},
        {"page": 2, "corrected_en": "x", "reason": "r"},
        {"page": 2, "reading_index": 0, "reason": "r"},
        {"page": 2, "reading_index": 0, "corrected_en": "x"},
        _item("2", 0, "x"),
        _item(2, "0", "x"),
        _item(2, 0.5, "x"),
        _item(2, 0, 5),
        _item(2, 0, None),
        _item(2, 0, "x", None),
        "page 2 line 0: x",
    ],
    ids=[
        "no-page",
        "no-reading-index",
        "no-corrected-en",
        "no-reason",
        "page-is-a-string",
        "index-is-a-string",
        "index-is-a-float",
        "english-is-a-number",
        "english-is-null",
        "reason-is-null",
        "item-is-not-an-object",
    ],
)
def test_a_malformed_item_raises_value_error_and_is_not_skipped(cp: ModuleType, bad: Any) -> None:
    """PO-1: a missing key or a wrong type refuses the whole chunk - after a
    valid item, so an implementation that skipped the bad one and returned
    its neighbour fails. A `KeyError` or `TypeError` escaping is not a
    `ValueError` and fails too."""
    body = json.dumps({"corrections": [_item(2, 0, "Let's go!"), bad]}, ensure_ascii=False)

    with pytest.raises(ValueError) as raised:
        cp.parse_corrections(body, _CURRENT)

    assert not isinstance(raised.value, json.JSONDecodeError), raised.value


def test_a_body_that_is_not_json_propagates_the_decode_error(cp: ModuleType) -> None:
    """The Contract: `json.loads` errors propagate, unwrapped."""
    with pytest.raises(json.JSONDecodeError):
        cp.parse_corrections('{"corrections": [', _CURRENT)


def test_unknown_line_and_page_too_large_are_exceptions_but_not_value_errors(
    cp: ModuleType,
) -> None:
    """The Contract: both derive from `Exception` directly - a refusal is not
    a malformed answer, so a caller catching the parse's `ValueError` must
    not catch either."""
    for refusal in (cp.UnknownLine, cp.PageTooLarge):
        assert issubclass(refusal, Exception)
        assert not issubclass(refusal, ValueError), refusal


# -- AC-4: the chunking -----------------------------------------------------------

#: A page block for one line `(0, "a" * m, "b")` on a single-digit page is
#: `"Page n:\n[0] " + "a"*m + "\n    b"` = 7 + 1 + 4 + m + 1 + 4 + 1 = 18 + m bytes.
_BLOCK_OVERHEAD = len("Page 1:\n[0] \n    b")


def _page(cp: ModuleType, ordinal: int, block_bytes: int) -> Any:
    """A single-digit-numbered page whose block is exactly `block_bytes`."""
    assert ordinal < 9
    return cp.PageLines(ordinal, ((0, "a" * (block_bytes - _BLOCK_OVERHEAD), "b"),))


#: 10 bytes. A chunk of k pages with blocks s_1..s_k renders to
#: `10 + 2 + sum(s) + 2 * (k - 1)` = `10 + sum(s) + 2k` bytes.
_G = "G" * 10

#: 300 bytes is exactly 100 estimated tokens; 301 is 101.
_SMALL_LIMIT = 100


def _boundary_volume(cp: ModuleType) -> tuple[Any, ...]:
    """**DV-2's fixture.** Blocks of 143, 143, 143, 143, 18 bytes:

    - pages 0+1: 10 + 286 + 4 = 300 bytes = exactly 100 tokens - fits (`<=`);
      adding page 2 makes 445 bytes - over, so page 2 starts the next chunk;
    - pages 2+3: 300 bytes again, exactly at the limit; page 4 starts a third;
    - page 4 alone: 10 + 18 + 2 = 30 bytes.

    Greedy partition: `[(0, 1), (2, 3), (4,)]`. A fit test of `<` instead of
    `<=` splits every pair; admitting a page after the estimate is over puts a
    chunk at 445 bytes (149 tokens).
    """
    return tuple(_page(cp, i, size) for i, size in enumerate((143, 143, 143, 143, 18)))


def _assert_a_partition(cp: ModuleType, pages: tuple[Any, ...], chunks: Any, limit: int) -> None:
    assert type(chunks) is list, type(chunks)
    assert all(type(chunk) is tuple for chunk in chunks), [type(c) for c in chunks]
    assert all(len(chunk) > 0 for chunk in chunks), "an empty chunk"
    flat = [page for chunk in chunks for page in chunk]
    assert len(flat) == len(pages), f"{len(flat)} pages in chunks, {len(pages)} given"
    assert all(got is given for got, given in zip(flat, pages, strict=True)), (
        "chunks are not the caller's pages, contiguous and in order"
    )
    over = [
        (i, estimate_tokens(cp.consistency_text(chunk, _G)))
        for i, chunk in enumerate(chunks)
        if estimate_tokens(cp.consistency_text(chunk, _G)) > limit
    ]
    assert over == [], f"chunks over {limit} tokens: {over}"


def test_the_boundary_fixture_estimates_exactly_at_the_limit_as_claimed(cp: ModuleType) -> None:
    """The precondition for the next test, so a fixture a byte off fails
    here and not as a puzzling partition."""
    pages = _boundary_volume(cp)

    assert len(cp.consistency_text(pages[0:2], _G).encode()) == 300
    assert estimate_tokens(cp.consistency_text(pages[0:2], _G)) == _SMALL_LIMIT
    assert estimate_tokens(cp.consistency_text(pages[2:4], _G)) == _SMALL_LIMIT
    assert estimate_tokens(cp.consistency_text(pages[0:3], _G)) == 149
    assert estimate_tokens(cp.consistency_text(pages[4:5], _G)) == 10


def test_greedy_chunking_admits_a_page_that_lands_exactly_on_the_limit(cp: ModuleType) -> None:
    """AC-4 and DV-2: the exact greedy partition `[(0, 1), (2, 3), (4,)]` -
    two chunks at exactly 100 tokens (inclusive), the page after each
    starting the next chunk - and the partition invariants on top."""
    pages = _boundary_volume(cp)

    chunks = cp.chunk_pages(pages, _G, max_tokens=_SMALL_LIMIT)

    assert [[page.ordinal for page in chunk] for chunk in chunks] == [[0, 1], [2, 3], [4]]
    _assert_a_partition(cp, pages, chunks, _SMALL_LIMIT)


def test_a_page_one_byte_past_the_boundary_starts_the_next_chunk(cp: ModuleType) -> None:
    """The control on the other side of DV-2's boundary: blocks 143, 144, 18.
    Pages 0+1 are 301 bytes = 101 tokens, over by one, so page 1 starts a
    chunk; pages 1+2 are 10 + 162 + 4 = 176 bytes = 59 tokens."""
    pages = tuple(_page(cp, i, size) for i, size in enumerate((143, 144, 18)))
    assert estimate_tokens(cp.consistency_text(pages[0:2], _G)) == 101

    chunks = cp.chunk_pages(pages, _G, max_tokens=_SMALL_LIMIT)

    assert [[page.ordinal for page in chunk] for chunk in chunks] == [[0], [1, 2]]
    _assert_a_partition(cp, pages, chunks, _SMALL_LIMIT)


def test_the_glossary_block_counts_toward_every_chunks_estimate(cp: ModuleType) -> None:
    """The Contract: "every chunk's text carries the glossary block (it is in
    the estimate)". Blocks of 143 + 143: with no glossary the pair is 288
    bytes (96 tokens) and is one chunk; with a 12-byte glossary it is
    12 + 2 + 288 = 302 bytes (101 tokens) and must split."""
    pages = tuple(_page(cp, i, 143) for i in range(2))
    glossary = "G" * 12
    assert estimate_tokens(cp.consistency_text(pages, "")) == 96
    assert estimate_tokens(cp.consistency_text(pages, glossary)) == 101

    assert [len(c) for c in cp.chunk_pages(pages, "", max_tokens=_SMALL_LIMIT)] == [2]
    assert [len(c) for c in cp.chunk_pages(pages, glossary, max_tokens=_SMALL_LIMIT)] == [1, 1]


def test_a_page_without_english_is_still_covered_by_a_chunk(cp: ModuleType) -> None:
    """AC-4's "covering every page exactly once" includes a page that renders
    to nothing: it is in some chunk, not lost."""
    pages = (
        _page(cp, 0, 143),
        cp.PageLines(1, ((0, "ドン", None),)),
        _page(cp, 2, 143),
    )

    chunks = cp.chunk_pages(pages, _G, max_tokens=_SMALL_LIMIT)

    _assert_a_partition(cp, pages, chunks, _SMALL_LIMIT)


def test_one_page_exactly_at_the_limit_is_a_chunk_of_its_own(cp: ModuleType) -> None:
    """A single page whose one-page text is 300 bytes (10 + 2 + 288) is at the
    limit, not over it."""
    page = _page(cp, 0, 288)
    assert estimate_tokens(cp.consistency_text((page,), _G)) == _SMALL_LIMIT

    assert cp.chunk_pages((page,), _G, max_tokens=_SMALL_LIMIT) == [(page,)]


def test_a_single_page_over_the_limit_raises_page_too_large_naming_page_estimate_and_limit(
    cp: ModuleType,
) -> None:
    """AC-4: `PageTooLarge`, its message carrying the page's `ordinal` (7),
    the estimate (1,234) and the limit (1,000), plain or comma-grouped - and
    nothing returned for the two pages before it.

    Ordinal 7 is `Page 8:`, a 7-byte header, so the block is 18 + m bytes and
    with no glossary that is the whole text: m = 3684 gives 3702 bytes =
    ceil(1234.0) = 1,234 tokens."""
    big = cp.PageLines(7, ((0, "a" * 3684, "b"),))
    assert estimate_tokens(cp.consistency_text((big,), "")) == 1234
    pages = (_page(cp, 5, 100), _page(cp, 6, 100), big)

    with pytest.raises(cp.PageTooLarge) as raised:
        cp.chunk_pages(pages, "", max_tokens=1000)

    message = str(raised.value)
    assert re.search(r"\b7\b", message), message
    assert re.search(r"\b1,?234\b", message), message
    assert re.search(r"\b1,?000\b", message), message


def test_one_byte_over_the_limit_on_a_single_page_is_too_large(cp: ModuleType) -> None:
    """The other side of the single-page boundary: 301 bytes, 101 tokens."""
    page = _page(cp, 0, 289)
    assert estimate_tokens(cp.consistency_text((page,), _G)) == 101

    with pytest.raises(cp.PageTooLarge, match=r"\b101\b"):
        cp.chunk_pages((page,), _G, max_tokens=_SMALL_LIMIT)


def test_no_pages_is_no_chunks(cp: ModuleType) -> None:
    assert cp.chunk_pages((), _G) == []
    assert cp.chunk_pages((), _G, max_tokens=_SMALL_LIMIT) == []


def test_the_limits_are_180000_in_and_8192_out_and_the_default_is_the_input_limit(
    cp: ModuleType,
) -> None:
    """The Contract, read out (MT-101 D-12): 200k tier on the whole prompt,
    20k headroom for the system instruction; and `max_tokens` defaults to it."""
    assert cp.CONSISTENCY_MAX_INPUT_TOKENS == 180_000
    assert cp.CONSISTENCY_MAX_OUTPUT_TOKENS == 8_192
    default = inspect.signature(cp.chunk_pages).parameters["max_tokens"].default
    assert default == cp.CONSISTENCY_MAX_INPUT_TOKENS


def _volume(cp: ModuleType) -> tuple[Any, ...]:
    """200 pages x 20 lines, ja 60 ASCII bytes, en 90: a line is
    `[i] ` (4 or 5 bytes) + 60 + `\\n    ` (5) + 90, about 160 bytes with its
    newline, so ~3,220 bytes (~1,073 tokens) a page and ~215k for the volume -
    the Context's ~1,200 tokens a page, rounded to ASCII."""
    return tuple(
        cp.PageLines(ordinal, tuple((i, "j" * 60, "e" * 90) for i in range(20)))
        for ordinal in range(200)
    )


def test_a_200_page_volume_over_the_default_limit_is_cut_into_more_than_one_chunk(
    cp: ModuleType,
) -> None:
    """AC-4's volume, under the DEFAULT `max_tokens`. Precondition: the whole
    volume estimates over 180,000 (and under 360,000, so greedy packing needs
    exactly two chunks: the first is within one page of the limit, leaving
    under 40k)."""
    pages = _volume(cp)
    total = estimate_tokens(cp.consistency_text(pages, _GLOSSARY))
    assert cp.CONSISTENCY_MAX_INPUT_TOKENS < total < 2 * cp.CONSISTENCY_MAX_INPUT_TOKENS, total

    chunks = cp.chunk_pages(pages, _GLOSSARY)

    assert len(chunks) > 1
    assert len(chunks) == 2, [len(c) for c in chunks]
    flat = [page for chunk in chunks for page in chunk]
    assert len(flat) == 200
    assert all(got is given for got, given in zip(flat, pages, strict=True))
    estimates = [estimate_tokens(cp.consistency_text(chunk, _GLOSSARY)) for chunk in chunks]
    assert max(estimates) <= cp.CONSISTENCY_MAX_INPUT_TOKENS, estimates


# -- SDK-free -----------------------------------------------------------------------


def test_importing_the_consistency_module_does_not_load_the_gemini_sdk() -> None:
    """The Contract's "SDK-free": a fresh interpreter, because this session
    has already imported `google.genai` elsewhere."""
    probe = (
        "import sys, mangatl.translate.consistency;"
        " print(sorted(m for m in sys.modules if m == 'google.genai'"
        " or m.startswith('google.genai.')))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60, check=False
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", done.stdout
