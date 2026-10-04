"""MT-066 C-2: `BakeConfirmDialog`, what the Render dialog says and does.

The dialog is presentational: it is built from a `BakePreview` value and reads
no project, so every test here builds the preview directly.

**Oracle: mechanical, pinned exactly** (C-6). Every row of C-2's copy table -
zero, singular and plural, the `page `/`pages ` prefix, distinct ascending
1-based page numbers - is spelled out below character for character, never read
back from the module under test. voice.md: the interface says *render*, never
*bake*, and one test checks every visible string for it.

AC-2 (review does not gate the bake) and the dialog's half of AC-3 (modal, the
initial focus, Tab stays inside) are here too. Focus returning to the invoking
control is the workspace's job (C-2, C-4) and is in `test_bake_render.py`.

**Offscreen focus** (measured in RED on a scratch `QDialog`, story
`## Handoff`): under `QT_QPA_PLATFORM=offscreen` a modal dialog opened with
`open()` becomes the active window and Tab/Shift+Tab cycle only its own
children. Every focus read waits with a bounded `qtbot.waitUntil`.

RED: `mangatl.ui.bake_dialog` does not exist and `mangatl.pipeline.bake` has no
`BakePreview`, so this file fails at import and no assertion in it has run.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMainWindow, QPushButton, QWidget

from mangatl.pipeline.bake import BakePreview, LineRef
from mangatl.ui.bake_dialog import BakeConfirmDialog

TITLE = "Render pages"
#: A folder name holding markup: PlainText must show it as typed.
MARKUP_DIR = Path("/library") / "<b>ch 1</b> & co_en"
OUT = Path("/library") / "ch 01_en"
FOCUS_MS = 2_000

LABELS = ("bakeOutputFolder", "bakeUnreviewed", "bakeFailed", "bakeOverflow")


def _refs(pairs: Sequence[tuple[int, int]]) -> tuple[LineRef, ...]:
    return tuple(LineRef(page_ordinal=p, reading_index=i) for p, i in pairs)


def _preview(
    *,
    output_dir: Path = OUT,
    page_count: int = 12,
    total_lines: int = 40,
    unreviewed: Sequence[tuple[int, int]] = (),
    failed: Sequence[tuple[int, int]] = (),
    overflowing: Sequence[tuple[int, int]] = (),
) -> BakePreview:
    return BakePreview(
        output_dir=output_dir,
        page_count=page_count,
        total_lines=total_lines,
        unreviewed=_refs(unreviewed),
        failed=_refs(failed),
        overflowing=_refs(overflowing),
    )


def _dialog(qtbot, preview: BakePreview) -> BakeConfirmDialog:  # type: ignore[no-untyped-def]
    dialog = BakeConfirmDialog(preview)
    qtbot.addWidget(dialog)
    return dialog


def _label(dialog: QDialog, name: str) -> QLabel:
    found = dialog.findChild(QLabel, name)
    assert isinstance(found, QLabel), f"the dialog has no QLabel named {name!r}"
    return found


def _text(dialog: QDialog, name: str) -> str:
    return _label(dialog, name).text()


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# The copy table (AC-1), row by row
# =============================================================================


def test_the_window_title_and_accessible_name_are_render_pages(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview())

    assert dialog.windowTitle() == TITLE
    assert dialog.accessibleName() == TITLE


def test_the_output_folder_is_stated_as_the_path_itself(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(output_dir=OUT))

    assert _text(dialog, "bakeOutputFolder") == str(OUT)


def test_a_folder_name_holding_markup_is_shown_as_typed_not_rendered(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(output_dir=MARKUP_DIR))
    label = _label(dialog, "bakeOutputFolder")

    assert label.text() == str(MARKUP_DIR)
    assert label.textFormat() == Qt.TextFormat.PlainText


def test_the_output_folder_can_be_selected_by_mouse_and_by_keyboard(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview())
    flags = _label(dialog, "bakeOutputFolder").textInteractionFlags()

    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert flags & Qt.TextInteractionFlag.TextSelectableByKeyboard


def test_every_label_is_plain_text_and_word_wraps(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(unreviewed=[(0, 0)], failed=[(1, 0)], overflowing=[(2, 0)]))

    for name in LABELS:
        label = _label(dialog, name)
        assert label.textFormat() == Qt.TextFormat.PlainText, f"{name} is not PlainText"
        assert label.wordWrap(), f"{name} does not word-wrap"


def test_a_chapter_with_no_lines_says_none_were_found(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(total_lines=0))

    assert _text(dialog, "bakeUnreviewed") == "No lines were found on any page."


def test_a_fully_reviewed_chapter_says_all_lines_were_reviewed(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(total_lines=7))

    assert _text(dialog, "bakeUnreviewed") == "All 7 lines were reviewed."


def test_one_unreviewed_line_is_singular_and_names_its_page(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(total_lines=7, unreviewed=[(2, 3)]))

    assert _text(dialog, "bakeUnreviewed") == (
        "1 of 7 lines was never reviewed (page 3). Render anyway?"
    )


def test_unreviewed_lines_on_one_page_name_that_page_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(total_lines=7, unreviewed=[(1, 0), (1, 2), (1, 3)]))

    assert _text(dialog, "bakeUnreviewed") == (
        "3 of 7 lines were never reviewed (page 2). Render anyway?"
    )


def test_unreviewed_lines_on_several_pages_list_each_page_once_in_ascending_order(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(
        qtbot,
        _preview(total_lines=40, unreviewed=[(0, 1), (0, 3), (2, 0), (9, 1), (9, 2), (11, 0)]),
    )

    assert _text(dialog, "bakeUnreviewed") == (
        "6 of 40 lines were never reviewed (pages 1, 3, 10, 12). Render anyway?"
    )


def test_one_failed_line_is_singular(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(failed=[(3, 1)]))

    assert _text(dialog, "bakeFailed") == (
        "1 line could not be translated and will be left empty (page 4)."
    )


def test_several_failed_lines_are_plural_and_list_their_pages(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(failed=[(0, 0), (0, 2), (1, 1)]))

    assert _text(dialog, "bakeFailed") == (
        "3 lines could not be translated and will be left empty (pages 1, 2)."
    )


def test_one_overflowing_line_is_singular(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(overflowing=[(0, 3)]))

    assert _text(dialog, "bakeOverflow") == (
        "1 line does not fit its bubble and will be cut off (page 1)."
    )


def test_several_overflowing_lines_are_plural_and_list_their_pages(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(overflowing=[(0, 3), (5, 3)]))

    assert _text(dialog, "bakeOverflow") == (
        "2 lines do not fit their bubble and will be cut off (pages 1, 6)."
    )


@pytest.mark.parametrize(("failed", "overflowing"), [((), ()), (((0, 1),), ()), ((), ((0, 1),))])
def test_the_failed_and_overflow_statements_exist_and_hide_when_their_count_is_zero(
    qtbot,  # type: ignore[no-untyped-def]
    failed: tuple[tuple[int, int], ...],
    overflowing: tuple[tuple[int, int], ...],
) -> None:
    dialog = _dialog(qtbot, _preview(failed=failed, overflowing=overflowing))

    assert _label(dialog, "bakeFailed").isVisibleTo(dialog) is bool(failed)
    assert _label(dialog, "bakeOverflow").isVisibleTo(dialog) is bool(overflowing)
    assert _label(dialog, "bakeOutputFolder").isVisibleTo(dialog)
    assert _label(dialog, "bakeUnreviewed").isVisibleTo(dialog)


@pytest.mark.parametrize(("pages", "text"), [(1, "Render 1 page"), (12, "Render 12 pages")])
def test_the_primary_action_names_the_page_count(qtbot, pages: int, text: str) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(page_count=pages))

    assert dialog.confirm_button.text() == text


def test_the_buttons_carry_their_names_and_the_primary_variant(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview())

    assert isinstance(dialog.confirm_button, QPushButton)
    assert isinstance(dialog.cancel_button, QPushButton)
    assert dialog.confirm_button.objectName() == "bakeConfirm"
    assert dialog.confirm_button.property("variant") == "primary"
    assert dialog.cancel_button.objectName() == "bakeCancel"
    assert dialog.cancel_button.text() == "Cancel"


def test_the_accessible_description_is_every_shown_statement_in_order(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(
        qtbot,
        _preview(total_lines=9, unreviewed=[(0, 0), (1, 0)], failed=[(1, 1)], overflowing=[(4, 3)]),
    )

    assert dialog.accessibleDescription() == "\n".join(
        [
            str(OUT),
            "2 of 9 lines were never reviewed (pages 1, 2). Render anyway?",
            "1 line could not be translated and will be left empty (page 2).",
            "1 line does not fit its bubble and will be cut off (page 5).",
        ]
    )


def test_the_accessible_description_leaves_out_hidden_statements(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview(total_lines=9, overflowing=[(4, 3)]))

    assert dialog.accessibleDescription() == "\n".join(
        [
            str(OUT),
            "All 9 lines were reviewed.",
            "1 line does not fit its bubble and will be cut off (page 5).",
        ]
    )


def test_no_visible_string_says_bake(qtbot) -> None:  # type: ignore[no-untyped-def]
    # voice.md: the interface says "render". OUT holds no "bake" itself.
    dialog = _dialog(
        qtbot, _preview(unreviewed=[(0, 0), (1, 1)], failed=[(1, 0)], overflowing=[(2, 0)])
    )
    shown = [
        dialog.windowTitle(),
        dialog.accessibleName(),
        dialog.accessibleDescription(),
        dialog.confirm_button.text(),
        dialog.cancel_button.text(),
        *(_text(dialog, name) for name in LABELS),
    ]

    assert [s for s in shown if "bake" in s.lower()] == []


# =============================================================================
# AC-2: review does not gate the bake; confirm accepts, Cancel and Esc reject
# =============================================================================


@pytest.fixture
def host(qtbot) -> QMainWindow:  # type: ignore[no-untyped-def]
    window = QMainWindow()
    central = QPushButton("elsewhere")
    window.setCentralWidget(central)
    qtbot.addWidget(window)
    window.resize(600, 400)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    return window


def _opened(qtbot, host: QWidget, preview: BakePreview) -> BakeConfirmDialog:  # type: ignore[no-untyped-def]
    dialog = BakeConfirmDialog(preview, host)
    dialog.open()
    qtbot.waitUntil(dialog.isVisible, timeout=FOCUS_MS)
    _settle()
    return dialog


def test_with_unreviewed_lines_the_primary_action_is_shown_enabled_and_default(
    qtbot,  # type: ignore[no-untyped-def]
    host: QMainWindow,
) -> None:
    dialog = _opened(qtbot, host, _preview(total_lines=5, unreviewed=[(0, 0), (0, 1), (2, 0)]))

    assert dialog.confirm_button.isVisible()
    assert dialog.confirm_button.isEnabled()
    assert dialog.confirm_button.isDefault()


def test_with_unreviewed_lines_confirming_accepts_the_dialog(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview(total_lines=5, unreviewed=[(0, 0), (0, 1), (2, 0)]))

    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS) as finished:
        QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert finished.args == [QDialog.DialogCode.Accepted.value]
    assert dialog.result() == QDialog.DialogCode.Accepted.value


def test_cancel_rejects_the_dialog(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview(unreviewed=[(0, 0)]))

    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS) as finished:
        QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)

    assert finished.args == [QDialog.DialogCode.Rejected.value]


def test_escape_rejects_the_dialog(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview(unreviewed=[(0, 0)]))
    qtbot.waitUntil(lambda: QApplication.focusWidget() is dialog.confirm_button, timeout=FOCUS_MS)

    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS) as finished:
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)

    assert finished.args == [QDialog.DialogCode.Rejected.value]


# =============================================================================
# AC-3 (the dialog's half): modal, initial focus on confirm, Tab stays inside
# =============================================================================


def test_the_dialog_is_modal(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview())

    assert dialog.isModal()


def test_the_dialog_opens_with_focus_on_the_primary_action(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview(unreviewed=[(0, 0)]))

    qtbot.waitUntil(lambda: QApplication.focusWidget() is dialog.confirm_button, timeout=FOCUS_MS)


@pytest.mark.parametrize("key", [Qt.Key.Key_Tab, Qt.Key.Key_Backtab], ids=["tab", "shift-tab"])
def test_tabbing_more_times_than_there_are_controls_never_leaves_the_dialog(
    qtbot,  # type: ignore[no-untyped-def]
    host: QMainWindow,
    key: Qt.Key,
) -> None:
    dialog = _opened(
        qtbot, host, _preview(unreviewed=[(0, 0)], failed=[(1, 0)], overflowing=[(2, 0)])
    )
    qtbot.waitUntil(lambda: QApplication.focusWidget() is dialog.confirm_button, timeout=FOCUS_MS)
    focusable = [
        w
        for w in dialog.findChildren(QWidget)
        if w.focusPolicy() & Qt.FocusPolicy.TabFocus and w.isVisibleTo(dialog)
    ]
    presses = len(focusable) + 3

    outside = []
    for _ in range(presses):
        QTest.keyClick(QApplication.focusWidget(), key)
        _settle()
        focused = QApplication.focusWidget()
        if focused is None or not (focused is dialog or dialog.isAncestorOf(focused)):
            outside.append(focused)

    assert outside == [], f"Tab moved focus out of the dialog to {outside!r}"
