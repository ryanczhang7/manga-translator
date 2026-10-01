"""MT-063 AC-1, panel half: `CallPriced` reaches the progress panel's cost readout.

"... and the progress panel's cost readout shows that spend." The contract pins
the wiring: `RunProgressPanel.on_event(CallPriced)` calls
`self.cost_readout.set_state(event.spent, event.ceiling, event.projection)`,
with the **event's** ceiling and not the one the panel was constructed with.
How the readout renders what it is given is MT-018's and settled; this file
uses it as the oracle (a reference `CostReadout` handed the same three values)
and spells the copy out as literals only where MT-018's tests already pin it.

Two levels: synthetic events fed by hand (the wiring, and the ceiling
discriminator), and one real `run_chapter` over a three-page chapter whose
events go straight into `panel.on_event` - the path a user walks.

**RED:** `from mangatl.domain.events import CallPriced` fails, so this file fails
at import and no assertion here has run. No real-time waits anywhere.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from mangatl.domain.budget import DEFAULT_CEILING, Projection
from mangatl.domain.events import CallPriced, PageStarted, RunEvent, RunStarted, StageFinished
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.pipeline.runner import run_chapter
from mangatl.pipeline.stages import build_stages
from mangatl.store.intake import read_chapter
from mangatl.store.project import create_project, project_dir_for
from mangatl.ui.cost_readout import CostReadout
from mangatl.ui.progress import RunProgressPanel

if TYPE_CHECKING:
    from mangatl.domain.glossary import PromptContext

DASH = "$\N{EM DASH}"


def usd(text: str) -> Usd:
    return Usd(Decimal(text))


#: Spend $1.60 against the event's $5.00 ceiling is `normal` (under 75%, and the
#: projected total $1.80 is under the ceiling); against the panel's default
#: $2.00 it would be `approaching` (80%) and the label would read "of $2.00".
#: So a panel that used its own ceiling fails on state, label and meter alike.
_EVENT_CEILING = usd("5.00")
_PROJECTION = Projection(
    next_call=usd("0.10"), remaining_chapter=usd("0.20"), basis="observed", sample_count=2
)
_EVENT = CallPriced(ordinal=3, spent=usd("1.60"), ceiling=_EVENT_CEILING, projection=_PROJECTION)


def _panel(qtbot, **kwargs) -> RunProgressPanel:  # type: ignore[no-untyped-def]
    panel = RunProgressPanel(**kwargs)
    qtbot.addWidget(panel)
    panel.show()
    return panel


def _shown(readout: CostReadout) -> tuple[str, str, str, str, int, str]:
    """Everything the readout shows a user, in one comparable tuple."""
    return (
        readout.state(),
        readout.figure.text(),
        readout.budget_label.text(),
        readout.projection_label.text(),
        readout.meter.value(),
        readout.glyph.text(),
    )


# =============================================================================
# The wiring: CallPriced -> cost_readout.set_state(spent, ceiling, projection)
# =============================================================================


def test_a_call_priced_event_shows_its_spend_in_the_panels_cost_readout(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    panel.on_event(RunStarted(run_id=1, page_count=20))
    assert panel.cost_readout.figure.text() == DASH, "the readout showed a spend before any call"

    panel.on_event(_EVENT)

    assert panel.cost_readout.figure.text() == "$1.60", (
        "CallPriced reached the panel and the cost readout does not show its spend"
    )
    assert panel.cost_readout.state() == "normal"


def test_the_readout_shows_exactly_what_set_state_shows_for_the_events_three_values(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """The contract's call, observed by its result: a reference `CostReadout`
    handed `(spent, ceiling, projection)` directly must look identical to the
    panel's after the event - figure, budget, projection, meter, glyph, state."""
    panel = _panel(qtbot)
    reference = CostReadout()
    qtbot.addWidget(reference)

    panel.on_event(_EVENT)
    reference.set_state(_EVENT.spent, _EVENT.ceiling, _EVENT.projection)

    assert _shown(panel.cost_readout) == _shown(reference)
    assert _shown(reference) == (
        "normal",
        "$1.60",
        "of $5.00",
        "~$1.80 projected (from 2 pages)",
        320,
        "",
    )


def test_the_readout_uses_the_events_ceiling_not_the_panels_constructor_ceiling(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """The panel is built with $2.00; the event carries $5.00. The event's wins:
    `budget_for(project)` is where the run's ceiling comes from, and the panel's
    constructor argument is only what its abort banner quotes."""
    panel = _panel(qtbot, ceiling=DEFAULT_CEILING)
    assert usd("2.00") == DEFAULT_CEILING != _EVENT_CEILING

    panel.on_event(_EVENT)

    assert panel.cost_readout.budget_label.text() == "of $5.00", (
        "the readout was given the panel's own ceiling, not the event's"
    )
    assert panel.cost_readout.state() == "normal", (
        "$1.60 is 'approaching' only against the panel's $2.00;"
        " against the event's $5.00 it is normal"
    )
    assert panel.cost_readout.meter.value() == 320


def test_each_call_priced_replaces_the_last_one(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)

    panel.on_event(_EVENT)
    panel.on_event(
        CallPriced(ordinal=4, spent=usd("1.70"), ceiling=_EVENT_CEILING, projection=_PROJECTION)
    )

    assert panel.cost_readout.figure.text() == "$1.70"


def test_call_priced_leaves_the_rest_of_the_panel_where_it_was(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The new branch is a cost branch only: the page label, the stepper and
    the elapsed time are what they were before the event, and the translate
    `StageFinished` after it still advances the stepper."""
    panel = _panel(qtbot)
    for event in (
        RunStarted(run_id=1, page_count=20),
        PageStarted(ordinal=3),
        StageFinished(ordinal=3, stage="detect", elapsed_ms=1000),
        StageFinished(ordinal=3, stage="ocr", elapsed_ms=2000),
    ):
        panel.on_event(event)
    before = (
        panel.overall_label.text(),
        panel.overall.value(),
        panel.stepper.step_states(),
        panel.elapsed_label.text(),
    )

    panel.on_event(_EVENT)

    assert (
        panel.overall_label.text(),
        panel.overall.value(),
        panel.stepper.step_states(),
        panel.elapsed_label.text(),
    ) == before
    assert panel.banner is None
    panel.on_event(StageFinished(ordinal=3, stage="translate", elapsed_ms=3000))
    assert panel.stepper.step_states() == ("done", "done", "done", "done")


# =============================================================================
# The path a user walks: a real run, its events straight into the panel
# =============================================================================

_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

#: Costs hand-worked in `tests/core/test_call_priced.py`: 40,000 / 60,000 /
#: 40,000 micro-dollars, so the running figure is $0.04, $0.10, $0.14.
_USAGES: tuple[tuple[str, TokenUsage], ...] = (
    ("claude-opus-5", TokenUsage(2000, 1200, 0, 0)),
    ("claude-sonnet-5", TokenUsage(2000, 5600, 0, 0)),
    ("claude-opus-5", TokenUsage(2000, 1200, 0, 0)),
)


def _png(width: int, height: int, mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


def _mask() -> bytes:
    image = Image.new("1", (8, 8))
    for x in range(4):
        for y in range(4):
            image.putpixel((x, y), 1)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _Translator:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self, image: bytes, results: Sequence[OcrResult], context: PromptContext
    ) -> TranslationResult:
        model_id, usage = _USAGES[self.calls]
        self.calls += 1
        return TranslationResult(
            lines={index: f"EN({result.text})" for index, result in enumerate(results)},
            usage=usage,
            call=CallInfo(request_id=f"msg_{self.calls}", model_id=model_id),
            proposed_terms=(),
        )


def test_a_real_run_drives_the_panels_cost_readout_page_by_page(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """AC-1 end to end: `run_chapter` with the real stage list and a fake
    translator, every event handed to `panel.on_event`. After each priced page
    the readout shows the chapter's spend so far; at the end it shows $0.14 of
    $2.00 with the projection from three pages, nothing remaining."""
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for filename, width, height in _PAGES:
        (source_dir / filename).write_bytes(_png(width, height))
    mask = _mask()

    def detect(image_bytes: bytes) -> Sequence[RawRegion]:
        ring = ((0, 0), (4, 0), (4, 4), (0, 4), (0, 0))
        return (RawRegion(polygon=ring, mask=mask, confidence=1.0, kind="bubble"),)

    def transcribe(image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
        return tuple(OcrResult(text=f"ja-{index}") for index in range(len(regions)))

    panel = _panel(qtbot)
    figures: list[str] = []

    def emit(event: RunEvent) -> None:
        panel.on_event(event)
        if isinstance(event, CallPriced):
            figures.append(panel.cost_readout.figure.text())

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        run_chapter(project, build_stages(detect, transcribe, _Translator()), emit, lambda: False)

    assert figures == ["$0.04", "$0.10", "$0.14"], (
        "the panel's cost readout did not follow the chapter's spend through the run"
    )
    assert panel.cost_readout.state() == "normal"
    assert panel.cost_readout.budget_label.text() == "of $2.00"
    assert panel.cost_readout.projection_label.text() == "~$0.14 projected (from 3 pages)"
