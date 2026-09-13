# agentic-dev-harness

A template repository for building software with Claude Code, where the
test-first discipline is enforced by the tooling rather than requested in a
prompt.

Four agents do the work. A product owner interviews you and turns the answers
into a backlog; a test developer writes failing tests from each story; a feature
developer makes them pass without being able to touch the tests; a designer
records the decisions that make the interface implementable. A fifth, optional,
audits whether the tests mean anything.

The harness itself depends on nothing but **git and bash**. The projects it
builds can use any stack.

---

## Requirements

For the harness itself, on any platform:

- **git**
- **bash** — already present on macOS and Linux; on Windows it comes with Git
  for Windows, which Claude Code requires anyway
- **Claude Code**

That is the whole list. No Python, no Node, no package manager. The harness is
plain shell so that it works on a machine that has nothing installed yet.

Your *project* will need a toolchain — a language runtime, a test runner, a
linter. Which one depends on the stack `/plan-product` chooses, so it is not
installed up front. `/setup-environment` works out what is needed, writes it
down in `docs/wiki/environment.md`, and `bash scripts/doctor.sh` verifies it.

## Starting a new project

The same seven steps every time. Nothing here is improvised, and you should not
have to ask how to set a project up.

**1. Get a copy that is its own repository.** Every project must be a separate
repo, so that project work never lands back on the harness.

*Preferred, on GitHub:* mark this repository as a template (Settings, General,
"Template repository"), then use **Use this template, Create a new repository**.
The new repo starts with no shared history and no fork relationship, so there is
no remote pointing back here to push to by accident.

*Without GitHub:*

```bash
git clone https://github.com/<you>/agentic-dev-harness my-project && cd my-project
rm -rf .git && git init && git add -A && git commit -m "harness baseline"
git remote add origin <your new empty repo>
```

Either way, check `git remote -v` before your first push. If it still says
`agentic-dev-harness`, stop and fix it.

Improvements you make to the harness while working on a project do not flow back
automatically. When you find one worth keeping, copy the file into this
repository deliberately. Neither does anything flow the other way — see
[Refreshing a vendored harness](#refreshing-a-vendored-harness), which is the
direction that has actually cost something.

**2. Check the machine.** `bash scripts/doctor.sh` — at this point it should
report the harness is fine and there is no toolchain configured yet. That is the
expected state before a stack is chosen.

**3. `/create-product`.** An interview. Answer honestly, including "I don't
know" — the Lead PO will push back rather than invent. Produces
`docs/wiki/product-brief.md`. Read it before continuing; everything downstream
inherits its assumptions.

**4. `/plan-product`.** Produces the stack, the architecture, the design
decisions, the epics and the stories — including a `bootstrap` story that will
turn this empty repo into the chosen stack's real layout. Read `stack.md` and
push back now if a choice looks wrong; it is cheap here and expensive later.

**5. `/setup-environment`.** Works out what the chosen stack needs installed,
writes `docs/wiki/environment.md`, and gives you the install commands. It will
not install anything without asking — that changes your machine, not the repo.
Run the commands it gives you, then let it re-verify.

**6. `bash scripts/doctor.sh`.** Must be clean before you continue. Every gate
command's executable has to be on PATH; a bootstrap story built on a missing
tool fails in a confusing way.

**7. `/complete-story <bootstrap-id>`.** Scaffolds the project and fills in
`.claude/harness/project.conf`. After it merges, `bash scripts/gates.sh` should
pass on a real, empty project — and from then on the loop is just
`/complete-story <next-id>`, over and over.

`/status` at any point shows the board, the active story and the last gate
result.

---

## The loop

```
  You                          Agents                        Artefacts

  /create-product   ────────►  Lead PO                ────►  docs/wiki/product-brief.md
  (interview)

  /plan-product     ────────►  Lead PO + Designer     ────►  docs/wiki/{stack,architecture}.md
                                                             docs/wiki/design/**
                                                             docs/backlog/{epics,stories}/**

  /advance-story ID ────────►  Lead PO orchestrates:
  /complete-story ID           ├─ Test Developer      ────►  failing tests            (RED)
                               ├─ Feature Developer   ────►  production code          (GREEN)
                               └─ scripts/gates.sh                                    (GATES)

  Review the PR     ◄────────  branch story/ID-slug + PR
```

A story is one RED→GREEN cycle. `/advance-story` moves it one phase and stops so
you can inspect; `/complete-story` runs the whole cycle and stops only for gate
failures and genuine ambiguity.

---

## Commands

| Command | Does |
|---|---|
| `/create-product` | Interviews you; writes the product brief |
| `/plan-product` | Brief → stack, architecture, design, epics, stories. Idempotent |
| `/setup-environment` | Works out what the stack needs installed, writes `docs/wiki/environment.md` |
| `/plan-story "<description>"` | Adds one story without re-planning the product |
| `/advance-story <id>` | Moves a story forward exactly one phase |
| `/complete-story <id>` | Drives a story to a PR |
| `/audit-mutations [scope]` | Optional: finds tests that would not notice a bug |
| `/status` | Board, active story, last gate result |

## Agents

| Agent | Writes | Never writes |
|---|---|---|
| Lead PO | `docs/wiki/**`, `docs/backlog/**`, `project.conf`; under SCAFFOLD, the bootstrap story's source and tests (see `rules.md`) | source, tests, outside that one story |
| Test Developer | test files, the story's test plan, handoff and regressions | production code |
| Feature Developer | source and config, the story's gate probes (the gate *results* are written by `gates.sh`) | test files |
| Lead Designer | `docs/wiki/design/**`, a story's design notes | code |
| Mutation Tester | `docs/wiki/audits/**`, new stories | code, tests |

The commands dispatch these; you do not normally invoke them directly.

---

## The phase lock

The part that makes this more than a prompt.

`.claude/hooks/phase-guard.sh` runs before every write and refuses the ones that
violate the story's current phase:

- **RED** — tests only. Production code is frozen, so the implementation cannot
  be written "while writing the test".
- **GREEN** — source only. Tests are frozen, so a failing test cannot be softened
  into a passing one.
- **GATES** — source only, for fixing lint, types and build.

It covers `Write`, `Edit`, `MultiEdit` and `NotebookEdit`, and inspects shell
commands too — redirects, `tee`, `sed -i`, `cp`, `mv`, `rm`, `touch`, each
resolved against the directory the command will actually run in — because an
agent that cannot use Edit
will reach for `cat > file`. Quoted arguments and heredoc bodies are masked
before that inspection, so a `|` inside `sed 's|a|b|'` and an arrow inside
`awk '/A -> B/'` stay data: a lock that fires on the contents of a string
teaches the agent that blocks are noise, which is the one thing it cannot
afford. Relative paths are resolved against the directory the command will
actually run in, so `cd /tmp/scratch && rm -rf logs` names no repo path at all
and `cd src && echo x > main.ts` names `src/main.ts` rather than a file at the
root. Anything the project's `.gitignore` covers is classified `ignored` and
writable in every phase, so deleting a test runner's scratch directory is not a
phase violation. And a parse the guard cannot believe — a "path" that is an
operator, a regex fragment or a leftover backquote — is treated as
inconclusive rather than as a violation: it is logged to
`.claude/state/phase-guard-declined.log` and allowed, because a guard that
cannot say what it is looking at is guessing, and every denial that turns out
to be a guess makes the real ones easier to ignore. The same file carries the
opposite finding, marked `no-candidate`: a command that names a write-capable
tool and yet hands the guard no operand at all — `find src -name '*.ts' | xargs
rm` writes a path the shell never spelled out — is allowed too, and said so,
because *allowed* and *never examined* are different facts and the log is the
only place they part. When no story is active the
lock is off entirely: it protects a cycle in flight, it is not a general
permission system.

The lock has its own regression suite, since it is the mechanism everything
else rests on, and so do the gate machinery and the stack profiles - the
profile suite asserts that every shipped profile obeys the rules
`new-profile.md` sets, because a profile is copied verbatim into a real
project and a bad line arrives pre-installed:

```bash
bash scripts/selftest.sh                   # the harness's own tests
bash scripts/ci-local.sh                   # every step CI runs, in order, here
```

`ci-local.sh` is the whole CI sequence on your machine — useful when a runner is
slow, metered or unavailable, and the right way to know a PR will pass before
opening one. It is not a substitute for the checks themselves: it is one machine,
it runs only when invoked, and no branch rule can require it.

```bash
bash scripts/phase.sh show                 # what is active, what may be written
bash scripts/phase.sh board                # every story at a glance
bash scripts/phase.sh set PROJ-014 GREEN   # the only supported way to change phase
```

A `Stop` hook refuses to let a story be called finished while the gates have not
been run since the last code change, or while the last run failed. "Done" is
measured, not asserted. "Code" there means what the gates would have hashed —
source, test, config, and the harness's scripts and manifests — so a coverage
report or a build directory the gates themselves produced does not count as a
change, re-running a gate to check something never blocks the report that
follows it, and neither does rewording a command file or a skill, which no
gate reads.

## Gates

Gate *names* are stable across every project; the *commands* are per-stack and
live in one file, `.claude/harness/project.conf`:

```
gate     | unit     | required | . | uv run pytest -q
evidence | unit     | [1-9][0-9]* passed
gate     | coverage | required | . | uv run pytest --cov=src --cov-fail-under=100
evidence | coverage | TOTAL +[0-9]+ +[0-9]+
task     | dev      | -        | . | uv run uvicorn app:api --reload
```

```bash
bash scripts/gates.sh              # all of them
bash scripts/gates.sh --fast       # all but the ones marked `slow` (RED, GREEN)
bash scripts/gates.sh --gate unit  # one
bash scripts/gates.sh --audit      # check the manifest, run nothing
bash scripts/check-boundaries.sh   # the other half of CI: the commit, not the code
bash scripts/task.sh dev           # run the app
bash scripts/mutate.sh F 'EXPR' -- CMD   # a diagnostic mutation, restored and verified
```

The `evidence` lines exist because **exit 0 does not mean a gate did anything**.
`cargo test` at a workspace root tests the root package and skips every member;
`mypy` over a target that resolves empty reports "no issues found in 0 source
files"; a linter aimed at a directory that moved checks nothing. All exit 0, and
a harness that treats exit 0 as proof will report `PASS` forever. After a gate
exits 0 its output must match its regex, or it fails with *ran but produced no
evidence of work*. The regex asserts volume of work, never success — success is
the exit code's job. Gates without an `evidence` line behave exactly as before.

A `floor` line goes one further: `evidence` catches a gate that did nothing, a
floor catches one that started doing much less — a suite that went from 47
tests to 3 exits 0 and matches its regex just as happily. And because a
coverage threshold on a glob matching nothing is satisfied *silently*,
`discovery` lines in the same file ask the runner what it can actually see, and
`doctor.sh` runs them: a claim about what a runner discovers is verified by
running the runner, never by reading its globs. A story whose evidence lives in
an optional gate escalates it for itself with `required_gates: [integration]`
in its frontmatter — optional for the repo, binding for that story.


A `slow` line names a gate that `--fast` leaves out — a release bundle, a
browser suite. Everything else stays in, and the instrumented test run stays in
deliberately: RED and GREEN otherwise only ever see the plain test command,
while a required gate judges the same tests under coverage, which is slower, on
CI hardware that is slower again. That gap cost one real story a full round
trip. `--fast` is what lets RED ask whether its tests are even admissible to the
gates, and it is never recorded — only a full run is evidence.

A `ci-factor` line records how much slower **one test** is on CI under a given
gate, measured once from a real CI log and cited:

```
ci-factor | coverage | 3.4 | actions run 412, "AC-4/AC-5 file 1,262 ms"
```

It is worth a line in the manifest because the number everyone reaches for
instead — the gate's own local-to-CI wall-time ratio — is several times too
large. Most of a coverage gate's wall time is fixed overhead that does not scale
with test compute: one project measured 14x for the gate and 3.4x per test, and
acting on the 14x means optimising a test that was already fine.

And `gates.sh` is not all of CI. `check-boundaries.sh` judges the **commit**
rather than the code, so it cannot be a gate: it reads the phase out of the
committed frontmatter and checks the gate record against the tree being merged,
neither of which exists yet while the gates are running. Run it after committing
and before opening the PR.

Three more things `gates.sh` does that a plain test runner does not. A `waiver`
line names an optional gate that is known to fail and why, so it reports as
`KNOWN` and `WARN` stays reserved for something that changed. A gate the
*environment* refused to launch — a policy blocking an unsigned local binary, a
missing runtime — reports `BLOCKED` and exits 3, because "the machine would not
run it" is neither a pass nor a failure, and reporting it as a failure sends an
orchestrator hunting a defect that is not there. A BLOCKED required gate is a
recorded decision, REVIEW with that gate *pending CI*, and DONE only once the
PR's CI run for it is quoted. And a full run
writes its own summary into the story's `## Gate results`, stamped with the
commit and a hash of the code it ran against; nobody pastes it, and
`check-boundaries.sh` refuses a PR whose recorded run does not match the code
being merged. That script also freezes acceptance criteria once a story leaves
PLANNED (changes need an `## Amendments` entry), requires a filled-in handoff,
requires a scaffold story to name every source file it wrote, and requires
`## Regressions` and `## Gate probes` to *show* the failure they claim rather
than describe it — a corrected test runs for the first time against code that
already satisfies it, so pasted red from a reverted mutation is the only thing
separating it from an assertion that checks nothing. That mutation goes through
`mutate.sh`, which is allowed in every phase — including the one that freezes
source — precisely because it restores the file and checks with `cmp` that it
did; the harness demanded such a mutation for several stories before it provided
a way to make one, and every agent quietly reached for `sed -i` instead.
`phase.sh` refuses to start a story whose `depends_on` are not DONE or from the
wrong branch.

That indirection is what lets the same agents drive a Python service, a
TypeScript app and a Godot game. `.claude/skills/stack-profiles/` holds command
sets for Python, TypeScript, Rust, Godot and static web, plus a template for
writing a profile for anything else. Lines that have not been run on a real
toolchain are marked `# UNVERIFIED`; the bootstrap story's job is to execute
every one of them and correct what has moved.

Coverage defaults to a 100% threshold, set in the gate command where it is
visible. Mutation testing is available but optional — it is the bar above the
bar, not the daily requirement.

## Environments, and why there is no Docker

Two layers, and only one is global.

**The toolchain is global** — `uv`, `node` + `pnpm`, `cargo`, the Godot binary.
Installed once on your machine, shared by every project. `/setup-environment`
walks you through it; `bash scripts/doctor.sh` verifies it.

**The libraries are per-project.** Python gets a real `.venv/`, Node gets
`node_modules/`, Rust resolves per project through `Cargo.lock`, Godot addons
are vendored into the repo. A virtualenv is not a special case — it is the shape
every one of these ecosystems already uses, and the harness relies on it rather
than inventing anything.

Gate commands are written to be environment-aware for that reason: `uv run
pytest`, not `pytest`; `pnpm exec vitest`, not `vitest`. There is no "activate
the venv first" step to forget, and an agent cannot accidentally shell out to
your system interpreter and get a meaningless pass.

`doctor.sh` checks both layers — the executables on PATH, and whether this
project's dependencies are actually installed.

**Docker is deliberately not part of this.** The harness must work on a machine
with nothing installed, containers add nothing to the dev loop for a browser or
CLI project, and bind-mount hot reload through a container is slow and fragile
on Windows. Containerisation is a deployment concern, and deployment is yours.

It remains a per-project choice: a project that genuinely needs Postgres, Redis
and three services should have its bootstrap story write a `docker-compose.yml`
and set `task | dev | - | . | docker compose up`. Nothing else changes, because
every command routes through `project.conf`.

**There is no sandbox.** Agents run on your machine with your permissions. The
above is dependency isolation, not a security boundary — use a dev container or
a VM if you want the real thing.

Full detail: `.claude/skills/stack-profiles/reference/environments.md`.

## CI

Two required jobs, and between them they run more than `gates.sh` does.

- **`gates.yml`** runs the harness's own self-test (`selftest.sh`), prints the
  configured gates, audits the manifest (`gates.sh --audit` — which fails a
  `floor` with no evidence line, or a `slow` line with no reason or naming no
  gate), then runs the gates. Add your stack's toolchain setup step; the harness
  itself needs nothing.
- **`boundaries.yml`** re-checks on the diff what the hook could not see, either
  because it was never in the loop or because the invariant is about a story
  file over time rather than one write: frontmatter is valid, runtime state is
  not committed, production code did not arrive without tests (or is named in
  `## Scaffold inventory`), the story is in a phase that justifies a PR, the
  branch matches its frontmatter, acceptance criteria have not changed since the
  base branch without an `## Amendments` entry, `## Handoff` is filled in, and
  the `## Gate results` block was written by `gates.sh` against the *same tree*
  being merged — including a PASS for any gate the story escalated with
  `required_gates`.
- **`deploy.yml.template`** is deliberately inert. Agents can write deploy
  configuration; they should not run it. You pull that trigger.

Run both locally before pushing: `bash scripts/gates.sh` and
`bash scripts/check-boundaries.sh`. "All gates pass" is not "CI will pass" —
they judge different things, the code and the commit.

## Layout

```
CLAUDE.md                     standing rules, in context every turn
.claude/
  settings.json               hooks, permissions, status line
  commands/                   the slash commands above
  agents/                     the five agent definitions
  skills/                     shared methodology, loaded on demand
    tdd-cycle/                the RED→GREEN discipline
    story-authoring/          story format and sizing
    quality-gates/            what each gate means, how to triage
    stack-profiles/           per-ecosystem command sets
    design-system/            tokens, states, accessibility floor
  hooks/                      phase guard, state injection, gate reminder,
                              status line, and lib.sh they all share
  tests/                      the harness's own tests (scripts/selftest.sh)
  harness/
    project.conf              how to build and test THIS project
    paths.conf                which paths are test / source / config
    phases.conf               which phase may write which category
    rules.md                  path ownership, imported by CLAUDE.md
    mcp-notes.md              which MCP servers are worth wiring, and when
  state/                      runtime state, gitignored
.github/workflows/            gates and boundaries, the two CI jobs
.mcp.json.example             MCP servers to opt into per project
docs/
  wiki/                       brief, stack, architecture, design, audits
  backlog/{epics,stories}/    the work
scripts/                      doctor, gates, phase, task, dev, new-story, selftest,
                              check-boundaries
```

## Notes on the design

**Methodology lives in skills, not in agent files.** The agents are short — a
role and its boundaries. The TDD discipline, story format and gate catalogue are
skills both the test and feature developers load, so there is one source of truth
and the details load only when needed.

**The story file is the protocol.** Subagents have separate context windows, so
handoffs are genuinely lossy. Anything the next agent needs must be written into
the story file before the phase ends — "as discussed above" does not survive the
boundary. This is a constraint worth designing for rather than around: it keeps
the orchestrator's context clean across a long cycle.

**Nothing is scaffolded until the stack is chosen.** There is no hello-world
app. The first story of any project is a `bootstrap` story that creates the real
layout and fills in `project.conf`. A skeleton in the wrong language is worse
than none.

**The harness never ships.** `.claude/`, `docs/` and `scripts/` are development
tooling. Keep them out of production images.

## Adapting it

- Change what counts as a test or config file: `.claude/harness/paths.conf`
- Change what each phase may write: `.claude/harness/phases.conf`
- Loosen the lock to warnings: change `permissionDecision` in
  `.claude/hooks/phase-guard.sh`
- Add a stack: write a profile in `.claude/skills/stack-profiles/reference/`
- Give the designer real eyes: copy `.mcp.json.example` to `.mcp.json`
  (needs Node)


## Refreshing a vendored harness

A project made from this template gets a **copy**. Nothing updates it, and the
copy going stale is not a theoretical problem: two consecutive field reports from
a real project filed defects that had been fixed upstream for weeks, and the
cost was not the reports — it was re-verifying every finding by hand before it
could be called already-fixed. One of those reports described agents working
around a rule with `sed -i` because the sanctioned tool for it "did not exist";
`scripts/mutate.sh` had been upstream for three rounds.

**First, find out how stale it is.** `bash scripts/doctor.sh` prints
`harness ver` in both repositories — compare them. A copy that reports
`unstamped` predates versioning entirely, and is older than any dated release.

**Then copy, and know which half you are copying.** The split is not by
directory, and getting it wrong either loses project configuration or keeps the
bug you were trying to remove:

| Upstream-owned — replace wholesale | Project-owned — never overwrite |
|---|---|
| `.claude/agents/`, `.claude/commands/`, `.claude/skills/` | `.claude/harness/project.conf` — gates, tasks, the whole stack indirection |
| `.claude/hooks/`, `.claude/tests/` | `docs/**` — wiki, backlog, stories, audits |
| `scripts/*.sh` | `.gitignore` — the project adds its stack's output |
| `.claude/harness/phases.conf`, `rules.md`, `VERSION` | `.github/workflows/gates.yml` — the project adds its toolchain setup steps |

`.claude/harness/paths.conf` and `CLAUDE.md` are the two that need reading rather
than copying: both are upstream documents a project is invited to extend, so
merge them instead of replacing them.

```bash
HARNESS=../agentic-dev-harness            # a checkout of this repository
rsync -a --delete "$HARNESS"/.claude/{agents,commands,skills,hooks,tests} .claude/
cp "$HARNESS"/.claude/harness/{phases.conf,rules.md,VERSION} .claude/harness/
cp "$HARNESS"/scripts/*.sh scripts/       # adds new scripts; leaves yours alone
```

`--delete` on the first line is deliberate: a skill or hook that upstream
*removed* has to go, or the project keeps running a rule this harness no longer
believes. It is also why `scripts/` uses `cp` instead — a project legitimately
adds its own scripts there, and `--delete` would take them.

**Finally, re-run the checks, in this order.** `bash scripts/selftest.sh` first —
it tests the machinery everything else depends on, and it is the file set you
just replaced. Then `bash scripts/doctor.sh`, then `bash scripts/gates.sh`. Do it
between stories, never mid-cycle: the hooks you are replacing are the ones
enforcing the phase you are standing in.

**When you next write a field report**, state the version you measured. That one
line is the difference between "here are twenty findings" and "here are the three
you have not already fixed".

## Licence

**All rights reserved.** This repository is readable, not reusable: no licence
is granted to use, copy, modify or distribute any part of it. See
[`LICENSE`](LICENSE), and ask if you want permission.

Note that the repository is public, and a public repository on GitHub can be
viewed and forked by any GitHub user under GitHub's own terms of service. That
is a platform permission, not a licence from the copyright holder, and it is not
something this file can withdraw. If nobody is to hold a copy at all, the
repository has to be private.
