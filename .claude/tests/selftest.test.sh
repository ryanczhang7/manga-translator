#!/usr/bin/env bash
# Tests for scripts/selftest.sh's ASSERTION FLOORS - MT-039.
#
# selftest.sh runs each harness suite and reads its exit status and nothing
# else. A suite that executed zero assertions exits 0; a suite replaced by a
# single `printf` exits 0. Three stories that reward a SMALLER self-test
# (MT-040, MT-041, MT-042) are queued behind this one, so the guard-rail ships
# first: each suite declares in .claude/tests/floors.conf how much work it is
# worth, and a suite that does less fails the run even when it exits 0.
#
# Two things about this file are worth knowing before changing it.
#
# 1. The floor is the EXECUTED assertion count - the `N` of summary()'s
#    `<name>: N passed, M failed` line - and not the number of `assert_` call
#    sites in the source. They are different numbers: `profiles` is ONE call
#    site inside a loop and FORTY-FOUR executed assertions, `lib` is 57 and
#    148. A call-site floor for `profiles` would be 1, and deleting 43 of its
#    44 assertions would satisfy it. Every fixture suite below is generated in
#    that same shape - one call site, a loop - so the distinction is live in
#    every case rather than argued about in a comment.
#
# 2. Every fixture runs against a THROWAWAY tree, never this checkout. The
#    fixture gets its own .claude/tests with its own suites and its own
#    floors.conf, so nothing here depends on - or disturbs - the twelve real
#    suites whose counts this story is about.
#
# The one real-tree assertion block reads .claude/tests/floors.conf itself and
# checks it against the values MT-039 C-3 settled. Those are read out, not
# re-derived.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT

mkdir -p "$FIX/.claude/tests"
# The REAL _lib.sh, for the same reason make_fixture copies the real paths.conf:
# the summary() format string this story reads is the one the repository ships.
cp "$REPO_ROOT/.claude/tests/_lib.sh" "$FIX/.claude/tests/_lib.sh"

# --- fixture helpers ---------------------------------------------------------

# reset_suites   Empties the fixture's test directory and its floors file.
reset_suites() { rm -f "$FIX"/.claude/tests/*.test.sh "$FIX/.claude/tests/floors.conf"; }

# passing_suite <name> <n>   A suite with exactly ONE `assert_` call site,
# executed <n> times. That shape is AC-7's subject, not an accident of writing.
passing_suite() {
  {
    printf '#!/usr/bin/env bash\n'
    printf '. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"\n'
    printf 'i=0\n'
    printf 'while [ $i -lt %d ]; do\n' "$2"
    printf '  assert_eq "case $i" x x\n'
    printf '  i=$((i+1))\n'
    printf 'done\n'
    printf 'summary "%s"\n' "$1"
  } > "$FIX/.claude/tests/$1.test.sh"
}

# floors   floors.conf body on stdin.
floors() { cat > "$FIX/.claude/tests/floors.conf"; }

# selftest [args...]   Runs the fixture's copy of scripts/selftest.sh. Sets
# `out` and `RC` as globals rather than echoing, so that $? survives.
selftest() { out="$( cd "$FIX" && bash scripts/selftest.sh "$@" 2>&1 )"; RC=$?; }

# shortfall   The floor-shortfall line out of the last run, or empty. Empty is
# never treated as a match by the assertions below: a preceding assert_contains
# on the WHOLE output reports what was printed instead.
shortfall() { printf '%s\n' "$out" | grep -F 'below the floor' | head -1; }

# ---------------------------------------------------------------------------
describe "AC-1  a suite below its floor fails the run, though the suite exits 0"

reset_suites
passing_suite new-story 21
floors <<'FLOORS'
floor | new-story | 22
FLOORS

# The premise, asserted rather than assumed: there is nothing wrong with the
# suite. 21 passing assertions, no failures, exit 0. That is precisely the
# state the existing exit-status check cannot see.
( cd "$FIX" && bash .claude/tests/new-story.test.sh >/dev/null 2>&1 )
assert_eq "the shrunken suite itself still exits 0" 0 "$?"

selftest new-story
assert_eq "but the self-test run exits non-zero" 1 "$RC"
assert_contains "and reports a floor shortfall" "below the floor" "$out"
line="$(shortfall)"
assert_contains "the shortfall names the suite" "new-story" "$line"
assert_contains "and both numbers, in the words gates.sh already uses" \
  "did 21 units of work, below the floor of 22" "$line"
assert_not_contains "the run does not also claim everything passed" \
  "harness suite(s) passed." "$out"

# ---------------------------------------------------------------------------
describe "AC-2  floors that match reality pass everything, and pass silently"

# The negative control for AC-1. A mechanism that satisfies AC-1 by failing
# always, or by failing any suite whose count it cannot parse, dies here.
reset_suites
passing_suite alpha 3
passing_suite beta  7
passing_suite gamma 1
floors <<'FLOORS'
# floors for the fixture suites
floor | alpha | 3
floor | beta  | 7
floor | gamma | 1
FLOORS
selftest
assert_eq "the run exits 0" 0 "$RC"
assert_contains "and says every suite passed" "3 harness suite(s) passed." "$out"
assert_not_contains "no suite is reported short" "below the floor" "$out"
assert_not_contains "and nothing is reported as a fault at all" "FAIL" "$out"

# ---------------------------------------------------------------------------
describe "AC-3  a floor is a floor, not an equality"

# Without this the mechanism becomes a tax on every future story: a story that
# ADDS an assertion would have to edit floors.conf to stay green. One that
# REMOVES one must.
reset_suites
passing_suite new-story 23
floors <<'FLOORS'
floor | new-story | 22
FLOORS
selftest new-story
assert_eq "a suite above its floor exits 0" 0 "$RC"
assert_contains "and the run says it passed" "1 harness suite(s) passed." "$out"
assert_not_contains "no shortfall is reported for a suite that grew" \
  "below the floor" "$out"

# ---------------------------------------------------------------------------
describe "AC-4  the floor does not displace the check that already exists"

# 22 passing assertions and one failing: the floor of 22 is MET, and the run
# must fail anyway. A mechanism that reduces to "is the count high enough"
# passes a suite whose assertions are red.
reset_suites
{
  printf '#!/usr/bin/env bash\n'
  printf '. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"\n'
  printf 'i=0\n'
  printf 'while [ $i -lt 22 ]; do\n'
  printf '  assert_eq "case $i" x x\n'
  printf '  i=$((i+1))\n'
  printf 'done\n'
  printf 'assert_eq "the one that is wrong" want got\n'
  printf 'summary "new-story"\n'
} > "$FIX/.claude/tests/new-story.test.sh"
floors <<'FLOORS'
floor | new-story | 22
FLOORS
selftest new-story
assert_eq "a failing assertion still fails the run" 1 "$RC"
assert_contains "the suite's own summary shows the floor was met" \
  "new-story: 22 passed, 1 failed" "$out"
assert_contains "and the run reports the suite as failed" \
  "harness suite(s) FAILED" "$out"
assert_not_contains "the floor is not what is blamed, because it was met" \
  "below the floor" "$out"

# ---------------------------------------------------------------------------
describe "AC-5  a malformed floors line is named, with its line and its fault"

# gates.sh:112 drops any `kind` it does not recognise, so a one-character typo
# switches a gate's evidence off in silence. A floors mechanism that inherits
# that silence is a floor a typo turns off with no output.

# (a) a floor naming a suite that does not exist.
reset_suites
passing_suite alpha 3
# Line 1 is the comment, 2 is blank, 3 is alpha's floor, and the fault is on
# line 4. The comment and the blank line are there so that a mechanism
# reporting a count of PARSED lines rather than a file line number gets the
# wrong answer here.
floors <<'FLOORS'
# a comment, and a blank line, before the fault

floor | alpha | 3
floor | ghost | 12
FLOORS
selftest
assert_eq "an unmatched floor fails the run" 1 "$RC"
assert_contains "it says which file and line" "floors.conf:4" "$out"
assert_contains "it names the suite it could not find" "ghost" "$out"
assert_contains "and which of the two faults this is" "does not exist" "$out"

# (b) a floor whose value is not a number.
reset_suites
passing_suite alpha 3
floors <<'FLOORS'
# the fault is on line 2
floor | alpha | lots
FLOORS
selftest
assert_eq "a non-numeric floor fails the run" 1 "$RC"
assert_contains "it says which file and line" "floors.conf:2" "$out"
assert_contains "it names the suite" "alpha" "$out"
assert_contains "and which of the two faults this is" "is not a number" "$out"
assert_not_contains "it is not quietly read as zero and passed" \
  "harness suite(s) passed." "$out"

# ---------------------------------------------------------------------------
describe "AC-6  a suite with no floor line fails the run"

# Twelve suites exist today and none has a floor, so this criterion is what
# makes C-3's table exhaustive rather than a sample. The friction is the point:
# a thirteenth suite must declare what it is worth, because a suite with no
# floor is a suite that can be emptied.
reset_suites
passing_suite alpha  3
passing_suite orphan 5
floors <<'FLOORS'
floor | alpha | 3
FLOORS
selftest
assert_eq "an undeclared suite fails the run" 1 "$RC"
assert_contains "it says a floor is missing" "no floor line" "$out"
miss="$(printf '%s\n' "$out" | grep -F 'no floor line' | head -1)"
assert_contains "and names the suite that has none" "orphan" "$miss"
assert_not_contains "and not the suite that has one" "alpha" "$miss"

# ---------------------------------------------------------------------------
describe "AC-7  the count read is the EXECUTED count, not the call sites"

# The failure this criterion exists to prevent: `grep -c assert_` over the
# source is the obvious reading of "assertion count" and it is the wrong
# quantity. profiles is 1 call site and 44 executed.
reset_suites
passing_suite loopy 5
assert_eq "the fixture suite really does have exactly one assert_ call site" \
  1 "$(grep -cE '^[[:space:]]*assert_' "$FIX/.claude/tests/loopy.test.sh")"
assert_contains "and really does execute five" "loopy: 5 passed, 0 failed" \
  "$( cd "$FIX" && bash .claude/tests/loopy.test.sh 2>&1 )"
floors <<'FLOORS'
floor | loopy | 5
FLOORS
selftest loopy
assert_eq "one call site executing five times meets a floor of five" 0 "$RC"

# The discriminating half. Four executions against a floor of five must fail
# reporting FOUR - an implementation counting call sites would report ONE, and
# would be wrong here in a way the pass above cannot show.
reset_suites
passing_suite loopy 4
floors <<'FLOORS'
floor | loopy | 5
FLOORS
selftest loopy
assert_eq "four executions against a floor of five fails" 1 "$RC"
line="$(shortfall)"
assert_contains "and the observed number is the executed count, not the call site" \
  "did 4 units of work, below the floor of 5" "$line"

# ---------------------------------------------------------------------------
describe "C-4  the summary line is matched anchored, by name, and the last wins"

# Three decoys, each defeating a different sloppy read: an anchored,
# correctly-named line EARLY (first-match), an indented one LATE (unanchored),
# and an anchored one under another name LATE (no name key). The real count is
# 3 against a floor of 5, so any read that takes a decoy passes and is caught.
reset_suites
cat > "$FIX/.claude/tests/decoy.test.sh" <<'DECOY'
#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
printf 'decoy: 99 passed, 0 failed\n'
i=0
while [ $i -lt 3 ]; do
  assert_eq "case $i" x x
  i=$((i+1))
done
summary "decoy"
printf '    decoy: 77 passed, 0 failed\n'
printf 'other: 88 passed, 0 failed\n'
DECOY
floors <<'FLOORS'
floor | decoy | 5
FLOORS
selftest decoy
assert_eq "the decoys do not rescue a suite below its floor" 1 "$RC"
line="$(shortfall)"
assert_contains "the count comes from the anchored, correctly named, last line" \
  "did 3 units of work, below the floor of 5" "$line"

# ---------------------------------------------------------------------------
describe "C-4  a suite that prints no summary line at all is a failure"

# The strongest form of the defect this story closes: a suite replaced by
# `exit 0` prints nothing, and must not be read as meeting its floor. An
# implementation that treats a missing summary as "no floor to check" is
# defeated by a one-line edit.
reset_suites
{
  printf '#!/usr/bin/env bash\n'
  printf 'printf "silent: did some work, honest\\n"\n'
  printf 'exit 0\n'
} > "$FIX/.claude/tests/silent.test.sh"
floors <<'FLOORS'
floor | silent | 7
FLOORS
selftest silent
assert_eq "a suite that prints no summary fails the run" 1 "$RC"
assert_contains "it names the suite" "silent" "$out"
assert_contains "and says no count could be read" "no summary line" "$out"
assert_not_contains "it is not excused as having no floor to check" \
  "harness suite(s) passed." "$out"

# ---------------------------------------------------------------------------
describe "C-4  the suite's own output still reaches the reader"

# The mechanism needs the suite's stdout, and the cheap way to get it swallows
# it. A failing suite whose output is captured and dropped makes every failure
# a second command to reproduce.
reset_suites
cat > "$FIX/.claude/tests/talky.test.sh" <<'TALKY'
#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
describe "a section heading"
assert_eq "a passing case" x x
assert_eq "a failing case" want got
summary "talky"
TALKY
floors <<'FLOORS'
floor | talky | 1
FLOORS
selftest talky
assert_eq "the failing suite fails the run" 1 "$RC"
assert_contains "the section heading survives" "a section heading" "$out"
assert_contains "the failing assertion's name survives" "FAIL a failing case" "$out"
assert_contains "and the detail under it" "expected: want" "$out"

out="$( cd "$FIX" && VERBOSE=1 bash scripts/selftest.sh talky 2>&1 )"
assert_contains "VERBOSE=1 still names every passing assertion" \
  "ok   a passing case" "$out"

# ---------------------------------------------------------------------------
describe "C-7  summary()'s format string is now load bearing for selftest.sh"

# The one genuine coupling this story introduces, pinned at this end so that a
# change to _lib.sh cannot break the floor read in silence.
# The haystack is summary() alone, not the whole file: a failure here should
# read like a bug report about one function, not print 200 lines of helpers.
assert_contains "the format string selftest.sh reads is unchanged" \
  "printf '\n%s: %d passed, %d failed\n'" \
  "$(sed -n '/^summary() {/,/^}/p' "$REPO_ROOT/.claude/tests/_lib.sh")"

# And live, rather than by grep: what summary() actually emits matches C-4's
# anchored regex exactly.
reset_suites
passing_suite shape 2
assert_eq "summary() emits exactly the anchored line C-4 matches" \
  "shape: 2 passed, 0 failed" \
  "$( cd "$FIX" && bash .claude/tests/shape.test.sh 2>&1 | grep -E '^shape: [0-9]+ passed, [0-9]+ failed$' )"

# ---------------------------------------------------------------------------
describe "C-2  the floors file uses project.conf's grammar"

reset_suites
passing_suite sloppy 3
# Written through printf rather than a heredoc on purpose: the floor line has
# TRAILING space, which is half of what "leading/trailing space trimmed" means,
# and an editor or a formatter that strips it from this file would silently
# delete the case. Generated at run time, nothing can strip it.
printf '%s\n' \
  '' \
  '# a comment, ignored - including one that looks exactly like a floor:' \
  '# floor | sloppy | 999' \
  '' \
  '   floor   |   sloppy   |   9   ' | floors
selftest sloppy
assert_eq "a sloppily spaced floor is still read" 1 "$RC"
line="$(shortfall)"
assert_contains "space is trimmed and the commented-out floor ignored" \
  "did 3 units of work, below the floor of 9" "$line"

# ---------------------------------------------------------------------------
describe "AC-6/AC-7  the shipped floors file covers every suite, at its count"

# The real tree, not a fixture. AC-6 makes C-3's table exhaustive; AC-7's own
# control is that `profiles` is recorded at 44 and not at its 1 call site.
REAL="$REPO_ROOT/.claude/tests/floors.conf"

floor_of() { # <suite>   the value recorded for a suite, or empty
  sed -n "s/^[[:space:]]*floor[[:space:]]*|[[:space:]]*$1[[:space:]]*|[[:space:]]*\([0-9][0-9]*\).*/\1/p" \
    "$REAL" 2>/dev/null | head -1
}

missing=""
for s in "$REPO_ROOT"/.claude/tests/*.test.sh; do
  n="$(basename "$s" .test.sh)"
  [ -n "$(floor_of "$n")" ] || missing="$missing $n"
done
assert_eq "every suite in .claude/tests has a floor" "" "$missing"

# C-3's settled ten, read out. Not re-derived, not rounded, not calibrated.
# The last two were measured by RED against the unchanged tree (DV-3).
wrong=""
while read -r n v; do
  [ -z "$n" ] && continue
  got="$(floor_of "$n")"
  [ "$got" = "$v" ] || wrong="$wrong $n=${got:-<none>}(want $v)"
done <<'COUNTS'
new-story 22
ci-local 8
profiles 44
phase 24
settings 20
mutate 39
doctor 7
lib 148
gate-reminder 32
boundaries 26
gates 161
phase-guard 289
COUNTS
assert_eq "and each records the executed count MT-039 C-3 settled" "" "$wrong"

# Named individually, because these two are the reason AC-7 is a criterion
# rather than a note: a call-site implementation records 1 and 57.
assert_eq "profiles is floored at its 44 executed assertions, not its 1 call site" \
  44 "$(floor_of profiles)"
assert_eq "lib is floored at its 148 executed assertions, not its 57 call sites" \
  148 "$(floor_of lib)"

summary "selftest"
