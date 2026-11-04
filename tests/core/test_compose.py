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
import dataclasses
import inspect
import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from mangatl.domain.money import Usd
from mangatl.domain.region import RawRegion
from mangatl.ocr.session import DECODER_FILENAME, ENCODER_FILENAME, VOCAB_FILENAME
from mangatl.pipeline.clean_stage import CleanStage
from mangatl.pipeline.detect_stage import DetectStage
from mangatl.pipeline.ocr_stage import OcrStage
from mangatl.pipeline.translate_stage import TranslateStage
from mangatl.translate.client import translate_page

if TYPE_CHECKING:
    from mangatl.translate.provider import Selection

#: `ANTHROPIC_API_KEY`, spelled out rather than read off the SDK. AC-6 is a
#: promise about a machine whose environment does not hold this name, and the
#: name is the SDK's contract with a person typing it into a shell.
_API_KEY_ENV = "ANTHROPIC_API_KEY"

#: MT-078 PO-1's other two key variables and the choice variable, spelled out
#: for the same reason. `keyless` deletes all four.
_PROVIDER_ENV = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "MANGATL_PROVIDER")


def _selection(provider: str, api_key: str = "test-key") -> Selection:
    """`Selection(provider, api_key)`, imported at call time.

    **MT-078, why not a top-level import.** `mangatl.translate.provider` does
    not exist in RED, and a top-level import would take every test in this file
    dark with it - the ~40 MT-036/044/065/024 tests that have nothing to do with
    selection. Imported here, only the tests that build a translating pipeline
    fail, each on the named absence.
    """
    from mangatl.translate.provider import Selection

    return Selection(provider, api_key)  # type: ignore[arg-type]


def _anthropic_if(translate: bool) -> Selection | None:
    """The parametrised MT-065/MT-024 tests' provider: Anthropic when the build
    translates, and nothing when it does not - `translate=False` consults no
    selection (C-2), so the call does not pretend to supply one."""
    return _selection("anthropic") if translate else None


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

    # MT-065 C-7 adds `INPAINTER_FILENAME`, in RUF022's order; MT-111 adds
    # `BatchBinding` and `build_batch_binding`, in the same order; MT-112 adds
    # `build_batch_collector`.
    assert module.__all__ == [
        "DETECTOR_FILENAME",
        "INPAINTER_FILENAME",
        "MODELS_ENV",
        "OCR_SUBDIR",
        "PROVIDER_PREFERENCE",
        "BatchBinding",
        "ModelsNotFound",
        "build_batch_binding",
        "build_batch_collector",
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

    # MT-107 `## Contract` appends `context_mode`, keyword-only and defaulted
    # to "rolling" (asserted at the end): AMENDED IN RED for that story, as
    # MT-078 amended it for `selection`.
    assert list(parameters) == ["models_dir", "translate", "selection", "context_mode"], (
        f"build_pipeline takes {list(parameters)}; MT-107 makes it"
        " (models_dir, *, translate, selection, context_mode)"
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
    # MT-078 C-2, amended in RED for that story: a third parameter, keyword-only
    # for the reason `translate` is, and defaulting to `None` - "select from the
    # environment", which is the window's path (`app.build_stages` passes
    # nothing new, C-5).
    assert parameters["selection"].kind is inspect.Parameter.KEYWORD_ONLY, (
        f"selection is {parameters['selection'].kind}, not keyword-only (MT-078 C-2)"
    )
    assert parameters["selection"].default is None, (
        f"selection defaults to {parameters['selection'].default!r}; MT-078 C-2 is None,"
        " meaning build_pipeline selects from the environment itself"
    )
    assert parameters["context_mode"].kind is inspect.Parameter.KEYWORD_ONLY, (
        f"context_mode is {parameters['context_mode'].kind}, not keyword-only (MT-107)"
    )
    assert parameters["context_mode"].default == "rolling", (
        f"context_mode defaults to {parameters['context_mode'].default!r}; MT-107 keeps"
        " rolling the default until MT-109 moves it"
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
        #: MT-078: what each construction was called with. Recorded rather than
        #: refused, so the existing count assertions still read a count; the
        #: one MT-078 test that pins the call shape reads this.
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        # `*args`/`**kwargs` rather than `()`: C-13 pins `Anthropic()` with no
        # arguments, and this double is here to count constructions, not to
        # re-pin the call shape at a second site. MT-078 AC-6 is the one test
        # that does pin it - a `Selection` now carries a key, and passing it is
        # MT-077's change, not this story's - and it reads `calls`.
        client = f"anthropic-client-{len(self.clients)}"
        self.clients.append(client)
        self.calls.append((args, dict(kwargs)))
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


class _GeminiClientSpy:
    """A stand-in for `google.genai.Client`, at `mangatl.compose.GeminiClient`
    (MT-080 V-8: `from google.genai import Client as GeminiClient`).

    Records each construction's arguments, because AC-6 is a claim about the
    call shape - `api_key=selection.api_key`, explicitly, and nothing else -
    and not only about a count. A separate class from `_ClientSpy` so that a
    client one spy returns can never be mistaken for the other's.
    """

    def __init__(self) -> None:
        self.clients: list[object] = []
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        client = f"gemini-client-{len(self.clients)}"
        self.clients.append(client)
        self.calls.append((args, dict(kwargs)))
        return client


@pytest.fixture
def gemini_client_spy(monkeypatch: pytest.MonkeyPatch) -> _GeminiClientSpy:
    """`raising=False`: the name arrives in GREEN (V-8), as
    `available_providers` did for MT-024. Installed in RED, the gemini arm still
    raises `ProviderUnavailable` - which is the right red."""
    spy = _GeminiClientSpy()
    monkeypatch.setattr("mangatl.compose.GeminiClient", spy, raising=False)
    return spy


@pytest.fixture
def keyless(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ANTHROPIC_API_KEY` out of the environment: AC-6's "no API key" machine.

    A developer with a key exported in their shell must not see different
    behaviour from CI on the one clause this criterion is about.

    **MT-078:** all three key variables and `MANGATL_PROVIDER` go, not only
    Anthropic's - a developer with a Gemini key exported must not see a
    different selection from CI either. A translating build under this fixture
    now has to say its provider (`selection=_selection("anthropic")`), because
    `selection=None` selects from this empty environment and refuses (C-2).
    """
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


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
    stages = build_pipeline(weights_dir, translate=False).stages

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

    **MT-078 (C-2) names the provider; it still omits `translate`.** Under
    `keyless` a `selection=None` build selects from an empty environment and
    refuses, so the provider is explicit - and AC-6's first half is exactly
    this: `selection=anthropic` binds one `Anthropic()`, as today.
    """
    stages = build_pipeline(weights_dir, selection=_selection("anthropic")).stages

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
    stages = build_pipeline(weights_dir, translate=False).stages

    assert len(stages) == 3
    assert _API_KEY_ENV not in os.environ, "the premise of this test was not established"


# -- MT-078 AC-6: the provider decides the translator, before any weight loads --
#
# `build_pipeline(models_dir, *, translate=True, selection=None)` (C-2). An
# `anthropic` selection binds `partial(translate_page, Anthropic())` exactly as
# MT-044 built it; `gemini` and `openai` raise `ProviderUnavailable` naming the
# provider until MT-080/081 register adapters. `selection=None` with
# `translate=True` selects from `os.environ` itself, reading `MANGATL_PROVIDER`
# as the choice. Every refusal happens BEFORE the loaders: "no loader called" is
# asserted on all four of `_Loaders`' records, so a build that loaded the
# weights and then refused - the keyless machine paying seconds of ONNX session
# construction for a one-line error - fails here.
#
# RED: `build_pipeline` has no `selection` keyword (TypeError) and
# `mangatl.translate.provider` does not exist (ModuleNotFoundError).


#: `ProviderUnavailable`'s exact text (C-1/C-2: "naming the provider"). Pinned
#: whole, because "contains 'gemini'" is also satisfied by a message listing
#: every provider.
def _unavailable(provider: str) -> str:
    return f"translation with {provider} is not available yet"


_NO_KEY = (
    "no API key is set: set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY,"
    " or run with --no-translate"
)


def _nothing_loaded(loaders: _Loaders) -> list[str]:
    """The names of every loader `build_pipeline` reached, in `_Loaders`' terms."""
    records = {
        "load_detector": loaders.detector_paths,
        "load_ocr": loaders.ocr_dirs,
        "load_vocab": loaders.vocab_paths,
        "load_inpainter": loaders.inpainter_loads,
    }
    return [name for name, record in records.items() if record]


def _provider_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """Exactly `values` among the four provider variables; the rest deleted."""
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_an_anthropic_selection_binds_translate_page_to_one_bare_anthropic_client(
    weights_dir: Path, loaders: _Loaders, client_spy: _ClientSpy, keyless: None
) -> None:
    """**AC-6, first half.** Four stages (MT-065 AC-7's list), one client, and
    the translator is `partial(translate_page, <that client>)`.

    **`Anthropic()` with no arguments** - MT-044 C-13 unchanged. The
    `Selection` carries a key now, and passing it as `api_key=` is the
    plausible wrong move: it is MT-077's change (story `## Out of scope`), and
    it would make the SDK's own environment lookup - the thing C-13 relies on -
    dead code. `keyless` is in force, so the build cannot be reading the key
    out of the environment either: the selection is the only source, and it is
    ignored for Claude in this story.
    """
    stages = build_pipeline(weights_dir, selection=_selection("anthropic", "sk-SECRET-ant")).stages

    assert [type(stage) for stage in stages] == [
        DetectStage,
        CleanStage,
        OcrStage,
        TranslateStage,
    ]
    assert client_spy.calls == [((), {})], (
        f"Anthropic was constructed as {client_spy.calls}; AC-6 is exactly one"
        " Anthropic() with no arguments (MT-044 C-13) - passing the key is MT-077's"
    )
    (translate_stage,) = [stage for stage in stages if isinstance(stage, TranslateStage)]
    translator = translate_stage.translate
    assert isinstance(translator, partial), f"the translator is {translator!r}, not a partial"
    assert translator.func is translate_page, f"the translator binds {translator.func!r}"
    assert translator.args == (client_spy.clients[0],) and translator.keywords == {}, (
        f"translate_page is bound to {translator.args}/{translator.keywords}, not the one client"
    )


def test_a_gemini_selection_binds_the_gemini_adapter_to_one_client_built_with_its_key(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    gemini_client_spy: _GeminiClientSpy,
    keyless: None,
) -> None:
    """**MT-080 AC-6.** Four stages; the translator is
    `partial(gemini.translate_page, <the one GeminiClient>)`; that client was
    constructed exactly once as `GeminiClient(api_key=<the selection's key>)`
    - keyword, explicit, nothing else - and no `Anthropic` was constructed.

    The key is passed explicitly because the SDK's own lookup reads two
    variables (`GOOGLE_API_KEY` and `GEMINI_API_KEY`) and PO-1 names one.
    `keyless` is in force, so the selection is the only place the key can come
    from.
    """
    stages = build_pipeline(weights_dir, selection=_selection("gemini", "g-SECRET-key")).stages

    from mangatl.translate import gemini

    assert [type(stage) for stage in stages] == [
        DetectStage,
        CleanStage,
        OcrStage,
        TranslateStage,
    ]
    assert gemini_client_spy.calls == [((), {"api_key": "g-SECRET-key"})], (
        f"GeminiClient was constructed as {gemini_client_spy.calls}; AC-6 is exactly"
        " one GeminiClient(api_key=selection.api_key)"
    )
    assert client_spy.clients == [], (
        f"a gemini selection constructed {len(client_spy.clients)} Anthropic client(s)"
    )
    (translate_stage,) = [stage for stage in stages if isinstance(stage, TranslateStage)]
    translator = translate_stage.translate
    assert isinstance(translator, partial), f"the translator is {translator!r}, not a partial"
    assert translator.func is gemini.translate_page, f"the translator binds {translator.func!r}"
    assert translator.args == (gemini_client_spy.clients[0],) and translator.keywords == {}, (
        f"gemini.translate_page is bound to {translator.args}/{translator.keywords}"
    )


#: MT-100 C-1's settled per-page figures, in micro-dollars: read out of the
#: contract, not re-derived from the token profile here.
_GEMINI_PAGE_MICRO = 30_000
_CLAUDE_PAGE_MICRO = 60_000


@pytest.mark.parametrize(
    ("provider", "micro"),
    [("gemini", _GEMINI_PAGE_MICRO), ("anthropic", _CLAUDE_PAGE_MICRO)],
    ids=["gemini-three-cents", "anthropic-six-cents"],
)
def test_the_translate_stage_is_built_with_the_selected_models_page_estimate(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    gemini_client_spy: _GeminiClientSpy,
    keyless: None,
    provider: str,
    micro: int,
) -> None:
    """**MT-100 C-4 / AC-5's binding**: the composition root computes
    `page_estimate(model_for(selection.provider))` once and hands it to the
    translate stage, so the guard a Gemini run consults projects $0.03 a page
    and a Claude run $0.06. A root that passed `BOOTSTRAP_PAGE_ESTIMATE` (or
    nothing, letting `Budget()` default) would show $0.06 for Gemini."""
    stages = build_pipeline(weights_dir, selection=_selection(provider)).stages

    (translate_stage,) = [stage for stage in stages if isinstance(stage, TranslateStage)]
    assert translate_stage.page_estimate == Usd.from_micro(micro), (
        f"a {provider} build's translate stage carries {translate_stage.page_estimate!r}"
        f" a page, not ${micro / 1e6:.2f}"
    )


def test_with_no_selection_a_lone_gemini_key_builds_the_stage_at_three_cents(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    gemini_client_spy: _GeminiClientSpy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MT-100 AC-5 through the window's path (`selection=None`): the user's
    environment - `GEMINI_API_KEY` and nothing else - is the run the story was
    filed for."""
    _provider_env(monkeypatch, GEMINI_API_KEY="g-SECRET-env")

    stages = build_pipeline(weights_dir).stages

    (translate_stage,) = [stage for stage in stages if isinstance(stage, TranslateStage)]
    assert translate_stage.page_estimate == Usd.from_micro(_GEMINI_PAGE_MICRO)


def test_an_anthropic_selection_constructs_no_gemini_client(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    gemini_client_spy: _GeminiClientSpy,
    keyless: None,
) -> None:
    """MT-080 AC-6's control from the other side: a `build_pipeline` that built
    a `GeminiClient` for every translating selection (and then bound Claude)
    passes the test above. Claude's arm is MT-078's, unchanged."""
    build_pipeline(weights_dir, selection=_selection("anthropic", "sk-SECRET-ant"))

    assert gemini_client_spy.calls == []
    assert len(client_spy.clients) == 1


def test_with_no_selection_a_lone_gemini_key_binds_gemini_with_that_key(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    gemini_client_spy: _GeminiClientSpy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MT-080 AC-6 through the window's path (`selection=None`): the one key
    in the environment is `GEMINI_API_KEY`, so gemini is selected and its key
    reaches the constructor - by the selection, not by the SDK's own lookup."""
    _provider_env(monkeypatch, GEMINI_API_KEY="g-SECRET-env")

    stages = build_pipeline(weights_dir).stages

    from mangatl.translate import gemini

    assert gemini_client_spy.calls == [((), {"api_key": "g-SECRET-env"})]
    assert client_spy.clients == []
    (translate_stage,) = [stage for stage in stages if isinstance(stage, TranslateStage)]
    assert isinstance(translate_stage.translate, partial)
    assert translate_stage.translate.func is gemini.translate_page


# MT-080: `gemini` left this list - it has an adapter now, and its arm is
# pinned by `test_a_gemini_selection_binds_the_gemini_adapter_to_one_client...`
# above. `openai` keeps the refusal observed until MT-081.
@pytest.mark.parametrize("provider", ["openai"])
def test_a_provider_with_no_adapter_yet_is_refused_by_name_before_anything_is_built(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    provider: str,
) -> None:
    """**AC-6, second half - the control the first half needs.** A
    `build_pipeline` that ignored the selection and always built `Anthropic()`
    satisfies the test above; here it builds a client (the spy counts it) and
    returns instead of raising. *No client of any kind*, and *before any weight
    is loaded* (C-2: selection precedes `select_providers` and the loaders)."""
    from mangatl.translate.provider import ProviderUnavailable

    with pytest.raises(ProviderUnavailable) as raised:
        build_pipeline(weights_dir, selection=_selection(provider))

    assert str(raised.value) == _unavailable(provider)
    assert client_spy.clients == [], (
        f"a {provider} selection constructed {len(client_spy.clients)} Anthropic client(s)"
    )
    assert _nothing_loaded(loaders) == [], (
        f"a {provider} selection reached {_nothing_loaded(loaders)} before refusing;"
        " C-2 refuses before any weight is loaded"
    )


def test_an_explicit_selection_is_not_second_guessed_by_the_environment(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2: a given `selection` is the decision. The environment here would
    select gemini (and refuse it); the build must not consult it."""
    _provider_env(
        monkeypatch,
        GEMINI_API_KEY="sk-SECRET-gem",
        OPENAI_API_KEY="sk-SECRET-oai",
        MANGATL_PROVIDER="gemini",
    )

    stages = build_pipeline(weights_dir, selection=_selection("anthropic")).stages

    assert len(stages) == 4
    assert len(client_spy.clients) == 1


def test_with_no_selection_the_one_key_in_the_environment_decides(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2, the window's path: `selection=None, translate=True` selects from
    `os.environ`. Exactly `ANTHROPIC_API_KEY` is set, so Claude is bound - the
    explicit form of the lookup `Anthropic()` already did."""
    _provider_env(monkeypatch, ANTHROPIC_API_KEY="sk-SECRET-ant")

    stages = build_pipeline(weights_dir).stages

    assert [type(stage) for stage in stages][-1] is TranslateStage
    assert client_spy.calls == [((), {})]


def test_with_no_selection_mangatl_provider_is_the_choice(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2: `select_provider(os.environ.get(PROVIDER_VAR), os.environ)`. Two
    keys are set, so a build that did not pass the variable through would
    refuse as ambiguous - a different exception - and one that ignored it would
    bind Claude. OpenAI has no adapter, so the variable being read shows as
    `ProviderUnavailable` naming openai, with nothing loaded.

    MT-080: was gemini/`GEMINI_API_KEY`, which has an adapter from this story
    on and would now bind rather than refuse; openai is the provider still
    without one. Same three-way discrimination, one provider along."""
    from mangatl.translate.provider import ProviderUnavailable

    _provider_env(
        monkeypatch,
        ANTHROPIC_API_KEY="sk-SECRET-ant",
        OPENAI_API_KEY="sk-SECRET-oai",
        MANGATL_PROVIDER="openai",
    )

    with pytest.raises(ProviderUnavailable) as raised:
        build_pipeline(weights_dir)

    assert str(raised.value) == _unavailable("openai")
    assert client_spy.clients == []
    assert _nothing_loaded(loaders) == []


def test_with_no_selection_and_no_key_the_build_refuses_before_loading_anything(
    weights_dir: Path, loaders: _Loaders, client_spy: _ClientSpy, keyless: None
) -> None:
    """AC-3 through `build_pipeline` (C-2, and Notes PO-4): a keyless machine
    fails in milliseconds with `NoApiKey`, not after loading the weights - and
    not, as MT-044 left it, on the first page that needs a call."""
    from mangatl.translate.provider import NoApiKey

    with pytest.raises(NoApiKey) as raised:
        build_pipeline(weights_dir, translate=True)

    assert str(raised.value) == _NO_KEY
    assert _nothing_loaded(loaders) == [], (
        f"a keyless build reached {_nothing_loaded(loaders)} before refusing (C-2)"
    )
    assert client_spy.clients == []


def test_the_flagged_build_attempts_no_selection_at_all(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2's first bullet and AC-7's last clause at this seam: `translate=False`
    selects nothing, so an environment that would refuse every way - two keys,
    and a choice that is not a provider - builds the three-stage list."""
    _provider_env(
        monkeypatch,
        ANTHROPIC_API_KEY="sk-SECRET-ant",
        OPENAI_API_KEY="sk-SECRET-oai",
        MANGATL_PROVIDER="claude",
    )

    stages = build_pipeline(weights_dir, translate=False).stages

    assert [type(stage) for stage in stages] == [DetectStage, CleanStage, OcrStage]
    assert client_spy.clients == []


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
    build_pipeline(weights_dir, translate=translate, selection=_anthropic_if(translate))

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
    stages = build_pipeline(
        weights_dir, translate=translate, selection=_anthropic_if(translate)
    ).stages
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

    build_pipeline(weights_dir, selection=_selection("anthropic"))

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

    build_pipeline(weights_dir, translate=translate, selection=_anthropic_if(translate))

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


# -- MT-105: the pipeline carries the glossary prelude ---------------------------
#
# `build_pipeline` returns `Pipeline(stages, prelude)` (`mangatl.pipeline.prelude`,
# the Contract as amended in RED). A `gemini` selection binds
# `glossary_prelude(partial(gemini.propose_glossary, client), model_id,
# listing=glossary_pass_text, max_output_tokens=GLOSSARY_PASS_MAX_OUTPUT_TOKENS)`
# around the **same** client the translator is bound to; `anthropic` and
# `--no-translate` bind none.
#
# The binding is observed by behaviour, not by introspecting a closure: the
# prelude is run over a real project with OCR stored, and the fake client's
# `generate_content` records what it was sent and stops the call there. A
# ceiling exactly at the pass's estimate (AC-5: `estimate_tokens` of the
# listing in, 8,192 out, at $2 / $12 per million) reaches the client; one
# micro-dollar below is refused before it. A root that bound the page cap
# (4,096), another listing, or another model's rates fails one of the two.

#: The rate row, read out (AC-5, settled): micro-dollars per token.
_GEMINI_IN_MICRO = 2
_GEMINI_OUT_MICRO = 12


class _Reached(Exception):
    """Raised by the fake client: the prelude got as far as the call."""


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        raise _Reached


class _FakeGeminiClient:
    def __init__(self) -> None:
        self.models = _FakeModels()


@pytest.fixture
def gemini_client(monkeypatch: pytest.MonkeyPatch) -> list[_FakeGeminiClient]:
    """`mangatl.compose.GeminiClient` replaced by a constructor of fakes that
    can be called; the list is every client constructed."""
    built: list[_FakeGeminiClient] = []

    def construct(*args: object, **kwargs: object) -> _FakeGeminiClient:
        client = _FakeGeminiClient()
        built.append(client)
        return client

    monkeypatch.setattr("mangatl.compose.GeminiClient", construct)
    return built


@dataclass
class _ReadProject:
    project: Any
    run_id: int

    def set_ceiling(self, micro: int) -> None:
        with self.project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))

    def pages(self) -> list[Any]:
        return [self.project.read_lines(page.ordinal) for page in self.project.pages()]


@pytest.fixture
def read_project(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_ReadProject]:
    """Two pages with OCR stored on the first, and a `run` row."""
    from mangatl.domain.line import OcrResult
    from mangatl.store.intake import read_chapter
    from mangatl.store.project import create_project, project_dir_for

    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    (source_dir / "p1.png").write_bytes(png_bytes(30, 20))
    (source_dir / "p2.png").write_bytes(png_bytes(30, 20))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        ring = ((0, 0), (4, 0), (4, 4), (0, 4), (0, 0))
        mask = one_bit_png(8, 8, [(0, 0, 4, 4)])
        project.write_regions(
            0, [RawRegion(polygon=ring, mask=mask, confidence=1.0, kind="bubble")]
        )
        project.write_lines(0, [OcrResult("ケンジ先輩、おはよう")])
        with project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-11-02T09:00:00+00:00"),
            )
            run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
        yield _ReadProject(project, run_id)


def _pass_estimate_micro(pages: Sequence[Any]) -> int:
    from mangatl.domain.glossary import estimate_tokens
    from mangatl.translate.glossary_pass import GLOSSARY_PASS_MAX_OUTPUT_TOKENS, glossary_pass_text

    tokens_in = estimate_tokens(glossary_pass_text(pages))
    return tokens_in * _GEMINI_IN_MICRO + GLOSSARY_PASS_MAX_OUTPUT_TOKENS * _GEMINI_OUT_MICRO


def test_build_pipeline_returns_a_pipeline_of_stages_and_prelude(
    weights_dir: Path, loaders: _Loaders, client_spy: _ClientSpy, keyless: None
) -> None:
    from mangatl.pipeline.prelude import Pipeline  # type: ignore[import-not-found]

    pipeline = build_pipeline(weights_dir, translate=False)

    assert isinstance(pipeline, Pipeline), f"build_pipeline returned {type(pipeline).__name__}"
    assert isinstance(pipeline.stages, tuple)


def test_a_gemini_selection_carries_a_glossary_prelude(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    gemini_client: list[_FakeGeminiClient],
    keyless: None,
) -> None:
    pipeline = build_pipeline(weights_dir, selection=_selection("gemini", "g-SECRET-key"))

    assert pipeline.prelude is not None, "a gemini pipeline carries no prelude"
    assert callable(pipeline.prelude)
    assert len(gemini_client) == 1, (
        f"{len(gemini_client)} GeminiClients were built; the prelude and the"
        " translator share the one client"
    )


@pytest.mark.parametrize(
    ("translate", "provider"),
    [(True, "anthropic"), (False, None)],
    ids=["anthropic", "no-translate"],
)
def test_an_anthropic_or_untranslated_pipeline_carries_no_prelude(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    keyless: None,
    translate: bool,
    provider: str | None,
) -> None:
    """No Claude pass exists (v1 is Gemini-only), and `--no-translate` calls no
    model at all."""
    selection = _selection(provider) if provider is not None else None

    pipeline = build_pipeline(weights_dir, translate=translate, selection=selection)

    assert pipeline.prelude is None, f"a {provider or 'no-translate'} pipeline carries a prelude"


def test_the_gemini_prelude_at_exactly_the_pass_estimate_reaches_the_client_with_the_listing(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    gemini_client: list[_FakeGeminiClient],
    keyless: None,
    read_project: _ReadProject,
) -> None:
    from mangatl.translate.glossary_pass import glossary_pass_text

    pipeline = build_pipeline(weights_dir, selection=_selection("gemini", "g-SECRET-key"))
    read_project.set_ceiling(_pass_estimate_micro(read_project.pages()))

    with pytest.raises(_Reached):
        pipeline.prelude(read_project.project, read_project.run_id, lambda event: None)

    ((sent,),) = [client.models.calls for client in gemini_client]
    assert sent["model"] == "gemini-3.1-pro-preview"
    assert sent["contents"] == [glossary_pass_text(read_project.pages())], (
        f"the pass sent {sent['contents']!r}"
    )


def test_the_gemini_prelude_one_micro_dollar_below_the_estimate_is_refused_before_the_client(
    weights_dir: Path,
    loaders: _Loaders,
    client_spy: _ClientSpy,
    gemini_client: list[_FakeGeminiClient],
    keyless: None,
    read_project: _ReadProject,
) -> None:
    from mangatl.pipeline.stage import BudgetRefused

    pipeline = build_pipeline(weights_dir, selection=_selection("gemini", "g-SECRET-key"))
    read_project.set_ceiling(_pass_estimate_micro(read_project.pages()) - 1)

    with pytest.raises(BudgetRefused):
        pipeline.prelude(read_project.project, read_project.run_id, lambda event: None)

    assert [client.models.calls for client in gemini_client] == [[]], (
        "the client was called although the guard refuses the pass"
    )


# -- MT-107: the context mode reaches the translate stage ----------------------------


def test_the_translate_stage_is_built_with_the_context_mode_it_was_asked_for(
    weights_dir: Path, loaders: _Loaders, client_spy: _ClientSpy, keyless: None
) -> None:
    """MT-107 `## Contract`: `build_pipeline(..., context_mode=...)` hands the
    mode to `pipeline.stages.build_stages`, which hands it to `TranslateStage`
    - so the run `mangatl-run --context neighbours` asked for is the run the
    stage builds its requests for."""
    stages = build_pipeline(
        weights_dir, selection=_selection("anthropic"), context_mode="neighbours"
    ).stages

    (translate_stage,) = [stage for stage in stages if isinstance(stage, TranslateStage)]
    assert translate_stage.context_mode == "neighbours", (
        f"the translate stage was built in {translate_stage.context_mode!r} mode"
    )


def test_with_no_context_mode_the_translate_stage_is_rolling(
    weights_dir: Path, loaders: _Loaders, client_spy: _ClientSpy, keyless: None
) -> None:
    """MT-107 AC-3 at the composition root: the default is unchanged."""
    stages = build_pipeline(weights_dir, selection=_selection("anthropic")).stages

    (translate_stage,) = [stage for stage in stages if isinstance(stage, TranslateStage)]
    assert translate_stage.context_mode == "rolling"


# -- MT-111 AC-10: `build_batch_binding`, the batch half of the composition root --
#
# `pipeline.batch.submit_volume` takes a submitter, a request-size function and
# a page estimate; `compose.build_batch_binding(selection, display_name=...)`
# binds the three for a Gemini selection around ONE `GeminiClient(api_key=...)`
# and returns `None` for Anthropic (no batch). A separate function, because
# `Pipeline`'s fields are pinned exactly (`test_glossary_prelude.py`).
#
# **The submit is observed at the client**, not by spying `submit_batch` at an
# import site: the fake client's `batches.create` records what it was handed,
# and the test compares that against `build_batch_requests` of the same pages
# built here, independently. That pins what reaches the provider - the model,
# the requests and the display name - whether `compose` calls
# `gemini_batch.submit_batch` through the module or through a name it imported.
#
# **The request size is computed here, independently**: `len(model_dump_json(
# exclude_none=True).encode())` of the page's one built request, checked stable
# across two builds of the same page in RED (3,182 bytes for a 40x30 page,
# twice).
#
# Names MT-111 adds are imported inside the tests, so in RED each fails alone.


class _FakeBatchJob:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeBatches:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeBatchJob:
        self.calls.append(kwargs)
        return _FakeBatchJob(f"batches/job-{len(self.calls)}")


class _FakeBatchClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = dict(kwargs)
        self.batches = _FakeBatches()


@pytest.fixture
def batch_client(monkeypatch: pytest.MonkeyPatch) -> list[_FakeBatchClient]:
    """`mangatl.compose.GeminiClient` replaced by a constructor of fakes with a
    recording `batches.create`; the list is every client constructed."""
    built: list[_FakeBatchClient] = []

    def construct(*args: object, **kwargs: object) -> _FakeBatchClient:
        client = _FakeBatchClient(*args, **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr("mangatl.compose.GeminiClient", construct)
    return built


def _build_batch_binding(selection: Selection, display_name: str = "volume-1") -> Any:
    from mangatl.compose import build_batch_binding  # type: ignore[attr-defined]

    return build_batch_binding(selection, display_name=display_name)


def _page_inputs(png_bytes: Callable[..., bytes]) -> list[Any]:
    from mangatl.domain.batch import BatchPageInput  # type: ignore[attr-defined]
    from mangatl.domain.glossary import PromptContext
    from mangatl.domain.line import OcrResult

    return [
        BatchPageInput(
            ordinal=0,
            page_image=png_bytes(40, 30),
            ocr_results=(OcrResult("ケンジ"),),
            context=PromptContext("glossary", "next page"),
        ),
        BatchPageInput(
            ordinal=1,
            page_image=png_bytes(30, 20),
            ocr_results=(OcrResult("先輩"), OcrResult("", ocr_empty=True)),
            context=PromptContext("glossary", "previous page"),
        ),
    ]


def _expected_requests(inputs: Sequence[Any]) -> list[Any]:
    """What `build_batch_requests` builds for these inputs, as `BatchPage`s."""
    from mangatl.translate.gemini_batch import BatchPage, build_batch_requests

    return list(
        build_batch_requests(
            [BatchPage(i.ordinal, i.page_image, i.ocr_results, i.context) for i in inputs]
        )
    )


def test_a_gemini_batch_binding_is_built_around_one_client_with_the_selections_key(
    batch_client: list[_FakeBatchClient], png_bytes: Callable[..., bytes]
) -> None:
    """AC-10: exactly one `GeminiClient(api_key=selection.api_key)`, and
    submitting twice through the binding constructs no second one."""
    binding = _build_batch_binding(_selection("gemini", "gemini-key-1"))
    inputs = _page_inputs(png_bytes)
    binding.submit(inputs[:1])
    binding.submit(inputs[1:])

    assert len(batch_client) == 1, f"{len(batch_client)} GeminiClients were built; AC-10 is one"
    (client,) = batch_client
    assert (client.args, client.kwargs) == ((), {"api_key": "gemini-key-1"})
    assert len(client.batches.calls) == 2, "both submits did not reach the one client"


def test_a_gemini_batch_submit_sends_the_built_requests_under_the_display_name(
    batch_client: list[_FakeBatchClient], png_bytes: Callable[..., bytes]
) -> None:
    """AC-10: `submit(inputs)` turns the inputs into `BatchPage`s, builds them
    with `build_batch_requests` and submits them with `submit_batch(client,
    requests, display_name)` - one `batches.create` of the Gemini model, the
    built requests and the display name - and returns the job's name."""
    from mangatl.translate.gemini import MODEL_ID

    binding = _build_batch_binding(_selection("gemini"), display_name="volume-7")
    inputs = _page_inputs(png_bytes)

    name = binding.submit(inputs)

    assert name == "batches/job-1"
    (client,) = batch_client
    (call,) = client.batches.calls
    assert call["model"] == MODEL_ID
    assert call["src"] == _expected_requests(inputs), "the requests sent are not the built ones"
    assert call["config"].display_name == "volume-7"


def test_a_gemini_request_size_is_the_built_requests_json_length_in_bytes(
    batch_client: list[_FakeBatchClient], png_bytes: Callable[..., bytes]
) -> None:
    """AC-10: `request_size(i)` == `len(InlinedRequest.model_dump_json(
    exclude_none=True).encode())` of the page's one built request, and
    measuring submits nothing."""
    binding = _build_batch_binding(_selection("gemini"))
    inputs = _page_inputs(png_bytes)

    for page_input in inputs:
        (request,) = _expected_requests([page_input])
        expected = len(request.model_dump_json(exclude_none=True).encode())
        measured = binding.request_size(page_input)
        assert measured == expected, (
            f"page {page_input.ordinal}: request_size said {measured};"
            f" the built request is {expected} bytes"
        )
    assert binding.request_size(inputs[0]) != binding.request_size(inputs[1]), (
        "precondition: the two pages' requests differ in size"
    )
    assert batch_client[0].batches.calls == [], "measuring a request submitted it"


def test_a_gemini_batch_binding_estimates_pages_at_the_batch_tier(
    batch_client: list[_FakeBatchClient],
) -> None:
    """AC-10: `page_estimate(model_id, pricing="batch")` - $0.02 for
    gemini-3.1-pro-preview (AC-1), not the interactive $0.03."""
    from mangatl.domain import budget

    binding = _build_batch_binding(_selection("gemini"))

    assert binding.page_estimate == Usd.from_micro(20_000)
    assert binding.page_estimate == budget.page_estimate(
        "gemini-3.1-pro-preview",
        pricing="batch",  # type: ignore[call-arg]
    )


def test_an_anthropic_selection_has_no_batch_binding_and_builds_no_client(
    batch_client: list[_FakeBatchClient], client_spy: _ClientSpy
) -> None:
    """AC-10: no batch for Anthropic - `None`, and no client of either kind."""
    assert _build_batch_binding(_selection("anthropic")) is None
    assert batch_client == [], "an Anthropic selection constructed a GeminiClient"
    assert client_spy.clients == [], "an Anthropic batch binding constructed a client"


def test_a_provider_with_no_adapter_has_no_batch_binding_either(
    batch_client: list[_FakeBatchClient],
) -> None:
    """Contract: any provider but the two is `ProviderUnavailable`, as
    `_translator` does."""
    from mangatl.translate.provider import ProviderUnavailable

    with pytest.raises(ProviderUnavailable):
        _build_batch_binding(_selection("openai"))
    assert batch_client == []


def test_a_batch_binding_is_a_frozen_submit_request_size_and_page_estimate() -> None:
    from mangatl.compose import BatchBinding  # type: ignore[attr-defined]

    assert [f.name for f in dataclasses.fields(BatchBinding)] == [
        "submit",
        "request_size",
        "page_estimate",
    ]
    assert BatchBinding.__dataclass_params__.frozen


# -- MT-112 AC-6: `build_batch_collector`, the collection half --------------------
#
# `pipeline.batch.collect_volume` takes a `BatchCollector`, `(provider_job_id,
# pages) -> BatchAnswer`; `compose.build_batch_collector(selection)` binds it for
# a Gemini selection around ONE `GeminiClient(api_key=...)` and returns `None`
# for Anthropic (no batch). The collector asks `gemini_batch.batch_state` and,
# only on `succeeded`, `gemini_batch.collect_batch`, converting `translate`'s
# `BatchItemError` to `domain`'s `BatchItemFailure`.
#
# **Observed at the client**, as MT-111's binding is: the fake client's
# `batches.get` answers a real `types.BatchJob` built the way
# `test_gemini_batch.py` builds them and records every call, so the test pins
# what reaches the provider and what comes back, not which module function the
# collector calls by which name. The expected `TranslationResult`s are written
# out by hand (usage is `input = P - C`, `output = K + T`, MT-101 D-7).
#
# Names MT-112 adds are imported inside the tests, so in RED each fails alone.

_COLLECT_JOB = "batches/collect-me"


class _FakeCollectBatches:
    """`client.batches` for collection: `get` answers `job` and records each
    call's kwargs; `create` must never be reached."""

    def __init__(self, job: object) -> None:
        self.job = job
        self.got: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> object:
        self.got.append(kwargs)
        return self.job

    def create(self, **kwargs: Any) -> object:
        raise AssertionError("the collector submitted a batch job")


class _FakeCollectClient:
    def __init__(self, job: object, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = dict(kwargs)
        self.batches = _FakeCollectBatches(job)


@dataclass
class _CollectClients:
    """Every client constructed, and the job the next one's `get` answers."""

    job: object = None
    built: list[_FakeCollectClient] = dataclasses.field(default_factory=list)


@pytest.fixture
def collect_client(monkeypatch: pytest.MonkeyPatch) -> _CollectClients:
    clients = _CollectClients()

    def construct(*args: object, **kwargs: object) -> _FakeCollectClient:
        client = _FakeCollectClient(clients.job, *args, **kwargs)
        clients.built.append(client)
        return client

    monkeypatch.setattr("mangatl.compose.GeminiClient", construct)
    return clients


def _build_batch_collector(selection: Selection) -> Any:
    from mangatl.compose import build_batch_collector  # type: ignore[attr-defined]

    return build_batch_collector(selection)


def _collect_pages() -> list[Any]:
    """Three pages as `collect_volume` hands them over (PO-3): no image, no
    context. Page 1 has two regions."""
    from mangatl.domain.batch import BatchPageInput
    from mangatl.domain.glossary import EMPTY_CONTEXT
    from mangatl.domain.line import OcrResult

    return [
        BatchPageInput(0, b"", (OcrResult("ケンジ"),), EMPTY_CONTEXT),
        BatchPageInput(1, b"", (OcrResult("先輩"), OcrResult("待って")), EMPTY_CONTEXT),
        BatchPageInput(2, b"", (OcrResult("走れ"),), EMPTY_CONTEXT),
    ]


def _batch_job(state_name: str, items: Sequence[Any] | None = None) -> Any:
    from google.genai import types

    return types.BatchJob(
        name=_COLLECT_JOB,
        state=getattr(types.JobState, state_name),
        dest=None if items is None else types.BatchJobDestination(inlined_responses=list(items)),
    )


def _inlined(key: str, text: str, usage: tuple[Any, ...], model_version: str | None) -> Any:
    from google.genai import types

    prompt, cached, candidates, thoughts = usage
    return types.InlinedResponse(
        response=types.GenerateContentResponse(
            candidates=[
                types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]))
            ],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=prompt,
                cached_content_token_count=cached,
                candidates_token_count=candidates,
                thoughts_token_count=thoughts,
            ),
            model_version=model_version,
        ),
        metadata={"key": key},
    )


def _succeeded_items() -> list[Any]:
    """Pages 2, 0, 1 - out of order, paired by key. Page 1's item is an error."""
    from google.genai import types

    return [
        _inlined("2", '{"0": "Run!"}', (700, 0, 90, 10), None),
        _inlined("0", '{"0": "Kenji"}', (1000, None, 500, None), "gemini-3.1-pro-preview"),
        types.InlinedResponse(error=types.JobError(code=3, message="quota"), metadata={"key": "1"}),
    ]


def test_a_gemini_collector_is_built_around_one_client_with_the_selections_key(
    collect_client: _CollectClients,
) -> None:
    """AC-6 / Contract: exactly one `GeminiClient(api_key=selection.api_key)`,
    and two collections through it construct no second one."""
    collect_client.job = _batch_job("JOB_STATE_RUNNING")
    collector = _build_batch_collector(_selection("gemini", "gemini-key-2"))

    collector(_COLLECT_JOB, _collect_pages())
    collector(_COLLECT_JOB, _collect_pages())

    assert len(collect_client.built) == 1, (
        f"{len(collect_client.built)} GeminiClients were built; the collector holds one"
    )
    (client,) = collect_client.built
    assert (client.args, client.kwargs) == ((), {"api_key": "gemini-key-2"})


@pytest.mark.parametrize(
    ("state_name", "answered"),
    [
        pytest.param("JOB_STATE_PENDING", "pending", id="pending"),
        pytest.param("JOB_STATE_RUNNING", "pending", id="running-is-pending"),
        pytest.param("JOB_STATE_FAILED", "failed", id="failed"),
        pytest.param("JOB_STATE_CANCELLED", "cancelled", id="cancelled"),
        pytest.param("JOB_STATE_EXPIRED", "expired", id="expired"),
    ],
)
def test_a_gemini_collector_answers_an_unfinished_job_with_its_state(
    collect_client: _CollectClients, state_name: str, answered: str
) -> None:
    """Contract: a job not `succeeded` answers `BatchJobState(state)`, read
    with `batches.get(name=job)` and nothing else."""
    from mangatl.domain.batch import BatchJobState  # type: ignore[attr-defined]

    collect_client.job = _batch_job(state_name)
    collector = _build_batch_collector(_selection("gemini"))

    answer = collector(_COLLECT_JOB, _collect_pages())

    assert answer == BatchJobState(answered)
    (client,) = collect_client.built
    assert client.batches.got, "the collector never asked for the job"
    assert all(call == {"name": _COLLECT_JOB} for call in client.batches.got), client.batches.got


def test_a_gemini_collector_answers_a_succeeded_job_with_every_pages_result_by_ordinal(
    collect_client: _CollectClients,
) -> None:
    """Contract: a `succeeded` job answers `BatchResults` keyed by ordinal - a
    `TranslationResult` per answered page, and the item error as `domain`'s
    `BatchItemFailure(1, "quota")`, never `translate`'s `BatchItemError`."""
    from mangatl.domain.batch import (  # type: ignore[attr-defined]
        BatchItemFailure,
        BatchResults,
    )
    from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
    from mangatl.translate.gemini import MODEL_ID

    collect_client.job = _batch_job("JOB_STATE_SUCCEEDED", _succeeded_items())
    collector = _build_batch_collector(_selection("gemini"))

    answer = collector(_COLLECT_JOB, _collect_pages())

    assert isinstance(answer, BatchResults), f"answered {answer!r}"
    assert dict(answer.results) == {
        0: TranslationResult(
            lines={0: "Kenji"},
            usage=TokenUsage(1000, 500, 0, 0),
            call=CallInfo(f"{_COLLECT_JOB}#0", "gemini-3.1-pro-preview"),
            proposed_terms=(),
        ),
        1: BatchItemFailure(1, "quota"),
        2: TranslationResult(
            lines={0: "Run!"},
            usage=TokenUsage(700, 100, 0, 0),
            call=CallInfo(f"{_COLLECT_JOB}#2", MODEL_ID),
            proposed_terms=(),
        ),
    }
    assert type(answer.results[1]) is BatchItemFailure
    (client,) = collect_client.built
    assert all(call == {"name": _COLLECT_JOB} for call in client.batches.got), client.batches.got


def test_an_anthropic_selection_has_no_collector_and_builds_no_client(
    collect_client: _CollectClients, client_spy: _ClientSpy
) -> None:
    """Contract: no batch for Anthropic - `None`, and no client of either kind."""
    assert _build_batch_collector(_selection("anthropic")) is None
    assert collect_client.built == [], "an Anthropic selection constructed a GeminiClient"
    assert client_spy.clients == [], "an Anthropic collector constructed a client"


def test_a_provider_with_no_adapter_has_no_collector_either(
    collect_client: _CollectClients,
) -> None:
    from mangatl.translate.provider import ProviderUnavailable

    with pytest.raises(ProviderUnavailable):
        _build_batch_collector(_selection("openai"))
    assert collect_client.built == []
