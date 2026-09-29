"""The bubble <-> line link: the rules both panes render from.

`components.md` §4. Everything here is shared by `PageCanvas` and
`TranslationColumn`, and neither of them owns it (§4.1):

- `OrderedRegion` - a detected region with its reading-order identity. The
  ordinal (`region_id + 1`) is the primary carrier of the link (§4.2).
- `pan_to_contain` - the minimum pan that brings a region fully in with
  `space.6` of margin, or `None` when it is already entirely visible (§4.5).
  `None` is what makes "the viewport did not change" assertable exactly.
- `hit_test` - smallest area wins, ties to the lowest id, repeated clicks at the
  same point cycle (§4.8).
- `LinkController` - the one owner of `LinkState`. Hover never touches
  selection.
- `LiveRegion` - the off-screen label that stands in for ARIA-live (§4.9).

`QAccessible` and `QAccessibleEvent` are imported by name at module level so a
test can replace `mangatl.ui.link.QAccessible` and capture the Alert.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent, QPolygonF
from PySide6.QtWidgets import QLabel, QWidget

__all__ = [
    "SAME_POINT_PX",
    "SELECTION_MARGIN_PX",
    "LinkController",
    "LinkState",
    "LiveRegion",
    "OrderedRegion",
    "hit_test",
    "pan_to_contain",
]

#: components.md §4.5: the selected region comes in with `space.6` (24 px) of margin.
SELECTION_MARGIN_PX: int = 24
#: components.md §4.8: "within 3px of the first click" is the same point.
SAME_POINT_PX: int = 3


@dataclass(frozen=True)
class OrderedRegion:
    """A region in reading order. `polygon` is in page pixels, which are scene
    coordinates; `region_id` is its 0-based position in `read_regions(page)`."""

    region_id: int
    polygon: tuple[tuple[int, int], ...]

    @property
    def ordinal(self) -> int:
        """The 1-based number on the badge and at the head of the row."""
        return self.region_id + 1

    def bounds(self) -> QRectF:
        """The bounding rect of the polygon's vertices."""
        xs = [x for x, _ in self.polygon]
        ys = [y for _, y in self.polygon]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def area(self) -> float:
        """The absolute shoelace area of the polygon (winding does not matter)."""
        points = self.polygon
        twice = sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True)
        )
        return abs(twice) / 2.0

    def qpolygon(self) -> QPolygonF:
        """The polygon as Qt geometry, for containment and painting."""
        return QPolygonF([QPointF(x, y) for x, y in self.polygon])


@dataclass
class LinkState:
    """The whole of the link: one selection, one hover, both optional."""

    selected_region_id: int | None = None
    hovered_region_id: int | None = None


def _axis_delta(low: float, high: float, inset_low: float, inset_high: float) -> float:
    """Minimal shift of [low, high] into [inset_low, inset_high]; centre if it cannot fit."""
    if high - low > inset_high - inset_low:
        return (inset_low + inset_high) / 2 - (low + high) / 2
    if low < inset_low:
        return inset_low - low
    if high > inset_high:
        return inset_high - high
    return 0.0


def pan_to_contain(view_rect: QRectF, region_rect: QRectF, margin: int) -> QPointF | None:
    """The content translation that brings `region_rect` into `view_rect` with
    `margin`, or `None` when it is already entirely inside `view_rect`.

    Both rects are in the same coordinates. Positive x moves the region right on
    screen. Per axis the shift is minimal; an axis the region cannot fit on
    (inside the inset) is centred instead (§4.5).
    """
    if (
        region_rect.left() >= view_rect.left()
        and region_rect.top() >= view_rect.top()
        and region_rect.right() <= view_rect.right()
        and region_rect.bottom() <= view_rect.bottom()
    ):
        return None
    inset = view_rect.adjusted(margin, margin, -margin, -margin)
    return QPointF(
        _axis_delta(region_rect.left(), region_rect.right(), inset.left(), inset.right()),
        _axis_delta(region_rect.top(), region_rect.bottom(), inset.top(), inset.bottom()),
    )


def hit_test(regions: Sequence[OrderedRegion], point: QPointF, previous: int | None) -> int | None:
    """The region a click at `point` selects (§4.8).

    Candidates are the regions whose polygon contains the point. With no usable
    `previous`, the smallest area wins and ties go to the lowest id; when
    `previous` is a candidate, the next candidate by ascending id, wrapping.
    """
    candidates = sorted(
        (
            region
            for region in regions
            if region.qpolygon().containsPoint(point, Qt.FillRule.OddEvenFill)
        ),
        key=lambda region: region.region_id,
    )
    if not candidates:
        return None
    ids = [region.region_id for region in candidates]
    if previous is not None and previous in ids:
        return ids[(ids.index(previous) + 1) % len(ids)]
    return min(candidates, key=lambda region: (region.area(), region.region_id)).region_id


class LinkController(QObject):
    """The one owner of `LinkState` (§4.1). Emits only on change."""

    selectionChanged = Signal(object)  # int | None
    hoverChanged = Signal(object)  # int | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.state = LinkState()

    def select(self, region_id: int | None) -> None:
        """Select `region_id` (or nothing). Hover is left exactly as it was."""
        if region_id == self.state.selected_region_id:
            return
        self.state.selected_region_id = region_id
        self.selectionChanged.emit(region_id)

    def hover(self, region_id: int | None) -> None:
        """Hover `region_id` (or nothing). Never touches the selection."""
        if region_id == self.state.hovered_region_id:
            return
        self.state.hovered_region_id = region_id
        self.hoverChanged.emit(region_id)


class LiveRegion(QLabel):
    """An off-screen label whose rewrite is announced as an Alert (§4.9)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("liveRegion")
        # Off-screen rather than hidden: a hidden widget is not in the
        # accessibility tree at all, and this one exists to be read.
        self.setGeometry(-10000, -10000, 1, 1)

    def announce(self, text: str) -> None:
        """Say `text` to a screen reader."""
        self.setAccessibleName(text)
        self.setText(text)
        QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.Alert))
