"""`CostReadout`: what the chapter has cost so far, against its budget (MT-018).

`components.md` §8 `CostReadout`, the *during* to `CostEstimate`'s *before*. It
is a widget given values: nothing here reads the store or the pipeline. The
run panel and the review workspace hand it a spend, a ceiling and a projection.

**`$—`, never `$0.00`, when nothing is priced** (AC-5). `unknown` is the state
of a readout that has been told nothing, including a freshly built one
(RED-A1): `$0.00` would be a claim that the run is free.

**The states** are `unknown`, `normal`, `approaching`, `exceeded` and `aborted`
(§8), plus the post-run `final` (§8 "idle / post-run", caption "final").
`approaching` is entered when spend reaches `APPROACHING_FRACTION` of the
ceiling **or** the projected total reaches the ceiling, both inclusive;
`exceeded` when spend reaches the ceiling. The money arithmetic is exact
`Decimal` throughout, and every figure goes through `format_usd`, reused rather
than re-spelled.

**The projection** counts only from `MIN_SAMPLES_FOR_PROJECTION` samples on - it
is neither shown nor allowed to move the state before then, so the warning
glyph never appears with no figure to explain it - and its basis is read from
`Projection.basis`, never inferred from the count (`budget.py`).

**The warning is announced on the edge, not the level** (AC-6): once on each
transition from `unknown`/`normal` into `approaching`/`exceeded`, through the
readout's own `LiveRegion`. `mark_aborted` and `show_final` never announce -
the banner speaks for an abort, and a chapter total opened for review is
history, not a warning.

Spacing comes from the design tokens; every colour and type size comes from
the application stylesheet by object name (MT-061's rule, as `cost_estimate.py`
does). The one thing the widget tells the sheet is its state, as the dynamic
property `costState`, re-polished on every change.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QWidget

from mangatl.domain.budget import MIN_SAMPLES_FOR_PROJECTION, Projection
from mangatl.domain.money import Usd
from mangatl.ui import tokens_gen
from mangatl.ui.cost_estimate import format_usd
from mangatl.ui.labels import plain_label
from mangatl.ui.link import LiveRegion

__all__ = ["APPROACHING_FRACTION", "CostReadout", "CostState"]

#: §8: spend at or above this share of the ceiling is `approaching`.
APPROACHING_FRACTION: Decimal = Decimal("0.75")

CostState = Literal["unknown", "normal", "approaching", "exceeded", "aborted", "final"]

OBJECT_NAME = "cost-readout"
DASH = "$\N{EM DASH}"
GLYPH = "\N{WARNING SIGN}"
#: §8 `unknown` copy, in place of a budget the readout cannot yet hold spend to.
UNKNOWN_CAPTION = "Cost appears after the first page."
#: The meter's resolution: per mille of the ceiling.
METER_MAX = 1000

#: The states an announcement is armed in; entering a warned state from one fires it.
_ARMED: frozenset[str] = frozenset({"unknown", "normal"})
_WARNED: frozenset[str] = frozenset({"approaching", "exceeded"})


def _meter_value(spent: Usd, ceiling: Usd) -> int:
    """Spend as per mille of the ceiling, full at or over it."""
    if spent >= ceiling:
        return METER_MAX
    return int(spent.amount * METER_MAX / ceiling.amount)


class CostReadout(QWidget):
    """The running cost: figure, budget, meter, glyph and projection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(OBJECT_NAME)
        self._state: CostState = "unknown"

        self.glyph = plain_label("cost-glyph", "")
        self.figure = plain_label("cost-figure", DASH)
        self.budget_label = plain_label("cost-budget-label", UNKNOWN_CAPTION)
        self.projection_label = plain_label("cost-projection", "")
        for label in (self.glyph, self.figure, self.budget_label, self.projection_label):
            label.setWordWrap(False)
        self.meter = QProgressBar()
        self.meter.setObjectName("cost-meter")
        self.meter.setRange(0, METER_MAX)
        self.meter.setValue(0)
        self.meter.setTextVisible(False)
        self.meter.setFixedSize(tokens_gen.SPACE_S12, tokens_gen.SPACE_S1)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens_gen.SPACE_S2)
        row.addWidget(self.glyph)
        row.addWidget(self.figure)
        row.addWidget(self.budget_label)
        row.addWidget(self.meter)
        row.addWidget(self.projection_label)

        # Outside the layout and off-screen: read, never seen (components.md §4.9).
        self.live_region = LiveRegion(self)
        self._publish()

    def state(self) -> CostState:
        """The current state, as the stylesheet sees it in `costState`."""
        return self._state

    def set_state(self, spent: Usd | None, ceiling: Usd, projection: Projection | None) -> None:
        """Show `spent` against `ceiling`; announce on entering a warned state."""
        if spent is None:
            self._show_unknown()
            return
        counted = (
            projection
            if projection is not None and projection.sample_count >= MIN_SAMPLES_FOR_PROJECTION
            else None
        )
        total = spent + counted.remaining_chapter if counted is not None else None
        state: CostState
        if spent >= ceiling:
            state = "exceeded"
        elif spent.amount >= APPROACHING_FRACTION * ceiling.amount or (
            total is not None and total >= ceiling
        ):
            state = "approaching"
        else:
            state = "normal"

        previous = self._state
        self.figure.setText(format_usd(spent))
        self.budget_label.setText(f"of {format_usd(ceiling)}")
        self.glyph.setText(GLYPH if state in _WARNED else "")
        self.meter.setValue(_meter_value(spent, ceiling))
        self.projection_label.setText(
            "" if counted is None or total is None else _projection_text(counted, total, ceiling)
        )
        self._set(state)
        if previous in _ARMED and state in _WARNED:
            self.live_region.announce(
                f"Cost {self.figure.text()} of {format_usd(ceiling)}: approaching the budget."
            )

    def mark_aborted(self) -> None:
        """The run stopped at the budget: figure frozen, meter full, no announcement."""
        self.glyph.setText("")
        self.meter.setValue(METER_MAX)
        self._set("aborted")

    def show_final(self, spent: Usd | None, ceiling: Usd) -> None:
        """The chapter's total after the run, or `$—` when nothing was priced.

        Never announces: it runs on every chapter opened for review."""
        if spent is None:
            self._show_unknown()
            return
        self.figure.setText(format_usd(spent))
        self.budget_label.setText(f"of {format_usd(ceiling)} \N{MIDDLE DOT} final")
        self.glyph.setText("")
        self.meter.setValue(_meter_value(spent, ceiling))
        self.projection_label.setText("")
        self._set("final")

    def _show_unknown(self) -> None:
        self.figure.setText(DASH)
        self.budget_label.setText(UNKNOWN_CAPTION)
        self.glyph.setText("")
        self.meter.setValue(0)
        self.projection_label.setText("")
        self._set("unknown")

    def _set(self, state: CostState) -> None:
        self._state = state
        self._publish()

    def _publish(self) -> None:
        """Mirror the state into `costState` and re-polish what the sheet keys on it."""
        self.setProperty("costState", self._state)
        for widget in (self, self.glyph, self.figure, self.meter):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


def _projection_text(projection: Projection, total: Usd, ceiling: Usd) -> str:
    basis = (
        "estimated" if projection.basis == "estimate" else f"from {projection.sample_count} pages"
    )
    if total >= ceiling:
        return f"projected {format_usd(total)} \N{EM DASH} over budget ({basis})"
    return f"~{format_usd(total)} projected ({basis})"
