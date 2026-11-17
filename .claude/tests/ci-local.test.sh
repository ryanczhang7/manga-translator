#!/usr/bin/env bash
# Tests for scripts/ci-local.sh - the local run of what CI runs.
#
# The script's whole value is that it is the SAME sequence, and that is exactly
# the property that rots: somebody adds a step to gates.yml, nobody adds it here,
# and a green local run starts meaning less than it says. So the load-bearing
# test is not "does it work" - it is "does it still agree with the workflows",
# derived from the workflow files rather than from a list copied out of them.
#
# The other half is fail-fast. A runner stops a job at the first failing step;
# a script that carries on and prints a summary at the end can report four
# passes under a failure, which is the one thing a CI substitute must not do.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

SCRIPT="$REPO_ROOT/scripts/ci-local.sh"
WF="$REPO_ROOT/.github/workflows"

# ---------------------------------------------------------------------------
describe "it runs what the workflows run"

# --dry-run prints the commands and executes none of them, which is what makes
# this checkable at all: the alternative is running the real suite to find out
# what it would have run.
dry="$( bash "$SCRIPT" --dry-run 2>&1 )"
assert_eq "--dry-run succeeds" 0 "$?"


# The script must RUN what the workflows say, and the only way to guarantee that
# in a project whose workflows this repository does not control is to read them.
#
# The first version hardcoded five steps and this test asserted they matched the
# workflow files. In THIS repository they matched by construction, so the test
# passed and looked meaningful. In a consuming project the workflow legitimately
# gains `pnpm install --frozen-lockfile` and `pnpm exec playwright install`, and
# the assertion then failed permanently, in a suite nobody could make green - the
# precise shape of red that teaches people to stop reading test output.
#
# So: derive. These assert the derivation, not a list.
missing=""
while IFS= read -r cmd; do
  [ -z "$cmd" ] && continue
  case "$cmd" in *'${{'*) continue ;; esac
  # awk over a here-string, not `printf | grep -qF`. `grep -qF` leaves at its
  # first match, the printf behind it dies of SIGPIPE, and pipefail promotes 141
  # to the status this `||` reads - so a command that IS in the script is
  # reported missing. index() is the same literal-substring test grep -F does.
  # WORLD-086 R-1.
  awk 'BEGIN { n = ARGV[1]; ARGV[1] = "" } index($0, n) { h = 1 } END { exit !h }' \
    "$cmd" <<<"$dry" || missing="$missing
  $cmd"
# Both spellings. This derivation reads THIS repository's workflows, and every
# one of them happens to use the two-line `name:` / `run:` form - so a grep for
# `^run:` derived a complete list here and would have under-derived in any
# project writing the compact `- run: cmd`. The script had the identical blind
# spot in its own parser, which is why neither side caught it: the test and the
# code were wrong in the same direction.
done <<< "$(grep -hE '^[[:space:]]*(-[[:space:]]+)?run:' "$WF"/gates.yml "$WF"/boundaries.yml \
             | sed -E 's/^[[:space:]]*(-[[:space:]]+)?run:[[:space:]]*//')"
assert_eq "every workflow step appears in the script" "" "$missing"

# ---------------------------------------------------------------------------
describe "a project whose workflow has its own steps"

# The regression. A consuming project adds toolchain setup to gates.yml; those
# steps ARE part of what CI runs, so a local stand-in that skips them is not a
# stand-in. Nothing here may be specific to this repository's own five commands.
PFIX="$(make_project_fixture)"
mkdir -p "$PFIX/.github/workflows"
cat > "$PFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Install npm dependencies
        run: pnpm install --frozen-lockfile
      - name: Install Playwright Chromium
        run: pnpm exec playwright install --with-deps chromium
      - name: Run gates
        run: bash scripts/gates.sh
YML
cat > "$PFIX/.github/workflows/boundaries.yml" <<'YML'
name: boundaries
on: [pull_request]
jobs:
  boundaries:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Check agent boundaries
        run: bash scripts/check-boundaries.sh origin/${{ github.base_ref }}
YML
pdry="$( cd "$PFIX" && bash scripts/ci-local.sh --dry-run 2>&1 )"
assert_contains "a project's install step is run"    "pnpm install --frozen-lockfile" "$pdry"
assert_contains "and its browser install"            "pnpm exec playwright install --with-deps chromium" "$pdry"
assert_contains "alongside the harness's own"        "bash scripts/gates.sh" "$pdry"
# The base_ref expression resolves rather than being passed through literally.
#
# STDOUT ONLY, and the whole resolved command. When the substitution fails the
# step is skipped with a note - on stderr - that quotes the command verbatim:
#   note: skipping a boundaries step this cannot resolve locally:
#     bash scripts/check-boundaries.sh origin/${{ github.base_ref }}
# so a haystack that folds stderr into stdout contains
# `bash scripts/check-boundaries.sh origin/` precisely BECAUSE resolution
# failed. Deleting the substitution outright left this assertion green and was
# caught only by the guard below - which means the thing this one names was not
# the thing it tested.
pout="$( cd "$PFIX" && bash scripts/ci-local.sh --dry-run 2>/dev/null )"
assert_contains "the base ref expression is resolved" \
  "bash scripts/check-boundaries.sh origin/main" "$pout"
case "$pdry" in
  *'${{'*) _bad "no unresolved workflow expression survives" "found one: $pdry" ;;
  *) _ok "no unresolved workflow expression survives" ;;
esac
# And nothing this repository happens to run is invented for a project that
# does not: the fixture's gates.yml has no selftest step.
case "$pdry" in
  *selftest*) _bad "it does not invent steps the workflow lacks" "selftest appeared: $pdry" ;;
  *) _ok "it does not invent steps the workflow lacks" ;;
esac

# A `run: |` block is one step spanning lines, and dropping its body would run a
# truncated command - worse than skipping it.
cat > "$PFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - name: Two things
        run: |
          bash scripts/selftest.sh
          bash scripts/gates.sh --list
YML
pdry="$( cd "$PFIX" && bash scripts/ci-local.sh --dry-run 2>&1 )"
assert_contains "a block scalar's first line"  "bash scripts/selftest.sh"     "$pdry"
assert_contains "and its second"               "bash scripts/gates.sh --list" "$pdry"
rm -rf "$PFIX"

# PR_HEAD_SHA is not decoration. Without it check-boundaries.sh hashes the
# WORKING TREE, and with it the commit - so a local run that omits it answers a
# different question from the PR check it is standing in for.
assert_contains "it sets PR_HEAD_SHA the way the workflow does" "PR_HEAD_SHA" "$(cat "$SCRIPT")"

# ---------------------------------------------------------------------------
describe "it stops at the first failing step, like a runner"

FIX="$(make_project_fixture)"
mkdir -p "$FIX/.github/workflows"
# Steps are read from the workflows now, so a fixture needs them to have any.
# selftest first, so that stubbing it red exercises the fail-fast path.
cat > "$FIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - name: Harness self-test
        run: bash scripts/selftest.sh
      - name: Run gates
        run: bash scripts/gates.sh
YML
trap 'rm -rf "$FIX"' EXIT
write_conf "$FIX" <<'CONF'
gate     | unit | required | . | printf 'Tests  3 passed (3)\n'
evidence | unit | Tests +[1-9][0-9]* passed
CONF

# The first step, stubbed red. Everything after it must not run: `gates.sh` in
# particular WRITES - it stamps .claude/state/last-gate-run - so "carried on
# after a failure" is observable rather than a matter of reading the output.
printf '#!/usr/bin/env bash\necho "stub selftest: red"\nexit 1\n' > "$FIX/scripts/selftest.sh"
rm -f "$FIX/.claude/state/last-gate-run"
out="$( cd "$FIX" && bash scripts/ci-local.sh 2>&1 )"; rc=$?
assert_eq "a failing first step fails the run" 1 "$rc"
assert_contains "and says which step failed" "selftest" "$out"
if [ -f "$FIX/.claude/state/last-gate-run" ]; then
  _bad "and does not run the steps after it" "gates.sh ran anyway: a stamp was written"
else
  _ok "and does not run the steps after it"
fi

# The failing step's own output has to survive. A wrapper that swallows it and
# prints its own verdict makes every failure a second command to reproduce.
assert_contains "the failing step's output is shown" "stub selftest: red" "$out"

# ---------------------------------------------------------------------------
describe "it says what it is about to judge, before it judges it"

# `check-boundaries.sh` judges the COMMIT, so a run started before committing
# returns a perfectly green verdict about the PREVIOUS commit - a right answer
# to a question nobody asked. I did that three times in one day while building
# this, and the information was not missing: a note already fired on a dirty
# tree, naming HEAD, and I read past it twice.
#
# Read past it for a reason worth fixing rather than remembering. The verdict
# line begins `ci-local:`, so that is what a reader greps - and the note did
# not, and only appeared when the tree happened to be dirty. The subject was
# discoverable only by reading the whole log, which is the one thing a summary
# line exists to avoid.
#
# So: the subject is announced FIRST, unconditionally, in the same shape as the
# verdict. One `grep '^ci-local:'` now returns what was judged and what the
# answer was, in that order.
SFIX="$(make_project_fixture)"
mkdir -p "$SFIX/.github/workflows"
cat > "$SFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - name: A step that passes
        run: printf 'stub: green\n'
YML
( cd "$SFIX" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a workflow" >/dev/null 2>&1 )
sout="$( cd "$SFIX" && bash scripts/ci-local.sh 2>&1 )"
shead="$(printf '%s\n' "$sout" | grep '^[[]ci-local[]]' | head -1)"
ssha="$( cd "$SFIX" && git rev-parse --short=7 HEAD )"

# Matched on the SUBJECT's own wording, not merely on `^ci-local:` carrying the
# sha. The verdict line carries it too, and while it was the only such line an
# assertion written that way passed against a script that announced nothing -
# which is what the first draft of this did.
assert_contains "the first ci-local: line names the commit being judged" \
  "judging commit $ssha" "$shead"
# Before the steps, not after them: a subject printed at the end is a subject
# you meet once the decision is already made.
first_step="$(printf '%s\n' "$sout" | grep -n 'stub: green' | head -1 | cut -d: -f1)"
subject_at="$(printf '%s\n' "$sout" | grep -n '^[[]ci-local[]]' | head -1 | cut -d: -f1)"
if [ -n "$first_step" ] && [ -n "$subject_at" ] && [ "$subject_at" -lt "$first_step" ]; then
  _ok "and says it before running anything"
else
  _bad "and says it before running anything" \
    "subject at line ${subject_at:-none}, first step at ${first_step:-none}"
fi
# Two lines, not one: the subject and the verdict, both reachable by the grep a
# reader actually types.
assert_eq "so one grep returns both the subject and the verdict" 2 \
  "$(printf '%s\n' "$sout" | grep -c '^[[]ci-local[]]')"

# The dirty-tree note carries the prefix too, for the same reason: it is about
# what is being judged, and it was previously invisible to that grep.
printf 'uncommitted\n' >> "$SFIX/docs/notes.md"
sout="$( cd "$SFIX" && bash scripts/ci-local.sh 2>&1 )"
assert_contains "and a dirty tree says so under the same prefix" \
  "[ci-local] uncommitted changes" "$sout"

# THE COLLISION THAT MADE THE SUBJECT LINE NECESSARY IN THE FIRST PLACE.
#
# The script's report and a test suite's summary had the same shape. That is not
# a coincidence to be worked around: `selftest.sh` IS one of the steps, it runs
# this script's own suite, and that suite's summary line reads
# `ci-local: 26 passed, 0 failed`. So a reader grepping the script's prefix got
# the SUITE's verdict mixed in with the SCRIPT's - and a waiting loop written
# against `^ci-local:` matched the suite's line and reported a run finished that
# had barely started. The information was right; the name was shared.
#
# The script's own voice is `[ci-local]` now, which no `summary <name>` can
# produce. The step below prints the old shape deliberately.
cat > "$SFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - name: A step whose output looks like the report
        run: printf 'ci-local: 26 passed, 0 failed\n'
YML
( cd "$SFIX" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a lookalike step" >/dev/null 2>&1 )
cout="$( cd "$SFIX" && bash scripts/ci-local.sh 2>&1 )"
assert_eq "a step that prints the old shape is not mistaken for the script" 2 \
  "$(printf '%s\n' "$cout" | grep -c '^[[]ci-local[]]')"
# And the step's output still reaches the terminal unaltered - the fix is to the
# script's own voice, not to what it shows you.
assert_contains "while its output is still shown in full" "ci-local: 26 passed, 0 failed" "$cout"
rm -rf "$SFIX"

# ---------------------------------------------------------------------------
describe "the branches that decide WHAT runs, and in WHICH order"

OFIX="$(make_project_fixture)"
mkdir -p "$OFIX/.github/workflows"

# Skipping is the honest answer for an expression this cannot resolve, and the
# two halves are separate claims: it must SAY so, and it must carry on with the
# steps it can run. Deleting the `continue` left both untested - the step would
# have been run with `${{ matrix.os }}` still in it, which is a command CI never
# ran.
cat > "$OFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/setup-${{ matrix.os }}.sh
      - run: bash scripts/gates.sh
YML
oerr="$( cd "$OFIX" && bash scripts/ci-local.sh --dry-run 2>&1 >/dev/null )"
oout="$( cd "$OFIX" && bash scripts/ci-local.sh --dry-run 2>/dev/null )"
assert_contains "an unresolvable expression is skipped OUT LOUD" "skipping a gates step" "$oerr"
assert_contains "and the note quotes what it could not resolve" 'matrix.os' "$oerr"
assert_contains "while the steps it CAN resolve still run" "bash scripts/gates.sh" "$oout"
case "$oout" in
  *'${{'*) _bad "and the unresolved step is not emitted" "it was: $oout" ;;
  *) _ok "and the unresolved step is not emitted" ;;
esac

# A folded scalar is the other block form. `run: >` joins its lines into one
# command; `run: |` keeps them separate. Narrowing the match to `|` alone left
# every assertion green and silently dropped every folded step a project wrote.
cat > "$OFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: >
          bash scripts/gates.sh
          --gate unit
YML
oout="$( cd "$OFIX" && bash scripts/ci-local.sh --dry-run 2>/dev/null )"
assert_contains "a folded scalar's body is emitted" "bash scripts/gates.sh" "$oout"
assert_contains "and so is its continuation" "--gate unit" "$oout"

# ORDER, not presence. gates.yml goes first because it carries the selftest and
# the fast checks, and there is no sense discovering a broken harness after a
# full build. Asserted by comparing the two line numbers rather than by grepping
# for gates.yml at all: the obvious mutation - dropping the line that emits it
# first - removes gates.yml from the list ENTIRELY, so a presence check would
# report the ordering broken for the wrong reason and pass a real reordering.
cat > "$OFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/selftest.sh
YML
cat > "$OFIX/.github/workflows/aaa-first-alphabetically.yml" <<'YML'
name: aaa
on: [pull_request]
jobs:
  aaa:
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/check-boundaries.sh origin/main
YML
oout="$( cd "$OFIX" && bash scripts/ci-local.sh --dry-run 2>/dev/null )"
g_at="$(printf '%s\n' "$oout" | grep -n 'scripts/selftest.sh'        | head -1 | cut -d: -f1)"
b_at="$(printf '%s\n' "$oout" | grep -n 'scripts/check-boundaries.sh' | head -1 | cut -d: -f1)"
if [ -n "$g_at" ] && [ -n "$b_at" ] && [ "$g_at" -lt "$b_at" ]; then
  _ok "gates.yml runs first even when another workflow sorts before it"
else
  _bad "gates.yml runs first even when another workflow sorts before it" \
    "gates at line ${g_at:-none}, the other at ${b_at:-none}: $oout"
fi
rm -rf "$OFIX"

# ---------------------------------------------------------------------------
describe "HARNESS-079 AC-8: a gates.yml split into two jobs is replayed, both halves, in order"

# The split `gates.sh --skip` exists for: one slow gate in a job of its own.
# Nothing in ci-local.sh knows about jobs - it reads every `run:` line in file
# order - so this should already hold. The test is here so that it is a fact
# rather than a claim: a parser that learned to stop at the first job, or to
# keep one `scripts/gates.sh` step per file, would replay half of CI and call
# it green.
SFIX="$(make_project_fixture)"
mkdir -p "$SFIX/.github/workflows"
cat > "$SFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: windows-latest
    timeout-minutes: 75
    steps:
      - uses: actions/checkout@v5
      - name: Run gates, all but integration
        run: bash scripts/gates.sh --skip integration
  integration:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v5
      - name: Run the integration gate
        run: bash scripts/gates.sh --gate integration
YML
sout="$( cd "$SFIX" && bash scripts/ci-local.sh --dry-run 2>/dev/null )"; src=$?
assert_eq "AC-8: --dry-run over a two-job gates.yml exits 0" 0 "$src"
assert_eq "AC-8: the first job's step is printed, once" 1 \
  "$(printf '%s\n' "$sout" | grep -cxF -- 'bash scripts/gates.sh --skip integration')"
assert_eq "AC-8: the second job's step is printed, once" 1 \
  "$(printf '%s\n' "$sout" | grep -cxF -- 'bash scripts/gates.sh --gate integration')"
s_at="$(printf '%s\n' "$sout" | grep -nxF -- 'bash scripts/gates.sh --skip integration' | head -1 | cut -d: -f1)"
i_at="$(printf '%s\n' "$sout" | grep -nxF -- 'bash scripts/gates.sh --gate integration' | head -1 | cut -d: -f1)"
if [ -n "$s_at" ] && [ -n "$i_at" ] && [ "$s_at" -lt "$i_at" ]; then
  _ok "AC-8: in file order, the --skip job first"
else
  _bad "AC-8: in file order, the --skip job first" "--skip at line ${s_at:-none}, --gate at ${i_at:-none}: $sout"
fi
rm -rf "$SFIX"

# ---------------------------------------------------------------------------
describe "only workflows CI runs on a pull request"

# HARNESS-100 (ported from clean_calendar HARNESS-052). The script's claim is
# "what PR CI runs", and it read every *.yml. A deploy workflow - push to main,
# workflow_dispatch, plain-shell steps, the shape of upstream's own
# deploy.yml.template once renamed as its header says - would then be RUN from
# a developer's machine. So a workflow contributes steps only when its `on:`
# names `pull_request`.
#
# Each step touches its own marker, so the dry listing and the real run are
# checked against the same names. Matched as WHOLE lines, not substrings: the
# listing is one command per line, and `touch .m-both` floating inside a longer
# line is not a step being listed. Through awk over a here-string, never
# `printf | grep -q`, which a pipefail SIGPIPE can turn into a false miss.
has_line() { # <exact line> <haystack>
  awk 'BEGIN { n = ARGV[1]; ARGV[1] = "" } $0 == n { h = 1 } END { exit !h }' "$1" <<<"$2"
}
has_text() { # <substring> <haystack>
  awk 'BEGIN { n = ARGV[1]; ARGV[1] = "" } index($0, n) { h = 1 } END { exit !h }' "$1" <<<"$2"
}

TFIX="$(make_project_fixture)"
mkdir -p "$TFIX/.github/workflows"
# The real gates.yml's shape: a block mapping, pull_request among other events.
cat > "$TFIX/.github/workflows/gates.yml" <<'YML'
name: gates
on:
  pull_request:
  # a comment between the events
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: touch .m-gates
YML
# deploy.yml.template's shape: push to main and a manual trigger, nothing else.
cat > "$TFIX/.github/workflows/deploy.yml" <<'YML'
name: deploy
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - run: touch .m-deploy
YML
cat > "$TFIX/.github/workflows/both.yml" <<'YML'
name: both
on: [push, pull_request]
jobs:
  both:
    runs-on: ubuntu-latest
    steps:
      - run: touch .m-both
YML
cat > "$TFIX/.github/workflows/bare.yml" <<'YML'
name: bare
on: pull_request
jobs:
  bare:
    runs-on: ubuntu-latest
    steps:
      - run: touch .m-bare
YML
# The negative control for a filter that greps the file for the word: every
# mention of pull_request here is outside `on:`.
cat > "$TFIX/.github/workflows/release.yml" <<'YML'
name: release
# Not run on pull_request: releases happen from main only.
on:
  push:
    branches: [main]
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Only when not a pull_request
        if: github.event_name != 'pull_request'
        run: touch .m-release
YML
# The negative control for a filter that matches pull_request as a PREFIX.
# pull_request_target runs the BASE branch's code, so it is not what this PR
# runs. Two files, because the inline and the block spellings are read by
# different branches of a filter and each can be wrong on its own.
cat > "$TFIX/.github/workflows/target.yml" <<'YML'
name: target
on: [pull_request_target]
jobs:
  target:
    runs-on: ubuntu-latest
    steps:
      - run: touch .m-target
YML
cat > "$TFIX/.github/workflows/target-block.yml" <<'YML'
name: target-block
on:
  pull_request_target:
jobs:
  targetblock:
    runs-on: ubuntu-latest
    steps:
      - run: touch .m-targetblock
YML
# R-1: a block SEQUENCE under `on:` written in column 0. Valid YAML, accepted
# by GitHub, and the unindented layout of the `- pull_request` shape the filter
# already reads - so a filter that ends the block at the first column-0 line
# drops this workflow and the run still reports green.
cat > "$TFIX/.github/workflows/compact.yml" <<'YML'
name: compact
on:
- pull_request
- workflow_dispatch
jobs:
  compact:
    runs-on: ubuntu-latest
    steps:
    - run: touch .m-compact
YML
# Its negative control: the same layout holding only `- push`, then `jobs:`
# whose own column-0 sequence mentions pull_request (the shape the diff review
# measured; a parsing control, not a runnable workflow). A filter that never
# lets a column-0 line end the block reads past `jobs:` as part of `on:` and
# lists it. The mention has to be in column 0: an indented one is skipped by
# the first-indentation rule whatever ends the block, so it would control
# nothing.
cat > "$TFIX/.github/workflows/compact-push.yml" <<'YML'
name: compact-push
on:
- push
jobs:
- pull_request
- run: touch .m-compact-push
YML

tout="$( cd "$TFIX" && bash scripts/ci-local.sh --dry-run 2>/dev/null )"
terr="$( cd "$TFIX" && bash scripts/ci-local.sh --dry-run 2>&1 >/dev/null )"

# AC-1
if has_line "touch .m-gates" "$tout"; then _ok "AC-1: a block on: with pull_request among other events is listed"
else _bad "AC-1: a block on: with pull_request among other events is listed" "stdout: $tout"; fi
if has_text "m-deploy" "$tout"; then _bad "AC-1: a push-only workflow's step is not listed" "stdout: $tout"
else _ok "AC-1: a push-only workflow's step is not listed"; fi
# AC-3
if has_line "touch .m-both" "$tout"; then _ok "AC-3: on: [push, pull_request] is listed"
else _bad "AC-3: on: [push, pull_request] is listed" "stdout: $tout"; fi
# AC-4
if has_line "touch .m-bare" "$tout"; then _ok "AC-4: a bare on: pull_request is listed"
else _bad "AC-4: a bare on: pull_request is listed" "stdout: $tout"; fi
# AC-5
if has_text "m-release" "$tout"; then _bad "AC-5: pull_request mentioned outside on: does not count" "stdout: $tout"
else _ok "AC-5: pull_request mentioned outside on: does not count"; fi
# AC-6
if has_line "note: not running deploy.yml: it does not trigger on pull_request" "$terr"; then
  _ok "AC-6: an excluded workflow is named on stderr"
else _bad "AC-6: an excluded workflow is named on stderr" "stderr: $terr"; fi
if has_line "note: not running release.yml: it does not trigger on pull_request" "$terr"; then
  _ok "AC-6: so is the one that only mentions pull_request"
else _bad "AC-6: so is the one that only mentions pull_request" "stderr: $terr"; fi
if has_text "not running gates.yml" "$terr"; then _bad "AC-6: an included workflow is not reported excluded" "stderr: $terr"
else _ok "AC-6: an included workflow is not reported excluded"; fi
# AC-8
if has_line "touch .m-target" "$tout"; then _bad "AC-8: on: [pull_request_target] is not listed" "stdout: $tout"
else _ok "AC-8: on: [pull_request_target] is not listed"; fi
if has_line "touch .m-targetblock" "$tout"; then _bad "AC-8: a block on: holding only pull_request_target: is not listed" "stdout: $tout"
else _ok "AC-8: a block on: holding only pull_request_target: is not listed"; fi
if has_line "note: not running target.yml: it does not trigger on pull_request" "$terr"; then
  _ok "AC-8: the inline pull_request_target workflow is named on stderr"
else _bad "AC-8: the inline pull_request_target workflow is named on stderr" "stderr: $terr"; fi
if has_line "note: not running target-block.yml: it does not trigger on pull_request" "$terr"; then
  _ok "AC-8: the block pull_request_target workflow is named on stderr"
else _bad "AC-8: the block pull_request_target workflow is named on stderr" "stderr: $terr"; fi
# R-1: the column-0 block sequence
if has_line "touch .m-compact" "$tout"; then _ok "R-1: an on: sequence written in column 0 holding - pull_request is listed"
else _bad "R-1: an on: sequence written in column 0 holding - pull_request is listed" "stdout: $tout"; fi
if has_text "not running compact.yml" "$terr"; then _bad "R-1: the column-0 pull_request workflow is not reported excluded" "stderr: $terr"
else _ok "R-1: the column-0 pull_request workflow is not reported excluded"; fi
if has_line "touch .m-compact-push" "$tout"; then _bad "R-1: a column-0 on: sequence holding only - push is not listed, though jobs: mentions pull_request" "stdout: $tout"
else _ok "R-1: a column-0 on: sequence holding only - push is not listed, though jobs: mentions pull_request"; fi
if has_line "note: not running compact-push.yml: it does not trigger on pull_request" "$terr"; then
  _ok "R-1: the column-0 push-only workflow is named on stderr"
else _bad "R-1: the column-0 push-only workflow is named on stderr" "stderr: $terr"; fi

# AC-2: a real run. The positive marker is the control that the run happened
# at all - without it, "no deploy marker" is equally true of a run that
# executed nothing.
rm -f "$TFIX"/.m-*
rout="$( cd "$TFIX" && bash scripts/ci-local.sh 2>&1 )"; rrc=$?
assert_eq "AC-2: the real run succeeds" 0 "$rrc"
if [ -f "$TFIX/.m-gates" ]; then _ok "AC-2: the pull_request workflow's step ran"
else _bad "AC-2: the pull_request workflow's step ran" "no .m-gates; output: $rout"; fi
if [ -f "$TFIX/.m-deploy" ]; then _bad "AC-2: the push-only workflow's step did not run" "a .m-deploy marker was written"
else _ok "AC-2: the push-only workflow's step did not run"; fi
if has_line "note: not running deploy.yml: it does not trigger on pull_request" "$rout"; then
  _ok "AC-6: a real run names the excluded workflow too"
else _bad "AC-6: a real run names the excluded workflow too" "output: $rout"; fi
rm -rf "$TFIX"

summary "ci-local"
