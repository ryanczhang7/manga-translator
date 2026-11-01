"""One change the consistency pass made to a line's English (MT-103 AC-5).

MT-115's pass reads a whole chapter and may change a line it already
translated; the store keeps what it changed, from what, and why, so the change
is reviewable rather than silent. Addressed as every line is outside the store,
by `(page_ordinal, reading_index)`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Correction"]


@dataclass(frozen=True)
class Correction:
    """`before_en` became `after_en` for `reason`, in run `run_id`."""

    run_id: int
    page_ordinal: int
    reading_index: int
    before_en: str
    after_en: str
    reason: str
