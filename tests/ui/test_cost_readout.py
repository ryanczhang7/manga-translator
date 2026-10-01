"""MT-018: the cost readout - `$—` before anything is priced, one warning, a stated basis.

`CostReadout` (new, `mangatl.ui.cost_readout`) is `components.md` §8's
`CostReadout`. Every state, threshold and string below is **settled** - read out
of §8 and the story's `## Contract`, never tuned:

- five run states `unknown` / `normal` / `approaching` / `exceeded` /
  `aborted`, plus the post-run `final` (§8 "idle / post-run", caption "final");
- `unknown` renders `$—` (U+2014) and **never** `$0.00` (AC-5);
- `approaching` at spend >= 75% of the budget **or** projected total >= the
  budget, both inclusive; `exceeded` at spend >= the budget (AC-6);
- the warning is announced through the live region **once per edge** into
  `approaching`/`exceeded`, never per update (AC-6);
- the projection appears only from two samples on and states the basis it
  was *given* - "estimated" or "from N pages" (AC-7, `budget.py`: "reported,
  not inferred").

Money figures are spelled out as literals here **and** cross-checked against
`format_usd` (MT-058's formatter, which the readout reuses) - the literal is
the design's oracle, `format_usd` is the proof the readout did not re-spell it.

AC-6 is asserted in three separate parts (entry, exactly-one, none-after),
because a test asserting only the state passes against a level-triggered
announcement - the story's falsifiable condition 1.

**RED:** fails at import (`mangatl.ui.cost_readout` does not exist), so no
assertion here has run yet. No real-time waits anywhere.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QLabel, QProgressBar

import mangatl.ui.link as link_module
from mangatl.domain.budget import DEFAULT_CEILING, Projection
from mangatl.domain.money import Usd
from mangatl.ui.cost_estimate import format_usd
from mangatl.ui.cost_readout import APPROACHING_FRACTION, CostReadout
from mangatl.ui.link import LiveRegion

# --- Settled strings (components.md §8, story ## Contract), spelled out ------------
DASH = "$\N{EM DASH}"  # "$" and an em dash: nothing is known
ZERO = "$0.00"  # a claim that the run is free - never shown for "unknown"
GLYPH = "\N{WARNING SIGN}"  # warning sign
TWO = Usd(Decimal("2.00"))


def usd(text: str) -> Usd:
    return Usd(Decimal(text))


def observed(remaining: str, samples: int) -> Projection:
    return Projection(
        next_call=usd("0.06"),
        remaining_chapter=usd(remaining),
        basis="observed",
        sample_count=samples,
    )


def estimated(remaining: str, samples: int) -> Projection:
    return Projection(
        next_call=usd("0.06"),
        remaining_chapter=usd(remaining),
        basis="estimate",
        sample_count=samples,
    )


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any, str]]:
    """Replace `mangatl.ui.link.QAccessible` (imported by name, `link.py`) with a
    recorder of (event type, object, the object's accessible name at the time)."""
    posted: list[tuple[Any, Any, str]] = []
    stand_in = SimpleNamespace(
        Event=QAccessible.Event,
        updateAccessibility=lambda event: posted.append(
            (event.type(), event.object(), event.object().accessibleName())
        ),
    )
    monkeypatch.setattr(link_module, "QAccessible", stand_in)
    return posted


def _readout(qtbot) -> CostReadout:  # type: ignore[no-untyped-def]
    readout = CostReadout()
    qtbot.addWidget(readout)
    return readout


def _announced(readout: CostReadout, alerts: list[tuple[Any, Any, str]]) -> list[str]:
    """The texts the readout's own live region announced, in order."""
    return [
        text
        for kind, obj, text in alerts
        if kind == QAccessible.Event.Alert and obj == readout.live_region
    ]


def _label_texts(readout: CostReadout) -> list[str]:
    return [label.text() for label in readout.findChildren(QLabel)]


# =============================================================================
# The settled constants and the shape
# =============================================================================


def test_the_approaching_threshold_is_exactly_75_percent_as_a_decimal() -> None:
    assert isinstance(APPROACHING_FRACTION, Decimal), (
        "APPROACHING_FRACTION is a float: it would be the only float in the money path"
    )
    assert Decimal("0.75") == APPROACHING_FRACTION


def test_the_readout_exposes_its_figure_budget_meter_glyph_projection_and_live_region(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    assert isinstance(readout.figure, QLabel)
    assert isinstance(readout.budget_label, QLabel)
    assert isinstance(readout.meter, QProgressBar)
    assert isinstance(readout.glyph, QLabel)
    assert isinstance(readout.projection_label, QLabel)
    assert isinstance(readout.live_region, LiveRegion)


# =============================================================================
# AC-5: zero priced calls -> "$—", never "$0.00"
# =============================================================================


def test_a_new_readout_has_priced_nothing_and_shows_a_dash_not_zero_dollars(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    assert readout.state() == "unknown"
    assert readout.figure.text() == DASH
    assert not any(ZERO in text for text in _label_texts(readout)), (
        f"an unpriced readout claims the run is free: {_label_texts(readout)}"
    )


def test_with_no_priced_call_the_readout_is_unknown_and_reads_dollar_dash(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)
    readout.set_state(usd("0.83"), TWO, None)  # from a priced state, back to nothing known

    readout.set_state(None, TWO, None)

    assert readout.state() == "unknown"
    assert readout.figure.text() == DASH
    assert readout.meter.value() == 0
    assert readout.projection_label.text() == ""
    assert readout.glyph.text() == ""


def test_an_unknown_readout_shows_zero_dollars_in_none_of_its_labels(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    readout.set_state(None, TWO, observed("1.00", 5))

    texts = _label_texts(readout)
    assert texts, "the readout has no QLabel children at all"
    assert not any(ZERO in text for text in texts), (
        f"$0.00 rendered for a cost nobody has measured: {texts}"
    )


def test_an_unknown_readout_shows_no_projection_even_when_handed_one(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    readout.set_state(None, TWO, observed("1.00", 5))

    assert readout.state() == "unknown"
    assert readout.projection_label.text() == ""


# =============================================================================
# normal: the figure and the budget, formatted by format_usd
# =============================================================================


def test_a_priced_spend_under_75_percent_is_normal_with_figure_and_budget(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    readout.set_state(usd("0.83"), TWO, None)

    assert readout.state() == "normal"
    assert readout.figure.text() == "$0.83" == format_usd(usd("0.83"))
    assert readout.budget_label.text() == "of $2.00" == f"of {format_usd(TWO)}"
    assert readout.glyph.text() == ""
    assert readout.projection_label.text() == ""


def test_the_figure_rounds_a_fraction_of_a_cent_up_as_format_usd_does(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    readout.set_state(usd("0.831"), TWO, None)

    assert readout.figure.text() == "$0.84" == format_usd(usd("0.831"))


def test_the_budget_label_is_the_ceiling_it_was_given(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)

    readout.set_state(usd("0.83"), usd("5.00"), None)

    assert readout.budget_label.text() == "of $5.00"
    assert readout.state() == "normal"


def test_the_readout_publishes_its_state_to_the_stylesheet_as_cost_state(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """Colour comes from theme.qss by dynamic property (MT-061's rule)."""
    readout = _readout(qtbot)
    for spent, expected in (
        (None, "unknown"),
        (usd("0.10"), "normal"),
        (usd("1.60"), "approaching"),
        (usd("2.10"), "exceeded"),
    ):
        readout.set_state(spent, TWO, None)
        assert readout.state() == expected
        assert readout.property("costState") == expected, (
            f"costState is {readout.property('costState')!r} in state {expected!r}"
        )

    readout.mark_aborted()
    assert readout.property("costState") == "aborted"
    readout.show_final(usd("1.00"), TWO)
    assert readout.property("costState") == "final"


# =============================================================================
# AC-6: crossing 75% -> approaching, exactly one announcement, none after
# =============================================================================


def test_crossing_75_percent_of_the_budget_enters_approaching_with_the_warning_glyph(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-6, part 1 of 3: entry."""
    readout = _readout(qtbot)
    readout.set_state(usd("1.20"), TWO, None)
    assert readout.state() == "normal"

    readout.set_state(usd("1.55"), TWO, None)

    assert readout.state() == "approaching"
    assert readout.glyph.text() == GLYPH
    assert readout.figure.text() == "$1.55"


def test_crossing_75_percent_announces_exactly_once_and_says_what_it_is(
    qtbot,  # type: ignore[no-untyped-def]
    alerts: list[tuple[Any, Any, str]],
) -> None:
    """AC-6, part 2 of 3: exactly one announcement, on the crossing."""
    readout = _readout(qtbot)
    readout.set_state(usd("1.20"), TWO, None)
    assert _announced(readout, alerts) == [], "a normal readout announced something"

    readout.set_state(usd("1.55"), TWO, None)

    assert _announced(readout, alerts) == ["Cost $1.55 of $2.00: approaching the budget."]


def test_further_updates_above_75_percent_announce_nothing_more(
    qtbot,  # type: ignore[no-untyped-def]
    alerts: list[tuple[Any, Any, str]],
) -> None:
    """AC-6, part 3 of 3: edge-triggered, not level-triggered. A live region that
    re-announces on every page turns a screen reader into a metronome."""
    readout = _readout(qtbot)
    readout.set_state(usd("1.20"), TWO, None)
    readout.set_state(usd("1.55"), TWO, None)
    assert len(_announced(readout, alerts)) == 1

    for spent in ("1.60", "1.70", "1.80", "1.95"):
        readout.set_state(usd(spent), TWO, observed("0.30", 4))
        assert readout.state() == "approaching"

    assert len(_announced(readout, alerts)) == 1, (
        f"the warning was re-announced while spend stayed above 75%: {_announced(readout, alerts)}"
    )


def test_going_on_from_approaching_to_exceeded_is_not_a_second_announcement(
    qtbot,  # type: ignore[no-untyped-def]
    alerts: list[tuple[Any, Any, str]],
) -> None:
    readout = _readout(qtbot)
    readout.set_state(usd("1.20"), TWO, None)
    readout.set_state(usd("1.55"), TWO, None)

    readout.set_state(usd("2.10"), TWO, None)
    readout.set_state(usd("2.20"), TWO, None)

    assert readout.state() == "exceeded"
    assert len(_announced(readout, alerts)) == 1


def test_exactly_75_percent_is_approaching_and_just_under_is_normal(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """The threshold is inclusive, and exact Decimal: $1.499999 reads "$1.50"
    (format_usd rounds up) and is still under 75% of $2.00."""
    readout = _readout(qtbot)

    readout.set_state(usd("1.49"), TWO, None)
    assert readout.state() == "normal"

    readout.set_state(usd("1.499999"), TWO, None)
    assert readout.state() == "normal"
    assert readout.glyph.text() == ""

    readout.set_state(usd("1.50"), TWO, None)
    assert readout.state() == "approaching", "spend of exactly 75% of the budget is not approaching"
    assert readout.glyph.text() == GLYPH


def test_the_75_percent_threshold_scales_with_the_ceiling(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)
    five = usd("5.00")

    readout.set_state(usd("3.74"), five, None)
    assert readout.state() == "normal"

    readout.set_state(usd("3.75"), five, None)
    assert readout.state() == "approaching"


def test_a_projection_reaching_the_budget_is_approaching_before_spend_reaches_75_percent(
    qtbot,  # type: ignore[no-untyped-def]
    alerts: list[tuple[Any, Any, str]],
) -> None:
    """§8: approaching on spend >= 75% **or** projection >= budget - the projection
    is what warns the user before the guard fires. Inclusive: $0.50 + $1.50 is
    exactly $2.00."""
    readout = _readout(qtbot)

    readout.set_state(usd("0.50"), TWO, observed("1.49", 3))
    assert readout.state() == "normal", "a projected $1.99 against $2.00 is not approaching"
    assert _announced(readout, alerts) == []

    readout.set_state(usd("0.50"), TWO, observed("1.50", 3))
    assert readout.state() == "approaching", "a projected total of exactly $2.00 is approaching"
    assert readout.glyph.text() == GLYPH
    assert _announced(readout, alerts) == ["Cost $0.50 of $2.00: approaching the budget."]


def test_spend_at_the_budget_is_exceeded_with_the_glyph(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)

    readout.set_state(usd("1.99"), TWO, None)
    assert readout.state() == "approaching"

    readout.set_state(usd("2.00"), TWO, None)
    assert readout.state() == "exceeded", "spend of exactly the budget is not exceeded"
    assert readout.glyph.text() == GLYPH
    assert readout.figure.text() == "$2.00"


def test_jumping_straight_from_unknown_to_exceeded_announces_once(
    qtbot,  # type: ignore[no-untyped-def]
    alerts: list[tuple[Any, Any, str]],
) -> None:
    readout = _readout(qtbot)

    readout.set_state(usd("2.10"), TWO, None)
    readout.set_state(usd("2.20"), TWO, None)

    assert readout.state() == "exceeded"
    assert _announced(readout, alerts) == ["Cost $2.10 of $2.00: approaching the budget."]


def test_falling_back_to_normal_and_crossing_again_is_a_second_edge(
    qtbot,  # type: ignore[no-untyped-def]
    alerts: list[tuple[Any, Any, str]],
) -> None:
    """Contract: announced once on **each** transition from unknown/normal into
    approaching/exceeded. A projection can fall back; spend cannot."""
    readout = _readout(qtbot)
    readout.set_state(usd("0.50"), TWO, observed("1.60", 3))
    assert readout.state() == "approaching"
    readout.set_state(usd("0.60"), TWO, observed("1.00", 4))
    assert readout.state() == "normal"

    readout.set_state(usd("0.70"), TWO, observed("1.40", 5))

    assert readout.state() == "approaching"
    assert _announced(readout, alerts) == [
        "Cost $0.50 of $2.00: approaching the budget.",
        "Cost $0.70 of $2.00: approaching the budget.",
    ]


# =============================================================================
# AC-7: the projection, from two samples on, stating its basis
# =============================================================================


def test_an_observed_projection_states_how_many_pages_it_is_from(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    readout.set_state(usd("0.40"), TWO, observed("0.78", 5))

    assert readout.projection_label.text() == "~$1.18 projected (from 5 pages)"
    assert readout.state() == "normal"


def test_an_estimated_projection_says_it_is_estimated(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)

    readout.set_state(usd("0.40"), TWO, estimated("0.78", 2))

    assert readout.projection_label.text() == "~$1.18 projected (estimated)"


def test_the_basis_is_read_from_the_projection_not_inferred_from_its_count(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """`budget.py`: the basis is reported, not inferred. Seven samples with an
    `estimate` basis is still "estimated"; two with `observed` is "from 2 pages"."""
    readout = _readout(qtbot)

    readout.set_state(usd("0.40"), TWO, estimated("0.78", 7))
    assert readout.projection_label.text() == "~$1.18 projected (estimated)"

    readout.set_state(usd("0.40"), TWO, observed("0.78", 2))
    assert readout.projection_label.text() == "~$1.18 projected (from 2 pages)"


@pytest.mark.parametrize("samples", [0, 1])
def test_fewer_than_two_samples_shows_no_projection(qtbot, samples: int) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)

    readout.set_state(usd("0.05"), TWO, estimated("1.14", samples))

    assert readout.projection_label.text() == "", (
        f"a projection was shown from {samples} priced call(s)"
    )


def test_no_projection_at_all_shows_none(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)
    readout.set_state(usd("0.40"), TWO, observed("0.78", 5))

    readout.set_state(usd("0.45"), TWO, None)

    assert readout.projection_label.text() == ""


def test_a_projection_over_the_budget_says_so_in_the_approaching_copy(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """§8 approaching copy: "projected $2.34 — over budget" (U+2014)."""
    readout = _readout(qtbot)

    readout.set_state(usd("0.90"), TWO, observed("1.44", 6))

    assert (
        readout.projection_label.text() == "projected $2.34 \N{EM DASH} over budget (from 6 pages)"
    )
    assert readout.state() == "approaching"


def test_a_projection_landing_exactly_on_the_budget_is_already_over_budget_copy(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    readout.set_state(usd("0.50"), TWO, estimated("1.50", 3))

    assert readout.projection_label.text() == "projected $2.00 \N{EM DASH} over budget (estimated)"


def test_the_projected_total_rounds_a_fraction_of_a_cent_up(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)

    readout.set_state(usd("0.400001"), TWO, observed("0.78", 3))

    assert readout.projection_label.text() == "~$1.19 projected (from 3 pages)"
    assert format_usd(usd("1.180001")) == "$1.19"


# =============================================================================
# aborted (AC-8's readout half) and final (AC-9's readout half)
# =============================================================================


def test_marking_aborted_keeps_the_figure_fills_the_meter_and_announces_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    alerts: list[tuple[Any, Any, str]],
) -> None:
    readout = _readout(qtbot)
    readout.set_state(usd("1.95"), TWO, None)
    before = len(_announced(readout, alerts))

    readout.mark_aborted()

    assert readout.state() == "aborted"
    assert readout.figure.text() == "$1.95", "the figure was not frozen at the aborted spend"
    assert readout.meter.maximum() > readout.meter.minimum()
    assert readout.meter.value() == readout.meter.maximum(), "the meter is not full"
    assert len(_announced(readout, alerts)) == before


def test_marking_an_unpriced_readout_aborted_still_shows_a_dash(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)

    readout.mark_aborted()

    assert readout.state() == "aborted"
    assert readout.figure.text() == DASH


def test_the_final_readout_shows_the_chapter_total_with_a_final_caption(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    readout.show_final(usd("1.37"), TWO)

    assert readout.state() == "final"
    assert readout.figure.text() == "$1.37"
    assert readout.budget_label.text() == "of $2.00 \N{MIDDLE DOT} final"
    assert readout.budget_label.text().endswith("final")


def test_a_final_readout_with_nothing_priced_is_unknown_and_shows_a_dash(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    readout = _readout(qtbot)

    readout.show_final(None, TWO)

    assert readout.state() == "unknown"
    assert readout.figure.text() == DASH
    assert not any(ZERO in text for text in _label_texts(readout))


def test_showing_the_final_total_never_announces_even_above_75_percent(
    qtbot,  # type: ignore[no-untyped-def]
    alerts: list[tuple[Any, Any, str]],
) -> None:
    """`show_final` runs on every `Workspace.load_chapter`; an alert from it would
    change the alert counts the workspace tests already pin."""
    readout = _readout(qtbot)

    readout.show_final(usd("1.90"), TWO)
    readout.show_final(usd("2.40"), TWO)
    readout.show_final(None, TWO)

    assert alerts == [], f"show_final posted accessibility events: {alerts}"


def test_a_final_readout_carries_no_warning_glyph(qtbot) -> None:  # type: ignore[no-untyped-def]
    readout = _readout(qtbot)

    readout.show_final(usd("1.90"), TWO)

    assert readout.state() == "final"
    assert readout.glyph.text() == ""


def test_the_default_ceiling_is_two_dollars_as_the_readout_shows_it() -> None:
    """The literal "of $2.00" above is the design's; this ties it to the domain."""
    assert format_usd(DEFAULT_CEILING) == "$2.00"
