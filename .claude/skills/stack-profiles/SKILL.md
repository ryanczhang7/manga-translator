---
name: stack-profiles
description: Canonical gate commands, test layout and conventions for the ecosystems this harness knows - Python, TypeScript/Node, Rust, Godot and static web - plus how to write a profile for a stack it does not. Use when choosing a stack during planning, writing the bootstrap story, or filling in project.conf.
---

# Stack profiles

The harness is stack-agnostic by design: nothing in it assumes a language. A
profile is the bridge - it says, for one ecosystem, what the standard gate
commands are, where tests live, and what the bootstrap story must produce.

## Available profiles

| Profile | For | File |
|---|---|---|
| `python-uv` | Python services, CLIs, data work | `reference/python-uv.md` |
| `python-uv-pyside6` | Windows desktop Python + Qt GUI + local ONNX inference (addendum to `python-uv`) | `reference/python-uv-pyside6.md` |
| `node-typescript` | React, Node APIs, anything on pnpm | `reference/node-typescript.md` |
| `rust-cargo` | Rust binaries, libraries, WASM | `reference/rust-cargo.md` |
| `godot` | 2D/3D games and interactive tools in Godot 4 | `reference/godot.md` |
| `web-static` | No-build or minimal-build browser projects | `reference/web-static.md` |

`reference/environments.md` covers where dependencies actually live, why
gate commands must be environment-aware, the `vendor` path category, and why
this harness is not built around Docker.

If none fits, `reference/new-profile.md` says what a profile must contain and
how to verify it before the bootstrap story depends on it.

## How to use one

1. During `/plan-product`, pick the profile that matches the stack the brief
   actually calls for. Record the choice and the pinned versions in
   `docs/wiki/stack.md`.
2. Copy its gate commands, `evidence` lines and `slow` lines into
   `.claude/harness/project.conf`, adjusting `cwd` for the layout you chose.
3. Copy its test and config globs into `.claude/harness/paths.conf` so the phase
   lock classifies this stack's files correctly.
4. Run `/setup-environment`, which turns the profile's Prerequisites section
   into `docs/wiki/environment.md` and verifies the toolchain with
   `bash scripts/doctor.sh`.
5. Have the bootstrap story prove each command actually runs. A profile is a
   starting point, not a guarantee - versions move.
6. Once CI has run the gates for real, measure the per-test CI/local factor
   from its log and record it as a `ci-factor` line in `project.conf`. No
   profile can carry that number - it is a property of the runner, not of the
   stack - and the ratio everyone derives instead, from the gate's own wall
   time, overestimates it several-fold. See the `quality-gates` skill.

## Choosing

Choose for the constraints in the brief, not for familiarity. Say why in
`stack.md`, in one sentence per choice, tied to a constraint. Where two options
are close, prefer the one whose test story is stronger: this harness's whole
value depends on a test runner that is fast, deterministic and scriptable.

Mixed-stack projects are normal - a Godot client with a Python service is two
profiles, two sets of gates with distinct ids, and one `paths.conf`.
