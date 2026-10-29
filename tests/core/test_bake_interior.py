"""MT-123 AC-4: the bake sets English in the bubble's interior and clips to it.

Observed through the public calls only, `bake_chapter` and `preview_bake`
(Contract block 2): the private `_set_blocks` / `_bake_area` change shape in
this story, and no test calls them.

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

import math
from pathlib import Path

import _bake_world as world
import _bubble_world as bw
import numpy as np
from _bake_world import Spec
from numpy.typing import NDArray

from mangatl.domain.region import RawRegion
from mangatl.pipeline.bake import LineRef, bake_chapter, preview_bake
from mangatl.store.intake import read_chapter
from mangatl.store.project import create_project, open_project, project_dir_for
from mangatl.typeset.fit import typeset
from mangatl.typeset.font import load_faces

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
