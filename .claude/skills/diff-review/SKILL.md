---
name: diff-review
description: How to review a story's whole diff, and the code connected to it, for bugs no test was written for - before the PR opens. Every finding carries a concrete case, a severity group and a four-part explanation, and the report ends in a verdict that decides whether GATES → REVIEW goes on. Use at the first step of GATES → REVIEW, as a fresh feature-developer dispatch.
---

# Diff review

The gates judge the code through things that execute: tests, lint, coverage,
the commit's shape. None of them reads the code. A green suite cannot see a
defect nobody wrote a test for - a caller broken by a changed return value, a
fix made in one caller while the shared function stays wrong, an error
swallowed on a write path. This review is the step that reads.

Review the change like the person who will be paged when it breaks. In order
of importance: correct, safe, holds at the load the repository states, tested,
fast, lean.

## Who runs it

A **fresh** `feature-developer` dispatch, not the one that wrote the code, on
the GATES row of `.claude/harness/models.conf`. A reviewer that carries the
author's reasoning repeats the author's blind spots, so it starts from the
story file and the diff, not from the author's notes on why the code is right.

The reviewer changes no file. Not the source, not the tests, not the story. It
returns its report to the orchestrator, which pastes it into a `## Diff review`
section of the story file under `docs/backlog/stories/`, directly above
`## Gate results`, and records the model that dispatch resolved to in
`## Model guidance`, by name, like any other.

## 1. Understand first

- Read the story: its acceptance criteria, `## Contract` and handoffs. They
  say what the change is for, and what it deliberately leaves out.
- Read the whole diff against the base branch: `git diff main...HEAD`, or the
  worktree's own base.
- Then read the code connected to it: the callers of every changed function,
  the functions it calls, and the tests that exercise it.
- A change can break code it does not touch. When a signature, a return value
  or a behaviour changes, grep every caller, and read each one.
- Trace the real flow: where data comes in, what is stored, what goes out.
- Find the load the repository states (the architecture page, the deploy
  configuration, the product brief) and judge scale against that. Say which
  load you assumed.

## 2. Look for

In this order.

1. **Bug.** A wrong result, a crash, a missed edge case (empty, zero, the last
   item, rounding, time zones), a caller broken by the change, a fix applied in
   one caller while the shared function stays wrong.
2. **Risk.** Security (injection, secrets, weak randomness, input from a user
   trusted unchecked) and data loss (an error swallowed, writes in the wrong
   order, a partial write left behind).
3. **Scale.** Fine for one user and wrong at the stated load: a check-then-write
   race, work every process repeats, a list that only grows, a query per item,
   quadratic work on large input.
4. **Missing test.** A behaviour or branch the change introduces or alters with
   no test that fails when it breaks. This is law 4 of `CLAUDE.md` read over the
   whole diff, not only over what the story claims: coverage of lines is the
   floor, and the question is whether breaking the behaviour turns a test red.
   Name the behaviour and the input that would break it unnoticed.
5. **Speed.** A real slowdown is a finding. A small win in a hot loop is a
   suggestion.
6. **Lean.** Code that should not exist, or should be smaller: dead code, an
   option nobody sets, an abstraction with one implementation, near-copies that
   must change together. And code that already exists elsewhere - the helper
   the repository already has (name its path), the standard library or platform
   feature that does it, a dependency added for a few lines.

## 3. Check before reporting

Every finding needs a concrete case: "this input, or this situation, leads to
this wrong result".
No case, no finding.

- Re-read the lines and confirm it: the caller exists, the value really can be
  empty, the code really is unused, the error really is swallowed.
- Propose the smallest fix that works. Prefer one that deletes code. Never
  propose a layer, a framework or a setting the problem does not need.
- No style taste, no "consider", no vague worry. A frozen test you merely
  dislike is not a finding; a test that cannot fail is.

## 4. Output

Short sentences, everyday words. Explain a technical term the first time it
appears; the reader may never have seen this code.

Start with `What this change does:` in two or three sentences.

Then the findings, in three groups, skipping any group that is empty:

- **Must fix:** a bug, a security hole, data loss, or something that breaks at
  the stated load.
- **Should fix:** a behaviour with no test that fails when it breaks, a real
  slowdown, duplication, code that should not exist.
- **Nice to have:** a small speed-up, a shorter form.

Number findings across all groups, so the orchestrator can say "fix 2 and 5".
Every finding has all four parts, each one or two short sentences:

    2. **A refused write is reported as success** (`scripts/sync.sh:40-52`)
       - **What this is:** The step that copies the story's gate stamp into the branch.
       - **Problem:** It ignores the copy's exit status, so a full disk leaves an
         empty stamp and the script still prints `synced`.
       - **Fix:** Exit non-zero when the copy fails. One line; nothing else changes.
       - **If we skip it:** CI reads an empty stamp and refuses the PR, with nothing
         pointing at the cause.

End with exactly one verdict line, last:

- `Verdict: Ship.` when there is nothing to fix first, or
- `Verdict: fix 1 and 3 first.`, naming the findings that must be fixed.

Before it, add `Not checked:` and one line when something that mattered could
not be checked. With no findings at all: `What this change does:`, one line on
what you checked, then `Verdict: Ship.`.

## 5. What happens to a finding

The review changes no file, and a finding is fixed through the phase rules,
never around the phase lock.

- **A Must-fix in the code** is fixed in GATES, by a feature-developer
  dispatch. The tree has changed, so `bash scripts/gates.sh` runs again and
  the GATES → REVIEW steps start over, beginning with a review of the fix.
- **A finding that needs a test added or changed** is a return to RED:
  `bash scripts/phase.sh set <id> RED`, the Test Developer makes the change,
  and records why in `## Regressions`. A test written against code that already
  exists has to be earned by a mutation, as the non-negotiables in
  `.claude/harness/rules.md` require.
- **A finding that says an acceptance criterion is wrong** is an
  `## Amendments` question for the user. Nobody resolves it by editing the
  criterion.
- **A Should-fix the orchestrator declines** is recorded in `## Diff review`
  with a one-line reason, never dropped silently.
- **A Nice-to-have** is listed, and that is all.

GATES → REVIEW goes on only once the review's last line is `Verdict: Ship.`.

Adapted from ponytail-review, github.com/DietrichGebert/ponytail, MIT licence.
