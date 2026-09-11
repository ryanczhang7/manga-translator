# Audit template

Copy this into `docs/wiki/audits/<scope>-<date>.md`. Delete this heading and the
italic guidance as you fill it in; keep the section headings.

The structure exists to keep two things apart that a reader will otherwise merge:
**what was decided**, which a later story is told not to reopen, and **what was
measured**, which that story may well be depending on and must be free to check.

That distinction is not theoretical. An audit here recommended an approach and
backed it with a claim that two implementations produced bit-identical output.
The recommendation was sound. The claim was measured on three seeds that
happened to get lucky, and the underlying assumption - that a quantity rounds to
exactly zero - fails for 58% of inputs. The story that consumed the audit was
told "follow its recommendation; do not re-litigate it", read that as covering
the numbers too, and came within one careful agent of productionising the bug.

---

## Scope

*What was audited, at which commit, and what was deliberately left out.*

## Decided

*The conclusions. This section is SETTLED: a story that cites this audit follows
it and does not reopen it. Keep it to decisions - "use X, not Y", "the boundary
belongs here" - and keep the reasoning short enough that someone can tell what
the decision actually was.*

*If a decision depends on a measurement below, say which. A decision resting on
evidence that later fails is not settled any more, and the link is what lets
anyone notice.*

## Evidence

*What was measured, on what inputs, with what tool, and how it could be wrong.
This section is NOT settled. A story depending on a number here verifies it
first - that is not re-litigating the decision, it is using the evidence as
intended.*

*For each claim:*

- *the claim, stated so it could be false*
- *the inputs it was measured on, named exactly - "three seeds: 1, 7, 42", not
  "several seeds"*
- *the tool and the command*
- *what would make it unrepresentative*

## What would have to be true for this to be wrong

*The assumptions the recommendation rests on, stated plainly. Floating-point
behaviour, input distributions, a library version, an ordering guarantee, the
absence of concurrency. One line each.*

## What was not checked

*The gaps. Cases skipped for time, platforms not tried, scales not reached,
properties assumed rather than tested. An audit that claims to have checked
everything has not been read carefully enough by its author.*

## Spike code

*Required if this audit was produced from throwaway code that a later story is
expected to draw on. State plainly:*

- *where it is, and that it is **unreviewed and not production code***
- *what a later story may take from it - the algorithm, the shape, the
  constants - and what it must re-derive*
- *anything known to be wrong in it that survived because the spike did not care*

*"The spike directory is throwaway" and "reuse its algorithm" are a mixed
message if they sit in different paragraphs. Put them in the same one.*

## Stories filed

*One line each: id, title, and the finding it comes from.*
