"""`mangatl.translate.gemini`: one page, one `google-genai` request, one result.

MT-080. Covers **AC-1** to **AC-5** - the request's pieces, its JSON/model/cap
settings, the parse, the usage arithmetic and the wordless-page guard. AC-6 is
in `test_compose.py`, AC-7 in `test_rates.py`, AC-8 in
`tests/integration/test_gemini_live.py`.

**Oracle partition: entirely mechanical.** Every figure is read out of the
story's `## Contract` as settled by "Lead-po verification at PLANNED->RED,
2026-10-12" (V-1..V-9), never re-derived here: the model id (V-1), the call
shape (V-3), the usage field names and `input = P - C`, `output = K + T` (V-4).

**No `google.genai` import anywhere in this file** (V-7): the SDK is a GREEN
dependency and is not installed in RED. The client and the response are
hand-written ducks, like `test_translate_client.py`'s. What the request looks
like is read **by attribute**, never by `isinstance` against an SDK type, so
the same assertions hold against the real `types.Part` / `GenerateContentConfig`
GREEN builds (C-2 as amended in RED, see the story):

- `kwargs["contents"]` is a list: the image part first, then the context text
  (only when non-empty), then the listing. A text part is either a plain `str`
  (V-3: the SDK accepts `str` in `contents`) or an object whose `.text` is the
  string - `_text_of` reads both, so that choice stays GREEN's. The image part
  is an object whose `.inline_data.data` is the capped JPEG and whose
  `.inline_data.mime_type` is `"image/jpeg"` - which is what
  `types.Part.from_bytes(data=..., mime_type=...)` produces.
- `kwargs["config"]` exposes `system_instruction`, `response_mime_type`,
  `response_json_schema`, `response_schema` (must be unset: V-3, "if set,
  `response_schema` must be omitted"), `max_output_tokens` and
  `thinking_config.thinking_level`. `ThinkingLevel` is a `str` enum in the SDK,
  so `== "MEDIUM"` holds for `ThinkingLevel.MEDIUM` as well as for the string.

**What this file cannot catch, stated so nobody mistakes its reach.** A kwarg
the real SDK does not accept, or a field name it spells differently, passes
every duck here. C-5: the live test is the only place an invented SDK shape
fails, and it is GATES' to run (DV-3).

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so no
budget in this file to size. The dominant cost is `prepare_page_image` on a
1200x2400 page (a resize and a JPEG encode, tens of ms); `_page` is cached.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from mangatl.domain.glossary import EMPTY_CONTEXT, PromptContext, ProposedTerm
from mangatl.domain.line import OcrResult
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.translate import page_prompt
from mangatl.translate.parse import UnknownRegionIndex, parse_terms_text

# -- the fixture page ----------------------------------------------------------

#: The four regions `fixtures/translate/README.md` tabulates.
_OCR_RESULTS: tuple[OcrResult, ...] = (
    OcrResult(text="醜鬼が人間の言う通りに動いたりね"),
    OcrResult(text="……なるほど"),
    OcrResult(text="どうして君がここに"),
    OcrResult(text="行くぞ"),
)

_ALL_EMPTY: tuple[OcrResult, ...] = tuple(OcrResult(text="", ocr_empty=True) for _ in range(4))

_EXPECTED: dict[int, str] = {
    0: "As if a demon would move at a human's say-so.",
    1: "...I see.",
    2: "Why are you here?",
    3: "Let's go.",
}

#: Both blocks non-empty, with text that occurs nowhere else in the request.
_CONTEXT = PromptContext(
    glossary_block="Glossary - use these renderings exactly:\nさくら = Sakura (name)",
    rolling_block="Previous page, in reading order:\nWait for me, Sakura!",
)


#: `fixtures/translate/` at the repository root (V-7).
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "translate"


@cache
def _page() -> bytes:
    """A 1200x2400 PNG - **over** the 1,568 px cap, so the capped JPEG and the
    page as handed over differ in size, format and bytes. A page under the cap
    would let an implementation that sent the raw bytes pass the image test."""
    image = Image.new("RGB", (1200, 2400), (32, 48, 64))
    for y in range(0, 2400, 40):
        image.paste((220, 220, 220), (0, y, 1200, y + 8))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _body(name: str) -> str:
    """A recorded body from `fixtures/translate/`, as text (key order matters)."""
    return (_FIXTURES / f"{name}.json").read_text(encoding="utf-8")


# -- the fake client and response ---------------------------------------------

#: Distinct from `gemini.MODEL_ID` on purpose: `CallInfo.model_id` must be the
#: model the response REPORTS (V-4, MT-044 C-5), and a fake that reported the
#: request's own id could not tell the two sources apart.
_REPORTED_MODEL = "gemini-3.1-pro-preview-reported-by-the-response"
_RESPONSE_ID = "gemini-response-fake"


def _usage_metadata(
    prompt: int | None = 0,
    cached: int | None = None,
    candidates: int | None = 0,
    thoughts: int | None = None,
) -> SimpleNamespace:
    """`response.usage_metadata` with V-4's four field names."""
    return SimpleNamespace(
        prompt_token_count=prompt,
        cached_content_token_count=cached,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        total_token_count=None,
    )


def _response(
    body: str,
    *,
    usage: SimpleNamespace | None = None,
    response_id: str | None = _RESPONSE_ID,
    model_version: str | None = _REPORTED_MODEL,
    finish_reason: str = "STOP",
) -> SimpleNamespace:
    """A `GenerateContentResponse`-shaped value (V-4, V-7)."""
    return SimpleNamespace(
        text=body,
        usage_metadata=usage if usage is not None else _usage_metadata(),
        model_version=model_version,
        response_id=response_id,
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
    )


class _ClientExploded(Exception):
    """A call nobody should have made."""


class _FakeModels:
    """`client.models`. Records every `generate_content` call's kwargs."""

    def __init__(self, responses: Sequence[object], *, explode: bool) -> None:
        self._responses = list(responses)
        self._explode = explode
        self.seen: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> object:
        self.seen.append(kwargs)
        if self._explode:
            raise _ClientExploded("the Gemini client was called and should not have been")
        return self._responses[len(self.seen) - 1]


class _FakeGeminiClient:
    """Stands in for `google.genai.Client`. No credential, no network."""

    def __init__(self, *responses: object, explode: bool = False) -> None:
        self.models = _FakeModels(responses, explode=explode)

    @property
    def calls(self) -> int:
        return len(self.models.seen)


@pytest.fixture
def gemini() -> ModuleType:
    """`mangatl.translate.gemini`, imported per test rather than at the top.

    RED: the module does not exist, and a top-level import is a COLLECTION
    error - which interrupts the whole `pytest tests/core tests/ui` session and
    takes every other test in the project dark with it. Imported here, each
    test in this file fails on the named absence and the rest of the suite
    still runs (the `_selection` pattern in `test_compose.py`).
    """
    from mangatl.translate import gemini as module

    return module


# -- reading the request without the SDK --------------------------------------


def _text_of(part: object) -> str | None:
    """The text of a text part - a plain `str`, or an object with a `str`
    `.text` and no inline data - else `None`."""
    if isinstance(part, str):
        return part
    if getattr(part, "inline_data", None) is None and isinstance(getattr(part, "text", None), str):
        return str(part.text)  # type: ignore[attr-defined]
    return None


def _inline_of(part: object) -> object | None:
    """The `.inline_data` of an image part, else `None`."""
    if isinstance(part, str):
        return None
    return getattr(part, "inline_data", None)


def _contents(request: dict[str, Any]) -> list[object]:
    contents = request["contents"]
    assert isinstance(contents, list), f"contents is {type(contents).__name__}, not a list"
    return contents


def _texts(request: dict[str, Any]) -> list[str | None]:
    return [_text_of(part) for part in _contents(request)]


# -- the module's constants (AC-2) --------------------------------------------


def test_the_model_is_the_one_id_the_gemini_api_lists_for_3_1_pro(gemini: ModuleType) -> None:
    """AC-2 and V-1: `gemini-3.1-pro-preview`, the API's only spelling of the
    model PO-2 chose."""
    assert gemini.MODEL_ID == "gemini-3.1-pro-preview"


def test_the_output_cap_is_claudes_4096_tokens(gemini: ModuleType) -> None:
    """AC-2: 4,096, Claude's figure for the same reason; V-5 - thinking counts
    against it on both providers, so this is parity, not a new risk."""
    assert gemini.MAX_OUTPUT_TOKENS == 4096


# -- AC-1 / AC-2: the request --------------------------------------------------


def test_the_request_is_exactly_model_contents_and_config(gemini: ModuleType) -> None:
    """V-3: `generate_content(*, model, contents, config)` is keyword-only, so
    `build_request` returns kwargs and nothing else - a stray key is a
    `TypeError` on the real client, which only the live test would see."""
    request = gemini.build_request(_page(), _OCR_RESULTS, EMPTY_CONTEXT)

    assert set(request) == {"model", "contents", "config"}, sorted(request)
    assert request["model"] == gemini.MODEL_ID


def test_with_an_empty_context_the_request_is_the_image_then_the_listing_and_no_empty_part(
    gemini: ModuleType,
) -> None:
    """AC-1: two parts, image first, the listing last - and **no empty text
    part** for the absent context (an empty `Part` is a 400 on the real API)."""
    request = gemini.build_request(_page(), _OCR_RESULTS, EMPTY_CONTEXT)

    contents = _contents(request)
    assert len(contents) == 2, f"{len(contents)} parts for an empty context: {_texts(request)}"
    assert _inline_of(contents[0]) is not None, "the first part is not the image"
    assert _texts(request) == [None, page_prompt.user_text(_OCR_RESULTS)]
    assert "" not in _texts(request)


def test_with_a_context_the_request_is_the_image_the_context_then_the_listing(
    gemini: ModuleType,
) -> None:
    """AC-1: three parts, in Claude's order - image, context, listing - with
    the context text exactly `page_prompt.context_text(context)`."""
    request = gemini.build_request(_page(), _OCR_RESULTS, _CONTEXT)

    contents = _contents(request)
    assert len(contents) == 3, f"{len(contents)} parts for a non-empty context"
    assert _inline_of(contents[0]) is not None, "the first part is not the image"
    assert _texts(request) == [
        None,
        page_prompt.context_text(_CONTEXT),
        page_prompt.user_text(_OCR_RESULTS),
    ]


def test_a_context_with_only_a_rolling_block_still_gets_its_own_part(gemini: ModuleType) -> None:
    """The one-of-two case: `context_text` omits the empty glossary block, and
    the request carries what remains rather than deciding emptiness on one
    field."""
    context = PromptContext(glossary_block="", rolling_block="Previous page:\nRun!")
    request = gemini.build_request(_page(), _OCR_RESULTS, context)

    assert _texts(request)[1:] == [
        page_prompt.context_text(context),
        page_prompt.user_text(_OCR_RESULTS),
    ]


def test_the_one_image_part_is_the_capped_jpeg_not_the_page_as_handed_over(
    gemini: ModuleType,
) -> None:
    """AC-1: exactly one image part, carrying `prepare_page_image(page)[0]` as
    `image/jpeg`. The page is a 1200x2400 PNG, so sending it raw, or uncapped,
    or with the wrong media type, each fails a different line."""
    page = _page()
    request = gemini.build_request(page, _OCR_RESULTS, _CONTEXT)

    images = [_inline_of(part) for part in _contents(request) if _inline_of(part) is not None]
    assert len(images) == 1, f"{len(images)} image parts"
    (inline,) = images
    jpeg, _ = page_prompt.prepare_page_image(page)
    assert inline.data == jpeg, "the image part is not the capped JPEG"  # type: ignore[attr-defined]
    assert inline.data != page  # type: ignore[attr-defined]
    assert inline.mime_type == "image/jpeg"  # type: ignore[attr-defined]


def test_the_system_prompt_is_in_the_system_instruction_slot_and_not_in_the_contents(
    gemini: ModuleType,
) -> None:
    """AC-1: `SYSTEM_PROMPT` in `config.system_instruction` (V-3). A copy in
    `contents` as well would bill it twice per page."""
    request = gemini.build_request(_page(), _OCR_RESULTS, _CONTEXT)

    assert request["config"].system_instruction == page_prompt.SYSTEM_PROMPT
    assert page_prompt.SYSTEM_PROMPT not in _texts(request)


def test_the_request_asks_for_json_against_the_page_schema_as_is(gemini: ModuleType) -> None:
    """AC-2 and V-3: `response_mime_type="application/json"` and
    `response_json_schema = page_prompt.response_schema(N)` unchanged -
    `additionalProperties: false` included - with `response_schema` left
    unset, because the SDK refuses both at once."""
    config = gemini.build_request(_page(), _OCR_RESULTS, EMPTY_CONTEXT)["config"]

    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == page_prompt.response_schema(len(_OCR_RESULTS))
    assert config.response_json_schema["additionalProperties"] is False
    assert getattr(config, "response_schema", None) is None


def test_the_schema_follows_the_number_of_regions_on_the_page(gemini: ModuleType) -> None:
    """The N of `response_schema(N)` is this page's region count, not a
    constant: a two-region page's schema has two index properties."""
    config = gemini.build_request(_page(), _OCR_RESULTS[:2], EMPTY_CONTEXT)["config"]

    assert config.response_json_schema == page_prompt.response_schema(2)
    assert config.response_json_schema != page_prompt.response_schema(len(_OCR_RESULTS))


def test_the_output_is_capped_and_thinking_runs_at_medium(gemini: ModuleType) -> None:
    """AC-2's cap (`max_output_tokens = MAX_OUTPUT_TOKENS`) and V-3's
    `thinking_level="MEDIUM"` - Claude's `effort: "medium"` intent. The model's
    default is HIGH (V-3), so an unset level is a cost-model change."""
    config = gemini.build_request(_page(), _OCR_RESULTS, EMPTY_CONTEXT)["config"]

    assert config.max_output_tokens == gemini.MAX_OUTPUT_TOKENS == 4096
    assert config.thinking_config.thinking_level == "MEDIUM"


# -- translate_page: dispatch --------------------------------------------------


def test_a_page_with_text_makes_exactly_one_call_carrying_the_built_request(
    gemini: ModuleType,
) -> None:
    """One call per page (`architecture.md` D5), carrying `build_request`'s own
    output - so the request shape is written down once, above."""
    page = _page()
    client = _FakeGeminiClient(_response(_body("well-formed")), _response(_body("well-formed")))

    gemini.translate_page(client, page, _OCR_RESULTS, _CONTEXT)

    assert client.calls == 1, f"{client.calls} calls for one page"
    assert client.models.seen[0] == gemini.build_request(page, _OCR_RESULTS, _CONTEXT)


def test_the_context_the_caller_passes_reaches_the_request(gemini: ModuleType) -> None:
    """The negative control for the test above: an implementation that always
    built the empty-context request would pass it with EMPTY_CONTEXT."""
    page = _page()
    client = _FakeGeminiClient(_response(_body("well-formed")))

    gemini.translate_page(client, page, _OCR_RESULTS, _CONTEXT)

    assert _texts(client.models.seen[0])[1] == page_prompt.context_text(_CONTEXT)


# -- AC-3: the parse -----------------------------------------------------------


def test_the_lines_come_back_keyed_by_reading_index_not_by_response_order(
    gemini: ModuleType,
) -> None:
    """AC-3: `well-formed.json` is keyed 2, 0, 3, 1, so a positional parse
    gets all four wrong."""
    client = _FakeGeminiClient(_response(_body("well-formed")))

    assert gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT).lines == _EXPECTED


def test_a_region_the_model_omitted_is_absent_and_the_page_is_kept(gemini: ModuleType) -> None:
    """AC-3: region 3 omitted -> absent; the other three kept."""
    client = _FakeGeminiClient(_response(_body("omits-region-3")))

    lines = gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT).lines

    assert lines == {index: _EXPECTED[index] for index in (0, 1, 2)}


def test_a_response_naming_an_unknown_region_raises_naming_it(gemini: ModuleType) -> None:
    """AC-3: `unknown-region-index.json` names region 7 on a four-region page;
    `UnknownRegionIndex` propagates rather than being swallowed."""
    client = _FakeGeminiClient(_response(_body("unknown-region-index")))

    with pytest.raises(UnknownRegionIndex, match=r"\b7\b"):
        gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT)


def test_the_proposed_terms_are_the_shared_parse_of_the_response_text(gemini: ModuleType) -> None:
    """MT-014 C-5 through this adapter: `proposed_terms ==
    parse_terms_text(response.text)`, in order, and the `glossary` key is not a
    region."""
    body = (
        '{"1": "Sakura!", "glossary": ['
        '{"term_ja": "さくら", "term_en": "Sakura", "note": "name"},'
        '{"term_ja": "先輩", "term_en": "senpai", "note": "honorific"}]}'
    )
    client = _FakeGeminiClient(_response(body))

    result = gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT)

    assert result.lines == {1: "Sakura!"}
    assert result.proposed_terms == parse_terms_text(body)
    assert result.proposed_terms == (
        ProposedTerm("さくら", "Sakura", "name"),
        ProposedTerm("先輩", "senpai", "honorific"),
    )


def test_a_response_with_no_glossary_proposes_nothing(gemini: ModuleType) -> None:
    client = _FakeGeminiClient(_response(_body("well-formed")))

    assert gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT).proposed_terms == ()


# -- AC-4: usage ---------------------------------------------------------------

#: AC-4's fixture: P=3200 prompt tokens of which C=700 cached, K=450 candidate
#: tokens and T=1300 thinking tokens - C > 0 and T > 0 so both named mistakes
#: change the numbers. Expected (V-4: P includes C; thinking bills as output):
#: input 3200 - 700 = 2500, output 450 + 1300 = 1750, cache_read 700,
#: cache_write 0. The same usage `test_rates.py` prices by hand (26,140 µ$).
_P, _C, _K, _T = 3200, 700, 450, 1300
_AC4_USAGE = TokenUsage(
    input_tokens=2500, output_tokens=1750, cache_read_tokens=700, cache_write_tokens=0
)


def test_usage_subtracts_the_cached_tokens_from_input_and_adds_thinking_to_output(
    gemini: ModuleType,
) -> None:
    """AC-4. Control values for the two mistakes it names:
    forgetting T gives output 450 (not 1750); not subtracting C gives input
    3200 (not 2500) - cached tokens billed twice."""
    usage = gemini._usage_of(
        SimpleNamespace(
            prompt_token_count=_P,
            cached_content_token_count=_C,
            candidates_token_count=_K,
            thoughts_token_count=_T,
            total_token_count=_P + _K + _T,
        )
    )

    assert usage == _AC4_USAGE
    assert type(usage) is TokenUsage


@pytest.mark.parametrize(
    ("cached", "thoughts", "expected"),
    [
        (None, None, TokenUsage(1000, 200, 0, 0)),
        (None, 300, TokenUsage(1000, 500, 0, 0)),
        (400, None, TokenUsage(600, 200, 400, 0)),
    ],
    ids=["neither", "no-cache", "no-thinking"],
)
def test_an_absent_cached_or_thinking_count_counts_as_zero(
    gemini: ModuleType, cached: int | None, thoughts: int | None, expected: TokenUsage
) -> None:
    """AC-4's second clause: `None` for C or T is 0 (V-4: every field is
    `Optional[int]`), never a `TypeError` and never a `None` on the ledger."""
    usage = gemini._usage_of(
        _usage_metadata(prompt=1000, cached=cached, candidates=200, thoughts=thoughts)
    )

    assert usage == expected


def test_translate_page_carries_the_converted_usage_and_the_responses_own_identity(
    gemini: ModuleType,
) -> None:
    """AC-4 through `translate_page`, and C-1's `CallInfo`: the response's
    `response_id` and **reported** `model_version`, not `MODEL_ID`."""
    client = _FakeGeminiClient(
        _response(_body("well-formed"), usage=_usage_metadata(_P, _C, _K, _T))
    )

    result = gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT)

    assert result.usage == _AC4_USAGE
    assert result.call == CallInfo(request_id=_RESPONSE_ID, model_id=_REPORTED_MODEL)


def test_usage_metadata_that_is_missing_entirely_raises_rather_than_counting_zero(
    gemini: ModuleType,
) -> None:
    """R-1. A response with no `usage_metadata` at all is not a free call:
    pricing it as `TokenUsage(0, 0, 0, 0)` spends money and reports none - the
    failure `domain.rates` calls its worst. Distinct from AC-4's absent C or T,
    which ARE zero."""
    with pytest.raises(ValueError, match="no usage"):
        gemini._usage_of(None)


def test_a_page_whose_response_reports_no_usage_raises_instead_of_pricing_it_at_nothing(
    gemini: ModuleType,
) -> None:
    """R-1 through `translate_page`: the guard holds where the cost is
    recorded, so no zero-priced `TranslationResult` ever reaches the ledger."""
    response = _response(_body("well-formed"))
    response.usage_metadata = None
    client = _FakeGeminiClient(response)

    with pytest.raises(ValueError, match="no usage"):
        gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT)

    assert client.calls == 1


def test_a_response_with_no_id_records_an_empty_request_id(gemini: ModuleType) -> None:
    """V-4: `response_id` is `Optional[str]`, and `CallInfo.request_id` is a
    required `str` - `None` becomes `""`."""
    client = _FakeGeminiClient(_response(_body("well-formed"), response_id=None))

    result = gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT)

    assert result.call == CallInfo(request_id="", model_id=_REPORTED_MODEL)


def test_the_result_carries_plain_domain_values_and_no_sdk_objects(gemini: ModuleType) -> None:
    client = _FakeGeminiClient(_response(_body("well-formed")))

    result = gemini.translate_page(client, _page(), _OCR_RESULTS, EMPTY_CONTEXT)

    assert type(result) is TranslationResult
    assert type(result.usage) is TokenUsage
    assert type(result.call) is CallInfo
    assert all(type(key) is int and type(value) is str for key, value in result.lines.items())


# -- AC-5: a page of wordless art makes no call --------------------------------


def test_a_page_whose_every_region_read_empty_makes_no_call_and_costs_nothing(
    gemini: ModuleType,
) -> None:
    """AC-5 (MT-011 AC-7's guard): no call, and exactly
    `TranslationResult({}, TokenUsage(0,0,0,0), call=None, proposed_terms=())`."""
    client = _FakeGeminiClient(explode=True)

    result = gemini.translate_page(client, _page(), _ALL_EMPTY, EMPTY_CONTEXT)

    assert client.calls == 0, f"{client.calls} call(s) made for a page with no text"
    assert result == TranslationResult(
        lines={}, usage=TokenUsage(0, 0, 0, 0), call=None, proposed_terms=()
    )


def test_a_page_with_no_regions_at_all_makes_no_call_either(gemini: ModuleType) -> None:
    client = _FakeGeminiClient(explode=True)

    assert gemini.translate_page(client, _page(), (), _CONTEXT).call is None
    assert client.calls == 0


def test_a_page_where_only_some_regions_read_empty_is_still_sent(gemini: ModuleType) -> None:
    """AC-5's negative control: the guard is `all`, not `any`. Without this, an
    adapter that never called anything would pass both tests above."""
    client = _FakeGeminiClient(_response('{"1": "...I see."}'))
    mixed = (
        OcrResult(text="", ocr_empty=True),
        _OCR_RESULTS[1],
        OcrResult(text="", ocr_empty=True),
    )

    result = gemini.translate_page(client, _page(), mixed, EMPTY_CONTEXT)

    assert client.calls == 1
    assert result.lines == {1: "...I see."}
