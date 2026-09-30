---
id: EPIC-05
title: The review workspace — the one place a human can catch an error
status: todo
stories: [MT-025, MT-015, MT-048, MT-016, MT-049, MT-050, MT-051, MT-052, MT-017, MT-054, MT-055, MT-056, MT-018, MT-057, MT-058, MT-059, MT-060, MT-026, MT-028]
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
- **MT-048** — the 1440 px breakpoint, split out of MT-015 (its PO-1).
- **MT-016** — the bubble-to-line link: selection both ways, hover, off-screen
  handling, overlapping bubbles, keyboard and screen-reader conveyance.
- **MT-049** — fix: hover clears when the pointer leaves the canvas (§4.4). MT-016's
  GREEN phase recorded this gap.
- **MT-050** — `Up`/`Down`/`Home`/`End` on the canvas move the selection (§4.7), and
  never scroll the view on their own (MT-016 PO-5).
- **MT-051** — ordinal badges never overlap: slide clockwise, then fall back to the
  centroid (§4.2). The placement is a pure function with a hand-computed oracle.
  Blocked on two design questions (Q2 and Q3 in the story).
- **MT-052** — the `OffscreenIndicator` and `Ctrl+9` (§4.6; MT-016 PO-3 and PO-5).
  Blocked on the zoom meaning of `Ctrl+9` and of the indicator click (Q1), and on the
  page-edge reading (Q4).

MT-049 to MT-052 are MT-016's deferred follow-ups, split four ways because each has a
different oracle: a hover-state fix, key → selection transitions, a geometric
placement algorithm, and a new accessible widget with a zoom rule. MT-052 depends on
MT-049, because the indicator is a child widget of the viewport and entering it sends
the viewport the `Leave` that MT-049 handles.
- **MT-017** — editing: edit, dirty state, revert to proposal, persistence across
  reopen, and the unedited-versus-accepted distinction.
- **MT-054** — the app opens a chapter in the review workspace (`mangatl <folder>`).
  Filed at MT-017 PO-1: the done-when's first verb, "open a chapter", had no story.
- **MT-055** — the no-argument window asks for a folder: the `FolderDropTarget`
  (components.md §2) as a keyboard-focusable button and a folder dialog. A picked
  folder behaves exactly as `mangatl <folder>`: the `Workspace`, or the
  no-project text naming `mangatl-run`. Filed at MT-054 PO-5 — a double-clicked
  installed app (MT-024) has no argument, so without it no chapter can be opened.
- **MT-056** — dropping a folder onto that target, with its hover-valid and
  hover-invalid states. Split from MT-055 (its PO-2) at the seam between the two
  input mechanisms; the design makes drag never the only path, so MT-055 is
  complete without it.
- **MT-057** — a chosen folder of pages with no project shows its
  `ChapterSummary` (name, page count, first and last page, the filename-order
  warning, the intake errors) and writes nothing. It replaces MT-055's interim
  "run `mangatl-run`" outcome, and MT-054's command-line notice with it:
  `mangatl <folder>` and the picker share one resolution (MT-057 PO-3).
- **MT-058** — the summary's `CostEstimate` against the budget, including the
  over-budget state and the >200-page warning.
- **MT-059** — "Start run": creates the project, runs the pipeline on a worker
  thread feeding MT-018's panel, and opens the review workspace when the run
  finishes. `mangatl.app` becomes the third composition root, exempted from the
  anthropic and onnxruntime import contracts (MT-059 PO-3), and the story owns
  the worker thread `architecture.md` §6 describes, which MT-018 had attributed
  to MT-015.
- **MT-060** — MT-017's real-time save-bound test holds on CI hardware. Filed
  2026-09-30 from a CI failure on MT-056's PR (860 ms against a 750 ms bound on
  the runner, 0.53 s locally); its Q1 decides what the test should measure.

MT-057 to MT-059 were filed on 2026-09-30 at the user's request (MT-055 Q2):
after MT-055 a double-clicked app could open a chapter already translated, but
could not translate one. Their open questions were answered by the user on
2026-09-30 (each story records its decisions); the Lead Designer is asked to
amend `components.md` §2 to match (MT-057 PO-4 and PO-5, MT-058 PO-1).

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
