"""MT-020 AC-4: where lines break, and which break set is chosen.

`break_lines` is called directly with widths built from advances this file reads
from the font with fontTools (`_typeset_oracle`), so every expected split
follows from an argument written beside it rather than from a guessed number.

**The size is the font's units-per-em**, so the scale `k` is exactly 1 and every
advance is an integer number of font units held in a float. Sums and squares of
those are exact, which is what makes a tie in C-5's cost a real tie (broken by
the lexicographic rule) rather than one decided by rounding.

Most fixtures repeat one word, `moon`. With every word of advance `A` and a
space of advance `S`, a line of `m` words measures `mA + (m-1)S`, and the
arguments below are about `u = A + S` alone, whatever the font's numbers are.

Three things each case is checked against, besides its literal expected lines:
the oracle's brute-force C-5 optimum (agreement), greedy first-fit
(disagreement: falsifiable condition 2), and - where named - the last-line-free
Knuth cost PO-1 rejected (disagreement: condition 4). The disagreements are
fixture self-checks: a case they do not hold for does not discriminate.
"""

from __future__ import annotations

import _typeset_oracle as oracle
import pytest

from mangatl.typeset.fit import break_lines
from mangatl.typeset.font import Faces, load_faces
from mangatl.typeset.markup import Run


@pytest.fixture(scope="module")
def faces() -> Faces:
    return load_faces()


@pytest.fixture(scope="module")
def size() -> float:
    return float(oracle.units_per_em("regular"))


def _adv(text: str, size: float) -> oracle.Adv:
    return lambda s, e: oracle.advance_px(text[s:e], "regular", size)


def _w(text: str, size: float) -> float:
    return oracle.advance_px(text, "regular", size)


def _break(text: str, widths: list[float], faces: Faces, size: float) -> list[str] | None:
    lines = break_lines([Run(text, False, False)], widths, faces, size)
    if lines is None:
        return None
    return ["".join(run.text for run in line) for line in lines]


# --- the objective: the optimum, where greedy and Knuth choose otherwise -------


def test_four_equal_words_in_two_lines_balance_two_and_two_not_three_and_one(
    faces: Faces, size: float
) -> None:
    # W = 3A + 2S, exactly three words. Splits (slack per line, cost):
    #   3|1: 0, 2u        -> 4u^2   (greedy: line 1 packed full)
    #   2|2: u, u         -> 2u^2   <- least
    #   1|3: 2u, 0        -> 4u^2
    # Knuth ignores the last line: 3|1 costs 0, so it picks 3|1. All-lines picks 2|2.
    text = "moon moon moon moon"
    width = _w("moon moon moon", size)
    widths = [width, width]
    expected = ["moon moon", "moon moon"]
    assert _break(text, widths, faces, size) == expected
    adv = _adv(text, size)
    assert oracle.optimum(text, widths, adv) == expected
    assert oracle.greedy(text, widths, adv) == ["moon moon moon", "moon"]
    assert oracle.optimum(text, widths, adv, last_line_counts=False) == ["moon moon moon", "moon"]


def test_a_sentence_set_on_two_lines_is_balanced_rather_than_leaving_a_lone_last_word(
    faces: Faces, size: float
) -> None:
    # W = the advance of everything but the last word. For ANY whitespace split
    # the two slacks sum to the same constant, 2W - (advance(text) - S) = W - t
    # (t = advance of "time?"). Greedy packs line 1 to exactly W and puts all of
    # that slack on line 2: cost (W - t)^2. Any split leaving slack on both lines
    # costs a^2 + b^2 < (a + b)^2, and "...the" / "whole time?" is such a split,
    # so the optimum is strictly better than greedy - whatever the advances are.
    # Knuth scores greedy's split 0, so it agrees with greedy and not with C-5.
    text = "Wait, you mean the cat was here the whole time?"
    width = _w("Wait, you mean the cat was here the whole", size)
    widths = [width, width]
    adv = _adv(text, size)
    got = _break(text, widths, faces, size)
    greedy = ["Wait, you mean the cat was here the whole", "time?"]
    assert oracle.greedy(text, widths, adv) == greedy
    assert oracle.optimum(text, widths, adv, last_line_counts=False) == greedy
    assert got == oracle.optimum(text, widths, adv)
    assert got != greedy


def test_per_line_widths_set_a_diamond_one_three_one(faces: Faces, size: float) -> None:
    # Widths [2A+S, 4A+3S, 2A+S] (capacity 2, 4, 2 words); five words leave a
    # total slack of 3u, and 1|3|1 puts exactly u on each line: cost 3u^2, the
    # unique least (every other feasible split concentrates slack: 2|2|1 and
    # 1|2|2 cost 4u^2 + ..., 2|3|0 has an empty line). Greedy takes 2 then 2,
    # leaving 1: 2|2|1. Using widths[0] for every line instead gives 1|2|2.
    text = "moon moon moon moon moon"
    narrow = _w("moon moon", size)
    wide = _w("moon moon moon moon", size)
    widths = [narrow, wide, narrow]
    expected = ["moon", "moon moon moon", "moon"]
    assert _break(text, widths, faces, size) == expected
    adv = _adv(text, size)
    assert oracle.optimum(text, widths, adv) == expected
    assert oracle.greedy(text, widths, adv) == ["moon moon", "moon moon", "moon"]
    assert oracle.optimum(text, [narrow] * 3, adv) != expected
    assert oracle.optimum(text, [wide] * 3, adv) != expected


def test_equal_cost_splits_break_at_the_earliest_position(faces: Faces, size: float) -> None:
    # Five words, W = 4A + 3S. 3|2 and 2|3 both cost u^2 + (2u)^2 = 5u^2, the
    # least. C-5's tie-break takes the lexicographically smallest break
    # positions: the break after word 2 comes first, so 2|3. Exact, because k = 1.
    text = "moon moon moon moon moon"
    width = _w("moon moon moon moon", size)
    widths = [width, width]
    expected = ["moon moon", "moon moon moon"]
    assert _break(text, widths, faces, size) == expected
    adv = _adv(text, size)
    assert oracle.optimum(text, widths, adv) == expected
    assert oracle.greedy(text, widths, adv) == ["moon moon moon moon", "moon"]


# --- feasibility --------------------------------------------------------------


def test_a_line_exactly_as_wide_as_its_width_fits(faces: Faces, size: float) -> None:
    assert _break("moon moon", [_w("moon moon", size)], faces, size) == ["moon moon"]


def test_a_line_one_unit_wider_than_its_width_does_not_fit(faces: Faces, size: float) -> None:
    assert _break("moon moon", [_w("moon moon", size) - 1.0], faces, size) is None


def test_the_split_has_exactly_as_many_lines_as_widths(faces: Faces, size: float) -> None:
    big = _w("moon moon moon", size)
    assert _break("moon moon", [big, big, big], faces, size) is None
    assert _break("moon moon", [big, big], faces, size) == ["moon", "moon"]


# --- break opportunities: whitespace and existing hyphens, nothing else -------


def test_a_hyphenated_word_breaks_after_its_hyphen_which_stays_on_the_line(
    faces: Faces, size: float
) -> None:
    width = max(_w("self-", size), _w("aware", size))
    assert _break("self-aware", [width, width], faces, size) == ["self-", "aware"]


def test_a_word_is_never_broken_and_no_hyphen_is_inserted(faces: Faces, size: float) -> None:
    # Any internal split of "moonlight" into two lines would fit these widths;
    # no break opportunity exists, so there is no split at all.
    width = _w("moonlight", size) - 1.0
    assert _break("moonlight", [width, width], faces, size) is None


def test_a_hyphen_after_a_space_is_not_a_break_opportunity(faces: Faces, size: float) -> None:
    # Only "wait -" / "no" would fit these widths, and that break is after a
    # hyphen with whitespace before it. The legal break (at the space) puts
    # "-no" on line 2, which is too wide.
    widths = [_w("wait -", size), _w("no", size)]
    assert _break("wait -no", widths, faces, size) is None


@pytest.mark.parametrize(
    "joiner", ["\u00a0", "\u2013", "\u2014"], ids=["no-break-space", "en-dash", "em-dash"]
)
def test_no_break_space_and_dashes_are_not_break_opportunities(
    faces: Faces, size: float, joiner: str
) -> None:
    text = f"wait{joiner}no"
    width = max(_w(f"wait{joiner}", size), _w("wait", size), _w(f"{joiner}no", size))
    assert width < _w(text, size)
    assert _break(text, [width, width], faces, size) is None
    assert _break(text, [_w(text, size)], faces, size) == [text]


# --- runs keep their style and are measured at their own face -----------------


def test_a_break_keeps_each_characters_style(faces: Faces, size: float) -> None:
    runs = [Run("moon ", False, False), Run("moon", True, False)]
    width = max(_w("moon", size), oracle.advance_px("moon", "italic", size))
    lines = break_lines(runs, [width, width], faces, size)
    assert lines is not None
    styled = [[(c, r.italic, r.bold) for r in line for c in r.text] for line in lines]
    assert styled == [
        [(c, False, False) for c in "moon"],
        [(c, True, False) for c in "moon"],
    ]


def test_an_italic_run_is_measured_with_the_italic_face(faces: Faces, size: float) -> None:
    # A word whose italic advance differs from its regular one, so measuring the
    # italic run with the regular face moves the line across one of the two
    # boundaries below (exact fit / one unit short).
    word = next(
        w
        for w in ("moon", "wave", "jolly", "fish", "quick", "mamma", "WWW")
        if oracle.advance_units(w, "italic") != oracle.advance_units(w, "regular")
    )
    runs = [Run(f"{word} ", False, False), Run(word, True, False)]
    exact = _w(f"{word} ", size) + oracle.advance_px(word, "italic", size)
    assert break_lines(runs, [exact], faces, size) is not None
    assert break_lines(runs, [exact - 1.0], faces, size) is None
