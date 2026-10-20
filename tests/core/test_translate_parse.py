"""`mangatl.translate.parse`: which line belongs to which bubble.

Covers **AC-4** and **AC-6** at the level the logic actually lives, and C-4's
string-key conversion with it. The stage-level halves - that the right English
reaches the right `line` row, and that a bad index writes nothing - are in
`tests/core/test_translate_stage.py`.

**The fixtures' key order is deliberately not the region order**
(`fixtures/translate/README.md`, MT-011 falsifiable success condition 1). A
parser that assigns lines by **position in the response** rather than by region
index is silent, plausible, and indistinguishable from a correct one against a
fixture whose keys happen to arrive sorted. Measured on 2026-09-18 outside
pytest: `well-formed.json` distinguishes the two parsings on **4 of 4** regions
and `omits-region-3.json` on **2 of 3**. `tests/core/test_translate_fixtures.py`
asserts both numbers and imports nothing from `mangatl`, so it is the one file
here that runs - and was watched - while this module did not exist.

**The response is a stand-in, not an `anthropic.types.Message`.** No test in
MT-011 makes a network call or constructs an `Anthropic` client (PO-1). The
stand-in is `conftest.fake_message`, and what it is faithful about is documented
there: structured output puts the JSON in a `text` content block, and adaptive
thinking may put a `thinking` block - which has `.thinking` and no `.text` - in
front of it.

**Timing.** No `pytest-timeout` in this project and no per-test timeout exists,
so there is no budget in this file to size; if a later story adds one, every
test and hook here needs one. Nothing here decodes an image or touches a disk
beyond four files of ~120 bytes.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable

import pytest

from mangatl.domain.glossary import ProposedTerm
from mangatl.translate import parse
from mangatl.translate.parse import UnknownRegionIndex, parse_lines

#: The fixture page's reading indices. Four regions, 0..3 (C-4: "the page's
#: actual reading indices"), and `fixtures/translate/README.md` tabulates them.
_REGION_INDICES: tuple[int, ...] = (0, 1, 2, 3)

#: What a correct parser returns for `well-formed.json`: **int** keys (C-4).
_EXPECTED: dict[int, str] = {
    0: "As if a demon would move at a human's say-so.",
    1: "...I see.",
    2: "Why are you here?",
    3: "Let's go.",
}

#: What the position bug returns for the same fixture, whose keys arrive in the
#: order 2, 0, 3, 1. Written out so the failure says which corruption happened
#: rather than only that two dicts differ.
_POSITION_BUG: dict[int, str] = {
    0: "Why are you here?",
    1: "As if a demon would move at a human's say-so.",
    2: "Let's go.",
    3: "...I see.",
}


# -- AC-4 ----------------------------------------------------------------------


def test_each_region_gets_the_line_keyed_by_its_own_index_not_its_position(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """AC-4, both halves, against a fixture built to tell them apart.

    "Each region receives its proposed English on the matching region id" and
    "no region id is assigned a line belonging to another" are the same claim
    read from two directions, and only a response whose key order differs from
    the region order can distinguish a parser that honours it from one that
    zips. This fixture's does, on all four regions.
    """
    lines = parse_lines(fake_message(response_body("well-formed")), _REGION_INDICES)

    assert lines == _EXPECTED
    assert lines != _POSITION_BUG, (
        "the lines were assigned by position in the response rather than by"
        " region index - the right words are on the wrong bubbles"
    )


def test_the_returned_keys_are_ints_and_not_the_strings_json_carries(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """C-4. JSON object keys are strings; region ids are ints.

    A parser that left them as strings would return a dict every `int`-keyed
    lookup misses - `lines.get(3)` is `None` against `{"3": ...}` - so every
    region would read as untranslated and AC-5 would appear to hold for the
    whole page. Silent, and indistinguishable from "the model omitted them all".
    """
    lines = parse_lines(fake_message(response_body("well-formed")), _REGION_INDICES)

    assert all(isinstance(key, int) for key in lines), f"got keys {sorted(map(str, lines))}"
    assert set(lines) == set(_REGION_INDICES)


def test_a_thinking_block_in_front_of_the_json_does_not_hide_it(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """C-5 pins `thinking={"type": "adaptive"}`, so a real response can carry a
    `thinking` block **before** the text block. An implementation reaching for
    `response.content[0].text` works against every hand-made fixture that has
    only a text block and fails against the model this story actually calls -
    the failure arrives in MT-037, with a credential, after spending money."""
    message = fake_message(response_body("well-formed"), leading_thinking=True)

    assert parse_lines(message, _REGION_INDICES) == _EXPECTED


@pytest.mark.parametrize(
    "leading_thinking",
    [False, True],
    ids=["redacted-then-text", "redacted-then-thinking-then-text"],
)
def test_a_redacted_thinking_block_in_front_of_the_json_does_not_hide_it(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
    leading_thinking: bool,
) -> None:
    """MT-084 AC-2 (audit survivor P7). `anthropic` 0.125.0's content union
    includes `RedactedThinkingBlock`, which has `data` and `type` and **no**
    `text`. A reader that takes "the first block that is not `thinking`" for the
    text block passes every test above - the only other non-text block they
    build is `thinking` - and raises `AttributeError` on a real response that
    leads with a redacted block, losing a paid page. The lines must come from
    the text block, whatever sits in front of it."""
    message = fake_message(
        response_body("well-formed"),
        leading_redacted_thinking=True,
        leading_thinking=leading_thinking,
    )
    first = message.content[0]
    assert first.type == "redacted_thinking", "precondition: the redacted block must come first"
    assert not hasattr(first, "text"), "precondition: a redacted block carries no `text`"

    assert parse_lines(message, _REGION_INDICES) == {
        0: "As if a demon would move at a human's say-so.",
        1: "...I see.",
        2: "Why are you here?",
        3: "Let's go.",
    }


# -- AC-5, at the parse level --------------------------------------------------


def test_a_region_the_response_omitted_is_simply_absent_from_the_result(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """AC-5's first half, and C-2's "sparse: an index absent here is AC-5's
    untranslated region". Absent, not present-and-empty: the store has to be
    able to tell "the model said nothing about region 3" from "the model
    proposed the empty string for region 3", and only absence does that.

    The page is **not** discarded - the other three regions come back - which is
    the clause AC-5 exists for.
    """
    lines = parse_lines(fake_message(response_body("omits-region-3")), _REGION_INDICES)

    assert 3 not in lines
    assert lines == {index: _EXPECTED[index] for index in (0, 1, 2)}


def test_an_empty_response_object_returns_no_lines_rather_than_raising(
    fake_message: Callable[..., object],
) -> None:
    """The zero of zero-one-many, and AC-5 taken to its limit: a compliant model
    may omit every region, because C-5's schema marks none required. That is a
    page with nothing proposed, not an error."""
    assert parse_lines(fake_message("{}"), _REGION_INDICES) == {}


def test_a_single_named_region_comes_back_on_its_own(
    fake_message: Callable[..., object],
) -> None:
    """The one of zero-one-many, at an index that is neither the first nor the
    last of the page - so a parser that special-cased either end is caught."""
    assert parse_lines(fake_message('{"2": "Why are you here?"}'), _REGION_INDICES) == {
        2: "Why are you here?"
    }


# -- AC-6 ----------------------------------------------------------------------


def test_the_exception_type_is_its_own_and_not_a_kind_of_value_error() -> None:
    """C-4 spells it `class UnknownRegionIndex(Exception)`, and that is load-
    bearing rather than cosmetic: the test below asserts a **non-integer** key
    raises `UnknownRegionIndex` "rather than a `ValueError` escaping from
    `int()`", and if the type were a `ValueError` subclass that test could not
    tell the two apart."""
    assert UnknownRegionIndex.__bases__ == (Exception,)


def test_an_index_this_page_does_not_have_is_raised_by_name(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """AC-6. Naming the index is the criterion, not decoration: without it the
    user is told a page failed and has nothing to look at. `7` is far enough
    from `0..3` that it cannot be confused with a neighbour.

    C-4: `parse_lines` validates **independently of the response schema**. The
    schema is the server's job; this function's contract is its own.
    """
    message = fake_message(response_body("unknown-region-index"))

    with pytest.raises(UnknownRegionIndex, match=r"\b7\b"):
        parse_lines(message, _REGION_INDICES)


def test_a_key_that_is_not_an_integer_raises_the_same_way_rather_than_escaping(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """C-4's other half. `int("first")` raises `ValueError: invalid literal for
    int() with base 10: 'first'`, which names nothing the caller can act on and
    is not the exception AC-6 says this function raises."""
    message = fake_message(response_body("non-integer-key"))

    with pytest.raises(UnknownRegionIndex, match="first"):
        parse_lines(message, _REGION_INDICES)


def test_an_index_one_past_the_end_of_the_page_is_rejected_like_any_other(
    fake_message: Callable[..., object],
) -> None:
    """The boundary. `4` on a four-region page is the off-by-one a model makes
    when it counts from one, and it is the value a bounds check written as
    `index > len(region_indices)` lets through."""
    with pytest.raises(UnknownRegionIndex, match=r"\b4\b"):
        parse_lines(fake_message('{"4": "A line for a fifth bubble."}'), _REGION_INDICES)


def test_a_negative_index_is_rejected_rather_than_wrapping_round(
    fake_message: Callable[..., object],
) -> None:
    """The other boundary, and the one a Python implementation gets wrong for
    free: `region_indices[-1]` is region 3, so a check written as an index into
    the sequence accepts `-1` and silently files the line under the last
    bubble on the page."""
    with pytest.raises(UnknownRegionIndex, match="-1"):
        parse_lines(
            fake_message('{"-1": "A line for a bubble before the first."}'), _REGION_INDICES
        )


def test_a_page_with_no_regions_rejects_every_index(
    fake_message: Callable[..., object],
) -> None:
    """The zero of zero-one-many on the *other* argument: a page the detector
    found nothing on has no index a response could legitimately name."""
    with pytest.raises(UnknownRegionIndex, match=r"\b0\b"):
        parse_lines(fake_message('{"0": "A line for a bubble that is not there."}'), ())


# -- Out of scope, pinned where it is cheap: refusals --------------------------


def test_a_body_that_is_not_json_is_loud_rather_than_silently_empty(
    fake_message: Callable[..., object],
) -> None:
    """MT-011 `## Out of scope`: Opus 5 can return **HTTP 200** with
    `stop_reason: "refusal"` and no usable content. The SDK does not raise, and
    a manga page is exactly the kind of input that trips a safety classifier.

    Handling it properly needs a fallback or a retry path, and `architecture.md`
    D5 puts a second pass over the budget - so this story's answer is that
    `parse_lines` raises on the non-JSON body, "which is loud rather than silent
    and is acceptable". This test is what makes that an answer rather than a
    hope: an implementation that swallowed the parse error and returned `{}`
    would mark every bubble untranslated and look exactly like a quiet model.
    """
    message = fake_message(
        "I'm not able to help with translating this page.", stop_reason="refusal"
    )

    with pytest.raises((ValueError, UnknownRegionIndex)):
        parse_lines(message, _REGION_INDICES)


# -- MT-014 C-4: the one key that is not a region -------------------------------


def test_the_glossary_key_is_skipped_rather_than_read_as_a_region(
    fake_message: Callable[..., object],
) -> None:
    """MT-014 C-4: `parse_lines` skips the key `"glossary"`. Without it every
    response that proposes a term raises `UnknownRegionIndex('glossary')` and
    the page's lines are lost over an advisory field - which is exactly the
    wrong trade C-4 names."""
    body = (
        '{"0": "Sakura!", "glossary": '
        '[{"term_ja": "さくら", "term_en": "Sakura", "note": "name"}], "2": "Why?"}'
    )

    assert parse_lines(fake_message(body), _REGION_INDICES) == {0: "Sakura!", 2: "Why?"}


def test_an_empty_glossary_beside_no_lines_is_an_empty_page_and_not_an_error(
    fake_message: Callable[..., object],
) -> None:
    """The zero of C-4's skip: a body whose only key is `glossary`."""
    assert parse_lines(fake_message('{"glossary": []}'), _REGION_INDICES) == {}


@pytest.mark.parametrize("key", ["Glossary", "glossary ", "terms", "glossary_"])
def test_only_the_exact_glossary_key_is_skipped_and_its_neighbours_still_raise(
    fake_message: Callable[..., object], key: str
) -> None:
    """The negative control for the skip, and MT-011 AC-6 unchanged: **only**
    `"glossary"` is skipped. A skip written as "any non-integer key" or as a
    case-folded or prefix match passes the two tests above and silently turns
    every malformed key into a dropped one."""
    body = f'{{"0": "Sakura!", "{key}": []}}'

    with pytest.raises(UnknownRegionIndex, match=key.strip()):
        parse_lines(fake_message(body), _REGION_INDICES)


# =============================================================================
# MT-079: the split at the text
# =============================================================================
#
# The new names are reached as `parse.<name>` at call time, not imported at the
# top, so that every test above still collects while they do not exist: the
# RED failure for each test below is an `AttributeError` naming the missing
# function, and nothing else in this file goes dark.
#
# These are new names over logic MT-011/MT-014 already built, so once GREEN
# lands they may pass on arrival. Deferred verification 2 earns AC-3's by
# returning string keys from `parse_lines_text` (owner: GATES).

_WELL_FORMED_TERMS = (
    '{"0": "Sakura!", "glossary": ['
    '{"term_ja": "さくら", "term_en": "Sakura", "note": "name"}, '
    '{"term_ja": "先輩", "term_en": "senpai", "note": "honorific"}]}'
)
_MALFORMED_TERMS = (
    '{"glossary": ['
    '{"term_ja": "さくら", "term_en": "Sakura", "note": "name"}, '
    '"not an object", '
    '{"term_ja": "東京", "term_en": "Tokyo"}, '
    '{"term_ja": "醜鬼", "term_en": 7, "note": ""}, '
    '{"term_ja": "東京", "term_en": "Tokyo", "note": "place"}]}'
)


# -- AC-3 ----------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["well-formed", "omits-region-3"])
def test_parse_lines_text_returns_what_parse_lines_returns_for_the_same_body(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
    fixture: str,
) -> None:
    """AC-3: the text entry point and the `Message` entry point agree, on the
    fixture keyed out of order and on the one that omits a region. The literal
    is compared too, so the two cannot agree on a wrong answer."""
    body = response_body(fixture)
    expected = _EXPECTED if fixture == "well-formed" else {i: _EXPECTED[i] for i in (0, 1, 2)}

    lines = parse.parse_lines_text(body, _REGION_INDICES)

    assert lines == parse_lines(fake_message(body), _REGION_INDICES)
    assert lines == expected
    assert lines != _POSITION_BUG


def test_parse_lines_text_returns_int_keys_not_the_strings_json_carries(
    response_body: Callable[[str], str],
) -> None:
    """AC-3 with C-4's key conversion: a string-keyed dict makes every region
    read as untranslated. This is the assertion Deferred verification 2's
    mutation (string keys back) must turn red."""
    lines = parse.parse_lines_text(response_body("well-formed"), _REGION_INDICES)

    assert all(type(key) is int for key in lines), f"got keys {sorted(map(repr, lines))}"
    assert set(lines) == set(_REGION_INDICES)


@pytest.mark.parametrize(
    ("body", "named"),
    [
        ('{"7": "A line for no bubble."}', r"\b7\b"),
        ('{"first": "A line keyed by a word."}', "first"),
        ('{"-1": "A line before the first bubble."}', "-1"),
    ],
    ids=["out-of-range", "non-integer", "negative"],
)
def test_parse_lines_text_raises_unknown_region_index_where_parse_lines_does(
    fake_message: Callable[..., object], body: str, named: str
) -> None:
    """AC-3's "including raising `UnknownRegionIndex` for the same inputs" -
    naming the key, as MT-011 AC-6 requires of `parse_lines`."""
    with pytest.raises(UnknownRegionIndex, match=named):
        parse_lines(fake_message(body), _REGION_INDICES)
    with pytest.raises(UnknownRegionIndex, match=named):
        parse.parse_lines_text(body, _REGION_INDICES)


def test_parse_lines_text_skips_the_glossary_key() -> None:
    """MT-014 C-4 through the text entry point: `"glossary"` is not a region."""
    assert parse.parse_lines_text(_WELL_FORMED_TERMS, _REGION_INDICES) == {0: "Sakura!"}


def test_parse_lines_text_on_a_non_json_body_is_loud() -> None:
    """C-3: "the non-JSON body still raises out of `json.loads`"."""
    with pytest.raises(json.JSONDecodeError):
        parse.parse_lines_text("I'm not able to help with that.", _REGION_INDICES)


def test_parse_lines_delegates_to_parse_lines_text_with_the_first_text_block(
    monkeypatch: pytest.MonkeyPatch,
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """AC-3's last clause: `parse_lines(message, ...)` **is**
    `parse_lines_text(first_text_block(message), ...)`. Observed with a
    recorder in place of `parse_lines_text`; a `parse_lines` that kept its own
    copy of the loop would never call it. The leading thinking block makes
    "first text block" and `content[0]` disagree."""
    body = response_body("well-formed")
    calls: list[tuple[str, object]] = []
    sentinel = {99: "recorded"}

    def recorder(text: str, region_indices: object) -> dict[int, str]:
        calls.append((text, region_indices))
        return sentinel

    monkeypatch.setattr(parse, "parse_lines_text", recorder)

    result = parse.parse_lines(fake_message(body, leading_thinking=True), _REGION_INDICES)

    assert calls == [(body, _REGION_INDICES)], (
        "parse_lines did not delegate to parse_lines_text with the first text block's text"
    )
    assert result is sentinel


# -- first_text_block ----------------------------------------------------------


def test_first_text_block_is_the_first_text_blocks_text_not_content_zero(
    fake_message: Callable[..., object],
) -> None:
    """C-3: what `_body` read, now public. Behind a thinking block, because
    `content[0]` is the bug MT-011 C-4's RED amendment names."""
    message = fake_message('{"0": "x"}', leading_thinking=True)

    assert parse.first_text_block(message) == '{"0": "x"}'


def test_first_text_block_of_a_message_with_no_text_block_raises_value_error_naming_it(
    fake_message: Callable[..., object],
) -> None:
    """C-3, pinned by RED (see the amendment in the story's `## Contract`): no
    text block raises `ValueError` saying so, not a bare `StopIteration` - which
    names nothing, and which PEP 479 turns into a `RuntimeError` the moment the
    call sits inside a generator. Not a `JSONDecodeError` either: that is a
    `ValueError` too, so the message is what tells them apart."""
    with_thinking = fake_message("{}", leading_thinking=True)
    thinking_only = dataclasses.replace(with_thinking, content=with_thinking.content[:1])

    with pytest.raises(ValueError, match="text block") as raised:
        parse.first_text_block(thinking_only)
    assert not isinstance(raised.value, json.JSONDecodeError)


# -- AC-4 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            _WELL_FORMED_TERMS,
            (ProposedTerm("さくら", "Sakura", "name"), ProposedTerm("先輩", "senpai", "honorific")),
        ),
        (
            _MALFORMED_TERMS,
            (ProposedTerm("さくら", "Sakura", "name"), ProposedTerm("東京", "Tokyo", "place")),
        ),
        ('{"0": "Sakura!"}', ()),
        ('{"glossary": []}', ()),
    ],
    ids=["well-formed", "malformed-items-skipped", "no-glossary-key", "empty-glossary"],
)
def test_parse_terms_text_returns_what_parse_terms_returns_for_the_same_body(
    fake_message: Callable[..., object],
    body: str,
    expected: tuple[ProposedTerm, ...],
) -> None:
    """AC-4: same terms, in the response's order; a malformed item (not an
    object, a field missing, a field not a string) skipped with its neighbours
    kept; `()` with no `glossary` key."""
    terms = parse.parse_terms_text(body)

    assert terms == expected
    assert terms == parse.parse_terms(fake_message(body))


def test_parse_terms_delegates_to_parse_terms_text_with_the_first_text_block(
    monkeypatch: pytest.MonkeyPatch,
    fake_message: Callable[..., object],
) -> None:
    """AC-4's delegation, observed the same way as AC-3's."""
    calls: list[str] = []
    sentinel = (ProposedTerm("記録", "recorded", ""),)

    def recorder(text: str) -> tuple[ProposedTerm, ...]:
        calls.append(text)
        return sentinel

    monkeypatch.setattr(parse, "parse_terms_text", recorder)

    result = parse.parse_terms(fake_message(_WELL_FORMED_TERMS, leading_thinking=True))

    assert calls == [_WELL_FORMED_TERMS], (
        "parse_terms did not delegate to parse_terms_text with the first text block's text"
    )
    assert result is sentinel


def test_parse_exports_the_three_new_names_and_keeps_the_old_four() -> None:
    """C-3: `__all__` grows by exactly three names. Pinned in the sorted order
    the existing list already uses (isort-style, which ruff's RUF022 enforces),
    and `GLOSSARY_KEY` still importable from `parse` with its value."""
    assert parse.__all__ == [
        "GLOSSARY_KEY",
        "UnknownRegionIndex",
        "first_text_block",
        "parse_lines",
        "parse_lines_text",
        "parse_terms",
        "parse_terms_text",
    ]
    assert parse.GLOSSARY_KEY == "glossary"
