"""Token ids to the Japanese string a human would read.

The decoder is `cl-tohoku/bert-base-japanese-char-v2`, a **character-level**
model: RED measured that not one of `vocab.txt`'s 6144 entries begins with `##`,
so there are no word-piece continuations and this module has no branch for them.
`spikes/MT-002/ocr.py` carried a `t[2:] if t.startswith("##")` and it was dead
code; reproducing it would be an unreachable branch in a package the `coverage`
gate reads, and a claim about the vocabulary nothing checks.

**The normalisation is a measurement, not a preference** (MT-010 C-7). MT-002 E5
Test 1 scored this export against the upstream author's own ground-truth set
twice: **6/12 raw** and **10/12** after upstream's `post_process`. All four
recovered files differed *only* in half-width against full-width punctuation and
digits - `!!!` against `！！！`, `LINK!私達7人` against `ＬＩＮＫ！私達７人`.
Omitting the step makes the model look 33 points worse than it is and makes
`ocr.page.OCR_MIN_ACCURACY` absorb a known, fixable defect, which is how a
threshold stops being a threshold.

The four steps below are upstream's own `post_process`, in its order
(`spikes/MT-002/rescore.py`, which is the script that measured 10/12), and the
order matters: `…` becomes three stops *before* the run collapse sees them, and
the widening happens last so that it widens the stops the collapse produced.
"""

# ruff: noqa: RUF002
#
# RUF002 warns that a full-width character in a docstring "looks like" its ASCII
# twin and may have been typed by accident. In this one module that rule is
# exactly inverted: telling those two apart IS the subject, and the
# half-width/full-width pairs quoted above are the evidence MT-002 E5 measured,
# written out so a reader can see the difference rather than decode an escape.
# Scoped to this file and to this one rule; `tests/core/test_ocr_decode.py`
# carries the same suppression for the same reason.

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

import jaconv

__all__ = ["SPECIAL_TOKENS", "decode"]

#: The tokens that are the model's own machinery rather than the user's text.
#: Ids 0-4 of the shipped `vocab.txt`, read rather than inferred; `[CLS]` and
#: `[SEP]` are also `generate`'s BOS and EOS, and the graph can emit `[PAD]` or
#: `[UNK]` at any position. A set of *strings*, so it is the vocabulary's own
#: entries that are matched and not a guess about ids.
SPECIAL_TOKENS: frozenset[str] = frozenset({"[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"})

#: A run of two or more stops or katakana middle dots - manga's ellipsis, set in
#: either glyph - which upstream folds to that many ASCII stops before widening.
_ELLIPSIS_RUN = re.compile(r"[・.]{2,}")


def decode(tokens: Sequence[int], vocab: Mapping[int, str]) -> str:
    """`tokens` as text: specials stripped, whitespace removed, forms normalised.

    An id the vocabulary does not hold raises `LookupError`. The graph's logits
    are 6144 wide and the vocabulary is 6144 long, so an id outside it means
    `vocab.txt` and the weights do not belong together - and silently dropping
    the token would produce a plausible Japanese string with characters missing,
    which `architecture.md` D11 calls worse than a miss and which no gate
    anywhere would see.

    A sequence with nothing printable in it - empty, delimiters only, specials
    only - decodes to `""`. That is a *successful read of nothing printable* and
    is not the same event as the model emitting no tokens; this function is
    handed a sequence and returns a string, and the distinction is made one layer
    up, in `ocr.page` (MT-010 C-5).
    """
    pieces: list[str] = []
    for token_id in tokens:
        if token_id not in vocab:
            raise LookupError(
                f"token id {token_id} is not in a vocabulary of {len(vocab)} entries:"
                " the vocabulary and the weights do not belong together"
            )
        token = vocab[token_id]
        if token not in SPECIAL_TOKENS:
            pieces.append(token)
    return _normalised("".join(pieces))


def _normalised(text: str) -> str:
    """Upstream `manga-ocr`'s `post_process`, step for step.

    `''.join(text.split())` removes every run of whitespace **anywhere**, not
    only at the ends: a Japanese line has no spaces in it, so a space the decoder
    emitted is an artefact, and one left in the middle survives into the
    translation prompt and onto the typeset page.

    `jaconv.h2z(ascii=True, digit=True)` is the measured step, and it is range
    guarded where a hand-rolled `chr(ord(c) + 0xFEE0)` would not be - applied
    unguarded to an already full-width `！` that offset produces U+1FEE1, and the
    result still looks right on every input that was half-width to begin with.
    """
    text = "".join(text.split())
    text = text.replace("…", "...")
    text = _ELLIPSIS_RUN.sub(lambda run: "." * (run.end() - run.start()), text)
    return str(jaconv.h2z(text, ascii=True, digit=True))
