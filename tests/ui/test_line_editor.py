"""MT-017 C-7 and C-9: `LineEditor`, the status machine a user drives with keys.

Driven with real key events (`QTest.keyClick`) on a real, focused editor, and
checked cell by cell against C-7's transition table. `save` is a recording
stand-in here - the editor's contract with its caller is a function of
`(final_en, status)` - and the real `commit_line` behind it is exercised in
`test_line_review_workspace.py`, where the project is real.

**"Exactly" means `==` on `str`** (AC-2, C-7). The proposals used below differ
from their own O2-normalised form - an NFD accent, a double space, a trailing
space - so an editor that normalised on revert, on commit or on the "equals the
proposal" test would be caught. AC-2 asserts `status == "reverted"`, never
`!= "proposed"`.

**Offscreen mechanics, measured in RED against a plain `QLineEdit`** (the
negative controls for the key and paste tests - each is behaviour a plain
field gets WRONG, so none of these tests can pass on an unmodified QLineEdit):

- `Ctrl+V`, `Shift+Insert` and `insert()` keep `\\n`, `\\r\\n`, U+2028, U+0085
  and `\\v` verbatim ("a \\n b" -> "a \\n b");
- `Shift+Return` and `Ctrl+Return` both emit `returnPressed`, so modifiers must
  be told apart by the editor itself;
- `Esc` and `Ctrl+R` change nothing.

**Timing.** Every test here is synchronous except the three that pin C-7's
save timer (AC-1's 500 ms), which wait real time: at most ~0.8 s each when the
implementation is right. `SLACK_MS` is event-loop scheduling slack, named and
not tuned. No `pytest-timeout` exists in this project; the waits carry their
own explicit timeouts.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from mangatl.domain.line import Line
from mangatl.ui.line_editor import SAVE_DEBOUNCE_MS, LineEditor

# --- Settled numbers ------------------------------------------------------------
DESIGN_SAVE_BOUND_MS = 500  # AC-1 / components.md §6 "debounced 500ms" - a literal
SLACK_MS = 250  # event-loop scheduling slack, named (story Contract, oracle table)

# --- Fixture text -------------------------------------------------------------
#: A proposal whose O2 form is not itself: NFD accent, double space, trailing space.
P = "Cafe\u0301  au lait "
EDITED = "Coffee, please."

NO = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def _line(
    status: str = "proposed",
    *,
    proposed_en: str | None = P,
    final_en: str | None = None,
    ocr_empty: bool = False,
) -> Line:
    return Line(
        reading_index=0,
        source_ja="カフェオレ",
        proposed_en=proposed_en,
        final_en=final_en,
        status=status,  # type: ignore[arg-type]
        edited_at=None,
        ocr_empty=ocr_empty,
    )


@dataclass
class _Save:
    """A `SaveFn` that records each successful call, and raises `fail` if set."""

    calls: list[tuple[str | None, str]] = field(default_factory=list)
    attempts: int = 0
    fail: Exception | None = None

    def __call__(self, final_en: str | None, status: str) -> None:
        self.attempts += 1
        if self.fail is not None:
            raise self.fail
        self.calls.append((final_en, status))


@dataclass
class _Rig:
    host: QWidget  # held: pytest-qt keeps only a weak reference, and Qt deletes children
    editor: LineEditor
    other: QLineEdit
    save: _Save
    statuses: list[str]
    failures: list[str]
    successes: list[None]


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


@pytest.fixture(autouse=True)
def _clean_clipboard() -> Iterator[None]:
    yield
    QGuiApplication.clipboard().clear()


def _rig(qtbot, line: Line, save: _Save | None = None, *, no_save: bool = False) -> _Rig:  # type: ignore[no-untyped-def]
    """The editor in a shown, active window, focused - so editing has begun and
    the edit-start value is the line's effective text. `other` is somewhere to
    move focus to."""
    recorder = save if save is not None else _Save()
    host = QWidget()
    editor = LineEditor(line, None if no_save else recorder, host)
    other = QLineEdit(host)
    layout = QVBoxLayout(host)
    layout.addWidget(editor)
    layout.addWidget(other)
    qtbot.addWidget(host)
    with qtbot.waitExposed(host):
        host.show()
    host.activateWindow()
    qtbot.waitUntil(host.isActiveWindow)
    editor.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(editor.hasFocus)
    _settle()
    rig = _Rig(host, editor, other, recorder, [], [], [])
    editor.statusChanged.connect(rig.statuses.append)
    editor.saveFailed.connect(rig.failures.append)
    editor.saveSucceeded.connect(lambda: rig.successes.append(None))
    return rig


def _key(rig: _Rig, key: Qt.Key, modifiers: Qt.KeyboardModifier = NO) -> None:
    QTest.keyClick(rig.editor, key, modifiers)
    _settle()


def _type(rig: _Rig, text: str) -> None:
    """Replace the field's content by typing, as a user would."""
    rig.editor.selectAll()
    QTest.keyClicks(rig.editor, text)
    _settle()


def _commit(rig: _Rig, text: str) -> None:
    _type(rig, text)
    _key(rig, Qt.Key.Key_Return)


# =============================================================================
# Starting state
# =============================================================================


@pytest.mark.parametrize(
    ("line", "shown"),
    [
        pytest.param(_line("proposed"), P, id="proposed-shows-the-proposal"),
        pytest.param(_line("accepted"), P, id="accepted-shows-the-proposal"),
        pytest.param(_line("edited", final_en=EDITED), EDITED, id="edited-shows-the-edit"),
        pytest.param(_line("edited", final_en=""), "", id="a-deleted-line-shows-empty"),
        pytest.param(_line("failed", proposed_en=None, ocr_empty=True), "", id="failed-empty"),
    ],
)
def test_the_editor_starts_with_the_lines_effective_text_and_status(
    qtbot,  # type: ignore[no-untyped-def]
    line: Line,
    shown: str,
) -> None:
    rig = _rig(qtbot, line)
    assert rig.editor.text() == shown
    assert rig.editor.status == line.status
    assert rig.editor.line == line


@pytest.mark.parametrize("status", ["proposed", "accepted", "edited", "reverted", "failed"])
def test_the_editor_is_editable_whatever_the_status(
    qtbot,  # type: ignore[no-untyped-def]
    status: str,
) -> None:
    """MT-016 PO-1 is superseded; a failed line is editable too (PO-5)."""
    rig = _rig(qtbot, _line(status))
    assert isinstance(rig.editor, QLineEdit)
    assert not rig.editor.isReadOnly()


# =============================================================================
# Enter (C-7 rows 1-4; AC-1)
# =============================================================================


def test_enter_with_the_field_unchanged_commits_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    _key(rig, Qt.Key.Key_Return)
    rig.editor.flush()

    assert (rig.editor.status, rig.editor.text()) == ("proposed", P)
    assert rig.statuses == []
    assert rig.save.calls == []


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["Return", "Enter"])
def test_typing_and_pressing_enter_on_a_proposed_line_makes_it_edited_and_saves_the_text(
    qtbot,  # type: ignore[no-untyped-def]
    key: Qt.Key,
) -> None:
    """AC-1's status half; the on-disk half is in the workspace suite."""
    rig = _rig(qtbot, _line("proposed"))
    _type(rig, EDITED)
    _key(rig, key)

    assert rig.editor.status == "edited"
    assert rig.statuses == ["edited"]
    assert rig.editor.text() == EDITED
    assert (rig.editor.line.final_en, rig.editor.line.status) == (EDITED, "edited")
    rig.editor.flush()
    assert rig.save.calls == [(EDITED, "edited")]


def test_typing_into_a_failed_line_with_no_proposal_makes_it_edited(qtbot) -> None:  # type: ignore[no-untyped-def]
    """PO-5: the user's own English in a bubble the model could not read."""
    rig = _rig(qtbot, _line("failed", proposed_en=None, ocr_empty=True))
    _commit(rig, "Hmph.")
    rig.editor.flush()

    assert rig.editor.status == "edited"
    assert rig.save.calls == [("Hmph.", "edited")]


def test_retyping_the_proposal_exactly_on_an_edited_line_makes_it_reverted(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("edited", final_en=EDITED))
    rig.editor.selectAll()
    rig.editor.insert(P)  # NFD combining mark: inserted, not key-clicked
    _settle()
    assert rig.editor.text() == P, "fixture: the field holds the proposal exactly"
    _key(rig, Qt.Key.Key_Return)
    rig.editor.flush()

    assert rig.editor.status == "reverted"
    assert rig.save.calls == [(P, "reverted")]


@pytest.mark.parametrize(
    "near",
    [
        pytest.param("Cafe\u0301 au lait", id="whitespace-differs"),
        pytest.param("Caf\u00e9  au lait ", id="nfc-differs"),
        pytest.param("Caf\u00e9 au lait", id="both-differ"),
    ],
)
def test_retyping_the_proposal_only_up_to_whitespace_or_nfc_stays_edited(
    qtbot,  # type: ignore[no-untyped-def]
    near: str,
) -> None:
    """C-7: "exactly" is `==`, not O2. `normalise(T) == normalise(P)` here, but
    `T != P`, so this is an edit, not a revert."""
    rig = _rig(qtbot, _line("edited", final_en=EDITED))
    rig.editor.selectAll()
    rig.editor.insert(near)
    _settle()
    _key(rig, Qt.Key.Key_Return)
    rig.editor.flush()

    assert rig.editor.status == "edited"
    assert rig.save.calls == [(near, "edited")]


@pytest.mark.parametrize("status", ["proposed", "accepted"])
def test_typing_and_then_retyping_the_proposal_on_an_unedited_line_commits_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    status: str,
) -> None:
    rig = _rig(qtbot, _line(status))
    _type(rig, "scratch")
    rig.editor.selectAll()
    rig.editor.insert(P)
    _settle()
    _key(rig, Qt.Key.Key_Return)
    rig.editor.flush()

    assert rig.editor.status == status
    assert rig.statuses == []
    assert rig.save.calls == []


def test_emphasis_markers_are_committed_as_literal_text(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    _commit(rig, "*Really* **now**")
    rig.editor.flush()

    assert rig.editor.text() == "*Really* **now**"
    assert rig.save.calls == [("*Really* **now**", "edited")]


# =============================================================================
# Ctrl+R / Revert (C-7 rows 5-6; AC-2)
# =============================================================================


def test_ctrl_r_on_an_edited_line_restores_the_proposal_exactly_and_marks_it_reverted(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-2: the field is `== P` character for character - the NFD accent, the
    double space and the trailing space all intact - and the status is
    `reverted`, not `proposed`."""
    rig = _rig(qtbot, _line("edited", final_en=EDITED))
    _key(rig, Qt.Key.Key_R, CTRL)

    assert rig.editor.text() == P
    assert rig.editor.status == "reverted"
    assert rig.statuses == ["reverted"]
    assert (rig.editor.line.final_en, rig.editor.line.status) == (P, "reverted")
    rig.editor.flush()
    assert rig.save.calls == [(P, "reverted")]


def test_editing_then_reverting_by_keyboard_ends_reverted_and_saves_only_the_latest(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """The whole AC-2 walk from a proposed line; one pending save carries the
    latest committed state (C-7)."""
    rig = _rig(qtbot, _line("proposed"))
    _commit(rig, EDITED)
    _key(rig, Qt.Key.Key_R, CTRL)
    rig.editor.flush()

    assert rig.editor.text() == P
    assert rig.statuses == ["edited", "reverted"]
    assert rig.save.calls == [(P, "reverted")]


def test_the_revert_control_is_the_same_act_as_ctrl_r(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("edited", final_en=EDITED))
    rig.editor.revert()
    rig.editor.flush()

    assert (rig.editor.text(), rig.editor.status) == (P, "reverted")
    assert rig.save.calls == [(P, "reverted")]


def test_ctrl_r_on_a_dirty_unedited_line_restores_the_proposal_and_keeps_the_status(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    rig = _rig(qtbot, _line("proposed"))
    _type(rig, "scratch")
    _key(rig, Qt.Key.Key_R, CTRL)
    rig.editor.flush()

    assert (rig.editor.text(), rig.editor.status) == (P, "proposed")
    assert rig.statuses == []
    assert rig.save.calls == []


@pytest.mark.parametrize("status", ["proposed", "accepted", "reverted"])
def test_ctrl_r_on_a_clean_line_that_is_not_edited_does_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    status: str,
) -> None:
    line = _line(status, final_en=P if status == "reverted" else None)
    rig = _rig(qtbot, line)
    _key(rig, Qt.Key.Key_R, CTRL)
    rig.editor.flush()

    assert (rig.editor.text(), rig.editor.status) == (P, status)
    assert rig.save.calls == []


def test_ctrl_r_on_an_edited_line_with_no_proposal_does_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    """PO-5: there is no proposal to revert to."""
    rig = _rig(qtbot, _line("edited", proposed_en=None, final_en="Mine."))
    _key(rig, Qt.Key.Key_R, CTRL)
    rig.editor.flush()

    assert (rig.editor.text(), rig.editor.status) == ("Mine.", "edited")
    assert rig.save.calls == []


# =============================================================================
# Ctrl+Enter / Accept (C-7 rows 7-9; AC-4)
# =============================================================================


def test_ctrl_enter_on_a_clean_proposed_line_accepts_it_with_the_text_unchanged(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-4. `accepted` keeps `final_en` NULL: the text did not change."""
    rig = _rig(qtbot, _line("proposed"))
    _key(rig, Qt.Key.Key_Return, CTRL)

    assert rig.editor.text() == P
    assert rig.editor.status == "accepted"
    assert rig.statuses == ["accepted"]
    assert (rig.editor.line.final_en, rig.editor.line.status) == (None, "accepted")
    rig.editor.flush()
    assert rig.save.calls == [(None, "accepted")]


def test_the_accept_control_is_the_same_act_as_ctrl_enter(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    rig.editor.accept_line()
    rig.editor.flush()

    assert (rig.editor.text(), rig.editor.status) == (P, "accepted")
    assert rig.save.calls == [(None, "accepted")]


def test_ctrl_enter_on_a_dirty_field_commits_it_as_enter_would(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    _type(rig, EDITED)
    _key(rig, Qt.Key.Key_Return, CTRL)
    rig.editor.flush()

    assert rig.editor.status == "edited"
    assert rig.save.calls == [(EDITED, "edited")]


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(_line("accepted"), id="accepted"),
        pytest.param(_line("edited", final_en=EDITED), id="edited"),
        pytest.param(_line("reverted", final_en=P), id="reverted"),
        pytest.param(_line("failed", proposed_en=None, ocr_empty=True), id="failed"),
    ],
)
def test_ctrl_enter_on_a_clean_line_that_is_not_proposed_does_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    line: Line,
) -> None:
    rig = _rig(qtbot, line)
    before = rig.editor.text()
    _key(rig, Qt.Key.Key_Return, CTRL)
    rig.editor.flush()

    assert (rig.editor.text(), rig.editor.status) == (before, line.status)
    assert rig.save.calls == []


# =============================================================================
# Esc (C-7 row 10; AC-3)
# =============================================================================


def test_escape_restores_the_value_at_edit_start_on_a_proposed_line(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    _type(rig, "half-typed thought")
    _key(rig, Qt.Key.Key_Escape)
    rig.editor.flush()

    assert (rig.editor.text(), rig.editor.status) == (P, "proposed")
    assert rig.statuses == []
    assert rig.save.calls == []


def test_escape_restores_the_edit_start_value_not_the_proposal_on_an_edited_line(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    rig = _rig(qtbot, _line("edited", final_en=EDITED))
    _type(rig, "something else")
    _key(rig, Qt.Key.Key_Escape)
    rig.editor.flush()

    assert (rig.editor.text(), rig.editor.status) == (EDITED, "edited")
    assert rig.save.calls == []


# =============================================================================
# Focus out (C-7 row 11)
# =============================================================================


def test_leaving_a_dirty_field_commits_it_as_enter_would(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    _type(rig, EDITED)
    rig.other.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(rig.other.hasFocus)
    _settle()
    rig.editor.flush()

    assert rig.editor.status == "edited"
    assert rig.save.calls == [(EDITED, "edited")]


def test_leaving_a_clean_field_commits_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    rig.other.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(rig.other.hasFocus)
    _settle()
    rig.editor.flush()

    assert rig.editor.status == "proposed"
    assert rig.save.calls == []


# =============================================================================
# One logical line (C-7 row 12, C-9; AC-5)
# =============================================================================


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["Return", "Enter"])
def test_shift_enter_inserts_no_break_commits_nothing_and_keeps_the_typing(
    qtbot,  # type: ignore[no-untyped-def]
    key: Qt.Key,
) -> None:
    rig = _rig(qtbot, _line("proposed"))
    _type(rig, "still typing")
    _key(rig, key, SHIFT)
    rig.editor.flush()

    assert rig.editor.text() == "still typing"
    assert rig.editor.status == "proposed"
    assert rig.statuses == []
    assert rig.save.calls == []


@pytest.mark.parametrize(
    ("pasted", "expected"),
    [
        pytest.param("a \n b", "a   b", id="spaces-beside-the-break-are-kept"),
        pytest.param("a\r\n\r\nb", "a b", id="a-run-of-breaks-is-one-space"),
        pytest.param("one\ntwo\nthree", "one two three", id="each-run-separately"),
        pytest.param("\nlead and trail\n", " lead and trail ", id="edges-are-not-stripped"),
    ],
)
@pytest.mark.parametrize(
    "chord",
    [
        pytest.param((Qt.Key.Key_V, CTRL), id="Ctrl+V"),
        pytest.param((Qt.Key.Key_Insert, SHIFT), id="Shift+Insert"),
    ],
)
def test_pasted_line_breaks_collapse_to_a_single_space_per_run(
    qtbot,  # type: ignore[no-untyped-def]
    pasted: str,
    expected: str,
    chord: tuple[Qt.Key, Qt.KeyboardModifier],
) -> None:
    rig = _rig(qtbot, _line("proposed"))
    rig.editor.clear()
    QGuiApplication.clipboard().setText(pasted)
    _key(rig, *chord)

    assert rig.editor.text() == expected


@pytest.mark.parametrize(
    "brk",
    ["\r", "\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
    ids=lambda c: f"U+{ord(c):04X}",
)
def test_every_line_break_character_inserted_becomes_one_space(
    qtbot,  # type: ignore[no-untyped-def]
    brk: str,
) -> None:
    rig = _rig(qtbot, _line("proposed"))
    rig.editor.clear()
    rig.editor.insert(f"a{brk}b{brk}{brk}c")

    assert rig.editor.text() == "a b c"


def test_a_mixed_run_of_break_characters_is_one_space_and_other_whitespace_is_kept(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """C-9: only line breaks collapse; a tab and U+3000 are left as pasted (the
    editor does not normalise - that is O2's job at measurement)."""
    rig = _rig(qtbot, _line("proposed"))
    rig.editor.clear()
    rig.editor.insert("a\r\n\u2029\x85b\t\u3000c")

    assert rig.editor.text() == "a b\t\u3000c"


def test_a_pasted_multi_line_text_commits_as_one_line(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    rig.editor.clear()
    QGuiApplication.clipboard().setText("first\nsecond")
    _key(rig, Qt.Key.Key_V, CTRL)
    _key(rig, Qt.Key.Key_Return)
    rig.editor.flush()

    assert rig.save.calls == [("first second", "edited")]


# =============================================================================
# Saving: AC-1's bound (C-7 "Saving")
# =============================================================================


def test_the_save_bound_is_no_more_than_the_500_ms_the_design_settles() -> None:
    """Against the literal, never against the constant read back."""
    assert SAVE_DEBOUNCE_MS <= DESIGN_SAVE_BOUND_MS


def test_a_commit_is_saved_without_any_flush_within_the_bound_plus_slack(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    rig = _rig(qtbot, _line("proposed"))
    _type(rig, EDITED)
    QTest.keyClick(rig.editor, Qt.Key.Key_Return)
    committed = time.monotonic()

    qtbot.waitUntil(lambda: rig.save.calls != [], timeout=4 * (DESIGN_SAVE_BOUND_MS + SLACK_MS))
    elapsed_ms = (time.monotonic() - committed) * 1000

    assert rig.save.calls == [(EDITED, "edited")]
    assert elapsed_ms <= DESIGN_SAVE_BOUND_MS + SLACK_MS, f"saved {elapsed_ms:.0f} ms after Enter"


def test_a_second_commit_does_not_restart_the_save_timer(qtbot) -> None:  # type: ignore[no-untyped-def]
    """C-7: an upper bound on data loss, not a debounce a fast typist can
    postpone forever. The first commit starts the timer; a second one 300 ms
    later is carried by the same firing, still within the first commit's
    bound. A restarting debounce would fire at ~800 ms."""
    rig = _rig(qtbot, _line("proposed"))
    _type(rig, "first")
    QTest.keyClick(rig.editor, Qt.Key.Key_Return)
    first_commit = time.monotonic()
    qtbot.wait(300)
    _commit(rig, "second")

    qtbot.waitUntil(lambda: rig.save.calls != [], timeout=4 * (DESIGN_SAVE_BOUND_MS + SLACK_MS))
    elapsed_ms = (time.monotonic() - first_commit) * 1000

    assert rig.save.calls == [("second", "edited")], "the timer's firing carries the latest commit"
    assert elapsed_ms <= DESIGN_SAVE_BOUND_MS + SLACK_MS, (
        f"saved {elapsed_ms:.0f} ms after the FIRST commit: the timer was restarted"
    )


def test_flush_writes_the_pending_save_at_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    _commit(rig, EDITED)
    assert rig.save.calls == [], "C-7: a commit starts the timer; it does not save inline"
    rig.editor.flush()

    assert rig.save.calls == [(EDITED, "edited")]


def test_flush_with_nothing_committed_writes_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    rig = _rig(qtbot, _line("proposed"))
    rig.editor.flush()

    assert rig.save.attempts == 0


def test_an_editor_with_no_project_behind_it_commits_as_a_silent_success(qtbot) -> None:  # type: ignore[no-untyped-def]
    """`save is None` (a row MT-016's three-argument `set_rows` built)."""
    rig = _rig(qtbot, _line("proposed"), no_save=True)
    _commit(rig, EDITED)
    rig.editor.flush()

    assert rig.editor.status == "edited"
    assert rig.failures == []
    assert not rig.editor.property("saveError")


# =============================================================================
# A failed save (AC-7)
# =============================================================================


def test_a_failed_save_keeps_the_typing_in_the_field_and_reports_the_reason(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    save = _Save(fail=OSError("disk is full"))
    rig = _rig(qtbot, _line("proposed"), save)
    _commit(rig, "My own words")
    rig.editor.flush()

    assert rig.editor.text() == "My own words"
    assert rig.failures == ["Not saved: disk is full"]
    assert rig.editor.property("saveError") is True
    assert rig.editor.status == "edited", "the in-memory status is the committed one"


def test_a_failed_save_stays_pending_and_the_next_flush_retries_and_clears_it(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    save = _Save(fail=OSError("disk is full"))
    rig = _rig(qtbot, _line("proposed"), save)
    _commit(rig, "My own words")
    rig.editor.flush()
    assert save.calls == []

    save.fail = None
    rig.editor.flush()

    assert save.calls == [("My own words", "edited")]
    assert not rig.editor.property("saveError")
    assert rig.successes == [None]
    assert rig.editor.text() == "My own words"


def test_a_save_that_fails_on_the_timer_also_keeps_the_text(qtbot) -> None:  # type: ignore[no-untyped-def]
    save = _Save(fail=PermissionError("project file is read-only"))
    rig = _rig(qtbot, _line("proposed"), save)
    _type(rig, "Typed before the failure")
    with qtbot.waitSignal(rig.editor.saveFailed, timeout=4 * (DESIGN_SAVE_BOUND_MS + SLACK_MS)):
        QTest.keyClick(rig.editor, Qt.Key.Key_Return)

    assert rig.editor.text() == "Typed before the failure"
    assert rig.failures == ["Not saved: project file is read-only"]
    assert rig.editor.property("saveError") is True
