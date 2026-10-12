"""The page prompt every translation provider is asked: provider-neutral.

MT-079 C-1. Everything a provider needs to ask the same question about one page
- the system prompt, the region listing, the context block, the capped page
image and the response JSON schema - moved here unchanged from `prompt.py`,
where it was private and sat beside Claude's call shape. `prompt.build_request`
now composes these pieces into Claude's kwargs; MT-080/081 compose the same
pieces into theirs. **The same prompt for every provider is the point**: the
measured costs and acceptance rates of the providers are comparable only if they
were asked the same question.

**This module imports no SDK, and nothing from `parse`** (AC-5, and the
PLANNED->RED amendment): `parse` imports `anthropic.types.Message`, so a
`GLOSSARY_KEY` imported from there would load the Anthropic SDK into every
provider. `GLOSSARY_KEY` therefore lives here and `parse` imports it.

**The page image is capped at 1,568 px on the long edge for every provider.**
It is a cost constraint (`architecture.md` D5, `stack.md` §5/O4): an uncapped
2400x3400 scan costs $1.95 against $1.14 capped on Claude, and 1,568 px is
Claude's documented long-edge cap, beyond which the image is downscaled
server-side anyway. The same image for every provider is also what keeps the
measurements comparable. Changing it goes back to the user.

**`est_tokens` is Claude's rule, `ceil(width x height / 750)`, on the *capped*
dimensions** (MT-011 C-7), and is not a provider-neutral number. `ceil` rather
than floor: a 1568x1098 page gives 1,721,664 / 750 = 2295.552, and 2296 is the
figure `stack.md` §5/O4 prints - and `ceil` is the safe direction for a number a
budget guard projects spend with. On the capped dimensions because the estimate
has to describe what is actually sent; taking it before the resize inflates a
2400x3400 page's projection 4.7x.

**An `ocr_empty` region is listed like any other, with empty source text**
(MT-011 PO-11). `stack.md` §5/O3 chose local OCR over LLM-only OCR because the
model receives both the OCR text and the page image and can correct an OCR miss
it can see; dropping an empty region from the listing and the schema would
remove that mechanism.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from math import ceil
from typing import Any

from PIL import Image

from mangatl.domain.glossary import PromptContext
from mangatl.domain.line import OcrResult

__all__ = [
    "GLOSSARY_KEY",
    "GLOSSARY_SCHEMA",
    "MAX_IMAGE_LONG_EDGE_PX",
    "SYSTEM_PROMPT",
    "context_text",
    "prepare_page_image",
    "response_schema",
    "user_text",
]

#: Claude's documented image long-edge cap, and `architecture.md` D5's budget.
MAX_IMAGE_LONG_EDGE_PX: int = 1568

#: The one response key that is not a reading index (MT-014 C-3/C-4). It can
#: never collide with one: a reading index is always digits.
GLOSSARY_KEY: str = "glossary"

#: Claude's published tokens-per-image divisor: `width x height / 750`.
_PIXELS_PER_TOKEN = 750

#: JPEG quality for the prepared page. Nothing in the contract pins it; 85 is
#: the usual legibility/size trade-off and the bytes are what the model reads,
#: not what the user sees.
_JPEG_QUALITY = 85

#: MT-014 C-3: the one non-index property of the response schema. Each item's
#: `additionalProperties: false` keeps an invented field out of `parse_terms`;
#: the note's enum is `domain.glossary.Note`.
GLOSSARY_SCHEMA: dict[str, Any] = {
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

#: The stable prefix. On Claude it is the only block carrying a cache
#: breakpoint, so nothing page-specific may appear here: everything in it is read
#: again for every page of the chapter, and one volatile character invalidates
#: the cache for all of them.
SYSTEM_PROMPT = """You translate Japanese manga into natural English.

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


def prepare_page_image(page_image: bytes) -> tuple[bytes, int]:
    """Cap one page for the request: `(JPEG bytes, est_tokens)`.

    The long edge comes back at **at most** `MAX_IMAGE_LONG_EDGE_PX`, with the
    aspect ratio preserved and the orientation unchanged. A page already at or
    under the cap is **not upscaled** (AC-3): "at most 1568 px" includes 1568,
    so a page already there is returned at its own size rather than resized to
    itself, and an implementation scaling unconditionally by `1568 / longest`
    would enlarge a 1567 px page into bytes the server throws away.

    It is still re-encoded as JPEG, because the request's media type says JPEG
    and the caller may hand over a PNG, a WebP or anything else `read_bytes`
    found in the scans folder.

    `est_tokens` is `ceil(w * h / 750)` on the dimensions of the image this
    function actually returns - see the module docstring for why both halves of
    that are load-bearing.
    """
    with Image.open(BytesIO(page_image)) as source:
        width, height = source.size
        longest = max(width, height)
        # `.convert("RGB")` on both paths: JPEG has no alpha and no palette, so
        # a page arriving as RGBA or as "P" raises on save without it.
        if longest > MAX_IMAGE_LONG_EDGE_PX:
            scale = MAX_IMAGE_LONG_EDGE_PX / longest
            size = (
                (MAX_IMAGE_LONG_EDGE_PX, max(1, round(height * scale)))
                if width >= height
                else (max(1, round(width * scale)), MAX_IMAGE_LONG_EDGE_PX)
            )
            prepared = source.resize(size, Image.Resampling.LANCZOS).convert("RGB")
        else:
            prepared = source.convert("RGB")
        buffer = BytesIO()
        prepared.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
        out_width, out_height = prepared.size

    return buffer.getvalue(), ceil(out_width * out_height / _PIXELS_PER_TOKEN)


def user_text(ocr_results: Sequence[OcrResult]) -> str:
    """The region listing: every region, once, by index and source text.

    In reading order and never re-sorted - reading order is computed once, in
    the domain (`architecture.md` D10), and a request that re-ordered it would
    hand the model a different page from the one the review screen shows.
    """
    listing = "\n".join(f"[{index}] {result.text}" for index, result in enumerate(ocr_results))
    return (
        "Here is the page, and the text OCR read from each of its regions in"
        f" reading order:\n\n{listing}"
    )


def context_text(context: PromptContext) -> str:
    """The glossary block, then the rolling block, the empty one omitted."""
    return "\n\n".join(block for block in (context.glossary_block, context.rolling_block) if block)


def response_schema(region_count: int) -> dict[str, Any]:
    """The JSON schema of one page's answer: a string per reading index, plus
    the optional `glossary` array (MT-011 C-5, MT-014 C-3).

    **No `required`**, and that is what makes an omitted region a real case
    (MT-011 AC-5): a compliant model may omit a region only if the schema lets
    it. `additionalProperties: false` is the other half - it makes an unknown
    index the model disobeying rather than the schema inviting it.
    """
    return {
        "type": "object",
        "properties": {
            str(index): {
                "type": "string",
                "description": f"The English for the region at reading index {index}.",
            }
            for index in range(region_count)
        }
        | {GLOSSARY_KEY: GLOSSARY_SCHEMA},
        "additionalProperties": False,
    }
