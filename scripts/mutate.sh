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
# Hence the two properties that matter more than convenience:
#
#   * The backup is at an explicit path under .claude/state/mutations/, never
#     $TMPDIR, which is not set in every shell this harness runs in.
#   * The restore is CHECKED with cmp and said out loud. A restore that cannot
#     be verified exits 90 and shouts, because the alternative is a mutation
#     left in the tree with a green suite ahead of it.
#
# A mutation that changes nothing is refused before the command runs (exit 3):
# an expression that matches nothing leaves the command green and hands the
# agent a passing test it believes it has earned, which is worse than no probe.
#
# Exit status is the COMMAND's, because a non-zero exit is usually the point —
# the red is the evidence. The exceptions all come with a message: 2 for usage,
# 3 for a mutation that changed nothing (neither reaches the command), and 90
# for a restore that could not be verified, which overrides everything.
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

cp "$FILE" "$BAK" || die "cannot back up $REL to $BAK"

# Read from the backup rather than the live file: a `sed` that reads and writes
# the same path truncates it, and this script's whole claim is that it does not
# lose the original.
if ! sed -e "$EXPR" "$BAK" > "$NEW" 2>"$NEW.err"; then
  printf 'mutate: sed rejected the expression:\n' >&2
  sed -e 's/^/  /' "$NEW.err" >&2
  rm -f "$NEW" "$NEW.err" "$BAK"
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
  rm -f "$NEW" "$BAK"
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

cp "$NEW" "$FILE" || { cp "$BAK" "$FILE"; die "cannot write $REL"; }

# From here on the file is mutated, so every exit path restores. The trap covers
# the abnormal ones - an interrupt, a signal - where nothing below runs.
RESTORED=0
on_exit() { [ "$RESTORED" = 1 ] && return 0; cp "$BAK" "$FILE" 2>/dev/null || true; }
trap on_exit EXIT INT TERM

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
  rm -f "$NEW" "$BAK"
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
rm -f "$NEW"
exit 90
