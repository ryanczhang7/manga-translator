#!/usr/bin/env bash
# HARNESS-008 - one phase lock per worktree, so two stories can be in flight.
#
# THE CLAIM THIS SUITE PINS
#
# `.claude/state/current-story.env` holds ONE story and ONE phase, and every
# hook reads it. Two stories in one checkout is one file and two truths. But a
# git worktree has its own working directory, and `.claude/state/*` is
# gitignored, so each worktree already carries its own lock, its own gate stamp
# and its own copy of every story file. Nothing is shared but `.git`. The story
# measured that before it was written; this suite reproduces the measurement
# and pins what has to stay true when two worktrees are live.
#
# REAL WORKTREES, NEVER A COPIED DIRECTORY. The whole claim is about what git
# does with `.git`: a `cp -r` of the fixture has a `.git` of its own and would
# pass every assertion here while proving nothing about worktrees. So the
# fixture is one main checkout plus two LINKED worktrees made with
# `git worktree add`, the suite asserts they share the main checkout's `.git`
# before anything else runs, and the trap removes them through git.
#
# ---------------------------------------------------------------------------
# WHAT IS ASSERTED WHERE
#
#   premise  the measurement in the story's ## Context, against THIS repository:
#            the state file and the gate stamp are gitignored, the README that
#            documents them is not, and a linked worktree shares the main
#            checkout's `.git` (which is what makes it a worktree and not a copy).
#   AC-1     a story set in one worktree is invisible to `phase.sh show` in the
#            other and in the main checkout; the first still reports its own.
#            Control: a second story set in the second worktree leaves the
#            first's state file AND its story frontmatter untouched.
#   AC-2     with RED in one worktree, GREEN beside it and a THIRD story in RED
#            in the main checkout, the SAME source write attempted in all three
#            at the same moment is refused in RED - naming THAT tree's story and
#            phase - and allowed in GREEN. Control: the symmetric test-file write
#            is refused in GREEN and allowed in RED, so "the GREEN worktree allows
#            everything" cannot satisfy this. The main checkout's story is what
#            makes the probe bite: a hook that read the shared `.git`'s parent
#            would find a real phase there, refuse in GREEN and name T-M.
#   AC-3     gates.sh run in one worktree stamps that worktree's state and that
#            worktree's story file only; check-boundaries.sh in each judges its
#            own tree. Control: the other worktree, put in REVIEW without a gate
#            run, is refused for having no tool-written record.
#   AC-4     doctor.sh prints a `worktree` line: `main checkout` in the main
#            checkout, `linked worktree of <path>` in a linked one, and MISSING
#            naming both releases when the linked worktree's harness is not the
#            main checkout's. Controls: no MISSING line while they match, exit 0
#            then and exit 1 on a mismatch. THIS DOES NOT EXIST YET: it is the
#            block that must be red on arrival.
#   AC-5     refresh-harness.sh run inside a linked worktree works on that
#            worktree alone - measured in RED, not assumed: it exits 0, stamps
#            that worktree with upstream's release, delivers a file upstream
#            ships, and leaves the other worktree's and the main checkout's
#            VERSION byte-identical. Then the AC-4 line reports the mismatch the
#            refresh just produced.
#
#   AC-6 (CLAUDE.md documents the workflow) is a deferred verification owned by
#   REVIEW and is deliberately not asserted here: a grep for a phrase pins the
#   phrasing, not the guidance.
#
# NEEDLES. Every match on captured output is anchored at line start and counted
# with awk over a here-string - no `| grep -q`, which under this suite's pipefail
# returns 141 when the reader leaves early, and no `grep -c ... || printf 0`.
# A row's status column is read, never the presence of a word anywhere.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"     # the MAIN checkout
UP="$(make_project_fixture)"      # a stand-in newer upstream, for AC-5
WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
WA="$WORK/a"; WB="$WORK/b"        # the two LINKED worktrees
cleanup() {
  git -C "$FIX" worktree remove --force "$WA" >/dev/null 2>&1
  git -C "$FIX" worktree remove --force "$WB" >/dev/null 2>&1
  rm -rf "$WORK" "$FIX" "$UP"
}
trap cleanup EXIT

# count <regex> <text>   How many lines of <text> match <regex>. The regex goes
# through ARGV rather than -v so that a backslash in it is not re-read as an
# escape; the text goes through a here-string, not a pipe.
count() {
  awk 'BEGIN { re = ARGV[1]; ARGV[1] = "" } $0 ~ re { n++ } END { print n + 0 }' "$1" <<< "$2"
}

# run_in <dir> <command...>   Run a command from inside a worktree, capturing
# both streams. Every script under test locates its tree from its own path, so
# "which worktree" is decided by which copy of the script runs.
#
# GITHUB_HEAD_REF AND PR_HEAD_SHA ARE CLEARED, and that is the whole reason this
# is a function rather than a bare subshell. check-boundaries.sh:179 reads
#
#     br="${GITHUB_HEAD_REF:-$(git rev-parse --abbrev-ref HEAD)}"
#
# deliberately, so that on CI it can name the PR's branch from a detached merge
# commit. Inside this suite that is poison: the fixture worktrees are on
# story/T-A-fixture and story/T-B-fixture, but a run under Actions inherits the
# REAL branch being built, so check-boundaries looks for that story, finds none
# in the fixture, and SKIPS its story checks. It then exits 0 having asserted
# nothing - so the AC-3 control, which needs worktree b to be REFUSED, was
# satisfied by a run that never judged anything.
#
# Measured: this suite is 73/0 on a developer machine and 69/4 under Actions,
# and setting GITHUB_HEAD_REF alone reproduces the CI result locally, exactly.
# The four reds are the assertions that read check-boundaries' verdict.
#
# Cleared for EVERY command, not just check-boundaries: these two are the only
# ambient variables any harness script reads (verified by grep over scripts/
# and .claude/hooks/), and a fixture is never the CI checkout, so there is no
# case where inheriting one is correct.
run_in() {
  local d="$1"; shift
  ( cd "$d" && unset GITHUB_HEAD_REF PR_HEAD_SHA && "$@" 2>&1 )
}

# first_version <tree>   The release stamp as doctor.sh reads it: the first
# non-comment line of .claude/harness/VERSION. CR stripped, because this
# machine's autocrlf checks worktrees out CRLF and the comparison is exact.
first_version() {
  awk '!/^[[:space:]]*#/ && !/^[[:space:]]*$/ && !done { sub(/\r$/, ""); print; done = 1 }' \
    "$1/.claude/harness/VERSION" 2>/dev/null
}

# fm <file> <key>   One frontmatter value, CR stripped.
fm() {
  awk -v k="$2" 'NR == 1 && /^---/ { inf = 1; next }
    inf && /^---/ { exit }
    inf && index($0, k ":") == 1 { s = substr($0, length(k) + 2); sub(/^[ \t]+/, "", s); sub(/\r$/, "", s); print s; exit }' "$1"
}

exists() { [ -e "$1" ] && printf yes || printf no; }

# A chore story, so that check-boundaries.sh does not demand a ## Handoff of
# the fixture. Branch names follow phase.sh's default, which is what each
# worktree is checked out on.
wt_story() { # <tree> <id> [branch]
  printf -- '---\nid: %s\ntitle: Fixture story\nslug: fixture\ntype: chore\nstatus: todo\nphase: PLANNED\nbranch: %s\n---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Gate results\n\n## Notes\n' \
    "$2" "${3:-story/$2-fixture}" > "$1/docs/backlog/stories/$2.md"
}

# --- the fixture: one main checkout, two linked worktrees ---------------------
# The real ignore rule for runtime state, so that the fixture's worktrees stand
# or fall on the same line this repository does.
printf '.claude/state/*\n!.claude/state/.gitkeep\n!.claude/state/README.md\n' >> "$FIX/.gitignore"
wt_story "$FIX" T-A
wt_story "$FIX" T-B
write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  1 passed (1)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "two stories" >/dev/null 2>&1
MAINBR="$(git -C "$FIX" rev-parse --abbrev-ref HEAD)"
git -C "$FIX" worktree add -q -b story/T-A-fixture "$WA" HEAD >/dev/null 2>&1
git -C "$FIX" worktree add -q -b story/T-B-fixture "$WB" HEAD >/dev/null 2>&1

# The upstream for AC-5: the same harness, one release later, with a hook this
# tree does not have - a marker that can be followed into exactly one worktree.
printf '99 (2099-01-01)\n' > "$UP/.claude/harness/VERSION"
printf '#!/usr/bin/env bash\n# marker shipped by the upstream fixture\n' > "$UP/.claude/hooks/__upstream_marker.sh"
git -C "$UP" add -A >/dev/null 2>&1
git -C "$UP" -c user.email=t@t -c user.name=t commit -qm "a release later" >/dev/null 2>&1

# ---------------------------------------------------------------------------
describe "premise: the measurement the story rests on, reproduced"

# Against THIS repository, read-only. The story's claim is "the lock is already
# per-worktree because .claude/state/* is gitignored"; if the rule went, the
# state would be committable and a worktree could inherit another's phase
# through a commit. check-boundaries.sh refuses a TRACKED state file; this pins
# the rule that keeps it from becoming one.
#
# `--no-index`, so the RULES are asked and not the index. Without it a tracked
# file is never reported ignored whatever the rules say, and the README control
# below was green with its negation line deleted - satisfied by the file being
# tracked, which is not what its name claims.
git -C "$REPO_ROOT" check-ignore -q --no-index .claude/state/current-story.env 2>/dev/null; rc=$?
assert_eq "this repository ignores .claude/state/current-story.env" 0 "$rc"
git -C "$REPO_ROOT" check-ignore -q --no-index .claude/state/last-gate-run 2>/dev/null; rc=$?
assert_eq "and .claude/state/last-gate-run" 0 "$rc"
# The rule has an exception, and the assertion above would be satisfied by
# ignoring the whole directory: the file that documents it is negated back in.
git -C "$REPO_ROOT" check-ignore -q --no-index .claude/state/README.md 2>/dev/null; rc=$?
assert_eq "but not the README that documents the directory" 1 "$rc"

# A worktree and not a copy: both linked trees resolve their common git
# directory to the main checkout's `.git`, and their own git directory is
# somewhere else. A copied directory has `.git` of its own and fails both.
main_git="$(cd "$FIX/.git" && pwd)"
for wt in "$WA" "$WB"; do
  common="$(cd "$wt" && cd "$(git rev-parse --git-common-dir)" && pwd)"
  own="$(cd "$wt" && cd "$(git rev-parse --git-dir)" && pwd)"
  assert_eq "$(basename "$wt"): shares the main checkout's .git" "$main_git" "$common"
  case "$own" in
    "$main_git") _bad "$(basename "$wt"): has its own git dir, so it is linked, not main" "git-dir is the common dir: $own" ;;
    *) _ok "$(basename "$wt"): has its own git dir, so it is linked, not main" ;;
  esac
done
assert_eq "git lists three worktrees" 3 "$(count '.' "$(git -C "$FIX" worktree list)")"
# The linked worktrees start with NO runtime state at all - the measurement
# from the story, on the fixture. The lock is off in both until somebody sets
# a story there.
assert_eq "a fresh linked worktree has no state file" no "$(exists "$WA/.claude/state/current-story.env")"

# ---------------------------------------------------------------------------
describe "AC-1: a story set in one worktree is invisible to the other"

out="$(run_in "$WA" bash scripts/phase.sh set T-A RED)"; rc=$?
assert_eq "T-A goes to RED in worktree a, on its own branch, without --force" 0 "$rc"
assert_eq "and phase.sh says so" 1 "$(count '^T-A -> RED$' "$out")"

out="$(run_in "$WB" bash scripts/phase.sh show)"
assert_eq "phase.sh show in worktree b reports no active story" \
  "No active story. The phase lock is off." "$out"
out="$(run_in "$FIX" bash scripts/phase.sh show)"
assert_eq "and so does the main checkout" \
  "No active story. The phase lock is off." "$out"
out="$(run_in "$WA" bash scripts/phase.sh show)"
assert_eq "worktree a still reports T-A" 1 "$(count '^  STORY_ID=T-A$' "$out")"
assert_eq "in RED" 1 "$(count '^  PHASE=RED$' "$out")"

# Control: a second story in the second worktree. Neither overwrites the other,
# in the state file OR in the story file phase.sh rewrites alongside it - each
# worktree has its own copy of docs/backlog/stories/*.md too.
out="$(run_in "$WB" bash scripts/phase.sh set T-B GREEN)"; rc=$?
assert_eq "T-B goes to GREEN in worktree b" 0 "$rc"
out="$(run_in "$WA" bash scripts/phase.sh show)"
assert_eq "worktree a is unchanged: still T-A" 1 "$(count '^  STORY_ID=T-A$' "$out")"
assert_eq "still RED" 1 "$(count '^  PHASE=RED$' "$out")"
assert_eq "and never mentions T-B" 0 "$(count 'T-B' "$out")"
out="$(run_in "$WB" bash scripts/phase.sh show)"
assert_eq "worktree b reports T-B" 1 "$(count '^  STORY_ID=T-B$' "$out")"
assert_eq "in GREEN" 1 "$(count '^  PHASE=GREEN$' "$out")"
assert_eq "the main checkout still has no state file" no "$(exists "$FIX/.claude/state/current-story.env")"
assert_eq "a's story file says RED"                 RED     "$(fm "$WA/docs/backlog/stories/T-A.md" phase)"
assert_eq "b's copy of the same story file does not" PLANNED "$(fm "$WB/docs/backlog/stories/T-A.md" phase)"
assert_eq "b's story file says GREEN"               GREEN   "$(fm "$WB/docs/backlog/stories/T-B.md" phase)"
assert_eq "a's copy of that one does not"           PLANNED "$(fm "$WA/docs/backlog/stories/T-B.md" phase)"

# ---------------------------------------------------------------------------
describe "AC-2: each worktree's write is judged against ITS OWN phase"

# A third story, in the MAIN checkout, on its own branch: three trees, three
# phases, one `.git`. Its story file is written into the main checkout only
# (untracked there; the worktrees were cut before it existed), which is the
# ordinary shape of a story started after the worktrees were made.
wt_story "$FIX" T-M "$MAINBR"
out="$(run_in "$FIX" bash scripts/phase.sh set T-M RED)"; rc=$?
assert_eq "T-M goes to RED in the main checkout" 0 "$rc"

# The same source write, attempted in all three trees AT THE SAME MOMENT: three
# hook processes in flight together, each pointed at its own tree. The hook
# reads the state file under CLAUDE_PROJECT_DIR, which is what a session in
# that tree sets.
( guard_bash "$WA"  "printf x > src/main.ts" > "$WORK/guard-a" ) &
( guard_bash "$WB"  "printf x > src/main.ts" > "$WORK/guard-b" ) &
( guard_bash "$FIX" "printf x > src/main.ts" > "$WORK/guard-m" ) &
wait
ga="$(cat "$WORK/guard-a")"; gb="$(cat "$WORK/guard-b")"; gm="$(cat "$WORK/guard-m")"
case "$ga" in
  "") _bad "the RED worktree refuses the source write" "not blocked at all" ;;
  *"path:     src/main.ts "*) _ok "the RED worktree refuses the source write" ;;
  *) _bad "the RED worktree refuses the source write" "blocked, but not on src/main.ts: $ga" ;;
esac
# ITS OWN story and phase in the refusal - not a neighbour's, not the main
# checkout's.
case "$ga" in *"story:    T-A "*) _ok "and the refusal names T-A" ;; *) _bad "and the refusal names T-A" "$ga" ;; esac
case "$ga" in *"phase:    RED "*) _ok "and RED" ;; *) _bad "and RED" "$ga" ;; esac
assert_eq "the GREEN worktree beside it allows the same write" "" "$gb"
case "$gm" in *"story:    T-M "*) _ok "the main checkout refuses it too, naming T-M" ;; *) _bad "the main checkout refuses it too, naming T-M" "${gm:-not blocked at all}" ;; esac

# Control: the mirror image. A TEST write is refused in GREEN and allowed in
# RED, so a hook that simply allowed everything in worktree b would fail here.
assert_blocked "$WB" "printf x > tests/main.test.ts" tests/main.test.ts "the GREEN worktree refuses a test write"
assert_allowed "$WA" "printf x > tests/main.test.ts" "the RED worktree allows the same test write"
# And the tool path, not only the Bash heuristics.
assert_eq "Write to source in RED is refused" \
  1 "$(count 'category: source' "$(guard "$WA" Write file_path src/main.ts)")"
assert_eq "Write to source in GREEN is allowed" "" "$(guard "$WB" Write file_path src/main.ts)"

# The main checkout's story has done its job; the blocks below are about the
# two linked worktrees, and AC-5's refresh must not find the main checkout
# mid-cycle under a probe that points the refresh at it.
run_in "$FIX" bash scripts/phase.sh clear >/dev/null
rm -f "$FIX/docs/backlog/stories/T-M.md"

# ---------------------------------------------------------------------------
describe "AC-3: the gate record belongs to the worktree that ran the gates"

run_in "$WA" bash scripts/phase.sh set T-A REVIEW >/dev/null
out="$(run_in "$WA" bash scripts/gates.sh)"; rc=$?
assert_eq "gates.sh runs in worktree a" 0 "$rc"
assert_eq "and records into a's story file" 1 "$(count '^recorded in docs/backlog/stories/T-A.md' "$out")"

assert_eq "the stamp is written in worktree a"        yes "$(exists "$WA/.claude/state/last-gate-run")"
assert_eq "and says pass" 1 "$(count '^RESULT=pass$' "$(tr -d '\r' < "$WA/.claude/state/last-gate-run")")"
assert_eq "worktree b has no stamp"                   no  "$(exists "$WB/.claude/state/last-gate-run")"
assert_eq "the main checkout has no stamp"            no  "$(exists "$FIX/.claude/state/last-gate-run")"
assert_eq "a's story file carries the tree hash"      1 "$(count '^    tree:   [0-9a-f]+' "$(cat "$WA/docs/backlog/stories/T-A.md")")"
assert_eq "b's copy of the same story file does not"  0 "$(count '^    tree:   [0-9a-f]+' "$(cat "$WB/docs/backlog/stories/T-A.md")")"
assert_eq "nor does the main checkout's"              0 "$(count '^    tree:   [0-9a-f]+' "$(cat "$FIX/docs/backlog/stories/T-A.md")")"

# check-boundaries.sh in each judges its own tree. The base is the fixture's
# default branch, which both story branches were cut from.
out="$(run_in "$WA" bash scripts/check-boundaries.sh "$MAINBR")"; rc=$?
assert_eq "check-boundaries in a accepts the record it finds" 0 "$rc"
assert_eq "and says the record matches a's tree" 1 "$(count '^ok    gate record matches the working tree' "$out")"
assert_eq "for story T-A" 1 "$(count '^ok    story T-A is in REVIEW$' "$out")"

# Control: the gate run in a does not satisfy b. Put b's story in REVIEW too,
# without running the gates there, and check-boundaries must refuse it for the
# record it does NOT have - not accept it for the one a has.
run_in "$WB" bash scripts/phase.sh set T-B REVIEW >/dev/null
out="$(run_in "$WB" bash scripts/check-boundaries.sh "$MAINBR")"; rc=$?
assert_eq "check-boundaries in b refuses" 1 "$rc"
assert_eq "because b has no tool-written record" 1 \
  "$(count '^FAIL  story T-B: ## Gate results was not written by scripts/gates.sh' "$out")"
assert_eq "and never claims a's record matches" 0 "$(count '^ok    gate record matches' "$out")"
assert_eq "it judged T-B, not T-A" 0 "$(count 'story T-A' "$out")"

# ---------------------------------------------------------------------------
describe "AC-4: doctor names the worktree it is in, and whether its release matches"

# The contract's three lines, in doctor's existing `ok`/`MISSING` column style:
#
#     ok       worktree     main checkout, harness 46
#     ok       worktree     linked worktree of <path>, harness 46
#     MISSING  worktree     linked worktree, harness 44 - main checkout is 46
#
# The release number is read from the fixture's own stamp, so this does not
# go stale on a bump. What follows the number is not constrained: `45` and
# `45 (2026-09-20)` both satisfy `harness 45([^0-9]|$)`; `450` does not.
hv="$(first_version "$FIX")"; num="${hv%% *}"

out="$(run_in "$WA" bash scripts/doctor.sh)"; rc=$?
assert_eq "a linked worktree is named as one, with its release" 1 \
  "$(count "^  ok       worktree +linked worktree of [^,]+, harness $num([^0-9]|$)" "$out")"
assert_eq "and not as the main checkout" 0 "$(count '^  ok       worktree +main checkout' "$out")"
assert_eq "no mismatch is reported while the releases match" 0 "$(count '^  MISSING  worktree' "$out")"
assert_eq "and doctor exits 0" 0 "$rc"

out="$(run_in "$FIX" bash scripts/doctor.sh)"; rc=$?
assert_eq "the main checkout is named as one, with its release" 1 \
  "$(count "^  ok       worktree +main checkout, harness $num([^0-9]|$)" "$out")"
assert_eq "and not as a linked worktree" 0 "$(count 'linked worktree' "$out")"
assert_eq "and exits 0" 0 "$rc"

# Two worktrees on different releases. Written directly rather than via
# refresh-harness.sh here, so that this block does not depend on AC-5; the
# refresh-produced instance is asserted at the end of AC-5.
printf '44 (2026-09-01)\n' > "$WA/.claude/harness/VERSION"
out="$(run_in "$WA" bash scripts/doctor.sh)"; rc=$?
assert_eq "a linked worktree behind the main checkout is MISSING, naming both releases" 1 \
  "$(count "^  MISSING  worktree +linked worktree.*harness 44([^0-9]|$).*main checkout is $num([^0-9]|$)" "$out")"
assert_eq "and is not also reported ok" 0 "$(count '^  ok       worktree' "$out")"
assert_eq "and doctor exits 1 on the mismatch" 1 "$rc"
out="$(run_in "$FIX" bash scripts/doctor.sh)"
assert_eq "the main checkout reads its own stamp, not the linked worktree's" 1 \
  "$(count "^  ok       worktree +main checkout, harness $num([^0-9]|$)" "$out")"
git -C "$WA" checkout -q -- .claude/harness/VERSION

# ---------------------------------------------------------------------------
describe "AC-5: refresh-harness.sh inside a linked worktree works on that worktree alone"

# Measured in RED, not assumed: the script's tree is `$(pwd)`, every path it
# writes is under it, and a linked worktree shares nothing with its neighbours
# but `.git`. So the outcome pinned is "works on that worktree alone", and the
# AC's control for it - the other worktree's VERSION is unchanged - is asserted
# against both the other worktree and the main checkout.
#
# Precondition, as for any refresh: between stories, clean tree. a's REVIEW
# frontmatter and gate record from AC-3 are discarded, not committed.
run_in "$WA" bash scripts/phase.sh clear >/dev/null
git -C "$WA" checkout -q -- .
before_b="$(first_version "$WB")"; before_m="$(first_version "$FIX")"

out="$(run_in "$WA" bash scripts/refresh-harness.sh "$UP")"; rc=$?
assert_eq "the refresh completes" 0 "$rc"
assert_eq "worktree a is stamped with upstream's release" "99 (2099-01-01)" "$(first_version "$WA")"
assert_eq "a hook upstream ships arrives in worktree a" yes "$(exists "$WA/.claude/hooks/__upstream_marker.sh")"
assert_eq "worktree b's VERSION is unchanged"           "$before_b" "$(first_version "$WB")"
assert_eq "the main checkout's VERSION is unchanged"    "$before_m" "$(first_version "$FIX")"
assert_eq "worktree b did not receive the hook"         no "$(exists "$WB/.claude/hooks/__upstream_marker.sh")"
assert_eq "nor did the main checkout"                   no "$(exists "$FIX/.claude/hooks/__upstream_marker.sh")"

# The state AC-4 exists for: "two worktrees on different releases is a state
# the refresh procedure can produce and nothing currently reports". It just
# did. Now something reports it - in the worktree that moved, and not in the
# main checkout, which is still on its own release.
out="$(run_in "$WA" bash scripts/doctor.sh)"; rc=$?
assert_eq "doctor in the refreshed worktree reports the mismatch the refresh produced" 1 \
  "$(count "^  MISSING  worktree +linked worktree.*harness 99([^0-9]|$).*main checkout is $num([^0-9]|$)" "$out")"
assert_eq "and exits 1" 1 "$rc"
out="$(run_in "$FIX" bash scripts/doctor.sh)"
assert_eq "doctor in the main checkout still reports its own release as ok" 1 \
  "$(count "^  ok       worktree +main checkout, harness $num([^0-9]|$)" "$out")"

summary "worktree"
