"""`mangatl.translate.client`: the one call a page is allowed to make.

Covers **AC-7** in the only form that catches it - **the fake client was not
called** - and the joins AC-1, AC-4 and AC-6 make once the request, the parse
and the SDK boundary are put together.

**No network call, no `Anthropic` client, no credential.** MT-011 PO-1 records
that this machine has none, and `pyproject.toml` marks the `network` marker
"never runs on CI", so no CI run could ever discharge a live test either. The
live measurement is **MT-037**. `_FakeClient` below is a duck: `translate_page`
is annotated `client: Anthropic` and never asks what it is.

**Why AC-7 is asserted as a call count and not as an empty result.**
"The page completes with no proposed lines" is true of a page that *was* sent to
the model and came back empty, and that page cost $0.06. The criterion is
"**no API call is made**" - *a page of wordless art must not cost money* - and
`client.calls == 0` is the only assertion that distinguishes the two. A suite
that asserted `result.lines == {}` would pass against an implementation that
spends the whole chapter budget on blank pages.

**Timing.** No `pytest-timeout` in this project and no per-test timeout exists,
so there is no budget in this file to size; if a later story adds one, every
test and hook here needs one. The dominant cost is `build_request`'s image
resize on a 200x300 page, which is negligible - the cap arithmetic is exercised
at real page sizes in `test_translate_prompt.py`, not here.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from mangatl.domain.line import OcrResult
from mangatl.domain.translation import TokenUsage, TranslationResult
from mangatl.translate.client import translate_page
from mangatl.translate.parse import UnknownRegionIndex
from mangatl.translate.prompt import build_request

# -- the fixture page ----------------------------------------------------------

#: The same four regions `fixtures/translate/README.md` tabulates.
_OCR_RESULTS: tuple[OcrResult, ...] = (
    OcrResult(text="醜鬼が人間の言う通りに動いたりね"),
    OcrResult(text="……なるほど"),
    OcrResult(text="どうして君がここに"),
    OcrResult(text="行くぞ"),
)

#: AC-7's page: every region read empty. `ocr_empty` means "the model emitted no
#: tokens" and is stored rather than derived (MT-010 C-5/PO-3), which is exactly
#: what makes this page recognisable before a call is made.
_ALL_EMPTY: tuple[OcrResult, ...] = tuple(OcrResult(text="", ocr_empty=True) for _ in range(4))

_EXPECTED: dict[int, str] = {
    0: "As if a demon would move at a human's say-so.",
    1: "...I see.",
    2: "Why are you here?",
    3: "Let's go.",
}


def _page() -> bytes:
    """A small PNG. Nothing here cares about its size - see the docstring."""
    width, height = 200, 300
    raw = b"".join(b"\x00" + b"\x20\x30\x40" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 1))
        + chunk(b"IEND", b"")
    )


class _ClientExploded(Exception):
    """A call nobody should have made. A bespoke type, so a test cannot pass by
    catching some real error raised elsewhere for another reason."""


class _FakeMessages:
    """`client.messages`. Records every `create`, because AC-7 is a claim about
    the **count** and AC-1 a claim about the **kwargs**."""

    def __init__(self, responses: Sequence[object], *, explode: bool = False) -> None:
        self._responses = list(responses)
        self._explode = explode
        self.seen: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.seen.append(kwargs)
        if self._explode:
            raise _ClientExploded("the client was called and should not have been")
        return self._responses[len(self.seen) - 1]


class _FakeClient:
    """Stands in for `anthropic.Anthropic`. Nothing here is a real client, and
    nothing here has a credential."""

    def __init__(self, *responses: object, explode: bool = False) -> None:
        self.messages = _FakeMessages(responses, explode=explode)

    @property
    def calls(self) -> int:
        return len(self.messages.seen)


# -- AC-7: a page of wordless art must not cost money -------------------------


def test_a_page_whose_every_region_read_empty_makes_no_api_call_at_all() -> None:
    """**AC-7**, and MT-011's falsifiable success condition 2.

    The fake client raises on any `create`, so this fails loudly rather than by
    an assertion at the end - but the assertion is there anyway, because
    `calls == 0` is the sentence the criterion is written in and a failure
    should read as "one call was made" rather than as a stray exception.

    `architecture.md` D5 allows exactly one call per page and `stack.md` §5/O4
    puts a 20-page chapter at $1.14 against a $2.00 ceiling. A chapter with five
    wordless splash pages spends a twentieth of its budget on nothing.
    """
    client = _FakeClient(explode=True)

    result = translate_page(client, _page(), _ALL_EMPTY)

    assert client.calls == 0, f"{client.calls} API call(s) made for a page with no text"
    assert result.lines == {}


def test_a_page_with_no_regions_at_all_makes_no_api_call_either() -> None:
    """The zero of zero-one-many, and the page the detector found nothing on.
    Not the same input as AC-7's - no regions rather than empty ones - and an
    implementation that guarded with `all(r.ocr_empty for r in results)` gets
    this right for free, while one that counted empties does not."""
    client = _FakeClient(explode=True)

    assert translate_page(client, _page(), ()).lines == {}
    assert client.calls == 0


def test_the_no_call_page_is_priced_at_nothing_rather_than_at_no_usage() -> None:
    """C-5's RED amendment. A page that made no call has a `TokenUsage` of four
    zeroes, not a `None` and not a missing field.

    MT-012 sums a ledger. A `None` usage would make every reader of that ledger
    unwrap an `Optional` for a case whose value is known and is zero, and the
    first reader that forgets is a `TypeError` in the cost report rather than
    here.
    """
    result = translate_page(_FakeClient(explode=True), _page(), _ALL_EMPTY)

    assert result.usage == TokenUsage(
        input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0
    )
    assert type(result) is TranslationResult


def test_a_page_with_one_region_that_read_empty_still_skips_the_call() -> None:
    """The one of zero-one-many. A one-region page is where a guard written as
    `len(results) > 1` or as a `for`-loop with no else branch goes wrong."""
    client = _FakeClient(explode=True)

    assert translate_page(client, _page(), (OcrResult(text="", ocr_empty=True),)).lines == {}
    assert client.calls == 0


def test_a_page_with_a_single_region_that_read_something_does_make_the_call(
    fake_message: Callable[..., object],
) -> None:
    """The negative control for the four tests above, and the reason they mean
    anything. Without it, `translate_page` could refuse to call the API under
    **every** circumstance and every AC-7 assertion here would still pass.

    One region carrying text is the smallest page that must cost money.
    """
    client = _FakeClient(fake_message('{"0": "Why are you here?"}'))

    result = translate_page(client, _page(), (_OCR_RESULTS[2],))

    assert client.calls == 1, "a page that has text to translate must be sent"
    assert result.lines == {0: "Why are you here?"}


def test_a_page_where_only_some_regions_read_empty_is_still_sent(
    fake_message: Callable[..., object],
) -> None:
    """The other side of AC-7's boundary, and the one that keeps the guard from
    being too eager. AC-7 is "a page whose regions are **all** `ocr_empty`"; a
    page with one readable bubble among three blank ones is an ordinary page and
    must be translated. A guard written as `any(r.ocr_empty ...)` passes every
    test above and silently stops translating most of the chapter."""
    client = _FakeClient(fake_message('{"1": "...I see."}'))

    mixed = (
        OcrResult(text="", ocr_empty=True),
        _OCR_RESULTS[1],
        OcrResult(text="", ocr_empty=True),
    )

    assert translate_page(client, _page(), mixed).lines == {1: "...I see."}
    assert client.calls == 1


# -- AC-1: one call per page, carrying the built request ----------------------


def test_a_page_with_text_makes_exactly_one_call_carrying_the_built_request(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """AC-1 and `architecture.md` D5's "one call per page", which is a budget:
    two passes per page costs $2.29 against a $2.00 ceiling.

    The kwargs are compared against `build_request`'s own output rather than
    re-described here, so that C-5's settled shape has exactly one place it is
    written down - `test_translate_prompt.py` is where it is checked - and this
    test stays a claim about *dispatch* rather than a second copy of it.
    """
    page = _page()
    client = _FakeClient(fake_message(response_body("well-formed")))

    translate_page(client, page, _OCR_RESULTS)

    expected, _ = build_request(page, _OCR_RESULTS)

    assert client.calls == 1, f"{client.calls} calls for one page"
    assert client.messages.seen[0] == expected


def test_the_call_is_not_retried_when_the_model_answers(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """MT-011 `## Out of scope`: "retries, second opinions, or any second pass -
    over budget by design". A second `create` would be caught by the count above
    too; this names the reason so a later reader does not add one as an
    improvement."""
    client = _FakeClient(
        fake_message(response_body("well-formed")),
        fake_message(response_body("well-formed")),
    )

    translate_page(client, _page(), _OCR_RESULTS)

    assert client.calls == 1


# -- AC-4 and AC-6, through the SDK boundary -----------------------------------


def test_the_lines_come_back_keyed_by_reading_index(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """AC-4, end to end through `client.py`. The fixture's key order is 2, 0,
    3, 1, so a position-based parse is caught here as well as in
    `test_translate_parse.py` - see `fixtures/translate/README.md`."""
    client = _FakeClient(fake_message(response_body("well-formed")))

    assert translate_page(client, _page(), _OCR_RESULTS).lines == _EXPECTED


def test_a_region_the_model_omitted_is_absent_from_the_result(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """AC-5, through `client.py`: three regions come back and the page is not
    discarded."""
    client = _FakeClient(fake_message(response_body("omits-region-3")))

    lines = translate_page(client, _page(), _OCR_RESULTS).lines

    assert set(lines) == {0, 1, 2}
    assert client.calls == 1


def test_a_response_naming_an_unknown_region_propagates_rather_than_being_swallowed(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """AC-6's first half. `translate_page` does not catch it: AC-6's "nothing is
    written to the store" is only true if the exception reaches the stage, and
    a `client.py` that returned a partial result instead would write the good
    regions and lose the error."""
    client = _FakeClient(fake_message(response_body("unknown-region-index")))

    with pytest.raises(UnknownRegionIndex, match=r"\b7\b"):
        translate_page(client, _page(), _OCR_RESULTS)


# -- C-2/C-5: the SDK boundary is where conversion happens ---------------------


def test_the_four_usage_counts_are_carried_across_onto_the_right_fields(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
    fake_usage: Callable[..., object],
) -> None:
    """C-5's last bullet and C-2's reason for four ints.

    Four **distinct** values, because the pairing is the whole assertion: a
    swap of `cache_read_input_tokens` and `cache_creation_input_tokens` is a
    factor-of-12.5 pricing error (0.1x against 1.25x of the base input rate),
    it is invisible in every other test in this suite, and MT-012 would report
    it as fact. Four zeroes or four equal numbers would let any permutation
    through.
    """
    client = _FakeClient(
        fake_message(
            response_body("well-formed"),
            usage=fake_usage(
                input_tokens=3011,
                output_tokens=712,
                cache_read_input_tokens=1499,
                cache_creation_input_tokens=1873,
            ),
        )
    )

    usage = translate_page(client, _page(), _OCR_RESULTS).usage

    assert usage == TokenUsage(
        input_tokens=3011,
        output_tokens=712,
        cache_read_tokens=1499,
        cache_write_tokens=1873,
    )


def test_the_result_carries_plain_domain_values_and_no_sdk_objects(
    response_body: Callable[[str], str],
    fake_message: Callable[..., object],
) -> None:
    """C-2. `domain` may not import `anthropic` (the *"domain is independent"*
    contract), so the conversion has to happen at this boundary and nowhere
    else. An implementation that stored `response.usage` straight onto the
    result would put an SDK object inside a domain value - which `lint` cannot
    see, because no import changed."""
    client = _FakeClient(fake_message(response_body("well-formed")))

    result = translate_page(client, _page(), _OCR_RESULTS)

    assert type(result) is TranslationResult
    assert type(result.usage) is TokenUsage
    assert all(type(key) is int and type(value) is str for key, value in result.lines.items())
