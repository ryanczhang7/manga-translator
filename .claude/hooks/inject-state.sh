#!/usr/bin/env bash
# UserPromptSubmit hook: keep the current story and phase in front of the model
# on every turn, so a long orchestration loop cannot quietly lose its place.

set -uo pipefail
HOOK_INPUT="$(cat)"
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh" 2>/dev/null || exit 0

load_state
[ "$PHASE" = "IDLE" ] && exit 0

STORY_FILE="$HARNESS_ROOT/docs/backlog/stories/${STORY_ID}.md"
cat <<TXT
<harness-state>
Active story: ${STORY_ID} — ${STORY_SLUG:-}
Phase: ${PHASE} (${STORY_TYPE:-feature} story)
Branch: ${BRANCH:-<none>}
Story file: docs/backlog/stories/${STORY_ID}.md$([ -f "$STORY_FILE" ] || printf ' (MISSING)')
Writes allowed this phase: $(phase_categories)
$(phase_message)
Advance with: bash scripts/phase.sh set ${STORY_ID} <PHASE>   |   Board: bash scripts/phase.sh show
</harness-state>
TXT
exit 0
