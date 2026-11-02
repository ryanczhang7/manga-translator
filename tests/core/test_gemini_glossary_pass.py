"""`mangatl.translate.gemini.propose_glossary`: the glossary pre-pass on Gemini.

MT-104. Covers **AC-3** (one text-only request, its config, the parse, the
usage and the call identity) and **AC-4** through the adapter (an over-limit
volume is refused before the client is touched; a volume exactly at the limit
is sent).

**Oracle partition: entirely mechanical.** Every figure is the Contract's or
an existing module's: `MODEL_ID`, the four-count usage mapping `translate_page`
uses (`gemini._usage_of`, PO-1: one implementation, not two), and the limit in
`glossary_pass`.

**The fake client is `test_translate_gemini.py`'s**, copied rather than
invented: `client.models.generate_content(**kwargs)` recorded per call, a
`SimpleNamespace` response with `text`, `usage_metadata`, `model_version` and
`response_id`. What the request carries is read **by attribute**; the
thinking level compares to `"MEDIUM"`, which `types.ThinkingLevel.MEDIUM` (a
`str` enum) equals.

**`contents` is pinned by list equality to `[glossary_pass_text(pages)]`** -
one element, a plain `str`. That is what makes DV-1 (the first page's image
part put back, `build_request`'s shape) fail here: a second element, or a
`types.Part` in place of the string, breaks the equality.

**Imported per test** (`gemini`, `gp` and `translation` fixtures): in RED
`glossary_pass`, `propose_glossary` and `GlossaryProposal` do not exist, and a
top-level import would be a collection error taking `tests/core tests/ui` dark.

**What this file cannot catch.** A config kwarg the real SDK spells
differently passes every duck here; the live test is the only place that
fails, and the pre-pass has none in this story (`integration` is optional).

**Timing.** No per-test timeout. The two boundary volumes are ~540 kB strings.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import FrozenInstanceError, fields
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from mangatl.domain.glossary import ProposedTerm, estimate_tokens
from mangatl.domain.line import OcrResult
from mangatl.domain.translation import CallInfo, TokenUsage


@pytest.fixture
def gemini() -> ModuleType:
    from mangatl.translate import gemini as module

    return module


@pytest.fixture
def gp() -> ModuleType:
    from mangatl.translate import glossary_pass as module

    return module


@pytest.fixture
def glossary_proposal() -> type:
    from mangatl.domain.translation import GlossaryProposal

    return GlossaryProposal


# -- the volume -------------------------------------------------------------------

_EMPTY = OcrResult(text="", ocr_empty=True)

_PAGES: tuple[tuple[OcrResult, ...], ...] = (
    (OcrResult("さくら先輩!"), _EMPTY),
    (_EMPTY, _EMPTY),
    (OcrResult("東京駅で会おう"), OcrResult("行くぞ、田中くん")),
)

_BODY = (
    '{"glossary": ['
    '{"term_ja": "さくら", "term_en": "Sakura", "note": "name"},'
    '{"term_ja": "東京駅", "term_en": "Tokyo Station", "note": "place"},'
    '{"term_ja": "先輩", "term_en": "senpai", "note": "honorific"}]}'
)

_TERMS = (
    ProposedTerm("さくら", "Sakura", "name"),
    ProposedTerm("東京駅", "Tokyo Station", "place"),
    ProposedTerm("先輩", "senpai", "honorific"),
)

# -- the fake client and response (test_translate_gemini.py's) --------------------

#: Distinct from `gemini.MODEL_ID`: AC-3 wants the model the response REPORTS.
_REPORTED_MODEL = "gemini-3.1-pro-preview-reported-by-the-response"
_RESPONSE_ID = "gemini-glossary-pass-response-fake"

#: Four distinct non-zero counts, so every swap and every forgotten term moves a
#: number: P=5000 prompt of which C=1200 cached, K=900 candidates, T=2100
#: thinking. Mapped as `translate_page` maps them (V-4): input P - C = 3800,
#: output K + T = 3000, cache_read C = 1200, cache_write 0.
_P, _C, _K, _T = 5000, 1200, 900, 2100
_USAGE = TokenUsage(
    input_tokens=3800, output_tokens=3000, cache_read_tokens=1200, cache_write_tokens=0
)


def _usage_metadata(
    prompt: int | None = _P,
    cached: int | None = _C,
    candidates: int | None = _K,
    thoughts: int | None = _T,
) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=prompt,
        cached_content_token_count=cached,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        total_token_count=None,
    )


def _response(
    body: str = _BODY,
    *,
    usage: SimpleNamespace | None = None,
    response_id: str | None = _RESPONSE_ID,
    model_version: str | None = _REPORTED_MODEL,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=body,
        usage_metadata=usage if usage is not None else _usage_metadata(),
        model_version=model_version,
        response_id=response_id,
        candidates=[SimpleNamespace(finish_reason="STOP")],
    )


class _ClientExploded(Exception):
    """A call nobody should have made."""


class _FakeModels:
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
    def __init__(self, *responses: object, explode: bool = False) -> None:
        self.models = _FakeModels(responses, explode=explode)

    @property
    def calls(self) -> int:
        return len(self.models.seen)


def _sent(gemini: ModuleType, pages: Sequence[Sequence[OcrResult]] = _PAGES) -> dict[str, Any]:
    """The kwargs of the one call `propose_glossary` made for `pages`."""
    client = _FakeGeminiClient(_response(), _response())
    gemini.propose_glossary(client, pages)
    assert client.calls == 1, f"{client.calls} calls for one volume"
    return client.models.seen[0]


# -- AC-3: the request --------------------------------------------------------------


def test_one_volume_makes_exactly_one_generate_content_call(gemini: ModuleType) -> None:
    """AC-3: one call for the whole volume - not one per page (three pages
    here, one of them art)."""
    client = _FakeGeminiClient(_response(), _response(), _response())

    gemini.propose_glossary(client, _PAGES)

    assert client.calls == 1, f"{client.calls} calls for one volume"


def test_the_request_is_exactly_model_contents_and_config_on_the_page_model(
    gemini: ModuleType,
) -> None:
    """AC-3: `model == MODEL_ID`, and the kwargs are exactly the three
    `generate_content` takes (keyword-only: a stray key is a `TypeError`)."""
    request = _sent(gemini)

    assert set(request) == {"model", "contents", "config"}, sorted(request)
    assert request["model"] == gemini.MODEL_ID


def test_the_contents_are_the_volume_listing_alone_with_no_image_part(
    gemini: ModuleType, gp: ModuleType
) -> None:
    """AC-3 and DV-1: `contents == [glossary_pass_text(pages)]` - one plain
    string. The first page's image beside it (`build_request`'s shape) makes
    this list two long; a `Part` in place of the string is not equal to it."""
    request = _sent(gemini)

    assert request["contents"] == [gp.glossary_pass_text(_PAGES)]
    assert type(request["contents"]) is list
    assert type(request["contents"][0]) is str


def test_the_contents_follow_the_pages_passed_in(gemini: ModuleType, gp: ModuleType) -> None:
    """The control for the test above: a different volume, a different
    listing - so a constant or cached listing cannot pass it."""
    other = ((OcrResult("別の巻"),),)

    assert _sent(gemini, other)["contents"] == [gp.glossary_pass_text(other)] == ["Page 1:\n別の巻"]


def test_the_system_instruction_is_the_pass_prompt_and_not_in_the_contents(
    gemini: ModuleType, gp: ModuleType
) -> None:
    """AC-3: `system_instruction == GLOSSARY_PASS_PROMPT` - the pass's prompt,
    not the page's - and only there."""
    request = _sent(gemini)

    assert request["config"].system_instruction == gp.GLOSSARY_PASS_PROMPT
    assert gp.GLOSSARY_PASS_PROMPT not in request["contents"]


def test_the_request_asks_for_json_against_the_pass_schema(
    gemini: ModuleType, gp: ModuleType
) -> None:
    """AC-3: `response_mime_type="application/json"` and
    `response_json_schema == GLOSSARY_PASS_SCHEMA`, with `response_schema`
    left unset (the SDK refuses both at once, MT-080 V-3)."""
    config = _sent(gemini)["config"]

    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == gp.GLOSSARY_PASS_SCHEMA
    assert getattr(config, "response_schema", None) is None


def test_thinking_runs_at_medium_and_the_output_is_capped_at_the_pass_cap(
    gemini: ModuleType, gp: ModuleType
) -> None:
    """AC-3: `ThinkingLevel.MEDIUM` and `max_output_tokens ==
    GLOSSARY_PASS_MAX_OUTPUT_TOKENS` (8,192) - not the page cap of 4,096."""
    config = _sent(gemini)["config"]

    assert config.thinking_config.thinking_level == "MEDIUM"
    assert config.max_output_tokens == gp.GLOSSARY_PASS_MAX_OUTPUT_TOKENS == 8_192
    assert config.max_output_tokens != gemini.MAX_OUTPUT_TOKENS


# -- AC-3: the result ---------------------------------------------------------------


def test_the_result_is_a_glossary_proposal_of_the_parsed_terms(
    gemini: ModuleType, gp: ModuleType, glossary_proposal: type
) -> None:
    """AC-3: `terms` is `parse_glossary_pass(response.text)`, in order."""
    client = _FakeGeminiClient(_response())

    proposal = gemini.propose_glossary(client, _PAGES)

    assert type(proposal) is glossary_proposal
    assert proposal.terms == gp.parse_glossary_pass(_BODY) == _TERMS


def test_the_usage_maps_the_four_counts_as_translate_page_does(gemini: ModuleType) -> None:
    """AC-3 and PO-1: thinking added to output, cached subtracted from input,
    cache_write 0. Controls: forgetting T gives output 900; not subtracting C
    gives input 5000; swapping input/output gives (3000, 3800, ...)."""
    client = _FakeGeminiClient(_response())

    proposal = gemini.propose_glossary(client, _PAGES)

    assert proposal.usage == _USAGE
    assert proposal.usage == gemini._usage_of(_usage_metadata())
    assert type(proposal.usage) is TokenUsage


def test_a_response_that_reports_no_usage_raises_rather_than_pricing_the_pass_at_nothing(
    gemini: ModuleType,
) -> None:
    """PO-1's "same helper": `_usage_of`'s guard holds here too - a paid
    volume-sized call reported as free is `domain.rates`' worst failure."""
    response = _response()
    response.usage_metadata = None
    client = _FakeGeminiClient(response)

    with pytest.raises(ValueError, match="no usage"):
        gemini.propose_glossary(client, _PAGES)


def test_the_call_is_the_model_the_response_reports_and_its_response_id(
    gemini: ModuleType,
) -> None:
    """AC-3: `call.model_id == response.model_version` (the ledger reconciles
    against the bill), not the requested `MODEL_ID`; `request_id` is the
    response's id, as `translate_page` records it."""
    client = _FakeGeminiClient(_response())

    proposal = gemini.propose_glossary(client, _PAGES)

    assert proposal.call == CallInfo(request_id=_RESPONSE_ID, model_id=_REPORTED_MODEL)
    assert proposal.call.model_id != gemini.MODEL_ID
    assert type(proposal.call) is CallInfo


def test_glossary_proposal_is_a_frozen_value_of_terms_usage_and_call(
    glossary_proposal: type,
) -> None:
    """The Contract's `GlossaryProposal`: three fields in that order, frozen."""
    proposal = glossary_proposal(
        terms=_TERMS, usage=_USAGE, call=CallInfo(request_id="r", model_id="m")
    )

    assert [field.name for field in fields(proposal)] == ["terms", "usage", "call"]
    assert proposal == glossary_proposal(_TERMS, _USAGE, CallInfo("r", "m"))
    with pytest.raises(FrozenInstanceError):
        proposal.terms = ()


# -- AC-4: the input limit, checked before the call ---------------------------------

#: `"Page 1:\n"` is 8 bytes; `estimate_tokens` is `ceil(bytes / 3)`. So one
#: line of `3 * limit - 8` ASCII bytes estimates to exactly `limit`, and one
#: more byte to `limit + 1` (checked in `test_glossary_pass.py` and below).
_HEADER_BYTES = len(b"Page 1:\n")


def _pages_estimating_to(tokens: int, *, extra_bytes: int = 0) -> tuple[tuple[OcrResult, ...]]:
    return ((OcrResult("a" * (3 * tokens - _HEADER_BYTES + extra_bytes)),),)


def test_a_volume_over_the_input_limit_is_refused_naming_the_estimate_and_the_limit(
    gemini: ModuleType, gp: ModuleType
) -> None:
    """AC-4: an estimate of 180,001 against 180,000 raises `VolumeTooLarge`
    whose message carries both numbers (plain or comma-grouped), and the
    client is never touched - the guard runs before the call."""
    limit = gp.GLOSSARY_PASS_MAX_INPUT_TOKENS
    pages = _pages_estimating_to(limit, extra_bytes=1)
    assert estimate_tokens(gp.glossary_pass_text(pages)) == 180_001
    client = _FakeGeminiClient(explode=True)

    with pytest.raises(gp.VolumeTooLarge) as raised:
        gemini.propose_glossary(client, pages)

    message = str(raised.value)
    assert client.calls == 0, f"{client.calls} call(s) made for a refused volume"
    assert re.search(r"\b180,?001\b", message), message
    assert re.search(r"\b180,?000\b", message), message


def test_a_volume_far_over_the_limit_names_its_own_estimate(
    gemini: ModuleType, gp: ModuleType
) -> None:
    """The control for the message: a different estimate (250,000), a
    different number in the message - so a message that printed the limit
    twice, or a constant, fails."""
    pages = _pages_estimating_to(250_000)
    client = _FakeGeminiClient(explode=True)

    with pytest.raises(gp.VolumeTooLarge, match=r"\b250,?000\b"):
        gemini.propose_glossary(client, pages)

    assert client.calls == 0


def test_a_volume_exactly_at_the_input_limit_is_sent(gemini: ModuleType, gp: ModuleType) -> None:
    """AC-4's boundary control: an estimate of exactly 180,000 is **not** over
    the limit - the check is `>`, inclusive of the limit - and is sent as the
    listing, in one call."""
    limit = gp.GLOSSARY_PASS_MAX_INPUT_TOKENS
    pages = _pages_estimating_to(limit)
    assert estimate_tokens(gp.glossary_pass_text(pages)) == limit == 180_000
    client = _FakeGeminiClient(_response())

    proposal = gemini.propose_glossary(client, pages)

    assert client.calls == 1
    assert client.models.seen[0]["contents"] == [gp.glossary_pass_text(pages)]
    assert proposal.terms == _TERMS
