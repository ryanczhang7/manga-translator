---
description: Add a single story to the backlog without re-planning the product
argument-hint: "<description of the feature, bug or chore>"
---

Delegate to the **lead-po** subagent.

Request: $ARGUMENTS

Use this for work that arrives after planning: a new feature, a bug report, a
chore. Do not re-run product planning.

1. Read `docs/wiki/architecture.md` and the existing backlog for context and for
   the id scheme in use.
2. Decide the type: `feature`, `fix`, `chore`, or `spike`. A bug is a `fix`
   whose acceptance criteria **reproduce the bug** — the failing test that
   captures it becomes the permanent regression test.
3. Create it with `bash scripts/new-story.sh <ID> "<title>" [epic] [type]` and
   fill in the sections. Load the `story-authoring` skill for the format.
4. If it does not fit one RED→GREEN cycle, split it into several stories and say
   why.
5. Report the story id and the command to start it.

Most of the template's sections are filled in by later phases. Two are yours and
are easy to leave empty by default:

- `## Out of scope` — often the most valuable section in the file, because it is
  the only thing that tells the Feature Developer where to stop.
- `## Model guidance` — optional, but if a phase of this story is worth running
  on a different model, write it before that phase starts and give it a success
  condition that could come out either way. The verdict gets recorded when the
  phase ends; without one the choice becomes folklore.
