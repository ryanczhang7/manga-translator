"""AC-8: the column merge on the real detector, on `011.jpg` and `014.jpg`.

Oracle-free, in the story's sense: there is no settled number to read out here,
so the assertions are the two facts a page can be asked about directly - no
output region is confined to a ruby column, and merging leaves strictly fewer
regions than the detector emitted on the same run.

**Everything here is marked `gpu` and never runs on CI** (MT-002 PO-1). The
pages and the weights live under `spikes/**`, which `.gitignore` covers - they
are non-redistributable scans of a commercial release and a GPL-3.0 model's
weights - and a checkout without them skips.

**The four ruby rectangles are annotations, measured in MT-008 RED.** PO-1 names
them: the ruby beside the kanji in boxes 6, 4 and 2 of `011.jpg` and in box 1 of
`014.jpg`. Their coordinates were taken from the art rather than from the model:
the greyscale page was thresholded at 128, the ink column belonging to the ruby
was separated from its parent column at the empty pixel columns between them,
and the ink bounding box was padded by **2px** on every side. The padding is not
taste - it is measured. Without it, the control below fires on two of the four
rectangles instead of four, because the detector's 0.50 probability threshold
finds a pixel or two more of each glyph than an ink threshold of 128 does.

**Why "confined" is measured against the rectangle grown by the dilation
reach.** `regions_from_detection` dilates every surviving component by
`DILATE_ITERATIONS` iterations of a `DILATE_KERNEL_SIDE` element before the
second fence, which grows it by three pixels per iteration in every direction.
A region whose ink is a ruby column and nothing else therefore comes out six
pixels larger than the ruby on each side, and a containment test against the
tight rectangle would be satisfied by no region at all - it would pass whatever
the detector did. The reach is read from the shipped constants, so a story that
changes the dilation moves this test with it.

**What RED measured, on `CUDAExecutionProvider`, 2026-09-16** (the story's
`## Handoff` carries the table):

- shipped pipeline: 0 regions confined to any of the four rectangles;
- control, `dilate_iterations=0`: 4, 2, 1 and 4 regions confined to rectangles
  A, B, C and D respectively - so the guard can fire, and what stops it firing
  today is MT-007's dilation rather than a vacuous predicate;
- region counts: `011.jpg` 12 before merging, `014.jpg` 10.

**Timings.** One inference is ~30ms and building the session costs a few
seconds once, which is why the session is module-scoped; the two pages are
detected once each into a module-scoped fixture, so both criteria are asserted
against the same run. `pytest-timeout` is not a dependency of this project and
no per-test timeout exists, so there is no budget in this file to size - if a
later story adds one, every hook here needs one too.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.detect.columns import merge_columns
from mangatl.detect.postprocess import (
    DILATE_ITERATIONS,
    DILATE_KERNEL_SIDE,
    decode_boxes,
    integer_boxes,
    letterbox,
    probability_to_page,
    regions_from_detection,
)
from mangatl.detect.session import DetectorSession, load_detector
from mangatl.domain.region import RawRegion

pytestmark = pytest.mark.gpu

_SPIKES = Path(__file__).resolve().parents[2] / "spikes"
_MODEL = _SPIKES / "MT-002" / "models" / "comic-text-detector-onnx" / "comic-text-detector.onnx"
_PAGES = _SPIKES / "MT-002" / "pages"
_PROVIDERS = ("CUDAExecutionProvider", "CPUExecutionProvider")

#: The four ruby columns of the corpus, as half-open `(x0, y0, x1, y1)` page
#: rectangles on the 1125x1600 scans. Ink bounding boxes padded by 2px; see the
#: module docstring for how they were taken and why the padding is there.
_RUBY: dict[str, dict[str, tuple[int, int, int, int]]] = {
    "011.jpg": {
        "011 box 6, ruby beside the first kanji pair": (947, 77, 962, 138),
        "011 box 4, ruby beside the second kanji pair": (214, 886, 225, 925),
        "011 box 2, ruby beside the pillar kanji": (133, 1165, 150, 1201),
    },
    "014.jpg": {
        "014 box 1, ruby beside the demon kanji": (1060, 557, 1076, 611),
    },
}

#: How far the dilation carries a component beyond its own ink, in page pixels.
_REACH = DILATE_ITERATIONS * (DILATE_KERNEL_SIDE // 2)


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path} is not present: gitignored spike data, see the module docstring")


@pytest.fixture(scope="module")
def session() -> Iterator[DetectorSession]:
    _require(_MODEL)
    yield load_detector(_MODEL, _PROVIDERS)


@pytest.fixture(scope="module")
def detected(
    session: DetectorSession,
) -> dict[str, tuple[list[RawRegion], list[RawRegion], tuple[int, int]]]:
    """`(before merging, after merging, page size)` per page, from one run each.

    The count criterion compares a page against itself, so both sides must come
    out of the same inference - a fixture that detected twice could be satisfied
    by two different runs.
    """
    out: dict[str, tuple[list[RawRegion], list[RawRegion], tuple[int, int]]] = {}
    for name in _RUBY:
        _require(_PAGES / name)
        with Image.open(_PAGES / name) as image:
            page = np.asarray(image.convert("RGB"), dtype=np.uint8)
        height, width = page.shape[:2]
        canvas, transform = letterbox(page)
        raw = session.run(canvas)
        boxes = decode_boxes(raw.blk, transform, (width, height))
        prob = probability_to_page(raw.seg, transform, (width, height))
        before = regions_from_detection(prob, boxes, (width, height))
        after = merge_columns(before, integer_boxes(boxes, width, height))
        out[name] = (before, after, (width, height))
    return out


def _mask_bbox(region: RawRegion, size: tuple[int, int]) -> tuple[int, int, int, int]:
    """The half-open bounding box of the region's set mask pixels."""
    with Image.open(BytesIO(region.mask)) as image:
        array: NDArray[np.bool_] = np.array(image, dtype=bool)
    assert array.shape == (size[1], size[0])
    ys, xs = np.nonzero(array)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


@pytest.mark.parametrize("page", sorted(_RUBY))
def test_no_output_region_is_confined_to_an_annotated_ruby_column(
    page: str,
    detected: dict[str, tuple[list[RawRegion], list[RawRegion], tuple[int, int]]],
) -> None:
    """AC-8's first clause, and EPIC-03's done-when: no ruby column appears as a
    region of its own.

    Measured, this is already true before MT-008 - MT-007's dilation absorbs all
    four ruby columns into their parent region (PO-1). The criterion pins it as a
    standing regression guard so that the epic's promise is attached to a test
    rather than to a paragraph, and so that a later story cannot lose it while
    tuning the dilation.
    """
    _before, after, size = detected[page]
    boxes = {region_index: _mask_bbox(region, size) for region_index, region in enumerate(after)}

    confined = {
        label: [index for index, box in boxes.items() if _inside(box, rect, _REACH)]
        for label, rect in _RUBY[page].items()
    }

    assert confined == {label: [] for label in _RUBY[page]}


def _inside(box: tuple[int, int, int, int], rect: tuple[int, int, int, int], reach: int) -> bool:
    return (
        rect[0] - reach <= box[0]
        and rect[1] - reach <= box[1]
        and box[2] <= rect[2] + reach
        and box[3] <= rect[3] + reach
    )


@pytest.mark.parametrize("page", sorted(_RUBY))
def test_merging_leaves_strictly_fewer_regions_than_the_detector_emitted(
    page: str,
    detected: dict[str, tuple[list[RawRegion], list[RawRegion], tuple[int, int]]],
) -> None:
    """AC-8's second clause: the harm D11 names, measured on the real pages.

    Both counts come from the same run, so a detector that found nothing cannot
    satisfy this - `0 < 0` is false - and the second assertion says out loud that
    regions survive rather than being merged away.
    """
    before, after, _size = detected[page]

    assert len(after) < len(before), (
        f"{page}: {len(before)} regions before merging and {len(after)} after."
        " On this corpus 7 of 25 boxes split one utterance into per-column"
        " regions; at least one of them is on this page."
    )
    assert len(after) >= 1


@pytest.mark.parametrize("page", sorted(_RUBY))
def test_a_merged_region_names_the_regions_it_absorbed(
    page: str,
    detected: dict[str, tuple[list[RawRegion], list[RawRegion], tuple[int, int]]],
) -> None:
    """AC-8 tied back to AC-1 on real data: the count did not drop because
    regions were discarded. Every absorbed index is an index into the pre-merge
    sequence, and the merges account exactly for the regions that disappeared.
    """
    before, after, _size = detected[page]
    absorbed = [index for region in after for index in region.merged_from]

    assert absorbed, f"{page}: no region records a merge, so the count cannot have dropped"
    assert sorted(absorbed) == sorted(set(absorbed))
    assert all(0 <= index < len(before) for index in absorbed)
    assert len(before) - len(after) == len(absorbed) - sum(
        1 for region in after if region.merged_from
    )
