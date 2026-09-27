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

# ===========================================================================
# MT-042  the runner runs its suites CONCURRENTLY
# ===========================================================================
#
# Everything below runs the fixture's copy of scripts/selftest.sh over PROBE
# suites: synthetic suites that sleep, print numbered lines while they sleep,
# and record what they observed into a marker directory ($MARKS) outside the
# fixture's .claude/tests. The markers are the structural evidence - which
# suites ran, how many were alive at once, which ones a suite saw beside it -
# so no assertion here is a wall-clock threshold. Timing only ever makes the
# evidence STRONGER (a slower machine overlaps more), never flips a verdict.
#
# The contract these pin is MT-042 C-2 and C-3 as amended in RED:
#   SELFTEST_JOBS         the job bound; unset or empty means 4; anything that
#                         is not a positive integer is refused, exit 1, before
#                         any suite runs.
#   SERIAL_SUITES=""      a line of scripts/selftest.sh, space-separated suite
#                         names; a suite named there runs with no other suite
#                         alive. Ships empty.
#   .claude/state/selftest/<name>.out
#                         each suite's output buffer, under the script's $ROOT,
#                         created if absent, no file left behind, pass or fail.

# The outer runner may have been started with a job bound of its own; the
# nested fixture runs below must see only the one each case sets.
unset SELFTEST_JOBS

MARKS="$FIX/marks"
cp "$FIX/scripts/selftest.sh" "$FIX/selftest.sh.as-copied"
restore_runner() { cp "$FIX/selftest.sh.as-copied" "$FIX/scripts/selftest.sh"; }
reset_marks() { rm -rf "$MARKS"; mkdir -p "$MARKS"; }

# probe_suite <name> <asserts> <steps> [pass|fail|silent]
#   A suite that, for each of <steps> steps, prints `<name> line <i>` and then
#   sleeps 0.3 s and counts the `running.*` markers alive. It records:
#     ran.<name>       it ran at all
#     buffered.<name>  its output buffer existed when it started (C-2)
#     peak.<name>      the most suites it saw alive at once, itself included
#     saw.<name>       every other suite it saw alive
#     verbose.<name>   VERBOSE reached it
#   Then it executes <asserts> passing assertions from ONE call site (MT-039's
#   shape), and - by mode - one failing assertion plus a stderr line, or no
#   summary line at all. Counting is pure bash: a fork per sample would cost
#   ~150 ms on Windows and blur the thing being sampled.
probe_suite() {
  local mode="${4:-pass}"
  {
    printf '#!/usr/bin/env bash\n'
    printf '. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"\n'
    printf "N='%s'; M='%s'; STEPS=%d; ASSERTS=%d\n" "$1" "$MARKS" "$3" "$2"
    cat <<'BODY'
: > "$M/running.$N"; : > "$M/ran.$N"
[ -f "${BASH_SOURCE[0]%/*}/../state/selftest/$N.out" ] && : > "$M/buffered.$N"
[ -n "${VERBOSE:-}" ] && : > "$M/verbose.$N"
peak=1; saw=""; i=1
while [ "$i" -le "$STEPS" ]; do
  printf '%s line %d\n' "$N" "$i"
  sleep 0.3
  c=0
  for f in "$M"/running.*; do
    [ -e "$f" ] || continue
    c=$((c+1)); o="${f##*/running.}"
    [ "$o" = "$N" ] && continue
    case " $saw " in *" $o "*) ;; *) saw="$saw $o" ;; esac
  done
  [ "$c" -gt "$peak" ] && peak=$c
  i=$((i+1))
done
printf '%s\n' "$peak" > "$M/peak.$N"
printf '%s\n' "${saw# }" > "$M/saw.$N"
rm -f "$M/running.$N"
j=0
while [ "$j" -lt "$ASSERTS" ]; do assert_eq "$N case $j" x x; j=$((j+1)); done
BODY
    case "$mode" in
      fail)
        printf 'printf "%%s-stderr\\n" "$N" >&2\n'
        printf 'assert_eq "$N is the one that is wrong" want got\n'
        printf 'summary "$N"\n' ;;
      silent)
        printf 'exit 0\n' ;;
      *)
        printf 'summary "$N"\n' ;;
    esac
  } > "$FIX/.claude/tests/$1.test.sh"
}

# peak_of <names...>   The highest concurrency any of the named suites saw.
peak_of() {
  local m=0 n v
  for n in "$@"; do
    v=""; [ -f "$MARKS/peak.$n" ] && read -r v < "$MARKS/peak.$n"
    [ -n "$v" ] && [ "$v" -gt "$m" ] && m=$v
  done
  printf '%s' "$m"
}

# ran_list <names...>   Which of the named suites left a ran.* marker.
ran_list() {
  local n r=""
  for n in "$@"; do [ -e "$MARKS/ran.$n" ] && r="$r $n"; done
  printf '%s' "${r# }"
}

# transcript <output>   Every `=== <name> ===` header as `H <name>` and every
# probe line as `<name> <i>`, in the order printed. Two suites interleaved, a
# line under the wrong header, or suites out of glob order all change it.
transcript() {
  printf '%s\n' "$1" | awk '
    /^=== [^ ]+ ===$/        { print "H " $2; next }
    /^[a-z]+ line [0-9]+$/   { print $1 " " $3 }'
}

# expect_transcript <name>:<steps> ...   The transcript of those suites run in
# that order, each contiguous.
expect_transcript() {
  local spec n s i
  for spec in "$@"; do
    n="${spec%%:*}"; s="${spec#*:}"
    printf 'H %s\n' "$n"
    i=1; while [ "$i" -le "$s" ]; do printf '%s %d\n' "$n" "$i"; i=$((i+1)); done
  done
}

# block <name>   The lines under suite <name>'s header, up to the next header.
block() {
  printf '%s\n' "$out" | awk -v h="=== $1 ===" '
    $0 == h { on = 1; next } /^=== [^ ]+ ===$/ { on = 0 } on'
}

headers() { printf '%s\n' "$out" | grep -E '^=== [^ ]+ ===$'; }
last_line() { printf '%s\n' "$out" | awk 'NF { l = $0 } END { print l }'; }
leftover_buffers() {
  [ -d "$FIX/.claude/state/selftest" ] || return 0
  find "$FIX/.claude/state/selftest" -type f | sed "s|^$FIX/||"
}

# ---------------------------------------------------------------------------
describe "MT-042 controls  the instruments below measure what they claim to"

# The concurrency probe, driven WITHOUT the runner: two probe suites started
# side by side by hand must see each other, and one alone must see only itself.
# Without this pair a peak of 1 could mean "the runner is serial" or "the probe
# cannot count", and every concurrency verdict below would be ambiguous.
reset_suites; reset_marks
probe_suite alpha 1 4
probe_suite bravo 1 4
( cd "$FIX" && { bash .claude/tests/alpha.test.sh >/dev/null 2>&1 &
                 bash .claude/tests/bravo.test.sh >/dev/null 2>&1 & wait; } )
assert_eq "two probe suites started side by side see a peak of 2" 2 "$(peak_of alpha bravo)"
assert_eq "and each names the other" "bravo alpha" \
  "$(cat "$MARKS/saw.alpha") $(cat "$MARKS/saw.bravo")"
reset_marks
( cd "$FIX" && bash .claude/tests/alpha.test.sh >/dev/null 2>&1 )
assert_eq "one probe suite alone sees a peak of 1" 1 "$(peak_of alpha)"
assert_eq "and sees nobody beside it" "" "$(cat "$MARKS/saw.alpha")"

# The transcript instrument, on text: interleaving and misordering must both
# change it, or the AC-4 comparison below proves nothing.
good="$(printf '\n=== aa ===\naa line 1\naa line 2\n\n=== bb ===\nbb line 1\n')"
mixed="$(printf '\n=== aa ===\naa line 1\nbb line 1\naa line 2\n\n=== bb ===\n')"
swapped="$(printf '\n=== bb ===\nbb line 1\n\n=== aa ===\naa line 1\naa line 2\n')"
want="$(expect_transcript aa:2 bb:1)"
assert_eq "the transcript of contiguous, ordered output is the expected one" \
  "$want" "$(transcript "$good")"
assert_not_contains "an interleaved line changes the transcript" \
  "$want" "$(transcript "$mixed")"
assert_not_contains "and so does a swapped suite order" \
  "$want" "$(transcript "$swapped")"

# ---------------------------------------------------------------------------
describe "MT-042 AC-2  an early suite that fails FIRST still fails the whole run"

# The classic bug, in the shape that exposes it: the failing suite is first in
# glob order and finishes first, and every suite after it passes and runs
# longer. A runner that reports the last job's status, or reads a bare
# `wait`'s $?, exits 0 here.
reset_suites; reset_marks
probe_suite alpha 2 0 fail
probe_suite bravo 3 3
probe_suite charlie 4 5
floors <<'FLOORS'
floor | alpha   | 2
floor | bravo   | 3
floor | charlie | 4
FLOORS
selftest
assert_eq "the run exits non-zero" 1 "$RC"
assert_eq "and its last line is the shipped FAILED count" \
  "1 of 3 harness suite(s) FAILED." "$(last_line)"
a="$(block alpha)"
assert_contains "the failing suite's failure is shown under its own header" \
  "FAIL alpha is the one that is wrong" "$a"
assert_contains "with the detail under it" "expected: want" "$a"
assert_contains "and its stderr too, in full" "alpha-stderr" "$a"
assert_contains "and its own summary line" "alpha: 2 passed, 1 failed" "$a"
assert_not_contains "the run does not also claim success" "harness suite(s) passed." "$out"

# Two failures, not adjacent, both before a passing suite: the count must be 2
# of 5, not 1 (a status overwritten by the next job) and not 0.
reset_suites; reset_marks
probe_suite alpha   1 3
probe_suite bravo   1 0 fail
probe_suite charlie 1 3
probe_suite delta   1 1 fail
probe_suite echo    1 2
floors <<'FLOORS'
floor | alpha   | 1
floor | bravo   | 1
floor | charlie | 1
floor | delta   | 1
floor | echo    | 1
FLOORS
selftest
assert_eq "two non-adjacent failures exit non-zero" 1 "$RC"
assert_eq "and are counted as two of five" \
  "2 of 5 harness suite(s) FAILED." "$(last_line)"

# ---------------------------------------------------------------------------
describe "MT-042 AC-3  the interface is unchanged"

# Exactly one suite: one header, and the markers prove the others never ran -
# not merely that their output was not printed.
reset_suites; reset_marks
probe_suite alpha   1 0
probe_suite bravo   1 0
probe_suite charlie 1 0
floors <<'FLOORS'
floor | alpha   | 1
floor | bravo   | 1
floor | charlie | 1
FLOORS
selftest bravo
assert_eq "a named suite runs and passes" 0 "$RC"
assert_eq "exactly one header is printed, and it is that suite's" "=== bravo ===" "$(headers)"
assert_eq "and no other suite ran at all" "bravo" "$(ran_list alpha bravo charlie)"
assert_eq "and the run reports one suite passed" "1 harness suite(s) passed." "$(last_line)"

# No such suite: the shipped message, on stderr, exit 1, nothing run.
reset_marks
err="$( cd "$FIX" && bash scripts/selftest.sh nosuchsuite 2>&1 >/dev/null )"; rc=$?
assert_eq "an unknown suite exits 1" 1 "$rc"
assert_eq "with the shipped message, on stderr" \
  "No suites matched 'nosuchsuite'. Looked in .claude/tests/*.test.sh" "$err"
assert_eq "and runs nothing" "" "$(ran_list alpha bravo charlie)"

# VERBOSE reaches every suite on a FULL run - the concurrent path - and its
# absence reaches them too: the negative control, so a probe that always writes
# the marker cannot pass this.
reset_marks
VERBOSE=1 selftest
assert_eq "a full VERBOSE run exits 0" 0 "$RC"
assert_eq "VERBOSE reached every suite" "alpha bravo charlie" \
  "$(for n in alpha bravo charlie; do [ -e "$MARKS/verbose.$n" ] && printf '%s ' "$n"; done | sed 's/ $//')"
assert_contains "and every suite names its passing assertions" "ok   alpha case 0" "$(block alpha)"
assert_contains "under its own header" "ok   charlie case 0" "$(block charlie)"
assert_eq "a full passing run ends with the shipped passed line" \
  "3 harness suite(s) passed." "$(last_line)"
reset_marks
VERBOSE= selftest
assert_eq "without VERBOSE no suite sees it" "" \
  "$(for n in alpha bravo charlie; do [ -e "$MARKS/verbose.$n" ] && printf '%s ' "$n"; done)"
assert_not_contains "and no passing assertion is named" "ok   alpha case 0" "$out"

# ---------------------------------------------------------------------------
describe "MT-042 AC-4  suites print contiguously, in glob order, whatever order they finish in"

# alpha is first in the glob and takes longest; charlie is last and finishes
# first. Each prints numbered lines WHILE the others are running, so a runner
# that streams interleaves them and a runner that prints on completion prints
# charlie first. Both change the transcript.
reset_suites; reset_marks
probe_suite alpha   3 5
probe_suite bravo   5 2
probe_suite charlie 8 1
floors <<'FLOORS'
floor | alpha   | 3
floor | bravo   | 4
floor | charlie | 7
FLOORS
selftest
assert_eq "the run passes" 0 "$RC"
assert_eq "each suite's lines sit contiguously under its own header, in glob order" \
  "$(expect_transcript alpha:5 bravo:2 charlie:1)" "$(transcript "$out")"
# AC-6 rides on the same run: distinct counts and floors per suite, so a count
# read from the wrong buffer changes a total.
assert_contains "and every count was read from its own suite" \
  "assertion floors: all 3 suite(s) met their declared floor (16 assertions executed, 14 declared)." "$out"

# ---------------------------------------------------------------------------
describe "MT-042 AC-6  each suite's floor is read from its own output"

# bravo is below its floor and finishes first; alpha and charlie are above
# theirs and finish later. Exactly one shortfall line, naming bravo, with
# bravo's numbers.
reset_suites; reset_marks
probe_suite alpha   5 5
probe_suite bravo   4 0
probe_suite charlie 9 2
floors <<'FLOORS'
floor | alpha   | 3
floor | bravo   | 6
floor | charlie | 8
FLOORS
selftest
assert_eq "a suite below its floor fails the run beside passing neighbours" 1 "$RC"
assert_eq "exactly one shortfall is reported, and it is bravo's, with bravo's numbers" \
  "FAIL bravo  did 4 units of work, below the floor of 6 in .claude/tests/floors.conf" \
  "$(printf '%s\n' "$out" | grep -F 'below the floor')"
assert_contains "the floors line counts the other two as met" \
  "assertion floors: 2 of 3 suite(s) met their declared floor." "$out"
assert_eq "and the run ends with one failed suite" \
  "1 of 3 harness suite(s) FAILED." "$(last_line)"

# A suite with no summary line, between two slower passing ones.
reset_suites; reset_marks
probe_suite alpha  2 4
probe_suite bravo  3 0 silent
probe_suite charlie 2 3
floors <<'FLOORS'
floor | alpha   | 2
floor | bravo   | 7
floor | charlie | 2
FLOORS
selftest
assert_eq "a silent suite fails the run under concurrency too" 1 "$RC"
assert_eq "and it alone is named as having printed no summary" \
  "FAIL bravo  printed no summary line, so its floor of 7 could not be checked" \
  "$(printf '%s\n' "$out" | grep -F 'printed no summary line')"
assert_eq "the run ends with one failed suite" \
  "1 of 3 harness suite(s) FAILED." "$(last_line)"

# ---------------------------------------------------------------------------
describe "MT-042 C-2  suites actually run concurrently, and never more than the bound"

# Four suites, a bound of two. The peak must be EXACTLY two: above it is an
# unbounded runner, below it is a serial one. This is the fixture-level proxy
# for AC-1, which cannot hold unless this does.
reset_suites; reset_marks
for n in alpha bravo charlie delta; do probe_suite "$n" 1 3; done
floors <<'FLOORS'
floor | alpha   | 1
floor | bravo   | 1
floor | charlie | 1
floor | delta   | 1
FLOORS
SELFTEST_JOBS=2 selftest
assert_eq "SELFTEST_JOBS=2 passes" 0 "$RC"
assert_eq "and runs exactly two suites at a time" 2 "$(peak_of alpha bravo charlie delta)"

# The default bound is 4: five suites, and the peak is 3 or 4 - more than a
# bound of 2 could produce, and never the 5 an nproc- or unbounded runner would.
reset_suites; reset_marks
for n in alpha bravo charlie delta echo; do probe_suite "$n" 1 4; done
floors <<'FLOORS'
floor | alpha   | 1
floor | bravo   | 1
floor | charlie | 1
floor | delta   | 1
floor | echo    | 1
FLOORS
selftest
assert_eq "the default run passes" 0 "$RC"
p="$(peak_of alpha bravo charlie delta echo)"
if [ "$p" -ge 3 ] && [ "$p" -le 4 ]; then
  _ok "with no SELFTEST_JOBS, at least 3 and at most 4 suites run at once"
else
  _bad "with no SELFTEST_JOBS, at least 3 and at most 4 suites run at once" "peak observed: $p"
fi

# SELFTEST_JOBS=1 is the serial runner, and the negative control for the peak
# counter under the runner: it must not over-count.
reset_suites; reset_marks
for n in alpha bravo charlie; do probe_suite "$n" 1 3; done
floors <<'FLOORS'
floor | alpha   | 1
floor | bravo   | 1
floor | charlie | 1
FLOORS
SELFTEST_JOBS=1 selftest
assert_eq "SELFTEST_JOBS=1 passes" 0 "$RC"
assert_eq "and runs one suite at a time" 1 "$(peak_of alpha bravo charlie)"

# A bound of zero would never start anything; a word is a typo. Both are
# refused before any suite runs, never read as "the default". The suites take
# no steps: a runner that ignores the bound should not cost seconds to catch.
for n in alpha bravo charlie; do probe_suite "$n" 1 0; done
for bad in 0 lots; do
  reset_marks
  SELFTEST_JOBS="$bad" selftest
  assert_eq "SELFTEST_JOBS=$bad is refused with exit 1" 1 "$RC"
  assert_contains "and the refusal names the variable" "SELFTEST_JOBS" "$out"
  assert_eq "and no suite ran" "" "$(ran_list alpha bravo charlie)"
done

# ---------------------------------------------------------------------------
describe "MT-042 C-2  output buffers live under the script's own .claude/state, and are cleaned up"

# Run from a SUBDIRECTORY of the fixture with no .claude/state at all: a
# buffer resolved from $PWD lands in src/.claude, and one that assumes the
# directory exists fails to write.
reset_suites; reset_marks
probe_suite alpha 1 1
probe_suite bravo 1 1
floors <<'FLOORS'
floor | alpha | 1
floor | bravo | 1
FLOORS
rm -rf "$FIX/.claude/state" "$FIX/src/.claude"
out="$( cd "$FIX/src" && bash ../scripts/selftest.sh 2>&1 )"; RC=$?
assert_eq "a run from a subdirectory, with no state directory, passes" 0 "$RC"
assert_eq "each suite's output went to .claude/state/selftest/<name>.out under the script's root" \
  "alpha bravo" "$(for n in alpha bravo; do [ -e "$MARKS/buffered.$n" ] && printf '%s ' "$n"; done | sed 's/ $//')"
assert_eq "nothing was written relative to the working directory" "" \
  "$( [ -e "$FIX/src/.claude" ] && echo "src/.claude exists" )"
assert_eq "and no buffer outlives a passing run" "" "$(leftover_buffers)"

reset_marks
probe_suite bravo 1 1 fail
selftest
assert_eq "a failing run fails" 1 "$RC"
assert_eq "and still used the buffers" "alpha bravo" \
  "$(for n in alpha bravo; do [ -e "$MARKS/buffered.$n" ] && printf '%s ' "$n"; done | sed 's/ $//')"
assert_eq "and no buffer outlives a failing run either" "" "$(leftover_buffers)"
mkdir -p "$FIX/.claude/state"

# ---------------------------------------------------------------------------
describe "MT-042 C-2  the runner stays within bash 3.2"

# macOS ships bash 3.2.57. Job control is where bash 4+ features are most
# tempting: `wait -n` (4.3), `wait -p` (5.1), associative arrays, mapfile.
# Read from the code, because nothing here can run the other bash. Comments may
# mention them; code may not.
bash4() {
  grep -nE '(wait[[:space:]]+-[np]|(declare|local|typeset)[[:space:]]+-[A-Za-z]*A|\bmapfile\b|\breadarray\b|\bcoproc\b|BASHPID|EPOCHREALTIME|EPOCHSECONDS)' "$1" \
    | grep -vE '^[0-9]+:[[:space:]]*#' || true
}
printf '# wait -n is bash 4.3\nwait -n\ndeclare -A seen\n' > "$FIX/bash4-sample.sh"
assert_eq "control: the check finds bash-4 job control in code, not in comments" \
  "2:wait -n
3:declare -A seen" "$(bash4 "$FIX/bash4-sample.sh")"
assert_eq "scripts/selftest.sh uses no bash-4 feature" "" "$(bash4 "$REPO_ROOT/scripts/selftest.sh")"

# ---------------------------------------------------------------------------
describe "MT-042 C-3  the serial escape hatch ships, empty, and works"

assert_eq "scripts/selftest.sh carries the list, and it ships empty" \
  'SERIAL_SUITES=""' "$(grep -E '^SERIAL_SUITES=' "$REPO_ROOT/scripts/selftest.sh")"

# Pin bravo and delta in the fixture's copy. Six suites, a bound of 4: the
# unpinned ones must overlap each other (or the runner is merely serial and the
# rest proves nothing), and neither pinned suite may see anyone beside it, nor
# be seen. delta is also below its floor: a pinned suite's floor is still read.
reset_suites; reset_marks
for n in alpha bravo charlie delta echo foxtrot; do probe_suite "$n" 2 3; done
probe_suite delta 1 3
floors <<'FLOORS'
floor | alpha   | 2
floor | bravo   | 2
floor | charlie | 2
floor | delta   | 2
floor | echo    | 2
floor | foxtrot | 2
FLOORS
sed 's/^SERIAL_SUITES=""$/SERIAL_SUITES="bravo delta"/' "$FIX/scripts/selftest.sh" > "$FIX/selftest.sh.pinned"
cp "$FIX/selftest.sh.pinned" "$FIX/scripts/selftest.sh"
assert_eq "the fixture's runner now pins bravo and delta" \
  'SERIAL_SUITES="bravo delta"' "$(grep -E '^SERIAL_SUITES=' "$FIX/scripts/selftest.sh")"
SELFTEST_JOBS=4 selftest
restore_runner
assert_eq "the pinned run fails, because delta is below its floor" 1 "$RC"
assert_eq "and delta, pinned, is the suite named short" \
  "FAIL delta  did 1 units of work, below the floor of 2 in .claude/tests/floors.conf" \
  "$(printf '%s\n' "$out" | grep -F 'below the floor')"
p="$(peak_of alpha charlie echo foxtrot)"
if [ "$p" -ge 2 ]; then _ok "the unpinned suites still ran concurrently"
else _bad "the unpinned suites still ran concurrently" "peak observed among them: $p"; fi
assert_eq "bravo, pinned, saw no other suite alive" "" "$(cat "$MARKS/saw.bravo" 2>/dev/null)"
assert_eq "delta, pinned, saw no other suite alive" "" "$(cat "$MARKS/saw.delta" 2>/dev/null)"
seen=""
for n in alpha charlie echo foxtrot; do
  case " $(cat "$MARKS/saw.$n" 2>/dev/null) " in
    *" bravo "*|*" delta "*) seen="$seen $n" ;;
  esac
done
assert_eq "and no unpinned suite saw a pinned one" "" "$seen"
assert_eq "pinned suites still print in glob order" \
  "=== alpha ===
=== bravo ===
=== charlie ===
=== delta ===
=== echo ===
=== foxtrot ===" "$(headers)"

summary "selftest"
