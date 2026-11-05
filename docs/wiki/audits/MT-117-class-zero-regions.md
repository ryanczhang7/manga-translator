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

## Decided

- **D-1** - R-1 is **not** met: 10 of the 16 class-0 regions examined, on 4
  of the 6 chapters, are dialogue. R-2 applies, and the narrower predicate
  **`kind == "box" and confidence < 0.37`** separates every watermark seen
  from every translatable region seen: watermarks span confidence
  0.247-0.316, translatable class-0 regions 0.424-0.768, and 0.37 sits
  0.054 from each side (a margin of 0.108 between the two sets). Rests on
  the 16 class-0 rows above; 22 pages, 6 chapters.
- **D-2** - D-1 is **thin**, and MT-121's story records it as such rather
  than inheriting confidence from this document: the 4 watermarks are one
  site's mark (`RawLazy.Com`) on two Japanese chapters, and all 10
  translatable class-0 regions are on English-lettered pages, which are
  not the product's input. On Japanese raws alone, 4 class-0 regions were
  found, all watermarks - fewer than R-1's 10, so that sub-population is
  under-powered (R-3's reading). Rests on the per-chapter totals table.
- **D-3** - The `DL-Raw.Se` watermark is never a region of its own on these
  pages; it is inside dialogue regions. No predicate over `kind` can remove
  it, and MT-121 does not claim to. Rests on `013.jpg` index 5 and
  `014.jpg` index 8.
- **D-4** - A class-0 credit (the scanlator's "next chapter" notice,
  confidence 0.518 and 0.531) is **kept** by D-1's predicate: it is not
  translatable text, but excluding it is not what the rule is for, and a
  threshold low enough to drop it would drop dialogue at 0.426. Rests on
  `0136-020.png` index 5 and `0137-022.png` index 1.
- **D-5** - Class 1 is complete for dialogue and narration on both Japanese
  chapters (53 of 53 class-1 regions translatable, and no translatable text
  seen outside a region); on the English pages 4 of 42 class-1 regions are
  not dialogue (3 not-text, 1 caption). Rests on the AC-3 table.

## What was not checked

- The full volumes on this machine, `matoseiheino_v17` to `v21` (about 200
  pages each, about 1,000 in all), were not run: the user had not named
  them for this spike (story PO-4). Running the script over them is the
  cheapest way to thicken D-2, and needs no API spend.
- The benchmark chapter (EPIC-07 O1) was not used; it is the user's to name.
- Watermarks from any site other than `RawLazy.Com` as their own class-0
  region: none was seen, so D-1's threshold says nothing about them.
- Whether class 0 behaves on Japanese raws as it does on English pages: the
  dialogue-in-class-0 finding is entirely English-lettered pages, and no
  Japanese-raw dialogue region came out class 0 here.
- The two discrepancies under `## Measurement` (A-4's 4 boxes, the field
  note's ちゃぽ) were recorded, not explained.
- The human reading is one reader (the orchestrator) looking at crops; no
  second reader.
