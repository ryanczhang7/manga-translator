"""MT-058: the chapter summary shows the estimated cost against the budget.

`CostEstimate` (new, `mangatl.ui.cost_estimate`, C-2) is `ChapterSummary`'s
part 5 (C-3): one line for the estimate, one for the budget, and - above 200
pages - a third warning that this is more pages than a chapter. `format_usd`
(C-1) is the one money formatter: to the cent, rounding a fraction of a cent
**up**.

Oracle partition (story `## Contract`):

- **Settled - read out, never re-typed:** every figure comes from
  `mangatl.domain.budget` (`DEFAULT_CEILING`, `BOOTSTRAP_PAGE_ESTIMATE`,
  `Budget.project`), read through `_estimate` / `_ceiling` below, which import
  nothing from the module under test. The design's worked examples ($0.06 for
  one page, $1.20 for 20, $1.98/$2.04 for 33/34, $12.00/$12.06 for 200/201) are
  spelled out as a second, literal oracle. Every string is spelled out here.
- **Control demanded:** AC-3's boundary, `DEFAULT_CEILING.micro() //
  BOOTSTRAP_PAGE_ESTIMATE.micro()` (33 today), both sides; the inclusive
  ceiling, reached by patching the per-page estimate to $0.10 (20 pages is
  exactly $2.00, normal; 21 over); AC-4's 200/201; AC-5 over 1..250, both with
  today's estimate and with a one-micro-dollar estimate, where a formatter that
  does not round up would show `$0.00`.
- **Mechanical:** `format_usd`'s examples, object names, absences
  (`findChild(...) is None`), the scroll description order, the warning token.

The widget calls `Budget.project` at construction, and `project` reads the
module global `BOOTSTRAP_PAGE_ESTIMATE` at call time, so
`monkeypatch.setattr(budget, "BOOTSTRAP_PAGE_ESTIMATE", ...)` changes what the
widget shows - that is how these tests prove the figure is read, not re-typed.
`DEFAULT_CEILING` is never patched: `Budget.__init__` binds it as a default
argument at definition time, so a patch would not reach it.

**RED:** this file fails at import (`mangatl.ui.cost_estimate` does not exist),
so no assertion here has run; each control's expected value is recorded in the
story's `## Handoff`. **Timing:** no real-time waits; the slowest test builds
250 small widgets twice (AC-5).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QWidget,
)

import mangatl.domain.budget as budget
from mangatl import app as app_module
from mangatl.domain.budget import Budget
from mangatl.domain.money import Usd
from mangatl.domain.page import Chapter, Page
from mangatl.ui import tokens_gen
from mangatl.ui.cost_estimate import CostEstimate, format_usd
from mangatl.ui.summary import ChapterSummary

# --- Settled strings, spelled out (never read back from the module under test) ------
OVER = "The estimate is over budget."
FRAME = "summary-cost-estimate"
ESTIMATE = "cost-estimate"
BUDGET = "cost-budget"
PAGE_WARNING = "cost-page-warning"
LABELS = (ESTIMATE, BUDGET, PAGE_WARNING)
ZERO = "$0.00"


# --- Figures, read from the domain ---------------------------------------------------


def _estimate(pages: int) -> Usd:
    """AC-2's figure: `Budget.project` with no priced calls, its remainder."""
    return Budget().project((), pages).remaining_chapter


def _ceiling() -> Usd:
    return Budget().ceiling


def _last_page_inside_budget() -> int:
    """AC-3's boundary, read from the two constants (33 today)."""
    return budget.DEFAULT_CEILING.micro() // budget.BOOTSTRAP_PAGE_ESTIMATE.micro()


def _estimate_line(pages: int, shown: str) -> str:
    noun = "page" if pages == 1 else "pages"
    return f"Estimated for {pages} {noun}: {shown}."


def _warning_line(shown: str) -> str:
    return f"That is more pages than a chapter. Estimated cost is {shown}."


# --- Helpers -------------------------------------------------------------------------


def _cost(qtbot, pages: int) -> CostEstimate:  # type: ignore[no-untyped-def]
    widget = CostEstimate(pages)
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


def _summary(qtbot, chapter: Chapter) -> ChapterSummary:  # type: ignore[no-untyped-def]
    summary = ChapterSummary(chapter)
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


def test_the_summary_gains_the_estimate_but_no_button(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _summary(qtbot, _chapter(34))

    buttons = summary.findChildren(QAbstractButton)
    assert [b.objectName() for b in buttons] == ["summary-choose"], (
        f"buttons: {[b.objectName() for b in buttons]}"
    )
    assert summary.findChildren(QLineEdit) == [] and summary.findChildren(QAbstractSpinBox) == []


# =============================================================================
# AC-2: N pages -> "Estimated for N pages: $x.", $x read from the domain
# =============================================================================


@pytest.mark.parametrize(
    ("pages", "line"),
    [
        (1, "Estimated for 1 page: $0.06."),
        (2, "Estimated for 2 pages: $0.12."),
        (20, "Estimated for 20 pages: $1.20."),
        (33, "Estimated for 33 pages: $1.98."),
        (34, "Estimated for 34 pages: $2.04."),
        (200, "Estimated for 200 pages: $12.00."),
    ],
    ids=["one", "two", "twenty", "33", "34", "200"],
)
def test_the_estimate_line_reads_the_page_count_and_the_bootstrap_figure(
    qtbot,  # type: ignore[no-untyped-def]
    pages: int,
    line: str,
) -> None:
    cost = _cost(qtbot, pages)
    text = _label(cost, ESTIMATE).text()

    assert text == _estimate_line(pages, format_usd(_estimate(pages)))
    assert text == line


def test_the_estimate_is_labelled_as_an_estimate(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 20)
    text = _label(cost, ESTIMATE).text()

    assert text.startswith("Estimated for "), f"not labelled as an estimate: {text!r}"


def test_the_shown_figure_follows_the_domains_per_page_estimate(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read, not re-typed: at $0.07 a page, 20 pages are $1.40, not $1.20."""
    monkeypatch.setattr(budget, "BOOTSTRAP_PAGE_ESTIMATE", Usd(Decimal("0.07")))

    cost = _cost(qtbot, 20)

    assert _label(cost, ESTIMATE).text() == "Estimated for 20 pages: $1.40."
    assert _label(cost, ESTIMATE).text() == _estimate_line(20, format_usd(_estimate(20)))
    assert not cost.over_budget


# =============================================================================
# AC-3: over the budget -> the over-budget state (control: 33 / 34)
# =============================================================================


def _assert_normal(cost: CostEstimate, pages: int) -> None:
    assert cost.over_budget is False, f"{pages} pages read as over budget"
    assert _label(cost, BUDGET).text() == "Budget $2.00.", f"{pages} pages"
    assert tokens_gen.COLOR_STATUS_WARNING not in cost.styleSheet(), (
        f"{pages} pages, within budget, are styled with the warning colour"
    )


def _assert_over(cost: CostEstimate, pages: int) -> None:
    assert cost.over_budget is True, f"{pages} pages did not read as over budget"
    assert _label(cost, BUDGET).text() == f"Budget $2.00. {OVER}", f"{pages} pages"
    assert tokens_gen.COLOR_STATUS_WARNING in cost.styleSheet(), (
        f"{pages} pages, over budget, are not styled with the warning colour"
    )


def test_the_boundary_read_from_the_constants_is_thirty_three_pages() -> None:
    """The second, literal oracle for the computed boundary."""
    assert _last_page_inside_budget() == 33
    assert format_usd(_estimate(33)) == "$1.98"
    assert format_usd(_estimate(34)) == "$2.04"


def test_the_last_page_count_inside_the_budget_shows_the_normal_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    pages = _last_page_inside_budget()
    assert _estimate(pages) <= _ceiling(), "precondition: the boundary is inside the budget"

    _assert_normal(_cost(qtbot, pages), pages)


def test_one_page_more_than_the_budget_holds_shows_the_over_budget_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    pages = _last_page_inside_budget() + 1
    assert _estimate(pages) > _ceiling(), "precondition: one more page is over the budget"

    _assert_over(_cost(qtbot, pages), pages)


def test_thirty_three_pages_are_normal_and_thirty_four_are_over_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The design's worked example, literally."""
    _assert_normal(_cost(qtbot, 33), 33)
    _assert_over(_cost(qtbot, 34), 34)


def test_an_estimate_exactly_on_the_ceiling_is_within_budget(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DV-2, isolated: the ceiling is inclusive, as `Budget.check`. At $0.10 a
    page, 20 pages are exactly $2.00 - normal. A `>=` fails only this."""
    monkeypatch.setattr(budget, "BOOTSTRAP_PAGE_ESTIMATE", Usd(Decimal("0.10")))
    assert _estimate(20) == _ceiling(), "precondition: 20 pages land exactly on the ceiling"

    cost = _cost(qtbot, 20)

    assert _label(cost, ESTIMATE).text() == "Estimated for 20 pages: $2.00."
    _assert_normal(cost, 20)


def test_one_cent_past_an_exact_ceiling_is_over_budget(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(budget, "BOOTSTRAP_PAGE_ESTIMATE", Usd(Decimal("0.10")))

    cost = _cost(qtbot, 21)

    assert _label(cost, ESTIMATE).text() == "Estimated for 21 pages: $2.10."
    _assert_over(cost, 21)


def test_over_budget_is_a_read_only_property() -> None:
    attribute = CostEstimate.__dict__.get("over_budget")
    assert isinstance(attribute, property), "over_budget is not a property"
    assert attribute.fset is None, "over_budget can be set"


# =============================================================================
# AC-4: more than 200 pages -> a warning, nothing blocked; exactly 200 -> none
# =============================================================================


def test_two_hundred_pages_carry_no_page_count_warning(qtbot) -> None:  # type: ignore[no-untyped-def]
    """DV-3, isolated: a `>= 200` fails only this."""
    _absent(_cost(qtbot, 200), PAGE_WARNING)


def test_two_hundred_and_one_pages_warn_with_the_estimated_cost(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 201)

    text = _label(cost, PAGE_WARNING).text()
    assert text == _warning_line(format_usd(_estimate(201)))
    assert text == "That is more pages than a chapter. Estimated cost is $12.06."


def test_two_hundred_and_one_pages_show_all_three_lines_over_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 201)

    assert _lines(cost) == [
        "Estimated for 201 pages: $12.06.",
        f"Budget $2.00. {OVER}",
        "That is more pages than a chapter. Estimated cost is $12.06.",
    ]
    assert cost.over_budget


def test_the_page_count_warning_does_not_set_the_over_budget_state(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Line 3 is text only: at $0.001 a page, 201 pages are $0.201 - within
    budget, shown rounded up as $0.21, and still warned about."""
    monkeypatch.setattr(budget, "BOOTSTRAP_PAGE_ESTIMATE", Usd.from_micro(1_000))

    cost = _cost(qtbot, 201)

    assert _label(cost, PAGE_WARNING).text() == _warning_line("$0.21")
    assert _label(cost, ESTIMATE).text() == "Estimated for 201 pages: $0.21."
    _assert_normal(cost, 201)


def test_a_summary_of_more_than_two_hundred_pages_blocks_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _summary(qtbot, _chapter(201))

    assert _label(summary, PAGE_WARNING).text() == _warning_line("$12.06")
    choose = summary.findChild(QPushButton, "summary-choose")
    assert choose is not None and choose.isEnabled(), "the way out is blocked"
    assert _label(summary, "summary-count").text() == "201 pages"
    assert summary.isEnabled()


# =============================================================================
# AC-5: never "$0.00" for one or more pages
# =============================================================================


def _zero_readings(qtbot, top: int) -> list[str]:  # type: ignore[no-untyped-def]
    """Every label and accessible name reading $0.00, over 1..top pages."""
    seen: list[str] = []
    for pages in range(1, top + 1):
        cost = CostEstimate(pages)
        texts = [label.text() for label in cost.findChildren(QLabel)] + [cost.accessibleName()]
        seen.extend(f"{pages}: {text!r}" for text in texts if ZERO in text)
        assert cost.findChildren(QLabel), f"{pages} pages: no labels at all"
        cost.deleteLater()
    return seen


def test_no_estimate_of_one_to_two_hundred_and_fifty_pages_reads_zero(qtbot) -> None:  # type: ignore[no-untyped-def]
    assert _zero_readings(qtbot, 250) == []


def test_a_sub_cent_estimate_never_reads_zero(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control with teeth: at one micro-dollar a page, every estimate up
    to 250 pages is under a cent. Rounding to nearest shows $0.00; up, $0.01."""
    monkeypatch.setattr(budget, "BOOTSTRAP_PAGE_ESTIMATE", Usd.from_micro(1))

    assert _zero_readings(qtbot, 250) == []
    one = _cost(qtbot, 1)
    assert _label(one, ESTIMATE).text() == "Estimated for 1 page: $0.01."
    most = _cost(qtbot, 250)
    assert _label(most, ESTIMATE).text() == "Estimated for 250 pages: $0.01."


# =============================================================================
# C-2: names, absences, label rules, accessibility
# =============================================================================


def test_the_estimate_is_a_frame_named_summary_cost_estimate(qtbot) -> None:  # type: ignore[no-untyped-def]
    cost = _cost(qtbot, 20)

    assert isinstance(cost, QFrame)
    assert cost.objectName() == FRAME


def test_the_frame_is_named_by_its_visible_lines(qtbot) -> None:  # type: ignore[no-untyped-def]
    for pages, lines in (
        (1, ["Estimated for 1 page: $0.06.", "Budget $2.00."]),
        (34, ["Estimated for 34 pages: $2.04.", f"Budget $2.00. {OVER}"]),
        (
            201,
            [
                "Estimated for 201 pages: $12.06.",
                f"Budget $2.00. {OVER}",
                "That is more pages than a chapter. Estimated cost is $12.06.",
            ],
        ),
    ):
        cost = _cost(qtbot, pages)
        assert _lines(cost) == lines, f"{pages} pages"
        assert cost.accessibleName() == "\n".join(lines), f"{pages} pages"


def test_every_estimate_label_is_plain_word_wrapped_mouse_selectable_and_never_a_focus_stop(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    cost = _cost(qtbot, 201)

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


def test_the_summary_carries_a_cost_estimate_of_its_page_count(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _summary(qtbot, _chapter(20))

    cost = summary.cost_estimate
    assert isinstance(cost, CostEstimate)
    assert summary.findChild(CostEstimate, FRAME) is cost
    assert _label(cost, ESTIMATE).text() == "Estimated for 20 pages: $1.20."
    assert _label(cost, BUDGET).text() == "Budget $2.00."


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
        "Estimated for 12 pages: $0.72.",
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

    assert lines[4:6] == ["Estimated for 34 pages: $2.04.", f"Budget $2.00. {OVER}"]


# =============================================================================
# C-4: through the window, from a real folder
# =============================================================================


def test_a_folder_of_pages_opened_by_the_app_shows_its_estimate(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
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
    assert _label(cost, ESTIMATE).text() == "Estimated for 3 pages: $0.18."
    assert _label(cost, BUDGET).text() == "Budget $2.00."
    assert cost.over_budget is False
