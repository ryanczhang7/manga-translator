"""MT-018 AC-9: a chapter opened for review shows its cost in the workspace header.

`Workspace` gains `cost_readout: CostReadout` inside `self.header`, and
`load_chapter(project)` calls `cost_readout.show_final(...)` with the ledger's
chapter total when any call was priced, else `None` (story `## Contract`,
"Workspace header"). The ceiling is the chapter's stored ceiling, or
`DEFAULT_CEILING` when none is stored.

Mechanical: real projects built with `create_project` in `tmp_path`, priced
calls appended with the real `ledger.record_call`. The keying is on whether a
call **exists**, not on the total being non-zero: one recorded call that cost
$0.00 is a priced chapter that cost nothing, which is the one place `$0.00` is
the truth.

`show_final` must post no accessibility alert - eleven existing `load_chapter`
callers include tests that count alerts through `mangatl.ui.link.QAccessible`.

**RED:** the module imports only what exists, so the fixtures (a real project,
a real `run` row, real ledger rows) execute; the first test fails on the missing
`mangatl.ui.cost_readout` and the rest on
`AttributeError: 'Workspace' object has no attribute 'cost_readout'`.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication, QLabel

import mangatl.ui.link as link_module
from mangatl.domain.money import Usd
from mangatl.domain.page import Chapter, Page
from mangatl.domain.rates import CostRecord
from mangatl.store.ledger import record_call
from mangatl.store.project import Project, create_project
from mangatl.ui.workspace import Workspace

DASH = "$\N{EM DASH}"
ZERO = "$0.00"
FINAL = "\N{MIDDLE DOT} final"  # "of $2.00", a middle dot, "final"


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _chapter(source: Path, pages: int = 3) -> Chapter:
    source.mkdir()
    return Chapter(
        source_dir=source,
        pages=tuple(
            Page(ordinal=i, filename=f"{i:03}.png", width=64, height=96, sha256=f"{i}" * 64)
            for i in range(pages)
        ),
    )


def _open_run(project: Project) -> int:
    """A `run` row, written the way the runner writes one (raw SQL: the ledger's
    foreign key needs one, and a UI test should not drive the pipeline)."""
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-10-01T09:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


def _price(project: Project, run_id: int, ordinal: int, cost: str) -> None:
    record_call(
        project,
        run_id,
        ordinal,
        f"req-{run_id}-{ordinal}-{cost}",
        CostRecord(
            model_id="claude-test",
            input_tokens=1_000,
            output_tokens=200,
            cache_write_tokens=0,
            cache_read_tokens=0,
            cost=Usd(Decimal(cost)),
            rate_table_version="2026-09-12",
        ),
    )


def _store_ceiling(project: Project, micro: int) -> None:
    with project.transaction() as cursor:
        cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))


@pytest.fixture
def unpriced(tmp_path: Path) -> Iterator[Project]:
    with create_project(_chapter(tmp_path / "plain"), tmp_path / "plain.mtproj") as project:
        yield project


@pytest.fixture
def priced(tmp_path: Path) -> Iterator[Project]:
    """Two priced calls, $0.40 and $0.43: a chapter total of $0.83."""
    with create_project(_chapter(tmp_path / "paid"), tmp_path / "paid.mtproj") as project:
        run_id = _open_run(project)
        _price(project, run_id, 0, "0.40")
        _price(project, run_id, 1, "0.43")
        yield project


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    posted: list[tuple[Any, Any]] = []
    stand_in = SimpleNamespace(
        Event=QAccessible.Event,
        updateAccessibility=lambda event: posted.append((event.type(), event.object())),
    )
    monkeypatch.setattr(link_module, "QAccessible", stand_in)
    return posted


def _open(qtbot) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.resize(1100, 720)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    return window


def test_the_workspace_header_holds_a_cost_readout(qtbot) -> None:  # type: ignore[no-untyped-def]
    # Imported here, not at module level, so that in RED the other tests in this
    # file still run against the real Workspace and fail on the missing attribute
    # rather than all failing at collection.
    from mangatl.ui.cost_readout import CostReadout

    window = _open(qtbot)

    assert isinstance(window.cost_readout, CostReadout)
    assert window.header.isAncestorOf(window.cost_readout), "the readout is not in the header"


def test_a_priced_chapter_shows_its_chapter_total_as_final(qtbot, priced: Project) -> None:  # type: ignore[no-untyped-def]
    window = _open(qtbot)

    window.load_chapter(priced)
    _settle()

    readout = window.cost_readout
    assert readout.state() == "final"
    assert readout.figure.text() == "$0.83"
    assert readout.budget_label.text() == f"of $2.00 {FINAL}"


def test_a_chapter_with_no_priced_call_shows_a_dash_not_zero_dollars(
    qtbot,  # type: ignore[no-untyped-def]
    unpriced: Project,
) -> None:
    window = _open(qtbot)

    window.load_chapter(unpriced)
    _settle()

    readout = window.cost_readout
    assert readout.state() == "unknown"
    assert readout.figure.text() == DASH
    texts = [label.text() for label in readout.findChildren(QLabel)]
    assert not any(ZERO in text for text in texts), f"an unpriced chapter shows $0.00: {texts}"


def test_one_priced_call_that_cost_nothing_is_a_final_zero_not_unknown(
    qtbot,  # type: ignore[no-untyped-def]
    unpriced: Project,
) -> None:
    """Keyed on whether a call exists (`chapter_call_costs` non-empty), not on
    whether the total is non-zero."""
    _price(unpriced, _open_run(unpriced), 0, "0")
    window = _open(qtbot)

    window.load_chapter(unpriced)
    _settle()

    assert window.cost_readout.state() == "final"
    assert window.cost_readout.figure.text() == ZERO


def test_the_chapters_stored_ceiling_is_the_budget_shown(qtbot, priced: Project) -> None:  # type: ignore[no-untyped-def]
    _store_ceiling(priced, 5_000_000)
    window = _open(qtbot)

    window.load_chapter(priced)
    _settle()

    assert window.cost_readout.budget_label.text() == f"of $5.00 {FINAL}"


def test_loading_an_unpriced_chapter_after_a_priced_one_goes_back_to_a_dash(
    qtbot,  # type: ignore[no-untyped-def]
    priced: Project,
    unpriced: Project,
) -> None:
    window = _open(qtbot)
    window.load_chapter(priced)
    _settle()
    assert window.cost_readout.figure.text() == "$0.83"

    window.load_chapter(unpriced)
    _settle()

    assert window.cost_readout.state() == "unknown"
    assert window.cost_readout.figure.text() == DASH


def test_opening_a_chapter_over_75_percent_spent_does_not_announce(
    qtbot,  # type: ignore[no-untyped-def]
    unpriced: Project,
    alerts: list[tuple[Any, Any]],
) -> None:
    """The post-run total is history, not a warning: no alert from the readout,
    whatever the total."""
    run_id = _open_run(unpriced)
    _price(unpriced, run_id, 0, "1.00")
    _price(unpriced, run_id, 1, "0.90")
    window = _open(qtbot)
    alerts.clear()

    window.load_chapter(unpriced)
    _settle()

    assert window.cost_readout.figure.text() == "$1.90"
    from_readout = [a for a in alerts if a[1] == window.cost_readout.live_region]
    assert from_readout == [], f"show_final announced: {from_readout}"
