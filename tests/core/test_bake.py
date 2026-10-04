"""`mangatl.pipeline.bake.bake_chapter`: the finished chapter, written to `<source>_en/`.

MT-021 AC-1..AC-8 at the chapter level, and every case of the retired
`tests/core/test_export.py` re-expressed against `bake_chapter` (C-8): folder
created; exactly one file per page; reading order; a second bake replaces rather
than merges; a single page; a failure on page *k* leaves no partial and no
`.part`; the pages before it whole; a failure on page 1 leaves the folder empty;
the source folder untouched, including on failure.

Conventions kept from `test_export.py`, for its reasons:

- **The output folder is asserted by its EXACT contents** over `rglob("*")`. One
  equality catches a missing page, a partial page and a leftover temp file.
- **Failure is injected by patching `os.replace`** (C-6 requires `bake` to call
  it as `os.replace`). A bake that writes straight to the final filename never
  calls it, so the injected failure never fires, `pytest.raises` fails, and the
  test is red - that is how AC-4 sees deferred condition 1. A second failure
  path is real rather than injected: a line whose text the font cannot set
  raises `MissingGlyph` out of `typeset` (C-4), on the page under test.
- **`<source>_en` is spelled out**, not derived from the implementation.

**AC-2 on the file, and what it compares against.** Two assertions, deliberately
different in what they trust:

1. *Complement*: outside the bake area `A` - computed in `_bake_world` from the
   pinned radius and `cv2.fillPoly`, never by `erase_mask` - the decoded PNG
   equals the decoded SOURCE page exactly. No module output is involved.
2. *Composition*: the decoded PNG equals `bake_page(cleaned, blocks, A)`, with
   `blocks = typeset(effective_text(line), polygon, load_faces())` per C-4. This
   leans on `bake_page`, whose positions `test_typeset_render.py` pins exactly;
   what it adds is that the chapter bakes the CLEANED page (not the source), with
   the RIGHT text (effective, not `source_ja`), into the RIGHT polygons, clipped
   to the right `A` (one that includes the polygon fill - the masks here cover a
   small part of each bubble, so a clip of the erase mask alone cuts most ink).
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Sequence
from io import BytesIO
from pathlib import Path

import _bake_world as world
import numpy as np
import pytest
from _bake_world import Spec
from PIL import Image, JpegImagePlugin

from mangatl.domain.line import effective_text
from mangatl.domain.page import order_filenames
from mangatl.pipeline.bake import BakeReport, bake_chapter
from mangatl.store.intake import read_chapter
from mangatl.store.lines import read_review_lines
from mangatl.store.project import Project, create_project, open_project, project_dir_for
from mangatl.typeset.fit import TypesetBlock, typeset
from mangatl.typeset.font import MissingGlyph, load_faces
from mangatl.typeset.render import bake_page

SIZE = (world.PAGE_W, world.PAGE_H)

#: Text every inked region can hold at some size on the grid.
_SHORT = ("HELLO", "THERE", "OK!", "A LOT OF WORDS FOR A TINY BOX")


class _InjectedWriteFailure(OSError):
    """The injected rename failure: an `OSError`, as a real `os.replace` raises,
    and bespoke so an unrelated error cannot satisfy `pytest.raises`."""


# -- the world -----------------------------------------------------------------


def _new_project(source_dir: Path) -> Project:
    return create_project(read_chapter(source_dir), project_dir_for(source_dir))


def _write_source(source_dir: Path, pages: Sequence[tuple[str, bytes]]) -> None:
    source_dir.mkdir()
    for name, data in pages:
        (source_dir / name).write_bytes(data)


def _inked_specs() -> list[Spec]:
    """Four lines with text, all `proposed`; the last overflows its tiny box."""
    return [Spec(proposed=text) for text in _SHORT]


def _seed_inked(project: Project, ordinal: int, source: np.ndarray) -> None:
    page_regions = world.regions()
    cleaned = world.cleaned_from(source, page_regions)
    world.seed_page(project, ordinal, page_regions, _inked_specs(), world.encode(cleaned, "PNG"))


def _expected_blocks(project: Project, ordinal: int) -> list[TypesetBlock]:
    """C-4's blocks, from the store's own regions and lines, in reading order."""
    faces = load_faces()
    blocks = []
    for region, line in zip(
        project.read_regions(ordinal), read_review_lines(project, ordinal), strict=True
    ):
        if line is None or line.status == "failed" or not effective_text(line).strip():
            continue
        blocks.append(typeset(effective_text(line), region.polygon, faces))
    return blocks


def _fail_replace_onto(target: str) -> Callable[..., None]:
    real_replace = os.replace

    def replace(src: str | Path, dst: str | Path) -> None:
        if Path(dst).name == target:
            raise _InjectedWriteFailure(f"injected failure renaming onto {dst}")
        real_replace(src, dst)

    return replace


@pytest.fixture
def four_inked(tmp_path: Path) -> tuple[Path, list[str]]:
    """p1..p4, PNG, 160x120, distinct textures; every page cleaned and inked."""
    names = [f"p{i}.png" for i in range(1, 5)]
    source_dir = tmp_path / "scans"
    _write_source(
        source_dir,
        [(name, world.encode(world.texture(*SIZE, salt=i), "PNG")) for i, name in enumerate(names)],
    )
    with _new_project(source_dir) as project:
        for page in project.pages():
            source = world.decode_rgb((source_dir / page.filename).read_bytes())
            _seed_inked(project, page.ordinal, source)
    return source_dir, names


def _open(source_dir: Path) -> Project:
    return open_project(project_dir_for(source_dir))


# -- AC-1: one file per page, same names, nothing else -------------------------


def test_the_output_folder_holds_exactly_one_file_per_page_with_the_input_names(
    four_inked: tuple[Path, list[str]],
) -> None:
    source_dir, names = four_inked
    output_dir = world.output_dir_for(source_dir)

    with _open(source_dir) as project:
        bake_chapter(project, output_dir)

    assert world.contents(output_dir) == sorted(names)


def test_the_output_folder_is_created_when_it_does_not_exist_yet(
    four_inked: tuple[Path, list[str]],
) -> None:
    source_dir, _ = four_inked
    output_dir = world.output_dir_for(source_dir)
    assert not output_dir.exists()

    with _open(source_dir) as project:
        bake_chapter(project, output_dir)

    assert output_dir.is_dir()


def test_the_output_files_carry_the_chapters_names_in_its_reading_order(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    # Natural order, not lexical: p10 after p9. Put the output names through
    # the chapter's own ordering rule and they must come out as the ordinals do.
    names = ["p10.png", "p9.png", "p1.png"]
    source_dir = tmp_path / "scans"
    _write_source(source_dir, [(n, png_bytes(5 + i, 3 + i)) for i, n in enumerate(names)])
    output_dir = world.output_dir_for(source_dir)

    with _new_project(source_dir) as project:
        bake_chapter(project, output_dir)
        expected = [page.filename for page in project.pages()]

    assert (
        order_filenames(world.contents(output_dir)) == expected == ["p1.png", "p9.png", "p10.png"]
    )


def test_a_single_page_chapter_writes_a_single_file(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    source_dir = tmp_path / "scans"
    _write_source(source_dir, [("p1.png", png_bytes(7, 3))])
    output_dir = world.output_dir_for(source_dir)

    with _new_project(source_dir) as project:
        report = bake_chapter(project, output_dir)

    assert world.contents(output_dir) == ["p1.png"]
    assert report == BakeReport(
        pages_written=1, regions_empty=0, unreviewed_lines=0, pages_uncleaned=0
    )


# -- AC-2: the baked page, on the decoded PNG ----------------------------------


def test_outside_the_bake_area_every_pixel_of_every_png_equals_the_source_exactly(
    four_inked: tuple[Path, list[str]],
) -> None:
    # The complement half, on the FILE. Exact equality, no tolerance: a whole
    # page recompressed, quantised or shifted fails it; so does ink from the
    # overflowing fourth region if it is not clipped to A.
    source_dir, names = four_inked
    output_dir = world.output_dir_for(source_dir)

    with _open(source_dir) as project:
        bake_chapter(project, output_dir)
        areas = {
            p.filename: world.bake_area(project.read_regions(p.ordinal), SIZE)
            for p in project.pages()
        }

    differing = {}
    for name in names:
        source = world.decode_rgb((source_dir / name).read_bytes())
        out = world.decode_rgb((output_dir / name).read_bytes())
        outside = ~areas[name]
        bad = int((out[outside] != source[outside]).any(axis=-1).sum())
        if bad:
            differing[name] = bad
    assert differing == {}


def test_the_overflowing_region_really_reaches_past_its_bake_area(
    four_inked: tuple[Path, list[str]],
) -> None:
    # Precondition for the clip half of the test above: the fourth region's
    # block overflowed, and some of its ink lies outside A. Without this, the
    # complement test would pass for a bake that ignores the clip.
    source_dir, _ = four_inked
    with _open(source_dir) as project:
        page_regions = project.read_regions(0)
        area = world.bake_area(page_regions, SIZE)
        block = typeset(_SHORT[world.OVERFLOW], page_regions[world.OVERFLOW].polygon, load_faces())

    assert block.overflowed
    outside = 0
    for line in block.lines:
        for glyph in line.glyphs:
            if glyph.ink is None:
                continue
            x0, y0 = (max(0, math.floor(v)) for v in glyph.ink[:2])
            x1, y1 = (max(0, math.ceil(v)) for v in glyph.ink[2:])
            box = np.zeros_like(area)
            box[y0:y1, x0:x1] = True
            outside += int((box & ~area).sum())
    assert outside > 0


def test_each_png_is_the_cleaned_page_with_every_regions_block_composited_in_the_bake_area(
    four_inked: tuple[Path, list[str]],
) -> None:
    source_dir, names = four_inked
    output_dir = world.output_dir_for(source_dir)

    with _open(source_dir) as project:
        bake_chapter(project, output_dir)
        expected = {}
        for page in project.pages():
            cleaned_bytes = project.read_cleaned(page.ordinal)
            assert cleaned_bytes is not None
            area = world.bake_area(project.read_regions(page.ordinal), SIZE)
            expected[page.filename] = bake_page(
                world.decode_rgb(cleaned_bytes), _expected_blocks(project, page.ordinal), area
            )

    mismatched = [
        name
        for name in names
        if not np.array_equal(world.decode_rgb((output_dir / name).read_bytes()), expected[name])
    ]
    assert mismatched == []


def test_every_inked_region_carries_ink_and_the_page_is_not_a_copy_of_its_source(
    four_inked: tuple[Path, list[str]],
) -> None:
    # Independent of bake_page: inside each region's polygon some pixel is
    # darker than the cleaned page (ink), and the file is not the source scan.
    source_dir, names = four_inked
    output_dir = world.output_dir_for(source_dir)

    with _open(source_dir) as project:
        bake_chapter(project, output_dir)
        cleaned = world.decode_rgb(project.read_cleaned(0) or b"")
        page_regions = project.read_regions(0)

    out = world.decode_rgb((output_dir / names[0]).read_bytes())
    inked = []
    for region in page_regions:
        (x0, y0), (x1, y1) = region.polygon[0], region.polygon[2]
        darker = out[y0:y1, x0:x1].astype(int).sum(-1) < cleaned[y0:y1, x0:x1].astype(int).sum(-1)
        inked.append(bool(darker.any()))
    assert inked == [True] * len(page_regions)
    assert world.sha256_of(output_dir / names[0]) != world.sha256_of(source_dir / names[0])


# -- AC-3: filename, extension, format ------------------------------------------


def _jpeg_q95_tables() -> dict[int, list[int]]:
    """The quantisation tables Pillow writes at quality 95: content-independent."""
    buffer = BytesIO()
    Image.new("RGB", (16, 16), (90, 120, 200)).save(
        buffer, format="JPEG", quality=95, subsampling=0
    )
    with Image.open(BytesIO(buffer.getvalue())) as image:
        return {k: list(v) for k, v in image.quantization.items()}


@pytest.fixture
def mixed_formats(tmp_path: Path, jpeg_7x3_bytes: bytes) -> Path:
    """Six pages: three baked (.png, .jpg, .JPEG), three with no regions."""
    source_dir = tmp_path / "scans"
    tex = [world.texture(*SIZE, salt=i) for i in range(3)]
    _write_source(
        source_dir,
        [
            ("p1.png", world.encode(tex[0], "PNG")),
            ("p2.jpg", world.encode(tex[1], "JPEG")),
            ("p3.JPEG", world.encode(tex[2], "JPEG")),
            ("p4.png", world.encode(world.texture(40, 30, salt=9), "PNG")),
            ("p5.jpg", jpeg_7x3_bytes),
            ("p6.jpeg", world.encode(world.texture(24, 16, salt=5), "JPEG")),
        ],
    )
    with _new_project(source_dir) as project:
        for ordinal in range(3):
            page = project.pages()[ordinal]
            source = world.decode_rgb((source_dir / page.filename).read_bytes())
            _seed_inked(project, ordinal, source)
    return source_dir


def test_each_output_keeps_its_inputs_filename_and_image_format(mixed_formats: Path) -> None:
    output_dir = world.output_dir_for(mixed_formats)

    with _open(mixed_formats) as project:
        bake_chapter(project, output_dir)

    formats = {}
    for path in sorted(output_dir.iterdir()):
        with Image.open(path) as image:
            formats[path.name] = image.format
    assert formats == {
        "p1.png": "PNG",
        "p2.jpg": "JPEG",
        "p3.JPEG": "JPEG",
        "p4.png": "PNG",
        "p5.jpg": "JPEG",
        "p6.jpeg": "JPEG",
    }


@pytest.mark.parametrize("name", ["p2.jpg", "p3.JPEG"])
def test_a_baked_jpeg_is_written_at_quality_95_with_4_4_4_subsampling(
    mixed_formats: Path, name: str
) -> None:
    output_dir = world.output_dir_for(mixed_formats)

    with _open(mixed_formats) as project:
        bake_chapter(project, output_dir)

    with Image.open(output_dir / name) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == SIZE
        assert JpegImagePlugin.get_sampling(image) == 0
        assert {k: list(v) for k, v in image.quantization.items()} == _jpeg_q95_tables()
    assert world.sha256_of(output_dir / name) != world.sha256_of(mixed_formats / name)


@pytest.mark.parametrize("name", ["p4.png", "p5.jpg", "p6.jpeg"])
def test_a_page_with_no_regions_is_written_as_the_source_files_bytes(
    mixed_formats: Path, name: str
) -> None:
    output_dir = world.output_dir_for(mixed_formats)

    with _open(mixed_formats) as project:
        bake_chapter(project, output_dir)

    assert world.sha256_of(output_dir / name) == world.sha256_of(mixed_formats / name)


def test_a_greyscale_png_page_is_baked_to_rgb(tmp_path: Path) -> None:
    # C-5: output mode is RGB for every baked page.
    source_dir = tmp_path / "scans"
    grey = world.texture(*SIZE)[..., 0]
    buffer = BytesIO()
    Image.fromarray(grey, "L").save(buffer, format="PNG")
    _write_source(source_dir, [("p1.png", buffer.getvalue())])
    output_dir = world.output_dir_for(source_dir)
    with _new_project(source_dir) as project:
        _seed_inked(project, 0, world.decode_rgb(buffer.getvalue()))
        bake_chapter(project, output_dir)

    with Image.open(output_dir / "p1.png") as image:
        assert (image.format, image.mode) == ("PNG", "RGB")


# -- C-5 row 2: regions but no cleaned image ----------------------------------


def test_a_page_with_regions_but_no_cleaned_image_is_its_source_bytes_and_is_counted(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "scans"
    _write_source(
        source_dir,
        [(f"p{i}.png", world.encode(world.texture(*SIZE, salt=i), "PNG")) for i in (1, 2)],
    )
    output_dir = world.output_dir_for(source_dir)
    with _new_project(source_dir) as project:
        # Accepted lines with text: neither empty nor unreviewed, so the two
        # counts this case does not decide stay out of it.
        accepted = [Spec(proposed="HELLO", commit=("accepted", None))] * 2
        world.seed_page(project, 1, world.regions(2), accepted, cleaned=None)
        report = bake_chapter(project, output_dir)

    assert world.sha256_of(output_dir / "p2.png") == world.sha256_of(source_dir / "p2.png")
    assert report == BakeReport(
        pages_written=2, regions_empty=0, unreviewed_lines=0, pages_uncleaned=1
    )


def test_an_uncleaned_pages_proposed_lines_are_unreviewed_but_its_regions_are_not_empty(
    tmp_path: Path,
) -> None:
    # C-4 PO-6: `unreviewed_lines` counts every `proposed` line in the chapter;
    # `regions_empty` counts only regions on pages that were baked. p1 is baked
    # (1 proposed, 1 failed); p2 has regions and no cleaned image (2 proposed,
    # 1 failed). Counting p2's failed region as empty gives 2, not 1; leaving
    # p2's proposals out of `unreviewed_lines` gives 1, not 3.
    source_dir = tmp_path / "scans"
    _write_source(
        source_dir,
        [(f"p{i}.png", world.encode(world.texture(*SIZE, salt=i), "PNG")) for i in (1, 2)],
    )
    output_dir = world.output_dir_for(source_dir)
    with _new_project(source_dir) as project:
        source = world.decode_rgb((source_dir / "p1.png").read_bytes())
        baked_regions = world.regions(2)
        world.seed_page(
            project,
            0,
            baked_regions,
            [Spec(proposed="HELLO"), Spec(proposed="THERE", ocr_empty=True)],
            world.encode(world.cleaned_from(source, baked_regions), "PNG"),
        )
        world.seed_page(
            project,
            1,
            world.regions(3),
            [Spec(proposed="HELLO"), Spec(proposed="THERE"), Spec(ocr_empty=True)],
            cleaned=None,
        )
        report = bake_chapter(project, output_dir)

    assert world.sha256_of(output_dir / "p2.png") == world.sha256_of(source_dir / "p2.png")
    assert report == BakeReport(
        pages_written=2, regions_empty=1, unreviewed_lines=3, pages_uncleaned=1
    )


# -- AC-4: a bake that fails partway -------------------------------------------


_EIGHT = [f"p{i}.png" for i in range(1, 9)]


@pytest.fixture
def eight_pages(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    """p1..p8; p2 is baked (regions, cleaned, ink), the rest have no regions.

    p2 and p7 are full-size textures (p7 so a test can give it regions); the
    others are tiny distinct sizes, so a page written under the wrong name is
    visible in its bytes.
    """
    source_dir = tmp_path / "scans"
    pages = [(n, png_bytes(7 + i, 3 + i)) for i, n in enumerate(_EIGHT)]
    pages[1] = ("p2.png", world.encode(world.texture(*SIZE, salt=2), "PNG"))
    pages[6] = ("p7.png", world.encode(world.texture(*SIZE, salt=7), "PNG"))
    _write_source(source_dir, pages)
    with _new_project(source_dir) as project:
        _seed_inked(project, 1, world.decode_rgb(pages[1][1]))
    return source_dir


def _reference_bytes(source_dir: Path, tmp_path: Path) -> dict[str, str]:
    """sha256 of every page of an unfailed bake of the same project."""
    reference = tmp_path / "reference_bake"
    with _open(source_dir) as project:
        bake_chapter(project, reference)
    return {n: world.sha256_of(reference / n) for n in _EIGHT}


def test_a_rename_that_fails_on_page_seven_leaves_no_partial_page_and_no_temp_file(
    eight_pages: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Deferred condition 1: a bake that writes p7.png straight to its final
    # name never calls os.replace, so nothing raises and this test is red.
    output_dir = world.output_dir_for(eight_pages)
    monkeypatch.setattr(os, "replace", _fail_replace_onto("p7.png"))

    with _open(eight_pages) as project, pytest.raises(_InjectedWriteFailure):
        bake_chapter(project, output_dir)

    assert world.contents(output_dir) == _EIGHT[:6]


def test_the_pages_written_before_the_failure_are_whole(
    eight_pages: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _reference_bytes(eight_pages, tmp_path)
    output_dir = world.output_dir_for(eight_pages)
    monkeypatch.setattr(os, "replace", _fail_replace_onto("p7.png"))

    with _open(eight_pages) as project, pytest.raises(_InjectedWriteFailure):
        bake_chapter(project, output_dir)

    assert {n: world.sha256_of(output_dir / n) for n in _EIGHT[:6]} == {
        n: reference[n] for n in _EIGHT[:6]
    }


def test_a_line_the_font_cannot_set_fails_the_bake_on_its_page_with_nothing_partial(
    eight_pages: Path,
) -> None:
    # C-4: MissingGlyph propagates, with AC-4's guarantees. Real, not injected.
    output_dir = world.output_dir_for(eight_pages)
    with _open(eight_pages) as project:
        source = world.decode_rgb((eight_pages / "p7.png").read_bytes())
        page_regions = world.regions(1)
        world.seed_page(
            project,
            6,
            page_regions,
            [Spec(proposed="こんにちは")],
            world.encode(world.cleaned_from(source, page_regions), "PNG"),
        )

    with _open(eight_pages) as project, pytest.raises(MissingGlyph):
        bake_chapter(project, output_dir)

    assert world.contents(output_dir) == _EIGHT[:6]


def test_a_failed_rename_onto_the_first_page_leaves_the_output_folder_empty(
    eight_pages: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = world.output_dir_for(eight_pages)
    monkeypatch.setattr(os, "replace", _fail_replace_onto("p1.png"))

    with _open(eight_pages) as project, pytest.raises(_InjectedWriteFailure):
        bake_chapter(project, output_dir)

    assert world.contents(output_dir) == []


# -- AC-5: the folder matches the chapter, not the last bake ------------------


def test_a_second_bake_removes_a_stale_page_and_replaces_rather_than_merges(
    four_inked: tuple[Path, list[str]], png_bytes: Callable[..., bytes]
) -> None:
    # Deferred condition 2: without C-6's emptying, the stale file survives.
    source_dir, names = four_inked
    output_dir = world.output_dir_for(source_dir)
    reference = source_dir.parent / "reference_bake"
    with _open(source_dir) as project:
        bake_chapter(project, reference)
    expected = {n: world.sha256_of(reference / n) for n in names}
    output_dir.mkdir()
    (output_dir / "p9-from-a-previous-chapter.png").write_bytes(png_bytes(3, 3))
    (output_dir / "p1.png").write_bytes(b"stale bytes from a previous bake\n")

    with _open(source_dir) as project:
        bake_chapter(project, output_dir)

    assert world.contents(output_dir) == sorted(names)
    assert {n: world.sha256_of(output_dir / n) for n in names} == expected


# -- AC-6 and AC-8: empty regions, unreviewed lines, and the report ------------


@pytest.fixture
def reviewed_mix(tmp_path: Path) -> Path:
    """Three 160x120 pages, every region accounted for in the module table.

    p1: failed (ocr_empty, but WITH a proposal), whitespace-only proposal,
        edited to "", proposed "HELLO"            -> 3 empty, 2 unreviewed
    p2: four regions, OCR never ran (no line rows) -> 4 empty, 0 unreviewed
    p3: proposed, proposed, accepted, reverted     -> 0 empty, 2 unreviewed
    """
    source_dir = tmp_path / "scans"
    _write_source(
        source_dir,
        [(f"p{i}.png", world.encode(world.texture(*SIZE, salt=i), "PNG")) for i in (1, 2, 3)],
    )
    specs: list[list[Spec] | None] = [
        [
            Spec(proposed="HELLO", ocr_empty=True),
            Spec(proposed="   \t "),
            Spec(proposed="THERE", commit=("edited", "")),
            Spec(proposed="HELLO"),
        ],
        None,
        [
            Spec(proposed="HELLO"),
            Spec(proposed="THERE"),
            Spec(proposed="OK!", commit=("accepted", None)),
            Spec(proposed="NO", commit=("reverted", "NO")),
        ],
    ]
    with _new_project(source_dir) as project:
        for page, page_specs in zip(project.pages(), specs, strict=True):
            source = world.decode_rgb((source_dir / page.filename).read_bytes())
            page_regions = world.regions()
            world.seed_page(
                project,
                page.ordinal,
                page_regions,
                page_specs,
                world.encode(world.cleaned_from(source, page_regions), "PNG"),
            )
    return source_dir


def test_the_report_counts_empty_regions_and_unreviewed_lines_exactly(reviewed_mix: Path) -> None:
    # AC-6: failed, empty-after-strip and no-line regions are empty (3 + 4).
    # AC-8: only `proposed` lines are unreviewed (2 + 2) - the failed line on
    # p1 has a proposal and is NOT counted; the whitespace proposal IS (C-4
    # counts by status, and its status is `proposed`).
    output_dir = world.output_dir_for(reviewed_mix)

    with _open(reviewed_mix) as project:
        report = bake_chapter(project, output_dir)

    assert report == BakeReport(
        pages_written=3, regions_empty=7, unreviewed_lines=4, pages_uncleaned=0
    )


def test_an_empty_region_is_cleaned_and_left_without_ink(reviewed_mix: Path) -> None:
    # p1's first three regions are empty, the fourth is inked; p2 has no lines
    # at all. Inside every empty region's polygon the file is the CLEANED page
    # exactly; the failed line's proposal ("HELLO") is not drawn.
    output_dir = world.output_dir_for(reviewed_mix)

    with _open(reviewed_mix) as project:
        bake_chapter(project, output_dir)
        cleaned = {o: world.decode_rgb(project.read_cleaned(o) or b"") for o in (0, 1)}

    p1 = world.decode_rgb((output_dir / "p1.png").read_bytes())
    p2 = world.decode_rgb((output_dir / "p2.png").read_bytes())
    inked = []
    for (x0, y0, x1, y1), _ in world.REGION_GEOMETRY:
        inked.append(not np.array_equal(p1[y0:y1, x0:x1], cleaned[0][y0:y1, x0:x1]))
    assert inked == [False, False, False, True]
    assert np.array_equal(p2, cleaned[1])


def test_unreviewed_lines_do_not_stop_the_bake(reviewed_mix: Path) -> None:
    output_dir = world.output_dir_for(reviewed_mix)

    with _open(reviewed_mix) as project:
        bake_chapter(project, output_dir)

    assert world.contents(output_dir) == ["p1.png", "p2.png", "p3.png"]


# -- AC-7: the source folder is read, never written ----------------------------


def test_baking_touches_nothing_in_the_source_folder(four_inked: tuple[Path, list[str]]) -> None:
    source_dir, names = four_inked
    output_dir = world.output_dir_for(source_dir)
    before = world.snapshot(source_dir)
    assert sum(1 for v in before.values() if v is not None) == len(names)

    with _open(source_dir) as project:
        bake_chapter(project, output_dir)

    assert world.snapshot(source_dir) == before
    assert output_dir.parent == source_dir.parent, "the output folder is a sibling, not a child"


def test_a_bake_that_fails_partway_still_touches_nothing_in_the_source_folder(
    eight_pages: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The temp file lives in the OUTPUT folder, never beside the scans.
    output_dir = world.output_dir_for(eight_pages)
    before = world.snapshot(eight_pages)
    assert sum(1 for v in before.values() if v is not None) == len(_EIGHT)
    monkeypatch.setattr(os, "replace", _fail_replace_onto("p7.png"))

    with _open(eight_pages) as project, pytest.raises(_InjectedWriteFailure):
        bake_chapter(project, output_dir)

    assert world.snapshot(eight_pages) == before
