#!/usr/bin/env bash
# Run a named task from .claude/harness/project.conf (install, dev, test, ...).
#   bash scripts/task.sh dev
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$ROOT/.claude/harness/project.conf"
want="${1:-}"
trim() { printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

if [ -z "$want" ]; then
  printf 'Available tasks:\n'
  awk -F'|' '/^[[:space:]]*task[[:space:]]*\|/ {gsub(/^ +| +$/,"",$2); gsub(/^ +| +$/,"",$5); printf "  %-10s %s\n", $2, ($5=="" ? "<unconfigured>" : $5)}' "$CONF"
  exit 0
fi

while IFS= read -r line; do
  case "$(trim "$line")" in ''|'#'*) continue ;; esac
  kind=$(trim "$(printf '%s' "$line" | cut -d'|' -f1)"); [ "$kind" = task ] || continue
  id=$(trim   "$(printf '%s' "$line" | cut -d'|' -f2)"); [ "$id" = "$want" ] || continue
  cwd=$(trim  "$(printf '%s' "$line" | cut -d'|' -f4)"); [ -z "$cwd" ] && cwd="."
  cmd=$(trim  "$(printf '%s' "$line" | cut -d'|' -f5-)")
  [ -z "$cmd" ] && { printf "task '%s' is not configured in project.conf\n" "$want" >&2; exit 1; }
  shift
  cd "$ROOT/$cwd" && eval "$cmd" "$@"
  exit $?
done < "$CONF"
printf "no such task: %s\n" "$want" >&2; exit 1
