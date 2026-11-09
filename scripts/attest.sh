#!/usr/bin/env bash
# Run a verification command once, record it against the tree it ran on, and let
# the orchestrator check that record instead of running the command again.
#
#   bash scripts/attest.sh -- <word>...          run the words, record the run, exit with the command's status
#   bash scripts/attest.sh check -- <word>...    is there a fresh record for exactly these words on this tree?
#   bash scripts/attest.sh show                  every record whose tree: is the current work hash
#
# Why (HARNESS-084). A subagent runs the tests and `gates.sh --fast`, then the
# orchestrator ran both again against the same tree - on a harness story, tens
# of minutes per phase spent learning nothing new. A run here is stamped with
# work_tree_hash (lib.sh): gate_tree_hash's tree plus the untracked gated
# files, so a RED subagent's new, untracked test file counts. `check` answers
# whether the newest record for exactly these words was made on the tree as it
# is now. `fresh` says the command RAN on this tree, not that it passed: read
# `exit:` and `last:`, and the log when you need more. A RED run is supposed to
# exit non-zero, and folding the exit status into the answer would hide that.
#
# The words after `--` are executed directly ("$@"), never through a shell.
# Leading NAME=value words go into the command's environment (never this
# script's own) and are not executed, so
# `SELFTEST_JOBS=4 bash scripts/selftest.sh` is one attestable command; the
# recorded `command:` is ALL the words, joined by one space, and `check`
# compares that string for equality - `a b` and `b a` are two commands. A word
# holding a newline or a CR is a usage error: it would forge record lines.
#
# The command's output goes to .claude/state/attest-logs/<run>.<pid>.log, not
# the terminal; this prints the record, then the last ATTEST_TAIL (default 20)
# lines of the log. Never the whole output: that is the point.
#
# The record is MACHINE-LOCAL and is never evidence to CI. It stands in for the
# orchestrator's re-run, not for ## Gate results, which gates.sh alone writes.
# A run whose tree moved while it ran is `void`: it ran on a tree nobody will
# see again. So is a run made while a mutation is stranded - refused outright,
# exit 2, as gates.sh refuses (HARNESS-030).
#
# Exit: the command's status; for `check`, 0 fresh / 1 otherwise; 2 on a usage
# error or a stranded mutation, which record nothing.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The root is this script's own, as gates.sh's is - never CLAUDE_PROJECT_DIR,
# which names whichever tree the session started in. The caller's value (or its
# absence) is kept for the command, which must run in the caller's environment.
CALLER_CPD="${CLAUDE_PROJECT_DIR-}"; CALLER_CPD_SET="${CLAUDE_PROJECT_DIR+1}"
export CLAUDE_PROJECT_DIR="$ROOT"
. "$ROOT/.claude/hooks/lib.sh"
set_harness_root "$ROOT"

ALOG_REL=".claude/state/attest.log"
ALOG="$ROOT/$ALOG_REL"

usage() {
  printf 'usage: bash scripts/attest.sh -- <command>...\n' >&2
  printf '       bash scripts/attest.sh check -- <command>...\n' >&2
  printf '       bash scripts/attest.sh show\n' >&2
  exit 2
}

# field_of <block> <key>   The value of <key>: in <block>, padding stripped.
field_of() {
  awk -v k="$2" '{ sub(/\r$/, "") } index($0, k ":") == 1 { v = substr($0, length(k) + 2); sub(/^ +/, "", v); print v; exit }' <<FIELD_IN
$1
FIELD_IN
}

# newest_block <command>   The last block in attest.log whose command: equals
# <command>, exactly; empty when there is none. Passed through ENVIRON, not -v,
# which would read backslashes in a Windows path as escapes.
newest_block() {
  [ -f "$ALOG" ] || return 0
  WANT="$1" awk '
    BEGIN { RS = ""; want = ENVIRON["WANT"] }
    {
      n = split($0, l, "\n"); cmd = ""
      for (i = 1; i <= n; i++) {
        sub(/\r$/, "", l[i])
        if (index(l[i], "command:") == 1) { cmd = substr(l[i], 9); sub(/^ +/, "", cmd) }
      }
      if (cmd == want) { b = l[1]; for (i = 2; i <= n; i++) b = b "\n" l[i] }
    }
    END { if (b != "") print b }' "$ALOG"
}

# --- arguments -----------------------------------------------------------------

[ $# -gt 0 ] || usage
MODE=""
case "$1" in
  --)    MODE=run; shift ;;
  check) [ "${2:-}" = "--" ] || usage; MODE=check; shift 2 ;;
  show)  [ $# -eq 1 ] || usage; MODE=show ;;
  *)     usage ;;
esac
if [ "$MODE" != show ]; then
  [ $# -gt 0 ] || usage
  # A word holding a newline or a CR would write extra lines into the record:
  # a forged `command:` line, and `check` answering `fresh` for a command that
  # never ran. Refused before anything runs or is recorded, in both modes.
  for w in "$@"; do
    case "$w" in *$'\n'*|*$'\r'*) usage ;; esac
  done
  WORDS="$*"   # IFS is the default here, so one space between words
fi

# --- show ----------------------------------------------------------------------

if [ "$MODE" = show ]; then
  now="$(work_tree_hash)" || { printf 'the work hash is unavailable; no record can match it\n'; exit 1; }
  [ -f "$ALOG" ] || exit 0
  NOW="$now" awk '
    BEGIN { RS = "" }
    {
      n = split($0, l, "\n"); tree = ""
      for (i = 1; i <= n; i++) {
        sub(/\r$/, "", l[i])
        if (index(l[i], "tree:") == 1) { tree = substr(l[i], 6); sub(/^ +/, "", tree) }
      }
      if (tree == ENVIRON["NOW"]) { for (i = 1; i <= n; i++) print l[i]; print "" }
    }' "$ALOG"
  exit 0
fi

# --- check ---------------------------------------------------------------------

if [ "$MODE" = check ]; then
  block="$(newest_block "$WORDS")"
  if [ -z "$block" ]; then
    printf 'none: no record for this command\n'; exit 1
  fi
  printf '%s\n' "$block"
  status="$(field_of "$block" status)"
  case "$status" in
    ok) ;;
    *) printf '%s\n' "$status"; exit 1 ;;   # void: <why>, verbatim; outranks the hash
  esac
  tree="$(field_of "$block" tree)"
  now="$(work_tree_hash)"   # `unavailable` on failure, which no record's tree: equals
  if [ "$tree" != "$now" ] || [ "$now" = unavailable ]; then
    printf 'stale: recorded on %s at %s, the tree is now %s\n' "$tree" "$(field_of "$block" run)" "$now"
    exit 1
  fi
  printf 'fresh\n'
  exit 0
fi

# --- run -----------------------------------------------------------------------

# Leading assignments go into the command's environment, not its argv - and
# never into this shell's: ROOT=, ALOG= or HARNESS_ROOT= must not move the
# record, the log or the tree hashed, nor skip the mutation refusal below.
ASSIGNS=()
while [ $# -gt 0 ] && [[ $1 =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do
  ASSIGNS+=("$1")
  shift
done
[ $# -gt 0 ] || usage

# A run behind a stranded mutation is a run on a tree nobody will see again.
if [ -f "$ROOT/scripts/mutate.sh" ]; then
  if ! mutation_report="$(bash "$ROOT/scripts/mutate.sh" --check 2>&1)"; then
    printf '%s\n' "$mutation_report" >&2
    printf 'attest: refusing to run. The record would name a tree that may hold a mutation nobody restored.\n' >&2
    exit 2
  fi
fi

TAIL="${ATTEST_TAIL:-20}"
case "$TAIL" in ''|*[!0-9]*) TAIL=20 ;; esac

RUN="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LOG_REL=".claude/state/attest-logs/${RUN//[-:]/}.$$.log"   # no colons: NTFS refuses them
mkdir -p "$ROOT/.claude/state/attest-logs"

TREE="$(work_tree_hash)"
started=$SECONDS
# A subshell sets them and execs: the command sees them, attest.sh does not.
# Not `env NAME=v "$@"`, which would also read a later word containing `=`
# (say `./a=b`) as an assignment. The caller's CLAUDE_PROJECT_DIR comes back
# first, so a leading CLAUDE_PROJECT_DIR= assignment still wins (return 4).
( if [ -n "$CALLER_CPD_SET" ]; then export CLAUDE_PROJECT_DIR="$CALLER_CPD"; else unset CLAUDE_PROJECT_DIR; fi
  for a in ${ASSIGNS[@]+"${ASSIGNS[@]}"}; do export "${a%%=*}=${a#*=}"; done
  exec "$@" ) > "$ROOT/$LOG_REL" 2>&1
rc=$?
duration=$((SECONDS - started))
AFTER="$(work_tree_hash)"

if [ "$TREE" = unavailable ] || [ "$AFTER" = unavailable ]; then
  status="void: hash unavailable"
elif [ "$TREE" != "$AFTER" ]; then
  status="void: tree changed during the run"
else
  status="ok"
fi
last="$(awk '{ sub(/\r$/, "") } NF { l = $0 } END { print l }' "$ROOT/$LOG_REL")"
[ -n "$last" ] || last="(no output)"

block="$(printf '%-9s %s\n' \
  run: "$RUN" command: "$WORDS" tree: "$TREE" after: "$AFTER" status: "$status" \
  exit: "$rc" duration: "${duration}s" last: "$last" log: "$LOG_REL")"

if [ -s "$ALOG" ]; then printf '\n%s\n' "$block" >> "$ALOG"
else printf '%s\n' "$block" >> "$ALOG"; fi

printf '%s\n\n--- last %s lines of %s ---\n' "$block" "$TAIL" "$LOG_REL"
tail -n "$TAIL" "$ROOT/$LOG_REL"
exit "$rc"
