"""MT-020 AC-5 (grammar half): `*italic*` and `**bold**` per C-3.

Every example C-3 rule 5 pins is asserted verbatim, plus the edges rules 1, 4
and 6 imply. The file-level half - which FONT FILE a run is drawn from - is in
`test_typeset_fit.py`.
"""

from __future__ import annotations

import pytest

from mangatl.typeset.markup import Run, parse_emphasis

R = (False, False)
I = (True, False)  # noqa: E741 - the style tags read as the grammar does
B = (False, True)


def _runs(*items: tuple[str, tuple[bool, bool]]) -> list[Run]:
    return [Run(text, italic, bold) for text, (italic, bold) in items]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # C-3 rule 5, verbatim.
        ("a *b* c", _runs(("a ", R), ("b", I), (" c", R))),
        ("a **b** c", _runs(("a ", R), ("b", B), (" c", R))),
        ("a *b c", _runs(("a *b c", R))),
        ("**a *b* c**", _runs(("**a ", R), ("b", I), (" c**", R))),
        ("***x***", _runs(("***x***", R))),
        ("\\*x\\*", _runs(("*x*", R))),
    ],
    ids=["italic", "bold", "unclosed", "nested", "triple", "escaped"],
)
def test_emphasis_grammar_examples_from_the_contract(text: str, expected: list[Run]) -> None:
    assert parse_emphasis(text) == expected


def test_an_unclosed_bold_marker_is_rendered_literally() -> None:
    assert parse_emphasis("a **b c") == _runs(("a **b c", R))


def test_a_delimiter_followed_by_one_of_a_different_length_is_literal() -> None:
    # "*", "**", "*": the first's next delimiter is "**" (rule 3 fails), the
    # "**"'s next is "*" (fails), the last has no next. All literal, one run.
    assert parse_emphasis("*a**b*") == _runs(("*a**b*", R))


def test_a_backslash_before_anything_but_a_star_is_a_literal_backslash() -> None:
    assert parse_emphasis("a\\b") == _runs(("a\\b", R))


def test_an_escaped_star_beside_a_delimiter_is_not_part_of_it() -> None:
    # "\**a*": the first star is escaped, so the delimiter is the single
    # unescaped star after it, which the final star closes.
    assert parse_emphasis("\\**a*") == _runs(("*", R), ("a", I))


def test_a_span_at_the_start_leaves_no_empty_leading_run() -> None:
    assert parse_emphasis("*a*") == _runs(("a", I))
    assert parse_emphasis("**a** b") == _runs(("a", B), (" b", R))


def test_two_spans_of_one_style_in_sequence_are_each_emphasised() -> None:
    assert parse_emphasis("*a* and *b*") == _runs(("a", I), (" and ", R), ("b", I))


def test_empty_text_parses_to_no_runs() -> None:
    assert parse_emphasis("") == []


def test_plain_text_is_one_regular_run() -> None:
    assert parse_emphasis("plain text") == _runs(("plain text", R))


@pytest.mark.parametrize(
    ("italic", "bold", "key"),
    [
        (False, False, "regular"),
        (True, False, "italic"),
        (False, True, "bold"),
        (True, True, "bold_italic"),
    ],
)
def test_a_run_names_the_face_its_style_is_drawn_from(italic: bool, bold: bool, key: str) -> None:
    assert Run("x", italic, bold).face_key == key
