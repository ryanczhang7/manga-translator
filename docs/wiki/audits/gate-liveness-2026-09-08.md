# Audit: gates could pass while testing nothing

**Date:** 2026-09-08
**Scope:** `scripts/gates.sh`, `project.conf`, every stack profile
**Origin:** `fantasy-world-builder` WORLD-001, the first real project on this
harness. Reported as a proposal; this file records what was found and what was
decided, and supersedes that proposal.

## What was found

A required `unit` gate configured as `cargo test` ran for one second, printed
`running 0 tests`, exited 0, and was recorded as `PASS`. `src-tauri/` was a
Cargo workspace whose root is also a package; in that layout `cargo test` builds
and tests only the root package and silently skips every member. The skipped
crate was the project's world-file container.

The harness reported `PASS` truthfully. `gates.sh` had no way to distinguish a
gate that ran the work and succeeded from a gate that ran no work at all — both
exit 0. Sixty-two further stories would have been built on it.

Two aggravating findings:

- **The bad command was ours.** `stack-profiles/reference/rust-cargo.md` shipped
  `cargo test` while, in the same file, recommending the workspace layout that
  makes it vacuous. It was not a downstream typo.
- **The gates were exempt from the harness's own central rule.** Law 1 says no
  production code without a failing test that demanded it, and `rules.md` says a
  test never observed to fail is not a test. Sixteen gates were written and not
  one had been observed failing before being trusted.

The class is general, and which tools are honest is not guessable. `pytest`,
`vitest`, `tsc` and `playwright` all fail loudly with nothing to do;
`cargo test` at a workspace root, `mypy` over an empty target, `biome lint` at a
sourceless directory, a coverage threshold on a glob matching no files, and
anything carrying `--passWithNoTests` all pass silently. The table lives in the
`quality-gates` skill.

## What shipped

1. **`evidence` lines in `project.conf`.** After a gate exits 0, its captured
   output must match its regex or it fails with *ran but produced no evidence of
   work*, at the gate's own severity. Asserts volume of work, never success —
   success remains the exit code's job. A gate with no `evidence` line behaves
   exactly as before, so this is safe to adopt late; once `BOOTSTRAPPED=yes` a
   required gate without one is warned about. A new `kind`, so old and new
   `gates.sh` and `project.conf` interoperate in both directions.
2. **`gates.sh --audit`.** Checks the manifest without running it: missing
   commands, missing evidence lines, non-existent `cwd`. Wired into CI.
3. **Gate-probe doctrine.** Law 3 in `CLAUDE.md` now ends: a gate that has never
   been observed to fail is not a gate. Stories that add or change a gate record
   the induced failure in `## Gate probes`, owned by the Feature Developer.
4. **Profiles carry evidence lines**, and `rust-cargo.md` now uses `--workspace`
   throughout, with the trap documented.
5. **`stack.md` declares its own epistemic status.** `/plan-product` now writes
   an "Unverified — nothing in this file has been executed" header. That
   convention caught six wrong commands in WORLD-001 and had been invented ad
   hoc there; it was never part of the harness.

## Decisions worth not relitigating

- **`evidence`, not `expect`.** The proposal's name invites the success
  assertions its own semantics rule forbids.
- **`evidence | <id> | -` is a deliberate opt-out.** Without an honest escape
  for tools that print nothing countable, the pressure lands on deleting the
  line instead.
- **`--audit` inside `gates.sh`, not a `verify-bootstrap.sh`.** A separate
  script would have duplicated the parser to check the same file.
- **Evidence lives in `project.conf`, with profiles as the source.** Same split
  as the gate commands, for the same reason: by bootstrap time a project's
  command has usually diverged from the profile's (`cwd`, workspace flags,
  filters), so a centrally-fixed regex would land on a command it no longer
  describes. The propagation that matters is the reverse — a project finding a
  regex wrong should fix the profile.
- **Compiler regexes are weak on purpose.** `cargo check`, `clippy` and `build`
  print a per-crate line cold and only `Finished` warm, so a "N units" regex
  fails spuriously on a second run. Test runners re-execute every time and are
  the strong case. Verify any new evidence line by running the gate twice.

## Still open

Python, Godot and `cargo-llvm-cov` evidence regexes are marked `# UNVERIFIED` in
their profiles — those toolchains were not installed when this was written. The
first bootstrap story on each of those stacks must run them and correct them.
