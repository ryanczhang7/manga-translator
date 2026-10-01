"""MT-025: design tokens generate a QSS sheet and a Python module.

The generator (`mangatl.ui.tokens`) is a pure function from `tokens.toml` plus two
QSS templates to four committed artefacts. It has no Qt, so nothing here uses
qtbot.

Two kinds of oracle are used, and they are kept apart on purpose:

* **Settled numbers** from the story's C-9 (126 tokens, 40 colour tokens, 100
  orphans, 25 tokens referenced by the base template) are read out as constants.
  They are not re-derived from the generator's own output.
* **An independent reading** of the source - `tomllib` plus a flatten written
  here - is what the key sets are compared against, so that a generator that
  flattens `[hc]` into tokens cannot agree with itself and pass (MT-025 AC-11).

AC-5 and AC-7 are the load-bearing drift checks: AC-5 regenerates into a
temporary directory and compares BYTES with the committed files; AC-7 reads the
two committed artefacts against each other, not each against the TOML.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from mangatl.ui import tokens as gen
from mangatl.ui.tokens import (
    GenerationReport,
    MalformedToken,
    MissingHighContrastMapping,
    OverrideTemplateViolation,
    TokenError,
    UnresolvedPlaceholder,
)

REPO = Path(__file__).resolve().parents[2]
DESIGN = REPO / "docs" / "wiki" / "design"
SOURCE = DESIGN / "tokens.toml"
BASE_IN = DESIGN / "theme.qss.in"
HC_IN = DESIGN / "theme_hc.qss.in"
COMMITTED = REPO / "src" / "mangatl" / "ui"

# C-2: the four artefacts, in the order GenerationReport.written lists them.
ARTEFACTS = ("theme.qss", "tokens_gen.py", "theme.qss.tmpl", "theme_hc.qss.tmpl")
ROLES = ("Window", "WindowText", "Highlight", "HighlightedText", "DisabledText")
DATA_NAMES = ("TOKENS", "HC_PALETTE_ROLE", "HC_OVERRIDE")

# C-9, measured by lead-po on 2026-09-28 and re-measured in RED with a separate
# parser. Read out, not re-derived.
TOKEN_COUNT = 126
COLOUR_TOKEN_COUNT = 40
# MT-061 RED: the Lead Designer's components.md section 2 and section 5 rules in
# theme.qss.in reference 14 more tokens (25 -> 39), so 13 fewer are orphans
# (100 -> 87; `border-width.emphasis` was already the HC template's). Re-measured
# with a separate parser - tomllib, the placeholder regex, comments stripped -
# which also reproduces MT-025's 25 and 100 from theme.qss.in before MT-061.
# MT-059 RED: the Lead Designer's `QPushButton[variant="primary"]` rules (story
# D-1, components.md section 1) reference three tokens neither template used -
# `color.accent.hover`, `color.accent.pressed`, `color.text.on-accent` - so 39 ->
# 42 and 87 -> 84. Re-measured in RED: `load_tokens` plus the placeholder regex
# over theme.qss.in and theme_hc.qss.in gives 39/87 today and 42/84 with D-1's
# four rules appended (accent.base, focus.width, focus.ring already counted).
ORPHAN_COUNT = 84
BASE_REFERENCED_COUNT = 42

PLACEHOLDER = re.compile(r"@\{([^}]+)\}")

# ---------------------------------------------------------------------------
# A small, complete source document. Every test that needs a broken document
# derives it from this one by a single checked edit, so the only thing wrong
# with it is the thing the test is about.
# ---------------------------------------------------------------------------

MINI_TOML = """\
[meta]
schema = 1
theme = "dark"
version = "1.0.0"

[color.surface]
base   = "#1C1C1C"
raised = "#262626"

[overlay]
halo = "#0B0B0B"

[overlay.stroke]
halo = 2

[overlay.dim]
opacity = 0.55

[type.family]
ui = "Noto Sans, sans-serif"

[space]
s2 = 8

[border-width]
emphasis = 2

[typeset]
hyphenate = false

[elevation.e0]
surface = "color.surface.base"

[hc]
roles = ["Window", "WindowText", "Highlight", "HighlightedText", "DisabledText"]
static-sentinel = "@static"

[hc.map]
"color.surface.base"   = "Window"
"color.surface.raised" = "Window"
"overlay.halo"         = "@static"

[hc.override]
"overlay.dim.opacity" = 1.0
"""

MINI_TOKEN_ORDER = (
    "color.surface.base",
    "color.surface.raised",
    "overlay.halo",
    "overlay.stroke.halo",
    "overlay.dim.opacity",
    "type.family.ui",
    "space.s2",
    "border-width.emphasis",
    "typeset.hyphenate",
    "elevation.e0.surface",
)

# Referenced by neither template; `border-width.emphasis` is referenced by the
# override template only and is therefore NOT an orphan (C-7: "neither").
MINI_ORPHANS = (
    "elevation.e0.surface",
    "overlay.dim.opacity",
    "overlay.halo",
    "overlay.stroke.halo",
    "typeset.hyphenate",
)

MINI_BASE = """\
/* base fixture: a comment { with braces } is not a rule */
QWidget {
    background-color: @{color.surface.base};
    padding: @{space.s2}px @{space.s2}px;
}

QPushButton:hover, QLineEdit {
    background-color: @{color.surface.raised};
    font-family: @{type.family.ui};
}
"""

MINI_BASE_RENDERED = """\
/* base fixture: a comment { with braces } is not a rule */
QWidget {
    background-color: #1C1C1C;
    padding: 8px 8px;
}

QPushButton:hover, QLineEdit {
    background-color: #262626;
    font-family: Noto Sans, sans-serif;
}
"""

MINI_HC = """\
/* hc fixture */
QWidget {
    border: @{border-width.emphasis}px solid @{hc.WindowText};
}

QLineEdit {
    color: @{hc.HighlightedText};
}
"""


# ---------------------------------------------------------------------------
# Helpers - all independent of the module under test.
# ---------------------------------------------------------------------------


def _edit(text: str, old: str, new: str) -> str:
    """One checked edit: a fixture edit that matches nothing is a test bug."""
    assert text.count(old) == 1, f"fixture edit {old!r} does not match exactly once"
    return text.replace(old, new)


def _world(
    tmp_path: Path,
    toml: str = MINI_TOML,
    base: str = MINI_BASE,
    hc: str = MINI_HC,
) -> tuple[Path, Path, Path, Path]:
    """Write the three inputs as UTF-8 with LF endings; return them and an empty out dir."""
    inputs = tmp_path / "in"
    inputs.mkdir()
    source = inputs / "tokens.toml"
    base_path = inputs / "theme.qss.in"
    hc_path = inputs / "theme_hc.qss.in"
    source.write_bytes(toml.encode("utf-8"))
    base_path.write_bytes(base.encode("utf-8"))
    hc_path.write_bytes(hc.encode("utf-8"))
    out = tmp_path / "out"
    out.mkdir()
    return source, base_path, hc_path, out


def _seed_out_dir(out: Path) -> None:
    """Pre-existing artefacts, so 'writes nothing' can be told from 'rewrote the same'."""
    for name in ARTEFACTS:
        (out / name).write_bytes(f"previous {name}\n".encode())
    (out / "unrelated.txt").write_bytes(b"left alone\n")


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _independent_tokens(path: Path) -> dict[str, object]:
    """Flatten the TOML depth-first, dropping every key under [hc] and [meta]."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    flat: dict[str, object] = {}

    def walk(table: dict[str, object], prefix: str) -> None:
        for key, value in table.items():
            name = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                walk(value, name)
            else:
                flat[name] = value

    walk(document, "")
    return {k: v for k, v in flat.items() if k.split(".")[0] not in ("hc", "meta")}


def _independent_hc(path: Path) -> dict[str, object]:
    hc = tomllib.loads(path.read_text(encoding="utf-8"))["hc"]
    assert isinstance(hc, dict)
    return hc


def _text(value: object) -> str:
    """C-3, restated independently of `token_text`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _constant(dotted: str) -> str:
    return dotted.upper().replace(".", "_").replace("-", "_")


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _placeholder_values(template: str, rendered: str) -> list[tuple[str, str]]:
    """Locate every placeholder of `template` inside `rendered`.

    Literal template text is escaped, each `@{name}` becomes a capture group, and
    the whole must match. Returns (token name, the text that stands in its place).
    """
    names: list[str] = []
    parts: list[str] = []
    position = 0
    for match in PLACEHOLDER.finditer(template):
        parts.append(re.escape(template[position : match.start()]))
        parts.append(r"([^\n]*?)")
        names.append(match.group(1))
        position = match.end()
    parts.append(re.escape(template[position:]))
    matched = re.fullmatch("".join(parts), rendered, flags=re.DOTALL)
    assert matched is not None, "theme.qss does not have the shape of theme.qss.tmpl"
    return list(zip(names, matched.groups(), strict=True))


def _assigned_names(module_source: str) -> list[str]:
    names: list[str] = []
    for node in ast.parse(module_source).body:
        if isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def _generate_real(out: Path) -> GenerationReport:
    return gen.generate(SOURCE, BASE_IN, HC_IN, out)


@pytest.fixture
def fresh(tmp_path: Path) -> Path:
    """The four artefacts regenerated from the committed sources into a temp dir."""
    out = tmp_path / "fresh"
    out.mkdir()
    _generate_real(out)
    return out


@pytest.fixture
def committed_tokens_gen() -> ModuleType:
    return importlib.import_module("mangatl.ui.tokens_gen")


# ===========================================================================
# C-1: the module's fixed names
# ===========================================================================


def test_the_generator_reads_the_design_sources_and_writes_into_the_ui_package() -> None:
    assert gen.TOKENS_SOURCE == SOURCE
    assert gen.BASE_TEMPLATE_SOURCE == BASE_IN
    assert gen.HC_TEMPLATE_SOURCE == HC_IN
    assert gen.PACKAGE_DIR == COMMITTED


def test_the_high_contrast_vocabulary_is_five_roles_and_the_static_sentinel() -> None:
    assert frozenset(ROLES) == gen.HC_ROLES
    assert gen.STATIC == "@static"
    assert frozenset({"hc", "meta"}) == gen.EXCLUDED_SECTIONS


def test_every_generator_failure_is_a_token_error() -> None:
    for error in (
        MalformedToken,
        UnresolvedPlaceholder,
        MissingHighContrastMapping,
        OverrideTemplateViolation,
    ):
        assert issubclass(error, TokenError)
    assert issubclass(TokenError, Exception)


# ===========================================================================
# AC-1 / C-2: four artefacts written
# ===========================================================================


def test_generation_writes_the_four_artefacts_and_reports_them_in_contract_order(
    tmp_path: Path,
) -> None:
    source, base, hc, out = _world(tmp_path)

    report = gen.generate(source, base, hc, out)

    assert report.written == tuple(out / name for name in ARTEFACTS)
    assert sorted(_snapshot(out)) == sorted(ARTEFACTS)


def test_generating_from_the_committed_sources_emits_theme_qss_and_tokens_gen(
    fresh: Path,
) -> None:
    assert (fresh / "theme.qss").is_file()
    assert (fresh / "tokens_gen.py").is_file()


def test_generation_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    _generate_real(first)
    _generate_real(second)

    assert _snapshot(first) == _snapshot(second)


# ===========================================================================
# AC-5: the committed artefacts are exactly what regeneration produces
# ===========================================================================


@pytest.mark.parametrize("name", ARTEFACTS)
def test_the_committed_artefact_is_byte_identical_to_a_fresh_regeneration(
    fresh: Path, name: str
) -> None:
    committed = COMMITTED / name
    assert committed.is_file(), f"{name} is not committed under src/mangatl/ui"
    assert committed.read_bytes() == (fresh / name).read_bytes(), (
        f"src/mangatl/ui/{name} differs from what the generator emits - "
        "edited by hand, or not regenerated after tokens.toml or a template changed"
    )


# ===========================================================================
# C-6: LF and UTF-8 on every platform
# ===========================================================================


def test_every_generated_file_uses_lf_line_endings(fresh: Path) -> None:
    for name in ARTEFACTS:
        assert b"\r" not in (fresh / name).read_bytes(), f"{name} was written with CR bytes"


@pytest.mark.parametrize("name", ARTEFACTS)
def test_every_committed_artefact_uses_lf_line_endings(name: str) -> None:
    assert b"\r" not in (COMMITTED / name).read_bytes()


def test_non_ascii_token_text_is_written_as_utf8_on_every_platform(tmp_path: Path) -> None:
    family = "Noto Sans CJK \u65e5\u672c\u8a9e, sans-serif"
    toml = _edit(MINI_TOML, 'ui = "Noto Sans, sans-serif"', f'ui = "{family}"')
    source, base, hc, out = _world(tmp_path, toml=toml)

    gen.generate(source, base, hc, out)

    encoded = family.encode("utf-8")
    assert encoded in (out / "theme.qss").read_bytes()
    assert encoded in (out / "tokens_gen.py").read_bytes()
    module = _load_module(out / "tokens_gen.py", "mt025_utf8_tokens_gen")
    assert family == module.TYPE_FAMILY_UI


# ===========================================================================
# AC-2 / C-3: constant names and native values
# ===========================================================================


@pytest.mark.parametrize(
    ("dotted", "constant"),
    [
        ("color.overlay.bubble.selected", "COLOR_OVERLAY_BUBBLE_SELECTED"),
        ("color.canvas.surround", "COLOR_CANVAS_SURROUND"),
        ("color.text.on-accent", "COLOR_TEXT_ON_ACCENT"),
        ("border-width.hairline", "BORDER_WIDTH_HAIRLINE"),
        ("space.s12", "SPACE_S12"),
        ("typeset.font.bold-italic", "TYPESET_FONT_BOLD_ITALIC"),
    ],
)
def test_a_constant_name_is_the_dotted_path_uppercased_with_dots_and_hyphens_as_underscores(
    dotted: str, constant: str
) -> None:
    assert gen.to_constant_name(dotted) == constant


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("#1C1C1C", "#1C1C1C"),
        (
            "Segoe UI Variable Text, Segoe UI, sans-serif",
            "Segoe UI Variable Text, Segoe UI, sans-serif",
        ),
        (True, "true"),
        (False, "false"),
        (0, "0"),
        (999, "999"),
        (0.55, "0.55"),
        (1.0, "1.0"),
        (1.08, "1.08"),
    ],
)
def test_token_text_renders_booleans_lowercase_and_floats_by_repr(
    value: str | int | float | bool, text: str
) -> None:
    assert gen.token_text(value) == text


def test_every_committed_token_is_a_module_constant_carrying_its_native_toml_value(
    committed_tokens_gen: ModuleType,
) -> None:
    expected = _independent_tokens(SOURCE)
    assert len(expected) == TOKEN_COUNT

    missing = [n for n in expected if not hasattr(committed_tokens_gen, _constant(n))]
    assert missing == [], f"tokens with no constant in tokens_gen: {missing}"
    wrong = [
        (name, getattr(committed_tokens_gen, _constant(name)), value)
        for name, value in expected.items()
        if getattr(committed_tokens_gen, _constant(name)) != value
        or type(getattr(committed_tokens_gen, _constant(name))) is not type(value)
    ]
    assert wrong == [], f"constant value or type differs from tokens.toml: {wrong}"


def test_the_named_examples_carry_native_types(committed_tokens_gen: ModuleType) -> None:
    # AC-2's example path `color.overlay.bubble.selected` is illustrative: the
    # document's token is `overlay.bubble.selected`. The derivation itself is
    # pinned on the AC's own example by the to_constant_name cases above.
    assert committed_tokens_gen.OVERLAY_BUBBLE_SELECTED == "#4CC2FF"
    assert not hasattr(committed_tokens_gen, "COLOR_OVERLAY_BUBBLE_SELECTED")
    assert type(committed_tokens_gen.OVERLAY_DIM_OPACITY) is float
    assert committed_tokens_gen.OVERLAY_DIM_OPACITY == 0.55
    assert type(committed_tokens_gen.SPACE_S2) is int
    assert committed_tokens_gen.SPACE_S2 == 8
    assert committed_tokens_gen.TYPESET_HYPHENATE is False


def test_tokens_is_keyed_by_every_dotted_name_in_source_order_with_text_values(
    committed_tokens_gen: ModuleType,
) -> None:
    expected = _independent_tokens(SOURCE)
    assert list(committed_tokens_gen.TOKENS) == list(expected)
    assert {k: _text(v) for k, v in expected.items()} == committed_tokens_gen.TOKENS


def test_a_generated_module_from_a_fixture_exposes_every_token(tmp_path: Path) -> None:
    source, base, hc, out = _world(tmp_path)
    gen.generate(source, base, hc, out)

    module = _load_module(out / "tokens_gen.py", "mt025_fixture_tokens_gen")

    assert module.COLOR_SURFACE_BASE == "#1C1C1C"
    assert module.COLOR_SURFACE_RAISED == "#262626"
    assert module.OVERLAY_HALO == "#0B0B0B"
    assert type(module.OVERLAY_STROKE_HALO) is int
    assert module.OVERLAY_STROKE_HALO == 2
    assert type(module.OVERLAY_DIM_OPACITY) is float
    assert module.OVERLAY_DIM_OPACITY == 0.55
    assert module.TYPE_FAMILY_UI == "Noto Sans, sans-serif"
    assert module.SPACE_S2 == 8
    assert module.BORDER_WIDTH_EMPHASIS == 2
    assert module.TYPESET_HYPHENATE is False
    assert module.ELEVATION_E0_SURFACE == "color.surface.base"
    assert list(module.TOKENS) == list(MINI_TOKEN_ORDER)
    assert module.TOKENS["overlay.dim.opacity"] == "0.55"
    assert module.TOKENS["typeset.hyphenate"] == "false"
    assert module.TOKENS["space.s2"] == "8"


def test_render_python_returns_the_module_source_as_a_string() -> None:
    tokens = {"color.surface.base": "#1C1C1C", "space.s2": 8}
    source = gen.render_python(tokens, {"color.surface.base": "Window"}, {"space.s2": 12.0})

    namespace: dict[str, object] = {}
    exec(compile(source, "tokens_gen.py", "exec"), namespace)

    assert namespace["COLOR_SURFACE_BASE"] == "#1C1C1C"
    assert namespace["SPACE_S2"] == 8
    assert namespace["TOKENS"] == {"color.surface.base": "#1C1C1C", "space.s2": "8"}
    assert namespace["HC_PALETTE_ROLE"] == {"color.surface.base": "Window"}
    assert namespace["HC_OVERRIDE"] == {"space.s2": 12.0}


def test_load_tokens_returns_the_flattened_tokens_in_source_order() -> None:
    loaded = gen.load_tokens(SOURCE)

    assert len(loaded) == TOKEN_COUNT
    assert list(loaded) == list(_independent_tokens(SOURCE))
    assert loaded == _independent_tokens(SOURCE)


def test_the_committed_source_has_126_distinct_constant_names() -> None:
    names = {gen.to_constant_name(n) for n in gen.load_tokens(SOURCE)}
    assert len(names) == TOKEN_COUNT


# ===========================================================================
# Token-name grammar and constant-name injectivity (MalformedToken)
# ===========================================================================


def test_a_hyphen_in_the_first_segment_is_accepted(tmp_path: Path) -> None:
    """PO-4: `border-width.*` is in the real document, so the grammar must admit it."""
    source, base, hc, out = _world(tmp_path)
    gen.generate(source, base, hc, out)

    module = _load_module(out / "tokens_gen.py", "mt025_hyphen_tokens_gen")
    assert module.BORDER_WIDTH_EMPHASIS == 2


@pytest.mark.parametrize(
    ("section", "key", "bad_name"),
    [
        ("[space]", "S3 = 12", "space.S3"),
        ("[space]", "s_3 = 12", "space.s_3"),
        ("[space]", '"-s3" = 12', "space.-s3"),
    ],
)
def test_a_token_name_outside_the_grammar_is_malformed_and_named(
    tmp_path: Path, section: str, key: str, bad_name: str
) -> None:
    toml = _edit(MINI_TOML, f"{section}\ns2 = 8\n", f"{section}\ns2 = 8\n{key}\n")
    source, base, hc, out = _world(tmp_path, toml=toml)
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(MalformedToken) as raised:
        gen.generate(source, base, hc, out)

    assert bad_name in str(raised.value)
    assert _snapshot(out) == before


def test_a_first_segment_starting_with_a_digit_is_malformed(tmp_path: Path) -> None:
    source, base, hc, out = _world(tmp_path, toml=MINI_TOML + '\n[2x]\nwide = "w"\n')

    with pytest.raises(MalformedToken) as raised:
        gen.generate(source, base, hc, out)

    assert "2x.wide" in str(raised.value)


def test_a_later_segment_may_start_with_a_digit(tmp_path: Path) -> None:
    toml = MINI_TOML + "\n[motion.duration]\n2x = 360\n"
    source, base, hc, out = _world(tmp_path, toml=toml)

    gen.generate(source, base, hc, out)

    module = _load_module(out / "tokens_gen.py", "mt025_digit_tokens_gen")
    assert module.MOTION_DURATION_2X == 360


def test_two_tokens_colliding_on_one_constant_name_are_malformed_not_last_writer_wins(
    tmp_path: Path,
) -> None:
    # A hyphen against a dot: `radius.pill-x` and `radius.pill.x` both give RADIUS_PILL_X.
    toml = MINI_TOML + '\n[radius]\n"pill-x" = 999\n\n[radius.pill]\nx = 998\n'
    source, base, hc, out = _world(tmp_path, toml=toml)
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(MalformedToken) as raised:
        gen.generate(source, base, hc, out)

    message = str(raised.value)
    assert "radius.pill-x" in message
    assert "radius.pill.x" in message
    assert _snapshot(out) == before


# ===========================================================================
# C-4 / AC-6: colour tokens and malformed colour values
# ===========================================================================


@pytest.mark.parametrize(
    ("dotted", "value", "is_colour"),
    [
        ("color.surface.base", "#1C1C1C", True),
        ("overlay.halo", "#0B0B0B", True),
        ("overlay.fill.hover", "#4CC2FF1A", True),
        ("overlay.stroke.halo", 2, False),
        ("overlay.dim.opacity", 0.55, False),
        ("elevation.e0.surface", "color.surface.base", False),
        ("typeset.font.family", "Shantell Sans", False),
        ("colorful.accent", "#FFFFFF", False),
        ("overlays.halo", "#FFFFFF", False),
        ("color.flag", True, False),
    ],
)
def test_a_colour_token_is_a_string_under_color_or_overlay(
    dotted: str, value: str | int | float | bool, is_colour: bool
) -> None:
    assert gen.is_colour_token(dotted, value) is is_colour


def test_the_committed_source_has_forty_colour_tokens_exactly_the_hc_map_keys() -> None:
    colours = [n for n, v in gen.load_tokens(SOURCE).items() if gen.is_colour_token(n, v)]
    hc_map = _independent_hc(SOURCE)["map"]
    assert isinstance(hc_map, dict)

    assert len(colours) == COLOUR_TOKEN_COUNT
    assert len(hc_map) == COLOUR_TOKEN_COUNT
    assert set(colours) == set(hc_map)


@pytest.mark.parametrize(
    ("token_line", "bad_line", "token", "value"),
    [
        ('raised = "#262626"', 'raised = "#26262G"', "color.surface.raised", "#26262G"),
        ('raised = "#262626"', 'raised = "#26262"', "color.surface.raised", "#26262"),
        ('raised = "#262626"', 'raised = "262626"', "color.surface.raised", "262626"),
        ('raised = "#262626"', 'raised = "#2626262"', "color.surface.raised", "#2626262"),
        ('raised = "#262626"', 'raised = "#262626FF0"', "color.surface.raised", "#262626FF0"),
        ('raised = "#262626"', 'raised = "grey"', "color.surface.raised", "grey"),
        ('halo = "#0B0B0B"', 'halo = "#0B0B0B "', "overlay.halo", "#0B0B0B "),
    ],
)
def test_a_malformed_colour_fails_naming_the_token_and_the_value_and_writes_nothing(
    tmp_path: Path, token_line: str, bad_line: str, token: str, value: str
) -> None:
    source, base, hc, out = _world(tmp_path, toml=_edit(MINI_TOML, token_line, bad_line))
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(MalformedToken) as raised:
        gen.generate(source, base, hc, out)

    message = str(raised.value)
    assert token in message
    assert value in message
    assert _snapshot(out) == before


@pytest.mark.parametrize("value", ["#1c1c1c", "#AbCdEf", "#4CC2FF1A", "#00000000"])
def test_six_and_eight_digit_hex_in_either_case_is_a_valid_colour(
    tmp_path: Path, value: str
) -> None:
    toml = _edit(MINI_TOML, 'raised = "#262626"', f'raised = "{value}"')
    source, base, hc, out = _world(tmp_path, toml=toml)

    gen.generate(source, base, hc, out)

    assert f"background-color: {value};".encode() in (out / "theme.qss").read_bytes()


def test_a_non_colour_string_token_is_not_validated_as_a_colour(tmp_path: Path) -> None:
    toml = _edit(MINI_TOML, 'surface = "color.surface.base"', 'surface = "not a #colour at all"')
    source, base, hc, out = _world(tmp_path, toml=toml)

    gen.generate(source, base, hc, out)

    module = _load_module(out / "tokens_gen.py", "mt025_noncolour_tokens_gen")
    assert module.ELEVATION_E0_SURFACE == "not a #colour at all"


def test_main_exits_non_zero_and_prints_the_malformed_token_and_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    toml = _edit(MINI_TOML, 'raised = "#262626"', 'raised = "#26262G"')
    source, base, hc, out = _world(tmp_path, toml=toml)
    _seed_out_dir(out)
    before = _snapshot(out)

    code = gen.main(_argv(source, base, hc, out))

    assert code != 0
    err = capsys.readouterr().err
    assert "color.surface.raised" in err
    assert "#26262G" in err
    assert _snapshot(out) == before


# ===========================================================================
# AC-3 / C-8: placeholders
# ===========================================================================


def test_render_qss_substitutes_every_placeholder_with_the_token_text() -> None:
    tokens = {"space.s2": 8, "color.surface.base": "#1C1C1C", "overlay.dim.opacity": 0.55}
    template = (
        "a: @{space.s2}px @{space.s2}px;\nb: @{color.surface.base};\nc: @{overlay.dim.opacity};"
    )

    assert gen.render_qss(tokens, template) == "a: 8px 8px;\nb: #1C1C1C;\nc: 0.55;"


def test_render_qss_leaves_a_template_without_placeholders_unchanged() -> None:
    assert gen.render_qss({}, "") == ""
    assert gen.render_qss({}, "QWidget { color: red; }\n") == "QWidget { color: red; }\n"


def test_an_unresolved_placeholder_is_an_error_naming_it_not_an_empty_string() -> None:
    with pytest.raises(UnresolvedPlaceholder) as raised:
        gen.render_qss({"space.s2": 8}, "QWidget { padding: @{space.s9}px; }")

    assert "space.s9" in str(raised.value)


def test_generation_refuses_a_base_template_naming_an_undefined_token(tmp_path: Path) -> None:
    base = _edit(MINI_BASE, "@{color.surface.raised}", "@{color.surface.missing}")
    source, base_path, hc, out = _world(tmp_path, base=base)
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(UnresolvedPlaceholder) as raised:
        gen.generate(source, base_path, hc, out)

    assert "color.surface.missing" in str(raised.value)
    assert _snapshot(out) == before


def test_a_high_contrast_role_placeholder_in_the_base_template_is_unresolved(
    tmp_path: Path,
) -> None:
    base = _edit(MINI_BASE, "@{color.surface.raised}", "@{hc.Window}")
    source, base_path, hc, out = _world(tmp_path, base=base)

    with pytest.raises(UnresolvedPlaceholder) as raised:
        gen.generate(source, base_path, hc, out)

    assert "hc.Window" in str(raised.value)


def test_generation_refuses_an_override_template_naming_an_undefined_token(
    tmp_path: Path,
) -> None:
    hc = _edit(MINI_HC, "@{border-width.emphasis}", "@{border-width.heavy}")
    source, base, hc_path, out = _world(tmp_path, hc=hc)
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(UnresolvedPlaceholder) as raised:
        gen.generate(source, base, hc_path, out)

    assert "border-width.heavy" in str(raised.value)
    assert _snapshot(out) == before


def test_the_generated_sheet_contains_no_placeholder(fresh: Path) -> None:
    assert "@{" not in (fresh / "theme.qss").read_text(encoding="utf-8")


def test_the_committed_sheet_contains_no_placeholder() -> None:
    assert "@{" not in (COMMITTED / "theme.qss").read_text(encoding="utf-8")


# ===========================================================================
# AC-8: theme.qss is the base template rendered, with nothing from HC
# ===========================================================================


def test_the_fixture_sheet_is_exactly_the_base_template_rendered(tmp_path: Path) -> None:
    source, base, hc, out = _world(tmp_path)

    gen.generate(source, base, hc, out)

    assert (out / "theme.qss").read_bytes() == MINI_BASE_RENDERED.encode("utf-8")


def test_the_sheet_carries_no_high_contrast_placeholder_and_no_override_rule(
    tmp_path: Path,
) -> None:
    source, base, hc, out = _world(tmp_path)

    gen.generate(source, base, hc, out)

    sheet = (out / "theme.qss").read_text(encoding="utf-8")
    assert "@{hc." not in sheet
    assert "hc fixture" not in sheet  # the override template's comment
    assert "solid" not in sheet  # the override template's only border declaration


def test_the_real_sheet_is_the_base_template_rendered_with_the_authored_values(
    fresh: Path,
) -> None:
    tokens = _independent_tokens(SOURCE)
    expected = PLACEHOLDER.sub(
        lambda m: _text(tokens[m.group(1)]), BASE_IN.read_text(encoding="utf-8")
    )

    sheet = (fresh / "theme.qss").read_text(encoding="utf-8")

    assert sheet == expected
    assert sheet == gen.render_qss(gen.load_tokens(SOURCE), BASE_IN.read_text(encoding="utf-8"))
    assert "@{hc." not in sheet


def test_both_templates_are_copied_into_the_package_verbatim(fresh: Path) -> None:
    assert (fresh / "theme.qss.tmpl").read_bytes() == BASE_IN.read_bytes()
    assert (fresh / "theme_hc.qss.tmpl").read_bytes() == HC_IN.read_bytes()


def test_the_committed_templates_are_verbatim_copies_of_the_design_inputs() -> None:
    assert (COMMITTED / "theme.qss.tmpl").read_bytes() == BASE_IN.read_bytes()
    assert (COMMITTED / "theme_hc.qss.tmpl").read_bytes() == HC_IN.read_bytes()


def test_fixture_templates_are_copied_byte_for_byte(tmp_path: Path) -> None:
    source, base, hc, out = _world(tmp_path)

    gen.generate(source, base, hc, out)

    assert (out / "theme.qss.tmpl").read_bytes() == MINI_BASE.encode("utf-8")
    assert (out / "theme_hc.qss.tmpl").read_bytes() == MINI_HC.encode("utf-8")


# ===========================================================================
# AC-7: the two committed artefacts agree with each other
# ===========================================================================


def test_every_value_in_the_committed_sheet_equals_the_committed_tokens_entry(
    committed_tokens_gen: ModuleType,
) -> None:
    template = (COMMITTED / "theme.qss.tmpl").read_text(encoding="utf-8")
    sheet = (COMMITTED / "theme.qss").read_text(encoding="utf-8")

    pairs = _placeholder_values(template, sheet)

    assert len({name for name, _ in pairs}) == BASE_REFERENCED_COUNT
    drift = [
        (name, in_sheet, committed_tokens_gen.TOKENS.get(name))
        for name, in_sheet in pairs
        if committed_tokens_gen.TOKENS.get(name) != in_sheet
    ]
    assert drift == [], f"theme.qss and tokens_gen.TOKENS disagree (token, qss, py): {drift}"


def test_every_value_in_the_committed_sheet_equals_the_committed_constant(
    committed_tokens_gen: ModuleType,
) -> None:
    template = (COMMITTED / "theme.qss.tmpl").read_text(encoding="utf-8")
    sheet = (COMMITTED / "theme.qss").read_text(encoding="utf-8")

    drift = [
        (name, in_sheet, getattr(committed_tokens_gen, _constant(name), None))
        for name, in_sheet in _placeholder_values(template, sheet)
        if _text(getattr(committed_tokens_gen, _constant(name), None)) != in_sheet
    ]
    assert drift == [], f"theme.qss and the tokens_gen constants disagree: {drift}"


def test_a_freshly_generated_sheet_and_module_agree_with_each_other(fresh: Path) -> None:
    module = _load_module(fresh / "tokens_gen.py", "mt025_fresh_tokens_gen")
    template = (fresh / "theme.qss.tmpl").read_text(encoding="utf-8")
    sheet = (fresh / "theme.qss").read_text(encoding="utf-8")

    drift = [
        (name, in_sheet, module.TOKENS.get(name))
        for name, in_sheet in _placeholder_values(template, sheet)
        if module.TOKENS.get(name) != in_sheet
    ]
    assert drift == []


# ===========================================================================
# AC-9: TOKENS, HC_PALETTE_ROLE, HC_OVERRIDE
# ===========================================================================


def test_the_module_declares_its_three_tables_with_their_contract_types(fresh: Path) -> None:
    tree = ast.parse((fresh / "tokens_gen.py").read_text(encoding="utf-8"))
    annotations = {
        node.target.id: ast.unparse(node.annotation)
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    assert annotations.get("TOKENS") == "dict[str, str]"
    assert annotations.get("HC_PALETTE_ROLE") == "dict[str, str]"
    assert annotations.get("HC_OVERRIDE") == "dict[str, str | float]"


def test_hc_palette_role_is_the_hc_map_in_source_order(committed_tokens_gen: ModuleType) -> None:
    hc_map = _independent_hc(SOURCE)["map"]
    assert isinstance(hc_map, dict)

    assert list(committed_tokens_gen.HC_PALETTE_ROLE) == list(hc_map)
    assert hc_map == committed_tokens_gen.HC_PALETTE_ROLE
    allowed = {*ROLES, "@static"}
    assert set(committed_tokens_gen.HC_PALETTE_ROLE.values()) <= allowed


def test_hc_override_is_the_override_table_and_every_key_is_a_token(
    committed_tokens_gen: ModuleType,
) -> None:
    assert committed_tokens_gen.HC_OVERRIDE == {"overlay.dim.opacity": 1.0}
    assert type(committed_tokens_gen.HC_OVERRIDE["overlay.dim.opacity"]) is float
    assert set(committed_tokens_gen.HC_OVERRIDE) <= set(committed_tokens_gen.TOKENS)


def test_every_tokens_key_and_value_is_a_string(committed_tokens_gen: ModuleType) -> None:
    items = committed_tokens_gen.TOKENS.items()
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in items)


def test_the_fixture_module_carries_the_fixture_high_contrast_tables(tmp_path: Path) -> None:
    source, base, hc, out = _world(tmp_path)
    gen.generate(source, base, hc, out)

    module = _load_module(out / "tokens_gen.py", "mt025_hc_tokens_gen")

    assert module.HC_PALETTE_ROLE == {
        "color.surface.base": "Window",
        "color.surface.raised": "Window",
        "overlay.halo": "@static",
    }
    assert module.HC_OVERRIDE == {"overlay.dim.opacity": 1.0}


def test_load_hc_returns_the_map_the_overrides_and_the_roles() -> None:
    hc_map, hc_override, roles = gen.load_hc(SOURCE)
    expected = _independent_hc(SOURCE)

    assert hc_map == expected["map"]
    assert len(hc_map) == COLOUR_TOKEN_COUNT
    assert hc_override == {"overlay.dim.opacity": 1.0}
    assert list(roles) == list(ROLES)


def test_an_override_naming_no_token_is_a_violation_naming_it_and_writes_nothing(
    tmp_path: Path,
) -> None:
    toml = _edit(
        MINI_TOML, '"overlay.dim.opacity" = 1.0', '"overlay.dim.opacity" = 1.0\n"space.s9" = 3'
    )
    source, base, hc, out = _world(tmp_path, toml=toml)
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(OverrideTemplateViolation) as raised:
        gen.generate(source, base, hc, out)

    assert "space.s9" in str(raised.value)
    assert _snapshot(out) == before


# ===========================================================================
# AC-10: [hc.map] must be total over colour tokens
# ===========================================================================


@pytest.mark.parametrize(
    ("map_line", "token"),
    [
        ('"color.surface.raised" = "Window"\n', "color.surface.raised"),
        ('"overlay.halo"         = "@static"\n', "overlay.halo"),
    ],
)
def test_a_colour_token_with_no_high_contrast_mapping_fails_naming_it_and_writes_nothing(
    tmp_path: Path, map_line: str, token: str
) -> None:
    source, base, hc, out = _world(tmp_path, toml=_edit(MINI_TOML, map_line, ""))
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(MissingHighContrastMapping) as raised:
        gen.generate(source, base, hc, out)

    assert token in str(raised.value)
    assert _snapshot(out) == before


def test_a_newly_added_colour_without_a_mapping_fails_rather_than_defaulting(
    tmp_path: Path,
) -> None:
    toml = _edit(MINI_TOML, 'raised = "#262626"', 'raised = "#262626"\nsunken = "#141414"')
    source, base, hc, out = _world(tmp_path, toml=toml)

    with pytest.raises(MissingHighContrastMapping) as raised:
        gen.generate(source, base, hc, out)

    assert "color.surface.sunken" in str(raised.value)


def test_non_colour_tokens_need_no_high_contrast_mapping(tmp_path: Path) -> None:
    # The fixture maps only its three colour tokens; the integer stroke, the
    # float opacity and the string `elevation.e0.surface` have no entry.
    source, base, hc, out = _world(tmp_path)

    report = gen.generate(source, base, hc, out)

    assert len(report.written) == len(ARTEFACTS)


def test_main_exits_non_zero_on_a_missing_mapping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    toml = _edit(MINI_TOML, '"color.surface.raised" = "Window"\n', "")
    source, base, hc, out = _world(tmp_path, toml=toml)

    code = gen.main(_argv(source, base, hc, out))

    assert code != 0
    assert "color.surface.raised" in capsys.readouterr().err
    assert _snapshot(out) == {}


# ===========================================================================
# AC-11: [hc] and [meta] are not tokens
# ===========================================================================


def test_no_hc_or_meta_key_is_a_token_in_the_committed_module(
    committed_tokens_gen: ModuleType,
) -> None:
    leaked = [k for k in committed_tokens_gen.TOKENS if k.split(".")[0] in ("hc", "meta")]
    assert leaked == []
    assert "hc.map.color.surface.base" not in committed_tokens_gen.TOKENS
    assert "meta.schema" not in committed_tokens_gen.TOKENS
    constants = [
        name
        for name in vars(committed_tokens_gen)
        if name.startswith(("HC_MAP_", "HC_OVERRIDE_", "HC_ROLES", "HC_STATIC", "META_"))
    ]
    assert constants == []


def test_the_module_defines_exactly_one_constant_per_token_plus_the_three_tables(
    fresh: Path,
) -> None:
    names = _assigned_names((fresh / "tokens_gen.py").read_text(encoding="utf-8"))
    expected = [_constant(n) for n in _independent_tokens(SOURCE)]

    assert names == [*expected, *DATA_NAMES]


def test_load_tokens_excludes_every_hc_and_meta_key(tmp_path: Path) -> None:
    source, _, _, _ = _world(tmp_path)

    loaded = gen.load_tokens(source)

    assert list(loaded) == list(MINI_TOKEN_ORDER)


def test_hc_and_meta_keys_are_never_reported_as_orphans(tmp_path: Path) -> None:
    source, base, hc, out = _world(tmp_path)

    report = gen.generate(source, base, hc, out)

    assert [o for o in report.orphans if o.split(".")[0] in ("hc", "meta")] == []


def test_a_section_merely_starting_with_hc_or_meta_is_still_tokens(tmp_path: Path) -> None:
    toml = MINI_TOML + '\n[metadata]\nnote = "kept"\n\n[hcx]\nnote = "kept"\n'
    source, _, _, _ = _world(tmp_path, toml=toml)

    loaded = gen.load_tokens(source)

    assert loaded["metadata.note"] == "kept"
    assert loaded["hcx.note"] == "kept"


# ===========================================================================
# AC-4 / C-7: orphans are reported, never fatal
# ===========================================================================


def test_tokens_referenced_by_neither_template_are_reported_as_sorted_orphans(
    tmp_path: Path,
) -> None:
    source, base, hc, out = _world(tmp_path)

    report = gen.generate(source, base, hc, out)

    assert report.orphans == MINI_ORPHANS


def test_the_committed_source_reports_its_hundred_orphans(tmp_path: Path) -> None:
    report = _generate_real(tmp_path)

    assert len(report.orphans) == ORPHAN_COUNT
    assert list(report.orphans) == sorted(report.orphans)
    tokens = _independent_tokens(SOURCE)
    painted = [n for n in tokens if n.split(".")[0] in ("overlay", "typeset")]
    assert [n for n in painted if n not in report.orphans] == []
    assert "border-width.emphasis" not in report.orphans  # override template only
    assert "color.surface.base" not in report.orphans


def test_an_orphan_is_still_written_to_the_module(tmp_path: Path) -> None:
    source, base, hc, out = _world(tmp_path)
    gen.generate(source, base, hc, out)

    module = _load_module(out / "tokens_gen.py", "mt025_orphan_tokens_gen")

    assert module.OVERLAY_STROKE_HALO == 2
    assert "overlay.stroke.halo" in module.TOKENS


def test_no_orphans_when_every_token_is_referenced(tmp_path: Path) -> None:
    base = MINI_BASE + (
        "\nQLabel {\n"
        "    color: @{overlay.halo};\n"
        "    width: @{overlay.stroke.halo}px;\n"
        "    opacity: @{overlay.dim.opacity};\n"
        "    hyphens: @{typeset.hyphenate};\n"
        "    background: @{elevation.e0.surface};\n"
        "}\n"
    )
    source, base_path, hc, out = _world(tmp_path, base=base)

    report = gen.generate(source, base_path, hc, out)

    assert report.orphans == ()


def test_main_prints_each_orphan_on_its_own_stderr_line_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, base, hc, out = _world(tmp_path)

    code = gen.main(_argv(source, base, hc, out))

    assert code == 0
    lines = capsys.readouterr().err.splitlines()
    for orphan in MINI_ORPHANS:
        exact = re.compile(rf"(?<![\w.-]){re.escape(orphan)}(?![\w.-])")
        carrying = [line for line in lines if exact.search(line)]
        assert len(carrying) == 1, f"{orphan} should be on exactly one stderr line: {lines}"
    orphan_lines = {line for line in lines for o in MINI_ORPHANS if o in line}
    assert len(orphan_lines) == len(MINI_ORPHANS)
    assert sorted(_snapshot(out)) == sorted(ARTEFACTS)


def test_the_module_runs_as_a_script_against_the_committed_sources(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mangatl.ui.tokens", "--out-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPO,
    )

    assert result.returncode == 0, result.stderr
    assert sorted(_snapshot(tmp_path)) == sorted(ARTEFACTS)
    assert "overlay.dim.opacity" in result.stderr


def _argv(source: Path, base: Path, hc: Path, out: Path) -> list[str]:
    return [
        "--source",
        str(source),
        "--base-template",
        str(base),
        "--hc-template",
        str(hc),
        "--out-dir",
        str(out),
    ]


# ===========================================================================
# AC-12 / C-8: the override template
# ===========================================================================


def test_the_committed_override_template_satisfies_the_base() -> None:
    gen.check_override_template(
        HC_IN.read_text(encoding="utf-8"), BASE_IN.read_text(encoding="utf-8"), ROLES
    )


def test_an_empty_override_template_is_valid() -> None:
    gen.check_override_template("", "QWidget { color: red; }", ROLES)


@pytest.mark.parametrize("role", ROLES)
def test_each_of_the_five_roles_is_accepted(role: str) -> None:
    gen.check_override_template(
        f"QWidget {{ color: @{{hc.{role}}}; }}", "QWidget { color: red; }", ROLES
    )


def test_an_unknown_role_is_a_violation_naming_it() -> None:
    with pytest.raises(OverrideTemplateViolation) as raised:
        gen.check_override_template(
            "QWidget { color: @{hc.ButtonText}; }", "QWidget { color: red; }", ROLES
        )

    assert "ButtonText" in str(raised.value)


def test_the_roles_argument_is_what_is_checked_against() -> None:
    with pytest.raises(OverrideTemplateViolation) as raised:
        gen.check_override_template(
            "QWidget { color: @{hc.WindowText}; }", "QWidget { color: red; }", ["Window"]
        )

    assert "WindowText" in str(raised.value)


def test_restyling_a_selector_the_base_lacks_is_a_violation_naming_the_selector() -> None:
    with pytest.raises(OverrideTemplateViolation) as raised:
        gen.check_override_template(
            "QCheckBox { color: @{hc.WindowText}; }", "QWidget { color: red; }", ROLES
        )

    assert "QCheckBox" in str(raised.value)


def test_one_foreign_selector_in_a_selector_list_is_a_violation_naming_it() -> None:
    with pytest.raises(OverrideTemplateViolation) as raised:
        gen.check_override_template(
            "QWidget, QSlider { color: @{hc.WindowText}; }",
            "QWidget { color: red; }\nQLineEdit { color: red; }",
            ROLES,
        )

    assert "QSlider" in str(raised.value)


def test_a_selector_is_matched_after_its_whitespace_is_collapsed() -> None:
    base = "QLineEdit:focus,  QPlainTextEdit:focus { border: 1px; }\nQDialog QPushButton { a: b; }"
    override = (
        "QLineEdit:focus,\n    QPlainTextEdit:focus {\n    border-color: @{hc.WindowText};\n}\n"
        "QDialog\n    QPushButton { color: @{hc.WindowText}; }\n"
    )

    gen.check_override_template(override, base, ROLES)


def test_placeholder_braces_are_not_mistaken_for_nested_rules() -> None:
    base = (
        "QWidget {\n    color: @{color.text.primary};\n    padding: @{space.s2}px;\n}\n"
        "QMenu {\n    padding: @{space.s1}px;\n}\n"
    )
    override = (
        "QMenu {\n    padding: @{space.s2}px;\n"
        "    border: @{border-width.emphasis}px solid @{hc.WindowText};\n}\n"
    )

    gen.check_override_template(override, base, ROLES)


def test_comments_are_ignored_when_reading_selectors() -> None:
    base = "/* QCheckBox { color: red; } */\nQWidget { color: red; }"
    override = (
        "/* QSlider { color: @{hc.WindowText}; } is only a comment */\n"
        "QWidget /* trailing */ { color: @{hc.WindowText}; }\n"
    )

    gen.check_override_template(override, base, ROLES)


def test_a_selector_that_exists_only_in_a_base_comment_does_not_count() -> None:
    base = "/* QCheckBox { color: red; } */\nQWidget { color: red; }"

    with pytest.raises(OverrideTemplateViolation) as raised:
        gen.check_override_template("QCheckBox { color: @{hc.WindowText}; }", base, ROLES)

    assert "QCheckBox" in str(raised.value)


def test_generation_refuses_an_override_template_restyling_a_foreign_selector(
    tmp_path: Path,
) -> None:
    hc = _edit(MINI_HC, "QLineEdit {", "QCheckBox {")
    source, base, hc_path, out = _world(tmp_path, hc=hc)
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(OverrideTemplateViolation) as raised:
        gen.generate(source, base, hc_path, out)

    assert "QCheckBox" in str(raised.value)
    assert _snapshot(out) == before


def test_generation_refuses_an_override_template_using_an_unknown_role(
    tmp_path: Path,
) -> None:
    hc = _edit(MINI_HC, "@{hc.HighlightedText}", "@{hc.GrayText}")
    source, base, hc_path, out = _world(tmp_path, hc=hc)
    _seed_out_dir(out)
    before = _snapshot(out)

    with pytest.raises(OverrideTemplateViolation) as raised:
        gen.generate(source, base, hc_path, out)

    assert "GrayText" in str(raised.value)
    assert _snapshot(out) == before


# ===========================================================================
# AC-13 / C-5: the generated module is data only, and lint-clean as emitted
# ===========================================================================

_FORBIDDEN_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.If,
    ast.IfExp,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Match,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.AsyncWith,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _logic_in(module_source: str) -> list[str]:
    tree = ast.parse(module_source)
    found = [
        f"{type(node).__name__} at line {getattr(node, 'lineno', '?')}"
        for node in ast.walk(tree)
        if isinstance(node, _FORBIDDEN_NODES)
    ]
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module == "__future__":
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue  # a docstring
        if isinstance(statement, ast.Assign | ast.AnnAssign) and statement.value is not None:
            try:
                ast.literal_eval(statement.value)
            except ValueError:
                found.append(f"non-literal value at line {statement.lineno}")
            continue
        found.append(f"{type(statement).__name__} statement at line {statement.lineno}")
    return found


def test_the_generated_module_contains_data_only(fresh: Path) -> None:
    assert _logic_in((fresh / "tokens_gen.py").read_text(encoding="utf-8")) == []


def test_the_committed_module_contains_data_only() -> None:
    assert _logic_in((COMMITTED / "tokens_gen.py").read_text(encoding="utf-8")) == []


def test_the_data_only_check_sees_a_function_and_a_branch() -> None:
    """Negative control for the AST check itself: it must fire on logic."""
    logic = "X = 1\ndef f() -> int:\n    return 1\nif X:\n    Y = [i for i in range(3)]\n"
    found = _logic_in(logic)

    assert any(f.startswith("FunctionDef") for f in found)
    assert any(f.startswith("If ") for f in found)
    assert any(f.startswith("ListComp") for f in found)


def test_the_generated_module_opens_with_a_do_not_edit_header(fresh: Path) -> None:
    lines = (fresh / "tokens_gen.py").read_text(encoding="utf-8").splitlines()
    header = []
    for line in lines:
        if not line.startswith("#"):
            break
        header.append(line)
    text = "\n".join(header)

    assert header, "tokens_gen.py does not open with a comment header"
    assert "tokens.toml" in text
    assert "mangatl.ui.tokens" in text
    assert re.search(r"(?i)\bnot\b.*\bedit", text), text


@pytest.mark.parametrize(
    "ruff_args",
    [["check", "--no-cache"], ["format", "--check", "--no-cache"]],
    ids=["ruff-check", "ruff-format"],
)
def test_the_generated_module_passes_ruff_as_emitted(fresh: Path, ruff_args: list[str]) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            *ruff_args,
            "--config",
            str(REPO / "pyproject.toml"),
            str(fresh / "tokens_gen.py"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
