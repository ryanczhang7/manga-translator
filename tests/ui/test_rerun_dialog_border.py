"""MT-127: the Run again dialog takes the warning hairline when over budget.

`components.md` §9 `RerunDialog`, budget row: *"The frame takes
`CostEstimate`'s warning hairline; the sentence carries the state (A-10)."*
`RerunDialog` (MT-125) sets the dynamic property `overBudget` before first
polish; this file pins the stylesheet rule that reads it, as **paint**, through
the real theme path - the packaged `theme.qss` (or the composed High Contrast
sheet) set as the *application* sheet, never `styleSheet()` on the widget.

Technique mirrored from `tests/ui/test_cost_estimate.py` ("AC-3's colour, as
paint"); its helpers are private to that module (`tests` is not a package), so
the ones needed are copied here. Differences, per the story's C-4: the dialog is
measured alone (the rule is unscoped), and the corners are skipped by one
hairline only - a top-level dialog has no radius.

Oracle partition (story `## Contract` C-5):

- **Settled, read out:** `color.status.warning`, `color.surface.base` and
  `border-width.hairline` from `tokens_gen.TOKENS`; the HC mapping through
  `theme.compose_stylesheet`.
- **Mechanical, pinned exactly:** every edge's colour set, the widget's own
  `styleSheet() == ""`, and no `RerunDialog` selector in `theme_hc.qss.in`.
- **Oracle-free:** none.

RED: the module exists, so nothing fails at import. The paint tests that need
the rule (AC-1, AC-3, AC-4's paint) fail on their edge assertion: the edge
comes back as the dialog's ground. AC-1's no-sheet control, AC-2 and AC-4's
text half pass on arrival by design (absence checks); the story's handoff says
why each is admissible.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from mangatl.domain.money import Usd
from mangatl.pipeline.resume import RerunPreview
from mangatl.ui import theme, tokens, tokens_gen
from mangatl.ui.rerun_dialog import RerunDialog
from mangatl.ui.stylesheet import base_template, hc_template

REPO = Path(__file__).resolve().parents[2]
DESIGN = REPO / "docs" / "wiki" / "design"
HC_IN = DESIGN / "theme_hc.qss.in"

#: components.md §9 / §2: the over-budget edge, its width, and the ground.
EDGE_OVER = "color.status.warning"
EDGE_WIDTH = "border-width.hairline"
GROUND = "color.surface.base"

#: A colour no token uses (asserted below); MT-061's AC-6 sentinel.
SENTINEL = "#13579B"

#: A five-role contrast palette. `WindowText` is a colour no token uses
#: (asserted below), so an edge of that colour can only have come from here.
PALETTE: dict[str, str] = {
    "Window": "#010203",
    "WindowText": "#FDFEFF",
    "Highlight": "#1A2B3C",
    "HighlightedText": "#C3B2A1",
    "DisabledText": "#4D5E6F",
}

#: Long edges, so each edge's run is hundreds of pixels (C-4).
DIALOG_W, DIALOG_H = 480, 240

EDGES = ("top", "bottom", "left", "right")


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


def _sentinel_theme(token: str) -> str:
    """The packaged template rendered with `token` = SENTINEL (MT-061 AC-6)."""
    values = dict(tokens_gen.TOKENS)
    values[token] = SENTINEL
    return tokens.render_qss(values, _packaged("theme.qss.tmpl"))


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


def _shown_dialog(qtbot, *, within_budget: bool) -> tuple[RerunDialog, QImage]:  # type: ignore[no-untyped-def]
    """The dialog alone, shown, and its own pixels. The dialog is returned so
    the caller holds it: qtbot keeps only a weak reference."""
    dialog = RerunDialog(_preview(within_budget=within_budget))
    qtbot.addWidget(dialog)
    dialog.resize(DIALOG_W, DIALOG_H)
    dialog.show()
    qtbot.waitExposed(dialog)
    QApplication.processEvents()
    QApplication.processEvents()
    return dialog, dialog.grab().toImage()


def _edge_colours(image: QImage) -> dict[str, set[str]]:
    """The colours along the middle line of each edge of the hairline,
    stopping one hairline short of each corner (no radius on a dialog)."""
    width = int(tokens_gen.TOKENS[EDGE_WIDTH])
    inset = width
    w, h, mid = image.width(), image.height(), width // 2

    def at(x: int, y: int) -> str:
        return image.pixelColor(x, y).name()

    return {
        "top": {at(x, mid) for x in range(inset, w - inset)},
        "bottom": {at(x, h - 1 - mid) for x in range(inset, w - inset)},
        "left": {at(mid, y) for y in range(inset, h - inset)},
        "right": {at(w - 1 - mid, y) for y in range(inset, h - inset)},
    }


def _all_edges(colour: str) -> dict[str, set[str]]:
    return {edge: {colour} for edge in EDGES}


# --- Preconditions: the colours this file compares are distinguishable ----------


def test_the_sentinel_and_the_hc_window_text_are_no_tokens_colour() -> None:
    """Without this, an edge of the sentinel or of WindowText could have come
    from some other token's rule rather than from the substitution."""
    used = _token_colours_used()
    assert QColor(SENTINEL).name() not in used, f"{SENTINEL} is a token's value"
    assert QColor(PALETTE["WindowText"]).name() not in used, (
        f"the test palette's WindowText {PALETTE['WindowText']} is a token's value"
    )
    assert set(PALETTE) == set(tokens.HC_ROLES), "the palette must carry exactly the five roles"


def test_the_warning_edge_and_the_ground_are_different_colours() -> None:
    """Without this AC-1 and AC-2 could not tell an edge from the ground."""
    assert _token_colour(EDGE_OVER) != _token_colour(GROUND)


def test_the_measured_dialog_is_large_enough_to_have_four_edge_runs(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The grab is the dialog's own size offscreen, so every edge run below
    holds hundreds of pixels, not none."""
    _dialog, image = _shown_dialog(qtbot, within_budget=False)

    assert (image.width(), image.height()) == (DIALOG_W, DIALOG_H)
    runs = _edge_colours(image)
    assert all(runs[edge] for edge in EDGES), f"an empty edge run: {runs}"


# --- AC-1: the packaged sheet paints the over-budget dialog's hairline ----------


def test_an_over_budget_run_again_dialog_is_framed_in_the_warning_hairline(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-1: packaged theme.qss as the application sheet, `within_budget`
    False - the middle line of every edge is color.status.warning and nothing
    else, and the colour comes from the application sheet, not the widget."""
    application_sheet(_packaged("theme.qss"))

    dialog, image = _shown_dialog(qtbot, within_budget=False)

    assert dialog.property("overBudget") is True, "precondition: MT-125's property"
    assert dialog.styleSheet() == "", "the dialog must take its border from the application sheet"
    assert _edge_colours(image) == _all_edges(_token_colour(EDGE_OVER)), (
        f"over budget, the Run again dialog's edge is not {EDGE_OVER} "
        f"({_token_colour(EDGE_OVER)}) on every side: no rule reads overBudget"
    )


def test_control_without_the_sheet_an_over_budget_dialog_paints_no_warning_edge(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-1's control: with no application sheet, the same over-budget dialog
    paints no color.status.warning pixel on any edge - the colour is authored
    in theme.qss, not in rerun_dialog.py. Qt's default is not pinned."""
    application_sheet("")

    dialog, image = _shown_dialog(qtbot, within_budget=False)

    assert dialog.property("overBudget") is True, "precondition"
    seen = set().union(*_edge_colours(image).values())
    assert _token_colour(EDGE_OVER) not in seen, (
        f"with no application sheet the over-budget dialog still paints {EDGE_OVER}: "
        f"the colour is authored somewhere other than theme.qss (edges {sorted(seen)})"
    )


# --- AC-2: within budget, no border - the edge is the ground --------------------


def test_a_run_again_dialog_within_budget_gains_no_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-2: packaged sheet, `within_budget` True - no edge pixel is
    color.status.warning, and every edge is the dialog's ground,
    color.surface.base (the `QMainWindow, QDialog` rule)."""
    application_sheet(_packaged("theme.qss"))

    dialog, image = _shown_dialog(qtbot, within_budget=True)

    assert dialog.property("overBudget") is False, "precondition"
    edges = _edge_colours(image)
    assert _token_colour(EDGE_OVER) not in set().union(*edges.values()), (
        f"within budget, the Run again dialog paints {EDGE_OVER} on an edge"
    )
    assert edges == _all_edges(_token_colour(GROUND)), (
        f"within budget, the Run again dialog's edge is not its ground {GROUND} on every side"
    )


# --- AC-3: the rule reads the token ----------------------------------------------


def test_the_over_budget_edge_follows_the_warning_token_in_the_sheet(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-3: the packaged template rendered with color.status.warning = an
    unused sentinel; every edge of the over-budget dialog is the sentinel. A
    colour hard-coded in the rule fails this."""
    application_sheet(_sentinel_theme(EDGE_OVER))

    dialog, image = _shown_dialog(qtbot, within_budget=False)

    assert dialog.property("overBudget") is True, "precondition"
    sentinel = QColor(SENTINEL).name()
    assert _edge_colours(image) == _all_edges(sentinel), (
        f"with {EDGE_OVER} = {sentinel}, the over-budget Run again dialog's edge "
        "painted something else: the rule does not read the token"
    )


# --- AC-4: High Contrast collapses the border to WindowText -----------------------


def test_under_high_contrast_the_over_budget_edge_is_window_text(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
) -> None:
    """AC-4: the sheet composed for High Contrast with the test palette; every
    edge of the over-budget dialog is the palette's WindowText."""
    application_sheet(_hc_theme())

    dialog, image = _shown_dialog(qtbot, within_budget=False)

    assert dialog.property("overBudget") is True, "precondition"
    window_text = PALETTE["WindowText"].lower()
    assert _edge_colours(image) == _all_edges(window_text), (
        f"under High Contrast the over-budget Run again dialog's edge is not "
        f"WindowText ({window_text}) on every side"
    )


def test_the_high_contrast_override_template_has_no_run_again_dialog_rule() -> None:
    """AC-4, text half (§10.9): High Contrast is a value change through
    [hc.map], not a rule change - theme_hc.qss.in names no RerunDialog."""
    text = HC_IN.read_text(encoding="utf-8")

    assert "RerunDialog" not in text, (
        "theme_hc.qss.in carries a RerunDialog rule; §10.9 resolves the border "
        "through the base template's token, not an override"
    )
