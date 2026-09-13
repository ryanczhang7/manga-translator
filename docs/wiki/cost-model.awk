# Chapter API cost model — the arithmetic behind stack.md §5 (O4).
#
#   awk -f docs/wiki/cost-model.awk
#
# UNVERIFIED. Every token figure here is an estimate; only the published rates
# and the image-token rule are external facts. MT-009 replaces the token
# estimates with measured `response.usage` values and MT-010 enforces a ceiling
# so that a wrong estimate is safe rather than expensive.
#
# Image tokens follow Claude's documented rule: tokens ~= (width * height) / 750,
# with the long edge capped at 1568 px before upload.
#   1098 x 1568  ->  2296 tokens   (a page capped at 1568 on the long edge)
#   2048 x 2896  ->  7908 tokens   (a typical raw scan)
#   2400 x 3400  -> 10880 tokens   (a large raw scan)

function chapter(img, ocr, roll, prefix, visible, thinking, rin, rout, rcw, rcr,
                 uncached, cachewrite, cacheread, out) {
  uncached   = PAGES * (img + ocr + roll) * rin  / 1000000
  cachewrite = prefix * rcw / 1000000
  cacheread  = (PAGES - 1) * prefix * rcr / 1000000
  out        = PAGES * (visible + thinking) * rout / 1000000
  return uncached + cachewrite + cacheread + out
}

BEGIN {
  PAGES = 20
  CEILING = 2.00

  # Published rates, $ per million tokens.
  O_IN = 5;  O_OUT = 25; O_CW = 6.25; O_CR = 0.50   # claude-opus-5
  S_IN = 2;  S_OUT = 10; S_CW = 2.50; S_CR = 0.20   # claude-sonnet-5

  # Per-page token estimates for the chosen design (A).
  IMG_CAPPED = 2296   # page image, long edge capped at 1568 px
  IMG_RAW    = 7908   # 2048 x 2896 raw scan
  IMG_BIG    = 10880  # 2400 x 3400 raw scan
  OCR_JA     = 500    # manga-ocr output, ~20 regions
  ROLLING    = 900    # previous page's English + running glossary
  PREFIX     = 1500   # system prompt + lettering style guide (cached)
  VISIBLE    = 700    # JSON of ~20 translated lines
  THINKING   = 800    # adaptive thinking; THE UNMEASURED INPUT

  a = chapter(IMG_CAPPED, OCR_JA, ROLLING, PREFIX, VISIBLE, THINKING, O_IN, O_OUT, O_CW, O_CR)

  printf "%-52s %8s  %s\n", "design", "$/chapter", "verdict"
  row("A   opus-5,  local OCR, image capped 1568px", a)
  row("A+  ... plus 20% of pages re-run after edits", a * 1.2)
  row("A-  sonnet-5, same call shape",
      chapter(IMG_CAPPED, OCR_JA, ROLLING, PREFIX, VISIBLE, THINKING, S_IN, S_OUT, S_CW, S_CR))
  row("B   opus-5, LLM does OCR, 2048x2896 image",
      chapter(IMG_RAW, 0, ROLLING, PREFIX, VISIBLE, THINKING, O_IN, O_OUT, O_CW, O_CR))
  row("C   opus-5, LLM does OCR, 2400x3400 image",
      chapter(IMG_BIG, 0, ROLLING, PREFIX, VISIBLE, THINKING, O_IN, O_OUT, O_CW, O_CR))
  row("D   opus-5, design A but two passes per page", a * 2)

  printf "\nSensitivity: adaptive thinking is the one unmeasured input.\n"
  for (t = 400; t <= 3200; t = t * 2) {
    printf "  design A with %5d thinking tokens/page: $%.2f%s\n", t,
      chapter(IMG_CAPPED, OCR_JA, ROLLING, PREFIX, VISIBLE, t, O_IN, O_OUT, O_CW, O_CR),
      (chapter(IMG_CAPPED, OCR_JA, ROLLING, PREFIX, VISIBLE, t, O_IN, O_OUT, O_CW, O_CR) > CEILING ? "  OVER" : "")
  }
}

function row(label, cost) {
  printf "%-52s %8.2f  %s\n", label, cost, (cost > CEILING ? "OVER CEILING" : "ok")
}
