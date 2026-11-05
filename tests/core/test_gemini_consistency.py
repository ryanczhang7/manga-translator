"""`mangatl.translate.gemini.run_consistency`: one consistency-pass chunk on
Gemini, and the domain values it returns.

MT-114. Covers **AC-5** (one text-only request, its config, the raw text, the
usage and the call identity) and the Contract's three new frozen dataclasses
in `domain/correction.py` (`ProposedCorrection`, `ParsedCorrections`,
`ConsistencyResult`).

**Oracle partition: entirely mechanical.** Every figure is the Contract's or
an existing module's: `MODEL_ID`, the four-count usage mapping
(`gemini._usage_of`, the one implementation), and the constants in
`translate.consistency`.

**The fake client is `test_gemini_glossary_pass.py`'s**, copied rather than
invented: `client.models.generate_content(**kwargs)` recorded per call, a
`SimpleNamespace` response with `text`, `usage_metadata`, `model_version` and
`response_id`. The thinking level compares to `"MEDIUM"`, which
`types.ThinkingLevel.MEDIUM` (a `str` enum) equals.

**Imported per test** (`gemini`, `cp` and the dataclass fixtures): in RED
`translate.consistency`, `run_consistency` and the three dataclasses do not
exist, and a top-level import would be a collection error taking
`tests/core tests/ui` dark.

**What this file cannot catch.** A config kwarg the real SDK spells
differently passes every duck here; the story has no live test (PO-3).

**Timing.** No per-test timeout. The largest input is one ~540 kB string.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import FrozenInstanceError, fields
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from mangatl.domain.glossary import estimate_tokens
from mangatl.domain.translation import CallInfo, TokenUsage


@pytest.fixture
def gemini() -> ModuleType:
    from mangatl.translate import gemini as module

    return module


@pytest.fixture
def cp() -> ModuleType:
    from mangatl.translate import consistency as module

    return module


@pytest.fixture
def consistency_result() -> type:
    from mangatl.domain.correction import ConsistencyResult

    return ConsistencyResult


@pytest.fixture
def proposed() -> type:
    from mangatl.domain.correction import ProposedCorrection

    return ProposedCorrection


@pytest.fixture
def parsed() -> type:
    from mangatl.domain.correction import ParsedCorrections

    return ParsedCorrections


# -- the chunk and the answer ----------------------------------------------------

#: A chunk as `consistency_text` renders one (AC-1), but `run_consistency`
#: takes it as given: the request must carry exactly this string.
_CHUNK = (
    "Glossary:\nさくら = Sakura (name)"
    "\n\n"
    "Page 1:\n[0] さくら先輩!\n    Sakura-senpai!"
    "\n\n"
    "Page 2:\n[0] 行くぞ\n    Let's go."
)

_BODY = (
    '{"corrections": ['
    '{"page": 2, "reading_index": 0, "corrected_en": "Let\'s go!",'
    ' "reason": "tone matches page 1"}]}'
)

# -- the fake client and response (test_gemini_glossary_pass.py's) --------------

#: Distinct from `gemini.MODEL_ID`: AC-5 wants the model the response REPORTS.
_REPORTED_MODEL = "gemini-3.1-pro-preview-reported-by-the-response"
_RESPONSE_ID = "gemini-consistency-response-fake"

#: Four distinct non-zero counts, so every swap and every forgotten term moves a
#: number: P=5000 prompt of which C=1200 cached, K=900 candidates, T=2100
#: thinking. Mapped as `translate_page` maps them: input P - C = 3800, output
#: K + T = 3000, cache_read C = 1200, cache_write 0.
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
    body: str | None = _BODY,
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


class _FakeModels:
    def __init__(self, responses: Sequence[object]) -> None:
        self._responses = list(responses)
        self.seen: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> object:
        self.seen.append(kwargs)
        return self._responses[len(self.seen) - 1]


class _FakeGeminiClient:
    def __init__(self, *responses: object) -> None:
        self.models = _FakeModels(responses)

    @property
    def calls(self) -> int:
        return len(self.models.seen)


def _sent(gemini: ModuleType, chunk: str = _CHUNK) -> dict[str, Any]:
    """The kwargs of the one call `run_consistency` made for `chunk`."""
    client = _FakeGeminiClient(_response(), _response())
    gemini.run_consistency(client, chunk)
    assert client.calls == 1, f"{client.calls} calls for one chunk"
    return client.models.seen[0]


# -- AC-5: the request ------------------------------------------------------------


def test_one_chunk_makes_exactly_one_generate_content_call(gemini: ModuleType) -> None:
    """AC-5: one call per chunk, no retry."""
    client = _FakeGeminiClient(_response(), _response(), _response())

    gemini.run_consistency(client, _CHUNK)

    assert client.calls == 1, f"{client.calls} calls for one chunk"


def test_the_request_is_exactly_model_contents_and_config_on_the_page_model(
    gemini: ModuleType,
) -> None:
    """AC-5: `model == MODEL_ID`, and the kwargs are exactly those three."""
    request = _sent(gemini)

    assert set(request) == {"model", "contents", "config"}, sorted(request)
    assert request["model"] == gemini.MODEL_ID


def test_the_contents_are_the_chunk_text_alone_with_no_image_part(gemini: ModuleType) -> None:
    """AC-5: `contents == [chunk_text]` - a one-element list holding the plain
    `str`. A page image beside it makes the list two long; a `Part` in place
    of the string is not equal to it and is not a `str`."""
    request = _sent(gemini)

    assert request["contents"] == [_CHUNK]
    assert type(request["contents"]) is list
    assert type(request["contents"][0]) is str


def test_the_contents_follow_the_chunk_passed_in(gemini: ModuleType) -> None:
    """The control for the test above: a different chunk, different contents
    - so a constant or cached text cannot pass."""
    other = "Page 7:\n[3] 別の巻\n    Another volume"

    assert _sent(gemini, other)["contents"] == [other]


def test_the_system_instruction_is_the_consistency_prompt_and_not_in_the_contents(
    gemini: ModuleType, cp: ModuleType
) -> None:
    """AC-5: `system_instruction == CONSISTENCY_PROMPT`, and only there."""
    request = _sent(gemini)

    assert request["config"].system_instruction == cp.CONSISTENCY_PROMPT
    assert cp.CONSISTENCY_PROMPT not in request["contents"]
    assert all(cp.CONSISTENCY_PROMPT not in part for part in request["contents"])


def test_the_request_asks_for_json_against_the_corrections_schema(
    gemini: ModuleType, cp: ModuleType
) -> None:
    """AC-5: `response_mime_type="application/json"` and
    `response_json_schema == CORRECTIONS_SCHEMA`, `response_schema` unset
    (the SDK refuses both at once, MT-080 V-3)."""
    config = _sent(gemini)["config"]

    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == cp.CORRECTIONS_SCHEMA
    assert getattr(config, "response_schema", None) is None


def test_thinking_runs_at_medium_and_the_output_is_capped_at_the_pass_cap(
    gemini: ModuleType, cp: ModuleType
) -> None:
    """AC-5: `ThinkingLevel.MEDIUM` and `max_output_tokens ==
    CONSISTENCY_MAX_OUTPUT_TOKENS` (8,192) - not the page cap."""
    config = _sent(gemini)["config"]

    assert config.thinking_config.thinking_level == "MEDIUM"
    assert config.max_output_tokens == cp.CONSISTENCY_MAX_OUTPUT_TOKENS == 8_192
    assert config.max_output_tokens != gemini.MAX_OUTPUT_TOKENS


def test_a_chunk_over_the_input_limit_is_still_sent_as_given(
    gemini: ModuleType, cp: ModuleType
) -> None:
    """The Contract: `run_consistency` performs no input-limit check -
    `chunk_pages` owns the limit, and a chunk is sent as given. 540,003 ASCII
    bytes estimate to 180,001 tokens: one call, no exception."""
    chunk = "a" * (3 * cp.CONSISTENCY_MAX_INPUT_TOKENS + 3)
    assert estimate_tokens(chunk) == 180_001
    client = _FakeGeminiClient(_response())

    gemini.run_consistency(client, chunk)

    assert client.calls == 1
    assert client.models.seen[0]["contents"] == [chunk]


# -- AC-5: the result -------------------------------------------------------------


def test_the_result_is_a_consistency_result_carrying_the_raw_text(
    gemini: ModuleType, consistency_result: type
) -> None:
    """AC-5: `text` is `response.text`, unparsed."""
    result = gemini.run_consistency(_FakeGeminiClient(_response()), _CHUNK)

    assert type(result) is consistency_result
    assert result.text == _BODY
    assert type(result.text) is str


def test_the_text_is_not_parsed_so_a_malformed_body_still_comes_back(gemini: ModuleType) -> None:
    """The Contract: raw, unparsed - MT-115 parses it and may want the body on
    a parse failure. A body that is not JSON must not raise here."""
    body = '{"corrections": [ this is not json'

    result = gemini.run_consistency(_FakeGeminiClient(_response(body)), _CHUNK)

    assert result.text == body


def test_a_response_with_no_text_is_the_empty_string(gemini: ModuleType) -> None:
    """The Contract: `text` is `response.text or ""`."""
    result = gemini.run_consistency(_FakeGeminiClient(_response(None)), _CHUNK)

    assert result.text == ""


def test_the_usage_maps_the_four_counts_as_translate_page_does(gemini: ModuleType) -> None:
    """AC-5: thinking added to output, cached subtracted from input,
    cache_write 0. Controls: forgetting T gives output 900; not subtracting C
    gives input 5000; swapping input/output gives (3000, 3800, ...)."""
    result = gemini.run_consistency(_FakeGeminiClient(_response()), _CHUNK)

    assert result.usage == _USAGE
    assert result.usage == gemini._usage_of(_usage_metadata())
    assert type(result.usage) is TokenUsage


def test_a_response_that_reports_no_usage_raises_rather_than_pricing_the_chunk_at_nothing(
    gemini: ModuleType,
) -> None:
    """`_usage_of`'s guard holds here too."""
    response = _response()
    response.usage_metadata = None

    with pytest.raises(ValueError, match="no usage"):
        gemini.run_consistency(_FakeGeminiClient(response), _CHUNK)


def test_the_call_is_the_model_the_response_reports_and_its_response_id(
    gemini: ModuleType,
) -> None:
    """AC-5: `CallInfo(response_id, model_version)` - the model the response
    reports, not the requested `MODEL_ID`."""
    result = gemini.run_consistency(_FakeGeminiClient(_response()), _CHUNK)

    assert result.call == CallInfo(request_id=_RESPONSE_ID, model_id=_REPORTED_MODEL)
    assert result.call.model_id != gemini.MODEL_ID
    assert type(result.call) is CallInfo


def test_a_response_without_identity_falls_back_as_propose_glossary_does(
    gemini: ModuleType,
) -> None:
    """The Contract: `CallInfo(response.response_id or "",
    response.model_version or MODEL_ID)`."""
    response = _response(response_id=None, model_version=None)

    result = gemini.run_consistency(_FakeGeminiClient(response), _CHUNK)

    assert result.call == CallInfo(request_id="", model_id=gemini.MODEL_ID)


# -- the prompt ---------------------------------------------------------------------


def test_the_prompt_asks_for_only_the_lines_the_model_would_change(cp: ModuleType) -> None:
    """The Contract's gloss: "return only lines you would change". The wording
    is not pinned beyond that - two words, case-insensitive."""
    prompt = cp.CONSISTENCY_PROMPT

    assert isinstance(prompt, str) and prompt.strip()
    assert "only" in prompt.lower(), prompt
    assert "change" in prompt.lower(), prompt


def test_the_prompt_fits_the_headroom_the_input_limit_leaves_under_the_200k_tier(
    cp: ModuleType,
) -> None:
    """The Contract's `CONSISTENCY_MAX_INPUT_TOKENS` comment: 20k headroom for
    the system prompt, as MT-104. A chunk at the limit plus the prompt must
    stay at or under 200,000 estimated tokens."""
    assert estimate_tokens(cp.CONSISTENCY_PROMPT) + cp.CONSISTENCY_MAX_INPUT_TOKENS <= 200_000


# -- the domain values (domain/correction.py) ---------------------------------------


def test_proposed_correction_is_a_frozen_value_of_ordinal_index_english_and_reason(
    proposed: type,
) -> None:
    """The Contract's `ProposedCorrection`: four fields in that order, frozen."""
    correction = proposed(page_ordinal=1, reading_index=0, corrected_en="Hi", reason="r")

    assert [field.name for field in fields(correction)] == [
        "page_ordinal",
        "reading_index",
        "corrected_en",
        "reason",
    ]
    assert correction == proposed(1, 0, "Hi", "r")
    with pytest.raises(FrozenInstanceError):
        correction.corrected_en = "Hello"


def test_parsed_corrections_is_a_frozen_value_of_corrections_and_the_unchanged_count(
    parsed: type, proposed: type
) -> None:
    corrections = (proposed(0, 2, "Wait!", "r"),)
    value = parsed(corrections=corrections, unchanged_returned=3)

    assert [field.name for field in fields(value)] == ["corrections", "unchanged_returned"]
    assert value == parsed(corrections, 3)
    with pytest.raises(FrozenInstanceError):
        value.unchanged_returned = 0


def test_consistency_result_is_a_frozen_value_of_text_usage_and_call(
    consistency_result: type,
) -> None:
    result = consistency_result(text="{}", usage=_USAGE, call=CallInfo("r", "m"))

    assert [field.name for field in fields(result)] == ["text", "usage", "call"]
    assert result == consistency_result("{}", _USAGE, CallInfo(request_id="r", model_id="m"))
    with pytest.raises(FrozenInstanceError):
        result.text = ""


def test_the_new_values_are_exported_beside_correction() -> None:
    """The Contract: the additions live in `domain/correction.py`, beside
    `Correction`, and the module's `__all__` names them."""
    from mangatl.domain import correction

    assert {"Correction", "ProposedCorrection", "ParsedCorrections", "ConsistencyResult"} <= set(
        correction.__all__
    )
