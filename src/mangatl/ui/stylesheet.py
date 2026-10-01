"""The application's base stylesheet, read from the package (MT-061).

`theme.qss` is generated from `docs/wiki/design/theme.qss.in` by
`mangatl.ui.tokens` and shipped inside the `mangatl.ui` package. It is read as a
package resource, never from the design sources or a path built off the source
tree, because a frozen build carries only what the package carries
(`tokens.md` §12.1).

There is deliberately no fallback: a build without the file fails at startup,
loudly, rather than running unthemed.
"""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtWidgets import QApplication

__all__ = ["THEME_RESOURCE", "apply_base_stylesheet", "base_stylesheet"]

THEME_RESOURCE = "theme.qss"


def base_stylesheet() -> str:
    """The packaged `theme.qss`, decoded as UTF-8 byte for byte (no newline
    translation, so the text is exactly what the generator wrote)."""
    return files("mangatl.ui").joinpath(THEME_RESOURCE).read_bytes().decode("utf-8")


def apply_base_stylesheet(app: QApplication) -> None:
    """Set the packaged base sheet on `app`, for every widget it will show."""
    app.setStyleSheet(base_stylesheet())
