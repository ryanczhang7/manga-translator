#!/usr/bin/env bash
# Tests for scripts/selftest.sh's ASSERTION FLOORS.
#
# PORTED FROM A CONSUMING PROJECT, manga-translator's MT-039, which built this
# and shipped it downstream while upstream had nothing like it. It came back
# because a refresh would have deleted it: `scripts/selftest.sh` and
# `.claude/tests/_lib.sh` are REPLACED by refresh-harness.sh while
# `floors.conf` and this suite are KEPT, so the implementation would have gone
# and its configuration and tests would have stayed - the H26 shape the refresh
# script's own header warns about. Ported rather than overwritten.
#
# The problem it solves: selftest.sh runs each harness suite and reads its exit
# status and nothing else. A suite that executed zero assertions exits 0; a
# suite replaced by a single `printf` exits 0. So each suite declares in
# .claude/tests/floors.conf how much work it is worth, and a suite that does
# less fails the run even when it exits 0. It is the `evidence`/`floor` idea
# project.conf already applies to GATES, turned on the harness's own tests.
#
# Two things about this file are worth knowing before changing it.
#
# 1. The floor is the EXECUTED assertion count - the `N` of summary()'s
#    `<name>: N passed, M failed` line - and not the number of `assert_` call
#    sites in the source. They are different numbers, and measured on THIS
#    tree rather than inherited: `profiles` is ONE call site inside a loop and
#    37 executed assertions; `lib` is 50 call sites and 139. A call-site floor
#    for `profiles` would be 1, and deleting 36 of its 37 assertions would
#    satisfy it. Every fixture suite below is generated in that same shape -
#    one call site, a loop - so the distinction is live in every case rather
#    than argued about in a comment.
#
# 2. Every fixture runs against a THROWAWAY tree, never this checkout. The
#    fixture gets its own .claude/tests with its own suites and its own
#    floors.conf, so nothing here depends on - or disturbs - the real suites
#    whose counts the shipped floors.conf records.
#
# The one real-tree assertion block reads .claude/tests/floors.conf itself and
# checks it against the counts measured from a full run of this repository.
# Those are read out, not re-derived.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
# HARNESS-036: the cases at the end background selftest.sh runs whose suites
# hold on files. On any exit, release every hold and wait every background run
# (each hold is bounded, so the wait is too) before the fixture is removed.
BG=""
selftest_cleanup() {
  local p
  mkdir -p "$FIX/mk/release" 2>/dev/null && : > "$FIX/mk/release/all"
  for p in $BG; do wait "$p" 2>/dev/null; done
  rm -rf "$FIX"
}
trap selftest_cleanup EXIT

mkdir -p "$FIX/.claude/tests"
# The REAL _lib.sh, for the same reason make_fixture copies the real paths.conf:
# the summary() format string this story reads is the one the repository ships.
cp "$REPO_ROOT/.claude/tests/_lib.sh" "$FIX/.claude/tests/_lib.sh"

# --- fixture helpers ---------------------------------------------------------

# reset_suites   Empties the fixture's test directory and BOTH floors files.
# HARNESS-020 added project-floors.conf; a block that writes one and a later
# block that assumes it absent would otherwise be coupled through the fixture.
reset_suites() {
  rm -f "$FIX"/.claude/tests/*.test.sh "$FIX/.claude/tests/floors.conf" \
        "$FIX/.claude/tests/project-floors.conf"
}

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
#
# ONE awk over a here-string, not `grep | head -1`. The ported original was
# `printf | grep -F | head -1`, and check-sigpipe.sh flagged it on arrival:
# `head` exits on its first line, the writer upstream takes SIGPIPE and dies
# 141, and under `pipefail` that corpse becomes the status. Fixed here rather
# than waived - the guard was right, and the downstream copy it came from has
# the same latent defect because its own guard predates the rule.
shortfall() {
  awk 'index($0, "below the floor") { print; exit }' <<SHORTFALL_OUT
$out
SHORTFALL_OUT
}

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

# One awk over the file, for the same reason as shortfall() above: `sed | head -1`
# is a pipeline into an early-exit reader, and check-sigpipe.sh flagged it.
floor_of() { # <suite> <file>   the value recorded for a suite in <file>, or empty
  awk -v want="$1" '
    { line = $0; sub(/#.*/, "", line) }
    { n = split(line, f, "|") }
    n < 3 { next }
    { for (i = 1; i <= n; i++) { gsub(/^[ \t]+|[ \t]+$/, "", f[i]) } }
    f[1] == "floor" && f[2] == want && f[3] ~ /^[0-9]+$/ { print f[3]; exit }
  ' "$2" 2>/dev/null
}

# suites_without_floor <root>   The space-joined names of the suites in
# <root>/.claude/tests/*.test.sh that have a floor line in neither
# <root>/.claude/tests/floors.conf nor, when it exists,
# <root>/.claude/tests/project-floors.conf. Empty when every suite is floored.
# HARNESS-021: this loop used to read floors.conf only, so every consuming
# project that floors its project-*.test.sh suites in project-floors.conf (as
# HARNESS-020 designed) failed the assertion below. Taking a root is what lets
# the fixture cases further down point it at a tree that is not this one.
suites_without_floor() {
  _swf_dir="$1/.claude/tests"
  _swf_missing=""
  for _swf_s in "$_swf_dir"/*.test.sh; do
    [ -e "$_swf_s" ] || continue
    _swf_n="$(basename "$_swf_s" .test.sh)"
    [ -n "$(floor_of "$_swf_n" "$_swf_dir/floors.conf")" ] && continue
    if [ -f "$_swf_dir/project-floors.conf" ]; then
      [ -n "$(floor_of "$_swf_n" "$_swf_dir/project-floors.conf")" ] && continue
    fi
    _swf_missing="$_swf_missing $_swf_n"
  done
  printf '%s' "${_swf_missing# }"
}

assert_eq "every suite in .claude/tests has a floor" "" "$(suites_without_floor "$REPO_ROOT")"

# HARNESS-021 fixture cases for suites_without_floor. Each root is a throwaway
# directory under $FIX holding only the .claude/tests files the helper reads:
# empty suite files (it reads names, not contents) and the floors files. Every
# needle is the helper's WHOLE output compared with assert_eq, so a helper that
# reports nothing, or reports the right name among wrong ones, cannot pass.

# floor_root <case> <suite>...   A fresh root with an empty <suite>.test.sh for
# each name. Prints the root. floors.conf / project-floors.conf are written by
# the caller, so "absent" is a case and not an accident.
floor_root() {
  _fr="$FIX/floor-roots/$1"; shift
  rm -rf "$_fr"; mkdir -p "$_fr/.claude/tests"
  for _fr_s in "$@"; do : > "$_fr/.claude/tests/$_fr_s.test.sh"; done
  printf '%s' "$_fr"
}

describe "HARNESS-021 AC-1  a suite floored only in project-floors.conf is not reported missing"

R="$(floor_root ac1 alpha project-mine)"
printf 'floor | alpha | 3\n' > "$R/.claude/tests/floors.conf"
printf '# a project'"'"'s own suites\nfloor | project-mine | 4\n' > "$R/.claude/tests/project-floors.conf"
assert_eq "a suite floored in project-floors.conf alone is not reported as missing a floor" \
  "" "$(suites_without_floor "$R")"
# The same, beside an unfloored suite: the project floor excuses project-mine
# and nothing else, so the output is exactly the orphan.
R="$(floor_root ac1b alpha project-mine project-orphan)"
printf 'floor | alpha | 3\n' > "$R/.claude/tests/floors.conf"
printf 'floor | project-mine | 4\n' > "$R/.claude/tests/project-floors.conf"
assert_eq "beside an unfloored suite, only the unfloored one is reported" \
  "project-orphan" "$(suites_without_floor "$R")"

describe "HARNESS-021 AC-2  control: a suite floored in neither file is reported, by name"

# Without this, a helper that reports nothing satisfies AC-1. A project-floors.conf
# EXISTS here (comment only), so this also refuses a helper that treats the
# file's mere presence as excusing every suite. Green under the old and the new
# helper alike - it is the control, not the change.
R="$(floor_root ac2 alpha project-orphan)"
printf 'floor | alpha | 3\n' > "$R/.claude/tests/floors.conf"
printf '# a project file that floors nothing\n' > "$R/.claude/tests/project-floors.conf"
assert_eq "a suite floored in neither file is reported, and only that suite" \
  "project-orphan" "$(suites_without_floor "$R")"

describe "HARNESS-021 AC-3  with no project-floors.conf the check behaves as before"

R="$(floor_root ac3 alpha beta gamma)"
printf 'floor | alpha | 3\nfloor | gamma | 1\n' > "$R/.claude/tests/floors.conf"
assert_eq "with no project-floors.conf, a suite missing from floors.conf is reported" \
  "beta" "$(suites_without_floor "$R")"
# Two missing, to pin the space-joined shape the real-tree message prints.
R="$(floor_root ac3b alpha beta gamma)"
printf 'floor | alpha | 3\n' > "$R/.claude/tests/floors.conf"
assert_eq "and several missing suites are reported space-joined, in name order" \
  "beta gamma" "$(suites_without_floor "$R")"
# AC-3's second half - this repository's real tree still passes - is the
# real-tree assertion above. Deliberately NOT asserted: that the real tree has
# no project-floors.conf. This file is copied into consuming projects, which
# do ship one, and there that assertion would be the defect this story removes.

# The counts measured from a full run of THIS repository, read out rather than
# re-derived. MT's numbers were deliberately NOT inherited: its suite set is a
# different one, and a floor copied from another tree is a floor nobody
# measured - which is the exact defect this mechanism exists to catch, pointed
# at itself. Confirmed against the CI run of the same tree, and three of them
# (profiles, mutate, lib) re-run locally at the port.
wrong=""
while read -r n v; do
  [ -z "$n" ] && continue
  got="$(floor_of "$n" "$REAL")"
  [ "$got" = "$v" ] || wrong="$wrong $n=${got:-<none>}(want $v)"
done <<'COUNTS'
boundaries 113
ci-local 28
classify 55
doctor 50
gate-reminder 32
gates 470
grep-count 20
lib 217
mutate 189
new-story 43
phase 33
phase-guard 310
plan 42
policy 17
procedure 37
profiles 50
refresh 122
reporting 27
run-lock 140
selftest 268
settings 27
sigpipe 82
spawns 69
worktree 73
COUNTS
assert_eq "and each records the executed count measured on this tree" "" "$wrong"

# Named individually, because these two are the reason AC-7 is a criterion
# rather than a note: a call-site implementation records 1 and 104. HARNESS-010
# moved lib from 139 to 197 and phase-guard from 188 to 288 - both floors are
# recorded in RED, so both suites sit BELOW them until the reconciled parser
# lands. See the note at the foot of floors.conf.
assert_eq "profiles is floored at its 50 executed assertions, not its call-site count" \
  50 "$(floor_of profiles "$REAL")"
assert_eq "lib is floored at its 217 executed assertions, not its call-site count" \
  217 "$(floor_of lib "$REAL")"

# ===========================================================================
# HARNESS-020: a project declares its own suites' floors in
# .claude/tests/project-floors.conf, which upstream never ships and the refresh
# keeps. Every needle below is a WHOLE LINE of selftest.sh's output, compared
# with `grep -cxF`, because the fault strings are mechanical (the story's
# Contract pins them byte for byte) and a floating substring is satisfied by
# the wrong file's name in the right sentence.
# ===========================================================================

# project_floors   project-floors.conf body on stdin.
project_floors() { cat > "$FIX/.claude/tests/project-floors.conf"; }

# exact_lines <line>   How many lines of the last run's output are EXACTLY
# <line>. A here-doc rather than a pipe, for check-sigpipe.sh; no `|| echo 0`
# fallback, for check-grep-count.sh - grep -c already prints 0.
exact_lines() {
  grep -cxF -- "$1" <<EXACT_OUT
$out
EXACT_OUT
}

PF=".claude/tests/project-floors.conf"
MISSING_TAIL="no floor line in .claude/tests/floors.conf or .claude/tests/project-floors.conf; every suite must declare one (a project's own suites go in project-floors.conf)"

# ---------------------------------------------------------------------------
describe "HARNESS-020 AC-1  a suite floored only in project-floors.conf passes the full-run audit"

# alpha is upstream's (floors.conf), project-mine is the project's own. The
# full run is the one CI invokes, and the one FWB's refresh broke.
reset_suites
passing_suite alpha 3
passing_suite project-mine 4
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
# a project's own suites
floor | project-mine | 4
FLOORS
selftest
assert_eq "a full run with a project-floored suite exits 0" 0 "$RC"
assert_eq "and says both suites passed" 1 "$(exact_lines "2 harness suite(s) passed.")"
assert_eq "and counts both floors as met, the project's included" 1 \
  "$(exact_lines "assertion floors: all 2 suite(s) met their declared floor (7 assertions executed, 7 declared).")"
# Prefix, not the new whole line: this must fail under the OLD wording too.
assert_eq "and the project suite is not reported as missing a floor" 0 \
  "$(printf '%s\n' "$out" | grep -c '^FAIL project-mine  no floor line')"
assert_not_contains "and no fault of any kind is printed" "FAIL" "$out"

describe "HARNESS-020 AC-1  and that floor is enforced, not merely accepted"

# The same declaration with the suite one assertion short. An implementation
# that satisfies the audit by treating project-floors.conf as "these suites
# need no floor" passes the block above and dies here.
reset_suites
passing_suite alpha 3
passing_suite project-mine 3
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
floor | project-mine | 4
FLOORS
selftest
assert_eq "a project suite below its project floor fails the full run" 1 "$RC"
# Contract amendment (RED): the shortfall names the file the floor came FROM.
# Saying `in .claude/tests/floors.conf` here would send the reader to edit the
# upstream file the refresh wipes - the very defect this story removes.
assert_eq "the shortfall names the suite, both numbers and project-floors.conf" 1 \
  "$(exact_lines "FAIL project-mine  did 3 units of work, below the floor of 4 in $PF")"
assert_eq "while upstream's suite, which met its floor, is not blamed" 0 \
  "$(printf '%s\n' "$out" | grep -c '^FAIL alpha ')"
assert_not_contains "and the run does not also claim everything passed" \
  "harness suite(s) passed." "$out"

describe "HARNESS-020 AC-1  a floors.conf floor's shortfall still names floors.conf"

# The control for the amendment above: the file a floor came from is reported
# per floor, not swapped wholesale for the new name.
reset_suites
passing_suite alpha 2
passing_suite project-mine 4
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
floor | project-mine | 4
FLOORS
selftest
assert_eq "an upstream suite below its floor fails the full run" 1 "$RC"
assert_eq "and its shortfall line names floors.conf, byte for byte as before" 1 \
  "$(exact_lines "FAIL alpha  did 2 units of work, below the floor of 3 in .claude/tests/floors.conf")"

# ---------------------------------------------------------------------------
describe "HARNESS-020 AC-2  a suite floored in neither file names both files"

# No project-floors.conf at all: exactly the tree FWB had after the refresh,
# and the case where the old message pointed only at the upstream file.
reset_suites
passing_suite alpha 3
passing_suite project-orphan 5
floors <<'FLOORS'
floor | alpha | 3
FLOORS
selftest
assert_eq "an unfloored suite fails the full run" 1 "$RC"
assert_eq "the fault names both files and where a project's own floor belongs" 1 \
  "$(exact_lines "FAIL project-orphan  $MISSING_TAIL")"
assert_eq "the old one-file wording is gone" 0 \
  "$(exact_lines "FAIL project-orphan  no floor line in .claude/tests/floors.conf; every suite must declare one")"

# The same with a project-floors.conf present that floors something else: the
# message does not depend on whether the project file exists.
reset_suites
passing_suite alpha 3
passing_suite project-mine 2
passing_suite project-orphan 5
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
floor | project-mine | 2
FLOORS
selftest
assert_eq "with a project file present, an unfloored suite still fails" 1 "$RC"
assert_eq "and the fault names both files, the same words" 1 \
  "$(exact_lines "FAIL project-orphan  $MISSING_TAIL")"
assert_eq "and only the unfloored suite is named" 1 \
  "$(printf '%s\n' "$out" | grep -c '^FAIL ')"

# ---------------------------------------------------------------------------
describe "HARNESS-020 AC-3  a project-floors.conf fault is named, with its file, line and fault"

# Each fault on a line number that a count of PARSED lines would get wrong: a
# comment and a blank line come first.

# (a) malformed line.
reset_suites
passing_suite alpha 3
passing_suite project-mine 4
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
# a comment, and a blank line, before the fault

floor | project-mine | 4
this is not a floor
FLOORS
selftest
assert_eq "a malformed project-floors.conf line fails the full run" 1 "$RC"
assert_eq "named with project-floors.conf, line 4, and the fault" 1 \
  "$(exact_lines "FAIL $PF:4  is not a floor line: 'this is not a floor'")"

# (b) a floor naming a suite that does not exist.
reset_suites
passing_suite alpha 3
passing_suite project-mine 4
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
# the fault is on line 3

floor | project-ghost | 12
floor | project-mine | 4
FLOORS
selftest
assert_eq "a project floor naming a missing suite fails the full run" 1 "$RC"
assert_eq "named with project-floors.conf, line 3, the suite, and the missing file" 1 \
  "$(exact_lines "FAIL $PF:3  floor names 'project-ghost', but .claude/tests/project-ghost.test.sh does not exist")"

# (c) a suite floored in BOTH files. Without this, a project could quietly
# lower an upstream suite's floor from the file the refresh never replaces.
reset_suites
passing_suite alpha 3
passing_suite project-mine 4
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
floor | project-mine | 4
floor | alpha | 1
FLOORS
selftest
assert_eq "a suite floored in both files fails the full run" 1 "$RC"
assert_eq "named against project-floors.conf's line 2, naming floors.conf" 1 \
  "$(exact_lines "FAIL $PF:2  floor for 'alpha' is already declared in .claude/tests/floors.conf; a suite has one floor")"
assert_eq "and the floors.conf line is not the one blamed" 0 \
  "$(printf '%s\n' "$out" | grep -c '^FAIL \.claude/tests/floors\.conf')"

# (d) the remaining two faults of the shared grammar, against the project file.
reset_suites
passing_suite alpha 3
passing_suite project-mine 4
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
# two faults
flor | project-mine | 4
floor | project-mine | lots
FLOORS
selftest
assert_eq "a non-numeric or unknown-kind project floor fails the full run" 1 "$RC"
assert_eq "an unknown kind is named with project-floors.conf and its line" 1 \
  "$(exact_lines "FAIL $PF:2  unknown kind 'flor'; the only kind is 'floor'")"
assert_eq "a non-number is named with project-floors.conf and its line" 1 \
  "$(exact_lines "FAIL $PF:3  floor for 'project-mine' is not a number: 'lots'")"

describe "HARNESS-020 AC-3  a fault that names no suite is reported, not dropped"

# Found in RED, and the reason (a) above cannot pass by reuse alone. A fault
# that carries no suite name - `is not a floor line`, `does not exist` - is
# queued as "<TAB><message>", and the report loop reads it back with
# IFS=<TAB>. TAB is an IFS WHITESPACE character, so read strips the leading
# one, the message lands in the name field, the message field is empty, and
# `[ -n "$fmsg" ] || continue` drops it. Measured on the shipped selftest.sh:
# a floors.conf holding `this is not a floor` passes the full run, exit 0. So
# the malformed-line fault has never been printed, for either file, and the
# missing-floors.conf fault is printed only by accident - every suite then
# also lacks a floor. These two pin the shared report path for floors.conf;
# (a) pins it for project-floors.conf.
reset_suites
passing_suite alpha 3
floors <<'FLOORS'
floor | alpha | 3
this is not a floor
FLOORS
selftest
assert_eq "a malformed floors.conf line fails the full run" 1 "$RC"
assert_eq "named with floors.conf, its line, and the fault" 1 \
  "$(exact_lines "FAIL .claude/tests/floors.conf:2  is not a floor line: 'this is not a floor'")"

reset_suites
passing_suite alpha 3
selftest
assert_eq "a missing floors.conf fails the full run" 1 "$RC"
assert_eq "and says so in its own words, not only through each suite's missing floor" 1 \
  "$(exact_lines "FAIL .claude/tests/floors.conf  does not exist; every suite must declare its assertion floor there")"

describe "HARNESS-020 AC-3  control: no project-floors.conf is not a fault"

# An upstream tree - this repository - ships no project-floors.conf, and must
# pass exactly as before. The needle is the file's NAME anywhere in the output:
# every fault above prints it, so a mechanism that makes absence a fault (or so
# much as mentions the file when it is absent) is caught here.
reset_suites
passing_suite alpha 3
passing_suite beta  7
floors <<'FLOORS'
floor | alpha | 3
floor | beta  | 7
FLOORS
selftest
assert_eq "with no project-floors.conf the full run exits 0" 0 "$RC"
assert_eq "and says both suites passed" 1 "$(exact_lines "2 harness suite(s) passed.")"
assert_not_contains "and project-floors.conf is not mentioned at all" "project-floors.conf" "$out"
assert_eq "and no line is a fault" 0 "$(printf '%s\n' "$out" | grep -c '^FAIL')"

# ---------------------------------------------------------------------------
describe "HARNESS-020 AC-4  a single-suite run enforces a project-floors.conf floor"

reset_suites
passing_suite alpha 3
passing_suite project-mine 3
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
floor | project-mine | 4
FLOORS
selftest project-mine
assert_eq "a project suite below its project floor fails its single-suite run" 1 "$RC"
assert_eq "naming the suite, both numbers and project-floors.conf" 1 \
  "$(exact_lines "FAIL project-mine  did 3 units of work, below the floor of 4 in $PF")"
assert_not_contains "and it is not waved through as having no floor" \
  "WARNING: no floor line for project-mine" "$out"

# The passing half: at its floor, the single-suite run is clean and counts
# the floor as met - not "passed, with a warning that no floor exists".
reset_suites
passing_suite alpha 3
passing_suite project-mine 4
floors <<'FLOORS'
floor | alpha | 3
FLOORS
project_floors <<'FLOORS'
floor | project-mine | 4
FLOORS
selftest project-mine
assert_eq "at its project floor the single-suite run exits 0" 0 "$RC"
assert_eq "and the floor is counted as met" 1 \
  "$(exact_lines "assertion floors: all 1 suite(s) met their declared floor (4 assertions executed, 4 declared).")"
assert_not_contains "with no missing-floor warning" "WARNING: no floor line" "$out"

# ===========================================================================
# HARNESS-036: opt-in concurrent suites, SELFTEST_JOBS. Every case below runs
# the fixture's copy of selftest.sh with SELFTEST_JOBS stated explicitly - a
# value, empty, or removed with `env -u` - and with VERBOSE empty, so nothing
# here depends on the caller's environment. The cases above are left alone
# and inherit the caller's value; under SELFTEST_JOBS=4 they exercise the
# concurrent path for free.
#
# THE SYNTHETIC SUITES are generated by held(): each sources _held.sh (below,
# written into the fixture), which records into the marker directory mk/ what
# the suite saw, and can HOLD - block on a file - so that ordering is a state
# the test controls rather than a race it hopes to win. Every hold is bounded:
# 120 s by default, 20 s for AC-3's work-conserving case (its control is meant
# to hit the bound), and a hold that waits on OTHER SUITES also gives up after
# 30 s with no other suite alive (LONELY) - a serial runner can never clear it,
# and without that every such hold would cost the suite its full bound. Once
# any hold in a run has timed out, every other hold in that run gives up at
# once: one failure is the evidence, the rest would be waiting time. A hold
# that times out fails the suite with
#     FAIL <name>: its hold cleared before its bound
# which is the line AC-3's control reads.
#
# What a suite records, all under mk/:
#   peers/<name>     the suites alive when it started, ITSELF INCLUDED. Each
#                    suite creates alive/<name> and THEN lists alive/, so of
#                    any set of suites alive together the last to start lists
#                    them all: the largest listing is the true peak.
#   started/<name>   created on start; finished/<name> created as it exits
#   state/<name>     `ls -A .claude/state` as it started
#   buf/<name>       the listing of .claude/state/selftest.*/ as it started
#   finbefore/<name> the suites that had finished when it finished
#   lockend/<name>   .claude/state/run.lock as it finished
#   timeout/<name>   created if its hold hit a bound
#
# Every executed assertion counts: a held() suite executes N+1 (its N cases
# and the hold assertion), so a floor of N+1 is met and N+2 is not.
# ===========================================================================

MK="$FIX/mk"
HW="$FIX/w"
mkdir -p "$HW"

cat > "$FIX/.claude/tests/_held.sh" <<'HELD'
# Sourced by HARNESS-036's synthetic suites, after _lib.sh. Inputs, set by the
# suite before sourcing: S (name), N (cases), and optionally WAIT_REL (hold
# until mk/release/<S> or mk/release/all), WAIT_FIN / WAIT_START (hold until
# those suites have finished / started), WAIT_COUNT (hold until that many
# suites have started), BOUND, LONELY, SETTLE, EXIT_RC, NOSUM, ERRLINE, TRAIL,
# FINISH_DELAY. mk/release/<S> or mk/release/all always clears a hold.
: "${N:=1}" "${BOUND:=120}" "${LONELY:=}" "${WAIT_REL:=}" "${WAIT_FIN:=}"
: "${WAIT_START:=}" "${WAIT_COUNT:=}" "${SETTLE:=}" "${EXIT_RC:=}" "${NOSUM:=}"
: "${ERRLINE:=}" "${TRAIL:=}" "${FINISH_DELAY:=}"
M="$REPO_ROOT/mk"
mkdir -p "$M/alive" "$M/started" "$M/finished" "$M/peers" "$M/state" "$M/buf" \
         "$M/lockend" "$M/finbefore" "$M/release" "$M/timeout"
: > "$M/alive/$S"
ls "$M/alive" > "$M/peers/$S"
ls -A "$REPO_ROOT/.claude/state" > "$M/state/$S" 2>/dev/null
ls -A "$REPO_ROOT"/.claude/state/selftest.*/ > "$M/buf/$S" 2>/dev/null
: > "$M/started/$S"

h_cond() {
  local x c
  if [ -e "$M/release/$S" ] || [ -e "$M/release/all" ]; then return 0; fi
  [ -n "$WAIT_REL" ] && return 1
  for x in $WAIT_FIN; do [ -e "$M/finished/$x" ] || return 1; done
  for x in $WAIT_START; do [ -e "$M/started/$x" ] || return 1; done
  if [ -n "$WAIT_COUNT" ]; then
    c=0
    for x in "$M"/started/*; do [ -e "$x" ] && c=$((c+1)); done
    [ "$c" -ge "$WAIT_COUNT" ] || return 1
  fi
  return 0
}
h_alone() {
  local x
  for x in "$M"/alive/*; do
    [ -e "$x" ] && [ "$x" != "$M/alive/$S" ] && return 1
  done
  return 0
}
held=cleared
if [ -n "$WAIT_REL$WAIT_FIN$WAIT_START$WAIT_COUNT" ]; then
  i=0; alone=0
  while ! h_cond; do
    if [ "$i" -ge $((BOUND*5)) ]; then held="timed out"; break; fi
    if [ -n "$LONELY" ]; then
      if h_alone; then alone=$((alone+1)); else alone=0; fi
      if [ "$alone" -ge $((LONELY*5)) ]; then held="timed out"; break; fi
    fi
    for x in "$M"/timeout/*; do [ -e "$x" ] && held="timed out"; done
    [ "$held" = cleared ] || break
    sleep 0.2; i=$((i+1))
  done
  if [ -n "$SETTLE" ] && [ "$held" = cleared ]; then sleep "$SETTLE"; fi
fi
[ "$held" = cleared ] || : > "$M/timeout/$S"

describe "$S"
printf '%s: a line of its own output\n' "$S"
[ -n "$ERRLINE" ] && printf '%s: a line on stderr\n' "$S" >&2
assert_eq "$S: its hold cleared before its bound" cleared "$held"
i=0
while [ "$i" -lt "$N" ]; do assert_eq "$S case $i" x x; i=$((i+1)); done
rc=0
if [ -z "$NOSUM" ]; then summary "$S"; rc=$?; fi
[ -n "$TRAIL" ] && printf '\n\n\n'
[ -n "$FINISH_DELAY" ] && sleep "$FINISH_DELAY"
cp "$REPO_ROOT/.claude/state/run.lock" "$M/lockend/$S" 2>/dev/null
ls "$M/finished" > "$M/finbefore/$S"
rm -f "$M/alive/$S"
: > "$M/finished/$S"
exit "${EXIT_RC:-$rc}"
HELD

# held <name> [VAR=value ...]   A synthetic suite. PAD=<n> adds n comment
# lines, which changes nothing but the file's size: C-2 lets GREEN start the
# largest file first, and the cases whose meaning depends on WHICH suites
# start first are padded so that size order and glob order agree.
held() {
  local n="$1" kv p
  shift
  {
    printf '#!/usr/bin/env bash\n'
    printf '. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"\n'
    printf 'S=%s\n' "$n"
    for kv in "$@"; do
      case "$kv" in
        PAD=*) p=0; while [ "$p" -lt "${kv#PAD=}" ]; do
                 printf '# padding, so that this file sorts larger by size\n'; p=$((p+1)); done ;;
        *) printf '%s\n' "$kv" ;;
      esac
    done
    printf '. "$(dirname "${BASH_SOURCE[0]}")/_held.sh"\n'
  } > "$FIX/.claude/tests/$n.test.sh"
}

# mk_reset   No markers. Holds are released only by files the case creates.
mk_reset() { rm -rf "$MK"; mkdir -p "$MK/release"; }

# release <name>...   Pre-releases a hold, so a serial run never blocks on it.
release() { local s; for s in "$@"; do : > "$MK/release/$s"; done; }

# jrun <jobs> [args]   The fixture's selftest.sh in the foreground, with
# SELFTEST_JOBS=<jobs>, or removed when <jobs> is `-`. stdout to $HW/out,
# stderr to $HW/err, status in JRC. Kept as files so that byte identity is
# checked with cmp, trailing newlines included.
JRC=""
jrun() {
  local j="$1"
  shift
  if [ "$j" = - ]; then
    ( cd "$FIX" && env -u SELFTEST_JOBS VERBOSE= bash scripts/selftest.sh "$@" ) > "$HW/out" 2> "$HW/err"
  else
    ( cd "$FIX" && SELFTEST_JOBS="$j" VERBOSE= bash scripts/selftest.sh "$@" ) > "$HW/out" 2> "$HW/err"
  fi
  JRC=$?
}

# keep <tag>   Saves the last run's out/err as out.<tag>/err.<tag>.
keep() { cp "$HW/out" "$HW/out.$1"; cp "$HW/err" "$HW/err.$1"; }

# jstart <jobs> [args]   The SCRIPT ITSELF backgrounded from inside the
# fixture - `cd`, then `bash scripts/selftest.sh &` - so that $! is the pid in
# the buffer directory's name and in the lock (as run-lock.test.sh does).
HP=""
jstart() {
  local j="$1" here="$PWD"
  shift
  cd "$FIX" || return 1
  SELFTEST_JOBS="$j" VERBOSE= bash scripts/selftest.sh "$@" > "$HW/out" 2> "$HW/err" &
  HP=$!
  cd "$here" || return 1
  BG="$BG $HP"
}

# h_wait <file>...   Polls up to 60 s for every file to exist. 0 once they do.
h_wait() {
  local i=0 f ok
  while [ "$i" -lt 300 ]; do
    ok=1
    for f in "$@"; do [ -e "$f" ] || ok=0; done
    [ "$ok" = 1 ] && return 0
    sleep 0.2; i=$((i+1))
  done
  return 1
}

# yn <test...>   `yes` or `no`, so a failure message says which.
yn() { if "$@"; then printf yes; else printf no; fi; }
present() { if [ -e "$1" ]; then printf present; else printf absent; fi; }

# h_lines <file>   Its line count, 0 when absent. Pure bash.
h_lines() {
  local n=0 l
  [ -f "$1" ] || { printf 0; return; }
  while IFS= read -r l || [ -n "$l" ]; do n=$((n+1)); done < "$1"
  printf '%s' "$n"
}

# h_count <dir>   How many entries mk/<dir> holds.
h_count() {
  local n=0 f
  for f in "$MK/$1"/*; do [ -e "$f" ] && n=$((n+1)); done
  printf '%s' "$n"
}

# h_peak   The most suites alive at once, from the peers listings.
h_peak() {
  local m=0 f n
  for f in "$MK"/peers/*; do
    [ -e "$f" ] || continue
    n="$(h_lines "$f")"
    [ "$n" -gt "$m" ] && m="$n"
  done
  printf '%s' "$m"
}

# h_saw_re <ERE>   How many suites' .claude/state listings hold a matching line.
h_saw_re() {
  local n=0 f
  for f in "$MK"/state/*; do
    [ -e "$f" ] || continue
    grep -qE -- "$1" "$f" && n=$((n+1))
  done
  printf '%s' "$n"
}

# h_saw_line <dir> <line|@NAME@>   How many of mk/<dir>/* hold the exact line,
# `@NAME@` replaced by each file's own suite name.
h_saw_line() {
  local n=0 f want
  for f in "$MK/$1"/*; do
    [ -e "$f" ] || continue
    want="${2//@NAME@/${f##*/}}"
    grep -qxF -- "$want" "$f" && n=$((n+1))
  done
  printf '%s' "$n"
}

# h_left   What the run left in the fixture's .claude/state: selftest.*
# entries, run.lock and run.lock.*, space-joined. Empty when clean.
h_left() {
  local f l=""
  for f in "$FIX"/.claude/state/selftest.* "$FIX"/.claude/state/run.lock \
           "$FIX"/.claude/state/run.lock.*; do
    [ -e "$f" ] && l="$l ${f##*/}"
  done
  printf '%s' "${l# }"
}

# h_last <name>   The last line of $HW/out.<name>.
h_last() { awk 'END { print }' "$HW/out.$1"; }

# h_exact <line> <file>   How many lines of <file> are exactly <line>.
h_exact() { grep -cxF -- "$1" "$2"; }

# h_same <a> <b>   `identical` or the first lines of the difference.
h_same() {
  if cmp -s "$1" "$2"; then printf identical
  else printf 'differ:\n%s' "$(diff "$1" "$2" 2>&1 | awk 'NR <= 12')"; fi
}

# ---------------------------------------------------------------------------
describe "HARNESS-036 AC-1  SELFTEST_JOBS unset, empty or 1 runs today's sequential loop, byte for byte"

# Five suites: one that holds until the second has started (pre-released for
# the sequential runs, so it never blocks there), one that writes stderr and
# ends in blank lines, one that exits 3 with its floor met, one below its
# floor, one with no summary line. 3 of 5 fail, for three different reasons.
reset_suites
held a1-holds  N=3 WAIT_START=a2-stderr LONELY=30
held a2-stderr N=2 ERRLINE=1 TRAIL=1
held a3-exits3 N=4 EXIT_RC=3
held a4-short  N=1
held a5-silent NOSUM=1
floors <<'FLOORS'
floor | a1-holds  | 4
floor | a2-stderr | 3
floor | a3-exits3 | 5
floor | a4-short  | 3
floor | a5-silent | 1
FLOORS

# THE GOLDEN: stdout of the release-77 scripts/selftest.sh (c9260a7, the one
# in the tree at RED) on exactly this fixture, captured in RED. Its stderr was
# empty and it exited 1. Only text the synthetic suites print and selftest.sh's
# own lines - no paths, no pids.
cat > "$HW/golden" <<'GOLDEN'

=== a1-holds ===

  a1-holds
a1-holds: a line of its own output

a1-holds: 4 passed, 0 failed

=== a2-stderr ===

  a2-stderr
a2-stderr: a line of its own output
a2-stderr: a line on stderr

a2-stderr: 3 passed, 0 failed

=== a3-exits3 ===

  a3-exits3
a3-exits3: a line of its own output

a3-exits3: 5 passed, 0 failed

=== a4-short ===

  a4-short
a4-short: a line of its own output

a4-short: 2 passed, 0 failed
FAIL a4-short  did 2 units of work, below the floor of 3 in .claude/tests/floors.conf

=== a5-silent ===

  a5-silent
a5-silent: a line of its own output
FAIL a5-silent  printed no summary line, so its floor of 1 could not be checked

assertion floors: 3 of 5 suite(s) met their declared floor.
3 of 5 harness suite(s) FAILED.
GOLDEN

for mode in unset empty 1; do
  mk_reset; release a1-holds
  case "$mode" in
    unset) jrun - ;;
    empty) jrun "" ;;
    1)     jrun 1 ;;
  esac
  keep "ac1-$mode"
  assert_eq "SELFTEST_JOBS $mode: the run exits 1, as release 77 does on this fixture" 1 "$JRC"
  assert_eq "SELFTEST_JOBS $mode: stdout is byte-identical to release 77's" identical \
    "$(h_same "$HW/golden" "$HW/out")"
  assert_eq "SELFTEST_JOBS $mode: stderr is identical to release 77's, which was empty" "" \
    "$(cat "$HW/err")"
  assert_eq "SELFTEST_JOBS $mode: precondition - all five suites ran" 5 "$(h_count finished)"
  assert_eq "SELFTEST_JOBS $mode: no two suites were ever alive at once" 1 "$(h_peak)"
  assert_eq "SELFTEST_JOBS $mode: no suite saw a .claude/state/selftest.* entry while it ran" 0 \
    "$(h_saw_re '^selftest\.')"
  assert_eq "SELFTEST_JOBS $mode: and none is left after it, nor a run.lock" "" "$(h_left)"
done

describe "HARNESS-036 AC-1  control: the same fixture at SELFTEST_JOBS=3 is concurrent"

mk_reset
jrun 3
assert_eq "SELFTEST_JOBS=3: suites were alive together (peak above 1)" yes \
  "$(yn [ "$(h_peak)" -ge 2 ])"
assert_eq "SELFTEST_JOBS=3: a suite saw a .claude/state/selftest.<pid> buffer directory while it ran" yes \
  "$(yn [ "$(h_saw_re '^selftest\.[0-9]+$')" -ge 1 ])"
assert_eq "SELFTEST_JOBS=3: and the same fixture still exits 1" 1 "$JRC"

# ---------------------------------------------------------------------------
describe "HARNESS-036 AC-2  concurrent output is the serial output, failures included"

# b1 is first in glob order and finishes LAST (it holds until every other
# suite has finished). b2 exits 3 with its floor met, and holds until b3 has
# finished, so it is neither first nor last to finish, nor first or last in
# glob order. b3 is below its floor, b4 prints no summary line, b5 writes
# stderr and ends in blank lines.
reset_suites
held b1-last   N=1 "WAIT_FIN='b2-exits3 b3-short b4-silent b5-stderr b6-plain'" LONELY=30
held b2-exits3 N=2 EXIT_RC=3 WAIT_FIN=b3-short LONELY=30
held b3-short  N=1
held b4-silent NOSUM=1
held b5-stderr N=1 ERRLINE=1 TRAIL=1
held b6-plain  N=1
floors <<'FLOORS'
floor | b1-last   | 2
floor | b2-exits3 | 3
floor | b3-short  | 3
floor | b4-silent | 1
floor | b5-stderr | 2
floor | b6-plain  | 2
FLOORS

mk_reset; release b1-last b2-exits3
jrun 1; keep ac2f-1; rc1="$JRC"
mk_reset
jrun 3; keep ac2f-3; rc3="$JRC"
assert_eq "SELFTEST_JOBS=1 over the failing fixture exits 1" 1 "$rc1"
assert_eq "SELFTEST_JOBS=3 over the failing fixture exits 1" 1 "$rc3"
assert_eq "SELFTEST_JOBS=1's last line counts the three failures" \
  "3 of 6 harness suite(s) FAILED." "$(h_last ac2f-1)"
assert_eq "SELFTEST_JOBS=3's last line counts the same three failures" \
  "3 of 6 harness suite(s) FAILED." "$(h_last ac2f-3)"
assert_eq "SELFTEST_JOBS=3's stdout is byte-identical to SELFTEST_JOBS=1's" identical \
  "$(h_same "$HW/out.ac2f-1" "$HW/out.ac2f-3")"
assert_eq "SELFTEST_JOBS=3's stderr is identical to SELFTEST_JOBS=1's" identical \
  "$(h_same "$HW/err.ac2f-1" "$HW/err.ac2f-3")"
assert_eq "precondition: all six suites ran at SELFTEST_JOBS=3" 6 "$(h_count finished)"
assert_eq "control: at SELFTEST_JOBS=3 the first suite in glob order finished last" 5 \
  "$(h_lines "$MK/finbefore/b1-last")"
assert_eq "control: and b2-exits3 was neither the first nor the last to finish" yes \
  "$(yn grep -qxF b3-short "$MK/finbefore/b2-exits3")"

describe "HARNESS-036 AC-2  an all-passing fixture: the same totals, the same verdict"

reset_suites
held c1-last   N=2 "WAIT_FIN='c2-plain c3-stderr c4-plain'" LONELY=30
held c2-plain  N=1
held c3-stderr N=3 ERRLINE=1 TRAIL=1
held c4-plain  N=2
floors <<'FLOORS'
floor | c1-last   | 3
floor | c2-plain  | 2
floor | c3-stderr | 4
floor | c4-plain  | 3
FLOORS
mk_reset; release c1-last
jrun 1; keep ac2p-1; rc1="$JRC"
mk_reset
jrun 3; keep ac2p-3; rc3="$JRC"
FLOORLINE="assertion floors: all 4 suite(s) met their declared floor (12 assertions executed, 12 declared)."
assert_eq "SELFTEST_JOBS=1 over the passing fixture exits 0" 0 "$rc1"
assert_eq "SELFTEST_JOBS=3 over the passing fixture exits 0" 0 "$rc3"
assert_eq "SELFTEST_JOBS=3's stdout is byte-identical to SELFTEST_JOBS=1's" identical \
  "$(h_same "$HW/out.ac2p-1" "$HW/out.ac2p-3")"
assert_eq "SELFTEST_JOBS=3's stderr is identical to SELFTEST_JOBS=1's" identical \
  "$(h_same "$HW/err.ac2p-1" "$HW/err.ac2p-3")"
assert_eq "SELFTEST_JOBS=1 prints the all-met floors line once" 1 "$(h_exact "$FLOORLINE" "$HW/out.ac2p-1")"
assert_eq "SELFTEST_JOBS=3 prints the all-met floors line once" 1 "$(h_exact "$FLOORLINE" "$HW/out.ac2p-3")"
assert_eq "SELFTEST_JOBS=1 ends with 4 harness suite(s) passed." \
  "4 harness suite(s) passed." "$(h_last ac2p-1)"
assert_eq "SELFTEST_JOBS=3 ends with 4 harness suite(s) passed." \
  "4 harness suite(s) passed." "$(h_last ac2p-3)"
assert_eq "control: at SELFTEST_JOBS=3 the first suite in glob order finished last" 3 \
  "$(h_lines "$MK/finbefore/c1-last")"

describe "HARNESS-036 AC-2  one named suite at SELFTEST_JOBS=3 is the same single-suite run"

# A suite with no floor line, so the single-suite WARNING lines on stderr are
# part of what must be identical.
held c5-nofloor N=1 ERRLINE=1
mk_reset
jrun 1 c5-nofloor; keep ac2s-1; rc1="$JRC"
mk_reset
jrun 3 c5-nofloor; keep ac2s-3; rc3="$JRC"
assert_eq "SELFTEST_JOBS=1 c5-nofloor exits 0" 0 "$rc1"
assert_eq "SELFTEST_JOBS=3 c5-nofloor exits 0" 0 "$rc3"
assert_eq "SELFTEST_JOBS=3 c5-nofloor: stdout byte-identical to SELFTEST_JOBS=1's" identical \
  "$(h_same "$HW/out.ac2s-1" "$HW/out.ac2s-3")"
assert_eq "SELFTEST_JOBS=3 c5-nofloor: stderr identical to SELFTEST_JOBS=1's, its WARNING lines included" identical \
  "$(h_same "$HW/err.ac2s-1" "$HW/err.ac2s-3")"
assert_eq "precondition: that stderr does carry the no-floor WARNING" 1 \
  "$(h_exact "WARNING: whether that suite did any work. Declare one before the full run." "$HW/err.ac2s-3")"
assert_eq "SELFTEST_JOBS=3 c5-nofloor runs exactly one suite: one header, its own" "=== c5-nofloor ===" \
  "$(grep -E '^=== .* ===$' "$HW/out.ac2s-3")"
assert_eq "and only that suite started" 1 "$(h_count started)"

describe "HARNESS-036 AC-2  a name that matches nothing at SELFTEST_JOBS=3"

mk_reset
jrun 3 nosuchsuite
assert_eq "SELFTEST_JOBS=3 nosuchsuite exits 1" 1 "$JRC"
assert_eq "with the shipped No suites matched line, alone, on stderr" \
  "No suites matched 'nosuchsuite'. Looked in .claude/tests/*.test.sh" "$(cat "$HW/err")"
assert_eq "and nothing on stdout" "" "$(cat "$HW/out")"
assert_eq "and no suite started" 0 "$(h_count started)"

describe "HARNESS-036 AC-2  a finished suite is printed while a later one is still held"

reset_suites
held d1-quick N=1
held d2-held  N=1 WAIT_REL=1
held d3-held  N=1 WAIT_REL=1
floors <<'FLOORS'
floor | d1-quick | 2
floor | d2-held  | 2
floor | d3-held  | 2
FLOORS
mk_reset
jstart 3
if h_wait "$MK/started/d2-held" "$MK/started/d3-held"; then both=yes; else both=no; fi
assert_eq "precondition: at SELFTEST_JOBS=3, d2-held and d3-held are both running and held" yes "$both"
# The runner may back off between polls; give it up to 30 s to print.
i=0; shown=no
while [ "$i" -lt 150 ]; do
  if [ "$(h_exact '=== d1-quick ===' "$HW/out")" = 1 ] && \
     [ "$(h_exact 'd1-quick: 2 passed, 0 failed' "$HW/out")" = 1 ]; then shown=yes; break; fi
  sleep 0.2; i=$((i+1))
done
heldnow="d2-held=$(present "$MK/finished/d2-held") d3-held=$(present "$MK/finished/d3-held")"
assert_eq "while both later suites are concurrently held, d1-quick's whole block is already on stdout" \
  "both-held=yes printed=yes finished: d2-held=absent d3-held=absent" \
  "both-held=$both printed=$shown finished: $heldnow"
release all
wait "$HP"; rc="$?"
assert_eq "released, the run exits 0" 0 "$rc"

# ---------------------------------------------------------------------------
describe "HARNESS-036 AC-3  at most SELFTEST_JOBS suites alive at once, and exactly that many"

# Each suite holds until K suites have started, then 1 s more, so the first K
# are alive together and an over-eager runner has time to start one more.
peak_case() { # <jobs> <suites> <K>
  local j="$1" n="$2" k="$3" s=1
  reset_suites
  : > "$FIX/.claude/tests/floors.conf"
  while [ "$s" -le "$n" ]; do
    held "e$s" N=1 WAIT_COUNT="$k" SETTLE=1 LONELY=30
    printf 'floor | e%s | 2\n' "$s" >> "$FIX/.claude/tests/floors.conf"
    s=$((s+1))
  done
  mk_reset
  jrun "$j"
  assert_eq "SELFTEST_JOBS=$j over $n held suites exits 0" 0 "$JRC"
  assert_eq "SELFTEST_JOBS=$j over $n: precondition - all $n ran" "$n" "$(h_count finished)"
  assert_eq "SELFTEST_JOBS=$j over $n: the most suites alive at once is exactly $k" "$k" "$(h_peak)"
}
peak_case 2 4 2
peak_case 3 5 3
peak_case 10 4 4

describe "HARNESS-036 AC-3  a free slot is refilled when ANY suite exits, not the oldest"

# w1 holds (20 s) until w4, the last in glob order, has started. With two
# slots that needs w2 and w3 to come and go beside a w1 that is still
# running. Padding makes w1 the largest file and w4 the smallest, so a
# largest-first start order starts the same two first as glob order does.
work_case() {
  reset_suites
  held w1-first N=1 WAIT_START=w4-last BOUND=20 PAD=40
  held w2-mid   N=1 PAD=10
  held w3-mid   N=1 PAD=10
  held w4-last  N=1
  floors <<'FLOORS'
floor | w1-first | 2
floor | w2-mid   | 2
floor | w3-mid   | 2
floor | w4-last  | 2
FLOORS
  mk_reset
}
work_case
jrun 2
assert_eq "SELFTEST_JOBS=2: the run completes and exits 0" 0 "$JRC"
assert_eq "SELFTEST_JOBS=2: w1-first's hold cleared, it did not time out" absent "$(present "$MK/timeout/w1-first")"

work_case
jrun 1
assert_eq "control: SELFTEST_JOBS=1 over the same fixture exits 1" 1 "$JRC"
assert_eq "control: because w1-first reports that its hold timed out" 1 \
  "$(h_exact '    FAIL w1-first: its hold cleared before its bound' "$HW/out")"

# ---------------------------------------------------------------------------
describe "HARNESS-036 AC-4  a bad SELFTEST_JOBS is refused before anything runs"

reset_suites
held h1 N=1
held h2 N=1
floors <<'FLOORS'
floor | h1 | 2
floor | h2 | 2
FLOORS
refusal() {
  printf "selftest: SELFTEST_JOBS must be a whole number of suites to run at once, 1 or more; got '%s'. Nothing was run." "$1"
}
for v in 0 00 -1 abc 1.5 ' 2' 2x; do
  for target in full h1; do
    mk_reset
    if [ "$target" = full ]; then jrun "$v"; else jrun "$v" h1; fi
    assert_eq "SELFTEST_JOBS='$v', $target run: exits 2" 2 "$JRC"
    assert_eq "SELFTEST_JOBS='$v', $target run: stderr is exactly the one refusal line" \
      "$(refusal "$v")" "$(cat "$HW/err")"
    assert_eq "SELFTEST_JOBS='$v', $target run: nothing on stdout" "" "$(cat "$HW/out")"
    assert_eq "SELFTEST_JOBS='$v', $target run: no suite started" 0 "$(h_count started)"
    assert_eq "SELFTEST_JOBS='$v', $target run: no run.lock and no selftest.* left" "" "$(h_left)"
  done
done

describe "HARNESS-036 AC-4  the value is checked before the floors file"

floors <<'FLOORS'
floor | h1 | 2
floor | h2 | 2
this is not a floor
FLOORS
mk_reset
jrun abc
assert_eq "SELFTEST_JOBS=abc over a malformed floors.conf: exits 2, not the floors audit's 1" 2 "$JRC"
assert_eq "and stderr is the refusal line, alone" "$(refusal abc)" "$(cat "$HW/err")"
assert_eq "and no floors fault is printed: stdout is empty" "" "$(cat "$HW/out")"

describe "HARNESS-036 AC-4  control: a value above the number of suites is accepted"

floors <<'FLOORS'
floor | h1 | 2
floor | h2 | 2
FLOORS
mk_reset
jrun 10
assert_eq "SELFTEST_JOBS=10 over two suites exits 0" 0 "$JRC"
assert_eq "and both passed" 1 "$(h_exact '2 harness suite(s) passed.' "$HW/out")"

# ---------------------------------------------------------------------------
describe "HARNESS-036 AC-5  buffers under .claude/state/selftest.<pid>/, the lock held to the end"

# f1 holds until f2 and f3 have finished, so which suite finishes last is a
# state the test controls (found in RED: picking "the suite whose finbefore
# lists the other two" is a race when suites finish together - none may).
reset_suites
held f1 N=1 "WAIT_FIN='f2 f3'" LONELY=30
held f2 N=1
held f3 N=1
floors <<'FLOORS'
floor | f1 | 2
floor | f2 | 2
floor | f3 | 2
FLOORS
mk_reset
jstart 3
wait "$HP"; rc="$?"
assert_eq "SELFTEST_JOBS=3 over three passing suites exits 0" 0 "$rc"
assert_eq "every suite saw .claude/state/selftest.<pid>, <pid> being selftest.sh's own (\$!)" 3 \
  "$(h_saw_line state "selftest.$HP")"
assert_eq "C-2: and its own buffer, <name>.out, already in it" 3 "$(h_saw_line buf '@NAME@.out')"
assert_eq "precondition: f1 finished last, after f2 and f3" 2 "$(h_lines "$MK/finbefore/f1")"
assert_eq "the suite that finished last still saw run.lock recording selftest.sh's pid" "$HP" \
  "$(awk -F'\t' '$1 == "pid" { print $2; exit }' "$MK/lockend/f1" 2>/dev/null)"
assert_eq "after exit 0: no selftest.* and no run.lock or run.lock.* remain" "" "$(h_left)"

held f1 N=1
held f2 N=1 EXIT_RC=1
mk_reset
jstart 3
wait "$HP"; rc="$?"
assert_eq "SELFTEST_JOBS=3 with one suite exiting 1 (floor met) exits 1" 1 "$rc"
assert_eq "after exit 1: no selftest.* and no run.lock or run.lock.* remain" "" "$(h_left)"

describe "HARNESS-036 AC-5  TERM drains the running suites, starts no more, and cleans up"

reset_suites
held t1-held N=1 WAIT_REL=1 FINISH_DELAY=1
held t2-held N=1 WAIT_REL=1 FINISH_DELAY=1
held t3-queued N=1
floors <<'FLOORS'
floor | t1-held   | 2
floor | t2-held   | 2
floor | t3-queued | 2
FLOORS
mk_reset
jstart 2
if h_wait "$MK/started/t1-held" "$MK/started/t2-held"; then both=yes; else both=no; fi
assert_eq "precondition: at SELFTEST_JOBS=2, t1-held and t2-held are both running and held" yes "$both"
kill -TERM "$HP" 2>/dev/null
sleep 1
assert_eq "sent TERM, selftest.sh is still alive one second later, while its suites are held" yes \
  "$(yn kill -0 "$HP" 2>/dev/null)"
assert_eq "and still holds run.lock while it drains" present "$(present "$FIX/.claude/state/run.lock")"
release all
wait "$HP"; rc="$?"
assert_eq "released, the run exits 143" 143 "$rc"
assert_eq "t1-held wrote its finished marker before the run exited" present "$(present "$MK/finished/t1-held")"
assert_eq "t2-held wrote its finished marker before the run exited" present "$(present "$MK/finished/t2-held")"
assert_eq "the queued t3-queued never started" absent "$(present "$MK/started/t3-queued")"
assert_eq "after TERM: no selftest.* and no run.lock or run.lock.* remain" "" "$(h_left)"

# ---------------------------------------------------------------------------
describe "HARNESS-036 AC-6  state, suite and portability hygiene, in this repository"

README="$REPO_ROOT/.claude/state/README.md"
# state_row <path cell>   Table rows with that path cell whose last cell is yes.
state_row() {
  local p; p="$(printf '%s' "$1" | sed 's/[.*]/\\&/g')"
  tr -d '\r' < "$README" | grep -cE -- "^\\| \`$p\` +\\|.*\\| yes +\\|\$"
}
assert_eq "README has one selftest.<pid>/*.out row, hand-editable yes" 1 "$(state_row 'selftest.<pid>/*.out')"
assert_eq "control: the same reader finds the existing run.lock.<pid> row" 1 "$(state_row 'run.lock.<pid>')"

git -C "$REPO_ROOT" check-ignore -q --no-index .claude/state/selftest.12345/gates.out; rc=$?
assert_eq ".claude/state/selftest.<pid>/<name>.out is gitignored here" 0 "$rc"
git -C "$REPO_ROOT" check-ignore -q --no-index .claude/state/README.md; rc=$?
assert_eq "control: the same check reports .claude/state/README.md as not ignored" 1 "$rc"

# C-2 pins this line, exactly, because DV-1's single sed expression targets it.
assert_eq "scripts/selftest.sh defines suite_status on exactly the one line DV-1 mutates" 1 \
  "$(grep -cxF 'suite_status() { wait "$1"; }' "$REPO_ROOT/scripts/selftest.sh")"
assert_eq "and defines it nowhere else" 1 \
  "$(grep -cE '^[[:space:]]*suite_status[[:space:]]*\(\)' "$REPO_ROOT/scripts/selftest.sh")"

# forbidden <file>   "<line>: <construct>" for each code line - full-line
# comments skipped, a trailing ` # ...` stripped - holding a construct bash
# 3.2 lacks or that would need one.
forbidden() {
  awk '
    /^[[:space:]]*#/ { next }
    { line = $0; sub(/[[:space:]]#.*$/, "", line)
      n = split("wait -n|wait -p|mapfile|readarray|coproc|declare -A|local -A|typeset -A", w, "|")
      for (i = 1; i <= n; i++) if (index(line, w[i])) printf "%d: %s\n", FNR, w[i] }' "$1"
}
assert_eq "scripts/selftest.sh's code lines use no wait -n, wait -p, mapfile, readarray, coproc or associative array" \
  "" "$(forbidden "$REPO_ROOT/scripts/selftest.sh")"
printf '%s\n' '  wait -n' '# wait -n, mapfile and coproc, in a comment' 'x=1  # declare -A in a trailing comment' \
  '  local -A seen' > "$HW/__probe_forbidden.sh"
assert_eq "control: the same reader flags them on code lines and not in comments" "1: wait -n
4: local -A" "$(forbidden "$HW/__probe_forbidden.sh")"

summary "selftest"
