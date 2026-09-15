"""Fixture bytes shared by MT-004's page-intake tests.

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
from collections.abc import Callable

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
