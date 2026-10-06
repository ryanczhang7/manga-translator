# Path ownership

Each agent owns a slice of the tree. The phase lock enforces the *phase*
dimension of this automatically. The *role* dimension is honoured by the agents
themselves: nothing checks which agent wrote a file. What CI checks, in
`scripts/check-boundaries.sh`, is the commit - source arrives with tests or a
scaffold inventory, the phase and criteria in the committed story, the gate
record against the tree.

| Agent | Writes | Never writes |
|---|---|---|
| **Lead PO** | `docs/wiki/**`, `docs/backlog/**`, `.claude/harness/project.conf` | any source or test file |
| **Test Developer** | test paths (see `paths.conf`), the story's `## Test plan`, `## Handoff` and `## Regressions` | production source, config |
| **Feature Developer** | source and config paths, the story's `## Gate probes` (`## Gate results` is written by `gates.sh`, by nobody else) | any test file |
| **Lead Designer** | `docs/wiki/design/**`, the story's `## Design notes` | source, tests, config |
| **Mutation Tester** | `docs/wiki/audits/**`, new story files | source, tests, config |

**The bootstrap exception.** A `bootstrap` story - and a `chore` that uses
SCAFFOLD - is one indivisible derivation: the test runner, the configuration,
the scaffold and the gate commands all depend on each other, and none of them
can be written test-first before the others exist. So the Lead PO drives it and
writes source, tests and config directly, under SCAFFOLD. That is the only time
the Lead PO writes outside docs and `project.conf`, and it is not free: every
production file written must be named in the story's `## Scaffold inventory`,
with the test that covers it, and `check-boundaries.sh` refuses the PR if a
changed source file is missing from that list. A table that quietly contradicts
the command that invokes it teaches agents the table is advisory; this
paragraph is here so that it does not.

**`.gitignore` has no single owner.** It classifies as `harness`, so the lock
permits it in every phase, and that is deliberate: whoever introduces a tool
that writes into the tree adds the line for its output, in the phase they
discover it - the Test Developer in RED for a test runner's scratch directory,
the Feature Developer in GREEN for a build artefact, the Lead PO during
bootstrap. Ignoring *generated* output is never a phase violation, and it now
has a second effect: `git check-ignore` is what makes the phase lock classify a
path as `ignored` rather than `source`. Every other edit to it - ignoring
something authored, a secret, or a committed artefact - belongs to the Lead PO.

**Portability.** Harness scripts, hooks and skill examples stay in bash, awk and
coreutils. Do not reach for python: on Windows a bare `python` hits the
Microsoft Store alias shim and exits 49 without running anything, so a script
that depends on it fails on a machine where python is genuinely installed.
Node is available only once a stack has chosen it, which the harness cannot
assume.

Categories are decided by `.claude/harness/paths.conf`, not by intuition. To see
how a path is classified:

```bash
bash scripts/classify.sh src/app/main.ts
```

**A test that needs this answer asks for it; it does not reimplement it.** A
guard asserting a property of every source module - no module-level constant of
some shape, no import crossing some boundary - needs to know which files count,
and the answer is the one the phase lock uses:

```bash
bash scripts/classify.sh --list source src     # every source file under src/
bash scripts/classify.sh --only test PATH...   # filter a list you already have
```

It enumerates through git, so a module written five minutes ago and not yet
committed is still returned, and build output is not. The alternative is each
guard carrying its own regex for "a source module", and that is not
hypothetical: four private copies in one project drifted apart and spent six
stories returning **probe artifacts** as production source - deliberately
offending files a guard writes to test a lint rule - asserting real properties
over files written to violate a rule, and passing only because the rule violated
was not the rule being asserted.

Probes are why `paths.conf` has a `__probe_` convention. A guard that tests a
*rule* rather than today's code has to write an offending module and run the real
tool over it, under the **real** path, because lint overrides are path-scoped and
a probe linted from a temp directory is linted under the wrong rules. Name it
`__probe_*.*` or `__*_probe.*` and one rule makes both the scanner and the lock
agree: the scanner skips it, and RED may write it, because it classifies as
`test`. The leading `__` is deliberate - matching `*_probe.*` would make a real
`heat_probe.ts` invisible to every guard, which is the same defect pointing the
other way.

# The model each agent runs on

Every definition in `.claude/agents/` declares `model:`, so which model a role
runs on is a fact of the harness rather than of whoever's session dispatched it.
The roles split by kind of work, and that is a decision rather than a default:
the planning roles (`lead-po`, `lead-designer`) and the orchestrating commands
declare `fable`; the roles that write or judge tests (`test-developer`,
`feature-developer`, `mutation-tester`) declare `opus`. The user's judgement
since release 78 is that Opus 5.5 is the stronger model for development and
testing and Fable for planning, architecture and running a multi-stage
workflow. Until then all five said `opus`, with `fable` used only as the weaker
model in RED - resting on the one controlled measurement this harness has, that
a partitioned RED brief on the weaker model produced sharper negative controls
than the stronger model without it. What survives that change is the
asymmetry: GREEN and GATES stay on the model judged stronger at the work,
because a weaker model's failure there is precisely the one this harness exists
to prevent, reaching green by weakening a test.

Change it deliberately, per role, and record the decision and the outcome. What
you may not do is leave it unstated: a session setting or an explicit override
can still win, and the orchestrator cannot see which did. Two stories once
compared "the default model" against a stronger one, and neither could say what
"default" had resolved to - so the comparison may have been the stronger model
against itself. Hence the other half of the rule: **`lead-po` records the
resolved model of every dispatch, by name, in the story.**

**The per-phase plan is `.claude/harness/models.conf`, not a judgement made
fresh each story.** `bash scripts/plan.sh write <id>` renders it into the
story's `## Model guidance` at the end of PLANNED, once the contract exists. Its
rows split by kind of work, as above: PLANNED and REVIEW on `fable`, every phase
that writes or tests code on `opus`, with no row moving with the story. GREEN
and GATES never move to a model judged weaker at the work, because a weaker
model's failure there is reaching green by weakening a test. A story that wants
a different answer says
so in its own `## Model guidance` with a success condition that could come out
either way - it does not edit the policy file. And the plan is still not the
record: what each dispatch RESOLVED to goes in underneath it, by name.

# Phase permissions

| Phase | May write | Meaning |
|---|---|---|
| any | vendor, ignored | installed dependencies, build output, and anything the project's `.gitignore` covers — generated, not authored |
| `PLANNED` | docs, harness | story is being written |
| `RED` | test, manifest, docs, harness | failing tests only; source frozen. The manifest is writable for **test** dependencies only — see below |
| `GREEN` | source, config, manifest, docs, harness | make them pass; tests frozen |
| `GATES` | source, config, manifest, docs, harness | fix lint/type/build; tests frozen |
| `REVIEW` | docs, harness | PR is open |
| `SCAFFOLD` | everything | bootstrap/chore stories only; every source file named in `## Scaffold inventory` |
| `DONE` | docs, harness | closed |

No active story means no restrictions. The lock protects a cycle in flight; it
is not a general permission system.

**RED may declare a test dependency, and only a test dependency.** A failing
test routinely needs one — a temp-directory crate, an async `pytest` plugin, a
snapshot matcher — and every ecosystem declares it in the same file as the
production dependencies. So dependency manifests are their own category,
`manifest`, and RED can write them; `config` stays frozen, because a build
config or a container definition is production surface.

The lock cannot tell a test dependency from a production one — it sees a path,
never a diff — so `check-boundaries.sh` reads the commit instead. For every
commit whose committed story says `phase: RED`, it deletes the dev-dependency
block from both sides of the manifest and requires what is left to be identical.
A production dependency added in RED is refused, and so is bumping one: that
changes what production code resolves to, from the phase that may not write
production code. It has to be per-commit, because by the time a PR exists the
story says REVIEW and the merged diff cannot say which phase added which line.

Two limits worth knowing before you meet them:

- **Lockfiles are permitted unchecked.** They have no dev/production split to
  read. That is sound only because the manifest they follow from *is* checked: a
  dependency nobody declared cannot be used.
- **Some ecosystems have no in-file split at all** — `go.mod`, `requirements.txt`,
  `*.csproj`. They stay `config`, so RED cannot add a test dependency there.
  That is the documented excursion below, not a bug to route around.

**When RED needs something the manifest cannot carry, it stops and says so.**
The orchestrator changes phase deliberately, the dependency goes in, and the
story records why. What RED does *not* do is meet a refusal and reach for a
different tool — that is law 5, and a refusal with no sanctioned next step is
exactly the condition under which an agent invents one.

**A gate failure whose only legal fix is a write the current phase forbids is a
return to RED, not a reason to route around the lock.** The return is usually
described as "a test is wrong", and that is only the common case. The general
one is this table: GREEN and GATES both freeze test files, and a `format` or
`lint` gate can fail on a test file the story itself added - a one-line reflow to
satisfy a line-width rule, with the assertion entirely correct. GATES is the
phase whose stated job is fixing lint and build failures, and it is the phase
that cannot fix that one. Set the phase back to RED, make the single change,
record why in `## Regressions`, and come back. Do not document a whitespace
failure as an expected WARN, and do not reach for a tool the lock does not
inspect.

# Non-negotiables

- A test that has never been observed to fail is not a test. Run it in RED and
  record the failure output in the story's `## Handoff`.
- **That is a property of the assertion, not of the phase or the run.** An
  ordinary RED satisfies it as a side effect - the implementation does not
  exist, so everything is red. Two situations look identical from outside and
  satisfy nothing:
  - a test **written or corrected while the implementation already exists** -
    on a return to RED, or against a module an earlier story built. It passes
    on its first execution and passes forever; it could assert nothing at all
    and nothing would notice. Earn it by mutating the specific production
    behaviour it claims to pin, watching that one assertion go red, reverting,
    and pasting the output into `## Regressions`. One mutation, one run, one
    revert — and the mutation goes through `bash scripts/mutate.sh FILE 'EXPR'
    -- COMMAND`, which is allowed in every phase because it restores the file
    and verifies the restore. `sed -i` here is working around the lock.
  - a suite that fails at **import**, where no assertion in the file has run.
    Negative controls - the cases that make a threshold mean something - are
    unverified for the whole of RED. Record each control's expected value in
    the handoff and have GREEN confirm the measured one.
  `check-boundaries.sh` refuses a PR whose `## Regressions` or `## Gate probes`
  describes a failure without showing one.
- A gate that has never been observed to fail is not a gate. When a story adds
  or changes one, break what it guards, watch it fail, and record that in the
  story's `## Gate probes`. Exit 0 means only that the tool did not complain,
  and a tool with nothing to do does not complain.
- **An assertion's needle is part of the assertion, and a needle that cannot
  fail is a test that cannot fail.** The corollary of the first rule at the
  level of the string, and it does not announce itself: the assertion has a
  sharp name, runs, and passes, and what it matched is not what it claims.
  Four in one day, across two repositories:
  - `"a lockfile is permitted unchecked"` asserted the **absence** of one
    message, so a lockfile refused with a *different* message satisfied it.
  - `"the base ref expression is resolved"` was satisfied by the skip note
    **announcing that resolution had failed** - the note quotes the unresolved
    command, so the needle appeared precisely because the substitution broke.
  - a needle of `PLAUSIBLE: sed -i option` is satisfied by
    `IMPLAUSIBLE: sed -i option` - the string that means the opposite.
  - `grep '^ci-local:'`, used to detect a CI run finishing, matched
    `ci-local: 15 passed, 0 failed` - that **suite's** result inside the run,
    not the **script's** verdict. It was one line of shell in a waiting loop
    and its failure mode was to report a run green.
  Three defences, cheapest first: anchor the match (`grep -cx`, `^…$`) rather
  than letting it float; prefer a needle whose negation is not also a match;
  and where neither is available, probe it by mutating the thing it claims to
  pin. Only the third catches the third case.
  **This does not respect the boundary between the code under test and the
  instrument reading it** - and the instrument is the side with no discipline
  pointed at it. A one-line `grep` standing between you and "is it green?" is
  load-bearing whether or not it looks it.
- **A rule is probed against the tree it judges, not only against fixtures you
  wrote.** The needle rule above asks what an assertion MATCHED. This asks what
  it was POINTED AT, and it is the harder one to notice, because the suite is
  green either way and the coverage number does not move.
  A guard's probe corpus is written by whoever wrote the rule, from the same
  reading of the problem, usually from the worked example in its own header. So
  it encodes the same blind spot twice and agrees with itself: every assertion
  passes while the rule cannot see the spelling the real tree actually uses.
  Three in one round, in this repository, all in guards whose suites were green:
  - `check-grep-count.sh` was probed with `y=$(grep -c …)` throughout, because
    that is the shape its header explains. It could not see
    `x="$(grep -c …)"` - which is how every real instance in the tree is
    written - and the suite had nothing to say about it.
  - the same guard could not see `cat f | grep -c x || printf 0`, judging `cat`
    rather than the grep. A consuming project had wired it into CI where all
    three uses are pipelines: the run was green and meant nothing.
  - `check-sigpipe.sh` read a here-string as a heredoc opener and went blind
    from that line to the end of the file - past line 108 of `plan.sh`, and in
    18 of this tree's 38 harness shell files. Its census line kept reporting
    the honest file count while the coverage behind it was partial.
  None of the three was reachable from the fixtures. All three were found the
  same way: **mutate a REAL line of the tree with `scripts/mutate.sh` and watch
  whether the guard fires.** The first of them broke the phase lock, and the
  probe found it in a guard that had nothing to do with the lock.
  So a story that adds or changes a rule over the tree carries a probe against a
  real line of that tree, alongside its fixtures - recorded in `## Gate probes`,
  or beside the deferred verification that owns it when the probe is a control
  some later phase has to run. `check-boundaries.sh` validates both sections and
  demands pasted output from either, so the choice is about which one owns the
  result, not about how much evidence is required. A result counts only as a
  block: a line beginning with three backticks or three tildes (a fence), or a
  line indented by exactly four spaces. Prose does not count, nor inline code in
  backticks, nor a tab, nor anything inside an HTML comment. Say which, rather
  than letting the probe want to live in two places at once.
  The fixtures say the rule is right about what you imagined; only this says it
  is right about what is there. A fixture corpus that has never met the real
  tree is a statement about your own understanding, and it is always green.
  **This is law rather than a comment beside the mechanism for a measured
  reason.** The warning about it was written into `lib.sh` in release 38, next
  to the helper it was about - and its author then committed the same defect in
  release 40, in the guard that note describes. Writing a caveat where the
  mechanism lives does not make the next person check the right property, and
  the next person includes whoever wrote the caveat.
- Do not weaken an assertion, add a `skip`, widen a tolerance, or delete a case
  to reach green. Any of these means going back to RED. The same applies to a
  gate: do not delete an `evidence` line, drop `--workspace`, or add
  `--passWithNoTests` to make a gate stop complaining.
- **Narrowing an input domain can be correct; loosening a comparison is always a
  weakening.** In a property test the input lives in a generator, not in the
  assertion, so a fifth move exists that is none of the four above: change what
  is generated. A generator is part of the *specification* - it is the domain the
  criterion claims to hold over - and narrowing it is legitimate exactly when the
  design cannot represent what was excluded, named against the document that
  fixes that. "The test was failing" is not a reason. The two moves are one line
  each and look identical in a diff: a round-trip property failing on a negative
  zero is fixed either by keeping `-0` out of the coordinate generator (correct -
  JSON cannot carry it) or by making the comparison treat `-0` and `0` as equal
  (which stops it distinguishing values for **every number in the document**, and
  is easier, because it is a one-line edit in the file the failure is reported
  in). So a narrowing carries three things: the design clause that excludes the
  value, the limit recorded in the architecture document rather than only in a
  comment, and a mutation showing the property still fails against a lossy
  implementation. `tdd-cycle` has the worked case.
- Acceptance criteria are frozen once a story leaves PLANNED, for the same
  reason tests are frozen during GREEN: they are what the tests are for. If one
  is wrong or unsatisfiable, stop, put it to the product owner, and record the
  change under `## Amendments` - which AC, what it said, what it says now, who
  approved it and why. `check-boundaries.sh` fails a PR whose criteria differ
  from their last committed PLANNED state (else the base branch) without an
  entry there.
- `## Gate results` is written by `scripts/gates.sh`, never by hand. It carries
  the commit and a hash of the code the gates ran against, and
  `check-boundaries.sh` refuses a PR where that hash does not match the code
  being merged. A pasted summary is not evidence of anything.
- `depends_on` and `branch` in a story's frontmatter are enforced by
  `phase.sh set`, which refuses to move a story past PLANNED while a dependency
  is not DONE or the checkout is on the wrong branch. `--force` overrides
  either, and prints that it did; record why in `## Notes`.
- Do not commit `.claude/state/**`. It is machine-local: `current-story.env` from
  `phase.sh`, `last-gate-run` and `gate-logs/` from `gates.sh`,
  `mutations/` (backups and a log) from `mutate.sh`, and the guard's
  `phase-guard-declined.log`. Two of those are denied to `Write`, `Edit` and
  `MultiEdit` in `settings.json` because their contents are read as evidence - the
  phase and the gate stamp - and `.claude/state/README.md` says which, in a column
  `.claude/tests/settings.test.sh` checks against the rules in both directions. A
  new state file belongs in that table, with a yes or no, or the suite fails. A
  `.bak` left behind under `mutations/` means a
  restore failed and `mutate.sh` exited 90 saying so; everything else it cleans
  up. A `.active` left behind means a mutation was killed or not restored, and
  `gates.sh` refuses to run until `bash scripts/mutate.sh --check` is clean.
  The backup path is explicit rather than `$TMPDIR` because that variable is
  unset in some of the shells this harness runs in, and a mutation whose backup
  went nowhere once left its restore depending on the `sed` expression happening
  to be an exact inverse of a single-occurrence match.
- Agentic scaffolding (`.claude/`, `docs/`, `scripts/`, `.github/`) never ships
  in a production image. Keep `.dockerignore` honest.

# Mutation work per story

The non-negotiables above say when a mutation is *owed*. This says how much a
story spends by default, because nothing else bounds it: on HARNESS-014 the
mutation work was 18 mutations, about 27 full-suite runs and 2h20 of a 7.5h
story, and none of the 18 found a defect. This section is the one place the
budget is stated; every command, skill and template defers to it.

- **Required per story.** One mutation that earns each test written or
  corrected against code that already exists, and, for a story that changes a
  rule over the tree, one probe against a real line of that tree - both the
  unchanged law above. Plus, for the story's central claim, one "defect put
  back" mutation: reintroduce the defect the story exists to remove and watch
  the assertion that pins it go red. A format or codec story may add one more,
  a wrong *value* rather than a missing field (`tdd-cycle` has the case).
- **How a mutation runs.** Through `scripts/mutate.sh`, against the one suite -
  or the narrowest test command - that holds the assertion it targets. Never
  the full suite per mutation.
- **Not per story.** Exhaustively earning every assertion that passed on
  arrival, verifying a handoff's whole mutation table, and the `mutation` gate
  (which every stack profile marks `ondemand`). Those belong to
  `/audit-mutations`, which runs on request, and which `/advance-story`
  recommends - never runs - when a story closes the last open story of its
  epic.

This is a default the PO writes into `## Deferred verifications` and the
orchestrator runs, not a cap: `check-boundaries.sh` does not count entries, and
a story with a real reason for more writes them and says why.

# Reporting to the user

This is about the messages the orchestrator writes to the person in chat: at
the end of a phase, a story, a plan or a status check. The user reads them to
decide what to do next, often between other things, so build them for that.

- **Lead with the outcome.** The first line says what is now true: the phase
  the story reached, the PR that is open, the gate that failed. No preamble,
  no recap of the request, no closing pleasantries.
- **One next action, last.** End with exactly one concrete thing to do, a
  command to type or a decision to make, taken from the script that knows:
  `bash scripts/plan.sh after <id>` once a story closes,
  `bash scripts/plan.sh <id>` while it is in flight. Do not end by asking
  the user what they want to do; if the script's answer is wrong, say why and
  give yours. Steps the user must take themselves are a numbered list, in
  order.
- **Plain words.** Say things the way the user would: "the new tests fail the
  way they should", not "RED complete, handoff written". Phase names, law
  numbers, section names and rule cross-references appear only when the user
  needs one to make a decision, and then with half a line saying what it
  means.
- **Working notes stay in the story.** What you read or skipped, which rule
  you followed, and caveats about your own process belong in the story file,
  where the next agent needs them. The user gets the result and whatever they
  must act on or know in order to trust it.
- **Evidence, not a diagnosis.** When something fails, say what failed and
  point at the evidence: the failing assertion, the command, its output or
  the log path. State a cause only when the evidence shows it. "Cause not yet
  known" is a finding. A cause made up to fit a "cause, then fix" template is
  the failure this rule exists to prevent.
- **Five items, then offer the rest.** Keep any visible list to about five
  items. Anything beyond that, and any tangent you noticed, goes in one line
  offering it, placed before the next action rather than after it.
- **Agent-to-agent artefacts are exempt.** Story files (`## Handoff`,
  `## Regressions`, `## Notes`, `## Gate probes`), audits under
  `docs/wiki/audits/`, and a subagent's report to the orchestrator need to be
  complete, not short. Nothing here shortens them. The message to the user
  can be short *because* they are complete.
