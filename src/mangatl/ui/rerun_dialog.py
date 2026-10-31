"""`RerunDialog`: what "Run again" will do, stated before it runs (MT-125 C-2).

`components.md` §9. The dialog only presents, as `BakeConfirmDialog` does: it
is built from a `RerunPreview` value (MT-124), reads no project and starts
nothing. The primary accepts it; Cancel and `Esc` reject it. The budget line
informs and never blocks - the primary stays enabled over budget, as "Start
run anyway" does (MT-059).

voice.md: the interface says *run*. Every label is plain text (a stage name
holding `<` is not markup) and word-wraps; an absent line is built and hidden.
A count noun follows its own number, so in `{n} of {m} pages` it follows `{m}`.

The over-budget state is carried by the sentence on the budget line (A-10);
the dynamic property `overBudget`, set before first polish, is emphasis only.

The dialog is modal and opened with `open()`, never `exec()`. Focus starts on
the primary, or on Close when there is nothing to run; returning focus to the
invoking control on close is the caller's job.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from mangatl.pipeline.resume import RerunPreview
from mangatl.ui.cost_estimate import OVER_BUDGET, format_usd
from mangatl.ui.labels import plain_label

__all__ = ["RerunDialog"]

TITLE = "Run again"

#: The verb a stage's name is said as; any other name is its own verb.
_VERBS = {"detect": "detect", "clean": "clean", "ocr": "read", "translate": "translate"}
_ALREADY_SPENT = "The budget is already spent."
_NOTHING_TO_RUN = "Every page is done. Nothing to run."


def _pages(count: int) -> str:
    return "page" if count == 1 else "pages"


def _pages_text(preview: RerunPreview) -> str:
    if preview.pages_to_run == 0:
        return _NOTHING_TO_RUN
    total = preview.page_count
    return f"{preview.pages_to_run} of {total} {_pages(total)} still to run."


def _stages_text(preview: RerunPreview) -> str:
    clauses = [
        f"{count} to {_VERBS.get(name, name)}" for name, count in preview.pending.items() if count
    ]
    return ", ".join(clauses) + "."


def _estimate_text(preview: RerunPreview) -> str:
    pages = preview.pages_to_translate
    return f"Estimated cost to translate {pages} {_pages(pages)}: {format_usd(preview.estimate)}."


def _budget_text(preview: RerunPreview) -> str:
    ceiling = format_usd(preview.ceiling)
    if preview.spent.amount == 0:
        text = f"Nothing spent yet of the {ceiling} budget."
    else:
        text = f"{format_usd(preview.spent)} spent of the {ceiling} budget."
    if not preview.within_budget:
        text += " " + (OVER_BUDGET if preview.pages_to_translate else _ALREADY_SPENT)
    return text


class RerunDialog(QDialog):
    """The Run again dialog: what runs, what it costs, and Run / Cancel."""

    def __init__(self, preview: RerunPreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setAccessibleName(TITLE)
        self.setModal(True)
        # Read by the stylesheet's [overBudget="true"] rule; set before first polish.
        self.setProperty("overBudget", not preview.within_budget)

        to_run = preview.pages_to_run
        pages = plain_label("rerunPages", _pages_text(preview))
        stages = plain_label("rerunStages", _stages_text(preview))
        estimate = plain_label("rerunEstimate", _estimate_text(preview))
        budget = plain_label("rerunBudget", _budget_text(preview))
        # Hidden, never shown here: a parentless label shown is a window.
        if not to_run:
            stages.hide()
        if not preview.pages_to_translate:
            estimate.hide()

        self.cancel_button = QPushButton("Cancel" if to_run else "Close")
        self.cancel_button.setObjectName("rerunCancel")
        self.cancel_button.clicked.connect(self.reject)
        self.run_button: QPushButton | None = None
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        if to_run:
            self.run_button = QPushButton(f"Run {to_run} {_pages(to_run)}")
            self.run_button.setObjectName("rerunConfirm")
            self.run_button.setProperty("variant", "primary")
            self.run_button.setDefault(True)
            self.run_button.clicked.connect(self.accept)
            buttons.addWidget(self.run_button)

        layout = QVBoxLayout(self)
        lines: list[QLabel] = [pages, stages, estimate, budget]
        for label in lines:
            layout.addWidget(label)
        layout.addLayout(buttons)

        # The whole statement, read when the dialog opens (§9).
        shown = [label.text() for label in lines if not label.isHidden()]
        self.setAccessibleDescription("\n".join(shown))
        first = self.run_button if self.run_button is not None else self.cancel_button
        first.setFocus(Qt.FocusReason.OtherFocusReason)
