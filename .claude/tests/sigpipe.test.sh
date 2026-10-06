#!/usr/bin/env bash
# WORLD-086 - a guard against pipefail SIGPIPE matchers.
#
# THE DEFECT CLASS THIS SUITE PINS A GUARD AGAINST
#
# Under `set -o pipefail`, a pipeline whose reader leaves early kills the writer
# with SIGPIPE, and pipefail promotes 141 to the pipeline's status:
#
#     has_content() { strip_comments | grep -q PATTERN; }
#
# `grep -q` exits at the first match; the awk inside strip_comments is still
# holding buffered output; it dies on EPIPE; the function returns 141; and every
# caller reads that as FALSE for a section that plainly has content. Found five
# times in this repository, twice by CI and never by a local run - the boundary
# is a pipe-buffer race and this Windows checkout sits on the safe side of it.
#
# WHY A GUARD RATHER THAN MORE VIGILANCE
#
# WORLD-084 was about this defect, knew the shape, wrote a suite to pin it, and
# still shipped two fresh instances inside that suite. Vigilance has been tried.
#
# ---------------------------------------------------------------------------
# WHAT IS ASSERTED WHERE
#
#   AC-1  a pipeline into an early-exit reader, in a pipefail file, whose status
#         is READ, is reported with its file and line. Three controls, each with
#         an in-file positive beside it so that "not reported" cannot be
#         satisfied by the file never having been scanned:
#           * the same pipeline in a file with no pipefail   (n_nopipefail.sh)
#           * readers that always drain                      (p_readers.sh 19-26)
#           * status discarded into a command substitution   (n_discard.sh)
#   AC-2  grep -q, grep -m, grep -l, grep -L and head, in the flag spellings the
#         real tree actually uses (-qF, -qE, -qx, -Eq, -m1, -oE -m1, -Eom1).
#   AC-3  the guard enumerates through scripts/classify.sh, not a private tree
#         walk, and sees an uncommitted file. The control replaces classify.sh in
#         a throwaway fixture with a stub that emits ONE path: a guard that walks
#         the tree itself reports nine files and twenty-three findings there.
#   AC-6  `# sigpipe-ok: <reason>` suppresses; a marker with no reason does not.
#   C-2   the trap. A pipeline that is the last command of a FUNCTION BODY, in
#         the one-line brace form and the multi-line form. There is no `if`, no
#         `||` and no `!` on those lines, and all five historical instances are
#         that shape - a rule that scans for a conditional passes on every defect
#         this story was filed for.
#   C-3   the scanned population is the one classify.sh returns, with a floor;
#         pipefail is resolved THROUGH `source`; and a quoted heredoc body is
#         data. The last two were found during RED and are not in the story as
#         filed - see the port note. FIFTEEN files here set no pipefail of
#         their own and inherit it from _lib.sh, every one a suite under
#         .claude/tests, and one of them is lib.test.sh, where the live instance
#         in this tree was found: a guard reading only each file own text scans
#         19 of 36 files and cannot see it.
#   C-5   the twelve status-discarded lines in the REAL tree are excluded BY THE
#         RULE. Each is checked for freshness first, so a drifted line number
#         fails loudly instead of making the exclusion assertion vacuous.
#   C-7   the guard cannot pass by matching nothing: every count is exact.
#   WORLD-090  a comment after a function's brace - `f() { ...; }   # x`,
#         `f() {   # x` and `}   # x` - no longer hides the body from the rule.
#         Where a comment begins is the masker's answer, not a private one: a
#         `#` inside quotes, after `$` or after `{` is not one. The marker pair
#         (a reason / no reason) is asserted on the newly visible one-line
#         form, in one file with an exact census, so AC-6 cannot go vacuous
#         there again - which is how this gap was found in the first place.
#
#   AC-4 and AC-5 are NOT here. Both are in the story's ## Deferred
#   verifications with owner GATES: AC-4 needs the guard to exist before the five
#   historical instances can be reintroduced through scripts/mutate.sh, and AC-5
#   needs it wired. See the handoff.
#
# ---------------------------------------------------------------------------
# WHERE THE PROBES LIVE, AND WHY NOT IN THIS TREE
#
# A probe file deliberately contains the offending shape. Written into this
# repository it would be found by the guard's own real-tree scan, and the tree
# could never come out clean (AC-4). paths.conf's `__probe_` convention does not
# help here: `.claude/**` matches the `harness` rule FIRST, so a probe under
# .claude/tests classifies as harness, which is exactly the category the guard
# scans. So every probe is generated into a THROWAWAY GIT FIXTURE - a temp repo
# with the real scripts/ and .claude/hooks/ copied in, per make_project_fixture -
# and the guard is run there, scoped by pathspec to the probe directory.
#
# This file is itself a shell file under .claude/, so the guard scans it, and its
# heredocs below contain pipeline-shaped text. It is not reported, and that is
# the rule working rather than a technicality: this file does not set pipefail
# (_lib.sh does, at source time, which is not a property of this file's text).
# That is AC-1's first control applied to the suite itself, and it is asserted.
#
# HOUSE RULE FOR THIS FILE: no assertion in it may read the status of a pipeline
# into an early-exit reader. Counting is done with awk over a here-string, which
# drains by nature and opens no pipe at all. WORLD-084 shipped this very bug
# twice inside the suite written to fix it.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

GUARD_REL="scripts/check-sigpipe.sh"
GUARD="$REPO_ROOT/$GUARD_REL"
SELF_REL=".claude/tests/sigpipe.test.sh"

# --- instruments -------------------------------------------------------------
# awk over a here-string: one process, no pipe, nothing to be killed by SIGPIPE.
# index($0,p)==1 is a true anchored prefix match - a floating substring would let
# a finding for some other file satisfy an assertion about this one.

count_prefix() { # <haystack> <literal prefix> -> count of lines starting with it
  awk -v p="$2" 'index($0, p) == 1 { n++ } END { print n + 0 }' <<< "$1"
}

count_substr() { # <haystack> <literal substring> -> count of lines containing it
  awk -v p="$2" 'index($0, p) > 0 { n++ } END { print n + 0 }' <<< "$1"
}

# shell_files   The harness shell files classify.sh lists, one per line.
shell_files() {
  awk '/\.sh$/ { print }' <<< "$(bash "$REPO_ROOT/scripts/classify.sh" --list harness)"
}

# lines_for <haystack> <file>  -> the line numbers the guard reported for <file>,
# space separated and in the order reported, from findings of the form
# `<path>:<line>:...`.
lines_for() {
  awk -v f="$2" 'BEGIN { ORS = "" }
    index($0, f ":") == 1 {
      rest = substr($0, length(f) + 2)
      n = rest + 0
      if (n > 0) { out = out sep n; sep = " " }
    }
    END { print out }' <<< "$1"
}

GUARD_OUT=""; GUARD_RC=0
run_guard() { # <root> [pathspec...]
  local root="$1"; shift
  GUARD_OUT="$(cd "$root" && bash "$root/$GUARD_REL" "$@" 2>&1)"
  GUARD_RC=$?
}

# assert_flagged <label> <file> <expected line numbers, space separated>
assert_flagged() {
  assert_eq "$1" "$3" "$(lines_for "$GUARD_OUT" "$2")"
}

# --- the probe corpus --------------------------------------------------------
# Line numbers below are load-bearing: every assertion names them. Each heredoc
# is written so that the FIRST line of the file is the shebang.

write_probes() { # <fixture root>
  local d="$1/scripts/probes"
  mkdir -p "$d"

  # AC-1 positive, bucket 1 (status read on the spot).  FLAG: 4
  cat > "$d/p_if_grep_q.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

if printf 'alpha\nbeta\n' | grep -q alpha; then
  echo yes
fi
SH

  # AC-2: every early-exit reader, in the flag spellings the real tree uses,
  # then the drain controls.  FLAG: 4-17.  NOT: 3, 18, 19-26.
  cat > "$d/p_readers.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
# AC-2 readers. Flag spellings taken from gates.sh and check-boundaries.sh.
if printf 'a\n' | grep -q a; then echo r04; fi
if printf 'a\n' | grep -qF -- a; then echo r05; fi
if printf 'a\n' | grep -qE 'a'; then echo r06; fi
if printf 'a\n' | grep -qx -- a; then echo r07; fi
if printf 'a\n' | grep -Eq -- 'a'; then echo r08; fi
if printf 'a\n' | grep -m 1 a; then echo r09; fi
if printf 'a\n' | grep -m1 a; then echo r10; fi
if printf 'a\n' | grep -oE -m1 -- 'a'; then echo r11; fi
if printf 'a\n' | grep -Eom1 -- 'a'; then echo r12; fi
if printf 'a\n' | grep -l a /dev/null; then echo r13; fi
if printf 'a\n' | grep -L a /dev/null; then echo r14; fi
if printf 'a\n' | head -1; then echo r15; fi
if printf 'a\n' | head; then echo r16; fi
if printf 'a\n' | head -n 5; then echo r17; fi
# AC-1 control: readers that always drain. The rule must not become "no pipes".
if printf 'a\n' | grep -c a; then echo d19; fi
if printf 'a\n' | grep -v b; then echo d20; fi
if printf 'a\n' | tr a b; then echo d21; fi
if printf 'a\n' | wc -l; then echo d22; fi
if printf 'a\n' | sed -n '1p'; then echo d23; fi
if printf 'a\n' | awk '{ print }'; then echo d24; fi
if printf 'a\n' | sort; then echo d25; fi
if printf 'a\n' | cat; then echo d26; fi
SH

  # C-2, one-line brace form. THE historical shape: no if, no ||, no !.
  # FLAG: 5.  NOT: 4 (no early-exit reader), 7 (grep -c drains).
  cat > "$d/p_fn_oneline.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

strip_comments() { sed 's/#.*//'; }
has_content() { strip_comments | grep -q '[^[:space:]]'; }

drains() { strip_comments | grep -c '[^[:space:]]'; }
SH

  # C-2, multi-line function form.  FLAG: 6.  NOT: 11 (grep -c drains).
  cat > "$d/p_fn_multiline.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

has_pasted_output() {
  local body="$1"
  printf '%s\n' "$body" | grep -qE 'fence'
}

counts() {
  local body="$1"
  printf '%s\n' "$body" | grep -cE 'fence'
}
SH

  # AC-1 control 1: the SAME pipelines, in a file that does not set pipefail.
  # Line 4 is byte-identical to p_if_grep_q.sh:4 and line 8 is the shape of
  # p_fn_oneline.sh:5, both of which ARE reported. FLAG: nothing.
  cat > "$d/n_nopipefail.sh" <<'SH'
#!/usr/bin/env bash
set -u

if printf 'alpha\nbeta\n' | grep -q alpha; then
  echo yes
fi

has_content() { sed 's/#.*//' | grep -q '[^[:space:]]'; }
SH

  # AC-1 control 3 / C-5: status discarded into a command substitution. These
  # four are transcriptions of real lines in doctor.sh, gates.sh, refresh-
  # harness.sh and check-boundaries.sh. FLAG: 9 only - the in-file positive that
  # proves this file was scanned at all.
  cat > "$d/n_discard.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

hv="$(grep -vE '^#' VERSION 2>/dev/null | head -1)"
BOOTSTRAPPED="$(grep -E '^B=' conf | head -1 | cut -d= -f2-)"
res=$(printf '%s\n' "$x" | sed -nE 's/^r://p' | head -1)
ph_at="$(git show "$c" 2>/dev/null | sed -nE 's/^p://p' | head -1 | tr -d ' ')"

if printf 'a\n' | grep -q a; then echo flagged09; fi
SH

  # A comment is not a pipeline. Both comment lines are transcriptions of real
  # comments in check-boundaries.sh. FLAG: 5 only.
  cat > "$d/n_comment.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
# ONE awk, not `strip_comments | grep -q`. That pipeline had an awk which buffers
#   if printf '%s\n' "$x" | grep -q PATTERN; then
if printf 'a\n' | grep -q a; then echo flagged05; fi
SH

  # AC-6. FLAG: 4 (in-file positive), 6 and 7 (markers naming no reason).
  # NOT: 5 (marker with a reason).
  cat > "$d/m_marker.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

if printf 'a\n' | grep -q a; then echo plain04; fi
if printf 'a\n' | grep -q a; then echo ok05; fi # sigpipe-ok: reviewed, the writer emits a single record
if printf 'a\n' | grep -q a; then echo bare06; fi # sigpipe-ok:
if printf 'a\n' | grep -q a; then echo bare07; fi # sigpipe-ok
SH

  # C-3a: pipefail reached through `source`. THIS IS THE ONE THAT DECIDES AC-4.
  # FIFTEEN files here set no pipefail of their own and inherit it from _lib.sh
  # at source time, every one a suite under .claude/tests - lib.test.sh among
  # them, which is where this tree live instance was found. A guard that reads
  # only the file own text scans nineteen files here instead of thirty-four and
  # cannot detect it at all. lib_pf.sh carries no pipeline
  # of its own, so it contributes a pipefail file and no finding.
  cat > "$d/lib_pf.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

helper() { echo helper; }
SH

  # Sets no pipefail itself; inherits it. The body is the historical shape.
  # FLAG: 4.
  cat > "$d/p_sourced.sh" <<'SH'
#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/lib_pf.sh"

has_content() { sed 's/#.*//' | grep -q '[^[:space:]]'; }
SH

  # C-3b: a quoted heredoc body is data, exactly as a comment is - the principle
  # CLAUDE.md already states for the phase lock. Without it this very suite is
  # reported, because the probe corpus above lives in this file's heredocs, and
  # the tree can never come out clean for AC-4. FLAG: 10 only. NOT 5, 6, 7 -
  # note line 5 would otherwise make this file look like it sets pipefail twice
  # and lines 6-7 like two defects.
  cat > "$d/n_heredoc.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

cat > /dev/null <<'INNER'
set -uo pipefail
if printf 'a\n' | grep -q a; then echo inside06; fi
has_content() { sed 's/#.*//' | grep -q x; }
INNER

if printf 'a\n' | grep -q a; then echo flagged10; fi
SH

  # C-2 again, as the real gates.sh work_count: a backslash-continued pipeline
  # that is the last command of a function. Kept in its OWN directory so that
  # the corpus above can assert an exact total - which line of a continued
  # pipeline the guard names is left to GREEN.
  mkdir -p "$1/scripts/probes-multiline"
  cat > "$1/scripts/probes-multiline/p_fn_continuation.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

work_count() {
  cat "$1" \
    | grep -oE -m1 -- "$2" 2>/dev/null | head -1 \
    | grep -oE '[0-9]+' 2>/dev/null | head -1
}
SH
}

# =============================================================================
describe "the guard exists and is runnable"

if [ -f "$GUARD" ]; then
  _ok "$GUARD_REL exists"
else
  _bad "$GUARD_REL exists" "no such file: $GUARD_REL
This is the RED failure: the guard has not been written yet. Every assertion
below depends on it and fails with 127 / empty output until it exists."
fi

# =============================================================================
# The probe corpus, in a throwaway fixture. AC-1, AC-2, AC-6, C-2, C-7.
# =============================================================================
FIX="$(make_project_fixture)"
write_probes "$FIX"
git -C "$FIX" add scripts/probes >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm probes >/dev/null 2>&1

# AC-3's control: written AFTER the commit and never added, so `git ls-files
# --others --exclude-standard` is the only thing that can find it.
cat > "$FIX/scripts/probes/u_untracked.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

if printf 'a\n' | grep -q a; then echo untracked04; fi
SH

run_guard "$FIX" scripts/probes

describe "C-7: the guard reports an exact census, so it cannot pass by matching nothing"

# Twelve shell files, eleven of them under pipefail, twenty-five findings:
#   p_if_grep_q 1 + p_readers 14 + p_fn_oneline 1 + p_fn_multiline 1
#   + n_nopipefail 0 + n_discard 1 + n_comment 1 + m_marker 3 + u_untracked 1
#   + lib_pf 0 + p_sourced 1 + n_heredoc 1
# Only n_nopipefail.sh is outside pipefail: p_sourced.sh reaches it through
# `source`, so a guard reading only each file's own text scores 10 and 24 here.
assert_eq "C-7: the summary line names the exact census of the probe corpus" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'check-sigpipe: scanned 12 shell file(s), 11 with pipefail, 25 finding(s)')"

assert_eq "C-7: and it exits non-zero when it has findings" "1" "$GUARD_RC"

describe "AC-1: a pipeline into an early-exit reader whose status is read is named, with its line"

assert_flagged "AC-1: the file and line of a pipeline under an if" \
  scripts/probes/p_if_grep_q.sh "4"

describe "AC-1 control 1: the same pipeline in a file that does not set pipefail is not reported"

# Paired: n_nopipefail.sh:4 is byte-identical to p_if_grep_q.sh:4, which IS
# reported above. Absence here is the pipefail condition, not a missed scan.
assert_flagged "AC-1 control: nothing at all is reported for a file without pipefail" \
  scripts/probes/n_nopipefail.sh ""

describe "AC-1 control 3: a pipeline whose status is discarded is not reported"

assert_flagged "AC-1 control: four command-substitution assignments are not reported, and the plain pipeline beside them is" \
  scripts/probes/n_discard.sh "9"

describe "AC-2: every early-exit reader, in the flag spellings the real tree uses"

# AC-1 control 2 rides here: 19-26 are the draining readers, absent from the
# same line set that carries 4-17. One file, so the control cannot be satisfied
# by the file having been skipped.
assert_flagged "AC-2: grep -q/-qF/-qE/-qx/-Eq, grep -m/-m1/-oE -m1/-Eom1, grep -l, grep -L, head/-1/-n are reported and eight draining readers are not" \
  scripts/probes/p_readers.sh "4 5 6 7 8 9 10 11 12 13 14 15 16 17"

describe "AC-1 control: a comment that contains the shape is not a pipeline"

assert_flagged "AC-1 control: two commented-out pipelines are not reported, and the live one beside them is" \
  scripts/probes/n_comment.sh "5"

describe "C-2: the trap - a pipeline that is the last command of a function body"

# There is no if, no ||, no ! on either line. All five historical instances are
# this shape; a rule that scans for a conditional passes on every one of them.
assert_flagged "C-2: the one-line brace form f() { writer | grep -q X; } is reported" \
  scripts/probes/p_fn_oneline.sh "5"

assert_flagged "C-2: the multi-line function form is reported, and its draining twin is not" \
  scripts/probes/p_fn_multiline.sh "6"

describe "C-3: pipefail reached through source - the condition AC-4 turns on"

# lib.test.sh held this tree live instance, sets no pipefail of its own, and
# inherits it from _lib.sh. Fifteen files in this repository are in that
# position, all of them suites. A guard reading only each file own text misses
# every one of them, and with them the instance this port found.
assert_flagged "C-3: a file that sets no pipefail itself but sources one that does is scanned, and its function-body pipeline reported" \
  scripts/probes/p_sourced.sh "4"

assert_flagged "C-3 control: the sourced library itself carries no pipeline and is not reported" \
  scripts/probes/lib_pf.sh ""

describe "C-3: a quoted heredoc body is data, not code"

# Without this the probe corpus in THIS file's heredocs is reported against the
# real tree and AC-4's clean tree is unreachable for as long as this suite
# exists. n_heredoc.sh:5 is a `set -uo pipefail` inside the heredoc and 6-7 are
# two offending pipelines inside it; line 10 is the live one beside them.
assert_flagged "C-3: pipelines inside a quoted heredoc are not reported, and the live one beside them is" \
  scripts/probes/n_heredoc.sh "10"

describe "C-2: a backslash-continued pipeline as a function's last command (the real gates.sh work_count)"

run_guard "$FIX" scripts/probes-multiline
CONT_LINES="$(lines_for "$GUARD_OUT" scripts/probes-multiline/p_fn_continuation.sh)"
CONT_BAD=""
for _l in $CONT_LINES; do
  case "$_l" in 5|6|7) ;; *) CONT_BAD="$CONT_BAD $_l" ;; esac
done
if [ -n "$CONT_LINES" ] && [ -z "$CONT_BAD" ]; then
  _ok "C-2: a continued pipeline as a function's last command is reported, on one of its own lines"
else
  _bad "C-2: a continued pipeline as a function's last command is reported, on one of its own lines" \
    "expected at least one reported line, all within 5-7
reported: '${CONT_LINES:-<none>}'${CONT_BAD:+  out of range:$CONT_BAD}
guard output:
$GUARD_OUT"
fi

describe "AC-6: the escape hatch, and the reason it must carry"

run_guard "$FIX" scripts/probes
assert_flagged "AC-6: a marker naming a reason suppresses the finding; a marker with no reason does not, and the unmarked line beside them is still reported" \
  scripts/probes/m_marker.sh "4 6 7"

describe "AC-3: an uncommitted file is still scanned"

assert_flagged "AC-3 control: a file added and never committed is scanned and reported" \
  scripts/probes/u_untracked.sh "4"

# =============================================================================
# AC-3: the enumeration goes THROUGH classify.sh. A second fixture, because the
# control destroys classify.sh.
# =============================================================================
describe "AC-3: the guard enumerates through scripts/classify.sh rather than walking the tree"

FIX2="$(make_project_fixture)"
write_probes "$FIX2"
git -C "$FIX2" add scripts/probes >/dev/null 2>&1
git -C "$FIX2" -c user.email=t@t -c user.name=t commit -qm probes >/dev/null 2>&1

# A stub that answers every question with ONE path. A guard that walks the tree
# itself is untouched by this and reports nine files and twenty-three findings.
cat > "$FIX2/scripts/classify.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' 'scripts/probes/p_if_grep_q.sh'
SH

run_guard "$FIX2" scripts/probes
assert_eq "AC-3: replacing classify.sh with a stub that emits one path makes the guard scan exactly that one file" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'check-sigpipe: scanned 1 shell file(s), 1 with pipefail, 1 finding(s)')"

assert_flagged "AC-3: and it reports only the file the stub named" \
  scripts/probes/p_if_grep_q.sh "4"

assert_flagged "AC-3 control: the other probes are invisible once classify.sh stops naming them" \
  scripts/probes/p_readers.sh ""

# =============================================================================
# The real tree. C-3, C-5.
# =============================================================================
describe "C-3: the scanned population is the one classify.sh returns"

run_guard "$REPO_ROOT"
REAL_OUT="$GUARD_OUT"

# The file count is computed here rather than hard-coded, because this suite and
# the guard are themselves harness shell files: the population grows by one when
# each lands. The instrument is deliberately trivial - classify.sh plus a suffix
# test - so that it shares nothing with the guard's rule.
EXPECTED_FILES="$(awk 'END { print NR + 0 }' <<< "$(shell_files)")"

if [ "$EXPECTED_FILES" -ge 36 ]; then
  _ok "C-3 floor: classify.sh still returns at least 36 harness shell files"
else
  _bad "C-3 floor: classify.sh still returns at least 36 harness shell files" \
    "measured 2026-09-17 on agentic-dev-harness: 34, plus this suite and the guard = 36
now: $EXPECTED_FILES
A guard written against the 'test' category scans ZERO files and passes forever:
'classify.sh --list test .claude/tests' returns nothing at all."
fi

assert_eq "C-3: the guard scans exactly the harness shell files classify.sh lists" \
  "1" "$(count_prefix "$REAL_OUT" \
        "check-sigpipe: scanned $EXPECTED_FILES shell file(s), ")"

# AND ZERO FINDINGS, which this suite did not assert until release 37. It
# checked the file count and the pipefail count but never the finding count, so
# a new instance in this tree would pass `bash scripts/selftest.sh` and be
# caught only by the CI step - and that step is the one a consuming project has
# to add by hand, because .github/workflows is project-owned. The guard failing
# a PR was the whole point; a guard whose suite cannot fail is half of one.
assert_eq "C-3: and the real tree has no findings at all" \
  "0" "$(awk 'index($0, "check-sigpipe: scanned ") == 1 {
                i = index($0, "pipefail, "); if (i == 0) next
                print substr($0, i + 10) + 0; exit }' <<<"$REAL_OUT")"
assert_eq "C-3: so the guard exits 0 against it" "0" "$GUARD_RC"

# The pipefail count is asserted as a FLOOR rather than an equality, because
# resolving it is the guard's own rule (it has to follow `source`) and an
# independent instrument here would just be a second copy of that rule. The
# floor is the number that discriminates: 34 of the 36 files are under pipefail
# once _lib.sh is followed, and only 19 are if it is not. A guard reading each
# file's own text scores 19 and fails this hard. The fixture above pins the
# semantics exactly, at 11 of 12.
REAL_PF="$(awk 'index($0, "check-sigpipe: scanned ") == 1 {
  i = index($0, "file(s), "); if (i == 0) next
  print substr($0, i + 9) + 0; exit
}' <<< "$REAL_OUT")"

if [ -n "$REAL_PF" ] && [ "$REAL_PF" -ge 34 ]; then
  _ok "C-3: and it resolves pipefail through source, reaching at least 34 of them"
else
  _bad "C-3: and it resolves pipefail through source, reaching at least 34 of them" \
    "reported: '${REAL_PF:-<no summary line>}', expected at least 34
19 means the guard read only each file's own text. FIFTEEN files here set no
pipefail of their own and inherit it from _lib.sh, every one a suite under
.claude/tests - lib.test.sh among them, which is where the live instance in this
tree was found. A guard scoring 19 cannot see it at all."
fi
describe "C-5: the twelve status-discarded lines in this tree are excluded by the rule, not by markers"


# Freshness first. An exclusion assertion about a line number that has drifted
# is vacuous, and vacuous is the failure mode this whole story is about: if the
# line no longer holds the shape, this fails as a stale fixture rather than
# reporting the guard correct.
DISCARDED='scripts/check-boundaries.sh:394:res=$(printf
scripts/check-boundaries.sh:433:rec=$(printf
scripts/check-boundaries.sh:608:ph_at="$(git show
scripts/ci-local.sh:169:dirty="$(git status
scripts/doctor.sh:68:v="$(grep
scripts/doctor.sh:140:BOOTSTRAPPED="$(grep
scripts/gates.sh:74:BOOTSTRAPPED="$(grep
scripts/gates.sh:580:why="could not launch: $(
scripts/refresh-harness.sh:134:ph="$(sed
scripts/refresh-harness.sh:135:sid="$(sed
scripts/refresh-harness.sh:147:upstream_version="$(grep
scripts/refresh-harness.sh:148:current_version="$(grep'

stale=""; flagged=""; checked=0
while IFS= read -r spec; do
  [ -n "$spec" ] || continue
  f="${spec%%:*}"; rest="${spec#*:}"; ln="${rest%%:*}"; needle="${rest#*:}"
  checked=$((checked+1))
  actual="$(awk -v n="$ln" 'NR == n { print; exit }' "$REPO_ROOT/$f")"
  if [ "$(count_substr "$actual" "$needle")" != "1" ]; then
    stale="$stale
  $f:$ln no longer holds [$needle] - it holds: $actual"
    continue
  fi
  if [ "$(count_prefix "$REAL_OUT" "$f:$ln:")" != "0" ]; then
    flagged="$flagged
  $f:$ln"
  fi
done <<< "$DISCARDED"

assert_eq "C-5 freshness: all twelve status-discarded lines are still where this suite says they are" \
  "12 lines, none stale" "$checked lines,${stale:- none stale}"

assert_eq "C-5: and the guard reports none of them" \
  "none flagged" "${flagged:-none flagged}"

describe "C-3: the heredoc rule, applied to this suite itself"

# This file is a harness shell file that sources _lib.sh, so the guard scans it
# AND treats it as under pipefail. Its probe corpus above sits in quoted
# heredocs and contains nine `set -uo pipefail` lines and a dozen pipelines into
# grep -q. Nothing in it may be reported, and the only thing that can deliver
# that is the heredoc rule - which is why n_heredoc.sh exists. Paired with the
# membership assertion below, so that "reports nothing" cannot be satisfied by
# the file never having been enumerated.
assert_eq "C-3: this suite is in the scanned population" \
  "1" "$(count_prefix "$(shell_files)" "$SELF_REL")"

assert_flagged "C-3: and the guard reports nothing in it, because its probe corpus lives in quoted heredocs" \
  "$SELF_REL" ""

# =============================================================================
# C-11 - QUOTED TEXT IS DATA. Added during the port to agentic-dev-harness.
#
# The rule reads shell text, and the first port read it RAW. That was wrong in
# both directions and both were live in this repository:
#
#   * FALSE POSITIVE - `echo "run: cat x | head -1"` reported as a defect. A
#     guard's entire value is being believed when it says a tree is clean, and
#     this one complained about prose.
#   * FALSE NEGATIVE - to find a one-line function's last command the body is
#     split on `;`, and a QUOTED `;` took the split with it. `has_operator()` in
#     .claude/tests/lib.test.sh is exactly that shape - a REAL instance of the
#     defect this guard exists for - and it scored clean.
#
# CLAUDE.md already states the rule for the phase lock: quoted arguments and
# heredoc bodies are data, not syntax. The guard honoured the heredoc half and
# reimplemented the rest. It now reads through `mask_shell_quotes`, which
# rules.md requires: a test that needs this answer asks for it.
#
# THE MASK IS NOT LINE-PRESERVING, which is why `unfold` exists and why the
# fixture below opens with three continuations. mask_shell_quotes folds a
# backslash-continued line and encodes the newline as \010; measured on this
# tree, lib.test.sh is 405 lines and masks to 348 carrying 57 of them. A guard
# that reports line numbers cannot use it that way - before `unfold`, this
# tree's one live finding was reported 44 lines above itself, which is worse
# than not reporting it: it sends a reader to an innocent line.
# =============================================================================
describe "C-11: quoted text is data, and the line numbers survive the mask"

Q11="$(make_project_fixture)"
mkdir -p "$Q11/scripts/probes"
cat > "$Q11/scripts/probes/q_quotes.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
# THREE continuations, folded to one line by the mask. Everything below shifts
# up by three unless unfold puts them back - so every number in this file is an
# assertion about the round trip as well as about the rule.
A=$(echo one \
  two \
  three \
  four)
# Quoted text that reads like a pipeline into an early-exit reader. NOT code.
q_double() { echo "run: cat x | head -1"; }
q_single() { echo 'usage: foo | grep -q bar'; }
# The same words unquoted: a real pipeline, and the positive beside the
# controls, so "not reported" cannot be satisfied by the file going unscanned.
real_head() { cat x | head -1; }
# A one-line body holding a QUOTED `;` before its real last command.
quoted_semi() { printf '%s' "$1" | grep -qE '[|&;<>]'; }
SH
run_guard "$Q11" scripts/probes

# 15 and 17 ONLY. 11 and 12 are prose inside quotes; 6-9 are the continuation
# group. Verified to discriminate in both directions:
#   * `| unfold` -> `| cat` reports these at 12 and 14 - three lines high,
#     exactly the three folded continuations, pointing a reader at innocent
#     lines. That is the whole reason unfold exists.
#   * reading the file raw instead of through the mask reports 11 and 12 and
#     misses 17.
assert_flagged "C-11: quoted text is not reported, the real pipeline beside it is, a quoted semicolon no longer hides a function's last command, and the line numbers survive the fold" \
  "scripts/probes/q_quotes.sh" "15 17"

# The exact census, so none of the above can pass by the file going unscanned -
# and so that a guard broken outright cannot pass here. It can be: during this
# port a mis-edit left check-sigpipe.sh unable to resolve its own rule, and it
# printed `0 finding(s)` and exited 0 while doing nothing whatsoever.
assert_eq "C-11: and the guard scanned the file it was reporting on" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'check-sigpipe: scanned 1 shell file(s), 1 with pipefail, 2 finding(s)')"

# The marker is read from the RAW file, and its line numbers have to line up
# with the UNFOLDED stream. Both halves are load-bearing and neither is obvious:
# mask_shell_quotes masks the spaces inside a comment body, so a marker matched
# against masked text stops suppressing; and it folds continuations, so a marker
# found in the folded stream carries the wrong number. Either way every marked
# line in every consuming project silently starts reporting again.
#
# THE MARKER SITS ON AN `if`, and that is a choice rather than a leftover. What
# this probe pins is the FOLD: a marker's line number, computed from the raw
# file, has to survive the three continuations above it, and bucket 1 is the
# shape with nothing else in the way - a failure here can only be the fold.
# The marker on a one-line FUNCTION, `f() { cmd | grep -q x; }   # sigpipe-ok:
# ...`, is pinned in the WORLD-090 block below instead, as a PAIR with the same
# function carrying a reasonless marker. Until WORLD-090 that shape was invisible
# to the rule with or without a marker - the one-line test required the line to
# END in `}` - so this assertion, first written on it, passed while pinning
# nothing. That is how the gap was found, and why the pair is the only honest
# way to assert a marker on a shape the rule has only just learned to see.
cat > "$Q11/scripts/probes/q_marked.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
B=$(echo one \
  two \
  three)
if cat x | head -1; then echo a; fi   # sigpipe-ok: measured, the writer emits one line
if cat x | head -1; then echo b; fi
SH
run_guard "$Q11" scripts/probes/q_marked.sh
# Verified to discriminate: computing the marks from the masked stream instead
# of the raw file reports 6 as well.
assert_flagged "C-11: a marker after a continuation still suppresses its own line, and the unmarked line below it is still reported" \
  "scripts/probes/q_marked.sh" "7"

# =============================================================================
# WORLD-090 - A COMMENT AFTER A BRACE DOES NOT HIDE THE FUNCTION.
#
# The rule recognised a one-line function by the line ENDING in `}`, an opener
# by the line ending in `{`, and a closer by the line BEING `}`. A comment after
# the brace defeated all three:
#
#     g() { cat "$1" | grep -q x; }   # anything at all   -> not reported
#     f() {   # anything at all                           -> body never entered
#
# The first is a genuine bucket-2 defect scored clean, and it was found by a
# vacuous assertion: a marker probe written on that shape "passed" because
# nothing was ever going to be reported there (see q_marked.sh above). The rule
# now reads the CODE part of the masked line - everything before the `#` that
# begins a comment - in the three structural brace tests and in the one-line
# body extraction.
#
# WHERE A COMMENT BEGINS IS THE MASKER'S DECISION, not a private quote parser.
# mask_shell_quotes has already turned every separator inside a quoted span into
# a control character, so in its output a `#` is a comment exactly when it is
# at column 1 or preceded by one of space, tab, `;`, `&`, `|`, `(`. The `#` in
# `echo "a # b"` is preceded by \006 and is code; `$#` and `${#v}` are preceded
# by `$` and `{` and are code. q_hash.sh pins those, with and without a real
# comment behind them.
#
# THE STRIPPED READING IS PREFERRED AND THE RAW LINE IS THE FALLBACK, in that
# order, and q_hash.sh carries one line for each half of that sentence:
#   * `k() { echo a \# b | grep -m1 c; }` - an ESCAPED hash outside quotes. The
#     masker drops the backslash and emits a bare `#`, so in its output this is
#     indistinguishable from a comment, and a rule that strips unconditionally
#     reads the body as `k() { echo a` and reports nothing. The guard as
#     shipped REPORTS this line. It is asserted reported here as a
#     no-regression control - the fallback to the raw line exists because of
#     it, and this assertion is what keeps the fallback there.
#   * `n() { cat "$1" | head -1; }   # see {braces}` - a comment that ENDS in
#     a brace, so the raw line ends in `}` too. A rule that tried the raw line
#     first would take the whole comment as the body, split it on a masked `;`
#     and report nothing. Asserted reported, which only the stripped-first
#     order delivers.
#
# q_trailing.sh is the story's C-8 table line for line, so the expected column
# here is the measured column there. Every run is scoped to ONE file and asserts
# the exact census, so no "not reported" below can be met by the file going
# unscanned - a guard broken outright prints `0 finding(s)` and exits 0.
# =============================================================================
describe "WORLD-090: a one-line function whose line ends in a comment is still a one-line function"

# Lines 3-9 are C-8's lines 3-9. FLAG: 3, 4 (commentless controls, reported
# before and after), 5 (the miss this story closes), 8 (a marker with no reason
# on the same shape - the pair that makes line 7 mean something).
# NOT: 6 (cut drains, comment or no comment), 7 (marker with a reason), 9 (the
# shape as TEXT in a comment - the masker holding, not new code).
cat > "$Q11/scripts/probes/q_trailing.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
f_quoted_semi() { cat "$1" | grep -qE '[a;b]'; }
f_plain()       { cat "$1" | grep -qE '[ab]'; }
g()             { cat "$1" | grep -q x; }   # trailing cmt
h()             { cat "$1" | cut -f1; }     # trailing cmt
marked()        { cat "$1" | grep -q x; }   # sigpipe-ok: reviewed, the writer emits one record
nomark()        { cat "$1" | grep -q x; }   # sigpipe-ok:
# a comment that names cat x | grep -q y as text
SH
run_guard "$Q11" scripts/probes/q_trailing.sh

assert_flagged "WORLD-090 AC-1: a one-line function whose line ends in a comment is reported beside the commentless forms; its draining twin, the marker with a reason, and the shape as comment text are not" \
  "scripts/probes/q_trailing.sh" "3 4 5 8"

# AC-1's "same message and line number": the whole finding line, anchored.
assert_eq "WORLD-090 AC-1: and the finding carries the same message as the commentless form, on the function's own line" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'scripts/probes/q_trailing.sh:5: pipeline into an early-exit reader under pipefail; the writer can be killed by SIGPIPE and 141 becomes the status this line is judged by')"

# AC-2's pair. Line 7 unreported proves nothing on its own - it was unreported
# before this story too, for the wrong reason. Line 8 REPORTED is what shows the
# marker on line 7 is doing the suppressing.
assert_eq "WORLD-090 AC-2: a marker with NO reason on the newly visible one-line form is reported - the pair that makes the marked line beside it mean something" \
  "1" "$(count_prefix "$GUARD_OUT" 'scripts/probes/q_trailing.sh:8:')"

assert_eq "WORLD-090 C-8: the census is exact - one file scanned, four findings, so neither absence above is an unscanned file" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'check-sigpipe: scanned 1 shell file(s), 1 with pipefail, 4 finding(s)')"

describe "WORLD-090: where a comment begins is the masker's answer - a hash in quotes, after \$ or after { is code"

# FLAG: 4 (a quoted `#`, no comment - reported before and after, the control
# that a comment stripper reading raw `#` cannot pass), 5, 6, 7, 8 (the same
# with a genuine comment behind each), 9 (the escaped hash - reported by the
# guard as shipped, lost by an unconditional strip: the fallback's control),
# 11 (a comment ending in a brace: the stripped-first order's control).
# NOT: 3 (cut drains, no comment - AC-1's "with and without" control, paired
# with q_trailing.sh:6), 10 (the escaped hash's draining twin).
cat > "$Q11/scripts/probes/q_hash.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
h_plain()       { cat "$1" | cut -f1; }
quoted_hash()   { echo "a # b" | grep -q c; }
quoted_hash_c() { echo "a # b" | grep -q c; }   # trailing cmt
argc()          { echo $# | grep -q 1; }        # trailing cmt
lenv()          { echo ${#v} | grep -q 1; }     # trailing cmt
sq_hash()       { echo 'a # b' | grep -q c; }   # trailing cmt
k()             { echo a \# b | grep -m1 c; }
m()             { echo a \# b | cut -f1; }
n()             { cat "$1" | head -1; }   # see {braces}
SH
run_guard "$Q11" scripts/probes/q_hash.sh

assert_flagged "WORLD-090 C-3: a hash inside double quotes, inside single quotes, after \$ or after { does not begin a comment, with and without a real comment behind it; the draining one-liner beside them is not reported" \
  "scripts/probes/q_hash.sh" "4 5 6 7 8 9 11"

# The no-regression control on its own, so that a strip with no fallback - the
# first prototype, and the obvious implementation - fails by name.
assert_eq "WORLD-090 C-4: an escaped hash outside quotes, which the masker cannot tell from a comment, is still reported - the raw-line fallback holds" \
  "1" "$(count_prefix "$GUARD_OUT" 'scripts/probes/q_hash.sh:9:')"

# The order on its own: a comment ending in a brace makes the raw line end in
# `}`; only stripped-before-raw reports the function under it.
assert_eq "WORLD-090 C-4: a comment that ends in a brace does not become the function's body - the stripped reading is tried before the raw one" \
  "1" "$(count_prefix "$GUARD_OUT" 'scripts/probes/q_hash.sh:11:')"

assert_eq "WORLD-090 C-3: the census is exact - one file scanned, seven findings" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'check-sigpipe: scanned 1 shell file(s), 1 with pipefail, 7 finding(s)')"

describe "WORLD-090: a multi-line function whose opening or closing brace carries a comment is still entered and left"

# C-2 items 2 and 3. FLAG: 6 (opener carries a comment), 11 (closer carries a
# comment - without which the body is never closed, and the NEXT function's
# opener discards this one's last command), 20 (plain, the in-file positive).
# NOT: 16 (both braces commented, grep -c drains).
cat > "$Q11/scripts/probes/q_opener.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

opener_cmt() {   # the opening brace carries a comment
  local body="$1"
  printf '%s\n' "$body" | grep -qE 'fence'
}

closer_cmt() {
  local body="$1"
  printf '%s\n' "$body" | grep -qE 'fence'
}   # the closing brace carries a comment

drains_cmt() {   # the opening brace carries a comment
  local body="$1"
  printf '%s\n' "$body" | grep -cE 'fence'
}   # and so does the closing one

plain_ml() {
  printf '%s\n' "$1" | grep -qE 'fence'
}
SH
run_guard "$Q11" scripts/probes/q_opener.sh

assert_flagged "WORLD-090 C-2: a comment after an opening brace or a closing brace does not hide a multi-line function's last-command pipeline, and its draining twin is not reported" \
  "scripts/probes/q_opener.sh" "6 11 20"

assert_eq "WORLD-090 C-2: the census is exact - one file scanned, three findings" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'check-sigpipe: scanned 1 shell file(s), 1 with pipefail, 3 finding(s)')"

rm -rf "$Q11"

# =============================================================================
# AC-7 - the SITES, behaviourally. Added in RED after the story absorbed
# WORLD-085 (amendment A-3).
#
# AC-4 reads shape; this reads behaviour. Each site this story fixes is driven
# with an input of >= 1.5 MB whose match sits on the FIRST line - the earliest
# possible reader exit, so the most still unwritten - and must give the answer
# it gives on a small input. The per-site negative control is the load-bearing
# half and C-10 says why: a site "fixed" by making it unconditionally true
# passes the guard, and only the absent-match case catches that.
#
# HOW EACH SITE IS EXERCISED, AND WHY NOT BY COPYING IT
# Seven of the nine sites are driven through the script's real entry point in a
# throwaway fixture - no extraction, no copy, and nothing that a rewrite can
# invalidate. The two that are function bodies whose callers discard the status
# are driven by cutting the named function out of the shipped file at run time
# and calling it, the WORLD-084 C-11 technique: a pasted copy would be a suite
# that passes forever against code nobody ships. Each extraction asserts the
# definition was found exactly once, so an extraction that produced nothing goes
# red rather than quiet.
# =============================================================================

AC7_MIN=1572864   # 1.5 MiB

# ~64 bytes a line; 25,600 lines clears AC7_MIN with room to spare.
filler() { awk -v n="${1:-25600}" 'BEGIN { for (i = 0; i < n; i++)
  printf "filler %06d abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW\n", i }'; }

big_enough() { # <label> <file>
  local b; b="$(wc -c < "$2")"
  if [ "$b" -ge "$AC7_MIN" ]; then _ok "$1 ($b bytes)"
  else _bad "$1" "fixture is $b bytes, below the $AC7_MIN floor AC-7 requires"; fi
}

# says <haystack> <literal needle> -> 1 or 0. awk, no pipe: this suite may not
# use the construct it is testing.
says() { awk -v p="$2" 'index($0, p) > 0 { n = 1 } END { print n + 0 }' <<< "$1"; }

# extract_fn <file> <name>   The named function's definition, cut out of the
# shipped file. One-line brace form and multi-line form; nothing else is
# assumed about the body, so GREEN may rewrite it freely as long as the name
# survives at column 0.
extract_fn() {
  awk -v f="$2" '
    index($0, f "()") == 1 {
      print; if ($0 ~ /\}[[:space:]]*$/) exit; inb = 1; next }
    inb { print; if ($0 == "}") exit }' "$1"
}

count_defs() { # <file> <name>  - the anchor must occur exactly once
  awk -v f="$2" 'index($0, f "()") == 1 { n++ } END { print n + 0 }' "$1"
}

AC7="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"

# -----------------------------------------------------------------------------
describe "AC-7: scripts/classify.sh - a valid category is still recognised at 1.5 MB"

C7="$(make_project_fixture)"
classify_only() { ( cd "$C7" && bash scripts/classify.sh --only "$1" first/x 2>&1 ); }

# Small first, so the large-input assertions cannot be the first thing that has
# ever run through this path.
printf 'aaaa | first/**\nzzzz | other/**\n' > "$C7/.claude/harness/paths.conf"
assert_eq "AC-7 small: a category that exists is not called unknown" \
  "0" "$(says "$(classify_only aaaa)" 'unknown category')"
assert_eq "AC-7 small control: a category that does not exist is called unknown" \
  "1" "$(says "$(classify_only qqqq)" 'unknown category')"

# 75,001 distinct category names, so `categories` streams past 1.5 MB, and
# `aaaa` sorts first - the earliest possible exit for `grep -qx`.
awk 'BEGIN { printf "aaaa | first/**\n"
  for (i = 0; i < 75000; i++) {
    s = ""; n = i
    for (j = 0; j < 9; j++) { s = sprintf("%c", 98 + (n % 25)) s; n = int(n / 25) }
    printf "z%s | other/**\n", s } }' > "$C7/.claude/harness/paths.conf"
big_enough "AC-7: the classify.sh fixture streams at least 1.5 MB of categories" \
  "$C7/.claude/harness/paths.conf"

assert_eq "AC-7: classify.sh accepts a category sitting on the first line of 1.5 MB of categories" \
  "0" "$(says "$(classify_only aaaa)" 'unknown category')"
assert_eq "AC-7 control: and still rejects one that is genuinely absent from the same 1.5 MB" \
  "1" "$(says "$(classify_only qqqq)" 'unknown category')"

# -----------------------------------------------------------------------------
describe "AC-7: scripts/gates.sh - evidence and blocked-pattern matching at 1.5 MB"

G7="$(make_project_fixture)"
gates7() { ( cd "$G7" && bash scripts/gates.sh --gate unit 2>&1 ); }

write_conf "$G7" <<'EOF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
assert_eq "AC-7 small: a gate whose small log carries the evidence passes" \
  "1" "$(says "$(gates7)" 'PASS         unit')"

write_conf "$G7" <<'EOF'
gate     | unit | required | . | printf 'nothing of interest\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
assert_eq "AC-7 small control: a gate whose small log lacks it reports no evidence" \
  "1" "$(says "$(gates7)" 'no evidence of work')"

# The evidence is the FIRST line of a 1.6 MB log. gates.sh:432.
write_conf "$G7" <<'EOF'
gate     | unit | required | . | awk 'BEGIN { printf "Tests  47 passed (47)\n"; for (i = 0; i < 25600; i++) printf "filler %06d abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW\n", i }'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out7="$(gates7)"
big_enough "AC-7: the gates.sh evidence fixture log is at least 1.5 MB" \
  "$G7/.claude/state/gate-logs/unit.log"
assert_eq "AC-7: a gate whose 1.5 MB log carries the evidence on its first line passes" \
  "1" "$(says "$out7" 'PASS         unit')"
assert_eq "AC-7: and is not reported as having produced no evidence" \
  "0" "$(says "$out7" 'no evidence of work')"

write_conf "$G7" <<'EOF'
gate     | unit | required | . | awk 'BEGIN { for (i = 0; i < 25600; i++) printf "filler %06d abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW\n", i }'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
assert_eq "AC-7 control: a 1.5 MB log with the evidence genuinely absent still reports no evidence" \
  "1" "$(says "$(gates7)" 'no evidence of work')"

# gates.sh:428 - the blocked-pattern check, reached only when the gate failed.
write_conf "$G7" <<'EOF'
gate     | unit | required | . | sh -c 'printf "flimflam: command not found\n"; exit 3'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
assert_eq "AC-7 small: a failing gate whose small log names a launch failure is BLOCKED" \
  "1" "$(says "$(gates7)" 'BLOCKED')"

write_conf "$G7" <<'EOF'
gate     | unit | required | . | sh -c 'awk "BEGIN { printf \"flimflam: command not found\n\"; for (i = 0; i < 25600; i++) printf \"filler %06d abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW\n\", i }"; exit 3'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out7="$(gates7)"
big_enough "AC-7: the gates.sh blocked-pattern fixture log is at least 1.5 MB" \
  "$G7/.claude/state/gate-logs/unit.log"
assert_eq "AC-7: a failing gate whose 1.5 MB log names a launch failure on its first line is BLOCKED" \
  "1" "$(says "$out7" 'BLOCKED')"

write_conf "$G7" <<'EOF'
gate     | unit | required | . | sh -c 'awk "BEGIN { for (i = 0; i < 25600; i++) printf \"filler %06d abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW\n\", i }"; exit 3'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out7="$(gates7)"
assert_eq "AC-7 control: a failing gate whose 1.5 MB log names no launch failure is not BLOCKED" \
  "0" "$(says "$out7" 'BLOCKED')"
assert_eq "AC-7 control: it is reported as a plain failure instead" \
  "1" "$(says "$out7" 'FAIL         unit')"

# -----------------------------------------------------------------------------
describe "AC-7: gates.sh work_count - a function body whose status every caller discards"

# Not reachable through gates.sh: work_count's VALUE is correct at any size (the
# match is found before the writer dies) and its caller takes it through a
# command substitution, which discards the status. The defect is the status
# alone, so the function is cut out of the shipped file and called directly.
GATES_SRC="$REPO_ROOT/scripts/gates.sh"
assert_eq "AC-7: work_count is defined exactly once at column 0 in gates.sh" \
  "1" "$(count_defs "$GATES_SRC" work_count)"
assert_eq "AC-7: and clean_log, which it calls, likewise" \
  "1" "$(count_defs "$GATES_SRC" clean_log)"

{ printf '#!/usr/bin/env bash\nset -uo pipefail\nESC=$(printf "\\033")\n'
  extract_fn "$GATES_SRC" clean_log
  extract_fn "$GATES_SRC" work_count
  printf 'v="$(work_count "$1" "$2")"\n'
  printf 'work_count "$1" "$2" >/dev/null 2>&1; s=$?\n'
  printf 'printf "%%s %%s\\n" "$v" "$s"\n'
} > "$AC7/wc_shim.sh"

printf 'Tests  47 passed (47)\n' > "$AC7/small.log"
{ printf 'Tests  47 passed (47)\n'; filler; } > "$AC7/big.log"
big_enough "AC-7: the work_count fixture log is at least 1.5 MB" "$AC7/big.log"

EV='Tests +[1-9][0-9]* passed'
assert_eq "AC-7 small: work_count returns the count and exits 0" \
  "47 0" "$(bash "$AC7/wc_shim.sh" "$AC7/small.log" "$EV")"
assert_eq "AC-7: work_count returns the same count AND still exits 0 when the match is on the first line of 1.5 MB" \
  "47 0" "$(bash "$AC7/wc_shim.sh" "$AC7/big.log" "$EV")"
assert_eq "AC-7 control: with the evidence genuinely absent from the same 1.5 MB it returns nothing and does not exit 0" \
  "1" "$(says "$(bash "$AC7/wc_shim.sh" "$AC7/big.log" 'no such evidence [0-9]+ anywhere')" ' 1')"

# -----------------------------------------------------------------------------
describe "AC-7: gate-reminder.sh stamp_value - the same shape, in a hook"

REM_SRC="$REPO_ROOT/.claude/hooks/gate-reminder.sh"
assert_eq "AC-7: stamp_value is defined exactly once at column 0 in gate-reminder.sh" \
  "1" "$(count_defs "$REM_SRC" stamp_value)"

{ printf '#!/usr/bin/env bash\nset -uo pipefail\nGATE_STAMP="$2"\n'
  extract_fn "$REM_SRC" stamp_value
  printf 'v="$(stamp_value "$1")"\n'
  printf 'stamp_value "$1" >/dev/null 2>&1; s=$?\n'
  printf 'printf "%%s %%s\\n" "$v" "$s"\n'
} > "$AC7/sv_shim.sh"

printf 'RESULT=pass\nFULL=yes\n' > "$AC7/small.stamp"
# Measured in RED: a realistic stamp has ONE line per key, so the writer emits
# one line and there is nothing left to kill - `grep | head -1` cannot fail
# there at any size. The only input that reaches this site has MANY lines
# matching the key. Adversarial, but it is the shape, and the fix removes it.
awk 'BEGIN { for (i = 0; i < 25600; i++)
  printf "RESULT=pass_%06d_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQR\n", i }' > "$AC7/big.stamp"
big_enough "AC-7: the stamp_value fixture is at least 1.5 MB" "$AC7/big.stamp"

assert_eq "AC-7 small: stamp_value returns the value and exits 0" \
  "pass 0" "$(bash "$AC7/sv_shim.sh" RESULT "$AC7/small.stamp")"
assert_eq "AC-7: stamp_value returns the first value AND still exits 0 at 1.5 MB" \
  "pass_000000_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQR 0" \
  "$(bash "$AC7/sv_shim.sh" RESULT "$AC7/big.stamp")"
assert_eq "AC-7 control: a key genuinely absent from the same 1.5 MB returns nothing and does not exit 0" \
  " 1" "$(bash "$AC7/sv_shim.sh" NOSUCHKEY "$AC7/big.stamp")"

# -----------------------------------------------------------------------------
describe "AC-7: scripts/check-boundaries.sh - the story-section matchers at 1.5 MB"

B7="$(make_project_fixture)"
GATE_MARK='<!-- gates.sh: written by bash scripts/gates.sh; do not edit or paste by hand -->'
git -C "$B7" -c user.email=t@t -c user.name=t branch -M main >/dev/null 2>&1
git -C "$B7" -c user.email=t@t -c user.name=t checkout -q -b story/T-1-fixture >/dev/null 2>&1

b7_run() { ( cd "$B7" && GITHUB_HEAD_REF= PR_HEAD_SHA= bash scripts/check-boundaries.sh main 2>&1 ); }
b7_commit() {
  git -C "$B7" add -A >/dev/null 2>&1
  git -C "$B7" -c user.email=t@t -c user.name=t commit -qm "${1:-wip}" --allow-empty >/dev/null 2>&1
}
b7_story() { cat > "$B7/docs/backlog/stories/T-1.md"; b7_commit; }

b7_head() { # <required_gates value>
  printf -- '---\nid: T-1\ntitle: T\nslug: fixture\ntype: chore\nstatus: in-progress\nphase: REVIEW\nbranch: story/T-1-fixture\ndepends_on: []\nrequired_gates: %s\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n\n' "$1"
}

# --- check-boundaries.sh:323, the gate-marker matcher ---
b7_story <<EOF
$(b7_head '[]')
## Gate results

$GATE_MARK
    result: pass

## Notes
EOF
assert_eq "AC-7 small: a small ## Gate results carrying the marker is accepted" \
  "0" "$(says "$(b7_run)" 'was not written by scripts/gates.sh')"

b7_story <<EOF
$(b7_head '[]')
## Gate results

    result: pass

## Notes
EOF
assert_eq "AC-7 small control: a small one without the marker is refused" \
  "1" "$(says "$(b7_run)" 'was not written by scripts/gates.sh')"

{ b7_head '[]'
  printf '## Gate results\n\n'
  printf '%s\n' "$GATE_MARK"
  printf '    result: pass\n'
  filler
  printf '\n## Notes\n'
} > "$B7/docs/backlog/stories/T-1.md"
b7_commit big-marker
big_enough "AC-7: the check-boundaries gate-marker fixture story is at least 1.5 MB" \
  "$B7/docs/backlog/stories/T-1.md"
assert_eq "AC-7: the marker on the first line of a 1.5 MB ## Gate results is still found" \
  "0" "$(says "$(b7_run)" 'was not written by scripts/gates.sh')"

{ b7_head '[]'
  printf '## Gate results\n\n'
  printf '    result: pass\n'
  filler
  printf '\n## Notes\n'
} > "$B7/docs/backlog/stories/T-1.md"
b7_commit big-nomarker
assert_eq "AC-7 control: a 1.5 MB ## Gate results with the marker genuinely absent is still refused" \
  "1" "$(says "$(b7_run)" 'was not written by scripts/gates.sh')"

# --- check-boundaries.sh:382, the required-gate PASS matcher ---
# The marker is placed LAST here, deliberately: the 323 matcher above has to
# succeed before this one is reached at all, and a marker on the last line
# leaves grep nothing to exit early on. The PASS line is first, which is the
# earliest exit for THIS matcher - the one under test.
{ b7_head '[unit]'
  printf '## Gate results\n\n'
  printf 'PASS         unit (1s)\n'
  filler
  printf '%s\n' "$GATE_MARK"
  printf '\n## Notes\n'
} > "$B7/docs/backlog/stories/T-1.md"
b7_commit big-pass
big_enough "AC-7: the check-boundaries required-gate fixture story is at least 1.5 MB" \
  "$B7/docs/backlog/stories/T-1.md"
assert_eq "AC-7: a PASS line on the first line of a 1.5 MB ## Gate results is still found" \
  "0" "$(says "$(b7_run)" "requires gate 'unit', but the recorded run has no PASS for it")"

{ b7_head '[unit]'
  printf '## Gate results\n\n'
  filler
  printf '%s\n' "$GATE_MARK"
  printf '\n## Notes\n'
} > "$B7/docs/backlog/stories/T-1.md"
b7_commit big-nopass
assert_eq "AC-7 control: a 1.5 MB ## Gate results with no PASS line at all is still refused" \
  "1" "$(says "$(b7_run)" "requires gate 'unit', but the recorded run has no PASS for it")"

# --- check-boundaries.sh:234, the scaffold-inventory matcher ---
mkdir -p "$B7/src"
printf 'export const a = 1\n' > "$B7/src/ac7.ts"
{ b7_head '[]'
  printf '## Scaffold inventory\n\n'
  printf 'src/ac7.ts - configuration, no behaviour\n'
  filler
  printf '\n## Gate results\n\n'
  printf '%s\n' "$GATE_MARK"
  printf '    result: pass\n'
  printf '\n## Notes\n'
} > "$B7/docs/backlog/stories/T-1.md"
b7_commit big-inventory
big_enough "AC-7: the check-boundaries scaffold-inventory fixture story is at least 1.5 MB" \
  "$B7/docs/backlog/stories/T-1.md"
assert_eq "AC-7: a source file named on the first line of a 1.5 MB ## Scaffold inventory is still found" \
  "0" "$(says "$(b7_run)" 'not named in ## Scaffold inventory')"

{ b7_head '[]'
  printf '## Scaffold inventory\n\n'
  filler
  printf '\n## Gate results\n\n'
  printf '%s\n' "$GATE_MARK"
  printf '    result: pass\n'
  printf '\n## Notes\n'
} > "$B7/docs/backlog/stories/T-1.md"
b7_commit big-noinventory
assert_eq "AC-7 control: a 1.5 MB inventory that genuinely omits the file is still refused" \
  "1" "$(says "$(b7_run)" 'not named in ## Scaffold inventory')"

# --- check-boundaries.sh:144, the frontmatter matcher ---
# MEASURED IN RED: this site cannot fail, at any size. Its writer is `head -1`,
# and a line-oriented reader must consume the whole line before it can decide
# the line matched - so `grep -q` never exits early and never kills anything.
# Confirmed at a 2.1 MB first line: PIPESTATUS was `0 0`, not `141 0`. These two
# assertions therefore pass on arrival and are a REGRESSION GUARD, not a red
# test: they pin that the rewrite C-10 demands still answers correctly, and the
# negative control is what catches a site rewritten unconditionally true.
LONG="$(awk 'BEGIN { for (i = 0; i < 60000; i++) printf "padding_%06d_abcdefghijklmnopqrst", i }')"
{ printf -- '---%s\n' "$LONG"
  printf 'id: T-1\ntitle: T\nslug: fixture\ntype: chore\nstatus: in-progress\nphase: REVIEW\nbranch: story/T-1-fixture\ndepends_on: []\nrequired_gates: []\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Gate results\n\n'
  printf '%s\n' "$GATE_MARK"
  printf '    result: pass\n\n## Notes\n'
} > "$B7/docs/backlog/stories/T-1.md"
b7_commit big-frontmatter
big_enough "AC-7: the check-boundaries frontmatter fixture story is at least 1.5 MB" \
  "$B7/docs/backlog/stories/T-1.md"
assert_eq "AC-7: a 1.5 MB first line beginning with --- is still read as frontmatter" \
  "0" "$(says "$(b7_run)" 'missing YAML frontmatter')"

{ printf 'NOT%s\n' "$LONG"
  printf 'id: T-1\ntitle: T\nslug: fixture\ntype: chore\nstatus: in-progress\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n'
} > "$B7/docs/backlog/stories/T-1.md"
b7_commit big-nofrontmatter
assert_eq "AC-7 control: a 1.5 MB first line NOT beginning with --- is still refused" \
  "1" "$(says "$(b7_run)" 'missing YAML frontmatter')"

rm -rf "$FIX" "$FIX2" "$C7" "$G7" "$B7" "$AC7"
summary "sigpipe"
