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

## A guard that shells out is asserting on a presentation

When a test captures another process's output and matches on it, it looks like an
assertion about behaviour. It is an assertion about **formatting** — and the tool
is entitled to change that on TTY detection, `CI`, `NO_COLOR`, `FORCE_COLOR`,
locale, terminal width or its own next version.

The case that bit: a guard matched `/Test Files\s+1 passed/`, and with colour on
the escapes land *between* the two words.

```
ESC[2m Test Files ESC[22m ESC[1mESC[32m1 passed ESC[39m

local, piped       : 9 consecutive passes
CI, colour forced  : 2 of 2 required gates failed
```

**This failure is deterministic per environment, and that is worse than a
flake.** A flake you can reproduce by running again. Here, running locally is
not merely weak evidence — it is *structurally incapable* of finding the bug,
because running locally is what holds the variable fixed.

- **Normalise at the single point of capture**, before any assertion sees the
  text. Strip ANSI at minimum; prefer a machine-readable mode — `--json`,
  `--reporter=json` — wherever the tool has one, because that is a surface the
  tool has promised not to reformat.
- **Normalise rather than suppress.** Passing `--colors=off` to the child makes
  the test pass *without ever exercising the coloured path*, leaving the defence
  untested in the one environment that broke it. Suppression hides the variable;
  normalisation handles it and keeps the child running exactly as the real gate
  runs it.
- **Run the suites once with colour forced.** `.github/workflows/gates.yml` does
  this as its own step, and that placement is the point: the project this bit
  already knew the rule — two other guards in the same directory passed
  `--colors=off` for exactly this reason — and the knowledge did not reach the
  third. **A convention that lives only as a habit in two files is not a
  convention.**

Colour is only the instance that bit. Line wrapping at a different terminal
width, locale-dependent number formatting and CRLF all do the same thing.

## When RED breaks the RUNNER, not the tests

The section above is about one file failing to load. This is about the runner
never starting, and the difference is the whole point: not "some tests fail" but
**no test in the repository runs at all**, and `gates.sh` fails outright.

```
Error: Failed to load url .../scripts/vitest/property-seed.global.ts. Does the file exist?
Serialized Error: { code: 'ERR_LOAD_URL' }
```

695 tests dark, on a commit that is a legitimate, rule-following RED.

**It comes from a genuine conflict, not a mistake.** `paths.conf` classifies
`vitest.config.ts` as **test**, deliberately and correctly: it carries the
per-directory coverage thresholds, and freezing it during GREEN is exactly what
stops a threshold being lowered to make a gate pass. But it is also the file that
*wires* anything global — `globalSetup`, `setupFiles`, reporters, projects. So a
story that adds a global test mechanism meets a lock-shaped dilemma with no clean
branch:

| Option | Consequence |
|---|---|
| Wire it in RED, implement in GREEN | the config names modules that do not exist. **The runner cannot start until GREEN lands** |
| Implement it in RED too | GREEN is empty, and the "failing test" was never observed failing against a real absence |
| Wire it in GREEN | impossible — the file is frozen |

**The first is the right answer, and the commit must say so.** Every rule about
RED — watch it fail, fail for the right reason, run the gates before reporting
the story — is written as though the suite still executes. None of them mean
anything when the runner exits before collecting a single file. An agent picking
up that tree cannot otherwise tell a deliberate dark suite from a broken
repository, and will start debugging the wrong thing.

**Verify a dark RED differently, because the usual check cannot be run.**
"Confirm the tests fail for the right reason" is undischargeable when no test
ran. The substitute is narrow and checkable:

- the **only** reason the runner cannot start is the named absence — not a syntax
  error, not a second missing import that arrived with it;
- the failure names **exactly** the modules GREEN is contracted to write, and the
  contract names them too. A dark suite whose error names a module no clause
  mentions is not a planned RED, it is a broken one.

Record both in the handoff, with the error pasted. That is what GREEN has to
clear, and it is the only evidence that the darkness was deliberate.

**Better still, dissolve it.** The reason the config is frozen is its
*thresholds*. Its *wiring* is not a threshold. Keep the thresholds in a small
frozen file the config imports, leave the wiring `config`-classified and writable
in GREEN, and the dilemma stops existing rather than being managed.

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

One codec was mutated three ways. Two mutants dropped a field, and each was
caught **only** by the round-trip property, because no structural test asserted
either field. The third flipped a float writer to big-endian, and six tests
caught it - but only because the container assertions read the bytes through a
reader that imports nothing from the source tree.

That is the general rule, and it is why a round-trip suite is weaker evidence
than it looks: **a codec that is uniformly wrong round-trips through itself
perfectly.** When you choose what observes a mutation, prefer the thing that does
not share the implementation's assumptions. And a missing field and a wrong value
fail differently: a suite that catches an omission can be blind to a corruption.

That is the lesson behind the one extra mutation that `rules.md`,
"Mutation work per story", lets a format or codec story add to its default
"defect put back": make it a wrong **value**, not another missing field. Everything beyond the budget -
earning every assertion that passed on arrival, a full mutation table - is
`/audit-mutations`' work, not the story's.

## When the failing test needs a dependency

A test-only dependency is an ordinary thing for RED to need: `tempfile` for
scratch directories, `pytest-asyncio`, `@testing-library/*`, `testcontainers`, a
snapshot matcher. Every ecosystem declares it in the same manifest as the
production dependencies, which is why `Cargo.toml`, `package.json` and
`pyproject.toml` are a category of their own — `manifest`, writable in RED, while
`config` stays frozen.

**Put it in the dev block and nothing else.** `[dev-dependencies]`,
`devDependencies`, `[dependency-groups]`. `check-boundaries.sh` reads every RED
commit, deletes that block from both sides of the manifest and requires the rest
to be identical, so a production dependency added in RED is refused — and so is
bumping one, because that changes what production code resolves to from the
phase that may not write production code. If the library you need is one
production will also use, that is a GREEN change; say so in the handoff and let
GREEN add it.

**Where there is no dev block, stop and ask.** `go.mod`, `requirements.txt` and
`*.csproj` have no in-file split, so they stay `config` and RED cannot write
them. The sanctioned move is to stop and tell the orchestrator, who changes phase
deliberately and records why in the story. It is a phase round trip and it is
meant to be visible. What you do not do is meet the refusal and reach for a
different tool: a blocked write is information, and an agent that routes around
it has turned the one mechanism this repository relies on into a speed bump.

## A test that writes into the tree and a test that reads it are not independent

Two patterns this skill recommends, put in the same suite, produce a defect
neither has on its own.

**Writing into the tree** is how you test a *rule* rather than today's code. A
guard that greps the current imports passes on a repository where the lint rule
has been deleted; a guard that writes a deliberately offending module, runs the
real linter over it, asserts the rejection and removes it, does not. It is the
negative-control idea applied to tooling, and it is right. The offending file has
to live at the **real** path, too, because lint overrides are path-scoped - a
probe linted from a temp directory is linted under the wrong rules, and then both
the probe and the rule silently stop testing anything while still passing.

**Reading the tree** is how you assert a structural property of all source: walk
the directory, read each file, check the property.

Run both and the second enumerates the first. When the owning worker's delete
lands between another worker's *list* and its *read*, the read dies:

    Error: ENOENT: no such file or directory, open 'src/ui/__import_guard_probe.ts'

Note where the failure surfaced: in a guard that is correct, about a subject that
is correct, naming a file belonging to a different guard testing a different
rule. **Your test runner will not save you** - worker isolation isolates module
state, not the filesystem.

Three things to take from it:

1. **The race is the symptom; the wrong result set is the defect.** Those
   scanners had been returning probe artifacts as source modules for six
   stories - asserting real properties over files written deliberately to
   violate a rule. It never fired only because the rule the probes violated was
   not the rule being asserted. Two guards were one overlap away from a failure
   that would have read as a genuine defect in `src/`.
2. **Ask the harness what a path is; do not answer it yourself.**
   `bash scripts/classify.sh --list source src` gives the same answer the phase
   lock gives, and `paths.conf` classifies a `__probe_*` artifact as `test`. A
   private regex per guard is how four copies in one project drifted apart, two
   of them excluding a file extension the other two did not.
3. **Do not fix it by catching the read error.** Tolerating `ENOENT` treats the
   symptom, hides every future cause, and lets a scanner degrade toward scanning
   nothing while still reporting green - the vacuous pass from three directions
   at once.

The invariant is testable even though the race is not reproducible on demand:
write a probe-named file into a fixture, call the scanner, and assert the probe
is absent **and** a genuine module is still present. Both halves, because an
exclusion that is too broad is the same defect reversed - match `*_probe.*` and a
real `heat_probe.ts` becomes invisible to every guard. Seal it from both
directions: no guard writes an artifact the scanners would not skip, and no
probe-named file sits under `src/` without a guard that owns it.

And if you are harmonising guards that had drifted, prove the cleanup did not
narrow one: run every old variant against the new shared one over the live tree
and compare the file lists. Byte-identical, or you have quietly stopped checking
something.

## The needle is part of the assertion

Rule 1 refuses a test that cannot fail. Read it one level down, at the string:
**a needle that cannot fail is a test that cannot fail**, and this kind does not
announce itself. The assertion has a sharp name, it runs, it passes, and what it
matched is not what it says.

Four cases, one day, two repositories:

| The needle | What also satisfies it |
|---|---|
| absence of `"outside the test-dependency block"` | the same file refused with a *different* message |
| `"bash scripts/check-boundaries.sh origin/"` | the skip note **announcing that resolution failed**, which quotes the unresolved command |
| `"PLAUSIBLE: sed -i option"` | `"IMPLAUSIBLE: sed -i option"` — the string that means the opposite |
| `grep '^ci-local:'` | `ci-local: 15 passed, 0 failed` — that *suite's* line inside the run, not the *script's* verdict |

Three defences, cheapest first:

1. **Anchor it.** `grep -cx`, `^…$`, a full-line compare. A floating substring
   is a claim about containment, and containment is rarely what you mean.
2. **Prefer a needle whose negation is not also a match.** If asserting `X`
   would also pass on `not X`, or on `X failed`, the needle is carrying no
   information. Rewrite it before reaching for a cleverer regex.
3. **Probe it.** Mutate the thing the assertion claims to pin and watch *that
   assertion* go red. Only this catches row three, where anchoring is no help
   and the negation is a longer string containing the needle.

**This does not respect the boundary between the code under test and the
instrument reading it.** Row four was one line of shell in a waiting loop —
no phase, no probe, no reviewer — and its failure mode was to report a run
green. The instrument is the side with no discipline pointed at it, and a
one-line `grep` standing between you and "is it green?" is load-bearing
whether or not it looks it.

## Code no machine you have can execute: grep for the shape

Rule 1 refuses a test that cannot fail. That refusal has a consequence people
reach past: **some code cannot be reached by any test you are able to run**, and
for that code a static check is not a weaker substitute for a test — it is the
only instrument that addresses it at all.

The case that made this concrete. Every suite here opens with

    WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"

and the `||` branch exists for a platform where the first call fails. It had been
written without the `X`s, so on that platform the fallback would have failed too
— a guard that could not rescue the one case it was for. Now ask how to test it.
The branch does not execute on Windows. It does not execute on Linux. A "test"
for it would run the second call directly, which proves the call works and proves
nothing about the branch; or it would assert the branch is reached, which on
every machine either author could touch is an assertion that cannot fail. That is
the thing rule 1 exists to refuse.

So the check is a `grep` over the shipped suites for the broken shape, sitting
beside the ones for bash-3.2 expansions and GNU-only `sed -i`. It pins **the
shape, not the behaviour**, and that is the honest description of what it can do.

Two things follow, and the second is the one worth carrying:

- **A green run on two platforms is compatible with that branch never having run
  on either.** It is, here. The fix was verified by calling the corrected
  expression directly and seeing a real directory come back — by *effect*, not by
  the rule going quiet, because a rule going quiet is also exactly what a wrong
  fix looks like.
- **"We could not test it so we grepped for it" and "a test here would be the
  untestable kind, so a grep is the correct instrument" read identically in a
  diff and mean opposite things.** The first is an excuse for skipping rule 1;
  the second is rule 1 applied. Say which one you mean, in the check, next to it —
  because the next reader sees a grep where they expected a test, and their
  default reading is the first one.

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
