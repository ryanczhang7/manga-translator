"""MT-074: status glyphs survive one colour (A-15.7, A-10; components.md §10.4, §10.6).

Under a contrast theme every status hue collapses to `WindowText`, so the
silhouette and the text are the only carriers of state. Two places carry state:

- **`CostReadout`** (AC-1, AC-3). Six states - `unknown`, `normal`,
  `approaching`, `exceeded`, `aborted` and the post-run `final` - must each show
  a unique `(text, glyph, meter)` triple, read by `CostReadout.triple()` (story
  Contract block 1). The glyphs are §10.6's: none / none / outline triangle
  (U+25B3) / filled triangle (U+25B2) / filled triangle / none. "Never by hue"
  is a property of `triple()`: it reads three labels and the meter, and no
  colour, so uniqueness over it is uniqueness with every colour removed.
- **The row gutter** (AC-2). `workspace.STATUS_GLYPHS` gives the five line
  statuses pairwise-distinct glyphs, `reverted` a return arrow alone (§10.4);
  a rendered row shows its status's glyph; its accessible name says the status
  in words.

**Oracle partition (story `## Model guidance`).** Everything here is *settled*
or *mechanical*: glyphs, captions and the meter arithmetic are read out of
§10.6, the Contract's expected-triples table and the modules
(`UNKNOWN_CAPTION`, `_meter_value`, `_STATUS_PHRASES`); `triple()`'s
composition and the `GLYPHS` table are pinned exactly. Nothing is tuned.

**The instrument.** `collisions` is the one function the uniqueness claims go
through; its negative control (a deliberately colliding pair) runs in RED,
because it imports nothing new.

**RED.** The new names (`GLYPHS`, `GLYPH_OUTLINE`, `GLYPH_FILLED`,
`ABORTED_CAPTION`, `CostReadout.triple`) are reached as attributes, so the file
collects and each test fails on its own `AttributeError` or assertion.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from itertools import combinations
from typing import Any, get_args

from PySide6.QtCore import Qt

from mangatl.domain.budget import MIN_SAMPLES_FOR_PROJECTION, Projection
from mangatl.domain.line import LINE_STATUSES, Line
from mangatl.domain.money import Usd
from mangatl.ui import cost_readout as cr
from mangatl.ui.cost_readout import UNKNOWN_CAPTION, CostReadout, CostState, _meter_value
from mangatl.ui.link import OrderedRegion
from mangatl.ui.workspace import (
    _STATUS_PHRASES,
    STATUS_GLYPHS,
    TranslationColumn,
    TranslationRow,
)

# --- Settled: components.md §10.6 / §10.4, spelled out by Unicode name -----------
OUTLINE = "\N{WHITE UP-POINTING TRIANGLE}"  # U+25B3, approaching
FILLED = "\N{BLACK UP-POINTING TRIANGLE}"  # U+25B2, exceeded and aborted
RETURN_ARROW = "\N{LEFTWARDS ARROW WITH HOOK}"  # U+21A9, reverted alone (§10.4)
PENCIL = "\N{LOWER RIGHT PENCIL}"  # U+270E, edited - never part of reverted
DASH = "$\N{EM DASH}"
ZERO = "$0.00"
ABORTED_COPY = "Run stopped \N{EM DASH} budget reached"  # §10.6 `aborted`, PO-2
FINAL_SUFFIX = " \N{MIDDLE DOT} final"

#: §10.6's glyph per state, the Contract's `GLYPHS` table.
DESIGN_GLYPHS: dict[str, str] = {
    "unknown": "",
    "normal": "",
    "approaching": OUTLINE,
    "exceeded": FILLED,
    "aborted": FILLED,
    "final": "",
}

TWO = Usd(Decimal("2.00"))

Triple = tuple[str, str, int]


def usd(text: str) -> Usd:
    return Usd(Decimal(text))


# =============================================================================
# The instrument: which pairs of named triples collide
# =============================================================================


def collisions(triples: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Every pair of names whose values are equal, in the mapping's order.

    The one place "unique" is decided: an empty list is the claim, a non-empty
    one is the bug report."""
    return [(a, b) for a, b in combinations(triples, 2) if triples[a] == triples[b]]


def test_the_collision_checker_reports_exactly_the_one_colliding_pair() -> None:
    """Negative control: a deliberate collision between two of six triples is
    reported, and nothing else is."""
    six: dict[str, Triple] = {
        "unknown": ("$— caption", "", 0),
        "normal": ("$0.83 of $2.00", "", 415),
        "approaching": ("$1.50 of $2.00", OUTLINE, 750),
        "exceeded": ("$2.00 of $2.00", FILLED, 1000),
        "aborted": ("$2.00 of $2.00", FILLED, 1000),  # the defect PO-2 removes
        "final": ("$1.00 of $2.00 · final", "", 500),
    }
    assert collisions(six) == [("exceeded", "aborted")]


def test_the_collision_checker_reports_nothing_for_six_distinct_triples() -> None:
    """Each pair differs in exactly one component - text, glyph or meter - so a
    checker that compared only part of the triple would report a collision."""
    six: dict[str, Triple] = {
        "a": ("x", "", 0),
        "b": ("y", "", 0),  # text only vs a
        "c": ("x", OUTLINE, 0),  # glyph only vs a
        "d": ("x", "", 1),  # meter only vs a
        "e": ("x", FILLED, 0),  # glyph only vs c
        "f": ("x", "", 2),  # meter only vs d
    }
    assert collisions(six) == []


# =============================================================================
# Driving the readout through its six states (real Usd values)
# =============================================================================


def _readout(qtbot) -> CostReadout:  # type: ignore[no-untyped-def]
    readout = CostReadout()
    qtbot.addWidget(readout)
    return readout


def _from_labels(readout: CostReadout) -> Triple:
    """Contract block 1's definition of `triple()`, computed from the widgets."""
    text = " ".join(
        t
        for t in (
            readout.figure.text(),
            readout.budget_label.text(),
            readout.projection_label.text(),
        )
        if t
    )
    return (text, readout.glyph.text(), readout.meter.value())


def _to_unknown(r: CostReadout) -> None:
    r.set_state(None, TWO, None)


def _to_normal(r: CostReadout) -> None:
    r.set_state(usd("0.83"), TWO, None)


def _to_approaching(r: CostReadout) -> None:
    r.set_state(usd("1.50"), TWO, None)


def _to_exceeded(r: CostReadout) -> None:
    r.set_state(usd("2.00"), TWO, None)


def _to_aborted(r: CostReadout) -> None:
    r.set_state(usd("2.00"), TWO, None)
    r.mark_aborted()


def _to_final(r: CostReadout) -> None:
    r.show_final(usd("1.00"), TWO)


DRIVERS: dict[str, Callable[[CostReadout], None]] = {
    "unknown": _to_unknown,
    "normal": _to_normal,
    "approaching": _to_approaching,
    "exceeded": _to_exceeded,
    "aborted": _to_aborted,
    "final": _to_final,
}

LIVE = ("unknown", "normal", "approaching", "exceeded", "aborted")


def _six_triples(qtbot) -> dict[str, Triple]:  # type: ignore[no-untyped-def]
    """One fresh readout per state, so no state's text leaks into the next."""
    triples: dict[str, Triple] = {}
    for state, drive in DRIVERS.items():
        readout = _readout(qtbot)
        drive(readout)
        assert readout.state() == state, f"the driver for {state!r} reached {readout.state()!r}"
        triples[state] = readout.triple()
    return triples


# =============================================================================
# Mechanical: the module's names and tables
# =============================================================================


def test_the_glyph_table_gives_every_cost_state_its_10_6_glyph() -> None:
    """AC-1: none / none / outline / filled / filled, and none for `final`;
    keyed by exactly the `CostState` literals."""
    glyphs = cr.GLYPHS
    assert set(glyphs) == set(get_args(CostState)), (
        f"GLYPHS is keyed by {sorted(glyphs)}, not by every CostState"
    )
    assert dict(glyphs) == DESIGN_GLYPHS


def test_the_outline_and_filled_triangles_are_the_10_6_code_points() -> None:
    assert cr.GLYPH_OUTLINE == "\N{WHITE UP-POINTING TRIANGLE}", "approaching is not U+25B3"
    assert cr.GLYPH_FILLED == "\N{BLACK UP-POINTING TRIANGLE}", "exceeded/aborted is not U+25B2"


def test_the_shared_warning_sign_glyph_is_retired() -> None:
    """PO-1: the triangles replace `⚠` in both themes; one name for two states
    is the defect this story removes."""
    assert not hasattr(cr, "GLYPH"), "cost_readout.GLYPH (the shared warning sign) still exists"


def test_the_aborted_caption_is_the_10_6_copy() -> None:
    assert cr.ABORTED_CAPTION == ABORTED_COPY


# =============================================================================
# Mechanical: triple() is exactly the three labels, the glyph and the meter
# =============================================================================


def test_the_triple_is_the_joined_labels_the_glyph_text_and_the_meter_value_in_every_state(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    mismatched = {}
    for state, drive in DRIVERS.items():
        readout = _readout(qtbot)
        drive(readout)
        if readout.triple() != _from_labels(readout):
            mismatched[state] = (readout.triple(), _from_labels(readout))
    assert mismatched == {}, f"triple() is not the labels and the meter: {mismatched}"


def test_the_triple_reads_the_widgets_themselves_not_the_state_that_set_them(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """Sentinels written straight into the labels and meter come back out: a
    `triple()` built from the state, a cache or a table would not see them. An
    empty label is skipped, not joined as a double space."""
    readout = _readout(qtbot)
    _to_normal(readout)
    readout.figure.setText("FIG")
    readout.budget_label.setText("")
    readout.projection_label.setText("PROJ")
    readout.glyph.setText("G")
    readout.meter.setValue(123)

    assert readout.triple() == ("FIG PROJ", "G", 123)


# =============================================================================
# Settled: the six states' triples (Contract table at ceiling $2.00)
# =============================================================================


def test_each_cost_state_renders_the_settled_triple(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-1 and AC-3, the Contract's expected-triples table."""
    expected: dict[str, Triple] = {
        "unknown": (f"{DASH} {UNKNOWN_CAPTION}", "", 0),
        "normal": ("$0.83 of $2.00", "", _meter_value(usd("0.83"), TWO)),
        "approaching": ("$1.50 of $2.00", OUTLINE, _meter_value(usd("1.50"), TWO)),
        "exceeded": ("$2.00 of $2.00", FILLED, _meter_value(usd("2.00"), TWO)),
        "aborted": (f"$2.00 of $2.00 {ABORTED_COPY}", FILLED, _meter_value(usd("2.00"), TWO)),
        "final": (f"$1.00 of $2.00{FINAL_SUFFIX}", "", _meter_value(usd("1.00"), TWO)),
    }
    # The meter column of the table, read back through the module's arithmetic.
    assert [m for _, _, m in expected.values()] == [0, 415, 750, 1000, 1000, 500]

    triples = _six_triples(qtbot)

    wrong = {s: (triples[s], expected[s]) for s in expected if triples[s] != expected[s]}
    assert wrong == {}, f"state: (rendered, settled) - {wrong}"


def test_the_six_cost_state_triples_are_pairwise_distinct(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-1 + AC-3 (A-15.7's testable form): no two states share a triple."""
    triples = _six_triples(qtbot)
    assert collisions(triples) == [], f"states told apart by nothing but hue: {triples}"


def test_the_glyph_column_of_the_six_triples_is_the_glyph_table(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-1: uniqueness alone would pass with the wrong triangle on a state
    whose caption already differs (falsifiable condition 1)."""
    triples = _six_triples(qtbot)
    assert {state: glyph for state, (_, glyph, _) in triples.items()} == cr.GLYPHS


def test_unknown_shows_a_dash_and_never_zero_dollars(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)
    _to_unknown(readout)
    text, _, _ = readout.triple()
    assert text.startswith(DASH), f"unknown reads {text!r}"
    assert ZERO not in text


def test_aborted_ends_with_the_run_stopped_caption(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)
    _to_aborted(readout)
    text, _, _ = readout.triple()
    assert text.endswith(cr.ABORTED_CAPTION), f"aborted reads {text!r}"


def test_aborting_replaces_a_shown_projection_with_the_run_stopped_caption(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """Contract block 1: the caption replaces any projection; figure and budget
    stay frozen."""
    readout = _readout(qtbot)
    readout.set_state(usd("1.90"), TWO, _projection("0.40"))
    assert readout.projection_label.text(), "precondition: a projection is shown"

    readout.mark_aborted()

    assert readout.projection_label.text() == cr.ABORTED_CAPTION
    assert readout.triple() == (f"$1.90 of $2.00 {ABORTED_COPY}", FILLED, 1000)


def _projection(remaining: str) -> Projection:
    return Projection(
        next_call=usd("0.06"),
        remaining_chapter=usd(remaining),
        basis="observed",
        sample_count=MIN_SAMPLES_FOR_PROJECTION,
    )


def test_approaching_entered_by_projection_shows_the_outline_triangle_and_the_projection(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-1 over the projection path: $0.50 spent (25%) with $1.60 still to come
    projects $2.10 over a $2.00 ceiling. The projection text is part of the
    triple and keeps it distinct from every other state."""
    readout = _readout(qtbot)
    readout.set_state(usd("0.50"), TWO, _projection("1.60"))

    assert readout.state() == "approaching"
    projection = readout.projection_label.text()
    assert projection, "the projection that put the readout in approaching is not shown"
    assert readout.triple() == (
        f"$0.50 of $2.00 {projection}",
        OUTLINE,
        _meter_value(usd("0.50"), TWO),
    )

    others = _six_triples(qtbot)
    others["approaching (projected)"] = readout.triple()
    assert collisions(others) == []


def test_the_triples_are_the_same_with_and_without_colour_rules(qtbot) -> None:  # type: ignore[no-untyped-def]
    """ "Never by hue": a stylesheet that recolours every label and the meter
    changes no triple, and the six stay distinct under it."""
    plain = _six_triples(qtbot)

    recoloured: dict[str, Triple] = {}
    for state, drive in DRIVERS.items():
        readout = _readout(qtbot)
        readout.setStyleSheet(
            "QLabel { color: red; background: red; }"
            " QProgressBar { background: red; } QProgressBar::chunk { background: red; }"
        )
        drive(readout)
        readout.ensurePolished()
        recoloured[state] = readout.triple()

    assert recoloured == plain
    assert collisions(recoloured) == []


# =============================================================================
# AC-3: `final` is a sixth state, not `normal`
# =============================================================================


def test_final_differs_from_every_live_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    triples = _six_triples(qtbot)
    same = [state for state in LIVE if triples[state] == triples["final"]]
    assert same == [], f"final reads as {same}: {triples['final']}"


def test_final_differs_from_normal_at_the_same_spend_by_its_final_caption_only(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    normal = _readout(qtbot)
    normal.set_state(usd("1.00"), TWO, None)
    assert normal.state() == "normal"
    final = _readout(qtbot)
    final.show_final(usd("1.00"), TWO)

    n_text, n_glyph, n_meter = normal.triple()
    f_text, f_glyph, f_meter = final.triple()

    assert (f_glyph, f_meter) == (n_glyph, n_meter), "final and normal differ by more than text"
    assert f_text == n_text + FINAL_SUFFIX
    assert f_text != n_text


# =============================================================================
# AC-2: the five gutter glyphs, the rendered row, the accessible name
# =============================================================================


def _status_line(status: str, index: int = 0) -> Line:
    """One representative line per status (test_line_review_workspace's shape)."""
    failed = status == "failed"
    return Line(
        reading_index=index,
        source_ja="" if failed else f"ja {index}",
        proposed_en=None if failed else "Hello.",
        final_en={"edited": "Mine", "reverted": "Hello."}.get(status),
        status=status,  # type: ignore[arg-type]
        edited_at=None,
        ocr_empty=failed,
    )


def test_the_status_glyphs_are_five_pairwise_distinct_glyphs() -> None:
    """AC-2: exactly the five statuses, no two sharing a glyph."""
    assert tuple(STATUS_GLYPHS) == LINE_STATUSES
    assert all(STATUS_GLYPHS.values()), f"a status has no glyph: {STATUS_GLYPHS}"
    assert collisions(STATUS_GLYPHS) == [], f"statuses sharing a glyph: {STATUS_GLYPHS}"


def test_the_status_glyph_for_reverted_is_the_return_arrow_alone() -> None:
    """§10.4: under one colour an outlined pencil with an arrow is not told
    apart from `edited`'s pencil; `reverted` is the arrow and nothing else."""
    assert STATUS_GLYPHS["reverted"] == RETURN_ARROW
    assert PENCIL not in STATUS_GLYPHS["reverted"]


def test_a_rendered_row_shows_its_status_glyph_in_the_gutter(qtbot) -> None:  # type: ignore[no-untyped-def]
    shown = {}
    for status in LINE_STATUSES:
        row = TranslationRow(0, _status_line(status), None)
        qtbot.addWidget(row)
        assert row.editor.status == status, f"the row for {status!r} is {row.editor.status!r}"
        shown[status] = row.gutter.text()
    assert shown == STATUS_GLYPHS


def test_each_rows_accessible_name_names_its_status_in_words(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The name is the column item's `AccessibleTextRole` (TranslationColumn
    `_describe`), status phrase last (§5)."""
    column = TranslationColumn()
    qtbot.addWidget(column)
    lines = [_status_line(status, i) for i, status in enumerate(LINE_STATUSES)]
    regions = [
        OrderedRegion(region_id=i, polygon=((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)))
        for i in range(len(lines))
    ]
    column.set_rows(
        regions,
        [line.source_ja or None for line in lines],
        [line.proposed_en for line in lines],
        lines=lines,
    )
    names = {
        status: column.list.item(i).data(Qt.ItemDataRole.AccessibleTextRole)
        for i, status in enumerate(LINE_STATUSES)
    }

    unnamed = {
        status: names[status]
        for status, phrase in _STATUS_PHRASES.items()
        if not names[status].endswith(f" {phrase}.")
    }
    assert unnamed == {}, f"rows whose accessible name does not end with their status: {unnamed}"
    assert "translation failed" in names["failed"], names["failed"]
    assert set(_STATUS_PHRASES) | {"failed"} == set(LINE_STATUSES)


def test_a_line_typed_without_a_proposal_is_announced_as_its_text_not_as_not_translated(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """MT-098 AC-1 (MT-017 C-8): "not translated" needs neither a proposal nor
    committed text. A failed line typed into commits `edited` with no proposal,
    and its accessible name reads the text that was typed."""
    column = TranslationColumn()
    qtbot.addWidget(column)
    region = OrderedRegion(region_id=0, polygon=((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)))
    line = Line(
        reading_index=0,
        source_ja="一",
        proposed_en=None,
        final_en="Mine.",
        status="edited",
        edited_at=None,
    )
    column.set_rows([region], ["一"], [None], lines=[line])

    name = column.list.item(0).data(Qt.ItemDataRole.AccessibleTextRole)

    assert "not translated" not in name, ascii(name)
    assert name == "Bubble 1 of 1. Japanese: 一. English: Mine.. edited.", ascii(name)
