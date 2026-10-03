"""What a run of text measures in one face at one size (MT-020 C-4).

One character, one glyph: no kerning, no GPOS, no ligatures. MT-021 draws the
glyphs at exactly the positions `fit` emits, so what is measured is what is drawn.
"""

from __future__ import annotations

from dataclasses import dataclass

from mangatl.typeset.font import Face


@dataclass(frozen=True)
class RunMetrics:
    advance: float  # page px
    ink: tuple[float, float, float, float] | None  # x0, y0, x1, y1; y down


def measure_run(text: str, face: Face, size_px: float) -> RunMetrics:
    """Advance and ink of ``text`` with the pen at x=0 on a baseline at y=0."""
    pen = 0
    box: tuple[float, float, float, float] | None = None
    for char in text:
        name, advance = face.glyph(char)
        bounds = face.ink_units(name)
        if bounds is not None:
            x0, y0, x1, y1 = pen + bounds[0], bounds[1], pen + bounds[2], bounds[3]
            box = (
                (x0, y0, x1, y1)
                if box is None
                else (min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1))
            )
        pen += advance
    k = size_px / face.units_per_em
    ink = None if box is None else (box[0] * k, -box[3] * k, box[2] * k, -box[1] * k)
    return RunMetrics(advance=pen * size_px / face.units_per_em, ink=ink)
