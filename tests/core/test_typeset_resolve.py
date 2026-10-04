"""MT-027 AC-1..AC-6: which faces letter the chapter, and why.

`mangatl.typeset.resolve.resolve_faces(override_dir, bundled_dir=FONT_DIR)` and
the check it reuses, `mangatl.typeset.font.validate_faces(dir)`.

**Oracle: entirely mechanical** (story `## Contract`). Every expectation below is
a resolution outcome over a synthesised fixture (`_font_fixtures`), with the
reason and the exact `detail` the contract's table pins:

| # | condition | `fallback` | `detail` |
|---|---|---|---|
| 1 | path does not exist | `missing_path` | `{path} does not exist` |
| 2 | path not a folder | `unparseable` | `{path} is not a font: not a folder` (amended in RED) |
| 2 | a candidate fails to parse | `unparseable` | `{file} is not a font: {error}` |
| 3 | a style has no file | `missing_style` | `{dir} has no {styles} face` |
| 4 | a face lacks required codepoints | `missing_glyphs` | `{file} lacks {cps}` |

**AC-5 and AC-6 have a fixture each, and they do not overlap** (Model guidance):
the coverage fixture has all four styles and lacks glyphs; the style fixture has
full coverage and lacks a style. With `validate_faces` made to succeed
unconditionally (deferred condition 1) both go red, separately.

**How a user's folder is read**: candidates are `.otf`/`.ttf` (any case) regular
files directly in the folder; each is classified by `OS/2.fsSelection` bits 0
and 5 only; sorted filename order, first file per style wins; `family` is the
regular face's name ID 16, else ID 1. File names in the fixtures never say the
style, so classifying by name fails.

RED: `mangatl.typeset.resolve` does not exist and `font.py` exports neither
`STYLE_KEYS` nor `validate_faces`, so this file fails at import.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import _font_fixtures as ff
import pytest
from _font_fixtures import BOXY, ELLIPSIS, EM_DASH, FILE_NAMES, NOT_A_FONT, WIDE

from mangatl.typeset import font as font_module
from mangatl.typeset import resolve as resolve_module
from mangatl.typeset.fit import typeset
from mangatl.typeset.font import (
    FACE_FILENAMES,
    FACE_FILES,
    FONT_DIR,
    FONT_FAMILY,
    STYLE_KEYS,
    load_faces,
    validate_faces,
)
from mangatl.typeset.resolve import FaceResolution, resolve_faces

KEYS = ("regular", "italic", "bold", "bold_italic")

#: A region polygon the short line fits in at a size above the minimum, in every
#: face used here (MT-021's region 0 on the 160x120 page; measured in RED).
BUBBLE = ((6, 6), (78, 6), (78, 56), (6, 56), (6, 6))


def _paths(faces: object) -> dict[str, Path]:
    return {key: face.path for key, face in faces.items()}  # type: ignore[attr-defined]


def _assert_default(resolution: FaceResolution, bundled: Path = FONT_DIR) -> None:
    """AC-3..AC-6's common half: the shipped faces, reported as the default."""
    assert resolution.source == "default"
    assert resolution.family == FONT_FAMILY
    assert _paths(resolution.faces) == {k: bundled / n for k, n in FACE_FILENAMES.items()}


# =============================================================================
# The names the contract pins
# =============================================================================


def test_style_keys_are_regular_italic_bold_bold_italic_in_face_filenames_order() -> None:
    assert STYLE_KEYS == KEYS
    assert tuple(FACE_FILENAMES) == STYLE_KEYS


def test_the_fallback_reason_lives_in_font_and_resolve_re_exports_the_same_type() -> None:
    assert resolve_module.FallbackReason is font_module.FallbackReason
    assert set(font_module.FallbackReason.__args__) == {  # type: ignore[attr-defined]
        "none",
        "missing_path",
        "unparseable",
        "missing_glyphs",
        "missing_style",
    }


def test_a_face_resolution_is_frozen() -> None:
    resolution = resolve_faces(None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolution.family = "Comic Sans"  # type: ignore[misc]


# =============================================================================
# AC-1: no override
# =============================================================================


def test_with_no_override_the_four_shipped_shantell_faces_are_used_and_reported_default() -> None:
    resolution = resolve_faces(None)

    assert resolution.source == "default"
    assert resolution.family == FONT_FAMILY == "Shantell Sans"
    assert resolution.fallback == "none"
    assert resolution.detail == ""
    assert _paths(resolution.faces) == dict(FACE_FILES)
    assert resolution.faces == load_faces()


def test_with_no_override_the_faces_come_from_the_bundled_directory_given(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    ff.copy_shipped(bundled)

    resolution = resolve_faces(None, bundled)

    _assert_default(resolution, bundled)
    assert resolution.fallback == "none"


# =============================================================================
# AC-2: a valid override
# =============================================================================


def test_a_folder_of_four_valid_faces_is_used_and_reported_as_the_override(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Boxy"
    written = ff.write_family(folder, BOXY)

    resolution = resolve_faces(folder)

    assert resolution.source == "override"
    assert resolution.fallback == "none"
    assert resolution.detail == ""
    assert _paths(resolution.faces) == written
    assert {k: f.key for k, f in resolution.faces.items()} == {k: k for k in KEYS}


def test_the_override_family_is_the_typographic_family_name_id_16_of_the_regular_face(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Boxy"
    ff.write_family(folder, BOXY)

    # ID 16 "Boxy Lettering", ID 1 "Boxy Legacy": a reader of ID 1 says Legacy.
    assert resolve_faces(folder).family == "Boxy Lettering" == BOXY.reported


def test_without_name_id_16_the_override_family_is_name_id_1(tmp_path: Path) -> None:
    folder = tmp_path / "Wide"
    ff.write_family(folder, WIDE)

    assert resolve_faces(folder).family == "Wide Lettering" == WIDE.reported


def test_the_family_is_read_from_the_regular_face_not_another_one(tmp_path: Path) -> None:
    # The italic face (f2.ttf) belongs to a different family; only the
    # regular face's name table counts.
    folder = tmp_path / "Mixed"
    ff.write_family(folder, BOXY, styles=("regular", "bold", "bold_italic"))
    ff.write_family(folder, WIDE, styles=("italic",))

    resolution = resolve_faces(folder)

    assert resolution.fallback == "none"
    assert resolution.family == "Boxy Lettering"


def test_a_copy_of_the_shipped_faces_is_a_valid_override_named_from_its_own_name_table(
    tmp_path: Path,
) -> None:
    # Real files, real bits: Shantell's fsSelection also carries bit 7
    # (USE_TYPO_METRICS) and bit 6 (REGULAR) - 192, 129, 160, 161 - so only a
    # classifier that reads bits 0 and 5 alone gets all four. Its name table
    # has no ID 16; ID 1 is "Shantell Sans Normal", which is NOT FONT_FAMILY.
    folder = tmp_path / "Shantell copy"
    written = ff.copy_shipped(folder)

    resolution = resolve_faces(folder)

    assert resolution.source == "override"
    assert resolution.fallback == "none"
    assert resolution.family == "Shantell Sans Normal"
    assert _paths(resolution.faces) == written


def test_mt020_typesetting_sets_the_override_faces_unchanged_regular_italic_and_bold(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Boxy"
    written = ff.write_family(folder, BOXY)
    faces = resolve_faces(folder).faces

    block = typeset("*HI* **YO**", BUBBLE, faces)

    glyphs = [g for line in block.lines for g in line.glyphs]
    by_char = {g.char: g for g in glyphs}
    assert by_char["H"].font_path == written["italic"]
    assert by_char["I"].font_path == written["italic"]
    assert by_char["Y"].font_path == written["bold"]
    assert by_char["O"].font_path == written["bold"]
    assert {g.font_path for g in glyphs} <= set(written.values())
    # Every box is BOXY.advance font units wide: the override's own metrics.
    assert all(g.advance == pytest.approx(BOXY.advance * g.size_px / ff.UPM) for g in glyphs)
    assert not block.overflowed


# --- how the folder is read --------------------------------------------------------


def test_style_is_read_from_the_os2_bits_whatever_the_files_are_called(tmp_path: Path) -> None:
    # Names that LIE: "bold.ttf" holds the regular face, and so on.
    folder = tmp_path / "Liars"
    lying = {
        "regular": "bold.ttf",
        "italic": "regular.ttf",
        "bold": "italic.ttf",
        "bold_italic": "z.ttf",
    }
    written = ff.write_family(folder, BOXY, names=lying)

    resolution = resolve_faces(folder)

    assert resolution.fallback == "none"
    assert _paths(resolution.faces) == written


def test_only_otf_and_ttf_files_directly_in_the_folder_are_candidates_in_any_case(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Busy"
    names = {"regular": "f1.TTF", "italic": "f2.Ttf", "bold": "f3.OTF", "bold_italic": "f4.otf"}
    written = ff.write_family(folder, BOXY, names=names)
    # Not candidates. Each of them, if read as a font, would fail to parse.
    (folder / "OFL.txt").write_bytes(NOT_A_FONT)
    (folder / "README").write_bytes(NOT_A_FONT)
    (folder / "f5.ttf.bak").write_bytes(NOT_A_FONT)
    (folder / "f6.woff2").write_bytes(NOT_A_FONT)
    (folder / "sub.ttf").mkdir()  # a folder with a font's suffix
    (folder / "nested").mkdir()
    (folder / "nested" / "f0.ttf").write_bytes(NOT_A_FONT)  # not recursive

    resolution = resolve_faces(folder)

    assert (resolution.fallback, resolution.detail) == ("none", "")
    assert _paths(resolution.faces) == written


def test_a_second_file_of_a_filled_style_is_ignored_and_the_first_in_sorted_order_wins(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Two regulars"
    # Written second-wins-on-disk order first, so directory order cannot help.
    ff.write_family(folder, BOXY, styles=("regular",), names={"regular": "b.ttf"})
    ff.write_family(folder, WIDE, styles=("regular",), names={"regular": "a.ttf"})
    ff.write_family(
        folder,
        BOXY,
        styles=("italic", "bold", "bold_italic"),
        names={"italic": "c.ttf", "bold": "d.ttf", "bold_italic": "e.ttf"},
    )

    resolution = resolve_faces(folder)

    assert (resolution.fallback, resolution.detail) == ("none", "")
    assert resolution.faces["regular"].path == folder / "a.ttf"
    assert resolution.family == "Wide Lettering"


# =============================================================================
# AC-3: the configured path does not exist
# =============================================================================


def test_a_missing_folder_falls_back_to_shantell_and_says_the_path_does_not_exist(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "Fonts I deleted"

    resolution = resolve_faces(missing)

    _assert_default(resolution)
    assert resolution.fallback == "missing_path"
    assert resolution.detail == f"{missing} does not exist"


def test_a_fallback_uses_the_bundled_directory_it_was_given(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    ff.copy_shipped(bundled)

    resolution = resolve_faces(tmp_path / "nope", bundled)

    _assert_default(resolution, bundled)
    assert resolution.fallback == "missing_path"


# =============================================================================
# AC-4: not a parseable font
# =============================================================================


def test_a_file_in_the_folder_that_is_not_a_font_falls_back_naming_it_and_the_parse_error(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Broken"
    ff.write_family(folder, BOXY)
    bad = folder / "f0.ttf"  # sorts first; the four valid faces follow it
    bad.write_bytes(NOT_A_FONT)

    resolution = resolve_faces(folder)

    _assert_default(resolution)
    assert resolution.fallback == "unparseable"
    assert resolution.detail == f"{bad} is not a font: {ff.parse_error(NOT_A_FONT)}"


def test_a_broken_candidate_after_four_good_faces_is_still_reported(tmp_path: Path) -> None:
    # Every candidate is parsed - a second file of a filled style is ignored
    # only once it is known to be a font of that style.
    folder = tmp_path / "Broken last"
    ff.write_family(folder, BOXY)
    bad = folder / "z.otf"
    bad.write_bytes(b"")

    resolution = resolve_faces(folder)

    assert resolution.fallback == "unparseable"
    assert resolution.detail == f"{bad} is not a font: {ff.parse_error(b'')}"


def test_with_two_broken_files_the_first_in_sorted_order_is_reported(tmp_path: Path) -> None:
    folder = tmp_path / "Two broken"
    folder.mkdir()
    (folder / "b.ttf").write_bytes(b"")
    (folder / "a.ttf").write_bytes(NOT_A_FONT)

    resolution = resolve_faces(folder)

    assert resolution.detail == f"{folder / 'a.ttf'} is not a font: {ff.parse_error(NOT_A_FONT)}"


@pytest.mark.parametrize("table", ["OS/2", "cmap", "name"])
def test_a_face_without_a_table_the_check_reads_is_not_a_font(tmp_path: Path, table: str) -> None:
    folder = tmp_path / "Incomplete"
    ff.write_family(folder, BOXY, styles=("italic", "bold", "bold_italic"))
    bad = folder / FILE_NAMES["regular"]
    bad.write_bytes(ff.face_bytes(BOXY, "regular", drop_tables=[table]))

    resolution = resolve_faces(folder)

    _assert_default(resolution)
    assert resolution.fallback == "unparseable"
    assert resolution.detail == f"{bad} is not a font: no {table} table"


def test_an_override_that_names_a_file_not_a_folder_is_not_a_font(tmp_path: Path) -> None:
    # AC-4's "pointing at a file": the setting names a folder (settled), so a
    # file - even a real font file - is reported, not opened (amended row 2).
    for name, data in (("notes.txt", NOT_A_FONT), ("Boxy.ttf", ff.face_bytes(BOXY, "regular"))):
        target = tmp_path / name
        target.write_bytes(data)

        resolution = resolve_faces(target)

        _assert_default(resolution)
        assert resolution.fallback == "unparseable"
        assert resolution.detail == f"{target} is not a font: not a folder"


# =============================================================================
# AC-5: faces that parse but lack required codepoints (all four styles present)
# =============================================================================


def test_faces_lacking_the_ellipsis_and_em_dash_fall_back_naming_the_codepoints(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "No dashes"
    lacking = (ELLIPSIS, EM_DASH)
    written = ff.write_family(folder, BOXY, omit={k: lacking for k in KEYS})

    resolution = resolve_faces(folder)

    _assert_default(resolution)
    assert resolution.fallback == "missing_glyphs"
    # The first failing face in STYLE_KEYS order is the regular face.
    assert resolution.detail == f"{written['regular']} lacks U+2014, U+2026"


def test_missing_codepoints_are_listed_ascending_as_four_hex_digits(tmp_path: Path) -> None:
    folder = tmp_path / "Gappy"
    written = ff.write_family(folder, BOXY, omit={"regular": (0x2026, 0x41, 0xF1, 0x20)})

    resolution = resolve_faces(folder)

    assert resolution.detail == f"{written['regular']} lacks U+0020, U+0041, U+00F1, U+2026"


def test_the_first_face_lacking_glyphs_in_style_order_is_the_one_reported(tmp_path: Path) -> None:
    # Bold lacks the em dash, italic lacks n-tilde: italic comes first.
    folder = tmp_path / "Two gaps"
    written = ff.write_family(folder, BOXY, omit={"bold": (EM_DASH,), "italic": (0xF1,)})

    resolution = resolve_faces(folder)

    assert resolution.fallback == "missing_glyphs"
    assert resolution.detail == f"{written['italic']} lacks U+00F1"


@pytest.mark.parametrize("style", KEYS)
def test_a_gap_in_any_one_face_is_caught(tmp_path: Path, style: str) -> None:
    folder = tmp_path / "One gap"
    written = ff.write_family(folder, BOXY, omit={style: (ELLIPSIS,)})

    resolution = resolve_faces(folder)

    assert resolution.fallback == "missing_glyphs"
    assert resolution.detail == f"{written[style]} lacks U+2026"


def test_the_interrobang_is_not_required_of_an_override(tmp_path: Path) -> None:
    # REQUIRED_CODEPOINTS excludes U+203D (settled); the fixtures never have it.
    folder = tmp_path / "No interrobang"
    ff.write_family(folder, BOXY)

    assert resolve_faces(folder).fallback == "none"


# =============================================================================
# AC-6: a style without a distinct face (full coverage everywhere)
# =============================================================================


def test_four_faces_whose_style_bits_do_not_differ_fall_back_naming_the_missing_styles(
    tmp_path: Path,
) -> None:
    # Four complete files that all say "regular" - the faux-oblique family.
    folder = tmp_path / "All regular"
    ff.write_family(folder, BOXY, fs_selection={k: ff.REGULAR_BIT for k in KEYS})

    resolution = resolve_faces(folder)

    _assert_default(resolution)
    assert resolution.fallback == "missing_style"
    assert resolution.detail == f"{folder} has no italic, bold, bold italic face"


@pytest.mark.parametrize(
    ("absent", "named"),
    [
        (("bold",), "bold"),
        (("italic",), "italic"),
        (("bold_italic",), "bold italic"),
        (("regular",), "regular"),
        (("italic", "bold_italic"), "italic, bold italic"),
        (KEYS, "regular, italic, bold, bold italic"),
    ],
    ids=["bold", "italic", "bold-italic", "regular", "both-italics", "all"],
)
def test_a_folder_missing_a_style_names_exactly_the_missing_ones_in_style_order(
    tmp_path: Path, absent: tuple[str, ...], named: str
) -> None:
    folder = tmp_path / "Short"
    folder.mkdir()
    ff.write_family(folder, BOXY, styles=[k for k in KEYS if k not in absent])

    resolution = resolve_faces(folder)

    _assert_default(resolution)
    assert resolution.fallback == "missing_style"
    assert resolution.detail == f"{folder} has no {named} face"


def test_a_folder_with_only_non_font_files_has_no_face_of_any_style(tmp_path: Path) -> None:
    folder = tmp_path / "Licence only"
    folder.mkdir()
    (folder / "OFL.txt").write_bytes(NOT_A_FONT)

    resolution = resolve_faces(folder)

    assert resolution.fallback == "missing_style"
    assert resolution.detail == f"{folder} has no regular, italic, bold, bold italic face"


# =============================================================================
# The order of the checks: the first that fails is the reason
# =============================================================================


def test_a_broken_file_is_reported_before_a_missing_style(tmp_path: Path) -> None:
    folder = tmp_path / "Broken and short"
    ff.write_family(folder, BOXY, styles=("regular",))
    bad = folder / "f9.ttf"
    bad.write_bytes(NOT_A_FONT)

    resolution = resolve_faces(folder)

    assert resolution.fallback == "unparseable"
    assert resolution.detail == f"{bad} is not a font: {ff.parse_error(NOT_A_FONT)}"


def test_a_missing_style_is_reported_before_missing_glyphs(tmp_path: Path) -> None:
    folder = tmp_path / "Short and gappy"
    ff.write_family(
        folder,
        BOXY,
        styles=("regular", "italic", "bold_italic"),
        omit={"regular": (ELLIPSIS, EM_DASH)},
    )

    resolution = resolve_faces(folder)

    assert resolution.fallback == "missing_style"
    assert resolution.detail == f"{folder} has no bold face"


# =============================================================================
# validate_faces: the reused check, against an arbitrary directory
# =============================================================================


def test_validate_faces_passes_the_shipped_font_directory() -> None:
    faces, reason, detail = validate_faces(FONT_DIR)

    assert (reason, detail) == ("none", "")
    assert faces is not None
    assert _paths(faces) == dict(FACE_FILES)


def _cases(tmp_path: Path) -> dict[str, Path]:
    """One directory per outcome of `validate_faces`."""
    good = tmp_path / "good"
    ff.write_family(good, BOXY)
    broken = tmp_path / "broken"
    ff.write_family(broken, BOXY)
    (broken / "f0.ttf").write_bytes(NOT_A_FONT)
    short = tmp_path / "short"
    ff.write_family(short, BOXY, styles=("regular", "italic", "bold_italic"))
    gappy = tmp_path / "gappy"
    ff.write_family(gappy, BOXY, omit={k: (ELLIPSIS, EM_DASH) for k in KEYS})
    return {
        "none": good,
        "missing_path": tmp_path / "absent",
        "unparseable": broken,
        "missing_style": short,
        "missing_glyphs": gappy,
    }


def test_validate_faces_returns_faces_exactly_when_the_reason_is_none_and_detail_is_empty(
    tmp_path: Path,
) -> None:
    seen = {}
    for expected, directory in _cases(tmp_path).items():
        faces, reason, detail = validate_faces(directory)
        seen[expected] = (reason, faces is not None, detail == "")

    assert seen == {
        "none": ("none", True, True),
        "missing_path": ("missing_path", False, False),
        "unparseable": ("unparseable", False, False),
        "missing_style": ("missing_style", False, False),
        "missing_glyphs": ("missing_glyphs", False, False),
    }


def test_resolve_reports_exactly_what_validate_faces_found(tmp_path: Path) -> None:
    for directory in _cases(tmp_path).values():
        _, reason, detail = validate_faces(directory)
        resolution = resolve_faces(directory)
        assert (resolution.fallback, resolution.detail) == (reason, detail), directory


# =============================================================================
# AC-9 at the resolver: no residue between calls
# =============================================================================


def test_resolving_with_no_override_after_an_override_returns_the_default_unchanged(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Boxy"
    ff.write_family(folder, BOXY)
    before = resolve_faces(None)

    assert resolve_faces(folder).source == "override"
    after = resolve_faces(None)

    assert after == before
    assert (after.source, after.family, after.fallback, after.detail) == (
        "default",
        FONT_FAMILY,
        "none",
        "",
    )
    assert _paths(after.faces) == dict(FACE_FILES)


def test_resolving_a_second_override_does_not_return_the_first(tmp_path: Path) -> None:
    boxy, wide = tmp_path / "Boxy", tmp_path / "Wide"
    ff.write_family(boxy, BOXY)
    written = ff.write_family(wide, WIDE)

    resolve_faces(boxy)
    resolution = resolve_faces(wide)

    assert resolution.family == "Wide Lettering"
    assert _paths(resolution.faces) == written
