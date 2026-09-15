#!/usr/bin/env bash
# The Stop hook: does it stop a phase being closed without a gate run, and does
# it stay quiet about everything else?
#
# The second question is what this suite is mostly about, because the hook has
# been wrong about it twice.
#
# It first decided staleness from file mtimes, and a gate run writes coverage
# reports, build directories and bundler caches as it goes - so an ad-hoc
# verification run afterwards regenerated them and the hook blocked on
# `coverage/base.css` with a clean `git status`. Ignoring generated output fixed
# that. But mtimes were still the measure, and under `/advance-story` - which
# ends every invocation mid-story by design - "a tracked file is newer than the
# gate stamp" is the NORMAL state at the end of a phase. The hook fired at the
# end of GREEN on a mutation screenshot and at the end of GATES on a gate the
# machine had refused to launch, and both times the only way to clear it was to
# re-run a two-minute suite to satisfy a hook whose own text said "if you are
# intentionally stopping mid-story, say so explicitly" - which it cannot read.
#
# So the measure is now the PHASE, not the mtime: a gate run newer than the last
# phase change means this phase's obligation has been met, and the result of
# that run is already recorded in the story. Anything else the hook has to say -
# a failure, an environment-blocked gate, code touched since - it says without
# blocking. It blocks on one thing only: closing a phase in which the gates
# were never run.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_fixture)"
trap 'rm -rf "$FIX"' EXIT

STAMP="$FIX/.claude/state/last-gate-run"
STATE="$FIX/.claude/state/current-story.env"

# The fixture's state file has always said `BRANCH=story/T-1-fixture` (set_phase,
# in _lib.sh) while `git init` left the checkout on `master`. Nothing read that
# mismatch, so it meant nothing. MT-032 C-5 makes the hook warn instead of
# blocking when the checkout is not the story's branch - which would have turned
# every block below into a warn for a reason none of them is about. So align the
# fixture with the state it already claims. This is a fixture correction, not a
# weakening: these cases are about the gate obligation, and they now assert it
# under a precondition that is legal. The mismatch has its own describe block at
# the end of the file.
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null

# hook [stop_hook_active]   Runs the real hook and echoes its raw output.
hook() {
  printf '{"stop_hook_active":%s}' "${1:-false}" \
    | CLAUDE_PROJECT_DIR="$FIX" bash "$REPO_ROOT/.claude/hooks/gate-reminder.sh" 2>&1
}

# unwrap <json> <key>   The string value of <key>, far enough unescaped to
# assert on. Trimming at the FIRST `"` is not good enough: both messages quote
# the hook's own vocabulary, and a helper that stops at `\"fix it\"` silently
# asserts against half a sentence.
unwrap() {
  local r BS
  BS=$(printf '\134')
  r="${1#*$2\":\"}"
  r="${r%\"\}*}"
  r="${r//"${BS}n"/ }"
  r="${r//"${BS}\""/\'}"
  printf '%s' "$r"
}

# stop   The block reason, or nothing when the stop was allowed.
stop() {
  local out
  out="$(hook "${1:-false}")"
  case "$out" in
    *'"decision":"block"'*) ;;
    *) printf ''; return 0 ;;
  esac
  unwrap "$out" reason
}

# warned   The non-blocking message, or nothing when the hook said nothing.
warned() {
  local out
  out="$(hook)"
  case "$out" in
    *'"systemMessage":"'*) ;;
    *) printf ''; return 0 ;;
  esac
  unwrap "$out" systemMessage
}

assert_blocks() { # <label> <needle>
  local r; r="$(stop)"
  if [ -z "$r" ]; then _bad "blocks: $1" "the stop was allowed"
  else assert_contains "blocks: $1" "$2" "$r"; fi
}

assert_allows() { # <label>
  local r; r="$(stop)"
  if [ -z "$r" ]; then _ok "allows: $1"
  else _bad "allows: $1" "blocked with: $r"; fi
}

# assert_warns <label> <needle>   Says something, and lets the stop through.
assert_warns() {
  local r w
  r="$(stop)"
  [ -z "$r" ] || { _bad "warns: $1" "it blocked instead: $r"; return 0; }
  w="$(warned)"
  if [ -z "$w" ]; then _bad "warns: $1" "the hook said nothing at all"
  else assert_contains "warns: $1" "$2" "$w"; fi
}

# assert_silent <label>   Nothing to say, and nothing said.
assert_silent() {
  local r w
  r="$(stop)"
  [ -z "$r" ] || { _bad "silent: $1" "it blocked: $r"; return 0; }
  w="$(warned)"
  if [ -z "$w" ]; then _ok "silent: $1"
  else _bad "silent: $1" "it warned: $w"; fi
}

# stamp_run <result> [full]   A finished gate run inside the current phase: the
# whole fixture settles into the past - the state file with it, so the run lands
# after the phase change - and the stamp lands after that. Fixed dates rather
# than sleeps: mtime granularity is a whole second on some filesystems and a
# suite that races it fails at random.
stamp_run() {
  find "$FIX" -type f -exec touch -t 202001010000 {} + 2>/dev/null
  printf 'RESULT=%s\nWHEN=2020-06-01T00:00:00Z\nFULL=%s\n' "$1" "${2:-yes}" > "$STAMP"
  touch -t 202006010000 "$STAMP"
}

# phase_moved   The phase changed AFTER that run, which is the one thing that
# makes a recorded run stop counting.
phase_moved() { touch -t 202101010000 "$STATE"; }

# --- the phases it watches ---------------------------------------------------
describe "the hook only watches GREEN and GATES"

for ph in PLANNED RED REVIEW DONE; do
  set_phase "$FIX" "$ph"
  rm -f "$STAMP"
  assert_allows "$ph is not this hook's business"
done

set_phase "$FIX" ""
assert_allows "no active story"

# --- the one thing it blocks -------------------------------------------------
describe "a phase is not closed without a gate run in it"

set_phase "$FIX" GREEN
rm -f "$STAMP"
assert_blocks "the gates have never been run" "has not been run"

# A run from an earlier phase is not a run in this one. This is the case the
# old mtime rule could not see and the new rule exists for: GREEN's gate run
# says nothing about the source GATES then changed.
stamp_run pass
phase_moved
assert_blocks "the last run predates the current phase" "before the story entered GREEN"

set_phase "$FIX" GATES
stamp_run pass
phase_moved
assert_blocks "GATES is watched too" "before the story entered GATES"

# --- what it says without blocking ------------------------------------------
describe "everything else is said, not enforced"

set_phase "$FIX" GREEN
stamp_run pass
assert_silent "a passing run in this phase"

# H3, three occurrences: an orchestrator mutating production code to check the
# suite discriminates, then reverting it, has touched a tracked file after the
# gate run - deliberately, and the revert is the point. Worth saying; not worth
# a two-minute suite.
stamp_run pass
touch "$FIX/src/main.ts"
assert_warns "code touched since the run" "src/main.ts"

stamp_run pass
touch "$FIX/tests/main.test.ts"
assert_warns "a test touched since the run" "tests/main.test.ts"

# H17: `/advance-story` ends every invocation mid-story. A failing run whose
# result is already recorded in the story is not a reason to refuse the stop -
# the orchestrator's next move is a phase change or a dispatch, and it needs to
# be able to report first.
stamp_run fail
assert_warns "the recorded run failed" "FAILED"

# H16: the third state. The gate did not run at all, so neither "fix it" nor
# "go back to RED" applies, and the hook must name the path that does instead
# of a choice between two wrong ones.
stamp_run blocked
assert_warns "a gate the environment refused to launch" "BLOCKED"
w="$(warned)"
assert_contains "and it names the CI path" "CI" "$w"

# And it must name a section that will still be there. The hook told the agent
# to quote the CI run into `## Gate results` - which gates.sh REWRITES on every
# run, and which the non-negotiables say nobody else may touch. Following the
# hook meant writing evidence into the one section guaranteed to lose it, and
# check-boundaries.sh looks for that line by grepping the whole story, so
# nothing would have complained until the record was gone.
assert_contains "and points the evidence at ## Notes" "## Notes" "$w"
case "$w" in
  *"Gate results"*) _bad "does not send evidence to a section gates.sh rewrites" "it names ## Gate results: $w" ;;
  *) _ok "does not send evidence to a section gates.sh rewrites" ;;
esac

# --- a partial run does not close GATES -------------------------------------
describe "in GATES the obligation is a full run"

# --fast and --gate write the stamp too, and must not be able to discharge the
# phase whose whole job is the full suite. In GREEN they are exactly what
# /advance-story asks for, so there they count.
set_phase "$FIX" GATES
stamp_run pass no
assert_blocks "a partial run in GATES" "partial"

set_phase "$FIX" GREEN
stamp_run pass no
assert_silent "a --fast run in GREEN is what GREEN was asked for"

# An older stamp, written before gates.sh recorded FULL at all, is not evidence
# of a partial run. Fail open rather than blocking on a missing line.
set_phase "$FIX" GATES
find "$FIX" -type f -exec touch -t 202001010000 {} + 2>/dev/null
printf 'RESULT=pass\nWHEN=2020-06-01T00:00:00Z\n' > "$STAMP"
touch -t 202006010000 "$STAMP"
assert_silent "a stamp from an older gates.sh"

# --- the gates' own exhaust --------------------------------------------------
describe "generated output is not a code change"

# Every path here is gitignored, and every one of them is written BY a gate
# run: the coverage report, the build directory, the test runner's cache. A
# hook that mentions these mentions them forever, because running the gates
# again recreates them. `src/generated/` is the case a prune list in the hook
# cannot catch, which is why .gitignore is the authority instead.
printf 'node_modules/\ndist/\n.vitest/\ncoverage/\nsrc/generated/\n' > "$FIX/.gitignore"
git -C "$FIX" add .gitignore >/dev/null 2>&1
set_phase "$FIX" GREEN
stamp_run pass
mkdir -p "$FIX/coverage" "$FIX/dist/assets" "$FIX/.vitest/deps"
printf 'body{}\n'   > "$FIX/coverage/base.css"
printf 'x\n'        > "$FIX/dist/assets/app.js"
printf 'x\n'        > "$FIX/.vitest/deps/chunk.js"
assert_silent "a coverage report, a build directory and a runner cache"

stamp_run pass
mkdir -p "$FIX/src/generated"
printf 'export const x = 1\n' > "$FIX/src/generated/api.ts"
assert_silent "generated output nested inside a source directory"

# Vitest writes a screenshot under .vitest/attachments/ when a browser test
# FAILS - which is what happens during a deliberate mutation, the strongest
# verification this harness has.
stamp_run pass
mkdir -p "$FIX/.vitest/attachments"
printf 'PNG\n' > "$FIX/.vitest/attachments/3f2a9c1e.png"
assert_silent "a failure screenshot written by a deliberate mutation run"

# The floor: ignoring generated output must not stop it noticing real ones.
touch "$FIX/src/main.ts"
assert_warns "a real source change alongside generated output" "src/main.ts"

# --- prose the gates never read ---------------------------------------------
describe "a harness prompt is not code the gates judge"

# .claude/commands/advance-story.md classifies as harness, and until now that
# meant editing a command file counted as a code change - while editing a wiki
# page, one directory over, did not. No gate reads either. The set is the one
# gate_tree_hash covers, so the two stay in agreement.
set_phase "$FIX" GREEN
stamp_run pass
mkdir -p "$FIX/.claude/commands" "$FIX/.claude/hooks"
printf '# advance\n' > "$FIX/.claude/commands/advance-story.md"
assert_silent "a command prompt edited after the run"

stamp_run pass
printf 'x() { :; }\n' > "$FIX/.claude/hooks/lib.sh"
assert_warns "a hook edited after the run is still code" ".claude/hooks/lib.sh"

stamp_run pass
printf 'gate | unit | required | . | true\n' > "$FIX/.claude/harness/project.conf"
assert_warns "the gate manifest is still code" ".claude/harness/project.conf"

# --- the loop guard ----------------------------------------------------------
describe "the hook never loops on itself"

set_phase "$FIX" GREEN
rm -f "$STAMP"
r="$(stop true)"
assert_eq "stop_hook_active suppresses even the block" "" "$r"

# --- whose story is this, anyway? --------------------------------------------
describe "a session on another branch is told, not stopped"

# MT-032 AC-4 / F-3. `.claude/state/current-story.env` is global to the tree: it
# names one story for everything running in it, and the hook reads it with no
# notion of which session is asking. Measured before this story, a session on
# another branch doing something entirely unrelated was returned
# {"decision":"block"} and told to gate T-1, a story belonging to
# story/T-1-fixture. A hard stop caused by another session's state is not
# cosmetic - it is a session that cannot finish - so the hook now says whose
# story it is and lets go.
#
# Both sources of "the story's branch" agree here on purpose: the state file
# says BRANCH=story/T-1-fixture and the story file's frontmatter says
# `branch: story/T-1-fixture`. Which one the hook reads is the implementer's
# choice; these assertions hold either way.
story "$FIX" T-1 GREEN </dev/null

git -C "$FIX" checkout -q -B unrelated-session 2>/dev/null
set_phase "$FIX" GREEN
rm -f "$STAMP"
assert_warns "a session on another branch is not blocked" "story/T-1-fixture"
w="$(warned)"
assert_contains "and the message names the branch it is actually on" "unrelated-session" "$w"

# DV-4, and the reason it exists: C-5 must NARROW the hook, not switch it off.
# A session ON the story's branch, in GREEN, with no gate run at all, is still
# stopped - exactly as it was before this story.
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
set_phase "$FIX" GREEN
rm -f "$STAMP"
assert_blocks "the story's own branch is still stopped" "has not been run"

# The same pair for the partial-run path, so that what changed is the branch
# test rather than one code path that happened to be looked at.
git -C "$FIX" checkout -q -B unrelated-session 2>/dev/null
set_phase "$FIX" GATES
stamp_run pass no
assert_warns "a partial run in GATES, on another branch" "story/T-1-fixture"

git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
set_phase "$FIX" GATES
stamp_run pass no
assert_blocks "a partial run in GATES, on the story's branch" "partial"

summary "gate-reminder"
