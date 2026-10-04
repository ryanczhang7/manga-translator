"""`BakeConfirmDialog`: what a render will do, stated before it runs (MT-066 C-2).

`components.md` §7 and §9. The dialog only presents: it is built from a
`BakePreview` value, reads no project and starts nothing. Confirm accepts it;
Cancel and `Esc` reject it. Unreviewed lines are stated, never enforced - the
primary action renders regardless (§7, AC-2).

voice.md: the interface says *render*, never *bake*. Every label is plain text
(a folder named `<b>` is not markup) and word-wraps. The failed and overflow
statements always exist and are hidden when their count is zero.

The dialog is modal and opened with `open()`, never `exec()`. Focus starts on
the primary action and Tab stays inside it; returning focus to the invoking
control on close is the caller's job (the workspace does it on `finished`).
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from mangatl.pipeline.bake import BakePreview, LineRef
from mangatl.ui.labels import plain_label

__all__ = ["BakeConfirmDialog"]

TITLE = "Render pages"


def _pages(refs: Sequence[LineRef]) -> str:
    """`page 3` or `pages 1, 3, 10`: the distinct 1-based pages, ascending."""
    numbers = sorted({ref.page_ordinal + 1 for ref in refs})
    prefix = "page" if len(numbers) == 1 else "pages"
    return f"{prefix} {', '.join(str(n) for n in numbers)}"


def _unreviewed_text(preview: BakePreview) -> str:
    total, count = preview.total_lines, len(preview.unreviewed)
    if total == 0:
        return "No lines were found on any page."
    if count == 0:
        return f"All {total} lines were reviewed."
    verb = "was" if count == 1 else "were"
    pages = _pages(preview.unreviewed)
    return f"{count} of {total} lines {verb} never reviewed ({pages}). Render anyway?"


def _failed_text(refs: Sequence[LineRef]) -> str:
    noun = "line" if len(refs) == 1 else "lines"
    return f"{len(refs)} {noun} could not be translated and will be left empty ({_pages(refs)})."


def _overflow_text(refs: Sequence[LineRef]) -> str:
    if len(refs) == 1:
        return f"1 line does not fit its bubble and will be cut off ({_pages(refs)})."
    return f"{len(refs)} lines do not fit their bubble and will be cut off ({_pages(refs)})."


class BakeConfirmDialog(QDialog):
    """The Render dialog: the output folder, the counts, and Render / Cancel."""

    def __init__(self, preview: BakePreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setAccessibleName(TITLE)
        self.setModal(True)

        folder = plain_label("bakeOutputFolder", str(preview.output_dir))
        # A path is copied as often as read: selectable by keyboard too, which
        # makes the label a focus stop, unlike `plain_label`'s default.
        folder.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        folder.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        unreviewed = plain_label("bakeUnreviewed", _unreviewed_text(preview))
        failed = plain_label("bakeFailed", _failed_text(preview.failed))
        overflow = plain_label("bakeOverflow", _overflow_text(preview.overflowing))
        failed.setVisible(bool(preview.failed))
        overflow.setVisible(bool(preview.overflowing))

        pages = preview.page_count
        self.confirm_button = QPushButton(f"Render {pages} page" + ("" if pages == 1 else "s"))
        self.confirm_button.setObjectName("bakeConfirm")
        self.confirm_button.setProperty("variant", "primary")
        self.confirm_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("bakeCancel")
        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.confirm_button)
        layout = QVBoxLayout(self)
        statements: list[QLabel] = [folder, unreviewed]
        statements += [label for label in (failed, overflow) if not label.isHidden()]
        for label in (folder, unreviewed, failed, overflow):
            layout.addWidget(label)
        layout.addLayout(buttons)

        # The whole statement, read when the dialog opens (§9).
        self.setAccessibleDescription("\n".join(label.text() for label in statements))
        self.confirm_button.setFocus(Qt.FocusReason.OtherFocusReason)
