"""`mangatl.translate.parse.parse_terms`: what one response proposes for the
glossary (MT-014 C-4).

The glossary is **advisory**. A malformed item is skipped, never raised: losing
a page's lines - which cost real money and are what the user reviews - over a
malformed glossary item would be the wrong trade (C-4). So every "bad item"
case here asserts that the good items around it survive, not merely that
nothing raised.

The response is `conftest.fake_message`, the same stand-in MT-011's parse tests
use; no network, no client.

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so
there is no budget in this file to size. Nothing here touches a disk.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from mangatl.domain.glossary import ProposedTerm
from mangatl.translate.parse import parse_terms

_SAKURA = '{"term_ja": "さくら", "term_en": "Sakura", "note": "name"}'
_SENPAI = '{"term_ja": "先輩", "term_en": "senpai", "note": "honorific"}'


def test_a_response_with_no_glossary_key_proposes_nothing(
    fake_message: Callable[..., object],
) -> None:
    """C-4: `()` when absent - every MT-011 recorded body is this case."""
    assert parse_terms(fake_message('{"0": "Sakura!"}')) == ()


def test_an_empty_glossary_proposes_nothing(fake_message: Callable[..., object]) -> None:
    assert parse_terms(fake_message('{"glossary": []}')) == ()


def test_the_proposed_terms_come_back_in_the_order_the_response_gave_them(
    fake_message: Callable[..., object],
) -> None:
    """C-4's "the `glossary` array in order". Order matters downstream: `merge`
    lets the **first** of two proposals for one `term_ja` win (C-1), so a parser
    that re-sorted would change which rendering a chapter keeps."""
    body = '{"1": "Senpai!", "glossary": [' + _SENPAI + ", " + _SAKURA + "]}"

    terms = parse_terms(fake_message(body))

    assert terms == (
        ProposedTerm(term_ja="先輩", term_en="senpai", note="honorific"),
        ProposedTerm(term_ja="さくら", term_en="Sakura", note="name"),
    )
    assert type(terms) is tuple


def test_an_empty_note_is_a_legal_note(fake_message: Callable[..., object]) -> None:
    """C-3's enum includes `""` - a term that is neither a name, an honorific
    nor a place - so it is a present string field and the item is kept."""
    body = '{"glossary": [{"term_ja": "醜鬼", "term_en": "Ugly Ogre", "note": ""}]}'

    assert parse_terms(fake_message(body)) == (ProposedTerm("醜鬼", "Ugly Ogre", ""),)


def test_a_thinking_block_in_front_of_the_json_does_not_hide_the_glossary(
    fake_message: Callable[..., object],
) -> None:
    """MT-011 C-4's RED amendment, again: adaptive thinking may put a
    `thinking` block (no `.text`) first, and `content[0].text` fails on it."""
    message = fake_message('{"glossary": [' + _SAKURA + "]}", leading_thinking=True)

    assert parse_terms(message) == (ProposedTerm("さくら", "Sakura", "name"),)


@pytest.mark.parametrize(
    "bad_item",
    [
        pytest.param('"さくら = Sakura"', id="a-string"),
        pytest.param("42", id="a-number"),
        pytest.param("null", id="null"),
        pytest.param('["さくら", "Sakura", "name"]', id="a-list"),
        pytest.param('{"term_en": "Kenji", "note": "name"}', id="no-term_ja"),
        pytest.param('{"term_ja": "けんじ", "note": "name"}', id="no-term_en"),
        pytest.param('{"term_ja": "けんじ", "term_en": "Kenji"}', id="no-note"),
        pytest.param('{"term_ja": "けんじ", "term_en": 7, "note": "name"}', id="term_en-not-str"),
        pytest.param('{"term_ja": 7, "term_en": "Kenji", "note": "name"}', id="term_ja-not-str"),
        pytest.param('{"term_ja": "けんじ", "term_en": "Kenji", "note": null}', id="note-null"),
    ],
)
def test_a_malformed_item_is_skipped_and_the_good_items_around_it_survive(
    fake_message: Callable[..., object], bad_item: str
) -> None:
    """C-4: "an item that is not an object, or lacks one of the three string
    fields, is **skipped**, not raised". The good items sit on **both** sides of
    the bad one, so a parser that stopped at the first bad item - `break`
    rather than `continue` - is caught as well as one that raised."""
    body = '{"0": "Sakura!", "glossary": [' + _SAKURA + ", " + bad_item + ", " + _SENPAI + "]}"

    assert parse_terms(fake_message(body)) == (
        ProposedTerm("さくら", "Sakura", "name"),
        ProposedTerm("先輩", "senpai", "honorific"),
    )
