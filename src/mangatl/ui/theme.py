"""High Contrast token resolution (MT-026).

`resolve` answers one question: what value does a design token take, given
whether a Windows contrast theme is active and the colours that theme supplies?
It is a pure function over a token name, a boolean and a plain mapping of role
name to `#RRGGBB` string - no Qt, no display. Snapshotting a real `QPalette` into
that mapping, and applying the result, belong to MT-028.

The rules are `docs/wiki/design/accessibility.md` A-15.1-A-15.3 and A-15.6, and
`docs/wiki/design/high-contrast.md` section 4 (the mapping and its exemptions) and
section 7.1 (dimming stops). The one rule everything rests on is that resolution
never silently falls back: an unknown token or a role the palette does not carry
raises, where a test can see it, instead of producing a half-High-Contrast screen.

Hand-written, deliberately not in the generated `tokens_gen` (section 4.3): logic
in a generated file is logic nobody reviews.
"""

from __future__ import annotations

from collections.abc import Mapping

from mangatl.ui.tokens import HC_ROLES, STATIC
from mangatl.ui.tokens_gen import HC_OVERRIDE, HC_PALETTE_ROLE, TOKENS

__all__ = ["HC_ROLES", "STATIC", "MissingPaletteRole", "UnknownToken", "resolve"]


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
