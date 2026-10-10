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
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.store.project import PAGE_DONE, project_dir_for

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

    def __call__(
        self,
        models_dir: Path,
        *,
        translate: bool | None = None,
        selection: object = None,
    ) -> tuple[Stage, ...]:
        self.models_dirs.append(models_dir)
        self.translate_flags.append(translate)
        self.selections.append(selection)
        return (self.stage,)


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
    root = _CompositionRoot()
    monkeypatch.setattr("mangatl.cli.build_pipeline", root)
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


_UNAVAILABLE_CASES = {
    "gemini-key-only": ({"GEMINI_API_KEY": "sk-SECRET-gem-4567"}, [], "gemini"),
    "openai-key-only-with-flag": (
        {"OPENAI_API_KEY": "sk-SECRET-oai-89ab"},
        ["--provider", "openai"],
        "openai",
    ),
    "two-keys-variable-chooses-gemini": (
        {"ANTHROPIC_API_KEY": _DEFAULT_KEY, "GEMINI_API_KEY": "sk-SECRET-gem-4567"},
        [],
        "gemini",
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
    if case == "two-keys-variable-chooses-gemini":
        monkeypatch.setenv("MANGATL_PROVIDER", "gemini")
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

    def build(models_dir: Path, **keywords: object) -> tuple[Stage, ...]:
        seen.append(project_dir_for(source_dir).exists())
        return root(models_dir, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr("mangatl.cli.build_pipeline", build)

    assert main([str(source_dir), "--models", str(models_dir)]) == 0

    assert seen == [False], (
        f"build_pipeline saw the project existing: {seen}; amended C-3 (A-2) builds"
        " before it creates, so a refusal leaves nothing behind"
    )
    assert root.stage.ran == list(range(len(_SOURCE_PAGES))), "the run did not walk the chapter"
