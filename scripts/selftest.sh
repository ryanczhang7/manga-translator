#!/usr/bin/env bash
# Run the harness's own tests.
#
#   bash scripts/selftest.sh            every suite in .claude/tests
#   bash scripts/selftest.sh phase-guard one suite, by name
#   VERBOSE=1 bash scripts/selftest.sh  name every assertion, not just failures
#
# These test the harness, not the project built with it: the phase lock, the
# path classifier, the hooks. They need bash, git and coreutils and nothing
# else, so they run before a stack has been chosen - which is the point, since
# the harness has to be trustworthy from the first story onwards.
#
# The project's own gates are a separate thing entirely: scripts/gates.sh.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ONLY="${1:-}"

fails=0; ran=0
for suite in "$ROOT"/.claude/tests/*.test.sh; do
  [ -e "$suite" ] || continue
  name="$(basename "$suite" .test.sh)"
  [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && continue
  printf '\n=== %s ===\n' "$name"
  bash "$suite" || fails=$((fails+1))
  ran=$((ran+1))
done

if [ "$ran" -eq 0 ]; then
  printf 'No suites matched%s. Looked in .claude/tests/*.test.sh\n' "${ONLY:+ '$ONLY'}" >&2
  exit 1
fi

printf '\n'
if [ "$fails" -gt 0 ]; then
  printf '%d of %d harness suite(s) FAILED.\n' "$fails" "$ran"
  exit 1
fi
printf '%d harness suite(s) passed.\n' "$ran"
