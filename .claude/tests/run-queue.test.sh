#!/usr/bin/env bash
# Tests for the machine-wide run queue (HARNESS-108, HARNESS-111): a run that
# queues - a FULL scripts/gates.sh or scripts/selftest.sh run, or any
# scripts/selftest.sh --changed run that gets as far as the run lock - waits
# for any other such run anywhere on the machine - another tree, another
# session - instead of running beside it, and says that it is queued and
# behind what. One lock file per user per machine,
# ${HARNESS_RUN_QUEUE_DIR:-$HOME/.cache/agentic-harness}/run-queue.lock, joined
# inside scripts/run-lock.sh (HARNESS-108 Contract C-1..C-7). Which commands
# queue is run_lock_queues (HARNESS-111 C-2); run_lock_full still says which
# are full, and a --changed run is not one.
#
# The measurement behind it: two refresh self-tests beside another session's
# runs took over three hours; the same self-test takes three to four minutes
# on CI, where it has the machine to itself.
#
# THE QUEUE IS NEVER THE HOST'S. _lib.sh exports HARNESS_RUN_QUEUE=off (AC-7);
# this suite turns the queue on PER CALL, in rq_run's subshell, always with
# HARNESS_RUN_QUEUE_DIR pointing into its own temp directory. The one case that
# unsets HARNESS_RUN_QUEUE_DIR (AC-9) unsets HOME with it, so no case can reach
# $HOME/.cache. Under the real selftest.sh this suite may inherit
# HARNESS_RUN_QUEUE_LOCK / _PID naming the host's queue; they name a different
# path from every queue here, no case depends on their absence, and the cases
# that are about them (AC-6) set them explicitly.
#
# CONCURRENCY IS OBSERVED BY THE RUNS THEMSELVES, NEVER BY THE CLOCK (C-8).
# Every gate command and every fixture suite is m/work.sh. As it starts it
# makes $SH/run.<tree> and records which OTHER trees' run.<tree> exist
# (m/k/overlap-start) and which trees have finished (m/k/done-before); as it
# ends it records the others again (m/k/overlap-end), then marks itself done.
# Because each run makes its own marker BEFORE looking for the others, two
# runs whose work overlaps at all are seen by at least one of them, whatever
# the timing. A HOLDER is a run whose work waits for m/k/release, which the
# test writes. "Has not started" is asserted only after the waiter's queued
# line (or its own start) has appeared, plus at least two poll intervals -
# never after a bare sleep. Every wait is bounded; a defect that waits for
# ever costs the bound and fails, it does not hang the suite.
#
# NEEDLES. C-3's lines are compared WHOLE (grep -cxF), because every one of
# them begins `run-queue: ` and a floating prefix would be satisfied by the
# wrong one. The two lines that carry a duration are matched as a fixed prefix
# plus an anchored span pattern. Exit statuses are exact: 0, 2, 143.
#
# RED: scripts/run-queue.sh and run_lock_full do not exist. The direct cases
# test for them first and fail ONE assertion per row in the if and the else
# alike, so the executed count is the same in RED and GREEN. The cases through
# gates.sh and selftest.sh fail for the right reason on their own: nothing
# queues, so B runs beside A. AC-10's "starts at once" assertions and AC-7's
# queue-off control pass on arrival in RED; DV-3 earns the first at GATES.
#
# HARNESS-111 (--changed). Three more trees, X, Y and Z, each a git checkout
# with a `main` and a story branch, so that `selftest.sh --changed` selects
# what the case says: X every suite (an unmapped x.conf), Y a proper subset
# (m.conf, mentioned by `work` only), Z no suite (a source-only commit). Every
# --changed case asserts its header line first, so a fixture whose selection
# drifted fails as that, not as a queue defect. In RED run_lock_queues does
# not exist and --changed never queues: its table rows fail one assertion
# each in the if and the else alike, and the cases through selftest.sh fail
# on their own - B runs beside A. AC-3 (nested --changed) and AC-4 (no suite)
# pass on arrival; DV-3 and DV-4 earn them at GATES.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

W="$(mktemp -d 2>/dev/null || mktemp -d -t runqueue.XXXXXX)"
W="$(cd "$W" && pwd)"
SH="$W/sh"                 # the shared run markers every tree's work.sh writes
Q="$W/q"                   # the queue directory every queue-on run is given
QL="$Q/run-queue.lock"     # its lock
BG=""                      # every background pid this suite starts; reaped on EXIT
POLL=1                     # HARNESS_RUN_QUEUE_POLL for every queue-on run
A=""; B=""; C=""           # the three trees, set below
X=""; Y=""; Z=""           # the three --changed trees (HARNESS-111), set below

# release_all   Lets every held work.sh in every tree finish.
release_all() {
  local t
  for t in "$A" "$B" "$C" "$X" "$Y" "$Z"; do [ -n "$t" ] && [ -d "$t/m/k" ] && touch "$t/m/k/release"; done
  return 0
}

cleanup() {
  local p t f
  release_all
  for t in "$A" "$B" "$C" "$X" "$Y" "$Z"; do
    [ -n "$t" ] || continue
    for f in "$t"/m/k/n*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
  done
  for p in $BG; do kill "$p" 2>/dev/null; done
  for p in $BG; do wait "$p" 2>/dev/null; done
  rm -rf "$A" "$B" "$C" "$X" "$Y" "$Z" "$W"
}
trap cleanup EXIT

# --- the fixture -------------------------------------------------------------

# fixture_setup <tree> <name>   m/work.sh is the one piece of work every run
# does: the gate `unit`, and the fixture's one suite `work`. `lint` is a
# second gate so that `--skip lint` still runs `unit`. The fixture's
# .claude/tests holds the REAL _lib.sh, work.test.sh and a floors.conf naming
# it, so the fixture's full selftest.sh passes its own floors audit and exits 0.
fixture_setup() {
  local t="$1" n="$2"
  mkdir -p "$t/m/k" "$t/.claude/tests" "$t/.claude/state"
  cp "$REPO_ROOT/.claude/tests/_lib.sh" "$t/.claude/tests/_lib.sh"
  { printf '#!/usr/bin/env bash\n'
    printf "SH='%s'\nN='%s'\nK='%s'\n" "$SH" "$n" "$t/m/k"
    cat <<'WORK'
others() {
  local d o=""
  for d in "$SH"/run.*; do
    [ -d "$d" ] || continue
    [ "$d" = "$SH/run.$N" ] || o="$o ${d##*/run.}"
  done
  printf '%s\n' "${o# }"
}
mkdir "$SH/run.$N" 2>/dev/null
others > "$K/overlap-start"
d=""
for f in "$SH"/done.*; do [ -e "$f" ] && d="$d ${f##*/done.}"; done
printf '%s\n' "${d# }" > "$K/done-before"
if [ -n "${HARNESS_RUN_QUEUE_DIR-}" ]; then
  cp "$HARNESS_RUN_QUEUE_DIR/run-queue.lock" "$K/qlock" 2>/dev/null
fi
touch "$K/started"
if [ -f "$K/hold" ]; then
  i=0
  while [ ! -f "$K/release" ] && [ "$i" -lt 600 ]; do sleep 0.2; i=$((i+1)); done
fi
others > "$K/overlap-end"
touch "$SH/done.$N"
rmdir "$SH/run.$N" 2>/dev/null
touch "$K/finished"
printf 'Tests  1 passed (1)\n'
WORK
  } > "$t/m/work.sh"
  printf '#!/usr/bin/env bash\nprintf '"'"'Tests  1 passed (1)\\n'"'"'\n' > "$t/m/lint.sh"

  cat > "$t/.claude/tests/work.test.sh" <<'SUITE'
#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
bash "$REPO_ROOT/m/work.sh" > /dev/null
assert_eq "work" x x
summary "work"
SUITE
  printf 'floor | work | 1\n' > "$t/.claude/tests/floors.conf"
  conf_work "$t"
}

# conf_work <tree>   Two required gates: unit (m/work.sh) and lint.
conf_work() {
  write_conf "$1" <<'EOF'
gate     | unit | required | . | bash m/work.sh
evidence | unit | Tests +[1-9][0-9]* passed
gate     | lint | required | . | bash m/lint.sh
evidence | lint | Tests +[1-9][0-9]* passed
EOF
}

A="$(make_project_fixture)"; A="$(cd "$A" && pwd)"
B="$(make_project_fixture)"; B="$(cd "$B" && pwd)"
C="$(make_project_fixture)"; C="$(cd "$C" && pwd)"
fixture_setup "$A" A
fixture_setup "$B" B
fixture_setup "$C" C

# nest.sh, A's gate command for AC-6: a full selftest.sh in A, then one in B,
# each in the background with its pid recorded (so cleanup can reach an inner
# run that waits on its own ancestor), each run's status and the queue lock as
# it stands after each run recorded.
{ printf '#!/usr/bin/env bash\n'
  printf "K='%s'\nTB='%s'\n" "$A/m/k" "$B"
  cat <<'NEST'
bash scripts/selftest.sh > "$K/n1.out" 2> "$K/n1.err" < /dev/null &
echo "$!" > "$K/n1.pid"; wait "$!"; echo "$?" > "$K/n1.rc"
cp "$HARNESS_RUN_QUEUE_DIR/run-queue.lock" "$K/n1.qlock" 2>/dev/null
( cd "$TB" && exec bash scripts/selftest.sh ) > "$K/n2.out" 2> "$K/n2.err" < /dev/null &
echo "$!" > "$K/n2.pid"; wait "$!"; echo "$?" > "$K/n2.rc"
cp "$HARNESS_RUN_QUEUE_DIR/run-queue.lock" "$K/n2.qlock" 2>/dev/null
printf 'Tests  1 passed (1)\n'
NEST
} > "$A/m/nest.sh"

# --- the --changed trees (HARNESS-111, C-5) ----------------------------------
# changed_setup <tree> <name> <change>   fixture_setup, plus what --changed
# needs: two suites, `work` (m/work.sh, and its source mentions
# .claude/harness/m.conf) and `other` (mentions nothing); one gate, unit, that
# is m/work.sh unless m/k/nest exists, then m/nest.sh; m/k/ and .claude/state/
# ignored; all of it committed on `main`; then a story branch carrying one
# committed change:
#   every   .claude/harness/x.conf, mapped by no rule  -> every suite
#   subset  .claude/harness/m.conf, mentioned by work  -> work only
#   none    src/app.ts, a source path                  -> no suite
# The work tree is clean afterwards, so the selection cannot drift as runs
# write their markers and their state.
cgit() { git -C "$1" -c user.email=t@t -c user.name=t "${@:2}"; }
changed_setup() {
  local t="$1" n="$2"
  fixture_setup "$t" "$n"
  cat > "$t/.claude/tests/work.test.sh" <<'SUITE'
#!/usr/bin/env bash
# reads .claude/harness/m.conf
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
bash "$REPO_ROOT/m/work.sh" > /dev/null
assert_eq "work" x x
summary "work"
SUITE
  cat > "$t/.claude/tests/other.test.sh" <<'SUITE'
#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
assert_eq "other" x x
summary "other"
SUITE
  printf 'floor | other | 1\nfloor | work  | 1\n' > "$t/.claude/tests/floors.conf"
  printf '#!/usr/bin/env bash\nif [ -f m/k/nest ]; then exec bash m/nest.sh; fi\nexec bash m/work.sh\n' > "$t/m/gate.sh"
  write_conf "$t" <<'EOF'
gate     | unit | required | . | bash m/gate.sh
evidence | unit | Tests +[1-9][0-9]* passed
gate     | lint | required | . | bash m/lint.sh
evidence | lint | Tests +[1-9][0-9]* passed
EOF
  printf '.claude/state/\nm/k/\n' >> "$t/.gitignore"
  cgit "$t" branch -M main >/dev/null 2>&1
  cgit "$t" add -A >/dev/null 2>&1
  cgit "$t" commit -qm "two suites" >/dev/null 2>&1
  cgit "$t" checkout -q -b story/T-1-fixture >/dev/null 2>&1
  case "$3" in
    every)  printf 'x\n' > "$t/.claude/harness/x.conf" ;;
    subset) printf 'm\n' > "$t/.claude/harness/m.conf" ;;
    none)   mkdir -p "$t/src"; printf 'export const a = 1\n' > "$t/src/app.ts" ;;
  esac
  cgit "$t" add -A >/dev/null 2>&1
  cgit "$t" commit -qm "the change" >/dev/null 2>&1
}
X="$(make_project_fixture)"; X="$(cd "$X" && pwd)"
Y="$(make_project_fixture)"; Y="$(cd "$Y" && pwd)"
Z="$(make_project_fixture)"; Z="$(cd "$Z" && pwd)"

# X's m/nest.sh, X's gate command for HARNESS-111 AC-3 once m/k/nest exists:
# selftest.sh --changed in X (the holder's own tree), then in Y, each in the
# background with its pid recorded, each run's status and the queue lock as it
# stands after each run recorded - the shape of A's nest.sh above. Written
# before changed_setup, so that it is committed on main with the rest.
mkdir -p "$X/m"
{ printf '#!/usr/bin/env bash\n'
  printf "K='%s'\nTB='%s'\n" "$X/m/k" "$Y"
  cat <<'NEST'
bash scripts/selftest.sh --changed > "$K/n1.out" 2> "$K/n1.err" < /dev/null &
echo "$!" > "$K/n1.pid"; wait "$!"; echo "$?" > "$K/n1.rc"
cp "$HARNESS_RUN_QUEUE_DIR/run-queue.lock" "$K/n1.qlock" 2>/dev/null
( cd "$TB" && exec bash scripts/selftest.sh --changed ) > "$K/n2.out" 2> "$K/n2.err" < /dev/null &
echo "$!" > "$K/n2.pid"; wait "$!"; echo "$?" > "$K/n2.rc"
cp "$HARNESS_RUN_QUEUE_DIR/run-queue.lock" "$K/n2.qlock" 2>/dev/null
printf 'Tests  1 passed (1)\n'
NEST
} > "$X/m/nest.sh"

changed_setup "$X" X every
changed_setup "$Y" Y subset
changed_setup "$Z" Z none

# The header line each selection prints on stdout before the run lock: the
# precondition every --changed case asserts first.
HDR_X="selftest: --changed — every suite: .claude/harness/x.conf is mapped by no rule; defaulting to every suite"
HDR_Y="selftest: --changed — 1 of 2 suite(s) selected: work"
HDR_Z="selftest: --changed selected no suite — selftest-needed: skip — no harness path among 1 changed path(s) against main (merge-base $(git -C "$Z" rev-parse --short main 2>/dev/null)); CI runs the self-test on the PR"
CHG="scripts/selftest.sh --changed"

# --- instruments -------------------------------------------------------------

present()  { if [ -e "$1" ]; then printf present; else printf absent; fi; }
is_alive() { if kill -0 "$1" 2>/dev/null; then printf alive; else printf gone; fi; }
readf()    { cat "$1" 2>/dev/null; }

# count_line <exact line> <file>   Whole-line occurrences.
count_line() { grep -cxF -- "$1" "$2" 2>/dev/null; }
# count_re <ere> <file>
count_re()   { awk -v re="$1" '$0 ~ re { n++ } END { print n + 0 }' "$2" 2>/dev/null; }
# count_span <fixed prefix> <ere for the rest> <file>   Lines that begin with
# the prefix verbatim and whose remainder matches the anchored pattern.
count_span() {
  awk -v p="$1" -v re="$2" 'index($0, p) == 1 && substr($0, length(p) + 1) ~ re { n++ } END { print n + 0 }' "$3" 2>/dev/null
}
# rq_lines <file>   The run-queue: lines of a file, in order.
rq_lines() { awk 'index($0, "run-queue:") == 1' "$1" 2>/dev/null; }
first_rq() { rq_lines "$1" | awk 'NR == 1'; }
last_rq()  { rq_lines "$1" | awk '{ l = $0 } END { print l }'; }
at_least() { if [ "$2" -ge "$1" ] 2>/dev/null; then printf yes; else printf 'no (%s)' "$2"; fi; }

# rec_field <record file> <key>   One TAB-separated field of a queue record.
rec_field() { awk -F'\t' -v k="$2" '$1 == k { print $2; exit }' "$1" 2>/dev/null; }
rec_keys()  { awk -F'\t' 'NF == 2 { printf "%s%s", s, $1; s = " " } NF != 2 { printf "%s<bad:%s>", s, $0; s = " " }' "$1" 2>/dev/null; }

# qsnap   Every file in the queue directory, name and exact bytes; empty when
# the directory holds nothing.
qsnap() {
  local f
  [ -d "$Q" ] || { printf 'no-dir'; return 0; }
  for f in "$Q"/* "$Q"/.[!.]*; do
    [ -e "$f" ] || continue
    printf '%s:' "${f##*/}"; cat "$f"; printf '|'
  done
  return 0
}

# qlock   The queue lock's own exact bytes, or <no lock>. For comparing the
# lock while a waiter is alive: a waiter writes and removes its temporary
# record run-queue.lock.<pid> on every poll, so qsnap - the whole directory -
# would race it (R-1). Where no waiter is alive, qsnap is the stronger check.
qlock() {
  if [ -f "$QL" ]; then cat "$QL"; printf '|eof'; else printf '<no lock>'; fi
}

# qplant <pid-or-empty> <started> <command> <root> [dir]   A queue lock
# written by hand. An empty pid writes no pid line.
qplant() {
  local d="${5:-$Q}"
  mkdir -p "$d"
  { [ -n "$1" ] && printf 'pid\t%s\n' "$1"
    printf 'started\t%s\ncommand\t%s\nroot\t%s\n' "$2" "$3" "$4"; } > "$d/run-queue.lock"
}

# leftovers <tree>   run.lock and run.lock.* files in the tree.
leftovers() {
  local n=0 f
  for f in "$1"/.claude/state/run.lock "$1"/.claude/state/run.lock.*; do
    [ -e "$f" ] && n=$((n+1))
  done
  printf '%s' "$n"
}

# wait_until <seconds> <cmd> [args]   Polls every 0.2 s. 0 once cmd succeeds.
wait_until() {
  local n=$(( $1 * 5 )) i=0; shift
  while ! "$@"; do
    i=$((i+1)); [ "$i" -ge "$n" ] && return 1
    sleep 0.2
  done
  return 0
}
is_started()        { [ -e "$1/m/k/started" ]; }
is_queued()         { [ "$(count_re '^run-queue: queued: ' "$1")" -gt 0 ]; }
started_or_queued() { is_started "$1" || is_queued "$2"; }

# wait_bounded <pid> <seconds>   Waits for a child of this shell. Sets WRC to
# its status and WTO to yes if it outlived the bound - in which case every
# holder is released and it is sent TERM, then KILL.
WRC=""; WTO=""
wait_bounded() {
  local i=0 n=$(( $2 * 5 ))
  while kill -0 "$1" 2>/dev/null && [ "$i" -lt "$n" ]; do sleep 0.2; i=$((i+1)); done
  if kill -0 "$1" 2>/dev/null; then
    WTO=yes
    release_all
    kill -TERM "$1" 2>/dev/null
    i=0
    while kill -0 "$1" 2>/dev/null && [ "$i" -lt 50 ]; do sleep 0.2; i=$((i+1)); done
    kill -KILL "$1" 2>/dev/null
  else
    WTO=no
  fi
  wait "$1" 2>/dev/null; WRC=$?
}

# The queue environment of the next rq_run. rq_defaults: queue on (empty
# HARNESS_RUN_QUEUE), this suite's $Q, nothing else set.
RQ_MODE=""; RQ_DIR=""; RQ_XLOCK=""; RQ_XPID=""; RQ_NOHOME=""; RQ_CI=""
rq_defaults() { RQ_MODE=""; RQ_DIR="$Q"; RQ_XLOCK=""; RQ_XPID=""; RQ_NOHOME=""; RQ_CI=""; }

# rq_run <var> <tree> <name> <script> [args...]   Starts `bash <script>` in the
# tree, in the background, with the queue environment above; stdout and stderr
# to $W/<name>.out and $W/<name>.err. `exec`, so <var> gets the script's own
# pid - the pid a queue record holds and the one a TERM must reach.
rq_run() {
  local __rv="$1" __rt="$2" __ro="$W/$3"; shift 3
  rm -f "$__ro.out" "$__ro.err"
  ( cd "$__rt" || exit 97
    if [ "$RQ_MODE" = "<unset>" ]; then unset HARNESS_RUN_QUEUE
    else HARNESS_RUN_QUEUE="$RQ_MODE"; export HARNESS_RUN_QUEUE; fi
    if [ "$RQ_DIR" = "<unset>" ]; then unset HARNESS_RUN_QUEUE_DIR
    else HARNESS_RUN_QUEUE_DIR="$RQ_DIR"; export HARNESS_RUN_QUEUE_DIR; fi
    HARNESS_RUN_QUEUE_POLL="$POLL"; HARNESS_RUN_QUEUE_HEARTBEAT=1
    export HARNESS_RUN_QUEUE_POLL HARNESS_RUN_QUEUE_HEARTBEAT
    if [ -n "$RQ_XLOCK" ]; then HARNESS_RUN_QUEUE_LOCK="$RQ_XLOCK"; export HARNESS_RUN_QUEUE_LOCK; fi
    if [ -n "$RQ_XPID" ]; then HARNESS_RUN_QUEUE_PID="$RQ_XPID"; export HARNESS_RUN_QUEUE_PID; fi
    if [ -n "$RQ_NOHOME" ]; then unset HOME; fi
    if [ -n "$RQ_CI" ]; then CI="$RQ_CI"; export CI; fi
    exec bash "$@" ) > "$__ro.out" 2> "$__ro.err" < /dev/null &
  printf -v "$__rv" '%s' "$!"
  BG="$BG $!"
}

# hold_run <var> <tree> <name> <script> [args...]   rq_run, with the tree's
# work held on m/k/release. HOLDING is yes once the work reported itself started.
HOLDING=no
hold_run() {
  local __ht="$2"
  touch "$__ht/m/k/hold"
  rq_run "$@"
  if wait_until 60 is_started "$__ht"; then HOLDING=yes; else HOLDING=no; fi
  rm -f "$__ht/m/k/hold"
}

# new_case   Empty queue directory, no shared markers, every tree's markers
# and run lock gone, the default queue environment.
new_case() {
  local t
  rm -rf "$Q" "$SH"; mkdir -p "$Q" "$SH"
  for t in "$A" "$B" "$C" "$X" "$Y" "$Z"; do
    [ -n "$t" ] || continue
    rm -rf "$t/m/k"; mkdir -p "$t/m/k"
    rm -f "$t"/.claude/state/run.lock*
  done
  rq_defaults
}

# C-3's lines. <self> is the waiting run's command string.
q1() { printf 'run-queue: queued: %s waits for another harness run on this machine to finish.' "$1"; }
q2() { printf 'run-queue:   behind pid %s, started %s, in %s: %s' "$1" "$2" "$3" "$4"; }   # pid started root command
q3() { printf 'run-queue: this is waiting, not hanging: it starts by itself when that run ends. If pid %s is not that run, delete %s and it starts.' "$1" "$2"; }
hb_prefix() { printf 'run-queue: still queued behind pid %s in %s: %s (waited ' "$1" "$2" "$3"; }
HB_RE='^[0-9]+m[0-5][0-9]s\)$'
start_prefix() { printf 'run-queue: starting %s after waiting ' "$1"; }
START_RE='^[0-9]+m[0-5][0-9]s\.$'
stale_line()  { printf 'run-queue: reclaimed a stale queue lock from pid %s (%s, in %s); that process is no longer running.' "$1" "$2" "$3"; }
unread_line() { printf 'run-queue: reclaimed an unreadable queue lock (no pid recorded in %s).' "$1"; }
cannot_line() { printf 'run-queue: cannot use %s; %s runs without the machine-wide queue.' "$1" "$2"; }
nohome_line() { printf 'run-queue: neither HARNESS_RUN_QUEUE_DIR nor HOME is set; %s runs without the machine-wide queue.' "$1"; }
missing_line(){ printf 'run-queue: scripts/run-queue.sh is missing; %s runs without the machine-wide queue.' "$1"; }
UTC_RE='^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z$'

# Processes the suite owns: two live ones that are not harness runs, and one
# that has exited.
hold_until_killed LIVE1; BG="$BG $LIVE1"
hold_until_killed LIVE2; BG="$BG $LIVE2"
bash -c 'exit 0' & DEAD=$!; wait "$DEAD" 2>/dev/null
PLANT_STARTED="2026-01-02T03:04:05Z"

# The status each kind of full run has alone, with the queue off: what AC-1
# compares a queued run's status with. Measured, not assumed.
new_case; RQ_MODE=off
rq_run p "$A" solo-gates scripts/gates.sh;    wait_bounded "$p" 120; SOLO_GATES=$WRC
new_case; RQ_MODE=off
rq_run p "$B" solo-self scripts/selftest.sh;  wait_bounded "$p" 120; SOLO_SELF=$WRC

# ---------------------------------------------------------------------------
# pair_case <label> <holder script> <waiter script>   AC-1: A's full run holds
# the queue; B's full run is started; B must not start its work while A holds,
# and must run once A ends.
pair_case() {
  local lbl="$1" hs="$2" ws="$3" hp wp arc brc bto solo
  case "$ws" in gates.sh) solo="$SOLO_GATES" ;; *) solo="$SOLO_SELF" ;; esac
  new_case
  hold_run hp "$A" "$lbl-A" "scripts/$hs"
  assert_eq "$lbl: precondition: A's full $hs is in progress, held on its release file" yes "$HOLDING"
  cp "$QL" "$W/$lbl-A.rec" 2>/dev/null || : > "$W/$lbl-A.rec"
  rq_run wp "$B" "$lbl-B" "scripts/$ws"
  wait_until 60 started_or_queued "$B" "$W/$lbl-B.err"
  sleep 3.5   # at least two poll intervals after it queued, and AC-3's three seconds held
  assert_eq "$lbl: B's full $ws has not started its work while A holds the queue, over two poll intervals after it queued" \
    absent "$(present "$B/m/k/started")"
  assert_eq "$lbl: precondition: A is still running at that moment" alive "$(is_alive "$hp")"
  touch "$A/m/k/release"
  wait_bounded "$hp" 60; arc=$WRC
  wait_bounded "$wp" 60; brc=$WRC; bto=$WTO
  assert_eq "$lbl: A finishes with its own status" 0 "$arc"
  assert_eq "$lbl: once A ends, B gets through by itself, within the bound" no "$bto"
  assert_eq "$lbl: B's work runs to its end" present "$(present "$B/m/k/finished")"
  assert_eq "$lbl: B exits with the status the same run has alone, queue off ($solo)" "$solo" "$brc"
  assert_eq "$lbl: B's work records, as it starts, that A's had finished" "A" "$(readf "$B/m/k/done-before")"
  assert_eq "$lbl: B's work saw no other run in progress as it started" "" "$(readf "$B/m/k/overlap-start")"
  assert_eq "$lbl: A's work saw no other run in progress as it ended" "" "$(readf "$A/m/k/overlap-end")"
  assert_eq "$lbl: the queue directory holds nothing once both have ended" "" "$(qsnap)"
  PAIR_HP="$hp"
}

describe "AC-1  a full run in another tree waits for the full run that holds the queue, then runs"

pair_case ac1-gg gates.sh gates.sh;    GG_HP="$PAIR_HP"
pair_case ac1-gs gates.sh selftest.sh; GS_HP="$PAIR_HP"
pair_case ac1-sg selftest.sh gates.sh; SG_HP="$PAIR_HP"

# ---------------------------------------------------------------------------
describe "AC-3  the queued run says it is queued, behind what, and that it is waiting; on stderr"

E="$W/ac1-gg-B.err"
H_STARTED="$(rec_field "$W/ac1-gg-A.rec" started)"
assert_eq "AC-3: queued line 1 names the waiting run, exactly once" 1 "$(count_line "$(q1 scripts/gates.sh)" "$E")"
assert_eq "AC-3: queued line 2 names A's pid, start, tree root and command from A's record, exactly once" 1 \
  "$(count_line "$(q2 "$GG_HP" "$H_STARTED" "$A" scripts/gates.sh)" "$E")"
assert_eq "AC-3: queued line 3 says it is waiting and names the lock to delete, exactly once" 1 \
  "$(count_line "$(q3 "$GG_HP" "$QL")" "$E")"
assert_eq "AC-3: the first run-queue: line is the queued line, printed before it waits" \
  "$(q1 scripts/gates.sh)" "$(first_rq "$E")"
assert_eq "AC-3: with a heartbeat of 1 s and A held over 3 s, at least one still-queued line naming A" yes \
  "$(at_least 1 "$(count_span "$(hb_prefix "$GG_HP" "$A" scripts/gates.sh)" "$HB_RE" "$E")")"
assert_eq "AC-3: one starting line with the total wait" 1 \
  "$(count_span "$(start_prefix scripts/gates.sh)" "$START_RE" "$E")"
last_rq "$E" > "$W/ac3-last"
assert_eq "AC-3: and the starting line is the last run-queue: line" 1 \
  "$(count_span "$(start_prefix scripts/gates.sh)" "$START_RE" "$W/ac3-last")"
assert_eq "AC-3: no run-queue: line goes to stdout" 0 "$(count_re '^run-queue:' "$W/ac1-gg-B.out")"
assert_eq "AC-3: a queued selftest.sh names itself in its queued line" 1 \
  "$(count_line "$(q1 scripts/selftest.sh)" "$W/ac1-gs-B.err")"
assert_eq "AC-3: and a gates.sh queued behind a selftest.sh names A's command as scripts/selftest.sh" 1 \
  "$(count_line "$(q2 "$SG_HP" "$(rec_field "$W/ac1-sg-A.rec" started)" "$A" scripts/selftest.sh)" "$W/ac1-sg-B.err")"

# ---------------------------------------------------------------------------
describe "AC-2  two runs queued behind a holder both finish, and no two of the three ever run together"

new_case
hold_run hp "$A" ac2-A scripts/gates.sh
assert_eq "AC-2: precondition: A's full gates.sh holds, its work in progress" yes "$HOLDING"
rq_run bp "$B" ac2-B scripts/gates.sh
rq_run cp_ "$C" ac2-C scripts/gates.sh
wait_until 60 started_or_queued "$B" "$W/ac2-B.err"
wait_until 60 started_or_queued "$C" "$W/ac2-C.err"
sleep 2   # two poll intervals: both have attempted the queue at least twice
touch "$A/m/k/release"
wait_bounded "$hp" 60;  arc=$WRC
wait_bounded "$bp" 90;  brc=$WRC
wait_bounded "$cp_" 90; crc=$WRC
assert_eq "AC-2: A exits 0" 0 "$arc"
assert_eq "AC-2: B runs to completion and exits 0" 0 "$brc"
assert_eq "AC-2: C runs to completion and exits 0" 0 "$crc"
assert_eq "AC-2: B's work finished" present "$(present "$B/m/k/finished")"
assert_eq "AC-2: C's work finished" present "$(present "$C/m/k/finished")"
for t in A B C; do
  eval "tp=\$$t"
  assert_eq "AC-2: $t's work saw no other run in progress as it started" "" "$(readf "$tp/m/k/overlap-start")"
  assert_eq "AC-2: $t's work saw no other run in progress as it ended" "" "$(readf "$tp/m/k/overlap-end")"
done
assert_eq "AC-2: the queue directory holds nothing afterwards" "" "$(qsnap)"

# ---------------------------------------------------------------------------
describe "AC-4  an uncontended full run takes the queue silently, records itself, and leaves nothing"

# ac4_case <script> <command string>
ac4_case() {
  local s="$1" cmd="$2" p offrc onrc
  new_case; RQ_MODE=off
  rq_run p "$A" "ac4-$s-off" "scripts/$s"; wait_bounded "$p" 120; offrc=$WRC
  new_case
  rq_run p "$A" "ac4-$s-on" "scripts/$s"; wait_bounded "$p" 120; onrc=$WRC
  local R="$A/m/k/qlock"
  assert_eq "AC-4 $s: while its work ran, the queue lock existed" present "$(present "$R")"
  assert_eq "AC-4 $s: the lock records the run's pid" "$p" "$(rec_field "$R" pid)"
  assert_eq "AC-4 $s: the lock records when it started, UTC to the second" 1 \
    "$(rec_field "$R" started | awk -v re="$UTC_RE" '$0 ~ re { n++ } END { print n + 0 }')"
  assert_eq "AC-4 $s: the lock records the run's command" "$cmd" "$(rec_field "$R" command)"
  assert_eq "AC-4 $s: the lock records the run's tree root, absolute" "$A" "$(rec_field "$R" root)"
  assert_eq "AC-4 $s: the lock is four TAB-separated lines: pid, started, command, root" \
    "pid started command root" "$(rec_keys "$R")"
  assert_eq "AC-4 $s: it prints no run-queue: line on stdout or stderr" 0 \
    "$(cat "$W/ac4-$s-on.out" "$W/ac4-$s-on.err" | awk 'index($0, "run-queue:") == 1 { n++ } END { print n + 0 }')"
  if cmp -s "$W/ac4-$s-off.err" "$W/ac4-$s-on.err"; then
    _ok "AC-4 $s: its stderr is byte-for-byte the same run's with HARNESS_RUN_QUEUE=off"
  else
    _bad "AC-4 $s: its stderr is byte-for-byte the same run's with HARNESS_RUN_QUEUE=off" \
      "$(diff "$W/ac4-$s-off.err" "$W/ac4-$s-on.err" 2>&1 | awk 'NR <= 10')"
  fi
  assert_eq "AC-4 $s: it exits as the same run does with the queue off ($offrc)" "$offrc" "$onrc"
  assert_eq "AC-4 $s: afterwards the queue directory holds neither the lock nor a temporary record" "" "$(qsnap)"
}
ac4_case gates.sh scripts/gates.sh
ac4_case selftest.sh scripts/selftest.sh

# ---------------------------------------------------------------------------
describe "AC-5  a stale or unreadable queue lock is reclaimed; a live pid never is"

assert_eq "AC-5: precondition: the dead pid is not running" gone "$(is_alive "$DEAD")"

# reclaim_case <label> <pid-or-empty> <expected line>
reclaim_case() {
  local lbl="$1" p
  new_case
  qplant "$2" "$PLANT_STARTED" "scripts/selftest.sh ghost" "/ghost/tree"
  rq_run p "$B" "$lbl" scripts/gates.sh; wait_bounded "$p" 60
  assert_eq "$lbl: prints the reclaim line, exactly once" 1 "$(count_line "$3" "$W/$lbl.err")"
  assert_eq "$lbl: does not wait: no queued line" 0 "$(count_re '^run-queue: queued: ' "$W/$lbl.err")"
  assert_eq "$lbl: runs its work and exits 0" "0 present" "$WRC $(present "$B/m/k/finished")"
  assert_eq "$lbl: having taken the queue: its work saw a lock recording its own pid" "$p" "$(rec_field "$B/m/k/qlock" pid)"
  assert_eq "$lbl: and leaves the queue directory empty" "" "$(qsnap)"
}
reclaim_case ac5-stale "$DEAD" "$(stale_line "$DEAD" "scripts/selftest.sh ghost" /ghost/tree)"
reclaim_case ac5-nopid "" "$(unread_line "$QL")"
reclaim_case ac5-nonnumeric "not-a-pid" "$(unread_line "$QL")"

describe "AC-5  a lock whose pid is a live process that is not a harness run: wait, never reclaim"

new_case
sleep 600 & SP=$!; BG="$BG $SP"
assert_eq "AC-5 live: precondition: the plain sleep holding the pid is running" alive "$(is_alive "$SP")"
qplant "$SP" "$PLANT_STARTED" "scripts/selftest.sh ghost" "/ghost/tree"
before="$(qlock)"
rq_run p "$B" ac5-live scripts/gates.sh
wait_until 60 started_or_queued "$B" "$W/ac5-live.err"
sleep 2.5
assert_eq "AC-5 live: the run has not started its work, over two poll intervals after it queued" absent "$(present "$B/m/k/started")"
assert_eq "AC-5 live: it names the live pid as what it waits behind" 1 \
  "$(count_line "$(q2 "$SP" "$PLANT_STARTED" /ghost/tree "scripts/selftest.sh ghost")" "$W/ac5-live.err")"
assert_eq "AC-5 live: it prints no reclaim line while the pid lives" 0 "$(count_re '^run-queue: reclaimed' "$W/ac5-live.err")"
assert_eq "AC-5 live: and the lock is byte-identical: a live pid is never reclaimed" "$before" "$(qlock)"
kill "$SP" 2>/dev/null; wait "$SP" 2>/dev/null
wait_bounded "$p" 60
assert_eq "AC-5 live: once the pid has gone, the run reclaims, runs and exits 0" "0 present" "$WRC $(present "$B/m/k/finished")"
assert_eq "AC-5 live: with the stale line naming that pid, exactly once" 1 \
  "$(count_line "$(stale_line "$SP" "scripts/selftest.sh ghost" /ghost/tree)" "$W/ac5-live.err")"
assert_eq "AC-5 live: and one starting line, since it had printed the queued lines" 1 \
  "$(count_span "$(start_prefix scripts/gates.sh)" "$START_RE" "$W/ac5-live.err")"
assert_eq "AC-5 live: the queue directory is empty afterwards" "" "$(qsnap)"

# ---------------------------------------------------------------------------
describe "AC-6  full runs nested under the holder, in its own tree and another, pass through"

new_case
write_conf "$A" <<'EOF'
gate     | unit | required | . | bash m/nest.sh
evidence | unit | Tests +[1-9][0-9]* passed
gate     | lint | required | . | bash m/lint.sh
evidence | lint | Tests +[1-9][0-9]* passed
EOF
rq_run op "$A" ac6-outer scripts/gates.sh; wait_bounded "$op" 120
orc=$WRC; oto=$WTO
for f in "$A"/m/k/n*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
conf_work "$A"
assert_eq "AC-6: the whole arrangement completes within the bound: it does not wait on itself" no "$oto"
assert_eq "AC-6: the outer full gates.sh finishes with its own status" 0 "$orc"
assert_eq "AC-6: the inner full selftest.sh in A (the holder's tree) exits 0" 0 "$(readf "$A/m/k/n1.rc")"
assert_eq "AC-6: the inner full selftest.sh in B (another tree) exits 0, its suite run" "0 present" \
  "$(readf "$A/m/k/n2.rc") $(present "$B/m/k/finished")"
assert_eq "AC-6: neither inner run prints a run-queue: line" 0 \
  "$(cat "$A/m/k/n1.out" "$A/m/k/n1.err" "$A/m/k/n2.out" "$A/m/k/n2.err" 2>/dev/null | awk 'index($0, "run-queue:") == 1 { n++ } END { print n + 0 }')"
assert_eq "AC-6: after the inner run in A has ended, the queue lock still records the outer run's pid" "$op" \
  "$(rec_field "$A/m/k/n1.qlock" pid)"
assert_eq "AC-6: after the inner run in B has ended, the queue lock still records the outer run's pid" "$op" \
  "$(rec_field "$A/m/k/n2.qlock" pid)"
assert_eq "AC-6: and once the outer run has ended the queue directory is empty" "" "$(qsnap)"

describe "AC-6  the inherited variables are not a bypass"

assert_eq "AC-6: precondition: both live holders are alive" "alive alive" "$(is_alive "$LIVE1") $(is_alive "$LIVE2")"
# bypass_case <label> <lock var> <pid var>
bypass_case() {
  local lbl="$1" p before
  new_case
  qplant "$LIVE1" "$PLANT_STARTED" "scripts/gates.sh" "$A"
  before="$(qlock)"
  RQ_XLOCK="$2"; RQ_XPID="$3"
  rq_run p "$B" "$lbl" scripts/gates.sh
  wait_until 60 started_or_queued "$B" "$W/$lbl.err"
  sleep 2.5
  assert_eq "$lbl: B queues behind the live holder" 1 "$(count_line "$(q1 scripts/gates.sh)" "$W/$lbl.err")"
  assert_eq "$lbl: B has not started its work, over two poll intervals after it queued" absent "$(present "$B/m/k/started")"
  assert_eq "$lbl: the holder's lock is byte-identical" "$before" "$(qlock)"
  kill -TERM "$p" 2>/dev/null; wait_bounded "$p" 15
}
mkdir -p "$W/q-other"
qplant "$LIVE1" "$PLANT_STARTED" "scripts/gates.sh" "$A" "$W/q-other"
bypass_case ac6-wrong-pid "$QL" "$LIVE2"
bypass_case ac6-wrong-path "$W/q-other/run-queue.lock" "$LIVE1"

# ---------------------------------------------------------------------------
describe "AC-7 / AC-10  beside a held queue: HARNESS_RUN_QUEUE=off and every run that does not queue starts at once"

new_case
hold_run hp "$A" ac10-A scripts/gates.sh
assert_eq "precondition: A's full gates.sh holds the queue, its work in progress" yes "$HOLDING"

# beside_case <label> <script> [args...]   B started while A holds; it must
# start its work at once, say nothing and leave the queue directory alone.
beside_case() {
  local lbl="$1" p before; shift
  rm -rf "$B/m/k"; mkdir -p "$B/m/k"; rm -f "$B"/.claude/state/run.lock*
  before="$(qsnap)"
  rq_run p "$B" "$lbl" "$@"
  wait_until 60 started_or_queued "$B" "$W/$lbl.err"
  assert_eq "$lbl: starts its work at once, while A holds" present "$(present "$B/m/k/started")"
  assert_eq "$lbl: precondition: A is still running then" alive "$(is_alive "$hp")"
  if is_started "$B"; then wait_bounded "$p" 60; else kill -TERM "$p" 2>/dev/null; wait_bounded "$p" 15; fi
  assert_eq "$lbl: exits 0" 0 "$WRC"
  assert_eq "$lbl: prints no run-queue: line" 0 \
    "$(cat "$W/$lbl.out" "$W/$lbl.err" | awk 'index($0, "run-queue:") == 1 { n++ } END { print n + 0 }')"
  assert_eq "$lbl: creates, changes and removes nothing in the queue directory" "$before" "$(qsnap)"
}

RQ_MODE=off
beside_case "AC-7 full gates.sh, HARNESS_RUN_QUEUE=off" scripts/gates.sh
assert_eq "AC-7 control: B's work ran beside A's - the arrangement can see two runs at once" "A" \
  "$(readf "$B/m/k/overlap-start")"
RQ_MODE=""
beside_case "AC-10 gates.sh --fast"      scripts/gates.sh --fast
beside_case "AC-10 gates.sh --gate unit" scripts/gates.sh --gate unit
beside_case "AC-10 gates.sh --skip lint" scripts/gates.sh --skip lint
beside_case "AC-10 gates.sh --required"  scripts/gates.sh --required
beside_case "AC-10 selftest.sh work"     scripts/selftest.sh work

# The run lock is unchanged: a non-full run in the tree A holds is refused.
rq_run p "$A" ac10-same scripts/gates.sh --fast; wait_bounded "$p" 60
assert_eq "AC-10: a non-full run in the tree A's full run holds is refused with exit 2" 2 "$WRC"
assert_eq "AC-10: by the run lock, as today" 1 \
  "$(count_line "run-lock: refusing to start scripts/gates.sh --fast: another harness run holds this worktree's lock." "$W/ac10-same.err")"

touch "$A/m/k/release"; wait_bounded "$hp" 60
assert_eq "AC-10: A then finishes, exit 0" 0 "$WRC"

describe "AC-10  a run in progress that does not queue is not waited for: a full run takes the queue at once"

new_case
hold_run bp "$B" ac10-B scripts/gates.sh --gate unit
assert_eq "precondition: B's gates.sh --gate unit is in progress" yes "$HOLDING"
assert_eq "AC-10: B's non-full run has written nothing in the queue directory" "" "$(qsnap)"
rq_run ap "$A" ac10-full scripts/gates.sh
wait_until 60 started_or_queued "$A" "$W/ac10-full.err"
assert_eq "AC-10: A's full run starts its work at once, beside B's" "present B" \
  "$(present "$A/m/k/started") $(readf "$A/m/k/overlap-start")"
assert_eq "AC-10: and has taken the queue: its work saw a lock recording its pid" "$ap" "$(rec_field "$A/m/k/qlock" pid)"
touch "$B/m/k/release"
wait_bounded "$bp" 60; brc=$WRC
wait_bounded "$ap" 60; arc=$WRC
assert_eq "AC-10: both exit 0" "0 0" "$brc $arc"
assert_eq "AC-10: the queue directory is empty afterwards" "" "$(qsnap)"

describe "AC-10  run_lock_full answers as C-5's table says"

# rows: <0 full | 1 not full>|<command string>
FULL_ROWS='0|scripts/gates.sh
0|scripts/gates.sh --story T-1
0|scripts/selftest.sh
1|scripts/gates.sh --fast
1|scripts/gates.sh --gate unit
1|scripts/gates.sh --skip unit
1|scripts/gates.sh --required
1|scripts/gates.sh --story T-1 --fast
1|scripts/gates.sh --list
1|scripts/gates.sh --audit
1|scripts/selftest.sh run-queue
1|scripts/selftest.sh run-queue run-lock
1|scripts/selftest.sh --changed
1|scripts/selftest.sh --changed origin/main
1|scripts/selftest-needed.sh --suites
1|scripts/check-boundaries.sh
1|scripts/ci-local.sh
1|scripts/attest.sh -- bash scripts/gates.sh
1|'
HAVE_FULL="$( ( . "$REPO_ROOT/scripts/run-lock.sh" && type run_lock_full >/dev/null 2>&1 ) && printf yes || printf no)"
while IFS='|' read -r want cmd; do
  [ -n "$want" ] || continue
  if [ "$want" = 0 ]; then word=full; else word="not full"; fi
  if [ "$HAVE_FULL" = yes ]; then
    got="$( . "$REPO_ROOT/scripts/run-lock.sh"; set -f; run_lock_full "$cmd"; printf '%s' "$?")"
    assert_eq "run_lock_full '$cmd' is $word" "$want" "$got"
  else
    _bad "run_lock_full '$cmd' is $word" "scripts/run-lock.sh defines no run_lock_full"
  fi
done <<EOF
$FULL_ROWS
EOF

# ---------------------------------------------------------------------------
describe "AC-7  any value but off, and CI=true on its own, leave the queue on"

# value_case <label> <RQ_MODE> <RQ_CI>
value_case() {
  local lbl="$1" p
  new_case
  qplant "$LIVE1" "$PLANT_STARTED" "scripts/gates.sh" "$A"
  RQ_MODE="$2"; RQ_CI="$3"
  rq_run p "$B" "$lbl" scripts/gates.sh
  wait_until 60 started_or_queued "$B" "$W/$lbl.err"
  assert_eq "$lbl: the run queues behind the live holder" 1 "$(count_line "$(q1 scripts/gates.sh)" "$W/$lbl.err")"
  assert_eq "$lbl: and has not started its work" absent "$(present "$B/m/k/started")"
  kill -TERM "$p" 2>/dev/null; wait_bounded "$p" 15
}
value_case "AC-7 HARNESS_RUN_QUEUE unset"           "<unset>" ""
value_case "AC-7 HARNESS_RUN_QUEUE=OFF"             "OFF"     ""
value_case "AC-7 HARNESS_RUN_QUEUE=no"              "no"      ""
value_case "AC-7 CI=true, HARNESS_RUN_QUEUE unset"  "<unset>" "true"

describe "AC-7  _lib.sh exports HARNESS_RUN_QUEUE=off to every suite"

assert_eq "AC-7: sourcing _lib.sh with HARNESS_RUN_QUEUE unset leaves it off" off \
  "$(env -u HARNESS_RUN_QUEUE bash -c '. "$1" >/dev/null 2>&1; printf "%s" "${HARNESS_RUN_QUEUE-<unset>}"' _ "$TESTS_DIR/_lib.sh")"
assert_eq "AC-7: unconditionally: with HARNESS_RUN_QUEUE=on in the environment it is still off" off \
  "$(HARNESS_RUN_QUEUE=on bash -c '. "$1" >/dev/null 2>&1; printf "%s" "${HARNESS_RUN_QUEUE-<unset>}"' _ "$TESTS_DIR/_lib.sh")"
assert_eq "AC-7: and exported: a process the suite starts sees off" off \
  "$(env -u HARNESS_RUN_QUEUE bash -c '. "$1" >/dev/null 2>&1; bash -c "printf %s \"\${HARNESS_RUN_QUEUE-<unset>}\""' _ "$TESTS_DIR/_lib.sh")"

# ---------------------------------------------------------------------------
describe "AC-8  TERM: a waiter exits 143 having run nothing; a holder's exit lets the next run in"

# term_waiter <label> <script>
term_waiter() {
  local lbl="$1" s="$2" p before
  new_case
  qplant "$LIVE1" "$PLANT_STARTED" "scripts/gates.sh" "$A"
  before="$(qsnap)"
  rq_run p "$B" "$lbl" "scripts/$s"
  wait_until 60 started_or_queued "$B" "$W/$lbl.err"
  assert_eq "$lbl: precondition: the run is queued" 1 "$(count_line "$(q1 "scripts/$s")" "$W/$lbl.err")"
  kill -TERM "$p" 2>/dev/null
  wait_bounded "$p" 10
  assert_eq "$lbl: sent TERM while queued, it exits within a few poll intervals" no "$WTO"
  assert_eq "$lbl: with status 143" 143 "$WRC"
  assert_eq "$lbl: having run nothing" absent "$(present "$B/m/k/started")"
  assert_eq "$lbl: the queue directory holds only the holder's lock, unchanged" "$before" "$(qsnap)"
  assert_eq "$lbl: and the waiter's tree holds no run.lock" 0 "$(leftovers "$B")"
}
term_waiter "AC-8 gates.sh waiter" gates.sh
term_waiter "AC-8 selftest.sh waiter" selftest.sh

new_case
hold_run hp "$A" ac8-A scripts/gates.sh
assert_eq "AC-8 holder: precondition: A's full gates.sh holds" yes "$HOLDING"
rq_run bp "$B" ac8-B scripts/gates.sh
wait_until 60 started_or_queued "$B" "$W/ac8-B.err"
kill -TERM "$hp" 2>/dev/null
touch "$A/m/k/release"   # gates.sh waits for its running gate command before acting on TERM
wait_bounded "$hp" 30
assert_eq "AC-8 holder: A, sent TERM, exits 143" 143 "$WRC"
assert_eq "AC-8 holder: once A has exited, the queue lock no longer records A" yes \
  "$(if [ "$(rec_field "$QL" pid)" != "$hp" ]; then printf yes; else printf 'no: it still records %s' "$hp"; fi)"
wait_bounded "$bp" 60
assert_eq "AC-8 holder: the run waiting behind A starts, runs and exits 0" "0 present" "$WRC $(present "$B/m/k/finished")"
assert_eq "AC-8 holder: and its work began only after A's had ended" "" "$(readf "$B/m/k/overlap-start")"
assert_eq "AC-8 holder: the queue directory is empty afterwards" "" "$(qsnap)"
# INT is not tested: a background job of a non-interactive shell starts with
# INT ignored, and an ignored signal cannot be trapped (C-4, Signals).

# ---------------------------------------------------------------------------
describe "AC-9  a queue it cannot use: one line, and the run runs as it would have"

touch "$W/afile"
# noq_case <label> <tree> <script> <expected line> <expected status>
noq_case() {
  local lbl="$1" t="$2" p
  rm -rf "$t/m/k"; mkdir -p "$t/m/k"; rm -f "$t"/.claude/state/run.lock*
  rq_run p "$t" "$lbl" "scripts/$3"; wait_bounded "$p" 60
  assert_eq "$lbl: prints the one line for its case" 1 "$(count_line "$4" "$W/$lbl.err")"
  assert_eq "$lbl: and no other run-queue: line" 1 "$(count_re '^run-queue:' "$W/$lbl.err")"
  assert_eq "$lbl: runs its work, with its own exit status ($5)" "$5 present" "$WRC $(present "$t/m/k/finished")"
}
new_case; RQ_DIR="$W/afile/q"
noq_case "AC-9 gates.sh, queue dir under a regular file" "$B" gates.sh \
  "$(cannot_line "$W/afile/q" scripts/gates.sh)" "$SOLO_GATES"
noq_case "AC-9 selftest.sh, queue dir under a regular file" "$B" selftest.sh \
  "$(cannot_line "$W/afile/q" scripts/selftest.sh)" "$SOLO_SELF"

new_case; RQ_DIR="<unset>"; RQ_NOHOME=1; RQ_MODE=off
rq_run p "$B" ac9-nohome-off scripts/gates.sh; wait_bounded "$p" 60; NOHOME_RC=$WRC
RQ_MODE=""
noq_case "AC-9 gates.sh, neither HARNESS_RUN_QUEUE_DIR nor HOME" "$B" gates.sh \
  "$(nohome_line scripts/gates.sh)" "$NOHOME_RC"

new_case
mv "$C/scripts/run-queue.sh" "$W/run-queue.sh.kept" 2>/dev/null
noq_case "AC-9 gates.sh, a tree without run-queue.sh" "$C" gates.sh \
  "$(missing_line scripts/gates.sh)" "$SOLO_GATES"
assert_eq "AC-9: a tree with no scripts/run-queue.sh writes nothing in the queue directory" "" "$(qsnap)"
mv "$W/run-queue.sh.kept" "$C/scripts/run-queue.sh" 2>/dev/null

# A directory at the lock path (R-2). GNU ln links a file INTO an existing
# directory, so without a type check the run would "take" the queue
# silently, leave its record inside the directory, and no full run on the
# machine would ever queue again. It is a queue it cannot use: C-3's line.
new_case
mkdir "$QL"
noq_case "AC-9 gates.sh, the queue lock path is a directory" "$B" gates.sh \
  "$(cannot_line "$Q" scripts/gates.sh)" "$SOLO_GATES"
assert_eq "AC-9 gates.sh, the queue lock path is a directory: nothing is left inside that directory" "" \
  "$(ls -A "$QL" 2>/dev/null)"
rm -rf "$QL"

# ===========================================================================
# HARNESS-111  a --changed run queues: every one that reaches the run lock
# (Contract C-1..C-5). Trees X (every suite), Y (a proper subset) and Z (no
# suite) are described where they are built. The holder, where there is one,
# is a full gates.sh in A, except in AC-2's reverse pair, where it is X's
# --changed run. Every case asserts its header line before the queue.
# ===========================================================================

# The status each --changed run has alone, with the queue off: what a queued
# or nested one is compared with. Measured, not assumed. solo-cx's stderr is
# also AC-2's byte-for-byte reference.
new_case; RQ_MODE=off
rq_run p "$X" solo-cx scripts/selftest.sh --changed; wait_bounded "$p" 120; SOLO_CX=$WRC
new_case; RQ_MODE=off
rq_run p "$Y" solo-cy scripts/selftest.sh --changed; wait_bounded "$p" 120; SOLO_CY=$WRC

# ---------------------------------------------------------------------------
describe "HARNESS-111 AC-1  a --changed run in another tree waits for the full run that holds the queue, then runs"

# changed_pair <label> <tree> <name> <header> <solo status> <other blocks>
# A's full gates.sh holds; <tree>'s --changed run is started; it must not
# start a suite while A holds, must say so naming A, and must run its own
# selection once A ends. <other blocks> is how many `=== other ===` blocks its
# stdout carries: 1 for every suite, 0 for the subset, which selects work only.
changed_pair() {
  local lbl="$1" t="$2" n="$3" hdr="$4" solo="$5" nother="$6" hp wp arc brc bto
  new_case
  hold_run hp "$A" "$lbl-A" scripts/gates.sh
  assert_eq "$lbl: precondition: A's full gates.sh is in progress, held on its release file" yes "$HOLDING"
  cp "$QL" "$W/$lbl-A.rec" 2>/dev/null || : > "$W/$lbl-A.rec"
  rq_run wp "$t" "$lbl-B" scripts/selftest.sh --changed
  wait_until 60 started_or_queued "$t" "$W/$lbl-B.err"
  sleep 3.5   # at least two poll intervals after it queued
  assert_eq "$lbl: precondition: $n's stdout carries the --changed header line for its selection" 1 \
    "$(count_line "$hdr" "$W/$lbl-B.out")"
  assert_eq "$lbl: $n's --changed run has not started its work while A holds the queue, over two poll intervals after it queued" \
    absent "$(present "$t/m/k/started")"
  assert_eq "$lbl: nor printed a suite block: no === <suite> === line yet" 0 "$(count_re '^=== ' "$W/$lbl-B.out")"
  assert_eq "$lbl: precondition: A is still running at that moment" alive "$(is_alive "$hp")"
  assert_eq "$lbl: queued line 1 names the waiting run as $CHG, exactly once, on stderr" 1 \
    "$(count_line "$(q1 "$CHG")" "$W/$lbl-B.err")"
  assert_eq "$lbl: queued line 2 names A's pid, start, tree root and command from A's record, exactly once" 1 \
    "$(count_line "$(q2 "$hp" "$(rec_field "$W/$lbl-A.rec" started)" "$A" scripts/gates.sh)" "$W/$lbl-B.err")"
  assert_eq "$lbl: queued line 3 says it is waiting and names the lock to delete, exactly once" 1 \
    "$(count_line "$(q3 "$hp" "$QL")" "$W/$lbl-B.err")"
  touch "$A/m/k/release"
  wait_bounded "$hp" 60; arc=$WRC
  wait_bounded "$wp" 90; brc=$WRC; bto=$WTO
  assert_eq "$lbl: A finishes with its own status" 0 "$arc"
  assert_eq "$lbl: once A ends, $n's run gets through by itself, within the bound" no "$bto"
  assert_eq "$lbl: $n's work runs to its end" present "$(present "$t/m/k/finished")"
  assert_eq "$lbl: $n's run exits with the status the same run has alone, queue off ($solo)" "$solo" "$brc"
  assert_eq "$lbl: $n's work records, as it starts, that A's had finished" "A" "$(readf "$t/m/k/done-before")"
  assert_eq "$lbl: $n's work saw no other run in progress as it started" "" "$(readf "$t/m/k/overlap-start")"
  assert_eq "$lbl: A's work saw no other run in progress as it ended" "" "$(readf "$A/m/k/overlap-end")"
  assert_eq "$lbl: one starting line naming $CHG, with the total wait" 1 \
    "$(count_span "$(start_prefix "$CHG")" "$START_RE" "$W/$lbl-B.err")"
  assert_eq "$lbl: it runs the suite its selection holds: one === work === block" 1 \
    "$(count_line '=== work ===' "$W/$lbl-B.out")"
  assert_eq "$lbl: and $nother === other === block(s), as its selection says" "$nother" \
    "$(count_line '=== other ===' "$W/$lbl-B.out")"
  assert_eq "$lbl: the queue directory holds nothing once both have ended" "" "$(qsnap)"
}
changed_pair "AC-1 every suite" "$X" X "$HDR_X" "$SOLO_CX" 1
changed_pair "AC-1 subset"      "$Y" Y "$HDR_Y" "$SOLO_CY" 0

# ---------------------------------------------------------------------------
describe "HARNESS-111 AC-2  an uncontended --changed run takes the queue silently, records itself, and leaves nothing"

new_case
rq_run p "$X" ac2c-on scripts/selftest.sh --changed; wait_bounded "$p" 120; onrc=$WRC
R="$X/m/k/qlock"
assert_eq "AC-2 --changed: precondition: its stdout carries the every-suite header line" 1 \
  "$(count_line "$HDR_X" "$W/ac2c-on.out")"
assert_eq "AC-2 --changed: while its suite ran, the queue lock existed" present "$(present "$R")"
assert_eq "AC-2 --changed: the lock records the run's pid" "$p" "$(rec_field "$R" pid)"
assert_eq "AC-2 --changed: the lock records the run's command, $CHG" "$CHG" "$(rec_field "$R" command)"
assert_eq "AC-2 --changed: the lock records the run's tree root, absolute" "$X" "$(rec_field "$R" root)"
assert_eq "AC-2 --changed: it prints no run-queue: line on stdout or stderr" 0 \
  "$(cat "$W/ac2c-on.out" "$W/ac2c-on.err" | awk 'index($0, "run-queue:") == 1 { n++ } END { print n + 0 }')"
if cmp -s "$W/solo-cx.err" "$W/ac2c-on.err"; then
  _ok "AC-2 --changed: its stderr is byte-for-byte the same run's with HARNESS_RUN_QUEUE=off"
else
  _bad "AC-2 --changed: its stderr is byte-for-byte the same run's with HARNESS_RUN_QUEUE=off" \
    "$(diff "$W/solo-cx.err" "$W/ac2c-on.err" 2>&1 | awk 'NR <= 10')"
fi
assert_eq "AC-2 --changed: it exits as the same run does with the queue off ($SOLO_CX)" "$SOLO_CX" "$onrc"
assert_eq "AC-2 --changed: afterwards the queue directory holds neither the lock nor a temporary record" "" "$(qsnap)"

describe "HARNESS-111 AC-2  a --changed run that holds the queue is waited for: a full gates.sh queues behind it"

new_case
hold_run hp "$X" ac2r-X scripts/selftest.sh --changed
assert_eq "AC-2 reverse: precondition: X's --changed run is in progress, held on its release file" yes "$HOLDING"
assert_eq "AC-2 reverse: precondition: X's stdout carries the every-suite header line" 1 \
  "$(count_line "$HDR_X" "$W/ac2r-X.out")"
cp "$QL" "$W/ac2r-X.rec" 2>/dev/null || : > "$W/ac2r-X.rec"
rq_run ap "$A" ac2r-A scripts/gates.sh
wait_until 60 started_or_queued "$A" "$W/ac2r-A.err"
sleep 3.5   # at least two poll intervals after it queued
assert_eq "AC-2 reverse: A's full gates.sh has not started its gate command while X's --changed run holds, over two poll intervals after it queued" \
  absent "$(present "$A/m/k/started")"
assert_eq "AC-2 reverse: precondition: X's run is still running at that moment" alive "$(is_alive "$hp")"
assert_eq "AC-2 reverse: A's queued line 1 names A's own command, exactly once" 1 \
  "$(count_line "$(q1 scripts/gates.sh)" "$W/ac2r-A.err")"
assert_eq "AC-2 reverse: A's queued line 2 names X's pid, start, tree root and $CHG, exactly once" 1 \
  "$(count_line "$(q2 "$hp" "$(rec_field "$W/ac2r-X.rec" started)" "$X" "$CHG")" "$W/ac2r-A.err")"
touch "$X/m/k/release"
wait_bounded "$hp" 60; xrc=$WRC
wait_bounded "$ap" 90; arc=$WRC; ato=$WTO
assert_eq "AC-2 reverse: X's --changed run finishes with its own status ($SOLO_CX)" "$SOLO_CX" "$xrc"
assert_eq "AC-2 reverse: once X ends, A gets through by itself, within the bound" no "$ato"
assert_eq "AC-2 reverse: A's work runs to its end" present "$(present "$A/m/k/finished")"
assert_eq "AC-2 reverse: A exits with the status it has alone ($SOLO_GATES)" "$SOLO_GATES" "$arc"
assert_eq "AC-2 reverse: A's work records, as it starts, that X's had finished" "X" "$(readf "$A/m/k/done-before")"
assert_eq "AC-2 reverse: A's work saw no other run in progress as it started" "" "$(readf "$A/m/k/overlap-start")"
assert_eq "AC-2 reverse: the queue directory holds nothing once both have ended" "" "$(qsnap)"

# ---------------------------------------------------------------------------
describe "HARNESS-111 AC-3  --changed runs nested under the holder, in its own tree and another, pass through"

new_case
touch "$X/m/k/nest"
rq_run op "$X" ac3c-outer scripts/gates.sh; wait_bounded "$op" 120
orc=$WRC; oto=$WTO
for f in "$X"/m/k/n*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
assert_eq "AC-3: precondition: the inner run in X (the holder's tree) carries the every-suite header line" 1 \
  "$(count_line "$HDR_X" "$X/m/k/n1.out")"
assert_eq "AC-3: precondition: the inner run in Y (another tree) carries the subset header line" 1 \
  "$(count_line "$HDR_Y" "$X/m/k/n2.out")"
assert_eq "AC-3: the whole arrangement completes within the bound: a nested --changed run does not wait on its ancestor" no "$oto"
assert_eq "AC-3: the outer full gates.sh finishes with its own status" 0 "$orc"
assert_eq "AC-3: the inner --changed run in X exits as it does alone ($SOLO_CX)" "$SOLO_CX" "$(readf "$X/m/k/n1.rc")"
assert_eq "AC-3: the inner --changed run in Y exits as it does alone ($SOLO_CY), its suite run" "$SOLO_CY present" \
  "$(readf "$X/m/k/n2.rc") $(present "$Y/m/k/finished")"
assert_eq "AC-3: neither inner run prints a run-queue: line" 0 \
  "$(cat "$X/m/k/n1.out" "$X/m/k/n1.err" "$X/m/k/n2.out" "$X/m/k/n2.err" 2>/dev/null | awk 'index($0, "run-queue:") == 1 { n++ } END { print n + 0 }')"
assert_eq "AC-3: after the inner run in X has ended, the queue lock still records the outer run's pid" "$op" \
  "$(rec_field "$X/m/k/n1.qlock" pid)"
assert_eq "AC-3: after the inner run in Y has ended, the queue lock still records the outer run's pid" "$op" \
  "$(rec_field "$X/m/k/n2.qlock" pid)"
assert_eq "AC-3: and once the outer run has ended the queue directory is empty" "" "$(qsnap)"

# ---------------------------------------------------------------------------
describe "HARNESS-111 AC-4, AC-1 control  beside a held queue: a --changed run that selects no suite, and one with the queue off"

new_case
hold_run hp "$A" ac4c-A scripts/gates.sh
assert_eq "AC-4: precondition: A's full gates.sh holds the queue, its work in progress" yes "$HOLDING"
before="$(qsnap)"
rq_run p "$Z" ac4c-Z scripts/selftest.sh --changed; wait_bounded "$p" 60
assert_eq "AC-4: Z's --changed run that selects no suite exits 1 at once, within the bound, while A holds" "no 1" "$WTO $WRC"
assert_eq "AC-4: its stdout is exactly the selected-no-suite line" "$HDR_Z" "$(tr -d '\r' < "$W/ac4c-Z.out")"
assert_eq "AC-4: it prints no run-queue: line on stdout or stderr" 0 \
  "$(cat "$W/ac4c-Z.out" "$W/ac4c-Z.err" | awk 'index($0, "run-queue:") == 1 { n++ } END { print n + 0 }')"
assert_eq "AC-4: it creates, changes and removes nothing in the queue directory" "$before" "$(qsnap)"
assert_eq "AC-4: and leaves no run.lock in Z" 0 "$(leftovers "$Z")"
assert_eq "AC-4: nothing ran: Z's work never started" absent "$(present "$Z/m/k/started")"
assert_eq "AC-4: precondition: A is still running then" alive "$(is_alive "$hp")"

RQ_MODE=off
rq_run p "$X" ac1c-off scripts/selftest.sh --changed
wait_until 60 started_or_queued "$X" "$W/ac1c-off.err"
assert_eq "AC-1 control: precondition: X's stdout carries the every-suite header line" 1 \
  "$(count_line "$HDR_X" "$W/ac1c-off.out")"
assert_eq "AC-1 control: with HARNESS_RUN_QUEUE=off, X's --changed run starts its work while A holds" present \
  "$(present "$X/m/k/started")"
assert_eq "AC-1 control: and its work saw A's in progress - the arrangement can see two runs at once" "A" \
  "$(readf "$X/m/k/overlap-start")"
assert_eq "AC-1 control: precondition: A is still running then" alive "$(is_alive "$hp")"
wait_bounded "$p" 60
assert_eq "AC-1 control: X's run exits as it does alone ($SOLO_CX)" "$SOLO_CX" "$WRC"
RQ_MODE=""
touch "$A/m/k/release"; wait_bounded "$hp" 60
assert_eq "AC-4: A then finishes, exit 0" 0 "$WRC"

# ---------------------------------------------------------------------------
describe "HARNESS-111 AC-5  run_lock_queues answers as C-2's table says"

# rows: <0 queues | 1 does not>|<command string>
QUEUE_ROWS='0|scripts/gates.sh
0|scripts/gates.sh --story T-1
0|scripts/selftest.sh
0|scripts/selftest.sh --changed
0|scripts/selftest.sh --changed origin/main
1|scripts/selftest.sh --changedx
1|scripts/selftest.sh run-queue --changed
1|scripts/selftest.sh run-queue
1|scripts/selftest.sh run-queue run-lock
1|scripts/gates.sh --fast
1|scripts/gates.sh --gate unit
1|scripts/gates.sh --skip unit
1|scripts/gates.sh --required
1|scripts/gates.sh --story T-1 --fast
1|scripts/gates.sh --list
1|scripts/gates.sh --audit
0|scripts/gates.sh --changed
1|scripts/selftest-needed.sh --suites
1|scripts/check-boundaries.sh
1|scripts/ci-local.sh
1|scripts/attest.sh -- bash scripts/selftest.sh --changed
1|'
HAVE_QUEUES="$( ( . "$REPO_ROOT/scripts/run-lock.sh" && type run_lock_queues >/dev/null 2>&1 ) && printf yes || printf no)"
while IFS='|' read -r want cmd; do
  [ -n "$want" ] || continue
  if [ "$want" = 0 ]; then word=queues; else word="does not queue"; fi
  if [ "$HAVE_QUEUES" = yes ]; then
    got="$( . "$REPO_ROOT/scripts/run-lock.sh"; set -f; run_lock_queues "$cmd"; printf '%s' "$?")"
    assert_eq "run_lock_queues '$cmd' $word" "$want" "$got"
  else
    _bad "run_lock_queues '$cmd' $word" "scripts/run-lock.sh defines no run_lock_queues"
  fi
done <<EOF
$QUEUE_ROWS
EOF

describe "HARNESS-111 C-2, C-3  the two lines of scripts/run-lock.sh the suite and DV-1 depend on"

assert_eq "scripts/run-lock.sh opens run_lock_queues alone on its line" 1 \
  "$(grep -cxF 'run_lock_queues() {' "$REPO_ROOT/scripts/run-lock.sh" 2>/dev/null || :)"
assert_eq "run_lock_join asks run_lock_queues, on exactly the one line DV-1 mutates" 1 \
  "$(grep -cxF '  run_lock_queues "$2" || return 0' "$REPO_ROOT/scripts/run-lock.sh" 2>/dev/null || :)"

# ---------------------------------------------------------------------------
describe "C-4, C-6  the shipped pieces the mutations and the messages depend on"

RQS="$REPO_ROOT/scripts/run-queue.sh"
assert_eq "scripts/run-queue.sh defines run_queue_alive on exactly the one line DV-1 mutates" 1 \
  "$(grep -cxF 'run_queue_alive() { kill -0 "$1" 2>/dev/null; }' "$RQS" 2>/dev/null || :)"
assert_eq "scripts/run-lock.sh opens run_lock_full on exactly the one line DV-3 mutates" 1 \
  "$(grep -cxF 'run_lock_full() {' "$REPO_ROOT/scripts/run-lock.sh" 2>/dev/null || :)"
for row in '0 0m00s' '59 0m59s' '60 1m00s' '65 1m05s' '10800 180m00s'; do
  n="${row% *}"; want="${row#* }"
  if [ -f "$RQS" ]; then
    assert_eq "run_queue_span $n is $want" "$want" "$( . "$RQS"; run_queue_span "$n")"
  else
    _bad "run_queue_span $n is $want" "scripts/run-queue.sh does not exist"
  fi
done

summary "run-queue"
