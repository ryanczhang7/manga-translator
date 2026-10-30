"""`RawRegion.excluded`: why a region is out of translation (MT-118 AC-1, C-1).

MT-007 wrote `tests/core/test_region.py` and MT-008 `test_region_merged_from.py`;
this story adds one field and pins it here, beside its own round trip
(`test_region_store_excluded.py`), rather than inside another story's suite -
and so that, while the field does not exist, the older suites keep running.

`None` is "included". `"watermark"` is the detector's rule (MT-121) and `"user"`
the workspace's (MT-120); nothing else is a reason, and the store's CHECK
(`test_schema_v8.py`) refuses anything else too. The domain refuses it first, so
the error names the field rather than surfacing as an `IntegrityError` two
layers away from its cause - `region.py`'s own reason for validating.

**Standard library only, for the reason MT-007 gave**: `domain` may not import
anything the architecture forbids it, and a test of it should not either.

**Every validation branch gets its own case** because `coverage-core` demands
100% of `src/mangatl/domain/**`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import get_args

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


# -- the exported names (C-1) ------------------------------------------------------


def test_the_two_exclusion_reasons_are_exported_as_a_constant_and_a_literal_type() -> None:
    """C-1: `EXCLUSION_REASONS` is the tuple the validation and the store's
    `set_excluded` both check against, in this order, and `ExclusionReason` is
    the `Literal` naming the same two values. `__all__` names both.

    Imported inside the test so that, while the names do not exist, only this
    test fails at the import and every other test here fails on its own line."""
    import mangatl.domain.region as module

    assert module.EXCLUSION_REASONS == ("watermark", "user")
    assert get_args(module.ExclusionReason) == ("watermark", "user")
    # MT-119 C-1 adds `included`, the one filter; `test_region.py` pins it.
    assert sorted(module.__all__) == [
        "EXCLUSION_REASONS",
        "ExclusionReason",
        "RawRegion",
        "included",
    ]


# -- AC-1: accepted and read back ------------------------------------------------


def test_a_region_built_without_mentioning_exclusion_is_included(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1's default: `None`, which is "included". Every one of the 80 existing
    construction sites relies on it."""
    assert _region(one_bit_png).excluded is None


def test_an_explicit_none_is_accepted_as_included(one_bit_png: Callable[..., bytes]) -> None:
    """`set_excluded(..., None)` clears; a caller building a region with the
    cleared value must be able to say so explicitly too."""
    assert _region(one_bit_png, excluded=None).excluded is None


@pytest.mark.parametrize("reason", ["watermark", "user"])
def test_each_exclusion_reason_is_accepted_and_reads_back_as_given(
    one_bit_png: Callable[..., bytes], reason: str
) -> None:
    """AC-1: both reasons, each read back exactly."""
    assert _region(one_bit_png, excluded=reason).excluded == reason


# -- AC-1: refused, naming the field -----------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "",  # the empty string is not "no reason"; None is
        "Watermark",  # case matters: the CHECK compares exactly
        "USER",
        " user",
        "users",
        "none",  # the word, not the value
        "bubble",  # a `kind`, not a reason
        "excluded",
    ],
)
def test_a_reason_outside_the_two_is_refused_naming_the_field(
    one_bit_png: Callable[..., bytes], reason: str
) -> None:
    """AC-1: "given any other string, then `ValueError` names `excluded`"."""
    with pytest.raises(ValueError, match=r"\bexcluded\b"):
        _region(one_bit_png, excluded=reason)


def test_the_refusal_quotes_the_value_it_refused(one_bit_png: Callable[..., bytes]) -> None:
    """The neighbouring fields' messages quote what they were given (`kind must
    be one of ...; got 'sfx'`). A message that named the field but not the
    value would leave a caller with a misspelling to find by hand."""
    with pytest.raises(ValueError, match=r"'Watermark'"):
        _region(one_bit_png, excluded="Watermark")


# -- AC-1: positional construction sites keep working --------------------------------


def test_positional_construction_without_the_field_keeps_working(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-1's last clause, `merged_from`'s rule: the field is LAST and
    defaulted, so MT-007's four-positional and MT-008's five-positional sites
    are both untouched."""
    mask = one_bit_png(320, 240, [(10, 10, 30, 40)])

    four = RawRegion(_CLOSED_TRIANGLE, mask, 0.8, "bubble")
    five = RawRegion(_CLOSED_TRIANGLE, mask, 0.8, "box", (0, 2))

    assert four.excluded is None
    assert (five.merged_from, five.excluded) == ((0, 2), None)


def test_the_field_is_declared_last_after_merged_from(one_bit_png: Callable[..., bytes]) -> None:
    """C-1: "LAST and defaulted". A sixth positional argument is the reason,
    and the dataclass's field order says so directly."""
    mask = one_bit_png(320, 240, [(10, 10, 30, 40)])

    names = [field.name for field in dataclasses.fields(RawRegion)]
    assert names[-2:] == ["merged_from", "excluded"]
    assert RawRegion(_CLOSED_TRIANGLE, mask, 0.8, "bubble", (), "user").excluded == "user"


def test_two_regions_differing_only_in_exclusion_are_not_equal(
    one_bit_png: Callable[..., bytes],
) -> None:
    """Every round-trip assertion in `test_region_store_excluded.py` is an
    equality, so equality has to see this field - a field declared with
    `compare=False` would make every one of them pass with the column dropped."""
    mask = one_bit_png(320, 240, [(10, 10, 30, 40)])

    assert _region(one_bit_png, mask=mask) != _region(one_bit_png, mask=mask, excluded="user")
    assert _region(one_bit_png, mask=mask, excluded="watermark") != _region(
        one_bit_png, mask=mask, excluded="user"
    )


def test_the_region_is_still_frozen_with_the_new_field(one_bit_png: Callable[..., bytes]) -> None:
    """A stage that wants a region excluded calls `set_excluded`; it cannot
    flip the flag on a value it was handed."""
    region = _region(one_bit_png, excluded="watermark")

    with pytest.raises(dataclasses.FrozenInstanceError):
        region.excluded = None  # type: ignore[misc]
