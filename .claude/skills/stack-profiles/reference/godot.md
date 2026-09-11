# Profile: godot

Godot 4 for games and interactive tools. The testing story is weaker than in
other ecosystems, so the architecture has to carry more of the load.

## Gate commands for project.conf

    gate | format    | optional | . | gdformat --check scripts/ src/
    gate | lint      | required | . | gdlint src/
    gate | typecheck | required | . | godot --headless --check-only --quit --path .
    gate | unit      | required | . | godot --headless --path . -s addons/gdUnit4/bin/GdUnitCmdTool.gd -a test/
    gate | coverage  | optional | . |
    gate | build     | required | . | godot --headless --path . --export-release "Linux/X11" build/game.x86_64

    task | install | - | . | echo "install Godot 4 and the gdUnit4 addon"
    task | dev     | - | . | godot --path .
    task | test    | - | . | godot --headless --path . -s addons/gdUnit4/bin/GdUnitCmdTool.gd -a test/

`gdlint` and `gdformat` come from `gdtoolkit` (`pipx install gdtoolkit`).
gdUnit4 is the test runner with the best headless CLI; GUT is the alternative.

## Evidence of work

See the `evidence` format in `project.conf`; these assert that the tool did
work, not that it succeeded.

    # UNVERIFIED - Godot was not installed when this was written. The bootstrap
    # story must run each gate and correct these against real output.
    evidence | unit      | [1-9][0-9]* of [0-9]+ test.?s? *(cases)? *(passed|executed)
    evidence | lint      | [1-9][0-9]* file.? *(linted|checked)|Success: no problems found
    evidence | typecheck | -
    evidence | build     | -

Liveness matters more here than anywhere else in this harness, because the
`unit` gate is a `godot --headless -s <script> -a test/` invocation - a shape
that can silently resolve to an empty test directory, a missing addon or a
misspelled `-a` path and still exit 0. Get the `unit` regex right during the
bootstrap story by deliberately pointing `-a` at an empty directory and
confirming the gate fails.

`build` is `-` because an export prints little that is reliably countable;
verify the artefact exists as a separate acceptance criterion instead.

## What the runner can see

    # UNVERIFIED - gdUnit4's flags move between versions; check yours.
    discovery | tests | . | godot --headless --path . -s addons/gdUnit4/bin/GdUnitCmdTool.gd -a test/ | grep -qE "[1-9][0-9]* test.?s?"

This is the weakest `discovery` line of any profile here, because gdUnit4 has no
list-only mode: the only way to ask what it can see is to run it, which makes
the line a duplicate of the `unit` gate rather than an independent check. Say so
in the bootstrap story rather than pretending otherwise, and treat the `unit`
gate's `floor` as the real guard against a suite quietly shrinking.

## The coverage problem

There is no reliable line-coverage tool for GDScript. Do not fake one, and do
not silently drop the requirement. Two honest options:

- **Mark the coverage gate optional and record why** in `docs/wiki/stack.md`,
  replacing it with a stricter rule: every acceptance criterion has a named test
  that fails when that criterion is broken, checked in the PR body rather than
  by a tool.
- **Put the logic where it can be measured.** Keep simulation, generation and
  rules in a plain GDScript or Rust core with no node dependencies, cover that
  properly, and keep the scene layer thin enough to verify by integration test.

The second is strongly preferred for a world-building or simulation project: the
interesting behaviour is exactly the part that does not need a scene tree.

## What `--fast` should leave out

    slow | build | an export-release template build; RED and GREEN have no use for it

Nothing else. This profile has no `integration` or `mutation` gate, and its
`coverage` gate is unconfigured (see above), so `--fast` here is lint, typecheck
and unit. That is a smaller subset than in other stacks, and it is honest about
it: the instrumented test run that `--fast` exists to protect does not exist in
this ecosystem, which is a weakness of the profile rather than a saving.

## Layout

    src/                    game scripts
    src/core/               node-free logic - the part you test properly
    scenes/                 .tscn files
    test/                   gdUnit4 test suites, *_test.gd
    assets/                 art, audio, fonts
    project.godot           committed

## paths.conf additions

Add to the `test` section:

    test | test/**
    test | **/*_test.gd

Add to the `config` section:

    config | project.godot
    config | export_presets.cfg

## Notes for the bootstrap story

- Commit `project.godot` and `export_presets.cfg`; the export gate needs the
  preset to exist.
- Add the gdUnit4 addon and prove one real test runs headlessly in CI - the
  headless invocation is the part that breaks, so verify it early.
- `.gitignore` must exclude `.godot/`, and `.import`/`build/` artefacts.
- Scene files are effectively binary for review purposes. Keep behaviour in
  scripts so that stories produce reviewable diffs.

## Prerequisites

Three separate things, and they are easy to confuse.

**1. The Godot editor and engine.** One executable that is both the editor you
click around in and the runtime that runs your game, including headlessly in CI.

    # Windows
    winget install --id GodotEngine.GodotEngine
    # macOS
    brew install --cask godot
    # Linux: download from godotengine.org, or use your distro package

The gate commands call it as `godot`. On Windows the installed executable may be
named something like `Godot_v4.x-stable_win64.exe` and not be on PATH - either
add it to PATH under that name, or write the full path into `project.conf`. Do
one of those before the bootstrap story, or every gate will fail with "command
not found".

Verify: `godot --version` prints 4.x.

**2. gdUnit4, the test runner.** A Godot addon, installed into the project
rather than onto the machine: get it from the Godot Asset Library inside the
editor, or copy the release into `addons/gdUnit4/`. It is committed with the
project, so this is a one-time step the bootstrap story does.

Verify: the headless command in the `unit` gate runs and reports zero tests
before any exist.

**3. gdtoolkit, the linter and formatter.** Python tooling, so it needs Python -
the only reason this profile touches Python at all.

    uv tool install "gdtoolkit==4.*"
    # or: pipx install "gdtoolkit==4.*"

Verify: `gdlint --version`, `gdformat --version`.

If you would rather not install Python for this, drop `gdlint` and make the
`lint` gate `godot --headless --check-only --quit --path .`, which catches
syntax and static type errors but not style. Record the choice in
`docs/wiki/stack.md` rather than leaving the gate silently weaker.

**If the project uses C# instead of GDScript**, you also need the .NET SDK
(`winget install --id Microsoft.DotNet.SDK.8`) and the .NET build of Godot - and
in exchange you get real line coverage through `coverlet`, which is the main
argument for taking that route.
