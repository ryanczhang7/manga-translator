"""`mangatl.ocr.generate`: greedy decoding, its stop condition and its length cap.

Covers **AC-8** in full, and C-4's structural claim that this loop is pure and
lives outside `session.py`.

**Why this file can exist at all.** The `manga-ocr` export is encoder + decoder,
two graphs, **no KV cache** (MT-002 E3, re-measured in RED against the shipped
`decoder_model.onnx`: `input_ids [batch, decoder_sequence_length] int64` and
`encoder_hidden_states [batch, encoder_sequence_length, 768]` in, `logits
[batch, decoder_sequence_length, 6144]` out). So transcription is an
autoregressive loop with an EOS test and a length cap, and C-4 puts that loop
behind a `DecoderStep` callable rather than inside the session - because
`detect/session.py`'s own docstring says a module only the `integration` gate
exercises is a module no required gate reads, and `integration` is `optional`
and never runs on CI. Driven by a hand-built logit table here, the loop is read
by `unit`, `coverage` and `mutation`.

**`MAX_NEW_TOKENS` is a termination guarantee, not tuning** (C-4). This export
exposes no score and has no "no text here" output (MT-002 E5 Test 3), so a
decoder that fails to emit EOS is a hung run with no error anywhere - not a bad
transcription. `test_a_step_that_never_emits_eos_stops_at_the_cap_rather_than_hanging`
is the assertion that a crash is preferred to a hang, and it is the reason the
cap is a criterion rather than a constant.

**The fake steps ignore `encoder_hidden` entirely**, because `greedy_generate`
never sees one: C-1 binds it into the callable at the call site. The threading of
a *particular* region's hidden state through to its own decode is AC-5's, and is
asserted in `test_ocr_page.py`.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. The most expensive test below runs the loop
`MAX_NEW_TOKENS` times over a 6144-wide float32 vector - measured in RED, at the
export's own `max_length` of 300 that is 7.4 MB of allocation and under 20 ms.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import get_args, get_origin

import numpy as np
import pytest
from numpy.typing import NDArray

from mangatl.ocr.generate import (
    BOS_TOKEN_ID,
    EOS_TOKEN_ID,
    MAX_NEW_TOKENS,
    DecoderStep,
    greedy_generate,
)

#: The decoder's real output width, measured in RED from `decoder_model.onnx`
#: (`logits [batch, decoder_sequence_length, 6144]`) and independently from
#: `config.json` (`decoder.vocab_size: 6144`) and from the 6144 lines of
#: `vocab.txt`. The fakes below build logits of exactly this width so that a
#: shape assumption in `greedy_generate` meets the real number here rather than
#: in `tests/integration/`.
_VOCAB = 6144


class _TableStep:
    """A `DecoderStep` that emits a fixed token sequence, then EOS forever.

    Records the prefix it was handed at every call, because AC-8 is as much a
    claim about *what the loop feeds back* as about what it returns: a loop that
    never appended its own output would still stop at EOS and still return the
    right length against a step that ignores its argument.

    The logits are one-hot at the wanted id with every other entry at a large
    negative value, so `argmax` is unambiguous and a tie-breaking rule cannot
    make this pass by accident.
    """

    def __init__(self, emits: Sequence[int]) -> None:
        self._emits = tuple(emits)
        self.prefixes: list[tuple[int, ...]] = []

    @property
    def calls(self) -> int:
        return len(self.prefixes)

    def __call__(self, tokens: Sequence[int]) -> NDArray[np.float32]:
        self.prefixes.append(tuple(int(t) for t in tokens))
        position = len(self.prefixes) - 1
        wanted = self._emits[position] if position < len(self._emits) else EOS_TOKEN_ID
        logits = np.full(_VOCAB, -1e4, dtype=np.float32)
        logits[wanted] = 1e4
        return logits


class _NeverStops:
    """A `DecoderStep` that emits the same non-EOS token forever.

    The pathological decoder C-4 names: with no cap, this loop does not
    terminate, and because this export exposes no score there is nothing else
    that could notice.
    """

    def __init__(self, token: int = 100) -> None:
        self._token = token
        self.calls = 0

    def __call__(self, tokens: Sequence[int]) -> NDArray[np.float32]:
        self.calls += 1
        logits = np.full(_VOCAB, -1e4, dtype=np.float32)
        logits[self._token] = 1e4
        return logits


# -- the module's shape --------------------------------------------------------


def test_the_special_token_ids_are_the_exports_own_generation_config() -> None:
    """C-1's `BOS_TOKEN_ID` and `EOS_TOKEN_ID`, read out of the export rather
    than inferred.

    MEASURED IN RED from two files that agree, neither of which is an inference:

    * `spikes/MT-002/models/manga-ocr-base-ONNX/generation_config.json` -
      `"decoder_start_token_id": 2`, `"eos_token_id": 3`, `"pad_token_id": 0`;
    * `spikes/MT-002/models/manga-ocr-base/vocab.txt` - line 1 `[PAD]`, line 2
      `[UNK]`, line 3 `[CLS]`, line 4 `[SEP]`, i.e. ids 0, 1, 2, 3.

    So the sequence starts at `[CLS]` and ends at `[SEP]`, and `spikes/MT-002/ocr.py`
    - the script that scored 10/12 against the upstream author's ground truth -
    used exactly `START, EOS, PAD = 2, 3, 0`. The two ids must also differ, which
    is not decoration: a loop whose start token is its stop token returns the
    empty string for every crop on every page and looks exactly like a model
    that found no text.
    """
    assert BOS_TOKEN_ID == 2
    assert EOS_TOKEN_ID == 3
    assert BOS_TOKEN_ID != EOS_TOKEN_ID


def test_the_token_cap_is_generous_enough_for_real_text_and_bounded_by_the_export() -> None:
    """C-4's cap, bounded at both ends by something measured.

    **Lower bound 64.** `spikes/MT-002/ocr.py` decoded at `maxlen=64` and every
    one of the 12 oracle transcriptions and 9 page transcriptions MT-002 E5
    recorded came back complete; RED re-ran the nine on `014.jpg` and the longest
    is 22 characters. A cap below 64 would start truncating real lines, and a
    truncation is a wrong transcription rather than an error.

    **Upper bound 300.** The export's own `generation_config.json` says
    `"max_length": 300`, so a cap above it is a number this model was never
    configured to reach, and - with no KV cache - each extra step re-runs the
    whole decoder over the whole prefix.
    """
    assert isinstance(MAX_NEW_TOKENS, int)
    assert not isinstance(MAX_NEW_TOKENS, bool)
    assert 64 <= MAX_NEW_TOKENS <= 300, (
        f"MAX_NEW_TOKENS is {MAX_NEW_TOKENS}: 64 decoded every transcription MT-002 E5"
        " measured, and 300 is the export's own generation_config max_length"
    )


def test_the_decoder_step_alias_is_a_prefix_in_and_one_row_of_logits_out() -> None:
    """C-4's seam, introspected rather than trusted.

    `DecoderStep` is why `generate.py` can be read by the `unit` gate: its two
    halves are stdlib and numpy, so naming the decoder costs this module no
    import of `ocr.session` and therefore none of `onnxruntime`. Asserted through
    `get_origin`/`get_args` so the claim is about the alias's meaning and not
    about which module `Callable` was imported from.
    """
    assert get_origin(DecoderStep) is Callable

    parameters, returned = get_args(DecoderStep)

    assert len(parameters) == 1
    # `get_origin`/`get_args` rather than `== Sequence[int]`, for the reason
    # `test_detect_stage.py` records: `typing.Sequence[int]` and
    # `collections.abc.Sequence[int]` are unequal objects that answer these two
    # questions identically, and which one `generate.py` imports is not a claim
    # this story has any business making.
    assert get_origin(parameters[0]) is Sequence
    assert get_args(parameters[0]) == (int,)
    assert get_origin(returned) is np.ndarray


def test_the_generate_module_imports_neither_the_session_nor_onnxruntime() -> None:
    """C-4's structural claim, as a `unit` tripwire rather than only as `lint`.

    A `TYPE_CHECKING` import of `OcrSession` to annotate a parameter would still
    be an import-linter edge and would still drag `onnxruntime` behind it, which
    is exactly the mistake that is cheap to make and expensive to diagnose. The
    module's own imports are read out of its AST, so the docstring may discuss
    `ocr.session` freely - which C-4 requires it to.
    """
    import mangatl.ocr.generate as module

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
        for root in ("mangatl.ocr.session", "onnxruntime", "PIL", "cv2")
        if name == root or name.startswith(f"{root}.")
    )
    assert forbidden == [], (
        f"{forbidden} is imported by mangatl.ocr.generate. C-4 puts the generation"
        " loop here precisely so the `unit` and `coverage` gates read it; a module"
        " that reaches onnxruntime is exercised only by the optional `integration`"
        " gate, which never runs on CI."
    )


# -- AC-8, first half: it stops at the first EOS and returns what came before --


@pytest.mark.parametrize("length", [0, 1, 5], ids=["empty", "one", "many"])
def test_generation_stops_at_the_first_eos_and_returns_the_tokens_before_it(
    length: int,
) -> None:
    """AC-8's first clause, at the empty, one and many boundaries.

    `length == 0` is AC-4's input seen from this side: a step that emits EOS
    immediately produces no tokens at all, and that is what "the model emitted
    nothing" means. It is a boundary rather than an error.

    The returned tuple carries **neither** `BOS_TOKEN_ID` nor `EOS_TOKEN_ID`:
    `greedy_generate` returns the generated text tokens, and `decode` would strip
    both as specials anyway - which is precisely why they have to be excluded
    here instead. A loop that returned them would make AC-4's empty case
    indistinguishable from its specials-only control, and that control is the
    only thing keeping `ocr_empty` from being `text == ""` spelled twice (C-5).
    """
    emits = tuple(range(1000, 1000 + length))
    step = _TableStep(emits)

    generated = greedy_generate(step)

    assert generated == emits
    assert isinstance(generated, tuple)
    assert BOS_TOKEN_ID not in generated
    assert EOS_TOKEN_ID not in generated
    # One call per emitted token, plus the one that returned EOS. Not "at least":
    # a loop that ran on past EOS and sliced afterwards would return the right
    # tuple and pay for every extra decoder pass on a model with no KV cache.
    assert step.calls == length + 1


def test_each_step_is_handed_the_bos_seeded_prefix_of_everything_emitted_so_far() -> None:
    """AC-8's mechanism, and the half a return value cannot show.

    With no KV cache the decoder is re-run over the **whole** prefix at every
    step, so the prefix is the loop's entire state. A loop that fed back only the
    previous token, or that forgot to seed with `BOS_TOKEN_ID`, returns exactly
    the same tuple against a step that ignores its argument - and produces
    nonsense against the real graph, in `tests/integration/`, where it is
    expensive to diagnose.
    """
    emits = (1000, 1001, 1002)
    step = _TableStep(emits)

    greedy_generate(step)

    assert step.prefixes == [
        (BOS_TOKEN_ID,),
        (BOS_TOKEN_ID, 1000),
        (BOS_TOKEN_ID, 1000, 1001),
        (BOS_TOKEN_ID, 1000, 1001, 1002),
    ]


def test_an_eos_in_the_middle_ends_the_sequence_and_nothing_after_it_is_read() -> None:
    """AC-8's "the **first** EOS", with something deliberately placed after it.

    A loop that ran to the cap and then searched for EOS would return the same
    prefix, so the count of calls is what separates the two: this asserts the
    step was never asked for the tokens beyond the stop.
    """
    step = _TableStep((1000, 1001, EOS_TOKEN_ID, 1002, 1003))

    generated = greedy_generate(step)

    assert generated == (1000, 1001)
    assert step.calls == 3, f"the loop called the decoder {step.calls} times to emit two tokens"


# -- AC-8, second half: the cap, which is a termination guarantee --------------


def test_a_step_that_never_emits_eos_stops_at_the_cap_rather_than_hanging() -> None:
    """AC-8's second clause, and C-4's reason for `MAX_NEW_TOKENS` existing.

    `MAX_NEW_TOKENS` tokens **exactly** - not "at most", and not
    `MAX_NEW_TOKENS - 1`. An off-by-one here truncates the longest real line on a
    page and nothing reports it, because this export has no score to threshold
    and no "no text here" output (MT-002 E5 Test 3).

    If this test ever *hangs* rather than fails, that is the bug it exists to
    find, and the runner's own timeout is the only thing that will say so - which
    is why the two assertions that matter are the count and the call count rather
    than the content.
    """
    step = _NeverStops()

    generated = greedy_generate(step)

    assert len(generated) == MAX_NEW_TOKENS
    assert generated == (100,) * MAX_NEW_TOKENS
    assert step.calls == MAX_NEW_TOKENS


def test_an_explicit_cap_overrides_the_default_and_is_honoured_exactly() -> None:
    """AC-8's second clause again, at a cap small enough to read.

    `max_new_tokens` is keyword-only in C-1's signature, so this also pins that a
    caller cannot pass it positionally where the `DecoderStep` goes. Three caps,
    including 1, which is the smallest cap that can produce anything and the one
    an accumulator initialised wrongly gets wrong.
    """
    for cap in (1, 3, 7):
        step = _NeverStops(token=205)

        generated = greedy_generate(step, max_new_tokens=cap)

        assert generated == (205,) * cap, f"cap {cap} produced {len(generated)} tokens"
        assert step.calls == cap


def test_a_sequence_that_ends_exactly_at_the_cap_is_not_truncated_by_one() -> None:
    """The boundary between AC-8's two halves: a real sequence that is exactly as
    long as the cap allows.

    All `cap` tokens come back, and the decoder is never asked for the EOS that
    would have followed - the cap reached and the EOS emitted are two different
    stop conditions, and only one of them fires here. A loop whose cap is tested
    one iteration late spends an extra full decoder pass (this export has no KV
    cache, so that is the whole prefix again) and one whose cap is tested one
    iteration early drops token 13.
    """
    cap = 4
    step = _TableStep((10, 11, 12, 13, EOS_TOKEN_ID))

    generated = greedy_generate(step, max_new_tokens=cap)

    assert generated == (10, 11, 12, 13)
    assert len(generated) == cap
    assert step.calls == cap
