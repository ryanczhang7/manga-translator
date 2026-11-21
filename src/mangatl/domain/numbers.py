"""MT-156: say when the numbers in a line's English differ from its Japanese.

The check compares what OCR read against what the model (or the user) wrote.
It says the two differ; it never says which one is wrong. The reviewer is sent
back to the page.

**What a number is** (`numbers_in`, C-2). The text is NFKC-normalised and
lower-cased first, so full-width digits, commas and full stops read as their
ASCII twins. A digit number is a run of ASCII digits, optionally grouped by
commas in threes, with at most one decimal part. A digit number directly
followed by 千, 万, 億 or 兆 is multiplied by it, and such parts directly
following each other add, with one bare digit number after the last part
joining the sum. The English number words `zero` to `twenty` and the tens to
`ninety` are numbers too, and a tens word joined to `one` ... `nine` by one
hyphen or one space is one number.

**How the sides compare** (`number_mismatch`, C-3). Digits on either side
always count. An English number *word* only ever cancels a Japanese number
left unmatched by the English digits; a word that finds none is ignored.

**Known limits** (C-9). Each of these can flag a line that is translated well,
or miss one that is not:

- Kanji numerals are not numbers: `一人` against "one person" flags, with
  `none` on the Japanese side.
- Only 千, 万, 億 and 兆 multiply, and only directly after a digit number.
  `百` and `十` do not, and a multiplier after a multiplier is not read: `3千万`
  is 3000, and `2億5千万` is 200,005,000.
- `hundred`, `thousand`, `million`, `dozen`, `half`, `twice`, `first` and
  `a`/`an` are not number words, so "eight thousand" is the word 8.
- A wrong number written as a word, against Japanese with no number, is not
  seen, because a word only ever cancels.
- A number word in the Japanese text counts like any other Japanese number.
- Idiom (`7割` against "70%", `2倍` against "twice") flags.
- Units are not compared: 100 mg against 100 mL agrees.

Values are taken exactly (`Decimal`) and turned into `float` once, so `2.01千`
is 2010.0. A value too large for a float reads as `inf`; nothing here raises.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from mangatl.domain.line import Line, effective_text

__all__ = ["NumberMismatch", "line_mismatch", "mismatch_sentence", "number_mismatch", "numbers_in"]


@dataclass(frozen=True)
class NumberMismatch:
    """Every number read on each side of a line, ascending, duplicates kept."""

    japanese: tuple[float, ...]
    english: tuple[float, ...]


# C-2 rule 3: grouped first, else plain; then one optional decimal part.
_DIGIT_NUMBER = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+(?![0-9])|[0-9]+)(?:\.[0-9]+)?")

# C-2 rule 4. Written as escapes: U+5343 千, U+4E07 万, U+5104 億, U+5146 兆.
_MULTIPLIERS: dict[str, Decimal] = {
    "千": Decimal(1000),
    "万": Decimal(10_000),
    "億": Decimal(100_000_000),
    "兆": Decimal(1_000_000_000_000),
}

# C-2 rule 5: the 28 words.
_UNITS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_TEENS = (
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_WORD_VALUES: dict[str, int] = {
    "zero": 0,
    **{word: value for value, word in enumerate(_UNITS, start=1)},
    **{word: value for value, word in enumerate(_TEENS, start=10)},
    **{word: value for value, word in zip(range(20, 100, 10), _TENS, strict=True)},
}


def _alternation(words: Iterable[str]) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


# C-2 rules 5 and 6: no ASCII letter directly before or after; longer words
# win; a tens word, one hyphen or whitespace, then `one` ... `nine` is one number.
_NUMBER_WORD = re.compile(
    rf"(?<![a-z])(?:(?P<tens>{_alternation(_TENS)})[-\s](?P<unit>{_alternation(_UNITS)})"
    rf"|(?P<word>{_alternation(_WORD_VALUES)}))(?![a-z])"
)


def _digit_value(match: re.Match[str]) -> Decimal:
    return Decimal(match.group().replace(",", ""))


def _digit_numbers(text: str) -> list[float]:
    """C-2 rules 3 and 4 over normalised text: digit numbers, parts summed."""
    values: list[float] = []
    pos = 0
    while (match := _DIGIT_NUMBER.search(text, pos)) is not None:
        total = _digit_value(match)
        pos = match.end()
        multiplier = _MULTIPLIERS.get(text[pos : pos + 1])
        if multiplier is not None:
            total *= multiplier
            pos += 1
            # Parts directly after parts add; one bare digit number ends the sum.
            while (following := _DIGIT_NUMBER.match(text, pos)) is not None:
                pos = following.end()
                multiplier = _MULTIPLIERS.get(text[pos : pos + 1])
                if multiplier is None:
                    total += _digit_value(following)
                    break
                total += _digit_value(following) * multiplier
                pos += 1
        values.append(float(total))
    return values


def _word_numbers(text: str) -> list[float]:
    """C-2 rules 5 and 6 over normalised text."""
    values: list[float] = []
    for match in _NUMBER_WORD.finditer(text):
        if match.group("word") is not None:
            values.append(float(_WORD_VALUES[match.group("word")]))
        else:
            tens, unit = match.group("tens", "unit")
            values.append(float(_WORD_VALUES[tens] + _WORD_VALUES[unit]))
    return values


def _read(text: str) -> tuple[list[float], list[float]]:
    """The digit numbers and the word numbers of `text` (C-2, "Two kinds")."""
    normal = unicodedata.normalize("NFKC", text).lower()
    return _digit_numbers(normal), _word_numbers(normal)


def numbers_in(text: str) -> tuple[float, ...]:
    """Every number in `text`, of both kinds, as `float`, ascending (C-2)."""
    digits, words = _read(text)
    return tuple(sorted(digits + words))


def number_mismatch(source_ja: str, english: str) -> NumberMismatch | None:
    """`None` when the numbers that count on the two sides agree (C-3)."""
    japanese = numbers_in(source_ja)
    digits, words = _read(english)
    left = Counter(japanese) - Counter(digits)
    counted: list[float] = []
    for word in words:
        if left[word] > 0:
            left[word] -= 1
            counted.append(word)
    shown = tuple(sorted(digits + counted))
    if japanese == shown:
        return None
    return NumberMismatch(japanese=japanese, english=shown)


def line_mismatch(line: Line) -> NumberMismatch | None:
    """C-4: a failed, excluded or not-yet-translated line is never checked."""
    if line.status in ("failed", "excluded"):
        return None
    if line.proposed_en is None and line.final_en is None:
        return None
    return number_mismatch(line.source_ja, effective_text(line))


def _value_text(value: float) -> str:
    return str(int(value)) if value.is_integer() else repr(value)


def _side_text(values: tuple[float, ...]) -> str:
    return ", ".join(_value_text(value) for value in values) if values else "none"


def mismatch_sentence(mismatch: NumberMismatch) -> str:
    """The row's caption and the tail of its accessible name (C-5)."""
    return (
        f"Japanese {_side_text(mismatch.japanese)}; "
        f"English {_side_text(mismatch.english)} - numbers differ, check the page"
    )
