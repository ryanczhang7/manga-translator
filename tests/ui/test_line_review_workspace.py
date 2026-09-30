"""MT-017 C-8: the row a line is reviewed in, and the workspace that saves it.

Two halves:

1. **`TranslationRow` / `TranslationColumn` rendering** (AC-8, AC-9, AC-7's
   caption). Every glyph, colour token, control and phrase is READ OUT of
   `components.md` §5-§7 and the story's C-8 (PO-2 fixes `reverted` as a return
   arrow alone):

       status    glyph  colour token          control      accessible phrase
       proposed  ○      color.text.muted      Accept       machine proposal
       accepted  ✔      color.status.success  -            accepted
       edited    ✎      color.accent.base     Revert       edited
       reverted  ↩      color.text.secondary  -            edited, then returned to the proposal
       failed    ⚠      color.status.danger   Retry line   translation failed: {reason}

   Colour is asserted as `QColor(tokens_gen.TOKENS[token])` equality on the
   gutter's `WindowText` palette role; controls with `isVisibleTo(row)` on an
   unhovered, unselected row and again hovered and selected - "never hover
   reveals" is a claim about both states.

2. **The workspace over a real project** (AC-1's on-disk bound, AC-6's round
   trip, C-7's "a page change or a window close never drops a pending save").
   The project file is observed with a plain `sqlite3` connection, which is
   what "present in the project file" means. AC-6 is a real round trip: every
   act goes through the editor's keys, the `Workspace` and the `Project` are
   closed, `open_project` reopens the same directory, and a fresh `Workspace`
   reads the rows back.

**Timing.** One test (AC-1's) waits real time, bounded by the literal
`500 + 250` ms; everything else is synchronous. The page PNG is small (600 x
800), encoded once per session. No `pytest-timeout` exists in this project.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from mangatl.domain.line import Line, OcrResult
from mangatl.domain.page import Chapter, Page
from mangatl.domain.region import RawRegion
from mangatl.store.project import PAGE_DONE, Project, create_project, open_project
from mangatl.ui import tokens_gen
from mangatl.ui.link import OrderedRegion
from mangatl.ui.workspace import (
    STATUS_COLOR_TOKENS,
    STATUS_GLYPHS,
    TranslationRow,
    Workspace,
)

# --- Settled: read out of components.md §5 / C-8 / PO-2 -------------------------
DESIGN_GLYPHS = {
    "proposed": "○",  # ○ hollow circle
    "accepted": "✔",  # ✔ heavy check mark
    "edited": "✎",  # ✎ pencil
    "reverted": "↩",  # ↩ return arrow, alone (PO-2)
    "failed": "⚠",  # ⚠ warning triangle
}
DESIGN_COLOR_TOKENS = {
    "proposed": "color.text.muted",
    "accepted": "color.status.success",
    "edited": "color.accent.base",
    "reverted": "color.text.secondary",
    "failed": "color.status.danger",
}
#: Which of (Revert, Accept, Retry line) each status shows - §5 "Row actions".
DESIGN_ACTIONS = {
    "proposed": (False, True, False),
    "accepted": (False, False, False),
    "edited": (True, False, False),
    "reverted": (False, False, False),
    "failed": (False, False, True),
}
DESIGN_PHRASES = {
    "proposed": "machine proposal",
    "accepted": "accepted",
    "edited": "edited",
    "reverted": "edited, then returned to the proposal",
}
REASON_OCR_EMPTY = "no text was read in this bubble"
REASON_UNTRANSLATED = "no translation was returned"

# --- Settled number: AC-1 --------------------------------------------------------
DESIGN_SAVE_BOUND_MS = 500
SLACK_MS = 250  # event-loop scheduling slack, named (story Contract, oracle table)

# --- Fixture ----------------------------------------------------------------------
STATUSES = ("proposed", "accepted", "edited", "reverted", "failed")
#: A proposal whose O2 form is not itself (NFD accent, double space, trailing space).
P = "Cafe\u0301  au lait "
PAGE = QSize(600, 800)
WINDOW = QSize(1100, 720)
PAGES = ("001.png", "002.png")

NO = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _line(
    status: str,
    *,
    index: int = 0,
    proposed_en: str | None = "Hello.",
    final_en: str | None = None,
    ocr_empty: bool = False,
) -> Line:
    return Line(
        reading_index=index,
        source_ja="" if ocr_empty else f"ja {index}",
        proposed_en=proposed_en,
        final_en=final_en,
        status=status,  # type: ignore[arg-type]
        edited_at=None,
        ocr_empty=ocr_empty,
    )


def _status_line(status: str, index: int = 0) -> Line:
    """One representative line per status."""
    return {
        "proposed": _line("proposed", index=index),
        "accepted": _line("accepted", index=index),
        "edited": _line("edited", index=index, final_en="Mine"),
        "reverted": _line("reverted", index=index, final_en="Hello."),
        "failed": _line("failed", index=index, proposed_en=None, ocr_empty=True),
    }[status]


def _actions(row: TranslationRow) -> tuple[bool, bool, bool]:
    return (
        row.revert_button.isVisibleTo(row),
        row.accept_button.isVisibleTo(row),
        row.retry_button.isVisibleTo(row),
    )


def _gutter_colour(row: TranslationRow) -> QColor:
    return row.gutter.palette().color(QPalette.ColorRole.WindowText)


def _token_colour(status: str) -> QColor:
    return QColor(tokens_gen.TOKENS[DESIGN_COLOR_TOKENS[status]])


def _pointer_to(widget: QWidget, point: QPoint) -> None:
    """Real pointer input from 1 px away (a move to where the pointer already is
    is dropped offscreen - MT-016's measurement)."""
    QTest.mouseMove(widget, point - QPoint(1, 1))
    QTest.mouseMove(widget, point)
    _settle()


def _show_row(qtbot, line: Line, save=None, region_id: int = 0) -> TranslationRow:  # type: ignore[no-untyped-def]
    row = TranslationRow(region_id, line, save)
    qtbot.addWidget(row)
    row.resize(480, 60)
    with qtbot.waitExposed(row):
        row.show()
    row.activateWindow()
    qtbot.waitUntil(row.isActiveWindow)
    _settle()
    return row


def _focus(qtbot, widget: QWidget) -> None:  # type: ignore[no-untyped-def]
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(widget.hasFocus)
    _settle()


def _key(widget: QWidget, key: Qt.Key, modifiers: Qt.KeyboardModifier = NO) -> None:
    QTest.keyClick(widget, key, modifiers)
    _settle()


def _type(widget: QWidget, text: str) -> None:
    widget.selectAll()  # type: ignore[attr-defined]
    QTest.keyClicks(widget, text)
    _settle()


# =============================================================================
# C-8's tables, read out
# =============================================================================


def test_the_status_glyphs_are_the_design_table() -> None:
    assert dict(STATUS_GLYPHS) == DESIGN_GLYPHS


def test_the_five_status_glyphs_are_pairwise_distinct() -> None:
    """accessibility.md A-15.7's "testable as": colour is never the only cue."""
    assert set(STATUS_GLYPHS) == set(STATUSES)
    assert len(set(STATUS_GLYPHS.values())) == len(STATUSES)


def test_reverted_is_a_return_arrow_alone_and_not_a_pencil_variant() -> None:
    """PO-2: one character, not the edited pencil with something added."""
    assert STATUS_GLYPHS["reverted"] == "↩"
    assert STATUS_GLYPHS["edited"] not in STATUS_GLYPHS["reverted"]


def test_the_status_colour_tokens_are_components_md_s5_glyph_colours() -> None:
    assert dict(STATUS_COLOR_TOKENS) == DESIGN_COLOR_TOKENS


# =============================================================================
# The row, per status (AC-8, AC-9)
# =============================================================================


@pytest.mark.parametrize("status", STATUSES)
def test_each_status_row_carries_its_glyph_in_its_token_colour(
    qtbot,  # type: ignore[no-untyped-def]
    status: str,
) -> None:
    row = _show_row(qtbot, _status_line(status))

    assert row.gutter.isVisibleTo(row)
    assert row.gutter.text() == DESIGN_GLYPHS[status]
    assert _gutter_colour(row) == _token_colour(status)
    assert row.editor.status == status


@pytest.mark.parametrize("status", STATUSES)
def test_each_status_row_shows_its_controls_whether_or_not_it_is_hovered(
    qtbot,  # type: ignore[no-untyped-def]
    status: str,
) -> None:
    """§5 "Row actions": always visible when applicable, never hover-only.
    (Revert, Accept, Retry line) visibility, unhovered and then hovered."""
    row = _show_row(qtbot, _status_line(status))
    unhovered = _actions(row)

    row.set_hovered(True)
    _pointer_to(row, row.rect().center())
    hovered = _actions(row)

    assert unhovered == DESIGN_ACTIONS[status]
    assert hovered == DESIGN_ACTIONS[status]


def test_the_row_controls_carry_their_accessible_names(qtbot) -> None:  # type: ignore[no-untyped-def]
    row = _show_row(qtbot, _status_line("proposed"))

    assert row.revert_button.accessibleName() == "Revert"
    assert row.accept_button.accessibleName() == "Accept"
    assert row.retry_button.accessibleName() == "Retry line"
    assert row.retry_button.text() == "Retry line"


@pytest.mark.parametrize("status", STATUSES)
def test_the_row_reads_gutter_then_badge_then_editor_then_actions(
    qtbot,  # type: ignore[no-untyped-def]
    status: str,
) -> None:
    """§5 anatomy: `[ status gutter ][ ordinal badge ][ editor ][ actions ]`."""
    row = _show_row(qtbot, _status_line(status))
    gutter_x = row.gutter.geometry().x()
    badge_x = row.badge.geometry().x()
    editor_x = row.editor.geometry().x()

    assert gutter_x < badge_x < editor_x
    for button in (row.revert_button, row.accept_button, row.retry_button):
        if button.isVisibleTo(row):
            assert button.mapTo(row, QPoint(0, 0)).x() > editor_x


def test_an_ocr_empty_row_is_failed_with_retry_and_says_no_text_was_read(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-8 (MT-010 AC-4)."""
    row = _show_row(qtbot, _line("failed", proposed_en=None, ocr_empty=True))

    assert row.editor.status == "failed"
    assert row.retry_button.isVisibleTo(row)
    assert row.error_caption.isVisibleTo(row)
    assert row.error_caption.text() == REASON_OCR_EMPTY


def test_an_untranslated_failed_row_says_no_translation_was_returned(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-8 (MT-011 AC-5)."""
    row = _show_row(qtbot, _line("failed", proposed_en=None))

    assert row.retry_button.isVisibleTo(row)
    assert row.error_caption.text() == REASON_UNTRANSLATED


def test_a_failed_row_is_distinguishable_from_an_empty_proposed_row(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-8: both show an empty field; glyph, colour, Retry and caption differ."""
    failed = _show_row(qtbot, _line("failed", proposed_en=None, ocr_empty=True), region_id=0)
    empty = _show_row(qtbot, _line("proposed", proposed_en=""), region_id=1)

    assert failed.editor.text() == empty.editor.text() == ""
    assert failed.gutter.text() != empty.gutter.text()
    assert _gutter_colour(failed) != _gutter_colour(empty)
    assert failed.retry_button.isVisibleTo(failed)
    assert not empty.retry_button.isVisibleTo(empty)
    assert not empty.error_caption.isVisibleTo(empty)


@pytest.mark.parametrize("status", ["proposed", "accepted", "edited", "reverted"])
def test_a_row_that_has_not_failed_shows_no_caption(
    qtbot,  # type: ignore[no-untyped-def]
    status: str,
) -> None:
    row = _show_row(qtbot, _status_line(status))
    assert not row.error_caption.isVisibleTo(row)


def test_retry_line_asks_for_a_retry_of_its_own_reading_index(qtbot) -> None:  # type: ignore[no-untyped-def]
    """PO-4: the row emits; nothing is connected to it in this story."""
    row = _show_row(qtbot, _line("failed", index=4, proposed_en=None), region_id=4)
    with qtbot.waitSignal(row.retryRequested, timeout=1000) as blocker:
        QTest.mouseClick(row.retry_button, Qt.MouseButton.LeftButton)
    assert blocker.args == [4]


# =============================================================================
# The row follows the editor's status (AC-9 recomputed on statusChanged)
# =============================================================================


def test_accepting_by_keyboard_turns_the_row_accepted_and_removes_accept(qtbot) -> None:  # type: ignore[no-untyped-def]
    row = _show_row(qtbot, _line("proposed"))
    _focus(qtbot, row.editor)
    _key(row.editor, Qt.Key.Key_Return, CTRL)

    assert row.gutter.text() == DESIGN_GLYPHS["accepted"]
    assert _gutter_colour(row) == _token_colour("accepted")
    assert _actions(row) == DESIGN_ACTIONS["accepted"]


def test_the_accept_button_accepts_the_line(qtbot) -> None:  # type: ignore[no-untyped-def]
    row = _show_row(qtbot, _line("proposed"))
    QTest.mouseClick(row.accept_button, Qt.MouseButton.LeftButton)
    _settle()

    assert row.editor.status == "accepted"
    assert row.gutter.text() == DESIGN_GLYPHS["accepted"]


def test_editing_then_pressing_revert_walks_the_row_through_edited_to_reverted(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-2 as the user sees it: edited shows the pencil and Revert; Revert puts
    the proposal back exactly and the row reads reverted - visibly not proposed."""
    row = _show_row(qtbot, _line("proposed", proposed_en=P))
    _focus(qtbot, row.editor)
    _type(row.editor, "Coffee.")
    _key(row.editor, Qt.Key.Key_Return)

    assert row.gutter.text() == DESIGN_GLYPHS["edited"]
    assert _gutter_colour(row) == _token_colour("edited")
    assert _actions(row) == DESIGN_ACTIONS["edited"]

    QTest.mouseClick(row.revert_button, Qt.MouseButton.LeftButton)
    _settle()

    assert row.editor.text() == P
    assert row.editor.status == "reverted"
    assert row.gutter.text() == DESIGN_GLYPHS["reverted"]
    assert row.gutter.text() != DESIGN_GLYPHS["proposed"]
    assert _gutter_colour(row) == _token_colour("reverted")
    assert _actions(row) == DESIGN_ACTIONS["reverted"]


def test_a_failed_save_shows_not_saved_and_the_reason_on_the_row_and_keeps_the_text(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-7 as rendered: the caption says why, the typing stays."""

    def failing(_text: str | None, _status: str) -> None:
        raise OSError("disk is full")

    row = _show_row(qtbot, _line("proposed"), failing)
    _focus(qtbot, row.editor)
    _type(row.editor, "My own words")
    _key(row.editor, Qt.Key.Key_Return)
    row.editor.flush()
    _settle()

    assert row.editor.text() == "My own words"
    assert row.error_caption.isVisibleTo(row)
    assert row.error_caption.text() == "Not saved: disk is full"


# =============================================================================
# The column: lines=, effective text, accessible phrases
# =============================================================================


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


def _grid(count: int) -> list[OrderedRegion]:
    return [
        OrderedRegion(
            region_id=i,
            polygon=_ring(i),
        )
        for i in range(count)
    ]


def _five_status_rows(window: Workspace) -> None:
    lines = [_status_line(status, index) for index, status in enumerate(STATUSES)]
    window.set_regions(
        _grid(len(lines)),
        [None if line.ocr_empty else line.source_ja for line in lines],
        [line.proposed_en for line in lines],
        lines=lines,
    )
    _settle()


def _item_texts(window: Workspace) -> list[str]:
    lst = window.translation_column.list
    return [lst.item(i).data(Qt.ItemDataRole.AccessibleTextRole) for i in range(lst.count())]


def test_rows_built_from_lines_read_their_status_in_the_accessible_name(qtbot) -> None:  # type: ignore[no-untyped-def]
    """§5 accessible name, with the per-status phrase; English is the row's
    shown (effective) text."""
    window = _open(qtbot)
    _five_status_rows(window)

    assert _item_texts(window) == [
        "Bubble 1 of 5. Japanese: ja 0. English: Hello.. machine proposal.",
        "Bubble 2 of 5. Japanese: ja 1. English: Hello.. accepted.",
        "Bubble 3 of 5. Japanese: ja 2. English: Mine. edited.",
        "Bubble 4 of 5. Japanese: ja 3. English: Hello.. edited, then returned to the proposal.",
        "Bubble 5 of 5. Japanese: not read. English: not translated."
        " translation failed: no text was read in this bubble.",
    ]


def test_a_rows_accessible_name_follows_its_status_change(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot)
    _five_status_rows(window)
    editor = window.translation_column.row(0).editor
    _focus(qtbot, editor)
    _key(editor, Qt.Key.Key_Return, CTRL)

    assert _item_texts(window)[0] == "Bubble 1 of 5. Japanese: ja 0. English: Hello.. accepted."


def test_rows_given_lines_show_the_committed_text_over_the_proposal(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot)
    _five_status_rows(window)

    shown = [window.translation_column.row(i).editor.text() for i in range(len(STATUSES))]
    assert shown == ["Hello.", "Hello.", "Mine", "Hello.", ""]


def test_three_argument_rows_are_unsaved_proposed_lines_as_mt016_left_them(qtbot) -> None:  # type: ignore[no-untyped-def]
    """`lines=None` synthesizes a proposed line with `save=None` for every row."""
    window = _open(qtbot)
    window.set_regions(_grid(2), ["ja 0", None], ["en 0", None])
    _settle()

    for i in range(2):
        row = window.translation_column.row(i)
        assert row.editor.status == "proposed"
        assert row.gutter.text() == DESIGN_GLYPHS["proposed"]
        assert _actions(row) == DESIGN_ACTIONS["proposed"]
    assert window.translation_column.row(0).editor.text() == "en 0"

    editor = window.translation_column.row(0).editor
    _focus(qtbot, editor)
    _type(editor, "typed")
    _key(editor, Qt.Key.Key_Return)
    editor.flush()
    assert editor.status == "edited"
    assert not window.translation_column.row(0).error_caption.isVisibleTo(
        window.translation_column.row(0)
    )


def test_selection_and_hover_change_no_rows_controls(qtbot) -> None:  # type: ignore[no-untyped-def]
    """ "Never hover reveals", in the column: select one row, hover another; every
    row still shows exactly its status's controls."""
    window = _open(qtbot)
    _five_status_rows(window)
    column = window.translation_column

    for selected, hovered in ((0, 1), (2, 4), (4, 3)):
        window.link.select(selected)
        window.link.hover(hovered)
        _settle()
        got = [_actions(column.row(i)) for i in range(len(STATUSES))]
        assert got == [DESIGN_ACTIONS[s] for s in STATUSES], (selected, hovered)


# =============================================================================
# The workspace over a real project: AC-1, flushes, AC-6, AC-8
# =============================================================================

#: Page 0's lines: `(source_ja, ocr_empty)` and the proposals by reading index.
PAGE0_OCR = (("一", False), ("二", False), ("三", False), ("四", False), ("", True))
PAGE0_PROPOSED = {0: "Hello.", 1: "Fine.", 2: "Wait!", 3: P}
PAGE1_OCR = (("五", False),)
PAGE1_PROPOSED = {0: "Next page."}


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


def _store(
    project: Project,
    ordinal: int,
    ocr: tuple[tuple[str, bool], ...],
    proposed: dict[int, str],
    mask: bytes,
) -> None:
    project.write_regions(
        ordinal,
        [
            RawRegion(polygon=_ring(i), mask=mask, confidence=0.9, kind="bubble")
            for i in range(len(ocr))
        ],
    )
    project.write_lines(ordinal, [OcrResult(ja, ocr_empty=empty) for ja, empty in ocr])
    project.write_proposed(ordinal, proposed)


@pytest.fixture
def chapter_dir(tmp_path: Path, page_png: bytes, mask_png: bytes) -> Path:
    """A two-page project on disk, CLOSED: each test opens it as it needs."""
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
        _store(project, 0, PAGE0_OCR, PAGE0_PROPOSED, mask_png)
        _store(project, 1, PAGE1_OCR, PAGE1_PROPOSED, mask_png)
    return project_dir


@pytest.fixture
def project(chapter_dir: Path) -> Iterator[Project]:
    with open_project(chapter_dir) as opened:
        yield opened


def _on_disk(project_dir: Path, ordinal: int) -> list[tuple[object, object]]:
    """`(final_en, status)` per line of a page, read by a separate connection."""
    connection = sqlite3.connect(project_dir / "project.db")
    try:
        return list(
            connection.execute(
                "SELECT line.final_en, line.status"
                " FROM line JOIN region ON region.id = line.region_id"
                " JOIN page ON page.id = region.page_id"
                " WHERE page.ordinal = ? ORDER BY region.reading_index",
                (ordinal,),
            )
        )
    finally:
        connection.close()


def _showing(qtbot, project: Project, ordinal: int = 0) -> Workspace:  # type: ignore[no-untyped-def]
    window = _open(qtbot)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(ordinal)
    _settle()
    return window


def _editor(window: Workspace, index: int):  # type: ignore[no-untyped-def]
    return window.translation_column.row(index).editor


def test_an_edit_is_in_the_project_file_within_500_ms_of_enter(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    chapter_dir: Path,
) -> None:
    """AC-1, observed as the criterion states it: a second connection to the
    project file sees the new text within the literal 500 ms, plus named
    event-loop slack. No flush is called."""
    window = _showing(qtbot, project)
    editor = _editor(window, 0)
    _focus(qtbot, editor)
    _type(editor, "Hi there.")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    committed = time.monotonic()

    qtbot.waitUntil(
        lambda: _on_disk(chapter_dir, 0)[0] == ("Hi there.", "edited"),
        timeout=4 * (DESIGN_SAVE_BOUND_MS + SLACK_MS),
    )
    elapsed_ms = (time.monotonic() - committed) * 1000

    assert editor.status == "edited"
    assert elapsed_ms <= DESIGN_SAVE_BOUND_MS + SLACK_MS, f"on disk {elapsed_ms:.0f} ms after Enter"


def test_changing_page_writes_a_pending_save_before_the_rows_are_replaced(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    chapter_dir: Path,
) -> None:
    """C-7/C-8: `set_rows` flushes every row's editor before discarding it - and
    the save lands on the page it was made on, not the page shown next."""
    window = _showing(qtbot, project)
    editor = _editor(window, 1)
    _focus(qtbot, editor)
    _key(editor, Qt.Key.Key_Return, CTRL)

    window.page_strip.setCurrentRow(1)

    assert _on_disk(chapter_dir, 0)[1] == (None, "accepted")
    assert _on_disk(chapter_dir, 1) == [(None, None)]


def test_closing_the_workspace_writes_a_pending_save(
    qtbot,  # type: ignore[no-untyped-def]
    project: Project,
    chapter_dir: Path,
) -> None:
    window = _showing(qtbot, project)
    editor = _editor(window, 2)
    _focus(qtbot, editor)
    _type(editor, "Wait for me!")
    _key(editor, Qt.Key.Key_Return)

    window.close()

    assert _on_disk(chapter_dir, 0)[2] == ("Wait for me!", "edited")


def test_every_status_text_and_glyph_survives_closing_and_reopening_the_app(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_dir: Path,
) -> None:
    """AC-6. Every act through the editor's keys; nothing waited for, so the
    close is what must write; the Workspace and the Project both closed; the
    same directory reopened into a fresh Workspace."""
    with open_project(chapter_dir) as project:
        window = _showing(qtbot, project)
        # row 0: untouched -> proposed
        _focus(qtbot, _editor(window, 1))  # row 1: accepted
        _key(_editor(window, 1), Qt.Key.Key_Return, CTRL)
        _focus(qtbot, _editor(window, 2))  # row 2: edited
        _type(_editor(window, 2), "Wait for me!")
        _key(_editor(window, 2), Qt.Key.Key_Return)
        _focus(qtbot, _editor(window, 3))  # row 3: edited, then reverted
        _type(_editor(window, 3), "Coffee.")
        _key(_editor(window, 3), Qt.Key.Key_Return)
        _key(_editor(window, 3), Qt.Key.Key_R, CTRL)
        # row 4: ocr_empty, untouched -> failed
        window.close()
        _settle()

    assert _on_disk(chapter_dir, 0) == [
        (None, None),
        (None, "accepted"),
        ("Wait for me!", "edited"),
        (P, "reverted"),
        (None, None),
    ]

    with open_project(chapter_dir) as reopened:
        fresh = _showing(qtbot, reopened)
        got = [
            (row.editor.text(), row.editor.status, row.gutter.text())
            for row in (fresh.translation_column.row(i) for i in range(len(PAGE0_OCR)))
        ]
        fresh.close()

    assert got == [
        ("Hello.", "proposed", DESIGN_GLYPHS["proposed"]),
        ("Fine.", "accepted", DESIGN_GLYPHS["accepted"]),
        ("Wait for me!", "edited", DESIGN_GLYPHS["edited"]),
        (P, "reverted", DESIGN_GLYPHS["reverted"]),
        ("", "failed", DESIGN_GLYPHS["failed"]),
    ]


def test_a_finished_pages_untranslated_region_shows_failed_with_retry(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_dir: Path,
    mask_png: bytes,
) -> None:
    """AC-8 through the store: MT-011 AC-5's untranslated region on a page the
    run finished is failed; the same NULL proposal on an unfinished page is a
    plain proposed line (PO-3)."""
    with open_project(chapter_dir) as project:
        _store(project, 1, (("五", False), ("六", False)), {0: "Next page."}, mask_png)
        pending = _showing(qtbot, project, 1)
        pending_row = pending.translation_column.row(1)
        pending_state = (pending_row.editor.status, _actions(pending_row))
        pending.close()

        with project.transaction() as cursor:
            cursor.execute("UPDATE page SET status = ? WHERE ordinal = 1", (PAGE_DONE,))
        done = _showing(qtbot, project, 1)
        row = done.translation_column.row(1)

        assert pending_state == ("proposed", DESIGN_ACTIONS["proposed"])
        assert row.editor.status == "failed"
        assert _actions(row) == DESIGN_ACTIONS["failed"]
        assert row.error_caption.text() == REASON_UNTRANSLATED
        assert _item_texts(done)[1] == (
            "Bubble 2 of 2. Japanese: 六. English: not translated."
            " translation failed: no translation was returned."
        )
        done.close()


def test_the_workspaces_rows_carry_the_stored_statuses(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_dir: Path,
) -> None:
    """`_load_regions` reads `store.lines.read_review_lines`: a status committed
    by the store alone is what the row shows."""
    from mangatl.store.lines import commit_line

    with open_project(chapter_dir) as project:
        commit_line(project, 0, 0, None, "accepted")
        commit_line(project, 0, 2, "Hold on.", "edited")
        window = _showing(qtbot, project)
        got = [
            (window.translation_column.row(i).editor.status, _editor(window, i).text())
            for i in range(len(PAGE0_OCR))
        ]
        window.close()

    assert got == [
        ("accepted", "Hello."),
        ("proposed", "Fine."),
        ("edited", "Hold on."),
        ("proposed", P),
        ("failed", ""),
    ]
