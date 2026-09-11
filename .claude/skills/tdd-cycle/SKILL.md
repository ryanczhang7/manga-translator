---
name: tdd-cycle
description: The RED to GREEN discipline this repository enforces - how to write a test that fails for the right reason, how to make it pass without weakening it, and what must be handed between the two phases. Use when writing tests for a story, implementing a story, or deciding whether a story is genuinely done.
---

# The RED to GREEN cycle

One story is one cycle. The cycle is not a ritual; each step exists to catch a
specific way software goes wrong.

| Phase | Question it answers | Failure it prevents |
|---|---|---|
| RED | Does a test exist that fails when this behaviour is absent? | Code with no verification |
| GREEN | Does the simplest implementation satisfy it? | Speculative generality |
| GATES | Does it hold up under lint, types, build and coverage? | "Works on my machine" |

## Non-negotiables

1. The test is written first and is **observed failing**. Paste the failure.
   Where it cannot be - a regression guard for an invariant an earlier story
   established, an assertion corrected while the implementation exists - the
   observation is replaced, never waived: a deliberate, reverted mutation of
   what the test pins, with the red pasted. See "Red is a property of an
   assertion" below and `reference/red-phase.md`.
2. The failure must be the *right* failure - your assertion, not an unrelated
   error that happens to be red.
3. During GREEN the tests are frozen. A test that is wrong sends the story back
   to RED; it is never edited into passing.
4. Never reach green by weakening: no relaxed tolerance, no skipped case, no
   deleted case, no assertion narrowed to what the code already does.
5. Done means `bash scripts/gates.sh` was run and passed. It writes its own
   summary into the story, stamped with the code it ran against; do not paste
   one, and do not edit what it wrote.
6. The same discipline applies to the gates themselves: a gate that has never
   been observed to fail is not a gate. When a story adds or changes one, break
   what it guards, watch it fail, record it in `## Gate probes`, and revert.
   See the `quality-gates` skill.
7. RED and GREEN each end with `bash scripts/gates.sh --fast`. Not for a pass -
   in RED the test gates are supposed to be red - but because the gates judge
   your tests with a *different and slower command* than the one you have been
   running. See "The gates run your tests differently" below.
8. A test that is wrong sends the story back to RED, and RED on a return is
   narrower: fix the defective test, touch nothing else, and earn the correction
   with a probe or a measurement. See `reference/red-phase.md`. The general
   trigger is wider than a wrong test - it is **any** gate failure whose only
   legal fix is a write the current phase forbids, and a `format` gate WARNing on
   a test file the story just added is the everyday instance.
9. Rule 1 is about an **assertion**, not about a run. See below - it is the one
   place the cycle can look completely correct and prove nothing.
10. A property test's **generator** is part of the specification, not part of the
    test strategy. Narrowing its domain is a change to what the criterion claims,
    and needs its own justification. See "A generator is part of the
    specification" below - it is the fifth way to reach green, and rule 4 does
    not cover it.

## Red is a property of an assertion, not of a run

A suite that goes red tells you *some* assertion in it failed. The law needs
more than that: **this** assertion, the one that pins **this** behaviour, has
been seen to fail. In an ordinary RED the two coincide, because nothing is
implemented and everything is red. Two situations, both routine, pull them
apart - and in both the story passes every written rule while shipping a test
that proves nothing.

**A test written or corrected while the implementation exists.** The clearest
case is a return to RED. A test asserted the wrong thing, GREEN caught it, the
Test Developer corrects the assertion - and the corrected assertion runs for the
first time against code that already satisfies it. It goes green on its first
execution and every execution after. Nothing distinguishes it from an assertion
that checks nothing at all. The same holds outside a return: a story adding
tests to a module an earlier story built starts from a working implementation.

Real example. A test demanded a validation error for an input the rule
actually permits - a lower bound compared against the document's own reference
value, where the test had assumed the reference was zero. Corrected to an input
the rule rejects, it passed instantly against untouched code. Mutating the
guard to the exact bug the test names - comparing against the constant zero
instead of the document's value - produced one failure, the right one:

    FAIL  compares the bound against the document's own reference, not zero
    1 failed, 27 passed

That is what earns it: one mutation of the specific production behaviour the
test claims to pin, one run, one revert, output pasted into `## Regressions`.
`check-boundaries.sh` refuses a PR whose `## Regressions` describes a failure
without showing one. Nothing in the harness asked for that mutation before this
rule existed, and a less suspicious orchestrator would have shipped the
unobserved assertion in full compliance with every other rule.

### Make the mutation with `scripts/mutate.sh`, and with nothing else

    bash scripts/mutate.sh src/camera.ts 's/Math.min(90/Math.min(900/' \
      -- pnpm exec vitest run tests/camera.test.ts

This is the only sanctioned way to mutate production source, and it is allowed in
every phase - including RED, where the file is otherwise frozen. It backs the
file up to an explicit path under `.claude/state/mutations/`, applies the
expression, runs the command, restores the file, **verifies the restore with
`cmp`**, prints the line it put back, and logs what happened for the story to
quote. It refuses an expression that changes nothing, because a probe that alters
no behaviour hands you a green run and a test you wrongly believe you have
earned. Its exit status is the command's, since a non-zero exit is the evidence
you came for.

Reach for `sed -i` here and you are routing around the phase lock. That is not a
hypothetical: the two rules above ("mutate the frozen file", "never work around
the lock") contradicted each other for several stories, and every agent resolved
it privately with `sed -i` on a path held in a variable - which the lock let
through only because it discarded any target containing a `$`. It no longer does.
And the one mutation made where source *was* writable lost its backup, because
that shell had no `$TMPDIR`; the restore came down to the substitution happening
to be an exact inverse of a single-occurrence match. It was. That is the coin
flip this script exists to remove.

The same script is what the orchestrator uses to check a handoff's claim that the
suite discriminates (`/advance-story`, "when the claim is *this suite
discriminates*"), for the same reason: the restore has to be a fact.

**A suite that fails at import.** In RED the module under test does not exist,
so the file does not load and **not one assertion in it has executed** -
including assertions that never touch the missing module. Negative controls are
the casualty: the white-noise field that must score near zero, the archipelago
that must not read as continents, the deliberately broken input a threshold has
to reject. They are what make every number in the suite mean something, and they
are unverified for the whole of RED.

Bridge it in two steps, both cheap:

- **RED records the expected value of every negative control** in the handoff -
  threshold, candidate range, and the value the control actually measured when
  driven outside the test framework (a plain interpreter, a script, whatever
  runs without the missing import). Not "controls exist": the numbers.
- **GREEN confirms each recorded value**, not merely that the control test
  passes. It costs one comparison and it works: a story recorded
  `0.54 -> 0.30 -> 0.18 -> 0.10` in RED and measured `0.50 -> 0.30 -> 0.20 ->
  0.12` in GREEN, because RED had measured a candidate pipeline and GREEN
  measured the shipped module. Benign, explained in the story, and exactly the
  kind of divergence that is cheap now and expensive later.

## A generator is part of the specification

Everything above is about assertions. A property test has a second half - the
generator - and it is not test strategy, it is the **input domain the criterion
claims to hold over**. That makes a fifth way to reach green, and the law's four
prohibitions do not cover it: shrink what is generated. No skip, no widened
tolerance, no deleted case, no weakened assertion, and a diff of one line in a
helper.

Sometimes that is exactly right. A round-trip property over generated documents
failed on roughly two runs in three, and both counterexamples shrank to the same
minimal shape: a **negative zero** in a coordinate. Neither the test nor the
implementation was wrong. The *criterion* admitted an input the format cannot
represent - the design stores those objects as JSON, `JSON.stringify(-0)` is
`"0"`, and the comparison distinguishes `-0` from `0`. Two one-line fixes were
available:

| Move | Effect |
|---|---|
| Keep `-0` out of the two coordinate generators | Removes an input the format's design excludes. **Legitimate.** |
| Compare `-0` and `0` as equal in the round-trip helper | Stops the comparison distinguishing values for **every number in the document**. **A weakening, and invisible.** |

The second is *easier*, because it is an edit in the file where the failure is
reported. Narrowing the domain and loosening the comparison look identical in
review, so a narrowing has to arrive with three things:

1. **The design clause that excludes the value**, named. "The format cannot carry
   this" is a reason; "the property was failing" is not. If no document says so,
   you have found an undocumented limit, not a test bug.
2. **The limit written into the architecture document**, not only into a comment
   beside the generator. It is a property of the format that every later story
   inherits - a migration or a golden fixture will meet it again.
3. **A mutation showing the property still fails on a lossy implementation.**
   This is the part with teeth, and it is the same mechanism as above: after the
   narrowing, break the thing the property is about and watch it go red. A
   narrowing that gutted the property cannot survive it.

And note the third branch this opens. "Test wrong → RED, code wrong → GREEN" has
no slot for *the criterion's domain is wider than the design's representable
domain*, which is the common case the moment a story has both a property test and
a serialisation format. It is an `## Amendments` conversation, and a
feature-developer that stops and says so rather than making the property pass has
done the right thing.

### A mutation is only as informative as the independence of what observes it

Three mutations of one codec: two dropped a field, and each was caught **only**
by the round-trip property, because no structural test asserted either field. The
third flipped a float writer to big-endian, and six tests caught it - but only
because the container assertions read the bytes through a reader that imports
nothing from the source tree.

That is the general rule, and it is why a round-trip suite is weaker evidence
than it looks: **a codec that is uniformly wrong round-trips through itself
perfectly.** When you choose what observes a mutation, prefer the thing that does
not share the implementation's assumptions. And mutate in two directions - a
missing field and a wrong value fail differently, and a suite that catches an
omission can be blind to a corruption.

## The gates run your tests differently

RED and GREEN validate with the test command. At least one required gate does
not: the coverage gate runs the same suite under instrumentation, which is
strictly slower, and CI hardware is slower again. Nothing about a green test
command tells you the tests are *admissible* to the gate that will judge them.

This is not hypothetical. A suite passed RED, passed GREEN, passed every local
gate and reached REVIEW - then failed a required gate in CI, because one
property test took 1,835 ms plain and 2,644 ms instrumented against a 5,000 ms
default timeout. Comfortable on a desktop, over the line on a runner. The cost
was a full RED -> GREEN -> GATES -> REVIEW round trip.

So:

- End RED and GREEN with `bash scripts/gates.sh --fast`. In RED read it for the
  *shape* of the failure: lint and typecheck should pass, and the test gates
  should fail with your assertion. A test gate failing on a timeout, a config
  error or a lint rule means the tests are not admissible and RED is not done.
- Set an explicit, generous timeout on property tests and anything that loops
  over a generated collection. The framework default is measured against the
  plain run, which is the fast one.
- **Budget every single test at under a quarter of the framework's timeout,
  measured under local instrumentation.** 4,275 ms against a 5,000 ms default
  is not a pass, it is a pending failure on hardware you do not control. When a
  test is over budget the first question is *is the cost in the helper?* - that
  is the one place it can be removed for free, without touching a threshold, a
  seed list or `numRuns`. Do not extrapolate to CI from the gate's whole wall
  time; see `quality-gates`, "How much slower is CI, actually".
- In a property test or a whole-collection loop, do not call the assertion once
  per item. Accumulate the violations and assert once at the end. On identical
  work this is routinely an order of magnitude cheaper - in the case above, 260
  ms against 2,644 ms for the sibling test in the same block.

## Details

- `reference/red-phase.md` - choosing the test level, naming, what to cover
- `reference/green-phase.md` - implementing without over-building, refactoring
- `reference/handoff.md` - what crosses the context boundary, and the template

## Why the lock exists

Both classic failure modes are invisible from inside the conversation that
commits them: writing the implementation while "writing the test", and softening
the test to reach green. `.claude/hooks/phase-guard.sh` makes both impossible
rather than merely discouraged. Being blocked by it is information: either you
are in the wrong phase, or you were about to do the wrong thing.
