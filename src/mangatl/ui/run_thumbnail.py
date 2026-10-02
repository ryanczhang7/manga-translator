"""The current page of a run, with its detected regions outlined (MT-062).

`components.md` §8 `RunThumbnail`. A fixed 120 x 160 frame in the
`RunProgressPanel`'s `run-current-page` row. It knows nothing of the run: the
panel hands it a page (`show_page`) and that page's region outlines
(`set_regions`), and it draws them.

**Geometry comes from the `Page`, never from the decoded image.** The content
box is the widget inset by the 1 px hairline frame, `(1, 1, 118, 158)`; the
page's own `width x height` is scaled by `s = min(118 / width, 158 / height)`
and centred in it, so a polygon point `p` lands at `image_rect().topLeft() +
p * s`. An image that fails to decode changes none of that - the markers are
still drawn where the page would be - and only sets the accessible description.

**Markers are A-06 unchanged**: every halo stroke, then every core stroke, so a
later halo never cuts an earlier core; cosmetic pens from `overlay_pen`, so
their widths are screen pixels at any scale. Outline only - no fill, badge or
state, which would be illegible at a tenth of the page's size.

The ground and the frame come from the stylesheet rule `#run-thumbnail`
(MT-061's rule: colours by object name), drawn through `PE_Widget`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QAccessible,
    QAccessibleInterface,
    QImage,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPolygonF,
)
from PySide6.QtWidgets import QAccessibleWidget, QStyle, QStyleOption, QWidget

from mangatl.ui import tokens_gen
from mangatl.ui.markers import overlay_pen

__all__ = ["RunThumbnail"]

_WIDTH = 120
_HEIGHT = 160
_INSET = tokens_gen.BORDER_WIDTH_HAIRLINE
#: The box the page is drawn into and painting is clipped to: inside the frame.
_CONTENT = QRectF(_INSET, _INSET, _WIDTH - 2 * _INSET, _HEIGHT - 2 * _INSET)

_HALO_WIDTH = tokens_gen.OVERLAY_STROKE_CORE_IDLE + 2 * tokens_gen.OVERLAY_STROKE_HALO
_CORE_WIDTH = tokens_gen.OVERLAY_STROKE_CORE_IDLE

NO_PAGE = "No page started"
UNDECODABLE = "The page image could not be opened."


def _graphic_factory(key: str, obj: QObject) -> QAccessibleInterface | None:
    """Give every `RunThumbnail` the `Graphic` role: a `QWidget` cannot declare one."""
    if isinstance(obj, RunThumbnail):
        return QAccessibleWidget(obj, QAccessible.Role.Graphic)
    return None


_factory_installed = False


def _found(count: int) -> str:
    if count == 0:
        return "no text regions found"
    if count == 1:
        return "1 text region found"
    return f"{count} text regions found"


class RunThumbnail(QWidget):
    """The page a run is working on, its regions outlined as they are found."""

    def __init__(self, parent: QWidget | None = None) -> None:
        global _factory_installed
        if not _factory_installed:
            QAccessible.installFactory(_graphic_factory)
            _factory_installed = True
        super().__init__(parent)
        self.setObjectName("run-thumbnail")
        self.setFixedSize(_WIDTH, _HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._ordinal: int | None = None
        self._image: QImage | None = None
        self._rect = QRectF(_CONTENT)
        self._scale = 1.0
        self._polygons: tuple[tuple[tuple[int, int], ...], ...] = ()
        self.setAccessibleName(NO_PAGE)
        self.setAccessibleDescription("")

    def show_page(self, ordinal: int, image_path: Path, width: int, height: int) -> None:
        """Show page `ordinal` (`width x height` page pixels) with no markers."""
        image = QImage(str(image_path))
        self._image = None if image.isNull() else image
        self._ordinal = ordinal
        self._scale = min(_CONTENT.width() / width, _CONTENT.height() / height)
        drawn_w, drawn_h = width * self._scale, height * self._scale
        self._rect = QRectF(
            _CONTENT.x() + (_CONTENT.width() - drawn_w) / 2,
            _CONTENT.y() + (_CONTENT.height() - drawn_h) / 2,
            drawn_w,
            drawn_h,
        )
        self._polygons = ()
        self.setAccessibleName(f"Page {ordinal + 1}: detecting text regions\N{HORIZONTAL ELLIPSIS}")
        self.setAccessibleDescription("" if self._image is not None else UNDECODABLE)
        self.update()

    def set_regions(self, polygons: Sequence[Sequence[tuple[int, int]]]) -> None:
        """Replace the markers with these polygons, in page pixels. Only after
        `show_page`: the panel calls it for the page it last showed (C-4), and
        no criterion gives a thumbnail regions for no page."""
        assert self._ordinal is not None, "set_regions before any show_page"
        self._polygons = tuple(tuple(polygon) for polygon in polygons)
        self.setAccessibleName(f"Page {self._ordinal + 1}: {_found(len(self._polygons))}")
        self.update()

    def image_rect(self) -> QRectF:
        """Where the page is drawn, in widget coordinates, its aspect kept."""
        return QRectF(self._rect)

    def markers(self) -> tuple[QPolygonF, ...]:
        """Each polygon mapped from page pixels onto `image_rect()`, as painted."""
        origin, s = self._rect.topLeft(), self._scale
        return tuple(
            QPolygonF([QPointF(origin.x() + x * s, origin.y() + y * s) for x, y in polygon])
            for polygon in self._polygons
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        painter.setClipRect(_CONTENT)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._image is not None:
            painter.drawImage(self._rect, self._image)
        paths = []
        for marker in self.markers():
            path = QPainterPath()
            path.addPolygon(marker)
            paths.append(path)
        halo = overlay_pen(tokens_gen.OVERLAY_HALO, _HALO_WIDTH)
        for path in paths:
            painter.strokePath(path, halo)
        core = overlay_pen(tokens_gen.OVERLAY_BUBBLE_IDLE, _CORE_WIDTH)
        for path in paths:
            painter.strokePath(path, core)
        painter.end()
