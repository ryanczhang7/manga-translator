"""The walking skeleton's window: it opens, it is identifiable, it closes."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QMainWindow

from mangatl import app as app_module
from mangatl.ui.main_window import CANVAS_ACCESSIBLE_NAME, WINDOW_TITLE, MainWindow


def test_the_window_opens_with_the_application_title(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert isinstance(window, QMainWindow)
    assert window.windowTitle() == WINDOW_TITLE
    assert window.isVisible()


def test_the_central_widget_carries_an_accessible_name(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    central = window.centralWidget()
    assert central is not None
    assert central.accessibleName() == CANVAS_ACCESSIBLE_NAME


def test_the_window_closes(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
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
