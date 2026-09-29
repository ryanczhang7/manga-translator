"""MT-050: Up / Down / Home / End on the canvas move the selection.

`components.md` §4.7 (normative) binds `Up`/`Down` ("previous / next ordinal on
this page") and `Home`/`End` ("ordinal 1 / the last ordinal") in EITHER pane;
`accessibility.md` A-07 makes Up/Down a binding that must never regress, and
A-05 names it the guaranteed way to reach a bubble too small to click.

Every key is synthesised with `QTest.keyClick` on the widget that HAS keyboard
focus (A-07 "Testable as"), and focus is read with `QApplication.focusWidget()`
in an active window (MT-016 quirk 6; `_open` activates and waits).

Oracle partition (story `## Contract`):
- AC-1, AC-2, AC-3, AC-4, AC-6 are MECHANICAL: exact transitions, pinned.
- AC-5 is SETTLED (§4.5): the pan is `PageCanvas.reveal`'s, read out -
  24 px (`space.6`) margin, m11/m22 untouched, and EXACT equality of both
  scroll values and the whole transform when the region is already visible.

The trap AC-5 exists for, measured in RED offscreen (PySide6, story Handoff):
`QGraphicsView`'s default key handling scrolls the view by one scroll-bar
single step on Up/Down (vertical delta -31 / +31 px at the workspace minimum
size, at zoom 1.0 and 2.0), even with both scroll bars `AlwaysOff`. Home/End
produce a delta of 0 by default, so the fall-through control has teeth on
Up/Down only; every AC-5 "already visible" case below runs Up and Down.

Helpers and fixtures are copied from `tests/ui/test_link_workspace.py`
(as `tests/ui/test_hover_leave.py` does), so this file stands alone.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mangatl.domain.page import Chapter, Page
from mangatl.store.project import Project, create_project
from mangatl.ui import link as link_module
from mangatl.ui.canvas import FAILED, PageCanvas
from mangatl.ui.link import SELECTION_MARGIN_PX, OrderedRegion
from mangatl.ui.workspace import Workspace

# --- Settled numbers, read out ------------------------------------------------
MARGIN = SELECTION_MARGIN_PX  # components.md §4.5 `space.6`
assert MARGIN == 24, "components.md §4.5: space.6 is 24 px"

# --- Fixture geometry (copied from tests/ui/test_link_workspace.py) -----------
PAGE = QSize(3000, 4000)
WINDOW = QSize(1100, 720)  # the workspace minimum; the canvas shows part of the page
GRID_COLUMNS = 5
REGION_W, REGION_H = 120, 90
MANY = 40
FEW = 5
SHOWN_PAGE = 1  # 0-based: "Page 2 of 3"; it has no stored regions
PAGES = ("001.png", "002.png", "003.png")
JUNK_PAGE_ORDINAL = 2  # 003.png does not decode

UP, DOWN, HOME, END = Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End
STEP_OF = {UP: "previous", DOWN: "next", HOME: "first", END: "last"}
KEY_IDS = {UP: "Up", DOWN: "Down", HOME: "Home", END: "End"}


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _png_bytes(size: QSize) -> bytes:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(128, 128, 128))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


@pytest.fixture(scope="session")
def page_png() -> bytes:
    """One 3000 x 4000 PNG, encoded once for the whole session."""
    return _png_bytes(PAGE)


@pytest.fixture
def project(tmp_path: Path, page_png: bytes) -> Iterator[Project]:
    """Three pages: two genuine 3000 x 4000 PNGs and one junk-bytes `*.png`."""
    source = tmp_path / "chapter"
    source.mkdir()
    for ordinal, name in enumerate(PAGES):
        payload = b"not a PNG at all" if ordinal == JUNK_PAGE_ORDINAL else page_png
        (source / name).write_bytes(payload)
    chapter = Chapter(
        source_dir=source,
        pages=tuple(
            Page(
                ordinal=i,
                filename=name,
                width=PAGE.width(),
                height=PAGE.height(),
                sha256=f"{i}" * 64,
            )
            for i, name in enumerate(PAGES)
        ),
    )
    with create_project(chapter, tmp_path / "chapter.mtproj") as opened:
        yield opened


@pytest.fixture
def recorded_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """Replace `mangatl.ui.link.QAccessible` (imported BY NAME) with a recorder
    of (event type, event object). The real Event enum is kept."""
    posted: list[tuple[Any, Any]] = []
    stand_in = SimpleNamespace(
        Event=QAccessible.Event,
        updateAccessibility=lambda event: posted.append((event.type(), event.object())),
    )
    monkeypatch.setattr(link_module, "QAccessible", stand_in)
    return posted


def _open(qtbot) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.resize(WINDOW)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()
    return window


def _on_page(qtbot, project: Project, ordinal: int = SHOWN_PAGE) -> Workspace:  # type: ignore[no-untyped-def]
    window = _open(qtbot)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(ordinal)
    _settle()
    return window


def _grid(count: int) -> list[OrderedRegion]:
    """`count` 120 x 90 regions on a 500 x 450 grid, >= 200 px from every edge."""
    regions = []
    for region_id in range(count):
        row, col = divmod(region_id, GRID_COLUMNS)
        x, y = 300 + col * 500, 300 + row * 450
        regions.append(OrderedRegion(region_id=region_id, polygon=_ring(x, y, REGION_W, REGION_H)))
    return regions


def _cluster(count: int) -> list[OrderedRegion]:
    """`count` 60 x 40 regions packed 100 px apart (3 per row) around scene
    (1300, 1500): all of them fit in the viewport at once, at zoom 1 and 2, with
    scroll range on every side, so a stray scroll step has room to show."""
    regions = []
    for region_id in range(count):
        row, col = divmod(region_id, 3)
        x, y = 1300 + col * 100, 1500 + row * 100
        regions.append(OrderedRegion(region_id=region_id, polygon=_ring(x, y, 60, 40)))
    return regions


def _ring(x: int, y: int, w: int, h: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y))


def _populate(window: Workspace, regions: Sequence[OrderedRegion]) -> None:
    window.set_regions(
        regions,
        [f"ja {r.region_id}" for r in regions],
        [f"en {r.region_id}" for r in regions],
    )
    _settle()


def _canvas_view(canvas: PageCanvas) -> tuple[Any, ...]:
    """Everything that says where the canvas is looking: scroll and transform."""
    t = canvas.transform()
    return (
        canvas.horizontalScrollBar().value(),
        canvas.verticalScrollBar().value(),
        (t.m11(), t.m12(), t.m13(), t.m21(), t.m22(), t.m23(), t.m31(), t.m32(), t.m33()),
    )


def _mapped(canvas: PageCanvas, region: OrderedRegion) -> QRect:
    return canvas.mapFromScene(region.bounds()).boundingRect()


def _place(canvas: PageCanvas, region: OrderedRegion, left: int, top: int) -> None:
    """Scroll so the region's mapped rect starts at (left, top) in the viewport."""
    zoom = canvas.transform().m11()
    bounds = region.bounds()
    canvas.horizontalScrollBar().setValue(round(zoom * bounds.left()) - left)
    canvas.verticalScrollBar().setValue(round(zoom * bounds.top()) - top)
    _settle()
    assert _mapped(canvas, region).topLeft() == QPoint(left, top), "fixture: scroll range"


def _select(window: Workspace, region_id: int) -> None:
    window.link.select(region_id)
    _settle()
    assert window.link.state.selected_region_id == region_id, "fixture: selection"


def _focus_canvas(window: Workspace) -> PageCanvas:
    canvas = window.page_canvas
    canvas.setFocus(Qt.FocusReason.OtherFocusReason)
    _settle()
    assert QApplication.focusWidget() is canvas, "fixture: canvas does not have focus"
    return canvas


def _press(key: Qt.Key, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    """Deliver `key` to whichever widget has keyboard focus right now."""
    widget = QApplication.focusWidget()
    assert widget is not None, "fixture: nothing has keyboard focus"
    QTest.keyClick(widget, key, modifier)
    _settle()


def _announcement(ordinal: int, total: int) -> str:
    return f"Bubble {ordinal} of {total} selected. Page {SHOWN_PAGE + 1} of {len(PAGES)}."


# =============================================================================
# Contract - PageCanvas reports the step and does nothing else
# =============================================================================


@pytest.fixture
def bare_canvas(qtbot) -> PageCanvas:  # type: ignore[no-untyped-def]
    """A PageCanvas alone, showing a 2000 x 2000 page scrolled to the middle."""
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 500)
    image = QImage(QSize(2000, 2000), QImage.Format.Format_RGB32)
    image.fill(QColor(128, 128, 128))
    canvas.set_page(QPixmap.fromImage(image))
    with qtbot.waitExposed(canvas):
        canvas.show()
    canvas.horizontalScrollBar().setValue(700)
    canvas.verticalScrollBar().setValue(700)
    _settle()
    return canvas


@pytest.mark.parametrize(
    "modifier",
    [Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier],
    ids=["main", "keypad"],
)
@pytest.mark.parametrize("key", [UP, DOWN, HOME, END], ids=lambda k: KEY_IDS[k])
def test_the_canvas_reports_each_navigation_key_as_exactly_one_selection_step(
    bare_canvas: PageCanvas,
    key: Qt.Key,
    modifier: Qt.KeyboardModifier,
) -> None:
    steps: list[str] = []
    bare_canvas.selectionStepRequested.connect(steps.append)

    QTest.keyClick(bare_canvas, key, modifier)
    _settle()

    assert steps == [STEP_OF[key]]


@pytest.mark.parametrize(
    ("key", "modifier"),
    [
        (UP, Qt.KeyboardModifier.ShiftModifier),
        (DOWN, Qt.KeyboardModifier.ControlModifier),
        (HOME, Qt.KeyboardModifier.ControlModifier),
        (END, Qt.KeyboardModifier.ShiftModifier),
        (UP, Qt.KeyboardModifier.AltModifier),
        (Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
    ],
    ids=["Shift+Up", "Ctrl+Down", "Ctrl+Home", "Shift+End", "Alt+Up", "Left", "Right", "Return"],
)
def test_modified_navigation_keys_and_other_keys_report_no_selection_step(
    bare_canvas: PageCanvas,
    key: Qt.Key,
    modifier: Qt.KeyboardModifier,
) -> None:
    # Out of scope: modified variants are unassigned (§4.1 has no multi-select);
    # Left/Right are not bound by §4.7; Enter is editRequested (MT-016).
    steps: list[str] = []
    bare_canvas.selectionStepRequested.connect(steps.append)

    QTest.keyClick(bare_canvas, key, modifier)
    _settle()

    assert steps == []


@pytest.mark.parametrize("key", [UP, DOWN], ids=lambda k: KEY_IDS[k])
def test_a_navigation_key_on_the_canvas_never_scrolls_the_view_itself(
    bare_canvas: PageCanvas,
    key: Qt.Key,
) -> None:
    # Contract: the four keys NEVER reach QGraphicsView.keyPressEvent. Measured
    # in RED on this 600 x 500 canvas: the default handling scrolls the vertical
    # value by -24 / +24 on Up / Down (one single step). Home / End scroll 0 by
    # default, so a case for them could not discriminate and is not written.
    before = _canvas_view(bare_canvas)

    QTest.keyClick(bare_canvas, key)
    _settle()

    assert _canvas_view(bare_canvas) == before, "the canvas scrolled on a selection key"


# =============================================================================
# AC-1 - Down / Up move to the next / previous ordinal, conveyed as any selection
# =============================================================================


@pytest.mark.parametrize(("key", "expected"), [(DOWN, 3), (UP, 1)], ids=["Down", "Up"])
def test_down_and_up_on_the_canvas_select_the_next_and_previous_ordinal_and_announce_it(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    recorded_alerts: list[tuple[Any, Any]],
    key: Qt.Key,
    expected: int,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(FEW))
    _select(window, 2)  # ordinal 3 of 5: 1 < k < n
    _focus_canvas(window)
    recorded_alerts.clear()

    _press(key)

    assert window.link.state.selected_region_id == expected
    assert window.translation_column.list.currentRow() == expected
    live = window.live_region
    assert live.accessibleName() == _announcement(expected + 1, FEW)
    assert recorded_alerts == [(QAccessible.Event.Alert, live)]


def test_repeated_down_then_up_on_the_canvas_walks_the_ordinals_one_at_a_time(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(FEW))
    _focus_canvas(window)

    walked = []
    for key in (DOWN, DOWN, DOWN, UP, UP):
        _press(key)
        walked.append(window.link.state.selected_region_id)

    assert walked == [1, 2, 3, 2, 1]


# =============================================================================
# AC-2 - no wrap: Up at ordinal 1 and Down at the last change and say nothing
# =============================================================================
# Each test first REACHES the end by the key (red until the canvas handles it),
# then presses once more. The clamp itself is only discriminated once a handler
# exists: GATES' mutation 3 (Up at ordinal 1 wraps) is what earns it.


@pytest.mark.parametrize(
    ("start", "key", "end"), [(1, UP, 0), (FEW - 2, DOWN, FEW - 1)], ids=["Up", "Down"]
)
def test_the_canvas_does_not_wrap_past_the_first_or_last_ordinal_and_announces_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    recorded_alerts: list[tuple[Any, Any]],
    start: int,
    key: Qt.Key,
    end: int,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(FEW))
    _select(window, start)
    _focus_canvas(window)

    _press(key)
    assert window.link.state.selected_region_id == end, "the key did not reach the end"
    live_text = window.live_region.accessibleName()
    recorded_alerts.clear()

    _press(key)

    assert window.link.state.selected_region_id == end, "the canvas wrapped or moved"
    assert window.translation_column.list.currentRow() == end
    assert recorded_alerts == [], "a clamped step announced something"
    assert window.live_region.accessibleName() == live_text


# =============================================================================
# AC-3 - Home / End select ordinal 1 / the last, on the canvas and in the column
# =============================================================================


@pytest.mark.parametrize(
    ("key", "start", "expected"),
    [(HOME, 2, 0), (HOME, FEW - 1, 0), (END, 2, FEW - 1), (END, 0, FEW - 1)],
    ids=["Home-from-middle", "Home-from-last", "End-from-middle", "End-from-first"],
)
def test_home_and_end_on_the_canvas_select_the_first_and_the_last_ordinal(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    recorded_alerts: list[tuple[Any, Any]],
    key: Qt.Key,
    start: int,
    expected: int,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(FEW))
    _select(window, start)
    _focus_canvas(window)
    recorded_alerts.clear()

    _press(key)

    assert window.link.state.selected_region_id == expected
    assert window.translation_column.list.currentRow() == expected
    assert window.live_region.accessibleName() == _announcement(expected + 1, FEW)
    assert len(recorded_alerts) == 1


@pytest.mark.parametrize(("key", "expected"), [(HOME, 0), (END, FEW - 1)], ids=["Home", "End"])
def test_home_and_end_in_the_translation_column_select_the_first_and_the_last_ordinal(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    key: Qt.Key,
    expected: int,
) -> None:
    # Passes on arrival (QListWidget moves its current row; _on_current_row_changed
    # selects it). Earned in RED by mutating _on_current_row_changed - see Handoff.
    window = _on_page(qtbot, project)
    _populate(window, _grid(FEW))
    _select(window, 2)
    lst = window.translation_column.list
    lst.setFocus(Qt.FocusReason.OtherFocusReason)
    _settle()
    assert QApplication.focusWidget() is lst, "fixture: the column does not have focus"

    _press(key)

    assert window.link.state.selected_region_id == expected
    assert lst.currentRow() == expected
    assert window.page_canvas.markers[expected].region.region_id == expected


# =============================================================================
# AC-4 - focus stays on the canvas
# =============================================================================


@pytest.mark.parametrize(
    ("key", "expected"),
    [(DOWN, 3), (UP, 1), (HOME, 0), (END, FEW - 1)],
    ids=["Down", "Up", "Home", "End"],
)
def test_after_a_key_moves_the_selection_keyboard_focus_is_still_on_the_canvas(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    key: Qt.Key,
    expected: int,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(FEW))
    _select(window, 2)
    canvas = _focus_canvas(window)

    _press(key)

    assert window.link.state.selected_region_id == expected, "the key did not select"
    assert QApplication.focusWidget() is canvas, QApplication.focusWidget()


def test_the_canvas_keeps_focus_through_a_run_of_keys_so_the_user_can_keep_pressing(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _on_page(qtbot, project)
    _populate(window, _grid(FEW))
    canvas = _focus_canvas(window)

    for key in (END, UP, UP, HOME, DOWN):
        _press(key)  # delivered to the focused widget: the canvas only if it kept focus

    assert window.link.state.selected_region_id == 1
    assert QApplication.focusWidget() is canvas


# =============================================================================
# AC-5 - the pan is reveal's: none when visible (EXACT), minimum with 24 px else
# =============================================================================

CLUSTER = 6
CLUSTER_START = 2  # ordinal 3 of 6: Up, Down, Home and End all move from here


@pytest.mark.parametrize("zoom", [1.0, 2.0])
@pytest.mark.parametrize(
    ("key", "expected"),
    [(DOWN, 3), (UP, 1), (HOME, 0), (END, CLUSTER - 1)],
    ids=["Down", "Up", "Home", "End"],
)
def test_a_key_that_selects_an_already_visible_region_leaves_the_view_exactly_as_it_was(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    key: Qt.Key,
    expected: int,
    zoom: float,
) -> None:
    # The control (select, then QGraphicsView.keyPressEvent) moves the vertical
    # scroll by -31 / +31 on Up / Down - measured in RED - and must fail here.
    window = _on_page(qtbot, project)
    regions = _cluster(CLUSTER)
    _populate(window, regions)
    canvas = window.page_canvas
    canvas.set_zoom(zoom)
    _settle()
    _select(window, CLUSTER_START)
    _place(canvas, regions[0], 60, 100)  # the whole cluster well inside, room all round
    viewport = canvas.viewport().rect()
    assert all(viewport.contains(_mapped(canvas, r)) for r in regions), "fixture: not visible"
    vertical = canvas.verticalScrollBar()
    assert 0 < vertical.value() < vertical.maximum(), "fixture: no room for a stray scroll"
    _focus_canvas(window)
    before = _canvas_view(canvas)

    _press(key)

    assert window.link.state.selected_region_id == expected, "the key did not select"
    assert _canvas_view(canvas) == before, "the view moved for a region already visible"


def _assert_contained_with_margin(canvas: PageCanvas, region: OrderedRegion) -> None:
    m = _mapped(canvas, region)
    vw, vh = canvas.viewport().width(), canvas.viewport().height()
    assert m.left() >= MARGIN, m
    assert m.top() >= MARGIN, m
    assert m.right() <= vw - 1 - MARGIN, (m, vw)
    assert m.bottom() <= vh - 1 - MARGIN, (m, vh)


@pytest.mark.parametrize("zoom", [1.0, 2.0])
@pytest.mark.parametrize(
    ("key", "start", "expected"),
    [(DOWN, 4, 5), (UP, 5, 4), (HOME, MANY - 1, 0), (END, 0, MANY - 1)],
    ids=["Down", "Up", "Home", "End"],
)
def test_a_key_that_selects_an_off_screen_region_pans_it_in_as_reveal_does_without_zooming(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    key: Qt.Key,
    start: int,
    expected: int,
    zoom: float,
) -> None:
    window = _on_page(qtbot, project)
    regions = _grid(MANY)
    _populate(window, regions)
    canvas = window.page_canvas
    canvas.set_zoom(zoom)
    _settle()
    _select(window, start)  # reveal brings `start` in; `expected` is then off-screen
    target = regions[expected]
    assert not canvas.viewport().rect().intersects(_mapped(canvas, target)), "fixture: visible"
    _focus_canvas(window)
    start_view = _canvas_view(canvas)
    m11, m22 = canvas.transform().m11(), canvas.transform().m22()

    _press(key)

    assert window.link.state.selected_region_id == expected, "the key did not select"
    assert (canvas.transform().m11(), canvas.transform().m22()) == (m11, m22), "selection zoomed"
    _assert_contained_with_margin(canvas, target)
    after_key = _canvas_view(canvas)

    # "Where MT-016's reveal puts it": the same start, revealed directly.
    canvas.horizontalScrollBar().setValue(start_view[0])
    canvas.verticalScrollBar().setValue(start_view[1])
    _settle()
    assert _canvas_view(canvas) == start_view, "fixture: could not restore the start view"
    canvas.reveal(expected)
    _settle()
    assert after_key == _canvas_view(canvas), "the key's pan is not reveal's pan"


# =============================================================================
# AC-6 - a page with no regions: nothing selected, nothing said, no exception
# =============================================================================


@pytest.mark.parametrize(
    "ordinal", [SHOWN_PAGE, JUNK_PAGE_ORDINAL], ids=["empty-page", "failed-page"]
)
def test_navigation_keys_on_a_page_with_no_regions_select_and_announce_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    recorded_alerts: list[tuple[Any, Any]],
    ordinal: int,
) -> None:
    window = _on_page(qtbot, project, ordinal)
    if ordinal == JUNK_PAGE_ORDINAL:
        assert window.page_canvas.state() == FAILED, "fixture: the junk page decoded"
    assert window.page_canvas.markers == [], "fixture: the page has regions"
    canvas = _focus_canvas(window)
    # Contract: the canvas still reports the step; Workspace ignores it. Recording
    # it proves each key reached the handler rather than passing vacuously.
    steps: list[str] = []
    canvas.selectionStepRequested.connect(steps.append)
    recorded_alerts.clear()

    for key in (UP, DOWN, HOME, END):
        _press(key)  # pytest-qt fails the test on an exception raised in the handler

    assert steps == ["previous", "next", "first", "last"]
    assert window.link.state.selected_region_id is None
    assert window.translation_column.list.currentRow() == -1
    assert recorded_alerts == []
