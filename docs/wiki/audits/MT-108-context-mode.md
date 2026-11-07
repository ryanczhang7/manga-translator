# Rolling vs neighbour context on the benchmark chapter - MT-108

Spike MT-108 (EPIC-09 PO-3). Written by the orchestrator (`lead-po`, Claude
Opus 5.5, `claude-opus-5-5`) on 2026-11-07. The decision rule was committed
in the story before either run was made (commit `096ef05`, refined at
PLANNED in `3a23996`); the runs were made on `505752d`.

## Method

**Chapter.** *Give My Regards to Black Jack* (ブラックジャックによろしく), 佐藤秀峰,
vol. 1, Ep.01 "Night of the Intern": **56 pages**, 1414x2000 JPEGs extracted
byte-for-byte from the author's own free distribution (Sato Manga Works,
`https://densho810.com/free/`, `001bj.zip`; reuse permitted without prior
consent). Never used in development (`development_use: false`).
Ground truth: **264 regions**, sha256
`2792f99e2137c408efe6c0dcde906d1a87290ec4810b74d39919b04305377c81`
(identical for both copies). Seeded from the detector (326), corrected by a
Claude review pass (+6 missed narration/balloons, -68 sound effects, drawn
signs and fragments, 14 refit), then confirmed by the user. Text drawn into
the art (sound effects, scenery signs) is out, per `product-brief.md` §5.

**Meaning reference.** The official English edition of the same volume from
the same distributor (`enbj001.zip`), page-aligned with the Japanese.

**Review rule (PO-1).** The reviewer does not read Japanese. A line is kept
as-is only if it says what the official line for that bubble says (meaning,
not wording) **and** reads as good English in the reviewer's own judgement;
otherwise it is edited to what the reviewer would publish. Unresolvable
disagreements with the official edition are edited to the official meaning
and listed as meaning disputes.

**Blind runs (PO-2, PO-3).** Two copies, `blackjack-v1-ep01-A` and `-B`;
modes drawn at random into a map the reviewer did not open until both reviews
were done; the run script masked the mode in everything it printed. Copy A
was reviewed first.

| | A | B |
|---|---|---|
| Mode (revealed after review) | `neighbours` | `rolling` |
| Commit | `505752d` | `505752d` |
| Command | `MANGATL_CONTEXT_MODE=neighbours uv run mangatl-run --models packaging/models D:\bench\blackjack-v1-ep01-A` | `MANGATL_CONTEXT_MODE=rolling uv run mangatl-run --models packaging/models D:\bench\blackjack-v1-ep01-B` |
| Then | `uv run python -m mangatl.bench D:\bench\blackjack-v1-ep01-A` | `uv run python -m mangatl.bench D:\bench\blackjack-v1-ep01-B` |
| Run time | 11:39:24 - 11:50:28 | 11:53:23 - 12:07:43 |
| Glossary pre-pass ran | yes, **7** terms | yes, **9** terms |
| Consistency pass | 1 line corrected | 1 line corrected |

Provider Gemini (the one key set). One run per mode: that is what the budget
allows, so there is no variance estimate - the glossary term count alone
differed between two runs over identical Japanese.

## Results

Bench report, after the user's review was rendered, verbatim:

```
A (neighbours)
S1b chapter acceptance      92.4%  accepted 244 / ground truth 264   <- headline
S1a translation acceptance  74.8%  accepted 244 / proposed 326
recall                      92.4%  matched 244 / ground truth 264
spurious                    82
S2 FAIL: recall, residual ink
S5 chapter cost  $0.6138  48 priced calls
per page         $0.0110  56 pages

B (rolling)
S1b chapter acceptance      92.4%  accepted 244 / ground truth 264   <- headline
S1a translation acceptance  74.8%  accepted 244 / proposed 326
recall                      92.4%  matched 244 / ground truth 264
spurious                    82
S2 FAIL: recall, residual ink
S5 chapter cost  $0.6762  48 priced calls
per page         $0.0121  56 pages
```

Ledger: **48 priced calls** in each run. Both S5 totals are under the $2.00
ceiling; no page was refused by the guard. Meaning disputes: **0** in either
(none were listed). Cost is about twice the $0.0057/page MT-080 measured; the
cause (glossary pre-pass, consistency pass, the context block) was not
measured.

**What S1b does and does not say here.** The reviewer edited no matched line
in either copy (`final_en == proposed_en` for all 326 lines in both), so S1b
equals recall in both and is set entirely by detection, which does not depend
on the mode. The tie is real but it is a tie of the *review*, not evidence
that the two modes translate equally well: 217 of 326 proposals differ in
wording between the copies. It must not be quoted as the product's S1 result:
lines below that a careful reader would edit (a wrong dose, a wrong name
reading) were kept.

### Lines where the modes differ (AC-4)

No line differs in **acceptance** - every matched line was accepted in both
copies. The renderings do differ; the clearest, from the user's page pairs,
with the Japanese and both proposals from the project stores:

1. `p018.jpg` region 5, `ラクテック全開ハイドロコーン１００ミリ側管注しろ！！`
   - A: "Open up the lactec and give him 100 mil of hydrocone by IV push!!"
   - B: "Open the lactec wide and give 1000 mg of hydrocortisone via side tube!!"
   - The Japanese says **100**; B's 1000 is a tenfold error on a dose.
2. 永大 (the hero's university, read *Eidai*), nine lines on p012-p055
   - A: "Eiroku U" / "an Eiroku graduate" (from the full name, 永禄大学).
   - B: "Eadai", consistently - a wrong reading, held across the chapter.
3. `p017.jpg` regions 4-7, `っ` / `いてーよー！！` / `いてーよー！！` / `急ぐぞ！！こっから先は戦場だ！！`
   - A: "WEE" / "WEE" / "It hurts!!" / "It hurts!!" - the lines slid one region
     down; "Hurry!! From here on out it's a battlefield!!" landed in the wrong
     balloon at a tiny size and the shout balloon reads "It hurts!!".
   - B: each dialogue line in its own balloon ("It huuurts!!" twice,
     "Hurry!! It's a battlefield from here on out!!", "Yes, sir!!"); the
     sound-effect fragment `っ` became "WEE-WOO WEE-WOO".
4. `p023.jpg` regions 8-9, `点` / `一律一１０円だ` (one balloon detected as two)
   - A: "One point" + "is a flat rate of 10 yen." - typeset on top of each
     other.
   - B: "It's a flat 10 yen per point." - one line, clean.

**Control** (a rolling-mode line whose acceptance depended on the previous
page's English - a sentence continued across a page break): **looked for, not
found.** No page's first line opens with a continuation (`…`, `・・`, `...`)
in either the Japanese or B's English, and the reviewer flagged none.

### The reviewer's reading (AC-5)

In the user's words: "I don't dislike either version. Whichever is cheaper
is good for me." Neither mode read better end to end. The edits the user did
make were not to wording but to **detection**: deleting duplicate fragment
regions (one balloon detected whole and in pieces). The problems the user
reported are mode-independent and are recorded below for the follow-up, not
for this decision:

- **Fragments.** One balloon detected as several pieces translates each piece
  separately and typesets them on top of each other (p004 in B, p016, p023 in
  A, p053 in both). Where only fragments are found, small pieces' Japanese is
  left uncleaned (p053: って, て).
- **Duplicates.** One balloon detected whole and as pieces (p004).
- **Sound effects and drawn signs proposed anyway** (82 spurious), some
  translated ("WEE-WOO", "gachi gachi (rattle rattle)") and typeset over the
  art; a drawn sign was replaced with "Emergency Entrance" over leftover
  Japanese (p016).
- **Cleaning residue.** Japanese left visible next to typeset English (p016
  under the sign and beside "Seido Hospital"; p023 合計 / 14330円), and faint
  ghosts of the erased Japanese in large balloons (p004).
- **Typesetting.** Text far too small for its balloon where a balloon held
  two regions (p011 narration, p016, p018 orders, p017 in A); text set at the
  top of a large balloon rather than centred (p004).

## Decided

- **D-1 - the synchronous default becomes `neighbours`.** The rule: neighbours
  unless its S1b is more than 2.0 points below rolling's. S1b is 92.4% in
  both, a difference of **0.0 points**. The figures differ by less than one
  point, so **the measurement does not separate the modes**, and `neighbours`
  is chosen for its order independence under the rule as written. It is also
  the cheaper of the two runs ($0.6138 against $0.6762, one run each), which
  is the user's stated preference, and the mode the batch path already
  forces. MT-109 is to set `neighbours` as the default.
- **D-2 - the batch path's forced `neighbours` is within the bar.** It is the
  same mode at the same S1b, so forcing it costs nothing measurable here.
