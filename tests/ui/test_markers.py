"""MT-016 AC-7 (badge half) and AC-8: how a bubble marker is painted.

AC-8 is asserted on CAPTURED PAINT CALLS, not on rendered pixels (story, oracle
partition). The halo exists because no single flat colour clears 3:1 against
both black and white art (accessibility.md A-06); a single-stroke marker over a
mid-grey fixture looks fine and fails over black, so a pixel test on grey would
pass a missing halo. The capture is a `QPainter` subclass painting onto a real
`QImage`: every call still reaches Qt, and the ones that matter are recorded.

The checker `_outline_problems` is the assertion. Its discrimination is shown
IN RED by running it over painter functions this file defines itself - a
two-stroke reference that must pass, and a single-stroke, a reversed and a
non-cosmetic variant that must each be rejected (Contract, "AC-8's control").
Those controls import nothing from `mangatl.ui.markers` / `mangatl.ui.link`,
and every test that needs the module imports it inside its body, so the
controls execute while the module does not yet exist. GATES then removes the
halo from the real `paint_marker` (Deferred verification 1).

One pixel test is kept on purpose, for a different claim: the 8-digit fill
tokens are `#RRGGBBAA` and Qt reads `#AARRGGBB` (MT-025 PO-7, story Notes), so
the fill is read back off the image rather than trusted from the string.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QStyleOptionGraphicsItem

from mangatl.ui import tokens_gen

HALO = tokens_gen.OVERLAY_HALO
HALO_EACH_SIDE = tokens_gen.OVERLAY_STROKE_HALO

# (state name, core colour token, core width token, fill token or None)
# components.md §4.3, read out.
STATES: list[tuple[str, str, int, str | None]] = [
    ("IDLE", tokens_gen.OVERLAY_BUBBLE_IDLE, tokens_gen.OVERLAY_STROKE_CORE_IDLE, None),
    (
        "HOVER",
        tokens_gen.OVERLAY_BUBBLE_HOVER,
        tokens_gen.OVERLAY_STROKE_CORE_HOVER,
        tokens_gen.OVERLAY_FILL_HOVER,
    ),
    (
        "SELECTED",
        tokens_gen.OVERLAY_BUBBLE_SELECTED,
        tokens_gen.OVERLAY_STROKE_CORE_SELECTED,
        tokens_gen.OVERLAY_FILL_SELECTED,
    ),
]

STATE_IDS = [state[0] for state in STATES]

# A 160 x 160 square in a 200 x 200 image, as a closed ring. region_id 6 so the
# badge reads "7": neither the id nor a hard-coded "1".
SQUARE = ((20, 20), (180, 20), (180, 180), (20, 180), (20, 20))
SQUARE_BOUNDS = QRectF(20, 20, 160, 160)
REGION_ID = 6
ORDINAL_TEXT = "7"
CENTRE = (100, 100)  # far from the outline and from the top-right badge


def _markers() -> ModuleType:
    return importlib.import_module("mangatl.ui.markers")


def _link() -> ModuleType:
    return importlib.import_module("mangatl.ui.link")


# =============================================================================
# The capture
# =============================================================================


class RecordingPainter(QPainter):
    """A real QPainter that also records the calls AC-8 and AC-7 are about.

    Python-level overrides: `paint_marker` is Python and calls these by
    attribute, so every call it makes lands here first and then in Qt.
    """

    def __init__(self, device: QImage) -> None:
        super().__init__(device)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def strokePath(self, path: QPainterPath, pen: QPen) -> None:  # type: ignore[override]
        self.calls.append(("strokePath", (QPainterPath(path), QPen(pen))))
        super().strokePath(path, pen)

    def drawText(self, *args: Any) -> None:  # type: ignore[override]
        self.calls.append(("drawText", args))
        super().drawText(*args)


def _white_image() -> QImage:
    image = QImage(200, 200, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    return image


def _capture(paint: Callable[[QPainter], None]) -> list[tuple[str, tuple[Any, ...]]]:
    image = _white_image()
    painter = RecordingPainter(image)
    try:
        paint(painter)
    finally:
        painter.end()
    return painter.calls


def _outline_problems(
    calls: list[tuple[str, tuple[Any, ...]]],
    core_colour: str,
    core_width: int,
    outline_bounds: QRectF,
) -> list[str]:
    """Every way the first two strokePath calls differ from halo-then-core.

    Empty means: stroke 1 is the halo (overlay.halo, width core + 2 * halo,
    cosmetic) and stroke 2 is the core (state colour, state width, cosmetic),
    and both stroke the region's outline.
    """
    strokes = [args for name, args in calls if name == "strokePath"]
    if len(strokes) < 2:
        return [f"expected two outline strokes (halo, then core); got {len(strokes)} strokePath"]
    problems: list[str] = []
    expected = [
        ("halo", QColor(HALO), core_width + 2 * HALO_EACH_SIDE),
        ("core", QColor(core_colour), core_width),
    ]
    for (label, colour, width), (path, pen) in zip(expected, strokes[:2], strict=True):
        if pen.color().rgba() != colour.rgba():
            problems.append(f"{label} stroke colour {pen.color().name()} != {colour.name()}")
        if pen.widthF() != float(width):
            problems.append(f"{label} stroke width {pen.widthF()} != {width}")
        if not pen.isCosmetic():
            problems.append(f"{label} pen is not cosmetic")
        if path.boundingRect() != outline_bounds:
            problems.append(f"{label} stroke is not the outline: {path.boundingRect()}")
    return problems


def _texts(calls: list[tuple[str, tuple[Any, ...]]]) -> list[tuple[int, str]]:
    return [
        (index, arg)
        for index, (name, args) in enumerate(calls)
        if name == "drawText"
        for arg in args
        if isinstance(arg, str)
    ]


# =============================================================================
# AC-8 control - runs in RED: the checker discriminates, on local painters
# =============================================================================


def _outline_path() -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in SQUARE]))
    return path


def _pen(colour: str, width: int, cosmetic: bool = True) -> QPen:
    pen = QPen(QColor(colour))
    pen.setWidthF(width)
    pen.setCosmetic(cosmetic)
    return pen


def _reference_two_strokes(painter: QPainter) -> None:
    core, width = tokens_gen.OVERLAY_BUBBLE_IDLE, tokens_gen.OVERLAY_STROKE_CORE_IDLE
    painter.strokePath(_outline_path(), _pen(HALO, width + 2 * HALO_EACH_SIDE))
    painter.strokePath(_outline_path(), _pen(core, width))
    painter.drawText(QRectF(170, 10, 18, 18), Qt.AlignmentFlag.AlignCenter, ORDINAL_TEXT)


def _single_stroke_no_halo(painter: QPainter) -> None:
    core, width = tokens_gen.OVERLAY_BUBBLE_IDLE, tokens_gen.OVERLAY_STROKE_CORE_IDLE
    painter.strokePath(_outline_path(), _pen(core, width))
    painter.drawText(QRectF(170, 10, 18, 18), Qt.AlignmentFlag.AlignCenter, ORDINAL_TEXT)


def _core_then_halo(painter: QPainter) -> None:
    core, width = tokens_gen.OVERLAY_BUBBLE_IDLE, tokens_gen.OVERLAY_STROKE_CORE_IDLE
    painter.strokePath(_outline_path(), _pen(core, width))
    painter.strokePath(_outline_path(), _pen(HALO, width + 2 * HALO_EACH_SIDE))


def _non_cosmetic_halo(painter: QPainter) -> None:
    core, width = tokens_gen.OVERLAY_BUBBLE_IDLE, tokens_gen.OVERLAY_STROKE_CORE_IDLE
    painter.strokePath(_outline_path(), _pen(HALO, width + 2 * HALO_EACH_SIDE, cosmetic=False))
    painter.strokePath(_outline_path(), _pen(core, width))


def _idle_problems(paint: Callable[[QPainter], None]) -> list[str]:
    return _outline_problems(
        _capture(paint),
        tokens_gen.OVERLAY_BUBBLE_IDLE,
        tokens_gen.OVERLAY_STROKE_CORE_IDLE,
        SQUARE_BOUNDS,
    )


def test_control_the_outline_checker_accepts_a_halo_then_core_marker(qapp) -> None:  # type: ignore[no-untyped-def]
    assert _idle_problems(_reference_two_strokes) == []


def test_control_the_outline_checker_rejects_a_single_stroke_marker_with_no_halo(qapp) -> None:  # type: ignore[no-untyped-def]
    problems = _idle_problems(_single_stroke_no_halo)
    assert problems == ["expected two outline strokes (halo, then core); got 1 strokePath"]


def test_control_the_outline_checker_rejects_core_drawn_before_halo(qapp) -> None:  # type: ignore[no-untyped-def]
    problems = _idle_problems(_core_then_halo)
    # both strokes wrong in colour and width: 4 problems.
    assert len(problems) == 4
    assert any(p.startswith("halo stroke colour") for p in problems)


def test_control_the_outline_checker_rejects_a_non_cosmetic_halo(qapp) -> None:  # type: ignore[no-untyped-def]
    assert _idle_problems(_non_cosmetic_halo) == ["halo pen is not cosmetic"]


# =============================================================================
# rgba_colour - tokens are #RRGGBBAA, Qt reads #AARRGGBB
# =============================================================================


def test_rgba_colour_reads_an_8_digit_token_as_rrggbbaa_not_qts_aarrggbb() -> None:
    colour = _markers().rgba_colour("#4CC2FF1A")
    assert (colour.red(), colour.green(), colour.blue(), colour.alpha()) == (
        0x4C,
        0xC2,
        0xFF,
        0x1A,
    )


def test_rgba_colour_reads_a_6_digit_token_as_opaque() -> None:
    colour = _markers().rgba_colour("#0B0B0B")
    assert (colour.red(), colour.green(), colour.blue(), colour.alpha()) == (0x0B, 0x0B, 0x0B, 255)


@pytest.mark.parametrize(
    "token",
    [
        tokens_gen.OVERLAY_FILL_HOVER,
        tokens_gen.OVERLAY_FILL_SELECTED,
        tokens_gen.OVERLAY_FILL_ERROR,
    ],
)
def test_rgba_colour_round_trips_every_overlay_fill_token(token: str) -> None:
    colour = _markers().rgba_colour(token)
    expected = tuple(int(token[i : i + 2], 16) for i in (1, 3, 5, 7))
    assert (colour.red(), colour.green(), colour.blue(), colour.alpha()) == expected


# =============================================================================
# AC-8 - the real paint_marker draws halo, then core, in every state
# =============================================================================


def _region() -> Any:
    return _link().OrderedRegion(region_id=REGION_ID, polygon=SQUARE)


def _paint_real(state_name: str) -> Callable[[QPainter], None]:
    markers = _markers()
    region = _region()
    state = markers.MarkerState[state_name]
    return lambda painter: markers.paint_marker(painter, region, state)


def test_marker_state_has_exactly_idle_hover_and_selected() -> None:
    assert [member.name for member in _markers().MarkerState] == ["IDLE", "HOVER", "SELECTED"]


@pytest.mark.parametrize(("state_name", "core", "width", "fill"), STATES, ids=STATE_IDS)
def test_every_marker_state_is_stroked_twice_halo_first_then_the_state_core(
    qapp,  # type: ignore[no-untyped-def]
    state_name: str,
    core: str,
    width: int,
    fill: str | None,
) -> None:
    calls = _capture(_paint_real(state_name))
    assert _outline_problems(calls, core, width, SQUARE_BOUNDS) == []


@pytest.mark.parametrize(("state_name", "core", "width", "fill"), STATES, ids=STATE_IDS)
def test_the_badge_numeral_is_the_ordinal_and_is_drawn_after_both_outline_strokes(
    qapp,  # type: ignore[no-untyped-def]
    state_name: str,
    core: str,
    width: int,
    fill: str | None,
) -> None:
    calls = _capture(_paint_real(state_name))
    stroke_indices = [i for i, (name, _) in enumerate(calls) if name == "strokePath"]
    ordinal_draws = [i for i, text in _texts(calls) if text == ORDINAL_TEXT]
    assert ordinal_draws, f"no drawText of {ORDINAL_TEXT!r}; texts drawn: {_texts(calls)}"
    assert len(stroke_indices) >= 2
    assert min(ordinal_draws) > stroke_indices[1]


def _blend_over_white(token: str) -> tuple[int, int, int]:
    """Source-over of an #RRGGBBAA token on opaque white, by hand."""
    r, g, b, a = (int(token[i : i + 2], 16) for i in (1, 3, 5, 7))
    alpha = a / 255
    return tuple(round(c * alpha + 255 * (1 - alpha)) for c in (r, g, b))  # type: ignore[return-value]


@pytest.mark.parametrize(("state_name", "core", "width", "fill"), STATES, ids=STATE_IDS)
def test_the_fill_painted_inside_the_marker_is_the_rrggbbaa_token_read_back_off_the_image(
    qapp,  # type: ignore[no-untyped-def]
    state_name: str,
    core: str,
    width: int,
    fill: str | None,
) -> None:
    image = _white_image()
    painter = QPainter(image)
    try:
        _paint_real(state_name)(painter)
    finally:
        painter.end()
    pixel = image.pixelColor(*CENTRE)
    got = (pixel.red(), pixel.green(), pixel.blue())
    expected = (255, 255, 255) if fill is None else _blend_over_white(fill)
    # +-1 per channel is 8-bit rounding in the blend, not a tolerance on the
    # colour: the #AARRGGBB misreading of the SELECTED fill is (237, 255, 193)
    # against (223, 244, 255) expected - 14+ apart on every channel.
    assert all(abs(g - e) <= 1 for g, e in zip(got, expected, strict=True)), (
        f"{state_name} fill at centre {got}, expected {expected}"
    )


# =============================================================================
# AC-7 (badge half) - every BubbleMarker on the canvas paints its ordinal
# =============================================================================


def test_each_marker_on_the_canvas_paints_its_own_reading_order_ordinal(qtbot) -> None:  # type: ignore[no-untyped-def]
    from mangatl.ui.canvas import PageCanvas

    link = _link()
    regions = [
        link.OrderedRegion(
            region_id=i, polygon=((x, 20), (x + 40, 20), (x + 40, 60), (x, 60), (x, 20))
        )
        for i, x in enumerate((20, 80, 140))
    ]
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.set_regions(regions)

    assert [marker.region.region_id for marker in canvas.markers] == [0, 1, 2]
    for marker in canvas.markers:
        calls = _capture(lambda p, m=marker: m.paint(p, QStyleOptionGraphicsItem(), None))
        texts = [text for _, text in _texts(calls)]
        assert str(marker.region.ordinal) in texts, (
            f"marker {marker.region.region_id} drew {texts}, not its ordinal"
        )
