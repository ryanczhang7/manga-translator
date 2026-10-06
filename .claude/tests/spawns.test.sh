#!/usr/bin/env bash
# HARNESS-025 - one phase-guard invocation spawns at most 27 processes.
#
# A port of manga-translator MT-041 (73ae959) and its R-1 (5f5ff6d). Every
# assertion of this story lives here, not in lib.test.sh or phase-guard.test.sh
# (C-2): those two are untouched, which is what makes AC-6 a property of
# `git diff`, and this suite runs in about the time of a handful of traces
# rather than the forty minutes those two take on a slow-forking host.
#
# A COST STORY. lib.sh is rewritten to spawn fewer processes and NO verdict may
# move. So most of what follows passes on arrival: it pins what the rewrite must
# preserve, and HARNESS-025 `## Test plan` has the C-5 mutation that earned
# each class. What is RED on arrival is the cost claims themselves (AC-1, AC-2's
# counts) and any agreement check that calls a helper GREEN introduces
# (`_to_slashes`).
#
# Numbers that are READ OUT of the story (C-8: settled) - the bound 27, and the
# measured 46 / 2,2,6 quoted in the comments - are not calibrated here.
#
# H025_CAPTURE_GOLDEN=<file>   Capture AC-5's golden instead of running the
# suite: classify every path in fixtures/classify/paths.txt with whatever
# lib.sh is checked out, write `<category>\t<path>` to <file>, and exit. The
# golden in the tree was captured this way from the UNCHANGED lib.sh (C-4);
# the handoff records the command and its sha256.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
. "$TESTS_DIR/_spawns.sh"

CLASSIFY_FIXTURES="$TESTS_DIR/fixtures/classify"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t h025.XXXXXX)"
FIXTURES_MADE=""
trap 'rm -rf "$WORK" $FIXTURES_MADE' EXIT

# ignore_fixture   make_fixture, plus ignore rules that tell the two spellings
# is_ignored asks about apart. make_fixture's own .gitignore already holds
# `.vitest/` and `playwright-report/`, which a bare name that is not on disk
# matches only in its SLASHED spelling. These add the mirror image:
#
#   bareonly     `bareonly` is ignored only BARE - `!bareonly/` re-includes
#   !bareonly/   the slashed spelling - so dropping either spelling moves a
#                verdict somewhere.
#   *.tmp        `keep.tmp` matches a pattern, the negation, and is NOT
#   !keep.tmp    ignored; `x.tmp` is.
ignore_fixture() {
  local d
  d="$(make_fixture)"
  printf 'bareonly\n!bareonly/\n*.tmp\n!keep.tmp\n' >> "$d/.gitignore"
  git -C "$d" add -A >/dev/null 2>&1
  printf '%s' "$d"
}

# classify_paths <fixture> <out>   AC-5's measurement: every line of
# paths.txt, its placeholders expanded against <fixture>, judged the way
# check_path judges a path - `classify "$(to_rel "$p")"` - in a subshell with
# lib.sh sourced against <fixture>. Writes `<category>\t<path as written>`.
#
#   @ROOTBS@   the fixture root spelled with BACKSLASHES
#   @ROOT@     the fixture root as mktemp spelled it
#   @BASE@     the fixture root's folder name - to_rel's drive-letter branch
classify_paths() {
  ( export CLAUDE_PROJECT_DIR="$1"
    . "$REPO_ROOT/.claude/hooks/lib.sh"
    root="$1"; rootbs="$(printf '%s' "$root" | tr '/' '\134')"; base="${root##*/}"
    while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      p="${line//@ROOTBS@/$rootbs}"; p="${p//@ROOT@/$root}"; p="${p//@BASE@/$base}"
      printf '%s\t%s\n' "$(classify "$(to_rel "$p")")" "$line"
    done < "$CLASSIFY_FIXTURES/paths.txt"
  ) > "$2"
}

if [ -n "${H025_CAPTURE_GOLDEN:-}" ]; then
  _cap="$(ignore_fixture)"; FIXTURES_MADE="$_cap"
  classify_paths "$_cap" "$H025_CAPTURE_GOLDEN"
  printf 'captured %s paths into %s\n' "$(awk 'END { print NR }' "$H025_CAPTURE_GOLDEN")" "$H025_CAPTURE_GOLDEN"
  exit 0
fi

# tally_detail <tally>   The whole tally, for a failure message: a count that
# is over its bound should say which tools it was spent on.
tally_detail() { printf 'measured, one line per tool (count, key):\n%s' "$1"; }

# ===========================================================================
describe "HARNESS-025 AC-3  the instrument counts processes, and only processes"

# Run FIRST: every bound below is "at most", and a counter that counts nothing
# satisfies every "at most". So the instrument is pointed at snippets whose
# answers are known before it is pointed at the hook.
FIX="$(make_fixture)"; FIXTURES_MADE="$FIXTURES_MADE $FIX"

# AC-3's script, as the story writes it. One tr, one git, and three builtins
# (printf, true, [) that must NOT count.
spawn_trace_fn "$FIX" "$WORK/ctl" 'tr a b </dev/null; printf x; git rev-parse --git-dir; true; [ 1 = 1 ]'
_tally="$(spawn_tally "$WORK/ctl")"
assert_eq "instrument: one tr is counted as one tr"           "1" "$(spawn_count "$_tally" 'tr:*')"
assert_eq "instrument: one git is counted, keyed by its subcommand" "1" "$(spawn_count "$_tally" 'git rev-parse')"
assert_eq "instrument: printf, true and [ are builtins, not spawns (total 2)" "2" "$(spawn_count "$_tally" TOTAL)"

# AC-1's four zeros are only worth something if the instrument RECOGNISES the
# four forms: a key that never matched would read 0 for the old lib.sh too.
# One of each, plus lower()'s tr, which this story leaves alone (C-3). Read
# from a heredoc so that no quoting is lost on the way to the snippet.
_forms="$(cat <<'SNIP'
tr -d '[:space:]' </dev/null; tr '\134' '/' </dev/null; tr -d '"'"'" </dev/null; tr -d '\r' </dev/null; tr 'A-Z' 'a-z' </dev/null
SNIP
)"
spawn_trace_fn "$FIX" "$WORK/forms" "$_forms"
_tally="$(spawn_tally "$WORK/forms")"
assert_eq "instrument: tr -d '[:space:]' is keyed tr:space"           "1" "$(spawn_count "$_tally" tr:space)"
assert_eq "instrument: tr '\\134' '/' is keyed tr:backslash"          "1" "$(spawn_count "$_tally" tr:backslash)"
assert_eq "instrument: tr -d of the two quote characters is keyed tr:quotes" "1" "$(spawn_count "$_tally" tr:quotes)"
assert_eq "instrument: tr -d '\\r' is keyed under tr:other -d"         "1" "$(spawn_count "$_tally" 'tr:other -d*')"
assert_eq "instrument: tr 'A-Z' 'a-z' is keyed tr:lower"              "1" "$(spawn_count "$_tally" tr:lower)"
assert_eq "instrument: five tr forms are five spawns"                  "5" "$(spawn_count "$_tally" TOTAL)"

# R-1. xtrace spells an embedded single quote as '\'' - a backslash OUTSIDE
# quotes. A parser that reads that escaped quote as opening a span ends the
# word early, and the next word of the VALUE becomes a command name; on the
# downstream CI runner that counted `.gitignore` twice and AC-1 read 29 for a
# true 27. The decoy is an executable on PATH in the tallying shell, so the old
# parser counts it on every platform, not only where some file in the tree
# happens to resolve.
_bin="$WORK/bin"; mkdir -p "$_bin"
printf '#!/bin/sh\nexit 0\n' > "$_bin/h025decoy"; chmod +x "$_bin/h025decoy"
spawn_trace_fn "$FIX" "$WORK/esc" "v=\"it's h025decoy here\""
_tally="$(PATH="$_bin:$PATH" spawn_tally "$WORK/esc")"
if PATH="$_bin:$PATH" type -P h025decoy >/dev/null 2>&1; then
  _ok "instrument R-1: the decoy resolves on PATH (control precondition)"
else _bad "instrument R-1: the decoy resolves on PATH (control precondition)" "type -P h025decoy failed"; fi
assert_contains "instrument R-1: the trace spells the quote as '\\''" "'\''" "$(cat "$WORK/esc")"
assert_eq "instrument R-1: a word after '\\'' inside a value is not a command" "0" \
  "$(spawn_count "$_tally" h025decoy)"
assert_eq "instrument R-1: an assignment alone spawns nothing" "0" "$(spawn_count "$_tally" TOTAL)"

# ===========================================================================
describe "HARNESS-025 AC-1  one guard invocation spawns at most 27 processes"
set_phase "$FIX" RED

# The invocation AC-1 names, on the real hook. RED ON ARRIVAL - measured at
# b6b4f27 (C-7): 46 in total, of which tr:space 7, tr:backslash 5, tr:quotes 4
# and tr -d '\r' 1. The bound 27 is C-7's arithmetic, read out, not tuned here.
spawn_trace "$FIX" Bash command 'echo hi > src/main.ts' "$WORK/ac1"
_ac1="$(spawn_tally "$WORK/ac1")"

# Vacuity controls: the bounds are all "at most", so a trace that never
# reached the judgement would satisfy them by counting nothing.
assert_contains "AC-1: the traced invocation still denies src/main.ts in RED (instrument control)" \
  '"permissionDecision":"deny"' "$(cat "$WORK/ac1.out")"
if [ "$(spawn_traced_calls "$WORK/ac1" classify)" -ge 1 ]; then
  _ok "AC-1: the trace reached classify (instrument control)"
else _bad "AC-1: the trace reached classify (instrument control)" "no classify call in the trace"; fi

_n="$(spawn_count "$_ac1" TOTAL)"
if [ "$_n" -le 27 ]; then _ok "AC-1: echo hi > src/main.ts spawns at most 27 external processes"
else _bad "AC-1: echo hi > src/main.ts spawns at most 27 external processes" "spawned $_n
$(tally_detail "$_ac1")"; fi
assert_eq "AC-1: no tr -d '[:space:]' is spawned"                 "0" "$(spawn_count "$_ac1" tr:space)"
assert_eq "AC-1: no tr '\\134' '/' is spawned"                     "0" "$(spawn_count "$_ac1" tr:backslash)"
assert_eq "AC-1: no tr -d of the two quote characters is spawned" "0" "$(spawn_count "$_ac1" tr:quotes)"
assert_eq "AC-1: no tr -d '\\r' is spawned"                        "0" "$(spawn_count "$_ac1" 'tr:other -d*')"

# HARNESS-035 AC-6. The host sends `cwd` in every hook input, so the bound has
# to hold with it present, not only in the suite's cwd-less input. Reading it
# and walking to its tree are pure bash; so is the ownership walk for a target.
GUARD_CWD="$FIX" spawn_trace "$FIX" Bash command 'echo hi > src/main.ts' "$WORK/h035"
_h035="$(spawn_tally "$WORK/h035")"
assert_contains "HARNESS-035 AC-6: with cwd, the traced invocation still denies src/main.ts (instrument control)" \
  '"permissionDecision":"deny"' "$(cat "$WORK/h035.out")"
_n="$(spawn_count "$_h035" TOTAL)"
_n0="$(spawn_count "$_ac1" TOTAL)"
if [ "$_n" -le 27 ]; then _ok "HARNESS-035 AC-6: with cwd in the input, echo hi > src/main.ts spawns at most 27"
else _bad "HARNESS-035 AC-6: with cwd in the input, echo hi > src/main.ts spawns at most 27" "spawned $_n
$(tally_detail "$_h035")"; fi
assert_eq "HARNESS-035 AC-6: and exactly as many as without it" "$_n0" "$_n"

# ===========================================================================
describe "HARNESS-025 AC-2  at most one git check-ignore per classified candidate"

# at_most <label> <trace> <tally> <want classify calls> <bound>
# The classify count is the instrument control: "at most N per candidate" over
# a trace that classified fewer candidates than claimed is satisfied by not
# asking.
at_most() {
  local c n
  c="$(spawn_traced_calls "$2" classify)"
  n="$(spawn_count "$3" 'git check-ignore')"
  if [ "$c" -ne "$4" ]; then
    _bad "$1" "classify was called $c times, not $4 (instrument control)"
  elif [ "$n" -le "$5" ]; then
    _ok "$1"
  else
    _bad "$1" "spawned $n git check-ignore for $c classified candidates
$(tally_detail "$3")"
  fi
}

# RED ON ARRIVAL, all three: measured 2, 2 and 6 at b6b4f27 - is_ignored asks
# `<p>`, then `<p>/`, in two processes.
at_most "AC-2: echo hi > src/main.ts spawns at most one git check-ignore" \
  "$WORK/ac1" "$_ac1" 1 1

spawn_trace "$FIX" Bash command 'rm -rf .vitest' "$WORK/vit"
assert_not_contains "AC-2: rm -rf .vitest is still allowed in RED - ignored only as .vitest/" \
  '"permissionDecision":"deny"' "$(cat "$WORK/vit.out")"
at_most "AC-2: rm -rf .vitest spawns at most one git check-ignore" \
  "$WORK/vit" "$(spawn_tally "$WORK/vit")" 1 1

# Three source candidates in GREEN, which permits source, so no denial ends the
# hook early and all three are classified.
set_phase "$FIX" GREEN
spawn_trace "$FIX" Bash command 'rm src/a.ts src/b.ts src/c.ts' "$WORK/three"
at_most "AC-2: three candidates spawn at most three git check-ignore" \
  "$WORK/three" "$(spawn_tally "$WORK/three")" 3 3

# THE CONTROL, BY VERDICT. Both spellings of every candidate must still reach
# git, and the instrument sees argv, not stdin - so this is proved by what the
# hook decides, whatever the mechanism. REVIEW refuses source; each of the
# three is ignored by a DIFFERENT spelling: `.vitest` and `playwright-report`
# only as `<p>/`, `bareonly` only as `<p>`. Allowed only if every candidate's
# deciding spelling reached git; drop either and one of them falls to `source`
# and the command is refused. Passes on arrival; earned by C-5 probe 1.
FIXB="$(ignore_fixture)"; FIXTURES_MADE="$FIXTURES_MADE $FIXB"
set_phase "$FIXB" REVIEW
spawn_trace "$FIXB" Bash command 'rm -rf .vitest bareonly playwright-report' "$WORK/both"
assert_not_contains "AC-2: rm -rf .vitest bareonly playwright-report is allowed in REVIEW - each ignored by a different spelling" \
  '"permissionDecision":"deny"' "$(cat "$WORK/both.out")"
at_most "AC-2: three ignored candidates spawn at most three git check-ignore" \
  "$WORK/both" "$(spawn_tally "$WORK/both")" 3 3

# ===========================================================================
describe "HARNESS-025 AC-4  the rewritten helpers agree with the forms they replace"

# In-process from here on: lib.sh sourced against the first fixture.
export CLAUDE_PROJECT_DIR="$FIX"
. "$REPO_ROOT/.claude/hooks/lib.sh"
BS="$(printf '\134')"

# --- _to_slashes <x> sets __lib_fs to what $(printf '%s' "$x" | tr '\134' '/')
# printed. That includes what $( ) STRIPPED: every trailing newline. The
# helper is GREEN's (C-3), so every case here is RED ON ARRIVAL.
to_slashes_case() { # <label> <value>
  local want got
  want="$(printf '%s' "$2" | tr '\134' '/')"
  unset __lib_fs
  if declare -F _to_slashes >/dev/null; then _to_slashes "$2"; fi
  got="${__lib_fs-<__lib_fs unset: lib.sh defines no _to_slashes>}"
  assert_eq "_to_slashes agrees with tr '\\134' '/' on $1" "$want" "$got"
}
to_slashes_case "a drive-letter path"              "C:${BS}Users${BS}x${BS}a.ts"
to_slashes_case "a run of backslashes"             "${BS}${BS}server${BS}${BS}${BS}share"
to_slashes_case "a value with no backslash"        "src/main.ts"
to_slashes_case "trailing newlines"                "C:${BS}x"$'\n\n\n'
to_slashes_case "a lone backslash"                 "$BS"
to_slashes_case "an inner newline and a trailing backslash" "a"$'\n'"b${BS}"
to_slashes_case "the empty string"                 ""

# The trailing-newline case is the one that separates the right expansion from
# the near miss (DV-2): `${x//\\//}` alone keeps the newlines `$( )` dropped.
_tn="C:${BS}x"$'\n\n\n'
_near="${_tn//\\//}"
if [ "$_near" != "$(printf '%s' "$_tn" | tr '\134' '/')" ]; then
  _ok "control: a conversion that keeps trailing newlines disagrees with tr on that input"
else _bad "control: a conversion that keeps trailing newlines disagrees with tr on that input" \
  "the input does not separate the two forms"; fi

# --- the whitespace deletion in phase_allows and phase_message is
# tr -d '[:space:]': SIX characters, not one. A phases.conf row whose phase and
# category fields are padded with a carriage return, a tab, a vertical tab and
# a form feed is still the RED row, and its categories are still read.
_ph="$WORK/phases"; mkdir -p "$_ph"
printf 'IDLE | vendor,ignored,test,source,config,docs,harness | idle\n' > "$_ph/phases.conf"
printf '\r\tRED\t\v| vendor, ignored ,\ttest,\fdocs ,harness\t\r | tabbed red message\n' >> "$_ph/phases.conf"
_hd="$HARNESS_DIR"; _pp="${PHASE:-}"
HARNESS_DIR="$_ph"; PHASE=RED
if phase_allows source; then _bad "phase_allows: a whitespace-padded RED row still forbids source" "allowed"
else _ok "phase_allows: a whitespace-padded RED row still forbids source"; fi
if phase_allows test; then _ok "phase_allows: a category after a tab is still permitted"
else _bad "phase_allows: a category after a tab is still permitted" "refused test - the padded phase name was not read as RED"; fi
if phase_allows docs; then _ok "phase_allows: a category after a form feed is still permitted"
else _bad "phase_allows: a category after a form feed is still permitted" "refused docs"; fi
if phase_allows harness; then _ok "phase_allows: a category before a tab and a carriage return is still permitted"
else _bad "phase_allows: a category before a tab and a carriage return is still permitted" "refused harness"; fi
assert_eq "phase_message: finds the whitespace-padded phase name" "tabbed red message" "$(phase_message)"

# The control AC-4 names: a deletion of spaces alone (`${x// /}`) must DISAGREE
# with tr -d '[:space:]' on the padded phase field, or the row above separates
# nothing.
_field=$'\r\tRED\t\v'
if [ "${_field// /}" != "$(printf '%s' "$_field" | tr -d '[:space:]')" ]; then
  _ok "control: a spaces-only deletion disagrees with tr -d '[:space:]' on the padded field"
else _bad "control: a spaces-only deletion disagrees with tr -d '[:space:]' on the padded field" \
  "both gave the same answer"; fi

# --- phase_message's trim matches the sed it replaces, on messages padded with
# every [:space:] character, carrying inner runs, a pipe, nothing at all, and a
# second carriage return (the read loop strips only one).
_msgs=(
  $' \t\v\f lead and trail \t\v\f '
  'inner   runs   survive'
  'a | pipe stays'
  $' \t  '
  ''
  'unpadded'
  $'two cr\r\r'
)
: > "$_ph/phases.conf"
_i=0
for _m in "${_msgs[@]}"; do
  _i=$((_i+1)); printf 'P%s | docs | %s\n' "$_i" "$_m" >> "$_ph/phases.conf"
done
# Compared as BYTES, through files, never as `$( )` captures: bash on
# MSYS/Cygwin deletes every carriage return from a command substitution's
# output, so a capture would hide exactly the character this block is about,
# on the platform the story was measured on. The oracle is the shipped line at
# b6b4f27, verbatim - its own inner `$( )` included.
_i=0
for _m in "${_msgs[@]}"; do
  _i=$((_i+1)); PHASE="P$_i"
  # The message field exactly as phase_message extracts it: the line's last \r
  # removed, then everything after the second `|`.
  printf -v _raw 'P%s | docs | %s' "$_i" "$_m"; _raw="${_raw%%$'\r'}"
  _raw="${_raw#*|}"; _raw="${_raw#*|}"
  printf '%s' "$(printf '%s' "$_raw" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')" > "$WORK/pm.want"
  phase_message > "$WORK/pm.got"
  golden_check "phase_message: trims message $_i exactly as the sed form did" "$WORK/pm.want" "$WORK/pm.got"
done
HARNESS_DIR="$_hd"; PHASE="$_pp"

# --- json_escape of a value carrying \r matches its old output, byte for byte
# and through files for the reason above. The oracle is the shipped pipeline at
# b6b4f27, verbatim.
old_json_escape() {
  printf '%s' "$1" | tr -d '\r' | awk 'BEGIN { ORS = "" }
    { gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); gsub(/\t/, "\\t")
      if (NR > 1) printf "\\n"
      printf "%s", $0 }'
}
_jin=(
  $'mid\rline'
  $'crlf\r\nline'
  "C:${BS}x"$'\r'
  $'\r'
  $'\r\r\n\r'
  $'tab\there "quoted"\r\n'
  $'no carriage return\nat all'
)
_i=0
for _j in "${_jin[@]}"; do
  _i=$((_i+1))
  old_json_escape "$_j" > "$WORK/je.want"
  json_escape "$_j" > "$WORK/je.got"
  golden_check "json_escape: input $_i, carrying \\r, matches the tr | awk form byte for byte" \
    "$WORK/je.want" "$WORK/je.got"
done
# Control: input 1's mid-line \r is one awk keeps on its own (MSYS awk drops a
# \r only before a newline), so the set separates "deletes \r" from "does not".
printf '%s' $'mid\rline' | awk 'BEGIN { ORS = "" } { printf "%s", $0 }' > "$WORK/je.awk"
old_json_escape $'mid\rline' > "$WORK/je.want"
if cmp -s "$WORK/je.awk" "$WORK/je.want"; then
  _bad "control: an escape that keeps \r disagrees with the old form on a mid-line \r" \
    "awk alone dropped the \r - the input separates nothing"
else _ok "control: an escape that keeps \r disagrees with the old form on a mid-line \r"; fi

# --- each of the four quote-strip sites strips BOTH quote characters, judged by
# the verdict of a command quoting its target each way. Every command below is
# ALLOWED in RED only because its quoted operand lost its quotes: a target
# still spelled `'docs/x.md'` matches no docs rule, falls to `source` and is
# refused. Measured against the shipped lib.sh with each site's set narrowed to
# `"` alone (C-5 probe 3 is the :632 one): every single-quoted command below
# flipped to DENY and every double-quoted one stayed allowed.
set_phase "$FIX" RED
assert_allowed "$FIX" "echo hi > 'docs/x.md'" \
  "write_candidates strips a single-quoted redirect target (docs/x.md, RED)"
assert_allowed "$FIX" 'echo hi > "docs/x.md"' \
  "write_candidates strips a double-quoted redirect target (docs/x.md, RED)"
assert_allowed "$FIX" "F='docs/x.md'; rm \"\$F\"" \
  "shell_assignments strips a single-quoted value (F='docs/x.md'; rm \"\$F\", RED)"
assert_allowed "$FIX" 'F="docs/x.md"; rm "$F"' \
  "shell_assignments strips a double-quoted value (F=\"docs/x.md\"; rm \"\$F\", RED)"
assert_allowed "$FIX" "bash scripts/mutate.sh 'src/main.ts' 's/a/b/' -- cp docs/notes.md src/main.ts" \
  "mutate_targets strips a single-quoted FILE, so the payload's write to it is exempt (RED)"
assert_allowed "$FIX" 'bash scripts/mutate.sh "src/main.ts" "s/a/b/" -- cp docs/notes.md src/main.ts' \
  "mutate_targets strips a double-quoted FILE, so the payload's write to it is exempt (RED)"
assert_allowed "$FIX" "cd 'docs' && echo x > main.ts" \
  "command_cwd strips a single-quoted cd target (cd 'docs' && echo x > main.ts, RED)"
assert_allowed "$FIX" 'cd "docs" && echo x > main.ts' \
  "command_cwd strips a double-quoted cd target (cd \"docs\" && echo x > main.ts, RED)"
# And the stripping does not open the lock: the same quoting on a source path.
assert_blocked "$FIX" "echo hi > 'src/main.ts'" "src/main.ts" \
  "a single-quoted redirect to src/main.ts in RED"

# ===========================================================================
describe "HARNESS-025 AC-5  classify's verdicts are unchanged"

# "Spawn less" must not be done by "decide less". Every path in paths.txt -
# tracked source and tests, vendor and build directories, gitignored paths in
# both spellings, backslash-spelled absolute paths into the fixture, and paths
# outside it - judged as check_path judges it, against a golden captured from
# the UNCHANGED lib.sh (C-4). `.vitest` and `playwright-report` are ignored
# only by their SLASHED spelling, `bareonly` only BARE, so C-5 probe 1 moves
# this golden too.
_cls="$WORK/classify.actual"
classify_paths "$FIXB" "$_cls"
golden_check "AC-5: classify(to_rel(p)) for every path in paths.txt is byte-identical to classify.golden" \
  "$CLASSIFY_FIXTURES/classify.golden" "$_cls"
assert_eq "AC-5: the golden judges every path in paths.txt (instrument control)" \
  "$(awk 'NF { n++ } END { print n + 0 }' "$CLASSIFY_FIXTURES/paths.txt")" \
  "$(awk 'END { print NR }' "$_cls")"

# ===========================================================================
describe "HARNESS-031 AC-6  the bare-path retry costs no process"

# The retry goes inside classify_stdin's awk (C-1), so a bare path that only its
# slashed form classifies is decided there and never reaches is_ignored's git.
# Numbers READ OUT of the story (C-6: settled), measured at 16c42a1 on this
# fixture in GREEN: `rm -rf fixtures` spawned 26 in total, 1 of them
# `git check-ignore`. HARNESS-025's AC-1 bound of 27 (above) has no headroom,
# which is why a retry that added a process would fail an existing test.
FIXF="$(make_fixture)"; FIXTURES_MADE="$FIXTURES_MADE $FIXF"
printf '%s\n' 'test | fixtures/**' >> "$FIXF/.claude/harness/paths.conf"
set_phase "$FIXF" GREEN
spawn_trace "$FIXF" Bash command 'rm -rf fixtures' "$WORK/h031"
_h031="$(spawn_tally "$WORK/h031")"

# Instrument control by verdict: the trace reached the judgement and the bare
# test directory was refused in GREEN. RED on arrival (allowed today).
assert_contains "AC-6: the traced rm -rf fixtures is refused in GREEN (instrument control)" \
  '"permissionDecision":"deny"' "$(cat "$WORK/h031.out")"
# at_most's shape: classify reached exactly once, THEN the bound. RED on
# arrival: measured 1 git check-ignore at 16c42a1.
at_most "AC-6: rm -rf fixtures spawns no git check-ignore" \
  "$WORK/h031" "$_h031" 1 0
_c="$(spawn_traced_calls "$WORK/h031" classify)"
_n="$(spawn_count "$_h031" TOTAL)"
if [ "$_c" -ne 1 ]; then
  _bad "AC-6: rm -rf fixtures spawns at most 26 external processes" \
    "classify was called $_c times, not 1 (instrument control)"
elif [ "$_n" -le 26 ]; then _ok "AC-6: rm -rf fixtures spawns at most 26 external processes"
else _bad "AC-6: rm -rf fixtures spawns at most 26 external processes" "spawned $_n
$(tally_detail "$_h031")"; fi

summary "spawns"
