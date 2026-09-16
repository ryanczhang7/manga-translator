# `fixtures/detect/` — synthetic detector fixtures

Every file here is a **declarative spec**, not a rendered array: a page size, a
background probability, a list of rectangles painted in order, a list of
accepted boxes, and — where the fixture has any — the annotated SFX rectangles.
`tests/core/test_detect_postprocess.py` renders a spec into the
`(H, W) float32` probability map and the `(N, 6)` box array that
`mangatl.detect.postprocess.regions_from_detection` takes.

**Provenance.** Authored by hand by the Test Developer (`claude-opus-5`) for
MT-007 RED on 2026-09-15. Nothing here is derived from a scan: MT-007 C-9 / PO-2
settled that the only pages carrying real art-integrated SFX are
non-redistributable scanlation scans, which `paths.conf` classifies as `test`
and which would therefore be committed to every clone and every CI runner. The
real pages stay gitignored under `spikes/**` and are read only by
`tests/integration/`, which never runs on CI.

Declarative rather than binary on purpose: a `.npy` blob is unreviewable, and a
fixture quietly adjusted to make a test pass is the same move as editing a test.
`fixtures/**` classifies as `test`, so GREEN cannot touch these files.

## The spec format

| Key | Meaning |
|---|---|
| `page_size` | `[width, height]` in page pixels |
| `background` | the probability every pixel starts at |
| `paint` | rectangles painted **in order** over the background; later ones win |
| `boxes` | accepted boxes: `rect`, `conf`, `cls` — one row of the `(N, 6)` array each |
| `sfx_rects` | annotated art-integrated SFX areas; no region may touch one (AC-6) |
| `control_boxes` | boxes a *control* adds to `boxes` to prove the assertion can fail |

Every `rect` is `[x0, y0, x1, y1]` in page pixels and is **half-open**: it
covers `x0 <= x < x1` and `y0 <= y < y1`, so its area is exactly
`(x1 - x0) * (y1 - y0)`. The same convention governs box membership in
`postprocess` (MT-007 amendment A-6).

## What each fixture is for

| Fixture | Pins |
|---|---|
| `clean-bubbles.json` | AC-1: one region per component inside an accepted box, polygon + page-sized 1-bit mask, emission order, mean-not-max confidence |
| `sfx.json` | AC-6: no region touches an annotated SFX rectangle at any swept threshold or dilation — and the control that makes that falsifiable |
| `overlapping-bubbles.json` | AC-3: two components with overlapping bounding boxes and disjoint pixels |
| `single-kana.json` | AC-2 / C-6: the 252 px kana that must survive and the 4 px speckle that must not |
| `page-edge.json` | AC-4: blobs flush with the page boundary |
