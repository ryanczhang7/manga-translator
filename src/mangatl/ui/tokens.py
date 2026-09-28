"""The design-token generator (MT-025).

A development tool, never run at application startup. It reads
`docs/wiki/design/tokens.toml` and the two QSS templates beside it, validates all
of them, and only then writes four artefacts into this package:

* `theme.qss` - the base template rendered with the authored values;
* `tokens_gen.py` - one constant per token plus `TOKENS`, `HC_PALETTE_ROLE` and
  `HC_OVERRIDE`, data only;
* `theme.qss.tmpl` and `theme_hc.qss.tmpl` - the two templates, byte for byte,
  so the running app can compose a High Contrast sheet (MT-028).

Regenerate with `uv run python -m mangatl.ui.tokens`. Never edit an artefact.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "BASE_TEMPLATE_SOURCE",
    "EXCLUDED_SECTIONS",
    "HC_ROLES",
    "HC_TEMPLATE_SOURCE",
    "PACKAGE_DIR",
    "STATIC",
    "TOKENS_SOURCE",
    "GenerationReport",
    "MalformedToken",
    "MissingHighContrastMapping",
    "OverrideTemplateViolation",
    "TokenError",
    "TokenValue",
    "UnresolvedPlaceholder",
    "check_override_template",
    "generate",
    "is_colour_token",
    "load_hc",
    "load_tokens",
    "main",
    "render_python",
    "render_qss",
    "to_constant_name",
    "token_text",
]

PACKAGE_DIR = Path(__file__).resolve().parent
_DESIGN = PACKAGE_DIR.parents[2] / "docs" / "wiki" / "design"
TOKENS_SOURCE = _DESIGN / "tokens.toml"
BASE_TEMPLATE_SOURCE = _DESIGN / "theme.qss.in"
HC_TEMPLATE_SOURCE = _DESIGN / "theme_hc.qss.in"

STATIC = "@static"
HC_ROLES = frozenset({"Window", "WindowText", "Highlight", "HighlightedText", "DisabledText"})
EXCLUDED_SECTIONS = frozenset({"hc", "meta"})

# C-2 order.
_ARTEFACTS = ("theme.qss", "tokens_gen.py", "theme.qss.tmpl", "theme_hc.qss.tmpl")

_NAME = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)*$")
_COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
_PLACEHOLDER = re.compile(r"@\{([^}]+)\}")
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE = re.compile(r"([^{}]*)\{[^{}]*\}")

TokenValue = str | int | float | bool


class TokenError(Exception):
    """Base of every generation failure."""


class MalformedToken(TokenError):
    """A bad colour value, a name outside the grammar, or a constant-name collision."""


class UnresolvedPlaceholder(TokenError):
    """A template placeholder naming no token."""


class MissingHighContrastMapping(TokenError):
    """A colour token with no `[hc.map]` entry."""


class OverrideTemplateViolation(TokenError):
    """The HC override template breaks AC-12, or `[hc.override]` names no token."""


@dataclass(frozen=True)
class GenerationReport:
    written: tuple[Path, ...]
    orphans: tuple[str, ...]


def _read_document(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_bytes().decode("utf-8"))


def load_tokens(path: Path) -> dict[str, TokenValue]:
    """Flatten the document depth-first into dotted names, skipping `[hc]` and `[meta]`."""
    flat: dict[str, TokenValue] = {}

    def walk(table: Mapping[str, Any], prefix: str) -> None:
        for key, value in table.items():
            name = prefix + key
            if isinstance(value, dict):
                walk(value, name + ".")
            else:
                flat[name] = value

    document = _read_document(path)
    walk({k: v for k, v in document.items() if k not in EXCLUDED_SECTIONS}, "")
    return flat


def load_hc(path: Path) -> tuple[dict[str, str], dict[str, str | float], list[str]]:
    """Return `([hc.map], [hc.override], [hc].roles)`."""
    hc: dict[str, Any] = _read_document(path).get("hc", {})
    hc_map: dict[str, str] = hc.get("map", {})
    hc_override: dict[str, str | float] = hc.get("override", {})
    roles: list[str] = hc.get("roles", [])
    return hc_map, hc_override, roles


def to_constant_name(dotted: str) -> str:
    return dotted.upper().replace(".", "_").replace("-", "_")


def is_colour_token(dotted: str, value: TokenValue) -> bool:
    return isinstance(value, str) and dotted.split(".")[0] in ("color", "overlay")


def token_text(value: TokenValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def render_qss(tokens: Mapping[str, TokenValue], template: str) -> str:
    """Substitute every `@{name}` in one pass; a name that is not a token is an error."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in tokens:
            raise UnresolvedPlaceholder(f"placeholder @{{{name}}} names no token")
        return token_text(tokens[name])

    return _PLACEHOLDER.sub(substitute, template)


def _literal(value: TokenValue) -> str:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else repr(value)


def _dict_literal(items: Mapping[str, TokenValue]) -> str:
    body = "".join(f"    {_literal(k)}: {_literal(v)},\n" for k, v in items.items())
    return "{\n" + body + "}" if body else "{}"


def render_python(
    tokens: Mapping[str, TokenValue],
    hc_map: Mapping[str, str],
    hc_override: Mapping[str, str | float],
) -> str:
    """The source of `tokens_gen.py`: data only, lint-clean as emitted (C-5)."""
    constants = "".join(
        f"{to_constant_name(name)} = {_literal(value)}\n" for name, value in tokens.items()
    )
    texts = {name: token_text(value) for name, value in tokens.items()}
    return (
        "# Generated from docs/wiki/design/tokens.toml by mangatl.ui.tokens.\n"
        "# Do not edit: regenerate with `uv run python -m mangatl.ui.tokens`.\n"
        "\n"
        f"{constants}"
        "\n"
        f"TOKENS: dict[str, str] = {_dict_literal(texts)}\n"
        "\n"
        f"HC_PALETTE_ROLE: dict[str, str] = {_dict_literal(hc_map)}\n"
        "\n"
        f"HC_OVERRIDE: dict[str, str | float] = {_dict_literal(hc_override)}\n"
    )


def _selectors(sheet: str) -> set[str]:
    masked = _PLACEHOLDER.sub("@", _COMMENT.sub("", sheet))
    return {
        " ".join(selector.split())
        for selector_list in _RULE.findall(masked)
        for selector in selector_list.split(",")
    }


def check_override_template(override: str, base: str, roles: Iterable[str]) -> None:
    """AC-12: every `@{hc.Role}` names a role; every selector is one the base defines."""
    allowed = set(roles)
    for name in _PLACEHOLDER.findall(override):
        if name.startswith("hc.") and name[3:] not in allowed:
            raise OverrideTemplateViolation(f"@{{{name}}}: {name[3:]} is not a High Contrast role")
    foreign = sorted(_selectors(override) - _selectors(base))
    if foreign:
        raise OverrideTemplateViolation(
            f"override template restyles selectors the base does not define: {foreign}"
        )


def _validate_tokens(tokens: Mapping[str, TokenValue]) -> None:
    owners: dict[str, str] = {}
    for name, value in tokens.items():
        if not _NAME.match(name):
            raise MalformedToken(f"token name {name!r} is outside the token-name grammar")
        constant = to_constant_name(name)
        if constant in owners:
            raise MalformedToken(
                f"tokens {owners[constant]!r} and {name!r} collide on constant {constant}"
            )
        owners[constant] = name
        if is_colour_token(name, value) and not _COLOUR.match(str(value)):
            raise MalformedToken(f"colour token {name} has malformed value {value!r}")


def generate(
    source: Path, base_template: Path, hc_template: Path, out_dir: Path
) -> GenerationReport:
    """Validate everything, then write the four artefacts into `out_dir`."""
    tokens = load_tokens(source)
    hc_map, hc_override, roles = load_hc(source)
    base_bytes = base_template.read_bytes()
    hc_bytes = hc_template.read_bytes()
    base = base_bytes.decode("utf-8")
    override = hc_bytes.decode("utf-8")

    _validate_tokens(tokens)
    for name, value in tokens.items():
        if is_colour_token(name, value) and name not in hc_map:
            raise MissingHighContrastMapping(f"colour token {name} has no [hc.map] entry")
    for name in hc_override:
        if name not in tokens:
            raise OverrideTemplateViolation(f"[hc.override] key {name} names no token")
    sheet = render_qss(tokens, base)
    for name in _PLACEHOLDER.findall(override):
        if not name.startswith("hc.") and name not in tokens:
            raise UnresolvedPlaceholder(f"override placeholder @{{{name}}} names no token")
    check_override_template(override, base, roles)
    module = render_python(tokens, hc_map, hc_override)

    referenced = set(_PLACEHOLDER.findall(base)) | set(_PLACEHOLDER.findall(override))
    orphans = tuple(sorted(name for name in tokens if name not in referenced))

    contents = (sheet.encode("utf-8"), module.encode("utf-8"), base_bytes, hc_bytes)
    written = tuple(out_dir / name for name in _ARTEFACTS)
    for path, data in zip(written, contents, strict=True):
        path.write_bytes(data)
    return GenerationReport(written=written, orphans=orphans)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mangatl.ui.tokens", description=__doc__)
    parser.add_argument("--source", type=Path, default=TOKENS_SOURCE)
    parser.add_argument("--base-template", type=Path, default=BASE_TEMPLATE_SOURCE)
    parser.add_argument("--hc-template", type=Path, default=HC_TEMPLATE_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=PACKAGE_DIR)
    args = parser.parse_args(argv)
    try:
        report = generate(args.source, args.base_template, args.hc_template, args.out_dir)
    except TokenError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for orphan in report.orphans:
        print(f"orphan, referenced by neither template: {orphan}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
