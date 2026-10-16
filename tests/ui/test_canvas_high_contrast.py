"""MT-073: the canvas under High Contrast changes exactly three things.

`components.md` §3 (the frame and the viewport focus ring, the baseline MT-015
deferred) and §10.3 (the three High Contrast deltas); `high-contrast.md` §6
(the mat stays grey, the 3:1 arithmetic), §7 (the markers do not change) and
§7.1 (dimming stops); `accessibility.md` A-04, A-15.5, A-15.6, A-15.9, A-15.10;
`tokens.md` §7 (focus ring geometry).

**Oracle partition (story `## Model guidance`, PO 2026-10-15).**

- *Settled, read out:* every width and colour below comes from
  `tokens_gen` (`TOKENS`, `BORDER_WIDTH_*`, `OVERLAY_DIM_OPACITY`,
  `HC_OVERRIDE`, `HC_PALETTE_ROLE`); the ratios 6.39 / 3.29 are
  `high-contrast.md` §6, 1.62 is the contract's (block 1), 3.0 is A-04's.
  Nothing here is tuned. The exempt set is ENUMERATED from `HC_PALETTE_ROLE`.
- *Mechanical, pinned:* `paint_boundary`'s geometry per pixel, the
  `PageCanvas` properties of contract block 2b, `set_high_contrast`'s refusal
  of a palette missing a role, `follow_theme` applying now and on every later
  `apply()`.
- *Oracle-free:* none. The pixel comparisons are equalities; the one thing a
  negative control is owed for is the comparison instrument itself.

**Instruments (measured in RED, story `## Handoff`).**

- `_rendered(canvas)` is `viewport().grab()`: a FRESH render through
  `PageCanvas.paintEvent` (measured: a test-local `paintEvent` override shows
  in it). It cannot see stale pixels, because it repaints everything.
- `_on_screen(canvas)` reads the window's backing store with
  `QScreen.grabWindow(window.winId())`, cropped to the viewport: what a user
  would see. A painter that leaves a stale copy of its band after a pan shows
  it here (measured: 493 stale band pixels with a naive viewport-space
  painter, 0 once it updates the viewport) and not in `_rendered`. So every
  claim about what is ON SCREEN after something changes - a pan, a focus
  change, a mode change - reads `_on_screen`, and the control
  `test_the_on_screen_instrument_sees_the_stale_band_a_naive_painter_leaves_after_a_pan`
  proves it can.
- `_reference(canvas)` is a plain `QGraphicsView` on the canvas's own scene, at
  the same size, transform, scroll values and background: the viewport's
  contents with no band. "The band does not move the contents" is the canvas
  equal to it strictly inside the band.
- `_differences(a, b, rect)` is the one pixel comparison; its controls are
  `test_the_pixel_comparison_reports_a_single_differing_pixel` and
  `test_the_reference_comparison_detects_a_one_pixel_pan`.

**AC-2 vs A-15.5's "Testable as".** A-15.5 says to assert every token whose
name starts with `overlay.` keeps its authored value under High Contrast, but
A-15.6 (and this story's AC-3, delta 1) has `overlay.dim.opacity` resolve to
1.0. The AC says "every `overlay.*` COLOUR"; the enumeration below is over
colours, and the resolve check exempts `overlay.dim.opacity` by name, citing
A-15.6. Raised in the RED handoff.

New names (`contrast_ratio`, `mat_safe`, `paint_boundary`, `set_high_contrast`,
...) are reached as module attributes inside the tests, so this file collects
in RED and each test fails on its own missing name; the instrument controls,
which need no new code, run and pass.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsScene,
    QGraphicsView,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from mangatl import app as app_module
from mangatl.domain.page import Chapter, Page
from mangatl.store.project import create_project
from mangatl.ui import canvas as canvas_module
from mangatl.ui import theme as theme_module
from mangatl.ui import tokens_gen
from mangatl.ui.canvas import PageCanvas
from mangatl.ui.contrast import FixedContrastSource
from mangatl.ui.link import LinkState, OrderedRegion
from mangatl.ui.markers import MarkerState
from mangatl.ui.workspace import Workspace

#: MT-072 (`tests/ui/conftest.py`): every window `build_window` returns here is
#: closed at teardown, and every project it opened with it.
pytestmark = pytest.mark.usefixtures(
    "every_opened_project_is_closed", "every_built_window_is_closed"
)

T = tokens_gen.TOKENS

# --- Settled, read out of tokens_gen (asserted against the documents below) ---
AUTHORED_FRAME = T["color.canvas.frame"]  # components.md §3
AUTHORED_RING = T["color.focus.ring"]  # tokens.md §7
AUTHORED_HALO = T["color.focus.halo"]  # tokens.md §7
MAT = T["color.canvas.surround"]  # high-contrast.md §6: "#5F5F5F"
HAIRLINE = tokens_gen.BORDER_WIDTH_HAIRLINE  # the default frame: 1 px
EMPHASIS = tokens_gen.BORDER_WIDTH_EMPHASIS  # the HC frame: 2 px (§10.3)
FOCUS_WIDTH = int(T["focus.width"])  # 2
FOCUS_HALO = int(T["focus.halo"])  # 1
DIM = tokens_gen.OVERLAY_DIM_OPACITY  # 0.55 (components.md §4.3)
HC_DIM = tokens_gen.HC_OVERRIDE["overlay.dim.opacity"]  # 1.0 (A-15.6)
STATIC = theme_module.STATIC
#: A-04: the non-text contrast floor `mat_safe` checks against.
THRESHOLD = 3.0

#: A synthetic contrast palette, this file's own (the `test_theme_apply.PALETTE`
#: convention, not that object). No value is any token's (asserted below), so a
#: pixel or property equal to one of these can only have come from the palette.
#: `WindowText` is near-white: 6.27:1 against the mat, so it clears 3:1.
PALETTE: dict[str, str] = {
    "Window": "#020406",
    "WindowText": "#FCFDFE",
    "Highlight": "#1B2C3D",
    "HighlightedText": "#C4B3A2",
    "DisabledText": "#4E5F60",
}
#: A user-edited theme whose Text is mid grey: 1.62:1 against the mat (A-15.9).
MID_GREY = "#808080"
MID_GREY_PALETTE: dict[str, str] = {**PALETTE, "WindowText": MID_GREY}
#: Microsoft's own extremes, black Text: 3.29:1, clears (high-contrast.md §6).
BLACK_PALETTE: dict[str, str] = {**PALETTE, "WindowText": "#000000", "Window": "#FFFFFF"}

#: Instrument colours: the bare image's ground, and the page's two inks. None
#: is any token's value or any palette's (asserted below).
SENTINEL = "#13579B"
PAGE_FILL = "#6A8A5A"
PAGE_INK = "#C08040"

# --- Geometry ------------------------------------------------------------------
#: The bare image `paint_boundary` paints onto, and the rect it is given: a 4 px
#: margin so "nothing outside `rect` is painted" is observable.
IMAGE = QSize(48, 36)
RECT = QRect(4, 4, 40, 28)
#: The shown canvas: a 1200 x 1000 patterned page in a host that also holds a
#: line edit, so focus can be put somewhere that is not the canvas. Scrolled to
#: (SCROLL, SCROLL): every viewport edge is on the page, away from its edge line.
PAGE = QSize(1200, 1000)
HOST = QSize(620, 560)
SCROLL = 200
PAN = (60, 30)


def _ring(x: int, y: int, w: int, h: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y))


#: Three regions well inside the viewport at scroll (SCROLL, SCROLL), far from
#: every edge, so no marker pixel reaches the band.
REGIONS = (
    OrderedRegion(region_id=0, polygon=_ring(350, 330, 110, 80)),
    OrderedRegion(region_id=1, polygon=_ring(520, 360, 90, 120)),
    OrderedRegion(region_id=2, polygon=_ring(400, 470, 140, 70)),
)


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# Instruments
# =============================================================================


def _rgb32(image: QImage) -> QImage:
    return image.convertToFormat(QImage.Format.Format_RGB32)


def _at(image: QImage, x: int, y: int) -> str:
    """`#rrggbb`, lower case, as `QColor.name()` gives it."""
    return QColor(image.pixel(x, y)).name()


def _differences(a: QImage, b: QImage, rect: QRect) -> list[tuple[int, int, str, str]]:
    """Every pixel inside `rect` where `a` and `b` differ: (x, y, a, b).

    Compared byte for byte in RGB32, row by row; only a differing row is
    walked pixel by pixel. An image whose size differs is a failure, not a
    comparison."""
    assert a.size() == b.size(), f"compared images differ in size: {a.size()} vs {b.size()}"
    first, second = _rgb32(a).copy(rect), _rgb32(b).copy(rect)
    stride = first.bytesPerLine()
    assert stride == second.bytesPerLine()
    left, right = bytes(first.constBits()), bytes(second.constBits())
    width = first.width() * 4
    found: list[tuple[int, int, str, str]] = []
    for y in range(first.height()):
        row = slice(y * stride, y * stride + width)
        if left[row] == right[row]:
            continue
        for x in range(first.width()):
            cell = slice(y * stride + 4 * x, y * stride + 4 * x + 4)
            if left[cell] != right[cell]:
                found.append((rect.x() + x, rect.y() + y, _at(first, x, y), _at(second, x, y)))
    return found


def _summary(found: list[tuple[int, int, str, str]]) -> str:
    return f"{len(found)} differing pixel(s), first: {found[:5]}"


def _inset(rect: QRect, by: int) -> QRect:
    return rect.adjusted(by, by, -by, -by)


def _depth(rect: QRect, x: int, y: int) -> int:
    """How many pixels in from `rect`'s nearest edge (x, y) is; negative outside."""
    return min(x - rect.left(), rect.right() - x, y - rect.top(), rect.bottom() - y)


def _ring_points(rect: QRect, depth: int) -> Iterator[tuple[int, int]]:
    """Every pixel exactly `depth` in from `rect`'s edge, each once."""
    left, right = rect.left() + depth, rect.right() - depth
    top, bottom = rect.top() + depth, rect.bottom() - depth
    for x in range(left, right + 1):
        yield x, top
        yield x, bottom
    for y in range(top + 1, bottom):
        yield left, y
        yield right, y


@dataclass(frozen=True)
class Band:
    """What the boundary should be: contract block 2a, in one mode and state."""

    focused: bool
    frame_width: int
    frame: str
    ring: str
    halo: str

    @property
    def depth(self) -> int:
        return FOCUS_HALO + FOCUS_WIDTH if self.focused else self.frame_width

    def colour_at(self, depth: int) -> str | None:
        """The band colour `depth` px in from the edge, or None inside the band."""
        if self.focused:
            if depth < FOCUS_HALO:
                return self.halo
            if depth < FOCUS_HALO + FOCUS_WIDTH:
                return self.ring
            return None
        return self.frame if depth < self.frame_width else None

    @property
    def colours(self) -> set[str]:
        return {self.frame.lower(), self.ring.lower(), self.halo.lower()}


def _default_band(focused: bool) -> Band:
    return Band(focused, HAIRLINE, AUTHORED_FRAME, AUTHORED_RING, AUTHORED_HALO)


def _hc_band(focused: bool, palette: Mapping[str, str] = PALETTE) -> Band:
    return Band(focused, EMPHASIS, palette["WindowText"], palette["WindowText"], palette["Window"])


def _band_failures(image: QImage, band: Band) -> list[str]:
    """Every band pixel of the viewport image that is not its band colour, and
    every pixel just inside the band that IS a band colour (a band too wide)."""
    rect = image.rect()
    failures: list[str] = []
    for depth in range(band.depth):
        expected = band.colour_at(depth)
        assert expected is not None
        for x, y in _ring_points(rect, depth):
            got = _at(image, x, y)
            if got != expected.lower():
                failures.append(f"({x},{y}) depth {depth}: {got}, expected {expected.lower()}")
    for x, y in _ring_points(rect, band.depth):
        got = _at(image, x, y)
        if got in band.colours:
            failures.append(f"({x},{y}) just inside the band (depth {band.depth}): {got}")
    return failures


def _report(failures: list[str]) -> str:
    return f"{len(failures)} pixel(s) wrong, first: {failures[:6]}"


def _rendered(canvas: QGraphicsView) -> QImage:
    """A fresh render of the viewport, through the view's `paintEvent`."""
    return _rgb32(canvas.viewport().grab().toImage())


def _on_screen(canvas: QGraphicsView) -> QImage:
    """The viewport's pixels as the window's backing store holds them."""
    window = canvas.window()
    viewport = canvas.viewport()
    origin = viewport.mapTo(window, QPoint(0, 0))
    screen = window.screen() or QGuiApplication.primaryScreen()
    whole = screen.grabWindow(window.winId()).toImage()
    return _rgb32(whole.copy(QRect(origin, viewport.size())))


def _reference(qtbot: Any, canvas: QGraphicsView) -> QImage:
    """The canvas's contents with no band: a plain view of the same scene, at
    the same size, transform, scroll values and background."""
    view = QGraphicsView(canvas.scene())
    qtbot.addWidget(view)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setBackgroundBrush(canvas.backgroundBrush())
    view.setTransform(canvas.transform())
    view.resize(canvas.size())
    with qtbot.waitExposed(view):
        view.show()
    view.horizontalScrollBar().setValue(canvas.horizontalScrollBar().value())
    view.verticalScrollBar().setValue(canvas.verticalScrollBar().value())
    _settle()
    assert view.viewport().size() == canvas.viewport().size(), "reference: viewport size"
    for point in (QPointF(0, 0), QPointF(PAGE.width(), PAGE.height())):
        assert view.mapFromScene(point) == canvas.mapFromScene(point), "reference: mapping"
    image = _rendered(view)
    view.hide()
    return image


def _page_image(size: QSize) -> QImage:
    """A page with a 7 x 11 px grid on it, so a one-pixel shift changes pixels."""
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(PAGE_FILL))
    painter = QPainter(image)
    try:
        painter.setPen(QColor(PAGE_INK))
        for x in range(0, size.width(), 7):
            painter.drawLine(x, 0, x, size.height() - 1)
        for y in range(0, size.height(), 11):
            painter.drawLine(0, y, size.width() - 1, y)
    finally:
        painter.end()
    return image


# =============================================================================
# The shown canvas
# =============================================================================


@dataclass
class Stage:
    host: QWidget
    canvas: PageCanvas
    elsewhere: QLineEdit


def _show(qtbot: Any, view: QGraphicsView) -> tuple[QWidget, QLineEdit]:
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    elsewhere = QLineEdit(host)
    layout.addWidget(elsewhere)
    layout.addWidget(view)
    host.resize(HOST)
    with qtbot.waitExposed(host):
        host.show()
    host.activateWindow()
    qtbot.waitUntil(host.isActiveWindow)
    return host, elsewhere


@pytest.fixture
def stage(qtbot: Any, qapp: QApplication) -> Iterator[Stage]:
    """A shown PageCanvas with a patterned page and REGIONS, nothing selected,
    zoom 1, scrolled to (SCROLL, SCROLL), keyboard focus in the line edit."""
    assert qapp.styleSheet() == "", "precondition: no application sheet"
    canvas = PageCanvas()
    canvas.set_page(QPixmap.fromImage(_page_image(PAGE)))
    canvas.set_regions(REGIONS)
    host, elsewhere = _show(qtbot, canvas)
    canvas.horizontalScrollBar().setValue(SCROLL)
    canvas.verticalScrollBar().setValue(SCROLL)
    elsewhere.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(elsewhere.hasFocus)
    _settle()
    assert canvas.horizontalScrollBar().value() == SCROLL, "fixture: no horizontal range"
    assert canvas.verticalScrollBar().value() == SCROLL, "fixture: no vertical range"
    assert not canvas.hasFocus()
    yield Stage(host, canvas, elsewhere)
    del host


def _focus(qtbot: Any, stage: Stage, focused: bool) -> None:
    target: QWidget = stage.canvas if focused else stage.elsewhere
    target.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(target.hasFocus)
    _settle()
    assert stage.canvas.hasFocus() is focused, "precondition: canvas focus"


def _set_hc(canvas: PageCanvas, enabled: bool, palette: Mapping[str, str] = PALETTE) -> None:
    canvas.set_high_contrast(enabled, palette)  # type: ignore[attr-defined]
    _settle()


def _transform(view: QGraphicsView) -> tuple[float, ...]:
    t = view.transform()
    return (t.m11(), t.m12(), t.m13(), t.m21(), t.m22(), t.m23(), t.m31(), t.m32(), t.m33())


def _canvas_snapshot(canvas: PageCanvas) -> dict[str, object]:
    """Everything `PageCanvas` exposes that High Contrast must NOT change."""
    rect = canvas.sceneRect()
    return {
        "zoom": canvas.zoom(),
        "transform": _transform(canvas),
        "horizontal scroll": canvas.horizontalScrollBar().value(),
        "vertical scroll": canvas.verticalScrollBar().value(),
        "link state": replace(canvas._link_state),
        "marker count": len(canvas.markers),
        "marker states": [marker.state() for marker in canvas.markers],
        "marker opacities": [marker.opacity() for marker in canvas.markers],
        "marker z": [marker.zValue() for marker in canvas.markers],
        "background": canvas.backgroundBrush().color().name(),
        "scene rect": (rect.x(), rect.y(), rect.width(), rect.height()),
        "state": canvas.state(),
        "focus policy": canvas.focusPolicy(),
        "widget style sheet": canvas.styleSheet(),
        "scene origin in viewport": canvas.mapFromScene(QPointF(0, 0)),
    }


def _properties(canvas: PageCanvas) -> dict[str, object]:
    c: Any = canvas
    return {
        "high_contrast": c.high_contrast,
        "frame_width": c.frame_width,
        "frame_colour": c.frame_colour,
        "ring_colour": c.ring_colour,
        "halo_colour": c.halo_colour,
    }


def _default_properties() -> dict[str, object]:
    return {
        "high_contrast": False,
        "frame_width": HAIRLINE,
        "frame_colour": AUTHORED_FRAME,
        "ring_colour": AUTHORED_RING,
        "halo_colour": AUTHORED_HALO,
    }


def _hc_properties(palette: Mapping[str, str] = PALETTE) -> dict[str, object]:
    return {
        "high_contrast": True,
        "frame_width": EMPHASIS,
        "frame_colour": palette["WindowText"],
        "ring_colour": palette["WindowText"],
        "halo_colour": palette["Window"],
    }


# =============================================================================
# Fixture checks: the instruments and the numbers read out
# =============================================================================


def test_no_instrument_or_synthetic_palette_colour_is_any_tokens_value() -> None:
    """Fixture check: a pixel or property equal to one of these came from here."""
    authored = {value.upper() for value in T.values()}
    ours = {
        "SENTINEL": SENTINEL,
        "PAGE_FILL": PAGE_FILL,
        "PAGE_INK": PAGE_INK,
        **{f"PALETTE[{role}]": value for role, value in PALETTE.items()},
    }
    clashes = {name: value for name, value in ours.items() if value.upper() in authored}
    assert clashes == {}, f"these share a value with a token: {clashes}"
    band_colours = {AUTHORED_FRAME, AUTHORED_RING, AUTHORED_HALO, *PALETTE.values(), MID_GREY}
    assert {PAGE_FILL, PAGE_INK, SENTINEL}.isdisjoint(band_colours)


def test_the_widths_and_opacities_read_out_are_the_documents_numbers() -> None:
    """Fixture check: components.md §3 / §10.3, tokens.md §7, A-15.6, §4.3."""
    assert (HAIRLINE, EMPHASIS, FOCUS_WIDTH, FOCUS_HALO) == (1, 2, 2, 1)
    assert DIM == 0.55
    assert HC_DIM == 1.0
    assert MAT.upper() == "#5F5F5F"
    assert STATIC == "@static"


def test_the_pixel_comparison_reports_a_single_differing_pixel() -> None:
    """Negative control for every 'identical' below: one pixel, found, named."""
    a = QImage(QSize(30, 20), QImage.Format.Format_RGB32)
    a.fill(QColor(SENTINEL))
    b = a.copy()
    b.setPixelColor(17, 9, QColor(PAGE_INK))
    found = _differences(a, b, a.rect())
    assert found == [(17, 9, SENTINEL.lower(), PAGE_INK.lower())], _summary(found)
    assert _differences(a, b, QRect(0, 0, 17, 20)) == [], "outside the rect is not compared"
    assert _differences(a, a.copy(), a.rect()) == []


class _NaiveBand(QGraphicsView):
    """A viewport-space band painted after the base, as contract block 2b says
    `PageCanvas` paints it - optionally WITHOUT repainting the viewport on a
    scroll, which is the defect the pan assertion exists for."""

    def __init__(self, scene: QGraphicsScene, *, update_on_scroll: bool) -> None:
        super().__init__(scene)
        self.update_on_scroll = update_on_scroll
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        try:
            rect = self.viewport().rect()
            for x, y in _ring_points(rect, 0):
                painter.fillRect(QRect(x, y, 1, 1), QColor(AUTHORED_FRAME))
        finally:
            painter.end()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if self.update_on_scroll:
            self.viewport().update()


@pytest.mark.parametrize("update_on_scroll", [False, True], ids=["naive", "updates"])
def test_the_on_screen_instrument_sees_the_stale_band_a_naive_painter_leaves_after_a_pan(
    qtbot: Any, update_on_scroll: bool
) -> None:
    """Negative control for AC-1's pan assertion: `_on_screen` must report the
    stale band a painter that does not repaint on scroll leaves - and must not
    report one for a painter that does. `_rendered` sees neither, which is why
    it is not the instrument for that assertion."""
    scene = QGraphicsScene()
    scene.addPixmap(QPixmap.fromImage(_page_image(PAGE)))
    view = _NaiveBand(scene, update_on_scroll=update_on_scroll)
    host, _ = _show(qtbot, view)  # held: a collected host deletes the view
    view.horizontalScrollBar().setValue(SCROLL)
    view.verticalScrollBar().setValue(SCROLL)
    _settle()
    view.horizontalScrollBar().setValue(SCROLL + PAN[0])
    view.verticalScrollBar().setValue(SCROLL + PAN[1])
    _settle()
    band = Band(False, 1, AUTHORED_FRAME, AUTHORED_FRAME, AUTHORED_FRAME)
    screen, fresh = _on_screen(view), _rendered(view)
    assert _band_failures(fresh, band) == [], "the fresh render always shows a clean band"
    stale = _differences(screen, fresh, screen.rect())
    if update_on_scroll:
        assert stale == [], _summary(stale)
        assert _band_failures(screen, band) == []
    else:
        assert len(stale) > 100, f"the instrument missed the stale band: {_summary(stale)}"
        # A stale copy of the band, carried inside the viewport by the scroll:
        inside = [
            d
            for d in stale
            if d[2] == AUTHORED_FRAME.lower() and _depth(screen.rect(), d[0], d[1]) >= 1
        ]
        assert len(inside) > 100, f"no stale band inside the viewport: {_summary(stale)}"
    del host


def test_the_reference_comparison_detects_a_one_pixel_pan(qtbot: Any, stage: Stage) -> None:
    """Negative control for 'the band does not move the contents': the
    reference taken before a one-pixel pan differs from the canvas after it."""
    canvas = stage.canvas
    before = _reference(qtbot, canvas)
    canvas.horizontalScrollBar().setValue(SCROLL + 1)
    _settle()
    found = _differences(_rendered(canvas), before, _inset(before.rect(), 3))
    assert len(found) > 1000, _summary(found)


# =============================================================================
# AC-1 and contract block 2a: `paint_boundary` on a bare image
# =============================================================================

BOUNDARY_PARAMETERS: dict[str, dict[str, Any]] = {
    "default theme": {
        "frame_width": HAIRLINE,
        "frame_colour": AUTHORED_FRAME,
        "ring_colour": AUTHORED_RING,
        "halo_colour": AUTHORED_HALO,
    },
    "high contrast": {
        "frame_width": EMPHASIS,
        "frame_colour": PALETTE["WindowText"],
        "ring_colour": PALETTE["WindowText"],
        "halo_colour": PALETTE["Window"],
    },
}


def _paint_boundary_on_sentinel(focused: bool, parameters: Mapping[str, Any]) -> QImage:
    image = QImage(IMAGE, QImage.Format.Format_RGB32)
    image.fill(QColor(SENTINEL))
    painter = QPainter(image)
    try:
        canvas_module.paint_boundary(  # type: ignore[attr-defined]
            painter, QRect(RECT), focused=focused, **parameters
        )
    finally:
        painter.end()
    return image


@pytest.mark.parametrize("focused", [False, True], ids=["unfocused", "focused"])
@pytest.mark.parametrize("mode", list(BOUNDARY_PARAMETERS))
def test_paint_boundary_paints_exactly_the_band_inside_rect_and_nothing_else(
    mode: str, focused: bool
) -> None:
    """Block 2a, per pixel. Unfocused: the outermost `frame_width` px of `rect`
    are `frame_colour`. Focused: the outermost 1 px (`focus.halo`) are
    `halo_colour` and the 2 px (`focus.width`) inside them `ring_colour` - the
    frame covered, not drawn beside. Everything else, inside the band and
    outside `rect`, is still the sentinel."""
    parameters = BOUNDARY_PARAMETERS[mode]
    image = _paint_boundary_on_sentinel(focused, parameters)
    band = Band(
        focused,
        parameters["frame_width"],
        parameters["frame_colour"],
        parameters["ring_colour"],
        parameters["halo_colour"],
    )
    wrong = []
    for y in range(IMAGE.height()):
        for x in range(IMAGE.width()):
            depth = _depth(RECT, x, y)
            colour = band.colour_at(depth) if depth >= 0 else None
            expected = (colour or SENTINEL).lower()
            got = _at(image, x, y)
            if got != expected:
                wrong.append(f"({x},{y}) depth {depth}: {got}, expected {expected}")
    assert wrong == [], f"{mode}, focused={focused}: {_report(wrong)}"


# =============================================================================
# AC-1: the real canvas, default theme
# =============================================================================


@pytest.mark.parametrize("focused", [False, True], ids=["unfocused", "focused"])
def test_the_shown_canvas_draws_the_frame_or_the_focus_ring_on_every_viewport_edge(
    qtbot: Any, stage: Stage, focused: bool
) -> None:
    """AC-1 (components.md §3, A-13.2, tokens.md §7): unfocused, a 1 px
    `color.canvas.frame` on the outermost viewport pixel of every side; with
    keyboard focus, a 1 px `color.focus.halo` then 2 px `color.focus.ring`, the
    frame covered. Read on screen, after the focus change."""
    _focus(qtbot, stage, focused)
    failures = _band_failures(_on_screen(stage.canvas), _default_band(focused))
    assert failures == [], f"focused={focused}: {_report(failures)}"


def test_losing_focus_puts_the_frame_back_on_screen(qtbot: Any, stage: Stage) -> None:
    """AC-1: the ring is shown while the canvas has focus, and only then."""
    _focus(qtbot, stage, True)
    _focus(qtbot, stage, False)
    failures = _band_failures(_on_screen(stage.canvas), _default_band(False))
    assert failures == [], _report(failures)


@pytest.mark.parametrize("focused", [False, True], ids=["unfocused", "focused"])
def test_the_band_does_not_move_the_viewport_contents(
    qtbot: Any, stage: Stage, focused: bool
) -> None:
    """AC-1 "neither moves the viewport's contents": strictly inside the band,
    the canvas is pixel-identical to a plain view of the same scene at the same
    mapping - and the band is there (else this would compare nothing new)."""
    _focus(qtbot, stage, focused)
    band = _default_band(focused)
    canvas = stage.canvas
    image = _rendered(canvas)
    assert _band_failures(image, band) == [], "precondition: the band is drawn"
    found = _differences(image, _reference(qtbot, canvas), _inset(image.rect(), band.depth))
    assert found == [], f"focused={focused}: the band moved the contents: {_summary(found)}"


@pytest.mark.parametrize("focused", [False, True], ids=["unfocused", "focused"])
def test_after_a_pan_the_band_is_at_the_viewport_edges_only(
    qtbot: Any, stage: Stage, focused: bool
) -> None:
    """Contract block 2b: a pan shifts the viewport's pixels; it must not leave
    a stale copy of the band inside. On screen, after the pan, the band is at
    the edges, the pixel just inside it is not a band colour, and the whole
    viewport equals a fresh render."""
    _focus(qtbot, stage, focused)
    canvas = stage.canvas
    canvas.horizontalScrollBar().setValue(SCROLL + PAN[0])
    canvas.verticalScrollBar().setValue(SCROLL + PAN[1])
    _settle()
    screen = _on_screen(canvas)
    failures = _band_failures(screen, _default_band(focused))
    assert failures == [], f"focused={focused}: {_report(failures)}"
    stale = _differences(screen, _rendered(canvas), screen.rect())
    assert stale == [], f"focused={focused}: stale pixels after a pan: {_summary(stale)}"


# =============================================================================
# AC-2: the overlay colours, the mat and the page edge keep their values
# =============================================================================

_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")


def _is_colour_token(name: str) -> bool:
    return _COLOUR.fullmatch(T[name]) is not None


def test_every_overlay_colour_and_the_mat_and_the_page_edge_are_static() -> None:
    """AC-2 / A-15.5, enumerated from `HC_PALETTE_ROLE`, not hand-picked: the
    `@static` set contains every `overlay.*` colour token, `color.canvas.surround`
    and `color.canvas.page-edge`; and no `overlay.*` token maps to a role."""
    static = {name for name, role in tokens_gen.HC_PALETTE_ROLE.items() if role == STATIC}
    overlay_colours = {n for n in T if n.startswith("overlay.") and _is_colour_token(n)}
    assert overlay_colours, "fixture: no overlay colour token found"
    required = overlay_colours | {"color.canvas.surround", "color.canvas.page-edge"}
    assert sorted(required - static) == [], "not @static in HC_PALETTE_ROLE"
    mapped = {
        name: role
        for name, role in tokens_gen.HC_PALETTE_ROLE.items()
        if name.startswith("overlay.") and role != STATIC
    }
    assert mapped == {}, f"overlay tokens mapped to a palette role: {mapped}"


@pytest.mark.parametrize("palette", [PALETTE, BLACK_PALETTE], ids=["near-white", "black"])
def test_under_high_contrast_every_overlay_token_but_the_dim_and_both_grounds_resolve_authored(
    palette: Mapping[str, str],
) -> None:
    """AC-2 / A-15.5 "Testable as", for any palette - except
    `overlay.dim.opacity`, which A-15.6 (AC-3 delta 1) resolves to 1.0."""
    names = [n for n in T if n.startswith("overlay.") and n != "overlay.dim.opacity"]
    names += ["color.canvas.surround", "color.canvas.page-edge"]
    changed = {
        n: (T[n], theme_module.resolve(n, high_contrast=True, palette=palette))
        for n in names
        if theme_module.resolve(n, high_contrast=True, palette=palette) != T[n]
    }
    assert changed == {}, f"(authored, resolved) under High Contrast: {changed}"
    dim = theme_module.resolve("overlay.dim.opacity", high_contrast=True, palette=palette)
    assert float(dim) == HC_DIM


@pytest.mark.parametrize("focused", [False, True], ids=["unfocused", "focused"])
def test_under_high_contrast_the_viewport_inside_the_band_is_pixel_identical(
    qtbot: Any, stage: Stage, focused: bool
) -> None:
    """AC-2 on pixels: with a page and regions and no selection (so dimming is
    not in play), everything strictly inside the wider of the two bands is the
    same with High Contrast off and on: page, mat, page edge and markers."""
    _focus(qtbot, stage, focused)
    canvas = stage.canvas
    inside = _inset(_rendered(canvas).rect(), max(_default_band(focused).depth, EMPHASIS))
    _set_hc(canvas, False, PALETTE)
    off = _rendered(canvas)
    _set_hc(canvas, True, PALETTE)
    on = _rendered(canvas)
    found = _differences(off, on, inside)
    assert found == [], f"High Contrast changed the canvas inside the band: {_summary(found)}"
    found = _differences(on, _reference(qtbot, canvas), inside)
    assert found == [], f"under High Contrast the contents moved: {_summary(found)}"


def test_the_frame_band_itself_does_differ_across_modes(stage: Stage) -> None:
    """Negative control for the identity above, at the band: the same
    comparison reports the frame, authored `color.canvas.frame` against the
    palette's `WindowText`, on every outermost viewport pixel."""
    canvas = stage.canvas
    _set_hc(canvas, False, PALETTE)
    off = _rendered(canvas)
    _set_hc(canvas, True, PALETTE)
    on = _rendered(canvas)
    outermost = set(_ring_points(off.rect(), 0))
    found = [d for d in _differences(off, on, off.rect()) if (d[0], d[1]) in outermost]
    assert len(found) == len(outermost), _summary(found)
    pairs = {(d[2], d[3]) for d in found}
    assert pairs == {(AUTHORED_FRAME.lower(), PALETTE["WindowText"].lower())}, pairs


# =============================================================================
# AC-3: exactly three things differ
# =============================================================================


@pytest.mark.parametrize("palette", [PALETTE, BLACK_PALETTE], ids=["near-white Text", "black Text"])
def test_high_contrast_makes_the_frame_window_text_at_2px_and_the_ring_window_text_on_window(
    stage: Stage, palette: Mapping[str, str]
) -> None:
    """AC-3 deltas 2 and 3 (components.md §10.3), as contract block 2b exposes
    them; and High Contrast off puts back the authored values exactly."""
    canvas = stage.canvas
    assert _properties(canvas) == _default_properties()
    _set_hc(canvas, True, palette)
    assert _properties(canvas) == _hc_properties(palette)
    _set_hc(canvas, False, palette)
    assert _properties(canvas) == _default_properties()


def test_high_contrast_changes_nothing_else_the_canvas_exposes(stage: Stage) -> None:
    """AC-3 "exactly three": zoom, transform, both scroll values, `_link_state`,
    marker count, states, opacities (nothing selected) and z, the background
    brush, scene rect, state, focus policy and the widget's own sheet are the
    same before High Contrast, under it, and after it."""
    canvas = stage.canvas
    canvas.set_zoom(1.5)
    canvas.horizontalScrollBar().setValue(SCROLL + PAN[0])
    _settle()
    before = _canvas_snapshot(canvas)
    assert before["marker count"] == len(REGIONS)
    assert before["background"] == MAT.lower()
    for enabled in (True, False):
        _set_hc(canvas, enabled, PALETTE)
        after = _canvas_snapshot(canvas)
        changed = {k: (before[k], after[k]) for k in before if after[k] != before[k]}
        assert changed == {}, f"set_high_contrast({enabled}) changed (before, after): {changed}"


@pytest.mark.parametrize("focused", [False, True], ids=["unfocused", "focused"])
def test_under_high_contrast_the_band_on_screen_is_window_text_with_a_window_halo(
    qtbot: Any, stage: Stage, focused: bool
) -> None:
    """AC-3 on pixels, on screen (so `set_high_contrast` must repaint): the
    frame 2 px of `WindowText`; focused, a 1 px `Window` halo outside a 2 px
    `WindowText` ring. And off again, the authored band."""
    _focus(qtbot, stage, focused)
    _set_hc(stage.canvas, True, PALETTE)
    failures = _band_failures(_on_screen(stage.canvas), _hc_band(focused))
    assert failures == [], f"HC on, focused={focused}: {_report(failures)}"
    _set_hc(stage.canvas, False, PALETTE)
    failures = _band_failures(_on_screen(stage.canvas), _default_band(focused))
    assert failures == [], f"HC off again, focused={focused}: {_report(failures)}"


@pytest.mark.parametrize("role", ["WindowText", "Window"])
def test_high_contrast_with_a_palette_missing_a_canvas_role_raises_missing_palette_role(
    stage: Stage, role: str
) -> None:
    """Contract block 2b: consistent with `resolve` (A-15.3), a missing role
    raises theme.py's `MissingPaletteRole` - never a silent authored value."""
    canvas: Any = stage.canvas
    palette = {k: v for k, v in PALETTE.items() if k != role}
    with pytest.raises(theme_module.MissingPaletteRole):
        canvas.set_high_contrast(True, palette)
    with pytest.raises(theme_module.MissingPaletteRole):
        canvas.set_high_contrast(True, {})


def test_high_contrast_off_ignores_the_palette(stage: Stage) -> None:
    """Contract block 2b: `set_high_contrast(False, palette)` ignores `palette`."""
    canvas = stage.canvas
    _set_hc(canvas, True, PALETTE)
    _set_hc(canvas, False, {})
    assert _properties(canvas) == _default_properties()


# =============================================================================
# AC-4: no marker is dimmed under High Contrast; selection still shows
# =============================================================================


def _opacities(canvas: PageCanvas) -> dict[int, float]:
    return {marker.region.region_id: marker.opacity() for marker in canvas.markers}


def _states(canvas: PageCanvas) -> dict[int, MarkerState]:
    return {marker.region.region_id: marker.state() for marker in canvas.markers}


def test_selecting_then_turning_high_contrast_on_undims_every_marker_and_off_dims_again(
    stage: Stage,
) -> None:
    """AC-4 / A-15.6 "Testable as": with HC off, the non-selected markers are at
    `overlay.dim.opacity` (0.55); with HC on, every marker is at 1.0
    (`HC_OVERRIDE`); off again, 0.55. The selected marker's state is SELECTED
    throughout and every other IDLE - the 3 px / fill / filled badge follow
    from `MarkerState` (MT-016, `test_markers.py`)."""
    canvas = stage.canvas
    canvas.set_link_state(LinkState(selected_region_id=1))
    _settle()
    dimmed = {0: DIM, 1: 1.0, 2: DIM}
    states = {0: MarkerState.IDLE, 1: MarkerState.SELECTED, 2: MarkerState.IDLE}
    assert _opacities(canvas) == dimmed, "precondition: HC off dims the non-selected"
    _set_hc(canvas, True, PALETTE)
    assert _opacities(canvas) == {0: HC_DIM, 1: HC_DIM, 2: HC_DIM}
    assert _states(canvas) == states
    _set_hc(canvas, False, PALETTE)
    assert _opacities(canvas) == dimmed
    assert _states(canvas) == states


def test_a_selection_and_a_hover_made_while_high_contrast_is_on_dim_nothing(
    stage: Stage,
) -> None:
    """AC-4, the other order: `set_link_state` under HC restyles undimmed, and
    selected/hover/idle still differ by state."""
    canvas = stage.canvas
    _set_hc(canvas, True, PALETTE)
    canvas.set_link_state(LinkState(selected_region_id=2, hovered_region_id=0))
    _settle()
    assert _opacities(canvas) == {0: HC_DIM, 1: HC_DIM, 2: HC_DIM}
    assert _states(canvas) == {
        0: MarkerState.HOVER,
        1: MarkerState.IDLE,
        2: MarkerState.SELECTED,
    }


# =============================================================================
# AC-5: the mat check, a pure function of two colours
# =============================================================================


@pytest.mark.parametrize(
    ("a", "b", "ratio"),
    [
        ("#FFFFFF", "#5F5F5F", 6.39),  # high-contrast.md §6
        ("#000000", "#5F5F5F", 3.29),  # high-contrast.md §6
        ("#808080", "#5F5F5F", 1.62),  # contract block 1
        ("#000000", "#FFFFFF", 21.0),  # WCAG 2.x's maximum
        ("#5F5F5F", "#5F5F5F", 1.0),  # equal colours
    ],
)
def test_contrast_ratio_gives_the_documents_numbers_in_either_order(
    a: str, b: str, ratio: float
) -> None:
    """Block 1: WCAG 2.x relative luminance, to 2 d.p., symmetric."""
    contrast_ratio = theme_module.contrast_ratio  # type: ignore[attr-defined]
    assert round(contrast_ratio(a, b), 2) == ratio
    assert round(contrast_ratio(b, a), 2) == ratio


def test_contrast_ratio_accepts_either_case() -> None:
    contrast_ratio = theme_module.contrast_ratio  # type: ignore[attr-defined]
    assert contrast_ratio("#fdfeff", "#5f5f5f") == contrast_ratio("#FDFEFF", "#5F5F5F")


AUTHORED = AUTHORED_FRAME  # what the canvas would pass as `authored` for the frame


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (MID_GREY, AUTHORED),  # 1.62:1 - falls back (A-15.9)
        ("#FFFFFF", "#FFFFFF"),  # 6.39:1
        ("#000000", "#000000"),  # 3.29:1
        (PALETTE["WindowText"], PALETTE["WindowText"]),  # 6.27:1
        ("#fdfeff", "#fdfeff"),  # returned as given, never normalised
    ],
)
def test_mat_safe_falls_back_to_the_authored_value_only_below_3_to_1_against_the_mat(
    value: str, expected: str
) -> None:
    """AC-5 / A-15.9: a fallback, not an exception, and only where it fails."""
    mat_safe = theme_module.mat_safe  # type: ignore[attr-defined]
    assert mat_safe(value, AUTHORED) == expected


@pytest.mark.parametrize(
    ("value", "passes"),
    [("#0F0F0F", True), ("#101010", False), ("#B1B1B1", False), ("#B2B2B2", True)],
)
def test_mat_safe_draws_the_line_at_3_to_1_on_both_sides_of_the_mat(
    value: str, passes: bool
) -> None:
    """A-04's 3.0, from both directions: the greys either side of 3:1 against
    `#5F5F5F` (3.0019 / 2.9799 dark, 2.9778 / 3.0115 light, RED handoff)."""
    contrast_ratio = theme_module.contrast_ratio  # type: ignore[attr-defined]
    mat_safe = theme_module.mat_safe  # type: ignore[attr-defined]
    assert (contrast_ratio(value, MAT) >= THRESHOLD) is passes
    assert mat_safe(value, AUTHORED) == (value if passes else AUTHORED)


def test_mat_safe_checks_against_the_canvas_surround_unless_told_otherwise() -> None:
    """Block 1: `mat` defaults to `TOKENS["color.canvas.surround"]` and is honoured."""
    mat_safe = theme_module.mat_safe  # type: ignore[attr-defined]
    default = inspect.signature(mat_safe).parameters["mat"].default
    assert default == MAT
    assert mat_safe("#FFFFFF", AUTHORED, mat="#FFFFFF") == AUTHORED
    assert mat_safe("#000000", AUTHORED, mat="#FFFFFF") == "#000000"


def test_mat_safe_never_raises_and_returns_one_of_its_two_inputs_for_every_grey() -> None:
    """Block 1: total over `#RRGGBB`, either case."""
    mat_safe = theme_module.mat_safe  # type: ignore[attr-defined]
    wrong = []
    for level in range(256):
        for value in (f"#{level:02X}{level:02X}{level:02X}", f"#{level:02x}{level:02x}{level:02x}"):
            got = mat_safe(value, AUTHORED)
            if got not in (value, AUTHORED):
                wrong.append((value, got))
    assert wrong == []


def test_under_high_contrast_a_mid_grey_window_text_keeps_the_authored_frame_and_ring_only(
    stage: Stage,
) -> None:
    """AC-5 "nothing else changes when it triggers": the frame and ring fall
    back to their authored values, the frame is still 2 px, the halo is still
    the palette's `Window`, and dimming still stops."""
    canvas = stage.canvas
    canvas.set_link_state(LinkState(selected_region_id=0))
    _set_hc(canvas, True, MID_GREY_PALETTE)
    assert _properties(canvas) == {
        "high_contrast": True,
        "frame_width": EMPHASIS,
        "frame_colour": AUTHORED_FRAME,
        "ring_colour": AUTHORED_RING,
        "halo_colour": MID_GREY_PALETTE["Window"],
    }
    assert set(_opacities(canvas).values()) == {HC_DIM}
    band = Band(False, EMPHASIS, AUTHORED_FRAME, AUTHORED_RING, MID_GREY_PALETTE["Window"])
    failures = _band_failures(_on_screen(canvas), band)
    assert failures == [], _report(failures)


# =============================================================================
# AC-6 and contract block 2c: the controller reaches the canvas
# =============================================================================


@pytest.fixture
def real_sheet_restored(qapp: QApplication) -> Iterator[QApplication]:
    """For tests that apply a sheet to the real application: `""` goes back."""
    try:
        yield qapp
    finally:
        qapp.setStyleSheet("")


def _controller(
    qapp: QApplication, on: bool, palette: Mapping[str, str] = PALETTE
) -> tuple[Any, FixedContrastSource]:
    source = FixedContrastSource(on)
    provider: Callable[[], Mapping[str, str]] = lambda: dict(palette)  # noqa: E731
    return theme_module.apply_theme(qapp, source, palette_provider=provider), source


def test_the_controller_palette_is_empty_while_off_and_the_providers_after_an_hc_apply(
    real_sheet_restored: QApplication,
) -> None:
    """Block 2c: `ThemeController.palette` is the mapping the last `apply()` read."""
    qapp = real_sheet_restored
    idle = theme_module.ThemeController(qapp, FixedContrastSource(True))
    assert dict(idle.palette) == {}, "never applied"  # type: ignore[attr-defined]
    controller, source = _controller(qapp, False)
    assert dict(controller.palette) == {}
    source.set_value(True)
    assert dict(controller.palette) == PALETTE
    source.set_value(False)
    assert dict(controller.palette) == {}


@pytest.mark.parametrize("on", [False, True], ids=["off", "on"])
def test_follow_theme_applies_the_controllers_current_mode_at_once(
    qtbot: Any, real_sheet_restored: QApplication, on: bool
) -> None:
    """Block 2c: `follow_theme` applies the controller's mode NOW."""
    controller, _ = _controller(real_sheet_restored, on)
    window = Workspace()
    qtbot.addWidget(window)
    window.follow_theme(controller)  # type: ignore[attr-defined]
    expected = _hc_properties() if on else _default_properties()
    assert _properties(window.page_canvas) == expected


def _pages_folder(root: Path, size: QSize) -> Path:
    folder = root / "chapter"
    folder.mkdir()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    assert _page_image(size).save(buffer, "PNG")
    (folder / "page 1.png").write_bytes(bytes(buffer.data().data()))
    buffer.close()
    return folder


def _project_folder(root: Path, size: QSize) -> Path:
    folder = _pages_folder(root, size)
    page = Page(
        ordinal=0, filename="page 1.png", width=size.width(), height=size.height(), sha256="0" * 64
    )
    chapter = Chapter(source_dir=folder, pages=(page,))
    with create_project(chapter, root / "chapter.mtproj"):
        pass
    return folder


#: AC-6: a page large enough that zoom 2.0 leaves both scroll bars a range.
WORKSPACE_PAGE = QSize(800, 600)
WINDOW = QSize(1100, 720)
WORKSPACE_REGIONS = (
    OrderedRegion(region_id=0, polygon=_ring(60, 60, 120, 80)),
    OrderedRegion(region_id=1, polygon=_ring(300, 200, 100, 120)),
    OrderedRegion(region_id=2, polygon=_ring(520, 380, 140, 90)),
)


def _workspace_snapshot(window: Workspace) -> dict[str, object]:
    canvas = window.page_canvas
    return {
        "selected_region_id": window.link.state.selected_region_id,
        "canvas link state": replace(canvas._link_state),
        "zoom": canvas.zoom(),
        "transform": _transform(canvas),
        "horizontal scroll": canvas.horizontalScrollBar().value(),
        "vertical scroll": canvas.verticalScrollBar().value(),
        "marker states": _states(canvas),
    }


def test_a_live_mode_change_on_a_shown_page_repaints_the_band_and_keeps_zoom_pan_and_selection(
    qtbot: Any,
    real_sheet_restored: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6 / A-15.10 (canvas half): a Workspace following a controller, a page
    with regions, zoom 2.0, a pan and region 1 selected, the canvas focused.
    Each `set_value` repaints the ring and dimming on screen and leaves zoom,
    both scroll values and the selection exactly as they were."""
    monkeypatch.setattr(app_module, "_theme", None)  # no stale controller from main()
    controller, source = _controller(real_sheet_restored, False)
    window = app_module.build_window([str(_project_folder(tmp_path, WORKSPACE_PAGE))])
    assert isinstance(window, Workspace)
    qtbot.addWidget(window)
    window.follow_theme(controller)  # type: ignore[attr-defined]
    window.resize(WINDOW)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.set_regions(
        WORKSPACE_REGIONS,
        [f"ja {r.region_id}" for r in WORKSPACE_REGIONS],
        [f"en {r.region_id}" for r in WORKSPACE_REGIONS],
    )
    _settle()
    window.link.select(1)
    canvas = window.page_canvas
    canvas.set_zoom(2.0)
    horizontal, vertical = canvas.horizontalScrollBar(), canvas.verticalScrollBar()
    horizontal.setValue(horizontal.maximum() // 3)
    vertical.setValue(vertical.maximum() // 3)
    canvas.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(canvas.hasFocus)
    _settle()

    before = _workspace_snapshot(window)
    assert before["selected_region_id"] == 1, before
    assert before["zoom"] == 2.0, before
    assert before["horizontal scroll"] > 0 and before["vertical scroll"] > 0, before
    assert _opacities(canvas) == {0: DIM, 1: 1.0, 2: DIM}, "precondition: dimmed"

    for on in (True, False):
        source.set_value(on)
        _settle()
        expected = _hc_properties() if on else _default_properties()
        assert _properties(canvas) == expected, f"after set_value({on})"
        band = _hc_band(True) if on else _default_band(True)
        failures = _band_failures(_on_screen(canvas), band)
        assert failures == [], f"after set_value({on}), on screen: {_report(failures)}"
        assert _opacities(canvas) == ({0: 1.0, 1: 1.0, 2: 1.0} if on else {0: DIM, 1: 1.0, 2: DIM})
        after = _workspace_snapshot(window)
        lost = {k: (before[k], after[k]) for k in before if after[k] != before[k]}
        assert lost == {}, f"set_value({on}) lost (before, after): {lost}"


def test_opening_a_project_folder_hands_the_running_theme_controller_to_the_canvas(
    qtbot: Any,
    real_sheet_restored: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Block 2c: `open_folder` (reached through `build_window`, so the MT-072
    fixtures close the window and its project) calls `follow_theme(_theme)`:
    the canvas starts in the controller's mode and follows its next change."""
    controller, source = _controller(real_sheet_restored, True)
    monkeypatch.setattr(app_module, "_theme", controller)
    window = app_module.build_window([str(_project_folder(tmp_path, WORKSPACE_PAGE))])
    assert isinstance(window, Workspace)
    qtbot.addWidget(window)
    assert _properties(window.page_canvas) == _hc_properties()
    source.set_value(False)
    assert _properties(window.page_canvas) == _default_properties()


def test_opening_a_project_folder_with_no_running_theme_leaves_the_canvas_in_the_default(
    qtbot: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Block 2c: `follow_theme` only `when _theme is not None`."""
    monkeypatch.setattr(app_module, "_theme", None)
    window = app_module.build_window([str(_project_folder(tmp_path, WORKSPACE_PAGE))])
    assert isinstance(window, Workspace)
    qtbot.addWidget(window)
    assert _properties(window.page_canvas) == _default_properties()
