"""MT-132: the error banner takes a 2px WindowText frame and a 3px bar under HC.

`components.md` §10.7: under High Contrast `ErrorBanner` is ground `Window`, a
**2px `WindowText` border all round** plus the **3px `WindowText` leading
bar**. The base rule (`theme.qss.in`, `QFrame#error-banner`) draws a hairline
frame and an emphasis-wide bar in `color.status.danger`; `theme_hc.qss.in` had
no banner rule, so under HC the colours collapse to `WindowText` through the
token map but the widths stay 1px all round and 2px on the left. This file pins
the HC frame as **paint**, through the real theme path - the sheet composed for
High Contrast (or the packaged `theme.qss`) set as the *application* sheet,
never `styleSheet()` on the widget.

"Line n" of an edge is the line n pixels in from that edge, sampled with
`radius.sm + border-width.bar` pixels skipped at each end (the banner keeps its
rounded corners, and the bar is the widest border meeting them). Each line is
asserted separately and in order, per edge, so a failure names both.

Helpers are copied from `tests/ui/test_rerun_dialog_border.py` and
`tests/ui/test_hc_dialog_border.py` (`tests` is not a package); `PALETTE` keeps
their values so runs can be compared.

Oracle partition (story `## Contract` C-4):

- **Settled, read out:** `border-width.emphasis`, `border-width.hairline`,
  `border-width.bar`, `radius.sm`, `color.status.danger`,
  `color.surface.raised` from `tokens_gen.TOKENS`; the HC mapping through
  `theme.compose_stylesheet`; the selector `QFrame#error-banner`.
- **Mechanical, pinned exactly:** every line colour set (AC-1 to AC-3); the
  banner's own `styleSheet() == ""`; AC-4's parsed declarations, in order.
- **Oracle-free:** none.

RED: every module exists, so nothing fails at import. `border-width.bar` does
not exist until GREEN adds it (C-1), and every width is read from
`tokens_gen.TOKENS` strictly, never typed and never defaulted - so every test
that samples an edge stops first on the missing-token precondition. The story's
handoff records the paint each one measured with the token supplied by a
`scripts/mutate.sh` probe: AC-1 red on line 1, AC-2 red on line 2, AC-3 green.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from mangatl.ui import theme, tokens, tokens_gen
from mangatl.ui.progress import ErrorBanner
from mangatl.ui.stylesheet import base_template, hc_template

REPO = Path(__file__).resolve().parents[2]
DESIGN = REPO / "docs" / "wiki" / "design"
HC_IN = DESIGN / "theme_hc.qss.in"

SELECTOR = "QFrame#error-banner"

#: components.md §10.7 / §9: the widths, the corner, and the base colours.
BAR = "border-width.bar"
FRAME = "border-width.emphasis"
HAIRLINE = "border-width.hairline"
RADIUS = "radius.sm"
DANGER = "color.status.danger"
GROUND = "color.surface.raised"

#: C-1, decided (story Notes PO-1): the leading bar is 3px.
BAR_PX = 3

#: A five-role contrast palette, identical to test_hc_dialog_border.py's.
#: `WindowText` and `Window` are colours no token uses (asserted below), so a
#: line of either can only have come from the palette.
PALETTE: dict[str, str] = {
    "Window": "#010203",
    "WindowText": "#FDFEFF",
    "Highlight": "#1A2B3C",
    "HighlightedText": "#C3B2A1",
    "DisabledText": "#4D5E6F",
}

BANNER_W, BANNER_H = 480, 160

EDGES = ("top", "bottom", "left", "right")

#: The edges that carry the frame alone; the left one carries the bar.
FRAME_EDGES = ("top", "bottom", "right")

#: A literal pixel number in a declaration (AC-4: none carries one).
LITERAL_PX = re.compile(r"\d\s*px")


# --- Helpers (copied, not imported: `tests` is not a package) ------------------


def _token_colour(name: str) -> str:
    return QColor(tokens_gen.TOKENS[name]).name()


def _token_colours_used() -> set[str]:
    return {
        QColor(str(v)[:7]).name()
        for v in tokens_gen.TOKENS.values()
        if isinstance(v, str) and v.startswith("#")
    }


def _width(name: str) -> int:
    """A width token, read out strictly: a missing token is a failed
    precondition, never a default (C-3)."""
    assert name in tokens_gen.TOKENS, (
        f"tokens_gen.TOKENS has no {name!r}: C-1 adds `bar = 3` under [border-width] "
        f"in tokens.toml and regenerates tokens_gen.py"
    )
    return int(tokens_gen.TOKENS[name])


def _inset() -> int:
    """Pixels skipped at each end of every sampled line: `radius.sm + bar`."""
    return _width(RADIUS) + _width(BAR)


def _packaged(resource: str) -> str:
    return files("mangatl.ui").joinpath(resource).read_text(encoding="utf-8")


def _hc_theme(palette: Mapping[str, str] = PALETTE) -> str:
    return theme.compose_stylesheet(
        base_template(), hc_template(), high_contrast=True, palette=palette
    )


@pytest.fixture
def application_sheet(qapp: QApplication) -> Iterator[Callable[[str], None]]:
    """Set the real application's sheet; always put `""` back."""

    def apply(sheet: str) -> None:
        qapp.setStyleSheet(sheet)

    try:
        yield apply
    finally:
        qapp.setStyleSheet("")


def _shown(qtbot) -> tuple[ErrorBanner, QImage]:  # type: ignore[no-untyped-def]
    """The banner alone, shown, and its own pixels. The banner is returned so
    the caller holds it: qtbot keeps only a weak reference."""
    banner = ErrorBanner("Translation stopped", "The budget was reached.")
    qtbot.addWidget(banner)
    banner.resize(BANNER_W, BANNER_H)
    banner.show()
    qtbot.waitExposed(banner)
    QApplication.processEvents()
    QApplication.processEvents()
    return banner, banner.grab().toImage()


def _edge_line(image: QImage, depth: int) -> dict[str, set[str]]:
    """Per edge, the colours along the line `depth` pixels in from that edge,
    with `radius.sm + bar` pixels skipped at each end (the rounded corners
    belong to neither edge alone)."""
    inset = _inset()
    w, h = image.width(), image.height()

    def at(x: int, y: int) -> str:
        return image.pixelColor(x, y).name()

    return {
        "top": {at(x, depth) for x in range(inset, w - inset)},
        "bottom": {at(x, h - 1 - depth) for x in range(inset, w - inset)},
        "left": {at(depth, y) for y in range(inset, h - inset)},
        "right": {at(w - 1 - depth, y) for y in range(inset, h - inset)},
    }


def _assert_lines(
    image: QImage, edge: str, expected: list[tuple[str, str]], sheet: str, cause: list[str]
) -> None:
    """Line 0, 1, ... of `edge`, asserted in order: line n is exactly
    {expected[n] colour}. `cause[n]` says what a failure at line n means."""
    for depth, ((label, colour), why) in enumerate(zip(expected, cause, strict=True)):
        line = _edge_line(image, depth)[edge]
        assert line == {colour}, (
            f"under {sheet} the error banner's {edge} edge, line {depth}, is not "
            f"{label} ({colour}) alone: {why}. Got {sorted(line)}"
        )


def _template_rules(template: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """(selector, [(property, value), ...]) per rule of an UNRENDERED template,
    parsed with the generator's own regexes (`tests/ui/test_theme_apply.py`'s
    `_rules`/`_template_rules` shape).

    `tokens._RULE` cannot see past a `{`, so each `@{name}` is first rewritten
    brace-free as `@<name>`; the values returned are MAPPED BACK to `@{name}`,
    so assertions compare against the template's own spelling."""
    rewritten = tokens._PLACEHOLDER.sub(lambda m: f"@<{m.group(1)}>", template)
    stripped = tokens._COMMENT.sub("", rewritten)
    parsed = []
    for match in tokens._RULE.finditer(stripped):
        selector = " ".join(match.group(1).split())
        body = match.group(0)[match.group(0).index("{") + 1 : -1]
        declarations: list[tuple[str, str]] = []
        for part in body.split(";"):
            if ":" in part:
                prop, value = part.split(":", 1)
                restored = re.sub(r"@<([^>]+)>", r"@{\1}", " ".join(value.split()))
                declarations.append((prop.strip(), restored))
        parsed.append((selector, declarations))
    return parsed


def _banner_rules() -> list[list[tuple[str, str]]]:
    return [
        decls
        for found, decls in _template_rules(HC_IN.read_text(encoding="utf-8"))
        if found == SELECTOR
    ]


# --- Preconditions: the colours and widths this file compares are distinct ------


def test_the_leading_bar_width_token_exists_and_is_three_pixels() -> None:
    """C-1 / Notes PO-1: `border-width.bar` is the 3px token the HC bar reads,
    wider than the 2px frame it sits in (else the bar is not a bar)."""
    bar = _width(BAR)
    assert bar == BAR_PX, f"{BAR} is {bar}; the decided leading-bar width is {BAR_PX}"
    assert bar > _width(FRAME), f"{BAR} ({bar}) is not wider than {FRAME}"


def test_the_frame_and_base_widths_are_the_ones_the_line_tests_assume() -> None:
    """AC-1's three lines mean 2px only if emphasis is 2; AC-3's mean a
    hairline frame and an emphasis bar only if those are 1 and 2."""
    assert _width(FRAME) == 2, f"{FRAME} is {_width(FRAME)}; AC-1's lines assume 2"
    assert _width(HAIRLINE) == 1, f"{HAIRLINE} is {_width(HAIRLINE)}; AC-3's lines assume 1"


def test_the_hc_palette_window_text_and_window_are_no_tokens_colour() -> None:
    """Without this a line of WindowText or Window could have come from some
    token's rule rather than from the palette."""
    used = _token_colours_used()
    for role in ("WindowText", "Window"):
        assert QColor(PALETTE[role]).name() not in used, (
            f"the test palette's {role} {PALETTE[role]} is a token's value"
        )
    assert QColor(PALETTE["WindowText"]).name() != QColor(PALETTE["Window"]).name()
    assert set(PALETTE) == set(tokens.HC_ROLES), "the palette must carry exactly the five roles"


def test_the_danger_border_and_the_raised_ground_are_different_colours() -> None:
    """AC-3 tells the border from the ground by colour alone."""
    assert _token_colour(DANGER) != _token_colour(GROUND), f"{DANGER} == {GROUND}"


@pytest.mark.parametrize("sheet", ["high-contrast", "packaged"])
def test_the_banner_grab_is_full_size_with_a_run_on_every_sampled_line(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    sheet: str,
) -> None:
    """The grab is 480x160 and every edge's lines 0-3 are non-empty runs."""
    application_sheet(_hc_theme() if sheet == "high-contrast" else _packaged("theme.qss"))

    banner, image = _shown(qtbot)

    assert banner.styleSheet() == "", "the banner must take its border from the application sheet"
    assert (image.width(), image.height()) == (BANNER_W, BANNER_H), (
        f"the banner grabbed at {image.width()}x{image.height()}"
    )
    for depth in range(4):
        runs = _edge_line(image, depth)
        assert all(runs[edge] for edge in EDGES), f"an empty line-{depth} run: {runs}"


# --- AC-1: the 2px WindowText frame under High Contrast -------------------------


@pytest.mark.parametrize("edge", FRAME_EDGES)
def test_under_high_contrast_the_error_banner_frame_is_two_pixels_of_window_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    edge: str,
) -> None:
    """AC-1: the HC sheet; on top, bottom and right, lines 0 and 1 are
    WindowText and line 2 is the Window ground. A 1px frame fails on line 1; a
    3px frame fails on line 2."""
    application_sheet(_hc_theme())

    banner, image = _shown(qtbot)

    assert banner.styleSheet() == "", "the banner must take its border from the application sheet"
    window_text = QColor(PALETTE["WindowText"]).name()
    window = QColor(PALETTE["Window"]).name()
    _assert_lines(
        image,
        edge,
        [("WindowText", window_text), ("WindowText", window_text), ("Window", window)],
        "the High Contrast sheet",
        [
            "there is no WindowText frame at all",
            f"the frame is narrower than {FRAME} (the base hairline still wins)",
            f"the frame is wider than {FRAME}, or a child reaches line 2",
        ],
    )


# --- AC-2: the 3px WindowText leading bar under High Contrast -------------------


def test_under_high_contrast_the_error_banner_leading_bar_is_three_pixels_of_window_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-2: the HC sheet; on the left, lines 0, 1 and 2 are WindowText and
    line 3 is the Window ground. A bar at emphasis fails on line 2."""
    application_sheet(_hc_theme())

    banner, image = _shown(qtbot)

    assert banner.styleSheet() == "", "the banner must take its border from the application sheet"
    window_text = QColor(PALETTE["WindowText"]).name()
    window = QColor(PALETTE["Window"]).name()
    _assert_lines(
        image,
        "left",
        [
            ("WindowText", window_text),
            ("WindowText", window_text),
            ("WindowText", window_text),
            ("Window", window),
        ],
        "the High Contrast sheet",
        [
            "there is no WindowText leading bar at all",
            "the leading bar is under 2px",
            f"the leading bar is narrower than {BAR} (still {FRAME}, the base bar)",
            f"the leading bar is wider than {BAR}, or a child reaches line 3",
        ],
    )


# --- AC-3: control - the packaged (non-HC) sheet is unchanged -------------------


@pytest.mark.parametrize("edge", FRAME_EDGES)
def test_control_under_the_packaged_sheet_the_banner_frame_is_a_danger_hairline(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    edge: str,
) -> None:
    """AC-3: the packaged theme.qss; on top, bottom and right line 0 is
    color.status.danger and line 1 is color.surface.raised - the base rule as
    it is today. The HC override must not leak into the base."""
    application_sheet(_packaged("theme.qss"))

    banner, image = _shown(qtbot)

    assert banner.styleSheet() == "", "the banner must take its border from the application sheet"
    _assert_lines(
        image,
        edge,
        [(DANGER, _token_colour(DANGER)), (GROUND, _token_colour(GROUND))],
        "the packaged sheet",
        [
            "the base banner lost its danger frame",
            f"the base frame is wider than {HAIRLINE}: the HC override leaked into the base",
        ],
    )


def test_control_under_the_packaged_sheet_the_banner_leading_bar_is_two_pixels_of_danger(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-3: the packaged theme.qss; on the left lines 0 and 1 are
    color.status.danger and line 2 is color.surface.raised."""
    application_sheet(_packaged("theme.qss"))

    banner, image = _shown(qtbot)

    assert banner.styleSheet() == "", "the banner must take its border from the application sheet"
    _assert_lines(
        image,
        "left",
        [
            (DANGER, _token_colour(DANGER)),
            (DANGER, _token_colour(DANGER)),
            (GROUND, _token_colour(GROUND)),
        ],
        "the packaged sheet",
        [
            "the base banner lost its danger bar",
            f"the base bar is narrower than {FRAME}",
            f"the base bar is wider than {FRAME}: the HC bar leaked into the base",
        ],
    )


# --- AC-4: the rule as written in the design input ------------------------------


def test_the_high_contrast_template_has_exactly_one_error_banner_rule() -> None:
    """AC-4: `theme_hc.qss.in` carries exactly one rule whose selector is
    `QFrame#error-banner`."""
    rules = _banner_rules()

    assert len(rules) == 1, (
        f"theme_hc.qss.in has {len(rules)} rules whose selector is {SELECTOR}, not 1: {rules}"
    )


def test_the_high_contrast_error_banner_rule_restates_the_frame_then_the_bar() -> None:
    """AC-4: its declarations are exactly the emphasis-wide WindowText frame
    and then the bar-wide WindowText leading bar - in that order, since a
    `border` after `border-left` would reset the bar."""
    rules = _banner_rules()

    assert rules == [
        [
            ("border", "@{border-width.emphasis}px solid @{hc.WindowText}"),
            ("border-left", "@{border-width.bar}px solid @{hc.WindowText}"),
        ]
    ], f"the HC {SELECTOR} rule is not the frame-then-bar pair C-1 specifies: {rules}"


def test_the_high_contrast_error_banner_rule_carries_no_literal_pixel_number() -> None:
    """AC-4: every width comes from a token placeholder."""
    rules = _banner_rules()

    assert rules, f"theme_hc.qss.in has no {SELECTOR} rule"
    literal = [
        (prop, value) for decls in rules for prop, value in decls if LITERAL_PX.search(value)
    ]
    assert literal == [], f"the HC {SELECTOR} rule types a pixel width: {literal}"
