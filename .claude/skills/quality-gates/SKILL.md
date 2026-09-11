---
name: quality-gates
description: What each quality gate means in this harness, how to run them, and how to triage a failure without weakening the tests. Use when a story reaches the GATES phase, when a gate fails, or when configuring gates for a new stack.
---

# Quality gates

The gate names are stable across every project; the commands behind them are
per-stack and live in `.claude/harness/project.conf`. Agents talk about "the
coverage gate"; the manifest knows whether that means `pytest --cov`,
`vitest --coverage` or `cargo llvm-cov`.

    bash scripts/gates.sh              # everything
    bash scripts/gates.sh --fast       # everything not marked `slow`
    bash scripts/gates.sh --list       # what is configured
    bash scripts/gates.sh --gate unit  # one gate
    bash scripts/gates.sh --required   # required only
    bash scripts/gates.sh --audit      # check the manifest itself, run nothing

Failures write their output to `.claude/state/gate-logs/<gate>.log`.

`gates.sh` is not all of CI. The other half is `bash scripts/check-boundaries.sh`,
and it is not a gate because it judges a different thing: the **commit** rather
than the code - the phase in the committed story frontmatter, the acceptance
criteria against the base branch, whether the gate record still matches the tree
being merged. Folding it into `gates.sh` would be circular, since one of the
things it checks is the record `gates.sh` has not written yet. Run it after
committing and before opening the PR. "All gates pass" is not "CI will pass".

## --fast, and why RED runs the gates at all

RED and GREEN validate with the test command. The gates do not: the coverage
gate runs the same suite under instrumentation, which is strictly slower, and CI
hardware is slower again. So a suite can pass RED, pass GREEN, pass every gate
on a developer machine, and fail a required gate in CI - which has happened, on
a property test at 2,644 ms instrumented against a 5,000 ms default timeout.

`--fast` is the primitive that lets RED and GREEN ask the gates whether the
tests are even admissible, without paying for a release bundle on every loop. In
RED it is read for the shape of the failure, not for a pass: lint and typecheck
green, test gates red with the story's assertion. Anything else - a timeout, a
config error, a lint rule the test file trips - means the tests are not
admissible and RED is not finished.

A gate is in `--fast` unless a `slow` line in `project.conf` excludes it:

    slow | build | a release bundle, which RED and GREEN have no use for

The reason is required, and `--audit` refuses a `slow` line without one or one
naming a gate that does not exist. Fast-by-default is deliberate: the subset is
then correct in a new project, and wrong only where someone said so out loud.
Never mark a gate slow to stop it failing - that is what a waiver is for, and
waivers are refused on required gates for the same reason.

A `--fast` run is never recorded in a story. It is not a full run, and only a
full run is evidence.

### How much slower is CI, actually

"Slower on CI" is only useful as a number, and the obvious number is wrong.

Do **not** extrapolate from the gate's own wall time. A coverage gate at 3 s
locally and 41 s in CI looks like 14x, and on that basis a 367 ms test looks
like it will take 5,000 ms there and blow the framework's default timeout. It
does not: most of a coverage gate's wall time is fixed overhead - process start,
transform, instrumentation setup, report generation - and none of it scales with
test compute. Measured **per test** from the CI log, the same gate was 3.4x.
Acting on the 14x means optimising a test that was already fine.

So measure the per-test factor once, from a real CI log - one test's duration
there over the same test's duration locally, both under the same gate - and
record it in `project.conf` next to the gate, where the next agent will find it:

    ci-factor | coverage | 3.4 | actions run 412, "AC-4/AC-5 file 1,262 ms"

`--audit` refuses a factor that is not a number, one with no source, and one
naming a gate that does not exist. Re-measure it when the runner image or the
test command changes.

**Budget, not limit: keep any single test under a quarter of the framework's
timeout** under local instrumentation. 4,275 ms against a 5,000 ms default is
not a pass; it is a pending failure on hardware you do not control.

### Hooks have their own timeout, and a GPU hides the cost in teardown

Everything above is about `it` blocks and about CPU. Both gaps have now cost a
story its REVIEW.

A story reached REVIEW with a green CI run. The next CI run, on a **docs-only
commit with identical code**, failed a required gate; so did the one after:
`Hook timed out in 30000ms`. The test that panned and zoomed a 100,000-cell
world carried its own 60 s budget, and so did the `beforeAll` and `beforeEach`
that built and mounted it - RED had sized all three from measurement. The
`afterEach` that destroyed the map carried none, so it had the framework's
30 s default, and it took just over that.

- **Every hook in a file that owns a test timeout gets a budget too**, sized
  from the same measurement. A file with a 60 s test and a default-timeout
  `afterEach` has a 30 s hole in it, and the hole is invisible until the day it
  is not.
- **For a test that drives a GPU, the cost is in teardown, not in your step
  timer.** That run reported a step mean of 0.27 ms; the 90 frames it queued
  were rasterised by the runner's software GL when the context was torn down, at
  roughly 300 ms a frame. Locally, on a real GPU, the whole file ran in five
  seconds and there was nothing to see - so the per-test CI factor above does
  not transfer, because the deferred cost is *zero* on the machine you measure
  it on. Either end the measured sequence with `gl.finish()` so the number means
  what it says, or budget the teardown from a CI log rather than a local one.
- **A CI pass within 10 % of a limit is a pending failure.** The green run
  cleared the 30 s default by three seconds, and that margin was the whole
  story. Read the hook and test timings out of the *first* CI log before calling
  the PR green.
- **A budget is a function of the workload, not a constant.** Those three numbers
  were sized against 100,000 cells. The next story was a performance audit of
  that very default - and had it raised the cell count, all three budgets would
  have been sized for a world that no longer existed, silently, with no gate able
  to notice. Worse, the story could not have fixed them in GREEN, because they
  live in a test file. Write the budget as an expression over the thing that
  drives the cost:

      const budgetMs = (base) => base * Math.max(1, siteCount / 100_000)

  Each measured base is preserved, the scaling is explicit, and at the default it
  was measured against the value is **numerically identical** - which is what
  makes the change safe to take before any new measurement exists. The
  `Math.max(1, …)` floor is not decoration: a *lower* default must not shrink a
  budget that came from observed CI behaviour rather than from theory.

**And the first question about a slow test is "is the cost in the helper?"** -
because "make the test faster" must never become "weaken the test". In the case
above the cost was entirely in a test helper doing a brute-force nearest-site
scan, 4,000 sites against ~8,600 queries per seed; replacing it with a greedy
walk over the mesh's existing adjacency took the test from 4,275 ms to 367 ms
with `numRuns`, the thresholds, the seed lists and the timeouts all untouched
and the measured statistics bit-identical. That is the one place cost can be
removed for free. Verify the replacement against the thing it replaced - that
one was checked on 80,000 random query/start pairs against the brute-force
oracle, 0 mismatches - because a subtly wrong helper moves calibrated
thresholds while every test stays green. Lowering `numRuns`, widening a
tolerance or raising a timeout to fit the budget is weakening the test, and
sends the story back to RED instead.

## The gates

| Gate | Required | Answers |
|---|---|---|
| `format` | optional | Is the code formatted to the project standard? |
| `lint` | required | Does it violate the project rules? |
| `typecheck` | required | Do the types hold? |
| `unit` | required | Does the behaviour hold in isolation? |
| `coverage` | required | Is anything shipped unexercised? |
| `integration` | optional | Do the seams hold against real dependencies? |
| `build` | required | Does a production artefact come out? |
| `mutation` | optional | Would the tests notice if the code were wrong? |

A gate marked required with no command configured is a warning before the
bootstrap story lands (`BOOTSTRAPPED=no`) and a hard failure after it. That is
deliberate: an unconfigured gate must never silently look like a passing one.

## The vacuous pass

**Exit 0 is not proof that a gate did anything.** It is the absence of a
complaint, and a tool with nothing to do does not complain. A gate can run, exit
0, be recorded as `PASS`, be pasted into a story as evidence, and have tested
nothing whatsoever.

This has happened for real. A `cargo test` in a workspace whose root is also a
package tests only the root package and skips every member crate; the gate ran
in under a second, printed `running 0 tests`, exited 0, and passed. The crate it
skipped was the one holding the product's data-integrity code.

Which tools are honest about having no work is not guessable:

| Gate command | With zero work to do | Safe? |
|---|---|---|
| `cargo test` at a workspace root | exit 0, `running 0 tests` | **no** |
| `biome lint <dir with no source>` | exit 0, "Checked 1 file" | **no** |
| `mypy <target resolving empty>` | exit 0, "no issues found in 0 source files" | **no** |
| Coverage threshold on a glob matching no files | satisfied silently | **no** |
| Anything with `--passWithNoTests` | exit 0 | **no** |
| `vitest run` with no matching test files | non-zero | yes |
| `pytest` collecting nothing | exit 5 | yes |
| `tsc --noEmit` with an empty `include` | exit 2, `TS18003` | yes |
| `playwright test` with no specs | non-zero | yes |

So each gate declares what evidence of work it must produce, in `project.conf`:

    gate     | unit | required | . | cargo test --workspace
    evidence | unit | test result: ok\. [1-9]

After a gate exits 0, its captured output must match its regex or it fails with
`ran but produced no evidence of work`, at the gate's own severity. The regex
asserts **volume of work observed, never success** - success is the exit code's
job, and conflating the two makes the regexes fragile against tool versions.

A gate with no `evidence` line behaves exactly as before, so this is safe to
adopt late; once `BOOTSTRAPPED=yes`, a required gate without one is reported as
a warning. `bash scripts/gates.sh --audit` lists what is missing without running
anything. Canonical regexes per ecosystem are in the `stack-profiles` skill.

### The gate that shrank

`evidence` catches a gate that did *nothing*. It does not catch one that
quietly started doing much less — a workspace member dropped from the include
list, a suite that went from 47 tests to 3. Both still match the regex. So a
gate can also declare a floor:

    evidence | unit | Tests +[1-9][0-9]* passed
    floor    | unit | 40

The number is read out of the evidence match, so a floor needs an evidence line
whose regex covers the whole number; `--audit` refuses one that does not, or a
floor that is not a number. Every full run prints `observed <n>` for any gate
with an evidence line, so the count is visible before anyone commits to a
floor.

Raise a floor in the story that adds the tests. **Never lower one to make a
gate pass** — that is the gate equivalent of deleting a failing test. A
legitimate drop (a suite genuinely split in two) is a change to explain in the
story, like any other.

### The directory nobody was testing

A coverage threshold on a glob that matches nothing is satisfied silently, and
a test written in a directory no project includes is committed and never runs.
Neither is visible in the configuration — reading the configuration is how it
stays invisible. It is visible immediately if you ask the runner what it can
see, so `project.conf` carries commands that do exactly that:

    discovery | platform | . | pnpm exec vitest list | grep -q "src/platform/"

`bash scripts/doctor.sh` runs them. Add one for every directory carrying a
coverage threshold and every workspace member whose tests must run. **A claim
about what a runner discovers is verified by running the runner**, never by
reading its globs — this was found the hard way, by a probe test that turned
out to be absent from `vitest list`.

## A gate the story requires of itself

`integration` is optional for the repo because it needs a browser, and a busy
laptop should not block unrelated stories on it. But a story whose central
claims are only ever checked *there* — "the canvas draws a non-blank first
frame", "the device pixel ratio survives a resize" — can pass every required
gate with its actual evidence unrun, and law 3 reads as satisfied.

So a story can escalate a gate for itself, in its frontmatter:

    required_gates: [integration]

`gates.sh` treats it as required while that story is active, and says
`required by story WORLD-003` wherever it reports it. Optional for the repo,
binding for the story that depends on it. A waiver cannot silence it — that is
a bypass, refused the same way it is on any required gate — and
`check-boundaries.sh` refuses a PR whose recorded run has no PASS for a gate
the story requires.

Use it whenever an acceptance criterion is verified only in an optional gate.

**`optional` means "this gate reports information". It never means "this gate
is the only thing testing a shipped feature"** - and it gets there without
anyone deciding it should. A test project that needs a real browser, an
`integration` gate marked optional because it needs one, a coverage `include`
that skips the same directory: each is right on its own, and together they put
every test of a renderer where nothing could block on it while `All required
gates passed` printed underneath. `gates.sh` could not notice, because nothing
in `project.conf` said which paths a gate exercises. Now something does:

    covers | unit        | src/core/**
    covers | integration | src/render/**

With any `covers` line present and a story active, every run - `--fast`
included, because GREEN ends with `--fast` and GREEN is where the source first
exists - takes the story's changed source paths, the diff against `main`
committed or not, and matches them. A path only optional gates read **fails
the run** and names the fix: `required_gates` in the story, or a `covers` line
for a required gate that reads it. A path no gate claims **warns**: the
manifest is incomplete or the file is genuinely ungated, and only a person can
say which. Tests are not the artifact and are not checked.

Write what the runner can see, not what the layout suggests: a
`covers | unit | src/**` over a vitest project whose include skips
`src/render/` is a lie the check will believe. Pair each line with the
`discovery` line that proves it. The story still names, before RED, the
required gate that would fail if its artifact broke - see `story-authoring` -
because the check catches the case at GREEN, and RED is where promoting a gate
is a decision rather than a scramble.

## WARN must mean something changed

Optional gates report rather than block, which is not the same as ignorable -
a WARN on `integration` has to be read. That only works if WARN is rare. An
optional gate that is *known* to fail - a mutation tool the stack cannot run
yet, an end-to-end suite waiting on a service - would otherwise WARN on every
run for the life of the project, the next agent learns to skip past WARNs, and
the day `integration` regresses its WARN sits in a list next to one that has
been noise for sixty stories.

So a known failure is declared, with its reason, in `project.conf`:

    gate   | mutation | optional | . | pnpm exec stryker run
    waiver | mutation | stryker needs a TS compiler API TS 7 lacks; stack.md s4

`gates.sh` then reports it as `KNOWN`, with the reason inline, and `WARN` is
reserved for a failure nobody declared. A waived gate still runs; when it
passes, the summary says the waiver is no longer needed and to remove it.
Waivers are refused on required gates - that would be a bypass with a nicer
name. Leaving a gate unconfigured is not an alternative: a required gate with
no command fails once `BOOTSTRAPPED=yes`, deliberately.

## BLOCKED: the gate the machine would not run

A gate's result used to be a boolean derived from an exit code, and there is a
third state that is neither pass nor fail: **the environment would not let the
gate start.** A required gate failed eight consecutive runs on one machine with

    error: failed to run custom build command for `fantasy-world-builder v0.1.0`
    Caused by: could not execute process `...build-script-build` (never executed)
    Caused by: An Application Control policy has blocked this file. (os error 4551)

which is Windows Smart App Control refusing an unsigned, locally built
executable by reputation. The crate was untouched on the branch, and the same
command passed on CI three times the same day. Reported as FAIL, it produced six
pointless retries, a Stop hook that offered only "fix it or move the story back
to RED" - neither of which applied - and an hour spent inventing a third path.

`gates.sh` now recognises the shapes that mean *this process never started* and
reports `BLOCKED`, with `RESULT=blocked` in the stamp and **exit 3**, distinct
from a failure's 1. A runner that says it differently gets a `blocked-when` line
in `project.conf`. What BLOCKED is *not* is a pass: the run is still non-zero and
the story still has no verdict on that gate.

The path, when a required gate is BLOCKED:

1. **Read the log before theorising, and do not retry on a hunch.** Retrying
   helps only where the blocked file is rebuilt with a different hash. In that
   story the blocked file was the package's *cached build script*, which cargo
   never rebuilds, so six retries could not have worked - and deleting the cache
   rebuilt a byte-identical binary. What sent the orchestrator down that road was
   a line in `environment.md` recording a *measurement* as a *rule*: "can fail
   once with os error 4551 - retry before believing it", true of a fresh test
   binary and false of this. A recorded workaround states **what was measured and
   on what**, or it costs more than it saves.
2. If the block is a **missing or unrunnable tool** rather than a policy, that is
   `scripts/doctor.sh` and `docs/wiki/environment.md`, and it is fixable.
3. Otherwise it is a **PO decision recorded in the story's `## Notes`** - not in
   `## Gate results`, which `gates.sh` rewrites on every run: which gate, the log
   line quoted, and what makes this the environment and not the code (the branch
   does not touch what the gate builds; the same command passed elsewhere). One
   line of it carries **the gate id and the words `pending CI`** together.
4. The story **may reach REVIEW**. `check-boundaries.sh` accepts a recorded result
   of `blocked` there when that line exists, and refuses it when it does not.
5. The story **may not reach DONE** until the PR's CI run for that gate is quoted
   in `## Notes`, on a line carrying **the gate id and the run URL**. CI is a
   different machine under a different policy, which is the entire reason this
   path exists rather than a waiver, and `check-boundaries.sh` enforces it.

Never reach for a waiver here: waivers are for optional gates, and an
environment-blocked required gate has not been verified by anything yet.

## The gate record is written by the tool

A full run of `gates.sh` writes its own summary into the active story's
`## Gate results` (or `--story <id>`): a marker line, the UTC time, the commit,
a hash of every source, test and config file plus the harness's scripts and
manifests (not its prompts - no gate reads a command file) as they were on disk
when the gates ran, and the summary. `--gate` and `--required` runs are not recorded,
because a partial run is not evidence that the story passes its gates.

Nobody pastes it and nobody edits it. `check-boundaries.sh` refuses a PR whose
section has no marker, whose recorded result is not `pass`, or whose recorded
hash does not match the code being merged - which means changing source after
the last full run forces another full run before the PR is acceptable. In CI
the hash is recomputed at the PR head commit, so base-branch drift does not
false-fail it. That turns law 3 from "run it and paste the result" - a step an
agent motivated to finish could fake without anything noticing - into a record
the tool wrote and the code has to match.

## A gate that has never been observed to fail is not a gate

The first law says no production code without a failing test that demanded it,
and `rules.md` says a test never observed to fail is not a test. The same
applies to the gates themselves - they are the mechanism the whole discipline
rests on, and they are code like anything else.

**When a story adds or changes a gate: break the thing it guards, watch the gate
fail, record the output, and revert.** This is RED, applied to a gate. Write it
into the story's `## Gate probes` section.

It is not ceremony. A lint rule forbidding `core/` from importing `ui/` was
probed this way and turned out to catch the aliased import `@ui/App` but not the
relative `../../ui/App` - which is the form somebody actually crosses a boundary
with by accident. Nothing but breaking it on purpose would have found that.

What to break, per gate: delete or rename the test files (`unit`); remove a test
covering a branch (`coverage`); write the violation the rule forbids (`lint`);
introduce a type error (`typecheck`); break an import (`build`). Revert every
probe before moving on, and say in the story that you did.

## Rules for triage

1. Read the actual output before forming a theory. It is in the log file.
2. Fix the cause, not the symptom. A type error that disappears when you widen
   a type to `any` has not been fixed.
3. Never reach green by weakening a test, loosening a lint rule, lowering the
   coverage threshold, or adding a suppression comment - unless the user agrees
   the rule itself is wrong, and it is recorded in the story.
4. If a gate failure means a **test** is wrong, the story returns to RED. Say so
   and record why.

4a. More generally: **if the only legal fix for a gate failure is a write this
   phase forbids, the story returns to RED.** Not only when the test is wrong -
   the everyday instance is a `format` or `lint` gate WARNing on one test file
   the story itself added, needing a one-line reflow, with the assertion
   perfectly correct. GREEN freezes test files and so does GATES, so the phase
   whose whole job is fixing lint failures is the phase that cannot fix that one.
   GATES → RED → the one line → GATES, with the reason in `## Regressions`. The
   two wrong answers are documenting a whitespace failure as an expected WARN,
   and reaching for a tool the lock does not inspect.

4b. If the gate reported `BLOCKED` it did not run, and neither rule 2 nor rule 4
   applies. Take the path in "BLOCKED: the gate the machine would not run"
   above. Do not retry it six times, and do not paper over it with a waiver.

5. A gate that fails because it produced no evidence of work is **not** fixed by
   deleting its `evidence` line. Fix the command so it does the work, or - if
   the regex is genuinely wrong for this tool version - correct the regex and
   say so in the story. Removing the line is the gate equivalent of deleting a
   failing test. The same holds for lowering a `floor`, dropping a `discovery`
   line, or removing a gate from a story's `required_gates`.

`reference/triage.md` has the per-gate playbook, including what a coverage
failure actually tells you and when a suppression is legitimate.
`reference/configuring.md` covers wiring gates for a new stack.
