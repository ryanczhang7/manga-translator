---
id: EPIC-06
title: Cleaning and typesetting — the pages come out looking like a release
status: todo
stories: [MT-019, MT-020, MT-021, MT-027]
---

## Goal

The Japanese disappears from inside the detected regions, the bubble interior is
reconstructed underneath, the edited English is fitted into the bubble in
standard scanlation lettering style, and the finished pages are written to the
sibling folder. The brief's bar: the baked page should look like a normal English
release, not like a machine's output.

## Why now

This is the half of the value that is pure grunt-work replacement — the hours of
erasing and fitting that the brief says dominate the manual workflow. It comes
after the review workspace because baking the wrong English beautifully is worse
than useless, and because the review screen is what decides the strings this epic
renders.

## Done when

A reviewed chapter bakes to a sibling folder of pages with no surviving Japanese
pixels inside any cleaned region, English centred in each bubble with sensible
line breaks at a size that fits, and nothing outside a detected region touched
anywhere on the page.

## Stories

- **MT-019** — inpainting: erase within the mask, reconstruct the interior
  including screentone and hatching.
- **MT-020** — typesetting: real glyph metrics, line breaking, fitting into the
  region polygon, italic and bold for emphasis.
- **MT-021** — bake and export: atomic per-page writes to `<input>_en/`, same
  filenames, same order.
- **MT-027** — the app-wide lettering-font override, and what happens when the
  configured font is missing, unparseable, or short of the glyphs and styles
  comic lettering needs. Last in the epic because it records its fallback on
  MT-021's `BakeReport`.

## Deliberately not in this epic

**Art-integrated sound effects.** Nothing outside a detected bubble region is
ever modified — not erased, not typeset, not listed. The brief calls this the
hardest thing in manga cleaning and says doing it badly is worse than not doing
it. Also out: any overlay or layered output format; the output is baked pixels.

**Per-bubble font or size control** stays a non-goal. The user's 2026-09-12
decision added *one app-wide* font override (MT-027) and nothing else; the brief
§5 now records that reading explicitly so the line does not move again by
accident.
