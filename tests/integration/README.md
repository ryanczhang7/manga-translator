# `tests/integration/`

Everything here is marked `gpu`, `network`, or both, and **never runs on CI**.
The `integration` gate is `optional` for exactly that reason.

This directory is empty at MT-001. It is created here rather than by the first
story that needs it because `docs/wiki/stack.md` §4 makes the adapter split
load-bearing: each of `detect`, `ocr` and `clean` is *logic* tested in
`tests/core/` against a fake inference session, and a *session* smoke-tested
here against a real `.onnx`. A story that finds no `tests/integration/` will put
its smoke test in `tests/core/` and the fake will quietly become the only thing
anyone tests.

While it is empty the `integration` gate collects nothing and exits 5. That is
recorded as a `waiver` in `.claude/harness/project.conf`; **MT-007 writes the
first test here and the waiver comes out then.**

**Corrected by MT-002 (PO-1).** MT-001 wrote MT-002 here, and MT-002 turned out
to be the wrong story: it is `type: spike`, its output is
`docs/wiki/audits/MT-002-model-runtime.md`, and `phases.conf` gives a spike only
PLANNED → REVIEW → DONE — none of which permits a write to a `test` path, so it
could not have written this directory without routing around the phase lock.
MT-007 is the story that fits: it `depends_on: [MT-002]`, carries
`required_gates: [integration]`, and its AC-7 is *"Given the real detector model
and a real page fixture, when the session loads and runs…"*. MT-002's `## Notes`
carries the full decision.
