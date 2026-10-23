"""MT-090 AC-1..AC-3: in the 28 px rail a page index is drawn only where it fits.

**Oracle partition (story `## Contract`, block 5).** All three criteria are
*mechanical*: nothing is calibrated, every number is read out.

- `STRIP_RAIL_WIDTH` is the budget; a row's horizontal cost is its widget's
  `sizeHint().width()` (block 2: the rail row has zero contents margins).
- Whether "100" fits is a fact of the font the suite actually has, so AC-2's
  premise is asserted against that font before the split is: under
  `QT_QPA_PLATFORM=offscreen` with no stylesheet (block 5) "99" is 24 px and
  "100" is 36 px. A font where "100" fits fails the premise, loudly, rather than
  letting the split test pass for the wrong reason.
- The hidden row's tooltip is matched as a whole string, both against
  `page_tooltip_text` and against a literal, so the helper and the strip are
  pinned independently and a tooltip that merely *contains* the number fails.

**Fixture (block 6).** A bare `Workspace` opened at 1100 / 1900 px, the page
strip filled with `set_pages(filenames, progress)` directly: no project, no
sheet, no thumbnails. 120 rows per test.

**Cost.** Every check over the 120 rows accumulates its violations and asserts
once, so a failure lists every offending row and the loop stays cheap under
coverage instrumentation. Nothing waits on a clock.

**RED.** `page_tooltip_text` does not exist in `mangatl.ui.workspace`: the file
fails at collection and no assertion in it has run. The controls' expected
values are in the story's handoff.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from mangatl.domain.page_status import PageProgress
from mangatl.ui.workspace import (
    STRIP_RAIL_WIDTH,
    PageStrip,
    Workspace,
    page_accessible_text,
    page_tooltip_text,
)

# --- Settled: MT-048's widths ---------------------------------------------------
WIDE = 1900
NARROW = 1100
HEIGHT = 720

# --- The 120-page chapter of AC-1 ----------------------------------------------
TOTAL = 120
FILENAMES = tuple(f"p{n:03d}.png" for n in range(1, TOTAL + 1))
#: AC-2's split under the suite's font: rows 1..99 draw their index, 100..120 do not.
FIRST_HIDDEN = 100
DRAWN_ROWS = range(1, FIRST_HIDDEN)
HIDDEN_ROWS = range(FIRST_HIDDEN, TOTAL + 1)

# --- AC-2's unchanged control: a chapter of 7 pages -----------------------------
SEVEN_FILENAMES = tuple(f"{n:03d}.png" for n in range(1, 8))

EM_DASH = "\N{EM DASH}"


def _pending(count: int) -> list[PageProgress]:
    return [PageProgress("pending", 0, 0, 0) for _ in range(count)]


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _open(qtbot, width: int, filenames: tuple[str, ...] = FILENAMES) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.resize(width, HEIGHT)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    window.page_strip.set_pages(filenames, _pending(len(filenames)))
    _settle()
    return window


def _resize(window: Workspace, width: int) -> None:
    window.resize(width, HEIGHT)
    _settle()


def _label(strip: PageStrip, row: int) -> QLabel:
    widget = strip.itemWidget(strip.item(row))
    assert widget is not None, f"strip row {row} has no item widget"
    found = widget.findChild(QLabel, "pageLabel")
    assert found is not None, f"strip row {row}'s widget has no QLabel named pageLabel"
    return found


def _glyph(strip: PageStrip, row: int) -> QLabel:
    widget = strip.itemWidget(strip.item(row))
    assert widget is not None, f"strip row {row} has no item widget"
    found = widget.findChild(QLabel, "pageGlyph")
    assert found is not None, f"strip row {row}'s widget has no QLabel named pageGlyph"
    return found


def _page_tooltip(n: int, filename: str, total: int = TOTAL) -> str:
    """AC-1's tooltip for 1-based page `n`, written out literally - not through
    `page_tooltip_text`, so the helper is checked against it rather than trusted."""
    return f"Page {n} of {total} {EM_DASH} {filename}"


def _shown_and_tooltips(strip: PageStrip) -> list[tuple[int, bool, str]]:
    """Every row as (1-based page, index label visible, item tooltip)."""
    return [
        (i + 1, _label(strip, i).isVisibleTo(strip), strip.item(i).toolTip())
        for i in range(strip.count())
    ]


def _expected_full(filenames: tuple[str, ...]) -> list[tuple[int, bool, str]]:
    return [(n, True, name) for n, name in enumerate(filenames, start=1)]


def _expected_rail_split() -> list[tuple[int, bool, str]]:
    return [
        (n, True, name) if n < FIRST_HIDDEN else (n, False, _page_tooltip(n, name))
        for n, name in enumerate(FILENAMES, start=1)
    ]


# =============================================================================
# Block 1: the tooltip text, alone
# =============================================================================


def test_the_page_tooltip_numbers_pages_from_one_and_joins_the_filename_with_a_spaced_em_dash() -> (
    None
):
    assert page_tooltip_text(99, 120, "p100.png") == "Page 100 of 120 — p100.png"
    assert page_tooltip_text(0, 120, "p001.png") == "Page 1 of 120 — p001.png"
    assert page_tooltip_text(11, 12, "012-last.png") == "Page 12 of 12 — 012-last.png"


# =============================================================================
# AC-1: every rail row fits and stays readable
# =============================================================================


def test_at_1100_px_every_row_of_a_120_page_chapter_fits_the_rail_and_still_says_its_number(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    window = _open(qtbot, NARROW)
    strip = window.page_strip
    assert strip.is_rail
    assert strip.count() == TOTAL

    too_wide: list[tuple[int, int]] = []
    glyph_hidden: list[int] = []
    unreadable: list[tuple[int, bool, str, str]] = []
    wrong_text: list[tuple[int, str]] = []
    wrong_name: list[tuple[int, object]] = []
    heights: set[int] = set()
    for i, filename in enumerate(FILENAMES):
        n = i + 1
        item = strip.item(i)
        row = strip.itemWidget(item)
        hint = row.sizeHint()
        heights.add(hint.height())
        if hint.width() > STRIP_RAIL_WIDTH:
            too_wide.append((n, hint.width()))
        if not _glyph(strip, i).isVisibleTo(strip):
            glyph_hidden.append(n)
        label = _label(strip, i)
        drawn = label.isVisibleTo(strip) and label.text() == str(n)
        told = item.toolTip() == _page_tooltip(n, filename)
        if not (drawn or told):
            unreadable.append((n, label.isVisibleTo(strip), label.text(), item.toolTip()))
        if item.text() != str(n):
            wrong_text.append((n, item.text()))
        name = item.data(Qt.ItemDataRole.AccessibleTextRole)
        expected_name = f"Page {n} of {TOTAL}, {filename}, not translated yet"
        if name != expected_name or name != page_accessible_text(
            i, TOTAL, filename, PageProgress("pending", 0, 0, 0)
        ):
            wrong_name.append((n, name))

    assert too_wide == [], f"rail rows wider than {STRIP_RAIL_WIDTH} px (page, width): {too_wide}"
    assert glyph_hidden == [], f"rail rows whose status glyph is hidden: {glyph_hidden}"
    assert len(heights) == 1, f"rail rows do not share one height: {sorted(heights)}"
    assert unreadable == [], (
        "rail rows that neither draw their index nor carry 'Page N of 120 — filename' "
        f"as tooltip (page, label visible, label text, tooltip): {unreadable}"
    )
    assert wrong_text == [], f"items whose text is not their 1-based index: {wrong_text}"
    assert wrong_name == [], f"items whose accessible name changed: {wrong_name}"


# =============================================================================
# AC-2: the split lands exactly where the font puts it
# =============================================================================


def test_at_1100_px_pages_1_to_99_draw_their_index_and_pages_100_to_120_move_it_to_the_tooltip(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    window = _open(qtbot, NARROW)
    strip = window.page_strip
    assert strip.is_rail

    # The premise, asserted against the font the rail label actually has: a
    # font where "100" fits would make the split below the wrong test.
    font = _label(strip, 0).font()
    three, two = QLabel("100"), QLabel("99")
    three.setFont(font)
    two.setFont(font)
    assert three.sizeHint().width() > STRIP_RAIL_WIDTH, (
        f'premise: "100" is {three.sizeHint().width()} px in the rail font, which fits '
        f"{STRIP_RAIL_WIDTH} px - this font does not exercise the split"
    )
    assert two.sizeHint().width() <= STRIP_RAIL_WIDTH, (
        f'premise: "99" is {two.sizeHint().width()} px in the rail font, wider than '
        f"{STRIP_RAIL_WIDTH} px - this font moves the split below page 100"
    )

    assert _shown_and_tooltips(strip) == _expected_rail_split()
    # The strip's tooltip is the helper's text, page for page.
    helper = [(n, page_tooltip_text(n - 1, TOTAL, FILENAMES[n - 1])) for n in HIDDEN_ROWS]
    assert [(n, strip.item(n - 1).toolTip()) for n in HIDDEN_ROWS] == helper
    # A hidden index keeps its text (block 3), and its glyph is still drawn.
    assert [_label(strip, n - 1).text() for n in HIDDEN_ROWS] == [str(n) for n in HIDDEN_ROWS]
    assert [_glyph(strip, n - 1).isVisibleTo(strip) for n in HIDDEN_ROWS] == [True] * len(
        HIDDEN_ROWS
    )


def test_at_1100_px_a_7_page_chapter_draws_every_index_with_the_filename_as_tooltip(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    window = _open(qtbot, NARROW, SEVEN_FILENAMES)
    strip = window.page_strip
    assert strip.is_rail

    assert _shown_and_tooltips(strip) == _expected_full(SEVEN_FILENAMES)
    assert [_label(strip, i).text() for i in range(7)] == [str(n) for n in range(1, 8)]


# =============================================================================
# AC-3: the full strip and the crossing are untouched
# =============================================================================


def test_at_1900_px_every_row_of_a_120_page_chapter_draws_its_index_with_the_filename_as_tooltip(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    window = _open(qtbot, WIDE)
    strip = window.page_strip
    assert not strip.is_rail

    assert _shown_and_tooltips(strip) == _expected_full(FILENAMES)
    assert [_label(strip, i).text() for i in range(TOTAL)] == [str(n) for n in range(1, TOTAL + 1)]


def test_crossing_1900_to_1100_to_1900_hides_and_restores_pages_100_to_120_and_their_tooltips(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    window = _open(qtbot, WIDE)
    strip = window.page_strip
    indices = [str(n) for n in range(1, TOTAL + 1)]

    seen = []
    for width, rail, expected in (
        (WIDE, False, _expected_full(FILENAMES)),
        (NARROW, True, _expected_rail_split()),
        (WIDE, False, _expected_full(FILENAMES)),
    ):
        _resize(window, width)
        assert strip.is_rail is rail, f"at {width} px the strip's rail state is {strip.is_rail}"
        seen.append(width)
        assert _shown_and_tooltips(strip) == expected, f"after crossing {seen}"
        assert [strip.item(i).text() for i in range(TOTAL)] == indices, f"after crossing {seen}"


def test_crossing_1100_to_1900_to_1100_restores_and_hides_pages_100_to_120_again(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    window = _open(qtbot, NARROW)
    strip = window.page_strip
    indices = [str(n) for n in range(1, TOTAL + 1)]

    seen = []
    for width, rail, expected in (
        (NARROW, True, _expected_rail_split()),
        (WIDE, False, _expected_full(FILENAMES)),
        (NARROW, True, _expected_rail_split()),
    ):
        _resize(window, width)
        assert strip.is_rail is rail, f"at {width} px the strip's rail state is {strip.is_rail}"
        seen.append(width)
        assert _shown_and_tooltips(strip) == expected, f"after crossing {seen}"
        assert [strip.item(i).text() for i in range(TOTAL)] == indices, f"after crossing {seen}"
    # Re-entering the rail keeps every row inside it, hidden rows included.
    widths = [strip.itemWidget(strip.item(i)).sizeHint().width() for i in range(TOTAL)]
    assert [(n, w) for n, w in enumerate(widths, 1) if w > STRIP_RAIL_WIDTH] == []
