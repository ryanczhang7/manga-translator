"""`python -m mangatl.bench`: one command, one report, all six numbers.

MT-089, AC-1..AC-4 and `## Contract` blocks 1-3 and 5. Every criterion is
settled or mechanical; nothing here designs a metric.

**The oracle is the three modules' own public functions.** AC-1's expected
stdout is never typed in: it is computed, on the same project and the same
loaded document, as

    validate(truth, chapter).warnings
    + acceptance.render(measure(project, truth))
    + s2.render(measure_s2(project, truth))
    + cost.render(measure_cost(project))

and compared to stdout **line for line, unstripped**. AC-2's refusal messages are
not typed in either: each is read off the acceptance command's own stderr for the
same arrangement, so the two commands are pinned to agree (PO-3).

**The fixture** is `_s2_world`'s two-page chapter (three truth regions a page,
glyph strokes in each), because it is the one that already gives S2 a real
residual measurement. Its baseline project is completed so every number is a
real one: an OCR line and a proposal per region, every line accepted as-is
except page 1 region 2 (edited, so S1b is 5 / 6 rather than a trivially round
figure), every page cleaned white (`S2 PASS`, residual 0.0000 everywhere), and -
for the `priced` chapter - two calls recorded in the ledger with
`store.ledger.record_call` from `domain.rates.price`, as
`test_bench_cost.py`'s `_record` does. The unpriced chapter is identical but
for the ledger, so S5 prints its `$—` lines.

**Timing.** No `pytest-timeout` in this project and no per-test budget; every
test builds one two-page 200 x 200 chapter and records at most two ledger rows.
"""

from __future__ import annotations

import ast
import dataclasses
import runpy
import sqlite3
import sys
import tomllib
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import _s2_world as w
import pytest

import mangatl.bench.__main__ as bench_main
import mangatl.bench.acceptance as acceptance
import mangatl.bench.cost as cost
import mangatl.bench.s2 as s2
from mangatl.bench.__main__ import main
from mangatl.bench.acceptance import measure
from mangatl.bench.cost import DASH, measure_cost
from mangatl.bench.s2 import measure_s2
from mangatl.bench.truth import (
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    load_ground_truth,
    truth_path_for,
    validate,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.page import Chapter
from mangatl.domain.rates import price
from mangatl.domain.translation import TokenUsage
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import record_call
from mangatl.store.lines import commit_line
from mangatl.store.project import SCHEMA_VERSION, Project, open_project, project_dir_for

_PROG = "python -m mangatl.bench"
_ACCEPTANCE_PROG = "python -m mangatl.bench.acceptance"

_ROOT = Path(__file__).resolve().parents[2]
#: Read as text from disk (AC-3), not through the imported module.
_MAIN_SOURCE = _ROOT / "src" / "mangatl" / "bench" / "__main__.py"
_PYPROJECT = _ROOT / "pyproject.toml"

_INSERT_RUN = "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)"

#: The one line committed as an edit rather than accepted: S1b 5 / 6.
_EDITED = (1, 2)


class _Call(NamedTuple):
    """One call to price, and the micro-dollars `price` must come to."""

    model_id: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    micro: int


#: The first two of `test_ledger.py`'s `_TWENTY_CALLS`, verbatim: 21,221 micro-dollars.
_CALLS: tuple[_Call, ...] = (
    _Call("claude-opus-5", 1000, 400, 1, 0, 15006),
    _Call("claude-sonnet-5", 1037, 413, 4, 7, 6215),
)


# -- the chapter ---------------------------------------------------------------


def _proposal(ordinal: int, index: int) -> str:
    return f"The café on street {10 * ordinal + index} is open."


def _open_run(project: Project, started_at: str) -> int:
    """A `run` row for the chapter, by raw SQL - `test_ledger.py`'s `_open_run`."""
    with project.transaction() as cursor:
        chapter_id = cursor.execute("SELECT id FROM chapter").fetchone()[0]
        cursor.execute(_INSERT_RUN, (chapter_id, started_at))
        return int(cursor.lastrowid or 0)


def _record(project: Project, run_id: int, ordinal: int, call: _Call, tag: str) -> None:
    """Price `call` and record it against `(run_id, ordinal)` - `test_bench_cost.py`'s `_record`."""
    record = price(
        call.model_id,
        TokenUsage(
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cache_read_tokens=call.cache_read_tokens,
            cache_write_tokens=call.cache_write_tokens,
        ),
    )
    assert record.cost == Usd.from_micro(call.micro), f"fixture: {call} no longer prices as stated"
    record_call(project, run_id, ordinal, f"req-{tag}", record)


def _complete(folder: Path, *, priced: bool) -> None:
    """Finish the baseline project at `project_dir_for(folder)`, which the command opens."""
    with open_project(project_dir_for(folder)) as project:
        for ordinal in range(len(w.FILENAMES)):
            project.write_lines(ordinal, [OcrResult(f"せりふ{i}") for i in range(w.PER_PAGE)])
            project.write_proposed(ordinal, {i: _proposal(ordinal, i) for i in range(w.PER_PAGE)})
            for index in range(w.PER_PAGE):
                if (ordinal, index) == _EDITED:
                    commit_line(project, ordinal, index, "A different line.", "edited")
                else:
                    commit_line(project, ordinal, index, _proposal(ordinal, index), "accepted")
            project.write_cleaned(ordinal, w.cleaned_page(ordinal, w.WHITE))
        if priced:
            run_id = _open_run(project, "2026-10-22T09:00:00+00:00")
            for index, call in enumerate(_CALLS):
                _record(project, run_id, index % len(w.FILENAMES), call, f"{index}")


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return w.write_chapter(tmp_path / w.CHAPTER)


@pytest.fixture
def chapter(folder: Path) -> Chapter:
    return read_chapter(folder)


@pytest.fixture
def truth(folder: Path, chapter: Chapter) -> GroundTruth:
    """The baseline project, its seeded truth (loaded), the project completed and priced."""
    loaded = w.seeded_truth(folder, chapter)
    _complete(folder, priced=True)
    return loaded


@pytest.fixture
def unpriced(folder: Path, chapter: Chapter) -> GroundTruth:
    """The same chapter with no call in its ledger: S5 is unmeasured."""
    loaded = w.seeded_truth(folder, chapter)
    _complete(folder, priced=False)
    return loaded


class _Parts(NamedTuple):
    warnings: list[str]
    acceptance: list[str]
    s2: list[str]
    cost: list[str]

    def joined(self) -> list[str]:
        return [*self.warnings, *self.acceptance, *self.s2, *self.cost]


def _expected(folder: Path, truth: GroundTruth) -> _Parts:
    """AC-1's report, computed from the three public functions on the same project."""
    with open_project(project_dir_for(folder)) as project:
        return _Parts(
            warnings=list(validate(truth, project.chapter).warnings),
            acceptance=list(acceptance.render(measure(project, truth))),
            s2=list(s2.render(measure_s2(project, truth))),
            cost=list(cost.render(measure_cost(project))),
        )


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


# -- AC-1: one report, the three commands' own lines, in order -------------------


def test_ac1_the_report_is_the_warnings_once_then_s1_then_s2_then_s5_exactly_and_exits_zero(
    folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    parts = _expected(folder, truth)
    # The fixture is what it claims: every part present and carrying a real number.
    assert parts.warnings, "the seeded truth warns; the report must carry those warnings"
    assert parts.acceptance[0].startswith("S1b"), parts.acceptance
    assert "5 / ground truth 6" in parts.acceptance[0], parts.acceptance
    assert parts.s2[-1] == "S2 PASS", parts.s2
    assert parts.cost[0].startswith("S5 chapter cost  $0.0212  2 priced calls"), parts.cost

    status = main([str(folder)])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    assert captured.out.splitlines() == parts.joined()
    assert _lines(captured.out) == parts.joined()


def test_ac1_the_report_has_exactly_as_many_lines_as_its_four_parts_together(
    folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each part once: warnings are not printed per measurement, no part is dropped."""
    parts = _expected(folder, truth)

    main([str(folder)])

    out = _lines(capsys.readouterr().out)
    expected = len(parts.warnings) + len(parts.acceptance) + len(parts.s2) + len(parts.cost)
    assert len(out) == expected, (len(out), expected, out)
    assert sum(line in parts.warnings for line in out) == len(parts.warnings), out


def test_ac1_a_chapter_with_no_priced_call_reports_s5_as_the_dash_not_zero(
    folder: Path, unpriced: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    parts = _expected(folder, unpriced)
    assert parts.cost == [
        f"S5 chapter cost  {DASH}  no priced calls",
        f"per page         {DASH}  {len(w.FILENAMES)} pages",
    ]

    status = main([str(folder)])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    assert captured.out.splitlines() == parts.joined()


def test_ac1_the_truth_option_names_the_document_when_the_default_one_is_gone(
    tmp_path: Path, folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    parts = _expected(folder, truth)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = elsewhere / "annotation.json"
    truth_path_for(folder).rename(path)
    assert not truth_path_for(folder).exists()

    status = main([str(folder), "--truth", str(path)])

    captured = capsys.readouterr()
    assert status == 0, captured.err
    assert captured.err == ""
    assert captured.out.splitlines() == parts.joined()


# -- AC-2: a refusal is one stderr line, the acceptance command's message --------


def _no_folder(tmp_path: Path, folder: Path) -> list[str]:
    return [str(tmp_path / "never-existed")]


def _no_project(tmp_path: Path, folder: Path) -> list[str]:
    other = tmp_path / "chapter-two"
    other.mkdir()
    for filename in w.FILENAMES:
        (other / filename).write_bytes((folder / filename).read_bytes())
    return [str(other)]


def _schema_too_new(tmp_path: Path, folder: Path) -> list[str]:
    connection = sqlite3.connect(project_dir_for(folder) / "project.db")
    try:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1:d}")
        connection.commit()
    finally:
        connection.close()
    return [str(folder)]


def _no_document(tmp_path: Path, folder: Path) -> list[str]:
    truth_path_for(folder).unlink()
    return [str(folder)]


def _malformed_document(tmp_path: Path, folder: Path) -> list[str]:
    truth_path_for(folder).write_text("{not json", encoding="utf-8")
    return [str(folder)]


def _stale_document(tmp_path: Path, folder: Path) -> list[str]:
    """Page 0's sha256 wrong, page 1's right: exactly one validator error."""
    loaded = load_ground_truth(truth_path_for(folder))
    pages = (dataclasses.replace(loaded.pages[0], sha256="0" * 64), *loaded.pages[1:])
    w.write_doc(truth_path_for(folder), dataclasses.replace(loaded, pages=pages))
    return [str(folder)]


def _development_document(tmp_path: Path, folder: Path) -> list[str]:
    loaded = load_ground_truth(truth_path_for(folder))
    w.write_doc(truth_path_for(folder), dataclasses.replace(loaded, development_use=True))
    return [str(folder)]


def _acceptance_message(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    """What `python -m mangatl.bench.acceptance` says for `argv`, without its prefix."""
    status = acceptance.main(argv)
    captured = capsys.readouterr()
    assert status == 2, captured
    assert captured.out == ""
    assert captured.err.startswith(f"{_ACCEPTANCE_PROG}: "), captured.err
    assert captured.err.endswith("\n"), captured.err
    return captured.err[len(f"{_ACCEPTANCE_PROG}: ") : -1]


@pytest.mark.parametrize(
    "arrange",
    [
        _no_folder,
        _no_project,
        _schema_too_new,
        _no_document,
        _malformed_document,
        _stale_document,
        _development_document,
    ],
    ids=[
        "no-such-folder",
        "no-project",
        "schema-too-new",
        "no-document",
        "malformed-document",
        "invalid-document",
        "development-use",
    ],
)
def test_ac2_a_refusal_prints_one_prefixed_stderr_line_with_the_acceptance_message_and_no_stdout(
    tmp_path: Path,
    folder: Path,
    truth: GroundTruth,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[Path, Path], list[str]],
) -> None:
    argv = arrange(tmp_path, folder)
    message = _acceptance_message(argv, capsys)
    assert message and "\n" not in message, f"fixture: not a one-line refusal: {message!r}"

    status = main(argv)

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1, captured.err
    assert captured.err.startswith(f"{_PROG}: "), captured.err
    assert captured.err == f"{_PROG}: {message}\n"
    if arrange is _development_document:
        assert w.CHAPTER in captured.err
        assert "S5" not in captured.out + captured.err


def test_ac2_a_document_with_several_errors_is_refused_with_the_acceptance_commands_message(
    tmp_path: Path, folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both pages stale: `str(InvalidGroundTruth)` is two error lines joined by a
    newline, for the acceptance command too. Pinned to agree with it, prefix once."""
    loaded = load_ground_truth(truth_path_for(folder))
    w.write_doc(
        truth_path_for(folder),
        dataclasses.replace(
            loaded, pages=tuple(dataclasses.replace(p, sha256="0" * 64) for p in loaded.pages)
        ),
    )
    argv = [str(folder)]
    message = _acceptance_message(argv, capsys)

    status = main(argv)

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert captured.err == f"{_PROG}: {message}\n"


@pytest.mark.parametrize("measurement", ["measure_s2", "measure_cost"])
@pytest.mark.parametrize("refusal", [InvalidGroundTruth, BenchmarkChapterUsedInDevelopment])
def test_ac2_a_refusal_from_a_later_measurement_leaves_stdout_empty(
    folder: Path,
    truth: GroundTruth,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    measurement: str,
    refusal: type[Exception],
) -> None:
    """Contract block 2: every measurement completes before the first print, and a
    refusal from any of them is one stderr line - S1's lines are not left behind."""

    def refuse(*args: object, **kwargs: object) -> object:
        raise refusal("refused by the later measurement")

    monkeypatch.setattr(bench_main, measurement, refuse)

    status = main([str(folder)])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert captured.err == f"{_PROG}: refused by the later measurement\n"


# -- AC-3: the measurements are called, not re-implemented -----------------------


def _tree() -> ast.Module:
    return ast.parse(_MAIN_SOURCE.read_text("utf-8"))


def _imported(tree: ast.Module, module: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module and node.level == 0
        for alias in node.names
    }


def _calls_named(tree: ast.Module, name: str) -> int:
    """Calls to `name`, whether spelled bare or as an attribute of anything."""
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id == name) or (
            isinstance(func, ast.Attribute) and func.attr == name
        ):
            count += 1
    return count


@pytest.mark.parametrize(
    ("module", "names"),
    [
        ("mangatl.bench.acceptance", {"measure", "render"}),
        ("mangatl.bench.s2", {"measure_s2", "render"}),
        ("mangatl.bench.cost", {"measure_cost", "render"}),
    ],
)
def test_ac3_the_command_imports_each_measurement_and_its_render_from_its_own_module(
    module: str, names: set[str]
) -> None:
    imported = _imported(_tree(), module)
    assert names <= imported, f"{module}: imports {sorted(imported)}, needs {sorted(names)}"


@pytest.mark.parametrize("name", ["measure", "measure_s2", "measure_cost"])
def test_ac3_the_command_calls_each_measurement_exactly_once(name: str) -> None:
    assert _calls_named(_tree(), name) == 1


def test_ac3_the_command_defines_no_measurement_and_no_renderer_of_its_own() -> None:
    defined = sorted(
        node.name
        for node in ast.walk(_tree())
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith(("measure", "render"))
    )
    assert defined == []


def test_ac3_the_module_ends_raising_systemexit_of_main_under_the_main_guard() -> None:
    last = _tree().body[-1]
    assert isinstance(last, ast.If), ast.dump(last)
    test = last.test
    assert isinstance(test, ast.Compare), ast.dump(test)
    assert isinstance(test.left, ast.Name) and test.left.id == "__name__"
    assert len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
    assert len(test.comparators) == 1
    assert isinstance(test.comparators[0], ast.Constant)
    assert test.comparators[0].value == "__main__"
    assert last.orelse == []
    assert len(last.body) == 1
    raised = last.body[0]
    assert isinstance(raised, ast.Raise) and raised.cause is None, ast.dump(raised)
    exc = raised.exc
    assert isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name), ast.dump(raised)
    assert exc.func.id == "SystemExit" and exc.keywords == [] and len(exc.args) == 1
    inner = exc.args[0]
    assert isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name), ast.dump(inner)
    assert inner.func.id == "main" and inner.args == [] and inner.keywords == []


# -- AC-4: the console script and the `python -m` entry -------------------------


def test_ac4_pyproject_declares_the_mangatl_bench_console_script() -> None:
    scripts = tomllib.loads(_PYPROJECT.read_text("utf-8"))["project"]["scripts"]
    assert scripts.get("mangatl-bench") == "mangatl.bench.__main__:main", scripts


def _run_module(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setattr(sys, "argv", [_PROG, *argv])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # runpy: already imported
        with pytest.raises(SystemExit) as exited:
            runpy.run_module("mangatl.bench", run_name="__main__")
    return exited.value.code


def test_ac4_python_dash_m_mangatl_bench_exits_zero_with_the_report_when_it_measures(
    folder: Path,
    truth: GroundTruth,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parts = _expected(folder, truth)

    code = _run_module([str(folder)], monkeypatch)

    assert code == 0
    assert capsys.readouterr().out.splitlines() == parts.joined()


def test_ac4_python_dash_m_mangatl_bench_exits_two_when_it_cannot_measure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_module([str(tmp_path / "never-existed")], monkeypatch)

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err.startswith(f"{_PROG}: no such folder: "), captured.err


# -- Contract block 1: `render` is public, and is what each command prints -------


@pytest.mark.parametrize("module", [acceptance, s2, cost], ids=["acceptance", "s2", "cost"])
def test_block1_render_is_public_and_exported_by_each_measurement_module(module: object) -> None:
    assert callable(getattr(module, "render", None)), f"{module!r} has no public render"
    assert "render" in getattr(module, "__all__", ()), getattr(module, "__all__", None)


def test_block1_acceptance_render_is_exactly_what_its_own_command_prints_after_the_warnings(
    folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    parts = _expected(folder, truth)

    assert acceptance.main([str(folder)]) == 0

    assert capsys.readouterr().out.splitlines() == [*parts.warnings, *parts.acceptance]


def test_block1_s2_render_is_exactly_what_its_own_command_prints_after_the_warnings(
    folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    parts = _expected(folder, truth)

    assert s2.main([str(folder)]) == 0

    assert capsys.readouterr().out.splitlines() == [*parts.warnings, *parts.s2]


def test_block1_cost_render_is_exactly_what_its_own_command_prints(
    folder: Path, truth: GroundTruth, capsys: pytest.CaptureFixture[str]
) -> None:
    parts = _expected(folder, truth)

    assert cost.main([str(folder)]) == 0

    assert capsys.readouterr().out.splitlines() == parts.cost
