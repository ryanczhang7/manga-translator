"""The off-screen indicator: where the selected bubble went, and a way back.

`components.md` §4.6 (normative). When the selected region is not fully visible,
a chevron plus the region's ordinal is pinned to the viewport edge nearest the
region's centre, drawn in `overlay.bubble.selected` **with the halo** (A-06) at
the badge size. There is at most one, and only for the selected region; the
canvas owns it (`PageCanvas.offscreen_indicator`) and decides when it shows.

It is a `QWidget`, not a graphics item, because it needs an accessible name
(A-08) and graphics items are invisible to UI Automation (A-13.1). The widget is
`INDICATOR_TARGET_PX` square - A-05's minimum pointer target - and paints an
18 px badge inside it, with the chevron outboard of the badge.

"Fully visible" is the viewport with **no** margin (MT-052 Q4): a region inside
the 24 px selection margin but inside the viewport shows no indicator.

Every colour comes from `tokens_gen`; MT-015 AC-7 scans this file for literals.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import QAbstractButton, QWidget

from mangatl.ui import tokens_gen
from mangatl.ui.markers import MarkerState, overlay_pen, paint_badge

__all__ = [
    "INDICATOR_TARGET_PX",
    "Edge",
    "OffscreenIndicator",
    "badge_rect",
    "chevron_points",
    "indicator_edge",
    "paint_indicator",
]

#: `accessibility.md` A-05: the minimum pointer target.
INDICATOR_TARGET_PX: int = 28

_HALF = INDICATOR_TARGET_PX / 2
#: How far the chevron's arms and apex sit outboard of the widget centre, and
#: how far its arms spread; and how far the badge is shifted inboard.
_ARM_OUT, _APEX_OUT, _ARM_SPREAD, _BADGE_IN = 7.0, 11.0, 5.0, 3.0


class Edge(Enum):
    """A viewport edge. Declaration order is the tie order (MT-052 B3)."""

    TOP = "top"
    RIGHT = "right"
    BOTTOM = "bottom"
    LEFT = "left"


#: The outward unit vector through each edge.
_OUTWARD: dict[Edge, tuple[float, float]] = {
    Edge.TOP: (0.0, -1.0),
    Edge.RIGHT: (1.0, 0.0),
    Edge.BOTTOM: (0.0, 1.0),
    Edge.LEFT: (-1.0, 0.0),
}


def indicator_edge(view_rect: QRectF, region_rect: QRectF) -> tuple[Edge, QPointF] | None:
    """The edge and indicator centre for `region_rect`, or None if fully visible.

    Both rects are in viewport pixels. Fully visible means entirely inside
    `view_rect` with no margin - `pan_to_contain`'s `None` predicate. Otherwise
    the edge is the one the region's centre is nearest by signed distance (a
    centre beyond an edge is negative to it), ties going TOP, RIGHT, BOTTOM,
    LEFT; the centre is on that edge, clamped half a target in from the corners.
    """
    if (
        region_rect.left() >= view_rect.left()
        and region_rect.top() >= view_rect.top()
        and region_rect.right() <= view_rect.right()
        and region_rect.bottom() <= view_rect.bottom()
    ):
        return None
    c = region_rect.center()
    distances = {
        Edge.TOP: c.y() - view_rect.top(),
        Edge.RIGHT: view_rect.right() - c.x(),
        Edge.BOTTOM: view_rect.bottom() - c.y(),
        Edge.LEFT: c.x() - view_rect.left(),
    }
    edge = min(Edge, key=lambda e: distances[e])  # min keeps the first of equals
    x = _clamp(c.x(), view_rect.left() + _HALF, view_rect.right() - _HALF)
    y = _clamp(c.y(), view_rect.top() + _HALF, view_rect.bottom() - _HALF)
    if edge is Edge.TOP:
        y = view_rect.top() + _HALF
    elif edge is Edge.BOTTOM:
        y = view_rect.bottom() - _HALF
    elif edge is Edge.RIGHT:
        x = view_rect.right() - _HALF
    else:
        x = view_rect.left() + _HALF
    return edge, QPointF(x, y)


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _along(edge: Edge, out: float, side: float) -> QPointF:
    """The widget centre moved `out` along the outward vector and `side` across it."""
    ux, uy = _OUTWARD[edge]
    vx, vy = -uy, ux
    return QPointF(_HALF + out * ux + side * vx, _HALF + out * uy + side * vy)


def chevron_points(edge: Edge) -> tuple[QPointF, QPointF, QPointF]:
    """Arm, apex, arm in widget coordinates; the apex points out through `edge`."""
    return (
        _along(edge, _ARM_OUT, _ARM_SPREAD),
        _along(edge, _APEX_OUT, 0.0),
        _along(edge, _ARM_OUT, -_ARM_SPREAD),
    )


def badge_rect(edge: Edge) -> QRectF:
    """The `overlay.badge.size` square, shifted inboard of the widget centre."""
    size = tokens_gen.OVERLAY_BADGE_SIZE
    centre = _along(edge, -_BADGE_IN, 0.0)
    return QRectF(centre.x() - size / 2, centre.y() - size / 2, size, size)


def paint_indicator(painter: QPainter, ordinal: int, edge: Edge) -> None:
    """Halo, then core, on the open chevron; then a selected marker's badge."""
    arm, apex, other_arm = chevron_points(edge)
    chevron = QPainterPath(arm)
    chevron.lineTo(apex)
    chevron.lineTo(other_arm)
    core_width = tokens_gen.OVERLAY_STROKE_CORE_SELECTED
    painter.save()
    try:
        painter.strokePath(
            chevron,
            overlay_pen(tokens_gen.OVERLAY_HALO, core_width + 2 * tokens_gen.OVERLAY_STROKE_HALO),
        )
        painter.strokePath(chevron, overlay_pen(tokens_gen.OVERLAY_BUBBLE_SELECTED, core_width))
        paint_badge(painter, badge_rect(edge), ordinal, MarkerState.SELECTED)
    finally:
        painter.restore()


class OffscreenIndicator(QAbstractButton):
    """The chevron-and-ordinal button pinned to the viewport edge (§4.6).

    Not a focus stop (§4.7; the keyboard path is `Ctrl+9`), no mouse tracking
    and no hover look. No mouse event reaches the widget beneath it (AC-9).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("offscreenIndicator")
        self.setFixedSize(INDICATOR_TARGET_PX, INDICATOR_TARGET_PX)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # An ignored mouse event (a button-less move, say) would otherwise
        # propagate to the viewport and hover the region under the indicator.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        self._ordinal: int | None = None
        self._edge: Edge | None = None

    def set_target(self, ordinal: int, edge: Edge) -> None:
        """Point at the region numbered `ordinal`, through `edge`, and name it (A-08)."""
        self._ordinal = ordinal
        self._edge = edge
        self.setAccessibleName(f"Bubble {ordinal} is off screen. Activate to show it.")
        self.update()

    def ordinal(self) -> int | None:
        return self._ordinal

    def edge(self) -> Edge | None:
        return self._edge

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._ordinal is None or self._edge is None:
            return
        painter = QPainter(self)
        try:
            # Looked up as a module global at paint time (AC-6 captures it).
            paint_indicator(painter, self._ordinal, self._edge)
        finally:
            painter.end()
