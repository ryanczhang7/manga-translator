# Configuring gates for a project

`.claude/harness/project.conf` is the only place the harness learns how to build
and test this project. Format, one entry per line:

    <kind> | <id> | <required|optional> | <cwd> | <command>

`kind` is `gate` or `task`. `cwd` is relative to the repository root. An empty
command marks the gate unconfigured.

Each gate also gets a liveness assertion, and an optional gate that is known to
fail gets a waiver naming why:

    evidence | <gate id> | <extended regex>
    waiver   | <gate id> | <why this optional gate is expected to fail>

A waiver turns that gate's failure from `WARN` into `KNOWN` so that `WARN`
always means something changed. It is refused on required gates.

Five more kinds, each explained in the skill and in `project.conf`'s own
comments:

    floor        | <gate id> | <minimum count read out of the evidence match>
    slow         | <gate id> | <why it is too slow for gates.sh --fast>
    covers       | <gate id> | <glob of the paths this gate actually reads>
    discovery    | <id> | <cwd> | <command proving a runner can see a directory>
    blocked-when | <gate id> | <regex meaning this runner could not START>

`floor` catches a gate that quietly started doing much less; `slow` names what
`--fast` leaves out, reason required; `covers` is what lets `gates.sh` fail a
run whose changed source only optional gates read; `discovery` lines are run
by `doctor.sh`, never by the gates, and are how a `covers` line is proved.

`blocked-when` extends the built-in list of shapes that mean the environment
would not launch the gate - `could not execute process`, `never executed`, `os
error 4551`, `cannot execute binary file`, `command not found`, a Permission
denied on a path - so that such a gate reports `BLOCKED` (exit 3) rather than
FAIL. Add one only for a launch failure your runner words differently. A compile
error, a missing module and a failed assertion are the gate doing its job, and a
pattern that catches them turns real failures into decisions nobody makes.
`--audit` refuses a line naming no gate, and one with no pattern.

Once CI has run a gate for real, record how much slower one test is there:

    ci-factor | <gate id> | <per-test factor> | <the CI run it came from>

Measured per test from a real log, never derived from the gate's own wall time,
which is mostly fixed overhead and overestimates the factor several-fold.
`--audit` refuses a factor that is not a number, one with no source, and one
naming a gate that does not exist. See the skill's "How much slower is CI,
actually".

## Rules

- **Pin the runner, not the shell alias.** `pnpm exec vitest run` rather than
  `npm test`, so the gate does not change meaning when someone edits a script.
- **Make it non-interactive and non-watching.** Gates run in CI. A watcher hangs
  the pipeline.
- **Put the threshold in the command.** The coverage gate should fail on its
  own: `--cov-fail-under=100`, `--coverage.thresholds.100`, and so on. Do not
  rely on a human reading the number.
- **Name the whole target explicitly.** `cargo test --workspace`, `pytest tests/`
  rather than whatever the tool defaults to. Defaults resolve to less than you
  expect and do it quietly.
- **Never add a "pass with no tests" flag.** `--passWithNoTests` and its
  equivalents turn a runner that honestly fails on an empty discovery into one
  that silently succeeds.
- **One command per gate.** If you need two, they are two gates.
- **Keep `cwd` honest** for monorepos - one gate per workspace is clearer than
  one command that loops.

## Writing an evidence line

Copy the ecosystem's from the `stack-profiles` skill, then verify it here rather
than trusting it: tool output changes between versions.

1. Run the gate normally and read the output.
2. Pick the smallest thing that **counts units of work** and require it to be
   non-zero - `Tests +[1-9][0-9]* passed`, `test result: ok\. [1-9]`.
3. Assert volume, not success. `0 failed` is a success assertion and is exactly
   as true when nothing ran.
4. Run the gate a second time. If the regex now fails, you have matched
   something a warm cache suppresses; pick something the tool prints every run.
5. Make the gate vacuous on purpose - move the test directory aside - and
   confirm it now fails. Then put it back.

`|` inside the regex is fine; everything after field 2 is the pattern. ANSI
colour and CRLF are stripped before matching, so write plain text. Where a tool
prints nothing countable, `evidence | <id> | -` records that deliberately - use
it rarely, and say why in the story.

    bash scripts/gates.sh --audit

reports gates whose `cwd` does not exist, gates with no evidence line, a floor
or slow line it cannot honour, and - once `BOOTSTRAPPED=yes` - required gates
with no command, without running anything. Before the flag is flipped an
unconfigured gate is reported as `ok (unconfigured)`.

## Multiple workspaces

For a project with a backend and a frontend, prefer distinct ids:

    gate | unit-api | required | backend  | uv run pytest
    gate | unit-web | required | frontend | pnpm exec vitest run

The stable name is the id, so stories and agents can refer to "the unit-web
gate" without knowing the command.

## Tasks

`task` entries are for commands humans and agents run outside the gates:
`install`, `dev`, `test`, and anything else worth not re-deriving. Anything an
agent would otherwise have to remember belongs here - the next agent starts with
an empty context and will trust this file.

## Flipping the flag

`BOOTSTRAPPED=no` at the top makes unconfigured required gates warnings rather
than failures, so the very first story can run before the stack exists. The
bootstrap story sets it to `yes`. Never set it back.

It is a one-way trust flip that every later story depends on, so earn it: run
`bash scripts/gates.sh --audit` until it is clean, and run every gate for real.
A bootstrap story that lands with a wrong command poisons every story after it,
because the next agent starts with an empty context and will trust this file
without re-deriving anything.
