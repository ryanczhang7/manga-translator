"""High Contrast token resolution (MT-026) and the theme path that calls it (MT-028).

`resolve` answers one question: what value does a design token take, given
whether a Windows contrast theme is active and the colours that theme supplies?
It is a pure function over a token name, a boolean and a plain mapping of role
name to `#RRGGBB` string - no Qt, no display. Snapshotting a real `QPalette` into
that mapping is `mangatl.ui.contrast.palette_snapshot` (MT-028).

MT-028 adds the path that uses it (`high-contrast.md` sections 2, 2.1 and 8):
`compose_stylesheet` re-composes the whole sheet from resolved values - the base
template, then the override appended - rather than dropping or narrowing it,
because a stylesheet that keeps its authored colours under a contrast theme is
the bug (A-15.3); `ThemeController` applies it with `setStyleSheet` and nothing
else, at startup and on each live change, announcing a change once (A-15.10,
A-12); `apply_theme` is what `mangatl.app.main` calls.

The rules are `docs/wiki/design/accessibility.md` A-15.1-A-15.3 and A-15.6, and
`docs/wiki/design/high-contrast.md` section 4 (the mapping and its exemptions) and
section 7.1 (dimming stops). The one rule everything rests on is that resolution
never silently falls back: an unknown token or a role the palette does not carry
raises, where a test can see it, instead of producing a half-High-Contrast screen.

Hand-written, deliberately not in the generated `tokens_gen` (section 4.3): logic
in a generated file is logic nobody reviews.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from mangatl.ui.contrast import ContrastSource, palette_snapshot
from mangatl.ui.link import LiveRegion
from mangatl.ui.stylesheet import base_template, hc_template
from mangatl.ui.tokens import _PLACEHOLDER, HC_ROLES, STATIC
from mangatl.ui.tokens_gen import HC_OVERRIDE, HC_PALETTE_ROLE, TOKENS

__all__ = [
    "HC_ROLES",
    "STATIC",
    "MissingPaletteRole",
    "ThemeController",
    "UnknownToken",
    "apply_theme",
    "compose_stylesheet",
    "resolve",
]

#: The override template's palette-role placeholders are `@{hc.<Role>}`.
_HC_PREFIX = "hc."
#: `high-contrast.md` section 8, exactly.
_ANNOUNCE_ON = "High contrast on."
_ANNOUNCE_OFF = "High contrast off."


class UnknownToken(KeyError):
    """A name that is not a key of `TOKENS`, in either mode."""

    def __init__(self, token: str) -> None:
        super().__init__(f"unknown design token {token!r}")
        self.token = token


class MissingPaletteRole(KeyError):
    """Under High Contrast, a token's mapped role is absent from the palette.

    Raised rather than falling back to the authored value: a silent fall-back is
    "High Contrast not supported", arrived at quietly (A-15.3).
    """

    def __init__(self, token: str, role: str) -> None:
        super().__init__(
            f"design token {token!r} maps to palette role {role!r}, "
            f"which the High Contrast palette does not provide"
        )
        self.token = token
        self.role = role


def resolve(name: str, *, high_contrast: bool, palette: Mapping[str, str]) -> str:
    """The value of token `name`, under High Contrast or not.

    The palette is read with `in` and `[]` only, and its values are returned as
    given - never normalised, never validated as colours.
    """
    if name not in TOKENS:
        raise UnknownToken(name)
    if not high_contrast:
        return TOKENS[name]
    if name in HC_OVERRIDE:
        return str(HC_OVERRIDE[name])
    if name in HC_PALETTE_ROLE:
        role = HC_PALETTE_ROLE[name]
        if role == STATIC:
            return TOKENS[name]
        if role not in palette:
            raise MissingPaletteRole(name, role)
        return palette[role]
    # In neither dict: a non-colour token, exempt (section 4.2, third group).
    return TOKENS[name]


def compose_stylesheet(
    base_tmpl: str, hc_tmpl: str, *, high_contrast: bool, palette: Mapping[str, str]
) -> str:
    """The application stylesheet for one mode (`high-contrast.md` section 2.1).

    Off: the base template with every `@{name}` resolved - the generator's own
    substitution, so the result is the packaged `theme.qss` byte for byte.
    On: the base template resolved under High Contrast, then `"\n"`, then the
    override template with `@{hc.Role}` taken from `palette` - appended, never
    substituted, and the base is never narrowed. Nothing is swallowed: an
    unknown token raises `UnknownToken`, a missing role `MissingPaletteRole`.
    """

    def base(match: re.Match[str]) -> str:
        return resolve(match.group(1), high_contrast=high_contrast, palette=palette)

    sheet = _PLACEHOLDER.sub(base, base_tmpl)
    if not high_contrast:
        return sheet

    def override(match: re.Match[str]) -> str:
        name = match.group(1)
        if name.startswith(_HC_PREFIX):
            role = name.removeprefix(_HC_PREFIX)
            if role not in palette:
                raise MissingPaletteRole(name, role)
            return palette[role]
        return resolve(name, high_contrast=True, palette=palette)

    return sheet + "\n" + _PLACEHOLDER.sub(override, hc_tmpl)


def _system_palette() -> dict[str, str]:
    # The class-level palette: reading it never touches the application object,
    # so with High Contrast off nothing but `setStyleSheet` reaches `app` (PO-4).
    return palette_snapshot(QGuiApplication.palette())


class ThemeController(QObject):
    """Applies the stylesheet for the source's mode, and again on each change.

    Re-applying is `app.setStyleSheet` and nothing else: no widget is rebuilt and
    no state is touched, which is what keeps uncommitted text, selection, scroll
    and zoom across a live change (A-15.10, section 8)."""

    themeApplied = Signal(bool)

    def __init__(
        self,
        app: QApplication,
        source: ContrastSource,
        *,
        palette_provider: Callable[[], Mapping[str, str]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._source = source
        self._palette_provider = palette_provider or _system_palette
        self._high_contrast = False
        #: The one widget this controller creates: parentless and off-screen (A-12).
        self.live_region = LiveRegion()

    @property
    def high_contrast(self) -> bool:
        """The mode most recently applied."""
        return self._high_contrast

    def apply(self) -> None:
        """Compose for the source's current mode and set it on the application."""
        high_contrast = self._source.is_high_contrast()
        # The palette is read only when it will be used (Contract block 4).
        palette: Mapping[str, str] = self._palette_provider() if high_contrast else {}
        sheet = compose_stylesheet(
            base_template(), hc_template(), high_contrast=high_contrast, palette=palette
        )
        self._app.setStyleSheet(sheet)
        self._high_contrast = high_contrast
        self.themeApplied.emit(high_contrast)

    def _on_changed(self, value: bool) -> None:
        # Changes, not notifications (AC-9).
        if value == self._high_contrast:
            return
        self.apply()
        self.live_region.announce(_ANNOUNCE_ON if self._high_contrast else _ANNOUNCE_OFF)


def apply_theme(
    app: QApplication,
    source: ContrastSource,
    *,
    palette_provider: Callable[[], Mapping[str, str]] | None = None,
) -> ThemeController:
    """Apply the theme for `source` now, and on every change it reports.

    The initial application announces nothing (AC-8). The caller keeps the
    returned controller alive for as long as the theme should follow `source`."""
    controller = ThemeController(app, source, palette_provider=palette_provider)
    controller.apply()
    source.changed.connect(controller._on_changed)
    return controller
