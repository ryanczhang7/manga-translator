"""MT-125 C-2: `RerunDialog`, what "Run again" says before it runs.

The dialog is presentational: it is built from a `RerunPreview` value (MT-124)
and reads no project, so every test here builds the preview directly.

**Oracle: settled, read out** (story `## Design notes`, the Lead Designer's pass
of 2026-10-30, and `components.md` §9 `RerunDialog`). Every line below is
spelled out character for character, never read back from the module under
test: the four lines by object name (`rerunPages`, `rerunStages`,
`rerunEstimate`, `rerunBudget`), the singular and plural forms (the noun
follows its own number; in `{n} of {m} pages` it follows `{m}`), the
`ocr` -> *read* verb, a fake stage name used verbatim as its own verb, the
zero-spent sentence (never `$0.00`), the two over-budget sentences, `format_usd`
money (thousands commas, a fraction of a cent rounded up) and the
nothing-to-run state with `Close` alone. The one sentence the design says is
imported rather than retyped, `cost_estimate.OVER_BUDGET`, is spelled here: the
observable output is what is pinned, not where the string lives.

"Absent rather than empty" is read as: no *shown* label of that name. A label
that exists and is hidden satisfies it; one that is shown with empty text does
not. The accessible description is the shown lines joined by `\\n`.

**Offscreen focus**: as `test_bake_dialog.py` measured in MT-066 RED, a modal
dialog opened with `open()` becomes the active window offscreen; every focus
read waits with a bounded `qtbot.waitUntil`.

RED: `mangatl.ui.rerun_dialog` does not exist, so this file fails at import and
no assertion in it has run; the story's handoff records each control's
expected value.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMainWindow, QPushButton

from mangatl.domain.money import Usd
from mangatl.pipeline.resume import RerunPreview
from mangatl.ui.rerun_dialog import TITLE, RerunDialog

# --- Settled copy, spelled out --------------------------------------------------
DIALOG_TITLE = "Run again"
ALREADY_SPENT_TEXT = "The budget is already spent."
NOTHING_TO_RUN = "Every page is done. Nothing to run."

LINE_NAMES = ("rerunPages", "rerunStages", "rerunEstimate", "rerunBudget")
FOCUS_MS = 2_000


def usd(text: str) -> Usd:
    return Usd(Decimal(text))


def _preview(
    *,
    page_count: int = 4,
    pages_to_run: int = 2,
    pending: Mapping[str, int] | None = None,
    pages_to_translate: int = 2,
    spent: str = "0.83",
    ceiling: str = "2.00",
    estimate: str = "0.12",
    within_budget: bool = True,
) -> RerunPreview:
    return RerunPreview(
        page_count=page_count,
        pages_to_run=pages_to_run,
        pending=dict(pending) if pending is not None else {"detect": 2, "translate": 2},
        pages_to_translate=pages_to_translate,
        spent=usd(spent),
        ceiling=usd(ceiling),
        estimate=usd(estimate),
        within_budget=within_budget,
    )


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _dialog(qtbot, preview: RerunPreview) -> RerunDialog:  # type: ignore[no-untyped-def]
    dialog = RerunDialog(preview)
    qtbot.addWidget(dialog)
    return dialog


def _shown_lines(dialog: QDialog) -> list[str]:
    """The text of every shown line, top to bottom, by object name."""
    lines: list[tuple[int, str]] = []
    for name in LINE_NAMES:
        label = dialog.findChild(QLabel, name)
        if isinstance(label, QLabel) and not label.isHidden():
            lines.append((LINE_NAMES.index(name), label.text()))
    return [text for _, text in sorted(lines)]


def _buttons(dialog: QDialog) -> list[QPushButton]:
    return [b for b in dialog.findChildren(QPushButton) if not b.isHidden()]


@pytest.fixture
def host(qtbot) -> QMainWindow:  # type: ignore[no-untyped-def]
    window = QMainWindow()
    window.setCentralWidget(QPushButton("elsewhere"))
    qtbot.addWidget(window)
    window.resize(600, 400)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    return window


def _opened(qtbot, host: QMainWindow, preview: RerunPreview) -> RerunDialog:  # type: ignore[no-untyped-def]
    dialog = RerunDialog(preview, host)
    dialog.open()
    qtbot.waitUntil(dialog.isVisible, timeout=FOCUS_MS)
    _settle()
    return dialog


# =============================================================================
# C-2: the export shape and the title
# =============================================================================


def test_the_module_exports_the_dialog_and_nothing_else() -> None:
    import mangatl.ui.rerun_dialog as module

    assert module.__all__ == ["RerunDialog"]


def test_the_title_constant_is_the_buttons_own_word() -> None:
    assert TITLE == DIALOG_TITLE


def test_the_window_title_and_accessible_name_are_run_again(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview())

    assert dialog.windowTitle() == DIALOG_TITLE
    assert dialog.accessibleName() == DIALOG_TITLE


# =============================================================================
# AC-2 / AC-9: the lines, character for character
# =============================================================================


@pytest.mark.parametrize(
    ("preview", "lines", "primary"),
    [
        pytest.param(
            _preview(),
            [
                "2 of 4 pages still to run.",
                "2 to detect, 2 to translate.",
                "Estimated cost to translate 2 pages: $0.12.",
                "$0.83 spent of the $2.00 budget.",
            ],
            "Run 2 pages",
            id="two-of-four",
        ),
        pytest.param(
            _preview(
                page_count=1,
                pages_to_run=1,
                pending={"detect": 1, "clean": 1, "ocr": 1, "translate": 1},
                pages_to_translate=1,
                spent="0",
                estimate="0.06",
            ),
            [
                "1 of 1 page still to run.",
                "1 to detect, 1 to clean, 1 to read, 1 to translate.",
                "Estimated cost to translate 1 page: $0.06.",
                "Nothing spent yet of the $2.00 budget.",
            ],
            "Run 1 page",
            id="one-of-one-every-stage-nothing-spent",
        ),
        pytest.param(
            _preview(
                page_count=4,
                pages_to_run=1,
                pending={"detect": 0, "clean": 1, "ocr": 0, "translate": 0},
                pages_to_translate=0,
                spent="0",
                estimate="0",
            ),
            [
                "1 of 4 pages still to run.",
                "1 to clean.",
                "Nothing spent yet of the $2.00 budget.",
            ],
            "Run 1 page",
            id="ac9-one-page-to-clean-no-estimate",
        ),
        pytest.param(
            _preview(
                pages_to_run=3,
                pending={"detect": 1, "clean": 0, "ocr": 3, "translate": 3},
                pages_to_translate=3,
                spent="1.95",
                estimate="0.18",
                within_budget=False,
            ),
            [
                "3 of 4 pages still to run.",
                "1 to detect, 3 to read, 3 to translate.",
                "Estimated cost to translate 3 pages: $0.18.",
                "$1.95 spent of the $2.00 budget. The estimate is over budget.",
            ],
            "Run 3 pages",
            id="over-budget-with-an-estimate",
        ),
        pytest.param(
            _preview(
                pages_to_run=1,
                pending={"detect": 0, "clean": 1, "ocr": 0, "translate": 0},
                pages_to_translate=0,
                spent="2.10",
                estimate="0",
                within_budget=False,
            ),
            [
                "1 of 4 pages still to run.",
                "1 to clean.",
                "$2.10 spent of the $2.00 budget. The budget is already spent.",
            ],
            "Run 1 page",
            id="over-budget-with-nothing-to-translate",
        ),
        pytest.param(
            _preview(
                pages_to_run=2,
                pending={"b": 1, "a": 2},
                pages_to_translate=0,
                spent="1234.5",
                ceiling="1200",
                estimate="0",
                within_budget=False,
            ),
            [
                "2 of 4 pages still to run.",
                "1 to b, 2 to a.",
                "$1,234.50 spent of the $1,200.00 budget. The budget is already spent.",
            ],
            "Run 2 pages",
            id="fake-stage-names-verbatim-in-stage-order-and-thousands",
        ),
        pytest.param(
            _preview(estimate="0.1201", spent="0.001"),
            [
                "2 of 4 pages still to run.",
                "2 to detect, 2 to translate.",
                "Estimated cost to translate 2 pages: $0.13.",
                "$0.01 spent of the $2.00 budget.",
            ],
            "Run 2 pages",
            id="a-fraction-of-a-cent-rounds-up",
        ),
    ],
)
def test_the_dialog_states_the_preview_in_the_design_notes_copy(
    qtbot,  # type: ignore[no-untyped-def]
    preview: RerunPreview,
    lines: list[str],
    primary: str,
) -> None:
    dialog = _dialog(qtbot, preview)

    assert _shown_lines(dialog) == lines
    assert dialog.run_button is not None, "a preview with pages to run has no primary action"
    assert dialog.run_button.text() == primary
    assert dialog.cancel_button.text() == "Cancel"


def test_control_within_budget_by_a_cent_carries_no_over_budget_sentence(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The over-budget case's control: the same figures, `within_budget` true."""
    dialog = _dialog(qtbot, _preview(spent="1.82", estimate="0.18", within_budget=True))

    assert _shown_lines(dialog)[-1] == "$1.82 spent of the $2.00 budget."
    assert dialog.property("overBudget") is False


def test_the_accessible_description_is_the_shown_lines_joined_by_newlines(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(
        qtbot,
        _preview(
            pages_to_run=1,
            pending={"detect": 0, "clean": 1, "ocr": 0, "translate": 0},
            pages_to_translate=0,
            spent="0",
            estimate="0",
        ),
    )

    assert dialog.accessibleDescription() == "\n".join(
        ["1 of 4 pages still to run.", "1 to clean.", "Nothing spent yet of the $2.00 budget."]
    )


@pytest.mark.parametrize(
    ("preview", "over"),
    [
        (_preview(within_budget=True), False),
        (_preview(spent="1.95", estimate="0.18", within_budget=False), True),
        (
            _preview(
                pending={"clean": 1},
                pages_to_run=1,
                pages_to_translate=0,
                spent="2.10",
                estimate="0",
                within_budget=False,
            ),
            True,
        ),
    ],
    ids=["within", "over-with-estimate", "over-already-spent"],
)
def test_the_over_budget_property_is_the_previews_bool(
    qtbot,  # type: ignore[no-untyped-def]
    preview: RerunPreview,
    over: bool,
) -> None:
    dialog = _dialog(qtbot, preview)

    assert dialog.property("overBudget") is over


def test_every_line_is_plain_text_and_word_wraps(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A fake stage's name is its own verb, verbatim: markup in it is shown as typed."""
    dialog = _dialog(qtbot, _preview(pending={"<b>x</b>": 2}))

    assert _shown_lines(dialog)[1] == "2 to <b>x</b>."
    for name in LINE_NAMES:
        label = dialog.findChild(QLabel, name)
        if isinstance(label, QLabel) and not label.isHidden():
            assert label.textFormat() == Qt.TextFormat.PlainText, name
            assert label.wordWrap(), name


# =============================================================================
# AC-2 control: nothing to run
# =============================================================================


def _nothing_to_run() -> RerunPreview:
    return _preview(
        pages_to_run=0,
        pending={"detect": 0, "translate": 0},
        pages_to_translate=0,
        spent="0.83",
        estimate="0",
    )


def test_with_every_page_done_the_dialog_says_nothing_is_left_to_run(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _nothing_to_run())

    assert _shown_lines(dialog) == [NOTHING_TO_RUN, "$0.83 spent of the $2.00 budget."]


def test_with_every_page_done_there_is_no_primary_and_close_is_the_only_button(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _nothing_to_run())

    assert dialog.run_button is None
    assert dialog.cancel_button.text() == "Close"
    assert [b.text() for b in _buttons(dialog)] == ["Close"]


def test_control_with_pages_to_run_there_are_two_buttons(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _preview())

    assert sorted(b.text() for b in _buttons(dialog)) == ["Cancel", "Run 2 pages"]


# =============================================================================
# The actions: order, default, accept and reject, focus
# =============================================================================


def test_cancel_sits_left_of_the_primary(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview())
    assert dialog.run_button is not None

    assert dialog.cancel_button.geometry().x() < dialog.run_button.geometry().x()


def test_the_primary_is_the_default_primary_variant_and_enabled_over_budget(
    qtbot,  # type: ignore[no-untyped-def]
    host: QMainWindow,
) -> None:
    dialog = _opened(qtbot, host, _preview(spent="1.95", estimate="0.18", within_budget=False))
    assert dialog.run_button is not None

    assert dialog.run_button.isDefault()
    assert dialog.run_button.property("variant") == "primary"
    assert dialog.run_button.isEnabled(), "the over-budget sentence informs; it must not block"


def test_the_dialog_is_modal(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview())

    assert dialog.isModal()


def test_the_primary_accepts(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview())
    assert dialog.run_button is not None

    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS) as finished:
        QTest.mouseClick(dialog.run_button, Qt.MouseButton.LeftButton)

    assert finished.args == [QDialog.DialogCode.Accepted.value]


@pytest.mark.parametrize(
    "preview", [_preview(), _nothing_to_run()], ids=["cancel", "close-with-nothing-to-run"]
)
def test_the_secondary_rejects(qtbot, host: QMainWindow, preview: RerunPreview) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, preview)

    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS) as finished:
        QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)

    assert finished.args == [QDialog.DialogCode.Rejected.value]


def test_escape_rejects_the_dialog(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview())
    qtbot.waitUntil(lambda: QApplication.focusWidget() is dialog.run_button, timeout=FOCUS_MS)

    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS) as finished:
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)

    assert finished.args == [QDialog.DialogCode.Rejected.value]


def test_focus_starts_on_the_primary(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _preview())

    qtbot.waitUntil(lambda: QApplication.focusWidget() is dialog.run_button, timeout=FOCUS_MS)


def test_with_nothing_to_run_focus_starts_on_close(qtbot, host: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    dialog = _opened(qtbot, host, _nothing_to_run())

    qtbot.waitUntil(lambda: QApplication.focusWidget() is dialog.cancel_button, timeout=FOCUS_MS)
