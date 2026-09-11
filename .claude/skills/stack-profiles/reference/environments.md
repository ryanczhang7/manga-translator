# Environments, isolation and Docker

Where dependencies actually live, and why this harness is not built around
containers. Read before changing an install command or proposing Docker.

## Two layers

**The toolchain is global.** `uv`, `node` and `pnpm`, `rustup` and `cargo`, the
Godot binary. Interpreters, compilers and package managers, installed once on
the machine and shared by every project. This is what `/setup-environment`
walks the user through and what `scripts/doctor.sh` verifies is on PATH.

**The libraries are per-project.** Every ecosystem here already isolates them:

| Stack | Libraries land in | Notes |
|---|---|---|
| Python + uv | `.venv/` in the project | A real virtualenv, created and managed by `uv sync`. Nothing touches a global site-packages |
| Node + pnpm | `node_modules/` in the project | Isolated per project. pnpm also keeps one global content-addressed store and hardlinks into it, so shared versions cost disk once |
| Rust + cargo | `target/` per project | Crates cached in `~/.cargo/registry`, resolved per project by `Cargo.lock`. `rust-toolchain.toml` pins the compiler per project |
| Godot | `addons/` in the project | Engine global; the test runner and addons are vendored into the repo and committed |

So a Python virtualenv is not a special case - it is the same shape every one of
these ecosystems uses.

## Gate commands must be environment-aware

This is why the profiles say `uv run pytest` and not `pytest`, `pnpm exec
vitest` and not `vitest`. The runner enters the project environment itself, so:

- there is no "activate the virtualenv first" step to forget
- an agent cannot accidentally shell out to the system interpreter and get a
  meaningless pass
- the same command works identically in CI, where nothing is activated

When adding a gate to `project.conf`, use the ecosystem's run-in-project form.
A bare binary name is a bug waiting for the day two projects want different
versions.

## The `vendor` path category

`node_modules/`, `.venv/`, `target/`, `dist/` and friends are classified
`vendor` in `paths.conf`, and `vendor` is writable in **every** phase.
Installing dependencies is never a phase violation, and a `rm -rf node_modules`
during RED should not be blocked.

The `vendor` rules are deliberately first in the file: `node_modules` is full of
`.md` and `*.test.js` files that would otherwise be classified as docs or tests,
which would let the phase lock be bypassed by writing into a dependency.

Never put authored code under a path that classifies as `vendor`.

## Docker

**This harness is not built around Docker, by choice.** Containers appear only
as: a note that agentic scaffolding must not ship in production images, a sketch
of the production Dockerfile in a couple of profiles, and a fully commented-out
deploy workflow.

The reasons:

- The harness has to work on a machine with nothing installed. Docker is a heavy
  prerequisite to impose on every project.
- For a browser or CLI project it adds nothing to the development loop.
- Bind-mount hot reload through a container is slower and more fragile,
  especially on Windows.
- Containerisation is mostly a deployment concern, and deployment is
  deliberately left to the user.

**It is a per-project decision, not a harness one.** A project that genuinely
needs services - Postgres, Redis, a message broker, several APIs - should have
its bootstrap story write a `docker-compose.yml` and set:

    task | dev | - | . | docker compose up

Nothing else in the harness changes, because every command routes through
`project.conf`. If you do containerise, keep `.dockerignore` honest: `.claude/`,
`docs/`, `scripts/` and `.github/` are development tooling and must not reach a
production image.

## There is no sandbox

Agents run on the user's machine, in the project directory, with the user's
permissions. Everything above is dependency isolation, not a security boundary.
A dev container or VM is the answer if real isolation is wanted; say so rather
than implying the harness provides it.
