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
because a user told only that a page failed has nothing to look at. An entry
under a valid index that is not a `{ja, en}` object of two strings is parsed to
`None` rather than raised (MT-149 PO-4): the page's answer is
`dict[int, AnswerEntry | None]`, and `domain.echo.checked_lines` reports a
`None` entry as misaligned, so the page is written and its call recorded.

`UnknownRegionIndex` derives from `Exception` **directly** and that is
load-bearing: a non-integer key must raise it rather than letting a `ValueError`
escape from `int()`, and if the type were a `ValueError` subclass no test could
tell those two apart.

A body that is not JSON at all - Opus 5 can return HTTP 200 with
`stop_reason: "refusal"` and no usable content - raises out of `json.loads`.
That is loud rather than silent, which is this story's accepted answer; handling
a refusal properly means a fallback or a retry path and `architecture.md` D5
puts a second pass over the budget. See MT-011 `## Out of scope`.

**The split at the text** (MT-079 C-3). `parse_lines_text` and
`parse_terms_text` take the JSON text itself and are the entry points every
provider shares; `parse_lines` and `parse_terms` keep their `Message`
signatures and delegate through `first_text_block`, which is the only part of
this module that knows a Claude response's shape. `GLOSSARY_KEY` lives in
`page_prompt` (so that module never loads the SDK through this one) and is
re-exported here for every existing caller.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from anthropic.types import Message

from mangatl.domain.echo import AnswerEntry
from mangatl.domain.glossary import ProposedTerm
from mangatl.translate.page_prompt import GLOSSARY_KEY

__all__ = [
    "GLOSSARY_KEY",
    "UnknownRegionIndex",
    "first_text_block",
    "parse_lines",
    "parse_lines_text",
    "parse_terms",
    "parse_terms_text",
]

_TERM_FIELDS = ("term_ja", "term_en", "note")


class UnknownRegionIndex(Exception):
    """The response named a region this page does not have.

    Straight off `Exception`, not off `ValueError` - see the module docstring.
    """


def first_text_block(response: Message) -> str:
    """The text of the response's first `text` block - not `content[0]`, which
    may be a `thinking` block (see the module docstring, point 1).

    Raises `ValueError` naming the missing text block when there is none,
    rather than letting a bare `StopIteration` escape (MT-079 C-3 as amended).
    """
    for block in response.content:
        if block.type == "text":
            return block.text
    raise ValueError("the response has no text block to read the JSON answer from")


def parse_lines(response: Message, region_indices: Sequence[int]) -> dict[int, AnswerEntry | None]:
    """The page's answer entries, keyed by reading index (`None` for a
    malformed one): `parse_lines_text` over the response's first text block."""
    return parse_lines_text(first_text_block(response), region_indices)


def parse_terms(response: Message) -> tuple[ProposedTerm, ...]:
    """The glossary terms the response proposed: `parse_terms_text` over the
    response's first text block."""
    return parse_terms_text(first_text_block(response))


def parse_lines_text(text: str, region_indices: Sequence[int]) -> dict[int, AnswerEntry | None]:
    """The page's answer entries, keyed by reading index.

    Each entry is the `{ja, en}` object MT-149 asks for, carried byte for byte:
    the parser does not compare `ja` with the listing - that is
    `domain.echo.checked_lines`, which every adapter calls next.

    **A malformed entry is `None`, not an exception** (MT-149 PO-4): a value
    that is not an object with a string `ja` and a string `en` - an old-schema
    bare string, `null`, a list, a number, a missing or non-string field - is
    kept under its key as `None`, which `checked_lines` reports as misaligned.
    The page is still written and its call still billed. Extra fields on an
    otherwise valid entry are ignored. A body that is not a JSON object still
    raises.

    Sparse: a region the model omitted is simply absent, which is AC-5's
    untranslated region and is what `Project.write_proposed` leaves NULL. The
    page is not discarded for it.

    Raises `UnknownRegionIndex`, naming the key, for anything outside
    `region_indices` - including a key that is not an integer, and including a
    negative one, which a check written as an index into the sequence would
    silently file under the last bubble on the page. The key is checked before
    the value, so a bad key raises whatever its value is.
    """
    known = set(region_indices)

    lines: dict[int, AnswerEntry | None] = {}
    for key, entry in _body(text).items():
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
        lines[reading_index] = _entry(entry)
    return lines


def _entry(value: object) -> AnswerEntry | None:
    """`value` as an `AnswerEntry` when it is an object with string `ja` and
    string `en` (other fields ignored), otherwise `None` (MT-149 PO-4)."""
    if not isinstance(value, dict):
        return None
    ja, en = value.get("ja"), value.get("en")
    if isinstance(ja, str) and isinstance(en, str):
        return AnswerEntry(ja, en)
    return None


def parse_terms_text(text: str) -> tuple[ProposedTerm, ...]:
    """The glossary terms the response proposed, in the order it gave them.

    `()` when the response has no `glossary` key. **An item that is not an
    object, or lacks one of the three string fields, is skipped rather than
    raised** (MT-014 C-4): the glossary is advisory, and losing a page's lines -
    which cost real money - over a malformed glossary item would be the wrong
    trade. The neighbours of a bad item are kept.
    """
    items = _body(text).get(GLOSSARY_KEY, [])
    return tuple(
        ProposedTerm(item["term_ja"], item["term_en"], item["note"])
        for item in items
        if isinstance(item, dict) and all(isinstance(item.get(f), str) for f in _TERM_FIELDS)
    )


def _body(text: str) -> dict[str, Any]:
    """The JSON object the answer text carries."""
    body: dict[str, Any] = json.loads(text)
    return body


def _unknown(key: object, known: set[int]) -> UnknownRegionIndex:
    return UnknownRegionIndex(
        f"the response names region {key!r}, which this page does not have;"
        f" its reading indices are {sorted(known)}"
    )
