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
# The story's frontmatter says `branch: story/T-1-fixture` and `git init` left
# this fixture on `master`. Nothing read that mismatch until MT-032 AC-3, which
# refuses to record a gate run into a story the checkout does not belong to - so
# the precondition for "a full run records" has to be a legal one. Be on the
# story's branch for this assertion and come back afterwards; the same technique
# the `covers` block below uses. The assertion itself is unchanged: it is the
# only coverage that recording works at all.
_here="$(git -C "$FIX" rev-parse --abbrev-ref HEAD 2>/dev/null)"
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
out="$(gates)"
assert_contains "a full run still is"          "recorded in docs/backlog/stories/T-1.md" "$out"
assert_contains "and points at CI's other script" "check-boundaries.sh" "$out"
git -C "$FIX" checkout -q "$_here" 2>/dev/null
git -C "$FIX" branch -q -D story/T-1-fixture 2>/dev/null
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

# ---------------------------------------------------------------------------
describe "the manifest must not change under the run"

# MT-032 AC-1 and AC-2 / F-1, the failure in this story with no backstop.
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

# F-1 was OBSERVED on a --fast run. A check that only ran in full mode would fix
# nothing that was actually reported.
conf_edits_itself
out="$(gates --fast)"; rc=$?
assert_contains "--fast catches it too" \
  "config: .claude/harness/project.conf changed while the gates were running" "$out"
assert_eq "and --fast exits non-zero as well" "1" "$rc"

# MT-032 AC-5, asserted where it can actually regress: these two lines live in
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

# DV-2, the false-positive control, and the one that matters: a check that fired
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
describe "--fast says, in full, that it is not a verdict"

# MT-032 AC-5. Both strings verbatim, on an ordinary --fast run, so that a later
# edit to the summary block cannot quietly drop or reword either. The existing
# assertions above match only the first half of each sentence.
write_conf "$FIX" <<'EOF'
gate     | unit  | required | . | printf 'Tests  47 passed (47)\n'
gate     | build | required | . | printf 'Bundled 3 targets\n'
evidence | unit  | Tests +[1-9][0-9]* passed
evidence | build | Bundled [1-9][0-9]* targets
slow     | build | a release bundle; RED has no use for it
EOF
out="$(gates --fast)"
assert_contains "the caveat, verbatim" \
  "This is a subset, not a verdict. The full run before REVIEW is what judges the story." "$out"
assert_contains "the not-recorded line, verbatim" \
  "(not recorded in the story: a partial run is not evidence of anything)" "$out"

# ---------------------------------------------------------------------------
describe "a gate record goes into the story whose branch you are on"

# MT-032 AC-3 / F-2. `.claude/state/current-story.env` is global to the tree
# rather than to the caller, so a second session - or a script run from the
# wrong context - stamps `## Gate results` into a story it is not working on.
# `phase.sh set` already refuses exactly this mismatch; gates.sh did not, and
# the two should agree. The run itself was valid: it is the RECORDING that is
# misdirected, so the verdict, the exit status and the machine-local stamp are
# all left alone.
gate_blocks() { grep -c 'written by bash scripts/gates.sh' "$FIX/docs/backlog/stories/T-1.md"; }

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
git -C "$FIX" checkout -q -B unrelated-session 2>/dev/null
story "$FIX" T-1 GATES </dev/null
set_phase "$FIX" GATES
rm -f "$FIX/.claude/state/last-gate-run"
out="$(gates)"; rc=$?
assert_contains "the record is refused, naming both branches" \
  "not recorded: the checkout is on 'unrelated-session' but story T-1 belongs on 'story/T-1-fixture'" "$out"
assert_eq "and nothing is written into the story"   "0" "$(gate_blocks)"
assert_eq "and the gates' own exit status is untouched" "0" "$rc"
assert_contains "and their verdict still printed"   "All required gates passed" "$out"
# C-4: the stamp is machine-local and it is what the Stop hook reads. Suppressing
# it would make the hook claim the gates had never run.
# The needle carries the following line, not just the field: `RESULT=pass` alone
# is a prefix of anything starting `RESULT=pass`, and a probe that renamed the
# value to `passok` walked straight through it.
assert_contains "the machine-local stamp is still written" $'RESULT=pass\nWHEN=' \
  "$(cat "$FIX/.claude/state/last-gate-run")"
assert_contains "and still says it was a full run"         "FULL=yes" \
  "$(cat "$FIX/.claude/state/last-gate-run")"

# A failing run on the wrong branch is still a failing run.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  2 failed, 45 passed (47)\n'; exit 1
evidence | unit | Tests +[1-9][0-9]* passed
EOF
story "$FIX" T-1 GATES </dev/null
out="$(gates)"; rc=$?
assert_eq "a failing run on the wrong branch still exits 1" "1" "$rc"
assert_eq "and still writes nothing into the story"         "0" "$(gate_blocks)"

# --story names the story explicitly. It is not an override: the comparison is
# against that story's own frontmatter, so it is refused too.
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
story "$FIX" T-1 GATES </dev/null
set_phase "$FIX" ""
out="$(gates --story T-1)"
assert_contains "--story is not an override" \
  "not recorded: the checkout is on 'unrelated-session' but story T-1 belongs on 'story/T-1-fixture'" "$out"
assert_eq "and it writes nothing either" "0" "$(gate_blocks)"

# Fail open where it cannot tell, as the harness does everywhere else: a
# detached HEAD has no branch to compare, and must not be refused.
story "$FIX" T-1 GATES </dev/null
set_phase "$FIX" GATES
git -C "$FIX" checkout -q --detach 2>/dev/null
out="$(gates)"
assert_contains "a detached HEAD is not refused" "recorded in docs/backlog/stories/T-1.md" "$out"
assert_eq "and the record is in the story"       "1" "$(gate_blocks)"

# The control for the refusal: on the story's own branch it records, as it
# always has.
story "$FIX" T-1 GATES </dev/null
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null
out="$(gates)"
assert_contains "the story's own branch records" "recorded in docs/backlog/stories/T-1.md" "$out"
assert_eq "and the block is in the story"        "1" "$(gate_blocks)"
set_phase "$FIX" ""

# ---------------------------------------------------------------------------
describe "skipped-when: a gate that skipped its work stops reporting PASS"

# MT-037. `integration` reported `PASS integration (9s, observed 1)` on a run
# where 1 of its 26 collected tests ran and 25 skipped, because the evidence
# regex `[1-9][0-9]* passed` is satisfied by `1 passed` and the gate had no
# floor. That is the vacuous pass the evidence mechanism exists to catch, and
# the mechanism could not catch it.
#
# The fix is a floor plus a new manifest kind, `skipped-when`, that CLASSIFIES
# a below-floor shortfall: the environment declining to supply the work
# (BLOCKED when a story leans on the gate, KNOWN when it does not) rather than
# the suite having lost it (FAIL/WARN, exactly as today). The two halves of
# that sentence are tested against each other throughout this block - a fix
# that made `integration` never pass, and a pattern that excused every
# shortfall, would each satisfy one half of it.

set_phase "$FIX" ""
git -C "$FIX" checkout -q -B story/T-1-fixture 2>/dev/null

# The `why` string, verbatim, for the 1-of-26 run most cases below use. It
# carries the observed count, the floor and the word `skipped`, so the summary
# line answers *why* without anyone opening the gate log.
SKIPWHY='did 1 units of work, below the floor of 26 in project.conf; the log says 25 skipped, so the work was skipped rather than lost: the environment did not supply it'
SKIPCMD='printf "1 passed, 25 skipped in 0.46s\n"'
INTLOG='-> .claude/state/gate-logs/integration.log'

# The configuration C-3 puts in the real manifest, spelled out so that the
# cases below test gates.sh's machinery rather than the manifest's contents.
# AC-1's own two cases read the real manifest instead; see below.
int_conf() { # <required|optional> <gate command>
  write_conf "$FIX" <<EOF
gate         | integration | $1 | . | $2
evidence     | integration | [1-9][0-9]* passed
floor        | integration | 26
skipped-when | integration | [1-9][0-9]* skipped
EOF
}

# --- AC-1: the bug, at the manifest and then end to end ---------------------

# The manifest itself, not a fixture copy of it. A suite that only ever asks
# gates.sh about a conf it wrote itself goes green while the REAL integration
# gate still reports PASS on a machine that ran one of its 26 tests - and that
# machine is every worktree this harness dispatches into. Same reasoning as
# make_fixture copying the real paths.conf and VERSION rather than inventing
# them.
REAL_CONF="$REPO_ROOT/.claude/harness/project.conf"
real_conf_value() { # <kind> <gate id>
  grep -E "^[[:space:]]*$1[[:space:]]*\|[[:space:]]*$2[[:space:]]*\|" "$REAL_CONF" \
    | head -1 | cut -d'|' -f3- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}
# 26 is settled: the collected count of `tests/integration -m "gpu or network"`,
# observed as `26 passed` in MT-036's stamped record and as `1 passed, 25
# skipped` in MT-037 PO-1. Not re-derived here.
assert_eq "the manifest gives integration a floor of 26" \
  "26" "$(real_conf_value floor integration)"
# `skipped` and NOT `deselected`, exactly. A skip is the tests deciding at call
# time that their inputs are absent; a deselection is the gate's own marker
# expression, which is a change to the manifest and therefore a regression. A
# pattern widened to cover `deselected` would excuse the regression AC-5
# protects against, and would do it in one word nobody would notice.
assert_eq "and a skipped-when pattern that matches skips only" \
  "[1-9][0-9]* skipped" "$(real_conf_value skipped-when integration)"

# End to end, with the real manifest's own integration lines lifted into the
# fixture and only the command replaced. This is MT-037 PO-1 reproduced
# mechanically, and it is the permanent regression test.
{ printf 'gate         | integration | optional | . | %s\n' "$SKIPCMD"
  grep -E '^[[:space:]]*(evidence|floor|skipped-when)[[:space:]]*\|[[:space:]]*integration[[:space:]]*\|' "$REAL_CONF"
} | write_conf "$FIX"
out="$(gates)"
assert_not_contains "a run that skipped 25 of its 26 tests is not a PASS" \
  "PASS         integration" "$out"

# --- AC-2: the negative control for AC-1 ------------------------------------

# A fix that satisfies AC-1 by making `integration` never pass fails here, and
# it is the cheapest wrong fix available.
int_conf optional 'printf "26 passed in 7.1s\n"'
out="$(gates)"; rc=$?
assert_contains "a machine that has the data still passes" "PASS         integration" "$out"
assert_contains "naming both the count and the floor"      "observed 26, floor 26" "$out"
assert_eq "and the run exits 0"                            "0" "$rc"

# C-1: the pattern is never consulted at or above the floor. A gate that did
# all its work is a pass even though some of its tests skipped.
int_conf optional 'printf "26 passed, 3 skipped in 7.1s\n"'
out="$(gates)"
assert_contains "a gate at its floor passes even though tests skipped" \
  "PASS         integration" "$out"
assert_not_contains "and is not turned into a declared non-result" \
  "KNOWN        integration" "$out"

# --- AC-4: no active story, so the gate is optional -------------------------
# Ordered before AC-3 because it needs no story file, and AC-3 leaves one.

set_phase "$FIX" ""
int_conf optional "$SKIPCMD"
rm -f "$FIX/.claude/state/last-gate-run"
out="$(gates)"; rc=$?
assert_contains "an optional gate the environment starved reports KNOWN" \
  "KNOWN        integration" "$out"
assert_contains "and says why, inline"   "$SKIPWHY" "$out"
assert_contains "and points at the log"  "$INTLOG" "$out"
# Specifically not WARN: a WARN on every PR for the life of the project is the
# outcome MT-007 and MT-008 declined a floor to avoid, and quality-gates
# reserves WARN for something that CHANGED.
assert_not_contains "and is specifically not a WARN" "WARN         integration" "$out"
assert_eq "and the run exits 0" "0" "$rc"
assert_contains "and it is counted as a known non-result" \
  "All required gates passed (1 ran, 0 unconfigured, 1 known)" "$out"
assert_contains "and the stamp still records a pass" $'RESULT=pass\nWHEN=' \
  "$(cat "$FIX/.claude/state/last-gate-run")"

# C-2: an optional gate that also carries a waiver keeps the waiver wording -
# the waiver is the broader declaration.
write_conf "$FIX" <<EOF
gate         | integration | optional | . | $SKIPCMD
evidence     | integration | [1-9][0-9]* passed
floor        | integration | 26
skipped-when | integration | [1-9][0-9]* skipped
waiver       | integration | the spike data is not redistributable
EOF
out="$(gates)"
assert_contains "a waiver is still named beside the reason" \
  "$SKIPWHY; the spike data is not redistributable" "$out"

# --- AC-3: a story escalated the gate ---------------------------------------

story "$FIX" T-1 GATES <<'EOF'
required_gates: [integration]
EOF
set_phase "$FIX" GATES
int_conf optional "$SKIPCMD"
rm -f "$FIX/.claude/state/last-gate-run"
out="$(gates)"; rc=$?
assert_contains "a gate the story leans on is BLOCKED" "BLOCKED      integration" "$out"
assert_contains "naming the story that escalated it"   "required by story T-1" "$out"
assert_contains "and says why"                         "$SKIPWHY" "$out"
assert_contains "and points at the log"                "$INTLOG" "$out"
assert_contains "and it is counted as a gate that could not run" \
  "1 required gate(s) could not run" "$out"
assert_eq "and the run exits 3, not 0 and not 1" "3" "$rc"
assert_contains "and the story records result: blocked" "result: blocked" \
  "$(cat "$FIX/docs/backlog/stories/T-1.md")"
# C-5: check-boundaries.sh greps ## Gate results for
# `^[[:space:]]*PASS[[:space:]]+<gate>` and calls it "story-required gate '<g>'
# passed in the recorded run". This is the assertion that makes that check bite
# instead of agreeing with a vacuous run - the same grep, run here against what
# gates.sh actually wrote.
assert_eq "so the record carries no PASS line for check-boundaries.sh to read" "0" \
  "$(grep -cE '^[[:space:]]*PASS[[:space:]]+integration( |\(|$)' "$FIX/docs/backlog/stories/T-1.md")"

# --- AC-5: the negative control for AC-3 and AC-4 ---------------------------
# The pattern CLASSIFIES a shortfall. It must never excuse one.

int_conf optional 'printf "3 passed in 0.4s\n"'
out="$(gates)"; rc=$?
assert_contains "required: a shortfall the pattern does not match still FAILs" \
  "FAIL         integration" "$out"
assert_contains "with the floor wording it has always had" \
  "did 3 units of work, below the floor of 26 in project.conf" "$out"
assert_not_contains "and is not reported as a block" "BLOCKED      integration" "$out"
assert_eq "and the run exits 1" "1" "$rc"

set_phase "$FIX" ""
out="$(gates)"; rc=$?
assert_contains "optional: the same shortfall still WARNs" "WARN         integration" "$out"
assert_not_contains "and is not excused as a declared non-result" \
  "KNOWN        integration" "$out"
assert_eq "and the run exits 0" "0" "$rc"

# The distinction C-3 calls load-bearing, at the only place it can be tested:
# `deselected` is the gate's own marker expression having changed, which is a
# regression in the manifest, not an environment that failed to supply data.
# `-m "network"` in place of `-m "gpu or network"` must still be caught.
int_conf optional 'printf "3 passed, 23 deselected in 0.4s\n"'
out="$(gates)"
assert_contains "a deselected shortfall is a manifest regression, not an environment" \
  "WARN         integration" "$out"
assert_not_contains "so the skip pattern does not classify it" \
  "KNOWN        integration" "$out"

# --- DV-2: the new arm is unreachable on the rc != 0 path -------------------
# `skipped-when` is consulted only for a gate that exited 0 and came in below
# its floor. A command that exits non-zero is the existing fail/blocked-when
# logic, whatever its log says.
#
# The claim has two halves, and each needs the fixture that can observe it. On a
# REQUIRED gate a broken rc guard would send this log into the `environment` arm
# and out as BLOCKED, so `required` is where "not a block" discriminates. It is
# also where `KNOWN` is impossible for a reason that has nothing to do with DV-2
# - a required gate never reports KNOWN without a waiver - so the other half is
# asserted on the OPTIONAL twin below, where `KNOWN` is exactly what a broken rc
# guard produces. See `## Regressions` R-6.

int_conf required 'printf "1 passed, 25 skipped in 0.46s\nINTERNALERROR: the run aborted\n"; exit 2'
out="$(gates)"; rc=$?
assert_contains "a non-zero exit fails even when the log matches the skip pattern" \
  "FAIL         integration" "$out"
assert_not_contains "and is not a block"            "BLOCKED      integration" "$out"
assert_eq "and the run exits 1"                     "1" "$rc"

# The optional twin: same command, same log, `optional` instead of `required`.
# The rc != 0 path ends in WARN here, and the arm DV-2 says is unreachable would
# end in KNOWN - so a single mutation of the rc guard turns this pair red.
int_conf optional 'printf "1 passed, 25 skipped in 0.46s\nINTERNALERROR: the run aborted\n"; exit 2'
out="$(gates)"
assert_contains "optional: a non-zero exit warns even when the log matches the skip pattern" \
  "WARN         integration" "$out"
assert_not_contains "and is not excused as a declared non-result on the rc != 0 path" \
  "KNOWN        integration" "$out"

# --- C-1: the pattern survives the split on `|` -----------------------------
# Stored with `cut -d'|' -f3-`, as `evidence` and `blocked-when` are, so a
# pattern using alternation is not truncated at its first branch. Here only the
# SECOND branch matches - `0 skipped` does not match `[1-9][0-9]* skipped` - so
# a parser that kept `-f3` would report WARN.

write_conf "$FIX" <<'EOF'
gate         | integration | optional | . | printf "1 passed, 0 skipped in 0.4s\nno data files were supplied\n"
evidence     | integration | [1-9][0-9]* passed
floor        | integration | 26
skipped-when | integration | [1-9][0-9]* skipped|no data files were supplied
EOF
out="$(gates)"
assert_contains "a pattern using alternation is not truncated at the first branch" \
  "KNOWN        integration" "$out"
assert_contains "and the line quotes the branch that matched" \
  "the log says no data files were supplied" "$out"

# --- AC-6: the audit refuses a line that can never protect anything ---------

# (a) names no configured gate: it fires on nothing.
write_conf "$FIX" <<'EOF'
gate         | integration | optional | . | printf "26 passed in 7.1s\n"
evidence     | integration | [1-9][0-9]* passed
floor        | integration | 26
skipped-when | integratoin | [1-9][0-9]* skipped
EOF
out="$(gates --audit)"; rc=$?
assert_contains "a skipped-when naming no configured gate fails the audit" \
  'a `skipped-when` line names no configured gate' "$out"
assert_eq "and the audit exits non-zero" "1" "$rc"

# (b) no pattern: it would match every log and turn every shortfall into a
# block, which is the opposite of the point.
write_conf "$FIX" <<'EOF'
gate         | integration | optional | . | printf "26 passed in 7.1s\n"
evidence     | integration | [1-9][0-9]* passed
floor        | integration | 26
skipped-when | integration |
EOF
out="$(gates --audit)"; rc=$?
assert_contains "a skipped-when with no pattern fails the audit" \
  'a `skipped-when` line has no pattern' "$out"
assert_eq "and the audit exits non-zero" "1" "$rc"

# (c) names a gate with no floor: there is no measurement to classify, so the
# line sits in the manifest looking like protection. Same reasoning as the
# existing "a floor needs an evidence regex to measure".
write_conf "$FIX" <<'EOF'
gate         | build | required | . | printf "Bundled 3 targets\n"
evidence     | build | Bundled [1-9][0-9]* targets
skipped-when | build | [1-9][0-9]* skipped
EOF
out="$(gates --audit)"; rc=$?
assert_contains "a skipped-when on a gate with no floor fails the audit" \
  'a `skipped-when` line names a gate with no `floor` line' "$out"
assert_eq "and the audit exits non-zero" "1" "$rc"

# The negative control for all three: a well-formed line on a floored gate
# passes, and is printed with the gate so that the audit shows what it read.
write_conf "$FIX" <<'EOF'
gate         | integration | optional | . | printf "26 passed in 7.1s\n"
evidence     | integration | [1-9][0-9]* passed
floor        | integration | 26
skipped-when | integration | [1-9][0-9]* skipped
EOF
out="$(gates --audit)"; rc=$?
assert_contains "a well-formed skipped-when passes the audit" "Manifest audit passed." "$out"
assert_contains "and the audit prints it with the gate" \
  "skipped-when: [1-9][0-9]* skipped" "$out"
assert_eq "and the audit exits 0" "0" "$rc"

# --- AC-7: --list prints the pattern ----------------------------------------

write_conf "$FIX" <<'EOF'
gate         | integration | optional | . | printf "26 passed in 7.1s\n"
evidence     | integration | [1-9][0-9]* passed
floor        | integration | 26
blocked-when | integration | no CUDA-capable device
skipped-when | integration | [1-9][0-9]* skipped
EOF
out="$(gates --list)"
assert_contains "--list prints the skip pattern"  "skipped-when: [1-9][0-9]* skipped" "$out"
assert_contains "beside the blocked-when line"    "blocked-when: no CUDA-capable device" "$out"
assert_contains "beside the floor"                "floor:    26" "$out"
assert_contains "and the evidence regex"          "evidence: [1-9][0-9]* passed" "$out"

set_phase "$FIX" ""


# --- a mutation left in the tree is not a thing to judge code against -------
describe "the gates refuse to run while a mutation is unaccounted for"

# scripts/mutate.sh can put the file back on every path it can still run code
# on, and there is one it cannot: a kill. The file is then left mutated with
# nothing to say so, and the next thing to read the tree judges code nobody
# wrote. Under law 3 that verdict is filed as evidence, stamped against a tree
# hash that faithfully records the mutated version.
#
# So mutate.sh leaves a sentinel while a mutation is in flight and `--check`
# reads it, and this is the consumer that matters. Detection, not a lock - the
# rule this file already holds about project.conf: nothing waits, nothing is
# held, the run is refused and the reason is printed.

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF

# Stranded the way a killed run strands one: the command makes the target
# unwritable, so mutate.sh's restore genuinely fails and its sentinel stays.
printf 'export const clamp = (v) => Math.min(90, v)\n' > "$FIX/src/main.ts"
( cd "$FIX" && bash scripts/mutate.sh src/main.ts 's/90/-90/' -- chmod 444 src/main.ts ) >/dev/null 2>&1
chmod 644 "$FIX/src/main.ts" 2>/dev/null

out="$(gates)"; rc=$?
assert_contains "it says the tree may not be the code"  "may not be the code you think" "$out"
assert_contains "and names the file that is mutated"    "src/main.ts" "$out"
assert_eq       "and exits non-zero"                    "2" "$rc"
assert_not_contains "and no gate ran"                   "PASS         unit" "$out"

# --list and --audit read the manifest and run nothing against the tree, so a
# stranded mutation is none of their business. A check that refused everything
# would make the harness unusable at exactly the moment somebody needs it to
# explain itself.
out="$(gates --list)"
assert_contains "--list still works" "unit" "$out"

# The negative control. Without this, a check that refused unconditionally
# would satisfy every assertion above.
cp "$FIX"/.claude/state/mutations/*.bak "$FIX/src/main.ts" 2>/dev/null
rm -f "$FIX"/.claude/state/mutations/*.active "$FIX"/.claude/state/mutations/*.bak
out="$(gates)"
assert_contains "resolved, the gates run again" "PASS         unit" "$out"

summary "gates"
