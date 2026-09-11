#!/usr/bin/env bash
# Tests for scripts/ci-local.sh - the local run of what CI runs.
#
# The script's whole value is that it is the SAME sequence, and that is exactly
# the property that rots: somebody adds a step to gates.yml, nobody adds it here,
# and a green local run starts meaning less than it says. So the load-bearing
# test is not "does it work" - it is "does it still agree with the workflows",
# derived from the workflow files rather than from a list copied out of them.
#
# The other half is fail-fast. A runner stops a job at the first failing step;
# a script that carries on and prints a summary at the end can report four
# passes under a failure, which is the one thing a CI substitute must not do.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

SCRIPT="$REPO_ROOT/scripts/ci-local.sh"
WF="$REPO_ROOT/.github/workflows"

# ---------------------------------------------------------------------------
describe "it runs what the workflows run"

# --dry-run prints the commands and executes none of them, which is what makes
# this checkable at all: the alternative is running the real suite to find out
# what it would have run.
dry="$( bash "$SCRIPT" --dry-run 2>&1 )"
assert_eq "--dry-run succeeds" 0 "$?"

# Every `run:` line in either workflow, normalised: the Actions expression for
# the base ref becomes the literal the script uses, and nothing else is touched.
# A step added to a workflow and not here fails this, which is the point.
missing=""
while IFS= read -r cmd; do
  [ -z "$cmd" ] && continue
  case "$cmd" in
    *'${{'*) cmd="$(printf '%s' "$cmd" | sed -E 's/origin\/\$\{\{ github\.base_ref \}\}/origin\/BASE/')" ;;
  esac
  printf '%s\n' "$dry" | sed -E 's/origin\/[A-Za-z0-9._\/-]+/origin\/BASE/' \
    | grep -qF -- "$cmd" || missing="$missing
  $cmd"
done <<< "$(grep -hE '^[[:space:]]*run:' "$WF"/gates.yml "$WF"/boundaries.yml \
             | sed -E 's/^[[:space:]]*run:[[:space:]]*//')"
assert_eq "every workflow step appears in the script" "" "$missing"

# And the reverse direction, because a local script that quietly runs MORE than
# CI is a different kind of lie: a green local run would then be a stronger
# claim than the PR check it stands in for.
extra=""
while IFS= read -r line; do
  case "$line" in
    ''|'#'*) continue ;;
    *"scripts/"*) ;;
    *) continue ;;
  esac
  norm="$(printf '%s' "$line" | sed -E 's/^[[:space:]]+//; s/origin\/[A-Za-z0-9._\/-]+/origin\/BASE/')"
  grep -hE '^[[:space:]]*run:' "$WF"/gates.yml "$WF"/boundaries.yml \
    | sed -E 's/^[[:space:]]*run:[[:space:]]*//; s/origin\/\$\{\{ github\.base_ref \}\}/origin\/BASE/' \
    | grep -qF -- "$norm" || extra="$extra
  $norm"
done <<< "$dry"
assert_eq "the script runs no step CI does not" "" "$extra"

# PR_HEAD_SHA is not decoration. Without it check-boundaries.sh hashes the
# WORKING TREE, and with it the commit - so a local run that omits it answers a
# different question from the PR check it is standing in for.
assert_contains "it sets PR_HEAD_SHA the way the workflow does" "PR_HEAD_SHA" "$(cat "$SCRIPT")"

# ---------------------------------------------------------------------------
describe "it stops at the first failing step, like a runner"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT
write_conf "$FIX" <<'CONF'
gate     | unit | required | . | printf 'Tests  3 passed (3)\n'
evidence | unit | Tests +[1-9][0-9]* passed
CONF

# The first step, stubbed red. Everything after it must not run: `gates.sh` in
# particular WRITES - it stamps .claude/state/last-gate-run - so "carried on
# after a failure" is observable rather than a matter of reading the output.
printf '#!/usr/bin/env bash\necho "stub selftest: red"\nexit 1\n' > "$FIX/scripts/selftest.sh"
rm -f "$FIX/.claude/state/last-gate-run"
out="$( cd "$FIX" && bash scripts/ci-local.sh 2>&1 )"; rc=$?
assert_eq "a failing first step fails the run" 1 "$rc"
assert_contains "and says which step failed" "selftest" "$out"
if [ -f "$FIX/.claude/state/last-gate-run" ]; then
  _bad "and does not run the steps after it" "gates.sh ran anyway: a stamp was written"
else
  _ok "and does not run the steps after it"
fi

# The failing step's own output has to survive. A wrapper that swallows it and
# prints its own verdict makes every failure a second command to reproduce.
assert_contains "the failing step's output is shown" "stub selftest: red" "$out"

summary "ci-local"
