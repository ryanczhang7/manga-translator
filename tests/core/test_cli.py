"""`mangatl.cli`: pointing the app at a folder of scans, headlessly.

Covers AC-10 (the whole walk: create the project beside the folder, run every
page, write `<folder>_en/` with one identically named file per page in the same
order, one line of progress per page, exit `0`) and the two branches `## Contract`
PO-1 asks for as ordinary tests rather than as criteria - a second invocation
that reopens and resumes, and a folder with no page scans that exits non-zero
with a named message rather than a traceback.

Two conventions here are load-bearing rather than stylistic:

- **`main([...])` is called directly, in process.** A test that shells out to
  the `mangatl-run` console script is testing the installer: it passes when the
  entry point is registered and the code is broken, and fails when the code is
  right and the wheel was not reinstalled. `## Contract` PO-5.
- **`<folder>_en` is spelled out rather than derived from the implementation.**
  It is the path AC-10 promises the user; computing it with the same helper the
  writer uses would make the assertion agree with the code by construction.

A note on what these tests do NOT constrain: whether `main` refreshes the
project from the source folder on reopen, which stream the progress lines go to,
and what `main(None)` reads out of `sys.argv`. Those are the implementer's.

-- MT-036 -------------------------------------------------------------------

**Every end-to-end case in this file now passes `--models` and installs the
seam, and that is a consequence of C-3 rather than a convenience.** After MT-036
`main` resolves a models directory *before* `read_chapter` and asks the
composition root for the stage list, so a `main([folder])` on a machine with no
weights exits non-zero by design (PO-4, put to the user and accepted). A case
that wants to reach the walk has to say where the weights are, and a case that
wants to assert a *different* failure has to get past this one to reach it -
which is why the two "nothing to translate" tests below carry `--models` too,
and then assert that the composition root was never asked to build anything.

**The seam is `mangatl.cli.build_pipeline`, the module attribute** (C-3).
`cli.py` imports the name and calls it by that name, so replacing the attribute
replaces the composition root for the duration of one test. That is the whole
mechanism by which AC-3 is assertable with no weights, no GPU and no network,
and it is why `compose` is a module rather than four more lines of `main`.
`resolve_models_dir` is deliberately **not** stubbed: it is pure, C-2 has it
take the environment as an argument, and a test that stubbed it would stop
checking that `main` wires the two together at all.

**`MANGATL_MODELS` is removed from the environment for every test in this
file.** A developer with it set in their shell would otherwise see different
behaviour from CI on the one branch PO-4 cares most about.
"""

from __future__ import annotations

import ast
import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from mangatl.cli import main
from mangatl.domain.budget import Decision, Projection
from mangatl.domain.events import (
    BatchCollected,
    CallPriced,
    CorrectionsApplied,
    PageStarted,
    RunFinished,
)
from mangatl.domain.money import Usd
from mangatl.pipeline.stage import BudgetRefused, PageContext, Stage
from mangatl.store.project import PAGE_DONE, project_dir_for
from mangatl.translate.provider import Selection

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 11),
    ("p4.png", 23, 17),
)
_FILENAMES: list[str] = [name for name, _, _ in _SOURCE_PAGES]

#: `mangatl.compose.MODELS_ENV`, spelled out rather than imported. It is a
#: promise to a person typing it into a shell - the same reason `<folder>_en` is
#: spelled out above - and importing it would also drag `onnxruntime` into this
#: file for one string. `test_compose.py` is where the constant is pinned.
_MODELS_ENV = "MANGATL_MODELS"

#: MT-078 PO-1's three key variables and the choice variable, spelled out for
#: the same reason `_MODELS_ENV` is.
_PROVIDER_VARS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "MANGATL_PROVIDER")

#: The dummy Anthropic key every test starts with. Recognisable, so a test can
#: assert it never reaches the user's terminal (C-6).
_DEFAULT_KEY = "sk-SECRET-test-key-0123"


# -- the composition root, replaced at the seam C-3 names ----------------------


class _CountingStage:
    """A `Stage` that records the ordinals it ran and writes nothing.

    Behaviourally `PassThroughStage` with a notebook: `is_done` asks the store
    the same question - is this page's `status` the done marker - so the resume
    case below still resumes, and `run` is a no-op so the output folder is still
    a copy of the scans. The notebook is what AC-3 reads: "the stages it runs
    are the built list" is only assertable if the built list can say it ran.
    """

    def __init__(self, name: str = "counting") -> None:
        self.name = name
        self.ran: list[int] = []

    def run(self, ctx: PageContext) -> None:
        self.ran.append(ctx.page.ordinal)

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


class _CompositionRoot:
    """A stand-in for `mangatl.compose.build_pipeline`, installed at the seam.

    It records every models directory it was handed - so the flag, the
    environment variable and the precedence between them are all observable -
    and hands back one stage that the run can be seen to have used.

    **MT-044 C-14** gives it a second thing to record: `translate=`, as `main`
    passed it, or `None` where `main` passed nothing at all.

    **The `None` sentinel is load-bearing and is not a tidy default.** A double
    defaulting to `True` would record `True` for a `main` that never mentioned
    the flag, so the test pinning C-14's default would have passed against
    today's one-argument call - green on arrival, asserting nothing. `None` is
    a value `main` cannot produce, so "the default is True" and "`main` never
    said" are different observations here.

    The `*` is load-bearing too: C-14 makes `translate` keyword-only, so a
    `main` that passed it positionally is a `TypeError` here rather than a
    second models directory.
    """

    def __init__(self) -> None:
        self.models_dirs: list[Path] = []
        self.translate_flags: list[bool | None] = []
        #: MT-078 C-3: `selection=` as `main` passed it, or `None` where it passed none.
        self.selections: list[object] = []
        self.stage = _CountingStage()
        #: MT-105: the chapter step the built pipeline carries; `None` unless a
        #: test hands one in.
        self.prelude: object = None
        #: MT-130: the pipeline's two passes when a test hands them in. `None`
        #: keeps MT-105's one-pass pipeline of `self.stage`, built without the
        #: `after_prelude` keyword, so every older test here still runs in RED.
        self.reading: tuple[Stage, ...] | None = None
        self.after_prelude: tuple[Stage, ...] = ()
        #: MT-107: `context_mode=` as `main` passed it, or `None` where it passed
        #: none - the sentinel C-14's reasoning asks for (see above).
        self.context_modes: list[object] = []
        #: MT-140: the `build_consistency` stand-in the fixture installs beside
        #: this one, answering `None` until a test hands it a step.
        self.consistency = _ConsistencyRoot()

    def __call__(
        self,
        models_dir: Path,
        *,
        translate: bool | None = None,
        selection: object = None,
        context_mode: object = None,
    ) -> object:
        self.models_dirs.append(models_dir)
        self.translate_flags.append(translate)
        self.selections.append(selection)
        self.context_modes.append(context_mode)
        reading = self.reading if self.reading is not None else (self.stage,)
        return _pipeline(reading, self.prelude, self.after_prelude)


class _ConsistencyRoot:
    """MT-140: a stand-in for `mangatl.compose.build_consistency`, at the seam
    `mangatl.cli.build_consistency` (PO-1), the shape of `_CompositionRoot`.

    Records every selection it was asked with and, per ask, whatever
    `observe()` returns at that moment - the hook the order assertions use
    (did the project exist yet, had the stage list or the collector been
    built). Answers `None` (the real one's answer for `anthropic`) until a
    test calls `hand_out(...)`; from then on answers `self.step`, which records
    the `run_id` it was called with, appends `"consistency"` to `log` when a
    log is given, emits `emits` through the `emit` it was handed, in order,
    and then raises `raises` if one is set."""

    def __init__(self) -> None:
        self.selections: list[object] = []
        self.observed: list[object] = []
        self.observe: Callable[[], object] = lambda: None
        self.answers_a_step = False
        self.runs: list[int] = []
        self.emits: tuple[object, ...] = ()
        self.raises: BaseException | None = None
        self.log: list[object] | None = None
        #: the one step object handed out, so `is` can say "this step" - a
        #: fresh `self.step` bound method on each access would not be.
        self.handed: Callable[[object, int, Callable[[object], None]], None] = self.step

    def hand_out(
        self,
        *,
        emits: Sequence[object] = (),
        raises: BaseException | None = None,
        log: list[object] | None = None,
    ) -> None:
        self.answers_a_step = True
        self.emits = tuple(emits)
        self.raises = raises
        self.log = log

    def step(self, project: object, run_id: int, emit: Callable[[object], None]) -> None:
        self.runs.append(run_id)
        if self.log is not None:
            self.log.append("consistency")
        for event in self.emits:
            emit(event)
        if self.raises is not None:
            raise self.raises

    def __call__(self, selection: object) -> object:
        self.selections.append(selection)
        self.observed.append(self.observe())
        return self.handed if self.answers_a_step else None


def _pipeline(
    stages: tuple[Stage, ...], prelude: object = None, after_prelude: tuple[Stage, ...] = ()
) -> object:
    """`Pipeline(stages, prelude, after_prelude)`, what `build_pipeline` returns
    from MT-130 on.

    `after_prelude` is passed only when there is one: the keyword does not
    exist before MT-130's GREEN, and every one-pass test in this file must
    keep running in RED. Imported at call time for the same reason."""
    from mangatl.pipeline.prelude import Pipeline

    if after_prelude:
        return Pipeline(stages=stages, prelude=prelude, after_prelude=after_prelude)  # type: ignore[call-arg]
    return Pipeline(stages=stages, prelude=prelude)


def _bundle_at(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    """`bundled_models_dir()` answers `directory`, at both names `main` could
    reach it by: the name `mangatl.cli` binds (C-5) and the module
    `mangatl.app_paths` (C-3). `raising=False`: neither exists before MT-024's
    GREEN."""
    monkeypatch.setattr("mangatl.cli.bundled_models_dir", lambda: directory, raising=False)
    monkeypatch.setattr("mangatl.app_paths.bundled_models_dir", lambda: directory, raising=False)


@pytest.fixture(autouse=True)
def _no_ambient_models_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`MANGATL_MODELS` out of the environment for every test in this file -
    and, since MT-024, no bundled weights either: a developer who has run the
    fetch has a real `packaging/models/`, and `main` would find it (AC-9)."""
    monkeypatch.delenv(_MODELS_ENV, raising=False)
    _bundle_at(monkeypatch, tmp_path / "no bundled models here")


@pytest.fixture(autouse=True)
def _exactly_one_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """**MT-078 (C-2's caller list): every test starts with exactly
    `ANTHROPIC_API_KEY` set**, to a dummy, and the other two keys and
    `MANGATL_PROVIDER` deleted.

    Since MT-078 `main` selects a provider out of the real environment before
    it asks for the stages (C-3), so every translating run in this file -
    which, before this fixture, controlled no key variable at all - would pass
    on a developer's machine with one key exported and fail on a keyless CI
    runner, or the other way round with two. The AC-7 tests below set their
    own environment on top of this one.
    """
    for name in _PROVIDER_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", _DEFAULT_KEY)


#: MT-107's variable, spelled out for the reason `_MODELS_ENV` is.
_CONTEXT_VAR = "MANGATL_CONTEXT_MODE"


@pytest.fixture(autouse=True)
def _no_ambient_context_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """MT-107: `MANGATL_CONTEXT_MODE` out of the environment for every test, so
    a developer running MT-108's measurement in their shell sees CI's runs."""
    monkeypatch.delenv(_CONTEXT_VAR, raising=False)


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    """A directory that exists and holds nothing.

    `resolve_models_dir` does not stat the weight files (C-2) and
    `build_pipeline` is replaced, so an empty directory is exactly enough. It
    also keeps the tests honest about which of the two functions each one is
    exercising.
    """
    directory = tmp_path / "models"
    directory.mkdir()
    return directory


@pytest.fixture
def composition_root(monkeypatch: pytest.MonkeyPatch) -> _CompositionRoot:
    """`build_pipeline` replaced - and, from MT-140, `build_consistency` too.

    **MT-140: the consistency seam answers `None` by default.** The real
    `build_consistency` builds a `GeminiClient` and a live step for any Gemini
    selection, and several tests here select Gemini; a real step at the end
    of their run would make a network call. A test that wants a pass
    configures `root.consistency` (`_ConsistencyRoot`, below). `raising=False`:
    `mangatl.cli` has no `build_consistency` before MT-140's GREEN, and the
    older tests must keep running in RED."""
    root = _CompositionRoot()
    monkeypatch.setattr("mangatl.cli.build_pipeline", root)
    monkeypatch.setattr("mangatl.cli.build_consistency", root.consistency, raising=False)
    return root


# -- helpers -------------------------------------------------------------------


def _build_source(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    pages: Sequence[tuple[str, int, int]] = _SOURCE_PAGES,
) -> Path:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for filename, width, height in pages:
        (source_dir / filename).write_bytes(png_bytes(width, height))
    return source_dir


def _output_dir_for(source_dir: Path) -> Path:
    """`<source>_en`. AC-10's promise, spelled out rather than derived."""
    return source_dir.with_name(source_dir.name + "_en")


def _contents(root: Path) -> list[str]:
    return sorted(entry.relative_to(root).as_posix() for entry in root.rglob("*"))


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of file contents, or None for a directory."""
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _lines_naming(lines: Sequence[str], filename: str) -> list[str]:
    return [line for line in lines if filename in line]


# -- AC-10: the whole walk ----------------------------------------------------


def test_pointing_the_cli_at_a_folder_creates_the_project_beside_it(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    code = main([str(source_dir), "--models", str(models_dir)])

    assert code == 0
    project_dir = project_dir_for(source_dir)
    assert project_dir.parent == source_dir.parent, "the project is a sibling, not a child"
    assert (project_dir / "project.db").is_file()


def test_pointing_the_cli_at_a_folder_writes_the_sibling_output_folder(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)
    output_dir = _output_dir_for(source_dir)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert output_dir.parent == source_dir.parent, "the output folder is a sibling, not a child"
    assert _contents(output_dir) == sorted(_FILENAMES)
    mismatched = [
        name
        for name in _FILENAMES
        if _sha256_of(output_dir / name) != _sha256_of(source_dir / name)
    ]
    assert mismatched == [], f"output bytes differ from the input scan for: {mismatched}"


def test_the_cli_ran_every_page_and_recorded_a_finished_run(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    source_dir = _build_source(tmp_path, png_bytes)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    db_path = project_dir_for(source_dir) / "project.db"
    assert [row[0] for row in _raw(db_path, "SELECT outcome FROM run ORDER BY id")] == ["finished"]
    assert len(_raw(db_path, "SELECT ordinal FROM page")) == len(_SOURCE_PAGES)


def test_the_cli_emits_exactly_one_line_of_progress_per_page(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    # "one line of progress output per page" (AC-10). Asserted by counting the
    # lines that name each page's own filename, which pins the *shape* of the
    # output - one line, one page, identified by something the user recognises -
    # without pinning a format nobody has designed yet. A run that printed one
    # summary line, or one line per stage, fails here.
    source_dir = _build_source(tmp_path, png_bytes)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    lines = _lines(capsys.readouterr().out)
    counted = {name: len(_lines_naming(lines, name)) for name in _FILENAMES}
    assert counted == dict.fromkeys(_FILENAMES, 1)


def test_the_cli_never_writes_inside_the_folder_of_scans(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    # AC-8 end to end. The project and the output folder are both siblings, so
    # after a whole CLI run the user's scans must be byte-for-byte what they
    # were, with no directory added underneath them either.
    source_dir = _build_source(tmp_path, png_bytes)
    before = _snapshot(source_dir)
    assert sum(1 for value in before.values() if value is not None) == len(_SOURCE_PAGES)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert _snapshot(source_dir) == before


# -- PO-1's first extra branch: a second invocation reopens and resumes --------


def test_a_second_invocation_reopens_the_project_rather_than_recreating_it(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    # `create_project` refuses an existing `project.db` with `ProjectExists`
    # rather than clobbering hours of edits (MT-005), so a CLI that always
    # creates cannot even return here. Two `run` rows in one project file is
    # what "reopened and ran again" looks like from outside; one row would mean
    # the file was rebuilt from scratch and the first run's work thrown away.
    source_dir = _build_source(tmp_path, png_bytes)
    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    db_path = project_dir_for(source_dir) / "project.db"
    assert [row[0] for row in _raw(db_path, "SELECT outcome FROM run ORDER BY id")] == [
        "finished",
        "finished",
    ]
    assert len(_raw(db_path, "SELECT id FROM chapter")) == 1
    # Two invocations, two runs, two builds: the composition root is asked once
    # per `main`, not once per process and not once per page.
    assert composition_root.models_dirs == [models_dir, models_dir]


def test_a_second_invocation_skips_the_pages_the_first_one_finished(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    # EPIC-02's done-when, through the entry point: starting again resumes
    # rather than restarting. Progress is still one line per page - a skipped
    # page is progress the user wants to see - and the output folder still holds
    # exactly the chapter.
    source_dir = _build_source(tmp_path, png_bytes)
    assert main([str(source_dir), "--models", str(models_dir)]) == 0
    capsys.readouterr()

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    lines = _lines(capsys.readouterr().out)
    counted = {name: len(_lines_naming(lines, name)) for name in _FILENAMES}
    assert counted == dict.fromkeys(_FILENAMES, 1)
    assert _contents(_output_dir_for(source_dir)) == sorted(_FILENAMES)


# -- PO-1's second extra branch: nothing to do, said plainly ------------------


def test_a_folder_with_no_page_scans_exits_non_zero_with_a_named_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    (source_dir / "notes.txt").write_text("not a scan\n", encoding="utf-8")

    code = main([str(source_dir), "--models", str(models_dir)])

    assert code != 0, "a folder with nothing to translate reported success"
    captured = capsys.readouterr()
    message = captured.err + captured.out
    assert "no pages" in message.lower(), f"the message does not say what went wrong: {message!r}"
    assert source_dir.name in message, "the message does not say which folder"
    assert "Traceback" not in message, "the CLI let a traceback reach the user"
    assert not project_dir_for(source_dir).exists(), "a project was created for an empty chapter"
    assert not _output_dir_for(source_dir).exists()
    assert composition_root.models_dirs == [], (
        "the composition root was asked to load the weights for a chapter with"
        " nothing to translate; on a real machine that is a second or more of ONNX"
        " session construction before a message the CLI could have printed first"
    )


def test_a_folder_that_is_not_there_exits_non_zero_with_a_named_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    # The likeliest user error of all: a typo in a path. It must read as a
    # message, not as an unhandled `FileNotFoundError` from `Path.iterdir`.
    missing = tmp_path / "not-a-folder"

    code = main([str(missing), "--models", str(models_dir)])

    assert code != 0, "a folder that does not exist reported success"
    captured = capsys.readouterr()
    message = captured.err + captured.out
    assert missing.name in message, "the message does not say which folder"
    assert "Traceback" not in message, "the CLI let a traceback reach the user"
    assert composition_root.models_dirs == []


# -- MT-036 AC-3: the run walks the stages the composition root built ----------


def test_the_cli_runs_the_stages_the_composition_root_built(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-3.** The stage list `mangatl-run` walks is `build_pipeline`'s.

    Asserted by the stages themselves rather than by inspecting an argument:
    the stage the composition root handed back has to have been run on every
    page of the chapter. A `main` that still built its own `PassThroughStage`
    would leave this notebook empty while every other test in this file passed,
    which is exactly the gap MT-035 PO-1 predicted and this story closes.
    """
    source_dir = _build_source(tmp_path, png_bytes)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert composition_root.models_dirs == [models_dir], (
        "the composition root was not asked for the stage list exactly once, with"
        f" the resolved models directory: {composition_root.models_dirs}"
    )
    assert composition_root.stage.ran == list(range(len(_SOURCE_PAGES))), (
        "the stages the composition root built were not the stages the run walked;"
        f" the built stage ran on {composition_root.stage.ran}"
    )


class _LoggingStage:
    """MT-130: a `Stage` that appends `(name, ordinal)` to a shared log.

    `is_done` is `False` for the reading stages (a fresh chapter) and the
    store's done marker for the translating one, so the runner's own
    bookkeeping is what marks a page complete."""

    def __init__(self, log: list[object], name: str, *, final: bool = False) -> None:
        self.log = log
        self.name = name
        self.final = final

    def run(self, ctx: PageContext) -> None:
        self.log.append((self.name, ctx.page.ordinal))

    def is_done(self, ctx: PageContext) -> bool:
        return self.final and ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


_THREE_PAGES = _SOURCE_PAGES[:3]


def _two_passes(composition_root: _CompositionRoot) -> list[object]:
    """Install MT-130's two-pass pipeline at the seam: `(detect, ocr)` reading,
    a recording prelude, `(translate,)` translating. Returns the shared log."""
    log: list[object] = []

    def prelude(project: object, run_id: int, emit: object) -> None:
        log.append("prelude")

    composition_root.reading = (_LoggingStage(log, "detect"), _LoggingStage(log, "ocr"))
    composition_root.prelude = prelude
    composition_root.after_prelude = (_LoggingStage(log, "translate", final=True),)
    return log


def test_the_cli_reads_every_page_then_runs_the_prelude_then_translates_page_by_page(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**MT-130 AC-14** (supersedes MT-105's "prelude before the first page",
    PO-5): `mangatl-run` hands `run_chapter` `pipeline.stages`,
    `prelude=pipeline.prelude` and `after_prelude=pipeline.after_prelude`, so
    the run's order is AC-2's."""
    source_dir = _build_source(tmp_path, png_bytes, _THREE_PAGES)
    log = _two_passes(composition_root)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert log == [
        ("detect", 0),
        ("ocr", 0),
        ("detect", 1),
        ("ocr", 1),
        ("detect", 2),
        ("ocr", 2),
        "prelude",
        ("translate", 0),
        ("translate", 1),
        ("translate", 2),
    ], f"the CLI's run went {log}"


def test_the_cli_announces_each_pass_once_and_prints_each_page_once_per_pass(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**MT-130 AC-14**, stdout: `Reading 3 pages` before the first page line,
    `Translating 3 pages` before the translating pass's first page line
    (PO-4's wording, the user's), and the page lines as today, once per pass.
    The bake's own summary line follows and is MT-021's, not pinned here."""
    source_dir = _build_source(tmp_path, png_bytes, _THREE_PAGES)
    _two_passes(composition_root)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    lines = _lines(capsys.readouterr().out)
    assert lines[:8] == [
        "Reading 3 pages",
        "[1/3] p1.png",
        "[2/3] p2.png",
        "[3/3] p3.png",
        "Translating 3 pages",
        "[1/3] p1.png",
        "[2/3] p2.png",
        "[3/3] p3.png",
    ], f"stdout opened {lines[:8]}"
    assert lines.count("Reading 3 pages") == 1
    assert lines.count("Translating 3 pages") == 1
    assert len(lines) == 9, f"stdout had {len(lines)} lines after the passes: {lines[8:]}"


def test_a_one_pass_cli_run_prints_no_pass_line(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """MT-130 AC-5 at the entry point: a pipeline with no `after_prelude`
    (`--no-translate`) runs one pass, and stdout has no pass line at all."""
    source_dir = _build_source(tmp_path, png_bytes, _THREE_PAGES)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    lines = _lines(capsys.readouterr().out)
    assert lines[:3] == ["[1/3] p1.png", "[2/3] p2.png", "[3/3] p3.png"], (
        f"stdout opened {lines[:3]}"
    )
    assert not [line for line in lines if line.startswith(("Reading", "Translating"))]


def test_the_cli_no_longer_reaches_for_the_pass_through_stage() -> None:
    """**AC-3's second half**, and the half a behavioural test cannot reach.

    `PassThroughStage` is the identity element the runner's own tests are built
    on and it stays in `pipeline/stage.py` (C-3) - so "not `PassThroughStage`"
    cannot be asserted by its absence from the project. It is asserted where the
    decision lives: the entry point does not import it and does not name it.

    The module's source is read rather than its namespace, so the name cannot
    survive as a local, a default argument or a fallback inside a branch no test
    happens to take.
    """
    import mangatl.cli as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    mentions = [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == "PassThroughStage")
        or (isinstance(node, ast.Attribute) and node.attr == "PassThroughStage")
        or (isinstance(node, ast.alias) and node.name == "PassThroughStage")
    ]
    assert mentions == [], (
        "mangatl/cli.py still names PassThroughStage. After MT-036 the entry point"
        " asks the composition root for its stages (C-3); the identity element"
        " belongs to the runner's tests, not to the CLI."
    )


def test_the_cli_takes_the_models_directory_from_the_environment_when_no_flag_is_given(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PO-4's second branch, through the entry point.

    `resolve_models_dir` takes the environment as an argument (C-2) and every
    branch of it is tested in `test_compose.py` without touching `os.environ`.
    This test is the other half and cannot be replaced by those: it is what
    pins that `main` passes the *real* environment in, rather than an empty
    mapping that would make `$MANGATL_MODELS` dead configuration.
    """
    source_dir = _build_source(tmp_path, png_bytes)
    monkeypatch.setenv(_MODELS_ENV, str(models_dir))

    assert main([str(source_dir)]) == 0

    assert composition_root.models_dirs == [models_dir]


def test_the_models_flag_wins_over_the_environment_variable(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PO-4's resolution order, end to end. Both are valid directories, so
    precedence is the only thing that can decide the answer."""
    source_dir = _build_source(tmp_path, png_bytes)
    from_env = tmp_path / "models-from-the-environment"
    from_env.mkdir()
    monkeypatch.setenv(_MODELS_ENV, str(from_env))

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert composition_root.models_dirs == [models_dir]


def test_with_no_flag_and_no_variable_the_cli_runs_on_the_bundled_weights(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MT-024 AC-9: *"`mangatl-run` passes the bundled directory"* (C-5:
    `resolve_models_dir(arguments.models, os.environ, bundled_models_dir())`).
    RED: `main` passes two arguments and the run fails on PO-4's sentence."""
    source_dir = _build_source(tmp_path, png_bytes)
    bundled = tmp_path / "bundled-models"
    bundled.mkdir()
    _bundle_at(monkeypatch, bundled)

    assert main([str(source_dir)]) == 0

    assert composition_root.models_dirs == [bundled]


def test_a_run_with_no_models_directory_fails_before_it_creates_anything(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    composition_root: _CompositionRoot,
) -> None:
    """PO-4's last branch, and C-3's ordering clause.

    *"No silent default"*: a default pointing at a missing directory produces an
    onnxruntime stack trace instead of a sentence. And the resolution happens
    **before** `read_chapter`, so the failure costs the user nothing - no
    project directory beside their scans to wonder about and delete, no output
    folder. The user was told, and accepted, that `mangatl-run` now fails here
    where MT-006 left it succeeding.
    """
    source_dir = _build_source(tmp_path, png_bytes)

    code = main([str(source_dir)])

    assert code != 0, "a run with nowhere to load the weights from reported success"
    captured = capsys.readouterr()
    message = captured.err + captured.out
    assert _MODELS_ENV in message, (
        f"the message does not name {_MODELS_ENV}, so a user who has not set it is"
        f" not told what to set: {message!r}"
    )
    assert "Traceback" not in message, "the CLI let a traceback reach the user"
    assert not project_dir_for(source_dir).exists(), (
        "a project was created beside the scans before the run found out it had no"
        " weights to run with (C-3: resolve the models directory before read_chapter)"
    )
    assert not _output_dir_for(source_dir).exists()
    assert composition_root.models_dirs == []


# -- MT-044 AC-6: `--no-translate`, the flag and its default -------------------


def test_the_no_translate_flag_asks_the_composition_root_not_to_translate(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-6**, the argparse half: `--no-translate` reaches `build_pipeline`
    as `translate=False`, and the run still walks the whole chapter.

    Asserted at the seam rather than by inspecting the parser, because what
    AC-6 is about is not that a flag exists but that it *arrives*: a `main` that
    declared `--no-translate` and then called `build_pipeline(models_dir)`
    anyway would pass a help-text assertion, pass every other test in this file,
    and translate five pages with a key nobody has (C-14).

    **What this test cannot see** is the stage list itself: the composition root
    is replaced here, so `translate=False` is observed as an argument and not as
    a two-stage tuple. `test_compose.py` is where the flag's *effect* is pinned,
    and the client counter with it.

    The tail of the test is AC-6's "the run completes" at the level this file
    reaches: exit 0, every page walked, `<folder>_en` written. The whole-chapter
    form of it, on a machine with real weights and no API key, is
    `tests/integration/test_pipeline_chapter.py`'s.
    """
    source_dir = _build_source(tmp_path, png_bytes)

    code = main([str(source_dir), "--models", str(models_dir), "--no-translate"])

    assert code == 0, "mangatl-run --no-translate did not complete the chapter"
    assert composition_root.translate_flags == [False], (
        "the composition root was asked for"
        f" translate={composition_root.translate_flags}; --no-translate must"
        " reach it as translate=False (C-14), and [None] means main never"
        " mentioned it at all"
    )
    assert composition_root.models_dirs == [models_dir]
    assert composition_root.stage.ran == list(range(len(_SOURCE_PAGES)))
    assert _contents(_output_dir_for(source_dir)) == sorted(_FILENAMES)


def test_a_run_without_the_flag_asks_for_a_translating_pipeline_and_says_so(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """C-14's default, through the entry point: **absent flag means translate**.

    `[True]` and not `[None]`: `main` passes `translate=not
    arguments.no_translate` on every call, so the builder is told what to do
    rather than left to its own default. The distinction is the whole reason
    `_CompositionRoot` records a `None` sentinel - with a double that defaulted
    to `True`, this assertion would have been satisfied by today's
    `build_pipeline(models_dir)` and would have asserted nothing.
    """
    source_dir = _build_source(tmp_path, png_bytes)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert composition_root.translate_flags == [True], (
        "a run with no --no-translate asked the composition root for"
        f" translate={composition_root.translate_flags}; [None] means main did"
        " not pass the argument at all and the pipeline's own default is the"
        " only thing deciding whether the tool spends money"
    )


def test_the_flag_is_one_the_parser_knows_about_and_tells_the_user_about(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--no-translate` is a declared argument, not a string `main` sniffs out.

    A user who cannot find the flag cannot use it, and argparse's own help is
    where they will look. This also pins that the flag is *declared*: a `main`
    that scanned `argv` itself would leave it out of `--help` and would accept
    typos silently instead of refusing them.

    The help text's wording is deliberately **not** pinned - C-14 suggests one
    and GREEN may write a better one.
    """
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    assert "--no-translate" in capsys.readouterr().out, (
        "mangatl-run --help does not mention --no-translate"
    )


def test_the_provider_flag_is_one_the_parser_knows_about_and_tells_the_user_about(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """MT-078 C-3: `--provider` is declared, so it is in `--help` and a typo
    in it is refused by argparse rather than sniffed out of `argv`."""
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    assert "--provider" in capsys.readouterr().out, "mangatl-run --help does not mention --provider"


# -- MT-078 AC-4/AC-7: choosing a provider, and refusing before anything runs --
#
# `main` selects after resolving the models directory and before `is_dir`,
# `read_chapter` and `create_project` (C-3): `select_provider(arguments.provider
# or os.environ.get("MANGATL_PROVIDER"), os.environ)`, unless `--no-translate`.
# A refusal is `_fail(str(error))`: exit non-zero, ONE line on stderr - the
# `mangatl-run: ` prefix every `_fail` line carries, then the exception's
# message, pinned exactly - nothing on stdout, no traceback, the composition
# root never asked (that is "before the weights are loaded") and no project
# beside the scans.
#
# The messages are spelled out, not imported: importing
# `mangatl.translate.provider` at the top of this file would take every test in
# it dark in RED, and the words are a promise to the user (C-1, pinned in
# `test_translate_provider.py` and repeated here so the two cannot drift
# silently - a change to one fails the other).

_NO_KEY = (
    "no API key is set: set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY,"
    " or run with --no-translate"
)
_AMBIGUOUS_ANTHROPIC_OPENAI = (
    "API keys are set for more than one provider (anthropic, openai);"
    " choose one with --provider or MANGATL_PROVIDER"
)
_OTHER_KEYS = {"GEMINI_API_KEY": "sk-SECRET-gem-4567", "OPENAI_API_KEY": "sk-SECRET-oai-89ab"}


def _refused(
    capsys: pytest.CaptureFixture[str],
    code: int,
    source_dir: Path,
    composition_root: _CompositionRoot,
) -> list[str]:
    """The common half of every AC-7 refusal; returns stderr's lines."""
    captured = capsys.readouterr()
    assert code != 0, "a run that could not select a provider reported success"
    assert "Traceback" not in captured.err + captured.out, "a traceback reached the user"
    assert captured.out == "", f"the refusal printed to stdout as well: {captured.out!r}"
    secrets = [_DEFAULT_KEY, *_OTHER_KEYS.values()]
    leaked = [s for s in secrets if s in captured.err + captured.out]
    assert leaked == [], f"a key value reached the terminal (C-6): {leaked}"
    assert composition_root.models_dirs == [], (
        "the composition root was asked to load the weights before the provider"
        " was settled (AC-7: before the weights are loaded)"
    )
    assert not project_dir_for(source_dir).exists(), (
        "a project was created beside the scans before the run found out it had no"
        " provider (AC-7: before any project directory is created)"
    )
    assert not _output_dir_for(source_dir).exists()
    return captured.err.splitlines()


def test_with_no_key_the_run_refuses_in_one_line_before_anything_is_built(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-7, no key** (AC-3's message). Notes PO-4: MT-044 left this run
    loading the weights and aborting on the first page; now it is one line."""
    source_dir = _build_source(tmp_path, png_bytes)
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    code = main([str(source_dir), "--models", str(models_dir)])

    lines = _refused(capsys, code, source_dir, composition_root)
    assert lines == [f"mangatl-run: {_NO_KEY}"]


def test_with_two_keys_and_no_choice_the_run_refuses_to_guess(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-7, several keys and no choice** (AC-2's message). The keys are
    recognisable, and `_refused` checks neither reached the terminal (C-6)."""
    source_dir = _build_source(tmp_path, png_bytes)
    monkeypatch.setenv("OPENAI_API_KEY", _OTHER_KEYS["OPENAI_API_KEY"])

    code = main([str(source_dir), "--models", str(models_dir)])

    lines = _refused(capsys, code, source_dir, composition_root)
    assert lines == [f"mangatl-run: {_AMBIGUOUS_ANTHROPIC_OPENAI}"]


@pytest.mark.parametrize("how", ["flag", "variable"])
def test_a_chosen_provider_whose_key_is_missing_is_refused_by_name(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
    how: str,
) -> None:
    """**AC-7, a missing key for the chosen provider** (AC-4's refusal), by
    either route to the choice. Only Anthropic's key is set: falling back to it
    is the guess PO-1 forbids."""
    source_dir = _build_source(tmp_path, png_bytes)
    arguments = [str(source_dir), "--models", str(models_dir)]
    if how == "flag":
        arguments += ["--provider", "openai"]
    else:
        monkeypatch.setenv("MANGATL_PROVIDER", "openai")

    code = main(arguments)

    lines = _refused(capsys, code, source_dir, composition_root)
    assert lines == ["mangatl-run: provider openai was chosen but OPENAI_API_KEY is not set"]


def test_an_unknown_provider_in_the_variable_is_refused_with_the_valid_names(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-7 / AC-5 through `MANGATL_PROVIDER`**, the path argparse cannot
    guard (C-3): `UnknownProvider`'s message, one line."""
    source_dir = _build_source(tmp_path, png_bytes)
    monkeypatch.setenv("MANGATL_PROVIDER", "Anthropic")

    code = main([str(source_dir), "--models", str(models_dir)])

    lines = _refused(capsys, code, source_dir, composition_root)
    assert lines == [
        "mangatl-run: unknown provider 'Anthropic': choose one of anthropic, gemini, openai"
    ]


def test_an_unknown_provider_flag_is_argparses_usage_error(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-7 / AC-5 at the flag** (C-3: `choices=PROVIDERS`). argparse's own
    refusal is the accepted form: exit 2, the bad value and "invalid choice"
    named, and still nothing built and nothing created."""
    source_dir = _build_source(tmp_path, png_bytes)

    with pytest.raises(SystemExit) as raised:
        main([str(source_dir), "--models", str(models_dir), "--provider", "bogus"])

    assert raised.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err and "'bogus'" in err, f"argparse said: {err!r}"
    assert composition_root.models_dirs == []
    assert not project_dir_for(source_dir).exists()


def test_with_no_translate_no_selection_is_attempted_even_with_no_key(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-7's last clause**: `--no-translate` attempts no selection, so none
    of the refusals can occur - here with no key at all AND a choice variable
    that is not a provider, which would refuse two different ways.

    **Green on arrival** (today's `main` selects nothing): it is a guard on
    GREEN's ordering, not a red test. Its probe needs GREEN's code - see the
    story's handoff.
    """
    source_dir = _build_source(tmp_path, png_bytes)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("MANGATL_PROVIDER", "claude")

    code = main([str(source_dir), "--models", str(models_dir), "--no-translate"])

    assert code == 0, f"--no-translate with no key failed: {capsys.readouterr().err!r}"
    assert composition_root.translate_flags == [False]
    assert composition_root.stage.ran == list(range(len(_SOURCE_PAGES)))


def _pair(selection: object) -> tuple[object, object]:
    """`(provider, api_key)` of what `main` passed, or the bare value when it
    passed something that is not a selection (`None`: it passed nothing)."""
    return (getattr(selection, "provider", selection), getattr(selection, "api_key", None))


def test_the_selection_main_makes_is_handed_to_the_composition_root(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """C-3: `selection=selection` reaches `build_pipeline`. With the fixture's
    one Anthropic key, that is Anthropic with that key - so the composition
    root does not select a second time from an environment `main` already
    read."""
    source_dir = _build_source(tmp_path, png_bytes)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert [_pair(s) for s in composition_root.selections] == [("anthropic", _DEFAULT_KEY)], (
        f"main handed the composition root {composition_root.selections!r}; C-3 passes"
        " the Selection it made"
    )
    from mangatl.translate.provider import Selection

    assert composition_root.selections == [Selection("anthropic", _DEFAULT_KEY)]


def test_the_choice_variable_picks_among_several_keys(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """AC-4 through the variable: all three keys set, `MANGATL_PROVIDER=gemini`,
    and the selection is gemini with gemini's key. (The composition root is
    replaced, so gemini's missing adapter is not reached here.)"""
    source_dir = _build_source(tmp_path, png_bytes)
    for name, value in _OTHER_KEYS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MANGATL_PROVIDER", "gemini")

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert [_pair(s) for s in composition_root.selections] == [
        ("gemini", _OTHER_KEYS["GEMINI_API_KEY"])
    ]


def test_the_provider_flag_beats_the_choice_variable(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-4: "the flag winning when both are given"** - which C-1 makes the
    caller's job, so it is pinned here, at the caller. `--provider openai`
    with `MANGATL_PROVIDER=gemini` and every key set: openai, with openai's
    key. A `main` that let the variable win hands over gemini."""
    source_dir = _build_source(tmp_path, png_bytes)
    for name, value in _OTHER_KEYS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MANGATL_PROVIDER", "gemini")

    code = main([str(source_dir), "--models", str(models_dir), "--provider", "openai"])

    assert code == 0
    assert [_pair(s) for s in composition_root.selections] == [
        ("openai", _OTHER_KEYS["OPENAI_API_KEY"])
    ], f"the flag did not beat the variable: {composition_root.selections!r}"


# -- MT-078 AC-7 as amended by A-2: a provider with no translator yet ----------
#
# With only a Gemini or only an OpenAI key, selection succeeds and it is
# `compose.build_pipeline` that refuses, with `ProviderUnavailable` (C-2).
# Amended C-3 calls `build_pipeline` after `read_chapter` and BEFORE
# `create_project`, inside `except ProviderError -> _fail(str(error))`.
#
# **These run through the REAL `mangatl.compose.build_pipeline`**, not the
# `composition_root` double, with its four loaders, `available_providers` and
# `Anthropic` replaced at `mangatl.compose`'s own names. A double taught to
# raise `ProviderUnavailable` for a non-anthropic selection would restate
# compose's dispatch inside this file, so the test would pass against the
# double's idea of compose rather than compose itself. With the real function
# the criterion is observed end to end: compose refuses, main catches the
# refusal, and the recorders show that no weight and no client were reached.
# The loaders record and then raise, so a build that went past the refusal
# fails loudly here instead of carrying fake sessions on.


class _LoaderReached(Exception):
    """A loader was called: the refusal did not precede the weights."""


class _WeightsRecorder:
    """`mangatl.compose`'s loaders and client, replaced, recording each reach."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.reached: list[str] = []
        for name in ("load_detector", "load_ocr", "load_vocab", "load_inpainter", "Anthropic"):
            monkeypatch.setattr(f"mangatl.compose.{name}", self._recorder(name))
        monkeypatch.setattr("mangatl.compose.available_providers", lambda: ["CPUExecutionProvider"])

    def _recorder(self, name: str) -> Callable[..., object]:
        def record(*args: object, **kwargs: object) -> object:
            self.reached.append(name)
            raise _LoaderReached(name)

        return record


#: MT-080: the two gemini cases became openai ones. Gemini has an adapter from
#: MT-080 on, so through the real `build_pipeline` it binds instead of refusing;
#: openai is the provider still without one (MT-081). The three routes to a
#: selection - one key alone, the flag, and the variable choosing between two
#: keys - are kept, each now observed on openai.
_UNAVAILABLE_CASES = {
    "openai-key-only": ({"OPENAI_API_KEY": "sk-SECRET-oai-89ab"}, [], "openai"),
    "openai-key-only-with-flag": (
        {"OPENAI_API_KEY": "sk-SECRET-oai-89ab"},
        ["--provider", "openai"],
        "openai",
    ),
    "two-keys-variable-chooses-openai": (
        {"ANTHROPIC_API_KEY": _DEFAULT_KEY, "OPENAI_API_KEY": "sk-SECRET-oai-89ab"},
        [],
        "openai",
    ),
}


@pytest.mark.parametrize("case", list(_UNAVAILABLE_CASES))
def test_a_provider_with_no_translator_yet_is_refused_in_one_line_and_leaves_nothing(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    case: str,
) -> None:
    """**AC-7 as amended by A-2.** The orchestrator reproduced this under PO-9:
    `ProviderUnavailable` raised by `build_pipeline` after `create_project`
    reached the user as a traceback and left a `.mtproj` behind. Assertions:
    a non-zero exit, exactly one stderr line, empty stdout, no traceback, no key
    printed, no project, no output folder, and no loader or client reached."""
    env, extra_arguments, provider = _UNAVAILABLE_CASES[case]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if case == "two-keys-variable-chooses-openai":
        monkeypatch.setenv("MANGATL_PROVIDER", "openai")
    weights = _WeightsRecorder(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes)

    escaped: BaseException | None = None
    code = None
    try:
        code = main([str(source_dir), "--models", str(models_dir), *extra_arguments])
    except Exception as error:  # the defect A-2 exists to remove
        escaped = error

    left_behind = project_dir_for(source_dir).exists()
    assert escaped is None, (
        f"main let {type(escaped).__name__}: {escaped} escape - a traceback for the"
        f" user (AC-7, A-2); project left beside the scans: {left_behind}"
    )
    captured = capsys.readouterr()
    assert code is not None and code != 0, f"the run reported {code!r}"
    assert captured.err.splitlines() == [
        f"mangatl-run: translation with {provider} is not available yet"
    ], f"stderr was {captured.err!r}"
    assert captured.out == "", f"the refusal printed to stdout as well: {captured.out!r}"
    assert "Traceback" not in captured.err
    leaked = [v for v in env.values() if v in captured.err + captured.out]
    assert leaked == [], f"a key value reached the terminal (C-6): {leaked}"
    assert not left_behind, (
        "a project was created beside the scans before the run found out its"
        " provider has no translator (AC-7: before any project directory is created)"
    )
    assert not _output_dir_for(source_dir).exists()
    assert weights.reached == [], (
        f"{weights.reached} was reached before the refusal (AC-7: before the weights are loaded)"
    )


def test_the_composition_root_is_asked_before_the_project_is_created(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Amended C-3's order for a run that proceeds: `read_chapter`, then
    `build_pipeline`, then `create_project`. The double records whether the
    project existed when it was asked. Before A-2 it did, because `main`
    created the project first."""
    source_dir = _build_source(tmp_path, png_bytes)
    root = _CompositionRoot()
    seen: list[bool] = []

    def build(models_dir: Path, **keywords: object) -> object:
        seen.append(project_dir_for(source_dir).exists())
        return root(models_dir, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr("mangatl.cli.build_pipeline", build)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert seen == [False], (
        f"build_pipeline saw the project existing: {seen}; amended C-3 (A-2) builds"
        " before it creates, so a refusal leaves nothing behind"
    )
    assert root.stage.ran == list(range(len(_SOURCE_PAGES))), "the run did not walk the chapter"


# -- MT-107 AC-5: choosing the context mode -------------------------------------------
#
# `--context`, else `MANGATL_CONTEXT_MODE`, else `rolling`; the flag beats the
# variable as `--provider` does. `main` passes `context_mode=` to the
# composition root on every translating call - the recorder's `None` means it
# passed nothing, which is not "rolling" (C-14's reasoning, applied here).
#
# RED: `main` has no `--context` and reads no variable, so the flag cases are
# argparse's exit 2 and the variable cases record `None`.


def test_the_context_flag_selects_neighbours(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-5**: `mangatl-run FOLDER --context neighbours` reaches
    `build_pipeline(..., context_mode="neighbours")`."""
    source_dir = _build_source(tmp_path, png_bytes)

    code = main([str(source_dir), "--models", str(models_dir), "--context", "neighbours"])

    assert code == 0
    assert composition_root.context_modes == ["neighbours"]


def test_the_context_variable_selects_neighbours(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-5**: `MANGATL_CONTEXT_MODE=neighbours` with no flag selects it."""
    source_dir = _build_source(tmp_path, png_bytes)
    monkeypatch.setenv(_CONTEXT_VAR, "neighbours")

    code = main([str(source_dir), "--models", str(models_dir)])

    assert code == 0
    assert composition_root.context_modes == ["neighbours"]


@pytest.mark.parametrize(
    ("flag", "variable"), [("rolling", "neighbours"), ("neighbours", "rolling")]
)
def test_the_context_flag_beats_the_variable(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
    flag: str,
    variable: str,
) -> None:
    """**AC-5**: "flag beats variable, as `--provider` does", both ways round -
    a `main` that let the variable win hands over the other mode."""
    source_dir = _build_source(tmp_path, png_bytes)
    monkeypatch.setenv(_CONTEXT_VAR, variable)

    code = main([str(source_dir), "--models", str(models_dir), "--context", flag])

    assert code == 0
    assert composition_root.context_modes == [flag], (
        f"--context {flag} with {_CONTEXT_VAR}={variable} gave {composition_root.context_modes}"
    )


@pytest.mark.parametrize("variable", [None, ""], ids=["unset", "empty"])
def test_with_no_flag_and_no_variable_the_context_is_rolling(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
    variable: str | None,
) -> None:
    """**AC-5**: "unset means `rolling`" - and an empty variable is unset -
    said out loud to the composition root, not left to its default."""
    source_dir = _build_source(tmp_path, png_bytes)
    if variable is not None:
        monkeypatch.setenv(_CONTEXT_VAR, variable)

    code = main([str(source_dir), "--models", str(models_dir)])

    assert code == 0
    assert composition_root.context_modes == ["rolling"]


@pytest.mark.parametrize("keyed", [True, False], ids=["with-a-key", "with-no-key"])
def test_an_unknown_context_mode_in_the_variable_is_refused_in_one_line_before_anything(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    models_dir: Path,
    composition_root: _CompositionRoot,
    keyed: bool,
) -> None:
    """**AC-5**: any other value is refused in one line naming the two modes,
    before any weight loads: exit 1 (`_FAILED`), one stderr line naming the
    value, `rolling` and `neighbours`, the composition root never asked and no
    `.mtproj` left beside the scans.

    `with-no-key` pins the order (`## Contract`: resolved **before
    `select_provider`**): with no key as well, the line is the context mode's
    and not the no-key sentence."""
    source_dir = _build_source(tmp_path, png_bytes)
    monkeypatch.setenv(_CONTEXT_VAR, "batch")
    if not keyed:
        monkeypatch.delenv("ANTHROPIC_API_KEY")

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 1, f"exit {code}; a refused context mode is _FAILED (1)"
    assert "Traceback" not in captured.err + captured.out
    lines = captured.err.splitlines()
    assert len(lines) == 1, f"the refusal is not one line: {lines}"
    (line,) = lines
    assert line.startswith("mangatl-run: "), line
    assert "batch" in line and "rolling" in line and "neighbours" in line, (
        f"the refusal does not name the value and both modes: {line!r}"
    )
    assert "API key" not in line, f"the provider was selected before the mode: {line!r}"
    assert composition_root.models_dirs == [], "the composition root was asked to build"
    assert not project_dir_for(source_dir).exists(), "a project was created before the refusal"


def test_an_unknown_context_flag_is_argparses_usage_error(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-5 at the flag** (`choices=CONTEXT_MODES`): argparse's own refusal,
    exit 2, naming the value and both choices; nothing built or created."""
    source_dir = _build_source(tmp_path, png_bytes)

    with pytest.raises(SystemExit) as raised:
        main([str(source_dir), "--models", str(models_dir), "--context", "batch"])

    assert raised.value.code == 2
    err = capsys.readouterr().err
    assert "--context" in err and "invalid choice" in err and "'batch'" in err, err
    assert "'rolling'" in err and "'neighbours'" in err, f"the choices are not named: {err!r}"
    assert composition_root.models_dirs == []
    assert not project_dir_for(source_dir).exists()


def test_the_context_flag_is_one_the_parser_tells_the_user_about(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--context` is in `--help`, with its two choices."""
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    out = capsys.readouterr().out
    assert "--context" in out and "{rolling,neighbours}" in out, out


# -- MT-112 AC-6: a project with pending batch jobs is collected, not run -----------
#
# `mangatl-run FOLDER` on a project holding `submitted` batch jobs collects each,
# in page order, through ONE collector built by `build_batch_collector(selection)`,
# prints one line and exits 0 - and builds no stage: `build_pipeline` (the
# `composition_root` seam) is called zero times. `--sync` is the per-page run:
# with a pending job it refuses in one line naming the first pending job's
# provider id; with none it is today's run.
#
# **The seams are `mangatl.cli.build_batch_collector` and
# `mangatl.cli.collect_volume`**, the module attributes, exactly as
# `mangatl.cli.build_pipeline` is MT-036's: `cli.py` imports both names and
# calls them by those names. `build_batch_collector` is replaced by
# `_CollectorRoot`, which records the selection and hands back a collector that
# answers per provider job id. `collect_volume` is the REAL one, wrapped by a
# recorder only where the page estimate it was handed is asserted - so the
# store, the ledger and the stdout line are the real consequences of a real
# collection.
#
# The projects are built here through the store, as `test_batch_collect.py`
# builds its world: one region and one OCR line per page, a `run` row, and the
# jobs recorded with `record_submission`. Every collecting test sets exactly
# `GEMINI_API_KEY` (the file's autouse fixture sets an Anthropic key; it is
# deleted here), because a pending batch needs the key that submitted it.

_GEMINI_KEY = "gm-SECRET-collect-key-42"
_BATCH_MODEL = "gemini-3.1-pro-preview"


def _gemini_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", _GEMINI_KEY)


def _answer_for(ordinals: Sequence[int], failed: Sequence[int] = ()) -> object:
    """`BatchResults` for `ordinals`: one line per page, `TokenUsage(1000, 500,
    0, 0)` each; an ordinal in `failed` is `BatchItemFailure(n, "quota")`."""
    from mangatl.domain.batch import (  # type: ignore[attr-defined]
        BatchItemFailure,
        BatchResults,
    )
    from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult

    return BatchResults(
        {
            n: BatchItemFailure(n, "quota")
            if n in failed
            else TranslationResult(
                lines={0: f"page {n}"},
                usage=TokenUsage(1000, 500, 0, 0),
                call=CallInfo(f"item-{n}", _BATCH_MODEL),
                proposed_terms=(),
            )
            for n in ordinals
        }
    )


def _still_pending() -> object:
    from mangatl.domain.batch import BatchJobState  # type: ignore[attr-defined]

    return BatchJobState("pending")


class _CollectorRoot:
    """A stand-in for `mangatl.compose.build_batch_collector`, at the seam.

    Records every selection it was built with, and hands back a collector that
    records `(provider_job_id, ordinals)` per call and answers `answers[id]`."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.selections: list[object] = []
        self.calls: list[tuple[str, list[int]]] = []

    def __call__(self, selection: object) -> Callable[[str, Sequence[object]], object]:
        self.selections.append(selection)

        def collect(provider_job_id: str, pages: Sequence[object]) -> object:
            self.calls.append((provider_job_id, [page.ordinal for page in pages]))  # type: ignore[attr-defined]
            return self.answers[provider_job_id]

        return collect


def _collector_root(monkeypatch: pytest.MonkeyPatch, answers: dict[str, object]) -> _CollectorRoot:
    root = _CollectorRoot(answers)
    monkeypatch.setattr("mangatl.cli.build_batch_collector", root)
    return root


def _ring_at(x: int) -> tuple[tuple[int, int], ...]:
    return ((x, 0), (x + 4, 0), (x + 4, 4), (x, 4), (x, 0))


def _project_with_jobs(
    source_dir: Path,
    one_bit_png: Callable[..., bytes],
    jobs: Sequence[tuple[str, int, int]],
    *,
    collected: Sequence[str] = (),
) -> None:
    """Create the project for `source_dir` with one region and one OCR line per
    page and a `run` row, and record `jobs` (provider id, first, last) in the
    order given; the ids in `collected` are then marked collected."""
    from mangatl.domain.line import OcrResult
    from mangatl.domain.region import RawRegion
    from mangatl.store.batch import mark_collected, record_submission
    from mangatl.store.intake import read_chapter
    from mangatl.store.project import create_project

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        mask = one_bit_png(8, 8, [(0, 0, 4, 4)])
        for page in project.pages():
            project.write_regions(
                page.ordinal,
                [RawRegion(polygon=_ring_at(0), mask=mask, confidence=1.0, kind="bubble")],
            )
            project.write_lines(page.ordinal, [OcrResult(f"ページ{page.ordinal}")])
        with project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-11-03T09:00:00+00:00"),
            )
            run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
        for name, first, last in jobs:
            job_id = record_submission(project, run_id, name, _BATCH_MODEL, first, last)
            if name in collected:
                mark_collected(project, job_id)


def _job_states(source_dir: Path) -> list[tuple[object, ...]]:
    return _raw(
        project_dir_for(source_dir) / "project.db",
        "SELECT provider_job_id, state FROM batch_job ORDER BY first_ordinal, id",
    )


def _page_statuses(source_dir: Path) -> list[object]:
    rows = _raw(
        project_dir_for(source_dir) / "project.db", "SELECT status FROM page ORDER BY ordinal"
    )
    return [status for (status,) in rows]


def _ledger_rows(source_dir: Path) -> list[tuple[object, ...]]:
    return _raw(
        project_dir_for(source_dir) / "project.db",
        "SELECT request_id, pricing FROM llm_call ORDER BY id",
    )


_THREE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 11),
)


def test_a_project_with_a_pending_job_is_collected_in_one_line_and_builds_no_stage(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-6: three pages under one pending job. Exit 0, exactly one stdout line
    `batch: 3 pages collected, 0 failed, 0 jobs still pending`, nothing on
    stderr, `build_pipeline` called zero times, the job collected through the
    seam once with its three pages, and the store holding the result."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _THREE_PAGES)
    _project_with_jobs(source_dir, one_bit_png, [("batches/only", 0, 2)])
    collector_root = _collector_root(monkeypatch, {"batches/only": _answer_for([0, 1, 2])})

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    assert _lines(captured.out) == ["batch: 3 pages collected, 0 failed, 0 jobs still pending"]
    assert captured.err == ""
    assert composition_root.models_dirs == [], "a collect run asked for the stage list"
    assert collector_root.calls == [("batches/only", [0, 1, 2])]
    assert _job_states(source_dir) == [("batches/only", "collected")]
    assert _page_statuses(source_dir) == [PAGE_DONE] * 3
    assert _ledger_rows(source_dir) == [
        ("batches/only#0", "batch"),
        ("batches/only#1", "batch"),
        ("batches/only#2", "batch"),
    ]
    assert not _output_dir_for(source_dir).exists(), "a collect run baked the chapter"


def test_the_collector_is_built_once_from_the_gemini_selection(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6: `build_batch_collector(selection)` once, with the Gemini selection
    `main` made, however many jobs are pending."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes)
    _project_with_jobs(source_dir, one_bit_png, [("batches/a", 0, 1), ("batches/b", 2, 3)])
    collector_root = _collector_root(
        monkeypatch, {"batches/a": _answer_for([0, 1]), "batches/b": _answer_for([2, 3])}
    )

    main([str(source_dir), "--models", str(models_dir)])

    assert [_pair(s) for s in collector_root.selections] == [("gemini", _GEMINI_KEY)]


def test_several_pending_jobs_are_collected_in_page_order_and_summed(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-6: the job over pages 2..3 is recorded FIRST, so page order is not
    insertion order; it is collected second. Page 1's item fails: 3 collected,
    1 failed, 0 still pending."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes)
    _project_with_jobs(source_dir, one_bit_png, [("batches/later", 2, 3), ("batches/early", 0, 1)])
    collector_root = _collector_root(
        monkeypatch,
        {"batches/early": _answer_for([0, 1], failed=[1]), "batches/later": _answer_for([2, 3])},
    )

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    assert collector_root.calls == [("batches/early", [0, 1]), ("batches/later", [2, 3])]
    assert _lines(captured.out) == ["batch: 3 pages collected, 1 failed, 0 jobs still pending"]
    assert composition_root.models_dirs == []


def test_a_job_still_running_is_counted_as_still_pending(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-6: the first job is collected, the second answers `pending` and stays
    pending - `2 pages collected, 0 failed, 1 jobs still pending`, exit 0."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes)
    _project_with_jobs(source_dir, one_bit_png, [("batches/a", 0, 1), ("batches/b", 2, 3)])
    _collector_root(monkeypatch, {"batches/a": _answer_for([0, 1]), "batches/b": _still_pending()})

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    assert _lines(captured.out) == ["batch: 2 pages collected, 0 failed, 1 jobs still pending"]
    assert _job_states(source_dir) == [("batches/a", "collected"), ("batches/b", "submitted")]
    assert composition_root.models_dirs == []


def test_a_collect_run_hands_collect_volume_the_batch_tier_page_estimate(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract: `collect_volume(project, job, collector, page_estimate(
    model_for("gemini"), pricing="batch"), reporter)` - $0.02, written out -
    reached through `mangatl.cli.collect_volume`, the real one underneath."""
    from mangatl.domain.money import Usd
    from mangatl.pipeline.batch import collect_volume  # type: ignore[attr-defined]

    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _THREE_PAGES)
    _project_with_jobs(source_dir, one_bit_png, [("batches/only", 0, 2)])
    _collector_root(monkeypatch, {"batches/only": _answer_for([0, 1, 2])})
    seen: list[tuple[str, object]] = []

    def recording(
        project: object,
        job: object,
        collect: object,
        page_estimate: object,
        emit: object,
        *,
        postlude: object = None,
    ) -> object:
        # MT-140: `_collect_pending` passes `postlude=` on every call; the
        # recorder accepts it and forwards it, so this test pins the estimate
        # and nothing about the pass.
        seen.append((job.provider_job_id, page_estimate))  # type: ignore[attr-defined]
        return collect_volume(project, job, collect, page_estimate, emit, postlude=postlude)

    monkeypatch.setattr("mangatl.cli.collect_volume", recording)

    code = main([str(source_dir), "--models", str(models_dir)])

    assert code == 0
    assert seen == [("batches/only", Usd.from_micro(20_000))]


def test_sync_with_a_pending_job_refuses_in_one_line_naming_the_first_pending_job(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-6: `--sync` with pending jobs - exit 1, one stderr line naming the
    FIRST pending job in page order (recorded second here), nothing built,
    nothing collected, every job still pending."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes)
    _project_with_jobs(
        source_dir, one_bit_png, [("batches/last-pages", 2, 3), ("batches/first-pages", 0, 1)]
    )
    collector_root = _collector_root(monkeypatch, {})

    code = main([str(source_dir), "--models", str(models_dir), "--sync"])

    captured = capsys.readouterr()
    assert code == 1, f"exit {code}"
    errors = _lines(captured.err)
    assert len(errors) == 1, f"expected one line on stderr: {errors}"
    assert "batches/first-pages" in errors[0], errors[0]
    assert errors[0].startswith("mangatl-run: "), errors[0]
    assert "Traceback" not in captured.err + captured.out
    assert captured.out == ""
    assert composition_root.models_dirs == [], "--sync built the stage list over a pending batch"
    assert collector_root.selections == [] and collector_root.calls == []
    assert _job_states(source_dir) == [
        ("batches/first-pages", "submitted"),
        ("batches/last-pages", "submitted"),
    ]


@pytest.mark.parametrize("sync", [True, False], ids=["sync", "no-flag"])
def test_with_nothing_pending_the_run_is_todays_run(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
    sync: bool,
) -> None:
    """AC-6: a project whose only job is already collected has nothing pending,
    so with or without `--sync` it is today's run: the stage list is built
    once, every page runs, the output is baked - and no collector is built."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes)
    _project_with_jobs(
        source_dir, one_bit_png, [("batches/done", 0, 3)], collected=["batches/done"]
    )
    collector_root = _collector_root(monkeypatch, {})

    code = main([str(source_dir), "--models", str(models_dir), *(["--sync"] if sync else [])])

    assert code == 0
    assert composition_root.models_dirs == [models_dir]
    assert composition_root.stage.ran == [0, 1, 2, 3]
    assert _output_dir_for(source_dir).is_dir()
    assert collector_root.selections == [], "a collector was built with nothing pending"


def test_sync_on_a_folder_with_no_project_yet_is_todays_first_run(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """AC-6: `--sync` with no `.mtproj` at all creates the project and runs it."""
    source_dir = _build_source(tmp_path, png_bytes)

    code = main([str(source_dir), "--models", str(models_dir), "--sync"])

    assert code == 0
    assert composition_root.stage.ran == [0, 1, 2, 3]
    assert project_dir_for(source_dir).is_dir()


def test_a_pending_job_with_no_gemini_selection_is_refused_in_one_line(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-6: only the Anthropic key is set (the file's default), so there is no
    collector: exit 1, one stderr line, nothing built, the job still pending
    and nothing billed. The REAL `build_batch_collector` answers `None` here."""
    source_dir = _build_source(tmp_path, png_bytes)
    _project_with_jobs(source_dir, one_bit_png, [("batches/a", 0, 3)])

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 1, f"exit {code}"
    errors = _lines(captured.err)
    assert len(errors) == 1, f"expected one line on stderr: {errors}"
    assert errors[0].startswith("mangatl-run: "), errors[0]
    assert "Traceback" not in captured.err + captured.out
    assert captured.out == ""
    assert composition_root.models_dirs == []
    assert _job_states(source_dir) == [("batches/a", "submitted")]
    assert _ledger_rows(source_dir) == []


def test_the_sync_flag_is_one_the_parser_tells_the_user_about(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-6: `--sync` is declared, so it is in `--help`."""
    with pytest.raises(SystemExit) as exited:
        main(["--help"])

    assert exited.value.code == 0
    assert "--sync" in capsys.readouterr().out, "mangatl-run --help does not mention --sync"


# -- MT-140: the consistency pass, after a run and after a collection -----------
#
# The seam is `mangatl.cli.build_consistency` (PO-1), replaced by the
# `_ConsistencyRoot` the `composition_root` fixture installs - `None` by
# default, a recording step once a test calls `hand_out(...)`. `run_chapter`
# and `collect_volume` are the REAL ones: they are what runs the step as a
# postlude (MT-115), so the lines, the exit code and the store are the real
# consequences of the step `main` handed over. `collect_volume` is wrapped by a
# recorder only where AC-5's "every call receives the step as `postlude=`" is
# asserted, because the real one runs the step on the last job alone and the
# step's own call record cannot say what the earlier calls were handed.
#
# RED: `mangatl.cli` never asks for the step, so every case that needs the pass
# to run, or the seam to have been consulted, fails on that - not on a fixture.

_PASS_LINE_2_1 = "Consistency pass: 2 lines corrected, 1 reviewed line left alone"
_PASS_NOT_RUN = (
    "mangatl-run: consistency pass not run: the budget would be exceeded. Every page"
    " is translated and kept; raise the budget and run again to finish."
)
_PASS_FAILED_BOOM = (
    "mangatl-run: consistency pass failed: RuntimeError: boom. Every page is"
    " translated and kept; run again to retry it."
)
_FOUR_PAGE_BATCH_LINE = "batch: 4 pages collected, 0 failed, 0 jobs still pending"


def _corrections(
    applied: int, skipped: int, unchanged: int, run: int, refused: int
) -> CorrectionsApplied:
    return CorrectionsApplied(
        applied=applied,
        skipped_user_lines=skipped,
        unchanged_returned=unchanged,
        chunks_run=run,
        chunks_refused=refused,
    )


def _chapter_call_priced() -> CallPriced:
    """A chapter-level bill (`ordinal=None`), as the pass's own calls are."""
    return CallPriced(
        ordinal=None,
        spent=Usd.from_micro(1_000),
        ceiling=Usd.from_micro(500_000),
        projection=Projection(
            next_call=Usd.from_micro(0),
            remaining_chapter=Usd.from_micro(0),
            basis="estimate",
            sample_count=0,
        ),
    )


def _budget_refused() -> BudgetRefused:
    """Any refused decision will do (contract): the CLI reads only the type."""
    return BudgetRefused(
        Decision(
            permitted=False,
            reason="the consistency pass would exceed the budget",
            spent=Usd.from_micro(0),
            ceiling=Usd.from_micro(1),
            projection=Projection(
                next_call=Usd.from_micro(60_000),
                remaining_chapter=Usd.from_micro(60_000),
                basis="estimate",
                sample_count=0,
            ),
        )
    )


def _boom() -> RuntimeError:
    return RuntimeError("boom")


def _run_ids(source_dir: Path) -> list[object]:
    rows = _raw(project_dir_for(source_dir) / "project.db", "SELECT id FROM run ORDER BY id")
    return [run_id for (run_id,) in rows]


def _record_reporter(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Every event `main`'s reporter receives, in order, the real reporter
    still printing. `mangatl.cli._reporter` is the name the contract gives the
    per-page path's emit (`_reporter(filenames)`)."""
    import mangatl.cli as cli

    real = cli._reporter
    events: list[object] = []

    def reporter(filenames: dict[int, str]) -> Callable[[object], None]:
        report = real(filenames)

        def both(event: object) -> None:
            events.append(event)
            report(event)  # type: ignore[arg-type]

        return both

    monkeypatch.setattr("mangatl.cli._reporter", reporter)
    return events


class _FailingOn:
    """A final-pass stage that raises `error` on `ordinal`; on every other
    page it does nothing, and the runner marks the page done."""

    name = "failing"

    def __init__(self, ordinal: int, error: Exception) -> None:
        self.ordinal = ordinal
        self.error = error

    def run(self, ctx: PageContext) -> None:
        if ctx.page.ordinal == self.ordinal:
            raise self.error

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


def _pass_lines(lines: Sequence[str]) -> list[str]:
    return [line for line in lines if line.startswith("Consistency")]


# -- AC-1: the per-page path asks for the step once and runs it once -------------


def test_the_run_asks_for_the_pass_once_with_its_selection_after_the_pipeline_before_the_project(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-1.** `build_consistency` once, with the Gemini `Selection` `main`
    made; when it is asked, `build_pipeline` has been asked once and the
    project does not exist yet (a refusal leaves no `.mtproj` behind)."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])
    consistency = composition_root.consistency
    consistency.observe = lambda: (
        len(composition_root.models_dirs),
        project_dir_for(source_dir).exists(),
    )
    consistency.hand_out(emits=[_corrections(2, 1, 0, 1, 0)])

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert consistency.selections == [Selection("gemini", _GEMINI_KEY)], (
        f"main asked build_consistency with {consistency.selections!r}; AC-1 asks it"
        " once, with the selection main made"
    )
    assert consistency.observed == [(1, False)], (
        "when build_consistency was asked, (build_pipeline calls so far, project"
        f" exists) was {consistency.observed}; AC-1 wants it after the pipeline and"
        " before the project is created"
    )


def test_the_run_runs_the_pass_once_with_its_run_id_after_the_final_pass_before_it_finishes(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-1.** A two-pass run (MT-130) over three pages: the step runs once,
    with the run's id, after the translating pass's last page and before
    `RunFinished`; the `CallPriced(ordinal=None)` it emits reaches the
    reporter, because the step's emit stream is the run's."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])
    log = _two_passes(composition_root)
    priced = _chapter_call_priced()
    composition_root.consistency.hand_out(emits=[priced, _corrections(2, 1, 0, 1, 0)], log=log)
    events = _record_reporter(monkeypatch)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    consistency = composition_root.consistency
    assert consistency.runs == _run_ids(source_dir), (
        f"the step ran with run ids {consistency.runs}; the chapter's runs are"
        f" {_run_ids(source_dir)} - AC-1 runs it exactly once, with the run's id"
    )
    assert log[-4:] == [("translate", 0), ("translate", 1), ("translate", 2), "consistency"], (
        f"the run went {log}; AC-1 runs the pass after every page of the final pass"
    )
    assert log.count("consistency") == 1, f"the run went {log}"
    priced_at = [i for i, event in enumerate(events) if event is priced]
    finished_at = [i for i, event in enumerate(events) if isinstance(event, RunFinished)]
    last_page_at = max(i for i, event in enumerate(events) if isinstance(event, PageStarted))
    assert len(priced_at) == 1, (
        "the CallPriced(ordinal=None) the step emitted did not reach the reporter"
        f" exactly once: {priced_at}"
    )
    assert len(finished_at) == 1 and last_page_at < priced_at[0] < finished_at[0], (
        f"last page at {last_page_at}, the step's bill at {priced_at}, RunFinished at"
        f" {finished_at}; AC-1 has the pass between the final page and RunFinished"
    )


# -- AC-2: the line a pass that ran prints ------------------------------------


def test_a_pass_that_ran_prints_one_line_after_the_pages_and_before_the_bake_line(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-2.** `CorrectionsApplied(2, 1, 0, 1, 0)`: stdout is the three page
    lines, then exactly `Consistency pass: 2 lines corrected, 1 reviewed line
    left alone`, then the bake line; the output folder is written; exit 0."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])
    composition_root.consistency.hand_out(emits=[_corrections(2, 1, 0, 1, 0)])

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    lines = _lines(captured.out)
    assert lines[:4] == ["[1/3] p1.png", "[2/3] p2.png", "[3/3] p3.png", _PASS_LINE_2_1], (
        f"stdout was {lines}"
    )
    assert len(lines) == 5, f"stdout was {lines}"
    assert lines[4].startswith(f"3 pages written to {_output_dir_for(source_dir)};"), lines[4]
    assert _output_dir_for(source_dir).is_dir()


def test_a_pass_stopped_part_way_says_so_and_the_output_is_still_written(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-2.** `CorrectionsApplied(1, 0, 0, 1, 1)` is not an abort: the
    part-way line, the bake line after it, the folder written, exit 0."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])
    composition_root.consistency.hand_out(emits=[_corrections(1, 0, 0, 1, 1)])

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    lines = _lines(captured.out)
    assert lines[3:4] == [
        "Consistency pass stopped part way: 1 line corrected, 1 of 2 requests made"
        " before the budget was reached. Raise the budget and run again to finish it."
    ], f"stdout was {lines}"
    assert len(lines) == 5 and lines[4].startswith("3 pages written to "), lines
    assert _output_dir_for(source_dir).is_dir()
    assert captured.err == ""


_PART_WAY_TAIL = " before the budget was reached. Raise the budget and run again to finish it."

#: AC-2's number words: singular at exactly 1, plural otherwise, for both
#: counts; `unchanged_returned` never shown (PO-2).
_PASS_LINES: dict[str, tuple[tuple[int, int, int, int, int], str]] = {
    "nothing-changed": (
        (0, 0, 0, 1, 0),
        "Consistency pass: 0 lines corrected, 0 reviewed lines left alone",
    ),
    "one-and-one": (
        (1, 1, 0, 1, 0),
        "Consistency pass: 1 line corrected, 1 reviewed line left alone",
    ),
    "two-and-two": (
        (2, 2, 0, 2, 0),
        "Consistency pass: 2 lines corrected, 2 reviewed lines left alone",
    ),
    "unchanged-is-not-shown": ((2, 1, 5, 1, 0), _PASS_LINE_2_1),
    "part-way-plural": (
        (2, 0, 0, 3, 2),
        "Consistency pass stopped part way: 2 lines corrected, 3 of 5 requests made"
        + _PART_WAY_TAIL,
    ),
    "part-way-none-corrected": (
        (0, 0, 0, 1, 1),
        "Consistency pass stopped part way: 0 lines corrected, 1 of 2 requests made"
        + _PART_WAY_TAIL,
    ),
}


@pytest.mark.parametrize("case", list(_PASS_LINES))
def test_the_pass_line_is_singular_at_exactly_one_and_plural_otherwise(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """**AC-2.** `1 line`, `0 lines`, `2 lines`; `1 reviewed line`, `2
    reviewed lines`; `unchanged_returned` is not shown (PO-2)."""
    counts, expected = _PASS_LINES[case]
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])
    composition_root.consistency.hand_out(emits=[_corrections(*counts)])

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    passes = _pass_lines(_lines(capsys.readouterr().out))
    assert passes == [expected], f"{counts} printed {passes}"


# -- AC-3: a refused or failed pass ends the invocation ------------------------


@pytest.mark.parametrize(
    ("raised", "expected"),
    [(_budget_refused, _PASS_NOT_RUN), (_boom, _PASS_FAILED_BOOM)],
    ids=["budget-refused", "runtime-error"],
)
def test_a_pass_that_does_not_complete_keeps_the_pages_writes_nothing_and_says_how_to_finish(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
    raised: Callable[[], BaseException],
    expected: str,
) -> None:
    """**AC-3.** Every page `done`, no output folder, exit 1, stdout the page
    lines alone (no pass line, no `pages written` line), and stderr exactly
    one line - `not run` for `BudgetRefused`, `failed: RuntimeError: boom`
    otherwise - with no traceback."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])
    composition_root.consistency.hand_out(raises=raised())

    escaped: BaseException | None = None
    code = None
    try:
        code = main([str(source_dir), "--models", str(models_dir)])
    except Exception as error:
        escaped = error

    captured = capsys.readouterr()
    assert escaped is None, f"main let {type(escaped).__name__}: {escaped} escape"
    assert code == 1, f"exit {code}; stderr {captured.err!r}"
    assert captured.err.splitlines() == [expected], f"stderr was {captured.err!r}"
    assert _lines(captured.out) == ["[1/3] p1.png", "[2/3] p2.png", "[3/3] p3.png"], (
        f"stdout was {captured.out!r}"
    )
    assert "Traceback" not in captured.err + captured.out
    assert _page_statuses(source_dir) == [PAGE_DONE] * 3
    assert not _output_dir_for(source_dir).exists(), "a run whose pass did not run was baked"


def test_a_run_aborted_by_a_page_of_the_final_pass_still_reads_run_aborted_and_skips_the_pass(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-3, the negative control.** A stage raising `RuntimeError("boom")`
    on page 2 - the same reason text a failed pass would carry - is a page's
    abort: `run aborted: RuntimeError: boom`, exit 1, and the step `main` was
    handed is never called."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])
    composition_root.reading = (_FailingOn(1, RuntimeError("boom")),)
    consistency = composition_root.consistency
    consistency.hand_out(emits=[_corrections(2, 1, 0, 1, 0)])

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 1, f"exit {code}"
    assert captured.err.splitlines() == ["mangatl-run: run aborted: RuntimeError: boom"], (
        f"stderr was {captured.err!r}"
    )
    assert consistency.selections == [Selection("gemini", _GEMINI_KEY)], (
        "the seam was never consulted, so 'the step is not called' would hold of a"
        f" CLI with no pass at all: {consistency.selections!r}"
    )
    assert consistency.runs == [], f"the pass ran after a page aborted: {consistency.runs}"
    assert _pass_lines(_lines(captured.out)) == []


# -- AC-4: no pass, no line --------------------------------------------------


def test_with_no_translate_the_pass_is_never_asked_for_and_no_line_is_printed(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-4.** `--no-translate` selects nothing, so `build_consistency` is
    not called at all; the output is written, exit 0, no pass line. A Gemini
    key is set and the seam would hand out a step, so a CLI that asked the
    seam regardless would be seen."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])
    consistency = composition_root.consistency
    consistency.hand_out(emits=[_corrections(2, 1, 0, 1, 0)])

    code = main([str(source_dir), "--models", str(models_dir), "--no-translate"])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    assert consistency.selections == [], (
        f"--no-translate asked build_consistency with {consistency.selections!r}"
    )
    assert consistency.runs == []
    assert _pass_lines(_lines(captured.out)) == []
    assert _output_dir_for(source_dir).is_dir()


def test_a_selection_with_no_pass_prints_no_line_and_writes_the_output(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
) -> None:
    """**AC-4.** The file's Anthropic selection, the seam answering `None` (as
    the real one does for `anthropic`): it IS asked - once, with that
    selection - and then no pass line, the output written, exit 0."""
    source_dir = _build_source(tmp_path, png_bytes, _SOURCE_PAGES[:3])

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    assert composition_root.consistency.selections == [Selection("anthropic", _DEFAULT_KEY)], (
        f"the seam was asked with {composition_root.consistency.selections!r}; with no"
        " ask, 'no line' would hold of a CLI that has no pass at all"
    )
    lines = _lines(captured.out)
    assert _pass_lines(lines) == [], lines
    assert len(lines) == 4 and lines[3].startswith("3 pages written to "), lines
    assert _output_dir_for(source_dir).is_dir()


# -- AC-5: the collect path hands every collection the step ----------------------


def _two_pending_jobs(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    monkeypatch: pytest.MonkeyPatch,
    second: object | None = None,
) -> tuple[Path, _CollectorRoot]:
    """Four pages under two pending jobs, `batches/a` (0..1) and `batches/b`
    (2..3), and a Gemini-only environment. `second` replaces `batches/b`'s
    answer (`_still_pending()` keeps it pending)."""
    _gemini_only(monkeypatch)
    source_dir = _build_source(tmp_path, png_bytes)
    _project_with_jobs(source_dir, one_bit_png, [("batches/a", 0, 1), ("batches/b", 2, 3)])
    collector_root = _collector_root(
        monkeypatch,
        {
            "batches/a": _answer_for([0, 1]),
            "batches/b": _answer_for([2, 3]) if second is None else second,
        },
    )
    return source_dir, collector_root


def test_a_collection_asks_for_the_pass_once_after_the_collector_and_before_any_job(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-5.** `build_consistency` once with the Gemini selection; when it is
    asked the collector has been built once and no job collected."""
    source_dir, collector_root = _two_pending_jobs(tmp_path, png_bytes, one_bit_png, monkeypatch)
    consistency = composition_root.consistency
    consistency.observe = lambda: (len(collector_root.selections), len(collector_root.calls))
    consistency.hand_out(emits=[_corrections(2, 1, 0, 1, 0)])

    main([str(source_dir), "--models", str(models_dir)])

    assert consistency.selections == [Selection("gemini", _GEMINI_KEY)], (
        f"the collect path asked build_consistency with {consistency.selections!r}"
    )
    assert consistency.observed == [(1, 0)], (
        f"(collectors built, jobs collected) when it was asked: {consistency.observed};"
        " AC-5 wants it after build_batch_collector and before any job"
    )


def test_every_collection_is_handed_the_step_and_it_runs_once_after_the_last_job(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-5.** `mangatl.cli.collect_volume` wrapped around the real one: both
    calls receive the step `build_consistency` returned, as `postlude=`; the
    step runs exactly once, with the jobs' run id, after the second job's
    `BatchCollected` reached the emit stream."""
    from mangatl.pipeline.batch import collect_volume

    source_dir, _ = _two_pending_jobs(tmp_path, png_bytes, one_bit_png, monkeypatch)
    log: list[object] = []
    consistency = composition_root.consistency
    consistency.hand_out(emits=[_corrections(2, 1, 0, 1, 0)], log=log)
    handed: list[object] = []
    missing = object()

    def recording(
        project: object,
        job: object,
        collect: object,
        page_estimate: object,
        emit: Callable[[object], None],
        **keywords: object,
    ) -> object:
        handed.append(keywords.get("postlude", missing))

        def logging(event: object) -> None:
            if isinstance(event, BatchCollected):
                log.append("collected")
            emit(event)

        return collect_volume(project, job, collect, page_estimate, logging, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr("mangatl.cli.collect_volume", recording)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert len(handed) == 2 and all(p is consistency.handed for p in handed), (
        f"collect_volume was handed postlude={handed!r}; AC-5 hands every call the step"
        " build_consistency returned"
    )
    assert log == ["collected", "collected", "consistency"], f"the collection went {log}"
    assert consistency.runs == _run_ids(source_dir), (
        f"the step ran with {consistency.runs}; the jobs' run is {_run_ids(source_dir)}"
    )


def test_a_collection_that_finishes_the_chapter_prints_the_batch_line_then_the_pass_line(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-5.** The real `collect_volume`: stdout is exactly two lines, the
    `batch:` line then AC-2's pass line, nothing on stderr, exit 0."""
    source_dir, _ = _two_pending_jobs(tmp_path, png_bytes, one_bit_png, monkeypatch)
    composition_root.consistency.hand_out(emits=[_corrections(2, 1, 0, 1, 0)])

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    assert _lines(captured.out) == [_FOUR_PAGE_BATCH_LINE, _PASS_LINE_2_1], (
        f"stdout was {captured.out!r}"
    )
    assert captured.err == ""
    assert composition_root.consistency.runs == _run_ids(source_dir)


def test_with_a_job_still_pending_the_pass_does_not_run_and_the_output_is_todays(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**AC-5, the negative control.** `batches/b` still pending after the
    poll: the step was handed over (the seam was asked) and is not called;
    stdout is the one `batch:` line; exit 0."""
    source_dir, _ = _two_pending_jobs(
        tmp_path, png_bytes, one_bit_png, monkeypatch, second=_still_pending()
    )
    consistency = composition_root.consistency
    consistency.hand_out(emits=[_corrections(2, 1, 0, 1, 0)])

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 0, f"exit {code}; stderr {captured.err!r}"
    assert consistency.selections == [Selection("gemini", _GEMINI_KEY)], (
        "the seam was never consulted, so 'the step is not called' would hold of a"
        f" CLI with no pass at all: {consistency.selections!r}"
    )
    assert consistency.runs == [], f"the pass ran with a job still pending: {consistency.runs}"
    assert _lines(captured.out) == ["batch: 2 pages collected, 0 failed, 1 jobs still pending"]


# -- AC-6: a refused or failed pass after a collection ---------------------------


@pytest.mark.parametrize(
    ("raised", "expected"),
    [(_budget_refused, _PASS_NOT_RUN), (_boom, _PASS_FAILED_BOOM)],
    ids=["budget-refused", "runtime-error"],
)
def test_a_pass_that_does_not_complete_after_a_collection_keeps_the_jobs_and_exits_one(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    capsys: pytest.CaptureFixture[str],
    models_dir: Path,
    composition_root: _CompositionRoot,
    monkeypatch: pytest.MonkeyPatch,
    raised: Callable[[], BaseException],
    expected: str,
) -> None:
    """**AC-6.** The jobs `collected`, the pages `done`, stdout the `batch:`
    line alone, stderr exactly AC-3's line, exit 1, no traceback."""
    source_dir, _ = _two_pending_jobs(tmp_path, png_bytes, one_bit_png, monkeypatch)
    composition_root.consistency.hand_out(raises=raised())

    code = main([str(source_dir), "--models", str(models_dir)])

    captured = capsys.readouterr()
    assert code == 1, f"exit {code}; stderr {captured.err!r}"
    assert captured.err.splitlines() == [expected], f"stderr was {captured.err!r}"
    assert _lines(captured.out) == [_FOUR_PAGE_BATCH_LINE], f"stdout was {captured.out!r}"
    assert "Traceback" not in captured.err + captured.out
    assert _job_states(source_dir) == [("batches/a", "collected"), ("batches/b", "collected")]
    assert _page_statuses(source_dir) == [PAGE_DONE] * 4
