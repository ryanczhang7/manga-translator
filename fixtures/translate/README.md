# `fixtures/translate/` — recorded structured-output response bodies

Each file is the **raw JSON body** that `output_config.format` puts in the
response's first `text` content block (MT-011 C-5, and the Anthropic API
reference: *"`output_config.format` guarantees the first block is text with
valid JSON"*). It is **not** a serialised `Message`: the envelope — the content
blocks, the `thinking` block adaptive thinking may put in front of the text
block, the `usage` object — is built in `tests/core/conftest.py`'s
`fake_message` builder, so that the one thing a fixture has to be exact about
stays visible here.

`tests/core/test_translate_parse.py` reads these with `read_text()` and never
with `json.load()`, because **key order is load-bearing** and re-serialising
would destroy it. See below.

**Provenance.** Authored by hand by the Test Developer (`claude-opus-5`) for
MT-011 RED on 2026-09-18. Nothing here came off the wire: MT-011 PO-1 records
that this machine has no `ANTHROPIC_API_KEY`, and no test in MT-011 makes a
network call. The live measurement is MT-037.

## The page these fixtures are about

Four regions in reading order. The Japanese is what OCR read; the English is
what a well-behaved model proposes.

| reading index | `source_ja` | proposed English |
|---|---|---|
| 0 | 醜鬼が人間の言う通りに動いたりね | `As if a demon would move at a human's say-so.` |
| 1 | ……なるほど | `...I see.` |
| 2 | どうして君がここに | `Why are you here?` |
| 3 | 行くぞ | `Let's go.` |

## Why the key order is deliberately wrong

**`well-formed.json` carries its keys in the order `2, 0, 3, 1`.** That is the
whole point of the fixture, and MT-011's falsifiable success condition 1.

A parser that assigns lines **by position in the response** rather than by
region index is a plausible, entirely silent corruption — it puts the right
words on the wrong bubbles, which is exactly the failure `stack.md` §5/O2's
"rotate the proposed lines by one region" control exists to catch further
downstream. A fixture whose key order happened to match region order **cannot**
catch it: `dict(zip(region_indices, parsed.values()))` and
`{int(k): v for k, v in parsed.items()}` would agree on every region.

Measured with the standard library on 2026-09-18, outside pytest:

| Fixture | key order | regions where index-based differs from position-based |
|---|---|---|
| `well-formed.json` | `["2", "0", "3", "1"]` | **4 of 4** |
| `omits-region-3.json` | `["1", "0", "2"]` | **2 of 3** |

`tests/core/test_translate_fixtures.py` asserts both numbers and imports
nothing from `mangatl`, so it is the one part of this story's suite that runs —
and can be watched — while `mangatl.translate` does not yet exist.

## The files

| File | What it is | Criterion |
|---|---|---|
| `well-formed.json` | every region named, keys out of order | AC-4 |
| `omits-region-3.json` | region 3 absent; the others named, out of order | AC-5 |
| `unknown-region-index.json` | names region `7`, which this page does not have | AC-6 |
| `non-integer-key.json` | names a key `"first"` that is not an integer at all | C-4 |

`fixtures/**` classifies as `test` in `.claude/harness/paths.conf`, so GREEN
cannot touch these files — a fixture quietly adjusted to make a test pass is the
same move as editing a test.
