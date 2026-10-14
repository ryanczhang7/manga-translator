"""MT-048: the workspace reallocates space at the 1440 px breakpoint.

Every number here is READ OUT of `docs/wiki/design/layout.md` §"The one
breakpoint - 1440px" (as amended for MT-048) and the story's `## Contract`
Block 1. None is derived from what the widgets measure, and none is tuned:

                       < 1440           >= 1440
    PageStrip          28 px rail       96 px
    strip item text    "1", "2", ...    the filename
    TranslationColumn  300 (default)    380 (default)
    header             cost readout     the chapter name, then the readout

The deltas in AC-3 / AC-4 are arithmetic over those numbers, written out where
they are asserted. Every geometry assertion is exact: no tolerance anywhere.

The helpers `_settle`, `_open`, `_remaining` and `_drag_column_to` are COPIED
from `tests/ui/test_workspace.py` (MT-015), unchanged: `tests` is not a
package, so they cannot be imported (Contract Block 6 allows either).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QLabel

from mangatl.domain.page import Chapter, Page
from mangatl.store.project import Project, create_project
from mangatl.ui import tokens_gen
from mangatl.ui.canvas import LOADED
from mangatl.ui.intake import display_name
from mangatl.ui.workspace import (
    BREAKPOINT_WIDTH,
    COLUMN_DEFAULT_NARROW,
    COLUMN_DEFAULT_WIDE,
    STRIP_RAIL_WIDTH,
    STRIP_WIDTH,
    Workspace,
)

# --- The widths the acceptance criteria name --------------------------------
NARROW = 1100  # AC-1, AC-3, AC-4, AC-6: the window minimum, below the breakpoint
WIDE = 1900  # AC-1, AC-3, AC-4, AC-5: above the breakpoint
EXACT = 1440  # AC-1: exactly on the breakpoint, which is wide (`>=`)
JUST_BELOW = 1439  # layout.md "How the breakpoint is judged": one pixel under is narrow
BELOW = 1400  # AC-2: the end of a resize that stays below
ABOVE = 1500  # AC-2: the start of a resize that stays above
HEIGHT = 720

# --- A real three-page chapter ----------------------------------------------
# Distinct pixel sizes, so which page the canvas shows is observable from the
# outside (AC-6) without reaching into `Workspace`'s private state.
PAGES: tuple[tuple[str, QSize], ...] = (
    ("001.png", QSize(64, 96)),
    ("002.png", QSize(72, 104)),
    ("003.png", QSize(80, 112)),
)
# Longer than intake's 40-character NAME_LIMIT, so `display_name` middle-cuts it
# and the header cannot pass by showing the bare folder name (AC-5).
LONG_FOLDER = "a-chapter-folder-whose-name-runs-well-past-forty-characters"


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _open(qtbot, width: int = NARROW, height: int = HEIGHT) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.resize(width, height)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    return window


def _remaining(window: Workspace) -> int:
    splitter = window.splitter
    return (
        splitter.width()
        - window.page_strip.width()
        - window.translation_column.width()
        - 2 * splitter.handleWidth()
    )


def _drag_column_to(window: Workspace, splitter_pos: int) -> None:
    """Drag the divider between canvas and column (handle index 2)."""
    window.splitter.moveSplitter(splitter_pos, 2)
    _settle()


def _resize(window: Workspace, width: int) -> None:
    window.resize(width, HEIGHT)
    _settle()
    assert window.width() == width, "the window did not settle at the requested width"


def _image(size: QSize) -> QImage:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.COLOR_TEXT_PRIMARY))
    return image


@pytest.fixture
def chapter_project(tmp_path: Path) -> Iterator[Project]:
    """A real project over three genuine PNGs in a long-named folder."""
    source = tmp_path / LONG_FOLDER
    source.mkdir()
    pages = []
    for ordinal, (filename, size) in enumerate(PAGES):
        assert _image(size).save(str(source / filename), "PNG")
        pages.append(
            Page(
                ordinal=ordinal,
                filename=filename,
                width=size.width(),
                height=size.height(),
                sha256=str(ordinal) * 64,
            )
        )
    chapter = Chapter(source_dir=source, pages=tuple(pages))
    with create_project(chapter, tmp_path / "chapter.mtproj") as project:
        yield project


def _open_loaded(qtbot, project: Project, width: int) -> Workspace:  # type: ignore[no-untyped-def]
    window = _open(qtbot, width)
    window.load_chapter(project)
    _settle()
    return window


def _item_texts(window: Workspace) -> list[str]:
    strip = window.page_strip
    return [strip.item(row).text() for row in range(strip.count())]


def _item_accessible_texts(window: Workspace) -> list[str]:
    strip = window.page_strip
    return [
        strip.item(row).data(Qt.ItemDataRole.AccessibleTextRole) for row in range(strip.count())
    ]


def _expected_accessible_texts() -> list[str]:
    total = len(PAGES)
    return [f"Page {i + 1} of {total}, {name}" for i, (name, _) in enumerate(PAGES)]


def _filenames() -> list[str]:
    return [name for name, _ in PAGES]


def _indices() -> list[str]:
    return [str(i + 1) for i in range(len(PAGES))]


def _chapter_label(window: Workspace) -> QLabel:
    found = window.header.findChild(QLabel, "chapterName")
    assert found is not None, "the header has no QLabel named chapterName"
    assert found is window.chapter_name
    return found


# =============================================================================
# The constants are the design's numbers (Contract Block 1). Each settled
# number is written as a literal HERE and only here; every other test uses
# the name, so a drifted constant fails this test by name.
# =============================================================================


def test_the_breakpoint_constants_are_the_numbers_layout_md_settles() -> None:
    assert BREAKPOINT_WIDTH == 1440
    assert STRIP_WIDTH == 96
    assert STRIP_RAIL_WIDTH == 28
    assert COLUMN_DEFAULT_NARROW == 300
    assert COLUMN_DEFAULT_WIDE == 380


def test_the_test_widths_sit_on_the_sides_of_the_breakpoint_they_claim() -> None:
    # A guard on this file's own fixtures: AC-2's "stays on one side" and
    # AC-1's "exactly" mean nothing if the widths drift across the line.
    assert NARROW < JUST_BELOW < BREAKPOINT_WIDTH
    assert BELOW < BREAKPOINT_WIDTH
    assert EXACT == BREAKPOINT_WIDTH
    assert BREAKPOINT_WIDTH < ABOVE < WIDE
    assert JUST_BELOW == BREAKPOINT_WIDTH - 1
    assert len(LONG_FOLDER) > 40


# =============================================================================
# AC-1: the layout on each side of the breakpoint, and exactly on it
# =============================================================================


def test_at_1100_px_the_page_strip_is_a_28_px_rail(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    assert window.width() == NARROW
    assert window.page_strip.width() == STRIP_RAIL_WIDTH


def test_at_1100_px_the_translation_column_is_300_px_wide(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    assert window.translation_column.width() == COLUMN_DEFAULT_NARROW


def test_at_1100_px_the_canvas_takes_every_pixel_the_rail_and_column_leave(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)

    assert window.splitter.width() == NARROW
    assert window.page_canvas.width() == _remaining(window)


def test_at_1900_px_the_page_strip_is_96_px_and_the_column_380_px(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, WIDE)

    assert window.width() == WIDE
    assert window.page_strip.width() == STRIP_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_WIDE
    assert window.page_canvas.width() == _remaining(window)


def test_at_exactly_1440_px_the_layout_is_the_wide_one(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, EXACT)

    assert window.width() == EXACT
    assert window.page_strip.width() == STRIP_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_WIDE


def test_at_1439_px_one_pixel_under_the_breakpoint_the_layout_is_the_narrow_one(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, JUST_BELOW)

    assert window.width() == JUST_BELOW
    assert window.page_strip.width() == STRIP_RAIL_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_NARROW


def test_at_1100_px_each_rail_item_shows_its_one_based_page_index(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, NARROW)

    assert _item_texts(window) == _indices()


def test_at_1900_px_each_strip_item_shows_its_filename(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, WIDE)

    assert _item_texts(window) == _filenames()


def test_at_exactly_1440_px_each_strip_item_shows_its_filename(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, EXACT)

    assert _item_texts(window) == _filenames()


@pytest.mark.parametrize("width", [NARROW, EXACT, WIDE])
def test_every_strip_item_reads_page_n_of_m_and_its_filename_at_any_width(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
    width: int,
) -> None:
    window = _open_loaded(qtbot, chapter_project, width)

    assert _item_accessible_texts(window) == _expected_accessible_texts()


def test_crossing_the_breakpoint_relabels_the_items_both_ways(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, NARROW)
    assert _item_texts(window) == _indices()

    _resize(window, WIDE)
    assert _item_texts(window) == _filenames()
    assert _item_accessible_texts(window) == _expected_accessible_texts()

    _resize(window, NARROW)
    assert _item_texts(window) == _indices()
    assert _item_accessible_texts(window) == _expected_accessible_texts()


def test_crossing_the_breakpoint_keeps_the_current_page(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    # Contract Block 2: relabel, do not rebuild - current row survives set_rail.
    window = _open_loaded(qtbot, chapter_project, NARROW)
    window.page_strip.setCurrentRow(2)
    _settle()

    _resize(window, WIDE)
    assert window.page_strip.currentRow() == 2
    assert window.page_strip.count() == len(PAGES)

    _resize(window, NARROW)
    assert window.page_strip.currentRow() == 2
    assert window.page_strip.count() == len(PAGES)


# =============================================================================
# AC-2: a resize that stays on one side gives the whole delta to the canvas
# =============================================================================


def test_widening_from_1100_to_1400_gives_all_300_px_to_the_canvas(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)
    # Start from AC-1's narrow layout, so "unchanged" is not vacuous.
    assert window.page_strip.width() == STRIP_RAIL_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_NARROW
    canvas_before = window.page_canvas.width()

    _resize(window, BELOW)

    assert window.page_canvas.width() - canvas_before == BELOW - NARROW
    assert window.page_strip.width() == STRIP_RAIL_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_NARROW


def test_widening_from_1500_to_1900_gives_all_400_px_to_the_canvas(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, ABOVE)
    assert window.page_strip.width() == STRIP_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_WIDE
    canvas_before = window.page_canvas.width()

    _resize(window, WIDE)

    assert window.page_canvas.width() - canvas_before == WIDE - ABOVE
    assert window.page_strip.width() == STRIP_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_WIDE


# =============================================================================
# AC-3: crossing with no drag reallocates to the other side's defaults
# =============================================================================


def test_crossing_up_and_back_with_no_drag_switches_both_side_widths(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)
    assert window.page_strip.width() == STRIP_RAIL_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_NARROW
    canvas_before = window.page_canvas.width()

    _resize(window, WIDE)

    assert window.page_strip.width() == STRIP_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_WIDE
    # 800 - (96 - 28) - (380 - 300) = 652
    expected = (
        (WIDE - NARROW)
        - (STRIP_WIDTH - STRIP_RAIL_WIDTH)
        - (COLUMN_DEFAULT_WIDE - COLUMN_DEFAULT_NARROW)
    )
    assert expected == 652
    assert window.page_canvas.width() - canvas_before == expected

    _resize(window, NARROW)

    assert window.page_strip.width() == STRIP_RAIL_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_NARROW
    assert window.page_canvas.width() == canvas_before


def test_crossing_by_one_pixel_each_way_switches_both_side_widths(qtbot) -> None:  # type: ignore[no-untyped-def]
    # layout.md "Behaviour the tests must assert" 4: 1439 -> 1440 -> 1439.
    window = _open(qtbot, JUST_BELOW)
    assert window.page_strip.width() == STRIP_RAIL_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_NARROW

    _resize(window, EXACT)
    assert window.page_strip.width() == STRIP_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_WIDE

    _resize(window, JUST_BELOW)
    assert window.page_strip.width() == STRIP_RAIL_WIDTH
    assert window.translation_column.width() == COLUMN_DEFAULT_NARROW


# =============================================================================
# AC-4: a dragged column keeps its width across the breakpoint
# (DV-2 claims this is the ONLY test here a broken drag guard fails: keep it
# one test.)
# =============================================================================


def test_a_column_dragged_to_400_keeps_400_across_the_breakpoint_both_ways(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot, NARROW)
    dragged = 400
    _drag_column_to(window, window.splitter.width() - window.splitter.handleWidth() - dragged)
    assert window.translation_column.width() == dragged
    assert window.page_strip.width() == STRIP_RAIL_WIDTH
    canvas_before = window.page_canvas.width()

    _resize(window, WIDE)

    assert window.translation_column.width() == dragged
    assert window.page_strip.width() == STRIP_WIDTH
    # 800 - (96 - 28) = 732
    expected = (WIDE - NARROW) - (STRIP_WIDTH - STRIP_RAIL_WIDTH)
    assert expected == 732
    assert window.page_canvas.width() - canvas_before == expected

    _resize(window, NARROW)

    assert window.translation_column.width() == dragged
    assert window.page_strip.width() == STRIP_RAIL_WIDTH


def test_opening_another_chapter_forgets_the_drag(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    # Contract Block 4: the dragged state resets on load_chapter (and only there).
    window = _open(qtbot, NARROW)
    dragged = 400
    _drag_column_to(window, window.splitter.width() - window.splitter.handleWidth() - dragged)
    assert window.translation_column.width() == dragged

    window.load_chapter(chapter_project)
    _settle()
    _resize(window, WIDE)

    assert window.translation_column.width() == COLUMN_DEFAULT_WIDE
    assert window.page_strip.width() == STRIP_WIDTH


# =============================================================================
# AC-5: the chapter name in the header, hidden (not removed) below 1440
# =============================================================================


def test_at_1900_px_the_header_shows_the_chapter_folder_display_name(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, WIDE)
    label = _chapter_label(window)

    expected = display_name(chapter_project.chapter.source_dir)
    assert expected != LONG_FOLDER, "the fixture folder must be long enough to be cut"
    assert label.isVisible()
    assert label.text() == expected


def test_at_1100_px_the_chapter_name_is_hidden_but_kept_in_the_header_with_its_text(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, NARROW)
    label = _chapter_label(window)

    assert label.isHidden()
    assert label.parent() is window.header
    assert window.header.layout().indexOf(label) >= 0
    assert label.text() == display_name(chapter_project.chapter.source_dir)


def test_the_chapter_name_hides_crossing_down_and_reappears_crossing_up(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, WIDE)
    label = _chapter_label(window)
    expected = display_name(chapter_project.chapter.source_dir)
    assert label.isVisible()

    _resize(window, NARROW)
    assert label.isHidden()
    assert label.text() == expected

    _resize(window, WIDE)
    assert label.isVisible()
    assert label.text() == expected


def test_the_chapter_name_leads_the_header_and_the_cost_readout_stays_last(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, WIDE)
    label = _chapter_label(window)
    row = window.header.layout()

    assert row.indexOf(label) == 0
    assert row.itemAt(row.count() - 1).widget() is window.cost_readout


def test_the_chapter_name_is_announced_as_chapter_and_its_name(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    # Contract Block 5 / Design notes: accessible name "Chapter {name}".
    window = _open_loaded(qtbot, chapter_project, WIDE)
    label = _chapter_label(window)
    name = display_name(chapter_project.chapter.source_dir)

    assert label.accessibleName() == f"Chapter {name}"


# =============================================================================
# AC-6: the rail still selects pages; the window minimum is unchanged
# =============================================================================


@pytest.mark.parametrize("width", [NARROW, WIDE])
def test_making_a_strip_item_current_shows_that_page_at_any_width(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
    width: int,
) -> None:
    window = _open_loaded(qtbot, chapter_project, width)
    canvas = window.page_canvas

    for ordinal in (2, 0, 1):
        window.page_strip.setCurrentRow(ordinal)
        _settle()

        assert canvas.state() == LOADED
        assert canvas.page_item is not None
        assert canvas.page_item.pixmap().size() == PAGES[ordinal][1], ordinal


def test_the_down_arrow_on_the_rail_moves_to_the_next_page(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_project: Project,
) -> None:
    window = _open_loaded(qtbot, chapter_project, NARROW)
    strip = window.page_strip
    assert strip.width() == STRIP_RAIL_WIDTH
    strip.setCurrentRow(0)
    strip.setFocus()
    _settle()

    qtbot.keyClick(strip, Qt.Key.Key_Down)
    _settle()

    assert strip.currentRow() == 1
    assert window.page_canvas.page_item is not None
    assert window.page_canvas.page_item.pixmap().size() == PAGES[1][1]


def test_the_window_minimum_stays_1100_by_720(qtbot) -> None:  # type: ignore[no-untyped-def]
    assert Workspace.MIN_SIZE == (1100, 720)
    window = _open(qtbot, 800, 600)

    assert window.size() == QSize(1100, 720)
