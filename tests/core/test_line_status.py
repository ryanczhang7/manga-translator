"""MT-017 C-1..C-4: a line's status, and the O2 definition of "accepted as-is".

Everything here is in `mangatl.domain.line`, beside MT-010's `OcrResult`, and is
pure: no project, no Qt.

**`normalise` is SETTLED, not designed** (C-3, `docs/wiki/stack.md` §5/O2):
NFC, every whitespace run collapsed to one space, strip - and nothing else. The
headline success metric S1 is computed with it (MT-022), so a `normalise` that
"helpfully" case-folds, strips punctuation or applies NFKC has silently changed
the product's number. The tests below therefore pin both halves:

- what it DOES, as examples and as `hypothesis` properties over the default
  `st.text()` domain;
- what it does NOT do, as rejections: a case-only difference and a
  punctuation-only difference are both *not* accepted as-is (the story's
  falsifiable success condition), full-width `\uff21` is left alone (no NFKC), and
  the content-preservation property says every non-whitespace character of the
  NFC input survives, in order - which no case fold, punctuation strip or
  compatibility fold can pass.

**The one generator narrowing.** `st.text()` by default excludes lone
surrogates (category Cs). That is the only exclusion, and its design clause is
C-3's: a Python `str` read from SQLite or from a Qt widget cannot carry one. No
other filter is applied to any generator in this file.

**Timing.** No `pytest-timeout` in this project; nothing here waits. The
properties run 200 examples of short strings, well under a second each.
"""

from __future__ import annotations

import dataclasses
import itertools
import unicodedata
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mangatl.domain.line import (
    COMMITTED_STATUSES,
    LINE_STATUSES,
    Line,
    derive_status,
    effective_text,
    failure_reason,
    is_accepted_as_is,
    normalise,
)

#: C-2's two failure reasons, read out of the contract.
REASON_OCR_EMPTY = "no text was read in this bubble"
REASON_UNTRANSLATED = "no translation was returned"


def _line(
    proposed_en: str | None = "Hello.",
    final_en: str | None = None,
    status: str = "proposed",
    *,
    ocr_empty: bool = False,
) -> Line:
    return Line(
        reading_index=0,
        source_ja="こんにちは。",
        proposed_en=proposed_en,
        final_en=final_en,
        status=status,  # type: ignore[arg-type]
        edited_at=None,
        ocr_empty=ocr_empty,
    )


# =============================================================================
# C-1 - the value and the status vocabulary
# =============================================================================


def test_the_five_statuses_are_exactly_the_design_vocabulary_in_order() -> None:
    assert LINE_STATUSES == ("proposed", "accepted", "edited", "reverted", "failed")


def test_only_the_three_user_acts_are_committed_statuses() -> None:
    """`proposed` and `failed` are derived, never stored (C-2)."""
    assert frozenset({"accepted", "edited", "reverted"}) == COMMITTED_STATUSES


def test_a_line_carries_its_reading_index_not_a_region_id_in_the_contract_field_order() -> None:
    names = tuple(field.name for field in dataclasses.fields(Line))
    assert names == (
        "reading_index",
        "source_ja",
        "proposed_en",
        "final_en",
        "status",
        "edited_at",
        "ocr_empty",
    )


def test_a_line_is_a_frozen_value_whose_ocr_empty_defaults_to_false() -> None:
    line = Line(
        reading_index=3,
        source_ja="ja",
        proposed_en="en",
        final_en=None,
        status="proposed",
        edited_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    assert line.ocr_empty is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        line.final_en = "changed"  # type: ignore[misc]


# =============================================================================
# C-3 - normalise IS the O2 definition: examples
# =============================================================================


def test_normalise_collapses_no_break_and_ideographic_spaces_and_strips_a_trailing_newline() -> (
    None
):
    assert normalise("a\u00a0\u3000b\n") == "a b"


def test_normalise_composes_an_nfd_accent_to_its_nfc_form() -> None:
    assert normalise("e\u0301") == "\u00e9"


def test_normalise_leaves_a_full_width_letter_alone_because_o2_is_nfc_not_nfkc() -> None:
    assert normalise("\uff21") == "\uff21"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("", "", id="empty"),
        pytest.param("   ", "", id="only-spaces"),
        pytest.param("Hello.", "Hello.", id="already-normal"),
        pytest.param("  Hello  world  ", "Hello world", id="double-and-edge-spaces"),
        pytest.param("a\tb\r\nc\u2028d\u2029e", "a b c d e", id="line-break-markers"),
        pytest.param("*italic* **bold**", "*italic* **bold**", id="emphasis-is-literal"),
    ],
)
def test_normalise_is_nfc_then_whitespace_collapsed_then_stripped(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_normalise_keeps_capitalisation() -> None:
    assert normalise("Hello.") != normalise("hello.")


def test_normalise_keeps_punctuation() -> None:
    assert normalise("Hello.") != normalise("Hello!")


# =============================================================================
# C-3 - properties over the default st.text() domain (surrogates excluded by
# st.text() itself; that is the only narrowing, see the module docstring)
# =============================================================================


@settings(deadline=None, max_examples=200)
@given(st.text())
def test_normalise_is_idempotent(text: str) -> None:
    once = normalise(text)
    assert normalise(once) == once


@settings(deadline=None, max_examples=200)
@given(st.text())
def test_nfd_and_nfc_spellings_of_the_same_text_normalise_identically(text: str) -> None:
    assert normalise(unicodedata.normalize("NFD", text)) == normalise(
        unicodedata.normalize("NFC", text)
    )


@settings(deadline=None, max_examples=200)
@given(st.text())
def test_normalised_text_has_no_edge_whitespace_no_runs_and_no_whitespace_but_u0020(
    text: str,
) -> None:
    out = normalise(text)
    problems = []
    if out and (out[0].isspace() or out[-1].isspace()):
        problems.append("leading or trailing whitespace")
    if any(a.isspace() and b.isspace() for a, b in itertools.pairwise(out)):
        problems.append("two consecutive whitespace characters")
    if any(c.isspace() and c != " " for c in out):
        problems.append("whitespace other than U+0020")
    assert not problems, f"normalise({text!r}) == {out!r}: {problems}"


@settings(deadline=None, max_examples=200)
@given(st.text())
def test_normalise_keeps_every_non_whitespace_character_of_the_nfc_text_in_order(
    text: str,
) -> None:
    """ "Nothing else" as a property: no case fold, no punctuation strip, no
    compatibility fold survives this, because each removes or rewrites a
    non-whitespace character."""
    nfc = unicodedata.normalize("NFC", text)
    assert normalise(text).replace(" ", "") == "".join(c for c in nfc if not c.isspace())


# =============================================================================
# C-4 - effective_text and is_accepted_as_is
# =============================================================================


@pytest.mark.parametrize(
    ("proposed_en", "final_en", "expected"),
    [
        pytest.param("Hello.", None, "Hello.", id="uncommitted-shows-the-proposal"),
        pytest.param("Hello.", "Bye.", "Bye.", id="committed-text-wins"),
        pytest.param("Hello.", "", "", id="a-committed-empty-line-is-empty-not-the-proposal"),
        pytest.param(None, "Mine.", "Mine.", id="no-proposal-but-user-text"),
        pytest.param(None, None, "", id="nothing-at-all"),
    ],
)
def test_effective_text_is_the_committed_text_else_the_proposal_else_empty(
    proposed_en: str | None, final_en: str | None, expected: str
) -> None:
    assert effective_text(_line(proposed_en, final_en)) == expected


def test_a_deleted_line_is_a_rejection_not_an_acceptance_of_the_proposal() -> None:
    """C-4's trap: `final_en or proposed_en` would call this accepted."""
    assert is_accepted_as_is(_line("Hello.", "", "edited")) is False


def test_a_capitalisation_only_change_is_a_rejection() -> None:
    assert is_accepted_as_is(_line("Hello.", "hello.", "edited")) is False


def test_a_punctuation_only_change_is_a_rejection() -> None:
    assert is_accepted_as_is(_line("Hello.", "Hello!", "edited")) is False


def test_a_one_word_fix_is_a_rejection() -> None:
    assert is_accepted_as_is(_line("I am go home.", "I am going home.", "edited")) is False


@pytest.mark.parametrize(
    ("proposed_en", "final_en", "status"),
    [
        pytest.param("Hello.", None, "proposed", id="unreviewed-proposal"),
        pytest.param("Hello.", None, "accepted", id="accepted"),
        pytest.param("Hello.", "Hello.", "reverted", id="reverted-exactly"),
        pytest.param("Hello  world ", "Hello world", "edited", id="whitespace-only-edit"),
        pytest.param("caf\u00e9", "cafe\u0301", "edited", id="nfd-spelling-of-the-same-text"),
    ],
)
def test_text_equal_to_the_proposal_under_o2_is_accepted_whatever_the_status(
    proposed_en: str, final_en: str | None, status: str
) -> None:
    """O2 compares strings, not history: status is not read (C-4)."""
    assert is_accepted_as_is(_line(proposed_en, final_en, status)) is True


@pytest.mark.parametrize("final_en", [None, "", "Mine."])
def test_a_line_with_no_proposal_is_never_accepted_as_is(final_en: str | None) -> None:
    assert is_accepted_as_is(_line(None, final_en, "edited" if final_en else "failed")) is False


# =============================================================================
# C-2 - derive_status and failure_reason
# =============================================================================


@pytest.mark.parametrize(
    ("stored", "ocr_empty", "proposed_en", "page_done", "expected"),
    [
        # rule 1: a user's act outranks everything
        pytest.param("accepted", False, "Hi", True, "accepted", id="stored-accepted"),
        pytest.param("edited", False, "Hi", False, "edited", id="stored-edited"),
        pytest.param("reverted", False, "Hi", True, "reverted", id="stored-reverted"),
        pytest.param("edited", True, None, True, "edited", id="user-typed-into-an-ocr-empty"),
        pytest.param("edited", False, None, True, "edited", id="user-typed-into-untranslated"),
        # rule 2: ocr_empty is failed whatever the page status
        pytest.param(None, True, None, False, "failed", id="ocr-empty-page-not-done"),
        pytest.param(None, True, None, True, "failed", id="ocr-empty-page-done"),
        # rule 3: no proposal on a finished page
        pytest.param(None, False, None, True, "failed", id="untranslated-on-a-done-page"),
        # rule 4
        pytest.param(None, False, None, False, "proposed", id="not-yet-translated-page"),
        pytest.param(None, False, "Hi", True, "proposed", id="proposal-on-a-done-page"),
        pytest.param(None, False, "", True, "proposed", id="empty-proposal-is-a-proposal"),
    ],
)
def test_derive_status_follows_c2_rules_in_order(
    stored: str | None, ocr_empty: bool, proposed_en: str | None, page_done: bool, expected: str
) -> None:
    got = derive_status(stored, ocr_empty=ocr_empty, proposed_en=proposed_en, page_done=page_done)
    assert got == expected


@pytest.mark.parametrize("stored", ["proposed", "failed", "banana", ""])
def test_a_stored_status_outside_the_committed_three_is_refused_as_corrupt(stored: str) -> None:
    with pytest.raises(ValueError):
        derive_status(stored, ocr_empty=False, proposed_en="Hi", page_done=False)


def test_an_ocr_empty_failed_line_says_no_text_was_read() -> None:
    line = _line(None, None, "failed", ocr_empty=True)
    assert failure_reason(line) == REASON_OCR_EMPTY


def test_an_untranslated_failed_line_says_no_translation_was_returned() -> None:
    assert failure_reason(_line(None, None, "failed")) == REASON_UNTRANSLATED


@pytest.mark.parametrize("status", ["proposed", "accepted", "edited", "reverted"])
def test_a_line_that_has_not_failed_has_no_failure_reason(status: str) -> None:
    # ocr_empty=True on an edited line too: the reason follows status, not the flag.
    assert failure_reason(_line(None, "x", status, ocr_empty=True)) is None
