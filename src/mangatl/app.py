"""Entry point. Opens one window and exits cleanly."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from mangatl.ui.main_window import MainWindow

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Run the application. Returns the Qt exit code."""
    app = QApplication(argv if argv is not None else sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
