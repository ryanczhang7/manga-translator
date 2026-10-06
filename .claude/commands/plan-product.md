---
description: Turn the product brief into a stack, an architecture and a backlog
model: fable
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

   **Cut for parallel work as well as for size.** Fill `touches:` for every
   story as you cut it. This is the only point at which the planner can still
   change the answer. The Contract comes later, after the backlog is cut.

   - **Granularity.** List the repository-relative files the story will
     WRITE, not the files it reads. Paths are compared as literal text, so a
     glob collides only with the same glob, spelled the same way.
     `src/core/*` and `src/core/world.ts` are reported clear of each other.
     Use a glob only for a family of sibling files the story edits as a set.
   - **"Some of `src/core/`, not sure which."** Do not declare the directory
     as a hedge. List every file it might plausibly write. Over-declaring
     costs some parallelism, and under-declaring costs a merge conflict found
     after both stories went green, so over-declaring is the safer error. If
     you cannot even list candidates, the story is not ready to be cut: make it
     a spike, or cut further. Leave it `touches: []` until then. `waves`
     reports it as UNKNOWN and places it nowhere, which is correct.
   - **Prefer footprints that partition.** Choose the decomposition in which
     stories that could run side by side share no file. A backlog where every
     story writes the same file is a queue, however it is drawn.
   - **Two stories that must share a file are one story or two waves.**
     Prefer two waves when each is its own behaviour. Merging would break the
     one-cycle size limit, and the collision only costs time. Prefer one story
     when both would change the same part of the file, such as the same
     function or table. Then they are one behaviour cut in two, and running
     them in parallel would conflict on every line. Merge only if the result
     still fits one RED to GREEN cycle. The `story-authoring` skill, Sizing,
     has the reasoning.
   - **`depends_on` is for true ordering only.** Use it when B needs what A
     decides or builds. Collision now has its own expression, `touches:`, so
     do not chain two stories only because they would collide. That makes the
     backlog look more sequential than it is and hides which chains are real.

   Check the cut with `bash scripts/plan.sh waves`. It groups the startable
   stories into waves in which every pair is clear, and lists BLOCKED and
   UNKNOWN stories separately. The grouping is greedy first fit, so it is not
   guaranteed to use the fewest waves. If everything lands in one wave, check
   that the declarations are real. If most stories need their own wave, the
   footprints do not partition: re-cut before accepting that the backlog is a
   queue. `bash scripts/plan.sh conflicts` names the shared path for each
   colliding pair.

Then update `.claude/harness/paths.conf` so its `test` and `config` sections
describe the chosen stack, and print the ordered story list with the one you
recommend starting on.

Do not write any source or test files here. Planning only.

Finally, tell the user to run `/setup-environment` before starting the bootstrap
story. Planning chooses a toolchain; it does not install one, and the bootstrap
story cannot pass its gates on a machine that does not have it. Report as
`rules.md`, "Reporting to the user" says.
