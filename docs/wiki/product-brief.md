# Product brief — manga translator

*Written by `/create-product` on 2026-09-11, from an interview with the user.
Source of truth for scope. `/plan-product` reads this and produces the stack,
architecture and backlog.*

---

## Summary

A Windows desktop application that takes a folder of raw Japanese manga page
scans and produces a folder of the same pages with the Japanese speech-bubble
text erased and English typeset in its place, in standard scanlation lettering
style.

It is a **first-pass tool for people who typeset translated manga by hand
today**. The machine does detection, OCR, translation, cleaning and typesetting;
the human reviews the proposed English lines on one screen before the pages are
baked, and fixes whatever remains in an image editor afterwards. The bar is not
"publish-ready without a human" — it is "a human starting from this output
finishes a chapter in materially less time than starting from the raws".

The word the user led with is **accurate**. Translation quality, not throughput
and not feature count, is the axis this product competes on.

---

## 1. Problem

Someone who wants an English version of a Japanese chapter that has no English
release does the whole job by hand: read the Japanese, translate it, erase the
Japanese text from each bubble in an image editor, reconstruct the bubble
interior, choose a font, fit the English into the bubble shape, and repeat for
every bubble on every page. It is hours of work per chapter, and most of those
hours are mechanical — erasing and fitting text, not translating.

The *interesting* part of the work (getting the English right) is a small
fraction of the time spent. The rest is grunt work that a machine should do.

**What they do instead today:** the manual image-editor workflow above. The user
has not adopted an existing automated tool; they have no incumbent to match, and
no prior tool's behaviour constrains this design.

## 2. Users

**Primary and only user of v1: someone who produces translated manga pages and
currently typesets them by hand.** Concretely, for now, the user themself.

What they already know how to use:

- image editors (Photoshop or equivalent) — they will still finish pages there
- the file-and-folder model of a chapter: an ordered directory of page scans
- enough Japanese, or enough judgement, to tell a wrong translation from a right
  one when they see it side by side with the art

What they should *not* be assumed to know: machine-learning tooling, Python
environments, model weights, GPU configuration. Installation and setup must not
require any of that.

## 3. The first five minutes

1. Open the app. It asks for a folder of page images.
2. Point it at a chapter — say 20 `.png`/`.jpg` scans in reading order.
3. It works through the pages, showing each page as it goes with the bubbles it
   found marked on the art, and reports progress and running cost.
4. When it finishes, it shows the review screen: the page image large, with the
   proposed English lines listed beside it, each tied to its bubble. The user
   reads down the list, edits any line that is wrong, and moves to the next page.
5. They press render. It writes a sibling folder of baked English pages.
6. They open those in their image editor and fix what is left.

**What brings them back:** step 6 being short. The first run either saves them
an evening or it does not, and they will know within one chapter.

## 4. Core features (v1)

The smallest set that makes the above true:

1. **Chapter intake** — point at a folder of page images; pages are processed in
   filename order and the output preserves order and filenames.
2. **Bubble and text-region detection** — find the speech bubbles and text boxes
   on each page, and their reading order (right-to-left, top-to-bottom for
   Japanese).
3. **OCR + translation with page context** — read the Japanese and translate it
   to English using a cloud LLM that can see the page, so pronouns, speaker
   attribution, honorifics and continuity across bubbles are handled with the
   art and the surrounding lines in view.
4. **Review screen** — one screen per page: the page image, the proposed English
   lines beside it, each editable, each tied to a visible bubble. This is the
   only editing surface in v1.
5. **Cleaning (inpainting)** — erase the Japanese text from inside the detected
   regions and reconstruct the bubble interior underneath.
6. **Typesetting** — fit the edited English into each bubble in standard
   scanlation lettering style: comic body font, centred, sensible line breaks,
   sized to the bubble.
7. **Bake and export** — write the finished pages to a sibling output folder.
8. **Cost reporting** — show what the run cost, per chapter and running, so the
   $2/chapter constraint is observable rather than assumed.

Anything not on this list is not in v1.

## 5. Explicit non-goals for v1

- **No art-integrated sound effects.** Text drawn into the artwork outside
  bubbles is left completely untouched — not erased, not typeset, not listed.
  The human handles SFX in their editor. (This is the hardest thing in manga
  cleaning, and doing it badly is worse than not doing it.)
- **No typeset editing.** No dragging or resizing text boxes, no per-bubble font
  or size control, no manual line-break control. If auto-placement is wrong, the
  human fixes it in their image editor.

  *Scope reading, decided by the user on 2026-09-12 so it is not re-litigated:
  this non-goal forbids **per-bubble** font control. **One app-wide lettering
  font override is in scope** — the app ships with a default font and a user who
  owns another comic-lettering face can point a single setting at it. Everything
  else in this bullet stands: no per-bubble anything, no size control, no manual
  breaks.*
- **No languages other than Japanese → English.** No Korean, no Chinese, no
  target language other than English.
- **No formats other than a folder of images.** No CBZ, no PDF, no archive
  handling, no direct reading from manga sites.
- **No reader or viewer.** The output is image files; the app is not where you
  read the result.
- **No overlay mode.** Output is baked pixels, not a toggleable layer.
- **No publishing, uploading, or distribution features of any kind.**
- **Not macOS or Linux.** Windows only.

## 6. Constraints

| Constraint | Value | Notes |
|---|---|---|
| Platform | Windows 11 desktop, local | The user's machine is the target; no server to deploy |
| Hardware available | RTX 5070, Ryzen 5 7600X, 32 GB RAM | Local GPU work (detection, inpainting) is cheap and fast here — but see open question O3 |
| Translation engine | Cloud LLM with page context | Chosen for accuracy: the model sees the art and neighbouring lines |
| Cost ceiling | **Under $2 per ~20-page chapter** in API spend | Hard budget. Design must minimise calls and tokens per page, and the app must report actual spend |
| Data handling | Page images are sent to the LLM API | Accepted by the user. Detection and inpainting are local work regardless — they are not LLM tasks |
| Input | Folder of `.png`/`.jpg` page scans | |
| Output | Sibling folder, same order and filenames | |
| Installation | Must not require the user to manage Python environments, model weights or GPU setup by hand | |
| Deadline | None | |
| Source material | User-supplied scans; the tool ships with no content and fetches none | The product adds no acquisition or distribution path in either direction |

## 7. Success

v1 has worked if, on a held-out benchmark chapter that was not used while
building:

- **S1 — Translation accuracy: at least 80% of the benchmark chapter's text
  regions carry a line that is accepted as-is**, with no edit on the review
  screen. This is the headline number and the axis the product competes on. It
  requires a benchmark chapter and a recorded, repeatable measurement, not an
  impression.

  The denominator is **every text region in the chapter's hand-made ground-truth
  list**, not every line the tool happened to propose. A bubble the detector
  missed therefore counts against S1, because from the user's seat a missing
  translation and a wrong one cost the same. *(Decided by the user on
  2026-09-12, resolving open question O2; see the interview notes and
  `docs/wiki/stack.md` §5/O2 for the mechanical definition of "accepted as-is".
  The conditional number — accepted out of *proposed* — is still reported
  alongside it as a diagnostic, and the gap between the two is exactly the
  detector-versus-translator diagnosis.)*
- **S2 — Detection and cleaning recall: every text-bearing bubble on the page is
  found, and no Japanese pixels survive inside a cleaned region.** Measured
  separately from S1 — a perfect translation in a missed bubble is still a
  failure, and a leftover glyph is visible at a glance.
- **S3 — Time saved: a chapter takes materially less wall-clock human time
  starting from the tool's output than starting from the raws.** Measured by
  timing the same chapter both ways, once, honestly.
- **S4 — It reads naturally end to end.** The user reads the baked chapter and
  it does not jar. Subjective, and deliberately not a gate — but it is the thing
  S1 is a proxy for, and if S1 is met while S4 is not, S1 is measuring the wrong
  thing.
- **S5 — Cost: a benchmark chapter run costs under $2**, as reported by the app
  and confirmed against the provider's billing at least once.

## 8. Look and feel

**Image-first workspace.** The page is the interface: a large page preview with
the detected bubbles marked on the art, translations docked beside it, minimal
chrome around the edges. Closer to a photo editor than to a form or a dashboard.

- The art is the largest thing on screen at all times. Controls are secondary.
- A translation line and its bubble must be visibly, unambiguously linked —
  selecting one highlights the other. This is the single most important
  interaction in the product: the review screen is the only place a human can
  catch an error, and an unclear link makes the review worthless.
- Progress during a run is visible and per-page, with the running cost in view.
- Typeset output follows **standard scanlation lettering conventions**: comic
  body font, centred in the bubble, sensible line breaks, italic and bold
  available for emphasis. The baked page should look like a normal English
  release, not like a machine's output.
- Tone: workmanlike and quiet. This is a tool used for hours at a stretch.

Detail belongs to the Lead Designer; this section is the brief, not the design.

---

## Open questions

- **O1 — What is the benchmark chapter?** S1, S2, S3 and S5 all measure against
  a held-out chapter that does not exist yet. It must be chosen before the first
  quality story, and it must not be used while tuning. *Owner: user.*
- **O2 — What counts as "a line accepted as-is"?** ~~The 80% bar needs an
  operational definition (per bubble? per sentence? does a one-word fix count as
  a rejection?) before it can be measured rather than argued about.~~
  **RESOLVED** — `/plan-product` defined it mechanically (per text region;
  NFC + whitespace-collapse + trim and nothing else; a one-word fix is a
  rejection), and the **user chose the denominator on 2026-09-12**: the 80% bar
  is against the chapter's ground-truth region count, not against what the tool
  proposed. `docs/wiki/stack.md` §5/O2; §7 S1 above is updated.
- **O3 — Detection, OCR and inpainting: local or cloud?** The user chose "cloud
  LLM with page context" for the *translation*. Bubble detection and inpainting
  are not LLM tasks and are near-free on the available GPU. Whether OCR should
  be local (cheaper, weaker on stylised text) or left to the LLM (better, and it
  is already seeing the page) is a stack decision bounded by the $2 ceiling.
  *Owner: `/plan-product`.*
- **O4 — Which model, and does the $2 ceiling survive contact with it?** Cost
  per page must be estimated from real token counts on a real page before the
  architecture commits to sending full page images.
  *Owner: `/plan-product`.*
- **O5 — Which font?** ~~"Standard scanlation style" names a convention, not a
  file. A specific licensed font must be chosen and shipped or sourced.~~
  **RESOLVED** — Shantell Sans 1.011 under the SIL Open Font License 1.1, four
  static faces, shipped with the app. `docs/wiki/design/typeset-font.md`. The
  user additionally decided on 2026-09-12 that it is the **default**, not the
  only option: see the scope reading added to §5.
- **O6 — Vertical text and furigana.** Japanese bubble text runs vertically and
  is often annotated with furigana. Whether that is handled by the OCR path or
  needs explicit treatment is unresolved. *Owner: `/plan-product`.*

## Interview notes

Recorded because they change how later answers should be read:

- The user first chose "fire and forget" (no editing UI) alongside "scanlation
  workflow" (which implies one). Put to them as a contradiction; they resolved it
  toward **a minimal review step** — edit the proposed English lines before
  baking, no box dragging. That is why feature 4 exists and why the "no typeset
  editing" non-goal is drawn where it is.
- The user selected both "new to this, no comparison" and "I do it by hand
  today": they hand-typeset, and have not adopted an automated tool. So no
  incumbent's quality bar constrains v1 — only the manual workflow it replaces.
- All four offered success signals were selected. They are kept as five items,
  with S4 explicitly marked subjective rather than silently dropped, because
  dropping it would let S1 be satisfied by a metric that does not track
  readability.

### Added 2026-09-12, after planning

Three decisions the user made once `/plan-product` had put the trade-offs in
front of them. Recorded here rather than only in the sections they changed, so
the reasoning survives the edit.

- **S1's denominator is ground truth, not proposals.** Planning found that
  "80% of translated lines accepted" is gameable: a detector that finds only the
  five easiest bubbles on a page scores 100% on it, and every metric built that
  way would have gone green over a product that missed half the chapter. Two
  numbers were offered — the conditional one the brief literally said, and the
  unconditional one that cannot be gamed and is strictly harder to hit. **The
  user took the harder number**, knowing it is harder. The conditional number is
  still computed and printed beside it, because the *difference* between them is
  the whole detector-versus-translator diagnosis: a large gap means fix the
  detector, a small gap with a low score means fix the translation.
- **A proposed "report is void if detection recall < 95%" rule was dropped as a
  consequence**, not forgotten. It existed to stop anyone reading the
  conditional number as the headline when detection was bad. With the headline
  now unconditional, poor detection lowers it directly and proportionally, so
  the rule guarded nothing — and it actively hurt, because it suppressed the
  conditional number at exactly the moment that number is most diagnostic.
- **The lettering font became a default rather than a fixture**, and Windows
  High Contrast mode moved from "detect it and decline" to supported. Both were
  flagged by planning as decisions the user owned; both were answered yes.
