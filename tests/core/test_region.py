"""`mangatl.domain.region`: the region value the detector emits.

Covers the half of AC-1 that is a *type* rather than an algorithm - a polygon in
page pixel coordinates, a 1-bit page-sized mask, a mean confidence and a kind -
and every validation branch of it, because `coverage-core` demands 100% of
`src/mangatl/domain/**` and a validation nothing exercises is a line the gate
will report.

**Why `mask` is `bytes` and not an array.** `architecture.md` §3 contract 2
forbids `domain` from importing `numpy`, `PIL`, `PySide6`, `onnxruntime` or
`anthropic`, and the `lint` gate enforces it through import-linter. So the
encoding happens in `detect` and the domain carries the encoded bytes. This
whole file is standard library only for the same reason: it is a test of a
module that may not import anything else, and a test that dragged numpy in
would be testing something the architecture forbids.

The validation rules are MT-007 amendment A-9, written into the story's C-7 in
RED. They exist because AC-5 stores these values in SQLite and MT-009 reads them
back: a `numpy.int32` coordinate is not JSON-serialisable and a polygon that
does not close cannot be filled, and both failures would otherwise surface two
stories later in code that did not cause them.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest

from mangatl.domain.region import RawRegion

# A closed triangle: three distinct vertices and the first repeated. This is the
# smallest polygon the validation accepts, so it is also the boundary case.
_CLOSED_TRIANGLE: tuple[tuple[int, int], ...] = ((10, 10), (30, 10), (30, 40), (10, 10))


def test_a_region_carries_its_polygon_mask_confidence_and_kind(
    one_bit_png: Callable[..., bytes],
) -> None:
    mask = one_bit_png(320, 240, [(10, 10, 30, 40)])
    region = RawRegion(
        polygon=_CLOSED_TRIANGLE,
        mask=mask,
        confidence=0.8,
        kind="bubble",
    )

    assert region.polygon == _CLOSED_TRIANGLE
    assert region.mask == mask
    assert region.confidence == pytest.approx(0.8)
    assert region.kind == "bubble"


def test_a_region_is_frozen_so_a_stage_cannot_edit_one_in_place(
    one_bit_png: Callable[..., bytes],
) -> None:
    """The detector's output is a value. MT-008 merges furigana by building a
    new region, not by mutating one it was handed."""
    region = RawRegion(
        polygon=_CLOSED_TRIANGLE,
        mask=one_bit_png(320, 240, [(10, 10, 30, 40)]),
        confidence=0.8,
        kind="bubble",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        region.confidence = 0.9  # type: ignore[misc]


def test_two_regions_with_the_same_values_are_equal(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-5 asserts a round trip, and a round trip needs equality to mean
    'the same region' rather than 'the same object'."""
    mask = one_bit_png(320, 240, [(10, 10, 30, 40)])
    first = RawRegion(polygon=_CLOSED_TRIANGLE, mask=mask, confidence=0.8, kind="bubble")
    second = RawRegion(polygon=_CLOSED_TRIANGLE, mask=bytes(mask), confidence=0.8, kind="bubble")

    assert first == second
    assert first is not second


# -- validation: one test per branch, because coverage-core demands all of them --


@pytest.mark.parametrize(
    ("polygon", "why"),
    [
        (((10, 10), (30, 10), (10, 10)), "three vertices is a line, not a polygon"),
        ((), "no vertices at all"),
        (((10, 10), (30, 10), (30, 40)), "not closed: the last vertex is not the first"),
        (((10, 10), (30, 10), (30, 40), (11, 10)), "closed against the wrong vertex"),
    ],
)
def test_a_polygon_that_is_not_a_closed_ring_is_refused_naming_the_field(
    polygon: tuple[tuple[int, int], ...],
    why: str,
    one_bit_png: Callable[..., bytes],
) -> None:
    with pytest.raises(ValueError, match="polygon"):
        RawRegion(
            polygon=polygon,
            mask=one_bit_png(320, 240, [(10, 10, 30, 40)]),
            confidence=0.8,
            kind="bubble",
        )
    assert why  # the reason is documentation, not an assertion


@pytest.mark.parametrize(
    ("polygon", "why"),
    [
        (((-1, 10), (30, 10), (30, 40), (-1, 10)), "a negative x is off the page"),
        (((10, -2), (30, 10), (30, 40), (10, -2)), "a negative y is off the page"),
        (((10, 10), (30.5, 10), (30, 40), (10, 10)), "a float coordinate"),
    ],
)
def test_a_polygon_coordinate_that_is_not_a_non_negative_int_is_refused(
    polygon: tuple[tuple[int, int], ...],
    why: str,
    one_bit_png: Callable[..., bytes],
) -> None:
    """The float case is not pedantry. `regions_from_detection` gets its
    contours from an array library, whose integers are `numpy.int32` rather than
    `int`; `json.dumps` refuses those, and AC-5's store writes the polygon as
    JSON. Catching it here names the field instead of failing in the store."""
    with pytest.raises(ValueError, match="polygon"):
        RawRegion(
            polygon=polygon,
            mask=one_bit_png(320, 240, [(10, 10, 30, 40)]),
            confidence=0.8,
            kind="bubble",
        )
    assert why


@pytest.mark.parametrize(
    ("mask", "why"),
    [
        (b"", "no mask at all"),
        (b"not a png", "not an image"),
        (b"\x89PNH\r\n\x1a\n" + b"\x00" * 16, "one byte wrong in the signature"),
    ],
)
def test_a_mask_that_is_not_png_encoded_is_refused_naming_the_field(mask: bytes, why: str) -> None:
    with pytest.raises(ValueError, match="mask"):
        RawRegion(polygon=_CLOSED_TRIANGLE, mask=mask, confidence=0.8, kind="bubble")
    assert why


@pytest.mark.parametrize("confidence", [-0.0001, -1.0, 1.0001, 2.0])
def test_a_confidence_outside_zero_to_one_is_refused_naming_the_field(
    confidence: float,
    one_bit_png: Callable[..., bytes],
) -> None:
    """`confidence` is a MEAN PROBABILITY (C-7), so the closed interval [0, 1] is
    its whole range. A value outside it means the mean was taken over the wrong
    array - a logit, a 0-255 mask - and that is worth a loud failure."""
    with pytest.raises(ValueError, match="confidence"):
        RawRegion(
            polygon=_CLOSED_TRIANGLE,
            mask=one_bit_png(320, 240, [(10, 10, 30, 40)]),
            confidence=confidence,
            kind="bubble",
        )


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_both_ends_of_the_probability_range_are_accepted(
    confidence: float,
    one_bit_png: Callable[..., bytes],
) -> None:
    """The boundary on the legal side. A region of pure background scores 0.0 and
    a saturated one scores 1.0 - the `seg` head's measured range on `012.jpg` is
    exactly [0.0, 1.0] (MT-007 C-7), so both are reachable."""
    region = RawRegion(
        polygon=_CLOSED_TRIANGLE,
        mask=one_bit_png(320, 240, [(10, 10, 30, 40)]),
        confidence=confidence,
        kind="bubble",
    )
    assert region.confidence == pytest.approx(confidence)


@pytest.mark.parametrize("kind", ["", "sfx", "Bubble", "panel"])
def test_a_kind_outside_the_two_the_schema_allows_is_refused_naming_the_field(
    kind: str,
    one_bit_png: Callable[..., bytes],
) -> None:
    with pytest.raises(ValueError, match="kind"):
        RawRegion(
            polygon=_CLOSED_TRIANGLE,
            mask=one_bit_png(320, 240, [(10, 10, 30, 40)]),
            confidence=0.8,
            kind=kind,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("kind", ["bubble", "box"])
def test_both_kinds_the_detector_can_emit_are_accepted(
    kind: str,
    one_bit_png: Callable[..., bytes],
) -> None:
    """Both are reachable, measured: on `011-015.jpg` the detector's box head
    emits class 1 for every speech bubble and class 0 for the free-floating
    scanlation watermark (MT-007 amendment A-4). `box` is not a placeholder."""
    region = RawRegion(
        polygon=_CLOSED_TRIANGLE,
        mask=one_bit_png(320, 240, [(10, 10, 30, 40)]),
        confidence=0.8,
        kind=kind,  # type: ignore[arg-type]
    )
    assert region.kind == kind
