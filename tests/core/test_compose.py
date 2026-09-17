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

What these tests do NOT constrain: how `build_pipeline` orders its three loads,
whether `resolve_models_dir` expands `~` or resolves symlinks, what
`ModelsNotFound` derives from beyond `Exception`, and the `str` form of any
message except the one branch PO-4 made a user decision about.
"""

from __future__ import annotations

import ast
import inspect
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


def test_the_pipeline_builder_takes_one_argument_and_it_is_the_models_directory() -> None:
    """`build_pipeline` is not called here - it constructs real sessions - so
    its shape is pinned the only way `tests/core` honestly can.

    `architecture.md` §2: the real model gets its smoke test in
    `tests/integration`, and AC-4 is that test.
    """
    parameters = list(inspect.signature(build_pipeline).parameters)
    assert parameters == ["models_dir"]


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
