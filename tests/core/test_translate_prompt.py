"""`mangatl.translate.prompt`: the image cap, the estimate and the request.

Covers **AC-1**, **AC-2** and **AC-3** in full, plus the call shape C-5 settles.

**The cap and the estimate are budget, not tuning** (`architecture.md` D5,
`stack.md` §5/O4). An uncapped 2400x3400 scan costs $1.95 against a $2.00
ceiling; the capped design costs $1.14. Nothing in this file is a preference.

**Dimensions are read back with a standard-library header parser, not with
Pillow** (`_image_size` below). `prepare_page_image` will almost certainly use
Pillow, and `tdd-cycle` is explicit that a mutation is only as informative as the
independence of what observes it: a decoder that shares the implementation's
assumptions about orientation, EXIF or downsampling is the wrong witness. A
20-line SOF/IHDR scan shares none of them.

**Why the expected short edges are a one-pixel band and not a constant.**
Preserving an aspect ratio in integer pixels is impossible in general - 1569x1000
capped to a long edge of 1568 wants a short edge of 999.363 - and C-7 pins the
*estimate*'s rounding (`ceil`) without pinning the *resize*'s. So the long edge
is pinned exactly, the short edge is required to be `floor` or `ceil` of the
exact scale, and the two cases whose scale is an exact ratio (2/3, 1/1) are
pinned to the integer. `est_tokens` is then checked against `ceil(w*h/750)` on
the dimensions actually read back, which is C-7's rule with nothing assumed.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. MEASURED 2026-09-18 (RED, this machine,
`uv run python`): the standard-library PNG builder below costs 12 ms at
1568x1000, 28 ms at 2352x1647 and 60 ms at 2400x3400 with `zlib` level 1 -
level 1 and not level 9 (which is 18/48/99 ms) because nothing here reads a
pixel. `_page` is `functools.cache`d, so the eleven distinct sizes are built once per
session and re-used across the parametrised cases.
"""

from __future__ import annotations

import base64
import struct
import zlib
from collections.abc import Sequence
from functools import cache
from math import ceil, floor
from typing import Any

import pytest

from mangatl.domain.line import OcrResult
from mangatl.translate.prompt import (
    MAX_IMAGE_LONG_EDGE_PX,
    MAX_OUTPUT_TOKENS,
    MODEL_ID,
    build_request,
    prepare_page_image,
)

# -- the fixture page ----------------------------------------------------------

#: Four regions in reading order, as `fixtures/translate/README.md` describes
#: them. None is `ocr_empty`: AC-1 is "N ordered regions **carrying Japanese
#: text**", and the all-empty page is AC-7's, in `test_translate_client.py`.
#:
#: The four strings share no substring and contain no ASCII digit, so "region i
#: is listed" and "the reading index i appears" are independent claims.
_OCR_RESULTS: tuple[OcrResult, ...] = (
    OcrResult(text="醜鬼が人間の言う通りに動いたりね"),
    OcrResult(text="……なるほど"),
    OcrResult(text="どうして君がここに"),
    OcrResult(text="行くぞ"),
)


@cache
def _page(width: int, height: int) -> bytes:
    """An 8-bit RGB PNG of the given size, filled with one colour.

    A local builder rather than `conftest.png_bytes` because that one is MT-004's
    and compresses at level 9; these pages are up to 2400x3400 and nothing here
    looks at a pixel. Cached, so eleven sizes cost eleven builds per session.
    """
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


# The JPEG start-of-frame markers that carry the frame dimensions. 0xC4 is a
# define-Huffman-table segment and 0xCC an arithmetic-coding one, which is why
# neither is in the run - they are not SOF markers despite sitting inside it.
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _image_size(data: bytes) -> tuple[str, int, int]:
    """`(format, width, height)` for PNG or JPEG bytes, standard library only.

    The independent witness this file's docstring is about. PNG dimensions come
    out of `IHDR`; JPEG dimensions out of the first SOF segment, which stores
    **height before width** - a reader that assumes the other order reports a
    square page for every page and silently agrees with a broken resize.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:2] != b"\xff\xd8":
        raise AssertionError(f"neither a PNG nor a JPEG; the first bytes are {data[:8]!r}")
    offset = 2
    while offset + 1 < len(data):
        if data[offset] != 0xFF:
            raise AssertionError(f"malformed JPEG: expected a marker at byte {offset}")
        marker = data[offset + 1]
        if marker == 0xFF:  # a fill byte; the marker is the next one along
            offset += 1
            continue
        offset += 2
        if 0xD0 <= marker <= 0xD9:  # RSTn, SOI, EOI: no length field
            continue
        (segment,) = struct.unpack(">H", data[offset : offset + 2])
        if marker in _SOF_MARKERS:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return "jpeg", width, height
        offset += segment
    raise AssertionError("malformed JPEG: no start-of-frame marker before the end of the data")


def _expected_short_edge(width: int, height: int) -> tuple[int, int]:
    """The `[floor, ceil]` band the short edge must land in after capping."""
    longest = max(width, height)
    if longest <= MAX_IMAGE_LONG_EDGE_PX:
        return min(width, height), min(width, height)
    exact = min(width, height) * MAX_IMAGE_LONG_EDGE_PX / longest
    return floor(exact), ceil(exact)


def _blocks(request: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Every content block of the one user message with `type == kind`."""
    (message,) = request["messages"]
    return [block for block in message["content"] if block["type"] == kind]


def _user_text(request: dict[str, Any]) -> str:
    (block,) = _blocks(request, "text")
    return str(block["text"])


def _request(results: Sequence[OcrResult] = _OCR_RESULTS) -> dict[str, Any]:
    """The kwargs half of `build_request` for a 1568x1000 page."""
    kwargs, _ = build_request(_page(1568, 1000), results)
    return kwargs


# -- the module's constants ----------------------------------------------------


def test_the_module_pins_the_cap_the_output_ceiling_and_the_model_as_constants() -> None:
    """C-3 and C-5, as literals.

    `MAX_IMAGE_LONG_EDGE_PX` is Claude's documented image long-edge cap and is
    `architecture.md` D5's budget. `MAX_OUTPUT_TOKENS` is required by the API
    (PO-5: the first draft omitted it). `MODEL_ID` is `stack.md` §5/O4's choice
    and the rate table MT-012 will price against.
    """
    assert MAX_IMAGE_LONG_EDGE_PX == 1568
    assert MAX_OUTPUT_TOKENS == 4096
    assert MODEL_ID == "claude-opus-5"


# -- AC-2: the cap, and the aspect ratio -------------------------------------


@pytest.mark.parametrize(
    ("width", "height"),
    [
        pytest.param(1569, 1000, id="landscape-one-over"),
        pytest.param(1000, 1569, id="portrait-one-over"),
        pytest.param(1569, 1569, id="square-one-over"),
        pytest.param(2352, 1647, id="landscape-two-thirds"),
        pytest.param(2400, 3400, id="the-uncapped-scan-from-the-cost-model"),
    ],
)
def test_a_page_over_the_cap_comes_back_at_1568_on_its_long_edge(width: int, height: int) -> None:
    """AC-2. One pixel over the cap is over the cap: 1569 is not 1568.

    The orientation cases are not decoration. An implementation that caps
    `width` unconditionally - rather than whichever edge is longer - passes
    every landscape case and silently leaves every portrait manga page
    uncapped, which is the orientation real scans actually arrive in.
    """
    capped, _ = prepare_page_image(_page(width, height))

    image_format, out_width, out_height = _image_size(capped)
    low, high = _expected_short_edge(width, height)

    assert image_format == "jpeg", "C-3 says the prepared page is JPEG bytes"
    assert max(out_width, out_height) == MAX_IMAGE_LONG_EDGE_PX
    assert low <= min(out_width, out_height) <= high, (
        f"{width}x{height} capped to {out_width}x{out_height};"
        f" an aspect-preserving resize gives a short edge in [{low}, {high}]"
    )
    assert (out_width >= out_height) == (width >= height), "the orientation flipped"


def test_a_two_thirds_scale_lands_on_exact_integers_in_both_edges() -> None:
    """AC-2, with the rounding taken out of it.

    2352x1647 is 784:549, so capping the long edge to 1568 is an exact 2/3 and
    **every** correct implementation gives 1568x1098 whatever it rounds with.
    It is also the page `stack.md` §5/O4's published 2,296-token figure is
    computed on - see the reconciliation test below.
    """
    capped, _ = prepare_page_image(_page(2352, 1647))

    assert _image_size(capped)[1:] == (1568, 1098)


# -- AC-3: no upscaling ------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "height"),
    [
        pytest.param(1568, 1000, id="landscape-at-the-cap"),
        pytest.param(1567, 1000, id="landscape-one-under"),
        pytest.param(1000, 1568, id="portrait-at-the-cap"),
        pytest.param(1000, 1567, id="portrait-one-under"),
        pytest.param(1568, 1568, id="square-at-the-cap"),
        pytest.param(1567, 1567, id="square-one-under"),
    ],
)
def test_a_page_already_within_the_cap_keeps_its_own_size(width: int, height: int) -> None:
    """AC-3, and C-7's "not symmetric with AC-2".

    Exactly 1568 is the boundary and is *within* the cap: "at most 1568 px"
    includes 1568, so a page already there is returned untouched rather than
    resized to itself. An implementation that scales unconditionally by
    `1568 / longest` passes this at 1568 and fails at 1567 by upscaling it,
    which pays for bytes the server throws away.
    """
    capped, _ = prepare_page_image(_page(width, height))

    image_format, out_width, out_height = _image_size(capped)

    assert image_format == "jpeg", "C-3 says the prepared page is JPEG bytes"
    assert (out_width, out_height) == (width, height), (
        f"a {width}x{height} page is within the {MAX_IMAGE_LONG_EDGE_PX} px cap"
        f" and must not be rescaled; got {out_width}x{out_height}"
    )


# -- AC-2: the estimate ------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (1568, 1000),
        (1569, 1000),
        (1567, 1000),
        (1000, 1568),
        (1000, 1569),
        (1000, 1567),
        (1568, 1568),
        (1569, 1569),
        (1567, 1567),
        (2352, 1647),
        (2400, 3400),
    ],
)
def test_the_estimate_is_the_ceiling_of_the_pixels_actually_sent_over_750(
    width: int, height: int
) -> None:
    """AC-2 and C-7, both halves: **`ceil`**, and on the **capped** dimensions.

    `floor` differs from `ceil` by exactly one in all eleven cases here - none
    of the capped pixel counts is a multiple of 750 - so an implementation using
    `int()` or `//` fails every one of them rather than passing by luck.
    """
    capped, est_tokens = prepare_page_image(_page(width, height))

    _, out_width, out_height = _image_size(capped)
    pixels = out_width * out_height

    assert est_tokens == ceil(pixels / 750), (
        f"{out_width}x{out_height} is {pixels} px; C-7 says ceil({pixels}/750)"
        f" = {ceil(pixels / 750)}, not {est_tokens}"
    )
    assert est_tokens != floor(pixels / 750), "floor and ceil must not agree here"


def test_the_published_2296_token_figure_is_reproduced_exactly() -> None:
    """C-7's reconciliation against `stack.md` §5/O4, as a literal.

    1568 x 1098 = 1,721,664 px; / 750 = 2295.552; `ceil` is **2296**, which is
    the number the document prints, and `floor` is 2295, which quietly is not.
    The whole cost model and the MT-013 budget guard project from this figure,
    and under-estimating spend is the one direction that is never safe.
    """
    _, est_tokens = prepare_page_image(_page(2352, 1647))

    assert est_tokens == 2296
    assert est_tokens != 2295, "2295 is floor; C-7 pins ceil"


def test_the_estimate_describes_the_capped_page_and_not_the_original() -> None:
    """AC-2 and C-7's second half, stated as an inequality.

    A 2400x3400 scan is 8,160,000 px - 10,880 tokens if the estimate is taken
    before the resize, against ~2,314 after it. That is a projection inflated
    4.7x, and `stack.md` §5/O4 costs the two designs at $1.95 and $1.14. The
    error is silent: every returned image is correctly capped and only the
    number is wrong, which is exactly what the MT-013 budget guard would act on.
    """
    _, est_tokens = prepare_page_image(_page(2400, 3400))

    assert est_tokens < ceil(2400 * 3400 / 750), "the estimate was taken before the resize"
    assert 2300 <= est_tokens <= 2320, f"a 2400x3400 scan caps to ~2,314 tokens; got {est_tokens}"


# -- AC-1: the request ---------------------------------------------------------


def test_the_request_is_exactly_one_image_block_one_system_block_and_one_user_block() -> None:
    """AC-1, counted. "Exactly" is the criterion: one call per page with one
    page image in it is `architecture.md` D5's budget, and a second image block
    or a second message is a second page's worth of input tokens."""
    request = _request()

    assert len(request["system"]) == 1, "C-5: system is a list of ONE text block"
    assert request["system"][0]["type"] == "text"
    assert len(request["messages"]) == 1, "AC-1: one user block"
    assert request["messages"][0]["role"] == "user"
    assert len(_blocks(request, "image")) == 1, "AC-1: exactly one image block"
    assert len(_blocks(request, "text")) == 1, "AC-1: exactly one user text block"
    assert len(request["messages"][0]["content"]) == 2, "an image block and a text block, no more"


def test_the_image_block_comes_before_the_text_that_describes_it() -> None:
    """The Anthropic API reference's vision ordering: the image block is placed
    before the text block it is about. Cheap to pin, and a request assembled the
    other way round is a silent quality change nothing else here would notice."""
    (content,) = (message["content"] for message in _request()["messages"])

    assert [block["type"] for block in content] == ["image", "text"]


def test_the_user_block_lists_every_region_by_reading_index_and_source_text() -> None:
    """AC-1, in full: **all N** regions, by **index** and by **source text**.

    The four source strings share no substring, so `count(...) == 1` is a real
    claim: a listing that repeated or dropped one fails it.
    """
    text = _user_text(_request())

    for index, result in enumerate(_OCR_RESULTS):
        assert result.text in text, f"region {index}'s source text is missing from the user block"
        assert text.count(result.text) == 1, f"region {index}'s source text is listed twice"
        assert str(index) in text, f"reading index {index} is not named in the user block"


def test_the_regions_are_listed_in_reading_order_and_not_some_other_one() -> None:
    """AC-1's "ordered" clause. Reading order is right-to-left, top-to-bottom
    and is computed once, in the domain (`architecture.md` D10); a request that
    re-sorted it would hand the model a different page from the one the review
    screen shows, and `stack.md` §5/O2 is explicit that the right words on the
    wrong bubbles is the failure that matters most."""
    text = _user_text(_request())

    positions = [text.index(result.text) for result in _OCR_RESULTS]

    assert positions == sorted(positions), f"the regions are listed out of order: {positions}"


def test_a_one_region_page_lists_one_region_and_nothing_else() -> None:
    """The "one" of zero-one-many. A listing built by joining on a separator is
    the usual place an off-by-one lives, and it only shows at N = 1."""
    request = _request((_OCR_RESULTS[0],))

    text = _user_text(request)

    assert _OCR_RESULTS[0].text in text
    for other in _OCR_RESULTS[1:]:
        assert other.text not in text
    assert len(_blocks(request, "image")) == 1


def test_the_image_block_carries_exactly_the_prepared_bytes_as_unwrapped_base64() -> None:
    """AC-2's "prepared for the request", joined up.

    Three separate things, each of which has been a real bug in somebody's
    client: the request must carry the **capped** bytes rather than the
    original; the media type must say what they are; and the base64 must have
    **no newlines** - `base64.encodebytes` inserts them every 76 characters and
    the API rejects the result, while `b64encode` does not.
    """
    page = _page(2400, 3400)
    expected, _ = prepare_page_image(page)
    request, _ = build_request(page, _OCR_RESULTS)

    (image,) = [block for block in request["messages"][0]["content"] if block["type"] == "image"]
    source = image["source"]

    assert source["type"] == "base64"
    assert source["media_type"] == "image/jpeg"
    assert "\n" not in source["data"], "base64 with newlines in it is rejected by the API"
    assert base64.b64decode(source["data"]) == expected, (
        "the request carries different bytes from the ones prepare_page_image returns"
    )


def test_the_request_reports_the_estimate_of_the_image_it_actually_carries() -> None:
    """AC-2's "recorded on the request", and MT-013's input.

    See MT-011 `## Contract` C-3's RED amendment for why this is the second half
    of a tuple rather than a key in the kwargs: `est_tokens` is not a parameter
    of the Messages API, and `client.messages.create(**request)` raises
    `TypeError` on an unexpected keyword.
    """
    page = _page(2400, 3400)
    _, prepared_estimate = prepare_page_image(page)
    request, request_estimate = build_request(page, _OCR_RESULTS)

    (image,) = [block for block in request["messages"][0]["content"] if block["type"] == "image"]
    _, width, height = _image_size(base64.b64decode(image["source"]["data"]))

    assert request_estimate == prepared_estimate
    assert request_estimate == ceil(width * height / 750), (
        "the recorded estimate does not describe the image the request carries"
    )


# -- C-5: the settled call shape ---------------------------------------------


def test_the_call_shape_is_the_one_c5_settles() -> None:
    """C-5, verified by the PO against the Anthropic API reference on
    2026-09-18 (PO-5). Every value here is a cost-model decision:
    `medium` effort rather than the default `high` because `cost-model.awk` puts
    the chapter over $2.00 at 3,200 thinking tokens per page."""
    request = _request()

    assert request["model"] == MODEL_ID
    assert request["max_tokens"] == MAX_OUTPUT_TOKENS
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"]["effort"] == "medium"
    assert request["output_config"]["format"]["type"] == "json_schema"


def test_the_only_cache_breakpoint_is_on_the_system_block() -> None:
    """C-5's caching placement, and the reason it is not free to move.

    Render order is `tools` -> `system` -> `messages`, so a breakpoint on the
    system block leaves the page image, the region list and MT-014's rolling
    context **after** it, where they are free to vary per page. A breakpoint
    placed after the page image instead caches nothing across pages and the cost
    model's "19 cache reads per 20-page chapter" evaporates - which is MT-037's
    deferred condition 1, because only a live call can read it back.
    """
    request = _request()

    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    for block in request["messages"][0]["content"]:
        assert "cache_control" not in block, (
            "a breakpoint after the page image invalidates the cache for every page"
        )


def test_the_request_uses_none_of_the_shapes_opus_5_rejects() -> None:
    """PO-5's four confirmed 400s and one deprecation, as negative assertions.

    Each is a shape an implementer working from pre-2026 documentation or from
    memory would reach for, and each fails at runtime against the real API -
    which is to say, only in MT-037, only with a credential, and only after
    spending money. They are checkable here for free.
    """
    request = _request()

    assert "budget_tokens" not in request["thinking"], "rejected with a 400 on Opus 5"
    assert "output_format" not in request, "deprecated; C-5 uses output_config.format"
    assert "fallbacks" not in request, "out of scope; it changes the cost model"
    assert request.get("stream") in (None, False), "C-5 pins non-streaming at 4096 max_tokens"
    assert all(message["role"] == "user" for message in request["messages"]), (
        "an assistant prefill returns a 400 on Opus 5 (PO-5)"
    )


def test_the_response_schema_names_the_pages_indices_and_requires_none_of_them() -> None:
    """C-5's schema, and it is what makes AC-5 a real case rather than a
    hypothetical: a compliant model may omit a region only if the schema does
    not require it. `additionalProperties: false` is the other half - it is what
    lets AC-6's unknown index be the model disobeying rather than the schema
    inviting it."""
    schema = _request()["output_config"]["format"]["schema"]

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert sorted(schema["properties"], key=int) == ["0", "1", "2", "3"]
    assert not schema.get("required"), "AC-5 turns on no region being required"
