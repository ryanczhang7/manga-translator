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

DRY=0
BASE=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) printf 'ci-local: unknown option %s\n' "$a" >&2; exit 2 ;;
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

steps=(
  "selftest|bash scripts/selftest.sh"
  "gate list|bash scripts/gates.sh --list"
  "manifest audit|bash scripts/gates.sh --audit"
  "gates|bash scripts/gates.sh"
  "boundaries|bash scripts/check-boundaries.sh $BASE"
)

if [ "$DRY" = 1 ]; then
  for s in "${steps[@]}"; do printf '%s\n' "${s#*|}"; done
  exit 0
fi

dirty="$(git status --porcelain 2>/dev/null | grep -vE '^\?\?' | head -1)"
[ -n "$dirty" ] && printf 'note: uncommitted changes are staged out of the boundaries check, which judges HEAD (%s) as CI does\n\n' "${PR_HEAD_SHA:0:7}"

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

printf 'ci-local: every step CI runs passed locally, against base %s at commit %s.\n' "$BASE" "${PR_HEAD_SHA:0:7}"
printf 'This is one machine and one moment. It is not the PR check, and it cannot be a required one.\n'
