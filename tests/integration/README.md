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
recorded as a `waiver` in `.claude/harness/project.conf`; **MT-002 writes the
first test here and the waiver comes out then.**
