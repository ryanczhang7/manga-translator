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

- `C:\Users\ryanc\Downloads\matoseiehino_v17` and `matoseiheino_v18` to
  `v21` - five full Japanese volumes, 1,021 pages, added on the user's
  instruction after the first measurement (2026-11-05, "Yes, measure them").
  Each volume is one "chapter" in the totals below; each includes its cover,
  contents, afterword and publisher pages.

Deliberately left out: the benchmark chapter (EPIC-07 O1, the user's to
name); the detector's thresholds and `_kind` itself (out of scope).

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

Run 2026-11-05 18:16 UTC (local time 12:16), on this machine, CUDA
provider, at commit `f621f5f` (the rule's commit; no source changed since).

**Weights.** `comic-text-detector.onnx` sha256
`1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f`, which is
the `packaging/models.json` entry (`mayocream/comic-text-detector-onnx` at
`a5d67ec772adef819ef5b0e7aa701fcf4c8bf74a`); the OCR is that manifest's
`manga-ocr` export. The script printed both hashes and they match.

**Command** (from the repository root; the spike pages live in the main
checkout, because `spikes/` is gitignored and a worktree has none):

```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 MANGATL_MODELS=packaging/models \
  uv run python spikes/MT-117/class_zero.py \
  "D:/manga-translator/spikes/MT-002/pages" \
  "C:/Users/ryanc/Downloads/mato sample" \
  "C:/Users/ryanc/Downloads/Mato no Seihei"
```

The script (AC-5; it uses only `detect_page_regions`, `sort_regions` and
`transcribe_page_regions` with the shipped sessions, and writes crops under
the gitignored `spikes/MT-117/crops/`):

```python
"""MT-117: every region the shipped detector finds on the given page folders."""
from __future__ import annotations
import os, sys
from pathlib import Path
import cv2
import numpy as np
from mangatl.compose import DETECTOR_FILENAME, OCR_SUBDIR, available_providers, resolve_models_dir
from mangatl.detect.page import detect_page_regions
from mangatl.detect.session import load_detector, selected_provider
from mangatl.domain.reading_order import sort_regions
from mangatl.models.manifest import MANIFEST_FILENAME, load_manifest, sha256_of
from mangatl.models.providers import select_providers
from mangatl.ocr.page import transcribe_page_regions
from mangatl.ocr.preprocess import crop_for_region
from mangatl.ocr.session import VOCAB_FILENAME, load_ocr, load_vocab

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
CROPS = Path("spikes/MT-117/crops")

def bbox(polygon):
    xs = [x for x, _ in polygon]; ys = [y for _, y in polygon]
    return min(xs), min(ys), max(xs), max(ys)

def main(folders):
    models_dir = resolve_models_dir(None, os.environ)
    providers = select_providers(available_providers())
    detector = load_detector(models_dir / DETECTOR_FILENAME, providers)
    ocr = load_ocr(models_dir / OCR_SUBDIR, providers)
    vocab = load_vocab(models_dir / OCR_SUBDIR / VOCAB_FILENAME)
    print(f"# provider\t{selected_provider(detector)}")
    print(f"# detector sha256 (file)\t{sha256_of(models_dir / DETECTOR_FILENAME)}")
    manifest = models_dir / MANIFEST_FILENAME
    if not manifest.is_file():
        manifest = Path("packaging") / MANIFEST_FILENAME
    for entry in load_manifest(manifest):
        if entry.path.endswith(DETECTOR_FILENAME):
            print(f"# detector sha256 (manifest {manifest})\t{entry.sha256}\t{entry.revision}")
    print("chapter\tpage\treading_index\tkind\tx0\ty0\tx1\ty1\tconfidence\tocr_empty\tocr")
    for folder in folders:
        chapter_dir = Path(folder); chapter = chapter_dir.name
        pages = sorted(p for p in chapter_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        totals = {"pages": 0, "regions": 0, "box": 0, "bubble": 0}
        (CROPS / chapter).mkdir(parents=True, exist_ok=True)
        for page_path in pages:
            image_bytes = page_path.read_bytes()
            page = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
            regions = sort_regions(detect_page_regions(detector, image_bytes))
            results = transcribe_page_regions(ocr, vocab, image_bytes, regions)
            totals["pages"] += 1
            for index, (region, result) in enumerate(zip(regions, results, strict=True)):
                totals["regions"] += 1; totals[region.kind] += 1
                x0, y0, x1, y1 = bbox(region.polygon)
                text = result.text.replace("\t", " ").replace("\n", " ")
                print(f"{chapter}\t{page_path.name}\t{index}\t{region.kind}\t{x0}\t{y0}\t{x1}\t{y1}"
                      f"\t{region.confidence:.3f}\t{int(result.ocr_empty)}\t{text}")
                cv2.imwrite(str(CROPS / chapter / f"{page_path.stem}-{index}-{region.kind}.png"),
                            crop_for_region(page, region))
                m = 40; h, w = page.shape[:2]
                cv2.imwrite(str(CROPS / chapter / f"{page_path.stem}-{index}-{region.kind}-context.png"),
                            page[max(0, y0 - m):min(h, y1 + m), max(0, x0 - m):min(w, x1 + m)])
        print(f"# totals\t{chapter}\tpages={totals['pages']}\tregions={totals['regions']}"
              f"\tclass0(box)={totals['box']}\tclass1(bubble)={totals['bubble']}")

if __name__ == "__main__":
    main(sys.argv[1:])
```

The human reading was made by the orchestrator looking at each region's
context crop (the box plus 40 px), one by one for class 0 and on labelled
contact sheets for class 1.

**Totals, per chapter.** "Chapter" is the folder for the first two; the
third folder holds pages of four chapters, split by the number in the file
name (`0134-...` is chapter 134).

| Chapter | Language on the page | Pages | Regions | Class 0 (`box`) | Class 1 (`bubble`) |
|---|---|---|---|---|---|
| `spikes/MT-002/pages` (011-015) | Japanese raw | 5 | 37 | 1 | 36 |
| `mato sample` (007, 008, 009, 016) | Japanese raw | 4 | 20 | 3 | 17 |
| `Mato no Seihei` ch. 134 | English-lettered scanlation | 3 | 17 | 2 | 15 |
| `Mato no Seihei` ch. 135 | English-lettered scanlation | 2 | 11 | 2 | 9 |
| `Mato no Seihei` ch. 136 | English-lettered scanlation | 3 | 11 | 4 | 7 |
| `Mato no Seihei` ch. 137 | English-lettered scanlation | 5 (`0137-001` has no region) | 15 | 4 | 11 |
| **All** | | **22** | **111** | **16** | **95** |

**Every class-0 region (AC-2).** Bounding box is `x0, y0, x1, y1` of the
polygon in page pixels.

| Chapter | Page | Index | Box | Confidence | OCR read | Human reading |
|---|---|---|---|---|---|---|
| MT-002 pages | 015.jpg | 0 | 107, 15, 292, 44 | 0.316 | `Ｒｅｎｄａｍａｚｏｎ` | watermark (`RawLazy.Com`, top strip) |
| mato sample | 007.jpg | 0 | 122, 18, 265, 42 | 0.277 | `それは、ここでよく` | watermark (`RawLazy.Com`) |
| mato sample | 008.jpg | 0 | 105, 10, 294, 47 | 0.304 | `「ＲあＬａｚｕｃｏｎ` | watermark (`RawLazy.Com`) |
| mato sample | 009.jpg | 0 | 244, 19, 289, 42 | 0.247 | `．．．` | watermark (the `.Com` end of `RawLazy.Com`) |
| ch. 134 | 0134-003.png | 0 | 905, 144, 1049, 198 | 0.426 | `エＮＨＵＭＡＮＴＥＲＭＳ，` | dialogue ("IN HUMAN TERMS," in a bubble) |
| ch. 134 | 0134-004.png | 3 | 88, 976, 246, 1163 | 0.424 | `＞＞０ＵＤＯＮＴＳＥＥＭ...` | dialogue ("YOU DON'T SEEM LIKE THE TYPE...") |
| ch. 135 | 0135-002.png | 2 | 589, 684, 766, 873 | 0.466 | `ＷＯＮＯＢＥＥＮＷＯＮＤＥＲ...` | dialogue ("I'D BEEN WONDERING IF...") |
| ch. 135 | 0135-009.png | 1 | 108, 561, 253, 771 | 0.439 | `ＩＣＡＮＡＮＩＡＮＤＬＥ...` | dialogue ("I CAN HANDLE ANY TRAPS...") |
| ch. 136 | 0136-007.png | 0 | 27, 25, 362, 325 | 0.558 | `いいよーならわーっ！！！...` | dialogue ("YOU COULD LET ME HAVE A HOT SPRING DIPLOMACY...") |
| ch. 136 | 0136-019.png | 0 | 449, 206, 596, 348 | 0.432 | `ＡＭｙＲＥＧＲＥＴＦＯＲ...` | dialogue ("MY REGRET FOR LETTING MY SIBLINGS DIE...") |
| ch. 136 | 0136-020.png | 0 | 899, 165, 1102, 319 | 0.768 | `あああああ...` | dialogue ("THIS CURSE MIGHT NOT BE ABLE TO DEFEAT...", outlined, on art) |
| ch. 136 | 0136-020.png | 5 | 471, 1786, 900, 1837 | 0.518 | `＃ｆｆｉｌｂＭＲＳｔｙｐｒｏｇｌｅｆｉｇｈｔｙ` | credit ("NEXT CHAPTER IS OUT 07/27(SATURDAY)!!", the scanlator's notice) |
| ch. 137 | 0137-007.png | 1 | 102, 1058, 335, 1356 | 0.507 | `いやいやいや...` | dialogue ("WHAT'S TAKING YOU SO LONG TO NEGOTIATE...") |
| ch. 137 | 0137-009.png | 0 | 883, 20, 1111, 297 | 0.517 | `！！` | dialogue ("SHE'S IN PLENTY OF DANGER...") |
| ch. 137 | 0137-009.png | 2 | 938, 480, 1179, 815 | 0.495 | `＞ＯＵＴＡＮＡＴＡＩＡＹＯ...` | dialogue ("YOU THINK TAIKYOKU-NEE WOULD LOSE...") |
| ch. 137 | 0137-022.png | 1 | 357, 1785, 801, 1830 | 0.531 | `＃Ｆ１＃Ｗ９Ｋ＄９６０００／０／３（Ａ）` | credit ("NEXT CHAPTER IS OUT 08/24 (SATURDAY)!!") |

By reading: **4 watermark, 2 credit, 10 dialogue**; no url, narration,
caption, sign, sfx or not-text. Every one of the 10 dialogue regions is on
an English-lettered page; on the two Japanese-raw chapters every class-0
region (4 of 4) is the `RawLazy.Com` watermark.

**Class-1 regions that are not dialogue or narration (AC-3).** 4 of 95.

| Chapter | Page | Index | Box | Confidence | OCR read | Human reading |
|---|---|---|---|---|---|---|
| ch. 135 | 0135-009.png | 4 | 814, 1606, 838, 1620 | 0.247 | `．．．` | not-text (screentone on a figure) |
| ch. 135 | 0135-009.png | 5 | 868, 1707, 879, 1725 | 0.340 | `．．．` | not-text (screentone) |
| ch. 135 | 0135-009.png | 6 | 779, 1807, 795, 1824 | 0.223 | `．．．` | not-text (a drawn hand) |
| ch. 137 | 0137-022.png | 0 | 984, 1488, 1080, 1833 | 0.476 | `はちきれそうな春へのＬｏｖｅｌ！！` | caption (Japanese song-lyric caption left untranslated on an English page) |

The other 91 class-1 regions read as dialogue or narration, including every
one of the 53 on the two Japanese chapters (white-on-black thought boxes on
`014.jpg` and the free-standing 決戦か / 共存か on `015.jpg` among them, and
the wordless `…` bubble `011.jpg` index 9). Two class-1 crops on Japanese
pages (`013.jpg` index 5, `014.jpg` index 8) carry the `DL-Raw.Se`
watermark **inside** a dialogue region: that mark is never its own region
here, as the story's field note also found.

**Two things this measurement does not reproduce.**

- MT-007 A-4 counted **4** class-0 boxes of 38 on `011-015.jpg`; this run
  finds **1** of 37 (on `015.jpg`). The detector weights are the manifest's;
  what changed between A-4 and this tree is not established here.
- The story's field note (2026-10-28) records `009.jpg` index 0 as the drawn
  sound effect ちゃぽ by the foot. This run finds `009.jpg` index 0 at the
  top strip (244, 19)-(289, 42), reading as the end of the watermark, and no
  region near the foot. The note read a project database that is no longer
  on the machine (`mato sample.mtproj` is gone), so the two cannot be
  compared region for region.

### The five volumes (second run)

Run 2026-11-05 18:53-19:04 UTC, same weights (the script printed the same
two hashes), same script, same branch:

```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 MANGATL_MODELS=packaging/models \
  uv run python spikes/MT-117/class_zero.py \
  "C:/Users/ryanc/Downloads/matoseiehino_v17" \
  "C:/Users/ryanc/Downloads/matoseiheino_v18" "C:/Users/ryanc/Downloads/matoseiheino_v19" \
  "C:/Users/ryanc/Downloads/matoseiheino_v20" "C:/Users/ryanc/Downloads/matoseiheino_v21"
```

The human reading of the 377 class-0 regions was made on contact sheets of
their context crops, 24 to a sheet, sorted by confidence, each labelled
with its volume, page, index and confidence; every crop was looked at.

| Volume | Pages | Regions | Class 0 | Class 1 | Class 0 by reading |
|---|---|---|---|---|---|
| `v17` | 199 | 1,328 | 240 | 1,088 | watermark 222, credit 16, narration 1, not-text 1 |
| `v18` | 200 | 1,215 | 33 | 1,182 | credit 33 |
| `v19` | 208 | 1,065 | 42 | 1,023 | credit 34, not-text 5, narration 2, caption 1 |
| `v20` | 207 | 1,189 | 32 | 1,157 | credit 29, sign 1, caption 1, not-text 1 |
| `v21` | 207 | 896 | 30 | 866 | credit 28, narration 1, not-text 1 |
| **All five** | **1,021** | **5,693** | **377** | **5,316** | watermark 222, credit 140, not-text 8, narration 4, caption 2, sign 1 |

Only `v17` carries scanlation watermarks (`RawLazy.Com` at the top,
`DL-Raw.Se` at the bottom); `v18`-`v21` carry none, and their class 0 is
the publisher's and the book's own furniture - the volume number, the
series logo, "JUMP COMICS+", "DIGITAL", "EXTRA PAGES", "contents",
"TAKAHIRO'S LINER NOTES", the cover-design credit, the author and artist
names, the publication-history small print. On `v17`, unlike the 22-page
set, `DL-Raw.Se` **is** a region of its own (for example `v17/006.jpg`
index 1, `v17/032.jpg` index 5).

**Confidence by reading, all 377:**

| Reading | Count | Confidence min | Confidence max |
|---|---|---|---|
| watermark | 222 | 0.135 | 0.486 |
| credit | 140 | 0.243 | 0.634 |
| not-text | 8 | 0.256 | 0.348 |
| narration | 4 | 0.358 | 0.445 |
| caption | 2 | 0.475 | 0.510 |
| sign | 1 | 0.375 | 0.375 |

The seven translatable class-0 regions (narration, caption, sign):

| Volume | Page | Index | Box | Confidence | OCR read | Human reading |
|---|---|---|---|---|---|---|
| v17 | 197.jpg | 4 | 689, 738, 948, 982 | 0.358 | `今巻はただきキャラクターが広くるのですが...` | narration (the author's afterword, a paragraph of prose) |
| v20 | p_167.jpg | 8 | 111, 1697, 170, 1728 | 0.375 | `．．．．．．` | sign (a placard drawn in the scene; its text too small to read) |
| v21 | p_204.jpg | 5 | 749, 881, 1043, 1127 | 0.387 | `全世界８５「万人の人」世紀ファンの皆様...` | narration (the artist's afterword) |
| v19 | 206.jpg | 5 | 748, 918, 1090, 1022 | 0.428 | `通りの支部だらは参考にするのに折り紙を...` | narration (afterword) |
| v19 | 206.jpg | 3 | 749, 579, 1021, 684 | 0.445 | `最近、ミネラルや食物繊維は意識して...` | narration (afterword) |
| v20 | p_199.jpg | 2 | 580, 1819, 913, 1859 | 0.475 | `☆２０３６年１月現在の情報です` | caption (the "information as of January" note on the next-volume page) |
| v19 | 201.jpg | 0 | 439, 1601, 1066, 1862 | 0.510 | `２０２６年１月発売予定・` | caption ("on sale January 2026!!", the next-volume notice) |

The highest-confidence watermarks, against which a threshold would have to
cut: `v17/188.jpg` index 2 (0.486, `-Raw.Se`), `v17/033.jpg` index 0 (0.406,
`RawLazy.Com` with the scanlator handle `Konomi_ttr` beside it, read as
credit), `v17/083.jpg` index 0 (0.403). Box height does not separate them
either: watermarks span 19-56 px, the sign is 31 px and the January note
40 px.

Every class-0 region of the five volumes, sorted by volume, page and index
(`#` is its position on the confidence-sorted contact sheets):

<details>
<summary>377 rows</summary>

| # | Volume | Page | Index | Box | Confidence | OCR read (first 24 chars) | Human reading |
|---|---|---|---|---|---|---|---|
| 212 | v17 | 001.jpg | 0 | 106, 18, 291, 43 | 0.355 | ＲａｗＬａｚｙＣｏｒｙ | watermark |
| 307 | v17 | 001.jpg | 1 | 797, 1167, 1014, 1306 | 0.449 | タガヒロ＿ュェ | credit |
| 316 | v17 | 001.jpg | 2 | 768, 1307, 1044, 1375 | 0.468 | 竹村洋平 | credit |
| 293 | v17 | 001.jpg | 3 | 852, 1518, 1069, 1569 | 0.432 | ＣＯＭＩＣＳ－ | credit |
| 265 | v17 | 001.jpg | 4 | 707, 1518, 836, 1558 | 0.397 | ＪＵＭＰ | credit |
| 244 | v17 | 002.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 19 | v17 | 002.jpg | 1 | 860, 1549, 881, 1581 | 0.193 | Ｄ | watermark |
| 156 | v17 | 003.jpg | 0 | 261, 19, 289, 42 | 0.300 | ．．． | watermark |
| 38 | v17 | 003.jpg | 1 | 161, 17, 223, 42 | 0.212 | ．．． | watermark |
| 73 | v17 | 003.jpg | 2 | 108, 17, 145, 42 | 0.233 | Ｒａｖ | watermark |
| 299 | v17 | 003.jpg | 3 | 655, 1521, 1019, 1575 | 0.439 | ．ｕＭＰ，ＧＯＷＩＣＳ－ | credit |
| 105 | v17 | 005.jpg | 0 | 105, 17, 292, 46 | 0.261 | 「そういうことですか」 | watermark |
| 229 | v17 | 006.jpg | 0 | 107, 17, 292, 43 | 0.373 | ＲａｎｄａｚｙＣｏｒｎ | watermark |
| 175 | v17 | 006.jpg | 1 | 848, 1547, 1020, 1582 | 0.319 | ＤＬ－Ｒａｗ．Ｓｅ | watermark |
| 128 | v17 | 007.jpg | 0 | 122, 18, 265, 42 | 0.277 | それは、ここでよく | watermark |
| 160 | v17 | 008.jpg | 0 | 105, 10, 294, 47 | 0.304 | 「ＲあＬａｚｕｃｏｎ | watermark |
| 83 | v17 | 009.jpg | 0 | 244, 19, 289, 42 | 0.247 | ．．． | watermark |
| 118 | v17 | 010.jpg | 0 | 105, 16, 246, 43 | 0.272 | ＲａｙｒＬａｚｙＣ | watermark |
| 174 | v17 | 015.jpg | 0 | 107, 15, 292, 44 | 0.316 | Ｒｅｎｄａｍａｚｏｎ | watermark |
| 172 | v17 | 017.jpg | 0 | 105, 2, 191, 47 | 0.315 | はぁ．．． | watermark |
| 92 | v17 | 017.jpg | 1 | 977, 1548, 1019, 1579 | 0.254 | ．．． | watermark |
| 86 | v17 | 017.jpg | 2 | 859, 1548, 951, 1579 | 0.249 | ＤＬ－Ｒａｖ | watermark |
| 210 | v17 | 019.jpg | 0 | 105, 17, 292, 42 | 0.354 | ＲａｖｌａｚｙＣｏｒｎ | watermark |
| 26 | v17 | 022.jpg | 0 | 271, 19, 290, 42 | 0.200 | ｍ | watermark |
| 50 | v17 | 022.jpg | 1 | 105, 18, 164, 43 | 0.222 | Ｒａｖ | watermark |
| 62 | v17 | 022.jpg | 6 | 914, 1548, 934, 1572 | 0.229 | ．．． | watermark |
| 130 | v17 | 023.jpg | 5 | 851, 1550, 894, 1577 | 0.278 | ．．． | watermark |
| 23 | v17 | 025.jpg | 0 | 246, 19, 266, 35 | 0.195 | 。 | watermark |
| 176 | v17 | 025.jpg | 1 | 106, 16, 226, 44 | 0.319 | Ｒａｖｌａｚｙ． | watermark |
| 191 | v17 | 025.jpg | 9 | 907, 1549, 1017, 1577 | 0.331 | 「ＲａｙｏＳｅ | watermark |
| 63 | v17 | 025.jpg | 10 | 874, 1560, 893, 1577 | 0.229 | ．．． | watermark |
| 283 | v17 | 026.jpg | 0 | 250, 11, 288, 45 | 0.421 | ．．． | watermark |
| 1 | v17 | 026.jpg | 1 | 124, 19, 144, 38 | 0.146 | ．．． | watermark |
| 140 | v17 | 027.jpg | 0 | 105, 14, 291, 44 | 0.284 | ．．．．．．．．．．．． | watermark |
| 226 | v17 | 027.jpg | 2 | 914, 1551, 982, 1577 | 0.369 | ．．．．．． | watermark |
| 159 | v17 | 029.jpg | 0 | 267, 19, 289, 41 | 0.303 | ｍ | watermark |
| 102 | v17 | 029.jpg | 1 | 106, 19, 144, 41 | 0.259 | Ｒａ | watermark |
| 227 | v17 | 030.jpg | 0 | 106, 16, 293, 43 | 0.370 | ＲａｗＬａｚｙＣｏｒｎ | watermark |
| 245 | v17 | 032.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 216 | v17 | 032.jpg | 5 | 852, 1547, 1018, 1580 | 0.359 | ＤＬ－Ｒａｖ．Ｓｅ | watermark |
| 272 | v17 | 033.jpg | 0 | 155, 25, 350, 81 | 0.406 | Ｋｏｎｏｍｉｔｔｒ | credit |
| 64 | v17 | 034.jpg | 0 | 178, 16, 294, 44 | 0.230 | ．．．．．． | watermark |
| 7 | v17 | 034.jpg | 1 | 122, 19, 143, 33 | 0.170 | ．．． | watermark |
| 57 | v17 | 035.jpg | 0 | 183, 15, 250, 43 | 0.226 | ．．．．．． | watermark |
| 254 | v17 | 036.jpg | 0 | 105, 15, 294, 44 | 0.385 | ＲａｗＬａｚｙＣｏｒｎ | watermark |
| 11 | v17 | 040.jpg | 7 | 851, 1550, 872, 1565 | 0.174 | ！ | watermark |
| 111 | v17 | 042.jpg | 0 | 252, 19, 277, 43 | 0.267 | が | watermark |
| 161 | v17 | 042.jpg | 1 | 106, 18, 169, 43 | 0.305 | Ｒａｗ | watermark |
| 220 | v17 | 044.jpg | 0 | 105, 16, 292, 43 | 0.360 | ＲａｖｌｌａｚｙＣｏｒｎ | watermark |
| 222 | v17 | 044.jpg | 1 | 849, 1550, 1018, 1578 | 0.362 | ＤＬ－Ｒａｗ．Ｓｅ | watermark |
| 170 | v17 | 045.jpg | 0 | 105, 16, 289, 44 | 0.313 | ＲａｖｌａｚｙＣｏｎｎ | watermark |
| 178 | v17 | 046.jpg | 0 | 114, 18, 294, 45 | 0.320 | ．．．．．． | watermark |
| 253 | v17 | 047.jpg | 0 | 217, 15, 288, 48 | 0.383 | それ | watermark |
| 103 | v17 | 047.jpg | 1 | 105, 15, 198, 44 | 0.260 | ＲａｖＬａ | watermark |
| 147 | v17 | 049.jpg | 0 | 181, 16, 290, 44 | 0.291 | ．．．．．． | watermark |
| 106 | v17 | 049.jpg | 1 | 114, 16, 144, 40 | 0.262 | ．．． | watermark |
| 127 | v17 | 050.jpg | 0 | 260, 19, 292, 42 | 0.276 | ．．． | watermark |
| 40 | v17 | 050.jpg | 1 | 111, 16, 141, 42 | 0.214 | Ｒａ | watermark |
| 70 | v17 | 051.jpg | 2 | 926, 1562, 945, 1580 | 0.232 | ．．． | watermark |
| 8 | v17 | 052.jpg | 0 | 277, 22, 292, 43 | 0.170 | ．．． | watermark |
| 9 | v17 | 052.jpg | 1 | 226, 17, 247, 37 | 0.171 | ん | watermark |
| 114 | v17 | 052.jpg | 2 | 106, 17, 164, 43 | 0.270 | Ｒａｖ | watermark |
| 16 | v17 | 052.jpg | 8 | 977, 1549, 1016, 1578 | 0.189 | Ｓｅ | watermark |
| 133 | v17 | 052.jpg | 9 | 916, 1548, 963, 1578 | 0.280 | ．．． | watermark |
| 96 | v17 | 053.jpg | 0 | 107, 18, 291, 42 | 0.255 | ＲａｗＬａみＣｏｍ | watermark |
| 53 | v17 | 055.jpg | 7 | 865, 1549, 895, 1572 | 0.224 | ．．． | watermark |
| 239 | v17 | 056.jpg | 0 | 107, 17, 291, 43 | 0.378 | ＲａｎｄａｓｅｒＣｏｒｎ | watermark |
| 136 | v17 | 057.jpg | 0 | 106, 15, 291, 43 | 0.281 | ＲａｗＬａｚｙＣｏｒｎ | watermark |
| 209 | v17 | 062.jpg | 0 | 106, 16, 291, 44 | 0.351 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 204 | v17 | 066.jpg | 0 | 105, 15, 293, 45 | 0.348 | ＲａｗＬａｚｙＣｏｒｎ | watermark |
| 3 | v17 | 068.jpg | 0 | 227, 28, 247, 43 | 0.155 | ．．． | watermark |
| 123 | v17 | 068.jpg | 1 | 106, 15, 145, 44 | 0.274 | Ｒａｖ | watermark |
| 76 | v17 | 070.jpg | 0 | 243, 19, 294, 44 | 0.238 | ．．． | watermark |
| 134 | v17 | 070.jpg | 1 | 105, 16, 228, 46 | 0.280 | Ｒａｖｌａｚｙ． | watermark |
| 261 | v17 | 071.jpg | 0 | 217, 10, 291, 47 | 0.394 | ん | watermark |
| 196 | v17 | 071.jpg | 1 | 935, 1543, 1006, 1583 | 0.338 | ｂ | watermark |
| 129 | v17 | 072.jpg | 0 | 179, 15, 291, 44 | 0.277 | ａｚｙ．Ｃｏｍ | watermark |
| 15 | v17 | 072.jpg | 1 | 114, 16, 131, 37 | 0.187 | Ｒ | watermark |
| 131 | v17 | 073.jpg | 0 | 107, 14, 288, 44 | 0.278 | ＲａｖａＬａｚｏｌＣｈｒｔ | watermark |
| 198 | v17 | 073.jpg | 6 | 977, 1549, 1018, 1580 | 0.339 | ．．．．．．Ｓｅ | watermark |
| 112 | v17 | 073.jpg | 7 | 849, 1549, 934, 1580 | 0.267 | ＤＬ－Ｒ | watermark |
| 237 | v17 | 074.jpg | 0 | 105, 17, 291, 43 | 0.377 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 238 | v17 | 075.jpg | 0 | 106, 17, 291, 43 | 0.377 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 61 | v17 | 076.jpg | 0 | 242, 19, 267, 43 | 0.228 | ．．． | watermark |
| 93 | v17 | 077.jpg | 0 | 226, 18, 293, 42 | 0.254 | ．．．Ｃｏｍ、 | watermark |
| 120 | v17 | 077.jpg | 1 | 106, 18, 212, 42 | 0.273 | ．．．．．． | watermark |
| 179 | v17 | 078.jpg | 0 | 105, 16, 292, 43 | 0.320 | ＲａｖｌｌａｚｙＣｏｒｎ | watermark |
| 42 | v17 | 078.jpg | 1 | 855, 1549, 881, 1583 | 0.215 | Ｄ | watermark |
| 58 | v17 | 079.jpg | 0 | 114, 16, 198, 44 | 0.226 | ．．．．．． | watermark |
| 257 | v17 | 080.jpg | 0 | 218, 26, 286, 46 | 0.391 | ．．． | watermark |
| 25 | v17 | 080.jpg | 1 | 112, 18, 131, 43 | 0.199 | ．．． | watermark |
| 201 | v17 | 080.jpg | 7 | 977, 1548, 1018, 1580 | 0.340 | ．．．Ｓｅ | watermark |
| 270 | v17 | 083.jpg | 0 | 107, 17, 293, 43 | 0.403 | ＲａｗＬａｚｙＣｏｎ | watermark |
| 75 | v17 | 086.jpg | 0 | 105, 15, 248, 45 | 0.234 | ＲａｗＬａｚｙ．Ｃ | watermark |
| 185 | v17 | 087.jpg | 0 | 242, 16, 291, 44 | 0.328 | ．．． | watermark |
| 87 | v17 | 087.jpg | 1 | 107, 16, 226, 45 | 0.250 | ＲａｗＬａｚｙ． | watermark |
| 28 | v17 | 089.jpg | 0 | 208, 27, 224, 42 | 0.201 | ！ | watermark |
| 186 | v17 | 092.jpg | 5 | 983, 1549, 1011, 1564 | 0.328 | ．．． | watermark |
| 52 | v17 | 093.jpg | 0 | 244, 19, 290, 42 | 0.223 | ．．． | watermark |
| 230 | v17 | 094.jpg | 0 | 106, 16, 292, 43 | 0.373 | ＲａｗＬａｚｙＣｏｒｎ | watermark |
| 59 | v17 | 094.jpg | 7 | 873, 1550, 894, 1566 | 0.227 | ．．． | watermark |
| 193 | v17 | 095.jpg | 0 | 106, 15, 294, 44 | 0.336 | Ｒａｖｉｃａｚｏｎは | watermark |
| 94 | v17 | 095.jpg | 3 | 985, 1549, 1019, 1579 | 0.254 | Ｓｅ | watermark |
| 246 | v17 | 096.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 55 | v17 | 098.jpg | 0 | 252, 20, 276, 43 | 0.225 | ．．． | watermark |
| 84 | v17 | 098.jpg | 1 | 105, 16, 145, 44 | 0.247 | ．．． | watermark |
| 2 | v17 | 099.jpg | 0 | 279, 24, 292, 43 | 0.147 | ．．． | watermark |
| 60 | v17 | 099.jpg | 1 | 107, 15, 144, 42 | 0.227 | Ｒａｖ | watermark |
| 29 | v17 | 100.jpg | 0 | 260, 20, 290, 43 | 0.201 | ＞ｍ | watermark |
| 197 | v17 | 100.jpg | 1 | 106, 18, 226, 43 | 0.338 | Ｐａｖｌａｚｙ． | watermark |
| 142 | v17 | 100.jpg | 7 | 927, 1564, 950, 1580 | 0.287 | ．．． | watermark |
| 82 | v17 | 100.jpg | 8 | 852, 1548, 882, 1580 | 0.246 | Ｄ | watermark |
| 88 | v17 | 103.jpg | 0 | 244, 19, 291, 42 | 0.250 | ．．． | watermark |
| 95 | v17 | 103.jpg | 1 | 105, 19, 131, 42 | 0.254 | Ｒ | watermark |
| 132 | v17 | 104.jpg | 0 | 105, 17, 294, 43 | 0.278 | ＲａｗＬａｚｙＣｏｎ | watermark |
| 12 | v17 | 106.jpg | 0 | 245, 27, 266, 43 | 0.177 | 。 | watermark |
| 56 | v17 | 106.jpg | 1 | 177, 19, 222, 43 | 0.225 | ．．． | watermark |
| 65 | v17 | 106.jpg | 2 | 106, 14, 131, 43 | 0.230 | Ｒ | watermark |
| 192 | v17 | 107.jpg | 0 | 267, 19, 289, 43 | 0.333 | ｍ | watermark |
| 43 | v17 | 107.jpg | 1 | 105, 17, 176, 43 | 0.215 | Ｒａｙａ | watermark |
| 116 | v17 | 107.jpg | 8 | 977, 1548, 1019, 1579 | 0.271 | ．．． | watermark |
| 90 | v17 | 107.jpg | 9 | 858, 1548, 951, 1579 | 0.253 | ＤＬ－Ｒａｖ | watermark |
| 20 | v17 | 108.jpg | 8 | 980, 1548, 1004, 1566 | 0.193 | で | watermark |
| 145 | v17 | 109.jpg | 0 | 108, 16, 291, 44 | 0.290 | ＲａｗｌａｚｙＣｏｍ | watermark |
| 10 | v17 | 110.jpg | 0 | 268, 19, 292, 38 | 0.172 | ．．． | watermark |
| 37 | v17 | 110.jpg | 1 | 192, 19, 222, 41 | 0.210 | ２ | watermark |
| 41 | v17 | 113.jpg | 0 | 205, 19, 226, 44 | 0.214 | ．．． | watermark |
| 121 | v17 | 113.jpg | 1 | 122, 14, 185, 43 | 0.273 | ａｖａは | watermark |
| 117 | v17 | 114.jpg | 0 | 242, 19, 291, 44 | 0.271 | ．．． | watermark |
| 39 | v17 | 114.jpg | 1 | 176, 25, 198, 43 | 0.213 | ．．． | watermark |
| 27 | v17 | 114.jpg | 2 | 105, 20, 119, 39 | 0.200 | Ｆ | watermark |
| 182 | v17 | 116.jpg | 1 | 225, 17, 290, 43 | 0.322 | ．．．．．． | watermark |
| 137 | v17 | 116.jpg | 2 | 113, 17, 199, 43 | 0.281 | Ｒａｌｌａｚ | watermark |
| 5 | v17 | 117.jpg | 0 | 105, 17, 120, 41 | 0.167 | ．．． | watermark |
| 247 | v17 | 118.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 180 | v17 | 119.jpg | 0 | 108, 16, 293, 44 | 0.320 | ＲａｗｌａｚｙＣｏｒｎ | watermark |
| 89 | v17 | 119.jpg | 9 | 978, 1548, 1017, 1580 | 0.252 | Ｓｅ | watermark |
| 194 | v17 | 120.jpg | 3 | 965, 1534, 1007, 1553 | 0.336 | ん | watermark |
| 259 | v17 | 120.jpg | 4 | 876, 1534, 939, 1571 | 0.392 | ．．． | watermark |
| 167 | v17 | 122.jpg | 4 | 977, 1548, 1020, 1581 | 0.311 | Ｓｅ | watermark |
| 32 | v17 | 122.jpg | 5 | 927, 1555, 950, 1574 | 0.204 | ２ | watermark |
| 262 | v17 | 123.jpg | 0 | 140, 13, 228, 45 | 0.395 | ．．． | watermark |
| 258 | v17 | 123.jpg | 1 | 102, 33, 124, 45 | 0.391 | ．．． | watermark |
| 217 | v17 | 124.jpg | 0 | 106, 18, 289, 41 | 0.359 | ＲａｖｉｌａｚｙＳｏｒｎ | watermark |
| 124 | v17 | 127.jpg | 0 | 245, 19, 291, 45 | 0.275 | ．．． | watermark |
| 125 | v17 | 127.jpg | 1 | 104, 16, 223, 44 | 0.275 | ＲａｒｖＬａｚｙ | watermark |
| 107 | v17 | 127.jpg | 8 | 977, 1548, 1017, 1583 | 0.263 | ．．．．．． | watermark |
| 85 | v17 | 127.jpg | 9 | 918, 1554, 934, 1572 | 0.248 | ？ | watermark |
| 97 | v17 | 127.jpg | 10 | 852, 1548, 894, 1583 | 0.255 | ＤＩ | watermark |
| 51 | v17 | 129.jpg | 0 | 270, 19, 292, 42 | 0.222 | ｍ | watermark |
| 49 | v17 | 129.jpg | 1 | 177, 19, 199, 42 | 0.221 | ．．． | watermark |
| 47 | v17 | 129.jpg | 2 | 114, 17, 144, 37 | 0.218 | Ｒａｙ | watermark |
| 113 | v17 | 131.jpg | 0 | 118, 15, 292, 44 | 0.269 | ａｗＬａｚｙ．Ｃｏｎｔ | watermark |
| 24 | v17 | 132.jpg | 0 | 227, 16, 244, 32 | 0.195 | で | watermark |
| 67 | v17 | 132.jpg | 1 | 105, 16, 164, 44 | 0.231 | ．．． | watermark |
| 68 | v17 | 133.jpg | 0 | 191, 19, 224, 47 | 0.231 | ．．． | watermark |
| 30 | v17 | 134.jpg | 5 | 861, 1565, 880, 1580 | 0.201 | ．．． | watermark |
| 148 | v17 | 135.jpg | 0 | 968, 1548, 1019, 1580 | 0.291 | ．．．Ｓｅ | watermark |
| 77 | v17 | 135.jpg | 1 | 858, 1548, 951, 1580 | 0.242 | ＤＬ－Ｒａｖ | watermark |
| 202 | v17 | 137.jpg | 0 | 105, 18, 290, 43 | 0.341 | ＲａｖｌａｚｙＣｏｍ | watermark |
| 0 | v17 | 138.jpg | 0 | 277, 19, 293, 42 | 0.135 | ．．． | watermark |
| 13 | v17 | 139.jpg | 0 | 226, 15, 260, 42 | 0.185 | ．．． | watermark |
| 248 | v17 | 140.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 79 | v17 | 141.jpg | 0 | 268, 19, 291, 43 | 0.243 | ！？ | watermark |
| 155 | v17 | 141.jpg | 5 | 982, 1549, 1018, 1579 | 0.299 | Ｓｅ | watermark |
| 45 | v17 | 141.jpg | 6 | 860, 1549, 882, 1579 | 0.216 | Ｄ | watermark |
| 213 | v17 | 142.jpg | 0 | 107, 17, 292, 45 | 0.356 | Ｐａｃｒｏｉｔアプリケーション | watermark |
| 150 | v17 | 143.jpg | 0 | 106, 17, 224, 43 | 0.293 | Ｒａｖｕｌａｚｙ | watermark |
| 17 | v17 | 144.jpg | 4 | 859, 1549, 881, 1583 | 0.190 | ．．． | watermark |
| 81 | v17 | 145.jpg | 0 | 108, 15, 245, 44 | 0.244 | ＲａｗｂａｚｙＣ | watermark |
| 141 | v17 | 146.jpg | 2 | 205, 14, 294, 46 | 0.286 | ．．．．．． | watermark |
| 78 | v17 | 146.jpg | 3 | 124, 19, 168, 43 | 0.242 | ．．． | watermark |
| 6 | v17 | 148.jpg | 0 | 114, 18, 130, 38 | 0.167 | ．．． | watermark |
| 33 | v17 | 149.jpg | 0 | 122, 21, 144, 42 | 0.204 | ．．． | watermark |
| 21 | v17 | 150.jpg | 0 | 269, 19, 291, 43 | 0.193 | ．．． | watermark |
| 74 | v17 | 150.jpg | 1 | 105, 18, 176, 43 | 0.233 | Ｒａｙｒｔ | watermark |
| 138 | v17 | 156.jpg | 0 | 105, 16, 224, 44 | 0.283 | Ｒａｖｌａｚｙ | watermark |
| 153 | v17 | 158.jpg | 0 | 105, 14, 293, 45 | 0.294 | ＲａｖｌａｚｙＣｏｒｎ | watermark |
| 171 | v17 | 160.jpg | 0 | 107, 16, 293, 43 | 0.314 | ＲａｙｌｌａｚｙＣｏｒｎ | watermark |
| 249 | v17 | 162.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 4 | v17 | 166.jpg | 0 | 269, 19, 291, 34 | 0.158 | ．．． | watermark |
| 44 | v17 | 166.jpg | 1 | 107, 15, 128, 36 | 0.215 | は | watermark |
| 69 | v17 | 168.jpg | 0 | 114, 17, 154, 43 | 0.231 | ．．．．．． | watermark |
| 164 | v17 | 170.jpg | 0 | 246, 19, 291, 43 | 0.309 | ．．． | watermark |
| 173 | v17 | 170.jpg | 1 | 106, 17, 222, 43 | 0.315 | Ｒａｖｌａｚｙ | watermark |
| 18 | v17 | 172.jpg | 0 | 272, 19, 290, 41 | 0.190 | ！？ | watermark |
| 14 | v17 | 172.jpg | 1 | 179, 19, 223, 43 | 0.186 | ．．． | watermark |
| 122 | v17 | 174.jpg | 0 | 204, 14, 290, 46 | 0.273 | Ｐｙｃｏｍ | watermark |
| 119 | v17 | 174.jpg | 1 | 122, 19, 145, 43 | 0.272 | お | watermark |
| 22 | v17 | 175.jpg | 0 | 269, 19, 291, 43 | 0.194 | ．．． | watermark |
| 31 | v17 | 175.jpg | 1 | 177, 19, 223, 44 | 0.201 | あそー | watermark |
| 101 | v17 | 176.jpg | 0 | 105, 16, 213, 44 | 0.258 | Ｒａｖｌａ２ | watermark |
| 54 | v17 | 177.jpg | 0 | 270, 19, 293, 44 | 0.224 | ．．． | watermark |
| 71 | v17 | 177.jpg | 1 | 113, 15, 250, 43 | 0.232 | ．．．．．．．．． | watermark |
| 48 | v17 | 178.jpg | 2 | 646, 1420, 657, 1438 | 0.220 | ．．． | watermark |
| 46 | v17 | 178.jpg | 3 | 733, 1435, 753, 1450 | 0.217 | ！！ | watermark |
| 181 | v17 | 178.jpg | 4 | 663, 1452, 747, 1511 | 0.320 | しかし | not-text |
| 34 | v17 | 178.jpg | 5 | 986, 1561, 1002, 1580 | 0.204 | ．．． | watermark |
| 169 | v17 | 178.jpg | 6 | 849, 1547, 953, 1583 | 0.312 | ＤＬ－Ｒａｖ | watermark |
| 177 | v17 | 181.jpg | 0 | 122, 15, 288, 47 | 0.319 | ．．．．．．．．．．．． | watermark |
| 250 | v17 | 184.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 205 | v17 | 185.jpg | 0 | 107, 16, 292, 44 | 0.348 | ＲａｎｙｌｉａｚｙＣｏｒｎ | watermark |
| 100 | v17 | 186.jpg | 0 | 181, 15, 290, 44 | 0.257 | ．．． | watermark |
| 165 | v17 | 186.jpg | 1 | 107, 15, 158, 44 | 0.309 | ．．． | watermark |
| 109 | v17 | 186.jpg | 4 | 996, 1555, 1013, 1583 | 0.266 | ．．． | watermark |
| 256 | v17 | 187.jpg | 0 | 190, 32, 247, 43 | 0.389 | ．．． | watermark |
| 108 | v17 | 187.jpg | 1 | 106, 15, 144, 43 | 0.263 | Ｒａｖ | watermark |
| 325 | v17 | 188.jpg | 2 | 927, 1544, 964, 1584 | 0.486 | ．．． | watermark |
| 218 | v17 | 188.jpg | 3 | 834, 1544, 889, 1576 | 0.359 | は | watermark |
| 235 | v17 | 190.jpg | 0 | 107, 17, 292, 43 | 0.375 | ＲａｎｄａｚｙＣｏｒｎ | watermark |
| 158 | v17 | 191.jpg | 0 | 106, 16, 289, 46 | 0.302 | Ｐａｖｉｌａｚｏｎｅの | watermark |
| 225 | v17 | 192.jpg | 0 | 105, 17, 291, 43 | 0.367 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 35 | v17 | 193.jpg | 0 | 150, 17, 199, 43 | 0.206 | ．．． | watermark |
| 251 | v17 | 194.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 211 | v17 | 194.jpg | 1 | 334, 1513, 797, 1558 | 0.354 | 運動機能力が試すデイン書が、表紙デザインクスタビ | credit |
| 146 | v17 | 194.jpg | 2 | 980, 1550, 1018, 1579 | 0.290 | Ｓｅ | watermark |
| 66 | v17 | 194.jpg | 3 | 927, 1555, 950, 1575 | 0.230 | ２ | watermark |
| 104 | v17 | 194.jpg | 4 | 859, 1550, 894, 1579 | 0.260 | ＤＩ | watermark |
| 240 | v17 | 195.jpg | 0 | 105, 17, 291, 43 | 0.379 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 36 | v17 | 195.jpg | 3 | 985, 1549, 1019, 1580 | 0.208 | Ｓｅ | watermark |
| 72 | v17 | 195.jpg | 4 | 858, 1549, 950, 1580 | 0.232 | ＤＬ－Ｒａ | watermark |
| 252 | v17 | 196.jpg | 0 | 105, 17, 291, 43 | 0.382 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 291 | v17 | 196.jpg | 1 | 870, 1292, 990, 1403 | 0.430 | わ。 | credit |
| 313 | v17 | 196.jpg | 2 | 869, 1405, 1026, 1469 | 0.453 | ＤＩＧＩＴＡＬＳＨＥＳＲＪＷＲＣＯＭＣ | credit |
| 231 | v17 | 197.jpg | 0 | 108, 17, 289, 42 | 0.373 | ＲａｗｄｅａｚｙＣｏｒｍ | watermark |
| 314 | v17 | 197.jpg | 1 | 3, 79, 173, 114 | 0.457 | ＢｘＴＲＡＲＡＧＡＳ | credit |
| 344 | v17 | 197.jpg | 2 | 27, 357, 102, 382 | 0.517 | いいかってのＮＨＣＳＰＬＵＳ | credit |
| 214 | v17 | 197.jpg | 4 | 689, 738, 948, 982 | 0.358 | 今巻はただきキャラクターが広くるのですが、僕は女 | narration |
| 187 | v17 | 197.jpg | 6 | 674, 1254, 758, 1303 | 0.328 | でもいいです。今日は、またまたまたはもうちょっと | credit |
| 215 | v17 | 197.jpg | 8 | 850, 1550, 1017, 1578 | 0.358 | ＤＬ－Ｒａｗ．Ｓｅ | watermark |
| 243 | v17 | 198.jpg | 0 | 105, 17, 291, 43 | 0.381 | ＲａｗＬａｚｙＣｏｍ | watermark |
| 356 | v17 | 198.jpg | 1 | 949, 81, 1123, 115 | 0.526 | 「現在ＲＡＲＡＧＡＳ | credit |
| 282 | v17 | 198.jpg | 6 | 670, 1378, 965, 1409 | 0.420 | ＪｕＭＰ．ＣＯＮＩＣＳ－ | credit |
| 163 | v17 | 198.jpg | 7 | 977, 1550, 1018, 1579 | 0.308 | ．．． | watermark |
| 149 | v17 | 198.jpg | 8 | 852, 1550, 952, 1579 | 0.292 | ＤＬ－Ｒａｖ | watermark |
| 206 | v17 | 199.jpg | 0 | 107, 17, 290, 42 | 0.348 | ＲａｗｄａｚｙＣｏｒｎ | watermark |
| 300 | v17 | 199.jpg | 1 | 2, 79, 175, 115 | 0.442 | ＦＸＸＴＲＡＲＡＧＥＳ | credit |
| 162 | v17 | 199.jpg | 2 | 164, 1352, 360, 1414 | 0.306 | ｄジｕブコミックスｅＯＭＩＬＣＳ | credit |
| 154 | v17 | 199.jpg | 3 | 977, 1550, 1018, 1578 | 0.294 | Ｓｅ | watermark |
| 110 | v17 | 199.jpg | 4 | 858, 1550, 950, 1578 | 0.266 | ＤＬ－Ｒａ | watermark |
| 287 | v18 | 00001.jpeg | 0 | 37, 820, 298, 1009 | 0.428 | タカヒロ竹村洋平 | credit |
| 294 | v18 | 00001.jpeg | 1 | 28, 1586, 389, 1635 | 0.432 | Ｊｕｍｐ－ｃｏｍｌＣＳ | credit |
| 331 | v18 | 00003.jpeg | 0 | 717, 1821, 1127, 1874 | 0.491 | ＪＵＭＰＣＯＭＩＣＳ－ | credit |
| 263 | v18 | 00006.jpeg | 0 | 1012, 680, 1103, 749 | 0.396 | １８ | credit |
| 346 | v18 | 00006.jpeg | 1 | 363, 641, 989, 784 | 0.518 | ＰＯＭＴＯＨＩＳ | credit |
| 241 | v18 | 00188.jpeg | 0 | 870, 1425, 952, 1503 | 0.379 | ．．． | credit |
| 224 | v18 | 00188.jpeg | 1 | 779, 1514, 820, 1548 | 0.366 | ん | credit |
| 321 | v18 | 00188.jpeg | 2 | 749, 1418, 839, 1526 | 0.480 | 日記と | credit |
| 143 | v18 | 00188.jpeg | 3 | 750, 1396, 780, 1432 | 0.287 | す | credit |
| 370 | v18 | 00188.jpeg | 4 | 630, 1442, 723, 1549 | 0.562 | ．．．．．． | credit |
| 168 | v18 | 00188.jpeg | 5 | 579, 1530, 596, 1548 | 0.311 | ．．． | credit |
| 376 | v18 | 00188.jpeg | 6 | 668, 1680, 906, 1757 | 0.634 | ．．．．．． | credit |
| 189 | v18 | 00189.jpeg | 0 | 614, 652, 651, 678 | 0.330 | ん | credit |
| 366 | v18 | 00189.jpeg | 1 | 231, 652, 642, 854 | 0.548 | 魔術病院の人は、 | credit |
| 266 | v18 | 00189.jpeg | 2 | 55, 910, 716, 1067 | 0.397 | １１／１７日（月）００日（土） | credit |
| 260 | v18 | 00194.jpeg | 0 | 223, 1788, 985, 1864 | 0.393 | このタグラムは９４時３時、２０１８年６月１２時間 | credit |
| 326 | v18 | 00195.jpeg | 0 | 250, 556, 410, 748 | 0.486 | ＤＩＧＩＴＡＬＳＨＥＢＡＲＩＭＣＯＭに | credit |
| 337 | v18 | 00196.jpeg | 0 | 945, 1551, 1101, 1685 | 0.511 | すぐ | credit |
| 308 | v18 | 00196.jpeg | 1 | 943, 1687, 1113, 1763 | 0.449 | ＤＩＧＩＴＡＬＳＨＥＲＡＪＷＰＣＯＮＣ | credit |
| 367 | v18 | 00197.jpeg | 0 | 3, 98, 191, 134 | 0.552 | ＦＸＩＲＡＢＡＧＥＳ | credit |
| 276 | v18 | 00197.jpeg | 1 | 28, 343, 114, 417 | 0.409 | す | credit |
| 360 | v18 | 00197.jpeg | 2 | 37, 428, 109, 459 | 0.535 | Ｕｎｍｐ．ｃｏｍｉｃｓＰＬＵＳ | credit |
| 91 | v18 | 00197.jpeg | 6 | 730, 1533, 862, 1565 | 0.253 | それはどうしても、このままでもこのままでもないで | credit |
| 341 | v18 | 00198.jpeg | 0 | 1029, 98, 1220, 136 | 0.514 | 「ライバスト」ＰＡＧＥＳ | credit |
| 334 | v18 | 00198.jpeg | 1 | 458, 383, 990, 452 | 0.501 | 魔都精兵のスレイン | credit |
| 277 | v18 | 00198.jpeg | 2 | 734, 1654, 1058, 1692 | 0.411 | ＪＵＭＰＣＯＭＩＣＳＴ－ | credit |
| 361 | v18 | 00199.jpeg | 0 | 2, 97, 192, 135 | 0.535 | ＦＸＴＲＡＥＡＧＥＳ | credit |
| 139 | v18 | 00199.jpeg | 1 | 176, 1625, 323, 1695 | 0.283 | ＪジャＵブコミックスＣＯＭＩＣＳ | credit |
| 371 | v18 | 1az.jpeg | 0 | 315, 29, 508, 70 | 0.577 | 魔都精兵の | credit |
| 199 | v18 | 1az.jpeg | 5 | 42, 579, 194, 666 | 0.339 | タカヒロ | credit |
| 284 | v18 | 1az.jpeg | 6 | 22, 666, 211, 720 | 0.421 | 竹村洋平 | credit |
| 278 | v18 | 1az.jpeg | 7 | 788, 1137, 870, 1188 | 0.411 | ．．．．．． | credit |
| 242 | v18 | 1az.jpeg | 8 | 19, 1135, 282, 1175 | 0.380 | ＪｕＭＰｒｏＯＭＩＣＳ | credit |
| 233 | v19 | 001.jpg | 0 | 778, 104, 868, 129 | 0.374 | ＤＩＧＩＴＡＬ | credit |
| 228 | v19 | 001.jpg | 1 | 569, 705, 720, 785 | 0.371 | タカヒロ | credit |
| 285 | v19 | 001.jpg | 2 | 549, 789, 732, 837 | 0.423 | 竹村洋平 | credit |
| 80 | v19 | 001.jpg | 3 | 774, 1063, 845, 1081 | 0.243 | ．．． | credit |
| 115 | v19 | 001.jpg | 4 | 834, 1118, 851, 1136 | 0.270 | ！ | credit |
| 288 | v19 | 001.jpg | 5 | 789, 1139, 870, 1188 | 0.428 | ．．．．．． | credit |
| 271 | v19 | 001.jpg | 6 | 22, 1136, 282, 1171 | 0.403 | ＪＵＭＰＣＯＭＩＣＳ | credit |
| 208 | v19 | 002.jpg | 0 | 1095, 971, 1118, 1007 | 0.349 | ん | credit |
| 273 | v19 | 002.jpg | 1 | 951, 912, 1080, 1018 | 0.406 | １９ | credit |
| 319 | v19 | 002.jpg | 2 | 189, 1820, 448, 1873 | 0.476 | ＣＯＭＩＣＳ－ | credit |
| 286 | v19 | 002.jpg | 3 | 37, 1824, 170, 1871 | 0.423 | ＪＵＭＰ | credit |
| 328 | v19 | 004.jpg | 0 | 711, 1818, 1126, 1872 | 0.488 | ＪｕＭＰ．ｃｏＷｌＧＳ－ | credit |
| 183 | v19 | 007.jpg | 0 | 1012, 681, 1106, 749 | 0.322 | １９ | credit |
| 352 | v19 | 007.jpg | 1 | 362, 639, 989, 784 | 0.523 | Ｃｏｎｄｅｎｌｓ | credit |
| 195 | v19 | 087.jpg | 0 | 826, 218, 854, 247 | 0.336 | ．．．．．． | not-text |
| 166 | v19 | 087.jpg | 1 | 872, 249, 901, 272 | 0.310 | ．．．．．． | not-text |
| 207 | v19 | 087.jpg | 2 | 790, 265, 825, 297 | 0.348 | ああ | not-text |
| 184 | v19 | 087.jpg | 3 | 887, 304, 916, 354 | 0.325 | ．．．．．． | not-text |
| 144 | v19 | 087.jpg | 4 | 799, 324, 827, 356 | 0.289 | ．．． | not-text |
| 279 | v19 | 195.jpg | 0 | 902, 1421, 1004, 1503 | 0.416 | ．．． | credit |
| 364 | v19 | 195.jpg | 1 | 630, 1396, 839, 1567 | 0.539 | 新年度 | credit |
| 372 | v19 | 195.jpg | 2 | 669, 1678, 894, 1756 | 0.587 | これから | credit |
| 268 | v19 | 196.jpg | 3 | 57, 910, 715, 1066 | 0.399 | １１／１０日（月） | credit |
| 336 | v19 | 201.jpg | 0 | 439, 1601, 1066, 1862 | 0.510 | ２０２６年１月発売予定・ | caption |
| 223 | v19 | 203.jpg | 0 | 223, 1787, 1000, 1852 | 0.362 | 勤辺兜ツ汁２００時時２億２億３億３０分０歳前０７ | credit |
| 327 | v19 | 204.jpg | 0 | 250, 556, 410, 748 | 0.486 | ＤＩＧＩＴＡＬＳＮＥＢＡＲＩＭＰＣは | credit |
| 335 | v19 | 205.jpg | 0 | 946, 1551, 1107, 1685 | 0.503 | する | credit |
| 303 | v19 | 205.jpg | 1 | 943, 1687, 1114, 1763 | 0.446 | ＤＩＧＩＴＡＬＳＨＵＦＧＢＡＪＵＭＣＯＮＣ | credit |
| 358 | v19 | 206.jpg | 0 | 2, 98, 190, 135 | 0.527 | ＦＸＸＴＲＡＬＰＡＧＥＳ | credit |
| 295 | v19 | 206.jpg | 1 | 29, 344, 113, 417 | 0.432 | 「な | credit |
| 353 | v19 | 206.jpg | 2 | 37, 427, 110, 459 | 0.524 | ＵＲＭＰＣＯＭＯＳＰＬＵＳ | credit |
| 301 | v19 | 206.jpg | 3 | 749, 579, 1021, 684 | 0.445 | 最近、ミネラルや食物繊維は意識して実収するように | narration |
| 324 | v19 | 206.jpg | 4 | 753, 864, 872, 898 | 0.483 | 竹村洋平 | credit |
| 289 | v19 | 206.jpg | 5 | 748, 918, 1090, 1022 | 0.428 | 通りの支部だらは参考にするのに折り紙を見てきて実 | narration |
| 305 | v19 | 206.jpg | 7 | 730, 1507, 866, 1566 | 0.447 | ＣｏｎｅｒｄｅｓｓにてＩｎｔａｃｈｉｏｎｄｉｏｎ | credit |
| 332 | v19 | 207.jpg | 0 | 1028, 97, 1220, 137 | 0.497 | ＰＸＴＲＡ＿ＰＡＧＥＳ | credit |
| 368 | v19 | 207.jpg | 1 | 456, 383, 982, 448 | 0.552 | 魔都精兵のスレイ | credit |
| 296 | v19 | 207.jpg | 2 | 511, 732, 713, 909 | 0.433 | タガヒロ竹村洋平 | credit |
| 126 | v19 | 207.jpg | 3 | 582, 943, 623, 992 | 0.275 | １０ | credit |
| 292 | v19 | 207.jpg | 4 | 726, 1655, 1034, 1691 | 0.430 | ＪＵＭＰＣＯＭＩＣＳ－ | credit |
| 342 | v19 | 208.jpg | 0 | 2, 97, 191, 136 | 0.514 | ＦＸＸＴＲＡＢＡＧＥＳ | credit |
| 203 | v19 | 208.jpg | 1 | 176, 1625, 325, 1696 | 0.346 | ＵシブコミックスＧＯＷＩＯＳ | credit |
| 373 | v20 | cover_000.jpg | 0 | 972, 1049, 1048, 1094 | 0.607 | 原作 | credit |
| 315 | v20 | cover_000.jpg | 1 | 881, 1098, 1134, 1181 | 0.464 | タガヒロ | credit |
| 359 | v20 | cover_000.jpg | 2 | 970, 1183, 1045, 1229 | 0.532 | 漫画 | credit |
| 338 | v20 | cover_000.jpg | 3 | 849, 1237, 1172, 1318 | 0.511 | 竹村洋平 | credit |
| 306 | v20 | cover_000.jpg | 4 | 189, 1826, 420, 1868 | 0.447 | ＣＯＭＩＣＳ－ | credit |
| 369 | v20 | cover_000.jpg | 5 | 30, 1826, 170, 1868 | 0.557 | ＪＵＭＰ | credit |
| 320 | v20 | p_002.jpg | 0 | 206, 1817, 457, 1871 | 0.476 | ＣｏｍｌＣｓ－ | credit |
| 290 | v20 | p_002.jpg | 1 | 48, 1824, 187, 1871 | 0.429 | ＪＵＭＰ | credit |
| 264 | v20 | p_005.jpg | 0 | 1011, 680, 1105, 747 | 0.396 | ２０ | credit |
| 354 | v20 | p_005.jpg | 1 | 363, 641, 990, 786 | 0.524 | Ｃｏｎｄｅｒｌｓ | credit |
| 236 | v20 | p_167.jpg | 8 | 111, 1697, 170, 1728 | 0.375 | ．．．．．．．．．．．．．．．．．． | sign |
| 151 | v20 | p_193.jpg | 0 | 750, 1400, 778, 1427 | 0.293 | げ | credit |
| 274 | v20 | p_193.jpg | 1 | 878, 1431, 956, 1502 | 0.406 | ．．． | credit |
| 349 | v20 | p_193.jpg | 2 | 630, 1423, 838, 1545 | 0.520 | おにい | credit |
| 98 | v20 | p_193.jpg | 3 | 811, 1553, 836, 1568 | 0.256 | あ | not-text |
| 374 | v20 | p_193.jpg | 4 | 669, 1681, 892, 1756 | 0.614 | これは | credit |
| 135 | v20 | p_194.jpg | 0 | 622, 645, 651, 671 | 0.280 | ．．． | credit |
| 365 | v20 | p_194.jpg | 1 | 265, 645, 640, 855 | 0.540 | 魔都精兵の一人で、 | credit |
| 267 | v20 | p_194.jpg | 2 | 56, 911, 710, 1069 | 0.398 | １１／１７日（月）日土 | credit |
| 318 | v20 | p_199.jpg | 2 | 580, 1819, 913, 1859 | 0.475 | ☆２０３６年１月現在の情報です | caption |
| 232 | v20 | p_201.jpg | 0 | 225, 1787, 1000, 1851 | 0.373 | 劃ゾ兜ヅ汁邯股領領嶋僊峠鰐鰐碍践踞騰崩筋鯨材 | credit |
| 322 | v20 | p_202.jpg | 0 | 250, 557, 410, 748 | 0.482 | ＤＩＧＩＴＡＬＳＮＥＢＡＲＩＭＣＯＭに | credit |
| 347 | v20 | p_203.jpg | 0 | 946, 1551, 1102, 1685 | 0.518 | すぐ | credit |
| 309 | v20 | p_203.jpg | 1 | 944, 1687, 1113, 1763 | 0.449 | ＤＩＧＩＴＡＬＳＨＥＲＥＡＪＵＭＣＯＮＣＳ | credit |
| 362 | v20 | p_204.jpg | 0 | 2, 98, 192, 135 | 0.536 | ＦＸＴＲＡＥＡＧＥＳ | credit |
| 330 | v20 | p_204.jpg | 1 | 30, 344, 113, 420 | 0.490 | す | credit |
| 340 | v20 | p_204.jpg | 2 | 31, 428, 109, 459 | 0.513 | ｕｂＲＰＣＯＭＯＳＰＬＵＳ | credit |
| 200 | v20 | p_204.jpg | 6 | 730, 1506, 865, 1566 | 0.339 | ＣｏｎｅｒｄｅｒｓｅｒＣｈｉｎｄｅｒｄａｔａｋｓ | credit |
| 333 | v20 | p_205.jpg | 0 | 1029, 97, 1220, 136 | 0.497 | ＦＸＴＲＡ＿ＰＡＧＥＳ | credit |
| 302 | v20 | p_205.jpg | 2 | 728, 1654, 1048, 1692 | 0.445 | ＪＵＭＰＣＯＷＩＣＳＯ | credit |
| 343 | v20 | p_206.jpg | 0 | 2, 97, 192, 136 | 0.514 | ＦＸＴＲＡＰＡＧＥＳ | credit |
| 157 | v20 | p_206.jpg | 1 | 176, 1624, 323, 1696 | 0.300 | ＪジャＵブコミックスＣＯＭＩＣＳ | credit |
| 188 | v21 | cover_000.jpg | 0 | 846, 1556, 916, 1571 | 0.328 | ふーっ | credit |
| 281 | v21 | cover_000.jpg | 1 | 761, 1576, 1003, 1653 | 0.418 | タガヒロ | credit |
| 312 | v21 | cover_000.jpg | 2 | 724, 1658, 1041, 1799 | 0.451 | 竹村洋平 | credit |
| 280 | v21 | cover_000.jpg | 3 | 834, 1824, 1055, 1873 | 0.417 | ＣＯＭＩＣＳ－ | credit |
| 298 | v21 | cover_000.jpg | 4 | 695, 1825, 815, 1873 | 0.435 | ＪＵＭＰ | credit |
| 355 | v21 | p_002.jpg | 0 | 770, 1410, 1049, 1621 | 0.525 | タカヒロ竹村洋平 | credit |
| 317 | v21 | p_002.jpg | 1 | 851, 1820, 1103, 1886 | 0.472 | ｃｏｍｌｃｓｆｆ | credit |
| 297 | v21 | p_002.jpg | 2 | 694, 1824, 834, 1871 | 0.434 | ＪＵＭＰ | credit |
| 221 | v21 | p_005.jpg | 0 | 1011, 680, 1100, 748 | 0.360 | ２１ | credit |
| 345 | v21 | p_005.jpg | 1 | 363, 638, 990, 785 | 0.517 | ＣｏｐｌｅＴｏｉｔｓ | credit |
| 152 | v21 | p_195.jpg | 0 | 750, 1400, 778, 1427 | 0.293 | げ | credit |
| 275 | v21 | p_195.jpg | 1 | 878, 1431, 956, 1502 | 0.406 | ．．． | credit |
| 350 | v21 | p_195.jpg | 2 | 630, 1423, 838, 1545 | 0.520 | おにい | credit |
| 99 | v21 | p_195.jpg | 3 | 811, 1553, 836, 1568 | 0.256 | あ | not-text |
| 375 | v21 | p_195.jpg | 4 | 669, 1681, 892, 1756 | 0.614 | これは | credit |
| 269 | v21 | p_196.jpg | 1 | 57, 910, 711, 1067 | 0.400 | １１／１７日（月）日土 | credit |
| 234 | v21 | p_201.jpg | 0 | 246, 1787, 968, 1859 | 0.374 | 配信のキャラの経営者は保険の保険の価格の価格が高 | credit |
| 323 | v21 | p_202.jpg | 0 | 250, 557, 410, 748 | 0.482 | ＤＩＧＩＴＡＬＳＮＥＢＡＲＩＭＣＯＭに | credit |
| 348 | v21 | p_203.jpg | 0 | 946, 1551, 1102, 1685 | 0.518 | すぐ | credit |
| 310 | v21 | p_203.jpg | 1 | 944, 1687, 1113, 1763 | 0.449 | ＤＩＧＩＴＡＬＳＨＥＲＥＡＪＵＭＣＯＮＣＳ | credit |
| 363 | v21 | p_204.jpg | 0 | 2, 98, 192, 135 | 0.537 | ＦＸＴＲＡＥＡＧＥＳ | credit |
| 311 | v21 | p_204.jpg | 1 | 28, 344, 115, 416 | 0.449 | す | credit |
| 339 | v21 | p_204.jpg | 2 | 30, 427, 111, 459 | 0.512 | ＪＭＰＣＯＭＣＳＰＬＵＳ | credit |
| 255 | v21 | p_204.jpg | 5 | 749, 881, 1043, 1127 | 0.387 | 全世界８５「万人の人」世紀ファンの皆様本当にごめ | narration |
| 219 | v21 | p_204.jpg | 7 | 730, 1506, 868, 1566 | 0.359 | ＣｏｏｇｒｅＣｏｎｇｅｒＩｎｔａｃｋｉｏｔＳｈｉ | credit |
| 329 | v21 | p_205.jpg | 0 | 1029, 97, 1220, 136 | 0.488 | ＦＸＴＲＡ＿ＰＡＧＥＳ | credit |
| 357 | v21 | p_205.jpg | 1 | 456, 383, 974, 450 | 0.526 | 魔都精兵のスレイ | credit |
| 304 | v21 | p_205.jpg | 4 | 727, 1654, 1053, 1691 | 0.446 | ＪＵＭＰＣＯＷＩＣＳ－ | credit |
| 351 | v21 | p_206.jpg | 0 | 2, 97, 192, 135 | 0.521 | ＦＸＴＲＡＰＡＧＥＳ | credit |
| 190 | v21 | p_206.jpg | 1 | 177, 1624, 325, 1695 | 0.330 | ＰＵＷ | credit |

</details>

**Class 1 on the volumes was not read by a person** (5,316 regions); AC-3's
converse rests on the 22-page set above. See `## What was not checked`.

## Decided

*Revised 2026-11-05 after the five volumes were measured on the user's
instruction. The first version of this section, written on the 22-page set
alone, adopted `kind == "box" and confidence < 0.37` under R-2 and called it
thin; the volumes refute it, and the rule written before either measurement
(above, unchanged) now decides the other way.*

- **D-1** - **No automatic rule.** R-1 is not met: 17 of the 393 class-0
  regions examined are translatable text (10 dialogue on the English pages,
  4 narration, 2 captions and 1 sign on the Japanese volumes). R-2 is not met
  either: on the fields the store holds, no predicate separates every
  watermark from every translatable region - confidence overlaps (watermarks
  0.135-0.486, translatable Japanese class-0 text 0.358-0.510, translatable
  English 0.424-0.768) and so does box height (watermarks 19-56 px, the sign
  31 px, the January note 40 px); `source_ja` is OCR's reading of a
  watermark, which is not stable (`RawLazy.Com` read eight different ways
  in the first table alone). So MT-121 closes as a no-op citing this audit,
  and the user's own Remove action (MT-120) is how a watermark comes out.
  Rests on 1,043 pages in 11 chapters or volumes, 393 class-0 regions.
- **D-2** - Class 0 is **not** "scanlation watermark" on this detector: on
  the four clean volumes (`v18`-`v21`) it is entirely the book's own
  furniture - logos, credits, volume numbers, the afterword, the
  next-volume notice - and on English-lettered pages it is ordinary
  dialogue. Watermarks are class 0 when the scan carries them (`v17`, 222 of
  240), which is why the first, small sample looked like a watermark class.
  Rests on the volume totals table.
- **D-3** - A watermark is sometimes its own class-0 region (`v17`, both
  marks) and sometimes inside a dialogue region (`DL-Raw.Se` on `013.jpg`
  index 5 and `014.jpg` index 8, class 1); no rule over `kind` can remove
  the second kind, whatever MT-121 had decided.
- **D-4** - The superseded predicate `kind == "box" and confidence < 0.37`
  would, on the volumes, have **dropped** the author's afterword at 0.358
  and kept watermarks up to 0.486. It is recorded here so that no later
  story adopts it from this document's history.
- **D-5** - Class 1 is complete for dialogue and narration on the two
  Japanese chapters read by a person (53 of 53 class-1 regions
  translatable, none translatable seen outside a region); on the English
  pages 4 of 42 class-1 regions are not dialogue (3 not-text, 1 caption).
  The volumes' 5,316 class-1 regions were not read. Rests on the AC-3 table.

## What was not checked

- **The volumes' class-1 regions** (5,316) were not looked at by a person:
  AC-3's converse is the 22-page set's. A volume-scale check of class 1
  would need a sample design, not a crop-by-crop reading.
- The benchmark chapter (EPIC-07 O1) was not used; it is the user's to name.
- Watermarks from sites other than `RawLazy.Com` and `DL-Raw.Se`: none was
  seen.
- The two discrepancies under `## Measurement` (A-4's 4 boxes, the field
  note's ちゃぽ) were recorded, not explained.
- The human reading is one reader (the orchestrator) looking at crops; no
  second reader. The borderline labels most worth a second look: the
  `v20/p_167.jpg` index 8 placard (read as a sign, text illegible), the
  series-logo regions (read as credit, though a translator might render a
  title), and `v17/033.jpg` index 0 (watermark and scanlator handle in one
  region, read as credit).
- Page size is not a store field the rule could use, so a position
  predicate ("in the top 30 px") was not tried; it would also be one
  site's layout, not the detector's meaning.
