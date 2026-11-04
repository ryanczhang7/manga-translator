"""MT-111 AC-3: `domain.batch.plan_batches`, a volume's pages split into the
inline jobs that fit.

MT-101 D-9: 200 capped pages are ~24 MB of base64 against Gemini's 20 MB inline
limit, so one job cannot hold a volume (PO-1). `plan_batches(sizes, limit)`
takes each page's request size in bytes, in ordinal order, and returns
consecutive inclusive `(first, last)` ranges whose sizes sum to `<= limit`,
**greedily from the first page**: each job takes as many pages as fit before
the next one starts.

**Oracle partition: mechanical.** Every expected output is written out by hand
from the criterion; nothing here is calibrated. `INLINE_REQUEST_LIMIT_BYTES` is
read out of AC-3: 20,000,000, decimal, D-9's smaller reading of "20 MB".

**The sweep is hand-written lists, not a generator.** It checks the invariants
any correct split has (consecutive, covering every page once, each range at or
under the limit, and greedy - no range could have taken the next page) over a
fixed set of lists including the edges: empty, one, sizes of zero, sizes at
exactly the limit. No domain is narrowed, because none is generated.

**Imports of the module under test are inside the tests** (`_plan`), so while
a name is missing each test fails on its own and the file is never dark.

**Timing.** Pure integer arithmetic over lists of at most a dozen sizes; no
budget to size.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import pytest


def _plan(sizes: Sequence[int], limit: int) -> list[tuple[int, int]]:
    from mangatl.domain.batch import plan_batches  # type: ignore[attr-defined]

    ranges: list[tuple[int, int]] = plan_batches(sizes, limit)
    return ranges


def _number(value: int) -> re.Pattern[str]:
    """`value` as a whole number: `1` does not match inside `11` or `10`."""
    return re.compile(rf"(?<!\d){value}(?!\d)")


def test_the_inline_request_limit_is_twenty_million_bytes_decimal() -> None:
    """AC-3: D-9's 20 MB, the smaller (decimal) reading - not 20 MiB."""
    from mangatl.domain import batch

    assert batch.INLINE_REQUEST_LIMIT_BYTES == 20_000_000  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("sizes", "limit", "expected"),
    [
        pytest.param([5, 5, 5], 10, [(0, 1), (2, 2)], id="two-fill-a-job-the-third-starts-one"),
        pytest.param([10], 10, [(0, 0)], id="exactly-at-the-limit-fits"),
        pytest.param([], 10, [], id="no-pages-no-jobs"),
        pytest.param([3, 3, 3, 3], 6, [(0, 1), (2, 3)], id="two-full-jobs"),
        pytest.param([1, 9, 1], 10, [(0, 1), (2, 2)], id="greedy-from-the-first-page"),
        pytest.param([4, 4, 4], 100, [(0, 2)], id="everything-in-one-job"),
        pytest.param([10, 10, 10], 10, [(0, 0), (1, 1), (2, 2)], id="one-page-per-job"),
        pytest.param([0, 0, 0], 10, [(0, 2)], id="zero-sized-pages"),
    ],
)
def test_page_sizes_are_split_into_consecutive_runs_that_fit(
    sizes: list[int], limit: int, expected: list[tuple[int, int]]
) -> None:
    assert _plan(sizes, limit) == expected, (
        f"plan_batches({sizes}, {limit}) should be the greedy split {expected}"
    )


def test_greedy_means_a_job_never_holds_back_a_page_that_would_fit() -> None:
    """`[1, 9, 1], 10`: page 1 fits beside page 0 (1 + 9 = 10), so the first
    job is `(0, 1)` - a planner that balanced the jobs, or started a new job
    one page early, gives `(0, 0), (1, 2)`."""
    assert _plan([1, 9, 1], 10) != [(0, 0), (1, 2)]
    assert _plan([1, 9, 1], 10)[0] == (0, 1)


def test_a_page_too_big_for_any_job_is_refused_naming_its_ordinal_size_and_the_limit() -> None:
    """AC-3: page 1 is 11 bytes against a 10-byte limit. No job can hold it, so
    the plan is refused - before any range is returned, even though page 0
    alone would have fitted - and the message names 1, 11 and 10."""
    with pytest.raises(ValueError) as caught:
        _plan([5, 11, 5], 10)

    message = str(caught.value)
    for what, value in (("ordinal", 1), ("size", 11), ("limit", 10)):
        assert _number(value).search(message), (
            f"the refusal does not name the {what} {value} as a whole number: {message!r}"
        )


@pytest.mark.parametrize(
    ("sizes", "ordinal", "size"),
    [
        pytest.param([11], 0, 11, id="the-only-page"),
        pytest.param([5, 5, 12], 2, 12, id="the-last-page"),
    ],
)
def test_an_oversized_page_anywhere_is_refused_by_ordinal(
    sizes: list[int], ordinal: int, size: int
) -> None:
    with pytest.raises(ValueError) as caught:
        _plan(sizes, 10)

    message = str(caught.value)
    assert _number(ordinal).search(message), f"ordinal {ordinal} not named: {message!r}"
    assert _number(size).search(message), f"size {size} not named: {message!r}"


#: The sweep's corpus: edges first (empty, one page, zeros, exact fits), then
#: assorted shapes. Hand-written; see the module docstring.
_SWEEP: tuple[tuple[tuple[int, ...], int], ...] = (
    ((), 1),
    ((1,), 1),
    ((0,), 0),
    ((7,), 7),
    ((0, 0, 0, 0), 1),
    ((1, 1, 1, 1, 1, 1, 1), 3),
    ((2, 8, 2, 8, 2, 8), 10),
    ((9, 1, 9, 1, 9, 1), 10),
    ((6, 6, 6, 6, 6), 13),
    ((10, 0, 10, 0, 10), 10),
    ((3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5), 15),
    ((5_000_000,) * 9, 20_000_000),
)


def test_every_split_covers_each_page_once_in_order_within_the_limit_and_greedily() -> None:
    """The invariants of AC-3 over every list in `_SWEEP`, violations collected
    and asserted once: the ranges are consecutive and cover `0 .. n-1` exactly
    once, each range's sizes sum to `<= limit`, and each range but the last
    could not have taken the next page (greedy)."""
    violations: list[str] = []
    for sizes, limit in _SWEEP:
        ranges = _plan(sizes, limit)
        covered = [n for first, last in ranges for n in range(first, last + 1)]
        if covered != list(range(len(sizes))):
            violations.append(f"{sizes}, {limit}: {ranges} covers {covered}")
        for first, last in ranges:
            if first > last:
                violations.append(f"{sizes}, {limit}: ({first}, {last}) is not a range")
            if sum(sizes[first : last + 1]) > limit:
                violations.append(f"{sizes}, {limit}: ({first}, {last}) is over the limit")
        for first, last in ranges[:-1]:
            if sum(sizes[first : last + 2]) <= limit:
                violations.append(
                    f"{sizes}, {limit}: ({first}, {last}) could also hold page {last + 1}"
                )
    assert violations == [], "\n".join(violations)
