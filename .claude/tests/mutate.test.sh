#!/usr/bin/env bash
# Tests for scripts/mutate.sh - the sanctioned diagnostic mutation.
#
# The harness requires mutations it did not provide a way to make. A test
# written or corrected while the implementation already exists passes on its
# first run and every run after, whether or not it asserts anything, and the
# only way to earn it is to break the production behaviour it claims to pin and
# watch that one assertion go red. rules.md demands that. rules.md also says
# never to route around the phase lock, and production source is frozen in RED,
# which is exactly when a corrected test needs earning.
#
# Every agent resolved that privately with `sed -i`, which the lock let through
# because it discarded any target containing `$`. Three source files were
# mutated that way in one corrective RED pass. And the one mutation done in a
# phase where source WAS writable lost its backup, because the shell it ran in
# had no $TMPDIR, so the restore depended on the substitution happening to be an
# exact inverse of a single-occurrence match. It was. That is the whole reason
# this script exists: the restore must be a fact, not a coincidence.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT

SRC="$FIX/src/main.ts"
ORIGINAL='export const clamp = (v) => Math.min(90, v)'

reset_src() { printf '%s\n' "$ORIGINAL" > "$SRC"; }

mutate() { ( cd "$FIX" && bash scripts/mutate.sh "$@" 2>&1 ); }

sha() { git -C "$FIX" hash-object "$1"; }

# ---------------------------------------------------------------------------
describe "the command sees the mutation"

reset_src
before="$(sha "$SRC")"
out="$(mutate src/main.ts 's/90/-90/' -- grep -c -- '-90' src/main.ts)"; rc=$?
assert_contains "the mutated file is what the command reads" "1" "$out"
assert_eq "and the command's exit code is passed through" "0" "$rc"
assert_eq "and the file is byte-identical afterwards" "$before" "$(sha "$SRC")"
assert_contains "and it says the restore was verified" "restored" "$out"
assert_contains "and prints the line it put back" "Math.min(90, v)" "$out"

# ---------------------------------------------------------------------------
describe "a failing command is the point, not an error"

# This is the shape the harness actually asks for: mutate the behaviour, watch
# the one assertion that pins it go red, revert. The red is the evidence, so a
# non-zero exit must not be treated as the script failing.
reset_src
before="$(sha "$SRC")"
out="$(mutate src/main.ts 's/90/-90/' -- sh -c 'exit 1')"; rc=$?
assert_eq "the command's failure is reported as its own" "1" "$rc"
assert_eq "and the file is still restored"               "$before" "$(sha "$SRC")"
assert_contains "and the exit code is stated plainly"    "exited 1" "$out"

# A command that cannot even start is not a reason to leave the tree mutated.
reset_src
before="$(sha "$SRC")"
mutate src/main.ts 's/90/-90/' -- no-such-command-here >/dev/null 2>&1
assert_eq "restored after a command that never ran" "$before" "$(sha "$SRC")"

# ---------------------------------------------------------------------------
describe "a mutation that mutates nothing proves nothing"

# An expression that matches nothing leaves the file identical, the command
# green, and the agent with a passing test it believes it has earned. That is
# worse than no probe at all, so it is refused before the command runs.
reset_src
before="$(sha "$SRC")"
rm -f "$FIX/ran-marker"
out="$(mutate src/main.ts 's/NOT_IN_THE_FILE/x/' -- touch ran-marker)"; rc=$?
assert_contains "it says the expression changed nothing" "changed nothing" "$out"
assert_eq "and exits 3"                                  "3" "$rc"
assert_eq "and the file is untouched"                    "$before" "$(sha "$SRC")"
if [ -e "$FIX/ran-marker" ]; then
  _bad "and the command never ran" "ran-marker exists"
else _ok "and the command never ran"; fi

# ---------------------------------------------------------------------------
describe "how much it changed is reported, because one line is the useful case"

reset_src
printf 'const a = 90\nconst b = 90\n' >> "$SRC"
out="$(mutate src/main.ts 's/90/-90/g' -- true)"
assert_contains "it counts the changed lines" "3 line(s)" "$out"
reset_src

# ---------------------------------------------------------------------------
describe "usage errors happen before anything is touched"

rm -f "$FIX/ran-marker"
out="$(mutate src/nope.ts 's/a/b/' -- touch ran-marker)"; rc=$?
assert_contains "a file that does not exist" "no such file" "$out"
assert_eq "exits 2"                          "2" "$rc"

out="$(mutate src/main.ts 's/90/-90/')"; rc=$?
assert_contains "no -- and no command" "-- <command>" "$out"
assert_eq "exits 2"                    "2" "$rc"

out="$(mutate src/main.ts 's/90/-90/' --)"; rc=$?
assert_contains "-- with nothing after it" "-- <command>" "$out"
assert_eq "exits 2"                        "2" "$rc"

out="$(mutate src/main.ts '' -- true)"; rc=$?
assert_contains "an empty expression" "expression" "$out"
assert_eq "exits 2"                   "2" "$rc"

if [ -e "$FIX/ran-marker" ]; then
  _bad "no command ran on any usage error" "ran-marker exists"
else _ok "no command ran on any usage error"; fi

# ---------------------------------------------------------------------------
describe "a restore that cannot be verified is loud, and keeps the backup"

# The one failure mode that must never be quiet. If the file cannot be put back
# byte-for-byte, an agent that reads "restored" and moves on has left a mutation
# in the tree with a green suite ahead of it.
reset_src
out="$(mutate src/main.ts 's/90/-90/' -- sh -c 'rm -f .claude/state/mutations/*.bak')"; rc=$?
assert_contains "it says the restore failed" "COULD NOT RESTORE" "$out"
assert_eq "and exits 90, whatever the command did" "90" "$rc"

# ---------------------------------------------------------------------------
describe "the scratch file never outlives the run"

# .claude/state/mutations/ has exactly one signal in it, and rules.md states it:
# a `.bak` left behind means a restore failed. That sentence ends "everything
# else it cleans up", which was not true. The mutated text is built in a `.new`
# beside the backup - sed cannot read and write one path - and each exit path
# removed it separately, so the two paths that write no log line removed nothing.
# Two `.new` files from different weeks sat in this repository's state directory
# with no log entry to explain either and no rule to read them by. Unlike the
# backup, a `.new` is not evidence of anything: its content is the backup put
# through the expression, and the log records both.
#
# So most of the cases below are one assertion - nothing named `.new` is left -
# and the point is that it holds on the paths that report nothing as much as on
# the ones that report success.

scratch() { ls "$FIX/.claude/state/mutations" 2>/dev/null | grep -c '\.new$'; }
backups() { ls "$FIX/.claude/state/mutations" 2>/dev/null | grep -c '\.bak$'; }

reset_src
mutate src/main.ts 's/90/-90/' -- true >/dev/null 2>&1
assert_eq "after a command that passed" "0" "$(scratch)"

mutate src/main.ts 's/90/-90/' -- sh -c 'exit 1' >/dev/null 2>&1
assert_eq "after a command that failed" "0" "$(scratch)"

mutate src/main.ts 's/90/-90/' -- no-such-command-here >/dev/null 2>&1
assert_eq "after a command that never ran" "0" "$(scratch)"

mutate src/main.ts 's/90/-90' -- true >/dev/null 2>&1
assert_eq "after sed rejected the expression" "0" "$(scratch)"

mutate src/main.ts 's/NOT_IN_THE_FILE/x/' -- true >/dev/null 2>&1
assert_eq "after an expression that changed nothing" "0" "$(scratch)"

# The one path that is MEANT to leave something, so that the cleanup above is
# not merely "delete everything". When the restore cannot be verified the backup
# is the only copy of the original and it must survive; the scratch file is
# still scratch. The command makes the target unwritable, so the restore that
# follows it genuinely fails.
reset_src
out="$(mutate src/main.ts 's/90/-90/' -- chmod 444 src/main.ts)"; rc=$?
chmod 644 "$SRC" 2>/dev/null
assert_eq "a restore that could not be verified exits 90" "90" "$rc"
assert_eq "and keeps its backup"                          "1" "$(backups)"
assert_eq "but not its scratch file"                      "0" "$(scratch)"
rm -f "$FIX"/.claude/state/mutations/*.bak

# The file cannot be written at all. This is the other path that writes no log
# line, and the shape that produced the older of the two orphans: the backup was
# taken, the scratch file was built, and then nothing could be copied over the
# original. Nothing was mutated, so there is nothing to go and look at - neither
# file should survive, and a `.bak` here would be a false alarm under a rule that
# reads a `.bak` as a failed restore.
reset_src
before="$(sha "$SRC")"
chmod 444 "$SRC" 2>/dev/null
mutate src/main.ts 's/90/-90/' -- true >/dev/null 2>&1
chmod 644 "$SRC" 2>/dev/null
assert_eq "an unwritable target leaves no scratch file" "0" "$(scratch)"
assert_eq "and no backup, because nothing was mutated"  "0" "$(backups)"
assert_eq "and the file is untouched"                   "$before" "$(sha "$SRC")"
reset_src

# ---------------------------------------------------------------------------
describe "it refuses to mutate the script that is running"

# Found by using this script on this repository. bash reads a script
# incrementally rather than loading it whole, so rewriting mutate.sh while
# mutate.sh is executing changes what the interpreter reads next: the run dies
# somewhere in the middle and the restore - the last thing it does - never
# happens. The mutation is then left in the tree with nothing to say so, which
# is the exact failure this script exists to make impossible.
before="$(sha "$FIX/scripts/mutate.sh")"
out="$(mutate scripts/mutate.sh 's/ROOT=/R00T=/' -- true)"; rc=$?
assert_contains "it says why" "cannot mutate itself" "$out"
assert_eq "and exits 2"                   "2" "$rc"
assert_eq "and the script is untouched"   "$before" "$(sha "$FIX/scripts/mutate.sh")"

# The same by absolute path, which is how it would arrive from a script.
out="$(mutate "$FIX/scripts/mutate.sh" 's/ROOT=/R00T=/' -- true)"; rc=$?
assert_eq "an absolute path is the same file" "2" "$rc"
assert_eq "and still untouched"               "$before" "$(sha "$FIX/scripts/mutate.sh")"

# ---------------------------------------------------------------------------
describe "the log is what the story quotes"

reset_src
LOG="$FIX/.claude/state/mutations/log"
rm -f "$LOG"
mutate src/main.ts 's/90/-90/' -- sh -c 'exit 1' >/dev/null 2>&1
log="$(cat "$LOG" 2>/dev/null)"
assert_contains "the file"            "src/main.ts" "$log"
assert_contains "the expression"      "s/90/-90/"   "$log"
assert_contains "the command"         "exit 1"      "$log"
assert_contains "the command's code"  "exited 1"    "$log"
assert_contains "and the restore"     "restored"    "$log"

# ---------------------------------------------------------------------------
describe "it works with the phase lock on, in every phase"

# The point of the script. In RED source is frozen and this is still allowed,
# because the file it names is put back before the command that follows it.
for ph in RED GREEN GATES REVIEW; do
  set_phase "$FIX" "$ph"
  reset_src
  before="$(sha "$SRC")"
  mutate src/main.ts 's/90/-90/' -- true >/dev/null 2>&1
  assert_eq "restored in $ph" "$before" "$(sha "$SRC")"
done
set_phase "$FIX" ""

summary "mutate"
