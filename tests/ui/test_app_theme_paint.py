"""MT-061 AC-2 to AC-8: what the packaged theme paints, measured in pixels.

**Oracle partition (story C-6).** AC-2, AC-3, AC-4, AC-5, AC-7 and AC-8 are
*settled*: `components.md` sections 2, 3 and 5 name every part's token, and
`tokens_gen.TOKENS` holds every value. The part-to-token tables below are read
out of `components.md` by name; no colour or size is typed here. AC-6 is
*mechanical*: one sentinel per token, every part in that token must show it.

**Measurement (C-5).**

- Painted colour, never `palette()`: the window holding the widget is grabbed
  over the widget's own rectangle (`_grab`), so what is sampled is what the
  screen would show, with every ancestor's ground composited behind it.
  Colours are compared as `QColor.name()`, exactly.
- A window's own ground (AC-2) is `render()` with `DrawWindowBackground` and no
  `DrawChildren`, after `ensurePolished()`.
- Text colour ("ink") is the most frequent colour in the part's rectangle other
  than its most frequent (the ground). A glyph's fully covered pixels are the
  text colour exactly; antialiased edge pixels are spread over many shades, so
  none of them outnumbers it.
- Borders are sampled as a run along the middle of an edge, inset by half the
  border width; the dashed empty border may contain the ground in its gaps and
  nothing else. Grounds are sampled at least `border-width.emphasis` + 2 px in.
- The drop target takes focus when its window is shown, so AC-4's resting
  borders are measured with focus cleared; AC-5 sets focus on purpose.
- Type is `ensurePolished()` then `font().pixelSize()` / `.weight()`.

**Isolation.** Every test that applies a sheet to the real application does it
through the `application_sheet` fixture, which restores `""` in teardown, so no
other suite inherits a theme whatever order the tests run in.

**What each AC's sheet is.** "The packaged `theme.qss`" is read here from the
package resource directly, not through `mangatl.ui.stylesheet`: AC-1 is where
the loader is judged, and reading the resource here lets these tests - and
their controls - run in RED instead of failing at import. In RED the packaged
artefacts are MT-025's, without this story's rules (GREEN regenerates them,
C-3), so the measurements below fail on the painted colour or size.

**Drags.** Qt keeps a raw pointer to the widget whose drag enter it last
accepted; a leave sent later goes there (MT-056's measurement). The
`drag_released` fixture ends any drag before qtbot closes the widgets.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QMimeData, QPoint, QRect, QSize, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QImage,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

from mangatl import app as app_module
from mangatl.domain.line import Line
from mangatl.domain.page import Chapter, Page
from mangatl.store.project import create_project
from mangatl.ui import tokens, tokens_gen
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.link import OrderedRegion
from mangatl.ui.main_window import MainWindow
from mangatl.ui.summary import ChapterSummary
from mangatl.ui.workspace import STATUS_COLOR_TOKENS, TranslationRow, Workspace

#: MT-072 (`tests/ui/conftest.py`): every Project `mangatl.app` opens here is
#: closed by teardown (AC-2), because every window `build_window` returns is.
pytestmark = pytest.mark.usefixtures(
    "every_opened_project_is_closed", "every_built_window_is_closed"
)

T = tokens_gen.TOKENS

# --- components.md, read out by name ----------------------------------------------
#: section 2, ChapterSummary "Parts" and "Filename-order warning" tables:
#: object name -> (type token, colour token).
SUMMARY_PARTS: dict[str, tuple[str, str]] = {
    "summary-name": ("type.title", "color.text.primary"),
    "summary-count": ("type.body", "color.text.primary"),
    "summary-first": ("type.body", "color.text.secondary"),
    "summary-last": ("type.body", "color.text.secondary"),
    "order-lead": ("type.body-strong", "color.text.primary"),
    "order-natural": ("type.body", "color.text.primary"),
    "order-lexical": ("type.body", "color.text.primary"),
}
#: section 2, the one-page chapter's line, measured on its own chapter.
ONLY_PAGE_PART = ("summary-only", ("type.body", "color.text.secondary"))
#: section 2, the order notice: ground, border, border width.
NOTICE_GROUND = "color.surface.raised"
NOTICE_BORDER = "color.status.warning"
NOTICE_BORDER_WIDTH = "border-width.hairline"
#: section 2 "How it is rendered", AC-3 as amended (AM-1).
SUMMARY_CONTENT_GROUND = "color.surface.base"
#: section 2, FolderDropTarget state table (AM-2 for hover-valid's ground):
#: state -> (border token, dashed?, ground token or None when not asserted).
TARGET_STATES: dict[str, tuple[str, bool, str | None]] = {
    "empty": ("color.border.interactive", True, "color.surface.base"),
    "hover-valid": ("color.accent.base", False, "color.surface.hover"),
    "hover-invalid": ("color.status.danger", False, None),
    "error": ("color.status.danger", False, None),
}
TARGET_BORDER_WIDTH = "border-width.emphasis"
TARGET_RADIUS = "radius.md"
TARGET_BODY = "color.text.secondary"
TARGET_HEADLINE_TYPE = "type.display"
#: A-04 / tokens.md section 7.
FOCUS_RING = "color.focus.ring"
FOCUS_WIDTH = "focus.width"
#: section 3 / section 5 "List ground" (AM-3).
LIST_GROUND = "color.surface.raised"
LIST_TEXT = "color.text.primary"
#: section 5, TranslationRow anatomy, "Glyph colour".
GLYPH_COLOURS: dict[str, str] = {
    "proposed": "color.text.muted",
    "accepted": "color.status.success",
    "edited": "color.accent.base",
    "reverted": "color.text.secondary",
    "failed": "color.status.danger",
}
#: section 2, the window ground (`QMainWindow, QDialog` rule).
WINDOW_GROUND = "color.surface.base"

#: Qt's own default grounds under an empty sheet (offscreen, Fusion), as the
#: AC-3 and AC-8 controls name them.
QT_CONTENT_GREY = "#efefef"
QT_VIEW_WHITE = "#ffffff"

#: AC-6: a colour that no token uses (asserted below).
SENTINEL = "#13579B"
AC6_TOKENS = (
    "color.text.primary",
    "color.text.secondary",
    "color.surface.raised",
    "color.status.warning",
    "color.status.danger",
    "color.border.interactive",
)

#: Natural order differs from text order, so the notice is shown (AC-3).
PAGES = ("page 10.png", "page 11.png", "page 9.png")
STATUSES = ("proposed", "accepted", "edited", "reverted", "failed")
WINDOW = QSize(1100, 720)


def _px(name: str) -> int:
    return int(T[name])


def _colour(name: str) -> str:
    """A colour token as `QColor.name()` spells it."""
    return QColor(T[name]).name()


def _size(type_token: str) -> int:
    return int(T[f"{type_token}.size"])


def _weight(type_token: str) -> int:
    return int(T[f"{type_token}.weight"])


# --- Self-checks: the tables are the code's, and the instruments discriminate ------


def test_the_glyph_table_is_the_one_workspace_uses() -> None:
    assert dict(STATUS_COLOR_TOKENS) == GLYPH_COLOURS


def test_the_five_glyph_colours_are_pairwise_distinct_and_none_is_text_primary() -> None:
    """Without this AC-7's control could not tell the statuses apart."""
    colours = [_colour(token) for token in GLYPH_COLOURS.values()]
    assert len(set(colours)) == 5, colours
    assert _colour("color.text.primary") not in colours


def test_the_title_and_body_sizes_differ() -> None:
    """Without this AC-3's heading control could not see the regression."""
    assert _size("type.title") != _size("type.body")


def test_the_sentinel_is_no_tokens_value() -> None:
    used = {value[:7].upper() for value in T.values() if value.startswith("#")}
    assert SENTINEL.upper() not in used, f"{SENTINEL} is a token's value"
    assert QColor(SENTINEL).name() not in {QT_CONTENT_GREY, QT_VIEW_WHITE}


# --- Sheets ------------------------------------------------------------------------


def _packaged(resource: str) -> str:
    return files("mangatl.ui").joinpath(resource).read_text(encoding="utf-8")


def packaged_theme() -> str:
    return _packaged("theme.qss")


def sentinel_theme(token: str) -> str:
    """AC-6: the packaged template rendered with `token` replaced."""
    values = dict(T)
    values[token] = SENTINEL
    return tokens.render_qss(values, _packaged("theme.qss.tmpl"))


@pytest.fixture
def application_sheet(qapp: QApplication) -> Iterator[Callable[[str], None]]:
    """Set the real application's sheet; always put `""` back."""

    def apply(sheet: str) -> None:
        qapp.setStyleSheet(sheet)

    try:
        yield apply
    finally:
        qapp.setStyleSheet("")


@pytest.fixture
def drag_released(qtbot) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Torn down before qtbot closes the widgets: end any drag Qt still holds."""
    yield
    QApplication.sendEvent(QWidget(), QDragLeaveEvent())


# --- Folders -------------------------------------------------------------------------


def _png() -> bytes:
    image = QImage(QSize(60, 80), QImage.Format.Format_RGB32)
    image.fill(QColor(T["color.surface.raised"]))
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    data = bytes(buffer.data().data())
    buffer.close()
    return data


def _pages_folder(root: Path, name: str, pages: tuple[str, ...] = PAGES) -> Path:
    folder = root / name
    folder.mkdir()
    png = _png()
    for page in pages:
        (folder / page).write_bytes(png)
    return folder


def _project_folder(root: Path) -> Path:
    folder = _pages_folder(root, "with project", ("b-first.png", "a-second.png"))
    chapter = Chapter(
        source_dir=folder,
        pages=tuple(
            Page(ordinal=i, filename=name, width=60, height=80, sha256=f"{i}" * 64)
            for i, name in enumerate(("b-first.png", "a-second.png"))
        ),
    )
    with create_project(chapter, root / "with project.mtproj"):
        pass
    return folder


def _empty_folder(root: Path) -> Path:
    folder = root / "no pages"
    folder.mkdir()
    (folder / "readme.txt").write_text("x", encoding="utf-8")
    return folder


# --- Instruments ---------------------------------------------------------------------


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _show(qtbot, window: QWidget) -> None:  # type: ignore[no-untyped-def]
    qtbot.addWidget(window)
    window.resize(WINDOW)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()


def _grab(widget: QWidget) -> QImage:
    """The window's painted pixels over `widget`'s rectangle."""
    window = widget.window()
    origin = widget.mapTo(window, QPoint(0, 0))
    return window.grab(QRect(origin, widget.size())).toImage()


def _at(image: QImage, x: int, y: int) -> str:
    return image.pixelColor(x, y).name()


def _counts(image: QImage) -> Counter[str]:
    return Counter(
        image.pixelColor(x, y).name() for y in range(image.height()) for x in range(image.width())
    )


def _ink(image: QImage) -> str:
    """The text colour: the most frequent colour after the ground."""
    ordered = [colour for colour, _ in _counts(image).most_common()]
    return ordered[1] if len(ordered) > 1 else f"no ink (only {ordered})"


def _window_ground(window: QWidget) -> str:
    """AC-2: the window's own ground, children not drawn."""
    window.ensurePolished()
    pixmap = QPixmap(window.size())
    pixmap.fill(QColor(SENTINEL))
    window.render(pixmap, QPoint(), QRegion(), QWidget.RenderFlag.DrawWindowBackground)
    image = pixmap.toImage()
    return _at(image, image.width() // 2, image.height() // 2)


def _edge_runs(image: QImage, width: int, inset: int) -> dict[str, list[str]]:
    """The middle line of each edge of a `width`-px border, stopping `inset`
    px short of the corners."""
    w, h = image.width(), image.height()
    mid = width // 2
    return {
        "top": [_at(image, x, mid) for x in range(inset, w - inset)],
        "bottom": [_at(image, x, h - 1 - mid) for x in range(inset, w - inset)],
        "left": [_at(image, mid, y) for y in range(inset, h - inset)],
        "right": [_at(image, w - 1 - mid, y) for y in range(inset, h - inset)],
    }


def _type(label: QLabel) -> tuple[int, int]:
    label.ensurePolished()
    font = label.font()
    return font.pixelSize(), int(font.weight().value)


# --- Windows -------------------------------------------------------------------------


def _summary_window(qtbot, root: Path) -> tuple[MainWindow, ChapterSummary]:  # type: ignore[no-untyped-def]
    window = app_module.build_window([str(_pages_folder(root, "Vol 1 & 2"))])
    assert isinstance(window, MainWindow)
    _show(qtbot, window)
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary), f"central is {type(summary).__name__}"
    return window, summary


def _intake_window(qtbot) -> tuple[MainWindow, FolderDropTarget]:  # type: ignore[no-untyped-def]
    window = app_module.build_window([])
    assert isinstance(window, MainWindow)
    _show(qtbot, window)
    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget), f"central is {type(target).__name__}"
    return window, target


def _part(summary: QWidget, name: str) -> QLabel:
    label = summary.findChild(QLabel, name)
    assert label is not None, f"no QLabel#{name}"
    return label


def _unfocus(target: FolderDropTarget) -> None:
    target.clearFocus()
    _settle()
    assert not target.hasFocus(), "precondition: the drop target still has focus"


# --- Drags (MT-056's shapes) -----------------------------------------------------------

_ALIVE: list[QMimeData] = []


def _mime(*paths: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    _ALIVE.append(mime)
    return mime


def _enter(target: FolderDropTarget, mime: QMimeData) -> None:
    event = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.setAccepted(False)
    QApplication.sendEvent(target, event)
    _settle()


def _leave(target: FolderDropTarget) -> None:
    QApplication.sendEvent(target, QDragLeaveEvent())
    _settle()


def _drop_directly(target: FolderDropTarget, mime: QMimeData) -> None:
    """An invalid drop: its enter was refused, so it is delivered to the
    target itself (MT-056 C-3)."""
    event = QDropEvent(
        QPoint(5, 5).toPointF(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.setAccepted(False)
    target.event(event)
    _settle()


def _to_state(target: FolderDropTarget, state: str, root: Path) -> None:
    """Put the target in `state` the way a user would."""
    if state == "empty":
        assert target.state == "empty"
    elif state == "hover-valid":
        folder = root / "a folder"
        folder.mkdir(exist_ok=True)
        _enter(target, _mime(folder))
    elif state == "hover-invalid":
        page = root / "a file.png"
        page.write_bytes(b"x")
        _enter(target, _mime(page))
    elif state == "error":
        target.show_error("No page images in C:\\manga. This tool reads .png and .jpg files.")
        _settle()
    assert target.state == state, f"precondition: target is {target.state!r}, not {state!r}"


def _border_problems(target: FolderDropTarget, token: str, dashed: bool) -> list[str]:
    """Every edge run of the target's border that is not `token` (with the
    ground in a dashed border's gaps)."""
    image = _grab(target)
    width = _px(TARGET_BORDER_WIDTH)
    ground = _at(image, width + 2, image.height() // 2)
    expected = _colour(token)
    allowed = {expected, ground} if dashed else {expected}
    problems = []
    for edge, run in _edge_runs(image, width, _px(TARGET_RADIUS) + width).items():
        seen = set(run)
        if expected not in seen or not seen <= allowed:
            problems.append(f"{edge} edge {sorted(Counter(run).items(), key=lambda c: -c[1])}")
    return problems


# =============================================================================
# AC-2: every window build_window returns is grounded in color.surface.base
# =============================================================================

WINDOW_KINDS: dict[str, Callable[[Path], list[str]]] = {
    "intake, empty": lambda root: [],
    "intake showing a ChapterSummary": lambda root: [str(_pages_folder(root, "Vol 1"))],
    "intake, error state": lambda root: [str(_empty_folder(root))],
    "notice window": lambda root: [str(root / "no such folder")],
    "Workspace": lambda root: [str(_project_folder(root))],
}


def _built(qtbot, kind: str, root: Path) -> QMainWindow:  # type: ignore[no-untyped-def]
    window = app_module.build_window(WINDOW_KINDS[kind](root))
    _show(qtbot, window)
    expected = Workspace if kind == "Workspace" else MainWindow
    assert type(window) is expected, f"{kind}: built a {type(window).__name__}"
    if kind == "intake, error state":
        target = window.centralWidget()
        assert isinstance(target, FolderDropTarget) and target.state == "error"
    if kind == "intake showing a ChapterSummary":
        assert isinstance(window.centralWidget(), ChapterSummary)
    return window


@pytest.mark.parametrize("kind", list(WINDOW_KINDS))
def test_every_window_is_painted_on_the_base_surface(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    kind: str,
) -> None:
    application_sheet(packaged_theme())
    window = _built(qtbot, kind, tmp_path)

    assert _window_ground(window) == _colour(WINDOW_GROUND), f"{kind}: window ground"


@pytest.mark.parametrize("kind", list(WINDOW_KINDS))
def test_control_without_the_sheet_no_window_is_on_the_base_surface(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    kind: str,
) -> None:
    """AC-2's control: the ground is not the token by coincidence."""
    application_sheet("")
    window = _built(qtbot, kind, tmp_path)

    assert _window_ground(window) != _colour(WINDOW_GROUND), f"{kind}: unthemed ground"


# =============================================================================
# AC-3: the ChapterSummary's parts, notice and content ground
# =============================================================================


def _part_problems(label: QLabel, type_token: str, colour_token: str) -> list[str]:
    size, weight = _type(label)
    ink = _ink(_grab(label))
    problems = []
    if (size, weight) != (_size(type_token), _weight(type_token)):
        problems.append(
            f"type {size}px/{weight}, not {type_token} {_size(type_token)}px/{_weight(type_token)}"
        )
    if ink != _colour(colour_token):
        problems.append(f"text {ink}, not {colour_token} {_colour(colour_token)}")
    return problems


@pytest.mark.parametrize("part", list(SUMMARY_PARTS))
def test_each_summary_part_has_its_type_and_text_colour(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    part: str,
) -> None:
    application_sheet(packaged_theme())
    _window, summary = _summary_window(qtbot, tmp_path)

    type_token, colour_token = SUMMARY_PARTS[part]
    assert _part_problems(_part(summary, part), type_token, colour_token) == [], part


def test_a_one_page_chapters_only_page_line_has_its_type_and_text_colour(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet(packaged_theme())
    window = app_module.build_window([str(_pages_folder(tmp_path, "One", ("001.png",)))])
    _show(qtbot, window)
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary)

    name, (type_token, colour_token) = ONLY_PAGE_PART
    assert _part_problems(_part(summary, name), type_token, colour_token) == []


def _notice(summary: ChapterSummary) -> QWidget:
    notice = summary.findChild(QWidget, "summary-order-notice")
    assert notice is not None, "no order notice: the fixture's orders agree"
    return notice


def test_the_order_notice_is_raised_inside_a_hairline_warning_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet(packaged_theme())
    _window, summary = _summary_window(qtbot, tmp_path)
    image = _grab(_notice(summary))
    h = image.height()
    hairline = _px(NOTICE_BORDER_WIDTH)
    inset = _px("radius.sm") + hairline

    runs = _edge_runs(image, hairline, inset)
    assert {edge: set(run) for edge, run in runs.items()} == {
        edge: {_colour(NOTICE_BORDER)} for edge in runs
    }, "notice border"
    # In the space.3 margin band before the labels, then just inside the hairline.
    ground = _at(image, _px(TARGET_BORDER_WIDTH) + 2, h // 2)
    assert ground == _colour(NOTICE_GROUND), f"notice ground {ground}, not {NOTICE_GROUND}"
    inside = _at(image, hairline, h // 2)
    assert inside == ground, f"the border is wider than {NOTICE_BORDER_WIDTH}: {inside} inside it"


def _content_ground_between_parts(summary: ChapterSummary) -> str:
    """A pixel of the scroll area's content widget in the space.2 gap between
    the heading and the page count."""
    heading = _part(summary, "summary-name")
    count = _part(summary, "summary-count")
    gap_top, gap_bottom = heading.geometry().bottom() + 1, count.geometry().top() - 1
    assert gap_bottom >= gap_top, "precondition: no gap between heading and count"
    content = heading.parentWidget()
    assert content is summary.scroll_area.widget()
    image = _grab(content)
    return _at(image, image.width() // 2, (gap_top + gap_bottom) // 2)


def test_the_summarys_reading_area_is_on_the_base_surface_between_its_parts(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet(packaged_theme())
    _window, summary = _summary_window(qtbot, tmp_path)

    assert _content_ground_between_parts(summary) == _colour(SUMMARY_CONTENT_GROUND)


def test_control_without_the_sheet_the_heading_is_not_text_primary(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet("")
    _window, summary = _summary_window(qtbot, tmp_path)

    assert _ink(_grab(_part(summary, "summary-name"))) != _colour("color.text.primary")


def test_control_with_the_sheet_the_heading_is_not_body_size(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """The regression the base `QWidget { font-size }` rule causes against a
    widget-level `setFont`."""
    application_sheet(packaged_theme())
    _window, summary = _summary_window(qtbot, tmp_path)

    size, _ = _type(_part(summary, "summary-name"))
    assert size != _size("type.body"), f"the heading is body size ({size}px) under the sheet"


def test_control_without_the_sheet_the_reading_area_is_qts_light_grey(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet("")
    _window, summary = _summary_window(qtbot, tmp_path)

    ground = _content_ground_between_parts(summary)
    assert ground != _colour(SUMMARY_CONTENT_GROUND)
    assert ground == QT_CONTENT_GREY


# =============================================================================
# AC-4: the FolderDropTarget paints each state's border and ground
# =============================================================================


@pytest.mark.parametrize("state", list(TARGET_STATES))
def test_the_drop_target_paints_each_states_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    drag_released: None,
    tmp_path: Path,
    state: str,
) -> None:
    application_sheet(packaged_theme())
    _window, target = _intake_window(qtbot)
    _unfocus(target)
    _to_state(target, state, tmp_path)

    token, dashed, _ = TARGET_STATES[state]
    assert _border_problems(target, token, dashed) == [], f"{state}: border is not {token}"


@pytest.mark.parametrize("state", [s for s, (_, _, g) in TARGET_STATES.items() if g])
def test_the_drop_target_paints_each_states_ground(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    drag_released: None,
    tmp_path: Path,
    state: str,
) -> None:
    application_sheet(packaged_theme())
    _window, target = _intake_window(qtbot)
    _unfocus(target)
    _to_state(target, state, tmp_path)
    image = _grab(target)

    ground = TARGET_STATES[state][2]
    assert ground is not None
    inside = _px(TARGET_BORDER_WIDTH) + 2
    assert _at(image, inside, image.height() // 2) == _colour(ground), f"{state}: ground"


def test_the_empty_border_is_dashed(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """Dashed, not solid: the top edge's run shows the ground in its gaps."""
    application_sheet(packaged_theme())
    _window, target = _intake_window(qtbot)
    _unfocus(target)
    image = _grab(target)
    width = _px(TARGET_BORDER_WIDTH)

    top = _edge_runs(image, width, _px(TARGET_RADIUS) + width)["top"]
    ground = _colour(TARGET_STATES["empty"][2] or "")
    assert set(top) == {_colour(TARGET_STATES["empty"][0]), ground}, Counter(top)


@pytest.mark.parametrize("state", ["empty", "hover-valid", "hover-invalid"])
def test_the_drop_targets_body_line_is_secondary_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    drag_released: None,
    tmp_path: Path,
    state: str,
) -> None:
    application_sheet(packaged_theme())
    _window, target = _intake_window(qtbot)
    _unfocus(target)
    _to_state(target, state, tmp_path)
    assert target.body.isVisible() and target.body.text(), f"{state}: no body line"

    assert _ink(_grab(target.body)) == _colour(TARGET_BODY), f"{state}: body line"


def test_the_drop_targets_headline_is_display_type(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    application_sheet(packaged_theme())
    _window, target = _intake_window(qtbot)

    assert _type(target.headline) == (
        _size(TARGET_HEADLINE_TYPE),
        _weight(TARGET_HEADLINE_TYPE),
    )


#: AC-4's restores: (state before, the drag) - each pair's two borders differ.
RESTORES = {
    "empty, a valid drag leaves": ("empty", "hover-valid"),
    "empty, an invalid drag leaves": ("empty", "hover-invalid"),
    "error, a valid drag leaves": ("error", "hover-valid"),
}


@pytest.mark.parametrize("case", list(RESTORES))
def test_a_drag_that_leaves_restores_the_previous_painted_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    drag_released: None,
    tmp_path: Path,
    case: str,
) -> None:
    before, during = RESTORES[case]
    application_sheet(packaged_theme())
    _window, target = _intake_window(qtbot)
    _unfocus(target)
    _to_state(target, before, tmp_path)
    _to_state(target, during, tmp_path)
    during_problems = _border_problems(target, TARGET_STATES[during][0], False)

    _leave(target)
    _unfocus(target)

    assert target.state == before
    token, dashed, _ = TARGET_STATES[before]
    restored_problems = _border_problems(target, token, dashed)
    assert {"during the drag": during_problems, "after it left": restored_problems} == {
        "during the drag": [],
        "after it left": [],
    }, f"{case}: the painted border did not follow the drag"


def test_an_invalid_drop_restores_the_previous_painted_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    drag_released: None,
    tmp_path: Path,
) -> None:
    application_sheet(packaged_theme())
    _window, target = _intake_window(qtbot)
    _unfocus(target)
    page = tmp_path / "a file.png"
    page.write_bytes(b"x")
    mime = _mime(page)
    _enter(target, mime)
    assert target.state == "hover-invalid", "precondition"
    during_problems = _border_problems(target, TARGET_STATES["hover-invalid"][0], False)

    _drop_directly(target, mime)
    _unfocus(target)

    assert target.state == "empty"
    token, dashed, _ = TARGET_STATES["empty"]
    restored_problems = _border_problems(target, token, dashed)
    assert {"during the drag": during_problems, "after the drop": restored_problems} == {
        "during the drag": [],
        "after the drop": [],
    }, "the painted border did not follow the refused drop"


# =============================================================================
# AC-5: focus rings on the summary's scroll area and the drop target
# =============================================================================


def _ring_problems(image: QImage) -> list[str]:
    """A `focus.width` ring in `color.focus.ring`, on the left edge's middle:
    ring for focus.width pixels, then not ring."""
    width = _px(FOCUS_WIDTH)
    ring = _colour(FOCUS_RING)
    y = image.height() // 2
    across = [_at(image, x, y) for x in range(width + 1)]
    expected = [ring] * width
    problems = []
    if across[:width] != expected:
        problems.append(f"left edge {across[:width]}, not {width} px of {ring}")
    if across[width] == ring:
        problems.append(f"the ring is wider than {width} px")
    top = _edge_runs(image, width, 2 * width)["top"]
    if set(top) != {ring}:
        problems.append(f"top edge {Counter(top)}")
    return problems


def test_the_summarys_scroll_area_shows_the_ring_while_focused_and_loses_it(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet(packaged_theme())
    _window, summary = _summary_window(qtbot, tmp_path)
    scroll = summary.scroll_area
    scroll.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(scroll.hasFocus)
    _settle()

    assert _ring_problems(_grab(scroll)) == [], "focused scroll area"

    summary.choose.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(summary.choose.hasFocus)
    _settle()
    image = _grab(scroll)
    left = [_at(image, x, image.height() // 2) for x in range(_px(FOCUS_WIDTH))]
    assert _colour(FOCUS_RING) not in left, f"the ring stayed after focus moved on: {left}"


@pytest.mark.parametrize("state", ["empty", "error"])
def test_the_drop_target_shows_the_ring_while_focused_and_loses_it(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    state: str,
) -> None:
    """The two states a keyboard user can focus it in: the resting ones."""
    application_sheet(packaged_theme())
    _window, target = _intake_window(qtbot)
    _unfocus(target)
    _to_state(target, state, tmp_path)
    target.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(target.hasFocus)
    _settle()

    assert _ring_problems(_grab(target)) == [], f"focused drop target, {state}"

    _unfocus(target)
    image = _grab(target)
    left = [_at(image, x, image.height() // 2) for x in range(_px(FOCUS_WIDTH))]
    assert _colour(FOCUS_RING) not in left, f"{state}: the ring stayed after focus moved on"


# =============================================================================
# AC-6: every colour the intake and summary show comes from the application sheet
# =============================================================================


def _ac6_measurements(qtbot, root: Path) -> dict[str, tuple[str, list[str]]]:  # type: ignore[no-untyped-def]
    """part -> (its token per components.md, what it paints). The border
    entries carry the list of edge problems against the *sentinel*, so they
    are measured later, by `_ac6_check`."""
    measured: dict[str, tuple[str, list[str]]] = {}
    _window, summary = _summary_window(qtbot, root)
    for part, (_, token) in SUMMARY_PARTS.items():
        measured[part] = (token, [_ink(_grab(_part(summary, part)))])
    notice = _grab(_notice(summary))
    h = notice.height()
    measured["order notice ground"] = (
        NOTICE_GROUND,
        [_at(notice, _px(TARGET_BORDER_WIDTH) + 2, h // 2)],
    )
    runs = _edge_runs(notice, _px(NOTICE_BORDER_WIDTH), _px("radius.sm") + 1)
    measured["order notice border"] = (NOTICE_BORDER, sorted({c for r in runs.values() for c in r}))

    _window, target = _intake_window(qtbot)
    _unfocus(target)
    measured["drop target body (empty)"] = (TARGET_BODY, [_ink(_grab(target.body))])
    for state in ("empty", "hover-invalid", "error"):
        if state != "empty":
            _to_state(target, state, root)
        image = _grab(target)
        width = _px(TARGET_BORDER_WIDTH)
        edge = _edge_runs(image, width, _px(TARGET_RADIUS) + width)
        ground = _at(image, width + 2, image.height() // 2)
        colours = sorted({c for run in edge.values() for c in run} - {ground})
        measured[f"drop target border ({state})"] = (TARGET_STATES[state][0], colours)
        if state == "hover-invalid":
            _leave(target)
            _unfocus(target)
    return measured


@pytest.mark.parametrize("token", AC6_TOKENS)
def test_every_part_in_the_token_follows_the_application_sheet(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    drag_released: None,
    tmp_path: Path,
    token: str,
) -> None:
    application_sheet(sentinel_theme(token))
    measured = _ac6_measurements(qtbot, tmp_path)

    sentinel = QColor(SENTINEL).name()
    parts = {part: seen for part, (part_token, seen) in measured.items() if part_token == token}
    assert parts, f"no part AC-3/AC-4 measures is in {token}"
    wrong = {part: seen for part, seen in parts.items() if seen != [sentinel]}
    assert wrong == {}, f"with {token} = {sentinel}, these parts painted something else"


# =============================================================================
# AC-7: the status gutter paints each status's glyph colour
# =============================================================================


def _line(status: str, index: int) -> Line:
    return Line(
        reading_index=index,
        source_ja="" if status == "failed" else f"ja {index}",
        proposed_en=None if status == "failed" else "Hello.",
        final_en={"edited": "Mine", "reverted": "Hello."}.get(status),
        status=status,  # type: ignore[arg-type]
        edited_at=None,
        ocr_empty=status == "failed",
    )


def _workspace_with_rows(qtbot, root: Path) -> Workspace:  # type: ignore[no-untyped-def]
    """A Workspace as `build_window` returns it - pages in its strip - with one
    row per status in its column."""
    window = app_module.build_window([str(_project_folder(root))])
    assert isinstance(window, Workspace)
    _show(qtbot, window)
    regions = [
        OrderedRegion(i, ((10, 10 + 40 * i), (60, 10 + 40 * i), (60, 40 + 40 * i)))
        for i in range(len(STATUSES))
    ]
    window.set_regions(
        regions,
        [f"ja {i}" for i in range(len(STATUSES))],
        ["Hello."] * len(STATUSES),
        [_line(status, i) for i, status in enumerate(STATUSES)],
    )
    _settle()
    for i, status in enumerate(STATUSES):
        assert window.translation_column.row(i).editor.status == status, "precondition"
    return window


def _glyph_colours(window: Workspace) -> dict[str, str]:
    return {
        status: _ink(_grab(window.translation_column.row(i).gutter))
        for i, status in enumerate(STATUSES)
    }


@pytest.mark.parametrize("status", STATUSES)
def test_each_status_glyph_is_painted_in_its_token(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    status: str,
) -> None:
    """One case per status, so a missing rule names its status (DV-3)."""
    application_sheet(packaged_theme())
    window = _workspace_with_rows(qtbot, tmp_path)

    painted = _glyph_colours(window)[status]
    token = GLYPH_COLOURS[status]
    assert painted == _colour(token), f"{status} glyph painted {painted}, not {token}"


def test_a_row_whose_status_changes_repaints_its_glyph_in_the_new_colour(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet(packaged_theme())
    window = _workspace_with_rows(qtbot, tmp_path)
    row = window.translation_column.row(0)
    assert row.editor.status == "proposed"

    row.editor.accept_line()
    _settle()

    assert row.editor.status == "accepted", "precondition: Accept did not accept"
    assert _ink(_grab(row.gutter)) == _colour(GLYPH_COLOURS["accepted"])


def test_control_a_sheet_with_only_a_widget_colour_fails_at_least_four_statuses(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-7's control: the measurement tells the five apart."""
    application_sheet(f"QWidget {{ color: {T['color.text.primary']}; }}")
    window = _workspace_with_rows(qtbot, tmp_path)

    measured = _glyph_colours(window)
    wrong = [s for s in STATUSES if measured[s] != _colour(GLYPH_COLOURS[s])]
    assert len(wrong) >= 4, f"only {wrong} failed: {measured}"


def test_a_standalone_row_is_measured_the_same_way(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """The same glyph colour off the list: the rule keys on the gutter, not on
    where the row sits."""
    application_sheet(packaged_theme())
    row = TranslationRow(0, _line("failed", 0), None)
    _show(qtbot, row)

    assert _ink(_grab(row.gutter)) == _colour(GLYPH_COLOURS["failed"])


# =============================================================================
# AC-8: both item views are grounded in color.surface.raised
# =============================================================================


def _views(window: Workspace) -> dict[str, QWidget]:
    return {
        "pageStrip": window.page_strip,
        "translationList": window.translation_column.list,
    }


def _ground_below_last_item(view) -> str:  # type: ignore[no-untyped-def]
    viewport = view.viewport()
    last = view.visualItemRect(view.item(view.count() - 1))
    y = viewport.height() - 4
    assert view.count() > 0 and last.bottom() < y, "precondition: no room below the last item"
    image = _grab(viewport)
    return _at(image, image.width() // 2, y)


@pytest.mark.parametrize("name", ["pageStrip", "translationList"])
def test_each_item_view_is_grounded_in_the_raised_surface_below_its_last_item(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    name: str,
) -> None:
    application_sheet(packaged_theme())
    window = _workspace_with_rows(qtbot, tmp_path)
    view = _views(window)[name]
    assert view.objectName() == name

    assert _ground_below_last_item(view) == _colour(LIST_GROUND), name


@pytest.mark.parametrize("name", ["pageStrip", "translationList"])
def test_control_without_the_sheet_each_item_view_is_white(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    name: str,
) -> None:
    application_sheet("")
    window = _workspace_with_rows(qtbot, tmp_path)

    ground = _ground_below_last_item(_views(window)[name])
    assert ground != _colour(LIST_GROUND)
    assert ground == QT_VIEW_WHITE


def _strip_row_one_ink(window: Workspace) -> str:
    strip = window.page_strip
    assert strip.count() >= 2 and strip.currentRow() != 1, "precondition: row 1 is current"
    # The item is wider than the 96 px strip; outside the viewport `copy` is black.
    rect = strip.visualItemRect(strip.item(1)).intersected(strip.viewport().rect())
    assert not rect.isEmpty(), "precondition: row 1 is not in view"
    image = _grab(strip.viewport()).copy(rect)
    return _ink(image)


def test_a_non_current_page_strip_items_text_is_primary(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet(packaged_theme())
    window = _workspace_with_rows(qtbot, tmp_path)

    assert _strip_row_one_ink(window) == _colour(LIST_TEXT)


def test_control_without_the_sheet_a_page_strip_items_text_is_not_primary(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    application_sheet("")
    window = _workspace_with_rows(qtbot, tmp_path)

    assert _strip_row_one_ink(window) != _colour(LIST_TEXT)
