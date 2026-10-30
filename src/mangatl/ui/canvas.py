"""The page canvas: the art, as large as the window allows, on its mat.

`components.md` §3. The canvas is a `QGraphicsView` whose background brush is
the `color.canvas.surround` mat in every state, and which draws a loaded page
with a 1 px cosmetic `color.canvas.page-edge` outline round the pixmap. The mat
is *lighter* than the chrome on purpose (`tokens.md` §4, simultaneous
contrast); it is not a bug to be tidied into the Photoshop convention.

Three states are built here - EMPTY (no chapter), LOADED and FAILED (the page's
bytes did not decode). The fourth design state, *loading*, is not observable
while decode is synchronous and arrives with the story that makes it
asynchronous (MT-015 PO-4).

Every colour comes from `tokens_gen`; MT-015 AC-7 scans this file for literals.

MT-016 adds the canvas half of the bubble <-> line link (`components.md` §4):
one `BubbleMarker` per region, restyled from `LinkState` and never moving the
viewport; a click (press and release within `SAME_POINT_PX`, so a drag pans
instead) hit-tests every region at once; hover is reported from mouse moves;
`reveal` pans by the minimum that brings a region in and **never zooms**.

MT-050 adds Up/Down/Home/End (§4.7): unmodified, they are reported as a
selection step and never reach `QGraphicsView`, whose default handling would
scroll the view on top of `reveal`'s minimum pan (§4.5).

MT-051 places the ordinal badges so that no two overlap (§4.2): `set_regions`
and `set_zoom` re-place them with `badges.place_badges` at the current zoom,
because a badge is a constant size on screen. Panning never re-places.

MT-052 adds the off-screen indicator (§4.6): one `OffscreenIndicator`, a child
widget of the viewport, shown while the selected region is not fully visible
and re-pinned after everything that moves the view - including every scroll,
because a scroll carries the viewport's child widgets with it. Clicking it or
`Ctrl+9` runs `bring_into_view`: centre the region, zooming out only as far as
it must to fit the 24 px inset, never in (Q1).

MT-073 adds the boundary MT-015 deferred and its High Contrast deltas
(`components.md` §3 and §10.3): `paint_boundary` paints, last and in viewport
pixels, a `color.canvas.frame` line - or, while the canvas has keyboard focus,
a `focus.width` ring with its `focus.halo` - over the outermost pixels of the
viewport, never moving its contents. The viewport is repainted whole after a
scroll, a focus change and a mode change, because a band painted in viewport
space would otherwise be carried inside by the scroll's pixel shift, or left
stale. `set_high_contrast` changes exactly three things (§10.3): dimming stops,
the frame becomes `WindowText` at 2 px, and the ring `WindowText` on a `Window`
halo - frame and ring falling back to their authored values when they fail 3:1
against the mat (`theme.mat_safe`, A-15.9). The markers are untouched (§7).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFocusEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from mangatl.ui import tokens_gen
from mangatl.ui.badges import place_badges
from mangatl.ui.link import (
    SAME_POINT_PX,
    SELECTION_MARGIN_PX,
    LinkState,
    OrderedRegion,
    hit_test,
    pan_to_contain,
)
from mangatl.ui.markers import BubbleMarker, MarkerState
from mangatl.ui.offscreen import INDICATOR_TARGET_PX, OffscreenIndicator, indicator_edge
from mangatl.ui.theme import MissingPaletteRole, mat_safe

__all__ = [
    "EMPTY",
    "EMPTY_ACTION",
    "EMPTY_TITLE",
    "FAILED",
    "FAILED_MESSAGE",
    "LOADED",
    "PageCanvas",
    "paint_boundary",
]

#: The two palette roles the canvas reads under High Contrast (§10.3), each
#: with the first token that takes it there - named when a role is missing.
_TEXT_ROLE = "WindowText"
_GROUND_ROLE = "Window"
_CANVAS_ROLES = {_TEXT_ROLE: "color.canvas.frame", _GROUND_ROLE: "color.focus.halo"}

EMPTY = "empty"
LOADED = "loaded"
FAILED = "failed"

EMPTY_TITLE = "No chapter loaded"
EMPTY_ACTION = "Open a folder"
FAILED_MESSAGE = "This page could not be opened. It will be copied to the output folder unchanged."

#: Unmodified navigation keys on the canvas and the selection step each asks for.
#: `Qt.Key` is an IntEnum and `QKeyEvent.key()` an int, so the int keys look it up.
_SELECTION_STEPS: dict[int, str] = {
    Qt.Key.Key_Up: "previous",
    Qt.Key.Key_Down: "next",
    Qt.Key.Key_Home: "first",
    Qt.Key.Key_End: "last",
}


def paint_boundary(
    painter: QPainter,
    rect: QRect,
    *,
    focused: bool,
    frame_width: int,
    frame_colour: str,
    ring_colour: str,
    halo_colour: str,
) -> None:
    """Paint the viewport's boundary band over the outermost pixels of `rect`.

    Not focused: the outermost `frame_width` px are `frame_colour`. Focused:
    the outermost `focus.halo` px are `halo_colour` and the `focus.width` px
    just inside them `ring_colour` - the frame covered, not drawn beside it
    (`components.md` §3, `tokens.md` §7). Nothing outside `rect` and nothing
    inside the band is touched.
    """
    if focused:
        halo = tokens_gen.FOCUS_HALO
        _paint_band(painter, rect, halo, halo_colour)
        inside_halo = rect.adjusted(halo, halo, -halo, -halo)
        _paint_band(painter, inside_halo, tokens_gen.FOCUS_WIDTH, ring_colour)
    else:
        _paint_band(painter, rect, frame_width, frame_colour)


def _paint_band(painter: QPainter, rect: QRect, width: int, colour: str) -> None:
    """Fill the outermost `width` px of `rect` on every side with `colour`."""
    if width <= 0:
        return
    fill = QColor(colour)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    painter.fillRect(QRect(x, y, w, width), fill)
    painter.fillRect(QRect(x, y + h - width, w, width), fill)
    painter.fillRect(QRect(x, y + width, width, h - 2 * width), fill)
    painter.fillRect(QRect(x + w - width, y + width, width, h - 2 * width), fill)


class PageCanvas(QGraphicsView):
    """The page, zoomable and pannable, or the message saying why there is none."""

    #: `components.md` §3: "Zoom range 10%-800%".
    ZOOM_MIN: float = 0.10
    ZOOM_MAX: float = 8.0

    #: A click on a region (after hit_test): press and release within SAME_POINT_PX.
    regionClicked = Signal(int)
    #: The region under the pointer, or None (hover, §4.4).
    regionHovered = Signal(object)
    #: Enter/Return on the canvas: "take me to this bubble's editor" (§4.7).
    editRequested = Signal()
    #: Up/Down/Home/End on the canvas: "move the selection" (§4.7). The canvas
    #: does not own the selection (§4.1); it reports the step and nothing else:
    #: "previous", "next", "first" or "last".
    selectionStepRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageCanvas")
        self.setAccessibleName("Page canvas")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setBackgroundBrush(QBrush(QColor(tokens_gen.COLOR_CANVAS_SURROUND)))
        # The canvas pans; it does not show scroll bars (layout.md).
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        self.message = QLabel(self.viewport())
        self.message.setObjectName("canvasMessage")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        overlay = QVBoxLayout(self.viewport())
        overlay.addWidget(self.message)

        self.page_item: QGraphicsPixmapItem | None = None
        self.page_edge_item: QGraphicsRectItem | None = None
        self.markers: list[BubbleMarker] = []
        self._regions: list[OrderedRegion] = []
        self._link_state = LinkState()
        self._high_contrast = False
        #: Under High Contrast, the palette's `WindowText` and `Window`; else empty.
        self._palette: dict[str, str] = {}
        self._press_pos: QPoint | None = None
        self._last_click: QPoint | None = None
        # Hover needs moves with no button held; offscreen and on a real
        # pointer alike, those reach the viewport only with tracking on.
        self.viewport().setMouseTracking(True)
        self._state = EMPTY

        # Not in the viewport's layout (which manages `message` only), and
        # hidden explicitly, or it would appear when the canvas is shown.
        self.offscreen_indicator = OffscreenIndicator(self.viewport())
        self.offscreen_indicator.hide()
        self.offscreen_indicator.clicked.connect(self._on_indicator_clicked)
        # Entering a viewport child sends the viewport no Leave (MT-052 B6,
        # measured), so MT-049's clear does not run: the canvas clears hover here.
        self.offscreen_indicator.installEventFilter(self)
        self.set_page(None)

    def state(self) -> str:
        """One of EMPTY, LOADED or FAILED."""
        return self._state

    def set_page(self, pixmap: QPixmap | None, error: str | None = None) -> None:
        """Show `pixmap`; or, with no pixmap, the failure naming `error`, else empty.

        `error` is the page's filename. Whatever was on the canvas before is
        removed first, so a failed page never leaves the previous one showing.
        """
        self._scene.clear()  # deletes the markers too
        self.page_item = None
        self.page_edge_item = None
        self.markers = []
        self._regions = []
        self._last_click = None
        if pixmap is not None:
            self._show_pixmap(pixmap)
        elif error is not None:
            self._show_message(FAILED, f"{error}\n{FAILED_MESSAGE}", f"{error}: {FAILED_MESSAGE}")
        else:
            self._show_message(EMPTY, f"{EMPTY_TITLE}\n{EMPTY_ACTION}", EMPTY_TITLE)
        self._update_indicator()

    def zoom(self) -> float:
        """The current zoom factor, 1.0 being one image pixel per screen pixel."""
        return self.transform().m11()

    def set_zoom(self, factor: float) -> None:
        """Set an absolute, uniform zoom, clamped to [ZOOM_MIN, ZOOM_MAX]."""
        clamped = min(max(factor, self.ZOOM_MIN), self.ZOOM_MAX)
        self.setTransform(QTransform.fromScale(clamped, clamped))
        self._place_badges()
        self._update_indicator()

    # --- The boundary and High Contrast (MT-073) --------------------------------

    def set_high_contrast(self, enabled: bool, palette: Mapping[str, str]) -> None:
        """Follow the contrast theme: the frame, the ring and dimming, nothing else.

        Off ignores `palette`. On reads its `WindowText` and `Window`, and a
        palette without either raises `MissingPaletteRole` (A-15.3) before
        anything changes. The transform, scroll bars and link state are untouched.
        """
        if enabled:
            for role, token in _CANVAS_ROLES.items():
                if role not in palette:
                    raise MissingPaletteRole(token, role)
            self._palette = {role: palette[role] for role in _CANVAS_ROLES}
        else:
            self._palette = {}
        self._high_contrast = enabled
        self.viewport().update()
        self._restyle()

    @property
    def high_contrast(self) -> bool:
        """Whether the canvas is showing the High Contrast deltas."""
        return self._high_contrast

    @property
    def frame_width(self) -> int:
        """The frame's width: a hairline, or `border.width.emphasis` under High Contrast."""
        if self._high_contrast:
            return tokens_gen.BORDER_WIDTH_EMPHASIS
        return tokens_gen.BORDER_WIDTH_HAIRLINE

    @property
    def frame_colour(self) -> str:
        """`color.canvas.frame`, or a mat-safe `WindowText` under High Contrast."""
        authored = tokens_gen.COLOR_CANVAS_FRAME
        if self._high_contrast:
            return mat_safe(self._palette[_TEXT_ROLE], authored)
        return authored

    @property
    def ring_colour(self) -> str:
        """`color.focus.ring`, or a mat-safe `WindowText` under High Contrast."""
        authored = tokens_gen.COLOR_FOCUS_RING
        if self._high_contrast:
            return mat_safe(self._palette[_TEXT_ROLE], authored)
        return authored

    @property
    def halo_colour(self) -> str:
        """`color.focus.halo`, or the palette's `Window` (no mat check, §10.3)."""
        if self._high_contrast:
            return self._palette[_GROUND_ROLE]
        return tokens_gen.COLOR_FOCUS_HALO

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        viewport = self.viewport()
        painter = QPainter(viewport)
        try:
            paint_boundary(
                painter,
                viewport.rect(),
                focused=self.hasFocus(),
                frame_width=self.frame_width,
                frame_colour=self.frame_colour,
                ring_colour=self.ring_colour,
                halo_colour=self.halo_colour,
            )
        finally:
            painter.end()

    # The viewport is opaque, so the canvas's own focus repaint does not reach
    # it; without these the band would keep the previous focus state.
    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.viewport().update()  # the ring replaces the frame

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.viewport().update()  # the frame replaces the ring

    # --- The link (MT-016)------------------------------------------------------

    def set_regions(self, regions: Sequence[OrderedRegion]) -> None:
        """One marker per region, in region_id order, styled from the current state."""
        for marker in self.markers:
            self._scene.removeItem(marker)
        self._regions = sorted(regions, key=lambda region: region.region_id)
        self.markers = [BubbleMarker(region) for region in self._regions]
        for marker in self.markers:
            self._scene.addItem(marker)
        self._last_click = None
        self._place_badges()
        self._restyle()
        self._update_indicator()

    def _place_badges(self) -> None:
        """Re-place every badge at the current zoom (MT-051, §4.2).

        Badges are a constant size on screen, so they collide in zoomed-scene
        units and are placed there; each marker gets its centre back in scene
        coordinates. Only a zoom change or new regions re-place: panning never does.
        """
        zoom = self.zoom()
        placed = place_badges(
            ((region.region_id, region.polygon) for region in self._regions),
            zoom=zoom,
            size=tokens_gen.OVERLAY_BADGE_SIZE,
            gap=tokens_gen.OVERLAY_BADGE_GAP,
        )
        for marker in self.markers:
            x, y = placed[marker.region.region_id].centre
            marker.set_badge_centre(QPointF(x / zoom, y / zoom))

    def set_link_state(self, state: LinkState) -> None:
        """Restyle the markers from `state`. Never moves the viewport."""
        self._link_state = replace(state)
        self._restyle()
        self._update_indicator()

    def reveal(self, region_id: int) -> None:
        """Pan by the minimum that brings the region in with SELECTION_MARGIN_PX.

        Nothing at all is touched when it is already entirely visible, and the
        transform is never touched: selection does not zoom (§4.5). Deltas are
        whole pixels, because scroll values are.
        """
        region = self._region(region_id)
        if region is None:
            return
        mapped = self.mapFromScene(region.bounds()).boundingRect()
        delta = pan_to_contain(QRectF(self.viewport().rect()), QRectF(mapped), SELECTION_MARGIN_PX)
        if delta is None:
            return
        horizontal, vertical = self.horizontalScrollBar(), self.verticalScrollBar()
        horizontal.setValue(horizontal.value() - round(delta.x()))
        vertical.setValue(vertical.value() - round(delta.y()))

    # --- The off-screen indicator (MT-052) --------------------------------------

    def bring_into_view(self, region_id: int) -> None:
        """Centre the region; zoom out only if it cannot fit the 24 px inset (Q1).

        The zoom is never increased, and the selection is never touched: this is
        what the indicator's click and `Ctrl+9` do. Unknown ids do nothing.
        """
        region = self._region(region_id)
        if region is None:
            return
        bounds = region.bounds()
        mapped = QRectF(self.mapFromScene(bounds).boundingRect())
        viewport = self.viewport()
        room_w = viewport.width() - 2 * SELECTION_MARGIN_PX
        room_h = viewport.height() - 2 * SELECTION_MARGIN_PX
        if not (mapped.width() <= room_w and mapped.height() <= room_h):
            target = self.zoom()
            if bounds.width() > 0:
                target = min(target, room_w / bounds.width())
            if bounds.height() > 0:
                target = min(target, room_h / bounds.height())
            self.set_zoom(target)
        self.centerOn(bounds.center())
        self._update_indicator()

    def _region(self, region_id: int | None) -> OrderedRegion | None:
        return next((r for r in self._regions if r.region_id == region_id), None)

    def _update_indicator(self) -> None:
        """Show and pin the indicator while the selected region is not fully visible."""
        indicator = self.offscreen_indicator
        region = self._region(self._link_state.selected_region_id)
        placement = None
        if self._state == LOADED and region is not None:
            placement = indicator_edge(
                QRectF(self.viewport().rect()),
                QRectF(self.mapFromScene(region.bounds()).boundingRect()),
            )
        if region is None or placement is None:
            indicator.hide()
            return
        edge, centre = placement
        half = INDICATOR_TARGET_PX / 2
        indicator.set_target(region.ordinal, edge)
        indicator.move((centre - QPointF(half, half)).toPoint())
        indicator.show()
        indicator.raise_()

    def _on_indicator_clicked(self) -> None:
        selected = self._link_state.selected_region_id
        if selected is not None:
            self.bring_into_view(selected)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.offscreen_indicator and event.type() == QEvent.Type.Enter:
            self.regionHovered.emit(None)
        return super().eventFilter(watched, event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)  # moves the viewport's child widgets too
        # The scroll shifts the viewport's pixels, band included: repaint it all,
        # or a stale copy of the band is left inside the viewport (MT-073).
        self.viewport().update()
        self._update_indicator()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_indicator()

    def _restyle(self) -> None:
        selected = self._link_state.selected_region_id
        hovered = self._link_state.hovered_region_id
        for marker in self.markers:
            region_id = marker.region.region_id
            excluded = marker.region.excluded
            if region_id == selected:
                state = MarkerState.SELECTED  # hover never changes the selected look (§4.4)
            elif region_id == hovered:
                state = MarkerState.HOVER
            elif excluded:
                state = MarkerState.EXCLUDED
            else:
                state = MarkerState.IDLE
            # A removed region is always dimmed unless it is itself the
            # selection (MT-120 C-3, §4.3 "Why always dimmed"). Under High
            # Contrast dimming stops (A-15.6, §7.1); nothing else does.
            dimmed = (
                not self._high_contrast
                and region_id != selected
                and (selected is not None or excluded)
            )
            marker.set_appearance(state, dimmed=dimmed)

    def set_region_excluded(self, region_id: int, excluded: bool) -> None:
        """Mark one region removed from translation or restored, in place.

        The marker object is kept (MT-120 C-4: no rebuild); only its region
        value and its look change. The selection and the viewport do not.
        """
        for index, region in enumerate(self._regions):
            if region.region_id == region_id:
                self._regions[index] = replace(region, excluded=excluded)
        for marker in self.markers:
            if marker.region.region_id == region_id:
                marker.region = replace(marker.region, excluded=excluded)
        self._restyle()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        press, self._press_pos = self._press_pos, None
        if event.button() != Qt.MouseButton.LeftButton or press is None:
            return
        release = event.position().toPoint()
        if not _within(press, release, SAME_POINT_PX):
            return  # a drag pans; it does not select
        same_point = self._last_click is not None and _within(
            self._last_click, release, SAME_POINT_PX
        )
        self._last_click = release
        previous = self._link_state.selected_region_id if same_point else None
        hit = hit_test(self._regions, self.mapToScene(release), previous)
        if hit is not None:
            self.regionClicked.emit(hit)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        self.regionHovered.emit(
            hit_test(self._regions, self.mapToScene(event.position().toPoint()), None)
        )

    def viewportEvent(self, event: QEvent) -> bool:
        """Clear hover when the pointer leaves the viewport (MT-049).

        `components.md` §4.4: hover "never persists after the pointer leaves".
        Moves alone cannot say so when the pointer exits straight off a region
        at the viewport edge. The clear is synchronous, so it lands before any
        row's Enter on the way in. Nothing else happens on Leave: no reveal.
        """
        if event.type() == QEvent.Type.Leave:
            self.regionHovered.emit(None)
        return super().viewportEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.editRequested.emit()
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_9
            and event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            == Qt.KeyboardModifier.ControlModifier
        ):
            # "Bring the selected bubble into view" (A-07); never reaches QGraphicsView.
            selected = self._link_state.selected_region_id
            if selected is not None:
                self.bring_into_view(selected)
            event.accept()
            return
        step = _SELECTION_STEPS.get(event.key())
        unmodified = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier == (
            Qt.KeyboardModifier.NoModifier
        )
        if step is not None and unmodified:
            # Never reaches QGraphicsView, which would scroll the view (MT-050 AC-5).
            self.selectionStepRequested.emit(step)
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_pixmap(self, pixmap: QPixmap) -> None:
        self.page_item = self._scene.addPixmap(pixmap)
        bounds = QRectF(pixmap.rect())
        pen = QPen(QColor(tokens_gen.COLOR_CANVAS_PAGE_EDGE))
        pen.setWidth(1)
        pen.setCosmetic(True)
        self.page_edge_item = self._scene.addRect(bounds, pen)
        self.page_edge_item.setZValue(1)
        self._scene.setSceneRect(bounds)
        self._state = LOADED
        self.message.hide()

    def _show_message(self, state: str, text: str, accessible_name: str) -> None:
        self._state = state
        self.message.setText(text)
        self.message.setAccessibleName(accessible_name)
        self.message.show()


def _within(a: QPoint, b: QPoint, pixels: int) -> bool:
    """Whether two viewport points are within `pixels` of each other."""
    return math.hypot(a.x() - b.x(), a.y() - b.y()) <= pixels
