"""Does each answer entry repeat its own region's Japanese? (MT-149)

Every translation answer entry is `{"ja": <the region's Japanese, repeated>,
"en": <English>}`. The model copies the Japanese listed under a key back into
`ja`; an entry whose `ja` is not close to the text listed under its own key is
**misaligned** - the model's answer slipped by a region, so its English belongs
to some other bubble. `checked_lines` drops that English and names the key, and
the store records the region as one whose translation did not line up.

A repeated line is not a slip: two regions with identical Japanese whose
entries swap both match, and both English lines are right for either (AC-4).

Pure and standard-library only: `domain` is independent (architecture.md §3).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "ECHO_MAX_EDIT_RATIO",
    "AnswerEntry",
    "CheckedLines",
    "checked_lines",
    "echo_matches",
]

#: The largest edit distance, as a share of the longer string's characters,
#: at which an echo still counts as a copy of its listing (OCR noise the model
#: corrected). Oracle-free (MT-149 C-3): measured gap [0.25, 0.875) - a
#: four-character line with one character changed (0.25) must pass, and p017's
#: nearest shifted echo that is not its own region's text (entry 7, 0.875) must
#: fail. 0.4 passes one wrong character in three and still fails p017's siren
#: pair (0.571).
ECHO_MAX_EDIT_RATIO: float = 0.4


@dataclass(frozen=True)
class AnswerEntry:
    """One answer entry: the Japanese the model echoed, and its English."""

    ja: str
    en: str


@dataclass(frozen=True)
class CheckedLines:
    """The English of every entry whose echo matched, and the keys that did not.

    A key the answer omitted is in neither.
    """

    lines: dict[int, str]
    misaligned: frozenset[int]


def _comparable(text: str) -> str:
    """NFKC, with every `str.isspace()` character removed."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", text) if not ch.isspace())


def _levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def echo_matches(listed: str, echoed: str) -> bool:
    """True when `echoed` is a close enough copy of `listed`.

    An empty listing (after normalising) matches anything: the model read that
    bubble itself (`ocr_empty`).
    """
    left = _comparable(listed)
    if not left:
        return True
    right = _comparable(echoed)
    ratio = _levenshtein(left, right) / max(len(left), len(right))
    return ratio <= ECHO_MAX_EDIT_RATIO


def checked_lines(entries: Mapping[int, AnswerEntry | None], listed: Sequence[str]) -> CheckedLines:
    """Keep each entry whose `ja` echoes `listed[key]`; name the others.

    A `None` entry - one the parser found malformed (MT-149 PO-4) - is
    misaligned without consulting the listing, so even an empty listing, which
    matches any echo, does not accept it.
    """
    lines: dict[int, str] = {}
    misaligned: set[int] = set()
    for key, entry in entries.items():
        if entry is not None and echo_matches(listed[key], entry.ja):
            lines[key] = entry.en
        else:
            misaligned.add(key)
    return CheckedLines(lines=lines, misaligned=frozenset(misaligned))
