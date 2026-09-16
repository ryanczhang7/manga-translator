"""`RawRegion.merged_from`: which input regions a region absorbed (MT-008 C-2).

MT-007 wrote `tests/core/test_region.py` and this file leaves it alone; MT-008
adds one field and pins it here, next to the round trip that carries it
(`test_region_store_merged_from.py`) rather than inside another story's suite.

**Standard library only, for the reason MT-007 gave.** `architecture.md` §3
contract 2 forbids `domain` from importing `numpy`, `PIL`, `PySide6`,
`onnxruntime` or `anthropic`, and the `lint` gate enforces it through
import-linter. A test of a module that may not import those would be testing the
opposite of the architecture if it imported them itself, so the float below
stands in for the `numpy.int32` that C-2's `int` check really exists for: it is
not an `int`, and `json.dumps` refuses it on the way into the store.

**Every validation branch gets its own case** because `coverage-core` demands
100% of `src/mangatl/domain/**`, and a branch nothing exercises is a line the
gate reports.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest

from mangatl.domain.region import RawRegion

_CLOSED_TRIANGLE: tuple[tuple[int, int], ...] = ((10, 10), (30, 10), (30, 40), (10, 10))


def _region(one_bit_png: Callable[..., bytes], **overrides: object) -> RawRegion:
    fields: dict[str, object] = {
        "polygon": _CLOSED_TRIANGLE,
        "mask": one_bit_png(320, 240, [(10, 10, 30, 40)]),
        "confidence": 0.8,
        "kind": "bubble",
    }
    fields.update(overrides)
    return RawRegion(**fields)  # type: ignore[arg-type]


def test_a_region_that_absorbed_nothing_records_no_merge(
    one_bit_png: Callable[..., bytes],
) -> None:
    """C-2's default. It is `()` rather than `None` so that every reader can
    iterate without a branch, and so that MT-007's construction sites keep
    compiling untouched."""
    assert _region(one_bit_png).merged_from == ()


def test_a_merged_region_records_the_indices_it_absorbed(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1's half that is a type rather than an algorithm."""
    region = _region(one_bit_png, merged_from=(0, 2))

    assert region.merged_from == (0, 2)


def test_merged_from_is_part_of_what_makes_two_regions_equal(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-9 asserts a round trip, and a round trip that could not tell `(0, 2)`
    from `()` would be satisfied by a store that dropped the column. This is the
    assertion that makes the round trip mean something."""
    merged = _region(one_bit_png, merged_from=(0, 2))
    unmerged = _region(one_bit_png)

    assert merged != unmerged
    assert merged == _region(one_bit_png, merged_from=(0, 2))


def test_merged_from_cannot_be_edited_in_place(one_bit_png: Callable[..., bytes]) -> None:
    """The field joins a frozen value. A later stage that wants a different merge
    builds a new region (MT-007 C-7)."""
    region = _region(one_bit_png, merged_from=(0, 2))

    with pytest.raises(dataclasses.FrozenInstanceError):
        region.merged_from = (1,)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("merged_from", "why"),
    [
        ((0.0, 1), "a float index - what a numpy.int32 looks like to json.dumps"),
        (("0", 1), "a string index"),
        ((None,), "no index at all"),
    ],
)
def test_a_merged_from_index_that_is_not_an_int_is_refused_naming_the_field(
    merged_from: tuple[object, ...],
    why: str,
    one_bit_png: Callable[..., bytes],
) -> None:
    """C-2. `numpy.int32` is not a subclass of `int` and `json.dumps` refuses it,
    and this field is JSON on its way to the store - so it is caught here, where
    the message names the field, rather than in the store two layers away."""
    with pytest.raises(ValueError, match="merged_from"):
        _region(one_bit_png, merged_from=merged_from)
    assert why  # the reason is documentation, not an assertion


@pytest.mark.parametrize("merged_from", [(-1,), (0, -2), (-1, -1)])
def test_a_negative_merged_from_index_is_refused_naming_the_field(
    merged_from: tuple[int, ...],
    one_bit_png: Callable[..., bytes],
) -> None:
    """Indices into the input sequence, so there is no such thing as a negative
    one - and Python would read `-1` as the last region rather than as an error."""
    with pytest.raises(ValueError, match="merged_from"):
        _region(one_bit_png, merged_from=merged_from)


@pytest.mark.parametrize("merged_from", [(0, 0), (1, 2, 1), (3, 3, 3)])
def test_a_repeated_merged_from_index_is_refused_naming_the_field(
    merged_from: tuple[int, ...],
    one_bit_png: Callable[..., bytes],
) -> None:
    """A region absorbed once cannot be absorbed twice. A duplicate means the
    merge walked the same input twice, which is a defect in the caller and is
    silent everywhere downstream."""
    with pytest.raises(ValueError, match="merged_from"):
        _region(one_bit_png, merged_from=merged_from)


@pytest.mark.parametrize("merged_from", [(), (0,), (0, 1), (1, 2), (4, 7, 11)])
def test_every_well_formed_index_tuple_is_accepted(
    merged_from: tuple[int, ...],
    one_bit_png: Callable[..., bytes],
) -> None:
    """The legal side of all three rules, including the empty tuple and a set of
    indices that is neither contiguous nor starting at zero: `merge_columns` is
    handed emission order, and the columns of one bubble need not be adjacent in
    it."""
    assert _region(one_bit_png, merged_from=merged_from).merged_from == merged_from
