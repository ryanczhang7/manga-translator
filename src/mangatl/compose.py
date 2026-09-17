"""The composition root: the one module that builds real ONNX sessions.

**MT-036 C-2, and `architecture.md` §3's "composition-root exception to rule
5".** Rule 5 confines the inference runtime to `detect`, `ocr` and `clean`; it
cannot also forbid *constructing* it, because something has to. That something
is this module and `mangatl.cli`, which imports it, and the exemption is exactly
those two names in one contract - `mangatl.app`, `domain`, `store`, `translate`,
`typeset`, `pipeline`, `bench` and `ui` are still confined, so §2's adapter split
is untouched and `pipeline` still may not reach `mangatl.detect` or `mangatl.ocr`.

The module is deliberately in two halves:

- **`resolve_models_dir` is pure and takes the environment as an argument.**
  That is what puts every branch of PO-4's resolution order - the flag, then the
  variable, then a sentence rather than a stack trace - inside `tests/core`,
  which three required gates read, with no weights anywhere on the machine.
- **`build_pipeline` does the loading**, and by §2 it is not coverable by a
  required gate and is not expected to be. Its smoke test is AC-4 in
  `tests/integration`, where a real `mangatl-run` over a real chapter is the
  only thing that can show the composition is wired correctly.

**This module imports `onnxruntime` at import time**, transitively through
`mangatl.detect.page` and `mangatl.ocr.page`. That is accepted rather than
overlooked (PO-9): deferring the imports into `build_pipeline` would not avoid
the rule-5 exemption, because import-linter reports function-body imports too.
Importing the runtime is not loading a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from pathlib import Path

from mangatl.detect.page import detect_page_regions
from mangatl.detect.session import load_detector
from mangatl.ocr.page import transcribe_page_regions
from mangatl.ocr.session import VOCAB_FILENAME, load_ocr, load_vocab
from mangatl.pipeline.stage import Stage
from mangatl.pipeline.stages import build_stages

__all__ = [
    "DETECTOR_FILENAME",
    "MODELS_ENV",
    "OCR_SUBDIR",
    "PROVIDER_PREFERENCE",
    "ModelsNotFound",
    "build_pipeline",
    "resolve_models_dir",
]

#: The environment variable PO-4 told the user about, on 2026-09-17. A promise
#: to a person typing it into a shell, so it is spelled out here and nowhere
#: else. MT-024's AC-7 replaces the *last* branch of the resolution order with a
#: bundled directory; this variable is not thrown away by that.
MODELS_ENV: str = "MANGATL_MODELS"

#: The detector graph, directly under the models directory (C-6).
DETECTOR_FILENAME: str = "comic-text-detector.onnx"

#: The subdirectory holding the OCR export. A *directory* rather than three
#: paths, because `load_ocr` takes one: the encoder and the decoder are one
#: export, and pairing one export's encoder with another's decoder is not a
#: configuration anyone wants to be able to express (C-6). The three filenames
#: inside it are `mangatl.ocr.session`'s own constants, referenced and never
#: re-spelled.
OCR_SUBDIR: str = "manga-ocr"

#: The interim provider preference: CUDA, then CPU.
#:
#: **Not** CUDA/DirectML/CPU. D3's correction in `architecture.md` records that
#: the chain is a packaging choice between mutually exclusive wheels rather than
#: a runtime fallback, and this project installs `onnxruntime-gpu[cuda,cudnn]`.
#: MT-024 owns the real `select_providers`; this constant is the interim and is
#: the whole of provider selection until that story lands. Requesting CUDA is
#: not getting it - `detect.session.selected_provider` is the honest answer,
#: after the fact.
PROVIDER_PREFERENCE: tuple[str, ...] = ("CUDAExecutionProvider", "CPUExecutionProvider")


class ModelsNotFound(Exception):
    """No models directory was given, or it does not hold what is expected.

    An exception a caller can catch by name: `cli.main` turns it into one
    sentence on stderr and exit 1, exactly as it does `NoPagesFound`. A bare
    `RuntimeError` would either be caught too broadly or reach the user as a
    traceback, which is a bug report aimed at the wrong person.
    """


def resolve_models_dir(override: Path | None, env: Mapping[str, str]) -> Path:
    """Where the weights are: `override` first, then `env[MODELS_ENV]`.

    **No silent default** (PO-4). A default pointing at a missing directory
    produces an onnxruntime error about a missing file instead of a sentence
    naming the two things the user can do about it, so the third branch is a
    refusal rather than a guess.

    The environment arrives as an argument rather than being read out of
    `os.environ` here, which is what makes every branch below testable without
    `monkeypatch.setenv` and keeps this function inside the `coverage` gate's
    reach. `cli.main` passes the real `os.environ`.

    It does **not** check that the weights themselves are present: that is
    `build_pipeline`'s business, and a resolver that stats model files cannot be
    tested without them.
    """
    if override is not None:
        return _directory(override)
    value = env.get(MODELS_ENV)
    if not value:
        # An unset variable and an empty one are the same statement. `Path("")`
        # is `Path(".")` and `Path(".").is_dir()` is `True`, so a resolver that
        # asked only whether the variable was present would answer "the
        # directory the user happened to be standing in" for `MANGATL_MODELS=`.
        raise ModelsNotFound(
            "no models directory: pass --models PATH or set"
            f" ${MODELS_ENV} to the directory holding the model weights"
        )
    return _directory(Path(value))


def build_pipeline(models_dir: Path) -> tuple[Stage, ...]:
    """Load the weights out of `models_dir` and bind them into the stage list.

    The one function in the project that may construct an inference session, and
    the reason this module exists. Everything it does is wiring: the sessions are
    `detect`'s and `ocr`'s, the binding is `functools.partial`, and the order of
    the stages is `pipeline.stages.build_stages`'s. Nothing here decides anything
    a stage decides.

    Layout is C-6: the detector directly under `models_dir`, the OCR export in
    `OCR_SUBDIR`.
    """
    ocr_dir = models_dir / OCR_SUBDIR
    detector = load_detector(models_dir / DETECTOR_FILENAME, PROVIDER_PREFERENCE)
    ocr = load_ocr(ocr_dir, PROVIDER_PREFERENCE)
    vocab = load_vocab(ocr_dir / VOCAB_FILENAME)
    return build_stages(
        partial(detect_page_regions, detector),
        partial(transcribe_page_regions, ocr, vocab),
    )


def _directory(path: Path) -> Path:
    """`path` if it is a directory, or a `ModelsNotFound` that names it."""
    if not path.is_dir():
        raise ModelsNotFound(f"not a models directory: {path}")
    return path
