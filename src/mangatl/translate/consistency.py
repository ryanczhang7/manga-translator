"""The consistency pass: what it reads, how its answer is read, and how a volume
is cut into requests.

MT-114. EPIC-09 PO-6 runs one text-only pass over a volume's Japanese and
English, after every page is translated, and asks for **only the lines it would
change**, each with a reason - never the full text, because a full rewrite
costs more than the batch saved (EPIC-09 `## Why now`). This module is the
provider-neutral half - the prompt, the text, the schema, the parse and the
chunking - and `gemini.run_consistency` sends one chunk, as `glossary_pass` is
split from `gemini`. Applying the answer to the store is MT-115's.

**This module imports no SDK** (the Contract's "SDK-free"): importing it loads
nothing from `google.genai`.

**Numbering.** The text and the response speak 1-based `page` (`Page {n}`,
`n = ordinal + 1`, a gap rather than a renumbering when a page is dropped - the
MT-104 rule); the domain speaks the store's 0-based `page_ordinal`.
`parse_corrections` converts with `page - 1`, and `current` is keyed by the
0-based `(page_ordinal, reading_index)` so MT-115 builds it from the store.

**A malformed item raises** (PO-1), where `parse_terms_text` skips a malformed
term (MT-014 C-4): a correction overwrites a proposal the user has not touched,
so half-reading an answer the schema already forbids and applying the rest
would apply corrections from a response the model mis-shaped. Refusing the
chunk costs one re-run.

**The limit** (MT-101 D-12): the 200k pricing tier is measured on the whole
prompt, so each chunk's text is held to 180,000 estimated tokens and the system
instruction has the remaining 20,000, as MT-104. `chunk_pages` cuts a volume
greedily at page boundaries; a page too large for a chunk of its own is refused
by name - `PageTooLarge`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

# `PageLines` lives in `domain.correction` since MT-115 and is re-exported here.
from mangatl.domain.correction import PageLines, ParsedCorrections, ProposedCorrection
from mangatl.domain.glossary import estimate_tokens

__all__ = [
    "CONSISTENCY_MAX_INPUT_TOKENS",
    "CONSISTENCY_MAX_OUTPUT_TOKENS",
    "CONSISTENCY_PROMPT",
    "CORRECTIONS_KEY",
    "CORRECTIONS_SCHEMA",
    "PageLines",
    "PageTooLarge",
    "UnknownLine",
    "chunk_pages",
    "consistency_text",
    "parse_corrections",
]

#: MT-101 D-12: 200k measured on the prompt; 20k headroom for the system
#: instruction, as MT-104.
CONSISTENCY_MAX_INPUT_TOKENS: int = 180_000

#: Corrections only, so an answer is far shorter than the text; the glossary
#: pass's cap. Includes thinking tokens on Gemini, as the page cap does.
CONSISTENCY_MAX_OUTPUT_TOKENS: int = 8_192

#: The answer's one key.
CORRECTIONS_KEY = "corrections"

#: One working prompt; tuning it is a later measurement, not this story's.
CONSISTENCY_PROMPT = """You check the English translation of a volume of \
Japanese manga for consistency.

You are given the volume's glossary, then its pages, each under a "Page N:" \
header. Each line is shown as "[i] Japanese" followed by its current English, \
indented, where i is the line's reading index on that page.

Find lines whose English is inconsistent with the glossary or with the rest of \
the volume: a name or honorific rendered differently, a recurring expression \
that changes, a character's voice or tone that shifts without reason, a line \
that contradicts another.

Return only the lines you would change. Never restate a line you keep. For \
each change give its page number N, its reading index i, the full corrected \
English for that one line, and a short reason. If nothing needs to change, \
answer with an empty "corrections" list."""

#: Every item is one changed line; nothing in the schema can hold a page.
CORRECTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        CORRECTIONS_KEY: {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer"},
                    "reading_index": {"type": "integer"},
                    "corrected_en": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["page", "reading_index", "corrected_en", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": [CORRECTIONS_KEY],
    "additionalProperties": False,
}


class UnknownLine(Exception):
    """A correction names a line the chunk did not show with English.

    Straight off `Exception`, not off `ValueError`: a refusal is not a
    malformed answer (MT-104's reason).
    """


class PageTooLarge(Exception):
    """One page's chunk estimates over the limit on its own.

    Straight off `Exception`, not off `ValueError`, as `UnknownLine`.
    """


def _page_block(page: PageLines) -> str:
    """`Page {ordinal + 1}:` and each English line, or `""` for a page with none."""
    rendered = [f"[{index}] {ja}\n    {en}" for index, ja, en in page.lines if en is not None]
    if not rendered:
        return ""
    return f"Page {page.ordinal + 1}:\n" + "\n".join(rendered)


def consistency_text(pages: Sequence[PageLines], glossary_block: str) -> str:
    """The glossary block, then each page's block, separated by one blank line.

    The separator appears only between two non-empty parts: an empty glossary
    puts the first page at byte 0, and with no page to render the text is the
    glossary alone. No preamble, no trailing newline. Pages and lines are in
    the order given; an English-less page is dropped header and all.
    """
    blocks = [block for block in (_page_block(page) for page in pages) if block]
    return "\n\n".join(([glossary_block] if glossary_block else []) + blocks)


def chunk_pages(
    pages: Sequence[PageLines],
    glossary_block: str,
    max_tokens: int = CONSISTENCY_MAX_INPUT_TOKENS,
) -> list[tuple[PageLines, ...]]:
    """Cut `pages` into contiguous chunks, each estimating at most `max_tokens`.

    Greedy: a chunk takes pages in order while its text - glossary included -
    still estimates `<= max_tokens` with the next page added; the first page
    that would push it over starts the next chunk. Raises `PageTooLarge` with
    the page's ordinal, its estimate and the limit when one page alone is over.
    """
    chunks: list[tuple[PageLines, ...]] = []
    current: list[PageLines] = []
    for page in pages:
        alone = estimate_tokens(consistency_text((page,), glossary_block))
        if alone > max_tokens:
            raise PageTooLarge(
                f"page ordinal {page.ordinal} estimates to {alone:,} tokens on its own,"
                f" over the consistency pass's limit of {max_tokens:,}"
            )
        if (
            current
            and estimate_tokens(consistency_text((*current, page), glossary_block)) > max_tokens
        ):
            chunks.append(tuple(current))
            current = []
        current.append(page)
    if current:
        chunks.append(tuple(current))
    return chunks


def _field(item: Mapping[str, Any], key: str, kind: type) -> Any:
    """`item[key]`, which must be exactly a `kind` (a JSON `true` is not an int)."""
    if key not in item:
        raise ValueError(f"a correction item has no {key!r}: {item!r}")
    value = item[key]
    if type(value) is not kind:
        raise ValueError(f"a correction item's {key!r} is not {kind.__name__}: {item!r}")
    return value


def parse_corrections(text: str, current: Mapping[tuple[int, int], str]) -> ParsedCorrections:
    """The lines the answer changes, in response order, on 0-based pages.

    `current` maps the store's `(page_ordinal, reading_index)` to the line's
    English. An item equal to it, exactly, is dropped and counted in
    `unchanged_returned`. Raises `UnknownLine` naming the response's `page` and
    `reading_index` for a line not in `current`, `ValueError` for an answer
    with no `corrections` key or a malformed item (PO-1), and lets a
    `json.loads` error propagate.
    """
    body = json.loads(text)
    if not isinstance(body, dict) or CORRECTIONS_KEY not in body:
        raise ValueError(f"the consistency pass answer has no {CORRECTIONS_KEY!r} key")
    items = body[CORRECTIONS_KEY]
    if not isinstance(items, list):
        raise ValueError(f"the consistency pass answer's {CORRECTIONS_KEY!r} is not a list")

    corrections: list[ProposedCorrection] = []
    unchanged = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"a correction item is not an object: {item!r}")
        page = _field(item, "page", int)
        reading_index = _field(item, "reading_index", int)
        corrected_en = _field(item, "corrected_en", str)
        reason = _field(item, "reason", str)
        key = (page - 1, reading_index)
        if key not in current:
            raise UnknownLine(
                f"the answer corrects page {page} line {reading_index}, which the chunk"
                " did not show with English"
            )
        if corrected_en == current[key]:
            unchanged += 1
            continue
        corrections.append(ProposedCorrection(key[0], reading_index, corrected_en, reason))
    return ParsedCorrections(corrections=tuple(corrections), unchanged_returned=unchanged)
