#!/usr/bin/env bash
# Tests for scripts/check-boundaries.sh - the half of CI that judges the
# COMMIT rather than the code.
#
# It reads a story file as it was committed and as it stands on the base
# branch, so every case here is a real two-branch repository: a base commit, a
# story branch, and a diff between them.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT

git -C "$FIX" -c user.email=t@t -c user.name=t branch -M main >/dev/null 2>&1

# The fixture's own branch decides which story is under test, so the CI
# variables that override that have to be cleared - otherwise this suite reads
# the story id out of the branch of whatever PR is running it, finds no story,
# and exits before reaching a single one of the checks below. It passes locally
# and fails on a runner, which is the failure mode the harness spends the rest
# of its documentation warning about. PR_HEAD_SHA goes for the same reason: it
# would recompute the gate hash at a commit in the real repository.
#
# run_boundaries sets BOTH $out and $rc, because they are two different claims
# and this suite spent its whole life making only the first. It passed 52/52
# against a check-boundaries.sh mutated to `exit 1` unconditionally - a script
# refusing every pull request it was ever handed - and it passes today with the
# two-claimant rule downgraded from `problem` to `note`, because `note` prints
# the same words. The status is what CI acts on; the message is only what the
# author reads. A helper that returns the output through a command substitution
# cannot carry the status back, which is why this one sets globals instead.
run_boundaries() { # sets $out and $rc
  out="$( cd "$FIX" && GITHUB_HEAD_REF= PR_HEAD_SHA= bash scripts/check-boundaries.sh main 2>&1 )"
  rc=$?
}

# refused <what> <needle>   Reads $out and $rc from the run just made. Both
# halves, always: a message with exit 0 is a warning nobody is stopped by, and a
# non-zero exit carrying the wrong message sends the next person to the wrong
# rule.
refused() {
  case "$out" in
    *"$2"*) ;;
    *) _bad "$1" "expected a refusal saying: $2
actual:                    $out"; return ;;
  esac
  if [ "${rc:-0}" -eq 0 ]; then
    _bad "$1" "said '$2' but exited 0, so CI would merge this"; return
  fi
  _ok "$1"
}

# accepts_manifest <what>   The other direction, where the run legitimately
# still exits non-zero: these fixture stories carry no ## Gate results, so the
# gate-record rule refuses them for a reason that has nothing to do with the
# manifest. What is asserted is therefore the absence of THIS rule's refusal,
# not a clean exit.
accepts_manifest() {
  case "$out" in
    *"outside the test-dependency block"*) _bad "$1" "refused: $out" ;;
    *) _ok "$1" ;;
  esac
}
commit_all() { git -C "$FIX" add -A >/dev/null 2>&1
               git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "${1:-wip}" >/dev/null 2>&1; }

# story_on_branch   Writes docs/backlog/stories/T-1.md on a fresh story branch
# cut from main, with the body on stdin appended after the frontmatter.
story_on_branch() {
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
  git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
  mkdir -p "$FIX/docs/backlog/stories"
  {
    printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n'
    printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n\n'
    cat
  } > "$FIX/docs/backlog/stories/T-1.md"
  commit_all "story T-1"
}

# HARNESS-037. The 3g and 3h refusals say WHAT counts as a pasted result,
# because an agent that pasted its result as prose with inline backticks was
# told "paste the output" and had no way to learn the rule but to read
# has_pasted_output. The clause is the story's C-1, byte for byte, and it is the
# same in both messages. Pinned as WHOLE lines (grep -cxF, fixed string,
# anchored both ends): the refused helper matches a substring, so a message
# that dropped a word of the rule - "four spaces" for "exactly four spaces" -
# would still satisfy every refused needle in this file.
BLOCK_RULE='a line beginning with three backticks or three tildes (a fence), or a line indented by exactly four spaces - a tab does not count, nor does inline code in backticks, nor anything inside an HTML comment.'
# want_3g <section>   The whole output line 3g prints for fixture story T-1.
want_3g() {
  printf 'FAIL  story T-1: ## %s describes something without showing it. What counts as showing it is the shape, not the words: %s Paste the output as such a block - the failure a reverted mutation produced, or the before/after measurement taken under the gate command. A test corrected while the implementation exists has never been observed to fail, and a description of red is not red.' "$1" "$BLOCK_RULE"
}
WANT_3H="FAIL  story T-1: ## Deferred verifications has no result and no waiver. The phase that owned it has passed and nothing says what happened. What counts as a result is the shape, not the words: $BLOCK_RULE Paste the output as such a block - what was mutated and what failed - or write WAIVED with the reason. This is the control that makes a threshold or a round trip mean anything; skipping it silently is the failure it was filed against."
# whole_line <what> <line>   Reads $out from the run just made: <line> appears
# in it exactly once, as a whole line. A count, on a here-string, never a pipe.
whole_line() {
  assert_eq "$1" 1 "$(grep -cxF -- "$2" <<< "$out")"
}

# ---------------------------------------------------------------------------
describe "a return to RED has to show the red"

# The first non-negotiable is a property of an assertion, not of a phase. On a
# corrective RED the implementation already exists, so the corrected assertion
# passes on its first execution and passes forever unless somebody deliberately
# breaks what it pins. Prose saying that happened is not evidence that it did.
story_on_branch <<'EOF'
## Regressions

The seaFloorM test asserted a RangeError the rule does not require. Corrected
to a floor below sea level, and it passes now.
EOF
run_boundaries
refused "described but not shown" "## Regressions describes something without showing it"

story_on_branch <<'EOF'
## Regressions

The seaFloorM test asserted a RangeError the rule does not require. Corrected
to a floor below sea level. Probed by mutating the guard to compare against
zero, which is the bug the test names:

```
 x compares seaFloorM against the document's sea level, not against zero
 Tests  1 failed | 27 passed (28)
```

Reverted; `git diff` clean.
EOF
run_boundaries
assert_contains "shown in a fence" "ok    ## Regressions carries pasted output" "$out"

story_on_branch <<'EOF'
## Regressions

Corrected the AC-4 helper, which was too slow for the coverage gate. Before and
after, both under `bash scripts/gates.sh --gate coverage`:

    AC-4 property test   4,275 ms  ->  367 ms

Thresholds, seeds and numRuns untouched; the measured statistics are identical.
EOF
run_boundaries
assert_contains "shown as an indented measurement" "ok    ## Regressions carries pasted output" "$out"

# The section is optional. A story that never returned to RED omits it, and
# the template's own commented-out block is not a claim about anything.
story_on_branch <<'EOF'
## Notes

One clean cycle.
EOF
run_boundaries
case "$out" in
  *"## Regressions"*) _bad "an absent section is not a failure" "complained anyway: $out" ;;
  *) _ok "an absent section is not a failure" ;;
esac

story_on_branch <<'EOF'
## Regressions

<!-- REQUIRED if this story ever returned to RED after GREEN or GATES; omit
     otherwise. One block per return:
       * which test, what it asserted, and what was wrong with it
       * what earns it, since "watched it fail" cannot apply once the
         implementation exists -->
EOF
run_boundaries
case "$out" in
  *"## Regressions"*) _bad "an untouched template block is not a claim" "complained anyway: $out" ;;
  *) _ok "an untouched template block is not a claim" ;;
esac

# HARNESS-037 AC-1. A reverted mutation, reported in prose - complete, honest,
# and in the one shape the check cannot see. The refusal has to say what shape
# it CAN see, or the author learns the rule by reading the predicate.
story_on_branch <<'EOF'
## Regressions

The seaFloorM test was corrected to a floor below sea level. Probed by mutating
the guard to compare against zero: the corrected test failed, one failure out
of twenty-eight, and the guard was reverted with cmp clean.
EOF
run_boundaries
refused "AC-1: a reverted mutation in prose is refused" "## Regressions describes something without showing it"
whole_line "AC-1: the 3g refusal for ## Regressions is exactly the line the contract gives, naming what counts" \
  "$(want_3g Regressions)"

# HARNESS-037 AC-3. The message states a rule; these pin that the rule it states
# is the rule the check applies, in both directions. Each passes against today's
# detection - they pin behaviour this story must NOT change - and DV-2 and DV-3
# in the story are what earn them, at GATES.
#
# (a) "three tildes" counts: a ~~~ fence is accepted. DV-3 flips this one.
story_on_branch <<'EOF'
## Regressions

Probed by mutating the guard to compare against zero:

~~~
 x compares seaFloorM against the document's sea level, not against zero
 Tests  1 failed | 27 passed (28)
~~~

Reverted.
EOF
run_boundaries
assert_contains "AC-3 (a): a block fenced with three tildes counts as pasted output" \
  "ok    ## Regressions carries pasted output" "$out"

# (b) "a tab does not count": the only indented line is led by a TAB, written
# with printf so no editor can quietly turn it into spaces. DV-2 flips it.
printf '## Regressions\n\nProbed by mutating the guard to compare against zero; the run printed:\n\n\tTests  1 failed | 27 passed (28)\n\nReverted.\n' | story_on_branch
run_boundaries
refused "AC-3 (b): a result indented by a tab is refused" "## Regressions describes something without showing it"
whole_line "AC-3 (b): and the refusal is AC-1's whole line" "$(want_3g Regressions)"

# (c) "nor anything inside an HTML comment": the only fence lies inside a
# comment, and prose follows. DV-2 flips it.
story_on_branch <<'EOF'
## Regressions

<!-- the shape to use:
```
 x the test name
```
-->
Probed by mutating the guard to compare against zero, and the test failed.
Reverted.
EOF
run_boundaries
refused "AC-3 (c): a fence inside an HTML comment, then prose, is refused" "## Regressions describes something without showing it"
whole_line "AC-3 (c): and the refusal is AC-1's whole line" "$(want_3g Regressions)"

# ---------------------------------------------------------------------------
describe "the story comes from GITHUB_HEAD_REF where CI sets it"

# On a pull_request the checkout is a detached merge commit, so the branch name
# says "HEAD" and names no story; CI passes the real one in GITHUB_HEAD_REF.
# Pinned here because this suite was written without it, inherited the variable
# from the runner, and silently checked nothing at all.
story_on_branch <<'EOF'
## Regressions

Described, not shown.
EOF
head_sha="$(git -C "$FIX" rev-parse HEAD)"
git -C "$FIX" checkout -q --detach "$head_sha" 2>/dev/null
out="$( cd "$FIX" && GITHUB_HEAD_REF=story/T-1-fixture PR_HEAD_SHA= bash scripts/check-boundaries.sh main 2>&1 )"; rc=$?
assert_contains "a detached checkout still finds the story" "story T-1 is in REVIEW" "$out"
git -C "$FIX" checkout -q story/T-1-fixture 2>/dev/null

# ---------------------------------------------------------------------------
describe "a PR is opened from REVIEW, as committed"

# This is why /advance-story sets the phase BEFORE committing. phase.sh set
# rewrites the frontmatter; this script reads the frontmatter back out of the
# commit; so a commit made while the story still said GATES carries GATES to
# CI no matter what the working tree says afterwards. Committing first passed
# whenever the PR happened to be opened before this job ran, which is worse
# than always failing: it taught one project that the order was cosmetic.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
mkdir -p "$FIX/docs/backlog/stories"
printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: GATES\nbranch: story/T-1-fixture\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n' \
  > "$FIX/docs/backlog/stories/T-1.md"
commit_all "T-1 committed before the phase was set"
run_boundaries
refused "a commit carrying GATES is refused" "a PR should be opened from REVIEW or DONE"

# ---------------------------------------------------------------------------
describe "the same rule covers gate probes"

story_on_branch <<'EOF'
## Gate probes

Broke the import boundary and the lint gate failed, as expected. Reverted.
EOF
run_boundaries
refused "a gate probe described but not shown" "## Gate probes describes something without showing it"
# HARNESS-037 AC-1, second case: the probe above is a reverted mutation told in
# prose, and the same refusal names the same rule for this section.
whole_line "AC-1: the 3g refusal for ## Gate probes is exactly the line the contract gives, naming what counts" \
  "$(want_3g 'Gate probes')"

# ---------------------------------------------------------------------------
describe "acceptance criteria are frozen"

# The anchor case: this is what 3d exists for, and it also proves the suite is
# reading the base branch rather than the working tree.
git -C "$FIX" checkout -q main 2>/dev/null
mkdir -p "$FIX/docs/backlog/stories"
printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: PLANNED\nbranch: story/T-1-fixture\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n' \
  > "$FIX/docs/backlog/stories/T-1.md"
commit_all "T-1 planned"

git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works differently now.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n' \
  > "$FIX/docs/backlog/stories/T-1.md"
commit_all "T-1 review"
run_boundaries
refused "changed criteria with no amendment" "## Acceptance criteria differ from main"

# ---------------------------------------------------------------------------
describe "criteria freeze at the last committed PLANNED state (HARNESS-033)"

# Law 6 freezes criteria once a story LEAVES PLANNED, and advance-story.md calls
# PLANNED the last phase in which they may change freely. 3d used to compare
# with the base branch whatever the phase, so a story merged to main at PLANNED
# and refined on its own branch before RED was refused (the manga-translator
# field case, issue #97 finding B) - and a story new in its PR, which is every
# story this repository has run, had no freeze at all. The baseline is now the
# state immediately before the FIRST commit that left PLANNED (else the base),
# and nothing after that commit is consulted.
#
# Every history is built commit by commit, one fresh story id per case, so a
# case that needs "new in the PR" cannot find its id on main. Base copies are
# committed on main and main is put back at the end of the block, so nothing
# below this describe sees them.
#
# "Accepted" is two claims: no criteria refusal, and the exact ok/note line.
# Never exit 0 - these stories carry no ## Gate results, so 3e refuses them.
crit_main_before="$(git -C "$FIX" rev-parse main)"

# crit_write <id> <phase> <criteria> [amendment]   The story file, as it stands
# in the working tree. Its branch: frontmatter is the fixture branch, or 3c
# refuses, and the branch name is where 3d's story id comes from.
crit_write() {
  mkdir -p "$FIX/docs/backlog/stories"
  {
    printf -- '---\nid: %s\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: %s\nbranch: story/%s-fixture\n---\n\n' "$1" "$2" "$1"
    printf -- '## Acceptance criteria\n\n- **AC-1** - %s.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n' "$3"
    [ -n "${4:-}" ] && printf -- '\n## Amendments\n\n%s\n' "$4"
  } > "$FIX/docs/backlog/stories/$1.md"
}
# crit_base <id> <phase> <criteria>   Commits the story on main: the base copy.
crit_base() {
  git -C "$FIX" checkout -q main 2>/dev/null
  crit_write "$1" "$2" "$3"
  commit_all "$1 on main at $2"
}
# crit_branch <id>   A fresh story/<id>-fixture cut from main.
crit_branch() {
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D "story/$1-fixture" >/dev/null 2>&1
  git -C "$FIX" checkout -q -b "story/$1-fixture" 2>/dev/null
}
# crit_commit <id> <phase> <criteria> [amendment]   One committed state. Sets
# $c7 to the first seven characters of the full commit id - not rev-parse
# --short, which can print more.
crit_commit() {
  crit_write "$@"
  commit_all "$1 at $2"
  local c; c="$(git -C "$FIX" rev-parse HEAD)"; c7="${c:0:7}"
}
# run_boundaries_against <base-ref>   run_boundaries with the base ref chosen,
# for AC-6's unwalkable base. Sets $out and $rc.
run_boundaries_against() {
  out="$( cd "$FIX" && GITHUB_HEAD_REF= PR_HEAD_SHA= bash scripts/check-boundaries.sh "$1" 2>&1 )"
  rc=$?
}

# AC-1, the field case: main holds the story at PLANNED v1; the branch refines
# it at PLANNED, then moves on. Today this is refused with `differ from main`.
crit_base T-31 PLANNED "criteria v1"
crit_branch T-31
crit_commit T-31 PLANNED "criteria v2"; p7="$c7"
crit_commit T-31 RED     "criteria v2"
crit_commit T-31 REVIEW  "criteria v2"
run_boundaries
assert_not_contains "AC-1: a refinement committed at PLANNED on the branch is not refused" \
  "## Acceptance criteria differ from" "$out"
assert_contains "AC-1: the criteria are judged against the branch's PLANNED commit" \
  "ok    acceptance criteria unchanged since the last committed PLANNED state ($p7)" "$out"

# AC-2, first case: a return to PLANNED after RED cannot move the baseline.
# New in the PR; today it is skipped as "nothing to freeze".
crit_branch T-32
crit_commit T-32 PLANNED "criteria v1"; first7="$c7"
crit_commit T-32 RED     "criteria v1"
crit_commit T-32 PLANNED "criteria v2"
crit_commit T-32 RED     "criteria v2"
crit_commit T-32 REVIEW  "criteria v2"
run_boundaries
refused "AC-2: a flip back to PLANNED is refused against the FIRST PLANNED commit, not the second" \
  "## Acceptance criteria differ from the last committed PLANNED state ($first7)"

# AC-2, second case: the story had already left PLANNED on main. A PLANNED
# commit on the branch comes after the freeze and cannot reopen it.
# (Control: passes today, and must still pass under DV-1.)
crit_base T-33 RED "criteria v1"
crit_branch T-33
crit_commit T-33 PLANNED "criteria v2"
crit_commit T-33 REVIEW  "criteria v2"
run_boundaries
refused "AC-2: a story already past PLANNED on main cannot be reopened by a PLANNED commit on the branch" \
  "## Acceptance criteria differ from main"

# AC-3, else the base: the refinement was never committed at PLANNED, so the
# baseline is main's copy. (Control: passes today; the case above at REVIEW is
# the same rule.)
crit_base T-34 PLANNED "criteria v1"
crit_branch T-34
crit_commit T-34 RED    "criteria v2"
crit_commit T-34 REVIEW "criteria v2"
run_boundaries
refused "AC-3: a refinement first committed at RED is compared with main" \
  "## Acceptance criteria differ from main"

# AC-4 (a): new in the PR, refined across two PLANNED commits, then frozen.
crit_branch T-35
crit_commit T-35 PLANNED "criteria v1"
crit_commit T-35 PLANNED "criteria v2"; p7="$c7"
crit_commit T-35 RED     "criteria v2"
crit_commit T-35 REVIEW  "criteria v2"
run_boundaries
assert_not_contains "AC-4a: a new story refined while PLANNED is not refused" \
  "## Acceptance criteria differ from" "$out"
assert_contains "AC-4a: a new story is judged against its LAST PLANNED commit" \
  "ok    acceptance criteria unchanged since the last committed PLANNED state ($p7)" "$out"

# AC-4 (b): new in the PR, first committed at RED, changed later. Today this
# is the skip note; it is the hole every new-in-PR story fell through.
crit_branch T-36
crit_commit T-36 RED    "criteria v1"; r7="$c7"
crit_commit T-36 REVIEW "criteria v2"
run_boundaries
refused "AC-4b: a new story first committed at RED is frozen at that commit" \
  "## Acceptance criteria differ from the first commit that left PLANNED ($r7)"

# AC-4 (c): the same history with the criteria left alone.
crit_branch T-37
crit_commit T-37 RED    "criteria v1"; r7="$c7"
crit_commit T-37 REVIEW "criteria v1"
run_boundaries
assert_not_contains "AC-4c: a new story whose criteria never changed after RED is not refused" \
  "## Acceptance criteria differ from" "$out"
assert_contains "AC-4c: and is reported unchanged since the first commit that left PLANNED" \
  "ok    acceptance criteria unchanged since the first commit that left PLANNED ($r7)" "$out"

# AC-4 (d): nothing has left PLANNED, committed or in the working tree.
crit_branch T-38
crit_commit T-38 PLANNED "criteria v1"
crit_commit T-38 PLANNED "criteria v2"
run_boundaries
assert_not_contains "AC-4d: a story that never left PLANNED has no criteria refusal" \
  "## Acceptance criteria differ from" "$out"
assert_contains "AC-4d: and says its criteria are not frozen yet" \
  "  story T-38 has not left PLANNED in any committed state; its criteria are not frozen yet" "$out"

# AC-5: the escape hatch still works on both refused new-in-PR histories.
crit_branch T-32
crit_commit T-32 PLANNED "criteria v1"
crit_commit T-32 RED     "criteria v1"
crit_commit T-32 PLANNED "criteria v2"
crit_commit T-32 RED     "criteria v2"
crit_commit T-32 REVIEW  "criteria v2" "AC-1 said v1 and says v2; approved by the PO because v1 was unsatisfiable."
run_boundaries
assert_not_contains "AC-5: the flip-back history with an ## Amendments entry is not refused" \
  "## Acceptance criteria differ from" "$out"
assert_contains "AC-5: the flip-back history is accepted on its ## Amendments entry" \
  "ok    acceptance criteria changed, with an ## Amendments entry" "$out"

crit_branch T-36
crit_commit T-36 RED    "criteria v1"
crit_commit T-36 REVIEW "criteria v2" "AC-1 said v1 and says v2; approved by the PO because v1 was unsatisfiable."
run_boundaries
assert_not_contains "AC-5: a first-committed-at-RED change with an ## Amendments entry is not refused" \
  "## Acceptance criteria differ from" "$out"
assert_contains "AC-5: a first-committed-at-RED change is accepted on its ## Amendments entry" \
  "ok    acceptance criteria changed, with an ## Amendments entry" "$out"

# AC-6: no merge base, so no history to walk. The base is an ORPHAN branch
# holding the story at PLANNED v1 - chosen over a depth-1 clone because it is
# faster on Windows, and `git merge-base` fails on both. The control is AC-1:
# the same history WITH a merge base is accepted.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" checkout -q --orphan unrelated-T-39 2>/dev/null
crit_write T-39 PLANNED "criteria v1"
commit_all "T-39 on an unrelated history"
crit_branch T-39
crit_commit T-39 PLANNED "criteria v2"
crit_commit T-39 REVIEW  "criteria v2"
run_boundaries_against unrelated-T-39
assert_contains "AC-6: with no merge base the check says the history cannot be walked" \
  "  no merge base with unrelated-T-39, so the branch's history cannot be walked; criteria compared with unrelated-T-39 itself" "$out"
refused "AC-6: and falls back to comparing with the base itself, as before" \
  "## Acceptance criteria differ from unrelated-T-39"

# AC-7: the procedure tells the orchestrator to commit at PLANNED, which is
# what makes the PLANNED baseline reachable. One assertion over the real file,
# pure bash. Line breaks fold to spaces so that a wrapped sentence still counts.
adv="$(< "$REPO_ROOT/.claude/commands/advance-story.md")"
adv_after="${adv#*"Create and switch to the story's branch"}"
if [ "$adv_after" = "$adv" ]; then
  _bad "AC-7: advance-story.md says to commit the story while it is still PLANNED" \
    "anchor 'Create and switch to the story's branch' not found in .claude/commands/advance-story.md"
else
  adv_seg="${adv_after%%"Set the phase;"*}"
  adv_seg="${adv_seg//$'\r'/}"
  adv_seg="${adv_seg//$'\n'/ }"
  assert_contains "AC-7: advance-story.md says to commit the story while it is still PLANNED, before setting the phase" \
    'while it still says `phase: PLANNED`' "$adv_seg"
fi

git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" reset -q --hard "$crit_main_before" 2>/dev/null


# ---------------------------------------------------------------------------
describe "a BLOCKED gate can reach REVIEW, but only with the decision written down"

# H16's third state. A required gate that the environment would not launch has
# no verdict: it neither passed nor failed. The story may go to REVIEW with that
# gate pending CI, because CI is a different machine under a different policy -
# and it may not go to DONE until CI has actually run it. Before this, the
# recorded result had to start with "pass", so the path the loop now prescribes
# was one CI would have refused.
#
# The record has to be a real one: gates.sh writes the marker and the tree hash,
# and nothing else can. So the fixture runs it.
story_blocked() { # <phase> [required_gates] ; body on stdin
  local phase="$1" rg="${2:-}" extra; extra="$(cat)"
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
  git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
  write_conf "$FIX" <<'CONF'
gate     | unit  | required | . | printf 'Tests  47 passed (47)\n'
gate     | types | required | . | printf 'error: could not execute process (never executed)\n'; exit 101
evidence | unit  | Tests +[1-9][0-9]* passed
evidence | types | Tests +[1-9][0-9]* passed
CONF
  mkdir -p "$FIX/docs/backlog/stories"
  {
    printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: %s\nbranch: story/T-1-fixture\n' "$phase"
    [ -n "$rg" ] && printf -- 'required_gates: %s\n' "$rg"
    printf -- '---\n\n'
    printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n\n'
    printf -- '## Notes\n\n%s\n\n## Gate results\n\n' "$extra"
  } > "$FIX/docs/backlog/stories/T-1.md"
  # project.conf is code the gate hash covers, so it is committed BEFORE the run.
  commit_all "T-1 conf"
  ( cd "$FIX" && bash scripts/gates.sh --story T-1 >/dev/null 2>&1 )
  commit_all "T-1 $phase"
}

story_blocked REVIEW <<'EOF'
1. PO decision: the `types` gate is BLOCKED here, not failing - Smart App Control
   refuses the locally built binary by reputation (os error 4551), the branch does
   not touch it, and the same command passes elsewhere. Marking types pending CI.
EOF
run_boundaries
assert_contains "a blocked gate at REVIEW with the decision recorded" "recorded gate result: blocked" "$out"
assert_contains "and the gate is named as pending CI" "types" "$out"
# The EXIT STATUS, which is what "not refused" actually means and what CI acts
# on. The old form looked for one refusal message and would have accepted a run
# that refused this PR for any other reason - and nothing in this suite read the
# status at all, so `check-boundaries.sh` could have exited 1 through every case
# here without a single assertion noticing.
assert_eq "and it is not refused" 0 "$rc"

story_blocked REVIEW <<'EOF'
Ran the gates. One of them did not work on this machine.
EOF
run_boundaries
refused "a blocked gate with nothing written down is refused" "pending CI"

story_blocked DONE <<'EOF'
1. PO decision: types is BLOCKED locally by Smart App Control. Marking it
   pending CI.
EOF
run_boundaries
refused "DONE needs more than pending: it needs the CI run" "has not been verified on CI"

story_blocked DONE <<'EOF'
1. PO decision: types was BLOCKED locally by Smart App Control (os error 4551).
2. types passed on CI: https://github.com/o/r/actions/runs/412 - "Tests 47 passed".
EOF
run_boundaries
assert_contains "DONE with the CI run quoted is accepted" "ok    blocked gate 'types' was verified on CI" "$out"
assert_eq "and DONE with the CI run quoted exits 0, so CI would merge it" 0 "$rc"

# The distinction has to cut both ways: an ordinary failure is still refused.
story_blocked REVIEW <<'EOF'
1. types is pending CI.
EOF
write_conf "$FIX" <<'CONF'
gate     | unit  | required | . | printf 'Tests  47 passed (47)\n'
gate     | types | required | . | printf 'error TS2322: Type string is not assignable to number\n'; exit 2
evidence | unit  | Tests +[1-9][0-9]* passed
evidence | types | Tests +[1-9][0-9]* passed
CONF
commit_all "T-1 conf ordinary failure"
( cd "$FIX" && bash scripts/gates.sh --story T-1 >/dev/null 2>&1 )
commit_all "T-1 review failing"
run_boundaries
refused "a recorded failure is still refused" "recorded gate result is 'fail"


# ---------------------------------------------------------------------------
describe "a deferred verification is discharged or waived, never just filed"

# H8 and K6. Some verifications provably cannot run in the phase that wants
# them: RED cannot mutate an encoder that does not exist yet, so the negative
# control that gives a round-trip property its meaning has to be named at
# PLANNED and run later. That is the honest answer, and it was working - until
# you notice the commitment is PROSE, and prose does not fail a build. One
# story ran its deferred control because it had written the promise into its
# own report twice. Nothing else would have noticed.
story_on_branch <<'EOF'
## Deferred verifications

With one field dropped from the encoder, AC-1's property test must fail, and
the orchestrator should watch it fail rather than take the claim.
EOF
run_boundaries
refused "no phase owns it" "does not declare an owner"


# The owner has to be DECLARED, not merely mentioned. The first version grepped
# the whole block for any phase word, and the story template tells an author to
# write "why the phase that wants it cannot run it" - so the sentence the
# template asks for ("RED cannot run this") discharged the obligation with no
# owner named anywhere. A check satisfied by the boilerplate that prompts it is
# not a check. Found by the second mutation audit.
story_on_branch <<'EOF'
## Deferred verifications

With one field dropped from the encoder, AC-1's property test must fail. RED
cannot run this - there is no encoder to mutate yet.

```
 x round-trips an arbitrary world document
 Tests  1 failed | 44 passed (45)
```
EOF
run_boundaries
refused "a phase merely mentioned is not an owner" "does not declare an owner"

# Declared, in the form the template teaches.
story_on_branch <<'EOF'
## Deferred verifications

With one field dropped from the encoder, AC-1's property test must fail. RED
cannot run this - there is no encoder to mutate yet. **Owner: GATES.**

```
 x round-trips an arbitrary world document
 Tests  1 failed | 44 passed (45)
```
EOF
run_boundaries
assert_contains "an explicit Owner: satisfies it" "ok    ## Deferred verifications names the phase" "$out"
# Naming the phase is half of it. A block that names GATES and reaches the PR
# with nothing recorded is the failure K6 describes exactly: a commitment that
# outlived the phase that owed it.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. RED cannot run
   this - there is no encoder to mutate. Owner: GATES.
EOF
run_boundaries
refused "named, owned, and never run" "no result and no waiver"

# Discharged: the phase ran it and pasted what happened. Same predicate as
# ## Regressions and ## Gate probes, for the same reason - "we ran it" is not
# a result.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. RED could not run
   it - no encoder existed. Owner: GATES. Run there against the real encoder:

```
 x round-trips an arbitrary world document
   - relation.note: expected "worn" to be "undefined"
 Tests  1 failed | 44 passed (45)
```

   Reverted; `cmp` clean.
EOF
run_boundaries
assert_contains "run, with the failure shown" "ok    ## Deferred verifications carries its result" "$out"

# Waived: the story decided not to run it, in writing. A waiver is a decision
# somebody can argue with later, which is the whole difference between it and
# silence.
story_on_branch <<'EOF'
## Deferred verifications

1. Owner: GATES. WAIVED - the encoder this control mutates moved to WORLD-010
   with the criterion it belonged to, so there is nothing here to break.
EOF
run_boundaries
assert_contains "waived in writing" "ok    ## Deferred verifications carries an explicit waiver" "$out"

# And the section is optional: most stories defer nothing, and a story that
# omits it is not asked about it.
story_on_branch <<'EOF'
## Notes

Nothing deferred.
EOF
run_boundaries
case "$out" in
  *"Deferred verifications"*) _bad "silent when the section is absent" "said something about it: $out" ;;
  *) _ok "silent when the section is absent" ;;
esac

# HARNESS-037 AC-2. The issue #97 shape: owned, run, reported - in prose, with
# the restore lines in inline backticks. The check is right to refuse it (the
# audit's decision 6 D); the message has to say why, in the same words as 3g.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. Owner: GATES.
   Ran it at GATES; `mutate.sh` reported the failure and `cmp` confirmed the
   restore.
EOF
run_boundaries
refused "AC-2: a result reported in prose with inline backticks is refused" "## Deferred verifications has no result and no waiver"
whole_line "AC-2: the 3h refusal is exactly the line the contract gives, naming what counts" "$WANT_3H"

# HARNESS-037 AC-3 (d): "nor inline code" - the output itself quoted in inline
# backticks within a sentence, owned, no waiver. DV-2 flips it.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. Owner: GATES.
   The run printed `x round-trips an arbitrary world document` and then
   `Tests  1 failed | 44 passed (45)`, and the encoder was put back.
EOF
run_boundaries
refused "AC-3 (d): output quoted in inline backticks within prose is refused" "## Deferred verifications has no result and no waiver"
whole_line "AC-3 (d): and the refusal is AC-2's whole line" "$WANT_3H"

# ---------------------------------------------------------------------------
describe "a harness change bumps the stamp"

# The stamp only helps if it is current, and a stamp somebody has to remember
# to bump is a stamp that will be wrong exactly when it matters. So CI refuses
# a harness change that leaves it alone.
#
# The scoping is the careful part. This must NOT fire in a project built on the
# harness, where .claude/ is edited all the time - project.conf, paths.conf,
# .gitignore - by people who are not upstream and have nothing to stamp. Two
# conditions together: the branch is not a story branch (downstream work is,
# upstream harness rounds are not), and the repo has not been bootstrapped
# (which every real project does, and the template never does).
harness_branch() { # <file to touch> ... ; body of VERSION on stdin
  local ver; ver="$(cat)"
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D harness/thing >/dev/null 2>&1
  git -C "$FIX" checkout -q -b harness/thing 2>/dev/null
  [ -n "$ver" ] && printf '%s\n' "$ver" > "$FIX/.claude/harness/VERSION"
  commit_all "harness change"
}

# Baseline: main carries a stamp, and the fixture is the unbootstrapped
# template.
git -C "$FIX" checkout -q main 2>/dev/null
printf '2026-01-01\n' > "$FIX/.claude/harness/VERSION"
printf 'BOOTSTRAPPED=no\n' > "$FIX/.claude/harness/project.conf"
commit_all "baseline stamp"

printf 'touched by a harness change\n' >> "$FIX/.claude/hooks/lib.sh"
harness_branch </dev/null
run_boundaries
refused "a harness change with a stale stamp is refused" "does not bump"

printf 'touched again\n' >> "$FIX/.claude/hooks/lib.sh"
harness_branch <<'EOF'
2026-02-02
EOF
run_boundaries
assert_contains "bumping it satisfies the check" "ok    harness version bumped" "$out"

# Downstream safety, both halves. A bootstrapped project editing .claude/ on a
# non-story branch is not upstream and has nothing to stamp.
git -C "$FIX" checkout -q main 2>/dev/null
printf 'BOOTSTRAPPED=yes\n' > "$FIX/.claude/harness/project.conf"
commit_all "bootstrapped now"
printf 'a project edit\n' >> "$FIX/.claude/hooks/lib.sh"
harness_branch </dev/null
run_boundaries
case "$out" in
  *"does not bump"*) _bad "a bootstrapped project is not asked to bump" "it fired: $out" ;;
  *) _ok "a bootstrapped project is not asked to bump" ;;
esac

# And a change that touches no harness file is not asked either, bootstrapped
# or not: the stamp describes the harness, not the commit.
git -C "$FIX" checkout -q main 2>/dev/null
printf 'BOOTSTRAPPED=no\n' > "$FIX/.claude/harness/project.conf"
commit_all "unbootstrapped again"
printf 'just a document\n' >> "$FIX/docs/notes.md"
harness_branch </dev/null
run_boundaries
case "$out" in
  *"does not bump"*) _bad "a docs-only change is not asked to bump" "it fired: $out" ;;
  *) _ok "a docs-only change is not asked to bump" ;;
esac

# The other half of the scoping, and the half a mutation caught as untested.
# An unbootstrapped repo on a STORY branch is not a hypothetical: it is the
# bootstrap story of every new project, which touches .claude/ by definition -
# it writes project.conf. Without the story-branch guard this check refuses the
# first PR of every project generated from this template, and no case here
# noticed until the guard was deliberately removed and nothing went red.
git -C "$FIX" checkout -q main 2>/dev/null
printf 'BOOTSTRAPPED=no\n' > "$FIX/.claude/harness/project.conf"
commit_all "unbootstrapped, pre-bootstrap-story"
story_on_branch <<'EOF'
## Scaffold inventory

vite.config.ts - configuration, no behaviour
EOF
printf 'BOOTSTRAPPED=no\ngate | unit | required | . | printf x\n' > "$FIX/.claude/harness/project.conf"
commit_all "the bootstrap story configures the project"
run_boundaries
case "$out" in
  *"does not bump"*) _bad "a story branch is never asked to bump" "the bootstrap story would be refused: $out" ;;
  *) _ok "a story branch is never asked to bump" ;;
esac

# ---------------------------------------------------------------------------
describe "RED may add a test dependency, and only a test dependency"

# H22. RED now owns the manifest, because a failing test routinely needs a
# test-only dependency and every ecosystem declares that in the same file as the
# production dependencies. The permission is only safe if something reads what
# RED actually wrote - otherwise "RED may edit the manifest" is "RED may add a
# production dependency", and the phase that may not write production code gets
# to pull production code in from a registry instead.
#
# The lock cannot do this: it sees a path, not a diff. So the commit does.

# manifest_story <phase> <manifest> <content>   A branch whose FIRST commit
# carries the manifest change with the story in <phase>, and whose second moves
# the story to REVIEW so the PR itself is well formed. That shape matters: by
# the time CI sees a PR the story says REVIEW, so a check that only looked at
# the tip would never see a RED commit at all.
manifest_story() {
  local phase="$1" file="$2" body="$3"
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
  git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
  mkdir -p "$FIX/docs/backlog/stories"
  _story_file "$phase"
  printf '%s' "$body" > "$FIX/$file"
  commit_all "T-1 $phase manifest"
  _story_file REVIEW
  commit_all "T-1 to review"
}
_story_file() {
  {
    printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: %s\nbranch: story/T-1-fixture\n---\n\n' "$1"
    printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n'
  } > "$FIX/docs/backlog/stories/T-1.md"
}

# The baseline both branches diverge from.
git -C "$FIX" checkout -q main
cat > "$FIX/Cargo.toml" <<'TOML'
[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "1.0"

[dev-dependencies]
TOML
cat > "$FIX/package.json" <<'JSON'
{
  "name": "fixture",
  "dependencies": {
    "left-pad": "1.0.0"
  },
  "devDependencies": {
  }
}
JSON
cat > "$FIX/pyproject.toml" <<'TOML'
[project]
name = "fixture"
dependencies = ["httpx"]

[tool.ruff]
line-length = 100
TOML
commit_all "baseline manifests"

# --- the case the finding is about: a test-only dependency in RED -----------
manifest_story RED Cargo.toml '[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "1.0"

[dev-dependencies]
tempfile = "3"
'
run_boundaries
assert_contains "a dev-dependency added in RED is fine" "ok    RED touched only test dependencies" "$out"

manifest_story RED package.json '{
  "name": "fixture",
  "dependencies": {
    "left-pad": "1.0.0"
  },
  "devDependencies": {
    "@testing-library/dom": "10.0.0"
  }
}
'
run_boundaries
assert_contains "the same in package.json" "ok    RED touched only test dependencies" "$out"

# --- what the permission must not become -----------------------------------
manifest_story RED Cargo.toml '[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "1.0"
regex = "1"

[dev-dependencies]
'
run_boundaries
refused "a production dependency added in RED is refused" "outside the test-dependency block"
assert_contains "and the file is named" "Cargo.toml" "$out"

# A version bump is the same defect wearing a smaller costume: it changes what
# production code resolves to, from the phase that may not write production code.
manifest_story RED Cargo.toml '[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "2.0"

[dev-dependencies]
'
run_boundaries
refused "so is bumping an existing production dependency" "outside the test-dependency block"

manifest_story RED package.json '{
  "name": "fixture",
  "dependencies": {
    "left-pad": "1.0.0",
    "express": "4.0.0"
  },
  "devDependencies": {
  }
}
'
run_boundaries
refused "and a production dependency in package.json" "outside the test-dependency block"

# --- GREEN is not RED ------------------------------------------------------
# The asymmetry is deliberate and stays: GREEN's whole job is making the tests
# pass, and pulling in a library is a legitimate way to do it.
manifest_story GREEN Cargo.toml '[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "1.0"
regex = "1"

[dev-dependencies]
'
run_boundaries
case "$out" in
  *"outside the test-dependency block"*) _bad "GREEN may add a production dependency" "refused: $out" ;;
  *) _ok "GREEN may add a production dependency" ;;
esac

# --- the honest gap --------------------------------------------------------
# A lockfile has no dev/production split to read, so nothing here can verify
# one. It is permitted unchecked, which is sound only because the manifest it
# follows from IS checked: a dependency nobody declared cannot be used.
#
# The real shape of that commit is BOTH files - you add a dev-dependency and the
# lockfile moves with it - and that is what makes a positive assertion possible.
# Asserting the ABSENCE of one message was satisfied by a lockfile refused with
# a DIFFERENT one: dropping `*.lock` from the skip sent Cargo.lock to a parser
# that has no rule for it, refused it as `__UNPARSEABLE__`, and left all 52
# assertions green. The count is the load-bearing half - `1`, not `2`, is what
# says the lockfile was skipped rather than merely tolerated.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
_story_file RED
printf '%s' '[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "1.0"

[dev-dependencies]
tempfile = "3"
' > "$FIX/Cargo.toml"
printf '%s' 'version = 3

[[package]]
name = "tempfile"
version = "3.10.1"
' > "$FIX/Cargo.lock"
commit_all "T-1 RED dev-dependency, and the lockfile that follows it"
_story_file REVIEW
commit_all "T-1 to review"
run_boundaries
assert_contains "a lockfile is permitted unchecked" \
  "ok    RED touched only test dependencies (1 manifest change(s))" "$out"

# --- every shape of dev block the parser claims to know ---------------------
#
# The cases above pin exactly two ecosystems' happy paths: one plain
# `[dev-dependencies]` and one flat `devDependencies`. Everything else
# manifest_strip_dev recognises was unasserted, so four separate narrowings of
# it survived the whole suite - and each one turns a LEGITIMATE dev-dependency
# into `changed '<file>' outside the test-dependency block`, in the phase least
# able to argue with the refusal. A false positive here is worse than a false
# negative: it is the exact condition under which an agent meets a refusal with
# no sanctioned next step and invents one.
#
# Each positive below is followed by the control that stops an over-broad fix
# from passing it. "Treat any [target.*] section as dev" satisfies the first
# assertion and fails the second.


# Cargo: a platform-gated test dependency is still a test dependency.
manifest_story RED Cargo.toml '[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "1.0"

[dev-dependencies]

[target.'"'"'cfg(unix)'"'"'.dev-dependencies]
nix = "0.27"
'
run_boundaries; accepts_manifest "a target-specific dev-dependency is a dev-dependency"

manifest_story RED Cargo.toml '[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "1.0"

[dev-dependencies]

[target.'"'"'cfg(unix)'"'"'.dependencies]
nix = "0.27"
'
run_boundaries; refused "but a target-specific PRODUCTION dependency is not" "outside the test-dependency block"

# PEP 735. The block a modern Python project actually puts its test deps in.
manifest_story RED pyproject.toml '[project]
name = "fixture"
dependencies = ["httpx"]

[dependency-groups]
test = ["pytest"]

[tool.ruff]
line-length = 100
'
run_boundaries; accepts_manifest "a PEP 735 dependency group is a dev block"

# poetry, which the same file may use instead.
manifest_story RED pyproject.toml '[project]
name = "fixture"
dependencies = ["httpx"]

[tool.poetry.group.dev.dependencies]
pytest = "^8"

[tool.ruff]
line-length = 100
'
run_boundaries; accepts_manifest "so is a poetry dev group"

# The control that keeps the TOML rule honest, and the one the code comment
# already argues for: an extra is not a test dependency. It can be a production
# extra, and the safe error is a refusal RED can escalate.
manifest_story RED pyproject.toml '[project]
name = "fixture"
dependencies = ["httpx"]

[project.optional-dependencies]
pdf = ["reportlab"]

[tool.ruff]
line-length = 100
'
run_boundaries; refused "an optional-dependencies extra is NOT a dev block" "outside the test-dependency block"

# --- JSON: the block ends at ITS closing brace, not the first one -----------
# A nested object inside devDependencies is ordinary, and the depth counter is
# the only thing keeping it from ending the block early. Both sides need the
# same shape, so the baseline moves - with production AFTER the dev block,
# which is what makes the control below able to fail.
git -C "$FIX" checkout -q main
cat > "$FIX/package.json" <<'JSON'
{
  "name": "fixture",
  "devDependencies": {
    "jest": "29.0.0",
    "c8": { "reporter": ["text"], "exclude": ["dist/**"] }
  },
  "dependencies": {
    "left-pad": "1.0.0"
  }
}
JSON
commit_all "a nested dev block, with production after it"

manifest_story RED package.json '{
  "name": "fixture",
  "devDependencies": {
    "jest": "29.0.0",
    "c8": { "reporter": ["text"], "exclude": ["dist/**"] },
    "msw": "2.0.0"
  },
  "dependencies": {
    "left-pad": "1.0.0"
  }
}
'
run_boundaries; accepts_manifest "a nested object does not end the dev block early"

# THE control. An exit condition that swallows the rest of the file passes the
# assertion above and makes every production change after a dev block invisible.
manifest_story RED package.json '{
  "name": "fixture",
  "devDependencies": {
    "jest": "29.0.0",
    "c8": { "reporter": ["text"], "exclude": ["dist/**"] }
  },
  "dependencies": {
    "left-pad": "2.0.0"
  }
}
'
run_boundaries; refused "and production AFTER the dev block is still read" "outside the test-dependency block"

# --- punctuation is not a dependency ---------------------------------------
# Adding a dev block where none existed leaves a trailing comma behind on one
# side only, and a blank separator that has no counterpart. Both are the edit's
# punctuation, not its content. A check that calls either a production change
# is a check people route around - which is the whole argument for manifest_norm
# and, until now, the only place that argument was written down.
git -C "$FIX" checkout -q main
cat > "$FIX/package.json" <<'JSON'
{
  "name": "fixture",
  "dependencies": {
    "left-pad": "1.0.0"
  }
}
JSON
commit_all "a manifest with no dev block at all"

manifest_story RED package.json '{
  "name": "fixture",
  "dependencies": {
    "left-pad": "1.0.0"
  },
  "devDependencies": {
    "jest": "29.0.0"
  }
}
'
run_boundaries; accepts_manifest "a first dev block, and the comma it leaves behind"

manifest_story RED package.json '{
  "name": "fixture",
  "dependencies": {
    "left-pad": "1.0.0"
  },

  "devDependencies": {
    "jest": "29.0.0"
  }
}
'
run_boundaries; accepts_manifest "and the blank line somebody put between them"

# ---------------------------------------------------------------------------
describe "the story is found by what claims the branch, not by the branch's name"

# Every check from 3b onward is gated behind knowing WHICH story this is, and
# that was read out of the branch name with ^story/. A real project names two of
# its three story types differently - bug/world-storage-megabyte-timeout,
# chore/tauri-capability-acl-guard - and those names carry no story id at all,
# so the id came back empty and the script exited before a single story check
# ran. The PR went green in four seconds having verified nothing: the phase, the
# frozen criteria, the gate record against the tree, the handoff, all skipped.
#
# Loosening the pattern cannot fix it, because there is no id in the name to
# find. The lookup has to be inverted: ask which story CLAIMS this branch. That
# datum already exists and is already enforced - phase.sh refuses to start a
# story whose frontmatter branch is not the checkout.

# story_claiming <branch> <phase> [id]
story_claiming() {
  local br="$1" phase="$2" id="${3:-T-1}"
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D "$br" >/dev/null 2>&1
  git -C "$FIX" checkout -q -b "$br" 2>/dev/null
  mkdir -p "$FIX/docs/backlog/stories"
  {
    printf -- '---\nid: %s\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: %s\nbranch: %s\n---\n\n' "$id" "$phase" "$br"
    printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n'
  } > "$FIX/docs/backlog/stories/$id.md"
  commit_all "$id on $br"
}

# A bug/ branch, deliberately left in GATES: if the story is found, the
# open-a-PR-from-REVIEW check fires. That it fires is the whole assertion - it
# is proof the eight gated checks are running at all.
story_claiming bug/world-storage-megabyte-timeout GATES
run_boundaries
assert_contains "a bug/ branch is matched to its story" "story T-1 is in phase 'GATES'" "$out"

story_claiming chore/tauri-capability-acl-guard GATES
run_boundaries
assert_contains "so is a chore/ branch" "story T-1 is in phase 'GATES'" "$out"

# The old form keeps working, and keeps working by the fast path rather than by
# accident: this one's frontmatter names the branch too, as every story's does.
story_claiming story/T-1-fixture GATES
run_boundaries
assert_contains "story/ still resolves" "story T-1 is in phase 'GATES'" "$out"

# A branch no story claims is not an error - a harness PR is exactly that - but
# it must SAY so. Exiting in silence is how eight skipped checks looked like
# eight passing ones for six stories.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" branch -D harness/some-fix >/dev/null 2>&1
git -C "$FIX" checkout -q -b harness/some-fix 2>/dev/null
printf 'x\n' > "$FIX/docs/notes.md"; commit_all "a harness change"
run_boundaries
assert_contains "an unclaimed branch says so" "no story claims branch" "$out"

# Two stories claiming one branch is ambiguous, and picking one silently is the
# same defect in a smaller costume.
story_claiming bug/shared-branch GATES T-1
{
  printf -- '---\nid: T-2\ntitle: Second\nslug: second\ntype: feature\nstatus: todo\nphase: GATES\nbranch: bug/shared-branch\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n'
} > "$FIX/docs/backlog/stories/T-2.md"
commit_all "a second story claiming the same branch"
run_boundaries
refused "two claimants is a problem, not a coin flip" "claimed by more than one story"
rm -f "$FIX/docs/backlog/stories/T-2.md"

# The story/ fast path is not redundant with the lookup, and a mutation proved
# the suite could not tell: disabling the pattern left all assertions green.
# What it is FOR is the case where the frontmatter is wrong - a story/<ID>
# branch whose `branch:` field names something else. The lookup cannot match
# that, and without the fast path the story goes unidentified and every check
# below is skipped with a note, when what the author needs is the mismatch
# reported as the problem it is.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" branch -D story/T-1-renamed >/dev/null 2>&1
git -C "$FIX" checkout -q -b story/T-1-renamed 2>/dev/null
{
  printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-the-old-name\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n'
} > "$FIX/docs/backlog/stories/T-1.md"
commit_all "T-1 on a branch its frontmatter does not name"
run_boundaries
assert_contains "a story/ branch with stale frontmatter is still identified" \
  "frontmatter says branch" "$out"
case "$out" in
  *"no story claims branch"*) _bad "and is not written off as unclaimed" "it was skipped: $out" ;;
  *) _ok "and is not written off as unclaimed" ;;
esac

# ---------------------------------------------------------------------------
describe "a story is located by its filename, so the id inside must agree"

# phase.sh, gates.sh and this script all find a story by filename and then read
# its frontmatter. A disagreement between the two points three tools at
# different things and none of them says a word; check 1 is the only place that
# can notice. It had no fixture at all, so relaxing it to `[ -n "$fid" ]` - any
# non-empty id will do - changed nothing any assertion read.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
mkdir -p "$FIX/docs/backlog/stories"
{
  printf -- '---\nid: T-9\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n'
} > "$FIX/docs/backlog/stories/T-1.md"
commit_all "a story whose id does not match its filename"
run_boundaries
refused "an id that disagrees with the filename" \
  "frontmatter id 'T-9' does not match filename 'T-1'"

# ---------------------------------------------------------------------------
describe "the handoff is the only channel to the next agent"

# A subagent starts with empty context, so an empty ## Handoff ends the phase
# having handed over nothing - "as discussed above" does not survive the
# boundary. The rule is scoped to feature and fix stories, and nothing pinned
# that scope: renaming the case labels to a type no story has, which switches
# the rule off entirely, left every assertion green.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
{
  printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\n'
  printf -- '<!-- REQUIRED. The command that fails, its output, and the shape the\n     next agent has to build against. -->\n'
} > "$FIX/docs/backlog/stories/T-1.md"
commit_all "a story whose handoff was never written"
run_boundaries
refused "a feature story with a template-only handoff" "## Handoff is empty"

# ---------------------------------------------------------------------------
describe "a gate the story escalated for itself appears in the record"

# gates.sh enforces required_gates while it runs; this catches the record
# written BEFORE the escalation was added, where the gate is optional again by
# the time anyone looks. No fixture ever set required_gates, so the loop body
# never executed once - and a loop that never runs cannot be broken by anything
# done to its condition.
story_blocked REVIEW '[types]' <<'EOF'
1. PO decision: the `types` gate is BLOCKED here, not failing - Smart App Control
   refuses the locally built binary by reputation (os error 4551), the branch does
   not touch it, and the same command passes elsewhere. Marking types pending CI.
EOF
run_boundaries
refused "a required gate the record has no PASS for" \
  "frontmatter requires gate 'types', but the recorded run has no PASS for it"

# The other direction, and this fixture IS clean, so it asserts the exit status
# rather than the absence of a message.
story_blocked REVIEW '[unit]' <<'EOF'
1. PO decision: the `types` gate is BLOCKED here, not failing - Smart App Control
   refuses the locally built binary by reputation (os error 4551), the branch does
   not touch it, and the same command passes elsewhere. Marking types pending CI.
EOF
run_boundaries
assert_contains "one that did pass is reported as passing" \
  "ok    story-required gate 'unit' passed in the recorded run" "$out"
assert_eq "and the run is clean" 0 "$rc"

# ---------------------------------------------------------------------------
describe "machine-local state is never committed"

# current-story.env carries the phase the guard reads. Committing it publishes
# one machine's idea of which story is active to everyone who checks the branch
# out. rules.md says it must never happen - and the check had no fixture, so
# inverting its condition, to fire only when the file is ABSENT, was invisible.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" branch -D harness/committed-state >/dev/null 2>&1
git -C "$FIX" checkout -q -b harness/committed-state 2>/dev/null
mkdir -p "$FIX/.claude/state"
printf 'STORY_ID=T-1\nPHASE=GREEN\n' > "$FIX/.claude/state/current-story.env"
git -C "$FIX" add -f .claude/state/current-story.env >/dev/null 2>&1
commit_all "somebody committed the lock file"
run_boundaries
refused "a committed current-story.env is refused" "is tracked; it is machine-local state"
# And it does not say the opposite in the same breath. The `ok` sat OUTSIDE the
# `if`, so the one repository this rule exists for was told both at once.
case "$out" in
  *"ok    harness state not tracked"*)
    _bad "and does not also report it clean" "both, in one run: $out" ;;
  *) _ok "and does not also report it clean" ;;
esac

# ---------------------------------------------------------------------------
describe "a section is not empty because it was too big to read"

# Reported from a consuming project, reproduced here before being fixed:
#
#   strip_comments | grep -q '[^[:space:]]'
#
# `strip_comments` is an awk that buffers the whole input and writes it in ONE
# printf at END. `grep -q` exits at its first match, the writer dies of SIGPIPE,
# and `set -uo pipefail` promotes 141 to the pipeline's status - so the predicate
# returns FALSE for a section that plainly has content. Measured on this machine:
# 1,000 and 50,000 bytes exit 0; 200,000 and 1,500,000 exit 141.
#
# It fails CLOSED, which is the better direction, but it refuses a good PR and it
# strikes exactly the stories that wrote the most. And the threshold is a RACE on
# the pipe buffer rather than a constant: the same shape passed on Windows and
# failed on ubuntu-latest in the reporting project.
#
# 1.5 MiB rather than the ~200 KB that reproduces here, because the buffer size
# is what varies between machines and this test must fail on the defect wherever
# it runs.
#
# ONE awk, not `yes ... | head -c`. `head -c` leaves at its byte limit, the
# `yes` behind it dies of SIGPIPE, and `set -uo pipefail` promotes 141 to the
# status of the pipeline that IS this function's body - so big_section itself
# returns false, in a suite written to catch exactly that shape. Same bytes
# (31,457 whole lines plus the first 14 of the next), one process, no pipe.
# WORLD-086 R-1.
big_section() {
  awk 'BEGIN { l = "the handoff says what the next agent needs to know\n"
               n = 1572864
               while (n >= length(l)) { printf "%s", l; n -= length(l) }
               if (n > 0) printf "%s", substr(l, 1, n) }' < /dev/null
}

git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
{
  printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\n'
  big_section; printf '\n'
} > "$FIX/docs/backlog/stories/T-1.md"
commit_all "a story whose handoff is enormous"
run_boundaries
case "$out" in
  *"## Handoff is empty"*)
    _bad "a 1.5 MiB handoff is not reported empty" "it was called empty: the predicate died of SIGPIPE" ;;
  *) _ok "a 1.5 MiB handoff is not reported empty" ;;
esac

# THE CONTROL. Without it, a predicate rewritten to answer "yes" unconditionally
# passes the assertion above, and the rule stops being a rule.
{
  printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\n'
  printf -- '<!-- REQUIRED. Still not written. -->\n'
} > "$FIX/docs/backlog/stories/T-1.md"
commit_all "and one whose handoff is still the template"
run_boundaries
refused "while a template-only one still is" "## Handoff is empty"

# The same shape guards ## Regressions, where the question is whether the
# section SHOWS its failure rather than merely describing one. A fenced block a
# megabyte in is still a fenced block.
{
  printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n\n'
  printf -- '## Regressions\n\nCorrected the AC-2 assertion. Probed by mutation:\n\n```\n'
  big_section; printf '\n x the assertion fails against the mutant\n```\n'
} > "$FIX/docs/backlog/stories/T-1.md"
commit_all "a regressions section with a very large fenced block"
run_boundaries
# ASSERTED ON THE `ok` LINE, not on the absence of the complaint. When
# has_content dies of SIGPIPE the section reads as ABSENT, and an absent
# ## Regressions is not a complaint - so "the complaint is missing" was true
# for a reason that had nothing to do with the fence being found. That version
# of this assertion passed against the defect it was written for.
assert_contains "a fenced block a megabyte in is still shown" \
  "ok    ## Regressions carries pasted output" "$out"

# THE FOURTH INSTANCE, and the one that proves the point about not fixing this
# by dropping `pipefail`. It is not one of the two named helpers - it is an
# inline `printf | strip_comments | grep -qiE` looking for the owner of a
# deferred verification, with the same buffering writer and the same
# early-exiting reader. Fixing only `has_content` and `has_pasted_output` would
# have left a large ## Deferred verifications refused for naming no owner while
# naming one in its first line.
{
  printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n\n'
  printf -- '## Deferred requirements placeholder\n\n'
  printf -- '## Deferred verifications\n\nAC-2 cannot run until the renderer exists. Owner: GATES\n\nResult, run at GATES:\n\n```\n x the property fails against the lossy encoder\n```\n\n'
  big_section; printf '\n'
} > "$FIX/docs/backlog/stories/T-1.md"
commit_all "a very large deferred-verifications section that names its owner"
run_boundaries
assert_contains "an owner named a megabyte from the end is still found" \
  "ok    ## Deferred verifications names the phase that owns each entry" "$out"

# ---------------------------------------------------------------------------
describe "the gate record is a stamp on a tree, not a sentence about one"

# Law 3: the record carries a hash of the code the gates ran against, and this
# script refuses a PR where that hash does not describe the code being merged.
# Nothing observed any part of that. Deleting the comparison outright -
# `[ "$rec" = "$now" ]` replaced by `true` - passed 59 of 59, because no fixture
# ever produced a mismatch for it to miss.
#
# Writing a CONSTANT stamp is already caught, by the exit-status assertions
# added for the story checks: a stamp that describes no tree makes the clean
# fixture refuse, and something finally reads the status. That is the opposite
# direction from this one. A broken comparison makes runs more PERMISSIVE, and
# nothing permissive is visible without an input that ought to have been
# refused.
GATE_STORY_NOTE='1. PO decision: the `types` gate is BLOCKED here, not failing - Smart App Control
   refuses the locally built binary by reputation (os error 4551), the branch does
   not touch it, and the same command passes elsewhere. Marking types pending CI.'

printf '%s\n' "$GATE_STORY_NOTE" | story_blocked REVIEW
run_boundaries
assert_contains "a record made against this tree matches it" \
  "ok    gate record matches the working tree" "$out"
assert_eq "and a record matching this tree leaves the run clean" 0 "$rc"

# End to end, and the direct form of "the stamp is a real hash": what gates.sh
# wrote equals gate_tree_hash computed independently over the same tree. The
# assertion above would also fail against a constant, but only as a side effect
# of the constant happening not to match - this one says what is actually
# claimed.
rec_tree="$(sed -nE 's/^[[:space:]]*tree:[[:space:]]*([0-9a-f]+).*/\1/p' \
  "$FIX/docs/backlog/stories/T-1.md" | head -1)"
live_tree="$( cd "$FIX" && CLAUDE_PROJECT_DIR="$FIX" bash -c \
  '. .claude/hooks/lib.sh; gate_tree_hash' 2>/dev/null )"
assert_eq "and the stamp gates.sh wrote IS that hash" "$live_tree" "$rec_tree"

# Source moved after the run. The test moves with it, so that section 3a is
# satisfied and the only thing left to refuse this PR is the stamp.
printf 'export const x = 2\n'                       > "$FIX/src/main.ts"
printf 'test("x", () => {})\n// and one more\n'     > "$FIX/tests/main.test.ts"
commit_all "code changed after the gates ran"
run_boundaries
refused "a stamp describing a different tree is refused" "gates were recorded against tree"

# And a TEST changing is enough on its own. The hash covers test files because a
# suite edited after the last full run is exactly the case law 3 exists for -
# the gates passed against code nobody is merging. Dropping `test` from the
# gated set left the stamp matching, and passed all 14 suites.
printf '%s\n' "$GATE_STORY_NOTE" | story_blocked REVIEW
printf 'test("x", () => {})\n// a case added after the run\n' > "$FIX/tests/main.test.ts"
commit_all "only a test changed after the gates ran"
run_boundaries
refused "a test changing alone breaks the stamp too" "gates were recorded against tree"

# ---------------------------------------------------------------------------
describe "the local verdict and CI's verdict agree about an untracked file (HARNESS-014, AC-2)"

# CI recomputes the stamp from the PR head COMMIT (PR_HEAD_SHA set), which holds
# no untracked file. The local run recomputed it from the working tree with
# `git add -A`, which folded every untracked gated file in. So a record made
# against a clean tree was refused locally the moment a stray .patch appeared,
# while CI accepted the same commit - and HARNESS-012 and -013 ran this script in
# a throwaway worktree to get an answer they could trust. After HARNESS-014 the
# working-tree hash is the tree `git commit -a` would make, and the two agree.
run_boundaries_at_head() { # sets $out and $rc, with PR_HEAD_SHA at HEAD, as CI and ci-local.sh do
  out="$( cd "$FIX" && GITHUB_HEAD_REF= PR_HEAD_SHA="$(git rev-parse HEAD)" bash scripts/check-boundaries.sh main 2>&1 )"
  rc=$?
}

printf '%s\n' "$GATE_STORY_NOTE" | story_blocked REVIEW      # record made by gates.sh, tree fully committed
mkdir -p "$FIX/handoff"
printf 'diff --git a/x b/x\n' > "$FIX/handoff/x.patch"         # untracked; classifies source, as the specimen does
run_boundaries
assert_contains "AC-2: an untracked gated file does not spoil the local verdict" \
  "ok    gate record matches the working tree" "$out"
assert_eq "AC-2: and the local run exits 0" 0 "$rc"
run_boundaries_at_head
assert_contains "AC-2: CI's verdict on the same commit is the same" \
  "ok    gate record matches commit" "$out"
assert_eq "AC-2: and CI's run exits 0" 0 "$rc"

# Control: a COMMITTED change to a tracked source file is refused by both, with
# the same message. The test moves with it so that only the stamp is left to
# refuse. Without this, "always say the record matches" passes AC-2.
printf 'export const x = 4\n'                       > "$FIX/src/main.ts"
printf 'test("x", () => {})\n// and one more\n'     > "$FIX/tests/main.test.ts"
commit_all "source changed after the gates ran, stray still present"
run_boundaries
refused "AC-2 control: a committed source change is refused locally" "gates were recorded against tree"
run_boundaries_at_head
refused "AC-2 control: and refused by CI's computation too" "gates were recorded against tree"
# The stray was swept into that commit by commit_all's `add -A`. Take it out of
# the tree so that no later block inherits a source file none of them wrote.
git -C "$FIX" rm -q -r --cached handoff >/dev/null 2>&1
rm -rf "$FIX/handoff"
commit_all "stray removed"

# ---------------------------------------------------------------------------
describe "production code arrives with tests, or with an inventory"

# Law 1, at the commit. Replacing the condition with `false` sends every PR down
# the else branch, where it prints
#   ok    source changes accompanied by test changes (3 source, 0 test)
# which is the line a CORRECT pr gets. The rule off, and reporting a pass in the
# same breath - the same shape as the `harness state not tracked` defect, and
# 59 of 59 green. No fixture changed source without changing tests.

story_on_branch <<'EOF'
## Notes

One clean cycle.
EOF
printf 'export const x = 99\n' > "$FIX/src/main.ts"
commit_all "source with no test"
run_boundaries
refused "a feature story whose source moved alone" \
  "Production code ships with the test that demanded it"

# The control. Without it, "refuse every diff that touches source" passes the
# assertion above, and the else branch - the one that prints the reassuring
# line - is never shown to be reachable for the right reason.
story_on_branch <<'EOF'
## Notes

One clean cycle.
EOF
printf 'export const x = 100\n'                      > "$FIX/src/main.ts"
printf 'test("x", () => {})\n// covering it\n'       > "$FIX/tests/main.test.ts"
commit_all "source with the test that demanded it"
run_boundaries
assert_contains "but source WITH a test is accepted" \
  "ok    source changes accompanied by test changes" "$out"

# scaffold_story <type>   A story of <type> at REVIEW whose ## Scaffold
# inventory is whatever arrives on stdin. The bootstrap exception is the only
# way source may arrive without tests, and it is not free: every production file
# written has to be named.
scaffold_story() {
  local t="$1" inv; inv="$(cat)"
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
  git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
  mkdir -p "$FIX/docs/backlog/stories"
  {
    printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: %s\nstatus: todo\nphase: REVIEW\nbranch: story/T-1-fixture\n---\n\n' "$t"
    printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n\n'
    printf -- '## Scaffold inventory\n\n%s\n' "$inv"
  } > "$FIX/docs/backlog/stories/T-1.md"
}

# Template-only is empty: the template is mostly comments, and a story that
# never filled it in has claimed nothing.
scaffold_story chore <<'EOF'
<!-- REQUIRED for a bootstrap or chore story that writes production code: every
     file written, and the test that covers it. -->
EOF
printf 'export const x = 1\nexport const y = 2\n' > "$FIX/src/main.ts"
commit_all "a chore that writes source and lists nothing"
run_boundaries
refused "a chore with a template-only inventory" "## Scaffold inventory is empty"

# Named, but not all of them. The per-file check is what makes the inventory an
# inventory rather than a paragraph.
scaffold_story chore <<'EOF'
src/main.ts - the entry point, covered by tests/main.test.ts
EOF
printf 'export const x = 1\n'      > "$FIX/src/main.ts"
printf 'export const helper = 1\n' > "$FIX/src/helper.ts"
commit_all "a chore that writes two files and lists one"
run_boundaries
refused "a source file missing from the inventory" "not named in ## Scaffold inventory:"
assert_contains "and the refusal names the file it missed" "src/helper.ts" "$out"

# The control for both of the above: an inventory that does account for
# everything is accepted, so neither is satisfied by a check that refuses every
# scaffold story it sees.
scaffold_story chore <<'EOF'
src/main.ts   - the entry point, covered by tests/main.test.ts
src/helper.ts - the helper it calls, covered by tests/main.test.ts
EOF
printf 'export const x = 1\n'      > "$FIX/src/main.ts"
printf 'export const helper = 1\n' > "$FIX/src/helper.ts"
commit_all "a chore that lists everything it wrote"
run_boundaries
assert_contains "an inventory naming every file is accepted" \
  "ok    every changed source file is named in ## Scaffold inventory" "$out"

# ---------------------------------------------------------------------------
describe "a story that predates touches: is still accepted (HARNESS-006, AC-5 control)"

# HARNESS-006 added `touches:` to the story template and to what
# `plan.sh conflicts` reads. It is a NEW field: every story already in a
# backlog lacks it, and a required-key check that grew a sixth key would make
# the whole backlog unmergeable in one release. So a story with no `touches:`
# key raises nothing about it. story_on_branch writes exactly such a story.
#
# PASSES ON ARRIVAL: nothing refuses the key's absence today, so this assertion
# has never been watched to fail. It is earned in GATES, per the story's
# `## Deferred verifications`, by adding `touches` to check-boundaries.sh's
# required-key loop (`for key in id title type status phase`) through
# scripts/mutate.sh and watching THIS assertion go red - the refusal that
# mutation prints is `frontmatter missing 'touches'`, which the needle below
# matches. The needle is the bare word so that any other spelling of a refusal
# about the key is caught too; the check's output names no other "touches".
story_on_branch <<'EOF'
## Notes

Written before the field existed.
EOF
run_boundaries
assert_not_contains "a story with no touches: key is not refused for lacking one" \
  "touches" "$out"

summary "boundaries"
