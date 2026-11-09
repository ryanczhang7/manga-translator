---
description: Move one story forward by exactly one phase
model: fable
argument-hint: <story-id>
allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/gates.sh:*), Bash(bash scripts/attest.sh check:*), Bash(bash scripts/check-boundaries.sh:*), Bash(bash scripts/selftest.sh:*), Bash(bash scripts/selftest-needed.sh:*), Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh:*), Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh --changed:*), Bash(bash scripts/ci-local.sh:*), Bash(bash scripts/task.sh:*), Bash(bash scripts/story.sh:*), Bash(git:*), Read, Grep, Glob, Edit, Write, Task
---

Story: $1

Current harness state:
!`bash scripts/phase.sh show`

Act as the **lead-po** orchestrator and advance this story by **one phase only**,
then stop and report. The user chose this command over `/complete-story`
because they want to inspect the result before the next phase runs.

Do not read the whole story file: it grows as the story runs, and every turn
re-sends it. Read the frontmatter with `bash scripts/story.sh frontmatter $1`,
then each section the current phase needs with
`bash scripts/story.sh section $1 <name>` (`bash scripts/story.sh sections $1`
lists the names, with their lengths):

| Phase | Read with `bash scripts/story.sh section $1 <name>` |
|---|---|
| PLANNED → RED | Context, Acceptance criteria, Contract, Deferred verifications, Model guidance, Out of scope |
| RED → GREEN | Acceptance criteria, Contract, Handoff: RED -> GREEN, Deferred verifications, Regressions, Model guidance |
| GREEN → GATES | Deferred verifications, Gate results, Gate probes, Model guidance, Notes |
| GATES → REVIEW | Diff review, Gate results, Gate probes, Deferred verifications, Acceptance criteria, Test plan, Model guidance, Notes |
| REVIEW → DONE | Notes |

A dispatch prompt is built from those sections, pasted, not from the file; a
`## Handoff` section is pasted whole, because it is the channel between phases.
A `## ` line inside a fenced block is read as a heading, because that is
`check-boundaries.sh`'s reading, so in a story that has one `section` can
return the wrong lines - a section cut short, stray fenced lines, or the stray
lines in place of the real section - and still exit 0. When
`bash scripts/story.sh sections $1` lists a name twice, or a heading the story
should not have, list the real boundaries with
``grep -n -e '^## ' -e '^```' -e '^~~~'`` on the story file and read that
section by line range.
Then, based on the story's current phase:

**PLANNED → RED.** Confirm the acceptance criteria are testable; fix them with
the user if they are not — this is the last phase in which they may change
without an `## Amendments` entry. Then name the gate that would fail if this
story's artifact broke, and check it is `required`. Read the criteria against
`bash scripts/gates.sh --list`, whose `covers` lines say which paths each gate
reads: if the only gate that exercises what the story builds is `optional` — a
browser-driven `integration` suite, most often — put it in the story's
`required_gates` now. That is a PO decision made here, not a discovery for
GATES; `gates.sh` will fail a GREEN run whose changed source only optional
gates read, and by then it is a scramble. Three individually sound exclusions (a test project that
needs a real browser, an `optional` integration gate because it needs one, a
coverage `include` that skips the same directory) once combined so that every
test of a renderer ran where nothing could block on it, and `All required gates
passed` was printed over a story whose artifact no required gate had touched.
If no gate at all can verify the artifact, the story is not ready.

Then three things that belong to you and cannot be delegated to RED:

**Pin the `## Contract`.** Module paths, exported names, exact signatures, the
semantics behind every number (which way a drag moves the world, where a value
clamps, what the floor is), the accessible markup, the oracle partition, and any
baseline measurement the story may read out rather than re-derive. Say in the
section that RED may amend a block in place with a reason and that GREEN builds
what the amended block says. A story that did this pinned eight blocks, produced
326 tests and a GREEN with no shape drift, and RED amended seventeen of them —
two of which were real design traps GREEN would have hit late. `story-authoring`
has the shape.

**List the callers of every changed signature.** For each *existing* export whose
signature the contract changes, `rg` every caller — source and test — into the
story before dispatch, and require RED's handoff to state that the list was
checked against the tree. RED cannot do this: during RED the old signature still
exists, so its callers still compile and are absent from RED's typecheck. One
missed file compiled happily through a 221-error RED, stopped collecting when
GREEN deleted the old signature, and turned 25 tests — the only verification of a
change GREEN had just made — into 25 silent skips. Running the gates at the end
of RED would not have caught it; every gate was green.

**Name the verifications RED cannot perform, and the phase that owns each.** A
negative control for a codec, a threshold or a round trip has to break the real
implementation to mean anything, and in RED there is nothing built to break. Write
each one into `## Deferred verifications` now, as a falsifiable condition with an
owning phase — *"with one field dropped from the encoder, AC-1's property must
fail; RED cannot run this; owner: GATES"* — and expect RED to *decline* it in the
handoff rather than claim it. Prefer GATES as the owner: source is writable there,
and a story that bounces back to RED mid-cycle then earns its corrected
assertions from the same experiment for free. `check-boundaries.sh` refuses a PR
whose block names no phase, or that reaches REVIEW with neither a pasted result
nor an explicit `WAIVED`; before that check existed the one story that ran its
deferred control ran it because it had written the promise into its own report
twice.

**Check the epic's done-when against these criteria.** If the epic promises
something no story between the last one and this one delivers — "the app opens on
a generated landmass", when `mount()` still draws a graticule — that gap is
yours to close, as a numbered PO decision recorded in the story and reported to
the user *first*, so they can overrule it before GREEN. Never absorb it silently,
and never skip it silently.

Create and switch to the story's branch
(`story/<id>-<slug>`) if it does not exist. Before setting the phase, commit
the story file on that branch while it still says `phase: PLANNED`:
`check-boundaries.sh` freezes the criteria at the last state committed at
PLANNED, so a refinement first committed together with RED is compared with the
base branch instead and needs an `## Amendments` entry. Set the phase;
`phase.sh` refuses if a `depends_on` story is not DONE or the checkout is on another branch, and
either refusal is a reason to stop and tell the user, not to reach for
`--force`. Then dispatch the
**test-developer** subagent with the story path, the criteria restated in full
and **partitioned by oracle** — which carry a settled number to read out, which
are oracle-free and need an invented metric with a negative control, which are
mechanical and want exact pinning (see `story-authoring`, "Brief RED by
oracle") — the relevant constraints from `docs/wiki/`, and the exact test
command from `.claude/harness/project.conf`, and tell it to run that command
and `--fast` through `bash scripts/attest.sh --`. When it returns, verify: read
the test files it wrote, then run `bash scripts/attest.sh check -- <test command>`
with the exact words it ran. **Run the command yourself only when the answer is
not `fresh`** (`stale`, `void` or `none`), directly rather than through
`attest.sh` (you run only its `check`), and say in the story which it was.
`fresh` says the run was made on this tree, not that it failed the right way:
read `exit:` and `last:`, and the log the record names, and confirm from that
log that the tests fail, and fail for the right reason. If they pass, or fail on
an unrelated error, send it back.

**Unless the runner did not start at all** — no test in the repository ran and
`gates.sh` failed outright. That is a real state, it is sometimes the correct
RED, and "confirm they fail for the right reason" cannot be discharged in it: a
story adding a global test mechanism has to wire the runner's own config, which
is frozen during GREEN, so the config names modules GREEN has not written yet.
`tdd-cycle`, "When RED breaks the RUNNER, not the tests", has the dilemma and why
this branch is the right one.

Verify it differently rather than waving it through. Confirm that the **only**
reason the runner cannot start is the named absence — not a syntax error, not a
second missing import — and that the failure names **exactly** the modules the
contract obliges GREEN to write. Then say so in the commit and paste the error
into the handoff. An agent arriving at that tree otherwise cannot tell a
deliberate dark suite from a broken repository, and will debug the wrong thing.

Then check `bash scripts/attest.sh check -- bash scripts/gates.sh --fast` the
same way - running it yourself, directly, only when the answer is not `fresh` - and read
its log before leaving RED. This is not a pass/fail check — the test gates are *supposed* to be red here. It asks a
different question: are these tests **admissible** to the gates that will judge
them? Expect lint and typecheck to pass, and the test gates to fail with the
assertion the story is about. A test gate failing for any other reason — a
timeout, a coverage threshold, a config error, a lint rule the test file trips —
means the tests are not admissible yet and RED is not finished. Note especially
that the coverage gate runs the same tests *instrumented*, which is slower than
the plain test command and slower again on CI hardware; a test that only just
fits its timeout here does not fit there.

**RED → GREEN.** Check the `## Handoff: RED -> GREEN` section is filled in; if
it is not, the RED phase is not finished. Where the story has negative controls
— the deliberately broken inputs a threshold has to reject — the handoff must
carry their **expected values**, not just the fact that they exist: in RED the
suite failed at import, so no assertion in the file ran and every control is an
unverified claim. Set the phase, then dispatch the **feature-developer** subagent
with the story path, the handoff, and the test command, and tell it to confirm
each recorded control value against the shipped module and to run the test
command and `--fast` through `bash scripts/attest.sh --`. When it returns, read
the files it wrote, then `bash scripts/attest.sh check -- <test command>` and
`bash scripts/attest.sh check -- bash scripts/gates.sh --fast` — the same
admissibility question, now expecting green. Run a command yourself, directly,
only when its answer is not `fresh`, and say in the story which it was; a `fresh` record
still has to show `exit: 0` and a passing `last:` line.

**GREEN → GATES.** Set the phase, then — **before** `gates.sh` — run every entry
in `## Deferred verifications` that names GATES as its owner, and paste what
happened into the block: what was mutated, which assertion went red, and that the
file was restored. Use `scripts/mutate.sh`, which is allowed in every phase and
verifies its own restore, and run each entry against the one suite that holds
its assertion, not the full suite. How many entries a story carries is the
budget in `rules.md`, "Mutation work per story": by default one "defect put
back" mutation for the story's central claim, plus what the law owes for tests
written against existing code; a format or codec story may add one wrong
**value** mutation. Anything beyond that — earning every assertion that passed on
arrival — is `/audit-mutations`' work, not this phase's. If an entry can no
longer run, write `WAIVED` and the reason; leaving it silent is what
`check-boundaries.sh` refuses.

Then dispatch a **feature-developer** on the GATES row of `models.conf` to run
the full gates, with the brief below. It runs
`bash scripts/attest.sh -- bash scripts/gates.sh` and returns its verdict: the
exit status, last line, duration and log path (the record's `exit:`, `last:`,
`duration:` and `log:`), and the model it resolved to. Check it with
`bash scripts/attest.sh check -- bash scripts/gates.sh`: require `fresh`, read
`exit:` (0 passed, 1 failed or not recorded, 3 BLOCKED, the paragraph below)
and the verdict line in the log it names, `All required gates passed ...` or
`N required gate(s) failed.`, and record the resolved model under
`## Model guidance`. For this command `last:` is the check-boundaries tip
printed after the verdict, not the verdict.
`stale`, `void` or `none` means it did not run that command on this tree: send
it back, and say so in `## Notes`.

The brief, here and for the self-test at GATES → REVIEW: the worktree's
absolute path and "run every command from there"; the one command, through
`bash scripts/attest.sh --`; "run nothing else in this worktree while it runs";
and "change nothing, unless the command is `bash scripts/gates.sh` and a
required gate fails: then fix it under your GATES rules and run it again".
While it is out, you run nothing in that worktree either.

`gates.sh` writes its own summary into the story's `## Gate results`, whoever
runs it; never paste or edit one. A failure the dispatch could not fix goes
back to the **feature-developer**, unless the failure
means a test is wrong — in which case return the story to RED (see below). A
`WARN` on an optional gate is read, not skipped; a known permanent failure gets
a `waiver` line with its reason.

**The stamp covers tracked and staged files only** — the tree `git commit -a`
would make, which is what CI recomputes. A file the story created must be
`git add`-ed before the full run. With an active story, `gates.sh` refuses to
record (exit 1) while it names any `UNTRACKED` file; a user's own stray that
should stay untracked belongs in `.git/info/exclude`, not in the commit.

**A required gate reported `BLOCKED` (exit 3) is a third thing, and it is your
decision.** BLOCKED means the environment would not let the gate start — a
policy refusing an unsigned local binary, a missing runtime — so it neither
passed nor failed, and neither "dispatch the developer" nor "back to RED"
applies. Do not retry it on a hunch: the case this came from retried six times
on the strength of a sentence in `environment.md` that recorded a measurement as
a rule, while the blocked file was a cached build script the toolchain never
rebuilds. Instead:

1. Read the log. If it is a missing or unrunnable tool, that is `doctor.sh` and
   `environment.md`, and it is fixable — fix it and re-run.
2. Otherwise record a numbered PO decision in the story's `## Notes` — not in
   `## Gate results`, which `gates.sh` rewrites on every run: which gate, the log
   line quoted, and what makes this the environment rather than the code (the
   branch does not touch what the gate builds; the same command passes
   elsewhere). One line of it must carry **the gate id and the words `pending
   CI`** together; `check-boundaries.sh` looks for exactly that, because words
   scattered through a story are satisfied by a story that mentions CI about
   something else.
3. The story **may** then reach REVIEW. `check-boundaries.sh` accepts a recorded
   result of `blocked` at REVIEW when that line is there, and refuses it when it
   is not.
4. The story **may not** reach DONE until the PR's CI run for that gate is quoted
   in `## Notes` — one line carrying **the gate id and the run URL**. CI is a
   different machine under a different policy, and that is the entire reason this
   path exists rather than a waiver. `check-boundaries.sh` enforces this at DONE.

Any workaround you write into `environment.md` states **what was measured and on
what**. A workaround is evidence, not a decision.

**GATES → REVIEW.** Only when every required gate passes. If this story added or
changed a gate, `## Gate probes` must record it having been observed to fail —
a gate nobody has seen fail is not evidence of anything, and refusing to move on
without it is the point.

Then, **in this order**:

1. Review the story's diff and its callers with the `diff-review` skill.
   Dispatch a **fresh** `feature-developer`, not the one that wrote the code,
   on the GATES row of `models.conf`; it changes no file and returns its
   report. Paste that report into a `## Diff review` section of the story,
   directly above `## Gate results`, and record the model the dispatch
   resolved to. A Must fix in the code is made in GATES by a feature-developer
   dispatch; the tree has changed, so `bash scripts/gates.sh` runs again and
   these steps start over, with a review of the fix. A finding that needs a
   test added or changed is a return to RED, with a `## Regressions` entry. A
   finding that an acceptance criterion is wrong is an `## Amendments` question
   for the user. Go on only once the report's last line is `Verdict: Ship.`.
   It comes before the self-test because a fix changes the tree, and a fix
   found after the self-test wastes that run.
2. `bash scripts/selftest-needed.sh` — it answers `run` (exit 0) when the
   story's changes, committed or not, include a path `classify.sh` calls
   `harness` - the files the harness suites read - and `skip` (exit 1)
   otherwise. When it cannot compute the diff (for example no base to compare
   against, no merge base, git failing, or its own library or `paths.conf`
   not loading) it says why and answers `run`. On `skip`,
   paste its line into `## Notes` as
   `- Self-test skipped at GATES → REVIEW (<date>): selftest-needed: skip — ...`
   and go on to step 3. CI runs the self-test on the PR either way, so a
   skipped run is deferred to CI, not lost. On `run`,
   `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` — the suites this
   story's diff can break, once, while the story is still at GATES.
   `selftest-needed.sh --suites` chooses them: a suite that mentions a
   changed path, a changed suite itself, the five tree-scanning suites for
   the paths they scan, and every suite when a path cannot be placed or the
   library changed; the full run's floors audit runs first. CI runs every
   suite, and one the story never touched can still fail on its change: a
   line number another suite pins, a floor, a value an upstream suite
   asserts. Dispatch it to a `feature-developer` on the GATES row, with the
   GREEN → GATES brief: it runs
   `bash scripts/attest.sh -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`
   detached (the Bash tool's `run_in_background` with its longest timeout,
   or `nohup` from a shell), so that a tool timeout cannot kill it, and
   alone: nothing else runs in this worktree until it exits, not
   `gates.sh`, not a second self-test, nothing of yours. It returns the
   verdict, and you check it with
   `bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`,
   requiring `fresh`. Give it the expectation: CI's whole job takes about 2-4
   minutes. On the Windows host this harness is developed on, the full
   self-test took 336 s at `SELFTEST_JOBS=4` against 1,135 s serial
   (HARNESS-036), 2,894-17,015 s serial while other test runs shared the
   host (HARNESS-050..068), and 3,845-11,419 s in HARNESS-086..088.
   HARNESS-094 measured `--changed` once: it selected
   21 of 34 suites and took 6,444 s, where the full run had taken 12,502 s
   just before it on the same loaded host. That is one observation, not a
   ratio to plan by. A slow run is slower, not wrong, most often because
   other test runs share the host: keep the value, do not swap in named
   suites. If a run
   goes far past the last duration a story recorded, look for an orphaned
   self-test or gate run before blaming the host; one run stalled past an
   hour beside an orphan and passed alone. Judge it by the record's `exit:`
   and its `last:` line, `N harness suite(s) passed.`, and paste both, with
   the `duration:` and the header line the run prints first,
   `selftest: --changed — ...` (either `every suite: <reason>` or
   `<k> of <n> suite(s) selected: <names>`), into `## Notes`. A failure
   takes GATES' own routes: the feature-developer, or RED if a test is
   wrong. A fix changes the tree, so `bash scripts/gates.sh` runs again and
   these steps start over.
   The full run, `SELFTEST_JOBS=4 bash scripts/selftest.sh`, is still the
   option, dispatched, attested and checked the same way in place of the
   `--changed` run, in exactly three cases. (a) The `--changed` header says
   `every suite`: the run already is the full one, and there is nothing to
   decide. (b) The story changed a script that other scripts invoke, and
   you cannot name the suite that exercises the caller: `--suites` places a
   path by the suites that mention it, not by who calls it, which is
   HARNESS-094's declared limit. (c) CI's self-test failed on the PR in a
   suite the local `--changed` run had not selected. That failure is seen
   at REVIEW, so go back to this step with
   `bash scripts/phase.sh set $1 GATES`, fix, run `bash scripts/gates.sh`,
   and start these steps over from the review of the fix, with the full
   run in place of `--changed` at this step, before pushing again; leaving
   REVIEW follows the ordering rule below. Record in `## Notes` which
   suite the selection missed. The orphan and host-load advice above
   applies to it unchanged. CI runs every suite on the PR either way; in
   this repository its `gates` check is not required on `main`, so the
   merge is where the user reads CI's full run.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit, with a message that names the story and what it does.
5. `bash scripts/check-boundaries.sh` — the second script CI runs, and the one
   `gates.sh` cannot stand in for. Fix anything it reports before pushing.
6. Push the branch and open a PR whose body links the story file and lists the
   acceptance criteria with the test that covers each.

The phase is set **before** the commit, and the order is not cosmetic:
`check-boundaries.sh` reads the phase out of the *committed* story frontmatter,
so a commit made while the story still says `phase: GATES` is a commit CI
rejects. Committing first happens to survive when the PR is opened before that
job runs, which makes it fail intermittently rather than every time — the worse
of the two. Do not reorder these to be helpful.

`bash scripts/ci-local.sh` runs that self-test and every other step CI runs,
read from the workflow files, and ends with step 5's check. It judges the
commit, so it can only run after step 4. It runs the self-test twice and the
gates again, so it is the better check where it is fast and never a
substitute for step 2 where it is not.

**REVIEW → DONE.** Only once the PR is merged. Set the phase to DONE, clear the
lock with `bash scripts/phase.sh clear`, and relay the report that
`phase.sh set <id> DONE` printed — the output of `bash scripts/plan.sh after
<id>` — to the user **as printed**: the `Next:` story and its command, any
`Alongside:` set with its `git worktree add` lines, `In flight:` and
`Blocked:`. Do not rebuild it from memory; run `bash scripts/plan.sh after
<id>` again if the output scrolled away. When that report carries an `Epic:`
line — the closed story's `epic:` is non-empty and no other story in that epic
is short of DONE — it recommends `/audit-mutations <epic>`, scoped to the paths
the epic's stories touched — the exhaustive mutation work that `rules.md`,
"Mutation work per story", keeps out of every story. Recommend it; never run it.
A story with an empty `epic:` gets no `Epic:` line and no recommendation.
Above that report the DONE output carries `bash scripts/tidy.sh`'s census of
finished worktrees and merged branches; when it counts any, recommend
`bash scripts/tidy.sh --apply` to the user, and never run it unasked.

Before you call the PR green, **read the timings out of its first CI log** — not
just the pass/fail. A pass within 10 % of a limit is a pending failure, and a
story has already been sent back to RED from REVIEW by it: a green run cleared a
30 s hook default by three seconds, and the two runs after it, on a docs-only
commit with identical code, both timed out. Check the hooks as well as the tests;
for anything driving a GPU the cost lands in teardown, where the local machine
reports nothing at all. A gate that reached REVIEW marked *pending CI* is checked
here too, and its CI run quoted into `## Notes` on a line carrying the gate id
and the run URL, or `check-boundaries.sh` refuses to call the story DONE.

**Returning to RED from GREEN or GATES.** A test that is wrong sends the story
back to RED; it is never edited into passing. The trigger is wider than that,
though, and the wider form is the one to hold: **any gate failure whose only
legal fix is a write the current phase forbids.** A `format` gate WARNing on one
test file the story itself added, needing a one-line reflow with the assertion
entirely correct, is the everyday instance — GREEN freezes test files and so does
GATES, so the phase whose stated job is fixing lint failures cannot fix that one.
Take the return deliberately and record why; the two wrong answers are
documenting a whitespace failure as an expected WARN and reaching for a tool the
lock does not inspect.

On arrival RED means something
narrower than it did the first time, because the implementation already exists
and may well be correct:

- Set the phase back to RED and say in `## Regressions` what is wrong with the
  test, how it was found, and what it should assert instead.
- The **test-developer**'s remit is the defective test and nothing else. Source
  is frozen again by the lock, which is correct — do not treat that as a signal
  to change phase.
- "Watch it fail" cannot apply, because the code whose absence would make it
  fail is no longer absent — so it is replaced, not waived. The corrected
  assertion passes on its first execution and every one after, whether or not it
  asserts anything, and one of these two is required before the phase ends:
  **probe** it by mutating the *specific* production behaviour the test claims
  to pin, watching that one assertion go red, and reverting (this is
  `## Gate probes` applied to a test); or, where the defect was about *cost*
  rather than correctness — a test too slow for its timeout under
  instrumentation — record the before and after measurement under the gate
  command, not the plain test command. The **output** goes in `## Regressions`,
  not a description of it: `check-boundaries.sh` refuses a PR whose
  `## Regressions` or `## Gate probes` shows none.
- GREEN may then be a genuine no-op: the source is untouched and already passes.
  Verify that yourself by running the suite and the fast gates. Do **not**
  dispatch the feature-developer with nothing to do — an agent given no work
  will find some. *May* be a no-op, not *is* one: the same return has also needed
  a real source fix, when the corrected test turned out to pin a real defect.

**Returning to RED from REVIEW is the same return with one extra hazard.** The
branch is published and CI has already run against a commit that is now
superseded, so the correction lands as a *second* commit on an open PR rather than
as a fix nobody saw. Everything above still applies, and one thing more: **the
ordering rule from GATES → REVIEW applies again on the way out.** Set the phase
back to REVIEW *before* the second commit, or that commit carries `phase: RED` in
its frontmatter and the `boundaries` job fails a PR that was green ten minutes
earlier. It applies on every exit from REVIEW, not only the first.

Rules for you as orchestrator:

- Change phase only with `bash scripts/phase.sh set $1 <PHASE>`.
- Verify every subagent claim against the filesystem and a real command run. A
  report of success is a claim.
- **A claim that the contract itself is wrong — an acceptance criterion, a
  threshold, a frozen test — you reproduce independently before accepting it:
  different inputs, and without reusing the subagent's own code.** Running its
  probe again is not verification. Record the reproduction in the story next to
  the `## Amendments` or `## Regressions` entry it justifies. This is the exact
  shape of claim an agent makes when it wants to stop failing — *the
  specification is wrong, not my work* — and it is also the shape of the two
  most valuable escalations this harness has seen. Independent reproduction is
  the only thing that separates them, and it is cheap: a fresh probe on
  different inputs, or reading the fixture and enumerating the cases the file
  asserts to show no rule satisfies all of them.
- **And it runs the other way: an instruction of yours that names a *mechanism*
  is a claim too.** When you tell a subagent *how* — call this function to force
  the work to complete, read the value from here, use that API — you are asserting
  something you may not have measured. A story's own PO decision named a GL call
  as the way to obtain a GPU-inclusive frame rate; the feature-developer probed
  the instruction instead of following it and found that the call does not wait on
  that browser, nor does the fence-based alternative, and that only a one-pixel
  read-back does. Followed literally, the decision would have published ~8,000 fps
  at every input size — a plausible number with nothing behind it. So say in the
  dispatch that a named mechanism is checkable, not sacred: a subagent that can
  cheaply verify one should, and should report when it does not hold. Treat that
  report as the valuable escalation it is.
- **When the claim is "this suite discriminates", the check is a mutation you
  run.** A handoff's mutation table — *changing X fails 9 tests, changing Y
  fails 1* — could not be verified in RED, where the suite did not load, and
  is easy to write. Against the committed implementation, run **one** mutation
  from the table: the one whose predicted catch is a **single** assertion (a
  lone assertion is where a vacuous test hides), against the one suite that
  holds that assertion. Compare the count, and confirm the suite is green again
  after the file is back. Record it in `## Notes`. Verifying the rest of the
  table is `/audit-mutations`' work (`rules.md`, "Mutation work per story").

  Use the script, in any phase:

      bash scripts/mutate.sh src/terrain.ts 's/1664525/1664526/' -- <test command>

  It backs the file up to an explicit path, applies the expression, runs the
  command, restores, verifies the restore with `cmp`, prints the line it put back
  and logs what happened. Doing it by hand cost one mutation its backup to an
  unset `$TMPDIR`, leaving the restore to depend on the substitution happening to
  be an exact inverse of a single-occurrence match — and `sed -i` in RED is
  working around the lock, which no longer lets it through. The failure
  screenshots a runner writes under an ignored directory while you do this are
  not a code change, and the Stop hook knows it.
- Keep the story file current as you go — it is the only thing the next agent
  will see.
- Stop and ask the user on any product ambiguity. Do not invent scope. A
  subagent that escalates a scope question instead of resolving it quietly has
  done the right thing; answer it rather than sending it back.

Finish by reporting, as `rules.md`, "Reporting to the user" says: the phase you
moved from and to, what changed, the real command output that justifies it, and
last, the command to run next. Take it from `bash scripts/plan.sh $1` while the
story is still in flight, or relay `bash scripts/plan.sh after $1` once it closed.
