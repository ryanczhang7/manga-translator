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

**MT-065 AC-6/AC-7 add a fourth loader and a fourth stage.** `build_pipeline`
now also loads the inpainter - `load_inpainter` on `lama_fp32.onnx` directly
under the models directory - under **both** values of `translate`, and binds it
into a `CleanStage` through `clean_page_image` (C-7). The `loaders` fixture
replaces `load_inpainter` too, with a recorder returning a fake
`InpaintSession` that counts its `run` calls (MT-019 C-2's convention), so
"the clean stage is bound to the loaded session" is asserted by behaviour - the
stage's callable is run and the fake's counter moves - and not only by type.
The full list is detect, clean, OCR, translate; under the flag it is detect,
clean, OCR (PO-1, the user's decision; PO-3 the order).

What these tests do NOT constrain: how `build_pipeline` orders its four loads,
*how* it produces the short list under `translate=False` (C-14 pins the
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.compose import (
    DETECTOR_FILENAME,
    INPAINTER_FILENAME,
    MODELS_ENV,
    OCR_SUBDIR,
    PROVIDER_PREFERENCE,
    ModelsNotFound,
    build_pipeline,
    resolve_models_dir,
)
from mangatl.domain.region import RawRegion
from mangatl.ocr.session import DECODER_FILENAME, ENCODER_FILENAME, VOCAB_FILENAME
from mangatl.pipeline.clean_stage import CleanStage
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

    # MT-065 C-7 adds `INPAINTER_FILENAME`, in RUF022's order.
    assert module.__all__ == [
        "DETECTOR_FILENAME",
        "INPAINTER_FILENAME",
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


def test_the_inpainter_is_lama_fp32_never_lama() -> None:
    # MT-065 AC-6 names the file, so the literal is spelled here. `lama.onnx`
    # is the export MT-002 E3/E4 measured and rejected; C-7.
    assert INPAINTER_FILENAME == "lama_fp32.onnx"


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


@dataclass
class _FakeInpaintSession:
    """An `InpaintSession` that counts its `run` calls (MT-065 C-7).

    MT-019 C-2's convention: `run(image, mask)` returns `image * 255`, the
    model-scale composite of an export that changed nothing, and
    `get_providers()` reports the CPU. The count is the whole point: it is what
    shows the composed clean stage reaches *this* session and not another.
    """

    runs: int = 0

    def run(self, image: NDArray[np.float32], mask: NDArray[np.float32]) -> NDArray[np.float32]:
        self.runs += 1
        return (image * 255.0).astype(np.float32)

    def get_providers(self) -> Sequence[str]:
        return ["CPUExecutionProvider"]


@dataclass
class _FakeDetectorSession:
    """A `DetectorSession` as far as `selected_provider` reads one (MT-024 AC-6):
    `get_providers()` reports what the session *actually* runs on, which is
    not necessarily what it was asked for."""

    path: Path
    reports: list[str]

    def get_providers(self) -> Sequence[str]:
        return list(self.reports)


class _Loaders:
    """The four weight loaders `build_pipeline` calls, replaced at its own names.

    Nothing here loads anything: each call records the path it was handed and
    returns a sentinel that only has to be identifiable - except the
    inpainter's, which returns a counting fake session, because MT-065 C-7
    asserts the clean stage by running it. That is what puts AC-6 - a
    criterion about *which stages get built* - inside `tests/core`, which three
    required gates read, with no weights on the machine and no GPU.
    """

    #: What the fake detector session reports from `get_providers()`: `None`
    #: means "the first provider it was asked for" (a machine where the request
    #: was honoured); a list means "this, whatever was asked" (MT-024 AC-6's
    #: CUDA-requested, CPU-delivered case).
    detector_reports: list[str] | None = None

    def __init__(self) -> None:
        self.detector_paths: list[Path] = []
        self.detector_providers: list[tuple[str, ...]] = []
        self.ocr_providers: list[tuple[str, ...]] = []
        self.ocr_dirs: list[Path] = []
        self.vocab_paths: list[Path] = []
        self.inpainter_loads: list[tuple[Path, tuple[str, ...]]] = []
        self.inpainters: list[_FakeInpaintSession] = []

    def load_detector(self, path: Path, providers: tuple[str, ...]) -> _FakeDetectorSession:
        self.detector_paths.append(path)
        self.detector_providers.append(tuple(providers))
        reports = self.detector_reports
        return _FakeDetectorSession(path, list(providers[:1]) if reports is None else list(reports))

    def load_ocr(self, directory: Path, providers: tuple[str, ...]) -> object:
        self.ocr_dirs.append(directory)
        self.ocr_providers.append(tuple(providers))
        return f"ocr-session({directory})"

    def load_vocab(self, path: Path) -> object:
        self.vocab_paths.append(path)
        return f"vocab({path})"

    def load_inpainter(self, path: Path, providers: Sequence[str]) -> _FakeInpaintSession:
        self.inpainter_loads.append((path, tuple(providers)))
        session = _FakeInpaintSession()
        self.inpainters.append(session)
        return session


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
    # MT-065 C-1 (b): without this every `build_pipeline` call in the file
    # reaches the real onnxruntime on an empty directory.
    monkeypatch.setattr("mangatl.compose.load_inpainter", stubs.load_inpainter)
    # MT-024 AC-6 (C-5): `build_pipeline` requests
    # `select_providers(available_providers())`, so without this every assertion
    # about the providers requested would be about THIS machine's onnxruntime.
    # CUDA and CPU both "available", so the selection is PROVIDER_PREFERENCE and
    # the `:530` assertion below stays about selection. `raising=False`: the
    # name does not exist until GREEN.
    monkeypatch.setattr(
        "mangatl.compose.available_providers",
        lambda: ["CPUExecutionProvider", "CUDAExecutionProvider"],
        raising=False,
    )
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


def test_the_no_translate_flag_builds_detect_clean_and_ocr_and_constructs_no_client(
    weights_dir: Path, loaders: _Loaders, client_spy: _ClientSpy, keyless: None
) -> None:
    """**MT-044 AC-6**, first and second clauses, at the one place both are
    decided - **as MT-065 AC-7 amends the first**: the flagged list is detect,
    clean, OCR (`## Amendments` A-1 of MT-065; it was "detect and OCR only").

    *The list* is asserted by type and by length, the way
    `test_stages.py` asserts the four-stage list: a list that lost or gained a
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
    weights still load, because the run still detects, cleans and transcribes
    (the inpainter's load under the flag is the parametrised test below).
    """
    stages = build_pipeline(weights_dir, translate=False)

    assert [type(stage) for stage in stages] == [DetectStage, CleanStage, OcrStage], (
        f"--no-translate built {[type(stage).__name__ for stage in stages]};"
        " MT-065 AC-7 says detect, clean, OCR"
    )
    assert len(stages) == 3, (
        f"the flagged stage list holds {len(stages)} stages; a list that kept a"
        " fourth one satisfies every type assertion about the first three"
    )
    assert [stage.name for stage in stages] == [
        DetectStage.name,
        CleanStage.name,
        OcrStage.name,
    ]
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
    pasted into `## Regressions` R-10. (That was MT-044's arrival. MT-065
    makes the list four stages, so in MT-065's RED it is red by assertion.)
    """
    stages = build_pipeline(weights_dir)

    assert [type(stage) for stage in stages] == [
        DetectStage,
        CleanStage,
        OcrStage,
        TranslateStage,
    ], (
        f"the unflagged stage list is {[type(stage).__name__ for stage in stages]};"
        " MT-065 AC-7 is detect, clean, OCR, translate"
    )
    assert len(stages) == 4
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

    assert len(stages) == 3
    assert _API_KEY_ENV not in os.environ, "the premise of this test was not established"


# -- MT-065 AC-6/AC-7: the clean stage, built from `load_inpainter` ------------


@pytest.mark.parametrize("translate", [True, False], ids=["translating", "no-translate"])
def test_the_inpainter_is_loaded_once_from_lama_fp32_in_the_models_directory(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    translate: bool,
) -> None:
    """**MT-065 AC-6** (C-7): `load_inpainter` on `lama_fp32.onnx` directly
    under the models directory, with the interim provider preference - and
    under **both** values of `translate`, because `--no-translate` still
    cleans (AC-7, PO-1). The file name is the literal, spelled here because
    AC-6 names it (DV-6 turns this red)."""
    build_pipeline(weights_dir, translate=translate)

    assert loaders.inpainter_loads == [(weights_dir / "lama_fp32.onnx", PROVIDER_PREFERENCE)], (
        f"the inpainter loads were {loaders.inpainter_loads}; AC-6 is exactly one,"
        " from <models>/lama_fp32.onnx, with PROVIDER_PREFERENCE"
    )


@pytest.mark.parametrize("translate", [True, False], ids=["translating", "no-translate"])
def test_the_clean_stage_runs_the_loaded_inpainter_through_clean_page_image(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    translate: bool,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> None:
    """**MT-065 AC-6**, behaviourally (C-7): the `CleanStage`'s callable, handed
    a small PNG page and one region with a non-empty mask, returns a PNG of the
    page's size, and the session `load_inpainter` returned is the one that ran.
    A stage bound to anything else - a second session, a lambda, the identity -
    leaves the counter at zero."""
    stages = build_pipeline(weights_dir, translate=translate)
    (clean_stage,) = [stage for stage in stages if isinstance(stage, CleanStage)]
    (session,) = loaders.inpainters
    width, height = 64, 48
    region = RawRegion(
        polygon=((10, 10), (20, 10), (20, 20), (10, 20), (10, 10)),
        mask=one_bit_png(width, height, [(10, 10, 20, 20)]),
        confidence=0.5,
        kind="bubble",
    )
    assert session.runs == 0

    cleaned = clean_stage.clean(png_bytes(width, height, (30, 60, 90)), [region])

    assert session.runs >= 1, (
        "the composed clean stage did not run the session load_inpainter returned"
    )
    assert cleaned[:8] == b"\x89PNG\r\n\x1a\n", "the composed cleaner did not return a PNG"
    with Image.open(BytesIO(cleaned)) as image:
        assert image.size == (width, height)


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


# -- MT-024 AC-6: the providers requested are selected, and the one used is logged --
#
# `build_pipeline` requests `select_providers(available_providers())` - not the
# constant - from all three ONNX loaders, and then logs `inference provider:
# <name>` at INFO on the `mangatl.compose` logger, where `<name>` is
# `selected_provider(detector)`: what the detector session reports it runs on,
# never what was asked for (MT-002 E2: onnxruntime falls back to CPU silently).
# `available_providers` is replaced at its own name: the `loaders` fixture
# installs CPU+CUDA, and each test below that needs another list sets it.
#
# RED: `build_pipeline` passes `PROVIDER_PREFERENCE` regardless and logs
# nothing, so these fail on their assertions. DV-3 reorders the preference and
# the log assertion must move with it.

_CUDA = "CUDAExecutionProvider"
_CPU = "CPUExecutionProvider"


def _available(monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
    monkeypatch.setattr("mangatl.compose.available_providers", lambda: list(names), raising=False)


def _provider_lines(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if record.name == "mangatl.compose" and record.getMessage().startswith("inference provider")
    ]


def test_available_providers_is_onnxruntimes_own_list() -> None:
    import onnxruntime

    import mangatl.compose as module

    assert module.available_providers() == onnxruntime.get_available_providers()


def test_on_a_machine_with_only_the_cpu_every_loader_is_asked_for_the_cpu_only(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _available(monkeypatch, [_CPU])

    build_pipeline(weights_dir)

    assert loaders.detector_providers == [(_CPU,)], (
        f"the detector was asked for {loaders.detector_providers}; with only the CPU"
        " available, select_providers gives ('CPUExecutionProvider',) - a constant"
        " request is AC-6's defect"
    )
    assert loaders.ocr_providers == [(_CPU,)]
    assert [providers for _, providers in loaders.inpainter_loads] == [(_CPU,)]


def test_with_cuda_available_every_loader_is_asked_for_cuda_then_cpu(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
) -> None:
    build_pipeline(weights_dir, translate=False)

    assert loaders.detector_providers == [(_CUDA, _CPU)]
    assert loaders.ocr_providers == [(_CUDA, _CPU)]
    assert [providers for _, providers in loaders.inpainter_loads] == [(_CUDA, _CPU)]


def test_an_unknown_provider_on_the_machine_is_never_requested(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _available(monkeypatch, ["DmlExecutionProvider", "TensorrtExecutionProvider", _CPU])

    build_pipeline(weights_dir, translate=False)

    assert loaders.detector_providers == [(_CPU,)]
    assert loaders.ocr_providers == [(_CPU,)]
    assert [providers for _, providers in loaders.inpainter_loads] == [(_CPU,)]


@pytest.mark.parametrize("translate", [True, False], ids=["translating", "no-translate"])
def test_the_provider_in_use_is_logged_once_at_info_on_the_compose_logger(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    caplog: pytest.LogCaptureFixture,
    translate: bool,
) -> None:
    caplog.set_level("INFO", logger="mangatl.compose")

    build_pipeline(weights_dir, translate=translate)

    assert _provider_lines(caplog) == [(20, f"inference provider: {_CUDA}")], (
        f"mangatl.compose logged {_provider_lines(caplog)}; AC-6 is exactly one INFO"
        " line naming selected_provider(detector)"
    )


def test_the_log_names_the_provider_the_detector_runs_on_not_the_one_requested(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CUDA requested, CPU delivered - MT-002 E2's silent fallback, the case
    the log line exists for. The request is asserted too, so this cannot pass
    by never having asked for CUDA."""
    caplog.set_level("INFO", logger="mangatl.compose")
    loaders.detector_reports = [_CPU]

    build_pipeline(weights_dir, translate=False)

    assert loaders.detector_providers == [(_CUDA, _CPU)], "CUDA was not requested"
    assert _provider_lines(caplog) == [(20, f"inference provider: {_CPU}")], (
        f"mangatl.compose logged {_provider_lines(caplog)}; the detector reported the"
        " CPU, so the honest line names the CPU (AC-6: the provider in use, not the"
        " one requested)"
    )


def test_the_log_follows_the_selection_when_only_the_cpu_is_available(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level("INFO", logger="mangatl.compose")
    _available(monkeypatch, [_CPU])

    build_pipeline(weights_dir, translate=False)

    assert _provider_lines(caplog) == [(20, f"inference provider: {_CPU}")]


def test_the_fake_detector_honours_the_request_unless_told_otherwise() -> None:
    """Fixture check on `_Loaders`: the default fake reports the first provider
    requested, and a set `detector_reports` overrides it. Without this the
    CUDA-requested-CPU-delivered test could be satisfied by a fake that always
    says CPU."""
    stubs = _Loaders()
    honoured = stubs.load_detector(Path("d.onnx"), (_CUDA, _CPU))
    stubs.detector_reports = [_CPU]
    overridden = stubs.load_detector(Path("d.onnx"), (_CUDA, _CPU))

    assert list(honoured.get_providers()) == [_CUDA]
    assert list(overridden.get_providers()) == [_CPU]


# -- MT-024 AC-9: the bundled models directory, the last branch ----------------------
#
# `resolve_models_dir(override, env, bundled=None)`: override, then
# `env[MODELS_ENV]`, then `bundled` if it is a directory, else `ModelsNotFound`
# as before. The two-argument tests above are the "behaves exactly as today"
# half and are unchanged.
#
# RED: the function takes two arguments, so each three-argument call raises
# `TypeError` - the missing parameter C-5 names.


def test_the_resolver_takes_the_bundled_directory_as_an_optional_third_argument() -> None:
    parameters = inspect.signature(resolve_models_dir).parameters

    assert list(parameters) == ["override", "env", "bundled"]
    assert parameters["bundled"].default is None


def test_with_no_flag_and_no_variable_the_bundled_directory_is_used(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()

    assert resolve_models_dir(None, {}, bundled) == bundled
    assert resolve_models_dir(None, {}, bundled=bundled) == bundled


def test_an_empty_variable_falls_through_to_the_bundled_directory(tmp_path: Path) -> None:
    # `MANGATL_MODELS=` is the same statement as unset (see `Path("")` above).
    bundled = tmp_path / "bundled"
    bundled.mkdir()

    assert resolve_models_dir(None, {MODELS_ENV: ""}, bundled) == bundled


def test_the_variable_still_wins_over_the_bundled_directory(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    from_env = tmp_path / "from-the-environment"
    from_env.mkdir()

    assert resolve_models_dir(None, {MODELS_ENV: str(from_env)}, bundled) == from_env


def test_the_override_still_wins_over_the_bundled_directory(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    override = tmp_path / "from-the-flag"
    override.mkdir()

    assert resolve_models_dir(override, {}, bundled) == override


def test_a_variable_naming_no_directory_is_refused_even_with_bundled_weights(
    tmp_path: Path,
) -> None:
    """C-5: env, *then* bundled. A `$MANGATL_MODELS` the user set and mistyped
    is refused by name as today, not silently replaced by the bundled weights."""
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    missing = tmp_path / "typo"

    with pytest.raises(ModelsNotFound) as raised:
        resolve_models_dir(None, {MODELS_ENV: str(missing)}, bundled)

    assert missing.name in str(raised.value)


@pytest.mark.parametrize("case", ["missing", "a file", "none"])
def test_a_bundled_directory_that_is_not_there_is_the_old_refusal(
    tmp_path: Path, case: str
) -> None:
    """A checkout with no fetched weights behaves exactly as today: the same
    exception, the same sentence naming the variable the user could set."""
    bundled: Path | None
    if case == "missing":
        bundled = tmp_path / "packaging" / "models"
    elif case == "a file":
        bundled = tmp_path / "models"
        bundled.write_bytes(b"not a folder")
    else:
        bundled = None

    with pytest.raises(ModelsNotFound) as raised:
        resolve_models_dir(None, {}, bundled)

    assert MODELS_ENV in str(raised.value), str(raised.value)


def test_resolving_the_bundled_directory_does_not_check_the_weights(tmp_path: Path) -> None:
    empty = tmp_path / "bundled"
    empty.mkdir()

    assert resolve_models_dir(None, {}, empty) == empty
    assert list(empty.iterdir()) == []
