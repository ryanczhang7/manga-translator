"""One change the consistency pass made to a line's English (MT-103 AC-5).

MT-115's pass reads a whole chapter and may change a line it already
translated; the store keeps what it changed, from what, and why, so the change
is reviewable rather than silent. Addressed as every line is outside the store,
by `(page_ordinal, reading_index)`.

MT-114 adds the pass's own values beside it: `ProposedCorrection` (one line
the pass would change, not yet applied), `ParsedCorrections` (a chunk's parsed
answer and how many items it restated unchanged), and `ConsistencyResult` (one
chunk's raw answer, usage and call identity). Like every domain value they are
branch-free frozen dataclasses - `coverage-core` holds `domain/**` at 100% with
branch coverage, so validation lives in the parse, not here.
"""

from __future__ import annotations

from dataclasses import dataclass

from mangatl.domain.translation import CallInfo, TokenUsage

__all__ = ["ConsistencyResult", "Correction", "ParsedCorrections", "ProposedCorrection"]


@dataclass(frozen=True)
class Correction:
    """`before_en` became `after_en` for `reason`, in run `run_id`."""

    run_id: int
    page_ordinal: int
    reading_index: int
    before_en: str
    after_en: str
    reason: str


@dataclass(frozen=True)
class ProposedCorrection:
    """The pass would make line `reading_index` of page `page_ordinal` say
    `corrected_en`, for `reason`.

    `page_ordinal` is 0-based, the store's key; the prompt and the response
    speak 1-based `Page {n}`, and `consistency.parse_corrections` converts.
    """

    page_ordinal: int
    reading_index: int
    corrected_en: str
    reason: str


@dataclass(frozen=True)
class ParsedCorrections:
    """A chunk's changed lines in response order, and the count of items it
    returned equal to the current English - the observable that says whether
    the model obeys "corrections only" (EPIC-09 PO-6)."""

    corrections: tuple[ProposedCorrection, ...]
    unchanged_returned: int


@dataclass(frozen=True)
class ConsistencyResult:
    """One consistency-pass chunk on a provider: the raw, unparsed answer, its
    usage and the call identity the ledger row records (MT-115)."""

    text: str
    usage: TokenUsage
    call: CallInfo
