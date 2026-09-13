# MT-002 — Local model runtime on the RTX 5070

*Spike run 2026-09-12 by **lead-po on Claude Opus 5 (`claude-opus-5`)**, dispatched
by the lead-po orchestrator. No session override was reported to the agent; the
resolved model recorded here is the one declared in `.claude/agents/lead-po.md`.*

**The question this spike was dispatched to settle**, from `stack.md` §3 and
`architecture.md` D3:

> Usable ONNX exports of a comic text detector, `manga-ocr` and LaMa exist, and
> run on an RTX 5070 (Blackwell, sm_120) under `onnxruntime-gpu`.

**Answer: yes, all three, on the CUDA execution provider — but not the way the
plan assumed, and D3's stated *reason* for choosing ONNX does not survive
measurement.** See `## Decided` for what later stories may take on trust, and
`## Evidence` for every number, all of which is to be re-verified.

---

## How to read this document

Per AC-5, every factual claim below carries one of three labels:

| Label | Meaning |
|---|---|
| **[MEASURED]** | Run on the development machine on 2026-09-12. The command is given. |
| **[WEB]** | Read from a repository, a README or package metadata. Not verified by running anything. |
| **[INFERRED]** | A conclusion drawn from measurements, not itself a measurement. |

**The machine everything was measured on**, and the only machine any
[MEASURED] number applies to:

```
Windows 11 Home 10.0.26200, Ryzen 5 7600X, 32 GB
NVIDIA GeForce RTX 5070 (Blackwell, sm_120), 12227 MiB, WDDM
NVIDIA-SMI 591.86, Driver 591.86, CUDA 13.1        [MEASURED]
no CUDA toolkit installed (`where nvcc` finds nothing) [MEASURED]
CPython 3.12.14 (uv-managed), uv 0.12.13
```

Every probe ran in a throwaway virtual environment at `spikes/MT-002/.venv`,
which is gitignored. **The project's own `pyproject.toml`, `uv.lock` and `.venv`
were not touched** (PO-1).

---

## Decided

*This section is the only part of this document later stories may take on trust
(MT-007, MT-010, MT-019). It contains the choice of runtime and the model file
identities, and nothing else. Every number lives in `## Evidence` and is to be
re-verified, not assumed.*

### Runtime for EPIC-03 and EPIC-06: **ONNX Runtime**, not the PyTorch fallback

All three models load and run on the CUDA execution provider on this machine.
The PyTorch `cu128` fallback is **not needed** and should not be added.

**Dependency lines to add to `pyproject.toml`** — by MT-007, which is the first
story that imports any of them, not before (`stack.md`'s sizing rule):

```toml
# Local inference — settled by MT-002.
"onnxruntime-gpu[cuda,cudnn]==1.30.0",   # NOT bare onnxruntime-gpu; see Evidence E2
"numpy>=2.1,<3",
"pillow>=11",
"opencv-python-headless>=4.11",
```

**One line of application code is mandatory and is not optional tuning.** Before
the first `InferenceSession` is constructed, the process must call:

```python
import onnxruntime as ort
ort.preload_dlls(cuda=True, cudnn=True, msvc=True)
```

Without it, on this machine, **the CUDA provider fails without raising and every
model runs on CPU** while `get_available_providers()` still advertises CUDA.
This is Evidence E2 — independently reproduced by the orchestrator with its own
probe, on the real 1024² detector rather than the small conv probe used here
(MT-002 `## Notes`, PO-3) — and it is the single most consequential finding of
the spike.

**How to detect it**, measured rather than assumed (PO-3):

- `get_available_providers()` advertises `CUDAExecutionProvider` **identically**
  whether or not the DLLs load. It is worthless as a check.
- `session.get_providers()` is **honest**: it returns `['CPUExecutionProvider']`
  when the load failed, and lists CUDA first when it did not. This is the check.
- Requesting CUDA **only** does not raise; it quietly returns a CPU session. An
  exception is not available as a signal.
- ORT does log a loud stderr error naming the missing `cublasLt64_13.dll`, and
  it survives `SessionOptions.log_severity_level = 3` — the provider bridge
  emits it below that filter. Visible to a human watching a console; invisible
  to a program that only inspects return values.

So MT-007's AC-7 should assert the provider actually selected, never the
provider list requested.

### Model file identities

Fetch by exact revision, verify by SHA-256. **`lama_fp32.onnx`, not `lama.onnx`** —
see E3.

| Role | Repo (Hugging Face) | File | SHA-256 | Bytes |
|---|---|---|---|---|
| Text-region detection | `mayocream/comic-text-detector-onnx` | `comic-text-detector.onnx` | `1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f` | 94,669,756 |
| Manga OCR — encoder | `onnx-community/manga-ocr-base-ONNX` | `onnx/encoder_model.onnx` | `df35f64c2400ea860c70a2d06f2a1f99892374a78c89fcf35308076557a3863f` | 343,377,067 |
| Manga OCR — decoder | `onnx-community/manga-ocr-base-ONNX` | `onnx/decoder_model.onnx` | `31ca14d6dee6b3966144e128d0481d5a91f5083cbced81fe7a9571713fa50cd4` | 117,445,718 |
| Manga OCR — vocab | `kha-white/manga-ocr-base` | `vocab.txt` | `344fbb6b8bf18c57839e924e2c9365434697e0227fac00b88bb4899b78aa594d` | 24,072 |
| Inpainting | `Carve/LaMa-ONNX` | `lama_fp32.onnx` | `1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6` | 208,044,816 |

All five hashes are **[MEASURED]** — `sha256sum` on the downloaded files.

### Estimated installed size

| Component | Size | Label |
|---|---|---|
| Bundled weights (the five files above) | **728.2 MiB** (763,537,357 bytes) | [MEASURED] |
| `onnxruntime-gpu` package | 218 MiB | [MEASURED] |
| `nvidia-*` CUDA 13 + cuDNN 9 libraries | **1,580 MiB** (cu13 1,015 + cudnn 565) | [MEASURED] |
| **Total inference footprint** | **≈ 2,526 MiB / 2.47 GiB** | [INFERRED] |

**This is the number that should worry the reader**, and it is the subject of
the D3 contradiction below. It is not the ~2 GB of *weights* the story
anticipated; it is 0.73 GB of weights and 1.75 GB of CUDA runtime.

### Escalation — two decisions I am not authorised to take

1. **The detector is GPL-3.0 and partly trained on Manga109-s.** See E7. This is
   a licensing question about a shippable product, not a technical one. It needs
   the user's decision before EPIC-03 ships, and it may force a different
   detector.
2. **Whether to ship CUDA at all**, given 1.75 GB of it. See the D3 contradiction
   and E8; `onnxruntime-directml` is a ~15 MB wheel with no NVIDIA dependency.
   This is a packaging/product tradeoff for MT-024 and the user.

---

## What contradicts `stack.md` / `architecture.md`

### D3's rationale fails, even though D3's conclusion holds

`architecture.md` D3 says, in full:

> A CUDA `torch` wheel is ~2.5 GB and would dominate an installer that must
> "just work"; ORT's provider chain (CUDA → DirectML → CPU) is what makes the app
> run on a machine without a CUDA toolkit.

Both halves are now measured, and both are weaker than stated:

- **The size argument is close to void.** `onnxruntime-gpu` with the CUDA
  execution provider actually working costs **1,798 MiB** of runtime on this
  machine (218 + 1,580) [MEASURED]. D3 rejected `torch` for being "~2.5 GB".
  The ONNX path is ~1.8 GB of runtime plus 0.73 GB of weights. **The installer
  saving that justified the decision is largely not there.**
- **"Runs on a machine without a CUDA toolkit" is true but required a step D3
  did not know about.** It is true that no CUDA *toolkit* is installed here.
  It is not true that it worked out of the box: bare `onnxruntime-gpu` fell
  through to CPU, and so did `onnxruntime-gpu[cuda,cudnn]` until
  `ort.preload_dlls()` was called (E2).

**D3's conclusion should stand, but its recorded reason should be replaced with
the measured one.** The honest reason to prefer ONNX Runtime here is not size —
it is that the DirectML and CPU providers give a single codebase that degrades
to any DX12 GPU or to no GPU, and that a CUDA-less install is a 15 MB wheel
rather than a different framework. I have not amended `architecture.md`; that is
the orchestrator's call, and D3 is an architecture decision, not a stack table.

### Other divergences from `stack.md` §3

| `stack.md` §3 said | Measured | Note |
|---|---|---|
| `onnxruntime-gpu` **1.22.x** | **1.30.0** | [MEASURED] What actually resolves today. 1.30 targets **CUDA 13**, not 12 — the missing DLL was `cublasLt64_13.dll`. The `nvidia-*-cu12` packages named in the dispatch brief are the wrong generation for this build; it pulls `nvidia-*` cu13 wheels. |
| `onnxruntime-directml` 1.22.x as the DirectML fallback | **latest cp312 wheel is 1.17.3** | [WEB] PyPI metadata. DirectML is four minor versions behind and **conflicts with `onnxruntime-gpu`** (both provide the `onnxruntime` module), so "CUDA → DirectML → CPU" is *not* one install with a provider chain — it is two mutually exclusive installs. This materially changes the fallback story and MT-024 needs to know. **Untested** — I did not install it. |
| `numpy` 2.1.x / `Pillow` 11.x / `opencv-python-headless` 4.11.x | numpy 2.5.3, Pillow 12.3.0, opencv-python-headless 5.0.0.93 | [MEASURED] All resolved fine; the candidates are stale but nothing depended on the difference. |
| OCR adds "~50 ms/region" (§5 O3) | **26.7 ms/crop** mean on CUDA | [MEASURED] The estimate was conservative; the real figure is about half. See E5. |
| Detector "must emit per-region masks, not just boxes" | Confirmed — emits `seg` and `det` masks *and* YOLO boxes | [MEASURED] But the mask and the boxes **disagree**, which is a design constraint MT-007 does not currently account for. See E6. |

`stack.md` §5 **O6 is confirmed**, not contradicted: `manga-ocr` read a crop
containing 醜鬼 with ruby しゅうき and returned 醜鬼 with the ruby correctly
dropped (E5).

---

## Evidence

*Everything in this section is a number, and **every number here is to be
re-verified by the story that depends on it, not assumed**. That is the whole
point of the split: MT-007, MT-010 and MT-019 are told not to re-litigate
`## Decided`; they are **not** told to trust anything below this line. A
threshold that held on five pages of one volume on one machine is a starting
point for a test, not a specification.*

### Reproducing any of this

`uv` is not on `PATH` in a bare Git Bash shell on this machine; every command
below assumes:

```bash
export PATH="/c/Users/ryanc/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
cd /c/Users/ryanc/Projects/manga-translator
uv venv --python 3.12 spikes/MT-002/.venv
uv pip install --python spikes/MT-002/.venv/Scripts/python.exe \
    "onnxruntime-gpu[cuda,cudnn]" numpy pillow opencv-python-headless huggingface_hub jaconv
```

The probe scripts are in `spikes/MT-002/` (gitignored, throwaway — see
*Unreviewed code* below). Raw results are the JSON files in `spikes/MT-002/out/`.

---

### E1 — What `get_available_providers()` actually returns (AC-3)

```bash
spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/probe_providers.py
```

```
onnxruntime ver  : 1.30.0
ort.get_device() : GPU
get_available_providers() :
    ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```
[MEASURED]

**`get_available_providers()` is not an answer to AC-3 and must not be used as
one.** It listed `CUDAExecutionProvider` in *every* configuration tested,
including the two in which CUDA did not work at all. It reports which provider
shared libraries were compiled into the wheel, not which ones can load. The
only trustworthy signal is `session.get_providers()` **after** the session is
constructed. That is what E2 uses.

### E2 — The CUDA provider loaded, but only on the third configuration

This is the finding with the highest consequence for MT-007, and it is exactly
the "silent fallback to CPU reported as a GPU result" the dispatch warned about.
It happened twice before it stopped happening.

| # | Configuration | `session.get_providers()` | Conv probe |
|---|---|---|---|
| 1 | `onnxruntime-gpu` bare, requesting `["CUDAExecutionProvider","CPUExecutionProvider"]` | `['CPUExecutionProvider']` | 40.0 ms |
| 2 | `onnxruntime-gpu[cuda,cudnn]` (NVIDIA libs installed), same request | `['CPUExecutionProvider']` | 50.2 ms |
| 3 | as #2, **plus `ort.preload_dlls(cuda=True, cudnn=True, msvc=True)`** | `['CUDAExecutionProvider', 'CPUExecutionProvider']` | **12.5 ms** |
[MEASURED] — `spikes/MT-002/probe_cuda_session.py`, `probe_cuda2.py`

In configurations 1 and 2 ONNX Runtime emitted a warning to stderr and continued:

```
[E:onnxruntime:Default, provider_bridge_ort.cc:2395 TryGetProviderInfo_CUDA]
  Error loading "...onnxruntime_providers_cuda.dll" which depends on
  "cublasLt64_13.dll" which is missing. (Error 126)
[W:onnxruntime:Default, onnxruntime_pybind_state.cc:1294]
  Failed to create CUDAExecutionProvider. Require cuDNN 9.* and CUDA 13.*
```

**No exception was raised.** A program that did not inspect `get_providers()`
would have run entirely on CPU and reported success.

**Mechanism check — the dispatch's assumption #2 was half wrong.** The brief
said recent `onnxruntime-gpu` wheels "are supposed to work via the `nvidia-*-cu12`
pip packages, sometimes needing an explicit extra". Measured: the extra is
necessary but **not sufficient** on Windows. The `[cuda,cudnn]` extra installs
the right files — `ort._get_nvidia_dll_paths(True, cuda=True, cudnn=True)`
resolves them correctly, and `nvidia/cu13/bin/x86_64/cublasLt64_13.dll` and
`nvidia/cudnn/bin/cudnn64_9.dll` are both present on disk [MEASURED] — but
nothing adds those directories to the Windows DLL search path. `preload_dlls()`
is what does that. Also note the generation: **cu13, not cu12.**

**Why I am confident this is real GPU execution and not a subtler fallback**
— three independent signals, per the dispatch's instruction to cross-check:

1. `session.get_providers()[0] == 'CUDAExecutionProvider'` for all three models.
2. Latencies implausible for CPU (E4): the detector is **22.4× faster** than the
   same session forced to CPU on the same machine, LaMa **14.9×**.
3. GPU memory rises on CUDA sessions and does not on CPU sessions (E4).

### E3 — The three exports (AC-1)

| Model | Obtained? | Source | Licence | How verified |
|---|---|---|---|---|
| Comic text detector | **Yes** | HF `mayocream/comic-text-detector-onnx`, file `comic-text-detector.onnx`, 94,669,756 B | **Contested — see E7.** Repo metadata says `apache-2.0` [WEB]; the upstream project `dmMaze/comic-text-detector` this is an export of is **GPL-3.0** [MEASURED — fetched `LICENSE`, GitHub API `spdx_id: GPL-3.0`] | Loads and runs; output validated against the upstream author's own published reference mask (E6) |
| `manga-ocr` | **Yes** | HF `onnx-community/manga-ocr-base-ONNX` (encoder + decoder), vocab from `kha-white/manga-ocr-base` | `apache-2.0` on both repos [WEB]. Upstream `kha-white/manga-ocr` is Apache-2.0 [WEB]. **Clean.** | Loads and runs; scored against the upstream author's own ground-truth test set (E5) |
| LaMa | **Yes** | HF `Carve/LaMa-ONNX`, file **`lama_fp32.onnx`**, 208,044,816 B | `apache-2.0` on the HF repo [WEB]; upstream `advimman/lama` is `Apache-2.0` [MEASURED — GitHub API `spdx_id: Apache-2.0`]. **See the caveat in E7** — I verified repository metadata, not the provenance of the `big-lama` checkpoint itself. | Loads and runs; calling convention validated against the repo's own published output image (E4) |

**Two file-choice traps, both of which I fell into first:**

1. **`lama.onnx` is the wrong file and it fails.** It is the repo's
   `torch.onnx.dynamo_export` build (opset 18) and it **will not load** in
   onnxruntime 1.30 at any optimization level above `ORT_DISABLE_ALL`:
   ```
   FAIL : Node (..._FourierUnit_..._DFT_20) Op (DFT) [ShapeInferenceError]
     one-sided DFT requires real input (last dimension must be 1)
   ```
   [MEASURED]. It *does* load with `ORT_DISABLE_ALL`, which is why this nearly
   became a documented workaround. **It should not be.** `lama_fp32.onnx` is the
   classic-exporter opset-17 build, loads at `ORT_ENABLE_ALL` with no workaround
   [MEASURED], and the repo's own README marks it RECOMMENDED and the other NOT
   RECOMMENDED [WEB]. Use `lama_fp32.onnx`.
2. **`anyisalin/big-lama-onnx` is a re-upload of the same bytes**, and its
   `model_fp16.onnx` is not fp16 — `onnx/model.onnx` and `onnx/model_fp16.onnx`
   carry the **same** blob id as `Carve/LaMa-ONNX/lama.onnx`
   (`f208051e92002de2a50cff9311f9f59d39d19a14`) [MEASURED — HF API]. Do not
   treat it as an independent second source, and do not expect fp16 from it.

**Model I/O signatures** [MEASURED]:

```
comic-text-detector.onnx
  IN  images                [1,3,1024,1024] float
  OUT blk                   [1,64512,7]      YOLOv5 head: cx cy w h obj cls0 cls1
  OUT seg                   [1,1,1024,1024]  text segmentation mask
  OUT det                   [1,2,1024,1024]
manga-ocr encoder_model.onnx
  IN  pixel_values          [b,c,h,w] -> 224x224 used
  OUT last_hidden_state     [b,197,768]
manga-ocr decoder_model.onnx          (NO kv-cache in this export)
  IN  input_ids [b,seq] int64;  encoder_hidden_states [b,seq,768]
  OUT logits    [b,seq,6144]
lama_fp32.onnx
  IN  image [batch,3,512,512];  mask [batch,1,512,512]
  OUT output[batch,3,512,512]        FIXED 512x512 — a full page needs tiling
```

`lama_fp32.onnx`'s **fixed 512×512 input is a hard constraint on MT-019** and is
not mentioned anywhere in `stack.md` or `architecture.md`. A 1125×1600 page
cannot be inpainted in one pass. Either tile it, or re-export at another
resolution (the repo links a notebook for that) [WEB].

### E4 — Forward passes, provider, wall time, VRAM (AC-2)

```bash
PYTHONIOENCODING=utf-8 spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/final_bench.py
```

All rows [MEASURED], same machine, same session, warm (2 warmup iterations
discarded); mean of 10 runs on CUDA, 3–5 on CPU.

| Model | Provider actually used | CUDA mean | CPU mean | Speed-up | VRAM delta |
|---|---|---|---|---|---|
| Detector, 1024² page | `CUDAExecutionProvider` | **25.83 ms** | 578.61 ms | **22.4×** | +359 MiB |
| `manga-ocr`, one crop, full greedy decode | `CUDAExecutionProvider` | **26.72 ms** | 158.06 ms | **5.9×** | +578 (enc) / +192 (dec) MiB |
| LaMa, one 512² tile | `CUDAExecutionProvider` | **105.33 ms** | 1567.47 ms | **14.9×** | +320 MiB |

CPU-provider sessions showed a VRAM delta of **0, −14 and +2 MiB** — i.e. noise
around zero — which is what makes the CUDA deltas above attributable rather than
coincidental.

**How VRAM was measured, and why the numbers are weak.** The dispatch proposed
polling `nvidia-smi --query-gpu=memory.used`. I first tried the stronger option,
per-process accounting:

```bash
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
  pid, used_gpu_memory [MiB]
  5880, [N/A]        # every process
```
[MEASURED] — **per-process VRAM is unavailable on this machine.** That is a WDDM
limitation on consumer Windows, not a transient error. So the proposed
mechanism was the only one available and I used it: a 25 Hz background poller
around session construction plus inference, recording the baseline immediately
before.

**These VRAM figures are therefore noisy global deltas, not model footprints.**
The desktop compositor and other processes sit on the same counter; the observed
idle baseline drifted between **3,203 and 4,488 MiB** across the session
[MEASURED]. Treat every VRAM number above as an order of magnitude. Total for
all three models resident simultaneously would be ≈ 1.4 GiB by summation
[INFERRED], comfortably inside 12 GiB, but I did not measure the three loaded
together and MT-007 should.

**LaMa calling convention, validated against the publisher's own output.**
Running `Carve/LaMa-ONNX`'s shipped `image.jpg` + `mask.png` through my code and
comparing to their published `output_onnx.png` gives **MAE 3.96/255 (1.6%)**
[MEASURED]. That is close enough to confirm my normalisation and channel order
are right, and the residual is explained by their reference having come from the
other export plus PNG/resize differences.

**A control that turned out to be worthless, recorded so nobody else trusts it.**
I measured "MAE outside the inpaint mask" expecting it to show that LaMa does not
damage untouched pixels. It came out at **exactly 0.000 for every case**. That is
not a quality result: the export **composites internally**
(`out = image*(1-mask) + pred*mask`), confirmed by a max-absolute-difference of
`0.0` outside the mask on a deliberate probe [MEASURED]. Outside-mask fidelity is
structural in this graph and cannot fail. Any later story that reports it as
evidence of inpainting quality is reporting a tautology.

### E5 — OCR: is the output actually Japanese?

**What would have counted as implausible, stated before the run:** Latin output,
empty strings, one token repeated, or CJK that is not plausibly the glyphs in
the crop. Additionally: if a crop with **no text** also produced confident
Japanese, the plausibility claim on the real crops would be worth much less.

**Test 1 — the upstream author's own ground-truth set.** `kha-white/manga-ocr`
ships `tests/data/images/{00..11}.jpg` with `tests/data/expected_results.json`.
This is a real oracle, not my judgement.

```bash
PYTHONIOENCODING=utf-8 spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/ocr.py
PYTHONIOENCODING=utf-8 spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/rescore.py
```

| Scoring | Exact matches |
|---|---|
| Raw decoder output | 6 / 12 |
| After the upstream project's own `post_process` (`jaconv.h2z(ascii=True, digit=True)`, `…`→`...`) | **10 / 12** |
[MEASURED]

The four recovered by post-processing were **entirely** half-width vs full-width
punctuation and digits (`!!!` vs `！！！`, `LINK!私達7人` vs `ＬＩＮＫ！私達７人`,
`?` vs `？`). **That normalisation step is required and MT-008 must implement it**;
without it the model looks 33 points worse than it is.

The two genuine misses:

| File | Expected | Got |
|---|---|---|
| `01.jpg` | `立川で見た〝穴〟の下の巨大な眼は：` | `立川で見た、穴への下の巨大な眼は．．．` |
| `03.jpg` | `第３０話重苦しい闇の奥で静かに呼吸づきながら` | `第３０話重苦しい間の奥で静かに呼吸づきながら` (闇→間) |

**10/12 is a lower bound.** The exported decoder has no KV cache, so I decoded
**greedily**; the reference configuration is `num_beams: 4` [MEASURED — the
export's `generation_config.json`]. Beam search would very likely do better.
MT-008 should re-measure rather than inherit 10/12.

**Test 2 — the real pipeline on a real page.** Detector boxes on `014.jpg` fed
straight into the OCR, right-to-left. All nine, with what I read in the page
myself alongside:

```bash
PYTHONIOENCODING=utf-8 spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/pipeline.py
```

| # | OCR output | Matches the glyphs I can read in the crop? |
|---|---|---|
| 00 | `「魔都を国の力とする」` | yes — **white text on solid black, no bubble** |
| 01 | `人間側のメリットは？` | yes |
| 02 | `醜鬼が人間の言う通りに動いたりね` | yes — **and the ruby しゅうき was dropped** |
| 03 | `この提案罠の可能性は十分にある` | yes |
| 04 | `私の理想に近いわ` | yes |
| 05 | `神の威信が高まった事で桃も安定供給` | yes |
| 06 | `……なるほど` | yes |
| 07 | `総理達もそれを望んでいる筈` | yes |
| 08 | `神が協力する事で魔都の資源をリスクなく使い放題` | yes |

**9/9 correct** [MEASURED], including the two hardest cases on the page: white
vertical text over solid black artwork, and a crop containing furigana.

Box 02 is the direct confirmation of `stack.md` §5 **O6**: the crop contains
醜鬼 with ruby しゅうき and the model returned 醜鬼, dropping the ruby, exactly as
O6 claims it is trained to.

**Test 3 — the negative control, and it FAILS.** Two crops from `014.jpg`
containing no text at all:

| Crop | Content | OCR output |
|---|---|---|
| `(0,700)–(55,900)` | pure white page margin | **`それは、`** |
| `(430,980)–(700,1260)` | hair and face artwork, no text | **`そして、`** |
[MEASURED]

**`manga-ocr` hallucinates confident, well-formed Japanese on text-free input.**
It has no "no text here" output and no score is exposed by this export. This is
a first-class constraint on the architecture:

- The OCR **cannot be used to decide whether a region contains text.** That
  decision belongs entirely to the detector, and a false-positive region will
  become a phantom line with plausible-looking Japanese in it — which is
  precisely the failure mode `architecture.md` D11 says is worse than a miss,
  arriving by a different route than D11 anticipated.
- Because the detector **does** sometimes box the burned-in watermarks (E6),
  this is not hypothetical.
- MT-008 should not add a "confidence threshold" without first checking that
  this export exposes anything to threshold on. It does not obviously do so.

**A caveat on my own method.** My first attempt at this test used hand-picked
crop rectangles and produced two apparent OCR failures. Inspecting the saved
crops showed **my rectangles had clipped the text**, not that the model failed.
The table above therefore uses the detector's own boxes. The lesson generalises:
a bad crop is indistinguishable from a bad model unless you look at the crop.

### E6 — Detector: how many regions, and where?

**What would have counted as implausible, stated before the run:** zero regions
on a page full of bubbles; one region covering most of the page; a region count
in the hundreds; or a mask with recall below ~0.30 against the upstream author's
published reference mask.

```bash
spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/detect.py
spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/iou.py
```

| Page | Boxes | Mask components | Mask % of page | Largest box % of page |
|---|---|---|---|---|
| `011.jpg` | 9 | 136 | 4.06 | — |
| `012.jpg` | 6 | 86 | 2.39 | — |
| `013.jpg` | 8 | 83 | 1.80 | — |
| `014.jpg` | 9 | 111 | 4.25 | — |
| `015.jpg` | 6 | 57 | 4.32 | — |
| `AisazuNihaIrarenai-003.jpg` (upstream sample) | 15 | 305 | 8.16 | — |
[MEASURED]

None of the disqualifying conditions fired: 6–15 regions per page, masks
covering 1.8–8.2% of the page. All nine boxes on `014.jpg` were confirmed to be
real text by reading them (E5).

**Against the upstream author's own published mask.** `dmMaze/comic-text-detector`
ships `AisazuNihaIrarenai-003.jpg` together with its own reference output
`AisazuNihaIrarenai-003-mask.png`. Comparing my thresholded `seg` output to it:

```
reference 100,344 px   mine 157,817 px
IoU 0.585    recall (of reference) 0.949    precision 0.604
```
[MEASURED]

**Recall 0.949 is the number that matters** and it says the ONNX export finds
essentially all of the text the upstream author's own pipeline marks. The lower
precision is expected and is my fault, not the export's: the published reference
is the author's *refined* mask (`refine_mask`, which MT-007 will implement),
while mine is the raw `seg` output thresholded at 0.3 with no refinement — so
mine is systematically fatter. **This does not license MT-007 to skip mask
refinement**; it means the unrefined mask over-covers, and the inpainter would
erase more than it should.

**Two things MT-007 inherits, both requested by the orchestrator:**

**(a) The burned-in watermarks are detected — inconsistently.** Both fixtures
carry `RawLazy.Com` and `DL-Raw.Se` burned into the pixels.

| Page | `RawLazy.Com` | `DL-Raw.Se` |
|---|---|---|
| `012.jpg` | **boxed** (0.53 coverage), mask covers 21.7% | **boxed** (0.86), mask covers 8.3% |
| `014.jpg` | not boxed (0.00), mask covers 21.3% | not boxed (0.18), mask covers 4.4% |
[MEASURED — `spikes/MT-002/wm.py`]

On `012.jpg` that is **2 of 6 boxes**, i.e. a third of the page's regions, that
are not story text. They would be OCR'd (and E5 shows the OCR will return
*something* for anything), translated, paid for, and typeset. The `seg` mask
touches them on both pages regardless of whether the box head fires.

This is an artefact of these particular scanlation-sourced fixtures and would
not appear on a clean scan — but the user's real input may well be this kind of
file, so MT-007 should not assume it away.

**(b) The box head and the mask disagree about sound effects, and MT-007's AC-6
depends on which one you use.** `012.jpg` carries art-integrated, unbubbled SFX
(パチ / パチ…) drawn into the artwork.

- The **YOLO box head does not fire on them** — no box on any パチ [MEASURED,
  confirmed visually in `spikes/MT-002/out/boxes-012.jpg.jpg`]. This is what
  MT-007 AC-6 wants.
- The **`seg` mask covers them clearly** [MEASURED, visible in
  `spikes/MT-002/out/mask-012.jpg.png`].

**Consequence, and it is a design constraint rather than a tuning note:** MT-019
must **not** inpaint the raw `seg` mask. Doing so would erase the artwork's
sound effects, violating MT-007's AC-6 via the inpainting path rather than the
detection path. The mask handed to the inpainter has to be the `seg` mask
**intersected with the accepted block boxes**. That is what I did in E7's
inpainting tests, and it worked; it is not currently written down in
`architecture.md`.

**A limit on all of the above:** the box head's behaviour on SFX was observed on
one page of one volume. It is a promising default, not a verified property.

### E7 — LaMa: non-garbage pixels?

**What would have counted as implausible, stated before the run:** uniform grey
or black fill where the surroundings are not; visible tiling seams; the original
text still legible through the inpaint; or — the strongest control — inpainting a
region that had **no** text failing to reproduce what was there.

```bash
PYTHONIOENCODING=utf-8 spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/lama_tests.py
PYTHONIOENCODING=utf-8 spikes/MT-002/.venv/Scripts/python.exe spikes/MT-002/lama_tone.py
```

**Control 1 — blank region, ground truth available.** A 128×128 patch of pure
white page margin (mean > 252, std < 2), masked and inpainted:

```
MAE vs ground truth: 5.89 / 255   (2.3%)
```
[MEASURED] Near-identical, as required. Slight grey tint, not visually apparent.

**Control 2 — screentone region with ground truth. This is the important one.**
A 96×96 patch of film-grain screentone on `014.jpg`, selected programmatically as
*flat after a 31×31 blur* (blur std 3.65) but *textured raw* — which is what
distinguishes halftone from artwork — masked and inpainted, then compared to the
pixels that were actually there:

```
MAE vs ground truth        : 25.18 / 255  (9.9%)
high-frequency energy      : 165.73 -> 153.77   (93% retained)
mean grey level            : 110.78 -> 108.28   (2.3 levels off)
```
[MEASURED]

**Read this carefully, because MAE is the wrong metric for texture.** Individual
grain dots cannot be expected to land in the same places, so a *perceptually
perfect* reconstruction would still score a large per-pixel MAE. The
informative numbers are the other two: the inpaint retained **93% of the
original high-frequency energy** and landed within **2.3 grey levels** of the
correct average tone. Visual inspection of
`spikes/MT-002/out/tone-014-patch-{orig,out}.png` confirms it: the output is
recognisable film grain at close to the right density, slightly more regular
than the original, and it even continued a dark stroke entering the patch from
the right edge. **It is not a grey smear.**

**A correction I am recording because it nearly became a false finding.** My
first attempt at this control selected the patch by "light and maximally
textured", which picked a patch of the *character's face*, not screentone. That
scored MAE 89.1 and lower HF energy, and had I reported it as written it would
have read as "LaMa fails on screentone" — a confident wrong conclusion of exactly
the kind this spike exists to avoid. Inspecting the saved image showed a smeared
face. What that discarded measurement legitimately shows is narrower and worth
one line: **LaMa does not reconstruct complex artwork** in a 128×128 hole. It was
never asked to; text regions are not faces.

`012.jpg` yielded **zero** qualifying screentone patches under the same
selection criteria [MEASURED] — its dot screentone is coarser and did not pass
the flat-after-blur test at this window size. So the screentone evidence rests
on `014.jpg` alone.

**Real case 1 — a bubble over screentone (`012.jpg`, box `(112,25,286,151)`).**
Mask = `seg` ∩ box, dilated 7×7 twice; 12,011 masked pixels.

```
inside-mask mean grey : 216.71 -> 250.21     (bubble interior, correctly白)
inside-mask std       :  68.21 ->  14.54
inside-mask HF energy : 102.03 ->  19.59
```
[MEASURED] Visual check (`lama-012-screentone-bubble-out.png`): the text
そうね私の方が上だったわ is **entirely gone**, the bubble interior is clean, the
bubble outline is intact, and the screentone dots *outside* the bubble are
undisturbed. The collapse in HF energy is correct here — the region is a white
bubble interior, which genuinely has no texture. Faint residue remains where the
`RawLazy.Com` watermark overlapped the mask.

**Real case 2 — white text on solid black, no bubble (`014.jpg`, box
`(968,907,1059,1133)`).** 19,269 masked pixels.

```
inside-mask mean grey : 112.64 -> 0.00
inside-mask std       : 110.42 -> 0.07
```
[MEASURED] Filled with pure black — which is the *correct* answer for text over
solid black artwork. Visual check (`lama-014-white-on-black-out.png`): 「魔都を国
の力とする」 is gone, the fill is indistinguishable from the surrounding black,
and the adjacent unmasked 私の理想に近いわ is untouched.

**Verdict on LaMa:** none of the pre-stated disqualifying conditions fired.
Texture is reconstructed at 93% of original HF energy with correct mean tone;
blank regions round-trip at 2.3% error; text is removed cleanly in both the
white-bubble and the solid-black case. **The dispatch's earlier "weakly supported
for want of a textured fixture" caveat is withdrawn** — the replacement fixtures
supported the test properly.

**What is still not tested:** tiling. Every measurement above is a single 512×512
tile. `stack.md`'s "obvious tiling seams" failure mode is **unmeasured**, because
a full page needs 4–12 tiles and I did not build a tiler. **MT-019 must test seams
explicitly.** That is the largest remaining gap in this spike.

### E8 — Sizes, and the DirectML alternative

```bash
du -sm spikes/MT-002/.venv/Lib/site-packages/{onnxruntime,nvidia,cv2,numpy,PIL}
```

| | MiB | Label |
|---|---|---|
| `nvidia/cu13` (cuBLAS, cuFFT, cuRAND, nvrtc, nvJitLink, runtime) | 1,015 | [MEASURED] |
| `nvidia/cudnn` | 565 | [MEASURED] |
| `onnxruntime` (the `-gpu` wheel) | 218 | [MEASURED] |
| `cv2` (opencv-python-headless) | 113 | [MEASURED] |
| `numpy` | 24 | [MEASURED] |
| `PIL` | 15 | [MEASURED] |
| whole spike venv (includes `onnx`, `huggingface_hub`, dev extras not shipped) | 2,041 | [MEASURED] |
| the five model weights | 728 | [MEASURED] |

For comparison [WEB, PyPI metadata]: `onnxruntime-directml` cp312 win_amd64 is a
**15.4 MB** wheel and `onnxruntime` (CPU) is **5.6 MB**, neither with any NVIDIA
dependency. The most recent cp312 DirectML build is **1.17.3**, well behind
1.30.0.

**Untested and left for MT-024**, flagged because it changes the installer by
more than a gigabyte: whether the app should ship DirectML by default and treat
CUDA as an opt-in download, and whether cuDNN (565 MiB) can be pruned given
which kernels these three models actually use. I did not attempt either.

**An fp16 option exists and I did not test it.** `onnx-community/manga-ocr-base-ONNX`
also publishes `encoder_model_fp16.onnx` (171,851,891 B) and
`decoder_model_fp16.onnx` (58,815,651 B) [MEASURED — HF API], which would cut the
weight bundle from 728 MiB to about 508 MiB. **No accuracy measurement was made
on them.** Do not adopt them without re-running E5's ground-truth scoring.

---

## Unreviewed code — nothing later may reuse this

Everything under `spikes/MT-002/` is **throwaway, unreviewed, untested spike
code** written by the Lead PO outside the RED→GREEN cycle. It exists only to
produce the numbers above.

**The pre-processing and post-processing in it must be re-derived test-first in
MT-007, MT-008 and MT-019, not copied.** Specifically, all of the following were
written by reading upstream source and are unverified by any test:

- `detect.py` — letterbox to 1024², channel order, the YOLO decode, the NMS, the
  `seg` threshold of 0.3, the 20-pixel connected-component floor. The thresholds
  `conf=0.4 / nms=0.35 / mask=0.3` are the upstream defaults, **not** values this
  spike chose or validated. MT-007 and MT-008 own those numbers.
- `ocr.py` — the ViT pre-processing, the greedy decode loop, the WordPiece
  detokenisation, and the `jaconv` post-processing.
- `lama.py` — the resize, the [0,1] normalisation, the mask polarity.

One specific trap worth naming: `detect.py` feeds the network **BGR**, because
upstream's `preprocess_img` converts BGR→RGB and then applies a `[::-1]` on the
channel axis that converts it back. I matched the net effect rather than the
apparent intent. MT-007 should verify that against upstream rather than trusting
this sentence.

## Fixtures, and their provenance (AC-5)

- `spikes/MT-002/pages/011–015.jpg` — **user-supplied interior story pages from a
  commercial digital release** (魔都精兵のスレイブ vol. 17), obtained from a
  scanlation site; `RawLazy.Com` and `DL-Raw.Se` watermarks are burned into the
  pixels. 1125×1600. **Held only in the gitignored `spikes/` tree and never
  committed.** These are not redistributable and must not become repository test
  fixtures; MT-007 and MT-019 need their own licensed or synthetic fixtures.
- `spikes/MT-002/oracle/manga-ocr-images/*.jpg` + `expected_results.json` —
  from `kha-white/manga-ocr` `tests/data/`, Apache-2.0 [WEB]. Used as a
  ground-truth oracle in E5.
- `spikes/MT-002/oracle/ctd/*` — `AisazuNihaIrarenai-003.jpg` and the author's
  reference mask, from `dmMaze/comic-text-detector` `data/`, GPL-3.0 repo [WEB].
  The page is from **Manga109**, an academic-use dataset. Used as a reference
  oracle in E6.

An earlier set of five pages (`001–005.jpg`) was replaced mid-spike; it was
volume front matter with no speech bubbles. **No number in this document comes
from that set** — every measurement above was re-run against `011–015.jpg`.

## Licence risk — needs a decision that is not mine

**The detector is the problem.** `dmMaze/comic-text-detector` is **GPL-3.0**
[MEASURED — GitHub API and the `LICENSE` file]. The ONNX re-upload
`mayocream/comic-text-detector-onnx` declares `apache-2.0` [WEB], but that is a
third party's metadata on a derivative of a GPL-3.0 project; it does not
obviously relicense anything. Additionally, the upstream README states the model
was trained on ~13k images, **1/3 from Manga109-s** [WEB] — a dataset whose terms
restrict use to academic research.

For a desktop application that is *distributed*, this is a real question with
three possible answers (ship it and accept GPL obligations; find a
permissively-licensed detector; train or commission one), and it is a product
and legal decision rather than a technical one. **I have not resolved it and it
should go to the user before EPIC-03 ships.** Nothing in this spike is blocked by
it — the technical answer is unaffected.

Lower-confidence, same family: the LaMa entry above records `apache-2.0` from the
`advimman/lama` repository and the `Carve/LaMa-ONNX` repo metadata. I verified
**repository metadata only**. The provenance of the `big-lama` checkpoint's
weights specifically was not traced, and inpainting checkpoints in this lineage
are sometimes distributed under non-commercial terms. Treat the LaMa licence as
*probably clean, unverified* rather than settled.

## What remains unresolved

Honest list, per the story's timebox instruction. None of these blocks EPIC-03.

1. **LaMa tiling and seams** — the single biggest gap. All inpainting evidence is
   single-tile. MT-019 must test a full page. (E7)
2. **DirectML** — never installed or run. The "CUDA → DirectML → CPU" chain in
   `stack.md` is, as written, not achievable in one install. (E8)
3. **Three models resident at once** — VRAM measured per model, never together.
4. **fp16 OCR weights** — would save 220 MiB, accuracy unmeasured. (E8)
5. **Beam search** — 10/12 is a greedy-decode lower bound. (E5)
6. **Cold-start / session construction time** — not measured. It affects
   perceived app startup and MT-024 may care.
7. **The detector's SFX behaviour** — observed on one page. (E6)
