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
done_rc=$?
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

# HARNESS-066 C-7, the failure path: this fixture has no `origin`, so tidy.sh
# cannot resolve its default base and exits 2 without a census. The DONE
# report then carries no tidy line at all and the phase change still exits 0 -
# the same rule the block applies to plan.sh. The precondition is what keeps
# the silence from being satisfied by tidy.sh simply not being there: it is
# red until GREEN ships scripts/tidy.sh, which make_project_fixture copies in.
assert_eq "HARNESS-066 AC-6 precondition: this fixture carries scripts/tidy.sh and has no origin/main, so tidy fails here" \
  "present|unresolved" \
  "$([ -f "$FIX/scripts/tidy.sh" ] && printf present || printf absent)|$(git -C "$FIX" rev-parse -q --verify origin/main >/dev/null 2>&1 && printf resolved || printf unresolved)"
assert_eq "HARNESS-066 AC-6 (C-7): a tidy that fails adds no line to the DONE report - no line begins tidy:" \
  0 "$(awk 'index($0, "tidy:") == 1 { c++ } END { print c + 0 }' <<<"$done_out")"
assert_eq "HARNESS-066 AC-6 (C-7): and does not fail the phase change - phase.sh set K-1 DONE exits 0" 0 "$done_rc"

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


# ---------------------------------------------------------------------------
# HARNESS-046 runs in a fixture of its own: phase.sh set writes the state file
# and moves frontmatter, and every block above depends on the state $FIX is in.
P46="$(make_project_fixture)"
trap 'rm -rf "$FIX" "$P46"' EXIT
p46() { ( cd "$P46" && bash scripts/phase.sh "$@" ); }

describe "HARNESS-046 AC-2: phase.sh set refuses an id that is not one path component"

# A story-shaped file one directory ABOVE the stories directory, inside the
# fixture: from docs/backlog/stories, ../EXIST is docs/backlog/EXIST.md (C-6).
# Measured on today's phase.sh, 2026-10-09: exit 0, EXIST.md rewritten (status
# and `branch: story/../EXIST-e` added), STORY_ID=../EXIST persisted.
printf -- '---\nid: EXIST\ntitle: Exists outside the stories directory\nslug: exist\ntype: feature\nstatus: todo\nphase: PLANNED\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n' \
  > "$P46/docs/backlog/EXIST.md"
cp "$P46/docs/backlog/EXIST.md" "$P46/EXIST.before"
rm -f "$P46/.claude/state/current-story.env"
assert_eq "HARNESS-046 AC-2 precondition: no current-story.env before the run" absent \
  "$([ -e "$P46/.claude/state/current-story.env" ] && printf present || printf absent)"

h46_err="$(p46 set ../EXIST PLANNED 2>&1 >/dev/null)"; h46_rc=$?
assert_eq "HARNESS-046 AC-2: phase.sh set ../EXIST PLANNED exits 1" 1 "$h46_rc"
assert_contains "HARNESS-046 AC-2: and prints the grammar message naming ../EXIST on stderr" \
  "error: story id '../EXIST' is not one path component: an id is letters, digits, '.', '_' or '-', and starts with a letter or digit" \
  "$h46_err"
assert_eq "HARNESS-046 AC-2: docs/backlog/EXIST.md is byte-for-byte unchanged" unchanged \
  "$(cmp -s "$P46/EXIST.before" "$P46/docs/backlog/EXIST.md" && printf unchanged || printf changed)"
assert_eq "HARNESS-046 AC-2: and current-story.env still does not exist" absent \
  "$([ -e "$P46/.claude/state/current-story.env" ] && printf "present: $(grep '^STORY_ID=' "$P46/.claude/state/current-story.env")" || printf absent)"

describe "HARNESS-046 AC-4: every id shape in use still works"

# The controls for the refusal: a grammar narrower than the settled one turns
# one of these red. new-story.sh then phase.sh set <id> PLANNED, both exit 0,
# and the story file is where it should be. PLANNED, because guard_transition
# skips it: this asserts the id check, not the branch or dependency checks.
for id in HARNESS-046 WORLD-014 T-1 T-A K-2 MT-071 a.b_c-1 x; do
  ( cd "$P46" && bash scripts/new-story.sh "$id" "x" >/dev/null 2>&1 ); h46_ns=$?
  p46 set "$id" PLANNED >/dev/null 2>&1; h46_ps=$?
  [ -f "$P46/docs/backlog/stories/$id.md" ] && h46_f=file || h46_f="no file"
  assert_eq "HARNESS-046 AC-4: new-story.sh $id then phase.sh set $id PLANNED both exit 0 and create docs/backlog/stories/$id.md" \
    "0|0|file" "$h46_ns|$h46_ps|$h46_f"
done

# ---------------------------------------------------------------------------
# HARNESS-066 AC-6 runs in a fixture of its own, with a real bare `origin` and
# `main` pushed to it, so tidy.sh's default base resolves; a real linked
# worktree (never a copy) and a real merged branch give it something to count.
describe "HARNESS-066 AC-6: phase.sh set <id> DONE prints tidy's census before the plan.sh after report"

P66="$(make_project_fixture)"
P66W="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
cleanup66() {
  local w
  for w in "$P66W/q-rm" "$P66W/q-keep"; do
    git -C "$P66" worktree remove --force "$w" >/dev/null 2>&1
  done
  git -C "$P66" worktree prune >/dev/null 2>&1
  rm -rf "$FIX" "$P46" "$P66" "$P66W"
}
trap cleanup66 EXIT
p66() { ( cd "$P66" && bash scripts/phase.sh "$@" 2>/dev/null ); }
line66() { awk -v n="$2" 'NR == n { print; exit }' <<<"$1"; }
count66() { awk 'BEGIN { l = ARGV[2]; ARGV[2] = "" } $0 == l { c++ } END { print c + 0 }' - "$2" <<<"$1"; }

git -C "$P66" config core.autocrlf false
git init -q --bare "$P66W/origin.git"
git -C "$P66" remote add origin "$P66W/origin.git"
git -C "$P66" push -q origin HEAD:main >/dev/null 2>&1
git -C "$P66" worktree add -q --detach "$P66W/q-rm" HEAD >/dev/null 2>&1
find "$P66W/q-rm" -exec touch -t 202001010000 {} + 2>/dev/null
git -C "$P66" branch story/q-done HEAD
story "$P66" Q-1 REVIEW </dev/null
story "$P66" Q-2 REVIEW </dev/null

assert_eq "HARNESS-066 AC-6 precondition: q-rm is merged into origin/main, clean, unlocked and idle; story/q-done is merged, checked out nowhere, with no origin copy" \
  "merged|clean|unlocked|0|merged|0|noremote" \
  "$(git -C "$P66" merge-base --is-ancestor "$(git -C "$P66W/q-rm" rev-parse HEAD)" origin/main && printf merged || printf unmerged)|$([ -z "$(git -C "$P66W/q-rm" status --porcelain --untracked-files=all)" ] && printf clean || printf dirty)|$(count66 "$(git -C "$P66" worktree list --porcelain)" locked | awk '{ print ($1 ? "locked" : "unlocked") }')|$(find "$P66W/q-rm" -type f -mmin -1440 | awk 'END { print NR }')|$(git -C "$P66" merge-base --is-ancestor story/q-done origin/main && printf merged || printf unmerged)|$(count66 "$(git -C "$P66" worktree list --porcelain)" 'branch refs/heads/story/q-done')|$(git -C "$P66" rev-parse -q --verify refs/remotes/origin/story/q-done >/dev/null 2>&1 && printf remote || printf noremote)"

CEN66='tidy: 1 worktree(s), 1 removable, 0 kept; 1 merged branch(es) deletable'
APPLY66='tidy: run bash scripts/tidy.sh --apply to remove them'
d66="$(p66 set Q-1 DONE)"; d66_rc=$?
a66="$( cd "$P66" && bash scripts/plan.sh after Q-1 2>/dev/null )"
assert_eq "HARNESS-066 AC-6: the first two lines are still -> DONE and writes allowed:" \
  "Q-1 -> DONE|writes allowed: " "$(line66 "$d66" 1)|$(line66 "$d66" 2 | awk '{ print (index($0, "writes allowed: ") == 1 ? "writes allowed: " : $0) }')"
assert_eq "HARNESS-066 AC-6: the census is the third line, straight after writes allowed:" "$CEN66" "$(line66 "$d66" 3)"
assert_eq "HARNESS-066 AC-6: with one removable worktree and one deletable branch, the fourth line says how to remove them" \
  "$APPLY66" "$(line66 "$d66" 4)"
assert_eq "HARNESS-066 AC-6: each appears exactly once" "1|1" "$(count66 "$d66" "$CEN66")|$(count66 "$d66" "$APPLY66")"
case "$d66" in
  *"$CEN66"$'\n'"$APPLY66"$'\n\n'"$a66") e66=ends ;;
  *) e66=does-not-end ;;
esac
assert_eq "HARNESS-066 AC-6: then one blank line, and the output still ENDS with exactly what plan.sh after Q-1 prints (non-empty)" \
  "ends|nonempty" "$e66|$([ -n "$a66" ] && printf nonempty || printf empty)"
assert_eq "HARNESS-066 AC-6: DONE never applies - the removable worktree is still on disk and registered, and the branch still exists" \
  "there|1|story/q-done" \
  "$([ -d "$P66W/q-rm" ] && printf there || printf gone)|$(count66 "$(git -C "$P66" worktree list --porcelain)" "worktree $(git -C "$P66W/q-rm" rev-parse --show-toplevel 2>/dev/null)")|$(git -C "$P66" for-each-ref --format='%(refname:short)' refs/heads/story/q-done)"
assert_eq "HARNESS-066 AC-6: and the phase change happened, exit 0" "DONE|0" "$(frontmatter_value "$P66/docs/backlog/stories/Q-1.md" phase)|$d66_rc"

# Nothing to tidy: the removable worktree and the branch are gone, and the one
# worktree left is fresh, so KEEP recent. R + M = 0, N = 1: the census alone.
git -C "$P66" worktree remove "$P66W/q-rm" >/dev/null 2>&1
git -C "$P66" branch -D story/q-done >/dev/null 2>&1
git -C "$P66" worktree add -q --detach "$P66W/q-keep" HEAD >/dev/null 2>&1
CEN66B='tidy: 1 worktree(s), 0 removable, 1 kept; 0 merged branch(es) deletable'
assert_eq "HARNESS-066 AC-6 precondition: q-rm and story/q-done are gone, q-keep is registered and holds a file modified in the last day" \
  "gone||yes" \
  "$([ -e "$P66W/q-rm" ] && printf there || printf gone)|$(git -C "$P66" for-each-ref --format='%(refname:short)' refs/heads/story/q-done)|$([ -n "$(find "$P66W/q-keep" -type f -mmin -1440 | awk 'NR == 1')" ] && printf yes || printf no)"
d66b="$(p66 set Q-2 DONE)"
a66b="$( cd "$P66" && bash scripts/plan.sh after Q-2 2>/dev/null )"
assert_eq "HARNESS-066 AC-6: with nothing removable or deletable, the third line is the census alone" "$CEN66B" "$(line66 "$d66b" 3)"
assert_eq "HARNESS-066 AC-6: and there is no apply line" 0 "$(count66 "$d66b" "$APPLY66")"
case "$d66b" in
  *"$CEN66B"$'\n\n'"$a66b") e66b=ends ;;
  *) e66b=does-not-end ;;
esac
assert_eq "HARNESS-066 AC-6: census, one blank line, then exactly what plan.sh after Q-2 prints, to the end" "ends" "$e66b"

summary "phase"
