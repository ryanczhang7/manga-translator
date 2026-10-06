#!/usr/bin/env bash
# Tests for scripts/phase.sh and the story frontmatter readers in lib.sh.
#
# phase.sh is the only supported way to change phase, so the checks it makes -
# unmet dependencies, the wrong branch - are load-bearing: an agent that gets
# past them starts writing code under a lock that says something untrue.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT

export CLAUDE_PROJECT_DIR="$FIX"
. "$REPO_ROOT/.claude/hooks/lib.sh"

phase() { ( cd "$FIX" && bash scripts/phase.sh "$@" 2>&1 ); }
new_story() { ( cd "$FIX" && bash scripts/new-story.sh "$@" 2>&1 ); }
sfile() { printf '%s/docs/backlog/stories/%s.md' "$FIX" "$1"; }

# ---------------------------------------------------------------------------
describe "frontmatter readers"

story "$FIX" T-9 PLANNED <<'EOF'
depends_on: [T-7, T-8]
required_gates: [integration]
EOF

assert_eq "a scalar"            "T-9"       "$(frontmatter_value "$(sfile T-9)" id)"
assert_eq "a phase"             "PLANNED"   "$(frontmatter_value "$(sfile T-9)" phase)"
assert_eq "an inline list"      "T-7 T-8 "  "$(frontmatter_list "$(sfile T-9)" depends_on | tr '\n' ' ')"
assert_eq "a one-element list"  "integration " "$(frontmatter_list "$(sfile T-9)" required_gates | tr '\n' ' ')"
assert_eq "a key that is absent" ""         "$(frontmatter_list "$(sfile T-9)" nope)"

# The block form, which YAML allows and an agent may well write by hand.
cat > "$(sfile T-10)" <<'EOF'
---
id: T-10
title: Block form
type: feature
status: todo
phase: PLANNED
depends_on:
  - T-7
  - T-8
---

## Acceptance criteria
EOF
assert_eq "a block list" "T-7 T-8 " "$(frontmatter_list "$(sfile T-10)" depends_on | tr '\n' ' ')"

# ---------------------------------------------------------------------------
describe "new-story.sh writes a story the harness can read"

out="$(new_story T-11 "A hex grid renders" EPIC-1 feature)"
assert_contains "it says where it went" "docs/backlog/stories/T-11.md" "$out"
assert_eq "id"       "T-11"                    "$(frontmatter_value "$(sfile T-11)" id)"
assert_eq "phase"    "PLANNED"                 "$(frontmatter_value "$(sfile T-11)" phase)"
assert_eq "branch"   "story/T-11-a-hex-grid-renders" "$(frontmatter_value "$(sfile T-11)" branch)"
assert_eq "required_gates starts empty" "" "$(frontmatter_list "$(sfile T-11)" required_gates | tr -d ' ')"

# ---------------------------------------------------------------------------
describe "phase.sh set: the branch has to match"

out="$(phase set T-11 RED)"
assert_contains "it refuses on the wrong branch" "belongs on" "$out"
assert_eq "and the story did not move" "PLANNED" "$(frontmatter_value "$(sfile T-11)" phase)"

git -C "$FIX" checkout -q -b story/T-11-a-hex-grid-renders
out="$(phase set T-11 RED)"
assert_contains "on the right branch it moves" "T-11 -> RED" "$out"

# A phase name that merely regex-matches a row is not a phase. `GREEN.` was
# accepted, written to the state file, and phase_allows - finding no such row
# - fell back to "unknown phase, do not block": the lock off, by typo.
out="$(phase set T-11 'GREEN.')"
assert_contains "a regex-matching phase name is refused" "unknown phase" "$out"
assert_eq "and the story did not move" "RED" "$(frontmatter_value "$(sfile T-11)" phase)"
assert_eq "frontmatter phase"  "RED"         "$(frontmatter_value "$(sfile T-11)" phase)"
assert_eq "frontmatter status" "in-progress" "$(frontmatter_value "$(sfile T-11)" status)"
assert_contains "and the hooks can see it" "PHASE=RED" "$(cat "$FIX/.claude/state/current-story.env")"

# `GREEN.` is KEPT, and it is also not the input that discriminates. As an awk
# regex it requires a sixth character, so it fails to match the row `GREEN`
# under `~` exactly as it does under `==` - the control for the defect cannot
# tell the fixed implementation from the broken one. A test named for the
# property it checks, using an input that cannot fail, is what this replaces.
#
# The inputs that DO discriminate are the ones where the typo is a prefix or a
# substring of a real phase. `cmd_set` uppercases its argument, so a fat-fingered
# `gree` arrives here as `GREE`.
for bad in GREE RE D; do
  out="$(phase set T-11 "$bad")"
  assert_contains "a phase name that is a prefix of a real one is refused: $bad" "unknown phase" "$out"
done
# And the metacharacter that matches every row at once.
out="$(phase set T-11 '.')"
assert_contains "so is a regex metacharacter matching any row" "unknown phase" "$out"

# Refusing is only half of it: nothing may have moved. A refusal that had
# already written the state file would leave the guard reading a phase the
# story does not claim.
assert_eq "and after all of them the story is still RED" "RED" "$(frontmatter_value "$(sfile T-11)" phase)"
assert_contains "and so is the state the hooks read" "PHASE=RED" "$(cat "$FIX/.claude/state/current-story.env")"

# --- the branch frontmatter, which is what check-boundaries reads ------------
#
# `check-boundaries.sh` finds the story that CLAIMS a branch by reading this
# key; with no claimant it skips eight checks and says so. new-story.sh writes
# it too, so on the common path this write is redundant - it is load-bearing for
# a story file written or edited by hand, and for one whose branch changed,
# which is exactly the file this fixture builds.
git -C "$FIX" checkout -q -b story/T-12-nobranch 2>/dev/null
mkdir -p "$FIX/docs/backlog/stories"
{
  printf -- '---\nid: T-12\ntitle: No branch key\nslug: nobranch\ntype: feature\nstatus: todo\nphase: PLANNED\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n'
} > "$FIX/docs/backlog/stories/T-12.md"
out="$(phase set T-12 RED)"
assert_contains "a story file with no branch: key still moves" "T-12 -> RED" "$out"
fm_branch="$(frontmatter_value "$FIX/docs/backlog/stories/T-12.md" branch)"
state_branch="$(sed -nE 's/^BRANCH=//p' "$FIX/.claude/state/current-story.env" | head -1)"
assert_eq "and the branch key is written into the frontmatter" "story/T-12-nobranch" "$fm_branch"
assert_eq "matching the branch the hooks were told about" "$state_branch" "$fm_branch"

# ---------------------------------------------------------------------------
describe "phase.sh set: dependencies have to be DONE"

story "$FIX" T-12 PLANNED <<'EOF'
depends_on: [T-11]
EOF
git -C "$FIX" checkout -q -b story/T-12-fixture
out="$(phase set T-12 RED)"
assert_contains "it refuses"        "depends on stories that are not DONE" "$out"
assert_contains "and names the one" "T-11" "$out"

out="$(phase set T-12 RED --force)"
assert_contains "--force says what it overrode" "warning: --force overrides unmet dependencies" "$out"
assert_eq "and moves the story" "RED" "$(frontmatter_value "$(sfile T-12)" phase)"

phase set T-11 DONE >/dev/null
git -C "$FIX" checkout -q story/T-12-fixture
out="$(phase set T-12 GREEN)"
assert_contains "with the dependency DONE it just moves" "T-12 -> GREEN" "$out"

phase clear >/dev/null

# ---------------------------------------------------------------------------
describe "phase.sh set <id> DONE ends with the plan.sh after report (HARNESS-018 AC-6)"

# Closing a story is the moment the next one is chosen, so the report that
# answers "what next, with which command, and what can run alongside it" is
# printed by the command that closes it, rather than reconstructed by hand.
#
# THE SUFFIX IS COMPARED WHOLE: the output must END with exactly what
# `plan.sh after K-1` prints, after one blank line. That report is captured on
# its own and must itself contain the Next line this backlog implies, so an
# empty report - which a suffix check alone would accept - fails here.
#
# stdout only: the Contract sends plan.sh's stderr to stderr.
#
# The backlog the report reads is everything this file built above, plus:
#   K-1  REVIEW, the story being closed
#   K-2  PLANNED, ordinary - first startable in glob order (K-* sorts before T-*)
story "$FIX" K-1 REVIEW </dev/null
story "$FIX" K-2 PLANNED <<'EOF'
touches: [src/k2.ts]
EOF
done_out="$( cd "$FIX" && bash scripts/phase.sh set K-1 DONE 2>/dev/null )"
after_out="$( cd "$FIX" && bash scripts/plan.sh after K-1 2>/dev/null )"
after_has_next="$(grep -cxF 'Next:      /complete-story K-2' <<<"$after_out")"
case "$done_out" in
  *$'\n\n'"$after_out") ends=ends ;;
  *) ends=does-not-end ;;
esac
assert_eq "AC-6: phase.sh set K-1 DONE ends with a blank line and then exactly what plan.sh after K-1 prints, and that report names Next" \
  "ends|1" "$ends|$after_has_next"
assert_eq "AC-6: the phase change itself is reported first, on the first line" \
  "K-1 -> DONE" "$(head -n 1 <<<"$done_out")"
assert_eq "AC-6: the after report's header and Next line both come after the -> DONE line" \
  "1|yes" "$(grep -cxF 'After K-1:' <<<"$done_out")|$(awk '
    $0 == "K-1 -> DONE" { d = NR } $0 == "After K-1:" { h = NR } index($0, "Next:      ") == 1 { n = NR }
    END { print ((d && h > d && n > h) ? "yes" : "no") }' <<<"$done_out")"
assert_eq "AC-6: and the phase change happened" "DONE" "$(frontmatter_value "$(sfile K-1)" phase)"

# CONTROL: any other phase prints no report. Each paired with the presence of
# its own `-> PHASE` line, so a run that printed nothing cannot pass.
git -C "$FIX" checkout -q -b story/K-2-fixture
for ph in RED GREEN GATES REVIEW PLANNED; do
  o="$( cd "$FIX" && bash scripts/phase.sh set K-2 "$ph" 2>/dev/null )"
  assert_eq "AC-6 control: phase.sh set K-2 $ph prints no after report" "1|0|0" \
    "$(grep -cxF "K-2 -> $ph" <<<"$o")|$(grep -c '^Next:' <<<"$o")|$(grep -c '^After K-2:' <<<"$o")"
done
phase clear >/dev/null

# The prose sites. These are read from the REAL tree, not the fixture: they are
# the instructions the orchestrator follows at the moment a story closes, and
# each must tell it to relay the report by naming the command that prints it.
for doc in .claude/commands/advance-story.md .claude/commands/complete-story.md .claude/agents/lead-po.md; do
  if grep -qF 'bash scripts/plan.sh after' "$REPO_ROOT/$doc"; then got=names; else got=silent; fi
  assert_eq "AC-6: $doc names bash scripts/plan.sh after" "names" "$got"
done

summary "phase"
