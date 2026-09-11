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
story "$FIX" T-1 GATES <<'EOF'
EOF
set_phase "$FIX" GATES
out="$(gates --fast)"
assert_contains "a fast run is never recorded" "not recorded in the story" "$out"
out="$(gates)"
assert_contains "a full run still is"          "recorded in docs/backlog/stories/T-1.md" "$out"
assert_contains "and points at CI's other script" "check-boundaries.sh" "$out"
set_phase "$FIX" ""

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
case "$out" in
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
#   error: failed to run custom build command for `fantasy-world-builder v0.1.0`
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

summary "gates"
