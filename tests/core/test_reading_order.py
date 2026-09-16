"""MT-009: regions are ordered right to left, top to bottom.

Reading direction is **settled**, not decided here: Japanese reads right to left,
so the greatest x-centre comes first, and y increases downward with the page's
top-left at (0, 0). See `docs/backlog/stories/MT-009.md` `## Contract`.

Three kinds of test live in this file, and they are kept apart on purpose.

- **Mechanical** (AC-1..AC-4, AC-7, plus the transitivity and tie-break clauses
  of `## Contract`): synthetic rectangles placed by hand, pinned exactly.
- **Property** (AC-5): a `hypothesis` property over generated polygons.
- **Oracle-free** (AC-6): the committed, geometry-only fixtures under
  `fixtures/reading-order/`, hand-annotated from the page art in RED, before
  `mangatl.domain.reading_order` existed. See that directory's README.

`BAND_OVERLAP_FRACTION`'s *value* is GREEN's to settle from the fixtures. The
boundary tests below therefore never name a number: they reconstruct the
constant as an exact rational and build geometry whose overlap fraction is
exactly it, one pixel under it and one pixel over it.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mangatl.domain.reading_order import BAND_OVERLAP_FRACTION, order_regions, sort_regions
from mangatl.domain.region import RawRegion

# -- geometry helpers ---------------------------------------------------------

PAGE_W = 1125
PAGE_H = 1600


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    """A box as the closed ring `RawRegion` requires: last vertex repeats the first."""
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def _region(mask: bytes, x0: int, y0: int, x1: int, y1: int) -> RawRegion:
    return RawRegion(polygon=_ring(x0, y0, x1, y1), mask=mask, confidence=0.9, kind="bubble")


def _x_centre(region: RawRegion) -> float:
    xs = [x for x, _ in region.polygon[:-1]]
    return (min(xs) + max(xs)) / 2


# -- AC-1: one band reads right to left ---------------------------------------


def test_regions_in_a_single_band_come_out_right_to_left(page_mask: bytes) -> None:
    # All four share the vertical extent [100, 300], so they are one band under
    # any band fraction at all. Input order is deliberately scrambled.
    regions = [
        _region(page_mask, 400, 100, 500, 300),  # 0: x-centre 450
        _region(page_mask, 900, 100, 1000, 300),  # 1: x-centre 950
        _region(page_mask, 100, 100, 200, 300),  # 2: x-centre 150
        _region(page_mask, 650, 100, 750, 300),  # 3: x-centre 700
    ]

    assert order_regions(regions) == [1, 3, 0, 2], (
        "Japanese reads right to left: the greatest x-centre comes first"
    )
    assert [_x_centre(r) for r in sort_regions(regions)] == [950.0, 700.0, 450.0, 150.0]


# -- AC-2: an upper band precedes a lower one whatever the x --------------------


def test_every_region_in_the_upper_band_precedes_every_region_in_the_lower_band(
    page_mask: bytes,
) -> None:
    # The upper band sits entirely on the LEFT and the lower band entirely on
    # the RIGHT, so a comparator that sorted by x alone would interleave them.
    regions = [
        _region(page_mask, 100, 100, 200, 200),  # 0: upper, x-centre 150
        _region(page_mask, 1000, 900, 1100, 1000),  # 1: lower, x-centre 1050
        _region(page_mask, 300, 100, 400, 200),  # 2: upper, x-centre 350
        _region(page_mask, 700, 900, 800, 1000),  # 3: lower, x-centre 750
    ]

    assert order_regions(regions) == [2, 0, 1, 3], (
        "both upper-band regions must precede both lower-band regions, even though"
        " both lower-band regions are further right"
    )


# -- AC-3 / AC-4: the band boundary, pinned without naming the constant ---------
#
# `BAND_OVERLAP_FRACTION` is unbound in RED. It is recovered here as an exact
# rational p/q, and the geometry is scaled by q so that an overlap of exactly
# p * SCALE pixels over a shorter extent of exactly q * SCALE pixels is the
# boundary *to the pixel*. `test_the_band_fraction_is_a_proper_fraction...`
# below asserts the reconstruction is exact, so a constant this trick cannot
# represent fails loudly instead of testing the wrong boundary.

_F = Fraction(BAND_OVERLAP_FRACTION).limit_denominator(10_000)
_SCALE = max(1, round(400 / _F.denominator))
#: The shorter region's vertical extent, in pixels.
_EXTENT = _F.denominator * _SCALE
#: The overlap, in pixels, at which the fraction is *exactly* the constant.
_OVERLAP_AT = _F.numerator * _SCALE


def test_the_band_fraction_is_a_proper_fraction_with_an_exact_rational_form() -> None:
    """The constant must be a proper fraction the boundary tests can straddle.

    A fraction of 0 bands every region with every other and a fraction of 1
    demands total containment; neither makes "the same band" mean anything, and
    neither leaves room for a pixel either side of the boundary.
    """
    assert 0 < BAND_OVERLAP_FRACTION < 1, (
        "BAND_OVERLAP_FRACTION is the fraction of the SHORTER vertical extent that"
        f" must overlap; it must be a proper fraction, got {BAND_OVERLAP_FRACTION!r}"
    )
    assert float(_F) == BAND_OVERLAP_FRACTION, (
        f"{BAND_OVERLAP_FRACTION!r} is not exactly representable as a rational with"
        f" denominator <= 10000 (best effort {_F}); the AC-3/AC-4 boundary geometry"
        " below would then straddle the wrong number"
    )
    assert _OVERLAP_AT / _EXTENT == BAND_OVERLAP_FRACTION
    assert _EXTENT - _OVERLAP_AT >= 2, (
        "the boundary geometry needs at least one pixel of headroom either side"
    )


def _boundary_pair(mask: bytes, overlap: int) -> list[RawRegion]:
    """A short LEFT region above a tall RIGHT one, overlapping by exactly `overlap`.

    Index 0 is the shorter region (extent `_EXTENT`) and is both **higher** and
    **further left**; index 1 is twice as tall and further right. So the two
    possible answers are distinguishable: banded gives `[1, 0]` (right to left),
    not banded gives `[0, 1]` (top to bottom).
    """
    tall_top = _EXTENT - overlap
    return [
        _region(mask, 100, 0, 200, _EXTENT),
        _region(mask, 800, tall_top, 900, tall_top + 2 * _EXTENT),
    ]


def test_regions_overlapping_by_more_than_the_band_fraction_are_one_band(
    page_mask: bytes,
) -> None:
    regions = _boundary_pair(page_mask, _OVERLAP_AT + 1)

    assert order_regions(regions) == [1, 0], (
        f"an overlap of {_OVERLAP_AT + 1}px over a shorter extent of {_EXTENT}px is"
        f" more than {BAND_OVERLAP_FRACTION}, so these are one band and read right"
        " to left"
    )


def test_regions_overlapping_by_less_than_the_band_fraction_are_two_bands(
    page_mask: bytes,
) -> None:
    regions = _boundary_pair(page_mask, _OVERLAP_AT - 1)

    assert order_regions(regions) == [0, 1], (
        f"an overlap of {_OVERLAP_AT - 1}px over a shorter extent of {_EXTENT}px is"
        f" less than {BAND_OVERLAP_FRACTION}, so the higher region comes first even"
        " though it is further left"
    )


def test_regions_overlapping_by_exactly_the_band_fraction_are_one_band(
    page_mask: bytes,
) -> None:
    """The boundary is inclusive: at exactly the fraction, the two band.

    `## Contract` as planned said only "must overlap by `BAND_OVERLAP_FRACTION`"
    and left the comparison open. RED amended it to `>=`, because "must overlap
    by f" reads as f being sufficient, and a half-open rule with no stated side
    is the kind of gap two implementations disagree about silently.
    """
    regions = _boundary_pair(page_mask, _OVERLAP_AT)

    assert order_regions(regions) == [1, 0], (
        f"an overlap of exactly {_OVERLAP_AT}px over a shorter extent of {_EXTENT}px"
        f" is exactly {BAND_OVERLAP_FRACTION}, which bands (the comparison is >=)"
    )


def test_a_tall_region_bands_with_a_short_one_that_sits_inside_its_span(
    page_mask: bytes,
) -> None:
    """The fraction is of the SHORTER extent, and that choice is what this pins.

    A short region wholly inside a tall one's vertical span overlaps 100% of its
    own extent but only a little of the tall one's. Measuring against the taller
    extent would refuse the band and read these top-to-bottom instead.
    """
    regions = [
        _region(page_mask, 100, 700, 200, 760),  # 0: short, left, 60px tall
        _region(page_mask, 900, 0, 1000, 1500),  # 1: tall, right, 1500px tall
    ]

    assert order_regions(regions) == [1, 0], (
        "the short region sits inside the tall one's span, so they are one band and"
        " the right-hand one comes first"
    )


# -- `## Contract`: banding is transitive within a sweep, not pairwise ---------
#
# Three equal-height regions stepped down the page so that A bands with B and B
# bands with C, but A does not band with C. The step is 3/4 of the largest step
# that still bands, expressed over the same exact rational as above, so it
# straddles the constant whatever GREEN settles it to.

_G = 1 - _F  # the fraction of the extent that may NOT overlap and still band
_T_SCALE = max(1, round(100 / _G.denominator))
_T_EXTENT = 4 * _G.denominator * _T_SCALE
_T_STEP = 3 * _G.numerator * _T_SCALE


def test_three_regions_chained_by_overlap_form_one_band_not_two(page_mask: bytes) -> None:
    """A-B band, B-C band, A-C do not: all three belong to one band.

    A pairwise implementation anchored on the first member puts {A, B} in one
    band and C in another, which reads `[B, A, C]`. The transitive answer is
    `[C, B, A]` — C is furthest right, so in one band it comes first.
    """
    # Guard the construction itself, so a bad rational announces itself here
    # rather than as a mysterious ordering failure.
    assert (_T_EXTENT - _T_STEP) / _T_EXTENT >= BAND_OVERLAP_FRACTION, "A and B must band"
    assert max(0, _T_EXTENT - 2 * _T_STEP) / _T_EXTENT < BAND_OVERLAP_FRACTION, (
        "A and C must not band"
    )

    regions = [
        _region(page_mask, 250, 0, 350, _T_EXTENT),  # 0 = A, x-centre 300
        _region(page_mask, 450, _T_STEP, 550, _T_STEP + _T_EXTENT),  # 1 = B, 500
        _region(page_mask, 850, 2 * _T_STEP, 950, 2 * _T_STEP + _T_EXTENT),  # 2 = C, 900
    ]

    assert order_regions(regions) == [2, 1, 0], (
        "banding is transitive within a sweep: A-B and B-C chained make one band of"
        " all three, read right to left. [1, 0, 2] is the pairwise answer."
    )


# -- `## Contract`: ties break on x first, then on input index ------------------


def test_regions_sharing_an_x_centre_in_one_band_keep_their_input_order(
    page_mask: bytes,
) -> None:
    """A total order needs a final tie-break, and it is the input index."""
    regions = [
        _region(page_mask, 400, 100, 600, 300),  # 0: x-centre 500
        _region(page_mask, 450, 100, 550, 300),  # 1: x-centre 500, narrower
    ]

    assert order_regions(regions) == [0, 1], (
        "two regions with the same x-centre in the same band break the tie on their"
        " position in the input, so the order is total"
    )
    assert order_regions(list(reversed(regions))) == [0, 1]


# -- AC-7: zero regions and one region -----------------------------------------


def test_ordering_no_regions_gives_an_empty_result() -> None:
    assert order_regions([]) == []
    assert sort_regions([]) == []


def test_ordering_a_single_region_gives_that_region_alone(page_mask: bytes) -> None:
    only = _region(page_mask, 500, 500, 600, 600)

    assert order_regions([only]) == [0]
    assert sort_regions([only]) == [only]


def test_ordering_does_not_mutate_the_sequence_it_was_given(page_mask: bytes) -> None:
    regions = [
        _region(page_mask, 100, 100, 200, 300),
        _region(page_mask, 900, 100, 1000, 300),
    ]
    before = list(regions)

    order_regions(regions)
    sort_regions(regions)

    assert regions == before, "ordering is a pure function; it must not sort in place"


def test_a_zero_height_region_is_ordered_without_raising(page_mask: bytes) -> None:
    """A zero-area region is a real MT-007 output if `MIN_REGION_AREA_PX` is wrong.

    Ordering must not divide by its extent and must not crash. Where it lands is
    `## Contract`'s zero-extent clause: a zero-extent region bands with another
    when their closed vertical extents touch, so this one joins the tall region's
    band and the right-hand region comes first.
    """
    regions = [
        _region(page_mask, 100, 400, 300, 400),  # 0: zero height, left
        _region(page_mask, 900, 200, 1000, 800),  # 1: tall, right
    ]

    assert order_regions(regions) == [1, 0]


# -- AC-5: a deterministic permutation, as a property --------------------------
#
# The generator is narrowed in exactly one way, against a named design clause:
# polygons have at least three distinct points and lie within the page, which is
# `RawRegion`'s own contract ("a closed ring ... in page pixel coordinates",
# `src/mangatl/domain/region.py`) and MT-007 AC-4. Degenerate polygons are
# deliberately NOT excluded - zero-area and collinear rings are generated, and
# `test_a_zero_height_region_is_ordered_without_raising` pins the same case by
# hand. "The test was failing on a degenerate rectangle" would not have been a
# reason to narrow it.

_points = st.tuples(st.integers(min_value=0, max_value=PAGE_W), st.integers(0, PAGE_H))
_free_polygons = st.lists(_points, min_size=3, max_size=6).map(lambda pts: (*pts, pts[0]))

# MEASURED in RED: uniform points over the page almost never produce the *chained*
# vertical overlap that distinguishes transitive banding from pairwise banding, so
# the property caught a pairwise implementation only sometimes and took 17-34 s to
# shrink when it did. Deferred verification 3 says in as many words that when this
# happens "the generator needs widening, not the assertion loosening" - so here is
# the widening. Tops come off a coarse grid and heights off a small set, which makes
# regions that share and partly share bands common. This ADDS density; it removes
# nothing, because `_free_polygons` above still samples the whole page uniformly.
_banded_boxes = st.builds(
    lambda x0, w, y0, h: _ring(x0, y0, x0 + w, y0 + h),
    x0=st.integers(min_value=0, max_value=900),
    w=st.sampled_from([0, 40, 100, 220]),
    y0=st.sampled_from([0, 60, 120, 180, 240, 300, 360, 420, 900, 960, 1020]),
    h=st.sampled_from([0, 100, 200, 300, 400]),
)
_polygons = st.one_of(_free_polygons, _banded_boxes)


def _x_centres(order: Sequence[int], regions: Sequence[RawRegion]) -> list[float]:
    return [_x_centre(regions[i]) for i in order]


# `@given` is given its strategies by KEYWORD, not positionally. Positional
# strategies bind to the *last* arguments, which here would swallow the
# `page_mask` fixture and leave pytest hunting for a fixture called `polygons`.
@given(polygons=st.lists(_polygons, max_size=8), rnd=st.randoms())
@settings(deadline=None, max_examples=100)
def test_order_regions_is_a_deterministic_permutation_of_its_input_indices(
    polygons: list[tuple[tuple[int, int], ...]],
    rnd: random.Random,
    page_mask: bytes,
) -> None:
    regions = [
        RawRegion(polygon=p, mask=page_mask, confidence=0.5, kind="bubble") for p in polygons
    ]

    order = order_regions(regions)

    assert sorted(order) == list(range(len(regions))), (
        "order_regions returns INPUT INDICES: every index present once, none"
        f" repeated, none invented. Got {order!r} for {len(regions)} regions."
    )
    assert sort_regions(regions) == [regions[i] for i in order], (
        "sort_regions must return exactly the regions order_regions names, in that"
        " order - position is the only carrier of reading order (PO-1)"
    )
    assert order_regions(regions) == order, "the same input twice must give the same order"

    # Input-order independence, projected onto x-centres. The projection is not a
    # weakening: `## Contract` breaks ties on the INPUT INDEX, so two regions
    # sharing an x-centre may legitimately swap when the input is shuffled, and
    # only their identities change - never the sequence of x-centres. Transitive
    # banding is input-order independent; the pairwise variant is not, and fails
    # this clause on roughly one generated example in ten (MEASURED in RED, see
    # `## Handoff`). That is what makes deferred verification 3 falsifiable.
    permutation = list(range(len(regions)))
    rnd.shuffle(permutation)
    shuffled = [regions[i] for i in permutation]

    assert _x_centres(order_regions(shuffled), shuffled) == _x_centres(order, regions), (
        "the reading order must not depend on the sequence the regions arrived in;"
        " a band computed pairwise rather than transitively does"
    )


# -- AC-6: the committed, hand-annotated fixture pages --------------------------

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "reading-order"


def _load_pages() -> list[dict[str, object]]:
    pages = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(_FIXTURE_DIR.glob("*.json"))]
    assert pages, f"no reading-order fixtures found under {_FIXTURE_DIR}"
    return pages


def _regions_of(page: dict[str, object], mask: bytes, mirrored: bool = False) -> list[RawRegion]:
    """Build regions from a page's BOXES ONLY.

    `mirrored` reflects every box about the page's vertical centre line. That
    turns the module's right-to-left sweep into a left-to-right one *without a
    second implementation to disagree with*: banding reads vertical extent only,
    which the reflection leaves untouched, so the only thing that changes is the
    direction of the x comparison. That is exactly AC-6's control.
    """
    width = int(page["page_size"][0])  # type: ignore[index]
    out = []
    for x0, y0, x1, y1 in page["boxes"]:  # type: ignore[union-attr]
        if mirrored:
            x0, x1 = width - x1, width - x0
        out.append(_region(mask, x0, y0, x1, y1))
    return out


def _conventional() -> list[dict[str, object]]:
    return [p for p in _load_pages() if p["layout"] == "conventional"]


def _unusual() -> list[dict[str, object]]:
    return [p for p in _load_pages() if p["layout"] == "unusual"]


def test_the_fixture_set_has_enough_conventional_pages_to_score() -> None:
    """A scored set that quietly emptied would make AC-6 pass by vacuity."""
    conventional = _conventional()

    assert len(conventional) >= 3, (
        f"AC-6 scores only `conventional` pages; {len(conventional)} is not enough"
        " for the criterion to mean anything"
    )
    assert _unusual(), (
        "at least one `unusual` page must be present: it is what carries the"
        " independence control below"
    )


def test_every_conventional_fixture_page_is_ordered_exactly_as_annotated(
    page_mask: bytes,
) -> None:
    conventional = _conventional()
    wrong = []
    for page in conventional:
        produced = order_regions(_regions_of(page, page_mask))
        if produced != page["reading_order"]:
            wrong.append(
                f"{page['source']}: produced {produced}, annotated {page['reading_order']}"
            )

    assert not wrong, (
        "AC-6: every conventional page must match its annotation exactly\n" + "\n".join(wrong)
    )


def test_a_left_to_right_ordering_matches_no_conventional_fixture_page(
    page_mask: bytes,
) -> None:
    """Control: reading the same pages the other way round must score zero.

    If it does not, the fixtures do not discriminate direction and AC-6 is
    measuring nothing.
    """
    conventional = _conventional()
    matched = [
        str(page["source"])
        for page in conventional
        if order_regions(_regions_of(page, page_mask, mirrored=True)) == page["reading_order"]
    ]

    assert matched == [], (
        "a left-to-right sweep must match 0 of"
        f" {len(conventional)} conventional pages; it matched {matched}"
    )


def test_the_unusual_pages_are_ordered_differently_from_their_annotation(
    page_mask: bytes,
) -> None:
    """The control that catches ground truth generated by the rule under test.

    PO-3: if these annotations had been produced by running a right-to-left band
    sweep over the boxes, AC-6 would compare an implementation against itself and
    the left-to-right control would still report success. The `unusual` pages are
    annotated from the art and the art disagrees with a panel-blind sweep - so a
    machine-generated ground truth would make this test red.
    """
    unusual = _unusual()
    agreed = [
        str(page["source"])
        for page in unusual
        if order_regions(_regions_of(page, page_mask)) == page["reading_order"]
    ]

    assert agreed == [], (
        "every `unusual` page must DISAGREE with the produced order - that"
        " disagreement is the evidence the annotation was read off the art rather"
        f" than computed from the boxes. These agreed: {agreed}"
    )


# -- `## Out of scope`: geometry only, never what a region says -----------------


def test_the_fixture_labels_are_review_material_and_never_reach_the_ordering(
    page_mask: bytes,
) -> None:
    """`## Out of scope`: any use of what a region *says* has changed the design.

    The fixtures carry `labels` so a human can check the annotation by eye - that
    reviewability is what PO-3's independence claim rests on. This pins that the
    labels are for the reader and not for the code: strip them and nothing the
    ordering sees changes.
    """
    for page in _load_pages():
        assert len(page["labels"]) == len(page["boxes"])  # type: ignore[arg-type]
        stripped = {k: v for k, v in page.items() if k != "labels"}

        assert _regions_of(stripped, page_mask) == _regions_of(page, page_mask), (
            f"{page['source']}: the regions handed to the ordering are built from"
            " `boxes` alone; a loader that read `labels` would fail here"
        )


@pytest.mark.parametrize("key", ["source", "page_size", "layout", "boxes", "reading_order"])
def test_every_fixture_page_carries_the_fields_the_contract_pins(key: str) -> None:
    for page in _load_pages():
        assert key in page, f"{page.get('source', '?')} is missing `{key}`"
        assert page["layout"] in ("conventional", "unusual")
        assert sorted(page["reading_order"]) == list(range(len(page["boxes"])))  # type: ignore[arg-type]
