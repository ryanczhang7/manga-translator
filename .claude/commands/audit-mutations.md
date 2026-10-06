---
description: Audit whether the tests actually verify behaviour (optional, above the bar)
argument-hint: [path or module to audit]
---

Delegate to the **mutation-tester** subagent.

Scope: $ARGUMENTS (default: the code touched by the most recently completed
stories). An epic id scopes it to the paths that epic's stories touched.

Full coverage is already required by this harness. This asks the harder
question: if the production code were subtly wrong, would any test notice?

**When it runs.** Only on request: when the user types it, or accepts the
recommendation `/advance-story` makes at REVIEW → DONE when a story closes the
last open story of its epic. Nothing in the story loop runs it. It is where the
mutation work lives that `rules.md`, "Mutation work per story", keeps out of
every story.

Have the Mutation Tester run `bash scripts/gates.sh --gate mutation` where the
`mutation` gate is configured — it is marked `ondemand`, so no full run executes
it and `--gate` is the way to ask — and otherwise reason through the mutants by
hand for the scope's most load-bearing functions. For the stories in scope it
also owns what the per-story budget leaves out: earning, one mutation each, the
assertions that passed on arrival, and verifying the mutation tables their
handoffs claimed. It should write `docs/wiki/audits/<scope>-<date>.md` and file
a story per cluster of surviving mutants.

Do not fix anything here. Findings become stories; stories go through the normal
RED→GREEN cycle.

Write the audit to the structure in `docs/wiki/audits/TEMPLATE.md`. The
`## Decided` / `## Evidence` split is the part that matters: a later story is
told to follow an audit's recommendation without re-litigating it, and the
natural reading of that extends to its numbers. It should not. Record what was
measured, on exactly which inputs, and how it could be wrong — separately from
the conclusion, so a story consuming it can verify the one while accepting the
other. Fill in `## What was not checked` honestly; that section is the audit's
only defence against being trusted further than it earned.

Report as `rules.md`, "Reporting to the user" says: the survivors ranked by
production impact, the stories filed, and last, what to run next from
`bash scripts/plan.sh after`.
