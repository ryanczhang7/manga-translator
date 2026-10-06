---
description: Drive one story from its current phase all the way to a merged-ready PR
model: fable
argument-hint: <story-id>
allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/gates.sh:*), Bash(bash scripts/check-boundaries.sh:*), Bash(bash scripts/selftest.sh:*), Bash(bash scripts/ci-local.sh:*), Bash(bash scripts/task.sh:*), Bash(git:*), Read, Grep, Glob, Edit, Write, Task
---

Story: $1

Current harness state:
!`bash scripts/phase.sh show`

Act as the **lead-po** orchestrator and run this story through every phase to
REVIEW without stopping for approval between phases. Follow exactly the same
per-phase procedure as `/advance-story` — the phases, the dispatches, the
verification and the rules are identical. The only difference is that you keep
going.

Two steps in that procedure are ordered for a reason, and running without
approval between phases is exactly when they get quietly reordered:

- **RED and GREEN each end with `bash scripts/gates.sh --fast`.** Not for a
  pass — in RED the test gates should be red — but to see whether the tests are
  admissible to the gates that will judge them. The coverage gate runs the same
  tests instrumented, which is slower than the test command and slower again on
  CI. A suite can pass RED, pass GREEN, pass every local gate, and still fail a
  required gate in CI on a timeout nobody measured.
- **GATES → REVIEW runs the full `bash scripts/selftest.sh` first**, detached
  and alone, while the story is still at GATES. Then it sets the phase before
  committing, runs `bash scripts/check-boundaries.sh`, and pushes and opens
  the PR. A suite the story never touched can fail on its change, and CI runs
  them all. `check-boundaries.sh` reads the phase out of the *committed*
  frontmatter, so a commit made while the story still says `phase: GATES` is
  one CI rejects — intermittently, depending on when that job runs, which is
  worse than always.

- **A return to RED ends with pasted red, not with a note saying it went red.**
  A corrected test runs for the first time against code that already satisfies
  it, so it passes immediately and forever; the Test Developer earns it by
  mutating the specific behaviour it pins, watching that assertion fail,
  reverting, and pasting the output into `## Regressions`. `check-boundaries.sh`
  refuses the PR otherwise. GREEN on re-entry may legitimately be a no-op you
  verify yourself rather than delegate.
- **GREEN confirms the negative-control values RED recorded**, not just that
  the control tests pass. RED could not run them: its suite failed at import.
- **A claim that the contract is wrong is reproduced before it is accepted.**
  When a subagent reports that an acceptance criterion, a threshold or a frozen
  test is wrong, verify it yourself on different inputs, without reusing the
  subagent's code, and record the reproduction in the story. Running unattended
  is exactly when this gets skipped, and it is the difference between a correct
  escalation and a plausible excuse for not failing.
- **A mutation table in the handoff is a claim until you run one.** When RED
  says the suite discriminates, run **one** mutation it predicts a count for —
  the one whose predicted catch is a single assertion — with
  `bash scripts/mutate.sh <file> '<expression>' -- <test command>`, against the
  one suite that holds that assertion. It restores the file and verifies the
  restore; compare the count and confirm green. Unattended is when this gets
  skipped too, and when a hand-rolled `sed -i` leaves a mutation in the tree.
  That one run, the story's deferred verifications and nothing more is the
  budget (`rules.md`, "Mutation work per story"); the rest of the table, and
  every assertion that passed on arrival, is `/audit-mutations`' work, which
  this loop never starts.
- **A required gate that reports `BLOCKED` (exit 3) is one of the reasons to
  stop and ask.** The environment would not let it start, so it has no verdict;
  do not retry it on a hunch, and do not treat it as a code defect. The path —
  a PO decision recorded in the story, REVIEW with the gate *pending CI*, DONE
  only once the PR's CI log for it is quoted — is in `/advance-story`.
- **PLANNED → RED pins the `## Contract` and lists the callers of every changed
  signature.** RED cannot find those callers itself: the old signature still
  exists during RED, so they still compile and never appear in its typecheck.
- **PLANNED → RED names the required gate that would fail if the artifact
  broke.** If only an optional gate can, `required_gates` gets it before the
  phase moves. Every required gate once passed over a story none of them had
  exercised.

Stop and ask the user only when:

- an acceptance criterion is ambiguous and the readings lead to different code;
- a required gate fails in a way that needs a product decision, or reports
  `BLOCKED` for anything other than a tool you can install;
- the epic's done-when needs something no story so far delivers, so this story
  has to close the gap;
- the tests turn out to be wrong, so the story must return to RED;
- the story is bigger than one cycle and needs splitting;
- something outside the story is broken and fixing it would exceed this scope.

Never resolve one of those by guessing in order to keep the loop running.

Between phases, state in one line which phase you are entering and why the
previous one is genuinely complete — with the command output that proves it, not
an assertion that it passed.

At the end, report: the PR link, every acceptance criterion with the test that
covers it, the full gate summary, anything you deliberately left out, and what
to run next: the output of `bash scripts/plan.sh after $1`, relayed as printed.
The story is at REVIEW by then, so it appears under `In flight:`. Report as
`rules.md`, "Reporting to the user" says.
