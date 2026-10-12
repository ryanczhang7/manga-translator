"""Claude's request for one page: the call shape around the page prompt.

MT-011 C-3, C-5 and C-7. **What is asked** - the system prompt, the region
listing, the context block, the capped page image and the response schema -
moved to `page_prompt` in MT-079 so every provider asks the same question; the
reasoning for each of those (the 1,568 px cap, `est_tokens`, listing an
`ocr_empty` region) is in that module's docstring. `MAX_IMAGE_LONG_EDGE_PX` and
`prepare_page_image` are re-exported from there unchanged. **How it is asked of
Claude** stays here, and the request is byte-for-byte what it was before the
move (MT-079 AC-1).

Two numbers are **budget constraints and not tuning knobs** (`architecture.md`
D5, `stack.md` §5/O4): **one call per page** - two passes per page costs $2.29
against a $2.00 ceiling, so everything a page needs goes in a single
`messages.create` - and the 1,568 px cap `page_prompt` applies. Changing either
is a change to a stated constraint and goes back to the user.

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
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

from mangatl.domain.glossary import EMPTY_CONTEXT, PromptContext
from mangatl.domain.line import OcrResult
from mangatl.translate.page_prompt import (
    MAX_IMAGE_LONG_EDGE_PX,
    SYSTEM_PROMPT,
    context_text,
    prepare_page_image,
    response_schema,
    user_text,
)

__all__ = [
    "MAX_IMAGE_LONG_EDGE_PX",
    "MAX_OUTPUT_TOKENS",
    "MODEL_ID",
    "build_request",
    "prepare_page_image",
]

#: The ceiling on one page's response. Required by the Messages API (PO-5: the
#: contract's first draft omitted it), and well clear of the cost model's ~700
#: visible output tokens per page.
MAX_OUTPUT_TOKENS: int = 4096

#: `stack.md` §5/O4's model, and the one MT-012's rate table prices against.
MODEL_ID: str = "claude-opus-5"


def build_request(
    page_image: bytes, ocr_results: Sequence[OcrResult], context: PromptContext
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

    **MT-014 C-3: the context goes after the only cache breakpoint.** With
    `context == EMPTY_CONTEXT` (by value) the content is MT-011's
    `[image, listing]` exactly - page 1's request, and no empty text block,
    which the Messages API rejects. Otherwise it is
    `[image, context, listing]`, the context being the non-empty halves of the
    glossary and rolling blocks joined by a blank line. Nothing page-specific
    enters `system` (AC-6), and no image but the current page's is ever sent
    (AC-4). The response schema carries the `glossary` property the model
    proposes terms under; it is not required.
    """
    prepared, est_tokens = prepare_page_image(page_image)
    context_blocks: list[dict[str, Any]] = (
        [] if context == EMPTY_CONTEXT else [{"type": "text", "text": context_text(context)}]
    )

    return {
        "model": MODEL_ID,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "thinking": {"type": "adaptive"},
        "output_config": {
            # `medium` rather than the default `high`: `cost-model.awk` puts the
            # chapter over $2.00 at 3,200 thinking tokens per page.
            "effort": "medium",
            "format": {"type": "json_schema", "schema": response_schema(len(ocr_results))},
        },
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
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
                    *context_blocks,
                    {"type": "text", "text": user_text(ocr_results)},
                ],
            }
        ],
    }, est_tokens
