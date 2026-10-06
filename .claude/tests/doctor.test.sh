#!/usr/bin/env bash
# Tests for scripts/doctor.sh - specifically the discovery checks, which are
# the answer to a gate whose scope collapsed to nothing without anyone noticing.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT

doctor() { ( cd "$FIX" && bash scripts/doctor.sh 2>&1 ); }

# run_doctor sets BOTH $out and $rc. The CI block below counts into `missing`,
# which is doctor's EXIT STATUS and the only part of it a caller can act on -
# a script, a setup step, a person typing `&&`. Deleting that one line left the
# block printing its complaint and doctor exiting 0, and every assertion here
# stayed green, because all of them read the text. A check whose verdict no
# caller can observe is the exact shape this block was added to detect, and it
# had arrived in the detector.
run_doctor() { out="$( cd "$FIX" && bash scripts/doctor.sh 2>&1 )"; rc=$?; }

describe "discovery: the runner is asked what it can see"

write_conf "$FIX" <<'EOF'
gate      | unit     | required | . | printf 'Tests  1 passed (1)\n'
evidence  | unit     | Tests +[1-9][0-9]* passed
discovery | platform | . | printf 'src/platform/gl.test.ts\n' | grep -q "src/platform/"
EOF
out="$(doctor)"
assert_contains "a directory the runner can see" "ok       platform     discovered" "$out"

write_conf "$FIX" <<'EOF'
gate      | unit     | required | . | printf 'Tests  1 passed (1)\n'
evidence  | unit     | Tests +[1-9][0-9]* passed
discovery | platform | . | printf 'src/ui/app.test.ts\n' | grep -q "src/platform/"
EOF
out="$(doctor)"
assert_contains "a directory it cannot" "MISSING  platform" "$out"
assert_contains "says what that costs"  "committed and never run" "$out"


# ---------------------------------------------------------------------------
describe "discovery survives a consumer that stops reading"

# Reported from a consuming project: doctor said "e2e: nothing discovered" on a
# tree where everything was discovered. The line was
#
#   pnpm exec vitest list --project ui | grep -q "src/ui/"
#
# `grep -q` exits on its FIRST match. The producer is still writing, gets
# SIGPIPE, and dies with 141 - and doctor runs the command under `pipefail`, so
# the pipeline's status is the producer's corpse rather than grep's success.
#
# The harness taught this exact shape in six places: project.conf's template,
# the quality-gates skill, and the godot, node-typescript and python-uv
# profiles. Every project that copied one got discovery lines that report
# nothing-discovered at random, on a check whose entire job is noticing when a
# gate's scope has collapsed to nothing. The wrong lesson from a spurious
# "nothing discovered" is to delete the line.
#
# The suite could not see it because every fixture here pipes ONE LINE into
# grep: the producer finishes before grep exits, so there is no signal to
# receive. The size of the producer is the whole variable, so this one is big.
write_conf "$FIX" <<'EOF'
gate      | unit | required | . | printf 'Tests  1 passed (1)\n'
evidence  | unit | Tests +[1-9][0-9]* passed
discovery | wide | . | seq 1 200000 | grep -q "^5$"
EOF
out="$(doctor)"
assert_contains "a large producer piped into grep -q still counts as discovered" \
  "ok       wide         discovered" "$out"

# And the check still has teeth: a command that genuinely finds nothing is still
# reported. Fixing the false negative must not turn discovery into a formality.
write_conf "$FIX" <<'EOF'
gate      | unit | required | . | printf 'Tests  1 passed (1)\n'
evidence  | unit | Tests +[1-9][0-9]* passed
discovery | none | . | seq 1 200000 | grep -q "^NOTHING$"
EOF
out="$(doctor)"
assert_contains "a genuinely empty discovery is still MISSING" "MISSING  none" "$out"
describe "discovery: nothing declared is reported, not skipped silently"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  1 passed (1)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(doctor)"
assert_contains "the section still appears" "none declared" "$out"


describe "the harness says which version it is"

# A vendored copy cannot be dated from the outside: it has the consuming
# project's git history, not this one's. Two field reports in a row arrived
# reporting defects that had been fixed upstream for weeks, and neither could
# say which harness it had measured - so every finding had to be re-verified by
# hand before it could be called already-fixed. The stamp is what makes
# "already fixed in 2026-09-11" a comparison instead of an afternoon.
out="$(doctor)"
assert_contains "doctor prints the harness version" "harness ver" "$out"
assert_contains "and it is the one in the file" \
  "$(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$REPO_ROOT/.claude/harness/VERSION" | head -1)" "$out"

# Absent, it says so rather than printing an empty field. A blank where a
# version should be reads as "no version", which is the one thing it must not
# be confused with - an unstamped copy is an OLD copy, from before stamping.
mv "$FIX/.claude/harness/VERSION" "$FIX/.claude/harness/VERSION.hidden" 2>/dev/null
out="$(doctor)"
assert_contains "an unstamped copy is named as one" "unstamped" "$out"
mv "$FIX/.claude/harness/VERSION.hidden" "$FIX/.claude/harness/VERSION" 2>/dev/null

# ---------------------------------------------------------------------------
describe "CI is asked whether it runs the harness's own checks"

# The gap this closes. `.github/workflows/**` is PROJECT-owned, so a refresh
# never touches it - correctly, since a project adds its toolchain setup there.
# The consequence nobody accounted for is that the template's workflow and the
# project's diverge from the moment of bootstrap, with nothing comparing them.
#
# It is not hypothetical. A real project's gates.yml ran `gates.sh` but not
# `selftest.sh` and not `gates.sh --audit`, so the harness's own tests had never
# executed in its CI - which is how a re-vendor there went green with two suites
# failing. The project could not have noticed: the suite that would have told it
# is the suite its CI does not run.
#
# doctor is the right home rather than the selftest, for exactly that reason: a
# check that only runs inside the thing that is not running cannot report it.
mkdir -p "$FIX/.github/workflows"
cat > "$FIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: pnpm install --frozen-lockfile
      - run: bash scripts/gates.sh
YML
run_doctor
assert_contains "a workflow that never runs the harness tests is named" "selftest.sh" "$out"
assert_contains "and says what it costs" "never run" "$out"
# THE HALF A CALLER CAN ACT ON. Everything else in this block is a string.
assert_eq "and doctor exits non-zero, not merely complains" 1 "$rc"

# The want-list is three entries and each has to be its own. Dropping `gates.sh`
# from it left every assertion here green: the two below it were still missing,
# so the block still complained, still counted, still exited 1 - and the gate
# runner had quietly stopped being required.
cat > "$FIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/selftest.sh
      - run: bash scripts/check-boundaries.sh origin/main
YML
run_doctor
assert_contains "a workflow missing only gates.sh is still incomplete" "gates.sh" "$out"
assert_eq "and still exits non-zero" 1 "$rc"

# MENTIONING is not RUNNING. The match is `scripts/<name>` rather than the bare
# name for this reason: weakened to a substring, a workflow that merely names
# selftest.sh in a comment - or in a job title, or in an `echo` - satisfies a
# check about whether CI executes it.
cat > "$FIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      # TODO: wire up selftest.sh and check-boundaries.sh here
      - name: notes about gates.sh
        run: echo "we should run selftest.sh one day"
      - run: bash scripts/gates.sh
YML
run_doctor
assert_contains "a workflow that only MENTIONS the scripts is still missing them" \
  "no workflow runs scripts/selftest.sh" "$out"
assert_eq "and exits non-zero on the mention" 1 "$rc"

# The boundaries half too: gates.sh judges the code, check-boundaries.sh judges
# the commit, and CI running only the first is the state that let a story reach
# main with a phase the lock would have refused.
assert_contains "and the commit-level check" "check-boundaries.sh" "$out"

# Satisfied by ANY workflow file, because splitting them across jobs is a
# legitimate layout and this must not dictate one.
cat > "$FIX/.github/workflows/boundaries.yml" <<'YML'
name: boundaries
on: [pull_request]
jobs:
  boundaries:
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/check-boundaries.sh origin/main
YML
cat > "$FIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: pnpm install --frozen-lockfile
      - run: bash scripts/selftest.sh
      - run: bash scripts/gates.sh
YML
run_doctor
# check-sigpipe.sh joined the want-list in release 36 and check-grep-count.sh in
# 37, so this pair is no longer complete - and that is the assertion, not an
# inconvenience. .github/workflows is project-owned and a refresh cannot add
# the step, so doctor naming it is the ONLY way a consuming project learns a
# guard is not running there.
assert_contains "a set missing a guard is named" \
  "no workflow runs scripts/check-sigpipe.sh" "$out"
assert_eq "and exits non-zero without it" 1 "$rc"

cat > "$FIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: pnpm install --frozen-lockfile
      - run: bash scripts/selftest.sh
      - run: bash scripts/gates.sh
      - run: bash scripts/check-sigpipe.sh
      - run: bash scripts/check-grep-count.sh
YML
run_doctor
assert_contains "a complete set reports ok" "ok       ci" "$out"
case "$out" in
  *"never run"*) _bad "and says nothing is missing" "still complaining: $out" ;;
  *) _ok "and says nothing is missing" ;;
esac
# The control for the exit assertions above: without it, "always exit 1"
# passes every one of them.
assert_eq "and a complete set exits 0" 0 "$rc"

# No workflows at all is not a failure - a project may not use CI, and doctor
# must not invent a requirement. It says so and moves on.
rm -rf "$FIX/.github"
out="$(doctor)"
case "$out" in
  *"never run"*) _bad "no workflows is not a complaint" "complained anyway: $out" ;;
  *) _ok "no workflows is not a complaint" ;;
esac

# ---------------------------------------------------------------------------
describe "the CI check runs even before a stack is chosen"

# Caught immediately after shipping the check, by running doctor on this
# repository: `project.conf has no commands` exits early, and the CI block sat
# AFTER that exit. So the check was dead in exactly the state the template
# itself is in, and every fixture above had already been given a project.conf -
# which is why nothing noticed.
#
# It is also the state a project is in for its first few stories, and its
# workflows can be wrong from the bootstrap commit onward.
write_conf "$FIX" <<'EOF'
EOF
mkdir -p "$FIX/.github/workflows"
cat > "$FIX/.github/workflows/gates.yml" <<'YML'
name: gates
on: [pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/gates.sh
YML
out="$(doctor)"
assert_contains "an unbootstrapped project still gets the CI check" "selftest.sh" "$out"
assert_contains "and is still told there is no toolchain yet" "no commands" "$out"
rm -rf "$FIX/.github"

# ---------------------------------------------------------------------------
describe "the version is a release number, not a date pretending to be one"

# The stamp was specified as "one ISO date", and bumping it per round drifted it
# off the calendar immediately: nine releases landed across three real days
# (2026-09-11 to -13) and were stamped 2026-09-11 through 2026-09-19. Every one
# of those dates was a claim about when, and six of them were false.
#
# Nothing ever read it as a date - check-boundaries.sh asks only whether it
# CHANGED, doctor prints it - so the date was decoration that could only mislead.
# It is a monotonic release number now, with the true date beside it.
first="$(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$REPO_ROOT/.claude/harness/VERSION" | head -1)"
# A plain integer, so that a date cannot satisfy this by starting with a digit -
# which `2026-09-19` does, and which is exactly the value being corrected.
case "${first%% *}" in
  ''|*[!0-9]*) _bad "the shipped version starts with a release number" "got: $first" ;;
  *) _ok "the shipped version starts with a release number" ;;
esac
case "$first" in
  *"("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]")"*) _ok "and carries the real release date" ;;
  *) _bad "and carries the real release date" "got: $first" ;;
esac

# A copy vendored before this change holds a bare date. It must keep working -
# doctor prints whatever it finds, and a reader can tell a date-shaped value
# predates the numbering and is therefore older than any number.
printf '2026-09-16\n' > "$FIX/.claude/harness/VERSION"
out="$(doctor)"
assert_contains "a legacy date-shaped stamp still reports" "2026-09-16" "$out"
case "$out" in
  *unstamped*) _bad "and is not mistaken for unstamped" "called it unstamped: $out" ;;
  *) _ok "and is not mistaken for unstamped" ;;
esac
printf '%s\n' "$first" > "$FIX/.claude/harness/VERSION"

# ============================================================================
# HARNESS-024: doctor.sh and task.sh parse the manifest without a process per
# field
# ============================================================================
#
# gates.test.sh holds AC-1, the gates.sh halves of AC-2 to AC-5, and AC-6. This
# half is the other two scripts: doctor.sh splits `discovery` lines at -f4-
# and `gate`/`task` lines at -f5-, task.sh splits `task` lines at -f5-, and
# neither strips a carriage return itself - trim()'s [:space:] is what keeps a
# CRLF manifest working there. No suite tested task.sh before this one.
#
# Every manifest is the synthetic one in fixtures/manifest/ (see _lib.sh),
# never the real .claude/harness/project.conf.

_h24="$(mktemp -d 2>/dev/null || mktemp -d -t h024.XXXXXX)"
MFX="$(manifest_fixture)"
trap 'rm -rf "$FIX" "$MFX" "$_h24"' EXIT
crlf_copy "$MANIFEST_FIXTURES/project.conf" "$_h24/crlf.conf"
pad_manifest "$MANIFEST_FIXTURES/project.conf" "$_h24/padded.conf"

describe "HARNESS-024 AC-3: doctor.sh and task.sh print what they printed before the rewrite"

# Goldens captured from the unchanged scripts (ea0fba0) through the same
# _lib.sh functions over the same fixture. doctor.sh: its `Project toolchain`
# and `Test discovery` sections. task.sh: the no-argument listing, then
# `task.sh <id> extra` for each fixture task and one it lacks, with each exit
# status. For the well-formed manifest and its CRLF copy.
for _c in project crlf; do
  case "$_c" in crlf) _conf="$_h24/crlf.conf" ;; *) _conf="$MANIFEST_FIXTURES/project.conf" ;; esac
  use_manifest "$MFX" "$_conf"
  doctor_golden "$MFX" > "$_h24/$_c.doctor"
  golden_check "AC-3: doctor.sh's toolchain and discovery sections over $_c.conf are byte-identical to the pre-rewrite golden" \
    "$MANIFEST_FIXTURES/$_c.doctor.golden" "$_h24/$_c.doctor"
  task_golden "$MFX" "$([ "$_c" = crlf ] && printf nolist)" > "$_h24/$_c.task"
  golden_check "AC-3: task.sh, listing and every task with an extra argument, over $_c.conf is byte-identical to the pre-rewrite golden" \
    "$MANIFEST_FIXTURES/$_c.task.golden" "$_h24/$_c.task"
done

describe "HARNESS-024 AC-4: doctor.sh and task.sh keep a value containing | whole"

# Read out of the AC-3 runs over the well-formed manifest. `cpu` succeeds only
# if the WHOLE command reaches eval: cut at its first pipe it is an unterminated
# quote. `gpu` fails whole, and its MISSING line quotes the command - three
# embedded pipes, all of which must survive (-f4-).
_d="$(cat "$_h24/project.doctor")"; _t="$(cat "$_h24/project.task")"
assert_contains "AC-4 -f4-: a discovery command with three embedded pipes runs whole" \
  "  ok       cpu          discovered" "$_d"
assert_contains "AC-4 -f4-: and a failing one is quoted whole, every pipe intact" \
  "  MISSING  gpu          nothing discovered by: printf 'CUDA|Dml\n' | { IFS= read -r l; case \"\$l\" in *'|CPU') true ;; *) false ;; esac; }" "$_d"
assert_contains "AC-4 -f5-: doctor.sh names the executable of a gate command (field 5 onwards)" \
  "  MISSING  no-such-tool-h024 needed for: gate 'mutation'" "$_d"
assert_contains "AC-4 -f5-: a task command with embedded pipes runs whole, extra argument appended" \
  "\$ task.sh pipes extra
[a|b]
args:extra
rc=0" "$_t"
assert_contains "AC-4: a tab-padded task runs in its own cwd (field 4) with the extra argument" \
  "\$ task.sh where extra
in src
arg=extra
rc=0" "$_t"
assert_contains "an unconfigured task says so and exits 1" \
  "\$ task.sh idle extra
task 'idle' is not configured in project.conf
rc=1" "$_t"
assert_contains "AC-4 over CRLF: the same task runs without a carriage return in its command" \
  "\$ task.sh where extra
in src
arg=extra
rc=0" "$(cat "$_h24/crlf.task")"

describe "HARNESS-024 AC-2: doctor.sh and task.sh spawn no more processes for a longer manifest"

# Traced over the manifest and over its padded copy; the counts must be EQUAL.
# doctor.sh's git, grep and awk calls are a constant per run and per data line,
# so they do not break the equality; the shipped trim()'s `sed` per padding
# line does.
use_manifest "$MFX" "$MANIFEST_FIXTURES/project.conf"
_doc_plain="$(trace_script "$MFX" "$_h24/t.doctor.plain" doctor.sh)"
_task_plain="$(trace_script "$MFX" "$_h24/t.task.plain" task.sh where extra)"
use_manifest "$MFX" "$_h24/padded.conf"
_doc_pad="$(trace_script "$MFX" "$_h24/t.doctor.pad" doctor.sh)"
_task_pad="$(trace_script "$MFX" "$_h24/t.task.pad" task.sh where extra)"
same_count "AC-2: doctor.sh spawns as many processes over the padded manifest as over the plain one" \
  "$_doc_plain" "$_doc_pad"
same_count "AC-2: task.sh <id> spawns as many processes over the padded manifest as over the plain one" \
  "$_task_plain" "$_task_pad"
# And the padding means nothing to either script, so the equality above is
# about cost and not about a manifest that was read differently.
awk '/^[^ ]/ { on = ($0 ~ /^Project toolchain/ || $0 ~ /^Test discovery$/) } on' \
  "$_h24/t.doctor.pad.out" > "$_h24/t.doctor.pad.sections"
golden_check "and doctor.sh reports the padded copy exactly as the plain one" \
  "$MANIFEST_FIXTURES/project.doctor.golden" "$_h24/t.doctor.pad.sections"
assert_eq "and task.sh runs the same task from it" \
  "in src
arg=extra
rc=0" "$(cat "$_h24/t.task.pad.out"; printf 'rc=%s' "$(cat "$_h24/t.task.pad.rc")")"

describe "HARNESS-024 AC-5: doctor.sh's and task.sh's trim() agree with the shipped sed form"

# The same input set and oracle as gates.test.sh's AC-5 block (_lib.sh),
# applied to the trim() each of these two scripts defines, in both forms.
trim_inputs "$_h24/trim.in"
trim_oracle "$_h24/trim.in" "$_h24/trim.oracle"
for _s in doctor task; do
  assert_contains "$_s.sh defines trim()" "trim()" "$(extract_fn "$REPO_ROOT/scripts/$_s.sh" trim)"
  apply_trim "$REPO_ROOT/scripts/$_s.sh" "$_h24/trim.in" "$_h24/trim.$_s"
  assert_eq "AC-5: $_s.sh trim, printing form, agrees with the sed form on every input" \
    "0" "$(disagreements "$_h24/trim.oracle" "$_h24/trim.$_s")"
  apply_trim "$REPO_ROOT/scripts/$_s.sh" "$_h24/trim.in" "$_h24/trim.$_s.assign" assign
  assert_eq "C-1: $_s.sh trim, assigning form (trim \"\$x\" var), agrees with the sed form on every input" \
    "0" "$(disagreements "$_h24/trim.oracle" "$_h24/trim.$_s.assign")"
done

summary "doctor"
