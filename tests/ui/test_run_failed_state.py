"""MT-059 C-5 / D-3 / D-4: the run panel's failed state (AC-5, AC-8).

`RunProgressPanel.on_event(RunAborted)` whose reason is neither
`pipeline.runner.BUDGET` nor `pipeline.runner.CANCELLED` builds an
`ErrorBanner` holding the runner's reason verbatim. The budget banner is
MT-018's and `test_run_progress.py` pins it; this file adds only what D-3 says
applies to it too (focus moves to its action, which Return and Enter activate).

Oracle partition: **settled**, every string spelled out here from the story's
`## Design notes` D-3 table (EM DASH U+2014, EN DASH U+2013), never read back from
`mangatl.ui.progress`. `{n}` = ordinal + 1, `{kept}` = ordinal; with no ordinal
`{kept}` falls back to completed + skipped, as the budget arm does, and `{n}` is
then `{kept}` + 1 (the budget arm's own headline rule; C-5 as amended in RED).

The reasons carry `<b>`, `&` and a second colon so that a banner built as rich
text, or one that re-derives the reason from the exception type, shows a
different string (DV-3's wrong value is a fixed string; this file's reasons are
all distinct, so a fixed one fails every case).

**RED:** the panel exists (MT-018) and ignores a non-budget abort, so these
fail on the assertion that a banner exists, or on focus and key activation for
the budget banner. No real-time waits beyond window activation and focus.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QPushButton

from mangatl.domain.budget import Projection
from mangatl.domain.events import (
    CallPriced,
    PageSkipped,
    PageStarted,
    RunAborted,
    RunEvent,
    RunStarted,
    StageFinished,
)
from mangatl.domain.money import Usd
from mangatl.pipeline.runner import BUDGET, CANCELLED
from mangatl.ui.progress import ErrorBanner, RunProgressPanel

EM = "\N{EM DASH}"
EN = "\N{EN DASH}"
REASON = "RuntimeError: the model returned <b>nothing</b> & no: text"
SURVIVED = "are translated and can be reviewed and rendered."
NONE_KEPT = "No pages were translated."


def _shown(qtbot) -> RunProgressPanel:  # type: ignore[no-untyped-def]
    panel = RunProgressPanel()
    qtbot.addWidget(panel)
    panel.resize(800, 500)
    with qtbot.waitExposed(panel):
        panel.show()
    panel.activateWindow()
    qtbot.waitUntil(panel.isActiveWindow)
    return panel


def _feed(panel: RunProgressPanel, *events: RunEvent) -> None:
    for event in events:
        panel.on_event(event)
    QApplication.processEvents()


def _fail_at(panel: RunProgressPanel, ordinal: int, reason: str = REASON, pages: int = 20) -> None:
    _feed(
        panel,
        RunStarted(run_id=1, page_count=pages),
        *[PageStarted(ordinal=o) for o in range(ordinal + 1)],
        RunAborted(reason=reason, ordinal=ordinal),
    )


def _banner(panel: RunProgressPanel) -> ErrorBanner:
    banner = panel.banner
    assert isinstance(banner, ErrorBanner), f"no failed banner after a failed run: {banner!r}"
    return banner


# =============================================================================
# The copy: kept >= 1, kept = 0, and the ordinal-less fallback
# =============================================================================


def test_a_failure_on_page_5_of_20_names_the_page_the_reason_and_what_survived(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    panel = _shown(qtbot)

    _fail_at(panel, 4)

    banner = _banner(panel)
    assert banner.headline.text() == f"Run stopped at page 5 of 20 {EM} page 5 failed."
    assert banner.body.text() == f"{REASON}\nPages 1{EN}4 {SURVIVED}"
    assert [b.text() for b in banner.actions] == [f"Review pages 1{EN}4"]
    assert all(isinstance(b, QPushButton) for b in banner.actions)
    assert banner.accessibleName() == f"{banner.headline.text()} {banner.body.text()}"


def test_a_failure_on_the_first_page_has_nothing_to_review(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _shown(qtbot)

    _fail_at(panel, 0, pages=3)

    banner = _banner(panel)
    assert banner.headline.text() == f"Run stopped at page 1 of 3 {EM} page 1 failed."
    assert banner.body.text() == f"{REASON}\n{NONE_KEPT}"
    assert banner.actions == ()
    assert banner.findChildren(QAbstractButton) == []


@pytest.mark.parametrize(
    "reason",
    [
        "TypeError: Could not resolve authentication method.",
        "OSError: [Errno 28] No space left on device",
        "ValueError: ",
    ],
)
def test_the_body_holds_the_runners_reason_verbatim(qtbot, reason: str) -> None:  # type: ignore[no-untyped-def]
    panel = _shown(qtbot)

    _fail_at(panel, 2, reason=reason, pages=9)

    body = _banner(panel).body
    assert body.text() == f"{reason}\nPages 1{EN}2 {SURVIVED}"
    assert body.textFormat() == Qt.TextFormat.PlainText, "the reason is not shown as plain text"


def test_with_no_ordinal_kept_is_completed_plus_skipped(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Pages 0 and 1 completed, page 2 skipped, page 3 in progress: kept = 3."""
    panel = _shown(qtbot)

    _feed(
        panel,
        RunStarted(run_id=1, page_count=20),
        PageStarted(ordinal=0),
        PageStarted(ordinal=1),
        PageSkipped(ordinal=2, reason="already done"),
        PageStarted(ordinal=3),
        RunAborted(reason=REASON, ordinal=None),
    )

    banner = _banner(panel)
    assert banner.headline.text() == f"Run stopped at page 4 of 20 {EM} page 4 failed."
    assert banner.body.text() == f"{REASON}\nPages 1{EN}3 {SURVIVED}"
    assert [b.text() for b in banner.actions] == [f"Review pages 1{EN}3"]


# =============================================================================
# The banner: where it is, what it is, what it does
# =============================================================================


def test_the_failed_banner_is_inside_the_panel_at_its_top_and_not_a_modal(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _shown(qtbot)

    _fail_at(panel, 4)

    banner = _banner(panel)
    assert not isinstance(banner, QDialog) and not banner.isWindow()
    assert panel.isAncestorOf(banner) and banner.isVisibleTo(panel)
    first = panel.layout().itemAt(0).widget()
    assert first is banner, f"the panel's first item is {first!r}, not the banner"
    assert QApplication.activeModalWidget() is None


def test_the_failed_banner_is_an_alert(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _shown(qtbot)
    _fail_at(panel, 4)

    interface = QAccessible.queryAccessibleInterface(_banner(panel))

    assert interface is not None
    assert interface.role() == QAccessible.Role.AlertMessage


def test_review_asks_for_the_kept_pages(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _shown(qtbot)
    _fail_at(panel, 4)
    requested: list[int] = []
    panel.review_requested.connect(requested.append)

    _banner(panel).actions[0].click()

    assert requested == [4]


def _abort(panel: RunProgressPanel, which: str) -> ErrorBanner:
    if which == "failed":
        _fail_at(panel, 4)
    else:
        _feed(
            panel,
            RunStarted(run_id=1, page_count=20),
            PageStarted(ordinal=4),
            RunAborted(reason=BUDGET, ordinal=4),
        )
    return _banner(panel)


@pytest.mark.parametrize("which", ["failed", "budget"])
def test_focus_moves_to_the_banners_review_action(qtbot, which: str) -> None:  # type: ignore[no-untyped-def]
    panel = _shown(qtbot)

    banner = _abort(panel, which)

    action = banner.actions[0]
    qtbot.waitUntil(action.hasFocus, timeout=2_000)


@pytest.mark.parametrize("which", ["failed", "budget"])
@pytest.mark.parametrize("key", ["Return", "Enter", "Space"])
def test_the_review_action_activates_once_on_return_enter_and_space(
    qtbot,  # type: ignore[no-untyped-def]
    which: str,
    key: str,
) -> None:
    panel = _shown(qtbot)
    action = _abort(panel, which).actions[0]
    requested: list[int] = []
    panel.review_requested.connect(requested.append)
    action.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(action.hasFocus, timeout=2_000)

    keys = {"Return": Qt.Key.Key_Return, "Enter": Qt.Key.Key_Enter, "Space": Qt.Key.Key_Space}
    QTest.keyClick(action, keys[key])
    QApplication.processEvents()

    assert requested == [4], f"{key} on the {which} banner's action asked {requested}"


# =============================================================================
# The cost readout is not the failed state's to touch; a cancel shows nothing
# =============================================================================

PRICED = CallPriced(
    ordinal=0,
    spent=Usd(Decimal("0.40")),
    ceiling=Usd(Decimal("2.00")),
    projection=Projection(
        next_call=Usd(Decimal("0.10")),
        remaining_chapter=Usd(Decimal("0.20")),
        basis="observed",
        sample_count=2,
    ),
)


def _readout(panel: RunProgressPanel) -> tuple[str, str, str, int, str]:
    readout = panel.cost_readout
    return (
        readout.state(),
        readout.figure.text(),
        readout.budget_label.text(),
        readout.meter.value(),
        readout.glyph.text(),
    )


@pytest.mark.parametrize("priced", [False, True], ids=["keyless-unknown", "after-a-call"])
def test_a_failure_leaves_the_cost_readout_exactly_as_it_was(qtbot, priced: bool) -> None:  # type: ignore[no-untyped-def]
    panel = _shown(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=20), PageStarted(ordinal=0))
    if priced:
        _feed(panel, StageFinished(ordinal=0, stage="translate", elapsed_ms=5), PRICED)
    before = _readout(panel)
    assert before[0] == ("normal" if priced else "unknown"), "precondition"

    _feed(panel, PageStarted(ordinal=1), RunAborted(reason=REASON, ordinal=1))

    _banner(panel)
    assert _readout(panel) == before, "the failed state changed the cost readout"


def test_a_cancelled_run_shows_no_banner_and_leaves_the_readout(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _shown(qtbot)
    _feed(panel, RunStarted(run_id=1, page_count=20), PageStarted(ordinal=4))
    before = _readout(panel)

    _feed(panel, RunAborted(reason=CANCELLED, ordinal=None))

    assert panel.banner is None
    assert panel.findChildren(ErrorBanner) == []
    assert _readout(panel) == before
