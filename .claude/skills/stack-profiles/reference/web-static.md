# Profile: web-static

Browser projects with little or no build step: canvas and WebGL toys, tools,
prototypes, documentation sites. Chosen when the brief values "open the file and
it runs" over framework leverage.

## Gate commands for project.conf

    gate | format    | optional | . | pnpm exec biome format --check .
    gate | lint      | required | . | pnpm exec biome lint .
    gate | typecheck | required | . | pnpm exec tsc --noEmit --allowJs --checkJs
    gate | unit      | required | . | pnpm exec vitest run --environment jsdom
    gate | coverage  | required | . | pnpm exec vitest run --coverage
    gate | integration | optional | . | pnpm exec playwright test
    gate | build     | required | . | pnpm exec vite build

    task | dev  | - | . | pnpm exec vite
    task | test | - | . | pnpm exec vitest

Even a no-build project benefits from `tsc --checkJs` over JSDoc types: it is
the cheapest type checking that exists, and it needs no compile step.

## Evidence of work

See the `evidence` format in `project.conf`; these assert that the tool did
work, not that it succeeded.

    evidence | unit        | Tests +[1-9][0-9]* passed
    evidence | coverage    | Tests +[1-9][0-9]* passed
    evidence | typecheck   | -
    evidence | integration | [1-9][0-9]* passed

    # UNVERIFIED - correct against your biome version's output.
    evidence | lint        | Checked [1-9][0-9]* files
    evidence | build       | built in

`biome lint` aimed at a directory containing no source **exits 0 and reports
"Checked 1 file"** - it counts the directory. That is the vacuous pass in this
stack; the `[1-9]` is a weak guard against it, so also keep the lint target
honest and re-check it whenever the tree is reorganised.

See `node-typescript.md` for the vitest and tsc notes, which apply unchanged.

## What the runner can see

    # UNVERIFIED - correct the grep targets against your own layout.
    discovery | tests | . | pnpm exec vitest list | grep -q "src/"

`vitest list` prints the test files it would run. A `test.include` that stopped
matching, or a directory moved out from under a coverage threshold, is invisible
in the configuration and obvious here. Add one line per directory carrying a
threshold; see `node-typescript.md`, where a 100% threshold on a directory no
project included went unnoticed because every glob looked right.

## What `--fast` should leave out

    slow | integration | playwright needs a browser; minutes, not seconds

Only that one. `vite build` on a static site is seconds, so marking it `slow`
would buy nothing and would hide a broken build from RED and GREEN - a gate is
fast unless it is genuinely expensive, not unless it is conceivably skippable.
Compare `node-typescript.md`, where `build` *is* marked slow because it is a
bundle rather than a static copy. The judgement is per stack, and the reason on
the line is what makes it reviewable.

`coverage` stays in, as everywhere: it runs the same tests under v8
instrumentation, and vitest's 5,000 ms default `testTimeout` was measured
against the plain run. See `node-typescript.md` for the numbers.

## Layout

    index.html
    src/                    ES modules, imported directly in dev
    src/**/*.test.js        unit tests
    e2e/                    Playwright specs
    public/                 static assets

## Notes for the bootstrap story

- Keep the module graph importable by both the browser and the test runner:
  real ES modules, no bundler-only syntax in `src/`.
- Canvas and WebGL logic is testable if you separate it: the function that
  decides *what* to draw is pure and unit-testable; the function that calls the
  drawing API is thin and covered by one integration test.
- For anything with rendering output worth pinning, add Playwright screenshot
  comparison as the `integration` gate and commit the baselines.

## Testing notes

Prefer `jsdom` for DOM logic and a real browser through Playwright for anything
involving layout, canvas or input. Do not assert on pixel colours in jsdom - it
does not paint, and a test that passes there proves nothing about the screen.

## Prerequisites

Same as the `node-typescript` profile: Node.js LTS plus pnpm via corepack. See
that profile's Prerequisites section.

Even for a project with no build step, the toolchain is needed for the gates -
the test runner, the type checker and the linter all run on Node.
