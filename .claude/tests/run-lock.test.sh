#!/usr/bin/env bash
# Tests for the run lock (HARNESS-034): scripts/gates.sh and scripts/selftest.sh
# refuse to start while another harness run holds the same tree's lock,
# <tree>/.claude/state/run.lock, reclaim a lock whose holder has died, and let a
# run nested under the holder in the same tree through.
#
# The field case (issue #97, finding C): selftest.sh run beside gates.sh in one
# worktree hung for over 30 minutes, and passed alone. This suite makes "the
# first run is still in progress" a state the test CONTROLS rather than a race
# it hopes to win: the holder's gate command, or its suite, touches m/started
# and then waits for m/release, which the test creates. Every wait is bounded
# (120 s), so a defect cannot hang the suite.
#
# Every run is in a throwaway fixture (make_project_fixture: the real scripts
# and hooks copied in), never in this checkout - except the block at the end,
# which asserts AC-7's real-tree facts.
#
# THE MARKERS. Under the real selftest.sh this suite inherits
# HARNESS_RUN_LOCK / HARNESS_RUN_LOCK_PID naming THIS checkout's lock and the
# outer run's pid, and so does every fixture run below. That is AC-5's
# situation, and no case here depends on their being absent: the cases that are
# about the markers set them explicitly (C-4). The suite must give the same
# result run directly and under selftest.sh.
#
# NEEDLES. The messages are C-2's, compared as WHOLE lines (grep -cxF), because
# `run-lock: reclaimed ...` and `run-lock: refusing ...` share a prefix and a
# floating `run-lock:` would be satisfied by the wrong one. Exit statuses are
# compared exactly: 2, not "non-zero" - a crash is non-zero too.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

W="$(mktemp -d 2>/dev/null || mktemp -d -t runlock.XXXXXX)"
FIX="$(make_project_fixture)"
FIXB="$(make_project_fixture)"
BG=""          # every background pid this suite starts; reaped on EXIT

cleanup() {
  local p
  touch "$FIX/m/release" "$FIXB/m/release" 2>/dev/null
  for p in $BG; do kill "$p" 2>/dev/null; done
  for p in $BG; do wait "$p" 2>/dev/null; done
  rm -rf "$FIX" "$FIXB" "$W"
}
trap cleanup EXIT

# --- the fixture -------------------------------------------------------------

# fixture_setup <tree>   The gate `unit` runs m/unit.sh; the fixture's own
# .claude/tests holds three suites (tiny, slow, failing), the REAL _lib.sh and
# a floors.conf naming them, so the fixture's selftest.sh passes its own floors
# audit.
fixture_setup() {
  local t="$1"
  mkdir -p "$t/m" "$t/.claude/tests" "$t/.claude/state"
  cp "$REPO_ROOT/.claude/tests/_lib.sh" "$t/.claude/tests/_lib.sh"

  # The gate command. Marks that it ran, whether it saw the lock, and the two
  # markers as it inherited them; holds while m/hold exists; fails when m/fail
  # does. m/unit-finished is written last, after any hold, so "the gate command
  # finished before gates.sh exited" is observable.
  cat > "$t/m/unit.sh" <<'UNIT'
#!/usr/bin/env bash
touch m/unit-ran
[ -f .claude/state/run.lock ] && touch m/unit-saw-lock
cp .claude/state/run.lock m/unit-lock 2>/dev/null
printf '%s\n%s\n' "${HARNESS_RUN_LOCK-<unset>}" "${HARNESS_RUN_LOCK_PID-<unset>}" > m/unit-env
if [ -f m/hold ]; then
  touch m/started
  i=0
  while [ ! -f m/release ] && [ "$i" -lt 600 ]; do sleep 0.2; i=$((i+1)); done
fi
touch m/unit-finished
if [ -f m/fail ]; then printf 'Tests  0 passed, 1 failed\n'; exit 1; fi
printf 'Tests  1 passed (1)\n'
UNIT

  cat > "$t/.claude/tests/tiny.test.sh" <<'SUITE'
#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
touch "$REPO_ROOT/m/tiny-ran"
[ -f "$REPO_ROOT/.claude/state/run.lock" ] && touch "$REPO_ROOT/m/tiny-saw-lock"
cp "$REPO_ROOT/.claude/state/run.lock" "$REPO_ROOT/m/tiny-lock" 2>/dev/null
assert_eq "tiny" x x
summary "tiny"
SUITE

  cat > "$t/.claude/tests/slow.test.sh" <<'SUITE'
#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
[ -f "$REPO_ROOT/.claude/state/run.lock" ] && touch "$REPO_ROOT/m/slow-saw-lock"
touch "$REPO_ROOT/m/started"
i=0
while [ ! -f "$REPO_ROOT/m/release" ] && [ "$i" -lt 600 ]; do sleep 0.2; i=$((i+1)); done
assert_eq "slow" x x
summary "slow"
SUITE

  cat > "$t/.claude/tests/failing.test.sh" <<'SUITE'
#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
[ -f "$REPO_ROOT/.claude/state/run.lock" ] && touch "$REPO_ROOT/m/failing-saw-lock"
assert_eq "this one passes" x x
assert_eq "this one fails on purpose" x y
summary "failing"
SUITE

  printf 'floor | tiny | 1\nfloor | slow | 1\nfloor | failing | 1\n' \
    > "$t/.claude/tests/floors.conf"
  conf_unit "$t"
}

# conf_unit <tree>   The ordinary manifest: one required gate running m/unit.sh.
conf_unit() {
  write_conf "$1" <<'EOF'
gate     | unit | required | . | bash m/unit.sh
evidence | unit | Tests +[1-9][0-9]* passed
EOF
}

# reset <tree>   No lock, no markers. The gate logs and stamp are left alone.
reset() {
  rm -f "$1"/m/unit-* "$1"/m/tiny-* "$1"/m/slow-* "$1"/m/failing-* \
        "$1/m/started" "$1/m/release" "$1/m/hold" "$1/m/fail" \
        "$1"/.claude/state/run.lock*
}

fixture_setup "$FIX"
fixture_setup "$FIXB"
FIXABS="$(cd "$FIX" && pwd)"
LOCKA="$FIXABS/.claude/state/run.lock"

# --- instruments -------------------------------------------------------------

count_line() { printf '%s\n' "$2" | grep -cxF -- "$1"; }   # <exact line> <text>
count_re()   { awk 'BEGIN { re = ARGV[1]; ARGV[1] = "" } $0 ~ re { n++ } END { print n + 0 }' "$1" <<< "$2"; }

# run <tree> <command...>   Runs it in the tree; sets OUT (stdout), ERR
# (stderr) and RC. C-2 says the lock speaks on stderr.
OUT=""; ERR=""; RC=""
run() {
  local t="$1"; shift
  ( cd "$t" && "$@" ) > "$W/out" 2> "$W/err"; RC=$?
  OUT="$(cat "$W/out")"; ERR="$(cat "$W/err")"
}

# wait_for <file>   Polls up to 60 s. 0 once it exists.
wait_for() {
  local i=0
  while [ ! -e "$1" ] && [ "$i" -lt 300 ]; do sleep 0.2; i=$((i+1)); done
  [ -e "$1" ]
}

# start_holder <tree> <command...>   Backgrounds the SCRIPT ITSELF from inside
# the tree - `cd`, then `bash scripts/... &` - so that $! is the script's pid,
# which is what the lock records and what a TERM must reach. Sets HP, and
# HOLDING to yes once the holder reported itself in progress.
HP=""; HOLDING=no
start_holder() {
  local t="$1" here="$PWD"; shift
  rm -f "$t/m/started" "$t/m/release"
  touch "$t/m/hold"
  cd "$t" || return 1
  "$@" > "$W/holder.out" 2> "$W/holder.err" &
  HP=$!
  cd "$here" || return 1
  BG="$BG $HP"
  if wait_for "$t/m/started"; then HOLDING=yes; else HOLDING=no; fi
  rm -f "$t/m/hold"
}

# finish_holder <tree>   Releases the holder and waits for it. Sets HRC.
HRC=""
finish_holder() { touch "$1/m/release"; wait "$HP"; HRC=$?; }

# lock_field <tree> <key>   The value of one TAB-separated line of the lock.
lock_field() { awk -F'\t' -v k="$2" '$1 == k { print $2; exit }' "$1/.claude/state/run.lock" 2>/dev/null; }

# seen_field <copy> <key>   One field of the lock as the gate command or suite
# copied it WHILE it ran (m/unit-lock, m/tiny-lock): whose lock the work ran under.
seen_field() { awk -F'\t' -v k="$2" '$1 == k { print $2; exit }' "$1" 2>/dev/null; }

# lock_snapshot <tree>   The lock's exact bytes (a trailing `x` keeps the final
# newline through the command substitution), or `absent`.
lock_snapshot() {
  if [ -f "$1/.claude/state/run.lock" ]; then cat "$1/.claude/state/run.lock"; printf 'x'
  else printf 'absent'; fi
}

# leftovers <tree>   How many run.lock and run.lock.* files the tree holds.
leftovers() {
  local n=0 f
  for f in "$1"/.claude/state/run.lock "$1"/.claude/state/run.lock.*; do
    [ -e "$f" ] && n=$((n+1))
  done
  printf '%s' "$n"
}

# present <file>   `present` or `absent`, so a failure message says which.
present() { if [ -e "$1" ]; then printf present; else printf absent; fi; }

# plant <tree> <pid-line-or-empty> <started> <command>   A lock written by hand,
# as a run that died would have left it. An empty pid writes no pid line.
plant() {
  mkdir -p "$1/.claude/state"
  { [ -n "$2" ] && printf 'pid\t%s\n' "$2"
    printf 'started\t%s\ncommand\t%s\n' "$3" "$4"; } > "$1/.claude/state/run.lock"
}

# The three refusal lines of C-2, for <self> refused by <pid> <started> <command>.
refusal1() { printf "run-lock: refusing to start %s: another harness run holds this worktree's lock." "$1"; }
refusal2() { printf 'run-lock:   pid %s, started %s: %s' "$1" "$2" "$3"; }
refusal3() { printf 'run-lock: wait for it to finish. If pid %s is not that run, delete .claude/state/run.lock and run again.' "$1"; }
stale_line() { printf 'run-lock: reclaimed a stale lock from pid %s (%s); that process is no longer running.' "$1" "$2"; }
UNREADABLE='run-lock: reclaimed an unreadable lock (no pid recorded in .claude/state/run.lock).'

# assert_refused <label> <stderr> <self> <pid> <started> <command>   The three
# whole lines, each exactly once.
assert_refused() {
  assert_eq "$1: refusal line 1 names this run ($3)" 1 "$(count_line "$(refusal1 "$3")" "$2")"
  assert_eq "$1: refusal line 2 names the holder (pid $4, $6)" 1 "$(count_line "$(refusal2 "$4" "$5" "$6")" "$2")"
  assert_eq "$1: refusal line 3 gives the remedy for pid $4" 1 "$(count_line "$(refusal3 "$4")" "$2")"
}

# Processes the suite owns: two live ones and one that has exited.
sleep 600 & LIVE1=$!; BG="$BG $LIVE1"
sleep 600 & LIVE2=$!; BG="$BG $LIVE2"
bash -c 'exit 0' & DEAD=$!; wait "$DEAD" 2>/dev/null
PLANT_STARTED="2026-01-02T03:04:05Z"

# ---------------------------------------------------------------------------
describe "AC-1  gates.sh in progress: selftest.sh refuses, runs no suite, and runs once it is gone"

reset "$FIX"
start_holder "$FIX" bash scripts/gates.sh --gate unit
assert_eq "precondition: the holder (gates.sh --gate unit) is in progress, blocked on its release file" yes "$HOLDING"
assert_eq "while it runs, the tree holds .claude/state/run.lock" present "$(present "$FIX/.claude/state/run.lock")"
assert_eq "the lock records the holder's pid" "$HP" "$(lock_field "$FIX" pid)"
assert_eq "the lock records the holder's command, as a literal script path and its arguments" \
  "scripts/gates.sh --gate unit" "$(lock_field "$FIX" command)"
assert_eq "the lock records when it started, as UTC to the second" 1 \
  "$(count_re '^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z$' "$(lock_field "$FIX" started)")"
assert_eq "the lock is exactly three TAB-separated lines: pid, started, command" "pid started command" \
  "$(awk -F'\t' 'NF == 2 { printf "%s%s", s, $1; s = " " } NF != 2 { printf "%s<bad:%s>", s, $0; s = " " }' "$FIX/.claude/state/run.lock" 2>/dev/null)"
assert_eq "C-4: the gate command inherits HARNESS_RUN_LOCK, the absolute path of this tree's lock" \
  "$LOCKA" "$(awk 'NR == 1' "$FIX/m/unit-env" 2>/dev/null)"
assert_eq "C-4: and HARNESS_RUN_LOCK_PID, the pid the lock records" \
  "$HP" "$(awk 'NR == 2' "$FIX/m/unit-env" 2>/dev/null)"
H_STARTED="$(lock_field "$FIX" started)"
before="$(lock_snapshot "$FIX")"

run "$FIX" bash scripts/selftest.sh tiny
assert_eq "selftest.sh tiny, started beside it, exits 2" 2 "$RC"
assert_eq "and runs no suite: tiny's own marker is absent" absent "$(present "$FIX/m/tiny-ran")"
assert_refused "AC-1 selftest beside gates" "$ERR" "scripts/selftest.sh tiny" "$HP" "$H_STARTED" "scripts/gates.sh --gate unit"
assert_eq "the refusal is on stderr, not stdout" 0 "$(count_re '^run-lock:' "$OUT")"
assert_eq "the lock is byte-identical after the refused attempt" "$before" "$(lock_snapshot "$FIX")"

finish_holder "$FIX"
assert_eq "the holder then finishes with its own normal status" 0 "$HRC"
assert_eq "and leaves no lock behind" 0 "$(leftovers "$FIX")"
run "$FIX" bash scripts/selftest.sh tiny
assert_eq "the same selftest.sh tiny, run again after the holder exits, exits 0" 0 "$RC"
assert_eq "and this time runs the suite" present "$(present "$FIX/m/tiny-ran")"

# ---------------------------------------------------------------------------
describe "AC-1  selftest.sh in progress: gates.sh refuses, runs no gate, records nothing"

reset "$FIX"
start_holder "$FIX" bash scripts/selftest.sh slow
assert_eq "precondition: the holder (selftest.sh slow) is in progress, blocked on its release file" yes "$HOLDING"
assert_eq "while it runs, the tree holds .claude/state/run.lock" present "$(present "$FIX/.claude/state/run.lock")"
assert_eq "the lock records the holder's pid" "$HP" "$(lock_field "$FIX" pid)"
assert_eq "the lock records the holder's command" "scripts/selftest.sh slow" "$(lock_field "$FIX" command)"
assert_eq "the suite itself runs while the lock is held" present "$(present "$FIX/m/slow-saw-lock")"
H_STARTED="$(lock_field "$FIX" started)"
before="$(lock_snapshot "$FIX")"
STAMPF="$FIX/.claude/state/last-gate-run"
sentinel="sentinel $$ $RANDOM, written by run-lock.test.sh"
printf '%s\n' "$sentinel" > "$STAMPF"

run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "gates.sh --gate unit, started beside it, exits 2" 2 "$RC"
assert_eq "and the gate command never runs: its marker is absent" absent "$(present "$FIX/m/unit-ran")"
assert_eq "and .claude/state/last-gate-run is not changed" "$sentinel" "$(cat "$STAMPF" 2>/dev/null)"
assert_refused "AC-1 gates beside selftest" "$ERR" "scripts/gates.sh --gate unit" "$HP" "$H_STARTED" "scripts/selftest.sh slow"
assert_eq "the refusal is on stderr, not stdout" 0 "$(count_re '^run-lock:' "$OUT")"
assert_eq "the lock is byte-identical after the refused attempt" "$before" "$(lock_snapshot "$FIX")"

rm -f "$STAMPF"
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "with no last-gate-run before it, a refused gates.sh does not create one" absent "$(present "$STAMPF")"

finish_holder "$FIX"
assert_eq "the holder then finishes with its own normal status" 0 "$HRC"
assert_eq "and leaves no lock behind" 0 "$(leftovers "$FIX")"
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "the same gates.sh --gate unit, run again after the holder exits, exits 0" 0 "$RC"
assert_eq "and this time runs the gate" present "$(present "$FIX/m/unit-ran")"

# ---------------------------------------------------------------------------
describe "AC-2  every way out of gates.sh releases the lock, and an uncontended run says nothing"

reset "$FIX"
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "a passing gate: gates.sh exits 0" 0 "$RC"
assert_eq "the lock was held while the gate command ran" present "$(present "$FIX/m/unit-saw-lock")"
assert_eq "and no run.lock or run.lock.* is left" 0 "$(leftovers "$FIX")"
assert_eq "an uncontended run prints no run-lock: line" 0 "$(count_re '^run-lock:' "$OUT
$ERR")"

reset "$FIX"; touch "$FIX/m/fail"
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "a failing gate: gates.sh exits 1" 1 "$RC"
assert_eq "the lock was held while the gate command ran" present "$(present "$FIX/m/unit-saw-lock")"
assert_eq "and no run.lock or run.lock.* is left" 0 "$(leftovers "$FIX")"
assert_eq "an uncontended failing run prints no run-lock: line" 0 "$(count_re '^run-lock:' "$OUT
$ERR")"

# TERM while the gate command runs (C-3). Trapped, bash waits for its
# foreground child, so the lock is held exactly as long as the work is; then
# the EXIT trap releases it and the script exits 143.
reset "$FIX"
start_holder "$FIX" bash scripts/gates.sh --gate unit
assert_eq "precondition: gates.sh is in progress, blocked in its gate command" yes "$HOLDING"
kill -TERM "$HP" 2>/dev/null
sleep 1
if kill -0 "$HP" 2>/dev/null; then alive=yes; else alive=no; fi
assert_eq "sent TERM, gates.sh waits for its gate command rather than exiting under it" yes "$alive"
assert_eq "and the lock is still held while the gate command runs" present "$(present "$FIX/.claude/state/run.lock")"
finish_holder "$FIX"
assert_eq "once the gate command finishes, gates.sh exits 143" 143 "$HRC"
assert_eq "and the gate command had finished before gates.sh exited" present "$(present "$FIX/m/unit-finished")"
assert_eq "and no run.lock or run.lock.* is left" 0 "$(leftovers "$FIX")"

describe "AC-2  every way out of selftest.sh releases the lock"

reset "$FIX"
run "$FIX" bash scripts/selftest.sh tiny
assert_eq "a passing suite: selftest.sh exits 0" 0 "$RC"
assert_eq "the lock was held while the suite ran" present "$(present "$FIX/m/tiny-saw-lock")"
assert_eq "and no run.lock or run.lock.* is left" 0 "$(leftovers "$FIX")"
assert_eq "an uncontended run prints no run-lock: line" 0 "$(count_re '^run-lock:' "$OUT
$ERR")"

reset "$FIX"
run "$FIX" bash scripts/selftest.sh failing
assert_eq "a failing suite: selftest.sh exits 1" 1 "$RC"
assert_eq "the lock was held while the suite ran" present "$(present "$FIX/m/failing-saw-lock")"
assert_eq "and no run.lock or run.lock.* is left" 0 "$(leftovers "$FIX")"
assert_eq "an uncontended failing run prints no run-lock: line" 0 "$(count_re '^run-lock:' "$OUT
$ERR")"

# ---------------------------------------------------------------------------
describe "AC-3  a lock whose holder is gone is reclaimed, once, and the run proceeds"

assert_eq "precondition: the dead pid really is not running" no \
  "$(if kill -0 "$DEAD" 2>/dev/null; then printf yes; else printf no; fi)"
assert_eq "precondition: the live pid really is running" yes \
  "$(if kill -0 "$LIVE1" 2>/dev/null; then printf yes; else printf no; fi)"

reset "$FIX"
plant "$FIX" "$DEAD" "$PLANT_STARTED" "scripts/selftest.sh ghost"
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "gates.sh over a dead holder's lock prints the reclaim line exactly once" 1 \
  "$(count_line "$(stale_line "$DEAD" "scripts/selftest.sh ghost")" "$ERR")"
assert_eq "and no refusal" 0 "$(count_re '^run-lock: refusing' "$ERR")"
assert_eq "runs the gate" present "$(present "$FIX/m/unit-ran")"
assert_eq "under its own lock, not the dead holder's: the lock it ran under names gates.sh --gate unit" \
  "scripts/gates.sh --gate unit" "$(seen_field "$FIX/m/unit-lock" command)"
assert_eq "exits 0" 0 "$RC"
assert_eq "and leaves no lock" 0 "$(leftovers "$FIX")"

reset "$FIX"
plant "$FIX" "" "$PLANT_STARTED" "scripts/selftest.sh ghost"
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "gates.sh over a lock with no pid line prints the unreadable-lock line exactly once" 1 \
  "$(count_line "$UNREADABLE" "$ERR")"
assert_eq "runs the gate" present "$(present "$FIX/m/unit-ran")"
assert_eq "exits 0" 0 "$RC"
assert_eq "and leaves no lock" 0 "$(leftovers "$FIX")"

reset "$FIX"
plant "$FIX" "not-a-pid" "$PLANT_STARTED" "scripts/selftest.sh ghost"
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "gates.sh over a lock whose pid is not all digits prints the unreadable-lock line exactly once" 1 \
  "$(count_line "$UNREADABLE" "$ERR")"
assert_eq "runs the gate" present "$(present "$FIX/m/unit-ran")"
assert_eq "exits 0" 0 "$RC"
assert_eq "and leaves no lock" 0 "$(leftovers "$FIX")"

reset "$FIX"
plant "$FIX" "$DEAD" "$PLANT_STARTED" "scripts/gates.sh --gate ghost"
run "$FIX" bash scripts/selftest.sh tiny
assert_eq "selftest.sh over a dead holder's lock prints the reclaim line exactly once" 1 \
  "$(count_line "$(stale_line "$DEAD" "scripts/gates.sh --gate ghost")" "$ERR")"
assert_eq "runs the suite" present "$(present "$FIX/m/tiny-ran")"
assert_eq "under its own lock, not the dead holder's: the lock it ran under names selftest.sh tiny" \
  "scripts/selftest.sh tiny" "$(seen_field "$FIX/m/tiny-lock" command)"
assert_eq "exits 0" 0 "$RC"
assert_eq "and leaves no lock" 0 "$(leftovers "$FIX")"

reset "$FIX"
plant "$FIX" "" "$PLANT_STARTED" "scripts/gates.sh --gate ghost"
run "$FIX" bash scripts/selftest.sh tiny
assert_eq "selftest.sh over a lock with no pid line prints the unreadable-lock line exactly once" 1 \
  "$(count_line "$UNREADABLE" "$ERR")"
assert_eq "runs the suite" present "$(present "$FIX/m/tiny-ran")"
assert_eq "exits 0" 0 "$RC"
assert_eq "and leaves no lock" 0 "$(leftovers "$FIX")"

describe "AC-3  control: the same lock with a LIVE pid is refused, not reclaimed"

reset "$FIX"
plant "$FIX" "$LIVE1" "$PLANT_STARTED" "scripts/selftest.sh ghost"
before="$(lock_snapshot "$FIX")"
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "gates.sh over a live holder's lock exits 2" 2 "$RC"
assert_refused "AC-3 control, gates" "$ERR" "scripts/gates.sh --gate unit" "$LIVE1" "$PLANT_STARTED" "scripts/selftest.sh ghost"
assert_eq "and does not print the reclaim line" 0 "$(count_re '^run-lock: reclaimed' "$ERR")"
assert_eq "the gate command never runs" absent "$(present "$FIX/m/unit-ran")"
assert_eq "the lock is byte-identical afterwards" "$before" "$(lock_snapshot "$FIX")"

run "$FIX" bash scripts/selftest.sh tiny
assert_eq "selftest.sh over a live holder's lock exits 2" 2 "$RC"
assert_refused "AC-3 control, selftest" "$ERR" "scripts/selftest.sh tiny" "$LIVE1" "$PLANT_STARTED" "scripts/selftest.sh ghost"
assert_eq "no suite runs" absent "$(present "$FIX/m/tiny-ran")"
assert_eq "the lock is byte-identical afterwards" "$before" "$(lock_snapshot "$FIX")"

# ---------------------------------------------------------------------------
describe "AC-4  --list, --audit and --help read the manifest and are not gated"

# Green on arrival, and deliberately: today there is no lock to obey. These
# guard against the lock being taken too early - above the argument loop, or
# before the --list/--audit dispatch - which would gag the manifest-only modes
# CI and ci-local.sh run beside a gate run.
for mode in --list --audit --help; do
  reset "$FIX"
  run "$FIX" bash scripts/gates.sh "$mode"; o0="$OUT
$ERR"; r0="$RC"
  plant "$FIX" "$LIVE1" "$PLANT_STARTED" "scripts/selftest.sh ghost"
  before="$(lock_snapshot "$FIX")"
  run "$FIX" bash scripts/gates.sh "$mode"
  if [ "$o0" = "$OUT
$ERR" ] && [ "$r0" = "$RC" ]; then
    _ok "gates.sh $mode under a live lock: output and exit status ($RC) identical to no lock"
  else
    _bad "gates.sh $mode under a live lock: output and exit status ($RC) identical to no lock" \
      "without a lock: rc=$r0
with a lock:    rc=$RC
$(diff <(printf '%s\n' "$o0") <(printf '%s\n%s\n' "$OUT" "$ERR") 2>&1 | awk 'NR <= 10')"
  fi
  assert_eq "gates.sh $mode leaves the lock byte-identical" "$before" "$(lock_snapshot "$FIX")"
done

# ---------------------------------------------------------------------------
describe "AC-5  the lock is keyed to the tree, and another tree's markers are not adopted"

reset "$FIX"; reset "$FIXB"
plant "$FIX" "$LIVE1" "$PLANT_STARTED" "scripts/selftest.sh ghost"
beforeA="$(lock_snapshot "$FIX")"
run "$FIXB" bash scripts/gates.sh --gate unit
assert_eq "with tree A locked by a live holder, gates.sh in tree B exits 0" 0 "$RC"
assert_eq "runs B's gate" present "$(present "$FIXB/m/unit-ran")"
assert_eq "and prints no run-lock: line" 0 "$(count_re '^run-lock:' "$OUT
$ERR")"

reset "$FIXB"
run "$FIXB" env HARNESS_RUN_LOCK="$LOCKA" HARNESS_RUN_LOCK_PID="$LIVE1" bash scripts/gates.sh --gate unit
assert_eq "with A's lock and live holder exported as the markers, B still exits 0" 0 "$RC"
assert_eq "B takes its OWN lock: its gate command sees B/.claude/state/run.lock" present "$(present "$FIXB/m/unit-saw-lock")"
assert_eq "and the markers B's gate command inherits name B's lock, not A's" \
  "$(cd "$FIXB" && pwd)/.claude/state/run.lock" "$(awk 'NR == 1' "$FIXB/m/unit-env" 2>/dev/null)"
assert_eq "B leaves no lock behind" 0 "$(leftovers "$FIXB")"
assert_eq "B prints no run-lock: line" 0 "$(count_re '^run-lock:' "$OUT
$ERR")"
assert_eq "and A's lock is byte-identical" "$beforeA" "$(lock_snapshot "$FIX")"

# ---------------------------------------------------------------------------
describe "AC-6  a run nested in the same tree, under the holder, is let through"

reset "$FIX"
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | bash scripts/selftest.sh tiny
evidence | unit | [1-9][0-9]* harness suite\(s\) passed
EOF
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "a gate whose command is selftest.sh tiny is reported PASS" 1 "$(count_re '^PASS +unit \(' "$OUT")"
assert_eq "gates.sh exits 0" 0 "$RC"
assert_eq "the nested suite ran while the parent's lock was held" present "$(present "$FIX/m/tiny-saw-lock")"
assert_eq "and it is the parent's lock: the nested run took none of its own" \
  "scripts/gates.sh --gate unit" "$(seen_field "$FIX/m/tiny-lock" command)"
assert_eq "and no lock is left" 0 "$(leftovers "$FIX")"

describe "AC-6  control: without the markers the nested run is refused by its own parent"

reset "$FIX"
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | env -u HARNESS_RUN_LOCK -u HARNESS_RUN_LOCK_PID bash scripts/selftest.sh tiny
evidence | unit | [1-9][0-9]* harness suite\(s\) passed
EOF
run "$FIX" bash scripts/gates.sh --gate unit
assert_eq "the same gate with the markers removed is reported FAIL" 1 "$(count_re '^FAIL +unit ' "$OUT")"
assert_eq "gates.sh exits 1" 1 "$RC"
LOGTXT="$(cat "$FIX/.claude/state/gate-logs/unit.log" 2>/dev/null)"
assert_eq "its gate log carries refusal line 1, naming the nested selftest.sh tiny" 1 \
  "$(count_line "$(refusal1 'scripts/selftest.sh tiny')" "$LOGTXT")"
assert_eq "and refusal line 2, naming the holder: scripts/gates.sh --gate unit" 1 \
  "$(count_re '^run-lock:   pid [0-9]+, started [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z: scripts/gates\.sh --gate unit$' "$LOGTXT")"
assert_eq "the suite never ran" absent "$(present "$FIX/m/tiny-ran")"
assert_eq "and no lock is left" 0 "$(leftovers "$FIX")"
conf_unit "$FIX"

describe "AC-6  the markers are not a bypass: the pid must be the one the lock records"

reset "$FIX"
plant "$FIX" "$LIVE1" "$PLANT_STARTED" "scripts/gates.sh --gate unit"
before="$(lock_snapshot "$FIX")"
run "$FIX" env HARNESS_RUN_LOCK="$LOCKA" HARNESS_RUN_LOCK_PID="$LIVE2" bash scripts/selftest.sh tiny
assert_eq "right lock path, another live pid: selftest.sh exits 2" 2 "$RC"
assert_refused "AC-6 wrong-pid marker" "$ERR" "scripts/selftest.sh tiny" "$LIVE1" "$PLANT_STARTED" "scripts/gates.sh --gate unit"
assert_eq "no suite runs" absent "$(present "$FIX/m/tiny-ran")"
assert_eq "the lock is byte-identical afterwards" "$before" "$(lock_snapshot "$FIX")"

# C-4's positive half, with the holder planted: the right path and the right
# live pid proceed without taking, releasing or printing anything. A nested run
# that released on exit would delete its parent's lock.
run "$FIX" env HARNESS_RUN_LOCK="$LOCKA" HARNESS_RUN_LOCK_PID="$LIVE1" bash scripts/selftest.sh tiny
assert_eq "right lock path and the recorded live pid: selftest.sh exits 0" 0 "$RC"
assert_eq "the suite runs" present "$(present "$FIX/m/tiny-ran")"
assert_eq "nothing is printed by the lock" 0 "$(count_re '^run-lock:' "$OUT
$ERR")"
assert_eq "and the parent's lock is byte-identical afterwards, not released by the child" "$before" "$(lock_snapshot "$FIX")"

# ---------------------------------------------------------------------------
describe "AC-7  state and suite hygiene, in this repository"

README="$REPO_ROOT/.claude/state/README.md"
# state_row <path cell>   Table rows with that path cell whose last cell is yes.
state_row() {
  local p; p="$(printf '%s' "$1" | sed 's/[.*]/\\&/g')"
  tr -d '\r' < "$README" | grep -cE -- "^\\| \`$p\` +\\|.*\\| yes +\\|\$"
}
assert_eq "README has one run.lock row, hand-editable yes" 1 "$(state_row 'run.lock')"
assert_eq "README has one run.lock.<pid> row, hand-editable yes" 1 "$(state_row 'run.lock.<pid>')"
assert_eq "control: the same reader finds the existing mutations/*.active row" 1 "$(state_row 'mutations/*.active')"

git -C "$REPO_ROOT" check-ignore -q --no-index .claude/state/run.lock; rc=$?
assert_eq ".claude/state/run.lock is gitignored here" 0 "$rc"
git -C "$REPO_ROOT" check-ignore -q --no-index .claude/state/run.lock.12345; rc=$?
assert_eq ".claude/state/run.lock.<pid> is gitignored here" 0 "$rc"
git -C "$REPO_ROOT" check-ignore -q --no-index .claude/state/README.md; rc=$?
assert_eq "control: the same check reports .claude/state/README.md as not ignored" 1 "$rc"

# C-3 pins this line, exactly, because DV-1's single sed expression targets it.
assert_eq "scripts/run-lock.sh defines run_lock_alive on exactly the one line DV-1 mutates" 1 \
  "$(grep -cxF 'run_lock_alive() { kill -0 "$1" 2>/dev/null; }' "$REPO_ROOT/scripts/run-lock.sh" 2>/dev/null)"

summary "run-lock"
