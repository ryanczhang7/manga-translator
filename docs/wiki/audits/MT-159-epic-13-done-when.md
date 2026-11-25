# EPIC-13's "Done when" lines, measured on the development set - MT-159

Spike MT-159 (EPIC-13, closing story). Written on 2026-11-25 by a `lead-po`
dispatch (planned `fable`, resolved Fable 5.2, `claude-fable-5-2`, no
override) from the output of one measuring dispatch (`feature-developer`,
planned `opus`, resolved Claude Opus 5.5, `claude-opus-5-5`, no override).
The measurer's whole hand-back is kept as
`D:\bench\review\mt159\measuring-report.md`.

Revised the same day, after MT-159's AM-1 was upheld and the user answered
the questions this audit returned (MT-159 `## Notes`, "The user's answers,
second round"): the slip figure's scope is corrected, the readings of lines
1, 2, 3 and 5 are the user's, and three of the six candidate stories are
filed. No figure was re-measured for the revision.

**Indices.** The bench prints `page N region M`: N is the page ordinal
(0 = p061 ... 23 = p084, 24 = p087 ... 45 = p108) and M is the **truth
document's** region index, written here as `t`: "p075 t2". A region of the
project is named by its **reading index**, written `r`: "p075 r2". MT-154's
and MT-155's names (p064:1, p075 7/8) are reading indices.

## Scope

**Audited.** The seven lines under "Done when" in
`docs/backlog/epics/EPIC-13.md`, as the epic reads on 2026-11-25, each
measured on MT-143's development set (46 pages, p061 to p108, 253 truth
regions) after the last story of the epic.

**Two runs.**

| | No-spend run | Paid run |
|---|---|---|
| What ran | detect, OCR and clean (`mangatl-run --no-translate`), then the bench | a copy of the no-spend pages, project and truth; the translate stage only, Gemini only, `rolling`; then the bench |
| Pages folder | `D:\bench\blackjack-v1-ep02-03-mt159\` (46 `.jpg`) | `D:\bench\blackjack-v1-ep02-03-mt159-paid\` (46 `.jpg`) |
| Project | `D:\bench\blackjack-v1-ep02-03-mt159.mtproj` | `D:\bench\blackjack-v1-ep02-03-mt159-paid.mtproj` |
| Truth | `D:\bench\blackjack-v1-ep02-03-mt159.truth.json` | `D:\bench\blackjack-v1-ep02-03-mt159-paid.truth.json` |
| Bench output, kept whole | `D:\bench\review\mt159-bench.txt` (254 lines) | `D:\bench\review\mt159-bench-paid.txt` (251 lines) |
| Used for | lines 3, 5 and 6, and the classing of AC-3 | lines 1, 2 and 4, with the no-spend figure beside each (MT-159 PO-5) |

**Commit.** `HEAD` was `97b31fbf8c997ba7030177f49602dbfe94b617a5` and
`origin/main` was `d13aeacbbc18e4a3db4d815f42dfe99fb867a550`, after `git
fetch origin`. `git diff --quiet origin/main HEAD -- src packaging` exited 0
and `git status --short -- src packaging` printed nothing, so `src/` and
`packaging/` are `origin/main`'s. Every attest record carries the tree hash
`2d0e012dfc6b13208512795d33f6e520add79cc7`.

**Truth document.** sha256 of both copies:

    68161def30c014abd0be260e29b5fa33225a1e125c70adc47a514878c942bc10

This is the hash in `docs/wiki/audits/MT-143-development-set.md`.

**The paid run was asked for by the user** on 2026-11-25 (MT-159 `## Notes`,
Q-1: "Translate only, ~$0.79"). Its cost, from its bench's S5 line:
`S5 chapter cost  $0.6792  46 priced calls`. Every response carried
`model_version` `gemini-3.1-pro-preview`. No Gemini call was made on the
no-spend project, and no Claude call, glossary pass, consistency pass or
`live` gate run was made at all.

**Left out, deliberately.**

- The benchmark chapter (pages 3 to 58). Nothing under it was read or run,
  and this audit holds no figure measured on it. Line 7 is not measured.
- The quality of the translations. No done-when line asks for it here.
- `neighbours` mode. The paid run used `rolling`, the shipped default.
- Any threshold, constant or fix. This audit measures; it changes nothing.

## Decided

The verdicts follow from the figures under "Evidence". Each row says which
part of the evidence it rests on. If that evidence later fails, the verdict
is no longer settled.

### The seven lines

| # | The line, as the epic reads | Before, and where it was read | After | Verdict |
|---|---|---|---|---|
| 1 | "S2 `spurious` falls by at least the fragment pieces and art regions MT-143 counts." | `spurious 106` = 89 pieces + 17 art-text regions. Quoted from MT-143's audit (seed run at `723b8ec`); the classing script reproduced it (E-3). | Paid: `spurious 23`, a fall of 83. No-spend: `spurious 32`, a fall of 74. Needed, by the PO's reading: a fall of at least 106. | `not met` |
| 2 | "`recall` rises by the fragmented balloons MT-143 counts." | `matched 234 / ground truth 253`; 16 balloons missed because fragmented. Quoted from MT-143's audit; reproduced (E-3). | Paid: `matched 235`, a rise of 1. No-spend: `matched 238`, a rise of 4. Needed, by the PO's reading: a rise of at least 16. | `not met` |
| 3 | "The worst residual ink is at or under `RESIDUAL_INK_MAX`, or each region over it is named with its cause in an audit." | `worst 0.0991 / max 0.0100`, six regions over. Quoted from MT-143's audit. | No-spend: `worst 0.5235 / max 0.0100`, five regions over. The first half of the line does not hold. Each of the five is named with its cause in E-5. | `met`, by the line's "or" clause |
| 4 | "The bench's slip count is zero." | No figure. The slip check did not exist before the epic (MT-150 added it). | Paid: `slips (identical English, different Japanese)  0`, measured over 207 neighbouring pairs on 40 pages. It is zero by construction on the other six pages, which hold fewer than two compared lines: p105 with none; p071, p072, p088, p096 and p108 with one each (E-2). The no-spend run also prints 0, by construction: it holds no English. | `met` |
| 5 | "Text is centred in its balloon: the six closed balloons MT-154 names (p064:1, p073:2, p075:6, p082:1, p082:2, p092:2) are re-measured at close, each found whole with its text centred as MT-154's AC-1 and AC-2 define (the user, 2026-11-19; MT-154 PO-3)." | None of the six was found whole before MT-154. Quoted from MT-154 (its DV-5); the control here reproduced it, 0 of 6 (E-6). | No-spend: 6 of 6 found whole; 4 of 6 pass. p082:1 fails on the block's offset, -17.5 %. p082:2 fails on the block's offset, +32.0 %. The bound is 5 %. | `not met` |
| 6 | "No two set blocks' glyph boxes intersect inside one balloon: re-measured at close as MT-155's DV-4 defines, with its fixed placeholder English. Measured at MT-155's planning: 4 block pairs before (p063 4/5, p066 6/7, p075 7/8, p089 7/8), 0 after by the PO's reference of the rule (the user, 2026-11-19; MT-155 PO-5 and PO-11)." | 4 colliding block pairs on 270 blocks, 23 overflowing. Quoted from MT-155 (its DV-4, at `0b0e378`); the control here reproduced it (E-7). | No-spend: 270 blocks, 15 overflowing, 0 pairs. | `met` |
| 7 | "A live run of the benchmark chapter, made once, after the last story and on the user's request, is reviewed by the user. They find no balloon translated twice, no art text typeset over, and no line in a neighbour's balloon." | None. | None. | `not measured` |

**Line 7** is `not measured` because the live benchmark run is the user's to
ask for and the user's to review. What would measure it: that run, made
once on the benchmark chapter at the user's request, and the user's reading
of its pages.

### Which lines the epic meets on the development set

- **Met:** line 4 (slip count, over 207 neighbouring pairs on 40 pages) and
  line 6 (glyph boxes).
- **Met by its "or" clause:** line 3 (residual ink). The worst value is
  0.5235 against a limit of 0.0100, so the first half does not hold. The line
  is met because all five regions over the limit are named with a cause in
  E-5. The user chose this reading on 2026-11-25 ("Met via 'or' clause").
- **Not met:** line 1 (`spurious`), line 2 (`recall`) and line 5 (centring).
- **Not measured:** line 7 (the live benchmark run).

### What is responsible for each line not met

- **Line 1, `spurious`.** 23 regions are still spurious on the paid run: 19
  fragment pieces and 4 art-text regions. The pieces are p063 r4; p064 r0;
  p065 r1, r3; p077 r0; p082 r1, r2, r3; p084 r0, r1, r2; p099 r6; p104 r0,
  r1; p105 r0, r1, r2, r3, r4. The art-text regions the model did not mark
  are p070 r1, p070 r2, p089 r5 and p106 r0. With every art-text region
  taken off, the fall would be 87, still short of 106. So the pieces alone
  decide this line.
- **Line 2, `recall`.** 12 of MT-143's 16 missed fragmented balloons are
  still missed (truth indices): p063 t4, p064 t0, p065 t1, p077 t0, p082 t1,
  p082 t2, p084 t0, p084 t1, p099 t6, p104 t0, p105 t0, p105 t1. On the paid
  run three more truth balloons are missed because the model marked their
  regions as art: p075 t0, t2 and t3. That is why the paid rise is 1 and the
  no-spend rise is 4.
- **Line 5, centring.** p082:1 and p082:2 (reading indices). Both lie in one
  balloon, which is found whole. MT-155 sets each in its own part of that
  balloon, so neither block sits at the whole balloon's centre.

### How the lines were read

All four readings below are the user's, given on 2026-11-25 after seeing
the figures (MT-159 `## Notes`).

- **Lines 1 and 2** are read as the epic's note of 2026-11-25 reads them: a
  fall of at least 106 in `spurious`, and a rise of at least 16 in
  `matched`. The reading was the Lead PO's, and the user confirmed it
  ("Confirm"). Both verdicts are `not met` on the paid figure and on the
  no-spend figure alike.
- **Line 5** is read as the epic's line says: the block against the centre
  of the **whole** balloon. The user first chose to decide after seeing the
  figures (MT-159 PO-3), and then chose "Whole balloon: not met". The epic's
  line stays as written. The figures against each region's own part are in
  E-6, labelled as extra, and decide nothing.
- **Line 3** is met by its "or" clause, the user's choice ("Met via 'or'
  clause"). "Its cause" is taken as what put the counted ink there. For one
  region, p075 t3, the evidence shows that the inpainter painted the ink and
  does not show why it painted a stroke at that place (E-5).
- **The paid figures stand.** MT-159's DV-7 first held two bullets that the
  paid run could not meet. A fresh adjudication upheld that the two bullets
  were wrong as planned (MT-159 AM-1), the user approved the amendment, and
  DV-7 holds on all five bullets as amended (E-2).

### Candidate stories

The user accepted three and declined three on 2026-11-25. The accepted ones
are filed (see "Stories filed").

1. Twelve fragmented balloons on nine pages are still missed, in 19 pieces.
   **Accepted** ("12 fragmented balloons"). Filed as **MT-166**, a spike:
   the rule that would join them is not known.
2. Four art-text regions are still proposed after the model's art marks
   (p070 r1, p070 r2, p089 r5, p106 r0). **Declined.** Not filed.
3. Three hand-lettered balloons on p075 are excluded as art and count as
   missed. **Accepted** ("p075 marked as art"). Filed as **MT-167**.
4. Part of a long dash is left on p082's cleaned page, between two pieces of
   one balloon. **Accepted** ("p082 dash left behind"). Filed as **MT-168**.
5. The inpainter paints strokes inside three small erased balloons on p075.
   **Declined.** Not filed.
6. The residual-ink measure reads screentone under erased text as ink (p061
   t0, p088 t0). **Declined.** Not filed.

What declining leaves in place: lines 1 and 3 keep their evidence as it is.
The four art-text regions of candidate 2 stay proposed, and the five regions
over the residual limit stay over it, named with their causes in E-5.

## Evidence

This section is not settled. A story that depends on a number here checks it
first.

### E-1 The no-spend run and its bench (AC-1)

**Commands,** each through `bash scripts/attest.sh --`:

- `uv run --no-sync mangatl-run --no-translate --models packaging/models
  D:/bench/blackjack-v1-ep02-03-mt159`: exit 0, 124 s. Its last line reads
  "46 pages written to D:\bench\blackjack-v1-ep02-03-mt159_en; 270 regions
  left empty; 0 lines unreviewed; 0 pages not cleaned". Log kept as
  `D:\bench\review\mt159-run.log`.
- `uv run --no-sync python -m mangatl.bench
  D:/bench/blackjack-v1-ep02-03-mt159 --development`: exit 0, 181 s. Attest
  log `.claude/state/attest-logs/20261125T170233Z.800853.log`. The writer
  ran `bash scripts/attest.sh check --` on the same words: `fresh`, exit 0.

**Output,** verbatim from `D:\bench\review\mt159-bench.txt`, with one cut.
The residual list is cut to the regions over the limit: 233 lines at or
under 0.0100 are omitted, 203 of them reading 0.0000, and the largest of
them is `page 2 region 5  0.0082`. The file holds all 238. The two `$—`
were written to the file as the single cp1252 byte `0x97` and are shown
decoded.

```
DEVELOPMENT SET - not a benchmark result
S1b chapter acceptance      0.0%  accepted 0 / ground truth 253   <- headline  [development]
S1a translation acceptance  0.0%  accepted 0 / proposed 270  [development]
recall                      94.1%  matched 238 / ground truth 253
spurious                    32
left as art                 0
identity S1b = S1a x recall does not hold (spurious present)
slips (identical English, different Japanese)  0
recall        94.1%  matched 238 / ground truth 253
missed        page 1 region 2, page 2 region 4, page 3 region 0, page 4 region 1, page 16 region 0, page 21 region 1, page 21 region 2, page 23 region 0, page 23 region 1, page 24 region 2, page 33 region 1, page 36 region 6, page 41 region 0, page 42 region 0, page 42 region 1
spurious      32
left as art   0
residual ink  worst 0.5235 / max 0.0100
  page 0 region 0  0.5235
  page 14 region 0  0.0202
  page 14 region 2  0.0826
  page 14 region 3  0.0418
  page 25 region 0  0.0991
S2 FAIL: recall, residual ink  [development]
S5 chapter cost  $—  no priced calls  [development]
per page         $—  46 pages
```

The S1 lines, `left as art 0` and `slips 0` are zero by construction on this
run: the project holds no English and no exclusion.

**AC-1's control holds.** The sha256 equals MT-143's. The first line is the
development label. The folder holds 46 `.jpg` files, p061 to p108, and none
from pages 3 to 58. The writer re-ran all three checks.

**Against the prediction** (MT-159 Contract B-3, MT-153's run at `09437a0`):
every figure is the one predicted. 270 regions, matched 238, spurious 32,
slips 0, worst 0.5235, and the same five regions over.

*How it could be wrong:* the run is one machine's, on one GPU. The bench is
deterministic on a stored project, but detect and clean were run once.

### E-2 The paid run and its bench (AC-5, second half)

**What ran.** The scratch driver `D:\bench\review\mt159\paid_run.py`, on the
copy only: `TranslateStage(partial(gemini.translate_page, recorder),
page_estimate(gemini.MODEL_ID), "rolling")`, page by page, with a stop once
the ledger passed $1.60 and one retry allowed for a page failing unbilled.
Exit 0, 347 s. Its last line: `TOTAL $0.6792; ledger rows 46; responses 46;
model_versions ['gemini-3.1-pro-preview']; retried []; untranslated [];
stopped None`. Log `D:\bench\review\mt159-paid-run.log`.

**Checked before the first call** (`paid-prepare.txt`): 46 `.jpg` files,
p061 to p108, none from pages 3 to 58; truth sha256 equal to MT-143's; 0
`llm_call` rows; 270 regions, none excluded; 0 proposals.

**The bench on the copy:** `uv run --no-sync python -m mangatl.bench
D:/bench/blackjack-v1-ep02-03-mt159-paid --development`, exit 0, 161 s.
Attest log `.claude/state/attest-logs/20261125T172450Z.827718.log`; the
writer's `attest.sh check` on the same words: `fresh`, exit 0. Verbatim from
`D:\bench\review\mt159-bench-paid.txt`, with the same cut: the residual list
is cut to the regions over the limit, and 233 lines at or under 0.0100 are
omitted. The file holds all 235.

```
DEVELOPMENT SET - not a benchmark result
S1b chapter acceptance      92.9%  accepted 235 / ground truth 253   <- headline  [development]
S1a translation acceptance  91.1%  accepted 235 / proposed 258  [development]
recall                      92.9%  matched 235 / ground truth 253
spurious                    23
left as art                 12
identity S1b = S1a x recall does not hold (spurious present)
slips (identical English, different Japanese)  0
recall        92.9%  matched 235 / ground truth 253
missed        page 1 region 2, page 2 region 4, page 3 region 0, page 4 region 1, page 14 region 0, page 14 region 2, page 14 region 3, page 16 region 0, page 21 region 1, page 21 region 2, page 23 region 0, page 23 region 1, page 24 region 2, page 33 region 1, page 36 region 6, page 41 region 0, page 42 region 0, page 42 region 1
spurious      23
left as art   12
residual ink  worst 0.5235 / max 0.0100
  page 0 region 0  0.5235
  page 25 region 0  0.0991
S2 FAIL: recall, residual ink  [development]
S5 chapter cost  $0.6792  46 priced calls  [development]
per page         $0.0148  46 pages
```

No proposal was reviewed in this run. The two S1 lines are pasted because
the command prints them, and no verdict here uses them.

**No-spend beside paid.**

| Bench line | No-spend | Paid |
|---|---|---|
| `recall` | `94.1%  matched 238 / ground truth 253` | `92.9%  matched 235 / ground truth 253` |
| `spurious` | 32 | 23 |
| `left as art` | 0 | 12 |
| `slips` | 0 (by construction) | 0 |
| residual lines / over the limit | 238 / 5 | 235 / 2 |
| S5 | `$—  no priced calls` | `$0.6792  46 priced calls` |

**The 12 regions the model excluded as art** (reading indices; the class is
AC-3's, from the no-spend project, E-3):

- Nine art-text regions: p061 r3, r4, r5; p066 r1; p070 r0; p071 r1; p072
  r0; p089 r3; p097 r2. These account for the fall in `spurious`, 32 to 23.
- Three regions that matched a truth balloon at IoU 1.0: p075 r0 (truth t0),
  p075 r2 (t2) and p075 r3 (t3). The bench counts an art-excluded truth
  balloon as missed (EPIC-13 PO-3). These account for the fall in `matched`,
  238 to 235, and for the three p075 entries the paid `missed` line adds.

**The three p075 balloons, looked at.** The crops
`D:\bench\review\mt159\crops\residual_p075_t0_x4.png`, `_t2_x4.png` and
`_t3_x4.png` show three small closed balloons, each holding three
hand-lettered katakana that read as ガチャ. The OCR stored `Ｈチャ`, `ロキャ`
and `Ｈチャ`. The truth document has all three as `kind: bubble`, "confirmed
by the user 2026-11-10". MT-147's DV-2 run marked the same three (quoted:
"p075 truth 0, 2 and 3"). Whether they are dialogue or a drawn sound is the
user's reading of the page. This audit keeps the truth document as it is.

**What the paid run hides.** The bench measures residual ink only on
matched truth regions. p075 t0, t2 and t3 are over the limit on the no-spend
run (E-5) and are absent from the paid residual list, because they are now
missed. The cleaned pages are the same.

**The two projects hold the same regions and the same cleaned pages.** The
writer's check, `D:\bench\review\mt159\writer_cmp.py` (sqlite, read-only;
output `writer-cmp.txt`): 270 region rows in each, identical on every
column but `excluded`; the `cleaned_page` table identical; `excluded` is
all null in the no-spend project and 258 null, 12 `art` in the paid one.

**Proposals stored** (`paid-store.txt`): 252 proposals, on all pages but
one. p105 holds none. The kept response for p105 has entries for regions r0
and r2 only, each with an echo that differs from the region's OCR text; the
store has both lines `misaligned` with no English, which is what MT-149's
check writes, and the other three lines with neither
(`p105-and-misaligned.txt`). They are the only two misaligned lines in the
chapter. p105's five regions are all fragment pieces (E-3). MT-159 AM-1's
adjudicator reproduced the store's side of this and did not read the
response.

**What the slip figure covers.** The bench's slip check compares each
compared line (a proposal, not excluded, not `misaligned`) with the next
compared line on the same page, so a page needs two to be able to show a
slip. Counted from the paid store, read-only, by MT-159 AM-1's adjudicator
and again when the amendment was applied:

| Compared lines on the page | Pages | Which |
|---|---|---|
| Two or more | 40 | 247 compared lines, so 247 - 40 = **207 neighbouring pairs** |
| One | 5 | p071 (r1 excluded as art), p072 (r0 excluded as art), p088, p096, p108 (one region each) |
| None | 1 | p105 (five regions, no proposal, two lines `misaligned`) |

So `slips 0` is a measurement over 207 neighbouring pairs on 40 pages, in
`rolling` mode, and zero by construction on the other six pages. An earlier
draft of this section gave the scope as every page holding English; that is
not the bench's scope. The slip the epic records was seen in `neighbours`,
which was not run.

**MT-159's DV-7 holds on all five bullets, as amended.** Two of its bullets
were wrong as planned, and MT-159's AM-1 reworded them: upheld by a fresh
adjudication on 2026-11-25, with a reproduction from the two stores and the
two kept bench outputs, and approved by the user the same day. Bullet 4 as
amended asks that the regions and cleaned pages be equal (above) and that
the paid residual block be the no-spend block less one line for each truth
balloon only the paid bench lists as missed: it is, by exactly the three
p075 lines. Bullet 5 as amended asks that the copy hold compared lines and
that the slip figure be written with its scope and the pages outside it
named: the table above. The evidence is pasted in the story under DV-7 and
AM-1. The paid figures stand.

*How it could be wrong:* one pass of one model version. A second pass can
mark different regions as art. MT-147's run on the seed regions (quoted:
"all 17 art-text regions marked `art`") marked every art-text region, and
this run left four unmarked, on regions that have since been merged.

### E-3 The classing of `spurious` and `recall` (AC-3)

**Method,** MT-143's, restated. Regions scored are the ones the bench
scores; a region is spurious if `match_regions` (IoU 0.5) pairs it with no
truth region.

- A **piece** is a project region whose IoU with every truth region on its
  page is below 0.5 (`iou(decode_mask(region.mask), polygon_mask(truth))`)
  and whose polygon raster lies at least 50 % inside one truth region's
  raster. It is assigned to the truth region holding the largest share.
- An **art-text region** is one whose polygon raster lies at least 50 %
  outside the union of the page's truth rasters.
- **Neither** is the rest.
- A **fragmented balloon** is a truth region holding at least one piece: a
  *duplicate* if a whole region also matches it, *missed* otherwise.

**Tool.** `D:\bench\review\mt159\classify.py`, written new from those
definitions, not adapted from MT-143's `measure.py` (a departure from
Contract C-5). Run with `uv run --no-sync python -I`, sqlite read-only.

**Control (AC-3's, DV-2): holds.** On MT-143's seed project the script
prints 340 scored, 106 spurious = 89 pieces + 17 art + 0 neither, and 18
fragmented balloons = 2 duplicate + 16 missed (`classify-seed.txt`). These
are MT-143's figures, and the 18-balloon list matches MT-143's
`summary_dev.md` row for row. So the after counts are comparable with the
before.

**After, on the no-spend project** (`classify-after.txt`). 270 scored, 238
matched, 32 spurious. No spurious region has an IoU of 0.5 or more with any
truth region.

| Class | Count | Regions (reading index) |
|---|---|---|
| Fragment piece | 19 | p063 r4; p064 r0; p065 r1, r3; p077 r0; p082 r1, r2, r3; p084 r0, r1, r2; p099 r6; p104 r0, r1; p105 r0, r1, r2, r3, r4 |
| Art-text region | 13 | p061 r3, r4, r5; p066 r1; p070 r0, r1, r2; p071 r1; p072 r0; p089 r3, r5; p097 r2; p106 r0 |
| Neither | 0 | - |
| **Sum** | **32** | equals the bench's `spurious 32` |

All 13 art-text regions lie 100 % outside the truth and have IoU 0.0. The
seed run had 17. The four fewer are on p089 (4 to 2) and p097 (3 to 1).
That they were merged is an inference from the counts; the regions were not
traced by polygon.

**After, on the paid copy** (`classify-paid.txt`). 258 scored, 235 matched,
23 spurious = 19 pieces + 4 art-text + 0 neither. The four art-text regions
left are p070 r1, p070 r2, p089 r5 and p106 r0. The pieces are the same 19.

**The 16 balloons MT-143 counts as missed because fragmented** (truth
indices):

| Now | Count | Balloons |
|---|---|---|
| Matched | 4 | p061 t0, p089 t6, p090 t0, p108 t0 |
| Still missed | 12 | p063 t4, p064 t0, p065 t1, p077 t0, p082 t1, p082 t2, p084 t0, p084 t1, p099 t6, p104 t0, p105 t0, p105 t1 |

Four are now matched, and the bench's `matched` rose by 4 on the no-spend
run (234 to 238). On the paid run it rose by 1 (234 to 235): the same four,
less the three p075 balloons excluded as art.

The 12 still missed hold all 19 pieces: p063 t4 [r4]; p064 t0 [r0]; p065 t1
[r1, r3]; p077 t0 [r0]; p082 t1 [r1, r2]; p082 t2 [r3]; p084 t0 [r0]; p084
t1 [r1, r2]; p099 t6 [r6]; p104 t0 [r0, r1]; p105 t0 [r0, r3]; p105 t1 [r1,
r2, r4]. None is a duplicate.

**Every truth region still missed, no-spend run** (15, truth indices; one
to one with the bench's `missed` line): p062 t2, p063 t4, p064 t0, p065 t1,
p077 t0, p082 t1, p082 t2, p084 t0, p084 t1, p087 t2, p096 t1, p099 t6,
p104 t0, p105 t0, p105 t1. Three hold no piece at all: p062 t2, p087 t2 and
p096 t1. They were missed before the epic too (MT-143's 19 missed were its
16 fragmented and these three).

**On the paid run** the missed list is those 15 and p075 t0, t2 and t3: 18.

*How it could be wrong:* the 50 % rules are MT-143's and were not
re-derived. A region half inside one truth region is classed by a raster
share, not by eye. The script is new and unreviewed; the seed control is
what ties it to MT-143's counts.

### E-4 Line arithmetic

| Line | Before | No-spend | Paid | Needed |
|---|---|---|---|---|
| 1, fall in `spurious` | 106 | 106 - 32 = 74 | 106 - 23 = 83 | at least 106 |
| 1, if every art-text region were off | - | 106 - 19 = 87 | 106 - 19 = 87 | at least 106 |
| 2, rise in `matched` | 234 | 238 - 234 = 4 | 235 - 234 = 1 | at least 16 |

### E-5 Each region over `RESIDUAL_INK_MAX` (AC-4)

**Method,** MT-143's section 5, on the no-spend project.
`RESIDUAL_INK_MAX` is read from `mangatl.bench.residual` and is 0.01. The
value is `ink_fraction(page_luma(cleaned), polygon_mask(truth))`. "Inside
the erase mask" is against `erase_mask(included(regions), size,
source_grey(source))`. "Unchanged from the source" is per pixel against the
original page. The path is `clean/inpaint.py`'s own choice per erase
component, as the module reads today. Tool:
`D:\bench\review\mt159\residual.py`, output `residual.txt`.

**Crops** are under `D:\bench\review\mt159\crops\`. Each shows the original,
the cleaned page with the truth polygon, and a map: red is counted ink
inside the erase mask, blue is counted ink outside it, grey is the mask.
The writer looked at every crop named below.

"Over the limit" is a value strictly above 0.0100 as the bench prints it.
Five residual lines are over, counted by command (DV-3), and the table has
five rows.

| Page | Truth | Bench line | Value | In MT-143's audit? | Counted ink px | Inside the erase mask | Unchanged from source | Path |
|---|---|---|---|---|---|---|---|---|
| p061 | t0 | `page 0 region 0` | 0.5235 | No. It was missed then, so it was not measured | 23475 | 14227 (9248 outside) | 9304 | 3 components, all native |
| p088 | t0 | `page 25 region 0` | 0.0991 | Yes, 0.0991 | 4181 | 4120 (61 outside) | 84 | 1 component, native |
| p075 | t2 | `page 14 region 2` | 0.0826 | Yes, 0.0826 | 189 | 189 | 2 | native |
| p075 | t3 | `page 14 region 3` | 0.0418 | Yes, 0.0418 | 84 | 84 | 0 | native |
| p075 | t0 | `page 14 region 0` | 0.0202 | Yes, 0.0202 | 47 | 47 | 1 | native |

**Causes, with the evidence for each.**

- **p061 t0, 0.5235. The text sits on screentone, and the measure counts
  the tone as ink.** The original crop shows a white, outlined vertical
  title on dark halftone, with building art at the foot of the truth
  polygon. In the cleaned crop no glyph is left; the column is repainted
  with a tone-like texture. 9248 of the counted pixels lie outside the
  erase mask and 9304 are unchanged from the source: that is the original
  tone and art the truth polygon covers and the mask does not (the mask
  covers 58 % of the polygon). The other 14227 are tone the inpainter
  painted inside the mask. The region's ink fraction was already 0.4349 on
  the source page. Crop: `residual_p061_t0.png`. The region is new to this
  list because its five pieces are now one region (`merged_from` 0 to 4),
  which matches the truth at IoU 0.5035. The repainted column is visibly smoother
  than the tone around it; the residual measure does not tell that apart
  from ink.
- **p088 t0, 0.0991. The same cause as MT-143 named: art under the text.**
  The episode title sits on light screentone crossed by vertical lines. The
  inpainter repainted the tone and the lines: 4120 of 4181 counted pixels
  are inside the mask and 84 are unchanged. No glyph is left in the cleaned
  crop. The value is MT-143's to four places. Crop: `residual_p088_t0.png`.
- **p075 t2, 0.0826. The inpainter drew two vertical strokes inside the
  erased balloon.** All 189 counted pixels are inside the mask and 2 are
  unchanged; 136 are at places where the source had glyph ink. The cleaned
  crop shows two long thin vertical lines where the glyphs' uprights were,
  longer than the strokes they replace. The same cause MT-143 named. Crop:
  `residual_p075_t2_x4.png`.
- **p075 t3, 0.0418. The inpainter painted a dark stroke on what was white
  paper, along the right edge of the erase mask, and a dot.** All 84 counted
  pixels are inside the mask, none is unchanged, and only 8 are where the
  source had ink. So it is not a glyph left behind and not a glyph redrawn.
  Why the inpainter painted a stroke at that place: **cause not known**.
  In the crop the stroke lies where this balloon's own outline and the
  neighbouring balloon's outline meet the mask, which is consistent with an
  outline being continued into the erased area; nothing measured shows it.
  MT-143 called this one a "faint stroke ghost"; the new crop does not
  support "ghost of a glyph". Crop: `residual_p075_t3_x4.png`.
- **p075 t0, 0.0202. The balloon's own outline, redrawn inside the mask.**
  All 47 counted pixels are inside the mask, 1 is unchanged, and 45 are
  where the source had ink. In the crop they form a short arc at the
  polygon's top-left corner, where the truth polygon and the erase mask
  overlap the balloon's drawn outline. MT-143 called it "faint stroke
  ghosts"; the crop shows outline, not text. Crop:
  `residual_p075_t0_x4.png`.

**MT-143's six regions, now.** Four are still over, at the same values:
p088 t0, p075 t2, p075 t3 and p075 t0. Two are no longer over:

| Page | Truth | In MT-143 | Now | Counted ink px | Path | Crop |
|---|---|---|---|---|---|---|
| p064 | t1 | 0.0315 | 0.0000 | 0 | native | `residual_p064_t1_x4.png` |
| p100 | t5 | 0.0250 | 0.0000 | 0 | flat fill (MT-153) | `residual_p100_t5_x4.png` |

**The project region each truth region is paired with** (reading index):
p061 t0 with r0, IoU 0.5035; p088 t0 with r0, IoU 0.979; p075 t0, t2 and t3
with r0, r2 and r3, IoU 1.0 each.

*How it could be wrong:* a cause is a judgement from two crops and three
counts. The counts are measured; "tone", "outline" and "stroke" are what the
crops look like to one reader.

### E-6 Centring of the six balloons MT-154 names (AC-8)

**Method.** Tool `D:\bench\review\mt159\centring.py`, on a scratch copy of
the no-spend project. Each of the six was found in the after run by its
polygon against the region of the same reading index in
`D:\bench\blackjack-v1-ep02-03-mt153-after.mtproj` (read-only), not by
assuming the index. The balloon's white interior is the 4-connected
component of pixels with grey at least 200 on the cleaned page that holds
the most light pixels of the region's polygon, found with `cv2` and not
through `mangatl.typeset.interior`. Its width, height and centre are that
component's bounding box and centroid. "Whole" means the fill of the ring
`bubble_interior` returns covers at least 95 % of it. The block is the one
`_set_blocks` returns with MT-155 PO-10's placeholder English. A balloon
passes at cover of at least 95 %, ring offsets within 2 %, and block offset
within 5 %: MT-154's bounds, not tuned here.

**After** (`centring-after.txt`; reading indices; all six matched at IoU
1.0000 with the same index):

| Balloon | Index in the after run | Found whole | Interior covered | Ring offset, x | Ring offset, y | Block offset, y | Balloon W x H | Result |
|---|---|---|---|---|---|---|---|---|
| p064:1 | r1 | yes | 100.0 % | +0.0 % | +0.0 % | -0.0 % | 104x244 | pass |
| p073:2 | r2 | yes | 100.0 % | +0.0 % | +0.0 % | -0.2 % | 103x187 | pass |
| p075:6 | r6 | yes | 100.0 % | +0.0 % | +0.0 % | +2.8 % | 176x206 | pass |
| p082:1 | r1 | yes | 100.0 % | -0.0 % | +0.1 % | -17.5 % | 262x479 | **fail: block offset -17.5 %** |
| p082:2 | r2 | yes | 100.0 % | -0.0 % | +0.1 % | +32.0 % | 262x479 | **fail: block offset +32.0 %** |
| p092:2 | r2 | yes | 100.0 % | +0.0 % | +0.0 % | +2.4 % | 161x218 | pass |

Pass 4 of 6; found whole 6 of 6.

**Control (AC-8's, DV-4): holds.** The same script, with
`typeset/interior.py` as it was before MT-154 (`git show
553c739:src/mangatl/typeset/interior.py`), reports all six as not found
whole (`centring-before-dv4.txt`): cover 64.9 %, 67.7 %, 43.0 %, 70.3 %,
0.5 % and 39.1 %. So the measure tells the defect from its fix.

**p082:1 and p082:2.** Both regions lie in one balloon, 262x479, and
`bubble_interior` returns that whole balloon for each. MT-155 then sets each
block in its own part of it, so each block is off the whole balloon's
centre. This is the case MT-159 PO-3 foresaw.

*Extra, not an AC-8 figure* (`centring_part.py`, `centring-part.txt`):
against the centre of its own part, p082:1's block is off by -4.0 % of the
part's height and p082:2's by +0.9 %.

*What the two regions are.* p082 r1 and r2 are the two fragment pieces of
one truth balloon, p082 t1 (E-3). The truth document's note on t1 reads
"fragments 2,3 of one balloon merged (long dash continues below)". The OCR
stored `君だー` for r1 and `ー` for r2. So the two blocks are one utterance
detected as two regions, not two utterances sharing a balloon.

**An aside on the same balloon.** On p082's cleaned page a thin vertical
stroke, about 190 px long, is left inside this balloon between r1 and r2
(`centring\5b_p082_r1.png`, `centring\centring_p082_1.png`). It is the
long dash. Its truth region is missed, so the bench's residual measure does
not see it. *Measured at the MT-159 diff review, round 1, read-only on the
stored pages:* the source component is `293 710 3x173`; r1's stored mask
covers 64 px of it and r2's covers 103 px. On the cleaned page the
component is `293 696 3x188`, 15 px longer than the source, with 67 px
inside r1's mask and 92 px inside r2's. So the ink left on the cleaned page
lies inside both masks as well as between them. Its place inside the truth
polygon was read off the crop, not measured.
*Added at the revision:* MT-152 measured a component on this page's source
as `p082 293 710 3x173` (a 173 px line, ring fraction 0.994), left it "not
judged" and put marks longer than `GLYPH_MAX_SIDE_PX` out of its scope.
The review's measurement shows it is this stroke. Why ink is left inside the
two masks is not known here; MT-168 measures it.

**Rule 5b.** Of the 270 included bubble regions of the after run, exactly 6
take MT-154's rule 5b, and they are the same six. Each was looked at
(`centring\5b_*.png`), by the measurer and again by the writer: p064 r1 is
a closed rectangle; p073 r2 is a closed oval; p075 r6 and p092 r2 are
closed by the panel frame where they touch it; p082 r1 and r2 are the one balloon
above, closed by the panel frame on its left and at its foot. **No open
balloon leaking into a plain white panel was found.**

*How it could be wrong:* the reference interior is a threshold at grey 200
on the cleaned page, which is this story's definition and not MT-154's
code. The blocks are set with placeholder English, not the paid run's.

### E-7 Glyph boxes (AC-9)

**Method.** MT-155's DV-4: a `proposed` `Line` per region with PO-10's
placeholder text, `_set_blocks(regions, lines, faces, grey)` per page, and
the count of block pairs on one page with at least one intersecting pair of
glyph boxes. Tool `D:\bench\review\mt159\glyphs.py`, which is MT-155's
scratch `measure.py` with its `--ref` branch disabled.

**After** (`glyphs-after.txt`):

```
mangatl from D:\manga-translator\src\mangatl\__init__.py
pages 46; blocks 270; overflowed 15; block pairs with intersecting glyph boxes: 0
```

**Control (AC-9's, DV-5): holds.** The same script on the same project, with
`src/` as it was before MT-155 (`git archive 0b0e378 src`,
`glyphs-before-dv5.txt`):

```
mangatl from D:\bench/review/mt159/src-0b0e378/src\mangatl\__init__.py
pages 46; blocks 270; overflowed 23; block pairs with intersecting glyph boxes: 4
   p063.jpg 4 5 11
   p066.jpg 6 7 6
   p075.jpg 7 8 15
   p089.jpg 7 8 30
```

Those are the four pairs MT-155 records (reading indices), so the after
count is comparable with the before. Both TSVs are byte-identical to
MT-155's `before.tsv` and `after-ref.tsv`.

*How it could be wrong:* the text is a fixed placeholder. Real English of a
different length sets differently; the 252 proposals of the paid run were
not set and measured.

### E-8 Where the mechanism departed from the Contract

1. **C-5.** The classing script is new, not an adaptation of MT-143's
   `measure.py`. The seed control (E-3) shows it reproduces MT-143's counts.
2. **DV-5.** `python -I` ignores `PYTHONPATH`, so the older `src` was put
   first on `sys.path` inside the script instead. The first output line of
   each run shows which `mangatl` was loaded.
3. **DV-4.** The older `interior.py` was loaded by file path and
   `pipeline.bake.bubble_interior` rebound to it. `shared_parts` stayed the
   tree's.
4. **C-8.** The copied project's database named the no-spend folder as the
   chapter's `source_dir`, and the translate stage reads images from it. On
   the copy only, `source_dir` and `output_dir` were rewritten to the paid
   folder. The no-spend `project.db` has the same sha256 before and after
   the paid run:
   `99ffe05cf5a549907b81dffcbb43ed6eee1e5d4c74edffb21a7331cdc9bc239c`.
5. **DV-7.** Two bullets did not hold as first written. They were reworded
   under MT-159's AM-1, and DV-7 holds as amended (E-2).
6. **A listing.** The measurer's first `ls D:/bench/` printed the names of
   the benchmark chapter's folders. Nothing under them was read, listed or
   passed to a command afterwards.
7. **Another listing.** `D:\bench\review\` holds page images of the
   benchmark chapter, seen by name when the folder was listed. None was
   opened.

## What would have to be true for this to be wrong

- The truth document is wrong about a region. Every verdict on lines 1 and
  2 counts against it, and the three p075 balloons are a case where the
  model and the truth disagree.
- The reading of lines 1 and 2 changes. The user confirmed it on
  2026-11-25. Under any reading that asks for a fall of 83 or less in
  `spurious`, or a rise of 1 or less in `matched` (4 or less on the no-spend
  figure), a verdict would change.
- "Its balloon" in line 5 comes to mean the region's own part. The user
  chose the whole balloon on 2026-11-25. On the other reading p082:1 and
  p082:2 pass on the extra figures in E-6, and the line would be met.
- "Its cause" in line 3 asks for more than what put the ink there. Then
  p075 t3 has no cause named, and the line would not be met.
- A second paid pass marks different regions as art. The paid figures are
  one pass.
- The classing script counts differently from MT-143's on merged regions
  in a way the seed control cannot show, since the seed project has no
  merged region.
- A slip can occur on a page with fewer than two compared lines. The slip
  count cannot see p105, p071, p072, p088, p096 or p108.

## What was not checked

- **Line 7,** the live benchmark run. Not made.
- **The benchmark chapter,** in any form.
- **`neighbours` mode.** The slip the epic records was seen there.
- **Translation quality,** and whether any of the 252 proposals is in the
  wrong balloon in a way the slip count's rule (identical English from
  different Japanese, on neighbours) does not catch.
- **The glossary and consistency passes,** and a full `mangatl-run` with
  translation. Only the translate stage ran.
- **Residual ink on the three p075 balloons in the paid copy.** They are
  missed there, so the bench does not measure them. The cleaned pages are
  the same as the no-spend run's.
- **Residual ink on any missed truth region,** on either run: 15 regions on
  the no-spend run. The dash stroke on p082 is one case found by eye.
- **The dash stroke on p082,** by pixel, in this audit's own work. It was
  seen in two crops; the figures in E-6 are the diff review's. Why ink is
  left inside r1's and r2's masks was not looked into.
- **Why four art-text regions were not marked** (p070 r1, r2; p089 r5; p106
  r0), and why three balloons were. The model's answers were not analysed.
- **The epic's "the review screen says so" clause** (EPIC-13, "Goal", note
  of 2026-11-25). It has no done-when line. The paid run gives one real
  figure beside it: 2 lines marked `misaligned` on 46 pages, both on p105.
  The review screen was not opened.
- **Where the four art-text regions fewer than the seed run went.** Counted
  per page, not traced by polygon.
- **The baked pages.** Centring and glyph boxes were measured on blocks set
  by a script with placeholder English, not on output images.
- **A second machine.** Every run is this one's.

## Spike code

All of it is in `D:\bench\review\mt159\`, outside the repository. It is
**unreviewed and not production code**, and nothing in it was written
test-first. A later story may take the *methods* restated in E-3, E-5, E-6
and E-7, which are precise enough to run again, and must re-derive every
count. It takes no constant from here: the only numbers are MT-143's 50 %
rules, MT-154's bounds and `RESIDUAL_INK_MAX`, each owned elsewhere.

| Script | What it does | Run as |
|---|---|---|
| `classify.py` | AC-3's classes, fragmented balloons, missed list | `uv run --no-sync python -I`, project opened read-only |
| `residual.py`, `zoom.py` | AC-4's counts per region and the crops | same |
| `centring.py`, `centring_part.py` | AC-8's table; the extra per-part figures | same, on a scratch copy under `proj\` |
| `glyphs.py` | AC-9's count; optional older `src` first on `sys.path` | same |
| `paid_prepare.py`, `paid_run.py`, `paid_store.py` | the paid copy's checks, the translate driver, the store counts | same; `paid_run.py` makes paid calls and is not to be re-run without the user asking |
| `writer_cmp.py` | compares the two projects' regions and cleaned pages | same, read-only |
| `schema.py` | prints the store's tables | same |

Also there: `old-interior\interior_553c739.py` and `src-0b0e378\`, the older
code the two controls load; and every output file named in "Evidence".

Known to be rough: `centring.py`'s reference interior is a fixed grey
threshold; `classify.py` was checked against MT-143's totals and its
18-balloon list, not region by region against MT-143's piece lists.

## Stories filed

Three, on 2026-11-25, from the candidates the user accepted. Each is
`phase: PLANNED` in EPIC-13, and none depends on MT-159.

| Id | Title | Type | From |
|---|---|---|---|
| MT-166 | Why twelve fragmented balloons on the development set are still split, and whether a rule can join them | spike | candidate 1; E-3, lines 1 and 2 |
| MT-167 | An art mark on text inside a closed balloon is not applied, and the balloon stays in review | feature | candidate 3; E-2 |
| MT-168 | A long dash the erase mask covers at both ends is erased whole | feature | candidate 4; E-6 |

Candidates 2, 5 and 6 were declined and are not filed.
