# The handoff between phases

The Test Developer and the Feature Developer never share a context. Everything
that crosses between them crosses through the story file. Treat it as writing
for someone who has read nothing.

## Filling in `## Handoff: RED -> GREEN`

Five things, always, and a sixth whenever the story has a negative control:

**1. The exact command.** Copy-pasteable, taken from
`.claude/harness/project.conf`, not from memory. Include any filter that runs
only this story's tests.

**2. The verbatim failure output.** Not a summary of it. Indent it as a code
block. The next agent needs to recognise the same output when they run it.

**3. A table of what was written.** One row per test:

| Test | Asserts | Covers |
|---|---|---|
| `rejects a region whose borders do not close` | validation error naming the open edge | AC-2 |

**4. The export shape the tests already pin.** The highest-value block in the
whole handoff, and the one most often left out. The tests import specific
modules, names and signatures; the Feature Developer starts with an empty
context and would otherwise *guess* them, then discover the guess was wrong
one compile error at a time. Write them down, and say plainly that they are not
up for negotiation:

> Nothing below is a suggestion. Each name and signature is already imported by
> a test, so getting it wrong is a compile error rather than a debate.
>
>     src/render/facade.ts
>       export function createSurface(canvas: HTMLCanvasElement): Surface
>       export type Surface = { resize(w: number, h: number): void; dispose(): void }
>
>     src/render/errors.ts
>       export class ContextLostError extends Error

Include every module the tests import, the exact exported names, their
signatures, and any type the assertions destructure. Where the tests do *not*
constrain something - internal structure, algorithm, file layout below the
imported module - say that too: it is the Feature Developer's to choose, and
saying so prevents a different guess, that the handoff is an implementation
plan.

**5. Notes for the implementer.** Anything discovered that should change the
approach: a constraint in the architecture doc, an existing helper worth
reusing, an edge case the acceptance criteria did not anticipate, a place where
the criteria and the design notes disagree. Also flag any test that **passed on
arrival** - a regression guard for an earlier story's invariant - naming the
probe or negative control that earns it (see `red-phase.md`), so that a green
test is not mistaken for a forgotten one.

Also state, in one sentence, **why this is the right failure** - which assertion
is unsatisfied, and why that assertion is the behaviour the story asks for.

**6. The expected value of every negative control**, where the story has any.
A control is the case a metric must reject - white noise that must not read as
continents, a deliberately broken field a smoothness check has to catch - and it
is what makes a threshold mean anything. In RED none of them ran: the file
failed at import, so no assertion in it executed. Measure them outside the
framework and write the numbers down:

| Control | Threshold | Expected | Measured in RED |
|---|---|---|---|
| white noise | > 2 continents | 0-1 | 0.6 |
| single blob | > 2 continents | 1 | 1.0 |
| archipelago | continental share > 0.4 | well below | 0.11 |

Say plainly that confirming these against the shipped module is GREEN's job.
Until then they are a claim, and a control that measures the wrong thing makes
every threshold in the suite look calibrated while proving nothing.

## `## Gate results` is not yours to write

`bash scripts/gates.sh` writes that section itself on every full run, stamped
with the commit and a hash of the code it ran against. Do not paste a summary
into it and do not edit what it wrote: `check-boundaries.sh` refuses a PR whose
record was not written by the tool or does not match the code being merged.

Anything that needs saying *about* the run - an optional gate that failed and
why that is acceptable - goes in `## Notes`. If you cannot justify it there, it
is not acceptable.

## What not to write

- "The tests fail as expected." Which tests, with what output?
- "Implemented the feature." Which files, satisfying which criteria?
- "All good." The gates are the only thing entitled to that opinion.
