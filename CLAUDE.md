# Agentic development harness

This repository builds software through a fixed loop driven by specialist
agents. Read this file as the standing rules of the house; it is in context on
every turn, so it stays short.

@.claude/harness/rules.md

## The loop

```
/create-product    → Lead PO interviews the user           → docs/wiki/product-brief.md
/plan-product      → Lead PO + Lead Designer plan          → docs/wiki/{stack,architecture}.md
                                                             docs/wiki/design/**
                                                             docs/backlog/{epics,stories}/*.md
/setup-environment → install the toolchain the stack needs → docs/wiki/environment.md
/advance-story ID  → one phase of the cycle
/complete-story ID → every phase, to done
/audit-mutations   → Mutation Tester (optional, above the bar)
```

A story moves `PLANNED → RED → GREEN → GATES → REVIEW → DONE`. One story is one
RED→GREEN cycle. If a story cannot be finished in one cycle, it is too big —
split it.

## The law

1. **No production code without a failing test that demanded it.** The test is
   written first, is watched to fail, and fails for the right reason. "Watched
   to fail" is a property of the *assertion*, not of the run; the
   non-negotiables in `rules.md` say how a test written against code that
   already exists earns it.
2. **Tests are frozen during GREEN.** If a test is wrong, go back to RED and say
   so in the story file under `## Regressions`. Never edit a test to make it
   pass.
3. **Done means the gates pass.** `bash scripts/gates.sh` — not "should pass",
   not "passes locally in principle". Run it; it records its own result in the
   story, stamped with the code it ran against, and CI refuses a PR where that
   record does not match the code being merged. Never paste a summary by hand.
4. **Full coverage of the behaviour the story claims.** Coverage of lines is the
   floor, not the goal; every acceptance criterion has a test that fails when
   that criterion is broken.
5. **Never work around the phase lock.** If the lock blocks a write you believe
   is correct, that is a signal to change phase deliberately or to reconsider —
   never to route around it with a different tool. The one mutation the law
   *requires* of a frozen file — earning a corrected test, checking that a suite
   discriminates — goes through `scripts/mutate.sh`, which restores the file and
   proves it did. `sed -i` on production source is working around the lock.
6. **Acceptance criteria are frozen once a story leaves PLANNED**, for the same
   reason tests are frozen during GREEN. If one is wrong, stop, put it to the
   user, and record the change under `## Amendments`. CI fails a PR whose
   criteria changed without one.

## Phase lock

`.claude/hooks/phase-guard.sh` refuses writes that violate the current phase. It
covers `Write`/`Edit`/`MultiEdit`/`NotebookEdit` and shell redirects alike. When
no story is active it is off entirely. Quoted arguments and heredoc bodies are
data, not syntax; relative paths resolve against the directory the command will
actually run in; a path held in a variable the command itself assigns is
resolved and judged, and one it cannot resolve is declined and logged rather
than waved through; and anything `.gitignore` covers is always writable. If it
still blocks a command that writes nothing, that is a bug in the guard: add the
case to `.claude/tests/phase-guard.test.sh` and fix it there, which is the one
form of "working around the lock" that is allowed.

```bash
bash scripts/phase.sh show                 # what is active, what may be written
bash scripts/phase.sh board                # every story at a glance
bash scripts/phase.sh set WORLD-014 GREEN  # the only supported way to change phase
```

## Where things live

| Path | Contents |
|---|---|
| `docs/wiki/` | product brief, stack, architecture, design decisions, audits |
| `docs/backlog/epics/` | epics |
| `docs/backlog/stories/` | stories — the unit of work, and the agent handoff medium |
| `.claude/harness/project.conf` | how to lint/test/build **this** project |
| `.claude/harness/paths.conf` | which paths count as test / source / config |
| `.claude/agents/`, `.claude/commands/`, `.claude/skills/` | the harness itself |

## Running things

Never guess a build command. Every project-specific command lives in
`.claude/harness/project.conf`:

```bash
bash scripts/doctor.sh           # is the toolchain installed?
bash scripts/selftest.sh         # the harness's own tests (bash + git only)
bash scripts/gates.sh            # all gates
bash scripts/gates.sh --fast     # every gate not marked `slow` — for RED and GREEN
bash scripts/gates.sh --gate unit
bash scripts/check-boundaries.sh # the other half of CI: the commit, not the code
bash scripts/ci-local.sh         # every step CI runs, in order, on this machine
bash scripts/task.sh dev         # run the app
bash scripts/mutate.sh F 'EXPR' -- CMD   # the only sanctioned diagnostic mutation
```

`mutate.sh` exists because the law below requires mutating production code in a
phase that freezes it. It backs the file up to an explicit path, applies a `sed`
expression, runs the command, restores the file, verifies the restore with `cmp`
and logs it — so it is allowed in every phase, and the phase lock knows it.
Anything else, `sed -i` included, is working around the lock (law 5).

`gates.sh` judges the **code**; `check-boundaries.sh` judges the **commit** —
the phase in the committed frontmatter, the acceptance criteria against the base
branch, whether the recorded gate run still matches the tree. CI runs both, so
"all gates pass" is not the same as "CI will pass". Run it after committing and
before opening the PR.

`ci-local.sh` runs the whole CI sequence — both of those plus `selftest.sh`,
`--list` and `--audit` — in order, stopping at the first failure as a runner
does. `.claude/tests/ci-local.test.sh` derives the expected step list *from the
workflow files*, so a step added to `.github/workflows/` and not to the script
fails the selftest; that test is the only thing making "the same sequence" a
fact rather than a claim. What it cannot replace: it is **one machine** — every
CI-only failure this file warns about is green here — it runs only when invoked,
so it cannot cover the diff no hook and no agent saw, and branch protection
cannot require it. Use it to know a PR will pass before opening one, never as
evidence that the PR's own checks did.

`--fast` exists because RED and GREEN otherwise only ever run the test command,
while the gates judge those tests with a slower one — the same suite under
coverage instrumentation. A suite can pass RED, pass GREEN, pass every local
gate and still fail a required gate on CI hardware. A gate is in `--fast` unless
a `slow` line in `project.conf` says otherwise, and a `--fast` run is never
recorded: it is not a full run.

If a command you need is not in `project.conf`, add it there rather than
memorising it — the next agent has a fresh context and will not know.

## Context discipline

Subagents start with empty context. Anything the next agent needs must be
written into the story file before the current phase ends — especially the
`## Handoff` section. "As discussed above" does not survive the boundary.
