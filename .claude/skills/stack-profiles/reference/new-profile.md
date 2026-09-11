# Writing a profile for a new stack

When `/plan-product` chooses an ecosystem the harness has not seen, write a
profile file in this directory before the bootstrap story starts. The bootstrap
story will depend on it, and so will every story after that.

## What a profile must contain

1. **Gate commands**, one line each in `project.conf` format, for every gate the
   ecosystem can support. Non-interactive, non-watching, exit-code-honest.
2. **Evidence of work** - an `evidence` line per gate, asserting that the tool
   observably did something. See below; this section is not optional.
3. **The coverage story.** Name the tool and how the threshold is enforced. If
   the ecosystem has no coverage tooling, say so explicitly and say what replaces
   it - never leave it implied.
3b. **A `discovery` command per place tests are expected to live** - the command
   that asks the runner what it can see (`vitest list`,
   `pytest --collect-only`, `cargo test --workspace --no-run`), and what its
   output looks like when a directory has silently fallen out of scope. Every
   ecosystem has a way for a suite to vanish while the run stays green; name
   this one's. Where the runner reports a count, say whether a `floor` line can
   read it - i.e. whether the evidence regex covers the whole number.
3c. **Which gates `--fast` should leave out**, as `slow` lines with reasons, and
   - the part that is easy to get wrong - which slow-looking gate must stay in.
   The instrumented test run belongs in the fast subset however slow it is:
   it is the command that judges the tests, and keeping it out of RED and GREEN
   is exactly how a suite reaches CI having never been measured under it. Note
   too whether this ecosystem's default test timeout is measured against the
   plain run rather than the instrumented one; most are.
4. **Layout** - where production code, tests and configuration live.
5. **`paths.conf` additions** - the globs that make the phase lock classify this
   stack's files correctly. Get this right or the lock will block the wrong
   writes and the agents will learn to distrust it.
6. **Bootstrap notes** - what the first story must produce, and which step is
   most likely to break.
7. **Testing notes** - the idiomatic runner, the assertion style, how to fake
   time and randomness, and which kinds of test are theatre in this ecosystem.

## These rules are enforced

`.claude/tests/profiles.test.sh` checks every profile in this directory against
the list above, and `scripts/selftest.sh` runs it in CI. A profile is any file
here carrying a `gate |` line, so a new one is picked up the moment it is
written - there is no list to add yourself to.

It asserts what `gates.sh --audit` asserts about a real `project.conf`, because
a profile is copied verbatim into one: every required gate is configured; every
required gate with a command has an `evidence` line; no `evidence`, `floor` or
`slow` line names a gate the profile does not configure; every `floor` has an
evidence line to measure out of; every `slow` line carries a reason; the
`## What --fast should leave out` section exists; and there is at least one
`discovery` line.

This suite exists because the rules above went unenforced and drifted within a
single round: the change that added the `--fast` requirement left four of the
five shipped profiles violating it, and three had been missing the `discovery`
requirement since it was written. A requirement that only the template knows
about is a suggestion.

## Verify before you rely on it

Run every command you write down, in this repository, before the bootstrap story
starts. A profile is documentation of something that works, not a plausible
guess at command-line flags. Versions move, flags get renamed, and an agent with
an empty context will trust this file completely.

Where you genuinely cannot - the toolchain is not installed on this machine -
mark the lines `# UNVERIFIED` and say what the bootstrap story must do about it.
A guess labelled as a guess is useful; a guess presented as fact is the thing
that poisons every story after it.

## Writing the evidence lines

For each gate, run its command in a state where **it has no work to do**: no
test files, an empty source directory, a glob that matches nothing. Then look at
what happened.

- **Non-zero exit?** The tool is already honest. Prefer `evidence | <id> | -`
  and say in the profile why the gate is safe without one.
- **Exit 0?** Find the smallest thing in the *working* run's output that counts
  units of work, and require it to be non-zero: `[1-9]` and `[1-9][0-9]*` do
  nearly all of it. Assert volume, never success.

Two failure modes to check before writing the line down:

- **Caching.** Compilers print a per-unit line on a cold build and nothing on a
  warm one, so a "N units processed" regex fails spuriously on the second run.
  Test runners re-execute every time and are safe. Run the gate twice.
- **Flags that make a safe tool unsafe.** `--passWithNoTests` and its cousins
  exist in most runners and turn a loud vacuous case into a silent one. Never
  add one, and check the ecosystem's config file for one already set.

## Be honest about weakness

Some ecosystems have poor tooling for some gates. Say so, in the profile, with
the compensating practice - the way `godot.md` handles the absence of coverage
tooling. A profile that quietly omits a gate teaches every future story that the
gate is optional.

## Prerequisites section

Every profile must also carry a **Prerequisites** section: the runtimes and
tools that have to exist on the machine before any gate can run, with install
commands per platform and a verify command for each.

This is the section people actually need and the one most likely to be wrong.
Write the install commands you ran, not the ones the project's website
recommends. Name the executable exactly as `project.conf` will call it -
`scripts/doctor.sh` checks for that name on PATH, and a profile that says
"install Godot" without saying the binary must be callable as `godot` will send
someone hunting for an hour.
