"""`mangatl.translate.gemini_batch`: build, submit, poll and collect one batch.

MT-110. Covers **AC-1** to **AC-5**. Every criterion is mechanical: each value
asserted here is read out of the story's `## Contract`, MT-101 D-5..D-8 and the
verbatim D-14 fixture, never re-derived from the module under test.

**The module under test is imported inside each test, through `batch`**
(the `test_translate_gemini.py` pattern): in RED it does not exist, and a
top-level import would be a collection error that takes the whole
`tests/core tests/ui` session dark. Imported here, each test fails on the named
absence and the rest of the suite still runs.

**Real SDK types where they carry the data, ducks where they would eat it.**
Checked against the installed `google-genai` 2.29.0 in RED (2026-11-03):

- `types.InlinedRequest` and `types.CreateBatchJobConfig` compare by field
  (pydantic `==`), so AC-1 and AC-2 compare against real instances.
- `types.InlinedResponse(response=SimpleNamespace(...))` does **not** refuse a
  duck: pydantic silently coerces it to an empty `GenerateContentResponse()`,
  dropping `text`, `usage_metadata` and `model_version`. So an item is either
  a real `InlinedResponse` wrapping a real `GenerateContentResponse` (whose
  `.text` is the SDK's own property over `candidates[0].content.parts`), or -
  only where a sentinel has to survive (AC-5) - a plain `SimpleNamespace`.

**What the expected values are.** The usage figures, the parsed lines, the
proposed terms and the error messages are written out literally below, not
computed by calling `_usage_of` / `parse_lines_text` on the same inputs: a
collector that forgot thinking tokens, or paired by position, has to disagree
with a number a human wrote down.

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so no
budget to size. The only non-trivial cost is `prepare_page_image` on three
96x96 PNGs (AC-1), a few ms each.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Sequence
from functools import cache
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types
from PIL import Image

from mangatl.domain.glossary import EMPTY_CONTEXT, PromptContext, ProposedTerm
from mangatl.domain.line import OcrResult
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.translate.gemini import MODEL_ID, build_request
from mangatl.translate.parse import parse_terms_text

# -- the module under test -----------------------------------------------------


class _LazyModule:
    """`mangatl.translate.gemini_batch`, imported on the first attribute read.

    The import happens inside the test body rather than in fixture setup, so a
    missing module or a missing name is a FAILED test naming it, not a setup
    ERROR that reads like a broken fixture.
    """

    def __getattr__(self, name: str) -> Any:
        module = importlib.import_module("mangatl.translate.gemini_batch")
        return getattr(module, name)


@pytest.fixture
def batch() -> Any:
    """The module under test, read lazily (see `_LazyModule`)."""
    return _LazyModule()


# -- pages ---------------------------------------------------------------------


@cache
def _png(rgb: tuple[int, int, int]) -> bytes:
    """A small solid PNG. A distinct colour per page, so two pages' capped
    JPEGs differ and a request built from the wrong page cannot compare equal."""
    image = Image.new("RGB", (96, 96), rgb)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


_OCR_0: tuple[OcrResult, ...] = (OcrResult(text="おい、急げ!"), OcrResult(text="翔、こっちだ!"))
_OCR_1: tuple[OcrResult, ...] = (OcrResult(text="待って……"),)
_OCR_2: tuple[OcrResult, ...] = (
    OcrResult(text="電車が出るぞ!"),
    OcrResult(text="", ocr_empty=True),
    OcrResult(text="走れ!"),
)
_OCR_EMPTY: tuple[OcrResult, ...] = (
    OcrResult(text="", ocr_empty=True),
    OcrResult(text="", ocr_empty=True),
)

_CONTEXT_0 = PromptContext(
    glossary_block="Glossary - use these renderings exactly:\n翔 = Kakeru (name)",
    rolling_block="",
)
_CONTEXT_2 = PromptContext(
    glossary_block="",
    rolling_block="Neighbouring pages, in reading order:\n電車が来た",
)


def _pages(batch: Any) -> list[Any]:
    """Three pages, ordinals 0, 1, 2, with 2, 1 and 3 regions respectively -
    different region counts, so a page parsed against another page's region
    range raises or answers differently."""
    return [
        batch.BatchPage(
            ordinal=0, page_image=_png((200, 30, 30)), ocr_results=_OCR_0, context=_CONTEXT_0
        ),
        batch.BatchPage(
            ordinal=1, page_image=_png((30, 200, 30)), ocr_results=_OCR_1, context=EMPTY_CONTEXT
        ),
        batch.BatchPage(
            ordinal=2, page_image=_png((30, 30, 200)), ocr_results=_OCR_2, context=_CONTEXT_2
        ),
    ]


# -- the fake client -----------------------------------------------------------

_JOB = "batches/abc"


class _ClientExploded(Exception):
    """The SDK's create-time failure (MT-101 D-4's 400), as the fake raises it."""


class _FakeModels:
    """`client.models`: nothing in a batch adapter may make an interactive call."""

    def generate_content(self, **kwargs: Any) -> object:
        raise AssertionError("the batch adapter made an interactive generate_content call")


class _FakeBatches:
    """`client.batches`. Records every call's kwargs."""

    def __init__(self, job: object, raises: BaseException | None) -> None:
        self._job = job
        self._raises = raises
        self.created: list[dict[str, Any]] = []
        self.got: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.created.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(name=_JOB)

    def get(self, **kwargs: Any) -> object:
        self.got.append(kwargs)
        return self._job


class _FakeGeminiClient:
    """Stands in for `google.genai.Client`. No credential, no network."""

    def __init__(self, job: object = None, *, raises: BaseException | None = None) -> None:
        self.batches = _FakeBatches(job, raises)
        self.models = _FakeModels()


# -- responses -----------------------------------------------------------------

#: Distinct from `MODEL_ID`: `CallInfo.model_id` must be what the response
#: REPORTS, and a fake reporting the request's own id could not tell them apart.
_REPORTED = "gemini-3.1-pro-preview-batch-reported"


def _usage(
    prompt: int | None, cached: int | None, candidates: int | None, thoughts: int | None
) -> types.GenerateContentResponseUsageMetadata:
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt,
        cached_content_token_count=cached,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
    )


def _answer(
    text: str,
    usage: types.GenerateContentResponseUsageMetadata | None,
    *,
    model_version: str | None = _REPORTED,
) -> types.GenerateContentResponse:
    """A real `GenerateContentResponse` whose `.text` is `text`. Its
    `response_id` is deliberately not the batch request id, so a collector
    that recorded `response_id` as `CallInfo.request_id` fails."""
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]))
        ],
        usage_metadata=usage,
        model_version=model_version,
        response_id="the-interactive-response-id-not-the-batch-one",
    )


def _item(key: str | None, response: types.GenerateContentResponse) -> types.InlinedResponse:
    return types.InlinedResponse(response=response, metadata=None if key is None else {"key": key})


def _job(
    items: Sequence[types.InlinedResponse],
    state: types.JobState = types.JobState.JOB_STATE_SUCCEEDED,
) -> types.BatchJob:
    return types.BatchJob(
        name=_JOB,
        state=state,
        dest=types.BatchJobDestination(inlined_responses=list(items)),
    )


# The three good answers. Page 0's keys are out of order and it carries one
# well-formed glossary term - which, since MT-106, it is not asked for and which
# reaches no result (AC-2's batch case); page 2 is sparse (region 1 omitted, it
# is `ocr_empty`).
_TEXT_0 = (
    '{"glossary": [{"term_ja": "翔", "term_en": "Kakeru", "note": "name"}],'
    ' "1": "Kakeru, over here!", "0": "Hey, hurry!"}'
)
_TEXT_1 = '{"0": "Wait up..."}'
_TEXT_2 = '{"2": "Run!", "0": "The train\'s about to leave!"}'

#: Page 0 reports non-zero thinking: P=1000, C=200, K=150, T=400.
_USAGE_0 = (1000, 200, 150, 400)
_USAGE_1 = (500, None, 40, None)
_USAGE_2 = (700, 0, 90, 10)


def _good_items() -> list[types.InlinedResponse]:
    return [
        _item("0", _answer(_TEXT_0, _usage(*_USAGE_0))),
        _item("1", _answer(_TEXT_1, _usage(*_USAGE_1))),
        _item("2", _answer(_TEXT_2, _usage(*_USAGE_2), model_version=None)),
    ]


#: Written out by hand. Usage is `input = P - C`, `output = K + T`,
#: `cache_read = C`, `cache_write = 0` (MT-101 D-7, MT-080 V-4). Page 0's
#: `proposed_terms` is `()` though `_TEXT_0` carries a glossary (MT-106 AC-2).
_EXPECTED_0 = TranslationResult(
    lines={0: "Hey, hurry!", 1: "Kakeru, over here!"},
    usage=TokenUsage(800, 550, 200, 0),
    call=CallInfo("batches/abc#0", _REPORTED),
    proposed_terms=(),
)
_EXPECTED_1 = TranslationResult(
    lines={0: "Wait up..."},
    usage=TokenUsage(500, 40, 0, 0),
    call=CallInfo("batches/abc#1", _REPORTED),
    proposed_terms=(),
)
_EXPECTED_2 = TranslationResult(
    lines={0: "The train's about to leave!", 2: "Run!"},
    usage=TokenUsage(700, 100, 0, 0),
    call=CallInfo("batches/abc#2", MODEL_ID),
    proposed_terms=(),
)

#: MT-101 D-14's probe response, verbatim from the story's `## Contract`: an
#: extra index key "3" and glossary items that are strings, not objects.
_D14_TEXT = """{
  "glossary": [
    "{\\"japanese\\": \\"翔\\", \\"english\\": \\"Kakeru\\", \\"type\\": \\"name\\"}"
  ],
  "0": "Hey, hurry!",
  "1": "Kakeru, over here!",
  "2": "Wait up...",
  "3": "The train's about to leave!"
}"""


def _number(n: int, message: str) -> bool:
    """`n` appears in `message` as a whole number, not as a digit of another."""
    return re.search(rf"(?<!\d){n}(?!\d)", message) is not None


# -- the module's surface ------------------------------------------------------


def test_the_module_exports_exactly_the_contracts_names(batch: Any) -> None:
    """Contract: `__all__` is the ten names the story lists, no more."""
    assert sorted(batch.__all__) == [
        "BatchItemError",
        "BatchNotFinished",
        "BatchPage",
        "BatchShapeError",
        "BatchStateName",
        "UnknownBatchState",
        "batch_state",
        "build_batch_requests",
        "collect_batch",
        "submit_batch",
    ]


# -- AC-1: build_batch_requests ------------------------------------------------


def test_each_page_becomes_an_inlined_request_carrying_build_requests_contents_and_config(
    batch: Any,
) -> None:
    """AC-1, MT-101 D-5: the per-request `contents` and `config` are the very
    ones `build_request` returns for that page; `model` is left unset (it goes
    on `batches.create`)."""
    pages = _pages(batch)

    requests = batch.build_batch_requests(pages)

    assert len(requests) == 3
    for request, page in zip(requests, pages, strict=True):
        expected = build_request(page.page_image, page.ocr_results, page.context)
        assert isinstance(request, types.InlinedRequest), type(request).__name__
        assert request.contents == expected["contents"], f"page {page.ordinal}'s contents differ"
        assert request.config == expected["config"], f"page {page.ordinal}'s config differs"
        assert request.model is None, request.model


def test_each_request_carries_its_pages_ordinal_as_the_metadata_key(batch: Any) -> None:
    """AC-1, MT-101 D-7: `metadata == {"key": str(ordinal)}` - the only thing
    a result can be paired back to its page by."""
    requests = batch.build_batch_requests(_pages(batch))

    assert [request.metadata for request in requests] == [{"key": "0"}, {"key": "1"}, {"key": "2"}]


def test_pages_given_out_of_order_come_back_sorted_by_ordinal(batch: Any) -> None:
    """AC-1: given 2, 0, 1 the requests are 0, 1, 2 - and each still carries
    its own page's contents, not the content of the page that was in its slot."""
    pages = _pages(batch)
    shuffled = [pages[2], pages[0], pages[1]]

    requests = batch.build_batch_requests(shuffled)

    assert [request.metadata for request in requests] == [{"key": "0"}, {"key": "1"}, {"key": "2"}]
    for request, page in zip(requests, pages, strict=True):
        expected = build_request(page.page_image, page.ocr_results, page.context)
        assert request.contents == expected["contents"], f"page {page.ordinal}'s contents differ"
        assert request.config == expected["config"], f"page {page.ordinal}'s config differs"


def test_two_builds_of_the_same_pages_compare_equal(batch: Any) -> None:
    """AC-1: deterministic, so a resubmission can be compared with what was sent."""
    pages = _pages(batch)

    assert batch.build_batch_requests(pages) == batch.build_batch_requests(list(pages))


def test_two_pages_sharing_an_ordinal_are_refused_naming_it(batch: Any) -> None:
    """AC-1: a duplicate ordinal is a `ValueError` naming it - two answers
    keyed "7" could not be told apart."""
    pages = [
        batch.BatchPage(
            ordinal=7, page_image=_png((10, 10, 10)), ocr_results=_OCR_1, context=EMPTY_CONTEXT
        ),
        batch.BatchPage(
            ordinal=3, page_image=_png((20, 20, 20)), ocr_results=_OCR_1, context=EMPTY_CONTEXT
        ),
        batch.BatchPage(
            ordinal=7, page_image=_png((40, 40, 40)), ocr_results=_OCR_0, context=EMPTY_CONTEXT
        ),
    ]

    with pytest.raises(ValueError) as raised:
        batch.build_batch_requests(pages)

    assert _number(7, str(raised.value)), str(raised.value)


def test_an_all_ocr_empty_page_still_gets_a_request(batch: Any) -> None:
    """AC-1, PO-2: the adapter builds what it is given; leaving a wordless page
    out of a batch is MT-111's decision, not this module's."""
    page = batch.BatchPage(
        ordinal=5, page_image=_png((90, 90, 90)), ocr_results=_OCR_EMPTY, context=EMPTY_CONTEXT
    )

    requests = batch.build_batch_requests([page])

    expected = build_request(page.page_image, page.ocr_results, page.context)
    assert len(requests) == 1
    assert requests[0].contents == expected["contents"]
    assert requests[0].config == expected["config"]
    assert requests[0].metadata == {"key": "5"}


def test_no_pages_build_no_requests(batch: Any) -> None:
    """AC-1, the empty edge: nothing given, nothing built."""
    assert batch.build_batch_requests([]) == []


# -- AC-2: submit_batch --------------------------------------------------------


def _requests() -> tuple[types.InlinedRequest, ...]:
    return (
        types.InlinedRequest(contents="page zero", metadata={"key": "0"}),
        types.InlinedRequest(contents="page one", metadata={"key": "1"}),
    )


def test_submit_makes_one_create_call_with_the_model_the_requests_and_the_display_name(
    batch: Any,
) -> None:
    """AC-2, MT-101 D-5: exactly `create(model=MODEL_ID, src=list(requests),
    config=CreateBatchJobConfig(display_name=...))`, and no other kwarg."""
    client = _FakeGeminiClient()
    requests = _requests()

    batch.submit_batch(client, requests, "mangatl volume 3")

    assert len(client.batches.created) == 1, client.batches.created
    kwargs = client.batches.created[0]
    assert kwargs == {
        "model": "gemini-3.1-pro-preview",
        "src": list(requests),
        "config": types.CreateBatchJobConfig(display_name="mangatl volume 3"),
    }
    assert type(kwargs["src"]) is list, type(kwargs["src"]).__name__


def test_submit_returns_the_name_the_created_job_carries(batch: Any) -> None:
    """AC-2: the job's `.name` (`batches/<id>`) is what the job table stores."""
    assert batch.submit_batch(_FakeGeminiClient(), _requests(), "v") == "batches/abc"


def test_a_create_time_refusal_propagates_unwrapped_after_one_call(batch: Any) -> None:
    """AC-2, MT-101 D-4: the SDK's create-time 400 reaches the caller as the
    very exception the client raised - not wrapped, not retried."""
    refusal = _ClientExploded("400 INVALID_ARGUMENT: response_json_schema")
    client = _FakeGeminiClient(raises=refusal)

    with pytest.raises(_ClientExploded) as raised:
        batch.submit_batch(client, _requests(), "v")

    assert raised.value is refusal
    assert len(client.batches.created) == 1, client.batches.created


# -- AC-3: batch_state ---------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "name"),
    [
        (types.JobState.JOB_STATE_PENDING, "pending"),
        (types.JobState.JOB_STATE_RUNNING, "pending"),
        (types.JobState.JOB_STATE_SUCCEEDED, "succeeded"),
        (types.JobState.JOB_STATE_FAILED, "failed"),
        (types.JobState.JOB_STATE_CANCELLED, "cancelled"),
        (types.JobState.JOB_STATE_EXPIRED, "expired"),
    ],
    ids=lambda value: getattr(value, "name", value),
)
def test_the_six_gemini_job_states_map_to_their_five_names(
    batch: Any, state: types.JobState, name: str
) -> None:
    """AC-3, MT-101 D-6: the Gemini API's six states, PENDING and RUNNING
    both reading as `"pending"`."""
    client = _FakeGeminiClient(SimpleNamespace(state=state, dest=None))

    assert batch.batch_state(client, "batches/xyz") == name


def test_batch_state_makes_one_get_call_by_the_jobs_name(batch: Any) -> None:
    """AC-3: one `client.batches.get(name=job_name)` and nothing else."""
    client = _FakeGeminiClient(SimpleNamespace(state=types.JobState.JOB_STATE_RUNNING, dest=None))

    batch.batch_state(client, "batches/xyz")

    assert client.batches.got == [{"name": "batches/xyz"}]


@pytest.mark.parametrize(
    "state",
    [
        types.JobState.JOB_STATE_UNSPECIFIED,
        types.JobState.JOB_STATE_QUEUED,
        types.JobState.JOB_STATE_CANCELLING,
        types.JobState.JOB_STATE_PAUSED,
        types.JobState.JOB_STATE_UPDATING,
        types.JobState.JOB_STATE_PARTIALLY_SUCCEEDED,
        None,
    ],
    ids=lambda value: getattr(value, "name", repr(value)),
)
def test_a_vertex_only_or_missing_state_is_unknown_never_pending(
    batch: Any, state: types.JobState | None
) -> None:
    """AC-3: the SDK's six Vertex-only members and a `None` state raise
    `UnknownBatchState` naming the state. A `"pending"` here would leave a
    page waiting forever on a state the Gemini API never documents."""
    client = _FakeGeminiClient(SimpleNamespace(state=state, dest=None))
    shown = "None" if state is None else state.name

    with pytest.raises(batch.UnknownBatchState) as raised:
        batch.batch_state(client, "batches/xyz")

    assert shown in str(raised.value), str(raised.value)
    assert client.batches.got == [{"name": "batches/xyz"}]


# -- AC-4: collect_batch on a succeeded job ------------------------------------


def test_a_succeeded_job_collects_one_translation_result_per_page(batch: Any) -> None:
    """AC-4: lines, usage, call and proposed terms per ordinal, every one
    written out by hand above."""
    client = _FakeGeminiClient(_job(_good_items()))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert result == {0: _EXPECTED_0, 1: _EXPECTED_1, 2: _EXPECTED_2}


def test_a_batch_page_that_returns_a_glossary_anyway_proposes_no_terms(batch: Any) -> None:
    """MT-106 AC-2, the batch item's case: page 0's body carries a
    **well-formed** glossary array - the negative control, checked here:
    `parse_terms_text`, which the pre-pass still reads through, accepts it -
    and the collected result's `proposed_terms` is `()`, its lines the region
    strings, and nothing raises."""
    assert parse_terms_text(_TEXT_0) == (ProposedTerm("翔", "Kakeru", "name"),), (
        "the control body is not a glossary parse_terms_text accepts"
    )
    client = _FakeGeminiClient(_job(_good_items()))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert isinstance(result[0], TranslationResult), result[0]
    assert result[0].lines == {0: "Hey, hurry!", 1: "Kakeru, over here!"}
    assert result[0].proposed_terms == (), (
        "a batch page's stray glossary array reached proposed_terms; after"
        " MT-106 a page proposes nothing"
    )


def test_a_batch_item_prices_its_thinking_tokens_as_output(batch: Any) -> None:
    """AC-4, DV-1's target: page 0 reports P=1000, C=200, K=150, T=400, so
    its usage is input 800, output 550 (150 + 400), cache read 200, cache
    write 0. A collector that priced K alone would report output 150 and
    under-bill the one input of the cost model nobody controls."""
    client = _FakeGeminiClient(_job(_good_items()))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert result[0].usage == TokenUsage(
        input_tokens=800, output_tokens=550, cache_read_tokens=200, cache_write_tokens=0
    )


def test_each_item_is_recorded_under_the_job_name_and_its_ordinal(batch: Any) -> None:
    """AC-4, story `## Notes`: `request_id` is `f"{job}#{ordinal}"` - the
    spelling MT-112's ledger shares - not the response's own id."""
    client = _FakeGeminiClient(_job(_good_items()))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert [result[n].call.request_id for n in (0, 1, 2)] == [
        "batches/abc#0",
        "batches/abc#1",
        "batches/abc#2",
    ]


def test_an_item_reporting_no_model_version_is_recorded_under_the_requested_model(
    batch: Any,
) -> None:
    """AC-4: `response.model_version or MODEL_ID` - page 2 reports none."""
    client = _FakeGeminiClient(_job(_good_items()))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert result[2].call == CallInfo("batches/abc#2", "gemini-3.1-pro-preview")
    assert result[0].call == CallInfo("batches/abc#0", _REPORTED)


def test_items_answered_in_reverse_order_pair_to_their_pages_by_key(batch: Any) -> None:
    """AC-4, PO-4, DV-2's target: MT-101 D-7 finds no order guarantee, so
    pairing is by `metadata["key"]`. Reversed, the result is unchanged - a
    positional pairing puts page 2's answer on page 0 and fails here."""
    client = _FakeGeminiClient(_job(list(reversed(_good_items()))))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert result == {0: _EXPECTED_0, 1: _EXPECTED_1, 2: _EXPECTED_2}


def test_collect_makes_exactly_one_get_call(batch: Any) -> None:
    """AC-4: one `batches.get(name=job_name)`; the state and the items come
    from the same job read."""
    client = _FakeGeminiClient(_job(_good_items()))

    batch.collect_batch(client, _JOB, _pages(batch))

    assert client.batches.got == [{"name": "batches/abc"}]


def test_an_item_carrying_an_error_fails_only_its_own_page(batch: Any) -> None:
    """AC-4, MT-101 D-8: `.error` becomes `BatchItemError(ordinal,
    error.message)` verbatim; the other pages still parse."""
    items = _good_items()
    items[1] = types.InlinedResponse(
        error=types.JobError(code=3, message="quota"), metadata={"key": "1"}
    )
    client = _FakeGeminiClient(_job(items))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert result == {0: _EXPECTED_0, 1: batch.BatchItemError(1, "quota"), 2: _EXPECTED_2}


def test_the_d14_probe_response_fails_its_page_naming_region_3(batch: Any) -> None:
    """AC-4, MT-101 D-14: batch did not enforce the schema, and the probe
    answered an extra key "3" for a three-region page. The parser's own
    `UnknownRegionIndex` fails that page, with its message; the others parse."""
    pages = _pages(batch)
    three_region_page = 2
    items = _good_items()
    items[three_region_page] = _item("2", _answer(_D14_TEXT, _usage(*_USAGE_2)))
    client = _FakeGeminiClient(_job(items))

    result = batch.collect_batch(client, _JOB, pages)

    assert len(pages[three_region_page].ocr_results) == 3
    assert result[2] == batch.BatchItemError(
        2,
        "UnknownRegionIndex: the response names region 3, which this page does not"
        " have; its reading indices are [0, 1, 2]",
    )
    assert result[0] == _EXPECTED_0
    assert result[1] == _EXPECTED_1


def test_an_item_whose_text_is_not_json_fails_its_page_with_the_decode_error(
    batch: Any,
) -> None:
    """AC-4: invalid JSON is `BatchItemError(ordinal, "JSONDecodeError: ...")`."""
    items = _good_items()
    items[0] = _item("0", _answer("not json at all", _usage(*_USAGE_0)))
    client = _FakeGeminiClient(_job(items))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert result[0] == batch.BatchItemError(
        0, "JSONDecodeError: Expecting value: line 1 column 1 (char 0)"
    )
    assert result[1] == _EXPECTED_1
    assert result[2] == _EXPECTED_2


def test_an_item_reporting_no_usage_fails_its_page_rather_than_pricing_it_at_zero(
    batch: Any,
) -> None:
    """AC-4: `_usage_of(None)` raises, so the page is a `BatchItemError`
    starting `"ValueError:"`, never a `TokenUsage(0, 0, 0, 0)`."""
    items = _good_items()
    items[1] = _item("1", _answer(_TEXT_1, None))
    client = _FakeGeminiClient(_job(items))

    result = batch.collect_batch(client, _JOB, _pages(batch))

    assert result[1] == batch.BatchItemError(
        1, "ValueError: the Gemini response reported no usage; a paid call cannot be priced"
    )
    assert result[0] == _EXPECTED_0
    assert result[2] == _EXPECTED_2


@pytest.mark.parametrize(
    ("count", "keys"),
    [(2, ["0", "1"]), (4, ["0", "1", "2", "3"])],
    ids=["fewer items than pages", "more items than pages"],
)
def test_an_item_count_that_differs_from_the_page_count_is_a_shape_error_naming_both(
    batch: Any, count: int, keys: list[str]
) -> None:
    """AC-4, PO-4: fewer OR more answers than pages is a shape error, whatever
    the keys say; the message names both counts."""
    items = [_item(key, _answer(_TEXT_1, _usage(*_USAGE_1))) for key in keys]
    assert len(items) == count
    client = _FakeGeminiClient(_job(items))

    with pytest.raises(batch.BatchShapeError) as raised:
        batch.collect_batch(client, _JOB, _pages(batch))

    message = str(raised.value)
    assert _number(count, message), message
    assert _number(3, message), message


@pytest.mark.parametrize("metadata", [None, {}], ids=["metadata None", "metadata without key"])
def test_an_item_with_no_key_is_a_shape_error(batch: Any, metadata: dict[str, str] | None) -> None:
    """AC-4: an item that cannot be paired is a shape error, not a guess."""
    items = _good_items()
    items[1] = types.InlinedResponse(
        response=_answer(_TEXT_1, _usage(*_USAGE_1)), metadata=metadata
    )
    client = _FakeGeminiClient(_job(items))

    with pytest.raises(batch.BatchShapeError):
        batch.collect_batch(client, _JOB, _pages(batch))


def test_an_item_keyed_to_a_page_the_batch_does_not_have_is_a_shape_error_naming_the_key(
    batch: Any,
) -> None:
    """AC-4, DV-2: key "9" for pages 0..2. A positional pairing never reads
    the key and so never notices."""
    items = _good_items()
    items[2] = _item("9", _answer(_TEXT_2, _usage(*_USAGE_2)))
    client = _FakeGeminiClient(_job(items))

    with pytest.raises(batch.BatchShapeError) as raised:
        batch.collect_batch(client, _JOB, _pages(batch))

    assert _number(9, str(raised.value)), str(raised.value)


def test_two_items_sharing_a_key_are_a_shape_error_naming_the_key(batch: Any) -> None:
    """AC-4: keys 0, 1, 1 - page 2 has no answer and page 1 has two."""
    items = _good_items()
    items[2] = _item("1", _answer(_TEXT_1, _usage(*_USAGE_1)))
    client = _FakeGeminiClient(_job(items))

    with pytest.raises(batch.BatchShapeError) as raised:
        batch.collect_batch(client, _JOB, _pages(batch))

    message = str(raised.value)
    assert _number(1, message), message


# -- AC-5: collect_batch on a job that has not succeeded -----------------------


class _ReadTooEarly(AssertionError):
    """A stale item was read on a job that has not succeeded."""


class _ExplodingResponse:
    """A response whose every field raises if read."""

    @property
    def text(self) -> str:
        raise _ReadTooEarly("response.text was read on an unfinished job")

    @property
    def usage_metadata(self) -> object:
        raise _ReadTooEarly("response.usage_metadata was read on an unfinished job")

    @property
    def model_version(self) -> str:
        raise _ReadTooEarly("response.model_version was read on an unfinished job")


class _StaleDest:
    """A non-empty `dest`, counting reads of its items."""

    def __init__(self) -> None:
        self.reads = 0

    @property
    def inlined_responses(self) -> list[object]:
        self.reads += 1
        return [
            SimpleNamespace(metadata={"key": str(n)}, error=None, response=_ExplodingResponse())
            for n in range(3)
        ]


@pytest.mark.parametrize(
    ("state", "name"),
    [
        (types.JobState.JOB_STATE_PENDING, "pending"),
        (types.JobState.JOB_STATE_RUNNING, "pending"),
        (types.JobState.JOB_STATE_FAILED, "failed"),
        (types.JobState.JOB_STATE_CANCELLED, "cancelled"),
        (types.JobState.JOB_STATE_EXPIRED, "expired"),
    ],
    ids=lambda value: getattr(value, "name", value),
)
def test_a_job_that_has_not_succeeded_is_not_finished_and_nothing_is_read(
    batch: Any, state: types.JobState, name: str
) -> None:
    """AC-5: `BatchNotFinished` naming the MAPPED state, raised before `dest`
    is touched - a pending job carrying a stale `dest` is still refused."""
    dest = _StaleDest()
    client = _FakeGeminiClient(SimpleNamespace(state=state, dest=dest))

    with pytest.raises(batch.BatchNotFinished) as raised:
        batch.collect_batch(client, _JOB, _pages(batch))

    assert re.search(rf"\b{name}\b", str(raised.value)), str(raised.value)
    assert dest.reads == 0, f"dest.inlined_responses was read {dest.reads} time(s)"
    assert client.batches.got == [{"name": "batches/abc"}]


@pytest.mark.parametrize(
    "state",
    [types.JobState.JOB_STATE_QUEUED, None],
    ids=lambda value: getattr(value, "name", repr(value)),
)
def test_collect_on_an_unknown_state_raises_unknown_state_not_not_finished(
    batch: Any, state: types.JobState | None
) -> None:
    """AC-5 with AC-3: the same table as `batch_state`, so an unknown state is
    `UnknownBatchState` - not `BatchNotFinished`, which would be retried as if
    pending - and `dest` is still not read."""
    dest = _StaleDest()
    client = _FakeGeminiClient(SimpleNamespace(state=state, dest=dest))

    with pytest.raises(batch.UnknownBatchState) as raised:
        batch.collect_batch(client, _JOB, _pages(batch))

    assert not isinstance(raised.value, batch.BatchNotFinished)
    assert ("None" if state is None else state.name) in str(raised.value), str(raised.value)
    assert dest.reads == 0, f"dest.inlined_responses was read {dest.reads} time(s)"
