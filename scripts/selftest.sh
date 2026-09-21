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

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ONLY="${1:-}"

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
SUITES=""
for suite in "$TESTS_DIR"/*.test.sh; do
  [ -e "$suite" ] || continue
  name="${suite##*/}"; name="${name%.test.sh}"
  [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && continue
  SUITES="$SUITES$name
"
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

# --- run --------------------------------------------------------------------
fails=0; ran=0; floored=0; met=0; executed=0; declared=0
for suite in "$TESTS_DIR"/*.test.sh; do
  [ -e "$suite" ] || continue
  name="${suite##*/}"; name="${name%.test.sh}"
  [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && continue
  printf '\n=== %s ===\n' "$name"

  # Captured rather than streamed, because the count is read back out of it -
  # and reprinted in full immediately, because a failing suite whose output was
  # swallowed makes every failure a second command to reproduce.
  out="$(bash "$suite" 2>&1)"; rc=$?
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
done

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
