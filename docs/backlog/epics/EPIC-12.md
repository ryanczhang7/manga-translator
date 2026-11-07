---
id: EPIC-12
title: Signs and sound effects in English - a small label beside the art (v2, after the first release)
status: parked
release: v2
stories: []
---

*Added 2026-11-07 by lead-po on Claude Opus 5.5, from the user. **This is v2
work. It must not be started before the first release.** The user, 2026-11-07:
sign and sound-effect translation is for v2 and must not be done before the
first release.*

## How this epic is kept out of v1

Nothing in `scripts/` reads `docs/backlog/epics/` - `phase.sh` and `plan.sh`
read only `docs/backlog/stories/`, and `plan.sh after`'s epic check looks an
epic up by the `epic:` field of a story there. There is no release or
milestone field anywhere in the harness. So the guard is the absence of story
files, the same convention as `docs/backlog/parked/` (README, "Parked
stories"; first v2 follow-up MT-122):

- **`stories: []`, and no story is cut.** No file under
  `docs/backlog/stories/` names `epic: EPIC-12`, so no story of this epic can
  be on the board, in `plan.sh after`'s "Next:" or "Alongside:", or blocked.
  A `depends_on` on some "v1 shipped" marker was considered and rejected:
  there is no such story, inventing one would sit on the board as a fake
  blocker, and `phase.sh set --force` overrides `depends_on` anyway.
- **`status: parked` and `release: v2`** above are for the human reader. No
  script reads either, so they are a label, not the guard.
- **Story sketches below are unnumbered** on purpose: an id in this file that
  someone later creates under `stories/` would be startable at once.
- **Un-parking** is a `/plan-product` or `/plan-story` decision made after the
  first release ships: answer the open questions below, then cut stories into
  `docs/backlog/stories/` with ids and `touches:`, and list them in
  `stories:`. Until then nobody cuts a story from this file.

## The problem

v1 leaves text drawn into the artwork alone (`product-brief.md` §5, "No
art-integrated sound effects": not erased, not typeset, not listed). That
covers sound effects and signs painted into the scenery, and the detector
cooperates: its box head does not fire on them, though its `seg` mask covers
them (`stack.md`, detector row). The user reads English only, so:

- they cannot tell what a sign says - a hospital name, a door plate;
- they cannot tell what a sound effect means, nor how one would be translated.

## The reference practice

The official English edition of the benchmark manga, aligned page for page
with the Japanese (`D:\bench\all-en\pNNN.jpg` against `D:\bench\all-jp\`;
ブラックジャックによろしく 佐藤秀峰, free to reuse,
https://densho810.com/free/):

- **A sign, p029** (誠同病院): the art is untouched; a small typeset label
  "Seido Hospital" is added beside it.
- **Sound effects, p020:** a phone ring inside a balloon-like tail becomes
  "BRRRRING"; the big hand-drawn screams are left untranslated.

So a professional release labels beside the art and does **not erase**. That
sidesteps the reason §5 gives for the non-goal - cleaning art-integrated text
is the hardest thing in manga cleaning, and doing it badly is worse than not
doing it. A label adds pixels to the page; it never removes any.

## Goal (v2)

A reader who knows no Japanese can tell what each sign on the page says and
what each sound effect is, without the art being erased, and the lines the
app proposes for them can be reviewed like any other line. **The shape of
that - which kinds, how shown, how found - is the open questions below; the
goal does not pre-decide them.**

## What v1 already gives this work

Recorded so v2 planning does not rediscover it:

- **The page image is already in the translate call.** `translate/gemini.py`
  `build_request` sends the capped page JPEG (`page_prompt.prepare_page_image`,
  long edge at most 1568 px) with the region listing, per page. Asking the
  same call to also list signs and sound effects would cost output tokens,
  not a second image - but it changes the response schema, which every
  recorded translate fixture pins.
- **The batch path sends the same image** (`gemini_batch.py`); the volume
  calls and the chunked text-only calls in `gemini.py` send **no** image
  (docstrings at lines ~199 and ~239), so they cannot see art text.
- **The detector's `seg` mask covers sound effects** where its boxes do not.
  MT-019 inpaints `seg ∩ accepted boxes` precisely so the mask's SFX coverage
  is never erased; the same mask, unintersected, is a candidate finder.
- **The user's region actions exist** (EPIC-10: Remove / Restore). A v2
  "mark this as a sign" action would be a third.

## Story sketches (unnumbered - not to be cut before the first release)

Indicative only; the open questions decide which survive.

1. **Spike: can the page call find them?** On `D:\bench\all-jp` pages
   *outside* 3-58, ask the translate call to list art text (kind, rough
   position, gloss) and score it against a hand list. Local hand list, small
   API spend, measured number before any product story.
2. **Truth format carries art text without moving S1b** - see Q-4.
3. **Found art text is stored per page** beside the regions, never as a
   region (so S1b, the review row count and typesetting are unchanged).
4. **Review lists them**, with the gloss editable like a line.
5. **Bake draws a small label beside the art** (if Q-2 picks labels): a new
   layout rule for a box placed *next to* the source, not over it, in the
   shipped font at a smaller size. Lead Designer owns the look.

## Open questions for v2

None of these is asked now; they are v2's to answer before any story is cut.
Mirrored as **O7** in `product-brief.md`.

- **Q-1 - Signs only, or sound effects too?** A sign has a literal
  translation ("Seido Hospital"). A sound effect often wants a gloss - "ring",
  "drip" - rather than a transliteration, and the reference leaves the big
  screams alone entirely. Which kinds are in, and is a sound effect's line a
  gloss, an English onomatopoeia ("BRRRRING"), or both?
- **Q-2 - How are they shown?** A small label beside the art (the reference
  practice), a list in the review screen only, a translator's-note margin on
  the baked page, or redrawing the art (the §5 cleaning problem, back again).
  These can combine: a review list is needed for editing whichever is baked.
- **Q-3 - How are they found?** (a) The detector's `seg` mask minus accepted
  boxes - local and free, but it outlines blobs, not words, and does not
  read them; (b) Gemini listing them from the page image the translate call
  already sends - no extra image, a schema change; (c) the user marking them
  in review; or a combination (b proposes, c corrects).
- **Q-4 - How is it measured without breaking S1b comparability?** The
  ground-truth format (`src/mangatl/bench/truth.py`, `TRUTH_SCHEMA_VERSION = 1`,
  `_KINDS = ("bubble", "box")`) refuses any other `kind`, and S1b's
  denominator is the ground-truth region count. Adding a kind to the region
  list would change every past S1b. A separate list beside `regions` under
  schema version 2, read by its own metric, keeps S1b's number meaning what
  it meant - but the v1 benchmark truth deliberately **excludes** signs and
  SFX (brief O1), so the benchmark chapter needs a new, separate annotation,
  not an edit of its truth file.
- **Q-5 - Which pages?** Chapter 1 (`D:\bench\all-jp` pages 3-58) is the
  held-out benchmark (O1, MT-108). Any v2 spike or tuning measures on pages
  **outside** 3-58 (the folder has 209), and the measured v2 number, if one
  is wanted on the benchmark chapter, is taken once, after tuning, never
  during it.

## Done when (v2)

Decided at un-parking, from the answers above. At minimum: the user can read,
for each in-scope sign or sound effect on a page, an English line they can
edit; nothing is erased from the art; and S1b on the benchmark chapter is
computed exactly as before.

## Not in this epic

- Anything in v1. §5's non-goal stands for the first release.
- MT-108's chapter, ground truth or decision rule. This epic only names the
  constraint they place on it (Q-4, Q-5).
- External watermark removal - that is MT-122, parked under EPIC-10.
