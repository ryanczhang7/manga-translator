"""MT-120: the workspace removes a region from translation and restores it.

Every criterion is **mechanical** (story C-7): a stored value, a widget state, a
visible button set, a signal, an accessible string, a count. The strings and
glyphs are read out of `components.md` §4.3, §4.7, §5 and `accessibility.md`
A-07, A-08, A-12, never designed here:

    Remove / Restore                 the two row actions (§5 "Row actions")
    \\N{CIRCLED DIVISION SLASH} (U+2298)  the `excluded` gutter glyph (§5 anatomy)
    "removed from translation"       the status phrase (§5 accessible name)
    "Bubble {n} removed from translation." / "Bubble {n} restored."   (A-12)
    "Page {n} \\N{EM DASH} {k} lines, {r} reviewed"   the column header (§5)
    Ctrl+E                           the toggle (§4.7, A-07)

**The world.** A two-page chapter on disk. Page 1 (ordinal 0) has four regions,
read by OCR as 一 二 三 四, and the run has finished it (`done`). Bubble 1 is
`accepted` (committed through the store), bubble 2 is a plain proposal
("Fine.") - AC-1's "proposed line at ordinal 2" - bubble 3 has no proposal and
so is `failed` on a finished page (AC-2's restored-to-failed case), bubble 4 is
a proposal. Page 2 (ordinal 1) has two regions and no `line` rows at all (OCR
has not run): C-2's "an excluded region with no line" case.

**What is observed.** The store through `Project.read_regions` - AC-1's own
words - and, where the claim is "on disk", through a plain `sqlite3`
connection that imports nothing from `mangatl.store`. Controls are activated
with `QAbstractButton.click()` (what Space or a pointer press ends in), so no
pointer hover is synthesised over the row; keys are real `QTest.keyClick`
events, so a `QShortcut` is reached the way a user reaches it.

**AC-3's editing case is a real key event into the focused editor**, not a slot
call. Measured in RED outside the framework (story `## Handoff`): a
`WidgetWithChildrenShortcut` `QShortcut(Ctrl+E)` on a widget holding a
focused `LineEditor` DOES fire on `QTest.keyClick(editor, Key_E, Ctrl)` -
`LineEditor`'s `ShortcutOverride` claims only its own chords - so a slot that
does not check the editing state toggles the store, and that test fails.

**RED.** `MarkerState.EXCLUDED`, `TranslationRow.exclude_button` /
`restore_button`, `TranslationColumn.header` and the `excluded` status do not
exist: the file imports (every name it imports exists today) and each test
fails on its own missing attribute, `KeyError` or assertion.

**Timing.** Nothing waits on a timer; every test is synchronous over a 600 x
800 page encoded once per session. No `pytest-timeout` in this project and no
hook in this file carries a budget, because none of them waits.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QStyleOptionGraphicsItem, QWidget

from mangatl.domain.line import Line, OcrResult
from mangatl.domain.page import Chapter, Page
from mangatl.domain.page_status import PageProgress
from mangatl.domain.region import RawRegion
from mangatl.store.lines import commit_line
from mangatl.store.project import PAGE_DONE, Project, create_project, open_project
from mangatl.ui import link as link_module
from mangatl.ui import tokens_gen
from mangatl.ui.markers import MarkerState
from mangatl.ui.workspace import STATUS_COLOR_TOKENS, STATUS_GLYPHS, TranslationRow, Workspace

# --- Settled: components.md §5 / §4.3, accessibility.md A-12 ---------------------
EXCLUDED_GLYPH = "\N{CIRCLED DIVISION SLASH}"  # U+2298
EXCLUDED_GLYPH_TOKEN = "color.text.muted"  # Lead Designer, decision 1
EXCLUDED_PHRASE = "removed from translation"
REMOVE = "Remove"
RESTORE = "Restore"
DIM = tokens_gen.OVERLAY_DIM_OPACITY
REASON_UNTRANSLATED = "no translation was returned"


def removed_announcement(ordinal: int) -> str:
    return f"Bubble {ordinal} removed from translation."


def restored_announcement(ordinal: int) -> str:
    return f"Bubble {ordinal} restored."


def header_text(page_number: int, lines: int, reviewed: int) -> str:
    """§5 "Column header: 'Page 7 \N{EM DASH} 18 lines, 12 reviewed'"."""
    return f"Page {page_number} \N{EM DASH} {lines} lines, {reviewed} reviewed"


# --- The world ---------------------------------------------------------------------
PAGE = QSize(600, 800)
WINDOW = QSize(1100, 720)
PAGES = ("001.png", "002.png")
PAGE0_OCR = ("一", "二", "三", "四")
PAGE0_PROPOSED = {0: "Hello.", 1: "Fine.", 3: "Wait!"}  # bubble 3 has none
PAGE1_REGIONS = 2  # no line rows: OCR has not run

#: Bubble 2 - the proposed line AC-1 removes - as a 0-based reading index.
SECOND = 1
#: Bubble 3 - no proposal on a finished page, so `failed`.
THIRD = 2

NO = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


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
    x, y = 60, 60 + 140 * i
    return ((x, y), (x + 200, y), (x + 200, y + 100), (x, y + 100), (x, y))


def _regions(count: int, mask: bytes) -> list[RawRegion]:
    return [
        RawRegion(polygon=_ring(i), mask=mask, confidence=0.9, kind="bubble") for i in range(count)
    ]


@pytest.fixture
def chapter_dir(tmp_path: Path, page_png: bytes, mask_png: bytes) -> Path:
    """The two-page project of the module docstring, on disk and CLOSED."""
    source = tmp_path / "chapter"
    source.mkdir()
    for name in PAGES:
        (source / name).write_bytes(page_png)
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
    project_dir = tmp_path / "chapter.mtproj"
    with create_project(chapter, project_dir) as project:
        project.write_regions(0, _regions(len(PAGE0_OCR), mask_png))
        project.write_lines(0, [OcrResult(ja) for ja in PAGE0_OCR])
        project.write_proposed(0, PAGE0_PROPOSED)
        with project.transaction() as cursor:
            cursor.execute("UPDATE page SET status = ? WHERE ordinal = 0", (PAGE_DONE,))
        commit_line(project, 0, 0, None, "accepted")
        project.write_regions(1, _regions(PAGE1_REGIONS, mask_png))
    return project_dir


@pytest.fixture
def project(chapter_dir: Path) -> Iterator[Project]:
    with open_project(chapter_dir) as opened:
        yield opened


@pytest.fixture
def recorded_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """`mangatl.ui.link.QAccessible` (imported by name, MT-016) replaced by a
    recorder of `(event type, object)`; the real `Event` enum is kept."""
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


def _showing(qtbot, project: Project, ordinal: int = 0) -> Workspace:  # type: ignore[no-untyped-def]
    window = _open(qtbot)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(ordinal)
    _settle()
    return window


def _row(window: Workspace, index: int) -> TranslationRow:
    return window.translation_column.row(index)


def _visible_actions(row: TranslationRow) -> set[str]:
    """The label of every push button the row shows - every one, so an extra
    control is a failure too, not only a missing one."""
    return {button.text() for button in row.findChildren(QPushButton) if button.isVisibleTo(row)}


def _states(window: Workspace) -> list[MarkerState]:
    return [marker.state() for marker in window.page_canvas.markers]


def _excluded_on_disk(chapter_dir: Path, ordinal: int) -> list[object]:
    """`region.excluded` for one page in reading order, by a plain connection."""
    connection = sqlite3.connect(chapter_dir / "project.db")
    try:
        return [
            row[0]
            for row in connection.execute(
                "SELECT region.excluded FROM region JOIN page ON page.id = region.page_id"
                " WHERE page.ordinal = ? ORDER BY region.reading_index",
                (ordinal,),
            )
        ]
    finally:
        connection.close()


def _accessible_name(window: Workspace, index: int) -> str:
    item = window.translation_column.list.item(index)
    return str(item.data(Qt.ItemDataRole.AccessibleTextRole))


def _focus(qtbot, widget: QWidget) -> None:  # type: ignore[no-untyped-def]
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(widget.hasFocus)
    _settle()


def _key(widget: QWidget, key: Qt.Key, modifiers: Qt.KeyboardModifier = NO) -> None:
    QTest.keyClick(widget, key, modifiers)
    _settle()


def _remove(window: Workspace, index: int) -> None:
    _row(window, index).exclude_button.click()
    _settle()


def _restore(window: Workspace, index: int) -> None:
    _row(window, index).restore_button.click()
    _settle()


# =============================================================================
# The vocabulary, read out of components.md §5
# =============================================================================


def test_the_removed_status_has_the_circled_division_slash_glyph() -> None:
    assert STATUS_GLYPHS["excluded"] == EXCLUDED_GLYPH


def test_the_removed_glyph_is_distinct_from_every_other_status_glyph() -> None:
    """A-15.7: one colour, so the silhouette alone must tell `excluded` apart."""
    others = [glyph for status, glyph in STATUS_GLYPHS.items() if status != "excluded"]
    assert STATUS_GLYPHS["excluded"] not in others
    assert len(set(STATUS_GLYPHS.values())) == len(STATUS_GLYPHS)


def test_the_removed_glyph_is_coloured_text_muted() -> None:
    assert STATUS_COLOR_TOKENS["excluded"] == EXCLUDED_GLYPH_TOKEN


# =============================================================================
# AC-1 - Remove
# =============================================================================


def test_removing_a_proposed_line_stores_the_users_exclusion_and_shows_the_row_removed(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    chapter_dir: Path,
) -> None:
    window = _showing(qtbot, project)
    row = _row(window, SECOND)
    assert row.editor.status == "proposed", "fixture: bubble 2 is not a plain proposal"

    _remove(window, SECOND)

    assert project.read_regions(0)[SECOND].excluded == "user", (
        "Remove did not store the user's exclusion"
    )
    assert _excluded_on_disk(chapter_dir, 0) == [None, "user", None, None]
    assert row.editor.status == "excluded"
    assert row.editor.isReadOnly(), "a removed line's editor still accepts typing"
    assert row.gutter.text() == EXCLUDED_GLYPH
    assert row.gutter.property("status") == "excluded"
    assert _visible_actions(row) == {RESTORE}
    assert window.page_canvas.markers[SECOND].state() == MarkerState.EXCLUDED
    assert row.badge.text() == "2"
    assert window.page_canvas.markers[SECOND].region.ordinal == 2


def test_removing_a_line_moves_and_renumbers_nothing_else(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """AC-1's last sentence, and C-4's "in place (no rebuild, no selection change)":
    the same row and marker objects, the same badges, the same selection."""
    window = _showing(qtbot, project)
    rows = [_row(window, i) for i in range(len(PAGE0_OCR))]
    markers = list(window.page_canvas.markers)
    assert window.link.state.selected_region_id == 0, "fixture: bubble 1 is selected"

    _remove(window, SECOND)

    assert [_row(window, i) for i in range(len(PAGE0_OCR))] == rows, "the rows were rebuilt"
    assert list(window.page_canvas.markers) == markers, "the markers were rebuilt"
    assert [row.badge.text() for row in rows] == ["1", "2", "3", "4"]
    assert [m.region.ordinal for m in markers] == [1, 2, 3, 4]
    assert [row.editor.status for row in rows] == ["accepted", "excluded", "failed", "proposed"]
    assert _states(window) == [
        MarkerState.SELECTED,
        MarkerState.EXCLUDED,
        MarkerState.IDLE,
        MarkerState.IDLE,
    ]
    assert window.link.state.selected_region_id == 0
    assert window.translation_column.list.currentRow() == 0


def test_every_row_that_is_not_removed_offers_remove_beside_its_status_action(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """§5 "Row actions": Remove on every row whose status is not `excluded`."""
    window = _showing(qtbot, project)

    assert [_visible_actions(_row(window, i)) for i in range(len(PAGE0_OCR))] == [
        {REMOVE},  # accepted
        {"Accept", REMOVE},  # proposed
        {"Retry line", REMOVE},  # failed
        {"Accept", REMOVE},  # proposed
    ]


# =============================================================================
# AC-2 - Restore
# =============================================================================


def test_restoring_a_removed_proposal_clears_the_store_and_shows_it_proposed_again(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _showing(qtbot, project)
    _remove(window, SECOND)
    row = _row(window, SECOND)

    _restore(window, SECOND)

    assert project.read_regions(0)[SECOND].excluded is None
    assert row.editor.status == "proposed"
    assert not row.editor.isReadOnly()
    assert row.gutter.text() == STATUS_GLYPHS["proposed"]
    assert _visible_actions(row) == {"Accept", REMOVE}
    assert window.page_canvas.markers[SECOND].state() == MarkerState.IDLE


def test_restoring_a_finished_pages_untranslated_region_shows_it_failed_with_retry(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """AC-2 / `## Context`: a restored region has a line and no proposal, and on
    a page the run finished `derive_status` reads it `failed`."""
    window = _showing(qtbot, project)
    _remove(window, THIRD)
    row = _row(window, THIRD)
    assert row.editor.status == "excluded", "precondition: Remove did not remove bubble 3"
    assert not row.error_caption.isVisibleTo(row), "a removed line shows a failure caption"

    _restore(window, THIRD)

    assert project.read_regions(0)[THIRD].excluded is None
    assert row.editor.status == "failed"
    assert _visible_actions(row) == {"Retry line", REMOVE}
    assert row.error_caption.text() == REASON_UNTRANSLATED


def test_restoring_an_accepted_line_reads_its_stored_act_again(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """C-1: excluded wins over a stored act for display; restore gives it back."""
    window = _showing(qtbot, project)
    row = _row(window, 0)

    _remove(window, 0)
    removed = row.editor.status
    _restore(window, 0)

    assert removed == "excluded"
    assert row.editor.status == "accepted"
    assert _visible_actions(row) == {REMOVE}


# =============================================================================
# AC-3 - Ctrl+E
# =============================================================================


def test_ctrl_e_on_the_focused_row_removes_its_line_and_again_restores_it(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _showing(qtbot, project)
    window.link.select(SECOND)
    _settle()
    lst = window.translation_column.list
    _focus(qtbot, lst)
    assert lst.currentRow() == SECOND, "fixture: bubble 2's row is not the current row"

    _key(lst, Qt.Key.Key_E, CTRL)
    removed = (project.read_regions(0)[SECOND].excluded, _row(window, SECOND).editor.status)
    _key(lst, Qt.Key.Key_E, CTRL)
    restored = (project.read_regions(0)[SECOND].excluded, _row(window, SECOND).editor.status)

    assert removed == ("user", "excluded")
    assert restored == (None, "proposed")


def test_ctrl_e_on_the_canvas_removes_the_selected_region_and_again_restores_it(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _showing(qtbot, project)
    window.link.select(THIRD)
    canvas = window.page_canvas
    _focus(qtbot, canvas)

    _key(canvas, Qt.Key.Key_E, CTRL)
    removed = (project.read_regions(0)[THIRD].excluded, _row(window, THIRD).editor.status)
    _key(canvas, Qt.Key.Key_E, CTRL)
    restored = (project.read_regions(0)[THIRD].excluded, _row(window, THIRD).editor.status)

    assert removed == ("user", "excluded")
    assert restored == (None, "failed")
    # The region stays selected throughout, so its marker is SELECTED, not EXCLUDED.
    assert window.link.state.selected_region_id == THIRD
    assert canvas.markers[THIRD].state() == MarkerState.SELECTED


def test_ctrl_e_while_a_line_is_being_edited_leaves_the_exclusion_alone_until_editing_ends(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """AC-3 "inert while editing", with a real key event INTO the focused
    editor: the column's shortcut reaches it (measured, module docstring), so
    a slot that does not check the editing state fails the first half. The
    second half - the same key once focus has left the editor - is what keeps
    the first from passing on a workspace with no shortcut at all."""
    window = _showing(qtbot, project)
    window.link.select(SECOND)
    _settle()
    editor = _row(window, SECOND).editor
    _focus(qtbot, editor)

    _key(editor, Qt.Key.Key_E, CTRL)
    while_editing = (
        project.read_regions(0)[SECOND].excluded,
        editor.status,
        editor.text(),
        editor.hasFocus(),
    )
    _focus(qtbot, window.translation_column.list)
    _key(window.translation_column.list, Qt.Key.Key_E, CTRL)
    after_editing = project.read_regions(0)[SECOND].excluded

    assert while_editing == (None, "proposed", "Fine.", True), (
        "Ctrl+E while editing changed the exclusion, the status, the text or the focus"
    )
    assert after_editing == "user", "Ctrl+E on the row, not editing, did not remove it"


# =============================================================================
# AC-4 - announcements, accessible names, the controls
# =============================================================================


def test_removing_and_restoring_are_announced_through_the_live_region(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    recorded_alerts: list[tuple[Any, Any]],
) -> None:
    window = _showing(qtbot, project)
    live = window.live_region
    recorded_alerts.clear()

    _remove(window, SECOND)
    removed = (live.accessibleName(), live.text(), list(recorded_alerts))
    recorded_alerts.clear()
    _restore(window, SECOND)
    restored = (live.accessibleName(), live.text(), list(recorded_alerts))

    alert = [(QAccessible.Event.Alert, live)]
    assert removed == (removed_announcement(2), removed_announcement(2), alert)
    assert restored == (restored_announcement(2), restored_announcement(2), alert)


def test_a_removed_rows_accessible_name_ends_with_removed_from_translation(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _showing(qtbot, project)

    _remove(window, SECOND)
    removed = _accessible_name(window, SECOND)
    _restore(window, SECOND)
    restored = _accessible_name(window, SECOND)

    assert removed.startswith("Bubble 2 of 4. "), removed
    assert removed.endswith(f". {EXCLUDED_PHRASE}."), removed
    assert restored == "Bubble 2 of 4. Japanese: 二. English: Fine.. machine proposal.", restored


def _standalone(qtbot, line: Line) -> TranslationRow:  # type: ignore[no-untyped-def]
    row = TranslationRow(0, line, None)
    qtbot.addWidget(row)
    row.resize(480, 60)
    with qtbot.waitExposed(row):
        row.show()
    row.activateWindow()
    qtbot.waitUntil(row.isActiveWindow)
    _settle()
    return row


def _tab_stops(row: TranslationRow, presses: int = 6) -> list[QWidget | None]:
    """Where focus is, then where each of `presses` Tabs takes it."""
    stops: list[QWidget | None] = [QApplication.focusWidget()]
    for _ in range(presses):
        target = QApplication.focusWidget() or row
        QTest.keyClick(target, Qt.Key.Key_Tab)
        _settle()
        stops.append(QApplication.focusWidget())
    return stops


def _proposed_line() -> Line:
    return Line(0, "二", "Fine.", None, "proposed", None)


def _excluded_line() -> Line:
    """The shape `read_review_lines` gives a removed proposal (C-1, C-2)."""
    return Line(0, "二", "Fine.", None, "excluded", None, excluded="user")


def test_remove_and_restore_carry_their_label_as_accessible_name(qtbot) -> None:  # type: ignore[no-untyped-def]
    row = _standalone(qtbot, _proposed_line())

    assert (row.exclude_button.text(), row.exclude_button.accessibleName()) == (REMOVE, REMOVE)
    assert (row.restore_button.text(), row.restore_button.accessibleName()) == (RESTORE, RESTORE)


def test_tab_reaches_remove_last_after_accept_on_a_proposed_row(qtbot) -> None:  # type: ignore[no-untyped-def]
    """§5: Remove is last in the row's tab order, after whichever action shows."""
    row = _standalone(qtbot, _proposed_line())

    stops = _tab_stops(row)

    assert row.exclude_button in stops, f"Tab never reached Remove: {stops}"
    assert row.accept_button in stops
    first_accept = stops.index(row.accept_button)
    first_remove = stops.index(row.exclude_button)
    assert first_accept < first_remove, "Remove is not after Accept in the tab order"


def test_tab_reaches_restore_on_a_removed_row(qtbot) -> None:  # type: ignore[no-untyped-def]
    row = _standalone(qtbot, _excluded_line())
    assert row.editor.status == "excluded", "precondition: the row is not removed"

    stops = _tab_stops(row)

    assert row.restore_button in stops, f"Tab never reached Restore: {stops}"
    assert row.exclude_button not in stops


# =============================================================================
# AC-5 - the counts
# =============================================================================


def test_a_removed_line_drops_out_of_the_header_and_the_strip_and_comes_back_on_restore(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """AC-5 with its control: four lines, one removed -> 3; cleared -> 4.
    Bubble 1 is accepted (1 reviewed), bubble 3 failed."""
    window = _showing(qtbot, project)
    header = window.translation_column.header
    before = (header.text(), window.page_strip.progress(0))

    _remove(window, SECOND)
    removed = (header.text(), window.page_strip.progress(0))
    _restore(window, SECOND)
    restored = (header.text(), window.page_strip.progress(0))

    assert before == (header_text(1, 4, 1), PageProgress("failed", 1, 4, 1))
    assert removed == (header_text(1, 3, 1), PageProgress("failed", 1, 3, 1))
    assert restored == before


def test_a_removed_failed_line_counts_as_neither_a_line_nor_a_failure(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _showing(qtbot, project)

    _remove(window, THIRD)

    assert window.page_strip.progress(0) == PageProgress("partly_reviewed", 1, 3, 0)
    assert window.translation_column.header.text() == header_text(1, 3, 1)
    strip_name = window.page_strip.item(0).data(Qt.ItemDataRole.AccessibleTextRole)
    assert str(strip_name).endswith(", 1 of 3 lines reviewed"), strip_name


def test_a_page_whose_every_region_is_removed_reads_zero_lines_and_fully_reviewed(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """AC-5's edge, read at load (`_stored_progress`), not after a toggle."""
    for index in range(len(PAGE0_OCR)):
        project.set_excluded(0, index, "user")

    window = _showing(qtbot, project)

    assert window.translation_column.header.text() == header_text(1, 0, 0)
    assert window.page_strip.progress(0) == PageProgress("fully_reviewed", 0, 0, 0)


def test_removing_the_last_included_line_in_the_workspace_makes_the_page_fully_reviewed(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """The same edge reached by toggles (`_refresh_page_progress`)."""
    for index in (0, 1, 2):
        project.set_excluded(0, index, "user")
    window = _showing(qtbot, project)
    assert window.page_strip.progress(0) == PageProgress("translated", 0, 1, 0), (
        "at load, three removed regions are still counted"
    )

    _remove(window, 3)

    assert window.page_strip.progress(0) == PageProgress("fully_reviewed", 0, 0, 0)
    assert window.translation_column.header.text() == header_text(1, 0, 0)


def test_the_header_counts_a_line_accepted_in_the_column(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """The header is new in this story and §7 says it counts reviewed lines: it
    follows an accept, not only a toggle."""
    window = _showing(qtbot, project)

    _row(window, 3).accept_button.click()
    _settle()

    assert window.translation_column.header.text() == header_text(1, 4, 2)


def test_a_removed_region_with_no_line_row_shows_removed_and_is_not_counted(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """C-2: a region with no `line` row reads back `None`; on an excluded region
    the workspace shows it excluded, from `read_regions`."""
    project.set_excluded(1, 1, "user")

    window = _showing(qtbot, project, 1)
    row = _row(window, 1)

    assert row.editor.status == "excluded"
    assert _visible_actions(row) == {RESTORE}
    assert window.page_canvas.markers[1].state() == MarkerState.EXCLUDED
    assert window.page_strip.progress(1) == PageProgress("pending", 0, 1, 0)


# =============================================================================
# AC-6 - the store is the memory
# =============================================================================


def test_a_removed_region_comes_back_removed_after_closing_and_reopening(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_dir: Path,
) -> None:
    with open_project(chapter_dir) as project:
        window = _showing(qtbot, project)
        _remove(window, SECOND)
        window.close()
        _settle()

    assert _excluded_on_disk(chapter_dir, 0) == [None, "user", None, None]

    with open_project(chapter_dir) as reopened:
        fresh = _showing(qtbot, reopened)
        row = _row(fresh, SECOND)
        got = (
            row.editor.status,
            row.gutter.text(),
            _visible_actions(row),
            fresh.page_canvas.markers[SECOND].state(),
            fresh.translation_column.header.text(),
            fresh.page_strip.progress(0).total,
        )
        fresh.close()

    assert got == (
        "excluded",
        EXCLUDED_GLYPH,
        {RESTORE},
        MarkerState.EXCLUDED,
        header_text(1, 3, 1),
        3,
    )


def test_an_exclusion_written_by_the_store_alone_is_shown_removed(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    """The flag is the store's, from either writer (`## Out of scope`): a
    `watermark` exclusion no workspace made reads exactly as a user's."""
    project.set_excluded(0, 3, "watermark")

    window = _showing(qtbot, project)
    row = _row(window, 3)

    assert row.editor.status == "excluded"
    assert _visible_actions(row) == {RESTORE}
    assert window.page_canvas.markers[3].state() == MarkerState.EXCLUDED
    assert window.page_canvas.markers[3].region.excluded is True


# =============================================================================
# AC-7 - selecting a removed region
# =============================================================================


class _StrokeRecorder(QPainter):
    """A real painter that records the pen of every outline stroke."""

    def __init__(self, device: QImage) -> None:
        super().__init__(device)
        self.pens: list[QPen] = []

    def strokePath(self, path: QPainterPath, pen: QPen) -> None:  # type: ignore[override]
        self.pens.append(QPen(pen))
        super().strokePath(path, pen)


def _stroke_pens(marker: Any) -> list[QPen]:
    image = QImage(200, 200, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    painter = _StrokeRecorder(image)
    try:
        marker.paint(painter, QStyleOptionGraphicsItem(), None)
    finally:
        painter.end()
    return painter.pens


def _removed_page(qtbot, project: Project) -> Workspace:  # type: ignore[no-untyped-def]
    project.set_excluded(0, SECOND, "user")
    window = _showing(qtbot, project)
    assert window.page_canvas.markers[SECOND].state() == MarkerState.EXCLUDED, "precondition"
    return window


def test_clicking_a_removed_regions_marker_selects_it_at_full_opacity_with_a_dashed_core(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _removed_page(qtbot, project)
    canvas = window.page_canvas
    marker = canvas.markers[SECOND]
    point = canvas.mapFromScene(marker.region.bounds().center())
    assert canvas.viewport().rect().contains(point), "fixture: bubble 2 is off screen"

    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, NO, point)
    _settle()

    assert window.link.state.selected_region_id == SECOND
    assert window.translation_column.list.currentRow() == SECOND
    assert marker.state() == MarkerState.SELECTED
    assert marker.opacity() == 1.0, "a selected removed marker is dimmed"
    assert [m.opacity() for i, m in enumerate(canvas.markers) if i != SECOND] == [DIM] * 3
    halo, core = _stroke_pens(marker)[:2]
    assert core.color().rgba() == QColor(tokens_gen.OVERLAY_BUBBLE_SELECTED).rgba()
    assert core.style() == Qt.PenStyle.DashLine, "the selected removed marker lost its dash"
    assert halo.style() == Qt.PenStyle.SolidLine


def test_down_on_the_canvas_selects_a_removed_region_like_any_other(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _removed_page(qtbot, project)
    canvas = window.page_canvas
    _focus(qtbot, canvas)

    _key(canvas, Qt.Key.Key_Down)

    assert window.link.state.selected_region_id == SECOND
    assert window.translation_column.list.currentRow() == SECOND
    assert canvas.markers[SECOND].state() == MarkerState.SELECTED


def test_down_in_the_column_selects_a_removed_row_like_any_other(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
) -> None:
    window = _removed_page(qtbot, project)
    lst = window.translation_column.list
    _focus(qtbot, lst)

    _key(lst, Qt.Key.Key_Down)

    assert window.link.state.selected_region_id == SECOND
    assert window.page_canvas.markers[SECOND].state() == MarkerState.SELECTED
    assert _row(window, SECOND).editor.status == "excluded"


def test_enter_on_the_canvas_lands_on_a_removed_row_without_beginning_to_edit(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    chapter_dir: Path,
) -> None:
    """§4.7 / §5: Enter on the canvas begins editing the selected line - except
    a removed one, where focus lands on the row and nothing becomes editable.
    The first half (bubble 1, not removed) is the control: Enter still edits."""
    window = _removed_page(qtbot, project)
    canvas = window.page_canvas
    _focus(qtbot, canvas)
    _key(canvas, Qt.Key.Key_Return)
    assert _row(window, 0).editor.hasFocus(), "control: Enter did not edit bubble 1"

    window.link.select(SECOND)
    _focus(qtbot, canvas)
    _key(canvas, Qt.Key.Key_Return)
    row = _row(window, SECOND)
    focused = QApplication.focusWidget()
    current = window.translation_column.list.currentRow()
    QTest.keyClicks(focused or window, "xyz")
    _settle()

    assert focused is not row.editor, "Enter began editing a removed line"
    assert focused is window.translation_column.list or (
        focused is not None and row.isAncestorOf(focused)
    ), f"focus landed on {focused!r}, not on bubble 2's row"
    assert current == SECOND
    assert row.editor.text() == "Fine.", "typing after Enter changed a removed line"
    assert row.editor.status == "excluded"
