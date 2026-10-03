"""The vendored lettering font: where it lives, what it must cover, and its metrics.

MT-020 C-2. The four faces are Shantell Sans 1.011's static ``Normal`` instances,
vendored byte for byte under their archive names (PO-8; provenance in
``docs/wiki/architecture.md``). They are CFF-outlined OTFs, so nothing here reads
a ``glyf`` table: advances come from ``hmtx`` and ink from ``BoundsPen`` over the
glyph set, which works for either outline format.

Only the directory a caller names is read - never a system font directory and
never an environment variable (AC-6).
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

FONT_FAMILY: str = "Shantell Sans"
FONT_VERSION: str = "1.011"
FONT_DIR: Path = Path(__file__).parent / "fonts"
FACE_FILENAMES: Mapping[str, str] = {
    "regular": "Shantell_Sans-Normal-Regular.otf",
    "italic": "Shantell_Sans-Normal-Regular_Italic.otf",
    "bold": "Shantell_Sans-Normal-Bold.otf",
    "bold_italic": "Shantell_Sans-Normal-Bold_Italic.otf",
}
FACE_FILES: Mapping[str, Path] = {key: FONT_DIR / name for key, name in FACE_FILENAMES.items()}
OFL_FILENAME: str = "OFL.txt"

#: `typeset-font.md` §6: printable ASCII, curly quotes, en and em dash, ellipsis,
#: no-break space and three common accented letters - 106 in all. U+203D
#: (interrobang) is deliberately absent: the convention sets `?!`.
REQUIRED_CODEPOINTS: frozenset[str] = frozenset(
    [chr(c) for c in range(0x20, 0x7F)]
    + [chr(0x2018), chr(0x2019), chr(0x201C), chr(0x201D)]  # curly quotes
    + [chr(0x2013), chr(0x2014)]  # en and em dash
    + [chr(0x2026)]  # ellipsis
    + [chr(0x00A0)]  # no-break space
    + [chr(0x00E9), chr(0x00FC), chr(0x00F1)]  # e-acute, u-umlaut, n-tilde
)

InkUnits = tuple[float, float, float, float]


class MissingGlyph(Exception):
    """A character the face's cmap does not map. Never replaced with .notdef."""

    def __init__(self, char: str, face: str) -> None:
        super().__init__(f"U+{ord(char):04X} is not in the {face!r} face")
        self.char = char
        self.face = face


@dataclass(frozen=True)
class Face:
    key: str
    path: Path
    units_per_em: int
    ascender: int
    descender: int
    _cmap: Mapping[int, str] = field(repr=False, compare=False)
    _advances: Mapping[str, int] = field(repr=False, compare=False)
    _glyph_set: Any = field(repr=False, compare=False)
    _ink: dict[str, InkUnits | None] = field(default_factory=dict, repr=False, compare=False)

    def glyph(self, char: str) -> tuple[str, int]:
        """(glyph name, advance in font units) for one character."""
        name = self._cmap.get(ord(char))
        if name is None:
            raise MissingGlyph(char, self.key)
        return name, self._advances[name]

    def ink_units(self, name: str) -> InkUnits | None:
        """The glyph's ink bounds in font units, y up; None for a blank glyph."""
        if name not in self._ink:
            pen = BoundsPen(self._glyph_set)
            self._glyph_set[name].draw(pen)
            self._ink[name] = pen.bounds
        return self._ink[name]


Faces = Mapping[str, Face]


def _load_face(key: str, path: Path) -> Face:
    # Read into memory: fontTools otherwise keeps the file open for lazy table
    # loading, which on Windows pins the directory it came from.
    font = TTFont(io.BytesIO(path.read_bytes()))
    hmtx = font["hmtx"]
    return Face(
        key=key,
        path=path,
        units_per_em=int(font["head"].unitsPerEm),
        ascender=int(font["hhea"].ascent),
        descender=int(font["hhea"].descent),
        _cmap=dict(font.getBestCmap()),
        _advances={name: int(hmtx[name][0]) for name in font.getGlyphOrder()},
        _glyph_set=font.getGlyphSet(),
    )


def load_faces(directory: Path = FONT_DIR) -> Faces:
    """The four faces from ``directory``; a missing file raises FileNotFoundError."""
    return {key: _load_face(key, directory / name) for key, name in FACE_FILENAMES.items()}
