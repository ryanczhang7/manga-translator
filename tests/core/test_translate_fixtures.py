"""The recorded response fixtures are adversarial. Checked, not asserted.

**This file imports nothing from `mangatl`**, deliberately. Every other test in
MT-011 fails at *import* for the whole of RED - `mangatl.translate` does not
exist - and a file that fails to import runs **no assertion in it at all**. The
one claim this story's suite leans hardest on is a property of a *fixture*
rather than of the code under test, so it is isolated here where it can be
watched in RED:

> **Falsifiable success condition 1.** AC-4's fixture has a response key order
> that differs from the region order, so a parser assigning lines by position in
> the response fails it.

A parser that does `dict(zip(region_indices, parsed.values()))` instead of
`{int(k): v for k, v in parsed.items()}` puts the right words on the wrong
bubbles. It is silent, it is plausible, and against a fixture whose keys happen
to arrive in region order the two expressions are **identical**. These tests are
what stop that fixture from drifting into uselessness.

**These tests pass on arrival** (`reference/red-phase.md`, "When a test passes
the moment you write it"). They earn it as a *negative control over the
fixture*: each asserts a count of regions on which the two parsings disagree, so
re-sorting a fixture's keys into region order - the exact edit that would gut
AC-4 - drives that count to zero and turns this file red. The probe is recorded
in MT-011's `## Handoff: RED -> GREEN`; it needs no production code, which is
why it could be run in RED.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

#: `fixtures/translate/`, which `fixtures/translate/README.md` documents.
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "translate"

#: The fixture page's reading indices: four regions, 0..3 (see that README).
_REGION_INDICES: tuple[int, ...] = (0, 1, 2, 3)

#: The proposals, keyed the way a CORRECT parser keys them.
_BY_INDEX: Mapping[int, str] = {
    0: "As if a demon would move at a human's say-so.",
    1: "...I see.",
    2: "Why are you here?",
    3: "Let's go.",
}


def _body(name: str) -> str:
    """One recorded body as text. Never `json.load` - see the folder README."""
    return (_FIXTURES / f"{name}.json").read_text(encoding="utf-8")


def _by_position(body: str, region_indices: Sequence[int]) -> dict[int, str]:
    """The mapping the **position** bug produces: nth key's value to nth region.

    This is the corruption AC-4 exists to catch, written out so the fixtures can
    be measured against it without a `mangatl` import.
    """
    return dict(zip(region_indices, json.loads(body).values(), strict=False))


def _by_index(body: str) -> dict[int, str]:
    """The mapping a correct parser produces (MT-011 C-4)."""
    return {int(key): value for key, value in json.loads(body).items()}


def test_the_well_formed_fixture_names_every_region_with_the_expected_english() -> None:
    """Without this, the disagreement counts below could be met by a fixture
    that is simply wrong rather than one that is deliberately out of order."""
    assert _by_index(_body("well-formed")) == dict(_BY_INDEX)


def test_a_position_based_parser_gets_every_one_of_the_four_regions_wrong() -> None:
    """MT-011 falsifiable success condition 1, as an executable claim.

    Measured 2026-09-18 outside pytest: **4 of 4**. Sorting `well-formed.json`'s
    keys into `0, 1, 2, 3` takes this to 0 and fails here.
    """
    body = _body("well-formed")
    correct = _by_index(body)
    corrupted = _by_position(body, _REGION_INDICES)

    wrong = [index for index in correct if corrupted.get(index) != correct[index]]

    assert list(json.loads(body)) == ["2", "0", "3", "1"], "the key order is the fixture"
    assert len(wrong) == 4, f"only {len(wrong)} of 4 regions distinguish the two parsings"


def test_the_fixture_that_omits_region_three_also_defeats_a_position_based_parser() -> None:
    """AC-5's fixture is out of order too. Measured 2026-09-18: **2 of 3**.

    Fewer than four because the fixture names three regions, and a page with
    three named regions has three chances to disagree. Two is what this key
    order gives; the number is asserted rather than described so that a later
    edit to the fixture has to come back here and change it on purpose.
    """
    body = _body("omits-region-3")
    correct = _by_index(body)
    corrupted = _by_position(body, _REGION_INDICES)

    wrong = [index for index in correct if corrupted.get(index) != correct[index]]

    assert list(json.loads(body)) == ["1", "0", "2"], "the key order is the fixture"
    assert len(wrong) == 2, f"only {len(wrong)} of 3 regions distinguish the two parsings"


def test_region_three_is_the_one_the_omitting_fixture_leaves_out() -> None:
    """AC-5 is "a response that omits region 3", and 3 is not the last region
    of the page - region 3 is `_REGION_INDICES[-1]`, so it IS the last, which is
    the weaker case. Pinned so the fixture cannot quietly start omitting a
    different one and leave AC-5's test name lying."""
    named = set(_by_index(_body("omits-region-3")))

    assert named == {0, 1, 2}
    assert 3 not in named


def test_the_unknown_index_fixture_names_a_region_this_page_does_not_have() -> None:
    """AC-6's fixture. `7` is outside `_REGION_INDICES` and is not a typo for a
    near neighbour, so the index in the raised message is unambiguous."""
    named = set(_by_index(_body("unknown-region-index")))

    assert 7 in named
    assert 7 not in _REGION_INDICES
    assert named - set(_REGION_INDICES) == {7}


def test_the_non_integer_key_fixture_carries_a_key_int_cannot_read() -> None:
    """C-4's case: `int("first")` raises `ValueError`, and C-4 says the parser
    must turn that into `UnknownRegionIndex` rather than letting it escape."""
    keys = list(json.loads(_body("non-integer-key")))

    assert "first" in keys
    with pytest.raises(ValueError, match="first"):
        int("first")


def test_every_fixture_is_a_json_object_of_strings_keyed_by_strings() -> None:
    """JSON object keys are strings - the whole reason C-4 pins the `int()`
    conversion. Asserted over all four fixtures so a future one cannot arrive
    as a list and quietly change what `parse_lines` is being handed."""
    for name in ("well-formed", "omits-region-3", "unknown-region-index", "non-integer-key"):
        parsed = json.loads(_body(name))
        assert isinstance(parsed, dict), f"{name} is not a JSON object"
        assert all(isinstance(key, str) for key in parsed), f"{name} has a non-string key"
        assert all(isinstance(value, str) for value in parsed.values()), f"{name} has a non-string"
