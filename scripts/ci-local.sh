#!/usr/bin/env bash
# Run, locally and in order, exactly what CI runs.
#
#   bash scripts/ci-local.sh              against origin/main
#   bash scripts/ci-local.sh origin/dev   against another base
#   bash scripts/ci-local.sh --dry-run    print the steps, run none of them
#
# The two workflows in .github/workflows are five bash commands between them, so
# there is no reason to need a runner to find out whether they pass. This script
# is that sequence, and `.claude/tests/ci-local.test.sh` derives the expected
# list FROM the workflow files: add a step to gates.yml without adding it here
# and the selftest fails. That test is the only thing that keeps a green local
# run honest, because the script's whole claim is "the same sequence".
#
# WHAT IT DOES NOT REPLACE, and this matters more than what it does:
#
#   * It is THIS machine. Every finding this harness carries about CI - a
#     coverage gate that times out only on a runner, a hook whose cost lands in
#     teardown on software GL, a gate an OS policy refuses to launch - is a
#     failure that a local run reports as green. For the unbootstrapped harness
#     there is nothing stack-specific to differ; for a project built on it,
#     there is, and "it passed locally" was the sentence in front of each of
#     those.
#   * It runs when you remember. The boundaries workflow exists as defence in
#     depth for the diff the phase-guard hook never saw - a human commit,
#     another tool, a force-push - and a script you have to invoke cannot cover
#     the case where nobody was in the loop.
#   * It cannot be a required check. Branch protection can only require a run
#     GitHub performed.
#
# So: use it to get the answer in seconds instead of minutes, and to know a PR
# will pass before opening it. Do not read a green run here as a merged-ready
# story if the PR's own checks never ran.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
WFDIR="$ROOT/.github/workflows"

DRY=0
BASE=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) printf '[ci-local] unknown option %s\n' "$a" >&2; exit 2 ;;
    *) BASE="$a" ;;
  esac
done

# The base ref for the boundaries check. CI checks out with fetch-depth 0 and
# diffs against origin/<base>, so a stale local origin/main would compare
# against a commit nobody is merging into - a wrong answer that looks like an
# answer. Fetch quietly and carry on if there is no remote (a fixture, an
# offline machine): check-boundaries.sh says so itself and skips the diff
# checks rather than guessing.
if [ -z "$BASE" ]; then
  main_branch="$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
  [ -n "$main_branch" ] || main_branch=main
  git fetch -q origin "$main_branch" 2>/dev/null
  BASE="origin/$main_branch"
fi

# PR_HEAD_SHA is what the boundaries workflow sets, and it is not cosmetic:
# with it, check-boundaries.sh recomputes the gate tree hash at that COMMIT;
# without it, at the working tree. CI judges the commit, so this does too -
# which means uncommitted changes are invisible to the last step, and it says so
# below rather than letting you find out on the PR.
PR_HEAD_SHA="$(git rev-parse HEAD 2>/dev/null || true)"
export PR_HEAD_SHA

# The steps are READ from the workflows, never listed here. The first version
# hardcoded this repository's five commands, and its test asserted they matched
# the workflow files - which they did, by construction, in this repository. In a
# consuming project the workflow legitimately adds toolchain setup, so the
# hardcoded list was both missing steps CI runs and inventing steps it does not,
# and the assertion failed permanently in a suite nobody there could make green.
#
# Reading them means the script is correct in any project without knowing
# anything about it. gates.yml goes first where it exists, because it carries the
# selftest and the fast checks and there is no sense discovering a broken harness
# after a full build; everything else follows in name order.
workflow_files() {
  local first="$WFDIR/gates.yml" f
  [ -f "$first" ] && printf '%s\n' "$first"
  for f in "$WFDIR"/*.yml; do
    [ -e "$f" ] || continue
    [ "$f" = "$first" ] && continue
    printf '%s\n' "$f"
  done
}

# `run:` steps in file order. A block scalar (`run: |`) is one step whose body
# spans lines: its lines are emitted individually, because dropping the body
# would run a truncated command, which is worse than skipping the step.
workflow_steps() { # <workflow file>
  awk '
    function flush(  i) { for (i = 1; i <= n; i++) print buf[i]; n = 0 }
    /^[[:space:]]*(-[[:space:]]+)?run:[[:space:]]*[|>]/ { flush(); inblock = 1; ind = -1; next }
    inblock {
      if ($0 ~ /^[[:space:]]*$/) next
      match($0, /^[[:space:]]*/); this = RLENGTH
      if (ind < 0) ind = this
      if (this < ind) { inblock = 0 }
      else { line = $0; sub(/^[[:space:]]+/, "", line); buf[++n] = line; next }
    }
    /^[[:space:]]*(-[[:space:]]+)?run:[[:space:]]*[^|>[:space:]]/ {
      flush(); line = $0
      sub(/^[[:space:]]*(-[[:space:]]+)?run:[[:space:]]*/, "", line)
      buf[++n] = line
      next
    }
    END { flush() }
  ' "$1"
}

steps=()
while IFS= read -r wf; do
  [ -n "$wf" ] || continue
  label="$(basename "$wf" .yml)"
  while IFS= read -r cmd; do
    [ -n "$cmd" ] || continue
    # The one expression this script can answer. Actions sets github.base_ref to
    # the PR's target branch; locally that is the base we were given.
    cmd="${cmd//\$\{\{ github.base_ref \}\}/${BASE#origin/}}"
    # Anything else the workflow computes at run time, this cannot. Skipping is
    # the honest answer - guessing would run a command CI never ran - and it is
    # said out loud rather than dropped.
    case "$cmd" in
      *'${{'*) printf 'note: skipping a %s step this cannot resolve locally: %s\n' "$label" "$cmd" >&2; continue ;;
    esac
    steps+=("$label|$cmd")
  done <<< "$(workflow_steps "$wf")"
done <<< "$(workflow_files)"

if [ "${#steps[@]}" -eq 0 ]; then
  printf '[ci-local] no run: steps found in %s - nothing CI does can be reproduced here.\n' "$WFDIR" >&2
  exit 2
fi

if [ "$DRY" = 1 ]; then
  for s in "${steps[@]}"; do printf '%s\n' "${s#*|}"; done
  exit 0
fi

# SAID FIRST, and under the same `ci-local:` prefix as the verdict.
#
# check-boundaries.sh judges the COMMIT, so a run started before committing
# returns a perfectly green verdict about the PREVIOUS commit - a right answer
# to a question nobody asked. That happened three times in one day, and the
# information was not missing: the note below already named HEAD whenever the
# tree was dirty. It was read past twice, because the verdict line began
# `ci-local:` and that is what a reader greps, while the note did not and only
# appeared when the tree happened to be dirty.
#
# So the subject goes first, unconditionally, in the verdict's own shape - and
# the note joins it, because it is also about what is being judged.
#
# AND THE VOICE IS `[ci-local]`, NOT `ci-local:`. The old prefix was not this
# script's alone: `summary <name>` gives every suite a line of the form
# `<name>: N passed, M failed`, and one of those suites is this script's own. So
# `selftest.sh` - a STEP of this very run - emitted `ci-local: 26 passed,
# 0 failed` into the middle of the report, and a waiting loop written against
# `^ci-local:` matched the SUITE's line and called a run finished that had
# barely started. That is not a coincidence to route around: the two things
# genuinely share a name. `[ci-local]` is a shape no `summary` can produce, so
# the script's own voice is now its own.
printf '[ci-local] judging commit %s against base %s\n' "${PR_HEAD_SHA:0:7}" "$BASE"
dirty="$(git status --porcelain 2>/dev/null | grep -vE '^\?\?' | head -1)"
[ -n "$dirty" ] && printf '[ci-local] uncommitted changes are staged out of the boundaries check, which judges HEAD (%s) as CI does\n' "${PR_HEAD_SHA:0:7}"
printf '\n'

# Fail fast, exactly as a runner does. A wrapper that runs every step and
# summarises at the end can print four passes under a failure, and a CI
# substitute that does that is worse than no substitute: the numbers look like
# evidence. The step's own output goes straight to the terminal, so a failure is
# reproducible by rerunning the one command named in the banner.
for s in "${steps[@]}"; do
  label="${s%%|*}"; cmd="${s#*|}"
  printf '=== ci-local: %s ===\n%s\n' "$label" "$cmd"
  if ! eval "$cmd"; then
    rc=$?
    printf '\nFAILED at step "%s" (exit %d):\n  %s\n' "$label" "$rc" "$cmd" >&2
    printf 'Nothing after this step ran, which is what the runner would have done.\n' >&2
    exit 1
  fi
  printf '\n'
done

printf '[ci-local] every step CI runs passed locally, against base %s at commit %s.\n' "$BASE" "${PR_HEAD_SHA:0:7}"
printf 'This is one machine and one moment. It is not the PR check, and it cannot be a required one.\n'
