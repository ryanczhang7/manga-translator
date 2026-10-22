# Profile: rust-cargo

Rust with cargo. Suits binaries, libraries, simulation cores and WASM modules
that a JavaScript or Godot front end drives.

## Gate commands for project.conf

    gate | format    | optional | . | cargo fmt --all --check
    gate | lint      | required | . | cargo clippy --workspace --all-targets -- -D warnings
    gate | typecheck | required | . | cargo check --workspace --all-targets
    gate | unit      | required | . | cargo test --workspace --no-fail-fast
    gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 100
    gate | build     | required | . | cargo build --release --workspace
    gate | mutation  | optional | . | cargo mutants
    ondemand | mutation | cargo mutants re-runs the suite once per mutant; run it with /audit-mutations, not per story
    # Combining this with another profile's `mutation` gate: see the stack-profiles skill, *Choosing*.

    task | install | - | . | cargo fetch
    task | dev     | - | . | cargo run
    task | test    | - | . | cargo test --workspace

`cargo check` and `clippy` overlap; keeping both is cheap and the failure
messages differ usefully.

**`--workspace` on every command is not optional.** In a workspace whose root is
also a package - the shape `cargo new` plus a `crates/` directory produces, and
the shape Tauri produces - a bare `cargo test` builds and tests *only the root
package* and silently skips every member. It exits 0 having run nothing. This
profile recommends exactly that layout below, so the flag and the layout have to
be adopted together.

**`--no-fail-fast` on the test gates.** By default cargo stops at the first
test *binary* with a failing test and never runs the rest, so a change that
breaks five suites reports one, and the other four surface one re-run at a
time. `--no-fail-fast` runs them all and still exits non-zero, so the gate
still fails. On a passing run it changes nothing in the output, so evidence
lines and floors read the same numbers. Found on a consuming project's
unit gate, then its coverage gate. `cargo llvm-cov` also offers
`--ignore-run-fail`, which runs every test too but **exits 0** when tests
fail and the report succeeds. On a required gate that is a failing test
graded as a pass: never use it there.

## Evidence of work

See the `evidence` format in `project.conf`; these assert that the tool did
work, not that it succeeded.

    evidence | unit     | test result: ok\. [1-9]
    evidence | lint     | Finished .* profile
    evidence | typecheck| Finished .* profile
    evidence | build    | Finished .* profile

    no-count | lint     | `Finished .* profile` is liveness-only; the digits after it are elapsed seconds
    no-count | typecheck| `Finished .* profile` is liveness-only; the digits after it are elapsed seconds
    no-count | build    | `Finished .* profile` is liveness-only; the digits after it are elapsed seconds

    # UNVERIFIED - cargo-llvm-cov was not installed when this was written.
    # The bootstrap story must run the coverage gate and correct this line.
    evidence | coverage | TOTAL

    # cargo-mutants prints one summary line, `N mutants tested in T: ...`,
    # listing only the non-zero outcomes. A run that killed nothing has no
    # `caught` in it at all, so there is nothing for this to match.
    evidence | mutation | [1-9][0-9]* caught

All but the coverage line were run against cargo 1.98 on Windows. The mutation
line was checked against cargo-mutants 27.1.0's real summary lines
(`4 mutants tested in 4s: 4 caught`, `4 mutants tested in 3s: 3 missed, 1
caught`). A `floor | mutation` would be meaningful here - `gates.sh` reads the
number directly before `caught`, which is the kill count - but no profile can
know how many mutants your crate has, so none is set; add one in the story that
gives the gate a number worth defending.

`cargo test` re-executes the test binaries on every run, warm cache or cold, so
the `unit` regex is strong: it fails on precisely the vacuous-workspace bug
above, and it does not fail spuriously.

A `floor` on `unit` is worth having, but not against this regex: `test result:
ok\. [1-9]` stops after one digit, so it would measure `1` where cargo printed
`12`. Widen it to `test result: ok\. [1-9][0-9]*` first, then add the floor.

The vacuous-workspace bug also has a direct check, which does not depend on
anyone reading `--workspace` correctly in a diff:

    discovery | crates | . | cargo test --workspace --no-run 2>&1 | grep "world-core" > /dev/null

Name a crate whose tests must run. `bash scripts/doctor.sh` runs it, and it
fails the moment that crate stops being compiled into the test run.

The three `Finished` regexes are **weak on purpose**. `cargo check`, `clippy`
and `build` print one `Compiling`/`Checking` line per crate on a cold build and
*nothing but `Finished`* on a warm one, so a `Checking [1-9]` regex would fail
whenever the cache was warm. `Finished` proves cargo ran to completion rather
than the command being a no-op or a broken alias; it cannot prove the crate set
was right. For those gates the protection comes from `--workspace` being correct
in the first place, and from the `unit` gate failing loudly if it is not.

Which is why all three carry a `no-count` line. The count `gates.sh` reads is
the first run of digits at or after the evidence match, and cargo's line is

    Finished `dev` profile [unoptimized + debuginfo] target(s) in 0.29s

so that number is the **elapsed time**. Read off a real cargo workspace:
`typecheck` reported `observed 0`, `lint` `2` then `6` across runs of an
unchanged tree, `build` `1` (from `in 1m 22s`). Harmless while it is only printed,
and a coin-toss gate the moment somebody adds `floor | lint | 5` in good faith.
The `no-count` lines make `gates.sh` print `observed -` instead and refuse that
floor outright. There is no regex that fixes this — cargo prints no count on a
warm cache, which is the same fact that makes the regexes weak to begin with.

## What `--fast` should leave out

    slow | build    | a release build of the whole workspace; minutes, and RED has no use for it
    slow | mutation | cargo mutants re-runs the suite once per mutant

`coverage` stays in, and in this stack that is the expensive call: `cargo
llvm-cov` recompiles the workspace with instrumentation, so it does not share
`cargo test`'s cache and it is not a marginal cost on top of `unit`. Keep it
anyway. It is the command that judges the story, and a story that never runs it
until GATES finds out about it on a CI runner instead of a desktop.

## Layout

    src/                    production code, unit tests in-module
    tests/                  integration tests, one binary per file
    benches/                criterion benchmarks, if performance is a criterion
    Cargo.toml              deps with exact-enough versions
    Cargo.lock              committed for binaries

## paths.conf additions

Rust puts unit tests inside source files under `#[cfg(test)]`, which the phase
lock cannot separate from production code. Two options:

- **Keep them in-module** and accept that `src/**/*.rs` is classified `source`.
  The RED phase then cannot write them. Prefer integration tests in `tests/` for
  story work, and treat in-module tests as an implementation detail written
  during GREEN.
- **Move story-level tests to `tests/`** entirely, which the defaults already
  classify as `test`. This is the recommended arrangement under this harness.

## Notes for the bootstrap story

- Install `cargo-llvm-cov`; it is the coverage tool that works without nightly.
- A workspace with a `core` library crate and a thin binary makes the logic
  testable without the IO. Do this from the start.
- For WASM, add `wasm-bindgen` and a `build-wasm` gate; test the core crate
  natively and keep the binding layer thin enough to need almost no tests.
- Set `-D warnings` in the clippy gate, not in CI config, so it means the same
  thing locally.

## Testing notes

`proptest` for invariants - Rust's type system removes whole classes of test,
so what remains is mostly logic and boundaries. `insta` for snapshots of
generated output, reviewed rather than blessed blindly.

## Prerequisites

`rustup` installs and manages the whole toolchain.

    # Windows
    winget install --id Rustlang.Rustup
    # macOS / Linux
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

On Windows, rustup will ask for the MSVC build tools if they are absent; accept,
or install them first with:

    winget install --id Microsoft.VisualStudio.2022.BuildTools

Then the extras the gates use:

    rustup component add clippy rustfmt
    cargo install cargo-llvm-cov
    cargo install cargo-mutants     # optional, mutation gate

Verify: `cargo --version`, `cargo clippy --version`, `cargo llvm-cov --version`.

`cargo install` builds from source and is slow the first time - expect several
minutes for `cargo-llvm-cov`.
