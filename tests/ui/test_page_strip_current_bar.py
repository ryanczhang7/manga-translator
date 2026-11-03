"""MT-134: the page strip marks the current page with a 3px accent bar, as paint.

`components.md` §4 ("How the current row is rendered"): the current `_PageRow`
carries a dynamic `current` property, set and re-polished by `PageStrip`, and
paints its own QSS box (`WA_StyledBackground`): ground `color.surface.selected`
and a **3px `color.accent.base` leading bar**; a non-current row paints nothing
over the list's `color.surface.raised`. §10.2: under High Contrast the current
row is `Highlight` ground with a `HighlightedText` bar, and its glyph and index
are `HighlightedText`. This file pins all of it as **paint**, through the real
theme path - the packaged `theme.qss` (or the sheet composed for High Contrast)
set as the *application* sheet, never `styleSheet()` on a widget.

**Sampling (the ACs' fixture).** A shown `PageStrip` holding
`test_page_strip_status.py`'s seven pages, built as that file builds it (shown,
then `set_pages`), grabbed through `strip.viewport().grab()`. A row's rect is
`strip.visualItemRect(item)` intersected with the viewport; "column n" is the
vertical line n px in from that rect's left edge, over the row's height less
`space.s1` px at the top and at the bottom. RED measured the band (story
`## Handoff`): with the bar built (simulated outside this file) the bar and the
ground span the row's **full** height in both modes - 121 px rows at 96 px, 26
px rows in the rail - so the `space.s1` trim is the AC's margin of safety, not a
band the paint needs.

**Ink.** A label's ink is read from pixels, as `test_app_theme_paint.py`'s
`_ink`: the label's rect in the viewport grab, the most frequent colour after
the ground. Under `QT_QPA_PLATFORM=offscreen` both the index and the glyph's
fallback box render with exactly two colours (RED measured 32 ink pixels each).

Helpers are copied from `tests/ui/test_hc_error_banner_border.py` and
`tests/ui/test_page_strip_status.py` (`tests` is not a package); `PALETTE`
keeps their values so runs can be compared.

Oracle partition (MT-134 `## Contract` C-7):

- **Settled, read out:** `border-width.bar` (3), `space.s1`,
  `color.accent.base`, `color.surface.selected`, `color.surface.raised`,
  `color.text.primary` from `tokens_gen.TOKENS`; `STRIP_RAIL_WIDTH`; the three
  ratios 5.31 / 7.54 / 1.42 (`tokens.md` 193-194, `accessibility.md` 39) as
  WCAG 1.4.11's 3:1 side of them; the HC map through
  `theme.compose_stylesheet`.
- **Mechanical, pinned exactly:** every column-colour set in AC-1, AC-2, AC-5,
  AC-6; AC-3's geometry tuples; the `current` property's bool values and the
  selector spelling `[current="true"]` (C-4).
- **Oracle-free:** none.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from mangatl.domain.page_status import PageProgress
from mangatl.ui import theme, tokens, tokens_gen
from mangatl.ui.stylesheet import base_template, hc_template
from mangatl.ui.workspace import STRIP_RAIL_WIDTH, PageStrip, _PageRow

REPO = Path(__file__).resolve().parents[2]
BASE_IN = REPO / "docs" / "wiki" / "design" / "theme.qss.in"

BAR = "border-width.bar"
BAND = "space.s1"
ACCENT = "color.accent.base"
SELECTED = "color.surface.selected"
RAISED = "color.surface.raised"

#: C-4: the property and the selector that matches it.
PROPERTY = "current"
SELECTOR = '#pageRow[current="true"]'

#: A five-role contrast palette, identical to test_hc_error_banner_border.py's.
PALETTE: dict[str, str] = {
    "Window": "#010203",
    "WindowText": "#FDFEFF",
    "Highlight": "#1A2B3C",
    "HighlightedText": "#C3B2A1",
    "DisabledText": "#4D5E6F",
}

#: The seven pages of test_page_strip_status.py, one per status, in its order.
STATUSES = (
    "pending",
    "running",
    "translated",
    "partly_reviewed",
    "fully_reviewed",
    "failed",
    "skipped",
)
SEVEN_FILENAMES = tuple(f"{i + 1:03d}-{status}.png" for i, status in enumerate(STATUSES))
SEVEN: dict[str, tuple[int, int, int]] = {
    "pending": (0, 4, 0),
    "running": (0, 4, 0),
    "translated": (0, 5, 0),
    "partly_reviewed": (12, 18, 0),
    "fully_reviewed": (4, 4, 0),
    "failed": (3, 10, 2),
    "skipped": (0, 2, 0),
}

#: Row k (AC-1, AC-5, AC-6) and the row current before it (AC-3). Row 2 is
#: `translated`, whose glyph is `text.secondary` -> WindowText under HC, so a
#: HighlightedText glyph on it can only be the override's. Row 0 (`pending`,
#: `text.muted` -> WindowText) is AC-6's non-current control. Rows 0-3 sit
#: fully inside a 600 px strip in both modes (asserted per sample).
K = 2
J = 0
CONTROL = 0
STRIP_HEIGHT = 600

#: The columns AC-1 / AC-6 sample: 0 .. bar, i.e. the bar's three and the
#: first column of ground after it.
COLUMNS = 4

RAIL = pytest.mark.parametrize("rail", [False, True], ids=["96 px strip", "28 px rail"])


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


def _seven() -> list[PageProgress]:
    return [PageProgress(status, *SEVEN[status]) for status in STATUSES]  # type: ignore[arg-type]


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _strip(qtbot, rail: bool = False) -> PageStrip:  # type: ignore[no-untyped-def]
    """The fixture: a shown strip of seven rows, as test_page_strip_status.py's
    `_strip` builds it, then switched into the rail if asked. The application
    sheet is the caller's; the strip's own `styleSheet()` stays empty."""
    strip = PageStrip()
    qtbot.addWidget(strip)
    strip.resize(strip.width(), STRIP_HEIGHT)
    with qtbot.waitExposed(strip):
        strip.show()
    _settle()
    strip.set_pages(SEVEN_FILENAMES, _seven())
    if rail:
        strip.set_rail(True)
    _settle()
    assert strip.styleSheet() == "", "the strip must take its paint from the application sheet"
    assert strip.is_rail is rail
    return strip


def _make_current(strip: PageStrip, row: int) -> None:
    strip.setCurrentRow(row)
    _settle()
    assert strip.currentRow() == row, f"precondition: setCurrentRow({row}) did not take"


def _row(strip: PageStrip, row: int) -> QWidget:
    widget = strip.itemWidget(strip.item(row))
    assert widget is not None, f"strip row {row} has no item widget"
    return widget


def _child(strip: PageStrip, row: int, name: str) -> QLabel:
    found = _row(strip, row).findChild(QLabel, name)
    assert found is not None, f"strip row {row}'s widget has no QLabel named {name}"
    return found


def _row_rect(strip: PageStrip, row: int) -> QRect:
    """Row `row`'s rect in viewport coordinates, cut to the viewport's width
    (the item is wider than the 96 px strip). The row must be wholly inside the
    viewport vertically, else a sample would read the scroll overflow."""
    viewport = strip.viewport().rect()
    rect = strip.visualItemRect(strip.item(row))
    assert rect.top() >= viewport.top() and rect.bottom() <= viewport.bottom(), (
        f"precondition: row {row} ({rect.getRect()}) is not wholly inside the viewport "
        f"({viewport.getRect()})"
    )
    cut = rect.intersected(viewport)
    assert cut.width() > COLUMNS, f"precondition: row {row} shows only {cut.width()} px"
    return cut


def _grab(strip: PageStrip) -> QImage:
    _settle()
    return strip.viewport().grab().toImage()


def _column(image: QImage, rect: QRect, n: int) -> set[str]:
    """The colours on column n of a row: the vertical line n px in from its
    left edge, `space.s1` px skipped at the top and at the bottom."""
    band = _width(BAND)
    x = rect.left() + n
    return {
        image.pixelColor(x, y).name() for y in range(rect.top() + band, rect.bottom() - band + 1)
    }


def _columns(strip: PageStrip, row: int, image: QImage | None = None) -> list[set[str]]:
    image = _grab(strip) if image is None else image
    rect = _row_rect(strip, row)
    return [_column(image, rect, n) for n in range(COLUMNS)]


def _bar_columns(bar: str, ground: str) -> list[set[str]]:
    """What columns 0..3 of a current row must be: `border-width.bar` columns
    of the bar colour, then the ground."""
    width = _width(BAR)
    assert width == COLUMNS - 1, (
        f"{BAR} is {width}; this file samples {COLUMNS} columns, bar then ground"
    )
    return [{bar}] * width + [{ground}]


def _ink(strip: PageStrip, image: QImage, label: QLabel) -> str:
    """A label's text colour, from pixels: the most frequent colour of its rect
    in the viewport grab after the ground (`test_app_theme_paint.py` `_ink`)."""
    origin = label.mapTo(strip.viewport(), QPoint(0, 0))
    rect = QRect(origin, label.size()).intersected(strip.viewport().rect())
    assert not rect.isEmpty(), f"precondition: {label.objectName()} is not in view"
    counts = Counter(
        image.pixelColor(x, y).name()
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
    )
    ordered = [colour for colour, _ in counts.most_common()]
    return ordered[1] if len(ordered) > 1 else f"no ink (only {ordered})"


def _layout_snapshot(strip: PageStrip) -> list[tuple[object, ...]]:
    """Per row: geometry, sizeHint, and where its glyph and label sit in the
    viewport (AC-3)."""
    viewport = strip.viewport()
    snapshot = []
    for row in range(strip.count()):
        widget = _row(strip, row)
        snapshot.append(
            (
                row,
                widget.geometry().getRect(),
                widget.sizeHint().toTuple(),
                _child(strip, row, "pageGlyph").mapTo(viewport, QPoint(0, 0)).toTuple(),
                _child(strip, row, "pageLabel").mapTo(viewport, QPoint(0, 0)).toTuple(),
            )
        )
    return snapshot


# --- Preconditions: the colours this file compares are distinct -----------------


def test_the_bar_the_selected_ground_and_the_list_ground_are_three_colours() -> None:
    """AC-1 and AC-2 tell bar, current ground and list ground apart by colour."""
    colours = {_token_colour(name) for name in (ACCENT, SELECTED, RAISED)}
    assert len(colours) == 3, f"{ACCENT}, {SELECTED}, {RAISED} are not distinct: {colours}"


def test_the_hc_palette_highlight_pair_and_window_pair_are_four_colours() -> None:
    """AC-6 tells HighlightedText from Highlight, and both from the Window pair."""
    roles = ("Highlight", "HighlightedText", "Window", "WindowText")
    assert len({_palette_colour(role) for role in roles}) == 4
    assert set(PALETTE) == set(tokens.HC_ROLES), "the palette must carry exactly the five roles"


# --- AC-1: the current row carries the bar --------------------------------------


@RAIL
def test_the_current_page_row_has_a_three_pixel_accent_bar_on_the_selected_ground(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    rail: bool,
) -> None:
    """AC-1: the packaged sheet; row k current; its columns 0, 1, 2 are every
    pixel color.accent.base and column 3 every pixel color.surface.selected.
    (Parametrised over the rail too: the 3px rail margin must not cover it.)"""
    application_sheet(_packaged("theme.qss"))
    strip = _strip(qtbot, rail)
    _make_current(strip, K)

    columns = _columns(strip, K)

    expected = _bar_columns(_token_colour(ACCENT), _token_colour(SELECTED))
    assert columns == expected, (
        f"the current page row ({'rail' if rail else '96 px'}) does not carry a {BAR} "
        f"{ACCENT} leading bar on {SELECTED}: columns 0-3 are {columns}, expected {expected}"
    )


# --- AC-2: control - a non-current row carries nothing --------------------------


def test_control_every_non_current_page_row_shows_the_list_ground_in_columns_0_to_3(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-2: every row other than k that lies wholly in the viewport: columns
    0-3 are every pixel color.surface.raised (`QAbstractItemView`'s ground)."""
    application_sheet(_packaged("theme.qss"))
    strip = _strip(qtbot)
    _make_current(strip, K)
    image = _grab(strip)
    viewport = strip.viewport().rect()

    raised = _token_colour(RAISED)
    sampled, wrong = [], {}
    for row in range(strip.count()):
        rect = strip.visualItemRect(strip.item(row))
        if row == K or rect.bottom() > viewport.bottom():
            continue
        sampled.append(row)
        columns = _columns(strip, row, image)
        if columns != [{raised}] * COLUMNS:
            wrong[row] = columns
    assert len(sampled) >= 2, f"precondition: only rows {sampled} besides {K} are in view"
    assert wrong == {}, (
        f"non-current page rows that are not {RAISED} ({raised}) in columns 0-3: {wrong}"
    )


# --- AC-3: nothing moves --------------------------------------------------------


@RAIL
def test_making_a_page_current_moves_no_row_glyph_or_index(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    rail: bool,
) -> None:
    """AC-3: row j current, then row k: every row's geometry() and sizeHint(),
    and every glyph's and index's position in the viewport, are identical
    before and after. Guarded by the bar actually appearing on k, so the test
    cannot pass on a strip that never repaints."""
    application_sheet(_packaged("theme.qss"))
    strip = _strip(qtbot, rail)
    _make_current(strip, J)
    before = _layout_snapshot(strip)

    _make_current(strip, K)
    after = _layout_snapshot(strip)

    accent = _token_colour(ACCENT)
    column_0 = _columns(strip, K)[0]
    assert column_0 == {accent}, (
        f"precondition: row {K} became current but shows no {ACCENT} bar (column 0 is "
        f"{column_0}) - AC-3 is about the bar appearing, so it cannot be judged yet"
    )
    moved = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert moved == [], (
        f"making row {K} current ({'rail' if rail else '96 px'}) moved rows - "
        f"(row, geometry, sizeHint, glyph at, index at) before -> after: {moved}"
    )


def test_in_the_rail_every_row_keeps_its_glyph_and_index_clear_of_the_bar(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """C-4: in the 28 px rail every row, current or not, takes a constant left
    contents margin of `border-width.bar`, so its glyph and index start at or
    right of the bar; and every row's hint still fits the rail."""
    application_sheet(_packaged("theme.qss"))
    strip = _strip(qtbot, rail=True)
    _make_current(strip, K)

    bar = _width(BAR)
    under, too_wide = {}, {}
    for row in range(strip.count()):
        widget = _row(strip, row)
        lefts = (
            _child(strip, row, "pageGlyph").geometry().left(),
            _child(strip, row, "pageLabel").geometry().left(),
        )
        if min(lefts) < bar:
            under[row] = lefts
        if widget.sizeHint().width() > STRIP_RAIL_WIDTH:
            too_wide[row] = widget.sizeHint().width()
    assert under == {}, (
        f"rail rows whose (glyph, index) left edge sits under the {bar}px bar: {under}"
    )
    assert too_wide == {}, f"rail rows wider than {STRIP_RAIL_WIDTH} px: {too_wide}"


# --- AC-4: the bar is the contrast carrier, by the fixture table ----------------


def test_the_accent_bar_clears_three_to_one_on_both_grounds_and_the_ground_alone_does_not() -> None:
    """AC-4 (WCAG 1.4.11 as accessibility.md fixes it): accent.base on
    surface.selected (5.31) and on surface.raised (7.54) >= 3:1; NEGATIVE
    CONTROL - surface.selected on surface.raised (1.42) is below 3:1, which is
    why a ground alone cannot mark the current row."""
    tokens_ = tokens_gen.TOKENS
    on_selected = theme.contrast_ratio(tokens_[ACCENT], tokens_[SELECTED])
    on_raised = theme.contrast_ratio(tokens_[ACCENT], tokens_[RAISED])
    ground_alone = theme.contrast_ratio(tokens_[SELECTED], tokens_[RAISED])

    assert on_selected >= 3.0, f"{ACCENT} on {SELECTED} is {on_selected:.2f}:1, under 3:1"
    assert on_raised >= 3.0, f"{ACCENT} on {RAISED} is {on_raised:.2f}:1, under 3:1"
    assert ground_alone < 3.0, (
        f"control: {SELECTED} on {RAISED} is {ground_alone:.2f}:1 - the ground alone "
        "clears 3:1, so the fixture table no longer says the bar is the carrier"
    )


# --- AC-5: a selection change repaints ------------------------------------------


def test_moving_the_current_page_moves_the_bar_to_the_new_row(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-5: row k current and sampled as AC-1; row k+1 made current; k+1 now
    satisfies AC-1 and k satisfies AC-2. Fails without the unpolish/polish on
    the property change: the sheet does not re-match on its own."""
    application_sheet(_packaged("theme.qss"))
    strip = _strip(qtbot)
    _make_current(strip, K)
    bar = _bar_columns(_token_colour(ACCENT), _token_colour(SELECTED))
    first = _columns(strip, K)
    assert first == bar, f"precondition (AC-1): row {K} columns 0-3 are {first}, expected {bar}"

    _make_current(strip, K + 1)
    image = _grab(strip)
    new, old = _columns(strip, K + 1, image), _columns(strip, K, image)

    raised = [{_token_colour(RAISED)}] * COLUMNS
    assert new == bar, (
        f"after row {K + 1} became current it does not carry the bar: columns 0-3 are "
        f"{new}, expected {bar}"
    )
    assert old == raised, (
        f"after row {K + 1} became current the old row {K} still shows {old}, expected "
        f"the list ground {raised}: the row was not re-polished"
    )


def test_the_current_property_is_a_bool_owned_by_the_strip(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """C-4: `_PageRow.set_current` exists; the `current` property is the bool
    True on the current row and the bool False on every other, before and
    after a change - the value `#pageRow[current="true"]` matches."""
    assert callable(getattr(_PageRow, "set_current", None)), "_PageRow has no set_current"
    application_sheet(_packaged("theme.qss"))
    strip = _strip(qtbot)

    seen = []
    for current in (K, K + 1):
        _make_current(strip, current)
        seen.append([(row, _row(strip, row).property(PROPERTY)) for row in range(strip.count())])

    expected = [[(row, row == current) for row in range(len(STATUSES))] for current in (K, K + 1)]
    assert seen == expected, f"the rows' {PROPERTY!r} property: {seen}, expected {expected}"
    assert all(type(value) is bool for snapshot in seen for _, value in snapshot), (
        f"the {PROPERTY!r} property is not a bool on every row: {seen}"
    )


def test_the_base_template_matches_the_current_property_by_its_string_form() -> None:
    """C-1 / C-4: the base design input spells the state selector
    `#pageRow[current="true"]`, the string form of the bool property."""
    text = BASE_IN.read_text(encoding="utf-8")
    assert SELECTOR + " {" in text, f"theme.qss.in has no rule `{SELECTOR} {{`"


# --- AC-6: under High Contrast the bar and the text are HighlightedText ---------


@RAIL
def test_under_high_contrast_the_current_page_row_bar_glyph_and_index_are_highlighted_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    rail: bool,
) -> None:
    """AC-6: the HC sheet with the five-role palette; row k current: columns
    0-2 every pixel HighlightedText, column 3 every pixel Highlight; the ink of
    row k's glyph and index is HighlightedText. (The non-current WindowText
    control is the next test, so it reports on its own.)"""
    application_sheet(_hc_theme())
    strip = _strip(qtbot, rail)
    _make_current(strip, K)
    image = _grab(strip)

    columns = _columns(strip, K, image)
    expected = _bar_columns(_palette_colour("HighlightedText"), _palette_colour("Highlight"))
    mode = "rail" if rail else "96 px"
    assert columns == expected, (
        f"under High Contrast ({mode}) the current page row is not a {BAR} HighlightedText "
        f"bar on Highlight: columns 0-3 are {columns}, expected {expected}"
    )
    highlighted_text = _palette_colour("HighlightedText")
    inks = {name: _ink(strip, image, _child(strip, K, name)) for name in ("pageGlyph", "pageLabel")}
    assert inks == {"pageGlyph": highlighted_text, "pageLabel": highlighted_text}, (
        f"under High Contrast ({mode}) the current row's glyph and index ink is {inks}, "
        f"not HighlightedText ({highlighted_text})"
    )


@RAIL
def test_control_under_high_contrast_a_non_current_page_glyph_is_window_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    rail: bool,
) -> None:
    """AC-6 control, on its own so it reports separately: row k current, row
    0's glyph ink is WindowText - the override reaches the current row only."""
    application_sheet(_hc_theme())
    strip = _strip(qtbot, rail)
    _make_current(strip, K)
    image = _grab(strip)

    control = _ink(strip, image, _child(strip, CONTROL, "pageGlyph"))
    assert control == _palette_colour("WindowText"), (
        f"under High Contrast non-current row {CONTROL}'s glyph ink is {control}, not "
        f"WindowText ({_palette_colour('WindowText')})"
    )


@RAIL
def test_control_the_base_template_alone_under_high_contrast_draws_an_invisible_bar(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    rail: bool,
) -> None:
    """AC-6 NEGATIVE CONTROL: the base template resolved under High Contrast with
    no override appended: row k's columns 0-3 are all Highlight - accent.base and
    surface.selected both map to Highlight, so the base bar is Highlight on
    Highlight. This is the defect the override exists to fix."""
    application_sheet(_hc_base_alone())
    strip = _strip(qtbot, rail)
    _make_current(strip, K)

    columns = _columns(strip, K)

    highlight = _palette_colour("Highlight")
    assert columns == [{highlight}] * COLUMNS, (
        f"control: under the HC base template alone ({'rail' if rail else '96 px'}) the "
        f"current row's columns 0-3 are {columns}, expected all Highlight ({highlight}) - "
        "the invisible bar"
    )
