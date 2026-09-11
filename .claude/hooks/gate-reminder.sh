#!/usr/bin/env bash
# Stop hook: refuse to close a phase on assertion alone.
#
# It blocks on exactly one thing: the story is in GREEN or GATES and the gates
# have not been run since the story entered that phase. Everything else it has
# to say - a recorded failure, a gate the environment would not launch, code
# touched since the run - it says without blocking.
#
# That division is the second design. The first compared the gate stamp against
# file MTIMES, and under `/advance-story` - which ends every invocation
# mid-story by design - "a tracked file is newer than the stamp" is the normal
# state at the end of a phase. It fired at the end of GREEN on a screenshot a
# runner wrote during a deliberate mutation, and at the end of GATES on a gate
# Windows Smart App Control had refused to launch, and both times the only way
# to clear it was to re-run a two-minute suite to satisfy a hook whose own text
# offered "if you are intentionally stopping mid-story, say so explicitly" -
# which it could not read. A hook that can only be cleared by prose it cannot
# read is a hook that trains agents to re-run suites for nothing.
#
# The phase change is the right clock because it is what the obligation attaches
# to: a gate run after it judged this phase's code, and its result is already
# recorded in the story, where the next agent will read it. In GATES the
# obligation is a FULL run - `--fast` and `--gate` write this stamp too, and the
# phase whose whole job is the full suite must not be dischargeable by a subset.
#
# "The code the gates judge", for the warning about changed code, is what
# gated_stdin in lib.sh keeps: source, test, config and the harness's scripts and
# manifests - never docs, prompts, vendor, or anything .gitignore covers.
# Counting generated output would make the hook fire on its own exhaust.

set -uo pipefail
HOOK_INPUT="$(cat)"
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh" 2>/dev/null || exit 0

# Never loop on ourselves.
json_is_true stop_hook_active && exit 0

load_state
case "$PHASE" in GREEN|GATES) ;; *) exit 0 ;; esac

block() {
  printf '{"decision":"block","reason":"%s"}\n' "$(json_escape "$1")"
  exit 0
}

# A Stop hook has two registers: block, or say something and let go. This is the
# second. If a runner does not surface systemMessage the object still carries no
# `decision`, so the stop proceeds - the note is lost, never the loop.
warn() {
  printf '{"continue":true,"systemMessage":"%s"}\n' "$(json_escape "$1")"
  exit 0
}

stamp_value() { grep -E "^$1=" "$GATE_STAMP" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]'; }

# --- the one thing it blocks -------------------------------------------------

if [ ! -f "$GATE_STAMP" ]; then
  block "The gate suite has not been run for story ${STORY_ID} at all.

  bash scripts/gates.sh          in GATES: the full run, recorded in the story
  bash scripts/gates.sh --fast   in GREEN: are the tests admissible to the gates

A phase does not close on the claim that the code is fine."
fi

if [ ! "$GATE_STAMP" -nt "$STATE_FILE" ]; then
  block "The last gate run for story ${STORY_ID} happened before the story entered ${PHASE}, so nothing has judged the code this phase produced. Run the gates:

  bash scripts/gates.sh          in GATES: the full run, recorded in the story
  bash scripts/gates.sh --fast   in GREEN: are the tests admissible to the gates"
fi

if [ "$PHASE" = "GATES" ] && [ "$(stamp_value FULL)" = "no" ]; then
  block "The last gate run for story ${STORY_ID} was a partial one - --fast, --gate or --required. GATES is the phase the full suite exists for, and a partial run is not recorded in the story because it is not evidence of anything:

  bash scripts/gates.sh"
fi

# --- everything else is said, not enforced ----------------------------------

note=""
case "$(stamp_value RESULT)" in
  blocked)
    # ## Notes, never ## Gate results: gates.sh rewrites that section on every
    # run, so evidence put there is evidence with an expiry date - and the
    # non-negotiables say nobody but gates.sh writes it. check-boundaries.sh
    # greps the whole story for these lines, so pointing here at the section
    # that loses them would never have complained until it mattered.
    note="The last gate run for story ${STORY_ID} reported BLOCKED: the environment refused to launch a required gate, so it neither passed nor failed. Neither \"fix it\" nor \"back to RED\" applies. Record it in the story's ## Notes as a PO decision with the log line quoted, on one line carrying the gate id and the words 'pending CI', take the story to REVIEW with that gate pending, and do not call it DONE until the PR's CI run for that gate is quoted in ## Notes on a line carrying the gate id and the run URL." ;;
  fail)
    note="The last gate run for story ${STORY_ID} FAILED, and that result is recorded in the story. Fix the cause, or - if the failure means a test is wrong - return the story to RED and say so in ## Regressions. Do not weaken the test." ;;
esac

# Deliberately not a block. An orchestrator mutating production code to check
# the suite discriminates, then reverting it, has touched a tracked file after
# the gate run on purpose, and the revert is the point.
newer="$(code_changed_since "$GATE_STAMP")"
if [ -n "$newer" ]; then
  note="${note:+$note

}Code the gates judge has changed since that run (e.g. ${newer}). If the change was a deliberate probe you reverted, nothing to do. If it was real, the recorded run no longer describes this tree - and check-boundaries.sh will say so on the PR, because the record carries a hash of the code it ran against."
fi

[ -z "$note" ] && exit 0
warn "$note"
