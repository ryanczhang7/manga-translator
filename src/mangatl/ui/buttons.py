"""`ActivatedByEnter`: a push button that Return and Enter activate.

Outside a dialog a `QPushButton` activates on Space only and ignores Return and
Enter (measured in MT-057 RED). Every button this app puts outside a dialog -
the summary's two (MT-057, MT-059) and a banner's actions (MT-059 D-3) - is
activated by all three, once each.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QPushButton

__all__ = ["ActivatedByEnter"]

_ACTIVATION_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


class ActivatedByEnter(QPushButton):
    """A push button that Return and Enter activate as Space does."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in _ACTIVATION_KEYS and not event.isAutoRepeat():
            self.click()
            return
        super().keyPressEvent(event)
