# Profile: node-typescript

TypeScript on pnpm. Suits React apps, Node APIs, CLIs, and anything that ships
to a browser through a bundler.

## Gate commands for project.conf

    gate | format    | optional | . | pnpm exec prettier --check .
    gate | lint      | required | . | pnpm exec eslint .
    gate | typecheck | required | . | pnpm exec tsc --noEmit
    gate | unit      | required | . | pnpm exec vitest run
    gate | coverage  | required | . | pnpm exec vitest run --coverage
    gate | integration | optional | . | pnpm exec playwright test
    gate | build     | required | . | pnpm build
    gate | mutation  | optional | . | pnpm exec stryker run
    ondemand | mutation | stryker re-runs the suite once per mutant; run it with /audit-mutations, not per story
    # Combining this with another profile's `mutation` gate: see the stack-profiles skill, *Choosing*.
    # On TypeScript 7 or Vitest 5, `stryker run` as shipped does not work; see
    # *The mutation gate on TypeScript 7 / Vitest 5* below.

    task | install | - | . | pnpm install --frozen-lockfile
    task | dev     | - | . | pnpm dev
    task | test    | - | . | pnpm exec vitest

Biome can replace both Prettier and ESLint; if you use it, one `lint` gate
covers both and `format` becomes `biome format --check`.

## Evidence of work

See the `evidence` format in `project.conf`; these assert that the tool did
work, not that it succeeded.

    evidence | unit        | Tests +[1-9][0-9]* passed
    evidence | coverage    | Tests +[1-9][0-9]* passed
    evidence | typecheck   | -
    evidence | integration | [1-9][0-9]* passed

    # UNVERIFIED against a Stryker run - derived from the clear-text reporter's
    # source. The third number in its `All files` row is `# killed`, and a run
    # that killed nothing is not evidence that the tests ran. No `floor` on this
    # line: gates.sh reads the first number after the match, which is the score.
    evidence | mutation    | All files *[|][^|]*[|][^|]*[|] *[1-9][0-9]* [|]

    # UNVERIFIED - correct these against your own linter's output.
    evidence | lint        | Checked [1-9][0-9]* files      # biome
    # eslint prints nothing on success; use `--format unix` and count, or `-`.

    # UNVERIFIED - `pnpm build` delegates to whatever your build script is, so
    # this is the line most likely to need changing. Vite and esbuild print
    # `built in 1.23s`; `tsc -b` prints nothing at all on success, in which case
    # use `-` and say why in the bootstrap story rather than inventing a match.
    evidence | build       | built in [0-9]
    no-count | build       | `built in 1.23s` is liveness-only; the digits are elapsed seconds

The `unit` and `coverage` lines were verified against vitest 5 and typescript 5
on Windows; the `mutation` line was not run here - its shape is derived from
Stryker's clear-text reporter source and checked by `profiles.test.sh` against
canned rows, not against a Stryker run. Vitest prints
`Tests  2 passed (2)` with ANSI colour and, on Windows, CRLF; `gates.sh` strips
both before matching, so write the regex against the plain text.

`typecheck` is `-` because `tsc` prints nothing on success and there is nothing
honest to match. It does not need liveness cover: `tsc --noEmit` over an empty
`include` fails with `TS18003: No inputs were found`, so its vacuous case is
already loud. `vitest run` with no matching test files is likewise non-zero.
**Never add `--passWithNoTests`** - it converts the safe case into the unsafe
one, which is the whole failure this mechanism exists to catch.

## What `--fast` should leave out

    slow | integration | playwright needs a browser; minutes, not seconds
    slow | build       | a production bundle, which RED and GREEN have no use for
    slow | mutation    | stryker re-runs the suite once per mutant

Note what is *not* here: `coverage` stays in the fast subset even though it is
the slowest of the four that remain. That is the point of it. `vitest run
--coverage` runs the same tests as `unit` under v8 instrumentation, and the
instrumented run is the one that judges the story.

## The mutation gate on TypeScript 7 / Vitest 5

`pnpm exec stryker run` with Stryker's defaults does not work on this
toolchain. Everything in this section was measured by the reporter of issue
#104 on a consumer project, with `@stryker-mutator/core` 10.0.0,
`@stryker-mutator/vitest-runner` 10.0.0, typescript 7.0.2, vitest 5.0.0, Node
24.19.0 and pnpm 12.3.4 on Windows 11. These are the reporter's measurements
(issue #104, section 2), not re-measured here: that toolchain is not installed
in the harness repository.

Two failures, independent of each other:

- **TypeScript 7.** Core's `TSConfigPreprocessor` calls
  `ts.parseConfigFileTextToJson`, which TypeScript 7 (the native port) no
  longer has, whenever `tsconfigFile` names a file that exists. `checkers: []`
  does not avoid it; only a `tsconfigFile` that points nowhere does.
- **Vitest 5.** The vitest runner plugin 10.0.0 was built against vitest
  4.1.10 with a peer range of `>=2.0.0`. Under vitest 5.0.0 it **runs no tests
  and still reports a score**: on one file 85.79% (156 static mutants killed,
  0 of 22 runtime mutants killed), on another 0 of 19 killed where the same
  mutant run by hand fails 9 tests. `--maxTestRunnerReuse 1` and
  `--coverageAnalysis off` do not fix it, and `--logLevel debug` crashes it.

What worked for the reporter was core's built-in command runner:

    // stryker.config.mjs - the shape the reporter measured working
    export default {
      testRunner: "command",
      commandRunner: { command: "pnpm exec vitest related --run <the files named in mutate>" },
      coverageAnalysis: "off",      // no static-mutant bookkeeping; every kill is a real run
      timeoutMS: 60000,             // 5,000 default: 5 of 19 were false timeouts on Windows
      tsconfigFile: "tsconfig.none.json",  // a path that does NOT exist, on TS 7
      plugins: [],                  // the command runner is built in; under pnpm a runner
                                    // plugin, if you use one, must be listed here explicitly
    };

With it, the reporter's runs killed 19 of 19 mutants on the small file, and 155
killed, 22 timeouts and 6 survivors on a 501-line one. Pointing `tsconfigFile`
at a file that does not exist loses nothing when `tsconfig.json` has no
`extends` or `references`; if yours has either, check what Stryker would have
read from it before copying this.

**What the `evidence | mutation` line can and cannot catch.** It requires the
`# killed` column of the `All files` row to be non-zero, so it fails the 0 of
19 run and a run in which nothing was tested at all. It would *pass* the
85.79% run: those 156 kills were static mutants, decided without the runner.
Under the configuration above that case does not arise - with
`coverageAnalysis: "off"` Stryker classifies no mutant as static, because
detecting one needs per-test coverage analysis - so every kill is one the
command runner actually ran, and the line then means what it says. Leave
coverage analysis on and the line is weaker than it looks. Stryker's reporter
also prints `Ran N tests per mutant on average.`, which would read `0.00` in
the broken-runner case; whether it appears depends on
`clearTextReporter.reportMutants`, so confirm it against your own output before
building anything on it.

## The 5,000 ms default is measured against the wrong run

Vitest's default `testTimeout` is 5,000 ms, and every timing intuition you have
comes from `vitest run`, which is the fast path. Under `--coverage` the same
test is slower, and on a CI runner slower again. Measured on one real story:

| | `--coverage` | plain |
|---|---|---|
| a property test asserting per-item | 2,644 ms | 1,835 ms |
| its sibling, same draws, accumulating | 260 ms | 75 ms |

The first one passed locally under both commands and failed CI. Two rules fall
out of it, and the second is worth more than the first:

- Set an explicit `testTimeout` on property tests and anything looping over a
  generated collection - in the test file or `vitest.config.ts`, generously,
  because the default was never measured against the command that judges you.
- **Do not call `expect()` once per item.** Accumulate the violations and assert
  once at the end. That is the entire difference between the two rows above:
  identical work, an order of magnitude apart, because each `expect` in vitest
  builds a diff and a stack. This matters more than the timeout, since it also
  makes the failure message name every violation instead of the first.

## How much work, and where

    floor | unit     | 40      # raise it in the story that adds the tests
    floor | coverage | 40

The floor is read out of the evidence match, so keep the whole number inside
the regex (`Tests +[1-9][0-9]* passed` does; a regex ending in `[1-9]` would
measure one digit). Never lower one to make a gate pass.

The real trap in this stack is per-directory coverage thresholds. A
`vitest.config.ts` carrying `"src/platform/**": { lines: 100 }` for a directory
no project's `include` matches is satisfied vacuously and reports nothing - a
test written there is committed and never runs. This has happened, and the
`coverage` evidence line does not catch it: the run is not empty, it is merely
blind in one place.

Reading the globs is how it stays hidden. Ask the runner instead, and record
the answer:

    discovery | platform | . | pnpm exec vitest list | grep "src/platform/" > /dev/null
    discovery | e2e      | . | pnpm exec playwright test --list | grep "e2e/" > /dev/null

`bash scripts/doctor.sh` runs these. Add one for every directory carrying a
threshold, and check `vitest list` yourself whenever you add a project or a
threshold - the config that produced the bug looked correct.

## Biome through stdin is not the gate

`biome lint --stdin-file-path=<path>` does **not** apply `overrides`. A file
that the real gate rejects is reported clean, exit 0 - a silent wrong answer
rather than an error. Any test asserting on a path-scoped Biome rule (an
`import/no-restricted-paths`-style boundary, for instance) must write a real
file at a real path, run the real gate command, and delete it afterwards.

## Layout

    src/                    production code
    src/**/*.test.ts        co-located unit tests, or tests/ if you prefer
    e2e/                    Playwright specs
    package.json            deps, scripts, pinned versions
    pnpm-lock.yaml          committed
    tsconfig.json           strict: true, no exceptions

## paths.conf additions

Defaults cover `*.test.*`, `*.spec.*`, `__tests__/` and the config files. If you
use `e2e/` for Playwright, add `e2e/**` to the `test` section.

## .gitignore additions

The runners write into the tree, and what they write is generated, not
authored. The repo's `.gitignore` already carries these; keep them if you
prune it:

    .vitest/              # vitest browser-mode failure screenshots
    playwright-report/
    test-results/
    .playwright/

Missing entries cost twice: untracked noise, and a phase lock that classifies
the directory as `source` and refuses to let you delete it.

## Notes for the bootstrap story

- Set the coverage thresholds in `vitest.config.ts` (`coverage.thresholds`) so
  the coverage gate fails on its own.
- `strict: true` plus `noUncheckedIndexedAccess` in `tsconfig.json`. Turning
  these on later is a project of its own; turning them on now costs nothing.
- For React, add Testing Library and prove one real user interaction in the
  example test - a render assertion alone is the theatre this harness exists to
  prevent.
- Dockerfile: builder runs `pnpm build`, runtime serves the static bundle from
  `nginx:alpine`, or `node:22-slim` for an API.

## Testing notes

Testing Library queries by role and label, not by test id, so the test fails
when the accessible name breaks. `vi.useFakeTimers()` rather than waiting. Mock
at the network boundary with MSW rather than mocking your own modules.

## Prerequisites

Node.js LTS, then pnpm through corepack (which ships with Node, so there is
nothing else to install globally).

    # Windows
    winget install --id OpenJS.NodeJS.LTS
    # macOS
    brew install node
    # Linux: use nvm, or your distro's nodesource package

    corepack enable
    corepack prepare pnpm@latest --activate

Then, inside the project: `pnpm install --frozen-lockfile`.

Verify: `node --version` prints v22.x or later, `pnpm --version` prints a
version.

Optional: `pnpm exec playwright install --with-deps chromium` downloads the
browser the integration gate drives. It is a few hundred megabytes, so only do
it when you actually add end-to-end tests.
