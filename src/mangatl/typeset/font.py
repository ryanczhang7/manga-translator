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
from typing import Any, Literal

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
    return _face(key, path, TTFont(io.BytesIO(path.read_bytes())))


def _face(key: str, path: Path, font: Any) -> Face:
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


# --- MT-027: a folder of faces the project did not ship ---------------------------

#: Why a configured font folder was not used; ``"none"`` when it was (or when
#: there was none). Lives here rather than in ``resolve`` because
#: ``validate_faces`` returns it and ``resolve`` imports this module.
FallbackReason = Literal["none", "missing_path", "unparseable", "missing_glyphs", "missing_style"]

#: The four styles, in ``FACE_FILENAMES`` order - the order a missing style or a
#: face lacking glyphs is reported in.
STYLE_KEYS: tuple[str, ...] = ("regular", "italic", "bold", "bold_italic")

_FONT_SUFFIXES = frozenset({".otf", ".ttf"})

#: ``OS/2.fsSelection`` bits 0 and 5 (MT-020 C-7). Nothing else in the field
#: counts: Shantell's faces also carry bits 6 and 7.
_ITALIC_BIT = 1 << 0
_BOLD_BIT = 1 << 5

#: Tables a candidate must carry, checked in this order. The first three are
#: the ones the check itself reads; the rest are the ones a ``Face`` is built
#: from, named here so their absence is reported as a sentence, not a KeyError.
_REQUIRED_TABLES = ("OS/2", "cmap", "name", "head", "hhea", "hmtx")

_REQUIRED_ORDS: tuple[int, ...] = tuple(sorted(ord(c) for c in REQUIRED_CODEPOINTS))


@dataclass(frozen=True)
class _Candidate:
    face: Face
    family: str


def _style_of(fs_selection: int) -> str:
    italic = bool(fs_selection & _ITALIC_BIT)
    bold = bool(fs_selection & _BOLD_BIT)
    return STYLE_KEYS[italic + 2 * bold]


def _read_candidate(path: Path) -> _Candidate | str:
    """The face in ``path``, classified by its style bits, or why it is not a font."""
    try:
        font = TTFont(io.BytesIO(path.read_bytes()))
        absent = [tag for tag in _REQUIRED_TABLES if tag not in font]
        if absent:
            return f"no {absent[0]} table"
        name = font["name"]
        family = name.getDebugName(16) or name.getDebugName(1) or ""
        return _Candidate(_face(_style_of(font["OS/2"].fsSelection), path, font), family)
    except Exception as error:  # fontTools raises many types for a bad file
        return str(error)


def _candidates(directory: Path) -> list[Path]:
    """``.otf``/``.ttf`` regular files directly in ``directory``, by file name."""
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.suffix.lower() in _FONT_SUFFIXES and path.is_file()
        ),
        key=lambda path: path.name,
    )


def read_face_folder(directory: Path) -> tuple[Faces | None, FallbackReason, str, str]:
    """``validate_faces`` plus the regular face's family (name ID 16, else 1)."""
    if not directory.exists():
        return None, "missing_path", f"{directory} does not exist", ""
    if not directory.is_dir():
        return None, "unparseable", f"{directory} is not a font: not a folder", ""

    found: dict[str, _Candidate] = {}
    for path in _candidates(directory):
        candidate = _read_candidate(path)
        if isinstance(candidate, str):
            return None, "unparseable", f"{path} is not a font: {candidate}", ""
        found.setdefault(candidate.face.key, candidate)

    absent = [key.replace("_", " ") for key in STYLE_KEYS if key not in found]
    if absent:
        return None, "missing_style", f"{directory} has no {', '.join(absent)} face", ""

    for key in STYLE_KEYS:
        face = found[key].face
        lacking = [cp for cp in _REQUIRED_ORDS if cp not in face._cmap]
        if lacking:
            listed = ", ".join(f"U+{cp:04X}" for cp in lacking)
            return None, "missing_glyphs", f"{face.path} lacks {listed}", ""

    faces = {key: found[key].face for key in STYLE_KEYS}
    return faces, "none", "", found["regular"].family


def validate_faces(directory: Path) -> tuple[Faces | None, FallbackReason, str]:
    """MT-020 AC-7's check, against any folder: its four faces, or why not.

    ``Faces`` is not None exactly when the reason is ``"none"``, and then the
    detail is ``""``. The checks run in the order of MT-027's table; the first
    that fails is the one reported. Never raises for what is in the folder.
    """
    faces, reason, detail, _ = read_face_folder(directory)
    return faces, reason, detail
