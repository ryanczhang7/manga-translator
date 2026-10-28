"""MT-086 AC-1..AC-4: every page in the strip carries its status as a glyph.

**Oracle partition (story `## Contract`).**

- *Settled*, read out and never derived: the glyph and colour-token tables of
  block 2 (written below with the same `\\N{...}` names the Contract uses), the
  phrases of block 3, the 1900 / 1100 px widths and `STRIP_RAIL_WIDTH` (MT-048),
  and AC-2's 12 of 18.
- *Mechanical*, pinned exactly: `PageStrip.set_pages(filenames, progress)`,
  `set_progress`, `progress`; the item widget's `QLabel#pageGlyph` (text = the
  glyph, dynamic property `status`) and `QLabel#pageLabel`; `item.text()`
  unchanged from MT-048; `AccessibleTextRole` = block 3; the rail row's
  `sizeHint().width() <= STRIP_RAIL_WIDTH`; `TranslationColumn.linesChanged` /
  `statuses()`; AC-4's "not reloaded" as a call count on `load_chapter` and
  `set_pages`.
- *Oracle-free*: none.

**Distinctness is code points, not pixels** (PO-1, the PO's measurement in
`### PLANNED -> RED`): under `QT_QPA_PLATFORM=offscreen` every glyph renders as
the same fallback box, so a rendered-mask test would be vacuous. `collisions`
is the one function the uniqueness claim goes through (the
`test_status_glyphs_one_colour.py` precedent), with its own negative control.

**Colour.** The colour lives only in the generated `theme.qss` (AC-3). Two
observations: the sheet's text, regexed per status against
`tokens_gen.TOKENS`; and the glyph label's `WindowText` after the packaged
sheet is applied to its window. The second is what `QStyleSheetStyle` writes
into the polished widget's palette - measured in RED on today's `rowGutter`
rule: the rule's colour after polish, the OLD colour when the property changes
without an unpolish/polish, and the sheet's base `QLabel` colour when no rule
matches - so it discriminates a missing rule and a missing re-polish. The
literal scan of `workspace.py` is MT-015 AC-7's
`tests/ui/test_workspace_colour_literals.py`, not repeated here.

**RED.** `mangatl.domain.page_status` does not exist, and neither do
`PAGE_STATUS_GLYPHS`, `PAGE_STATUS_COLOR_TOKENS` or `page_accessible_text` in
`mangatl.ui.workspace`: the file fails at collection and no assertion in it,
the controls included, has run. Expected values are in the story's handoff.

**Timing.** Nothing waits on a clock; every wait is `qtbot.waitExposed` /
`waitUntil` on window activation, as in the MT-017 / MT-048 suites.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from importlib.resources import files
from itertools import combinations
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QListWidgetItem, QWidget

from mangatl.domain.line import Line, OcrResult
from mangatl.domain.page import Chapter, Page
from mangatl.domain.page_status import PAGE_STATUSES, PageProgress
from mangatl.domain.region import RawRegion
from mangatl.store.lines import commit_line, read_review_lines
from mangatl.store.project import PAGE_DONE, PAGE_STALE, Project, create_project
from mangatl.ui import tokens_gen
from mangatl.ui.link import OrderedRegion
from mangatl.ui.workspace import (
    PAGE_STATUS_COLOR_TOKENS,
    PAGE_STATUS_GLYPHS,
    STRIP_RAIL_WIDTH,
    PageStrip,
    TranslationColumn,
    Workspace,
    page_accessible_text,
)

# --- Settled: block 2, verbatim -------------------------------------------------
DESIGN_GLYPHS = {
    "pending": "\N{WHITE CIRCLE}",
    "running": "\N{CIRCLE WITH LEFT HALF BLACK}",
    "translated": "\N{WHITE DIAMOND}",
    "partly_reviewed": "\N{WHITE DIAMOND CONTAINING BLACK SMALL DIAMOND}",
    "fully_reviewed": "\N{BLACK DIAMOND}",
    "failed": "\N{WARNING SIGN}",
    "skipped": "\N{BLACK RECTANGLE}",
}
DESIGN_CODE_POINTS = {
    "pending": 0x25CB,
    "running": 0x25D0,
    "translated": 0x25C7,
    "partly_reviewed": 0x25C8,
    "fully_reviewed": 0x25C6,
    "failed": 0x26A0,
    "skipped": 0x25AC,
}
DESIGN_COLOR_TOKENS = {
    "pending": "color.text.muted",
    "running": "color.accent.base",
    "translated": "color.text.secondary",
    "partly_reviewed": "color.status.success",
    "fully_reviewed": "color.status.success",
    "failed": "color.status.danger",
    "skipped": "color.text.disabled",
}
DESIGN_ORDER = tuple(DESIGN_GLYPHS)
#: Block 2: seven rows, six distinct tokens (partly and fully share success).
DESIGN_TOKEN_COUNT = 6

# --- Settled: MT-048's widths ---------------------------------------------------
WIDE = 1900
NARROW = 1100
HEIGHT = 720
DESIGN_RAIL_WIDTH = 28

# --- One strip with a page in every state (AC-1). `running` is reachable only
# through `set_pages` (Out of scope: nothing sets it). ---------------------------
SEVEN_FILENAMES = tuple(f"{i + 1:03d}-{status}.png" for i, status in enumerate(DESIGN_ORDER))
SEVEN: dict[str, tuple[int, int, int]] = {
    "pending": (0, 4, 0),
    "running": (0, 4, 0),
    "translated": (0, 5, 0),
    "partly_reviewed": (12, 18, 0),
    "fully_reviewed": (4, 4, 0),
    "failed": (3, 10, 2),
    "skipped": (0, 2, 0),
}
#: Block 3's phrase for each of SEVEN's rows, exactly.
SEVEN_PHRASES = {
    "pending": "not translated yet",
    "running": "translating",
    "translated": "0 of 5 lines reviewed",
    "partly_reviewed": "12 of 18 lines reviewed",
    "fully_reviewed": "4 of 4 lines reviewed",
    "failed": "3 of 10 lines reviewed, 2 failed",
    "skipped": "skipped, source changed",
}

NO = Qt.KeyboardModifier.NoModifier


def _seven() -> list[PageProgress]:
    return [PageProgress(status, *SEVEN[status]) for status in DESIGN_ORDER]  # type: ignore[arg-type]


def collisions(values: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Every pair of names whose values are equal, in the mapping's order.

    The one place "distinct" is decided (copied from
    `test_status_glyphs_one_colour.py`: `tests` is not a package)."""
    return [(a, b) for a, b in combinations(values, 2) if values[a] == values[b]]


def _sheet() -> str:
    """The packaged, generated sheet - what the app applies."""
    return files("mangatl.ui").joinpath("theme.qss").read_text(encoding="utf-8")


THEME_IN = Path(__file__).resolve().parents[2] / "docs" / "wiki" / "design" / "theme.qss.in"


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _glyph(strip: PageStrip, row: int) -> QLabel:
    widget = strip.itemWidget(strip.item(row))
    assert widget is not None, f"strip row {row} has no item widget"
    found = widget.findChild(QLabel, "pageGlyph")
    assert found is not None, f"strip row {row}'s widget has no QLabel named pageGlyph"
    return found


def _label(strip: PageStrip, row: int) -> QLabel:
    widget = strip.itemWidget(strip.item(row))
    assert widget is not None, f"strip row {row} has no item widget"
    found = widget.findChild(QLabel, "pageLabel")
    assert found is not None, f"strip row {row}'s widget has no QLabel named pageLabel"
    return found


def _ink(label: QLabel) -> QColor:
    return label.palette().color(QPalette.ColorRole.WindowText)


def _token(status: str) -> QColor:
    return QColor(tokens_gen.TOKENS[DESIGN_COLOR_TOKENS[status]])


def _accessible(strip: PageStrip) -> list[str]:
    return [
        strip.item(row).data(Qt.ItemDataRole.AccessibleTextRole) for row in range(strip.count())
    ]


def _shown(strip: PageStrip) -> list[tuple[str, Any, str]]:
    """`(glyph text, status property, ink name)` per row."""
    return [
        (
            _glyph(strip, row).text(),
            _glyph(strip, row).property("status"),
            _ink(_glyph(strip, row)).name(),
        )
        for row in range(strip.count())
    ]


def _expected_shown(statuses: list[str]) -> list[tuple[str, Any, str]]:
    return [(DESIGN_GLYPHS[s], s, _token(s).name()) for s in statuses]


# =============================================================================
# AC-1 / AC-3: block 2's tables, read out
# =============================================================================


def test_the_page_status_glyphs_are_block_2s_table() -> None:
    assert dict(PAGE_STATUS_GLYPHS) == DESIGN_GLYPHS


def test_the_page_status_glyphs_are_keyed_in_page_statuses_order() -> None:
    assert tuple(PAGE_STATUS_GLYPHS) == PAGE_STATUSES == DESIGN_ORDER


def test_each_page_glyph_is_the_one_code_point_the_design_names() -> None:
    assert {s: [ord(c) for c in g] for s, g in PAGE_STATUS_GLYPHS.items()} == {
        s: [cp] for s, cp in DESIGN_CODE_POINTS.items()
    }


def test_the_seven_page_glyphs_are_pairwise_distinct_code_points() -> None:
    """AC-1 / A-15.7 / PO-1: no two statuses share a glyph, so one colour
    cannot collapse any pair (DV-2 mutates `translated` back to the circle)."""
    assert collisions(PAGE_STATUS_GLYPHS) == []
    assert len(set(PAGE_STATUS_GLYPHS.values())) == 7


def test_the_collision_checker_reports_exactly_the_one_colliding_pair() -> None:
    """Negative control: the design table before PO-1 (`translated` sharing
    `pending`'s hollow circle) is reported, and nothing else."""
    before_po1 = dict(DESIGN_GLYPHS, translated="\N{WHITE CIRCLE}")
    assert collisions(before_po1) == [("pending", "translated")]
    assert collisions(DESIGN_GLYPHS) == []


def test_the_page_glyph_colour_tokens_are_block_2s_table() -> None:
    assert dict(PAGE_STATUS_COLOR_TOKENS) == DESIGN_COLOR_TOKENS
    assert tuple(PAGE_STATUS_COLOR_TOKENS) == DESIGN_ORDER
    assert len(set(PAGE_STATUS_COLOR_TOKENS.values())) == DESIGN_TOKEN_COUNT


def test_every_page_glyph_colour_token_is_a_generated_token() -> None:
    missing = [t for t in PAGE_STATUS_COLOR_TOKENS.values() if t not in tokens_gen.TOKENS]
    assert missing == []


_RULE = re.compile(r'QLabel#pageGlyph\[status="([^"]*)"\]\s*\{([^}]*)\}')


def test_the_generated_sheet_colours_each_page_glyph_by_its_token() -> None:
    """AC-3: one `QLabel#pageGlyph[status="..."]` rule per status, in
    `theme.qss`, whose only declaration is `color:` = that token's value."""
    rules = _RULE.findall(_sheet())
    names = [name for name, _ in rules]
    assert sorted(names) == sorted(DESIGN_ORDER), f"pageGlyph rules in theme.qss: {names}"
    colours = {}
    for name, body in rules:
        declared = re.fullmatch(r"\s*color:\s*(#[0-9A-Fa-f]{6})\s*;\s*", body)
        assert declared is not None, f"rule {name!r} is not one colour declaration: {body!r}"
        colours[name] = declared.group(1)
    assert colours == {s: tokens_gen.TOKENS[t] for s, t in DESIGN_COLOR_TOKENS.items()}


def test_the_sheet_source_names_each_page_glyph_colour_by_token_never_by_value() -> None:
    """Block 5: `theme.qss.in` spells `@{token}`, so the colour resolves
    through `tokens.toml` (and `[hc.map]`) rather than a literal."""
    source = THEME_IN.read_text(encoding="utf-8")
    missing = [
        s
        for s, token in DESIGN_COLOR_TOKENS.items()
        if not re.search(
            r'QLabel#pageGlyph\[status="'
            + s
            + r'"\]\s*\{\s*color:\s*@\{'
            + re.escape(token)
            + r"\}\s*;\s*\}",
            source,
        )
    ]
    assert missing == [], f"theme.qss.in has no token-coloured pageGlyph rule for {missing}"


# =============================================================================
# AC-2 / block 3: the accessible name
# =============================================================================


@pytest.mark.parametrize("status", DESIGN_ORDER)
def test_the_accessible_name_ends_with_the_statuss_phrase(status: str) -> None:
    progress = PageProgress(status, *SEVEN[status])  # type: ignore[arg-type]
    assert page_accessible_text(0, 3, "001.png", progress) == (
        f"Page 1 of 3, 001.png, {SEVEN_PHRASES[status]}"
    )


def test_the_accessible_name_numbers_the_page_from_one() -> None:
    progress = PageProgress("partly_reviewed", 12, 18, 0)
    assert page_accessible_text(6, 20, "filename.png", progress) == (
        "Page 7 of 20, filename.png, 12 of 18 lines reviewed"
    )


def test_a_pending_or_skipped_page_says_its_phrase_whatever_its_counts() -> None:
    """PO-4: one phrase per status, not "0 of 0 lines reviewed"."""
    assert page_accessible_text(0, 1, "a.png", PageProgress("pending", 2, 5, 1)) == (
        "Page 1 of 1, a.png, not translated yet"
    )
    assert page_accessible_text(0, 1, "a.png", PageProgress("skipped", 2, 5, 1)) == (
        "Page 1 of 1, a.png, skipped, source changed"
    )
    assert page_accessible_text(0, 1, "a.png", PageProgress("running", 2, 5, 1)) == (
        "Page 1 of 1, a.png, translating"
    )


def test_a_page_with_no_lines_reads_zero_of_zero_reviewed() -> None:
    assert page_accessible_text(0, 1, "a.png", PageProgress("translated", 0, 0, 0)) == (
        "Page 1 of 1, a.png, 0 of 0 lines reviewed"
    )


# =============================================================================
# Block 4: PageStrip.set_pages / set_progress / progress, on its own
# =============================================================================


def _strip(qtbot) -> PageStrip:  # type: ignore[no-untyped-def]
    strip = PageStrip()
    qtbot.addWidget(strip)
    strip.setStyleSheet(_sheet())
    strip.resize(strip.width(), 600)
    with qtbot.waitExposed(strip):
        strip.show()
    _settle()
    return strip


def test_set_pages_gives_every_row_its_progress_glyph_status_ink_and_name(qtbot) -> None:  # type: ignore[no-untyped-def]
    strip = _strip(qtbot)
    strip.set_pages(SEVEN_FILENAMES, _seven())
    _settle()

    assert strip.count() == 7
    assert [strip.progress(i) for i in range(7)] == _seven()
    assert _shown(strip) == _expected_shown(list(DESIGN_ORDER))
    assert _accessible(strip) == [
        f"Page {i + 1} of 7, {name}, {SEVEN_PHRASES[s]}"
        for i, (name, s) in enumerate(zip(SEVEN_FILENAMES, DESIGN_ORDER, strict=True))
    ]


def test_set_pages_with_no_pages_leaves_an_empty_strip(qtbot) -> None:  # type: ignore[no-untyped-def]
    strip = _strip(qtbot)
    strip.set_pages(SEVEN_FILENAMES, _seven())
    strip.set_pages([], [])
    assert strip.count() == 0


def test_set_progress_updates_one_row_in_place_and_keeps_the_current_row(qtbot) -> None:  # type: ignore[no-untyped-def]
    strip = _strip(qtbot)
    strip.set_pages(SEVEN_FILENAMES, _seven())
    strip.setCurrentRow(2)
    _settle()
    item_before: QListWidgetItem = strip.item(2)
    others_before = [(_shown(strip)[i], _accessible(strip)[i]) for i in range(7) if i != 2]

    strip.set_progress(2, PageProgress("partly_reviewed", 1, 5, 0))
    _settle()

    assert strip.item(2) is item_before, "set_progress rebuilt the item"
    assert strip.currentRow() == 2
    assert strip.item(2).isSelected()
    assert strip.progress(2) == PageProgress("partly_reviewed", 1, 5, 0)
    assert _shown(strip)[2] == _expected_shown(["partly_reviewed"])[0], (
        "the glyph's text, status or colour did not follow (missing unpolish/polish?)"
    )
    assert _accessible(strip)[2] == f"Page 3 of 7, {SEVEN_FILENAMES[2]}, 1 of 5 lines reviewed"
    assert [(_shown(strip)[i], _accessible(strip)[i]) for i in range(7) if i != 2] == (
        others_before
    )


def test_set_progress_leaves_the_items_own_text_alone(qtbot) -> None:  # type: ignore[no-untyped-def]
    strip = _strip(qtbot)
    strip.set_pages(SEVEN_FILENAMES, _seven())
    strip.set_progress(0, PageProgress("fully_reviewed", 4, 4, 0))
    assert strip.item(0).text() == "1"  # MT-087 (PO-1): the index in the full strip too
    strip.set_rail(True)
    strip.set_progress(0, PageProgress("failed", 0, 4, 1))
    assert strip.item(0).text() == "1"
    assert _label(strip, 0).text() == "1"


def test_crossing_into_the_rail_and_back_keeps_glyphs_current_row_and_selection(qtbot) -> None:  # type: ignore[no-untyped-def]
    strip = _strip(qtbot)
    strip.set_pages(SEVEN_FILENAMES, _seven())
    strip.setCurrentRow(4)
    _settle()

    strip.set_rail(True)
    _settle()
    rail = (_shown(strip), [strip.item(i).text() for i in range(7)], _accessible(strip))
    rail_current = (strip.currentRow(), strip.item(4).isSelected())
    strip.set_rail(False)
    _settle()

    assert rail[0] == _expected_shown(list(DESIGN_ORDER))
    assert rail[1] == [str(i + 1) for i in range(7)]
    assert rail[2] == _accessible(strip)
    assert rail_current == (4, True)
    assert _shown(strip) == _expected_shown(list(DESIGN_ORDER))
    # MT-087 (PO-1): the full strip's text is the index too, so rail and full agree.
    assert [strip.item(i).text() for i in range(7)] == [str(i + 1) for i in range(7)]
    assert (strip.currentRow(), strip.item(4).isSelected()) == (4, True)


# =============================================================================
# AC-1: in the Workspace, at 1900 px and at 1100 px
# =============================================================================


def _open(qtbot, width: int) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.setStyleSheet(_sheet())
    window.resize(width, HEIGHT)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()
    return window


def test_the_rail_width_is_the_design_number() -> None:
    assert STRIP_RAIL_WIDTH == DESIGN_RAIL_WIDTH


def test_at_1900_px_every_row_shows_its_glyph_in_its_colour_and_its_index(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, WIDE)
    strip = window.page_strip
    strip.set_pages(SEVEN_FILENAMES, _seven())
    _settle()

    assert not strip.is_rail
    assert _shown(strip) == _expected_shown(list(DESIGN_ORDER))
    assert [_glyph(strip, i).isVisibleTo(strip) for i in range(7)] == [True] * 7
    # MT-087 (PO-1): the index, under the thumbnail; the filename is the tooltip.
    assert [strip.item(i).text() for i in range(7)] == [str(i + 1) for i in range(7)]
    assert [_label(strip, i).text() for i in range(7)] == [str(i + 1) for i in range(7)]
    assert [_label(strip, i).isVisibleTo(strip) for i in range(7)] == [True] * 7


def test_at_1100_px_every_rail_row_shows_its_glyph_in_its_colour_and_its_index(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)
    strip = window.page_strip
    strip.set_pages(SEVEN_FILENAMES, _seven())
    _settle()

    assert strip.is_rail
    assert _shown(strip) == _expected_shown(list(DESIGN_ORDER))
    assert [_glyph(strip, i).isVisibleTo(strip) for i in range(7)] == [True] * 7
    assert [strip.item(i).text() for i in range(7)] == [str(i + 1) for i in range(7)]
    assert [_label(strip, i).text() for i in range(7)] == [str(i + 1) for i in range(7)]
    assert [_label(strip, i).isVisibleTo(strip) for i in range(7)] == [True] * 7


def test_at_1100_px_every_rail_row_fits_the_rail(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)
    strip = window.page_strip
    strip.set_pages(SEVEN_FILENAMES, _seven())
    _settle()

    widths = [strip.itemWidget(strip.item(i)).sizeHint().width() for i in range(7)]
    assert [w for w in widths if w > STRIP_RAIL_WIDTH] == [], f"row size hints {widths}"


@pytest.mark.parametrize("width", [NARROW, WIDE])
def test_every_row_reads_its_status_phrase_at_any_width(qtbot, width: int) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, width)
    window.page_strip.set_pages(SEVEN_FILENAMES, _seven())
    assert _accessible(window.page_strip) == [
        f"Page {i + 1} of 7, {name}, {SEVEN_PHRASES[s]}"
        for i, (name, s) in enumerate(zip(SEVEN_FILENAMES, DESIGN_ORDER, strict=True))
    ]


# =============================================================================
# Real projects through Workspace.load_chapter (block 6)
# =============================================================================

PAGE = QSize(600, 800)


def _png(size: QSize) -> bytes:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


@pytest.fixture(scope="session")
def page_png() -> bytes:
    return _png(PAGE)


@pytest.fixture(scope="session")
def mask_png() -> bytes:
    return _png(QSize(4, 4))


def _ring(i: int) -> tuple[tuple[int, int], ...]:
    """Small, non-overlapping, inside a 600 x 800 page for up to 36 regions."""
    x, y = 10 + 30 * (i % 18), 10 + 30 * (i // 18)
    return ((x, y), (x + 20, y), (x + 20, y + 20), (x, y + 20), (x, y))


def _regions(project: Project, ordinal: int, count: int, mask: bytes) -> None:
    project.write_regions(
        ordinal,
        [
            RawRegion(polygon=_ring(i), mask=mask, confidence=0.9, kind="bubble")
            for i in range(count)
        ],
    )


def _lines(
    project: Project, ordinal: int, count: int, mask: bytes, proposed: dict[int, str] | None = None
) -> None:
    """`count` regions with OCR'd lines; proposals for every index unless given."""
    _regions(project, ordinal, count, mask)
    project.write_lines(ordinal, [OcrResult(f"ja {i}", ocr_empty=False) for i in range(count)])
    project.write_proposed(
        ordinal, proposed if proposed is not None else {i: f"en {i}" for i in range(count)}
    )


def _set_status(project: Project, ordinal: int, status: str) -> None:
    with project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ? WHERE ordinal = ?", (status, ordinal))


def _project(tmp_path: Path, page_png: bytes, filenames: tuple[str, ...]) -> Project:
    source = tmp_path / "chapter"
    source.mkdir()
    for name in filenames:
        (source / name).write_bytes(page_png)
    chapter = Chapter(
        source_dir=source,
        pages=tuple(
            Page(
                ordinal=i, filename=n, width=PAGE.width(), height=PAGE.height(), sha256=f"{i}" * 64
            )
            for i, n in enumerate(filenames)
        ),
    )
    return create_project(chapter, tmp_path / "chapter.mtproj")


#: Every state the store can produce, and its expected derivation and phrase.
STORE_PAGES: tuple[tuple[str, PageProgress, str], ...] = (
    ("001.png", PageProgress("pending", 0, 2, 0), "not translated yet"),
    ("002.png", PageProgress("translated", 0, 3, 0), "0 of 3 lines reviewed"),
    ("003.png", PageProgress("partly_reviewed", 1, 3, 0), "1 of 3 lines reviewed"),
    ("004.png", PageProgress("fully_reviewed", 2, 2, 0), "2 of 2 lines reviewed"),
    ("005.png", PageProgress("failed", 1, 3, 1), "1 of 3 lines reviewed, 1 failed"),
    ("006.png", PageProgress("skipped", 0, 2, 0), "skipped, source changed"),
    ("007.png", PageProgress("translated", 0, 0, 0), "0 of 0 lines reviewed"),
    ("008.png", PageProgress("translated", 0, 2, 0), "0 of 2 lines reviewed"),
)


@pytest.fixture
def every_state(tmp_path: Path, page_png: bytes, mask_png: bytes) -> Iterator[Project]:
    with _project(tmp_path, page_png, tuple(name for name, _, _ in STORE_PAGES)) as project:
        _lines(project, 0, 2, mask_png)  # pending: the run has not reached it
        _lines(project, 1, 3, mask_png)  # done, nothing reviewed
        _set_status(project, 1, PAGE_DONE)
        _lines(project, 2, 3, mask_png)  # done, 1 of 3 accepted
        _set_status(project, 2, PAGE_DONE)
        commit_line(project, 2, 0, None, "accepted")
        _lines(project, 3, 2, mask_png)  # done, edited + reverted
        _set_status(project, 3, PAGE_DONE)
        commit_line(project, 3, 0, "Mine.", "edited")
        commit_line(project, 3, 1, "en 1", "reverted")
        _lines(project, 4, 3, mask_png, {0: "en 0", 1: "en 1"})  # region 2 untranslated
        _set_status(project, 4, PAGE_DONE)
        commit_line(project, 4, 0, None, "accepted")
        _lines(project, 5, 2, mask_png)  # stale: the source changed
        _set_status(project, 5, PAGE_STALE)
        _set_status(project, 6, PAGE_DONE)  # done, no regions at all
        _regions(project, 7, 2, mask_png)  # done, regions whose OCR never ran
        _set_status(project, 7, PAGE_DONE)
        yield project


def test_load_chapter_derives_every_pages_status_from_the_store(
    qtbot, every_state: Project
) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, WIDE)
    window.load_chapter(every_state)
    _settle()
    strip = window.page_strip

    assert [strip.progress(i) for i in range(strip.count())] == [p for _, p, _ in STORE_PAGES]
    assert _shown(strip) == _expected_shown([p.status for _, p, _ in STORE_PAGES])
    assert _accessible(strip) == [
        f"Page {i + 1} of {len(STORE_PAGES)}, {name}, {phrase}"
        for i, (name, _, phrase) in enumerate(STORE_PAGES)
    ]


@pytest.fixture
def twelve_of_eighteen(tmp_path: Path, page_png: bytes, mask_png: bytes) -> Iterator[Project]:
    """AC-2: page 2 of 2 is done, 18 regions, 12 committed (4 accepted, 4
    edited, 4 reverted) and 6 proposed."""
    with _project(tmp_path, page_png, ("001.png", "002.png")) as project:
        _lines(project, 1, 18, mask_png)
        _set_status(project, 1, PAGE_DONE)
        for i in range(4):
            commit_line(project, 1, i, None, "accepted")
        for i in range(4, 8):
            commit_line(project, 1, i, f"mine {i}", "edited")
        for i in range(8, 12):
            commit_line(project, 1, i, f"en {i}", "reverted")
        yield project


def test_a_done_page_with_12_of_18_lines_committed_reads_12_of_18_lines_reviewed(
    qtbot,  # type: ignore[no-untyped-def]
    twelve_of_eighteen: Project,
) -> None:
    window = _open(qtbot, NARROW)
    window.load_chapter(twelve_of_eighteen)
    _settle()
    strip = window.page_strip

    assert strip.item(1).data(Qt.ItemDataRole.AccessibleTextRole) == (
        "Page 2 of 2, 002.png, 12 of 18 lines reviewed"
    )
    assert strip.progress(1) == PageProgress("partly_reviewed", 12, 18, 0)
    assert _shown(strip)[1] == _expected_shown(["partly_reviewed"])[0]


# =============================================================================
# Block 6: TranslationColumn.statuses / linesChanged
# =============================================================================


def _line(index: int, status: str, final_en: str | None = None) -> Line:
    return Line(
        reading_index=index,
        source_ja=f"ja {index}",
        proposed_en=f"en {index}",
        final_en=final_en,
        status=status,  # type: ignore[arg-type]
        edited_at=None,
    )


def _column(qtbot, lines: list[Line | None]) -> TranslationColumn:  # type: ignore[no-untyped-def]
    column = TranslationColumn()
    qtbot.addWidget(column)
    column.resize(380, 400)
    count = len(lines)
    column.set_rows(
        [OrderedRegion(region_id=i, polygon=_ring(i)) for i in range(count)],
        [f"ja {i}" for i in range(count)],
        [f"en {i}" for i in range(count)],
        lines=lines,
    )
    with qtbot.waitExposed(column):
        column.show()
    _settle()
    return column


def test_an_empty_column_has_no_statuses(qtbot) -> None:  # type: ignore[no-untyped-def]
    assert _column(qtbot, []).statuses() == ()


def test_the_column_reports_each_rows_status_in_row_order(qtbot) -> None:  # type: ignore[no-untyped-def]
    column = _column(
        qtbot, [_line(0, "accepted"), None, _line(2, "failed"), _line(3, "edited", "x")]
    )
    # A `None` line is MT-016's unsaved proposal: it shows, and reports, proposed.
    assert column.statuses() == ("accepted", "proposed", "failed", "edited")


def test_accepting_a_row_emits_lines_changed_and_the_new_status_is_reported(qtbot) -> None:  # type: ignore[no-untyped-def]
    column = _column(qtbot, [_line(0, "proposed"), _line(1, "proposed")])
    seen: list[tuple[str, ...]] = []
    column.linesChanged.connect(lambda: seen.append(column.statuses()))

    QTest.mouseClick(column.row(1).accept_button, Qt.MouseButton.LeftButton)
    _settle()

    assert seen, "linesChanged was not emitted when a row was accepted"
    assert seen[-1] == ("proposed", "accepted")
    assert column.statuses() == ("proposed", "accepted")


# =============================================================================
# AC-4: the current page's row follows the column, without a reload
# =============================================================================


@pytest.fixture
def reviewing(tmp_path: Path, page_png: bytes, mask_png: bytes) -> Iterator[Project]:
    """Page 0 done with 3 proposed lines; page 1 done with 1; page 2 stale
    with 2; page 3 pending with 2."""
    with _project(tmp_path, page_png, ("001.png", "002.png", "003.png", "004.png")) as project:
        _lines(project, 0, 3, mask_png)
        _set_status(project, 0, PAGE_DONE)
        _lines(project, 1, 1, mask_png)
        _set_status(project, 1, PAGE_DONE)
        _lines(project, 2, 2, mask_png)
        _set_status(project, 2, PAGE_STALE)
        _lines(project, 3, 2, mask_png)
        yield project


class _Calls:
    """Counts calls to a bound method replaced on its instance."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, owner: object, name: str) -> None:
        self.count = 0
        real: Callable[..., Any] = getattr(owner, name)

        def counting(*args: Any, **kwargs: Any) -> Any:
            self.count += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, counting)


def _reviewing(qtbot, project: Project, ordinal: int) -> Workspace:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(ordinal)
    _settle()
    return window


def _focus(qtbot, widget: QWidget) -> None:  # type: ignore[no-untyped-def]
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(widget.hasFocus)
    _settle()


def _edit(qtbot, window: Workspace, index: int, text: str) -> None:  # type: ignore[no-untyped-def]
    editor = window.translation_column.row(index).editor
    _focus(qtbot, editor)
    editor.selectAll()
    QTest.keyClicks(editor, text)
    QTest.keyClick(editor, Qt.Key.Key_Return, NO)
    _settle()


def _click(window: Workspace, index: int, button: str) -> None:
    QTest.mouseClick(
        getattr(window.translation_column.row(index), button), Qt.MouseButton.LeftButton
    )
    _settle()


def test_the_call_counter_counts_a_call_through_the_instance(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control for AC-4's "not reloaded": the instrument sees a reload."""
    window = _reviewing(qtbot, reviewing, 0)
    loads = _Calls(monkeypatch, window, "load_chapter")
    window.load_chapter(reviewing)
    assert loads.count == 1


def test_accepting_a_line_updates_the_current_pages_glyph_and_name_without_a_reload(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _reviewing(qtbot, reviewing, 0)
    strip = window.page_strip
    before = strip.progress(0)
    loads = _Calls(monkeypatch, window, "load_chapter")
    rebuilds = _Calls(monkeypatch, strip, "set_pages")

    _click(window, 0, "accept_button")

    assert before == PageProgress("translated", 0, 3, 0)
    assert strip.progress(0) == PageProgress("partly_reviewed", 1, 3, 0)
    assert _shown(strip)[0] == _expected_shown(["partly_reviewed"])[0]
    assert _glyph(strip, 0).text() == "\N{WHITE DIAMOND CONTAINING BLACK SMALL DIAMOND}"
    assert strip.item(0).data(Qt.ItemDataRole.AccessibleTextRole) == (
        "Page 1 of 4, 001.png, 1 of 3 lines reviewed"
    )
    assert (loads.count, rebuilds.count) == (0, 0), "the chapter was reloaded"
    assert strip.currentRow() == 0


def test_editing_and_reverting_lines_walk_the_page_to_fully_reviewed_without_a_reload(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _reviewing(qtbot, reviewing, 0)
    strip = window.page_strip
    loads = _Calls(monkeypatch, window, "load_chapter")
    rebuilds = _Calls(monkeypatch, strip, "set_pages")

    _edit(qtbot, window, 1, "My own words.")
    after_edit = (strip.progress(0), window.translation_column.statuses())
    _click(window, 0, "accept_button")
    _edit(qtbot, window, 2, "Another.")
    after_all = (strip.progress(0), _shown(strip)[0])
    _click(window, 2, "revert_button")
    after_revert = (strip.progress(0), window.translation_column.statuses())

    assert after_edit == (
        PageProgress("partly_reviewed", 1, 3, 0),
        ("proposed", "edited", "proposed"),
    )
    assert after_all == (
        PageProgress("fully_reviewed", 3, 3, 0),
        _expected_shown(["fully_reviewed"])[0],
    )
    # PO-2: a reverted line was looked at and decided - still reviewed.
    assert after_revert == (
        PageProgress("fully_reviewed", 3, 3, 0),
        ("accepted", "edited", "reverted"),
    )
    assert strip.item(0).data(Qt.ItemDataRole.AccessibleTextRole) == (
        "Page 1 of 4, 001.png, 3 of 3 lines reviewed"
    )
    assert (loads.count, rebuilds.count) == (0, 0), "the chapter was reloaded"


def test_a_change_on_the_current_page_updates_that_pages_row_and_no_other(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
) -> None:
    window = _reviewing(qtbot, reviewing, 0)
    window.page_strip.setCurrentRow(1)
    _settle()
    others_before = [window.page_strip.progress(i) for i in (0, 2, 3)]

    _click(window, 0, "accept_button")

    assert window.page_strip.progress(1) == PageProgress("fully_reviewed", 1, 1, 0)
    assert [window.page_strip.progress(i) for i in (0, 2, 3)] == others_before


# =============================================================================
# MT-097: a save still pending when the page changes belongs to the page left
# =============================================================================


def _stored_row(project: Project, ordinal: int, index: int) -> tuple[Any, ...]:
    """One stored line as `(status, final_en, proposed_en, source_ja, edited)`."""
    line = read_review_lines(project, ordinal)[index]
    assert line is not None, f"page {ordinal} region {index} has no line"
    return (
        line.status,
        line.final_en,
        line.proposed_en,
        line.source_ja,
        line.edited_at is not None,
    )


def test_changing_page_with_a_save_pending_leaves_the_new_pages_row_its_own(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
) -> None:
    """MT-097 AC-1: the flushed save of page 1's accept re-derives page 1's
    row, never page 2's - which is the page being entered."""
    window = _reviewing(qtbot, reviewing, 0)
    strip = window.page_strip
    before = [strip.progress(i) for i in range(4)]

    _click(window, 0, "accept_button")
    strip.setCurrentRow(1)
    _settle()

    assert before[1] == PageProgress("translated", 0, 1, 0)
    entered = strip.progress(1)
    assert entered == before[1], (
        f"page 2's strip row now reads {entered!r}, not its own {before[1]!r}:"
        " the save flushed on leaving page 1 was written onto the page entered"
    )
    assert strip.progress(0) == PageProgress("partly_reviewed", 1, 3, 0)
    assert [strip.progress(i) for i in (2, 3)] == before[2:]
    assert strip.currentRow() == 1


def test_a_save_pending_when_the_page_changes_still_reaches_the_project_file(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
) -> None:
    """MT-097 AC-2: reordering the flush neither drops nor delays the save.

    Read straight after the page change and a `flush()` of the column - no
    wait - so a save deferred past the page change fails too."""
    window = _reviewing(qtbot, reviewing, 0)

    _click(window, 0, "accept_button")
    pending = _stored_row(reviewing, 0, 0)
    window.page_strip.setCurrentRow(1)
    _settle()
    window.translation_column.flush()

    # Precondition: the accept was still unsaved when the page changed.
    assert pending == ("proposed", None, "en 0", "ja 0", False)
    assert _stored_row(reviewing, 0, 0) == ("accepted", None, "en 0", "ja 0", True)
    assert [_stored_row(reviewing, 0, i) for i in (1, 2)] == [
        ("proposed", None, "en 1", "ja 1", False),
        ("proposed", None, "en 2", "ja 2", False),
    ]
    assert _stored_row(reviewing, 1, 0) == ("proposed", None, "en 0", "ja 0", False)


# =============================================================================
# MT-099: a save that keeps failing across the page change still belongs to the
# page left
# =============================================================================

#: AC-2's value, read out of the shipped code (MT-099 `## Test plan`): page 1's
#: row after its accept's save has failed once, with no page change - and the
#: same value when only the first of the page change's flushes fails.
PAGE_1_AFTER_A_FAILED_SAVE = PageProgress("partly_reviewed", 1, 3, 0)


def _saves_fail(
    monkeypatch: pytest.MonkeyPatch, *, first_only: bool = False
) -> list[tuple[Any, ...]]:
    """Replace the name `_saver` calls with one that raises - on every call, or
    on the first only and then saves through the real `commit_line`. Returns
    the calls it saw, as `(page_ordinal, reading_index, text, status)`."""
    calls: list[tuple[Any, ...]] = []

    def full_disk(project: Project, ordinal: int, index: int, text: Any, status: Any) -> None:
        calls.append((ordinal, index, text, status))
        if first_only and len(calls) > 1:
            commit_line(project, ordinal, index, text, status)
            return
        raise OSError("disk is full")

    monkeypatch.setattr("mangatl.ui.workspace.commit_line", full_disk)
    return calls


def _accept_then_change_page_with_every_save_failing(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Workspace, list[PageProgress], list[tuple[Any, ...]]]:
    return _accept_then_change_page(qtbot, project, _saves_fail(monkeypatch))


def _accept_then_change_page(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    calls: list[tuple[Any, ...]],
) -> tuple[Workspace, list[PageProgress], list[tuple[Any, ...]]]:
    """Accept page 1's row 0, then select page 2 before its save timer fires,
    with saves failing as `calls`' patch was told to."""
    window = _reviewing(qtbot, project, 0)
    strip = window.page_strip
    before = [strip.progress(i) for i in range(4)]

    _click(window, 0, "accept_button")
    strip.setCurrentRow(1)
    _settle()

    # Preconditions: the save really failed on leaving page 1 and was retried
    # after the page changed - the sequence this story is about.
    assert len(calls) >= 2, f"the accept's save was attempted {len(calls)} time(s), not retried"
    assert set(calls) == {(0, 0, None, "accepted")}, calls
    assert strip.currentRow() == 1
    return window, before, calls


def test_a_save_failing_again_after_the_page_change_leaves_the_new_pages_row_its_own(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MT-099 AC-1: the retried, failed save of page 1's accept re-renders a
    page 1 row, and must not re-derive page 2's strip row from it."""
    window, before, _ = _accept_then_change_page_with_every_save_failing(
        qtbot, reviewing, monkeypatch
    )
    strip = window.page_strip

    assert before[1] == PageProgress("translated", 0, 1, 0)
    entered = strip.progress(1)
    assert entered == before[1], (
        f"page 2's strip row now reads {entered!r}, not its own {before[1]!r}:"
        " the save that failed again after the page change was written onto"
        " the page entered"
    )
    assert [strip.progress(i) for i in (2, 3)] == before[2:]


def test_a_save_failing_again_after_the_page_change_leaves_the_left_pages_row_as_one_failure_did(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MT-099 AC-2: the retried failure changes no row but its own page's, so
    page 1's row reads what one failed flush leaves it reading."""
    window, before, _ = _accept_then_change_page_with_every_save_failing(
        qtbot, reviewing, monkeypatch
    )

    assert before[0] == PageProgress("translated", 0, 3, 0)
    left = window.page_strip.progress(0)
    assert left == PAGE_1_AFTER_A_FAILED_SAVE, (
        f"page 1's strip row reads {left!r} after its save failed again on the"
        f" next page, not {PAGE_1_AFTER_A_FAILED_SAVE!r} as after one failure"
    )


def test_a_save_that_succeeds_on_retry_after_the_page_change_leaves_the_new_pages_row_its_own(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MT-099 AC-3: the first save of page 1's accept fails on leaving page 1
    and the retry, after the page change, succeeds. The success re-renders a
    page 1 row and must not re-derive page 2's strip row from it; the accept
    reaches the project file."""
    window, before, _ = _accept_then_change_page(
        qtbot, reviewing, _saves_fail(monkeypatch, first_only=True)
    )
    strip = window.page_strip

    assert before[1] == PageProgress("translated", 0, 1, 0)
    # The store is checked before the strip, so it is observed even while the
    # strip assertion below fails.
    assert _stored_row(reviewing, 0, 0) == ("accepted", None, "en 0", "ja 0", True), (
        "the retried save of page 1's accept did not reach the project file"
    )
    entered = strip.progress(1)
    assert entered == before[1], (
        f"page 2's strip row now reads {entered!r}, not its own {before[1]!r}:"
        " the save that succeeded on retry after the page change was written"
        " onto the page entered"
    )
    assert [strip.progress(i) for i in (2, 3)] == before[2:]


@pytest.mark.parametrize(
    ("ordinal", "expected"),
    [
        (2, PageProgress("skipped", 1, 2, 0)),
        (3, PageProgress("pending", 1, 2, 0)),
    ],
    ids=["stale-stays-skipped", "pending-stays-pending"],
)
def test_a_live_update_keeps_the_pages_stored_state(
    qtbot,  # type: ignore[no-untyped-def]
    reviewing: Project,
    ordinal: int,
    expected: PageProgress,
) -> None:
    """Block 6: the refresh reads the page's stored status, not just the lines."""
    window = _reviewing(qtbot, reviewing, ordinal)

    _click(window, 0, "accept_button")

    assert window.page_strip.progress(ordinal) == expected
    assert _shown(window.page_strip)[ordinal] == _expected_shown([expected.status])[0]
