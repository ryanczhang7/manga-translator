# What the detector's class 0 is: watermark only, or any text outside a bubble - MT-117

Spike MT-117 (EPIC-10 PO-4). Written by the orchestrator (`lead-po`, Claude
Fable 5.1, `claude-fable-5-1`) on 2026-11-05. The decision rule below was
committed **before** the measurement was run (AC-1); the measurement commit
follows it in the branch history.

## Scope

What is measured: every region the shipped detector (`comic-text-detector.onnx`,
hash recorded under `## Measurement`) returns on the pages named below, with
its `kind` (`box` = box-head class 0, `bubble` = class 1), its bounding box,
its `confidence`, what the shipped OCR reads from its crop, and a one-word
human reading of the crop. The question is whether `kind == "box"` can be read
as "scanlation watermark" (and so excluded automatically, MT-121) or means
"any text outside a bubble".

Pages, from the folders on the development machine (none is in the
repository; all are non-redistributable scans, `fixtures/detect/README.md`):

- `spikes/MT-002/pages` - the five spike pages `011-015.jpg` (MT-007 A-4's
  chapter).
- `C:\Users\ryanc\Downloads\mato sample` - the user's sample chapter,
  `007, 008, 009, 016.jpg` (the story's field evidence).
- `C:\Users\ryanc\Downloads\Mato no Seihei` - fifteen `.png` pages whose
  names carry chapter numbers `0134`-`0136`.

Deliberately left out: the full volumes `matoseiheino_v17`-`v21` (about 200
pages each) unless the user asks for them (`## What was not checked`); the
benchmark chapter (EPIC-07 O1, the user's to name); the detector's thresholds
and `_kind` itself (out of scope).

## Decision rule

Written 2026-11-05, before any page was measured; the PO's proposal from the
story, which the user did not reset (EPIC-10 Q-2).

- **R-1** - The predicate `kind == "box"` is adopted as the automatic rule if
  at least **10** class-0 regions were examined across at least **2**
  chapters, and **none** of them is translatable text (dialogue, narration, a
  caption, a sign, a thought) - every one is a watermark, a URL, a credit, or
  not text at all.
- **R-2** - If one or more class-0 regions is translatable text, the audit
  states a narrower predicate only if it can be stated mechanically over
  fields the store holds (`kind`, `polygon`, `confidence`, `source_ja`) and
  separates every watermark seen from every translatable region seen with a
  margin the audit records; otherwise `## Decided` says **no automatic rule**
  and MT-121 closes as a no-op with the audit cited.
- **R-3** - If fewer than 10 class-0 regions exist on every page available,
  the audit says so, records what was seen, and `## Decided` still answers
  R-1 or R-2 on what there is, marked **under-powered**, so that MT-121's
  story records the thinness rather than inheriting a confidence the data
  does not carry.

The human-reading vocabulary, fixed here so the measurement cannot bend it:
{watermark, url, credit, narration, caption, sign, dialogue, sfx, not-text}.
"Translatable text" for R-1 and R-2 is {narration, caption, sign, dialogue}.
`sfx` (a drawn sound effect) is **not** counted as translatable for R-1 - the
product translates dialogue and narration, and the story's field evidence
(`009.jpg` ちゃぽ) is exactly the case the rule has to be explicit about -
but a class-0 `sfx` is recorded and `## Decided` says what it means for an
exclusion rule.

## Measurement

*Not yet run. Filled by the measurement commit.*

## Decided

*Filled by the measurement commit.*

## What was not checked

*Filled by the measurement commit.*
