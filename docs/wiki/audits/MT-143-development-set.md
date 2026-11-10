# A development set outside the benchmark chapter - MT-143

Spike MT-143 (EPIC-13 enabler). Written by the orchestrator (`lead-po`; Claude
Opus 5.5, `claude-opus-5-5`) on 2026-11-10. Every EPIC-13 story measures its
before/after on this set, never on the benchmark chapter (EPIC-13 "Evidence":
chapter 1 is diagnosis only).

## The set

**Pages.** *Give My Regards to Black Jack*, vol. 1, from the same free
distribution as the benchmark (`D:\bench\all-jp`, 1414x2000, official English
page-aligned in `D:\bench\all-en`). Episode boundaries were found from the
title pages on a contact sheet of p055-p134:

| Episode | Title page | Pages | Count |
|---|---|---|---|
| Ep.01 (the benchmark) | p003 | p003-p058 | 56 |
| *(blank separators)* | | p059-p060 | |
| **Ep.02** 「うなぎとゴッドハンド」 | p062 (cold open from p061) | **p061-p084** | **24** |
| *(blank separators)* | | p085-p086 | |
| **Ep.03** 「75歳の値段」 | p088 (cold open from p087) | **p087-p108** | **22** |

Ep.02 is under 30 pages, so Ep.03 was added (the story's rule): **46 pages**,
copied byte-for-byte with their original file names into
`D:\bench\blackjack-v1-ep02-03\`. Outside the repo; never committed.

**Detector run.** `uv run mangatl-run --no-translate --models packaging/models
D:\bench\blackjack-v1-ep02-03` at commit
**`723b8ec3c9788ddf20a6a75dd7034d7481fb0cc5`** (branch
`story/MT-143-a-development-set-outside-the-benchmark`, = `main` after MT-141
plus MT-141's close), 2026-11-09 07:44:52Z - 07:46:44Z, exit 0: "46 pages
written ...; 340 regions left empty". Log: `D:\bench\review\mt143-detect.log`.

**Ground truth.** `D:\bench\blackjack-v1-ep02-03.truth.json`,
`development_use: true`, **253 regions**, sha256

    68161def30c014abd0be260e29b5fa33225a1e125c70adc47a514878c942bc10

1. Seeded by `uv run python -m mangatl.bench.seed D:\bench\blackjack-v1-ep02-03`
   (340 regions, all `source: seed`); `development_use` set to `true`.
2. A Claude review pass under the benchmark truth's rules, unchanged (MT-108):
   typeset text in or out of balloons is in; hand-drawn sound effects and signs
   drawn into the scenery are out (`product-brief.md` §5); a balloon detected in
   pieces, or whole and in pieces, is one region refit to the balloon's text; a
   missed typeset balloon is added. Four reviewers in parallel, one per batch of
   11-12 pages, over 100-px grid overlays, the originals and the official
   English (for which Japanese an English reader got as a balloon). Result:
   **-90** removed, **17** refit, **+3** added (p062's episode title; one-
   ellipsis balloons on p087 and p096), and 29 regions re-kinded `box`
   (narration and loose text). The orchestrator spot-checked p064, p065, p084
   and p105.
3. The user looked at all 46 pages with the corrected regions drawn on them
   (`D:\bench\review\mt143-confirm\`), with the least certain calls listed
   (p075 chewing sounds kept; p066 ちゅううう, p070 スー/モゴ, p097 ピーッ removed
   as SFX; p089's 第一外科 door sign removed; p065 and p104 merged; p090's
   joined balloon kept as two lobes; p084's narration as two columns), and
   answered **"All correct"** on 2026-11-10. Every region is now `source:
   human` with `note: ... confirmed by the user 2026-11-10`.
4. `uv run python -m mangatl.bench.truth D:\bench\blackjack-v1-ep02-03`:
   `ok: 46 pages, 253 regions`, no warning.

Kept beside it in `D:\bench\review\`: `mt143-truth.seed-draft.json`,
`mt143-edits-{1..4}.json`, `mt143-truth.claude-pass.json`,
`mt143-truth.confirmed.json`.

## The seed run, measured (AC-2)

`uv run python -m mangatl.bench D:\bench\blackjack-v1-ep02-03 --development`
(MT-142), verbatim except the per-region residual list, which is cut to the
regions over the limit (the full output, 240 lines, is
`D:\bench\review\mt143-bench.txt`). No translation ran (it is a paid run and
the user did not ask for one), so the S1 lines read 0 % by construction and
are reported only because the command prints them.

```
DEVELOPMENT SET - not a benchmark result
S1b chapter acceptance      0.0%  accepted 0 / ground truth 253   <- headline  [development]
S1a translation acceptance  0.0%  accepted 0 / proposed 340  [development]
recall                      92.5%  matched 234 / ground truth 253
spurious                    106
identity S1b = S1a x recall does not hold (spurious present)
recall        92.5%  matched 234 / ground truth 253
missed        page 0 region 0, page 1 region 2, page 2 region 4, page 3 region 0, page 4 region 1, page 16 region 0, page 21 region 1, page 21 region 2, page 23 region 0, page 23 region 1, page 24 region 2, page 26 region 6, page 27 region 0, page 33 region 1, page 36 region 6, page 41 region 0, page 42 region 0, page 42 region 1, page 45 region 0
spurious      106
residual ink  worst 0.0991 / max 0.0100
  ... (228 regions at or under 0.0100 omitted)
  page 3 region 1  0.0315
  page 14 region 0  0.0202
  page 14 region 2  0.0826
  page 14 region 3  0.0418
  page 25 region 0  0.0991
  page 37 region 5  0.0250
S2 FAIL: recall, residual ink  [development]
S5 chapter cost  $—  no priced calls  [development]
per page         $—  46 pages
```

(Page ordinals map to files as ordinal 0 = p061 ... 23 = p084, 24 = p087 ...
45 = p108. The two `$—` were written to the redirected file as the single
cp1252 byte `0x97`, not UTF-8; shown here decoded.)

## The counts each EPIC-13 story reads (AC-3)

Measured on 2026-11-10 by one script run over both chapters, so the two
columns are comparable: `D:\bench\review\mt143-counts\measure.py CHAPTER
OUT.json` then `analyze.py OUT.json`, run from the repo with `uv run python
-I`. Per-item listings in full: `summary_dev.md`, `summary_bench.md` in the
same folder. The script reuses the repo's own functions: `bench.matching`
(`polygon_mask`, `decode_mask`, `iou`, `match_regions`, IoU 0.5),
`bench.residual` (`ink_fraction`, `page_luma`, `RESIDUAL_INK_MAX`),
`detect.postprocess` and `detect.columns` (`merge_columns`, `_extent`,
`_fence_of`), `clean.mask.erase_mask`, `clean.inpaint.MIN_CONTEXT_PX`,
`typeset.interior.bubble_interior`. The orchestrator re-derived two figures
independently (the long-side count, and the residual list against the CLI run
above); both agree.

"Seed" below means the detector's regions as stored in the project (340 on the
development set, 326 on the benchmark).

### 1. Fragmented balloons (MT-144, MT-145)

**Method.** A *piece* is a seed region whose IoU with every truth region on its
page is below 0.5 (`iou(decode_mask(seed.mask), polygon_mask(truth))`, the
bench's matching) and whose polygon raster lies ≥ 50 % inside one truth
region's raster; it is assigned to the truth region holding the largest share.
A *fragmented balloon* is a truth region holding ≥ 1 piece - a *duplicate* if
`match_regions` also pairs it with a whole seed, *missed* otherwise. Measuring
containment on the seed mask instead of its polygon, or "unmatched" as "not
paired one-to-one", gives identical results on both chapters.

| | Development | Benchmark |
|---|---|---|
| Fragmented balloons | **18** on 14 pages | 15 on 11 pages |
| Pieces | **89** | 52 |
| ... duplicate (whole + pieces) / missed | 2 / 16 | 1 / 14 |
| Worst balloon | p084 truth 0 (narration `box`): 18 pieces | p004 truth 0: 12 pieces |

Two big-font narration pages - **p084 (30 pieces) and p105 (16)** - hold 46 of
the 89: each large glyph came back as its own region. Without them the
development set has 14 balloons and 43 pieces.

### 2. Art-text regions (MT-146, MT-147, MT-148)

**Method.** A seed region whose polygon raster lies ≥ 50 % outside the union of
the page's truth rasters. Each was cropped and looked at.

| | Development | Benchmark |
|---|---|---|
| Art-text regions | **17** on 8 pages | 30 on 14 pages |
| ... SFX / drawn sign / other | 11 / 2 / 4 | 19 / 7 / 4 |

Every one, in both chapters, is `kind: bubble`, lies 100 % outside the truth,
and matches nothing (IoU 0.0). Many are SFX drawn inside balloon-like shapes
(プルル phone rings on p061, モゴ on p070). The two development signs are the
two halves of p089's 第一外科 door sign.

### 3. Gaps between pieces, and MT-145's negative

**Method.** Extents are `columns._extent(stored mask)`; gap and overlap are
`columns.py`'s formulas. A pair is *along* when the two share a pixel column
(stacked in one column; gap = vertical gap), *across* when they share no
column but a row (side by side; gap = horizontal gap, `columns.py`'s own gap),
*diagonal* otherwise. Positive pairs are two pieces of one truth balloon,
restricted to *adjacent* pairs (no third piece of that balloon between them),
since merging is transitive. Negative pairs are two seeds assigned to
*different* truth regions that lie in the **same fence box**. Fence boxes are
not stored, so they were recomputed by running the pipeline's own chain
(`integer_boxes(decode_boxes(...))`, `detect/page.py`) over every page with the
packaged model on CPU. The recomputation reproduces the store: the same region
count on every page, and every stored mask has a recomputed mask at IoU ≥
0.961 (development) and ≥ 0.982 (benchmark).

| | Development | Benchmark |
|---|---|---|
| Positive pairs in one fence box | 361 of 361 | 112 of 112 |
| Adjacent along gaps | n=65; min 0, median 5, max 116 | n=34; min 0, median 5, max 23 |
| ... of which ≤ 11 px / ≤ 17 px / ≤ 29 px | 48 / 57 / 61 | - |
| Adjacent across gaps | 12, 13, 14, 14, 20, 25, 38 | 14, 17, 18, 25, 27, 63 |
| Negative pairs, along | 1 (p075 seeds 2/3, gap **0**, column overlap 0.156) | 1 (p056, gap 60) |
| Negative pairs, across | 7, gaps 37-71 (median 53) | 7, gaps 33-108 (median 76) |
| Negative pairs, diagonal | 3 | 0 |
| Nearest different-balloon pair in one fence | along 0, across 37 | along 60, across 33 |

Development along-gap histogram (2-px bins, adjacent pairs): 0-1: 8, 2-3: 18,
4-5: 7, 6-7: 9, 8-9: 4, 10-11: 2, 12-13: 6, 14-15: 2, 16-17: 3, 24-25: 1,
26-27: 1, 28-29: 2, 58-59: 1, 116-117: 1. The tail is p082 2/3 (116 px) and
the big-font narration of p105 and p064.

Two facts for the stories that read this table:

- **The fence never blocks a merge the truth wants** - every same-balloon pair
  shares a fence box on both chapters. Fragmentation comes entirely from the
  two geometric clauses of `merge_columns`: stacked pieces have 0 % overlap
  along the run, and adjacent columns sit 12-38 px apart against
  `COLUMN_MAX_GAP_PX = 12`.
- **There is one hard negative**, on the development set only: p075 seeds 2/3
  are two different balloons in one fence whose extents touch (gap 0 both
  ways). An along rule that accepts gap 0 at a small column overlap merges
  them. Every other negative is ≥ 33 px apart.
- **Selection bias**: the store holds `merge_columns`' *output*, so no
  same-fence pair with gap ≤ 12 and overlap ≥ 0.5 can appear in either list.
  The absence of across gaps under 12 px is the current rule's doing, not a
  property of the pages.

### 4. Truth regions with a long side over 448 px (MT-151)

**Method.** max(width, height) of the truth polygon's extent > 448.

| | Development | Benchmark |
|---|---|---|
| Regions | **8** | 10 |
| ... matched by a whole seed | 1 (p095 truth 5) | 3 |

Development: p061 t0 (74x606), p062 t2 (696x164, the episode title), p064 t0
(259x608), p084 t0 (194x777), p084 t1 (99x769), p095 t5 (191x521), p105 t0
(161x816), p105 t1 (151x1374). Seven of the eight are fragmented (item 1).

### 5. Regions over `RESIDUAL_INK_MAX` = 0.0100

**Method.** `ink_fraction(page_luma(cleaned page), polygon_mask(truth))` for
every matched truth region, as `measure_residual` does - equal, region for
region and value for value, to the CLI's list. Each was cropped (original and
cleaned) and looked at. Whether the counted ink lies inside the erase mask, and
whether it is unchanged from the source, was measured per pixel. The inpainter
path is `clean/inpaint.py`'s test per erase component: bbox + 2 x
`MIN_CONTEXT_PX` (64) ≤ 512 on both sides is native; otherwise downscale.

| Page | Truth | Value | Cause | Ink inside the erase mask | Path |
|---|---|---|---|---|---|
| p088 | 0 | 0.0991 | Art under the text: the episode title sits on screentone with vertical lines, which the inpainter repainted | 4120 of 4181 | native |
| p075 | 2 | 0.0826 | The inpainter redrew glyph strokes inside a fully masked narrow balloon | 189 of 189 | native |
| p075 | 3 | 0.0418 | Faint stroke ghost, same narrow balloon pattern | 84 of 84 | native |
| p064 | 1 | 0.0315 | A drawn leader line ending under 7月 continued into the erased area | 57 of 57 | native |
| p100 | 5 | 0.0250 | A dark blot painted at the top of the つまり…… column | 166 of 166 | native |
| p075 | 0 | 0.0202 | Faint stroke ghosts, same narrow balloon pattern | 47 of 47 | native |

| | Development | Benchmark |
|---|---|---|
| Over the limit | **6** on 4 pages, worst 0.0991 | 7 on 7 pages, worst 0.4352 |
| ... on the downscale path | **0** | 2 (p011 t0, the 0.4352 smear; p008 t1, one of three components) |
| ... half-erased where a fence cut a glyph line | **0** | 0 (see AC-4) |

In 12 of the 13 regions across both chapters the counted ink lies wholly or
almost wholly inside the erase mask and almost none of it is unchanged from
the source: **the inpainter painted it; the text was not left behind.** The
exception is benchmark p008 t1, art left unerased.

### 6. Pairs of regions sharing one `bubble_interior` (MT-155)

**Method.** `bubble_interior(grey cleaned page, region.polygon, region.kind)`
for every seed region, called as `pipeline/bake.py` `_set_blocks` calls it -
on the **cleaned** page in grey, not the original (the original gives the same
result). A pair on one page counts when the rings are identical or their fills
overlap at IoU ≥ 0.9. The bake only calls it for regions with a non-empty line;
this counts every seed region.

| | Development | Benchmark |
|---|---|---|
| Pairs sharing an interior | **1** (p075 seeds 7/8, truth 7 and 8, IoU 0.9975) | 2 (p016 1/3, p027 5/6, identical rings) |

Pieces of *one* balloon do not share an interior: their interiors overlap at
median IoU 0.17 (development, 111 overlapping pairs; max 0.68) - each piece
finds its own smaller interior. The shared-interior case is two different
truth regions sitting in one drawn balloon.

## Development against the benchmark (AC-4)

The benchmark figures are EPIC-13's "Evidence" table, with this script's
recount beside them where they differ.

| Defect | EPIC-13 (benchmark) | This script on the benchmark | Development | Same defect at a comparable rate? | Story |
|---|---|---|---|---|---|
| Fragmented balloons / pieces | 15 on 12 pages / 53 | 15 on 11 / 52 | 18 on 14 / 89 | **Yes**, higher (two big-font narration pages give 46 pieces) | MT-144, MT-145 |
| Missed because fragmented | 7 of 20 missed | 14 | 16 of 19 missed | Yes | MT-144, MT-145 |
| Duplicates (whole + pieces) | p008, p004, p053 | 1 | 2 | Yes, rare in both | MT-144 |
| Different-balloon pairs in one fence (MT-145's negative) | not counted | 8 | 11 (one at gap 0) | **Yes**, and harder: p075's touching pair has no benchmark counterpart | MT-145 |
| Art-text regions | 30 on 13 pages | 30 on 14 | 17 on 8 | **Yes**, at about half the rate per page | MT-146..MT-148 |
| Truth regions, long side > 448 | 10 | 10 | 8 | Yes | MT-151 |
| Residual ink over the limit | 7 | 7 | 6 | Yes in count, **not in cause** (below) | MT-151..MT-153 |
| ... on the downscale path | p011, p008 | 2 | **0** | **No** | MT-151 |
| ... half-erased where a fence cut a glyph | p023 (`合計1433点` / `14330円`) | 0 | **0** | **No** | MT-152 |
| ... ghosts of erased glyphs on flat paper | p004 (S2 cannot see it) | not measurable by S2 | not measured | **Unknown**: S2's metric cannot see a ghost, and no count here can | MT-153 |
| Shared `bubble_interior` pairs | p011, p016, p017, p018, p023 (by eye) | 2 | 1 | Yes, but thin | MT-155 |
| Text at the top of a large balloon | p004 | not counted | not counted | not measured here | MT-154 |
| Line slips, number mismatches | copy A p017; p018 dose | need a translation run | need a translation run | **not measured**: no translation ran | MT-150, MT-156 |

**Defects that do not occur on the development set, and the stories that
therefore lack a development before/after:**

- **MT-151** (a region taller than the inpainter window is cleaned natively):
  no development region takes the downscale path, so there is no residual-ink
  failure for it to remove. The development set does have 8 truth regions
  over 448 px, so MT-151 can show its regions now take the native path, but
  not a residual-ink improvement.
- **MT-152** (a glyph the erase mask cuts is erased whole): no region on either
  chapter is half-erased by a fence edge under this measurement; every
  residual truth polygon is ≥ 99 % inside the erase mask. Why this count does
  not see EPIC-13's p023 example (`合計1433点` / `14330円`) is not known. MT-152
  has no development before/after as measured here.
- **MT-153** (no ghost on flat paper): unmeasurable by S2 on either chapter,
  as EPIC-13 already says; it needs its own measure.
- **MT-154, MT-150, MT-156**: not counted by this spike (MT-154's "set at the
  top" is not among AC-3's counts; MT-150 and MT-156 need a paid translation
  run, which the user has not asked for).

**Residual ink differs in kind.** The six development regions over the limit
are the inpainter painting marks (repainted tone, redrawn strokes, a blot, an
extended leader line), not text left behind and not the downscale smear. A
residual-ink before/after on the development set therefore measures LaMa's
fill on small native components, which is not what MT-151 or MT-152 change.

## What this spike did not do

- No fix, and no threshold derived. The counts are the before figures.
- No translation run (paid; not asked for). The S1 lines above are 0 % by
  construction.
- The benchmark recount (15 on 11 pages / 52 pieces against EPIC-13's 15 on 12
  / 53) is not reconciled: possibly the benchmark truth was confirmed after
  EPIC-13 counted, or the containment rule differed. The cause is not known.
- The CPU recomputation of the fence boxes is not bit-identical to the stored
  detection (88 development masks differ at pixel level, all at IoU ≥ 0.961).
