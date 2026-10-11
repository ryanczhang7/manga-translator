"""`mangatl.translate.page_prompt`: the request's five parts, provider-neutral.

MT-079. Covers **AC-1** (the golden: Claude's request is byte-for-byte what it
was), **AC-2** (the response schema) and **AC-5** (the module loads no SDK). The
parse half of the story, AC-3 and AC-4, is in `test_translate_parse.py`.

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
_SYSTEM_PROMPT_GOLDEN = """You translate Japanese manga into natural English.

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
page for who is speaking and what is being continued.
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


def _region_property(index: int) -> dict[str, str]:
    """One region's schema property exactly as the pre-story inline schema
    wrote it - `description` included, which is part of what Claude is sent."""
    return {
        "type": "string",
        "description": f"The English for the region at reading index {index}.",
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
                "schema": page_prompt.response_schema(len(ocr_results)),
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
        "page_prompt.SYSTEM_PROMPT is not the pre-story system prompt; MT-079 moves"
        " the text and must not change one character of it"
    )


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
        "build_request no longer returns the pre-story kwargs built from page_prompt's parts"
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


@pytest.mark.parametrize("region_count", [0, 1, 3, 20])
def test_the_response_schema_names_every_region_and_the_glossary_and_requires_none(
    region_count: int,
) -> None:
    """AC-2. Exactly `"0".."n-1"` plus `glossary`; **no `required` key** (an
    omitted region is legal, MT-011 AC-5); `additionalProperties: False` (an
    unknown index is the model disobeying, not the schema inviting it). 20 is
    past single digits, so a schema built from characters rather than numbers
    is caught; 0 is a page the detector found nothing on."""
    schema = page_prompt.response_schema(region_count)

    expected_properties: dict[str, Any] = {
        str(index): _region_property(index) for index in range(region_count)
    }
    expected_properties["glossary"] = _GLOSSARY_SCHEMA_GOLDEN
    assert schema == {
        "type": "object",
        "properties": expected_properties,
        "additionalProperties": False,
    }
    assert "required" not in schema, "AC-5 of MT-011 turns on no region being required"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["glossary"] == page_prompt.GLOSSARY_SCHEMA


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
