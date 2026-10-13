"""MT-077 C-2: `ApiKeyDialog` and `ask_api_key`, what the first-run dialog is.

AC-1: a dialog asks for the Gemini API key, links to where one is obtained
(Google AI Studio), and has a Cancel. AC-5: its field masks the key. The rest
is C-2's mechanics - Ok disabled until something other than whitespace is
typed, `key()` stripping a paste's surrounding whitespace, `ask_api_key`
returning the key on Ok and `None` on Cancel.

**Oracle: mechanical, pinned exactly.** The title, the accessible name and the
link target are spelled out here, never read back from the module (C-2). The
explanatory wording is GREEN's (voice.md); only "review" is asserted.

**Driving `exec()`.** `ask_api_key` runs the dialog with `exec()`, which blocks
in a nested event loop. A zero-delay `QTimer.singleShot` fires inside that loop,
finds `QApplication.activeModalWidget()` and clicks the button. A second timer
is the hang guard: after `EXEC_GUARD_MS` it rejects every visible `QDialog`, so
a dialog the driver could not find fails the test instead of blocking the suite.

RED: `mangatl.ui.api_key_dialog` does not exist; each test imports it through
the `dialog_module` fixture, so the file collects and every test fails on the
import.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QLineEdit

TITLE = "Gemini API key"
ACCESSIBLE_NAME = "Gemini API key"
AI_STUDIO = "https://aistudio.google.com/apikey"
KEY = "AIzaSyD-not-a-real-key-0123456789wxyz"

#: Bounded waits. A local offscreen dialog opens and focuses in well under
#: 100 ms; these are liveness bounds, not cost estimates.
FOCUS_MS = 2_000
#: How long `exec()` may run before the guard rejects the dialog.
EXEC_GUARD_MS = 5_000


class _DialogModule:
    """`mangatl.ui.api_key_dialog`, imported on first attribute access - inside
    the test body, so in RED each test FAILS on the missing module rather than
    erroring in setup."""

    def __getattr__(self, name: str) -> Any:
        return getattr(importlib.import_module("mangatl.ui.api_key_dialog"), name)


@pytest.fixture
def dialog_module() -> ModuleType:
    return _DialogModule()  # type: ignore[return-value]


def _dialog(qtbot, dialog_module: ModuleType) -> Any:  # type: ignore[no-untyped-def]
    dialog = dialog_module.ApiKeyDialog()
    qtbot.addWidget(dialog)
    return dialog


def _ok(dialog: Any) -> Any:
    box = dialog.buttons
    assert isinstance(box, QDialogButtonBox)
    button = box.button(QDialogButtonBox.StandardButton.Ok)
    assert button is not None, "the dialog has no Ok button"
    return button


def _cancel(dialog: Any) -> Any:
    button = dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
    assert button is not None, "the dialog has no Cancel button (AC-1)"
    return button


# =============================================================================
# What the dialog is (AC-1, AC-5)
# =============================================================================


def test_the_dialog_is_titled_and_modal(qtbot, dialog_module: ModuleType) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, dialog_module)

    assert isinstance(dialog, QDialog)
    assert dialog.windowTitle() == TITLE
    assert dialog.isModal(), "C-2: the first-run dialog is modal"


def test_the_key_field_masks_what_is_typed(qtbot, dialog_module: ModuleType) -> None:  # type: ignore[no-untyped-def]
    """AC-5: the dialog never shows the key in full."""
    dialog = _dialog(qtbot, dialog_module)
    field = dialog.key_field

    assert isinstance(field, QLineEdit)
    assert field.echoMode() == QLineEdit.EchoMode.Password, (
        f"the key field echoes as {field.echoMode()}; AC-5 masks it (Password)"
    )
    assert field.accessibleName() == ACCESSIBLE_NAME


def test_the_dialog_links_to_google_ai_studio(qtbot, dialog_module: ModuleType) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, dialog_module)
    label = dialog.link_label

    assert dialog_module.AI_STUDIO_URL == AI_STUDIO
    assert isinstance(label, QLabel)
    assert f'href="{AI_STUDIO}"' in label.text(), (
        f"the link label says {label.text()!r}; AC-1 links to {AI_STUDIO}"
    )
    assert label.openExternalLinks() is True, "the link does not open in the browser"
    assert label.textFormat() == Qt.TextFormat.RichText


def test_the_buttons_are_exactly_ok_and_cancel(qtbot, dialog_module: ModuleType) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, dialog_module)
    box = dialog.buttons

    assert isinstance(box, QDialogButtonBox)
    assert box.standardButtons() == (
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )


def test_the_dialog_says_chapters_can_still_be_reviewed_without_a_key(
    qtbot,  # type: ignore[no-untyped-def]
    dialog_module: ModuleType,
) -> None:
    """AC-1: Cancel leaves the app runnable in review-only mode, and the dialog
    says so. The wording is GREEN's; only "review" is pinned."""
    dialog = _dialog(qtbot, dialog_module)
    texts = [label.text() for label in dialog.findChildren(QLabel)]

    assert any("review" in text.lower() for text in texts), (
        f"no label in the dialog mentions review: {texts}"
    )


def test_the_key_field_has_focus_when_the_dialog_opens(qtbot, dialog_module: ModuleType) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, dialog_module)

    with qtbot.waitExposed(dialog):
        dialog.open()
    qtbot.waitUntil(lambda: dialog.key_field.hasFocus(), timeout=FOCUS_MS)


def test_the_dialog_imports_nothing_from_mangatl_or_an_sdk(dialog_module: ModuleType) -> None:
    """C-2 / C-6: PySide6 only - no `mangatl.app`, no store, no compose, no SDK."""
    source = Path(dialog_module.__file__).read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)

    forbidden = [
        name
        for name in imported
        if name.split(".")[0] in {"mangatl", "anthropic", "google", "openai"}
    ]
    assert forbidden == [], f"mangatl.ui.api_key_dialog imports {forbidden}"
    assert any(name.startswith("PySide6") for name in imported), "precondition: the scan saw Qt"


# =============================================================================
# Ok is enabled only when a key has been typed
# =============================================================================


def test_ok_is_disabled_until_a_key_is_typed(qtbot, dialog_module: ModuleType) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, dialog_module)
    ok = _ok(dialog)

    assert not ok.isEnabled(), "Ok is enabled with an empty key field"

    QTest.keyClicks(dialog.key_field, "   ")
    assert not ok.isEnabled(), "Ok is enabled with only whitespace in the key field"

    QTest.keyClicks(dialog.key_field, "a")
    assert ok.isEnabled(), "Ok stays disabled after a key was typed"

    dialog.key_field.clear()
    assert not ok.isEnabled(), "Ok stays enabled after the field was cleared"

    assert _cancel(dialog).isEnabled(), "Cancel is always available"


def test_the_key_is_the_field_without_surrounding_whitespace(
    qtbot,  # type: ignore[no-untyped-def]
    dialog_module: ModuleType,
) -> None:
    dialog = _dialog(qtbot, dialog_module)
    dialog.key_field.setText(f"  {KEY[:10]} {KEY[10:]}   ")

    assert dialog.key() == f"{KEY[:10]} {KEY[10:]}", (
        "key() strips a paste's surrounding whitespace and touches nothing inside"
    )


# =============================================================================
# ask_api_key - exec() it, Ok is the key, Cancel is None
# =============================================================================


@pytest.fixture
def guards() -> Any:
    """Every hang-guard timer a test arms, stopped at teardown so a guard can
    never fire into a later test's dialog."""
    armed: list[QTimer] = []
    yield armed
    for timer in armed:
        timer.stop()


def _drive_exec(guards: list[QTimer], act: str, text: str = "") -> list[str]:
    """Arm the timers that answer the modal dialog `ask_api_key` is about to
    `exec()`. Returns a log of what the driver saw, for the assertion message."""
    seen: list[str] = []

    def answer() -> None:
        dialog = QApplication.activeModalWidget()
        seen.append(type(dialog).__name__)
        if dialog is None:
            return
        field = dialog.findChild(QLineEdit)
        box = dialog.findChild(QDialogButtonBox)
        if field is None or box is None:
            return
        field.setText(text)
        which = (
            QDialogButtonBox.StandardButton.Ok
            if act == "ok"
            else QDialogButtonBox.StandardButton.Cancel
        )
        button = box.button(which)
        if button is not None:
            button.click()

    def guard() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                seen.append(f"guard rejected {type(widget).__name__}")
                widget.reject()

    for delay, slot in ((0, answer), (EXEC_GUARD_MS, guard)):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(slot)
        timer.start(delay)
        guards.append(timer)
    return seen


def test_ask_returns_the_typed_key_when_ok_is_pressed(
    qtbot,  # type: ignore[no-untyped-def]
    dialog_module: ModuleType,
    guards: list[QTimer],
) -> None:
    seen = _drive_exec(guards, "ok", f"  {KEY} ")

    result = dialog_module.ask_api_key()

    assert result == KEY, f"ask_api_key returned {result!r} (driver saw {seen})"
    assert seen[0] == "ApiKeyDialog", f"the modal dialog exec()'d was {seen}"


def test_ask_returns_none_when_cancel_is_pressed(
    qtbot,  # type: ignore[no-untyped-def]
    dialog_module: ModuleType,
    guards: list[QTimer],
) -> None:
    """AC-1: Cancel - even with something typed - is no key."""
    seen = _drive_exec(guards, "cancel", KEY)

    result = dialog_module.ask_api_key()

    assert result is None, f"ask_api_key returned {result!r} on Cancel (driver saw {seen})"
    assert seen[0] == "ApiKeyDialog", f"the modal dialog exec()'d was {seen}"


def test_the_module_exports_exactly_the_three_names(dialog_module: ModuleType) -> None:
    assert sorted(dialog_module.__all__) == ["AI_STUDIO_URL", "ApiKeyDialog", "ask_api_key"]
