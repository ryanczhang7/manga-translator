# Path ownership

Each agent owns a slice of the tree. The phase lock enforces the *phase*
dimension of this automatically. The *role* dimension is honoured by the agents
themselves: nothing checks which agent wrote a file. What CI checks, in
`scripts/check-boundaries.sh`, is the commit - source arrives with tests or a
scaffold inventory, the phase and criteria in the committed story, the gate
record against the tree.

| Agent | Writes | Never writes |
|---|---|---|
| **Lead PO** | `docs/wiki/**`, `docs/backlog/**`, `.claude/harness/project.conf` | any source or test file |
| **Test Developer** | test paths (see `paths.conf`), the story's `## Test plan`, `## Handoff` and `## Regressions` | production source, config |
| **Feature Developer** | source and config paths, the story's `## Gate probes` (`## Gate results` is written by `gates.sh`, by nobody else) | any test file |
| **Lead Designer** | `docs/wiki/design/**`, the story's `## Design notes` | source, tests, config |
| **Mutation Tester** | `docs/wiki/audits/**`, new story files | source, tests, config |

**The bootstrap exception.** A `bootstrap` story - and a `chore` that uses
SCAFFOLD - is one indivisible derivation: the test runner, the configuration,
the scaffold and the gate commands all depend on each other, and none of them
can be written test-first before the others exist. So the Lead PO drives it and
writes source, tests and config directly, under SCAFFOLD. That is the only time
the Lead PO writes outside docs and `project.conf`, and it is not free: every
production file written must be named in the story's `## Scaffold inventory`,
with the test that covers it, and `check-boundaries.sh` refuses the PR if a
changed source file is missing from that list. A table that quietly contradicts
the command that invokes it teaches agents the table is advisory; this
paragraph is here so that it does not.

**`.gitignore` has no single owner.** It classifies as `harness`, so the lock
permits it in every phase, and that is deliberate: whoever introduces a tool
that writes into the tree adds the line for its output, in the phase they
discover it - the Test Developer in RED for a test runner's scratch directory,
the Feature Developer in GREEN for a build artefact, the Lead PO during
bootstrap. Ignoring *generated* output is never a phase violation, and it now
has a second effect: `git check-ignore` is what makes the phase lock classify a
path as `ignored` rather than `source`. Every other edit to it - ignoring
something authored, a secret, or a committed artefact - belongs to the Lead PO.

**Portability.** Harness scripts, hooks and skill examples stay in bash, awk and
coreutils. Do not reach for python: on Windows a bare `python` hits the
Microsoft Store alias shim and exits 49 without running anything, so a script
that depends on it fails on a machine where python is genuinely installed.
Node is available only once a stack has chosen it, which the harness cannot
assume.

Categories are decided by `.claude/harness/paths.conf`, not by intuition. To see
how a path is classified:

```bash
bash -c '. .claude/hooks/lib.sh; classify "src/app/main.ts"'
```

# The model each agent runs on

Every definition in `.claude/agents/` declares `model:`, so which model a role
runs on is a fact of the harness rather than of whoever's session dispatched it.
All five say `opus` today, and that is a decision rather than a default: the one
place model choice has been measured against a controlled alternative, the
*brief* out-performed the model - a partitioned RED brief on the weaker model
produced sharper negative controls than the stronger model without it - while the
failure mode of a weaker model in GREEN or GATES is precisely the one this
harness exists to prevent, reaching green by weakening a test.

Lower it deliberately, per role, and record the decision and the outcome. What
you may not do is leave it unstated: a session setting or an explicit override
can still win, and the orchestrator cannot see which did. Two stories once
compared "the default model" against a stronger one, and neither could say what
"default" had resolved to - so the comparison may have been the stronger model
against itself. Hence the other half of the rule: **`lead-po` records the
resolved model of every dispatch, by name, in the story.**

# Phase permissions

| Phase | May write | Meaning |
|---|---|---|
| any | vendor, ignored | installed dependencies, build output, and anything the project's `.gitignore` covers — generated, not authored |
| `PLANNED` | docs, harness | story is being written |
| `RED` | test, docs, harness | failing tests only; source frozen |
| `GREEN` | source, config, docs, harness | make them pass; tests frozen |
| `GATES` | source, config, docs, harness | fix lint/type/build; tests frozen |
| `REVIEW` | docs, harness | PR is open |
| `SCAFFOLD` | everything | bootstrap/chore stories only; every source file named in `## Scaffold inventory` |
| `DONE` | docs, harness | closed |

No active story means no restrictions. The lock protects a cycle in flight; it
is not a general permission system.

**A gate failure whose only legal fix is a write the current phase forbids is a
return to RED, not a reason to route around the lock.** The return is usually
described as "a test is wrong", and that is only the common case. The general
one is this table: GREEN and GATES both freeze test files, and a `format` or
`lint` gate can fail on a test file the story itself added - a one-line reflow to
satisfy a line-width rule, with the assertion entirely correct. GATES is the
phase whose stated job is fixing lint and build failures, and it is the phase
that cannot fix that one. Set the phase back to RED, make the single change,
record why in `## Regressions`, and come back. Do not document a whitespace
failure as an expected WARN, and do not reach for a tool the lock does not
inspect.

# Non-negotiables

- A test that has never been observed to fail is not a test. Run it in RED and
  record the failure output in the story's `## Handoff`.
- **That is a property of the assertion, not of the phase or the run.** An
  ordinary RED satisfies it as a side effect - the implementation does not
  exist, so everything is red. Two situations look identical from outside and
  satisfy nothing:
  - a test **written or corrected while the implementation already exists** -
    on a return to RED, or against a module an earlier story built. It passes
    on its first execution and passes forever; it could assert nothing at all
    and nothing would notice. Earn it by mutating the specific production
    behaviour it claims to pin, watching that one assertion go red, reverting,
    and pasting the output into `## Regressions`. One mutation, one run, one
    revert — and the mutation goes through `bash scripts/mutate.sh FILE 'EXPR'
    -- COMMAND`, which is allowed in every phase because it restores the file
    and verifies the restore. `sed -i` here is working around the lock.
  - a suite that fails at **import**, where no assertion in the file has run.
    Negative controls - the cases that make a threshold mean something - are
    unverified for the whole of RED. Record each control's expected value in
    the handoff and have GREEN confirm the measured one.
  `check-boundaries.sh` refuses a PR whose `## Regressions` or `## Gate probes`
  describes a failure without showing one.
- A gate that has never been observed to fail is not a gate. When a story adds
  or changes one, break what it guards, watch it fail, and record that in the
  story's `## Gate probes`. Exit 0 means only that the tool did not complain,
  and a tool with nothing to do does not complain.
- Do not weaken an assertion, add a `skip`, widen a tolerance, or delete a case
  to reach green. Any of these means going back to RED. The same applies to a
  gate: do not delete an `evidence` line, drop `--workspace`, or add
  `--passWithNoTests` to make a gate stop complaining.
- **Narrowing an input domain can be correct; loosening a comparison is always a
  weakening.** In a property test the input lives in a generator, not in the
  assertion, so a fifth move exists that is none of the four above: change what
  is generated. A generator is part of the *specification* - it is the domain the
  criterion claims to hold over - and narrowing it is legitimate exactly when the
  design cannot represent what was excluded, named against the document that
  fixes that. "The test was failing" is not a reason. The two moves are one line
  each and look identical in a diff: a round-trip property failing on a negative
  zero is fixed either by keeping `-0` out of the coordinate generator (correct -
  JSON cannot carry it) or by making the comparison treat `-0` and `0` as equal
  (which stops it distinguishing values for **every number in the document**, and
  is easier, because it is a one-line edit in the file the failure is reported
  in). So a narrowing carries three things: the design clause that excludes the
  value, the limit recorded in the architecture document rather than only in a
  comment, and a mutation showing the property still fails against a lossy
  implementation. `tdd-cycle` has the worked case.
- Acceptance criteria are frozen once a story leaves PLANNED, for the same
  reason tests are frozen during GREEN: they are what the tests are for. If one
  is wrong or unsatisfiable, stop, put it to the product owner, and record the
  change under `## Amendments` - which AC, what it said, what it says now, who
  approved it and why. `check-boundaries.sh` fails a PR whose criteria differ
  from the base branch without an entry there.
- `## Gate results` is written by `scripts/gates.sh`, never by hand. It carries
  the commit and a hash of the code the gates ran against, and
  `check-boundaries.sh` refuses a PR where that hash does not match the code
  being merged. A pasted summary is not evidence of anything.
- `depends_on` and `branch` in a story's frontmatter are enforced by
  `phase.sh set`, which refuses to move a story past PLANNED while a dependency
  is not DONE or the checkout is on the wrong branch. `--force` overrides
  either, and prints that it did; record why in `## Notes`.
- Do not commit `.claude/state/**`. It is machine-local: `current-story.env` from
  `phase.sh`, `last-gate-run` and `gate-logs/` from `gates.sh`,
  `mutations/` (backups and a log) from `mutate.sh`, and the guard's
  `phase-guard-declined.log`. Two of those are denied to `Write`, `Edit` and
  `MultiEdit` in `settings.json` because their contents are read as evidence - the
  phase and the gate stamp - and `.claude/state/README.md` says which, in a column
  `.claude/tests/settings.test.sh` checks against the rules in both directions. A
  new state file belongs in that table, with a yes or no, or the suite fails. A
  `.bak` left behind under `mutations/` means a
  restore failed and `mutate.sh` exited 90 saying so; everything else it cleans
  up. The backup path is explicit rather than `$TMPDIR` because that variable is
  unset in some of the shells this harness runs in, and a mutation whose backup
  went nowhere once left its restore depending on the `sed` expression happening
  to be an exact inverse of a single-occurrence match.
- Agentic scaffolding (`.claude/`, `docs/`, `scripts/`, `.github/`) never ships
  in a production image. Keep `.dockerignore` honest.
