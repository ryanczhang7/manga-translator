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
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeyEvent, QMouseEvent, QPen, QPixmap, QTransform
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
from mangatl.ui.link import (
    SAME_POINT_PX,
    SELECTION_MARGIN_PX,
    LinkState,
    OrderedRegion,
    hit_test,
    pan_to_contain,
)
from mangatl.ui.markers import BubbleMarker, MarkerState

__all__ = [
    "EMPTY",
    "EMPTY_ACTION",
    "EMPTY_TITLE",
    "FAILED",
    "FAILED_MESSAGE",
    "LOADED",
    "PageCanvas",
]

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
        self._press_pos: QPoint | None = None
        self._last_click: QPoint | None = None
        # Hover needs moves with no button held; offscreen and on a real
        # pointer alike, those reach the viewport only with tracking on.
        self.viewport().setMouseTracking(True)
        self._state = EMPTY
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

    def zoom(self) -> float:
        """The current zoom factor, 1.0 being one image pixel per screen pixel."""
        return self.transform().m11()

    def set_zoom(self, factor: float) -> None:
        """Set an absolute, uniform zoom, clamped to [ZOOM_MIN, ZOOM_MAX]."""
        clamped = min(max(factor, self.ZOOM_MIN), self.ZOOM_MAX)
        self.setTransform(QTransform.fromScale(clamped, clamped))

    # --- The link (MT-016) ------------------------------------------------------

    def set_regions(self, regions: Sequence[OrderedRegion]) -> None:
        """One marker per region, in region_id order, styled from the current state."""
        for marker in self.markers:
            self._scene.removeItem(marker)
        self._regions = sorted(regions, key=lambda region: region.region_id)
        self.markers = [BubbleMarker(region) for region in self._regions]
        for marker in self.markers:
            self._scene.addItem(marker)
        self._last_click = None
        self._restyle()

    def set_link_state(self, state: LinkState) -> None:
        """Restyle the markers from `state`. Never moves the viewport."""
        self._link_state = replace(state)
        self._restyle()

    def reveal(self, region_id: int) -> None:
        """Pan by the minimum that brings the region in with SELECTION_MARGIN_PX.

        Nothing at all is touched when it is already entirely visible, and the
        transform is never touched: selection does not zoom (§4.5). Deltas are
        whole pixels, because scroll values are.
        """
        region = next((r for r in self._regions if r.region_id == region_id), None)
        if region is None:
            return
        mapped = self.mapFromScene(region.bounds()).boundingRect()
        delta = pan_to_contain(QRectF(self.viewport().rect()), QRectF(mapped), SELECTION_MARGIN_PX)
        if delta is None:
            return
        horizontal, vertical = self.horizontalScrollBar(), self.verticalScrollBar()
        horizontal.setValue(horizontal.value() - round(delta.x()))
        vertical.setValue(vertical.value() - round(delta.y()))

    def _restyle(self) -> None:
        selected = self._link_state.selected_region_id
        hovered = self._link_state.hovered_region_id
        for marker in self.markers:
            region_id = marker.region.region_id
            if region_id == selected:
                state = MarkerState.SELECTED  # hover never changes the selected look (§4.4)
            elif region_id == hovered:
                state = MarkerState.HOVER
            else:
                state = MarkerState.IDLE
            marker.set_appearance(state, dimmed=selected is not None and region_id != selected)

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
