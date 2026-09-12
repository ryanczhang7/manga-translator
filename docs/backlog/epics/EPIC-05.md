---
id: EPIC-05
title: The review workspace — the one place a human can catch an error
status: todo
stories: [MT-025, MT-015, MT-016, MT-017, MT-018, MT-026, MT-028]
---

## Goal

The screen the brief describes in section 8: the page image large, the proposed
English lines docked beside it, each line unambiguously tied to a visible bubble
on the art, each editable, with per-page progress and the running cost in view
during a run. The user reads down the list, fixes what is wrong, and moves on.

## Why now

The brief calls the bubble-to-line link **the single most important interaction
in the product**, and gives the reason: the review screen is the only place a
human can catch an error, so an unclear link makes the review worthless. It
comes straight after translation because reviewing proposals is what makes
translation quality visible at all — and it comes *before* cleaning and
typesetting deliberately, so the accuracy loop (run, read, judge) closes as early
as possible, on the axis the product competes on.

## Done when

The user can open a chapter that has been translated, see the page large with its
bubbles marked, select a line and see exactly which bubble it belongs to (and the
reverse), edit a line, revert it, close the app, reopen it and find their edits;
and during a run they can see which page is being worked on and what has been
spent so far.

## Stories

Note the numbering: **MT-025 runs first**, out of numeric order. It was added
after the Lead Designer reported a constraint the plan had not anticipated — QSS
has no variables, so the token source must be *generated* into two artefacts,
one for chrome and one for the canvas markers that QSS cannot style. `depends_on`
in each story's frontmatter carries the real order.

- **MT-025** — chore: the token generator. `tokens.toml` → `theme.qss` +
  `tokens_gen.py`, with a gate that fails if the committed artefacts drift from
  the source.
- **MT-015** — the workspace shell: page canvas with pan and zoom, docked line
  column, page pager. Layout and tokens from `docs/wiki/design/`.
- **MT-016** — the bubble-to-line link: selection both ways, hover, off-screen
  handling, overlapping bubbles, keyboard and screen-reader conveyance.
- **MT-017** — editing: edit, dirty state, revert to proposal, persistence across
  reopen, and the unedited-versus-accepted distinction.
- **MT-018** — run progress and the running cost readout, including its
  near-ceiling and aborted states.
- **MT-026** — Windows High Contrast, part one: token resolution. Pure functions
  over a token name, a boolean and a plain dict — no Qt, no display.
- **MT-028** — Windows High Contrast, part two: the widgets and the scene
  actually use it, and a live toggle loses no uncommitted work.

The last two exist because the user decided on 2026-09-12 that a contrast theme
is **supported**, not detected and declined. The split is at the seam between
*what colour a token is* and *that the screen uses it* — the same seam as MT-025
against MT-015/MT-016. The Lead PO and the Lead Designer reached it
independently.

## Deliberately not in this epic

Everything the brief's non-goals forbid, and they bite hardest here: no dragging
or resizing typeset boxes, no per-bubble font or size control, no manual
line-break control. If auto-placement is wrong, the human fixes it in their image
editor. No reader or viewer — this screen is for judging translations, not for
reading the chapter.
