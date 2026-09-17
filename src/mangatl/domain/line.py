"""What OCR read off one region: the text, and whether the model said anything.

**`ocr_empty` means "the model emitted no tokens", not "the text is empty"**
(MT-010 C-5). The two differ, and the difference is the whole reason the flag
exists:

* an **empty token sequence** is the decoder emitting EOS immediately - the model
  declined to read anything;
* a sequence of **special tokens only** decodes to `""` and is a *successful*
  read whose printable content happens to be nothing.

So `__post_init__` enforces the one direction that must hold - `ocr_empty`
implies `text == ""` - and deliberately **not** the converse. A flag enforced in
both directions is `text == ""` spelled twice, carries no information, and makes
MT-010 AC-4's negative control unfailable.

The flag is stored rather than derived (MT-010 PO-3), which is what makes the
three states a reopened project has to distinguish tellable apart: **no `line`
row** (OCR has not run), **a row with `ocr_empty = 1`** (the model emitted
nothing), **a row with `source_ja`** (read).

`domain` imports nothing of ours and no third-party package (`architecture.md`
§3 contract 2), which is why this is a value and the decoding that produces it
lives in `mangatl.ocr`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["OcrResult"]


@dataclass(frozen=True)
class OcrResult:
    """One region's transcription, and whether the model emitted anything at all.

    Frozen because it is a value: two results with the same text and the same
    flag *are* the same result, and nothing downstream mutates one after it is
    built. `ocr_empty` defaults to `False` so that every construction site
    holding real text need not mention it.
    """

    text: str
    ocr_empty: bool = False

    def __post_init__(self) -> None:
        if self.ocr_empty and self.text:
            raise ValueError(
                "ocr_empty means the model emitted no tokens, so the text must be"
                f" empty; got {self.text!r}. An empty text WITHOUT the flag is legal"
                " and is a successful read of nothing printable (MT-010 C-5)."
            )
