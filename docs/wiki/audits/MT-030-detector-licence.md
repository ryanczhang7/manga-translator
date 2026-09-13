# MT-030 — A permissively-licensed text detector, or a decision to ship GPL

*Spike run 2026-09-12 by **lead-po on Claude Opus 5 (`claude-opus-5`)**, dispatched
by the lead-po orchestrator. No session override was reported to the agent; the
resolved model recorded here is the one declared in `.claude/agents/lead-po.md`.
Candidate enumeration and licence fetching were delegated to a `general-purpose`
subagent, also on Claude Opus 5; **every licence quote and dataset term it
returned was re-fetched or re-read from the saved primary artefact by the spike
before being written here**, and the ONNX graph signatures it could only infer
from source were confirmed by loading the graphs.*

**The question this spike was dispatched to settle:** the text detector MT-007
is planned to use is GPL-3.0 upstream, and this application is *distributed* as
a double-click installer. Is there a permissively-licensed detector that can
replace it?

**Answer: no. Nine candidates were checked, four were measured on this machine,
and none is a viable replacement — but the reason the incumbent is a problem is
narrower than the plan recorded.** The Manga109-s objection is void: those terms
expressly permit commercial use of models trained on the dataset. **GPL-3.0 is
the entire blocker**, and the remaining choice is a product decision the user
must take, not one this spike may take. See `## Decided`.

---

## How to read this document

Per AC-5, every factual claim below carries one of three labels:

| Label | Meaning |
|---|---|
| **[MEASURED]** | Run on the development machine on 2026-09-12. The command is given in *Reproducing any of this*. |
| **[WEB]** | Read from a repository file, an API response or a published terms page. The URL is given. Not verified by running anything. |
| **[INFERRED]** | A conclusion drawn from the above, not itself a measurement. |

**The machine everything was measured on**, and the only machine any
[MEASURED] number applies to — unchanged from MT-002:

```
Windows 11 Home 10.0.26200, Ryzen 5 7600X, 32 GB
NVIDIA GeForce RTX 5070 (Blackwell, sm_120), Driver 591.86, CUDA 13.1
onnxruntime-gpu 1.30.0, numpy 2.5.3, opencv 5.0.0, CPython 3.12.14
```

Every probe ran in the surviving MT-002 spike venv at `spikes/MT-002/.venv`.
**The project's `pyproject.toml`, `uv.lock` and `.venv` were not touched**, and
no file outside `docs/` and the gitignored `spikes/` tree was written.

**This document gives no legal advice and must not be read as any.** Its job is
to put the actual licence text, the actual dataset terms and the actual measured
alternatives in one place. Where a reading of a licence is offered it is labelled
**[AGENT READING]** and is exactly that: an agent's reading, not counsel's.

---

## Scope

**Audited:** which text detector MT-007 should use, given that the incumbent is
GPL-3.0 upstream and this application is distributed as an installer. Commit:
branch `story/MT-030-a-permissively-licensed-text-detector-or` at
`565ae1a` + this story's documentation changes. Nine candidate detectors were
enumerated, their licences read from upstream `LICENSE` files, and every
candidate that was both permissively licensed and had a usable ONNX export was
downloaded and run on this machine against the same fixture pages MT-002 used.

**Deliberately out of scope**, and not reopened here:

- **The runtime.** ONNX Runtime on the CUDA execution provider is settled by
  MT-002 `## Decided`. Nothing below re-litigates it.
- **Detection thresholds.** They are MT-007's and are derived test-first. Where a
  threshold is swept below it is to give a candidate its best showing in a
  comparison, never to propose a value.
- **Mask refinement and region merging.** MT-007's. Their absence is the
  proximate cause of escalation E-1 and is named there rather than worked around.
- **OCR and inpainting model choice**; **training or fine-tuning anything.**
- **Whether GPL-3.0 obligations are acceptable for this product.** That is the
  user's decision and may need counsel. This document supplies the text, not the
  answer.

## Decided

*This section is the only part later stories may take on trust. It contains the
outcome and the file identities, and nothing else. Every number lives in
`## Evidence` and is to be re-verified, not assumed.*

### No permissively-licensed replacement was found. The decision is the user's.

Per AC-4, this spike **does not name a replacement detector**, because none of
the candidates that is both permissively licensed and has a usable ONNX export
clears the floor pinned in the story before the first measurement ran. The
remaining options are:

1. **Ship the incumbent and accept GPL-3.0 obligations**, or
2. **Commission / train a detector** on licence-clean data.

**That choice is not technical and the spike may not make it** (story PO-3). The
evidence for each is below; the decision is put to the user.

### The premise has changed, and this is the most consequential finding

`stack.md` line 130, MT-002's `## Licence risk` and MT-030's own `## Context` all
record **two** objections to the incumbent: GPL-3.0, *and* training on Manga109-s
described as "a dataset whose terms restrict use to academic research".

**The second objection is void.** Manga109-s is a deliberately-created
commercial-use subset and its published terms permit exactly what this product
would do. The academic-only restriction belongs to **Manga109** (the full
109-volume set), not to **Manga109-s** (87 volumes), and the incumbent's README
says Manga109-**s**. Quoted in full in `## Licence and dataset texts`. [WEB]

**Consequence:** the GPL-3.0 question is the *whole* question, and it is a
software-licence question rather than a data-provenance one. One live obligation
does survive from the dataset terms — attribution — and it is cheap:

> When publishing results (including pre-trained models) obtained from machine
> learning experiments or image processing experiments, the use of the Manga109-s
> dataset must be indicated clearly within the published work.

If option 1 is taken, that line belongs in the installer's notices alongside the
GPL obligations. **MT-024 owns it.**

### File identities

The incumbent is unchanged from MT-002 `## Decided`; repeated here only so this
document stands alone.

| Role | Repo | File | SHA-256 | Bytes |
|---|---|---|---|---|
| Incumbent detector | `mayocream/comic-text-detector-onnx` | `comic-text-detector.onnx` | `1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f` | 94,669,756 |

The candidates measured and rejected, so nobody re-downloads them to find out —
all sizes and hashes **[MEASURED]**, `sha256sum` on the downloaded file:

| Candidate | Repo / file | SHA-256 | Bytes |
|---|---|---|---|
| PP-OCRv5 server det | `PaddlePaddle/PP-OCRv5_server_det_onnx` `inference.onnx` | `10803475a591f7dc623e24670fb5752ec94d39a1f8cf069aac1b6f0ce19cfc85` | 88,116,791 |
| PP-OCRv5 mobile det | `PaddlePaddle/PP-OCRv5_mobile_det_onnx` `inference.onnx` | `a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d` | 4,826,518 |
| PP-OCRv6 medium det | `PaddlePaddle/PP-OCRv6_medium_det_onnx` `inference.onnx` | `eb13b44b25bb36f89528b68720af8a61d9cf381176107f465db1757b65d086e1` | 62,032,837 |
| docTR DBNet R50 | `Felix92/onnxtr-db-resnet50` `model.onnx` | `69ba00155c16b198d062f5a7b9cdb446c82aed81812d7ff5a74e01ab41421d55` | 100,919,029 |
| docTR DBNet MNv3 | `Felix92/onnxtr-db-mobilenet-v3-large` `model.onnx` | `4987e7bdea372559808bd5add85fda10e179dc639696fb489e59a197a25b4c64` | 16,076,965 |
| docTR LinkNet R18 | `Felix92/onnxtr-linknet-resnet18` `model.onnx` | `e0e0b9dc95b881e1a869954bb785b83bc6a1259c7444ffe914a3538698d0d79e` | 46,134,192 |
| CRAFT | `KvaytG/craft-mlt-25k-onnx` `craft.onnx` | `f69ff10b3fd19126738b2ff7322285a59ba92571bb603dfbeb61a0dc03aa536e` | 83,179,177 |
| ogkalu comic detector | `ogkalu/comic-text-and-bubble-detector` `detector.onnx` | `065744e91c0594ad8663aa8b870ce3fb27222942eded5a3cc388ce23421bd195` | 168,481,531 |
| manga109 seg bubble | `NeuronCState/manga109-segmentation-bubble-onnx` `best.onnx` | `760146a01c3e9f547bc271751bedacd30ae973bfa043dd7761069be7ae0b1336` | 12,509,314 |

### What MT-007 inherits either way

These hold whichever option the user picks, and MT-007 should read them:

- **No candidate other than the incumbent has a box head.** Every permissive
  candidate emits a probability map and nothing else. The `seg`-versus-boxes
  split that MT-007 AC-6 and MT-019 are built on **does not exist** for any of
  them; each one masks the sound effects. See E4. If the detector ever changes,
  AC-6 needs a different mechanism and that is a real cost.

  **Confirmed independently by the orchestrator** by enumerating every
  downloaded graph's outputs — this claim decides whether MT-007 AC-6 survives,
  so it was checked against the artefacts rather than accepted:

  ```
  PP-OCRv5_mobile_det_onnx      [('fetch_name_0', [_, 1, _, _])]
  PP-OCRv5_server_det_onnx      [('fetch_name_0', [_, 1, _, _])]
  PP-OCRv6_medium_det_onnx      [('fetch_name_0', [_, 1, _, _])]
  craft-mlt-25k                 [('output', [_, h/2, w/2, 2]), ('relu_18', [_, 32, h/2, w/2])]
  onnxtr-db-mobilenet-v3-large  [('logits', [_, 1, 1024, 1024])]
  onnxtr-db-resnet50            [('logits', [_, 1, 1024, 1024])]
  onnxtr-linknet-resnet18       [('logits', [_, 1, 1024, 1024])]
  ogkalu-comic-bubble           [('labels', ...), ('boxes', ...), ('scores', ...)]
  manga109-seg-bubble           [('output0', [1, 37, 52500]), ('output1', [1, 32, 400, 400])]
  comic-text-detector-onnx      [('blk', [1, 64512, 7]), ('seg', [1, 1, 1024, 1024]), ('det', [1, 2, 1024, 1024])]
  ```
  [MEASURED — orchestrator, 2026-09-12]

  The incumbent is the only graph carrying **both** a detection head (`blk`,
  the 64512×7 YOLO tensor) and a segmentation map (`seg`). Every permissive
  candidate emits one spatial map and no boxes. `ogkalu` emits `labels` /
  `boxes` / `scores` and no map at all, which confirms the P1 structural
  disqualification against the artefact rather than against its model card.
- **The incumbent's mask threshold is not 0.3.** MT-002 used the upstream default
  and measured IoU 0.585. Swept, the incumbent's IoU against the same reference
  peaks at **0.714 at threshold ≈0.81** (E5). This is a hint for MT-007, **not a
  value to adopt**: the reference is the author's *refined* mask and MT-007 will
  implement refinement, so the right operating threshold for a raw map feeding a
  refinement step is a different quantity. MT-007 still derives it.

---

## Escalations — two pinned thresholds that do not work, and were not moved

The story pinned five disqualifying conditions W1–W5 before any candidate ran,
and instructed the spike not to re-scope them after seeing a result. **Two of
them turn out not to measure what they were meant to. Neither was moved.** The
numbers below are reported under the pins as written, with the defect named.

### E-1 — W3 disqualifies the incumbent against itself

W3 reads *"Region count on any of `011–015.jpg` falls outside **2–40**"*, with
the incumbent's value given as *"6–9 per page (E6)"*.

**MT-002 E6's table has two count columns and 6–9 is the *Boxes* column.** The
*Mask components* column in that same table is 57–136. For a detector typed by
P1 as a per-pixel probability map, the natural region count is connected
components of the thresholded map — and there the incumbent scores far outside
2–40 on every page. [MEASURED]

| Interpretation of "region count" | 011 | 012 | 013 | 014 | 015 | within 2–40? |
|---|---|---|---|---|---|---|
| YOLO **boxes** (E6 "Boxes" column) | 9 | 6 | 8 | 9 | 6 | yes |
| mask **components**, ≥20 px — MT-002 E6's "Mask components" column, reproduced exactly | 136 | 86 | 83 | 111 | 57 | **no — all five** |
| the same, under the harness's resize-then-threshold ordering (see E4) | 136 | 82 | 80 | 108 | 56 | **no — all five** |
| mask components, ≥400 px | 44 | 41 | 32 | 42 | 25 | no — three of five |
| components after a 15×15 close, ≥400 px | 14 | 18 | 15 | 14 | 11 | yes |
| components after a 31×31 close, ≥400 px | 11 | 13 | 10 | 11 | 11 | yes |

So W3 as pinned **fires for the incumbent**, and — worse for its usefulness as a
discriminator — *clears* for PaddleOCR (12–35), which is far worse at the actual
job (recall 0.71 versus 0.95). A threshold that ranks a weaker detector above the
one it is calibrated from is not measuring detector quality.

**Why:** Japanese text is many disconnected glyphs and strokes, so an unrefined
thresholded mask yields roughly one component per glyph-blob, not one per bubble.
MT-002 E6 already said the raw mask is unrefined and that MT-007 implements
`refine_mask`. A bubble-level region count only exists *after* refinement, and
refinement is MT-007's to derive and explicitly out of this spike's scope.

**Not resolved here.** The fix is either (a) W3 counts boxes, which is
unmeasurable for exactly the mask-only candidates P1 prefers, or (b) W3 counts
components after a stated, uniform morphological close, which imports a
post-processing constant this spike is not allowed to choose. **Put to the
orchestrator.** No candidate's verdict below turns on it: every candidate is
already disqualified by W1.

**Settled by the orchestrator, 2026-09-12 — W3 is withdrawn, not repaired.**

The escalation is correct and I accept it; the pin was mine and it was
ill-posed. I verified the defect directly against MT-002 E6 rather than
against the spike's reproduction of it — that table has two count columns,
*Boxes* `9, 6, 8, 9, 6` and *Mask components* `136, 86, 83, 111, 57`, and my
pin said "region count" while quoting the first and meaning something a
mask-only candidate could produce. Both readings are defensible and they
disagree by an order of magnitude, which is the definition of an unusable
threshold.

Neither repair is available to this story. **(a)** makes W3 unmeasurable for
every candidate P1 selects for, which inverts its purpose. **(b)** requires
choosing a morphological close, and a bubble-level region count does not exist
before `refine_mask` — which is MT-007's to derive, test-first, and is named
*Out of scope* in this story. Picking a constant here to rescue a threshold
would be exactly the "narrowing to make the test pass" that `rules.md` forbids,
and it would hand MT-007 a number it never derived.

So W3 is **withdrawn** rather than reinterpreted, and the honest statement of
what happened is: *four of the five pinned conditions discriminated; the fifth
was ill-posed and is void.* This costs nothing, because W3 excluded no
candidate that W1 and E5 did not already exclude by a wide margin — the spike
checked this and I confirmed it against the table above: PaddleOCR is the only
candidate W3 would have *cleared*, and it is out on peak IoU 0.38 vs 0.75.

**What MT-007 inherits from this:** a region-count sanity check is a reasonable
thing to want and this is where it belongs — *after* refinement, against a
bubble count, with the morphology constant derived from a fixture rather than
asserted. It is not a licence question and it is not this spike's.

### E-2 — W1 is recall-only and is gameable by lowering a threshold

W1 reads *"Recall … is **below 0.85**"*. Recall against a fixed reference rises
monotonically as the threshold falls, so any model can clear W1 by being
maximally over-eager. Measured on `onnxtr-db-resnet50`: [MEASURED]

| threshold | recall | precision | % of the page masked |
|---|---|---|---|
| 0.005 | **1.0000** | 0.064 | **81.0** |
| 0.010 | 0.9993 | 0.078 | 66.6 |
| 0.050 | 0.9045 | 0.195 | 24.0 |
| 0.080 | 0.8401 | 0.259 | 16.8 |
| 0.100 | 0.7941 | 0.298 | 13.8 |

A model that masks 81% of the page scores perfect recall. W4 (a single region
over 40% of the page) catches the extreme, but not the 0.05 row, which clears
W1 at 24% of the page masked.

**Not resolved here, and it did not need to be:** rather than move W1, the spike
added a threshold-*independent* comparison alongside it (E5), which removes the
threshold from the argument entirely and reaches the same verdict by a wider
margin. The pin stands as written; the diagnostic is additional.

### E-3 — the P6 table is missing one entry

P6 lists where the detector identity is written down. Swept against the tree
[MEASURED], the list is correct but incomplete by one:
`docs/backlog/stories/MT-002.md` line 311 also carries the detector's SHA-256 in
its model manifest. Like the MT-002 audit, it is a closed story's file and not
this story's to edit. **No code callers exist** — `src/mangatl/detect/` is an
empty package, confirmed.

---

## Evidence

*Everything in this section is a number, and **every number here is to be
re-verified by the story that depends on it, not assumed**. MT-007 is told not
to re-litigate `## Decided`; it is **not** told to trust anything below this
line.*

### E1 — the incumbent baseline reproduces, independently

MT-002's `## Evidence` is the bar a replacement had to clear, so it was
re-verified first. **The probe was written from the model's I/O signature rather
than adapted from `spikes/MT-002/detect.py`**, so agreement is a reproduction and
not a re-run of the same lines.

| Quantity | MT-002 E4/E6 | MT-030 re-measurement | |
|---|---|---|---|
| provider actually selected | `CUDAExecutionProvider` | `CUDAExecutionProvider` | [MEASURED] |
| latency, 1024² page | 25.83 ms | 23.3–25.3 ms | [MEASURED] |
| boxes, `011`–`015` | 9, 6, 8, 9, 6 | **9, 6, 8, 9, 6** | [MEASURED] |
| mask components, `011`–`015` | 136, 86, 83, 111, 57 | **136, 86, 83, 111, 57** | [MEASURED] |
| recall vs the author's reference mask | 0.949 | **0.9492** | [MEASURED] |
| IoU vs the author's reference mask | 0.585 | **0.5847** | [MEASURED] |

**Every figure reproduced.** [MEASURED] The baseline is sound and the comparisons
below rest on something checked rather than inherited.

`session.get_providers()` was used throughout and `get_available_providers()`
never was (P7). `ort.preload_dlls(cuda=True, cudnn=True, msvc=True)` was called
before the first session in every process; the mechanism MT-002 PO-3 asserted
held on every one of the nine graphs loaded here — all selected CUDA. [MEASURED]

### E2 — the W2 reference region set, earned rather than assumed

W2 asks whether a candidate covers *"the 9 regions E5 confirmed as real text by
reading them back through manga-ocr"*. **Those coordinates are written down
nowhere in the audit**, so they were re-derived and re-read through manga-ocr.

All nine boxes came back byte-identical to MT-002's own saved
`out/pipeline_014.json`, including box 06, whose transcription the E5 prose table
renders as `……なるほど` while the JSON it came from holds `．．．．．．なるほど` —
a cosmetic difference in the audit's prose, not a discrepancy. **9/9 reproduced.**
[MEASURED]

The nine boxes are frozen in `spikes/MT-030/out/w2-reference-014.json` and are
the W2 oracle for every candidate. A region counts as covered when at least 10%
of its box area is masked.

### E3 — the candidate table (AC-1)

Nine candidates. Licences read from the **upstream repository's `LICENSE` file**
and cross-checked against the GitHub API's `spdx_id` (P5), never from a model
card. Where a re-upload's metadata disagrees with upstream, both are recorded.

| # | Candidate | Licence (from the artefact) | ONNX export | Training data, as stated | Mask? | Outcome |
|---|---|---|---|---|---|---|
| 1 | **`dmMaze/comic-text-detector`** (incumbent) | **GPL-3.0** [WEB — the repo's `LICENSE`, 35,149 B, full GPLv3 text; GitHub API `spdx_id: GPL-3.0`] | yes, `mayocream/comic-text-detector-onnx` | README: *"around 13 thousand … 1/3 from Manga109-s, 1/3 from DCM, and 1/3 are synthetic"* [WEB] | **yes** + boxes | **incumbent; GPL-3.0 is the blocker** |
| 2 | `ragavsachdeva/magi` / Magiv2 | **none** — GitHub API `license: null`, no `LICENSE` file. README: *"available for academic research purposes only"*; the HF card says *"personal, research, non-commercial"*. **The author's two statements disagree.** [WEB] | **no** | arXiv 2401.10224 / 2408.00298 | boxes | **ruled out — non-commercial, and no ONNX** |
| 3 | **PaddleOCR det** (PP-OCRv5/v6) | **Apache-2.0** [WEB — `LICENSE`; API `spdx_id: Apache-2.0`] | yes, **official first-party** | not stated; no manga data claimed | yes | **measured → disqualified on W1** |
| 4 | **docTR / OnnxTR** DBNet, LinkNet | **Apache-2.0** both repos [WEB — both `LICENSE` files; API `spdx_id: Apache-2.0`] | yes, pre-exported | not stated; no manga data | yes | **measured → disqualified on W1** |
| 5 | **CRAFT** (ClovaAI) | code **MIT** [WEB — `LICENSE`, API `spdx_id: MIT`]. **Weights are not in the repo** — `craft_mlt_25k` ships from Google Drive with no licence file; the ONNX is a third-party re-upload tagged `mit`. **Unresolved.** | yes, third-party | README: *"SynthText, IC13, IC17"*; no manga data [WEB] | yes | **measured → disqualified on W1** |
| 6 | MMOCR DBNet++ | **Apache-2.0** [WEB] | **no pre-built**; MMDeploy export path | no manga data | yes | **ruled out — no export within the timebox; same generic-text family as #3/#4, which measured far below the floor** |
| 7 | EasyOCR | Apache-2.0, but it *packages* CRAFT so CRAFT's weight terms ride along [WEB] | not first-party | same CRAFT weights | yes | **ruled out — #5 by another route** |
| 8 | **`ogkalu/comic-text-and-bubble-detector`** | HF tag `apache-2.0`; **no upstream repo, so no `LICENSE` file to read** — a tag, not a file | yes, `detector.onnx` | card: *"~11k Manga, Webtoon, Manhua and Western Comic style Images"* [WEB] | **NO — boxes only** | **ruled out under P1.** Confirmed by loading the graph: outputs are `labels`, `boxes`, `scores` and no mask tensor [MEASURED] |
| 9 | YOLO-seg bubble detectors (`kitsumed/yolov8m_seg-…`, `huyvux3005/manga109-segmentation-bubble` + ONNX ports) | **contested.** HF tags say `apache-2.0`/`gpl-3.0`; the Ultralytics base is **AGPL-3.0** [WEB — `LICENSE`, API `spdx_id: AGPL-3.0`]. No upstream `LICENSE` for the fine-tunes. | yes | card `datasets:` names **`manga109`** — the *full*, academic-only set, not Manga109-s [WEB] | yes (YOLO-seg) | **ruled out — AGPL-3.0 is the same class of problem as GPL-3.0, not an escape from it; and the dataset really is academic-only here. Detects *bubbles*, not text.** |

**Also found and recorded, because it is the one licence-clean manga-native
lineage** — `juvian/Manga-Text-Segmentation`, **MIT** [WEB — `LICENSE`; API
`spdx_id: MIT`], whose label masks are on Zenodo under **CC-BY-4.0** [WEB]. It
emits per-pixel text masks and is *the source of the incumbent's own mask
labels*, per the incumbent's README. **It has no ONNX export and no released
weights suitable for one** (fastai notebooks; the 2025 successor on HF carries
*no licence at all*). It is not a candidate today — it is the most plausible
starting point if the user picks option 2.

**How the non-listed candidates were found:** Hugging Face API `?search=` on
`comic text detector`, `manga segmentation`, `speech bubble segmentation`,
`PP-OCR det onnx`; GitHub search for manga text segmentation, which the
incumbent's own README then confirmed as its mask-label source; docTR's export
documentation, which names OnnxTR.

### E4 — measured forward passes (AC-2)

Every candidate that is permissively licensed **and** has an ONNX export was run
on the same five fixture pages MT-002 used plus the reference page, on this
machine. Each was given its best honest shot first: preprocessing was taken from
each repo's own shipped config, and channel order, input resolution, padding
value and threshold were **swept** before the six-page run, so no candidate is
rejected on a strawman configuration.

Each row is the candidate's **best** configuration. [MEASURED]

**A note on ordering, because it moves the numbers slightly and MT-007 will hit
it.** A probability map can be resized to page size and *then* thresholded, or
thresholded and *then* resized with nearest-neighbour. The first is correct for a
probability map and is what the shared harness does, so every row below uses it.
MT-002 used the second. On the incumbent the difference is real but small —
recall 0.9658 versus 0.9492, IoU 0.5657 versus 0.5847, components 136/82/80/108/56
versus 136/86/83/111/57 [MEASURED, both] — and **the second ordering is the one
that reproduces MT-002 E6 exactly** (E1). No verdict here turns on the choice.

| Candidate | provider (`get_providers()[0]`) | ms/page | W1 recall | W2 | W3 components (011–015) | W4 max region | verdict |
|---|---|---|---|---|---|---|---|
| **incumbent** comic-text-detector | `CUDAExecutionProvider` | 23.3 | **0.966** | 9/9 | 136 / 82 / 80 / 108 / 56 | 1.99% | *(the bar; W3 fires — see E-1)* |
| PP-OCRv5 server det @1600 | `CUDAExecutionProvider` | 80.7 | **0.706** | 9/9 | 35 / 23 / 24 / 32 / 12 | 1.09% | **W1 fires → disqualified** |
| PP-OCRv5 mobile det @1600 | `CUDAExecutionProvider` | 18.8 | **0.657** | 9/9 | 31 / 20 / 22 / 31 / 12 | 1.40% | **W1 fires → disqualified** |
| PP-OCRv6 medium det @1600 | `CUDAExecutionProvider` | 47.2 | **0.611** | 9/9 | 33 / 27 / 20 / 32 / 11 | 1.01% | **W1 fires → disqualified** |
| docTR DBNet R50, th 0.15 | `CUDAExecutionProvider` | 24.6 | **0.638** | 9/9 | 117 / 64 / 85 / 117 / 40 | 1.16% | **W1 fires → disqualified** |
| docTR DBNet MNv3, th 0.20 | `CUDAExecutionProvider` | 14.0 | **0.581** | 9/9 | 90 / 76 / 50 / 95 / 27 | 1.78% | **W1 fires → disqualified** |
| docTR LinkNet R18 | `CUDAExecutionProvider` | 12.9 | **0.308** | — | — | — | **W1 fires → disqualified** |
| CRAFT @2048, th 0.30 | `CUDAExecutionProvider` | 146.4 | **0.807** | 9/9 | 52 / 61 / 29 / 51 / 22 | 2.28% | **W1 fires → disqualified** |

**W5 never fired.** All nine graphs loaded on `CUDAExecutionProvider`; the
runtime is not what rules anything out.

**W2 and W4 never fired either.** Every candidate covers all nine confirmed text
regions on `014.jpg` and none produces a page-swallowing region. **The candidates
are not blind — they are imprecise.** They find the text; they trace it much less
faithfully, which is exactly what recall against a pixel-accurate reference
measures and what an inpainting mask depends on.

One incidental result worth recording: **RGB and BGR input give identical results
to four decimal places** for every PaddleOCR configuration [MEASURED]. Manga
scans are greyscale, so R=G=B per pixel and the channel swap is a no-op. The
channel-order trap MT-002 flagged for the incumbent does not exist on this input
domain.

### E5 — the threshold-independent comparison

Because W1 is gameable (E-2), each model was swept over 140 thresholds and
compared two ways that do not depend on picking one: its **best achievable IoU at
any operating point**, and its **recall at the threshold where its precision
matches the incumbent's measured 0.604** — i.e. at an equally fat mask. [MEASURED]

| Candidate | peak IoU (at any threshold) | recall at equal precision |
|---|---|---|
| **incumbent comic-text-detector** | **0.7137** @ th 0.814 | **0.9587** |
| PP-OCRv6 medium det @1600 | 0.3940 @ th 0.009 | 0.4028 |
| PP-OCRv5 server det @1600 | 0.3848 @ th 0.043 | 0.5463 |
| PP-OCRv5 mobile det @1600 | 0.3739 @ th 0.022 | 0.5451 |
| CRAFT @2048 | **0.4595** @ th 0.316 | 0.4568 |
| docTR DBNet MNv3 | 0.3342 @ th 0.200 | 0.0255 |
| docTR LinkNet R18 | 0.3217 @ th 0.002 | 0.1438 |
| docTR DBNet R50 | 0.3118 @ th 0.152 | 0.1639 |

**The incumbent's peak IoU is 1.55× the best permissive candidate's (0.714 vs
0.460) and its recall at equal precision is 2.1× (0.959 vs 0.457).** The gap does
not close at any threshold, so the verdict is not an artefact of the pinned
number in W1. [INFERRED, from the measurements above]

**Why the gap is real and not a fixture accident:** the reference is the
incumbent author's *own published* mask, so the incumbent is being scored against
a target produced by its own lineage. That biases the comparison **in the
incumbent's favour** and is the single largest caveat on this section — see
*What would have to be true for this to be wrong*.

#### E5-orch — the gap, reproduced independently by the orchestrator

This table is the load-bearing measurement of the whole document — the verdict
rests on it rather than on W1 — so it was re-derived with a probe **written from
the ONNX graph signatures and sharing no lines with `spikes/MT-030/*.py` or
`spikes/MT-002/*.py`**, living outside the repository. Deliberate differences,
so that agreement means reproduction rather than a re-run: PIL rather than cv2
for image IO; a coarse **41-point** sweep rather than 140; the reference
binarised at `>0` rather than `>=128`; and the metric computed at the
**reference's own 1654×1170 resolution by upsampling the model's map**, rather
than by downsampling the reference.

```
reference mask 1654x1170, 100344 px set
  comic-text-detector-onnx     in=[1, 3, 1024, 1024]  providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
incumbent comic-text-detector      peak IoU 0.7534 @ th 0.772 (recall there 0.8604)
                                     recall>=0.85 reachable at th 0.772 -> recall 0.8604, page masked 5.2%
  craft-mlt-25k                in=['batch_size', 3, 'height', 'width']  providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
CRAFT mlt-25k @2048                peak IoU 0.4471 @ th 0.574 (recall there 0.7669)
                                     recall>=0.85 reachable at th 0.549 -> recall 0.8661, page masked 10.5%
  PP-OCRv5_server_det_onnx     in=['DynamicDimension.0', 3, ...]        providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
PP-OCRv5 server det @1600          peak IoU 0.3819 @ th 0.054 (recall there 0.7634)
                                     recall never reaches 0.85 at any swept threshold

VERDICT: incumbent peak IoU 0.7534 vs best permissive 0.4471  -> ratio 1.68x
```
[MEASURED — orchestrator, 2026-09-12, this machine]

| Quantity | spike's harness | orchestrator's | agree? |
|---|---|---|---|
| reference mask pixels | 100,344 | **100,344** | yes — and matches MT-002 E6 exactly |
| incumbent peak IoU | 0.7137 | **0.7534** | same conclusion, orchestrator's is *higher* |
| CRAFT peak IoU | 0.4595 | **0.4471** | yes, within resampling noise |
| PP-OCRv5 server peak IoU | 0.3848 | **0.3819** | yes |
| incumbent ÷ best permissive | 1.55× | **1.68×** | **the gap reproduces, slightly wider** |

The script asserts `session.get_providers()[0] == "CUDAExecutionProvider"` and
aborts otherwise (P7); all three models selected CUDA. **The verdict stands on a
second, independent measurement.**

**One refinement this reproduction forces, and it matters for how the summary
table is read.** The sweep shows **CRAFT reaching recall 0.8661 at threshold
0.549 while masking 10.5% of the page** — so CRAFT is *not* disqualified by W1 as
a threshold-independent matter. It fires W1 only at the operating point the spike
chose. E-2 already established that W1 is gameable and used
`onnxtr-db-resnet50` as the example; the same objection applies to CRAFT, which
is the *best* permissive candidate and therefore the one it matters for.

**What actually rules CRAFT out is E5, not W1**: peak IoU 0.4471 against the
incumbent's 0.7534, and recall at equal precision 0.4568 against 0.9587. A
reader should not take "CRAFT → W1 fires" from the summary table as the reason.
The verdict is unchanged; its justification is the threshold-independent
comparison. [MEASURED / INFERRED — orchestrator]

### E6 — the SFX split (P3), measured on `012.jpg`

MT-002 observed that the box head is silent on the art-integrated パチ while the
`seg` mask covers them, and MT-007 AC-6 / MT-019 both depend on it. The audit
records no coordinates, so **six SFX glyph areas were annotated by hand at full
resolution** and drawn back onto the page for a visual check
(`spikes/MT-030/out/sfx-annotation-check.png`). Each rectangle sits on glyph
strokes and none touches a speech bubble.

Coverage of each SFX rectangle, by the box head and by the mask: [MEASURED]

| SFX area | incumbent boxes | incumbent mask | PP-OCRv5 srv | CRAFT | docTR R50 |
|---|---|---|---|---|---|
| S1 left panel パチ (left) | **0.000** | 0.343 | 0.652 | 0.082 | 0.351 |
| S2 left panel パチ (right) | **0.000** | 0.278 | 0.482 | 0.247 | 0.385 |
| S3 mid panel パチ (upper) | **0.000** | 0.272 | 0.460 | 0.297 | 0.453 |
| S4 mid panel パチ (lower) | **0.000** | 0.294 | 0.633 | 0.490 | 0.346 |
| S5 inset パ | **0.000** | 0.456 | 0.319 | 0.397 | 0.615 |
| S6 inset チ | **0.000** | 0.589 | 0.000 | 0.710 | 0.480 |

**The split is confirmed quantitatively for the first time:** the incumbent's box
head covers **exactly 0.000** of all six SFX areas while its mask covers 27–59%.
MT-002's observation holds and now has numbers behind it.

**And the split is unavailable in every alternative.** None of the permissive
candidates has a box head at all — the "boxes" column is not zero for them, it
does not exist. Each one masks the SFX at 8–71%. So **if the detector ever
changes, MT-007 AC-6 loses the mechanism it is designed around**, and MT-019
loses the `seg ∩ accepted boxes` construction MT-002 prescribed. P3 required this
to be said explicitly, because it is a cost the user is entitled to see before
choosing. [MEASURED]

---

## Licence and dataset texts

*AC-3 requires the actual text, not a summary. Each was fetched from the primary
source and re-read from the saved artefact before being quoted here.*

### (a) The incumbent's licence, where it bears on distributing a derived work

`dmMaze/comic-text-detector` `LICENSE` is the full, unmodified GNU General Public
License version 3 (35,149 bytes; the GitHub API reports `spdx_id: "GPL-3.0"`).
[WEB — `https://raw.githubusercontent.com/dmMaze/comic-text-detector/master/LICENSE`]

**§5, Conveying Modified Source Versions**, condition (c) — verbatim:

> c) You must license the entire work, as a whole, under this
> License to anyone who comes into possession of a copy.  This
> License will therefore apply, along with any applicable section 7
> additional terms, to the whole of the work, and all its parts,
> regardless of how they are packaged.  This License gives no
> permission to license the work in any other way, but it does not
> invalidate such permission if you have separately received it.

**§6, Conveying Non-Source Forms** — the operative opening and the two subsections
that bear on a downloadable installer, verbatim:

> You may convey a covered work in object code form under the terms of
> sections 4 and 5, provided that you also convey the
> machine-readable Corresponding Source under the terms of this License,
> in one of these ways:
>
>     a) Convey the object code in, or embodied in, a physical product
>     (including a physical distribution medium), accompanied by the
>     Corresponding Source fixed on a durable physical medium
>     customarily used for software interchange.
>
>     d) Convey the object code by offering access from a designated
>     place (gratis or for a charge), and offer equivalent access to the
>     Corresponding Source in the same way through the same place at no
>     further charge.

**[AGENT READING — not legal advice.]** §5(c) is the clause that makes GPL-3.0
"viral": it says a work that is a modified version of, or based on, the Program
must itself be licensed under GPL-3.0 in its entirety. §6 says that if you ship
the binary, you must also make the corresponding source available. Whether an
application that loads a GPL-3.0 project's *exported weights* at runtime is "a
work based on the Program" is **exactly the question this document cannot answer**
and the one on which the decision turns. It is contested in general and the
answer may differ for the weights file and for the pre/post-processing code
derived by reading upstream's `inference.py` — which MT-002 explicitly did, and
which MT-007 is instructed to re-derive. **This needs counsel, not an agent.**

### (b) The metadata disagreement, stated plainly

- Upstream `dmMaze/comic-text-detector`: **GPL-3.0**, the full licence file. [WEB]
- `mayocream/comic-text-detector-onnx`: `cardData: {"license": "apache-2.0"}`,
  and its entire README body is *"The ONNX model of the comic text detector."*
  with a link to the GPL-3.0 repo — i.e. it self-identifies as a re-upload. [WEB]
- **The same uploader labels another copy differently.** `mayocream/comic-text-detector`
  — the safetensors split of the same model — is tagged `license: gpl-3.0`. [WEB]

**[AGENT READING — not legal advice.]** One uploader tagging one copy Apache-2.0
and another GPL-3.0 looks like a metadata error rather than a relicensing anyone
had authority to perform. A third party generally cannot relicense someone else's
GPL-3.0 work by typing a different string into a model card. **Do not rely on the
`apache-2.0` tag.**

A second GPL vector, recorded for completeness: the incumbent's README says
*"Text block detector was trained using [yolov5 official repository]"*, and
Ultralytics is **AGPL-3.0** today [WEB — `LICENSE`, API `spdx_id: AGPL-3.0`].

### (c) The Manga109-s terms, as published

Fetched from `https://manga109.github.io/manga109-project-website/en/index.html`
(`http://www.manga109.org/en/` redirects there; `download_s.html` resolves to the
same page — the terms live in its licence section). Re-fetched independently by
the spike. [WEB]

**Manga109 — the full 109-volume set. This is the academic-only one:**

> Users are requested to strictly observe the following rules when using
> Manga109: The dataset is to be used for academic purposes by non-commercial
> organizations. Data shall not be transferred to a third party.

**Manga109-s — the 87-volume subset the incumbent actually used. Materially
different, and this is the finding that changes the premise:**

> Among the works contained in the Manga109 dataset, 87 books are available for
> commercial use, under the following conditions. This special subset of the
> Manga109 dataset is available as the Manga109-s dataset (hereby referred to as
> "the dataset").

Permitted uses include, verbatim:

> Using the Manga109-s dataset for experiments for machine learning or image
> processing.

> Using results, or portions of results, obtained from machine learning
> experiments or image processing experiments, for commercial use.

Conditions, verbatim:

> Redistribution of the Manga109-s dataset to third parties is forbidden.

> When publishing results (including pre-trained models) obtained from machine
> learning experiments or image processing experiments, the use of the Manga109-s
> dataset must be indicated clearly within the published work.

> Selling manga images within the dataset together with results obtained from
> machine learning or image processing experiments is forbidden.

> Direct copies or modifications of the manga images within the Manga109-s
> dataset must not be treated as products, regardless of the product being either
> free or being sold for a fee.

**Added by the orchestrator, 2026-09-12, on independent re-fetch.** The list
above originally stopped at four conditions; the published text has **five**, and
a list presented as *the* conditions that silently drops one is the exact failure
AC-3 exists to prevent. The fifth, verbatim: [WEB — re-fetched by the
orchestrator, see the Verification note below]

> For all uses from Number 1 to 5 when publishing whole pages (or modifications
> of whole pages) of the manga works contained within the dataset for the purpose
> of presenting the results of research and development, the total number of
> whole pages (including modifications of whole pages) to be published must not
> exceed 20% of the entire book (volume), for each of the books (volumes) in the
> dataset. Publishing over 20% of whole pages or modifications of whole pages of
> any book (volume) is forbidden.

It does not change the conclusion — this product publishes no manga pages from
the dataset at all — but it is now in front of the reader rather than elided.

**Verification note — the orchestrator re-fetched these terms independently**
before accepting the finding, because it contradicts this story's own
`## Context`, `stack.md` and the MT-002 audit. Different entry URL, different
extraction code, outside the repository:

```
$ python -c "urlopen('http://www.manga109.org/en/download_s.html')"
final URL: https://manga109.github.io/manga109-project-website/en/index.html 31003 bytes
saved 10781 chars
```

The extracted text carries, at separate points in the page:

```
line 238:  academic purposes by non-commercial organizations          <- Manga109 (full)
line 250:  87 books are available for commercial use                  <- Manga109-s
line 258:  for commercial use            <- closing "Using results ... for commercial use."
```

And the incumbent's own README, fetched from
`raw.githubusercontent.com/dmMaze/comic-text-detector/master/README.md`:

```
All models were trained on around 13 thousand anime & comic style images,
1/3 from Manga109-s, 1/3 from DCM, and 1/3 are synthetic data in a weak
supervision manner due to the lack of available high-quality annotations.
```

**Manga109-s**, not Manga109. The finding is confirmed on both halves: the
subset the incumbent names is the commercial-use one, and its terms say so.
[MEASURED — orchestrator, 2026-09-12]

**[AGENT READING — not legal advice.]** This app ships a *model*, not the
dataset, and does not sell manga images. On the face of the text the first two
permitted uses cover what the product does, and the binding condition is the
attribution one. **The Manga109-s objection recorded in `stack.md` and in MT-002
does not survive reading the terms.** Note that candidate #9 in E3 cites the
*full* `manga109`, where the academic-only restriction does apply and is fatal.

---

## What would have to be true for this to be wrong

- **That the reference mask is a fair yardstick.** It is the *incumbent author's
  own published output* on a page from the incumbent's own training-data
  distribution. The incumbent is being graded against its own lineage's answer
  key. A generic detector scoring 0.46 IoU against it is not necessarily 0.46 as
  good at finding manga text — it is 0.46 as good at *agreeing with this
  detector's idea of a text mask*. **This is the largest caveat in the document.**
  It biases every comparison in the incumbent's favour, and no independent
  manga text-mask ground truth was available within the timebox.
- **That recall against a refined mask is the right quality axis at all.** MT-007
  will refine the raw mask. A candidate whose raw map is fatter but better shaped
  could refine to something better than its raw score suggests. Refinement was
  not implemented here — it is MT-007's and out of scope.
- **That greyscale input makes channel order irrelevant.** Measured true on these
  fixtures; a colour cover page or a colour insert would not satisfy it.
- **That the sweeps found each candidate's best configuration.** Resolution,
  padding, channel order and threshold were swept; input *tiling* was not, and a
  detector fed 1024² tiles of a 1125×1600 page might do markedly better on small
  text. Not attempted — see below.
- **That `preload_dlls` remains required.** Asserted at dispatch and consistent
  with all nine loads here, but not re-falsified: no session was constructed
  without it, because the call is process-global and cannot be undone.

## What was not checked

Honest list, per the story's timebox instruction.

1. **Tiled inference for the generic detectors.** docTR's graphs are fixed at
   1024², and a 1125×1600 page downscaled to 1024 makes manga text small. Feeding
   four overlapping tiles could plausibly move DBNet's recall materially. **This
   is the single most likely way the negative finding could be wrong**, and it was
   left out because it is a post-processing design this spike may not choose.
2. **MMOCR DBNet++.** No pre-built ONNX; the MMDeploy export was outside the
   timebox. Same generic-text family as PaddleOCR and docTR, both of which
   measured far below the floor, so the expected value of building it was low.
3. **Fine-tuning any candidate on manga.** Explicitly out of scope — if a detector
   must be commissioned, that conclusion is the deliverable, not the model.
4. **The `juvian` MIT lineage as a runnable model.** Identified as the licence-clean
   manga-native route; no ONNX export was built and its 2025 successor's weights
   carry no licence. Unmeasured.
5. **Whether the incumbent's pre/post-processing is itself a derived work.** MT-002
   wrote it by reading upstream's `inference.py`. Whether re-deriving it test-first
   in MT-007 changes the GPL position is a legal question, flagged not answered.
6. **The `ogkalu` weights' actual licence.** The `apache-2.0` is an HF tag with no
   upstream repository behind it — the same shape of unverifiable claim as the
   incumbent's. Moot, since P1 rules it out anyway.

---

## Reproducing any of this

Everything ran in the surviving MT-002 spike venv. No new environment was needed
and nothing was installed.

```bash
cd /c/Users/ryanc/Projects/manga-translator
V=spikes/MT-002/.venv/Scripts/python.exe

# E1  - reproduce the incumbent baseline, independently written
PYTHONIOENCODING=utf-8 $V spikes/MT-030/baseline.py

# E2  - re-derive and re-read the nine confirmed text regions on 014.jpg
PYTHONIOENCODING=utf-8 $V spikes/MT-030/w2ref.py

# E-1 - the W3 count-column probe
PYTHONIOENCODING=utf-8 $V spikes/MT-030/w3_probe.py

# E6  - draw the SFX annotation, then the incumbent's split
PYTHONIOENCODING=utf-8 $V spikes/MT-030/sfx.py
PYTHONIOENCODING=utf-8 $V spikes/MT-030/incumbent_sfx.py

# E4  - configuration sweeps, then the six-page run for each candidate
PYTHONIOENCODING=utf-8 $V spikes/MT-030/run_paddle.py sweep
PYTHONIOENCODING=utf-8 $V spikes/MT-030/run_onnxtr.py sweep
PYTHONIOENCODING=utf-8 $V spikes/MT-030/run_craft.py  sweep
PYTHONIOENCODING=utf-8 $V spikes/MT-030/run_incumbent.py
PYTHONIOENCODING=utf-8 $V spikes/MT-030/run_paddle.py  PP-OCRv5_server_det 1600 BGR
PYTHONIOENCODING=utf-8 $V spikes/MT-030/run_onnxtr.py  onnxtr-db-resnet50 0 0.15
PYTHONIOENCODING=utf-8 $V spikes/MT-030/run_craft.py   2048 1.5 0.3

# E5  - the threshold-independent comparison
PYTHONIOENCODING=utf-8 $V spikes/MT-030/isoprecision.py
```

Raw results are the JSON files in `spikes/MT-030/out/`; the fetched licence texts
and terms pages are in `spikes/MT-030/research/`. **Both trees are gitignored and
neither is committed** (`.gitignore:76: spikes/`).

## Unreviewed code — nothing later may reuse this

Everything under `spikes/MT-030/` is **throwaway, unreviewed, untested spike code**
written by the Lead PO outside the RED→GREEN cycle, exactly as `spikes/MT-002/`
is. It exists only to produce the numbers above. The pre- and post-processing in
it — letterboxing, normalisation constants, sigmoid placement, thresholds,
connected-component floors — was written by reading each project's shipped config
and source and is **unverified by any test**. MT-007 re-derives what it needs
test-first and copies nothing.

## Fixtures, and their provenance

Unchanged from MT-002, and the constraint MT-002 recorded still binds:

- `spikes/MT-002/pages/011–015.jpg` — user-supplied pages from a commercial
  digital release with scanlation watermarks burned in. **Non-redistributable,
  held only in the gitignored `spikes/` tree, never committed.** MT-007 and
  MT-023 need their own licensed or synthetic fixtures; **EPIC-03 cannot be shown
  done by anything CI can re-run** until they exist. Noted at dispatch (story
  PO-2) and unchanged by this spike.
- `spikes/MT-002/oracle/ctd/*` — `AisazuNihaIrarenai-003.jpg` and the author's
  reference mask, from the GPL-3.0 `dmMaze/comic-text-detector` `data/`. The page
  is from Manga109. Used as the reference oracle in E1 and E5.
