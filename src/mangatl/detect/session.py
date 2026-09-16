"""The detector's ONNX session: load the graph, run it, report the provider.

**This module owns no arithmetic** (MT-007 C-1). It is only ever exercised by
the `integration` gate, which needs a GPU and the gitignored weights and so never
runs on CI - a letterbox or a decode written here would be a letterbox no
required gate reads. Everything that is arithmetic lives in
`mangatl.detect.postprocess`, which `unit` and `coverage` both read.

**`ort.preload_dlls(...)` before the first `InferenceSession` is mandatory, not
tuning.** MT-002 E2 measured three configurations on this machine: the bare
`onnxruntime-gpu` wheel and the `[cuda,cudnn]` wheel both produced a session
reporting `['CPUExecutionProvider']` - 40-50 ms against 23 ms - *without
raising*, and only the preload made CUDA load. Requesting CUDA is not a
guarantee of getting it and no exception is available as a signal.

**`selected_provider` reads `session.get_providers()` and never
`get_available_providers()`.** The latter reports which provider libraries were
compiled into the wheel, not which ones loaded: MT-002 E1 measured it
advertising `CUDAExecutionProvider` in every configuration tested, including the
two where CUDA did not work at all. Re-verified in MT-007 RED, and again in
GREEN on this machine: identical output before and after the preload.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import numpy as np
import onnxruntime as ort
from numpy.typing import NDArray

__all__ = [
    "MODEL_INPUT_SIDE",
    "PAD_VALUE",
    "DetectorSession",
    "RawDetectorOutput",
    "load_detector",
    "selected_provider",
]

#: The side of the square canvas the graph takes: input `images` is
#: `[1, 3, 1024, 1024]` (measured against this `.onnx`, MT-002 E3).
MODEL_INPUT_SIDE: int = 1024

#: The grey the letterbox pads with. Upstream's value, kept so that the canvas
#: this code builds is the one the weights were trained against.
PAD_VALUE: int = 114

#: The graph's outputs, in the order it declares them.
_OUTPUT_NAMES = ("blk", "seg", "det")

#: The graph's single input.
_INPUT_NAME = "images"


@dataclass(frozen=True)
class RawDetectorOutput:
    """The three heads, exactly as the graph returns them, in canvas coordinates.

    `blk` is the box head, `(1, 64512, 7)` of `cx cy w h obj cls0 cls1`; `seg` is
    the text mask, `(1, 1, 1024, 1024)` in [0, 1]; `det` is `(1, 2, 1024, 1024)`.
    Nothing in MT-007 reads `det` - it is carried so AC-7 can assert the graph's
    shape through this type rather than around it, and MT-019 may want it
    (amendment A-1).
    """

    blk: NDArray[np.float32]
    seg: NDArray[np.float32]
    det: NDArray[np.float32]


class DetectorSession(Protocol):
    """What the rest of the pipeline needs of a detector session.

    A Protocol so that `tests/integration` can wrap a real session in a proxy
    and so that `postprocess` never sees an `InferenceSession`. `get_providers`
    is declared because `selected_provider` calls it (amendment A-2).
    """

    def run(self, canvas: NDArray[np.float32]) -> RawDetectorOutput: ...

    def get_providers(self) -> Sequence[str]: ...


class _OnnxDetectorSession:
    """A `DetectorSession` backed by one `onnxruntime.InferenceSession`."""

    def __init__(self, session: ort.InferenceSession) -> None:
        self._session = session

    def run(self, canvas: NDArray[np.float32]) -> RawDetectorOutput:
        blk, seg, det = self._session.run(list(_OUTPUT_NAMES), {_INPUT_NAME: canvas})
        return RawDetectorOutput(
            blk=cast(NDArray[np.float32], blk),
            seg=cast(NDArray[np.float32], seg),
            det=cast(NDArray[np.float32], det),
        )

    def get_providers(self) -> Sequence[str]:
        return cast(Sequence[str], self._session.get_providers())


def load_detector(model_path: Path, providers: Sequence[str]) -> DetectorSession:
    """Load the detector graph, asking for `providers` in order of preference.

    Calls `ort.preload_dlls(cuda=True, cudnn=True, msvc=True)` first. That call
    is process-global and idempotent, so making it here - rather than at import -
    keeps it next to the reason it exists, and every session in the process gets
    it because no session is built any other way.

    It does **not** raise when CUDA is unavailable: onnxruntime falls back to CPU
    silently, which is why the honest answer is `selected_provider(session)`
    after the fact rather than the request made here.
    """
    ort.preload_dlls(cuda=True, cudnn=True, msvc=True)
    return _OnnxDetectorSession(ort.InferenceSession(str(model_path), providers=list(providers)))


def selected_provider(session: DetectorSession) -> str:
    """The provider the session **actually** runs on: `get_providers()[0]`.

    Never `get_available_providers()`. See the module docstring: that call is
    dishonest by measurement, not by reputation.
    """
    return str(session.get_providers()[0])
