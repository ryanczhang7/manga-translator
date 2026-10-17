"""`mangatl.bench.cost`: S5, the chapter's cost, read out of the ledger.

MT-075, AC-1..AC-6 and `## Contract` blocks 1-3. Every criterion is mechanical:
the oracle is the ledger's own sum (`Usd.__add__` folded with `reduce`, and
`store.ledger.chapter_total`), `Usd.from_micro` of a number stated here, or a
pinned string. Nothing in this file designs a metric or a threshold.

**The fixture.** A chapter of tiny PNGs built the way `tests/core/test_ledger.py`
builds one: `create_project(read_chapter(folder), project_dir_for(folder))`, a
`run` row inserted with raw SQL (`_open_run`, copied from that file, because
`bench` sits beside `pipeline` and a bench test that reached into the
orchestrator would break for the wrong reason), and every call recorded with
`store.ledger.record_call` from `domain.rates.price` - never an `llm_call` row
written directly, so what these tests sum is what the product writes.

**The twenty calls** are `test_ledger.py`'s `_TWENTY_CALLS`, copied rather than
imported (a test module is not a library). Their exact sum is 279,280
micro-dollars, $0.27928, which is not representable as an IEEE-754 double - so a
total that travelled through a `float` anywhere cannot equal it. 279,280 is also
exactly AC-4's three-page total, so one table serves AC-1, AC-3, AC-4 and AC-5.
Each call's `micro` is a number read out of MT-012's handoff, not recomputed
here; `_record` asserts `price` still produces it, so a rate change surfaces as
a fixture failure naming the call rather than as a wrong total.

**The figures every assertion reads out** (all exact, micro-dollars):

- AC-1 total 279,280 ($0.27928), per page over 2 pages 139,640;
- AC-3 doubles call #1 (6,215): total 285,495, per page 142,747.5 -> 142,748
  (half up);
- AC-4 279,280 / 3 = 93,093.33... -> 93,093; and 1 / 2 = 0.5 -> 1 (half up;
  half-even and truncation both give 0);
- AC-5 prints `$0.2793` and `$0.1396` (`str(Usd)`, four places).

**Timing.** No `pytest-timeout` in this project and no per-test budget; every
test builds a chapter of at most three 40 x 30 PNGs and records at most
twenty-one rows.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import runpy
import sqlite3
import sys
import warnings
from collections.abc import Callable, Iterator
from decimal import ROUND_HALF_UP, Decimal
from functools import reduce
from operator import add
from pathlib import Path
from typing import NamedTuple

import pytest

from mangatl.bench.cost import DASH, CostReport, main, measure_cost
from mangatl.domain.money import Usd
from mangatl.domain.rates import CostRecord, price
from mangatl.domain.translation import TokenUsage
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import chapter_total, record_call
from mangatl.store.project import (
    SCHEMA_VERSION,
    Project,
    create_project,
    project_dir_for,
)

_PROG = "python -m mangatl.bench.cost"
_PAGE_W, _PAGE_H = 40, 30
_INSERT_RUN = "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)"

#: The module AC-6 reads as text. Located on disk rather than through the
#: imported module, so the source check reads the file GREEN writes and nothing
#: an import hook could stand in for.
_COST_SOURCE = Path(__file__).resolve().parents[2] / "src" / "mangatl" / "bench" / "cost.py"


class _Call(NamedTuple):
    """One call to price, and the micro-dollars `price` must come to."""

    model_id: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    micro: int


#: `test_ledger.py`'s `_TWENTY_CALLS`, verbatim. Exact sum 279,280.
_TWENTY_CALLS: tuple[_Call, ...] = (
    _Call("claude-opus-5", 1000, 400, 1, 0, 15006),
    _Call("claude-sonnet-5", 1037, 413, 4, 7, 6215),
    _Call("claude-opus-5", 1074, 426, 7, 14, 16071),
    _Call("claude-sonnet-5", 1111, 439, 10, 21, 6641),
    _Call("claude-opus-5", 1148, 452, 13, 28, 17135),
    _Call("claude-sonnet-5", 1185, 465, 16, 35, 7067),
    _Call("claude-opus-5", 1222, 478, 19, 42, 18200),
    _Call("claude-sonnet-5", 1259, 491, 22, 49, 7493),
    _Call("claude-opus-5", 1296, 504, 25, 56, 19264),
    _Call("claude-sonnet-5", 1333, 517, 28, 63, 7919),
    _Call("claude-opus-5", 1370, 530, 31, 70, 20329),
    _Call("claude-sonnet-5", 1407, 543, 34, 77, 8344),
    _Call("claude-opus-5", 1444, 556, 37, 84, 21393),
    _Call("claude-sonnet-5", 1481, 569, 40, 91, 8770),
    _Call("claude-opus-5", 1518, 582, 43, 98, 22458),
    _Call("claude-sonnet-5", 1555, 595, 46, 105, 9196),
    _Call("claude-opus-5", 1592, 608, 49, 112, 23522),
    _Call("claude-sonnet-5", 1629, 621, 52, 119, 9622),
    _Call("claude-opus-5", 1666, 634, 55, 126, 24587),
    _Call("claude-sonnet-5", 1703, 647, 58, 133, 10048),
)

#: Their exact sum: $0.27928.
_TWENTY_TOTAL_MICRO = 279_280

#: Five cache-read tokens on sonnet at $0.20/MTok: exactly 1.0 micro-dollar,
#: so `price` yields `Usd.from_micro(1)` with no rounding of its own.
_ONE_MICRO_CALL = _Call("claude-sonnet-5", 0, 0, 0, 5, 1)

#: AC-3's doubled call: `_TWENTY_CALLS[1]`, 6,215 micro-dollars - odd, so the
#: new per-page quotient lands on a half and the rounding rule is exercised.
_DOUBLED = 1


# -- helpers -------------------------------------------------------------------


def _write_chapter(folder: Path, png_bytes: Callable[..., bytes], pages: int) -> Path:
    folder.mkdir()
    for index in range(pages):
        (folder / f"p{index + 1}.png").write_bytes(png_bytes(_PAGE_W, _PAGE_H, (index * 40, 0, 0)))
    return folder


def _open_run(project: Project, started_at: str) -> int:
    """A `run` row for the chapter, by raw SQL - `test_ledger.py`'s `_open_run`."""
    with project.transaction() as cursor:
        chapter_id = cursor.execute("SELECT id FROM chapter").fetchone()[0]
        cursor.execute(_INSERT_RUN, (chapter_id, started_at))
        return int(cursor.lastrowid or 0)


def _usage(call: _Call) -> TokenUsage:
    """By keyword: `TokenUsage` orders the cache counts read-then-write."""
    return TokenUsage(
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cache_read_tokens=call.cache_read_tokens,
        cache_write_tokens=call.cache_write_tokens,
    )


def _record(project: Project, run_id: int, ordinal: int, call: _Call, tag: str) -> CostRecord:
    """Price `call`, record it against `(run_id, ordinal)`, and return the record."""
    record = price(call.model_id, _usage(call))
    assert record.cost == Usd.from_micro(call.micro), f"fixture: {call} no longer prices as stated"
    record_call(project, run_id, ordinal, f"req-{tag}", record)
    return record


def _per_page_rule(total: Usd, pages: int) -> Usd:
    """Contract block 1's per-page rule, spelled out once for AC-3's comparison."""
    return Usd((total.amount / pages).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


class _Chapter(NamedTuple):
    folder: Path
    project: Project
    first_run: tuple[Usd, ...]
    second_run: tuple[Usd, ...]
    records: tuple[CostRecord, ...]
    run_ids: tuple[int, int]


def _record_twenty_over_two_runs(
    folder: Path, project: Project, *, all_on_page_zero: bool
) -> _Chapter:
    """AC-1's ledger: calls 0..9 against a first run, 10..19 against a resume,
    alternating pages 0 and 1 (or all on page 0)."""
    first = _open_run(project, "2026-10-17T09:00:00+00:00")
    second = _open_run(project, "2026-10-17T11:00:00+00:00")
    records: list[CostRecord] = []
    for index, call in enumerate(_TWENTY_CALLS):
        run_id = first if index < 10 else second
        ordinal = 0 if all_on_page_zero else index % 2
        records.append(_record(project, run_id, ordinal, call, f"{index}"))
    costs = tuple(record.cost for record in records)
    return _Chapter(
        folder=folder,
        project=project,
        first_run=costs[:10],
        second_run=costs[10:],
        records=tuple(records),
        run_ids=(first, second),
    )


def _lines(text: str) -> list[str]:
    return text.splitlines()


# -- fixtures ------------------------------------------------------------------


@pytest.fixture
def folder(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    """The two-page chapter's folder of scans."""
    return _write_chapter(tmp_path / "chapter", png_bytes, 2)


@pytest.fixture
def project(folder: Path) -> Iterator[Project]:
    with create_project(read_chapter(folder), project_dir_for(folder)) as opened:
        yield opened


@pytest.fixture
def chapter(folder: Path, project: Project) -> _Chapter:
    """AC-1's chapter: two pages, twenty priced calls over two runs, both pages."""
    return _record_twenty_over_two_runs(folder, project, all_on_page_zero=False)


# -- Contract block 1: the shapes ----------------------------------------------


def test_the_dash_is_dollar_em_dash_the_readouts_glyph_for_nothing_priced() -> None:
    assert DASH == "$\N{EM DASH}"


def test_the_report_has_exactly_total_calls_pages_and_per_page_in_that_order() -> None:
    assert [field.name for field in dataclasses.fields(CostReport)] == [
        "total",
        "calls",
        "pages",
        "per_page",
    ]


def test_the_report_is_frozen(project: Project) -> None:
    report = measure_cost(project)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.calls = 99  # type: ignore[misc]


# -- AC-1: the chapter's total is the ledger's, exactly, across every run ------


def test_ac1_the_chapter_total_is_the_exact_fold_of_every_recorded_cost_across_both_runs(
    chapter: _Chapter,
) -> None:
    report = measure_cost(chapter.project)

    every_cost = chapter.first_run + chapter.second_run
    assert report.total == reduce(add, every_cost)
    assert report.total == chapter_total(chapter.project)
    assert report.total == Usd.from_micro(_TWENTY_TOTAL_MICRO)
    assert report.total is not None
    assert report.total.amount == Decimal("0.27928")
    # The device: $0.27928 is not a double, so a float anywhere on the way misses it.
    assert Decimal(float(Decimal("0.27928"))) != Decimal("0.27928")


def test_ac1_the_calls_count_every_ledger_row_and_the_pages_are_the_chapters(
    chapter: _Chapter,
) -> None:
    report = measure_cost(chapter.project)

    assert report.calls == 20
    assert report.pages == len(chapter.project.pages()) == 2


def test_ac1_both_runs_count_so_dropping_either_runs_calls_breaks_the_equality(
    chapter: _Chapter,
) -> None:
    """A resumed chapter is two `run` rows and one spend. The two runs' sums are
    unequal and non-zero, so a total that read either run alone differs."""
    report = measure_cost(chapter.project)

    first, second = reduce(add, chapter.first_run), reduce(add, chapter.second_run)
    assert first != Usd.from_micro(0) and second != Usd.from_micro(0)
    assert report.total != first, "S5 is only the first run's spend"
    assert report.total != second, "S5 is only the resumed run's spend"
    assert report.total == first + second


def test_ac1_a_single_priced_call_is_a_total_of_that_call(project: Project) -> None:
    run_id = _open_run(project, "2026-10-17T09:00:00+00:00")
    record = _record(project, run_id, 1, _TWENTY_CALLS[4], "one")

    report = measure_cost(project)

    assert report.total == record.cost == Usd.from_micro(17135)
    assert report.calls == 1
    assert report.pages == 2


def test_a_call_priced_at_zero_is_a_measured_zero_not_nothing_priced(project: Project) -> None:
    """MT-018's rule, restated in `## Context`: `$—` is keyed on a call
    *existing*, not on the total being non-zero. A wordless page priced at zero
    is a measured $0, and the report says `Usd` zero, not `None`."""
    run_id = _open_run(project, "2026-10-17T09:00:00+00:00")
    _record(project, run_id, 0, _Call("claude-opus-5", 0, 0, 0, 0, 0), "zero")

    report = measure_cost(project)

    assert report.total == Usd.from_micro(0)
    assert report.per_page == Usd.from_micro(0)
    assert report.calls == 1


# -- AC-2: nothing priced is `$—`, never `$0.00` -------------------------------


@pytest.mark.parametrize("with_run", [False, True], ids=["no-run", "a-run-with-no-calls"])
def test_ac2_a_chapter_with_no_ledger_rows_reports_none_rather_than_zero(
    project: Project, with_run: bool
) -> None:
    if with_run:
        _open_run(project, "2026-10-17T09:00:00+00:00")

    report = measure_cost(project)

    assert report.total is None
    assert report.per_page is None
    assert report.calls == 0
    assert report.pages == 2


def test_ac2_the_command_prints_the_dash_for_both_figures_and_never_zero_dollars(
    folder: Path, project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.__exit__()

    status = main([str(folder)])

    captured = capsys.readouterr()
    out = _lines(captured.out)
    assert status == 0
    assert captured.err == ""
    assert len(out) == 2, out
    assert re.fullmatch(r"S5 chapter cost\s+\$\N{EM DASH}\s+no priced calls", out[0]), out[0]
    assert re.fullmatch(r"per page\s+\$\N{EM DASH}\s+2 pages", out[1]), out[1]
    assert "$0.00" not in captured.out


# -- AC-3 (negative control): one entry doubled raises S5 by exactly that entry -


def test_ac3_control_recording_one_call_twice_raises_the_total_by_exactly_its_cost(
    chapter: _Chapter,
) -> None:
    before = measure_cost(chapter.project)
    doubled = chapter.records[_DOUBLED]
    assert doubled.cost == Usd.from_micro(6215)

    # The same CostRecord, the same run and the same page as its first recording.
    record_call(chapter.project, chapter.run_ids[0], _DOUBLED % 2, "req-retried", doubled)
    after = measure_cost(chapter.project)

    assert before.total is not None
    assert after.total == before.total + doubled.cost
    assert after.total == Usd.from_micro(285_495)
    assert after.total != before.total
    assert after.calls == before.calls + 1 == 21


def test_ac3_control_the_doubled_entry_moves_the_per_page_figure_but_not_the_page_count(
    chapter: _Chapter,
) -> None:
    doubled = chapter.records[_DOUBLED]
    record_call(chapter.project, chapter.run_ids[0], _DOUBLED % 2, "req-retried", doubled)

    after = measure_cost(chapter.project)

    assert after.pages == 2
    assert after.total is not None
    assert after.per_page == _per_page_rule(after.total, 2)
    # 285,495 / 2 = 142,747.5, half up.
    assert after.per_page == Usd.from_micro(142_748)


# -- AC-4: the per-page figure, rounded once to a micro-dollar, half up ---------


def test_ac4_a_total_over_three_pages_rounds_to_the_nearest_micro_dollar(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    three = _write_chapter(tmp_path / "three", png_bytes, 3)
    with create_project(read_chapter(three), project_dir_for(three)) as opened:
        run_id = _open_run(opened, "2026-10-17T09:00:00+00:00")
        for index, call in enumerate(_TWENTY_CALLS):
            _record(opened, run_id, index % 3, call, f"{index}")

        report = measure_cost(opened)

    assert report.pages == 3
    assert report.total == Usd.from_micro(279_280)
    # 279,280 / 3 = 93,093.333...
    assert report.per_page == Usd.from_micro(93093)


def test_ac4_one_micro_dollar_over_two_pages_rounds_half_up_to_one_not_to_even(
    project: Project,
) -> None:
    run_id = _open_run(project, "2026-10-17T09:00:00+00:00")
    _record(project, run_id, 0, _ONE_MICRO_CALL, "one-micro")

    report = measure_cost(project)

    assert report.total == Usd.from_micro(1)
    assert report.pages == 2
    # 1 / 2 = 0.5 micro-dollars: ROUND_HALF_UP gives 1; half-even and truncation give 0.
    assert report.per_page == Usd.from_micro(1)


def test_ac4_an_even_split_over_two_pages_is_exact(chapter: _Chapter) -> None:
    report = measure_cost(chapter.project)

    assert report.per_page == Usd.from_micro(139_640)


def test_ac4_the_divisor_is_the_chapters_page_count_not_the_pages_that_carry_a_call(
    folder: Path, project: Project
) -> None:
    """Every call on page 0; page 1 never reached. Per page is still total / 2."""
    _record_twenty_over_two_runs(folder, project, all_on_page_zero=True)

    report = measure_cost(project)

    assert report.pages == 2
    assert report.total == Usd.from_micro(279_280)
    assert report.per_page == Usd.from_micro(139_640)


# -- AC-5: the command prints two lines and exits as its siblings do ------------


def test_ac5_the_command_prints_the_chapter_figure_and_the_per_page_figure_and_returns_zero(
    chapter: _Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter.project.__exit__()
    total, per_page = Usd.from_micro(279_280), Usd.from_micro(139_640)
    assert (str(total), str(per_page)) == ("$0.2793", "$0.1396")

    status = main([str(chapter.folder)])

    captured = capsys.readouterr()
    out = _lines(captured.out)
    assert status == 0
    assert captured.err == ""
    assert len(out) == 2, out
    assert re.fullmatch(rf"S5 chapter cost\s+{re.escape(str(total))}\s+20 priced calls", out[0]), (
        out[0]
    )
    assert re.fullmatch(rf"per page\s+{re.escape(str(per_page))}\s+2 pages", out[1]), out[1]


def test_ac5_one_call_is_still_priced_calls_plural_nothing_pluralises(
    folder: Path, project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = _open_run(project, "2026-10-17T09:00:00+00:00")
    _record(project, run_id, 0, _TWENTY_CALLS[4], "one")
    project.__exit__()

    status = main([str(folder)])

    out = _lines(capsys.readouterr().out)
    assert status == 0
    assert re.fullmatch(r"S5 chapter cost\s+\$0\.0171\s+1 priced calls", out[0]), out[0]
    assert re.fullmatch(r"per page\s+\$0\.0086\s+2 pages", out[1]), out[1]


def _no_folder(tmp_path: Path, folder: Path) -> list[str]:
    return [str(tmp_path / "never-existed")]


def _no_project(tmp_path: Path, folder: Path) -> list[str]:
    other = tmp_path / "chapter-two"
    other.mkdir()
    for page in folder.iterdir():
        (other / page.name).write_bytes(page.read_bytes())
    return [str(other)]


def _schema_too_new(tmp_path: Path, folder: Path) -> list[str]:
    connection = sqlite3.connect(project_dir_for(folder) / "project.db")
    try:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1:d}")
        connection.commit()
    finally:
        connection.close()
    return [str(folder)]


@pytest.mark.parametrize(
    "arrange",
    [_no_folder, _no_project, _schema_too_new],
    ids=["no-such-folder", "no-project", "schema-too-new"],
)
def test_ac5_the_command_returns_two_with_one_stderr_line_and_no_stdout_when_it_cannot_measure(
    tmp_path: Path,
    folder: Path,
    project: Project,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[Path, Path], list[str]],
) -> None:
    project.__exit__()
    argv = arrange(tmp_path, folder)

    status = main(argv)

    captured = capsys.readouterr()
    err = _lines(captured.err)
    assert status == 2
    assert captured.out == ""
    assert len(err) == 1, err
    assert err[0].startswith(f"{_PROG}: "), err[0]
    assert "Traceback" not in captured.err


def test_python_dash_m_runs_main_and_exits_with_its_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`python -m mangatl.bench.cost FOLDER` is the entry point (Contract block 2)."""
    monkeypatch.setattr(sys, "argv", [_PROG, str(tmp_path / "never-existed")])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # runpy: already imported
        with pytest.raises(SystemExit) as exited:
            runpy.run_module("mangatl.bench.cost", run_name="__main__")

    assert exited.value.code == 2
    assert capsys.readouterr().err.startswith(f"{_PROG}: ")


def test_the_command_takes_no_truth_option(
    folder: Path, project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    """Contract block 3 and PO-2: S5 has no truth input. argparse refuses it."""
    project.__exit__()

    with pytest.raises(SystemExit) as exited:
        main([str(folder), "--truth", str(folder) + ".truth.json"])

    assert exited.value.code == 2
    assert capsys.readouterr().out == ""


# -- AC-6: the module reads the ledger through store.ledger and prices nothing --


def _source_tree() -> ast.Module:
    return ast.parse(_COST_SOURCE.read_text("utf-8"))


def _identifiers(tree: ast.Module) -> set[str]:
    """Every name the module binds, uses or imports - not module paths, so the
    contract's own `from operator import add` is not read as a `rate`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add(node.name)
            if node.asname:
                names.add(node.asname)
    return names


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_ac6_cost_imports_chapter_call_costs_from_the_ledger() -> None:
    tree = _source_tree()

    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "mangatl.store.ledger"
        and any(alias.name == "chapter_call_costs" for alias in node.names)
        for node in ast.walk(tree)
    ), "cost.py does not read the ledger through chapter_call_costs"


def test_ac6_cost_imports_neither_ui_nor_pipeline_nor_the_rate_table() -> None:
    modules = _imported_modules(_source_tree())

    for forbidden in ("mangatl.ui", "mangatl.pipeline", "mangatl.domain.rates"):
        offending = {m for m in modules if m == forbidden or m.startswith(forbidden + ".")}
        assert not offending, f"cost.py imports {sorted(offending)}"
    assert "rates" not in _identifiers(_source_tree()), "cost.py imports rates from a package"


def test_ac6_no_name_in_cost_mentions_a_price_or_a_rate() -> None:
    """A bench that re-priced a call would be a second answer to one question."""
    offending = sorted(
        name
        for name in _identifiers(_source_tree())
        if "price" in name.lower() or "rate" in name.lower()
    )

    assert not offending, f"cost.py names {offending}"


def test_cost_does_not_read_the_budget_ceiling() -> None:
    """Contract block 3: not read `budget_ceiling`, not project, not judge."""
    assert not any("budget" in name.lower() for name in _identifiers(_source_tree()))
