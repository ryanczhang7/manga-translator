#!/usr/bin/env bash
# Run the harness's own tests.
#
#   bash scripts/selftest.sh            every suite in .claude/tests
#   bash scripts/selftest.sh phase-guard one suite, by name
#   bash scripts/selftest.sh a b ...    several suites, by name, in glob order
#   bash scripts/selftest.sh --changed [base-ref]
#                                       the suites this branch's diff can break,
#                                       as `selftest-needed.sh --suites` names them
#   VERBOSE=1 bash scripts/selftest.sh  name every assertion, not just failures
#   SELFTEST_JOBS=4 bash scripts/selftest.sh   up to 4 suites at once
#
# SELFTEST_JOBS (HARNESS-036) is opt-in, and unset means 1: one suite at a
# time, exactly as before. With 2 or more over a run of two or more suites, up
# to that many run at once, each into its own buffer under
# .claude/state/selftest.<pid>/, and their output is still printed in suite
# order - byte for byte what a one-at-a-time run prints - each suite as soon as
# it and every suite before it have finished. Anything but a whole number of 1
# or more is refused with exit 2 before anything runs. The self-test is
# spawn-bound, and two spawn-heavy runs on one Windows machine is what hung
# issue #97, so choose a value for a machine you know; CI leaves it unset.
# Measured once on the Windows/Git Bash host this was built on (HARNESS-036
# DV-2, 2026-10-05): the full self-test took 1,135 s with it unset and 336 s
# with SELFTEST_JOBS=4, with identical per-suite results. Suites start in suite
# order, so the slowest one (phase-guard) still sets the floor.
#
# A parallel run that ends before its summary (HARNESS-090) - a signal, a fork
# bash does not return from, an error in the scheduler - still prints, from the
# EXIT handler, the block of every suite it started and could collect, in suite
# order, then an empty line and `selftest: ended before its summary: <p> of <n>
# suite(s) reported (status <s>).`, the suites never started, the started ones
# whose block could not be printed, and, if there are any of those, the buffer
# directory it kept for them. It never prints a summary or a floors line, and
# exits <s>, or 1 if <s> is 0. A suite whose start the scheduler sees fail is
# reported as `FAIL <name>  not started: <error>`, counts as a failure, and the
# run goes on with the next suite.
#
# SELFTEST_FAIL_START is a TEST HOOK and nothing more: a space-separated list of
# suite names whose start, on the parallel path, is not attempted and fails
# with `fork: simulated by SELFTEST_FAIL_START`. It exists so that
# .claude/tests/selftest.test.sh can execute the failed-start path without
# exhausting the host's process table. Leave it unset.
#
# Other test runs on the host (HARNESS-074). Once the run lock is taken and
# before the first suite, scripts/host-load.sh reads `ps -ef` and, if other
# harness test runs (bash or sh running a selftest.sh, *.test.sh or gates.sh)
# outside this run's own process tree are live - another worktree, another
# project - says so on stderr: how many, and the first five by pid and
# command. A slow run then arrives with its circumstances. It is a warning
# only: it never refuses, never waits, and never changes the exit status or a
# byte of stdout. A listing that cannot be read or parsed gets one line saying
# so; an empty listing prints nothing; a missing host-load.sh gets one line and
# the run proceeds. HARNESS_PS_LISTING=<file> replaces `ps -ef` with that
# file's contents. .claude/tests/_lib.sh exports it as /dev/null, so every
# selftest.sh a suite starts - each fixture run and the whole-run goldens, on
# CI as anywhere - sees an empty listing and stays silent. The top-level run
# does not source _lib.sh: CI's own `bash scripts/selftest.sh` reads the
# runner's real `ps -ef`, where no other harness run is expected.
# On Git Bash a process started outside the MSYS runtime (from PowerShell or
# cmd) is not in `ps -ef`, so is not noticed either.
#
# These test the harness, not the project built with it: the phase lock, the
# path classifier, the hooks. They need bash, git and coreutils and nothing
# else, so they run before a stack has been chosen - which is the point, since
# the harness has to be trustworthy from the first story onwards.
#
# The project's own gates are a separate thing entirely: scripts/gates.sh.
#
# --- assertion floors --------------------------------------------------------
#
# Ported from manga-translator's MT-039, which built this downstream while
# upstream had nothing like it, and sent it back rather than lose it to a
# refresh.
#
# A suite's exit status is not evidence that it did any work: a suite that
# executed zero assertions exits 0, and a suite replaced by a single `printf`
# exits 0. So each suite also declares in .claude/tests/floors.conf how much
# work it is worth, and this script reads the EXECUTED assertion count back out
# of the suite's own stdout - the `N` of summary()'s `<name>: N passed, M
# failed` line, matched anchored and by name, last match winning - then fails
# the run when a suite did less than it declared. That count is not the number
# of `assert_` call sites in the source: on this tree `profiles` is ONE call
# site inside a loop and 37 executed assertions.
#
# This is the `evidence` and `floor` idea project.conf already applies to the
# GATES, turned on the harness's own tests. A gate that exits 0 having done
# nothing does not complain; neither does a suite.
#
# Two rules about scope, and the second matters most:
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
# --- a project's own floors (HARNESS-020) -----------------------------------
#
# floors.conf ships upstream and is REPLACED by every refresh, so a consuming
# project cannot floor its own `project-*.test.sh` suites there without the
# next refresh wiping the line. Those floors go in
# .claude/tests/project-floors.conf instead: same grammar, same faults, read
# after floors.conf and only if it exists. Upstream never ships it, so the
# refresh keeps it. Its absence is never a fault. A suite floored in both files
# is a fault against the project file's line - otherwise a project could lower
# an upstream suite's floor from the one file the refresh never replaces. A
# shortfall names the file its floor came from, so the reader edits the right
# one.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# ONLY is the one name of a one-name run, for its no-match message; the set of
# suites a run selects is WANT, built below (HARNESS-094).
ONLY=""
[ "$#" -eq 1 ] && ONLY="$1"

# SELFTEST_JOBS, read before anything else so that a bad value is refused
# before the floors audit, the lock and any suite (HARNESS-036 C-3). Unset and
# empty mean 1; leading zeros are refused rather than normalised.
JOBS="${SELFTEST_JOBS-}"
case "$JOBS" in
  '') JOBS=1 ;;
  *[!0-9]*|0*)
    printf "selftest: SELFTEST_JOBS must be a whole number of suites to run at once, 1 or more; got '%s'. Nothing was run.\n" "$JOBS" >&2
    exit 2 ;;
esac

# Resolved from the script's own root, never $PWD and never a baked path: the
# harness's fixtures run a copy of this script from a throwaway tree.
TESTS_DIR="$ROOT/.claude/tests"
FLOORS_REL=".claude/tests/floors.conf"
FLOORS_FILE="$ROOT/$FLOORS_REL"
PROJECT_FLOORS_REL=".claude/tests/project-floors.conf"
PROJECT_FLOORS_FILE="$ROOT/$PROJECT_FLOORS_REL"

TAB=$(printf '\t')
CR=$(printf '\r')
# The FAULTS separator. Deliberately NOT whitespace: `read` strips a leading
# IFS-whitespace delimiter, so with TAB a fault carrying no suite name
# ("<TAB><message>") came back with the message in the name field and was
# silently dropped - a malformed floors line passed the full run (HARNESS-020).
# A non-whitespace IFS character yields an empty first field instead.
US=$(printf '\037')

# trim <string>   Result in $TRIMMED. Pure bash: no subshell, no process.
TRIMMED=""
trim() {
  TRIMMED="$1"
  TRIMMED="${TRIMMED#"${TRIMMED%%[![:space:]]*}"}"
  TRIMMED="${TRIMMED%"${TRIMMED##*[![:space:]]}"}"
}

# --- the floors table -------------------------------------------------------
# "<suite><TAB><floor><TAB><source-rel-path>" lines; no associative arrays, for
# bash 3.2 - as gates.sh does for project.conf, and the grammar is deliberately
# the same: `#` comments and blank lines ignored, `|`-separated, space trimmed.
# The source travels with the floor so that a shortfall names the file to edit.
FLOORS=""
# "<suite><US><message>" lines. The suite name is carried so that a single-
# suite run can tell its own fault from somebody else's (C-4(b)). A fault that
# belongs to no suite has an EMPTY name, and a full run reports it.
FAULTS=""

# Both lookups below set a global rather than printing, and both are pure bash.
# That is deliberate and it is DV-5: a command substitution is a fork, and on
# Windows a fork costs ~150 ms, so an awk per suite plus a `basename` per suite
# in the name pass added ~2 s to EVERY invocation - which on the 2.5 s suites
# agents iterate against is a tax of most of a run. Reading a line of output and
# comparing an integer should be free, and this way it is: the floors mechanism
# spawns no process at all.

# floor_of <suite>   Sets $FLOOR to the declared floor, or empty, and
# $FLOOR_SRC to the file it was declared in. Last wins.
FLOOR=""
FLOOR_SRC=""
floor_of() {
  local n="$1" line rest
  FLOOR=""; FLOOR_SRC=""
  while IFS= read -r line; do
    case "$line" in
      "$n$TAB"*)
        rest="${line#"$n$TAB"}"
        FLOOR="${rest%%"$TAB"*}"
        FLOOR_SRC="${rest#*"$TAB"}" ;;
    esac
  done <<FLOOR_LINES
$FLOORS
FLOOR_LINES
}

# load_floors <abs-path> <rel-path>   Appends the file's floors to $FLOORS and
# its faults to $FAULTS, every fault located as <rel-path>:<lineno>. One more
# `while read` per file, never a process (DV-5).
load_floors() {
  local file="$1" rel="$2" lineno=0 line rest kind name value
  while IFS= read -r line || [ -n "$line" ]; do
    lineno=$((lineno+1))
    line="${line%$CR}"
    trim "$line"; line="$TRIMMED"
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in
      *'|'*'|'*) ;;
      *) FAULTS="$FAULTS$US$rel:$lineno  is not a floor line: '$line'
"; continue ;;
    esac
    rest="$line"
    kind="${rest%%|*}"; rest="${rest#*|}"
    name="${rest%%|*}"; value="${rest#*|}"
    trim "$kind";  kind="$TRIMMED"
    trim "$name";  name="$TRIMMED"
    trim "$value"; value="$TRIMMED"
    if [ "$kind" != floor ]; then
      FAULTS="$FAULTS$name$US$rel:$lineno  unknown kind '$kind'; the only kind is 'floor'
"
      continue
    fi
    if [ ! -f "$TESTS_DIR/$name.test.sh" ]; then
      FAULTS="$FAULTS$name$US$rel:$lineno  floor names '$name', but .claude/tests/$name.test.sh does not exist
"
      continue
    fi
    case "$value" in
      ''|*[!0-9]*)
        FAULTS="$FAULTS$name$US$rel:$lineno  floor for '$name' is not a number: '$value'
"
        continue ;;
    esac
    # A suite has one floor. Only the project file can collide with the other:
    # floors.conf is loaded first, and a repeat inside one file is last-wins,
    # as it always was.
    if [ "$rel" != "$FLOORS_REL" ]; then
      floor_of "$name"
      if [ "$FLOOR_SRC" = "$FLOORS_REL" ]; then
        FAULTS="$FAULTS$name$US$rel:$lineno  floor for '$name' is already declared in $FLOORS_REL; a suite has one floor
"
        continue
      fi
    fi
    FLOORS="$FLOORS$name$TAB$value$TAB$rel
"
  done < "$file"
}

if [ -f "$FLOORS_FILE" ]; then load_floors "$FLOORS_FILE" "$FLOORS_REL"; fi
if [ -f "$PROJECT_FLOORS_FILE" ]; then
  load_floors "$PROJECT_FLOORS_FILE" "$PROJECT_FLOORS_REL"
fi

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

# --- which suites (HARNESS-094) ----------------------------------------------
# WANT holds the selected names, each between newlines; empty means every
# suite. Names come from the arguments, or - for `--changed [base-ref]` - from
# `selftest-needed.sh --suites [base-ref]`, asked here, before the floors audit
# and the lock: it takes no lock and is seconds. Its answer decides the run:
#   names     the full-run floors audit (every suite floored, the file well
#             formed), a header line, then exactly those suites, as a
#             several-name run runs them
#   `all`     a header line, then a full run
#   nothing   (exit 1) one line saying so, the skip text appended; exit 1, no
#             lock, nothing run
#   else      `cannot select` on stderr, exit 2
# A several-name run (two or more) applies the single-suite floor rule to each
# named suite and audits nothing else; a name that matches no suite stops it
# before the lock. One name is the one-name run it always was.
NL='
'
D='—'
WANT=""
AUDIT=0          # 1: audit the whole floors file, as a full run does
CHANGED_HDR=""   # --changed: the stdout line printed before the first suite
CHECK_NAMES=0    # 1: refuse, before the lock, a selected name that is no suite
selected() {
  [ -z "$WANT" ] && return 0
  case "$WANT" in *"$NL$1$NL"*) return 0 ;; esac
  return 1
}

if [ "${1-}" = --changed ]; then
  # stdout and stderr both captured without a temporary file, which no shipped
  # script may depend on: stderr streams into the outer capture through fd 3,
  # then one US, the status, a newline and stdout follow it, and a closing US
  # so that the substitution cannot strip the newline after an empty stdout.
  SEL="$( { o="$(cd "$ROOT" && bash scripts/selftest-needed.sh --suites "${@:2}" 2>&3)"; r=$?
            printf '%s%s\n%s%s' "$US" "$r" "$o" "$US"; } 3>&1 )"
  sel_err="${SEL%%"$US"*}"; sel_err="${sel_err%"$NL"}"
  rest="${SEL#*"$US"}"; rest="${rest%"$US"}"
  sel_rc="${rest%%"$NL"*}"; sel_out="${rest#*"$NL"}"
  if [ "$sel_rc" = 0 ] && [ "$sel_out" = all ]; then
    [ -z "$sel_err" ] || printf '%s\n' "$sel_err" >&2
    line1="${sel_err%%"$NL"*}"
    CHANGED_HDR="selftest: --changed $D every suite: ${line1#*all: }"
    AUDIT=1
  elif [ "$sel_rc" = 0 ] && [ -n "$sel_out" ]; then
    [ -z "$sel_err" ] || printf '%s\n' "$sel_err" >&2
    WANT="$NL$sel_out$NL"
    AUDIT=1; CHECK_NAMES=1
    CHANGED_HDR=list   # completed once the suites are counted, below
  elif [ "$sel_rc" = 1 ] && [ -z "$sel_out" ]; then
    printf 'selftest: --changed selected no suite %s %s\n' "$D" "$sel_err"
    exit 1
  else
    printf 'selftest: --changed cannot select: %s\n' "$sel_err" >&2
    exit 2
  fi
else
  for a in "$@"; do
    [ -n "$a" ] && WANT="${WANT:-$NL}$a$NL"
  done
  [ -n "$WANT" ] || AUDIT=1
  [ "$#" -ge 2 ] && CHECK_NAMES=1
fi

# --- what this run is going to run ------------------------------------------
# Names by parameter expansion rather than `basename`, for the reason above: a
# fork per suite, twice over, is the whole cost of this mechanism on Windows.
SUITES=""
ALL_SUITES=""
NALL=0
for suite in "$TESTS_DIR"/*.test.sh; do
  [ -e "$suite" ] || continue
  name="${suite##*/}"; name="${name%.test.sh}"
  ALL_SUITES="$ALL_SUITES$name
"
  NALL=$((NALL+1))
  selected "$name" || continue
  SUITES="$SUITES$name
"
done

if [ "$CHECK_NAMES" = 1 ]; then
  unknown=0
  while IFS= read -r a; do
    [ -n "$a" ] || continue
    case "$NL$ALL_SUITES" in
      *"$NL$a$NL"*) ;;
      *) printf "No suites matched '%s'. Looked in .claude/tests/*.test.sh\n" "$a" >&2
         unknown=1 ;;
    esac
  done <<WANT_NAMES
$WANT
WANT_NAMES
  [ "$unknown" = 0 ] || exit 1
fi
if [ "$CHANGED_HDR" = list ]; then
  k=0; names=""
  while IFS= read -r a; do
    [ -n "$a" ] || continue
    k=$((k+1)); names="${names:+$names }$a"
  done <<WANT_COUNT
$WANT
WANT_COUNT
  CHANGED_HDR="selftest: --changed $D $k of $NALL suite(s) selected: $names"
fi

# AC-6, on a full run only: a suite with no floor is a suite that can be
# emptied. Reported before anything executes - a floors file that is wrong is
# worth knowing about in a second rather than after the whole suite has run.
# `--changed` audits as a full run does, whatever it selected.
if [ "$AUDIT" = 1 ]; then
  [ -f "$FLOORS_FILE" ] || [ -z "$ALL_SUITES" ] || \
    FAULTS="$FAULTS$US$FLOORS_REL  does not exist; every suite must declare its assertion floor there
"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    floor_of "$name"
    [ -n "$FLOOR" ] || \
      FAULTS="$FAULTS$name$US$name  no floor line in $FLOORS_REL or $PROJECT_FLOORS_REL; every suite must declare one (a project's own suites go in project-floors.conf)
"
  done <<SUITE_NAMES
$ALL_SUITES
SUITE_NAMES
fi

# Report the faults this run is answerable for. A single-suite run answers for
# its own suite's line and for nothing else (C-4(b)) - so a fault that names no
# suite (a line that is not a floor line, a missing floors.conf) is reported by
# a full run and by no single-suite run, which audits nothing but its own floor.
faulted=0
while IFS="$US" read -r fname fmsg; do
  [ -n "$fmsg" ] || continue
  [ "$AUDIT" = 1 ] || selected "$fname" || continue
  printf 'FAIL %s\n' "$fmsg"
  faulted=$((faulted+1))
done <<FAULT_LINES
$FAULTS
FAULT_LINES
if [ "$faulted" -gt 0 ]; then
  where="$FLOORS_REL"
  [ -f "$PROJECT_FLOORS_FILE" ] && where="$FLOORS_REL or $PROJECT_FLOORS_REL"
  printf '\n%d fault(s) in %s. Nothing was run.\n' "$faulted" "$where"
  exit 1
fi
[ -z "$CHANGED_HDR" ] || printf '%s\n' "$CHANGED_HDR"

# --- the run lock (HARNESS-034) ----------------------------------------------
# A self-test beside gates.sh, or beside another self-test, in one tree is how
# issue #97 got a hang past 30 minutes that passed alone. Every run - full or
# one suite - takes .claude/state/run.lock or refuses with 2 before any suite
# runs; it never waits. After the floors audit, so a malformed floors file is
# reported at once without contending for anything. Traps BEFORE the take, so
# no signal strands a lock; trapped, TERM and INT wait for the running suite
# rather than orphaning it. Suites inherit HARNESS_RUN_LOCK(_PID), which is
# what lets a suite that runs this tree's own selftest.sh through - and what
# a fixture tree, whose lock path differs, ignores.
#
# One EXIT handler (HARNESS-036 C-4): with suites in the background the lock
# may go only after the last of them has exited, so the handler waits for any
# still running, removes this run's buffer directory if it made one, and only
# then releases the lock. On a one-at-a-time run there is nothing to wait for
# and no directory, and it is the release it always was. A trapped TERM or INT
# therefore starts no further suite and lets the running ones finish.
#
# A parallel run whose scheduler loop did not finish (BUF_MADE=1, LOOP_DONE=0)
# is an early end (HARNESS-090): the handler collects the status of every suite
# it waits for, prints each started suite's block it can, names what is missing,
# keeps the buffer directory if any block could not be printed, and exits
# non-zero. It prints no summary. Every array element is read with a default.
# It covers every suite start_suite was entered for - every index below
# ${#PIDS[@]}, which start_suite extends as its first act - not only those
# `started` counts, because `started` moves only after start_suite returns.
# Its second statement ignores INT and TERM, so a second signal cannot end it
# before it has printed and released the lock.
BUF="$ROOT/.claude/state/selftest.$$"
BUF_MADE=0
LOOP_DONE=0
FAIL_START="${SELFTEST_FAIL_START-}"
PIDS=()     # by suite index, glob order; emptied once a suite's status is collected
STARTERR=() # by suite index; non-empty when that suite's start failed
selftest_exit() {
  local st=$?
  trap '' INT TERM
  local i=0 n="${#PIDS[@]}" pid name f kept=0 unreported="" never=""
  while [ "$i" -lt "$n" ]; do
    pid="${PIDS[$i]-}"
    if [ -n "$pid" ]; then
      suite_status "$pid" 2>/dev/null; RCS[$i]=$?
      PIDS[$i]=""
    fi
    i=$((i+1))
  done
  if [ "$BUF_MADE" != 1 ] || [ "$LOOP_DONE" = 1 ]; then
    [ "$BUF_MADE" = 1 ] && rm -rf "$BUF"
    run_lock_release
    return
  fi

  printed="${printed:-0}"
  i="$printed"
  while [ "$i" -lt "$n" ]; do
    name="${NAMES[$i]-}"
    f="$BUF/$name.out"
    if [ -n "${STARTERR[$i]-}" ]; then
      report_unstarted "$name" "${STARTERR[$i]}"
      printed=$((printed+1))
    elif [ -n "${RCS[$i]-}" ] && [ -f "$f" ] && [ -r "$f" ] && out="$(cat "$f" 2>/dev/null)"; then
      suite_header "$name"
      report_suite "$name" "${RCS[$i]}"
      printed=$((printed+1))
    else
      unreported="${unreported:+$unreported }$name"
      kept=1
    fi
    i=$((i+1))
  done
  i="$n"
  while [ "$i" -lt "${NSUITES:-0}" ]; do
    never="${never:+$never }${NAMES[$i]-}"
    i=$((i+1))
  done
  printf '\n'
  printf 'selftest: ended before its summary: %s of %s suite(s) reported (status %s).\n' \
    "$printed" "${NSUITES:-0}" "$st"
  [ -z "$never" ] || printf 'selftest: never started: %s\n' "$never"
  [ -z "$unreported" ] || printf 'selftest: unreported: %s\n' "$unreported"
  [ "$kept" != 1 ] || printf 'selftest: buffers kept: .claude/state/selftest.%s/\n' "$$"

  [ "$kept" = 1 ] || rm -rf "$BUF"
  run_lock_release
  [ "$st" -eq 0 ] || exit "$st"
  exit 1
}
. "$ROOT/scripts/run-lock.sh" || { printf 'run-lock: scripts/run-lock.sh is missing; nothing was run.\n' >&2; exit 2; }
trap selftest_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
run_lock_acquire "$ROOT" "scripts/selftest.sh${*:+ $*}" || exit 2

if [ -f "$ROOT/scripts/host-load.sh" ]; then
  . "$ROOT/scripts/host-load.sh"
  host_load_warn "$$" "${HARNESS_RUN_LOCK_PID:-$$}" >&2
else
  printf 'selftest: scripts/host-load.sh is missing; other test runs on this host were not checked.\n' >&2
fi

# --- run --------------------------------------------------------------------
fails=0; ran=0; floored=0; met=0; executed=0; declared=0

# The per-suite verdict, shared by both paths so that they cannot drift
# (HARNESS-036 C-1). suite_header prints the block's first line; report_suite
# prints the suite's output - the global $out, captured exactly as `$(...)`
# captures it - and judges it: exit status, then the floor read back out of it.
suite_header() { printf '\n=== %s ===\n' "$1"; }
report_suite() {
  local name="$1" rc="$2" bad floor observed
  printf '%s\n' "$out"

  bad=0
  [ "$rc" -eq 0 ] || bad=1
  ran=$((ran+1))

  floor_of "$name"; floor="$FLOOR"   # and $FLOOR_SRC, the file it came from
  if [ -z "$floor" ]; then
    # Only reachable on a single-suite run; a full run has already failed above.
    printf 'WARNING: no floor line for %s in %s, so this run cannot tell\n' \
      "$name" "$FLOORS_REL or $PROJECT_FLOORS_REL" >&2
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
          "$name" "$observed" "$floor" "$FLOOR_SRC"
        bad=1
      else
        met=$((met+1))
      fi
    fi
  fi

  [ "$bad" -eq 0 ] || fails=$((fails+1))
  return 0
}

# The block of a suite whose start failed (HARNESS-090): its header and one
# line. One failure and one suite run; nothing for the floors.
report_unstarted() {
  suite_header "$1"
  printf 'FAIL %s  not started: %s\n' "$1" "$2"
  ran=$((ran+1))
  fails=$((fails+1))
}

# A suite's exit status, collected by its own pid once it has exited. One line,
# exactly: DV-1's mutation targets it. A pid the shell no longer knows makes
# `wait` return 127, which counts as a failure - fail closed.
suite_status() { wait "$1"; }

# start_suite <index>   Start the suite at that index in the background, into
# its buffer (HARNESS-090). Returns 1, with STARTERR[index] saying why, when the
# start failed in a way this shell can see: the `&` reported failure, `$!` did
# not change, or SELFTEST_FAIL_START names the suite (a test hook). Bash prints
# its own fork error on the group's stderr, which is the `.start` file; the
# suite's stderr still goes into its `.out`.
LASTPID=""
start_suite() {
  local i="$1" name rc pid first=""
  name="${NAMES[$i]}"
  PIDS[$i]=""; RCS[$i]=""; STARTERR[$i]=""
  case " ${FAIL_START//[[:space:]]/ } " in
    *" $name "*)
      STARTERR[$i]="fork: simulated by SELFTEST_FAIL_START"
      return 1 ;;
  esac
  { bash "$TESTS_DIR/$name.test.sh" > "$BUF/$name.out" 2>&1 & } 2> "$BUF/$name.start"; rc=$?
  pid="${!-}"
  if [ "$rc" -ne 0 ] || [ -z "$pid" ] || [ "$pid" = "$LASTPID" ]; then
    IFS= read -r first 2>/dev/null < "$BUF/$name.start"
    STARTERR[$i]="${first:-start failed (status $rc)}"
    return 1
  fi
  PIDS[$i]="$pid"
  LASTPID="$pid"
  # A child that failed its own redirection may still hold this open; a
  # failed rm must not matter.
  rm -f "$BUF/$name.start" 2>/dev/null
  return 0
}

NSUITES=0
while IFS= read -r name; do
  [ -n "$name" ] && NSUITES=$((NSUITES+1))
done <<SUITE_COUNT
$SUITES
SUITE_COUNT

if [ "$JOBS" -lt 2 ] || [ "$NSUITES" -lt 2 ]; then
  # One at a time: the loop as it has always been. Nothing in the background,
  # no buffer directory.
  for suite in "$TESTS_DIR"/*.test.sh; do
    [ -e "$suite" ] || continue
    name="${suite##*/}"; name="${name%.test.sh}"
    selected "$name" || continue
    suite_header "$name"

    # Captured rather than streamed, because the count is read back out of it -
    # and reprinted in full immediately, because a failing suite whose output
    # was swallowed makes every failure a second command to reproduce.
    out="$(bash "$suite" 2>&1)"; rc=$?
    report_suite "$name" "$rc"
  done
else
  # Concurrently (HARNESS-036 C-2). Up to $JOBS suites alive at once, started
  # in glob order; a slot is refilled when ANY of them exits. bash 3.2 has no
  # way to wait for whichever job ends first, so the running pids are polled
  # with `kill -0` and a gone one's status is collected with suite_status.
  # Printing is in glob order: a suite's block goes out as soon as it and every
  # suite before it have finished.
  mkdir -p "$BUF" 2>/dev/null || {
    printf "selftest: cannot create .claude/state/selftest.%s for the suites' output; nothing was run.\n" "$$" >&2
    exit 2
  }
  BUF_MADE=1
  NAMES=(); RCS=()
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    NAMES[${#NAMES[@]}]="$name"
  done <<SUITE_LIST
$SUITES
SUITE_LIST

  started=0; printed=0; running=0
  # Each `sleep` is a fork, so back off while nothing changes and start again
  # from the shortest interval whenever something does. The ceiling stays at
  # 1 s: a trapped TERM is acted on only once the current sleep returns.
  delays="0.05 0.1 0.2 0.5 1"
  delay_left="$delays"
  while [ "$printed" -lt "$NSUITES" ]; do
    changed=0
    while [ "$running" -lt "$JOBS" ] && [ "$started" -lt "$NSUITES" ]; do
      if start_suite "$started"; then
        running=$((running+1))
      fi
      started=$((started+1))
    done

    i="$printed"
    while [ "$i" -lt "$started" ]; do
      if [ -n "${PIDS[$i]-}" ] && ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
        suite_status "${PIDS[$i]}"; RCS[$i]=$?
        PIDS[$i]=""
        running=$((running-1)); changed=1
      fi
      i=$((i+1))
    done

    while [ "$printed" -lt "$started" ]; do
      name="${NAMES[$printed]}"
      if [ -n "${STARTERR[$printed]-}" ]; then
        report_unstarted "$name" "${STARTERR[$printed]}"
      elif [ -n "${RCS[$printed]-}" ]; then
        suite_header "$name"
        out="$(cat "$BUF/$name.out")"
        report_suite "$name" "${RCS[$printed]}"
      else
        break
      fi
      printed=$((printed+1))
    done

    if [ "$changed" -eq 1 ]; then
      delay_left="$delays"
    elif [ "$printed" -lt "$NSUITES" ]; then
      delay="${delay_left%% *}"
      [ "$delay_left" = "$delay" ] || delay_left="${delay_left#* }"
      sleep "$delay"
    fi
  done
  LOOP_DONE=1
fi

if [ "$ran" -eq 0 ]; then
  printf 'No suites matched%s. Looked in .claude/tests/*.test.sh\n' "${ONLY:+ '$ONLY'}" >&2
  exit 1
fi

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
