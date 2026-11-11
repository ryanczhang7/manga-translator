"""`mangatl.domain.echo`: does each answer entry repeat its own region's Japanese?

MT-149. Every answer entry is `{"ja": <the region's Japanese, repeated>, "en":
<English>}`, and an entry whose `ja` is not close to the OCR text listed under
its key is **misaligned**: its English is dropped and the region recorded as
untranslated (C-1a). This file covers the pure half - **AC-2** (`echo_matches`),
**AC-3** (p017's slip rebuilt as a fixture) and **AC-4** (a repeated line is not
a slip) - plus `checked_lines`' bookkeeping and the band C-3 puts
`ECHO_MAX_EDIT_RATIO` in. The adapters' half (AC-6) is in
`test_translate_client.py`, `test_translate_gemini.py` and
`test_gemini_batch.py`; the store's and the stage's (AC-5) in
`test_proposed_store.py`, `test_review_lines_store.py`,
`test_translate_stage.py`, `test_translate_stage_excluded.py` and
`test_batch_collect.py`.

**Oracle partition (C-4).** AC-2 to AC-4 are oracle-free: no document says how
close an echo must be. C-3 therefore sets the constant from controls written
first, and this file pins the controls rather than the number:

* one substitution in ten characters (ratio 0.1) must pass;
* one changed character in four (ratio 0.25) must pass - the short-text case;
* AC-3's shifted echoes that are not their region's own text must fail; the
  nearest of them is entry 7's `いてーよー！！` against `急ぐぞ！！こっから先は戦場だ！！`,
  **0.875** (measured in RED, see below - not the 1.0 C-3 estimated).

So `0.25 <= ECHO_MAX_EDIT_RATIO < 0.875`, asserted as a band, because in RED the
module does not exist and a literal would be a guess pinned as fact. The value
recommended in the story's `## Handoff` is 0.4.

**Measured in RED, outside pytest** (2026-11-11, a candidate of C-1a's
algorithm - NFKC, every `str.isspace()` character removed, Levenshtein over the
longer length - run with the project's interpreter; the module under test did
not exist, so no assertion here has run against it):

    one substitution in ten          0.1
    one changed character in four    0.25
    whitespace-only difference       0.0
    full-width vs half-width (NFKC)  0.0
    AC-3 entry 4  っ          <- あああ…                 1.0
    AC-3 entry 5  いてーよー！！ <- っ                    1.0
    AC-3 entry 6  いてーよー！！ <- いてーよー！！         0.0   (identical text)
    AC-3 entry 7  急ぐぞ！！…   <- いてーよー！！         0.875

**Entry 6 is the case AC-4 describes**: regions 5 and 6 carry the same
Japanese, so the slipped entry 6 echoes its own listing exactly and keeps its
English - which is "It hurts!!", correct for region 6. AC-3 as first written
said regions 4-7 all lose their proposal; with p017's Japanese no echo check
can drop region 6 without also breaking AC-4. Amendment A-1 settled it: AC-3
now says regions 4, 5 and 7 have no proposal and region 6 keeps the English it
carries. The AC-3 tests below assert exactly that, region 6 included.

**The module is read lazily** (`_LazyModule`, the `test_gemini_batch.py`
pattern): a top-level import of a module that does not exist is a collection
error that interrupts the whole `tests/core tests/ui` session. Read inside each
test, a missing module or name is a FAILED test naming it.

**Timing.** No `pytest-timeout` in this project; nothing here is slower than a
Levenshtein over a few hundred characters.
"""

# ruff: noqa: RUF001, RUF002, RUF003
#
# RUF001/2/3 warn that a full-width character "looks like" its ASCII twin and may
# have been typed by accident. Here that is exactly inverted: p017's Japanese
# carries full-width `！`, and AC-2's NFKC case IS the difference between `！`
# and `!`. Every U+FF01 below is deliberate. Scoped to this file and these rules.

from __future__ import annotations

import dataclasses
import importlib
import math
from typing import Any

import pytest

# -- the module under test -----------------------------------------------------


class _LazyModule:
    """`mangatl.domain.echo`, imported on the first attribute read."""

    def __getattr__(self, name: str) -> Any:
        module = importlib.import_module("mangatl.domain.echo")
        return getattr(module, name)


@pytest.fixture
def echo() -> Any:
    return _LazyModule()


# -- the controls C-3 names (expected values: see the module docstring) ---------

#: C-3's first control: ten characters, one substituted. Ratio 0.1.
_TEN = "あいうえおかきくけこ"
_TEN_ONE_SUBSTITUTED = "あいうえおかきくけさ"

#: C-3's third control: four characters, one changed. Ratio 0.25 - one
#: character is a quarter of a short line, and this must still pass.
_FOUR = "行くぞ！"
_FOUR_ONE_CHANGED = "行くよ！"

#: The band's bounds, from the controls: the lower is the short-text control,
#: the upper is AC-3's nearest shifted pair that is not its region's own text.
_BAND_LOW = 0.25
_BAND_HIGH = 0.875

# -- AC-3's fixture: p017 copy A, rebuilt ----------------------------------------

#: Nine regions in reading order. 4-7 are p017's (the story's `## Context`); 2
#: and 3 are its siren regions' hallucinated OCR; 0, 1 and 8 are invented,
#: plausible and distinct.
_P017: tuple[str, ...] = (
    "おい、待てよ！",
    "ここはどこだ……",
    "んーーー…",
    "あああ…",
    "っ",
    "いてーよー！！",
    "いてーよー！！",
    "急ぐぞ！！こっから先は戦場だ！！",
    "早く乗れ！",
)

#: The English a correctly keyed answer would carry, region by region.
_P017_EN: tuple[str, ...] = (
    "Hey, wait up!",
    "Where are we...",
    "WEE-WOO...",
    "WEE-WOO...",
    "Ngh",
    "It hurts!!",
    "It hurts!!",
    "Hurry!! It's a battlefield from here on!!",
    "Get in, quick!",
)


def _slipped_p017(echo: Any) -> dict[int, Any]:
    """AC-3's answer: entries 0-3 and 8 echo their own region; entries 4-7
    carry the `ja` of regions 3-6, with the English shifted to match."""
    entries = {k: echo.AnswerEntry(_P017[k], _P017_EN[k]) for k in (0, 1, 2, 3, 8)}
    for k in (4, 5, 6, 7):
        entries[k] = echo.AnswerEntry(_P017[k - 1], _P017_EN[k - 1])
    return entries


# -- the module's surface --------------------------------------------------------


def test_the_module_exports_exactly_the_contracts_names(echo: Any) -> None:
    """C-1: five names, sorted (RUF022)."""
    assert echo.__all__ == [
        "ECHO_MAX_EDIT_RATIO",
        "AnswerEntry",
        "CheckedLines",
        "checked_lines",
        "echo_matches",
    ]


def test_an_answer_entry_is_a_frozen_value_of_ja_then_en(echo: Any) -> None:
    entry = echo.AnswerEntry("行くぞ", "Let's go.")

    assert [f.name for f in dataclasses.fields(echo.AnswerEntry)] == ["ja", "en"]
    assert (entry.ja, entry.en) == ("行くぞ", "Let's go.")
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.en = "changed"


def test_checked_lines_is_a_frozen_value_of_lines_then_misaligned(echo: Any) -> None:
    checked = echo.CheckedLines(lines={0: "a"}, misaligned=frozenset({1}))

    assert [f.name for f in dataclasses.fields(echo.CheckedLines)] == ["lines", "misaligned"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        checked.lines = {}


def test_the_module_imports_nothing_but_the_standard_library(echo: Any) -> None:
    """C-1: "pure; stdlib only" - `domain` is independent (architecture.md §3)."""
    import ast
    import sys
    from pathlib import Path

    source = Path(importlib.import_module("mangatl.domain.echo").__file__ or "").read_text(
        encoding="utf-8"
    )
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])

    assert roots <= set(sys.stdlib_module_names) | {"__future__"}, sorted(roots)


# -- ECHO_MAX_EDIT_RATIO: the band C-3's controls leave ----------------------------


def test_the_constant_lies_in_the_gap_between_the_controls(echo: Any) -> None:
    """C-3: at least 0.25 (one changed character in four must pass) and below
    0.875 (AC-3's nearest shifted echo that is not its own text must fail). A
    value outside the band fails one of the controls below anyway; this test
    says which way it went."""
    ratio = echo.ECHO_MAX_EDIT_RATIO

    assert isinstance(ratio, float)
    assert _BAND_LOW <= ratio < _BAND_HIGH, (
        f"ECHO_MAX_EDIT_RATIO = {ratio}, outside [{_BAND_LOW}, {_BAND_HIGH})"
    )


def _distinct(count: int, start: int) -> str:
    """`count` distinct CJK ideographs from U+4E00 + `start`: NFKC-stable, no
    whitespace, and no two equal, so `k` substitutions or insertions are an
    edit distance of exactly `k`."""
    return "".join(chr(0x4E00 + start + i) for i in range(count))


def test_the_threshold_is_the_constant_compared_over_the_longer_string(echo: Any) -> None:
    """AC-2's "`ECHO_MAX_EDIT_RATIO` or less of the longer string's characters",
    measured against whatever value the constant has. A 100-character listing,
    echoed with `d` characters appended: the edit distance is `d`, the longer
    length `100 + d`. With `d` the largest count for which `d / (100 + d) <= R`,
    the echo passes; one more character fails it. And at that `d`, `d / 100`
    exceeds `R`, so an implementation dividing by the listing's length (or the
    shorter one) rejects the first echo and fails here."""
    ratio = echo.ECHO_MAX_EDIT_RATIO
    listed = _distinct(100, 0)
    d = math.floor(100 * ratio / (1 - ratio))
    while d / (100 + d) > ratio:  # guard floating rounding at the boundary
        d -= 1
    assert d / 100 > ratio, f"precondition: d = {d} does not separate the denominators"

    within = listed + _distinct(d, 1000)
    beyond = listed + _distinct(d + 1, 1000)

    assert echo.echo_matches(listed, within), f"{d} insertions over {100 + d} rejected"
    assert not echo.echo_matches(listed, beyond), f"{d + 1} insertions over {101 + d} accepted"


# -- AC-2: what passes -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["行くぞ", _P017[7], "っ", "……なるほど"],
    ids=["short", "long", "one-character", "punctuation-led"],
)
def test_an_exact_copy_matches(echo: Any, text: str) -> None:
    assert echo.echo_matches(text, text) is True


@pytest.mark.parametrize(
    ("listed", "echoed"),
    [
        ("どうして 君が ここに", "どうして君がここに"),
        ("どうして君がここに", "どうして\n君が\tここに"),
        ("どうして　君がここに", "どうして君がここに"),
        (" 行くぞ ", "行くぞ"),
    ],
    ids=["spaces-in-listing", "newline-and-tab-in-echo", "ideographic-space", "edges"],
)
def test_a_copy_differing_only_by_whitespace_matches(echo: Any, listed: str, echoed: str) -> None:
    """AC-2: every `str.isspace()` character is removed from both sides - a
    vertical bubble's OCR line breaks are not a slip."""
    assert echo.echo_matches(listed, echoed) is True


@pytest.mark.parametrize(
    ("listed", "echoed"),
    [
        ("待て！！", "待て!!"),
        ("ＯＫだ", "OKだ"),
        ("ｲﾃｰﾖ", "イテーヨ"),
        ("１２３", "123"),
    ],
    ids=["full-width-bang", "full-width-latin", "half-width-katakana", "full-width-digits"],
)
def test_a_copy_differing_only_by_full_width_against_half_width_forms_matches(
    echo: Any, listed: str, echoed: str
) -> None:
    """AC-2: NFKC on both sides. Each pair is several characters apart before
    normalisation - `ｲﾃｰﾖ` against `イテーヨ` is four of four - so a
    comparison without NFKC rejects it whatever the threshold."""
    assert echo.echo_matches(listed, echoed) is True
    assert echo.echo_matches(echoed, listed) is True


def test_one_substitution_in_ten_characters_matches(echo: Any) -> None:
    """C-3's first control: OCR noise the model corrected. Ratio 0.1."""
    assert echo.echo_matches(_TEN, _TEN_ONE_SUBSTITUTED) is True


def test_one_changed_character_in_four_matches(echo: Any) -> None:
    """C-3's third control, the short-text one: ratio 0.25, which is why the
    constant is at least 0.25."""
    assert echo.echo_matches(_FOUR, _FOUR_ONE_CHANGED) is True


@pytest.mark.parametrize(
    "echoed",
    ["", "っ", "あの泡の中に何か書いてある", "WEE-WOO"],
    ids=["empty-echo", "short", "long", "latin"],
)
def test_an_empty_listing_matches_any_echo(echo: Any, echoed: str) -> None:
    """AC-2: an `ocr_empty` region is listed with empty text and the model
    reads the bubble itself (PO-1), so whatever it echoes is its reading."""
    assert echo.echo_matches("", echoed) is True


def test_whitespace_is_removed_rather_than_counted_however_much_of_it_there_is(
    echo: Any,
) -> None:
    """The cases above differ by a few characters of whitespace, which a
    comparison that *counted* whitespace as edits could absorb under a loose
    threshold. Here it is 24 of 27 characters (ratio 0.889 if counted, above
    the band's top), so only removing it lets the copy match."""
    spread = "行" + " " * 12 + "く" + "\n" * 12 + "ぞ"

    assert echo.echo_matches(spread, "行くぞ") is True
    assert echo.echo_matches("行くぞ", spread) is True


def test_a_listing_of_only_whitespace_counts_as_empty(echo: Any) -> None:
    """C-1a: `listed == ""` is decided *after* whitespace is removed."""
    assert echo.echo_matches(" 　\n", "なんだ") is True


# -- AC-2: what does not (the negative controls) -----------------------------------


def test_a_non_empty_listing_echoed_as_nothing_does_not_match(echo: Any) -> None:
    """The control for the empty-listing rule: emptiness exempts the listing,
    not the echo. Ratio 1.0."""
    assert echo.echo_matches("行くぞ", "") is False


def test_another_regions_japanese_does_not_match(echo: Any) -> None:
    """A wholly different line: ratio 1.0."""
    assert echo.echo_matches("どうして君がここに", "醜鬼が人間の言う通りに動いたりね") is False


@pytest.mark.parametrize(
    ("listed", "echoed"),
    [(_P017[4], _P017[3]), (_P017[5], _P017[4]), (_P017[7], _P017[6])],
    ids=["entry-4", "entry-5", "entry-7"],
)
def test_each_shifted_p017_echo_that_is_not_its_own_text_does_not_match(
    echo: Any, listed: str, echoed: str
) -> None:
    """C-3's second control, pair by pair: 1.0, 1.0 and 0.875 (the nearest)."""
    assert echo.echo_matches(listed, echoed) is False


def test_the_comparison_is_symmetric_in_its_ratio(echo: Any) -> None:
    """Over the longer length, swapping the arguments changes nothing for a
    non-empty pair - entry 7's pair both ways."""
    assert echo.echo_matches(_P017[7], _P017[6]) is False
    assert echo.echo_matches(_P017[6], _P017[7]) is False


# -- checked_lines -----------------------------------------------------------------


def test_matching_entries_are_kept_and_nothing_is_misaligned(echo: Any) -> None:
    entries = {0: echo.AnswerEntry("行くぞ", "Let's go."), 1: echo.AnswerEntry("待て", "Wait.")}

    checked = echo.checked_lines(entries, ["行くぞ", "待て"])

    assert checked == echo.CheckedLines(lines={0: "Let's go.", 1: "Wait."}, misaligned=frozenset())


def test_a_mismatched_entry_is_misaligned_and_its_english_is_dropped(echo: Any) -> None:
    """C-1a: misaligned, and NOT in `lines` - its English never reaches the store."""
    entries = {0: echo.AnswerEntry("行くぞ", "Let's go."), 1: echo.AnswerEntry("行くぞ", "Wait.")}

    checked = echo.checked_lines(entries, ["行くぞ", "待て"])

    assert checked.lines == {0: "Let's go."}
    assert checked.misaligned == frozenset({1})
    assert type(checked.misaligned) is frozenset
    assert type(checked.lines) is dict


def test_a_key_the_answer_omitted_is_in_neither(echo: Any) -> None:
    """C-1a: an omitted region stays "no translation was returned" - it is not
    misaligned, because nothing was answered for it."""
    checked = echo.checked_lines({0: echo.AnswerEntry("行くぞ", "Let's go.")}, ["行くぞ", "待て"])

    assert checked.lines == {0: "Let's go."}
    assert 1 not in checked.misaligned


def test_a_malformed_entry_is_misaligned_and_has_no_english(echo: Any) -> None:
    """R-2a (PO-4): the parser maps a malformed entry to `None`, and
    `checked_lines` files its key as misaligned - it is answered, so not
    "omitted", and it carries nothing that could be accepted. Its neighbour
    is checked as usual."""
    entries = {0: echo.AnswerEntry("行くぞ", "Let's go."), 1: None}

    checked = echo.checked_lines(entries, ["行くぞ", "待て"])

    assert checked == echo.CheckedLines(lines={0: "Let's go."}, misaligned=frozenset({1}))


def test_a_malformed_entry_is_misaligned_even_where_the_listing_is_empty(echo: Any) -> None:
    """R-2a: no listing match is consulted for a `None` entry. An empty
    listing matches *any* echo (AC-2), so an implementation that ran the echo
    check first, or read an empty string for a missing `ja`, would accept
    nothing as English here; the key must still read misaligned."""
    checked = echo.checked_lines({1: None}, ["行くぞ", ""])

    assert checked == echo.CheckedLines(lines={}, misaligned=frozenset({1}))


def test_no_entries_check_to_nothing(echo: Any) -> None:
    """The zero: a page of wordless art, or a model that answered nothing."""
    checked = echo.checked_lines({}, ["行くぞ"])

    assert checked == echo.CheckedLines(lines={}, misaligned=frozenset())


def test_an_entry_for_an_empty_listing_keeps_its_english(echo: Any) -> None:
    """AC-2's empty-listing rule through `checked_lines`: an `ocr_empty` region
    the model read for itself is translated, not dropped."""
    checked = echo.checked_lines({1: echo.AnswerEntry("なんだと", "What?!")}, ["行くぞ", ""])

    assert checked.lines == {1: "What?!"}
    assert checked.misaligned == frozenset()


def test_the_english_kept_is_the_entrys_own_and_not_its_neighbours(echo: Any) -> None:
    """Each kept line is the `en` of the entry under that key, never another's:
    three regions, each with distinct English."""
    entries = {k: echo.AnswerEntry(ja, f"line {k}") for k, ja in enumerate(["一", "二", "三"])}

    assert echo.checked_lines(entries, ["一", "二", "三"]).lines == {
        0: "line 0",
        1: "line 1",
        2: "line 2",
    }


# -- AC-3: p017's slip -------------------------------------------------------------


def test_the_p017_fixture_is_nine_regions_with_the_storys_japanese_at_4_to_7() -> None:
    """The fixture's own precondition, against the story's `## Context`."""
    assert len(_P017) == 9
    assert _P017[4:8] == (
        "っ",
        "いてーよー！！",
        "いてーよー！！",
        "急ぐぞ！！こっから先は戦場だ！！",
    )
    assert len(set(_P017[:4] + _P017[8:])) == 5, "regions 0-3 and 8 must be distinct"


def test_regions_0_to_3_and_8_whose_echoes_match_keep_their_english(echo: Any) -> None:
    """AC-3: the regions the slip did not touch are translated as answered."""
    checked = echo.checked_lines(_slipped_p017(echo), list(_P017))

    assert {k: checked.lines.get(k) for k in (0, 1, 2, 3, 8)} == {
        k: _P017_EN[k] for k in (0, 1, 2, 3, 8)
    }


def test_the_shifted_entries_4_5_and_7_have_no_proposal_and_are_misaligned(echo: Any) -> None:
    """AC-3 (as amended, A-1): the three shifted entries whose echo is another
    region's text lose their English and are reported misaligned. Region 6 is
    pinned separately, by the test that follows."""
    checked = echo.checked_lines(_slipped_p017(echo), list(_P017))

    assert not {4, 5, 7} & set(checked.lines), f"kept: {sorted(checked.lines)}"
    assert {4, 5, 7} <= checked.misaligned, f"misaligned: {sorted(checked.misaligned)}"
    assert not {0, 1, 2, 3, 8} & checked.misaligned


def test_the_slipped_region_6_keeps_the_english_its_entry_carries_and_is_not_misaligned(
    echo: Any,
) -> None:
    """AC-3 (as amended, A-1): entry 6 carries region 5's `ja` and English, and
    that `ja` is region 6's own listing, so region 6 keeps exactly "It hurts!!"
    - region 5's English, correct for it - and is not reported misaligned."""
    checked = echo.checked_lines(_slipped_p017(echo), list(_P017))

    assert checked.lines.get(6) == _P017_EN[5] == "It hurts!!", (
        f"region 6 got {checked.lines.get(6)!r}"
    )
    assert 6 not in checked.misaligned, f"misaligned: {sorted(checked.misaligned)}"


def test_in_the_fixture_the_slipped_entry_6_echoes_its_own_regions_text() -> None:
    """The fact behind amendment A-1, asserted on the fixture alone: entry 6
    carries region 5's `ja`, which is region 6's listing character for
    character, so no comparison of `ja` with the listing can see the slip
    there - and the English it carries is the right English for region 6."""
    assert _P017[5] == _P017[6]
    assert _P017_EN[5] == _P017_EN[6]


# -- AC-4: a repeated line is not a slip -------------------------------------------


def test_two_identical_lines_whose_entries_swap_both_keep_their_english(echo: Any) -> None:
    """AC-4: regions 1 and 2 are both `いてーよー！！`; the answer swaps their
    English. Both echoes match, both are kept - the echo cannot tell them
    apart and need not, since either English fits either bubble."""
    entries = {
        0: echo.AnswerEntry("っ", "Ngh"),
        1: echo.AnswerEntry("いてーよー！！", "It hurts!! (2)"),
        2: echo.AnswerEntry("いてーよー！！", "It hurts!! (1)"),
    }

    checked = echo.checked_lines(entries, ["っ", "いてーよー！！", "いてーよー！！"])

    assert checked.lines == {0: "Ngh", 1: "It hurts!! (2)", 2: "It hurts!! (1)"}
    assert checked.misaligned == frozenset()
