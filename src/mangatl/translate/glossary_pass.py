"""The glossary pre-pass: what is asked once per volume, and how it is read.

MT-104. EPIC-09 PO-2 proposes the glossary once, up front, from one text-only
call over every page's local-OCR Japanese. This module is the provider-neutral
half - the prompt, the listing, the schema, the parse and the limits - and
`gemini.propose_glossary` sends it, as `page_prompt` is split from `gemini`.

**This module imports no SDK** (the Contract's "SDK-free"): importing it loads
nothing from `google.genai`. It does import `parse`, and so the Anthropic SDK's
`Message` type - permitted, because `parse_terms_text` is the shared parse and
a second copy of its item handling would be a second thing to keep in step.

**The answer is the per-page glossary fragment, unchanged.** The items are
`page_prompt.GLOSSARY_SCHEMA`'s and parse to the same `ProposedTerm`s, so the
merge MT-105 runs them through sees nothing new. The one difference is that the
key is **required** here: a page may propose no terms by leaving the key out,
but the pass exists to propose them, so an answer without it is the model
disobeying the schema and raises.

**The limits** (PO-1, MT-101 D-12): the 200k pricing tier is measured on the
whole prompt, so the listing is held to 180,000 estimated tokens and the system
instruction has the remaining 20,000. A volume over it is refused by name -
`VolumeTooLarge` - rather than priced at a tier the rate table has no row for.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mangatl.domain.glossary import ProposedTerm
from mangatl.domain.line import OcrResult
from mangatl.translate.page_prompt import GLOSSARY_KEY, GLOSSARY_SCHEMA
from mangatl.translate.parse import parse_terms_text

__all__ = [
    "GLOSSARY_PASS_MAX_INPUT_TOKENS",
    "GLOSSARY_PASS_MAX_OUTPUT_TOKENS",
    "GLOSSARY_PASS_PROMPT",
    "GLOSSARY_PASS_SCHEMA",
    "VolumeTooLarge",
    "glossary_pass_text",
    "parse_glossary_pass",
]

#: MT-101 D-12 via PO-1: the 200k tier is measured on the prompt; 20k headroom
#: is left for the system instruction.
GLOSSARY_PASS_MAX_INPUT_TOKENS: int = 180_000

#: A volume's glossary is longer than one page's answer, so twice the page cap.
#: Includes thinking tokens on Gemini, as the page cap does.
GLOSSARY_PASS_MAX_OUTPUT_TOKENS: int = 8_192

#: One working prompt; tuning it is MT-108's measurement, not this story's.
GLOSSARY_PASS_PROMPT = """You build the glossary for a volume of Japanese manga \
before it is translated.

You are given the text OCR read from every page of the volume, page by page, \
each page's lines in reading order under a "Page N:" header. Pages with no \
readable text are left out. Do not translate the lines.

Find the terms that need one consistent English rendering across the volume:
- character names, as written in Japanese;
- honorifics attached to them (for example さん, くん, 先輩);
- place names;
- catchphrases or recurring expressions a reader would notice changing.

For each term give its Japanese exactly as it appears in the text, the one \
English rendering to use everywhere, and a note of "name", "honorific" or \
"place" ("" for anything else). List each term once. Prefer terms that recur; \
leave out ordinary words a translator would render differently by context.

Answer under the "glossary" key. If the volume has no such terms, answer with \
an empty list."""

#: The pass's answer: the per-page glossary fragment, required, and nothing else.
GLOSSARY_PASS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {GLOSSARY_KEY: GLOSSARY_SCHEMA},
    "required": [GLOSSARY_KEY],
    "additionalProperties": False,
}


class VolumeTooLarge(Exception):
    """The volume's listing estimates over `GLOSSARY_PASS_MAX_INPUT_TOKENS`.

    Straight off `Exception`, not off `ValueError`: a caller refusing a volume
    must not catch it as one of the parse's malformed answers.
    """


def glossary_pass_text(pages: Sequence[Sequence[OcrResult]]) -> str:
    """The volume listing: each page's readable lines under `Page {n}:`.

    `n` is the page's index plus one, not a count of rendered pages, so a page
    the model's notes cite is the right page. A page with no line that is not
    `ocr_empty` - art, or no regions at all - is dropped header and all: it has
    no terms to find and would spend input tokens against the limit. Lines are
    verbatim, one per line; blocks are separated by one blank line, with no
    preamble and no trailing newline. A volume with nothing readable is `""`.
    """
    blocks = (
        (index, [result.text for result in page if not result.ocr_empty])
        for index, page in enumerate(pages)
    )
    return "\n\n".join(
        f"Page {index + 1}:\n" + "\n".join(lines) for index, lines in blocks if lines
    )


def parse_glossary_pass(text: str) -> tuple[ProposedTerm, ...]:
    """The terms the pass proposed, in the order it gave them.

    Raises `ValueError` naming the key when the answer has no `glossary` - the
    schema requires it. Items are read by `parse_terms_text`, which skips a
    malformed one and keeps its neighbours (MT-014 C-4).
    """
    if GLOSSARY_KEY not in json.loads(text):
        raise ValueError(f"the glossary pass answer has no {GLOSSARY_KEY!r} key")
    return parse_terms_text(text)
