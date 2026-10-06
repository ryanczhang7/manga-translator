#!/usr/bin/env bash
# This project's own pins on its REAL `integration` gate. They lived in the
# upstream-owned gates.test.sh until the release-81 harness refresh, which
# replaces that file: upstream's suites never assert a consuming project's
# manifest values (agentic-dev-harness issue #97, port audit "Decided"), so
# they moved here, where a refresh keeps them.
#
# Origins: MT-037 (5a51681) wrote them; MT-019 (9b45911) moved the floor pin
# from 26 to 39. The gate machinery they exercise is upstream's `skipped-when`
# (HARNESS-028), so only the manifest values are this project's claim.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT
set_phase "$FIX" ""

gates() { ( cd "$FIX" && bash scripts/gates.sh "$@" 2>&1 ); }

# The manifest itself, not a fixture copy of it. A suite that only ever asks
# gates.sh about a conf it wrote itself goes green while the REAL integration
# gate still reports PASS on a machine that ran one of its tests - and that
# machine is every worktree this harness dispatches into.
REAL_CONF="$REPO_ROOT/.claude/harness/project.conf"
# One awk over the file, no pipeline: the upstream copy piped grep into
# `head -1`, which check-sigpipe.sh refuses under pipefail.
real_conf_value() { # <kind> <gate id>
  awk -F'|' -v k="$1" -v g="$2" '
    { a = $1; b = $2; gsub(/^[ \t]+|[ \t]+$/, "", a); gsub(/^[ \t]+|[ \t]+$/, "", b) }
    a == k && b == g { v = $0; sub(/^[^|]*\|[^|]*\|/, "", v); gsub(/^[ \t]+|[ \t]+$/, "", v); print v; exit }
  ' "$REAL_CONF"
}

describe "the real integration gate: floor and skipped-when"

# 39 is settled (raised from 26 by MT-019, which added 13 GPU tests to
# `tests/integration -m "gpu or network"`; observed `40 passed` in its stamped
# record, one of which never skips). Not re-derived here.
assert_eq "the manifest gives integration a floor of 39" \
  "39" "$(real_conf_value floor integration)"
# `skipped` and NOT `deselected`, exactly. A skip is the tests deciding at call
# time that their inputs are absent; a deselection is the gate's own marker
# expression, which is a change to the manifest and therefore a regression. A
# pattern widened to cover `deselected` would excuse that regression, and would
# do it in one word nobody would notice.
assert_eq "and a skipped-when pattern that matches skips only" \
  "[1-9][0-9]* skipped" "$(real_conf_value skipped-when integration)"

describe "the real integration lines, end to end"

# The real manifest's own integration lines lifted into the fixture, only the
# command replaced. MT-037 PO-1 reproduced mechanically: a machine without the
# models or the API key runs 1 test and skips the rest.
SKIPCMD='printf "1 passed, 25 skipped in 0.46s\n"'
{ printf 'gate         | integration | optional | . | %s\n' "$SKIPCMD"
  grep -E '^[[:space:]]*(evidence|floor|skipped-when)[[:space:]]*\|[[:space:]]*integration[[:space:]]*\|' "$REAL_CONF"
} | write_conf "$FIX"
out="$(gates)"
assert_not_contains "a run that skipped 25 of its tests is not a PASS" \
  "PASS         integration" "$out"
# The half the line above cannot say: it is reported as the environment's
# shortfall (KNOWN, for an optional gate), not dropped or failed.
assert_contains "it is reported KNOWN, the environment's shortfall" \
  "KNOWN        integration" "$out"

summary "project-gates"
