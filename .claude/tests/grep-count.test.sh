#!/usr/bin/env bash
# Tests for scripts/check-grep-count.sh - WORLD-088, filed by
# a consuming project and built here so it arrives downstream vendored.
#
# THE DEFECT. `grep -c` prints `0` AND exits 1 when nothing matches, so a `||`
# fallback that PRINTS fires on exactly the case it was written for and appends
# a second value to output the command already produced:
#
#     doc_count() { grep -c "$@" "$DOC" 2>/dev/null || printf '0'; }
#     no-match -> "0\n0"   which equals neither `0` nor any count
#
# It reached GREEN inside WORLD-084's own suite and cost a return to RED: the
# control assertions built on it could not pass in either direction, and it was
# invisible during RED because the document did not exist yet so the counting
# path never ran.
#
# `|| true` IS CORRECT AND MUST NOT BE FLAGGED - it discards the status without
# printing. Both live instances in this tree are that form. Telling the two
# apart is the whole guard; a rule that flags every `grep -c ... ||` is a rule
# against a correct idiom, and the first person to hit it deletes the guard.
#
# WHERE THE PROBES LIVE. In a throwaway fixture, not in this tree, for the
# reason check-sigpipe.sh's suite gives: a probe here would be found by the
# guard's own real-tree scan and the tree could never come out clean.
#
# HOUSE RULE, inherited: no assertion in this file may read the status of a
# pipeline into an early-exit reader. Counting is awk over a here-string.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

GUARD_REL="scripts/check-grep-count.sh"
GUARD="$REPO_ROOT/$GUARD_REL"

# --- instruments -------------------------------------------------------------
# awk over a here-string: one process, no pipe, nothing to kill with SIGPIPE.
count_prefix() { # <haystack> <literal prefix>
  awk 'BEGIN { p = ARGV[1]; ARGV[1] = "" } index($0, p) == 1 { n++ } END { print n + 0 }' \
    "$2" <<<"$1"
}

# lines_for <haystack> <file>  -> the line numbers reported for <file>, in order.
lines_for() {
  awk 'BEGIN { p = ARGV[1] ":"; ARGV[1] = "" }
       index($0, p) == 1 { s = substr($0, length(p) + 1)
                           sub(/:.*$/, "", s)
                           out = out (out == "" ? "" : " ") s }
       END { print out }' "$2" <<<"$1"
}

run_guard() { # <root> [pathspec...]
  local root="$1"; shift
  GUARD_OUT="$( cd "$root" && bash "$root/$GUARD_REL" "$@" 2>&1 )"
  GUARD_RC=$?
}

assert_flagged() { # <label> <file> <expected line numbers>
  assert_eq "$1" "$3" "$(lines_for "$GUARD_OUT" "$2")"
}

# ---------------------------------------------------------------------------
describe "AC-2: the mechanism, reproduced end to end"

# A guard for a defect nobody has reproduced is a guard for a rumour. This runs
# the real construct against real input and shows the actual failure - a value
# that equals neither the count nor zero - rather than matching a shape.
AC2="$(make_project_fixture)"
printf 'alpha\nbeta\nalpha\n' > "$AC2/doc.txt"

bad_count()  { grep -c "$1" "$AC2/doc.txt" 2>/dev/null || printf '0'; }   # grep-count-ok: this IS the defect, on purpose, and the guard reports it when the marker is removed
good_count() { grep -c "$1" "$AC2/doc.txt" 2>/dev/null || true; }

assert_eq "AC-2: grep -c with a MATCH gives the count" "2" "$(bad_count alpha)"

# The load-bearing one. On a no-match the fallback fires and appends, so the
# value is two lines. Compared as a string it equals neither "0" nor any count.
n="$(bad_count zzz)"
assert_eq "AC-2: and on a no-match it returns TWO values, not zero" \
  "2 lines" "$(awk 'END { print NR " lines" }' <<<"$n")"
assert_eq "AC-2: so the comparison the caller writes cannot succeed" \
  "not equal" "$([ "$n" = "0" ] && printf 'equal' || printf 'not equal')"

# The correct idiom, same input, same path - so the difference is the fallback
# and nothing else.
assert_eq "AC-2 control: || true returns a bare 0 on the same no-match" \
  "0" "$(good_count zzz)"
assert_eq "AC-2 control: and still the count on a match" "2" "$(good_count alpha)"

# ---------------------------------------------------------------------------
describe "AC-1: a printing fallback is reported; a silent one is not"

FIX="$(make_project_fixture)"
mkdir -p "$FIX/scripts/probes"

# Line numbers below are load-bearing: every assertion names them.
cat > "$FIX/scripts/probes/p_forms.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
# REPORTED: 4-9. Every printing spelling.
a=$(grep -c "x" f 2>/dev/null || printf '0')
b=$(grep -cE "y" f || echo 0)
c=$(grep --count "z" f || printf '%s' 0)
d() { grep -c "$1" "$DOC" 2>/dev/null || printf '0'; }
e=$(grep -c "q" f || cat /dev/null)
g=$(grep -c "w" f || 0)
# NOT REPORTED: 11-16. Silent fallbacks, no fallback, and not a counting grep.
h=$(grep -c "x" f 2>/dev/null || true)
i=$(grep -cE "y" f || :)
j=$(grep -c "z" f)
k=$(wc -l f || printf '0')
m=$(grep -q "x" f || printf '0')
n=$(grep -m1 "x" f || printf '0')
# NOT REPORTED: 18. Quoted prose is data, not syntax.
echo "never write: grep -c p f || printf 0"
SH
run_guard "$FIX" scripts/probes

assert_flagged "AC-1: every printing fallback is reported, and nothing else" \
  "scripts/probes/p_forms.sh" "4 5 6 7 8 9"

assert_eq "AC-1: and it exits non-zero on a finding" "1" "$GUARD_RC"

# The census, so none of the above can be satisfied by the file going unscanned.
assert_eq "AC-1: the summary names the exact census" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'check-grep-count: scanned 1 shell file(s), 6 finding(s)')"

# ---------------------------------------------------------------------------
describe "the two shapes that were MISSED first time round"

# Both were found by AC-4's mutation rather than by review, and both are the
# commonest spellings in this tree. Neither is hypothetical.
cat > "$FIX/scripts/probes/p_missed.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
# 6: the substitution is WRAPPED IN DOUBLE QUOTES. mask_shell_quotes masks the
# whole interior of a `"$( ... )"` on purpose - for the phase lock the text in
# there is data - so the `||` arrived as \001\001 and the rule never saw it.
acs="$(grep -cE '^AC-' "$file" 2>/dev/null || printf '0')"
# 11: AFTER A HERE-STRING. `<<<` was read as a heredoc opener, so every line
# below it was masked as heredoc body and the guard was blind to the rest of
# the file. scripts/plan.sh uses `<<<` at line 108.
x=$(awk '{ print }' <<< "$data")
y=$(grep -c "p" f || printf '0')
SH
run_guard "$FIX" scripts/probes/p_missed.sh

assert_flagged "both the double-quoted substitution and the line after a here-string are reported" \
  "scripts/probes/p_missed.sh" "6 11"

# The control for the unwrap: a `"$(` inside SINGLE quotes is prose, and the
# unwrap must not expose it. Blanking a `"` cannot open or close a single-quoted
# span, which is what makes the unwrap safe rather than lucky.
cat > "$FIX/scripts/probes/n_prose.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
echo 'never write: n="$(grep -c p f || printf 0)"'
z=$(grep -c "p" f || true)
SH
run_guard "$FIX" scripts/probes/n_prose.sh
assert_flagged "a quoted substitution inside single quotes is prose, not code" \
  "scripts/probes/n_prose.sh" ""


# ---------------------------------------------------------------------------
describe "a counting grep on the RIGHT of a pipe"

# THE BLIND SPOT, reported by a consuming project against release 37 with this
# corpus. The rule took the text back to the nearest `(`, `{`, `;` or `&` to
# find the command being judged - and NOT back to a `|`. So in
# `cat f | grep -c x || printf 0` the command it judged was `cat`, which is not
# a counting grep, and the line was silent.
#
# THE PROBE CORPUS IS THEIRS, and it is better than the one I wrote: each line
# differs from line 3 by exactly one thing, so a fix cannot be credited to the
# wrong variable. Line 5 uses `echo` rather than `printf`, so it is not the
# fallback word; line 9 carries a redirect, so it is not the redirect; line 7 is
# the function-body form.
#
# LINE 6 IS THE ONE WORTH READING TWICE. `|| true` is correctly silent - but
# before the fix it sat INSIDE the blind spot, so its silence was not evidence
# of the rule working. After the fix it is silent because the rule looked and
# approved, which is a different fact with the same appearance. That is why it
# is asserted alongside the others rather than trusted on its own.
#
# WHY IT MATTERS RATHER THAN BEING AN EDGE CASE: they wired this guard into CI,
# and all three `grep -c` uses in their tree are pipelines. A green run was
# evidence of nothing.
cat > "$FIX/scripts/probes/p_pipe.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
a=$(grep -c foo bar || printf 0)
b=$(cat bar | grep -c foo || printf 0)
c=$(cat bar | grep -cE foo || echo 0)
d=$(cat bar | grep -c foo || true)
e() { cat bar | grep -c foo || printf 0; }
f=$(grep -c foo bar 2>/dev/null || printf 0)
g=$(cat bar | grep -c foo 2>/dev/null || printf 0)
SH
run_guard "$FIX" scripts/probes/p_pipe.sh

assert_flagged "a counting grep is judged wherever it sits in the pipeline" \
  "scripts/probes/p_pipe.sh" "3 4 5 7 8 9"

assert_eq "the census counts them all" \
  "1" "$(count_prefix "$GUARD_OUT" \
        'check-grep-count: scanned 1 shell file(s), 6 finding(s)')"

# A quoted `|` is still data, so the producer on the left must be real syntax
# before the rule looks past it.
cat > "$FIX/scripts/probes/n_pipeprose.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
echo 'never write: cat f | grep -c x || printf 0'
h=$(cat f | grep -c x || true)
SH
run_guard "$FIX" scripts/probes/n_pipeprose.sh
assert_flagged "a pipeline inside quotes is prose, and || true beside it is silent" \
  "scripts/probes/n_pipeprose.sh" ""
# ---------------------------------------------------------------------------
describe "AC-6: the escape hatch, and the reason it must carry"

cat > "$FIX/scripts/probes/m_marker.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
a=$(grep -c "x" f || printf '0')   # grep-count-ok: measured, the caller splits on newline
b=$(grep -c "y" f || printf '0')   # grep-count-ok:
c=$(grep -c "z" f || printf '0')   # grep-count-ok
d=$(grep -c "w" f || printf '0')
SH
run_guard "$FIX" scripts/probes/m_marker.sh
assert_flagged "a marker with a reason suppresses; one without a reason does not; and the unmarked line is still reported" \
  "scripts/probes/m_marker.sh" "4 5 6"

# ---------------------------------------------------------------------------
describe "AC-3: the population comes from classify.sh"

# An uncommitted file is still scanned - classify enumerates through git, so a
# file written five minutes ago and never added is still returned.
cat > "$FIX/scripts/probes/u_untracked.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
q=$(grep -c "x" f || printf '0')
SH
run_guard "$FIX" scripts/probes
assert_eq "AC-3: an uncommitted file is still scanned" \
  "1" "$(count_prefix "$GUARD_OUT" "scripts/probes/u_untracked.sh:3:")"

# And the guard asks classify rather than walking the tree itself. The control
# replaces classify.sh with a stub that emits ONE path: a guard doing its own
# walk is unaffected by that and still reports every probe above.
STUB="$(make_project_fixture)"
mkdir -p "$STUB/scripts/probes"
cp "$FIX/scripts/probes/p_forms.sh" "$STUB/scripts/probes/"
cp "$FIX/scripts/probes/u_untracked.sh" "$STUB/scripts/probes/"
cat > "$STUB/scripts/classify.sh" <<'SH'
#!/usr/bin/env bash
printf 'scripts/probes/u_untracked.sh\n'
SH
run_guard "$STUB" scripts/probes
assert_eq "AC-3: the guard scans exactly what classify.sh returns, not its own walk" \
  "1" "$(count_prefix "$GUARD_OUT" 'check-grep-count: scanned 1 shell file(s), 1 finding(s)')"
rm -rf "$STUB"

# ---------------------------------------------------------------------------
describe "AC-4/AC-5: the real tree, and the guard blocking a PR"

# THE REAL TREE IS CLEAN, asserted here rather than only in CI, because AC-5
# requires a finding to fail `bash scripts/selftest.sh`. Without this assertion
# the suite would pass while the tree carried the defect and only the CI step
# would notice - and the CI step is the one a consuming project has to add by
# hand, since .github/workflows is project-owned.
run_guard "$REPO_ROOT"
assert_eq "AC-4: the real tree has no printing fallback" \
  "1" "$(count_prefix "$GUARD_OUT" 'check-grep-count: scanned ')"
assert_eq "AC-4: and the finding count in that census is zero" \
  "0" "$(awk 'index($0, "check-grep-count: scanned ") == 1 {
                i = index($0, "file(s), "); if (i == 0) next
                print substr($0, i + 9) + 0; exit }' <<<"$GUARD_OUT")"
assert_eq "AC-4: so it exits 0 against this tree" "0" "$GUARD_RC"

# The correct idiom is LIVE here, so the clean result above is not the vacuous
# kind: there are lines of this shape for the rule to get wrong.
assert_eq "AC-4: and the tree does carry || true instances for the rule to judge" \
  "2" "$(awk 'index($0, "|| true") > 0 && index($0, "grep -c") > 0 { n++ } END { print n + 0 }' \
        "$REPO_ROOT/scripts/plan.sh" "$REPO_ROOT/scripts/check-boundaries.sh")"

rm -rf "$FIX" "$AC2"
summary "grep-count"
