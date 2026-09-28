#!/usr/bin/env bash
# Run the harness's own tests.
#
#   bash scripts/selftest.sh            every suite in .claude/tests
#   bash scripts/selftest.sh phase-guard one suite, by name
#   VERBOSE=1 bash scripts/selftest.sh  name every assertion, not just failures
#
# These test the harness, not the project built with it: the phase lock, the
# path classifier, the hooks. They need bash, git and coreutils and nothing
# else, so they run before a stack has been chosen - which is the point, since
# the harness has to be trustworthy from the first story onwards.
#
# The project's own gates are a separate thing entirely: scripts/gates.sh.
#
# --- assertion floors (MT-039) ----------------------------------------------
#
# A suite's exit status is not evidence that it did any work: a suite that
# executed zero assertions exits 0, and a suite replaced by a single `printf`
# exits 0. So each suite also declares in .claude/tests/floors.conf how much
# work it is worth, and this script reads the EXECUTED assertion count back out
# of the suite's own stdout - the `N` of summary()'s `<name>: N passed, M
# failed` line, matched anchored and by name, last match winning - then fails
# the run when a suite did less than it declared. That count is not the number
# of `assert_` call sites in the source: `profiles` is ONE call site inside a
# loop and FORTY-FOUR executed assertions.
#
# Two rules about scope, and the second is C-4(b) of MT-039:
#
#   * a suite that prints no summary line at all FAILS. "No count could be
#     read" is the strongest form of the defect, not an excuse to skip the
#     check.
#   * a FULL run audits the whole floors file: a line naming a suite that does
#     not exist, a non-numeric value, or a suite with no floor line each fail
#     the run, before any suite is executed. A SINGLE-suite run enforces only
#     that suite's own floor, so that adding a suite does not cost a full run
#     to learn one number; if the named suite has no floor it warns loudly and
#     exits 0. CI and scripts/ci-local.sh both invoke the full run, which is
#     where the audit has to hold.
#
# --- concurrency (MT-042) ---------------------------------------------------
#
#   SELFTEST_JOBS=2 bash scripts/selftest.sh   at most two suites at once
#   SELFTEST_JOBS=1 bash scripts/selftest.sh   the serial runner
#
# Suites run concurrently, at most $SELFTEST_JOBS at once. Unset or empty means
# 4, the CI runner's vCPU count, and deliberately not `nproc`: the work is
# spawn-bound, and on Windows more jobs than cores is slower, not faster.
# Anything that is not a positive integer is refused before any suite starts,
# because a bound of 0 would never start anything.
#
# Four properties, each of which a concurrent runner gets wrong by default:
#
#   * EVERY job's exit status is collected on its own. A finished job is
#     noticed with `kill -0 <pid>` and its status is then read with
#     `wait <pid>`, which returns that job's status even though it has already
#     exited. A bare `wait` would not. Should a bash ever forget a reaped job,
#     `wait` returns 127 ("not a child"), which counts as a FAILURE, so this
#     fails closed and never reports a lost status as a pass.
#   * Output is BUFFERED per suite, in .claude/state/selftest/<name>.out under
#     this script's own root (stdout and stderr together, as `2>&1` always
#     was), and printed in GLOB order, each suite contiguous under its header,
#     whatever order the suites finish in. A suite is printed as soon as it
#     and every suite before it in the glob have finished. Each suite's floor
#     is read from its own buffer. No buffer is left behind, pass or fail; one
#     that survives means a run was killed, and it is safe to delete.
#   * The LARGEST suite files start first. A run cannot finish before its
#     longest suite does, so that suite must not wait in the queue behind short
#     ones. Starting in glob order put `phase-guard` ~108 s late, which is over
#     MT-042 AC-1's 1.10x ceiling before any contention is counted. File size is
#     the proxy, because it needs no timing data and names no suite.
#   * A slot is refilled the moment ANY job exits. Without bash 4.3's `wait -n`
#     that means polling, and each `sleep` is a fork, so the interval backs off
#     from 0.1 s to 2 s while nothing changes and resets when a job ends. The
#     suites run for seconds to minutes, so 2 s is nothing on the critical path.
#
# SERIAL_SUITES, below, is the escape hatch for a suite that proves not to be
# parallel-safe (MT-042 C-3). A suite named there runs alone, before the
# concurrent ones, with no other suite alive. Its floor is still read and it
# still prints in glob order. It is a line in this file, not an environment
# variable, so that the exception is visible in the repository. It ships empty.
#
# Bash 3.2: no `wait -n`, no associative arrays, no mapfile; the tests grep for
# them.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ONLY="${1:-}"

# Space-separated suite names, each of which runs with no other suite alive.
SERIAL_SUITES=""

# The job bound, validated before anything else happens.
JOBS="${SELFTEST_JOBS:-}"
case "$JOBS" in
  '') JOBS=4 ;;
  *[!0-9]*) JOBS="" ;;
  *) JOBS="${JOBS#"${JOBS%%[!0]*}"}" ;;   # strip leading zeros; all zeros -> empty
esac
if [ -z "$JOBS" ]; then
  printf "SELFTEST_JOBS must be a positive integer, the number of suites run at once; got '%s'. Nothing was run.\n" \
    "${SELFTEST_JOBS:-}" >&2
  exit 1
fi

# Resolved from the script's own root, never $PWD and never a baked path: the
# harness's fixtures run a copy of this script from a throwaway tree.
TESTS_DIR="$ROOT/.claude/tests"
FLOORS_REL=".claude/tests/floors.conf"
FLOORS_FILE="$ROOT/$FLOORS_REL"

TAB=$(printf '\t')
CR=$(printf '\r')

# trim <string>   Result in $TRIMMED. Pure bash: no subshell, no process.
TRIMMED=""
trim() {
  TRIMMED="$1"
  TRIMMED="${TRIMMED#"${TRIMMED%%[![:space:]]*}"}"
  TRIMMED="${TRIMMED%"${TRIMMED##*[![:space:]]}"}"
}

# --- the floors table -------------------------------------------------------
# "<suite><TAB><floor>" lines; no associative arrays, for bash 3.2 - as
# gates.sh does for project.conf, and the grammar is deliberately the same:
# `#` comments and blank lines ignored, `|`-separated, space trimmed.
FLOORS=""
# "<suite><TAB><message>" lines. The suite name is carried so that a single-
# suite run can tell its own fault from somebody else's (C-4(b)).
FAULTS=""

if [ -f "$FLOORS_FILE" ]; then
  lineno=0
  while IFS= read -r line || [ -n "$line" ]; do
    lineno=$((lineno+1))
    line="${line%$CR}"
    trim "$line"; line="$TRIMMED"
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in
      *'|'*'|'*) ;;
      *) FAULTS="$FAULTS$TAB$FLOORS_REL:$lineno  is not a floor line: '$line'
"; continue ;;
    esac
    rest="$line"
    kind="${rest%%|*}"; rest="${rest#*|}"
    name="${rest%%|*}"; value="${rest#*|}"
    trim "$kind";  kind="$TRIMMED"
    trim "$name";  name="$TRIMMED"
    trim "$value"; value="$TRIMMED"
    if [ "$kind" != floor ]; then
      FAULTS="$FAULTS$name$TAB$FLOORS_REL:$lineno  unknown kind '$kind'; the only kind is 'floor'
"
      continue
    fi
    if [ ! -f "$TESTS_DIR/$name.test.sh" ]; then
      FAULTS="$FAULTS$name$TAB$FLOORS_REL:$lineno  floor names '$name', but .claude/tests/$name.test.sh does not exist
"
      continue
    fi
    case "$value" in
      ''|*[!0-9]*)
        FAULTS="$FAULTS$name$TAB$FLOORS_REL:$lineno  floor for '$name' is not a number: '$value'
"
        continue ;;
    esac
    FLOORS="$FLOORS$name$TAB$value
"
  done < "$FLOORS_FILE"
fi

# Both lookups below set a global rather than printing, and both are pure bash.
# That is deliberate and it is DV-5: a command substitution is a fork, and on
# Windows a fork costs ~150 ms, so an awk per suite plus a `basename` per suite
# in the name pass added ~2 s to EVERY invocation - which on the 2.5 s suites
# agents iterate against is a tax of most of a run. Reading a line of output and
# comparing an integer should be free, and this way it is: the floors mechanism
# spawns no process at all.

# floor_of <suite>   Sets $FLOOR to the declared floor, or empty. Last wins.
FLOOR=""
floor_of() {
  local n="$1" line
  FLOOR=""
  while IFS= read -r line; do
    case "$line" in "$n$TAB"*) FLOOR="${line#*"$TAB"}" ;; esac
  done <<FLOOR_LINES
$FLOORS
FLOOR_LINES
}

# executed_count <suite> <output>   Sets $COUNT to the N of
# `<name>: N passed, M failed`, anchored at column one, keyed by name, LAST
# match winning - so that an indented line, a line under another name, or an
# early decoy cannot be read as the count. Empty when the suite printed no such
# line at all, which is a failure and never a reason to skip the check.
# The name is matched as a QUOTED case pattern, so a suite whose name contains
# a glob or regex character is still matched literally.
COUNT=""
executed_count() {
  local n="$1" line rest passed failed
  COUNT=""
  while IFS= read -r line; do
    case "$line" in "$n: "*) ;; *) continue ;; esac
    rest="${line#"$n": }"
    case "$rest" in *' passed, '*' failed') ;; *) continue ;; esac
    passed="${rest%% passed,*}"
    failed="${rest#* passed, }"; failed="${failed% failed}"
    case "$passed" in ''|*[!0-9]*) continue ;; esac
    case "$failed" in ''|*[!0-9]*) continue ;; esac
    COUNT="$passed"
  done <<SUITE_OUTPUT
$2
SUITE_OUTPUT
}

# --- what this run is going to run ------------------------------------------
# Names by parameter expansion rather than `basename`, for the reason above: a
# fork per suite, twice over, is the whole cost of this mechanism on Windows.
# The same list is kept as indexed arrays, in glob order, for the run below.
SUITES=""
S_NAME=(); S_FILE=(); N=0
for suite in "$TESTS_DIR"/*.test.sh; do
  [ -e "$suite" ] || continue
  name="${suite##*/}"; name="${name%.test.sh}"
  [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && continue
  SUITES="$SUITES$name
"
  S_NAME[$N]="$name"; S_FILE[$N]="$suite"; N=$((N+1))
done

# AC-6, on a full run only: a suite with no floor is a suite that can be
# emptied. Reported before anything executes - a floors file that is wrong is
# worth knowing about in a second rather than after the whole suite has run.
if [ -z "$ONLY" ]; then
  [ -f "$FLOORS_FILE" ] || [ -z "$SUITES" ] || \
    FAULTS="$FAULTS$TAB$FLOORS_REL  does not exist; every suite must declare its assertion floor there
"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    floor_of "$name"
    [ -n "$FLOOR" ] || \
      FAULTS="$FAULTS$name$TAB$name  no floor line in $FLOORS_REL; every suite must declare one
"
  done <<SUITE_NAMES
$SUITES
SUITE_NAMES
fi

# Report the faults this run is answerable for. A single-suite run answers for
# its own suite's line and for nothing else (C-4(b)).
faulted=0
while IFS="$TAB" read -r fname fmsg; do
  [ -n "$fmsg" ] || continue
  [ -n "$ONLY" ] && [ "$ONLY" != "$fname" ] && continue
  printf 'FAIL %s\n' "$fmsg"
  faulted=$((faulted+1))
done <<FAULT_LINES
$FAULTS
FAULT_LINES
if [ "$faulted" -gt 0 ]; then
  printf '\n%d fault(s) in %s. Nothing was run.\n' "$faulted" "$FLOORS_REL"
  exit 1
fi

if [ "$N" -eq 0 ]; then
  printf 'No suites matched%s. Looked in .claude/tests/*.test.sh\n' "${ONLY:+ '$ONLY'}" >&2
  exit 1
fi

# --- run --------------------------------------------------------------------
# Per suite, by glob index: S_PID (empty until started), S_DONE (0/1), S_RC.
BUF_DIR="$ROOT/.claude/state/selftest"
[ -d "$BUF_DIR" ] || mkdir -p "$BUF_DIR" || {
  printf 'selftest.sh: cannot create %s for the output buffers\n' "$BUF_DIR" >&2
  exit 1
}
S_PID=(); S_DONE=(); S_RC=()
i=0
while [ "$i" -lt "$N" ]; do S_PID[$i]=""; S_DONE[$i]=0; S_RC[$i]=0; i=$((i+1)); done

# On the way out, however the runner ends: any suite still running is stopped,
# rather than left orphaned and writing to a buffer nobody will read, and this
# run's own buffers are removed, in one process. On a normal exit nothing is
# running. It matters when the runner itself dies - an interrupt, or a runner
# edited under a live run, which bash reads incrementally and will misparse
# (MT-042 GREEN hit exactly that and left four suites running).
cleanup() {
  local j files
  for j in $ALIVE; do kill "${S_PID[$j]}" 2>/dev/null; done
  files=(); j=0
  while [ "$j" -lt "$N" ]; do
    [ -e "$BUF_DIR/${S_NAME[$j]}.out" ] && files[${#files[@]}]="$BUF_DIR/${S_NAME[$j]}.out"
    j=$((j+1))
  done
  [ "${#files[@]}" -eq 0 ] || rm -f "${files[@]}"
}
on_signal() { exit "$1"; }
ALIVE=""      # glob indices of the suites now running, space-separated
RUNNING=0
trap cleanup EXIT
trap 'on_signal 130' INT
trap 'on_signal 143' TERM

# start <index>   In the background. The redirect is made before the suite's
# first line runs, so its buffer exists from the start.
start() {
  bash "${S_FILE[$1]}" > "$BUF_DIR/${S_NAME[$1]}.out" 2>&1 &
  S_PID[$1]=$!
  ALIVE="$ALIVE $1"
  RUNNING=$((RUNNING+1))
}

# reap   Collects every job that has exited, each by its own pid, and sets
# REAPED to how many. `kill -0` fails once the job is gone; `wait <pid>` then
# returns that job's own status.
REAPED=0
reap() {
  local j still=""
  REAPED=0
  for j in $ALIVE; do
    if kill -0 "${S_PID[$j]}" 2>/dev/null; then
      still="$still $j"
    else
      wait "${S_PID[$j]}"; S_RC[$j]=$?
      S_DONE[$j]=1
      RUNNING=$((RUNNING-1)); REAPED=$((REAPED+1))
    fi
  done
  ALIVE="$still"
}

# wait_until <n>   Returns once at most <n> suites are running, printing every
# suite that becomes printable on the way. Polls, backing off while nothing
# changes: see "concurrency" at the top.
NAP=0.1
wait_until() {
  while [ "$RUNNING" -gt "$1" ]; do
    reap
    if [ "$REAPED" -gt 0 ]; then
      flush; NAP=0.1
    else
      sleep "$NAP"
      case "$NAP" in 0.1) NAP=0.2 ;; 0.2) NAP=0.5 ;; 0.5) NAP=1 ;; *) NAP=2 ;; esac
    fi
  done
}

# flush   Prints, in glob order, every finished suite not yet printed whose
# predecessors have all been printed.
NEXT=0
flush() {
  while [ "$NEXT" -lt "$N" ] && [ "${S_DONE[$NEXT]}" -eq 1 ]; do
    report "$NEXT"
    NEXT=$((NEXT+1))
  done
}

fails=0; ran=0; floored=0; met=0; executed=0; declared=0
NL='
'
# report <index>   The suite's header, its buffer, and its floor verdict.
report() {
  local name="${S_NAME[$1]}" rc="${S_RC[$1]}" out="" bad floor observed
  printf '\n=== %s ===\n' "$name"

  # Buffered rather than streamed, because the count is read back out of it -
  # and printed in full, because a failing suite whose output was swallowed
  # makes every failure a second command to reproduce. Read by `read -d ''`,
  # a builtin, where `$(cat)` would be a fork; trailing newlines are then
  # stripped, which is exactly what the `$(...)` capture it replaces did.
  IFS= read -r -d '' out < "$BUF_DIR/$name.out"
  out="${out%"${out##*[!$NL]}"}"
  printf '%s\n' "$out"

  bad=0
  [ "$rc" -eq 0 ] || bad=1
  ran=$((ran+1))

  floor_of "$name"; floor="$FLOOR"
  if [ -z "$floor" ]; then
    # Only reachable on a single-suite run; a full run has already failed above.
    printf 'WARNING: no floor line for %s in %s, so this run cannot tell\n' \
      "$name" "$FLOORS_REL" >&2
    printf 'WARNING: whether that suite did any work. Declare one before the full run.\n' >&2
  else
    floored=$((floored+1))
    declared=$((declared+floor))
    executed_count "$name" "$out"; observed="$COUNT"
    if [ -z "$observed" ]; then
      printf 'FAIL %s  printed no summary line, so its floor of %s could not be checked\n' \
        "$name" "$floor"
      bad=1
    else
      executed=$((executed+observed))
      if [ "$observed" -lt "$floor" ]; then
        printf 'FAIL %s  did %s units of work, below the floor of %s in %s\n' \
          "$name" "$observed" "$floor" "$FLOORS_REL"
        bad=1
      else
        met=$((met+1))
      fi
    fi
  fi

  [ "$bad" -eq 0 ] || fails=$((fails+1))
}

# --- the start order --------------------------------------------------------
# Pinned suites first, in glob order; then the rest, largest file first, ties
# in glob order. One `wc -c` over every file is the only process this costs,
# and it is skipped when there is nothing to reorder. Each of wc's lines is
# matched to its file by path, so a file wc could not read sorts last rather
# than shifting every size after it.
PINNED=""; POOL=""
i=0
while [ "$i" -lt "$N" ]; do
  case " $SERIAL_SUITES " in
    *" ${S_NAME[$i]} "*) PINNED="$PINNED $i" ;;
    *) POOL="$POOL $i" ;;
  esac
  i=$((i+1))
done

if [ "$JOBS" -gt 1 ] && [ "$N" -gt 1 ]; then
  S_SIZE=()
  i=0; while [ "$i" -lt "$N" ]; do S_SIZE[$i]=0; i=$((i+1)); done
  SIZES="$(wc -c "${S_FILE[@]}" 2>/dev/null)"
  i=0
  while IFS= read -r line; do
    # wc prints in argument order, so search forward from the last match.
    j="$i"
    while [ "$j" -lt "$N" ]; do
      case "$line" in *" ${S_FILE[$j]}") break ;; esac
      j=$((j+1))
    done
    [ "$j" -lt "$N" ] || continue          # the `total` line, or noise
    trim "${line% "${S_FILE[$j]}"}"
    case "$TRIMMED" in ''|*[!0-9]*) ;; *) S_SIZE[$j]="$TRIMMED" ;; esac
    i=$((j+1))
  done <<WC_LINES
$SIZES
WC_LINES
  # Insertion sort, descending by size; strict comparison keeps it stable.
  SORTED=""
  for i in $POOL; do
    before=""; after=""; placed=0
    for j in $SORTED; do
      if [ "$placed" -eq 0 ] && [ "${S_SIZE[$i]}" -gt "${S_SIZE[$j]}" ]; then
        after="$after $i"; placed=1
      fi
      if [ "$placed" -eq 0 ]; then before="$before $j"; else after="$after $j"; fi
    done
    [ "$placed" -eq 1 ] || after="$after $i"
    SORTED="$before$after"
  done
  POOL="$SORTED"
fi

# --- the run ----------------------------------------------------------------
for i in $PINNED; do
  # Nothing else is alive: the pinned suites run before any other starts.
  start "$i"
  wait_until 0
done
for i in $POOL; do
  wait_until $((JOBS-1))
  start "$i"
done
wait_until 0
flush

printf '\n'
if [ "$floored" -eq 0 ]; then
  :
elif [ "$met" -eq "$floored" ]; then
  # The totals are printed only when every count was actually read: a suite
  # that printed no summary line has an UNKNOWN executed count, and adding a
  # zero for it would report less work than was done.
  printf 'assertion floors: all %d suite(s) met their declared floor (%d assertions executed, %d declared).\n' \
    "$floored" "$executed" "$declared"
else
  printf 'assertion floors: %d of %d suite(s) met their declared floor.\n' "$met" "$floored"
fi
if [ "$fails" -gt 0 ]; then
  printf '%d of %d harness suite(s) FAILED.\n' "$fails" "$ran"
  exit 1
fi
printf '%d harness suite(s) passed.\n' "$ran"
