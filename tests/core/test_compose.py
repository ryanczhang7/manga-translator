"""`mangatl.compose`: the composition root's pure half.

**AC-3's mechanism (C-2).** `build_pipeline` is the one function in the project
allowed to construct real ONNX sessions, so it is not coverable here and is not
tested here (`architecture.md` §2's adapter split; PO-7 measures the coverage
headroom this costs). `resolve_models_dir` is the other half and it is pure:
C-2 makes it take the environment **as an argument** precisely so every branch
of it is exercised by `tests/core`, which three required gates read, without
`monkeypatch.setenv` and without a weights directory existing anywhere.

**This module imports `mangatl.compose`, and therefore `onnxruntime`.** That is
new for `tests/core` and it is deliberate rather than overlooked: importing the
runtime is not loading a model, it costs 0.28 s once per session (measured on
this machine, 2026-09-17), and the `integration` gate already proves the import
itself succeeds on a CI runner with no GPU - that is what makes its
`blocked-when` expression match a *provider* failure rather than an import one.
What §2 forbids is a required gate that needs weights, and nothing here does.

**MT-044 AC-6 changes one sentence of the paragraph above, and only one.**
`build_pipeline` is still never called here with its real collaborators - it is
called with `load_detector`, `load_ocr` and `load_vocab` replaced at its own
names, so nothing is loaded, nothing is decoded and no weights need exist. AC-6
is a criterion about *which stages `build_pipeline` builds and what it
constructs while doing it*, and a signature assertion cannot reach either. What
§2's adapter split forbids is a required gate that needs weights; it does not
forbid one that proves the wiring without them, and the three loaders are the
whole of what needs stubbing to get there. The real model still gets its smoke
test in `tests/integration`, where AC-6's "the run completes" clause lives.

What these tests do NOT constrain: how `build_pipeline` orders its three loads,
*how* it produces a two-stage list under `translate=False` (C-14 pins the
signature and the outcome, not the body - a conditional tuple, a second builder
and an optional parameter on `build_stages` are all equally acceptable), whether
`resolve_models_dir` expands `~` or resolves symlinks, what `ModelsNotFound`
derives from beyond `Exception`, and the `str` form of any message except the
one branch PO-4 made a user decision about.
"""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path

import pytest

from mangatl.compose import (
    DETECTOR_FILENAME,
    MODELS_ENV,
    OCR_SUBDIR,
    PROVIDER_PREFERENCE,
    ModelsNotFound,
    build_pipeline,
    resolve_models_dir,
)
from mangatl.ocr.session import DECODER_FILENAME, ENCODER_FILENAME, VOCAB_FILENAME
from mangatl.pipeline.detect_stage import DetectStage
from mangatl.pipeline.ocr_stage import OcrStage
from mangatl.pipeline.translate_stage import TranslateStage

#: `ANTHROPIC_API_KEY`, spelled out rather than read off the SDK. AC-6 is a
#: promise about a machine whose environment does not hold this name, and the
#: name is the SDK's contract with a person typing it into a shell.
_API_KEY_ENV = "ANTHROPIC_API_KEY"

# -- the module's shape --------------------------------------------------------


def test_the_composition_root_exports_exactly_what_the_contract_names() -> None:
    # C-2's `__all__` block, compared in C-2's ORDER rather than sorted (R-4).
    #
    # The order is asserted on purpose. `sorted(module.__all__)` would impose
    # code-point order on one side of this equality only, and C-2's list is not
    # in code-point order: `ModelsNotFound` sorts *before* `OCR_SUBDIR` by code
    # point and *after* `PROVIDER_PREFERENCE` under ruff's RUF022. Mixing the
    # two conventions made the assertion unsatisfiable for every possible
    # `__all__`, and it went unnoticed through RED because this file failed at
    # import and the assertion never ran.
    #
    # Comparing the list directly is strictly stronger than what was intended -
    # it pins order as well as membership - and the order it pins is the one
    # RUF022 already enforces on the shipped `src/mangatl/compose.py`, so this
    # test and the linter agree rather than compete. Do not re-add `sorted(`.
    import mangatl.compose as module

    assert module.__all__ == [
        "DETECTOR_FILENAME",
        "MODELS_ENV",
        "OCR_SUBDIR",
        "PROVIDER_PREFERENCE",
        "ModelsNotFound",
        "build_pipeline",
        "resolve_models_dir",
    ]


def test_the_environment_variable_is_the_one_the_user_was_told_about() -> None:
    # PO-4, a user decision of 2026-09-17. The literal is spelled out rather
    # than read off the constant, because it is a promise to a person typing it
    # into a shell, not an internal name.
    assert MODELS_ENV == "MANGATL_MODELS"


def test_the_models_directory_layout_is_the_one_c6_draws() -> None:
    # C-6. `load_ocr` takes the *directory*, which is why a subdirectory name
    # exists here rather than three separate paths.
    assert DETECTOR_FILENAME == "comic-text-detector.onnx"
    assert OCR_SUBDIR == "manga-ocr"


def test_the_three_ocr_filenames_are_referenced_and_never_respelled() -> None:
    """C-6: the OCR filenames are `ocr.session`'s own exported constants.

    A second spelling of `encoder_model.onnx` in the composition root is a
    duplicate that nothing keeps in step: `ocr.session` could rename its file
    and `load_ocr` would keep working while `build_pipeline` looked for the old
    name. Asserted against the module's source text, because the failure is a
    string literal and not an import.
    """
    import mangatl.compose as module

    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")

    respelled = sorted(
        name
        for name in (ENCODER_FILENAME, DECODER_FILENAME, VOCAB_FILENAME)
        if f'"{name}"' in source or f"'{name}'" in source
    )
    assert respelled == [], (
        f"{respelled} is spelled out in mangatl/compose.py. C-6 says the three OCR"
        " filenames are ocr.session's exported constants, referenced and never"
        " re-spelled."
    )


def test_the_provider_preference_is_cuda_then_cpu_and_is_not_a_fallback_chain() -> None:
    """D3's correction, read out rather than re-decided.

    CUDA then CPU, **not** CUDA/DirectML/CPU: the chain is a packaging choice
    between mutually exclusive wheels and this project installs
    `onnxruntime-gpu[cuda,cudnn]`. MT-024 owns the real `select_providers`; this
    constant is the interim (C-2).
    """
    assert PROVIDER_PREFERENCE == ("CUDAExecutionProvider", "CPUExecutionProvider")
    assert type(PROVIDER_PREFERENCE) is tuple


def test_the_composition_root_does_not_import_the_window_it_has_no_display_for() -> None:
    """C-2's last clause and PO-3's, as a unit tripwire beside the `lint`
    contract that owns it.

    MT-006 PO-5 put `mangatl.cli` in *"Nothing imports ui"* on purpose so that
    headlessness is a checked fact; this story's exemption from rule 5 must not
    undo it by the back door, and `mangatl.compose` is listed in that contract
    by C-5. This test is here because the failure is cheap to make - a type
    annotation reaching for a widget - and it names the offending import in the
    `unit` gate rather than in a contract report.
    """
    import mangatl.compose as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    forbidden = sorted(
        name
        for name in imported
        for root in ("mangatl.ui", "PySide6")
        if name == root or name.startswith(f"{root}.")
    )
    assert forbidden == [], f"{forbidden} is imported by mangatl.compose"


def test_the_pipeline_builders_only_positional_argument_is_the_models_directory() -> None:
    """The builder's shape, pinned where `tests/core` can hold it.

    `architecture.md` §2: the real model gets its smoke test in
    `tests/integration`, and AC-4 is that test.

    **AMENDED IN RED for MT-044 AC-6, 2026-09-22 (`## Regressions` R-10), and
    renamed with it.** It said `parameters == ["models_dir"]` and was named
    `..._takes_one_argument_and_...`, which C-14 makes false: the builder now
    takes a second parameter, `translate`. The *intent* was never "one
    parameter" - it was **"the only positional argument is the models
    directory"**, which is exactly what keyword-only preserves, so the
    amendment is the narrow one and the assertion got stronger rather than
    looser. The name changed because the old one would have read like a bug
    report about a thing that is no longer a bug.

    The three assertions are the three separate facts C-14 relies on, and each
    fails on its own account: `translate` exists, it cannot be passed
    positionally (so `build_pipeline(models_dir, False)` is a `TypeError` at
    every call site rather than a silent argument in the wrong slot), and
    omitting it translates (the flag is an opt-out a user types, never a state
    the program drifts into).
    """
    parameters = inspect.signature(build_pipeline).parameters

    assert list(parameters) == ["models_dir", "translate"], (
        f"build_pipeline takes {list(parameters)}; C-14 makes it (models_dir, *, translate)"
    )
    assert parameters["models_dir"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, (
        "the models directory stopped being positional; every caller in the"
        " project passes it positionally"
    )
    assert parameters["translate"].kind is inspect.Parameter.KEYWORD_ONLY, (
        f"translate is {parameters['translate'].kind}, not keyword-only. C-14 is"
        " keyword-only so that the builder's only positional argument stays the"
        " models directory, which is what this test has pinned since MT-036"
    )
    assert parameters["translate"].default is True, (
        f"translate defaults to {parameters['translate'].default!r}. C-14: the"
        " default is True because translating is what the tool is for - the flag"
        " is an opt-out a user types, never a state the program drifts into"
    )


# -- MT-044 AC-6: `--no-translate`, at the seam that decides both halves -------


class _Loaders:
    """The three weight loaders `build_pipeline` calls, replaced at its own names.

    Nothing here loads anything: each call records the path it was handed and
    returns a sentinel that only has to be identifiable. That is what puts
    AC-6 - a criterion about *which stages get built* - inside `tests/core`,
    which three required gates read, with no weights on the machine and no GPU.
    """

    def __init__(self) -> None:
        self.detector_paths: list[Path] = []
        self.ocr_dirs: list[Path] = []
        self.vocab_paths: list[Path] = []

    def load_detector(self, path: Path, providers: tuple[str, ...]) -> object:
        self.detector_paths.append(path)
        return f"detector-session({path})"

    def load_ocr(self, directory: Path, providers: tuple[str, ...]) -> object:
        self.ocr_dirs.append(directory)
        return f"ocr-session({directory})"

    def load_vocab(self, path: Path) -> object:
        self.vocab_paths.append(path)
        return f"vocab({path})"


class _ClientSpy:
    """A stand-in for `anthropic.Anthropic`, at `mangatl.compose`'s name for it.

    **This counter is the only thing in `tests/core` that can tell "never
    constructed" from "constructed and thrown away".** C-13 measured that a real
    `Anthropic()` constructs happily with no key and raises only at request
    time, so a build that runs to completion on a keyless machine proves exactly
    nothing about AC-6's middle clause. Counting constructions does.

    **What it would not catch, stated so nobody mistakes its reach.** A
    `build_pipeline` that constructed its client somewhere other than
    `mangatl.compose.Anthropic` - a factory, a helper module, a lazily imported
    name - would leave this counter at zero under the flag, and the negative
    assertion would pass while a client was being built. That is why the
    positive control lives in the same file with the same patch installed: if
    the construction ever moves off this name, the *control* goes red rather
    than the negative assertion going quietly vacuous. Neither test is evidence
    without the other.
    """

    def __init__(self) -> None:
        self.clients: list[object] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        # `*args`/`**kwargs` rather than `()`: C-13 pins `Anthropic()` with no
        # arguments, and this double is here to count constructions, not to
        # re-pin the call shape at a second site.
        client = f"anthropic-client-{len(self.clients)}"
        self.clients.append(client)
        return client


@pytest.fixture
def loaders(monkeypatch: pytest.MonkeyPatch) -> _Loaders:
    stubs = _Loaders()
    monkeypatch.setattr("mangatl.compose.load_detector", stubs.load_detector)
    monkeypatch.setattr("mangatl.compose.load_ocr", stubs.load_ocr)
    monkeypatch.setattr("mangatl.compose.load_vocab", stubs.load_vocab)
    return stubs


@pytest.fixture
def client_spy(monkeypatch: pytest.MonkeyPatch) -> _ClientSpy:
    spy = _ClientSpy()
    monkeypatch.setattr("mangatl.compose.Anthropic", spy)
    return spy


@pytest.fixture
def keyless(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ANTHROPIC_API_KEY` out of the environment: AC-6's "no API key" machine.

    A developer with a key exported in their shell must not see different
    behaviour from CI on the one clause this criterion is about.
    """
    monkeypatch.delenv(_API_KEY_ENV, raising=False)


@pytest.fixture
def weights_dir(tmp_path: Path) -> Path:
    """A models directory that exists and holds nothing.

    The loaders are replaced and `build_pipeline` does not stat anything else,
    so an empty directory is exactly enough - and it keeps these tests honest
    about which half of the module each one exercises.
    """
    directory = tmp_path / "models"
    directory.mkdir()
    return directory


def test_the_no_translate_flag_builds_detect_and_ocr_only_and_constructs_no_client(
    weights_dir: Path, loaders: _Loaders, client_spy: _ClientSpy, keyless: None
) -> None:
    """**AC-6**, first and second clauses, at the one place both are decided.

    *Holds detect and OCR only* is asserted by type and by length, the way
    `test_stages.py` asserts the three-stage list: a list that lost or gained a
    stage still satisfies every assertion about the ones it kept, so the count
    is not decoration. The stage classes are imported rather than named by
    string - `"detect"` and `"ocr"` are `test_stages.py`'s literals and C-6's,
    and re-spelling settled names here would let the two files disagree.

    *No `Anthropic` client is constructed* is asserted by the counter, for the
    reason `_ClientSpy` gives at length: this is a claim about something that
    does not happen, and every cheaper way of checking it - running keyless and
    seeing no error, reading the module's AST for the name - is satisfied by a
    build that constructs a client and drops it on the floor. C-14: *"must not
    construct an `Anthropic` at all - not construct-and-discard"*.

    The two loader assertions are what stops the whole thing passing for the
    wrong reason: a `build_pipeline` that refused the flag by building *nothing*
    would satisfy the first three and is not a pipeline. With the flag the
    weights still load, because the run still detects and still transcribes.
    """
    stages = build_pipeline(weights_dir, translate=False)

    assert [type(stage) for stage in stages] == [DetectStage, OcrStage], (
        f"--no-translate built {[type(stage).__name__ for stage in stages]};"
        " AC-6 says detect and OCR only"
    )
    assert len(stages) == 2, (
        f"the flagged stage list holds {len(stages)} stages; a list that kept a"
        " third one satisfies every type assertion about the first two"
    )
    assert [stage.name for stage in stages] == [DetectStage.name, OcrStage.name]
    assert client_spy.clients == [], (
        f"--no-translate constructed {len(client_spy.clients)} Anthropic"
        " client(s). C-13 measured that construction succeeds with no key and"
        " raises only at request time, so this is invisible to a run that"
        " completes - which is exactly why AC-6 names the construction and not"
        " the failure"
    )
    assert loaders.detector_paths == [weights_dir / DETECTOR_FILENAME], (
        "the flagged pipeline did not load the detector; --no-translate drops"
        f" the translate stage, not the run: {loaders.detector_paths}"
    )
    assert loaders.ocr_dirs == [weights_dir / OCR_SUBDIR]
    assert loaders.vocab_paths == [weights_dir / OCR_SUBDIR / VOCAB_FILENAME]


def test_the_unflagged_build_still_translates_and_constructs_exactly_one_client(
    weights_dir: Path, loaders: _Loaders, client_spy: _ClientSpy, keyless: None
) -> None:
    """**AC-6's positive control, and C-14's default read off a real call.**

    Two things at once, and neither is spare. It pins that omitting the flag
    still builds the translating pipeline - `translate` defaults to `True`,
    asserted here by behaviour rather than by `inspect` - and it is what makes
    the negative assertion in the test above mean anything: the counter is
    reading the name `build_pipeline` actually constructs its client through, so
    a zero under the flag is a fact about the flag rather than about the patch.

    **Green on arrival**, because today's one-argument `build_pipeline` already
    builds three stages and one client. Earned with two mutations of the exact
    production behaviour it claims to pin - the client construction in
    `compose.py` and the translate stage in `stages.py` - both reverted, both
    pasted into `## Regressions` R-10.
    """
    stages = build_pipeline(weights_dir)

    assert [type(stage) for stage in stages] == [DetectStage, OcrStage, TranslateStage], (
        f"the unflagged stage list is {[type(stage).__name__ for stage in stages]};"
        " AC-4 is detect, then OCR, then translate, and C-14 leaves it alone"
    )
    assert len(client_spy.clients) == 1, (
        f"the unflagged build constructed {len(client_spy.clients)} clients"
        " through mangatl.compose.Anthropic. Exactly one is C-13; zero means the"
        " construction has moved off this name, and every 'no client was"
        " constructed' assertion in this file is reading a counter nothing"
        " increments any more"
    )


def test_the_flagged_build_needs_no_api_key_in_the_environment(
    weights_dir: Path, loaders: _Loaders, keyless: None
) -> None:
    """**AC-6's last clause**, as far as `tests/core` can honestly carry it.

    The real `anthropic.Anthropic` is left in place here - no `client_spy` - so
    this is the flagged build running through production's own names on a
    machine with no key.

    **What it would catch:** a `build_pipeline` that reads the key eagerly, or
    that asks the SDK for anything that needs one, under `--no-translate`.

    **What it would not catch, and this is the important half:** C-13 measured
    that `Anthropic()` constructs successfully with `ANTHROPIC_API_KEY` absent,
    so a build that constructs a client and discards it passes here without a
    murmur. This test is not evidence about construction and is not offered as
    any; the counter two tests up is. What neither can reach is *the run* - five
    real pages walked end to end with no key - which is
    `tests/integration/test_pipeline_chapter.py`'s, on a machine with the
    weights.
    """
    stages = build_pipeline(weights_dir, translate=False)

    assert len(stages) == 2
    assert _API_KEY_ENV not in os.environ, "the premise of this test was not established"


# -- C-2: resolving the models directory, every branch -------------------------


def test_an_explicit_override_is_the_directory_that_is_used(tmp_path: Path) -> None:
    override = tmp_path / "weights"
    override.mkdir()

    assert resolve_models_dir(override, {}) == override


def test_the_override_wins_over_the_environment(tmp_path: Path) -> None:
    """PO-4's resolution order, first clause: `--models`, then
    `$MANGATL_MODELS`. Both are valid directories here, so the only thing that
    can decide the answer is the precedence rule."""
    override = tmp_path / "from-the-flag"
    override.mkdir()
    from_env = tmp_path / "from-the-environment"
    from_env.mkdir()

    assert resolve_models_dir(override, {MODELS_ENV: str(from_env)}) == override


def test_the_environment_is_used_when_no_override_is_given(tmp_path: Path) -> None:
    from_env = tmp_path / "from-the-environment"
    from_env.mkdir()

    assert resolve_models_dir(None, {MODELS_ENV: str(from_env)}) == from_env


def test_an_unrelated_variable_in_the_environment_is_not_mistaken_for_ours(
    tmp_path: Path,
) -> None:
    from_env = tmp_path / "from-the-environment"
    from_env.mkdir()

    with pytest.raises(ModelsNotFound):
        resolve_models_dir(None, {"MANGATL_MODEL": str(from_env), "MODELS": str(from_env)})


def test_neither_a_flag_nor_a_variable_names_the_variable_the_user_could_set() -> None:
    """PO-4: *"no silent default"*, and the message is the whole point of the
    branch - a default pointing at a missing directory produces an onnxruntime
    stack trace instead of a sentence.

    The name of the environment variable is the half of PO-4's message this
    module can be held to; `--models` belongs to the argument parser and is
    asserted in `test_cli.py`.
    """
    with pytest.raises(ModelsNotFound) as raised:
        resolve_models_dir(None, {})

    assert MODELS_ENV in str(raised.value), (
        f"the message does not name {MODELS_ENV}, so a user who has not set it is"
        f" not told what to set: {str(raised.value)!r}"
    )


def test_an_empty_environment_variable_is_not_a_models_directory() -> None:
    """The trap this branch exists to avoid, and the reason C-2 is amended.

    `Path("")` is `Path(".")`, and `Path(".").is_dir()` is `True`, so a
    resolver that tests only for presence answers "the current working
    directory" for `MANGATL_MODELS=`. `build_pipeline` would then look for the
    weights wherever the user happened to be standing and fail with an
    onnxruntime error about a missing file, which is exactly the outcome PO-4's
    "no silent default" rules out. An unset variable and an empty one are the
    same statement.
    """
    assert Path("").is_dir(), "the premise of this test no longer holds on this platform"

    with pytest.raises(ModelsNotFound):
        resolve_models_dir(None, {MODELS_ENV: ""})


def test_an_override_that_is_not_a_directory_is_refused_by_name(tmp_path: Path) -> None:
    missing = tmp_path / "not-there"

    with pytest.raises(ModelsNotFound) as raised:
        resolve_models_dir(missing, {})

    assert missing.name in str(raised.value), (
        f"the message does not say which path was wrong: {str(raised.value)!r}"
    )


def test_an_override_that_is_a_file_rather_than_a_directory_is_refused(tmp_path: Path) -> None:
    # The likeliest form of the mistake: pointing `--models` at the detector
    # weights themselves instead of at the folder holding them.
    weights = tmp_path / DETECTOR_FILENAME
    weights.write_bytes(b"not really an onnx graph")

    with pytest.raises(ModelsNotFound):
        resolve_models_dir(weights, {})


def test_an_environment_value_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    missing = tmp_path / "not-there"

    with pytest.raises(ModelsNotFound):
        resolve_models_dir(None, {MODELS_ENV: str(missing)})


def test_resolving_does_not_check_that_the_weights_are_present(tmp_path: Path) -> None:
    """C-2, explicitly: `resolve_models_dir` does **not** stat the four weight
    files.

    That is `build_pipeline`'s business, and a resolver that stats files cannot
    be tested without them - which would put this whole function outside the
    `coverage` gate's reach and is the failure §2's adapter split exists to
    prevent.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    assert list(empty.iterdir()) == []

    assert resolve_models_dir(empty, {}) == empty
    assert resolve_models_dir(None, {MODELS_ENV: str(empty)}) == empty


def test_the_failure_is_an_exception_a_caller_can_catch_by_name() -> None:
    # `cli.main` catches it and turns it into one sentence on stderr, exactly
    # as it catches `NoPagesFound` (C-3). A bare `RuntimeError` there would
    # either be caught too broadly or reach the user as a traceback.
    assert issubclass(ModelsNotFound, Exception)
