"""The application's stylesheets, read from the package (MT-061, MT-028).

`theme.qss` is generated from `docs/wiki/design/theme.qss.in` by
`mangatl.ui.tokens` and shipped inside the `mangatl.ui` package. It is read as a
package resource, never from the design sources or a path built off the source
tree, because a frozen build carries only what the package carries
(`tokens.md` §12.1).

The two templates the generator also ships - `theme.qss.tmpl` (the base, with its
`@{token}` placeholders) and `theme_hc.qss.tmpl` (the append-only High Contrast
override) - are read the same way, for `theme.compose_stylesheet` (MT-028,
`high-contrast.md` §2).

There is deliberately no fallback: a build without the file fails at startup,
loudly, rather than running unthemed.
"""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtWidgets import QApplication

__all__ = [
    "BASE_TEMPLATE_RESOURCE",
    "HC_TEMPLATE_RESOURCE",
    "THEME_RESOURCE",
    "apply_base_stylesheet",
    "base_stylesheet",
    "base_template",
    "hc_template",
]

THEME_RESOURCE = "theme.qss"
BASE_TEMPLATE_RESOURCE = "theme.qss.tmpl"
HC_TEMPLATE_RESOURCE = "theme_hc.qss.tmpl"


def _read(resource: str) -> str:
    """A packaged resource decoded as UTF-8 byte for byte (no newline
    translation, so the text is exactly what the generator wrote)."""
    return files("mangatl.ui").joinpath(resource).read_bytes().decode("utf-8")


def base_stylesheet() -> str:
    """The packaged `theme.qss`, decoded as UTF-8 byte for byte (no newline
    translation, so the text is exactly what the generator wrote)."""
    return files("mangatl.ui").joinpath(THEME_RESOURCE).read_bytes().decode("utf-8")


def base_template() -> str:
    """The packaged base template, `@{token}` placeholders unrendered."""
    return _read(BASE_TEMPLATE_RESOURCE)


def hc_template() -> str:
    """The packaged High Contrast override template, unrendered."""
    return _read(HC_TEMPLATE_RESOURCE)


def apply_base_stylesheet(app: QApplication) -> None:
    """Set the packaged base sheet on `app`, for every widget it will show."""
    app.setStyleSheet(base_stylesheet())
