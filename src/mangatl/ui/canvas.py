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
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap, QTransform
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


class PageCanvas(QGraphicsView):
    """The page, zoomable and pannable, or the message saying why there is none."""

    #: `components.md` §3: "Zoom range 10%-800%".
    ZOOM_MIN: float = 0.10
    ZOOM_MAX: float = 8.0

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
        self._scene.clear()
        self.page_item = None
        self.page_edge_item = None
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
