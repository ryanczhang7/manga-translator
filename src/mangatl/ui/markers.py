"""How a bubble is marked on the art: `BubbleMarker` and `paint_marker`.

`components.md` §4.3. **Every marker is stroked twice** - `overlay.halo`, then
the state's core - because no single flat colour clears 3:1 against both pure
black and pure white art (`tokens.md` §5, `accessibility.md` A-06). The halo is
the mechanism, not decoration; MT-016 AC-8 asserts it on captured paint calls.

Pens are cosmetic, so the outline is the same width on screen at every zoom.
The ordinal badge is drawn after both outline strokes, at the region's
top-right (§4.2), at a constant on-screen size for the same reason. Badge
collision avoidance (§4.2) is MT-051's: `mangatl.ui.badges` places the badges,
the canvas hands each marker its centre (`BubbleMarker.set_badge_centre`), and
`paint_marker` draws the circle there; with no centre it is MT-016's nominal.

The `overlay.fill.*` tokens are `#RRGGBBAA`; Qt reads an 8-digit string as
`#AARRGGBB` (MT-025 PO-7), so every token goes through `rgba_colour`.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from mangatl.ui import tokens_gen
from mangatl.ui.link import OrderedRegion

__all__ = [
    "BubbleMarker",
    "MarkerState",
    "overlay_pen",
    "paint_badge",
    "paint_marker",
    "rgba_colour",
]


class MarkerState(Enum):
    """The marker states this story builds (§4.3); error and edited come later."""

    IDLE = "idle"
    HOVER = "hover"
    SELECTED = "selected"


#: state -> (core colour, core width, fill token or None). §4.3, read out.
_STYLE: dict[MarkerState, tuple[str, int, str | None]] = {
    MarkerState.IDLE: (tokens_gen.OVERLAY_BUBBLE_IDLE, tokens_gen.OVERLAY_STROKE_CORE_IDLE, None),
    MarkerState.HOVER: (
        tokens_gen.OVERLAY_BUBBLE_HOVER,
        tokens_gen.OVERLAY_STROKE_CORE_HOVER,
        tokens_gen.OVERLAY_FILL_HOVER,
    ),
    MarkerState.SELECTED: (
        tokens_gen.OVERLAY_BUBBLE_SELECTED,
        tokens_gen.OVERLAY_STROKE_CORE_SELECTED,
        tokens_gen.OVERLAY_FILL_SELECTED,
    ),
}

#: `PageCanvas.ZOOM_MIN`. The outline and the badge are constant in SCREEN
#: pixels, so in scene units they are largest at the smallest zoom, and the
#: item's bounding rect has to cover that.
_SMALLEST_ZOOM = 0.10
_SCREEN_PAD = (
    tokens_gen.OVERLAY_BADGE_GAP
    + tokens_gen.OVERLAY_BADGE_SIZE
    + tokens_gen.OVERLAY_STROKE_CORE_SELECTED
    + 2 * tokens_gen.OVERLAY_STROKE_HALO
)


def rgba_colour(token: str) -> QColor:
    """A `#RRGGBB` or `#RRGGBBAA` token (tokens.toml's order) as a QColor."""
    colour = QColor(token[:7])
    if len(token) == 9:
        colour.setAlpha(int(token[7:9], 16))
    return colour


def overlay_pen(token: str, width: int) -> QPen:
    """A cosmetic, round-joined pen of `width` screen px in the colour `token`."""
    pen = QPen(rgba_colour(token))
    pen.setWidthF(float(width))
    pen.setCosmetic(True)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def paint_marker(
    painter: QPainter,
    region: OrderedRegion,
    state: MarkerState,
    *,
    badge_centre: QPointF | None = None,
) -> None:
    """Fill, halo, core, badge - in that order, in scene coordinates.

    `badge_centre` (scene coordinates) is where the badge was placed (MT-051);
    None draws it at MT-016's nominal position off the top-right corner.
    """
    core_colour, core_width, fill = _STYLE[state]
    path = QPainterPath()
    path.addPolygon(region.qpolygon())

    if fill is not None:
        painter.fillPath(path, QBrush(rgba_colour(fill)))
    painter.strokePath(
        path, overlay_pen(tokens_gen.OVERLAY_HALO, core_width + 2 * tokens_gen.OVERLAY_STROKE_HALO)
    )
    painter.strokePath(path, overlay_pen(core_colour, core_width))
    _paint_badge(painter, region, state, badge_centre)


def _paint_badge(
    painter: QPainter, region: OrderedRegion, state: MarkerState, centre: QPointF | None
) -> None:
    """The ordinal in a circle at `centre`, or just off the top-right corner (§4.2).

    Drawn in screen pixels anchored at the centre (or the corner), so it reads
    the same at every zoom. Selected: filled `overlay.bubble.selected`,
    `color.text.on-accent` numeral. Otherwise: a halo-dark disc outlined and
    numbered in the core colour.
    """
    scale = painter.worldTransform().m11() or 1.0
    size = tokens_gen.OVERLAY_BADGE_SIZE
    gap = tokens_gen.OVERLAY_BADGE_GAP
    painter.save()
    try:
        if centre is None:
            painter.translate(region.bounds().topRight())
            circle = QRectF(gap, -gap - size, size, size)
        else:
            painter.translate(centre)
            circle = QRectF(-size / 2, -size / 2, size, size)
        painter.scale(1.0 / scale, 1.0 / scale)
        paint_badge(painter, circle, region.ordinal, state)
    finally:
        painter.restore()


def paint_badge(painter: QPainter, circle: QRectF, ordinal: int, state: MarkerState) -> None:
    """The disc and its numeral in `circle`, in the painter's current coordinates.

    Selected: filled `overlay.bubble.selected` with a halo ring and a
    `color.text.on-accent` numeral. Otherwise: a halo-dark disc outlined and
    numbered in the core colour. Leaves the painter's pen, brush and font
    changed; callers wrap it in `save`/`restore`. MT-052's off-screen indicator
    draws its badge with this, SELECTED.
    """
    core_colour = _STYLE[state][0]
    if state is MarkerState.SELECTED:
        painter.setPen(overlay_pen(tokens_gen.OVERLAY_HALO, tokens_gen.OVERLAY_STROKE_HALO))
        painter.setBrush(QBrush(rgba_colour(core_colour)))
        numeral = tokens_gen.COLOR_TEXT_ON_ACCENT
    else:
        painter.setPen(overlay_pen(core_colour, tokens_gen.BORDER_WIDTH_HAIRLINE))
        painter.setBrush(QBrush(rgba_colour(tokens_gen.OVERLAY_HALO)))
        numeral = core_colour
    painter.drawEllipse(circle)
    font = QFont(painter.font())
    font.setPixelSize(tokens_gen.TYPE_CAPTION_SIZE)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QPen(rgba_colour(numeral)))
    painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(ordinal))


class BubbleMarker(QGraphicsItem):
    """One region's marker on the canvas. Purely a view of `LinkState`."""

    def __init__(self, region: OrderedRegion) -> None:
        super().__init__()
        self.region = region
        self._state = MarkerState.IDLE
        self._badge_centre: QPointF | None = None
        # Clicks and hover are the canvas's (it hit-tests all regions at once).
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def state(self) -> MarkerState:
        return self._state

    def set_appearance(self, state: MarkerState, dimmed: bool) -> None:
        """Take `state`; drop to `overlay.dim.opacity` when `dimmed` (§4.3)."""
        self._state = state
        self.setOpacity(tokens_gen.OVERLAY_DIM_OPACITY if dimmed else 1.0)
        # Selected above hover above idle (§4.8 draw order, by tier).
        self.setZValue({MarkerState.IDLE: 2, MarkerState.HOVER: 3, MarkerState.SELECTED: 4}[state])
        self.update()

    def set_badge_centre(self, centre: QPointF | None) -> None:
        """Paint the badge centred on `centre` (scene coordinates); None: nominal.

        `boundingRect` is unchanged: a placed badge is at most gap + size screen
        px off the outline, which `_SCREEN_PAD / _SMALLEST_ZOOM` already covers.
        """
        self._badge_centre = None if centre is None else QPointF(centre)
        self.update()

    def boundingRect(self) -> QRectF:
        pad = _SCREEN_PAD / _SMALLEST_ZOOM
        return self.region.bounds().adjusted(-pad, -pad, pad, pad)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        paint_marker(painter, self.region, self._state, badge_centre=self._badge_centre)
