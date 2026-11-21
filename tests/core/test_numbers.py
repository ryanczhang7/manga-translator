"""MT-156: a proposal whose numbers differ from the Japanese says so in review.

`mangatl.domain.numbers` (Contract C-1) reads the numbers on each side of a
line and says when they differ. Every criterion is mechanical (C-11): the
values below are READ OUT of the story's acceptance criteria and the tables of
C-2 (`numbers_in`), C-3 (`number_mismatch`) and C-5 (`mismatch_sentence`).
They were run on the PO's scratch reference at PLANNED and are settled; none
is derived or tuned here.

`NumberMismatch` holds floats (C-1); `(100,) == (100.0,)` in Python, so the
expected tuples are written as the tables write them, and one test pins that
every value read really is a `float`.

**Negative controls.** Every `None` below is a control: it is what makes a
flagging case mean "this pair differs" rather than "this function flags
everything". In RED the module does not exist and this file fails at import,
so no assertion here, control or otherwise, has run against shipped code. The
handoff records each control's expected value, measured against a scratch
reference of C-2 to C-5, and GREEN confirms it against the shipped module.
"""

# ruff: noqa: RUF001, RUF002, RUF003
#
# RUF001/2/3 warn that a full-width character "looks like" its ASCII twin and may
# have been typed by accident. Here that is exactly inverted: the OCR stores
# full-width digits, commas and full stops (`１００`, `１，０００`, `１６．５`), and
# C-2 rule 1's NFKC step IS the difference between them and their ASCII twins.
# Every full-width character below is deliberate. Scoped to this file and these
# rules, as tests/core/test_domain_echo.py and test_ocr_decode.py are.

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from mangatl.domain import numbers
from mangatl.domain.line import Line
from mangatl.domain.numbers import (
    NumberMismatch,
    line_mismatch,
    mismatch_sentence,
    number_mismatch,
    numbers_in,
)

# --- C-2's table, read out: text -> numbers_in(text) -----------------------------
NINES = "9" * 400
NUMBERS_IN_TABLE: list[tuple[str, tuple[float, ...]]] = [
    ("１００ミリ", (100,)),
    ("1,000 milligrams", (1000,)),
    ("１，０００", (1000,)),
    ("12,345,678", (12345678,)),
    ("1,00", (0, 1)),
    ("1,0000", (0, 1)),
    ("1234,567", (567, 1234)),
    ("3.5", (3.5,)),
    ("１６．５", (16.5,)),
    ("1,000.50", (1000.5,)),
    ("3.", (3,)),
    (".5", (5,)),
    ("1.2.3", (1.2, 3)),
    ("3...4", (3, 4)),
    ("-5", (5,)),
    ("3-5", (3, 5)),
    ("３〜５", (3, 5)),
    ("3:30", (3, 30)),
    ("70%", (70,)),
    ("500cc", (500,)),
    ("B2", (2,)),
    ("1st", (1,)),
    ("007", (7,)),
    ("３万８千", (38000,)),
    ("３万８千円", (38000,)),
    ("１千１００", (1100,)),
    ("８万", (80000,)),
    ("１００万円", (1000000,)),
    ("２億", (200000000,)),
    ("５０兆", (50000000000000,)),
    ("３万８千５００", (38500,)),
    ("３万５", (30005,)),
    ("３．５万", (35000,)),
    ("1,000万", (10000000,)),
    ("１万２，０００", (12000,)),
    ("２．０１千", (2010,)),
    ("３ 万", (3,)),
    ("３万 ８千", (8000, 30000)),
    ("３万、８千", (8000, 30000)),
    ("５０兆．．．．．．５年後には８０兆", (5, 50000000000000, 80000000000000)),
    ("万", ()),
    ("千円", ()),
    ("five万", (5,)),
    ("３百", (3,)),
    ("３千万", (3000,)),
    ("２億５千万", (200005000,)),
    ("Three", (3,)),
    ("THREE", (3,)),
    ("No one", (1,)),
    ("one's", (1,)),
    ("someone", ()),
    ("none", ()),
    ("tenth", ()),
    ("first", ()),
    ("twice", ()),
    ("fourteen", (14,)),
    ("seventy", (70,)),
    ("seventeen", (17,)),
    ("twenty-five", (25,)),
    ("twenty five", (25,)),
    ("twenty, five", (5, 20)),
    ("twenty-ten", (10, 20)),
    ("ninety-nine", (99,)),
    ("a hundred", ()),
    ("three hundred", (3,)),
    ("eight thousand", (8,)),
    ("三万八千円", ()),
    ("一人", ()),
    (NINES, (float("inf"),)),
    (NINES + "万", (float("inf"),)),
]

# --- C-3's table, read out: (source_ja, english) -> number_mismatch -------------
# `None` rows are the negative controls (AC-4, DV-2).
MISMATCH_TABLE: list[tuple[str, str, tuple[tuple[float, ...], tuple[float, ...]] | None]] = [
    ("ハイドロコーン１００ミリ", "give 1000 mg", ((100,), (1000,))),
    ("ハイドロコーン１００ミリ", "give him 100 mil", None),
    ("勤務医は３人", "Three full-time doctors", None),
    ("やめろ", "Stop it", None),
    ("合計1433点", "Total points", ((1433,), ())),
    ("三万八千円", "38,000 yen", ((), (38000,))),
    ("３万８千円", "38,000 yen", None),
    ("１千１００", "1,100", None),
    ("だれも来ない", "No one came", None),
    ("一晩", "one night", None),
    ("３人", "Three doctors and one nurse", None),
    ("３人", "Two doctors", ((3,), ())),
    ("３人と３人", "three", ((3, 3), (3,))),
    ("３人と３人", "three and three and three", None),
    ("５人", "5 or five", None),
    ("５人と５匹", "5 and five", None),
    ("３人で１００ミリ", "three of us, 1000 mg", ((3, 100), (3, 1000))),
    ("２５歳", "twenty-five years old", None),
    ("２５歳", "twenty, five", ((25,), ())),
    ("８千円", "eight thousand yen", ((8000,), ())),
    ("３万８千円", "thirty-eight thousand yen", ((38000,), ())),
    ("７割", "70%", ((7,), (70,))),
    ("１．５", "1.50", None),
    ("ONE", "one", None),
    ("ja 0", "Hello.", ((0,), ())),
    ("ja-0-0", "EN-0", ((0, 0), (0,))),
]

# --- C-5's table, read out -------------------------------------------------------
SENTENCE_TABLE: list[tuple[tuple[tuple[float, ...], tuple[float, ...]], str]] = [
    ((((100,), (1000,))), "Japanese 100; English 1000 - numbers differ, check the page"),
    (((), (38000,)), "Japanese none; English 38000 - numbers differ, check the page"),
    (((1433,), ()), "Japanese 1433; English none - numbers differ, check the page"),
    (
        ((3, 100), (1.5, 3, 1000)),
        "Japanese 3, 100; English 1.5, 3, 1000 - numbers differ, check the page",
    ),
]


def _mismatch(pair: tuple[tuple[float, ...], tuple[float, ...]] | None) -> NumberMismatch | None:
    return None if pair is None else NumberMismatch(japanese=pair[0], english=pair[1])


def _line(
    status: str,
    source_ja: str,
    proposed_en: str | None,
    final_en: str | None = None,
    excluded: str | None = None,
) -> Line:
    return Line(
        reading_index=0,
        source_ja=source_ja,
        proposed_en=proposed_en,
        final_en=final_en,
        status=status,  # type: ignore[arg-type]
        edited_at=None,
        excluded=excluded,  # type: ignore[arg-type]
    )


# =============================================================================
# C-1: the module and its exports
# =============================================================================


def test_the_numbers_module_exports_exactly_the_five_names_of_the_contract() -> None:
    assert sorted(numbers.__all__) == [
        "NumberMismatch",
        "line_mismatch",
        "mismatch_sentence",
        "number_mismatch",
        "numbers_in",
    ]


def test_a_number_mismatch_is_a_frozen_value_with_a_japanese_and_an_english_side() -> None:
    mismatch = NumberMismatch(japanese=(100.0,), english=(1000.0,))

    assert (mismatch.japanese, mismatch.english) == ((100.0,), (1000.0,))
    assert mismatch == NumberMismatch((100.0,), (1000.0,))
    with pytest.raises(FrozenInstanceError):
        mismatch.japanese = ()  # type: ignore[misc]


def test_the_module_docstring_names_kanji_numerals_as_a_limit() -> None:
    """AC-5: the limit is in the module docstring (C-1, C-9)."""
    assert numbers.__doc__ is not None
    assert "kanji numerals" in numbers.__doc__.lower()


# =============================================================================
# C-2: what a number is
# =============================================================================


@pytest.mark.parametrize(("text", "expected"), NUMBERS_IN_TABLE, ids=lambda v: repr(v)[:40])
def test_numbers_in_reads_the_values_c2s_table_settles(
    text: str, expected: tuple[float, ...]
) -> None:
    assert numbers_in(text) == expected


def test_every_value_numbers_in_reads_is_a_float_in_ascending_order() -> None:
    """C-1/C-2 rule 7: `float`, ascending, duplicates kept - including the exact
    product of rule 4 (`２．０１千` is 2010.0, not 2009.9999999999998)."""
    read = numbers_in("５０兆．．．．．．５年後には８０兆 ２．０１千 and 3 and three")

    assert read == (3, 3, 5, 2010, 50000000000000, 80000000000000)
    assert all(type(value) is float for value in read), [type(v) for v in read]


def test_numbers_in_of_an_empty_string_is_empty() -> None:
    assert numbers_in("") == ()


# =============================================================================
# C-3: the comparison (AC-1 to AC-5)
# =============================================================================


@pytest.mark.parametrize(
    ("source_ja", "english", "expected"), MISMATCH_TABLE, ids=lambda v: repr(v)[:30]
)
def test_number_mismatch_gives_the_result_c3s_table_settles(
    source_ja: str,
    english: str,
    expected: tuple[tuple[float, ...], tuple[float, ...]] | None,
) -> None:
    assert number_mismatch(source_ja, english) == _mismatch(expected)


def test_a_dose_read_as_100_and_written_as_1000_is_flagged_with_both_sides() -> None:
    """AC-2, the case: p018's dose. DV-1 puts the defect back here."""
    assert number_mismatch("ハイドロコーン１００ミリ", "give 1000 mg") == NumberMismatch(
        (100,), (1000,)
    )


def test_control_the_same_dose_written_as_100_is_not_flagged() -> None:
    """AC-2's control: units are not compared (`ミリ` against `mil`)."""
    assert number_mismatch("ハイドロコーン１００ミリ", "give him 100 mil") is None


def test_control_an_english_number_word_matches_a_japanese_digit() -> None:
    """AC-3: `three` cancels the `３`."""
    assert number_mismatch("勤務医は３人", "Three full-time doctors") is None


def test_control_an_english_number_word_with_no_japanese_number_left_is_ignored() -> None:
    """AC-3's last sentence: "No one came" against Japanese with no number."""
    assert number_mismatch("だれも来ない", "No one came") is None


def test_control_a_line_with_no_numbers_on_either_side_is_not_flagged() -> None:
    """AC-4's first control."""
    assert number_mismatch("やめろ", "Stop it") is None


def test_control_two_empty_sides_are_not_flagged() -> None:
    """C-3: an empty string on either side is an empty side."""
    assert number_mismatch("", "") is None


def test_a_number_dropped_from_the_english_is_flagged_with_an_empty_english_side() -> None:
    """AC-4's second control."""
    assert number_mismatch("合計1433点", "Total points") == NumberMismatch((1433,), ())


def test_kanji_numerals_are_not_read_so_the_english_digits_stand_alone() -> None:
    """AC-5, the documented limit."""
    assert number_mismatch("三万八千円", "38,000 yen") == NumberMismatch((), (38000,))


def test_control_digits_with_kanji_multipliers_match_the_english_amount() -> None:
    """AC-1: `３万８千` is 38000."""
    assert number_mismatch("３万８千円", "38,000 yen") is None


def test_control_a_multiplied_part_then_a_bare_digit_number_adds() -> None:
    """AC-1: `１千１００` is 1100."""
    assert number_mismatch("１千１００", "1,100") is None


def test_a_wrong_number_word_still_flags_the_unmatched_japanese_number() -> None:
    """C-3: the ignored `two` is on neither side; the `３` is unmatched."""
    assert number_mismatch("３人", "Two doctors") == NumberMismatch((3,), ())


def test_each_side_of_a_mismatch_is_the_whole_side_not_the_difference() -> None:
    assert number_mismatch("３人で１００ミリ", "three of us, 1000 mg") == NumberMismatch(
        (3, 100), (3, 1000)
    )


def test_order_in_the_text_does_not_count_but_a_repeat_does() -> None:
    """C-3: multiset equality of float values. `1,000` and `1000.0` are one value."""
    assert number_mismatch("１００と１，０００", "1000.0 then 100") is None
    assert number_mismatch("１００と１００", "100") == NumberMismatch((100, 100), (100,))


# =============================================================================
# C-4: which lines are checked
# =============================================================================

DOSE_JA = "ハイドロコーン１００ミリ"
DOSE_WRONG = "give 1000 mg"
DOSE_RIGHT = "give him 100 mil"


@pytest.mark.parametrize("status", ["proposed", "accepted"])
def test_a_proposed_or_accepted_line_is_checked_on_its_proposal(status: str) -> None:
    assert line_mismatch(_line(status, DOSE_JA, DOSE_WRONG)) == NumberMismatch((100,), (1000,))


@pytest.mark.parametrize("status", ["edited", "reverted"])
def test_an_edited_or_reverted_line_is_checked_on_its_committed_text(status: str) -> None:
    """AC-6 / PO-6: the shown text (`effective_text`), not the proposal."""
    flagged = _line(status, DOSE_JA, DOSE_RIGHT, final_en=DOSE_WRONG)
    fixed = _line(status, DOSE_JA, DOSE_WRONG, final_en=DOSE_RIGHT)

    assert line_mismatch(flagged) == NumberMismatch((100,), (1000,))
    assert line_mismatch(fixed) is None


@pytest.mark.parametrize("status", ["failed", "excluded"])
def test_a_failed_or_excluded_line_is_never_checked(status: str) -> None:
    excluded = "user" if status == "excluded" else None
    assert line_mismatch(_line(status, DOSE_JA, DOSE_WRONG, excluded=excluded)) is None


def test_a_line_with_no_english_yet_is_never_checked() -> None:
    """C-4: while a run is on, a proposed line has no proposal and no text."""
    assert line_mismatch(_line("proposed", "合計1433点", None)) is None


def test_a_committed_empty_line_is_checked_and_reads_no_english_numbers() -> None:
    """C-4: `final_en == ""` is a deleted line, checked against the Japanese."""
    deleted = _line("edited", "合計1433点", "Total 1433 points", final_en="")
    assert line_mismatch(deleted) == NumberMismatch((1433,), ())


# =============================================================================
# C-5: the sentence
# =============================================================================


@pytest.mark.parametrize(("pair", "sentence"), SENTENCE_TABLE, ids=lambda v: repr(v)[:30])
def test_mismatch_sentence_is_the_exact_c5_copy(
    pair: tuple[tuple[float, ...], tuple[float, ...]], sentence: str
) -> None:
    assert mismatch_sentence(NumberMismatch(*pair)) == sentence


def test_the_sentence_prints_whole_floats_without_a_point_and_others_by_repr() -> None:
    """C-5: `str(int(v))` when integral, else `repr(v)`; `inf` is `repr`'s."""
    mismatch = NumberMismatch((50000000000000.0,), (16.5, float("inf")))
    assert mismatch_sentence(mismatch) == (
        "Japanese 50000000000000; English 16.5, inf - numbers differ, check the page"
    )
