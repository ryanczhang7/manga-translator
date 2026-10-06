#!/usr/bin/env bash
# check-grep-count.sh - refuse a `grep -c` whose `||` fallback PRINTS.
#
#   bash scripts/check-grep-count.sh [PATHSPEC...]
#
# THE DEFECT.
#
#     doc_count() { grep -c "$@" "$DOC" 2>/dev/null || printf '0'; }
#
# `grep -c` prints `0` AND exits 1 when nothing matches. Measured:
#
#     $ grep -c zzz doc.txt ; echo "exit=$?"
#     0
#     exit=1
#
# So the fallback fires on exactly the case it was written for, and appends a
# SECOND value to output the command already produced. The caller receives
# "0\n0", which equals neither `0` nor any count:
#
#     no-match -> [0\n0]   == 0 : FALSE      -eq 0 : FALSE (and a syntax error)
#     match    -> [2]      == 0 : FALSE
#
# A comparison against it cannot succeed in either direction. In
# a consuming project this shape reached GREEN inside WORLD-084's own suite and
# cost a return to RED: the two control assertions built on it could not pass,
# and it was invisible during RED because the document did not exist yet, so the
# counting path never ran.
#
# THE FAMILY. This is the sibling of the defect check-sigpipe.sh guards, and they
# are worth naming together: both produce A MATCHER THAT REPORTS THE OPPOSITE OF
# THE TRUTH WHILE EVERY PROCESS IN IT EXITS CLEANLY.
#
#   pipeline into an early-exit reader under pipefail  writer dies of SIGPIPE,
#                                                      141 becomes the status
#   grep -c with a PRINTING fallback                   the fallback appends to
#                                                      output already produced
#
# `|| true` IS THE CORRECT IDIOM AND MUST NOT BE FLAGGED. It discards the
# no-match status without printing anything, which is exactly right, and both
# live instances in this tree are that form. Separating the two is the whole
# difficulty of this guard - a rule that flags every `grep -c ... ||` is not a
# guard, it is a rule against a correct idiom, and the first person to hit it
# will delete the guard rather than the line.
#
# WHAT COUNTS AS PRINTING. The fallback is judged by its command word:
#   SILENT (allowed)   true, :, break, continue, return, exit, and an empty
#                      fallback (no `||` at all)
#   PRINTING (refused) printf, echo, cat, tee, print, or a bare word that is
#                      none of the silent ones - `|| 0` and `|| $default` both
#                      put something on stdout or are meaningless there.
# Anything genuinely ambiguous is refused rather than waved through, because a
# fallback nobody can read at a glance is one nobody can review either.
#
# WHY A SECOND GUARD RATHER THAN A SECOND RULE IN check-sigpipe.sh. WORLD-088
# left this open deliberately, so: separate, for two reasons that are not about
# taste.
#
#   * That script is named for its mechanism, and a consuming project has just
#     wired `scripts/check-sigpipe.sh` into its boundaries job and into doctor's
#     want-list. Growing it a rule about `grep -c` makes the name a lie; renaming
#     it churns a consuming project's CI for no gain.
#   * The two rules share PLUMBING, not logic. The disposition question is
#     genuinely different - check-sigpipe.sh must ask whether anybody READS the
#     status, because a discarded status is harmless there, while this defect
#     corrupts the VALUE and is reportable wherever it sits.
#
# What they must not do is keep two copies of the shared part. `masked_lines`
# and `harness_shell_files` live in .claude/hooks/lib.sh and both guards call
# them, so the two cannot drift about what a file's text is or what the
# population is - which is the failure rules.md names, and which this pair would
# have walked straight into.
#
# SCOPE, QUOTING AND HEREDOCS. Identical to check-sigpipe.sh and for the same
# reasons: the population is `harness_shell_files` (through classify.sh, so an
# uncommitted file is still scanned), and every file is read through
# `masked_lines`, so a quoted `||` in prose is data rather than syntax and the
# line numbers still match the source.
#
# ESCAPE HATCH. `# grep-count-ok: <reason>` on the offending line, with a
# non-empty reason. A bare marker does not suppress - a hatch that does not make
# somebody write down why is a hatch nobody reviews. Read from the RAW file: the
# masker masks the spaces inside a comment body.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# masked_lines, harness_shell_files. CLAUDE_PROJECT_DIR is what lib.sh resolves
# against; check-boundaries.sh and check-sigpipe.sh set it the same way.
export CLAUDE_PROJECT_DIR="$ROOT"
. "$ROOT/.claude/hooks/lib.sh"

NL='
'

# --- the rule ----------------------------------------------------------------
# One awk pass per file, emitting `HIT <line>` for each reportable fallback.
AWK_RULE="$(cat <<'AWKEOF'
function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
function bname(p,   n, a) { n = split(p, a, "/"); return a[n] }

# is_count(s)  Does the text starting at s invoke grep asking for a COUNT?
# -c / --count, in the bundled spellings the real tree uses (-c, -cE, -Ec, -chE).
# `-m` is a count of MATCHES to stop after, not a count on stdout, and does not
# qualify. A pattern argument ends the options.
function is_count(s,   n, a, w, i, t, c) {
  sub(/^[ \t]+/, "", s)
  n = split(s, a, /[ \t]+/)
  if (n < 1) return 0
  w = bname(a[1])
  sub(/[;&)}<>|].*$/, "", w)
  if (w != "grep" && w != "egrep" && w != "fgrep") return 0
  for (i = 2; i <= n; i++) {
    t = a[i]
    if (t == "--") return 0
    if (substr(t, 1, 2) == "--") {
      if (t ~ /^--count/) return 1
      continue
    }
    if (substr(t, 1, 1) == "-") {
      # A bundled short option carrying c. No option letter that takes an
      # inline argument can precede it here without a separator, so a plain
      # scan for `c` in the cluster is right: -c, -cE, -Ec, -chE.
      c = t; sub(/^-/, "", c)
      if (match(c, /^[A-Za-z]+/) && substr(c, 1, RLENGTH) ~ /c/) return 1
      continue
    }
    return 0   # the pattern: options are over
  }
  return 0
}

# silent_word(w)  Is w a fallback command that prints nothing?
function silent_word(w) {
  return (w == "true" || w == ":" || w == "break" || w == "continue" ||
          w == "return" || w == "exit")
}

# fallback_prints(s)  s is the text AFTER `||`. 1 if it puts something on
# stdout, 0 if it is one of the silent forms. An empty tail is silent - the
# caller only reaches here when a `||` was actually present.
function fallback_prints(s,   n, a, w) {
  s = trim(s)
  if (s == "") return 0
  # `|| { printf 0; }` and `|| ( echo 0 )` - step inside the group.
  sub(/^[({][ \t]*/, "", s)
  n = split(s, a, /[ \t]+/)
  if (n < 1) return 0
  w = a[1]
  sub(/[;&)}].*$/, "", w)
  w = bname(w)
  if (silent_word(w)) return 0
  return 1
}

# scan_line(s)  The column of the first `||` at command-substitution depth zero
# that follows a counting grep and is followed by a printing fallback, or 0.
# D is global so a backslash-continued line keeps its depth.
function scan_line(s,   i, c, L, head) {
  L = length(s)
  for (i = 1; i <= L; i++) {
    c = substr(s, i, 1)
    if (c == "\\") { i++; continue }
    if (c == "$" && substr(s, i + 1, 1) == "(") { D++; i++; continue }
    if (c == ")") { if (D > 0) D--; continue }
    if (c == "|" && substr(s, i + 1, 1) == "|") {
      # The command immediately left of this `||`. Take the text back to the
      # nearest opener or separator, so `x=$(grep -c p f || printf 0)` is
      # judged on `grep -c p f` rather than on `x=$(grep ...`.
      head = substr(s, 1, i - 1)
      # BACK TO THE NEAREST SEPARATOR, AND `|` IS ONE OF THEM. Without the `|`
      # in this class the command judged in `cat f | grep -c x || printf 0` was
      # `cat` - not a counting grep - so every pipeline form was silent. A
      # consuming project wired this guard into CI where all three `grep -c`
      # uses are pipelines, and a green run was evidence of nothing.
      #
      # A quoted `|` has already been masked to \001 by masked_lines, so only a
      # real producer is stepped over.
      sub(/^.*[({;&|]/, "", head)
      sub(/^.*\$\(/, "", head)
      if (is_count(head) && fallback_prints(substr(s, i + 2))) return i
      i++
      continue
    }
  }
  return 0
}

# hd_word(s)  The delimiter of a heredoc opened on this line, or "". `<<<` is a
# here-string and opens nothing.
function hd_word(s,   m) {
  if (!match(s, /<<-?[ \t]*("[A-Za-z_][A-Za-z0-9_]*"|'[A-Za-z_][A-Za-z0-9_]*'|\\[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)/)) return ""
  m = substr(s, RSTART, RLENGTH)
  sub(/^<<-?[ \t]*/, "", m)
  gsub(/["'\\]/, "", m)
  return m
}

{ raw[NR] = $0 }

END {
  in_hd = 0; hd = ""
  i = 1
  while (i <= NR) {
    line = raw[i]

    if (in_hd) { if (trim(line) == hd) in_hd = 0; i++; continue }

    t = trim(line)
    if (t == "" || substr(t, 1, 1) == "#") { i++; continue }

    # One logical line: backslash continuations folded in.
    start = i
    grp = line
    while (line ~ /\\[ \t]*$/ && i < NR) { i++; line = raw[i]; grp = grp "\n" line }
    last = i
    i++

    D = 0; hitline = 0
    for (k = start; k <= last; k++) {
      pos = scan_line(raw[k])
      if (pos > 0 && hitline == 0) hitline = k
    }

    # The marker, by line number, computed from the RAW file - see analyze().
    marked = 0
    for (k = start; k <= last; k++)
      if (index(MARKS, "," k ",") > 0) marked = 1

    # NO DISPOSITION BUCKETS HERE, unlike check-sigpipe.sh, and the difference
    # is real rather than an omission. That guard has to ask whether anybody
    # READS the status, because a discarded status is harmless. This defect
    # corrupts the VALUE on stdout, and every one of these exists to have its
    # value used - `grep -c` whose output nobody reads is dead code, not an
    # idiom. So every printing fallback is reportable wherever it sits.
    if (hitline > 0 && !marked) print "HIT " hitline

    hw = hd_word(grp)
    if (hw != "") { in_hd = 1; hd = hw }
  }
}
AWKEOF
)"

# unwrap_quoted_subst   Blank the double quotes that WRAP a command
# substitution, turning "$( ... )" into  $( ... )  with the length unchanged.
#
# WITHOUT THIS THE GUARD MISSES THE COMMONEST SPELLING, and it missed it in the
# first version - caught only because AC-4's mutation reintroduced the defect on
# a real line and the guard reported nothing:
#
#   a=$(grep -c x f || printf 0)     the || is visible
#   b="$(grep -c x f || printf 0)"   the || arrives as \001\001
#
# mask_shell_quotes masks the WHOLE interior of a `"$( ... )"` on purpose: for
# the phase lock the text in there is data to the command outside it, and a
# redirect hidden in there should fail open. Correct there, wrong here - this
# guard reads SOURCE, and the interior of a command substitution is code that
# runs. The surrounding quotes affect word-splitting of the RESULT, not the
# parsing of the inside, so removing them changes nothing about what the shell
# would do with the interior.
#
# SAFE AGAINST QUOTED PROSE, which is the thing it could plausibly break. Only
# `"` characters are blanked, and a `"` does not open or close a single-quoted
# span or a heredoc body - so `echo 'x="$(cmd || printf 0)"'` still has its
# interior masked by the single quotes, and is still not reported. There is a
# test for exactly that.
#
# Both quotes are blanked or neither: the closing `)` is found by depth, and the
# pair is only taken when a `"` immediately follows it. An unbalanced rewrite
# would corrupt the masking of everything after it on the line.
#
# KNOWN LIMIT: only a `"` IMMEDIATELY before `$(`. In `x="a $(cmd) b"` the
# substitution is embedded in a larger string and its interior stays masked, so
# a defect written that way is not reported. No instance exists in this tree and
# the shape is a poor place to put one; recorded rather than left silent.
unwrap_quoted_subst() { # <file>
  awk '{
    s = $0; L = length(s)
    delete blank
    for (i = 1; i <= L; i++) {
      if (substr(s, i, 3) != "\"$(") continue
      d = 0
      for (j = i + 1; j <= L; j++) {
        c = substr(s, j, 1)
        if (c == "(") d++
        else if (c == ")") { d--; if (d == 0) break }
      }
      if (j <= L && substr(s, j + 1, 1) == "\"") { blank[i] = 1; blank[j + 1] = 1 }
    }
    out = ""
    for (i = 1; i <= L; i++) out = out (blank[i] ? " " : substr(s, i, 1))
    print out
  }' "$1"
}

analyze() { # <abs path>   The report for one file, on stdout.
  local marks
  marks="$(awk '/#[ \t]*grep-count-ok:[ \t]*[^ \t]/ { printf "%s,", NR }' "$1" 2>/dev/null)"
  unwrap_quoted_subst "$1" | masked_lines \
    | awk -v MARKS=",$marks" "$AWK_RULE" 2>/dev/null
}

# --- enumerate, through classify.sh --------------------------------------------
FILES=()
while IFS= read -r p; do
  [ -n "$p" ] || continue
  FILES+=("$p")
done <<< "$(harness_shell_files "$@")"

# --- report --------------------------------------------------------------------
findings=0
scanned=0
for rel in "${FILES[@]:-}"; do
  [ -n "$rel" ] || continue
  [ -f "$ROOT/$rel" ] || continue
  scanned=$((scanned + 1))
  report="$(analyze "$ROOT/$rel")"
  [ -n "$report" ] || continue
  while IFS= read -r row; do
    [ -n "$row" ] || continue
    case "$row" in
      HIT\ *)
        ln="${row#HIT }"
        printf '%s:%s: grep -c prints 0 AND exits 1 on no-match, so this printing fallback appends a second value; the caller gets "0\\n0", which equals neither the count nor zero\n' "$rel" "$ln"
        findings=$((findings + 1)) ;;
    esac
  done <<< "$report"
done

printf 'check-grep-count: scanned %d shell file(s), %d finding(s)\n' "$scanned" "$findings"
[ "$findings" -eq 0 ]
