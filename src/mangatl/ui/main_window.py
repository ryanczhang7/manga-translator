"""The application's window when no chapter is open.

With no `notice` it is the folder intake (MT-055): its whole content is a
`FolderDropTarget`. Activating it asks `choose_folder` for a folder, and
dropping one folder on it (MT-056) supplies one directly; either way the folder
goes down one path to `open_folder`. The window does not decide what a folder
means - `mangatl.app` injects that function, the same one `mangatl <folder>`
runs, so the picker, the drop and the command line cannot drift apart. A window back
from it is the opened chapter: it is shown, then this window closes. A string
back is the reason nothing opened, shown in the target's error state.

With a `notice` (MT-054 C-5) the window says one thing instead: why no chapter
could be opened, and what to do about it. The notice is the whole content of
the window, so it is its accessible name, plain text (a folder name holding
`<` is not markup) and selectable, so the command it names can be copied.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget

from mangatl.ui.intake import FolderDropTarget, choose_folder_dialog

__all__ = [
    "NOTICE_OBJECT_NAME",
    "WINDOW_TITLE",
    "FolderChooser",
    "FolderOpener",
    "MainWindow",
]

WINDOW_TITLE = "mangatl"
NOTICE_OBJECT_NAME = "notice"

#: A folder to the window that opened it, or the reason nothing opened.
FolderOpener = Callable[[Path], QMainWindow | str]
#: The chosen folder, or `None` when the choice was dismissed.
FolderChooser = Callable[[QWidget], Path | None]


class MainWindow(QMainWindow):
    """The single top-level window before a chapter is open."""

    def __init__(
        self,
        notice: str | None = None,
        *,
        open_folder: FolderOpener | None = None,
        choose_folder: FolderChooser | None = None,
    ) -> None:
        if notice is None and open_folder is None:
            # A window that can choose a folder and do nothing with it is not
            # a state this app has (MT-055 C-2).
            raise TypeError("MainWindow needs a notice or an open_folder")
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.open_folder = open_folder
        self.opened: QMainWindow | None = None
        if notice is not None:
            self.setCentralWidget(_notice_label(notice, self))
            return
        assert open_folder is not None  # the TypeError above
        self._open: FolderOpener = open_folder
        self._choose_folder = choose_folder or choose_folder_dialog
        self._target = FolderDropTarget(self)
        self._target.activated.connect(self._choose)
        self._target.dropped.connect(self._hand_over)
        self.setCentralWidget(self._target)

    def _choose(self) -> None:
        folder = self._choose_folder(self)
        if folder is None:
            return
        self._hand_over(folder)

    def _hand_over(self, folder: Path) -> None:
        """The one path a folder takes, chosen or dropped (MT-056 C-2)."""
        outcome = self._open(folder)
        if isinstance(outcome, str):
            self._target.show_error(outcome)
            return
        self.opened = outcome
        # Shown first, so quit-on-last-window-closed never sees zero windows.
        outcome.show()
        self.close()


def _notice_label(notice: str, parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName(NOTICE_OBJECT_NAME)
    # Before the text, so it is never interpreted as rich text.
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(notice)
    label.setAccessibleName(notice)
    label.setWordWrap(True)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    return label
