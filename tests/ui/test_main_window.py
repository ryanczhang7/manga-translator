"""The walking skeleton's window: it opens, it is identifiable, it closes.

MT-055 rewrote the pins of MT-001's bare canvas: with no notice the window is
the folder intake (`FolderDropTarget`), which needs an `open_folder` (C-2), so
every `MainWindow()` here is given a stub one. The central widget's accessible
name is now the drop target's, read out of `accessibility.md` A-08.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QMainWindow

from mangatl import app as app_module
from mangatl.ui.main_window import WINDOW_TITLE, MainWindow


def _never_opens(folder: Path) -> str:
    """A stub `open_folder`: these tests never choose a folder."""
    raise AssertionError(f"no folder should be opened here, got {folder}")


def test_the_window_opens_with_the_application_title(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(open_folder=_never_opens)
    qtbot.addWidget(window)
    window.show()

    assert isinstance(window, QMainWindow)
    assert window.windowTitle() == WINDOW_TITLE
    assert window.isVisible()


def test_the_central_widget_is_the_chapter_folder_button(qtbot) -> None:  # type: ignore[no-untyped-def]
    """MT-055 AC-1 / A-08: role Button, name "Choose chapter folder"."""
    window = MainWindow(open_folder=_never_opens)
    qtbot.addWidget(window)

    central = window.centralWidget()
    assert central is not None
    interface = QAccessible.queryAccessibleInterface(central)
    assert interface is not None
    assert interface.role() == QAccessible.Role.Button, f"role is {interface.role()!r}"
    assert interface.text(QAccessible.Text.Name) == "Choose chapter folder"


def test_the_window_closes(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(open_folder=_never_opens)
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()

    assert window.close()
    assert not window.isVisible()


class _FakeQApplication:
    """Stands in for QApplication so `main` can be run without an event loop.

    A real `app.exec()` blocks forever, and only one QApplication may exist per
    process - qtbot already made it.
    """

    exit_code = 7

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        _FakeQApplication.last = self

    def exec(self) -> int:
        return _FakeQApplication.exit_code


def test_main_returns_the_qt_exit_code(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(app_module, "QApplication", _FakeQApplication)

    assert app_module.main(["mangatl"]) == 7
    assert _FakeQApplication.last.argv == ["mangatl"]


def test_main_falls_back_to_sys_argv(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(app_module, "QApplication", _FakeQApplication)
    monkeypatch.setattr(sys, "argv", ["mangatl", "--from-sys-argv"])

    app_module.main()

    assert _FakeQApplication.last.argv == ["mangatl", "--from-sys-argv"]
