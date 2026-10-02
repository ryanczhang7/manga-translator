"""The inpainter's ONNX session: load LaMa, run it, report the provider (MT-019 C-2).

**This module owns no arithmetic**, exactly as `mangatl.detect.session` owns
none. It is only ever exercised by the `integration` gate, which needs a GPU and
the gitignored weights and so never runs on CI. Every normalisation, transpose,
resize and rounding lives in `mangatl.clean.inpaint`, which `unit` and
`coverage` both read.

**The calling convention, settled (C-2; MT-002 E3/E4, output scale measured by
the Lead PO on 2026-10-02):**

* `image`: `float32 (1, 3, 512, 512)`, **RGB**, values in `[0.0, 1.0]`;
* `mask`: `float32 (1, 1, 512, 512)`, exactly `0.0` or `1.0`, **`1.0` = hole**;
* return: `float32 (1, 3, 512, 512)`, RGB, **in 8-bit scale `[0, 255]`**. The
  export composites internally, so outside the hole the output is `255 * image`.

**`ort.preload_dlls(...)` before the first `InferenceSession` is mandatory**
(MT-002 E2): without it onnxruntime falls back to CPU silently. And
`selected_provider` reads `get_providers()`, never `get_available_providers()`
(MT-002 E1) - see `mangatl.detect.session` for the measurements.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

import numpy as np
import onnxruntime as ort
from numpy.typing import NDArray

__all__ = [
    "MODEL_INPUT_SIDE",
    "InpaintSession",
    "load_inpainter",
    "selected_provider",
]

#: `lama_fp32.onnx` takes a fixed input: image `[b, 3, 512, 512]`, mask
#: `[b, 1, 512, 512]` (MT-002 E3).
MODEL_INPUT_SIDE: int = 512

_IMAGE_INPUT = "image"
_MASK_INPUT = "mask"
_OUTPUT = "output"


class InpaintSession(Protocol):
    """What `clean_page` needs of an inpainter. A Protocol so `tests/core` can
    hand in a recording fake and `inpaint` never sees an `InferenceSession`."""

    def run(self, image: NDArray[np.float32], mask: NDArray[np.float32]) -> NDArray[np.float32]: ...

    def get_providers(self) -> Sequence[str]: ...


class _OnnxInpaintSession:
    """An `InpaintSession` backed by one `onnxruntime.InferenceSession`."""

    def __init__(self, session: ort.InferenceSession) -> None:
        self._session = session

    def run(self, image: NDArray[np.float32], mask: NDArray[np.float32]) -> NDArray[np.float32]:
        (output,) = self._session.run([_OUTPUT], {_IMAGE_INPUT: image, _MASK_INPUT: mask})
        return cast(NDArray[np.float32], output)

    def get_providers(self) -> Sequence[str]:
        return cast(Sequence[str], self._session.get_providers())


def load_inpainter(model_path: Path, providers: Sequence[str]) -> InpaintSession:
    """Load the inpainting graph, asking for `providers` in order of preference.

    Calls `ort.preload_dlls(cuda=True, cudnn=True, msvc=True)` first (process-
    global and idempotent). It does not raise when CUDA is unavailable; ask
    `selected_provider(session)` afterwards.
    """
    ort.preload_dlls(cuda=True, cudnn=True, msvc=True)
    return _OnnxInpaintSession(ort.InferenceSession(str(model_path), providers=list(providers)))


def selected_provider(session: InpaintSession) -> str:
    """The provider the session **actually** runs on: `get_providers()[0]`."""
    return str(session.get_providers()[0])
