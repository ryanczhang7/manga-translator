"""Synthesised lettering faces for MT-027's override suites.

Nothing here imports `mangatl`, so every builder runs in a plain interpreter
while `mangatl.typeset.resolve` does not exist - which is how RED measured the
discriminating values recorded in the story's handoff.

**Why synthesised, not vendored** (story `## Contract`, "Fixtures"): a second
real family would be a licence obligation and a few hundred kilobytes for a
test that needs four tiny files. `fontTools.fontBuilder.FontBuilder` writes a
TrueType (`glyf`) font of about a hundred glyphs in milliseconds.

**Every inked glyph is a solid box** of the face's own `advance`, inset by
`side` on each side, from the baseline to `BOX_TOP`. Two families with
different advances therefore lay a line out differently - different break
points, different sizes, different x positions - and both differ from Shantell
Sans, whose advances vary per glyph. That is what makes a bake lettered in the
wrong face a pixel difference rather than a claim (AC-8, deferred condition 3).
Space and no-break space are blank, as in a real font.

**Style is carried by `OS/2.fsSelection` alone**, set explicitly per face:
ITALIC bit 0, BOLD bit 5, REGULAR bit 6 - the bits MT-020 C-7 pins for the
shipped faces and MT-027's `## Contract` classifies a user's files by. File
names never say the style, so an implementation that classified by filename
fails.

The `name` table carries ID 1 (family) always and ID 16 (typographic family)
when asked: MT-027 reads ID 16 first, else ID 1.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

#: MT-020's `REQUIRED_CODEPOINTS`, written out from `typeset-font.md` §6 rather
#: than imported, so a fixture "with full coverage" is full against the design
#: document and not against whatever the module says today.
REQUIRED: frozenset[int] = frozenset(
    [
        *range(0x20, 0x7F),  # printable ASCII
        *(0x2018, 0x2019, 0x201C, 0x201D),  # curly quotes
        *(0x2013, 0x2014),  # en and em dash
        0x2026,  # ellipsis
        0x00A0,  # no-break space
        *(0x00E9, 0x00FC, 0x00F1),  # e-acute, u-umlaut, n-tilde
    ]
)

#: The two the story names for the glyph-coverage fixture (AC-5).
ELLIPSIS = 0x2026
EM_DASH = 0x2014

BLANK = frozenset({0x20, 0xA0})

UPM = 1000
ASCENT = 800
DESCENT = -200
BOX_TOP = 700

ITALIC_BIT = 1 << 0
BOLD_BIT = 1 << 5
REGULAR_BIT = 1 << 6

#: Style key -> `OS/2.fsSelection`, MT-020 C-7's table.
FS_SELECTION: dict[str, int] = {
    "regular": REGULAR_BIT,
    "italic": ITALIC_BIT,
    "bold": BOLD_BIT,
    "bold_italic": ITALIC_BIT | BOLD_BIT,
}

STYLE_KEYS = ("regular", "italic", "bold", "bold_italic")


@dataclass(frozen=True)
class Family:
    """One synthesised family: its names and the geometry of its boxes."""

    family: str  # name ID 1
    typographic: str | None  # name ID 16, or absent
    advance: int
    side: int

    @property
    def reported(self) -> str:
        """The family MT-027 must report: ID 16 when present, else ID 1."""
        return self.typographic if self.typographic is not None else self.family


#: Narrow boxes. Its ID 1 and ID 16 differ, so a reader of ID 1 is caught.
BOXY = Family(family="Boxy Legacy", typographic="Boxy Lettering", advance=520, side=40)
#: Wide boxes: the same text needs far more room than in BOXY or Shantell Sans.
WIDE = Family(family="Wide Lettering", typographic=None, advance=980, side=60)


def _glyph_name(cp: int) -> str:
    return f"uni{cp:04X}"


def _box(advance: int, side: int):  # type: ignore[no-untyped-def]
    pen = TTGlyphPen(None)
    pen.moveTo((side, 0))
    pen.lineTo((side, BOX_TOP))
    pen.lineTo((advance - side, BOX_TOP))
    pen.lineTo((advance - side, 0))
    pen.closePath()
    return pen.glyph()


def _empty():  # type: ignore[no-untyped-def]
    return TTGlyphPen(None).glyph()


def face_bytes(
    family: Family,
    style: str,
    *,
    omit: Iterable[int] = (),
    fs_selection: int | None = None,
    drop_tables: Sequence[str] = (),
) -> bytes:
    """The bytes of one TrueType face of `family` in `style`.

    `omit` removes codepoints from the cmap (and their glyphs); `fs_selection`
    overrides the style's own bits (AC-6: four files that all say "regular");
    `drop_tables` deletes tables after building (row 2: `OS/2`/`cmap`/`name`
    absent).
    """
    omitted = set(omit)
    codepoints = sorted(REQUIRED - omitted)
    order = [".notdef"] + [_glyph_name(cp) for cp in codepoints]
    builder = FontBuilder(UPM, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({cp: _glyph_name(cp) for cp in codepoints})
    glyphs = {".notdef": _box(family.advance, family.side)}
    for cp in codepoints:
        glyphs[_glyph_name(cp)] = _empty() if cp in BLANK else _box(family.advance, family.side)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(
        {name: (family.advance, family.side if name in glyphs else 0) for name in order}
    )
    builder.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    style_name = {
        "regular": "Regular",
        "italic": "Italic",
        "bold": "Bold",
        "bold_italic": "Bold Italic",
    }[style]
    names: dict[str, str] = {"familyName": family.family, "styleName": style_name}
    if family.typographic is not None:
        names["typographicFamily"] = family.typographic
        names["typographicSubfamily"] = style_name
    builder.setupNameTable(names)
    builder.setupOS2(
        sTypoAscender=ASCENT,
        sTypoDescender=DESCENT,
        usWinAscent=ASCENT,
        usWinDescent=-DESCENT,
    )
    builder.font["OS/2"].fsSelection = FS_SELECTION[style] if fs_selection is None else fs_selection
    builder.font["head"].macStyle = (1 if style in ("bold", "bold_italic") else 0) | (
        2 if style in ("italic", "bold_italic") else 0
    )
    builder.setupPost()
    for tag in drop_tables:
        del builder.font[tag]

    buffer = BytesIO()
    builder.save(buffer)
    return buffer.getvalue()


#: File names that do NOT say the style, and sort in a fixed order.
FILE_NAMES: dict[str, str] = {
    "regular": "f1.ttf",
    "italic": "f2.ttf",
    "bold": "f3.ttf",
    "bold_italic": "f4.ttf",
}


def write_family(
    directory: Path,
    family: Family,
    *,
    styles: Sequence[str] = STYLE_KEYS,
    omit: dict[str, Iterable[int]] | None = None,
    fs_selection: dict[str, int] | None = None,
    names: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Write `styles` of `family` into `directory` (created); style -> path."""
    directory.mkdir(parents=True, exist_ok=True)
    omit = omit or {}
    fs_selection = fs_selection or {}
    names = names or FILE_NAMES
    paths: dict[str, Path] = {}
    for style in styles:
        path = directory / names[style]
        path.write_bytes(
            face_bytes(
                family, style, omit=omit.get(style, ()), fs_selection=fs_selection.get(style)
            )
        )
        paths[style] = path
    return paths


def write_settings(appdata: Path, value: object, *, raw: str | None = None) -> Path:
    """Write `%APPDATA%/mangatl/settings.json` with `lettering_font_dir = value`.

    `raw` writes that text verbatim instead (row 1b). Returns the file's path,
    spelled out from the contract (`app_paths.settings_path`), never derived.
    """
    path = appdata / "mangatl" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = raw if raw is not None else json.dumps({"lettering_font_dir": value})
    path.write_text(text, encoding="utf-8")
    return path


def settings_file(appdata: Path) -> Path:
    return appdata / "mangatl" / "settings.json"


#: Bytes that are no font at all (AC-4): text, as a mis-saved download would be.
NOT_A_FONT = b"this is not a font, it is a note about one\n"

#: The shipped faces, spelled out from the repository root (MT-020 C-2), not
#: read from `mangatl.typeset.font`.
SHIPPED_DIR = Path(__file__).resolve().parents[2] / "src" / "mangatl" / "typeset" / "fonts"


def parse_error(data: bytes) -> str:
    """What fontTools says when asked to read `data` - the `{error}` of row 2.

    Asked of fontTools here, in the test, rather than written out, so the pin is
    "the parser's own message" and not "the message fontTools 4.66 happens to
    print". Raises AssertionError if `data` parses.
    """
    from fontTools.ttLib import TTFont

    try:
        TTFont(BytesIO(data))
    except Exception as error:
        return str(error)
    raise AssertionError("the bytes parsed as a font")


def copy_shipped(directory: Path) -> dict[str, Path]:
    """The four shipped faces copied into `directory`; style -> path."""
    names = {
        "regular": "Shantell_Sans-Normal-Regular.otf",
        "italic": "Shantell_Sans-Normal-Regular_Italic.otf",
        "bold": "Shantell_Sans-Normal-Bold.otf",
        "bold_italic": "Shantell_Sans-Normal-Bold_Italic.otf",
    }
    directory.mkdir(parents=True, exist_ok=True)
    out = {}
    for style, name in names.items():
        (directory / name).write_bytes((SHIPPED_DIR / name).read_bytes())
        out[style] = directory / name
    return out
