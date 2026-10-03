"""MT-020 AC-1, AC-2, AC-3, AC-5 (file level), AC-6, and the C-5 numbers.

**Expected fitting areas are computed in this file**, from the literal `0.12`
(`_typeset_oracle.PINNED_INSET_RATIO`), never by calling `fitting_area` (C-9).
A rectangle `W x H` gives the rectangle inset by `0.12 * min(W, H)` on every
side, written out by hand below; other shapes use shapely's `buffer` on the
input with that literal. Containment is asserted with **no epsilon**.

The shapes:

- `RECT`  300 x 200 at (100, 50). d = 24, so the area is [124, 376] x [74, 226]
  and its centre is (250, 150).
- `SMALL` 60 x 40 at the origin. d = 4.8: [4.8, 55.2] x [4.8, 35.2], centre
  (30, 20), bbox width 50.4. Nothing of `LONG` fits in it at 14 px.
- `THIN`  a band about 5.7 px across along the diagonal of a 100 x 100 box.
  d = 12 exceeds its half-width, so the fitting area is EMPTY.
- `DUMBBELL` a 100 x 100 square joined by a 10 px neck to a 60 x 60 square.
  d = 12 removes the neck, so the buffer is a MultiPolygon of two parts.
- `ELLIPSE` a 64-gon, semi-axes 160 and 110, centred on (200, 150).
"""

from __future__ import annotations

import dataclasses
import math
import shutil
from collections.abc import Sequence
from pathlib import Path

import _typeset_oracle as oracle
import pytest
from shapely.geometry import LineString, MultiPolygon, box
from shapely.geometry import Polygon as ShapelyPolygon

from mangatl.typeset.fit import (
    FIT_INSET_RATIO,
    LINE_HEIGHT_RATIO,
    MAX_SIZE_PX,
    MIN_SIZE_PX,
    SIZE_STEP_PX,
    Line,
    PlacedGlyph,
    TypesetBlock,
    fitting_area,
    layout_at,
    line_widths,
    typeset,
)
from mangatl.typeset.font import FACE_FILES, Faces, MissingGlyph, load_faces
from mangatl.ui.tokens_gen import TOKENS


def _rect(x: int, y: int, w: int, h: int) -> list[tuple[int, int]]:
    # ints, as `Region.polygon` carries them (C-5: ints accepted).
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


RECT = _rect(100, 50, 300, 200)
RECT_AREA = (124.0, 74.0, 376.0, 226.0)  # x0, y0, x1, y1 - by hand, d = 0.12 * 200
RECT_CENTRE = (250.0, 150.0)

SMALL = _rect(0, 0, 60, 40)
SMALL_CENTRE = (30.0, 20.0)
SMALL_AREA_WIDTH = 50.4  # 60 - 2 * 0.12 * 40

THIN = [(0, 0), (4, 0), (100, 96), (100, 100), (96, 100), (0, 4), (0, 0)]
THIN_CENTRE = (50.0, 50.0)  # input bbox centre: the area has none (C-6, amended)
THIN_WIDTH = 100.0  # input bbox width: the overflow layout's W when the area is empty

DUMBBELL = [
    (0, 0), (100, 0), (100, 45), (140, 45), (140, 20), (200, 20),
    (200, 80), (140, 80), (140, 55), (100, 55), (100, 100), (0, 100), (0, 0),
]  # fmt: skip

ELLIPSE = [
    (
        round(200 + 160 * math.cos(2 * math.pi * i / 64), 3),
        round(150 + 110 * math.sin(2 * math.pi * i / 64), 3),
    )
    for i in range(64)
]
ELLIPSE.append(ELLIPSE[0])

#: Long enough that it cannot sit at MAX_SIZE_PX in RECT, so the chosen size is
#: bound by the fitting area - which is what makes an inset of 0.0 visible.
LONG = "We have to get out of here before the whole building comes down on all of us!"
SHORT = "Hi!"
ELLIPSE_TEXT = "Are you serious? You walked all the way here in the rain just to tell me that?"


@pytest.fixture(scope="module")
def faces() -> Faces:
    return load_faces()


def _expected_area(polygon: Sequence[tuple[float, float]]) -> ShapelyPolygon:
    """The fitting area, from the pinned 0.12 - independent of `fitting_area`."""
    shape = ShapelyPolygon(polygon)
    x0, y0, x1, y1 = shape.bounds
    inner = shape.buffer(-oracle.PINNED_INSET_RATIO * min(x1 - x0, y1 - y0))
    if isinstance(inner, MultiPolygon):
        inner = max(inner.geoms, key=lambda g: g.area)
    return inner


def _centre(area: ShapelyPolygon) -> tuple[float, float]:
    x0, y0, x1, y1 = area.bounds
    return (x0 + x1) / 2, (y0 + y1) / 2


def _glyphs(block: TypesetBlock) -> list[PlacedGlyph]:
    return [g for line in block.lines for g in line.glyphs]


def _line_texts(block: TypesetBlock) -> list[str]:
    return ["".join(g.char for g in line.glyphs) for line in block.lines]


def _independent_width(area: ShapelyPolygon, cx: float, y0: float, y1: float) -> float:
    """C-5's `w_i` by an independent bisection to 1e-6 px."""
    if not area.covers(LineString([(cx, y0), (cx, y1)])):
        return 0.0
    lo, hi = 0.0, area.bounds[2] - area.bounds[0]
    while hi - lo > 1e-6:
        mid = (lo + hi) / 2
        if area.covers(box(cx - mid, y0, cx + mid, y1)):
            lo = mid
        else:
            hi = mid
    return 2 * lo


def _strip_dir(block: TypesetBlock) -> TypesetBlock:
    lines = tuple(
        dataclasses.replace(
            line,
            glyphs=tuple(
                dataclasses.replace(g, font_path=Path(g.font_path.name)) for g in line.glyphs
            ),
        )
        for line in block.lines
    )
    return dataclasses.replace(block, lines=lines)


# --- C-5: the numbers are the design tokens --------------------------------------


@pytest.mark.parametrize(
    ("value", "pinned", "token"),
    [
        (MIN_SIZE_PX, 14.0, "typeset.size-min"),
        (MAX_SIZE_PX, 42.0, "typeset.size-max"),
        (SIZE_STEP_PX, 1.0, "typeset.size-step"),
        (LINE_HEIGHT_RATIO, 1.08, "typeset.line-height"),
        (FIT_INSET_RATIO, 0.12, "typeset.padding-ratio"),
    ],
    ids=["size-min", "size-max", "size-step", "line-height", "padding-ratio"],
)
def test_each_fitting_number_is_its_pinned_value_and_equals_its_design_token(
    value: float, pinned: float, token: str
) -> None:
    assert value == pinned
    assert float(TOKENS[token]) == value


def test_the_typesetter_does_not_hyphenate_per_the_design_token() -> None:
    assert TOKENS["typeset.hyphenate"] == "false"


# --- C-5: the fitting area ------------------------------------------------------------


def test_fitting_area_of_a_rectangle_is_it_inset_by_twelve_percent_of_its_short_side() -> None:
    area = fitting_area(RECT)
    assert area.geom_type == "Polygon"
    assert area.bounds == pytest.approx(RECT_AREA, abs=1e-9)
    assert area.area == pytest.approx(252.0 * 152.0, abs=1e-6)


def test_fitting_area_of_a_split_buffer_is_its_largest_part() -> None:
    raw = ShapelyPolygon(DUMBBELL).buffer(-12.0)
    assert isinstance(raw, MultiPolygon)  # fixture check: the neck really goes
    area = fitting_area(DUMBBELL)
    assert area.geom_type == "Polygon"
    assert area.symmetric_difference(_expected_area(DUMBBELL)).area < 1e-6
    assert area.bounds[0] == pytest.approx(12.0) and area.bounds[2] < 100.0


def test_fitting_area_of_a_polygon_thinner_than_the_inset_is_empty() -> None:
    assert _expected_area(THIN).is_empty  # fixture check
    assert fitting_area(THIN).is_empty


def test_line_widths_in_a_rectangle_are_its_inner_width_or_zero_outside_it() -> None:
    # s = 20: a = 21.6; n = 8 is 172.8 tall against an area 152 tall, centred on
    # y = 150, so t = 63.6. Line 0 is [63.6, 85.2] (pokes above 74) and line 7 is
    # [214.8, 236.4] (below 226): zero. Lines 1-6 are inside: the full 252.
    area = fitting_area(RECT)
    assert line_widths(area, 20.0, 8) == pytest.approx([0.0] + [252.0] * 6 + [0.0], abs=0.021)
    assert line_widths(area, 20.0, 1) == pytest.approx([252.0], abs=0.021)


def test_line_widths_in_an_ellipse_follow_its_outline_narrow_wide_narrow() -> None:
    expected_area = _expected_area(ELLIPSE)
    cx, cy = _centre(expected_area)
    size, n = 30.0, 3
    a = size * 1.08
    top = cy - n * a / 2
    expected = [
        _independent_width(expected_area, cx, top + i * a, top + (i + 1) * a) for i in range(n)
    ]
    assert expected[0] < expected[1] > expected[2]  # fixture check: the shape matters
    got = line_widths(fitting_area(ELLIPSE), size, n)
    assert got == pytest.approx(expected, abs=0.021)


# --- AC-1: inside the fitting area, at the largest size that achieves it ---------


def test_every_glyph_ink_box_lies_inside_the_rectangle_inset_by_twelve_percent(
    faces: Faces,
) -> None:
    block = typeset(LONG, RECT, faces)
    assert not block.overflowed
    x0, y0, x1, y1 = RECT_AREA
    inked = [g for g in _glyphs(block) if g.ink is not None]
    assert inked
    outside = [
        (g.char, g.ink)
        for g in inked
        if g.ink is not None
        and not (x0 <= g.ink[0] and g.ink[2] <= x1 and y0 <= g.ink[1] and g.ink[3] <= y1)
    ]
    assert outside == []


def test_the_size_chosen_is_the_largest_on_the_grid_at_which_the_text_fits(
    faces: Faces,
) -> None:
    block = typeset(LONG, RECT, faces)
    assert MIN_SIZE_PX <= block.size_px < MAX_SIZE_PX
    assert block.size_px == float(int(block.size_px))
    assert layout_at(LONG, RECT, faces, block.size_px) == block
    assert layout_at(LONG, RECT, faces, block.size_px + SIZE_STEP_PX) is None


def test_a_short_line_in_a_roomy_bubble_sits_at_the_maximum_size(faces: Faces) -> None:
    block = typeset(SHORT, RECT, faces)
    assert block.size_px == MAX_SIZE_PX
    assert not block.overflowed
    x0, y0, x1, y1 = RECT_AREA
    for g in _glyphs(block):
        if g.ink is not None:
            assert x0 <= g.ink[0] and g.ink[2] <= x1 and y0 <= g.ink[1] and g.ink[3] <= y1


def test_in_an_ellipse_every_glyph_is_inside_and_each_line_fits_its_own_width(
    faces: Faces,
) -> None:
    expected_area = _expected_area(ELLIPSE)
    block = typeset(ELLIPSE_TEXT, ELLIPSE, faces)
    assert not block.overflowed
    assert len(block.lines) >= 3
    outside = [
        g.char
        for g in _glyphs(block)
        if g.ink is not None and not expected_area.covers(box(*g.ink))
    ]
    assert outside == []
    cx, _ = _centre(expected_area)
    for line in block.lines:
        width = _independent_width(expected_area, cx, line.top, line.top + line.height)
        assert line.advance <= width + 0.021, _line_texts(block)
    assert layout_at(ELLIPSE_TEXT, ELLIPSE, faces, block.size_px + SIZE_STEP_PX) is None


#: (R-2) Descender-heavy text. The hhea box is 1.34 em against a 1.08 em line
#: advance, so at some size a candidate fits every per-line width while its
#: descenders cross below the fitting area. Only C-6's ink-containment check
#: rejects it. Without the check, "gyp ..." sets at 35 px in RECT, with ink to
#: y = 228.09 > 226 (the size step-down case). "Yep ..." sets at 28 px in BOX,
#: with six descenders outside (the 3- to 4-line case). Both values were measured
#: with mutate.sh (R-2).
GYP = "gyp gyp gyp gyp gyp gyp gyp gyp gyp gyp"
YEP = "Yep, jolly piggy jumps; giggly puppy yaps"
BOX = _rect(0, 0, 240, 160)
BOX_AREA = (19.2, 19.2, 220.8, 140.8)  # x0, y0, x1, y1 - by hand, d = 0.12 * 160 = 19.2


@pytest.mark.parametrize(
    ("text", "polygon", "area"),
    [(GYP, RECT, RECT_AREA), (YEP, BOX, BOX_AREA)],
    ids=["gyp-in-rect", "yep-in-box"],
)
def test_descender_ink_stays_inside_the_area_even_when_every_line_fits_its_width(
    faces: Faces,
    text: str,
    polygon: list[tuple[int, int]],
    area: tuple[float, float, float, float],
) -> None:
    block = typeset(text, polygon, faces)
    assert block.overflowed is False
    x0, y0, x1, y1 = area
    inked = [g for g in _glyphs(block) if g.ink is not None]
    assert inked
    outside = [
        (g.char, g.ink)
        for g in inked
        if g.ink is not None
        and not (x0 <= g.ink[0] and g.ink[2] <= x1 and y0 <= g.ink[1] and g.ink[3] <= y1)
    ]
    assert outside == [], f"ink outside the 0.12 area at {block.size_px} px"
    assert layout_at(text, polygon, faces, block.size_px + SIZE_STEP_PX) is None


# --- AC-2: lines centred on cx, the block on cy ----------------------------------------


@pytest.mark.parametrize("which", ["rect", "ellipse"])
def test_each_line_is_centred_horizontally_and_the_block_vertically(
    faces: Faces, which: str
) -> None:
    polygon, text = (RECT, LONG) if which == "rect" else (ELLIPSE, ELLIPSE_TEXT)
    cx, cy = _centre(_expected_area(polygon))
    block = typeset(text, polygon, faces)
    assert len(block.lines) >= 2
    for line in block.lines:
        assert line.left + line.advance / 2 == pytest.approx(cx, abs=1e-6)
    a = block.size_px * 1.08
    n = len(block.lines)
    for i, line in enumerate(block.lines):
        assert line.height == pytest.approx(a, abs=1e-9)
        assert line.top == pytest.approx(cy - n * a / 2 + i * a, abs=1e-6)
    assert (block.lines[0].top + block.lines[-1].top + a) / 2 == pytest.approx(cy, abs=1e-6)


def test_glyphs_follow_by_advance_on_a_baseline_centring_the_hhea_box_in_the_line(
    faces: Faces,
) -> None:
    block = typeset(LONG, RECT, faces)
    size = block.size_px
    ascent, descent = oracle.hhea("regular")
    k = size / oracle.units_per_em("regular")
    for line in block.lines:
        assert isinstance(line, Line)
        assert line.glyphs[0].x == pytest.approx(line.left, abs=1e-9)
        assert line.advance == pytest.approx(sum(g.advance for g in line.glyphs), abs=1e-9)
        baseline = line.top + line.height / 2 + (ascent + descent) / 2 * k
        pen = line.left
        for g in line.glyphs:
            assert g.size_px == size
            assert g.x == pytest.approx(pen, abs=1e-6)
            assert g.baseline_y == pytest.approx(baseline, abs=1e-6)
            assert g.advance == pytest.approx(oracle.advance_px(g.char, "regular", size), rel=1e-12)
            ink = oracle.ink_px(g.char, "regular", size)
            if ink is None:
                assert g.ink is None
            else:
                moved = (ink[0] + g.x, ink[1] + g.baseline_y, ink[2] + g.x, ink[3] + g.baseline_y)
                assert g.ink == pytest.approx(moved, abs=1e-6)
            pen += g.advance


# --- AC-3: overflow is reported, at the minimum size, with nothing dropped ----------


def test_text_that_cannot_fit_is_set_at_the_minimum_size_and_reported_as_overflow(
    faces: Faces,
) -> None:
    text = "  We  have\tto get *out* of here\nbefore the whole well-known building comes down!  "
    expected = "We have to get out of here before the whole well-known building comes down!"
    block = typeset(text, SMALL, faces)
    assert block.overflowed is True
    assert block.size_px == MIN_SIZE_PX
    assert block.text == expected
    assert oracle.join_lines(_line_texts(block)) == expected
    assert layout_at(text, SMALL, faces, MIN_SIZE_PX) is None


def test_an_overflowed_block_uses_the_fewest_lines_of_the_area_width(faces: Faces) -> None:
    text = "We have to get out of here before the whole well-known building comes down!"
    italic = range(text.index("out"), text.index("out") + 3)
    keys = ["italic" if i in italic else "regular" for i in range(len(text))]

    def adv(s: int, e: int) -> float:
        return oracle.styled_advance(list(zip(text[s:e], keys[s:e], strict=True)), 14.0)

    block = typeset(text.replace("out", "*out*"), SMALL, faces)
    assert block.overflowed
    assert len(block.lines) == oracle.min_lines_allowing_wide_words(text, SMALL_AREA_WIDTH, adv)
    cx, cy = SMALL_CENTRE
    a = 14.0 * 1.08
    for line in block.lines:
        assert line.left + line.advance / 2 == pytest.approx(cx, abs=1e-6)
    assert block.lines[0].top + len(block.lines) * a / 2 == pytest.approx(cy, abs=1e-6)


def test_a_word_wider_than_the_bubble_gets_a_line_of_its_own_unbroken(faces: Faces) -> None:
    text = "a Supercalifragilisticexpialidocious b"
    block = typeset(text, SMALL, faces)
    assert block.overflowed
    assert block.size_px == MIN_SIZE_PX
    assert "Supercalifragilisticexpialidocious" in _line_texts(block)
    assert oracle.join_lines(_line_texts(block)) == text == block.text


def test_a_bubble_with_an_empty_fitting_area_overflows_centred_on_the_outline(
    faces: Faces,
) -> None:
    text = "Look out behind you!"
    block = typeset(text, THIN, faces)
    assert block.overflowed is True
    assert block.size_px == MIN_SIZE_PX
    assert block.text == "Look out behind you!"
    assert oracle.join_lines(_line_texts(block)) == block.text
    assert layout_at(text, THIN, faces, MIN_SIZE_PX) is None
    assert layout_at(text, THIN, faces, MAX_SIZE_PX) is None

    def adv(s: int, e: int) -> float:
        return oracle.advance_px(text[s:e], "regular", 14.0)

    assert len(block.lines) == oracle.min_lines_allowing_wide_words(text, THIN_WIDTH, adv)
    cx, cy = THIN_CENTRE
    for line in block.lines:
        assert line.left + line.advance / 2 == pytest.approx(cx, abs=1e-6)
    a = 14.0 * 1.08
    assert block.lines[0].top + len(block.lines) * a / 2 == pytest.approx(cy, abs=1e-6)


def test_a_block_that_fits_also_reproduces_its_text_exactly(faces: Faces) -> None:
    block = typeset(LONG, RECT, faces)
    assert block.text == LONG
    assert oracle.join_lines(_line_texts(block)) == LONG


def test_whitespace_is_collapsed_to_single_spaces_and_trimmed(faces: Faces) -> None:
    block = typeset("  moon \t\n  moon  ", RECT, faces)
    assert block.text == "moon moon"
    assert oracle.join_lines(_line_texts(block)) == "moon moon"


def test_a_no_break_space_is_kept_and_placed(faces: Faces) -> None:
    block = typeset("moon\u00a0moon", RECT, faces)
    assert block.text == "moon\u00a0moon"
    assert _line_texts(block) == ["moon\u00a0moon"]


@pytest.mark.parametrize("text", ["", "   \t\n "])
def test_empty_text_sets_no_lines_at_the_maximum_size(faces: Faces, text: str) -> None:
    block = typeset(text, RECT, faces)
    assert block == TypesetBlock(lines=(), size_px=MAX_SIZE_PX, overflowed=False, text="")


def test_a_character_no_face_has_raises_missing_glyph(faces: Faces) -> None:
    assert 0x3042 not in oracle.cmap("regular")
    with pytest.raises(MissingGlyph) as excinfo:
        typeset("hello \u3042", RECT, faces)
    assert excinfo.value.char == "\u3042"
    assert excinfo.value.face == "regular"


# --- AC-5: emphasis is drawn from the Italic and Bold FILES -------------------------


def _faces_by_char(block: TypesetBlock) -> list[tuple[str, Path]]:
    return [(g.char, g.font_path) for g in _glyphs(block)]


def test_an_italic_run_is_drawn_from_the_italic_font_file(faces: Faces) -> None:
    block = typeset("a *b* c", RECT, faces)
    regular, italic = FACE_FILES["regular"], FACE_FILES["italic"]
    assert italic.resolve() == (oracle.FONT_DIR / oracle.FILENAMES["italic"]).resolve()
    assert _faces_by_char(block) == [
        ("a", regular),
        (" ", regular),
        ("b", italic),
        (" ", regular),
        ("c", regular),
    ]
    assert block.text == "a b c"


def test_a_bold_run_is_drawn_from_the_bold_font_file(faces: Faces) -> None:
    block = typeset("a **b** c", RECT, faces)
    regular, bold = FACE_FILES["regular"], FACE_FILES["bold"]
    assert bold.resolve() == (oracle.FONT_DIR / oracle.FILENAMES["bold"]).resolve()
    assert _faces_by_char(block) == [
        ("a", regular),
        (" ", regular),
        ("b", bold),
        (" ", regular),
        ("c", regular),
    ]
    assert block.text == "a b c"


def test_an_emphasised_glyph_is_measured_from_its_own_face(faces: Faces) -> None:
    block = typeset("so **BIG** *wow*", RECT, faces)
    for g in _glyphs(block):
        key = {v: k for k, v in FACE_FILES.items()}[g.font_path]
        assert g.advance == pytest.approx(oracle.advance_px(g.char, key, g.size_px), rel=1e-12)


def test_no_consumed_marker_is_placed(faces: Faces) -> None:
    block = typeset("*one* **two** *three*", RECT, faces)
    assert "*" not in "".join(_line_texts(block))
    assert block.text == "one two three"


def test_an_unclosed_marker_is_drawn_literally_in_the_regular_face(faces: Faces) -> None:
    block = typeset("a *b c", RECT, faces)
    assert "".join(_line_texts(block)).replace(" ", "") == "a*bc"
    assert {g.font_path for g in _glyphs(block)} == {FACE_FILES["regular"]}
    assert block.text == "a *b c"


def test_nested_markers_are_literal_and_only_the_inner_span_is_italic(faces: Faces) -> None:
    block = typeset("**a *b* c**", RECT, faces)
    assert block.text == "**a b c**"
    italic = [g.char for g in _glyphs(block) if g.font_path == FACE_FILES["italic"]]
    assert italic == ["b"]


def test_an_escaped_star_is_drawn_as_a_star(faces: Faces) -> None:
    block = typeset("\\*x\\*", RECT, faces)
    assert block.text == "*x*"
    assert _line_texts(block) == ["*x*"]


def test_a_character_missing_from_the_italic_face_names_the_italic_face(faces: Faces) -> None:
    with pytest.raises(MissingGlyph) as excinfo:
        typeset("*\u3042*", RECT, faces)
    assert excinfo.value.face == "italic"


# --- AC-6: byte-identical, independent of where the fonts live ----------------------


def test_typesetting_twice_gives_equal_blocks_with_equal_repr(faces: Faces) -> None:
    first = typeset("Are *you* **serious**? " + ELLIPSE_TEXT, ELLIPSE, faces)
    second = typeset("Are *you* **serious**? " + ELLIPSE_TEXT, ELLIPSE, load_faces())
    assert first == second
    assert repr(first) == repr(second)


def test_a_copy_of_the_font_directory_elsewhere_gives_the_same_layout(
    faces: Faces, tmp_path: Path
) -> None:
    for name in oracle.FILENAMES.values():
        shutil.copyfile(oracle.FONT_DIR / name, tmp_path / name)
    copied = load_faces(tmp_path)
    here = typeset(LONG, RECT, faces)
    there = typeset(LONG, RECT, copied)
    assert {g.font_path.parent for g in _glyphs(there)} == {tmp_path}
    assert _strip_dir(here) == _strip_dir(there)
    assert repr(_strip_dir(here)) == repr(_strip_dir(there))
