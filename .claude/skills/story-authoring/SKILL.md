---
name: story-authoring
description: How to write epics and stories for this harness - sizing a story to one RED to GREEN cycle, phrasing acceptance criteria as testable behaviour, and choosing story types. Use when planning a product, adding a story to the backlog, or judging whether a story is ready to start.
---

# Writing epics and stories

## Create stories with the script

    bash scripts/new-story.sh WORLD-014 "Regions render with distinct biome colours" EPIC-03 feature

It writes the canonical file with the frontmatter the harness depends on. Do not
hand-roll story files; `scripts/check-boundaries.sh` validates the frontmatter
in CI and the hooks read it.

## Sizing

A story is one RED to GREEN cycle: one behaviour, testable in isolation,
typically a handful of files. Signs it is too big:

- the acceptance criteria describe two features joined by "and"
- you cannot name the tests before writing them
- it touches the data model, the API and the UI at once
- you would want to commit halfway through

Split by behaviour, not by layer. "Backend for regions" and "frontend for
regions" is a split that produces two stories neither of which can be
demonstrated. "Regions persist across reload" and "Regions render with distinct
colours" is a split that produces two demonstrable behaviours.

The rule above is framed around RED→GREEN. The bootstrap story runs under
SCAFFOLD instead, where nothing forces a test to exist, so over-sizing it is
both easier and more expensive: keep it to the toolchain and the gates, and
put every project-specific piece in a story of its own afterwards. See
`reference/bootstrap-story.md`, Sizing.

Order matters as well as size. `depends_on` in the frontmatter is enforced:
`phase.sh set` refuses to start a story while a dependency is not DONE. Use it
whenever a spike decides something a later story builds on.

## When the evidence lives in an optional gate

Before leaving PLANNED, read the acceptance criteria against the gate list. If
an AC can only be verified by a gate `project.conf` marks `optional` - a
browser-driven `integration` suite, most often - then `bash scripts/gates.sh`
can come back green with that criterion unverified, and nothing notices. Say so
in the frontmatter:

    required_gates: [integration]

That gate is then binding for this story and optional for every other. See the
`quality-gates` skill.

Do this for every story, not only the obviously browser-bound ones: **name,
before RED, the required gate that would fail if the story's artifact broke.**
If the answer is "none" or "an optional one", this is the moment to fix it. The
trap is not one wrong decision but three right ones adding up: a test project
that needs a real browser (correct - jsdom has no WebGL, and testing a renderer
there is theatre), an `integration` gate marked `optional` because it needs
that browser (correct), a coverage `include` that skips the same directory
(correct). Together they put all twenty-five tests of a renderer where nothing
could block on them, and `All required gates passed` was printed over a story
whose artifact no required gate had exercised. `optional` means "this
gate reports information"; it must never be the only thing testing a shipped
feature. `gates.sh` checks this on every run once `project.conf` carries
`covers` lines saying which paths each gate reads (see `quality-gates`), and
fails a run whose changed source is read only by optional gates - but it
checks at GREEN, when the source exists, and the fix is a story decision best
made here.

## Brief RED by oracle

Not every criterion is the same kind of claim, and a Test Developer told "you
have no oracle, design the metric" across *all* of them will re-derive values a
design decision already fixed - the audit problem arriving from the other
direction. Before RED, sort the criteria and say which is which:

| Kind | Instruction to RED |
|---|---|
| **Settled** - a design doc, an audit's `## Decided`, a validated constant stands behind it | *Read the numbers out. Do not derive, tune or "calibrate" them.* |
| **Oracle-free** - perceptual, statistical, "reads as continents" | *Invent the metric, and demand a negative control that fires hard.* |
| **Mechanical** - an API shape, an event, instrumentation | *Precision beats invention; pin it exactly, leave nothing open-ended.* |

This partition is the part of a RED brief that has been measured to matter.
Two stories ran RED with it, one on a stronger model and one on the default,
with the default-model claim written down first so it could come out either
way. The default-model run produced the sharper controls - 69x separation
against 10x - and a second control for a criterion whose first metric could be
defeated by per-triangle flat shading. One run each, so the honest reading is
"the brief did the work, not the model"; and the brief is the cheap variable.
Put the partition in the story, under `## Model guidance` or beside the
criteria, so that the orchestrator's dispatch prompt carries it.

## Pin the whole contract before RED, and let RED amend it in place

The acceptance criteria say what must be true. They do not say what the modules
are called, what the exported signatures are, which way a drag moves the world,
where a value clamps, what the accessible markup is, or which measurements the
story is entitled to treat as settled. RED will decide every one of those by
writing a test against it, and GREEN will then either build that shape or build a
different one. "RED tested one shape and GREEN built another" is a named failure
of this loop, and the fix is cheap: write the shape down first.

So give the story a `## Contract` section, owned by the PO before RED, holding
whatever of these the story touches:

- **Module paths and exported names**, exactly.
- **Exact signatures**, including the types the assertions will destructure.
- **The semantics behind each number.** Not `clamp(latitude)` but "latitude
  clamps at ±85°, and dragging *down* brings the north into view". One sentence
  per number is what settles a sign error in one line instead of an argument.
- **The accessible markup** for anything user-facing: roles, labels, what is a
  sibling of what.
- **The oracle partition** of the criteria (above).
- **Baseline measurements** the story may read out rather than re-derive, each
  with what it was measured on.

And one standing rule, in the section itself: **RED may amend any block, in
place, with a reason** - and GREEN then builds what the amended block says. That
is not a loophole, it is where the value showed up. A story that pinned eight
such blocks produced 326 tests and a GREEN with no shape drift, and RED amended
seventeen of them - two of which were real design traps that GREEN would have hit
late and expensively (pointer capture on a map region swallows clicks on any
button inside it, so the overlay chips must be siblings; a plain container
re-uploads a graticule on every move, 17,280 bytes per ten frames measured, while
a render group uploads nothing).

The `## Contract` is not the acceptance criteria and does not inherit their
freeze. Criteria are frozen once the story leaves PLANNED and change only through
`## Amendments`; the contract is a working agreement RED is expected to sharpen.

### A changed signature must list its callers

The one gap RED cannot see for itself. When the contract changes the signature of
an **existing** export, the PO greps every caller - source *and* test - and lists
them in the story before dispatch, and RED's handoff states the list was checked
against the tree. It is one `rg` per changed export.

Why it has to be the PO's job: a story changed `equirectangular(width, height)`
to `equirectangular(viewport, extent, camera?)` and listed the test files RED had
to rewrite, missing one from an earlier story. RED's typecheck reported 221
errors, all correctly attributed to the not-yet-built contract, and the missed
file was **not among them** - it still compiled, because the old signature still
existed. GREEN deleted the old signature, that file stopped collecting, and its
25 tests - the only verification of a change GREEN had just made - became 25
silent skips. Running the gates at the end of RED would not have caught it:
every gate was green. A caller of a changed signature is invisible to RED
precisely because RED does not change the signature.

## When the story depends on an audit or a spike

A story that follows an earlier audit says so, and says it precisely. "Read the
audit before starting and follow its recommendation; do not re-litigate it" is
the right instruction about the audit's `## Decided` section and the wrong one
about its `## Evidence`. Spell out both halves:

- the **decision** is settled - name it, and say the story implements it;
- the **evidence** is not - name any number the story is about to depend on
  (a threshold, a tolerance, a claim that two things agree) and say that it is
  to be verified, not assumed.

This is not pedantry. An audit here recommended an approach and supported it
with a claim of bit-identical output measured on three lucky seeds; the
underlying assumption fails for 58% of inputs. The recommendation was fine. A
story that had trusted the number would have shipped the bug.

The same goes for spike code. If a story is expected to draw on a throwaway
spike, say what it may take - the algorithm, the shape - and what it must
re-derive, in one sentence rather than two paragraphs apart. Spike code is
unreviewed by definition; "throwaway" and "reuse its algorithm" cancel out if
the story does not resolve them.

## Acceptance criteria

Each one is a behaviour observable from outside the code, phrased so that a test
either passes or fails against it. Number them AC-1, AC-2 - the Test Developer
cites them and the PR body maps tests to them.

Good:

- **AC-1** - Given a world with three regions, when the map is rendered, then
  each region is filled with the colour registered for its biome.
- **AC-2** - Given a region whose biome is unknown, when the map is rendered,
  then it is filled with the neutral placeholder colour and a warning names the
  region.

Not criteria:

- "The map looks good." Not observable.
- "Refactor the renderer." No behaviour; that is a chore.
- "Use a quadtree." An implementation choice - if it matters it belongs in the
  architecture doc, and if it does not, let the Feature Developer choose.

Performance and accessibility criteria are welcome, with numbers: "renders a
10,000-tile world in under 100ms on the reference machine", "every control is
reachable by keyboard in visual order".

### A criterion that names a measurement names a control too

When an AC names a **statistic, a metric or a threshold**, it must arrive with a
**negative control**: a deliberately broken input the metric is required to
reject, and roughly what it should score. If you cannot name one, the criterion
is not ready to leave PLANNED.

Two different questions hide here, and only the first is usually asked:

- *Is 25% the right threshold?* — a control on the **number**.
- *Is variance the right quantity?* — a control on the **choice of metric**,
  one level up. This is the one that had a wrong answer.

An AC read as: "height **variance** in a polar band and an equatorial band of
equal area are within 25% of each other — no smearing at the poles". Impeccably
testable, reviewed, approved, and blind. Variance is a **one-point** statistic,
and the marginal distribution of a stationary noise field does not change when
the domain is stretched; "smearing" is a **two-point** property, about how fast
the field varies with distance. Measured on 400,000 points, the AC's own metric
separated a correct field from the exact defect it names by **9%**, against a
25% threshold — which side of the line you land on is decided by sampling noise.
The two-point statistic that replaced it separated them by **10x**.

Every agent downstream would have implemented that faithfully, and the test
would have passed on broken code.

So write the control into the story next to the criterion:

> **AC-5** — a polar band and an equal-area equatorial band have mean squared
> gradients within 25% of each other.
> *Control:* the same field sampled in the lon/lat plane instead of on the
> sphere — the defect this AC exists to catch — must fail this check by a wide
> margin (measured ~10x).

**A criterion that is precise, measurable and blind is more dangerous than a
vague one.** A vague criterion gets challenged in review; a blind one survives
review and produces a green tick over a broken implementation.

If the Test Developer reports that a criterion's metric cannot detect what the
criterion is about, that is an AC change: it stops, the product owner decides,
and the change is recorded under `## Amendments` — after the orchestrator has
reproduced the finding independently, on its own inputs.

### Name the control you cannot run yet, and the phase that owns it

Some controls cannot run when they are needed. A control for a codec, a
threshold or a round trip has to break the **real** implementation to mean
anything, and in RED the implementation is what the story is about to build.
There is nothing to mutate, and RED claiming otherwise is the failure mode this
whole section exists to prevent.

So write it into the story at PLANNED, in `## Deferred verifications`, as a
falsifiable condition with an owner:

> With one field dropped from the encoder, AC-1's round-trip property **must**
> fail, and the orchestrator watches it fail rather than taking the claim. RED
> cannot run this — there is no encoder to mutate. **Owner: GATES.**

Three things follow from that shape, and each was learned the expensive way:

- **RED declines it explicitly.** "I could not run this, and here is why" in the
  handoff is honest; a verification claimed and not done is not.
- **Prefer GATES to RED as the owner.** Source is writable there, so the
  mutation needs no special permission — and a story that bounced back to RED
  mid-cycle gets its corrected assertions earned by the *same* experiment, which
  is the cheapest way there is to satisfy `tdd-cycle`'s corrective-RED rule.
- **Do three mutations, and make one a wrong value rather than a missing
  field.** Two dropped-field mutations of one codec were each caught only by the
  property test; the one that flipped a float writer's byte order was caught by
  six tests, and only because the container assertions read bytes through an
  independent reader. A suite that catches an omission can be blind to a
  corruption.

`check-boundaries.sh` refuses a PR whose `## Deferred verifications` names no
phase, or that reaches REVIEW with neither a pasted result nor an explicit
`WAIVED` and a reason. That is deliberate: the pattern worked the first time
because an orchestrator had written the promise into its own report twice, and
prose does not fail a build.

### A round trip proves the application self-consistent, not the file sufficient

"Encode it, decode it, assert you got the same thing back" is the most natural
criterion for any persistence story, and by every rule above it is impeccable:
observable, falsifiable, one line. It is also satisfied by an implementation that
**never reads part of what it wrote**, as long as it can reconstruct that part by
other means — and for a format whose promise is longevity those are very
different guarantees.

A codec story's round-trip property passed while the decoder never read the
largest entry in the file. It size-checked the entry, discarded the result, and
regenerated the data from a seed. The values survived because the generator is
deterministic, not because the bytes were read. Three consequences, none visible
from the criteria:

- **The durability guarantee moved.** The product promise was "worlds open years
  later"; as built, that rests on a mesh builder staying bit-identical forever,
  which is far stronger and more fragile than "the bytes are on disk". The
  implementer knew and wrote it at the call site. No criterion had asked.
- **A documented limit came out backwards.** The wiki note said those values
  "round-trip at float32 precision" — true of the test's comparison, false of the
  system, which loses nothing today because it regenerates. The loss is *latent*:
  it springs the day a reader actually parses those bytes.
- **The mutation control does not catch it.** Corrupting the writer is caught, on
  the write side. Deleting the *read* is caught by nothing, because there is no
  read.

So when a criterion is a round trip, a restore or a reload, it must also say
**which stored artifacts the read path consumes**. An entry written but not read
is a legitimate design — for future readers, for other tools, for a migration —
and it must be *declared*, together with the invariant standing in for reading
it, in the architecture document rather than only in a source comment. Where the
mechanism is the point, phrase the criterion over the mechanism: *"decoding a
container whose `mesh/params.json` has been removed fails"* is a test; *"the
world round-trips"* is not, for this purpose.

This is the same family as the blind metric above, with a different blindness.
That one is a statistic that cannot move when its subject breaks; this one is a
criterion whose subject is *broader* than the thing it was written to guarantee.

## Types

| Type | When | Phase path |
|---|---|---|
| `feature` | new behaviour | PLANNED, RED, GREEN, GATES, REVIEW, DONE |
| `fix` | a bug; criteria reproduce it | same - the failing test becomes the regression test |
| `chore` | tooling or migrations with no behaviour change | may use SCAFFOLD |
| `bootstrap` | turns the repo into the chosen stack | SCAFFOLD, GATES, REVIEW, DONE |
| `spike` | a timeboxed investigation; output is a document | PLANNED, REVIEW, DONE |

A bug is never fixed without a test that reproduces it first. That test is the
whole value of the fix.

## More

- `reference/sections.md` - what belongs in each section of a story file
- `reference/bootstrap-story.md` - how to write the first story of a project
- `reference/epics.md` - epic format and ordering
