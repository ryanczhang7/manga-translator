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
boundaries() {
  ( cd "$FIX" && GITHUB_HEAD_REF= PR_HEAD_SHA= bash scripts/check-boundaries.sh main 2>&1 )
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
out="$(boundaries)"
assert_contains "described but not shown" "## Regressions describes something without showing it" "$out"

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
out="$(boundaries)"
assert_contains "shown in a fence" "ok    ## Regressions carries pasted output" "$out"

story_on_branch <<'EOF'
## Regressions

Corrected the AC-4 helper, which was too slow for the coverage gate. Before and
after, both under `bash scripts/gates.sh --gate coverage`:

    AC-4 property test   4,275 ms  ->  367 ms

Thresholds, seeds and numRuns untouched; the measured statistics are identical.
EOF
out="$(boundaries)"
assert_contains "shown as an indented measurement" "ok    ## Regressions carries pasted output" "$out"

# The section is optional. A story that never returned to RED omits it, and
# the template's own commented-out block is not a claim about anything.
story_on_branch <<'EOF'
## Notes

One clean cycle.
EOF
out="$(boundaries)"
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
out="$(boundaries)"
case "$out" in
  *"## Regressions"*) _bad "an untouched template block is not a claim" "complained anyway: $out" ;;
  *) _ok "an untouched template block is not a claim" ;;
esac

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
out="$( cd "$FIX" && GITHUB_HEAD_REF=story/T-1-fixture PR_HEAD_SHA= bash scripts/check-boundaries.sh main 2>&1 )"
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
out="$(boundaries)"
assert_contains "a commit carrying GATES is refused" "a PR should be opened from REVIEW or DONE" "$out"

# ---------------------------------------------------------------------------
describe "the same rule covers gate probes"

story_on_branch <<'EOF'
## Gate probes

Broke the import boundary and the lint gate failed, as expected. Reverted.
EOF
out="$(boundaries)"
assert_contains "a gate probe described but not shown" "## Gate probes describes something without showing it" "$out"

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
out="$(boundaries)"
assert_contains "changed criteria with no amendment" "## Acceptance criteria differ from main" "$out"


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
story_blocked() { # <phase> ; body on stdin
  local phase="$1" extra; extra="$(cat)"
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
    printf -- '---\nid: T-1\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: %s\nbranch: story/T-1-fixture\n---\n\n' "$phase"
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
out="$(boundaries)"
assert_contains "a blocked gate at REVIEW with the decision recorded" "recorded gate result: blocked" "$out"
assert_contains "and the gate is named as pending CI" "types" "$out"
case "$out" in
  *"recorded gate result is 'blocked"*) _bad "and it is not refused" "refused anyway: $out" ;;
  *) _ok "and it is not refused" ;;
esac

story_blocked REVIEW <<'EOF'
Ran the gates. One of them did not work on this machine.
EOF
out="$(boundaries)"
assert_contains "a blocked gate with nothing written down is refused" "pending CI" "$out"

story_blocked DONE <<'EOF'
1. PO decision: types is BLOCKED locally by Smart App Control. Marking it
   pending CI.
EOF
out="$(boundaries)"
assert_contains "DONE needs more than pending: it needs the CI run" "has not been verified on CI" "$out"

story_blocked DONE <<'EOF'
1. PO decision: types was BLOCKED locally by Smart App Control (os error 4551).
2. types passed on CI: https://github.com/o/r/actions/runs/412 - "Tests 47 passed".
EOF
out="$(boundaries)"
assert_contains "DONE with the CI run quoted is accepted" "verified on CI" "$out"

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
out="$(boundaries)"
assert_contains "a recorded failure is still refused" "recorded gate result is 'fail" "$out"


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
out="$(boundaries)"
assert_contains "no phase owns it" "names no phase" "$out"

# Naming the phase is half of it. A block that names GATES and reaches the PR
# with nothing recorded is the failure K6 describes exactly: a commitment that
# outlived the phase that owed it.
story_on_branch <<'EOF'
## Deferred verifications

1. Drop a field from the encoder; AC-1's property must fail. RED cannot run
   this - there is no encoder to mutate. Owner: GATES.
EOF
out="$(boundaries)"
assert_contains "named, owned, and never run" "no result and no waiver" "$out"

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
out="$(boundaries)"
assert_contains "run, with the failure shown" "ok    ## Deferred verifications carries its result" "$out"

# Waived: the story decided not to run it, in writing. A waiver is a decision
# somebody can argue with later, which is the whole difference between it and
# silence.
story_on_branch <<'EOF'
## Deferred verifications

1. Owner: GATES. WAIVED - the encoder this control mutates moved to WORLD-010
   with the criterion it belonged to, so there is nothing here to break.
EOF
out="$(boundaries)"
assert_contains "waived in writing" "ok    ## Deferred verifications carries an explicit waiver" "$out"

# And the section is optional: most stories defer nothing, and a story that
# omits it is not asked about it.
story_on_branch <<'EOF'
## Notes

Nothing deferred.
EOF
out="$(boundaries)"
case "$out" in
  *"Deferred verifications"*) _bad "silent when the section is absent" "said something about it: $out" ;;
  *) _ok "silent when the section is absent" ;;
esac

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
bnd_harness() { ( cd "$FIX" && GITHUB_HEAD_REF= PR_HEAD_SHA= bash scripts/check-boundaries.sh main 2>&1 ); }

# Baseline: main carries a stamp, and the fixture is the unbootstrapped
# template.
git -C "$FIX" checkout -q main 2>/dev/null
printf '2026-01-01\n' > "$FIX/.claude/harness/VERSION"
printf 'BOOTSTRAPPED=no\n' > "$FIX/.claude/harness/project.conf"
commit_all "baseline stamp"

printf 'touched by a harness change\n' >> "$FIX/.claude/hooks/lib.sh"
harness_branch </dev/null
out="$(bnd_harness)"
assert_contains "a harness change with a stale stamp is refused" "does not bump" "$out"

printf 'touched again\n' >> "$FIX/.claude/hooks/lib.sh"
harness_branch <<'EOF'
2026-02-02
EOF
out="$(bnd_harness)"
assert_contains "bumping it satisfies the check" "ok    harness version bumped" "$out"

# Downstream safety, both halves. A bootstrapped project editing .claude/ on a
# non-story branch is not upstream and has nothing to stamp.
git -C "$FIX" checkout -q main 2>/dev/null
printf 'BOOTSTRAPPED=yes\n' > "$FIX/.claude/harness/project.conf"
commit_all "bootstrapped now"
printf 'a project edit\n' >> "$FIX/.claude/hooks/lib.sh"
harness_branch </dev/null
out="$(bnd_harness)"
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
out="$(bnd_harness)"
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
out="$(boundaries)"
case "$out" in
  *"does not bump"*) _bad "a story branch is never asked to bump" "the bootstrap story would be refused: $out" ;;
  *) _ok "a story branch is never asked to bump" ;;
esac
summary "boundaries"
