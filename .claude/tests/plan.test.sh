#!/usr/bin/env bash
# Tests for scripts/plan.sh - which model each phase of a story runs on, and
# which command to drive it with.
#
# Both answers used to be asked of the human every time, which is the condition
# under which they stop being answers and become habits. The model question in
# particular: `rules.md` has said since WORLD-007 that a model choice with no
# recorded verdict is folklore, and the way a choice becomes folklore is that
# nobody writes down why - so the policy lives in a file with a reason per row,
# and the plan is written INTO the story before the phase it applies to.
#
# TWO THINGS ARE TESTED HERE, AND THEY ARE KEPT APART ON PURPOSE.
#
#   * THE SHIPPED POLICY - what `.claude/harness/models.conf` says today. Since
#     release 78 that is a split by kind of work rather than a weaker/stronger
#     ladder: `fable` plans (PLANNED, REVIEW - the orchestrator's judgement
#     phases), `opus` builds and tests (RED, GREEN, GATES, SCAFFOLD), and no
#     row moves with the story. One describe block, against the real file.
#
#   * THE MECHANISM - exceptions, first match wins, and the three conditions
#     (`no-contract`, `unenforced`, `type=`). The shipped policy no longer
#     uses an exception, so a test of the mechanism that read the shipped file
#     would pass for nothing: every RED row is `opus` whether or not the
#     exception fired. So every block after the first runs against
#     MECHANISM_POLICY below, a fixture that keeps the pre-78 shape - RED on
#     `fable` with a brief, back to `opus` without one. In those blocks
#     "the weaker model" means that fixture's base row and "the stronger"
#     its exception rows; it is a statement about the fixture, not about the
#     models.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT

plan() { ( cd "$FIX" && bash scripts/plan.sh "$@" 2>&1 ); }

# story_with <id> <type> <phase> <ac-count> ; section bodies on stdin as
# `SECTION:body` lines, so a case says only what it is about.
#
# `TOUCHES:` is the HARNESS-006 frontmatter declaration, and its three states
# are the ones the Contract distinguishes: no line means no `touches:` key at
# all; `TOUCHES:` with nothing after it writes `touches: []`, the line
# new-story.sh emits into every fresh story; `TOUCHES:a, b` writes
# `touches: [a, b]`. The middle one exists so a test can say "empty list" and
# "absent key" as two different fixtures, because PO decision 1 says they must
# be judged the same and only two fixtures can show that.
#
# `EPIC:<name>` writes `epic: <name>` (HARNESS-018); no line writes no key.
story_with() {
  local id="$1" type="$2" phase="$3" acs="$4" extra contract="" deferred="" deps="" touches="" has_touches=0 epic="" has_epic=0
  extra="$(cat)"
  case "$extra" in *EPIC:*)     has_epic=1; epic="$(printf '%s\n' "$extra" | sed -n 's/^EPIC://p')" ;; esac
  case "$extra" in *CONTRACT:*) contract="$(printf '%s\n' "$extra" | sed -n 's/^CONTRACT://p')" ;; esac
  case "$extra" in *DEFERRED:*) deferred="$(printf '%s\n' "$extra" | sed -n 's/^DEFERRED://p')" ;; esac
  case "$extra" in *DEPENDS:*)  deps="$(printf '%s\n' "$extra" | sed -n 's/^DEPENDS://p')" ;; esac
  case "$extra" in *TOUCHES:*)  has_touches=1; touches="$(printf '%s\n' "$extra" | sed -n 's/^TOUCHES://p')" ;; esac
  mkdir -p "$FIX/docs/backlog/stories"
  {
    printf -- '---\nid: %s\ntitle: Fixture story\nslug: fixture\ntype: %s\nstatus: todo\nphase: %s\nbranch: story/%s-fixture\n' \
      "$id" "$type" "$phase" "$id"
    [ -n "$deps" ] && printf -- 'depends_on: [%s]\n' "$deps"
    [ "$has_touches" = 1 ] && printf -- 'touches: [%s]\n' "$touches"
    [ "$has_epic" = 1 ] && printf -- 'epic: %s\n' "$epic"
    printf -- '---\n\n## Acceptance criteria\n\n'
    local i=1
    while [ "$i" -le "$acs" ]; do printf -- '- **AC-%s** - it works.\n' "$i"; i=$((i+1)); done
    printf -- '\n## Contract\n\n'
    [ -n "$contract" ] && printf -- '%s\n' "$contract"
    printf -- '\n## Deferred verifications\n\n'
    [ -n "$deferred" ] && printf -- '%s\n' "$deferred"
    printf -- '\n## Model guidance\n\n## Gate results\n\n## Notes\n'
  } > "$FIX/docs/backlog/stories/$id.md"
}

# A story that is ordinary in every way the rules below care about: a real
# contract, few criteria, nothing deferred, no dependencies.
ordinary() { story_with "${1:-T-1}" "${2:-feature}" "${3:-PLANNED}" 2 <<'EOF'
CONTRACT:`src/core/world.ts` exports `buildWorld(seed: number): World`.
EOF
}

# ---------------------------------------------------------------------------
describe "the shipped policy: fable plans, opus builds and tests"

# WHY THE SPLIT. Until release 77 the policy was a ladder: `opus` the stronger
# model everywhere, `fable` the weaker one in RED when a brief existed. The
# user's call on 2026-10-05 is that Opus 5.5 is now the better development and
# testing model and Fable the better planner - so the rows split by KIND OF
# WORK: the orchestrator's judgement phases (PLANNED, REVIEW) on `fable`, every
# phase that writes or tests code on `opus`. GREEN and GATES were on `opus`
# before and stay there, so the asymmetry this harness rests on - never a
# weaker model where the temptation is to weaken a test - holds unchanged.
#
# NEEDLES. Each check compares the whole (phase, agent, model) projection,
# sorted, against the exact expected set: a missing row, an extra row, a row on
# the wrong agent and a row on the wrong model all read as "differs". Nothing
# floats.

SHIP="$(make_project_fixture)"
trap 'rm -rf "$FIX" "$SHIP"' EXIT
ship()     { ( cd "$SHIP" && bash scripts/plan.sh "$@" 2>&1 ); }
ship_set() { ship models "$1" | awk -F'\t' 'NF >= 4 { print $1, $2, $3 }' | LC_ALL=C sort; }
SHIP_EXPECTED="$(LC_ALL=C sort <<'ROWS'
PLANNED lead-po fable
RED test-developer opus
GREEN feature-developer opus
GATES feature-developer opus
REVIEW lead-po fable
SCAFFOLD lead-po opus
ROWS
)"
ship_story() { # <id> <type> <contract line, or empty>
  mkdir -p "$SHIP/docs/backlog/stories"
  printf -- '---\nid: %s\ntitle: Fixture story\nslug: fixture\ntype: %s\nstatus: todo\nphase: PLANNED\nbranch: story/%s-fixture\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Contract\n\n%s\n\n## Model guidance\n\n## Notes\n' \
    "$1" "$2" "$1" "$3" > "$SHIP/docs/backlog/stories/$1.md"
}

ship_story S-1 feature '`src/core/world.ts` exports `buildWorld(seed: number): World`.'
assert_eq "an ordinary story: fable plans and reviews, opus writes and tests the code" \
  "$SHIP_EXPECTED" "$(ship_set S-1)"

# No row moves with the story. Each of these fired an exception under the old
# ladder; under the split there is nothing for one to move to.
ship_story S-2 feature ''
assert_eq "with no contract, the plan is the same" "$SHIP_EXPECTED" "$(ship_set S-2)"
ship_story S-3 feature '**Writes:** `scripts/plan.sh`, `.claude/tests/plan.test.sh`'
assert_eq "with a contract the lock cannot police, the plan is the same" "$SHIP_EXPECTED" "$(ship_set S-3)"
ship_story S-4 bootstrap 'the stack, the runner, and the scaffold.'
assert_eq "for a bootstrap story, the plan is the same" "$SHIP_EXPECTED" "$(ship_set S-4)"

# The agents' own `model:` is what a dispatch gets when nobody passes the plan's
# model - /audit-mutations, a designer review, a lead-po interview. It follows
# the same split: the planning roles declare `fable`, the roles that write or
# judge tests declare `opus`. lead-po runs SCAFFOLD on `opus` by the plan above,
# which is why that row exists: the declaration is its home, not its every
# dispatch.
declared() { awk '/^---$/ { n++; next } n == 1 && /^model:/ { print $2; exit }' "$REPO_ROOT/.claude/agents/$1.md"; }
agents_got="$(for a in feature-developer lead-designer lead-po mutation-tester test-developer; do printf '%s %s\n' "$a" "$(declared "$a")"; done)"
assert_eq "each agent declares the model of its kind of work" \
"feature-developer opus
lead-designer fable
lead-po fable
mutation-tester opus
test-developer opus" "$agents_got"

# The orchestrating commands run in the user's session, not in an agent, so the
# agent's `model:` never reaches them. Their own frontmatter is the only place
# the harness can say "this multi-stage workflow is planned on fable".
cmd_model() { awk '/^---$/ { n++; next } n == 1 && /^model:/ { print $2; exit }' "$REPO_ROOT/.claude/commands/$1.md"; }
cmds_got="$(for c in advance-story complete-story create-product plan-product plan-story; do printf '%s %s\n' "$c" "$(cmd_model "$c")"; done)"
assert_eq "each orchestrating command runs on fable" \
"advance-story fable
complete-story fable
create-product fable
plan-product fable
plan-story fable" "$cmds_got"

# ---------------------------------------------------------------------------
# MECHANISM_POLICY. Every block below tests plan.sh's exception machinery, not
# the shipped policy, so it runs against this file rather than the real one -
# see the header. It is the pre-78 policy verbatim in shape: one base row per
# dispatching phase, RED on `fable`, and three RED exceptions back to `opus`.
cat > "$FIX/.claude/harness/models.conf" <<'POLICY'
# Mechanism fixture for plan.test.sh - not the shipped policy.
model  | PLANNED  | lead-po           | opus  | planning is the judgement phase
model  | RED      | test-developer    | fable | the measured case: with a partitioned contract the brief carries the judgement and the model writes sharper negative controls
model  | GREEN    | feature-developer | opus  | a weaker model here reaches green by weakening a test
model  | GATES    | feature-developer | opus  | same risk as GREEN
model  | REVIEW   | lead-po           | opus  | a wrong call here ships
model  | SCAFFOLD | lead-po           | opus  | source, tests and config in one derivation

except | RED | no-contract    | opus  | with no contract to hand RED, the thing that was measured is absent
except | RED | unenforced     | opus  | the lock freezes none of the paths this story names, so the contract is the only enforcement there is
except | RED | type=bootstrap | opus  | a bootstrap story derives the runner, the config and the scaffold together
POLICY

# ---------------------------------------------------------------------------
describe "the exception mechanism (against MECHANISM_POLICY)"

ordinary T-1
out="$(plan models T-1)"

# RED is the whole point of the policy, and it is the only row that moves.
assert_contains "RED runs on the weaker model when a brief exists" \
  "RED	test-developer	fable" "$out"

# These two never move, and the reason is the one this harness was built for.
assert_contains "GREEN stays on the stronger model" \
  "GREEN	feature-developer	opus" "$out"
assert_contains "GATES stays on the stronger model" \
  "GATES	feature-developer	opus" "$out"
assert_contains "and the orchestrator does too" \
  "PLANNED	lead-po	opus" "$out"

# Both checks below are loops over the plan's rows, and a loop over nothing
# finds no fault: with no plan at all they reported green while every other
# assertion in this file was red. So the row count is asserted first, and they
# mean something only because it is.
assert_eq "the plan has a row for every dispatching phase" 6 \
  "$(printf '%s\n' "$out" | grep -c '	')"

# A row without a reason is the folklore rules.md warns about, so every row
# carries one and the test refuses a blank.
missing=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  why="$(printf '%s' "$line" | cut -f4-)"
  case "$why" in ''|' ') missing="$missing $(printf '%s' "$line" | cut -f1)" ;; esac
done <<< "$out"
assert_eq "every phase in the plan says why" "" "$missing"

# THE EXCEPTION, and the reason it exists. The measurement was a partitioned
# RED BRIEF against the stronger model without one - so with no contract to
# hand RED, the thing that was measured is not present and the weaker model is
# not what was tested.
story_with T-2 feature PLANNED 2 <<'EOF'
EOF
out="$(plan models T-2)"
assert_contains "with no contract, RED goes back to the stronger model" \
  "RED	test-developer	opus" "$out"
assert_contains "and says it is the brief that is missing" "contract" "$out"

# THE STORY THE LOCK DOES NOT COVER, reported from the field and confirmed
# here: `.claude/tests/*.test.sh`, `scripts/*` and `.claude/hooks/*` all
# classify as `harness`, and `harness` is writable in EVERY phase. So for a
# story that maintains the harness itself, RED may write the mechanism and
# GREEN may rewrite the frozen tests, and nothing complains - the consuming
# project measured `gates.sh --fast` at 13/13 with identical counts across a
# GREEN that added a script, a config file and 25 assertions.
#
# That changes what the RED row is resting on. Elsewhere the contract is an AID
# to the model and the lock is the enforcement; here the contract IS the
# enforcement, the only one there is. A weaker model is a different proposition
# against a safety net than against nothing, so RED stays on the stronger model
# when every path the contract names is one the lock will not freeze.
story_with T-4 feature PLANNED 2 <<'EOF'
CONTRACT:`scripts/plan.sh` gains a `write` subcommand; `.claude/tests/plan.test.sh` pins it.
EOF
out="$(plan models T-4)"
assert_contains "a story the lock cannot police keeps RED on the stronger model" \
  "RED	test-developer	opus" "$out"
assert_contains "and says the lock is what is missing" "lock" "$out"

# THE CONTROL, and the reason this is not just "mentions a script". One source
# path is enough for the lock to bite, and without this assertion the rule
# above would push every story that touches a helper onto the stronger model.
story_with T-5 feature PLANNED 2 <<'EOF'
CONTRACT:`src/core/world.ts` exports `buildWorld`; `scripts/task.sh` gains a `seed` target.
EOF
out="$(plan models T-5)"
assert_contains "but one source path is enough for the lock to bite" \
  "RED	test-developer	fable" "$out"

# A CONTRACT TOO BIG TO READ IS STILL A CONTRACT. `has_content` here was lifted
# from check-boundaries.sh when this script was written, and the defect came with
# it: `strip_comments | grep -q` has an awk that buffers to END feeding a grep
# that exits at the first match, so the writer dies of SIGPIPE and `pipefail`
# turns 141 into "no content". Measured: 50,000 bytes exit 0, 200,000 exit 141.
#
# The consequence here is quieter than a refused PR and worse for it. A thorough
# contract - the kind the RED row exists to reward - reads as ABSENT, the
# no-contract exception fires, and the plan silently moves RED to the stronger
# model. Nothing fails; the story just runs on a model nobody chose, for a reason
# nobody can see.
#
# The body is STREAMED into the file rather than held in a shell variable and
# passed through `awk -v`: a megabyte on a command line stalls indefinitely here,
# which is a fact about this fixture rather than about the defect.
{
  printf -- '---\nid: T-6\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: PLANNED\nbranch: story/T-6-fixture\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Contract\n\n'
  yes '`src/core/world.ts` exports buildWorld(seed: number): World.' | head -c 1572864
  printf -- '\n\n## Deferred verifications\n\n## Model guidance\n\n## Gate results\n\n## Notes\n'
} > "$FIX/docs/backlog/stories/T-6.md"
out="$(plan models T-6)"
assert_contains "a 1.5 MiB contract still counts as a contract" \
  "RED	test-developer	fable" "$out"

# Bootstrap writes source, tests and config in one indivisible derivation under
# SCAFFOLD, with no failing test to anchor it.
story_with T-3 bootstrap PLANNED 2 <<'EOF'
CONTRACT:the stack, the runner, and the scaffold.
EOF
out="$(plan models T-3)"
assert_contains "a bootstrap story keeps RED on the stronger model" \
  "RED	test-developer	opus" "$out"

# Derived, not listed: every phase that dispatches an agent has a row. A phase
# added to phases.conf with no model row is a phase whose model is decided by
# whatever the session happens to be set to, which is the state this replaces.
unplanned=""
for ph in $(awk -F'|' '!/^#|^[[:space:]]*$/ { gsub(/ /,"",$1); print $1 }' "$FIX/.claude/harness/phases.conf"); do
  case "$ph" in IDLE|DONE) continue ;; esac
  # awk over a here-string, not `printf | grep -q`. `grep -q` leaves at its
  # first match, the printf behind it dies of SIGPIPE, and pipefail promotes 141
  # to the status this `||` reads - so a phase that HAS a row is recorded as
  # unplanned. -F'\t' with NF > 1 is exactly the old `^PHASE<tab>` anchor: $1 is
  # everything before the first tab, and NF > 1 is what says a tab was there.
  # WORLD-086 R-1.
  awk -F'\t' 'BEGIN { n = ARGV[1]; ARGV[1] = "" } $1 == n && NF > 1 { h = 1 } END { exit !h }' \
    "$ph" <<<"$out" || unplanned="$unplanned $ph"
done
assert_eq "every dispatching phase has a model" "" "$unplanned"

# A model nobody can dispatch is a typo that surfaces as a silent fallback.
bad=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  m="$(printf '%s' "$line" | cut -f3)"
  case "$m" in opus|fable|sonnet|haiku) ;; *) bad="$bad $m" ;; esac
done <<< "$out"
assert_eq "and names a model that can actually be dispatched" "" "$bad"

# ---------------------------------------------------------------------------
describe "which command to drive the story with"

# The ordinary case, and the one the request is about: nothing here needs a
# human between phases.
ordinary T-10
out="$(plan next T-10)"
assert_contains "an ordinary story runs end to end" "complete-story" "$out"
assert_contains "and says why" "T-10" "$out"

# Mid-flight is not a recommendation about the whole cycle; it is the next
# phase, and the answer is never complete-story.
ordinary T-11 feature GREEN
out="$(plan next T-11)"
assert_contains "a story already in flight advances one phase" "advance-story" "$out"
assert_contains "and names the phase it would move to" "GATES" "$out"

# Bootstrap is the one type that writes production code with no failing test
# in front of it. Look between the phases.
story_with T-12 bootstrap PLANNED 2 <<'EOF'
CONTRACT:the stack and the runner.
EOF
out="$(plan next T-12)"
assert_contains "a bootstrap story is driven one phase at a time" "advance-story" "$out"

# A deferred verification names a control and the phase that must run it, so
# something has to stop in that phase and look.
story_with T-13 feature PLANNED 2 <<'EOF'
CONTRACT:`src/core/world.ts` exports `buildWorld`.
DEFERRED:- AC-2's negative control cannot run until the renderer exists. Owner: GREEN
EOF
out="$(plan next T-13)"
assert_contains "so is one carrying a deferred verification" "advance-story" "$out"
assert_contains "and the reason names it" "Deferred" "$out"

# Size is the crudest signal and the last one consulted, which is why it is a
# threshold rather than a judgement.
story_with T-14 feature PLANNED 9 <<'EOF'
CONTRACT:`src/core/world.ts` exports `buildWorld`.
EOF
out="$(plan next T-14)"
assert_contains "and one with many criteria" "advance-story" "$out"

# A story whose dependency is not DONE cannot be driven by either command, and
# saying `complete-story` here sends somebody into a refusal from phase.sh.
ordinary T-20 feature DONE
story_with T-21 feature PLANNED 2 <<'EOF'
CONTRACT:`src/core/world.ts` exports `buildWorld`.
DEPENDS:T-22
EOF
story_with T-22 feature GREEN 2 <<'EOF'
CONTRACT:something else.
EOF
out="$(plan next T-21)"
assert_contains "a blocked story recommends neither" "blocked" "$out"
assert_contains "and names the dependency that blocks it" "T-22" "$out"

# The same story once its dependency lands.
story_with T-22 feature DONE 2 <<'EOF'
CONTRACT:something else.
EOF
out="$(plan next T-21)"
assert_contains "and stops being blocked when the dependency is DONE" "complete-story" "$out"

# DONE is not a recommendation to do anything.
ordinary T-30 feature DONE
out="$(plan next T-30)"
case "$out" in
  *advance-story*|*complete-story*) _bad "a DONE story recommends no command" "it recommended one: $out" ;;
  *) _ok "a DONE story recommends no command" ;;
esac

# ---------------------------------------------------------------------------
describe "the plan is written into the story, not left to be looked up"

# `## Gate results` is written by gates.sh and never by hand, for a reason that
# applies here too: a section a person retypes is a section that drifts from
# what the tool would say. The plan goes in at the END of PLANNED, because it
# depends on the contract - writing it at creation time would bake in the
# no-contract exception before anybody had a chance to write one.
ordinary T-40
plan write T-40 >/dev/null
body="$(awk '/^## Model guidance/{on=1;next} on&&/^## /{exit} on{print}' "$FIX/docs/backlog/stories/T-40.md")"
assert_contains "the section carries the plan" "RED" "$body"
assert_contains "with the model for each phase" "fable" "$body"
assert_contains "and the reason, not just the name" "negative controls" "$body"
# It is a PLAN. rules.md wants the resolved model recorded, and a section that
# looked like a record would quietly satisfy a rule it does not satisfy.
assert_contains "and says it is a plan, not a record" "resolved" "$body"

# Nothing else in the story moves.
assert_contains "the criteria are untouched" "**AC-1**" "$(cat "$FIX/docs/backlog/stories/T-40.md")"
assert_contains "and so is the contract" "buildWorld" "$(cat "$FIX/docs/backlog/stories/T-40.md")"

# Writing twice is writing once: the orchestrator re-runs this after amending
# the contract, and a section that grew a second copy each time would be worse
# than no section.
plan write T-40 >/dev/null
assert_eq "writing it again replaces rather than appends" 1 \
  "$(grep -c '^| RED ' "$FIX/docs/backlog/stories/T-40.md")"


# ---------------------------------------------------------------------------
describe "write says it wrote only when the file on disk says so (WORLD-097)"

# THE DEFECT. `cmd_write` splices the plan in with an awk that matches
# `^## Model guidance` and replaces the section - and then prints `wrote the
# model plan into ...` and exits 0 whether or not anything matched. A story
# that arrived without the heading (WORLD-072 was split out of WORLD-012 by
# hand) passes through byte-identical and the tool says it wrote the plan.
# plan.sh runs under `set -uo pipefail` with no `-e`, so the same line is
# reached when the render itself fails.
#
# EVERY ASSERTION HERE READS THE FILE. The natural check - `output contains
# "wrote the model plan"` - is satisfied by the defect, which is what hid it for
# two stories. The heading is counted with `grep -cx`, whole line, so a
# `## Model guidance` that is duplicated, missing or turned into
# `### Model guidance` all read as "not 1". The success line, where it is
# counted at all, is counted the same way: the exact line, `-cxF`, so a
# differently worded message is not a match and neither is its absence.

STORY_DIR="$FIX/docs/backlog/stories"
mg_count()   { grep -cx '## Model guidance' "$1" || true; }
mg_body()    { awk '/^## Model guidance$/ { on = 1; next } on && /^## / { exit } on { print }' "$1"; }
without_mg() { awk '/^## Model guidance$/ { skip = 1; next } skip && /^## / { skip = 0 } !skip { print }' "$1"; }
headings()   { grep '^## ' "$1"; }
# success_lines <id> <output>   How many lines of <output> ARE the success line.
success_lines() { grep -cxF "wrote the model plan into docs/backlog/stories/$1.md" <<<"$2" || true; }
zero_or_not() { case "$1" in 0) printf 'zero' ;; *) printf 'non-zero' ;; esac; }
present()    { if [ -e "$1" ]; then printf 'present'; else printf 'absent'; fi; }
identical()  { if cmp -s "$1" "$2"; then printf 'identical'; else printf 'differs'; fi; }

# write_fixture <id> <layout>   A story with a real contract, so RED plans to
# `fable`, in one of three layouts:
#   none    no `## Model guidance` heading anywhere - the WORLD-072 shape
#   middle  the heading between two other sections, with a stale body
#   last    the heading is the final section, stale body, nothing after it
write_fixture() {
  mkdir -p "$STORY_DIR"
  {
    printf -- '---\nid: %s\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: PLANNED\nbranch: story/%s-fixture\n---\n\n' "$1" "$1"
    printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Contract\n\n`src/core/world.ts` exports `buildWorld(seed: number): World`.\n\n'
    [ "$2" = middle ] && printf -- '## Model guidance\n\nstale plan from an earlier run\n\n'
    printf -- '## Out of scope\n\n- nothing.\n\n## Notes\n\nhand-written notes.\n'
    [ "$2" = last ] && printf -- '\n## Model guidance\n\nstale plan from an earlier run\n\n**Resolved:**\n\n- RED - written by hand, and replaced on purpose (see Out of scope)\n'
  } > "$STORY_DIR/$1.md"
}

# rendered_plan <id>   The body the splice produces when the heading sits
# mid-file - the one layout today's cmd_write already gets right (T-40 above,
# and the story's own reproduction). It is the oracle for every OTHER layout:
# whatever route the heading arrived by, the body it ends up with is this one,
# byte for byte. The exact-text needles further down pin the lines that must
# survive independently of this oracle, so a fix that rewords the block fails
# both ways.
rendered_plan() {
  write_fixture "$1" middle
  plan write "$1" >/dev/null
  mg_body "$STORY_DIR/$1.md"
}

# --- AC-1: a story with no heading gains the section ------------------------
reference="$(rendered_plan T-50)"
write_fixture T-50 none
cp "$STORY_DIR/T-50.md" "$FIX/T-50.before"
out="$(plan write T-50)"; rc=$?
assert_eq "AC-1: a story with no heading gains exactly one \`## Model guidance\`" \
  1 "$(mg_count "$STORY_DIR/T-50.md")"
assert_eq "AC-1: and the command exits 0" 0 "$rc"
body="$(mg_body "$STORY_DIR/T-50.md")"
assert_eq "AC-1: the section's body is the rendered plan, byte for byte" "$reference" "$body"
# The lines the contract says must survive, pinned against literal text rather
# than against the oracle above.
assert_contains "AC-1: it says which command planned it, from which file" \
  'Planned by `bash scripts/plan.sh write T-50` from `.claude/harness/models.conf`.' "$body"
assert_contains "AC-1: it carries the table header" '| Phase | Agent | Planned | Why |' "$body"
assert_contains "AC-1: and the RED row from models.conf" '| RED | `test-developer` | `fable` |' "$body"
assert_contains "AC-1: and the Resolved marker" '**Resolved:**' "$body"
assert_contains "AC-1: and the comment beneath it" \
  'One line per dispatch, as it happened: phase, agent, the model that' "$body"
# CONTROL: only `## Model guidance` was added. Every other heading is still
# there, once, in the same order, and nothing outside the new section moved.
assert_eq "AC-1 control: every other heading is where it was, once" \
  "$(headings "$FIX/T-50.before")" \
  "$(headings "$STORY_DIR/T-50.md" | grep -vx '## Model guidance')"
assert_eq "AC-1 control: and the file minus the new section is the file it was" \
  "$(cat "$FIX/T-50.before")" "$(without_mg "$STORY_DIR/T-50.md")"

# --- AC-2: the success line is a claim about the file -----------------------
# (a) The same heading-less run. Three numbers, read together: the exit status,
# how many lines of output ARE the success line, and how many `## Model
# guidance` headings the file holds afterwards. Today this reads `0/1/0`: exit
# 0, success printed, no section - the lie in one string. Neither `0/0/0` (an
# honest refusal) nor `0/1/1` (an honest success) is the defect, and only the
# second is what AC-1 asks for.
assert_eq "AC-2 (a): exit / success lines / headings agree on a story that had no heading" \
  "0/1/1" "$rc/$(success_lines T-50 "$out")/$(mg_count "$STORY_DIR/T-50.md")"

# The same reading on a story whose heading was already there. Green today, and
# earned in ## Regressions: an awk that prints the heading a second time after
# the plan makes this string read `0/1/2`, and one that never matches the
# heading leaves it `0/1/1` - which is why the body is compared as well below.
write_fixture T-51 middle
out="$(plan write T-51)"; rc=$?
assert_eq "AC-2: exit / success lines / headings agree on a story that had one" \
  "0/1/1" "$rc/$(success_lines T-51 "$out")/$(mg_count "$STORY_DIR/T-51.md")"

# (b) A render that cannot happen. The plan is rendered to
# `$ROOT/.claude/state/plan-write.$$.md` (contract); with a regular FILE sitting
# at `.claude/state`, `mkdir -p` fails and the redirect fails ("Not a
# directory"), so there is no plan for the splice to read. Today the awk still
# matches the heading, `getline` from the unreadable temp file returns nothing,
# and the section is DELETED from the story - then `mv` runs, the success line
# is printed and the exit is 0. Portable: no chmod, which a directory on Windows
# ignores.
#
# The state directory is put back BEFORE the assertions, so an assertion
# failing here cannot leave the fixture broken for the cases below.
write_fixture T-52 middle
cp "$STORY_DIR/T-52.md" "$FIX/T-52.before"
rm -rf "$FIX/.claude/state"; : > "$FIX/.claude/state"
out="$(plan write T-52)"; rc=$?
leftovers="$(find "$FIX/.claude" -name 'plan-write.*.md' 2>/dev/null)"
rm -f "$FIX/.claude/state"; mkdir -p "$FIX/.claude/state"
assert_eq "AC-2 (b): a run whose plan cannot be rendered exits non-zero" \
  non-zero "$(zero_or_not "$rc")"
assert_eq "AC-2 (b): and prints no success line" 0 "$(success_lines T-52 "$out")"
assert_eq "AC-2 (b): and leaves no T-52.md.new behind" absent "$(present "$STORY_DIR/T-52.md.new")"
assert_eq "AC-2 (b): and leaves the story file byte-identical to what it was" \
  identical "$(identical "$FIX/T-52.before" "$STORY_DIR/T-52.md")"
# Vacuous under THIS mechanism - the temp file could never be created - and
# said so in the handoff. It is here so that a mechanism that can create it
# (GREEN's own probe of the failure path) has an assertion already waiting.
assert_eq "AC-2 (b): and no plan-write temp file is left under .claude" "" "$leftovers"

# --- AC-3: an existing section is replaced, and replacing is idempotent -----
# T-51 was written once above. The stale body is gone, the plan is in its place.
assert_eq "AC-3: an existing section is replaced, leaving exactly one heading" \
  1 "$(mg_count "$STORY_DIR/T-51.md")"
assert_eq "AC-3: and the stale body is gone, not appended to" \
  0 "$(grep -c 'stale plan from an earlier run' "$STORY_DIR/T-51.md" || true)"
cp "$STORY_DIR/T-51.md" "$FIX/T-51.once"
plan write T-51 >/dev/null
assert_eq "AC-3: writing twice leaves the file identical to writing once" \
  identical "$(identical "$FIX/T-51.once" "$STORY_DIR/T-51.md")"
# The section AC-1 appended is an existing section from then on: the second run
# replaces it in place rather than appending a second copy.
cp "$STORY_DIR/T-50.md" "$FIX/T-50.once"
plan write T-50 >/dev/null
assert_eq "AC-3: the section a heading-less story gained is replaced on the next run, not appended again" \
  "1/identical" "$(mg_count "$STORY_DIR/T-50.md")/$(identical "$FIX/T-50.once" "$STORY_DIR/T-50.md")"

# CONTROL: the heading is the LAST section, with nothing after it. The awk's
# skip runs to end of file; the file must still end with exactly one heading,
# with the whole plan beneath it - down to its last line - and everything before
# the heading untouched. (The stale body's hand-written Resolved line is
# discarded: that is the replacing behaviour AC-3 pins, and preserving it is
# out of scope.)
reference="$(rendered_plan T-53)"
write_fixture T-53 last
cp "$STORY_DIR/T-53.md" "$FIX/T-53.before"
out="$(plan write T-53)"; rc=$?
assert_eq "AC-3 control: a heading that is the last section still ends up as exactly one" \
  1 "$(mg_count "$STORY_DIR/T-53.md")"
assert_eq "AC-3 control: with the rendered plan as its body" "$reference" "$(mg_body "$STORY_DIR/T-53.md")"
assert_eq "AC-3 control: and the file ends with the plan's last line, not short of it" \
  '     another — what that changed. A choice with no verdict is folklore. -->' \
  "$(tail -n 1 "$STORY_DIR/T-53.md")"
assert_eq "AC-3 control: and everything before the heading is untouched" \
  "$(without_mg "$FIX/T-53.before")" "$(without_mg "$STORY_DIR/T-53.md")"
assert_eq "AC-3 control: and it exits 0" 0 "$rc"

# --- AC-4: a missing story is refused, and names the path -------------------
# The story calls this `story_file`'s existing die, and it is not: the die runs
# inside `file="$(story_file "$id")"`, so it exits the SUBSHELL and cmd_write
# carries on with an empty `$file` - two `plan: no story at ...` lines on
# stderr, an awk with no input file, a `.new` dropped in the project root, and
# then the success line and exit 0. Measured on this tree before these cases
# were written. So this is red today for the same reason the others are, and
# the fix must not lean on a die it cannot see.
#
# The path must appear in an ERROR line (die's `plan: ` prefix), because the
# success line names the same path and would satisfy a bare "contains the
# path". Exactly one such line: today there are two. stdin is /dev/null because
# today's fall-through awk reads it when `$file` is empty, and a run from a
# terminal would sit there waiting.
out="$(plan write T-99 </dev/null)"; rc=$?
assert_eq "AC-4: a story id with no file exits non-zero" non-zero "$(zero_or_not "$rc")"
assert_eq "AC-4: and names the path it looked for, in one error line" \
  1 "$(grep -c '^plan: .*docs/backlog/stories/T-99\.md$' <<<"$out" || true)"
assert_eq "AC-4: and prints no success line" 0 "$(success_lines T-99 "$out")"
assert_eq "AC-4: and creates neither the story nor any .new anywhere in the project" \
  "absent/" "$(present "$STORY_DIR/T-99.md")/$(find "$FIX" -name '*.new' -not -path '*/.git/*' 2>/dev/null)"

# ---------------------------------------------------------------------------
describe "conflicts: which startable stories would fight over the same file"

# WHAT THIS IS FOR. Running two stories at once needs two things to be true:
# neither is blocked, and they do not write the same files. `depends_on` already
# answers the first - `plan.sh next` returns `blocked` and the board shows it.
# Nothing answered the second, so two ready stories could both be started and
# the collision found at merge.
#
# The declared paths already exist: `## Contract` names the modules a story
# touches, and contract_unenforced has been reading them since release 23 to
# decide the RED model. This intersects them instead of re-deriving them.

rm -rf "$FIX/docs/backlog/stories"; mkdir -p "$FIX/docs/backlog/stories"
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:`src/core/world.ts` exports buildWorld(seed: number): World.
EOF
story_with B feature PLANNED 1 <<'EOF'
CONTRACT:`src/ui/panel.tsx` exports Panel().
EOF
out="$(plan conflicts)"
assert_contains "two stories touching different files are reported clear" \
  "A + B" "$out"
case "$out" in
  *CONFLICT*) _bad "and not as a conflict" "reported a conflict: $out" ;;
  *) _ok "and not as a conflict" ;;
esac

# The case it exists for.
rm -rf "$FIX/docs/backlog/stories"; mkdir -p "$FIX/docs/backlog/stories"
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:`src/core/world.ts` exports buildWorld(seed: number): World.
EOF
story_with B feature RED 1 <<'EOF'
CONTRACT:`src/core/world.ts` gains clampLatitude(deg: number): number.
EOF
out="$(plan conflicts)"
assert_contains "two stories declaring the same path are named as a conflict" \
  "CONFLICT" "$out"
assert_contains "and the shared path is named, so it can be checked" \
  "src/core/world.ts" "$out"
assert_eq "and it exits non-zero when there is one" "1" "$( ( cd "$FIX" && bash scripts/plan.sh conflicts >/dev/null 2>&1 ); printf '%s' "$?" )"

# A STORY THAT DECLARES NOTHING CANNOT BE JUDGED, and must not read as clear.
# This is the real-tree case: all five stories in this repository's own backlog
# are PLANNED with an empty Contract, because the contract is written before
# RED. A guard that called that "no conflicts" would be answering a question it
# had no information about - the same failure as refresh-harness.sh reporting
# LOCAL from a source with no history.
rm -rf "$FIX/docs/backlog/stories"; mkdir -p "$FIX/docs/backlog/stories"
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:`src/core/world.ts` exports buildWorld(seed: number): World.
EOF
story_with B feature PLANNED 1 </dev/null
out="$(plan conflicts)"
assert_contains "a story declaring no paths is reported as unjudgeable" \
  "UNKNOWN" "$out"
# ANCHORED ON THE ROW'S STATUS COLUMN, not on the absence of the word "clear"
# anywhere in the output. Written the floating way first, it matched the footer
# sentence "UNKNOWN is not clear:" - the line that exists to say the opposite -
# and reported the code broken. rules.md: prefer a needle whose negation is not
# also a match.
assert_eq "and never as clear" "UNKNOWN" \
  "$(awk '$2 == "A" && $3 == "+" && $4 == "B" { print $1; exit }' <<<"$out")"

# Blocked and DONE stories are not candidates: one cannot start, the other is
# finished. Without this the report is noise proportional to backlog size.
rm -rf "$FIX/docs/backlog/stories"; mkdir -p "$FIX/docs/backlog/stories"
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:`src/core/world.ts` exports buildWorld(seed: number): World.
EOF
story_with B feature PLANNED 1 <<'EOF'
DEPENDS:A
CONTRACT:`src/core/world.ts` also changes buildWorld.
EOF
out="$(plan conflicts)"
case "$out" in
  *CONFLICT*) _bad "a blocked story is not a conflict candidate" "reported anyway: $out" ;;
  *) _ok "a blocked story is not a conflict candidate" ;;
esac

# ---------------------------------------------------------------------------
describe "conflicts: a story declares the files it touches in frontmatter (HARNESS-006)"

# WHY THE DECLARATION MOVES. The block above reads `## Contract`, and a Contract
# is written at the end of PLANNED - after the backlog has been cut. So at the
# moment the planner decides which stories can run together, every pair is
# UNKNOWN: ten of ten on this repository's own backlog at release 45. The check
# was honest and useless. `touches:` is the same fact stated when the story is
# AUTHORED, read by frontmatter_list - the reader depends_on already uses - and
# cmd_conflicts takes a story's paths from it first, falling back to the
# Contract only when it is absent or empty.
#
# EVERY ROW ASSERTION BELOW READS THE STATUS COLUMN of the named pair, never a
# floating substring: `clear` also appears in the footer sentence that exists
# to say UNKNOWN is NOT clear, and `DRIFT` could one day appear in prose.

# row_status <a> <b>   The first column of the pair's row, or nothing.
row_status() { awk -v a="$1" -v b="$2" '$2 == a && $3 == "+" && $4 == b { print $1; exit }' <<<"$out"; }
# drift_for <id>   Every DRIFT line for the story - first column exactly DRIFT,
# second the id - so a test can say "names this path" and "names no other".
drift_for()  { awk -v id="$1" '$1 == "DRIFT" && $2 == id { print }' <<<"$out"; }
# conflicts_rc   The exit status of the command, which is a claim of its own.
conflicts_rc() { ( cd "$FIX" && bash scripts/plan.sh conflicts >/dev/null 2>&1 ); printf '%s' "$?"; }
fresh() { rm -rf "$FIX/docs/backlog/stories"; mkdir -p "$FIX/docs/backlog/stories"; }

# --- AC-1: touches: is what the story is judged on --------------------------
#
# A's Contract names the very file B touches; A's `touches:` does not. Judged
# on `touches:`, the pair is clear. Judged on the Contract - today's code - or
# on the UNION of the two, it is a CONFLICT on src/ui/panel.tsx. The row can
# only read `clear` if the frontmatter took precedence.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
CONTRACT:`src/ui/panel.tsx` gains a slot.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/ui/panel.tsx
EOF
out="$(plan conflicts)"
assert_eq "a story with touches: is judged on those paths, not on its Contract" \
  "clear" "$(row_status A B)"

# The reverse: the same two stories with the Contract left alone and A's
# `touches:` moved onto B's file. Only the frontmatter changed, and the verdict
# flips. Without this the assertion above is also satisfied by "ignore both".
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/ui/panel.tsx
CONTRACT:`src/core/world.ts` gains a slot.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/ui/panel.tsx
EOF
out="$(plan conflicts)"
assert_eq "and changing only touches: changes the verdict" \
  "CONFLICT" "$(row_status A B)"

# THE CONTROL, PO decision 1. `touches: []` is what new-story.sh writes into
# every fresh story, so its meaning decides what a whole new backlog reports.
# It declares NOTHING: the story falls through to its Contract exactly as if
# the key were absent. Two fixtures, because two wrong readings exist and each
# passes one of them:
#   * "empty means touches no file" -> clear against everything. Refused by the
#     first case, where A's Contract collides with B and the row must say so.
#   * "empty means stop, declare nothing, do not consult the Contract" ->
#     UNKNOWN in the first case. Also refused by it.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:
CONTRACT:`src/core/world.ts` gains a slot.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_eq "touches: [] falls through to the Contract, like an absent key" \
  "CONFLICT" "$(row_status A B)"

# And with no Contract to fall through to, it is UNKNOWN - never clear. This
# is the second reading's other half: `[]` as "touches no file" would make
# every story new-story.sh creates read clear against everything.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_eq "touches: [] with no Contract is UNKNOWN, not clear" \
  "UNKNOWN" "$(row_status A B)"

# --- AC-2: intersecting sets are CONFLICT, disjoint sets are clear -----------
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts, src/ui/panel.tsx
EOF
story_with B feature RED 1 <<'EOF'
TOUCHES:docs/wiki/design.md, src/ui/panel.tsx
EOF
out="$(plan conflicts)"
assert_eq "two stories whose touches: intersect are a CONFLICT" \
  "CONFLICT" "$(row_status A B)"
assert_contains "and the shared path is named on the row" "src/ui/panel.tsx" \
  "$(awk '$2 == "A" && $3 == "+" && $4 == "B" { print; exit }' <<<"$out")"
# Not the unshared ones: a row naming every path either side declares would
# also contain the needle above, and would send the reader to the wrong file.
assert_not_contains "and only the shared path" "src/core/world.ts" \
  "$(awk '$2 == "A" && $3 == "+" && $4 == "B" { print; exit }' <<<"$out")"
assert_eq "and the command exits non-zero" "1" "$(conflicts_rc)"

# The control: same shape, no overlap.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts, src/core/climate.ts
EOF
story_with B feature RED 1 <<'EOF'
TOUCHES:src/ui/panel.tsx, docs/wiki/design.md
EOF
out="$(plan conflicts)"
assert_eq "two stories whose touches: are disjoint are clear" \
  "clear" "$(row_status A B)"
assert_eq "and the command exits 0" "0" "$(conflicts_rc)"

# --- AC-3: touches: plus an EMPTY Contract is judged, not UNKNOWN ------------
#
# The whole point. Both stories here are what a freshly planned backlog looks
# like - a filled `touches:`, a Contract nobody has written - and the pair is
# judged. Today's code reports UNKNOWN for it.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:scripts/new-story.sh
EOF
out="$(plan conflicts)"
assert_eq "touches: with an empty Contract is judged, not UNKNOWN" \
  "clear" "$(row_status A B)"
assert_contains "and the summary counts no unjudged pair" \
  "0 pair(s) that could not be judged" "$out"
# No Contract means nothing to drift from: drift is judged only when BOTH
# sources are present.
assert_eq "and an empty Contract raises no drift warning" "" "$(drift_for A)$(drift_for B)"

# THE CONTROL. A story with neither `touches:` nor Contract paths still cannot
# be judged, and UNKNOWN is still never spelled `clear`. Absent key, not `[]`:
# the `[]` twin of this case is under AC-1.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
story_with B feature PLANNED 1 </dev/null
out="$(plan conflicts)"
assert_eq "a story with neither touches: nor Contract paths is still UNKNOWN" \
  "UNKNOWN" "$(row_status A B)"
# The row's detail used to say "no Contract paths declared yet", which after
# this story is only half the diagnosis and would send a planner to write a
# Contract when one line of frontmatter is the cheaper fix.
assert_contains "and the row says which declaration is missing" "touches" \
  "$(awk '$2 == "A" && $3 == "+" && $4 == "B" { print; exit }' <<<"$out")"
assert_eq "and a Contract-less story with touches: on the other side raises no drift" \
  "" "$(drift_for A)$(drift_for B)"

# --- AC-4: a Contract path absent from touches: is a drift warning -----------
#
# The Contract is the sharper document, written later by someone who has read
# the code. When it names a file the declaration did not, one of the two is
# wrong, and neither should silently overrule the other: the pair is still
# judged on `touches:` (AC-1), and the disagreement is printed.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:**Writes:** `scripts/plan.sh`, `scripts/new-story.sh`
CONTRACT:`scripts/plan.sh` gains story_touches; `scripts/new-story.sh` emits the key.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_eq "a Contract path absent from touches: is one DRIFT line for that story" \
  "1" "$(drift_for A | grep -c .)"
assert_contains "naming the path" "scripts/new-story.sh" "$(drift_for A)"
assert_not_contains "and not the path both documents agree on" "scripts/plan.sh" "$(drift_for A)"
assert_eq "a story whose Contract is empty has nothing to drift from" "" "$(drift_for B)"
# The exact line the Contract specifies, anchored: first column DRIFT, second
# the id, then the path in the wording the reader will grep for.
assert_eq "in the documented wording" "1" \
  "$(grep -c '^DRIFT[[:space:]]\{1,\}A[[:space:]]\{1,\}contract names scripts/new-story.sh, touches: does not$' <<<"$out")"
# It is a WARNING. The exit status is about conflicts, and there is none here.
assert_eq "and drift alone does not change the exit status" "0" "$(conflicts_rc)"
assert_eq "and the pair is still judged on touches:" "clear" "$(row_status A B)"
assert_eq "and the summary line counts it" "1" \
  "$(grep -cx '0 conflict(s), 0 pair(s) that could not be judged, 1 drift warning(s).' <<<"$out")"

# A GLOB IN touches: COVERS THE FILES IT MATCHES. A story declaring a directory
# glob and a Contract naming one file under it has not drifted; the two
# documents agree at different granularities.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/ui/*.tsx
CONTRACT:**Writes:** `src/ui/panel.tsx`
CONTRACT:`src/ui/panel.tsx` exports Panel().
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_eq "a Contract path matched by a touches: glob is not drift" "" "$(drift_for A)"

# The control for the glob rule: a glob that does NOT match the Contract's path
# still drifts. Without this, "globs never drift" satisfies the case above.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/core/*.ts
CONTRACT:**Writes:** `src/ui/panel.tsx`
CONTRACT:`src/ui/panel.tsx` exports Panel().
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_contains "but a glob that does not match the path is drift" \
  "src/ui/panel.tsx" "$(drift_for A)"

# DRIFT IS PER STORY, NOT PER PAIR. A backlog with one startable story has no
# pair to judge and still has a declaration that can disagree with its
# Contract - this story's own situation at PLANNED, where it was the only
# startable story in its backlog.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:**Writes:** `scripts/plan.sh`, `scripts/new-story.sh`
CONTRACT:`scripts/plan.sh` gains story_touches; `scripts/new-story.sh` emits the key.
EOF
out="$(plan conflicts)"
assert_contains "drift is reported even with fewer than two startable stories" \
  "scripts/new-story.sh" "$(drift_for A)"
assert_eq "and still exits 0" "0" "$(conflicts_rc)"

# Drift beside a real conflict: the warning is counted and the conflict still
# decides the exit status. Both numbers on one summary line, so a count that
# overwrote the other would show.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:**Writes:** `scripts/plan.sh`, `scripts/new-story.sh`
CONTRACT:`scripts/plan.sh` gains story_touches; `scripts/new-story.sh` emits the key.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
EOF
out="$(plan conflicts)"
assert_eq "drift and a conflict are counted separately" "1" \
  "$(grep -cx '1 conflict(s), 0 pair(s) that could not be judged, 1 drift warning(s).' <<<"$out")"
assert_eq "and the conflict still decides the exit status" "1" "$(conflicts_rc)"

# DRIFT NEEDS BOTH DOCUMENTS. A story with a Contract and no `touches:` has
# nothing for the Contract to drift FROM; printing its whole path list as
# drift would be noise on every story that predates the field. The other
# conjunct - a Contract-less story does not drift - is pinned under AC-3.
fresh
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:**Writes:** `scripts/plan.sh`, `scripts/new-story.sh`
CONTRACT:`scripts/plan.sh` gains story_touches; `scripts/new-story.sh` emits the key.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_eq "a story with a Contract and no touches: key is not drift" "" "$(drift_for A)"

# A blocked story is not startable, so it is not drift-checked either: the
# report is about what could run now. Same rule the pair table applies.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
story_with B feature PLANNED 1 <<'EOF'
DEPENDS:A
TOUCHES:src/ui/panel.tsx
CONTRACT:**Writes:** `src/ui/other.tsx`
CONTRACT:`src/ui/other.tsx` also changes.
EOF
out="$(plan conflicts)"
assert_eq "a blocked story is not drift-checked" "" "$(drift_for B)"

# THE MODEL POLICY DOES NOT MOVE. cmd_models reads the Contract alone to decide
# the RED row - a story with a lock-policed `touches:` and an empty Contract is
# still a story with no brief, and RED stays on the stronger model.
fresh
story_with A feature PLANNED 2 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan models A)"
assert_contains "touches: does not stand in for the Contract in the model plan" \
  "RED	test-developer	opus" "$out"

# ---------------------------------------------------------------------------
describe "drift reads what a Contract writes (HARNESS-016)"

# WHY. HARNESS-006's DRIFT line compared `touches:` with every path-shaped token
# in the Contract's prose, and on this repository's own backlog it fired 15
# times and was wrong 15 times: files a story only READS (a helper it calls, a
# script it cites), bare basenames of files `touches:` lists in full, directory
# prefixes, and tokens that are not paths at all (`AC-1..AC`). A warning that is
# always false teaches its reader to skip it.
#
# PO decision 1: the Contract says what it writes on a column-0 `**Writes:**`
# line, the backticked tokens on it, unioned across lines. DRIFT compares THAT
# with `touches:` and is silent when there is no such line. The prose extractor
# survives only as the fallback for `conflicts` and the model plan, minus four
# drop rules for tokens that are not paths.
#
# NEEDLES. Every DRIFT assertion here is a whole-line compare against the exact
# text cmd_conflicts prints (`printf '%-9s %-13s %s'`), or an exact count of
# such lines - never a floating `DRIFT`, which the summary's `drift warning(s)`
# also satisfies.

# drift_line <id> <path>   The one DRIFT line the Contract specifies, exactly.
drift_line() { printf '%-9s %-13s %s' DRIFT "$1" "contract names $2, touches: does not"; }
# red_model <id>   The model column of the RED row of `plan.sh models`, and
# nothing else: `fable` and `opus` are compared whole, not found in a line.
# No `exit` in the awk: it reads to the end, so the writer never meets a closed
# pipe (WORLD-086's house rule).
red_model() { plan models "$1" | awk -F'\t' '$1 == "RED" { print $3 }'; }
# pair_row <a> <b>   The pair's whole row, for field-level checks of the detail.
pair_row() { awk -v a="$1" -v b="$2" '$2 == a && $3 == "+" && $4 == b { print; exit }' <<<"$out"; }

# --- AC-1: read-only mentions are not drift ----------------------------------
#
# A writes two files and `touches:` lists both. Its prose also names a helper it
# calls, a script it cites, a rule it follows, and the bare basename of a file
# `touches:` lists in full. Today every one of those is a DRIFT line.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh, .claude/tests/plan.test.sh
CONTRACT:**Writes:** `scripts/plan.sh`, `.claude/tests/plan.test.sh`
CONTRACT:`plan.sh` calls `frontmatter_list` the way `scripts/phase.sh` does;
CONTRACT:no change to `scripts/check-boundaries.sh`. See `.claude/harness/rules.md`.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_eq "files a Contract only reads or cites are not drift when touches: covers every file it writes" \
  "" "$(drift_for A)"
assert_eq "and the summary counts no drift warning" "1" \
  "$(grep -cx '0 conflict(s), 0 pair(s) that could not be judged, 0 drift warning(s).' <<<"$out")"

# THE CONTROL. The same story with one written file dropped from `touches:`:
# exactly one DRIFT line, and it is that file - not the read-only mentions,
# which would make the count larger, and not the file both documents agree on.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:**Writes:** `scripts/plan.sh`, `.claude/tests/plan.test.sh`
CONTRACT:`plan.sh` calls `frontmatter_list` the way `scripts/phase.sh` does;
CONTRACT:no change to `scripts/check-boundaries.sh`. See `.claude/harness/rules.md`.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_eq "a written file missing from touches: is exactly one DRIFT line, naming that file" \
  "$(drift_line A .claude/tests/plan.test.sh)" "$(drift_for A)"
assert_eq "and the summary counts exactly one" "1" \
  "$(grep -cx '0 conflict(s), 0 pair(s) that could not be judged, 1 drift warning(s).' <<<"$out")"

# NO **Writes:** LINE, NO DRIFT. A story that has not said what it writes has
# nothing for `touches:` to disagree with - its prose is not read for drift at
# all, however path-like. This is the rule that silences the real backlog.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:`scripts/plan.sh` gains story_touches; `scripts/new-story.sh` emits the key.
EOF
out="$(plan conflicts)"
assert_eq "a Contract with no **Writes:** line produces no DRIFT line, whatever its prose names" \
  "" "$(drift_for A)"

# MORE THAN ONE **Writes:** LINE, AND THEY UNION. Two lines, `touches:` covers
# only the first: the second line's path is the one drift.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:**Writes:** `scripts/plan.sh`
CONTRACT:Then the template.
CONTRACT:**Writes:** `scripts/new-story.sh`
EOF
out="$(plan conflicts)"
assert_eq "every **Writes:** line is read, and they union" \
  "$(drift_line A scripts/new-story.sh)" "$(drift_for A)"

# A **Writes:** INSIDE AN HTML COMMENT IS NOT READ. The template's own example
# lives in one; read without strip_comments, every fresh story would declare it.
# Column 0 on purpose: a reader that grepped lines without stripping comments
# first would see this one.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:**Writes:** `scripts/plan.sh`
CONTRACT:<!-- for example:
CONTRACT:**Writes:** `scripts/ghost.sh`
CONTRACT:-->
EOF
out="$(plan conflicts)"
assert_eq "a **Writes:** line inside an HTML comment declares nothing" "" "$(drift_for A)"

# NO BASENAME MATCHING. A **Writes:** entry is a repository-relative path, so a
# bare basename there is itself the disagreement, even when `touches:` lists a
# path ending in it.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:**Writes:** `plan.sh`
EOF
out="$(plan conflicts)"
assert_eq "a bare basename on a **Writes:** line is drift, not covered by the full path" \
  "$(drift_line A plan.sh)" "$(drift_for A)"

# --- AC-2: tokens that are not paths -----------------------------------------
#
# Each of the Contract's four drop rules has a token here: `..` (rule 1), a
# trailing `/` (rule 2), a trailing dot-and-digits version (rule 3), and a
# one-character stem with no `/` (rule 4: `e.g`, `i.bak`, `0.139s`).
#
# Drift side: the junk sits in prose beside a **Writes:** line whose second
# path `touches:` omits. The whole DRIFT output must be that one line.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:scripts/plan.sh
CONTRACT:**Writes:** `scripts/plan.sh`, `scripts/new-story.sh`
CONTRACT:Covers AC-1..AC-4, e.g. the 1.2 and 4.9 readers under `.claude/skills/stack-profiles/reference/`;
CONTRACT:keeps i.bak and measured 0.139s.
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/core/world.ts
EOF
out="$(plan conflicts)"
assert_eq "non-path tokens and directory prefixes never reach a DRIFT line; the omitted written path does" \
  "$(drift_line A scripts/new-story.sh)" "$(drift_for A)"

# CONFLICT side, on the prose fallback: two stories with no `touches:` and no
# **Writes:** line, whose Contracts share ONLY junk. Today every shared junk
# token is a "shared path" and the pair is a CONFLICT.
fresh
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:`src/core/world.ts` covers AC-1..AC, e.g. the 1.2 reader under `.claude/skills/stack-profiles/reference/`.
CONTRACT:Keeps i.bak; measured 0.139s.
EOF
story_with B feature PLANNED 1 <<'EOF'
CONTRACT:`src/ui/panel.tsx` covers AC-1..AC, e.g. the 1.2 reader under `.claude/skills/stack-profiles/reference/`.
CONTRACT:Keeps i.bak; measured 0.139s.
EOF
out="$(plan conflicts)"
assert_eq "two Contracts sharing only non-path tokens are clear, not a CONFLICT" \
  "clear" "$(row_status A B)"
assert_eq "and the command exits 0" "0" "$(conflicts_rc)"

# THE CONTROL: the same two Contracts sharing one real path as well. CONFLICT,
# and the detail is that path ALONE - five fields, the fifth the path - so no
# junk token rode along as a second "shared path".
fresh
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:`src/core/world.ts` covers AC-1..AC, e.g. the 1.2 reader under `.claude/skills/stack-profiles/reference/`.
CONTRACT:Keeps i.bak; measured 0.139s.
EOF
story_with B feature PLANNED 1 <<'EOF'
CONTRACT:`src/ui/panel.tsx` and `src/core/world.ts` cover AC-1..AC, e.g. the 1.2 reader under `.claude/skills/stack-profiles/reference/`.
CONTRACT:Keeps i.bak; measured 0.139s.
EOF
out="$(plan conflicts)"
assert_eq "a real shared path beside the junk is still a CONFLICT naming only that path" \
  "CONFLICT 5 src/core/world.ts" "$(pair_row A B | awk '{ print $1, NF, $5 }')"

# THE OTHER DIRECTION: the drop rules must not eat real basenames. The fallback
# exists for stories that declare nothing better, and dropping `plan.sh` here
# would turn a real CONFLICT into clear with nothing to say so.
fresh
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:`plan.sh` gains a subcommand.
EOF
story_with B feature PLANNED 1 <<'EOF'
CONTRACT:`plan.sh` gains a different subcommand.
EOF
out="$(plan conflicts)"
assert_eq "a bare basename is still a path on the prose fallback" \
  "CONFLICT 5 plan.sh" "$(pair_row A B | awk '{ print $1, NF, $5 }')"

# --- AC-4: no touches:, and the pair is judged on the Contract ---------------
#
# With a **Writes:** line the fallback judges THAT line, not the prose: A only
# READS B's file. Today the prose is read and the pair is a CONFLICT on it.
fresh
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:**Writes:** `src/core/world.ts`
CONTRACT:Reads the layout from `src/ui/panel.tsx`; does not change it.
EOF
story_with B feature PLANNED 1 <<'EOF'
CONTRACT:**Writes:** `src/ui/panel.tsx`
EOF
out="$(plan conflicts)"
assert_eq "with no touches:, a pair is judged on the **Writes:** lines, not on files merely read" \
  "clear" "$(row_status A B)"

# THE CONTROL: B writes A's file. Judged, not UNKNOWN, and a CONFLICT on that
# path alone.
fresh
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:**Writes:** `src/core/world.ts`
CONTRACT:Reads the layout from `src/ui/panel.tsx`; does not change it.
EOF
story_with B feature PLANNED 1 <<'EOF'
CONTRACT:**Writes:** `src/core/world.ts`
EOF
out="$(plan conflicts)"
assert_eq "and two **Writes:** lines naming the same file are a CONFLICT on it" \
  "CONFLICT 5 src/core/world.ts" "$(pair_row A B | awk '{ print $1, NF, $5 }')"

# Without a **Writes:** line the fallback is still the prose, so HARNESS-006's
# pre-touches behaviour holds. (The describe blocks above pin the same thing;
# this one pairs a declared side with an undeclared one.)
fresh
story_with A feature PLANNED 1 <<'EOF'
CONTRACT:**Writes:** `src/core/world.ts`
EOF
story_with B feature PLANNED 1 <<'EOF'
CONTRACT:`src/core/world.ts` gains clampLatitude(deg: number): number.
EOF
out="$(plan conflicts)"
assert_eq "a **Writes:** side and a prose-only side are still judged against each other" \
  "CONFLICT 5 src/core/world.ts" "$(pair_row A B | awk '{ print $1, NF, $5 }')"

# --- AC-3: the RED row follows contract_paths, and moves only where decided --
#
# contract_unenforced reads contract_paths, so it follows the new output. The
# Contract's measurement: zero RED rows move among HARNESS-001..015 (DV-3
# checks the real backlog). These pin the mechanism.
#
# (a) No **Writes:** line: harness paths in full plus a bare `plan.sh`, which
# classifies `source`. Enforced, `fable`, exactly as today - rule 4 does not
# drop a basename with a real stem.
fresh
story_with A feature PLANNED 2 <<'EOF'
CONTRACT:`scripts/plan.sh` gains a subcommand; `.claude/tests/plan.test.sh` pins it; `plan.sh` stays bash.
EOF
assert_eq "a prose-only Contract naming a bare plan.sh keeps RED on the weaker model" \
  "fable" "$(red_model A)"

# (b) The same prose with a **Writes:** line naming only harness paths. The
# declared writes are what the lock would have to freeze, and it freezes none
# of them: the unenforced row, `opus`. This is Amendment A-1's move.
fresh
story_with A feature PLANNED 2 <<'EOF'
CONTRACT:**Writes:** `scripts/plan.sh`, `.claude/tests/plan.test.sh`
CONTRACT:`scripts/plan.sh` gains a subcommand; `.claude/tests/plan.test.sh` pins it; `plan.sh` stays bash.
EOF
assert_eq "a **Writes:** line naming only harness paths puts RED on the stronger model" \
  "opus" "$(red_model A)"

# (b') The prose names a source file the story only reads. The **Writes:** line
# decides, not the prose: still unenforced.
fresh
story_with A feature PLANNED 2 <<'EOF'
CONTRACT:**Writes:** `scripts/plan.sh`, `.claude/tests/plan.test.sh`
CONTRACT:Reads `src/core/world.ts` for its fixture shape; does not change it.
EOF
assert_eq "a source file the prose only reads does not make a harness-only **Writes:** enforced" \
  "opus" "$(red_model A)"

# (c) THE CONTROL: one source path on the **Writes:** line is enough for the
# lock to bite, so RED stays on the weaker model.
fresh
story_with A feature PLANNED 2 <<'EOF'
CONTRACT:**Writes:** `src/core/world.ts`, `scripts/plan.sh`
EOF
assert_eq "a **Writes:** line with one source path keeps RED on the weaker model" \
  "fable" "$(red_model A)"

# ---------------------------------------------------------------------------
describe "waves: the planner cuts stories into waves (HARNESS-007)"

# WHAT THIS IS FOR. `conflicts` reports which pairs of startable stories would
# fight over a file. A planner does not think in pairs; it thinks in "which of
# these can run together". `waves` arranges the same pairwise answer as groups:
# within a wave every pair is clear, and a story that collides with something
# in every existing wave opens the next one. Greedy first fit, in candidate
# order - not minimal, and not claimed to be.
#
# LAST IN THE FILE ON PURPOSE. Every fixture set below starts from an empty
# stories directory (`fresh`, defined in the HARNESS-006 block above), which
# would delete stories any later section depended on.
#
# EVERY NEEDLE IS A WHOLE LINE OR A WHOLE FIELD. `WAVE 1` floating also matches
# `WAVE 10`, and an id `T-1` floating matches `T-10`: grep -cxF for lines, awk
# field equality for ids. And no assertion here is an absence on its own: "U is
# in no wave" is satisfied by a command that prints nothing, which is exactly
# what RED prints. Each absence travels with a presence in the same assertion,
# so every one of them was watched fail. Exit 0 is an absence too: before
# `waves` existed it fell to the `*` arm, cmd_both, whose `die` runs in a
# command substitution and does not end the script - so `plan.sh waves` exited
# 0, and a bare "exits 0" assertion passed on arrival. Measured in RED: three
# did. Each is now paired with the summary line it implies.

# wline <exact line>   How many lines of $out are exactly this.
wline() { grep -cxF -- "$1" <<<"$out"; }
# where <id>...   "A=1 B=2 U=-": the wave(s) each id is placed in, read by field
# equality on WAVE lines, comma-joined if more than one; `-` for none. Asking
# for several ids at once is what ties an absence to a presence.
where() {
  local id s=""
  for id in "$@"; do
    s="$s$id=$(awk -v id="$id" '
      $1 == "WAVE" { for (k = 3; k <= NF; k++) if ($k == id) w = w (w == "" ? "" : ",") $2 }
      END { print (w == "" ? "-" : w) }' <<<"$out") "
  done
  printf '%s' "${s% }"
}
# labels_for <id>   The first field of every line whose second field is the id,
# space-joined: WAVE lines have the wave number there, so this sees only
# BLOCKED and UNKNOWN lines.
labels_for() { awk -v id="$1" '$2 == id { s = s (s == "" ? "" : " ") $1 } END { print s }' <<<"$out"; }
# wave_count   How many WAVE lines there are.
wave_count() { awk '$1 == "WAVE" { n++ } END { print n + 0 }' <<<"$out"; }
# waves_rc   The exit status, which is a claim of its own.
waves_rc() { ( cd "$FIX" && bash scripts/plan.sh waves >/dev/null 2>&1 ); printf '%s' "$?"; }

# --- AC-1: pairwise disjoint stories all land in wave 1 --------------------
#
# B is in flight (RED): it still occupies its files, so it is a candidate, as
# it is for `conflicts`. The WHOLE output is pinned once here, because it is
# the simplest case of the Contract's "Output, exactly": label padded to 9,
# ids joined by two spaces, one blank line, the summary.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with B feature RED 1 <<'EOF'
TOUCHES:src/b.ts
EOF
story_with C feature PLANNED 1 <<'EOF'
TOUCHES:src/c.ts, docs/c.md
EOF
out="$(plan waves)"
assert_eq "AC-1: pairwise disjoint stories, in flight or not, are all in wave 1 and nothing else is printed" \
  "WAVE 1   A  B  C

1 wave(s), 0 blocked, 0 unplaceable." "$out"
assert_eq "AC-1: and there are waves, so it exits 0" \
  "0|1" "$(waves_rc)|$(wline '1 wave(s), 0 blocked, 0 unplaceable.')"

# Collision is an exact comparison of whole paths - the `conflicts`
# intersection - not a substring or prefix match.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/a.tsx, src/a.ts.bak
EOF
out="$(plan waves)"
assert_eq "AC-1: paths that merely share a prefix do not collide, so both are in wave 1" \
  "1" "$(wline 'WAVE 1   A  B')"

# AC-1 CONTROL: two whose sets intersect - in one path among several - never
# share a wave, and each is in exactly one wave.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts, src/core/world.ts
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/b.ts, src/core/world.ts
EOF
out="$(plan waves)"
assert_eq "AC-1 control: two stories sharing one path are in different waves, each in exactly one" \
  "A=1 B=2" "$(where A B)"
assert_eq "AC-1 control: wave 1 is exactly A" "1" "$(wline 'WAVE 1   A')"
assert_eq "AC-1 control: wave 2 is exactly B" "1" "$(wline 'WAVE 2   B')"
assert_eq "AC-1 control: the summary counts two waves" \
  "1" "$(wline '2 wave(s), 0 blocked, 0 unplaceable.')"

# MANY, and the reason the needles are anchored: ten stories all sharing one
# file need ten waves, and `WAVE 10` is a line a floating `WAVE 1` would match.
# The label is padded to 9, so a two-digit wave has two spaces, not three.
fresh
for id in A B C D E F G H I J; do
  story_with "$id" feature PLANNED 1 <<'EOF'
TOUCHES:docs/shared.md
EOF
done
out="$(plan waves)"
assert_eq "many: ten stories sharing one file make ten waves, one story each" \
  "A=1 B=2 C=3 D=4 E=5 F=6 G=7 H=8 I=9 J=10" "$(where A B C D E F G H I J)"
assert_eq "many: wave 10 is printed with the label padded to 9 columns" \
  "1" "$(wline 'WAVE 10  J')"
assert_eq "many: and exactly one line is wave 1's, despite wave 10 existing" \
  "1" "$(wline 'WAVE 1   A')"
assert_eq "many: the summary counts ten waves" \
  "1" "$(wline '10 wave(s), 0 blocked, 0 unplaceable.')"

# A DONE story is omitted entirely: it would collide with A, and if it were a
# candidate it would open a second wave.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with D feature DONE 1 <<'EOF'
TOUCHES:src/a.ts
EOF
out="$(plan waves)"
assert_eq "a DONE story is omitted entirely: one wave, A alone, and no line names D" \
  "1|WAVE 1   A|" \
  "$(wave_count)|$(awk '$1 == "WAVE"' <<<"$out")|$(labels_for D)"

# --- AC-2: a wave is a set of MUTUALLY disjoint stories --------------------
#
# As written: A-B collide, B-C collide, A-C do not. First fit puts C back in
# wave 1 beside A. A "next fit" placement, which only tries the newest wave,
# would compare C with B alone and open a third.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/p1.ts
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/p1.ts, src/p2.ts
EOF
story_with C feature PLANNED 1 <<'EOF'
TOUCHES:src/p2.ts
EOF
out="$(plan waves)"
assert_eq "AC-2: A and C share wave 1 and B, which collides with both, is in wave 2" \
  "A=1 B=2 C=1" "$(where A B C)"
assert_eq "AC-2: wave 1 is exactly A and C, in candidate order" "1" "$(wline 'WAVE 1   A  C')"
assert_eq "AC-2: wave 2 is exactly B" "1" "$(wline 'WAVE 2   B')"
assert_eq "AC-2: two waves, not three" "1" "$(wline '2 wave(s), 0 blocked, 0 unplaceable.')"

# AC-2 CONTROL, mutual disjointness. The case above CANNOT catch a placement
# that compares a candidate only with the last story placed in each wave: C's
# wave-1 neighbour is A either way. Here A and C collide and B is disjoint from
# both, in id order A, B, C. Wave 1 is {A, B}; checked only against its last
# member B, C would wrongly join it. Checked against every member, it collides
# with A and opens wave 2.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/p1.ts
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/p2.ts
EOF
story_with C feature PLANNED 1 <<'EOF'
TOUCHES:src/p1.ts
EOF
out="$(plan waves)"
assert_eq "AC-2 control: C collides with A, so it is NOT in wave 1 even though wave 1's last member B is clear of it" \
  "A=1 B=1 C=2" "$(where A B C)"
assert_eq "AC-2 control: wave 1 is exactly A and B" "1" "$(wline 'WAVE 1   A  B')"
assert_eq "AC-2 control: wave 2 is exactly C" "1" "$(wline 'WAVE 2   C')"

# --- AC-3: a story that declares nothing is unplaceable --------------------
#
# U has no touches: key and no Contract; V has `touches: []`, the line
# new-story.sh writes, and no Contract. Both declare nothing, and both are
# reported, never compared - so neither can land in wave 1 by default.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with U feature PLANNED 1 </dev/null
story_with V feature PLANNED 1 <<'EOF'
TOUCHES:
EOF
out="$(plan waves)"
assert_eq "AC-3: undeclared stories are in no wave, and the declared one is placed" \
  "A=1 U=- V=-" "$(where A U V)"
assert_eq "AC-3: wave 1 is exactly A - the undeclared did not silently land there" \
  "1" "$(wline 'WAVE 1   A')"
assert_eq "AC-3: a story with no touches: key and no Contract is listed as unplaceable, with the reason" \
  "1" "$(wline 'UNKNOWN  U  declares no paths - cannot be placed')"
assert_eq "AC-3: so is one with touches: [] and no Contract" \
  "1" "$(wline 'UNKNOWN  V  declares no paths - cannot be placed')"
assert_eq "AC-3: the summary counts them as unplaceable" \
  "1" "$(wline '1 wave(s), 0 blocked, 2 unplaceable.')"
assert_eq "AC-3 control: with one placeable story there are waves, so it exits 0" \
  "0|1" "$(waves_rc)|$(wline '1 wave(s), 0 blocked, 2 unplaceable.')"

# "Declares nothing" means story_paths is empty - the same answer `conflicts`
# uses - so a story with no touches: but a Contract **Writes:** line DOES
# declare, is compared, and here collides with A.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with W feature PLANNED 1 <<'EOF'
CONTRACT:**Writes:** `src/a.ts`
EOF
out="$(plan waves)"
assert_eq "a story declaring only through its Contract is placed, and collides on that path" \
  "A=1 W=2|" "$(where A W)|$(labels_for W)"

# AC-3 CONTROL, the exit status: nothing but undeclared candidates means no
# waves, and that is not a success. The whole output is pinned.
fresh
story_with U feature PLANNED 1 </dev/null
story_with V feature PLANNED 1 <<'EOF'
TOUCHES:
EOF
out="$(plan waves)"
assert_eq "AC-3 control: only undeclared stories - UNKNOWN lines in candidate order, no wave, the summary" \
  "UNKNOWN  U  declares no paths - cannot be placed
UNKNOWN  V  declares no paths - cannot be placed

0 wave(s), 0 blocked, 2 unplaceable." "$out"
assert_eq "AC-3 control: and with nothing judged it exits 1, not 0" "1" "$(waves_rc)"

# Zero waves for the other reasons: a backlog of nothing but DONE stories, and
# an empty one. The summary is always printed, and neither is a success.
fresh
story_with D feature DONE 1 <<'EOF'
TOUCHES:src/d.ts
EOF
out="$(plan waves)"
assert_eq "a backlog of only DONE stories prints just the zero summary" \
  "
0 wave(s), 0 blocked, 0 unplaceable." "$out"
assert_eq "and exits 1" "1" "$(waves_rc)"
fresh
out="$(plan waves)"
assert_eq "an empty backlog prints the zero summary" \
  "1" "$(wline '0 wave(s), 0 blocked, 0 unplaceable.')"
assert_eq "and exits 1" "1" "$(waves_rc)"

# --- AC-4: a story blocked by depends_on is reported, not placed -----------
#
# P is PLANNED, D is DONE. B depends on P: blocked. C depends on D: startable,
# placed normally. E depends on D, P and a story that does not exist: the line
# names every dep that is not DONE, in depends_on order, and skips D. Q is DONE
# with a non-DONE dependency: DONE is decided first, so Q is omitted rather
# than reported blocked. B and E both touch A's file, so a placement that
# ignored ordering would also have to open a second wave for them.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with B feature PLANNED 1 <<'EOF'
DEPENDS:P
TOUCHES:src/a.ts
EOF
story_with C feature PLANNED 1 <<'EOF'
DEPENDS:D
TOUCHES:src/c.ts
EOF
story_with D feature DONE 1 <<'EOF'
TOUCHES:src/d.ts
EOF
story_with E feature PLANNED 1 <<'EOF'
DEPENDS:D, P, Z
TOUCHES:src/a.ts
EOF
story_with P feature PLANNED 1 <<'EOF'
TOUCHES:src/p.ts
EOF
story_with Q feature DONE 1 <<'EOF'
DEPENDS:P
TOUCHES:src/a.ts
EOF
out="$(plan waves)"
assert_eq "AC-4: blocked stories are in no wave; a story whose dependency is DONE is placed normally" \
  "A=1 B=- C=1 E=- P=1" "$(where A B C E P)"
assert_eq "AC-4: wave 1 is exactly the startable stories, in candidate order" \
  "1" "$(wline 'WAVE 1   A  C  P')"
assert_eq "AC-4: the blocked story is reported as blocked, naming the dependency and its phase" \
  "1" "$(wline 'BLOCKED  B  depends_on P (PLANNED)')"
assert_eq "AC-4: every dependency not DONE is named, in order, a missing one as (missing)" \
  "1" "$(wline 'BLOCKED  E  depends_on P (PLANNED), Z (missing)')"
# Q's absence is tied to the summary line: on its own, "no line names Q" is
# also what an empty or failing run prints.
assert_eq "AC-4: the summary counts two blocked, and the DONE story Q, whose dependency is not DONE, appears nowhere" \
  "Q=-||1" "$(where Q)|$(labels_for Q)|$(wline '1 wave(s), 2 blocked, 0 unplaceable.')"

# BLOCKED BEFORE UNKNOWN, and every line kind in its place: the Contract's shape
# block, with ids chosen so that line order CANNOT fall out of id order. A
# declares nothing, B is blocked (and declares nothing, so it could be either:
# it must be listed once, as BLOCKED), F is the dependency, E collides with C.
fresh
story_with A feature PLANNED 1 </dev/null
story_with B feature PLANNED 1 <<'EOF'
DEPENDS:F
EOF
story_with C feature PLANNED 1 <<'EOF'
TOUCHES:src/x.ts
EOF
story_with D feature PLANNED 1 <<'EOF'
TOUCHES:src/y.ts
EOF
story_with E feature PLANNED 1 <<'EOF'
TOUCHES:src/x.ts
EOF
story_with F feature RED 1 <<'EOF'
TOUCHES:src/w.ts
EOF
out="$(plan waves)"
assert_eq "AC-4: every WAVE line, then BLOCKED, then UNKNOWN, then a blank line and the summary" \
  "WAVE 1   C  D  F
WAVE 2   E
BLOCKED  B  depends_on F (RED)
UNKNOWN  A  declares no paths - cannot be placed

2 wave(s), 1 blocked, 1 unplaceable." "$out"
assert_eq "AC-4: a blocked story that also declares nothing is listed once, as BLOCKED" \
  "BLOCKED" "$(labels_for B)"
assert_eq "AC-4: with waves, blocked and unplaceable together, it exits 0" \
  "0|1" "$(waves_rc)|$(wline '2 wave(s), 1 blocked, 1 unplaceable.')"

# ---------------------------------------------------------------------------
describe "conflicts --pairs: the clear pairs, for an orchestrator to read (HARNESS-009)"

# WHY. lead-po selects which stories may run in two worktrees at once, and the
# rule it is given is: only a pair `conflicts` reports `clear`. The table is for
# a human - padded columns, a header, a rule, DRIFT lines, a footer and an
# "UNKNOWN is not clear" note - and an orchestrator that parses columns out of
# it is one reformat away from selecting the wrong pair. `--pairs` is the same
# judgement in a shape with nothing to misparse: `<id>\t<id>` per clear pair,
# nothing else on stdout, exit 0.
#
# THE CENTRAL CLAIM IS AN OMISSION, so every omission below is discriminated
# against a SIBLING THAT IS PRINTED from the same run: the CONFLICT pair, the
# UNKNOWN story and the blocked story all sit in one backlog beside clear pairs,
# and the blocked story declares a path that collides with nothing, so were it
# wrongly let in it would produce clear-looking lines. An output that is merely
# empty fails the exact-equality assertions; one that lets a pair in fails the
# whole-line counts.
#
# NEEDLES. Exact equality against the whole of stdout, or whole-line counts
# (`grep -cxF`) and whole-field equality in awk - never a floating substring.
# `A<TAB>B` floats inside `A<TAB>BC`, and `H-1` inside `H-10`; the second
# fixture is built out of ids that prefix one another for exactly that reason.
#
# stdout and stderr are captured SEPARATELY here, unlike `plan()`: the Contract
# says `--pairs` is read from stdout only, so a helper that folded stderr in
# would let a usage message pass as output, or output hide in a usage message.

PAIRS_ERR="$FIX/.pairs.stderr"
# pairs_run <args...>   Sets p_out (stdout), p_err (stderr), p_rc (status).
pairs_run() {
  p_out="$( cd "$FIX" && bash scripts/plan.sh conflicts "$@" 2>"$PAIRS_ERR" )"; p_rc=$?
  p_err="$(cat "$PAIRS_ERR")"
}
# table_clear_pairs   The table's `clear` rows over the same backlog, rendered
# as `<id>\t<id>` in the table's own order - read from the STATUS column, never
# from a floating `clear`, which the footer's "UNKNOWN is not clear" also holds.
# Captured first, then read: no pipe into the reader (WORLD-086's house rule).
table_clear_pairs() {
  local t; t="$( cd "$FIX" && bash scripts/plan.sh conflicts 2>/dev/null )"
  awk '$1 == "clear" && $3 == "+" { printf "%s\t%s\n", $2, $4 }' <<<"$t"
}
# pline <a> <b>   How many stdout lines are EXACTLY `<a>\t<b>`.
pline() { grep -cxF "$1	$2" <<<"$p_out"; }
# naming <id>   How many stdout lines carry <id> as either whole field.
naming() { awk -F'\t' -v id="$1" '$1 == id || $2 == id { n++ } END { print n + 0 }' <<<"$p_out"; }

# --- AC-1: one backlog holding every kind of pair ---------------------------
#
#   A  touches src/a.ts             (and a **Writes:** line touches: misses,
#                                    so the table prints a DRIFT line)
#   B  touches src/b.ts
#   C  touches src/a.ts             -> A + C is CONFLICT
#   D  declares nothing             -> every D pair is UNKNOWN
#   E  touches src/e.ts, depends on F (RED) -> blocked, never a candidate;
#                                    its path is disjoint, so letting it in
#                                    would produce clear-looking lines
#   F  touches src/f.ts, phase RED
#
# Clear, in story_walk order: A+B, A+F, B+C, B+F, C+F. Single-letter ids so the
# glob order the walk uses cannot depend on the locale's collation.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
CONTRACT:**Writes:** `src/a.ts`, `src/a-extra.ts`
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/b.ts
EOF
story_with C feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with D feature PLANNED 1 </dev/null
story_with E feature PLANNED 1 <<'EOF'
TOUCHES:src/e.ts
DEPENDS:F
EOF
story_with F feature RED 1 <<'EOF'
TOUCHES:src/f.ts
EOF

pairs_run --pairs
assert_eq "AC-1: --pairs prints exactly the clear pairs, one <id><TAB><id> line each, in the table's order, and nothing else" \
  "A	B
A	F
B	C
B	F
C	F" "$p_out"
assert_eq "AC-1: --pairs exits 0 though the backlog holds a CONFLICT and an UNKNOWN pair" "0" "$p_rc"
assert_eq "AC-1: --pairs writes nothing to stderr on an ordinary run" "" "$p_err"

# The negative controls, each a whole-line or whole-field count so that a
# neighbouring line cannot satisfy it. The sibling assertion comes first: an
# empty stdout would satisfy every "absent" below.
assert_eq "AC-1 control: the clear sibling A<TAB>B is printed exactly once" "1" "$(pline A B)"
assert_eq "AC-1 control: the CONFLICT pair A + C is never printed, either way round" "0|0" \
  "$(pline A C)|$(pline C A)"
assert_eq "AC-1 control: the UNKNOWN story D appears on no line - unknown is not permission" "0" "$(naming D)"
assert_eq "AC-1 control: the blocked story E appears on no line, though its path collides with nothing" "0" "$(naming E)"

# Shape, stated independently of the exact equality above so a failure names
# which property broke: every line two non-empty fields and one TAB, nothing
# trailing; five distinct pairs; no pair twice in either orientation.
assert_eq "AC-1: every line is <id><TAB><id> - one TAB, no space, no trailing whitespace" "0" \
  "$(awk '!/^[^\t ]+\t[^\t ]+$/ { n++ } END { print n + 0 }' <<<"$p_out")"
assert_eq "AC-1: each pair is printed once, in one orientation only" "5|5" \
  "$(awk -F'\t' '{ k = ($1 < $2) ? $1 "\t" $2 : $2 "\t" $1; if (!(k in s)) { s[k] = 1; n++ } } END { print n + 0 }' <<<"$p_out")|$(awk 'END { print NR }' <<<"$p_out")"
assert_eq "AC-1: no header, rule, DRIFT, footer or UNKNOWN note reaches stdout" "0" \
  "$(awk '/STATUS|-----|DRIFT|conflict\(s\)|UNKNOWN|not clear|fewer than/ { n++ } END { print n + 0 }' <<<"$p_out")"

# ONE COMPUTATION, TWO RENDERINGS. The lines are the table's clear rows over the
# same backlog, compared whole and in order. This is what keeps --pairs from
# being a second judgement that one day disagrees with the first.
assert_eq "AC-1: --pairs is exactly the table's clear rows over the same backlog, in the same order" \
  "$(table_clear_pairs)" "$p_out"

# AC-5, the half a suite can hold: the table over this same backlog is byte for
# byte what it printed before --pairs existed, and still exits 1 on a CONFLICT.
# GREEN ON ARRIVAL - a regression guard, earned in RED by a mutate.sh probe on
# the table's `clear` detail text (the story's handoff has the output).
out="$( cd "$FIX" && bash scripts/plan.sh conflicts 2>/dev/null )"; t_rc=$?
# `sp` is the one trailing space shared_paths leaves on a CONFLICT detail,
# written as a variable because an editor that strips trailing whitespace would
# otherwise change this expectation silently.
sp=" "
assert_eq "AC-5: conflicts with no argument prints the same table as before --pairs existed" \
  "STATUS    PAIR                      DETAIL
--------- ------------------------- ------------------------
clear     A + B                     no shared path
CONFLICT  A + C                     src/a.ts${sp}
UNKNOWN   A + D                     declares neither touches: nor Contract paths - cannot judge
clear     A + F                     no shared path
clear     B + C                     no shared path
UNKNOWN   B + D                     declares neither touches: nor Contract paths - cannot judge
clear     B + F                     no shared path
UNKNOWN   C + D                     declares neither touches: nor Contract paths - cannot judge
clear     C + F                     no shared path
UNKNOWN   D + F                     declares neither touches: nor Contract paths - cannot judge

DRIFT     A             contract names src/a-extra.ts, touches: does not

1 conflict(s), 4 pair(s) that could not be judged, 1 drift warning(s).
UNKNOWN is not clear: a story that declares neither touches: nor Contract
paths gives no basis to judge. Judge those pairs by hand, or fill touches:." "$out"
assert_eq "AC-5: and still exits 1 when there is a CONFLICT" "1" "$t_rc"

# --- AC-1: ids that are prefixes of one another -----------------------------
#
#   H-1    declares nothing        -> UNKNOWN with everything
#   H-10   touches src/a.ts
#   H-11   touches src/b.ts
#   H-110  touches src/a.ts        -> H-10 + H-110 is CONFLICT
#   H-2    touches src/z.ts, depends on H-10 (PLANNED) -> blocked
#
# Clear: H-10+H-11 and H-11+H-110, and nothing else. An implementation that
# drops the UNKNOWN story's pairs by substring (`*H-1*`) drops both, and one
# that drops the CONFLICT pair by substring drops H-11+H-110 with it. Glob order
# over these names differs between the C and en_US collations, so the ORDER is
# checked against the table and the SET against a C-sorted literal.
fresh
story_with H-1 feature PLANNED 1 </dev/null
story_with H-10 feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with H-11 feature PLANNED 1 <<'EOF'
TOUCHES:src/b.ts
EOF
story_with H-110 feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with H-2 feature PLANNED 1 <<'EOF'
TOUCHES:src/z.ts
DEPENDS:H-10
EOF

pairs_run --pairs
p_set="$(awk -F'\t' '{ print (($1 < $2) ? $1 "\t" $2 : $2 "\t" $1) }' <<<"$p_out")"
assert_eq "AC-1: with ids that prefix one another, the set of lines is exactly the two clear pairs" \
  "H-10	H-11
H-11	H-110" "$(LC_ALL=C sort <<<"$p_set")"
assert_eq "AC-1: and in the table's order, matching it line for line" "$(table_clear_pairs)" "$p_out"
assert_eq "AC-1 control: the UNKNOWN story H-1 is on no line, while H-10, H-11 and H-110 are" \
  "0|1|2|1" "$(naming H-1)|$(naming H-10)|$(naming H-11)|$(naming H-110)"
assert_eq "AC-1 control: the CONFLICT pair H-10 + H-110 is never printed, either way round" "0|0" \
  "$(pline H-10 H-110)|$(pline H-110 H-10)"
assert_eq "AC-1 control: the blocked story H-2 is on no line" "0" "$(naming H-2)"
assert_eq "AC-1: with prefix ids, --pairs exits 0" "0" "$p_rc"

# --- AC-1: nothing may pair -------------------------------------------------
#
# Only a CONFLICT and UNKNOWNs: the table exits 1, --pairs prints nothing and
# exits 0 - "nothing may pair" is an answer, and `pairs=$(plan.sh conflicts
# --pairs)` under `set -e` must not die on it.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with C feature PLANNED 1 </dev/null
pairs_run --pairs
assert_eq "AC-1: a backlog with no clear pair gives empty stdout and exit 0 (the table's CONFLICT status does not leak)" \
  "|0" "$p_out|$p_rc"
assert_eq "AC-5: while the table over the same backlog still exits 1" "1" "$(conflicts_rc)"
assert_eq "AC-1: a set -e caller survives the empty answer" "survived" \
  "$( cd "$FIX" && bash -ec 'p="$(bash scripts/plan.sh conflicts --pairs 2>/dev/null)"; printf survived' )"

# --- AC-1: fewer than two startable stories ---------------------------------
#
# The table prints a sentence here; --pairs prints nothing. Three shapes: an
# empty backlog, one story, and two stories one of which is blocked - the last
# is the one where "two stories exist" and "two are startable" differ.
fresh
pairs_run --pairs
assert_eq "AC-1: an empty backlog gives empty stdout and exit 0" "|0" "$p_out|$p_rc"

fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
pairs_run --pairs
assert_eq "AC-1: one startable story gives empty stdout and exit 0, not the fewer-than-two sentence" \
  "|0" "$p_out|$p_rc"

story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/b.ts
DEPENDS:A
EOF
pairs_run --pairs
assert_eq "AC-1: two stories, one blocked, is fewer than two startable: empty stdout and exit 0" \
  "|0" "$p_out|$p_rc"

# --- AC-1: an unrecognised argument refuses ---------------------------------
#
# A typo must not fall back to the human table, which an orchestrator would
# then misparse. Over a backlog WITH a clear pair, so "prints no table" is not
# satisfied by there being nothing to print. `conflicts` bare is unchanged, and
# the AC-5 assertions above hold it.
fresh
story_with A feature PLANNED 1 <<'EOF'
TOUCHES:src/a.ts
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/b.ts
EOF
for bad in --pair --json pairs; do
  pairs_run "$bad"
  assert_eq "AC-1: conflicts $bad exits non-zero and prints nothing on stdout" \
    "nonzero|" "$(if [ "$p_rc" -ne 0 ]; then printf nonzero; else printf zero; fi)|$p_out"
  assert_eq "AC-1: conflicts $bad puts a usage message on stderr" "1" \
    "$(awk 'tolower($0) ~ /usage/ { n = 1 } END { print n + 0 }' <<<"$p_err")"
done
pairs_run --pairs
assert_eq "AC-1 control: the same backlog's --pairs prints its one clear pair, so the refusals above are not an empty backlog" \
  "A	B|0" "$p_out|$p_rc"

# ---------------------------------------------------------------------------
describe "after: closing a story names what to run next, and what can run alongside it (HARNESS-018)"

# WHY. Every closing report used to be reconstructed by hand from five commands
# - `next`, `waves`, `conflicts --pairs`, the epic rule in advance-story.md and
# the worktree recipe in CLAUDE.md - and came out different every time. `after`
# is the whole answer in one report, and `phase.sh set <id> DONE` prints it.
#
# LAST IN THE FILE, like the blocks above it: every fixture starts from `fresh`.
#
# NEEDLES. Every label assertion is a WHOLE LINE (`grep -cxF`), so `Next:` can
# never be satisfied by `Next:` on some other story, `C` cannot float inside
# `CC`, and the padding the Contract fixes (`printf '%-11s'`) is part of what is
# matched. Every "is NOT listed" assertion counts the exact listing line AND
# travels in the same assert_eq with a presence from the same run - the reason
# line that says why it was left out, or the Next line - so an output that is
# merely empty, which is what RED prints, fails it rather than passing it.
#
# stdout and stderr are captured SEPARATELY: the Contract says `after` writes to
# stdout only and always exits 0.

AFTER_ERR="$FIX/.after.stderr"
# after_run [args...]   Sets a_out (stdout), a_err (stderr), a_rc (status).
after_run() {
  a_out="$( cd "$FIX" && bash scripts/plan.sh after "$@" 2>"$AFTER_ERR" )"; a_rc=$?
  a_err="$(cat "$AFTER_ERR")"
}
# aline <exact line>   How many lines of a_out are exactly this.
aline() { grep -cxF -- "$1" <<<"$a_out"; }
# alabel <prefix>   How many lines of a_out START with this prefix. Used only
# for "this block is absent", and always paired with a presence.
alabel() { awk -v l="$1" 'index($0, l) == 1 { n++ } END { print n + 0 }' <<<"$a_out"; }
# acount <ere>   How many lines of a_out match an ERE anywhere.
acount() { awk -v re="$1" '$0 ~ re { n++ } END { print n + 0 }' <<<"$a_out"; }
# The directory name the worktree lines are built from: the basename of the
# repository root, computed the way plan.sh computes its ROOT.
REPO_BASE="$( cd "$FIX" && basename "$(pwd)" )"
# cmd_next's reason for one story, verbatim - the Contract says the Next block
# carries it unchanged, and `next` is the existing command that produces it.
reason_of() { ( cd "$FIX" && bash scripts/plan.sh next "$1" 2>/dev/null | cut -f2- ); }
IND='           '     # 11 spaces: a continuation line
LST='             '   # 13 spaces: a listed command or worktree line

# --- AC-1, AC-2, AC-4: one backlog holding every disposition ----------------
#
#   A  DONE,     epic E1, touches src/a.ts          <- the closed story
#   B  PLANNED,  touches src/j.ts, depends on C (PLANNED) and Z (no file)
#                -> Blocked, first non-DONE story in backlog order, never Next;
#                   and it shares src/j.ts with J, so were a blocked story a
#                   member, J would be refused
#   C  PLANNED,  epic E1, touches src/c.ts          -> Next, /complete-story
#   D  RED,      touches src/d.ts, src/d2.ts        -> In flight; a member
#   E  PLANNED,  touches src/e.ts, src/a.ts, Deferred verification
#                -> Alongside, with ITS OWN command /advance-story; src/a.ts
#                   is A's, and A is DONE, so DONE stories are not members
#   F  PLANNED,  touches src/c.ts                   -> shares with Next (C)
#   G  PLANNED,  touches src/e.ts                   -> shares with E, a story
#                   listed earlier in the same run
#   H  PLANNED,  touches src/d.ts, src/d2.ts        -> shares two paths with
#                   D, in flight
#   I  PLANNED,  declares nothing                   -> UNKNOWN, not listed
#   J  PLANNED,  declares src/j.ts on a Contract **Writes:** line only
#                -> Alongside, /complete-story; read through story_paths
#
# C is in epic E1 and not DONE, so closing A must NOT recommend
# /audit-mutations E1 (AC-5 control, the "another story not DONE" half).
fresh
story_with A feature DONE 1 <<'EOF'
TOUCHES:src/a.ts
EPIC:E1
EOF
story_with B feature PLANNED 1 <<'EOF'
TOUCHES:src/j.ts
DEPENDS:C, Z
EOF
story_with C feature PLANNED 1 <<'EOF'
TOUCHES:src/c.ts
EPIC:E1
EOF
story_with D feature RED 1 <<'EOF'
TOUCHES:src/d.ts, src/d2.ts
EOF
story_with E feature PLANNED 1 <<'EOF'
TOUCHES:src/e.ts, src/a.ts
DEFERRED:- With the encoder broken, AC-1 MUST fail. Owner: GATES.
EOF
story_with F feature PLANNED 1 <<'EOF'
TOUCHES:src/c.ts
EOF
story_with G feature PLANNED 1 <<'EOF'
TOUCHES:src/e.ts
EOF
story_with H feature PLANNED 1 <<'EOF'
TOUCHES:src/d.ts, src/d2.ts
EOF
story_with I feature PLANNED 1 </dev/null
story_with J feature PLANNED 1 <<'EOF'
CONTRACT:**Writes:** `src/j.ts`
EOF

C_REASON='C is an ordinary cycle: a contract to work from, 1 criteria, nothing deferred, no dependency waiting. Run it end to end.'
assert_eq "AC-1 fixture: the reason expected for C is what plan.sh next says for it (pins the fixture, not after)" \
  "$C_REASON" "$(reason_of C)"

after_run A
# The whole report, once, because the Contract fixes the format exactly: block
# order, label padding, the 13-column indent of commands and worktree lines,
# and reason lines in backlog order after the worktree instructions.
AFTER_A_BODY="Next:      /complete-story C
${IND}$C_REASON

Alongside: can start now, in parallel with C - no two of these, and no story in flight, declare a shared path:
${LST}/advance-story E
${LST}/complete-story J
${IND}To run them together, give each its own worktree (one worktree, one story):
${LST}git worktree add ../$REPO_BASE-E -b story/E-fixture
${LST}git worktree add ../$REPO_BASE-J -b story/J-fixture
${IND}then run its command from inside that worktree.
${IND}F shares src/c.ts with C
${IND}G shares src/e.ts with E
${IND}H shares src/d.ts src/d2.ts with D
${IND}I declares no paths, so it cannot be judged - UNKNOWN is not clear

In flight: D (RED)  /advance-story D

Blocked:   B  depends_on C (PLANNED), Z (missing)"
assert_eq "AC-1..AC-4: after A prints exactly the Contract's report for this backlog" \
  "After A:

$AFTER_A_BODY" "$a_out"
assert_eq "after exits 0 and writes nothing to stderr on an ordinary run" "0||1" \
  "$a_rc|$a_err|$(aline 'Next:      /complete-story C')"

# The same properties line by line, so a failure names which one broke.
assert_eq "AC-1: the header names the closed story" "1" "$(aline 'After A:')"
assert_eq "AC-1: Next names the first startable PLANNED story with plan.sh next's command" \
  "1" "$(aline 'Next:      /complete-story C')"
assert_eq "AC-1: and carries plan.sh next's reason verbatim on the line after it" \
  "${IND}$(reason_of C)" "$(awk 'p { print; exit } $0 == "Next:      /complete-story C" { p = 1 }' <<<"$a_out")"
assert_eq "AC-1 control: the blocked story B, first in backlog order, is not named by Next while C is" \
  "0|0|1" "$(alabel 'Next:      /complete-story B')|$(alabel 'Next:      /advance-story B')|$(aline 'Next:      /complete-story C')"
assert_eq "AC-1: there is exactly one Next line" "1" "$(alabel 'Next:')"

assert_eq "AC-2: a disjoint startable story is listed under Alongside with its own command (advance-story, from its Deferred verification)" \
  "1" "$(aline "${LST}/advance-story E")"
assert_eq "AC-2: a second disjoint story is listed too, its paths read from a Contract **Writes:** line" \
  "1" "$(aline "${LST}/complete-story J")"
assert_eq "AC-2: each listed story gets one git worktree add line, on its frontmatter branch" \
  "1|1" "$(aline "${LST}git worktree add ../$REPO_BASE-E -b story/E-fixture")|$(aline "${LST}git worktree add ../$REPO_BASE-J -b story/J-fixture")"
assert_eq "AC-2: and one worktree line per listed story, no more" \
  "2" "$(acount 'git worktree add')"
assert_eq "AC-2: the report says to run each command from inside its worktree" \
  "1" "$(aline "${IND}then run its command from inside that worktree.")"
assert_eq "AC-2: a story whose only overlap is with a DONE story is listed (DONE is not a member)" \
  "1|0" "$(aline "${LST}/advance-story E")|$(acount 'shares src/a[.]ts')"
assert_eq "AC-2: a story whose only overlap is with a BLOCKED story is listed (blocked is not a member)" \
  "1|0|1" "$(aline "${LST}/complete-story J")|$(acount 'shares src/j[.]ts')|$(aline 'Blocked:   B  depends_on C (PLANNED), Z (missing)')"

# THE CONTROLS. Absent listing line AND present reason line, in one assertion.
assert_eq "AC-2 control: a story sharing a path with Next is not listed, and the shared path is named" \
  "0|0|1" "$(aline "${LST}/complete-story F")|$(aline "${LST}/advance-story F")|$(aline "${IND}F shares src/c.ts with C")"
assert_eq "AC-2 control: a story sharing a path with another LISTED story is not listed, and the path and story are named" \
  "0|0|1" "$(aline "${LST}/complete-story G")|$(aline "${LST}/advance-story G")|$(aline "${IND}G shares src/e.ts with E")"
assert_eq "AC-2 control: a story sharing paths with an in-flight story is not listed, and every shared path is named" \
  "0|0|1" "$(aline "${LST}/complete-story H")|$(aline "${LST}/advance-story H")|$(aline "${IND}H shares src/d.ts src/d2.ts with D")"
assert_eq "AC-2 control: a story declaring no paths is not listed, and is named as one that cannot be judged" \
  "0|0|1" "$(aline "${LST}/complete-story I")|$(aline "${LST}/advance-story I")|$(aline "${IND}I declares no paths, so it cannot be judged - UNKNOWN is not clear")"
assert_eq "AC-2 control: no worktree line for any story left out, while the listed ones have theirs" "0|0|0|0|2" \
  "$(acount "$REPO_BASE-F ")|$(acount "$REPO_BASE-G ")|$(acount "$REPO_BASE-H ")|$(acount "$REPO_BASE-I ")|$(acount 'git worktree add')"

assert_eq "AC-4: an in-flight story is named with its phase and /advance-story" \
  "1" "$(aline 'In flight: D (RED)  /advance-story D')"
assert_eq "AC-4: a blocked story is named with every dependency that is not DONE, missing ones as missing" \
  "1" "$(aline 'Blocked:   B  depends_on C (PLANNED), Z (missing)')"
assert_eq "AC-4: the in-flight story is offered neither as Next nor Alongside" "0|0|1" \
  "$(alabel 'Next:      /advance-story D')|$(aline "${LST}/advance-story D")|$(aline 'In flight: D (RED)  /advance-story D')"

assert_eq "AC-5 control: closing A, whose epic E1 still holds C (PLANNED), recommends no audit" \
  "0|0|1" "$(alabel 'Epic:')|$(acount 'audit-mutations')|$(aline 'Next:      /complete-story C')"

# Without a closed id, or with one that names no story: the same report minus
# the header (and the epic check), still exit 0.
after_run
assert_eq "after with no id prints the same report without the header, exit 0" \
  "$AFTER_A_BODY|0" "$a_out|$a_rc"
after_run NOPE
assert_eq "after with an id that names no story prints the report without a header, exit 0" \
  "$AFTER_A_BODY|0" "$a_out|$a_rc"

# --- AC-3: nothing can join -------------------------------------------------
#
#   N  PLANNED, touches src/n.ts  -> Next
#   O  PLANNED, touches src/n.ts  -> shares with N
#   P  PLANNED, declares nothing  -> UNKNOWN
fresh
story_with N feature PLANNED 1 <<'EOF'
TOUCHES:src/n.ts
EOF
story_with O feature PLANNED 1 <<'EOF'
TOUCHES:src/n.ts
EOF
story_with P feature PLANNED 1 </dev/null
after_run
assert_eq "AC-3: with nothing able to join, Alongside says run one at a time and still names why each was left out" \
  "Next:      /complete-story N
${IND}$(reason_of N)

Alongside: nothing - run one story at a time.
${IND}O shares src/n.ts with N
${IND}P declares no paths, so it cannot be judged - UNKNOWN is not clear" "$a_out"
assert_eq "AC-3 control: no worktree instructions when nothing joins, while the one-at-a-time line is there" \
  "0|0|1" "$(acount 'git worktree add')|$(acount 'To run them together')|$(aline 'Alongside: nothing - run one story at a time.')"
assert_eq "AC-3 control: neither O nor P is listed" "0|0|1|1" \
  "$(alabel "${LST}/")|$(acount 'can start now')|$(aline "${IND}O shares src/n.ts with N")|$(aline "${IND}P declares no paths, so it cannot be judged - UNKNOWN is not clear")"

# A single startable story and nothing else: still one at a time, no reasons.
fresh
story_with N feature PLANNED 1 <<'EOF'
TOUCHES:src/n.ts
EOF
after_run
assert_eq "AC-3: a lone startable story gets Next and run-one-at-a-time, and nothing else" \
  "Next:      /complete-story N
${IND}$(reason_of N)

Alongside: nothing - run one story at a time." "$a_out"

# --- Alongside when a member declares no paths ------------------------------
#
# Nothing can be judged against a member with no paths, so nothing is listed -
# even a story that is disjoint from everything that DID declare.
#   R  RED,     declares nothing      -> in flight, a member, unjudgeable
#   S  PLANNED, touches src/s.ts      -> Next
#   T  PLANNED, touches src/t.ts      -> disjoint from S, still not listed
#   U  REVIEW,  touches src/u.ts      -> second in-flight line
fresh
story_with R feature RED 1 </dev/null
story_with S feature PLANNED 1 <<'EOF'
TOUCHES:src/s.ts
EOF
story_with T feature PLANNED 1 <<'EOF'
TOUCHES:src/t.ts
EOF
story_with U feature REVIEW 1 <<'EOF'
TOUCHES:src/u.ts
EOF
after_run
assert_eq "AC-2: an in-flight story with no paths means nothing is listed alongside, and it is named" \
  "1|0|0" "$(aline 'Alongside: nothing - R declares no paths, so nothing can be judged against it.')|$(alabel "${LST}/")|$(acount 'git worktree add')"
assert_eq "AC-4: several in-flight stories are one line each, continuation lines indented 11" \
  "1|1" "$(aline 'In flight: R (RED)  /advance-story R')|$(aline "${IND}U (REVIEW)  /advance-story U")"
assert_eq "AC-1: in-flight stories earlier in backlog order are never Next" \
  "1|1" "$(aline 'Next:      /complete-story S')|$(alabel 'Next:')"

fresh
story_with S feature PLANNED 1 </dev/null
story_with T feature PLANNED 1 <<'EOF'
TOUCHES:src/t.ts
EOF
after_run
assert_eq "AC-2: a Next story with no paths means nothing is listed alongside, and it is named" \
  "1|1|0" "$(aline 'Next:      /complete-story S')|$(aline 'Alongside: nothing - S declares no paths, so nothing can be judged against it.')|$(alabel "${LST}/")"

# --- AC-5: nothing startable, and the epic check ----------------------------
#
#   X1, X2  DONE, epic E1   -> E1 is closed when X1 closes
#   V       PLANNED, epic E10, blocked on missing W9
#           -> not startable; its epic E10 is not E1 (a prefix), so it must
#              not hold E1 open
fresh
story_with X1 feature DONE 1 <<'EOF'
TOUCHES:src/x.ts
EPIC:E1
EOF
story_with X2 feature DONE 1 <<'EOF'
TOUCHES:src/x2.ts
EPIC:E1
EOF
story_with V feature PLANNED 1 <<'EOF'
TOUCHES:src/v.ts
EPIC:E10
DEPENDS:W9
EOF
after_run X1
assert_eq "AC-5: no startable story - Next says so and names /plan-story; the closed epic is recommended for an audit" \
  "After X1:

Next:      no new story is startable.
${IND}Add work with /plan-story.

Blocked:   V  depends_on W9 (missing)

Epic:      E1 has no open story left - /audit-mutations E1 is recommended; nothing runs it automatically." "$a_out"
assert_eq "AC-5: with nothing startable, after still exits 0" "0|1" "$a_rc|$(aline 'Next:      no new story is startable.')"
assert_eq "AC-5: the Epic line names E1, not E10, whose open story V is not in E1" \
  "1" "$(aline 'Epic:      E1 has no open story left - /audit-mutations E1 is recommended; nothing runs it automatically.')"
assert_eq "AC-1 control: a blocked story is never Next, even when it is the only open story" \
  "0|1" "$(alabel 'Next:      /')|$(aline 'Blocked:   V  depends_on W9 (missing)')"

# With no closed id there is no epic check at all.
after_run
assert_eq "AC-5: without a closed id there is no Epic line, while Next still prints" \
  "0|1" "$(alabel 'Epic:')|$(aline 'Next:      no new story is startable.')"

# CONTROL: another story in the epic not DONE. W is in flight in E1, so E1 is
# open; and with something in flight, the /plan-story line is not printed.
story_with W feature GREEN 1 <<'EOF'
TOUCHES:src/w.ts
EPIC:E1
EOF
after_run X1
assert_eq "AC-5 control: with another story in E1 not DONE (W, GREEN), no audit is recommended" \
  "0|0|1" "$(alabel 'Epic:')|$(acount 'audit-mutations')|$(aline 'In flight: W (GREEN)  /advance-story W')"
assert_eq "AC-5: with nothing startable but a story in flight, Next says none is startable and does not send you to /plan-story" \
  "1|0" "$(aline 'Next:      no new story is startable.')|$(acount 'plan-story')"

# CONTROL: an empty epic. Every story is DONE and has `epic:` empty, so an
# implementation that skipped the non-empty check would print an Epic line for
# the empty name.
fresh
story_with Q1 feature DONE 1 <<'EOF'
TOUCHES:src/q.ts
EPIC:
EOF
story_with Q2 feature DONE 1 <<'EOF'
TOUCHES:src/q2.ts
EPIC:
EOF
after_run Q1
assert_eq "AC-5 control: a closed story with an empty epic gets no Epic line, while the rest of the report prints" \
  "After Q1:

Next:      no new story is startable.
${IND}Add work with /plan-story." "$a_out"
assert_eq "AC-5 control: and nothing mentions /audit-mutations" "0|1" \
  "$(acount 'audit-mutations')|$(aline 'After Q1:')"

# An empty backlog is an answer, not an error.
fresh
after_run
assert_eq "AC-5: an empty backlog prints Next with the /plan-story line and exits 0" \
  "Next:      no new story is startable.
${IND}Add work with /plan-story.|0" "$a_out|$a_rc"

# --- help -------------------------------------------------------------------
help_out="$( cd "$FIX" && bash scripts/plan.sh --help 2>&1 )"
assert_eq "plan.sh --help lists the after subcommand" "1" \
  "$(grep -cE '^  bash scripts/plan\.sh after( |$)' <<<"$help_out")"

summary "plan"
