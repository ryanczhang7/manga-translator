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
write_conf "$FIX" <<'EOF'
gate     | unit     | required | . | printf 'Tests  47 passed (47)\n'
gate     | mutation | optional | . | printf 'Killed 12 of 12 mutants\n'
evidence | unit     | Tests +[1-9][0-9]* passed
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
lineno() { printf '%s\n' "$2" | grep -m1 -nxF -- "$1" | cut -d: -f1; }
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

assert_eq "HARNESS-030: no sentinel is left in the shared fixture" "" \
  "$(for a in "$H30MUT"/*.active; do [ -e "$a" ] && printf '%s ' "${a##*/}"; done)"
rm -f "$H30MARK"
git -C "$FIX" checkout -q -- . 2>/dev/null
git -C "$FIX" checkout -q main 2>/dev/null
set_phase "$FIX" ""

summary "gates"
