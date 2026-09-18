"""Fixture bytes shared by MT-004's page-intake tests, and by MT-007's.

MT-007 appended `one_bit_png` at the foot of this file, MT-009 `page_mask` below
it, and MT-011 the structured-output `Message` stand-in below that; everything
above `one_bit_png` belongs to MT-004 and is unchanged.

Recipes are pinned in `docs/backlog/stories/MT-004.md` `## Contract` PO-2, and
were verified there against Pillow 12.3.0 on 2026-09-15 in a scratch directory
outside this project -- Pillow is not a project dependency during RED, so RED
cannot re-run that verification. RED *has* independently re-checked, using only
the standard library (`base64`, `hashlib`, `struct`, `zlib`, no decoder), that:

- the JPEG bytes below are exactly 286 bytes and hash to the sha256 PO-2(b)
  states, confirming the base64 transcription is exact;
- the "header-valid, body-corrupt" PNG bytes below are exactly 81 bytes, carry
  a valid 8-byte PNG signature, and their `IHDR` chunk declares 13x29 -- i.e.
  they are structurally a real PNG header, not plain garbage, which is the
  whole point of PO-3's second fixture.

Neither check needs a decoder, so neither is DV-1 (whether Pillow's `open()`
actually accepts these bytes while `load()` rejects them). DV-1 is owned by
GATES, against the shipped `read_chapter`, and is declined here.
"""

from __future__ import annotations

import base64
import struct
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest


def _png_bytes(width: int, height: int, rgb: tuple[int, int, int] = (0, 0, 0)) -> bytes:
    """An 8-bit RGB PNG of the given size, filled with one colour.

    `## Contract` PO-2(a), verified there to open, `load()` and report the
    requested size at 1x1, 7x3, 13x29 and 640x906 under Pillow 12.3.0.
    Standard-library only, so it is usable before Pillow is a dependency.
    """
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

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
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# PO-2(b): a baseline JPEG, 7x3 RGB, 286 bytes. There is no JPEG encoder in the
# standard library, so this is a pinned constant rather than a builder.
_JPEG_7X3_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIf\n"
    "IiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7\n"
    "Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCAADAAcDASIA\n"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEB\n"
    "AAAAAAAAAAAAAAAAAAAABf/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJ6ASHv/\n"
    "2Q==\n"
)
_JPEG_7X3 = base64.b64decode(_JPEG_7X3_B64)
# Re-verified 2026-09-15 with hashlib alone (no Pillow):
#   len(_JPEG_7X3) == 286
#   hashlib.sha256(_JPEG_7X3).hexdigest() == _JPEG_7X3_SHA256
# Both matched on the first try; no discrepancy to escalate.
_JPEG_7X3_SHA256 = "b83ae4bbbdc15dfb5c89c274a847d3a27f0f6ae419f2e73f39c59f849570ce74"

# PO-2(c): a header-valid, body-corrupt PNG -- the standard-library builder
# above with its IDAT payload replaced by garbage, 81 bytes, IHDR declaring
# 13x29. This is the fixture PO-3 depends on: Image.open() must accept it (a
# valid header) and img.load() must reject it (corrupt compressed data) -- DV-1
# below, owned by GATES.
_CORRUPT_PNG_13X29_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAA0AAAAdCAIAAAD+X3GwAAAAGElEQVSZmZmZmZmZmZmZmZmZmZmZ\n"
    "mZmZmZmZmZmOk9WIAAAAAElFTkSuQmCC\n"
)
_CORRUPT_PNG_13X29 = base64.b64decode(_CORRUPT_PNG_13X29_B64)

# PO-3's first fixture: bytes that are not an image at all, so `Image.open()`
# itself must refuse them -- the case a header-only reader would also reject,
# and the reason AC-5 needs a *second*, header-valid fixture to mean anything.
_GARBAGE_BYTES = b"this is not an image at all\n"


@pytest.fixture
def png_bytes() -> Callable[..., bytes]:
    """A builder: `png_bytes(width, height)` -> raw PNG bytes of that size."""
    return _png_bytes


@pytest.fixture
def jpeg_7x3_bytes() -> bytes:
    return _JPEG_7X3


@pytest.fixture
def jpeg_7x3_sha256() -> str:
    return _JPEG_7X3_SHA256


@pytest.fixture
def corrupt_png_13x29_bytes() -> bytes:
    return _CORRUPT_PNG_13X29


@pytest.fixture
def garbage_bytes() -> bytes:
    return _GARBAGE_BYTES


# -- MT-007: a 1-bit PNG builder ----------------------------------------------
#
# `RawRegion.mask` is "PNG-encoded 1-bit, page-sized" (MT-007 C-7), and the
# domain may not import an encoder: `architecture.md` §3 contract 2 forbids
# `domain` from importing PIL. So the tests that exercise the type, and the
# store round trip of AC-5, need mask bytes built with the standard library
# alone - `zlib` and `struct`, the same two `_png_bytes` above uses.
#
# Bit depth 1, colour type 0 (greyscale): one bit per pixel, MSB first, `1` =
# set. That is exactly what `Image.open(...).mode == "1"` reads back, and what
# `tests/core/test_detect_postprocess.py` asserts of the shipped encoder by
# parsing IHDR directly.


def _one_bit_png(width: int, height: int, rects: Sequence[tuple[int, int, int, int]]) -> bytes:
    """A 1-bit PNG of `width` x `height`, with every half-open `rect` set.

    `rects` are `(x0, y0, x1, y1)` covering `x0 <= x < x1` and `y0 <= y < y1`,
    the same half-open convention `fixtures/detect/README.md` pins.
    """
    stride = (width + 7) // 8
    raw = bytearray()
    for y in range(height):
        row = bytearray(stride)
        for x0, y0, x1, y1 in rects:
            if y0 <= y < y1:
                for x in range(max(0, x0), min(width, x1)):
                    row[x // 8] |= 0x80 >> (x % 8)
        raw += b"\x00" + row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def one_bit_png() -> Callable[..., bytes]:
    """A builder: `one_bit_png(width, height, [(x0, y0, x1, y1), ...])`."""
    return _one_bit_png


# -- MT-009: one page-sized mask, built once per session -----------------------
#
# MEASURED 2026-09-16 (RED, this machine, uv run python): `_one_bit_png` above
# is a per-pixel Python loop, so a page-sized mask with every pixel set costs
# **281 ms** and one with a single 8x8 rect costs **7 ms**. MT-009's AC-5 is a
# `hypothesis` property over up to eight regions at 100 examples; encoding a
# mask per example would cost seconds to minutes under the coverage gate's
# instrumentation. Reading order never looks at `mask` - it is geometry only -
# so one shared page-sized constant is both cheap and faithful to MT-007 C-7
# ("PNG-encoded 1-bit, page-sized"). Session scope, not module scope, so the
# hypothesis health check for function-scoped fixtures never applies.
#
# The page is 1125x1600, the size of every scan under `spikes/MT-002/pages/`.


@pytest.fixture(scope="session")
def page_mask() -> bytes:
    """A 1125x1600 1-bit PNG with one small rect set. Built once per session."""
    return _one_bit_png(1125, 1600, [(0, 0, 8, 8)])


# -- MT-011: a fake structured-output `Message`, and the recorded bodies -------
#
# `mangatl.translate.parse.parse_lines` takes an `anthropic.types.Message`
# (MT-011 C-4). No test in MT-011 makes a network call or constructs a real
# `Anthropic` client, so what it is handed here is a duck-typed stand-in built
# out of the standard library.
#
# The stand-in is faithful in the two ways that matter, both from the Anthropic
# API reference (MT-011 PO-5, re-read in RED):
#
# * **structured output puts the JSON in a `text` content block** -
#   `output_config.format` guarantees a text block carrying valid JSON, reached
#   as `next(b.text for b in response.content if b.type == "text")`;
# * **adaptive thinking can put a `thinking` block in front of it** (C-5 pins
#   `thinking={"type": "adaptive"}`), and a thinking block has `.thinking`, not
#   `.text`. So `_FakeThinkingBlock` deliberately has **no** `text` attribute:
#   an implementation reaching for `response.content[0].text` fails with an
#   `AttributeError` naming it rather than silently reading an empty string.
#
# `usage` carries the four fields C-5 names and C-2 converts to `TokenUsage`.

#: Where `fixtures/translate/*.json` lives, relative to this file.
_TRANSLATE_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "translate"


@dataclass(frozen=True)
class FakeUsage:
    """`response.usage`, with the four fields MT-011 C-5 reads off it."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass(frozen=True)
class FakeThinkingBlock:
    """A `thinking` block. Note the absence of a `text` attribute - see above."""

    thinking: str = ""
    type: str = "thinking"


@dataclass(frozen=True)
class FakeMessage:
    content: tuple[FakeTextBlock | FakeThinkingBlock, ...]
    usage: FakeUsage = FakeUsage()
    stop_reason: str = "end_turn"


def _fake_message(
    body: str,
    *,
    leading_thinking: bool = False,
    usage: FakeUsage | None = None,
    stop_reason: str = "end_turn",
) -> FakeMessage:
    """A `Message`-shaped value whose text block carries `body` verbatim."""
    blocks: list[FakeTextBlock | FakeThinkingBlock] = []
    if leading_thinking:
        blocks.append(FakeThinkingBlock())
    blocks.append(FakeTextBlock(text=body))
    return FakeMessage(
        content=tuple(blocks),
        usage=usage if usage is not None else FakeUsage(),
        stop_reason=stop_reason,
    )


@pytest.fixture
def fake_message() -> Callable[..., FakeMessage]:
    """A builder: `fake_message(body, leading_thinking=..., usage=...)`."""
    return _fake_message


def _response_body(name: str) -> str:
    """One recorded body from `fixtures/translate/`, as **text**.

    `read_text` and never `json.load`: key order is what MT-011's falsifiable
    success condition 1 is about, and round-tripping through a `dict` and back
    out of `json.dumps` would silently normalise it. See that folder's README.
    """
    return (_TRANSLATE_FIXTURES / f"{name}.json").read_text(encoding="utf-8")


@pytest.fixture
def response_body() -> Callable[[str], str]:
    """A loader: `response_body("well-formed")` -> the raw JSON body text."""
    return _response_body


@pytest.fixture
def fake_usage() -> type[FakeUsage]:
    """The `usage` type `fake_message` accepts, for a test that needs to set
    the four counts to distinct values and check where each one landed."""
    return FakeUsage
