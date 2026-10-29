"""MT-123 AC-5: the user's four pages come out unclipped and filled.

**Everything here is marked `pages` and never runs on CI** (Contract block 5).
The pages and their project live under `spikes/MT-123/mato/`, gitignored: a
scanlation raw, non-redistributable (Contract block 7). A checkout without them
skips, with the path in the message.

**What is read, and from where (story PO-1, checked in RED).** The copied
`project.db`'s `chapter.source_dir` still names
`C:\\Users\\ryanc\\Downloads\\mato sample`. Nothing here reads the source
folder: regions, lines and the CLEANED images all come out of the store
(`read_regions`, `read_review_lines`, `read_cleaned`), and `preview_bake` only
derives the output folder's path from `source_dir`, never touches it. The
project is opened on a **copy** in a temp directory, because `open_project`
migrates an older schema in place.

**Every bubble line is set as `bake_chapter` sets it** (Contract block 2):
`typeset(effective_text(line), bubble_interior(grey, region.polygon,
region.kind), load_faces())`, for each region whose line is present, not
`failed` and not blank, with `grey` the cleaned PNG through PIL
`convert("L")`. AC-5(a) is also read through the public `preview_bake`, which
is the bake's own rule and needs nothing of this file's composition.

**AC-5(b)'s denominator is this file's own reference interior** (Contract
block 6), importing nothing of `mangatl.typeset.interior`: the 4-connected
component of `grey >= 200` holding the most light pixels of the polygon's fill,
clipped to the window, united with the polygon fill. On an open bubble it
overstates the bubble, which makes the fill a lower bound.

**Oracle partition** (Contract block 4): (a), (c), (d) are exact counts; (b) is
oracle-free and its threshold, 0.20, is the story's, not tuned here. Each
discriminating metric carries a control that runs in this file, against today's
layout, and must fire:

| Metric | Fixed bar | Control, and what RED measured (2026-10-29) |
|---|---|---|
| (a) overflowed bubble lines | 0 | `typeset(text, polygon)`: 12 of 17 |
| (b) per-page median fill | >= 0.20 | `typeset(text, polygon)`: 0.069 / 0.089 / 0.089 / 0.101 |
| (c) glyph ink boxes on dark | 0 | `typeset(text, window)`: 159 of 489 boxes, 17 of 17 bubbles |

Measured in RED under the Contract's rule as amended (block 1 rule 6, the star
minus the closed dark mask) with a scratch implementation, not the shipped one:
0 overflow, 0 of 489 boxes on dark, medians 0.330 / 0.345 / 0.342 / 0.246.
Those are claims until GREEN measures them against `interior.py`.

**Timings.** One pass over the 17 lines in each layout is a few seconds on this
machine; each layout is computed once into a module-scoped fixture. No
`pytest-timeout` exists in this project, so there is no budget to size.
"""

from __future__ import annotations

import math
import shutil
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.domain.line import effective_text
from mangatl.domain.region import RawRegion
from mangatl.pipeline.bake import LineRef, preview_bake
from mangatl.store.lines import read_review_lines
from mangatl.store.project import open_project
from mangatl.typeset.fit import TypesetBlock, typeset
from mangatl.typeset.font import Faces, load_faces

pytestmark = pytest.mark.pages

_MATO = Path(__file__).resolve().parents[2] / "spikes" / "MT-123" / "mato"
_DB = _MATO / "project.db"
_PAGES = ("007.jpg", "008.jpg", "009.jpg", "016.jpg")
_TITLE = "Chapter 134: God's Proposal"

#: Contract block 1, written out: the reference interior must not agree with an
#: implementation that changed one of these.
_LIGHT_GREY = 200
_CAP_RATIO = 1.0

#: AC-5(b)'s bar, and the bar its control must fall under.
_MIN_MEDIAN_FILL = 0.20
_TODAY_FILL_BELOW = 0.12


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path} is not present: gitignored spike data, see the module docstring")


@dataclass(frozen=True)
class _Set:
    """One line the bake sets: where, what, and the cleaned page under it."""

    page: str
    ordinal: int
    index: int
    region: RawRegion
    text: str
    grey: NDArray[np.uint8]


# -- the test's own geometry (Contract block 6) ----------------------------------------------------


def _fill(polygon: Sequence[tuple[int, int]], shape: tuple[int, ...]) -> NDArray[np.bool_]:
    filled = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(filled, [np.array(polygon, dtype=np.int32)], 1)
    return filled.astype(bool)


def _window(
    polygon: Sequence[tuple[int, int]], shape: tuple[int, ...]
) -> tuple[int, int, int, int]:
    """Inclusive `(x0, y0, x1, y1)`: bbox grown by CAP_RATIO x max(w, h), clipped."""
    height, width = shape[:2]
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    grow = _CAP_RATIO * max(x1 - x0, y1 - y0)
    return (
        max(0, math.floor(x0 - grow)),
        max(0, math.floor(y0 - grow)),
        min(width - 1, math.ceil(x1 + grow)),
        min(height - 1, math.ceil(y1 + grow)),
    )


def _reference_interior(line: _Set) -> NDArray[np.bool_]:
    grey, polygon = line.grey, line.region.polygon
    fill = _fill(polygon, grey.shape)
    light = grey >= _LIGHT_GREY
    count, labels = cv2.connectedComponents(light.astype(np.uint8), connectivity=4)
    votes = np.bincount(labels[light & fill], minlength=count)
    votes[0] = 0  # label 0 is the non-light background
    component = labels == int(votes.argmax())
    x0, y0, x1, y1 = _window(polygon, grey.shape)
    window = np.zeros_like(component)
    window[y0 : y1 + 1, x0 : x1 + 1] = True
    return np.asarray((component & window) | fill)


def _fill_ratio(block: TypesetBlock, line: _Set) -> float:
    area = sum(text_line.advance * text_line.height for text_line in block.lines)
    return area / float(_reference_interior(line).sum())


def _median_fill_per_page(
    lines: Sequence[_Set], blocks: Sequence[TypesetBlock]
) -> dict[str, float]:
    by_page: dict[str, list[float]] = {}
    for line, block in zip(lines, blocks, strict=True):
        by_page.setdefault(line.page, []).append(_fill_ratio(block, line))
    return {page: statistics.median(fills) for page, fills in by_page.items()}


def _boxes_on_dark(block: TypesetBlock, line: _Set) -> tuple[int, int]:
    """(glyph ink boxes touching a dark pixel outside the polygon, ink boxes)."""
    grey = line.grey
    height, width = grey.shape
    dark = (grey < _LIGHT_GREY) & ~_fill(line.region.polygon, grey.shape)
    hits = total = 0
    for text_line in block.lines:
        for glyph in text_line.glyphs:
            if glyph.ink is None:
                continue
            total += 1
            x0, y0, x1, y1 = glyph.ink
            box = dark[
                max(0, math.floor(y0)) : min(height, math.ceil(y1)),
                max(0, math.floor(x0)) : min(width, math.ceil(x1)),
            ]
            hits += bool(box.any())
    return hits, total


# -- the chapter, read once ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def project_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _require(_MATO)
    _require(_DB)
    directory = tmp_path_factory.mktemp("mato")
    shutil.copyfile(_DB, directory / "project.db")
    return directory


@pytest.fixture(scope="module")
def set_lines(project_copy: Path) -> tuple[_Set, ...]:
    """Every line the bake would set, in page then reading order."""
    out: list[_Set] = []
    with open_project(project_copy) as project:
        for page in project.pages():
            cleaned = project.read_cleaned(page.ordinal)
            assert cleaned is not None, f"{page.filename} has no cleaned image in the project"
            with Image.open(BytesIO(cleaned)) as image:
                grey = np.asarray(image.convert("L"))
            lines = read_review_lines(project, page.ordinal)
            regions = project.read_regions(page.ordinal)
            for index, (region, line) in enumerate(zip(regions, lines, strict=True)):
                if line is None or line.status == "failed" or not effective_text(line).strip():
                    continue
                out.append(
                    _Set(page.filename, page.ordinal, index, region, effective_text(line), grey)
                )
    return tuple(out)


@pytest.fixture(scope="module")
def faces() -> Faces:
    return load_faces()


@pytest.fixture(scope="module")
def bubbles(set_lines: tuple[_Set, ...]) -> tuple[_Set, ...]:
    return tuple(line for line in set_lines if line.region.kind == "bubble")


def _layout(
    lines: Sequence[_Set], faces: Faces, where: Callable[[_Set], Sequence[tuple[int, int]]]
) -> tuple[TypesetBlock, ...]:
    return tuple(typeset(line.text, where(line), faces) for line in lines)


@pytest.fixture(scope="module")
def fitted(bubbles: tuple[_Set, ...], faces: Faces) -> tuple[TypesetBlock, ...]:
    """The bubble lines as the bake sets them after MT-123."""
    from mangatl.typeset.interior import bubble_interior

    return _layout(
        bubbles,
        faces,
        lambda line: bubble_interior(line.grey, line.region.polygon, line.region.kind),
    )


@pytest.fixture(scope="module")
def today(bubbles: tuple[_Set, ...], faces: Faces) -> tuple[TypesetBlock, ...]:
    """The control: the bubble lines set in the detector's column, as before MT-123."""
    return _layout(bubbles, faces, lambda line: line.region.polygon)


def _name(line: _Set) -> str:
    return f"{line.page}#{line.index}"


# -- the sample is the one the story measured ------------------------------------------------------


def test_the_sample_sets_seventeen_bubble_lines_and_one_titled_box(
    set_lines: tuple[_Set, ...],
) -> None:
    assert sorted({line.page for line in set_lines}) == list(_PAGES)
    assert sum(line.region.kind == "bubble" for line in set_lines) == 17
    boxes = [(line.page, line.text) for line in set_lines if line.region.kind == "box"]
    assert boxes == [("007.jpg", _TITLE)]


# -- AC-5(a): no bubble line overflows -------------------------------------------------------------


def test_todays_column_layout_overflows_bubble_lines_on_the_sample(
    bubbles: tuple[_Set, ...], today: tuple[TypesetBlock, ...]
) -> None:
    # Control for (a): measured 12 of 17 in RED.
    over = [_name(line) for line, block in zip(bubbles, today, strict=True) if block.overflowed]
    assert len(over) >= 1, "control: today's layout overflows nothing, so (a) cannot discriminate"


def test_no_bubble_line_on_the_users_pages_overflows(
    bubbles: tuple[_Set, ...], fitted: tuple[TypesetBlock, ...]
) -> None:
    over = [
        f"{_name(line)} at {block.size_px:g} px"
        for line, block in zip(bubbles, fitted, strict=True)
        if block.overflowed
    ]
    assert over == [], f"{len(over)} of {len(bubbles)} bubble lines overflow: {over}"


def test_the_render_dialog_names_no_bubble_line_as_overflowing(
    project_copy: Path, bubbles: tuple[_Set, ...]
) -> None:
    # The bake's own rule, read through the public preview. The 007 title (a
    # `box`, unchanged by this story) may still overflow; no bubble may.
    bubble_refs = {LineRef(line.ordinal, line.index) for line in bubbles}
    with open_project(project_copy) as project:
        overflowing = preview_bake(project).overflowing

    named = sorted(
        (ref.page_ordinal, ref.reading_index) for ref in overflowing if ref in bubble_refs
    )
    assert named == [], f"the Render dialog names {len(named)} bubble lines overflowing: {named}"


# -- AC-5(b): the bubble is filled -----------------------------------------------------------------


def test_todays_column_layout_fills_under_an_eighth_of_every_page_s_bubbles(
    bubbles: tuple[_Set, ...], today: tuple[TypesetBlock, ...]
) -> None:
    # Control for (b): the metric is seen to separate before it is trusted.
    # Measured in RED: 0.069 / 0.089 / 0.089 / 0.101.
    medians = _median_fill_per_page(bubbles, today)

    assert sorted(medians) == list(_PAGES)
    high = {page: round(m, 3) for page, m in medians.items() if not m < _TODAY_FILL_BELOW}
    assert high == {}, f"control: today's median fill is not under {_TODAY_FILL_BELOW}: {high}"


def test_every_page_s_median_bubble_fill_is_at_least_a_fifth(
    bubbles: tuple[_Set, ...], fitted: tuple[TypesetBlock, ...]
) -> None:
    medians = _median_fill_per_page(bubbles, fitted)

    assert sorted(medians) == list(_PAGES)
    low = {page: round(m, 3) for page, m in medians.items() if not m >= _MIN_MEDIAN_FILL}
    assert low == {}, f"pages whose median bubble fill is under {_MIN_MEDIAN_FILL}: {low}"


# -- AC-5(c): the bigger text stays off the art ----------------------------------------------------


def test_a_layout_that_ignores_the_outline_puts_glyphs_on_the_art_of_every_bubble(
    bubbles: tuple[_Set, ...], faces: Faces
) -> None:
    # Control for (c): set into the window rectangle - an interior that ignores
    # the outline. Measured in RED: 159 of 489 boxes, on 17 of 17 bubbles.
    def window_ring(line: _Set) -> tuple[tuple[int, int], ...]:
        x0, y0, x1, y1 = _window(line.region.polygon, line.grey.shape)
        return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))

    blocks = _layout(bubbles, faces, window_ring)

    clean = [
        _name(line)
        for line, block in zip(bubbles, blocks, strict=True)
        if _boxes_on_dark(block, line)[0] == 0
    ]
    assert clean == [], f"control: the window layout keeps off the art on {clean}"


def test_no_glyph_on_the_users_pages_lands_on_outline_or_art(
    bubbles: tuple[_Set, ...], fitted: tuple[TypesetBlock, ...]
) -> None:
    hits = {}
    total = 0
    for line, block in zip(bubbles, fitted, strict=True):
        on_dark, boxes = _boxes_on_dark(block, line)
        total += boxes
        if on_dark:
            hits[_name(line)] = on_dark
    assert hits == {}, f"glyph ink boxes on dark pixels outside the polygon ({total} boxes): {hits}"


# -- AC-5(d): the title is unchanged ---------------------------------------------------------------


def test_the_chapter_title_box_is_set_exactly_as_before(
    set_lines: tuple[_Set, ...], faces: Faces
) -> None:
    from mangatl.typeset.interior import bubble_interior

    (title,) = [line for line in set_lines if line.region.kind == "box"]

    block = typeset(
        title.text, bubble_interior(title.grey, title.region.polygon, title.region.kind), faces
    )

    assert block == typeset(title.text, title.region.polygon, faces)
