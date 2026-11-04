"""MT-136: translation rows show their status borders under the selection bar.

`components.md` §5's state table and "How the row's ground and bars are
rendered" (precedence rules 3, 4 and 5): an `edited` row carries a **2px
`color.accent.base` leading bar even when unselected** (`border-width.emphasis`,
deliberately never `bar`); a `failed` row a **1px `color.status.danger` frame**
on all four sides (`border-width.hairline`); an `excluded` row **no bar**. The
selected rule (MT-135, rule 6) is authored after all three and so wins the left
side: selected + edited is one 3px bar, selected + failed is the 3px bar on the
left and the 1px frame on the other three sides. §10.4: under High Contrast the
`failed` frame is **2px `WindowText`** and the `edited` bar `WindowText` on
`Window`, replaced by the selected bar on the selected row. The status is a
row-level `status` property set and re-polished in `TranslationRow._render`.

This file pins all of it as **paint**, through the real theme path - the
packaged `theme.qss` (or the sheet composed for High Contrast) set as the
*application* sheet, never `styleSheet()` on a widget.

**The fixture (MT-136 C-6, PLANNED amendment, re-measured in RED).** A shown
`Workspace` as `build_window` returns it, its column holding six rows of status
`proposed, edited, failed, excluded, accepted, reverted`
(`_workspace_with_rows`). As built, the column's viewport is 278 px wide and the
`failed` row hints 312 px, so no row lies inside the viewport; the fixture
therefore resizes the window to 1400x720 and the splitter to `[96, 816, 480]`,
which gives a **478 px** viewport holding every row. Then `select(None)`, so a
row is selected only where a case says so.

**Sampling.** A row's rect is `list.visualItemRect(item)` mapped from the
list's viewport into the window, and the window is grabbed over it.

- **Band** = `list.spacing()`, measured **0**: rows `band .. height - band` of
  the grab are the row; nothing is cropped today.
- **Corner inset** = `border-width.bar` (read from the token, **3** px) at each
  end of every sampled column and edge line. The row has no radius; the inset
  is for the frame: a `failed` row's top and bottom frame pixels lie on the ends
  of every column, and its left and right ones on the ends of every horizontal
  line, so without it AC-3's "line 1 every pixel raised" is unsatisfiable. On a
  selected `failed` row the 3px bar's join with the 1px frame is anti-aliased in
  the three corner pixels (C-6 measured `#69b6e9`, `#a69ebc`, `#e28690`).
- "Column n" is pixels `(n, y)` for `y` in `[inset, h - inset)`; "line d of an
  edge" is `test_hc_error_banner_border.py`'s `_edge_line` with that inset.

Helpers are copied from `tests/ui/test_translation_row_selected_bar.py` and
`tests/ui/test_hc_error_banner_border.py` (`tests` is not a package); `PALETTE`
keeps their values so runs can be compared.

Oracle partition (MT-136 `## Contract` C-7):

- **Settled, read out:** `border-width.hairline` (1), `emphasis` (2), `bar`
  (3), `color.status.danger`, `color.accent.base`, `color.surface.selected`,
  `color.surface.raised` from `tokens_gen.TOKENS`; the HC map through
  `theme.resolve` / `theme.compose_stylesheet`.
- **Mechanical, pinned exactly:** every column and edge-line set in AC-1 to
  AC-7 and AC-9; AC-8's geometry tuples.
- **Oracle-free:** none.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget

from mangatl import app as app_module
from mangatl.domain.line import Line
from mangatl.domain.page import Chapter, Page
from mangatl.store.project import create_project
from mangatl.ui import theme, tokens, tokens_gen
from mangatl.ui.link import OrderedRegion
from mangatl.ui.stylesheet import base_template, hc_template
from mangatl.ui.workspace import TranslationRow, Workspace

#: MT-072 (`tests/ui/conftest.py`): every Project `mangatl.app` opens here is
#: closed by teardown, because every window `build_window` returns is.
pytestmark = pytest.mark.usefixtures(
    "every_opened_project_is_closed", "every_built_window_is_closed"
)

HAIRLINE = "border-width.hairline"
EMPHASIS = "border-width.emphasis"
BAR = "border-width.bar"
ACCENT = "color.accent.base"
DANGER = "color.status.danger"
SELECTED = "color.surface.selected"
RAISED = "color.surface.raised"

#: A five-role contrast palette, identical to test_hc_error_banner_border.py's.
PALETTE: dict[str, str] = {
    "Window": "#010203",
    "WindowText": "#FDFEFF",
    "Highlight": "#1A2B3C",
    "HighlightedText": "#C3B2A1",
    "DisabledText": "#4D5E6F",
}

#: C-6: one row per status; row k has STATUSES[k].
STATUSES = ("proposed", "edited", "failed", "excluded", "accepted", "reverted")
#: J is current after `set_regions` (row 0).
J = 0
WINDOW = QSize(1100, 720)
#: C-6 PLANNED amendment: the widened window and splitter, and the viewport
#: width they give (measured 478; the column is 480 with a 1px frame each side).
WIDE = QSize(1400, 720)
SPLIT = (96, 816, 480)
VIEWPORT_WIDTH = 478

#: The columns sampled: the bar's three, then the first column of ground.
COLUMNS = 4
EDGES = ("top", "bottom", "left", "right")
#: The three edges the selection bar does not own.
FRAME_EDGES = ("top", "bottom", "right")


# --- Helpers (copied, not imported: `tests` is not a package) ------------------


def _token_colour(name: str) -> str:
    return QColor(tokens_gen.TOKENS[name]).name()


def _palette_colour(role: str) -> str:
    return QColor(PALETTE[role]).name()


def _width(name: str) -> int:
    """A width token, read out strictly: a missing token is a failed
    precondition, never a default."""
    assert name in tokens_gen.TOKENS, f"tokens_gen.TOKENS has no {name!r}"
    return int(tokens_gen.TOKENS[name])


def _inset() -> int:
    """C-6: the corner inset at each end of every sampled column and edge line."""
    return _width(BAR)


def _packaged(resource: str) -> str:
    return files("mangatl.ui").joinpath(resource).read_text(encoding="utf-8")


def _hc_theme(palette: Mapping[str, str] = PALETTE) -> str:
    return theme.compose_stylesheet(
        base_template(), hc_template(), high_contrast=True, palette=palette
    )


def _hc_base_alone(palette: Mapping[str, str] = PALETTE) -> str:
    """The packaged base template resolved under High Contrast with NO override
    appended - `test_theme_apply.py`'s `_render_base(True, PALETTE)` shape."""
    template = _packaged("theme.qss.tmpl")
    return tokens._PLACEHOLDER.sub(
        lambda m: theme.resolve(m.group(1), high_contrast=True, palette=palette), template
    )


@pytest.fixture
def application_sheet(qapp: QApplication) -> Iterator[Callable[[str], None]]:
    """Set the real application's sheet; always put `""` back."""

    def apply(sheet: str) -> None:
        qapp.setStyleSheet(sheet)

    try:
        yield apply
    finally:
        qapp.setStyleSheet("")


def _png() -> bytes:
    image = QImage(QSize(60, 80), QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    data = bytes(buffer.data().data())
    buffer.close()
    return data


def _project_folder(root: Path) -> Path:
    folder = root / "with project"
    folder.mkdir()
    png = _png()
    names = ("b-first.png", "a-second.png")
    for name in names:
        (folder / name).write_bytes(png)
    chapter = Chapter(
        source_dir=folder,
        pages=tuple(
            Page(ordinal=i, filename=name, width=60, height=80, sha256=f"{i}" * 64)
            for i, name in enumerate(names)
        ),
    )
    with create_project(chapter, root / "with project.mtproj"):
        pass
    return folder


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


def _workspace_with_rows(  # type: ignore[no-untyped-def]
    qtbot, root: Path, statuses: tuple[str, ...] = STATUSES
) -> Workspace:
    """A Workspace as `build_window` returns it, one row per status in its
    column; `set_regions` selects row 0. The application sheet is the
    caller's."""
    window = app_module.build_window([str(_project_folder(root))])
    assert isinstance(window, Workspace)
    _show(qtbot, window)
    regions = [
        OrderedRegion(i, ((10, 10 + 40 * i), (60, 10 + 40 * i), (60, 40 + 40 * i)))
        for i in range(len(statuses))
    ]
    window.set_regions(
        regions,
        [f"ja {i}" for i in range(len(statuses))],
        ["Hello."] * len(statuses),
        [_line(status, i) for i, status in enumerate(statuses)],
    )
    _settle()
    for i, status in enumerate(statuses):
        assert window.translation_column.row(i).editor.status == status, "precondition"
    assert window.translation_column.list.currentRow() == J, "precondition: row 0 current"
    return window


def _select(window: Workspace, row: int | None) -> None:
    window.translation_column.select(row)
    _settle()
    expected = -1 if row is None else row
    current = window.translation_column.list.currentRow()
    assert current == expected, f"precondition: select({row}) left row {current} current"


def _rows(window: Workspace) -> list[TranslationRow]:
    column = window.translation_column
    return [column.row(i) for i in range(column.list.count())]


def _outside_the_viewport(window: Workspace) -> dict[int, tuple[int, int, int, int]]:
    view = window.translation_column.list
    viewport = view.viewport().rect()
    return {
        i: rect.getRect()
        for i in range(view.count())
        if not viewport.contains(rect := view.visualItemRect(view.item(i)))
    }


def _wide_workspace(  # type: ignore[no-untyped-def]
    qtbot, root: Path, apply: Callable[[str], None], sheet: str
) -> Workspace:
    """C-6: the sheet applied, the six-status workspace built, widened so every
    row lies in a 478 px viewport, and nothing selected."""
    apply(sheet)
    window = _workspace_with_rows(qtbot, root)
    window.resize(WIDE)
    window.splitter.setSizes(list(SPLIT))
    _settle()
    width = window.translation_column.list.viewport().width()
    assert width == VIEWPORT_WIDTH, (
        f"precondition: the widened fixture's viewport is {width} px, not {VIEWPORT_WIDTH}"
    )
    outside = _outside_the_viewport(window)
    assert outside == {}, f"precondition: rows not wholly inside the viewport: {outside}"
    _select(window, None)
    return window


def _row_image(window: Workspace, row: int) -> QImage:
    """The window's painted pixels over row `row`'s item rect, less
    `list.spacing()` px at the top and bottom (the band)."""
    _settle()
    view = window.translation_column.list
    rect = view.visualItemRect(view.item(row))
    viewport = view.viewport().rect()
    assert viewport.contains(rect), (
        f"precondition: row {row} ({rect.getRect()}) is not wholly inside the viewport "
        f"({viewport.getRect()})"
    )
    origin = view.viewport().mapTo(window, rect.topLeft())
    image = window.grab(QRect(origin, rect.size())).toImage()
    band = view.spacing()
    assert image.height() > 2 * (band + _inset()) and image.width() > 2 * _inset() + COLUMNS, (
        f"precondition: row {row} is too small to sample ({image.width()}x{image.height()})"
    )
    return image.copy(0, band, image.width(), image.height() - 2 * band)


def _columns(image: QImage) -> list[set[str]]:
    """The colours on columns 0..3, each over `[inset, height - inset)`."""
    inset = _inset()
    return [
        {image.pixelColor(n, y).name() for y in range(inset, image.height() - inset)}
        for n in range(COLUMNS)
    ]


def _edge_line(image: QImage, depth: int) -> dict[str, set[str]]:
    """Per edge, the colours along the line `depth` pixels in from that edge,
    with the corner inset skipped at each end (the orthogonal sides' frame
    pixels, and the bar's anti-aliased join, belong to neither edge alone)."""
    inset = _inset()
    w, h = image.width(), image.height()

    def at(x: int, y: int) -> str:
        return image.pixelColor(x, y).name()

    return {
        "top": {at(x, depth) for x in range(inset, w - inset)},
        "bottom": {at(x, h - 1 - depth) for x in range(inset, w - inset)},
        "left": {at(depth, y) for y in range(inset, h - inset)},
        "right": {at(w - 1 - depth, y) for y in range(inset, h - inset)},
    }


#: What a case expects: "columns" -> columns 0..3, or an edge name -> its lines
#: 0, 1, ... in order. Only the keys given are sampled.
Expected = dict[str, list[set[str]]]


def _observe(image: QImage, expected: Expected) -> Expected:
    """The same shape as `expected`, read from `image`."""
    observed: Expected = {}
    for key, lines in expected.items():
        if key == "columns":
            observed[key] = _columns(image)
        else:
            observed[key] = [_edge_line(image, depth)[key] for depth in range(len(lines))]
    return observed


def _sampled(window: Workspace, row: int, expected: Expected) -> Expected:
    return _observe(_row_image(window, row), expected)


def _differences(observed: Expected, expected: Expected) -> dict[str, str]:
    return {
        key: f"got {observed[key]}, expected {lines}"
        for key, lines in expected.items()
        if observed[key] != lines
    }


def _bar(colour: str, ground: str, width: int) -> list[set[str]]:
    """Columns 0..3: `width` columns of `colour`, then `ground`."""
    assert 0 <= width < COLUMNS, f"a {width}px bar leaves no ground column in {COLUMNS}"
    return [{colour}] * width + [{ground}] * (COLUMNS - width)


def _frame(colour: str, ground: str, width: int) -> list[set[str]]:
    """Lines 0..width of an edge: `width` lines of `colour`, then `ground`."""
    return [{colour}] * width + [{ground}]


# --- What each case expects, read out of the tokens and the palette ------------


def _base_expected(status: str, selected: bool) -> Expected:
    """AC-1 to AC-6 under the packaged sheet."""
    accent, danger = _token_colour(ACCENT), _token_colour(DANGER)
    raised, selected_ground = _token_colour(RAISED), _token_colour(SELECTED)
    selection_bar = _bar(accent, selected_ground, _width(BAR))
    if status == "edited":  # AC-1, AC-2
        return {"columns": selection_bar if selected else _bar(accent, raised, _width(EMPHASIS))}
    if status == "failed":  # AC-3, AC-4
        if selected:
            frame = _frame(danger, selected_ground, _width(HAIRLINE))
            return {"columns": selection_bar} | {edge: frame for edge in FRAME_EDGES}
        return {edge: _frame(danger, raised, _width(HAIRLINE)) for edge in EDGES}
    if status == "excluded":  # AC-5
        return {"columns": selection_bar if selected else [{raised}] * COLUMNS}
    # AC-6: proposed, accepted, reverted, unselected only.
    assert not selected, f"no case selects a {status} row"
    return {"columns": [{raised}] * COLUMNS} | {edge: [{raised}] for edge in EDGES}


def _hc_expected(status: str, selected: bool) -> Expected:
    """AC-9 under the HC-composed sheet with the five-role palette."""
    window, window_text = _palette_colour("Window"), _palette_colour("WindowText")
    highlight, highlighted_text = _palette_colour("Highlight"), _palette_colour("HighlightedText")
    selection_bar = _bar(highlighted_text, highlight, _width(BAR))
    if status == "edited":
        return {
            "columns": selection_bar if selected else _bar(window_text, window, _width(EMPHASIS))
        }
    assert status == "failed", f"AC-9 has no {status} case"
    if selected:
        frame = _frame(window_text, highlight, _width(EMPHASIS))
        return {"columns": selection_bar} | {edge: frame for edge in FRAME_EDGES}
    return {edge: _frame(window_text, window, _width(EMPHASIS)) for edge in EDGES}


#: (status, selected) -> the AC it pins, under the packaged sheet.
BASE_CASES = [
    pytest.param("edited", False, id="AC-1 edited unselected"),
    pytest.param("edited", True, id="AC-2 edited selected"),
    pytest.param("failed", False, id="AC-3 failed unselected"),
    pytest.param("failed", True, id="AC-4 failed selected"),
    pytest.param("excluded", False, id="AC-5 excluded unselected"),
    pytest.param("excluded", True, id="AC-5 excluded selected"),
    pytest.param("proposed", False, id="AC-6 proposed unselected"),
    pytest.param("accepted", False, id="AC-6 accepted unselected"),
    pytest.param("reverted", False, id="AC-6 reverted unselected"),
]

HC_CASES = [
    pytest.param("failed", False, id="AC-9 failed unselected"),
    pytest.param("edited", False, id="AC-9 edited unselected"),
    pytest.param("edited", True, id="AC-9 edited selected"),
    pytest.param("failed", True, id="AC-9 failed selected"),
]


# --- Preconditions: the colours and widths this file compares are distinct -----


def test_the_list_ground_the_selected_ground_the_accent_and_the_danger_are_four_colours() -> None:
    """AC-1 to AC-6 tell raised, selected, accent and danger apart by colour."""
    colours = {_token_colour(name) for name in (RAISED, SELECTED, ACCENT, DANGER)}
    assert len(colours) == 4, f"{RAISED}, {SELECTED}, {ACCENT}, {DANGER} are not distinct"


def test_the_hc_palette_highlight_pair_and_window_pair_are_four_colours() -> None:
    """AC-9 tells HighlightedText from Highlight, and both from the Window pair."""
    roles = ("Highlight", "HighlightedText", "Window", "WindowText")
    assert len({_palette_colour(role) for role in roles}) == 4
    assert set(PALETTE) == set(tokens.HC_ROLES), "the palette must carry exactly the five roles"


def test_the_hairline_the_emphasis_and_the_bar_are_three_widths_that_fit_four_columns() -> None:
    """AC-1 and AC-2 tell the 2px `edited` bar from the 3px selection bar, and
    AC-9 the 2px HC frame from the 1px base frame: hairline < emphasis < bar,
    and the bar leaves a ground column in the four sampled."""
    widths = [_width(name) for name in (HAIRLINE, EMPHASIS, BAR)]
    assert widths[0] < widths[1] < widths[2] < COLUMNS, (
        f"{HAIRLINE}, {EMPHASIS}, {BAR} are {widths}; this file needs them strictly "
        f"increasing and under {COLUMNS}"
    )


def test_under_high_contrast_danger_maps_to_window_text_and_accent_to_highlight() -> None:
    """AC-9's negative controls read the base rules through the HC token map:
    the frame `color.status.danger` -> WindowText, the bar `color.accent.base`
    -> Highlight, the list ground `color.surface.raised` -> Window."""
    mapped = {
        name: QColor(theme.resolve(name, high_contrast=True, palette=PALETTE)).name()
        for name in (DANGER, ACCENT, RAISED)
    }
    expected = {
        DANGER: _palette_colour("WindowText"),
        ACCENT: _palette_colour("Highlight"),
        RAISED: _palette_colour("Window"),
    }
    assert mapped == expected


def test_precondition_the_widened_fixture_holds_every_row_inside_a_478_px_viewport(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """C-6: after `resize(1400, 720)` and `setSizes([96, 816, 480])` the
    viewport is 478 px wide and all six rows lie wholly inside it, nothing is
    selected, and the list's item spacing (the band) is 0."""
    window = _wide_workspace(qtbot, tmp_path, application_sheet, _packaged("theme.qss"))
    view = window.translation_column.list
    assert view.spacing() == 0, f"the band is {view.spacing()} px, recorded as 0 in RED"
    assert [row.editor.status for row in _rows(window)] == list(STATUSES)
    assert [row.property("selected") for row in _rows(window)] == [False] * len(STATUSES)


# --- AC-1 to AC-6: each (status, selected) under the packaged sheet --------------


@pytest.mark.parametrize(("status", "selected"), BASE_CASES)
def test_a_translation_row_draws_its_status_border_under_the_packaged_sheet(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    status: str,
    selected: bool,
) -> None:
    """AC-1 (edited unselected: columns 0-1 accent, 2 raised), AC-2 (edited
    selected: columns 0-2 accent, 3 selected), AC-3 (failed unselected: line 0
    of every edge danger, line 1 raised), AC-4 (failed selected: the selection
    bar, and line 0 danger / line 1 selected on top, bottom, right), AC-5
    (excluded: no bar unselected, the selection bar selected), AC-6 (proposed,
    accepted, reverted: columns 0-3 and line 0 of every edge raised). One
    sampler; the case id names the AC."""
    window = _wide_workspace(qtbot, tmp_path, application_sheet, _packaged("theme.qss"))
    row = STATUSES.index(status)
    if selected:
        _select(window, row)

    expected = _base_expected(status, selected)
    wrong = _differences(_sampled(window, row, expected), expected)

    state = "selected" if selected else "unselected"
    assert wrong == {}, f"the {state} {status} row (row {row}) draws the wrong border: {wrong}"


def test_an_excluded_row_hides_the_two_pixel_bar_an_edited_row_shows(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-5 with its CONTROL: in the same fixture the unselected `edited` row
    satisfies AC-1 (so "excluded hides the 2px bar" is told from "no status bar
    is ever drawn"); the unselected `excluded` row's columns 0-3 are raised;
    selected, its columns 0-2 are accent and column 3 selected."""
    window = _wide_workspace(qtbot, tmp_path, application_sheet, _packaged("theme.qss"))
    edited, excluded = STATUSES.index("edited"), STATUSES.index("excluded")

    control = _columns(_row_image(window, edited))
    assert control == _base_expected("edited", False)["columns"], (
        f"control: the unselected edited row (row {edited}) does not carry the "
        f"{EMPHASIS} {ACCENT} bar - columns 0-3 are {control}, expected "
        f"{_base_expected('edited', False)['columns']}; without it AC-5 cannot tell "
        "'excluded hides the bar' from 'no status bar is drawn'"
    )
    unselected = _columns(_row_image(window, excluded))
    assert unselected == _base_expected("excluded", False)["columns"], (
        f"the unselected excluded row (row {excluded}) shows a bar: columns 0-3 are {unselected}"
    )
    _select(window, excluded)
    chosen = _columns(_row_image(window, excluded))
    assert chosen == _base_expected("excluded", True)["columns"], (
        f"the selected excluded row (row {excluded}) does not carry the selection bar alone: "
        f"columns 0-3 are {chosen}"
    )


# --- AC-7: a status change repaints ---------------------------------------------


def test_a_row_whose_status_becomes_edited_and_then_reverted_repaints_its_bar(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-7: the unselected `proposed` row satisfies AC-6; typing "Mine" and
    accepting through the editor makes it `edited` and it then satisfies AC-1;
    reverting through the editor makes it `reverted` and it satisfies AC-6
    again. Fails without the row-level status property and its re-polish."""
    window = _wide_workspace(qtbot, tmp_path, application_sheet, _packaged("theme.qss"))
    index = STATUSES.index("proposed")
    row = window.translation_column.row(index)
    nothing = _base_expected("proposed", False)
    before = _sampled(window, index, nothing)
    assert _differences(before, nothing) == {}, f"precondition (AC-6): row {index} shows {before}"

    row.editor.setText("Mine")
    row.editor.accept_line()
    _settle()
    assert row.editor.status == "edited", f"precondition: the edit committed {row.editor.status}"
    edited = _columns(_row_image(window, index))
    bar = _base_expected("edited", False)["columns"]
    assert edited == bar, (
        f"row {index}, now edited, does not repaint the {EMPHASIS} {ACCENT} bar: columns 0-3 "
        f"are {edited}, expected {bar} - the row was not re-polished on its status change"
    )

    row.editor.revert()
    _settle()
    assert row.editor.status == "reverted", f"precondition: revert committed {row.editor.status}"
    after = _sampled(window, index, nothing)
    assert _differences(after, nothing) == {}, (
        f"row {index}, now reverted, still shows a bar: {_differences(after, nothing)}"
    )


# --- AC-8: nothing moves --------------------------------------------------------


def _layout_snapshot(window: Workspace) -> list[tuple[object, ...]]:
    """Per row: geometry, its sizeHint and its item's, and where its gutter,
    badge and editor sit in the list's viewport."""
    view = window.translation_column.list
    viewport = view.viewport()
    return [
        (
            i,
            row.geometry().getRect(),
            row.sizeHint().toTuple(),
            view.item(i).sizeHint().toTuple(),
            row.gutter.mapTo(viewport, QPoint(0, 0)).toTuple(),
            row.badge.mapTo(viewport, QPoint(0, 0)).toTuple(),
            row.editor.mapTo(viewport, QPoint(0, 0)).toTuple(),
        )
        for i, row in enumerate(_rows(window))
    ]


def test_no_status_border_and_no_selection_moves_a_row_gutter_badge_or_editor(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-8: with nothing selected and then with each of the six rows selected
    in turn, every row's geometry() and sizeHint() (and its item's) and its
    gutter's, badge's and editor's position in the viewport are identical.
    Guarded by the borders actually being drawn (the edited row's AC-1 bar, the
    failed row's AC-3 frame): AC-8 is about those borders moving nothing, so it
    cannot be judged on rows that draw none."""
    window = _wide_workspace(qtbot, tmp_path, application_sheet, _packaged("theme.qss"))
    drawn = {
        status: _differences(
            _sampled(window, STATUSES.index(status), _base_expected(status, False)),
            _base_expected(status, False),
        )
        for status in ("edited", "failed")
    }
    assert drawn == {"edited": {}, "failed": {}}, (
        f"precondition: the status borders AC-8 judges are not drawn yet: {drawn}"
    )
    at_rest = _layout_snapshot(window)

    moved: dict[int, list[tuple[object, object]]] = {}
    for index in range(len(STATUSES)):
        _select(window, index)
        snapshot = _layout_snapshot(window)
        if diff := [(b, a) for b, a in zip(at_rest, snapshot, strict=True) if b != a]:
            moved[index] = diff

    assert moved == {}, (
        "selecting a row moved rows - {selected row: [(row, geometry, sizeHint, item "
        f"sizeHint, gutter at, badge at, editor at) at rest -> selected]}}: {moved}"
    )


# --- AC-9: High Contrast --------------------------------------------------------


@pytest.mark.parametrize(("status", "selected"), HC_CASES)
def test_under_high_contrast_a_translation_row_draws_its_status_border_in_window_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    status: str,
    selected: bool,
) -> None:
    """AC-9: the HC-composed sheet with the five-role palette. Unselected
    failed: lines 0-1 of every edge WindowText, line 2 Window. Unselected
    edited: columns 0-1 WindowText, 2 Window. Selected edited: columns 0-2
    HighlightedText, 3 Highlight (the selected override, authored after the
    edited one, wins the left side). Selected failed: the same columns, and on
    top, bottom and right lines 0-1 WindowText, line 2 Highlight."""
    window = _wide_workspace(qtbot, tmp_path, application_sheet, _hc_theme())
    row = STATUSES.index(status)
    if selected:
        _select(window, row)

    expected = _hc_expected(status, selected)
    wrong = _differences(_sampled(window, row, expected), expected)

    state = "selected" if selected else "unselected"
    assert wrong == {}, (
        f"under High Contrast the {state} {status} row (row {row}) draws the wrong border: {wrong}"
    )


def test_control_the_base_template_alone_under_high_contrast_frames_failed_in_one_pixel(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-9 NEGATIVE CONTROL: the base template resolved under High Contrast
    with no override appended: the unselected failed row's line 0 of every edge
    is WindowText and line 1 Window - the 1px frame the override widens."""
    window = _wide_workspace(qtbot, tmp_path, application_sheet, _hc_base_alone())
    window_text, ground = _palette_colour("WindowText"), _palette_colour("Window")
    expected = {edge: _frame(window_text, ground, _width(HAIRLINE)) for edge in EDGES}

    wrong = _differences(_sampled(window, STATUSES.index("failed"), expected), expected)

    assert wrong == {}, (
        f"control: under the HC base template alone the failed row is not the "
        f"{HAIRLINE} WindowText frame: {wrong}"
    )


def test_control_the_base_template_alone_under_high_contrast_draws_the_edited_bar_highlight(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-9 NEGATIVE CONTROL: the base template alone under High Contrast: the
    unselected edited row's columns 0-1 are Highlight and 2-3 Window - the
    accent bar through the token map, which the override recolours."""
    window = _wide_workspace(qtbot, tmp_path, application_sheet, _hc_base_alone())
    expected = _bar(_palette_colour("Highlight"), _palette_colour("Window"), _width(EMPHASIS))

    columns = _columns(_row_image(window, STATUSES.index("edited")))

    assert columns == expected, (
        f"control: under the HC base template alone the edited row's columns 0-3 are "
        f"{columns}, expected {expected}"
    )
