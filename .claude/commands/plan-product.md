---
description: Turn the product brief into a stack, an architecture and a backlog
argument-hint: [optional focus or constraint]
---

Delegate to the **lead-po** subagent, consulting the **lead-designer** subagent
for anything user-facing. Extra guidance from the user: $ARGUMENTS

Read `docs/wiki/product-brief.md` first. If it does not exist, stop and tell the
user to run `/create-product`.

This command is **idempotent**. If the artefacts already exist, diff against
them: keep what still holds, revise what the brief has changed, add what is new,
and mark superseded stories rather than silently deleting them.

Produce, in this order:

1. **`docs/wiki/stack.md`** — the chosen languages, frameworks, libraries and
   tools, each with a pinned version and one sentence of justification tied to a
   constraint in the brief. Load the `stack-profiles` skill; use an existing
   profile where one fits, and write a new profile file when the stack is one
   the harness has not seen. Name the test runner, the coverage tool, the
   linter, the type checker and the build command explicitly — these become the
   gates, with an `evidence` regex each (see the `quality-gates` skill).

   **Open this file with a header declaring its epistemic status**, because
   nothing in it has been run yet:

   > **Unverified.** Nothing in this file has been executed. Every version and
   > every command below is researched, not verified. The bootstrap story must
   > run each gate command, observe it fail on purpose, correct anything that
   > has moved, and update both this file and `.claude/harness/project.conf`.

   Say it plainly rather than implying it. The next agent starts with an empty
   context and will otherwise treat a plausible command line as a working one —
   which is how a wrong gate command survives to story 30 instead of story 1.

2. **`docs/wiki/architecture.md`** — components and their responsibilities, the
   data model in outline, how the pieces talk to each other, where state lives,
   and the deployment shape. Record decisions with their alternatives and why
   they lost. Keep it at the altitude where it stays true for months.

3. **`docs/wiki/design/`** — via the Lead Designer, for any product with a user
   interface: the token set, the component inventory, and the accessibility
   floor. Skip for headless projects.

4. **`docs/backlog/epics/*.md`** — coherent slices of user value, ordered.

5. **`docs/backlog/stories/*.md`** — via `bash scripts/new-story.sh`. Load the
   `story-authoring` skill for format and sizing. The **first** story is always
   a `bootstrap` story that turns this repository into the chosen stack's real
   layout and fills in every gate command in `.claude/harness/project.conf`.
   After that, a walking skeleton, then features in dependency order.

Then update `.claude/harness/paths.conf` so its `test` and `config` sections
describe the chosen stack, and print the ordered story list with the one you
recommend starting on.

Do not write any source or test files here. Planning only.

Finally, tell the user to run `/setup-environment` before starting the bootstrap
story. Planning chooses a toolchain; it does not install one, and the bootstrap
story cannot pass its gates on a machine that does not have it.
