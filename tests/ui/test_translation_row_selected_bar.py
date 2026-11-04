"""MT-135: the selected translation row carries the 3px accent bar, as paint.

`components.md` §5 `TranslationRow` ("How the row's ground and bars are
rendered"): the selected row carries a dynamic `selected` property, set and
re-polished by `TranslationColumn` from the list's current row, and paints its
own QSS box (`WA_StyledBackground`): ground `color.surface.selected` and a
**3px `color.accent.base` leading bar**; a hovered row takes only the
`color.surface.hover` ground; an unselected row paints nothing over the list's
`color.surface.raised`. `accessibility.md` A-03: the bar is the only selection
carrier that clears 3:1. §10.4: under High Contrast the selected row is the
`Highlight` pair with a `HighlightedText` bar, and its gutter glyph and ordinal
badge are `HighlightedText`. This file pins all of it as **paint**, through the
real theme path - the packaged `theme.qss` (or the sheet composed for High
Contrast) set as the *application* sheet, never `styleSheet()` on a widget.

**Sampling (the ACs' fixture).** A shown `Workspace` as `build_window` returns
it, its column holding three `proposed` rows (`test_app_theme_paint.py`
`_workspace_with_rows`, which selects row 0 through `set_regions`). A row's rect
is `list.visualItemRect(item)` mapped from the list's viewport into the window,
and the window is grabbed over it. "Column n" is the vertical line n px in from
the row's left edge over the row's full height less `list.spacing()` px at the
top and bottom - RED measured the spacing at **0** (story `## Handoff`), so the
band is empty and every pixel of the row's height is sampled.

**Ink.** A label's ink is read from pixels, as `test_app_theme_paint.py`'s
`_ink`: the window grabbed over the label's rect, the most frequent colour
after the ground. Under `QT_QPA_PLATFORM=offscreen` the gutter glyph and the
badge each render as exactly two colours (RED measured 371 ground, 32 ink).

Helpers are copied from `tests/ui/test_app_theme_paint.py`,
`tests/ui/test_hc_error_banner_border.py` and
`tests/ui/test_page_strip_current_bar.py` (`tests` is not a package); `PALETTE`
keeps their values so runs can be compared.

Oracle partition (MT-135 `## Contract` C-7):

- **Settled, read out:** `border-width.bar` (3), `color.accent.base`,
  `color.surface.selected`, `color.surface.hover`, `color.surface.raised` from
  `tokens_gen.TOKENS`; the ratios 5.31 / 7.54 / 1.42 (`accessibility.md` A-03)
  as WCAG 1.4.11's 3:1 side of them; the HC map through
  `theme.compose_stylesheet`.
- **Mechanical, pinned exactly:** every column-colour set in AC-1, AC-2, AC-5
  to AC-8; AC-3's geometry tuples; the `selected` property's bool values and
  the selector spelling `[selected="true"]` (C-4).
- **Oracle-free:** none.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QLabel, QWidget

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

REPO = Path(__file__).resolve().parents[2]
BASE_IN = REPO / "docs" / "wiki" / "design" / "theme.qss.in"

BAR = "border-width.bar"
ACCENT = "color.accent.base"
SELECTED = "color.surface.selected"
HOVER = "color.surface.hover"
RAISED = "color.surface.raised"

#: C-4: the property and the selector that matches it.
PROPERTY = "selected"
SELECTOR = '#translationRow[selected="true"]'

#: A five-role contrast palette, identical to test_hc_error_banner_border.py's.
PALETTE: dict[str, str] = {
    "Window": "#010203",
    "WindowText": "#FDFEFF",
    "Highlight": "#1A2B3C",
    "HighlightedText": "#C3B2A1",
    "DisabledText": "#4D5E6F",
}

#: Three `proposed` rows. `proposed`'s glyph is `text.muted`, which maps to
#: WindowText under HC, so a HighlightedText glyph can only be the override's.
ROWS = ("proposed", "proposed", "proposed")
#: J is current after `set_regions` (row 0); K is the row AC-1 selects; K + 1
#: is AC-5's next row; M is AC-6's hovered row, never K.
J = 0
K = 1
M = 2
WINDOW = QSize(1100, 720)

#: The columns sampled: the bar's three, then the first column of ground.
COLUMNS = 4


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
    qtbot, root: Path, statuses: tuple[str, ...] = ROWS
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


def _grab(widget: QWidget) -> QImage:
    """The window's painted pixels over `widget`'s rectangle."""
    window = widget.window()
    origin = widget.mapTo(window, QPoint(0, 0))
    return window.grab(QRect(origin, widget.size())).toImage()


def _ink(image: QImage) -> str:
    """The text colour: the most frequent colour after the ground."""
    counts = Counter(
        image.pixelColor(x, y).name() for y in range(image.height()) for x in range(image.width())
    )
    ordered = [colour for colour, _ in counts.most_common()]
    return ordered[1] if len(ordered) > 1 else f"no ink (only {ordered})"


def _columns(window: Workspace, row: int) -> list[set[str]]:
    """The colours on columns 0..3 of row `row`: the window grabbed over the
    item's rect, each column over the row's height less `list.spacing()` px
    at the top and bottom. The row must lie wholly in the viewport."""
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
    assert image.height() > 2 * band and image.width() > COLUMNS, f"precondition: row {row}"
    return [
        {image.pixelColor(n, y).name() for y in range(band, image.height() - band)}
        for n in range(COLUMNS)
    ]


def _bar_columns(bar: str, ground: str) -> list[set[str]]:
    """What columns 0..3 of a selected row must be: `border-width.bar` columns
    of the bar colour, then the ground."""
    width = _width(BAR)
    assert width == COLUMNS - 1, (
        f"{BAR} is {width}; this file samples {COLUMNS} columns, bar then ground"
    )
    return [{bar}] * width + [{ground}]


def _base_bar() -> list[set[str]]:
    return _bar_columns(_token_colour(ACCENT), _token_colour(SELECTED))


def _ground(token: str) -> list[set[str]]:
    return [{_token_colour(token)}] * COLUMNS


def _rows(window: Workspace) -> list[TranslationRow]:
    column = window.translation_column
    return [column.row(i) for i in range(column.list.count())]


def _layout_snapshot(window: Workspace) -> list[tuple[object, ...]]:
    """Per row: geometry, its sizeHint and its item's, and where its gutter,
    badge and editor sit in the list's viewport (AC-3)."""
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


# --- Preconditions: the colours this file compares are distinct -----------------


def test_the_bar_the_selected_ground_the_hover_ground_and_the_list_ground_are_four_colours() -> (
    None
):
    """AC-1, AC-2 and AC-6 tell bar, selected ground, hover ground and list
    ground apart by colour."""
    colours = {_token_colour(name) for name in (ACCENT, SELECTED, HOVER, RAISED)}
    assert len(colours) == 4, f"{ACCENT}, {SELECTED}, {HOVER}, {RAISED} are not distinct"


def test_the_hc_palette_highlight_pair_and_window_pair_are_four_colours() -> None:
    """AC-8 tells HighlightedText from Highlight, and both from the Window pair."""
    roles = ("Highlight", "HighlightedText", "Window", "WindowText")
    assert len({_palette_colour(role) for role in roles}) == 4
    assert set(PALETTE) == set(tokens.HC_ROLES), "the palette must carry exactly the five roles"


# --- AC-1: the selected row carries the bar -------------------------------------


def test_the_selected_translation_row_has_a_three_pixel_accent_bar_on_the_selected_ground(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-1: the packaged sheet; row k selected; its columns 0, 1, 2 are every
    pixel color.accent.base and column 3 every pixel color.surface.selected."""
    application_sheet(_packaged("theme.qss"))
    window = _workspace_with_rows(qtbot, tmp_path)
    _select(window, K)

    columns = _columns(window, K)

    expected = _base_bar()
    assert columns == expected, (
        f"the selected translation row does not carry a {BAR} {ACCENT} leading bar on "
        f"{SELECTED}: columns 0-3 are {columns}, expected {expected}"
    )


def test_a_row_selected_through_the_link_carries_the_bar_and_the_old_row_loses_it(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-1 and AC-5 by the AC's other route, `link.select(k)` - the canvas,
    the keys and `set_regions` all select this way, and the workspace moves the
    list's current row under a `QSignalBlocker` (`_on_selection_changed`), so
    `currentRowChanged` never fires. Row k carries the bar; row j, current
    before, shows the list ground."""
    application_sheet(_packaged("theme.qss"))
    window = _workspace_with_rows(qtbot, tmp_path)

    window.link.select(K)
    _settle()
    assert window.translation_column.list.currentRow() == K, "precondition: link did not move"
    selected, old = _columns(window, K), _columns(window, J)

    assert selected == _base_bar(), (
        f"row {K}, selected through the link, does not carry the bar: columns 0-3 are "
        f"{selected}, expected {_base_bar()}"
    )
    assert old == _ground(RAISED), (
        f"row {J}, current before the link moved the selection, still shows {old}"
    )


# --- AC-2: control - an unselected row carries nothing --------------------------


def test_control_every_unselected_translation_row_shows_the_list_ground_in_columns_0_to_3(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-2: row k selected; every other row's columns 0-3 are every pixel
    color.surface.raised (`QAbstractItemView`'s ground)."""
    application_sheet(_packaged("theme.qss"))
    window = _workspace_with_rows(qtbot, tmp_path)
    _select(window, K)

    others = [i for i in range(len(ROWS)) if i != K]
    wrong = {i: c for i in others if (c := _columns(window, i)) != _ground(RAISED)}
    assert wrong == {}, (
        f"unselected translation rows that are not {RAISED} ({_token_colour(RAISED)}) in "
        f"columns 0-3: {wrong}"
    )


# --- AC-3: nothing moves --------------------------------------------------------


def test_selecting_a_row_moves_no_row_gutter_badge_or_editor(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-3: row j selected, then row k: every row's geometry() and sizeHint()
    (and its item's), and every gutter's, badge's and editor's position in the
    viewport, are identical before and after. Guarded by the bar actually
    appearing on k, so the test cannot pass on a column that never repaints."""
    application_sheet(_packaged("theme.qss"))
    window = _workspace_with_rows(qtbot, tmp_path)
    _select(window, J)
    before = _layout_snapshot(window)

    _select(window, K)
    after = _layout_snapshot(window)

    accent = _token_colour(ACCENT)
    column_0 = _columns(window, K)[0]
    assert column_0 == {accent}, (
        f"precondition: row {K} was selected but shows no {ACCENT} bar (column 0 is "
        f"{column_0}) - AC-3 is about the bar appearing, so it cannot be judged yet"
    )
    moved = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert moved == [], (
        f"selecting row {K} moved rows - (row, geometry, sizeHint, item sizeHint, gutter at, "
        f"badge at, editor at) before -> after: {moved}"
    )


# --- AC-4: the bar is the contrast carrier, by the fixture table ----------------


def test_the_accent_bar_clears_three_to_one_on_both_grounds_and_the_ground_alone_does_not() -> None:
    """AC-4 (WCAG 1.4.11 as accessibility.md fixes it): accent.base on
    surface.selected (5.31) and on surface.raised (7.54) >= 3:1; NEGATIVE
    CONTROL - surface.selected on surface.raised (1.42, A-03) is below 3:1,
    which is why the selected ground alone cannot mark the row."""
    values = tokens_gen.TOKENS
    on_selected = theme.contrast_ratio(values[ACCENT], values[SELECTED])
    on_raised = theme.contrast_ratio(values[ACCENT], values[RAISED])
    ground_alone = theme.contrast_ratio(values[SELECTED], values[RAISED])

    assert on_selected >= 3.0, f"{ACCENT} on {SELECTED} is {on_selected:.2f}:1, under 3:1"
    assert on_raised >= 3.0, f"{ACCENT} on {RAISED} is {on_raised:.2f}:1, under 3:1"
    assert ground_alone < 3.0, (
        f"control: {SELECTED} on {RAISED} is {ground_alone:.2f}:1 - the ground alone "
        "clears 3:1, so the fixture table no longer says the bar is the carrier"
    )


# --- AC-5: a selection change repaints ------------------------------------------


def test_moving_the_selection_moves_the_bar_and_clearing_it_leaves_no_bar(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-5: row k selected and sampled as AC-1; row k+1 selected: k+1 now
    satisfies AC-1 and k satisfies AC-2; selecting None leaves every row
    satisfying AC-2. Fails without the unpolish/polish on the property change:
    the sheet does not re-match on its own."""
    application_sheet(_packaged("theme.qss"))
    window = _workspace_with_rows(qtbot, tmp_path)
    _select(window, K)
    bar = _base_bar()
    first = _columns(window, K)
    assert first == bar, f"precondition (AC-1): row {K} columns 0-3 are {first}, expected {bar}"

    _select(window, K + 1)
    new, old = _columns(window, K + 1), _columns(window, K)

    raised = _ground(RAISED)
    assert new == bar, (
        f"after row {K + 1} was selected it does not carry the bar: columns 0-3 are "
        f"{new}, expected {bar}"
    )
    assert old == raised, (
        f"after row {K + 1} was selected the old row {K} still shows {old}, expected "
        f"the list ground {raised}: the row was not re-polished"
    )

    _select(window, None)
    cleared = {i: c for i in range(len(ROWS)) if (c := _columns(window, i)) != raised}
    assert cleared == {}, f"with no row selected these rows still show a bar or ground: {cleared}"


# --- AC-6: hover is a ground, never a bar ---------------------------------------


def test_a_hovered_row_takes_the_hover_ground_and_never_a_bar(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-6: row k selected and row m hovered: m's columns 0-3 are every pixel
    color.surface.hover and k still satisfies AC-1; k itself hovered: its
    columns are unchanged from AC-1 (selected wins the ground); control - hover
    cleared, m satisfies AC-2."""
    application_sheet(_packaged("theme.qss"))
    window = _workspace_with_rows(qtbot, tmp_path)
    column = window.translation_column
    _select(window, K)
    bar = _base_bar()

    column.set_hovered(M)
    hovered, selected = _columns(window, M), _columns(window, K)
    assert hovered == _ground(HOVER), (
        f"hovered row {M} is not the {HOVER} ground ({_token_colour(HOVER)}) in columns 0-3, "
        f"and carries no bar: it shows {hovered}"
    )
    assert selected == bar, f"with row {M} hovered the selected row {K} shows {selected}"

    column.set_hovered(K)
    both = _columns(window, K)
    assert both == bar, (
        f"the selected row {K}, hovered, shows {both}: the selected ground and bar must win "
        f"over hover, expected {bar}"
    )

    column.set_hovered(None)
    cleared = _columns(window, M)
    assert cleared == _ground(RAISED), (
        f"control: with hover cleared row {M} shows {cleared}, not the list ground"
    )


# --- AC-7: the bar persists under lock ------------------------------------------


def test_the_selected_rows_bar_persists_while_the_column_is_disabled(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-7: row k selected; the column disabled (the widget-level lock): k's
    columns 0-2 are still every pixel color.accent.base; re-enabled, AC-1
    holds."""
    application_sheet(_packaged("theme.qss"))
    window = _workspace_with_rows(qtbot, tmp_path)
    column = window.translation_column
    _select(window, K)

    column.setEnabled(False)
    _settle()
    assert not column.row(K).isEnabled(), "precondition: the row did not follow the lock"
    locked = _columns(window, K)

    accent = [{_token_colour(ACCENT)}] * _width(BAR)
    assert locked[: _width(BAR)] == accent, (
        f"with the column disabled the selected row {K}'s columns 0-2 are "
        f"{locked[: _width(BAR)]}, not the {ACCENT} bar {accent}"
    )

    column.setEnabled(True)
    _settle()
    unlocked = _columns(window, K)
    assert unlocked == _base_bar(), f"re-enabled, the selected row {K} shows {unlocked}"


# --- C-4 / C-1: the property and the selector -----------------------------------


def test_the_selected_property_is_a_bool_that_follows_the_lists_current_row(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """C-4: `TranslationRow.set_selected` exists; the `selected` property is
    the bool True on the list's current row and the bool False on every other -
    after `set_regions`, after each `select`, and with nothing selected."""
    assert callable(getattr(TranslationRow, "set_selected", None)), (
        "TranslationRow has no set_selected"
    )
    application_sheet(_packaged("theme.qss"))
    window = _workspace_with_rows(qtbot, tmp_path)

    seen = [[(i, row.property(PROPERTY)) for i, row in enumerate(_rows(window))]]
    for current in (K, K + 1, None):
        _select(window, current)
        seen.append([(i, row.property(PROPERTY)) for i, row in enumerate(_rows(window))])

    expected = [[(i, i == current) for i in range(len(ROWS))] for current in (J, K, K + 1, None)]
    assert seen == expected, f"the rows' {PROPERTY!r} property: {seen}, expected {expected}"
    assert all(type(value) is bool for snapshot in seen for _, value in snapshot), (
        f"the {PROPERTY!r} property is not a bool on every row: {seen}"
    )


def test_the_base_template_matches_the_selected_property_by_its_string_form() -> None:
    """C-1 / C-4: the base design input spells the state selector
    `#translationRow[selected="true"]`, the string form of the bool property."""
    text = BASE_IN.read_text(encoding="utf-8")
    assert SELECTOR + " {" in text, f"theme.qss.in has no rule `{SELECTOR} {{`"


# --- AC-8: under High Contrast the bar, the glyph and the badge are HighlightedText


@pytest.mark.parametrize("label", ["rowGutter", "rowBadge"])
def test_under_high_contrast_the_selected_rows_bar_and_label_are_highlighted_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    label: str,
) -> None:
    """AC-8: the HC sheet with the five-role palette; row k selected: columns
    0-2 every pixel HighlightedText, column 3 every pixel Highlight; the ink of
    row k's `label` is HighlightedText. (Parametrised over the gutter glyph and
    the ordinal badge; the WindowText control is its own test.)"""
    application_sheet(_hc_theme())
    window = _workspace_with_rows(qtbot, tmp_path)
    _select(window, K)

    columns = _columns(window, K)
    expected = _bar_columns(_palette_colour("HighlightedText"), _palette_colour("Highlight"))
    assert columns == expected, (
        f"under High Contrast the selected row is not a {BAR} HighlightedText bar on "
        f"Highlight: columns 0-3 are {columns}, expected {expected}"
    )
    widget = window.translation_column.row(K).findChild(QLabel, label)
    assert widget is not None, f"precondition: row {K} has no QLabel#{label}"
    ink = _ink(_grab(widget))
    highlighted_text = _palette_colour("HighlightedText")
    assert ink == highlighted_text, (
        f"under High Contrast the selected row's {label} ink is {ink}, not HighlightedText "
        f"({highlighted_text})"
    )


def test_control_under_high_contrast_an_unselected_rows_gutter_is_window_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-8 control, on its own so it reports separately: row k selected, row
    j's gutter ink is WindowText - the override reaches the selected row only."""
    application_sheet(_hc_theme())
    window = _workspace_with_rows(qtbot, tmp_path)
    _select(window, K)

    control = _ink(_grab(window.translation_column.row(J).gutter))
    assert control == _palette_colour("WindowText"), (
        f"under High Contrast unselected row {J}'s gutter ink is {control}, not "
        f"WindowText ({_palette_colour('WindowText')})"
    )


def test_control_the_base_template_alone_under_high_contrast_draws_an_invisible_bar(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-8 NEGATIVE CONTROL: the base template resolved under High Contrast with
    no override appended: row k's columns 0-3 are all Highlight - accent.base and
    surface.selected both map to Highlight, so the base bar is Highlight on
    Highlight. This is the defect the override exists to fix."""
    application_sheet(_hc_base_alone())
    window = _workspace_with_rows(qtbot, tmp_path)
    _select(window, K)

    columns = _columns(window, K)

    highlight = _palette_colour("Highlight")
    assert columns == [{highlight}] * COLUMNS, (
        f"control: under the HC base template alone the selected row's columns 0-3 are "
        f"{columns}, expected all Highlight ({highlight}) - the invisible bar"
    )
