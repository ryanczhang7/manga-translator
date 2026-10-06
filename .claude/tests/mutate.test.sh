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
# W holds what HARNESS-029's blocks record outside the fixture: what a command
# saw, and bash -x traces. Outside src/ so that nothing it writes is a source
# write, and removed with the fixture.
W="$(mktemp -d 2>/dev/null || mktemp -d -t h029.XXXXXX)"
trap 'chmod 644 "$FIX/src/main.ts" 2>/dev/null; rm -rf "$FIX" "$W"' EXIT

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


# ---------------------------------------------------------------------------
describe "a reader that leaves early does not strand the backup"

# FOUND IN USE, not by review. `bash scripts/mutate.sh ... | head -12` is how
# this script is actually invoked when the command under it is chatty - it is
# how the orchestrator invoked it a dozen times during releases 37-45. `head`
# closes the pipe after its count, the script takes SIGPIPE while printing the
# restore confirmation, and dies AFTER restoring but BEFORE `rm -f $NEW $BAK`
# and before the log append.
#
# The file is fine. What is left behind is a `.bak` and no log line - and
# `rules.md` tells the reader, in as many words, that a `.bak` left under
# `mutations/` means a restore FAILED and the script exited 90 saying so. So
# the one artefact that is supposed to mean "something went wrong" is produced
# routinely by something that went right, and the log that would contradict it
# is missing for the same reason.
#
# Three stale backups sat in this repository's own mutations directory when
# this was found, all benign, all from piping into `head`.
#
# The trap covered EXIT INT TERM and not PIPE, which is why none of the
# cleanup ran. This is the SIGPIPE class of check-sigpipe.sh, in the tool the
# non-negotiables name as the sanctioned way to probe.
reset_src
rm -f "$FIX"/.claude/state/mutations/*.bak "$FIX"/.claude/state/mutations/*.new 2>/dev/null
before_baks="$(ls "$FIX"/.claude/state/mutations/*.bak 2>/dev/null | wc -l | tr -d ' ')"
log_before="$(awk 'END { print NR + 0 }' "$FIX/.claude/state/mutations/log" 2>/dev/null || printf 0)"

# The pipeline is the point: a reader that stops after two lines while mutate
# is still printing. `seq` is chatty enough to guarantee that and STOPS ON ITS
# OWN - the first draft used `yes | head`, a writer that only ends when
# something kills it, which hung this suite for hours during a probe. A test
# for a SIGPIPE defect is the last place to put an unbounded writer.
# BOUNDED WITH `timeout`, because the thing this pins can HANG rather than
# misbehave: without the cleanup in on_exit, each SIGPIPE re-enters the trap,
# finds the backup still there, and the cycle never ends. Measured - the probe
# for that line times out rather than failing. A suite that hangs is a worse
# signal than one that fails, so the bound turns it into a failure.
# THE WHOLE PIPELINE IS BOUNDED, not just mutate.sh. A first attempt put
# `timeout` on the script alone and left the subshell and `head` unbounded -
# it passed standalone and hung the FULL selftest, which is the difference
# between a bound on the part you suspect and a bound on the thing you run.
timeout 60 bash -c "cd \"$FIX\" && bash scripts/mutate.sh src/main.ts 's/90/-90/' -- sh -c 'seq 1 200' 2>&1 | head -2" >/dev/null 2>&1 || true

after_baks="$(ls "$FIX"/.claude/state/mutations/*.bak 2>/dev/null | wc -l | tr -d ' ')"
log_after="$(awk 'END { print NR + 0 }' "$FIX/.claude/state/mutations/log" 2>/dev/null || printf 0)"

assert_eq "no backup is stranded when the reader leaves early" \
  "$before_baks" "$after_baks"

# The other half, and the one that makes the first meaningful: the file really
# was restored. A cleanup that ran because the restore never happened would
# satisfy the assertion above and be much worse.
assert_eq "and the source is back to what it was" \
  "$ORIGINAL" "$(cat "$SRC")"

# And the run is still recorded. Losing the log entry is how a stranded backup
# becomes unexplainable: no line saying the command ran, no line saying it
# failed.
# And the run is still recorded. Losing the log entry is how a stranded backup
# becomes unexplainable: no line saying the command ran, no line saying it
# failed. Counted as a DELTA, because the log accumulates across this suite and
# an absolute count would pass or fail on what ran before it.
assert_eq "and the run still reaches the log" "1" \
  "$((log_after - log_before))"

# The control that stops this being satisfied by never writing a backup at all:
# an ordinary run, no pipe, still cleans up and still restores.
reset_src
out="$(mutate src/main.ts 's/90/-90/' -- true)"
assert_eq "an ordinary run leaves no backup either" \
  "0" "$(ls "$FIX"/.claude/state/mutations/*.bak 2>/dev/null | wc -l | tr -d ' ')"
assert_eq "and restores the source" "$ORIGINAL" "$(cat "$SRC")"

# THE CONTROL THAT MATTERS MOST is not written here: it is the existing
# "COULD NOT RESTORE" case above, which deletes the backup mid-command so the
# restore genuinely cannot happen. Fixing this false alarm must not silence
# that real one, and that test asserting exit 90 is what says so. Clobbering
# the file does NOT make a restore fail - mutate.sh copies the backup over it
# regardless - which is a thing this suite already knew and the first draft of
# this block did not.
reset_src

# ===========================================================================
# HARNESS-029: mutate.sh counts what changed, cleans up on every path, and
# survives an early reader. EVERY BLOCK BELOW IS BOUNDED - a pipeline under
# `timeout`, a background run under a polling limit that kills it - because the
# AC-2 block reproduces a HANG on Git Bash, and the warning above about
# unbounded writers applies twice over to a suite about a hang.

MUTDIR="$FIX/.claude/state/mutations"
TAB="$(printf '\t')"

# strays_of <ext>   How many *.<ext> files sit in the mutations directory.
strays_of() { ls "$MUTDIR"/*."$1" 2>/dev/null | wc -l | tr -d ' '; }
strays() { echo $(( $(strays_of bak) + $(strays_of new) )); }
# HARNESS-030: `.active` too, and with -r, because a COULD NOT RESTORE now leaves
# its sentinel standing and the AC-2 block below plants DIRECTORIES under that
# name. A sentinel left by one block would otherwise be read by the next.
clear_strays() { rm -f "$MUTDIR"/*.bak "$MUTDIR"/*.new "$MUTDIR"/*.diff 2>/dev/null; rm -rf "$MUTDIR"/*.active 2>/dev/null; }
log_count() { awk 'END { print NR + 0 }' "$MUTDIR/log" 2>/dev/null || printf 0; }
last_log() { tail -n 1 "$MUTDIR/log" 2>/dev/null; }

# whole_lines <line> <text>   How many lines of <text> are exactly <line>.
# Anchored on purpose: a floating `1 line(s)` is satisfied by `31 line(s)`.
whole_lines() { grep -cxF -- "$1" <<< "$2"; }
# preview_of <output>   The numbered `  N - ` / `  N + ` lines printed before
# the command runs.
preview_of() { awk '/^=== mutate: running/ { exit } /^  [0-9]+ [-+] / { print }' <<< "$1"; }
# listing_of <output>   Every indented line after the restore verdict - the
# restore listing, and `  ... and K more` when there is one. The commands these
# blocks run print nothing, so nothing else can be indented there.
listing_of() { awk 'f && /^  / { print } /restored \(verified/ { f = 1 }' <<< "$1"; }

# ---------------------------------------------------------------------------
describe "HARNESS-029 AC-1: a target it cannot write is left as it was, with nothing stranded"

# THE METHOD, PROVED BEFORE IT IS RELIED ON: chmod 444 after the fixture is
# written. On Git Bash that sets the Windows read-only attribute and `cp` onto
# the file fails with "Permission denied" (measured 2026-10-04); on a Linux
# runner it fails for any non-root user. A root runner would ignore it, so the
# precondition is an assertion, not an assumption: if `cp` can still write the
# file, this block says so rather than passing for the wrong reason. The
# precondition copies the file's own bytes back onto it, so it changes nothing
# even when it succeeds.
reset_src
clear_strays
before="$(sha "$SRC")"
rm -f "$FIX/ran-marker"
chmod 444 "$SRC"
cp "$SRC" "$W/probe-copy"
if cp "$W/probe-copy" "$SRC" 2>/dev/null; then pre=writable; else pre=refused; fi
assert_eq "AC-1 precondition: after chmod 444, cp onto the target fails on this host" \
  "refused" "$pre"
out="$(mutate src/main.ts 's/90/-90/' -- touch ran-marker)"; rc=$?
chmod 644 "$SRC"
assert_eq "AC-1: a target it cannot write exits 2" "2" "$rc"
assert_eq "AC-1: and says, as a whole line, that the file is unchanged and verified against the backup" 1 \
  "$(whole_lines 'mutate: cannot write src/main.ts; it is unchanged, verified against the backup' "$out")"
assert_eq "AC-1: the file is byte-identical to before" "$before" "$(sha "$SRC")"
assert_eq "AC-1: no .bak is left behind by a run that wrote nothing" 0 "$(strays_of bak)"
assert_eq "AC-1: no .new is left behind by a run that wrote nothing" 0 "$(strays_of new)"
if [ -e "$FIX/ran-marker" ]; then
  _bad "AC-1: the command is not run against a file that was never mutated" "ran-marker exists"
else _ok "AC-1: the command is not run against a file that was never mutated"; fi
rm -f "$FIX/ran-marker"
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-029 AC-2: a reader that leaves after one line neither voids the probe nor hangs"

# Reproduced on Git Bash at 3fcd706 (the story's ## Context). The PIPE trap ran
# the restore when the first printf after the mutation hit the closed pipe, so
# the command ran against the ORIGINAL while the log said "exited 0  restored
# (verified)" - and then the run hung in a pipeline writing to the dead reader
# until `timeout` killed it. The two are asserted separately: what the command
# SAW (recorded outside src/, under $W), and timeout's status, where 124 means
# "timeout killed it" and anything else means the pipeline finished.
# THE WHOLE PIPELINE IS UNDER `timeout`, as in the block above and for the same
# reason: a bound on mutate.sh alone left `head` and the subshell unbounded.
reset_src
clear_strays
SEEN="$W/seen.txt"
rm -f "$SEEN"
log_before="$(log_count)"
timeout 60 bash -c "cd \"$FIX\" && bash scripts/mutate.sh src/main.ts 's/90/-90/' -- sh -c 'cat src/main.ts > \"$SEEN\"' 2>&1 | head -1" >/dev/null 2>&1
trc=$?
log_after="$(log_count)"
assert_eq "AC-2: the command saw the MUTATED file, not the original" \
  'export const clamp = (v) => Math.min(-90, v)' "$(cat "$SEEN" 2>/dev/null)"
if [ "$trc" = 124 ]; then
  _bad "AC-2: the pipeline finishes before the 60s timeout" "timeout killed it (status 124): mutate.sh hung after its reader left"
else _ok "AC-2: the pipeline finishes before the 60s timeout"; fi
assert_eq "AC-2: the file is restored" "$ORIGINAL" "$(cat "$SRC")"
assert_eq "AC-2: no .bak or .new is left" 0 "$(strays)"
assert_eq "AC-2: exactly one log line is added" 1 "$((log_after - log_before))"
assert_contains "AC-2: and it records one changed line, exit 0 and a verified restore" \
  "${TAB}src/main.ts${TAB}s/90/-90/${TAB}1 line(s)${TAB}command: sh -c cat src/main.ts > \"$SEEN\"${TAB}exited 0${TAB}restored (verified)" \
  "$(last_log)"
rm -f "$SEEN"

# ---------------------------------------------------------------------------
describe "HARNESS-029 AC-3: TERM while the command runs restores, logs, and leaves nothing"

# bash defers a trapped TERM until its foreground child exits, so the command
# is a short `sleep 3`, not a long one. The TERM goes to mutate.sh's OWN pid,
# read from its backup's name (<safe>.<stamp>.<pid>.bak): on Git Bash the `$!`
# of a backgrounded command is not always the bash running it - measured, a
# backgrounded `bash -c ... > file` was a wrapper whose CHILD was the bash, and
# a TERM to the wrapper reached nothing that had a trap.
# Bounded twice: 20s for the mutation to land, 30s for the run to end once
# signalled. Past either, the run is KILLed and reported, never waited on.
reset_src
clear_strays
log_before="$(log_count)"
( cd "$FIX" && exec bash scripts/mutate.sh src/main.ts 's/90/-90/' -- sh -c 'sleep 3' ) > "$W/term.out" 2>&1 &
wrapper=$!
i=0
while [ "$i" -lt 200 ] && ! grep -qF -- '-90' "$SRC" 2>/dev/null; do sleep 0.1; i=$((i + 1)); done
mpid=""
for b in "$MUTDIR"/*.bak; do
  [ -e "$b" ] || continue
  mpid="${b%.bak}"; mpid="${mpid##*.}"
done
if [ "$i" -lt 200 ] && [ -n "$mpid" ]; then
  _ok "AC-3 precondition: the file was mutated, and mutate.sh's pid known, before TERM"
  kill -TERM "$mpid" 2>/dev/null
else
  _bad "AC-3 precondition: the file was mutated, and mutate.sh's pid known, before TERM" \
    "mutated within 20s: $([ "$i" -lt 200 ] && printf yes || printf no); pid: ${mpid:-unknown}"
  kill -TERM "$wrapper" 2>/dev/null
fi
target="${mpid:-$wrapper}"
j=0
while [ "$j" -lt 300 ] && kill -0 "$target" 2>/dev/null; do sleep 0.1; j=$((j + 1)); done
if [ "$j" -ge 300 ]; then
  kill -KILL "$target" "$wrapper" 2>/dev/null
  _bad "AC-3: the run ends after TERM" "still running 30s after TERM; killed. Output:
$(cat "$W/term.out")"
else _ok "AC-3: the run ends after TERM"; fi
wait "$wrapper" 2>/dev/null
log_after="$(log_count)"
assert_eq "AC-3: the file is restored" "$ORIGINAL" "$(cat "$SRC")"
assert_eq "AC-3: no .new is left" 0 "$(strays_of new)"
assert_eq "AC-3: no .bak is left, because the restore was verified" 0 "$(strays_of bak)"
assert_eq "AC-3: the run writes exactly one log line" 1 "$((log_after - log_before))"
assert_contains "AC-3: and that line records a verified restore" \
  "${TAB}restored (verified)" "$(last_log)"
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-029 AC-3 control: a restore that really fails still exits 90 and keeps its backup"

# The cleanup must not silence the one real alarm. The existing COULD NOT
# RESTORE case above deletes the backup itself, so it cannot say whether a
# backup that IS there survives the new cleanup. This one makes the restore
# fail with the backup intact: the command makes the target read-only - AC-1's
# method, whose precondition is asserted above - so `cp` from the backup
# cannot put it back.
reset_src
clear_strays
out="$(mutate src/main.ts 's/90/-90/' -- chmod 444 src/main.ts)"; rc=$?
chmod 644 "$SRC"
assert_eq "control: a restore that cannot happen exits 90" "90" "$rc"
assert_contains "control: and says COULD NOT RESTORE" "COULD NOT RESTORE src/main.ts" "$out"
assert_eq "control: and keeps exactly one .bak" 1 "$(strays_of bak)"
kept=""
for b in "$MUTDIR"/*.bak; do [ -e "$b" ] && kept="$(cat "$b")"; done
assert_eq "control: and that .bak holds the original" "$ORIGINAL" "$kept"
reset_src
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-029 AC-4: the count is the lines that changed, not the lines that moved"

# Count rule (the story's AC-4): per hunk, the larger of lines removed and
# lines added, summed over hunks. Each case pins the whole header line, the
# whole preview, and the count in the log line.
FORTY="$FIX/src/forty.txt"
count_case() { # <expr> <count> <preview, newline-joined>
  local expr="$1" n="$2" pv="$3" out
  seq 1 40 > "$FORTY"
  out="$(mutate src/forty.txt "$expr" -- true)"
  assert_eq "AC-4: $expr reports $n line(s) changed, as a whole header line" 1 \
    "$(whole_lines "=== mutate: src/forty.txt ($n line(s) changed by $expr) ===" "$out")"
  assert_eq "AC-4: $expr previews only removed (old number) and added (new number) lines" \
    "$pv" "$(preview_of "$out")"
  assert_contains "AC-4: $expr logs the same count" \
    "${TAB}src/forty.txt${TAB}${expr}${TAB}${n} line(s)${TAB}" "$(last_log)"
}
# One insertion is one line, not every line after it (reported 39 before).
count_case '2s/$/\ninserted/' 1 '  3 + inserted'
# One deletion is one line, not every line after it (reported 35 before).
count_case '5d' 1 '  5 - 5'
# Deleting the last line is one line, not none (reported 0 before).
count_case '$d' 1 '  40 - 40'
# A one-line substitution, which was already right.
count_case 's/^1$/one/' 1 '  1 - 1
  1 + one'
# CONTROL: three separate hunks sum to 3, and the 9 unchanged lines between
# them never count. "Count 1 always" fails here.
count_case 's/^\(10\|20\|30\)$/&x/' 3 '  10 - 10
  10 + 10x
  20 - 20
  20 + 20x
  30 - 30
  30 + 30x'
# CONTROL: two lines joined into one is max(2, 1) = 2 - not the sum (3), and
# not the added side alone (1).
count_case '5{N;s/\n/+/}' 2 '  5 - 5
  6 - 6
  5 + 5+6'
rm -f "$FORTY"

# The existing three-line case, pinned as a whole header line rather than the
# floating `3 line(s)` above, which `13 line(s)` would satisfy.
reset_src
printf 'const a = 90\nconst b = 90\n' >> "$SRC"
out="$(mutate src/main.ts 's/90/-90/g' -- true)"
assert_eq "AC-4: s/90/-90/g on three matching lines still reports 3, as a whole header line" 1 \
  "$(whole_lines '=== mutate: src/main.ts (3 line(s) changed by s/90/-90/g) ===' "$out")"
reset_src
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-029 AC-5: the restore listing is capped, and costs the same however much changed"

# 30 separate one-line hunks: every odd line of 60 (GNU sed's first~step
# address, checked on Git Bash's sed 4.9; CI is ubuntu-latest, also GNU).
# The story's Contract said a 40-line file; 1~3 on 40 lines changes 14, and 30
# SEPARATE lines need at least 59 - see the C-3 amendment.
SIXTY="$FIX/src/sixty.txt"
seq 1 60 > "$SIXTY"
out="$(mutate src/sixty.txt '1~2s/$/x/' -- true)"
assert_eq "AC-5: 30 separate changed lines report 30, as a whole header line" 1 \
  "$(whole_lines '=== mutate: src/sixty.txt (30 line(s) changed by 1~2s/$/x/) ===' "$out")"
pv="$(preview_of "$out")"
assert_eq "AC-4: the preview is capped at 20 lines" 20 "$(awk 'END { print NR + 0 }' <<< "$pv")"
exp="$(for n in 1 3 5 7 9 11 13 15 17 19; do printf '  %s: %s\n' "$n" "$n"; done; printf '  ... and 20 more')"
assert_eq "AC-5: the listing is ten restored lines, then exactly '  ... and 20 more'" \
  "$exp" "$(listing_of "$out")"
assert_eq "AC-5: the '  ... and 20 more' line appears once, compared whole" 1 \
  "$(whole_lines '  ... and 20 more' "$out")"

# A pure insertion restores no line, so it lists none.
seq 1 40 > "$FORTY"
out="$(mutate src/forty.txt '2s/$/\ninserted/' -- true)"
assert_eq "AC-5: a pure insertion lists no restored lines" "" "$(listing_of "$out")"
rm -f "$FORTY"

# "Reads the restored file once, not once per line", stated as what it costs:
# the external processes mutate.sh starts, read from a `bash -x` trace
# (_lib.sh's trace_externals), are the same for 1 changed line and for 30.
# Before this story the listing started one awk per changed line.
seq 1 60 > "$SIXTY"
c1="$(trace_script "$FIX" "$W/one" mutate.sh src/sixty.txt 's/^1$/one/' -- true)"
c30="$(trace_script "$FIX" "$W/thirty" mutate.sh src/sixty.txt '1~2s/$/x/' -- true)"
t1="$(ext_count "$c1" TOTAL)"; t30="$(ext_count "$c30" TOTAL)"
if [ -n "$t1" ] && [ "$t1" != 0 ] && [ "$t1" = "$t30" ]; then
  _ok "AC-5: 30 changed lines start no more processes than 1"
else
  _bad "AC-5: 30 changed lines start no more processes than 1" "1 line: $t1 processes; 30 lines: $t30
by command, 1 line:
$c1
by command, 30 lines:
$c30"
fi
rm -f "$SIXTY"
clear_strays

# ===========================================================================
# HARNESS-030: a mutation in flight says so, in an `.active` sentinel written
# before the file is touched and removed only after a verified restore; and
# `mutate.sh --check` reads what a killed run left behind. No test here races a
# real SIGKILL: a STRANDED mutation is planted - target mutated, `.bak` holding
# the original, an `.active` whose pid is the `$$` of a `bash -c` that has
# already exited and been reaped (the story's C-4). A RUNNING one uses the pid of
# a bounded `sleep 30 &`, killed at the end of its block and by the EXIT trap.
#
# Needles are whole lines (whole_lines, `grep -cxF`) or exact values. The texts
# of --check are downstream's (manga-translator a0b43a2), read out verbatim per
# the Contract's C-1; the cannot-record line is AC-2's. Every assertion below
# executes unconditionally, so the executed count is fixed (floors.conf).

FIXABS="$(cd "$FIX" && pwd)"
ABSMUT="$FIXABS/.claude/state/mutations"
H30_SLEEP=""
trap 'chmod 644 "$FIX/src/main.ts" "$W/h30-outside.ts" 2>/dev/null; [ -n "$H30_SLEEP" ] && kill "$H30_SLEEP" 2>/dev/null; rm -rf "$FIX" "$W"' EXIT

# count_re_m <ERE> <text>   How many lines of <text> match. HARNESS-028's rule:
# no intervals, no \d, no backreferences in any pattern passed here.
count_re_m() { awk 'BEGIN { re = ARGV[1]; ARGV[1] = "" } $0 ~ re { n++ } END { print n + 0 }' "$1" <<< "$2"; }
# actives   How many sentinel FILES sit in the mutations directory. Files only:
# AC-2's unwritable-sentinel method plants a directory under that name.
actives() { local n=0 a; for a in "$ABSMUT"/*.active; do [ -f "$a" ] && n=$((n + 1)); done; printf '%s' "$n"; }
# the_bak   The path of the one backup, or empty.
the_bak() { local b; for b in "$ABSMUT"/*.bak; do [ -f "$b" ] && printf '%s' "$b"; done; }
# key_of <sentinel file> <key>   The value of one tab-separated key, read from a
# file (no pipe), first occurrence.
key_of() { awk -F'\t' -v k="$2" '$1 == k { print substr($0, length(k) + 2); exit }' "$1" 2>/dev/null; }
# keys_of <file>   The keys in order, space-joined.
keys_of() { awk -F'\t' '{ printf "%s%s", (NR > 1 ? " " : ""), $1 }' "$1" 2>/dev/null; }
lines_of() { awk 'END { print NR + 0 }' "$1" 2>/dev/null || printf 0; }
# chk   --check in the fixture, stdout and stderr kept apart: AC-3 is about
# stdout, AC-4 about stderr.
chk() {
  CHK_OUT="$( cd "$FIX" && bash scripts/mutate.sh --check 2>"$W/h30-err" )"; CHK_RC=$?
  CHK_ERR="$(cat "$W/h30-err" 2>/dev/null)"
}
# remedy_of <text>   The indented remedy line --check printed, unindented.
remedy_of() { awk '/^      (cp|rm -f) / { sub(/^      /, ""); print; exit }' <<< "$1"; }
# plant <sentinel> <pid> <file> <path, or empty for no path line> <backup> <expr> <command> <started>
plant() {
  mkdir -p "$ABSMUT"
  {
    printf 'pid\t%s\n' "$2"
    printf 'file\t%s\n' "$3"
    [ -n "$4" ] && printf 'path\t%s\n' "$4"
    printf 'backup\t%s\n' "$5"
    printf 'expr\t%s\n' "$6"
    printf 'command\t%s\n' "$7"
    printf 'started\t%s\n' "$8"
  } > "$1"
}
dead_pid() { bash -c 'echo $$'; }
is_alive() { if kill -0 "$1" 2>/dev/null; then printf alive; else printf gone; fi; }
MUTATED='export const clamp = (v) => Math.min(-90, v)'
UNACCOUNTED='mutate: a mutation is unaccounted for. The tree may not be the code you think.'
CLEAN_LINE='mutate: no stranded mutation; nothing of a previous run is in the tree.'
GONE_SUFFIX='(GONE - the run was killed, so the file is probably still mutated)'
RUNNING_SUFFIX='(RUNNING - a mutation is in flight right now; wait for it)'
ONE_COUNT='1 unaccounted-for mutation(s). Nothing that judges this tree should run'

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-1: the command sees an .active sentinel with seven keys, and it goes after the restore"

reset_src
clear_strays
SEEN="$W/h30-seen"
rm -f "$SEEN" "$W/h30-env" "$W/h30-named"
H30_SCRIPT='cat .claude/state/mutations/*.active > "$1"; printf "%s" "$HARNESS_MUTATION" > "$2"; cat "$HARNESS_MUTATION" > "$3"'
out="$(mutate src/main.ts 's/90/-90/' -- sh -c "$H30_SCRIPT" h30 "$SEEN" "$W/h30-env" "$W/h30-named")"; rc=$?
s_pid="$(key_of "$SEEN" pid)"; s_started="$(key_of "$SEEN" started)"
assert_eq "AC-1: the command, which reads the sentinel and the file HARNESS_MUTATION names, exits 0" "0" "$rc"
assert_eq "AC-1: the command saw exactly one sentinel of seven lines" "7" "$(lines_of "$SEEN")"
assert_eq "AC-1: its keys, in order, are pid file path backup expr command started" \
  "pid file path backup expr command started" "$(keys_of "$SEEN")"
assert_eq "AC-1: file is the target as given" "src/main.ts" "$(key_of "$SEEN" file)"
assert_eq "AC-1: path is the resolved absolute target" "$FIXABS/src/main.ts" "$(key_of "$SEEN" path)"
assert_eq "AC-1: backup is this run's .bak, named by the same stamp and pid" \
  "$ABSMUT/src_main.ts.$s_started.$s_pid.bak" "$(key_of "$SEEN" backup)"
assert_eq "AC-1: expr is the expression" "s/90/-90/" "$(key_of "$SEEN" expr)"
assert_eq "AC-1: command is the command, space-joined" \
  "sh -c $H30_SCRIPT h30 $SEEN $W/h30-env $W/h30-named" "$(key_of "$SEEN" command)"
assert_eq "AC-1 (C-1): the command is told its own sentinel in HARNESS_MUTATION, named <safe>.<stamp>.<pid>.active" \
  "$ABSMUT/src_main.ts.$s_started.$s_pid.active" "$(cat "$W/h30-env" 2>/dev/null)"
if [ -s "$W/h30-named" ] && cmp -s "$SEEN" "$W/h30-named"; then
  _ok "AC-1 (C-1): the file HARNESS_MUTATION names is the sentinel the command found"
else _bad "AC-1 (C-1): the file HARNESS_MUTATION names is the sentinel the command found" "named: $(cat "$W/h30-named" 2>/dev/null)"; fi
assert_eq "AC-1: after a verified restore with exit 0, no sentinel is left" "0" "$(actives)"

# Whatever the command's exit: a failure, and a command that never started.
out="$(mutate src/main.ts 's/90/-90/' -- sh -c 'exit 1')"; rc=$?
assert_eq "AC-1: a failing command's exit is still its own" "1" "$rc"
assert_eq "AC-1: after a verified restore with exit 1, no sentinel is left" "0" "$(actives)"
mutate src/main.ts 's/90/-90/' -- no-such-command-here >/dev/null 2>&1
assert_eq "AC-1: after a command that never started, no sentinel is left" "0" "$(actives)"

# A multi-command expression carries real newlines (HARNESS-026). The record
# stays one line per key: the newline is written as the two characters \n.
rm -f "$SEEN"
out="$(mutate src/main.ts $'s/90/-90/\ns/(v)/(w)/' -- sh -c 'cat .claude/state/mutations/*.active > "$1"' h30 "$SEEN")"
assert_eq "AC-1: a two-line expression still leaves a seven-line sentinel" "7" "$(lines_of "$SEEN")"
assert_eq "AC-1: and its expr holds the newline as the two characters \\n" \
  's/90/-90/\ns/(v)/(w)/' "$(key_of "$SEEN" expr)"
assert_eq "AC-1: and it is gone afterwards" "0" "$(actives)"
reset_src
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-1/AC-2: visible from outside while the command runs, and removed after a TERM once restored"

# HARNESS-029 AC-3's method: a short `sleep 3`, TERM to mutate.sh's own pid read
# from its backup's name, both waits bounded and a KILL past either.
reset_src
clear_strays
( cd "$FIX" && exec bash scripts/mutate.sh src/main.ts 's/90/-90/' -- sh -c 'sleep 3' ) > "$W/h30-term.out" 2>&1 &
wrapper=$!
i=0
while [ "$i" -lt 200 ] && ! grep -qF -- '-90' "$SRC" 2>/dev/null; do sleep 0.1; i=$((i + 1)); done
during="$(actives)"
mpid=""
for b in "$MUTDIR"/*.bak; do [ -e "$b" ] || continue; mpid="${b%.bak}"; mpid="${mpid##*.}"; done
if [ "$i" -lt 200 ] && [ -n "$mpid" ]; then
  _ok "AC-2 precondition: the file was mutated, and mutate.sh's pid known, before TERM"
  kill -TERM "$mpid" 2>/dev/null
else
  _bad "AC-2 precondition: the file was mutated, and mutate.sh's pid known, before TERM" \
    "mutated within 20s: $([ "$i" -lt 200 ] && printf yes || printf no); pid: ${mpid:-unknown}"
  kill -TERM "$wrapper" 2>/dev/null
fi
assert_eq "AC-1: while the command runs, exactly one sentinel is visible from outside" "1" "$during"
target="${mpid:-$wrapper}"
j=0
while [ "$j" -lt 300 ] && kill -0 "$target" 2>/dev/null; do sleep 0.1; j=$((j + 1)); done
if [ "$j" -ge 300 ]; then
  kill -KILL "$target" "$wrapper" 2>/dev/null
  _bad "AC-2: the run ends after TERM" "still running 30s after TERM; killed"
else _ok "AC-2: the run ends after TERM"; fi
wait "$wrapper" 2>/dev/null
assert_eq "AC-2: after TERM the file is restored" "$ORIGINAL" "$(cat "$SRC")"
assert_eq "AC-2: after TERM and a verified restore, no sentinel is left" "0" "$(actives)"
reset_src
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-2: the sentinel survives a restore that could not be verified"

# The backup deleted by the command: nothing to restore from.
reset_src
clear_strays
out="$(mutate src/main.ts 's/90/-90/' -- sh -c 'rm -f .claude/state/mutations/*.bak')"; rc=$?
assert_eq "AC-2 precondition: a deleted backup is COULD NOT RESTORE, exit 90" "90" "$rc"
assert_eq "AC-2: and the sentinel survives it" "1" "$(actives)"
reset_src
clear_strays

# The target made read-only by the command (HARNESS-029 AC-1's method, whose
# precondition is asserted above): the backup is there, the copy back fails.
out="$(mutate src/main.ts 's/90/-90/' -- chmod 444 src/main.ts)"; rc=$?
chmod 644 "$SRC"
assert_eq "AC-2 precondition: a read-only target is COULD NOT RESTORE, exit 90" "90" "$rc"
assert_eq "AC-2: and the sentinel survives it, beside its backup" "1" "$(actives)"
reset_src
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-2: a sentinel that cannot be written stops the mutation"

# THE METHOD, PROVED BEFORE IT IS RELIED ON. The sentinel's name is
# <safe>.<stamp>.<pid>.active, unknowable in advance. A read-only mutations/
# directory would fail the BACKUP first (it lives there too), and on Git Bash a
# chmod'd directory does not refuse new files anyway. So a `date` shim on PATH
# fixes the stamp and - because a command substitution's child is exec'd
# directly, its $PPID is mutate.sh's own $$ - plants a DIRECTORY at exactly the
# path the sentinel will be written to, and records that path. A redirect into
# a directory fails ("Is a directory") on every platform, as root too. The shim
# is called once, by the STAMP line; nothing else in mutate.sh runs `date`.
# Measured on Git Bash 2026-10-04: the shim's $PPID equalled the script's $$
# and the redirect was refused. The precondition below re-proves it every run,
# so a host where it does not hold fails here rather than passing for the
# wrong reason.
SHIM="$W/h30-shim"
mkdir -p "$SHIM"
cat > "$SHIM/date" <<'EOF'
#!/usr/bin/env bash
d="$(pwd)/.claude/state/mutations/src_main.ts.20260101T000000Z.$PPID.active"
mkdir -p "$d"
printf '%s\n' "$d" > "$H30_PLANTED"
printf '20260101T000000Z\n'
EOF
chmod +x "$SHIM/date"
export H30_PLANTED="$W/h30-planted"
mutate_shimmed() { ( cd "$FIX" && PATH="$SHIM:$PATH" bash scripts/mutate.sh "$@" 2>&1 ); }

clear_strays
rm -f "$H30_PLANTED"
pre="$( cd "$FIX" && PATH="$SHIM:$PATH" bash -c 's="$(date -u +%Y%m%dT%H%M%SZ)"; { printf x; } > "$(pwd)/.claude/state/mutations/src_main.ts.$s.$$.active" 2>/dev/null && printf written || printf refused' 2>/dev/null )"
assert_eq "AC-2 precondition: under the date shim, a script's own sentinel redirect fails on this host" "refused" "$pre"
clear_strays

reset_src
before="$(sha "$SRC")"
rm -f "$H30_PLANTED" "$FIX/ran-marker"
out="$(mutate_shimmed src/main.ts 's/90/-90/' -- touch ran-marker)"; rc=$?
planted="$(cat "$H30_PLANTED" 2>/dev/null)"
assert_eq "AC-2: an unwritable sentinel exits 2" "2" "$rc"
assert_eq "AC-2: and says so, as a whole line naming the sentinel's path" 1 \
  "$(whole_lines "mutate: cannot record the mutation in flight at $planted; refusing to mutate without it" "$out")"
assert_eq "AC-2: the file is byte-identical to before" "$before" "$(sha "$SRC")"
assert_eq "AC-2: no .bak is left" 0 "$(strays_of bak)"
assert_eq "AC-2: no .new is left" 0 "$(strays_of new)"
if [ -e "$FIX/ran-marker" ]; then
  _bad "AC-2: the command is not run when the mutation cannot be recorded" "ran-marker exists"
else _ok "AC-2: the command is not run when the mutation cannot be recorded"; fi
rm -f "$FIX/ran-marker"
clear_strays

# NEVER WRITTEN for an expression sed rejects or one that changes nothing - and
# "never" is observable here, not just "not left behind": under the same shim
# a run that tried to write the sentinel would die on the planted directory
# with the cannot-record line instead.
reset_src
out="$(mutate_shimmed src/main.ts 's/[/x/' -- true)"; rc=$?
assert_eq "AC-2: a rejected expression still exits 2" "2" "$rc"
assert_eq "AC-2: with sed's own message" 1 "$(whole_lines 'mutate: sed rejected the expression:' "$out")"
assert_eq "AC-2: and the sentinel was never attempted" 0 "$(count_re_m '^mutate: cannot record the mutation in flight' "$out")"
assert_eq "AC-2: and no sentinel exists" "0" "$(actives)"
clear_strays
out="$(mutate_shimmed src/main.ts 's/NOT_IN_THE_FILE/x/' -- true)"; rc=$?
assert_eq "AC-2: an expression that changes nothing still exits 3" "3" "$rc"
assert_eq "AC-2: and the sentinel was never attempted for it" 0 "$(count_re_m '^mutate: cannot record the mutation in flight' "$out")"
assert_eq "AC-2: and no sentinel exists after it" "0" "$(actives)"
clear_strays

# REMOVED when the target cannot be written and is verified unchanged.
reset_src
chmod 444 "$SRC"
out="$(mutate src/main.ts 's/90/-90/' -- true)"; rc=$?
chmod 644 "$SRC"
assert_eq "AC-2 precondition: a read-only target is cannot-write, exit 2" "2" "$rc"
assert_eq "AC-2: and no sentinel is left after a verified cannot-write" "0" "$(actives)"
reset_src
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-3: --check on a clean tree is one line on stdout and exit 0"

clear_strays
chk
assert_eq "AC-3: a clean tree exits 0" "0" "$CHK_RC"
assert_eq "AC-3: and prints exactly that one line on stdout" "$CLEAN_LINE" "$CHK_OUT"

# A tree that has never mutated anything has no mutations/ directory at all.
mv "$MUTDIR" "$W/h30-mutdir-aside"
chk
mv "$W/h30-mutdir-aside" "$MUTDIR"
assert_eq "AC-3: with no mutations/ directory it exits 0" "0" "$CHK_RC"
assert_eq "AC-3: and prints the same one line" "$CLEAN_LINE" "$CHK_OUT"

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-4: --check names a stranded mutation, says GONE, and prints the exact remedy"

reset_src
clear_strays
DPID="$(dead_pid)"
assert_eq "AC-4 precondition: the planted pid belongs to a process that has exited" "gone" "$(is_alive "$DPID")"
STARTED=20261004T010203Z
P_BAK="$ABSMUT/src_main.ts.$STARTED.$DPID.bak"
P_ACT="$ABSMUT/src_main.ts.$STARTED.$DPID.active"
mkdir -p "$ABSMUT"
printf '%s\n' "$ORIGINAL" > "$P_BAK"
printf '%s\n' "$MUTATED" > "$SRC"
plant "$P_ACT" "$DPID" src/main.ts "$FIXABS/src/main.ts" "$P_BAK" 's/90/-90/' 'bash .claude/tests/gates.test.sh' "$STARTED"
chk
assert_eq "AC-4: a stranded mutation exits 1" "1" "$CHK_RC"
assert_eq "AC-4: and prints nothing on stdout" "" "$CHK_OUT"
assert_eq "AC-4: it opens with the unaccounted-for line" 1 "$(whole_lines "$UNACCOUNTED" "$CHK_ERR")"
assert_eq "AC-4: it names the file" 1 "$(whole_lines '  src/main.ts' "$CHK_ERR")"
assert_eq "AC-4: the expression" 1 "$(whole_lines '    mutated by:  s/90/-90/' "$CHK_ERR")"
assert_eq "AC-4: the command" 1 "$(whole_lines '    command:     bash .claude/tests/gates.test.sh' "$CHK_ERR")"
assert_eq "AC-4: the start stamp" 1 "$(whole_lines "    started:     $STARTED" "$CHK_ERR")"
assert_eq "AC-4: the backup" 1 "$(whole_lines "    original:    $P_BAK" "$CHK_ERR")"
assert_eq "AC-4: and reports the dead process as GONE" 1 "$(whole_lines "    process:     $DPID $GONE_SUFFIX" "$CHK_ERR")"
assert_eq "AC-4: the file differs, and it says so" 1 "$(whole_lines '    the file DIFFERS from the original. Put it back:' "$CHK_ERR")"
assert_eq "AC-4: the exact cp && cmp && rm -f remedy, against the recorded path" 1 \
  "$(whole_lines "      cp $P_BAK $FIXABS/src/main.ts && cmp $P_BAK $FIXABS/src/main.ts && rm -f $P_BAK $P_ACT" "$CHK_ERR")"
assert_eq "AC-4: the count line" 1 "$(whole_lines "$ONE_COUNT" "$CHK_ERR")"
assert_eq "AC-4: and the report's last line closes the count" "until each is resolved above." \
  "$(awk 'NF { last = $0 } END { print last }' <<< "$CHK_ERR")"
# The remedy is a command, so run it: it must put the file back and clear both.
remedy="$(remedy_of "$CHK_ERR")"
( cd "$FIX" && bash -c "$remedy" ) >/dev/null 2>&1
assert_eq "AC-4: running the printed remedy puts the original back" "$ORIGINAL" "$(cat "$SRC")"
chk
assert_eq "AC-4: and leaves --check clean" "0" "$CHK_RC"

# The file already matches the backup: only the clearing is needed.
reset_src
printf '%s\n' "$ORIGINAL" > "$P_BAK"
plant "$P_ACT" "$DPID" src/main.ts "$FIXABS/src/main.ts" "$P_BAK" 's/90/-90/' 'bash .claude/tests/gates.test.sh' "$STARTED"
chk
assert_eq "AC-4: a matching file still exits 1" "1" "$CHK_RC"
assert_eq "AC-4: and says it MATCHES" 1 \
  "$(whole_lines '    the file currently MATCHES the original; clearing this is safe:' "$CHK_ERR")"
assert_eq "AC-4: with the exact rm -f remedy" 1 "$(whole_lines "      rm -f $P_BAK $P_ACT" "$CHK_ERR")"
assert_eq "AC-4: and no cp remedy" 0 "$(count_re_m '^      cp ' "$CHK_ERR")"
remedy="$(remedy_of "$CHK_ERR")"
( cd "$FIX" && bash -c "$remedy" ) >/dev/null 2>&1
chk
assert_eq "AC-4: running that rm leaves --check clean" "0" "$CHK_RC"

# A sentinel with no `path` line (C-1's fallback) compares against $ROOT/<file>.
printf '%s\n' "$ORIGINAL" > "$P_BAK"
printf '%s\n' "$MUTATED" > "$SRC"
plant "$P_ACT" "$DPID" src/main.ts "" "$P_BAK" 's/90/-90/' 'true' "$STARTED"
chk
assert_eq "C-1: a sentinel with no path line falls back to <root>/<file> for the remedy" 1 \
  "$(whole_lines "      cp $P_BAK $FIXABS/src/main.ts && cmp $P_BAK $FIXABS/src/main.ts && rm -f $P_BAK $P_ACT" "$CHK_ERR")"
reset_src
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-4: both remedies hold for a target given as an absolute path"

# Triage finding 1: downstream compared the backup against $ROOT/$file, which
# for an absolute target is no file at all - so a file that MATCHES was reported
# as differing, and the cp remedy named a path that does not exist. Stranded by
# a REAL run, not planted, so the sentinel under test is the one mutate.sh
# writes (the story's DV-2 removes its path line and expects red here). The
# target is outside the fixture; the read-only command makes the restore fail.
OUTSIDE="$W/h30-outside.ts"
printf '%s\n' "$ORIGINAL" > "$OUTSIDE"
clear_strays
out="$(mutate "$OUTSIDE" 's/90/-90/' -- chmod 444 "$OUTSIDE")"; rc=$?
chmod 644 "$OUTSIDE"
O_BAK="$(the_bak)"
O_ACT="${O_BAK%.bak}.active"
assert_eq "AC-4 precondition: an absolute target made read-only is COULD NOT RESTORE, exit 90" "90" "$rc"
assert_eq "AC-4 precondition: and its backup survives, holding the original" "$ORIGINAL" "$(cat "$O_BAK" 2>/dev/null)"
chk
assert_eq "AC-4 (absolute): it exits 1" "1" "$CHK_RC"
assert_eq "AC-4 (absolute): it names the target as given" 1 "$(whole_lines "  $OUTSIDE" "$CHK_ERR")"
assert_eq "AC-4 (absolute): the file differs, and it says so" 1 \
  "$(whole_lines '    the file DIFFERS from the original. Put it back:' "$CHK_ERR")"
assert_eq "AC-4 (absolute): the cp && cmp && rm -f remedy names the absolute path" 1 \
  "$(whole_lines "      cp $O_BAK $OUTSIDE && cmp $O_BAK $OUTSIDE && rm -f $O_BAK $O_ACT" "$CHK_ERR")"
cp "$O_BAK" "$OUTSIDE" 2>/dev/null
chk
assert_eq "AC-4 (absolute): once the file matches, it says MATCHES" 1 \
  "$(whole_lines '    the file currently MATCHES the original; clearing this is safe:' "$CHK_ERR")"
assert_eq "AC-4 (absolute): with the exact rm -f remedy" 1 "$(whole_lines "      rm -f $O_BAK $O_ACT" "$CHK_ERR")"
rm -f "$OUTSIDE"
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-4: a sentinel whose process is alive is RUNNING"

clear_strays
sleep 30 &
H30_SLEEP=$!
assert_eq "AC-4 precondition: the planted pid is a live process" "alive" "$(is_alive "$H30_SLEEP")"
R_BAK="$ABSMUT/src_other.ts.$STARTED.$H30_SLEEP.bak"
R_ACT="$ABSMUT/src_other.ts.$STARTED.$H30_SLEEP.active"
printf 'other\n' > "$R_BAK"
plant "$R_ACT" "$H30_SLEEP" src/other.ts "$FIXABS/src/other.ts" "$R_BAK" 's/a/b/' 'true' "$STARTED"
chk
assert_eq "AC-4: a live sentinel is still reported, exit 1" "1" "$CHK_RC"
assert_eq "AC-4: as RUNNING" 1 "$(whole_lines "    process:     $H30_SLEEP $RUNNING_SUFFIX" "$CHK_ERR")"
assert_eq "AC-4: and not as GONE" 0 "$(count_re_m 'GONE - ' "$CHK_ERR")"

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-6: --check run as a mutation's own command counts its own sentinel out, and nothing else"

# Control first, while the live sentinel above is still planted: a SECOND,
# unrelated live mutation is still reported, and the command's own is not
# counted beside it.
reset_src
out="$(mutate src/main.ts 's/90/-90/' -- bash scripts/mutate.sh --check)"; rc=$?
assert_eq "AC-6 control: beside another live sentinel, --check as the command exits 1" "1" "$rc"
assert_eq "AC-6 control: the other one is reported RUNNING" 1 "$(whole_lines "    process:     $H30_SLEEP $RUNNING_SUFFIX" "$out")"
assert_eq "AC-6 control: and only it is counted" 1 "$(whole_lines "$ONE_COUNT" "$out")"
assert_eq "AC-6 control: the command's own mutation is not listed as unaccounted for" 0 \
  "$(whole_lines '  src/main.ts' "$out")"

# HARNESS_MUTATION alone is not enough: it must name a sentinel whose pid is
# alive. Naming the live one above, it is that command's own...
out="$( cd "$FIX" && HARNESS_MUTATION="$R_ACT" bash scripts/mutate.sh --check 2>&1 )"; rc=$?
assert_eq "C-1: HARNESS_MUTATION naming a live sentinel in this tree counts it out, exit 0" "0" "$rc"
assert_eq "C-1: and says the one in flight is that command's own" 1 \
  "$(whole_lines "mutate: no stranded mutation; the one in flight is this command's own (src/other.ts)." "$out")"
kill "$H30_SLEEP" 2>/dev/null; wait "$H30_SLEEP" 2>/dev/null; H30_SLEEP=""
rm -f "$R_ACT" "$R_BAK"

# ...and naming a dead one, a stale variable gains nothing.
printf '%s\n' "$ORIGINAL" > "$P_BAK"
plant "$P_ACT" "$DPID" src/main.ts "$FIXABS/src/main.ts" "$P_BAK" 's/90/-90/' 'true' "$STARTED"
out="$( cd "$FIX" && HARNESS_MUTATION="$P_ACT" bash scripts/mutate.sh --check 2>&1 )"; rc=$?
assert_eq "C-3: HARNESS_MUTATION naming a dead sentinel still exits 1" "1" "$rc"
assert_eq "C-3: and reports it GONE" 1 "$(whole_lines "    process:     $DPID $GONE_SUFFIX" "$out")"
clear_strays

# The case itself: alone, its own sentinel is the only one, and that is clean.
reset_src
out="$(mutate src/main.ts 's/90/-90/' -- bash scripts/mutate.sh --check)"; rc=$?
assert_eq "AC-6: --check as the mutation's own command exits 0" "0" "$rc"
assert_eq "AC-6: and says the one mutation in flight is its own" 1 \
  "$(whole_lines "mutate: no stranded mutation; the one in flight is this command's own (src/main.ts)." "$out")"
assert_eq "AC-6: and does not call it unaccounted for" 0 "$(whole_lines "$UNACCOUNTED" "$out")"
reset_src
clear_strays

# ---------------------------------------------------------------------------
describe "HARNESS-030 AC-7: the sentinel is documented where the state, the commands and the rules live"

# Whole lines where the Contract (C-6) gives the text. The rules.md sentence is
# given by meaning, not verbatim, so it is pinned by the two names it must
# carry, inside the one bullet that holds the `.bak` sentence. One awk reads
# the file: no pipeline, so no SIGPIPE.
assert_eq "AC-7: .claude/state/README.md has the mutations/*.active row" 1 \
  "$(whole_lines '| `mutations/*.active` | `scripts/mutate.sh` | `mutate.sh --check`, and `gates.sh` through it | yes |' "$(tr -d '\r' < "$REPO_ROOT/.claude/state/README.md")")"
assert_eq "AC-7: CLAUDE.md's Running things block lists bash scripts/mutate.sh --check" 1 \
  "$(count_re_m '^bash scripts/mutate\.sh --check +# is a killed mutation still in the tree\? gates\.sh asks first$' "$(tr -d '\r' < "$REPO_ROOT/CLAUDE.md")")"
bak_bullet="$(awk '{ sub(/\r$/, "") }
  /^- Do not commit `\.claude\/state\/\*\*`/ { f = 1; printf "%s ", $0; next }
  f && /^- / { exit }
  f { printf "%s ", $0 }' "$REPO_ROOT/.claude/harness/rules.md")"
assert_contains "AC-7 precondition: the rules.md bullet holding the .bak sentence is found" '`.bak` left behind' "$bak_bullet"
assert_contains "AC-7: rules.md's .bak bullet says what a surviving .active means" '.active' "$bak_bullet"
assert_contains "AC-7: and names mutate.sh --check" 'mutate.sh --check' "$bak_bullet"

summary "mutate"
