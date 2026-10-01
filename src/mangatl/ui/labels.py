"""The plain label every summary part is made of (MT-057's rules, shared in MT-058).

Plain text (a folder named `a<b>c` is not markup), word-wrapped, selectable with
the mouse so a filename or a figure can be copied, and never a focus stop. Kept
in its own module so that `summary` and `cost_estimate` - which `summary`
imports - can both use it without importing each other.

A label sets no font and no colour: its type and colour are `theme.qss`'s rule
for its object name (MT-061), which a widget-level `setFont` would fight.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

__all__ = ["plain_label"]


def plain_label(name: str, text: str) -> QLabel:
    """A plain, word-wrapped label: selectable with the mouse, never focused."""
    label = QLabel()
    label.setObjectName(name)
    # Before the text, so it is never interpreted as rich text.
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    # After the flags: mouse selection alone makes a QLabel a click-focus stop.
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return label
