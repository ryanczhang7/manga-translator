---
description: Audit the code for security defects with Cloudflare's vendored security-audit skill (optional, on request)
model: fable
argument-hint: [path | subsystem | <ref>..<ref>]
---

Runs in the session that reads this file, not in a subagent: the skill's parent
launches hunters, critics and verifiers, and no subagent here can launch one.

Load `.claude/skills/security-audit/SKILL.md` in full audit mode and follow it.
The method lives in that directory, vendored unmodified and pinned by its
`UPSTREAM` file; this file carries only what the harness decides.

Scope: $ARGUMENTS - a repository path, a subsystem name (map it onto the
skill's coverage units and companion files), or `<ref>..<ref>` for the diff
between two refs. Empty means the whole repository.

Defaults: scope repo-wide; profile `quick`; budget 18 agent invocations (strict; set by HARNESS-043 DV-1 from a run that spent 16)

The user may ask for `standard` or `deep`, another scope or another budget.

**Setup.** Resolve the skill directory, the target (this repository's root),
the repo name and the source ref (commit, and whether the tree is dirty). Raw
output goes outside the repository, in the skill's default
`~/security-audit-skill/<repo>/run-<N>`. Write `profile`, `scope_paths` and
`budget` into `run-metadata.json` before any reconnaissance agent starts.

**Roles.** Map the skill's two delegated roles onto this platform:

- hunters, critics and verifiers: `subagent_type: general-purpose`, `model: opus`
- `research` agents: `subagent_type: Explore`, `model: opus`

**Honesty.** Three statements, each carried into the summary:

- this environment has no OS-enforced sandbox, so the skill executes no target code; every finding is source-traced and anything that needs execution stays `needs_validation`
- before Phase 4, run `command -v node` and then both validators. If `node` is absent, or a validator refuses with an error that is not a schema error, record `validators not run: <first line of its stderr, verbatim>` under `## Evidence` and continue. That is a normal outcome, never a failure, never silent.
- a run with no confirmed finding is reported as nothing found this run, never as "clean" or "secure"; a single run finds roughly half of what repeated runs find.

**When it runs.** Only when the user types it. It is never a gate, and nothing in the story loop runs it.

**Output.** After Phase 6, write one summary to
docs/wiki/audits/<scope>-<date>.md in the structure of
docs/wiki/audits/TEMPLATE.md - `<scope>` is `security` for a repo-wide run and
`security-<slug of the argument>` otherwise. `## Decided` holds the verdicts;
`## Evidence` the agents spent by phase, wall-clock, the validator status and
the resolved model of every dispatch by name; `## What was not checked` the
sandbox statement and what the profile, scope and budget left out. Then file
one `fix` story per confirmed finding or cluster with
`bash scripts/new-story.sh`. Fix nothing here: findings become stories, and
stories go through the normal RED→GREEN cycle.

Report as `rules.md`, "Reporting to the user" says: confirmed findings ranked
by impact, the stories filed, and last, what to run next from
`bash scripts/plan.sh after`.
