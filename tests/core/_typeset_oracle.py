"""An independent oracle for MT-020's typesetter tests.

Nothing here imports `mangatl`. The font is read with fontTools directly, from
the path the contract pins (`src/mangatl/typeset/fonts/`, MT-020 C-2/C-7), and
the line-breaking objective is re-implemented by brute force from the words of
MT-020 C-5. The point is independence: a test that asks the module under test
for its own advances, its own fitting area or its own break set passes against
any value of the thing it claims to pin (MT-020 `## Deferred verifications`,
conditions 2-4).

The pure half (`opportunities` .. `min_lines_allowing_wide_words`) takes an
`adv(start, end)` callable and imports nothing, so it can be - and in RED was -
exercised against synthetic advances in a plain interpreter before fontTools or
the font exist.
"""

from __future__ import annotations

import functools
import itertools
from collections.abc import Callable, Sequence
from pathlib import Path

#: Where C-2 puts the four faces and C-7 puts `OFL.txt`. Spelled out from the
#: repository root rather than read from `mangatl.typeset.font.FONT_DIR`, so a
#: test comparing the two is a comparison and not a tautology.
REPO_ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = REPO_ROOT / "src" / "mangatl" / "typeset" / "fonts"

#: C-2, verbatim (amended by PO-8, R-1): upstream 1.011's static faces are
#: CFF-outlined OTFs, vendored under their archive names, unrenamed. Nothing in
#: this oracle reads `glyf`: ink comes from `BoundsPen` over the glyph set and
#: advances from `hmtx`, both of which hold for CFF outlines.
FILENAMES: dict[str, str] = {
    "regular": "Shantell_Sans-Normal-Regular.otf",
    "italic": "Shantell_Sans-Normal-Regular_Italic.otf",
    "bold": "Shantell_Sans-Normal-Bold.otf",
    "bold_italic": "Shantell_Sans-Normal-Bold_Italic.otf",
}

#: The settled inset, written out here and NOT read from `fit.FIT_INSET_RATIO`
#: (C-9, AC-1): with the ratio mutated to 0.0 the module's own fitting area
#: grows, and only an area computed from this literal notices.
PINNED_INSET_RATIO = 0.12

Adv = Callable[[int, int], float]


# --- fontTools, read directly ---------------------------------------------------


@functools.cache
def font(key: str):
    from fontTools.ttLib import TTFont

    return TTFont(str(FONT_DIR / FILENAMES[key]))


@functools.cache
def cmap(key: str) -> dict[int, str]:
    return dict(font(key).getBestCmap())


def units_per_em(key: str = "regular") -> int:
    return int(font(key)["head"].unitsPerEm)


def hhea(key: str) -> tuple[int, int]:
    """(ascent, descent) in font units; descent is negative."""
    table = font(key)["hhea"]
    return int(table.ascent), int(table.descent)


def advance_units(text: str, key: str) -> int:
    hmtx = font(key)["hmtx"]
    names = cmap(key)
    return sum(int(hmtx[names[ord(c)]][0]) for c in text)


def advance_px(text: str, key: str, size_px: float) -> float:
    return advance_units(text, key) * size_px / units_per_em(key)


def styled_advance(chars: Sequence[tuple[str, str]], size_px: float) -> float:
    """Advance of a sequence of (char, face_key), each char at its own face."""
    return sum(advance_px(c, k, size_px) for c, k in chars)


def ink_px(text: str, key: str, size_px: float) -> tuple[float, float, float, float] | None:
    """C-4's ink box: pen at x=0, baseline at y=0, y growing downward."""
    from fontTools.pens.boundsPen import BoundsPen

    f = font(key)
    glyphs = f.getGlyphSet()
    hmtx = f["hmtx"]
    names = cmap(key)
    k = size_px / units_per_em(key)
    pen_x = 0
    box: list[float] | None = None
    for c in text:
        name = names[ord(c)]
        pen = BoundsPen(glyphs)
        glyphs[name].draw(pen)
        if pen.bounds is not None:
            x_min, y_min, x_max, y_max = pen.bounds
            g = [pen_x + x_min, y_min, pen_x + x_max, y_max]
            box = (
                g
                if box is None
                else [min(box[0], g[0]), min(box[1], g[1]), max(box[2], g[2]), max(box[3], g[3])]
            )
        pen_x += int(hmtx[name][0])
    if box is None:
        return None
    return (box[0] * k, -box[3] * k, box[2] * k, -box[1] * k)


# --- the C-5 objective, by brute force -----------------------------------------


def opportunities(text: str) -> list[tuple[int, int]]:
    """C-5's break opportunities in NORMALISED text, as (line_end, next_start).

    A U+0020 at `i` is consumed: the line ends at `i`, the next starts at
    `i + 1`. A U+002D at `i` with non-whitespace on both sides stays on the
    line: both are `i + 1`. Nothing else is an opportunity - no U+00A0, no
    dash, no point inside a word.
    """
    out: list[tuple[int, int]] = []
    for i, c in enumerate(text):
        if c == " ":
            out.append((i, i + 1))
        elif (
            c == "-"
            and 0 < i < len(text) - 1
            and not text[i - 1].isspace()
            and not text[i + 1].isspace()
        ):
            out.append((i + 1, i + 1))
    return out


def splits(text: str, n: int) -> list[tuple[tuple[int, ...], list[tuple[int, int]]]]:
    """Every split of `text` into exactly `n` non-empty lines.

    Each item is (break positions, [(start, end), ...]); a break's position is
    its `line_end` offset, which is what C-5's lexicographic tie-break orders.
    """
    out = []
    for chosen in itertools.combinations(opportunities(text), n - 1):
        segments: list[tuple[int, int]] = []
        start = 0
        for end, nxt in chosen:
            segments.append((start, end))
            start = nxt
        segments.append((start, len(text)))
        if all(e > s for s, e in segments):
            out.append((tuple(end for end, _ in chosen), segments))
    return out


def optimum(
    text: str, widths: Sequence[float], adv: Adv, *, last_line_counts: bool = True
) -> list[str] | None:
    """C-5's least-cost feasible split into exactly `len(widths)` lines.

    `last_line_counts=False` is the Knuth variant PO-1 rejected; it exists so a
    fixture can show that it chooses differently (condition 4).
    """
    best: tuple[float, tuple[int, ...], list[tuple[int, int]]] | None = None
    for positions, segments in splits(text, len(widths)):
        advances = [adv(s, e) for s, e in segments]
        if any(a > w for a, w in zip(advances, widths, strict=True)):
            continue
        slacks = [w - a for a, w in zip(advances, widths, strict=True)]
        if not last_line_counts:
            slacks = slacks[:-1]
        cost = sum(s * s for s in slacks)
        if best is None or (cost, positions) < (best[0], best[1]):
            best = (cost, positions, segments)
    if best is None:
        return None
    return [text[s:e] for s, e in best[2]]


def greedy(text: str, widths: Sequence[float], adv: Adv) -> list[str] | None:
    """First-fit: fill each line as full as it will go, the rest on the last.

    Not an implementation of C-5 (condition 2); a fixture that this agrees with
    does not distinguish the two.
    """
    ops = opportunities(text)
    start = 0
    lines: list[str] = []
    for w in widths[:-1]:
        fitting = [(e, nx) for e, nx in ops if e > start and adv(start, e) <= w]
        if not fitting:
            return None
        end, nxt = fitting[-1]
        lines.append(text[start:end])
        start = nxt
    if start >= len(text) or adv(start, len(text)) > widths[-1]:
        return None
    lines.append(text[start:])
    return lines


def min_lines_allowing_wide_words(text: str, width: float, adv: Adv) -> int:
    """The least line count at uniform `width` once a word wider than `width`
    may sit on a line of its own (C-6, the overflow layout). First-fit is
    optimal for the COUNT at a uniform width, which is all this answers."""
    ops = [*opportunities(text), (len(text), len(text))]
    start = 0
    count = 0
    while start < len(text):
        after = [(e, nx) for e, nx in ops if e > start]
        fitting = [(e, nx) for e, nx in after if adv(start, e) <= width]
        _, nxt = fitting[-1] if fitting else after[0]
        count += 1
        start = nxt if nxt > start else len(text)
    return count


def join_lines(lines: Sequence[str]) -> str:
    """C-6's join: `""` after a hyphen break, `" "` at a whitespace break.

    Fixtures that use this never contain `"- "`, so a line ending in `-` is
    always a hyphen break.
    """
    out = ""
    for i, line in enumerate(lines):
        if i:
            out += "" if lines[i - 1].endswith("-") else " "
        out += line
    return out
