"""The one call a page is allowed to make, and the page that makes none.

MT-011 C-5. This is the only module in the project that dispatches to the
Anthropic API, and it is the boundary where the SDK's objects are converted into
the plain `domain` values everything above it reads - `domain` may not import
`anthropic` (the *"domain is independent"* contract), so a `Message` or a
`Usage` must not travel past this function.

**AC-7's guard lives here** (C-5's RED amendment). "No API call is made" is a
claim about the client, the client is this function's parameter and appears
nowhere else in the story, so a guard in `TranslateStage.run` instead would
leave `translate_page` willing to spend on a blank page whenever anything else
called it. A page of wordless art must not cost money: a chapter with five
wordless splash pages would otherwise spend a twentieth of its budget on
nothing.

**The guard is `all(...)` and it is decided on `ocr_empty`, never on the text.**
`all` and not `any`: AC-7 is "a page whose regions are **all** `ocr_empty`", and
a page with one readable bubble among three blank ones is an ordinary page that
must be translated - a guard written with `any` stops translating most of the
chapter and passes every all-empty test. And `ocr_empty` and not `text == ""`:
MT-010 C-5 is explicit that an empty text *without* the flag is a successful
read of nothing printable, so a guard on the text would skip a bubble of pure
punctuation too. The flag is stored rather than derived (MT-010 PO-3) precisely
so that this question is answerable before a call is made.

**A page that made no call is priced at zero, not at `None`.** MT-012 sums a
ledger; an `Optional` usage for a case whose value is known and is zero gets
unwrapped wrongly once and reports a `TypeError` instead of a cost.

**One call, and no retry.** `architecture.md` D5 allows exactly one call per
page - two passes costs $2.29 against a $2.00 ceiling - so an
`UnknownRegionIndex` from the parse propagates rather than being caught here:
AC-6's "nothing is written to the store" is only true if the exception reaches
the stage, and a partial result returned instead would write the good regions
and lose the error.
"""

from __future__ import annotations

from collections.abc import Sequence

from anthropic import Anthropic
from anthropic.types import Usage

from mangatl.domain.line import OcrResult
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.translate.parse import parse_lines
from mangatl.translate.prompt import build_request

__all__ = ["translate_page"]


def translate_page(
    client: Anthropic, page_image: bytes, ocr_results: Sequence[OcrResult]
) -> TranslationResult:
    """Translate one page: one request, one response, one result.

    Returns
    `TranslationResult(lines={}, usage=TokenUsage(0, 0, 0, 0), call=None)`
    without touching `client` when every region read empty - or when there are
    no regions at all, which `all(...)` answers for free. `call=None` is the
    statement that no API call was made (MT-044 C-4), and it is what
    `TranslateStage` reads to decide there is no ledger row to write; the four
    zero counts are what it *cost*, which is a different fact.

    On a call, `call` carries the response's own `id` and `model`. **The
    model is `response.model` and not `prompt.MODEL_ID`** (MT-044 C-5): the
    ledger exists to be reconciled against the provider's bill, and the bill is
    for the model that actually served the request, so pinning the request's
    constant records a lie the day an alias resolves to a snapshot. The cost of
    that pin is named rather than hidden: an id `domain.rates.RATES` does not
    list makes `price` raise `UnknownModel` and aborts the run, which is
    `rates.py`'s designed behaviour and is carried as MT-044 DV-5.
    """
    if all(result.ocr_empty for result in ocr_results):
        return TranslationResult(lines={}, usage=TokenUsage(0, 0, 0, 0), call=None)

    request, _ = build_request(page_image, ocr_results)
    response = client.messages.create(**request)

    return TranslationResult(
        lines=parse_lines(response, range(len(ocr_results))),
        usage=_usage_of(response.usage),
        call=CallInfo(request_id=response.id, model_id=response.model),
    )


def _usage_of(usage: Usage) -> TokenUsage:
    """The SDK's four counts as the domain's four.

    The two cache fields are `Optional[int]` on the SDK's `Usage` - they are
    absent on a response that neither read nor wrote a cache entry - and the
    ledger's columns are not nullable, so a missing count is the zero it means.
    The pairing is the whole of this function: a swap of the two is a
    factor-of-12.5 pricing error (0.1x against 1.25x of the base input rate)
    that MT-012 would report as fact.
    """
    return TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
    )
