#!/usr/bin/env bash
# Status line: current story and phase, so the lock is never a surprise.
set -uo pipefail
HOOK_INPUT="$(cat)"
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh" 2>/dev/null || exit 0

load_state
branch="$(git -C "$HARNESS_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-')"
if [ "$PHASE" = "IDLE" ]; then
  printf '%s  |  no active story' "$branch"
else
  printf '%s  |  %s  %s' "$branch" "${STORY_ID}" "${PHASE}"
fi
