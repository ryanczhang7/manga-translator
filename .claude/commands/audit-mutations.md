---
description: Audit whether the tests actually verify behaviour (optional, above the bar)
argument-hint: [path or module to audit]
---

Delegate to the **mutation-tester** subagent.

Scope: $ARGUMENTS (default: the code touched by the most recently completed
stories)

Full coverage is already required by this harness. This asks the harder
question: if the production code were subtly wrong, would any test notice?

Have the Mutation Tester run the configured `mutation` gate if there is one, and
otherwise reason through the mutants by hand for the scope's most load-bearing
functions. It should write `docs/wiki/audits/<scope>-<date>.md` and file a story
per cluster of surviving mutants.

Do not fix anything here. Findings become stories; stories go through the normal
RED→GREEN cycle. Report the survivors ranked by production impact, and the
stories filed.

Write the audit to the structure in `docs/wiki/audits/TEMPLATE.md`. The
`## Decided` / `## Evidence` split is the part that matters: a later story is
told to follow an audit's recommendation without re-litigating it, and the
natural reading of that extends to its numbers. It should not. Record what was
measured, on exactly which inputs, and how it could be wrong — separately from
the conclusion, so a story consuming it can verify the one while accepting the
other. Fill in `## What was not checked` honestly; that section is the audit's
only defence against being trusted further than it earned.
