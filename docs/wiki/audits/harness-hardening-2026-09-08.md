# Audit: seven hardening findings from the first real bootstrap

**Date:** 2026-09-08
**Scope:** `scripts/{gates,check-boundaries,phase,new-story}.sh`,
`.claude/hooks/lib.sh`, `rules.md`, `phases.conf`, the agent and command
definitions, CI.
**Origin:** `fantasy-world-builder` WORLD-001, the first real project on this
harness - a 15-criteria, ~90-file bootstrap story. Companion to
`gate-liveness-2026-09-08.md`. Reported as a proposal; this file records what
was found, what was decided, and where the decisions depart from the proposal.

## What was found

Four things actually happened during that story, and three were confirmed by
reading the code:

1. **The role table forbade the work the story required.** `/complete-story`
   says "act as the lead-po", and `rules.md` said the Lead PO never writes
   source or tests. The bootstrap story writes ~90 of them. The agent did it
   anyway because the phase lock permitted it, and learned that the role table
   is advisory.
2. **SCAFFOLD had no discipline.** The one story every other story's
   correctness depends on was the one exempt from "no code without a failing
   test". The agent wrote 17 real tests; nothing required it to, and a lazier
   pass would have scaffolded the same files with none and every gate green.
3. **Acceptance criteria were editable in every phase.** `docs` is writable
   always and story files live in `docs/`. An agent in GATES could rewrite the
   criterion a failing gate was checking and nothing would notice - the exact
   move `rules.md` forbids for tests, one line away. The benign version was
   hit: an AC was unsatisfiable as written and the right move (stop, ask,
   record) and the wrong one (edit it quietly) were equally available.
4. **WARN had no signal-to-noise mechanism.** A permanently failing optional
   gate WARNs on every run forever; the next agent learns WARNs are ignorable,
   and the day `integration` regresses its WARN is buried.
5. **Gate results were agent-transcribed.** Law 3's "run it and paste the
   result" made the durable evidence a block of text an agent - one motivated
   to finish - copied into a file, unverifiable and indistinguishable from a
   fabricated one.
6. **`depends_on` was decoration.** Written by `new-story.sh`, read by nothing.
7. **Nothing checked the branch.** A story could be set active and committed
   to `main`. Related: `## Handoff` was described as mandatory and checked by
   nobody.

And one thing the brief did not find, found while implementing #5: **every
story check in `check-boundaries.sh` had been silently skipped in CI since day
one.** On a `pull_request` event `actions/checkout` produces a detached merge
commit, so `git rev-parse --abbrev-ref HEAD` returns `HEAD`, no story id is
derived, and the phase check the brief credited the script with never ran.

## What shipped

1. **The bootstrap exception, stated.** `rules.md` and `lead-po.md` now say the
   Lead PO writes source, tests and config for the bootstrap story alone, and
   why: it is one indivisible derivation. Option (a) of the three proposed.
2. **`## Scaffold inventory`.** Required when a story uses the
   source-without-tests exemption. `check-boundaries.sh` refuses the PR unless
   every changed source file is named in it. Whether the named test is
   adequate is a reviewer's call; that the file is accounted for is the
   script's.
3. **Criteria frozen after PLANNED.** `check-boundaries.sh` diffs the
   `## Acceptance criteria` section against the base branch and fails unless
   `## Amendments` has an entry. Law 6 in `CLAUDE.md`.
4. **`waiver` lines.** `waiver | <id> | <reason>` on an optional gate turns
   its failure into `KNOWN` with the reason inline; `WARN` is reserved for the
   undeclared. A waived gate still runs, and a pass says to remove the line.
   Waivers on required gates are refused.
5. **The gate record is tool-written.** A full `gates.sh` run writes its own
   block into the story: marker, UTC time, commit, a hash of every
   source/test/config/harness file as it was on disk, and the summary.
   `--gate`/`--required` runs are not recorded. `check-boundaries.sh` refuses a
   PR without the marker, without `result: pass`, or whose hash does not match
   the code being merged.
6. **`depends_on` enforced.** `phase.sh set` refuses to move a story past
   PLANNED while a dependency is not DONE.
7. **Branch enforced.** `phase.sh set` refuses when the checkout is not on the
   story's branch; `check-boundaries.sh` checks the frontmatter branch against
   the PR branch; and `## Handoff` must have content for feature and fix
   stories. Both `phase.sh` refusals take `--force`, which prints that it was
   used.
8. **CI story checks actually run.** The story is taken from `GITHUB_HEAD_REF`
   and the tree hash is recomputed at `PR_HEAD_SHA`, which the workflow now
   passes.
9. **Bootstrap sizing guidance** in the story-authoring skill: toolchain and
   gates on a walking skeleton, nothing project-specific.

## Decisions worth not relitigating

- **A tree hash, not "the SHA matches HEAD".** The proposal asked CI to check
  that the recorded SHA equals the PR head. That can never hold: the commit
  that contains the gate record is by construction made *after* the run. What
  can hold is that the *content the gates saw* equals the content being
  merged. So the record carries a hash over the blob ids of every source, test,
  config and harness file - taken from a temporary index so untracked files
  count and ignored ones do not, docs excluded so the story file can hold the
  hash, `.claude/state/` excluded. Blob ids are of LF-normalised content, so a
  Windows working tree and a Linux checkout agree; verified on this repository.
- **The hash is recomputed at the PR head commit in CI, not the checkout.** The
  checkout is a merge commit whose tree includes whatever moved on the base
  branch since; hashing it would false-fail every PR behind `main`.
- **Any AC difference from base needs an amendment, whatever phase it was made
  in.** The rule says "frozen after PLANNED", but CI sees a diff, not a
  timeline, and a story that refines its criteria in PLANNED and moves to
  REVIEW in one commit is indistinguishable from one that edited them in
  GATES. Recording a PLANNED-time refinement is cheap and honest, so the
  simpler, stricter rule wins. A story file that is new in the PR has nothing
  to be frozen against and is skipped.
- **Refuse, do not warn, in `phase.sh`.** The brief allowed either. The next
  agent starts with an empty context and trusts whatever state the script
  writes; a warning in a transcript it never sees is not a guard. `--force`
  exists and announces itself.
- **`waiver`, not `expect-warn`.** Consistent with `evidence` replacing
  `expect` in the previous audit, and it names what it is.
- **`--audit` inside `gates.sh`** rather than a separate script, as before.
- **One classifier pass.** The tree hash classifies every file in the tree.
  Spawning a process per rule per path, as the hook's per-path `classify` does,
  costs seconds on Windows even for a dozen paths; `classify_stdin` does the
  whole tree in one `awk`, verified to agree with `classify` on every case
  tried, including a bracketed filename.

## Not done, and why

- **`doctor.sh` reading the stack profile before bootstrap.** `/setup-environment`
  already reads `stack.md`, finds the profile, and works from its Prerequisites
  section; the gap the brief describes is the gap that command exists to fill.
  A second implementation of the same lookup in `doctor.sh` would be a second
  place for it to drift.
- **Option (c), a `bootstrapper` agent.** More agents is more surface for the
  same ownership question; the exception is one paragraph.
