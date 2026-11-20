"""MT-123 AC-4: the bake sets English in the bubble's interior and clips to it.

Observed through the public calls only, `bake_chapter` and `preview_bake`
(Contract block 2): the private `_set_blocks` / `_bake_area` change shape in
this story, and no test calls them. *MT-155's section at the end is the
exception*: its glyph-box and block assertions call `_set_blocks` directly, as
its Contract C-5 permits, and says so there.

**The world.** One page, `_bubble_world.bubble_page()` as the cleaned image (the
closed 300 x 240 bubble, interior 255, so white under the erase mask), one
`bubble` region with the 60 x 200 polygon and two mask strokes inside it, one
`proposed` line. The source page is `_bake_world.texture` at the same size: the
bake writes the cleaned page, so source and cleaned differ everywhere outside
the bubble and an implementation that composited onto the source fails (b).

**What each assertion trusts.** (a)'s first half - ink exists outside the
polygon's fill - and (c) need nothing of `mangatl.typeset.interior` and run in
RED against today's bake, which keeps every glyph inside the column and reports
the line overflowing. The ring's fill, needed for (b) and for "inside the ring"
in (a), is `bubble_interior`'s own answer on the cleaned page, imported inside
`_ring_fill` so that the rest of the file still loads while the module is
missing. The erase mask is `_bake_world.dilated_masks`, from the pinned radius,
never `erase_mask`.

**Fixture-only controls** live here too, because this file loads in RED: the
page is light only inside the bubble (AC-1's given, asserted once), and the
plain light flood of the open page reaches the page edge (AC-2's control).

The page is 640 x 560 and each test bakes it at most once; no `pytest-timeout`
exists in this project, so there is no per-test budget to size.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Literal

import _bake_world as world
import _bubble_world as bw
import numpy as np
import pytest
from _bake_world import Spec
from numpy.typing import NDArray

from mangatl.domain.line import Line
from mangatl.domain.region import RawRegion
from mangatl.pipeline.bake import LineRef, _set_blocks, bake_chapter, preview_bake
from mangatl.store.intake import read_chapter
from mangatl.store.lines import read_review_lines
from mangatl.store.project import create_project, open_project, project_dir_for
from mangatl.typeset.fit import TypesetBlock, typeset
from mangatl.typeset.font import load_faces
from mangatl.typeset.interior import Ring, bubble_interior

SHAPE = (bw.PAGE_H, bw.PAGE_W)
SIZE = (bw.PAGE_W, bw.PAGE_H)

#: Overflows the column at the minimum size; fits the interior (at 30 px, RED).
FITS_THE_BUBBLE = "YOU WANT TO COEXIST WITH HUMANS... HUH?"

_RAMBLE = (
    "THIS LINE GOES ON AND ON AND ON, FAR LONGER THAN ANY BUBBLE COULD EVER HOPE TO"
    " HOLD, AND THEN IT KEEPS GOING WITH EVEN MORE WORDS UNTIL THE WHOLE INTERIOR IS"
    " FULL AND STILL THERE IS MORE TO SAY ABOUT IT ALL, SO MUCH MORE, MORE THAN ANYONE"
    " COULD READ IN ONE SITTING"
)

#: Overflows even the 300 x 240 interior, and by enough that the overflow
#: layout reaches far past it: measured in RED against the analytic inner
#: ellipse, 14 px, 21 lines, 158 of 422 glyph ink boxes outside the interior
#: (one `_RAMBLE` alone reached past it with 1 box of 211 - too few for the
#: clip assertion to mean anything).
TOO_LONG = f"{_RAMBLE} {_RAMBLE}"


def _region() -> RawRegion:
    return RawRegion(
        polygon=bw.POLYGON,
        mask=world.mask_png(bw.PAGE_W, bw.PAGE_H, bw.STROKES),
        confidence=0.9,
        kind="bubble",
    )


def _chapter(tmp_path: Path, text: str) -> Path:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    (source_dir / "p1.png").write_bytes(world.encode(world.texture(*SIZE, salt=3), "PNG"))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        world.seed_page(
            project,
            0,
            [_region()],
            [Spec(proposed=text)],
            world.encode(bw.bubble_page().rgb, "PNG"),
        )
    return source_dir


def _bake(source_dir: Path) -> NDArray[np.uint8]:
    output_dir = world.output_dir_for(source_dir)
    with open_project(project_dir_for(source_dir)) as project:
        bake_chapter(project, output_dir)
    return world.decode_rgb((output_dir / "p1.png").read_bytes())


def _overflowing(source_dir: Path) -> tuple[LineRef, ...]:
    with open_project(project_dir_for(source_dir)) as project:
        return preview_bake(project).overflowing


def _ink(out: NDArray[np.uint8], cleaned: NDArray[np.uint8]) -> NDArray[np.bool_]:
    """Pixels the bake made darker than the cleaned page."""
    return np.asarray(out.astype(np.int32).sum(axis=-1) < cleaned.astype(np.int32).sum(axis=-1))


def _interior_ring() -> tuple[tuple[int, int], ...]:
    """The interior `bubble_interior` finds on this page's cleaned image."""
    from mangatl.typeset.interior import bubble_interior

    return bubble_interior(bw.bubble_page().grey, bw.POLYGON, "bubble")


def _ring_fill() -> NDArray[np.bool_]:
    return bw.fill(_interior_ring(), SHAPE)


def _box_inside(ink: tuple[float, float, float, float], area: NDArray[np.bool_]) -> bool:
    x0, y0, x1, y1 = ink
    box = area[max(0, math.floor(y0)) : math.ceil(y1), max(0, math.floor(x0)) : math.ceil(x1)]
    return bool(box.all())


def _column_and_mask() -> NDArray[np.bool_]:
    """`erase_mask | polygon fill`: today's bake area, MT-021 C-3."""
    return world.dilated_masks([_region()], SIZE) | bw.fill(bw.POLYGON, SHAPE)


# -- the page itself (fixture controls; they run in RED) --------------------------------


def test_the_synthetic_page_is_light_only_inside_the_bubble() -> None:
    # AC-1's given: a non-light texture (grey < 200) everywhere but the interior.
    # `_bake_world.texture` alone is NOT that (measured luma max 223-225): the
    # control below keeps the clip in `_bubble_world.dark_texture` honest.
    closed = bw.bubble_page()
    opened = bw.bubble_page(open_gap=True)

    assert np.array_equal(closed.grey >= 200, closed.interior)
    assert np.array_equal(opened.grey >= 200, opened.interior | opened.band)
    assert int(closed.grey[closed.outline].max()) <= 120, "the outline must be dark (<= 120)"
    assert (bw.grey_of(world.texture(*SIZE)) >= 200).any(), (
        "control: the unclipped bake texture has light pixels - if it stops having"
        " them, the clip in dark_texture is no longer what makes AC-1's page"
    )


def test_a_plain_light_flood_of_the_open_bubble_leaks_to_the_page_edge() -> None:
    # AC-2's control: the leak the criterion refuses is real on this page, and
    # absent on the closed one, where the flood is exactly the interior.
    opened = bw.bubble_page(open_gap=True)
    closed = bw.bubble_page()

    assert bw.touches_page_edge(bw.plain_flood(opened.grey, bw.POLYGON))
    assert np.array_equal(bw.plain_flood(closed.grey, bw.POLYGON), closed.interior)


# -- AC-4: the bake uses the interior, and the clip follows it ---------------------------------


def test_the_bake_inks_the_bubble_outside_the_japanese_column(tmp_path: Path) -> None:
    cleaned = bw.bubble_page().rgb

    ink = _ink(_bake(_chapter(tmp_path, FITS_THE_BUBBLE)), cleaned)

    beyond_column = ink & ~bw.fill(bw.POLYGON, SHAPE)
    assert int(beyond_column.sum()) > 0, (
        "no ink outside the region's polygon: the line was still set in the column"
    )
    stray = int((beyond_column & ~_ring_fill()).sum())
    assert stray == 0, f"{stray} inked pixels lie outside both the polygon and the interior"


def test_the_bake_changes_nothing_outside_the_mask_the_column_and_the_interior(
    tmp_path: Path,
) -> None:
    source_dir = _chapter(tmp_path, FITS_THE_BUBBLE)
    source = world.decode_rgb((source_dir / "p1.png").read_bytes())
    cleaned = bw.bubble_page().rgb
    beyond = ~bw.fill(bw.POLYGON, SHAPE) & ~bw.bubble_page().interior
    differs = (source[beyond] != cleaned[beyond]).any(axis=-1).mean()
    assert differs > 0.9, (
        f"precondition: source and cleaned page differ on only {differs:.2f} of the page"
        " outside the bubble, so 'equals the cleaned page' would not tell them apart"
    )

    out = _bake(source_dir)

    outside = ~(_column_and_mask() | _ring_fill())
    changed = int((out[outside] != cleaned[outside]).any(axis=-1).sum())
    assert changed == 0, f"{changed} pixels outside the bake area differ from the cleaned page"


def test_the_render_dialog_reports_no_overflow_for_a_line_the_interior_holds(
    tmp_path: Path,
) -> None:
    assert _overflowing(_chapter(tmp_path, FITS_THE_BUBBLE)) == ()


def test_a_line_too_long_even_for_the_interior_is_reported_and_still_clipped(
    tmp_path: Path,
) -> None:
    source_dir = _chapter(tmp_path, TOO_LONG)
    cleaned = bw.bubble_page().rgb

    assert _overflowing(source_dir) == (LineRef(page_ordinal=0, reading_index=0),)
    area = _column_and_mask() | _ring_fill()
    block = typeset(TOO_LONG, _interior_ring(), load_faces())
    reaching = sum(
        1
        for line in block.lines
        for glyph in line.glyphs
        if glyph.ink is not None and not _box_inside(glyph.ink, area)
    )
    assert reaching >= 10, (
        f"precondition: only {reaching} glyph boxes of the overflowed block reach past the"
        " bake area, so the clip is barely exercised"
    )
    ink = _ink(_bake(source_dir), cleaned)
    stray = int((ink & ~area).sum())
    assert stray == 0, f"{stray} inked pixels of the overflowed line escaped the bake area"


# -- MT-155: regions sharing one balloon are each set in their own part of it ----------
#
# Contract C-2 and C-5. `_set_blocks` is the one rule `bake_chapter` and
# `preview_bake` set lines by, and a block's glyph boxes cannot be read from a
# baked PNG, so AC-1's, AC-2's and AC-6's glyph-box assertions, and AC-3's and
# AC-4's block equalities, call it directly on the fixture's grey page (C-5
# permits this). The bake itself is driven for AC-1's count, AC-2's dialog and
# AC-5's store reads. `shared_parts` is imported inside the one test that needs
# it, so the rest of this section runs - and fails on its own assertions - while
# it does not exist.

#: C-5's texts. Today each pair is set at 37/37 and 42/37 px over the whole
#: balloon with 16 and 13 intersecting glyph-box pairs (measured in RED); in the
#: parts 33/23 and 41/30, none, neither overflowed.
LOBE_TEXTS: tuple[tuple[str, str], ...] = (
    ("HELLO THERE", "GENERAL KENOBI"),
    ("One point", "is a flat rate of 10 yen."),
)
#: AC-6's texts: today A is 42 px over B's 25 px block, 6 intersecting pairs.
BALLOON_TEXT, BOX_TEXT = "One point more", "Ten yen"

Box = tuple[float, float, float, float]
Entry = tuple[int, Ring, TypesetBlock]


def _region_for(polygon: Ring, kind: Literal["bubble", "box"] = "bubble") -> RawRegion:
    """A region whose mask is one stroke rect 8 px inside its rectangle polygon."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    stroke = (min(xs) + 8, min(ys) + 8, max(xs) - 8, max(ys) - 8)
    return RawRegion(
        polygon=polygon,
        mask=world.mask_png(bw.PAGE_W, bw.PAGE_H, [stroke]),
        confidence=0.9,
        kind=kind,
    )


def _lobe_regions() -> list[RawRegion]:
    return [_region_for(bw.LEFT_LOBE_POLYGON), _region_for(bw.RIGHT_LOBE_POLYGON)]


def _proposed(index: int, text: str) -> Line:
    return Line(index, "テキスト", text, None, "proposed", None)


def _glyph_boxes(block: TypesetBlock) -> list[Box]:
    return [glyph.ink for line in block.lines for glyph in line.glyphs if glyph.ink is not None]


def _lobe_blocks(left: str, right: str) -> list[Entry]:
    return _set_blocks(
        _lobe_regions(),
        [_proposed(0, left), _proposed(1, right)],
        load_faces(),
        bw.two_lobed_page().grey,
    )


def _shared_chapter(tmp_path: Path, left: str, right: str) -> Path:
    """The two-lobed page as one chapter: two `bubble` regions, two proposals."""
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    (source_dir / "p1.png").write_bytes(world.encode(world.texture(*SIZE, salt=3), "PNG"))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        world.seed_page(
            project,
            0,
            _lobe_regions(),
            [Spec(proposed=left), Spec(proposed=right)],
            world.encode(bw.two_lobed_page().rgb, "PNG"),
        )
    return source_dir


# -- AC-1 ------------------------------------------------------------------------------


@pytest.mark.parametrize(("left", "right"), LOBE_TEXTS)
def test_each_lobe_region_is_drawn_wholly_on_its_own_side_of_the_midline(
    left: str, right: str
) -> None:
    entries = _lobe_blocks(left, right)

    assert [index for index, _, _ in entries] == [0, 1], "two blocks, one per region"
    left_x1 = max(box[2] for box in _glyph_boxes(entries[0][2]))
    right_x0 = min(box[0] for box in _glyph_boxes(entries[1][2]))
    assert left_x1 <= bw.MIDLINE_X, (
        f"the left region's English reaches x = {left_x1:.1f}, across the midline x = 320"
    )
    assert right_x0 >= bw.MIDLINE_X, (
        f"the right region's English starts at x = {right_x0:.1f}, across the midline x = 320"
    )


def test_a_bake_of_the_two_lobed_page_sets_both_regions_and_inks_both_lobes(
    tmp_path: Path,
) -> None:
    left, right = LOBE_TEXTS[0]
    source_dir = _shared_chapter(tmp_path, left, right)
    output_dir = world.output_dir_for(source_dir)
    with open_project(project_dir_for(source_dir)) as project:
        report = bake_chapter(project, output_dir)
    page = bw.two_lobed_page()
    ink = _ink(world.decode_rgb((output_dir / "p1.png").read_bytes()), page.rgb)

    assert report.regions_empty == 0, "a region sharing the balloon was left without text"
    assert ink[:, : bw.MIDLINE_X].any() and ink[:, bw.MIDLINE_X + 1 :].any()
    stray = int((ink & ~page.interior).sum())
    assert stray == 0, f"{stray} inked pixels lie outside the balloon's interior"


# -- AC-2 ------------------------------------------------------------------------------


@pytest.mark.parametrize(("left", "right"), LOBE_TEXTS)
def test_two_regions_in_one_balloon_have_no_glyph_box_over_each_other(
    left: str, right: str
) -> None:
    entries = _lobe_blocks(left, right)

    hits = bw.intersecting_pairs(_glyph_boxes(entries[0][2]), _glyph_boxes(entries[1][2]))
    assert hits == 0, f"{hits} glyph-box pairs of the two regions' English intersect"


@pytest.mark.parametrize(("left", "right"), LOBE_TEXTS)
def test_control_today_each_text_fitted_into_the_whole_balloon_collides(
    left: str, right: str
) -> None:
    # AC-2's control, the defect itself: both regions find the whole balloon,
    # and each text set there alone is drawn over the other (16 and 13 pairs).
    grey = bw.two_lobed_page().grey
    faces = load_faces()
    whole = [
        typeset(text, bubble_interior(grey, polygon, "bubble"), faces)
        for text, polygon in ((left, bw.LEFT_LOBE_POLYGON), (right, bw.RIGHT_LOBE_POLYGON))
    ]

    hits = bw.intersecting_pairs(_glyph_boxes(whole[0]), _glyph_boxes(whole[1]))
    assert hits >= 1, (
        "control: today's whole-balloon blocks do not collide on this fixture, so it"
        " cannot show AC-2"
    )


@pytest.mark.parametrize(("left", "right"), LOBE_TEXTS)
def test_each_block_in_a_shared_balloon_is_typeset_in_its_own_part(left: str, right: str) -> None:
    from mangatl.typeset.interior import shared_parts

    grey = bw.two_lobed_page().grey
    faces = load_faces()
    polygons = [bw.LEFT_LOBE_POLYGON, bw.RIGHT_LOBE_POLYGON]
    parts = shared_parts([bubble_interior(grey, p, "bubble") for p in polygons], polygons, SHAPE)

    assert _lobe_blocks(left, right) == [
        (0, parts[0], typeset(left, parts[0], faces)),
        (1, parts[1], typeset(right, parts[1], faces)),
    ]


@pytest.mark.parametrize(("left", "right"), LOBE_TEXTS)
def test_the_render_dialog_reports_neither_line_in_a_shared_balloon_overflowing(
    tmp_path: Path, left: str, right: str
) -> None:
    assert _overflowing(_shared_chapter(tmp_path, left, right)) == ()


# -- AC-3: nothing shared, set exactly as today ----------------------------------------


def _as_today(regions: list[RawRegion], texts: list[str], grey: NDArray[np.uint8]) -> list[Entry]:
    faces = load_faces()
    expected: list[Entry] = []
    for index, (region, text) in enumerate(zip(regions, texts, strict=True)):
        interior = bubble_interior(grey, region.polygon, region.kind)
        expected.append((index, interior, typeset(text, interior, faces)))
    return expected


def _set_both(regions: list[RawRegion], texts: list[str], grey: NDArray[np.uint8]) -> list[Entry]:
    lines: list[Line | None] = [_proposed(i, text) for i, text in enumerate(texts)]
    return _set_blocks(regions, lines, load_faces(), grey)


def test_two_regions_in_two_separate_balloons_are_each_set_as_today() -> None:
    grey = bw.separate_balloons_page().grey
    regions = [_region_for(bw.SEPARATE_LEFT_POLYGON), _region_for(bw.SEPARATE_RIGHT_POLYGON)]
    texts = list(LOBE_TEXTS[0])

    assert _set_both(regions, texts, grey) == _as_today(regions, texts, grey)


def test_a_box_straddling_a_balloon_outline_and_the_balloon_region_are_each_set_as_today() -> None:
    grey = bw.bubble_page().grey
    regions = [_region_for(bw.BALLOON_A_POLYGON), _region_for(bw.STRADDLING_BOX_POLYGON, "box")]
    texts = [BALLOON_TEXT, BOX_TEXT]

    assert _set_both(regions, texts, grey) == _as_today(regions, texts, grey)


# -- AC-4: a region with nothing to set takes no share ---------------------------------


def _right_lobe_without_text(case: str) -> tuple[list[RawRegion], list[Line | None]]:
    regions = _lobe_regions()
    left = _proposed(0, LOBE_TEXTS[0][0])
    right_text = LOBE_TEXTS[0][1]
    if case == "excluded":
        regions[1] = dataclasses.replace(regions[1], excluded="user")
        return regions, [left, _proposed(1, right_text)]
    if case == "no line":
        return regions, [left, None]
    if case == "failed":
        return regions, [left, Line(1, "", right_text, None, "failed", None, ocr_empty=True)]
    return regions, [left, _proposed(1, "   ")]


@pytest.mark.parametrize("case", ["excluded", "no line", "failed", "blank"])
def test_a_region_with_nothing_to_set_leaves_the_whole_balloon_to_the_other(case: str) -> None:
    grey = bw.two_lobed_page().grey
    faces = load_faces()
    regions, lines = _right_lobe_without_text(case)
    whole = bubble_interior(grey, bw.LEFT_LOBE_POLYGON, "bubble")
    alone = _set_blocks(regions[:1], lines[:1], faces, grey)

    entries = _set_blocks(regions, lines, faces, grey)

    expected = [(0, whole, typeset(LOBE_TEXTS[0][0], whole, faces))]
    assert entries == expected, f"with the right region {case}, the left lost part of the balloon"
    assert entries == alone


# -- AC-5: the bake only reads ---------------------------------------------------------


StoreReads = tuple[tuple[RawRegion, ...], tuple[Line | None, ...]]


def _store_reads(source_dir: Path) -> StoreReads:
    with open_project(project_dir_for(source_dir)) as project:
        return project.read_regions(0), read_review_lines(project, 0)


def _assert_store_unchanged(before: StoreReads, after: StoreReads) -> None:
    assert after[0] == before[0], "the page's regions read back differently after the bake"
    assert after[1] == before[1], "the page's lines read back differently after the bake"


def test_a_bake_and_a_preview_of_a_shared_balloon_leave_its_regions_and_lines_as_they_were(
    tmp_path: Path,
) -> None:
    source_dir = _shared_chapter(tmp_path, *LOBE_TEXTS[0])
    before = _store_reads(source_dir)
    assert len(before[0]) == 2 and len(before[1]) == 2 and None not in before[1]

    with open_project(project_dir_for(source_dir)) as project:
        bake_chapter(project, world.output_dir_for(source_dir))
    _assert_store_unchanged(before, _store_reads(source_dir))
    with open_project(project_dir_for(source_dir)) as project:
        preview_bake(project)
    _assert_store_unchanged(before, _store_reads(source_dir))


def test_control_the_store_comparison_reports_a_proposal_the_test_itself_changed(
    tmp_path: Path,
) -> None:
    # AC-5's test passes on arrival and has no production line to mutate: this
    # control shows the same comparison fails when the store did change.
    source_dir = _shared_chapter(tmp_path, *LOBE_TEXTS[0])
    before = _store_reads(source_dir)
    with open_project(project_dir_for(source_dir)) as project:
        project.write_proposed(0, {1: "A DIFFERENT PROPOSAL"})

    with pytest.raises(AssertionError, match="lines read back differently"):
        _assert_store_unchanged(before, _store_reads(source_dir))


# -- AC-6: one-way sharing - a box inside the balloon ----------------------------------


def _box_inside_blocks() -> list[Entry]:
    return _set_both(
        [_region_for(bw.BALLOON_A_POLYGON), _region_for(bw.INNER_BOX_POLYGON, "box")],
        [BALLOON_TEXT, BOX_TEXT],
        bw.bubble_page().grey,
    )


def test_a_balloon_holding_a_box_is_set_beside_the_box_and_not_over_it() -> None:
    entries = _box_inside_blocks()
    whole = bubble_interior(bw.bubble_page().grey, bw.BALLOON_A_POLYGON, "bubble")

    hits = bw.intersecting_pairs(_glyph_boxes(entries[0][2]), _glyph_boxes(entries[1][2]))
    assert hits == 0, f"{hits} glyph-box pairs of the balloon's English lie over the box's"
    assert entries[0][1] != whole, "the balloon region was set in its whole interior, box and all"


def test_a_box_inside_a_balloon_is_set_exactly_as_today() -> None:
    entries = _box_inside_blocks()

    expected = (1, bw.INNER_BOX_POLYGON, typeset(BOX_TEXT, bw.INNER_BOX_POLYGON, load_faces()))
    assert entries[1] == expected
