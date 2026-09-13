# Stack — manga translator

> **Verified in part, on 2026-09-12, by story MT-001 (bootstrap), on the
> development machine** (Windows 11 Home 10.0.26200, Ryzen 5 7600X, RTX 5070,
> uv 0.12.13, CPython 3.12.14).
>
> **What was verified:** every version in §3 *Runtime and packaging* and
> *Development tooling* is now what `uv.lock` actually locked, not a candidate.
> All nine gate commands in §6 were executed; the `format`, `lint`, `typecheck`,
> `unit`, `coverage`, `coverage-core` and `build` gates passed against the
> walking skeleton, `integration` collects nothing yet and is waived, and
> `mutation` is waived. Every `evidence` line matched real output. The three
> `floor` lines were set from that run. `bash scripts/task.sh dev` opened a Qt
> window. **Two** commands in §6 were changed against what this document
> originally researched, both by MT-001 and both recorded in §6: the
> `ruff-sees-src` discovery line was **wrong** and is corrected, and the `lint`
> **gate command** now carries that same reach assertion, because MT-001's GATES
> phase measured the gate passing with `Contracts: 1 kept` while `ruff` had
> checked none of this project's source. See the notes in §6.
>
> **Verified further on 2026-09-12 by story MT-002 (spike):** §3 *Local
> inference* and *Models* are no longer guesses. Every version and every model
> file in them was installed and run on this machine, and the ONNX-versus-PyTorch
> question is settled in ONNX Runtime's favour — see
> `docs/wiki/audits/MT-002-model-runtime.md`. Two things the plan had wrong are
> corrected in place there and in §3: `onnxruntime-gpu` needs an explicit
> `preload_dlls()` call or it silently runs on CPU, and D3's installer-size
> rationale does not survive measurement.
>
> **What is still unverified, and where it is owned:** §3 *Cloud translation* in
> full, and the *installed-nowhere* status of *Local inference*. **No inference
> runtime and no `anthropic` client is pinned at all** — MT-001's sizing rule
> forbids adding a dependency nothing imports, so MT-002 deliberately did not add
> one (PO-1); **MT-007** adds the inference lines and the `anthropic` client
> arrives with the story that first calls it. The cost model remains an estimate.
> Do not read a version in the *Cloud translation* table as a fact.

*Written by `/plan-product` on 2026-09-12 from `docs/wiki/product-brief.md`.
Planned by **lead-po on Claude Opus 5 (`claude-opus-5`)**, no session override.
The design system in `docs/wiki/design/**` was produced by **lead-designer on
Claude Opus 5 (`claude-opus-5`)**, dispatched by lead-po.
Corrected against a real install by **lead-po on Claude Opus 5
(`claude-opus-5`)** during MT-001 on 2026-09-12.*

Companion documents: `docs/wiki/architecture.md` (components, data, decisions),
`docs/wiki/design/**` (tokens, components, accessibility floor).

---

## 1. The shape of the problem, and what it forces

Four constraints in the brief do most of the choosing:

| Brief constraint | What it forces |
|---|---|
| Windows 11 desktop, local, single user, no server | A native desktop app, not a web service. One process. No auth, no multi-tenancy, no deployment. |
| "Installation must not require the user to manage Python environments, model weights or GPU setup by hand" | A frozen, signed-ish installer that carries the interpreter, the dependencies **and** the model weights. This is a *packaging* requirement, not a language requirement. |
| RTX 5070 (12 GB) available; detection and inpainting are not LLM tasks | Local GPU inference. That means the ML ecosystem, which is Python or ONNX. |
| **Under $2 per ~20-page chapter** in API spend | The LLM is called once per page, with the smallest image that still carries the art, and the token accounting is a first-class product feature, not a log line. |

Plus one from section 8: "the art is the largest thing on screen at all times…
closer to a photo editor than to a form". That is a canvas with pan, zoom and
overlay items — not a document-flow layout.

## 2. Profile

Base profile: **`python-uv`** (`.claude/skills/stack-profiles/reference/python-uv.md`).

It does not cover three things this project needs — a Qt GUI under test, a
frozen-binary build gate, and GPU inference that CI cannot run — so an addendum
profile is written alongside it:
`.claude/skills/stack-profiles/reference/python-uv-pyside6.md`. Read both.

## 3. Languages, frameworks, libraries

**Two kinds of row live in this section and they are not equally true.**
*Runtime and packaging* and *Development tooling* below are **locked**: the
version column is what `uv.lock` holds, read out of the lockfile on 2026-09-12
by MT-001. *Local inference*, *Models* and *Cloud translation* are still
**candidates and are installed nowhere** — nothing in `pyproject.toml` names
them. MT-002 settles the inference trio; the `anthropic` client arrives with the
story that first calls it.

### Runtime and packaging

| Thing | Locked version | Candidate at planning | Why — tied to a constraint |
|---|---|---|---|
| Python | **3.12.14** (`.python-version` pins `3.12`; `requires-python = "==3.12.*"`) | 3.12.x | The ML and Qt wheel ecosystem is Python. 3.12 rather than 3.13 because `onnxruntime` and `PySide6` wheel availability has historically lagged a release behind, and this project cannot afford a "no wheel for your Python" stall on the machine it must install cleanly on. |
| `uv` | **0.12.13** | 0.8.x | Single self-contained binary; manages the interpreter *and* the venv, so the user installs one thing. Also the only reliable way to invoke Python on Windows from bash — see §7. The candidate was four minor versions stale; `winget` installed 0.12.13 and nothing depended on the difference. |
| PySide6 | **6.9.3** (`pyside6-essentials`, `pyside6-addons`, `shiboken6` all 6.9.3) | 6.8.x (Qt 6.8 LTS) | The "photo editor, not a dashboard" workspace is a `QGraphicsView`/`QGraphicsScene` with pan, zoom and overlay items — a solved problem in Qt and a from-scratch project in most alternatives. LGPL, so redistributable in an installer without a commercial Qt licence. **Not the 6.8 LTS the plan named**: `>=6.8,<6.10` resolved to 6.9.3. Qt 6.9 is not an LTS line. If LTS turns out to matter for the installer story, pin it there and say why — nothing measured so far needs it. |
| PyInstaller | **6.22.3** (+ `pyinstaller-hooks-contrib` 2026.7) | 6.x | Produces a one-folder Windows build carrying the interpreter, the venv and the `.onnx` weights. This is the *only* thing that satisfies "must not require the user to manage Python environments, model weights or GPU setup by hand". **Measured 2026-09-12:** 34 s and a 111 MB `dist/mangatl/` with PySide6 alone and no weights. |
| Inno Setup (or PyInstaller one-folder + a zip) | *not installed* | 6.x | Turns the PyInstaller output into a double-clickable installer. Deferred to MT-024; not a build-gate dependency. |

### Local inference

> **VERIFIED on the development machine on 2026-09-12 by MT-002** (spike;
> `docs/wiki/audits/MT-002-model-runtime.md`). All three models load and run on
> the **CUDA execution provider** on the RTX 5070 (sm_120). **Still installed
> nowhere** — PO-1 keeps MT-002 document-only, and MT-007 is the story that adds
> these lines to `pyproject.toml`. The candidate column is kept, as everywhere in
> this section, so that a version that moved is visible rather than quietly
> overwritten.
>
> **Read the audit before depending on a number here.** Its `## Decided` section
> may be taken on trust; every measurement is in `## Evidence` and is to be
> re-verified by the story that depends on it.

| Thing | Measured 2026-09-12 (MT-002) | Candidate at planning | Why |
|---|---|---|---|
| `onnxruntime-gpu` | **1.30.0**, CUDA EP confirmed in use | 1.22.x (CUDA EP) | Detection, OCR and inpainting run locally (decision O3, §5). **Two corrections from MT-002.** (1) The extra is required — `onnxruntime-gpu[cuda,cudnn]`, and it pulls **cu13**, not cu12; 1.30 is built against CUDA 13. (2) **`ort.preload_dlls(cuda=True, cudnn=True, msvc=True)` must be called before the first session or the CUDA provider silently fails to CPU** while still being advertised by `get_available_providers()`. This is application code, not configuration. See audit E2. |
| `onnxruntime-directml` | **not installed, not run** | 1.22.x | Latest cp312 wheel is **1.17.3** (PyPI, read not run), four minor versions behind, and it **conflicts** with `onnxruntime-gpu` — both provide the `onnxruntime` module. So "CUDA → DirectML → CPU" is **not one install with a provider chain**; it is two mutually exclusive installs. MT-024 owns the consequence. See audit E8. |
| `numpy` | **2.5.3** | 2.1.x | Tensor pre/post-processing. |
| `Pillow` | **12.3.0** | 11.x | Image decode/encode, page I/O, output baking. |
| `opencv-python-headless` | **5.0.0.93** | 4.11.x | Mask morphology, connected components, region merging for the detector's raw output. **Headless** deliberately: the GUI is Qt, and `opencv-python` (non-headless) drags in a second, conflicting Qt. |
| `fonttools` | *not exercised by MT-002* | 4.5x.x | Real glyph metrics for the typesetter's line-breaking and fitting. Measuring text by character count is how machine typesetting looks like machine typesetting. |

**The installer-size argument in D3 did not survive measurement.** `architecture.md`
D3 rejected `torch` for being "~2.5 GB". Measured, the working CUDA path costs
**1,798 MiB of runtime** (`onnxruntime` 218 MiB + `nvidia-*` cu13/cuDNN 1,580 MiB)
**plus 728 MiB of weights ≈ 2.47 GiB**. D3's *conclusion* still holds — ONNX
Runtime is the right choice — but for a different reason: a CUDA-less install is a
15 MB wheel and the same code runs on DirectML or CPU. D3's recorded rationale
should be corrected; that is an architecture edit and MT-002 did not make it.

**Models** (weights, not libraries — versions are file hashes, pinned in the
model manifest, not in `pyproject.toml`):

| Role | Settled 2026-09-12 (MT-002) | Candidate at planning | Note |
|---|---|---|---|
| Text-region detection | `mayocream/comic-text-detector-onnx` → `comic-text-detector.onnx`, 90 MiB | a comic/manga text detector exported to ONNX (the `comic-text-detector` lineage ships one) | Emits both a `seg` mask and YOLO boxes. **They disagree**: the box head does not fire on art-integrated SFX but the mask covers them, so MT-019 must inpaint `seg ∩ accepted boxes`, never the raw mask. **Licence risk — GPL-3.0 upstream, partly trained on Manga109-s; needs a user decision before EPIC-03 ships.** Audit E6, E7. |
| Japanese manga OCR | `onnx-community/manga-ocr-base-ONNX` (encoder 328 MiB + decoder 112 MiB) + vocab from `kha-white/manga-ocr-base` | `manga-ocr` (ViT encoder + GPT-2 decoder), exported to ONNX via `optimum` | Chosen for O6, and **O6 is confirmed**: a crop of 醜鬼 with ruby しゅうき read back as 醜鬼, ruby dropped. 10/12 exact on the upstream author's own ground-truth set (greedy decode; the reference uses 4 beams, so that is a lower bound). **It hallucinates confident Japanese on text-free crops** — the detector alone decides what is text. Audit E5. |
| Inpainting | `Carve/LaMa-ONNX` → **`lama_fp32.onnx`**, 198 MiB | LaMa, ONNX export (the IOPaint / lama-cleaner lineage ships one) | **Not `lama.onnx`** — that build fails to load in onnxruntime 1.30. Fixed **512×512** input, so a page must be tiled; seams are unmeasured and MT-019 owns them. Reconstructs screentone at 93% of the original high-frequency energy. Audit E3, E7. |

Exact URLs, **SHA-256 for every file**, and licences are in the audit's
`## Decided`. Bundle total **728.2 MiB** measured.

**This trio was the largest single risk in the plan, and MT-002 retired it.** The
claim "usable ONNX exports of all three exist and run on an RTX 5070 (Blackwell,
sm_120) under `onnxruntime-gpu`" is now **verified on the development machine**:
detector 25.8 ms/page, OCR 26.7 ms/crop, LaMa 105 ms/512² tile, all on
`CUDAExecutionProvider`, cross-checked at 22×, 6× and 15× the CPU-forced
latency on the same machine. **The `torch` + `cu128` fallback is not needed and
should not be added.** What replaced the risk is a smaller one — the GPL-3.0
detector licence, and 1.75 GB of CUDA runtime — both recorded in the audit.

### Cloud translation

| Thing | Candidate version | Why |
|---|---|---|
| `anthropic` (Python SDK) | 1.x | Official SDK for the chosen model. |
| Model | **`claude-opus-5`**, adaptive thinking, `output_config.effort: "medium"` | Decision O4, §5. The brief's axis is accuracy, and this is the strongest model whose cost survives the $2 ceiling with headroom. |
| Fallback model | `claude-sonnet-5` | Configurable, for a user who wants a cheaper run; ~40% of the Opus 5 cost at the same call shape. |

### Development tooling

Locked by `uv.lock` on 2026-09-12 and read out of it, not out of a terminal.
Every one of these is installed; the candidate column is kept so that a version
that moved a long way is visible rather than quietly overwritten.

| Thing | Locked version | Candidate at planning | Role |
|---|---|---|---|
| `pytest` | **8.4.2** | 8.3.x | Test runner. |
| `pytest-cov` | **7.1.0** | 6.x | Coverage gate. A major version ahead of the candidate; nothing in the two coverage gate commands needed changing. |
| `pytest-qt` | **4.5.0** | 4.4.x | Drives Qt widgets in tests. |
| `pytest-env` | **1.2.0** | *not named at planning* | Sets `QT_QPA_PLATFORM=offscreen` from `[tool.pytest.ini_options]`, so `uv run pytest` by hand behaves like the gate. The plan required that behaviour without naming the plugin that provides it. |
| `coverage` | **7.16.0** | *transitive* | The engine under `pytest-cov`; named here because the `cov-domain` discovery line invokes `uv run coverage` directly. |
| `hypothesis` | **6.168.0** | 6.x | Property tests for reading order, line breaking and the round-trip of the project store. Installed, unused at MT-001. |
| `ruff` | **0.16.7** | 0.12.x | Linter **and** formatter. Four minor versions ahead of the candidate and **it behaves differently**: 0.16 formats Python code blocks inside Markdown, so `ruff format .` reported 115 files (17 Python, 98 Markdown under `.claude/` and `docs/`). `pyproject.toml` now carries `extend-exclude = [".claude", "docs", "fixtures", "*.md"]` so the formatter stays inside this project's own code. See §6 and MT-001 PO-4. |
| `mypy` | **1.20.2** | 1.11.x | Type checker, `strict = true`, with `ignore_missing_imports` narrowed to `PySide6.*` and nothing of ours. |
| `import-linter` | **2.15** (with `grimp` 3.17) | 2.x | **Architectural boundary gate.** `architecture.md` §3 states five contracts; **one** is configured at MT-001 (*"Nothing imports `ui`"*) purely so the `lint` gate's evidence line has something to assert. MT-003 writes the other four, probes all five, and must raise `floor | lint` from 1 to 5. |
| `mutmut` | *not installed* | 3.x | Optional mutation gate, waived in `project.conf`. |

## 4. Layout

```
src/mangatl/
  domain/      pure model: Page, Region, ReadingOrder, Line, CostRecord, Budget
  store/       SQLite project store (chapter state, resumable runs, cost ledger)
  detect/      text-region detection; ONNX adapter + pure pre/post-processing
  ocr/         manga OCR; ONNX adapter + pure pre/post-processing
  translate/   LLM client, prompt assembly, page context, cost accounting
  clean/       inpainting; ONNX adapter + mask logic
  typeset/     font metrics, line breaking, fitting, rendering into the bubble
  pipeline/    stage orchestration, resumability, progress events
  bench/       the S1/S2/S5 measurement harness
  ui/          PySide6 workspace (imports everything; imported by nothing)
  app.py       entry point
tests/
  core/        pure tests: domain, typeset, bench, and every adapter's
               pre/post-processing against a FAKE inference session. No GPU,
               no network, no display. Runs on CI.
  ui/          pytest-qt, QT_QPA_PLATFORM=offscreen. Runs on CI.
  integration/ marked `gpu` and/or `network`. Real .onnx files, real API.
               Does NOT run on CI. See §6.
fixtures/      page scans, ground-truth regions, recorded API responses
packaging/     mangatl.spec, model manifest, installer script
pyproject.toml deps, ruff/mypy/pytest/coverage/import-linter config — one file
uv.lock        committed
```

**The split inside each adapter package is load-bearing** and exists to defeat
the exact trap `quality-gates` describes. Detection, OCR and inpainting cannot
run on a CI machine with no GPU. If their tests all live in an `integration`
gate marked optional, then every *required* gate can pass over a story whose
artifact nothing exercised. So each adapter is two things:

- **the logic** — tensor shaping, thresholding, region merging, furigana
  suppression, mask dilation, decode post-processing — which takes an injected
  session object and is tested in `tests/core/` with a fake one. This is where
  the acceptance criteria live, and a **required** gate reads it;
- **the session** — loading a real `.onnx`, choosing a provider — which is a
  thin smoke test in `tests/integration/`.

A story that puts its central claim in `tests/integration/` must declare
`required_gates: [integration]` in its frontmatter. Better still, it should not
need to.

## 5. Decisions the brief left to `/plan-product`

### O2 — what counts as "a line accepted as-is"

**Unit: one text region.** Not a sentence, not a page.

**Definition, mechanical:** a region's proposed line is *accepted as-is* when
`norm(proposed) == norm(final)`, where `final` is the string present when the
user pressed render, and `norm` is:

1. Unicode NFC normalisation;
2. every run of whitespace (including the app's internal line-break markers)
   collapsed to a single space;
3. leading and trailing whitespace stripped.

`norm` does **nothing else**. A one-word fix is a rejection. A punctuation
change is a rejection. A capitalisation change is a rejection. Deleting the line
is a rejection. Editing a line and then restoring it character-for-character is
an acceptance, because the metric compares strings and not history — which is
deliberate: it measures the output, not the user's mouse.

**Two numbers, always reported together, and neither is ever suppressed:**

- **S1b — chapter acceptance** = accepted / *ground-truth region count*, where
  the ground truth is a human-made region list that ships with the benchmark
  chapter. A region the detector missed contributes 0 to the numerator and 1 to
  the denominator. **This is the headline, and the brief's 80% bar attaches to
  it** — *decided by the user on 2026-09-12, resolving O2.*
- **S1a — translation acceptance** = accepted / *proposed*. Diagnostic, not a
  bar. It answers "of what the detector found, how good was the translation?",
  which is the question you need answered when S1b is low.

**The gap between them is the diagnosis.** With no spurious detections the two
are related exactly:

    S1b = S1a x recall

so a large gap means fix the detector and a small gap with a low S1b means fix
the translation. That identity is a testable claim, not a slogan, and MT-022
asserts it.

The brief's wording was "80% of translated lines", which read literally is S1a —
and S1a is a blind metric in exactly the way `story-authoring` warns about: a
detector that finds only the five easiest bubbles on a page scores 100% on it.
Planning put both numbers to the user and they took the unconditional one,
knowing it is strictly harder to hit.

**A "report is void if detection recall < 95%" rule was proposed and has been
dropped.** It existed solely to stop S1a being read as the headline when
detection was bad. With S1b as the headline, poor detection lowers the headline
directly and proportionally — the metric's own construction does the work — so
the rule guarded nothing. Worse, it suppressed S1a exactly when recall was poor,
which is precisely when S1a is most diagnostic. Removing it is not a relaxation;
it restores a number the rule was throwing away. Recall is still reported on
every run, and is a criterion of its own under S2 (MT-023).

**What S1b is blind to, and where that is caught instead.** A missed region
lowers S1b. A *spurious* region — a phantom bubble where there is no text — does
not: it is absent from the ground truth, so it changes neither numerator nor
denominator. S1a partly covered this, since a phantom diluted its denominator,
and the headline no longer does. So the report **must** carry the spurious count
beside S1b (MT-022 AC-1, AC-9), and spurious detections are a first-class
reported failure under S2 (MT-023 AC-3). Do not read S1b alone.

**Negative controls for the metric itself** (required by `story-authoring`; the
measurement is a metric, so it needs controls, and these belong in MT-022):

| Control | What it breaks | Required result |
|---|---|---|
| Rotate the proposed lines by one region | The metric's ability to notice that the right words are on the wrong bubbles | ≈ 0% on **both** numbers. A metric that scores this near the real run is measuring nothing. |
| Replace every final with its NFD form, plus doubled interior spaces | Whether `norm` does what it claims | **100%** acceptance. |
| Change one character in every final (e.g. `.` → `!`) | Whether `norm` over-normalises | **0%** acceptance. |
| Drop 30% of regions from the detector output | Whether the headline is coupled to detection | S1a unchanged, **S1b down by ≈ 30%** — the whole point of the user's decision. |
| Add 1,000 spurious regions | Whether the report exposes what S1b cannot see | S1b **unchanged**, S1a falls, spurious count reported non-zero. |

### O3 — detection, OCR and inpainting: local or cloud

**All three local.** The cloud LLM is used for translation only.

- **Detection — local.** The downstream consumers need pixel masks, not prose:
  the inpainter needs a mask to erase, the typesetter needs a polygon to fit
  into. An LLM returns neither reliably, and asking one for coordinates is the
  most expensive way to get the worst boxes.
- **Inpainting — local.** Not an LLM task in any sense; the output is pixels.
- **OCR — local, with the LLM as corrector.** This is the one that was a real
  choice. `manga-ocr` is a small model trained specifically on manga text
  crops; it is strong on vertical text and stylised lettering, which is where
  general OCR fails on this material. Running it locally costs nothing and adds
  ~50 ms/region. The LLM then receives *both* the OCR text and the page image,
  so it can silently correct an OCR miss it can see — which is the safety net
  that makes the cheap option safe.

  *Alternatives and why they lost:*
  - **LLM-only OCR** (send the page, ask for Japanese + English). Better on
    heavily stylised text, but it needs a full-resolution page image to read
    small kanji and furigana, and full resolution is 7,900–10,900 image tokens
    per page against 2,296 at the capped size — 3.4×–4.7× the input cost. It
    also gives no reliable region↔text alignment, and alignment is what the
    typesetter and the bubble↔line link are built on. See O4 for the numbers:
    designs B and C are the ones that eat the budget.
  - **A cloud OCR API** (Google Vision and similar). A second vendor, a second
    bill, a second failure mode, and weaker than `manga-ocr` on vertical manga
    lettering specifically.

### O4 — which model, and does the $2 ceiling survive

**Model: `claude-opus-5`**, one call per page, adaptive thinking,
`output_config.effort: "medium"`, with the stable prefix prompt-cached.

**The ceiling survives, with roughly 43% headroom — but only because of the
O3 decision.** The estimate, from Claude's documented image-token rule
(`tokens ≈ width × height / 750`, long edge capped at 1,568 px) and the
published Opus 5 rates ($5/MTok in, $25/MTok out, cache write 1.25×, cache
read 0.1×):

Per page, design A: page image at 1,568 px long edge = **2,296 tokens**;
`manga-ocr` output for ~20 regions ≈ 500 tokens; rolling context (previous
page's English, running glossary) ≈ 900 tokens. Output ≈ 700 visible + ≈ 800
adaptive-thinking tokens. Stable prefix (system prompt, lettering style guide,
glossary header) ≈ 1,500 tokens, cache-written once and read 19 times.

| Design | Per 20-page chapter |
|---|---|
| **A — local OCR, page image capped at 1,568 px (chosen)** | **$1.14** |
| A + 20% of pages re-run after an edit | $1.37 |
| A on `claude-sonnet-5` instead | $0.46 |
| B — LLM does the OCR, 2048×2896 page image | $1.65 |
| C — LLM does the OCR, 2400×3400 page image | $1.95 |
| D — design A but two LLM passes per page | **$2.29 — over** |

Reproduce with `awk -f docs/wiki/cost-model.awk`; the numbers above came from
that script, and MT-010 replaces its assumptions with measured
`response.usage` values.

Three things follow, and they are architecture, not preference:

1. **The page image is capped at 1,568 px on the long edge before it is sent.**
   Sending the raw scan is the difference between $1.14 and $1.95.
2. **One LLM call per page.** Design D is over the ceiling on its own. A retry
   path exists, but the budget guard prices retries before making them.
3. **The ceiling is enforced in code, not hoped for.** `translate` reads
   `response.usage` off every response, prices it from a pinned rate table,
   writes it to the ledger, and the run aborts when projected chapter cost
   crosses the configured ceiling (default $2.00). MT-010 is that story.

The estimate is unverified in one respect that matters: **the adaptive-thinking
output is a guess.** Thinking tokens bill as output at $25/MTok, so if Opus 5
thinks 3,000 tokens per page instead of 800, design A becomes $2.24 and the
ceiling fails. MT-009's acceptance criteria therefore require the *measured*
mean output tokens per page to be recorded, and MT-010's budget guard is what
makes a bad guess safe rather than expensive.

### O6 — vertical text and furigana

**Handled by the OCR path, but not for free — it needs two explicit
behaviours, and they get acceptance criteria of their own (MT-008).**

- **Vertical text: handled by model choice.** `manga-ocr` is trained on manga
  crops in their native orientation; it reads vertical columns directly with no
  rotation step. The pre-processing must therefore *not* deskew or rotate a
  crop to horizontal — a "helpful" rotation is the failure mode here.
- **Furigana: handled at the region level, then at the model level.** Ruby text
  is a thin column (or row) adjacent to the main text and is *not* a separate
  utterance; a detector that emits it as its own region produces a phantom
  bubble with a phantom translation on the review screen. So the region
  post-processing merges a thin region into an adjacent main region when it is
  within a furigana-plausible distance and below a width/height ratio threshold,
  rather than passing it on. `manga-ocr` is additionally trained to ignore ruby
  *inside* a crop, which covers the case where the detector merged them already.
- **Right-to-left, top-to-bottom reading order** over the merged regions is a
  pure function on geometry and is its own story (MT-007), not part of OCR.

The three thresholds this introduces (merge distance, ratio, minimum region
area) are numbers, so MT-008's criteria carry negative controls: a fixture page
with furigana on every bubble must produce the same region count as the same
page with the ruby removed, and a fixture with two genuinely adjacent small
bubbles must **not** merge them.

## 6. Gates

Proposed `project.conf` content. Every command goes through `uv run` — see §7.

```
gate | format        | optional | . | uv run ruff format --check .
gate | lint          | required | . | uv run ruff check . && uv run ruff check --no-cache --show-files . | grep -qE "src.mangatl.*[.]py" && uv run lint-imports
gate | typecheck     | required | . | uv run mypy src
gate | unit          | required | . | uv run pytest -q tests/core tests/ui
gate | coverage      | required | . | uv run pytest -q tests/core tests/ui --cov=src/mangatl --cov-report=term-missing --cov-fail-under=90
gate | coverage-core | required | . | uv run pytest -q tests/core --cov=src/mangatl/domain --cov=src/mangatl/typeset --cov=src/mangatl/bench --cov-report=term-missing --cov-fail-under=100
gate | integration   | optional | . | uv run pytest -q tests/integration -m "gpu or network"
gate | build         | required | . | uv run pyinstaller --noconfirm packaging/mangatl.spec
gate | mutation      | optional | . | uv run mutmut run
```

**Why two coverage gates.** `domain`, `typeset` and `bench` are pure, are where
the product's correctness actually lives, and have no excuse for an untested
line — 100%. The rest of the tree contains Qt event plumbing and ONNX session
setup where a 100% bar buys `# pragma: no cover` comments rather than tests —
90%. The alternative (one gate at 100% with liberal pragmas) was rejected
because a pragma is invisible in the gate output and a second gate is not.

### Evidence lines

```
evidence | format        | [1-9][0-9]* files? (already formatted|would be reformatted)
evidence | lint          | Contracts: [1-9][0-9]* kept
evidence | typecheck     | Success: no issues found in [1-9][0-9]* source file
evidence | unit          | [1-9][0-9]* passed
evidence | coverage      | [1-9][0-9]* passed
evidence | coverage-core | [1-9][0-9]* passed
evidence | integration   | [1-9][0-9]* passed
evidence | build         | Building EXE from|completed successfully
```

```
floor | unit          | 12
floor | coverage      | 12
floor | coverage-core | 7
floor | lint          | 1
floor | typecheck     | 14
```

**Set by MT-001 on 2026-09-12 from the first real run**, and two lines longer
than this document proposed: `coverage-core` and `typecheck` are required gates
holding real numbers, and a floor is the only thing that notices a suite or a
`mypy` target quietly shrinking. **`floor | lint | 1` is a placeholder with an
owner** — it counts import-linter contracts, MT-001 configures one, and
`architecture.md` §3 states five. **MT-003 raises it to 5.** Left at 1, four
contracts could be deleted and the gate would still pass.

**The `ruff` liveness gap — closed, and not the way this document proposed.**
The `lint` evidence regex asserts that *import-linter* did work. It does **not**
assert that `ruff` saw any files: `ruff check` on an empty tree prints
`All checks passed!` and exits 0, which is the canonical vacuous pass. The
proposed close was:

```
discovery | ruff-sees-src | . | uv run ruff check --no-cache -v . 2>&1 | grep -qE "[Cc]hecked [1-9][0-9]* files"
```

**Measured on 2026-09-12 against the installed ruff 0.16.7: that line never
matches, and would have sat red in `doctor.sh` forever.** `-v` emits one
`Included path via 'include'` DEBUG line *per file* and no total; `--statistics`
prints nothing at all on a clean run. What does work is the resolved file list
itself, which is the same assertion said differently and does not depend on a
summary line surviving a ruff release:

```
discovery | ruff-sees-src | . | uv run ruff check --no-cache --show-files . | grep -qE "src.mangatl.*[.]py"
```

Observed: 14 files under `src/mangatl`. **The requirement was not deleted.**

**Settled by MT-001's GATES phase on 2026-09-12, and the gap was real.** What the
paragraph above warned of was measured rather than reasoned: a `discovery` line is
run by `doctor.sh`, never by the gates, so the `lint` *gate* still passed
vacuously when `ruff` could not see `src/`. With `src` added to ruff's
`extend-exclude` and `src/` itself left on disk, the then-current gate command
exited **0** printing `All checks passed!` and `Contracts: 1 kept, 0 broken` —
satisfying the evidence regex *and* the floor of 1 — while ruff checked none of
this project's source.

So the assertion moved into the gate command as well, and `floor | lint | 1` and
the `evidence` line are unchanged:

```
gate | lint | required | . | uv run ruff check . && uv run ruff check --no-cache --show-files . | grep -qE "src.mangatl.*[.]py" && uv run lint-imports
```

The `ruff-sees-src` discovery line is **kept** — `doctor.sh` is where a human or
an agent finds out *why* the gate is failing, and it costs nothing. The gate now
fails under the mutation that used to pass it; the pasted probe is in MT-001's
`## Deferred verifications` §5 and the decision is PO-6. One caution for whoever
touches this next: with `src/` moved out of the tree entirely, `ruff check .`
exits 1 for an unrelated reason — `mangatl` stops resolving as first-party, so
isort re-classifies it *in the test files* and I001 fires. That failure is a
coincidence of this layout, not the reach assertion doing its job; suppress I001
and ruff is green. Do not read it as evidence that the gate is watching `src/`.

### Discovery lines

```
discovery | core-tests  | . | uv run pytest --collect-only -q tests/core | grep -qE "[1-9][0-9]* tests? collected"
discovery | ui-tests    | . | uv run pytest --collect-only -q tests/ui | grep -q "tests/ui/"
discovery | cov-domain  | . | uv run coverage report --include="src/mangatl/domain/*" | grep -qE "^src.mangatl.domain"
discovery | ruff-sees-src | . | (as above)
discovery | providers   | . | uv run python -c "import onnxruntime as o; print(o.get_available_providers())" | grep -qE "CUDA|Dml|CPU"
```

**Status on 2026-09-12 (MT-001).** `core-tests`, `ui-tests`, `cov-domain`
and the corrected `ruff-sees-src` all pass. **`providers` does not, and is
expected not to**: no inference runtime is pinned, because MT-001 may not
choose between `onnxruntime` and `torch`+`cu128` and MT-002 is the spike that
does. The line is kept rather than deleted so the check exists the moment the
dependency does; `doctor.sh` reports it MISSING until then. MT-001 PO-2.

`cov-domain` exists because `--cov=src/mangatl/domain` resolving to nothing is
satisfied silently, and `coverage-core` is the gate holding the 100% bar.

### What each gate reads

```
covers | unit          | src/mangatl/**
covers | coverage      | src/mangatl/**
covers | coverage-core | src/mangatl/domain/**
covers | coverage-core | src/mangatl/typeset/**
covers | coverage-core | src/mangatl/bench/**
covers | integration   | src/mangatl/detect/**
covers | integration   | src/mangatl/ocr/**
covers | integration   | src/mangatl/clean/**
covers | build         | packaging/**
```

Note that `detect`, `ocr` and `clean` are claimed by **both** `unit` (their
logic, against a fake session) and `integration` (their real-model smoke test).
That is the point of the §4 split: a change in those packages is read by a
required gate. Bootstrap must write these `covers` lines **from the runners'
real include lists**, not from this document.

### `--fast` exclusions

```
slow | build          | PyInstaller freezes an interpreter and ~1 GB of weights; minutes
slow | integration    | loads real .onnx models onto the GPU and calls a paid API
slow | mutation       | re-runs the suite once per mutant
```

`coverage` and `coverage-core` stay in `--fast` deliberately: the instrumented
run is the one that judges the story, and keeping it out of RED and GREEN is
exactly how a suite reaches CI having never been measured under it.

### `blocked-when`

```
blocked-when | integration | (CUDAExecutionProvider is not in available provider names|Failed to load library .*onnxruntime_providers_cuda|no CUDA-capable device)
```

A machine with no GPU cannot *start* this gate's work; that is BLOCKED, not
FAIL. A model that loads and returns garbage is a FAIL and must stay one — do
not widen this pattern to cover an inference error.

### `waiver`

```
waiver | mutation    | mutmut is not installed and not configured until the suite is real; stack.md §6
waiver | integration | tests/integration/ is empty until MT-002; pytest exits 5 with "no tests ran"
```

**The `integration` waiver was added by MT-001**, which measured what this
document did not predict: `uv run pytest -q tests/integration -m "gpu or
network"` over an empty directory exits **5**, not 0. Without a waiver the
gate would WARN on every run from here to MT-002, and the next agent would
learn that WARNs are ignorable. **MT-002 writes the first real-model smoke
test and removes this line.**

Remove the `mutation` one in the story that configures `mutmut`.

## 7. The Windows Python trap — read this before writing a gate command

`.claude/harness/rules.md` forbids Python in *harness scripts* because a bare
`python` on Windows hits the Microsoft Store App Execution Alias and exits 49
without running anything. That rule is about harness scripts and does not forbid
Python as the project stack. But **gate commands from `project.conf` are
executed through bash on this Windows machine**, so the same shim is one bare
command away.

The rule for this project:

- **Every gate and task command starts with `uv run`.** `uv` is a standalone
  binary on `PATH`; `uv run` resolves the project venv's interpreter directly
  and never consults the App Execution Alias.
- **Never write a bare `python`, `python3`, `pytest`, `mypy` or `ruff` in
  `project.conf`, in a `discovery` line, or in a CI workflow step.** Not even
  inside a pipe. `uv run python -c ...` is correct; `python -c ...` is the bug.
- `py -3` is the other correct form on Windows, but it does not exist on the CI
  runner, so it is not used anywhere in this repo.
- If a command must be invoked that `uv run` cannot reach, use the venv binary
  by explicit path: `.venv/Scripts/python.exe` on Windows,
  `.venv/bin/python` elsewhere. Prefer `uv run`.

`docs/wiki/environment.md` (written by `/setup-environment`) carries the install
steps; this section carries the rule.

## 8. Open questions this file does not answer

- **O1 — the benchmark chapter.** The user's, and still open. MT-019 builds the
  harness; the chapter itself is a user-supplied input and the story says so.
- ~~**Should the 80% bar attach to S1a or S1b?**~~ **Decided by the user on
  2026-09-12: S1b**, the uncheatable and strictly harder number. §5/O2 is
  updated, the recall validity rule is gone, and the brief's §7 S1 now states
  the ground-truth denominator.
- **The ONNX export trio.** MT-002 is the spike. If it fails, the fallback is
  `torch` + `cu128` and a much larger installer; the installer size is not a
  stated constraint, so this is a decision the spike can make, but the user
  should know the installer could be ~3 GB rather than ~1 GB.
- **Adaptive-thinking output volume** is the one unmeasured input to the cost
  model (§5/O4). MT-009 measures it; MT-010 makes a bad guess safe.
- **O5 is resolved** by the Lead Designer:
  `docs/wiki/design/typeset-font.md` chooses **Shantell Sans 1.011 under the SIL
  Open Font License 1.1**, shipping the four static faces. Licence confidence is
  stated as high (OFL declared by the upstream repository, not by an
  aggregator); **glyph coverage is explicitly unverified** and is converted into
  a test that MT-020 carries. A warning is recorded there against a
  piracy-aggregator claim that "CC Wild Words Roman is OFL", which is almost
  certainly false — do not act on it.
- ~~**Windows High Contrast mode is not supported in v1.**~~ **Decided by the
  user on 2026-09-12: supported**, not merely detected and declined.
  `docs/wiki/design/accessibility.md` A-13.3 is revised and MT-026 carries it.
- ~~**An app-level "lettering font file" setting.**~~ **Decided by the user on
  2026-09-12: in scope.** Shantell Sans stays the default and still ships;
  one app-wide override setting is added. The scope reading is now recorded in
  the brief's §5 non-goals so it is not re-litigated — no *per-bubble* font
  control, one app-wide override. MT-027 carries it.
- **Four flags raised by the Lead Designer with the High Contrast work
  (2026-09-12), none of them blocking, none of them in the backlog:**
  1. *The `reverted` glyph.* Under a contrast theme `edited` and `reverted` are
     not distinguishable as drawn, so §10.4 makes `reverted` a return arrow
     alone. Whether the **dark** theme adopts the same single glyph set is a
     product call: cheaper to build and test, but it amends `components.md` §7
     and MT-017's AC-9.
  2. *How far support extends to a user-**edited** contrast theme.* The designer
     recommends promising the four shipped Windows themes and best-effort
     beyond, said in the brief rather than only in A-15.11.
  3. *`color.canvas.page-edge` is single-stroked*, so a scan with a black gutter
     has no visible page edge. **Pre-existing**, not introduced by High
     Contrast; needs its own story (`high-contrast.md` §7.2).
  4. *`overlay.dim.opacity` at 0.55 composites the halo to ≈`#797979`*, which
     fails against a 50% screentone — A-06's floors are on token values, not on
     composited ones. **Pre-existing.** Widening A-06 now would change what
     MT-016 must satisfy after it was written, so it is recorded rather than
     folded in.
- **Three Qt behaviours are researched, not observed**, and MT-028 must verify
  rather than assume: whether Qt 6.8 populates `QPalette` from a contrast theme
  at all and with which roles; whether it does so before the first
  `setStyleSheet` and re-emits on `WM_SETTINGCHANGE`; and whether re-applying
  the sheet re-polishes custom-`paintEvent` widgets. The bounded fallback for
  the first is reading the Windows colours through `ctypes` — a different source
  for the same five-key dict, not a different design.
- **Code signing** for the installer. Not in the brief, not a v1 gate, but an
  unsigned installer on Windows 11 produces a SmartScreen warning on the user's
  own machine. Named here so it is not a surprise.
