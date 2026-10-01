"""The plain label every summary part is made of (MT-057's rules, shared in MT-058).

Plain text (a folder named `a<b>c` is not markup), word-wrapped, selectable with
the mouse so a filename or a figure can be copied, and never a focus stop. Kept
in its own module so that `summary` and `cost_estimate` - which `summary`
imports - can both use it without importing each other.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel

from mangatl.ui import tokens_gen

__all__ = ["BODY", "BODY_STRONG", "TITLE", "plain_label"]

#: `(pixel size, weight)` of the type tokens the summary uses.
TITLE = (tokens_gen.TYPE_TITLE_SIZE, tokens_gen.TYPE_TITLE_WEIGHT)
BODY = (tokens_gen.TYPE_BODY_SIZE, tokens_gen.TYPE_BODY_WEIGHT)
BODY_STRONG = (tokens_gen.TYPE_BODY_STRONG_SIZE, tokens_gen.TYPE_BODY_STRONG_WEIGHT)


def _font(size: int, weight: int) -> QFont:
    font = QFont()
    font.setPixelSize(size)
    font.setWeight(QFont.Weight(weight))
    return font


def plain_label(name: str, text: str, type_: tuple[int, int]) -> QLabel:
    """A plain, word-wrapped label: selectable with the mouse, never focused."""
    label = QLabel()
    label.setObjectName(name)
    # Before the text, so it is never interpreted as rich text.
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(text)
    label.setWordWrap(True)
    label.setFont(_font(*type_))
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    # After the flags: mouse selection alone makes a QLabel a click-focus stop.
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return label
