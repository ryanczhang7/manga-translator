"""Which proposed line belongs to which bubble.

MT-011 C-4, and the whole of AC-4 and AC-6. Three things here are silent if they
are got wrong, which is why each is pinned by its own test:

1. **The JSON comes out of the first `text` content block, not out of
   `content[0]`** (C-4's RED amendment). `output_config.format` guarantees a
   text block carrying valid JSON, and C-5 pins `thinking={"type": "adaptive"}`
   - so a real response may carry a `thinking` block first, and a thinking block
   has `.thinking` and no `.text`. `response.content[0].text` works against
   every hand-made fixture that has only a text block and fails against
   production.
2. **JSON object keys are strings and region ids are ints.** A parser that left
   them as strings returns a dict every `int`-keyed lookup misses, so every
   region reads as untranslated and the page looks exactly like one the model
   declined to translate.
3. **Lines are assigned by region index, never by position in the response.**
   The model may answer in any order, and zipping its values onto the region
   list puts the right words on the wrong bubbles - the failure `stack.md`
   §5/O2 calls the one that matters most. `fixtures/translate/well-formed.json`
   is deliberately keyed `2, 0, 3, 1` so that the two parsings disagree on all
   four regions.

**Validation is this function's own, independent of the response schema.** The
schema in `output_config.format` is the server's job and a fixture can say
anything; an index outside the page raises `UnknownRegionIndex` **naming it**,
because a user told only that a page failed has nothing to look at.

`UnknownRegionIndex` derives from `Exception` **directly** and that is
load-bearing: a non-integer key must raise it rather than letting a `ValueError`
escape from `int()`, and if the type were a `ValueError` subclass no test could
tell those two apart.

A body that is not JSON at all - Opus 5 can return HTTP 200 with
`stop_reason: "refusal"` and no usable content - raises out of `json.loads`.
That is loud rather than silent, which is this story's accepted answer; handling
a refusal properly means a fallback or a retry path and `architecture.md` D5
puts a second pass over the budget. See MT-011 `## Out of scope`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from anthropic.types import Message

from mangatl.domain.glossary import ProposedTerm

__all__ = ["GLOSSARY_KEY", "UnknownRegionIndex", "parse_lines", "parse_terms"]

#: The one response key that is not a reading index (MT-014 C-3/C-4). It can
#: never collide with one: a reading index is always digits.
GLOSSARY_KEY: str = "glossary"

_TERM_FIELDS = ("term_ja", "term_en", "note")


class UnknownRegionIndex(Exception):
    """The response named a region this page does not have.

    Straight off `Exception`, not off `ValueError` - see the module docstring.
    """


def parse_lines(response: Message, region_indices: Sequence[int]) -> dict[int, str]:
    """The page's proposed English, keyed by reading index.

    Sparse: a region the model omitted is simply absent, which is AC-5's
    untranslated region and is what `Project.write_proposed` leaves NULL. The
    page is not discarded for it.

    Raises `UnknownRegionIndex`, naming the key, for anything outside
    `region_indices` - including a key that is not an integer, and including a
    negative one, which a check written as an index into the sequence would
    silently file under the last bubble on the page.
    """
    known = set(region_indices)

    lines: dict[int, str] = {}
    for key, english in _body(response).items():
        # MT-014 C-4: exactly this key and no other - a case-folded or prefix
        # match would silently turn a malformed key into a dropped one.
        if key == GLOSSARY_KEY:
            continue
        try:
            reading_index = int(key)
        except ValueError:
            raise _unknown(key, known) from None
        if reading_index not in known:
            raise _unknown(reading_index, known)
        lines[reading_index] = english
    return lines


def parse_terms(response: Message) -> tuple[ProposedTerm, ...]:
    """The glossary terms the response proposed, in the order it gave them.

    `()` when the response has no `glossary` key. **An item that is not an
    object, or lacks one of the three string fields, is skipped rather than
    raised** (MT-014 C-4): the glossary is advisory, and losing a page's lines -
    which cost real money - over a malformed glossary item would be the wrong
    trade. The neighbours of a bad item are kept.
    """
    items = _body(response).get(GLOSSARY_KEY, [])
    return tuple(
        ProposedTerm(item["term_ja"], item["term_en"], item["note"])
        for item in items
        if isinstance(item, dict) and all(isinstance(item.get(f), str) for f in _TERM_FIELDS)
    )


def _body(response: Message) -> dict[str, Any]:
    """The JSON object in the response's first `text` block - not `content[0]`,
    which may be a `thinking` block (see the module docstring, point 1)."""
    text = next(block.text for block in response.content if block.type == "text")
    body: dict[str, Any] = json.loads(text)
    return body


def _unknown(key: object, known: set[int]) -> UnknownRegionIndex:
    return UnknownRegionIndex(
        f"the response names region {key!r}, which this page does not have;"
        f" its reading indices are {sorted(known)}"
    )
