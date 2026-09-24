#!/usr/bin/env bash
# Run a named task from .claude/harness/project.conf (install, dev, test, ...).
#   bash scripts/task.sh dev
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$ROOT/.claude/harness/project.conf"
want="${1:-}"
# Parsing project.conf with builtins only, as scripts/gates.sh does (see there):
# a process per field cost minutes per manifest walk on Windows.
#
# trim <string> [var]   <string> without leading or trailing [:space:] - the
# carriage return of a CRLF manifest included, which this script relies on.
# Printed, or assigned to <var>. Self-contained: the test suite evaluates it alone.
trim() { local _t="$1"; _t="${_t#"${_t%%[![:space:]]*}"}"; _t="${_t%"${_t##*[![:space:]]}"}"; if [ $# -gt 1 ]; then printf -v "$2" '%s' "$_t"; else printf '%s' "$_t"; fi; }
# from_field <n> <string> <var>   `cut -d'|' -f<n>-`, untrimmed: the later `|`s
# kept, a string with no `|` returned whole, too few fields giving ''.
from_field() {
  local _r="$2" _i=1
  case "$_r" in
    *'|'*)
      while [ "$_i" -lt "$1" ]; do
        case "$_r" in *'|'*) _r="${_r#*|}" ;; *) _r=""; break ;; esac
        _i=$((_i+1))
      done ;;
  esac
  printf -v "$3" '%s' "$_r"
}
rest()  { local _v; from_field "$1" "$2" _v; trim "$_v" "$3"; }          # trimmed -f<n>-
field() { local _v; from_field "$1" "$2" _v; trim "${_v%%|*}" "$3"; }    # trimmed -f<n>

if [ -z "$want" ]; then
  printf 'Available tasks:\n'
  awk -F'|' '/^[[:space:]]*task[[:space:]]*\|/ {gsub(/^ +| +$/,"",$2); gsub(/^ +| +$/,"",$5); printf "  %-10s %s\n", $2, ($5=="" ? "<unconfigured>" : $5)}' "$CONF"
  exit 0
fi

while IFS= read -r line; do
  trim "$line" tline
  case "$tline" in ''|'#'*) continue ;; esac
  field 1 "$line" kind; [ "$kind" = task ] || continue
  field 2 "$line" id;   [ "$id" = "$want" ] || continue
  field 4 "$line" cwd;  [ -z "$cwd" ] && cwd="."
  rest  5 "$line" cmd
  [ -z "$cmd" ] && { printf "task '%s' is not configured in project.conf\n" "$want" >&2; exit 1; }
  shift
  cd "$ROOT/$cwd" && eval "$cmd" "$@"
  exit $?
done < "$CONF"
printf "no such task: %s\n" "$want" >&2; exit 1
