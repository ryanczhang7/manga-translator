"""MT-015 AC-7: no colour literal appears in the workspace widget sources.

Every colour in `src/mangatl/ui/` resolves through `tokens_gen` (Python) or
`theme.qss` (the generated sheet). This is the only thing that keeps MT-025's
generator load-bearing: a single `#FFFFFF` typed into a widget under deadline
is a theme the generator no longer controls.

The scan is a plain function of text, so its negative controls - each
forbidden form fed in and reported - execute here even while the modules it
must scan do not yet exist. This file deliberately imports nothing from
`mangatl.ui`.

Scope (Contract, AC-7): every `*.py` under `src/mangatl/ui/`, except
`tokens_gen.py` (the generated artefact, which IS the colour table) and
`tokens.py` (its generator). The allowlist has ZERO entries.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI_SOURCE = REPO / "src" / "mangatl" / "ui"
EXCLUDED = frozenset({"tokens_gen.py", "tokens.py"})
MUST_SCAN = frozenset({"workspace.py", "canvas.py"})
ALLOWLIST: frozenset[tuple[str, int]] = frozenset()  # zero entries, by decision

# Qt's named global colours (Qt.GlobalColor members), reachable as Qt.<name>.
_QT_NAMED = (
    "black|white|red|green|blue|cyan|magenta|yellow|gray|darkGray|lightGray|"
    "darkRed|darkGreen|darkBlue|darkCyan|darkMagenta|darkYellow|transparent|"
    "color0|color1"
)

FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    # `#` then 3, 4, 6 or 8 hex digits, as a whole token.
    ("hex colour", re.compile(r"(?<![\w&])#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3,4})\b")),
    # QColor( whose first argument is a literal: a quote, a digit, or a sign.
    # QColor(tokens_gen.X) is the sanctioned form and does not match.
    ("QColor literal", re.compile(r"\bQColor\(\s*(?:[rRbBfFuU]{0,2}[\"']|[-+]?\.?\d)")),
    # Every QColor.from* constructor builds a colour from numbers or a name.
    ("QColor.from*", re.compile(r"\bQColor\.from[A-Za-z0-9]+\b")),
    ("QColorConstants", re.compile(r"\bQColorConstants\b")),
    ("rgb()/rgba()", re.compile(r"\brgba?\(")),
    ("hsl()/hsv()", re.compile(r"\bhs[lv]a?\(")),
    ("Qt.GlobalColor", re.compile(r"\bQt\.GlobalColor\b|\bGlobalColor\.")),
    ("Qt named colour", re.compile(rf"\bQt\.(?:{_QT_NAMED})\b")),
)


def scan(text: str) -> list[tuple[int, str, str]]:
    """Every colour literal in `text`, as (line, kind, matched text)."""
    found: list[tuple[int, str, str]] = []
    for kind, pattern in FORBIDDEN:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append((line, kind, match.group(0)))
    return sorted(found)


def scan_inputs() -> list[Path]:
    return sorted(p for p in UI_SOURCE.rglob("*.py") if p.name not in EXCLUDED)


# --- The scanner's own controls ----------------------------------------------

# One sample per forbidden form in the Contract, plus the obvious spellings of
# each. Every one of these MUST be reported.
FORBIDDEN_SAMPLES: tuple[str, ...] = (
    'label.setStyleSheet("color: #fff")',
    'x = "#FFFF"',
    'brush = QBrush("#1C1C1C")',
    'pen = "#0B0B0B80"',
    "QColor('#5F5F5F')",
    'QColor("red")',
    "QColor(95, 95, 95)",
    "QColor(\n    0x5F, 0x5F, 0x5F)",
    "QColor(0.5)",
    "QColor.fromRgb(1, 2, 3)",
    "QColor.fromRgbF(0.1, 0.2, 0.3)",
    "QColor.fromHsv(1, 2, 3)",
    "QColor.fromHsl(1, 2, 3)",
    "QColor.fromString('teal')",
    "QColorConstants.Svg.teal",
    'sheet = "background: rgb(1, 2, 3)"',
    'sheet = "background: rgba(1, 2, 3, 4)"',
    'sheet = "background: hsl(1, 2%, 3%)"',
    "brush = Qt.GlobalColor.black",
    "brush = QBrush(Qt.white)",
    "brush = QBrush(Qt.transparent)",
    "pen.setColor(Qt.darkGray)",
)

# Colour-free code a workspace legitimately contains. None may be reported:
# a scanner that flags everything would make the real scan pass nothing.
ALLOWED_SAMPLES: tuple[str, ...] = (
    "QColor(tokens_gen.COLOR_CANVAS_SURROUND)",
    "QColor(tokens_gen.COLOR_CANVAS_PAGE_EDGE)",
    "# a comment that is not a colour",
    "#: a Sphinx-style attribute comment",
    'self.setObjectName("pageCanvas")',
    "view.setBackgroundBrush(QBrush(QColor(tokens_gen.COLOR_CANVAS_SURROUND)))",
    "Qt.AlignmentFlag.AlignCenter",
    "Qt.ScrollBarPolicy.ScrollBarAlwaysOff",
    "Qt.Orientation.Horizontal",
    "item = f'{ordinal:#x}'",
    "EMPTY_TITLE = 'No chapter loaded'",
)


def test_the_scanner_reports_every_forbidden_colour_form() -> None:
    missed = [sample for sample in FORBIDDEN_SAMPLES if not scan(sample)]

    assert missed == [], f"the scanner did not report: {missed}"


def test_the_scanner_reports_each_occurrence_with_its_line_number() -> None:
    text = "a = 1\nb = '#ABCDEF'\nc = QColor(1, 2, 3)\nd = Qt.black\n"

    assert [line for line, _, _ in scan(text)] == [2, 3, 4]


def test_the_scanner_passes_colour_free_widget_code() -> None:
    flagged = {sample: scan(sample) for sample in ALLOWED_SAMPLES if scan(sample)}

    assert flagged == {}, f"the scanner flagged colour-free code: {flagged}"


def test_the_allowlist_is_empty() -> None:
    assert len(ALLOWLIST) == 0


# --- The scan itself ------------------------------------------------------------


def test_the_scan_covers_workspace_py_and_canvas_py() -> None:
    names = {path.name for path in scan_inputs()}

    missing = sorted(MUST_SCAN - names)
    assert missing == [], f"the colour scan did not find {missing} under {UI_SOURCE}"


def test_the_scan_excludes_only_the_token_generator_and_its_output() -> None:
    names = {path.name for path in scan_inputs()}

    assert not names & EXCLUDED
    assert "main_window.py" in names


def test_no_colour_literal_appears_in_the_workspace_widget_sources() -> None:
    inputs = scan_inputs()
    names = {path.name for path in inputs}
    assert names >= MUST_SCAN, f"vacuous scan: {sorted(MUST_SCAN - names)} not among its inputs"

    findings = [
        f"{path.relative_to(REPO).as_posix()}:{line}: {kind}: {text!r}"
        for path in inputs
        for line, kind, text in scan(path.read_text(encoding="utf-8"))
        if (path.name, line) not in ALLOWLIST
    ]

    assert findings == [], "colour literals in ui source:\n" + "\n".join(findings)
