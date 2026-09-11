---
description: Work out what this project needs installed, write it down, and verify it
allowed-tools: Bash(bash scripts/doctor.sh:*), Bash(bash scripts/gates.sh:*), Bash(command -v:*), Bash(where:*), Bash(winget:*), Read, Write, Edit, Grep, Glob
---

Current machine check:
!`bash scripts/doctor.sh`

Extra context from the user: $ARGUMENTS

Your job is to get this machine from "cannot run the gates" to "runs the gates",
and to leave behind a document so nobody has to work it out again.

Run this after `/plan-product` has chosen a stack and before the bootstrap
story. It is safe to re-run at any time.

## 1. Work out what is needed

Read `docs/wiki/stack.md` for the chosen stack, and the matching profile in
`.claude/skills/stack-profiles/reference/`. Each profile has a Prerequisites
section listing the actual runtimes and tools, with install commands.

If the gate commands in `.claude/harness/project.conf` are not filled in yet,
take the profile's commands as the intended ones and say so.

## 2. Write `docs/wiki/environment.md`

One page, written for someone setting up this project on a fresh machine:

- **Required** — every runtime and tool, with the version the project expects
  and why it is needed (which gate or task uses it).
- **Install** — the actual commands, for the user's platform first. On Windows
  prefer `winget`, then `scoop`; on macOS `brew`; on Linux the distro package
  manager or the tool's official installer.
- **Verify** — the command that proves each one works, with the expected output
  shape.
- **Optional** — things only needed for optional gates (mutation testing,
  end-to-end browsers), clearly marked as skippable.
- **Notes** — anything platform-specific that will otherwise cost an hour:
  PATH quirks, the Windows Store Python alias, shells, container requirements.

Keep it to what this project actually uses. A generic install guide is worse
than none, because it will not be trusted.

**Every recorded workaround says what was measured and on what.** A workaround is
evidence, not a decision, and the difference is expensive. One line here read
"can fail once with `os error 4551` — retry before believing it". That was true
of a freshly built *test* binary, whose hash changes on every build; the day a
required gate was blocked it was the package's cached *build script*, which the
toolchain never rebuilds, so retrying could not possibly help. An orchestrator
retried six times on the strength of that sentence. Written as evidence —
"measured 2026-08-14 on a fresh test binary under Smart App Control; a rebuilt
binary got a new hash and passed" — it would have said, correctly, that it did not
apply. So: what you saw, on which machine and tool version, what you did, and
whether it worked. Not a rule.

## 3. Install

**Do not install anything yourself without asking.** Installing a runtime
changes the user's machine outside this repository. Instead:

- Tell the user exactly which commands to run, in a copy-pasteable block, and
  why each is needed.
- If they ask you to run them, run them one at a time and show the output.
- Where a tool has a scoped, project-local alternative to a global install, say
  so and recommend it.

## 4. Verify

Run `bash scripts/doctor.sh` again. Every executable a gate or task names must
be found. Then run `bash scripts/gates.sh --list` and confirm the commands
match what `stack.md` says.

Report: what was already present, what the user still needs to install, the
exact commands, and whether the bootstrap story can now start.
