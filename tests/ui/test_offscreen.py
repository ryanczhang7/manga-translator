"""MT-052: the off-screen indicator's rules and its widget, without a canvas.

`components.md` §4.6 (normative): when the selected region is not fully visible
"an indicator appears: a chevron plus the region's ordinal, pinned to the
viewport edge nearest the region's centre, drawn in `overlay.bubble.selected`
WITH THE HALO, at the same badge size". `accessibility.md` A-06 (halo), A-08
(the exact accessible name).

Every expected number below is computed BY HAND from the story's Contract
(B2-B6) and written out as a literal; nothing is derived from the module under
test. The viewport in the pure cases is 800 x 600 at the origin, so
`h = 14`, `W - h = 786`, `H - h = 586`.

Oracle partition (story `## Contract`):
- AC-3's boundary (Q4) is MECHANICAL: "fully visible" is the viewport with NO
  margin. Its control - an inset predicate must reject the boundary rects - is
  over local predicates that import nothing from `mangatl.ui.offscreen`, so it
  RUNS IN RED.
- AC-5 is SETTLED: B3's signed-distance rule and B4's clamp, read literally.
- AC-6 is MECHANICAL, on captured paint calls (MT-016 AC-8's mechanism). Its
  control - the outline checker must reject a single-stroke chevron - also runs
  in RED.
- AC-7 is SETTLED: A-08's string, exactly.

`mangatl.ui.offscreen` is imported inside each test body (`_off()`), so this
file collects while the module does not exist and the controls execute.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QAccessible, QColor, QImage, QPainter, QPainterPath, QPen

from mangatl.ui import tokens_gen

# --- Settled numbers, read out ------------------------------------------------
TARGET = 28  # accessibility.md A-05: the minimum pointer target
H = TARGET // 2  # 14
BADGE = tokens_gen.OVERLAY_BADGE_SIZE  # 18, components.md §4.2 / §4.6
HALO = tokens_gen.OVERLAY_HALO
HALO_EACH_SIDE = tokens_gen.OVERLAY_STROKE_HALO  # 2
CORE = tokens_gen.OVERLAY_BUBBLE_SELECTED
CORE_WIDTH = tokens_gen.OVERLAY_STROKE_CORE_SELECTED  # 3
NUMERAL = tokens_gen.COLOR_TEXT_ON_ACCENT
MARGIN = 24  # components.md §4.5 `space.6`: the SELECTION margin, not visibility's

assert (BADGE, HALO_EACH_SIDE, CORE_WIDTH) == (18, 2, 3), "tokens moved: recompute by hand"

VIEW = QRectF(0, 0, 800, 600)
EDGES = ["TOP", "RIGHT", "BOTTOM", "LEFT"]


def _off() -> ModuleType:
    return importlib.import_module("mangatl.ui.offscreen")


def _edge(name: str) -> Any:
    return _off().Edge[name]


def _xy(point: QPointF) -> tuple[float, float]:
    return (point.x(), point.y())


# =============================================================================
# B1 - the module's names and settled constants
# =============================================================================


def test_the_indicator_target_is_28_px_the_a05_minimum_pointer_target() -> None:
    assert _off().INDICATOR_TARGET_PX == 28


def test_edge_has_exactly_top_right_bottom_left_in_that_order() -> None:
    assert [member.name for member in _off().Edge] == EDGES


# =============================================================================
# AC-3 boundary control - runs in RED, over local predicates
# =============================================================================
# B2: "fully visible" is the viewport with NO margin (Q4). The boundary rects
# are entirely inside VIEW and within 24 px of its edge. A predicate that tests
# against the 24 px inset (the selection margin) would show an indicator for
# every one of them; the control proves these fixtures have that teeth.

BOUNDARY_RECTS: dict[str, QRectF] = {
    "touching-top-left": QRectF(0, 0, 100, 100),
    "within-margin-of-top-left": QRectF(5, 5, 100, 100),
    "within-margin-of-bottom-right": QRectF(690, 490, 100, 100),  # right 790, bottom 590
    "touching-bottom-right": QRectF(700, 500, 100, 100),  # right 800, bottom 600
    "the-whole-viewport": QRectF(0, 0, 800, 600),
}


def _fully_visible_b2(view: QRectF, region: QRectF) -> bool:
    """B2, transcribed: entirely inside `view`, no margin."""
    return (
        region.left() >= view.left()
        and region.top() >= view.top()
        and region.right() <= view.right()
        and region.bottom() <= view.bottom()
    )


def _fully_visible_inset_wrong(view: QRectF, region: QRectF) -> bool:
    """The WRONG predicate Deferred 2 plants: visibility against the 24 px inset."""
    return _fully_visible_b2(view.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN), region)


@pytest.mark.parametrize("case", sorted(BOUNDARY_RECTS))
def test_control_every_boundary_rect_is_fully_visible_by_b2(case: str) -> None:
    assert _fully_visible_b2(VIEW, BOUNDARY_RECTS[case]) is True


@pytest.mark.parametrize("case", sorted(BOUNDARY_RECTS))
def test_control_an_inset_predicate_rejects_every_boundary_rect(case: str) -> None:
    # If this passed for a case, that case could not tell B2 from the inset.
    assert _fully_visible_inset_wrong(VIEW, BOUNDARY_RECTS[case]) is False


@pytest.mark.parametrize("case", sorted(BOUNDARY_RECTS))
def test_a_region_inside_the_viewport_but_within_24_px_of_its_edge_gets_no_indicator(
    case: str,
) -> None:
    got = _off().indicator_edge(VIEW, BOUNDARY_RECTS[case])
    assert got is None, (
        f"{case}: {BOUNDARY_RECTS[case]} is entirely inside the viewport {VIEW} and so is "
        f"fully visible (Q4), but indicator_edge returned {got} - is it testing the 24 px inset?"
    )


@pytest.mark.parametrize(
    ("case", "rect"),
    [
        ("half-a-pixel-past-the-right-edge", QRectF(700.5, 250, 100, 100)),
        ("half-a-pixel-past-the-bottom-edge", QRectF(300, 500.5, 100, 100)),
        ("half-a-pixel-past-the-left-edge", QRectF(-0.5, 250, 100, 100)),
        ("half-a-pixel-past-the-top-edge", QRectF(300, -0.5, 100, 100)),
        ("wider-than-the-viewport", QRectF(-10, 250, 820, 100)),
        ("taller-than-the-viewport", QRectF(300, -10, 100, 620)),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_region_not_entirely_inside_the_viewport_gets_an_indicator(
    case: str, rect: QRectF
) -> None:
    assert _off().indicator_edge(VIEW, rect) is not None, f"{case}: {rect} is not fully visible"


# =============================================================================
# AC-5 - the edge nearest the region's centre, and the position along it (B3, B4)
# =============================================================================
# (case, region rect, expected edge, expected centre). Hand-worked: c is the
# rect's centre; distances TOP c.y, RIGHT 800 - c.x, BOTTOM 600 - c.y, LEFT c.x;
# smallest wins, ties TOP > RIGHT > BOTTOM > LEFT; then B4's clamp to [14, 786]
# x [14, 586].
PLACEMENTS: list[tuple[str, QRectF, str, tuple[float, float]]] = [
    # c (350, -150): TOP -150 | RIGHT 450 | BOTTOM 750 | LEFT 350
    ("beyond-top", QRectF(300, -200, 100, 100), "TOP", (350, H)),
    # c (950, 300): TOP 300 | RIGHT -150 | BOTTOM 300 | LEFT 950
    ("beyond-right", QRectF(900, 250, 100, 100), "RIGHT", (800 - H, 300)),
    # c (250, 750): TOP 750 | RIGHT 550 | BOTTOM -150 | LEFT 250
    ("beyond-bottom", QRectF(200, 700, 100, 100), "BOTTOM", (250, 600 - H)),
    # c (-250, 150): TOP 150 | RIGHT 1050 | BOTTOM 450 | LEFT -250
    ("beyond-left", QRectF(-300, 100, 100, 100), "LEFT", (H, 150)),
    # straddling the right edge: c (800, 300): RIGHT 0 is smallest
    ("straddling-right", QRectF(750, 250, 100, 100), "RIGHT", (800 - H, 300)),
    # straddling the left edge: c (0, 400): LEFT 0 < TOP 400, BOTTOM 200
    ("straddling-left", QRectF(-50, 350, 100, 100), "LEFT", (H, 400)),
    # near a corner, clamped: c (5, 500): LEFT 5 < BOTTOM 100
    ("clamped-along-the-left-edge", QRectF(-45, 450, 100, 100), "LEFT", (H, 500)),
    # clamped along the top: c (795, -20): TOP -20 < RIGHT 5
    ("clamped-along-the-top-edge", QRectF(745, -70, 100, 100), "TOP", (800 - H, H)),
    # B3 read literally (§4.6): overflows horizontally only, centre (400, 250)
    # is nearer the TOP (250) than the bottom (350) or the sides (400).
    ("overflowing-sideways-centre-nearer-top", QRectF(-100, 200, 1000, 100), "TOP", (400, H)),
    # Deferred 3's discriminating case. c (-100, -150): TOP -150 < LEFT -100, so
    # TOP. Measured from the viewport CENTRE (400, 300) the offset is (-500,
    # -450): mostly horizontal, which a centre-distance rule reads as LEFT.
    ("beyond-top-left-top-by-signed-distance", QRectF(-150, -200, 100, 100), "TOP", (H, H)),
    # Deferred 3 again, other axis. c (1000, 550): RIGHT -200 < BOTTOM 50. From
    # the viewport centre the offset is (600, 250): also RIGHT - so this case
    # pins B3 against LEFT/RIGHT swapped, and the one above against the centre.
    ("beyond-right-near-bottom", QRectF(950, 500, 100, 100), "RIGHT", (800 - H, 550)),
]
PLACEMENT_IDS = [case for case, *_ in PLACEMENTS]

# Ties break TOP, RIGHT, BOTTOM, LEFT (B3).
TIES: list[tuple[str, QRectF, str, tuple[float, float]]] = [
    # c (-250, -250): TOP -250 == LEFT -250 -> TOP
    ("top-left-corner-tie-goes-to-top", QRectF(-300, -300, 100, 100), "TOP", (H, H)),
    # c (1000, 800): RIGHT -200 == BOTTOM -200 -> RIGHT
    ("bottom-right-corner-tie-goes-to-right", QRectF(950, 750, 100, 100), "RIGHT", (786, 586)),
    # c (-200, 800): BOTTOM -200 == LEFT -200 -> BOTTOM
    ("bottom-left-corner-tie-goes-to-bottom", QRectF(-250, 750, 100, 100), "BOTTOM", (H, 586)),
    # c (1000, -200): TOP -200 == RIGHT -200 -> TOP
    ("top-right-corner-tie-goes-to-top", QRectF(950, -250, 100, 100), "TOP", (786, H)),
]
TIE_IDS = [case for case, *_ in TIES]


@pytest.mark.parametrize(("case", "rect", "edge", "centre"), PLACEMENTS, ids=PLACEMENT_IDS)
def test_the_indicator_is_pinned_to_the_edge_nearest_the_regions_centre_at_the_b4_position(
    case: str, rect: QRectF, edge: str, centre: tuple[float, float]
) -> None:
    got = _off().indicator_edge(VIEW, rect)
    assert got is not None, f"{case}: no indicator for {rect}"
    got_edge, got_centre = got
    assert (got_edge.name, _xy(got_centre)) == (edge, centre), f"{case}: {rect}"


@pytest.mark.parametrize(("case", "rect", "edge", "centre"), TIES, ids=TIE_IDS)
def test_a_tie_between_two_edges_breaks_top_then_right_then_bottom_then_left(
    case: str, rect: QRectF, edge: str, centre: tuple[float, float]
) -> None:
    got = _off().indicator_edge(VIEW, rect)
    assert got is not None
    assert (got[0].name, _xy(got[1])) == (edge, centre), f"{case}: {rect}"


# =============================================================================
# AC-5 - the chevron points outward through its edge; the badge sits inboard (B5)
# =============================================================================
# m = (14, 14); u outward; v = (-u.y, u.x); points (m+7u+5v, m+11u, m+7u-5v).
CHEVRONS: dict[str, tuple[tuple[float, float], tuple[float, float], tuple[float, float]]] = {
    "TOP": ((19, 7), (14, 3), (9, 7)),  # u (0,-1), v (1, 0)
    "RIGHT": ((21, 19), (25, 14), (21, 9)),  # u (1, 0), v (0, 1)
    "BOTTOM": ((9, 21), (14, 25), (19, 21)),  # u (0, 1), v (-1,0)
    "LEFT": ((7, 9), (3, 14), (7, 19)),  # u (-1,0), v (0,-1)
}
# The 18 px square centred on m - 3u.
BADGES: dict[str, tuple[float, float, float, float]] = {
    "TOP": (5, 8, 18, 18),  # centre (14, 17)
    "RIGHT": (2, 5, 18, 18),  # centre (11, 14)
    "BOTTOM": (5, 2, 18, 18),  # centre (14, 11)
    "LEFT": (8, 5, 18, 18),  # centre (17, 14)
}


@pytest.mark.parametrize("edge", EDGES)
def test_the_chevron_is_arm_apex_arm_with_the_apex_pointing_out_through_its_edge(edge: str) -> None:
    points = _off().chevron_points(_edge(edge))
    assert tuple(_xy(p) for p in points) == CHEVRONS[edge]


@pytest.mark.parametrize("edge", EDGES)
def test_the_badge_is_an_18_px_square_shifted_3_px_inboard_of_the_widget_centre(edge: str) -> None:
    rect = _off().badge_rect(_edge(edge))
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == BADGES[edge]


@pytest.mark.parametrize("edge", EDGES)
def test_the_chevron_lies_outboard_of_the_badge_and_inside_the_28_px_widget(edge: str) -> None:
    off = _off()
    badge = off.badge_rect(_edge(edge))
    widget = QRectF(0, 0, TARGET, TARGET)
    for point in off.chevron_points(_edge(edge)):
        assert widget.contains(point), f"{edge}: chevron point {_xy(point)} outside the widget"
        assert not badge.contains(point), f"{edge}: chevron point {_xy(point)} inside the badge"


# =============================================================================
# AC-6 - the capture, and its control (runs in RED)
# =============================================================================


class RecordingPainter(QPainter):
    """A real QPainter that also records what AC-6 is about, in DEVICE
    coordinates (through the world transform at the time of the call), so a
    `translate` + local rect and a direct rect record the same thing."""

    def __init__(self, device: QImage) -> None:
        super().__init__(device)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def strokePath(self, path: QPainterPath, pen: QPen) -> None:  # type: ignore[override]
        self.calls.append(("strokePath", (self.worldTransform().map(path), QPen(pen))))
        super().strokePath(path, pen)

    def drawEllipse(self, *args: Any) -> None:  # type: ignore[override]
        if isinstance(args[0], QPointF):  # (centre, rx, ry)
            centre, rx, ry = args
            rect = QRectF(centre.x() - rx, centre.y() - ry, 2 * rx, 2 * ry)
        elif len(args) == 1:
            rect = QRectF(args[0])
        else:
            rect = QRectF(*args)
        self.calls.append(
            ("drawEllipse", (self.worldTransform().mapRect(rect), QPen(self.pen()), self.brush()))
        )
        super().drawEllipse(*args)

    def drawText(self, *args: Any) -> None:  # type: ignore[override]
        rect = QRectF(args[0]) if isinstance(args[0], QRectF | QRect) else None
        mapped = None if rect is None else self.worldTransform().mapRect(rect)
        texts = [arg for arg in args if isinstance(arg, str)]
        self.calls.append(("drawText", (mapped, texts, QPen(self.pen()))))
        super().drawText(*args)


def _capture(paint: Callable[[QPainter], None]) -> list[tuple[str, tuple[Any, ...]]]:
    image = QImage(TARGET, TARGET, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    painter = RecordingPainter(image)
    try:
        paint(painter)
    finally:
        painter.end()
    return painter.calls


def _polyline(points: tuple[tuple[float, float], ...]) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    return path


def _path_points(path: QPainterPath) -> list[tuple[float, float]]:
    return [(path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount())]


def _outline_problems(
    calls: list[tuple[str, tuple[Any, ...]]],
    chevron: tuple[tuple[float, float], ...],
) -> list[str]:
    """Every way the first two strokePath calls differ from halo-then-core on
    the chevron (MT-016 AC-8's checker, applied to the indicator's chevron).

    Empty means: stroke 1 is the halo (overlay.halo, width core + 2 * halo,
    cosmetic), stroke 2 the selected core (overlay.bubble.selected, core width,
    cosmetic), and both are the open polyline through the chevron's 3 points.
    """
    strokes = [args for name, args in calls if name == "strokePath"]
    if len(strokes) < 2:
        return [f"expected two chevron strokes (halo, then core); got {len(strokes)} strokePath"]
    problems: list[str] = []
    expected = [
        ("halo", QColor(HALO), CORE_WIDTH + 2 * HALO_EACH_SIDE),
        ("core", QColor(CORE), CORE_WIDTH),
    ]
    for (label, colour, width), (path, pen) in zip(expected, strokes[:2], strict=True):
        if pen.color().rgba() != colour.rgba():
            problems.append(f"{label} stroke colour {pen.color().name()} != {colour.name()}")
        if pen.widthF() != float(width):
            problems.append(f"{label} stroke width {pen.widthF()} != {width}")
        if not pen.isCosmetic():
            problems.append(f"{label} pen is not cosmetic")
        if _path_points(path) != list(chevron):
            problems.append(f"{label} stroke is not the chevron polyline: {_path_points(path)}")
    return problems


CONTROL_CHEVRON = CHEVRONS["TOP"]


def _pen(colour: str, width: int, cosmetic: bool = True) -> QPen:
    pen = QPen(QColor(colour))
    pen.setWidthF(width)
    pen.setCosmetic(cosmetic)
    return pen


def _reference_two_strokes(painter: QPainter) -> None:
    painter.strokePath(_polyline(CONTROL_CHEVRON), _pen(HALO, CORE_WIDTH + 2 * HALO_EACH_SIDE))
    painter.strokePath(_polyline(CONTROL_CHEVRON), _pen(CORE, CORE_WIDTH))


def _single_stroke_no_halo(painter: QPainter) -> None:
    painter.strokePath(_polyline(CONTROL_CHEVRON), _pen(CORE, CORE_WIDTH))


def _core_then_halo(painter: QPainter) -> None:
    painter.strokePath(_polyline(CONTROL_CHEVRON), _pen(CORE, CORE_WIDTH))
    painter.strokePath(_polyline(CONTROL_CHEVRON), _pen(HALO, CORE_WIDTH + 2 * HALO_EACH_SIDE))


def _closed_chevron(painter: QPainter) -> None:
    path = _polyline(CONTROL_CHEVRON)
    path.closeSubpath()  # a triangle, not a chevron
    painter.strokePath(path, _pen(HALO, CORE_WIDTH + 2 * HALO_EACH_SIDE))
    painter.strokePath(path, _pen(CORE, CORE_WIDTH))


def test_control_the_outline_checker_accepts_a_halo_then_core_chevron(qapp) -> None:  # type: ignore[no-untyped-def]
    assert _outline_problems(_capture(_reference_two_strokes), CONTROL_CHEVRON) == []


def test_control_the_outline_checker_rejects_a_single_stroke_chevron_with_no_halo(qapp) -> None:  # type: ignore[no-untyped-def]
    problems = _outline_problems(_capture(_single_stroke_no_halo), CONTROL_CHEVRON)
    assert problems == ["expected two chevron strokes (halo, then core); got 1 strokePath"]


def test_control_the_outline_checker_rejects_core_drawn_before_halo(qapp) -> None:  # type: ignore[no-untyped-def]
    problems = _outline_problems(_capture(_core_then_halo), CONTROL_CHEVRON)
    # both strokes wrong in colour and in width: 4 problems.
    assert len(problems) == 4, problems
    assert any(p.startswith("halo stroke colour") for p in problems)


def test_control_the_outline_checker_rejects_a_closed_triangle_for_the_chevron(qapp) -> None:  # type: ignore[no-untyped-def]
    problems = _outline_problems(_capture(_closed_chevron), CONTROL_CHEVRON)
    assert len(problems) == 2, problems
    assert all("not the chevron polyline" in p for p in problems)


# =============================================================================
# AC-6 - the real paint_indicator
# =============================================================================

ORDINAL = 4  # "Bubble 4" in §4.6's example; neither 0 nor 1


def _paint_real(edge: str, ordinal: int = ORDINAL) -> list[tuple[str, tuple[Any, ...]]]:
    off = _off()
    return _capture(lambda painter: off.paint_indicator(painter, ordinal, _edge(edge)))


def _indices(calls: list[tuple[str, tuple[Any, ...]]], name: str) -> list[int]:
    return [i for i, (call, _) in enumerate(calls) if call == name]


@pytest.mark.parametrize("edge", EDGES)
def test_the_indicator_strokes_the_halo_before_the_selected_core_on_its_chevron(
    qapp,  # type: ignore[no-untyped-def]
    edge: str,
) -> None:
    assert _outline_problems(_paint_real(edge), CHEVRONS[edge]) == []


@pytest.mark.parametrize("edge", EDGES)
def test_the_indicator_draws_an_18_px_selected_badge_after_both_chevron_strokes(
    qapp,  # type: ignore[no-untyped-def]
    edge: str,
) -> None:
    calls = _paint_real(edge)
    strokes, ellipses = _indices(calls, "strokePath"), _indices(calls, "drawEllipse")
    assert len(ellipses) == 1, f"expected one badge disc, got {len(ellipses)}"
    assert len(strokes) >= 2 and ellipses[0] > strokes[1], "badge drawn before the chevron"
    rect, pen, brush = calls[ellipses[0]][1]
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == BADGES[edge]
    assert rect.width() == BADGE, "the drawn badge is not overlay.badge.size across"
    # As a SELECTED marker's badge (markers._paint_badge): halo ring, selected disc.
    assert pen.color().rgba() == QColor(HALO).rgba(), pen.color().name()
    assert pen.widthF() == float(HALO_EACH_SIDE)
    assert brush.color().rgba() == QColor(CORE).rgba(), brush.color().name()


@pytest.mark.parametrize("edge", EDGES)
@pytest.mark.parametrize("ordinal", [4, 12])
def test_the_indicator_draws_the_regions_ordinal_in_the_badge_last_in_on_accent_text(
    qapp,  # type: ignore[no-untyped-def]
    edge: str,
    ordinal: int,
) -> None:
    calls = _paint_real(edge, ordinal)
    texts = _indices(calls, "drawText")
    assert len(texts) == 1, f"expected one numeral, got {len(texts)}"
    rect, strings, pen = calls[texts[0]][1]
    assert strings == [str(ordinal)]
    assert texts[0] > max(_indices(calls, "drawEllipse")), "numeral drawn under the disc"
    assert rect is not None
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == BADGES[edge]
    assert pen.color().rgba() == QColor(NUMERAL).rgba(), pen.color().name()


# =============================================================================
# The widget (B6) - and AC-6 through its paintEvent, AC-7 on its own
# =============================================================================

NAME_4 = "Bubble 4 is off screen. Activate to show it."  # accessibility.md A-08, exactly


def test_a_new_indicator_has_no_target_a_fixed_28_px_size_and_takes_no_focus(qtbot) -> None:  # type: ignore[no-untyped-def]
    indicator = _off().OffscreenIndicator()
    qtbot.addWidget(indicator)
    assert (indicator.ordinal(), indicator.edge()) == (None, None)
    assert (indicator.minimumWidth(), indicator.minimumHeight()) == (TARGET, TARGET)
    assert (indicator.maximumWidth(), indicator.maximumHeight()) == (TARGET, TARGET)
    assert indicator.focusPolicy() == Qt.FocusPolicy.NoFocus, "§4.7 keeps three focus stops"
    assert not indicator.hasMouseTracking(), "the indicator has no hover look of its own"


@pytest.mark.parametrize("edge", EDGES)
def test_set_target_stores_the_ordinal_and_edge_and_names_it_exactly_as_a08_says(
    qtbot,  # type: ignore[no-untyped-def]
    edge: str,
) -> None:
    indicator = _off().OffscreenIndicator()
    qtbot.addWidget(indicator)
    indicator.set_target(4, _edge(edge))
    assert (indicator.ordinal(), indicator.edge()) == (4, _edge(edge))
    assert indicator.accessibleName() == NAME_4


def test_the_indicators_accessible_role_is_button_and_its_name_follows_set_target(qtbot) -> None:  # type: ignore[no-untyped-def]
    indicator = _off().OffscreenIndicator()
    qtbot.addWidget(indicator)
    indicator.set_target(4, _edge("TOP"))
    with qtbot.waitExposed(indicator):
        indicator.show()
    iface = QAccessible.queryAccessibleInterface(indicator)
    assert iface is not None
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Text.Name) == NAME_4
    indicator.set_target(11, _edge("LEFT"))
    assert iface.text(QAccessible.Text.Name) == "Bubble 11 is off screen. Activate to show it."


def test_the_indicators_paint_event_paints_paint_indicator_with_its_stored_target(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    off = _off()
    seen: list[tuple[int, Any]] = []
    real = off.paint_indicator

    def recording(painter: QPainter, ordinal: int, edge: Any) -> None:
        seen.append((ordinal, edge))
        real(painter, ordinal, edge)

    monkeypatch.setattr(off, "paint_indicator", recording)
    indicator = off.OffscreenIndicator()
    qtbot.addWidget(indicator)
    indicator.set_target(7, off.Edge.BOTTOM)

    indicator.grab()  # renders synchronously through paintEvent

    assert seen and set(seen) == {(7, off.Edge.BOTTOM)}, seen
