"""`mangatl.domain.budget`: the projection, the ceiling, and the basis it reports.

`architecture.md` D6 - "budget enforcement is a domain rule, not a warning" -
and the decisive design point from MT-013's `## Context`: **the guard runs
before the call, on a projection, not after it on a total.** A guard that
notices the overrun after paying for it has not guarded anything.

Covers **AC-1** and **AC-2** (the inclusive comparison, one cent either side of
a $2.00 ceiling), **AC-5** (fewer than two priced calls project from the
configured estimate and say so), **AC-6** (five priced calls project from their
mean, and the remainder is that mean times the pages left), **AC-7** (a $0.00
ceiling permits nothing, ever) and **AC-8** (`Budget()` judges against
`DEFAULT_CEILING`).

**Oracle partition: entirely mechanical.** Every number below is *read out of*
MT-013's `## Contract` and `docs/wiki/cost-model.awk`, never re-derived or
calibrated here:

- The comparison is `spent + projection.next_call <= ceiling`, **inclusive**.
- `BOOTSTRAP_PAGE_ESTIMATE` is **$0.06**: design A is $1.14 per 20-page chapter
  (`awk -f docs/wiki/cost-model.awk`, reproduced in RED), and $1.14 / 20 =
  $0.057 rounded **up** to the cent. Up, because an estimate that errs low lets
  a run start that it cannot finish.
- `MIN_SAMPLES_FOR_PROJECTION` is **2**: one page is not a sample, and a single
  wordless page would project the whole chapter at nearly zero and disable the
  guard for every page after it.
- AC-1's spend is **$1.95**, per `## Amendments` A-4. It was $1.90, which made
  AC-1 arithmetically unsatisfiable ($1.90 + $0.06 = $1.96, under the ceiling)
  and Deferred verification 1 vacuous. $1.95 is the unique whole-cent spend at
  which AC-1 refuses, AC-2 permits, and `<=` differs from `<`.
- AC-6's mean rounds **up** to the micro-dollar (`## Contract`, closed by
  RED-A2's note). `_OBSERVED_COSTS` below is chosen so that round-up,
  round-half-up and truncation give **three different answers**, which is what
  makes that a pinned rule rather than a coincidence.

**Money is compared in micro-dollars, not through `str()`.** `Usd.__str__`
renders four decimal places, so `Usd.from_micro(56045)` prints `$0.0560` -
AC-6's mean is *below* the resolution of the product's own rendering. Every
value assertion here is on `.micro()` or on `Usd` equality (exact `Decimal`);
`str()` is used only where a criterion is about what a **message** says, and
there only on amounts that are whole cents and so render losslessly.

**No arithmetic here is a tolerance.** `Usd` wraps an exact `Decimal` and the
ledger deals in whole micro-dollars, so every assertion is `==` on an integer
or on a `Usd`. There is no `pytest.approx` in this file and there must never be.

**What this suite deliberately does not constrain**, so it stays GREEN's choice:

- **The wording of a refusal.** AC-1 asks that a refusal *name* the projection,
  the spend and the ceiling. The test asserts the three amounts appear in the
  message in the product's canonical `Usd` rendering; the sentence around them
  is free.
- **How the mean is computed.** The assertions are on values. `## Contract`
  RED-A1 suggests `functools.reduce(operator.add, ...)`, `.micro()` and integer
  ceiling division `-(-a // b)`, and forbids only one route to the same numbers:
  **`Usd` must not grow a `__truediv__` or a `__mul__`.**
- **`__all__`.** Nothing here pins the module's export list, so a later story
  can extend it without editing a frozen test. What *is* pinned is that the
  names imported below exist with these signatures.
- **Import independence.** That `budget` reaches into neither `store` nor
  `pipeline` is enforced by the `lint` gate's `domain is independent`
  import-linter contract (`pyproject.toml:215`), which is a stronger and more
  general mechanism than a test could be. Not duplicated here.

**Timing.** There is no `pytest-timeout` in this project and no per-test
timeout, so there is no budget in this file to size; if a later story adds one,
every test and every hook in this file needs one. Nothing here touches the
filesystem, sqlite, the network or a model - it is `Decimal` arithmetic over at
most five values.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from mangatl.domain.budget import (
    BOOTSTRAP_PAGE_ESTIMATE,
    DEFAULT_CEILING,
    MIN_SAMPLES_FOR_PROJECTION,
    Budget,
    Decision,
    Projection,
)
from mangatl.domain.money import Usd

# --- the numbers, read out of the story ------------------------------------

#: AC-1 and AC-2's ceiling, stated explicitly rather than taken from
#: `DEFAULT_CEILING`, so that the boundary tests fail if the *comparison* slips
#: and AC-8's test is the only thing that fails if the *default* slips.
_CEILING = Usd(Decimal("2.00"))

#: AC-1 and AC-2's spend (`## Amendments` A-4). $1.95 + $0.06 = $2.01 refuses;
#: $1.95 + $0.05 = $2.00 permits, *exactly* on the ceiling.
_SPENT = Usd(Decimal("1.95"))

#: A chapter is twenty pages, per the brief's "under $2 per ~20-page chapter"
#: and `cost-model.awk`'s denominator.
_CHAPTER_PAGES = 20

#: AC-6's five priced calls, in micro-dollars. Their total is 280,221, so the
#: exact mean is 56,044.2 micro-dollars - deliberately **not** a whole number.
#: Round up gives 56,045; round-half-up gives 56,044; truncation gives 56,044.
#: A fixture whose mean divided evenly would let all three rules pass and would
#: step around the one question `## Contract` left open.
_OBSERVED_COSTS: tuple[Usd, ...] = tuple(
    Usd.from_micro(m) for m in (64875, 57000, 48250, 71100, 38996)
)

#: The mean of `_OBSERVED_COSTS`, rounded **up** to the micro-dollar.
_OBSERVED_MEAN_MICRO = 56045

#: The answer both *rejected* rounding rules give, asserted against explicitly
#: so that a `ROUND_HALF_UP` or a truncating implementation cannot pass by
#: landing one micro-dollar low.
_MEAN_ROUNDED_DOWN_MICRO = 56044


def _projection(next_call: Usd) -> Projection:
    """A `Projection` built by hand, to test `check` in isolation from `project`.

    AC-1 and AC-2 are about the **comparison**, and a bug in the extrapolation
    should not be able to turn the boundary test red for the wrong reason. The
    fields `check` does not read are filled with the values `project` would
    produce for a one-page remainder.
    """
    return Projection(
        next_call=next_call,
        remaining_chapter=next_call,
        basis="estimate",
        sample_count=0,
    )


# --- the constants, and where they come from -------------------------------


def test_the_default_ceiling_is_two_dollars() -> None:
    """AC-8. The brief's hard budget: under $2 per ~20-page chapter.

    Compared through `.amount` rather than against a `Usd(Decimal("2.00"))` on
    the right: ruff's `SIM300` reads an ALL_CAPS name on the left of an `==` as
    a literal and reports a Yoda condition, so `CONST == Usd(...)` fails the
    `lint` gate. `.amount` keeps the natural reading order, and since `amount`
    is `Usd`'s only field the assertion is exactly as strong. Do not "fix" this
    back - the `lint` gate is required.
    """
    assert DEFAULT_CEILING.amount == Decimal("2.00")
    assert DEFAULT_CEILING.micro() == 2_000_000


def test_the_bootstrap_estimate_is_six_cents_rounded_up_from_the_cost_model() -> None:
    """AC-5's "configured per-page estimate", and where the number comes from.

    `docs/wiki/cost-model.awk` puts design A at $1.14 for a 20-page chapter, so
    the per-page figure is $1.14 / 20 = $0.057. It is rounded **up** to $0.06
    and not down to $0.05, because an estimate that errs low is an estimate that
    lets a run start which it cannot finish - the same direction of caution as
    the inclusive comparison, and the opposite of a tuning parameter.

    The second assertion is the one that makes the direction observable: the
    estimate must be at least the exact per-page cost, which $0.05 is not.
    """
    exact_per_page = Decimal("1.14") / _CHAPTER_PAGES
    assert exact_per_page == Decimal("0.057")

    # `.amount` rather than `== Usd(...)`, for the `SIM300` reason recorded on
    # `test_the_default_ceiling_is_two_dollars`.
    assert BOOTSTRAP_PAGE_ESTIMATE.amount == Decimal("0.06")
    assert BOOTSTRAP_PAGE_ESTIMATE.micro() == 60_000
    assert BOOTSTRAP_PAGE_ESTIMATE.amount >= exact_per_page


def test_one_priced_call_is_not_enough_to_project_from() -> None:
    """AC-5's "fewer than two", as a constant.

    Two, because a single wordless page - which `translate/client.py` says is a
    real and common outcome - would project the rest of the chapter at nearly
    zero and switch the guard off for every page after it.
    """
    assert MIN_SAMPLES_FOR_PROJECTION == 2


# --- AC-1 and AC-2: the ceiling comparison, one cent either side -----------


def test_a_projection_that_would_cross_the_ceiling_is_refused() -> None:
    """AC-1. $1.95 spent plus a projected $0.06 is $2.01, over a $2.00 ceiling."""
    decision = Budget(ceiling=_CEILING).check(_SPENT, _projection(Usd(Decimal("0.06"))))

    assert decision.permitted is False


def test_a_refusal_names_the_projection_the_spend_and_the_ceiling() -> None:
    """AC-1's second half: a refusal that does not say why is not actionable.

    The three amounts are asserted in `Usd`'s own rendering, which is what the
    user sees elsewhere in the product. The sentence they sit in is GREEN's
    choice; that all three are *present* is not. All three are whole cents, so
    the four-place rendering is lossless here.
    """
    decision = Budget(ceiling=_CEILING).check(_SPENT, _projection(Usd(Decimal("0.06"))))

    assert decision.reason is not None
    assert "$0.0600" in decision.reason, "the refusal must name the projection"
    assert "$1.9500" in decision.reason, "the refusal must name the spend"
    assert "$2.0000" in decision.reason, "the refusal must name the ceiling"


def test_a_projection_that_lands_exactly_on_the_ceiling_is_permitted() -> None:
    """AC-2, and the whole point of the boundary: the comparison is **inclusive**.

    $1.95 + $0.05 = $2.00, which *is* the ceiling. This is the single input on
    which `spent + next_call <= ceiling` and `spent + next_call < ceiling`
    disagree, and it is `## Deferred verifications` condition 1's target: with
    the comparison tightened to `<`, this test must fail and the AC-1 tests
    above must still pass.
    """
    decision = Budget(ceiling=_CEILING).check(_SPENT, _projection(Usd(Decimal("0.05"))))

    assert decision.permitted is True


def test_a_permitted_decision_carries_no_reason() -> None:
    """AC-2. `reason` is the refusal's explanation, so a permit has none."""
    decision = Budget(ceiling=_CEILING).check(_SPENT, _projection(Usd(Decimal("0.05"))))

    assert decision.reason is None


def test_a_decision_reports_the_spend_the_ceiling_and_the_projection_it_judged() -> None:
    """AC-1 and AC-2. MT-018 renders the decision, so it has to be self-contained.

    A `Decision` that carried only a boolean would force every caller to keep
    the three inputs alive to explain it, and `architecture.md` D6 makes this a
    domain rule rather than a warning the UI reconstructs.
    """
    projection = _projection(Usd(Decimal("0.05")))
    decision = Budget(ceiling=_CEILING).check(_SPENT, projection)

    assert isinstance(decision, Decision), "`check` returns the exported `Decision`"
    assert decision.spent == _SPENT
    assert decision.ceiling == _CEILING
    assert decision.projection == projection


# --- AC-5: fewer than two priced calls use the configured estimate ---------


def test_a_chapter_with_no_priced_calls_projects_from_the_configured_estimate() -> None:
    """AC-5 at zero - the first consultation of a run, before anything is priced.

    Twenty pages at $0.06 is $1.20, which is above `cost-model.awk`'s $1.14 for
    the same chapter. That gap is the round-up doing its job and is not a defect.
    """
    projection = Budget().project(priced_calls=(), pages_remaining=_CHAPTER_PAGES)

    assert projection.next_call == BOOTSTRAP_PAGE_ESTIMATE
    assert projection.basis == "estimate"
    assert projection.sample_count == 0
    assert projection.remaining_chapter.micro() == 1_200_000


def test_a_chapter_with_one_priced_call_projects_from_the_estimate_not_from_that_call() -> None:
    """AC-5 at one, which is the criterion's actual claim: one sample is not data.

    The single call here costs $0.0009 - a near-wordless splash page, exactly
    the case `## Contract` warns about. Extrapolating from it would project the
    remaining nineteen pages at about $0.017 and leave the guard unable to fire
    for the rest of the chapter. The projection must stay at the $0.06 estimate
    and must still *say* it is an estimate.

    This is `## Deferred verifications` condition 3's target: with
    `MIN_SAMPLES_FOR_PROJECTION` changed from 2 to 1, `next_call` becomes
    $0.0009 and `basis` becomes "observed", so this test fails twice over.
    """
    wordless_page = Usd.from_micro(900)
    assert wordless_page != BOOTSTRAP_PAGE_ESTIMATE, "negative control: the two must differ"

    projection = Budget().project(priced_calls=[wordless_page], pages_remaining=19)

    assert projection.next_call == BOOTSTRAP_PAGE_ESTIMATE
    assert projection.basis == "estimate"
    assert projection.sample_count == 1
    assert projection.remaining_chapter.micro() == 1_140_000


def test_the_second_priced_call_is_what_switches_the_projection_to_observed() -> None:
    """AC-5 and AC-6 meeting at the threshold: one is an estimate, two are observed.

    Two calls of $0.04 and $0.06 mean exactly $0.05, so nothing here depends on
    the rounding rule - this test is about *which side of the threshold* two
    samples fall on, and pins that `MIN_SAMPLES_FOR_PROJECTION` is a floor that
    two meets rather than a count two must exceed.
    """
    calls = (Usd.from_micro(40_000), Usd.from_micro(60_000))
    projection = Budget().project(priced_calls=calls, pages_remaining=18)

    assert projection.basis == "observed"
    assert projection.sample_count == 2
    assert projection.next_call.micro() == 50_000


# --- AC-6: five priced calls project from their mean -----------------------


def test_five_priced_calls_project_the_next_call_at_their_observed_mean() -> None:
    """AC-6. The mean of the five costs, reported as observed rather than estimated.

    `basis` is reported and not inferred (`## Contract`): MT-018 shows the user
    "projected $1.30 (estimated)" against "(from 5 pages)", and those are
    different claims about the same number.
    """
    projection = Budget().project(priced_calls=_OBSERVED_COSTS, pages_remaining=15)

    assert projection.next_call.micro() == _OBSERVED_MEAN_MICRO
    assert projection.next_call == Usd.from_micro(_OBSERVED_MEAN_MICRO)
    assert projection.basis == "observed"
    assert projection.sample_count == 5


def test_a_mean_that_does_not_divide_evenly_is_rounded_up_to_the_micro_dollar() -> None:
    """AC-6's open question, closed: **up**, and never half-up or truncated.

    This is the first division this product performs on money. The five costs
    total 280,221 micro-dollars, so the exact mean is 56,044.2 - and the three
    candidate rules disagree:

        round up    -> 56,045    <- the rule
        round half  -> 56,044
        truncate    -> 56,044

    Up, for the same reason `BOOTSTRAP_PAGE_ESTIMATE` rounds up: under-projecting
    is the failure that costs money, and it costs it silently. The second
    assertion is the negative control - without it, a `ROUND_HALF_UP`
    implementation would differ from the rule by one micro-dollar per page and
    nothing would say so.
    """
    total_micro = sum(cost.micro() for cost in _OBSERVED_COSTS)
    assert total_micro == 280_221, "the fixture's mean must not be a whole micro-dollar"
    assert total_micro % len(_OBSERVED_COSTS) != 0

    projection = Budget().project(priced_calls=_OBSERVED_COSTS, pages_remaining=15)

    assert projection.next_call.micro() == _OBSERVED_MEAN_MICRO
    assert projection.next_call.micro() != _MEAN_ROUNDED_DOWN_MICRO


def test_the_remaining_chapter_is_the_projected_mean_times_the_pages_left() -> None:
    """AC-6's second half, stated as the invariant it is.

    Asserted twice on purpose: once against the arithmetic written out in full
    (56,045 x 15 = 840,675), and once as the relation between the two fields, so
    that an implementation which computed the remainder from the *unrounded*
    mean - 56,044.2 x 15 = 840,663 - fails on both.
    """
    pages_remaining = 15
    projection = Budget().project(priced_calls=_OBSERVED_COSTS, pages_remaining=pages_remaining)

    assert projection.remaining_chapter.micro() == 840_675
    assert projection.remaining_chapter.micro() == projection.next_call.micro() * pages_remaining


def test_a_chapter_with_no_pages_left_projects_nothing_for_the_remainder() -> None:
    """AC-6 at the empty end of zero-one-many: the last page has been done.

    `next_call` is still a real figure - the guard may be consulted once more by
    a caller that has not yet noticed it is finished - but there is no remainder
    to project, so it is $0.00 rather than one more page's worth.
    """
    projection = Budget().project(priced_calls=_OBSERVED_COSTS, pages_remaining=0)

    assert projection.remaining_chapter == Usd(Decimal(0))
    assert projection.remaining_chapter.micro() == 0
    assert projection.next_call.micro() == _OBSERVED_MEAN_MICRO


# --- AC-7: a zero ceiling permits nothing ----------------------------------


def test_a_zero_ceiling_refuses_the_very_first_consultation() -> None:
    """AC-7 (as reworded by `## Amendments` A-2). No call is ever permitted.

    This sits on the boundary rather than beside it: `BOOTSTRAP_PAGE_ESTIMATE`
    is strictly positive, so $0.00 + $0.06 <= $0.00 is false and the refusal
    follows from the estimate being real rather than from a special case for
    zero. It is `## Deferred verifications` condition 2's second target - with
    the estimate set to $0.00 the sum becomes $0.00 <= $0.00, which **permits**,
    and this test fails.

    GREEN must not add a branch for a zero ceiling. The comparison already
    handles it, and `domain` lives under a 100% branch-coverage bar where an
    unreachable arm is a gate failure.
    """
    budget = Budget(ceiling=Usd(Decimal("0.00")))
    projection = budget.project(priced_calls=(), pages_remaining=_CHAPTER_PAGES)

    assert projection.next_call == BOOTSTRAP_PAGE_ESTIMATE

    decision = budget.check(Usd(Decimal("0.00")), projection)

    assert decision.permitted is False
    assert decision.reason is not None
    assert "$0.0600" in decision.reason
    assert "$0.0000" in decision.reason


# --- AC-8: the default ceiling is the one that judges ----------------------


def test_a_budget_constructed_with_no_ceiling_judges_against_two_dollars() -> None:
    """AC-8 (as reworded by `## Amendments` A-3).

    Not merely that `DEFAULT_CEILING` is $2.00 - the constants test above says
    that - but that a `Budget()` built without one actually *compares against*
    it. The inputs are AC-1's, so a default wired to anything other than $2.00
    either permits $2.01 or reports the wrong ceiling in the refusal.

    The default is a default **argument**, not a lookup. Where a real ceiling
    comes from is MT-044's question; this module imports nothing from `store`.
    """
    decision = Budget().check(_SPENT, _projection(Usd(Decimal("0.06"))))

    assert decision.ceiling == DEFAULT_CEILING
    assert decision.ceiling == Usd(Decimal("2.00"))
    assert decision.permitted is False


# --- the shape of what crosses the layer boundary --------------------------


def test_a_projection_cannot_be_rewritten_after_it_is_made() -> None:
    """`## Contract`: `Projection` is `frozen=True`, for `events.py`'s reason.

    MT-015 hands the run's stream to a UI thread, and MT-018 renders this
    number. A consumer that can rewrite a projection is a consumer that can
    rewrite the evidence a refusal was based on.
    """
    projection = Budget().project(priced_calls=(), pages_remaining=_CHAPTER_PAGES)

    with pytest.raises(dataclasses.FrozenInstanceError):
        projection.next_call = Usd(Decimal("0.01"))  # type: ignore[misc]


def test_a_decision_cannot_be_rewritten_after_it_is_made() -> None:
    """`## Contract`: `Decision` is `frozen=True`. A refusal is not negotiable.

    `architecture.md` D6 makes budget enforcement a domain rule rather than a
    warning; a caller that can flip `permitted` from False to True has turned it
    back into one.
    """
    decision = Budget(ceiling=_CEILING).check(_SPENT, _projection(Usd(Decimal("0.06"))))

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.permitted = True  # type: ignore[misc]
