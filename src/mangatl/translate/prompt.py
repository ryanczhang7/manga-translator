"""The page image, the region list, and the one request they go in.

MT-011 C-3, C-5 and C-7. Two numbers here are **budget constraints and not
tuning knobs** (`architecture.md` D5, `stack.md` §5/O4):

- **one call per page** - two passes per page costs $2.29 against a $2.00
  ceiling, so everything a page needs goes in a single `messages.create`;
- **the page image capped at 1,568 px on the long edge** - an uncapped 2400x3400
  scan costs $1.95 against $1.14 capped, and 1,568 px is Claude's documented
  image long-edge cap, beyond which the image is downscaled server-side anyway.
  Sending more is paying for bytes that are discarded.

Changing either is a change to a stated constraint and goes back to the user.

**`est_tokens` is `ceil(width x height / 750)` on the *capped* dimensions**
(C-7). `ceil` rather than floor: a 1568x1098 page gives 1,721,664 / 750 =
2295.552, and 2296 is the figure `stack.md` §5/O4 prints - and `ceil` is the
safe direction for a number MT-013's budget guard projects spend with. On the
capped dimensions rather than the original because the estimate has to describe
what is actually sent; taking it before the resize is silent, leaves every image
correctly capped, and inflates a 2400x3400 page's projection 4.7x.

**`build_request` returns `(kwargs, est_tokens)`, not one dict** (C-3's RED
amendment, accepted as PO-9). `est_tokens` is not a parameter of the Messages
API and there is no field on it that could carry one - `metadata` accepts
`user_id` only - so a dict carrying it raises `TypeError: create() got an
unexpected keyword argument 'est_tokens'` at the first real dispatch, which is
MT-037's, with a credential, after spending money.

**The cache breakpoint is on the `system` block and nowhere else** (C-5). Render
order is `tools` -> `system` -> `messages`, so the page image, the region list
and MT-014's rolling context all sit *after* it, where they are free to vary per
page. A breakpoint placed after the page image caches nothing across pages.

**An `ocr_empty` region is listed like any other, with empty source text**
(PO-11). `stack.md` §5/O3 chose local OCR over LLM-only OCR precisely because
"the LLM then receives both the OCR text and the page image, so it can silently
correct an OCR miss it can see - which is the safety net that makes the cheap
option safe". A region OCR read nothing from is exactly that miss, so dropping
it from the listing and the schema would remove the mechanism O3 relies on.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from io import BytesIO
from math import ceil
from typing import Any

from PIL import Image

from mangatl.domain.line import OcrResult

__all__ = [
    "MAX_IMAGE_LONG_EDGE_PX",
    "MAX_OUTPUT_TOKENS",
    "MODEL_ID",
    "build_request",
    "prepare_page_image",
]

#: Claude's documented image long-edge cap, and `architecture.md` D5's budget.
MAX_IMAGE_LONG_EDGE_PX: int = 1568

#: The ceiling on one page's response. Required by the Messages API (PO-5: the
#: contract's first draft omitted it), and well clear of the cost model's ~700
#: visible output tokens per page.
MAX_OUTPUT_TOKENS: int = 4096

#: `stack.md` §5/O4's model, and the one MT-012's rate table prices against.
MODEL_ID: str = "claude-opus-5"

#: Claude's published tokens-per-image divisor: `width x height / 750`.
_PIXELS_PER_TOKEN = 750

#: JPEG quality for the prepared page. Nothing in the contract pins it; 85 is
#: the usual legibility/size trade-off and the bytes are what the model reads,
#: not what the user sees.
_JPEG_QUALITY = 85

#: The stable prefix, and the only block carrying a cache breakpoint. Nothing
#: page-specific may appear here: everything in it is read again for every page
#: of the chapter, and one volatile character invalidates the cache for all of
#: them.
_SYSTEM_PROMPT = """You translate Japanese manga into natural English.

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
- Answer with one entry per region, keyed by the region's reading index."""


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


def build_request(
    page_image: bytes, ocr_results: Sequence[OcrResult]
) -> tuple[dict[str, Any], int]:
    """The kwargs for one page's `client.messages.create(**kwargs)`, and the
    estimate of the image they carry.

    Exactly three blocks (AC-1): one image block, one system block and one user
    text block listing all N regions by reading index and source text, in
    reading order. The image comes **before** the text that describes it, which
    is the ordering the Anthropic API reference's own vision examples use.

    The call shape is C-5's, settled and verified against the API reference
    (PO-5): `thinking={"type": "adaptive"}` with no `budget_tokens` (a 400 on
    this model), `effort` **inside** `output_config`, structured output via
    `output_config.format` rather than the deprecated top-level `output_format`
    or an assistant prefill (also a 400), non-streaming at `max_tokens`. An
    agent that "improves" any of it has changed the cost model.
    """
    prepared, est_tokens = prepare_page_image(page_image)
    reading_indices = [str(index) for index in range(len(ocr_results))]

    return {
        "model": MODEL_ID,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "thinking": {"type": "adaptive"},
        "output_config": {
            # `medium` rather than the default `high`: `cost-model.awk` puts the
            # chapter over $2.00 at 3,200 thinking tokens per page.
            "effort": "medium",
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        index: {
                            "type": "string",
                            "description": f"The English for the region at reading index {index}.",
                        }
                        for index in reading_indices
                    },
                    # No `required`, and that is what makes AC-5 a real case: a
                    # compliant model may omit a region only if the schema lets
                    # it. `additionalProperties: false` is the other half - it
                    # makes AC-6's unknown index the model disobeying rather
                    # than the schema inviting it.
                    "additionalProperties": False,
                },
            },
        },
        "system": [
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
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
                            # `b64encode` and never `encodebytes`: the latter
                            # wraps at 76 characters and the API rejects it.
                            "data": base64.b64encode(prepared).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": _user_text(ocr_results)},
                ],
            }
        ],
    }, est_tokens


def _user_text(ocr_results: Sequence[OcrResult]) -> str:
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
