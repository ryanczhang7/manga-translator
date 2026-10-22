#!/usr/bin/env bash
# tidy.sh - finished worktrees and merged branches (HARNESS-066).
#
#   bash scripts/tidy.sh [--apply] [--base REF] [--idle-hours N]
#
# REPORTS BY DEFAULT, AND CHANGES NOTHING. One line per linked worktree other
# than the main checkout and the worktree it runs in:
#
#   REMOVABLE <path>
#   KEEP <path>  <missing|unmerged|uncommitted|locked|recent>
#
# then one ORPHAN line per folder under <main>/.claude/worktrees/ that git does
# not list, each followed by the command to remove it (printed, never run),
# then one DELETABLE line per merged local story/* or harness/* branch, then the
# census, always last:
#
#   tidy: N worktree(s), R removable, K kept; M merged branch(es) deletable
#
# WHAT "FINISHED" MEANS. A worktree is REMOVABLE only when its folder exists
# and, in this order, the first failing fact being the KEEP reason:
#   unmerged     its HEAD is not an ancestor of --base (default origin/main)
#   uncommitted  `status --porcelain --untracked-files=all` prints anything
#   locked       its `git worktree list --porcelain` record has a locked line
#   recent       a file `ls-files -co --exclude-standard` lists was modified
#                less than --idle-hours (default 24) ago. Ignored files -
#                node_modules, build output - are what a removal frees, not
#                evidence of work, so they are not consulted. This is a proxy
#                for "no session is using it"; `ps` is not portable enough.
# `missing` (the folder is gone) is judged by the directory, not by git's
# `prunable` line: git prints none for a locked worktree.
#
# A branch is DELETABLE when its tip is in --base, no worktree has it checked
# out, and there is no refs/remotes/origin/<name>. Nothing is fetched, so a
# stale remote-tracking ref keeps a branch: the safe direction.
#
# --apply prints the same report without its census, then removes each
# REMOVABLE worktree with `git -c core.longpaths=true worktree remove` (never
# --force; the branch is kept) and deletes each DELETABLE branch with
# `git branch -d` (never -D), then prints the census of the state it acted on.
# A removal git refuses is reported LEFT with git's first line and the command
# for the user to finish it, and the script exits 1. Nothing is ever deleted by
# any other means: a recursive delete outside the repository is exactly what
# an agent's own safety checks refuse, and must not be routed around.
#
# The repository judged is the cwd's (`git rev-parse --show-toplevel`), not
# this file's, so a copy in a linked worktree judges the same repository.
#
# Exit: 0 report, 0 --apply with nothing LEFT, 1 --apply with a LEFT or a
# branch git would not delete, 2 usage error or a --base that does not resolve.

set -uo pipefail

usage() {
  printf 'usage: bash scripts/tidy.sh [--apply] [--base REF] [--idle-hours N]\n' >&2
  exit 2
}
die2() { printf 'tidy: %s\n' "$1" >&2; exit 2; }

APPLY=0
BASE=origin/main
IDLE=24
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --base)
      [ $# -ge 2 ] || usage
      BASE="$2"; shift ;;
    --idle-hours)
      [ $# -ge 2 ] || usage
      case "$2" in ''|*[!0-9]*) die2 "--idle-hours takes a whole number of hours, not '$2'" ;; esac
      IDLE="$2"; shift ;;
    -h|--help)
      awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *) printf 'tidy: unknown option %s\n' "$1" >&2; usage ;;
  esac
  shift
done
IDLE_MIN=$(( 10#$IDLE * 60 ))

TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || die2 "not inside a git working tree"
[ -n "$TOP" ] || die2 "not inside a git working tree"
G() { git -C "$TOP" "$@"; }

BASE_SHA="$(G rev-parse -q --verify "$BASE^{commit}" 2>/dev/null)" \
  || { printf "tidy: base '%s' does not resolve\n" "$BASE" >&2; exit 2; }

case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*) WIN=1 ;;
  *) WIN=0 ;;
esac

# remove_cmd <path>   The command a user runs to delete a folder git will not.
remove_cmd() {
  local p="$1" q
  if [ "$WIN" = 1 ]; then
    p="${p//\//\\}"; q="${p//\'/\'\'}"
    printf "Remove-Item -LiteralPath '%s%s' -Recurse -Force" '\\?\' "$q"
  else
    q="${p//\'/\'\\\'\'}"
    printf "rm -rf -- '%s'" "$q"
  fi
}
finish_cmd() {
  if [ "$WIN" = 1 ]; then printf '%s; git worktree prune' "$(remove_cmd "$1")"
  else printf '%s && git worktree prune' "$(remove_cmd "$1")"; fi
}

# recent <dir>   Prints something when a file git would track there (tracked,
# or untracked and not ignored) is younger than the idle window. One find per
# xargs batch, so the cost does not grow with a spawn per file.
recent() {
  local list
  list="$(git -C "$1" ls-files -z -co --exclude-standard 2>/dev/null | tr '\0' '\n')"
  [ -n "$list" ] || return 0
  ( cd "$1" && printf '%s\n' "$list" | awk '{ print "./" $0 }' | tr '\n' '\0' \
      | xargs -0 sh -c 'find "$@" -prune -mmin "-$0" -print -quit' "$IDLE_MIN" 2>/dev/null )
  return 0
}

# --- the worktree records, in git's order -------------------------------------
PORC="$(G worktree list --porcelain)" || die2 "git worktree list failed"
WT_PATH=() WT_HEAD=() WT_LOCKED=()
CHECKED_OUT=" "
idx=-1
while IFS= read -r line; do
  case "$line" in
    "worktree "*) idx=$((idx + 1)); WT_PATH[idx]="${line#worktree }"; WT_HEAD[idx]=""; WT_LOCKED[idx]=0 ;;
    "HEAD "*) WT_HEAD[idx]="${line#HEAD }" ;;
    "branch refs/heads/"*) CHECKED_OUT="$CHECKED_OUT${line#branch refs/heads/} " ;;
    locked|"locked "*) WT_LOCKED[idx]=1 ;;
  esac
done <<< "$PORC"

REPORT=()          # every line of the report, census aside, in print order
REMOVE=()          # REMOVABLE paths, in report order
DELETE=()          # DELETABLE branches, sorted
N=0 R=0 K=0

for (( i = 1; i <= idx; i++ )); do
  p="${WT_PATH[i]}"
  [ "$p" -ef "$TOP" ] && continue
  why=""
  if [ ! -d "$p" ]; then
    why=missing
  elif ! G merge-base --is-ancestor "${WT_HEAD[i]}" "$BASE_SHA" >/dev/null 2>&1; then
    why=unmerged
  elif [ -n "$(git --no-optional-locks -C "$p" status --porcelain --untracked-files=all 2>/dev/null)" ]; then
    why=uncommitted
  elif [ "${WT_LOCKED[i]}" = 1 ]; then
    why=locked
  elif [ -n "$(recent "$p")" ]; then
    why=recent
  fi
  N=$((N + 1))
  if [ -z "$why" ]; then
    R=$((R + 1)); REMOVE+=("$p"); REPORT+=("REMOVABLE $p")
  else
    K=$((K + 1)); REPORT+=("KEEP $p  $why")
  fi
done

# --- orphans: folders under <main>/.claude/worktrees/ git does not list --------
MAIN="${WT_PATH[0]}"
if [ -d "$MAIN/.claude/worktrees" ]; then
  names="$(cd "$MAIN/.claude/worktrees" && for d in * .[!.]* ..?*; do [ -d "$d" ] && [ ! -L "$d" ] && printf '%s\n' "$d"; done | LC_ALL=C sort)"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    o="$MAIN/.claude/worktrees/$name"
    known=0
    for (( i = 0; i <= idx; i++ )); do
      if [ "$o" -ef "${WT_PATH[i]}" ]; then known=1; break; fi
    done
    [ "$known" = 1 ] && continue
    files="$(find "$o" -type f 2>/dev/null | awk 'END { print NR }')"
    if [ "$files" = 0 ]; then REPORT+=("ORPHAN $o  empty")
    else REPORT+=("ORPHAN $o  $files file(s)"); fi
    REPORT+=("  remove it: $(remove_cmd "$o")")
  done <<< "$names"
fi

# --- merged local branches ------------------------------------------------------
REMOTES=" $(G for-each-ref --format='%(refname)' refs/remotes/origin | awk '{ sub(/^refs\/remotes\/origin\//, ""); printf "%s ", $0 }')"
while IFS=' ' read -r sha ref; do
  [ -n "$ref" ] || continue
  name="${ref#refs/heads/}"
  case "$name" in story/*|harness/*) ;; *) continue ;; esac
  case "$CHECKED_OUT" in *" $name "*) continue ;; esac
  case "$REMOTES" in *" $name "*) continue ;; esac
  G merge-base --is-ancestor "$sha" "$BASE_SHA" >/dev/null 2>&1 || continue
  DELETE+=("$name")
done <<< "$(G for-each-ref --format='%(objectname) %(refname)' refs/heads/story refs/heads/harness | LC_ALL=C sort -k2)"
M=${#DELETE[@]}
for b in ${DELETE[@]+"${DELETE[@]}"}; do REPORT+=("DELETABLE $b"); done

# --- print, then act -------------------------------------------------------------
if [ ${#REPORT[@]} -gt 0 ]; then printf '%s\n' "${REPORT[@]}"; fi

rc=0
if [ "$APPLY" = 1 ]; then
  for p in ${REMOVE[@]+"${REMOVE[@]}"}; do
    if msg="$(G -c core.longpaths=true worktree remove "$p" 2>&1)"; then
      printf 'removed %s\n' "$p"
    else
      printf 'LEFT %s  %s\n' "$p" "$(awk 'NR == 1 { print; exit }' <<< "$msg")"
      printf '  finish it: %s\n' "$(finish_cmd "$p")"
      rc=1
    fi
  done
  for b in ${DELETE[@]+"${DELETE[@]}"}; do
    if msg="$(G branch -d "$b" 2>&1)"; then
      printf 'deleted %s\n' "$b"
    else
      printf 'not deleted %s  %s\n' "$b" "$(awk 'NR == 1 { print; exit }' <<< "$msg")"
      rc=1
    fi
  done
fi

printf 'tidy: %s worktree(s), %s removable, %s kept; %s merged branch(es) deletable\n' "$N" "$R" "$K" "$M"
exit "$rc"
