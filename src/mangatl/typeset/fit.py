"""Fit English into a bubble polygon: the fitting area, line breaks and layout.

MT-020 C-5 and C-6. Every number is a design token (PO-3); `tests/core/
test_typeset_fit.py` pins each against `mangatl.ui.tokens_gen.TOKENS`, which
this package may not import.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import shapely
from shapely.geometry import LineString, MultiPolygon
from shapely.geometry import Polygon as ShapelyPolygon

from mangatl.typeset.font import Faces
from mangatl.typeset.markup import Run, parse_emphasis
from mangatl.typeset.measure import measure_run

MIN_SIZE_PX: float = 14.0  # == TOKENS["typeset.size-min"]
MAX_SIZE_PX: float = 42.0  # == TOKENS["typeset.size-max"]
SIZE_STEP_PX: float = 1.0  # == TOKENS["typeset.size-step"]
LINE_HEIGHT_RATIO: float = 1.08  # == TOKENS["typeset.line-height"]
FIT_INSET_RATIO: float = 0.12  # == TOKENS["typeset.padding-ratio"]

#: `line_widths` bisects the half-width `h` until the bracket is this narrow and
#: keeps the low end, so a width is never generous and is at most 0.01 px short
#: (C-5 requires <= 0.01 px).
HALF_WIDTH_TOLERANCE_PX: float = 0.005

Polygon = Sequence[tuple[float, float]]
Style = tuple[bool, bool]  # (italic, bold)
NO_BREAK_SPACE = chr(0x00A0)  # kept, placed, and never a break (C-5)


@dataclass(frozen=True)
class PlacedGlyph:
    char: str
    font_path: Path
    size_px: float
    x: float
    baseline_y: float
    advance: float
    ink: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class Line:
    glyphs: tuple[PlacedGlyph, ...]
    advance: float
    left: float
    top: float
    height: float


@dataclass(frozen=True)
class TypesetBlock:
    lines: tuple[Line, ...]
    size_px: float
    overflowed: bool
    text: str


# --- geometry ----------------------------------------------------------------------


def fitting_area(polygon: Polygon) -> ShapelyPolygon:
    """The polygon buffered inward by 0.12 x its bbox's short side; may be empty."""
    shape = ShapelyPolygon(polygon)
    x0, y0, x1, y1 = shape.bounds
    inner = shape.buffer(-FIT_INSET_RATIO * min(x1 - x0, y1 - y0))
    if isinstance(inner, MultiPolygon):
        inner = max(inner.geoms, key=lambda g: g.area)
    shapely.prepare(inner)
    return inner


def _centre(bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = bounds
    return (x0 + x1) / 2, (y0 + y1) / 2


def _top(cy: float, size_px: float, n: int) -> float:
    return cy - n * size_px * LINE_HEIGHT_RATIO / 2


def line_widths(area: ShapelyPolygon, size_px: float, n: int) -> list[float]:
    """Per line box, the widest rectangle centred on cx that the area covers."""
    cx, cy = _centre(area.bounds)
    a = size_px * LINE_HEIGHT_RATIO
    top = _top(cy, size_px, n)
    reach = max(cx - area.bounds[0], area.bounds[2] - cx)
    widths: list[float] = []
    for i in range(n):
        y0, y1 = top + i * a, top + (i + 1) * a
        if not area.covers(LineString([(cx, y0), (cx, y1)])):
            widths.append(0.0)
            continue
        lo, hi = 0.0, reach
        while hi - lo > HALF_WIDTH_TOLERANCE_PX:
            mid = (lo + hi) / 2
            if area.covers(shapely.box(cx - mid, y0, cx + mid, y1)):
                lo = mid
            else:
                hi = mid
        widths.append(2 * lo)
    return widths


# --- text -----------------------------------------------------------------------------


def _is_break_space(c: str) -> bool:
    return c.isspace() and c != NO_BREAK_SPACE


def _normalise(runs: Sequence[Run]) -> list[tuple[str, Style]]:
    """Whitespace runs (not U+00A0) collapsed to one U+0020 and trimmed (C-5)."""
    out: list[tuple[str, Style]] = []
    for run in runs:
        for c in run.text:
            if not _is_break_space(c):
                out.append((c, (run.italic, run.bold)))
            elif out and out[-1][0] != " ":
                out.append((" ", (run.italic, run.bold)))
    if out and out[-1][0] == " ":
        out.pop()
    return out


def _opportunities(text: str) -> list[tuple[int, int]]:
    """(line end, next line start) for each break opportunity in normalised text."""
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


def _to_runs(chars: Sequence[tuple[str, Style]]) -> list[Run]:
    runs: list[Run] = []
    for c, (italic, bold) in chars:
        if runs and (runs[-1].italic, runs[-1].bold) == (italic, bold):
            runs[-1] = Run(runs[-1].text + c, italic, bold)
        else:
            runs.append(Run(c, italic, bold))
    return runs


@dataclass(frozen=True)
class _Split:
    cost: float
    segments: tuple[tuple[int, int], ...]  # (start, end) per line


def _best_split(
    chars: Sequence[tuple[str, Style]],
    advances: Sequence[float],
    widths: Sequence[float],
    *,
    allow_wide_words: bool = False,
) -> _Split | None:
    """C-5's least-cost feasible split into exactly ``len(widths)`` lines.

    Breakpoints are indexed 0 (text start), 1..B (the opportunities) and B+1
    (text end). Ties go to the lexicographically smallest break positions,
    which a prefix DP preserves: two prefixes ending at the same breakpoint
    share every possible suffix. ``allow_wide_words`` admits a line holding a
    single unbreakable piece whatever its advance (C-6, the overflow layout).
    """
    text = "".join(c for c, _ in chars)
    ops = _opportunities(text)
    starts = [0, *(nxt for _, nxt in ops)]
    ends = [0, *(end for end, _ in ops), len(text)]
    last = len(ops) + 1
    # cum[j][m] = advance of the m characters from starts[j], summed left to right.
    cum: list[list[float]] = []
    for s in starts:
        acc = [0.0]
        for a in advances[s:]:
            acc.append(acc[-1] + a)
        cum.append(acc)

    best: dict[int, tuple[float, tuple[int, ...], tuple[tuple[int, int], ...]]] = {0: (0.0, (), ())}
    for line, width in enumerate(widths):
        final = line == len(widths) - 1
        targets = [last] if final else range(1, last)
        nxt: dict[int, tuple[float, tuple[int, ...], tuple[tuple[int, int], ...]]] = {}
        for k in targets:
            for j, (cost, positions, segments) in best.items():
                if j >= k:
                    continue
                start, end = starts[j], ends[k]
                advance = cum[j][end - start]
                # end == start only for empty text, which has no split: a line is
                # never empty (C-5, amended in RED).
                if end <= start or (advance > width and not (allow_wide_words and k == j + 1)):
                    continue
                candidate = (
                    cost + (width - advance) ** 2,
                    positions if final else (*positions, end),
                    (*segments, (start, end)),
                )
                if k not in nxt or candidate[:2] < nxt[k][:2]:
                    nxt[k] = candidate
        best = nxt
    if last not in best:
        return None
    cost, _, segments = best[last]
    return _Split(cost, segments)


def _advances(chars: Sequence[tuple[str, Style]], faces: Faces, size_px: float) -> list[float]:
    return [measure_run(c, faces[Run(c, *style).face_key], size_px).advance for c, style in chars]


def break_lines(
    runs: Sequence[Run], widths: Sequence[float], faces: Faces, size_px: float
) -> list[list[Run]] | None:
    """The least-cost feasible split of normalised ``runs`` into ``len(widths)`` lines."""
    chars = [(c, (run.italic, run.bold)) for run in runs for c in run.text]
    split = _best_split(chars, _advances(chars, faces, size_px), widths)
    if split is None:
        return None
    return [_to_runs(chars[s:e]) for s, e in split.segments]


# --- layout ------------------------------------------------------------------------------


def _place(
    chars: Sequence[tuple[str, Style]],
    segments: Sequence[tuple[int, int]],
    centre: tuple[float, float],
    faces: Faces,
    size_px: float,
) -> tuple[Line, ...]:
    cx, cy = centre
    a = size_px * LINE_HEIGHT_RATIO
    top = _top(cy, size_px, len(segments))
    regular = faces["regular"]
    lift = (regular.ascender + regular.descender) / 2 * (size_px / regular.units_per_em)
    lines: list[Line] = []
    for i, (start, end) in enumerate(segments):
        line_top = top + i * a
        baseline = line_top + a / 2 + lift
        measured = []
        for c, style in chars[start:end]:
            face = faces[Run(c, *style).face_key]
            measured.append((c, face.path, measure_run(c, face, size_px)))
        advance = sum(m.advance for _, _, m in measured)
        left = cx - advance / 2
        pen = left
        glyphs: list[PlacedGlyph] = []
        for c, path, m in measured:
            ink = None
            if m.ink is not None:
                x0, y0, x1, y1 = m.ink
                ink = (x0 + pen, y0 + baseline, x1 + pen, y1 + baseline)
            glyphs.append(PlacedGlyph(c, path, size_px, pen, baseline, m.advance, ink))
            pen += m.advance
        lines.append(Line(tuple(glyphs), advance, left, line_top, a))
    return tuple(lines)


def _inside(area: ShapelyPolygon, lines: Sequence[Line]) -> bool:
    boxes = [g.ink for line in lines for g in line.glyphs if g.ink is not None]
    return all(area.covers(shapely.box(*ink)) for ink in boxes)


def _prepare(
    text: str, faces: Faces, size_px: float
) -> tuple[list[tuple[str, Style]], list[float]]:
    chars = _normalise(parse_emphasis(text))
    return chars, _advances(chars, faces, size_px)


def layout_at(text: str, polygon: Polygon, faces: Faces, size_px: float) -> TypesetBlock | None:
    """The block at ``size_px`` with every glyph's ink inside the fitting area, or None."""
    chars, advances = _prepare(text, faces, size_px)
    normalised = "".join(c for c, _ in chars)
    area = fitting_area(polygon)
    if area.is_empty:
        return None
    centre = _centre(area.bounds)
    height = area.bounds[3] - area.bounds[1]
    pieces = len(_opportunities(normalised)) + 1
    candidates: list[tuple[float, int, _Split]] = []
    n = 1
    while n <= pieces and n * size_px * LINE_HEIGHT_RATIO <= height:
        split = _best_split(chars, advances, line_widths(area, size_px, n))
        if split is not None:
            candidates.append((split.cost, n, split))
        n += 1
    for _, _, split in sorted(candidates, key=lambda c: (c[0], c[1])):
        lines = _place(chars, split.segments, centre, faces, size_px)
        if _inside(area, lines):
            return TypesetBlock(lines, size_px, False, normalised)
    return None


def _sizes() -> list[float]:
    steps = round((MAX_SIZE_PX - MIN_SIZE_PX) / SIZE_STEP_PX)
    return [MAX_SIZE_PX - i * SIZE_STEP_PX for i in range(steps + 1)]


def typeset(text: str, polygon: Polygon, faces: Faces) -> TypesetBlock:
    """The largest size on the grid at which ``text`` fits; else overflow at the minimum."""
    chars, advances = _prepare(text, faces, MIN_SIZE_PX)
    if not chars:
        return TypesetBlock((), MAX_SIZE_PX, False, "")
    for size in _sizes():
        block = layout_at(text, polygon, faces, size)
        if block is not None:
            return block
    area = fitting_area(polygon)
    bounds = ShapelyPolygon(polygon).bounds if area.is_empty else area.bounds
    width = bounds[2] - bounds[0]
    n = 1
    split = None
    while split is None:
        split = _best_split(chars, advances, [width] * n, allow_wide_words=True)
        n += 1
    lines = _place(chars, split.segments, _centre(bounds), faces, MIN_SIZE_PX)
    return TypesetBlock(lines, MIN_SIZE_PX, True, "".join(c for c, _ in chars))
