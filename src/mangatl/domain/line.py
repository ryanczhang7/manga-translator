"""What OCR read off one region: the text, and whether the model said anything.

**`ocr_empty` means "the model emitted no tokens", not "the text is empty"**
(MT-010 C-5). The two differ, and the difference is the whole reason the flag
exists:

* an **empty token sequence** is the decoder emitting EOS immediately - the model
  declined to read anything;
* a sequence of **special tokens only** decodes to `""` and is a *successful*
  read whose printable content happens to be nothing.

So `__post_init__` enforces the one direction that must hold - `ocr_empty`
implies `text == ""` - and deliberately **not** the converse. A flag enforced in
both directions is `text == ""` spelled twice, carries no information, and makes
MT-010 AC-4's negative control unfailable.

The flag is stored rather than derived (MT-010 PO-3), which is what makes the
three states a reopened project has to distinguish tellable apart: **no `line`
row** (OCR has not run), **a row with `ocr_empty = 1`** (the model emitted
nothing), **a row with `source_ja`** (read).

`domain` imports nothing of ours and no third-party package (`architecture.md`
§3 contract 2), which is why this is a value and the decoding that produces it
lives in `mangatl.ocr`.

**A line under review (MT-017 C-1..C-4).** `Line` is one bubble's text as the
review screen holds it: what OCR read, what the model proposed, what the user
committed, and the status that says which of those the user has looked at.
Status is `proposed / accepted / edited / reverted / failed`; only the middle
three are *acts* and only they are stored (`COMMITTED_STATUSES`). `proposed` and
`failed` are derived from the pipeline's facts by `derive_status`, so a file
never says "proposed" about a line a user has never touched - it says nothing.

`normalise` is the O2 definition of `docs/wiki/stack.md` §5, verbatim: NFC,
every whitespace run to one space, strip - and nothing else. MT-022 measures the
headline metric with it, which is why it lives here and exists once.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

__all__ = [
    "COMMITTED_STATUSES",
    "LINE_STATUSES",
    "Line",
    "LineStatus",
    "OcrResult",
    "derive_status",
    "effective_text",
    "failure_reason",
    "is_accepted_as_is",
    "normalise",
]

LineStatus = Literal["proposed", "accepted", "edited", "reverted", "failed"]

#: The design vocabulary (components.md §5), in its order.
LINE_STATUSES: tuple[LineStatus, ...] = ("proposed", "accepted", "edited", "reverted", "failed")

#: The three statuses a user's act writes. `proposed` and `failed` are never
#: stored; they are derived (`derive_status`).
COMMITTED_STATUSES: frozenset[LineStatus] = frozenset({"accepted", "edited", "reverted"})

_REASON_OCR_EMPTY = "no text was read in this bubble"
_REASON_UNTRANSLATED = "no translation was returned"


@dataclass(frozen=True)
class Line:
    """One region's line as the review screen holds it (C-1).

    Addressed by `reading_index`, not the database's `region.id`: every line
    address outside the store is `(page_ordinal, reading_index)`.
    `proposed_en is None` means no proposal; `final_en is None` means the user
    has committed no text (an `accepted` line keeps it `None` - the text is the
    proposal's). `edited_at` is tz-aware UTC, the time of the last commit.
    """

    reading_index: int
    source_ja: str
    proposed_en: str | None
    final_en: str | None
    status: LineStatus
    edited_at: datetime | None
    ocr_empty: bool = False


def normalise(text: str) -> str:
    """O2's comparison form: NFC, every whitespace run to one U+0020, stripped.

    "Whitespace" is exactly `str.isspace()`. No case fold, no punctuation strip,
    no NFKC: each of those would change the product's headline number (C-3).
    """
    return " ".join(unicodedata.normalize("NFC", text).split())


def effective_text(line: Line) -> str:
    """The text the line shows: the committed text, else the proposal, else `""`.

    `is None` tests, not `or`: a committed `""` is a deleted line, and deleting
    the line is a rejection, not a fall-back to the proposal (C-4).
    """
    if line.final_en is not None:
        return line.final_en
    if line.proposed_en is not None:
        return line.proposed_en
    return ""


def is_accepted_as_is(line: Line) -> bool:
    """O2: the shown text equals the proposal after `normalise`. Reads no status."""
    return line.proposed_en is not None and normalise(line.proposed_en) == normalise(
        effective_text(line)
    )


def derive_status(
    stored: str | None, *, ocr_empty: bool, proposed_en: str | None, page_done: bool
) -> LineStatus:
    """A line's status from what is stored (C-2's four rules, in order).

    A user's act outranks the pipeline's flags; then `ocr_empty` is failed; then
    no proposal on a page the run finished is failed; otherwise proposed. A
    stored value outside `COMMITTED_STATUSES` is a corrupt file and raises.
    """
    if stored is not None:
        for status in COMMITTED_STATUSES:
            if stored == status:
                return status
        raise ValueError(
            f"line.status {stored!r} is not a user act; the column holds only"
            f" {sorted(COMMITTED_STATUSES)} or NULL"
        )
    if ocr_empty or (proposed_en is None and page_done):
        return "failed"
    return "proposed"


def failure_reason(line: Line) -> str | None:
    """Why a `failed` line failed, in the row's words; `None` for any other status."""
    if line.status != "failed":
        return None
    return _REASON_OCR_EMPTY if line.ocr_empty else _REASON_UNTRANSLATED


@dataclass(frozen=True)
class OcrResult:
    """One region's transcription, and whether the model emitted anything at all.

    Frozen because it is a value: two results with the same text and the same
    flag *are* the same result, and nothing downstream mutates one after it is
    built. `ocr_empty` defaults to `False` so that every construction site
    holding real text need not mention it.
    """

    text: str
    ocr_empty: bool = False

    def __post_init__(self) -> None:
        if self.ocr_empty and self.text:
            raise ValueError(
                "ocr_empty means the model emitted no tokens, so the text must be"
                f" empty; got {self.text!r}. An empty text WITHOUT the flag is legal"
                " and is a successful read of nothing printable (MT-010 C-5)."
            )
