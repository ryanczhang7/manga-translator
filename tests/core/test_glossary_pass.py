"""`mangatl.translate.glossary_pass`: what the glossary pre-pass asks, and how
its answer is read.

MT-104. Covers **AC-1** (the listing), **AC-2** (the schema and the parse) and
the pure half of **AC-4** (the limit, the exception and the boundary fixtures
`test_gemini_glossary_pass.py` sends). AC-3 and AC-4 through the adapter are in
`test_gemini_glossary_pass.py`.

**Oracle partition: entirely mechanical** (the story's `## Contract`). Every
number is read out of the contract, never re-derived: the limit 180,000 is
MT-101 D-12 as cited in PO-1, the output cap 8,192 is the contract's, and the
listing's exact bytes are the Contract's "Semantics" paragraph as amended in
RED (header `Page {n}:` with `n = index + 1`, lines verbatim one per line,
pages separated by one blank line, a page with no readable line dropped header
and all, no preamble, no trailing newline).

**The module is imported per test, not at the top** (the `gemini` fixture
pattern in `test_translate_gemini.py`): in RED it does not exist, and a
top-level import is a COLLECTION error that interrupts the whole
`pytest tests/core tests/ui` session. Imported in a fixture, each test here
fails on the named absence and the rest of the suite still runs.

**Timing.** No per-test timeout in this project. The largest fixture is a
~540 kB ASCII line built once per test; `glossary_pass_text` over it is linear.
The SDK-free check spawns one interpreter (about a second).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from types import ModuleType

import pytest

from mangatl.domain.glossary import ProposedTerm, estimate_tokens
from mangatl.domain.line import OcrResult
from mangatl.translate import page_prompt
from mangatl.translate.parse import parse_terms_text


@pytest.fixture
def gp() -> ModuleType:
    """`mangatl.translate.glossary_pass`, imported per test (see the docstring)."""
    from mangatl.translate import glossary_pass as module

    return module


def _read(text: str) -> OcrResult:
    return OcrResult(text=text)


#: An `ocr_empty` region: the model emitted nothing (`domain.line`).
_EMPTY = OcrResult(text="", ocr_empty=True)

#: Three pages of Japanese, each with an `ocr_empty` region in a different
#: position (middle, none, first), so dropping by position cannot pass.
_PAGES: tuple[tuple[OcrResult, ...], ...] = (
    (_read("さくら先輩!"), _EMPTY, _read("待って、さくら!")),
    (_read("東京駅で会おう"),),
    (_EMPTY, _read("行くぞ、田中くん"), _read("……なるほど")),
)

#: The exact bytes AC-1 and the amended Contract pin for `_PAGES`.
_PAGES_TEXT = (
    "Page 1:\nさくら先輩!\n待って、さくら!"
    "\n\n"
    "Page 2:\n東京駅で会おう"
    "\n\n"
    "Page 3:\n行くぞ、田中くん\n……なるほど"
)


# -- AC-1: the listing ----------------------------------------------------------


def test_three_pages_render_every_line_once_under_one_based_page_headers_in_order(
    gp: ModuleType,
) -> None:
    """AC-1: every readable line once, in page then reading order, under
    `Page {index + 1}:`, the `ocr_empty` regions left out - byte for byte."""
    assert gp.glossary_pass_text(_PAGES) == _PAGES_TEXT


def test_the_listing_contains_no_ocr_empty_placeholder_and_no_preamble(gp: ModuleType) -> None:
    """AC-1's exclusion, stated on its own so its failure names it: no empty
    line inside a page's block (an `ocr_empty` region listed as `""` would
    leave one) and nothing before the first header."""
    text = gp.glossary_pass_text(_PAGES)

    assert text.startswith("Page 1:\n"), repr(text[:40])
    for block in text.split("\n\n"):
        assert "" not in block.split("\n"), f"an empty line inside a page block: {block!r}"


def test_the_first_page_is_page_1_not_page_0(gp: ModuleType) -> None:
    """The Contract's `n = index + 1`: a 0-based header misnumbers every page
    the model's notes could cite."""
    text = gp.glossary_pass_text([[_read("一")]])

    assert text == "Page 1:\n一"


def test_two_calls_with_the_same_pages_are_byte_identical(gp: ModuleType) -> None:
    """AC-1's determinism, against a separately built equal input too - so an
    output that depended on object identity or a set's order would differ."""
    rebuilt = tuple(tuple(OcrResult(r.text, r.ocr_empty) for r in page) for page in _PAGES)

    first = gp.glossary_pass_text(_PAGES)
    second = gp.glossary_pass_text(_PAGES)
    third = gp.glossary_pass_text(rebuilt)

    assert first.encode("utf-8") == second.encode("utf-8") == third.encode("utf-8")


def test_a_page_whose_every_line_is_ocr_empty_is_dropped_and_later_pages_keep_their_number(
    gp: ModuleType,
) -> None:
    """AC-1's control, decided in RED (Contract amendment): an all-`ocr_empty`
    page - a page of art - contributes **nothing**, header included. The page
    after it is still `Page 3:` because `n` is the page's index, not a count
    of rendered pages: a counter would print `Page 2:` and point the model's
    page references at the wrong page."""
    pages = (_PAGES[0], (_EMPTY, _EMPTY), _PAGES[2])

    assert gp.glossary_pass_text(pages) == (
        "Page 1:\nさくら先輩!\n待って、さくら!\n\nPage 3:\n行くぞ、田中くん\n……なるほど"
    )


def test_a_page_with_no_regions_at_all_is_dropped_too(gp: ModuleType) -> None:
    """The zero-region page is the same case as the all-empty one."""
    assert gp.glossary_pass_text([(), [_read("二")]]) == "Page 2:\n二"


@pytest.mark.parametrize(
    "pages",
    [(), ((),), ((_EMPTY,), (_EMPTY, _EMPTY))],
    ids=["no-pages", "one-empty-page", "only-art"],
)
def test_a_volume_with_no_readable_line_renders_as_the_empty_string(
    gp: ModuleType, pages: Sequence[Sequence[OcrResult]]
) -> None:
    """The edge the drop decision implies: no readable line anywhere, no text."""
    assert gp.glossary_pass_text(pages) == ""


def test_a_line_is_rendered_verbatim(gp: ModuleType) -> None:
    """The Contract's "lines are `text` verbatim": no strip, no normalisation."""
    line = "  ｻｸﾗ  先輩　"
    assert gp.glossary_pass_text([[_read(line)]]) == f"Page 1:\n{line}"


# -- AC-2: the schema -------------------------------------------------------------


def test_the_pass_schema_is_an_object_requiring_only_a_glossary_array(gp: ModuleType) -> None:
    """AC-2, top level: `glossary` is the one property, it is required, and
    nothing else is allowed."""
    schema = gp.GLOSSARY_PASS_SCHEMA

    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"glossary"}
    assert schema["required"] == ["glossary"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["glossary"]["type"] == "array"


def test_the_pass_schemas_items_are_exactly_the_page_glossary_items(gp: ModuleType) -> None:
    """AC-2, item level: the same fragment as the per-page `GLOSSARY_SCHEMA`
    (so MT-105's merge sees nothing new) - three required strings, nothing
    else allowed."""
    items = gp.GLOSSARY_PASS_SCHEMA["properties"]["glossary"]["items"]

    assert items == page_prompt.GLOSSARY_SCHEMA["items"]
    assert set(items["required"]) == {"term_ja", "term_en", "note"}
    assert set(items["properties"]) == {"term_ja", "term_en", "note"}
    assert items["additionalProperties"] is False


# -- AC-2: the parse --------------------------------------------------------------

_TERMS_BODY = (
    '{"glossary": ['
    '{"term_ja": "田中", "term_en": "Tanaka", "note": "name"},'
    '{"term_ja": "東京駅", "term_en": "Tokyo Station", "note": "place"},'
    '{"term_ja": "先輩", "term_en": "senpai", "note": "honorific"}]}'
)


def test_a_conforming_body_parses_to_proposed_terms_in_response_order(gp: ModuleType) -> None:
    """AC-2: `ProposedTerm`s, in the order given (not sorted: 田中 < 東京駅 <
    先輩 is not any sort order of either side)."""
    terms = gp.parse_glossary_pass(_TERMS_BODY)

    assert terms == (
        ProposedTerm("田中", "Tanaka", "name"),
        ProposedTerm("東京駅", "Tokyo Station", "place"),
        ProposedTerm("先輩", "senpai", "honorific"),
    )
    assert type(terms) is tuple
    assert all(type(term) is ProposedTerm for term in terms)
    assert terms == parse_terms_text(_TERMS_BODY)


def test_a_body_without_the_glossary_key_raises_value_error_naming_the_key(
    gp: ModuleType,
) -> None:
    """AC-2: a required key missing is the model disobeying the schema, and
    unlike a page's optional glossary it is not "no terms" - it raises, and
    the message names `glossary`."""
    with pytest.raises(ValueError, match=r"\bglossary\b"):
        gp.parse_glossary_pass('{"terms": []}')


def test_an_empty_glossary_is_no_terms_and_not_an_error(gp: ModuleType) -> None:
    """The control for the test above: the key present and empty is a legal
    answer (a volume with no recurring names), so the raise is about the key,
    not about having nothing."""
    assert gp.parse_glossary_pass('{"glossary": []}') == ()


# -- the constants and the prompt -------------------------------------------------


def test_the_input_limit_is_180000_tokens_from_mt_101_d_12(gp: ModuleType) -> None:
    """PO-1: 200k tier measured on the prompt, 20k headroom for the system
    instruction. Read out, not re-derived."""
    assert gp.GLOSSARY_PASS_MAX_INPUT_TOKENS == 180_000


def test_the_output_cap_is_8192_tokens(gp: ModuleType) -> None:
    assert gp.GLOSSARY_PASS_MAX_OUTPUT_TOKENS == 8_192


def test_the_prompt_fits_the_headroom_the_input_limit_leaves_under_the_200k_tier(
    gp: ModuleType,
) -> None:
    """PO-1's arithmetic as a guard: listing at the limit plus the system
    instruction must stay at or under the 200,000-token tier. A prompt that
    grew past 20,000 estimated tokens would silently price a full volume at a
    tier the table has no row for."""
    prompt = gp.GLOSSARY_PASS_PROMPT

    assert isinstance(prompt, str) and prompt.strip()
    assert estimate_tokens(prompt) + gp.GLOSSARY_PASS_MAX_INPUT_TOKENS <= 200_000


def test_the_pass_prompt_is_not_the_page_translation_prompt(gp: ModuleType) -> None:
    """The Contract: the pass asks for terms, "no translation of lines". The
    page's `SYSTEM_PROMPT` asks for exactly that translation."""
    assert gp.GLOSSARY_PASS_PROMPT != page_prompt.SYSTEM_PROMPT


def test_importing_the_pass_module_does_not_load_the_gemini_sdk() -> None:
    """The Contract's "SDK-free": `tests/core` tests these functions without a
    client, as `page_prompt` is split from `gemini`. A fresh interpreter,
    because this session has already imported `google.genai` elsewhere."""
    probe = (
        "import sys, mangatl.translate.glossary_pass;"
        " print(sorted(m for m in sys.modules if m == 'google.genai'"
        " or m.startswith('google.genai.')))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60, check=False
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", done.stdout


# -- AC-4, the pure half: the exception and the boundary fixtures ----------------

#: `"Page 1:\n"` is 8 UTF-8 bytes. `estimate_tokens` is `ceil(bytes / 3)`, so a
#: one-line volume of 540,000 bytes estimates to exactly 180,000 and one more
#: byte to 180,001. The ASCII filler makes the byte count exact by construction.
_HEADER_BYTES = len(b"Page 1:\n")


def _at_limit_pages(limit: int) -> tuple[tuple[OcrResult, ...], ...]:
    """One page, one line, rendering to exactly `limit` estimated tokens."""
    return ((_read("a" * (3 * limit - _HEADER_BYTES)),),)


def _over_limit_pages(limit: int) -> tuple[tuple[OcrResult, ...], ...]:
    """The same plus one byte: `limit + 1` estimated tokens."""
    return ((_read("a" * (3 * limit - _HEADER_BYTES + 1)),),)


def test_the_boundary_fixtures_estimate_to_exactly_the_limit_and_one_over(gp: ModuleType) -> None:
    """The fixtures AC-4's adapter tests send, checked against the exact
    listing they render to - so the boundary those tests pin is the one
    claimed, not one a byte away."""
    limit = gp.GLOSSARY_PASS_MAX_INPUT_TOKENS
    at, over = _at_limit_pages(limit), _over_limit_pages(limit)

    assert gp.glossary_pass_text(at) == "Page 1:\n" + at[0][0].text
    assert gp.glossary_pass_text(over) == "Page 1:\n" + over[0][0].text
    assert estimate_tokens(gp.glossary_pass_text(at)) == limit == 180_000
    assert estimate_tokens(gp.glossary_pass_text(over)) == limit + 1


def test_volume_too_large_is_an_exception_the_module_exports(gp: ModuleType) -> None:
    """AC-4's type: an `Exception`, and not one of the parse's `ValueError`s -
    a caller refusing a volume must not catch it as a malformed answer."""
    assert issubclass(gp.VolumeTooLarge, Exception)
    assert not issubclass(gp.VolumeTooLarge, ValueError)
