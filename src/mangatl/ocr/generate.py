"""Greedy decoding: the loop, its stop condition, and its length cap.

**This loop is here rather than in `session.py`, and that is a rule with a
measurement behind it** (MT-010 C-4). The `manga-ocr` export is encoder +
decoder, two graphs, **no KV cache**, so transcription is autoregressive: the
decoder is re-run over the whole prefix at every step. `detect/session.py`'s
docstring states the rule that follows - a module only the `integration` gate
exercises is a module no required gate reads, because `integration` needs a GPU
and gitignored weights and never runs on CI. So the arithmetic lives here, behind
a `DecoderStep` callable that `tests/core` drives with a hand-built logit table,
and the `unit`, `coverage` and `mutation` gates all read it.

That is also why this module imports **nothing** from `ocr.session`, not even
under `TYPE_CHECKING`: such an import is still an import-linter edge and would
still drag `onnxruntime` behind it. `tests/core/test_ocr_generate.py` reads this
module's own AST and says so by name, so the constraint fails in `unit` before
`lint` sees it.

**`MAX_NEW_TOKENS` is a termination guarantee, not tuning.** This export exposes
no score and has no "no text here" output (MT-002 E5 Test 3), so a decoder that
never emits EOS is a hung run with no error anywhere rather than a bad
transcription.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

__all__ = [
    "BOS_TOKEN_ID",
    "EOS_TOKEN_ID",
    "MAX_NEW_TOKENS",
    "DecoderStep",
    "greedy_generate",
]

#: `[CLS]`, id 2. The export's `generation_config.json` calls it
#: `decoder_start_token_id` and `vocab.txt`'s third line is `[CLS]`; the two
#: agree, and `spikes/MT-002/ocr.py` used exactly this.
BOS_TOKEN_ID: int = 2

#: `[SEP]`, id 3 - `generation_config.json`'s `eos_token_id`.
EOS_TOKEN_ID: int = 3

#: The cap. Bounded below by 64, which decoded every one of the 12 oracle and 9
#: page transcriptions MT-002 E5 recorded (the longest of them is 22 characters),
#: and above by the export's own `generation_config.json` `max_length: 300`.
#: Twice the measured-sufficient value: truncation is a *wrong transcription*
#: that nothing reports, while the cost of a larger cap is paid only by a decoder
#: that has already failed to terminate.
MAX_NEW_TOKENS: int = 128

#: The prefix emitted so far, in; the logits for the **next** token, out, as one
#: row of shape `(vocab,)`. The narrowest type this module can name - stdlib and
#: numpy - which is what keeps `onnxruntime` out of it. A caller binds one crop's
#: encoder hidden state into a `DecoderStep` at the call site
#: (`ocr.page.transcribe_page_regions`).
#:
#: Spelled `np.ndarray[...]` long-hand rather than as `NDArray[np.float32]`, and
#: that is not style. `NDArray` is numpy's own parametrised alias, so
#: `typing.get_origin(NDArray[np.float32])` is `NDArray` and not `np.ndarray`
#: (measured, numpy 2.5.3) - and this alias is *introspected* by
#: `tests/core/test_ocr_generate.py`, which asks what it returns. The two are the
#: same type to mypy; only one of them answers that question.
DecoderStep = Callable[[Sequence[int]], np.ndarray[Any, np.dtype[np.float32]]]


def greedy_generate(step: DecoderStep, *, max_new_tokens: int = MAX_NEW_TOKENS) -> tuple[int, ...]:
    """Decode greedily until `step` emits EOS, or until `max_new_tokens`.

    Returns the **generated** tokens: neither `BOS_TOKEN_ID` nor `EOS_TOKEN_ID`
    is in the tuple. That is what lets "the model emitted nothing" be an empty
    tuple, which is the distinction `domain.line.OcrResult.ocr_empty` rests on
    (MT-010 C-5) - and `decode` would strip both as special tokens anyway, so
    returning them would carry no information and destroy that one.

    `step` is handed the whole prefix, seeded with `BOS_TOKEN_ID`, because with no
    KV cache the prefix *is* the loop's state. It is called once per emitted
    token plus once for the call that returns EOS, and never past the stop: each
    call is a full decoder pass over the whole prefix, so running on and slicing
    afterwards would pay for passes nobody reads.
    """
    prefix = [BOS_TOKEN_ID]
    generated: list[int] = []
    for _ in range(max_new_tokens):
        next_token = int(np.argmax(step(tuple(prefix))))
        if next_token == EOS_TOKEN_ID:
            break
        generated.append(next_token)
        prefix.append(next_token)
    return tuple(generated)
