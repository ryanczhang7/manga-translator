---
id: EPIC-04
title: Translating with the page in view, under a hard budget
status: todo
stories: [MT-011, MT-012, MT-013, MT-044, MT-014, MT-038]
---

## Goal

The ordered Japanese utterances become proposed English lines, produced by a
cloud LLM that can see the page art alongside the text — so pronouns, speaker
attribution, honorifics and continuity across bubbles are decided with the
picture in view, which is the entire reason the brief chose a cloud LLM over a
local translation model. And every call is priced, recorded, and refused when it
would take the chapter past $2.

## Why now

This is the axis the product competes on. The brief's word was *accurate*, and
the headline success metric (S1 — 80% of the chapter's **ground-truth** text
regions carrying a line accepted with no edit) is measured against exactly what
this epic produces, together with what EPIC-03 feeds it. It comes after EPIC-03 because it
consumes ordered regions, and before the review screen because the review screen
exists to inspect its output.

## Done when

A page's regions go in with the page image and come back as proposed English
lines; the ledger shows input, output, cache-read and cache-write tokens and a
dollar figure per call; a run stops before crossing the configured ceiling and
keeps the pages it already paid for; and a character named on page 3 is still
called the same thing on page 17.

## Done when it is *not* done: the cost estimate is unverified

`docs/wiki/stack.md` §5/O4 puts the chosen design at $1.14 per 20-page chapter
against a $2.00 ceiling, and `docs/wiki/cost-model.awk` shows that a plausible
adaptive-thinking volume (3,200 tokens per page) crosses it. **MT-038** must
therefore *record* the measured mean output tokens per page, and MT-013 is what
makes a wrong estimate safe rather than expensive. An epic that reports "cost
looks fine" without a measured number has not finished.

*Amended 2026-09-18 by the user (MT-011 PO-1):* this measurement was MT-011's
AC-8 and is now **MT-038**, a story of its own. MT-011 has no credential on the
development machine and no CI job that could ever discharge it — the `network`
marker never runs on CI — so leaving it there meant one criterion in a
seven-criterion story whose only available outcome was a waiver, in exactly the
place this section says a waiver is unacceptable.

*Amended 2026-09-21 by the user (MT-013 PO-1):* **MT-013 is split.** Its
criteria described the budget arithmetic *and* the run-level behaviour that
makes it bite, which is two RED→GREEN cycles. MT-013 keeps the arithmetic;
**MT-044** takes the seam — wiring `TranslateStage` into `build_stages`,
recording every call into the ledger, and the abort itself. The epic's
budget clause — *"a run stops before crossing the configured ceiling and keeps
the pages it already paid for"* — is delivered by **MT-044**, not MT-013.
This matters because the seam had already been deferred twice: MT-011 shipped
`TranslateStage` wired to nothing and named MT-013 as the wiring story, and
MT-012 shipped `record_call` with no production caller. With nothing writing
ledger rows, `chapter_total()` is permanently $0 and MT-013's guard is inert
however correct its arithmetic. Filing MT-044 is what stops that being a third
silent deferral.

## Stories

- **MT-011** — one call per page: prompt assembly, the capped page image, the
  regions, the response parsed back onto region ids.
- **MT-012** — the ledger: `response.usage` priced from a pinned rate table and
  written append-only.
- **MT-013** — the guard: the budget arithmetic, as a pure domain module —
  the projection, the comparison against the ceiling, and the basis it reports.
- **MT-044** — the seam: the translate stage in the running pipeline, every
  call priced into the ledger, and a projected overrun aborting the run
  **before** the call is made.
- **MT-014** — continuity: a running glossary of names, honorifics and place
  names carried across pages.
- **MT-038** — the measurement: one real call, `response.usage` recorded, and
  the cost model re-run against it rather than against its own assumptions.

## Deliberately not in this epic

No editing surface — that is EPIC-05. No retry-on-disagreement or second-opinion
pass: `architecture.md` D5 shows two passes per page at $2.29, over the ceiling,
so a second pass is a change to a stated constraint and goes back to the user.
No language pair but Japanese to English.
