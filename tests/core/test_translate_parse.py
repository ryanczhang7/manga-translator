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

from collections.abc import Callable

import pytest

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
