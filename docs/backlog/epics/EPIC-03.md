---
id: EPIC-03
title: Reading the page — what is text, in what order, and what does it say
status: todo
stories: [MT-007, MT-008, MT-009, MT-010]
---

## Goal

The machine can look at a page scan and produce an ordered list of Japanese
utterances, each tied to a pixel mask on the art. That is the input the whole
rest of the product consumes: the translator needs the text and the order, the
cleaner needs the mask, the typesetter needs the polygon, and the review screen
needs the region↔line correspondence that makes the bubble link possible.

## Why now

Brief feature 2, and half of feature 3. Nothing downstream can start without it,
and the brief's second success metric (S2, "every text-bearing bubble is found")
attaches directly to it. It comes after the spine because it is the first stage
to plug into it, and after MT-002 because the spike decides which runtime these
stories are written against.

## Done when

Given a page scan, the pipeline produces regions with masks, with furigana
folded into their parent utterance rather than standing as phantom bubbles, in
right-to-left top-to-bottom reading order, each carrying transcribed vertical
Japanese. On the fixture pages, every text-bearing bubble is found and no ruby
column appears as a region of its own.

## Stories

- **MT-007** — text-region detection: page image in, masked regions out.
- **MT-008** — furigana: a thin ruby column adjacent to a main column is merged
  into it, and two genuinely separate small bubbles are not.
- **MT-009** — reading order: right-to-left, top-to-bottom, band-swept, as a
  pure function on geometry.
- **MT-010** — OCR: vertical Japanese in a region crop becomes text, without a
  deskew step that would break it.

## Deliberately not in this epic

**Sound effects drawn into the art are never detected, never erased, never
listed.** That is the brief's first and firmest non-goal, and it is a property
of what MT-007 is allowed to emit, not a filter applied later. Panel
segmentation is also out (`architecture.md` D10): v1 orders regions by geometry
and leans on the LLM seeing the page to recover from an imperfect order.
Translation is EPIC-04.
