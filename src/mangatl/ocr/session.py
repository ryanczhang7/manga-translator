"""The OCR export's two ONNX graphs: load them, run them, report the provider.

**This module owns no arithmetic**, for the reason `detect/session.py` states in
its own docstring and MT-010 C-4 restates: it is only ever exercised by the
`integration` gate, which needs a GPU and the gitignored weights and so never
runs on CI. A generation loop or a normalisation written here would be one no
required gate reads. The loop is `ocr.generate`, the pre-processing is
`ocr.preprocess`, the de-tokenisation is `ocr.decode`, and all three are driven
by fakes in `tests/core`.

**The export is encoder + decoder, two graphs, with no KV cache** (MT-002 E3,
re-measured in RED against the shipped files):

    encoder_model.onnx  pixel_values [batch, 3, 224, 224]
                        -> last_hidden_state [batch, 197, 768]
    decoder_model.onnx  input_ids [batch, seq] int64
                        + encoder_hidden_states [batch, seq, 768]
                        -> logits [batch, seq, 6144]

So `decode_step` re-runs the decoder over the **whole** prefix and returns the
last row - the logits for the next token. That is what "no KV cache" costs, and
it is why `generate.MAX_NEW_TOKENS` is a cap worth having.

**`ort.preload_dlls(...)` before the first `InferenceSession` is mandatory, not
tuning**, and **`get_providers()` rather than `get_available_providers()`** -
both measured in MT-002 E1/E2 and both re-verified by MT-007. The latter reports
which provider libraries were compiled into the wheel, not which ones loaded, and
advertises CUDA in configurations where CUDA does not work at all; a silent fall
back to CPU turns 48 ms a crop into 158 ms with no exception anywhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

import numpy as np
import onnxruntime as ort
from numpy.typing import NDArray

__all__ = [
    "DECODER_FILENAME",
    "ENCODER_FILENAME",
    "VOCAB_FILENAME",
    "OcrSession",
    "load_ocr",
    "load_vocab",
    "selected_provider",
]

#: The three files `load_ocr` expects side by side in one directory. The names
#: are the export's own.
ENCODER_FILENAME: str = "encoder_model.onnx"
DECODER_FILENAME: str = "decoder_model.onnx"
VOCAB_FILENAME: str = "vocab.txt"

_ENCODER_INPUT = "pixel_values"
_DECODER_TOKENS_INPUT = "input_ids"
_DECODER_HIDDEN_INPUT = "encoder_hidden_states"


class OcrSession(Protocol):
    """What the rest of the pipeline needs of an OCR session.

    A Protocol so that `tests/core` can drive `ocr.page` with a fake that decides
    what to emit from the hidden state it is handed - which is the only way the
    threading of *this* region's encoder output into *this* region's decode can
    be asserted without a GPU.
    """

    def encode(self, pixels: NDArray[np.float32]) -> NDArray[np.float32]: ...

    def decode_step(
        self, encoder_hidden: NDArray[np.float32], tokens: Sequence[int]
    ) -> NDArray[np.float32]: ...

    def get_providers(self) -> Sequence[str]: ...


class _OnnxOcrSession:
    """An `OcrSession` backed by the export's two `InferenceSession`s."""

    def __init__(self, encoder: ort.InferenceSession, decoder: ort.InferenceSession) -> None:
        self._encoder = encoder
        self._decoder = decoder

    def encode(self, pixels: NDArray[np.float32]) -> NDArray[np.float32]:
        hidden = self._encoder.run(None, {_ENCODER_INPUT: pixels})[0]
        return cast(NDArray[np.float32], hidden)

    def decode_step(
        self, encoder_hidden: NDArray[np.float32], tokens: Sequence[int]
    ) -> NDArray[np.float32]:
        """The logits for the token **after** `tokens`, as one row of `(6144,)`.

        `logits[0, -1]`: the graph returns a row per position of the prefix and
        only the last one is about the next token. `int64` is the declared dtype
        of `input_ids` and onnxruntime raises on anything else rather than
        casting.
        """
        logits = self._decoder.run(
            None,
            {
                _DECODER_TOKENS_INPUT: np.asarray([list(tokens)], dtype=np.int64),
                _DECODER_HIDDEN_INPUT: encoder_hidden,
            },
        )[0]
        return cast(NDArray[np.float32], logits[0, -1])

    def get_providers(self) -> Sequence[str]:
        return cast(Sequence[str], self._encoder.get_providers())


def load_ocr(model_dir: Path, providers: Sequence[str]) -> OcrSession:
    """Load both graphs out of `model_dir`, asking for `providers` in order.

    A directory rather than two paths, because the two files are one export and
    pairing an encoder with another export's decoder is not a configuration
    anyone wants to be able to express.

    `ort.preload_dlls(cuda=True, cudnn=True, msvc=True)` first, for the reason
    `detect.session.load_detector` gives: without it the session reports
    `['CPUExecutionProvider']` **without raising**. Requesting CUDA is not a
    guarantee of getting it, which is why the honest answer is
    `selected_provider(session)` after the fact.
    """
    ort.preload_dlls(cuda=True, cudnn=True, msvc=True)
    requested = list(providers)
    return _OnnxOcrSession(
        ort.InferenceSession(str(model_dir / ENCODER_FILENAME), providers=requested),
        ort.InferenceSession(str(model_dir / DECODER_FILENAME), providers=requested),
    )


def load_vocab(vocab_path: Path) -> Mapping[int, str]:
    """`vocab.txt` as id -> token: one entry per line, in file order.

    The file is 6144 lines, matching `logits [batch, seq, 6144]` and
    `config.json`'s `decoder.vocab_size`. `splitlines()` rather than iterating
    the handle, so a trailing newline does not become a 6145th, empty token whose
    id no logit ever names.
    """
    return dict(enumerate(vocab_path.read_text(encoding="utf-8").splitlines()))


def selected_provider(session: OcrSession) -> str:
    """The provider the session **actually** runs on: `get_providers()[0]`.

    Never `get_available_providers()`. See the module docstring: that call is
    dishonest by measurement, not by reputation.
    """
    return str(session.get_providers()[0])
