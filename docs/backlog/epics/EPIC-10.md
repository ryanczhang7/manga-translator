---
id: EPIC-10
title: Regions that are not dialogue - the watermark left out, and the user's say over any region
status: todo
stories: [MT-117, MT-118, MT-119, MT-120, MT-121]
---

*Added 2026-10-28 by lead-po on Claude Fable 5.1, from the user's report on a
page of their sample chapter in the review workspace: region 1 was the
scanlation watermark ("RawLazy.Com", top-left, on art), numbered and given a
translation line like dialogue, its box clipping the first and last letters.
User: "the first box doesnt include the entire text, and that text should be
removed honestly." They asked for (a) detected watermark regions to be left out
of translation and cleaning and (b) a way to remove any region from a page in
the workspace. The product decisions this epic rests on are recorded as PO-1
to PO-6 below; the ones still the user's are Q-1 to Q-4.*

## Goal

A region the detector found that is not dialogue - the scanlation watermark
first, and anything else the user says is not text to translate - gets no
translation line, costs no tokens, and is left alone on the page; the user can
make that call per region in the workspace and take it back, and the
automatic rule for watermarks rests on a measurement rather than on four
boxes looked at once.

## Why now

The watermark is on three of the five sample pages (MT-007 A-4) and on the
user's chapter; every one costs a model call's worth of tokens for text nobody
wants translated and ends up as a numbered line the user must skip past. The
gap has been known since MT-007 (`## Notes` 10: *"MT-011 will OCR and
translate them unless something filters them. Worth a story; not this one"*),
and nothing downstream reads `region.kind` today (grep: only the store, the
bench truth format and the column merge touch it). The user has now hit it.

## Decisions (the Lead PO's, 2026-10-28, open to the user)

- **PO-1 - One mechanism, two writers.** A region carries an exclusion -
  `region.excluded`, `NULL` (included), `'watermark'` (the detector's rule) or
  `'user'` (the workspace) - and the automatic rule and the user's action both
  write that one column. Every consumer honours the flag, not the `kind`.
- **PO-2 - OCR still runs on an excluded region.** It is local and free, and
  a line row with `source_ja` is what lets a restored region be reviewed and
  hand-translated without a per-page re-run path, which the app does not have
  (EPIC-09 "Deliberately not"). Only translation, cleaning, typesetting and
  the review listing honour the flag.
- **PO-3 - An excluded region keeps its reading index and its ordinal.** The
  badge numbers on the art and the rows stay stable when a region is removed
  or restored; the model is handed a contiguous re-numbered listing and the
  stage maps the answer back. Nothing about the link (`components.md` §4)
  changes.
- **PO-4 - The automatic rule waits for a measurement.** `kind == "box"`
  (class 0) was established as "the watermark" on four boxes across five pages
  (MT-007 A-4). Whether a narration box or a caption also comes out class 0 is
  not known, and an automatic drop of narration is a silent loss of real text.
  MT-117 measures it under a decision rule written before the measurement;
  MT-121 ships the rule the audit decides, and only once the workspace can
  restore a wrongly excluded region (MT-120), which is the safety net the
  risk needs.
- **PO-5 - "Removed" means left as drawn.** An excluded region is not
  inpainted and nothing is typeset over it (MT-119). The safer reading of
  "remove": inpainting a false positive damages art, and a user who removes a
  region is saying "this is not text to translate", not "erase this". **Q-1
  below** - the user's words could mean erased.
- **PO-6 - Not sending the region to the model is in scope**, in the first
  mechanism story (MT-118): an exclusion that still spent tokens on the
  watermark would miss half the point.

## Open questions for the user

- **Q-1 - ANSWERED 2026-10-28 by the user: left as drawn.** *"leave it as
  drawn, but file a followup issue for v2 that does remove external
  watermarks (external as in not associated with the manga or its artist or
  publisher)"*. PO-5 stands; MT-119 stays. The v2 follow-up is
  `docs/backlog/parked/MT-122.md`, parked out of v1 and outside this epic's
  `stories:` list. The clipped watermark box is out of v1 scope and recorded
  there. Original question: excluded = left as drawn on the page, or erased
  (inpainted) and left untranslated? If erased: MT-119 is closed unneeded (the
  pipeline as left by MT-118 already inpaints and typesets nothing there),
  and the clipped box the user noticed becomes a real defect - the erase would
  leave the first and last letters standing - so a story on the box geometry
  is cut then.
- **Q-2** - The automatic rule waits for MT-117 (PO-4, assumed) or ships now
  on `kind == "box"` behind the restore action? Waiting costs one local
  measurement and no API spend.
- **Q-3** - MT-117 needs pages: the five spike pages are on the development
  machine (`spikes/MT-002/pages`, gitignored); the user's sample chapter and
  the benchmark chapter are the user's to point the spike at, as MT-101 Q-1.
- **Q-4** - The action is labelled **Remove** / **Restore**, bound to
  `Ctrl+E`, and shown on every row; the Lead Designer confirms the label, the
  key and the excluded-state hues (MT-120 `## Design notes`). The user may
  prefer "Ignore".

## Done when

On the user's sample chapter, the watermark regions carry no translation line,
no tokens were spent on them, and their pixels are untouched in the output; in
the workspace the user can remove any region from translation and restore it,
by pointer and by keyboard, with the change surviving a reopen; and
`docs/wiki/audits/MT-117-class-zero-regions.md` records what class 0 is on
every page it was measured on, with the rule MT-121 implements in its
`## Decided`.

## Stories

- **MT-117** (spike) - what class 0 is, measured on every available page
  under a decision rule written first. No code; `## Decided` names the
  predicate MT-121 implements, or says there is none.
- **MT-118** - the mechanism: `region.excluded` persisted (schema v8), set
  and cleared through the store, and honoured by the translate stage - an
  excluded region is not listed, not sent, gets no proposal, and a page whose
  included regions are all empty makes no call.
- **MT-119** - the pixels: an excluded region is outside the erase mask and
  the bake area, so it is neither inpainted nor typeset. Depends on MT-118;
  closed unneeded if Q-1 goes "erased".
- **MT-120** - the workspace: a Remove / Restore action on every row and on
  the canvas, keyboard-reachable, announced, the excluded row and marker
  states, the counts that leave removed regions out. Depends on MT-118.
- **MT-121** - the automatic rule: the detect stage stores the regions the
  audit's predicate matches as `excluded = 'watermark'`. Depends on MT-117,
  MT-118 and MT-120.

## Deliberately not in this epic

The detector's box geometry (the clipped first and last letters) - the box is
MT-007's and an excluded region's box is never used, unless Q-1 goes "erased".
Re-running one page after a restore; the restored region is reviewed by hand
or by a chapter re-run. Multi-select, or removing every region of a page at
once. Erasing art-integrated sound effects - still the brief's firmest
non-goal. Any change to `kind`, to the detector, to its classes or to the
bench truth format, which carries `kind` and not the exclusion. Carrying a
user's exclusion across a re-detection: `write_regions` writes what the new
detection carries, as it does for every other column.
