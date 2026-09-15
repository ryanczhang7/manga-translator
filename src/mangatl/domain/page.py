"""Pages, chapters, and the rule that puts a folder of scans in reading order.

Filename order is not string order in any sense a user expects: plain
lexicographic comparison puts `page10.png` before `page2.png`, and a chapter
delivered out of order is a chapter whose translation context is wrong on every
page. `natural_key` is the rule that fixes that, and `order_filenames` is the
total order built on it.

Nothing here touches a filesystem or a decoder. `domain` imports the standard
library and nothing else (`architecture.md` §3 contract 2), so the folder read
and the pixel decode live in `store.intake`; `Chapter.source_dir` is a `Path`
because a path is a value, not because anything here opens it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

__all__ = ["PAGE_SUFFIXES", "Chapter", "Page", "natural_key", "order_filenames"]

#: The file suffixes that count as a page scan. Matched case-insensitively by
#: `store.intake`, so `.JPG` is a page; the folding happens at the comparison,
#: not in this set.
PAGE_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg"})

# A capturing split on digit runs yields an odd-length list that always
# alternates text, digits, text, ... starting and ending with text (possibly
# empty). That is what keeps `natural_key`'s tuple SHAPE UNIFORM across every
# name: position 0, 2, 4 ... is always str and position 1, 3, 5 ... is always
# int, so two keys can never compare an int against a str and raise TypeError.
_DIGIT_RUN = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Page:
    """One scanned page of a chapter, as read at intake.

    `ordinal` is assigned after ordering and is contiguous from 0; it is the
    page's identity for the rest of the product. `sha256` is over the file's
    raw bytes, not over decoded pixels - re-encoding an identical image must
    count as a change, because the tool cannot know it is identical without
    decoding and the cheap conservative answer is the right one.
    """

    ordinal: int
    filename: str
    width: int
    height: int
    sha256: str


@dataclass(frozen=True)
class Chapter:
    """A folder of scans, in reading order.

    `source_dir` is informational: it records where the pages came from. The
    domain never opens it, and the tool never writes there (`architecture.md`
    §5).
    """

    source_dir: Path
    pages: tuple[Page, ...]


def natural_key(name: str) -> tuple[object, ...]:
    """Split `name` into alternating text and digit runs, digits as integers.

    `p2` sorts before `p10` because `2 < 10`, not because of any zero-padding
    the user may or may not have used - so `p02` and `p2` give an *equal* key.
    Case folding happens here, in the key, which is why `A.png` and `a.png` are
    also equal: making them ordered rather than equal is `order_filenames`'
    job, and it is a tie-break, not part of the natural ordering.
    """
    return tuple(
        int(part) if index % 2 else part.casefold()
        for index, part in enumerate(_DIGIT_RUN.split(name))
    )


def order_filenames(names: Iterable[str]) -> list[str]:
    """Return `names` in reading order: a total, deterministic permutation.

    The tie-break is what makes it total. Two names that fold to the same key -
    `A.png` and `a.png`, `p2.png` and `p02.png` - fall back to the raw ordering
    of the name itself, so the output does not depend on the order the
    filesystem happened to hand the names over in. AC-7 exists because a
    non-total comparator is a bug that only shows up on someone else's machine.
    """
    return sorted(names, key=lambda name: (natural_key(name), name))
