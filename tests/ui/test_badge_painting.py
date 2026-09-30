"""MT-051 AC-7: the badges the canvas actually paints are the placed ones.

Asserted on CAPTURED PAINT CALLS, as MT-016 AC-8 was (`test_markers.py`), not on
pixels. The capture is a `QPainter` subclass on a real `QImage` that records every
`drawEllipse` - the badge circle - together with the painter's world transform
at that moment, so each circle is mapped to DEVICE coordinates: exactly what a
screen pixel measures, and exactly the zoomed-scene units `place_badges` returns.

The painter is given the canvas's own transform (`canvas.transform()`: the zoom,
without the pan), which is what `QGraphicsView` hands an item's `paint`, minus a
translation that moves every badge alike.

AC-7's control is MT-016's shipped painter: `paint_marker(painter, region, state)`
with no badge centre is still the nominal circle (Contract), and on the fixture
below the nominal circles collide. That control runs in RED and after it.

Nothing from `mangatl.ui.badges` is imported at module level: the canvas tests
fail on what the canvas paints, not on a missing import.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QStyleOptionGraphicsItem

from mangatl.ui import tokens_gen

SIZE = tokens_gen.OVERLAY_BADGE_SIZE  # 18
GAP = tokens_gen.OVERLAY_BADGE_GAP  # 4
ABS = 1e-6

Point = tuple[float, float]


def _markers() -> ModuleType:
    return importlib.import_module("mangatl.ui.markers")


def _link() -> ModuleType:
    return importlib.import_module("mangatl.ui.link")


# =============================================================================
# The capture
# =============================================================================


class EllipseRecorder(QPainter):
    """A real QPainter that records each ellipse's device centre and diameter."""

    def __init__(self, device: QImage) -> None:
        super().__init__(device)
        self.circles: list[tuple[Point, float, float]] = []
        self.text_centres: list[Point] = []

    def drawEllipse(self, *args: Any) -> None:  # type: ignore[override]
        transform = self.worldTransform()
        if len(args) == 1 and isinstance(args[0], QRectF):
            rect = args[0]
            centre, width, height = rect.center(), rect.width(), rect.height()
        elif len(args) == 3 and isinstance(args[0], QPointF):
            centre, width, height = args[0], 2.0 * args[1], 2.0 * args[2]
        else:
            raise AssertionError(f"drawEllipse overload this capture does not map: {args!r}")
        assert transform.m12() == 0 and transform.m21() == 0, "badge painted under a rotation"
        mapped = transform.map(centre)
        self.circles.append(
            ((mapped.x(), mapped.y()), width * transform.m11(), height * transform.m22())
        )
        super().drawEllipse(*args)

    def drawText(self, *args: Any) -> None:  # type: ignore[override]
        if args and isinstance(args[0], QRectF):
            mapped = self.worldTransform().map(args[0].center())
            self.text_centres.append((mapped.x(), mapped.y()))
        super().drawText(*args)


def _capture(paint: Callable[[QPainter], None], transform: QTransform) -> EllipseRecorder:
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    painter = EllipseRecorder(image)
    try:
        painter.setWorldTransform(transform)
        paint(painter)
    finally:
        painter.end()
    return painter


def _painted_badges(canvas: Any) -> dict[int, Point]:
    """region_id -> device centre of the one circle each marker paints."""
    painted: dict[int, Point] = {}
    for marker in canvas.markers:
        recorder = _capture(
            lambda p, m=marker: m.paint(p, QStyleOptionGraphicsItem(), None), canvas.transform()
        )
        assert len(recorder.circles) == 1, (
            f"marker {marker.region.region_id} painted {len(recorder.circles)} circles"
        )
        centre, width, height = recorder.circles[0]
        assert (width, height) == pytest.approx((SIZE, SIZE), abs=ABS), (
            f"marker {marker.region.region_id}: badge {width} x {height} on screen, not 18 x 18"
        )
        painted[marker.region.region_id] = centre
    return painted


def _collisions(painted: dict[int, Point]) -> list[tuple[int, int, float]]:
    """Every pair (later, earlier, distance) of painted badges closer than size."""
    ids = sorted(painted)
    return [
        (later, earlier, math.dist(painted[later], painted[earlier]))
        for index, later in enumerate(ids)
        for earlier in ids[:index]
        if math.dist(painted[later], painted[earlier]) < SIZE - ABS
    ]


# =============================================================================
# The fixture: test_badges.py's rectangle fixture, as OrderedRegions
# =============================================================================
#
# Worked out by hand in test_badges.py (AC-3, rectangle):
#   0: x 120..130, y 113..140 -> nominal (143, 100)
#   1: x 60..119, y 136..160  -> nominal (132, 123)
#   2: x 100..130, y 100..110 -> nominal (143, 87), 13 from region 0's: taken;
#      slides to (113, 123)
# At zoom 2 nothing collides and all three are nominal:
#   0: (260 + 13, 226 - 13) = (273, 213)
#   1: (238 + 13, 272 - 13) = (251, 259)   0-1: hypot(22, 46) = 51
#   2: (260 + 13, 200 - 13) = (273, 187)   0-2: 26; 1-2: hypot(22, 72) = 75.3
# A layout placed once at zoom 1 and merely scaled would paint region 2 at
# (226, 246) at zoom 2; one placed once at zoom 2 would paint region 2 at (136.5, 93.5)
# and region 0 at (136.5, 106.5) at zoom 1 - 13 apart, colliding again.
RECTS = {0: (120, 113, 130, 140), 1: (60, 136, 119, 160), 2: (100, 100, 130, 110)}
AT_ZOOM_1: dict[int, Point] = {0: (143.0, 100.0), 1: (132.0, 123.0), 2: (113.0, 123.0)}
AT_ZOOM_2: dict[int, Point] = {0: (273.0, 213.0), 1: (251.0, 259.0), 2: (273.0, 187.0)}


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def _regions() -> list[Any]:
    link = _link()
    return [link.OrderedRegion(region_id=rid, polygon=_ring(*box)) for rid, box in RECTS.items()]


def _canvas(qtbot: Any) -> Any:
    from mangatl.ui.canvas import PageCanvas

    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    return canvas


def _assert_painted(painted: dict[int, Point], expected: dict[int, Point], when: str) -> None:
    assert sorted(painted) == sorted(expected)
    wrong = {
        rid: painted[rid]
        for rid in expected
        if painted[rid] != pytest.approx(expected[rid], abs=ABS)
    }
    assert wrong == {}, f"{when}: badges painted at {wrong}, expected {expected}"


# =============================================================================
# AC-7's control - MT-016's nominal painter collides on this fixture (runs in RED)
# =============================================================================


def test_control_mt016s_nominal_painter_paints_colliding_badges_on_this_fixture(qapp) -> None:  # type: ignore[no-untyped-def]
    markers = _markers()
    painted: dict[int, Point] = {}
    for region in _regions():
        recorder = _capture(
            lambda p, r=region: markers.paint_marker(p, r, markers.MarkerState.IDLE),
            QTransform(),
        )
        painted[region.region_id] = recorder.circles[0][0]
    # Nominal: region 2 at (143, 87), 13 from region 0's (143, 100).
    assert painted == {0: (143.0, 100.0), 1: (132.0, 123.0), 2: (143.0, 87.0)}
    assert _collisions(painted) == [(2, 0, 13.0)]


# =============================================================================
# AC-7 - the canvas paints the placed badges, and re-places them on zoom
# =============================================================================


def test_the_canvas_paints_every_badge_where_it_was_placed_and_no_two_overlap(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _canvas(qtbot)
    canvas.set_zoom(1.0)
    canvas.set_regions(_regions())

    painted = _painted_badges(canvas)
    assert _collisions(painted) == [], (
        f"painted badges overlap (later, earlier, distance): {_collisions(painted)}"
    )
    _assert_painted(painted, AT_ZOOM_1, "at zoom 1")

    badges = importlib.import_module("mangatl.ui.badges")
    placed = badges.place_badges(
        [(r.region_id, r.polygon) for r in _regions()], zoom=1.0, size=SIZE, gap=GAP
    )
    _assert_painted(painted, {rid: b.centre for rid, b in placed.items()}, "vs place_badges")


def test_after_set_zoom_the_canvas_paints_the_layout_placed_at_the_new_zoom(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _canvas(qtbot)
    canvas.set_zoom(2.0)
    canvas.set_regions(_regions())
    _assert_painted(_painted_badges(canvas), AT_ZOOM_2, "regions set at zoom 2")

    canvas.set_zoom(1.0)
    painted = _painted_badges(canvas)
    assert _collisions(painted) == [], (
        f"after set_zoom(1.0), painted badges overlap: {_collisions(painted)}"
    )
    _assert_painted(painted, AT_ZOOM_1, "after set_zoom(1.0)")

    canvas.set_zoom(2.0)
    _assert_painted(_painted_badges(canvas), AT_ZOOM_2, "after set_zoom(2.0) again")


def test_the_canvas_paints_a_colliding_single_point_region_at_its_bounding_rect_centre(
    qtbot,
) -> None:  # type: ignore[no-untyped-def]
    # Amendment 1, worked out by hand in test_badges.py:
    #   0: x 60..100, y 100..130 (R 100, T 100) -> NOMINAL (113, 87); zoom 2 (213, 187)
    #   1: the single point (100, 100), stored as a closed ring of 5 - a ring
    #      OrderedRegion (like RawRegion) accepts. Its nominal (113, 87) is taken,
    #      so no walk: the bounding-rect centre (100, 100); at zoom 2, (200, 200).
    link = _link()
    regions = [
        link.OrderedRegion(region_id=0, polygon=_ring(60, 100, 100, 130)),
        link.OrderedRegion(region_id=1, polygon=((100, 100),) * 5),
    ]
    canvas = _canvas(qtbot)
    canvas.set_zoom(1.0)
    canvas.set_regions(regions)  # must not raise
    _assert_painted(
        _painted_badges(canvas), {0: (113.0, 87.0), 1: (100.0, 100.0)}, "degenerate at zoom 1"
    )

    canvas.set_zoom(2.0)  # re-places; must not raise
    _assert_painted(
        _painted_badges(canvas), {0: (213.0, 187.0), 1: (200.0, 200.0)}, "degenerate at zoom 2"
    )


# =============================================================================
# The painter's new surface (Contract): paint_marker(badge_centre=...) and
# BubbleMarker.set_badge_centre
# =============================================================================


def _square() -> Any:
    # R 180, T 20 -> nominal badge (193, 7) at scale 1.
    return _link().OrderedRegion(region_id=6, polygon=_ring(20, 20, 180, 180))


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0])
def test_paint_marker_centres_the_badge_on_badge_centre_at_18_screen_px(qapp, scale: float) -> None:  # type: ignore[no-untyped-def]
    markers = _markers()
    region = _square()
    recorder = _capture(
        lambda p: markers.paint_marker(
            p, region, markers.MarkerState.IDLE, badge_centre=QPointF(50.0, 60.0)
        ),
        QTransform.fromScale(scale, scale),
    )
    assert len(recorder.circles) == 1
    centre, width, height = recorder.circles[0]
    # Scene (50, 60) under scale s is device (50 s, 60 s); the circle stays 18 x 18.
    assert centre == pytest.approx((50.0 * scale, 60.0 * scale), abs=ABS)
    assert (width, height) == pytest.approx((SIZE, SIZE), abs=ABS)
    # The ordinal is drawn in the same circle, not left behind at the nominal spot.
    assert recorder.text_centres == [pytest.approx(centre, abs=ABS)]


@pytest.mark.parametrize("state_name", ["IDLE", "HOVER", "SELECTED"])
def test_paint_marker_with_no_badge_centre_is_mt016s_nominal_badge(qapp, state_name: str) -> None:  # type: ignore[no-untyped-def]
    markers = _markers()
    region = _square()
    state = markers.MarkerState[state_name]
    explicit = _capture(
        lambda p: markers.paint_marker(p, region, state, badge_centre=None),
        QTransform.fromScale(2.0, 2.0),
    )
    implicit = _capture(
        lambda p: markers.paint_marker(p, region, state), QTransform.fromScale(2.0, 2.0)
    )
    # Nominal at scale 2: (360 + 13, 40 - 13) = (373, 27).
    assert explicit.circles == implicit.circles
    assert [c for c, _, _ in explicit.circles] == [pytest.approx((373.0, 27.0), abs=ABS)]


def test_a_marker_paints_its_badge_at_the_centre_it_was_given_and_back_at_nominal_on_none(
    qapp,  # type: ignore[no-untyped-def]
) -> None:
    markers = _markers()
    marker = markers.BubbleMarker(_square())

    def paint(painter: QPainter) -> None:
        marker.paint(painter, QStyleOptionGraphicsItem(), None)

    marker.set_badge_centre(QPointF(100.0, 40.0))
    moved = _capture(paint, QTransform.fromScale(2.0, 2.0))
    assert [c for c, _, _ in moved.circles] == [pytest.approx((200.0, 80.0), abs=ABS)]

    marker.set_badge_centre(None)
    nominal = _capture(paint, QTransform.fromScale(2.0, 2.0))
    assert [c for c, _, _ in nominal.circles] == [pytest.approx((373.0, 27.0), abs=ABS)]
