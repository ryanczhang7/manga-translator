"""MT-058: the chapter summary shows the estimated cost against the budget.
MT-100: ... priced on the model the run will actually call.

`CostEstimate` (`mangatl.ui.cost_estimate`, MT-058 C-2) is `ChapterSummary`'s
part 5 (C-3): one line for the estimate, one for the budget, and - above 200
pages - a third warning that this is more pages than a chapter. `format_usd`
(C-1) is the one money formatter: to the cent, rounding a fraction of a cent
**up**.

**MT-100 (C-6) makes the widget take the model it prices against**:
`CostEstimate(pages, model)`, where `model` is a rate-table model id or a
`NoProvider(reason)` when no model can be chosen. The estimate line names the
model (`Estimated for N pages with <model>: $x.`), and the figure is
`Budget(page_estimate=page_estimate(model)).project((), N).remaining_chapter` -
the guard's own arithmetic on that model's per-page figure. `ChapterSummary`
takes the model as a required keyword, and `MainWindow.show_summary` resolves it
from `RunSetup.select_model` (C-5).

Oracle partition (MT-058 and MT-100 `## Contract` C-8):

- **Settled - read out, never re-typed:** every figure comes from
  `mangatl.domain.budget` (`DEFAULT_CEILING`, `page_estimate`, `Budget.project`),
  read through `_estimate` / `_ceiling` below, which import nothing from the
  module under test. The worked examples are spelled out as a second, literal
  oracle: on claude-opus-5 $0.06 for one page, $1.20 for 20, $1.98/$2.04 for
  33/34, $12.00/$12.06 for 200/201; on gemini-3.1-pro-preview (MT-100 AC-1/AC-2)
  $6.00 for 200, $1.98/$2.01 for 66/67. Every string is spelled out here.
- **Control demanded:** each model's boundary, both sides; the inclusive
  ceiling, reached on a test model priced at $0.10 a page (20 pages exactly
  $2.00, normal; 21 over); 200/201; never `$0.00` over 1..250 pages, on both
  shipped models and on a test model whose exact cost is 2 micro-dollars a page.
- **Mechanical:** `format_usd`'s examples, object names, absences
  (`findChild(...) is None`), the scroll description order, the no-provider
  lines (MT-100 AC-4) character for character, and AC-6's shared number.

**How a test moves the per-page figure (MT-100).** MT-058 patched the module
global `BOOTSTRAP_PAGE_ESTIMATE`; the widget no longer reads it. A test now adds
a model to `mangatl.domain.rates.RATES` (`_with_model`), which `price` reads at
call time, and asks the widget to price that model. `DEFAULT_CEILING` is never
patched: `Budget.__init__` binds it as a default argument at definition time.

**The environment.** Every test that reaches `mangatl.app.selected_model` sets
exactly the provider variables it means (`_provider_env`), so nothing here reads
the developer's real `GEMINI_API_KEY` (MT-100 C-9). `APPDATA` is a fresh empty
directory per test (`tests/conftest.py`), so no stored key leaks in either.
Every window built by `app.build_window` without a reason to read the
environment is given a `RunSetup` with a fixed `select_model`.

**RED (MT-100):** `NoProvider` and `page_estimate` are read off their modules at
call time and `CostEstimate`/`ChapterSummary` reject the new argument, so each
test fails on its own named absence and `format_usd`'s tests still run.
**Timing:** no real-time waits; the slowest tests build 250 small widgets twice
and two 200-page folders of tiny PNGs.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from decimal import Decimal
from importlib.resources import files
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QWidget,
)

import mangatl.domain.budget as budget
import mangatl.domain.rates as rates_module
import mangatl.translate.provider as provider_module
import mangatl.ui.cost_estimate as cost_estimate_module
from mangatl import app as app_module
from mangatl.domain.budget import Budget
from mangatl.domain.money import Usd
from mangatl.domain.page import Chapter, Page
from mangatl.domain.rates import ModelRates
from mangatl.pipeline.stage import BudgetRefused, PageContext, Stage
from mangatl.pipeline.translate_stage import TranslateStage
from mangatl.store.intake import read_chapter
from mangatl.store.project import create_project, open_project, project_dir_for
from mangatl.translate.provider import AmbiguousProvider, NoApiKey, ProviderError
from mangatl.ui import tokens, tokens_gen
from mangatl.ui.cost_estimate import CostEstimate, format_usd
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.main_window import MainWindow
from mangatl.ui.run import RunSetup
from mangatl.ui.summary import ChapterSummary

# --- Settled strings, spelled out (never read back from the module under test) ------
OVER = "The estimate is over budget."
FRAME = "summary-cost-estimate"
ESTIMATE = "cost-estimate"
BUDGET = "cost-budget"
PAGE_WARNING = "cost-page-warning"
LABELS = (ESTIMATE, BUDGET, PAGE_WARNING)
ZERO = "$0.00"
MORE_THAN_A_CHAPTER = "That is more pages than a chapter."
START = "Start run"
START_ANYWAY = "Start run anyway"

#: The two models a translator calls today (MT-100 C-2), spelled as `RATES` keys.
OPUS = "claude-opus-5"
GEMINI = "gemini-3.1-pro-preview"

#: MT-078's refusals, spelled out (`tests/core/test_translate_provider.py` pins
#: them at the function that raises them).
NO_KEY_TEXT = (
    "no API key is set: set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY,"
    " or run with --no-translate"
)
AMBIGUOUS_TEXT = (
    "API keys are set for more than one provider (anthropic, gemini);"
    " choose one with --provider or MANGATL_PROVIDER"
)
OPENAI_TEXT = "translation with openai is not available yet"
#: MT-059 AC-7's sentence (`tests/ui/test_start_run.py` pins it).
NO_MODELS_TEXT = (
    "No models folder: set MANGATL_MODELS to the folder holding the model"
    " weights, then start the app again."
)

#: Every variable `select_provider` and its callers read.
PROVIDER_VARIABLES = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "MANGATL_PROVIDER")


# --- Figures, read from the domain ---------------------------------------------------


def _per_page(model: str) -> Usd:
    """MT-100 C-1's `page_estimate(model)`, read off the module at call time."""
    figure: Usd = budget.page_estimate(model)
    return figure


def _estimate(pages: int, model: str = OPUS) -> Usd:
    """The figure the widget must show: the guard's projection on `model`."""
    return Budget(page_estimate=_per_page(model)).project((), pages).remaining_chapter


def _ceiling() -> Usd:
    return Budget().ceiling


def _last_page_inside_budget(model: str = OPUS) -> int:
    """MT-058 AC-3's boundary on `model` (33 on opus, 66 on gemini)."""
    return budget.DEFAULT_CEILING.micro() // _per_page(model).micro()


def _estimate_line(pages: int, shown: str, model: str = OPUS) -> str:
    noun = "page" if pages == 1 else "pages"
    return f"Estimated for {pages} {noun} with {model}: {shown}."


def _warning_line(shown: str) -> str:
    return f"{MORE_THAN_A_CHAPTER} Estimated cost is {shown}."


def _no_estimate_line(reason: str) -> str:
    return f"No estimate: {reason}."


def _no_provider(reason: str) -> object:
    """MT-100 C-6's `NoProvider(reason)`, read off the module at call time."""
    return cost_estimate_module.NoProvider(reason)


def _with_model(monkeypatch: pytest.MonkeyPatch, model_id: str, output_rate: str) -> str:
    """Add `model_id` to the rate table, priced on output only at `output_rate`
    dollars per million tokens. Design A's page has 1,500 output tokens, so the
    exact per-page cost is `1500 x output_rate` micro-dollars."""
    table = dict(rates_module.RATES)
    table[model_id] = ModelRates(
        input_per_mtok=Decimal("0"),
        output_per_mtok=Decimal(output_rate),
        cache_write_per_mtok=Decimal("0"),
        cache_read_per_mtok=Decimal("0"),
    )
    monkeypatch.setattr(rates_module, "RATES", table)
    return model_id


def _provider_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """Exactly `values` among the provider variables; the rest deleted."""
    for name in PROVIDER_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


# --- Helpers -------------------------------------------------------------------------


def _cost(qtbot, pages: int, model: object = OPUS) -> CostEstimate:  # type: ignore[no-untyped-def]
    widget = CostEstimate(pages, model)
    qtbot.addWidget(widget)
    return widget


def _label(parent: QWidget, name: str) -> QLabel:
    label = parent.findChild(QLabel, name)
    assert label is not None, f"no QLabel named {name!r}"
    return label


def _absent(parent: QWidget, name: str) -> None:
    assert parent.findChild(QWidget, name) is None, f"{name!r} exists (absent means not created)"


def _lines(widget: QWidget) -> list[str]:
    """The visible lines, in the contract's order, of whichever labels exist."""
    found = [widget.findChild(QLabel, name) for name in LABELS]
    return [label.text() for label in found if label is not None]


def _chapter(count: int, folder: Path = Path("C:/manga/Chapter 12")) -> Chapter:
    """`count` pages, `p1.png … p{count}.png`, in natural order."""
    return Chapter(
        source_dir=folder,
        pages=tuple(
            Page(ordinal=i, filename=f"p{i + 1}.png", width=60, height=80, sha256=f"{i % 10}" * 64)
            for i in range(count)
        ),
    )


def _summary(qtbot, chapter: Chapter, model: object = OPUS) -> ChapterSummary:  # type: ignore[no-untyped-def]
    summary = ChapterSummary(chapter, model=model)
    qtbot.addWidget(summary)
    return summary


def _png() -> bytes:
    image = QImage(QSize(60, 80), QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def _pil_png() -> bytes:
    """A tiny PNG with no QApplication needed (module-scoped fixtures)."""
    out = BytesIO()
    Image.new("RGB", (6, 8), (40, 40, 40)).save(out, format="PNG")
    return out.getvalue()


def _folder_of(root: Path, name: str, pages: int, png: bytes) -> Path:
    """`pages` copies of `png`, zero-padded so no order notice appears."""
    folder = root / name
    folder.mkdir()
    for i in range(1, pages + 1):
        (folder / f"p{i:03d}.png").write_bytes(png)
    return folder


def _no_stages(models_dir: Path) -> Sequence[Stage]:
    return ()


def _fixed(model: str) -> Callable[[], str]:
    """A `select_model` that always answers `model`."""
    return lambda: model


def _refusing(error: ProviderError) -> Callable[[], str]:
    """A `select_model` that always raises `error`, as `select_provider` does."""

    def select() -> str:
        raise error

    return select


def _setup(select_model: Callable[[], str], models: Path | None = None) -> RunSetup:
    return RunSetup(lambda: models, _no_stages, select_model)


def _window_summary(qtbot, chapter: Chapter, setup: RunSetup | None) -> ChapterSummary:  # type: ignore[no-untyped-def]
    window = MainWindow(open_folder=app_module.open_folder, run_setup=setup)
    qtbot.addWidget(window)
    window.show_summary(chapter)
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary), f"central is {type(summary).__name__}"
    return summary


def _start_button(summary: QWidget) -> QPushButton:
    button = summary.findChild(QPushButton, "summary-start")
    assert button is not None, "the summary has no QPushButton named 'summary-start'"
    return button


# =============================================================================
# C-1: format_usd - to the cent, a fraction of a cent rounds UP
# =============================================================================


@pytest.mark.parametrize(
    ("amount", "shown"),
    [
        (Usd.from_micro(60_000), "$0.06"),
        (Usd(Decimal("12.06")), "$12.06"),
        (Usd(Decimal("1200")), "$1,200.00"),
        (Usd(Decimal("1234567.89")), "$1,234,567.89"),
        (Usd.from_micro(0), "$0.00"),
        (Usd(Decimal("1.15")), "$1.15"),
        (Usd(Decimal("2.00")), "$2.00"),
    ],
    ids=["six-cents", "12.06", "thousands", "millions", "zero-is-honest", "1.15", "2.00"],
)
def test_format_usd_shows_dollars_with_thousands_commas_and_exactly_two_decimals(
    amount: Usd, shown: str
) -> None:
    assert format_usd(amount) == shown


def test_format_usd_never_prints_usds_four_place_str() -> None:
    assert str(Usd(Decimal("2.00"))) == "$2.0000", "precondition: str(Usd) prints four places"
    assert format_usd(Usd(Decimal("2.00"))) == "$2.00"


@pytest.mark.parametrize(
    ("amount", "shown"),
    [
        (Usd(Decimal("1.141")), "$1.15"),
        (Usd(Decimal("2.0001")), "$2.01"),
        (Usd.from_micro(1), "$0.01"),
        (Usd.from_micro(10_001), "$0.02"),
        (Usd(Decimal("999.991")), "$1,000.00"),
    ],
    ids=["1.141", "2.0001", "one-micro", "one-cent-and-a-micro", "carries-into-a-comma"],
)
def test_format_usd_rounds_a_fraction_of_a_cent_up_never_to_nearest(
    amount: Usd, shown: str
) -> None:
    """DV-1: half-up and half-even give $1.14, $2.00, $0.00, $0.01, $999.99."""
    assert format_usd(amount) == shown


def test_format_usd_does_not_bump_a_whole_number_of_cents() -> None:
    """The other side of rounding up: a ceiling that adds a cent unconditionally
    shows $1.16."""
    assert format_usd(Usd(Decimal("1.15"))) == "$1.15"
    assert format_usd(Usd(Decimal("1.150000"))) == "$1.15"


def test_format_usd_is_exact_beyond_a_floats_precision() -> None:
    """No float anywhere: `f"{float(x):,.2f}"` shows this as ...456.75."""
    amount = Usd(Decimal("1234567890123456.78"))

    assert format_usd(amount) == "$1,234,567,890,123,456.78"


# =============================================================================
# AC-1: the budget the run will be held to, read-only
# =============================================================================


def test_the_estimate_states_the_budget_of_two_dollars(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 20)

    assert _label(cost, BUDGET).text() == f"Budget {format_usd(_ceiling())}."
    assert _label(cost, BUDGET).text() == "Budget $2.00."


def test_the_budget_is_read_only_with_no_field_and_no_control(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 20)

    for kind in (QLineEdit, QAbstractSpinBox, QAbstractButton):
        assert cost.findChildren(kind) == [], f"the estimate has a {kind.__name__}"
    assert cost.focusPolicy() == Qt.FocusPolicy.NoFocus, "the estimate frame is a focus stop"


def test_the_summary_gains_the_estimate_and_the_start_button_but_no_field(qtbot) -> None:  # type: ignore[no-untyped-def]
    """MT-059 C-2/D-1 rewrote this MT-058 test, which pinned "no button" beyond
    Choose: the summary's buttons are now Start and Choose, as a set."""
    summary = _summary(qtbot, _chapter(34))

    buttons = summary.findChildren(QAbstractButton)
    assert {b.objectName() for b in buttons} == {"summary-start", "summary-choose"}, (
        f"buttons: {[b.objectName() for b in buttons]}"
    )
    assert len(buttons) == 2
    assert summary.findChildren(QLineEdit) == [] and summary.findChildren(QAbstractSpinBox) == []


# =============================================================================
# AC-2 (MT-058): N pages -> "Estimated for N pages with <model>: $x."
# =============================================================================


@pytest.mark.parametrize(
    ("pages", "line"),
    [
        (1, "Estimated for 1 page with claude-opus-5: $0.06."),
        (2, "Estimated for 2 pages with claude-opus-5: $0.12."),
        (20, "Estimated for 20 pages with claude-opus-5: $1.20."),
        (33, "Estimated for 33 pages with claude-opus-5: $1.98."),
        (34, "Estimated for 34 pages with claude-opus-5: $2.04."),
        (200, "Estimated for 200 pages with claude-opus-5: $12.00."),
    ],
    ids=["one", "two", "twenty", "33", "34", "200"],
)
def test_the_estimate_line_reads_the_page_count_the_model_and_its_figure(
    qtbot,  # type: ignore[no-untyped-def]
    pages: int,
    line: str,
) -> None:
    cost = _cost(qtbot, pages, OPUS)
    text = _label(cost, ESTIMATE).text()

    assert text == _estimate_line(pages, format_usd(_estimate(pages, OPUS)), OPUS)
    assert text == line


def test_the_estimate_is_labelled_as_an_estimate(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 20)
    text = _label(cost, ESTIMATE).text()

    assert text.startswith("Estimated for "), f"not labelled as an estimate: {text!r}"


def test_the_shown_figure_follows_the_models_per_page_estimate(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read, not re-typed: a test model at 69,000 micro-dollars a page rounds up
    to $0.07, so 20 pages are $1.40 - neither opus's $1.20 nor gemini's $0.60."""
    model = _with_model(monkeypatch, "test-seven-cents", "46")
    assert _per_page(model) == Usd(Decimal("0.07")), "precondition: 1500 x $46/M, rounded up"

    cost = _cost(qtbot, 20, model)

    assert _label(cost, ESTIMATE).text() == "Estimated for 20 pages with test-seven-cents: $1.40."
    assert _label(cost, ESTIMATE).text() == _estimate_line(
        20, format_usd(_estimate(20, model)), model
    )
    assert not cost.over_budget


# =============================================================================
# MT-100 AC-1 / AC-2 / AC-3: the figure is the selected model's
# =============================================================================


def test_two_hundred_pages_on_gemini_are_six_dollars_and_over_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    """**MT-100 AC-1** at the widget: $6.00, not Claude's $12.00."""
    cost = _cost(qtbot, 200, GEMINI)

    assert _label(cost, ESTIMATE).text() == (
        "Estimated for 200 pages with gemini-3.1-pro-preview: $6.00."
    ), "the Gemini estimate is not $6.00 - is it still priced at Claude's $0.06 a page?"
    assert _label(cost, BUDGET).text() == f"Budget $2.00. {OVER}"
    assert cost.over_budget is True


def test_two_hundred_pages_on_claude_are_twelve_dollars(qtbot) -> None:  # type: ignore[no-untyped-def]
    """**MT-100 AC-3**: Claude keeps Claude's figure."""
    cost = _cost(qtbot, 200, OPUS)

    assert _label(cost, ESTIMATE).text() == "Estimated for 200 pages with claude-opus-5: $12.00."
    assert cost.over_budget is True


def test_the_gemini_boundary_is_sixty_six_pages_read_from_the_domain() -> None:
    """MT-100 AC-2's second, literal oracle for the computed boundary."""
    assert _last_page_inside_budget(GEMINI) == 66
    assert format_usd(_estimate(66, GEMINI)) == "$1.98"
    assert format_usd(_estimate(67, GEMINI)) == "$2.01"


def test_sixty_six_pages_on_gemini_are_within_budget_and_sixty_seven_are_over(qtbot) -> None:  # type: ignore[no-untyped-def]
    """**MT-100 AC-2**: on Claude 34 pages are already over; on Gemini 66 fit."""
    inside = _cost(qtbot, 66, GEMINI)
    over = _cost(qtbot, 67, GEMINI)

    assert _label(inside, ESTIMATE).text() == (
        "Estimated for 66 pages with gemini-3.1-pro-preview: $1.98."
    )
    _assert_normal(inside, 66)
    assert _label(over, ESTIMATE).text() == (
        "Estimated for 67 pages with gemini-3.1-pro-preview: $2.01."
    )
    _assert_over(over, 67)


# =============================================================================
# AC-3 (MT-058): over the budget -> the over-budget state (control: 33 / 34)
# =============================================================================


def _assert_styled_by_the_sheet_alone(cost: CostEstimate, pages: int, over: bool) -> None:
    """C-2 as amended (return 2, MT-061's rule): the widget authors no style;
    the state reaches `theme.qss` as the dynamic property `overBudget`. The
    colour itself is pinned as paint, in the section after AC-5."""
    assert cost.styleSheet() == "", (
        f"{pages} pages: the estimate authors its own style instead of leaving it "
        f"to theme.qss: {cost.styleSheet()!r}"
    )
    assert cost.property("overBudget") is over, (
        f"{pages} pages: overBudget property is {cost.property('overBudget')!r}, not {over}"
    )


def _assert_normal(cost: CostEstimate, pages: int) -> None:
    assert cost.over_budget is False, f"{pages} pages read as over budget"
    assert _label(cost, BUDGET).text() == "Budget $2.00.", f"{pages} pages"
    _assert_styled_by_the_sheet_alone(cost, pages, over=False)


def _assert_over(cost: CostEstimate, pages: int) -> None:
    assert cost.over_budget is True, f"{pages} pages did not read as over budget"
    assert _label(cost, BUDGET).text() == f"Budget $2.00. {OVER}", f"{pages} pages"
    _assert_styled_by_the_sheet_alone(cost, pages, over=True)


def test_the_boundary_read_from_the_domain_is_thirty_three_pages_on_claude() -> None:
    """The second, literal oracle for the computed boundary."""
    assert _last_page_inside_budget(OPUS) == 33
    assert format_usd(_estimate(33, OPUS)) == "$1.98"
    assert format_usd(_estimate(34, OPUS)) == "$2.04"


@pytest.mark.parametrize("model", [OPUS, GEMINI])
def test_the_last_page_count_inside_the_budget_shows_the_normal_state(qtbot, model: str) -> None:  # type: ignore[no-untyped-def]
    pages = _last_page_inside_budget(model)
    assert _estimate(pages, model) <= _ceiling(), "precondition: the boundary is inside"

    _assert_normal(_cost(qtbot, pages, model), pages)


@pytest.mark.parametrize("model", [OPUS, GEMINI])
def test_one_page_more_than_the_budget_holds_shows_the_over_budget_state(
    qtbot,  # type: ignore[no-untyped-def]
    model: str,
) -> None:
    pages = _last_page_inside_budget(model) + 1
    assert _estimate(pages, model) > _ceiling(), "precondition: one more page is over"

    _assert_over(_cost(qtbot, pages, model), pages)


def test_thirty_three_pages_are_normal_and_thirty_four_are_over_budget_on_claude(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The design's worked example, literally."""
    _assert_normal(_cost(qtbot, 33, OPUS), 33)
    _assert_over(_cost(qtbot, 34, OPUS), 34)


def test_an_estimate_exactly_on_the_ceiling_is_within_budget(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DV-2, isolated: the ceiling is inclusive, as `Budget.check`. A test model
    at 99,000 micro-dollars a page rounds up to $0.10, so 20 pages are exactly
    $2.00 - normal. A `>=` fails only this."""
    model = _with_model(monkeypatch, "test-ten-cents", "66")
    assert _estimate(20, model) == _ceiling(), "precondition: 20 pages land on the ceiling"

    cost = _cost(qtbot, 20, model)

    assert _label(cost, ESTIMATE).text() == "Estimated for 20 pages with test-ten-cents: $2.00."
    _assert_normal(cost, 20)


def test_one_cent_past_an_exact_ceiling_is_over_budget(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _with_model(monkeypatch, "test-ten-cents", "66")

    cost = _cost(qtbot, 21, model)

    assert _label(cost, ESTIMATE).text() == "Estimated for 21 pages with test-ten-cents: $2.10."
    _assert_over(cost, 21)


def test_over_budget_is_a_read_only_property() -> None:
    attribute = CostEstimate.__dict__.get("over_budget")
    assert isinstance(attribute, property), "over_budget is not a property"
    assert attribute.fset is None, "over_budget can be set"


# =============================================================================
# AC-4 (MT-058): more than 200 pages -> a warning, nothing blocked
# =============================================================================


def test_two_hundred_pages_carry_no_page_count_warning(qtbot) -> None:  # type: ignore[no-untyped-def]
    """DV-3, isolated: a `>= 200` fails only this."""
    _absent(_cost(qtbot, 200), PAGE_WARNING)


def test_two_hundred_and_one_pages_warn_with_the_estimated_cost(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 201, OPUS)

    text = _label(cost, PAGE_WARNING).text()
    assert text == _warning_line(format_usd(_estimate(201, OPUS)))
    assert text == "That is more pages than a chapter. Estimated cost is $12.06."


def test_two_hundred_and_one_pages_on_gemini_warn_with_gemini_s_figure(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The warning's figure is the same model's: 201 x $0.03 = $6.03."""
    cost = _cost(qtbot, 201, GEMINI)

    assert _label(cost, PAGE_WARNING).text() == _warning_line("$6.03")


def test_two_hundred_and_one_pages_show_all_three_lines_over_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 201, OPUS)

    assert _lines(cost) == [
        "Estimated for 201 pages with claude-opus-5: $12.06.",
        f"Budget $2.00. {OVER}",
        "That is more pages than a chapter. Estimated cost is $12.06.",
    ]
    assert cost.over_budget


def test_the_page_count_warning_does_not_set_the_over_budget_state(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Line 3 is text only. Every shipped model is at least a cent a page, so
    201 pages are always over $2.00 on one; a test model priced at nothing is
    the one that puts 201 pages within budget, and they are still warned about."""
    model = _with_model(monkeypatch, "test-free", "0")

    cost = _cost(qtbot, 201, model)

    assert _label(cost, PAGE_WARNING).text() == _warning_line(ZERO)
    _assert_normal(cost, 201)


def test_a_summary_of_more_than_two_hundred_pages_blocks_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _summary(qtbot, _chapter(201), OPUS)

    assert _label(summary, PAGE_WARNING).text() == _warning_line("$12.06")
    choose = summary.findChild(QPushButton, "summary-choose")
    assert choose is not None and choose.isEnabled(), "the way out is blocked"
    assert _label(summary, "summary-count").text() == "201 pages"
    assert summary.isEnabled()


# =============================================================================
# AC-5 (MT-058): never "$0.00" for one or more pages
# =============================================================================


def _zero_readings(qtbot, top: int, model: str) -> list[str]:  # type: ignore[no-untyped-def]
    """Every label and accessible name reading $0.00, over 1..top pages."""
    seen: list[str] = []
    for pages in range(1, top + 1):
        cost = CostEstimate(pages, model)
        texts = [label.text() for label in cost.findChildren(QLabel)] + [cost.accessibleName()]
        seen.extend(f"{pages}: {text!r}" for text in texts if ZERO in text)
        assert cost.findChildren(QLabel), f"{pages} pages: no labels at all"
        cost.deleteLater()
    return seen


@pytest.mark.parametrize("model", [OPUS, GEMINI])
def test_no_estimate_of_one_to_two_hundred_and_fifty_pages_reads_zero(qtbot, model: str) -> None:  # type: ignore[no-untyped-def]
    assert _zero_readings(qtbot, 250, model) == []


def test_a_model_costing_a_fraction_of_a_cent_a_page_never_reads_zero(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control with teeth: a test model whose exact page cost is 2
    micro-dollars (1,500 tokens at $0.001/M, rounded half-up by `price`).
    Priced to the nearest cent it is $0.00 a page, and every line reads $0.00;
    rounded up (MT-100 C-1) it is $0.01."""
    model = _with_model(monkeypatch, "test-two-micro", "0.001")

    assert _zero_readings(qtbot, 250, model) == []
    one = _cost(qtbot, 1, model)
    assert _label(one, ESTIMATE).text() == "Estimated for 1 page with test-two-micro: $0.01."
    most = _cost(qtbot, 250, model)
    assert _label(most, ESTIMATE).text() == "Estimated for 250 pages with test-two-micro: $2.50."


# =============================================================================
# MT-100 AC-4: no model can be chosen -> no figure, and no over-budget state
# =============================================================================


@pytest.mark.parametrize(
    "reason", [NO_KEY_TEXT, AMBIGUOUS_TEXT, OPENAI_TEXT], ids=["no-key", "ambiguous", "openai"]
)
def test_with_no_provider_the_estimate_line_says_why_and_the_budget_stands_alone(
    qtbot,  # type: ignore[no-untyped-def]
    reason: str,
) -> None:
    """**MT-100 AC-4** at the widget: `No estimate: <reason>.`, `Budget $2.00.`
    and nothing over budget - at 34 pages, which on any model is over."""
    cost = _cost(qtbot, 34, _no_provider(reason))

    assert _lines(cost) == [_no_estimate_line(reason), "Budget $2.00."]
    assert cost.accessibleName() == "\n".join(_lines(cost))
    _assert_normal(cost, 34)


def test_with_no_provider_above_two_hundred_pages_the_warning_has_no_cost_sentence(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AC-4's last clause: exactly `That is more pages than a chapter.`"""
    cost = _cost(qtbot, 201, _no_provider(NO_KEY_TEXT))

    assert _label(cost, PAGE_WARNING).text() == MORE_THAN_A_CHAPTER
    assert _lines(cost) == [
        _no_estimate_line(NO_KEY_TEXT),
        "Budget $2.00.",
        MORE_THAN_A_CHAPTER,
    ]
    assert cost.over_budget is False


def test_with_no_provider_two_hundred_pages_carry_no_warning(qtbot) -> None:  # type: ignore[no-untyped-def]
    _absent(_cost(qtbot, 200, _no_provider(NO_KEY_TEXT)), PAGE_WARNING)


def test_with_no_provider_no_line_carries_a_dollar_figure_but_the_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    """No figure is invented for a model that is not there: the only amount on
    screen is the budget's."""
    cost = _cost(qtbot, 201, _no_provider(NO_KEY_TEXT))

    amounts = [re.findall(r"\$[0-9][0-9,]*\.[0-9]{2}", line) for line in _lines(cost)]
    assert amounts == [[], ["$2.00"], []], f"amounts shown with no provider: {amounts}"


def test_no_provider_is_a_frozen_value_carrying_the_reason() -> None:
    no_provider = _no_provider(NO_KEY_TEXT)

    assert no_provider.reason == NO_KEY_TEXT  # type: ignore[attr-defined]
    assert no_provider == _no_provider(NO_KEY_TEXT)
    with pytest.raises(AttributeError):
        no_provider.reason = "changed"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("error", "reason"),
    [(NoApiKey(NO_KEY_TEXT), NO_KEY_TEXT), (AmbiguousProvider(AMBIGUOUS_TEXT), AMBIGUOUS_TEXT)],
    ids=["no-key", "ambiguous"],
)
def test_a_window_whose_model_cannot_be_chosen_shows_why_and_offers_start_run(
    qtbot,  # type: ignore[no-untyped-def]
    error: ProviderError,
    reason: str,
) -> None:
    """**MT-100 AC-4** through `MainWindow.show_summary` and a `RunSetup` whose
    `select_model` raises: the ProviderError's message verbatim, no
    over-budget state, Start reads `Start run` - at 201 pages, which on any
    model would read `Start run anyway`."""
    summary = _window_summary(qtbot, _chapter(201), _setup(_refusing(error)))

    cost = summary.cost_estimate
    assert _lines(cost) == [_no_estimate_line(reason), "Budget $2.00.", MORE_THAN_A_CHAPTER]
    assert cost.over_budget is False
    assert _start_button(summary).text() == START


@pytest.mark.parametrize(
    ("error", "reason"),
    [(NoApiKey(NO_KEY_TEXT), NO_KEY_TEXT), (AmbiguousProvider(AMBIGUOUS_TEXT), AMBIGUOUS_TEXT)],
    ids=["no-key", "ambiguous"],
)
def test_pressing_start_with_no_model_still_fails_as_it_did(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    error: ProviderError,
    reason: str,
) -> None:
    """AC-4's "Pressing Start still fails as it does today": `MainWindow._start`
    shows the builder's `ProviderError` as the drop target's error."""

    def refusing_builder(models_dir: Path) -> Sequence[Stage]:
        raise error

    models = tmp_path / "models"
    models.mkdir()
    setup = RunSetup(lambda: models, refusing_builder, _refusing(error))
    window = MainWindow(open_folder=app_module.open_folder, run_setup=setup)
    qtbot.addWidget(window)
    window.show_summary(_chapter(3, tmp_path / "Chapter 3"))
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary)

    _start_button(summary).click()
    QApplication.processEvents()

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget), f"after Start: {type(target).__name__}"
    assert target.headline.text() == reason


def test_a_window_with_no_run_setup_shows_no_estimate_for_want_of_models(qtbot) -> None:  # type: ignore[no-untyped-def]
    """C-6: `setup is None` -> `NoProvider(NO_MODELS)` - Start would say the
    same. The sentence keeps one full stop (C-6 as amended in RED: NO_MODELS
    already ends with one)."""
    summary = _window_summary(qtbot, _chapter(34), None)

    assert _lines(summary.cost_estimate) == [
        "No estimate: " + NO_MODELS_TEXT,
        "Budget $2.00.",
    ]
    assert summary.cost_estimate.over_budget is False
    assert _start_button(summary).text() == START


@pytest.mark.parametrize(
    ("model", "pages", "line", "start"),
    [
        (GEMINI, 66, "Estimated for 66 pages with gemini-3.1-pro-preview: $1.98.", START),
        (GEMINI, 67, "Estimated for 67 pages with gemini-3.1-pro-preview: $2.01.", START_ANYWAY),
        (OPUS, 33, "Estimated for 33 pages with claude-opus-5: $1.98.", START),
        (OPUS, 34, "Estimated for 34 pages with claude-opus-5: $2.04.", START_ANYWAY),
    ],
    ids=["gemini-66", "gemini-67", "claude-33", "claude-34"],
)
def test_a_window_prices_the_summary_on_the_model_its_setup_selects(
    qtbot,  # type: ignore[no-untyped-def]
    model: str,
    pages: int,
    line: str,
    start: str,
) -> None:
    """**MT-100 AC-2** through `MainWindow`: the boundary moves with the model
    `RunSetup.select_model` answers, and Start's label moves with it."""
    summary = _window_summary(qtbot, _chapter(pages), _setup(_fixed(model)))

    assert _label(summary.cost_estimate, ESTIMATE).text() == line
    assert _start_button(summary).text() == start


# =============================================================================
# MT-100 AC-1 / AC-3 / AC-4 through the app, from the environment
# =============================================================================


@pytest.fixture
def two_hundred_pages(tmp_path: Path) -> Path:
    return _folder_of(tmp_path, "Volume 1", 200, _png())


def _app_summary(qtbot, folder: Path) -> ChapterSummary:  # type: ignore[no-untyped-def]
    """`app.build_window` with its own default `RunSetup` - so the model comes
    from the REAL `app.selected_model`, reading the environment the test set."""
    window = app_module.build_window([str(folder)])
    qtbot.addWidget(window)
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary), f"central is {type(summary).__name__}"
    return summary


def test_a_gemini_only_environment_prices_two_hundred_pages_at_six_dollars(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    two_hundred_pages: Path,
) -> None:
    """**MT-100 AC-1**, the reproduction: the user's environment. Before this
    story the same state read `Estimated for 200 pages: $12.00.`"""
    _provider_env(monkeypatch, GEMINI_API_KEY="g-dummy-key-0000")

    summary = _app_summary(qtbot, two_hundred_pages)

    assert _lines(summary.cost_estimate)[:2] == [
        "Estimated for 200 pages with gemini-3.1-pro-preview: $6.00.",
        f"Budget $2.00. {OVER}",
    ]
    assert _start_button(summary).text() == START_ANYWAY


def test_an_anthropic_only_environment_prices_two_hundred_pages_at_twelve_dollars(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    two_hundred_pages: Path,
) -> None:
    """**MT-100 AC-3** through the app."""
    _provider_env(monkeypatch, ANTHROPIC_API_KEY="sk-dummy-key-0000")

    summary = _app_summary(qtbot, two_hundred_pages)

    assert _label(summary.cost_estimate, ESTIMATE).text() == (
        "Estimated for 200 pages with claude-opus-5: $12.00."
    )


@pytest.mark.parametrize(
    ("keys", "reason"),
    [
        ({}, NO_KEY_TEXT),
        ({"ANTHROPIC_API_KEY": "sk-dummy-0000", "GEMINI_API_KEY": "g-dummy-0000"}, AMBIGUOUS_TEXT),
        ({"OPENAI_API_KEY": "sk-dummy-0000"}, OPENAI_TEXT),
    ],
    ids=["no-key", "ambiguous", "openai"],
)
def test_an_environment_with_no_usable_provider_shows_why_and_no_figure(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    two_hundred_pages: Path,
    keys: dict[str, str],
    reason: str,
) -> None:
    """**MT-100 AC-4** through the real `app.selected_model`: no key, two keys
    and no choice, or a provider with no translator (`Out of scope`'s openai
    line)."""
    _provider_env(monkeypatch, **keys)

    summary = _app_summary(qtbot, two_hundred_pages)

    assert _lines(summary.cost_estimate) == [_no_estimate_line(reason), "Budget $2.00."]
    assert summary.cost_estimate.over_budget is False
    assert _start_button(summary).text() == START


# =============================================================================
# MT-100 AC-6: the screen and the guard share one number, per provider
# =============================================================================


_SHARED_PAGE_COUNTS = (1, 20, 200)


@pytest.fixture(scope="module")
def chapters_of(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Path]:
    """One folder per page count in {1, 20, 200}, shared by both providers."""
    root = tmp_path_factory.mktemp("shared-number")
    png = _pil_png()
    return {count: _folder_of(root, f"{count} pages", count, png) for count in _SHARED_PAGE_COUNTS}


def _guard_first_projection(folder: Path, model: str) -> object:
    """The projection the REAL translate stage judges for page 0 of `folder`,
    with no priced calls, when built for `model` the way the composition root
    builds it (`page_estimate(model)`, MT-100 C-4). A stored $0.00 ceiling makes
    the stage refuse, which is what puts its decision - and the projection in
    it - where a test can read it; nothing is called and nothing is written."""

    def unreachable(*args: object) -> object:
        raise AssertionError("the translator was called for a page the guard refused")

    project_dir = project_dir_for(folder)
    if project_dir.exists():
        opener = open_project(project_dir)
    else:
        opener = create_project(read_chapter(folder), project_dir)
    with opener as project:
        with project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = 0")
        page = next(page for page in project.pages() if page.ordinal == 0)
        ctx = PageContext(project=project, page=page, run_id=0, emit=lambda _event: None)
        stage = TranslateStage(unreachable, _per_page(model))  # type: ignore[arg-type]
        with pytest.raises(BudgetRefused) as refused:
            stage.run(ctx)
    return refused.value.decision.projection


@pytest.mark.parametrize("pages", _SHARED_PAGE_COUNTS)
@pytest.mark.parametrize("provider", ["anthropic", "gemini"])
def test_the_summary_shows_the_guards_own_first_projection_for_the_providers_model(
    qtbot,  # type: ignore[no-untyped-def]
    chapters_of: dict[int, Path],
    provider: str,
    pages: int,
) -> None:
    """**MT-100 AC-6.** For each provider with a translator, the figure the
    summary shows for `pages` pages is `remaining_chapter` of the guard's first
    projection on that provider's model - the screen and the guard cannot
    disagree about whether a chapter fits (MT-058's docstring, kept)."""
    model: str = provider_module.model_for(provider)
    guard = _guard_first_projection(chapters_of[pages], model)

    cost = _cost(qtbot, pages, model)
    text = _label(cost, ESTIMATE).text()
    match = re.fullmatch(
        rf"Estimated for {pages} pages? with {re.escape(model)}: (\$[0-9.,]+)\.", text
    )
    assert match is not None, f"the estimate line does not read as the contract's: {text!r}"
    shown = match.group(1)

    remaining = guard.remaining_chapter  # type: ignore[attr-defined]
    assert guard.basis == "estimate" and guard.sample_count == 0  # type: ignore[attr-defined]
    assert shown == format_usd(remaining), (
        f"{provider}, {pages} pages: the summary shows {shown}, the guard projects"
        f" {format_usd(remaining)} - the screen and the guard disagree"
    )
    assert Usd(Decimal(shown[1:].replace(",", ""))) == remaining, "a whole-cent figure, exactly"


# =============================================================================
# AC-3's colour, as paint (C-2 amended, return 2): theme.qss and nowhere else
# =============================================================================
#
# Modelled on MT-061's `test_the_order_notice_is_raised_inside_a_hairline_
# warning_border` (tests/ui/test_app_theme_paint.py). Its helpers are private
# to that module (no conftest, `tests` is not a package), so a minimal copy of
# the four this needs lives here: the application-sheet fixture, the packaged
# sheet and template, the grab, and the edge run. The rules are scoped to
# `#chapter-summary`, so the frame is measured inside a real summary built by
# `app.build_window` from a folder of real PNGs; a standalone `CostEstimate`
# gets none of them (Design notes, "Theme (MT-061 rule)"). MT-100: the window
# is given a `RunSetup` answering claude-opus-5, so the 33/34 boundary is
# Claude's and nothing reads the machine's environment.

#: components.md section 2 CostEstimate, "How it is rendered": edge per state.
EDGE_NORMAL = "color.border.subtle"
EDGE_OVER = "color.status.warning"
EDGE_WIDTH = "border-width.hairline"
#: A colour no token uses (asserted below); MT-061's AC-6 sentinel.
SENTINEL = "#13579B"
PAINT_WINDOW = QSize(1100, 720)


def _token_colour(name: str) -> str:
    return QColor(tokens_gen.TOKENS[name]).name()


def _packaged(resource: str) -> str:
    return files("mangatl.ui").joinpath(resource).read_text(encoding="utf-8")


def _sentinel_theme(token: str) -> str:
    """The packaged template rendered with `token` = SENTINEL (MT-061 AC-6)."""
    values = dict(tokens_gen.TOKENS)
    values[token] = SENTINEL
    return tokens.render_qss(values, _packaged("theme.qss.tmpl"))


@pytest.fixture
def application_sheet(qapp: QApplication) -> Iterator[Callable[[str], None]]:
    """Set the real application's sheet; always put `""` back."""

    def apply(sheet: str) -> None:
        qapp.setStyleSheet(sheet)

    try:
        yield apply
    finally:
        qapp.setStyleSheet("")


def _painted_cost_frame(  # type: ignore[no-untyped-def]
    qtbot, root: Path, pages: int
) -> tuple[QWidget, CostEstimate, QImage]:
    """A real summary of `pages` PNGs, shown; the window's pixels over the
    estimate frame. Zero-padded names, so no order notice moves anything.
    The window is returned so the caller holds it: qtbot keeps only a weak
    reference, and the frame's C++ object dies with it."""
    folder = _folder_of(root, f"{pages} pages", pages, _png())
    window = app_module.build_window([str(folder)], run_setup=_setup(_fixed(OPUS)))
    qtbot.addWidget(window)
    window.resize(PAINT_WINDOW)
    with qtbot.waitExposed(window):
        window.show()
    QApplication.processEvents()
    QApplication.processEvents()
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary), f"central is {type(summary).__name__}"
    cost = summary.cost_estimate
    assert cost.isVisible() and not cost.visibleRegion().isEmpty(), "the estimate is not on screen"
    origin = cost.mapTo(window, QPoint(0, 0))
    return window, cost, window.grab(QRect(origin, cost.size())).toImage()


def _edge_colours(image: QImage) -> dict[str, set[str]]:
    """The colours along the middle line of each edge of the hairline,
    stopping `radius.sm` + hairline short of the corners."""
    width = int(tokens_gen.TOKENS[EDGE_WIDTH])
    inset = int(tokens_gen.TOKENS["radius.sm"]) + width
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
    return {edge: {colour} for edge in ("top", "bottom", "left", "right")}


def test_the_sentinel_and_the_two_edge_colours_are_distinct() -> None:
    """Without this the paint tests below could not tell the states apart."""
    used = {v[:7].upper() for v in tokens_gen.TOKENS.values() if str(v).startswith("#")}
    assert SENTINEL.upper() not in used, f"{SENTINEL} is a token's value"
    assert _token_colour(EDGE_NORMAL) != _token_colour(EDGE_OVER)


def test_an_over_budget_summary_paints_the_estimates_edge_in_the_warning_colour(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-3: 34 pages ($2.04) - every edge of the frame is color.status.warning."""
    application_sheet(_packaged("theme.qss"))
    pages = _last_page_inside_budget(OPUS) + 1

    _window, cost, image = _painted_cost_frame(qtbot, tmp_path, pages)

    assert cost.over_budget is True, "precondition"
    assert _edge_colours(image) == _all_edges(_token_colour(EDGE_OVER)), (
        f"{pages} pages, over budget: the estimate's edge is not {EDGE_OVER}"
    )


def test_a_summary_within_budget_paints_the_estimates_edge_in_the_subtle_border(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """AC-3's control: 33 pages ($1.98) - every edge is color.border.subtle."""
    application_sheet(_packaged("theme.qss"))
    pages = _last_page_inside_budget(OPUS)

    _window, cost, image = _painted_cost_frame(qtbot, tmp_path, pages)

    assert cost.over_budget is False, "precondition"
    assert _edge_colours(image) == _all_edges(_token_colour(EDGE_NORMAL)), (
        f"{pages} pages, within budget: the estimate's edge is not {EDGE_NORMAL}"
    )


def test_control_without_the_sheet_an_over_budget_edge_is_not_the_warning_colour(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
) -> None:
    """The warning colour comes from theme.qss: with no application sheet the
    34-page frame shows Qt's default, not color.status.warning."""
    application_sheet("")
    pages = _last_page_inside_budget(OPUS) + 1

    _window, cost, image = _painted_cost_frame(qtbot, tmp_path, pages)

    assert cost.over_budget is True, "precondition"
    seen = set().union(*_edge_colours(image).values())
    assert _token_colour(EDGE_OVER) not in seen, (
        f"with no application sheet, {pages} pages still paint {EDGE_OVER}: the "
        f"colour is authored somewhere other than theme.qss (edges {sorted(seen)})"
    )


@pytest.mark.parametrize(
    ("token", "over"),
    [(EDGE_NORMAL, False), (EDGE_OVER, True)],
    ids=["within-budget-edge", "over-budget-edge"],
)
def test_the_estimates_edge_follows_its_token_in_the_application_sheet(
    qtbot,  # type: ignore[no-untyped-def]
    application_sheet: Callable[[str], None],
    tmp_path: Path,
    token: str,
    over: bool,
) -> None:
    """MT-061 AC-6's shape: substitute an unused colour for the state's token
    in the packaged template; the frame's edge must show it on every side."""
    application_sheet(_sentinel_theme(token))
    pages = _last_page_inside_budget(OPUS) + (1 if over else 0)

    _window, cost, image = _painted_cost_frame(qtbot, tmp_path, pages)

    assert cost.over_budget is over, "precondition"
    sentinel = QColor(SENTINEL).name()
    assert _edge_colours(image) == _all_edges(sentinel), (
        f"with {token} = {sentinel}, the {pages}-page estimate's edge painted something else"
    )


# =============================================================================
# C-2: names, absences, label rules, accessibility
# =============================================================================


def test_the_estimate_is_a_frame_named_summary_cost_estimate(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 20)

    assert isinstance(cost, QFrame)
    assert cost.objectName() == FRAME


def test_the_frame_is_named_by_its_visible_lines(qtbot) -> None:  # type: ignore[no-untyped-def]
    for pages, model, lines in (
        (1, OPUS, ["Estimated for 1 page with claude-opus-5: $0.06.", "Budget $2.00."]),
        (
            34,
            OPUS,
            ["Estimated for 34 pages with claude-opus-5: $2.04.", f"Budget $2.00. {OVER}"],
        ),
        (
            201,
            OPUS,
            [
                "Estimated for 201 pages with claude-opus-5: $12.06.",
                f"Budget $2.00. {OVER}",
                "That is more pages than a chapter. Estimated cost is $12.06.",
            ],
        ),
        (
            1,
            GEMINI,
            ["Estimated for 1 page with gemini-3.1-pro-preview: $0.03.", "Budget $2.00."],
        ),
    ):
        cost = _cost(qtbot, pages, model)
        assert _lines(cost) == lines, f"{pages} pages on {model}"
        assert cost.accessibleName() == "\n".join(lines), f"{pages} pages on {model}"


@pytest.mark.parametrize("no_provider", [False, True], ids=["with-model", "no-provider"])
def test_every_estimate_label_is_plain_word_wrapped_mouse_selectable_and_never_a_focus_stop(
    qtbot,  # type: ignore[no-untyped-def]
    no_provider: bool,
) -> None:
    model = _no_provider(NO_KEY_TEXT) if no_provider else OPUS
    cost = _cost(qtbot, 201, model)

    labels = cost.findChildren(QLabel)
    assert {label.objectName() for label in labels} == set(LABELS)
    for label in labels:
        name = label.objectName()
        assert label.textFormat() == Qt.TextFormat.PlainText, f"{name} is not plain text"
        assert label.wordWrap(), f"{name} does not word-wrap"
        assert label.textInteractionFlags() == Qt.TextInteractionFlag.TextSelectableByMouse, (
            f"{name} has interaction flags {label.textInteractionFlags()!r}"
        )
        assert label.focusPolicy() == Qt.FocusPolicy.NoFocus, f"{name} takes focus"


def test_the_estimate_is_not_announced_as_an_alert(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 34)
    interface = QAccessible.queryAccessibleInterface(cost)

    assert interface is not None
    assert interface.role() != QAccessible.Role.AlertMessage


# =============================================================================
# C-3: ChapterSummary carries it, inside the scroll area, before the notice
# =============================================================================


def test_the_summary_carries_a_cost_estimate_of_its_page_count_on_its_model(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _summary(qtbot, _chapter(20), GEMINI)

    cost = summary.cost_estimate
    assert isinstance(cost, CostEstimate)
    assert summary.findChild(CostEstimate, FRAME) is cost
    assert _label(cost, ESTIMATE).text() == (
        "Estimated for 20 pages with gemini-3.1-pro-preview: $0.60."
    )
    assert _label(cost, BUDGET).text() == "Budget $2.00."


def test_the_summary_requires_the_model_as_a_keyword() -> None:
    """MT-100 C-6: REQUIRED, so no summary can quietly price Claude's figure."""
    with pytest.raises(TypeError):
        ChapterSummary(_chapter(2))  # type: ignore[call-arg]


def test_the_estimate_is_inside_the_scroll_area_between_the_page_facts_and_the_notice(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """p1 … p12 sort differently as text, so the order notice exists."""
    summary = _summary(qtbot, _chapter(12))
    summary.resize(600, 900)
    with qtbot.waitExposed(summary):
        summary.show()

    scroll = summary.findChild(QScrollArea, "summary-scroll")
    assert scroll is not None
    cost = summary.cost_estimate
    assert scroll.isAncestorOf(cost), "the estimate is outside the scroll area"
    content = scroll.widget()
    last = _label(summary, "summary-last")
    notice = summary.findChild(QFrame, "summary-order-notice")
    assert notice is not None, "precondition: p1 … p12 have an order notice"

    def top(widget: QWidget) -> int:
        return widget.mapTo(content, widget.rect().topLeft()).y()

    assert top(last) < top(cost) < top(notice), (
        f"tops: last page {top(last)}, estimate {top(cost)}, notice {top(notice)}"
    )


def test_the_scroll_description_puts_the_estimate_after_the_page_facts_and_before_the_notice(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    summary = _summary(qtbot, _chapter(12, Path("C:/manga/Twelve")))
    scroll = summary.findChild(QScrollArea, "summary-scroll")
    assert scroll is not None

    lines = scroll.accessibleDescription().split("\n")

    assert lines[:6] == [
        "Twelve",
        "12 pages",
        "First page: p1.png",
        "Last page: p12.png",
        "Estimated for 12 pages with claude-opus-5: $0.72.",
        "Budget $2.00.",
    ]
    assert lines[6] == (
        "These filenames sort differently as numbers and as text. The run uses natural order."
    )
    assert len(lines) == 9


def test_an_over_budget_summary_describes_the_over_budget_sentence(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _summary(qtbot, _chapter(34, Path("C:/manga/Long")))
    scroll = summary.findChild(QScrollArea, "summary-scroll")
    assert scroll is not None

    lines = scroll.accessibleDescription().split("\n")

    assert lines[4:6] == [
        "Estimated for 34 pages with claude-opus-5: $2.04.",
        f"Budget $2.00. {OVER}",
    ]


def test_a_summary_with_no_provider_describes_why_there_is_no_estimate(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _summary(qtbot, _chapter(34, Path("C:/manga/Long")), _no_provider(NO_KEY_TEXT))
    scroll = summary.findChild(QScrollArea, "summary-scroll")
    assert scroll is not None

    lines = scroll.accessibleDescription().split("\n")

    assert lines[4:6] == [_no_estimate_line(NO_KEY_TEXT), "Budget $2.00."]


# =============================================================================
# C-4: through the window, from a real folder
# =============================================================================


def test_a_folder_of_pages_opened_by_the_app_shows_its_estimate_on_the_selected_model(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The user's environment again, at three pages: $0.09 on Gemini."""
    _provider_env(monkeypatch, GEMINI_API_KEY="g-dummy-key-0000")
    folder = tmp_path / "Chapter 3"
    folder.mkdir()
    png = _png()
    for name in ("page 9.png", "page 10.png", "page 11.png"):
        (folder / name).write_bytes(png)

    window = app_module.build_window([str(folder)])
    qtbot.addWidget(window)

    central = window.centralWidget()
    assert isinstance(central, ChapterSummary), f"central widget is {type(central).__name__}"
    cost = central.cost_estimate
    assert _label(cost, ESTIMATE).text() == (
        "Estimated for 3 pages with gemini-3.1-pro-preview: $0.09."
    )
    assert _label(cost, BUDGET).text() == "Budget $2.00."
    assert cost.over_budget is False
