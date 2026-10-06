#!/usr/bin/env bash
# Ask the harness what a path is - from any language.
#
#   bash scripts/classify.sh src/main.ts tests/a.test.ts   "<category>\t<path>" each
#   printf '%s\n' src/main.ts | bash scripts/classify.sh    the same, from stdin
#   bash scripts/classify.sh --only source PATH...          just the paths, one per line
#   bash scripts/classify.sh --list source [PATHSPEC...]    every such file in the tree
#
# Categories come from .claude/harness/paths.conf, plus ignored, source, outside
# and vendor, which the classifier returns without a rule. `--only` and `--list`
# accept any of them, DERIVED rather than listed here, so the set cannot drift
# from paths.conf the way a hand-copied list did. This is the SAME answer
# .claude/hooks/phase-guard.sh uses to allow or refuse a write, which is the
# entire point of the script existing.
#
# WHY IT EXISTS. `classify` was a bash function in .claude/hooks/lib.sh, so the
# only thing that could reach it was another bash script. A project's own
# guards - a test asserting that no module under src/ declares a certain
# constant, say - are written in the project's language, so each one rolled its
# own idea of "a source module" in a private regex. One project accumulated four
# copies, two of which had already drifted, and every one of them was returning
# deliberately-offending probe artifacts as production source. They had been
# doing that for six stories, asserting their properties over files written to
# VIOLATE a rule, and passing only because the rule violated was not the rule
# being asserted. A tree-scanning guard should ask this question, not answer it.
#
# --list enumerates through git: tracked files, plus untracked ones git does not
# ignore. Both halves matter. Skipping untracked files would make a module
# written five minutes ago invisible to every guard, which is the vacuous pass
# this repository spends its documentation warning about; and including ignored
# ones would hand the caller build output. Probe artifacts are excluded by their
# CLASSIFICATION - see the `__probe_` convention in paths.conf - never by
# whether they happen to be committed yet.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
. "$ROOT/.claude/hooks/lib.sh" || { printf 'classify: cannot load .claude/hooks/lib.sh\n' >&2; exit 1; }

categories() {
  { awk -F'|' '/^[[:space:]]*[a-z]+[[:space:]]*\|/ { gsub(/[[:space:]]/, "", $1); print $1 }' \
      "$ROOT/.claude/harness/paths.conf" 2>/dev/null
    printf 'ignored\nsource\noutside\nvendor\n'; } | sort -u
}

usage() {
  printf 'usage: classify.sh [--only CATEGORY | --list CATEGORY] [PATH...]\n\n' >&2
  sed -n '5,8p' "$0" | sed 's/^# \{0,1\}//' >&2
  printf '\ncategories: %s\n' "$(categories | tr '\n' ' ')" >&2
  exit 2
}

MODE=pairs
WANT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --only|--list)
      [ "$1" = "--list" ] && MODE=list || MODE=only
      shift
      # A category is required, and an option in its place is a typo rather than
      # a category: `--only --list src` should not silently filter for nothing.
      case "${1:-}" in ''|-*) printf 'classify: %s needs a category\n\n' "${MODE/only/--only}" >&2; usage ;; esac
      WANT="$1"; shift ;;
    -h|--help) usage ;;
    --) shift; break ;;
    -*) printf 'classify: unknown option %s\n\n' "$1" >&2; usage ;;
    *) break ;;
  esac
done

# The category has to be one the classifier can actually return. A typo'd
# `--only sources` otherwise returns nothing at all, which reads exactly like
# "this tree has no source files" and is the failure mode the script exists to
# prevent.
#
# DERIVED from paths.conf, not listed here. It was listed here, as a copy of
# that file's categories, and the copy drifted the moment paths.conf gained
# `manifest`: this script printed `manifest` for Cargo.toml and then refused
# `--only manifest` as unknown, contradicting itself in two lines. A longer
# hand-written list would drift again the next time.
#
# The four added to whatever paths.conf declares are the ones classify returns
# without a rule: `ignored` from git, `source` as the fallback, `outside` for a
# path that is not in this repository, and `vendor` in case no rule names it.
#
# ONE awk that DRAINS, not `categories | grep -qx`. `grep -qx` leaves at the
# first match, so under `set -o pipefail` the writer behind it dies of SIGPIPE
# and 141 becomes the pipeline's status - which this `if` reads as "unknown
# category" for a category that is right there on the first line. The regex is
# carried in ARGV rather than `-v`, because awk expands escape sequences in a
# `-v` assignment and a category is compared literally here.
if [ -n "$WANT" ]; then
  if ! categories | awk 'BEGIN { w = ARGV[1]; ARGV[1] = "" } $0 == w { h = 1 } END { exit !h }' "$WANT"; then
    printf 'classify: unknown category "%s"\n\n' "$WANT" >&2; usage
  fi
fi

emit() { # <category> <path>
  case "$MODE" in
    pairs) printf '%s\t%s\n' "$1" "$2" ;;
    only|list) [ "$1" = "$WANT" ] && printf '%s\n' "$2" ;;
  esac
  return 0
}

if [ "$MODE" = list ]; then
  # No pathspec means the whole repository.
  [ $# -eq 0 ] && set -- .
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    emit "$(classify "$p")" "$p"
  done <<< "$(git ls-files --cached --others --exclude-standard -- "$@" 2>/dev/null | sort -u)"
  exit 0
fi

if [ $# -gt 0 ]; then
  for p in "$@"; do emit "$(classify "$p")" "$p"; done
else
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    emit "$(classify "$p")" "$p"
  done
fi
exit 0
