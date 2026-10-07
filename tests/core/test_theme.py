"""MT-026: High Contrast token resolution is total and loud.

`mangatl.ui.theme.resolve(name, *, high_contrast, palette) -> str` against the
generated data in `mangatl.ui.tokens_gen` (`TOKENS`, `HC_PALETTE_ROLE`,
`HC_OVERRIDE`). Every expected value is read out of `accessibility.md` A-15.1-A-15.6
and `high-contrast.md` section 4 and section 7.1; nothing here is calibrated. The
oracle partition is entirely mechanical.

The AC each test covers is in its name. Every whole-set test iterates `TOKENS`,
`HC_PALETTE_ROLE` or `HC_OVERRIDE` themselves (Contract block 5), never a
hand-written sample: a sample cannot fail when a colour is added.

No Qt import, anywhere: `resolve` is a pure function and a test of it that needs
a display is phrased wrongly.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType

import pytest

import mangatl.ui.theme as theme
import mangatl.ui.tokens as tokens
from mangatl.ui.theme import (
    HC_ROLES,
    STATIC,
    MissingPaletteRole,
    UnknownToken,
    resolve,
)
from mangatl.ui.tokens_gen import HC_OVERRIDE, HC_PALETTE_ROLE, TOKENS

#: A-15.2 / `high-contrast.md` 4.1, written out here rather than read from the
#: module, so `HC_ROLES` is pinned by equality with the document.
FIVE_ROLES = frozenset({"Window", "WindowText", "Highlight", "HighlightedText", "DisabledText"})

#: The designer's synthetic palette (`design/README.md`, "High Contrast - token
#: resolution"; AC-10). Used as given; `Window` and `HighlightedText` share a value.
DESIGNER_PALETTE: dict[str, str] = {
    "Window": "#000000",
    "WindowText": "#FFFFFF",
    "Highlight": "#1AEBFF",
    "HighlightedText": "#000000",
    "DisabledText": "#3FF23F",
}

#: A five-key palette whose values are pairwise distinct, odd-cased, and appear
#: nowhere in `TOKENS`, so a value returned under HC names the role it came from
#: (AC-3) and no normalisation of case can pass unnoticed.
DISTINCT_PALETTE: dict[str, str] = {
    "Window": "#AbCdEf",
    "WindowText": "#fEdCbA",
    "Highlight": "#0a1B2c",
    "HighlightedText": "#D3e4F5",
    "DisabledText": "#6a7B8c",
}

#: `high-contrast.md` 4.2 and A-15.5, groups one and two, derived mechanically:
#: every `overlay.*` token and the two canvas names, minus `overlay.dim.opacity`
#: (A-15.6, the one non-colour token that is not exempt).
CANVAS_EXEMPT = frozenset({"color.canvas.surround", "color.canvas.page-edge"})
DIM = "overlay.dim.opacity"
ARTWORK_EXEMPT = frozenset({n for n in TOKENS if n.startswith("overlay.")} | CANVAS_EXEMPT) - {DIM}

STATIC_TOKENS = sorted(n for n, role in HC_PALETTE_ROLE.items() if role == "@static")
UNMAPPED_TOKENS = sorted(n for n in TOKENS if n not in HC_PALETTE_ROLE and n not in HC_OVERRIDE)
EXEMPT_TOKENS = sorted(set(STATIC_TOKENS) | set(UNMAPPED_TOKENS))
ROLE_MAPPED_TOKENS = sorted(n for n, role in HC_PALETTE_ROLE.items() if role != "@static")
NON_EXEMPT_COLOUR_TOKENS = sorted(
    n for n in TOKENS if n.startswith("color.") and n not in ARTWORK_EXEMPT
)

UNKNOWN_NAMES = [
    "",
    "color",
    "color.surface",
    "color.surface.bse",
    "COLOR.SURFACE.BASE",
    "color.surface.base ",
    "COLOR_SURFACE_BASE",
    "overlay.dim",
    "hc.map.color.surface.base",
    "Window",
]


class ExplodingPalette(Mapping[str, str]):
    """A palette that fails the test the moment anything reads it."""

    def __getitem__(self, key: str) -> str:
        raise AssertionError(f"palette was read with [{key!r}]")

    def __contains__(self, key: object) -> bool:
        raise AssertionError(f"palette was read with {key!r} in palette")

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("palette was iterated")

    def __len__(self) -> int:
        raise AssertionError("palette len() was taken")

    def get(self, key, default=None):  # type: ignore[override]
        raise AssertionError(f"palette.get({key!r}) was called")


class InAndIndexOnlyPalette(Mapping[str, str]):
    """Block 4: a palette that answers `in` and `[]` and refuses everything else."""

    def __init__(self, data: Mapping[str, str]) -> None:
        self._data = dict(data)

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("resolve iterated the palette (block 4: `in` and `[]` only)")

    def __len__(self) -> int:
        raise AssertionError("resolve took len() of the palette (block 4)")

    def get(self, key, default=None):  # type: ignore[override]
        raise AssertionError(f"resolve called palette.get({key!r}) (block 4)")

    def keys(self):  # type: ignore[override]
        raise AssertionError("resolve called palette.keys() (block 4)")

    def values(self):  # type: ignore[override]
        raise AssertionError("resolve called palette.values() (block 4)")

    def items(self):  # type: ignore[override]
        raise AssertionError("resolve called palette.items() (block 4)")


def _without(role: str, palette: Mapping[str, str] = DESIGNER_PALETTE) -> dict[str, str]:
    return {k: v for k, v in palette.items() if k != role}


# --- the shipped data the resolution model depends on ------------------------------


def test_the_shipped_data_has_the_shape_the_story_was_written_against() -> None:
    assert len(TOKENS) == 126
    assert all(isinstance(v, str) for v in TOKENS.values())
    assert len(HC_PALETTE_ROLE) == 40
    assert set(HC_PALETTE_ROLE) <= set(TOKENS)
    assert set(HC_OVERRIDE) <= set(TOKENS)
    assert len(UNMAPPED_TOKENS) == 85
    assert len(STATIC_TOKENS) == 10
    assert len(ROLE_MAPPED_TOKENS) == 30


def test_override_and_role_map_are_disjoint_so_precedence_is_never_a_live_question() -> None:
    """Contract block 2 step 3 / PO-5: an overlap must be a loud failure."""
    assert set(HC_OVERRIDE).isdisjoint(HC_PALETTE_ROLE)


# --- AC-6: five roles, the sentinel, and the re-export ------------------------------


def test_ac6_the_role_map_uses_only_the_five_guaranteed_roles_and_the_sentinel() -> None:
    used = set(HC_PALETTE_ROLE.values())
    assert used <= FIVE_ROLES | {"@static"}, sorted(used - (FIVE_ROLES | {"@static"}))


@pytest.mark.parametrize("forbidden", ["Button", "ButtonText", "Link"])
def test_ac6_the_role_map_never_uses_an_unguaranteed_cross_product_role(forbidden: str) -> None:
    offenders = sorted(n for n, role in HC_PALETTE_ROLE.items() if role == forbidden)
    assert offenders == []


def test_ac6_theme_hc_roles_is_exactly_the_five_documented_roles() -> None:
    assert isinstance(theme.HC_ROLES, frozenset)
    assert (
        frozenset({"Window", "WindowText", "Highlight", "HighlightedText", "DisabledText"})
        == theme.HC_ROLES
    )
    assert HC_ROLES is theme.HC_ROLES


def test_ac6_theme_re_exports_hc_roles_and_static_from_the_generator_not_a_copy() -> None:
    assert theme.HC_ROLES == tokens.HC_ROLES
    assert theme.HC_ROLES is tokens.HC_ROLES
    assert theme.STATIC == tokens.STATIC == "@static"
    assert STATIC == "@static"


# --- AC-1: high_contrast=False is the authored value, always ------------------------


@pytest.mark.parametrize("name", list(TOKENS))
def test_ac1_without_high_contrast_every_token_is_its_authored_value(name: str) -> None:
    for palette in ({}, DESIGNER_PALETTE, DISTINCT_PALETTE, _without("Highlight")):
        assert resolve(name, high_contrast=False, palette=palette) == TOKENS[name]


def test_ac1_without_high_contrast_the_palette_is_never_read() -> None:
    """Contract block 2 step 2: nothing else is read."""
    palette = ExplodingPalette()
    resolved = {name: resolve(name, high_contrast=False, palette=palette) for name in TOKENS}
    assert resolved == TOKENS


# --- AC-2: exempt tokens keep their authored value under HC -------------------------


@pytest.mark.parametrize("name", STATIC_TOKENS)
def test_ac2_a_static_mapped_token_keeps_its_authored_value_under_high_contrast(
    name: str,
) -> None:
    for palette in ({}, DESIGNER_PALETTE, DISTINCT_PALETTE):
        assert resolve(name, high_contrast=True, palette=palette) == TOKENS[name]


@pytest.mark.parametrize("name", UNMAPPED_TOKENS)
def test_ac2_a_non_colour_token_in_neither_map_keeps_its_authored_value_under_high_contrast(
    name: str,
) -> None:
    for palette in ({}, DESIGNER_PALETTE, DISTINCT_PALETTE):
        assert resolve(name, high_contrast=True, palette=palette) == TOKENS[name]


def test_ac2_exempt_tokens_never_read_the_palette_under_high_contrast() -> None:
    palette = ExplodingPalette()
    resolved = {name: resolve(name, high_contrast=True, palette=palette) for name in EXEMPT_TOKENS}
    assert resolved == {name: TOKENS[name] for name in EXEMPT_TOKENS}


def test_ac2_the_exempt_groups_cover_every_token_that_is_neither_role_mapped_nor_overridden() -> (
    None
):
    assert set(EXEMPT_TOKENS) | set(ROLE_MAPPED_TOKENS) | set(HC_OVERRIDE) == set(TOKENS)
    assert DIM not in EXEMPT_TOKENS


# --- AC-3: a role-mapped token is palette[role], byte for byte ----------------------


@pytest.mark.parametrize("name", ROLE_MAPPED_TOKENS)
def test_ac3_a_role_mapped_token_resolves_to_its_own_role_in_the_palette(name: str) -> None:
    role = HC_PALETTE_ROLE[name]
    assert resolve(name, high_contrast=True, palette=DISTINCT_PALETTE) == DISTINCT_PALETTE[role]


def test_ac3_the_palette_value_is_returned_without_normalising_case() -> None:
    assert resolve("color.surface.base", high_contrast=True, palette=DISTINCT_PALETTE) == "#AbCdEf"
    assert resolve("color.text.primary", high_contrast=True, palette=DISTINCT_PALETTE) == "#fEdCbA"
    assert (
        resolve("color.surface.selected", high_contrast=True, palette=DISTINCT_PALETTE) == "#0a1B2c"
    )
    assert (
        resolve("color.text.on-accent", high_contrast=True, palette=DISTINCT_PALETTE) == "#D3e4F5"
    )
    assert resolve("color.text.disabled", high_contrast=True, palette=DISTINCT_PALETTE) == "#6a7B8c"


def test_ac3_the_palette_value_is_returned_as_given_and_never_validated_as_a_colour() -> None:
    """Contract block 4: resolve never validates that a value is a colour."""
    palette = {**DISTINCT_PALETTE, "Window": "not a colour"}
    assert resolve("color.surface.base", high_contrast=True, palette=palette) == "not a colour"


def test_ac3_a_mapping_proxy_palette_is_accepted() -> None:
    """Contract block 4: any Mapping, read with `in` and `[]`."""
    palette = MappingProxyType(dict(DISTINCT_PALETTE))
    resolved = {
        name: resolve(name, high_contrast=True, palette=palette) for name in ROLE_MAPPED_TOKENS
    }
    assert resolved == {
        name: DISTINCT_PALETTE[HC_PALETTE_ROLE[name]] for name in ROLE_MAPPED_TOKENS
    }


def test_ac3_the_palette_is_read_with_in_and_index_only() -> None:
    """Contract block 4: never `.get`, never iteration."""
    palette = InAndIndexOnlyPalette(DISTINCT_PALETTE)
    resolved = {name: resolve(name, high_contrast=True, palette=palette) for name in TOKENS}
    expected = {
        name: (
            str(HC_OVERRIDE[name])
            if name in HC_OVERRIDE
            else DISTINCT_PALETTE[HC_PALETTE_ROLE[name]]
            if name in ROLE_MAPPED_TOKENS
            else TOKENS[name]
        )
        for name in TOKENS
    }
    assert resolved == expected


def test_ac3_a_role_missing_from_the_palette_does_not_affect_tokens_mapped_to_other_roles() -> None:
    palette = _without("DisabledText", DISTINCT_PALETTE)
    for name in ROLE_MAPPED_TOKENS:
        if HC_PALETTE_ROLE[name] != "DisabledText":
            assert (
                resolve(name, high_contrast=True, palette=palette) == palette[HC_PALETTE_ROLE[name]]
            )


# --- AC-4: a mapped role absent from the palette raises -----------------------------


def test_ac4_selected_surface_with_no_highlight_in_the_palette_raises_naming_both() -> None:
    with pytest.raises(MissingPaletteRole) as caught:
        resolve("color.surface.selected", high_contrast=True, palette=_without("Highlight"))
    exc = caught.value
    assert isinstance(exc.args[0], str)
    assert "color.surface.selected" in exc.args[0]
    assert "Highlight" in exc.args[0]
    assert exc.token == "color.surface.selected"
    assert exc.role == "Highlight"


def test_ac4_disabled_text_with_no_disabled_text_role_raises_naming_both() -> None:
    with pytest.raises(MissingPaletteRole) as caught:
        resolve("color.text.disabled", high_contrast=True, palette=_without("DisabledText"))
    exc = caught.value
    assert isinstance(exc.args[0], str)
    assert "color.text.disabled" in exc.args[0]
    assert "DisabledText" in exc.args[0]
    assert exc.token == "color.text.disabled"
    assert exc.role == "DisabledText"


@pytest.mark.parametrize("name", ROLE_MAPPED_TOKENS)
def test_ac4_every_role_mapped_token_raises_rather_than_falling_back_when_its_role_is_absent(
    name: str,
) -> None:
    role = HC_PALETTE_ROLE[name]
    for palette in ({}, _without(role)):
        with pytest.raises(MissingPaletteRole) as caught:
            resolve(name, high_contrast=True, palette=palette)
        exc = caught.value
        assert isinstance(exc.args[0], str)
        assert name in exc.args[0]
        assert role in exc.args[0]
        assert (exc.token, exc.role) == (name, role)


# --- AC-5: an unknown name raises in both modes, before the palette is read ---------


@pytest.mark.parametrize("high_contrast", [False, True])
@pytest.mark.parametrize("name", UNKNOWN_NAMES)
def test_ac5_an_unknown_token_name_raises_unknown_token_in_either_mode(
    name: str, high_contrast: bool
) -> None:
    assert name not in TOKENS
    with pytest.raises(UnknownToken) as caught:
        resolve(name, high_contrast=high_contrast, palette=DESIGNER_PALETTE)
    exc = caught.value
    assert isinstance(exc.args[0], str)
    assert name in exc.args[0]
    assert exc.token == name


@pytest.mark.parametrize("high_contrast", [False, True])
def test_ac5_an_unknown_token_raises_before_the_palette_is_consulted(high_contrast: bool) -> None:
    with pytest.raises(UnknownToken) as caught:
        resolve("color.surface.nope", high_contrast=high_contrast, palette=ExplodingPalette())
    assert caught.value.token == "color.surface.nope"


def test_ac5_an_unknown_token_is_unknown_even_with_an_empty_palette_under_high_contrast() -> None:
    with pytest.raises(UnknownToken):
        resolve("color.surface.nope", high_contrast=True, palette={})


def test_ac5_both_exceptions_subclass_key_error_directly_and_neither_subclasses_the_other() -> None:
    assert UnknownToken.__bases__ == (KeyError,)
    assert MissingPaletteRole.__bases__ == (KeyError,)
    assert not issubclass(UnknownToken, MissingPaletteRole)
    assert not issubclass(MissingPaletteRole, UnknownToken)


def test_ac5_catching_unknown_token_does_not_swallow_a_missing_role() -> None:
    with pytest.raises(MissingPaletteRole):
        try:
            resolve("color.surface.base", high_contrast=True, palette={})
        except UnknownToken:  # pragma: no cover - reaching here is the failure
            pytest.fail("a missing palette role was raised as UnknownToken")


# --- AC-7: totality ----------------------------------------------------------------


@pytest.mark.parametrize(
    "palette", [DESIGNER_PALETTE, DISTINCT_PALETTE], ids=["designer", "distinct"]
)
def test_ac7_every_token_resolves_under_high_contrast_with_a_five_key_palette(
    palette: dict[str, str],
) -> None:
    failures: dict[str, str] = {}
    for name in TOKENS:
        try:
            value = resolve(name, high_contrast=True, palette=palette)
        except Exception as exc:  # the point is to name every failure
            failures[name] = f"{type(exc).__name__}: {exc}"
            continue
        if not isinstance(value, str):
            failures[name] = f"returned {type(value).__name__} {value!r}, not str"
    assert failures == {}


# --- AC-8: dimming stops under a contrast theme -------------------------------------


def test_ac8_dim_opacity_is_the_string_one_point_zero_under_high_contrast() -> None:
    for palette in ({}, DESIGNER_PALETTE):
        value = resolve(DIM, high_contrast=True, palette=palette)
        assert type(value) is str
        assert value == "1.0"
        assert value == str(HC_OVERRIDE[DIM])


def test_ac8_dim_opacity_override_does_not_read_the_palette() -> None:
    assert resolve(DIM, high_contrast=True, palette=ExplodingPalette()) == "1.0"


def test_ac8_dim_opacity_is_the_authored_string_without_high_contrast() -> None:
    value = resolve(DIM, high_contrast=False, palette=DESIGNER_PALETTE)
    assert type(value) is str
    assert value == "0.55"
    assert value == TOKENS[DIM]


@pytest.mark.parametrize("name", sorted(HC_OVERRIDE))
def test_ac8_every_override_wins_under_high_contrast_as_a_string(name: str) -> None:
    assert resolve(name, high_contrast=True, palette=DESIGNER_PALETTE) == str(HC_OVERRIDE[name])


# --- AC-9: resolve never synthesises a value ----------------------------------------


@pytest.mark.parametrize(
    "palette", [DESIGNER_PALETTE, DISTINCT_PALETTE], ids=["designer", "distinct"]
)
def test_ac9_every_value_under_high_contrast_comes_from_the_palette_tokens_or_the_override(
    palette: dict[str, str],
) -> None:
    allowed = set(palette.values()) | set(TOKENS.values())
    synthesised: dict[str, str] = {}
    for name in TOKENS:
        value = resolve(name, high_contrast=True, palette=palette)
        if name in HC_OVERRIDE:
            if value != str(HC_OVERRIDE[name]):
                synthesised[name] = value
        elif value not in allowed:
            synthesised[name] = value
    assert synthesised == {}


# --- AC-10: the designer's assertable -----------------------------------------------


def test_ac10_the_derived_artwork_exemptions_are_exactly_the_static_entries_of_the_role_map() -> (
    None
):
    """The data and the mechanical derivation pin each other (Contract block 5, as amended).

    `ARTWORK_EXEMPT` also holds the eight non-colour `overlay.*` tokens (stroke
    widths, badge sizes), which the generator never maps; they are the third
    exempt group of 4.2, so the derived set restricted to the role map's keys is
    what must equal the `@static` entries, and the remainder must be unmapped.
    """
    assert DIM not in ARTWORK_EXEMPT
    assert CANVAS_EXEMPT <= ARTWORK_EXEMPT
    assert ARTWORK_EXEMPT & set(HC_PALETTE_ROLE) == set(STATIC_TOKENS)
    assert ARTWORK_EXEMPT - set(HC_PALETTE_ROLE) <= set(UNMAPPED_TOKENS)
    assert sorted(ARTWORK_EXEMPT - set(HC_PALETTE_ROLE)) == [
        "overlay.badge.gap",
        "overlay.badge.leader-width",
        "overlay.badge.size",
        "overlay.stroke.core-error",
        "overlay.stroke.core-hover",
        "overlay.stroke.core-idle",
        "overlay.stroke.core-selected",
        "overlay.stroke.halo",
    ]


def test_ac10_every_non_exempt_colour_token_resolves_to_one_of_the_designers_five_values() -> None:
    assert len(NON_EXEMPT_COLOUR_TOKENS) == 30
    five = set(DESIGNER_PALETTE.values())
    off_palette = {
        name: value
        for name in NON_EXEMPT_COLOUR_TOKENS
        if (value := resolve(name, high_contrast=True, palette=DESIGNER_PALETTE)) not in five
    }
    assert off_palette == {}


@pytest.mark.parametrize("name", sorted(ARTWORK_EXEMPT))
def test_ac10_every_overlay_and_canvas_exempt_token_is_byte_for_byte_authored_under_high_contrast(
    name: str,
) -> None:
    assert resolve(name, high_contrast=True, palette=DESIGNER_PALETTE) == TOKENS[name]
