"""Reading a folder of scans into a `Chapter`.

This is the input boundary of the whole product: one folder is one chapter, its
pages are the `.png`/`.jpg`/`.jpeg` files directly inside it, and they are
ordered by `domain.page.order_filenames`. Subdirectories are not descended into
- nesting is not a chapter structure this product recognises.

**The input folder is the user's scans and is never written to**
(`architecture.md` §5). Every file here is opened for reading only, and the
decode runs against bytes already in memory rather than against the file, so
there is no handle through which anything could be written back.

Why `img.load()` and not `Image.open()` or `img.verify()`: measured against
Pillow 12.3.0 on a PNG with a valid signature, a valid `IHDR` declaring 13x29,
an `IDAT` of junk and a valid `IEND`, `open()` succeeds and reports
`size == (13, 29)`, `verify()` also succeeds, and only `load()` raises
`OSError: broken data stream when reading image file`. A reader built on either
of the first two accepts a corrupt scan and reports a confident width and
height for it. (Re-measured in GREEN on the resolved Pillow 12.3.0; the
alternatives `tobytes()`, `getpixel()` and `getdata()` all reject the same
fixture only because they call `load()` themselves, so none is cheaper.)
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

from mangatl.domain.page import PAGE_SUFFIXES, Chapter, Page, order_filenames

__all__ = ["NoPagesFound", "UnreadablePage", "read_chapter"]


class NoPagesFound(Exception):
    """A folder held no page scans at all - which is not an empty chapter."""


class UnreadablePage(Exception):
    """A file with a page suffix whose bytes could not be decoded.

    Raised on the *first* undecodable file in reading order, aborting the read
    rather than returning a partial chapter: a partial chapter would give every
    later page a wrong ordinal, and the ordinal is the page's identity for the
    rest of the product.
    """


def read_chapter(source_dir: Path) -> Chapter:
    """Read `source_dir` as one chapter of pages, in filename order.

    Raises `NoPagesFound` if the folder holds no page scans, and
    `UnreadablePage` if one of them cannot be decoded. Nothing inside
    `source_dir` is created, modified or deleted.
    """
    names = [
        entry.name
        for entry in source_dir.iterdir()
        if entry.is_file() and entry.suffix.lower() in PAGE_SUFFIXES
    ]
    if not names:
        raise NoPagesFound(f"no pages found in {source_dir}")

    pages = []
    for ordinal, filename in enumerate(order_filenames(names)):
        raw = (source_dir / filename).read_bytes()
        try:
            with Image.open(BytesIO(raw)) as img:
                # The integrity call. `open()` only parses the header; `load()`
                # is what pulls the pixel data through the decoder and is the
                # only one of the three that rejects a corrupt body.
                img.load()
                width, height = img.size
        except OSError as error:
            raise UnreadablePage(f"cannot decode page {filename}: {error}") from error
        pages.append(
            Page(
                ordinal=ordinal,
                filename=filename,
                width=width,
                height=height,
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return Chapter(source_dir=source_dir, pages=tuple(pages))
