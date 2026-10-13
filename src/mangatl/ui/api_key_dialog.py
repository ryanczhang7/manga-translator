"""`ApiKeyDialog`: the first-run question for the Gemini API key (MT-077 C-2).

The one setup step the brief permits (architecture.md §8 step 4). The dialog
asks for the key, links to Google AI Studio where one is obtained, and says
that Cancel still leaves chapters open for review. It only asks: storing the
key is `mangatl.app.first_run`'s, so this module imports Qt and nothing else -
no store, no SDK, no `mangatl.app`.

The field echoes as a password (AC-5). Ok is enabled only while the field holds
something other than whitespace; `key()` strips a paste's surrounding
whitespace and leaves the inside alone.

`ask_api_key` runs the dialog with `exec()`: it is shown at startup, before any
main window exists, so there is nothing for an `open()` to return to.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

__all__ = ["AI_STUDIO_URL", "ApiKeyDialog", "ask_api_key"]

AI_STUDIO_URL = "https://aistudio.google.com/apikey"

TITLE = "Gemini API key"
PROMPT = "Translating pages needs a Gemini API key. It is saved on this computer."
LINK = f'<a href="{AI_STUDIO_URL}">Get a key from Google AI Studio</a>'
REVIEW_ONLY = "Without a key, chapters can still be opened and reviewed, but not translated."


class ApiKeyDialog(QDialog):
    """Asks for the Gemini API key. Ok accepts, Cancel rejects."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setModal(True)

        prompt = QLabel(PROMPT)
        prompt.setTextFormat(Qt.TextFormat.PlainText)
        prompt.setWordWrap(True)

        self.key_field = QLineEdit()
        self.key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_field.setAccessibleName(TITLE)

        self.link_label = QLabel(LINK)
        self.link_label.setTextFormat(Qt.TextFormat.RichText)
        self.link_label.setOpenExternalLinks(True)

        review = QLabel(REVIEW_ONLY)
        review.setTextFormat(Qt.TextFormat.PlainText)
        review.setWordWrap(True)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(prompt)
        layout.addWidget(self.key_field)
        layout.addWidget(self.link_label)
        layout.addWidget(review)
        layout.addWidget(self.buttons)

        self.key_field.textChanged.connect(self._update_ok)
        self._update_ok()
        self.key_field.setFocus()

    def key(self) -> str:
        """The typed key without surrounding whitespace."""
        return self.key_field.text().strip()

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(self.key() != "")


def ask_api_key(parent: QWidget | None = None) -> str | None:
    """Show the dialog modally: the key on Ok, `None` on Cancel."""
    dialog = ApiKeyDialog(parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    key = dialog.key() if accepted else None
    dialog.deleteLater()
    return key
