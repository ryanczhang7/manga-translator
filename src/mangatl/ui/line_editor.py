"""The line editor: one logical line of English, and the status machine a user
drives with keys (MT-017 C-7, C-9).

**Keys** (`components.md` §6): `Enter` commits, `Esc` restores the value the
field had when editing began, `Ctrl+R` reverts to the machine proposal,
`Ctrl+Enter` accepts the line without editing, and `Shift+Enter` does nothing.
A plain `QLineEdit` emits `returnPressed` for `Shift+Return` and `Ctrl+Return`
alike, so the editor reads the modifiers itself and never lets the base class
see a Return or an Enter.

**"Exactly" is `==` on `str`.** Nothing here calls `normalise`: whether a
committed text equals the proposal decides `reverted` against `edited`, and AC-2
asks for the proposal back character for character. O2's normalisation is for
measuring (MT-022), never for editing.

**Saving is an upper bound on data loss, not a debounce.** A commit updates the
in-memory line at once and starts a single-shot `SAVE_DEBOUNCE_MS` timer if one
is not already running; a later commit rides the same firing and never restarts
it, so a fast typist cannot postpone the write forever. The firing - or
`flush()` - hands the *latest* committed `(final_en, status)` to `save`. A save
that raises keeps the text in the field, says why, and stays pending for the
next commit or flush to retry (AC-7).

**One logical line** (AC-5, C-9) is a validator: whatever inserts the text -
typing, `Ctrl+V`, `Shift+Insert`, the context menu, a drop, `insert()`,
`setText()` - passes through `validate`, which replaces every run of line-break
characters with one space and leaves every other character as it came.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QValidator
from PySide6.QtWidgets import QLineEdit, QWidget

from mangatl.domain.line import Line, LineStatus, effective_text

__all__ = ["SAVE_DEBOUNCE_MS", "LineEditor", "SaveFn"]

#: AC-1: a commit is in the project file within this many milliseconds.
SAVE_DEBOUNCE_MS: int = 500

#: `(final_en, status)` -> None; raises on failure. `final_en` is `None` for an
#: accept, whose text is the proposal's.
SaveFn = Callable[[str | None, LineStatus], None]

#: C-9's line-break characters - `str.splitlines`'s set - as maximal runs.
_BREAKS = re.compile("[\r\n\v\f\x1c\x1d\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]+")

_RETURN_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)

#: The modifiers that decide what a key means. `KeypadModifier` is not one: the
#: keypad's Enter is Enter.
_MEANINGFUL = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier


class _OneLogicalLine(QValidator):
    """Rewrites every run of line breaks to one space; never rejects."""

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        collapsed = _BREAKS.sub(" ", text)
        if collapsed != text:
            pos = len(_BREAKS.sub(" ", text[:pos]))
        return QValidator.State.Acceptable, collapsed, pos


class LineEditor(QLineEdit):
    """One line under review. Always editable, whatever its status (PO-5)."""

    #: The line's status after a commit (emitted on every commit, so a listener
    #: can re-read `line` for its text as well).
    statusChanged = Signal(str)
    #: A save raised; the argument is the reason as shown, `"Not saved: ..."`.
    saveFailed = Signal(str)
    #: A save reached `save` and returned.
    saveSucceeded = Signal()

    def __init__(self, line: Line, save: SaveFn | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line = line
        self._save = save
        self._pending: tuple[str | None, LineStatus] | None = None
        self.setValidator(_OneLogicalLine(self))
        self.setText(effective_text(line))
        self._edit_start = self.text()
        self.setProperty("saveError", False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(SAVE_DEBOUNCE_MS)
        self._timer.timeout.connect(self.flush)

    @property
    def status(self) -> LineStatus:
        return self._line.status

    @property
    def line(self) -> Line:
        """The in-memory state after the last commit."""
        return self._line

    # -- the acts ----------------------------------------------------------------

    def revert(self) -> None:
        """`Ctrl+R` and the Revert control (C-7 rows 5-6)."""
        proposal = self._line.proposed_en
        if proposal is None:
            return
        if self._line.status == "edited":
            self.setText(proposal)
            self._commit(proposal, "reverted")
        elif self._dirty():
            self.setText(proposal)

    def accept_line(self) -> None:
        """`Ctrl+Enter` and the Accept control (C-7 rows 7-9)."""
        if self._dirty():
            self._commit_typed()
        elif self._line.status == "proposed":
            self._commit(None, "accepted")

    def flush(self) -> None:
        """Write any pending save now, synchronously, and stop the timer."""
        self._timer.stop()
        if self._pending is None:
            return
        if self._save is not None:
            try:
                self._save(*self._pending)
            except Exception as exc:
                self._set_save_error(True)
                self.saveFailed.emit(f"Not saved: {exc}")
                return
        self._pending = None
        self._set_save_error(False)
        self.saveSucceeded.emit()

    # -- events ------------------------------------------------------------------

    def event(self, event: QEvent) -> bool:
        # Claim the editor's own chords before any window shortcut can.
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and self._is_own_chord(event)
        ):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers() & _MEANINGFUL
        if key in _RETURN_KEYS:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                pass  # AC-5: no line break, and no commit
            elif modifiers & Qt.KeyboardModifier.ControlModifier:
                self.accept_line()
            else:
                self._commit_typed()
            event.accept()
        elif key == Qt.Key.Key_Escape and not modifiers:
            self.setText(self._edit_start)
            event.accept()
        elif key == Qt.Key.Key_R and modifiers == Qt.KeyboardModifier.ControlModifier:
            self.revert()
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        # Editing begins. A context menu closing hands focus back mid-edit: the
        # edit that began before it is still the one in progress.
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self._edit_start = self.text()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        # A context menu opening (to paste, say) is not leaving the field.
        if event.reason() != Qt.FocusReason.PopupFocusReason and self._dirty():
            self._commit_typed()
        super().focusOutEvent(event)

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _is_own_chord(event: QKeyEvent) -> bool:
        modifiers = event.modifiers() & _MEANINGFUL
        key = event.key()
        return (
            key in _RETURN_KEYS
            or (key == Qt.Key.Key_Escape and not modifiers)
            or (key == Qt.Key.Key_R and modifiers == Qt.KeyboardModifier.ControlModifier)
        )

    def _dirty(self) -> bool:
        return self.text() != self._edit_start

    def _commit_typed(self) -> None:
        """`Enter` (C-7 rows 1-4); also a dirty `Ctrl+Enter` and a dirty focus-out."""
        typed = self.text()
        if typed == self._edit_start:
            return
        proposal = self._line.proposed_en
        if typed != proposal:
            self._commit(typed, "edited")
        elif self._line.status in ("edited", "reverted"):
            self._commit(typed, "reverted")

    def _commit(self, final_en: str | None, status: LineStatus) -> None:
        self._line = replace(
            self._line, final_en=final_en, status=status, edited_at=datetime.now(UTC)
        )
        self._edit_start = self.text()
        self._pending = (final_en, status)
        if not self._timer.isActive():
            self._timer.start()
        self.statusChanged.emit(status)

    def _set_save_error(self, failed: bool) -> None:
        if bool(self.property("saveError")) == failed:
            return
        self.setProperty("saveError", failed)
        self.style().unpolish(self)
        self.style().polish(self)
