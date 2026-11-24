"""`mangatl.translate.page_prompt`: the request's five parts, provider-neutral.

MT-079. Covers **AC-1** (the golden: Claude's request is byte-for-byte what it
was), **AC-2** (the response schema) and **AC-5** (the module loads no SDK). The
parse half of the story, AC-3 and AC-4, is in `test_translate_parse.py`.

**Amended by MT-106** ("pages stop proposing glossary terms"), in place: the
system-prompt golden loses the glossary-proposal bullet (MT-106 AC-6, C-2), and
the expected request's schema is now written out literally (MT-106 AC-1) instead
of read off `page_prompt.response_schema` - read off it, the byte-for-byte pin
moved with whatever the schema became. Everything else MT-079 pinned is
unchanged.

**Amended by MT-147** ("the page answer names drawn art text"), in place, by
C-2: the golden gains one bullet, inserted after the answer bullets
(`_ART_BULLET_MT147`), and the expected schema gains an `art_text` property
for a page with at least one region (`_art_property`). `page_prompt.__all__`
gains `ART_KEY`. Nothing else MT-079, MT-106 or MT-149 pinned moves.

**Why the system prompt is pinned as a literal here, not read off `prompt`.**
Deferred verification 1 is "one character of `SYSTEM_PROMPT` changed must turn
AC-1 red". `test_translate_prompt.py` pins only a phrase of it, so a test that
compared `page_prompt.SYSTEM_PROMPT` with whatever `build_request` sends would
pass against *any* text, both sides moving together. `_SYSTEM_PROMPT_GOLDEN`
below is the text of `prompt._SYSTEM_PROMPT` copied verbatim out of
`src/mangatl/translate/prompt.py` (lines 105-130) on 2026-10-10, before this
story moved it, and checked equal to it out-of-tree during RED (see the story's
`## Handoff`).

**The whole kwargs are compared, not five fields of them.** AC-1 says the
returned kwargs are *equal* to the pre-story ones. The expected dict is written
out below with every constant the pre-story `build_request` used - model, effort,
thinking, cache breakpoint, media type - and the five page-varying parts taken
from `page_prompt`. A field added, dropped or moved fails the equality, which
five targeted lookups could not see.

**Timing.** No `pytest-timeout` in this project and no per-test timeout exists,
so there is no budget in this file to size. The largest page built here is
1800x1200 through `conftest.png_bytes`; the two subprocess probes carry the
same explicit `timeout=60` as `test_translate_provider.py`'s.
"""

from __future__ import annotations

import ast
import base64
import re
import subprocess
import sys
from collections.abc import Callable
from typing import Any

import pytest

from mangatl.domain.glossary import EMPTY_CONTEXT, PromptContext
from mangatl.domain.line import OcrResult
from mangatl.translate import page_prompt, prompt

# -- pinned values -------------------------------------------------------------

#: `prompt._SYSTEM_PROMPT` before MT-079, verbatim. Every character is the
#: criterion: one changed character invalidates the cache for every page of
#: every chapter and changes what the model is asked (`## Out of scope`).
#:
#: **Re-pinned by MT-106** (AC-6, C-2, PO-1 - the user's decision, 2026-11-06):
#: the final bullet of "Continuity across pages" - the one asking the model to
#: add new terms under the `glossary` key - is removed, with the newline before
#: it, and not one other character changed. The pre-MT-106 text is this one
#: plus that bullet; `_SYSTEM_PROMPT_PRE_MT106_LAST_BULLET` below holds it so
#: the "nothing else changed" half of AC-6 is a comparison, not a reading.
#:
#: **Re-pinned by MT-149** (AC-1, PO-1, and the story's `## Contract` C-1b): the
#: last "Guidance" bullet, `_ANSWER_PRE_MT149`, is replaced by `_ANSWER_MT149`,
#: and not one other character changes. This literal is the pre-MT-149 text;
#: `_SYSTEM_PROMPT_GOLDEN` below is derived from it by that one replacement, so
#: "nothing else changed" is again a comparison.
_SYSTEM_PROMPT_PRE_MT149 = """You translate Japanese manga into natural English.

You are given one page image and the text OCR read from each of its regions, \
listed in reading order (right to left, top to bottom). Translate every region \
into English, using the art to decide pronouns, speaker attribution, honorifics \
and continuity - that is why you are given the page and not just the text.

Guidance:
- Keep each line's register and tone. Manga dialogue is spoken, not literary.
- A region whose source text is empty is one the OCR missed. If you can read \
that bubble from the page image, translate what it says; if it genuinely has no \
text, leave it out of your answer.
- If you cannot read a region at all, leave it out of your answer rather than \
guessing. An omitted region is recorded as untranslated, which is recoverable; \
an invented line is not.
- Answer with one entry per region, keyed by the region's reading index.

Continuity across pages:
- You may also be given a glossary of names, honorifics and place names this \
chapter has already settled on, and the previous page's English in reading \
order. Use the glossary's renderings exactly, every time, and read the previous \
page for who is speaking and what is being continued."""

#: MT-149: the answer-format bullet before this story, verbatim.
_ANSWER_PRE_MT149 = "- Answer with one entry per region, keyed by the region's reading index.\n"

#: MT-149 C-1b: what replaces it. Three bullets: the entry's shape; `ja` is a
#: copy of the listing even where the model believes the listing was misread,
#: and the model's own reading only where the listing is empty (PO-1); `en`
#: may still come from the image.
_ANSWER_MT149 = """\
- Answer with one entry per region, keyed by the region's reading index. Each \
entry is an object with two fields, "ja" and "en".
- In "ja", copy the region's Japanese exactly as it is listed above, even where \
you believe the listing was misread. Only when a region's listing is empty, \
write in "ja" the Japanese you read in that bubble on the page image.
- In "en", write the English for that region. Where the listing looks misread, \
you may translate from the page image instead; "ja" stays a copy of the listing.
"""

#: The system prompt MT-149 pinned, to the character - the text before MT-147.
_SYSTEM_PROMPT_PRE_MT147 = _SYSTEM_PROMPT_PRE_MT149.replace(_ANSWER_PRE_MT149, _ANSWER_MT149)

#: MT-147 C-2: the one bullet inserted directly after the `- In "en", write the
#: English` bullet (the last line of `_ANSWER_MT149`) and before the blank line
#: above `Continuity across pages:`. Verbatim from the story's Contract; each
#: trailing backslash is a line continuation, so the bullet is one line.
_ART_BULLET_MT147 = """\
- The one exception to translating every region is text drawn into the \
artwork itself: sound effects, signs, labels on objects. List the reading \
index of each such region under the "art_text" key and give that region no \
entry and no translation. Dialogue, narration and captions are never art \
text, however they are lettered.
"""

#: The system prompt this story pins, to the character: MT-149's text with the
#: art bullet inserted after the answer bullets, and not one other character
#: changed (MT-147 C-2).
_SYSTEM_PROMPT_GOLDEN = _SYSTEM_PROMPT_PRE_MT147.replace(
    _ANSWER_MT149, _ANSWER_MT149 + _ART_BULLET_MT147
)

#: The bullet MT-106 removed, verbatim, with the newline that preceded it. The
#: pre-MT-106 prompt was exactly `_SYSTEM_PROMPT_PRE_MT149 + this`.
_SYSTEM_PROMPT_PRE_MT106_LAST_BULLET = """
- When a character name, an honorific or a place name appears on this page that \
the glossary does not have, add it under the "glossary" key: its Japanese as \
written, the English you used, and a note of "name", "honorific" or "place" \
("" for anything else). Do not repeat terms the glossary already has."""

#: MT-014 C-3's glossary property, re-pinned verbatim from
#: `test_translate_prompt.py` (`_GLOSSARY_SCHEMA`) rather than imported from it:
#: one test module importing another's private constant couples their
#: collection, and the value is short enough to read twice.
_GLOSSARY_SCHEMA_GOLDEN: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "term_ja": {"type": "string"},
            "term_en": {"type": "string"},
            "note": {"type": "string", "enum": ["name", "honorific", "place", ""]},
        },
        "required": ["term_ja", "term_en", "note"],
        "additionalProperties": False,
    },
}

#: `prompt.__all__` before MT-079 (C-2: "unchanged").
_PROMPT_ALL = [
    "MAX_IMAGE_LONG_EDGE_PX",
    "MAX_OUTPUT_TOKENS",
    "MODEL_ID",
    "build_request",
    "prepare_page_image",
]

#: Two regions in reading order, one of them `ocr_empty` (PO-11: listed like
#: any other, with empty source text).
_OCR_RESULTS: tuple[OcrResult, ...] = (
    OcrResult(text="どうして君がここに"),
    OcrResult(text="", ocr_empty=True),
)

_CONTEXT = PromptContext(
    glossary_block="Glossary - use these renderings exactly:\nさくら = Sakura (name)",
    rolling_block="Previous page, in reading order:\nWait up, Sakura!",
)


def _region_property(index: int) -> dict[str, Any]:
    """One region's schema property, written out - `description`s included,
    which are part of what Claude is sent.

    MT-149 AC-1 and C-1b: an object with required string fields `ja` and `en`
    and `additionalProperties: False` (it was one string before MT-149)."""
    return {
        "type": "object",
        "description": f"The region at reading index {index}.",
        "properties": {
            "ja": {
                "type": "string",
                "description": "The region's Japanese, copied exactly as listed.",
            },
            "en": {"type": "string", "description": "The English for the region."},
        },
        "required": ["ja", "en"],
        "additionalProperties": False,
    }


def _art_property(region_count: int) -> dict[str, Any]:
    """MT-147 C-2's `art_text` property, written out: an array of integers
    restricted by an `enum` to the page's reading indices, with no
    `uniqueItems` and no `minimum`/`maximum` (PO-1)."""
    return {
        "type": "array",
        "description": "Reading indices of regions whose text is drawn into the artwork.",
        "items": {"type": "integer", "enum": list(range(region_count))},
    }


def _expected_schema(region_count: int) -> dict[str, Any]:
    """MT-106 AC-1's page schema, literally: one `{ja, en}` object per reading index (MT-149), no
    `glossary` property, no `required`, `additionalProperties: False` - and, for a page with at
    least one region, MT-147's `art_text` beside the indices. A page with none has no properties."""
    properties: dict[str, Any] = {
        str(index): _region_property(index) for index in range(region_count)
    }
    if region_count >= 1:
        properties["art_text"] = _art_property(region_count)
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }


def _expected_request(
    page_image: bytes, ocr_results: tuple[OcrResult, ...], context: PromptContext
) -> dict[str, Any]:
    """The pre-story `build_request` kwargs, with its constants written out and
    its five page-varying parts taken from `page_prompt`."""
    prepared, _ = page_prompt.prepare_page_image(page_image)
    context_blocks = (
        []
        if context == EMPTY_CONTEXT
        else [{"type": "text", "text": page_prompt.context_text(context)}]
    )
    return {
        "model": "claude-opus-5",
        "max_tokens": 4096,
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": "medium",
            "format": {
                "type": "json_schema",
                # Written out rather than read off `page_prompt.response_schema`
                # (MT-106): read off it, a schema change moves both sides of
                # this equality together and the byte-for-byte pin sees nothing.
                "schema": _expected_schema(len(ocr_results)),
            },
        },
        "system": [
            {
                "type": "text",
                "text": page_prompt.SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.b64encode(prepared).decode("ascii"),
                        },
                    },
                    *context_blocks,
                    {"type": "text", "text": page_prompt.user_text(ocr_results)},
                ],
            }
        ],
    }


# -- AC-1: the golden ----------------------------------------------------------


def test_the_system_prompt_is_the_pre_story_text_to_the_character() -> None:
    """AC-1 and Deferred verification 1: the whole text, not a phrase of it.
    A difference here is a change to what Claude is asked and to the cache
    prefix every page shares - a product decision, not a refactor."""
    assert page_prompt.SYSTEM_PROMPT == _SYSTEM_PROMPT_GOLDEN, (
        "page_prompt.SYSTEM_PROMPT is not the pinned system prompt (MT-079's text"
        " less the glossary-proposal bullet MT-106 removed); not one other"
        " character may change"
    )


def test_the_system_prompt_no_longer_asks_pages_to_add_glossary_terms() -> None:
    """MT-106 AC-6, stated on its own so a failure reads as the behaviour: the
    page schema forbids a `glossary` key, so the prompt must not ask for one,
    and it still tells the model to use the glossary's renderings exactly."""
    assert _SYSTEM_PROMPT_PRE_MT106_LAST_BULLET not in page_prompt.SYSTEM_PROMPT, (
        "SYSTEM_PROMPT still asks every page to add new terms under the"
        ' "glossary" key, which the page schema no longer allows'
    )
    assert 'under the "glossary" key' not in page_prompt.SYSTEM_PROMPT
    assert "Use the glossary's renderings exactly, every time" in page_prompt.SYSTEM_PROMPT


# -- MT-149 AC-1: the echo instruction -----------------------------------------


def test_the_pinned_prompt_differs_from_the_pre_story_one_only_in_the_answer_bullets() -> None:
    """The golden's own precondition: the old answer bullet occurs exactly once
    in the pre-MT-149 text, so the replacement that derives MT-149's text
    changes that bullet and nothing else (MT-147 then inserts one bullet; see
    `test_the_prompt_gains_the_art_bullet_once_and_no_other_character`)."""
    assert _SYSTEM_PROMPT_PRE_MT149.count(_ANSWER_PRE_MT149) == 1
    assert _SYSTEM_PROMPT_PRE_MT147 != _SYSTEM_PROMPT_PRE_MT149
    head, tail = _SYSTEM_PROMPT_PRE_MT149.split(_ANSWER_PRE_MT149)
    assert head + _ANSWER_MT149 + tail == _SYSTEM_PROMPT_PRE_MT147


def test_the_prompt_tells_the_model_to_copy_each_listing_into_ja_even_where_it_looks_misread() -> (
    None
):
    """AC-1 / PO-1: `ja` is a copy of the listing and nothing else, so a
    mismatch means a slip. The needle is the whole instruction, anchored at its
    imperative: a prompt saying *not* to copy, or to copy only where the listing
    looks right, does not contain it."""
    assert (
        '- In "ja", copy the region\'s Japanese exactly as it is listed above, even where'
        " you believe the listing was misread." in page_prompt.SYSTEM_PROMPT
    ), "SYSTEM_PROMPT does not tell the model to copy the listing into `ja` as listed"


def test_the_prompt_lets_the_model_write_its_own_reading_into_ja_only_for_an_empty_listing() -> (
    None
):
    """AC-1: "write what it reads in the image only when the listing for that
    region is empty"."""
    assert (
        'Only when a region\'s listing is empty, write in "ja" the Japanese you read'
        " in that bubble on the page image." in page_prompt.SYSTEM_PROMPT
    )


def test_the_prompt_no_longer_lets_the_model_rewrite_a_listing_it_thinks_is_wrong() -> None:
    """PO-1: AC-1's first draft let the model write what it reads "when the
    listing is empty or wrong", which pulls against the check - a corrected
    echo of a hallucinated listing drops a correctly keyed line. Neither that
    permission nor any instruction to correct the listing may survive."""
    prompt_text = page_prompt.SYSTEM_PROMPT
    # Control: the needles fire on the wording PO-1 withdrew, so passing below
    # is a statement about the prompt and not about a regex that matches nothing.
    withdrawn = "write what you read in the image when the listing is empty or wrong"
    assert re.search(r"\bempty or wrong\b", withdrawn) is not None
    assert re.search(r"\bcorrect(ing)? the listing\b", "Correct the listing.", re.I) is not None

    assert re.search(r"\bempty or wrong\b", prompt_text) is None
    assert re.search(r"\bcorrect(ing)? the listing\b", prompt_text, re.IGNORECASE) is None
    assert re.search(r"\bfix(ing)? the listing\b", prompt_text, re.IGNORECASE) is None


@pytest.mark.parametrize(
    ("size", "context"),
    [
        ((64, 48), EMPTY_CONTEXT),
        ((64, 48), _CONTEXT),
        ((1800, 1200), _CONTEXT),
    ],
    ids=["small-page-empty-context", "small-page-with-context", "capped-page-with-context"],
)
def test_build_request_returns_exactly_the_pre_story_kwargs_composed_from_page_prompt(
    png_bytes: Callable[..., bytes],
    size: tuple[int, int],
    context: PromptContext,
) -> None:
    """AC-1, whole: `build_request`'s kwargs equal the pre-story kwargs, with
    the system text, the listing, the context block, the image and the schema
    each being `page_prompt`'s. The empty context gives `[image, listing]` with
    no context block (MT-014: the Messages API rejects an empty text block);
    the 1800x1200 page goes through the cap."""
    page = png_bytes(*size)

    kwargs, est_tokens = prompt.build_request(page, _OCR_RESULTS, context)

    assert kwargs == _expected_request(page, _OCR_RESULTS, context), (
        "build_request is not the pinned Claude request (MT-079's kwargs, with MT-106's"
        " schema: no glossary property)"
    )
    assert est_tokens == page_prompt.prepare_page_image(page)[1]


def test_the_five_parts_land_where_ac1_names_them(png_bytes: Callable[..., bytes]) -> None:
    """AC-1's five clauses read off the request one by one, so a failure names
    the part that moved rather than only that two dicts differ."""
    page = png_bytes(64, 48)

    kwargs, _ = prompt.build_request(page, _OCR_RESULTS, _CONTEXT)
    (message,) = kwargs["messages"]
    image, context_block, listing = message["content"]

    assert kwargs["system"][0]["text"] == page_prompt.SYSTEM_PROMPT
    assert listing["text"] == page_prompt.user_text(_OCR_RESULTS)
    assert context_block["text"] == page_prompt.context_text(_CONTEXT)
    assert base64.b64decode(image["source"]["data"]) == page_prompt.prepare_page_image(page)[0]
    assert kwargs["output_config"]["format"]["schema"] == page_prompt.response_schema(
        len(_OCR_RESULTS)
    )


def test_the_region_listing_is_the_pre_story_text() -> None:
    """`user_text` pinned as a value, not only as "what `build_request` uses":
    otherwise a reworded listing moves both sides of AC-1 together."""
    assert page_prompt.user_text(_OCR_RESULTS) == (
        "Here is the page, and the text OCR read from each of its regions in"
        " reading order:\n\n[0] どうして君がここに\n[1] "
    )


def test_a_page_with_no_regions_lists_none() -> None:
    """The zero of the listing: the preamble and nothing after it."""
    assert page_prompt.user_text(()) == (
        "Here is the page, and the text OCR read from each of its regions in reading order:\n\n"
    )


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (_CONTEXT, f"{_CONTEXT.glossary_block}\n\n{_CONTEXT.rolling_block}"),
        (PromptContext(glossary_block="G", rolling_block=""), "G"),
        (PromptContext(glossary_block="", rolling_block="R"), "R"),
    ],
    ids=["both", "glossary-only", "rolling-only"],
)
def test_the_context_block_is_the_non_empty_halves_joined_by_a_blank_line(
    context: PromptContext, expected: str
) -> None:
    """`context_text` pinned as a value: glossary first, then rolling, an empty
    half omitted rather than leaving a stray blank line."""
    assert page_prompt.context_text(context) == expected


def test_the_image_cap_is_1568_and_prompt_re_exports_the_same_objects() -> None:
    """C-1 and C-2: the cap moved, its value did not, and `prompt` re-exports
    the very objects so `test_translate_prompt.py` imports as before."""
    assert page_prompt.MAX_IMAGE_LONG_EDGE_PX == 1568
    assert prompt.MAX_IMAGE_LONG_EDGE_PX is page_prompt.MAX_IMAGE_LONG_EDGE_PX
    assert prompt.prepare_page_image is page_prompt.prepare_page_image, (
        "prompt.prepare_page_image is a second implementation, not page_prompt's re-exported"
    )


def test_prompts_public_surface_is_unchanged() -> None:
    """C-2: `prompt.__all__` is exactly what it was."""
    assert prompt.__all__ == _PROMPT_ALL


def test_the_glossary_key_lives_in_page_prompt_with_its_value_unchanged() -> None:
    """The lead-po amendment to C-1: `GLOSSARY_KEY` moves to `page_prompt`
    (so `page_prompt` need not import `parse`, which loads the SDK)."""
    assert page_prompt.GLOSSARY_KEY == "glossary"


# -- AC-2: the response schema -------------------------------------------------


def test_the_glossary_schema_is_mt014s_verbatim() -> None:
    """AC-2's last clause: the array-of-`{term_ja, term_en, note}` schema
    MT-014 C-3 pins."""
    assert page_prompt.GLOSSARY_SCHEMA == _GLOSSARY_SCHEMA_GOLDEN


def test_the_glossary_names_stay_exported_for_the_pre_pass() -> None:
    """MT-106 AC-4's last clause and C-1: `GLOSSARY_SCHEMA` and `GLOSSARY_KEY`
    leave the page schema but not the module - `glossary_pass` builds the
    pre-pass schema from both. MT-147 C-1 adds `ART_KEY`, first in the sorted
    order the list already uses (RUF022), and nothing else."""
    assert page_prompt.__all__ == [
        "ART_KEY",
        "GLOSSARY_KEY",
        "GLOSSARY_SCHEMA",
        "MAX_IMAGE_LONG_EDGE_PX",
        "SYSTEM_PROMPT",
        "context_text",
        "prepare_page_image",
        "response_schema",
        "user_text",
    ]


@pytest.mark.parametrize("region_count", [0, 1, 3, 20])
def test_the_response_schema_names_every_region_and_nothing_else_and_requires_none(
    region_count: int,
) -> None:
    """MT-079 AC-2 as amended by MT-106 AC-1. Exactly `"0".."n-1"` and **no
    `glossary` property** (MT-106: a page proposes no terms, and
    `additionalProperties: False` forbids the key); **no `required` key** (an
    omitted region is legal, MT-011 AC-5); `additionalProperties: False` (an
    unknown index is the model disobeying, not the schema inviting it). 20 is
    past single digits, so a schema built from characters rather than numbers
    is caught; 0 is a page the detector found nothing on. MT-147 C-2: plus
    `art_text` for a page with a region, and nothing for a page with none."""
    schema = page_prompt.response_schema(region_count)

    assert "glossary" not in schema["properties"], (
        "a page's response schema still offers a glossary array; after MT-106 a"
        " page proposes no terms and the key must be forbidden"
    )
    assert schema == _expected_schema(region_count)
    assert "required" not in schema, "AC-5 of MT-011 turns on no region being required"
    assert schema["additionalProperties"] is False


def test_a_page_with_no_regions_has_an_empty_properties_mapping() -> None:
    """MT-106 AC-1's zero: no region, no glossary, nothing at all."""
    assert page_prompt.response_schema(0)["properties"] == {}


@pytest.mark.parametrize("region_count", [1, 3, 20])
def test_each_region_is_an_object_requiring_its_echoed_japanese_and_its_english(
    region_count: int,
) -> None:
    """MT-149 AC-1, structurally - the reading a failure should give, beside the
    literal equality above: every index property is an object whose required
    fields are exactly the strings `ja` and `en`, with `additionalProperties:
    False`, and the index properties themselves are still not required."""
    schema = page_prompt.response_schema(region_count)

    for key in (str(index) for index in range(region_count)):
        entry = schema["properties"][key]
        assert entry["type"] == "object", f"region {key} is a {entry['type']}, not an object"
        assert sorted(entry["required"]) == ["en", "ja"], f"region {key}: {entry['required']}"
        assert set(entry["properties"]) == {"ja", "en"}, f"region {key}: {entry['properties']}"
        assert entry["properties"]["ja"]["type"] == "string"
        assert entry["properties"]["en"]["type"] == "string"
        assert entry["additionalProperties"] is False
    assert "required" not in schema


# -- MT-147 AC-1: the art_text key ---------------------------------------------


def test_the_art_key_is_art_text_and_lives_in_page_prompt() -> None:
    """MT-147 C-1: `ART_KEY` sits beside `GLOSSARY_KEY`, its value the literal
    the schema and the prompt both name. It can never collide with a reading
    index, which is always digits."""
    assert page_prompt.ART_KEY == "art_text"  # type: ignore[attr-defined]


@pytest.mark.parametrize("region_count", [1, 3, 20])
def test_the_schema_offers_art_text_as_integers_restricted_to_the_pages_indices(
    region_count: int,
) -> None:
    """MT-147 AC-1 and C-2: for `n >= 1` a property `art_text`, an array whose
    items are integers restricted by an `enum` to `0..n-1` - not by `minimum`
    and `maximum`, which Claude's structured outputs do not support, and with
    no `uniqueItems` (PO-1). 20 is past single digits."""
    schema = page_prompt.response_schema(region_count)

    assert "art_text" in schema["properties"], (
        f"response_schema({region_count}) has no art_text property (MT-147 AC-1)"
    )
    assert schema["properties"]["art_text"] == _art_property(region_count)
    items = schema["properties"]["art_text"]["items"]
    assert items["enum"] == list(range(region_count))
    assert "minimum" not in items
    assert "maximum" not in items
    assert "uniqueItems" not in schema["properties"]["art_text"]


@pytest.mark.parametrize("region_count", [1, 3])
def test_art_text_is_not_required_and_unknown_keys_are_still_refused(region_count: int) -> None:
    """MT-147 AC-1: `art_text` is optional - a page with no art omits it - and
    `additionalProperties` is still `False`. The index properties are
    untouched."""
    schema = page_prompt.response_schema(region_count)

    assert "art_text" in schema["properties"]
    assert "required" not in schema
    assert schema["additionalProperties"] is False
    for index in range(region_count):
        assert schema["properties"][str(index)] == _region_property(index)


def test_a_page_with_no_regions_offers_no_art_text_either() -> None:
    """MT-147 AC-1 and C-2: `response_schema(0)` has no properties - an `enum`
    of no values is not a valid schema, and no call is made for such a page."""
    assert page_prompt.response_schema(0) == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def test_the_prompt_gains_the_art_bullet_once_and_no_other_character() -> None:
    """MT-147 C-2, the golden's precondition: the answer bullets occur once in
    MT-149's text, so the insertion that derives the golden adds the art bullet
    right after the `en` bullet and before the blank line above `Continuity
    across pages:`, and changes nothing else."""
    assert _SYSTEM_PROMPT_PRE_MT147.count(_ANSWER_MT149) == 1
    head, tail = _SYSTEM_PROMPT_PRE_MT147.split(_ANSWER_MT149)
    assert tail.startswith("\nContinuity across pages:")
    assert head + _ANSWER_MT149 + _ART_BULLET_MT147 + tail == _SYSTEM_PROMPT_GOLDEN
    assert page_prompt.SYSTEM_PROMPT.count(_ART_BULLET_MT147) == 1, (
        "SYSTEM_PROMPT does not carry MT-147's art bullet exactly once"
    )


def test_the_prompt_tells_the_model_to_list_drawn_text_under_art_text_with_no_translation() -> None:
    """MT-147 AC-1: the model lists there any region whose text is drawn into
    the artwork - sound effects, signs, labels on objects - and gives it no
    translation. The needle is the instruction itself, anchored at its
    imperative: a prompt telling the model to translate such a region does not
    contain it."""
    assert (
        "text drawn into the artwork itself: sound effects, signs, labels on objects."
        ' List the reading index of each such region under the "art_text" key and give'
        " that region no entry and no translation." in page_prompt.SYSTEM_PROMPT
    ), "SYSTEM_PROMPT does not tell the model to list drawn text under art_text untranslated"


def test_the_prompt_says_dialogue_narration_and_captions_are_never_art_text() -> None:
    """MT-147 AC-1's last clause: the one guard against a balloon wrongly
    excluded, which DV-2 measures as the number that matters."""
    assert (
        "Dialogue, narration and captions are never art text, however they are lettered."
        in page_prompt.SYSTEM_PROMPT
    ), "SYSTEM_PROMPT does not say dialogue, narration and captions are never art text"


# -- AC-5: no SDK --------------------------------------------------------------

#: The SDK roots EPIC-08's providers ship as; `google` covers `google.genai`.
_SDK_ROOTS = ("anthropic", "openai", "google")


def _loaded_after_import(module: str) -> tuple[list[str], bool, str]:
    """Import `module` in a fresh interpreter; report which SDK roots and
    whether `mangatl.translate.parse` ended up in `sys.modules`."""
    probe = (
        "import sys\n"
        f"import {module}\n"
        f"roots = {_SDK_ROOTS!r}\n"
        "print(sorted({m.split('.')[0] for m in sys.modules} & set(roots)))\n"
        "print('mangatl.translate.parse' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, (
        f"importing {module} failed in a fresh interpreter: {result.stderr}"
    )
    roots_line, parse_line = result.stdout.strip().splitlines()
    return ast.literal_eval(roots_line), parse_line == "True", result.stdout


def test_importing_page_prompt_loads_no_sdk_and_not_parse() -> None:
    """AC-5, observed in a fresh interpreter rather than read off the source:
    an SDK pulled in transitively (through `parse`, which imports
    `anthropic.types.Message`) is exactly what the amendment to C-1 exists to
    prevent, and only `sys.modules` sees it."""
    roots, parse_loaded, raw = _loaded_after_import("mangatl.translate.page_prompt")

    assert roots == [], f"importing page_prompt loaded {roots}; AC-5 says it loads no SDK"
    assert parse_loaded is False, (
        f"importing page_prompt loaded mangatl.translate.parse ({raw!r}); C-1's amendment"
        " says page_prompt imports nothing from parse"
    )


def test_control_the_probe_sees_anthropic_through_parse() -> None:
    """The negative control: the same probe over `parse`, which does import
    the SDK. A probe that printed `[]` for everything would keep AC-5 green
    forever."""
    roots, parse_loaded, _ = _loaded_after_import("mangatl.translate.parse")

    assert roots == ["anthropic"]
    assert parse_loaded is True
