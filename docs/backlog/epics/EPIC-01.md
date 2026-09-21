---
id: EPIC-01
title: Foundations — a real toolchain, real gates, and a model runtime we trust
status: in-progress
stories: [MT-001, MT-002, MT-003, MT-031, MT-032, MT-033, MT-034, MT-037, MT-039, MT-040, MT-041, MT-042, MT-043]
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
- **MT-031** — chore: the phase guard's command extractors read prose as paths
  and, worse, miss a real operand behind a trailing redirect or a capture group.
- **MT-032** — chore: harness state survives two things running in one working
  tree.
- **MT-033** — chore: `mv` removes its source operand and the guard never judges
  it, so a frozen file can leave its path; `git mv` is unrecognised entirely.
- **MT-034** — chore: a bare directory name classifies `source`, so `cp x docs/`
  is refused in a phase that permits `docs`, and `cp x tests/` is permitted in
  GREEN, which freezes tests.
- **MT-037** — fix: a gate that skipped its work stops reporting PASS.
- **MT-039** — chore: the harness self-test refuses to shrink — per-suite
  assertion floors, so that MT-040, MT-041 and MT-042 cannot be satisfied by
  running less of it.
- **MT-040** — chore: parsing the gate manifest spawns no process per field —
  1,669 external processes for `gates.sh --list`, of which 1,461 are one
  `trim()`.
- **MT-041** — chore: one phase-guard invocation costs half the processes — 44
  spawns per invocation, driven 307 times by one suite.
- **MT-042** — chore: the harness self-test runs its suites concurrently.
  Carries a re-measure gate and may correctly be closed unstarted.
- **MT-043** — fix: `gates.sh --audit` says "1 required gate(s) have no
  evidence line" when the one gate without an evidence line is `mutation`,
  which is optional — and the count that would report a *genuinely* required
  gate losing its line is therefore already non-zero.

**MT-031, MT-032, MT-033, MT-034, MT-037, MT-039, MT-040, MT-041, MT-042 and
MT-043 are not clauses of `## Done when`.** They were filed into this epic after
MT-003 closed it, because MT-001 built the machinery they correct and this is
the toolchain epic. The done-when above was discharged by MT-001, MT-002 and
MT-003 and is not reopened by any of them — see the notes at the end of this
file.

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

**Marked `done` on 2026-09-18, with MT-037.** The done-when above closed after
MT-003 and was never reopened; what kept this epic open was its five later
corrections to the machinery MT-001 built — MT-031 to MT-034, and MT-037, which
removed the last way a gate in this repository could report PASS having done
nothing. At that point all eight stories were DONE and no clause was
outstanding.

## Reopened on 2026-09-20 — `status: done` → `status: in-progress`

**What changed:** four stories were added to this epic at the user's direction
— **MT-039, MT-040, MT-041, MT-042** — all of them corrections to the cost of
the machinery MT-001 built. They came out of a measurement taken at REVIEW by
two consecutive stories: CI's `gates` job spends 63% of its wall-clock in the
harness self-test and 25% in the gates that judge the product, and both figures
moved the same way between MT-011 (PR #25) and MT-012 (PR #26).

**Why the `status:` field moved, and why that is the honest answer rather than
a bookkeeping nicety.** `status: done` on an epic is a claim about its
`## Stories` list. With four stories in that list at `PLANNED`, the claim is
false, and the closing note above said in terms *"All eight stories are DONE
and no clause is outstanding"* — a sentence that stops being true the moment a
ninth is added. Nothing in the harness reads an epic's `status`
(`bash scripts/phase.sh board` shows story status, not epic status; no script
parses `docs/backlog/epics/**`), so this is a documentation-honesty call and
not a mechanical one. It is made rather than skipped precisely because nothing
enforces it: the epic is read by people and by agents with empty context, and a
`done` epic containing four undone stories teaches both that the field means
nothing.

**What has NOT changed, and is not reopened by any of the four:** every clause
of `## Done when` above remains **discharged**, exactly as the note on the last
clause records. `bash scripts/gates.sh` still runs every gate against the
walking skeleton and passes; `--audit` is still clean; `bash scripts/task.sh
dev` still opens a Qt window; each required gate still has a pasted failure in
a story's `## Gate probes`; and `docs/wiki/stack.md`'s correction still stands
on MT-001 plus MT-002, on the qualified reading the user approved on 2026-09-12
— including the distinction between rows **locked** against `uv.lock` and rows
**measured in a spike**, which §3 keeps as a separate third state. None of
MT-039 to MT-042 touches any of that: they change how fast the harness runs,
never what it decides. MT-040 and MT-041 are both held to byte-identical output
and unchanged verdicts as acceptance criteria.

**What closes this epic again:** MT-039, MT-040 and MT-041 DONE, and MT-042
either DONE or closed unstarted on its own re-measure gate (MT-042 DV-0, which
may correctly conclude the work is not worth building once MT-040 and MT-041
have landed). No new `## Done when` clause is added, for the same reason none
was added for MT-031 to MT-034 and MT-037.
**Amended 2026-09-21:** and **MT-043** DONE. See the note below.

## MT-043 added on 2026-09-21 — and what it does and does not touch

**What changed:** one story was added at the orchestrator's direction, out of a
defect found and reproduced while closing MT-039 — **MT-043**, a `fix`. It is
the tenth correction to the machinery MT-001 built and the second `fix` in this
epic after MT-037. `status:` stays `in-progress`; it was already, and the
sentence above about a `done` epic containing undone stories applies unchanged.
**What closes the epic is now the list above plus MT-043.**

**The one `## Done when` clause it brushes against, stated plainly rather than
glossed.** That list contains *"`bash scripts/gates.sh --audit` is clean"*. It
still is, on the reading that clause was written under and that MT-001 and
MT-003 discharged it under: `--audit` exits 0 and prints `Manifest audit
passed.`, with no manifest problem, today. **That clause is not reopened.**

What MT-043 corrects is a *false sentence inside output that passes*. `--audit`
also prints `1 required gate(s) have no evidence line`, and the one gate without
one is `mutation`, which is `optional`; all six required gates have an evidence
line. The audit's verdict is right and its prose is wrong. That is a defect in
the machinery, not an outstanding clause of this epic's goal — the same
distinction MT-037 turned on, where a gate reporting `PASS` having run one of
twenty-six tests was a defect in the gate rather than a reopening of *"each
required gate has a pasted failure in a story's `## Gate probes`"*.

**Ordering.** MT-043 should land **before MT-040**, which is held to
byte-identical output as an acceptance criterion and would otherwise record a
baseline that MT-043 then invalidates. MT-043 `## Notes` PO-5 has the reasoning
and notes that the ordering is stated, not enforced — enforcing it would mean
adding `MT-043` to MT-040's `depends_on`, which the Lead PO left as a decision
for the orchestrator rather than taking unasked.
