#!/usr/bin/env bash
# check-sigpipe.sh - refuse a pipeline into an early-exit reader whose status is
# read, in a shell file running under `set -o pipefail`.
#
#   bash scripts/check-sigpipe.sh [PATHSPEC...]
#
# THE DEFECT. Under `set -o pipefail`:
#
#     has_content() { strip_comments | grep -q PATTERN; }
#
# `grep -q` leaves at the first match; the writer still holding buffered output
# dies of SIGPIPE; pipefail promotes 141 to the pipeline's status; and the caller
# reads that as FALSE for a section that plainly has content. Found five times in
# this repository, twice by CI and never by a local run - the boundary is a race
# on the pipe buffer, so a Windows checkout and a Linux runner disagree about the
# same file.
#
# WHAT IT REPORTS, AND WHAT IT DELIBERATELY DOES NOT. A hit falls in one of three
# buckets, and only the first two are the defect:
#
#   1. status read on the spot   - the pipeline is under `if`, `elif`, `while`,
#                                  `until`, `!`, `&&` or `||`.
#   2. status read by the caller - the pipeline is the LAST COMMAND OF A
#                                  FUNCTION, so it becomes the function's status.
#                                  All five historical instances are this shape,
#                                  with no conditional anywhere on the line: a
#                                  guard that scans for a conditional is trusted
#                                  and catches nothing.
#   3. status discarded          - the pipeline sits inside a command
#                                  substitution whose value is used and whose
#                                  status is not, or it is a bare top-level
#                                  statement in a script that does not `set -e`.
#                                  These are correct idioms; twelve of them live
#                                  in this tree and none is reported.
#
# PIPEFAIL IS INHERITED. Nineteen test suites here set no `pipefail` of their own
# and get it from `_lib.sh` when they source it - and one of those is where two
# of the five historical instances lived. A file is under pipefail if it sets it
# OR if it sources (one level) a file that does.
#
# COMMENTS AND HEREDOC BODIES ARE DATA, not code - the same rule CLAUDE.md states
# for the phase lock. Without it this guard reports its own test suite, whose
# probe corpus is a stack of quoted heredocs.
#
# A COMMENT AFTER A BRACE DOES NOT HIDE THE FUNCTION. Structural recognition of
# a function's braces - the one-line form `f() { ...; }`, the opener `f() {`, the
# closer `}` - reads the CODE PART of the masked logical line, everything before
# the `#` that begins a comment, and the one-line body is extracted from that
# same text. Reading the whole line instead meant a trailing comment defeated all
# three, and `f() { cmd | grep -q x; }   # anything at all` scored clean. That
# was found by an assertion written against the shape, which "passed" because
# nothing there was ever going to be reported - see code_part() for where a
# comment begins, which is the masker's decision and not a private one.
#
# AND THE RAW LINE IS THE FALLBACK, which is why the three tests are disjunctions
# rather than a plain strip. mask_shell_quotes drops the backslash of an escaped
# `\#` outside quotes and emits a bare `#`, so in its output
#
#     k() { echo a \# b | grep -m1 c; }        reaches the rule as
#     k() { echo a # b | grep -m1 c; }
#
# and the code part alone reads the body as `k() { echo a`. That shape IS
# reported, and stripping unconditionally would trade it away for the one above -
# a fix for one blind spot that opens another. Trying the code part first and the
# whole line second reports both, and makes this a strict widening: every line
# the comment-blind rule reported is still reported, from the identical body
# text. The order cannot be reversed - a comment that ENDS in a brace,
# `n() { cmd | head -1; }   # see {braces}`, makes the whole line look like a
# one-line function whose body is the comment.
#
# ESCAPE HATCH. `# sigpipe-ok: <reason>` on the offending line, with a non-empty
# reason. `# sigpipe-ok:` and `# sigpipe-ok` do not suppress - a hatch that does
# not make somebody write down why is a hatch nobody reviews.
#
# SCOPE. The files are the ones `scripts/classify.sh --list harness` returns,
# filtered to `*.sh`. It is not a private tree walk on purpose (rules.md, "A test
# that needs this answer asks for it"): classify enumerates through git, so a file
# written five minutes ago and never committed is still scanned.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# mask_shell_quotes and unmask_shell_quotes live here. CLAUDE_PROJECT_DIR is
# what lib.sh resolves paths against; check-boundaries.sh sets it the same way.
export CLAUDE_PROJECT_DIR="$ROOT"
. "$ROOT/.claude/hooks/lib.sh"

# NO SCRATCH DIRECTORY. Nothing shipped here may write to a temporary directory
# it did not name itself - `$TMPDIR` is unset in some of the shells this harness
# runs in, and `.claude/tests/lib.test.sh` refuses `mktemp` in a shipped script
# for that reason. Every intermediate below lives in an indexed bash array (3.2
# has those; only associative arrays would need bash 4).
NL='
'

# --- the rule ----------------------------------------------------------------
# One awk pass per file. It emits, on stdout:
#   PF                 the file sets pipefail in its own text
#   SRC <token>        the file sources something; <token> is a path-ish token
#   HIT <line>         a reportable pipeline, marker already applied
AWK_RULE="$(cat <<'AWKEOF'
function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
function bname(p,   n, a) { n = split(p, a, "/"); return a[n] }

# code_part(s)  Everything before the `#` that begins a comment, or s when the
# line carries no comment. WHERE A COMMENT BEGINS IS THE MASKER'S DECISION, not
# a private quote parser: mask_shell_quotes has already mapped every separator
# inside a quoted, escaped or heredoc span to a control character, so in its
# output a `#` begins a comment exactly when it is at column 1 or is preceded by
# one of space, tab, `;`, `&`, `|`, `(` - the same test the masker itself makes.
# Measured on this tree: `echo "a # b"` masks to `echo "a\006#\006b"` and `$#`
# and `${#v}` are untouched, so none of the three is read as a comment here.
function code_part(s,   i, c, p) {
  for (i = 1; i <= length(s); i++) {
    c = substr(s, i, 1)
    if (c != "#") continue
    if (i == 1) return ""
    p = substr(s, i - 1, 1)
    if (index(" \t;&|(", p) > 0) return substr(s, 1, i - 1)
  }
  return s
}

# early_reader(s)  Does the text immediately after a `|` start a reader that can
# leave before its input is drained? `head` always can. `grep` can when it is
# asked for a yes/no (-q), a bounded count (-m), or a file list (-l/-L).
# Everything else - -c, -v, -o alone, sed, awk, tr, wc, sort, cat - drains.
function early_reader(s,   n, a, w, i, t) {
  sub(/^[ \t]+/, "", s)
  n = split(s, a, /[ \t]+/)
  if (n < 1) return 0
  w = bname(a[1])
  # `| head; then ...` - the command word carries the separator when nothing
  # follows it. Without this, bare `head` at the end of a command is invisible.
  sub(/[;&)}<>].*$/, "", w)
  if (w == "head") return 1
  if (w != "grep" && w != "egrep" && w != "fgrep") return 0
  for (i = 2; i <= n; i++) {
    t = a[i]
    if (t == "--") return 0
    if (substr(t, 1, 2) == "--") {
      if (t ~ /^--(quiet|silent|max-count|files-with-matches|files-without-match)/) return 1
      continue
    }
    if (substr(t, 1, 1) == "-") {
      # A bundled short option carrying q, l, L or m: -q -qF -qE -qx -Eq -m1
      # -oE -m1 -Eom1 -l -L. No draining option letter is one of those four.
      if (t ~ /^-[A-Za-z]*[qlLm]/) return 1
      continue
    }
    return 0   # the pattern: options are over
  }
  return 0
}

# scan_line(s)  The column of the first `|` at command-substitution depth zero
# that feeds an early-exit reader, or 0. D is global so that a backslash-
# continued pipeline keeps its depth across physical lines. Backticks are NOT
# treated as substitution: this repository uses none, and every shell file in it
# carries markdown backticks in prose.
function scan_line(s,   i, c, L, res) {
  L = length(s); res = 0
  for (i = 1; i <= L; i++) {
    c = substr(s, i, 1)
    if (c == "\\") { i++; continue }
    if (c == "$" && substr(s, i + 1, 1) == "(") { D++; i++; continue }
    if (c == ")") { if (D > 0) D--; continue }
    if (c == "|") {
      if (substr(s, i + 1, 1) == "|") { i++; continue }
      if (D == 0 && res == 0 && early_reader(substr(s, i + 1))) res = i
    }
  }
  return res
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
  pf = 0; in_hd = 0; hd = ""; in_fn = 0; last_hit = 0
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

    if (t ~ /^set[ \t]/ && index(t, "pipefail") > 0) pf = 1

    if (t ~ /^(\.|source)[ \t]/) {
      s2 = t; tok = ""
      while (match(s2, /[A-Za-z0-9_.\/+-]+\.sh/)) {
        tok = substr(s2, RSTART, RLENGTH)
        s2 = substr(s2, RSTART + RLENGTH)
      }
      if (tok != "") print "SRC " tok
    }

    # STRUCTURAL BRACE RECOGNITION READS THE CODE PART FIRST AND THE RAW LINE AS
    # THE FALLBACK, in that order, and both halves are load-bearing (see the
    # header). `onesrc` is the text the one-line body is then extracted from, so
    # the fallback branch splits exactly what the comment-blind rule splits.
    ct = trim(code_part(t))

    is_open    = (start == last) &&
                 ((ct ~ /^[A-Za-z_][A-Za-z0-9_]*[ \t]*\(\)[ \t]*\{[ \t]*$/) ||
                  (t  ~ /^[A-Za-z_][A-Za-z0-9_]*[ \t]*\(\)[ \t]*\{[ \t]*$/))

    is_oneline = 0; onesrc = ""
    if (start == last) {
      if      (ct ~ /^[A-Za-z_][A-Za-z0-9_]*[ \t]*\(\)[ \t]*\{.*\}[ \t]*$/) { is_oneline = 1; onesrc = code_part(grp) }
      else if (t  ~ /^[A-Za-z_][A-Za-z0-9_]*[ \t]*\(\)[ \t]*\{.*\}[ \t]*$/) { is_oneline = 1; onesrc = grp }
    }

    is_close   = (code_part(line) ~ /^\}[ \t]*$/) || (line ~ /^\}[ \t]*$/)

    D = 0; hitline = 0
    for (k = start; k <= last; k++) {
      pos = scan_line(raw[k])
      if (pos > 0 && hitline == 0) hitline = k
    }

    # THE MARKER IS READ FROM THE RAW FILE, not the masked one, and arrives as
    # MARKS. mask_shell_quotes treats a comment body as data and masks the
    # spaces inside it, so `# sigpipe-ok: reason` reaches the rule as
    # `#\006sigpipe-ok:\006reason` and a pattern written with [ \t] stops
    # matching - every marked line in every consuming project would quietly
    # start reporting again. A marker is a human annotation about the source as
    # written; the mask is about what the shell would execute. Different
    # questions, so different inputs.
    marked = 0
    for (k = start; k <= last; k++)
      if (index(MARKS, "," k ",") > 0) marked = 1

    # Bucket 1: the status is read right here.
    b1 = (t ~ /^(if|elif|while|until)[ \t]/) || (t ~ /^![ \t]/) ||
         (index(grp, "&&") > 0) || (index(grp, "||") > 0)

    emitted = 0
    if (hitline > 0 && !marked) {
      if (b1) { print "HIT " hitline; emitted = 1 }
      else if (is_oneline) {
        # Bucket 2, one-line brace form: only the LAST command of the body
        # becomes the function's status.
        body = substr(onesrc, index(onesrc, "{") + 1)
        sub(/\}[ \t]*$/, "", body)
        n = split(body, seg, ";")
        tail = ""
        for (q = n; q >= 1; q--) if (trim(seg[q]) != "") { tail = seg[q]; break }
        D = 0
        if (scan_line(tail) > 0) { print "HIT " hitline; emitted = 1 }
      }
    }

    # Bucket 2, multi-line form: remember the body's last command and report it
    # when the closing brace arrives.
    if (is_open) { in_fn = 1; last_hit = 0 }
    else if (in_fn && is_close) {
      if (last_hit > 0) print "HIT " last_hit
      in_fn = 0; last_hit = 0
    }
    else if (in_fn) last_hit = (hitline > 0 && !marked && !emitted) ? hitline : 0

    hw = hd_word(grp)
    if (hw != "") { in_hd = 1; hd = hw }
  }
  if (pf) print "PF"
}
AWKEOF
)"

analyze() { # <abs path>   The report for one file, on stdout.
  # THROUGH THE MASKER, NOT A PRIVATE QUOTE PARSER. CLAUDE.md states the rule
  # for the phase lock and it is the same rule here: quoted arguments and
  # heredoc bodies are DATA, not syntax. `masked_lines` (lib.sh) applies it and
  # keeps the line numbers honest; read its comment before changing this.
  #
  # Ported without it, the rule was wrong in BOTH directions, and both were live
  # in this tree:
  #   * FALSE POSITIVE - `echo "run: cat x | head -1"` reported as a defect.
  #     Prose inside quotes, in a guard whose entire value is being trusted when
  #     it says a tree is clean.
  #   * FALSE NEGATIVE - the one-line function body is split on `;` to find its
  #     last command, and a QUOTED `;` earlier in the body took the split with
  #     it. `.claude/tests/lib.test.sh` had exactly that shape - a real instance
  #     of the defect this guard exists for - and it scored clean.
  #
  # THE MARKER IS READ FROM THE RAW FILE. The masker treats a comment body as
  # data and masks the spaces inside it, so `# sigpipe-ok: reason` arrives as
  # `#\006sigpipe-ok:\006reason` and a pattern written with [ \t] stops matching.
  # A marker is a human annotation about the source as written; the mask is
  # about what the shell would execute. Different questions, different inputs.
  local marks
  marks="$(awk '/#[ \t]*sigpipe-ok:[ \t]*[^ \t]/ { printf "%s,", NR }' "$1" 2>/dev/null)"
  masked_lines "$1" | awk -v MARKS=",$marks" "$AWK_RULE" 2>/dev/null
}

# has_line <report> <exact line>
has_line() {
  case "$NL$1$NL" in *"$NL$2$NL"*) return 0 ;; esac
  return 1
}

# --- 1. enumerate, through classify.sh -----------------------------------------
# harness_shell_files (lib.sh) - shared with check-grep-count.sh so the two
# guards cannot disagree about what the population is.
FILES=()
while IFS= read -r p; do
  [ -n "$p" ] || continue
  FILES+=("$p")
done <<< "$(harness_shell_files "$@")"

SCANNED=${#FILES[@]}

REPORTS=()
PF_OWN=""
i=0
while [ "$i" -lt "$SCANNED" ]; do
  p="${FILES[$i]}"
  r="$(analyze "$ROOT/$p")"
  REPORTS+=("$r")
  has_line "$r" PF && PF_OWN="$PF_OWN$p$NL"
  i=$((i + 1))
done

own_pf() { # <repo-relative path>   Is it in the set that sets pipefail itself?
  case "$NL$PF_OWN" in *"$NL$1$NL"*) return 0 ;; esac
  return 1
}

# sets_pipefail <repo-relative path>   Own text only; a `source` target need not
# be in the scanned population, so it may have to be analysed on the spot.
sets_pipefail() {
  own_pf "$1" && return 0
  [ -f "$ROOT/$1" ] || return 1
  has_line "$(analyze "$ROOT/$1")" PF
}

# same_basename <basename>   The scanned path ending in it, if any. The last
# resort for a `source` line whose path is built out of variables this script
# cannot resolve - `. "$ROOT/.claude/hooks/lib.sh"` and friends.
same_basename() {
  local j=0
  while [ "$j" -lt "$SCANNED" ]; do
    case "${FILES[$j]}" in */"$1") printf '%s' "${FILES[$j]}"; return 0 ;; esac
    j=$((j + 1))
  done
  return 1
}

# --- 2. report -----------------------------------------------------------------
FINDINGS=0
PFCOUNT=0
i=0
while [ "$i" -lt "$SCANNED" ]; do
  p="${FILES[$i]}"; r="${REPORTS[$i]}"; i=$((i + 1))

  under=0
  if own_pf "$p"; then
    under=1
  else
    dir="${p%/*}"; [ "$dir" = "$p" ] && dir=""
    while IFS= read -r l; do
      case "$l" in "SRC "*) ;; *) continue ;; esac
      tok="${l#SRC }"
      tok="${tok#/}"
      for cand in "${dir:+$dir/}$tok" "$tok" "$(same_basename "${tok##*/}")"; do
        [ -n "$cand" ] || continue
        if sets_pipefail "$cand"; then under=1; break; fi
      done
      [ "$under" = 1 ] && break
    done <<< "$r"
  fi
  [ "$under" = 1 ] || continue
  PFCOUNT=$((PFCOUNT + 1))

  while IFS= read -r l; do
    case "$l" in "HIT "*) ;; *) continue ;; esac
    FINDINGS=$((FINDINGS + 1))
    printf '%s:%s: pipeline into an early-exit reader under pipefail; the writer can be killed by SIGPIPE and 141 becomes the status this line is judged by\n' \
      "$p" "${l#HIT }"
  done <<< "$r"
done

printf 'check-sigpipe: scanned %d shell file(s), %d with pipefail, %d finding(s)\n' \
  "$SCANNED" "$PFCOUNT" "$FINDINGS"

[ "$FINDINGS" -eq 0 ] || exit 1
exit 0
