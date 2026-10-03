"""``*italic*`` and ``**bold**`` emphasis markers, per MT-020 C-3.

1. ``\\*`` is a literal ``*``; a ``\\`` before anything else is a literal ``\\``.
2. A delimiter is a maximal run of unescaped ``*``.
3. A delimiter of length 1 or 2 opens a span iff the next delimiter in the string
   has the same length; the pair is consumed and the text between is emphasised.
4. Every other delimiter is literal text. Nesting is therefore rendered literally.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Run:
    text: str
    italic: bool
    bold: bool

    @property
    def face_key(self) -> str:
        if self.italic and self.bold:
            return "bold_italic"
        if self.italic:
            return "italic"
        return "bold" if self.bold else "regular"


def _tokens(text: str) -> list[str | int]:
    """Literal text as ``str``, delimiters as their length (``int``)."""
    out: list[str | int] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and text[i + 1 : i + 2] == "*":
            out.append("*")
            i += 2
        elif c == "*":
            j = i
            while j < len(text) and text[j] == "*":
                j += 1
            out.append(j - i)
            i = j
        else:
            out.append(c)
            i += 1
    return out


def parse_emphasis(text: str) -> list[Run]:
    tokens = _tokens(text)
    delimiters = [i for i, t in enumerate(tokens) if isinstance(t, int)]
    pieces: list[tuple[str, bool, bool]] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if isinstance(token, str):
            pieces.append((token, False, False))
            i += 1
            continue
        later = [d for d in delimiters if d > i]
        close = later[0] if later else None
        if token in (1, 2) and close is not None and tokens[close] == token:
            inner = "".join(str(t) for t in tokens[i + 1 : close])
            pieces.append((inner, token == 1, token == 2))
            i = close + 1
        else:
            pieces.append(("*" * token, False, False))
            i += 1
    runs: list[Run] = []
    for piece, italic, bold in pieces:
        if runs and (runs[-1].italic, runs[-1].bold) == (italic, bold):
            runs[-1] = Run(runs[-1].text + piece, italic, bold)
        else:
            runs.append(Run(piece, italic, bold))
    return runs
