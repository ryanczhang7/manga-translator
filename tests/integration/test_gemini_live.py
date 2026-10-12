"""MT-080 AC-8: one real page through `gemini.translate_page`, twice.

**Live, no oracle.** This file RECORDS what Gemini did with one real page - the
four usage counts, the priced cost, the model string the response reports, the
finish reason and the first lines - and asserts only the two things AC-8 makes
assertable: (b) the reported model prices without `UnknownModel`, and (c) at
least one region came back translated. The cost is not asserted; (d)'s second
call's `cache_read_tokens` is printed, never asserted > 0 (V-6 predicts 0: a
page request is below Gemini 3.1 Pro's 4,096-token implicit-cache minimum).

**C-5: this is the only place an invented SDK shape is caught.** Every test in
`tests/core/test_translate_gemini.py` runs against a duck; a kwarg the real
`generate_content` refuses, or a usage field it spells differently, surfaces
here as a `TypeError`, a 400 or an `AttributeError`.

**Marked `network` and not `gpu`.** The OCR input is recorded once, in
`fixtures/translate/page-011-ocr.json` (see the README there), so this test
needs the key and the network but not the GPU or the weights. It is in the
optional `integration` gate (`pytest -m "gpu or network"`), which never runs on
CI. It spends real money - two calls, on the order of $0.05 together at V-2's
rates - every time that gate runs on a machine with `GEMINI_API_KEY` set.

**Skips** when `GEMINI_API_KEY` is unset, and when the gitignored spike page is
absent. `google.genai` is imported inside the test body, so collecting this
file never needs the SDK.

Run it, with the output visible (the record is the printout):

    uv run pytest -q -s tests/integration/test_gemini_live.py

**Timing.** No `pytest-timeout` in this project, so no budget to size. Two
calls at thinking level MEDIUM; the SDK's own HTTP timeout applies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from mangatl.domain.glossary import EMPTY_CONTEXT
from mangatl.domain.line import OcrResult
from mangatl.domain.rates import price

pytestmark = pytest.mark.network

_REPO = Path(__file__).resolve().parents[2]
_PAGE = _REPO / "spikes" / "MT-002" / "pages" / "011.jpg"
_OCR_FIXTURE = _REPO / "fixtures" / "translate" / "page-011-ocr.json"

#: PO-1 names exactly this variable; the SDK's own `GOOGLE_API_KEY` lookup is
#: not used (AC-6), so the key is read here and passed explicitly.
_KEY_ENV = "GEMINI_API_KEY"


def load_ocr_fixture(path: Path = _OCR_FIXTURE) -> tuple[OcrResult, ...]:
    """`page-011-ocr.json` -> the `OcrResult`s, in reading order.

    The file is a JSON list of `{"text": str, "ocr_empty": bool}`, one per
    region, in the order the detect stage's `sort_regions` produced them -
    which is the order the request lists them in."""
    records: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return tuple(OcrResult(text=r["text"], ocr_empty=r["ocr_empty"]) for r in records)


def test_the_recorded_ocr_fixture_loads_as_eleven_readable_regions() -> None:
    """The loader and the fixture, checked without the network so a malformed
    fixture fails as itself rather than as a confusing live failure."""
    results = load_ocr_fixture()

    assert len(results) == 11
    assert not any(result.ocr_empty for result in results)
    assert results[0] == OcrResult(text="魔都は")


def test_one_real_page_translates_and_prices_and_the_usage_is_recorded() -> None:
    """AC-8 (a)-(d). Prints the record; asserts (b) and (c) only."""
    key = os.environ.get(_KEY_ENV)
    if not key:
        pytest.skip(f"{_KEY_ENV} is not set: AC-8 is a live measurement (DV-3)")
    if not _PAGE.exists():
        pytest.skip(f"{_PAGE} is not present: gitignored spike data")

    from google.genai import Client

    from mangatl.translate import gemini

    page = _PAGE.read_bytes()
    ocr_results = load_ocr_fixture()
    client = Client(api_key=key)

    for attempt in (1, 2):
        # One call per `translate_page`; the call's raw response is not
        # returned, so the finish reason is read off a second, recording
        # client wrapper rather than by changing the adapter's signature.
        recorder = _Recorder(client)
        result = gemini.translate_page(recorder, page, ocr_results, EMPTY_CONTEXT)
        assert result.call is not None, "a page with eleven readable regions made no call"

        record = price(result.call.model_id, result.usage)  # (b): raises UnknownModel if unlisted
        finish = recorder.finish_reason
        lines = sorted(result.lines.items())

        print(f"\n--- MT-080 AC-8, call {attempt} of 2 ---")
        print(f"model_version (reported): {result.call.model_id!r}")
        print(f"request id:               {result.call.request_id!r}")
        print(f"finish_reason:            {finish!r}")
        print(
            f"usage: input={result.usage.input_tokens}"
            f" output={result.usage.output_tokens}"
            f" cache_read={result.usage.cache_read_tokens}"
            f" cache_write={result.usage.cache_write_tokens}"
        )
        print(f"raw usage_metadata:       {recorder.usage_metadata!r}")
        print(
            f"cost: ${record.cost.amount} ({record.cost.micro()} micro-dollars),"
            f" x20 = ${record.cost.amount * 20}"
        )
        print(f"lines parsed: {len(lines)} of {len(ocr_results)}")
        for index, english in lines[:2]:
            print(f"  [{index}] {english}")
        if "MAX_TOKENS" in str(finish):
            print(
                "\n!!!!!! MAX_TOKENS: the response hit MAX_OUTPUT_TOKENS (thinking"
                " counts against it, V-5). This is a cap decision for the user -"
                " do NOT raise the cap silently. !!!!!!\n"
            )

        assert len(result.lines) >= 1, f"call {attempt}: no region was translated (AC-8 c)"


class _Recorder:
    """Wraps the real client so the test can read what `translate_page` does
    not return - the finish reason and the raw usage - without changing it.
    `client.models.generate_content` is passed straight through."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.finish_reason: object = None
        self.usage_metadata: object = None
        self.models = self

    def generate_content(self, **kwargs: Any) -> Any:
        response = self._client.models.generate_content(**kwargs)
        candidates = getattr(response, "candidates", None) or []
        self.finish_reason = candidates[0].finish_reason if candidates else None
        self.usage_metadata = getattr(response, "usage_metadata", None)
        return response
