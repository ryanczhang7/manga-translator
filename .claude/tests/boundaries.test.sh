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

# story_on_branch [type] [extra-frontmatter-line] [phase]   Writes
# docs/backlog/stories/T-1.md on a fresh story branch cut from main, with the
# body on stdin appended after the frontmatter. Defaults: type feature, no extra
# line, phase REVIEW - which writes the same bytes the argument-free form always
# wrote, so every call site that passes nothing is unchanged (HARNESS-054). The
# phase argument is HARNESS-062's: a rule that runs at REVIEW|DONE needs a DONE
# fixture, or dropping DONE from its case label survives (audit mutant B07).
story_on_branch() {
  local type="${1:-feature}" extra="${2:-}" phase="${3:-REVIEW}"
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
  git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
  mkdir -p "$FIX/docs/backlog/stories"
  {
    printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: %s\nstatus: todo\nphase: %s\nbranch: story/T-1-fixture\n' "$type" "$phase"
    [ -n "$extra" ] && printf -- '%s\n' "$extra"
    printf -- '---\n\n'
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
describe "a story copy of any size gets its criteria line (HARNESS-089)"

# The FWB field case: on Git for Windows (bash 5.3.15, cygwin) a here-string
# whose payload falls in a narrow window just above 64 KiB blocks forever, and
# criteria_baseline fed every committed story copy through one. A story whose
# first non-PLANNED copy was 65,566 bytes hung check-boundaries.sh for five
# hours. Measured on that shell, 2026-11-05: payloads up to 65,535 return,
# 65,536 to 65,566 block, 66,000 to 140,000 return. `$(git show)` strips the
# file's trailing newline and the here-string appends one, so a 65,566-byte
# FILE is a 65,566-byte write: inside the window. On Linux nothing here hangs,
# so a green Linux run says nothing about the fix; the window is this host's.
#
# Three histories, one shape - PLANNED small, RED, GREEN - built with the
# HARNESS-033 helpers. Only the RED copy's size differs: small, exactly 65,566
# bytes, and 135,000 bytes (outside the window today: it pins that size does
# not matter at all, not merely that one size was fixed). Each run is under
# `timeout 120`, because the defect is a hang and a hung suite holds the run
# lock. The oversized histories must print what the small one prints: the same
# status and the same criteria line, with their own PLANNED commit's c7.

# crit_pad <id> <bytes>   Appends a ## Notes section of fixed-width lines to
# the working-tree story so the FILE is exactly <bytes> long: 64-byte lines,
# then one short line for the remainder. One awk, no loop in bash.
crit_pad() {
  local f="$FIX/docs/backlog/stories/$1.md" have
  printf '\n## Notes\n\n' >> "$f"
  have="$(wc -c < "$f")"; have="${have//[[:space:]]/}"
  awk -v r="$(( $2 - have ))" 'BEGIN {
    w = "padding line: fixed width, so the file size is exact. ";
    while (length(w) < 63) w = w "x";
    w = substr(w, 1, 63);
    for (i = 0; i < int(r / 64); i++) print w;
    if (r % 64 > 0) print substr(w, 1, r % 64 - 1);
  }' >> "$f"
}
# crit_size_history <id> <bytes>   PLANNED small, then RED and GREEN padded to
# <bytes> (0: no padding). Sets $p7 to the PLANNED commit's c7, and $red_size
# and $red_blob to the RED copy's size on disk and as committed.
crit_size_history() {
  crit_branch "$1"
  crit_commit "$1" PLANNED "criteria v1"; p7="$c7"
  crit_write "$1" RED "criteria v1"
  [ "$2" -gt 0 ] && crit_pad "$1" "$2"
  red_size="$(wc -c < "$FIX/docs/backlog/stories/$1.md")"; red_size="${red_size//[[:space:]]/}"
  commit_all "$1 at RED"
  red_blob="$(git -C "$FIX" cat-file -s "HEAD:docs/backlog/stories/$1.md" 2>/dev/null)"
  crit_write "$1" GREEN "criteria v1"
  [ "$2" -gt 0 ] && crit_pad "$1" "$2"
  commit_all "$1 at GREEN"
}
# run_boundaries_against_timed <base-ref>   run_boundaries_against under
# `timeout 120`. Sets $out and $rc; a hang is rc 124 with whatever was printed
# before it.
run_boundaries_against_timed() {
  out="$( cd "$FIX" && GITHUB_HEAD_REF= PR_HEAD_SHA= timeout 120 bash scripts/check-boundaries.sh "$1" 2>&1 )"
  rc=$?
}

# The small twin: the reference every oversized history is compared with.
crit_size_history T-40 0
run_boundaries_against_timed main
small_rc="$rc"
assert_eq "AC-1: the small-copy history is not killed by the timeout (status 124)" \
  no "$([ "$rc" -eq 124 ] && echo "yes, status 124" || echo no)"
whole_line "AC-1: the small-copy history reports its criteria unchanged since its PLANNED commit" \
  "ok    acceptance criteria unchanged since the last committed PLANNED state ($p7)"

for crit_bytes in 65566 135000; do
  crit_id="T-41"; [ "$crit_bytes" = 135000 ] && crit_id="T-42"
  crit_size_history "$crit_id" "$crit_bytes"
  assert_eq "AC-1 precondition: the RED copy is exactly $crit_bytes bytes on disk" "$crit_bytes" "$red_size"
  assert_eq "AC-1 precondition: the RED copy is exactly $crit_bytes bytes as committed" "$crit_bytes" "$red_blob"
  run_boundaries_against_timed main
  assert_eq "AC-1: a $crit_bytes-byte RED copy does not hang check-boundaries.sh (status 124 under timeout 120)" \
    no "$([ "$rc" -eq 124 ] && echo "yes, status 124" || echo no)"
  assert_eq "AC-1: a $crit_bytes-byte RED copy exits with the small-copy history's status" "$small_rc" "$rc"
  whole_line "AC-1: a $crit_bytes-byte RED copy reports the same criteria line as the small-copy history" \
    "ok    acceptance criteria unchanged since the last committed PLANNED state ($p7)"
done

git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" reset -q --hard "$crit_main_before" 2>/dev/null


# ---------------------------------------------------------------------------
describe "no here-string carries a story copy or a git show result (HARNESS-089)"

# The rule AC-2 states, mechanically, over any script: for each line holding
# `<<<`, every `$name` or `${name` token in the text after `<<<` names a
# variable, and the line is refused if any assignment to that variable
# anywhere in the script (`name=$(` or `name="$(`) opens with `git show`,
# `git cat-file`, `cat ` or `<` (the `$(< file)` form). One fault line per
# offending line, naming the first such variable on it:
#   <path>:<n>: here-string carries <name>, assigned from <command>
# <command> is the opener as matched: `git show`, `git cat-file`, `cat` or `<`.
# <path> is printed as given. One awk reading the file twice: the first pass
# collects the assignments by name, the second enumerates the `<<<` lines.
# Nothing is skipped: a comment holding `<<<` is a line holding `<<<`.
here_string_sources() { # <script>
  awk -v path="$1" '
    FNR == NR {
      s = $0
      while (match(s, /[A-Za-z_][A-Za-z0-9_]*="?\$\(/)) {
        name = substr(s, RSTART, RLENGTH); sub(/="?\$\($/, "", name)
        s = substr(s, RSTART + RLENGTH)
        rest = s; sub(/^[ \t]+/, "", rest)
        cmd = ""
        if (index(rest, "git show") == 1) cmd = "git show"
        else if (index(rest, "git cat-file") == 1) cmd = "git cat-file"
        else if (index(rest, "cat ") == 1) cmd = "cat"
        else if (index(rest, "<") == 1) cmd = "<"
        if (cmd != "" && !(name in src)) src[name] = cmd
      }
      next
    }
    {
      i = index($0, "<<<"); if (!i) next
      s = substr($0, i + 3)
      while (match(s, /\$\{?[A-Za-z_][A-Za-z0-9_]*/)) {
        name = substr(s, RSTART, RLENGTH); sub(/^\$\{?/, "", name)
        s = substr(s, RSTART + RLENGTH)
        if (name in src) {
          printf "%s:%d: here-string carries %s, assigned from %s\n", path, FNR, name, src[name]
          break
        }
      }
    }' "$1" "$1"
}

# The real tree. At 3b9f531 this prints six lines - 330, 336, 372, 1077, 1086
# and 1113 - and the story pastes them; after the fix it prints nothing.
assert_eq "AC-2: no here-string in scripts/check-boundaries.sh carries a story copy or a git show result" \
  "" "$(cd "$REPO_ROOT" && here_string_sources scripts/check-boundaries.sh)"

# The fixtures: the defect put back on one line, and the shapes around it.
# hs_fix <name>   Writes the body on stdin to $FIX/hs/<name>.sh; sets $hs_p.
hs_fix() { mkdir -p "$FIX/hs"; hs_p="$FIX/hs/$1.sh"; cat > "$hs_p"; }

hs_fix one-git-show <<'SH'
x="$(git show a:b)"
cmd <<< "$x"
SH
assert_eq "AC-2: a here-string fed from \`git show\` is refused on that one line" \
  "$hs_p:2: here-string carries x, assigned from git show" "$(here_string_sources "$hs_p")"

hs_fix rev-parse <<'SH'
x="$(git rev-parse HEAD)"
cmd <<< "$x"
SH
assert_eq "AC-2: a here-string fed from \`git rev-parse\` is accepted" \
  "" "$(here_string_sources "$hs_p")"

hs_fix two-vars <<'SH'
a="$(git rev-parse HEAD)"
b="$(git show a:b)"
cmd <<< "$a"$'\n'"$b"
SH
assert_eq "AC-2: a here-string of two variables names the one assigned from \`git show\`, not the other" \
  "$hs_p:3: here-string carries b, assigned from git show" "$(here_string_sources "$hs_p")"

hs_fix redirect-read <<'SH'
x="$(< story.md)"
cmd <<< "$x"
SH
assert_eq "AC-2: a here-string fed from \`\$(< file)\` is refused" \
  "$hs_p:2: here-string carries x, assigned from <" "$(here_string_sources "$hs_p")"

hs_fix cat-unquoted <<'SH'
x=$(cat story.md)
cmd <<< "$x"
SH
assert_eq "AC-2: a here-string fed from \`cat\`, unquoted assignment, is refused" \
  "$hs_p:2: here-string carries x, assigned from cat" "$(here_string_sources "$hs_p")"

hs_fix cat-file-braced <<'SH'
if ! x="$(git cat-file -p HEAD:f)"; then exit 1; fi
cmd <<< "${x}"
SH
assert_eq "AC-2: a \${name} here-string fed from \`git cat-file\` inside an \`if !\` is refused" \
  "$hs_p:2: here-string carries x, assigned from git cat-file" "$(here_string_sources "$hs_p")"

hs_fix assigned-later <<'SH'
f() { cmd <<< "$x"; }
y="$(git rev-parse HEAD)"
cmd <<< "$y"
x="$(git show a:b)"
SH
assert_eq "AC-2: an assignment anywhere in the script counts, and only the line using it is refused" \
  "$hs_p:1: here-string carries x, assigned from git show" "$(here_string_sources "$hs_p")"
rm -rf "$FIX/hs"


# ---------------------------------------------------------------------------
describe "no scratch directory, no verdict; the scratch directory is left empty (HARNESS-097)"

# check-boundaries.sh writes every story copy and git show result to a scratch
# file under .claude/state/check-boundaries/ (HARNESS-089). At release 110 the
# `mkdir -p` that makes that directory ignored its status: with a plain file at
# the path every `git show ... > "$cp"` failed with `Not a directory`, the
# criteria were judged against an empty baseline, and the run printed a verdict
# - `ok    acceptance criteria changed, with an ## Amendments entry` - read
# from evidence it never had (HARNESS-089's diff review, finding 1). A run that
# cannot read its evidence refuses instead.
#
# The fixture is the reviewer's: a base copy at PLANNED on main, the branch at
# REVIEW with the SAME criteria and an ## Amendments entry. With the directory
# the run says `unchanged since main`; without it the empty baseline differs
# from everything, and the amendment turns that into `ok ... changed`. The
# branch's story is a SPIKE, which is what makes $rc mean something: a feature
# story at REVIEW needs a ## Gate results record only gates.sh can write, and at
# any other phase is refused as "a PR should be opened from REVIEW", so every
# feature fixture exits 1 whatever the scratch directory does. A spike at REVIEW
# that changes no source exits 0 - checked by the twin below - so the non-zero
# exit asserted with the plain file in place is the refusal's own.
crit_base   T-43 PLANNED "criteria v1"
crit_branch T-43
{ printf -- '---\nid: T-43\ntitle: Fixture story\nslug: fixture\ntype: spike\nstatus: todo\nphase: REVIEW\nbranch: story/T-43-fixture\n---\n\n'
  printf -- '## Acceptance criteria\n\n- **AC-1** - criteria v1.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n'
  printf -- '\n## Amendments\n\nAC-1 unchanged; this entry exists so that an empty baseline reads as an amended change.\n'
} > "$FIX/docs/backlog/stories/T-43.md"
commit_all "T-43 at REVIEW, a spike"

# The precondition: a plain file where the directory goes. make_fixture made
# $FIX/.claude/state, so the parent exists; `mkdir -p` over a plain file exits 1
# with `File exists` on Git for Windows bash and on Linux alike.
rm -rf "$FIX/.claude/state/check-boundaries"
: > "$FIX/.claude/state/check-boundaries"
run_boundaries

# The needle is a whole FAIL line, never the bare path: at release 110 bash's
# own redirect error - `.../.claude/state/check-boundaries/copy-<pid>.md: Not a
# directory`, on stderr, which run_boundaries captures - already carries the
# path, so `refused "..." ".claude/state/check-boundaries"` passes over the
# defect. Only a line that starts `FAIL  ` (problem's prefix) counts.
cb_fail_lines="$(grep -E '^FAIL  .*\.claude/state/check-boundaries' <<< "$out")"
if [ -n "$cb_fail_lines" ]; then
  _ok "AC-1: with a plain file at .claude/state/check-boundaries, a FAIL line names that path"
else
  _bad "AC-1: with a plain file at .claude/state/check-boundaries, a FAIL line names that path" \
    "expected a line starting 'FAIL  ' that names .claude/state/check-boundaries
actual:   $out"
fi
assert_eq "AC-1: with a plain file at .claude/state/check-boundaries, the run exits non-zero" \
  non-zero "$([ "$rc" -ne 0 ] && echo non-zero || echo "$rc")"
# No criteria verdict of any kind: neither `ok    acceptance criteria ...` nor
# the `## Acceptance criteria differ` refusal, so the match ignores case.
assert_eq "AC-1: with a plain file at .claude/state/check-boundaries, no line mentions acceptance criteria" \
  "" "$(grep -i 'acceptance criteria' <<< "$out")"

# The plain file goes BEFORE anything else runs: every later check-boundaries
# run in this suite shares $FIX, and with the file in place each would be
# refused for AC-1's reason rather than judged on its own.
rm -f "$FIX/.claude/state/check-boundaries"
run_boundaries

# The twin: the same fixture, directory creatable, gets its ordinary verdict and
# its ordinary status - so the refusal above is the directory's, not the
# fixture's.
whole_line "AC-1 twin: with the plain file gone, the same fixture reports its criteria unchanged since main" \
  "ok    acceptance criteria unchanged since main"
assert_eq "AC-1 twin: with the plain file gone, the same fixture exits 0" 0 "$rc"

# AC-2: the run has exited, and its scratch files went with it. Passes on
# arrival - the trap predates this story - and is earned by DV-1, which deletes
# the trap and watches this name the copy-<pid>.md it leaves behind.
assert_eq "AC-2: after a run, .claude/state/check-boundaries exists as a directory" \
  directory "$([ -d "$FIX/.claude/state/check-boundaries" ] && echo directory || echo missing)"
assert_eq "AC-2: after a run, .claude/state/check-boundaries is empty" \
  "" "$(ls -A "$FIX/.claude/state/check-boundaries" 2>&1)"

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

# HARNESS-062 AC-2, audit mutant B04. The owner has to be a PHASE, not merely
# a word after "owner:". Every acceptance above names GATES and the one refusal
# names nobody at all, so widening has_owner's phase list to any run of letters
# (`[a-z]*`) survived the whole suite: `owner: banana` would have counted as a
# declared owner. The fixture is exactly the shape that mutant admits - lower
# case, a colon, one word - and carries a fenced result, so the owner check is
# the only rule with anything to say about it.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. owner: banana

```
 x round-trips an arbitrary world document
 Tests  1 failed | 44 passed (45)
```
EOF
run_boundaries
refused "HARNESS-062 AC-2: an owner line naming no phase (owner: banana) is refused" "does not declare an owner"

# Its control names GREEN, not GATES: B04's widened class still matches GATES,
# and a control the mutant cannot tell apart from the original says nothing
# about which phases the list really carries.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. Owner: GREEN

```
 x round-trips an arbitrary world document
 Tests  1 failed | 44 passed (45)
```
EOF
run_boundaries
assert_contains "HARNESS-062 AC-2: the same section with Owner: GREEN is accepted as owned" \
  "ok    ## Deferred verifications names the phase that owns each entry" "$out"

# HARNESS-062 AC-3, audit mutant B05. A waiver is the WORD "waived". The only
# waiver fixture above writes WAIVED in capitals with a space after it, so
# matching the bare substring survived: "unwaived" - which says the opposite -
# would have counted as a waiver and discharged the entry. The prose below
# carries no block and no "waived" as a word of its own; re-read it before
# changing it, because one stray "waived" makes the case pass for the wrong
# reason.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. Owner: GATES.
   This entry is still unwaived, and nobody has run it yet.
EOF
run_boundaries
refused "HARNESS-062 AC-3: 'unwaived' is not a waiver, so the entry has no result and no waiver" \
  "## Deferred verifications has no result and no waiver"
whole_line "HARNESS-062 AC-3: and the refusal is the whole 3h line" "$WANT_3H"

# Its two controls: the word in lower case mid-sentence, and at the start of a
# line with a colon - the two spellings an author actually writes, neither of
# them the capitalised WAIVED the case above already holds.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. Owner: GATES.
   The PO waived it on 2026-10-17: the encoder moved to WORLD-010.
EOF
run_boundaries
assert_contains "HARNESS-062 AC-3: 'waived' in lower case mid-sentence is a waiver" \
  "ok    ## Deferred verifications carries an explicit waiver" "$out"

story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. Owner: GATES.
Waived: the encoder moved to WORLD-010 with the criterion it belonged to.
EOF
run_boundaries
assert_contains "HARNESS-062 AC-3: 'Waived:' starting a line is a waiver" \
  "ok    ## Deferred verifications carries an explicit waiver" "$out"

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
story_blocked REVIEW <<'EOF'
1. PO decision: the `types` gate is BLOCKED here, not failing - Smart App Control
   refuses the locally built binary by reputation (os error 4551), the branch does
   not touch it, and the same command passes elsewhere. Marking types pending CI.
EOF
# The escalation lands AFTER the run, as the comment above describes: `lint` is
# not in the record at all - neither PASS nor BLOCKED.
sed -i 's/^branch: story\/T-1-fixture$/&\nrequired_gates: [lint]/' "$FIX/docs/backlog/stories/T-1.md"
commit_all "T-1 escalates lint after the run"
run_boundaries
refused "a required gate the record has no PASS for" \
  "frontmatter requires gate 'lint', but the recorded run has no PASS for it"

# HARNESS-071. A gate is only ever BLOCKED because it is required, so a
# story-required gate the environment refused is the ordinary BLOCKED case, not
# an exception to it. Demanding a PASS for it contradicted the BLOCKED check,
# which accepts REVIEW on "pending CI" - and no local run can ever produce that
# PASS, so the path /advance-story prescribes was closed to every story that
# escalated the gate it blocked on (CAL-016, `db`, in clean_calendar). The
# pending-CI line and, at DONE, the CI run URL are judged by the BLOCKED check;
# this rule defers to it.
story_blocked REVIEW '[types]' <<'EOF'
1. PO decision: the `types` gate is BLOCKED here, not failing - Smart App Control
   refuses the locally built binary by reputation (os error 4551), the branch does
   not touch it, and the same command passes elsewhere. Marking types pending CI.
EOF
run_boundaries
assert_contains "a required gate that was BLOCKED defers to the pending-CI check" \
  "ok    story-required gate 'types' was BLOCKED; judged as pending CI above" "$out"
assert_eq "and a blocked required gate recorded as pending CI is not refused" 0 "$rc"

# Deferring must not become a way past the BLOCKED check: with nothing written
# down, the same story is still refused, by that check.
story_blocked REVIEW '[types]' <<'EOF'
Ran the gates. One of them did not work on this machine.
EOF
run_boundaries
refused "a blocked required gate with no pending-CI line is still refused" \
  "gate 'types' was BLOCKED - the environment would not launch it - and nothing in the story says so"

# And at DONE the CI run is still owed.
story_blocked DONE '[types]' <<'EOF'
1. PO decision: types is BLOCKED locally by Smart App Control. Marking it
   pending CI.
EOF
run_boundaries
refused "a blocked required gate at DONE still needs the CI run" \
  "gate 'types' was BLOCKED locally and has not been verified on CI"

# Only a gate the BLOCKED check actually judged is deferred. A spike's record is
# not judged above, so its BLOCKED required gate has had no pending-CI check and
# is still owed a PASS here.
story_blocked REVIEW '[types]' <<'EOF'
1. PO decision: types is BLOCKED locally by Smart App Control. Marking it
   pending CI.
EOF
sed -i 's/^type: feature$/type: spike/' "$FIX/docs/backlog/stories/T-1.md"
commit_all "T-1 is a spike"
run_boundaries
refused "a spike's blocked required gate is not deferred, since nothing judged it" \
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

# HARNESS-062 AC-1, audit mutant B08. The gate id has to END where the record's
# gate name ends - a space, a "(" or the end of the line. Every record above
# names gates that share no prefix, so dropping that terminator survived: a
# PASS for `unit-slow` would have stood in for a required `unit` that never ran.
# The record here is pasted, not run: rule 3e-i reads the section's text, and
# the tree-hash rule that refuses a pasted record says so in different words.
# So the refusal is asserted by its needle, and the two controls by their ok
# line rather than by $rc, which the tree-hash rule keeps non-zero throughout.
story_on_branch feature 'required_gates: [unit]' <<'EOF'
## Gate results

PASS         unit-slow (1s)
EOF
run_boundaries
refused "HARNESS-062 AC-1: a PASS for unit-slow does not satisfy a required unit" \
  "frontmatter requires gate 'unit', but the recorded run has no PASS for it"

story_on_branch feature 'required_gates: [unit]' <<'EOF'
## Gate results

PASS         unit (12s)
EOF
run_boundaries
assert_contains "HARNESS-062 AC-1: PASS unit followed by its timing satisfies a required unit" \
  "ok    story-required gate 'unit' passed in the recorded run" "$out"

story_on_branch feature 'required_gates: [unit]' <<'EOF'
## Gate results

PASS         unit
EOF
run_boundaries
assert_contains "HARNESS-062 AC-1: PASS unit ending the line satisfies a required unit" \
  "ok    story-required gate 'unit' passed in the recorded run" "$out"

# HARNESS-062 AC-4, audit mutant B07. The rule runs at DONE as well as REVIEW,
# and every fixture that reached it was at REVIEW, so dropping DONE from its
# case label survived: a story could be closed with a gate it escalated never
# having passed. Under that mutant other rules still refuse this story, which
# is why refused checks the message as well as the status. The second case is
# the same rule from the other side - at DONE, a gate that did pass is SAID to
# have passed - and it goes red under B07 too, because the rule never runs.
story_on_branch feature 'required_gates: [unit]' DONE <<'EOF'
## Gate results

PASS         unit-slow (1s)
EOF
run_boundaries
refused "HARNESS-062 AC-4: at DONE, a PASS for unit-slow does not satisfy a required unit" \
  "frontmatter requires gate 'unit', but the recorded run has no PASS for it"

story_on_branch feature 'required_gates: [unit]' DONE <<'EOF'
## Gate results

PASS         unit (12s)
EOF
run_boundaries
assert_contains "HARNESS-062 AC-4: at DONE, a recorded PASS unit is reported as passing" \
  "ok    story-required gate 'unit' passed in the recorded run" "$out"

# ---------------------------------------------------------------------------
describe "a spike that escalates a gate has to have run it"

# HARNESS-054, ported from manhwa-cropper 3ac70e3. The required_gates re-check
# lived inside the non-spike arm of 3e, and inside the else of its marker test,
# so a spike that named a gate in required_gates and never ran it merged with
# nothing said but "spike story; gate record not required". Every fixture in
# the describe above is type: feature, so no spike had ever been put through.
#
# The exemption is right and stays (AC-2); only its width was wrong. AC-1a and
# AC-1b are pinned separately because they fail through different code today:
# no record at all, and a real record with no PASS for the escalated gate.
# AC-3 is AC-1b's twin with integration in the record, so a fix that refused
# every escalating spike passes AC-1 and fails AC-3.

# gates_recorded <what>   Runs the real gates.sh for T-1 in the fixture. Its
# record is the only one check-boundaries.sh's tree hash agrees with, so it is
# never pasted - and a run that quietly stopped recording would make AC-1b
# pass for the wrong reason and AC-3 fail for one, hence the assertion.
gates_recorded() {
  local g
  g="$( cd "$FIX" && bash scripts/gates.sh --story T-1 2>&1 )"
  assert_contains "fixture: $1 was recorded by gates.sh" \
    "recorded in docs/backlog/stories/T-1.md" "$g"
}

story_on_branch spike 'required_gates: [integration]' <<'EOF'
## Notes

A spike that named a gate in its frontmatter and never ran it.
EOF
run_boundaries
assert_contains "AC-1a an escalating spike with no gate record is refused" \
  "story T-1: frontmatter requires gate 'integration'" "$out"
assert_eq "AC-1a and the run fails rather than noting and moving on" 1 "$rc"

story_on_branch spike 'required_gates: [integration]' </dev/null
write_conf "$FIX" <<'CONF'
gate     | unit | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit | Tests +[1-9][0-9]* passed
CONF
# project.conf is code the gate hash covers, and gates.sh will not record while
# a gated file is untracked, so it is committed BEFORE the run.
commit_all "T-1 conf"
gates_recorded "a run that never touched integration"
commit_all "T-1 recorded, integration unrun"
run_boundaries
assert_contains "AC-1b a recorded run with no PASS for the escalated gate is refused" \
  "story T-1: frontmatter requires gate 'integration'" "$out"
assert_eq "AC-1b and that run fails too" 1 "$rc"

story_on_branch spike 'required_gates: []' <<'EOF'
## Notes

A spike that escalated nothing, which is what a spike usually is.
EOF
run_boundaries
assert_contains "AC-2 a spike escalating nothing still needs no gate record" \
  "spike story; gate record not required" "$out"
assert_eq "AC-2 and merges" 0 "$rc"

story_on_branch spike 'required_gates: [integration]' </dev/null
write_conf "$FIX" <<'CONF'
gate     | unit        | required | . | printf 'Tests  47 passed (47)\n'
evidence | unit        | Tests +[1-9][0-9]* passed
gate     | integration | optional | . | printf 'Tests  3 passed (3)\n'
evidence | integration | Tests +[1-9][0-9]* passed
CONF
commit_all "T-1 conf"
gates_recorded "a run that did cover integration"
assert_contains "fixture: the record carries a PASS for integration" \
  "PASS         integration" "$(cat "$FIX/docs/backlog/stories/T-1.md")"
commit_all "T-1 recorded, integration run"
assert_eq "fixture: the record's tree is the tree being merged" \
  "$( cd "$FIX" && CLAUDE_PROJECT_DIR="$FIX" bash -c '. .claude/hooks/lib.sh; gate_tree_hash' )" \
  "$(sed -nE '/^[[:space:]]*tree:[[:space:]]*[0-9a-f]+/{s/^[[:space:]]*tree:[[:space:]]*([0-9a-f]+).*/\1/p;q;}' "$FIX/docs/backlog/stories/T-1.md")"
run_boundaries
assert_eq "AC-3 a spike that ran the gate it escalated merges" 0 "$rc"
# No line BEGINS with FAIL - read on a here-string, never a pipe. A message
# that merely mentions the word is not an objection. The lines themselves are
# the actual value, so a failure names the objection rather than a count.
assert_eq "AC-3 and nothing in the run objects" "" "$(grep '^FAIL' <<< "$out")"

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

# ---------------------------------------------------------------------------
describe "GREEN and GATES add no suppression to source (HARNESS-081): the fixture"

# Issue #132. The lock freezes tests in GREEN and GATES, and 3i reads what RED
# puts in a manifest; nothing read what GREEN and GATES ADD to source, and the
# cheapest way to make a lint, type or coverage gate stop complaining is a
# one-line directive that silences the tool. Block 3j walks every GREEN and
# GATES commit, as 3i walks RED ones, and refuses an added line that is a
# suppression directive unless the story's ## Suppressions declares it.
#
# THE FIXTURE IS A SPIKE, AND THAT IS WHAT MAKES $rc MEAN SOMETHING. A feature
# story at REVIEW needs a ## Gate results record only a real gates.sh run can
# write, so every feature fixture in this file exits 1 whatever 3j does, and a
# refusal's status assertion would be satisfied by 3e. A spike at REVIEW needs
# no record, and its ## Scaffold inventory names every path the branch changes,
# so a branch this rule does not refuse exits 0 - the premise below, checked
# before anything relies on it. Nothing in the rule may key on the story type:
# AC-1 is pinned on a feature story as well, by its whole line.

# _src_story <phase> <inventory paths> [body] [type]   Writes the T-1 story.
_src_story() {
  {
    printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: %s\nstatus: todo\nphase: %s\nbranch: story/T-1-fixture\n---\n\n' "${4:-spike}" "$1"
    printf -- '## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Handoff: RED -> GREEN\n\nthe command, the failure, the export shape.\n\n'
    printf -- '## Scaffold inventory\n\n%s - fixture\nsrc/clean.ts - fixture\n' "$2"
    [ -n "${3:-}" ] && printf -- '\n%s\n' "$3"
  } > "$FIX/docs/backlog/stories/T-1.md"
}
# _src_branch   A fresh story/T-1-fixture cut from main.
_src_branch() {
  git -C "$FIX" checkout -q main 2>/dev/null
  git -C "$FIX" branch -D story/T-1-fixture >/dev/null 2>&1
  git -C "$FIX" checkout -q -b story/T-1-fixture 2>/dev/null
  mkdir -p "$FIX/docs/backlog/stories"
}
# _short   The short form of HEAD, as check-boundaries.sh prints a commit.
_short() { local c; c="$(git -C "$FIX" rev-parse HEAD)"; printf '%s' "${c:0:7}"; }

# source_story <phase> <path> <line> [then]   C-5's helper, in the shape of
# manifest_story: a branch whose first commit carries the story at <phase> and
# appends <line> to <path> (creating it), and whose last moves the story to
# REVIEW with the body on stdin appended - which is how a ## Suppressions entry
# reaches the WORKING-TREE story the rule reads. Sets $sup_c (the short commit
# that added <line>) and $sup_n (its line number in the file as committed).
#   [then] = clean   a GREEN commit appending a clean line to src/clean.ts sits
#                    in between, so the rule has a commit it must judge
#   [then] = GATES   a GATES commit appends <line> to <path> a second time, and
#                    sets $sup_c2 and $sup_n2 for it
# SRC_STORY_TYPE overrides the story type (default spike).
source_story() {
  local phase="$1" path="$2" line="$3" then="${4:-}" t="${SRC_STORY_TYPE:-spike}" body
  body="$(cat)"
  _src_branch
  mkdir -p "$(dirname "$FIX/$path")"
  _src_story "$phase" "$path" "" "$t"
  printf '%s\n' "$line" >> "$FIX/$path"
  commit_all "T-1 $phase adds a line to $path"
  sup_c="$(_short)"; sup_n="$(awk 'END { print NR }' "$FIX/$path")"
  case "$then" in
    clean)
      _src_story GREEN "$path" "" "$t"
      printf 'export const clean = 1\n' >> "$FIX/src/clean.ts"
      commit_all "T-1 GREEN, a clean source change" ;;
    GATES)
      _src_story GATES "$path" "" "$t"
      printf '%s\n' "$line" >> "$FIX/$path"
      commit_all "T-1 GATES adds the same line again"
      sup_c2="$(_short)"; sup_n2="$(awk 'END { print NR }' "$FIX/$path")" ;;
  esac
  _src_story REVIEW "$path" "$body" "$t"
  commit_all "T-1 to review"
}

# The refusal, as C-2 states it, byte for byte, and pinned as a WHOLE line: a
# substring needle is satisfied by a message that dropped the line number or
# named the wrong phase in a clause the needle did not reach.
SUP_TAIL=". GREEN and GATES may not silence a tool to reach green; if this one is needed, declare it in ## Suppressions - one line carrying the path, the rule id and 'approved by <who>', with the reason - and say why in that line."
# want_3j <commit> <PHASE> <path> <line no> <rule id> <added line, trimmed> [suffix]
want_3j() { printf "FAIL  story T-1: commit %s (%s) added a suppression to '%s' line %s [%s]: %s%s%s" "$1" "$2" "$3" "$4" "$5" "$6" "$SUP_TAIL" "${7:-}"; }
# want_3j_ok <n>   The rule's summary line over <n> judged commits (C-1 b).
want_3j_ok() { printf 'ok    GREEN/GATES added no suppression (%s commit(s) judged)' "$1"; }
# sup_fails   Every line of $out this rule printed as a refusal - the lines, not
# a count, so a failure names them. A here-string, never a pipe.
sup_fails() { grep -F -- 'added a suppression to' <<< "$out"; }
# sup_nfail   How many such lines.
sup_nfail() { grep -cF -- 'added a suppression to' <<< "$out"; }
# sup_count <line>   How many whole lines of $out equal <line>.
sup_count() { grep -cxF -- "$1" <<< "$out"; }

AC1_LINE='// eslint-disable-next-line @typescript-eslint/no-explicit-any'

# A known baseline on main: src/main.ts is one line, so a line appended to it is
# line 2; and no T-1 story on main, so every branch's story is new in the PR
# and 3d has no criteria to compare (an earlier describe commits one to main).
git -C "$FIX" checkout -q main 2>/dev/null
printf 'export const x = 1\n' > "$FIX/src/main.ts"
git -C "$FIX" rm -q --cached docs/backlog/stories/T-1.md >/dev/null 2>&1
rm -f "$FIX/docs/backlog/stories/T-1.md"
commit_all "HARNESS-081 baseline: src/main.ts is one line, no T-1 on main"

# The premise. PASSES ON ARRIVAL, by design: it is a claim about the fixture,
# not about 3j, and it is what makes the `rc 0` and `rc 1` halves below say
# something about this rule rather than about some other one.
source_story GREEN src/main.ts 'export const y = 2' </dev/null
run_boundaries </dev/null
assert_eq "fixture: a spike branch whose GREEN commit adds a clean line exits 0, and nothing objects" \
  "0|" "$rc|$(grep '^FAIL' <<< "$out")"

# ---------------------------------------------------------------------------
describe "AC-1: a suppression added in GREEN or GATES is refused, by path, line, commit and phase"

for ph in GREEN GATES; do
  source_story "$ph" src/main.ts "$AC1_LINE" </dev/null
  run_boundaries </dev/null
  whole_line "AC-1 ($ph): the refusal names eslint-disable, src/main.ts, line 2, the commit and $ph" \
    "$(want_3j "$sup_c" "$ph" src/main.ts 2 eslint-disable "$AC1_LINE")"
  assert_eq "AC-1 ($ph): it is the only refusal this rule prints" 1 "$(sup_nfail)"
  assert_eq "AC-1 ($ph): and the run exits 1, where the same branch without the line exits 0" 1 "$rc"
  assert_eq "AC-1 ($ph): and no summary line claims the commit was clean beside the refusal" 0 \
    "$(grep -cF -- 'GREEN/GATES added no suppression' <<< "$out")"
done

# The rule is about the commit's phase and the path's category, never the story
# type - the spike fixture must not be what makes it fire.
SRC_STORY_TYPE=feature source_story GREEN src/main.ts "$AC1_LINE" </dev/null
run_boundaries </dev/null
whole_line "AC-1: a feature story's GREEN commit is refused by the same whole line" \
  "$(want_3j "$sup_c" GREEN src/main.ts 2 eslint-disable "$AC1_LINE")"

# A-1 (a), diff review finding 1. The documented GATES -> REVIEW step sets the
# phase and only THEN commits, so a fix still uncommitted at that moment lands in
# a commit whose own story says REVIEW. Judged by its first parent's phase
# (C-9), and the FAIL line says both: `(REVIEW, after GATES)`. The branch: a
# story-only commit at <parent phase> (no source path, so not itself a judged
# commit), then ONE commit that sets REVIEW and appends the AC-1 line.
for pph in GATES GREEN; do
  _src_branch
  _src_story "$pph" src/main.ts
  commit_all "T-1 to $pph"
  _src_story REVIEW src/main.ts
  printf '%s\n' "$AC1_LINE" >> "$FIX/src/main.ts"
  commit_all "T-1 to review, with the $pph work still uncommitted"
  rev_c="$(_short)"
  run_boundaries </dev/null
  whole_line "AC-1 (REVIEW after $pph): a line committed by the step that sets REVIEW is refused, naming 'REVIEW, after $pph'" \
    "$(want_3j "$rev_c" "REVIEW, after $pph" src/main.ts 2 eslint-disable "$AC1_LINE")"
  assert_eq "AC-1 (REVIEW after $pph): rc|refusals|summary - refused once, and nothing calls it clean" \
    "1|1|0" "$rc|$(sup_nfail)|$(grep -cF -- 'GREEN/GATES added no suppression' <<< "$out")"
done

# A-1 (b), diff review finding 6. Every case above adds ONE line, so it is the
# first of its hunk and its number is the hunk header's: a counter that never
# advances would pass them all. Three lines appended in one GREEN commit, the
# needle third: src/main.ts is one line on main, so the needle is line 4. PASSES
# ON ARRIVAL (the counter is right today); earned by a mutate.sh run deleting the
# `ln++` for an added line, in ## Regressions, Return 1.
source_story GREEN src/main.ts $'export const a = 1\nexport const b = 2\n// @ts-ignore' </dev/null
run_boundaries </dev/null
whole_line "AC-1: the third of three lines added in one hunk is refused by ITS line number, 4, not the hunk's first" \
  "$(want_3j "$sup_c" GREEN src/main.ts 4 ts-ignore '// @ts-ignore')"
assert_eq "AC-1: three lines in one hunk - the two clean ones are not refused (refusals)" 1 "$(sup_nfail)"

# ---------------------------------------------------------------------------
describe "AC-2: every row of the needle table is refused by its rule id, in GREEN and in GATES"

# C-2's table, one row per example line: <rule id>|<path>|<example added line>.
# HARNESS-082 appends its rows HERE and inherits both the refusal below and the
# path inventory. Paths are `source` by the real paths.conf the fixture copies;
# the two config-file linters' rows go to a Dockerfile and a Makefile, which it
# calls `config`, so no classification is faked.
# The last two rows are A-1's (finding 5): directives the tools honour with no
# space before the opener, which an anchor of whitespace alone missed.
AC2_ROWS="$(cat <<'ROWS'
eslint-disable|src/main.ts|// eslint-disable-next-line @typescript-eslint/no-explicit-any
ts-ignore|src/main.ts|// @ts-ignore
biome-ignore|src/main.ts|// biome-ignore lint/suspicious/noExplicitAny: legacy
noqa|src/app.py|x = eval(s)  # noqa: S307
type-ignore|src/app.py|y = f()  # type: ignore[attr-defined]
rust-allow|src/lib.rs|#[allow(dead_code)]
rust-allow|src/lib.rs|#![allow(clippy::all)]
gd-warning-ignore|src/player.gd|@warning_ignore("unused_parameter")
coverage-ignore|src/main.ts|/* istanbul ignore next */
coverage-ignore|src/main.ts|// c8 ignore start
no-cover|src/app.py|def f():  # pragma: no cover
stryker-disable|src/main.ts|// Stryker disable next-line all
hadolint-ignore|Dockerfile|# hadolint ignore=DL3008
shellcheck-disable|Makefile|# shellcheck disable=SC2086
eslint-disable|src/main.ts|foo();// eslint-disable-line
noqa|src/app.py|x = eval(s)# noqa
stub-throw|src/main.ts|throw new Error("not implemented")
stub-throw|src/main.ts|throw Error('Not Implemented')
stub-throw|src/main.ts|  throw new NotImplementedError()
stub-throw|src/main.ts|const f = () => { throw new Error(`TODO: wire the cache`) }
stub-throw|src/main.ts|throw new Error("unimplemented")
stub-todo|src/lib.rs|todo!()
stub-todo|src/lib.rs|unimplemented!("later")
stub-todo|src/lib.rs|    Some(todo!())
stub-todo|src/lib.rs|    _ => unreachable!(),
stub-todo|src/lib.rs|let x = todo!();
stub-raise|src/app.py|raise NotImplementedError
stub-raise|src/app.py|    raise NotImplementedError("later")
stub-gd|src/player.gd|push_error("not implemented")
stub-gd|src/player.gd|assert(false)
stub-gd|src/player.gd|    assert( false, "unreachable")
stub-throw|src/main.ts|throw new Error("Method not implemented.");
stub-throw|src/main.ts|throw new Error('not yet implemented')
stub-throw|src/main.ts|throw new Error("NOT IMPLEMENTED")
stub-gd|src/player.gd|push_error("Not implemented")
empty-handler|src/main.ts|} catch (e) {}
empty-handler|src/main.ts|} catch {}
empty-handler|src/app.py|except: pass
empty-handler|src/app.py|    except Exception: ...  # swallowed
ROWS
)"
# HARNESS-082's return 1 (diff review round 1, findings 2-4) appended the last
# eight rows above, from the amended C-1: TypeScript's quick-fix stub (a prefix
# inside the quotes), `not yet implemented` in single quotes, the upper-case
# spelling; GDScript's capital-N push_error; and the ONE-LINE empty handler in
# its two shapes - a brace pair with nothing between, and `except ...:` with
# `pass` or `...` and an optional comment - refused under the same rule id as
# C-3's two-line window.
# HARNESS-082 appended the last fifteen rows above (its C-1 table, the four stub
# rows): every spelling the contract names - `throw` with and without `new`, a
# custom NotImplementedError class, the message in any of its three quote
# characters and case; `todo!`/`unimplemented!`/`unreachable!` after `(`, `=>`,
# `=` and indentation (the widened `O`); `raise` bare and with a message; and
# GDScript's two spellings. They are refused by HARNESS-081's wording, byte for
# byte (C-4: the word "suppression" stays).
# The C-3 non-matching corpus, <path>|<line>. Each would be refused by a needle
# that floated rather than anchoring on the comment opener, and each must be
# clean. The last three are RED's (C-3 amendment): the two string-literal cases
# C-3 names are excluded by each ERE's TAIL guard - `"` follows `noqa` - not by
# the opener anchor, so these are the lines on which only the anchor holds.
C3_ROWS="$(cat <<'ROWS'
src/main.ts|// never add an eslint-disable here
src/main.ts|const s = "# noqa";
src/main.ts|// see rules.md: "# pragma: no cover" is refused
src/main.ts|// Stryker restore all
src/lib.rs|fn allow(x: u32) -> u32 { x }
src/lib.rs|let expect = 3;
src/main.ts|// @ts-ignored-thing
src/app.py|    Lines ending in type: ignore are not honoured here.
src/app.py|url = "http://x/#noqa"
src/app.py|const s = "# noqa: S307";
src/app.py|url = "http://x/#noqa:frag"
src/lib.rs|msg = "#[allow(dead_code)]"
src/main.ts|const msg = "todo!()"
src/main.ts|const t = `unimplemented!()`
src/lib.rs|let s = 'todo!()';
src/lib.rs|let unimplemented = 0;
src/lib.rs|fn todo_later()
src/lib.rs|my_todo!(x)
src/main.ts|} catch (e) { log(e) }
src/main.ts|throw new Error("no such user")
src/app.py|raise NotImplementedErrorSubclass()
src/player.gd|assert(is_ready)
src/player.gd|assert(false_positives == 0)
src/main.ts|assert(falseCount === 0);
src/app.py|except KeyError: retry()
src/main.ts|throw new Error("could not open the file")
ROWS
)"
# HARNESS-082's return 1 (diff review round 1, findings 2-4) appended the last
# four rows above, from the amended C-2: `false` as the start of an identifier
# (stub-gd's tail guard), in both case conventions; a one-line except WITH a
# body (not the one-line empty-handler row); and a message that contains `not`
# but is not a stub (the widened stub-throw prefix must still need the word
# `implemented`).
# HARNESS-082 appended the last ten rows above: its C-2 corpus, one line per
# commit - a stub inside each of the three quote characters (the `O` class
# excludes them), `unimplemented` and `todo_` as identifiers, a macro whose name
# merely ends in `todo`, a handler with a body on one line (no opener: the line
# does not end in `{`), a real error message, the NotImplementedError tail guard,
# and an assert on a real condition. C-1's accepted false positive - a COMMENT
# quoting a stub - is deliberately absent: it is refused by design. The
# multi-line members of C-2 are their own describe below, since this table is
# one line per commit.
# _trim <s>   <s> without leading or trailing whitespace, as the refusal quotes it.
_trim() { local s="$1"; s="${s#"${s%%[![:space:]]*}"}"; printf '%s' "${s%"${s##*[![:space:]]}"}"; }

# ONE branch, ONE run: per row a GREEN commit adding the line and then a GATES
# commit adding it again, each recorded with the whole refusal it must draw. One
# run rather than one per row because a check-boundaries.sh run costs about 3 s
# on this host and the rows differ only in data; every row is still asserted by
# its own whole line, and the exit status is pinned per case by AC-1. GATES is in
# every row because DV-1 narrows the phase test to GREEN and needs every row's
# GATES half to go red.
ac2_paths="$(awk -F'|' 'NF && !seen[$2]++ { printf "%s ", $2 }' <<< "$AC2_ROWS")"
_src_branch
ac2_want=()
while IFS='|' read -r rid path line; do
  [ -z "$rid" ] && continue
  for ph in GREEN GATES; do
    _src_story "$ph" "$ac2_paths"
    printf '%s\n' "$line" >> "$FIX/$path"
    commit_all "T-1 $ph adds [$rid] to $path"
    ac2_want+=("$rid|$ph|$path: $(_trim "$line")|$(want_3j "$(_short)" "$ph" "$path" "$(awk 'END { print NR }' "$FIX/$path")" "$rid" "$(_trim "$line")")")
  done
done <<< "$AC2_ROWS"
_src_story REVIEW "$ac2_paths"
commit_all "T-1 to review"
run_boundaries </dev/null
for w in "${ac2_want[@]}"; do
  rid="${w%%|*}"; w="${w#*|}"; ph="${w%%|*}"; w="${w#*|}"; what="${w%%|*}"
  whole_line "AC-2 [$rid] ($ph): the added line is refused by its whole line, naming $rid - $what" "${w#*|}"
done
assert_eq "AC-2: the table branch - rc|refusals (one per added line)|summary" \
  "1|${#ac2_want[@]}|0" "$rc|$(sup_nfail)|$(grep -cF -- 'GREEN/GATES added no suppression' <<< "$out")"

# ---------------------------------------------------------------------------
describe "AC-2 control: a line that only mentions a directive is clean (C-3)"

# Same run shape - one GREEN commit per corpus line to a source file - and the
# claims that make "clean" mean something: exit 0, no refusal from anywhere, and
# the rule's own summary over every commit it judged, so a rule that judged
# nothing cannot pass. Per row, the line is not quoted anywhere in the output.
c3_paths="$(awk -F'|' 'NF && !seen[$1]++ { printf "%s ", $1 }' <<< "$C3_ROWS")"
_src_branch
c3_n=0
while IFS='|' read -r path line; do
  [ -z "$path" ] && continue
  _src_story GREEN "$c3_paths"
  printf '%s\n' "$line" >> "$FIX/$path"
  commit_all "T-1 GREEN adds a C-3 line to $path"
  c3_n=$((c3_n+1))
done <<< "$C3_ROWS"
_src_story REVIEW "$c3_paths"
commit_all "T-1 to review"
run_boundaries </dev/null
while IFS='|' read -r path line; do
  [ -z "$path" ] && continue
  assert_eq "AC-2 control: '$line' in $path is not refused" "" \
    "$(grep -F -- "$(_trim "$line")" <<< "$out")"
done <<< "$C3_ROWS"
assert_eq "AC-2 control: the corpus branch - rc|refusals|summary($c3_n)" \
  "0||1" "$rc|$(grep '^FAIL' <<< "$out")|$(sup_count "$(want_3j_ok "$c3_n")")"

describe "AC-3: other phases, and docs, harness and test paths, are not judged"

# One branch: the AC-1 line added by a RED, a PLANNED, a SCAFFOLD, a REVIEW and
# a DONE commit in turn, then one clean GREEN commit. The summary over exactly
# ONE judged commit is the half that is red before 3j exists, and the half that
# catches a rule judging every commit: that one would print five refusals and
# count six. A-1 (finding 1) judges a commit by its FIRST PARENT's phase too,
# so this case is meaningful only because no commit here has a GREEN or GATES
# parent: REVIEW's parent is SCAFFOLD, DONE's is REVIEW, and the one commit
# whose parent IS GREEN - the final "to review" - changes only the story.
_src_branch
for ph in RED PLANNED SCAFFOLD REVIEW DONE; do
  _src_story "$ph" src/main.ts
  printf '%s\n' "$AC1_LINE" >> "$FIX/src/main.ts"
  commit_all "T-1 $ph adds the AC-1 line"
done
_src_story GREEN src/main.ts
printf 'export const clean = 1\n' >> "$FIX/src/clean.ts"
commit_all "T-1 GREEN, a clean source change"
_src_story REVIEW src/main.ts
commit_all "T-1 to review"
run_boundaries </dev/null
for ph in RED PLANNED SCAFFOLD REVIEW DONE; do
  assert_eq "AC-3: the AC-1 line added in a $ph commit is not refused" "" \
    "$(grep -F -- "($ph) added a suppression" <<< "$out")"
done
assert_eq "AC-3: across those phases - rc|refusals|summary(1)" \
  "0||1" "$rc|$(sup_fails)|$(sup_count "$(want_3j_ok 1)")"

# A GREEN commit adding the line to a path classify.sh calls docs, harness or
# test is out of scope by the classifier's answer. One branch: a GREEN commit
# per path, then one clean GREEN source commit, so the summary says the rule ran
# and judged exactly one - a GREEN commit touching only such paths is not a
# judged commit (C-1 b, and DV-2's "no 3j ok line" depends on it).
_src_branch
for path in docs/backlog/stories/T-1.md scripts/x.sh tests/a.test.ts; do
  _src_story GREEN src/clean.ts
  mkdir -p "$(dirname "$FIX/$path")"
  printf '%s\n' "$AC1_LINE" >> "$FIX/$path"
  commit_all "T-1 GREEN adds the AC-1 line to $path"
done
_src_story GREEN src/clean.ts
printf 'export const clean = 1\n' >> "$FIX/src/clean.ts"
commit_all "T-1 GREEN, a clean source change"
_src_story REVIEW src/clean.ts
commit_all "T-1 to review"
run_boundaries </dev/null
for path in docs/backlog/stories/T-1.md scripts/x.sh tests/a.test.ts; do
  assert_eq "AC-3: the AC-1 line added to $path ($(cd "$FIX" && bash scripts/classify.sh "$path" | cut -f1)) in GREEN is not refused" "" \
    "$(grep -F -- "'$path'" <<< "$out")"
done
assert_eq "AC-3: across those paths - rc|refusals|summary(1)" \
  "0||1" "$rc|$(sup_fails)|$(sup_count "$(want_3j_ok 1)")"

# ---------------------------------------------------------------------------
describe "AC-4: removed lines and context lines are never judged"

# Both files carry a directive ON MAIN, which this rule does not judge (Out of
# scope: suppressions already on the base branch).
git -C "$FIX" checkout -q main 2>/dev/null
printf 'x = 1\ny = eval(s)  # noqa: S307\nz = 3\n' > "$FIX/src/app.py"
printf '#[allow(dead_code)]\nfn a() {}\n'          > "$FIX/src/lib.rs"
commit_all "HARNESS-081 AC-4 baseline: a noqa and an allow on main"
_src_branch
_src_story GREEN "src/app.py src/lib.rs"
printf 'x = 1\nz = 3\n' > "$FIX/src/app.py"
commit_all "T-1 GREEN removes the noqa line"
_src_story GREEN "src/app.py src/lib.rs"
printf '#[allow(dead_code)]\nfn a() -> u32 { 1 }\n' > "$FIX/src/lib.rs"
commit_all "T-1 GREEN edits the line beside the allow"
_src_story REVIEW "src/app.py src/lib.rs"
commit_all "T-1 to review"
run_boundaries </dev/null
assert_eq "AC-4: a removed # noqa and an #[allow] left as context - rc|refusals" \
  "0|" "$rc|$(sup_fails)"
whole_line "AC-4: and the summary counts the two GREEN commits it judged" "$(want_3j_ok 2)"
# Put main back as the describes above found it.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" rm -q --cached src/app.py src/lib.rs >/dev/null 2>&1
rm -f "$FIX/src/app.py" "$FIX/src/lib.rs"
commit_all "HARNESS-081 AC-4 baseline removed"

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
describe "AC-5: a suppression declared in ## Suppressions is accepted, and only a whole declaration"

# The entry is one line carrying the path, the rule id and `approved by`, read
# from the WORKING-TREE story after HTML comments are stripped (C-4). So the
# branch is built once - the AC-1 commit - and each case rewrites the story in
# the working tree only, uncommitted: an implementation reading the section
# from HEAD rather than from $sfile fails the first case.
source_story GREEN src/main.ts "$AC1_LINE" </dev/null
ac5_c="$sup_c"
# ac5 <body>   Rewrite the working-tree story at REVIEW with <body> (printf %b) and run.
# ac5_path is the inventory path, src/main.ts unless a case below moves it.
ac5_path=src/main.ts
ac5() { _src_story REVIEW "$ac5_path" "$(printf '%b' "$1")"; run_boundaries </dev/null; }
AC5_OK="ok    suppression [eslint-disable] in 'src/main.ts' is declared in ## Suppressions"

ac5 '## Suppressions\n\n- `src/main.ts` [eslint-disable] approved by ryan: the generated client types this as any; replacing the generator is its own story.'
assert_eq "AC-5: a declared suppression - rc|refusals" "0|" "$rc|$(sup_fails)"
whole_line "AC-5: and the rule says the path is declared" "$AC5_OK"

# Order free, case-insensitive, and the bare rule id as a word (C-4).
ac5 '## Suppressions\n\n- Approved By ryan: eslint-disable in src/main.ts, because the generated client types this as any.'
assert_eq "AC-5: the three in another order, other case, rule id bare - rc|refusals|declared" \
  "0||1" "$rc|$(sup_fails)|$(sup_count "$AC5_OK")"

# Return 2 (C-9 as amended, round 2 finding 2): the path in single quotes, the
# way the FAIL line itself prints it, so an author who copies it is declared.
ac5 "## Suppressions\n\n- 'src/main.ts' [eslint-disable] approved by ryan: copied from the refusal"
assert_eq "AC-5: a path in single quotes, as the refusal prints it - rc|refusals" "0|" "$rc|$(sup_fails)"
whole_line "AC-5: and the quoted path is declared" "$AC5_OK"

# The controls. Each leaves the refusal in place, by its whole line - so the
# message still says what an entry must carry - and the partial entries say
# which part is missing (C-4 amendment). The four A-1 rows (finding 4): a line
# names a path only as a whole token that is its first path-like token, and a
# bare rule id counts only where no id is bracketed (C-9); a line that does
# not name the path gets no suffix. <what>|<suffix after SUP_TAIL>|<body>
while IFS='|' read -r what suffix entry; do
  [ -z "$what" ] && continue
  ac5 "$entry"
  assert_eq "AC-5 control, $what: still refused, by the whole line - rc|refusals|line|declared" \
    "1|1|1|0" \
    "$rc|$(sup_nfail)|$(sup_count "$(want_3j "$ac5_c" GREEN src/main.ts 2 eslint-disable "$AC1_LINE" "$suffix")")|$(grep -cF -- 'is declared in ## Suppressions' <<< "$out")"
done <<'ROWS'
an entry inside an HTML comment||## Suppressions\n\n<!-- - `src/main.ts` [eslint-disable] approved by ryan: legacy -->
an entry naming the path but not the rule id| The ## Suppressions line naming 'src/main.ts' is missing the rule id [eslint-disable].|## Suppressions\n\n- `src/main.ts` [noqa] approved by ryan: legacy
an entry naming path and rule id without approved by| The ## Suppressions line naming 'src/main.ts' is missing 'approved by'.|## Suppressions\n\n- `src/main.ts` [eslint-disable]: legacy
an entry for a different path||## Suppressions\n\n- `src/other.ts` [eslint-disable] approved by ryan: legacy
a whole entry outside ## Suppressions||## Notes\n\n- `src/main.ts` [eslint-disable] approved by ryan: legacy
the path only after another path (A-1)||## Suppressions\n\n- src/other.ts [noqa] approved by ryan: same as src/main.ts
the path only after another path, right rule id (A-1)||## Suppressions\n\n- src/other.ts [eslint-disable] approved by ryan: same as src/main.ts
an entry for src/main.ts.bak (A-1)||## Suppressions\n\n- `src/main.ts.bak` [eslint-disable] approved by ryan: legacy
another id bracketed, the right one only bare (A-1)| The ## Suppressions line naming 'src/main.ts' is missing the rule id [eslint-disable].|## Suppressions\n\n- src/main.ts [noqa] approved by ryan: not eslint-disable
ROWS
# The working-tree edits are this describe's alone.
git -C "$FIX" checkout -q -- . 2>/dev/null

# Return 2 (C-9 as amended, round 2 finding 1): a Next.js route-group path.
# Its parentheses are part of the path, so a tokenizer that splits on them
# makes it undeclarable - backticked or bare. Its own branch: a GREEN commit
# adds the AC-1 line to it, then each case rewrites the working-tree story.
ac5_path='app/(auth)/page.tsx'
source_story GREEN "$ac5_path" "$AC1_LINE" </dev/null
AC5_RG="ok    suppression [eslint-disable] in 'app/(auth)/page.tsx' is declared in ## Suppressions"
ac5 '## Suppressions\n\n- `app/(auth)/page.tsx` [eslint-disable] approved by ryan: route group'
assert_eq "AC-5: a route-group path, backticked - rc|refusals" "0|" "$rc|$(sup_fails)"
whole_line "AC-5: and the backticked route-group path is declared" "$AC5_RG"
ac5 '## Suppressions\n\n- app/(auth)/page.tsx [eslint-disable] approved by ryan: route group'
assert_eq "AC-5: a route-group path, bare - rc|refusals" "0|" "$rc|$(sup_fails)"
whole_line "AC-5: and the bare route-group path is declared" "$AC5_RG"
ac5_path=src/main.ts
git -C "$FIX" checkout -q -- . 2>/dev/null

# ---------------------------------------------------------------------------
describe "AC-6: a commit the rule could not judge is said out loud; no judged commit, nothing said"

# The first commit on the branch holds the AC-1 line and no story file, so
# `git show <c>:docs/backlog/stories/T-1.md` fails there: no phase, so no
# verdict. 3i skips such a commit with `continue`; this rule says so (C-1 a),
# and does not count it as clean.
_src_branch
printf '%s\n' "$AC1_LINE" >> "$FIX/src/main.ts"
commit_all "T-1 work before the story file existed"
nostory_c="$(_short)"
_src_story REVIEW src/main.ts
commit_all "T-1 story, at REVIEW"
run_boundaries </dev/null
whole_line "AC-6: the commit with no readable story file is named as not judged" \
  "  commit $nostory_c: story file not readable at this commit; GREEN/GATES additions not judged"
assert_eq "AC-6: and it is neither refused nor counted - rc|refusals|summary" \
  "0||0" "$rc|$(sup_fails)|$(grep -cF -- 'GREEN/GATES added no suppression' <<< "$out")"

# A branch with no GREEN or GATES commit at all: the rule has looked at nothing
# and says nothing - no `ok` over zero commits, which is the vacuous pass. Every
# commit's story file is readable, so there is no note either. PASSES ON
# ARRIVAL: before 3j exists nothing prints these words; see the handoff for
# what earns it.
source_story RED src/main.ts "$AC1_LINE" </dev/null
run_boundaries </dev/null
assert_eq "AC-6: a branch with only RED and REVIEW commits - rc|anything from this rule" \
  "0|" "$rc|$(grep -F -e 'GREEN/GATES' -e 'added a suppression' <<< "$out")"

# ---------------------------------------------------------------------------
describe "HARNESS-082 AC-1: a stub added in GREEN or GATES is refused as stub-throw, by path, line, commit and phase"

# HARNESS-082 (issue #132, second cut) appends four stub rows to 3j's table and
# one two-line matcher, `empty-handler`. Everything else - the walk, the phases,
# the classifier, the refusal text, ## Suppressions - is HARNESS-081's and is
# pinned above. The same spike fixture, the same whole-line refusal (C-4: the
# word "suppression" stays). One branch: a GREEN commit appends the line to
# src/main.ts (line 2 - main's baseline is one line) and a GATES commit appends
# it again (line 3).
STUB_LINE='throw new Error("not implemented")'
source_story GREEN src/main.ts "$STUB_LINE" GATES </dev/null
run_boundaries </dev/null
whole_line "HARNESS-082 AC-1 (GREEN): the refusal names stub-throw, src/main.ts, line 2, the commit and GREEN" \
  "$(want_3j "$sup_c" GREEN src/main.ts 2 stub-throw "$STUB_LINE")"
whole_line "HARNESS-082 AC-1 (GATES): the refusal names stub-throw, src/main.ts, line 3, the commit and GATES" \
  "$(want_3j "$sup_c2" GATES src/main.ts 3 stub-throw "$STUB_LINE")"
assert_eq "HARNESS-082 AC-1: rc|refusals|summary - refused twice, exit 1, and nothing calls it clean" \
  "1|2|0" "$rc|$(sup_nfail)|$(grep -cF -- 'GREEN/GATES added no suppression' <<< "$out")"

# ---------------------------------------------------------------------------
describe "HARNESS-082 AC-3: an empty handler added as two consecutive lines is refused as empty-handler, naming the opener"

# The matcher is C-3's: the previous ADDED line is an opener, the current added
# line is its closer, both in one hunk. The refusal names the OPENER's line
# number and quotes the opener's trimmed text.
#
# Files the describes below need on main, beside src/main.ts's one-line
# baseline: an opener left as context for a closer to be added under it (the
# AC-3 control), three unchanged lines for a two-hunk commit, an abstract method
# whose decorator and def predate the branch (C-3's "added lines only"), and a
# file holding the stubs AC-5 removes. Removed again at the end of this section.
git -C "$FIX" checkout -q main 2>/dev/null
printf 'try {\n  f()\n} catch (e) {\n'                                       > "$FIX/src/handler.ts"
printf 'try:\n    f()\nexcept Exception:\n'                                   > "$FIX/src/handler.py"
printf 'const a = 1\nconst b = 2\nconst c = 3\n'                              > "$FIX/src/twohunk.ts"
printf 'class Shape(ABC):\n    @abstractmethod\n    def area(self):\n'        > "$FIX/src/iface.py"
printf 'fn a() -> u32 {\n    todo!()\n}\nfn b() -> u32 {\n    unimplemented!()\n}\n' > "$FIX/src/stubs.rs"
commit_all "HARNESS-082 baseline: a context opener, a two-hunk file, a pre-existing abstract method, two stubs"

# _nlines <path>   How many lines <path> holds in the fixture's working tree; 0
# when it does not exist yet.
_nlines() { if [ -f "$FIX/$1" ]; then awk 'END { print NR }' "$FIX/$1"; else printf 0; fi; }

# <PHASE>|<path>|<opener>|<closer>, one commit per row, the two lines appended
# consecutively. Every opener and closer spelling C-3 pins: `} catch (e) {`, a
# bare `catch {`, a typed binding, Java's `catch (Exception e) {`, indentation;
# a closer that is a lone `}`, an indented `}` and `} finally {`; `except`
# bare, with a class, with `as`, and a closer of `pass`, `...` and
# `pass  # why`. GATES is in two rows, one per opener kind.
EH_ROWS="$(cat <<'ROWS'
GREEN|src/main.ts|} catch (e) {|}
GREEN|src/app.py|except Exception:|    pass
GATES|src/main.ts|  } catch (e) {|  }
GATES|src/app.py|except Exception:|    pass
GREEN|src/main.ts|catch (e) {|} finally {
GREEN|src/main.ts|catch {|}
GREEN|src/main.ts|} catch (e: unknown) {|}
GREEN|src/main.ts|    catch (Exception e) {|    }
GREEN|src/app.py|except:|    ...
GREEN|src/app.py|    except Foo as e:|        pass  # swallowed on purpose
ROWS
)"
eh_paths="src/main.ts src/app.py src/iface.py src/base.py"
_src_branch
eh_want=()
while IFS='|' read -r ph path opener closer; do
  [ -z "$ph" ] && continue
  _src_story "$ph" "$eh_paths"
  eh_ln=$(( $(_nlines "$path") + 1 ))
  printf '%s\n%s\n' "$opener" "$closer" >> "$FIX/$path"
  commit_all "T-1 $ph adds an empty handler to $path"
  eh_want+=("$ph, '$(_trim "$opener")' then '$(_trim "$closer")' in $path|$(want_3j "$(_short)" "$ph" "$path" "$eh_ln" empty-handler "$(_trim "$opener")")")
done <<< "$EH_ROWS"

# HARNESS-082's return 1 (diff review round 1, finding 1; C-3's amended
# Precedence bullet). An opener whose line ALSO hits a table row is still armed:
# only the closer test is skipped on a hit. So one commit adding the opener and
# its closer draws TWO refusals, both at the opener's line - the row's and
# `empty-handler` - and declaring the row's id does not declare the handler.
# Two entries per commit, so the branch count below counts both. Colon: `noqa`
# on a bare except. Brace: `coverage-ignore` inside a `} ... catch (e) {` line
# that still ENDS in `{` - C-3's brace opener must end in `{`, so a directive
# trailing the brace (`{ // eslint-disable-line`) is not an opener and is not
# this case.
while IFS='|' read -r ph path rid opener closer; do
  [ -z "$ph" ] && continue
  _src_story "$ph" "$eh_paths"
  eh_ln=$(( $(_nlines "$path") + 1 ))
  printf '%s\n%s\n' "$opener" "$closer" >> "$FIX/$path"
  commit_all "T-1 $ph adds an empty handler whose opener carries [$rid] to $path"
  eh_want+=("$ph, '$(_trim "$opener")' then '$(_trim "$closer")' in $path, the row's own refusal [$rid] at the opener|$(want_3j "$(_short)" "$ph" "$path" "$eh_ln" "$rid" "$(_trim "$opener")")")
  eh_want+=("$ph, '$(_trim "$opener")' then '$(_trim "$closer")' in $path, AND empty-handler at the opener although it hit [$rid]|$(want_3j "$(_short)" "$ph" "$path" "$eh_ln" empty-handler "$(_trim "$opener")")")
done <<'ROWS'
GREEN|src/app.py|noqa|except:  # noqa: E722|    pass
GREEN|src/main.ts|coverage-ignore|} /* istanbul ignore next */ catch (e) {|}
ROWS

# C-3's "added lines only", the positive half: a raise added under a decorator
# and def that are already on main is not the abstract-method idiom as far as
# the diff can see, and is refused as stub-raise.
_src_story GREEN "$eh_paths"
eh_ln=$(( $(_nlines src/iface.py) + 1 ))
printf '        raise NotImplementedError\n' >> "$FIX/src/iface.py"
commit_all "T-1 GREEN adds a raise under a decorator that is context"
eh_want+=("stub-raise under a decorator and def that are context|$(want_3j "$(_short)" GREEN src/iface.py "$eh_ln" stub-raise 'raise NotImplementedError')")
# The exclusion needs the DECORATOR, not only the def: a raise under an added
# def with no decorator, and under an added `@staticmethod`, are both refused.
_src_story GREEN "$eh_paths"
printf 'class Base:\n    def f(self):\n        raise NotImplementedError\n' >> "$FIX/src/base.py"
commit_all "T-1 GREEN adds a raise under an undecorated def"
eh_want+=("stub-raise under an added def with no decorator|$(want_3j "$(_short)" GREEN src/base.py 3 stub-raise 'raise NotImplementedError')")
_src_story GREEN "$eh_paths"
printf '    @staticmethod\n    def g():\n        raise NotImplementedError\n' >> "$FIX/src/base.py"
commit_all "T-1 GREEN adds a raise under an added @staticmethod"
eh_want+=("stub-raise under an added @staticmethod and def|$(want_3j "$(_short)" GREEN src/base.py 6 stub-raise 'raise NotImplementedError')")
_src_story REVIEW "$eh_paths"
commit_all "T-1 to review"
run_boundaries </dev/null
for w in "${eh_want[@]}"; do
  whole_line "HARNESS-082 AC-3: ${w%%|*} - refused by its whole line" "${w#*|}"
done
assert_eq "HARNESS-082 AC-3: the handler branch - rc|refusals (one per handler or raise)|summary" \
  "1|${#eh_want[@]}|0" "$rc|$(sup_nfail)|$(grep -cF -- 'GREEN/GATES added no suppression' <<< "$out")"

# ---------------------------------------------------------------------------
describe "HARNESS-082's return 2: a directive on a closer or on a one-line handler does not approve the empty handler, and a two-catch line is refused once"

# HARNESS-082's return 2 (diff review round 2, finding 1 and nice-to-have 2;
# C-3's Precedence bullet, amended clauses (a), (b), (c)). Return 1 closed the
# hole on the OPENER line; these are the other two lines of a handler. A branch
# of its own, so every count above is unchanged and the one below is exact.
#   (a) a directive on the CLOSER: the row's refusal stays at the closer's line,
#       quoting the closer, and empty-handler is printed at the OPENER's line,
#       quoting the opener - two refusals per commit;
#   (b) a directive on a ONE-LINE handler: the winning row's refusal and then
#       empty-handler, both at that line, both quoting it - two per commit, and
#       the directive's first ("after the winning row's");
#   (c) `} catch (A e) {} catch (B e) {` over `}`: the line reports
#       empty-handler through the one-line row AND is armed as an opener; it is
#       refused as empty-handler exactly ONCE. One commit, one refusal.
_src_branch
r2_want=()
# (a) <path>|<rule id>|<opener>|<closer>, one GREEN commit each.
while IFS='|' read -r path rid opener closer; do
  [ -z "$path" ] && continue
  _src_story GREEN "$eh_paths"
  r2_op=$(( $(_nlines "$path") + 1 ))
  printf '%s\n%s\n' "$opener" "$closer" >> "$FIX/$path"
  commit_all "T-1 GREEN adds an empty handler whose closer carries [$rid] to $path"
  r2_want+=("(a) '$(_trim "$opener")' then '$(_trim "$closer")' in $path, the row's own refusal [$rid] at the closer|$(want_3j "$(_short)" GREEN "$path" "$((r2_op + 1))" "$rid" "$(_trim "$closer")")")
  r2_want+=("(a) '$(_trim "$opener")' then '$(_trim "$closer")' in $path, AND empty-handler at the opener although the closer hit [$rid]|$(want_3j "$(_short)" GREEN "$path" "$r2_op" empty-handler "$(_trim "$opener")")")
done <<'ROWS'
src/main.ts|eslint-disable|catch (err) {|} // eslint-disable-line
src/app.py|noqa|except ValueError:|    pass  # noqa: SIM105
ROWS
# (b) <path>|<rule id>|<one-line handler>, one GREEN commit each. The ordering
# pair is kept to assert "after the winning row's".
r2_order=()
while IFS='|' read -r path rid line; do
  [ -z "$path" ] && continue
  _src_story GREEN "$eh_paths"
  r2_ln=$(( $(_nlines "$path") + 1 ))
  printf '%s\n' "$line" >> "$FIX/$path"
  commit_all "T-1 GREEN adds a one-line empty handler carrying [$rid] to $path"
  r2_dir="$(want_3j "$(_short)" GREEN "$path" "$r2_ln" "$rid" "$(_trim "$line")")"
  r2_eh="$(want_3j "$(_short)" GREEN "$path" "$r2_ln" empty-handler "$(_trim "$line")")"
  r2_want+=("(b) '$(_trim "$line")' in $path, the row's own refusal [$rid]|$r2_dir")
  r2_want+=("(b) '$(_trim "$line")' in $path, AND empty-handler at the same line although it hit [$rid]|$r2_eh")
  r2_order+=("'$(_trim "$line")' in $path: [$rid]|$r2_dir|$r2_eh")
done <<'ROWS'
src/main.ts|eslint-disable|} catch {} // eslint-disable-line no-empty
src/app.py|noqa|except OSError: ...  # noqa: S112
ROWS
# (c) the two-catch line over its closer.
_src_story GREEN "$eh_paths"
r2_ln=$(( $(_nlines src/main.ts) + 1 ))
printf '%s\n%s\n' '} catch (IOException e) {} catch (Exception e) {' '}' >> "$FIX/src/main.ts"
commit_all "T-1 GREEN adds a two-catch line whose second catch is opened and closed"
r2_c="$(want_3j "$(_short)" GREEN src/main.ts "$r2_ln" empty-handler '} catch (IOException e) {} catch (Exception e) {')"
_src_story REVIEW "$eh_paths"
commit_all "T-1 to review"
run_boundaries </dev/null
for w in "${r2_want[@]}"; do
  whole_line "HARNESS-082's return 2: ${w%%|*} - refused by its whole line" "${w#*|}"
done
# _r2_at <line>   The number of the first line of $out that equals <line>
# exactly; empty when none. ENVIRON, not -v, so no escape is interpreted.
_r2_at() { R2W="$1" awk '$0 == ENVIRON["R2W"] { print NR; exit }' <<< "$out"; }
for w in "${r2_order[@]}"; do
  what="${w%%|*}"; w="${w#*|}"; r2_d="$(_r2_at "${w%%|*}")"; r2_e="$(_r2_at "${w#*|}")"
  if [ -n "$r2_d" ] && [ -n "$r2_e" ] && [ "$r2_d" -lt "$r2_e" ]; then r2_got=before
  else r2_got="directive at line ${r2_d:-<none>}, empty-handler at line ${r2_e:-<none>}"; fi
  assert_eq "HARNESS-082's return 2 (b): $what - the row's refusal is printed, then empty-handler after it" \
    before "$r2_got"
done
assert_eq "HARNESS-082's return 2 (c): '} catch (IOException e) {} catch (Exception e) {' then '}' is refused as empty-handler exactly once, by its whole line" \
  1 "$(sup_count "$r2_c")"
assert_eq "HARNESS-082's return 2: the branch - rc|refusals (two per (a) and (b) commit, one for (c))|summary" \
  "1|$(( ${#r2_want[@]} + 1 ))|0" "$rc|$(sup_nfail)|$(grep -cF -- 'GREEN/GATES added no suppression' <<< "$out")"

# ---------------------------------------------------------------------------
describe "HARNESS-082's return 3: a directive on a stub line does not approve the stub - every rule a line matches is reported"

# HARNESS-082's return 3 (diff review round 3, finding 1; C-3's Precedence
# bullet, "Every rule a line matches is reported", and C-4 as amended). The
# directive rows come first in the table, so "first row wins" let a directive on
# a stub line hide the stub, and declaring the directive passed the stub. Now
# one refusal per distinct rule id the line matches, in table order. A branch of
# its own, so every count above is unchanged and the one below is exact.
# <path>|<directive id>|<stub id>|<line>: each line matches exactly those two
# rows of today's table and no third (checked by testing every row of
# suppression_needles against each line, gawk and the default awk). One GREEN
# commit per line; two whole-line refusals at that line, the directive's first.
r3_paths="src/app.py src/lib.rs src/main.ts src/player.gd"
_src_branch
r3_want=()
r3_order=()
while IFS='|' read -r path did sid line; do
  [ -z "$path" ] && continue
  _src_story GREEN "$r3_paths"
  r3_ln=$(( $(_nlines "$path") + 1 ))
  printf '%s\n' "$line" >> "$FIX/$path"
  commit_all "T-1 GREEN adds a [$sid] stub carrying [$did] to $path"
  r3_dir="$(want_3j "$(_short)" GREEN "$path" "$r3_ln" "$did" "$(_trim "$line")")"
  r3_stub="$(want_3j "$(_short)" GREEN "$path" "$r3_ln" "$sid" "$(_trim "$line")")"
  r3_want+=("'$(_trim "$line")' in $path, the directive's refusal [$did]|$r3_dir")
  r3_want+=("'$(_trim "$line")' in $path, AND the stub's refusal [$sid] at the same line although it hit [$did]|$r3_stub")
  r3_order+=("'$(_trim "$line")' in $path: [$did] then [$sid]|$r3_dir|$r3_stub")
done <<'ROWS'
src/app.py|no-cover|stub-raise|raise NotImplementedError  # pragma: no cover
src/lib.rs|eslint-disable|stub-todo|let x = todo!(); // eslint-disable-line
src/main.ts|coverage-ignore|stub-throw|throw new Error("not implemented") // istanbul ignore next
src/player.gd|noqa|stub-gd|push_error("not implemented") # noqa
ROWS
# The @abstractmethod exclusion drops ONLY stub-raise: an abstract method whose
# raise carries `# pragma: no cover`, all three lines added in one commit, is
# refused exactly once, for no-cover, at the raise's line.
_src_story GREEN "$r3_paths"
r3_ln=$(( $(_nlines src/app.py) + 3 ))
printf '    @abstractmethod\n    def f(self):\n        raise NotImplementedError  # pragma: no cover\n' >> "$FIX/src/app.py"
commit_all "T-1 GREEN adds an abstract method whose raise carries [no-cover]"
r3_ac="$(_short)"
r3_abs_nc="$(want_3j "$r3_ac" GREEN src/app.py "$r3_ln" no-cover 'raise NotImplementedError  # pragma: no cover')"
r3_abs_sr="$(want_3j "$r3_ac" GREEN src/app.py "$r3_ln" stub-raise 'raise NotImplementedError  # pragma: no cover')"
_src_story REVIEW "$r3_paths"
commit_all "T-1 to review"
run_boundaries </dev/null
for w in "${r3_want[@]}"; do
  whole_line "HARNESS-082's return 3: ${w%%|*} - refused by its whole line" "${w#*|}"
done
for w in "${r3_order[@]}"; do
  what="${w%%|*}"; w="${w#*|}"; r3_d="$(_r2_at "${w%%|*}")"; r3_s="$(_r2_at "${w#*|}")"
  if [ -n "$r3_d" ] && [ -n "$r3_s" ] && [ "$r3_d" -lt "$r3_s" ]; then r3_got=before
  else r3_got="directive at line ${r3_d:-<none>}, stub at line ${r3_s:-<none>}"; fi
  assert_eq "HARNESS-082's return 3: $what - the directive's refusal is printed, then the stub's after it (table order)" \
    before "$r3_got"
done
assert_eq "HARNESS-082's return 3: an @abstractmethod raise carrying '# pragma: no cover' is not refused as stub-raise (whole lines)" \
  0 "$(sup_count "$r3_abs_sr")"
assert_eq "HARNESS-082's return 3: an @abstractmethod raise carrying '# pragma: no cover' is refused as no-cover exactly once, at the raise's line (whole lines)" \
  1 "$(sup_count "$r3_abs_nc")"
assert_eq "HARNESS-082's return 3: the abstract-method commit draws exactly one refusal in all" \
  1 "$(grep -cF -- "commit $r3_ac (GREEN) added a suppression to" <<< "$out")"
assert_eq "HARNESS-082's return 3: the branch - rc|refusals (two per directive-on-stub commit, one for the abstract method)|summary" \
  "1|$(( ${#r3_want[@]} + 1 ))|0" "$rc|$(sup_nfail)|$(grep -cF -- 'GREEN/GATES added no suppression' <<< "$out")"

# AC-4's shape for the new behaviour: the no-cover + stub-raise line with ONLY
# [no-cover] declared. The declaration discharges no-cover and nothing else, so
# the stub is still refused - one refusal, exit 1. A here-string, not a pipe:
# source_story sets $sup_c and $sup_n in THIS shell.
R3_AC4_LINE='raise NotImplementedError  # pragma: no cover'
source_story GREEN src/app.py "$R3_AC4_LINE" \
  <<< $'## Suppressions\n\n- `src/app.py` [no-cover] approved by ryan: coverage tool cannot reach it'
run_boundaries </dev/null
whole_line "HARNESS-082's return 3 AC-4: the declared [no-cover] is accepted" \
  "ok    suppression [no-cover] in 'src/app.py' is declared in ## Suppressions"
whole_line "HARNESS-082's return 3 AC-4: declaring [no-cover] does not declare the stub - refused as stub-raise by its whole line" \
  "$(want_3j "$sup_c" GREEN src/app.py "$sup_n" stub-raise "$R3_AC4_LINE" " The ## Suppressions line naming 'src/app.py' is missing the rule id [stub-raise].")"
assert_eq "HARNESS-082's return 3 AC-4: only [no-cover] declared - rc|refusals" \
  "1|1" "$rc|$(sup_nfail)"

# ---------------------------------------------------------------------------
describe "HARNESS-082 AC-2/AC-3 controls: a handler that pre-existed, has a body or spans hunks, and an abstract method, are clean"

# One branch of GREEN commits, each one C-2 or C-3 says is NOT refused, and the
# claims that make "clean" mean something: exit 0, no FAIL from anywhere, and
# the rule's summary over every commit it judged - a rule that judged nothing
# cannot pass. <what>|<path>|<lines appended in one commit, \n-separated>:
#   - a closer added under an opener that is CONTEXT (AC-3's control), brace
#     and colon;
#   - `except ValueError:` then a statement then `pass` (C-2: the `pass` is the
#     third added line, not the second);
#   - `@abstractmethod` / `def` / `raise NotImplementedError`, all three added
#     (C-3's exclusion), and its `@abc.abstractmethod` / `async def` spelling.
EHC_ROWS="$(cat <<'ROWS'
a brace closer added under a context opener|src/handler.ts|}
a colon closer added under a context opener|src/handler.py|    pass
an except whose next added line is a statement|src/app.py|except ValueError:\n    retries += 1\n    pass
an abstract method, all three lines added|src/shapes.py|class Shape(ABC):\n    @abstractmethod\n    def area(self):\n        raise NotImplementedError
an abc.abstractmethod on an async def, all three lines added|src/shapes.py|    @abc.abstractmethod\n    async def load(self):\n        raise NotImplementedError("subclass")
ROWS
)"
ehc_paths="src/handler.ts src/handler.py src/app.py src/shapes.py src/twohunk.ts"
_src_branch
ehc_n=0
while IFS='|' read -r what path lines; do
  [ -z "$what" ] && continue
  _src_story GREEN "$ehc_paths"
  printf '%b\n' "$lines" >> "$FIX/$path"
  commit_all "T-1 GREEN: $what"
  ehc_n=$((ehc_n+1))
done <<< "$EHC_ROWS"
# Two hunks in ONE commit: the opener added above three unchanged lines, the
# closer below them. Only a hunk header clears the window (C-3), and here one
# sits between the two added lines.
_src_story GREEN "$ehc_paths"
printf '} catch (e) {\nconst a = 1\nconst b = 2\nconst c = 3\n}\n' > "$FIX/src/twohunk.ts"
commit_all "T-1 GREEN: an opener and a closer in two hunks"
ehc_n=$((ehc_n+1))
_src_story REVIEW "$ehc_paths"
commit_all "T-1 to review"
run_boundaries </dev/null
while IFS='|' read -r what path lines; do
  [ -z "$what" ] && continue
  assert_eq "HARNESS-082 control: $what ($path) is not refused" "" \
    "$(grep -F -- "'$path' line" <<< "$out")"
done <<< "$EHC_ROWS"
assert_eq "HARNESS-082 control: an opener and a closer in two hunks of one commit are not refused" "" \
  "$(grep -F -- "'src/twohunk.ts' line" <<< "$out")"
assert_eq "HARNESS-082 controls: the branch - rc|FAIL lines|summary($ehc_n)" \
  "0||1" "$rc|$(grep '^FAIL' <<< "$out")|$(sup_count "$(want_3j_ok "$ehc_n")")"

# ---------------------------------------------------------------------------
describe "HARNESS-082 AC-4: a stub declared in ## Suppressions is accepted by HARNESS-081's hatch"

# Only that a new row discharges through the existing mechanism; the hatch's
# parsing is HARNESS-081's AC-5 and is not re-tested here. A here-string, not a
# pipe: source_story sets $sup_c in THIS shell.
source_story GREEN src/main.ts "$STUB_LINE" \
  <<< $'## Suppressions\n\n- `src/main.ts` [stub-throw] approved by ryan: feature-flagged, the test asserts it throws'
run_boundaries </dev/null
assert_eq "HARNESS-082 AC-4: the declared stub-throw - rc|refusals" "0|" "$rc|$(sup_fails)"
whole_line "HARNESS-082 AC-4: and the rule says the stub is declared" \
  "ok    suppression [stub-throw] in 'src/main.ts' is declared in ## Suppressions"

# ---------------------------------------------------------------------------
describe "HARNESS-082 AC-5: a stub removed is never judged, and the commit is still counted"

# src/stubs.rs holds a todo!() and an unimplemented!() on main. One GREEN
# commit deletes the todo!() line outright; a second replaces the
# unimplemented!() with a value. Both are judged commits; neither adds a stub.
_src_branch
_src_story GREEN src/stubs.rs
printf 'fn a() -> u32 {\n}\nfn b() -> u32 {\n    unimplemented!()\n}\n' > "$FIX/src/stubs.rs"
commit_all "T-1 GREEN removes the todo!() line"
_src_story GREEN src/stubs.rs
printf 'fn a() -> u32 {\n}\nfn b() -> u32 {\n    2\n}\n' > "$FIX/src/stubs.rs"
commit_all "T-1 GREEN replaces the unimplemented!() with a value"
_src_story REVIEW src/stubs.rs
commit_all "T-1 to review"
run_boundaries </dev/null
assert_eq "HARNESS-082 AC-5: a removed todo!() and a replaced unimplemented!() - rc|refusals" \
  "0|" "$rc|$(sup_fails)"
whole_line "HARNESS-082 AC-5: and the summary counts both GREEN commits as judged" "$(want_3j_ok 2)"

# Put main back as the describes above found it.
git -C "$FIX" checkout -q main 2>/dev/null
git -C "$FIX" rm -q --cached src/handler.ts src/handler.py src/twohunk.ts src/iface.py src/stubs.rs >/dev/null 2>&1
rm -f "$FIX/src/handler.ts" "$FIX/src/handler.py" "$FIX/src/twohunk.ts" "$FIX/src/iface.py" "$FIX/src/stubs.rs"
commit_all "HARNESS-082 baseline removed"

# ---------------------------------------------------------------------------
describe "HARNESS-083: a gate loosened in project.conf during GREEN or GATES - the fixture"

# Issue #132, third family. 3j walks GREEN and GATES commits and reads what they
# ADD to source; a lowered floor or a deleted evidence line is not an added
# line, and project.conf classifies as `harness`, which 3j's category test never
# reads. So 3j gains a second per-path branch, by PATH (C-1): it compares the
# file before and after the commit and refuses a loosened gate as
# [gate-loosened], declarable through the same ## Suppressions hatch.
#
# The fixture is 3j's spike (see the comment above _src_story), so `rc 0` means
# something. Every project.conf below is built from REAL lines - this
# repository's own file and the stack profiles under
# .claude/skills/stack-profiles/reference/ - because DV-2's fallback is "the
# fixture corpus is copied from the real file's lines" (C-6). In particular the
# rust profile's coverage gate, the python profile's `--cov-fail-under=`, the
# node profile's evidence/floor/covers/discovery lines, and this repository's
# `slow`, `ondemand` and `task` lines are verbatim apart from the numbers.
#
# No existing assertion moves: no GREEN or GATES fixture commit above touches
# .claude/harness/project.conf (the 3j describes write src/, docs, scripts/x.sh
# and tests/ only), so no `(N commit(s) judged)` count above changes when
# project.conf joins the walk. Main's project.conf here is `BOOTSTRAPPED=no`,
# as the "a harness change bumps the stamp" describe left it; a story branch is
# never asked to bump, so changing it on story/T-1-fixture costs nothing else.
GL_PATH=.claude/harness/project.conf
GL_BASE="$(cat <<'CONF'
# Project quality gates and tasks. THE SINGLE PLACE the harness learns how to
# build, test and run *this* project. Written by the bootstrap story once
# /plan-product has chosen a stack.
#
#   covers | unit        | src/core/**
#   covers | integration | src/render/**

# Set to yes by the bootstrap story once the stack is real.
BOOTSTRAPPED=no

# --- Gates ------------------------------------------------------------------
gate | format    | optional | . | pnpm exec prettier --check .
gate | lint      | required | . | pnpm exec eslint .
gate | unit      | required | . | pnpm exec vitest run
gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80
gate | integration | optional | . | pnpm exec playwright test
gate | build     | required | . | pnpm build
gate | mutation  | optional | . | pnpm exec stryker run

# --- Left out of `gates.sh --fast` ------------------------------------------
slow | integration | needs a browser or a running service; minutes, not seconds
slow | build       | a release bundle, which RED and GREEN have no use for

# --- Evidence of work -------------------------------------------------------
evidence | unit        | Tests +[1-9][0-9]* passed
evidence | coverage    | TOTAL
evidence | integration | [1-9][0-9]* passed
floor    | unit        | 40

# --- What each gate reads ---------------------------------------------------
covers | unit        | src/core/**
covers | unit        | src/platform/**
covers | coverage    | src/core/**
discovery | platform | . | pnpm exec vitest list | grep "src/platform/" > /dev/null

# --- Tasks ------------------------------------------------------------------
task | install | - | . |
task | test    | - | . | pnpm exec vitest run
CONF
)"
# The base's lines that cases below remove or rewrite, by name.
GL_COV='gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80'
GL_EVID='evidence | unit        | Tests +[1-9][0-9]* passed'
GL_FLOOR='floor    | unit        | 40'
GL_SLOWB='slow | build       | a release bundle, which RED and GREEN have no use for'
GL_TASK='task | test    | - | . | pnpm exec vitest run'

# gl_swap <conf> <exact line> <replacement text>   <conf> with the one line that
# equals <exact line> replaced (an empty replacement deletes the line). Pure
# bash on a quoted pattern, so nothing in the line is a regex. A line that is
# not there is a fixture bug, said out loud rather than producing a case whose
# before and after are the same file.
gl_swap() {
  local conf=$'\n'"$1"$'\n' old=$'\n'"$2"$'\n' new
  case "$conf" in *"$old"*) ;; *) printf 'FIXTURE BUG: gl_swap found no line: %s\n' "$2" >&2 ;; esac
  if [ -n "$3" ]; then new=$'\n'"$3"$'\n'; else new=$'\n'; fi
  conf="${conf/"$old"/"$new"}"; conf="${conf#$'\n'}"; printf '%s' "${conf%$'\n'}"
}
# gl_after <conf> <exact line> <line to add>   <conf> with <line to add> placed
# directly after <exact line>.
gl_after() { gl_swap "$1" "$2" "$2"$'\n'"$3"; }

GL_ABSENT='__no project.conf on the before side__'
# conf_story <phase> <before> <after>   C-6's helper, in the shape of
# manifest_story: a branch whose first commit (story at RED, so never judged -
# its parent on main carries no T-1 story) writes <before> as project.conf, or
# deletes the file when <before> is $GL_ABSENT; whose second commit, the story
# at <phase>, writes <after>; and whose last moves the story to REVIEW with the
# body on stdin, which is how a ## Suppressions entry reaches the working-tree
# story. Sets $gl_c, the short form of the <phase> commit. A <before> equal to
# <after> would make that commit change only the story - a control that judges
# nothing - so it is a fixture bug, reported.
conf_story() {
  local phase="$1" before="$2" after="$3" body
  body="$(cat)"
  [ "$before" = "$after" ] && printf 'FIXTURE BUG: conf_story before and after are identical\n' >&2
  _src_branch
  _src_story RED "$GL_PATH"
  if [ "$before" = "$GL_ABSENT" ]; then rm -f "$FIX/$GL_PATH"
  else printf '%s\n' "$before" > "$FIX/$GL_PATH"; fi
  commit_all "T-1 RED: project.conf as it stood before"
  _src_story "$phase" "$GL_PATH"
  printf '%s\n' "$after" > "$FIX/$GL_PATH"
  commit_all "T-1 $phase changes project.conf"
  gl_c="$(_short)"
  _src_story REVIEW "$GL_PATH" "$body"
  commit_all "T-1 to review"
}

# The refusal, as C-1 pins it, byte for byte, and pinned as a WHOLE line.
GL_TAIL=". A gate is never loosened to reach green; if this is deliberate, declare it in ## Suppressions - one line carrying the path, the rule id and 'approved by <who>', with the reason."
# want_gl <commit> <PHASE> <finding> [suffix]   <finding> is `<id>: <what>` (C-2).
want_gl() { printf "FAIL  story T-1: commit %s (%s) loosened a gate in '.claude/harness/project.conf' [gate-loosened]: %s%s%s" "$1" "$2" "$3" "$GL_TAIL" "${4:-}"; }
# gl_fails   Every line this rule printed as a refusal, in order. A here-string.
gl_fails() { grep -F -- 'loosened a gate in' <<< "$out"; }
# gl_refused <what> <PHASE> <finding>   The run just made refused exactly once,
# by this whole line: rc 1, one FAIL line in the whole output, and it is this.
gl_refused() {
  whole_line "$1: refused by the whole line naming '$3'" "$(want_gl "$gl_c" "$2" "$3")"
  assert_eq "$1: and that is the run's only FAIL, so it exits 1 - rc|FAIL lines" \
    "1|1" "$rc|$(grep -c '^FAIL' <<< "$out")"
}
# gl_clean <what>   The run just made refused nothing and exited 0, and 3j
# counted the project.conf commit as judged - so the control is a commit the
# rule READ and passed, not one it never looked at (C-1: such a commit is
# judged; today it is not, which is why the second assertion is red in RED).
gl_clean() {
  assert_eq "$1: not refused - rc|FAIL lines" "0|" "$rc|$(grep '^FAIL' <<< "$out")"
  whole_line "$1: and 3j counts the project.conf commit as judged" "$(want_3j_ok 1)"
}

# The premise, on the eve of the first case: the base conf on a spike branch
# whose GREEN commit only edits a comment is a branch nothing else refuses.
# PASSES ON ARRIVAL, by design - a claim about the fixture, not about 3j.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" '# Set to yes by the bootstrap story once the stack is real.' '# Set to yes by the bootstrap story once the stack is real (it is not yet).')" </dev/null
run_boundaries </dev/null
assert_eq "HARNESS-083 fixture: a spike branch whose GREEN commit edits a project.conf comment exits 0, and nothing objects" \
  "0|" "$rc|$(grep '^FAIL' <<< "$out")"

# ---------------------------------------------------------------------------
describe "HARNESS-083 AC-1: a removed evidence, floor, covers or discovery line is refused, by kind, in GREEN and GATES"

for ph in GREEN GATES; do
  conf_story "$ph" "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_EVID" '')" </dev/null
  run_boundaries </dev/null
  gl_refused "HARNESS-083 AC-1 ($ph): evidence | unit deleted" "$ph" 'unit: evidence line removed'
done

conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_FLOOR" '')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-1: floor | unit deleted" GREEN 'unit: floor line removed'

# One of unit's two covers globs goes; the finding names THAT glob, and the
# other glob, still present, is no finding.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" 'covers | unit        | src/platform/**' '')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-1: covers | unit | src/platform/** deleted" GREEN 'unit: covers line removed src/platform/**'

# discovery's field 2 is a discovery id, not a gate id, and names the finding.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" 'discovery | platform | . | pnpm exec vitest list | grep "src/platform/" > /dev/null' '')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-1: discovery | platform deleted" GREEN 'platform: discovery line removed'

# C-2: `evidence | g | -` declares that no evidence exists - the same weakening.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_EVID" 'evidence | unit        | -')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-1: evidence | unit regex replaced by '-'" GREEN 'unit: evidence line removed'

# ---------------------------------------------------------------------------
describe "HARNESS-083 AC-2: a floor lowered is refused with both numbers; raised or newly added, it is not"

conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_FLOOR" 'floor    | unit        | 12')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-2: floor | unit 40 -> 12" GREEN 'unit: floor lowered 40 -> 12'

# DV-1 mutates the comparison from < to != - this control is what goes red.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_FLOOR" 'floor    | unit        | 60')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-2 control: floor | unit 40 -> 60 (tightening is silent)"

conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" "$GL_FLOOR" 'floor    | coverage    | 40')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-2 control: a floor | coverage line added where none existed"

# C-2: numbers are compared as numbers.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_FLOOR" 'floor    | unit        | 40.0')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-2 control: floor | unit 40 -> 40.0 is the same number"

# ---------------------------------------------------------------------------
describe "HARNESS-083 AC-3: required -> optional and a removed gate are refused; the reverse and a new gate are not"

conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_COV" 'gate | coverage  | optional | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-3: gate | coverage required -> optional" GREEN 'coverage: required -> optional'

# The unit gate removed outright, and every line of it with it - its evidence,
# its floor, both covers globs. C-2: a gate removed reports ONLY `gate removed`.
gl_nounit="$(gl_swap "$GL_BASE" 'gate | unit      | required | . | pnpm exec vitest run' '')"
gl_nounit="$(gl_swap "$gl_nounit" "$GL_EVID" '')"
gl_nounit="$(gl_swap "$gl_nounit" "$GL_FLOOR" '')"
gl_nounit="$(gl_swap "$gl_nounit" 'covers | unit        | src/core/**' '')"
gl_nounit="$(gl_swap "$gl_nounit" 'covers | unit        | src/platform/**' '')"
conf_story GREEN "$GL_BASE" "$gl_nounit" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-3: gate | unit removed with its evidence, floor and covers lines" GREEN 'unit: gate removed'

conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" 'gate | integration | optional | . | pnpm exec playwright test' 'gate | integration | required | . | pnpm exec playwright test')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-3 control: gate | integration optional -> required"

conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" 'gate | lint      | required | . | pnpm exec eslint .' 'gate | typecheck | required | . | pnpm exec tsc --noEmit')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-3 control: a new gate | typecheck line added"

# ---------------------------------------------------------------------------
describe "HARNESS-083 AC-4: a threshold flag lowered in a gate command is refused, per flag; raised, added or unchanged, it is not"

# One row per spelling: <gate line before>|<gate line after>|<finding>. The
# first two are the rust and python profiles' real coverage gates
# (rust-cargo.md line 12, python-uv.md line 11), numbers lowered from 100.
# The rows are TAB-separated because a gate line is full of `|`.
gl_rows="$(printf '%s\t%s\t%s\n' \
  'gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80' \
  'gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 70' \
  'coverage: threshold lowered --fail-under-lines 80 -> 70' \
  'gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=80' \
  'gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=70' \
  'coverage: threshold lowered --cov-fail-under 80 -> 70' \
  'gate | coverage  | required | . | pnpm exec vitest run --coverage --coverage.thresholds.lines=80' \
  'gate | coverage  | required | . | pnpm exec vitest run --coverage --coverage.thresholds.lines=75' \
  'coverage: threshold lowered --coverage.thresholds.lines 80 -> 75' \
  'gate | coverage  | required | . | pnpm exec diff-cover coverage.xml --min-coverage 90' \
  'gate | coverage  | required | . | pnpm exec diff-cover coverage.xml --min-coverage 85' \
  'coverage: threshold lowered --min-coverage 90 -> 85' \
  'gate | lint      | required | . | pnpm exec jscpd src --threshold 5' \
  'gate | lint      | required | . | pnpm exec jscpd src --threshold 3' \
  'lint: threshold lowered --threshold 5 -> 3')"
while IFS=$'\t' read -r gl_b gl_a gl_f; do
  [ -n "$gl_b" ] || continue
  case "$gl_b" in
    'gate | lint '*) gl_old='gate | lint      | required | . | pnpm exec eslint .' ;;
    *)               gl_old="$GL_COV" ;;
  esac
  gl_before="$(gl_swap "$GL_BASE" "$gl_old" "$gl_b")"
  conf_story GREEN "$gl_before" "$(gl_swap "$gl_before" "$gl_b" "$gl_a")" </dev/null
  run_boundaries </dev/null
  gl_refused "HARNESS-083 AC-4: ${gl_f#*lowered }" GREEN "$gl_f"
done <<< "$gl_rows"

# Two flags lowered in one command are two findings, each by its whole line.
gl_two_b='gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80 --fail-under-functions 70'
gl_two_a='gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 75 --fail-under-functions 60'
gl_before="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_two_b")"
conf_story GREEN "$gl_before" "$(gl_swap "$gl_before" "$gl_two_b" "$gl_two_a")" </dev/null
run_boundaries </dev/null
whole_line "HARNESS-083 AC-4: two flags lowered in one command - --fail-under-lines is one finding" \
  "$(want_gl "$gl_c" GREEN 'coverage: threshold lowered --fail-under-lines 80 -> 75')"
whole_line "HARNESS-083 AC-4: two flags lowered in one command - --fail-under-functions is the other" \
  "$(want_gl "$gl_c" GREEN 'coverage: threshold lowered --fail-under-functions 70 -> 60')"
assert_eq "HARNESS-083 AC-4: two flags lowered in one command - rc|FAIL lines" "1|2" "$rc|$(grep -c '^FAIL' <<< "$out")"

# The controls.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_COV" 'gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 90')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-4 control: --fail-under-lines 80 -> 90 (raised)"

gl_before="$(gl_swap "$GL_BASE" "$GL_COV" 'gate | coverage  | required | . | pnpm exec vitest run --coverage')"
conf_story GREEN "$gl_before" "$(gl_swap "$gl_before" 'gate | coverage  | required | . | pnpm exec vitest run --coverage' 'gate | coverage  | required | . | pnpm exec vitest run --coverage --coverage.thresholds.lines=80')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-4 control: --coverage.thresholds.lines=80 added where no flag was"

gl_before="$(gl_swap "$GL_BASE" "$GL_COV" 'gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=80')"
conf_story GREEN "$gl_before" "$(gl_swap "$gl_before" 'gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=80' 'gate | coverage  | required | . | uv run --package app pytest --cov=app --cov-report=term-missing --cov-branch --cov-fail-under=80')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-4 control: a renamed package and a new -- option, --cov-fail-under=80 unchanged"

gl_before="$(gl_swap "$GL_BASE" "$GL_COV" 'gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80.0')"
conf_story GREEN "$gl_before" "$GL_BASE" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-4 control: --fail-under-lines 80.0 -> 80 is the same number"

# ---------------------------------------------------------------------------
describe "HARNESS-083 AC-4, threshold removed: a threshold flag deleted from a gate command is refused, with the number it had"

# C-2's `threshold removed` row (amended in RED, approved by the user): the gate
# exists on both sides, its command had a flag from AC-4's list before and has
# no flag of that name after. Deleting the flag is the same weakening as
# deleting a `floor` line. The "flag added where none was" control above stays:
# a flag present only AFTER is no finding.

# The rust profile's coverage gate (rust-cargo.md line 12), as GL_BASE carries
# it with 80, the flag deleted outright.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_COV" 'gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-4 threshold removed: --fail-under-lines 80 deleted from the rust coverage gate" GREEN 'coverage: threshold removed --fail-under-lines 80'

# The python profile's coverage gate (python-uv.md line 11), verbatim, the `=`
# spelling deleted. The flag is named up to the `[ =]`, the number after it.
gl_py='gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=100'
gl_before="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_py")"
conf_story GREEN "$gl_before" "$(gl_swap "$gl_before" "$gl_py" 'gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-4 threshold removed: --cov-fail-under=100 deleted from the python coverage gate" GREEN 'coverage: threshold removed --cov-fail-under 100'

# Two flags in one command, one deleted and the other lowered: two findings,
# each by its whole line. Their relative order is NOT pinned - C-2's Order
# bullet fixes the before file's LINE order, and both come from one line.
gl_two_b='gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80 --fail-under-functions 70'
gl_two_a='gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-functions 60'
gl_before="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_two_b")"
conf_story GREEN "$gl_before" "$(gl_swap "$gl_before" "$gl_two_b" "$gl_two_a")" </dev/null
run_boundaries </dev/null
whole_line "HARNESS-083 AC-4 threshold removed: one flag deleted, one lowered - --fail-under-lines is removed" \
  "$(want_gl "$gl_c" GREEN 'coverage: threshold removed --fail-under-lines 80')"
whole_line "HARNESS-083 AC-4 threshold removed: one flag deleted, one lowered - --fail-under-functions is lowered" \
  "$(want_gl "$gl_c" GREEN 'coverage: threshold lowered --fail-under-functions 70 -> 60')"
assert_eq "HARNESS-083 AC-4 threshold removed: one flag deleted, one lowered - rc|FAIL lines" "1|2" "$rc|$(grep -c '^FAIL' <<< "$out")"

# Control: the coverage gate removed outright, with every line of it - its
# command carried --fail-under-lines 80, and C-2 says a gate removed reports
# ONLY `gate removed`. A rule that also reported the flag as removed (the gate
# is not on both sides) prints a second FAIL and this goes red on 1|1.
gl_nocov="$(gl_swap "$GL_BASE" "$GL_COV" '')"
gl_nocov="$(gl_swap "$gl_nocov" 'evidence | coverage    | TOTAL' '')"
gl_nocov="$(gl_swap "$gl_nocov" 'covers | coverage    | src/core/**' '')"
conf_story GREEN "$GL_BASE" "$gl_nocov" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-4 threshold removed control: gate | coverage removed outright, flag and all" GREEN 'coverage: gate removed'

# ---------------------------------------------------------------------------
describe "HARNESS-083 AC-5: a slow, ondemand or waiver line added on a gate required BEFORE is refused; on an optional gate it is not"

# The base's existing `slow | build` sits on a required gate on both sides of
# every case in this section, so a line present before is no finding.
conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" "$GL_SLOWB" 'slow | unit        | the suite takes a minute on this runner')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-5: slow | unit added, unit required before" GREEN 'unit: slow added on required gate'

conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" "$GL_SLOWB" 'ondemand | coverage | the instrumented run is too slow to pay per story')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-5: ondemand | coverage added, coverage required before" GREEN 'coverage: ondemand added on required gate'

conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" "$GL_SLOWB" 'waiver | build | the bundler cannot start on this runner yet')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 AC-5: waiver | build added, build required before" GREEN 'build: waiver added on required gate'

# This repository's own line, verbatim, on its own optional mutation gate.
conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" "$GL_SLOWB" 'ondemand | mutation | per-story cost the user declined (HARNESS-015); run it with /audit-mutations')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-5 control: this repository's ondemand | mutation line, on the optional mutation gate"

# ---------------------------------------------------------------------------
describe "HARNESS-083 AC-6: a loosening declared in ## Suppressions is accepted by HARNESS-081's hatch, and only a whole declaration"

# A here-string, not a pipe: conf_story sets $gl_c in THIS shell.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_EVID" '')" \
  <<< $'## Suppressions\n\n- `.claude/harness/project.conf` [gate-loosened] approved by ryan: the suite was split in two'
run_boundaries </dev/null
assert_eq "HARNESS-083 AC-6: the declared evidence removal - rc|refusals" "0|" "$rc|$(gl_fails)"
whole_line "HARNESS-083 AC-6: and the rule says project.conf's [gate-loosened] is declared, once" \
  "ok    suppression [gate-loosened] in '.claude/harness/project.conf' is declared in ## Suppressions"

conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_EVID" '')" \
  <<< $'## Suppressions\n\n- `.claude/harness/project.conf` [noqa] approved by ryan: the wrong rule id'
run_boundaries </dev/null
whole_line "HARNESS-083 AC-6: an entry naming the path with another rule id is refused, saying what it is missing" \
  "$(want_gl "$gl_c" GREEN 'unit: evidence line removed' " The ## Suppressions line naming '.claude/harness/project.conf' is missing the rule id [gate-loosened].")"
assert_eq "HARNESS-083 AC-6: the partial entry - rc|FAIL lines" "1|1" "$rc|$(grep -c '^FAIL' <<< "$out")"

# ---------------------------------------------------------------------------
describe "HARNESS-083 AC-7: a project.conf change that loosens nothing is not refused, and the commit is judged"

# The header's commented example lines are this repository's own header's: deleting
# `#   covers | integration | src/render/**` is a comment edit, not a covers line removed.
gl_cmt="$(gl_swap "$GL_BASE" '# --- Gates ------------------------------------------------------------------' '# --- Gates (reviewed 2026-10-30) ------------------------------------------')"
conf_story GREEN "$GL_BASE" "$(gl_swap "$gl_cmt" '#   covers | integration | src/render/**' '')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-7: a comment edited, and a commented example covers line deleted"

conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" "$GL_TASK" 'task | dev     | - | . | pnpm exec vite')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-7: a task | dev line added"

conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" 'gate | unit      | required | . | pnpm exec vitest run' 'gate | unit      | required | . | pnpm exec vitest run --reporter=verbose')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 AC-7: a gate command changed with no threshold in it"

# C-2: a project.conf missing on the before side - the commit created it -
# produces no findings.
conf_story GREEN "$GL_ABSENT" "$GL_BASE" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 C-2: project.conf created by the GREEN commit, nothing before it"

# ---------------------------------------------------------------------------
describe "HARNESS-083 C-1/C-2: two findings in one commit print in the before-file's line order; the parent-phase arm applies"

# The coverage gate line precedes the floor line in the before file, so its
# finding prints first - though `floor` is a kind an implementation iterating
# kinds might visit first.
gl_after_two="$(gl_swap "$GL_BASE" "$GL_COV" 'gate | coverage  | optional | . | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80')"
gl_after_two="$(gl_swap "$gl_after_two" "$GL_FLOOR" 'floor    | unit        | 12')"
conf_story GREEN "$GL_BASE" "$gl_after_two" </dev/null
run_boundaries </dev/null
assert_eq "HARNESS-083 order: required -> optional, then floor lowered - both whole lines, in the before file's order" \
  "$(want_gl "$gl_c" GREEN 'coverage: required -> optional')"$'\n'"$(want_gl "$gl_c" GREEN 'unit: floor lowered 40 -> 12')" \
  "$(gl_fails)"
assert_eq "HARNESS-083 order: rc|FAIL lines" "1|2" "$rc|$(grep -c '^FAIL' <<< "$out")"

# The documented GATES -> REVIEW step sets the phase and only then commits, so
# the loosening lands in a commit whose own story says REVIEW; judged by its
# parent's phase, as 3j judges source (C-1).
_src_branch
_src_story RED "$GL_PATH"
printf '%s\n' "$GL_BASE" > "$FIX/$GL_PATH"
commit_all "T-1 RED: project.conf as it stood before"
_src_story GATES "$GL_PATH"
commit_all "T-1 to GATES"
_src_story REVIEW "$GL_PATH"
printf '%s\n' "$(gl_swap "$GL_BASE" "$GL_EVID" '')" > "$FIX/$GL_PATH"
commit_all "T-1 to review, with the GATES work still uncommitted"
gl_c="$(_short)"
run_boundaries </dev/null
gl_refused "HARNESS-083 C-1: evidence | unit deleted by the commit that sets REVIEW after GATES" "REVIEW, after GATES" 'unit: evidence line removed'

# Put main back as the describes above found it: no branch here committed to
# main, so there is nothing to undo; leave main checked out.
git -C "$FIX" checkout -q main 2>/dev/null

# ---------------------------------------------------------------------------
describe "HARNESS-083 return 1: project.conf read as gates.sh reads it - any non-required severity, the first evidence line, the lowest repeated flag, a deleted file"

# Return 1 (GATES -> RED), from the diff review's findings 1-4 and C-2's block
# amended at GATES -> REVIEW. No acceptance criterion changed; each case pins
# what gates.sh actually enforces, where the first cut read the file otherwise.

# Severity. gates.sh treats a gate as required only when field 3 is exactly
# `required` (`[ "$req" = "required" ]`, gates.sh 530/821), so ANY other after
# value loosens it, and the finding names the value it became - an empty field
# names nothing, so the finding ends `required -> ` and the refusal's `.`
# follows the space.
gl_covcmd='. | cargo llvm-cov --workspace --no-fail-fast --fail-under-lines 80'
for gl_sev in advisory Required ''; do
  conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_COV" "gate | coverage  | $gl_sev | $gl_covcmd")" </dev/null
  run_boundaries </dev/null
  gl_refused "HARNESS-083 return 1: gate | coverage required -> '$gl_sev'" GREEN "coverage: required -> $gl_sev"
done

# Controls. A gate optional BEFORE is not loosened by any after value (AC-3's
# optional -> required control stands above); and `required` padded with
# spaces trims to `required`, as gates.sh's `field` trims it.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" 'gate | integration | optional | . | pnpm exec playwright test' 'gate | integration | advisory | . | pnpm exec playwright test')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 1 control: gate | integration optional -> advisory (not required before)"

conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_COV" "gate | coverage  |   required   | $gl_covcmd")" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 1 control: gate | coverage 'required' re-padded with spaces is still required"

# Evidence. gates.sh's table_get takes the FIRST evidence line of a gate
# (gates.sh 306-313), so `-` inserted ABOVE an unchanged real line turns the
# unit gate's evidence off while the real line still exists.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_EVID" 'evidence | unit        | -'$'\n'"$GL_EVID")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 1: evidence | unit | - inserted above the unchanged real evidence line" GREEN 'unit: evidence line removed'

# Controls: the first line is still the real regex in both.
conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" "$GL_EVID" 'evidence | unit        | [1-9][0-9]* tests? passed')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 1 control: a second real evidence | unit line added below the first"

conf_story GREEN "$GL_BASE" "$(gl_after "$GL_BASE" "$GL_EVID" 'evidence | unit        | -')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 1 control: evidence | unit | - added BELOW the real line, which stays first"

# Threshold repeated. Parsers disagree on whether the first or the last repeat
# wins (argparse, under pytest-cov, takes the last), so the before value - the
# first occurrence - is compared with the LOWEST occurrence after.
gl_py90='gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90'
gl_before="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_py90")"
conf_story GREEN "$gl_before" "$(gl_swap "$gl_before" "$gl_py90" "$gl_py90 --cov-fail-under=10")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 1: --cov-fail-under=90 repeated as --cov-fail-under=10" GREEN 'coverage: threshold lowered --cov-fail-under 90 -> 10'

conf_story GREEN "$gl_before" "$(gl_swap "$gl_before" "$gl_py90" "$gl_py90 --cov-fail-under=95")" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 1 control: --cov-fail-under=90 repeated as --cov-fail-under=95 (higher)"

# Three occurrences, the lowest in the MIDDLE: neither "first wins" (80) nor
# "last wins" (90) sees it; only the lowest does.
conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_COV" "$GL_COV --fail-under-lines 30 --fail-under-lines 90")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 1: --fail-under-lines 80 repeated as 30 then 90 - the lowest, in the middle" GREEN 'coverage: threshold lowered --fail-under-lines 80 -> 30'

# Deleted. A GREEN commit that removes project.conf is compared with an empty
# after side: one `gate removed` per gate and `discovery line removed` per
# discovery id, in the before file's order - and nothing for the removed gates'
# evidence, floor, covers or slow lines. PASSES ON ARRIVAL (GREEN chose this);
# earned by mutate.sh no-op'ing the deleted-file branch (## Regressions,
# Return 1).
_src_branch
_src_story RED "$GL_PATH"
printf '%s\n' "$GL_BASE" > "$FIX/$GL_PATH"
commit_all "T-1 RED: project.conf as it stood before"
_src_story GREEN "$GL_PATH"
git -C "$FIX" rm -q "$GL_PATH" >/dev/null 2>&1
commit_all "T-1 GREEN deletes project.conf"
gl_c="$(_short)"
_src_story REVIEW "$GL_PATH"
commit_all "T-1 to review"
run_boundaries </dev/null
gl_del=""
for gl_f in 'format: gate removed' 'lint: gate removed' 'unit: gate removed' 'coverage: gate removed' \
            'integration: gate removed' 'build: gate removed' 'mutation: gate removed' 'platform: discovery line removed'; do
  gl_del="$gl_del${gl_del:+$'\n'}$(want_gl "$gl_c" GREEN "$gl_f")"
done
assert_eq "HARNESS-083 return 1: project.conf deleted by a GREEN commit - every gate removed and the discovery line, whole lines in the before file's order" \
  "$gl_del" "$(gl_fails)"
assert_eq "HARNESS-083 return 1: project.conf deleted - rc|FAIL lines (seven gates, one discovery id)" "1|8" "$rc|$(grep -c '^FAIL' <<< "$out")"

git -C "$FIX" checkout -q main 2>/dev/null

# ---------------------------------------------------------------------------
describe "HARNESS-083 return 2: an emptied evidence or floor value, a threshold repeated on the before side, and BOOTSTRAPPED yes -> no"

# Return 2 (GATES -> RED), from the diff review's round-2 findings 1, 3, 4 and 5
# and C-2's block "Amended again at GATES -> REVIEW ... round 2". No acceptance
# criterion changed; each case pins what gates.sh actually enforces.

# Evidence, empty. gates.sh matches an empty regex against every log line
# (`$0 ~ ""`), so an evidence value that trims to empty is no evidence, like
# `-`. Three spellings: a bare `|`, no third field, and spaces after the `|`.
for gl_ev in 'evidence | unit        |' 'evidence | unit' 'evidence | unit        |   '; do
  conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_EVID" "$gl_ev")" </dev/null
  run_boundaries </dev/null
  gl_refused "HARNESS-083 return 2: evidence | unit regex emptied as '$gl_ev'" GREEN 'unit: evidence line removed'
done

# Controls: an empty first evidence line BEFORE is no evidence there, so there
# is nothing to remove - whether the after side leaves it alone (an unrelated
# comment edited) or fills it with a real regex.
gl_e0="$(gl_swap "$GL_BASE" "$GL_EVID" 'evidence | unit        |')"
conf_story GREEN "$gl_e0" "$(gl_swap "$gl_e0" '# Set to yes by the bootstrap story once the stack is real.' '# Set to yes by the bootstrap story once the stack is real (it is not yet).')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 2 control: evidence | unit already empty before, unchanged after (a comment edited)"

conf_story GREEN "$gl_e0" "$(gl_swap "$gl_e0" 'evidence | unit        |' "$GL_EVID")" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 2 control: evidence | unit empty before, a real regex after"

# Threshold repeated BEFORE. argparse (under pytest-cov) takes the last repeat,
# so `=10 =90` enforces 90; the before value is the HIGHEST occurrence, the
# after the LOWEST. Dropping the 90, or swapping the pair so a last-wins parser
# sees 10, are both `90 -> 10`.
gl_py='gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing'
gl_b2="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_py --cov-fail-under=10 --cov-fail-under=90")"
conf_story GREEN "$gl_b2" "$(gl_swap "$gl_b2" "$gl_py --cov-fail-under=10 --cov-fail-under=90" "$gl_py --cov-fail-under=10")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 2: --cov-fail-under=10 --cov-fail-under=90 -> the 90 dropped" GREEN 'coverage: threshold lowered --cov-fail-under 90 -> 10'

conf_story GREEN "$gl_b2" "$(gl_swap "$gl_b2" "$gl_py --cov-fail-under=10 --cov-fail-under=90" "$gl_py --cov-fail-under=90 --cov-fail-under=10")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 2: --cov-fail-under=10 --cov-fail-under=90 -> swapped to =90 =10" GREEN 'coverage: threshold lowered --cov-fail-under 90 -> 10'

# Control: the same repeated pair on both sides, the command otherwise changed.
conf_story GREEN "$gl_b2" "$(gl_swap "$gl_b2" "$gl_py --cov-fail-under=10 --cov-fail-under=90" "$gl_py -q --cov-fail-under=10 --cov-fail-under=90")" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 2 control: --cov-fail-under=10 --cov-fail-under=90 on both sides, -q added"

# BOOTSTRAPPED, read as gates.sh 93-95 reads it: the first line matching
# ^BOOTSTRAPPED=, the text after `=` with all whitespace removed, empty meaning
# `no`. The base is `no`, so these cases start from a `yes` before.
gl_by="$(gl_swap "$GL_BASE" 'BOOTSTRAPPED=no' 'BOOTSTRAPPED=yes')"
conf_story GREEN "$gl_by" "$GL_BASE" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 2: BOOTSTRAPPED=yes -> BOOTSTRAPPED=no" GREEN 'BOOTSTRAPPED: BOOTSTRAPPED yes -> no'

conf_story GREEN "$gl_by" "$(gl_swap "$gl_by" 'BOOTSTRAPPED=yes' '')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 2: the BOOTSTRAPPED=yes line removed reads as no" GREEN 'BOOTSTRAPPED: BOOTSTRAPPED yes -> no'

conf_story GREEN "$gl_by" "$(gl_swap "$gl_by" 'BOOTSTRAPPED=yes' 'BOOTSTRAPPED=')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 2: BOOTSTRAPPED=yes -> BOOTSTRAPPED= (empty reads as no)" GREEN 'BOOTSTRAPPED: BOOTSTRAPPED yes -> no'

# A space BEFORE the `=` no longer matches ^BOOTSTRAPPED=, so gates.sh finds no
# line and reads `no`: a loosening that looks like reformatting.
conf_story GREEN "$gl_by" "$(gl_swap "$gl_by" 'BOOTSTRAPPED=yes' 'BOOTSTRAPPED = yes')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-083 return 2: BOOTSTRAPPED=yes -> 'BOOTSTRAPPED = yes' (no ^BOOTSTRAPPED= line, reads as no)" GREEN 'BOOTSTRAPPED: BOOTSTRAPPED yes -> no'

# Controls: whitespace AFTER the `=` is removed and still reads yes; and the
# reverse flip tightens.
conf_story GREEN "$gl_by" "$(gl_swap "$gl_by" 'BOOTSTRAPPED=yes' 'BOOTSTRAPPED=  yes  ')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 2 control: BOOTSTRAPPED=yes -> 'BOOTSTRAPPED=  yes  ' (whitespace removed, still yes)"

conf_story GREEN "$GL_BASE" "$gl_by" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-083 return 2 control: BOOTSTRAPPED=no -> BOOTSTRAPPED=yes"

# BOOTSTRAPPED prints before every other finding - so the line is moved to the
# END of the file, after the floor line, where the before file's order would
# put it last.
gl_bend="$(gl_swap "$GL_BASE" 'BOOTSTRAPPED=no' '')"
conf_story GREEN "$gl_bend"$'\n''BOOTSTRAPPED=yes' "$(gl_swap "$gl_bend" "$GL_FLOOR" 'floor    | unit        | 12')"$'\n''BOOTSTRAPPED=no' </dev/null
run_boundaries </dev/null
assert_eq "HARNESS-083 return 2: BOOTSTRAPPED yes -> no and a floor lowered - BOOTSTRAPPED first though its line is last, whole lines" \
  "$(want_gl "$gl_c" GREEN 'BOOTSTRAPPED: BOOTSTRAPPED yes -> no')"$'\n'"$(want_gl "$gl_c" GREEN 'unit: floor lowered 40 -> 12')" \
  "$(gl_fails)"
assert_eq "HARNESS-083 return 2: BOOTSTRAPPED and a floor - rc|FAIL lines" "1|2" "$rc|$(grep -c '^FAIL' <<< "$out")"

# Floor, empty. gates.sh treats an empty floor as no floor, so emptying it is
# `floor line removed`, not `floor lowered 40 -> `.
for gl_fl in 'floor    | unit        |' 'floor    | unit' 'floor    | unit        |   '; do
  conf_story GREEN "$GL_BASE" "$(gl_swap "$GL_BASE" "$GL_FLOOR" "$gl_fl")" </dev/null
  run_boundaries </dev/null
  gl_refused "HARNESS-083 return 2: floor | unit 40 emptied as '$gl_fl'" GREEN 'unit: floor line removed'
done

git -C "$FIX" checkout -q main 2>/dev/null

# ---------------------------------------------------------------------------
describe "HARNESS-088: a repeated threshold flag is judged by four statistics, and the refusal names the pair that fell"

# C-2, restated whole by HARNESS-088: per gate and flag name, the FIRST, LAST,
# LOWEST and HIGHEST numbers on each side; a finding when any one is lower
# after, printing `<B> -> <A>` of the first statistic that fell, in that order.
# Every row here is a row of C-2's settled table, its printed pair read off it.
# Each fixture is HARNESS-083's: GL_BASE with one gate line swapped, a GREEN
# commit, gl_refused for a refusal (one whole line, rc 1, the run's only FAIL)
# and gl_clean for a control (rc 0 and the project.conf commit counted judged).

# AC-5. The `lint` gate, its real eslint line replaced by a command that repeats
# `--threshold` three times. Only the MIDDLE value is lowered: first, last and
# lowest are 60 on both sides, so only the highest (90 -> 70) falls. Today
# silent.
gl_lint='gate | lint      | required | . | pnpm exec eslint .'
gl_t3='gate | lint      | required | . | a --threshold 60 && b --threshold 90 && c --threshold 60'
gl_b3="$(gl_swap "$GL_BASE" "$gl_lint" "$gl_t3")"
conf_story GREEN "$gl_b3" "$(gl_swap "$gl_b3" "$gl_t3" 'gate | lint      | required | . | a --threshold 60 && b --threshold 70 && c --threshold 60')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-088 AC-5: --threshold 60 90 60 -> 60 70 60 (only the highest falls)" GREEN 'lint: threshold lowered --threshold 90 -> 70'

# AC-5 controls: the middle value RAISED (only the highest moves, upward), and
# the command unchanged but for an added -q.
conf_story GREEN "$gl_b3" "$(gl_swap "$gl_b3" "$gl_t3" 'gate | lint      | required | . | a --threshold 60 && b --threshold 95 && c --threshold 60')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-088 AC-5 control: --threshold 60 90 60 -> 60 95 60 (the middle raised)"

conf_story GREEN "$gl_b3" "$(gl_swap "$gl_b3" "$gl_t3" 'gate | lint      | required | . | a -q --threshold 60 && b --threshold 90 && c --threshold 60')" </dev/null
run_boundaries </dev/null
gl_clean "HARNESS-088 AC-5 control: --threshold 60 90 60 unchanged, -q added"

# AC-6. The python profile's coverage gate with `=10 =90` -> `=10 =80`: the last
# falls (90 -> 80) and so does the highest; the first and lowest do not. The
# refusal names 90 -> 80, the numbers the commit moved; today it prints the
# highest before against the lowest after, `90 -> 10`.
gl_py='gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing'
gl_b2="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_py --cov-fail-under=10 --cov-fail-under=90")"
conf_story GREEN "$gl_b2" "$(gl_swap "$gl_b2" "$gl_py --cov-fail-under=10 --cov-fail-under=90" "$gl_py --cov-fail-under=10 --cov-fail-under=80")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-088 AC-6: --cov-fail-under=10 =90 -> =10 =80 names the pair that moved" GREEN 'coverage: threshold lowered --cov-fail-under 90 -> 80'

# AC-7. `=90 =10` -> `=80 =10`: the first falls (90 -> 80), and so does the
# highest; last and lowest are 10 on both sides. HARNESS-083's named case.
gl_b9="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_py --cov-fail-under=90 --cov-fail-under=10")"
conf_story GREEN "$gl_b9" "$(gl_swap "$gl_b9" "$gl_py --cov-fail-under=90 --cov-fail-under=10" "$gl_py --cov-fail-under=80 --cov-fail-under=10")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-088 AC-7: --cov-fail-under=90 =10 -> =80 =10 (first and highest fall)" GREEN 'coverage: threshold lowered --cov-fail-under 90 -> 80'

# AC-7, the first arm ALONE. `=90 =10 =95` -> `=80 =10 =95`: last 95, lowest 10
# and highest 95 are unchanged; only the first falls. This is the fixture DV-2
# deletes the first-value disjunct against, and the one that must go red then.
gl_b95="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_py --cov-fail-under=90 --cov-fail-under=10 --cov-fail-under=95")"
conf_story GREEN "$gl_b95" "$(gl_swap "$gl_b95" "$gl_py --cov-fail-under=90 --cov-fail-under=10 --cov-fail-under=95" "$gl_py --cov-fail-under=80 --cov-fail-under=10 --cov-fail-under=95")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-088 AC-7: --cov-fail-under=90 =10 =95 -> =80 =10 =95 (only the first falls)" GREEN 'coverage: threshold lowered --cov-fail-under 90 -> 80'

# C-2's two rows marked "HARNESS-083's C-2 check, unchanged", which no fixture
# above carried. PASS ON ARRIVAL: today's `<highest before> -> <lowest after>`
# happens to name the same pair here. Earned in RED by one mutate.sh run that
# makes the printed pair `<highest before> -> <highest after>` (## Test plan).
# `=90` -> `=90 =10`: the last falls (90 -> 10), and the lowest; first and
# highest stay 90.
gl_b1="$(gl_swap "$GL_BASE" "$GL_COV" "$gl_py --cov-fail-under=90")"
conf_story GREEN "$gl_b1" "$(gl_swap "$gl_b1" "$gl_py --cov-fail-under=90" "$gl_py --cov-fail-under=90 --cov-fail-under=10")" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-088 C-2 row: --cov-fail-under=90 -> =90 =10 (the last falls)" GREEN 'coverage: threshold lowered --cov-fail-under 90 -> 10'

# `80` -> `80 30 90`: first stays 80, the last RISES to 90, the lowest falls to
# 30 - the lowest arm, printing 80 -> 30.
gl_l1='gate | lint      | required | . | a --threshold 80'
gl_bl="$(gl_swap "$GL_BASE" "$gl_lint" "$gl_l1")"
conf_story GREEN "$gl_bl" "$(gl_swap "$gl_bl" "$gl_l1" 'gate | lint      | required | . | a --threshold 80 && b --threshold 30 && c --threshold 90')" </dev/null
run_boundaries </dev/null
gl_refused "HARNESS-088 C-2 row: --threshold 80 -> 80 30 90 (the lowest falls)" GREEN 'lint: threshold lowered --threshold 80 -> 30'

git -C "$FIX" checkout -q main 2>/dev/null

summary "boundaries"
