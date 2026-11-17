#!/usr/bin/env bash
# Does this story's diff touch a harness path?
#
#   bash scripts/selftest-needed.sh [base-ref]
#
#   exit 0  run   - a changed path is one `classify.sh` calls `harness`, or the
#                   diff could not be computed, or `lib.sh` could not be loaded
#                   (when in doubt, run)
#   exit 1  skip  - no changed path is `harness`; CI still runs the self-test
#   exit 2  usage
#
# Step 2 of GATES -> REVIEW asks this before spending minutes (hours on a busy
# Windows host) on `SELFTEST_JOBS=4 bash scripts/selftest.sh`. The harness
# suites read harness paths - scripts, `.claude/**`, `CLAUDE.md`, the workflows
# - so a story that changes none of them cannot break one, and CI's own run on
# the PR is the backstop either way (HARNESS-075).
#
# "The story's diff" is the same enumeration as the `covers` check in
# `gates.sh`: base = first of origin/main, main that resolves; changes against
# `git merge-base <base> HEAD`, committed or not, plus untracked files. It is
# duplicated rather than shared because `sigpipe.test.sh` pins `gates.sh` line
# numbers. Deliberate differences: with no merge base, `gates.sh` falls back
# to the base itself, and this answers `run`; a failing `git diff` or
# `git ls-files` answers `run` rather than an empty set; a rename counts under
# both names (`--no-renames`). Both scripts read NUL-separated output (`-z`),
# so no name is C-quoted: not a non-ASCII one, and not `"`, `\` or a tab
# (HARNESS-078). `lib.sh` is probe-loaded in a subshell first, so a
# library that will not load answers `run` and its error reaches stderr, and a
# missing `paths.conf` or a failing classify step answers `run` too (HARNESS-077).
# Known limit: a name holding a newline still splits into two paths that name
# no file, and is misread.
#
# --- `--suites [base-ref]`: WHICH suites (HARNESS-094) ------------------------
#
#   bash scripts/selftest-needed.sh --suites [base-ref]
#
#   stdout  the names of the suites in .claude/tests/*.test.sh that the changed
#           harness paths can break, sorted, one per line; or the one line
#           `all`; or nothing
#   exit 0  a list, or `all` - including every fallback above, which in this
#           mode answers `all`
#   exit 1  no harness path changed (stdout empty, the skip line on stderr)
#   exit 2  usage
#   stderr  a header, then one line per selected suite: the first path, in sort
#           order, that selected it, and the rule
#
# The same enumeration as the run/skip mode. Then, for each harness path, every
# rule that matches contributes, and `all` wins over everything:
#   R1 itself    .claude/tests/<name>.test.sh selects <name>
#   R2 every     .claude/tests/_lib.sh, .claude/tests/_spawns.sh,
#                scripts/selftest.sh and .claude/hooks/lib.sh are read by
#                every suite: `all` (A-4)
#   R3 mentioned a suite whose source holds the path as a fixed substring
#                that ends where the path ends; comments and test data
#                count, so a path a suite names only as test data is
#                mapped by that mention and never reaches R5 (HARNESS-096)
#   R4 scans     a row of the SCANS table below; an `add` row adds its suite
#                but does not map the path (A-5)
#   R5 unmapped  a path R1-R3 and R4's `map` rows all miss: `all`, naming the
#                path. A path the mapping cannot place selects more, never
#                fewer.
# A rule names a suite only when its .claude/tests/<name>.test.sh exists in
# this tree (amendment A-1), so a deleted suite, or a row whose suite is
# absent, contributes nothing - and a path left with no existing suite is R5's.
#
# Known limit: a suite that exercises a changed script only through another
# script, and never names it, is not selected. Transitive selection was
# measured and rejected (one level from gates.sh selects nearly every suite);
# CI's full run is the backstop.

set -uo pipefail

usage() {
  printf 'usage: bash scripts/selftest-needed.sh [base-ref]\n' >&2
  printf '       bash scripts/selftest-needed.sh --suites [base-ref]\n' >&2
  exit 2
}
MODE=run
if [ "${1-}" = --suites ]; then MODE=suites; shift; fi
[ "$#" -le 1 ] || usage
case "${1-}" in -*) usage ;; esac

D='—'
fallback() {
  if [ "$MODE" = suites ]; then
    printf 'selftest-needed: suites %s all: cannot compute the diff: %s; defaulting to every suite\n' "$D" "$1" >&2
    printf 'all\n'
    exit 0
  fi
  printf 'selftest-needed: run %s cannot compute the diff: %s; defaulting to run\n' "$D" "$1"
  exit 0
}

# Resolved before the `cd` below: BASH_SOURCE may be relative to the caller's
# directory (`bash ../scripts/selftest-needed.sh`).
SELF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)" \
  || fallback "cannot locate the harness this script belongs to"

TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || fallback "not a git checkout"
[ -n "$TOP" ] || fallback "not a git checkout"
cd "$TOP" || fallback "not a git checkout"

export CLAUDE_PROJECT_DIR="$SELF_ROOT"
LIB="$SELF_ROOT/.claude/hooks/lib.sh"
# Probe first: a `set -u` trip or a non-zero `exit` in a sourced file ends
# the whole script, so it is sourced in a subshell (stderr kept, so the
# error is seen) before the real source, which then cannot fail that way.
# Both discard stdout: the answer is one line, and a library that prints
# on load must not add one.
[ -f "$LIB" ] || fallback "cannot load $LIB"
( . "$LIB" ) >/dev/null || fallback "cannot load $LIB"
. "$LIB" >/dev/null
declare -F classify_stdin >/dev/null || fallback "$LIB defines no classify_stdin"
# Without its rules classify_stdin calls every path `source`, so a `skip` from
# here would be wrong by construction. On disk, not the index.
RULES="${HARNESS_DIR:-$SELF_ROOT/.claude/harness}/paths.conf"
[ -r "$RULES" ] || fallback "cannot classify the changed paths: no $RULES"

base="${1-}"
if [ -z "$base" ]; then
  for b in origin/main main; do
    if git rev-parse --verify -q "$b" >/dev/null 2>&1; then base="$b"; break; fi
  done
  [ -n "$base" ] || fallback "no origin/main or main to compare against"
fi

mb="$(git merge-base "$base" HEAD 2>/dev/null)" && [ -n "$mb" ] \
  || fallback "no merge base with $base"
short="$(git rev-parse --short "$mb" 2>/dev/null)"

# --no-renames lists both sides of a rename; -z names every path as the
# filesystem does, never C-quoted. The `tr` sits inside each substitution so
# that pipefail still carries git's failure to its fallback.
tracked="$(git diff -z --no-renames --name-only "$mb" 2>/dev/null | tr '\0' '\n')" \
  || fallback "git diff against $base failed"
untracked="$(git ls-files -z --others --exclude-standard 2>/dev/null | tr '\0' '\n')" \
  || fallback "git ls-files failed"
changed="$(printf '%s\n%s\n' "$tracked" "$untracked" | awk 'length' | sort -u)"
n=0; [ -n "$changed" ] && n="$(printf '%s\n' "$changed" | awk 'END { print NR }')"

harness="$(printf '%s\n' "$changed" | classify_stdin | awk -F'\t' '$1 == "harness" { print substr($0, length($1) + 2) }')" \
  || fallback "cannot classify the changed paths: classify_stdin failed"

if [ -z "$harness" ]; then
  if [ "$MODE" = suites ]; then
    printf 'selftest-needed: skip %s no harness path among %s changed path(s) against %s (merge-base %s); CI runs the self-test on the PR\n' \
      "$D" "$n" "$base" "$short" >&2
    exit 1
  fi
  printf 'selftest-needed: skip %s no harness path among %s changed path(s) against %s (merge-base %s); CI runs the self-test on the PR\n' \
    "$D" "$n" "$base" "$short"
  exit 1
fi

if [ "$MODE" = suites ]; then
  # R4. One row per suite that reads the tree by GLOB rather than by name, so
  # that R3 cannot see what it reads. A row is a declaration, like a floor: a
  # new suite that globs the tree adds its row here; nothing checks that it did.
  # Patterns are bash `case` patterns over the whole repo-relative path, so `*`
  # crosses `/`: `.claude/skills/*.md` is any depth. Evidence, per row:
  #   lib           lib.test.sh, `shipped="$(ls .../scripts/*.sh .../.claude/hooks/*.sh)"`
  #                 - its portability block reads every one
  #   sigpipe       sigpipe.test.sh, shell_files: `classify.sh --list harness`
  #                 filtered to `.sh`
  #   grep-count    grep-count.test.sh, run_guard over the real tree, which
  #                 scans the same `.sh` list
  #   profiles      profiles.test.sh, PROFILE_DIR: the reference directory
  #   shipped-docs  shipped-docs.test.sh: .claude/commands/*.md,
  #                 .claude/agents/*.md, and every .md under .claude/skills
  #                 (map row); and the `add` row: suite_docs_reads in
  #                 shipped-docs.test.sh scans every top-level
  #                 .claude/tests/*.sh for a read of docs/ (HARNESS-106,
  #                 HARNESS-107). The pattern also matches a .sh in a
  #                 subdirectory, which the rule does not scan; harmless,
  #                 because an `add` row never maps a path: it only runs
  #                 one small suite more than needed
  # The second column is the row's kind (A-5). A `map` row maps the path: a
  # match counts as placing it. An `add` row only adds its suite: the `*.sh`
  # scanners match every shell file, so letting them map would mean no shell
  # file could ever reach R5, and a new helper would select only the scanners.
  SCANS='lib          add scripts/*.sh .claude/hooks/*.sh
sigpipe      add *.sh
grep-count   add *.sh
profiles     map .claude/skills/stack-profiles/reference/*
shipped-docs add .claude/tests/*.sh
shipped-docs map .claude/commands/*.md .claude/agents/*.md .claude/skills/*.md'
  SC_NAME=(); SC_PAT=(); SC_MAP=()
  while read -r sc_suite sc_kind sc_pats; do
    [ -f ".claude/tests/$sc_suite.test.sh" ] || continue   # A-1
    read -ra sc_arr <<<"$sc_pats"   # `read -a` splits without globbing
    for sc_pat in "${sc_arr[@]}"; do
      SC_NAME[${#SC_NAME[@]}]="$sc_suite"; SC_PAT[${#SC_PAT[@]}]="$sc_pat"
      SC_MAP[${#SC_MAP[@]}]="$sc_kind"
    done
  done <<<"$SCANS"

  m=0
  for f in .claude/tests/*.test.sh; do [ -e "$f" ] && m=$((m+1)); done

  # R3, one process for every (path, suite) pair: the paths first, then each
  # suite file. Prints "<path index><TAB><suite>" for every path a suite's
  # source holds as a fixed substring (`index`, never a regex) that ends
  # where the path ends: clean_hit refuses an occurrence continued by a
  # path character, or by a `.` and an alphanumeric (`x.sh.bak`, `new-story`).
  mentions=""
  if [ "$m" -gt 0 ]; then
    mentions="$(printf '%s\n' "$harness" | awk '
      function clean_hit(line, p,   k, off, c, nx) {
        off = 0
        while ((k = index(substr(line, off + 1), p)) > 0) {
          off += k
          c = substr(line, off + length(p), 1)
          nx = substr(line, off + length(p) + 1, 1)
          if (c == "") return 1
          if (!index("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_/-", c) &&
              !(c == "." && nx != "" && index("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", nx)))
            return 1
        }
        return 0
      }
      FNR == NR { if (length($0)) { np++; p[np] = $0 }; next }
      FILENAME != cur {
        cur = FILENAME; split("", hit)
        s = FILENAME; sub(/.*\//, "", s); sub(/\.test\.sh$/, "", s)
      }
      {
        for (j = 1; j <= np; j++)
          if (!(j in hit) && clean_hit($0, p[j])) { hit[j] = 1; print j "\t" s }
      }' - .claude/tests/*.test.sh)"
  fi

  # Every path, in sort order; every rule, in order. A record is
  # "<suite><TAB><path> (<rule>)", and the first per suite is its reason.
  TAB=$(printf '\t')
  NL='
'
  recs=""; why_all=""; i=0; np=0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    i=$((i+1)); np=$i; hit=0
    case "$p" in
      .claude/tests/_lib.sh|.claude/tests/_spawns.sh|scripts/selftest.sh|.claude/hooks/lib.sh)
        [ -n "$why_all" ] || why_all="$p is read by every suite"
        continue ;;
    esac
    case "$p" in
      .claude/tests/*/*) ;;
      .claude/tests/*.test.sh)
        s="${p#.claude/tests/}"; s="${s%.test.sh}"
        if [ -f "$p" ]; then recs="$recs$s$TAB$p (itself)$NL"; hit=1; fi ;;
    esac
    while IFS="$TAB" read -r mi ms; do
      [ "$mi" = "$i" ] || continue
      recs="$recs$ms$TAB$p (mentioned)$NL"; hit=1
    done <<<"$mentions"
    k=0
    while [ "$k" -lt "${#SC_PAT[@]}" ]; do
      # Unquoted on purpose: the row is a pattern, not a string.
      # An `add` row records its suite and leaves `hit` alone (A-5).
      case "$p" in ${SC_PAT[$k]})
        recs="$recs${SC_NAME[$k]}$TAB$p (scans ${SC_PAT[$k]})$NL"
        [ "${SC_MAP[$k]}" = map ] && hit=1 ;;
      esac
      k=$((k+1))
    done
    [ "$hit" = 1 ] || [ -n "$why_all" ] || why_all="$p is mapped by no rule; defaulting to every suite"
  done <<<"$harness"

  if [ -n "$why_all" ]; then
    printf 'selftest-needed: suites %s all: %s\n' "$D" "$why_all" >&2
    printf 'all\n'
    exit 0
  fi

  # The first record per suite is its reason; then by name, which is the order
  # of stdout.
  sel="$(printf '%s' "$recs" | awk -F'\t' 'length($1) && !($1 in seen) { seen[$1] = 1; print }' \
    | sort -t "$TAB" -k1,1)"
  k="$(printf '%s\n' "$sel" | awk 'length { c++ } END { print c + 0 }')"
  printf 'selftest-needed: suites %s %s of %s selected from %s harness path(s) changed against %s (merge-base %s)\n' \
    "$D" "$k" "$m" "$np" "$base" "$short" >&2
  printf '%s\n' "$sel" | awk -F'\t' '
    length($1) { c++; n[c] = $1; r[c] = $2; if (length($1) > w) w = length($1) }
    END { for (i = 1; i <= c; i++) printf "  %-" w "s  %s\n", n[i], r[i] }' >&2
  printf '%s\n' "$sel" | awk -F'\t' 'length($1) { print $1 }'
  exit 0
fi

list="$(printf '%s\n' "$harness" | awk '
  NR <= 3 { out = (NR == 1 ? $0 : out ", " $0) }
  END { if (NR > 3) out = out ", +" (NR - 3) " more"; printf "%s|%d", out, NR }')"
printf 'selftest-needed: run %s %s harness path(s) changed against %s (merge-base %s): %s\n' \
  "$D" "${list##*|}" "$base" "$short" "${list%|*}"
exit 0
