#!/usr/bin/env bash
# Tests for scripts/gates.sh - the liveness machinery, not any real toolchain.
#
# Every gate command here is a `printf`, so the suite runs in a second and
# tests exactly one thing: whether gates.sh can tell a gate that did work from
# one that only exited 0.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT

gates() { ( cd "$FIX" && bash scripts/gates.sh "$@" 2>&1 ); }

# ---------------------------------------------------------------------------
describe "evidence: a gate that exits 0 having done nothing"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
# project.conf is gated (harness, not markdown) and write_conf creates it
# UNTRACKED. HARNESS-014 makes a full run with an active story refuse to record
# while any untracked gated file exists, so the fixture's conf is tracked once,
# here; every later write_conf is then an edit to a tracked file, which the
# stamp covers and the refusal ignores. Its content still changes per block.
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "track project.conf" >/dev/null 2>&1
out="$(gates)"
assert_contains "a live gate passes" "PASS         unit" "$out"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'No test files found, exiting with code 0\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(gates)"
assert_contains "a vacuous gate fails" "no evidence of work" "$out"
assert_contains "and the run fails"    "1 required gate(s) failed" "$out"

# ---------------------------------------------------------------------------
describe "--gate names a gate that exists"

# `--gate untt` ran nothing and printed "All required gates passed (0 ran)",
# exit 0. A typo is not a pass.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(gates --gate untt)"; rc=$?
assert_contains "a typo is refused" "no gate named 'untt'" "$out"
assert_eq "and exits non-zero" "2" "$rc"

# ---------------------------------------------------------------------------
describe "floor: a gate that started doing much less"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
floor    | unit | 40
EOF
out="$(gates)"
assert_contains "above the floor passes"   "PASS         unit" "$out"
assert_contains "and reports the count"    "observed 47, floor 40" "$out"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  3 passed (3)\n'
evidence | unit | Tests +[1-9][0-9]* passed
floor    | unit | 40
EOF
out="$(gates)"
assert_contains "below the floor fails"     "below the floor of 40" "$out"
assert_contains "naming what it observed"   "did 3 units of work" "$out"

# An optional gate below its floor warns rather than blocking, like any other
# optional failure.
write_conf "$FIX" <<'EOF'
gate     | integration | optional | . | printf 'Tests  1 passed (1)\n'
evidence | integration | Tests +[1-9][0-9]* passed
floor    | integration | 10
EOF
out="$(gates)"
assert_contains "an optional gate below its floor warns" "WARN         integration" "$out"

describe "floor: a floor that cannot be evaluated is a manifest error"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
floor    | unit | 40
EOF
out="$(gates --audit)"
assert_contains "a floor without an evidence line" "floor needs an evidence regex" "$out"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
floor    | unit | lots
EOF
out="$(gates --audit)"
assert_contains "a floor that is not a number" "is not a number" "$out"

describe "floor: an evidence regex that uses alternation"

# `a|b` at the top level would otherwise bind the trailing `.*` to the last
# branch alone, so a count that follows the matched text is invisible.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests passed: 47\n'
evidence | unit | Tests passed:|Examples passed:
floor    | unit | 40
EOF
out="$(gates)"
assert_contains "counts what follows the branch that matched" "observed 47" "$out"
assert_contains "so the gate passes" "PASS         unit" "$out"

describe "the count is reported even with no floor"

write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Checked 132 files in 400ms\n'
evidence | lint | Checked [1-9][0-9]* files
EOF
out="$(gates)"
assert_contains "observed count in the summary" "observed 132" "$out"

# ---------------------------------------------------------------------------
describe "no-count: an evidence regex that proves liveness and measures nothing"

# The field report: cargo's `Finished \`dev\` profile ... in 0.29s` proves the
# tool ran and offers no count, so work_count reports the ELAPSED TIME. It read
# 0, then 2, then 6 across runs of the same unchanged workspace. Harmless while
# decorative; a coin-toss gate the moment somebody puts a floor under it.
write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Finished `dev` profile [unoptimized + debuginfo] target(s) in 0.29s\n'
evidence | lint | Finished .* profile
EOF
out="$(gates)"
assert_contains "undeclared, the stopwatch is reported as a count" "observed 0" "$out"

write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Finished `dev` profile [unoptimized + debuginfo] target(s) in 0.29s\n'
evidence | lint | Finished .* profile
no-count | lint | the digits after it are elapsed seconds, not a count
EOF
out="$(gates)"
assert_contains "declared, the number is withheld" "observed -" "$out"
assert_contains "and liveness still holds"         "PASS         lint" "$out"

# The same gate with nothing to say still fails: `no-count` withholds the
# measurement, it does not excuse the gate from proving it ran.
write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'nothing to do\n'
evidence | lint | Finished .* profile
no-count | lint | the digits after it are elapsed seconds, not a count
EOF
out="$(gates)"
assert_contains "no-count does not weaken the evidence assertion" "no evidence of work" "$out"

describe "no-count: a floor on it is refused"

write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Finished `dev` profile [unoptimized + debuginfo] target(s) in 5.29s\n'
evidence | lint | Finished .* profile
no-count | lint | the digits after it are elapsed seconds, not a count
floor    | lint | 5
EOF
out="$(gates --audit)"
assert_contains "the audit refuses it" "declared no-count" "$out"
assert_contains "and the audit fails"  "1 manifest problem" "$out"

# Refused at run time too, not only under --audit: a floor that would otherwise
# have PASSED here purely because the fixture's stopwatch read 5.29s.
out="$(gates)"
assert_contains "the run refuses it"  "FAIL         lint" "$out"
assert_contains "rather than passing on the clock" "declared no-count" "$out"

describe "no-count: a line that defends nothing is a manifest error"

write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Finished `dev` profile in 0.29s\n'
evidence | lint | Finished .* profile
no-count | lint |
EOF
out="$(gates --audit)"
assert_contains "no-count without a reason fails the audit" "marked no-count with no reason" "$out"

write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Finished `dev` profile in 0.29s\n'
evidence | lint | Finished .* profile
no-count | lnit | a typo, so lint is left open to a floor on its stopwatch
floor    | lint | 5
EOF
out="$(gates --audit)"
assert_contains "no-count naming no gate fails the audit" "names no configured gate" "$out"

# A count-free regex is not detectable from the regex, which is why it is
# declared. `TOTAL` has no digit class either, and the number after it is a
# real one a floor may use.
write_conf "$FIX" <<'EOF'
gate     | coverage | required | . | printf 'TOTAL  1629  16  99.02%%\n'
evidence | coverage | TOTAL
floor    | coverage | 1000
EOF
out="$(gates)"
assert_contains "a digit-class-free regex may still measure" "observed 1629, floor 1000" "$out"

# ---------------------------------------------------------------------------
describe "no-count: what HARNESS-055 adds beyond the ported block (AC-2, AC-3, AC-4, AC-5, AC-7)"

# AC-7: the declaration is visible where a reader looks for it - beside the
# gate in --list and in the audit's ok block - and is not itself a problem.
write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Finished `dev` profile [unoptimized + debuginfo] target(s) in 0.29s\n'
evidence | lint | Finished .* profile
no-count | lint | the digits after it are elapsed seconds, not a count
EOF
out="$(gates --list)"
assert_contains "--list shows the no-count reason beside the gate" \
  "no-count: the digits after it are elapsed seconds, not a count (no floor possible)" "$out"
out="$(gates --audit)"; rc=$?
assert_contains "--audit's ok block shows the no-count reason" \
  'no-count: the digits after it are elapsed seconds, not a count (reports `observed -`; no floor possible)' "$out"
assert_eq "and a declared gate with no floor passes the audit" "0 Manifest audit passed." \
  "$rc $(grep -x 'Manifest audit passed\.' <<< "$out")"

# AC-2 and AC-3: the refusal names the gate and the reason, the audit's exit
# says so, and the run is a failed run rather than a pass with a note beside it.
write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Finished `dev` profile [unoptimized + debuginfo] target(s) in 5.29s\n'
evidence | lint | Finished .* profile
no-count | lint | the digits after it are elapsed seconds, not a count
floor    | lint | 5
EOF
out="$(gates --audit)"; rc=$?
assert_contains "the audit's refusal of a floor on a no-count gate names lint and why it was declared" \
  "FAIL lint         floor cannot be measured: lint is declared no-count (the digits after it are elapsed seconds, not a count)" "$out"
assert_eq "and the audit exits non-zero" "non-zero" "$( [ "$rc" != 0 ] && echo non-zero || echo zero)"
out="$(gates)"
assert_contains "the run's refusal names lint and why it was declared" \
  "FAIL         lint (floor cannot be measured: lint is declared no-count (the digits after it are elapsed seconds, not a count))" "$out"
assert_not_contains "and the run does not say the required gates passed" \
  "All required gates passed" "$out"

# AC-4: a no-count with no reason fails the audit, and on a plain run fails the
# gate before its command runs. The command leaves a marker inside .git, which
# is neither tracked nor untracked, so whether it ran is observable without
# disturbing the fixture's recorded tree.
write_conf "$FIX" <<'EOF'
gate     | lint | required | . | touch .git/h055-nocount-ran; printf 'Finished `dev` profile in 0.29s\n'
evidence | lint | Finished .* profile
no-count | lint |
EOF
out="$(gates --audit)"; rc=$?
assert_contains "--audit names lint as marked no-count with no reason" \
  "FAIL lint         marked no-count with no reason; say what its evidence regex measures instead" "$out"
assert_eq "and that audit exits non-zero" "non-zero" "$( [ "$rc" != 0 ] && echo non-zero || echo zero)"
rm -f "$FIX/.git/h055-nocount-ran"
out="$(gates)"
assert_contains "on a plain run, no-count without a reason fails the gate" \
  "FAIL         lint (marked no-count with no reason in project.conf)" "$out"
assert_eq "and the gate's command is never run" "not run" \
  "$( [ -e "$FIX/.git/h055-nocount-ran" ] && echo ran || echo "not run")"
rm -f "$FIX/.git/h055-nocount-ran"

# AC-5: the misspelt id is named, and the audit's exit says so.
write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Finished `dev` profile in 0.29s\n'
evidence | lint | Finished .* profile
no-count | lnit | a typo, so lint is left open to a floor on its stopwatch
floor    | lint | 5
EOF
out="$(gates --audit)"; rc=$?
assert_contains "the orphan no-count line is named by its misspelt id" \
  'FAIL lnit         a `no-count` line names no configured gate' "$out"
assert_eq "and that audit exits non-zero" "non-zero" "$( [ "$rc" != 0 ] && echo non-zero || echo zero)"

# ---------------------------------------------------------------------------
describe "required_gates: a story can escalate an optional gate for itself"

write_conf "$FIX" <<'EOF'
gate     | unit        | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit        | Tests +[1-9][0-9]* passed
gate     | integration | optional | . | printf 'boom\n'; exit 1
evidence | integration | [1-9][0-9]* passed
EOF

story "$FIX" T-1 GATES </dev/null
set_phase "$FIX" GATES
out="$(gates)"
assert_contains "optional by default: it warns" "WARN         integration" "$out"
assert_contains "and the run still passes"      "All required gates passed" "$out"

story "$FIX" T-1 GATES <<'EOF'
required_gates: [integration]
EOF
out="$(gates)"
assert_contains "escalated: it fails"      "FAIL         integration" "$out"
assert_contains "naming the story"         "required by story T-1" "$out"
assert_contains "and the run fails"        "1 required gate(s) failed" "$out"

# A waiver cannot silence a gate the story requires - that is a bypass, the
# same one waivers are already refused for on repo-required gates.
write_conf "$FIX" <<'EOF'
gate     | integration | optional | . | printf 'boom\n'; exit 1
evidence | integration | [1-9][0-9]* passed
waiver   | integration | the service is not up in CI
EOF
out="$(gates)"
assert_contains "a waiver on a story-required gate is refused" "waiver" "$out"
assert_contains "and it fails"                                 "1 required gate(s) failed" "$out"

set_phase "$FIX" ""


# ---------------------------------------------------------------------------
describe "--fast: the subset that judges whether tests are admissible"

# The field report this came from: RED and GREEN only ever ran the plain test
# command, so a suite that passed both, and passed sixteen local gates, still
# failed a REQUIRED gate in CI - the same tests under coverage instrumentation,
# where one property test crossed the 5s timeout. --fast is the primitive that
# lets RED and GREEN ask the gates the question, without paying for a bundle.
write_conf "$FIX" <<'EOF'
gate     | lint     | required | . | printf 'Checked 12 files\n'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | coverage | required | . | printf 'Tests  47 passed (47)\n'
gate     | build    | required | . | printf 'Bundled 3 targets\n'
evidence | lint     | Checked [1-9][0-9]* files
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | coverage | Tests +[1-9][0-9]* passed
evidence | build    | Bundled [1-9][0-9]* targets
slow     | build    | a Tauri release bundle; RED has no use for it
EOF
out="$(gates --fast)"
assert_contains "a fast gate runs"          "PASS         lint" "$out"
assert_contains "the instrumented one runs" "PASS         coverage" "$out"
case "$out" in
  *"PASS         build"*) _bad "a slow gate is skipped" "build ran anyway: $out" ;;
  *) _ok "a slow gate is skipped" ;;
esac
assert_contains "and is named"        "--fast skipped: build" "$out"
assert_contains "with the caveat"     "This is a subset, not a verdict" "$out"

# A subset is not evidence, for the same reason --gate and --required are not.
# Run from the story's own branch: HARNESS-026 refuses to record a run made from
# any other, so a full run that is meant to record has to be made from there.
# The branch is deleted again below, because the covers block creates it afresh.
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
story "$FIX" T-1 GATES <<'EOF'
EOF
set_phase "$FIX" GATES
out="$(gates --fast)"
assert_contains "a fast run is never recorded" "not recorded in the story" "$out"
out="$(gates)"
assert_contains "a full run still is"          "recorded in docs/backlog/stories/T-1.md" "$out"
assert_contains "and points at CI's other script" "check-boundaries.sh" "$out"
set_phase "$FIX" ""
git -C "$FIX" checkout -q - 2>/dev/null
git -C "$FIX" branch -q -D story/T-1-fixture 2>/dev/null

# With nothing marked slow, --fast is a full run in everything but the record,
# and says so rather than letting anyone believe they bought speed.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(gates --fast)"
assert_contains "no slow lines is reported" "--fast skipped nothing" "$out"

# ---------------------------------------------------------------------------
describe "slow: a line that excludes nothing is a manifest error"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
slow     | unit |
EOF
out="$(gates --audit)"
assert_contains "slow without a reason fails the audit" "marked slow with no reason" "$out"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
slow     | unti | a typo, so `build` never leaves the fast subset
EOF
out="$(gates --audit)"
assert_contains "slow naming no gate fails the audit" "names no configured gate" "$out"

# ---------------------------------------------------------------------------
describe "covers: is what this story changed exercised by a required gate"

# The failure this exists for: a renderer's tests lived in a browser-only
# project, that project ran in an `optional` integration gate, and the
# coverage include skipped the same directory. Each decision was right on its
# own. Together they put every test of the story's artifact where nothing
# could block on it, and "All required gates passed" printed underneath.
# gates.sh could not notice, because nothing said which paths a gate reads.
# `covers` lines say. Then the story's changed source paths - the diff against
# main, committed or not - are checked against them after every run.

git -C "$FIX" -c user.email=t@t -c user.name=t branch -M main >/dev/null 2>&1
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
mkdir -p "$FIX/src/render" "$FIX/src/core" "$FIX/src/shaders"
story "$FIX" T-1 GATES <<'EOF'
EOF
set_phase "$FIX" GATES

# No covers lines: the check does not exist, and says nothing.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
printf 'export const m = 1\n' > "$FIX/src/render/mesh.ts"
out="$(gates)"
case "$out" in
  *"changed source"*|*"covers"*) _bad "no covers lines means no check" "spoke anyway: $out" ;;
  *) _ok "no covers lines means no check" ;;
esac

# A changed path that only an OPTIONAL gate reads fails the run, and the
# message names the fix, which is the story's to make.
write_conf "$FIX" <<'EOF'
gate     | unit        | required | . | printf 'Tests  47 passed (47)\n'
gate     | integration | optional | . | printf 'Tests  25 passed (25)\n'
evidence | unit        | Tests +[1-9][0-9]* passed
evidence | integration | Tests +[1-9][0-9]* passed
covers   | unit        | src/core/**
covers   | integration | src/render/**
EOF
out="$(gates)"
assert_contains "only an optional gate reads it" "FAIL         changes: src/render/mesh.ts is exercised only by optional gate(s): integration" "$out"
assert_contains "and names the fix"              "required_gates: [integration]" "$out"
assert_contains "and the run fails"              "required gate(s) failed" "$out"

# The story escalates the gate, and the same change is covered.
story "$FIX" T-1 GATES <<'EOF'
required_gates: [integration]
EOF
out="$(gates)"
assert_contains "escalated, it counts as required" "changed source path(s), all exercised by a required gate" "$out"
assert_contains "and the run passes" "All required gates passed" "$out"

# A change a required gate reads is fine without any escalation.
story "$FIX" T-1 GATES <<'EOF'
EOF
rm -f "$FIX/src/render/mesh.ts"
printf 'export const c = 1\n' > "$FIX/src/core/thing.ts"
out="$(gates)"
assert_contains "a required gate reads it" "1 changed source path(s), all exercised by a required gate" "$out"

# A change NO gate claims is a warning: the manifest may be incomplete, or the
# file may genuinely be ungated, and only a person can tell which.
printf 'void main() {}\n' > "$FIX/src/shaders/sky.glsl"
out="$(gates)"
assert_contains "no gate claims it" "WARN         changes: src/shaders/sky.glsl is exercised by no gate with a covers line" "$out"
assert_contains "and the run still passes" "All required gates passed" "$out"

# Committed changes count the same as uncommitted ones: the diff is against
# main, not against HEAD.
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "story work" >/dev/null 2>&1
out="$(gates)"
assert_contains "committed changes are still the story's" "WARN         changes: src/shaders/sky.glsl" "$out"

# Test files are not the artifact; a changed test in a gated directory is not
# reported even when no covers line names the tests directory.
rm -f "$FIX/src/shaders/sky.glsl"
printf 'test("y", () => {})\n' > "$FIX/tests/other.test.ts"
out="$(gates)"
# Anchored to the changes report (`WARN         changes: …` / `FAIL         changes: …`).
# The file is untracked and classifies as test, so AC-4 (HARNESS-014) REQUIRES
# `    UNTRACKED  tests/other.test.ts` in this same output; a needle floating
# over the whole output was satisfied by that line and could only pass by
# breaking AC-4 (R-1b).
changes_lines="$(printf '%s\n' "$out" | grep -E '^(WARN|FAIL) +changes: ')" || changes_lines=""
case "$changes_lines" in
  *"tests/other.test.ts"*) _bad "a test file is not a changed source path" "reported it: $out" ;;
  *) _ok "a test file is not a changed source path" ;;
esac

# --fast runs the check too: GREEN is where the source first exists, and
# GREEN ends with --fast.
printf 'export const m = 1\n' > "$FIX/src/render/mesh.ts"
out="$(gates --fast)"
assert_contains "--fast checks it as well" "FAIL         changes: src/render/mesh.ts" "$out"

# --list shows the lines; --audit refuses one naming no gate.
out="$(gates --list)"
assert_contains "--list shows covers" "covers:   src/render/**" "$out"
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
covers   | unti | src/**
EOF
out="$(gates --audit)"
assert_contains "covers naming no gate fails the audit" "a \`covers\` line names no configured gate" "$out"
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(gates --audit)"
assert_contains "no covers lines is noted by the audit" "no \`covers\` lines" "$out"

rm -f "$FIX/src/render/mesh.ts" "$FIX/tests/other.test.ts"
set_phase "$FIX" ""
git -C "$FIX" checkout -q -- . 2>/dev/null
git -C "$FIX" checkout -q main 2>/dev/null

# ---------------------------------------------------------------------------
describe "ci-factor: a measurement, or nothing"

# The number is how much slower ONE TEST is on CI under this gate. It is worth
# recording because the obvious way to derive it - the gate's own wall time,
# most of which is fixed overhead - overestimates it several-fold and sends
# somebody optimising a test that was already fast enough.
write_conf "$FIX" <<'EOF'
gate      | coverage | required | . | printf 'Tests  47 passed (47)\n'
evidence  | coverage | Tests +[1-9][0-9]* passed
ci-factor | coverage | 3.4 | actions run 412, AC-4 file 1,262 ms instrumented
EOF
out="$(gates --audit)"
assert_contains "a measured factor passes the audit" "ci-factor: 3.4" "$out"

write_conf "$FIX" <<'EOF'
gate      | coverage | required | . | printf 'Tests  47 passed (47)\n'
evidence  | coverage | Tests +[1-9][0-9]* passed
ci-factor | coverage | about 14x | eyeballed it
EOF
out="$(gates --audit)"
assert_contains "a factor that is not a number fails" "is not a number" "$out"

write_conf "$FIX" <<'EOF'
gate      | coverage | required | . | printf 'Tests  47 passed (47)\n'
evidence  | coverage | Tests +[1-9][0-9]* passed
ci-factor | coverage | 3.4
EOF
out="$(gates --audit)"
assert_contains "a factor with no source fails" "has no source" "$out"

write_conf "$FIX" <<'EOF'
gate      | coverage | required | . | printf 'Tests  47 passed (47)\n'
evidence  | coverage | Tests +[1-9][0-9]* passed
ci-factor | covrage  | 3.4 | actions run 412
EOF
out="$(gates --audit)"
assert_contains "a factor naming no gate fails the audit" "names no configured gate" "$out"


# ---------------------------------------------------------------------------
describe "BLOCKED: the environment would not let the gate run"

# H16. A required gate failed eight consecutive runs on one machine with this,
# and nothing about it was a test failure:
#
#   error: failed to run custom build command for `the-project v0.1.0`
#   Caused by: could not execute process `...build-script-build` (never executed)
#   Caused by: An Application Control policy has blocked this file. (os error 4551)
#
# The runner reported FAIL, because a gate's result was a boolean derived from an
# exit code. The Stop hook then refused every report with "fix it or move the
# story back to RED", and neither applied: there was nothing to fix and the code
# was fine - the same command passed on CI three times that day. An hour and a
# user decision went into inventing the third path. BLOCKED is that path, named.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'error: could not execute process (never executed)\nCaused by: An Application Control policy has blocked this file. (os error 4551)\n'; exit 101
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(gates)"; rc=$?
assert_contains "a launch failure is BLOCKED, not FAIL" "BLOCKED      unit" "$out"
assert_contains "and says the environment refused it"   "could not launch" "$out"
assert_contains "and it is not reported as a pass"      "1 required gate(s) could not run" "$out"
assert_eq "and exits 3, distinct from a failure"        "3" "$rc"
assert_contains "and names the third path"              "pending CI" "$out"
assert_contains "RESULT=blocked in the stamp" "RESULT=blocked" \
  "$(cat "$FIX/.claude/state/last-gate-run")"

# The distinction has to cut both ways, or it is just a wider FAIL. An ordinary
# failure - the gate ran, the gate complained - is still a failure.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  2 failed, 45 passed (47)\nAssertionError: expected 3 to be 4\n'; exit 1
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(gates)"; rc=$?
assert_contains "a real failure is still FAIL" "FAIL         unit" "$out"
assert_eq "and still exits 1"                  "1" "$rc"
assert_contains "RESULT=fail in the stamp" "RESULT=fail" \
  "$(cat "$FIX/.claude/state/last-gate-run")"

# A blocked gate must never hide a broken one. When both happen the run is a
# failure: there is something to fix, and that decides what happens next.
write_conf "$FIX" <<'EOF'
gate     | unit  | required | . | printf 'Tests  2 failed, 45 passed (47)\n'; exit 1
gate     | types | required | . | printf 'error: could not execute process (never executed)\n'; exit 101
evidence | unit  | Tests +[1-9][0-9]* passed
evidence | types | Tests +[1-9][0-9]* passed
EOF
out="$(gates)"; rc=$?
assert_contains "a failure alongside a block is reported as both" "BLOCKED      types" "$out"
assert_eq "and a real failure decides the exit code" "1" "$rc"
assert_contains "RESULT=fail wins in the stamp" "RESULT=fail" \
  "$(cat "$FIX/.claude/state/last-gate-run")"

# An OPTIONAL gate the environment blocked is nobody's decision to make: it was
# never going to stop the story. It warns, like any other optional failure.
write_conf "$FIX" <<'EOF'
gate     | unit  | required | . | printf 'Tests  47 passed (47)\n'
gate     | e2e   | optional | . | printf 'error: could not execute process (never executed)\n'; exit 101
evidence | unit  | Tests +[1-9][0-9]* passed
evidence | e2e   | Tests +[1-9][0-9]* passed
EOF
out="$(gates)"; rc=$?
assert_contains "an optional blocked gate warns" "WARN         e2e" "$out"
assert_contains "and says why"                   "could not launch" "$out"
assert_eq "and the run still passes"             "0" "$rc"

# The built-in patterns describe a process that never started. They cannot
# describe every runner, so a project adds its own - and, like every other line
# in the manifest, an unusable one is refused rather than sitting there looking
# like protection.
write_conf "$FIX" <<'EOF'
gate         | unit | required | . | printf 'FATAL: emulator device offline\n'; exit 7
evidence     | unit | Tests +[1-9][0-9]* passed
blocked-when | unit | emulator device offline
EOF
out="$(gates)"; rc=$?
assert_contains "a project pattern is honoured" "BLOCKED      unit" "$out"
assert_eq "and exits 3"                         "3" "$rc"

write_conf "$FIX" <<'EOF'
gate         | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence     | unit | Tests +[1-9][0-9]* passed
blocked-when | untt | emulator device offline
EOF
out="$(gates --audit)"
assert_contains "a blocked-when naming no gate fails the audit" "names no configured gate" "$out"

write_conf "$FIX" <<'EOF'
gate         | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence     | unit | Tests +[1-9][0-9]* passed
blocked-when | unit |
EOF
out="$(gates --audit)"
assert_contains "a blocked-when with no pattern fails the audit" "has no pattern" "$out"

# ---------------------------------------------------------------------------
describe "the stamp says whether the run was a full one"

# The Stop hook decides whether a phase's gate obligation was met from this
# stamp, and `--fast` and `--gate` write it too. Without this line a `--gate
# unit` could discharge GATES, whose entire job is the full suite.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
slow     | unit | it is the whole suite under instrumentation
EOF
gates >/dev/null
assert_contains "a full run records FULL=yes" "FULL=yes" "$(cat "$FIX/.claude/state/last-gate-run")"
gates --fast >/dev/null
assert_contains "--fast records FULL=no"      "FULL=no"  "$(cat "$FIX/.claude/state/last-gate-run")"
gates --gate unit >/dev/null
assert_contains "--gate records FULL=no"      "FULL=no"  "$(cat "$FIX/.claude/state/last-gate-run")"

# ---------------------------------------------------------------------------
describe "the manifest must not change under the run"

# PORTED from manga-translator (MT-032 AC-1/AC-2), reported there off a --fast
# run. Upstream had no backstop for it.
# gates.sh parses project.conf into its evidence/floor/waiver/slow tables ONCE
# at start-up and runs the gate commands afterwards. Anything that edits the
# file in between produces a summary whose numbers are each real and whose
# PAIRING never existed - `PASS lint (0s, observed 5, floor 1)` printed as a
# clean pass while the file on disk says `floor | lint | 5`. It was reported off
# a --fast run, which is never recorded, so nothing downstream ever compares it
# to anything: its only consumer is whoever reads the summary and decides the
# phase is healthy.
#
# The race is made deterministic with no sleeps and no second process by letting
# the fixture's own gate command do the editing. That is the same interleaving
# with the timing taken out, and it is why this is testable at all.
set_phase "$FIX" ""

conf_edits_itself() {
  write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Contracts: 5 kept\n'; printf 'floor    | lint | 5\n' >> .claude/harness/project.conf
evidence | lint | Contracts: [1-9][0-9]* kept
floor    | lint | 1
EOF
}

conf_edits_itself
out="$(gates)"; rc=$?
assert_contains "a full run says the manifest changed under it" \
  "config: .claude/harness/project.conf changed while the gates were running" "$out"
assert_contains "and it is a FAIL, not a footnote under a pass" \
  "FAIL         config:" "$out"
assert_contains "and says the summary's pairings may be of no single state" \
  "may not correspond to any single state" "$out"
assert_eq "and the run exits non-zero" "1" "$rc"
case "$out" in
  *"All required gates passed"*) _bad "and does not call it a pass" "it passed anyway: $out" ;;
  *) _ok "and does not call it a pass" ;;
esac

# It was OBSERVED on a --fast run downstream. A check that only ran in full mode would fix
# nothing that was actually reported.
conf_edits_itself
out="$(gates --fast)"; rc=$?
assert_contains "--fast catches it too" \
  "config: .claude/harness/project.conf changed while the gates were running" "$out"
assert_eq "and --fast exits non-zero as well" "1" "$rc"

# Asserted where it can actually regress: these two lines live in
# the same summary/record block the new failure path lands in, so a check that
# exits early takes them with it.
assert_contains "the subset caveat survives the new failure path" \
  "This is a subset, not a verdict. The full run before REVIEW is what judges the story." "$out"
assert_contains "and so does the not-recorded line" \
  "(not recorded in the story: a partial run is not evidence of anything)" "$out"

# A run that was already failing must still report it. The manifest changing is
# a fact about the whole summary, not an alternative to the gates' own verdict.
write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Contracts: 5 kept\n'; printf 'floor    | lint | 5\n' >> .claude/harness/project.conf
gate     | unit | required | . | printf 'Tests  2 failed, 45 passed (47)\n'; exit 1
evidence | lint | Contracts: [1-9][0-9]* kept
evidence | unit | Tests +[1-9][0-9]* passed
floor    | lint | 1
EOF
out="$(gates)"; rc=$?
assert_contains "an already-failing run still reports the manifest change" \
  "config: .claude/harness/project.conf changed while the gates were running" "$out"
assert_contains "and still reports the gate that failed" "FAIL         unit" "$out"
assert_eq "and still exits 1" "1" "$rc"

describe "and it does not fire on a run that changed nothing"

# The false-positive control, and the one that matters: a check that fired
# on every run would satisfy every assertion above and be worth nothing. Nothing
# here touches project.conf after gates.sh has read it, and both modes must stay
# green - including on CI, where these are the only runs that ever happen.
write_conf "$FIX" <<'EOF'
gate     | lint | required | . | printf 'Contracts: 5 kept\n'
evidence | lint | Contracts: [1-9][0-9]* kept
floor    | lint | 1
EOF
out="$(gates)"; rc=$?
assert_contains "an ordinary full run passes" "All required gates passed" "$out"
assert_eq "and exits 0"                       "0" "$rc"
case "$out" in
  *"project.conf changed"*) _bad "an ordinary full run is not accused" "it fired anyway: $out" ;;
  *) _ok "an ordinary full run is not accused" ;;
esac

out="$(gates --fast)"; rc=$?
assert_contains "an ordinary --fast run passes" "All required gates passed" "$out"
assert_eq "and --fast exits 0"                  "0" "$rc"
case "$out" in
  *"project.conf changed"*) _bad "an ordinary --fast run is not accused" "it fired anyway: $out" ;;
  *) _ok "an ordinary --fast run is not accused" ;;
esac

# ---------------------------------------------------------------------------
describe "untracked gated files are named, whole-line, in every run (HARNESS-014, AC-4)"

# The stamp now describes the tree `git commit -a` would make, so a file the
# working tree holds and the commit will not - a stray .patch, a new test nobody
# staged - is judged by the gates and absent from the record. gates.sh names each
# one as `    UNTRACKED  <path>`: four spaces, the word, two spaces, the path,
# nothing after. Matched WHOLE here, by grep -cx, never by the bare word - a
# needle of `UNTRACKED` would be satisfied by the sentence explaining it.
count_line() { printf '%s\n' "$2" | grep -cxF -- "$1"; }   # <exact line> <text>
count_re()   { awk 'BEGIN { re = ARGV[1]; ARGV[1] = "" } $0 ~ re { n++ } END { print n + 0 }' "$1" <<< "$2"; }
fix_commit() { git -C "$FIX" add -A -- . ':!.claude/state' >/dev/null 2>&1
               git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "$1" >/dev/null 2>&1; }

set_phase "$FIX" ""
git -C "$FIX" checkout -q -- . 2>/dev/null
# Everything from here to the end of the HARNESS-015 blocks records into T-1, so
# it runs on T-1's own branch (HARNESS-026 refuses a record made from another).
# -B resets the branch the covers block left behind to main's HEAD, so the state
# is main's, and the commits below land on the story branch. Back to main after
# the HARNESS-015 blocks.
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
story "$FIX" T-1 GATES </dev/null
fix_commit "clean tree, story in GATES"        # nothing untracked, nothing dirty
set_phase "$FIX" GATES

# One untracked file per class the specimen had, plus the two the rule must
# leave alone: a root docs file and a harness markdown file.
mkdir -p "$FIX/handoff" "$FIX/.claude/commands"
printf 'diff --git a/x b/x\n' > "$FIX/handoff/x.patch"          # source
printf 'test("stray", () => {})\n' > "$FIX/tests/stray.test.ts"  # test
printf '# stray notes\n' > "$FIX/notes.md"                       # docs
printf '# a prompt\n' > "$FIX/.claude/commands/x.md"             # harness markdown

out="$(gates --fast)"; rc=$?
assert_eq "--fast names the stray patch, whole line" 1 "$(count_line '    UNTRACKED  handoff/x.patch' "$out")"
assert_eq "--fast names the stray test, whole line"  1 "$(count_line '    UNTRACKED  tests/stray.test.ts' "$out")"
assert_eq "and exactly those two: one UNTRACKED line per untracked gated file" 2 "$(count_re '^    UNTRACKED  ' "$out")"
assert_eq "AC-4 control: the root docs file is not named"       0 "$(count_re 'UNTRACKED.*notes\.md' "$out")"
assert_eq "AC-4 control: the harness markdown file is not named" 0 "$(count_re 'UNTRACKED.*\.claude/commands/x\.md' "$out")"
assert_contains "and says, in words, that they are not part of the recorded tree" "not part of the recorded tree" "$out"
assert_contains "and names the remedy for a file the story owns: stage it" "git add" "$out"
assert_contains "and the remedy for a stray the user keeps: .git/info/exclude" ".git/info/exclude" "$out"
assert_eq "a --fast run is partial, so it is NOT refused: exit is the gates' own" 0 "$rc"
assert_eq "and its not-recorded line is the ordinary partial-run one" 1 \
  "$(count_re '^\(not recorded in the story: a partial run is not evidence of anything\)$' "$out")"
assert_eq "not a refusal for untracked files" 0 "$(count_re '^\(not recorded: .*untracked gated file' "$out")"

# ---------------------------------------------------------------------------
describe "a full run with an active story refuses to record while anything is named (HARNESS-014, AC-5, Option R)"

# The record says "the gates ran against exactly this tree". While the working
# tree holds a gated file the stamp cannot describe, that sentence is false, so
# the run leaves ## Gate results byte-for-byte alone, says why on one line, and
# exits 1 even though every gate passed. The user's decision, 2026-09-24 (PO-E).
cp "$FIX/docs/backlog/stories/T-1.md" "$FIX/.claude/state/T-1.before"
out="$(gates)"; rc=$?
assert_eq "the full run still names each file" 2 "$(count_re '^    UNTRACKED  ' "$out")"
assert_eq "AC-5: ## Gate results is byte-for-byte unchanged" yes \
  "$(cmp -s "$FIX/.claude/state/T-1.before" "$FIX/docs/backlog/stories/T-1.md" && printf yes || printf no)"
assert_eq "AC-5: nothing claims to have recorded" 0 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "AC-5: one line beginning '(not recorded: ' gives the reason - N untracked gated file(s)" 1 \
  "$(count_re '^\(not recorded: .*2 untracked gated file' "$out")"
assert_eq "AC-5: and the run exits 1 although every gate passed" 1 "$rc"
assert_contains "the gates' own verdict is still printed - the refusal is about the record, not the code" \
  "All required gates passed" "$out"
# PO-F, a contract pin rather than an AC: a refused run must not discharge GATES.
assert_eq "C-4: the stamp of a refused run says FULL=no" 1 \
  "$(count_re '^FULL=no$' "$(tr -d '\r' < "$FIX/.claude/state/last-gate-run")")"

# Precedence: a BLOCKED run that is refused exits 1, not 3 - nothing was recorded
# for a PO decision to stand on.
write_conf "$FIX" <<'EOF'
gate     | unit  | required | . | printf 'Tests  47 passed (47)\n'
gate     | types | required | . | printf 'error: could not execute process (never executed)\n'; exit 101
evidence | unit  | Tests +[1-9][0-9]* passed
evidence | types | Tests +[1-9][0-9]* passed
EOF
out="$(gates)"; rc=$?
assert_contains "a blocked gate is still reported as BLOCKED" "BLOCKED      types" "$out"
assert_eq "C-4: but a refused run exits 1, not 3" 1 "$rc"
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
git -C "$FIX" add .claude/harness/project.conf >/dev/null 2>&1   # the conf only; the strays stay untracked
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "conf back to one passing gate" >/dev/null 2>&1

# AC-5: with NO active story - CI, and ci-local.sh's gates step - there is no
# refusal. The files are still named; the exit is the gates' own.
set_phase "$FIX" ""
out="$(gates)"; rc=$?
assert_eq "no active story: the files are still named" 2 "$(count_re '^    UNTRACKED  ' "$out")"
assert_eq "no active story: exit is the gates' own, 0" 0 "$rc"
assert_eq "no active story: the not-recorded line is the ordinary no-story one" 1 \
  "$(count_re '^\(not recorded: no active story' "$out")"
assert_eq "no active story: and there is no refusal for untracked files" 0 \
  "$(count_re '^\(not recorded: .*untracked gated file' "$out")"
set_phase "$FIX" GATES

# AC-5 control (i): once the named files are STAGED, the same run records and
# exits 0, and names nothing.
git -C "$FIX" add handoff/x.patch tests/stray.test.ts >/dev/null 2>&1
out="$(gates)"; rc=$?
assert_eq "AC-5 control: staged, nothing is named"        0 "$(count_re 'UNTRACKED' "$out")"
assert_eq "AC-5 control: staged, the run records"         1 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "AC-5 control: staged, the run exits 0"         0 "$rc"
assert_eq "AC-5 control: and ## Gate results now carries a tree stamp" 1 \
  "$(count_re '^    tree:   [0-9a-f]{40}$' "$(tr -d '\r' < "$FIX/docs/backlog/stories/T-1.md")")"
assert_eq "C-4: the stamp of a recorded run says FULL=yes" 1 \
  "$(count_re '^FULL=yes$' "$(tr -d '\r' < "$FIX/.claude/state/last-gate-run")")"
git -C "$FIX" reset -q -- handoff/x.patch tests/stray.test.ts 2>/dev/null   # untracked again
git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null           # record wiped

# AC-5 control (ii) and AC-6: excluded through .git/info/exclude, the same run
# records and exits 0. This is the remedy the refusal points a user to for a
# stray they mean to keep, so it has to actually work.
cp "$FIX/.git/info/exclude" "$FIX/.claude/state/exclude.before"
printf 'handoff/x.patch\ntests/stray.test.ts\n' >> "$FIX/.git/info/exclude"
out="$(gates)"; rc=$?
assert_eq "AC-6: excluded via .git/info/exclude, nothing is named" 0 "$(count_re 'UNTRACKED' "$out")"
assert_eq "AC-5 control: excluded, the run records"            1 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "AC-5 control: excluded, the run exits 0"            0 "$rc"
git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null

# AC-6 control: with the exclude rule removed, the same files are named again
# and the run is refused again.
cp "$FIX/.claude/state/exclude.before" "$FIX/.git/info/exclude"
out="$(gates)"; rc=$?
assert_eq "AC-6 control: exclude rule removed, both files are named again" 2 "$(count_re '^    UNTRACKED  ' "$out")"
assert_eq "AC-6 control: and the run is refused again" 1 "$rc"

# AC-6, the other ignore file: a .gitignore rule for one stray silences that one
# and only that one. .gitignore is itself gated and tracked, so editing it is an
# ordinary edit the stamp covers - and the record is still refused, because the
# other stray is still there.
printf 'handoff/\n' >> "$FIX/.gitignore"
out="$(gates)"; rc=$?
assert_eq "AC-6: a .gitignore'd stray is not named"      0 "$(count_line '    UNTRACKED  handoff/x.patch' "$out")"
assert_eq "AC-6: while the other stray still is"          1 "$(count_line '    UNTRACKED  tests/stray.test.ts' "$out")"
assert_eq "and the count in the reason says 1, not 2" 1 "$(count_re '^\(not recorded: .*1 untracked gated file' "$out")"
assert_eq "and one stray is enough to refuse"             1 "$rc"
git -C "$FIX" checkout -q -- .gitignore 2>/dev/null

# AC-4 control: with no untracked GATED file - the docs and the prompt still
# untracked - no UNTRACKED line appears at all, and the run records.
rm -rf "$FIX/handoff" "$FIX/tests/stray.test.ts"
out="$(gates)"; rc=$?
assert_eq "AC-4 control: no untracked gated file, no UNTRACKED anywhere in the output" 0 "$(count_re 'UNTRACKED' "$out")"
assert_eq "AC-4 control: and no untracked: lead line either" 0 "$(count_re 'not part of the recorded tree' "$out")"
assert_eq "and the run records" 1 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "and exits 0"         0 "$rc"

rm -f "$FIX/notes.md" "$FIX/.claude/commands/x.md" "$FIX/.claude/state/T-1.before" "$FIX/.claude/state/exclude.before"
git -C "$FIX" checkout -q -- . 2>/dev/null
set_phase "$FIX" ""

# ---------------------------------------------------------------------------
describe "ondemand: a gate marked on request is left out of a full run and of --fast (HARNESS-015, AC-1)"

# `slow` only keeps a gate out of --fast, so a `mutation` gate marked slow still
# ran on every full gates.sh run: every story's GATES and every PR's CI job. On
# HARNESS-014 that class of work was 2h20 of a 7.5h story and found nothing.
# `ondemand | <id> | <why>` says the gate runs only when somebody asks for it -
# `--gate <id>`, or a story that names it in `required_gates` - and a run that
# leaves it out says so on ONE whole line, with the reason and the command.
#
# The gate command writes a MARKER. Whether the command ran is then a fact about
# the filesystem rather than a reading of the summary, and it is asserted on
# both sides: absent after a full run and after --fast, present after --gate and
# after a story escalation.
MARKER="$FIX/.claude/state/mutation-ran"
ONREQ='ON REQUEST   mutation (not run: per-story cost the user declined; bash scripts/gates.sh --gate mutation)'
marker_state() { if [ -e "$MARKER" ]; then printf present; else printf absent; fi; }

write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | build    | required | . | printf 'Bundled 3 targets\n'
gate     | mutation | optional | . | touch .claude/state/mutation-ran; printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | build    | Bundled [1-9][0-9]* targets
evidence | mutation | Killed [0-9]+ of
slow     | build    | a release bundle, which RED and GREEN have no use for
ondemand | mutation | per-story cost the user declined
EOF
story "$FIX" T-1 GATES </dev/null
fix_commit "ondemand fixture: a mutation gate on request"
set_phase "$FIX" GATES

rm -f "$MARKER"
out="$(gates)"; rc=$?
assert_eq "a full run does not execute the on-request gate's command" absent "$(marker_state)"
assert_eq "and reports it once, whole line: ON REQUEST, the reason, and the command that runs it" \
  1 "$(count_line "$ONREQ" "$out")"
assert_eq "it is not reported UNCONFIGURED" 0 "$(count_re '^UNCONFIGURED +mutation' "$out")"
assert_eq "and it is counted in none of ran, unconfigured or known" \
  1 "$(count_re '^All required gates passed \(2 ran, 0 unconfigured, 0 known\)\.$' "$out")"
assert_eq "the run exits 0: the on-request gate does not touch the verdict" 0 "$rc"
assert_eq "and the recorded ## Gate results carries the ON REQUEST line" \
  1 "$(count_line "    $ONREQ" "$(tr -d '\r' < "$FIX/docs/backlog/stories/T-1.md")")"
assert_eq "and the stamp still says FULL=yes: the on-request gate is not part of what a full run judges" \
  1 "$(count_re '^FULL=yes$' "$(tr -d '\r' < "$FIX/.claude/state/last-gate-run")")"

rm -f "$MARKER"
out="$(gates --fast)"; rc=$?
assert_eq "--fast does not execute it either" absent "$(marker_state)"
assert_eq "--fast reports the same ON REQUEST line, once" 1 "$(count_line "$ONREQ" "$out")"
assert_eq "and --fast's skipped list names the slow gate only: on request is reported once, not twice" \
  1 "$(count_line '--fast skipped: build' "$out")"
assert_eq "--fast exits 0" 0 "$rc"

# AC-1 control (i): asked for by name, it runs.
rm -f "$MARKER"
out="$(gates --gate mutation)"; rc=$?
assert_eq "AC-1 control: --gate mutation executes the command" present "$(marker_state)"
assert_eq "and reports it as PASS, with its observed count" 1 "$(count_re '^PASS +mutation \([0-9]+s, observed 12\)$' "$out")"
assert_eq "and prints no ON REQUEST line" 0 "$(count_re '^ON REQUEST ' "$out")"

# AC-1 control (ii): a story that escalates the gate asked for it.
story "$FIX" T-1 GATES <<'EOF'
required_gates: [mutation]
EOF
fix_commit "the story escalates mutation"
rm -f "$MARKER"
out="$(gates)"; rc=$?
assert_eq "AC-1 control: a story with required_gates: [mutation] gets it run on a full run" present "$(marker_state)"
assert_eq "with the existing escalation suffix in the gate header" \
  1 "$(count_line '=== gate: mutation (required (required by story T-1)) ===' "$out")"
assert_eq "and no ON REQUEST line" 0 "$(count_re '^ON REQUEST ' "$out")"
assert_eq "and the run passes with the gate counted as ran" \
  1 "$(count_re '^All required gates passed \(3 ran, 0 unconfigured, 0 known\)\.$' "$out")"
story "$FIX" T-1 GATES </dev/null
fix_commit "the story no longer escalates mutation"

# C-2: on-request is decided before configured-ness. This repository's own
# project.conf declares `mutation` with no command, and after this story it is
# ON REQUEST there rather than UNCONFIGURED.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . |
evidence | unit     | Tests +[1-9][0-9]* passed
ondemand | mutation | no tool chosen yet; run it with /audit-mutations
EOF
out="$(gates)"; rc=$?
assert_eq "an on-request gate with no command is ON REQUEST, not UNCONFIGURED" \
  1 "$(count_line 'ON REQUEST   mutation (not run: no tool chosen yet; run it with /audit-mutations; bash scripts/gates.sh --gate mutation)' "$out")"
assert_eq "and UNCONFIGURED does not name it" 0 "$(count_re '^UNCONFIGURED +mutation' "$out")"
assert_eq "and the result counts it in nothing" \
  1 "$(count_re '^All required gates passed \(1 ran, 0 unconfigured, 0 known\)\.$' "$out")"
assert_eq "exit 0" 0 "$rc"

# C-4: --list shows the line beside the gate.
out="$(gates --list)"
assert_contains "--list shows the on-request row with the reason and the command" \
  "on-request: no tool chosen yet; run it with /audit-mutations (run with --gate mutation)" "$out"

# ---------------------------------------------------------------------------
describe "ondemand: an on-request gate cannot be required (HARNESS-015, AC-2)"

# A required gate that no full run ever judges is a hole shaped like a gate.
# The audit refuses the combination, and refuses the two ways an `ondemand`
# line can be empty of meaning - naming no gate, or giving no reason - in the
# words `slow` already uses for the same faults.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | required | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | mutation | Killed [0-9]+ of
ondemand | mutation | per-story cost the user declined
EOF
out="$(gates --audit)"; rc=$?
assert_eq "ondemand on a required gate fails the audit, naming the gate and why" \
  1 "$(count_re '^FAIL +mutation +an on-request gate cannot be required: no full run would ever judge it$' "$out")"
assert_eq "and the audit exits 1" 1 "$rc"
assert_eq "and counts it as a manifest problem" 1 "$(count_re '^1 manifest problem\(s\)\.$' "$out")"

write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | mutation | Killed [0-9]+ of
ondemand | mutatoin | a typo, so the gate it meant runs on every full run
EOF
out="$(gates --audit)"; rc=$?
assert_eq "ondemand naming no configured gate fails the audit" \
  1 "$(count_re '^FAIL +mutatoin +an `ondemand` line names no configured gate$' "$out")"
assert_eq "and exits 1" 1 "$rc"

write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | mutation | Killed [0-9]+ of
ondemand | mutation |
EOF
out="$(gates --audit)"; rc=$?
assert_eq "ondemand with no reason fails the audit" \
  1 "$(count_re '^FAIL +mutation +marked on-request with no reason; say why it is not run per story$' "$out")"
assert_eq "and exits 1" 1 "$rc"

# AC-2 control: the same line on an OPTIONAL gate is what the story asks every
# stack profile to carry, and the audit passes it.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | mutation | Killed [0-9]+ of
ondemand | mutation | per-story cost the user declined
EOF
out="$(gates --audit)"; rc=$?
assert_eq "AC-2 control: the same line on an optional gate passes the audit" 0 "$rc"
assert_eq "and the audit says so" 1 "$(count_re '^Manifest audit passed\.$' "$out")"
assert_eq "and no FAIL names the gate" 0 "$(count_re '^FAIL +mutation' "$out")"

# C-3: "required" means required IN project.conf. A story escalation makes the
# gate required for that story's runs - and runs it, above - without making the
# manifest wrong.
story "$FIX" T-1 GATES <<'EOF'
required_gates: [mutation]
EOF
out="$(gates --audit)"; rc=$?
assert_eq "a story escalation does not make the audit fail: the manifest itself is fine" 0 "$rc"
assert_eq "and no FAIL names the gate" 0 "$(count_re '^FAIL +mutation' "$out")"
story "$FIX" T-1 GATES </dev/null

# ---------------------------------------------------------------------------
describe "ondemand: the audit refuses a mutation gate with no ondemand line (HARNESS-039)"

# Issue #104 Symptom B. `slow` keeps a gate out of --fast; only `ondemand`
# keeps it out of a FULL run. A consumer's project.conf with a `mutation` gate,
# a `slow` line and no `ondemand` line passed the audit, so the day the tool is
# installed every story's GATES and every PR's CI runs it. The message is
# pinned byte for byte (story C-3) and matched WHOLE: `^FAIL +mutation +` ...
# `$`. H39_ANY is the same message under ANY id - the controls use it, because
# a rule that judged every gate except `mutation` (DV-3's mutation) prints the
# message under `unit`, which the mutation-anchored needle cannot see.
H39_MSG='no `ondemand \| mutation \| <why>` line, so every full run executes it; `slow` alone only leaves it out of --fast$'
H39_LINE="^FAIL +mutation +$H39_MSG"
H39_ANY="^FAIL +[^ ]+ +$H39_MSG"

# AC-1: the bug. The AC-2 manifest of HARNESS-015 above, with the `ondemand`
# line replaced by a `slow` line (story C-9). No other fault in it, so the
# problem count is exactly this one.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | mutation | Killed [0-9]+ of
slow     | mutation | re-runs the suite once per mutant
EOF
out="$(gates --audit)"; rc=$?
assert_eq "AC-1: a mutation gate with slow and no ondemand line fails the audit with exactly one whole-line FAIL naming it" \
  1 "$(count_re "$H39_LINE" "$out")"
assert_eq "AC-1: and it is counted as the one manifest problem" \
  1 "$(count_re '^1 manifest problem\(s\)\.$' "$out")"
assert_eq "AC-1: and the audit no longer says it passed" \
  0 "$(count_re '^Manifest audit passed\.$' "$out")"
assert_eq "AC-1: and the audit exits 1" 1 "$rc"

# AC-4a: the same, with an EMPTY command - the shape the template ships before
# bootstrap. The cost arrives the day the command is filled in.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . |
evidence | unit     | Tests +[1-9][0-9]* passed
EOF
out="$(gates --audit)"; rc=$?
assert_eq "AC-4a: an unconfigured (empty-command) mutation gate with no ondemand line is still flagged, whole line" \
  1 "$(count_re "$H39_LINE" "$out")"
assert_eq "AC-4a: and it is counted as the one manifest problem" \
  1 "$(count_re '^1 manifest problem\(s\)\.$' "$out")"
assert_eq "AC-4a: and the audit exits 1" 1 "$rc"

# C-4: regardless of `required`. A required mutation gate with no ondemand line
# gets this FAIL; it has no ondemand line, so the "cannot be required" FAIL of
# HARNESS-015 does not fire alongside it.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | required | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | mutation | Killed [0-9]+ of
EOF
out="$(gates --audit)"; rc=$?
assert_eq "C-4: a REQUIRED mutation gate with no ondemand line is flagged too, whole line" \
  1 "$(count_re "$H39_LINE" "$out")"
assert_eq "C-4: and it is the one manifest problem" \
  1 "$(count_re '^1 manifest problem\(s\)\.$' "$out")"
assert_eq "C-4: and the audit exits 1" 1 "$rc"

# AC-2: control - the line is what passes. The AC-1 manifest plus the line.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
evidence | mutation | Killed [0-9]+ of
slow     | mutation | re-runs the suite once per mutant
ondemand | mutation | per-story cost the user declined
EOF
out="$(gates --audit)"; rc=$?
assert_eq "AC-2 control: with the ondemand line the new message appears under no id" \
  0 "$(count_re "$H39_ANY" "$out")"
assert_eq "AC-2 control: and no FAIL names mutation" 0 "$(count_re '^FAIL +mutation' "$out")"
assert_eq "AC-2 control: and the audit says it passed" 1 "$(count_re '^Manifest audit passed\.$' "$out")"
assert_eq "AC-2 control: and exits 0" 0 "$rc"

# AC-3: control - only the mutation gate. Other ids never need the line, with
# or without a mutation gate beside them; and the rule demands the line of a
# gate that exists, never the gate.
write_conf "$FIX" <<'EOF'
gate     | unit        | required | . | printf 'Tests  47 passed (47)\n'
gate     | build       | required | . | printf 'built ok\n'
gate     | integration | optional | . | printf 'Tests  3 passed (3)\n'
evidence | unit        | Tests +[1-9][0-9]* passed
evidence | build       | built ok
evidence | integration | Tests +[1-9][0-9]* passed
slow     | integration | starts a database
EOF
out="$(gates --audit)"; rc=$?
assert_eq "AC-3 control: with no mutation gate at all, the new message appears under no id" \
  0 "$(count_re "$H39_ANY" "$out")"
assert_eq "AC-3 control: and nothing FAILs at all" 0 "$(count_re '^FAIL ' "$out")"
assert_eq "AC-3 control: and the audit says it passed" 1 "$(count_re '^Manifest audit passed\.$' "$out")"
assert_eq "AC-3 control: and exits 0" 0 "$rc"

write_conf "$FIX" <<'EOF'
gate     | unit        | required | . | printf 'Tests  47 passed (47)\n'
gate     | build       | required | . | printf 'built ok\n'
gate     | integration | optional | . | printf 'Tests  3 passed (3)\n'
gate     | mutation    | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit        | Tests +[1-9][0-9]* passed
evidence | build       | built ok
evidence | integration | Tests +[1-9][0-9]* passed
evidence | mutation    | Killed [0-9]+ of
slow     | mutation    | re-runs the suite once per mutant
ondemand | mutation    | per-story cost the user declined
EOF
out="$(gates --audit)"; rc=$?
assert_eq "AC-3 control: beside a mutation gate that has the line, unit/build/integration are not asked for one" \
  0 "$(count_re "$H39_ANY" "$out")"
assert_eq "AC-3 control: and nothing FAILs at all" 0 "$(count_re '^FAIL ' "$out")"
assert_eq "AC-3 control: and the audit says it passed" 1 "$(count_re '^Manifest audit passed\.$' "$out")"
assert_eq "AC-3 control: and exits 0" 0 "$rc"

# AC-4b: the written limit of the rule. A mutation tool under another id is not
# caught - the id is compared exactly. A later story that names a convention for
# a second mutation gate changes this assertion deliberately.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutants  | optional | . | cargo mutants
evidence | unit     | Tests +[1-9][0-9]* passed
EOF
out="$(gates --audit)"; rc=$?
assert_eq "AC-4b limit: a mutation tool under the id 'mutants' is not flagged - the rule is on the id 'mutation' only" \
  0 "$(count_re "$H39_ANY" "$out")"
assert_eq "AC-4b limit: and the audit says it passed" 1 "$(count_re '^Manifest audit passed\.$' "$out")"
assert_eq "AC-4b limit: and exits 0" 0 "$rc"

# AC-5: this repository's own project.conf - what the CI step at gates.yml's
# `--audit` judges on this tree - still passes: it carries `ondemand | mutation`.
#
# So it is audited IN this tree, as CI does it (HARNESS-048). It used to be
# copied into $FIX and audited there, and --audit checks that every gate's cwd
# exists: a consuming project whose gates run in a subdirectory (`src-tauri`)
# failed this on a fixture that has no such directory, while its real audit -
# the one CI runs - passed. --audit runs no gate and takes no run lock, so it is
# safe here beside a gate run in flight.
out="$( cd "$REPO_ROOT" && bash scripts/gates.sh --audit 2>&1 )"; rc=$?
assert_eq "AC-5: this repository's own project.conf draws the new message under no id" \
  0 "$(count_re "$H39_ANY" "$out")"
assert_eq "AC-5: and its audit says it passed" 1 "$(count_re '^Manifest audit passed\.$' "$out")"
assert_eq "AC-5: and exits 0" 0 "$rc"

rm -f "$MARKER"
git -C "$FIX" checkout -q -- . 2>/dev/null
set_phase "$FIX" ""
git -C "$FIX" checkout -q main 2>/dev/null   # off T-1's branch again (see HARNESS-014 above)

# ============================================================================
# HARNESS-024: parsing project.conf spawns no process per field
# ============================================================================
#
# gates.sh parsed project.conf with a `sed` trim() and a `cut -d'|'` per field:
# 735 external processes for one `--list` of upstream's own 283-line manifest
# (ea0fba0), 647 of them the same `sed`. The rewrite is pure bash, and it can go
# wrong in four ways, each of which a block below exists to catch:
#
#   * still fork per line, or per padding line        -> AC-1, AC-2 (traces)
#   * parse LESS (skip a table, a kind, a line)       -> AC-3, byte-identity
#   * lose everything after an embedded `|`           -> AC-4, whole values
#   * trim a different character class than [:space:]  -> AC-5, equivalence
#
# Every manifest here is the SYNTHETIC one in fixtures/manifest/ (see _lib.sh),
# never the real .claude/harness/project.conf: this suite ships to consuming
# projects, where an assertion about upstream's manifest values would fail.
# doctor.test.sh holds the doctor.sh and task.sh halves.

_h24="$(mktemp -d 2>/dev/null || mktemp -d -t h024.XXXXXX)"
MFX="$(manifest_fixture)"
trap 'rm -rf "$FIX" "$MFX" "$_h24"' EXIT
crlf_copy "$MANIFEST_FIXTURES/project.conf" "$_h24/crlf.conf"
pad_manifest "$MANIFEST_FIXTURES/project.conf" "$_h24/padded.conf"

describe "HARNESS-024 C-3 instrument: the trace counter counts processes, and only processes"

# The negative control for AC-1's two zeros. A counter that counts nothing
# satisfies "zero sed" and "at most 20" against any implementation, so it is
# first shown counting a trace whose answer is known: three externals (sed, cut,
# tr), a builtin (printf) that must not be counted, and a function (f) that must
# not be counted even though bash -x traces it like a command.
cat > "$_h24/ctl.sh" <<'CTL'
f() { :; }
f
printf 'x\n' | sed 's/x/y/' | cut -c1 >/dev/null
v="$(printf 'ab' | tr a b)"
f
CTL
bash -x "$_h24/ctl.sh" 2> "$_h24/ctl.trace" >/dev/null
_ctl="$(trace_externals "$_h24/ctl.trace" "$_h24/ctl.sh")"
assert_eq "the counter sees the one sed in a trace with one sed" "1" "$(ext_count "$_ctl" sed)"
assert_eq "the counter sees the one cut in a trace with one cut" "1" "$(ext_count "$_ctl" cut)"
assert_eq "a builtin (printf) is not counted as a process"       "0" "$(ext_count "$_ctl" printf)"
assert_eq "a function the script defines is not counted"         "0" "$(ext_count "$_ctl" f)"
assert_eq "and the total is exactly the three externals"         "3" "$(ext_count "$_ctl" TOTAL)"

describe "HARNESS-024 fixtures: the padded copy is the same manifest, 100 lines longer"

# AC-2 compares a manifest with its padded copy. That comparison means nothing
# unless the copy really is 100 lines longer, really carries the tab-indented
# comments AC-2 names, and really means the same thing - checked here by its
# --list output being the golden's, below, in the traced run.
assert_eq "the padded copy is exactly 100 lines longer" \
  "$(( $(awk 'END { print NR }' "$MANIFEST_FIXTURES/project.conf") + 100 ))" \
  "$(awk 'END { print NR }' "$_h24/padded.conf")"
assert_eq "and 20 of the added lines are TAB-indented comments" \
  "$(( $(awk '/^\t#/ { n++ } END { print n + 0 }' "$MANIFEST_FIXTURES/project.conf") + 20 ))" \
  "$(awk '/^\t#/ { n++ } END { print n + 0 }' "$_h24/padded.conf")"
assert_eq "and padding precedes the manifest's last line" \
  "#	gate | pad99 | required | . | exit 1" \
  "$(awk '{ prev = cur; cur = $0 } END { print prev }' "$_h24/padded.conf")"

describe "HARNESS-024 AC-1: --list over the synthetic manifest spawns no sed, no cut, and at most 20 processes"

use_manifest "$MFX" "$MANIFEST_FIXTURES/project.conf"
_list_plain="$(trace_script "$MFX" "$_h24/t.list.plain" gates.sh --list)"
assert_eq "the traced --list exits 0" "0" "$(cat "$_h24/t.list.plain.rc")"
assert_eq "AC-1: tracing --list over the synthetic manifest records zero sed processes" \
  "0" "$(ext_count "$_list_plain" sed)"
assert_eq "AC-1: tracing --list over the synthetic manifest records zero cut processes" \
  "0" "$(ext_count "$_list_plain" cut)"
_total="$(ext_count "$_list_plain" TOTAL)"
if [ "$_total" -le 20 ]; then
  _ok "AC-1: tracing --list over the synthetic manifest records at most 20 external processes"
else
  _bad "AC-1: tracing --list over the synthetic manifest records at most 20 external processes" \
    "counted $_total; by command:
$_list_plain"
fi

describe "HARNESS-024 AC-2: gates.sh spawns no more processes for a longer manifest"

# Each invocation traced over the manifest and over its padded copy. The counts
# must be EQUAL: a parser that still forks per line pays for every padding line.
# The shipped parser fails all three, because each padding line costs a `sed`.
use_manifest "$MFX" "$_h24/padded.conf"
_list_pad="$(trace_script "$MFX" "$_h24/t.list.pad" gates.sh --list)"
same_count "AC-2: gates.sh --list spawns as many processes over the padded manifest as over the plain one" \
  "$_list_plain" "$_list_pad"
printf '%s\nrc=%s\n' "$(cat "$_h24/t.list.pad.out")" "$(cat "$_h24/t.list.pad.rc")" > "$_h24/t.list.pad.golden"
golden_check "and the padded copy lists exactly what the plain one does (the padding means nothing)" \
  "$MANIFEST_FIXTURES/project.list.golden" "$_h24/t.list.pad.golden"

use_manifest "$MFX" "$MANIFEST_FIXTURES/project.conf"
_audit_plain="$(trace_script "$MFX" "$_h24/t.audit.plain" gates.sh --audit)"
use_manifest "$MFX" "$_h24/padded.conf"
_audit_pad="$(trace_script "$MFX" "$_h24/t.audit.pad" gates.sh --audit)"
same_count "AC-2: gates.sh --audit spawns as many processes over the padded manifest as over the plain one" \
  "$_audit_plain" "$_audit_pad"
printf '%s\nrc=%s\n' "$(cat "$_h24/t.audit.pad.out")" "$(cat "$_h24/t.audit.pad.rc")" > "$_h24/t.audit.pad.golden"
golden_check "and the padded copy audits exactly as the plain one does" \
  "$MANIFEST_FIXTURES/project.audit.golden" "$_h24/t.audit.pad.golden"

use_manifest "$MFX" "$MANIFEST_FIXTURES/project.conf"
_run_plain="$(trace_script "$MFX" "$_h24/t.run.plain" gates.sh)"
use_manifest "$MFX" "$_h24/padded.conf"
_run_pad="$(trace_script "$MFX" "$_h24/t.run.pad" gates.sh)"
same_count "AC-2: a full gates.sh run spawns as many processes over the padded manifest as over the plain one" \
  "$_run_plain" "$_run_pad"

describe "HARNESS-024 AC-3: gates.sh prints what it printed before the rewrite, byte for byte"

# Goldens captured from the unchanged gates.sh (ea0fba0) through the same
# _lib.sh functions, over the same fixture: the well-formed manifest, the
# broken one (every --audit failure path), and a CRLF copy of the well-formed
# one. Output and exit status; the full run's `(<N>s` is the only thing
# normalised. This is what stops "parse faster" being done by "parse less".
for _c in project broken crlf; do
  case "$_c" in crlf) _conf="$_h24/crlf.conf" ;; *) _conf="$MANIFEST_FIXTURES/$_c.conf" ;; esac
  use_manifest "$MFX" "$_conf"
  for _m in list audit run; do
    gates_golden "$MFX" "$_m" > "$_h24/$_c.$_m"
    golden_check "AC-3: gates.sh $([ "$_m" = run ] && printf 'full run' || printf -- '--%s' "$_m") over $_c.conf is byte-identical to the pre-rewrite golden" \
      "$MANIFEST_FIXTURES/$_c.$_m.golden" "$_h24/$_c.$_m"
  done
done

describe "HARNESS-024 AC-4: a value containing | is the whole remainder of its line"

# Read out of the AC-3 runs over the well-formed manifest. Each needle is the
# WHOLE value, so a split that stops at the first embedded pipe (`field` where
# `rest` belongs, or `IFS='|' read`) leaves a prefix and fails the match.
_l="$(cat "$_h24/project.list")"; _a="$(cat "$_h24/project.audit")"; _r="$(cat "$_h24/project.run")"
assert_contains "AC-4 -f3-: an evidence regex keeps its alternation" \
  "evidence: Tests +[1-9][0-9]* passed|Checks [0-9]+ ok" "$_l"
assert_contains "AC-4 -f3-: a blocked-when regex keeps all three alternations" \
  "blocked-when: alpha launch failed|beta refused to start|no device here" "$_l"
assert_contains "AC-4 -f3-: a slow reason containing | is kept whole" \
  "slow:     instrumented | about 3x the plain run (left out of --fast)" "$_l"
assert_contains "AC-4 -f3-: a waiver containing | is kept whole" \
  "waiver:   docs build needs a renderer this machine lacks | issue 12" "$_l"
assert_contains "AC-4 -f3-: an ondemand reason containing | is kept whole" \
  "on-request: minutes per mutant | run with --gate mutation (run with --gate mutation)" "$_l"
assert_contains "AC-4 -f3-: a ci-factor whose source contains | is kept whole" \
  "ci-factor: 1.5 | actions run 412 | lint job | step 3" "$_l"
assert_contains "AC-4 -f3-: a ci-factor with an empty second field is kept whole" \
  "ci-factor: 2.5 |  | measured in actions run 413" "$_l"
assert_contains "AC-4 -f5-: a gate command with | and || is listed whole" \
  "lint         required  .      printf 'Checked 5 files|ok\n' | while IFS= read -r l; do printf '%s\n' \"\$l\"; done || exit 1" "$_l"
assert_contains "AC-4 -f5-: and is echoed whole before it runs" \
  "=== gate: lint (required) ===
printf 'Checked 5 files|ok\n' | while IFS= read -r l; do printf '%s\n' \"\$l\"; done || exit 1" "$_r"
assert_contains "AC-4 -f5-: and runs whole, so its evidence is observed and floored" \
  "PASS         lint (Ns, observed 5, floor 3)" "$_r"
assert_contains "AC-4 -f3-: a blocked-when regex matched on its THIRD alternation still names the launch failure" \
  "WARN         e2e (Ns, could not launch: no device here, optional)" "$_r"
# The second level: a ci-factor value re-split into its number (-f1) and its
# source (-f2-). A number taken with `rest` is `1.5 | actions run ...`, not a
# number; a source taken with `field` after an empty second field is empty.
assert_eq "AC-4 second level: the audit accepts every ci-factor (number -f1, source -f2-), and exits 0" \
  "not-a-number:0 no-source:0 rc=0:1" \
  "not-a-number:$(count_re 'is not a number' "$_a") no-source:$(count_re 'has no source' "$_a") rc=0:$(count_re '^rc=0$' "$_a")"
assert_contains "AC-4 second level: a source after an empty second field is still a source" \
  "ci-factor: 2.5 |  | measured in actions run 413" "$_a"

describe "HARNESS-024 C-1: gates.sh's from_field, rest and field are cut's -fN-, trimmed -fN- and trimmed -fN"

# The helpers gates.sh ships, lifted out of it, against `cut -d'|'` itself as
# the oracle, for n = 1..5 over every data line of the manifest and a handful
# of shapes the manifest does not have: no pipe at all (cut returns the line
# whole), fewer fields than n (empty), empty fields, a leading and a trailing
# pipe. AC-6 then holds doctor.sh and task.sh to the same definitions.
{ awk '/\|/ && !/^[[:space:]]*#/' "$MANIFEST_FIXTURES/project.conf"
  printf '%s\n' 'no pipe here' 'a|b' 'a||c' ' x | | y |' '|lead' 'trail|' '  |  '
} > "$_h24/split.in"
: > "$_h24/split.from.oracle"; : > "$_h24/split.rest.oracle"; : > "$_h24/split.field.oracle"
for _n in 1 2 3 4 5; do
  cut -d'|' -f"$_n"- "$_h24/split.in" >> "$_h24/split.from.oracle"
  cut -d'|' -f"$_n"- "$_h24/split.in" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' >> "$_h24/split.rest.oracle"
  cut -d'|' -f"$_n"  "$_h24/split.in" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' >> "$_h24/split.field.oracle"
done
# The result variable is `_got`, not `_v`: bash scopes `local` dynamically, so a
# caller passing the name of one of the helpers' own locals (`_v`, `_t`, `_r`,
# `_i`) has its result assigned to the helper's local and lost. No call site in
# the three scripts uses those names; neither may this test.
_helpers="$(for _f in trim from_field rest field; do extract_fn "$REPO_ROOT/scripts/gates.sh" "$_f"; done)"
for _k in from rest field; do
  ( eval "$_helpers"
    for _n in 1 2 3 4 5; do
      while IFS= read -r _line || [ -n "$_line" ]; do
        _got="<unassigned>"
        case "$_k" in
          from)  from_field "$_n" "$_line" _got ;;
          rest)  rest "$_n" "$_line" _got ;;
          field) field "$_n" "$_line" _got ;;
        esac
        printf '%s\n' "$_got"
      done < "$_h24/split.in"
    done
  ) > "$_h24/split.$_k" 2>/dev/null
done
assert_eq "from_field <n> behaves as cut -d'|' -f<n>- on every input, n = 1..5" \
  "0" "$(disagreements "$_h24/split.from.oracle" "$_h24/split.from")"
assert_eq "rest <n> behaves as the trimmed cut -d'|' -f<n>- on every input, n = 1..5" \
  "0" "$(disagreements "$_h24/split.rest.oracle" "$_h24/split.rest")"
assert_eq "field <n> behaves as the trimmed cut -d'|' -f<n> on every input, n = 1..5" \
  "0" "$(disagreements "$_h24/split.field.oracle" "$_h24/split.field")"

describe "HARNESS-024 AC-5: gates.sh's trim() agrees with the shipped sed form"

trim_inputs "$_h24/trim.in"
trim_oracle "$_h24/trim.in" "$_h24/trim.oracle"
assert_eq "the input set is every manifest line and the six edge cases" \
  "$((TRIM_EDGE + 6))" "$(awk 'END { print NR }' "$_h24/trim.in")"
# Read with bash, not awk or sed: MSYS awk and sed read in text mode and drop
# a carriage return before any pattern sees it, so they cannot tell.
_cr=0; while IFS= read -r _line; do case "$_line" in *$'\r') _cr=$((_cr+1)) ;; esac; done < "$_h24/trim.in"
assert_eq "and exactly one input, the last edge case, ends in a carriage return" "1" "$_cr"
assert_contains "gates.sh defines trim()" "trim()" "$(extract_fn "$REPO_ROOT/scripts/gates.sh" trim)"
apply_trim "$REPO_ROOT/scripts/gates.sh" "$_h24/trim.in" "$_h24/trim.gates"
_d="$(disagreements "$_h24/trim.oracle" "$_h24/trim.gates")"
assert_eq "AC-5: gates.sh trim, printing form, agrees with the sed form on every input" "0" "$_d"
apply_trim "$REPO_ROOT/scripts/gates.sh" "$_h24/trim.in" "$_h24/trim.gates.assign" assign
_d="$(disagreements "$_h24/trim.oracle" "$_h24/trim.gates.assign")"
assert_eq "C-1: gates.sh trim, assigning form (trim \"\$x\" var), agrees with the sed form on every input" "0" "$_d"

# The control that makes the input set mean something: a space-only trim must
# DISAGREE with the oracle on the tab case and the multi-space case. If it did
# not, these inputs could not tell `[:space:]` from a literal space.
( naive() { local s="$1"; s="${s## }"; printf '%s' "${s%% }"; }
  while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "$(naive "$l")"; done < "$_h24/trim.in"
) > "$_h24/trim.naive"
_differs() { [ "$(line_of "$1" "$2")" != "$(line_of "$1" "$3")" ] && echo differs || echo agrees; }
assert_eq "control: the space-only trim disagrees on the tab-padded input" \
  "differs" "$(_differs "$((TRIM_EDGE + 4))" "$_h24/trim.oracle" "$_h24/trim.naive")"
assert_eq "control: the space-only trim disagrees on the multi-space input" \
  "differs" "$(_differs "$((TRIM_EDGE + 3))" "$_h24/trim.oracle" "$_h24/trim.naive")"

describe "HARNESS-024 AC-6: one parser, in three identical copies, and no sed trim or cut -d'|' left"

# Scoped to the three scripts AC-6 names: lib.sh's own copy of the sed trim is
# the next story's (MT-041), and selftest.sh's trim is already pure bash.
assert_eq "AC-6: no copy of the sed trim body in gates.sh, doctor.sh or task.sh" \
  "gates.sh:0 doctor.sh:0 task.sh:0" \
  "$(for _s in gates doctor task; do printf '%s.sh:%s ' "$_s" "$(grep -cF -- "$TRIM_SED_BODY" "$REPO_ROOT/scripts/$_s.sh")"; done | awk '{ sub(/ $/, ""); print }')"
assert_eq "AC-6: no cut -d'|' in gates.sh, doctor.sh or task.sh" \
  "gates.sh:0 doctor.sh:0 task.sh:0" \
  "$(for _s in gates doctor task; do printf '%s.sh:%s ' "$_s" "$(grep -cF -- "cut -d'|'" "$REPO_ROOT/scripts/$_s.sh")"; done | awk '{ sub(/ $/, ""); print }')"
for _f in trim from_field field rest; do
  _g="$(extract_fn "$REPO_ROOT/scripts/gates.sh" "$_f")"
  _verdict="$([ -n "$_g" ] && printf defined || printf missing)"
  for _s in doctor task; do
    if [ "$(extract_fn "$REPO_ROOT/scripts/$_s.sh" "$_f")" = "$_g" ]; then _verdict="$_verdict same"; else _verdict="$_verdict differs"; fi
  done
  assert_eq "AC-6: $_f() is defined in gates.sh, and doctor.sh and task.sh define it byte-identically" \
    "defined same same" "$_verdict"
done

# ============================================================================
# HARNESS-057: a gate's settings are looked up without forking
# ============================================================================
#
# HARNESS-024 made the per-LINE parse cost builtin. The per-GATE cost was left:
# every gate line ran `x=$(table_lookup ...)` eight times, and a `$(...)` forks
# whether or not its body execs anything. trace_externals counts exec'd
# programs only, so it cannot see those forks - HARNESS-024's assertions above
# hold over a manifest whose gate count drives eighty of them, and they stay as
# the guard on correctness (AC-3: a lookup that forks less by looking up less,
# or by returning the wrong value, changes the goldens).
#
# The oracle here is the one that sees a fork that execs nothing: bash -x with
# PS4='+ ' marks a command inside a command substitution or subshell with `++`,
# so `grep -c '^++'` counts commands run in a fork. Nine more gates must cost no
# more of them. The trace goes to fd 9 so stdout and stderr stay what a user
# sees. Each oracle covers the other's blind spot: this one is blind to a
# top-level pipeline, which trace_externals sees.

# nested_measure <fixture> <out-prefix> <mode>   gates.sh <mode> under bash -x
# with the trace on fd 9. Sets N_RC, N_NESTED (lines at depth >= 2), and
# leaves stdout in <out-prefix>.out, stderr in <out-prefix>.err.
nested_measure() {
  local fix="$1" pre="$2" mode="$3"
  (
    cd "$fix" || exit 99
    exec 9> "$pre.trace"
    BASH_XTRACEFD=9 PS4='+ ' bash -x scripts/gates.sh "$mode" > "$pre.out" 2> "$pre.err"
  )
  N_RC=$?
  N_NESTED=$(grep -c '^++' "$pre.trace")
}

# The one-gate manifest carries every table kind that can sit on one gate
# without failing the audit (no-count cannot share a gate with a floor). The
# ten-gate manifest is those six lines plus a gate and an evidence line for each
# of g02..g10 (story C-3).
_h57_one() {
  printf '%s\n' \
    "gate      | g01 | optional | . | printf 'Tests  47 passed (47)\\n'" \
    "evidence  | g01 | Tests +[1-9][0-9]* passed" \
    "floor     | g01 | 40" \
    "waiver    | g01 | flaky on the fixture runner, see MC-000" \
    "slow      | g01 | builds a release bundle" \
    "ci-factor | g01 | 3.4 | measured from CI run 12345"
}
_h57_ten() {
  local i id
  _h57_one
  for i in 2 3 4 5 6 7 8 9 10; do
    id="$(printf 'g%02d' "$i")"
    printf '%s\n' \
      "gate      | $id | required | . | printf 'Tests  47 passed (47)\\n'" \
      "evidence  | $id | Tests +[1-9][0-9]* passed"
  done
}
_h57="$(mktemp -d 2>/dev/null || mktemp -d -t h057.XXXXXX)"
_h57_f1="$(make_project_fixture)"
_h57_f10="$(make_project_fixture)"
_h57_one | write_conf "$_h57_f1"
_h57_ten | write_conf "$_h57_f10"

describe "HARNESS-057 fixtures: the ten-gate manifest declares ten gates, the one-gate manifest one"

assert_eq "the one-gate manifest declares exactly one gate line" \
  1 "$(count_re '^gate +\| g[0-9][0-9] +\| ' "$(cat "$_h57_f1/.claude/harness/project.conf")")"
assert_eq "the ten-gate manifest declares exactly ten gate lines" \
  10 "$(count_re '^gate +\| g[0-9][0-9] +\| ' "$(cat "$_h57_f10/.claude/harness/project.conf")")"
# Fixed-string, so no regex layer reinterprets the backslash: the needle is the
# command text with its literal \n, which a manifest whose escape was expanded
# into a real newline (the command split over two lines) does not contain.
assert_eq "and every gate command is one line with its \\n escape intact (none split over two lines)" \
  10 "$(grep -c -F "printf 'Tests  47 passed (47)\\n'" "$_h57_f10/.claude/harness/project.conf")"
assert_eq "and the ten-gate manifest is exactly BOOTSTRAPPED=yes plus 6 + 9 x 2 lines" \
  25 "$(awk 'END { print NR }' "$_h57_f10/.claude/harness/project.conf")"

# _h57_same <what> <one> <ten> <mode>   the equality, with a message naming both
# counts and the lookups that ran inside a fork, so a failure reads as the bug.
_h57_same() {
  if [ "$2" = "$3" ]; then _ok "$1"; else
    _bad "$1" "nested commands (trace lines at depth >= 2): one gate $2, ten gates $3
of which \$(table_lookup ...) substitutions: one gate $(grep -c '^++ table_lookup' "$_h57/one.$4.trace"), ten gates $(grep -c '^++ table_lookup' "$_h57/ten.$4.trace")"
  fi
}

for _m in list audit; do
  describe "HARNESS-057 AC-$([ "$_m" = list ] && printf 1 || printf 2): gates.sh --$_m runs no more nested commands for nine more gates"

  nested_measure "$_h57_f1" "$_h57/one.$_m" "--$_m"; _one_rc=$N_RC; _one_n=$N_NESTED
  nested_measure "$_h57_f10" "$_h57/ten.$_m" "--$_m"; _ten_rc=$N_RC; _ten_n=$N_NESTED
  assert_eq "the traced one-gate --$_m exits 0" 0 "$_one_rc"
  assert_eq "the traced ten-gate --$_m exits 0" 0 "$_ten_rc"
  # The control on the equality: a trace that was never written satisfies 0 = 0.
  if [ "${_one_n:-0}" -gt 0 ] 2>/dev/null; then
    _ok "control: the one-gate --$_m trace records nested commands at all ($_one_n)"
  else
    _bad "control: the one-gate --$_m trace records nested commands at all" \
      "counted '${_one_n}' lines beginning ++ in $_h57/one.$_m.trace; stderr: $(cat "$_h57/one.$_m.err")"
  fi
  _h57_same "AC-$([ "$_m" = list ] && printf 1 || printf 2): gates.sh --$_m runs as many nested commands over ten gates as over one" \
    "$_one_n" "$_ten_n" "$_m"
done

_out="$(cat "$_h57/ten.list.out")"
_named=""
for _i in 01 02 03 04 05 06 07 08 09 10; do
  [ "$(count_re "^g$_i +(optional|required) " "$_out")" = 1 ] && _named="$_named g$_i"
done
assert_eq "AC-1: the ten-gate --list names every one of the ten gates, once each" \
  " g01 g02 g03 g04 g05 g06 g07 g08 g09 g10" "$_named"

_out="$(cat "$_h57/ten.audit.out")"
assert_eq "AC-2: the ten-gate --audit prints an ok line for the tenth gate, g10" \
  1 "$(count_re '^ok +g10 +evidence: ' "$_out")"
assert_eq "AC-2: and the ten-gate --audit passes" 1 "$(count_re '^Manifest audit passed\.$' "$_out")"

describe "HARNESS-057 AC-4: gates.sh has no \$(table_lookup substitution, and still defines table_lookup"

# A fixed-string count over the shipped file. "$(table_lookup contains the
# needle, so the quoted form is caught too; a comment naming the function
# without `$(` is not. The predicate callers (`table_lookup ... >/dev/null`)
# fork nothing and do not match.
assert_eq "AC-4: no line of scripts/gates.sh contains \$(table_lookup" \
  0 "$(grep -c -F '$(table_lookup' "$REPO_ROOT/scripts/gates.sh")"
# So AC-4 cannot be satisfied by deleting the function and its predicate callers.
assert_eq "AC-4: and scripts/gates.sh still defines table_lookup()" \
  1 "$(grep -c -E '^table_lookup\(\) \{' "$REPO_ROOT/scripts/gates.sh")"

rm -rf "$_h57" "$_h57_f1" "$_h57_f10"


# ============================================================================
# HARNESS-026: the audit counts only required gates, and a run from another
# branch is not recorded (ports MT-043 and MT-032 F-2)
# ============================================================================
#
# FIX is on `main` here: the HARNESS-014/015 blocks above returned it there.
# Every needle is a whole line, or a prefix anchored at ^, through count_re /
# count_line; nothing here is awk-dialect-specific (HARNESS-025's lesson).

describe "HARNESS-026 AC-1..AC-3  --audit counts only required gates without evidence"

set_phase "$FIX" ""
git -C "$FIX" checkout -q -- . 2>/dev/null
NOEV_UNIT="$(printf 'WARN %-12s no evidence line; a vacuous pass would go unnoticed' unit)"
NOEV_MUT="$(printf 'WARN %-12s no evidence line; a vacuous pass would go unnoticed' mutation)"
NOEV_ONE='^1 required gate\(s\) have no evidence line\. Add one per gate:$'
NOEV_ANY='required gate\(s\) have no evidence line'

# AC-1: the audit's own reproduction. Required `unit` has evidence, optional
# `mutation` has none. Upstream printed `1 required gate(s) ...` for it.
# The `ondemand` line is HARNESS-039's: without it the audit FAILs this
# manifest for a reason unrelated to evidence, and the exit-0 assertion below
# is about evidence counting only. An on-request gate still gets its per-gate
# no-evidence WARN in the audit, so nothing else here changes.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
ondemand | mutation | per-story cost the user declined
EOF
out="$(gates --audit)"; rc=$?
assert_eq "AC-1: an optional gate without evidence produces no 'required gate(s) have no evidence line' summary" \
  0 "$(count_re "$NOEV_ANY" "$out")"
assert_eq "AC-1: the optional gate's own no-evidence WARN line is still printed, whole" \
  1 "$(count_line "$NOEV_MUT" "$out")"
assert_eq "AC-1: and the audit exits 0" 0 "$rc"

# AC-2: both gates lack evidence. Exactly one summary line, and it says 1.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
EOF
out="$(gates --audit)"
assert_eq "AC-2: one required and one optional gate without evidence: the summary says 1, not 2" \
  1 "$(count_re "$NOEV_ONE" "$out")"
assert_eq "AC-2: and there is exactly one summary line" 1 "$(count_re "^[0-9]+ $NOEV_ANY" "$out")"
assert_eq "AC-2: the required gate's WARN line is printed" 1 "$(count_line "$NOEV_UNIT" "$out")"
assert_eq "AC-2: and so is the optional gate's" 1 "$(count_line "$NOEV_MUT" "$out")"

# AC-2 control: the required gate is the ONLY one without evidence. The count is
# 1, not 0 - this is what stops "count nothing" from satisfying AC-1.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | mutation | Killed [0-9]+ of
EOF
out="$(gates --audit)"
assert_eq "AC-2 control: a required gate alone without evidence is still counted: 1, not 0" \
  1 "$(count_re "$NOEV_ONE" "$out")"
assert_eq "AC-2 control: with its WARN line" 1 "$(count_line "$NOEV_UNIT" "$out")"
# ... and with BOOTSTRAPPED=no, which the run path's counter conditions on and
# the audit's must not.
printf '%s\n' 'BOOTSTRAPPED=no' \
  "gate     | unit     | required | . | printf 'Tests  47 passed (47)\\n'" \
  "gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\\n'" \
  'evidence | mutation | Killed [0-9]+ of' > "$FIX/.claude/harness/project.conf"
out="$(gates --audit)"
assert_eq "AC-2 control: with BOOTSTRAPPED=no the required gate without evidence is still counted: 1" \
  1 "$(count_re "$NOEV_ONE" "$out")"

# AC-3: the count follows the gate's requirement AFTER story escalation. The
# pair is the discriminator: the same manifest counts 0 while the story leaves
# `mutation` optional, and 1 once the story's required_gates names it.
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
EOF
story "$FIX" T-1 GATES </dev/null
set_phase "$FIX" GATES
out="$(gates --audit)"
assert_eq "AC-3: an active story that does not escalate the optional gate: no summary" \
  0 "$(count_re "$NOEV_ANY" "$out")"
story "$FIX" T-1 GATES <<'EOF'
required_gates: [mutation]
EOF
out="$(gates --audit)"
assert_eq "AC-3: an optional gate the story's required_gates escalates, without evidence, is counted: 1" \
  1 "$(count_re "$NOEV_ONE" "$out")"
assert_eq "AC-3: and its WARN line is printed" 1 "$(count_line "$NOEV_MUT" "$out")"
set_phase "$FIX" ""
git -C "$FIX" checkout -q -- . 2>/dev/null

describe "HARNESS-026 AC-4..AC-6  a run from another branch is not recorded"

# The audit's reproduction: an active story whose frontmatter says
# `branch: story/T-1-fixture`, a passing full run, the checkout on `main`.
# Upstream recorded and exited 0.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
story "$FIX" T-1 GATES </dev/null
fix_commit "HARNESS-026 fixture: T-1 committed on main"
set_phase "$FIX" GATES
T1="$FIX/docs/backlog/stories/T-1.md"
BRANCH_REFUSAL="^\\(not recorded: the checkout is on 'main' but story T-1 belongs on 'story/T-1-fixture'"
stamp_val()   { sed -n "s/^$1=//p" "$FIX/.claude/state/last-gate-run" | tr -d '\r'; }
same_record() { cmp -s "$FIX/.claude/state/T-1.before" "$T1" && printf yes || printf no; }

assert_eq "fixture precondition: the checkout is on main" main "$(git -C "$FIX" branch --show-current)"
assert_eq "fixture precondition: the story belongs on story/T-1-fixture" 1 \
  "$(count_line 'branch: story/T-1-fixture' "$(tr -d '\r' < "$T1")")"

# AC-4, twice: with T-1 the active story, and with no active story and
# `--story T-1` naming it explicitly.
for _mode in active explicit; do
  if [ "$_mode" = active ]; then
    set_phase "$FIX" GATES; _label="AC-4"
    cp "$T1" "$FIX/.claude/state/T-1.before"
    out="$(gates)"; rc=$?
  else
    set_phase "$FIX" ""; _label="AC-4 (--story T-1)"
    cp "$T1" "$FIX/.claude/state/T-1.before"
    out="$(gates --story T-1)"; rc=$?
  fi
  assert_eq "$_label: a passing full run on main prints the branch refusal, naming both branches, once" \
    1 "$(count_re "$BRANCH_REFUSAL" "$out")"
  assert_eq "$_label: and it is the only line beginning '(not recorded:'" 1 "$(count_re '^\(not recorded:' "$out")"
  assert_eq "$_label: ## Gate results is byte-for-byte unchanged" yes "$(same_record)"
  assert_eq "$_label: no line claims to have recorded" 0 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
  assert_eq "$_label: the run exits 1 although every gate passed" 1 "$rc"
  assert_eq "$_label: the stamp says FULL=no" no "$(stamp_val FULL)"
  assert_eq "$_label: while RESULT= is still the verdict on the code" pass "$(stamp_val RESULT)"
  git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null
done
set_phase "$FIX" GATES

# AC-5: the controls. The refusal fires only where it can tell; these keep it
# from being satisfied by "never record".
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
out="$(gates)"; rc=$?
assert_eq "AC-5 control: on story/T-1-fixture the run records" 1 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "AC-5 control: on story/T-1-fixture it is not refused" 0 "$(count_re '^\(not recorded:' "$out")"
assert_eq "AC-5 control: on story/T-1-fixture it exits 0" 0 "$rc"
assert_eq "AC-5 control: on story/T-1-fixture the stamp says FULL=yes" yes "$(stamp_val FULL)"
git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null
git -C "$FIX" checkout -q main 2>/dev/null

git -C "$FIX" checkout -q --detach 2>/dev/null
assert_eq "fixture precondition: HEAD is detached" "" "$(git -C "$FIX" branch --show-current)"
out="$(gates)"; rc=$?
assert_eq "AC-5 control: with HEAD detached the run records" 1 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "AC-5 control: with HEAD detached it is not refused" 0 "$(count_re '^\(not recorded:' "$out")"
assert_eq "AC-5 control: with HEAD detached it exits 0" 0 "$rc"
git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null
git -C "$FIX" checkout -q main 2>/dev/null

# A story with no `branch:` line, written directly (story() always writes one).
printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: GATES\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Gate results\n\n## Notes\n' > "$T1"
out="$(gates)"; rc=$?
assert_eq "AC-5 control: a story with no branch: line records from main" 1 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "AC-5 control: a story with no branch: line is not refused" 0 "$(count_re '^\(not recorded:' "$out")"
assert_eq "AC-5 control: a story with no branch: line exits 0" 0 "$rc"
git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null

set_phase "$FIX" ""
out="$(gates)"; rc=$?
assert_eq "AC-5 control: no active story prints the no-story line, as before" 1 \
  "$(count_re '^\(not recorded: no active story' "$out")"
assert_eq "AC-5 control: no active story: no branch refusal" 0 "$(count_re '^\(not recorded: the checkout is on ' "$out")"
assert_eq "AC-5 control: no active story: exit is the gates' own, 0" 0 "$rc"
set_phase "$FIX" GATES

# AC-6: the branch refusal and HARNESS-014's untracked refusal both apply. One
# '(not recorded:' line, and it is the branch one (PO decision 2).
mkdir -p "$FIX/handoff"
printf 'diff --git a/x b/x\n' > "$FIX/handoff/x.patch"          # an untracked gated file
cp "$T1" "$FIX/.claude/state/T-1.before"
out="$(gates)"; rc=$?
assert_eq "AC-6: both refusals apply: exactly one line begins '(not recorded:'" 1 "$(count_re '^\(not recorded:' "$out")"
assert_eq "AC-6: and it is the branch refusal" 1 "$(count_re "$BRANCH_REFUSAL" "$out")"
assert_eq "AC-6: not the untracked-file one" 0 "$(count_re '^\(not recorded: .*untracked gated file' "$out")"
assert_eq "AC-6: both refusals: exit 1" 1 "$rc"
assert_eq "AC-6: both refusals: ## Gate results unchanged" yes "$(same_record)"

# A BLOCKED run refused by both exits 1, not 3.
write_conf "$FIX" <<'EOF'
gate     | unit  | required | . | printf 'Tests  47 passed (47)\n'
gate     | types | required | . | printf 'error: could not execute process (never executed)\n'; exit 101
evidence | unit  | Tests +[1-9][0-9]* passed
evidence | types | Tests +[1-9][0-9]* passed
EOF
out="$(gates)"; rc=$?
assert_eq "AC-6: a BLOCKED run under both refusals is still reported BLOCKED" 1 "$(count_re '^BLOCKED +types' "$out")"
assert_eq "AC-6: a BLOCKED run under both refusals exits 1, not 3" 1 "$rc"
rm -rf "$FIX/handoff"

# The branch refusal alone, on a BLOCKED run: exits 1, not 3, and records nothing.
out="$(gates)"; rc=$?
assert_eq "AC-6: a BLOCKED run refused for its branch alone prints the branch refusal" 1 "$(count_re "$BRANCH_REFUSAL" "$out")"
assert_eq "AC-6: a BLOCKED run refused for its branch alone exits 1, not 3" 1 "$rc"
assert_eq "AC-6: and leaves ## Gate results unchanged" yes "$(same_record)"
git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null   # so the next comparison is its own

# The branch refusal alone, on a FAILING run: still exits 1, and records nothing.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'boom\n'; exit 1
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(gates)"; rc=$?
assert_eq "AC-6: a failing run refused for its branch prints the branch refusal" 1 "$(count_re "$BRANCH_REFUSAL" "$out")"
assert_eq "AC-6: a failing run refused for its branch exits 1" 1 "$rc"
assert_eq "AC-6: and records nothing" 0 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "AC-6: ## Gate results unchanged after a refused failing run" yes "$(same_record)"

rm -f "$FIX/.claude/state/T-1.before"
git -C "$FIX" checkout -q -- . 2>/dev/null
set_phase "$FIX" ""

describe "HARNESS-056 AC-1..AC-5  a gate run that started earlier never overwrites a newer gate record"

# A run that started earlier and finished later used to win: record_in_story
# stamped run: at WRITE time and replaced ## Gate results unconditionally. The
# "newer" record is PLANTED, in the tool's own shape, with run: 2099 - no
# sleep, no background run, no race. The fixture is HARNESS-026's: T-1 at
# GATES, on its own branch story/T-1-fixture, the story file committed (026
# refuses a record from another branch, 014 one with untracked gated files).
#
# Needles: whole lines (count_line) or anchored count_re with no intervals.
# The decline line is pinned whole, as the Contract writes it; the start time
# it names is extracted and checked to lie between a clock read just before
# the run and one just after, so the planted 2099 cannot stand in for it.
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
story "$FIX" T-1 GATES </dev/null
fix_commit "HARNESS-056 fixture: T-1 on its own branch"
set_phase "$FIX" GATES
T1="$FIX/docs/backlog/stories/T-1.md"
H56_STAMP="$FIX/.claude/state/last-gate-run"
H56_MARKER="$(sed -n "s/^GATE_MARKER='\(.*\)'$/\1/p" "$FIX/.claude/hooks/lib.sh")"
H56_RECORDED='^recorded in docs/backlog/stories/T-1\.md \(## Gate results\)$'
H56_TS='[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
H56_DECLINE="^\\(not recorded: docs/backlog/stories/T-1\\.md already holds a record from a gate run that started at 2099-01-01T00:00:00Z; this one started at $H56_TS, so the newer record stands\\)\$"
H56_RUN_NOW='^    run:    20[2-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z$'

# h56_plant <run-value>   Rewrite T-1's ## Gate results as a record in the
# tool's own shape whose run: is <run-value>, and commit it on the story branch.
h56_plant() {
  story "$FIX" T-1 GATES </dev/null
  {
    sed -e '/^## Gate results/q' "$T1"
    printf '\n%s\n\n' "$H56_MARKER"
    printf '    run:    %s\n    commit: deadbee\n    tree:   abc123\n' "$1"
    printf '    result: pass (1 ran, 0 unconfigured, 0 known)\n    PASS         unit (0s)\n\n'
    printf '## Notes\n'
  } > "$FIX/t1.new" && mv "$FIX/t1.new" "$T1"
  fix_commit "HARNESS-056 fixture: a record whose run: is $1"
}
h56_now()     { date -u +%Y-%m-%dT%H:%M:%SZ; }
h56_section() { sed -n '/^## Gate results/,/^## Notes/p' "$T1"; }
h56_runs()    { grep -c '^ *run: ' "$T1"; }
# h56_run_lines   Every run: line of the story, verbatim, so a clobbered record
# shows the value that replaced it.
h56_run_lines() { awk '/^ *run: / { sub(/\r$/, ""); print }' "$T1"; }
h56_stamp()   { tr -d '\r' < "$H56_STAMP"; }
# h56_started <output>   The start time the decline line names, or empty.
h56_started() { sed -n 's/^(not recorded: .* this one started at \([^,]*\), so the newer record stands)$/\1/p' <<< "$1"; }
# h56_within <ts> <lo> <hi>   "yes" when lo <= ts <= hi as timestamps (digits
# compared as integers, all three the same width), else what was wrong.
h56_within() {
  local t="${1//[!0-9]/}" l="${2//[!0-9]/}" h="${3//[!0-9]/}"
  if [ -z "$t" ]; then printf 'no start time in the output'; return; fi
  if [ "${#t}" != "${#l}" ]; then printf 'malformed start time %s' "$1"; return; fi
  if [ "$t" -ge "$l" ] && [ "$t" -le "$h" ]; then printf yes; else printf '%s is not within [%s, %s]' "$1" "$2" "$3"; fi
}

h56_plant 2099-01-01T00:00:00Z
assert_eq "fixture precondition: the checkout is on story/T-1-fixture" story/T-1-fixture "$(git -C "$FIX" branch --show-current)"
assert_eq "fixture precondition: the planted record's run: is 2099" 1 \
  "$(count_line '    run:    2099-01-01T00:00:00Z' "$(tr -d '\r' < "$T1")")"
assert_eq "fixture precondition: the planted record carries the tool's marker" 1 \
  "$(count_line "$H56_MARKER" "$(tr -d '\r' < "$T1")")"
assert_eq "fixture precondition: nothing gated is dirty or untracked" "" \
  "$(git -C "$FIX" status --porcelain -- . ':!.claude/state')"
h56_section > "$FIX/.claude/state/h56.before"

# --- AC-1..AC-3: a passing run that started before the newer record ----------
H56_LO="$(h56_now)"
out="$(gates)"; rc=$?
H56_HI="$(h56_now)"
h56_section > "$FIX/.claude/state/h56.after"
assert_eq "AC-1: a run that started before a newer record does not say it recorded" 0 "$(count_re "$H56_RECORDED" "$out")"
assert_eq "AC-1: exactly one line begins '(not recorded: '" 1 "$(count_re '^\(not recorded: ' "$out")"
assert_eq "AC-1: and it is the decline naming the story file, the standing 2099 record and this run's start" 1 \
  "$(count_re "$H56_DECLINE" "$out")"
assert_eq "AC-1: the start time the decline names is this run's own (between the clock before and after it)" yes \
  "$(h56_within "$(h56_started "$out")" "$H56_LO" "$H56_HI")"
if cmp -s "$FIX/.claude/state/h56.before" "$FIX/.claude/state/h56.after"; then h56_same=yes; else h56_same=no; fi
assert_eq "AC-2: ## Gate results is byte-for-byte what it was before the run" yes "$h56_same"
assert_eq "AC-2: the newer record's run: still reads 2099-01-01T00:00:00Z (the run: lines of the story, as written)" "    run:    2099-01-01T00:00:00Z" \
  "$(h56_run_lines)"
assert_eq "AC-2: the story holds exactly one run: line (nothing appended)" 1 "$(h56_runs)"
assert_eq "AC-3: declining to record leaves the exit status the gates' verdict, 0" 0 "$rc"
assert_eq "AC-3: last-gate-run says RESULT=pass" 1 "$(count_line 'RESULT=pass' "$(h56_stamp)")"
assert_eq "AC-3: last-gate-run says FULL=yes" 1 "$(count_line 'FULL=yes' "$(h56_stamp)")"

# --- AC-4: a failing run may not overwrite what a passing one may not ---------
git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  0 passed\n'; exit 1
evidence | unit | Tests +[1-9][0-9]* passed
EOF
h56_section > "$FIX/.claude/state/h56.before"
H56_LO="$(h56_now)"
out="$(gates)"; rc=$?
H56_HI="$(h56_now)"
h56_section > "$FIX/.claude/state/h56.after"
assert_eq "AC-4: a failing run that started before the newer record does not say it recorded" 0 "$(count_re "$H56_RECORDED" "$out")"
assert_eq "AC-4: it prints the same decline, once" 1 "$(count_re "$H56_DECLINE" "$out")"
assert_eq "AC-4: and no other '(not recorded: ' line" 1 "$(count_re '^\(not recorded: ' "$out")"
assert_eq "AC-4: naming this run's own start time" yes \
  "$(h56_within "$(h56_started "$out")" "$H56_LO" "$H56_HI")"
assert_eq "AC-4: the 2099 record still stands (the run: lines of the story, as written)" "    run:    2099-01-01T00:00:00Z" \
  "$(h56_run_lines)"
if cmp -s "$FIX/.claude/state/h56.before" "$FIX/.claude/state/h56.after"; then h56_same=yes; else h56_same=no; fi
assert_eq "AC-4: ## Gate results is byte-for-byte unchanged by the failing run" yes "$h56_same"
if [ "$rc" != 0 ]; then h56_rc=non-zero; else h56_rc=zero; fi
assert_eq "AC-4: the exit status is the failing verdict" non-zero "$h56_rc"

# --- AC-5: the controls - an older record, and an empty section, are replaced -
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
h56_plant 2000-01-01T00:00:00Z
assert_eq "fixture precondition: the planted record's run: is 2000" 1 \
  "$(count_line '    run:    2000-01-01T00:00:00Z' "$(tr -d '\r' < "$T1")")"
H56_LO="$(h56_now)"
out="$(gates)"; rc=$?
H56_HI="$(h56_now)"
assert_eq "AC-5 control: an older (2000) record is replaced: one 'recorded in' line" 1 "$(count_re "$H56_RECORDED" "$out")"
assert_eq "AC-5 control: an older record: no '(not recorded:' line" 0 "$(count_re '^\(not recorded:' "$out")"
assert_eq "AC-5 control: an older record: run: now holds a current-century time" 1 "$(count_re "$H56_RUN_NOW" "$(tr -d '\r' < "$T1")")"
assert_eq "AC-5 control: an older record: and it is this run's (between the clock before and after it)" yes \
  "$(h56_within "$(sed -n 's/^    run:    //p' "$T1" | tr -d '\r')" "$H56_LO" "$H56_HI")"
assert_eq "AC-5 control: an older record: the 2000 run: is gone" 0 \
  "$(count_line '    run:    2000-01-01T00:00:00Z' "$(tr -d '\r' < "$T1")")"
assert_eq "AC-5 control: an older record: exactly one run: line" 1 "$(h56_runs)"
assert_eq "AC-5 control: an older record: exit 0" 0 "$rc"

story "$FIX" T-1 GATES </dev/null
fix_commit "HARNESS-056 fixture: an empty ## Gate results (the template)"
assert_eq "fixture precondition: the template story holds no run: line" 0 "$(h56_runs)"
out="$(gates)"; rc=$?
assert_eq "AC-5 control: an empty section is written: one 'recorded in' line" 1 "$(count_re "$H56_RECORDED" "$out")"
assert_eq "AC-5 control: an empty section: no '(not recorded:' line" 0 "$(count_re '^\(not recorded:' "$out")"
assert_eq "AC-5 control: an empty section: run: holds a current-century time" 1 "$(count_re "$H56_RUN_NOW" "$(tr -d '\r' < "$T1")")"
assert_eq "AC-5 control: an empty section: exactly one run: line" 1 "$(h56_runs)"
assert_eq "AC-5 control: an empty section: exit 0" 0 "$rc"
# AC-6 is HARNESS-024 AC-1's existing --list process budget, unchanged.

rm -f "$FIX/.claude/state/h56.before" "$FIX/.claude/state/h56.after"
git -C "$FIX" checkout -q -- . 2>/dev/null
git -C "$FIX" checkout -q main 2>/dev/null
set_phase "$FIX" ""

describe "HARNESS-046 AC-3  gates.sh --story refuses an id that is not one path component, before any gate runs"

# A fixture of its own, so nothing here depends on the state $FIX was left in.
# EXIST.md sits one directory ABOVE the stories directory, inside the fixture:
# from docs/backlog/stories, ../EXIST is docs/backlog/EXIST.md (C-6). It and
# project.conf are committed, so a run that is NOT refused records into it -
# measured on today's gates.sh, 2026-10-09: the gate runs, its output line
# `ran` is printed, and `## Gate results` is appended to EXIST.md.
G46="$(make_project_fixture)"
trap 'rm -rf "$FIX" "$MFX" "$_h24" "$G46"' EXIT
g46() { ( cd "$G46" && bash scripts/gates.sh "$@" 2>&1 ); }
G46_MSG="error: story id '../EXIST' is not one path component: an id is letters, digits, '.', '_' or '-', and starts with a letter or digit"
write_conf "$G46" <<'EOF2'
gate     | probe | required | . | printf 'ran\n'
evidence | probe | ran
EOF2
printf -- '---\nid: EXIST\ntitle: Exists outside the stories directory\nslug: exist\ntype: feature\nstatus: todo\nphase: GATES\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Gate results\n\n## Notes\n' \
  > "$G46/docs/backlog/EXIST.md"
git -C "$G46" add -A >/dev/null 2>&1
git -C "$G46" -c user.email=t@t -c user.name=t commit -qm "HARNESS-046 fixture" >/dev/null 2>&1
cp "$G46/docs/backlog/EXIST.md" "$G46/.claude/state/EXIST.before"
g46_same() { cmp -s "$G46/.claude/state/EXIST.before" "$G46/docs/backlog/EXIST.md" && printf unchanged || printf changed; }
rm -f "$G46/.claude/state/current-story.env"

out="$(g46 --story ../EXIST)"; rc=$?
assert_eq "HARNESS-046 AC-3: gates.sh --story ../EXIST exits 2" 2 "$rc"
assert_eq "HARNESS-046 AC-3: and prints the grammar message naming ../EXIST, once" 1 "$(count_line "$G46_MSG" "$out")"
# Two needles for "the gate did not run": its own output line, whole, and the
# header gates.sh prints before every gate it runs.
assert_eq "HARNESS-046 AC-3: no line is the gate's output 'ran' (the gate did not run)" 0 "$(count_line ran "$out")"
assert_eq "HARNESS-046 AC-3: and no gate header was printed" 0 "$(count_re '^=== gate: ' "$out")"
assert_eq "HARNESS-046 AC-3: docs/backlog/EXIST.md is byte-for-byte unchanged" unchanged "$(g46_same)"
git -C "$G46" checkout -q -- . 2>/dev/null

# Contract C-4's second site: an id arriving from current-story.env rather than
# --story. phase.sh will refuse to write one, but the state file is evidence and
# is checked where it is read (gates.sh:331), so a hand-edited STORY_ID is
# refused the same way.
printf 'STORY_ID=../EXIST\nSTORY_SLUG=exist\nSTORY_TYPE=feature\nPHASE=GATES\nBRANCH=main\n' \
  > "$G46/.claude/state/current-story.env"
out="$(g46)"; rc=$?
assert_eq "HARNESS-046 C-4: with STORY_ID=../EXIST in current-story.env, gates.sh exits 2" 2 "$rc"
assert_eq "HARNESS-046 C-4: and prints the grammar message naming ../EXIST, once" 1 "$(count_line "$G46_MSG" "$out")"
assert_eq "HARNESS-046 C-4: and runs no gate" 0 "$(count_re '^=== gate: ' "$out")"
assert_eq "HARNESS-046 C-4: and docs/backlog/EXIST.md is byte-for-byte unchanged" unchanged "$(g46_same)"
rm -rf "$G46"

# ============================================================================
# HARNESS-027: a failing gate's log survives the passing re-run
# ============================================================================
#
# gates.sh tees each gate into gate-logs/<id>.log and every run truncates it, so
# the re-run that checks whether a failure was a flake destroys the only copy of
# the failure (issue #97, ported from manga-translator MT-046). A gate that ran
# and did not pass - outcome fail, noevidence or blocked, whatever word is
# printed - now leaves <id>.failed.log: six header lines, then that run's log
# byte for byte. A pass never writes it, a later pass never touches it, a later
# non-pass replaces it whole, a gate that did not run leaves it alone.
#
# One manifest throughout. `flaky` reads a marker file, so the same manifest
# fails, passes and fails differently; `steady` always passes, with NO evidence
# line, so it is the "PASS annotated for a missing evidence line" of AC-4;
# `broke` always fails, optional, so it is WARNed rather than FAILed - a non-pass
# whose printed word is not FAIL. The markers live under .claude/state/h27/, not
# at the fixture root: an untracked file there would classify as source and make
# a full run refuse to record (HARNESS-014), and AC-1 compares against the
# record. Never inside gate-logs/, which is the directory under test.
#
# Byte comparisons are `tail -n +7 | cmp` and `cmp`; text needles are whole
# lines through count_line or anchored count_re. No awk of our own (HARNESS-025).

describe "HARNESS-027 AC-1..AC-6  a failing gate's log survives the passing re-run"

set_phase "$FIX" ""
git -C "$FIX" checkout -q -- . 2>/dev/null
# T-1 records only from its own branch (HARNESS-026); AC-1 compares with the record.
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
set_phase "$FIX" GATES
KLOG="$FIX/.claude/state/gate-logs"
KM="$FIX/.claude/state/h27"
rm -rf "$KLOG" "$KM"; mkdir -p "$KM"
write_conf "$FIX" <<'EOF'
gate     | flaky  | required | . | if [ -f .claude/state/h27/fail-a ]; then printf 'boom A\n'; exit 1; elif [ -f .claude/state/h27/fail-b ]; then printf 'boom B\n'; exit 1; else printf 'Tests  3 passed (3)\n'; fi
evidence | flaky  | Tests +[1-9][0-9]* passed
gate     | steady | required | . | printf 'all good\n'
gate     | broke  | optional | . | printf 'nope\n'; exit 1
EOF

# stdout only: AC-6 is a statement about stdout.
kgates() { ( cd "$FIX" && bash scripts/gates.sh "$@" 2>/dev/null ); }
kept_line() { printf 'failing log kept: .claude/state/gate-logs/%s.failed.log' "$1"; }
kexists()   { [ -f "$KLOG/$1.failed.log" ] && printf yes || printf no; }
hdr()       { sed -n "$2p" "$KLOG/$1.failed.log" 2>/dev/null | tr -d '\r'; }
# body_vs_log <id>   AC-1's "byte-identical": everything after the six header lines.
body_vs_log() {
  [ -f "$KLOG/$1.failed.log" ] || { printf 'no %s.failed.log was written' "$1"; return; }
  if tail -n +7 "$KLOG/$1.failed.log" | cmp -s - "$KLOG/$1.log"; then printf identical; else printf differs; fi
}
# same <before> <after>   Byte-identity of two files, naming which is missing.
same() {
  [ -f "$1" ] || { printf 'missing: %s' "$1"; return; }
  [ -f "$2" ] || { printf 'missing: %s' "$2"; return; }
  cmp -s "$1" "$2" && printf identical || printf differs
}
# in_kept <id> <exact line>   How many whole lines of <id>.failed.log equal it.
# An absent file is reported as such, not as 0: a missing file is not evidence
# that the old run is gone.
in_kept() {
  [ -f "$KLOG/$1.failed.log" ] || { printf 'no %s.failed.log' "$1"; return; }
  count_line "$2" "$(tr -d '\r' < "$KLOG/$1.failed.log")"
}
# entries <prefix>   gate-logs/ entries starting with <prefix>, sorted, space-separated.
entries() { ( cd "$KLOG" 2>/dev/null && ls -1 | grep -F -- "$1" | LC_ALL=C sort | tr '\n' ' ' | sed 's/ $//' ); }
# lineno <exact line> <text>   1-based line of the first whole-line match, or empty.
lineno() { grep -m1 -nxF -- "$1" <<<"$2" | cut -d: -f1; }
k_tree()   { ( cd "$FIX" && CLAUDE_PROJECT_DIR="$FIX" bash -c '. .claude/hooks/lib.sh; gate_tree_hash' 2>/dev/null ); }
# k_commit   The commit line the contract specifies, computed here independently.
k_commit() {
  local c; c="$(git -C "$FIX" rev-parse --short HEAD)"
  [ -z "$(git -C "$FIX" status --porcelain -- . ':!docs' 2>/dev/null)" ] \
    || c="$c (working tree had uncommitted changes)"
  printf '%s' "$c"
}
T1="$FIX/docs/backlog/stories/T-1.md"
# grep -E, not count_re: awk interval expressions ({4}) are not in every mawk.
RUN_RE='^# run:     [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'

# --- AC-4: a pass never creates the file, the annotated pass included --------
out="$(kgates)"
assert_eq "AC-4 control: flaky passes plainly" 1 "$(count_re '^PASS +flaky \(' "$out")"
assert_eq "AC-4 control: steady is a PASS annotated for its missing evidence line" 1 \
  "$(count_re '^PASS +steady \(.*-- no evidence line: a vacuous pass would go unnoticed$' "$out")"
assert_eq "AC-4: a plain pass leaves no flaky.failed.log" no "$(kexists flaky)"
assert_eq "AC-4: a pass annotated for no evidence line leaves no steady.failed.log" no "$(kexists steady)"
assert_eq "AC-6: no kept line for the gate that passed plainly" 0 "$(count_line "$(kept_line flaky)" "$out")"
assert_eq "AC-6: no kept line for the annotated pass" 0 "$(count_line "$(kept_line steady)" "$out")"
# The same run's control that the keep fires at all: an optional gate, printed
# WARN, outcome fail, did not pass.
assert_eq "control: the optional gate that fails is printed WARN, not FAIL" 1 "$(count_re '^WARN +broke \(' "$out")"
assert_eq "AC-1: an optional gate printed WARN still did not pass, and keeps broke.failed.log" yes "$(kexists broke)"
assert_eq "AC-6: and the kept line is printed for it, once" 1 "$(count_line "$(kept_line broke)" "$out")"

# --- AC-1 / AC-6: a required gate fails; the full run records into T-1 -------
: > "$KM/fail-a"
before="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
out="$(kgates)"
assert_eq "AC-1 control: flaky failed" 1 "$(count_re '^FAIL +flaky \(' "$out")"
assert_eq "AC-1 control: the failing full run recorded into T-1" 1 \
  "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
rec_commit="$(tr -d '\r' < "$T1" | sed -n '/^    commit: /{s///p;q;}')"
rec_tree="$(tr -d '\r' < "$T1" | sed -n '/^    tree:   /{s///p;q;}')"
assert_eq "AC-1: a failing gate leaves flaky.failed.log" yes "$(kexists flaky)"
assert_eq "AC-1 header 1 names the gate" "# gates.sh: last failing run of gate 'flaky'" "$(hdr flaky 1)"
assert_eq "AC-1 header 2 is the outcome" "# outcome: fail" "$(hdr flaky 2)"
assert_eq "AC-1 header 3 is a UTC time, YYYY-MM-DDTHH:MM:SSZ" 1 "$(hdr flaky 3 | grep -cE -- "$RUN_RE")"
_run="$(hdr flaky 3)"; _run="${_run#'# run:     '}"
assert_eq "AC-1 header 3 is no earlier than the run was started" yes \
  "$([[ -n "$_run" && ! "$_run" < "$before" ]] && printf yes || printf "no ([$_run] before [$before])")"
assert_eq "control: the record has a commit line to compare against" 1 "$([ -n "$rec_commit" ] && printf 1 || printf 0)"
assert_eq "AC-1 header 4 is the commit line the same run recorded in ## Gate results" \
  "# commit:  $rec_commit" "$(hdr flaky 4)"
assert_eq "AC-1 header 4 is the short HEAD with the uncommitted-changes note" \
  "# commit:  $(k_commit)" "$(hdr flaky 4)"
assert_eq "AC-1 header 5 is gate_tree_hash, computed independently" "# tree:    $(k_tree)" "$(hdr flaky 5)"
assert_eq "AC-1 header 5 is the tree the same run recorded" "# tree:    $rec_tree" "$(hdr flaky 5)"
assert_eq "AC-1 header 6 closes the header" "# ----" "$(hdr flaky 6)"
assert_eq "AC-1: after six header lines, the run's log byte for byte" identical "$(body_vs_log flaky)"
assert_eq "AC-1: and it is this run's log" 1 "$(in_kept flaky 'boom A')"
assert_eq "AC-6: the kept line is printed once" 1 "$(count_line "$(kept_line flaky)" "$out")"
_out_l="$(lineno 'boom A' "$out")"; _kept_l="$(lineno "$(kept_line flaky)" "$out")"
_next_l="$(printf '%s\n' "$out" | grep -m1 -n '^=== gate: steady ' | cut -d: -f1)"
assert_eq "AC-6: the kept line comes right after flaky's output" yes \
  "$([ -n "$_out_l" ] && [ -n "$_kept_l" ] && [ "$_kept_l" -eq $((_out_l + 1)) ] && printf yes || printf "no (output at ${_out_l:-?}, kept line at ${_kept_l:-absent})")"
assert_eq "AC-6: and before the next gate's header" yes \
  "$([ -n "$_kept_l" ] && [ -n "$_next_l" ] && [ "$_kept_l" -lt "$_next_l" ] && printf yes || printf "no (kept line at ${_kept_l:-absent}, next header at ${_next_l:-?})")"
assert_eq "AC-6: ## Gate results does not carry the kept line" 0 "$(count_re '^ *failing log kept:' "$(tr -d '\r' < "$T1")")"
cp "$KLOG/flaky.failed.log" "$KM/flaky.first" 2>/dev/null

# --- AC-2: a later pass leaves it byte-identical -----------------------------
rm -f "$KM/fail-a"
out="$(kgates)"
assert_eq "AC-2 control: the re-run passed" 1 "$(count_re '^PASS +flaky \(' "$out")"
assert_eq "AC-2: after the pass, flaky.failed.log is byte-identical" identical \
  "$(same "$KM/flaky.first" "$KLOG/flaky.failed.log")"
assert_eq "AC-2: while flaky.log holds the passing run" 1 "$(count_line 'Tests  3 passed (3)' "$(tr -d '\r' < "$KLOG/flaky.log")")"
assert_eq "AC-2: and not the failure" 0 "$(count_line 'boom A' "$(tr -d '\r' < "$KLOG/flaky.log")")"
assert_eq "AC-6: the pass printed no kept line for flaky" 0 "$(count_line "$(kept_line flaky)" "$out")"

# --- AC-3: a different failure replaces it whole -----------------------------
: > "$KM/fail-b"
out="$(kgates)"
assert_eq "AC-3: the newer failure is kept" 1 "$(in_kept flaky 'boom B')"
assert_eq "AC-3: none of the older output remains" 0 "$(in_kept flaky 'boom A')"
assert_eq "AC-3: one header, replaced rather than appended" 1 \
  "$(in_kept flaky "# gates.sh: last failing run of gate 'flaky'")"
assert_eq "AC-3: header then the newer log, byte for byte" identical "$(body_vs_log flaky)"
assert_eq "AC-3: gate-logs/ holds flaky.failed.log and flaky.log, nothing else for flaky" \
  "flaky.failed.log flaky.log" "$(entries flaky.)"

# --- AC-5: --fast and --gate <id> -------------------------------------------
rm -f "$KM/fail-b" "$KLOG/flaky.failed.log"; : > "$KM/fail-a"
out="$(kgates --fast)"
assert_eq "AC-5 --fast: a failing gate leaves flaky.failed.log" yes "$(kexists flaky)"
assert_eq "AC-5 --fast: header 1"  "# gates.sh: last failing run of gate 'flaky'" "$(hdr flaky 1)"
assert_eq "AC-5 --fast: header 2"  "# outcome: fail" "$(hdr flaky 2)"
assert_eq "AC-5 --fast: header 4"  "# commit:  $(k_commit)" "$(hdr flaky 4)"
assert_eq "AC-5 --fast: log byte for byte" identical "$(body_vs_log flaky)"
assert_eq "AC-5 --fast: kept line, once" 1 "$(count_line "$(kept_line flaky)" "$out")"

rm -f "$KM/fail-a" "$KLOG/flaky.failed.log"; : > "$KM/fail-b"
out="$(kgates --gate flaky)"
assert_eq "AC-5 --gate flaky: a failing gate leaves flaky.failed.log" yes "$(kexists flaky)"
assert_eq "AC-5 --gate flaky: header 2" "# outcome: fail" "$(hdr flaky 2)"
assert_eq "AC-5 --gate flaky: this run's log, byte for byte" identical "$(body_vs_log flaky)"
assert_eq "AC-5 --gate flaky: and it is this run's" 1 "$(in_kept flaky 'boom B')"
assert_eq "AC-5 --gate flaky: kept line, once" 1 "$(count_line "$(kept_line flaky)" "$out")"

# A gate the run does not execute leaves its kept file alone, even when the
# gate that does run also fails.
cp "$KLOG/flaky.failed.log" "$KM/flaky.before-broke" 2>/dev/null
out="$(kgates --gate broke)"
assert_eq "AC-5 control: --gate broke runs broke" 1 "$(count_re '^=== gate: broke ' "$out")"
assert_eq "AC-5 control: and not flaky" 0 "$(count_re '^=== gate: flaky ' "$out")"
assert_eq "AC-5: --gate broke leaves flaky.failed.log byte-identical" identical \
  "$(same "$KM/flaky.before-broke" "$KLOG/flaky.failed.log")"
assert_eq "AC-5: and prints no kept line for flaky" 0 "$(count_line "$(kept_line flaky)" "$out")"

rm -rf "$KM"
git -C "$FIX" checkout -q -- . 2>/dev/null
git -C "$FIX" checkout -q main 2>/dev/null
set_phase "$FIX" ""

# ============================================================================
# HARNESS-028: a floor shortfall the environment caused is classified
# ============================================================================
#
# A gate below its floor is `noevidence` today: FAIL when required, WARN when
# optional. That conflates a suite that SHRANK with a checkout that does not
# carry the suite's inputs (gitignored data: `Tests  1 passed, 25 skipped`).
# `skipped-when | <id> | <regex>` classifies the second: BLOCKED (exit 3) when
# the gate is required, KNOWN (exit 0) when optional. A shortfall the pattern
# does not match stays byte-for-byte what it is today (AC-4), and that is the
# half a pattern that EXCUSED every shortfall would break.
#
# Ported from manga-translator MT-037 (5a51681), fixture cases only: nothing
# here reads this repository's real project.conf.
#
# One manifest, one marker file. `itest` cats .claude/state/h28/itest.out and
# exits with .claude/state/h28/itest.rc (default 0), so each case is one write.
# The markers live under .claude/state/, never the fixture root: an untracked
# root file classifies as source and a full run would refuse to record
# (HARNESS-014), and AC-1/AC-2 read the record.
#
# Every summary line is compared WHOLE (count_line, grep -cxF) after the `(Ns`
# normalisation the HARNESS-024 goldens use. Regexes (count_re, awk) are only
# anchored prefixes using [...], *, +, ( ), | and literals: no intervals, no
# \d, no backreferences (HARNESS-025: Ubuntu's awk is mawk).

describe "HARNESS-028 AC-1..AC-8  a shortfall the environment caused is classified, not excused"

set_phase "$FIX" ""
git -C "$FIX" checkout -q -- . 2>/dev/null
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
SM="$FIX/.claude/state/h28"
rm -rf "$SM"; mkdir -p "$SM"
rm -f "$FIX/.claude/state/gate-logs/itest.failed.log"

SKIPPAT='[1-9][0-9]* (skipped|deselected)'
# it_conf <optional|required>   The C-3 manifest; extra lines on stdin.
it_conf() {
  local extra; extra="$(cat)"
  write_conf "$FIX" <<EOF
gate         | itest | $1 | . | cat .claude/state/h28/itest.out; exit \$(cat .claude/state/h28/itest.rc 2>/dev/null || printf 0)
evidence     | itest | Tests +[1-9][0-9]* passed
floor        | itest | 26
skipped-when | itest | $SKIPPAT
$extra
EOF
}
# it_log <log line> [exit status]
it_log() {
  printf '%s\n' "$1" > "$SM/itest.out"
  rm -f "$SM/itest.rc"
  [ -z "${2:-}" ] || printf '%s\n' "$2" > "$SM/itest.rc"
}
# gates.sh's stdout+stderr, CR-stripped, with `(<N>s` normalised to `(Ns`
# exactly as gates_golden does for the HARNESS-024 goldens. Exit status is
# gates.sh's own.
it_gates() {
  local o r
  o="$( cd "$FIX" && bash scripts/gates.sh "$@" 2>&1 )"; r=$?
  printf '%s\n' "$o" | tr -d '\r' | sed -E 's/\(([0-9]+)s([,)])/(Ns\2/g'
  return "$r"
}
it_rec() { tr -d '\r' < "$FIX/docs/backlog/stories/T-1.md"; }
it_hdr() { sed -n "$1p" "$FIX/.claude/state/gate-logs/itest.failed.log" 2>/dev/null | tr -d '\r'; }

ILOG='-> .claude/state/gate-logs/itest.log'
WHY1='did 1 units of work, below the floor of 26 in project.conf; the log says 25 skipped, so the work was skipped rather than lost: the environment did not supply it'
WHYD='did 1 units of work, below the floor of 26 in project.conf; the log says 25 deselected, so the work was skipped rather than lost: the environment did not supply it'
KNOWN1="KNOWN        itest (Ns, $WHY1) $ILOG"
BLOCK1="BLOCKED      itest (Ns, $WHY1) $ILOG"
BLOCK1E="BLOCKED      itest (required by story T-1) (Ns, $WHY1) $ILOG"
PASS26='PASS         itest (Ns, observed 26, floor 26)'
KEPT='failing log kept: .claude/state/gate-logs/itest.failed.log'
# AC-4's expected lines, captured in RED (2026-10-04) from gates.sh at 91eed2c -
# today's script - over this manifest WITHOUT the skipped-when line, log
# `Tests  3 passed`, exit 0. Byte for byte after the (Ns normalisation.
TODAY_WARN3='WARN         itest (Ns, did 3 units of work, below the floor of 26 in project.conf, optional)'
TODAY_FAIL3="FAIL         itest (Ns, did 3 units of work, below the floor of 26 in project.conf) $ILOG"
# And, from the same capture, a non-zero exit whose log carries the skip line.
TODAY_WARNRC="WARN         itest (Ns, exit 2, optional) $ILOG"
TODAY_FAILRC="FAIL         itest (Ns, exit 2) $ILOG"

# --- AC-1 / AC-7: optional, 1 passed of 26, 25 skipped ----------------------
story "$FIX" T-1 GATES </dev/null
set_phase "$FIX" GATES
it_conf optional </dev/null
it_log 'Tests  1 passed, 25 skipped'
rm -f "$FIX/.claude/state/last-gate-run"
out="$(it_gates)"; rc=$?
assert_eq "AC-1: an optional gate whose shortfall the log says was skipped is one KNOWN line, naming the shortfall and the matched text" \
  1 "$(count_line "$KNOWN1" "$out")"
assert_eq "AC-1: and it is the only line for itest beginning KNOWN" 1 "$(count_re '^KNOWN +itest \(' "$out")"
assert_eq "AC-1: a skipped shortfall is not reported as a PASS" 0 "$(count_re '^PASS +itest' "$out")"
assert_eq "AC-1: nor as the WARN today's gates.sh prints" 0 "$(count_re '^WARN +itest' "$out")"
assert_eq "AC-1: the run exits 0" 0 "$rc"
assert_eq "AC-1 control: the run recorded into T-1" 1 "$(count_re '^recorded in docs/backlog/stories/T-1\.md' "$out")"
assert_eq "AC-1: ## Gate results records result: pass" 1 "$(count_re '^    result: pass \(' "$(it_rec)")"
assert_eq "AC-1: and the stamp says RESULT=pass" 1 \
  "$(count_line 'RESULT=pass' "$(tr -d '\r' < "$FIX/.claude/state/last-gate-run")")"
assert_eq "AC-7: a skip-classified run keeps itest.failed.log, header naming the gate" \
  "# gates.sh: last failing run of gate 'itest'" "$(it_hdr 1)"
assert_eq "AC-7: whose outcome header says environment, not a code failure" "# outcome: environment" "$(it_hdr 2)"
assert_eq "AC-7: and the kept log carries the skip line" 1 \
  "$(count_line 'Tests  1 passed, 25 skipped' "$(tr -d '\r' < "$FIX/.claude/state/gate-logs/itest.failed.log" 2>/dev/null)")"
assert_eq "AC-7: the failing-log-kept line is printed once" 1 "$(count_line "$KEPT" "$out")"

# C-1: the stored pattern is the WHOLE remainder of its line (rest 3), so the
# second alternation branch reaches the classifier: `deselected` only matches
# if `(skipped|deselected)` survived the split on `|`.
it_log 'Tests  1 passed, 25 deselected'
out="$(it_gates)"; rc=$?
assert_eq "AC-1 (C-1): the pattern's second alternation branch classifies too, quoting what matched" \
  1 "$(count_line "KNOWN        itest (Ns, $WHYD) $ILOG" "$out")"
assert_eq "AC-1 (C-1): and exits 0" 0 "$rc"

# C-1: an optional gate with a waiver keeps the waiver beside the reason.
it_conf optional <<'EOF'
waiver       | itest | fixture data is not redistributable
EOF
it_log 'Tests  1 passed, 25 skipped'
out="$(it_gates)"
assert_eq "C-1: an optional waived gate names the waiver after the skip reason" \
  1 "$(count_line "KNOWN        itest (Ns, $WHY1; fixture data is not redistributable) $ILOG" "$out")"

# --- AC-2: required, by the manifest and by the story -----------------------
it_conf required </dev/null
it_log 'Tests  1 passed, 25 skipped'
rm -f "$FIX/.claude/state/last-gate-run"
out="$(it_gates)"; rc=$?
assert_eq "AC-2 manifest-required: a skipped shortfall is BLOCKED, whole line" 1 "$(count_line "$BLOCK1" "$out")"
assert_eq "AC-2 manifest-required: the run exits 3" 3 "$rc"
assert_eq "AC-2 manifest-required: ## Gate results records result: blocked" 1 "$(count_re '^    result: blocked \(' "$(it_rec)")"
assert_eq "AC-2 manifest-required: no PASS line for itest" 0 "$(count_re '^PASS +itest' "$out")"
assert_eq "AC-2 manifest-required: and no PASS line for it in the record check-boundaries.sh reads" 0 \
  "$(count_re '^ *PASS +itest' "$(it_rec)")"
assert_eq "AC-2 manifest-required: and the stamp says RESULT=blocked" 1 \
  "$(count_line 'RESULT=blocked' "$(tr -d '\r' < "$FIX/.claude/state/last-gate-run")")"

story "$FIX" T-1 GATES <<'EOF'
required_gates: [itest]
EOF
it_conf optional </dev/null
out="$(it_gates)"; rc=$?
assert_eq "AC-2 story-escalated: an optional gate the story requires is BLOCKED, naming the story" 1 "$(count_line "$BLOCK1E" "$out")"
assert_eq "AC-2 story-escalated: the run exits 3" 3 "$rc"
assert_eq "AC-2 story-escalated: ## Gate results records result: blocked" 1 "$(count_re '^    result: blocked \(' "$(it_rec)")"
assert_eq "AC-2 story-escalated: no PASS line for itest" 0 "$(count_re '^PASS +itest' "$out")"
assert_eq "AC-2 story-escalated: and it is not the KNOWN an unescalated optional gate gets" 0 "$(count_re '^KNOWN +itest' "$out")"
story "$FIX" T-1 GATES </dev/null

# --- AC-3 (control): a full run passes, the pattern unconsulted --------------
for _req in optional required; do
  it_conf "$_req" </dev/null
  it_log 'Tests  26 passed'
  out="$(it_gates)"; rc=$?
  assert_eq "AC-3 control ($_req): 26 of 26 is a PASS, whole line" 1 "$(count_line "$PASS26" "$out")"
  assert_eq "AC-3 control ($_req): and exits 0" 0 "$rc"
done
# At the floor with some tests skipped: still a pass. The pattern is consulted
# only below the floor.
it_conf optional </dev/null
it_log 'Tests  26 passed, 3 skipped'
out="$(it_gates)"
assert_eq "AC-3 control: at the floor, a log that also says skipped is still a PASS" 1 "$(count_line "$PASS26" "$out")"
assert_eq "AC-3 control: and not a KNOWN" 0 "$(count_re '^KNOWN +itest' "$out")"

# --- AC-4 (control): an unmatched shortfall is exactly today's ---------------
it_conf optional </dev/null
it_log 'Tests  3 passed'
out="$(it_gates)"; rc=$?
assert_eq "AC-4 control optional: a shortfall the pattern does not match prints today's WARN line" 1 "$(count_line "$TODAY_WARN3" "$out")"
assert_eq "AC-4 control optional: and is not excused as KNOWN" 0 "$(count_re '^KNOWN +itest' "$out")"
assert_eq "AC-4 control optional: exits 0, as today" 0 "$rc"
it_log 'Tests  3 passed, 0 skipped'
out="$(it_gates)"
assert_eq "AC-4 control optional: '0 skipped' does not match [1-9][0-9]*, so it is today's WARN" 1 "$(count_line "$TODAY_WARN3" "$out")"

it_conf required </dev/null
it_log 'Tests  3 passed'
out="$(it_gates)"; rc=$?
assert_eq "AC-4 control required: a shortfall the pattern does not match prints today's FAIL line" 1 "$(count_line "$TODAY_FAIL3" "$out")"
assert_eq "AC-4 control required: and is not reported BLOCKED" 0 "$(count_re '^BLOCKED +itest' "$out")"
assert_eq "AC-4 control required: exits 1, as today" 1 "$rc"

# Out of scope, pinned because it is cheap: a non-zero exit is never consulted
# against the skip pattern, whatever its log says.
it_conf optional </dev/null
it_log 'Tests  1 passed, 25 skipped' 2
out="$(it_gates)"
assert_eq "scope optional: a non-zero exit whose log says skipped is today's WARN, not KNOWN" 1 "$(count_line "$TODAY_WARNRC" "$out")"
it_conf required </dev/null
out="$(it_gates)"; rc=$?
assert_eq "scope required: a non-zero exit whose log says skipped is today's FAIL, not BLOCKED" 1 "$(count_line "$TODAY_FAILRC" "$out")"
assert_eq "scope required: and exits 1" 1 "$rc"

# --- AC-5: --audit ----------------------------------------------------------
set_phase "$FIX" ""
write_conf "$FIX" <<EOF
gate         | itest | optional | . | printf 'Tests  26 passed\n'
evidence     | itest | Tests +[1-9][0-9]* passed
floor        | itest | 26
skipped-when | itset | $SKIPPAT
EOF
out="$(it_gates --audit)"; rc=$?
assert_eq "AC-5: --audit fails a skipped-when that names no configured gate, naming it" 1 \
  "$(count_line "$(printf 'FAIL %-12s a `skipped-when` line names no configured gate' itset)" "$out")"
assert_eq "AC-5: and exits 1" 1 "$rc"

write_conf "$FIX" <<'EOF'
gate         | itest | optional | . | printf 'Tests  26 passed\n'
evidence     | itest | Tests +[1-9][0-9]* passed
floor        | itest | 26
skipped-when | itest |
EOF
out="$(it_gates --audit)"; rc=$?
assert_eq "AC-5: --audit fails a skipped-when with no pattern" 1 \
  "$(count_line "$(printf 'FAIL %-12s a `skipped-when` line has no pattern' itest)" "$out")"
assert_eq "AC-5: and exits 1" 1 "$rc"

write_conf "$FIX" <<EOF
gate         | itest | optional | . | printf 'Tests  26 passed\n'
evidence     | itest | Tests +[1-9][0-9]* passed
skipped-when | itest | $SKIPPAT
EOF
out="$(it_gates --audit)"; rc=$?
assert_eq "AC-5: --audit fails a skipped-when on a gate with no floor" 1 \
  "$(count_line "$(printf 'FAIL %-12s a `skipped-when` line names a gate with no `floor` line: there is nothing to measure the shortfall it would classify' itest)" "$out")"
assert_eq "AC-5: and exits 1" 1 "$rc"
assert_eq "AC-5: one manifest problem, not more" 1 "$(count_line '1 manifest problem(s).' "$out")"

it_conf optional </dev/null
out="$(it_gates --audit)"; rc=$?
assert_eq "AC-5 control: a well-formed skipped-when on a floored gate passes the audit" 1 "$(count_line 'Manifest audit passed.' "$out")"
assert_eq "AC-5 control: and exits 0" 0 "$rc"
assert_eq "AC-5 control: no FAIL line names a skipped-when" 0 "$(count_re '^FAIL .*skipped-when' "$out")"
assert_eq "AC-5 control: the audit prints the pattern under the gate" 1 \
  "$(count_line "$(printf '     %-12s skipped-when: %s' '' "$SKIPPAT")" "$out")"

# --- AC-6: --list -----------------------------------------------------------
it_conf optional <<'EOF'
blocked-when | itest | no fixture device
EOF
out="$(it_gates --list)"
assert_eq "AC-6: --list prints skipped-when with its | alternation whole" 1 \
  "$(count_line "$(printf '%-12s %-9s %-6s skipped-when: %s' '' '' '' "$SKIPPAT")" "$out")"
assert_eq "AC-6 control: in the same column style as the blocked-when line beside it" 1 \
  "$(count_line "$(printf '%-12s %-9s %-6s blocked-when: %s' '' '' '' 'no fixture device')" "$out")"

# --- AC-8 -------------------------------------------------------------------
# No new assertion: the HARNESS-024 AC-3 golden comparisons above are the check.
# RED confirmed (2026-10-04) that no fixtures/manifest/*.conf carries
# skipped-when and no golden run is below its floor (unit 47 vs 40, lint 5 vs 3).

rm -rf "$SM"
rm -f "$FIX/.claude/state/gate-logs/itest.failed.log"
git -C "$FIX" checkout -q -- . 2>/dev/null
git -C "$FIX" checkout -q main 2>/dev/null
set_phase "$FIX" ""


# ============================================================================
# HARNESS-030: the gates refuse to judge a tree behind a stranded mutation
# (AC-5), and a mutation's own command may run them but never record (AC-6)
# ============================================================================
#
# A STRANDED mutation is planted, not produced by a kill (the story's C-4): the
# target mutated, a `.bak` holding the original, an `.active` with the seven
# keys whose pid is the `$$` of a `bash -c` that has already exited. A RUNNING
# one uses the pid of a bounded `sleep 30 &`, killed when its case ends and by
# the EXIT trap.
#
# EVERY PLANTED SENTINEL IS REMOVED WHEN ITS CASE ENDS. FIX is shared by the
# whole suite, and one sentinel left behind would make every later gates.sh run
# exit 2.
#
# Whether a gate RAN is a fact about the filesystem, not a reading of the
# summary (MT-047, and the ondemand block's MARKER above): the gate command
# touches h30-ran. Before each refused run the stamp, the gate log and the story
# are set to known content, so "untouched" is a byte comparison against a value
# no real run could reproduce - not a cksum of a file a rewrite within the same
# second could reproduce exactly.
#
# The recorded-run cases run on story/T-1-fixture (HARNESS-026). Needles are
# whole lines through count_line, or anchored count_re with no intervals.

H30W="$(mktemp -d 2>/dev/null || mktemp -d -t h030.XXXXXX)"
H30_SLEEP=""
trap '[ -n "$H30_SLEEP" ] && kill "$H30_SLEEP" 2>/dev/null; rm -rf "$FIX" "$H30W"' EXIT

git -C "$FIX" checkout -q -- . 2>/dev/null
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | touch .claude/state/h30-ran; printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
floor    | unit | 40
EOF
story "$FIX" T-1 GATES </dev/null
fix_commit "HARNESS-030 fixture: a marker gate, T-1 on its own branch"
set_phase "$FIX" GATES

H30ABS="$(cd "$FIX" && pwd)"
H30MUT="$H30ABS/.claude/state/mutations"
H30MARK="$FIX/.claude/state/h30-ran"
H30LOGS="$FIX/.claude/state/gate-logs"
H30STAMPF="$FIX/.claude/state/last-gate-run"
T1="$FIX/docs/backlog/stories/T-1.md"
H30_REFUSAL='gates: refusing to run. The gates judge the working tree, and the tree may hold a mutation nobody restored.'
H30_UNACCOUNTED='mutate: a mutation is unaccounted for. The tree may not be the code you think.'
H30_INSIDE="(not recorded: this run is inside mutate.sh's mutation of .claude/harness/project.conf; a verdict on mutated code is not evidence)"
H30_RECORDED='^recorded in docs/backlog/stories/T-1\.md'

h30_mark() { if [ -e "$H30MARK" ]; then printf present; else printf absent; fi; }
# h30_logs   Every file under gate-logs/ with its checksum, in glob order.
h30_logs() { local f; for f in "$H30LOGS"/*; do [ -f "$f" ] && printf '%s %s\n' "${f##*/}" "$(cksum < "$f")"; done; }
# h30_fresh   Known state before a run: no marker, the story as committed (an
# empty ## Gate results), a stamp and a gate log no real run writes.
h30_fresh() {
  rm -f "$H30MARK"
  git -C "$FIX" checkout -q -- docs/backlog/stories/T-1.md 2>/dev/null
  mkdir -p "$H30LOGS"
  printf 'RESULT=h30-before\n' > "$H30STAMPF"
  printf 'h30 before\n' > "$H30LOGS/unit.log"
}
# line_no <exact line> <text>   The number of the first line that is exactly
# <line>, or empty.
line_no() { awk 'BEGIN { l = ARGV[1]; ARGV[1] = "" } $0 == l { print NR; exit }' "$1" <<< "$2"; }
# h30_plant <sentinel> <pid> <file>   A sentinel with all seven keys, for a
# target in this fixture; its backup is <sentinel>.bak's sibling.
h30_plant() {
  mkdir -p "$H30MUT"
  printf 'pid\t%s\nfile\t%s\npath\t%s\nbackup\t%s\nexpr\t%s\ncommand\t%s\nstarted\t%s\n' \
    "$2" "$3" "$H30ABS/$3" "${1%.active}.bak" 's/1/-1/' 'bash scripts/gates.sh' 20261004T010203Z > "$1"
}
# h30_probe <expr> [gates args...]   The fixture's OWN mutate.sh mutating the
# fixture's project.conf around the fixture's gates.sh, so the sentinel is in
# the fixture's mutations/ (the story's C-4).
h30_probe() { local e="$1"; shift; ( cd "$FIX" && bash scripts/mutate.sh .claude/harness/project.conf "$e" -- bash scripts/gates.sh "$@" 2>&1 ); }

# --- the baseline: nothing planted, the run records ---------------------------
h30_fresh
out="$(gates)"; rc=$?
assert_eq "HARNESS-030 baseline: with nothing planted the full run exits 0" 0 "$rc"
assert_eq "HARNESS-030 baseline: the marker gate's command ran" present "$(h30_mark)"
assert_eq "HARNESS-030 baseline: and the run records" 1 "$(count_re "$H30_RECORDED" "$out")"

# --- AC-5: refused behind a stranded mutation ---------------------------------
H30_DEAD="$(bash -c 'echo $$')"
if kill -0 "$H30_DEAD" 2>/dev/null; then h30_alive=alive; else h30_alive=gone; fi
assert_eq "AC-5 precondition: the planted pid belongs to a process that has exited" gone "$h30_alive"
H30_ACT="$H30MUT/src_main.ts.20261004T010203Z.$H30_DEAD.active"
mkdir -p "$H30MUT"
cp "$FIX/src/main.ts" "${H30_ACT%.active}.bak"
printf 'export const x = -1\n' > "$FIX/src/main.ts"
h30_plant "$H30_ACT" "$H30_DEAD" src/main.ts

# The precondition is checked, not assumed: if --check did not call this
# stranded, every refusal below would be testing nothing.
check_out="$( cd "$FIX" && bash scripts/mutate.sh --check 2>&1 )"; check_rc=$?
assert_eq "AC-5 precondition: mutate.sh --check calls the planted sentinel stranded (exit 1)" 1 "$check_rc"

h30_refused() { # <label> [gates args...]
  local label="$1" logs_before n_report n_refusal; shift
  h30_fresh
  logs_before="$(h30_logs)"
  cp "$T1" "$H30W/t1.before"
  out="$(gates "$@")"; rc=$?
  assert_eq "$label: behind a stranded mutation gates.sh exits 2" 2 "$rc"
  assert_eq "$label: it prints the refusal, whole" 1 "$(count_line "$H30_REFUSAL" "$out")"
  assert_eq "$label: after --check's report, which opens with the unaccounted-for line" 1 "$(count_line "$H30_UNACCOUNTED" "$out")"
  assert_eq "$label: and names the stranded file" 1 "$(count_line '  src/main.ts' "$out")"
  n_report="$(line_no "$H30_UNACCOUNTED" "$out")"; n_refusal="$(line_no "$H30_REFUSAL" "$out")"
  if [ -n "$n_report" ] && [ -n "$n_refusal" ] && [ "$n_report" -lt "$n_refusal" ]; then
    _ok "$label: the report comes before the refusal"
  else _bad "$label: the report comes before the refusal" "report at line '${n_report}', refusal at line '${n_refusal}'"; fi
  assert_eq "$label: no '=== gate:' line is printed" 0 "$(count_re '^=== gate:' "$out")"
  assert_eq "$label: the gate command never ran (marker absent)" absent "$(h30_mark)"
  assert_eq "$label: gate-logs/ is untouched" "$logs_before" "$(h30_logs)"
  assert_eq "$label: last-gate-run is untouched" 'RESULT=h30-before' "$(tr -d '\r' < "$H30STAMPF")"
  if cmp -s "$H30W/t1.before" "$T1"; then _ok "$label: the story's ## Gate results is byte-identical"
  else _bad "$label: the story's ## Gate results is byte-identical" "the story file changed"; fi
}
h30_refused "AC-5 gates.sh"
h30_refused "AC-5 gates.sh --fast"      --fast
h30_refused "AC-5 gates.sh --gate unit" --gate unit

# --list and --audit read the manifest and never run a gate, so a stranded
# mutation is none of their business.
h30_fresh
out="$(gates --list)"; rc=$?
assert_eq "AC-5: --list still exits 0 behind a stranded mutation" 0 "$rc"
assert_contains "AC-5: --list still lists the gate" "unit" "$out"
assert_eq "AC-5: --list prints no refusal" 0 "$(count_line "$H30_REFUSAL" "$out")"
out="$(gates --audit)"; rc=$?
assert_eq "AC-5: --audit still exits 0 behind a stranded mutation" 0 "$rc"
assert_eq "AC-5: --audit prints no refusal" 0 "$(count_line "$H30_REFUSAL" "$out")"
assert_eq "AC-5: neither ran the gate" absent "$(h30_mark)"

# A SECOND, dead sentinel under a mutation still refuses (C-3: "a second
# sentinel, live or dead"). Planted beside the probe's own.
h30_fresh
out="$(h30_probe 's/47 passed (47)/48 passed (48)/' --gate unit)"; rc=$?
assert_eq "AC-6 control: under a mutation, a second, dead sentinel still refuses: exit 2" 2 "$rc"
assert_eq "AC-6 control: with the refusal, whole" 1 "$(count_line "$H30_REFUSAL" "$out")"
assert_eq "AC-6 control: and the gate never ran" absent "$(h30_mark)"

# AC-5 control: resolved - file back, backup and sentinel gone - the same three
# runs proceed. Without this a gates.sh that refused unconditionally would pass
# every assertion above.
cp "${H30_ACT%.active}.bak" "$FIX/src/main.ts"
rm -f "$H30_ACT" "${H30_ACT%.active}.bak"
h30_fresh
out="$(gates)"; rc=$?
assert_eq "AC-5 control: with the sentinel removed the full run exits 0" 0 "$rc"
assert_eq "AC-5 control: and prints the marker gate's header" 1 "$(count_re '^=== gate: unit ' "$out")"
assert_eq "AC-5 control: and the gate command ran" present "$(h30_mark)"
assert_eq "AC-5 control: and the run records" 1 "$(count_re "$H30_RECORDED" "$out")"
h30_fresh
out="$(gates --fast)"; rc=$?
assert_eq "AC-5 control: --fast proceeds, exit 0" 0 "$rc"
assert_eq "AC-5 control: --fast ran the gate" present "$(h30_mark)"
h30_fresh
out="$(gates --gate unit)"; rc=$?
assert_eq "AC-5 control: --gate unit proceeds, exit 0" 0 "$rc"
assert_eq "AC-5 control: --gate unit ran the gate" present "$(h30_mark)"

# --- AC-6: the mutation's own command ------------------------------------------
# A gate probe (rules.md requires one whenever a story changes a gate): mutate
# the conf, run the gate under it. Its own sentinel must not refuse it.
h30_fresh
out="$(h30_probe 's/47 passed (47)/48 passed (48)/' --gate unit)"; rc=$?
assert_eq "AC-6: a gate probe under its own mutation runs the gate: exit 0" 0 "$rc"
assert_eq "AC-6: the probe prints no refusal" 0 "$(count_line "$H30_REFUSAL" "$out")"
assert_eq "AC-6: the gate's header is printed" 1 "$(count_re '^=== gate: unit ' "$out")"
assert_eq "AC-6: the gate command ran" present "$(h30_mark)"
assert_eq "AC-6: and its result is the mutated gate's own: PASS, observed 48 against the floor of 40" 1 \
  "$(count_re '^PASS +unit \([0-9]+s, observed 48, floor 40\)$' "$out")"
h30_fresh
out="$(h30_probe 's/47 passed (47)/3 passed (3)/' --gate unit)"; rc=$?
assert_eq "AC-6: a probe whose mutation breaks the gate gets the gate's failure: exit 1" 1 "$rc"
assert_eq "AC-6: below the floor, as the gate says" 1 "$(count_re 'below the floor of 40' "$out")"
assert_eq "AC-6: and no refusal" 0 "$(count_line "$H30_REFUSAL" "$out")"

# PO decision 1: a FULL run inside a mutation of this tree runs, and is never
# recorded. On the story's own branch, so nothing else refuses it.
h30_fresh
cp "$T1" "$H30W/t1.before"
out="$(h30_probe 's/47 passed (47)/48 passed (48)/')"; rc=$?
assert_eq "AC-6: a full run under a mutation exits 1" 1 "$rc"
assert_eq "AC-6: and says why it is not recorded, whole" 1 "$(count_line "$H30_INSIDE" "$out")"
assert_eq "AC-6: that is the only '(not recorded:' line" 1 "$(count_re '^\(not recorded:' "$out")"
assert_eq "AC-6: no line claims to have recorded" 0 "$(count_re "$H30_RECORDED" "$out")"
assert_eq "AC-6: the stamp says FULL=no" no "$(stamp_val FULL)"
if cmp -s "$H30W/t1.before" "$T1"; then _ok "AC-6: the story's ## Gate results is byte-identical"
else _bad "AC-6: the story's ## Gate results is byte-identical" "the story file changed"; fi
assert_eq "AC-6: but the gates did run" present "$(h30_mark)"

# Precedence (C-2): mutated code first, then the branch. From another branch,
# the one reason given is the mutation.
git -C "$FIX" checkout -q -b h30-elsewhere 2>/dev/null
h30_fresh
out="$(h30_probe 's/47 passed (47)/48 passed (48)/')"; rc=$?
assert_eq "AC-6 (C-2): from another branch the reason given is still the mutation" 1 "$(count_line "$H30_INSIDE" "$out")"
assert_eq "AC-6 (C-2): and not the branch" 0 "$(count_re '^\(not recorded: the checkout is on ' "$out")"
assert_eq "AC-6 (C-2): one '(not recorded:' line" 1 "$(count_re '^\(not recorded:' "$out")"
assert_eq "AC-6 (C-2): exit 1" 1 "$rc"
git -C "$FIX" checkout -q story/T-1-fixture 2>/dev/null
git -C "$FIX" branch -q -D h30-elsewhere 2>/dev/null

# Controls on HARNESS_MUTATION itself: it counts only when it names a file
# in THIS tree's mutations/. A deferred verification runs gates.test.sh under a
# mutation of the real tree, and every fixture gates.sh inherits that variable;
# if the fixture took it for its own, every recorded-run assertion in this
# suite would fail under every such verification.
mkdir -p "$H30W/other/.claude/state/mutations"
printf 'pid\t%s\nfile\tsrc/x.ts\n' "$$" > "$H30W/other/.claude/state/mutations/x.active"
h30_fresh
out="$( cd "$FIX" && HARNESS_MUTATION="$H30W/other/.claude/state/mutations/x.active" bash scripts/gates.sh 2>&1 )"; rc=$?
assert_eq "C-2 control: HARNESS_MUTATION naming another tree's sentinel: the run records" 1 "$(count_re "$H30_RECORDED" "$out")"
assert_eq "C-2 control: and exits 0" 0 "$rc"
assert_eq "C-2 control: and stamps FULL=yes" yes "$(stamp_val FULL)"
h30_fresh
out="$( cd "$FIX" && HARNESS_MUTATION="$H30MUT/no-such.active" bash scripts/gates.sh 2>&1 )"; rc=$?
assert_eq "C-2 control: HARNESS_MUTATION naming no file in this tree: the run records" 1 "$(count_re "$H30_RECORDED" "$out")"
assert_eq "C-2 control: and exits 0" 0 "$rc"

# AC-6 control: a SECOND, unrelated LIVE sentinel is still RUNNING, and the
# gates still refuse the probe.
sleep 30 &
H30_SLEEP=$!
H30_ACT2="$H30MUT/src_other.ts.20261004T010203Z.$H30_SLEEP.active"
printf 'other\n' > "${H30_ACT2%.active}.bak"
h30_plant "$H30_ACT2" "$H30_SLEEP" src/other.ts
h30_fresh
out="$(h30_probe 's/47 passed (47)/48 passed (48)/' --gate unit)"; rc=$?
assert_eq "AC-6 control: beside a second live sentinel the probe is refused: exit 2" 2 "$rc"
assert_eq "AC-6 control: that sentinel is reported RUNNING" 1 \
  "$(count_line "    process:     $H30_SLEEP (RUNNING - a mutation is in flight right now; wait for it)" "$out")"
assert_eq "AC-6 control: with the refusal, whole" 1 "$(count_line "$H30_REFUSAL" "$out")"
assert_eq "AC-6 control: and the gate never ran" absent "$(h30_mark)"
kill "$H30_SLEEP" 2>/dev/null; wait "$H30_SLEEP" 2>/dev/null; H30_SLEEP=""
rm -f "$H30_ACT2" "${H30_ACT2%.active}.bak"

# --- HARNESS-059 AC-2: refused behind a stranded mutation of a .claude/ file ---
# F1 at the gate: the sentinel for a target under .claude/ is named with a
# leading `.`, and gates.sh learns of stranded mutations only through
# `mutate.sh --check` (gates.sh:233). A GONE sentinel for .claude/hooks/lib.sh,
# its backup DIFFERING from the fixture's file - the backup is made to differ,
# so the fixture's lib.sh, which gates.sh may read, is not edited.
H59_DEAD="$(bash -c 'echo $$')"
if kill -0 "$H59_DEAD" 2>/dev/null; then h59_alive=alive; else h59_alive=gone; fi
assert_eq "HARNESS-059 AC-2 precondition: the planted pid belongs to a process that has exited" gone "$h59_alive"
H59_ACT="$H30MUT/.claude_hooks_lib.sh.20261016T053548Z.$H59_DEAD.active"
printf 'not what lib.sh holds\n' > "${H59_ACT%.active}.bak"
h30_plant "$H59_ACT" "$H59_DEAD" .claude/hooks/lib.sh
if cmp -s "${H59_ACT%.active}.bak" "$FIX/.claude/hooks/lib.sh"; then h59_differs=matches; else h59_differs=differs; fi
assert_eq "HARNESS-059 AC-2 precondition: the planted backup differs from the fixture's .claude/hooks/lib.sh" differs "$h59_differs"
h30_fresh
out="$(gates)"; rc=$?
assert_eq "HARNESS-059 AC-2: behind a stranded .claude/ mutation gates.sh exits 2" 2 "$rc"
assert_eq "HARNESS-059 AC-2: it prints the refusal, whole" 1 "$(count_line "$H30_REFUSAL" "$out")"
assert_eq "HARNESS-059 AC-2: after --check's unaccounted-for line" 1 "$(count_line "$H30_UNACCOUNTED" "$out")"
assert_eq "HARNESS-059 AC-2: which names .claude/hooks/lib.sh" 1 "$(count_line '  .claude/hooks/lib.sh' "$out")"
assert_eq "HARNESS-059 AC-2: no line says the run recorded" 0 "$(count_re "$H30_RECORDED" "$out")"
assert_eq "HARNESS-059 AC-2: and the gate command never ran (marker absent)" absent "$(h30_mark)"
h30_fresh
out="$(gates --gate unit)"; rc=$?
assert_eq "HARNESS-059 AC-2: gates.sh --gate unit is refused too, exit 2" 2 "$rc"
assert_eq "HARNESS-059 AC-2: --gate unit prints the refusal, whole" 1 "$(count_line "$H30_REFUSAL" "$out")"
assert_eq "HARNESS-059 AC-2: and --gate unit never ran the gate" absent "$(h30_mark)"
rm -f "$H59_ACT" "${H59_ACT%.active}.bak"

# The glob sees dot-named sentinels too (the story's C-4): `*.active` alone
# would report this fixture clean over a stranded .claude/ mutation.
assert_eq "HARNESS-030: no sentinel is left in the shared fixture" "" \
  "$(for a in "$H30MUT"/*.active "$H30MUT"/.*.active; do [ -e "$a" ] && printf '%s ' "${a##*/}"; done)"
rm -f "$H30MARK"
git -C "$FIX" checkout -q -- . 2>/dev/null
git -C "$FIX" checkout -q main 2>/dev/null
set_phase "$FIX" ""


# ===========================================================================
# HARNESS-052: a gate that reads stdin cannot swallow the gates after it, and a
# run accounts for every declared gate. Ported from manhwa-cropper's MC-046 and
# MC-047 suites (the adapted text is in the story's `## Notes`). Every run below
# that is not about the caller's stdin is made with stdin at end-of-input and
# descriptors 3-9 closed, so a gate that drains a descriptor can only reach what
# gates.sh gave it, never this suite's terminal or pipe.
# ===========================================================================

# gates_isolated [args]   gates.sh with stdin at EOF and fds 3-9 closed.
gates_isolated() {
  ( cd "$FIX" && bash scripts/gates.sh "$@" 2>&1 ) </dev/null 3<&- 4<&- 5<&- 6<&- 7<&- 8<&- 9<&-
}

# assert_gate_failed <what> <id> <output>   The summary line for a required gate
# that exited 1, by id: `FAIL         <id> (<n>s, exit 1) -> <its log>`. The
# duration is the one field not pinned.
assert_gate_failed() {
  case "$3" in
    *"FAIL         $2 ("*"s, exit 1) -> .claude/state/gate-logs/$2.log"*) _ok "$1" ;;
    *) _bad "$1" "expected a summary line: FAIL         $2 (<n>s, exit 1) -> .claude/state/gate-logs/$2.log
actual:   $3" ;;
  esac
}

# assert_lacks <what> <needle> <haystack>   The downstream name for _lib.sh's
# assert_not_contains, which is the same assertion; reused rather than copied.
assert_lacks() { assert_not_contains "$@"; }

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-1: a gate that reads its stdin cannot delete the gates after it"

# AC-1(a): the reported bug. Release 93: `later` is absent, "(1 ran, ...)", exit 0.
write_conf "$FIX" <<'EOF'
gate     | eats  | required | . | cat >/dev/null; printf 'Tests 1 passed\n'
gate     | later | required | . | printf 'Tests 2 passed\n'
evidence | eats  | Tests [1-9][0-9]* passed
evidence | later | Tests [1-9][0-9]* passed
EOF
out="$(gates_isolated)"; rc=$?
assert_contains "the gate after a stdin-reading gate still runs" "=== gate: later (required) ===" "$out"
assert_contains "the stdin-reading gate passes"          "PASS         eats (" "$out"
assert_contains "and so does the gate after it"          "PASS         later (" "$out"
assert_contains "and both are counted as having run" \
  "All required gates passed (2 ran, 0 unconfigured, 0 known)." "$out"
assert_eq "a run of two passing gates exits 0" "0" "$rc"

# AC-1(b): worse than reported. Release 93: exit 0, "All required gates passed".
AC1B_CONF="gate     | eats  | required | . | cat >/dev/null; printf 'Tests 1 passed\n'
gate     | later | required | . | exit 1
evidence | eats  | Tests [1-9][0-9]* passed"
printf '%s\n' "$AC1B_CONF" | write_conf "$FIX"
out="$(gates_isolated)"; rc=$?
assert_gate_failed "a failing required gate after a stdin-reading gate is reported FAIL" later "$out"
assert_contains "and the run says a required gate failed" "1 required gate(s) failed." "$out"
assert_lacks "and does not certify the run" "All required gates passed" "$out"
assert_eq "and exits 1" "1" "$rc"

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-2: a gate cannot reach the manifest through any inherited descriptor"

# The obvious fix - read the manifest on fd 3 instead of fd 0 - passes AC-1 and
# relocates the defect: the eval'd command inherits fd 3 and a gate that reads
# it drains the manifest exactly as before. This gate reads 0 and every
# descriptor 3 to 9 an ordinary command can reach by accident.
write_conf "$FIX" <<'EOF'
gate     | eats  | required | . | for fd in 0 3 4 5 6 7 8 9; do cat <&$fd >/dev/null; done 2>/dev/null; printf 'Tests 1 passed\n'
gate     | later | required | . | exit 1
evidence | eats  | Tests [1-9][0-9]* passed
EOF
out="$(gates_isolated)"; rc=$?
assert_gate_failed "a gate after one that drains fds 0 and 3-9 still runs and is reported FAIL" later "$out"
assert_contains "and the run says a required gate failed" "1 required gate(s) failed." "$out"
assert_lacks "and does not certify the run" "All required gates passed" "$out"
assert_eq "and exits 1" "1" "$rc"

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-3: a gate reads end-of-input, not the manifest and not the caller's stdin"

# Release 93: the gate reads the rest of the manifest (57 bytes). Under the
# fd-3-only fix it reads whatever gates.sh was given - here a pipe, in a
# terminal the TTY, where it would block forever. The pipe is finite, so this
# test cannot block whichever of those it meets; it fails instead.
write_conf "$FIX" <<'EOF'
gate  | count | required | . | printf 'stdin-bytes=%s\n' "$(wc -c | tr -d ' ')"
gate  | after | required | . | printf 'Tests 2 passed\n'
EOF
rm -f "$FIX/.claude/state/gate-logs/count.log"
out="$(printf 'CALLER-DATA\n' | ( cd "$FIX" && bash scripts/gates.sh 2>&1 ))"
assert_contains "a run given data on stdin still finishes" "--- gate summary ---" "$out"
seen="$(grep '^stdin-bytes=' "$FIX/.claude/state/gate-logs/count.log" 2>/dev/null)"
assert_eq "a gate reads zero bytes of stdin, whatever gates.sh was given" "stdin-bytes=0" "$seen"

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-4: --fast and --required give the same guarantee as a full run"

# The subsets run the same loop. (--gate <id> is deliberately absent: a
# filtered-out gate hits `continue` before anything runs, so it has no defect.)
printf '%s\n%s\n%s\n' "$AC1B_CONF" \
  "gate     | slow_one | required | . | printf 'Tests 3 passed\n'" \
  "slow     | slow_one | stands in for a release build; RED has no use for it" \
  | write_conf "$FIX"
out="$(gates_isolated --fast)"; rc=$?
assert_gate_failed "--fast: a failing gate after a stdin-reading gate is reported FAIL" later "$out"
assert_contains "--fast: the slow gate after them is still seen, and skipped" "--fast skipped: slow_one" "$out"
assert_contains "--fast: the run says a required gate failed" "1 required gate(s) failed." "$out"
assert_eq "--fast: and exits 1" "1" "$rc"

printf '%s\n' "$AC1B_CONF" | write_conf "$FIX"
out="$(gates_isolated --required)"; rc=$?
assert_gate_failed "--required: a failing gate after a stdin-reading gate is reported FAIL" later "$out"
assert_contains "--required: the run says a required gate failed" "1 required gate(s) failed." "$out"
assert_eq "--required: and exits 1" "1" "$rc"

# ---------------------------------------------------------------------------
# AC-6 to AC-11 (MC-047): the run accounts for every declared gate.
#
# The seam is set per call and never exported, so no later block inherits it.
# It is unset here as well, so that a caller's environment cannot leak into the
# no-false-refusal controls at the end.
unset GATES_FAULT_LOSE

# seam <ids> [gates.sh args...]   A run with GATES_FAULT_LOSE set for that one
# process only.
seam() {
  local lose="$1"; shift
  ( cd "$FIX" && GATES_FAULT_LOSE="$lose" bash scripts/gates.sh "$@" 2>&1 ) </dev/null
}

# assert_line <what> <line> <output>   <line> is a WHOLE line of <output>, not a
# substring of one: a refusal naming `ab` must not pass for `b`.
assert_line() {
  if grep -Fxq -- "$2" <<<"$3"; then _ok "$1"
  else _bad "$1" "expected a line exactly: $2
actual:   $3"; fi
}

# assert_no_line <what> <line> <output>
assert_no_line() {
  if grep -Fxq -- "$2" <<<"$3"; then _bad "$1" "expected NO line: $2
actual:   $3"
  else _ok "$1"; fi
}

# first_line_no <prefix> <output>   The number of the first line that starts
# with <prefix>, compared literally; empty when there is none.
first_line_no() {
  printf '%s\n' "$2" | awk -v p="$1" 'index($0, p) == 1 { print NR; exit }'
}

# refusal <id>   The summary line for a lost gate, 13-column prefix and all.
refusal() { printf 'FAIL         %s (declared in project.conf but never accounted for)' "$1"; }

# lost_count <n>   The line under the summary that counts them.
lost_count() { printf '%s declared gate(s) never accounted for; this run certifies nothing.' "$1"; }

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-6: a gate that rewrites project.conf in place cannot make a later gate vanish from a certified run"

# `first` reads no stdin: it truncates the manifest by path. The loop streams
# project.conf from an open descriptor, so its next read lands past the new end
# of file and `later` is never reached.
#
# ac1_outcome <output> <exit>   Classifies a run as exactly one of:
#   ran        `later` ran and passed, and both gates were counted, exit 0
#   refused    the refusal line names `later`, no pass line, exit 1
#   false-cert "All required gates passed" and `later` absent: the defect
#   other      anything else, which is not an acceptable outcome either
ac1_outcome() {
  if [ "$2" = 0 ] \
     && grep -Fxq '=== gate: later (required) ===' <<<"$1" \
     && grep -q '^PASS         later (' <<<"$1" \
     && grep -Fxq 'All required gates passed (2 ran, 0 unconfigured, 0 known).' <<<"$1"; then
    printf 'ran'
  elif [ "$2" = 1 ] \
     && grep -Fxq -- "$(refusal later)" <<<"$1" \
     && ! grep -Fq 'All required gates passed' <<<"$1"; then
    printf 'refused'
  elif grep -Fq 'All required gates passed' <<<"$1" \
     && ! grep -Fq 'later' <<<"$1"; then
    printf 'false-cert'
  else
    printf 'other'
  fi
}

# Each case writes the manifest afresh: the first gate destroys it.
write_conf "$FIX" <<'EOF'
gate | first | required | . | printf 'BOOTSTRAPPED=yes\n' > .claude/harness/project.conf; printf 'Tests 1 passed\n'
gate | later | required | . | printf 'Tests 2 passed\n'
EOF
out="$(gates_isolated)"; rc=$?
outcome="$(ac1_outcome "$out" "$rc")"
case "$outcome" in
  ran|refused) _ok "the gate after an in-place rewrite of project.conf either runs or is refused by name" ;;
  *) _bad "the gate after an in-place rewrite of project.conf either runs or is refused by name" \
       "outcome: $outcome (exit $rc); wanted 'ran' or 'refused'
$out" ;;
esac
case "$outcome" in
  false-cert) _bad "and the run never certifies itself with that gate absent from the output" \
       "certified a pass (exit $rc) without mentioning 'later':
$out" ;;
  *) _ok "and the run never certifies itself with that gate absent from the output" ;;
esac

write_conf "$FIX" <<'EOF'
gate | first | required | . | printf 'BOOTSTRAPPED=yes\n' > .claude/harness/project.conf; printf 'Tests 1 passed\n'
gate | later | required | . | exit 1
EOF
out="$(gates_isolated)"; rc=$?
assert_eq "a failing required gate after an in-place rewrite fails the run" "1" "$rc"
if grep -q '^FAIL         later (' <<<"$out"; then
  _ok "and the summary has a FAIL line for it, its own or the refusal"
else
  _bad "and the summary has a FAIL line for it, its own or the refusal" \
    "expected a line starting: FAIL         later (
actual:   $out"
fi
assert_lacks "and the run is not certified" "All required gates passed" "$out"

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-7: GATES_FAULT_LOSE loses exactly the gates it names, and says so before any gate runs"

# Release 93: the variable is ignored and all three gates run.
SEAM_CONF="gate | a | required | . | printf 'Tests 1 passed\n'
gate | b | required | . | printf 'Tests 1 passed\n'
gate | c | required | . | printf 'Tests 1 passed\n'"

printf '%s\n' "$SEAM_CONF" | write_conf "$FIX"
out_b="$(seam b)"; rc_b=$?
assert_lacks    "a gate the seam names never runs"        "=== gate: b (" "$out_b"
assert_contains "the gate before it still runs"           "=== gate: a (required) ===" "$out_b"
assert_contains "and so does the gate after it"           "=== gate: c (required) ===" "$out_b"

note_no="$(first_line_no 'note: GATES_FAULT_LOSE is set' "$out_b")"
banner_no="$(first_line_no '=== gate:' "$out_b")"
if [ -n "$note_no" ]; then
  _ok "the seam announces itself with a note: GATES_FAULT_LOSE is set line"
  note_line="$(printf '%s\n' "$out_b" | sed -n "${note_no}p")"
  if grep -Fxq b <<<"$(tr -c 'A-Za-z0-9_.-' '\n' <<<"$note_line")"; then
    _ok "and the note names the gate it will lose"
  else
    _bad "and the note names the gate it will lose" "note line does not name 'b': $note_line"
  fi
else
  _bad "the seam announces itself with a note: GATES_FAULT_LOSE is set line" \
    "no line starts 'note: GATES_FAULT_LOSE is set':
$out_b"
  _bad "and the note names the gate it will lose" "there is no note line to name it"
fi
if [ -n "$note_no" ] && [ -n "$banner_no" ] && [ "$note_no" -lt "$banner_no" ]; then
  _ok "and the note comes before the first gate banner"
else
  _bad "and the note comes before the first gate banner" \
    "note at line '${note_no:-none}', first '=== gate:' at line '${banner_no:-none}'"
fi

out_ac="$(seam 'a c')"; rc_ac=$?
assert_lacks    "a seam naming two gates loses the first" "=== gate: a (" "$out_ac"
assert_lacks    "and the second"                          "=== gate: c (" "$out_ac"
assert_contains "and runs the one it does not name"       "=== gate: b (required) ===" "$out_ac"

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-8: a lost gate refuses the run"

# On the two runs above. Release 93: all three gates run, exit 0.
assert_line  "(a) a lost gate gets its own refusal line"   "$(refusal b)" "$out_b"
assert_line  "(a) and the refusals are counted"            "$(lost_count 1)" "$out_b"
assert_lacks "(a) and the run is not certified" "All required gates passed" "$out_b"
assert_eq    "(a) and exits 1" "1" "$rc_b"

assert_line  "(b) two lost gates: the first is refused"    "$(refusal a)" "$out_ac"
assert_line  "(b) and the second"                          "$(refusal c)" "$out_ac"
a_no="$(first_line_no "$(refusal a)" "$out_ac")"
c_no="$(first_line_no "$(refusal c)" "$out_ac")"
if [ -n "$a_no" ] && [ -n "$c_no" ] && [ "$a_no" -lt "$c_no" ]; then
  _ok "(b) in manifest order"
else
  _bad "(b) in manifest order" "refusal of a at line '${a_no:-none}', of c at line '${c_no:-none}'"
fi
assert_line  "(b) and both are counted"                    "$(lost_count 2)" "$out_ac"
assert_lacks "(b) and the run is not certified" "All required gates passed" "$out_ac"
assert_eq    "(b) and exits 1" "1" "$rc_ac"

# (c) A lost OPTIONAL gate is not a WARN: losing it means the runner is broken.
printf '%s\n' "$SEAM_CONF" | sed 's/^gate | b | required |/gate | b | optional |/' | write_conf "$FIX"
out="$(seam b)"; rc=$?
assert_line  "(c) a lost optional gate is refused like a required one" "$(refusal b)" "$out"
assert_line  "(c) and counted"                              "$(lost_count 1)" "$out"
assert_lacks "(c) not merely warned about"                  "WARN         b" "$out"
assert_lacks "(c) and the run is not certified" "All required gates passed" "$out"
assert_eq    "(c) and exits 1" "1" "$rc"

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-9: the refusal reaches the story record and the stamp"

# Release 93: the record reads `result: pass (3 ran, ...)`. Upstream refuses to
# record off the story branch or while a gated file is untracked, hence the
# branch and the `git add -A`; the branch is switched back after.
printf '%s\n' "$SEAM_CONF" | write_conf "$FIX"
story "$FIX" T-47 GATES </dev/null
git -C "$FIX" checkout -q -b story/T-47-fixture 2>/dev/null
git -C "$FIX" add -A 2>/dev/null
rm -f "$FIX/.claude/state/last-gate-run"
out="$(seam b --story T-47)"
rec="$(awk '/^## Gate results/ { f = 1; next } f && /^## / { exit } f' "$FIX/docs/backlog/stories/T-47.md")"
if grep -Eq '^ *result: fail( |$)' <<<"$rec"; then
  _ok "a full run that lost a gate records result: fail"
else
  _bad "a full run that lost a gate records result: fail" "## Gate results:
$rec
run output:
$out"
fi
assert_line "and the record carries the refusal line" "    $(refusal b)" "$rec"
assert_line "and the stamp says RESULT=fail" "RESULT=fail" \
  "$(cat "$FIX/.claude/state/last-gate-run" 2>/dev/null)"
git -C "$FIX" checkout -q - 2>/dev/null

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-10: --fast, --required and --gate refuse a lost gate, and never blame one they excluded"

# `s` is slow, `o` optional. A lost line was never reached to be excluded, so a
# filter that would have excluded it does not excuse it. Release 93: all four
# runs exit 0.
AC10_CONF="$SEAM_CONF
gate | s | required | . | printf 'Tests 1 passed\n'
slow | s | fixture: stands in for a release build
gate | o | optional | . | printf 'Tests 1 passed\n'"

printf '%s\n' "$AC10_CONF" | write_conf "$FIX"
out="$(seam b --fast)"; rc=$?
assert_line    "(a) --fast: the lost gate is refused"            "$(refusal b)" "$out"
assert_line    "(a) --fast: the slow gate is reported skipped"   "--fast skipped: s" "$out"
assert_no_line "(a) --fast: and is not blamed as lost"           "$(refusal s)" "$out"
assert_line    "(a) --fast: exactly one gate is counted lost"    "$(lost_count 1)" "$out"
assert_eq      "(a) --fast: and exits 1" "1" "$rc"

printf '%s\n' "$AC10_CONF" | write_conf "$FIX"
out="$(seam b --required)"; rc=$?
assert_line    "(b) --required: the lost gate is refused"        "$(refusal b)" "$out"
assert_no_line "(b) --required: the optional gate it left out is not blamed" "$(refusal o)" "$out"
assert_line    "(b) --required: exactly one gate is counted lost" "$(lost_count 1)" "$out"
assert_eq      "(b) --required: and exits 1" "1" "$rc"

printf '%s\n' "$AC10_CONF" | write_conf "$FIX"
out="$(seam b --gate b)"; rc=$?
assert_line    "(c) --gate b: the lost gate it selected is refused" "$(refusal b)" "$out"
assert_lacks   "(c) --gate b: b is declared, so it is not a typo" "no gate named" "$out"
assert_line    "(c) --gate b: exactly one gate is counted lost"   "$(lost_count 1)" "$out"
assert_eq      "(c) --gate b: and exits 1, not 2" "1" "$rc"

printf '%s\n' "$AC10_CONF" | write_conf "$FIX"
out="$(seam b --gate a)"; rc=$?
assert_line    "(d) --gate a: a lost gate it did not select is still refused" "$(refusal b)" "$out"
assert_line    "(d) --gate a: exactly one gate is counted lost"   "$(lost_count 1)" "$out"
assert_eq      "(d) --gate a: and exits 1" "1" "$rc"

# ---------------------------------------------------------------------------
describe "HARNESS-052 AC-11: no false refusal - every disposition counts as accounted for"

# The negative controls on the invariant: it runs on every CI job, so a false
# refusal would block every PR. Each summary is pinned whole - every status
# line and the verdict, timings masked - because a healthy run must stay
# byte-for-byte what it is today. These pass on arrival (there is no invariant
# yet); each earns its red in GATES by a mutation that makes the invariant
# forget dispositions (the story's DV-2).
#
# verdict_of <output>   The status lines, the --fast skip line and the verdict,
# with each `(<n>s` masked to `(Ns`.
verdict_of() {
  printf '%s\n' "$1" | sed -n -E \
    -e '/^(PASS|FAIL|WARN|KNOWN|UNCONFIGURED) /{s/\(([0-9]+)s/(Ns/;p;}' \
    -e '/^--fast skipped/p' \
    -e '/^All required gates passed/p' \
    -e '/^[0-9]+ required gate\(s\) failed\.$/p'
}

HEALTHY_CONF="gate     | a | required | . | printf 'Tests 3 passed\n'
evidence | a | Tests [1-9]
gate     | k | optional | . | exit 1
waiver   | k | fixture: known red
gate     | w | optional | . | exit 1
gate     | u | optional | . |
gate     | s | required | . | printf 'Tests 2 passed\n'
evidence | s | Tests [1-9]
slow     | s | fixture: stands in for a release build"

# ac6_row <label> <expected verdict_of> <expected exit> [gates.sh args...]
ac6_row() {
  local label="$1" want="$2" want_rc="$3" o r
  shift 3
  printf '%s\n' "$HEALTHY_CONF" | write_conf "$FIX"
  o="$( ( cd "$FIX" && bash scripts/gates.sh "$@" 2>&1 ) </dev/null )"; r=$?
  assert_eq    "$label: the summary is exactly what it was" "$want" "$(verdict_of "$o")"
  assert_eq    "$label: and so is the exit code" "$want_rc" "$r"
  assert_lacks "$label: and nothing is called unaccounted for" "never accounted for" "$o"
}

ac6_row "healthy, full run" "PASS         a (Ns, observed 3)
KNOWN        k (Ns, exit 1; fixture: known red) -> .claude/state/gate-logs/k.log
WARN         w (Ns, exit 1, optional) -> .claude/state/gate-logs/w.log
UNCONFIGURED u
PASS         s (Ns, observed 2)
All required gates passed (4 ran, 1 unconfigured, 1 known)." 0

ac6_row "healthy, --fast" "PASS         a (Ns, observed 3)
KNOWN        k (Ns, exit 1; fixture: known red) -> .claude/state/gate-logs/k.log
WARN         w (Ns, exit 1, optional) -> .claude/state/gate-logs/w.log
UNCONFIGURED u
--fast skipped: s
All required gates passed (3 ran, 1 unconfigured, 1 known)." 0 --fast

ac6_row "healthy, --required" "PASS         a (Ns, observed 3)
PASS         s (Ns, observed 2)
All required gates passed (2 ran, 0 unconfigured, 0 known)." 0 --required

ac6_row "healthy, --gate w" "WARN         w (Ns, exit 1, optional) -> .claude/state/gate-logs/w.log
All required gates passed (1 ran, 0 unconfigured, 0 known)." 0 --gate w

ac6_row "healthy, --gate u" "UNCONFIGURED u
All required gates passed (0 ran, 1 unconfigured, 0 known)." 0 --gate u

# One gate per refusal that happens before a gate runs, plus one that runs.
# (Downstream's e_nocnt row is dropped: upstream has no no-count line; that is
# HARNESS-055.)
write_conf "$FIX" <<'EOF'
gate      | e_slow  | required | . | printf 'Tests 1 passed\n'
slow      | e_slow  |
gate      | e_floor | required | . | printf 'Tests 1 passed\n'
evidence  | e_floor | Tests [1-9]
floor     | e_floor | abc
gate      | e_cif   | required | . | printf 'Tests 1 passed\n'
evidence  | e_cif   | Tests [1-9]
ci-factor | e_cif   | 3.4
gate      | e_waive | required | . | printf 'Tests 1 passed\n'
waiver    | e_waive | fixture: a bypass
gate      | e_nocmd | required | . |
gate      | ok      | required | . | printf 'Tests 1 passed\n'
evidence  | ok      | Tests [1-9]
EOF
out="$( ( cd "$FIX" && bash scripts/gates.sh 2>&1 ) </dev/null )"; rc=$?
assert_eq "manifest errors: the summary is exactly what it was" \
"FAIL         e_slow (marked slow with no reason in project.conf)
FAIL         e_floor (floor 'abc' is not a number)
FAIL         e_cif (ci-factor has no source; say which CI run it was measured from)
FAIL         e_waive (has a waiver but is required; waivers are for optional gates only)
FAIL         e_nocmd (required gate has no command in project.conf)
PASS         ok (Ns, observed 1)
5 required gate(s) failed." "$(verdict_of "$out")"
assert_eq    "manifest errors: and so is the exit code" "1" "$rc"
assert_lacks "manifest errors: and nothing is called unaccounted for" "never accounted for" "$out"

# ============================================================================
# HARNESS-069: a failing log with an unexplained signature outlives later failures
# ============================================================================
#
# Provenance: ported from manga-translator MT-053, where it was written against
# a vendored release-82 harness. Re-measured on release 95; the names below are
# this story's.
#
# HARNESS-027 keeps the LAST non-passing run of a gate in <id>.failed.log, and
# the next ordinary failure replaces it. `keep-when | <id> | <extended regex>`
# keeps a non-passing run whose cleaned log matches it in
# .claude/state/gate-logs/kept/<id>.<seq6>.<YYYYMMDDTHHMMSSZ>.log, at most 5 per
# gate id, lowest <seq> evicted first, and changes nothing that is judged.
#
# Its own fixture, F69, so that nothing here has to clear another block's state:
#   - project.conf and .claude/state/ are in F69's .git/info/exclude, so the
#     manifest is read but neither tracked nor gated. AC-10 compares a run whose
#     keep-when line matches with one whose line does not; with the conf
#     tracked, the two `tree:` and `commit:` lines would differ because the
#     MANIFEST differs, and the comparison would need a second mask. Excluded,
#     every recorded line but `run:` is a fact about the same tree.
#   - every scenario uses its own gate ids, so kept/ is never cleared and no
#     test removes a path held in a variable.
#   - a gate's output and exit status come from .claude/state/h69/<id>.out and
#     <id>.rc (feed69), so changing a case is a write, never an rm.
# Needles are whole lines (count_line) or anchored; the kept file's name is
# matched by grep -E, never awk (mawk has no intervals, HARNESS-025).

describe "HARNESS-069 AC-1..AC-11  a failing log with an unexplained signature outlives later failures"

F69="$(make_project_fixture)"
trap '[ -n "$H30_SLEEP" ] && kill "$H30_SLEEP" 2>/dev/null; rm -rf "$FIX" "$H30W" "$F69"' EXIT
mkdir -p "$F69/.git/info"
printf '%s\n' .claude/harness/project.conf .claude/state/ >> "$F69/.git/info/exclude"
story "$F69" T-1 GATES </dev/null
git -C "$F69" add -A >/dev/null 2>&1
git -C "$F69" -c user.email=t@t -c user.name=t commit -qm "HARNESS-069 fixture story" >/dev/null 2>&1
git -C "$F69" checkout -q -B story/T-1-fixture 2>/dev/null
set_phase "$F69" ""
L69="$F69/.claude/state/gate-logs"
K69="$L69/kept"
M69="$F69/.claude/state/h69"
mkdir -p "$M69"

# stdout only: AC-9 is a statement about stdout.
g69() { ( cd "$F69" && bash scripts/gates.sh "$@" 2>/dev/null ); }
# feed69 <id> <exit status> <output, printf %b>
feed69() { printf '%b' "$3" > "$M69/$1.out"; printf '%s' "$2" > "$M69/$1.rc"; }
# names69 <dir> [id]   File names in <dir>, C-sorted, space-separated. With <id>,
# only that gate's kept files, by the Contract's anchored name: a glob of
# `<id>*` would take coverage-core's files for coverage's.
names69() {
  local all; all="$(ls -1A "$1" 2>/dev/null | tr -d '\r')"
  if [ -n "${2:-}" ]; then
    all="$(printf '%s\n' "$all" | grep -E -- "^$2\\.[0-9]{6}\\.[0-9]{8}T[0-9]{6}Z\\.log\$")"
  fi
  printf '%s\n' "$all" | LC_ALL=C sort | tr '\n' ' ' | sed -e 's/^ *//' -e 's/ *$//'
}
kept69()   { names69 "$K69" "$1"; }
kn69()     { printf '%s' "$(kept69 "$1")" | awk '{ n += NF } END { print n + 0 }'; }
seqs69()   { kept69 "$1" | tr ' ' '\n' | cut -d. -f2 | tr '\n' ' ' | sed -e 's/ *$//'; }
last69()   { kept69 "$1" | tr ' ' '\n' | tail -n 1; }
# prefix69 <prefix>   How many entries of kept/, of ANY name, start with it.
prefix69() { names69 "$K69" | tr ' ' '\n' | awk -v p="$1" 'index($0, p) == 1 { n++ } END { print n + 0 }'; }
hdr69()    { [ -n "$1" ] && sed -n "$2p" "$K69/$1" 2>/dev/null | tr -d '\r'; }
# body69 <kept file> <id>   AC-1: after the eight header lines, <id>.log byte for byte.
body69() {
  [ -n "$1" ] && [ -f "$K69/$1" ] || { printf 'no kept file [%s]' "$1"; return 0; }
  if tail -n +9 "$K69/$1" | cmp -s - "$L69/$2.log"; then printf identical; else printf differs; fi
}
# sig69 <kept file> <regex>   The one stdout line AC-9 specifies.
sig69() { printf 'signature log kept: .claude/state/gate-logs/kept/%s (matched: %s)' "$1" "$2"; }
# snap69 <name> / same69 <name> [id]   A copy of kept/ now; later, whether
# kept/ (or one gate's part of it) is the same set of names with the same bytes.
snap69() { mkdir -p "$M69/snap.$1"; [ ! -d "$K69" ] || cp -R "$K69/." "$M69/snap.$1/"; }
same69() {
  local a b f
  a="$(names69 "$M69/snap.$1" "${2:-}")"; b="$(names69 "$K69" "${2:-}")"
  [ "$a" = "$b" ] || { printf 'kept/ changed: before [%s] after [%s]' "$a" "$b"; return 0; }
  for f in $a; do cmp -s "$M69/snap.$1/$f" "$K69/$f" || { printf 'kept/%s changed' "$f"; return 0; }; done
  printf unchanged
}
# in69 <kept file> <exact line>   Whole lines of a kept file equal to it.
in69() {
  [ -n "$1" ] && [ -f "$K69/$1" ] || { printf 'no kept file [%s]' "$1"; return 0; }
  count_line "$2" "$(tr -d '\r' < "$K69/$1")"
}
# fhdr69 <id> <n>   Line <n> of HARNESS-027's <id>.failed.log from the same run.
fhdr69() { sed -n "$2p" "$L69/$1.failed.log" 2>/dev/null | tr -d '\r'; }
t69()    { ( cd "$F69" && CLAUDE_PROJECT_DIR="$F69" bash -c '. .claude/hooks/lib.sh; gate_tree_hash' 2>/dev/null ); }
c69() {
  local c; c="$(git -C "$F69" rev-parse --short HEAD)"
  [ -z "$(git -C "$F69" status --porcelain -- . ':!docs' 2>/dev/null)" ] \
    || c="$c (working tree had uncommitted changes)"
  printf '%s' "$c"
}
# hline69 <id> <text>   1-based line of gate <id>'s `=== gate:` header, or empty.
# A here-string, not printf | grep -m1: no writer for an early exit to kill.
hline69() { grep -m1 -n -- "^=== gate: $1 " <<<"$2" | cut -d: -f1; }
R69_RUN='^# run:     [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'

write_conf "$F69" <<'EOF'
gate      | sig   | required | . | cat .claude/state/h69/sig.out; exit "$(cat .claude/state/h69/sig.rc)"
evidence  | sig   | -
gate      | after | optional | . | printf 'after ran\n'
evidence  | after | -
keep-when | sig   | Windows fatal exception
keep-when | sig   | Unknown C\+\+ exception
EOF

# --- AC-1 / AC-2 / AC-9: a failing run whose log carries a signature ----------
feed69 sig 1 'cv2 imported\nWindows fatal exception: code 0x8007000e\nboom 1\n'
out="$(g69)"
assert_eq "AC-1 control: sig failed, required" 1 "$(count_re '^FAIL +sig \(' "$out")"
assert_eq "AC-1 control: the optional gate after it ran" 1 "$(count_re '^=== gate: after ' "$out")"
r1="$(kept69 sig)"
assert_eq "AC-1: a failing run whose log matches a keep-when line leaves exactly one kept file for that gate" 1 "$(kn69 sig)"
_run="$(fhdr69 sig 3)"; _run="${_run#'# run:     '}"
_stamp="$(printf '%s' "$_run" | tr -d ':-')"
assert_eq "AC-1 control: HARNESS-027's failed.log gives a start time to derive the stamp from" 1 \
  "$(printf '%s\n' "$_stamp" | grep -cE '^[0-9]{8}T[0-9]{6}Z$')"
assert_eq "AC-1: the kept file is kept/sig.000001.<the run's start, without - and :>.log" "sig.000001.$_stamp.log" "$r1"
assert_eq "AC-2 header 1 names the gate and why it was kept" \
  "# gates.sh: failing run of gate 'sig' kept for a signature" "$(hdr69 "$r1" 1)"
assert_eq "AC-2 header 2 is the outcome" "# outcome: fail" "$(hdr69 "$r1" 2)"
assert_eq "AC-2 header 2 is the outcome line of the same run's sig.failed.log" "$(fhdr69 sig 2)" "$(hdr69 "$r1" 2)"
assert_eq "AC-2 header 3 is a UTC time, YYYY-MM-DDTHH:MM:SSZ" 1 "$(hdr69 "$r1" 3 | grep -cE -- "$R69_RUN")"
assert_eq "AC-2 header 3 is the run line of the same run's sig.failed.log" "$(fhdr69 sig 3)" "$(hdr69 "$r1" 3)"
assert_eq "AC-2 header 4 is the commit line of the same run's sig.failed.log" "$(fhdr69 sig 4)" "$(hdr69 "$r1" 4)"
assert_eq "AC-2 header 4 is the short HEAD, with the note only when the tree is dirty" "# commit:  $(c69)" "$(hdr69 "$r1" 4)"
assert_eq "AC-2 header 5 is the tree line of the same run's sig.failed.log" "$(fhdr69 sig 5)" "$(hdr69 "$r1" 5)"
assert_eq "AC-2 header 5 is gate_tree_hash, computed independently" "# tree:    $(t69)" "$(hdr69 "$r1" 5)"
assert_eq "AC-2 header 6 is the keep-when regex that matched, verbatim" "# matched: Windows fatal exception" "$(hdr69 "$r1" 6)"
assert_eq "AC-2 header 7 is the whole first log line it matched" \
  "# line:    Windows fatal exception: code 0x8007000e" "$(hdr69 "$r1" 7)"
assert_eq "AC-2 header 8 closes the header" "# ----" "$(hdr69 "$r1" 8)"
assert_eq "AC-1: after eight header lines, the run's sig.log byte for byte" identical "$(body69 "$r1" sig)"
assert_eq "AC-1: and it is this run's log" 1 "$(in69 "$r1" 'boom 1')"
assert_eq "AC-3: a run that keeps for a signature still writes HARNESS-027's sig.failed.log" \
  "# gates.sh: last failing run of gate 'sig'" "$(fhdr69 sig 1)"
assert_eq "AC-3: and still prints HARNESS-027's kept line, once" 1 "$(count_line "$(kept_line sig)" "$out")"
assert_eq "AC-9: the signature line is printed exactly once, naming the file and the regex" 1 \
  "$(count_line "$(sig69 "$r1" 'Windows fatal exception')" "$out")"
assert_eq "AC-9: and no other signature line is printed" 1 "$(count_re '^signature log kept:' "$out")"
_hs="$(hline69 sig "$out")"; _ha="$(hline69 after "$out")"
_fk="$(lineno "$(kept_line sig)" "$out")"; _sk="$(lineno "$(sig69 "$r1" 'Windows fatal exception')" "$out")"
assert_eq "AC-9: it comes after sig's header and after HARNESS-027's failing log kept line" yes \
  "$([ -n "$_hs" ] && [ -n "$_fk" ] && [ -n "$_sk" ] && [ "$_hs" -lt "$_fk" ] && [ "$_fk" -lt "$_sk" ] && printf yes || printf "no (header ${_hs:-?}, failing log kept ${_fk:-absent}, signature ${_sk:-absent})")"
assert_eq "AC-9: and before the next gate's header" yes \
  "$([ -n "$_sk" ] && [ -n "$_ha" ] && [ "$_sk" -lt "$_ha" ] && printf yes || printf "no (signature ${_sk:-absent}, next header ${_ha:-?})")"
[ -z "$r1" ] || cp "$K69/$r1" "$M69/r1.copy"

# --- AC-2: two keep-when lines match; the first in MANIFEST order is named ----
# The log's first matching line is the C++ one, so a "first line of the log"
# reading names the wrong regex.
feed69 sig 1 'cv2.error: Unknown C++ exception from OpenCV code\nWindows fatal exception: access violation\nboom 2\n'
out="$(g69 --gate sig)"
r2="$(last69 sig)"
assert_eq "AC-2: a run matching two keep-when lines still produces exactly one kept file" 2 "$(kn69 sig)"
assert_eq "AC-2: the next kept file takes <seq> 000002" "000001 000002" "$(seqs69 sig)"
assert_eq "AC-2: the header names the first keep-when line in manifest order" \
  "# matched: Windows fatal exception" "$(hdr69 "$r2" 6)"
assert_eq "AC-2: and the first log line THAT regex matched" \
  "# line:    Windows fatal exception: access violation" "$(hdr69 "$r2" 7)"
assert_eq "AC-2: header 3 is the same run's failed.log run line" "$(fhdr69 sig 3)" "$(hdr69 "$r2" 3)"
assert_eq "AC-1: the second kept file is the second run's log, byte for byte" identical "$(body69 "$r2" sig)"
assert_eq "AC-9: one signature line, naming the manifest-first regex" 1 \
  "$(count_line "$(sig69 "$r2" 'Windows fatal exception')" "$out")"
assert_eq "AC-9: and only one" 1 "$(count_re '^signature log kept:' "$out")"
assert_eq "AC-1: a later failing run WITH a signature leaves the first kept file byte-identical" identical \
  "$(same "$M69/r1.copy" "$K69/$r1")"

# --- AC-2: the escaped regex is named verbatim -------------------------------
feed69 sig 1 'cv2.error: Unknown C++ exception from OpenCV code\nboom 3\n'
out="$(g69 --gate sig)"
r3="$(last69 sig)"
assert_eq "AC-2: a log matching only the second keep-when line is kept" 3 "$(kn69 sig)"
assert_eq "AC-2: its header names that regex verbatim, backslashes included" \
  "# matched: Unknown C\\+\\+ exception" "$(hdr69 "$r3" 6)"
assert_eq "AC-2: and the whole line it matched" \
  "# line:    cv2.error: Unknown C++ exception from OpenCV code" "$(hdr69 "$r3" 7)"
assert_eq "AC-9: the signature line carries the regex verbatim" 1 \
  "$(count_line "$(sig69 "$r3" 'Unknown C\+\+ exception')" "$out")"

# --- AC-1 / AC-3: a later failing run with NO signature ----------------------
# The lower-case line is a decoy: matching is grep -E, case-sensitive (AC-6).
snap69 r4
feed69 sig 1 'boom 4\nwindows fatal exception, in lower case\n'
out="$(g69 --gate sig)"
assert_eq "AC-3 control: sig failed again" 1 "$(count_re '^FAIL +sig \(' "$out")"
assert_eq "AC-3 control: the snapshot holds the three kept sig files" 3 \
  "$(names69 "$M69/snap.r4" sig | awk '{ print NF }')"
assert_eq "AC-3/AC-6: a failing run matching no signature (a lower-case decoy only) leaves kept/ unchanged, byte for byte" unchanged "$(same69 r4)"
assert_eq "AC-1: a later failing run WITHOUT a signature leaves the first kept file byte-identical" identical \
  "$(same "$M69/r1.copy" "$K69/$r1")"
assert_eq "AC-3: and prints no signature line" 0 "$(count_re '^signature log kept:' "$out")"
assert_eq "AC-3: HARNESS-027's failing log kept line is printed, once" 1 "$(count_line "$(kept_line sig)" "$out")"
assert_eq "AC-3: HARNESS-027's sig.failed.log header is unchanged" "# gates.sh: last failing run of gate 'sig'" "$(fhdr69 sig 1)"
assert_eq "AC-3: HARNESS-027's sig.failed.log holds this run after its six header lines" identical \
  "$(tail -n +7 "$L69/sig.failed.log" | cmp -s - "$L69/sig.log" && printf identical || printf differs)"

# --- AC-1: every outcome that is not a pass ----------------------------------
# "Did not pass" is fail, noevidence, environment or blocked (HARNESS-027's
# terms). Each of the last three is reached here with a signature in the log;
# each must be kept, its header naming its own outcome.
write_conf "$F69" <<'EOF'
gate         | nev | required | . | printf 'Windows fatal exception: no evidence\nnothing counted\n'
evidence     | nev | Tests +[1-9][0-9]* passed
gate         | blk | required | . | printf 'could not execute process: denied\nWindows fatal exception: blocked\n'; exit 1
evidence     | blk | -
blocked-when | blk | could not execute process
gate         | env | required | . | printf 'Tests 2 passed\n40 skipped\nWindows fatal exception: environment\n'
evidence     | env | Tests +[1-9][0-9]* passed
floor        | env | 10
skipped-when | env | [1-9][0-9]* skipped
keep-when    | nev | Windows fatal exception
keep-when    | blk | Windows fatal exception
keep-when    | env | Windows fatal exception
EOF
out="$(g69)"
assert_eq "AC-1 control: nev is FAILed for no evidence" 1 "$(count_re '^FAIL +nev \(.*no evidence of work' "$out")"
assert_eq "AC-1 control: blk is BLOCKED" 1 "$(count_re '^BLOCKED +blk \(' "$out")"
assert_eq "AC-1 control: env is BLOCKED by its skipped-when line" 1 "$(count_re '^BLOCKED +env \(.*environment did not supply it' "$out")"
for _o in nev:noevidence blk:blocked env:environment; do
  _g="${_o%%:*}"; _w="${_o#*:}"
  _r="$(kept69 "$_g")"
  assert_eq "AC-1: a run of $_g whose outcome is $_w and whose log matches is kept, once" 1 "$(kn69 "$_g")"
  assert_eq "AC-2: its header says outcome $_w" "# outcome: $_w" "$(hdr69 "$_r" 2)"
  assert_eq "AC-2: the same outcome line as $_g.failed.log" "$(fhdr69 "$_g" 2)" "$(hdr69 "$_r" 2)"
  assert_eq "AC-1: $_g's kept file is its log, byte for byte" identical "$(body69 "$_r" "$_g")"
  assert_eq "AC-9: one signature line for $_g" 1 "$(count_line "$(sig69 "$_r" 'Windows fatal exception')" "$out")"
done

# --- AC-4: a pass, even one whose log carries a signature --------------------
write_conf "$F69" <<'EOF'
gate      | sig   | required | . | cat .claude/state/h69/sig.out; exit "$(cat .claude/state/h69/sig.rc)"
evidence  | sig   | -
gate      | after | optional | . | printf 'after ran\n'
evidence  | after | -
keep-when | sig   | Windows fatal exception
keep-when | sig   | Unknown C\+\+ exception
EOF
snap69 r5
feed69 sig 0 'Windows fatal exception: code 0x8007000e\nall passed\n'
out="$(g69)"
assert_eq "AC-4 control: sig passed" 1 "$(count_re '^PASS +sig \(' "$out")"
assert_eq "AC-4 control: and its log holds the signature line" 1 \
  "$(count_line 'Windows fatal exception: code 0x8007000e' "$(tr -d '\r' < "$L69/sig.log")")"
assert_eq "AC-4: a pass whose log matches a signature leaves kept/ unchanged" unchanged "$(same69 r5)"
assert_eq "AC-4: and prints no signature line" 0 "$(count_re '^signature log kept:' "$out")"

# --- AC-4: gates a run does not execute --------------------------------------
feed69 sig 1 'Windows fatal exception: never executed\n'
out="$(g69 --gate after)"
assert_eq "AC-4 control: --gate after does not run sig" 0 "$(count_re '^=== gate: sig ' "$out")"
assert_eq "AC-4: --gate after leaves kept/ unchanged" unchanged "$(same69 r5)"
assert_eq "AC-4: --gate after prints no signature line" 0 "$(count_re '^signature log kept:' "$out")"
out="$(g69 --list)"
assert_eq "AC-4 control: --list lists sig" 1 "$(count_re '^sig +required ' "$out")"
assert_eq "AC-4: --list leaves kept/ unchanged" unchanged "$(same69 r5)"
assert_eq "AC-4: --list prints no signature line" 0 "$(count_re '^signature log kept:' "$out")"
out="$(g69 --audit)"
assert_eq "AC-7 control: a well-formed keep-when manifest passes --audit" 1 "$(count_line 'Manifest audit passed.' "$out")"
assert_eq "AC-7 control: and no FAIL line names keep-when" 0 "$(count_re '^FAIL .*keep-when' "$out")"
assert_eq "AC-4: --audit leaves kept/ unchanged" unchanged "$(same69 r5)"
assert_eq "AC-4: --audit prints no signature line" 0 "$(count_re '^signature log kept:' "$out")"
write_conf "$F69" <<'EOF'
gate      | sig   | required | . | cat .claude/state/h69/sig.out; exit "$(cat .claude/state/h69/sig.rc)"
evidence  | sig   | -
gate      | after | optional | . | printf 'after ran\n'
evidence  | after | -
slow      | sig   | left out of --fast for HARNESS-069 AC-4
keep-when | sig   | Windows fatal exception
keep-when | sig   | Unknown C\+\+ exception
EOF
out="$(g69 --fast)"
assert_eq "AC-4 control: --fast leaves out the slow gate" 1 "$(count_line '--fast skipped: sig' "$out")"
assert_eq "AC-4: --fast leaves kept/ unchanged for the gate it left out" unchanged "$(same69 r5)"
assert_eq "AC-4: --fast prints no signature line" 0 "$(count_re '^signature log kept:' "$out")"

# --- AC-1: a signature on the first line of a large log ----------------------
# 20,000 filler lines after it, about 349 KB. `clean_log | grep -Em1` read as a
# STATUS loses this match under pipefail - sed dies of SIGPIPE once grep has
# left and the pipeline reports 141 - in 10 of 10 tries on the RED host, and at
# 6,000 lines too (story handoff). The decision has to rest on the captured line.
write_conf "$F69" <<'EOF'
gate      | big   | required | . | awk 'BEGIN { print "Windows fatal exception: code 0x8007000e"; for (i = 0; i < 20000; i++) print "filler line " i }'; exit 1
evidence  | big   | -
keep-when | big   | Windows fatal exception
EOF
g69 --gate big >/dev/null
rb="$(kept69 big)"
assert_eq "AC-1 control: big's log is the 20,001-line log, signature first" "20001 Windows fatal exception: code 0x8007000e" \
  "$(awk 'END { printf "%d ", NR }' "$L69/big.log")$(sed -n 1p "$L69/big.log" | tr -d '\r')"
assert_eq "AC-1: a 20,001-line log whose first line is the signature is kept" 1 "$(kn69 big)"
assert_eq "AC-1: after its header, the large log byte for byte" identical "$(body69 "$rb" big)"
assert_eq "AC-2: and its header names the line it matched" "# line:    Windows fatal exception: code 0x8007000e" "$(hdr69 "$rb" 7)"

# --- AC-6: the signatures come from keep-when lines and nowhere else ---------
write_conf "$F69" <<'EOF'
gate      | nokw  | required | . | cat .claude/state/h69/nokw.out; exit "$(cat .claude/state/h69/nokw.rc)"
evidence  | nokw  | -
gate      | zebra | required | . | cat .claude/state/h69/zebra.out; exit "$(cat .claude/state/h69/zebra.rc)"
evidence  | zebra | -
gate      | alt   | optional | . | cat .claude/state/h69/alt.out; exit "$(cat .claude/state/h69/alt.rc)"
evidence  | alt   | -
gate      | lc    | required | . | cat .claude/state/h69/lc.out; exit "$(cat .claude/state/h69/lc.rc)"
evidence  | lc    | -
keep-when | zebra | ZEBRA-[0-9]+
keep-when | alt   | (QUAGGA|OKAPI) [0-9]+
keep-when | lc    | ZEBRA-[0-9]+
EOF
feed69 nokw  1 'Windows fatal exception: code 0x8007000e\ncv2.error: Unknown C++ exception from OpenCV code\nZEBRA-9 in the wrong gate\n'
feed69 zebra 1 'escaped: ZEBRA-42\n'
feed69 alt   1 'an OKAPI 7 appeared\n'
feed69 lc    1 'escaped: zebra-42, and Zebra-42\n'
snap69 z
out="$(g69)"
assert_eq "AC-6 control: nokw failed" 1 "$(count_re '^FAIL +nokw \(' "$out")"
assert_eq "AC-6 control: lc failed" 1 "$(count_re '^FAIL +lc \(' "$out")"
assert_eq "AC-6: with no keep-when line, a log holding every signature this suite uses keeps nothing" 0 "$(kn69 nokw)"
assert_eq "AC-6: and no file of any name for nokw appears in kept/" 0 "$(prefix69 nokw)"
assert_eq "AC-6: another gate's keep-when line (zebra's ZEBRA-[0-9]+) never keeps nokw's log" unchanged "$(same69 z nokw)"
assert_eq "AC-6: a log differing from the regex only in case keeps nothing" 0 "$(kn69 lc)"
assert_eq "AC-6: and no file of any name for lc appears in kept/" 0 "$(prefix69 lc)"
rz="$(kept69 zebra)"
assert_eq "AC-6: an arbitrary regex, ZEBRA-[0-9]+, keeps a failing log that matches it" 1 "$(kn69 zebra)"
assert_eq "AC-6: naming it verbatim" "# matched: ZEBRA-[0-9]+" "$(hdr69 "$rz" 6)"
assert_eq "AC-6: and the line it matched" "# line:    escaped: ZEBRA-42" "$(hdr69 "$rz" 7)"
ra="$(kept69 alt)"
assert_eq "AC-6: a regex containing | survives the manifest whole, and keeps an optional gate's failure" 1 "$(kn69 alt)"
assert_eq "AC-6: named verbatim, alternation and all" "# matched: (QUAGGA|OKAPI) [0-9]+" "$(hdr69 "$ra" 6)"
assert_eq "AC-6: alt's kept file says outcome fail (printed WARN)" "# outcome: fail" "$(hdr69 "$ra" 2)"
assert_eq "AC-9: one signature line for zebra" 1 "$(count_line "$(sig69 "$rz" 'ZEBRA-[0-9]+')" "$out")"
assert_eq "AC-9: one signature line for alt" 1 "$(count_line "$(sig69 "$ra" '(QUAGGA|OKAPI) [0-9]+')" "$out")"
assert_eq "AC-9: and two in all" 2 "$(count_re '^signature log kept:' "$out")"
assert_eq "AC-6: the earlier kept files are untouched by other gates' runs" identical "$(same "$M69/r1.copy" "$K69/$r1")"
# No regex of its own: none of the signatures this suite feeds is in gates.sh.
# Control: the same reader finds each of them in this suite, so a 0 below is
# gates.sh's and not the reader's.
for _n in 'Windows fatal exception' 'Unknown C++ exception' 'Unknown C\+\+ exception' 'ZEBRA-' 'QUAGGA|OKAPI'; do
  assert_eq "AC-6 control: the reader finds '$_n' in this suite" yes \
    "$(grep -qF -- "$_n" "$TESTS_DIR/gates.test.sh" && printf yes || printf no)"
  assert_eq "AC-6: scripts/gates.sh does not contain '$_n'" 0 \
    "$(grep -cF -- "$_n" "$REPO_ROOT/scripts/gates.sh")"
done

# --- AC-5: at most 5 per gate id; the lowest <seq> goes; coverage-core is not coverage
write_conf "$F69" <<'EOF'
gate      | coverage      | required | . | cat .claude/state/h69/coverage.out; exit 1
evidence  | coverage      | -
gate      | coverage-core | required | . | cat .claude/state/h69/coverage-core.out; exit 1
evidence  | coverage-core | -
keep-when | coverage      | SIG
keep-when | coverage-core | SIG
EOF
for _i in 1 2 3 4 5; do
  feed69 coverage-core 1 "SIG core $_i\n"; g69 --gate coverage-core >/dev/null
done
assert_eq "AC-5 control: five kept coverage-core runs" "000001 000002 000003 000004 000005" "$(seqs69 coverage-core)"
# Taken BEFORE any coverage run: an eviction that reaches coverage-core can
# happen on the first coverage run, not only on the sixth.
snap69 core5
for _i in 1 2 3 4 5; do
  feed69 coverage 1 "SIG cov $_i\n"; g69 --gate coverage >/dev/null
done
assert_eq "AC-5 control: five kept coverage runs, and no coverage-core file taken for one" \
  "000001 000002 000003 000004 000005" "$(seqs69 coverage)"
assert_eq "AC-5 control: five coverage runs leave coverage-core's five alone" \
  "000001 000002 000003 000004 000005" "$(seqs69 coverage-core)"
snap69 cov5
_old="$(kept69 coverage | tr ' ' '\n' | sed -n 1p)"
feed69 coverage 1 'SIG cov 6\n'
out="$(g69 --gate coverage)"
r6="$(last69 coverage)"
assert_eq "AC-5: the sixth kept run leaves exactly 5 coverage files" 5 "$(kn69 coverage)"
assert_eq "AC-5: the one removed is the lowest <seq>, and the new one is 000006" \
  "000002 000003 000004 000005 000006" "$(seqs69 coverage)"
assert_eq "AC-5: the oldest run's output is gone from every file in kept/" 0 \
  "$(grep -rlxF -- 'SIG cov 1' "$K69" 2>/dev/null | awk 'END { print NR }')"
assert_eq "AC-5 control: the second run's output is still in exactly one file" 1 \
  "$(grep -rlxF -- 'SIG cov 2' "$K69" 2>/dev/null | awk 'END { print NR }')"
_left=0
for _f in $(kept69 coverage); do
  [ "$_f" = "$r6" ] && continue
  [ "$_f" != "$_old" ] && [ -f "$M69/snap.cov5/$_f" ] && cmp -s "$M69/snap.cov5/$_f" "$K69/$_f" && _left=$((_left + 1))
done
assert_eq "AC-5: the other four are byte-identical to before" 4 "$_left"
assert_eq "AC-5: the new one is the sixth run's log" 1 "$(in69 "$r6" 'SIG cov 6')"
assert_eq "AC-5: all five coverage-core files are unchanged, byte for byte" unchanged "$(same69 core5 coverage-core)"
assert_eq "AC-5: kept/ holds exactly 5 + 5 files whose names start with coverage" 10 "$(prefix69 coverage)"
assert_eq "AC-9: the eviction run prints one signature line, for the new file" 1 \
  "$(count_line "$(sig69 "$r6" SIG)" "$out")"
assert_eq "AC-9: eviction prints nothing else on stdout that names kept/" 1 "$(count_re 'kept/' "$out")"

# --- AC-10: a keep and an eviction change nothing that is judged -------------
# cap69 <name> [args]   A full run recorded into T-1 (--story); saves the exit
# status, the summary (from `--- gate summary ---` to the end), last-gate-run's
# RESULT= and FULL=, and the ## Gate results body with `run:` masked. `(<N>s` is
# normalised in the summary and the record as HARNESS-024's goldens do: a
# duration is a measurement of the run, not an output of the gate.
cap69() {
  local o r n="$1"; shift
  o="$(g69 --story T-1 "$@")"; r=$?
  printf '%s\n' "$r" > "$M69/$n.rc"
  printf '%s\n' "$o" | awk '/^--- gate summary ---$/ { on = 1 } on' \
    | sed -E 's/\(([0-9]+)s([,)])/(Ns\2/g' > "$M69/$n.summary"
  tr -d '\r' < "$F69/.claude/state/last-gate-run" | grep -E '^(RESULT|FULL)=' > "$M69/$n.stamp"
  tr -d '\r' < "$F69/docs/backlog/stories/T-1.md" \
    | awk '/^## Gate results/ { on = 1; next } on && /^## / { on = 0 } on' \
    | sed -E -e 's/^(    run:    ).*/\1<masked>/' -e 's/\(([0-9]+)s([,)])/(Ns\2/g' > "$M69/$n.record"
  printf '%s\n' "$o" > "$M69/$n.out"
}
conf10() {
  { printf '%s\n' \
      "gate      | g10  | required | . | printf 'boom 10\\n'; exit 1" \
      "evidence  | g10  | -" \
      "gate      | ok10 | optional | . | printf 'fine\\n'" \
      "evidence  | ok10 | -" \
      "keep-when | g10  | $1"; } | write_conf "$F69"
}
conf10 boom
cap69 a10
assert_eq "AC-10 control: the matching run kept a file" 1 "$(kn69 g10)"
assert_eq "AC-10 control: and printed its signature line" 1 "$(count_re '^signature log kept: ' "$(cat "$M69/a10.out")")"
assert_eq "AC-10 control: the run was recorded into T-1" 1 "$(count_line '    run:    <masked>' "$(cat "$M69/a10.record")")"
assert_eq "AC-10 control: the record carries g10's FAIL line" 1 "$(count_re '^    FAIL +g10 \(' "$(cat "$M69/a10.record")")"
assert_eq "AC-10 control: the summary was captured" 1 "$(count_line '--- gate summary ---' "$(cat "$M69/a10.summary")")"
assert_eq "AC-10 control: RESULT= and FULL= were captured" 2 "$(awk 'END { print NR }' "$M69/a10.stamp")"
conf10 'ZEBRA-[0-9]+'
cap69 b10
assert_eq "AC-10 control: the non-matching run kept nothing" 1 "$(kn69 g10)"
assert_eq "AC-10: exit status is the same whether or not a keep-when line matches" "$(cat "$M69/b10.rc")" "$(cat "$M69/a10.rc")"
assert_eq "AC-10: every summary line is the same whether or not a keep-when line matches" identical "$(same "$M69/b10.summary" "$M69/a10.summary")"
assert_eq "AC-10: last-gate-run's RESULT= and FULL= are the same whether or not a keep-when line matches" identical "$(same "$M69/b10.stamp" "$M69/a10.stamp")"
assert_eq "AC-10: ## Gate results (run: masked) is the same whether or not a keep-when line matches" identical "$(same "$M69/b10.record" "$M69/a10.record")"
conf10 boom
for _i in 2 3 4; do g69 --gate g10 >/dev/null; done
cap69 c10
assert_eq "AC-10 control: the fifth kept run evicts nothing" "000001 000002 000003 000004 000005" "$(seqs69 g10)"
cap69 d10
assert_eq "AC-10 control: the sixth kept run evicts the first" "000002 000003 000004 000005 000006" "$(seqs69 g10)"
assert_eq "AC-10: exit status is the same with and without an eviction" "$(cat "$M69/c10.rc")" "$(cat "$M69/d10.rc")"
assert_eq "AC-10: every summary line is the same with and without an eviction" identical "$(same "$M69/c10.summary" "$M69/d10.summary")"
assert_eq "AC-10: last-gate-run's RESULT= and FULL= are the same with and without an eviction" identical "$(same "$M69/c10.stamp" "$M69/d10.stamp")"
assert_eq "AC-10: ## Gate results (run: masked) is the same with and without an eviction" identical "$(same "$M69/c10.record" "$M69/d10.record")"

# --- AC-8: --list shows each keep-when line under its gate -------------------
write_conf "$F69" <<'EOF'
gate         | lst  | required | . | printf 'x\n'
evidence     | lst  | -
gate         | none | required | . | printf 'x\n'
evidence     | none | -
blocked-when | lst  | could not execute process
keep-when    | lst  | Windows fatal exception
keep-when    | lst  | (QUAGGA|OKAPI) [0-9]+
EOF
out="$(g69 --list)"
_kw1="$(printf '%-12s %-9s %-6s keep-when: %s' "" "" "" 'Windows fatal exception')"
_kw2="$(printf '%-12s %-9s %-6s keep-when: %s' "" "" "" '(QUAGGA|OKAPI) [0-9]+')"
_bw="$(printf '%-12s %-9s %-6s blocked-when: %s' "" "" "" 'could not execute process')"
_hl="$(printf '%s\n' "$out" | grep -m1 -n -- '^lst ' | cut -d: -f1)"
_hn="$(printf '%s\n' "$out" | grep -m1 -n -- '^none ' | cut -d: -f1)"
_l1="$(lineno "$_kw1" "$out")"; _l2="$(lineno "$_kw2" "$out")"
assert_eq "AC-8 control: --list prints lst's blocked-when line in its column layout" 1 "$(count_line "$_bw" "$out")"
assert_eq "AC-8: --list prints the first keep-when line once, in the blocked-when column layout" 1 "$(count_line "$_kw1" "$out")"
assert_eq "AC-8: and the second, | and all" 1 "$(count_line "$_kw2" "$out")"
assert_eq "AC-8: both under lst, in manifest order, before the next gate's line" yes \
  "$([ -n "$_hl" ] && [ -n "$_hn" ] && [ -n "$_l1" ] && [ -n "$_l2" ] && [ "$_hl" -lt "$_l1" ] && [ "$_l1" -lt "$_l2" ] && [ "$_l2" -lt "$_hn" ] && printf yes || printf "no (lst ${_hl:-?}, first ${_l1:-absent}, second ${_l2:-absent}, none ${_hn:-?})")"
assert_eq "AC-8: a gate with no keep-when line gets none: two keep-when lines in all" 2 "$(count_re '^ +keep-when: ' "$out")"

# --- AC-7: --audit refuses a malformed keep-when line ------------------------
write_conf "$F69" <<'EOF'
gate      | sig    | required | . | printf 'x\n'
evidence  | sig    | -
keep-when | nosuch | Windows fatal exception
EOF
out="$(g69 --audit)"; rc=$?
assert_eq "AC-7: --audit fails a keep-when line that names no configured gate, naming it" 1 \
  "$(count_line "$(printf 'FAIL %-12s a `keep-when` line names no configured gate' nosuch)" "$out")"
assert_eq "AC-7: counted as a manifest problem" 1 "$(count_line '1 manifest problem(s).' "$out")"
assert_eq "AC-7: and exits 1" 1 "$rc"
write_conf "$F69" <<'EOF'
gate      | sig    | required | . | printf 'x\n'
evidence  | sig    | -
keep-when | sig    |
EOF
out="$(g69 --audit)"; rc=$?
assert_eq "AC-7: --audit fails a keep-when line with no pattern" 1 \
  "$(count_line "$(printf 'FAIL %-12s a `keep-when` line has no pattern' sig)" "$out")"
assert_eq "AC-7: counted as a manifest problem" 1 "$(count_line '1 manifest problem(s).' "$out")"
assert_eq "AC-7: and exits 1" 1 "$rc"
# Control: the blocked-when check this wording copies, in the same fixture, so
# a miss above is the new kind's and not the reader's.
write_conf "$F69" <<'EOF'
gate         | sig    | required | . | printf 'x\n'
evidence     | sig    | -
blocked-when | nosuch | could not execute process
EOF
out="$(g69 --audit)"
assert_eq "AC-7 control: the blocked-when check this wording copies fires in this fixture" 1 \
  "$(count_line "$(printf 'FAIL %-12s a `blocked-when` line names no configured gate' nosuch)" "$out")"

# --- AC-7: the shipped manifest ---------------------------------------------
# Read from the real tree; --audit runs on a copy in F69, so nothing in this
# checkout is written. This repository ships no live keep-when line (PO-5):
# only the documented format and a commented example.
#
# HARNESS-070: the first three assertions below are about the TEMPLATE's text.
# In a project built on the harness project.conf is the project's own -
# refresh-harness.sh LEAVES it - and may carry live keep-when lines, which is
# what the feature is for. "Is this the template" is check-boundaries.sh
# 3a-bis's test: every real project sets BOOTSTRAPPED=yes; the template never does.
SHIP69="$REPO_ROOT/.claude/harness/project.conf"
live69() { tr -d '\r' < "$1" | grep -cE -- '^[[:space:]]*keep-when[[:space:]]*\|'; }
if grep -qE '^BOOTSTRAPPED=yes' "$SHIP69"; then
  printf '    note: %s\n' "project.conf is this project's own (BOOTSTRAPPED=yes), not the template; its keep-when text is not asserted (HARNESS-070)"
else
  _fmt="$(tr -d '\r' < "$SHIP69" | grep -nxF -- '# Format:  keep-when | <gate id> | <extended regex>' | cut -d: -f1 | tr '\n' ' ' | sed 's/ $//')"
  _sfmt="$(tr -d '\r' < "$SHIP69" | grep -nxF -- '# Format:  skipped-when | <gate id> | <extended regex>' | cut -d: -f1)"
  _boot="$(tr -d '\r' < "$SHIP69" | grep -nxE -- 'BOOTSTRAPPED=[a-z]+' | head -n 1 | cut -d: -f1)"
  assert_eq "AC-7: the shipped project.conf holds the keep-when format line once, after skipped-when's and before BOOTSTRAPPED=" yes \
    "$([ -n "$_fmt" ] && [ "${_fmt#* }" = "$_fmt" ] && [ -n "$_sfmt" ] && [ -n "$_boot" ] && [ "$_sfmt" -lt "$_fmt" ] && [ "$_fmt" -lt "$_boot" ] && printf yes || printf "no (keep-when format at ${_fmt:-none}, skipped-when format at ${_sfmt:-none}, BOOTSTRAPPED at ${_boot:-none})")"
  _ex="$(tr -d '\r' < "$SHIP69" | grep -nE -- '^#[[:space:]]+keep-when[[:space:]]*\|[[:space:]]*[a-z]' | head -n 1 | cut -d: -f1)"
  assert_eq "AC-7: and an example keep-when line in a comment, between the format line and BOOTSTRAPPED=" yes \
    "$([ -n "$_ex" ] && [ -n "$_fmt" ] && [ -n "$_boot" ] && [ "$_fmt" -lt "$_ex" ] && [ "$_ex" -lt "$_boot" ] && printf yes || printf "no (example at ${_ex:-none})")"
  assert_eq "AC-7: the shipped project.conf carries no live keep-when line" 0 "$(live69 "$SHIP69")"
fi
printf 'BOOTSTRAPPED=yes\nkeep-when | unit | x\n  keep-when|unit|y\n# keep-when | unit | z\n' > "$M69/live.conf"
assert_eq "AC-7 control: the live-line reader counts two live lines and not the comment" 2 "$(live69 "$M69/live.conf")"
cp "$SHIP69" "$F69/.claude/harness/project.conf"
out="$(g69 --audit)"; rc=$?
assert_eq "AC-7: the shipped manifest's --audit still passes" 1 "$(count_line 'Manifest audit passed.' "$out")"
assert_eq "AC-7: and exits 0" 0 "$rc"
assert_eq "AC-7: with no FAIL line" 0 "$(count_re '^FAIL ' "$out")"
assert_eq "AC-7 control: the manifest fixture beside the goldens carries no keep-when line" 0 \
  "$(live69 "$MANIFEST_FIXTURES/project.conf")"
assert_eq "AC-7: project.audit.golden is byte-for-byte what it was (blob 336b0ed)" \
  336b0ede549165e3bfa04bbb8b248e35b2186589 "$(git -C "$REPO_ROOT" hash-object -- "$MANIFEST_FIXTURES/project.audit.golden")"
assert_eq "AC-7: project.list.golden is byte-for-byte what it was (blob 8569947)" \
  8569947d5764058a64116cbdd32d079396735ae8 "$(git -C "$REPO_ROOT" hash-object -- "$MANIFEST_FIXTURES/project.list.golden")"
assert_eq "AC-7: broken.audit.golden is byte-for-byte what it was (blob 283d6b1)" \
  283d6b1627dd62738e6955be0e4768ea1f73542d "$(git -C "$REPO_ROOT" hash-object -- "$MANIFEST_FIXTURES/broken.audit.golden")"

# --- AC-11: configuring.md lists the kind ------------------------------------
CFG69="$REPO_ROOT/.claude/skills/quality-gates/reference/configuring.md"
_kr="$(tr -d '\r' < "$CFG69" | grep -nxF -- '    keep-when    | <gate id> | <regex of a failure nobody has explained yet>' | cut -d: -f1)"
_sr="$(tr -d '\r' < "$CFG69" | grep -nxF -- '    skipped-when | <gate id> | <regex meaning the work was skipped, not lost>' | cut -d: -f1)"
assert_eq "AC-11 control: configuring.md has the skipped-when row the new one goes after" 1 \
  "$(printf '%s\n' "$_sr" | grep -c '^[0-9]')"
assert_eq "AC-11: configuring.md's kinds table has the keep-when row once, straight after skipped-when's" yes \
  "$([ -n "$_kr" ] && [ "${_kr#*[!0-9]}" = "$_kr" ] && [ -n "$_sr" ] && [ "$_kr" = "$((_sr + 1))" ] && printf yes || printf "no (keep-when row at ${_kr:-none}, skipped-when row at ${_sr:-none})")"
assert_eq "AC-11: and the count above the table says nine" 1 \
  "$(count_line 'Nine more kinds, each explained in the skill and in `project.conf`'"'"'s own' "$(tr -d '\r' < "$CFG69")")"

summary "gates"
