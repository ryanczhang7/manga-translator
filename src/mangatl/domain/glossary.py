"""The chapter glossary and the rolling context, as pure values (MT-014 C-1).

Two blocks of text reach every page's request after the first: the glossary -
names, honorifics and places the chapter has already settled on - and the
previous page's proposed English. Together they are the ~900 tokens a page that
`docs/wiki/cost-model.awk`'s `ROLLING` budgets for, split 400 / 500, and the caps
below are what keep the $1.14 chapter estimate honest (`stack.md` §5/O4).

**One counter, `estimate_tokens`.** `ceil(utf-8 bytes / 3)`: Japanese is about
three bytes and one token per character, English about four characters per
token, so English is over-counted by roughly a third. That is the safe direction
for a budget cap, and it needs no tokenizer.

**Eviction is least-recently-SEEN first, and it is greedy** (AC-3, PO-3). The
sort key is `(source == "user", last_seen_page, first_seen_page, term_ja)`:
every model entry goes before any user entry, and within a source the entry
last sighted longest ago goes first. Entries are removed one at a time, in that
order, until the block fits - so what survives is always a suffix of the
eviction order, and a small stale entry is never kept in place of a larger
fresh one. Eviction is render-only: the store keeps every entry.

Branch-light on purpose: this module is under `coverage-core`'s 100 % branch
floor, so every `if` owes a test per arm.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from math import ceil
from typing import Literal

__all__ = [
    "EMPTY_CONTEXT",
    "MAX_GLOSSARY_TOKENS",
    "MAX_ROLLING_TOKENS",
    "GlossaryEntry",
    "Note",
    "PromptContext",
    "ProposedTerm",
    "Source",
    "estimate_tokens",
    "mark_seen",
    "merge",
    "render_block",
    "render_rolling",
]

#: The glossary block's cap. With `MAX_ROLLING_TOKENS`, 900 == cost-model.awk's
#: `ROLLING`; retuning one without the other breaks the chapter estimate.
MAX_GLOSSARY_TOKENS: int = 400

#: The rolling block's cap (the previous page's proposed English).
MAX_ROLLING_TOKENS: int = 500

Note = Literal["name", "honorific", "place", ""]
Source = Literal["model", "user"]

_GLOSSARY_HEADER = "Glossary - use these renderings exactly:"
_ROLLING_HEADER = "Previous page, in reading order:"


@dataclass(frozen=True)
class ProposedTerm:
    """One term one response proposed. No page yet: `merge` supplies it."""

    term_ja: str
    term_en: str
    note: str


@dataclass(frozen=True)
class GlossaryEntry:
    """One settled rendering, and when the chapter last saw it.

    `first_seen_page` and `last_seen_page` are page ordinals, 0-based (MT-004).
    `source` is `"user"` once the user's own edit has set `term_en` (AC-2).
    """

    term_ja: str
    term_en: str
    note: str
    first_seen_page: int
    last_seen_page: int
    source: Source


@dataclass(frozen=True)
class PromptContext:
    """The two page-varying blocks a request carries after the cache breakpoint.

    Not `PageContext`: `pipeline.stage` already has one.
    """

    glossary_block: str
    rolling_block: str


#: Page 1's context (AC-5). `build_request` compares against it by value.
EMPTY_CONTEXT: PromptContext = PromptContext("", "")


def estimate_tokens(text: str) -> int:
    """`ceil(len(text.encode("utf-8")) / 3)` - the one token counter."""
    return ceil(len(text.encode("utf-8")) / 3)


def merge(
    entries: Sequence[GlossaryEntry], proposed: Sequence[ProposedTerm], page: int
) -> list[GlossaryEntry]:
    """Fold one page's model proposals into the chapter's entries.

    A new `term_ja` is appended as a model entry first and last seen on `page`.
    A known one keeps everything it has - rendering, note, first sighting and
    source, whatever the source - and only `last_seen_page` moves forward:
    continuity is the point, and a later page's different rendering is exactly
    the inconsistency this story ends. That same rule makes the first of two
    proposals for one term in a batch the one that wins, and makes `merge`
    idempotent. A proposal with a blank side is dropped.
    """
    merged = list(entries)
    position = {entry.term_ja: index for index, entry in enumerate(merged)}
    for term in proposed:
        if not term.term_ja.strip() or not term.term_en.strip():
            continue
        if term.term_ja in position:
            index = position[term.term_ja]
            merged[index] = _seen(merged[index], page)
        else:
            position[term.term_ja] = len(merged)
            merged.append(GlossaryEntry(term.term_ja, term.term_en, term.note, page, page, "model"))
    return merged


def mark_seen(
    entries: Sequence[GlossaryEntry], source_texts: Sequence[str], page: int
) -> list[GlossaryEntry]:
    """Move `last_seen_page` forward for every entry whose `term_ja` appears in
    any of the page's OCR text - so a character on every page stays recent even
    when the model does not re-propose them."""
    return [
        _seen(entry, page) if any(entry.term_ja in text for text in source_texts) else entry
        for entry in entries
    ]


def render_block(entries: Sequence[GlossaryEntry], max_tokens: int) -> str:
    """The glossary block, evicted greedily in `_eviction_key` order until
    `estimate_tokens(block) <= max_tokens`; `""` when nothing fits or there is
    nothing to render - never a header alone. Does not touch `entries`."""
    kept = sorted(entries, key=_eviction_key)
    while estimate_tokens(block := _glossary(kept)) > max_tokens:
        kept.pop(0)
    return block


def render_rolling(lines: Sequence[str], max_tokens: int) -> str:
    """The previous page's English, dropping lines from the **start** until it
    fits - the end of the page is what the next page continues. `""` when no
    line fits or there are none."""
    kept = list(lines)
    while estimate_tokens(block := _with_header(_ROLLING_HEADER, kept)) > max_tokens:
        kept.pop(0)
    return block


def _seen(entry: GlossaryEntry, page: int) -> GlossaryEntry:
    return replace(entry, last_seen_page=max(entry.last_seen_page, page))


def _eviction_key(entry: GlossaryEntry) -> tuple[bool, int, int, str]:
    """First removed first: every model entry before any user entry, then the
    least recently SEEN; first sighting and `term_ja` only break ties."""
    return (entry.source == "user", entry.last_seen_page, entry.first_seen_page, entry.term_ja)


def _glossary(entries: Sequence[GlossaryEntry]) -> str:
    ordered = sorted(entries, key=lambda entry: (entry.first_seen_page, entry.term_ja))
    return _with_header(_GLOSSARY_HEADER, [_line(entry) for entry in ordered])


def _line(entry: GlossaryEntry) -> str:
    note = f" ({entry.note})" if entry.note else ""
    return f"{entry.term_ja} = {entry.term_en}{note}"


def _with_header(header: str, lines: Sequence[str]) -> str:
    return "\n".join([header, *lines]) if lines else ""
