---
id: EPIC-01
title: Foundations — a real toolchain, real gates, and a model runtime we trust
status: todo
stories: [MT-001, MT-002, MT-003]
---

## Goal

The repository becomes the stack `docs/wiki/stack.md` describes: a Python 3.12
project managed by `uv`, with a PySide6 entry point, a test runner that
discovers real tests, and eight gate commands that have each been watched to
fail. And the single largest technical unknown in the plan — whether the three
local models run on this machine as ONNX — is settled before anything depends
on it.

## Why now

Everything depends on it. A bootstrap story that lands with a wrong test command
poisons every story after it, because the next agent trusts `project.conf`
without re-deriving it. And MT-002's answer changes a dependency in
`pyproject.toml` (ONNX Runtime versus PyTorch + CUDA 12.8) and the size of the
shipped installer, so it must land before the first detection story, not after.

## Done when

`bash scripts/gates.sh` runs every gate against a walking skeleton and passes;
`bash scripts/gates.sh --audit` is clean; `bash scripts/task.sh dev` opens an
empty Qt window; each required gate has a pasted failure in a story's
`## Gate probes`; and `docs/wiki/stack.md` has been corrected against what
actually installed and ran.

## Stories

- **MT-001** — bootstrap: the toolchain, the layout, and every gate observed
  failing.
- **MT-002** — spike: do usable ONNX exports of the detector, `manga-ocr` and
  LaMa exist and run on an RTX 5070 under `onnxruntime-gpu`? Output is a
  decision document, not code.
- **MT-003** — chore: the five `import-linter` contracts from
  `architecture.md` §3, each probed in both absolute and relative import form.

## Deliberately not in this epic

No product behaviour whatsoever. No detection, no OCR, no API client, no
review screen. The bootstrap story's sizing rule is explicit: anything
project-specific gets its own RED→GREEN story afterwards. MT-003 is here rather
than in bootstrap because the contracts need a package layout to point at, and
because a gate deserves its own probes rather than being the tenth item on a
scaffold list.
