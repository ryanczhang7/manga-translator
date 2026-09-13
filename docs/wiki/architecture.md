# Architecture — manga translator

*Written by `/plan-product` on 2026-09-12, by **lead-po on Claude Opus 5
(`claude-opus-5`)**, no session override. Sources: `docs/wiki/product-brief.md`
(scope), `docs/wiki/stack.md` (technology and the O2/O3/O4/O6 decisions),
`docs/wiki/design/**` (the interface, by **lead-designer on Claude Opus 5**).*

This document is meant to stay true for months. It says what the pieces are,
what each is responsible for, what the data is, where state lives, and which
decisions are settled — with the alternatives that lost. It does not say what
any function is called; that belongs in a story's `## Contract`.

---

## 1. Shape

One process, one machine, one user, no network service.

```
        ┌──────────────────────────────────────────────────────┐
        │  ui  (PySide6)   page workspace · review · progress  │
        └───────────────┬──────────────────────────────────────┘
                        │ commands down, progress events up
        ┌───────────────▼──────────────────────────────────────┐
        │  pipeline     stage orchestration · resume · events   │
        └──┬──────┬──────┬──────────┬──────────┬───────────────┘
           │      │      │          │          │
      ┌────▼─┐ ┌──▼──┐ ┌─▼───────┐ ┌▼──────┐ ┌─▼────────┐
      │detect│ │ ocr │ │translate│ │ clean │ │ typeset  │
      └───┬──┘ └──┬──┘ └────┬────┘ └───┬───┘ └────┬─────┘
          │       │         │          │          │
      ┌───▼───────▼─────────▼──────────▼──────────▼──────┐
      │  domain   pure types and rules · no I/O           │
      └───────────────────────┬──────────────────────────┘
                              │
                     ┌────────▼────────┐        ┌──────────┐
                     │ store  (SQLite) │        │  bench   │
                     └─────────────────┘        └──────────┘

  local GPU (ONNX Runtime): detect, ocr, clean
  network (Anthropic API):  translate — and nothing else
```

Three things about this picture are load-bearing:

- **`translate` is the only component that touches the network.** Everything
  else runs on the machine. That is what makes the $2 ceiling a property of one
  module rather than of the whole system, and it is what makes the cost ledger
  trustworthy: there is exactly one place spend can originate.
- **`ui` sits on top and nothing imports it.** Enforced by `import-linter` in
  the `lint` gate (§3). A pipeline that can reach into a widget is a pipeline
  that cannot be tested without a display.
- **`domain` sits at the bottom and imports nothing of ours.** It holds the
  types and the rules — reading order, budget arithmetic, the acceptance
  definition, region geometry — and it is where the product's correctness
  lives. It carries a 100% coverage bar for that reason.

## 2. Components and responsibilities

| Component | Owns | Explicitly does not own |
|---|---|---|
| `domain` | `Chapter`, `Page`, `Region`, `Line`, `Run`, `CostRecord`, `Budget`; reading-order rules; region-merge rules; the acceptance-comparison function; money arithmetic | Any I/O, any file path, any tensor, any widget |
| `store` | The chapter project on disk: schema, migrations, transactional writes, resume state, the cost ledger | Business rules. It persists what `domain` defines; it does not decide anything |
| `detect` | Turning a page image into a set of text regions with masks, including the furigana merge (O6) | Reading order. Deciding what the text *says* |
| `ocr` | Turning a region crop into Japanese text, vertical-native | Region geometry. Translation |
| `translate` | Prompt assembly, the one LLM call per page, response parsing, **token accounting and budget enforcement** | OCR, detection, anything visual |
| `clean` | Erasing the Japanese inside a region mask and reconstructing the interior | Deciding which regions to erase (`pipeline` decides) |
| `typeset` | Font metrics, line breaking, fitting English into a region polygon, rendering it | Letting the human move a box — the brief forbids it |
| `pipeline` | Stage sequencing, resumability, cancellation, progress events, writing the sibling output folder | Any of the above stages' logic |
| `bench` | The ground-truth format, its validator and the single region-matching rule; computing S1b (the headline) and S1a (diagnostic), S2 and S5 against a benchmark chapter; the metrics' own negative controls | Choosing the benchmark chapter, or producing its annotation — both the user's (O1) |
| `ui` | The workspace, the review interaction, the progress and cost readout | Any rule. It renders `domain` and issues `pipeline` commands |

### The adapter split

`detect`, `ocr` and `clean` each contain two things that must not be confused:

- **logic** — a pure function over arrays: pre-processing, thresholding, region
  merging, mask dilation, decode post-processing. It takes an *injected session
  object* with a narrow `run(inputs) -> outputs` interface.
- **a session** — loading a real `.onnx` file and selecting an execution
  provider (CUDA → DirectML → CPU).

The acceptance criteria of every detection/OCR/cleaning story attach to the
**logic**, tested against a fake session in `tests/core/`, which a *required*
gate reads. The real model gets a smoke test in `tests/integration/`, which is
optional because CI has no GPU. Without this split, every required gate could
pass over stories whose artifact nothing exercised — the failure mode
`quality-gates` describes, arrived at by three individually sensible decisions.

## 3. Boundaries, as enforced rules

`import-linter` contracts, checked by the `lint` gate:

1. **Layered.** `ui` → `pipeline` → (`detect`, `ocr`, `translate`, `clean`,
   `typeset`, `bench`) → `store` → `domain`. Imports go down only.
   **The six stage packages are *independent of each other*, not merely
   co-layered** — decided by the user 2026-09-13 during MT-003, because this
   clause was silent on it and `import-linter` cannot be configured without an
   answer (`|` for independent siblings, `:` for siblings that may import each
   other; MT-003 uses `|`). Three reasons: `pipeline` is the orchestrator, and
   stages calling each other directly makes that layer decorative; rule 5
   confines `onnxruntime` to `detect`/`ocr`/`clean`, and that confinement leaks
   transitively the moment `typeset` or `bench` may import `detect`; and the
   `coverage-core` gate demands 100% coverage of `domain`, `typeset` and
   `bench`, which is unreachable if `bench` can pull in a stage that loads ONNX.
   A later story that genuinely needs a stage-to-stage import amends this
   deliberately — that is what the gate is for.
2. **`domain` is independent.** It may import the standard library and nothing
   else of ours — and not `numpy`, `PIL`, `PySide6`, `onnxruntime` or
   `anthropic`.
3. **Nothing imports `ui`.** Including `bench`, which must be runnable headless.
4. **Only `translate` imports `anthropic`.** This is the contract that makes
   "one place spend can originate" a checked fact.
5. **Only `detect`, `ocr` and `clean` import `onnxruntime`.**

A gate that has never been observed to fail is not a gate. The story that adds
these contracts must write each violation on purpose, watch `lint-imports`
reject it, and paste the output into `## Gate probes` — **including the
relative-import form** (`from ...ui import X`), not only the absolute one. A
boundary rule that catches `mangatl.ui` but not `...ui` catches the deliberate
crossing and misses the accidental one.

## 4. Data model, in outline

One **chapter project** = one SQLite database, `<input-folder>.mtproj/project.db`,
a sibling of the input folder. Not inside it: the input folder is the user's
scans and the tool does not write there.

```
chapter    id, source_dir, output_dir, created_at, schema_version,
           budget_ceiling_usd, model_id, rate_table_version

page       id, chapter_id, ordinal, filename, width, height, sha256, status
           -- ordinal is filename order at intake and never changes

region     id, page_id, reading_index, polygon, mask_blob, kind, confidence,
           merged_from            -- furigana regions merged in (O6)
           -- reading_index is assigned by the reading-order pass (MT-007)

line       id, region_id, source_ja, proposed_en, final_en, edited_at,
           viewed_at              -- NULL final_en means "unedited"; acceptance
                                  -- compares norm(proposed_en) to norm(COALESCE
                                  -- (final_en, proposed_en)) per stack.md §5/O2

run        id, chapter_id, started_at, ended_at, outcome, aborted_reason
llm_call   id, run_id, page_id, request_id, model_id,
           input_tokens, output_tokens, cache_write_tokens, cache_read_tokens,
           cost_usd, at            -- the ledger; append-only

glossary   id, chapter_id, term_ja, term_en, note, first_seen_page
           -- continuity across pages: names, honorifics, place names
```

Notes that are decisions, not description:

- **`line.final_en` is nullable and stays NULL until the user edits.** That is
  what makes "accepted as-is" a query rather than a diff of an event log, and
  it is why an edit-then-restore counts as an acceptance (stack.md §5/O2).
- **`llm_call` is append-only and stores the token counts, not just the
  dollars.** Rates change; a ledger that stored only dollars could not be
  re-priced, and S5 requires confirming the app's number against the provider's
  billing at least once.
- **`region.mask_blob`** is a PNG-compressed 1-bit mask, stored rather than
  recomputed, because re-running detection to clean a page is the expensive
  half of a resume.
- **`page.sha256`** is what makes resume safe: if the user replaces a scan, the
  hash changes and that page's downstream state is invalidated rather than
  silently reused.

## 5. Where state lives

| State | Lives in | Lifetime |
|---|---|---|
| The user's scans | Their input folder | Read-only to this app, always |
| Detections, OCR, translations, edits, ledger | `<input-folder>.mtproj/project.db` | Until the user deletes it |
| Baked output pages | `<input-folder>_en/`, same filenames, same order | Overwritten on each bake |
| Model weights | Inside the installed application directory | Installed with the app |
| API key, model choice, budget ceiling, **lettering font override**, UI prefs | `%APPDATA%\mangatl\settings.json` | Per user |
| In-flight run progress | Memory, mirrored to `run`/`page.status` after each stage | Crash-resumable |

**Nothing lives in a cloud account.** There is no sync, no telemetry, no
upload. Page images go to the Anthropic API during translation and nowhere
else; the brief records the user accepting that.

## 6. How the pieces talk

- **`ui` → `pipeline`: commands.** `start_run(chapter, stages)`, `cancel()`,
  `bake(chapter)`. Synchronous call, returns immediately; the work runs on a
  worker thread.
- **`pipeline` → `ui`: an event stream**, not callbacks into widgets.
  `PageStarted`, `StageFinished`, `RegionsDetected`, `LinesProposed`,
  `CostRecorded`, `RunAborted(reason)`, `RunFinished`. Qt signals at the
  boundary; plain dataclasses inside. This is what lets the whole pipeline be
  driven in a test with no display, and it is why the progress and cost readout
  can be asserted on without a GPU.
- **`pipeline` → stages: plain function calls** on a worker thread. No queue, no
  broker. One user, one chapter at a time; a job system here would be
  infrastructure with no user.
- **Stages → `store`: one transaction per page per stage.** That is the resume
  granularity: a crash costs at most one page of one stage, and — critically —
  at most one page of API spend.

## 7. Decisions, with what lost

**D1 — Native Qt desktop (PySide6), not a web UI.**
The workspace is a zoomable canvas with overlay items on a large bitmap, used
for hours. Qt's `QGraphicsView` is that, out of the box.
*Lost:* a local web UI (FastAPI + browser) — two languages, two gate sets, and
"the app" becomes a browser tab, which fights the brief's photo-editor framing;
Electron/Tauri + a Python sidecar — the same two-toolchain cost plus IPC and a
much worse Windows packaging story. **This is the most contestable decision in
the plan**: QSS is a poor styling language compared to CSS, and it is the reason
the design tokens must be authored in a machine-readable source file and
*generated* into QSS rather than hand-written.

**D2 — One language, one process.**
The harness's value is a fast, deterministic gate loop; every additional
toolchain doubles the gates and halves the loop speed.
*Lost:* C#/.NET + ONNX Runtime, which has the best Windows packaging story of
all — but `manga-ocr` and LaMa would need reimplementation, which is
ecosystem risk in exchange for installer polish.

**D3 — ONNX Runtime, not PyTorch, for local inference.**
A CUDA `torch` wheel is ~2.5 GB and would dominate an installer that must
"just work"; ORT's provider chain (CUDA → DirectML → CPU) is what makes the app
run on a machine without a CUDA toolkit.
*Lost:* `torch` + `cu128`. It is the **named fallback** if MT-002's spike finds
the ONNX exports unusable on Blackwell — a bigger installer, but a working one.

> **D3 CORRECTED by MT-002 on 2026-09-12. The conclusion stands; the rationale
> above does not, and is kept only so the correction is legible.**
> See `docs/wiki/audits/MT-002-model-runtime.md`.
>
> **Upheld:** all three ONNX exports run on the RTX 5070's CUDA execution
> provider. The `torch` + `cu128` fallback is **not needed** and should not be
> added. That is the part later stories may take on trust.
>
> **Void — the size argument.** D3 rejected `torch` for being "~2.5 GB". A
> *working* CUDA execution provider measures **1,798 MiB** of runtime on the
> development machine (218 MiB `onnxruntime-gpu` + 1,580 MiB of `nvidia-*` cu13
> and cuDNN 9 wheels), plus 728 MiB of weights — **≈2.47 GiB**. The installer
> saving that justified this decision is largely not there.
>
> **Overstated — "runs on a machine without a CUDA toolkit".** True that no CUDA
> *toolkit* is needed. False that it works out of the box: bare
> `onnxruntime-gpu` fell through to CPU, and so did `onnxruntime-gpu[cuda,cudnn]`,
> until `ort.preload_dlls(cuda=True, cudnn=True, msvc=True)` was called. Without
> that one line the provider fails **without raising** while
> `get_available_providers()` still advertises CUDA — 578 ms versus 23 ms on the
> same model, independently reproduced by the orchestrator (MT-002 PO-3).
>
> **Overstated — "ORT's provider chain (CUDA → DirectML → CPU)".** That is not a
> single install. `onnxruntime-directml` conflicts with `onnxruntime-gpu` and its
> latest cp312 build is 1.17.3, well behind the 1.30.0 that CUDA needs. The chain
> is a *packaging* choice between wheels, not a runtime fallback within one.
>
> **The honest reason to prefer ONNX Runtime, measured rather than assumed:** one
> codebase degrades to any DX12 GPU or to no GPU at all, and the CUDA-less
> install is a ~15 MB wheel rather than a different framework. Size was never the
> reason. **Whether to ship the 1.75 GB of CUDA at all is an open product
> question** — see MT-024 and MT-002's escalations.

**D4 — Local detection, OCR and inpainting; cloud translation only.**
Full reasoning in `stack.md` §5/O3. In short: the downstream consumers need
masks and polygons, an LLM returns neither well, and local OCR keeps the page
image small enough that the $2 ceiling survives.
*Lost:* LLM-only OCR (needs a full-resolution image: 3.4×–4.7× the input
tokens, and no reliable region↔text alignment); a cloud OCR vendor (a second
bill, weaker on vertical manga lettering).

**D5 — One LLM call per page, with the image capped at 1,568 px on the long
edge.** The cost model (`docs/wiki/cost-model.awk`) puts a two-call design at
$2.29 and an uncapped image at $1.95; the chosen design is $1.14. The cap is
not a tuning knob, it is the budget.
*Lost:* one call per *chapter* (cheaper on the prefix, but a single failure
loses twenty pages of spend and the context window fights twenty images);
one call per *bubble* (far better alignment, catastrophically more expensive,
and it discards the page context the brief chose a cloud LLM for).

**D6 — Budget enforcement is a domain rule, not a warning.**
`Budget` lives in `domain`, is fed by the ledger, and `translate` refuses to
make a call whose projected cost would take the run past the ceiling. The run
aborts with a reason the UI shows; the pages already done are kept.
*Lost:* reporting spend and letting it run. The brief calls $2 a hard budget,
and the sensitivity analysis in the cost model shows a plausible
adaptive-thinking volume that crosses it — so the guard is what makes an
unverified estimate safe rather than expensive.

**D7 — SQLite project file, not a JSON sidecar.**
A 20-page run takes minutes and costs money, so it must be resumable; a crash
mid-write must not cost the whole chapter; and the cost ledger wants to be
queried. SQLite gives all three for free.
*Lost:* a JSON sidecar — simpler and diffable, but a partial write corrupts
everything and resume becomes read-all/write-all.

**D8 — Output is written whole, to a sibling folder, atomically per page.**
`<input>_en/<same filename>`. Written to a temp name and renamed, so a
half-baked page never appears.
*Lost:* writing in place (destroys the user's scans); an archive (the brief's
non-goals forbid CBZ/PDF); an overlay format (explicitly a non-goal).

**D9 — The review screen is the only editing surface, and it edits text only.**
Straight from the brief's non-goals. Architecturally this means `typeset`
consumes `line.final_en` and region geometry and has **no per-bubble**
user-facing parameters. If auto-placement is wrong, the human fixes it in
Photoshop.
*Amended 2026-09-12 by the user:* `typeset` takes **one application-wide
parameter** — which font family to letter with, defaulting to the shipped
Shantell Sans. That is a settings value read once per bake, not a per-region
argument, so the "no per-bubble control" property is unchanged and the
architecture is not. MT-027, and the scope reading in the brief's §5.
*Lost:* nothing — both halves are the user's decision, recorded in the brief.

**D10 — Reading order is a pure function on region geometry, computed once.**
Right-to-left, top-to-bottom, band-swept. It is not panel-segmentation-aware in
v1, and it will therefore be wrong on some unusual panel layouts. The mitigation
is that the LLM sees the page image and can attribute speakers from the art even
when the order it was given is imperfect, and the human sees the order on the
review screen.
*Lost:* full panel segmentation — a second model, a second failure mode, and
the brief's success metric is translation acceptance, not ordering fidelity.
Recorded here so a later story can revisit it with evidence rather than taste.

**D11 — Furigana is suppressed at the region level, before OCR.**
`stack.md` §5/O6. A ruby column emitted as its own region becomes a phantom
bubble with a phantom translation on the review screen, which is worse than a
missed one because it costs the human attention.
*Lost:* letting the OCR model drop ruby and living with the extra region — it
does drop ruby *inside* a crop, but that does not remove the phantom region.

**D12 — The read path reads what it writes.**
Every table above is read back on resume; nothing is written "for later". Where
that stops being true — a future export format, say — the entry that is written
but not read must be declared here, together with the invariant standing in for
reading it. A round-trip test proves the application self-consistent, not the
file sufficient, and that distinction has to be recorded somewhere a test can
cite.

**D13 — Ship the GPL-3.0 detector knowingly, conveying weights and not code.**
**Decided by the user on 2026-09-13**, on the evidence in
`docs/wiki/audits/MT-030-detector-licence.md`. MT-030 measured nine candidate
detectors and found no permissively-licensed alternative with an ONNX export
that cleared its pinned floor — the incumbent's peak IoU against the reference
mask is 0.71–0.75 against the best permissive candidate's 0.45, a gap that does
not close at any threshold. So the choice was between shipping GPL-3.0 and
commissioning a detector, and it is not a technical choice. The product ships.

*This is a recorded product decision, not legal advice. The obligations below
are an engineer's reading of the licence texts quoted in MT-030's audit; a
distributed commercial product may warrant counsel, and nothing here substitutes
for it.*

**What the application actually conveys, which is the load-bearing distinction.**
Not `dmMaze/comic-text-detector`'s source. MT-002 already forbade reusing it —
*"the pre-processing and post-processing in it must be re-derived test-first"* —
so the installer contains the trained **weights** (`comic-text-detector.onnx`,
SHA-256 `1a86ace7…`) plus first-party code written against MT-007's own contract.
Whether trained weights are a derivative work of the GPL'd training code is
genuinely unsettled, and this decision does not pretend to settle it. It
minimises the exposure instead: **no GPL-licensed source file enters the image,
and the detector stays behind the `detect` adapter boundary** (§2), so the
question never widens from "we distribute a weights file" to "we distribute a
combined work".

*Lost:* the option of treating the detector as a swappable commodity. Two
things now depend on this specific model and are recorded so a later swap is
costed rather than assumed — MT-007 AC-6 is built on the box-head/mask split,
and MT-019's `seg ∩ accepted boxes` construction needs the box head. **No
permissive candidate has a box head at all** (MT-030 E4, confirmed against every
candidate's graph outputs), so replacing the detector is a design change, not a
substitution.

**The obligations this creates. MT-024 owns all of them.**

| # | Obligation | Source |
|---|---|---|
| O-1 | Convey the full GPL-3.0 licence text with the installer | GPL-3.0 §4 |
| O-2 | Identify the GPL-3.0 component, its upstream, and its version or hash | GPL-3.0 §4–5 |
| O-3 | Offer **corresponding source** for the GPL-3.0 component — a written offer, or a URL to the upstream repository at the revision used | GPL-3.0 §6 |
| O-4 | State clearly that the Manga109-s dataset was used, since the detector is a pre-trained model within its terms | Manga109-s, condition 2 |
| O-5 | Keep the notices accurate when a model changes — a manifest entry without a notice entry is a defect | this decision |

O-4 is the one that is *only* attribution. O-1 through O-3 are copyleft
obligations and are not discharged by an attribution line; that distinction is
recorded because it is easy to collapse the two into "add a credits screen".

**What this decision does not decide.** Whether *other* bundled weights carry
obligations of their own. MT-002 flagged the LaMa checkpoint's provenance as
**traced at repository-metadata level only**, and inpainting checkpoints in that
lineage are sometimes distributed under non-commercial terms. That is unresolved
and is a separate question from this one; MT-024 must not read D13 as clearing
it.

## 8. Deployment shape

There is none, in the server sense. The deliverable is a Windows installer:

1. PyInstaller freezes `src/mangatl` plus the venv into a one-folder build.
2. The `.onnx` weights are bundled as data, with a manifest of file hashes the
   app verifies at startup. **The user never downloads or places a weight.**
3. Inno Setup wraps the folder into a double-clickable installer.
4. First run asks for the Anthropic API key and writes it to
   `%APPDATA%\mangatl\settings.json`. That is the only setup step, and it is the
   one the brief permits.

`.dockerignore` is not relevant — nothing is containerised — but the same
principle applies to the PyInstaller spec: **`.claude/`, `docs/`, `scripts/` and
`.github/` never enter the shipped build.** The packaging story asserts that
with a test over the built tree, not with a comment in the spec file.

## 9. What this architecture deliberately cannot do

Carried from the brief's non-goals so that a later reader does not mistake an
omission for an oversight: no art-integrated SFX (nothing outside a detected
bubble region is ever touched); no typeset editing; no language pair but
Japanese→English; no CBZ/PDF/archive; no reader or viewer; no overlay output;
no publishing, upload or acquisition path of any kind; Windows only.
