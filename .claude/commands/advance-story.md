---
description: Move one story forward by exactly one phase
argument-hint: <story-id>
allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/gates.sh:*), Bash(bash scripts/check-boundaries.sh:*), Bash(bash scripts/task.sh:*), Bash(git:*), Read, Grep, Glob, Edit, Write, Task
---

Story: $1

Current harness state:
!`bash scripts/phase.sh show`

Act as the **lead-po** orchestrator and advance this story by **one phase only**,
then stop and report. The user chose this command over `/complete-story`
because they want to inspect the result before the next phase runs.

Read `docs/backlog/stories/$1.md` first. Then, based on its current phase:

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
(`story/<id>-<slug>`) if it does not exist. Set the phase; `phase.sh` refuses
if a `depends_on` story is not DONE or the checkout is on another branch, and
either refusal is a reason to stop and tell the user, not to reach for
`--force`. Then dispatch the
**test-developer** subagent with the story path, the criteria restated in full
and **partitioned by oracle** — which carry a settled number to read out, which
are oracle-free and need an invented metric with a negative control, which are
mechanical and want exact pinning (see `story-authoring`, "Brief RED by
oracle") — the relevant constraints from `docs/wiki/`, and the exact test
command from `.claude/harness/project.conf`. When it returns, verify: read the test files it
wrote and run the tests yourself. Confirm they fail, and fail for the right
reason. If they pass, or fail on an unrelated error, send it back.

Then run `bash scripts/gates.sh --fast` and read it before leaving RED. This is
not a pass/fail check — the test gates are *supposed* to be red here. It asks a
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
each recorded control value against the shipped module. When it returns, run the
tests yourself, then `bash scripts/gates.sh --fast` — the same admissibility
question, now expecting green.

**GREEN → GATES.** Set the phase, then — **before** `gates.sh` — run every entry
in `## Deferred verifications` that names GATES as its owner, and paste what
happened into the block: what was mutated, which assertion went red, and that the
file was restored. Use `scripts/mutate.sh`, which is allowed in every phase and
verifies its own restore. Do three mutations rather than one where the entry is
about a format or a codec, and make one of them a wrong **value** rather than a
missing field: two dropped-field mutations of one codec were each caught only by
its property test, while the one that flipped a float writer's byte order was
caught by six tests — and only because the container assertions read the bytes
through a reader importing nothing from the source tree. A round-trip suite that
verifies a format through its own reader passes against an encoder that is
uniformly wrong. If an entry can no longer run, write `WAIVED` and the reason;
leaving it silent is what `check-boundaries.sh` now refuses.

Then run `bash scripts/gates.sh`. It writes
its own summary into the story's `## Gate results`; never paste or edit one.
On failure, dispatch the **feature-developer** to fix it, unless the failure
means a test is wrong — in which case return the story to RED (see below). A
`WARN` on an optional gate is read, not skipped; a known permanent failure gets
a `waiver` line with its reason.

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

1. `bash scripts/phase.sh set $1 REVIEW`
2. Commit, with a message that names the story and what it does.
3. `bash scripts/check-boundaries.sh` — the second script CI runs, and the one
   `gates.sh` cannot stand in for. Fix anything it reports before pushing.
4. Push the branch and open a PR whose body links the story file and lists the
   acceptance criteria with the test that covers each.

The phase is set **before** the commit, and the order is not cosmetic:
`check-boundaries.sh` reads the phase out of the *committed* story frontmatter,
so a commit made while the story still says `phase: GATES` is a commit CI
rejects. Committing first happens to survive when the PR is opened before that
job runs, which makes it fail intermittently rather than every time — the worse
of the two. Do not reorder these to be helpful.

**REVIEW → DONE.** Only once the PR is merged. Set the phase to DONE, clear the
lock with `bash scripts/phase.sh clear`, and report what the next story is.

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
  is easy to write. Against the committed implementation, pick a mutation the
  table predicts a count for, preferring one whose predicted catch is a
  **single** assertion (a lone assertion is where a vacuous test hides), run
  the suite, compare the count, and confirm the suite is green again after the
  file is back. Two mutations, one run each, is enough; matching counts turn the
  table from a claim into evidence. Record it in `## Notes`.

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

Finish by reporting: the phase you moved from and to, what changed, the real
command output that justifies it, and the exact command to run next.
