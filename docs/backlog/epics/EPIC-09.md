---
id: EPIC-09
title: A whole volume as one Gemini batch, then a consistency pass that returns only corrections
status: todo
stories: [MT-101, MT-102, MT-103, MT-104, MT-105, MT-106, MT-107, MT-108, MT-109, MT-110, MT-111, MT-112, MT-113, MT-114, MT-115, MT-116]
---

*Added 2026-10-28 by lead-po on Claude Fable 5.1, from the user's request:
translate a whole volume as one Gemini batch, then run a consistency pass
that returns only corrections. The product decisions it rests on are the
user's, dated 2026-10-28, and are recorded as PO-1 to PO-7 below. Two of
them relax constraints the architecture calls budget constraints rather than
tuning knobs - `architecture.md` D5 (one LLM call per page) and
`translate/prompt.py`'s docstring ("two passes per page costs $2.29 against a
$2.00 ceiling ... goes back to the user"). They went back to the user, and
the user asked for this; D5 carries the amendment.*

## Goal

A user with a 200-page volume and a Gemini key presses Start once, pays the
batch rate for every page, closes the app if they like, and comes back to a
translated volume whose names, honorifics and recurring phrases are rendered
the same way on page 190 as on page 3. After the pages are in, one text-only
pass over the whole volume returns the lines it would change - and only
those - with a reason each, and those corrections are visible in the review.
Every call, batch or not, is priced into the same ledger and held under the
same guard, and the guard judges the whole batch **before** it is submitted
(D6).

## Why now

The user's real observation is ~$20 for ~200 pages on the per-page path, and
the unverified figures (coordinator's, from `cost-model.awk` tokens x Gemini
rates, 200 pages) are: per-page today ~$5.10; batch ~$3.10; batch plus a
corrections-only pass ~$3.60; batch plus a full-rewrite pass ~$5.50. Measured
costs may be ~4x those. Two consequences shape the epic: the batch discount
is worth more than any prompt tuning, and **a consistency pass that returns
full text would eat the whole saving**, which is why "corrections only" is a
hard constraint (PO-6) and not a preference.

Consistency across a volume also needs the glossary fixed *before* the pages
are translated, because a batch has no page order to accumulate it along
(PO-2), and needs a page's context to depend on nothing another page's
translation produced (PO-3). Both are improvements the per-page path can take
on their own, which is why they are stories here and not folded into the
batch.

## Decisions (the user's, 2026-10-28)

- **PO-1** - D5's "one LLM call per page" becomes "one request per page,
  submitted together as one batch per volume". Lost under D5 was "one call per
  chapter" because a single failure loses twenty pages of spend; a batch is
  not that - each request succeeds or fails on its own and is billed on its
  own. The 1,568 px cap, the thinking level and the model are **unchanged**.
- **PO-2** - The glossary is proposed once, up front, by one text-only call
  over every page's local-OCR Japanese, and is then fixed for every page. The
  per-page response schema stops carrying `glossary`; a page only marks terms
  seen. Today's accumulation (`pipeline/continuity.py`,
  `translate_stage._update_glossary`) is replaced, not kept beside it.
- **PO-3** - A page's context block carries the previous and next pages'
  **Japanese OCR**, not the previous page's proposed English, so no request
  depends on another's result. This is the only context a batch can use.
  Whether it also becomes the **synchronous** default is decided by a
  measurement (MT-107) that can come out either way; until then the
  synchronous default stays `rolling`.
- **PO-4** - Batch calls are priced at Gemini's batch rate from a rate row of
  their own; `RATE_TABLE_VERSION` bumps; every ledger row says which tier
  priced it, so the ledger reconciles against the bill.
- **PO-5** - The budget guard runs **once on the whole batch's projection
  before submission**; a refused batch submits nothing and spends nothing.
  Collected pages are ledgered one row per page, exactly as per-page calls are.
- **PO-6** - The consistency pass is text-only, one request per chapter
  (prompts stay under the 200k-token tier), and its schema returns only
  `{page, reading_index, corrected_en, reason}` for lines it changes - never
  the full text. A response that returns a line unchanged is counted as a
  defect of the pass, not applied.
- **PO-7** - Corrections land on lines the user has **not** touched (`status
  == "proposed"`), as a new `proposed_en`, with the previous text and the
  reason kept in a `correction` row. Accepted, edited and reverted lines are
  left alone. **Open question Q-2** below: apply (as here) or show as
  suggestions the user accepts.

## Open questions for the user

- **Q-1** - MT-101's live probe (one tiny batch) and MT-107's benchmark runs
  need the user's key and the held-out benchmark chapter; the user runs them
  and pastes the results, as MT-080 did.
- **Q-2** - Corrections: applied to untouched proposals (PO-7, assumed) or
  presented as suggestions beside the proposal? Suggestions need a review
  surface this epic has not planned; MT-116 is cut either way after the answer.
- **Q-3** - In the window, Start on Gemini submits a **batch** (assumed - it
  is what the user asked for); the synchronous per-page run stays reachable
  from `mangatl-run --sync`. Confirm, or Start asks which.
- **Q-4** - The consistency pass itself through the Batch API: possible,
  deferred; MT-115 runs it synchronously and the saving is 50% of ~$0.50.
- **Q-5** - MT-108's decision rule (neighbours becomes the synchronous
  default unless its S1b is more than two points below rolling's) is the PO's
  proposal; the user may set a different bar before the spike runs.

## Done when

With `GEMINI_API_KEY` set and a volume folder open, Start projects the whole
batch against the ceiling, refuses or submits it in one step, shows a waiting
state that survives the app being closed and reopened, collects the finished
batch into the same project the per-page path writes, with one ledger row per
page at the batch rate, and then runs the consistency pass, after which the
review shows which lines it changed and why. `python -m mangatl.bench.cost`
reports the volume's cost from those rows. The audit documents of MT-101 and
MT-107 exist, each with a `## Decided` section the implementing stories cite.

## Stories

- **MT-101** (spike) - Gemini Batch API facts from Google's current docs plus
  one live probe: the discount, structured output and thinking config in
  batch, caching in batch, turnaround, the >200k-token tier. `## Decided`
  fixes the numbers MT-102 and MT-109 read out.
- **MT-102** - batch rates in the rate table: a pricing tier on `price`, a
  Gemini batch row, `RATE_TABLE_VERSION` bump, `CostRecord.pricing`.
- **MT-103** - schema v8: what the store needs for this epic, in one
  migration - a chapter-level ledger row (nullable `page_id`), the pricing
  tier on `llm_call`, a `batch_job` table, a `correction` table.
- **MT-104** - the glossary pre-pass call: prompt, schema, parse and Gemini
  adapter for one text-only request over every page's Japanese.
- **MT-105** - the run proposes the glossary once, before page 1: a
  chapter-level step in the runner, guarded, ledgered, run once per chapter.
- **MT-106** - pages stop proposing glossary terms: the per-page schema drops
  `glossary`, a page only marks the fixed glossary's terms seen.
- **MT-107** - the neighbour-Japanese context mode, selectable per run, the
  default unchanged.
- **MT-108** (spike) - rolling vs neighbour context measured on the benchmark
  chapter: S1b and S5 for each, on Gemini; `## Decided` names the synchronous
  default under a rule written before the measurement.
- **MT-109** - *cut after MT-108*: the measured winner becomes the
  synchronous default (or the story is closed as a no-op with the audit cited).
- **MT-110** - Gemini batch adapter: build a batch's requests, submit, poll,
  and parse a finished batch back into per-page results and usage.
- **MT-111** - a volume is guarded as a whole and submitted once: the batch
  projection, the refusal that spends nothing, the persisted job id, the
  `BatchSubmitted` event.
- **MT-112** - collecting a finished batch, resumable: results into the same
  proposals path, one batch-priced ledger row per page, collection resumed
  when a project with a pending job is reopened.
- **MT-113** - the window: Start submits the batch, the panel shows the
  waiting and collected states; `mangatl-run --sync` keeps the per-page run.
- **MT-114** - the consistency-pass request: text-only, chunked under the
  200k tier at page boundaries, the corrections-only schema, parse.
- **MT-115** - corrections applied to untouched proposals and recorded with
  their reason; guarded and ledgered as a chapter-level call; run after
  collection.
- **MT-116** - *cut after Q-2*: the review shows a corrected line's previous
  text and the reason (or the suggestion surface, if Q-2 goes that way).

## Deliberately not in this epic

Claude batches (the Anthropic adapter stays per-page and unchanged).
Switching to Flash or any other model; changing the thinking level; changing
the $2.00 ceiling or where it comes from. Re-running a single page after an
edit - there is no such path in the app today, and this epic adds none; the
synchronous run stays the per-page run. The consistency pass through the
Batch API (Q-4). A per-provider prompt. `cost-model.awk`, which stays
Claude's. The pre-run estimate for a batch (MT-100 gives the per-page one;
MT-111's projection is the batch figure the guard uses, and showing it on the
summary is a story for after Q-3). The audit documents of MT-101 and MT-108
are the spikes' outputs and are referenced by id above.
