"""MT-020 AC-7 and AC-8(a): the shipped faces, their coverage and their style bits.

Everything about the font FILES is read with fontTools directly, through
`_typeset_oracle`, and never through `mangatl.typeset.font`'s own reader
(C-9, AC-7): a reader that is wrong in the same way as the module would agree
with it. `font.py` is imported only for the names C-2 pins.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import _typeset_oracle as oracle
import pytest

from mangatl.typeset import font
from mangatl.typeset.font import (
    FACE_FILENAMES,
    FACE_FILES,
    FONT_DIR,
    FONT_FAMILY,
    FONT_VERSION,
    OFL_FILENAME,
    REQUIRED_CODEPOINTS,
    Face,
    MissingGlyph,
    load_faces,
)
from mangatl.ui.tokens_gen import TOKENS

KEYS = ("regular", "italic", "bold", "bold_italic")

#: `typeset-font.md` §6, as C-2 transcribes it. Written out here, not derived
#: from the module, so `REQUIRED_CODEPOINTS` is pinned by EQUALITY.
EXPECTED_CODEPOINTS = frozenset(
    [chr(c) for c in range(0x20, 0x7F)]
    + ["\u2018", "\u2019", "\u201c", "\u201d"]
    + ["\u2013", "\u2014"]
    + ["\u2026"]
    + ["\u00a0"]
    + ["\u00e9", "\u00fc", "\u00f1"]
)

#: C-7's table: (ITALIC bit 0, BOLD bit 5, REGULAR bit 6) of `OS/2.fsSelection`.
EXPECTED_STYLE_BITS = {
    "regular": (0, 0, 1),
    "italic": (1, 0, 0),
    "bold": (0, 1, 0),
    "bold_italic": (1, 1, 0),
}


def _style_bits(key: str) -> tuple[int, int, int]:
    fs = int(oracle.font(key)["OS/2"].fsSelection)
    return (fs >> 0) & 1, (fs >> 5) & 1, (fs >> 6) & 1


# --- C-2: the names, against the design tokens ----------------------------------


def test_family_and_version_are_shantell_sans_1_011_and_match_the_design_tokens() -> None:
    assert FONT_FAMILY == "Shantell Sans"
    assert FONT_VERSION == "1.011"
    assert TOKENS["typeset.font.family"] == FONT_FAMILY
    assert TOKENS["typeset.font.version"] == FONT_VERSION


def test_face_filenames_are_upstreams_four_static_otf_archive_names_unrenamed() -> None:
    # R-1 / PO-8: the file names no longer relate to the `typeset.font.*`
    # tokens, and no test may pin them against the tokens (C-2).
    assert dict(FACE_FILENAMES) == oracle.FILENAMES


def test_font_dir_is_the_fonts_folder_beside_font_py_and_face_files_live_in_it() -> None:
    assert Path(font.__file__).parent / "fonts" == FONT_DIR
    assert FONT_DIR.resolve() == oracle.FONT_DIR.resolve()
    assert dict(FACE_FILES) == {k: FONT_DIR / n for k, n in oracle.FILENAMES.items()}
    assert OFL_FILENAME == "OFL.txt"


def test_required_codepoints_is_exactly_the_106_characters_of_the_design_doc() -> None:
    assert len(EXPECTED_CODEPOINTS) == 106
    assert REQUIRED_CODEPOINTS == EXPECTED_CODEPOINTS
    assert isinstance(REQUIRED_CODEPOINTS, frozenset)


def test_interrobang_is_not_a_required_codepoint() -> None:
    assert "\u203d" not in REQUIRED_CODEPOINTS


# --- AC-7: the files themselves, read with fontTools directly -------------------


@pytest.mark.parametrize("key", KEYS)
def test_every_required_codepoint_is_in_the_cmap_of_each_shipped_face(key: str) -> None:
    present = oracle.cmap(key)
    missing = sorted(f"U+{ord(c):04X}" for c in EXPECTED_CODEPOINTS if ord(c) not in present)
    assert missing == [], f"{oracle.FILENAMES[key]} lacks {missing}"


@pytest.mark.parametrize("key", KEYS)
def test_each_face_carries_its_own_os2_style_bits_in_the_file(key: str) -> None:
    assert _style_bits(key) == EXPECTED_STYLE_BITS[key]


def test_the_four_faces_have_distinct_style_bits_so_bold_is_not_synthesised() -> None:
    assert len({_style_bits(k) for k in KEYS}) == 4


# --- AC-8(a): the licence ships beside the faces ---------------------------------


def test_ofl_txt_sits_beside_the_font_files_and_is_the_ofl_1_1() -> None:
    ofl = oracle.FONT_DIR / "OFL.txt"
    assert ofl.is_file()
    assert b"SIL OPEN FONT LICENSE Version 1.1" in ofl.read_bytes()
    for name in oracle.FILENAMES.values():
        assert (ofl.parent / name).is_file(), name


def test_the_font_directory_holds_exactly_the_four_faces_and_the_licence() -> None:
    names = {p.name for p in oracle.FONT_DIR.iterdir()}
    assert names == {*oracle.FILENAMES.values(), "OFL.txt"}


#: C-7's table (PO-8, R-1), measured by the orchestrator from
#: `Shantell_Sans_1.011.zip` on 2026-10-03. Literals, so a re-encoded, subset,
#: renamed-and-swapped or otherwise modified file fails here.
EXPECTED_SHA256 = {
    "Shantell_Sans-Normal-Regular.otf": (
        "a340af0fb6f614f4a7d2c692dc0486fc4aaf5cf1028929dbf3e741b6574623b2"
    ),
    "Shantell_Sans-Normal-Regular_Italic.otf": (
        "c3375c19f8ac44302cd233998a6331bd28abed40dc079d093185b1a8eabd4777"
    ),
    "Shantell_Sans-Normal-Bold.otf": (
        "7b446a4d2f0e31d08692339cf019b3321e612a6dd28bd679979fad809548ed2c"
    ),
    "Shantell_Sans-Normal-Bold_Italic.otf": (
        "4198e1360a37ad1934b1c3288e3fa559cbea8cd6b115af80b7d7ea5e6b919c2f"
    ),
    "OFL.txt": "ebfce7d104d597c385b71e9fbf8f0e2034e73320f857086105dc265b82c05caa",
}


@pytest.mark.parametrize("name", sorted(EXPECTED_SHA256))
def test_each_vendored_file_is_byte_for_byte_upstreams(name: str) -> None:
    digest = hashlib.sha256((oracle.FONT_DIR / name).read_bytes()).hexdigest()
    assert digest == EXPECTED_SHA256[name], f"{name} differs from upstream 1.011"


# --- C-2: load_faces -----------------------------------------------------------------


def test_load_faces_returns_the_four_faces_with_metrics_read_from_the_files() -> None:
    faces = load_faces()
    assert set(faces) == set(KEYS)
    for key in KEYS:
        face = faces[key]
        assert isinstance(face, Face)
        assert face.key == key
        assert face.path == FACE_FILES[key]
        assert face.units_per_em == oracle.units_per_em(key)
        assert (face.ascender, face.descender) == oracle.hhea(key)
        assert face.descender < 0 < face.ascender


def test_load_faces_reads_from_the_directory_it_is_given(tmp_path: Path) -> None:
    for name in oracle.FILENAMES.values():
        shutil.copyfile(oracle.FONT_DIR / name, tmp_path / name)
    faces = load_faces(tmp_path)
    for key, name in oracle.FILENAMES.items():
        assert faces[key].path == tmp_path / name


def test_load_faces_raises_file_not_found_when_a_face_is_missing(tmp_path: Path) -> None:
    for key, name in oracle.FILENAMES.items():
        if key != "bold":
            shutil.copyfile(oracle.FONT_DIR / name, tmp_path / name)
    with pytest.raises(FileNotFoundError):
        load_faces(tmp_path)


def test_missing_glyph_names_the_character_and_the_face() -> None:
    err = MissingGlyph("\u3042", "italic")
    assert isinstance(err, Exception)
    assert err.char == "\u3042"
    assert err.face == "italic"
