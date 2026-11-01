"""One page, one `google-genai` request, one result: translation on Gemini.

MT-080 C-1. The Gemini twin of `translate/client.py` and `translate/prompt.py`
together: it asks **the same question** - `page_prompt`'s system prompt, region
listing, context block, capped page image and response schema, unchanged
(MT-079) - in Gemini's call shape, and turns the answer into the same
`TranslationResult` Claude's adapter returns, through the same
`parse_lines_text` / `parse_terms_text`. Nothing above this module can tell the
providers apart except by `CallInfo.model_id`, which is the point: the ledger,
the budget guard and the review screen are unchanged.

Every number and every SDK shape here is cited, not derived - MT-080
"Lead-po verification at PLANNED->RED, 2026-10-12":

- **`MODEL_ID = "gemini-3.1-pro-preview"`** (V-1): the only id the Gemini API
  models page lists for 3.1 Pro. `domain.rates` prices it under that key.
- **The call** (V-3, introspected from `google-genai` 2.29.0):
  `client.models.generate_content(*, model, contents, config)`, keyword-only,
  so `build_request` returns exactly those three kwargs. The image is
  `types.Part.from_bytes(data=, mime_type="image/jpeg")`; text parts are plain
  `str`, which `contents` accepts. The system prompt goes in
  `config.system_instruction`, never in `contents`.
- **Structured output** (V-3): `response_mime_type="application/json"` with
  `response_json_schema = page_prompt.response_schema(N)` **as-is**,
  `additionalProperties: false` included, and `response_schema` left unset -
  the SDK refuses both at once. `parse_lines_text` still validates on its own
  (MT-011 C-4).
- **Thinking at `MEDIUM`** (V-3): Gemini 3.1 Pro defaults to `HIGH`;
  `MEDIUM` is the same effort intent as Claude's `effort: "medium"`, and a
  different level is a cost-model decision that goes to the user.
- **`MAX_OUTPUT_TOKENS = 4096`** (AC-2, V-5): Claude's figure. On Gemini it
  includes thinking tokens, as Claude's `max_tokens` does, so it is parity. A
  truncated answer is a finding for the user, never a silent raise of the cap.
- **No cache control** (C-2, V-6): Gemini's implicit caching is automatic and
  has no per-request setting, and its 4,096-token minimum is above a page's
  prefix, so cache reads are expected to be zero and writes are always zero.
- **Usage** (V-4): `prompt_token_count` (P) **includes**
  `cached_content_token_count` (C) - the REST reference calls P "the total
  effective prompt size" - and thinking bills as output (V-2's pricing page:
  "thinking tokens are included"), so `input = P - C`, `output = K + T`,
  `cache_read = C`, `cache_write = 0`. Every SDK count is `Optional[int]`;
  an absent one is the zero it means.

**The wordless-page guard is `client.translate_page`'s, in the same place**
(MT-011 AC-7 via MT-080 AC-5): `all(...)` on `ocr_empty`, before the client is
touched, so a page of art costs nothing on either provider. The reasons for
`all` over `any` and the flag over the text are in that module's docstring.

**One call and no retry** (`architecture.md` D5): an `UnknownRegionIndex`
propagates to the stage, exactly as on Claude.

**The client is the caller's** (C-6): `compose` constructs
`google.genai.Client(api_key=...)` with the selected key and binds it with
`functools.partial`; this module never constructs one. `parse` imports the
Anthropic SDK's `Message` type at module level, so importing this module loads
that SDK too - noted in MT-080's handoff, harmless, and not this story's to
change.

**The glossary pre-pass** (MT-104) is `propose_glossary`: one text-only call
over the volume's listing, with `glossary_pass`'s prompt, schema and cap, the
same model and thinking level as a page, and the same `_usage_of`. Its input
limit is checked before the client is touched.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from google.genai import Client, types

from mangatl.domain.glossary import PromptContext, estimate_tokens
from mangatl.domain.line import OcrResult
from mangatl.domain.translation import (
    CallInfo,
    GlossaryProposal,
    TokenUsage,
    TranslationResult,
)
from mangatl.translate.glossary_pass import (
    GLOSSARY_PASS_MAX_INPUT_TOKENS,
    GLOSSARY_PASS_MAX_OUTPUT_TOKENS,
    GLOSSARY_PASS_PROMPT,
    GLOSSARY_PASS_SCHEMA,
    VolumeTooLarge,
    glossary_pass_text,
    parse_glossary_pass,
)
from mangatl.translate.page_prompt import (
    SYSTEM_PROMPT,
    context_text,
    prepare_page_image,
    response_schema,
    user_text,
)
from mangatl.translate.parse import parse_lines_text, parse_terms_text

__all__ = ["MAX_OUTPUT_TOKENS", "MODEL_ID", "build_request", "propose_glossary", "translate_page"]

#: V-1: the API's only spelling of Gemini 3.1 Pro (PO-2's model).
MODEL_ID: str = "gemini-3.1-pro-preview"

#: AC-2: Claude's cap, for the same reason; includes thinking tokens (V-5).
MAX_OUTPUT_TOKENS: int = 4096


def build_request(
    page_image: bytes, ocr_results: Sequence[OcrResult], context: PromptContext
) -> dict[str, Any]:
    """The kwargs for one page's `client.models.generate_content(**kwargs)`.

    `contents` is the capped JPEG first, then the context text **only when it
    is non-empty** (an empty part is a 400), then the region listing - Claude's
    order (MT-079 AC-1). Built deterministically, so two calls with the same
    arguments compare equal.
    """
    jpeg, _ = prepare_page_image(page_image)
    context_part = context_text(context)
    contents: list[types.Part | str] = [
        types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
        *([context_part] if context_part else []),
        user_text(ocr_results),
    ]
    return {
        "model": MODEL_ID,
        "contents": contents,
        "config": types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=response_schema(len(ocr_results)),
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM),
            max_output_tokens=MAX_OUTPUT_TOKENS,
        ),
    }


def translate_page(
    client: Client,
    page_image: bytes,
    ocr_results: Sequence[OcrResult],
    context: PromptContext,
) -> TranslationResult:
    """Translate one page on Gemini: one request, one response, one result.

    Positional in the same order as `client.translate_page`, so `compose` binds
    it the same way. With every region `ocr_empty` - or no regions at all - it
    returns `TranslationResult({}, TokenUsage(0, 0, 0, 0), call=None, ())`
    without touching `client`.

    `CallInfo.model_id` is the model the response **reports**
    (`model_version`), not `MODEL_ID` (MT-044 C-5: the ledger reconciles
    against the bill); only when the response reports none is the requested
    id recorded. `request_id` is `response_id`, `""` when the SDK has none.

    A response with no text (V-5's truncation, or a block) parses as an empty
    body and fails loudly in `json.loads`, as a refusal does on Claude.
    """
    if all(result.ocr_empty for result in ocr_results):
        return TranslationResult(
            lines={}, usage=TokenUsage(0, 0, 0, 0), call=None, proposed_terms=()
        )

    response = client.models.generate_content(**build_request(page_image, ocr_results, context))
    text = response.text or ""

    return TranslationResult(
        lines=parse_lines_text(text, range(len(ocr_results))),
        usage=_usage_of(response.usage_metadata),
        call=CallInfo(
            request_id=response.response_id or "",
            model_id=response.model_version or MODEL_ID,
        ),
        proposed_terms=parse_terms_text(text),
    )


def propose_glossary(client: Client, pages: Sequence[Sequence[OcrResult]]) -> GlossaryProposal:
    """Propose the volume's glossary on Gemini: one text-only request.

    `contents` is the listing alone - no page image, which would make a
    volume-sized call cost a page image per page. Raises `VolumeTooLarge`,
    naming the estimate and the limit, **before** `client` is touched when the
    listing estimates over `GLOSSARY_PASS_MAX_INPUT_TOKENS`; at the limit is
    sent. `call` is recorded as `translate_page` records it.
    """
    listing = glossary_pass_text(pages)
    estimate = estimate_tokens(listing)
    if estimate > GLOSSARY_PASS_MAX_INPUT_TOKENS:
        raise VolumeTooLarge(
            f"the volume's listing estimates to {estimate:,} tokens, over the"
            f" glossary pass's limit of {GLOSSARY_PASS_MAX_INPUT_TOKENS:,}"
        )

    contents: list[types.PartUnionDict] = [listing]
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=GLOSSARY_PASS_PROMPT,
            response_mime_type="application/json",
            response_json_schema=GLOSSARY_PASS_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM),
            max_output_tokens=GLOSSARY_PASS_MAX_OUTPUT_TOKENS,
        ),
    )

    return GlossaryProposal(
        terms=parse_glossary_pass(response.text or ""),
        usage=_usage_of(response.usage_metadata),
        call=CallInfo(
            request_id=response.response_id or "",
            model_id=response.model_version or MODEL_ID,
        ),
    )


def _usage_of(
    usage_metadata: types.GenerateContentResponseUsageMetadata | None,
) -> TokenUsage:
    """The SDK's usage counts as the domain's four (V-4).

    `input = P - C` because the prompt count includes the cached part, and
    `output = K + T` because thinking bills as output: forgetting T
    under-reports the one input of the cost model nobody controls, and not
    subtracting C bills cached tokens twice. `cache_write` is always 0 -
    implicit caching has no write. A missing count is zero rather than `None`,
    because the ledger's columns are not nullable.

    **Missing metadata is not zero**: a response that reports no usage at all
    raises rather than pricing a paid call at nothing - the failure
    `domain.rates` calls its worst (it spends money and reports none).
    """
    if usage_metadata is None:
        raise ValueError("the Gemini response reported no usage; a paid call cannot be priced")
    cached = usage_metadata.cached_content_token_count or 0
    thinking = usage_metadata.thoughts_token_count or 0
    return TokenUsage(
        input_tokens=(usage_metadata.prompt_token_count or 0) - cached,
        output_tokens=(usage_metadata.candidates_token_count or 0) + thinking,
        cache_read_tokens=cached,
        cache_write_tokens=0,
    )
