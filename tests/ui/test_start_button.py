"""MT-059 C-2 / D-1: the chapter summary's Start button.

`ChapterSummary` gains a second button outside its scroll area, `summary-start`,
before `summary-choose`, with the new signal `start_requested`. Its text is
**settled** (AC-1, `components.md` §2): `Start run`, or `Start run anyway`
exactly when `summary.cost_estimate.over_budget` (MT-058's estimate, whose
boundary is read from the domain - 33 pages fit $2.00 at $0.06, 34 do not).

The rest is D-1, read out: object name, the `variant="primary"` property,
accessible name = text, placement (one row at the scroll area's foot,
left-aligned, start first, `space.2` apart, `space.4` below the scroll area),
focus order by Tab and Shift+Tab (never by `findChildren` order, which is
construction order), activation by click / Space / Return / Enter once each,
and the `primary` paint under the packaged theme, measured in pixels as
`test_app_theme_paint.py` measures every other part (MT-061's method).

**Paint, measured in RED.** The packaged `theme.qss` has no primary rule yet,
so the button paints as a secondary one (ground `color.surface.raised`). A
scratch sheet holding D-1's candidate rule was measured with these same
instruments: ground `#4cc2ff` (accent.base), ink `#06202b` (text.on-accent),
hover `#7ad3ff` (via `QTest.mouseMove`; `WA_UnderMouse` alone does not repaint
:hover), pressed `#2fa8e8` (`setDown(True)`), focus band `#ffffff` x
`focus.width` px on the left and top, and the transparent band at rest showing
the window's `#1c1c1c` (surface.base). Recorded in the story's `## Handoff`.

**RED:** the summary has no Start button, so every test here fails on
`findChild(QPushButton, "summary-start")` returning `None`, or on the missing
`start_requested` attribute.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import mangatl.domain.budget as budget
from mangatl import app as app_module
from mangatl.domain.page import Chapter, Page
from mangatl.ui import tokens_gen
from mangatl.ui.main_window import MainWindow
from mangatl.ui.summary import ChapterSummary

T = tokens_gen.TOKENS
START = "Start run"
START_ANYWAY = "Start run anyway"
CHOOSE = "Choose a different folder"


def _last_page_inside_budget() -> int:
    """MT-058 AC-3's boundary, read from the two constants (33 today)."""
    return budget.DEFAULT_CEILING.micro() // budget.BOOTSTRAP_PAGE_ESTIMATE.micro()


def _chapter(count: int, folder: Path = Path("C:/manga/Chapter 12")) -> Chapter:
    return Chapter(
        source_dir=folder,
        pages=tuple(
            Page(ordinal=i, filename=f"p{i + 1}.png", width=60, height=80, sha256=f"{i % 10}" * 64)
            for i in range(count)
        ),
    )


def _bare(qtbot, count: int) -> ChapterSummary:  # type: ignore[no-untyped-def]
    summary = ChapterSummary(_chapter(count))
    qtbot.addWidget(summary)
    return summary


def _shown(qtbot, count: int = 2) -> ChapterSummary:  # type: ignore[no-untyped-def]
    summary = _bare(qtbot, count)
    summary.resize(700, 500)
    with qtbot.waitExposed(summary):
        summary.show()
    summary.activateWindow()
    qtbot.waitUntil(summary.isActiveWindow)
    return summary


def _start(summary: QWidget) -> QPushButton:
    button = summary.findChild(QPushButton, "summary-start")
    assert button is not None, "the summary has no QPushButton named 'summary-start'"
    return button


def _choose(summary: QWidget) -> QPushButton:
    button = summary.findChild(QPushButton, "summary-choose")
    assert button is not None
    return button


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# The text: Start run, or Start run anyway when the estimate is over budget
# =============================================================================


def test_the_boundary_is_33_pages_at_today_s_rates() -> None:
    assert _last_page_inside_budget() == 33


@pytest.mark.parametrize(
    ("offset", "text"),
    [(0, START), (1, START_ANYWAY)],
    ids=["33-inside", "34-over"],
)
def test_the_start_button_reads_start_run_unless_the_estimate_is_over_budget(
    qtbot,  # type: ignore[no-untyped-def]
    offset: int,
    text: str,
) -> None:
    summary = _bare(qtbot, _last_page_inside_budget() + offset)

    button = _start(summary)
    assert summary.cost_estimate.over_budget is bool(offset), "precondition: MT-058's estimate"
    assert button.text() == text
    assert button.accessibleName() == text


def test_a_one_page_chapter_reads_start_run(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _bare(qtbot, 1)

    assert _start(summary).text() == START


def test_the_start_button_is_the_primary_variant(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _bare(qtbot, 2)

    assert _start(summary).property("variant") == "primary"
    assert _choose(summary).property("variant") in (None, "", "secondary")


# =============================================================================
# Placement: one row at the scroll area's foot, start first
# =============================================================================


def test_both_buttons_sit_outside_the_scroll_area_in_one_row_start_first(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _shown(qtbot, 40)
    _settle()
    scroll = summary.scroll_area
    start, choose = _start(summary), _choose(summary)

    for button in (start, choose):
        assert summary.isAncestorOf(button)
        assert not scroll.isAncestorOf(button), f"{button.objectName()} scrolls with the content"
    s, c, area = start.geometry(), choose.geometry(), scroll.geometry()
    assert s.left() == area.left(), f"start is not left-aligned: {s.left()} vs {area.left()}"
    assert c.left() - s.right() - 1 == tokens_gen.SPACE_S2, (
        f"gap between the buttons is {c.left() - s.right() - 1}, not space.2"
    )
    assert abs(s.center().y() - c.center().y()) <= 1, "the buttons are not in one row"
    top = min(s.top(), c.top())
    assert top - area.bottom() - 1 == tokens_gen.SPACE_S4, (
        f"the row is {top - area.bottom() - 1} px below the scroll area, not space.4"
    )


# =============================================================================
# Focus order: scroll area -> Start run -> Choose a different folder
# =============================================================================


def _tab(qtbot, backwards: bool = False) -> QWidget | None:  # type: ignore[no-untyped-def]
    focused = QApplication.focusWidget()
    assert focused is not None, "nothing has focus to tab from"
    QTest.keyClick(
        focused,
        Qt.Key.Key_Backtab if backwards else Qt.Key.Key_Tab,
        Qt.KeyboardModifier.ShiftModifier if backwards else Qt.KeyboardModifier.NoModifier,
    )
    _settle()
    return QApplication.focusWidget()


def test_tab_goes_scroll_area_then_start_then_choose_and_shift_tab_reverses(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _shown(qtbot)
    scroll, start, choose = summary.scroll_area, _start(summary), _choose(summary)
    scroll.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(scroll.hasFocus)

    forward = [_tab(qtbot), _tab(qtbot)]
    backward = [_tab(qtbot, backwards=True), _tab(qtbot, backwards=True)]

    names = [w.objectName() if w else None for w in forward + backward]
    assert forward == [start, choose], f"Tab order: {names[:2]}"
    assert backward == [start, scroll], f"Shift+Tab order: {names[2:]}"


def test_the_summary_still_opens_with_focus_on_its_scroll_area(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    window = MainWindow(open_folder=app_module.open_folder)
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)

    window.show_summary(_chapter(2))
    _settle()

    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary)
    assert summary.scroll_area.hasFocus(), f"focus is on {QApplication.focusWidget()!r}"
    _start(summary)


# =============================================================================
# Activation: start_requested once per click, Space, Return, Enter
# =============================================================================


def _activate(qtbot, button: QPushButton, how: str) -> None:  # type: ignore[no-untyped-def]
    if how == "click":
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    else:
        button.setFocus(Qt.FocusReason.OtherFocusReason)
        qtbot.waitUntil(button.hasFocus)
        key = {"Return": Qt.Key.Key_Return, "Enter": Qt.Key.Key_Enter, "Space": Qt.Key.Key_Space}
        QTest.keyClick(button, key[how])
    _settle()


@pytest.mark.parametrize("how", ["click", "Return", "Enter", "Space"])
def test_start_emits_start_requested_once_per_activation_and_nothing_else(
    qtbot,  # type: ignore[no-untyped-def]
    how: str,
) -> None:
    summary = _shown(qtbot)
    started: list[int] = []
    chose: list[int] = []
    summary.start_requested.connect(lambda: started.append(1))
    summary.choose_other.connect(lambda: chose.append(1))

    _activate(qtbot, _start(summary), how)

    assert (started, chose) == ([1], []), f"{how}: start_requested {started}, choose_other {chose}"


def test_choose_a_different_folder_does_not_request_a_start(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _shown(qtbot)
    started: list[int] = []
    summary.start_requested.connect(lambda: started.append(1))

    _activate(qtbot, _choose(summary), "click")

    assert started == []


# =============================================================================
# Paint: the primary variant under the packaged theme
# =============================================================================


def _colour(name: str) -> str:
    return QColor(T[name]).name()


@pytest.fixture
def themed(qapp: QApplication) -> Iterator[None]:
    """The packaged theme on the real application; always put `""` back."""
    qapp.setStyleSheet(files("mangatl.ui").joinpath("theme.qss").read_text(encoding="utf-8"))
    try:
        yield
    finally:
        qapp.setStyleSheet("")


def _png() -> bytes:
    image = QImage(QSize(60, 80), QImage.Format.Format_RGB32)
    image.fill(QColor(T["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def _themed_summary(qtbot, root: Path) -> tuple[QWidget, ChapterSummary]:  # type: ignore[no-untyped-def]
    folder = root / "Vol 1"
    folder.mkdir()
    png = _png()
    for name in ("p1.png", "p2.png"):
        (folder / name).write_bytes(png)
    window = app_module.build_window([str(folder)])
    qtbot.addWidget(window)
    window.resize(1100, 720)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary)
    QTest.mouseMove(summary.scroll_area, summary.scroll_area.rect().center())
    _settle()
    return window, summary


def _grab(widget: QWidget) -> QImage:
    window = widget.window()
    origin = widget.mapTo(window, QPoint(0, 0))
    return window.grab(QRect(origin, widget.size())).toImage()


def _at(image: QImage, x: int, y: int) -> str:
    return image.pixelColor(x, y).name()


def _ground(image: QImage) -> str:
    """Inside the band, left of the centred label."""
    return _at(image, int(T["focus.width"]) + 3, image.height() // 2)


def _ink(image: QImage) -> str:
    """The most frequent colour inside the band other than the ground."""
    inset = int(T["focus.width"]) + 2
    counts = Counter(
        image.pixelColor(x, y).name()
        for y in range(inset, image.height() - inset)
        for x in range(inset, image.width() - inset)
    )
    ordered = [colour for colour, _ in counts.most_common()]
    return ordered[1] if len(ordered) > 1 else f"no ink (only {ordered})"


def _band(image: QImage) -> tuple[list[str], set[str]]:
    """The left edge's first `focus.width` px at mid-height, and the top edge's
    colours along its middle line."""
    width = int(T["focus.width"])
    left = [_at(image, x, image.height() // 2) for x in range(width)]
    top = {_at(image, x, width // 2) for x in range(2 * width, image.width() - 2 * width)}
    return left, top


def test_at_rest_the_start_button_is_accent_with_on_accent_text_and_no_ring(
    qtbot,  # type: ignore[no-untyped-def]
    themed: None,
    tmp_path: Path,
) -> None:
    _window, summary = _themed_summary(qtbot, tmp_path)
    image = _grab(_start(summary))

    assert _ground(image) == _colour("color.accent.base")
    assert _ink(image) == _colour("color.text.on-accent")
    left, top = _band(image)
    base = _colour("color.surface.base")
    assert (left, top) == ([base] * int(T["focus.width"]), {base}), (
        "at rest the band is not transparent over the window's ground"
    )


def test_hovered_the_start_button_is_accent_hover(
    qtbot,  # type: ignore[no-untyped-def]
    themed: None,
    tmp_path: Path,
) -> None:
    _window, summary = _themed_summary(qtbot, tmp_path)
    button = _start(summary)

    QTest.mouseMove(button, button.rect().center())
    _settle()

    assert button.underMouse(), "precondition: the pointer is over the button"
    assert _ground(_grab(button)) == _colour("color.accent.hover")


def test_pressed_the_start_button_is_accent_pressed(
    qtbot,  # type: ignore[no-untyped-def]
    themed: None,
    tmp_path: Path,
) -> None:
    _window, summary = _themed_summary(qtbot, tmp_path)
    button = _start(summary)

    button.setDown(True)
    _settle()
    try:
        assert _ground(_grab(button)) == _colour("color.accent.pressed")
    finally:
        button.setDown(False)


def test_focused_the_start_button_shows_the_ring_on_the_band_and_keeps_its_ground(
    qtbot,  # type: ignore[no-untyped-def]
    themed: None,
    tmp_path: Path,
) -> None:
    _window, summary = _themed_summary(qtbot, tmp_path)
    button = _start(summary)

    button.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(button.hasFocus)
    _settle()
    image = _grab(button)

    ring = _colour("color.focus.ring")
    assert _band(image) == ([ring] * int(T["focus.width"]), {ring})
    assert _ground(image) == _colour("color.accent.base"), "focus changed the ground"


def test_the_choose_button_keeps_the_secondary_ground(
    qtbot,  # type: ignore[no-untyped-def]
    themed: None,
    tmp_path: Path,
) -> None:
    """Control: the primary rule is scoped by the property, not to every button."""
    _window, summary = _themed_summary(qtbot, tmp_path)
    image = _grab(_choose(summary))

    assert _at(image, 4, image.height() // 2) == _colour("color.surface.raised")
