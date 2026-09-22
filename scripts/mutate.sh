#!/usr/bin/env bash
# Apply a diagnostic mutation to one file, run a command against it, and put the
# file back — verifiably.
#
#   bash scripts/mutate.sh <FILE> '<SED-EXPRESSION>' -- <COMMAND> [ARGS...]
#
#   bash scripts/mutate.sh src/camera.ts 's/Math.min(90/Math.min(900/' \
#     -- pnpm exec vitest run tests/camera.test.ts
#
# This is the ONLY sanctioned way to mutate production source, and it is allowed
# in every phase. The phase lock knows about it and does not treat the file it
# names as a write, because the file is restored before this script returns.
#
# Why it exists. The harness requires mutations it did not provide a way to
# make. A test written or corrected while the implementation already exists
# passes on its first execution and every one after, whether or not it asserts
# anything; rules.md says the only thing that earns it is breaking the specific
# production behaviour it claims to pin and watching that one assertion go red.
# In RED, where a corrected test is written, production source is frozen. So the
# same document said "mutate the frozen file" and "never route around the lock",
# and every agent reconciled that privately with `sed -i` — which the lock let
# through only because it discarded any target containing a `$`. Three source
# files were mutated that way in one corrective RED pass. Separately, the one
# mutation made in a phase where source WAS writable lost its backup, because
# the shell had no $TMPDIR, and the restore came down to the substitution
# happening to be an exact inverse of a single-occurrence match.
#
# Hence the three properties that matter more than convenience:
#
#   * The backup is at an explicit path under .claude/state/mutations/, never
#     $TMPDIR, which is not set in every shell this harness runs in.
#   * The restore is CHECKED with cmp and said out loud. A restore that cannot
#     be verified exits 90 and shouts, because the alternative is a mutation
#     left in the tree with a green suite ahead of it.
#   * The directory it works in holds exactly one signal, so a `.bak` left
#     behind means a restore failed and nothing else does. The mutated text
#     is built in a `.new` beside the backup - sed cannot read and write one
#     path - and that file is scratch: its content is the backup put through
#     the expression, and the log records both. A single trap removes it on
#     every path this script can still run code on, so a `.new` that survives
#     means the run was killed outright, and it arrives with its `.bak`.
#
# A mutation that changes nothing is refused before the command runs (exit 3):
# an expression that matches nothing leaves the command green and hands the
# agent a passing test it believes it has earned, which is worse than no probe.
#
# Exit status is the COMMAND's, because a non-zero exit is usually the point —
# the red is the evidence. The exceptions all come with a message: 2 for usage,
# 3 for a mutation that changed nothing (neither reaches the command), and 90
# for a file that is not the original afterwards - a restore that could not be
# verified, or a mutation that could not be written AND could not be undone -
# which overrides everything.
#
# What runs is executed directly, not through a shell, so a redirect or a pipe
# in the payload needs its own `sh -c`. The command runs from the repository
# root, whatever directory you invoked this from.
#
# Deliberately NOT in the allow list in .claude/settings.json, unlike gates.sh and
# phase.sh: everything after `--` is an arbitrary command, so allowlisting this
# script would allowlist every command through it. It is meant to be approved
# per call, like any other command that runs a test suite.
#
# It refuses to mutate ITSELF, for a reason worth knowing before you mutate
# anything a running process reads lazily: see the check below.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MUTDIR="$ROOT/.claude/state/mutations"
LOG="$MUTDIR/log"

usage() {
  printf 'usage: bash scripts/mutate.sh <FILE> '"'"'<SED-EXPRESSION>'"'"' -- <command> [args...]\n' >&2
  printf '\n  e.g. bash scripts/mutate.sh src/camera.ts '"'"'s/90/900/'"'"' -- pnpm exec vitest run\n' >&2
}
die() { printf 'mutate: %s\n' "$1" >&2; usage; exit 2; }

REL="${1:-}"; EXPR="${2:-}"
[ -n "$REL" ] || die "no file given"
[ $# -ge 2 ] || die "no sed expression given"
shift 2
[ -n "$EXPR" ] || die "the sed expression is empty; there is nothing to mutate"
[ "${1:-}" = "--" ] || die "the command must be separated from the expression by -- <command>"
shift
[ $# -ge 1 ] || die "nothing after --; -- <command> is what watches the mutation"
CMD=("$@")

# Resolved against the repository root so that the same invocation works from
# anywhere, which is also what makes the log lines comparable.
case "$REL" in
  /*|?:[/\\]*) FILE="$REL" ;;
  *)           FILE="$ROOT/$REL" ;;
esac
[ -f "$FILE" ] || die "no such file: $REL"

# bash reads a script incrementally rather than loading it whole, so rewriting
# THIS file while it is executing changes what the interpreter reads next: the
# run dies somewhere in the middle and the restore - the last thing it does -
# never happens. The mutation is then left in the tree with nothing to say so,
# which is precisely the outcome this script exists to make impossible. Found by
# probing this script with itself, which is also the only way to find it.
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
if [ "$(cd "$(dirname "$FILE")" 2>/dev/null && pwd)/$(basename "$FILE")" = "$SELF" ]; then
  die "cannot mutate itself: bash reads this script as it runs, so the restore would never happen. Copy it elsewhere and mutate the copy."
fi

mkdir -p "$MUTDIR" || die "cannot create $MUTDIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SAFE="$(printf '%s' "$REL" | tr '/\\ ' '___')"
BAK="$MUTDIR/$SAFE.$STAMP.$$.bak"
NEW="$MUTDIR/$SAFE.$STAMP.$$.new"

# $NEW is scratch and nothing else. sed cannot read and write one path, so the
# mutated text is built here and copied over the original. It is not evidence:
# its content is $BAK put through $EXPR, and the log records both. $BAK is the
# only copy of the original, which is why the directory has exactly one signal
# in it and rules.md states it - a `.bak` left behind means a restore failed.
#
# That sentence ends "everything else it cleans up", and it was not true. Each
# exit path removed the scratch file separately, so the paths that write no log
# line - `cannot write` below, and being killed outright - removed nothing. Two
# `.new` files from different weeks sat in .claude/state/mutations/ with no log
# entry to explain either. One trap, installed before the file exists, is what
# makes the sentence true: the scratch file goes on every path this script can
# still run code on, and the backup survives exactly when the restore could not
# be verified. A `.new` that outlives a run now means the run was killed
# outright, which is the one case nothing here can catch - and it arrives with
# its `.bak`, so the source file is still checkable against the original.
MUTATED=0
RESTORED=0

# Putting the file back is its own function because two traps want it and the
# ordinary path wants it a third time; every call is idempotent, and every call
# decides by CONTENT rather than by $MUTATED. A signal can land between the `cp`
# that mutates the file and the assignment that records it, and a handler that
# trusts the flag in that window deletes the only copy of the original while the
# mutation is still in the tree. Asking `cmp` costs one process and cannot lag.
put_back() {
  [ "$RESTORED" = 1 ] && return 0
  [ -f "$BAK" ] || return 0
  cmp -s "$BAK" "$FILE" 2>/dev/null && return 0
  cp "$BAK" "$FILE" 2>/dev/null
  return 0
}
on_exit() { put_back; rm -f "$NEW" "$NEW.err" 2>/dev/null; return 0; }

# A signal that arrives once the file is mutated is handled the way it always
# was: put the file back, then RETURN, so that the restore-and-verify block
# below still runs and still writes its log line. A signal that arrives before
# the mutation is a different thing - returning would resume a script whose
# scratch file the EXIT trap had just deleted - so that one cleans up and goes.
# $MUTATED decides only WHICH of those two it is, and getting that wrong is
# survivable: put_back has already run either way. The backup goes only when the
# file is verifiably the original, because left behind it would read, under the
# only rule this directory has, as a restore that failed.
on_signal() {
  put_back
  [ "$MUTATED" = 1 ] && return 0
  [ -f "$BAK" ] && cmp -s "$BAK" "$FILE" 2>/dev/null && rm -f "$BAK" 2>/dev/null
  rm -f "$NEW" "$NEW.err" 2>/dev/null
  exit 130
}

cp "$FILE" "$BAK" || die "cannot back up $REL to $BAK"

# Armed only once the backup is a complete copy. Earlier than this, a `cp` that
# failed halfway would leave put_back holding a truncated original and willing
# to write it over the real one; and there is no scratch file to clean up yet.
trap on_exit EXIT
trap on_signal INT TERM

# Read from the backup rather than the live file: a `sed` that reads and writes
# the same path truncates it, and this script's whole claim is that it does not
# lose the original.
if ! sed -e "$EXPR" "$BAK" > "$NEW" 2>"$NEW.err"; then
  printf 'mutate: sed rejected the expression:\n' >&2
  sed -e 's/^/  /' "$NEW.err" >&2
  rm -f "$BAK"
  exit 2
fi
rm -f "$NEW.err"

# A mutation that mutates nothing. Refused here, before the command runs, so
# that nobody reads the resulting green as a probe that passed.
if cmp -s "$BAK" "$NEW"; then
  printf 'mutate: the expression changed nothing in %s.\n' "$REL" >&2
  printf '  A probe that does not alter behaviour cannot show a test discriminates:\n' >&2
  printf '  the command would have passed for the same reason it passes now. Check the\n' >&2
  printf '  expression against the file and try again.\n' >&2
  printf '%s\t%s\t%s\tCHANGED NOTHING - command not run\n' "$STAMP" "$REL" "$EXPR" >> "$LOG" 2>/dev/null || true
  rm -f "$BAK"
  exit 3
fi

# Which lines moved, and how many. One line is the useful case - a probe aimed
# at a single behaviour, whose predicted catch is a single assertion - so the
# count is printed rather than left to be counted by eye.
CHANGED="$(awk 'NR == FNR { a[FNR] = $0; next } { if ($0 != a[FNR]) c++ } END { print c + 0 }' "$BAK" "$NEW")"
LINES="$(awk 'NR == FNR { a[FNR] = $0; next } $0 != a[FNR] { print FNR }' "$BAK" "$NEW")"

printf '=== mutate: %s (%s line(s) changed by %s) ===\n' "$REL" "$CHANGED" "$EXPR"
awk 'NR == FNR { a[FNR] = $0; next }
     $0 != a[FNR] { printf "  %d - %s\n  %d + %s\n", FNR, a[FNR], FNR, $0 }' "$BAK" "$NEW" | head -20

# From here the file is mutated, and the trap installed above restores it on the
# abnormal exits - an interrupt, a signal - where nothing below runs.
if cp "$NEW" "$FILE"; then
  MUTATED=1
else
  # The write failed, so nothing was mutated and there is nothing to go and look
  # at. Say that with the same check the restore below uses rather than assuming
  # it: a `.bak` left here would read, under the only rule this directory has, as
  # a mutation stranded in the tree, and this path writes no log line to correct
  # the impression. If the file genuinely does not match, it is the same failure
  # as a failed restore and gets the same exit code and the same backup.
  cp "$BAK" "$FILE" 2>/dev/null
  if cmp -s "$BAK" "$FILE" 2>/dev/null; then
    rm -f "$BAK"
    die "cannot write $REL; it is unchanged, verified against the backup"
  fi
  printf '\n=== mutate: COULD NOT RESTORE %s ===\n' "$REL" >&2
  printf '%s could not be written, and does not match the backup afterwards.\n' "$REL" >&2
  printf 'The original is still at:\n  %s\nPut it back by hand and check nothing else moved.\n' "$BAK" >&2
  printf '%s\t%s\t%s\t%s line(s)\tcommand: not run\tCOULD NOT RESTORE\n' \
    "$STAMP" "$REL" "$EXPR" "$CHANGED" >> "$LOG" 2>/dev/null || true
  exit 90
fi

printf '\n=== mutate: running %s ===\n' "${CMD[*]}"
( cd "$ROOT" && "${CMD[@]}" )
rc=$?

# --- restore, and check it ---------------------------------------------------
cp "$BAK" "$FILE" 2>/dev/null
RESTORED=1
if cmp -s "$BAK" "$FILE" 2>/dev/null; then
  verdict="restored (verified byte-for-byte against $BAK)"
  printf '\n=== mutate: command exited %d; %s ===\n' "$rc" "$verdict"
  printf '%s\n' "$LINES" | while IFS= read -r n; do
    [ -n "$n" ] || continue
    printf '  %s: %s\n' "$n" "$(awk -v n="$n" 'FNR == n { print; exit }' "$FILE")"
  done
  printf '%s\t%s\t%s\t%s line(s)\tcommand: %s\texited %d\t%s\n' \
    "$STAMP" "$REL" "$EXPR" "$CHANGED" "${CMD[*]}" "$rc" "restored (verified)" >> "$LOG" 2>/dev/null || true
  rm -f "$BAK"
  exit "$rc"
fi

# The one failure mode that must never be quiet.
printf '\n=== mutate: COULD NOT RESTORE %s ===\n' "$REL" >&2
printf 'The command exited %d, but %s does not match the backup afterwards.\n' "$rc" "$REL" >&2
if [ -f "$BAK" ]; then
  printf 'The original is still at:\n  %s\nPut it back by hand and check nothing else moved.\n' "$BAK" >&2
else
  printf 'The backup at %s is gone too, so this script cannot help you: check\n' "$BAK" >&2
  printf 'git status and git diff before running anything that judges this tree.\n' >&2
fi
printf '%s\t%s\t%s\t%s line(s)\tcommand: %s\texited %d\tCOULD NOT RESTORE\n' \
  "$STAMP" "$REL" "$EXPR" "$CHANGED" "${CMD[*]}" "$rc" >> "$LOG" 2>/dev/null || true
exit 90
