---
id: EPIC-13
title: The baked chapter - v1 fixes for what the benchmark review found
status: todo
release: v1
stories: [MT-142, MT-143, MT-144, MT-145, MT-146, MT-147, MT-148, MT-149, MT-150, MT-151, MT-152, MT-153, MT-154, MT-155, MT-156]
---

*Planned 2026-11-07 by `lead-po` (Claude Opus 5.5, `claude-opus-5-5`) from
the user's review of the MT-108 benchmark runs
(`docs/wiki/audits/MT-108-context-mode.md`, "The reviewer's reading"). The
user reviewed *Give My Regards to Black Jack* vol. 1 ep. 1 (pages 3-58), the
held-out benchmark chapter, in two copies: `D:\bench\blackjack-v1-ep01-A`
(`neighbours`) and `-B` (`rolling`). The defects below do not depend on the
mode, apart from one line-to-region slip that was seen in `neighbours`. Every
figure in "Evidence" was measured on 2026-11-07 from the two project files,
`truth.seed-draft.json` (the detector's 326 regions) and
`blackjack-v1-ep01-A.truth.json` (264). The scratch scripts that produced them
are not kept. Each story that relies on a figure re-measures it, on
development pages.*

## Goal

The baked page shows each balloon's English once, centred in its balloon, at
a size that fits. No Japanese is visible beside it. Drawn sound effects and
signs are left exactly as drawn, and a line never lands in a neighbour's
balloon. Where the pipeline cannot be sure of a line, the review screen says
so instead of shipping it silently.

## Why now

The product brief's S2 ("every text-bearing bubble is found, and no Japanese
pixels survive inside a cleaned region") fails on the benchmark for both
reasons. `recall` fails because 20 balloons are missed and 82 regions are
spurious. `residual ink` fails at a worst value of 0.4352 against a limit of
0.0100. The user found the visible consequences on almost every page they
checked. MT-108 D-1 makes `neighbours` the default (MT-109), which is the mode
in which the slip was seen. None of this is v2 work. Translating art text is
(EPIC-12), and this epic only stops the app proposing it.

## Evidence (diagnosis on the benchmark chapter; never tuned against it)

**Chapter 1 (pages 3-58) is diagnosis only.** No threshold, constant or rule
in this epic may be derived from it, and no story's before/after is measured
on it. The development set is MT-143's, drawn from `D:\bench\all-jp` pages
outside 3-58 (`product-brief.md` O1). The benchmark is re-run once, after the
epic, as the release measurement.

| Defect | Size on the benchmark | Mechanism, found in the code |
|---|---|---|
| **Fragments** (one balloon, several regions) | **15 balloons on 12 pages, split into 53 pieces.** 51 of the 82 "spurious" regions are pieces lying inside a truth balloon. 7 of the 20 "missed" truth regions are fragmented balloons that no single piece matches at IoU 0.5. | `detect/columns.py` `merge_columns` joins two regions only if they share one fence box, sit at most 12 px apart *across* the run direction, and overlap at least 50 % *along* it. Pieces **stacked in one column** overlap 0 % along the run, so they never merge. Of the in-balloon piece pairs that share a column, 28 have along-run gaps of 0-10 px. Adjacent columns of one balloon at this 1414 px scan sit 14-19 px apart (p004: 19), which is above `COLUMN_MAX_GAP_PX = 12`, a value measured on 1125 px scans (MT-008 recorded this limit). The worst page is p004: one balloon in 12 pieces, mostly single kana. |
| **Duplicates** (whole and pieces) | p008: two pieces inside a whole region's polygon. p004/p053: one piece carries the whole sentence's English and the others carry fragments or nothing. | The p008 pieces sit inside the outer contour of a ring-shaped component. The translator, given every piece, writes the whole sentence into one key. Both disappear once the pieces are one region. |
| **Art text proposed** | **30 regions on 13 pages** lie outside every truth region (sound effects, drawn signs). Examples: p017 has three siren regions whose OCR hallucinated `んーーー…` and `あああ…` (proposed "Brring"). p016's sign `救急舟人口` is `kind: bubble`, proposed "Emergency Entrance" and typeset over the art. | The detector's class cannot separate them (MT-117 D-1, 1,043 pages: no predicate). The OCR reads hallucinations confidently (`stack.md`). The translator is asked to translate every region it is sent. |
| **Residual ink** | 7 measured regions over the 0.0100 limit. The two worst are both **taller than the inpainter's native window**: p011 region 0 at **0.4352** (a grey smear over white narration on a photo) and p008 region 1 at 0.0329. **10 of 264 truth regions** have a long side above 448 px. Half-erased glyphs where the fence box cut a line (p023: `合計1433点` / `14330円`). Faint ghost rectangles of erased glyphs in the white of large balloons (p004). | `clean/inpaint.py`: a component whose bbox plus `MIN_CONTEXT_PX = 32` on each side exceeds 512 takes the **downscale path**, which the module itself calls "a correctness fallback: no component on the fixture pages takes it". `clean/mask.py`: the erase mask is the detector's `seg ∩ box` pixels dilated by 2 px, so a glyph that crosses the fence edge is erased only up to that edge. The ghosts are LaMa's near-white fill differing from the paper by a few levels. S2's contrast-based metric cannot see that difference. |
| **Typesetting** | Text too small or overlapping where one balloon held two regions (p011, p016, p017, p018, p023). Text set at the top of a large balloon (p004). | `typeset/interior.py`: each region looks for its balloon in a window of its own bbox grown by `CAP_RATIO = 1.0 x max(w, h)`. If the balloon is larger than that window, the flood is treated as a leak, and the star fallback centres the text on the *piece*. Two regions in one balloon each get the same interior and are set on top of each other (`pipeline/bake.py` `_set_blocks`). |
| **Line slip** (copy A, p017) | Regions 4-7 (`っ` / `いてーよー！！` / `いてーよー！！` / `急ぐぞ！！こっから先は戦場だ！！`) received "WEE" / "WEE" / "It hurts!!" / "It hurts!!". Region 8 `はい！！` received the battlefield line. | **Not our parser.** `page_prompt.response_schema` keys the answer by index, `parse.parse_lines_text` assigns by key (MT-011 C-4), and `translate_stage._to_reading_indices` maps keys back through `included`. The model itself wrote each answer under the wrong key: the page carried three hallucinated siren regions and a lone `っ`, and it attached the drawn "WEE-WOO" to the next index. Copy B, given the same listing, keyed it correctly. Nothing in the answer lets the app detect the slip. |
| **Translation slips** (copy B) | 永大 rendered "Eadai" (the official edition says "Eiroku"): B's glossary pre-pass proposed `永大 → Eadai`, and B's consistency pass then rewrote a correct "Eidai" line to match it. **Corrected after planning began:** the p018 dose is *not* a translation slip. The page prints a small horizontal `1000` inside vertical text, the OCR stored `１００`, and the official English says 1,000 mg. So B's "1000 mg" was right, and A's "100 mil" followed the bad OCR. | The reading comes from the glossary and is out of scope (U-2). The dose is an **OCR** defect. Its in-scope remedy is MT-156's flag, which shows the reviewer that the numbers disagree without claiming which side is wrong. |

## The user's decisions (2026-11-07)

- **U-1 - Priority order**, as asked and then clarified (the first wording of
  the option contradicted itself):
  1. merge split balloons;
  2. stop art-text proposals;
  3. the line-slip guard, with the bench's slip check;
  4. cleaning residue;
  5. typesetting leftovers;
  6. the number check.

  Enablers come first because every before/after needs them: the bench's
  development mode (MT-142) and the development set (MT-143).
- **U-2 - Item 7: the number check only.** A proposal whose numbers differ from
  the Japanese is flagged in review (MT-156). Name readings stay with the
  existing glossary editing. Changing what the consistency pass may overwrite
  is *not* in this epic.

  *Re-decided the same day.* The p018 dose turned out to be an OCR error (see
  "Evidence"). The user then chose to keep MT-156 as a **disagreement flag**:
  the caption says the numbers differ and asks the reviewer to check the page,
  without claiming which side is wrong. They declined both an OCR story for
  small horizontal numbers in vertical text and dropping the check.
- **U-3 - The bench gains a slip check** (MT-150). It counts neighbouring
  regions that got identical English from different Japanese, listed per page
  and reported beside S1b without changing it.
- **U-4 - Art text: the model marks it.** The page answer may name regions as
  drawn art text. The app excludes those regions with no proposal, and baking
  puts the original art back. They stay visible and restorable in review
  (MT-146, MT-147).

## Decisions (the Lead PO's, open to the user)

- **PO-1 - Merging is decided by the balloon, not by a wider pixel gap.**
  Raising `COLUMN_MAX_GAP_PX` from 12 to about 20 would join p004's columns,
  and it would also walk towards MT-008's measured negative: the separate
  bubble at gap 54. Separate balloons are separated by their outlines, not by
  distance. So MT-144 merges the regions whose text lies in one **closed
  balloon found on the source page**. The column rule stays for text with no
  closed balloon (narration on art, captions), and MT-145 extends it to
  pieces stacked in one column.
  *Amended 2026-11-11 (the user, in MT-144's GREEN):* on the MT-143
  development set, balloons that are drawn joined or overlapping share one
  patch of paper with no outline between them (p063, p089), and the user
  decided they **stay separate**. No setting of the closed-balloon rule kept
  them apart (MT-144 `## Notes`), so MT-144 was not built and its job folded
  into MT-145: merging is decided by the gaps between pieces in one fence box,
  both along a column and across columns, with the limits re-derived on the
  development set.
- **PO-2 - `art` is a new exclusion reason, not `user` and not `watermark`.**
  The store, the review row and the bench must be able to tell the model's
  judgement from the user's act. It needs a schema migration: SQLite cannot
  alter a CHECK in place, so the `region` table is rebuilt (MT-146).
- **PO-3 - The bench counts an `art`-excluded region as not proposed**
  (MT-148). Baking leaves its art as drawn, so it is not the phantom S2 fails a
  spurious region for. It still counts as missed if it was really a balloon,
  so the rule cannot hide a wrong exclusion. A `user` exclusion is still
  counted: it is a human's correction, not the pipeline's output. *Open to the
  user:* the alternative is to leave the bench's definition unchanged and
  report the art exclusions beside it.
- **PO-4 - The slip guard: each answer entry repeats its region's Japanese.**
  A line whose echo does not match its region's OCR text is recorded
  untranslated, which the system prompt already calls "recoverable", rather
  than shipped in the wrong balloon (MT-149). This is the cheapest guard that
  can *detect* a slip. Numbered markers drawn on the page image would change
  the image every provider is sent (`page_prompt` caps and shares it). *Cost,
  open to the user:* the echo adds output tokens of about the page's Japanese
  length. MT-149 measures it on the development set, and the live run is
  started only on the user's request.
- **PO-5 - The number check flags; it does not drop.** The check compares
  the English against the **OCR'd** Japanese, either of which can be wrong.
  On p018 the English was right and the OCR wrong. So it can only say they
  disagree, and clearing the line would destroy the correct side as often as
  the wrong one. The review row shows a caption naming the
  numbers (MT-156). The check covers Arabic digits, full-width and ASCII, plus
  English number words up to twenty and the tens. Kanji numerals (`三万八千`) are
  a documented limit.
- **PO-6 - MT-155 (one block per shared balloon) is conditional.** After
  MT-145 has merged what it can, MT-155 re-counts the regions
  that share a balloon interior on the development set. If the count is zero,
  it closes as a no-op with the count cited, as MT-121 did.

## Overlaps with stories outside this epic

- **MT-109** (to be cut: `neighbours` becomes the default) will change
  `context_mode`'s default in `pipeline/translate_stage.py`, `pipeline/
  stages.py` and `compose.py`. MT-147 and MT-149 also write
  `pipeline/translate_stage.py`. Different lines, but the same file: land
  MT-109 first (it is one line and a test) or put it in a different wave.
- **MT-141** (open: the window's consistency pass) writes `app.py`, `ui/run.py`,
  `ui/main_window.py`, `ui/progress.py`, `ui/batch_panel.py` and
  `components.md`. No story here writes those. MT-156 writes
  `ui/workspace.py` and MT-146 writes `ui/workspace.py`'s exclusion label.
  Their code is clear of MT-141 by declaration. All three stories edit
  `docs/wiki/design/components.md` §5, so they are reported as conflicts:
  rebase the docs, then go.

`bash scripts/plan.sh conflicts`, run 2026-11-07 on this branch, reported 6
conflicts and no UNKNOWN or DRIFT. It judges only the stories that can start
now, so it does not show the waves inside this epic, which `depends_on` keeps
apart:

- MT-106 + MT-149: MT-106's main-branch story file still says REVIEW, though
  PR #152 merged it. Clear in fact, once MT-106's close is recorded.
- MT-141 + MT-146, and MT-141 + MT-156: `components.md`, docs only.
- MT-142 + MT-150: `bench/__main__.py`.
- MT-146 + MT-149: `store/schema.py` and `store/project.py`. These are two
  migrations, so they go in two waves, and the second takes the next schema
  version.
- MT-146 + MT-156: `ui/workspace.py`'s caption line.

The pairs inside the epic that share files run as separate waves, never in
parallel:

- MT-147 + MT-149: `page_prompt.py`, `parse.py` and the adapters.
- MT-151 + MT-153: `clean/inpaint.py`.
- MT-152 + MT-155: `pipeline/bake.py`.
- MT-142 + MT-148: `bench/recall.py` and `acceptance.py`.

## Done when

On the development set, before and after the epic:

- S2 `spurious` falls by at least the fragment pieces and art regions MT-143
  counts.
- `recall` rises by the fragmented balloons MT-143 counts.
- The worst residual ink is at or under `RESIDUAL_INK_MAX`, or each region over
  it is named with its cause in an audit.
- The bench's slip count is zero.
- A live run of the benchmark chapter, made once, after the last story and on
  the user's request, is reviewed by the user. They find no balloon translated
  twice, no art text typeset over, and no line in a neighbour's balloon.

## Stories (in the user's priority order)

Enablers:

- **MT-142** - the bench measures a development-use truth document when asked
  (`--development`), labels every line of the report as a development
  measurement, and still refuses it by default.
- **MT-143** (spike) - the development set: a truth document for a full
  episode outside pages 3-58, seeded from the detector, reviewed, and confirmed
  by the user. It records the baseline report and the fragment, art-text,
  residual and tall-region counts every later story moves.

1. Split balloons:
   - **MT-144** - *not built: folded into MT-145, the user's decision of
     2026-11-11* (see PO-1's amendment).
   - **MT-145** - pieces of one utterance come back as one region, stacked or
     side by side, decided by the gaps between them in one fence box.
2. Art text:
   - **MT-146** - `art` is an exclusion reason the project file, the domain and
     the review row know (schema v13).
   - **MT-147** - the page answer names drawn art text, and those regions arrive
     excluded with no proposal.
   - **MT-148** - the bench counts an `art`-excluded region as not proposed
     (PO-3).
3. Line slips:
   - **MT-149** - each answer entry repeats its region's Japanese. A mismatched
     entry is recorded untranslated.
   - **MT-150** - the bench reports a slip count (U-3).
4. Cleaning:
   - **MT-151** - a region taller than the inpainter's window is cleaned at
     native resolution.
   - **MT-152** - a glyph the erase mask cuts is erased whole, inside a
     balloon.
   - **MT-153** - an erased glyph leaves no ghost on flat paper.
5. Typesetting:
   - **MT-154** - a closed balloon larger than the search window is found
     whole, so its text is centred.
   - **MT-155** - regions sharing one balloon are set as one block
     (conditional, PO-6).
6. Numbers:
   - **MT-156** - a proposal whose numbers differ from the Japanese says so in
     review.

## Deliberately not in this epic

- Translating, labelling or redrawing signs and sound effects: EPIC-12 (v2).
- Name readings and what the consistency pass may overwrite (U-2).
- Horizontal-text merging. p023's receipt is horizontal, and
  `merge_columns`' axis is a parameter the pipeline never sets. That is its
  own story if the development set shows it matters.
- Retraining or replacing the detector, or changing `MASK_THRESHOLD`,
  `BOX_CONFIDENCE` or NMS.
- Re-detecting projects made before these stories. Their regions stay as
  stored until the user runs again on a fresh project.
