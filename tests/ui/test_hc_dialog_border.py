"""MT-131: every sheet-styled dialog takes a 2px WindowText border under HC.

`components.md` §10.2 / §10.7: under High Contrast elevation `e2` - "popover /
menu / dialog" - is `Window` plus a **2px `WindowText`** boundary and no
shadow. `theme_hc.qss.in` did that for `QToolTip` and `QMenu` and for no
dialog. This file pins it as **paint**, through the real theme path - the sheet
composed for High Contrast (or the packaged `theme.qss`) set as the
*application* sheet, never `styleSheet()` on the widget - for every dialog the
sheet styles: `ApiKeyDialog`, `BakeConfirmDialog`, `RerunDialog` within and
over budget, and the settings warning `QMessageBox` (`app.show_warning`).

"The 2px edge test": for each of the four edges, with `emphasis` pixels skipped
at each end of every line, line 0 and line 1 in from that edge are the
palette's `WindowText` and nothing else, and line 2 is the palette's `Window`
and nothing else. No border fails line 0; a 1px border fails line 1; a 3px
border fails line 2. The three lines are asserted separately, in order, so a
failure names the line.

Helpers are copied from `tests/ui/test_rerun_dialog_border.py` (`tests` is not
a package); `PALETTE` keeps that file's values so runs can be compared.

Oracle partition (story `## Contract` C-6):

- **Settled, read out:** `border-width.emphasis` (2) and
  `border-width.hairline` (1) from `tokens_gen.TOKENS`; `color.surface.base`;
  the HC mapping through `theme.compose_stylesheet`; the five `HC_ROLES`; the
  selectors `QDialog` and `RerunDialog[overBudget="true"]`.
- **Mechanical, pinned exactly:** every line-0/1/2 colour set (AC-1 to AC-6);
  the dialog's own `styleSheet() == ""`; AC-7's parsed declarations.
- **Oracle-free:** none.

RED: every module exists, so nothing fails at import. AC-1, AC-2, AC-3 and AC-5
fail on their line-0 assertion (the edge comes back as `Window`, the HC
ground); AC-4 fails on line 1 (the base hairline is `WindowText`, 1px); AC-7
fails on the missing rules. AC-6 (the non-HC control) and the preconditions
pass on arrival by design; the story's handoff says why each is admissible.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from mangatl.domain.money import Usd
from mangatl.pipeline.bake import BakePreview
from mangatl.pipeline.resume import RerunPreview
from mangatl.ui import theme, tokens, tokens_gen
from mangatl.ui.api_key_dialog import ApiKeyDialog
from mangatl.ui.bake_dialog import BakeConfirmDialog
from mangatl.ui.rerun_dialog import RerunDialog
from mangatl.ui.stylesheet import base_template, hc_template

REPO = Path(__file__).resolve().parents[2]
DESIGN = REPO / "docs" / "wiki" / "design"
HC_IN = DESIGN / "theme_hc.qss.in"

#: components.md §10.2: the HC e2 boundary width; the base hairline it must beat.
EDGE_WIDTH = "border-width.emphasis"
HAIRLINE = "border-width.hairline"
GROUND = "color.surface.base"

#: Read out, never typed (C-6).
EMPHASIS = int(tokens_gen.TOKENS[EDGE_WIDTH])

#: A five-role contrast palette, identical to test_rerun_dialog_border.py's.
#: `WindowText` and `Window` are colours no token uses (asserted below), so an
#: edge of either can only have come from the palette.
PALETTE: dict[str, str] = {
    "Window": "#010203",
    "WindowText": "#FDFEFF",
    "Highlight": "#1A2B3C",
    "HighlightedText": "#C3B2A1",
    "DisabledText": "#4D5E6F",
}

DIALOG_W, DIALOG_H = 480, 240

EDGES = ("top", "bottom", "left", "right")

#: The three lines of the 2px edge test, by depth in from the edge.
LINES = (0, 1, 2)

#: One line of text, as `app.show_warning` would show it.
WARNING_TEXT = "The settings file could not be read."

#: A literal pixel number in a rule body (AC-7: neither rule carries one).
LITERAL_PX = re.compile(r"\b\d+px")


# --- Helpers (copied, not imported: `tests` is not a package) ------------------


def _token_colour(name: str) -> str:
    return QColor(tokens_gen.TOKENS[name]).name()


def _token_colours_used() -> set[str]:
    return {
        QColor(str(v)[:7]).name()
        for v in tokens_gen.TOKENS.values()
        if isinstance(v, str) and v.startswith("#")
    }


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


def _preview(*, within_budget: bool) -> RerunPreview:
    """`tests/ui/test_rerun_dialog.py`'s default preview; the dialog reads
    only the bool for the property this file measures."""
    return RerunPreview(
        page_count=4,
        pages_to_run=2,
        pending={"detect": 2, "translate": 2},
        pages_to_translate=2,
        spent=Usd(Decimal("0.83")),
        ceiling=Usd(Decimal("2.00")),
        estimate=Usd(Decimal("0.12")),
        within_budget=within_budget,
    )


# --- The dialogs, each built as the application builds it -----------------------


def _api_key_dialog(tmp_path: Path) -> QDialog:
    return ApiKeyDialog()


def _bake_dialog(tmp_path: Path) -> QDialog:
    return BakeConfirmDialog(
        BakePreview(
            output_dir=tmp_path,
            page_count=4,
            total_lines=6,
            unreviewed=(),
            failed=(),
            overflowing=(),
        )
    )


def _rerun_within(tmp_path: Path) -> QDialog:
    return RerunDialog(_preview(within_budget=True))


def _rerun_over(tmp_path: Path) -> QDialog:
    return RerunDialog(_preview(within_budget=False))


def _warning_box(tmp_path: Path) -> QDialog:
    """`app.show_warning`'s box, built directly: the static
    `QMessageBox.warning` blocks in `exec`."""
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Settings")
    box.setText(WARNING_TEXT)
    return box


Builder = Callable[[Path], QDialog]

ALL_BUILDERS: dict[str, Builder] = {
    "ApiKeyDialog": _api_key_dialog,
    "BakeConfirmDialog": _bake_dialog,
    "RerunDialog-within-budget": _rerun_within,
    "RerunDialog-over-budget": _rerun_over,
    "QMessageBox-warning": _warning_box,
}

#: AC-6 measures every dialog but the over-budget one (MT-127 AC-1 owns that).
CONTROL_BUILDERS = {k: v for k, v in ALL_BUILDERS.items() if k != "RerunDialog-over-budget"}


def _shown(qtbot, build: Builder, tmp_path: Path) -> tuple[QDialog, QImage]:  # type: ignore[no-untyped-def]
    """The dialog alone, shown, and its own pixels. The dialog is returned so
    the caller holds it: qtbot keeps only a weak reference."""
    dialog = build(tmp_path)
    qtbot.addWidget(dialog)
    dialog.resize(DIALOG_W, DIALOG_H)
    dialog.show()
    qtbot.waitExposed(dialog)
    QApplication.processEvents()
    QApplication.processEvents()
    return dialog, dialog.grab().toImage()


def _edge_line(image: QImage, depth: int) -> dict[str, set[str]]:
    """Per edge, the colours along the line `depth` pixels in from that edge,
    with `EMPHASIS` pixels skipped at each end (the corners belong to the
    perpendicular edges' border)."""
    w, h = image.width(), image.height()

    def at(x: int, y: int) -> str:
        return image.pixelColor(x, y).name()

    return {
        "top": {at(x, depth) for x in range(EMPHASIS, w - EMPHASIS)},
        "bottom": {at(x, h - 1 - depth) for x in range(EMPHASIS, w - EMPHASIS)},
        "left": {at(depth, y) for y in range(EMPHASIS, h - EMPHASIS)},
        "right": {at(w - 1 - depth, y) for y in range(EMPHASIS, h - EMPHASIS)},
    }


def _all_edges(colour: str) -> dict[str, set[str]]:
    return {edge: {colour} for edge in EDGES}


def _assert_two_pixel_window_text_edge(dialog: QDialog, image: QImage, name: str) -> None:
    """The 2px edge test: line 0, line 1, line 2, asserted in that order so a
    failure names the line."""
    window_text = QColor(PALETTE["WindowText"]).name()
    window = QColor(PALETTE["Window"]).name()

    assert dialog.styleSheet() == "", f"{name} must take its border from the application sheet"
    line0 = _edge_line(image, 0)
    assert line0 == _all_edges(window_text), (
        f"under High Contrast {name}'s outermost line (line 0) is not WindowText "
        f"({window_text}) on every side: no e2 border at all. Got {line0}"
    )
    line1 = _edge_line(image, 1)
    assert line1 == _all_edges(window_text), (
        f"under High Contrast {name}'s line 1 is not WindowText ({window_text}) on "
        f"every side: the border is narrower than {EDGE_WIDTH}. Got {line1}"
    )
    line2 = _edge_line(image, 2)
    assert line2 == _all_edges(window), (
        f"under High Contrast {name}'s line 2 is not the Window ground ({window}) on "
        f"every side: the border is wider than {EDGE_WIDTH}, or a child reaches it. "
        f"Got {line2}"
    )


def _template_rules(template: str) -> list[tuple[str, dict[str, str]]]:
    """(selector, {property: value}) per rule of an UNRENDERED template, parsed
    with the generator's own regexes (`tests/ui/test_theme_apply.py`'s shape).

    `tokens._RULE` cannot see past a `{`, so each `@{name}` is first rewritten
    brace-free as `@<name>`; the values returned are then MAPPED BACK to
    `@{name}`, so assertions compare against the template's own spelling."""
    rewritten = tokens._PLACEHOLDER.sub(lambda m: f"@<{m.group(1)}>", template)
    stripped = tokens._COMMENT.sub("", rewritten)
    parsed = []
    for match in tokens._RULE.finditer(stripped):
        selector = " ".join(match.group(1).split())
        body = match.group(0)[match.group(0).index("{") + 1 : -1]
        declarations: dict[str, str] = {}
        for part in body.split(";"):
            if ":" in part:
                prop, value = part.split(":", 1)
                restored = re.sub(r"@<([^>]+)>", r"@{\1}", " ".join(value.split()))
                declarations[prop.strip()] = restored
        parsed.append((selector, declarations))
    return parsed


def _rules_for(selector: str) -> list[dict[str, str]]:
    return [
        decls
        for found, decls in _template_rules(HC_IN.read_text(encoding="utf-8"))
        if found == selector
    ]


# --- Preconditions: the colours and widths this file compares are distinct ------


def test_the_hc_palette_window_text_and_window_are_no_tokens_colour() -> None:
    """Without this an edge of WindowText, or a line 2 of Window, could have
    come from some token's rule rather than from the palette."""
    used = _token_colours_used()
    for role in ("WindowText", "Window"):
        assert QColor(PALETTE[role]).name() not in used, (
            f"the test palette's {role} {PALETTE[role]} is a token's value"
        )
    assert QColor(PALETTE["WindowText"]).name() != QColor(PALETTE["Window"]).name()
    assert set(PALETTE) == set(tokens.HC_ROLES), "the palette must carry exactly the five roles"


def test_the_emphasis_width_is_two_pixels_and_differs_from_the_hairline() -> None:
    """The edge test's three lines mean 2px only if emphasis is 2; and a 1px
    hairline must be distinguishable from it (AC-4)."""
    assert EMPHASIS == 2, f"{EDGE_WIDTH} is {EMPHASIS}; the edge test's lines assume 2"
    assert int(tokens_gen.TOKENS[HAIRLINE]) != EMPHASIS


@pytest.mark.parametrize("name", list(ALL_BUILDERS))
def test_every_measured_dialog_is_large_enough_for_three_edge_lines(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    name: str,
) -> None:
    """Under the HC sheet, each grab is at least 3 * emphasis + 1 on each axis
    and every edge run of lines 0-2 is non-empty - a size, not a fixed one: a
    QMessageBox may refuse `resize` below its layout minimum."""
    application_sheet(_hc_theme())

    _dialog, image = _shown(qtbot, ALL_BUILDERS[name], tmp_path)

    floor = 3 * EMPHASIS + 1
    assert image.width() >= floor and image.height() >= floor, (
        f"{name} grabbed at {image.width()}x{image.height()}"
    )
    for depth in LINES:
        runs = _edge_line(image, depth)
        assert all(runs[edge] for edge in EDGES), f"{name}: an empty line-{depth} run: {runs}"


# --- AC-1 to AC-5: the 2px WindowText edge under High Contrast -------------------


def test_under_high_contrast_the_api_key_dialog_has_a_two_pixel_window_text_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-1: the HC sheet; ApiKeyDialog() shown alone passes the 2px edge test."""
    application_sheet(_hc_theme())

    dialog, image = _shown(qtbot, _api_key_dialog, tmp_path)

    _assert_two_pixel_window_text_edge(dialog, image, "the API key dialog")


def test_under_high_contrast_the_bake_dialog_has_a_two_pixel_window_text_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-2: the HC sheet; BakeConfirmDialog(preview) shown alone passes."""
    application_sheet(_hc_theme())

    dialog, image = _shown(qtbot, _bake_dialog, tmp_path)

    _assert_two_pixel_window_text_edge(dialog, image, "the bake dialog")


def test_under_high_contrast_a_run_again_dialog_within_budget_has_a_two_pixel_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-3: the HC sheet; RerunDialog within budget shown alone passes."""
    application_sheet(_hc_theme())

    dialog, image = _shown(qtbot, _rerun_within, tmp_path)

    assert dialog.property("overBudget") is False, "precondition: MT-125's property"
    _assert_two_pixel_window_text_edge(dialog, image, "the within-budget Run again dialog")


def test_under_high_contrast_an_over_budget_run_again_dialog_is_two_pixels_not_a_hairline(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-4: the HC sheet; RerunDialog over budget shown alone passes. The base
    hairline rule outranks `QDialog` on specificity, so without the HC
    `RerunDialog[overBudget="true"]` width rule this fails on line 1 (DV-2)."""
    application_sheet(_hc_theme())

    dialog, image = _shown(qtbot, _rerun_over, tmp_path)

    assert dialog.property("overBudget") is True, "precondition: MT-125's property"
    _assert_two_pixel_window_text_edge(dialog, image, "the over-budget Run again dialog")


def test_under_high_contrast_the_settings_warning_box_has_a_two_pixel_window_text_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-5: the HC sheet; the settings warning QMessageBox (Warning icon,
    title Settings, one line) shown alone passes."""
    application_sheet(_hc_theme())

    dialog, image = _shown(qtbot, _warning_box, tmp_path)

    _assert_two_pixel_window_text_edge(dialog, image, "the settings warning box")


# --- AC-6: control - the non-HC sheet gains no dialog border --------------------


@pytest.mark.parametrize("name", list(CONTROL_BUILDERS))
def test_control_under_the_packaged_sheet_a_dialog_edge_is_its_ground(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    name: str,
) -> None:
    """AC-6: the packaged theme.qss; lines 0 and 1 of every edge are
    color.surface.base and nothing else. Line 2 too: C-4's check that the
    instrument reads the dialog's ground, not a child, on every line the HC
    tests sample."""
    application_sheet(_packaged("theme.qss"))

    dialog, image = _shown(qtbot, CONTROL_BUILDERS[name], tmp_path)

    assert dialog.styleSheet() == "", f"{name} must take its ground from the application sheet"
    ground = _token_colour(GROUND)
    for depth in (0, 1):
        line = _edge_line(image, depth)
        assert line == _all_edges(ground), (
            f"under the packaged sheet {name}'s line {depth} is not its ground {GROUND} "
            f"({ground}) on every side: the non-HC sheet gained a dialog border. Got {line}"
        )
    line2 = _edge_line(image, 2)
    assert line2 == _all_edges(ground), (
        f"under the packaged sheet {name}'s line 2 is not its ground ({ground}): a child "
        f"reaches line 2, so the HC line-2 assertion would measure the child. Got {line2}"
    )


# --- AC-7: the two rules as written in the design input --------------------------


def test_the_high_contrast_template_gives_every_dialog_an_emphasis_window_text_border() -> None:
    """AC-7, first rule: `theme_hc.qss.in` carries a rule whose selector is
    exactly `QDialog` with a `border` reading `@{border-width.emphasis}` and
    `@{hc.WindowText}`, and no literal pixel number."""
    rules = _rules_for("QDialog")

    assert rules, "theme_hc.qss.in has no rule whose selector is exactly QDialog"
    borders = [decls["border"] for decls in rules if "border" in decls]
    assert any(
        "@{border-width.emphasis}px" in value and "@{hc.WindowText}" in value for value in borders
    ), f"no QDialog border reads @{{border-width.emphasis}}px and @{{hc.WindowText}}: {rules}"
    for decls in rules:
        for prop, value in decls.items():
            assert not LITERAL_PX.search(value), f"QDialog {prop}: {value} is a literal width"


def test_the_high_contrast_run_again_dialog_rule_restates_only_the_emphasis_width() -> None:
    """AC-7, second rule: `RerunDialog[overBudget="true"]` in theme_hc.qss.in
    has exactly one declaration, `border-width: @{border-width.emphasis}px` -
    no `border`, no `border-color`, no `@{hc.*}`: the colour still arrives
    through the base token map (§10.9)."""
    rules = _rules_for('RerunDialog[overBudget="true"]')

    assert rules, 'theme_hc.qss.in has no rule whose selector is RerunDialog[overBudget="true"]'
    assert rules == [{"border-width": "@{border-width.emphasis}px"}], (
        f"the over-budget Run again dialog's HC rule must restate only the width: {rules}"
    )
    for decls in rules:
        for prop, value in decls.items():
            assert "@{hc." not in value, f"{prop}: {value} restates a colour"
            assert not LITERAL_PX.search(value), f"{prop}: {value} is a literal width"
