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
        self.stage = _CountingStage()

    def __call__(self, models_dir: Path, *, translate: bool | None = None) -> tuple[Stage, ...]:
        self.models_dirs.append(models_dir)
        self.translate_flags.append(translate)
        return (self.stage,)


@pytest.fixture(autouse=True)
def _no_ambient_models_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """`MANGATL_MODELS` out of the environment for every test in this file."""
    monkeypatch.delenv(_MODELS_ENV, raising=False)


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
