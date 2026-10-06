#!/usr/bin/env bash
# Apply a diagnostic mutation to one file, run a command against it, and put the
# file back — verifiably.
#
#   bash scripts/mutate.sh <FILE> '<SED-EXPRESSION>' -- <COMMAND> [ARGS...]
#
#   bash scripts/mutate.sh src/camera.ts 's/Math.min(90/Math.min(900/' \
#     -- pnpm exec vitest run tests/camera.test.ts
#
#   bash scripts/mutate.sh --check
#
# ...asks the other question: is anything of a PREVIOUS run still in the tree?
# Exit 0 and one line when not; exit 1 and a report per stranded mutation when
# so. scripts/gates.sh runs it before it runs any gate.
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
#   * And a mutation in flight SAYS SO, in an `.active` file written before the
#     file is touched and removed only once it is verifiably back. That answers
#     the one hole the two properties above cannot close: a kill runs no code,
#     so the file stays mutated and nothing says so, and the next thing to read
#     the tree judges code nobody wrote. `--check` reads the sentinels; gates.sh
#     runs it before any gate. The command itself is told its own sentinel in
#     HARNESS_MUTATION, so a gate probe run under a mutation is not refused by
#     the very mutation it exists to observe.
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
  printf '\n  bash scripts/mutate.sh --check   is anything of a previous run still in the tree?\n' >&2
}
die() { printf 'mutate: %s\n' "$1" >&2; usage; exit 2; }

# --- --check: is anything of a previous run still in the tree? --------------
#
# The one failure this script cannot clean up after is a kill - SIGKILL, a
# closed terminal, a tool limit that does not wait. Nothing below runs, so the
# file is left mutated and the only trace is the backup and the scratch file in
# $MUTDIR. So a mutation announces itself while it is in flight, in an `.active`
# sentinel written immediately before the file is mutated and removed only once
# the file is verifiably back; it survives exactly a kill and a restore that
# could not be verified, and this is what reads it.
#
# Detection, not a lock: this reports and exits, holds nothing and waits for
# nothing, because a lock the harness can deadlock against its own subagent is
# worse than the race. A sentinel whose process is alive is reported as in
# flight rather than as wreckage, because the answer differs - "wait" against
# "put the file back". `kill -0` can say RUNNING for a recycled pid but never
# GONE for a live one, so the error it can make is the cautious one.
#
# One sentinel is not counted: the caller's own. A gate probe runs gates.sh
# UNDER a mutation, and gates.sh asks this first; refusing that probe would make
# every gate probe impossible. The command is told its sentinel in
# HARNESS_MUTATION, and it is honoured only for a sentinel in THIS tree's
# mutations/ (it is compared with the globbed path) whose process is alive, so a
# stale variable, or one inherited by a fixture tree, gains nothing.
#
# The remedy compares against the sentinel's `path`, the resolved absolute
# target, because a target may be given as an absolute path and `$ROOT/<file>`
# is then no file at all. A sentinel with no `path` falls back to that.
if [ "${1:-}" = "--check" ]; then
  TAB="$(printf '\t')"
  found=0; own=""
  for a in "$MUTDIR"/*.active; do
    [ -f "$a" ] || continue
    a_pid=""; a_file=""; a_path=""; a_backup=""; a_expr=""; a_command=""; a_started=""
    while IFS="$TAB" read -r k v; do
      case "$k" in
        pid)     a_pid="$v" ;;
        file)    a_file="$v" ;;
        path)    a_path="$v" ;;
        backup)  a_backup="$v" ;;
        expr)    a_expr="$v" ;;
        command) a_command="$v" ;;
        started) a_started="$v" ;;
      esac
    done < "$a"
    a_alive=0
    [ -n "$a_pid" ] && kill -0 "$a_pid" 2>/dev/null && a_alive=1
    if [ -n "${HARNESS_MUTATION:-}" ] && [ "$a" = "$HARNESS_MUTATION" ] && [ "$a_alive" = 1 ]; then
      own="${a_file:-<unrecorded>}"
      continue
    fi
    [ -n "$a_path" ] || a_path="$ROOT/$a_file"
    if [ "$found" = 0 ]; then
      printf 'mutate: a mutation is unaccounted for. The tree may not be the code you think.\n\n' >&2
    fi
    found=$((found+1))
    if [ "$a_alive" = 1 ]; then
      a_state="$a_pid (RUNNING - a mutation is in flight right now; wait for it)"
    else
      a_state="$a_pid (GONE - the run was killed, so the file is probably still mutated)"
    fi
    printf '  %s\n' "${a_file:-<unrecorded>}" >&2
    printf '    mutated by:  %s\n' "${a_expr:-<unrecorded>}" >&2
    printf '    command:     %s\n' "${a_command:-<unrecorded>}" >&2
    printf '    started:     %s\n' "${a_started:-<unrecorded>}" >&2
    printf '    process:     %s\n' "$a_state" >&2
    printf '    original:    %s\n' "${a_backup:-<gone - check git diff>}" >&2
    if [ -n "$a_backup" ] && [ -f "$a_backup" ]; then
      if cmp -s "$a_backup" "$a_path" 2>/dev/null; then
        printf '    the file currently MATCHES the original; clearing this is safe:\n' >&2
        printf '      rm -f %s %s\n' "$a_backup" "$a" >&2
      else
        printf '    the file DIFFERS from the original. Put it back:\n' >&2
        printf '      cp %s %s && cmp %s %s && rm -f %s %s\n' \
          "$a_backup" "$a_path" "$a_backup" "$a_path" "$a_backup" "$a" >&2
      fi
    else
      printf '    no backup survives, so this cannot be undone from here: check\n' >&2
      printf '    git status and git diff before running anything that judges this tree.\n' >&2
    fi
    printf '\n' >&2
  done
  if [ "$found" = 0 ]; then
    if [ -n "$own" ]; then
      printf "mutate: no stranded mutation; the one in flight is this command's own (%s).\n" "$own"
    else
      printf 'mutate: no stranded mutation; nothing of a previous run is in the tree.\n'
    fi
    exit 0
  fi
  printf '%d unaccounted-for mutation(s). Nothing that judges this tree should run\n' "$found" >&2
  printf 'until each is resolved above.\n' >&2
  exit 1
fi

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
DIFF="$MUTDIR/$SAFE.$STAMP.$$.diff"
ACTIVE="$MUTDIR/$SAFE.$STAMP.$$.active"

# $NEW is scratch and nothing else. sed cannot read and write one path, so the
# mutated text is built here and copied over the original. It is not evidence:
# its content is $BAK put through $EXPR, and the log records both. $DIFF is
# scratch too: the diff of the two, read once to count, preview and list. $BAK is
# the only copy of the original, which is why the directory has exactly one
# signal in it and rules.md states it - a `.bak` left behind means a restore
# failed.
#
# That sentence ends "everything else it cleans up", and it was not true. Each
# exit path removed the scratch file separately, so the paths that write no log
# line - `cannot write` below, and being killed outright - removed nothing. Two
# `.new` files from different weeks sat in a consuming project's
# .claude/state/mutations/ with no log entry to explain either. One trap,
# installed before the file exists, is what makes the sentence true: the scratch
# files go on every path this script can still run code on, and the backup
# survives exactly when the restore could not be verified. A `.new` that
# outlives a run now means the run was killed outright, which is the one case
# nothing here can catch - and it arrives with its `.bak`, so the source file is
# still checkable against the original.
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
# The sentinel goes only when the file is verifiably the original again. That is
# what makes its presence mean something: it survives a restore that could not
# be verified and it survives a kill, the two states in which the tree is not
# what it looks like.
clear_active() { [ -f "$BAK" ] && cmp -s "$BAK" "$FILE" 2>/dev/null && rm -f "$ACTIVE" 2>/dev/null; return 0; }
on_exit() { put_back; clear_active; rm -f "$NEW" "$NEW.err" "$DIFF" 2>/dev/null; return 0; }

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
  clear_active
  [ -f "$BAK" ] && cmp -s "$BAK" "$FILE" 2>/dev/null && rm -f "$BAK" 2>/dev/null
  rm -f "$NEW" "$NEW.err" "$DIFF" 2>/dev/null
  exit 130
}

cp "$FILE" "$BAK" || die "cannot back up $REL to $BAK"

# Armed only once the backup is a complete copy. Earlier than this, a `cp` that
# failed halfway would leave put_back holding a truncated original and willing
# to write it over the real one; and there is no scratch file to clean up yet.
# PIPE is armed here too, before the first printf to stdout, not after the
# mutation: every one of them can meet a reader that has already gone.
trap on_exit EXIT
trap on_signal INT TERM

# PIPE IS TRAPPED, AND ITS HANDLER DOES NOTHING. Both halves matter.
#
# Why trapped (b38f5b3). This script prints a header, a preview, a restore
# confirmation and a listing, then appends to the log - and it is routinely read
# through `| head`, because the command under it is chatty. `head` leaves after
# its count, the next printf takes SIGPIPE, and with PIPE untrapped bash kills
# the script THERE: after the restore, before the backup is removed, before the
# log append. What that left was the worst possible artefact: the file fine, but
# a `.bak` with no log line beside it - and rules.md tells the reader that a
# `.bak` under `mutations/` means a restore FAILED. Three of them sat in this
# repository when it was found, all benign, all from `| head`. A trapped signal
# makes bash resume after the failed write instead, and the trap is reset to the
# default in children at exec, so the command under test still sees an ordinary
# SIGPIPE.
#
# Why it restores nothing (HARNESS-029). b38f5b3 put PIPE in the same list as
# EXIT, INT and TERM, so its handler RESTORED THE FILE, and the comment here said
# nothing else was needed. Something else was. A reader that left before the
# command started made the first printf after the mutation take SIGPIPE; the
# handler put the original back, execution resumed, and the command then ran
# against the ORIGINAL - while the log recorded `exited 0  restored (verified)`.
# The probe was void and said it ran (reproduced 3 of 3 on Git Bash). Restoring
# is the EXIT trap's job. Folding PIPE into on_signal instead would turn an early
# reader into `exit 130` before the command runs, so a piped probe would never
# run at all.
#
# One more rule rides on this, and it is containment, not a diagnosis: NOTHING
# BELOW WRITES TO THIS SCRIPT'S OWN STDOUT THROUGH A PIPELINE. Every pipeline's
# output is captured first and printed with one printf. With `| head -1` as the
# reader the run hung every time on Git Bash, and both places it was seen to
# hang were such pipelines (the preview's `awk | head -20`, the listing's
# `printf | while read`). Why they hung is not known.
trap ':' PIPE

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

# Which lines changed, and how many. One line is the useful case - a probe aimed
# at a single behaviour, whose predicted catch is a single assertion - so the
# count is printed rather than left to be counted by eye.
#
# Counted from a real diff, not by line number. Comparing line N with line N
# made one insertion "change" every line after it: 661d once reported 613 lines,
# and the listing then started one awk for each. `git diff --no-index` rather
# than `diff`, because git is already a hard dependency and diffutils is not;
# every config that could change its output is pinned off - core.autocrlf in
# particular, which otherwise prints CRLF warnings on Windows. It exits 1 when
# the files differ, which is the expected case, so its status is not used.
git -c core.autocrlf=false -c core.quotepath=off -c diff.noprefix=false \
  diff --no-index --no-color --no-ext-diff --no-textconv -U0 -- "$BAK" "$NEW" > "$DIFF" 2>/dev/null

# One pass over the diff. The count is, per hunk `@@ -a[,b] +c[,d] @@`, the
# larger of b and d (a missing count is 1), summed over hunks: every line
# removed, added or replaced counts once, and nothing between hunks counts.
# Printed: line 1 the count, line 2 `binary` or `text`, line 3 the old-side
# numbers of the removed lines (for the restore listing), then the preview -
# removed lines numbered from a, added lines from c, at most 20. mawk-safe:
# match/substr/split and plain comparisons only (CI's awk is mawk).
SUMMARY="$(awk '
  function count(s,   p, f) { p = split(s, f, ","); return (p > 1) ? f[2] + 0 : 1 }
  function first(s,   f) { split(s, f, ","); return f[1] + 0 }
  /^Binary files / && !hunk { binary = 1; next }
  /^@@ / {
    hunk = 1
    split($0, h, " ")
    o = substr(h[2], 2); n = substr(h[3], 2)
    b = count(o); d = count(n)
    old = first(o); new = first(n)
    total += (b > d) ? b : d
    next
  }
  !hunk { next }
  /^\\/ { next }
  /^-/ {
    lines = lines (lines == "" ? "" : " ") old
    if (shown < 20) preview[++shown] = "  " old " - " substr($0, 2)
    old++; next
  }
  /^\+/ {
    if (shown < 20) preview[++shown] = "  " new " + " substr($0, 2)
    new++; next
  }
  END {
    print total + 0
    print (binary ? "binary" : "text")
    print lines
    for (i = 1; i <= shown; i++) print preview[i]
  }' "$DIFF" 2>/dev/null)"
mapfile -t SUMMARY_LINES <<< "$SUMMARY"
CHANGED="${SUMMARY_LINES[0]:-0}"
KIND=""; [ "${SUMMARY_LINES[1]:-}" = binary ] && KIND=" (binary)"
LINES="${SUMMARY_LINES[2]:-}"
PREVIEW=""
[ "${#SUMMARY_LINES[@]}" -gt 3 ] && printf -v PREVIEW '%s\n' "${SUMMARY_LINES[@]:3}"

# The 2>/dev/null on this and the two other stdout printfs below: once a reader
# has gone, the PIPE trap above lets bash carry on, and bash then reports the
# failed write on stderr - a "write error: Broken pipe" per printf, about a
# reader that left on purpose. Only these printfs' own complaints are dropped.
printf '=== mutate: %s (%s line(s) changed%s by %s) ===\n%s' "$REL" "$CHANGED" "$KIND" "$EXPR" "$PREVIEW" 2>/dev/null

# From here the file is mutated, and the traps installed above restore it on the
# abnormal exits - an interrupt, a signal - where nothing below runs.
#
# The sentinel is written BEFORE the file is mutated, never after: one that
# appears a moment later leaves a window in which the tree is wrong and nothing
# says so, and that window is the whole failure it guards against. Tab-separated
# so an expression or a command containing anything reads back whole; a newline
# in the expression is written as the two characters \n, so the record stays one
# line per key. And it is not optional: a sentinel that silently failed to exist
# defeats the mechanism, so a run that cannot write one does not mutate.
# The replacement is held in quoted variables: the literal `${EXPR//$'\n'/\\n}`
# writes `n` without its backslash under bash 5.3, joining the two commands.
NL=$'\n'; BSN='\n'
{ printf 'pid\t%s\n'     "$$"
  printf 'file\t%s\n'    "$REL"
  printf 'path\t%s\n'    "$FILE"
  printf 'backup\t%s\n'  "$BAK"
  printf 'expr\t%s\n'    "${EXPR//"$NL"/"$BSN"}"
  printf 'command\t%s\n' "${CMD[*]}"
  printf 'started\t%s\n' "$STAMP"
} > "$ACTIVE" 2>/dev/null || { rm -f "$ACTIVE" "$BAK" 2>/dev/null; die "cannot record the mutation in flight at $ACTIVE; refusing to mutate without it"; }

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
    rm -f "$ACTIVE" "$BAK"
    die "cannot write $REL; it is unchanged, verified against the backup"
  fi
  printf '\n=== mutate: COULD NOT RESTORE %s ===\n' "$REL" >&2
  printf '%s could not be written, and does not match the backup afterwards.\n' "$REL" >&2
  printf 'The original is still at:\n  %s\nPut it back by hand and check nothing else moved.\n' "$BAK" >&2
  printf '%s\t%s\t%s\t%s line(s)\tcommand: not run\tCOULD NOT RESTORE\n' \
    "$STAMP" "$REL" "$EXPR" "$CHANGED" >> "$LOG" 2>/dev/null || true
  exit 90
fi

printf '\n=== mutate: running %s ===\n' "${CMD[*]}" 2>/dev/null
# HARNESS_MUTATION tells the command which sentinel is its own, so that a gate
# probe's gates.sh, and --check, do not refuse the mutation they run under.
( cd "$ROOT" && HARNESS_MUTATION="$ACTIVE" "${CMD[@]}" )
rc=$?

# --- restore, and check it ---------------------------------------------------
cp "$BAK" "$FILE" 2>/dev/null
RESTORED=1
if cmp -s "$BAK" "$FILE" 2>/dev/null; then
  verdict="restored (verified byte-for-byte against $BAK)"
  # What the restore put back: the first ten removed lines, read from the
  # restored file in ONE pass, then how many more. A pure insertion removed
  # nothing, so it lists nothing. The awk runs whatever the count, so what this
  # costs does not depend on how much changed.
  LISTING="$(awk -v want="$LINES" '
    BEGIN {
      n = split(want, w, " ")
      for (i = 1; i <= n && i <= 10; i++) { pick[w[i] + 0] = 1; last = w[i] + 0 }
      if (n == 0) exit
    }
    (FNR in pick) { printf "  %d: %s\n", FNR, $0 }
    FNR >= last { exit }
    END { if (n > 10) printf "  ... and %d more\n", n - 10 }' "$FILE" 2>/dev/null)"
  printf '\n=== mutate: command exited %d; %s ===\n%s%s' "$rc" "$verdict" "$LISTING" "${LISTING:+$'\n'}" 2>/dev/null
  printf '%s\t%s\t%s\t%s line(s)\tcommand: %s\texited %d\t%s\n' \
    "$STAMP" "$REL" "$EXPR" "$CHANGED" "${CMD[*]}" "$rc" "restored (verified)" >> "$LOG" 2>/dev/null || true
  rm -f "$ACTIVE" "$BAK"
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
