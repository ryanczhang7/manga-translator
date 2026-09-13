---
id: EPIC-01
title: Foundations — a real toolchain, real gates, and a model runtime we trust
status: todo
stories: [MT-001, MT-002, MT-003, MT-031, MT-032]
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

## Note on the last done-when clause — confirmed by the user 2026-09-12

*"`docs/wiki/stack.md` has been corrected against what actually installed and
ran"* is satisfied by **MT-001 plus MT-002**, on a qualified reading the user
approved before MT-002 reached REVIEW (MT-002 `## Notes`, PO-2).

MT-001 corrected §3 *Runtime and packaging* and *Development tooling* against
`uv.lock` — those rows are **locked**. MT-002 corrected §3 *Local inference* and
*Models* against a real install and three real forward passes, but in an
isolated, gitignored environment at `spikes/MT-002/.venv`, because MT-002 PO-1
keeps the inference dependency out of `pyproject.toml` and `uv.lock` until
MT-007 — the first story that imports it. Those rows are therefore **measured in
a spike, not locked**, and §3 names them as a distinct third state rather than
folding them into the locked tables.

That distinction is deliberate: §3's opening line is *"Two kinds of row live in
this section and they are not equally true"*, and collapsing a spike measurement
into a locked fact is precisely what that sentence exists to prevent.

*Cloud translation* in §3 remains unverified and is out of this epic; it arrives
with the story that first calls the API.

**So EPIC-01 closes after MT-003**, with no clause outstanding.
