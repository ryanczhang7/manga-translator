#!/usr/bin/env bash
# Tests for scripts/selftest-needed.sh (HARNESS-075): does this story's diff
# touch a path `classify.sh` calls `harness`? `run` (exit 0) when it does, or
# when the diff cannot be computed; `skip` (exit 1) when it does not.
#
# THE LINES ARE READ OUT, NOT DERIVED (story, Contract, "Output"). Every
# expected line below is written out whole, with the em dash, and compared
# WHOLE with assert_eq: `selftest-needed: run` is a prefix of the fail-toward-
# run lines too, so a floating `run` needle would be satisfied by the script
# failing to compute anything. The only value read from the fixture is the
# merge-base's short SHA, via `git rev-parse --short` on the ref the fixture
# itself arranged - never via the script's own enumeration.
#
# EVERY CASE IS RUN TWICE: from the fixture root and from its `src/`
# subdirectory, because the script must `cd` to the top level first (Contract,
# "Changed set"). A script that ran `git diff` relative to the cwd would list
# the same paths but `ls-files --others` would not, and a subdirectory run is
# what tells them apart.
#
# THE CONTROLS. The AC-2 skip and the AC-1 mixed diff differ by exactly one
# committed path, `scripts/z.sh`, so a run/skip decided by count (or by "any
# change at all") cannot pass both. The explicit-base and origin/main cases each
# carry a second reading against the other ref, which must give the OTHER
# answer - that is what makes "the ref was used" observable.
#
# THE RED SHAPE. scripts/selftest-needed.sh does not exist in RED, so every
# `bash <script>` exits 127 with empty stdout. One named assertion says so
# first; every case runs regardless, and every assertion is unconditional, so
# the executed count is the same in RED and GREEN.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
FIXES=()
cleanup() { local f; rm -rf "$WORK"; for f in "${FIXES[@]}"; do rm -rf "$f"; done; }
trap cleanup EXIT

# --- fixture helpers ----------------------------------------------------------

gitc() { git -C "$d" -c user.email=t@t -c user.name=t "$@"; }

# new_fixture   d := a fresh make_project_fixture, its one commit on `main`.
new_fixture() {
  d="$(make_project_fixture)"; FIXES+=("$d")
  gitc branch -M main >/dev/null 2>&1
}

# story_branch   Check out a story branch at the current HEAD.
story_branch() { gitc checkout -q -b story/T-1-fixture >/dev/null 2>&1; }

# put <rel> [content]   Write a file in the fixture, making its directory.
put() {
  mkdir -p "$(dirname "$d/$1")"
  printf '%s\n' "${2:-x}" > "$d/$1"
}

# commit_all <msg>
commit_all() { gitc add -A >/dev/null 2>&1; gitc commit -qm "$1" >/dev/null 2>&1; }

# short <ref>   The ref's short SHA, as `git rev-parse --short` prints it.
short() { gitc rev-parse --short "$1" 2>/dev/null; }

CEIL=""   # GIT_CEILING_DIRECTORIES for the run; empty = none

# run_sn <cwd> [args...]   Runs the fixture's copy of the script from <cwd>.
# RC := exit status, OL := stdout lines (CR stripped), FIRST := OL[0],
# NOUT := stdout line count, ERR := stderr.
run_sn() {
  local cwd="$1" i; shift
  ( cd "$cwd" && GIT_CEILING_DIRECTORIES="$CEIL" bash "$SN" "$@" ) >"$WORK/o" 2>"$WORK/e"
  RC=$?
  OL=(); mapfile -t OL < "$WORK/o"
  for i in "${!OL[@]}"; do OL[$i]="${OL[$i]%$'\r'}"; done
  NOUT="${#OL[@]}"; FIRST="${OL[0]-}"
  ERR=""; [ -s "$WORK/e" ] && ERR="$(cat "$WORK/e")"
}

# expect <label> <rc> <line> <quiet:yes|no> [args...]   Run from the fixture
# root and from src/, and assert each time: the exit status, the whole first
# line, exactly one stdout line, and - when <quiet> is yes, the run/skip paths -
# nothing on stderr (Contract, "Output").
expect() {
  local label="$1" rc="$2" line="$3" quiet="$4" where cwd
  shift 4
  for where in root subdir; do
    cwd="$d"; [ "$where" = subdir ] && cwd="$d/$SUBDIR"
    run_sn "$cwd" "$@"
    assert_eq "$label [from $where]: exits $rc" "$rc" "$RC"
    assert_eq "$label [from $where]: the first line is exactly the pinned line" "$line" "$FIRST"
    assert_eq "$label [from $where]: stdout is exactly one line" 1 "$NOUT"
    [ "$quiet" = yes ] && assert_eq "$label [from $where]: nothing on stderr" "" "$ERR"
  done
  return 0
}

SUBDIR=src
D='—'   # the em dash the Contract pins
CI_TAIL='; CI runs the self-test on the PR'

# ---------------------------------------------------------------------------
describe "the script exists"

assert_eq "scripts/selftest-needed.sh exists in this repository" \
  "" "$([ -f "$REPO_ROOT/scripts/selftest-needed.sh" ] || printf 'missing')"

# ---------------------------------------------------------------------------
describe "AC-1: a harness path among the story's changes answers run, exit 0"

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put scripts/x.sh '#!/usr/bin/env bash'; commit_all "add x"
expect "a COMMITTED new scripts/x.sh answers run and names it" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): scripts/x.sh" yes

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put .claude/tests/project-x.test.sh 'true'; gitc add .claude/tests/project-x.test.sh >/dev/null 2>&1
expect "an UNCOMMITTED (staged) .claude/tests/project-x.test.sh answers run and names it" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): .claude/tests/project-x.test.sh" yes

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put .github/workflows/ci.yml 'on: push'
expect "an UNTRACKED .github/workflows/ci.yml answers run and names it" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): .github/workflows/ci.yml" yes

new_fixture; SN="$d/scripts/selftest-needed.sh"
put CLAUDE.md '# rules'; commit_all "add CLAUDE.md"; story_branch
put CLAUDE.md '# rules, edited'
expect "an unstaged edit to CLAUDE.md answers run and names it" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): CLAUDE.md" yes

new_fixture; SN="$d/scripts/selftest-needed.sh"
put scripts/y.sh '#!/usr/bin/env bash'; commit_all "add y"; story_branch
rm -f "$d/scripts/y.sh"
expect "a DELETED scripts/y.sh answers run and names it: classification is by path" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): scripts/y.sh" yes

# The mixed diff, and AC-2's control: the AC-2 skip's six paths plus one
# committed harness path. An ignored untracked file sits beside them and is not
# a changed path (ls-files --exclude-standard).
mixed_paths() {
  put src/app.ts 'export const a = 1'
  put src/app.test.ts 'test("a", () => {})'
  put docs/wiki/x.md '# x'
  put package.json '{}'
  put .dockerignore '.claude'
  put vendor/lib.js 'module.exports = 1'
}
new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
mixed_paths; put scripts/z.sh '#!/usr/bin/env bash'; commit_all "mixed"
put node_modules/pkg/index.js 'ignored'
expect "a mixed diff whose ONLY harness path is scripts/z.sh, beside source, test, docs, manifest, config and vendor paths, answers run (AC-2's control)" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): scripts/z.sh" yes

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put scripts/c.sh; put scripts/a.sh; put scripts/b.sh; commit_all "three"
expect "exactly three harness paths are all listed, in sort order, with no \`+N more\`" 0 \
  "selftest-needed: run $D 3 harness path(s) changed against main (merge-base $(short main)): scripts/a.sh, scripts/b.sh, scripts/c.sh" yes

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put scripts/d.sh; put scripts/c.sh; put scripts/a.sh; put scripts/b.sh; commit_all "four"
expect "four harness paths list the first three in sort order, then \`, +1 more\`" 0 \
  "selftest-needed: run $D 4 harness path(s) changed against main (merge-base $(short main)): scripts/a.sh, scripts/b.sh, scripts/c.sh, +1 more" yes

# ---------------------------------------------------------------------------
describe "AC-2: no harness path among the changes answers skip, exit 1"

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
mixed_paths; commit_all "no harness"
put node_modules/pkg/index.js 'ignored'
expect "source, test, docs, manifest, config and vendor paths only (and an ignored untracked file) answer skip with the count and the base" 1 \
  "selftest-needed: skip $D no harness path among 6 changed path(s) against main (merge-base $(short main))$CI_TAIL" yes

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
expect "a branch with no changes at all answers skip with \`0 changed path(s)\`" 1 \
  "selftest-needed: skip $D no harness path among 0 changed path(s) against main (merge-base $(short main))$CI_TAIL" yes

# ---------------------------------------------------------------------------
describe "AC-3: when the diff cannot be computed, it answers run, exit 0"

new_fixture; SN="$d/scripts/selftest-needed.sh"
gitc branch -M trunk >/dev/null 2>&1; story_branch
put src/app.ts 'export const a = 1'; commit_all "source only"
expect "neither origin/main nor main resolves: run, saying so" 0 \
  "selftest-needed: run $D cannot compute the diff: no origin/main or main to compare against; defaulting to run" no

# An unrelated-history `main`: a root commit of the empty tree, made with
# plumbing so the story branch's checkout is never disturbed.
new_fixture; SN="$d/scripts/selftest-needed.sh"
gitc branch -M story/T-1-fixture >/dev/null 2>&1
put src/app.ts 'export const a = 1'; commit_all "source only"
empty_tree="$(gitc mktree </dev/null 2>/dev/null)"
unrelated="$(gitc commit-tree "$empty_tree" -m unrelated 2>/dev/null)"
gitc update-ref refs/heads/main "$unrelated" >/dev/null 2>&1
assert_eq "precondition: main exists and shares no history with the story branch" \
  "1:1" "$(gitc rev-parse --verify -q main >/dev/null 2>&1 && printf 1):$(gitc merge-base main HEAD >/dev/null 2>&1 || printf 1)"
expect "main resolves but \`git merge-base\` fails: run, naming the base" 0 \
  "selftest-needed: run $D cannot compute the diff: no merge base with main; defaulting to run" no

# Not a git checkout: the scripts, hooks and confs, with no .git anywhere up
# to the ceiling.
nd="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"; FIXES+=("$nd")
mkdir -p "$nd/.claude" "$nd/$SUBDIR"
cp -r "$REPO_ROOT/scripts" "$nd/scripts"
cp -r "$REPO_ROOT/.claude/hooks" "$nd/.claude/hooks"
cp -r "$REPO_ROOT/.claude/harness" "$nd/.claude/harness"
CEIL="$(dirname "$nd")"
assert_eq "precondition: the directory is not inside any git checkout" \
  "no" "$(cd "$nd" && GIT_CEILING_DIRECTORIES="$CEIL" git rev-parse --show-toplevel >/dev/null 2>&1 && printf yes || printf no)"
d="$nd"; SN="$d/scripts/selftest-needed.sh"
expect "outside any git checkout: run, saying so" 0 \
  "selftest-needed: run $D cannot compute the diff: not a git checkout; defaulting to run" no
CEIL=""

# ---------------------------------------------------------------------------
describe "AC-3: an explicit base ref is used in place of the resolution"

# main has moved past `release` with a harness commit; the story branch adds a
# source file. Against main: one changed path, no harness (skip). Against
# release: the harness commit too (run). The two refs give different answers.
new_fixture; SN="$d/scripts/selftest-needed.sh"
gitc branch release >/dev/null 2>&1
put scripts/x.sh '#!/usr/bin/env bash'; commit_all "harness on main"
story_branch; put src/app.ts 'export const a = 1'; commit_all "source"
expect "\`selftest-needed.sh release\` diffs against release and says \`against release\`" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against release (merge-base $(short release)): scripts/x.sh" yes release
expect "control: the same fixture with no argument resolves main and gives the other answer" 1 \
  "selftest-needed: skip $D no harness path among 1 changed path(s) against main (merge-base $(short main))$CI_TAIL" yes

# ---------------------------------------------------------------------------
describe "AC-3: origin/main is preferred over main when both resolve"

# origin/main is a plain ref one commit behind main (no network). Against
# origin/main the harness commit on main is in the diff (run); against main it
# is not (skip).
new_fixture; SN="$d/scripts/selftest-needed.sh"
behind="$(gitc rev-parse HEAD 2>/dev/null)"
put scripts/x.sh '#!/usr/bin/env bash'; commit_all "harness on main"
gitc update-ref refs/remotes/origin/main "$behind" >/dev/null 2>&1
story_branch; put src/app.ts 'export const a = 1'; commit_all "source"
expect "with both refs present and no argument, origin/main is the base" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against origin/main (merge-base $(short origin/main)): scripts/x.sh" yes
expect "control: \`selftest-needed.sh main\` on the same fixture gives the other answer" 1 \
  "selftest-needed: skip $D no harness path among 1 changed path(s) against main (merge-base $(short main))$CI_TAIL" yes main

# ---------------------------------------------------------------------------
describe "Contract: a second argument, or a \`-\`-prefixed one, is a usage error, exit 2"

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
run_sn "$d" main extra
assert_eq "two arguments exit 2" 2 "$RC"
assert_eq "two arguments print nothing on stdout" 0 "$NOUT"
assert_eq "two arguments say why on stderr" yes "$([ -n "$ERR" ] && printf yes || printf no)"
run_sn "$d" --help
assert_eq "a \`-\`-prefixed argument exits 2" 2 "$RC"
assert_eq "a \`-\`-prefixed argument prints nothing on stdout" 0 "$NOUT"
assert_eq "a \`-\`-prefixed argument says why on stderr" yes "$([ -n "$ERR" ] && printf yes || printf no)"

# ---------------------------------------------------------------------------
# HARNESS-075, Return 1 (GATES -> RED, from the diff review, findings 1-4).
# Four wrong-way skips the cases above could not see: the script called by a
# RELATIVE path, a rename, git itself failing, and a non-ASCII name. Every
# other case calls the script by absolute path, so these are the only ones
# that do not.

describe "AC-1 / Contract: called by a relative path from inside the checkout, it still answers run"

new_fixture; story_branch
put scripts/x.sh '#!/usr/bin/env bash'; commit_all "add x"
REL_LINE="selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): scripts/x.sh"
for rel in "src|../scripts/selftest-needed.sh" "scripts|selftest-needed.sh"; do
  SN="${rel#*|}"; run_sn "$d/${rel%%|*}"
  assert_eq "\`bash $SN\` from ${rel%%|*}/ exits 0" 0 "$RC"
  assert_eq "\`bash $SN\` from ${rel%%|*}/: the first line is exactly the line the root call gives" "$REL_LINE" "$FIRST"
  assert_eq "\`bash $SN\` from ${rel%%|*}/: stdout is exactly one line" 1 "$NOUT"
  assert_eq "\`bash $SN\` from ${rel%%|*}/: nothing on stderr" "" "$ERR"
done

describe "AC-1: a renamed harness file counts under its OLD name too"

# tools/ is not a harness path (classify.sh calls tools/r.sh `source`), so the
# rename's destination alone answers skip; its source, scripts/r.sh, is the
# one harness path.
new_fixture; SN="$d/scripts/selftest-needed.sh"
put scripts/r.sh '#!/usr/bin/env bash'; commit_all "add r"; story_branch
mkdir -p "$d/tools"; gitc mv scripts/r.sh tools/r.sh >/dev/null 2>&1; commit_all "move r"
assert_eq "precondition: the rename's destination, tools/r.sh, is not a harness path in the fixture" \
  "source" "$(cd "$d" && bash scripts/classify.sh tools/r.sh 2>/dev/null | awk -F'\t' '{ print $1 }')"
expect "a committed \`git mv scripts/r.sh tools/r.sh\` answers run and names scripts/r.sh" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): scripts/r.sh" yes

describe "AC-3 / PO decision 3: when git itself fails to list the changes, it answers run"

# A staged harness file, then an index git cannot read: `git diff` and
# `git ls-files` both fail, while rev-parse and merge-base still work. The
# reason text between the prefix and the suffix is the implementer's.
new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put scripts/new.sh '#!/usr/bin/env bash'; gitc add scripts/new.sh >/dev/null 2>&1
printf garbage > "$d/.git/index"
assert_eq "precondition: \`git diff\` fails on the corrupted index" \
  "fails" "$(gitc diff --name-only main >/dev/null 2>&1 && printf works || printf fails)"
GF_PRE="selftest-needed: run $D cannot compute the diff: "
GF_SUF="; defaulting to run"
for where in root subdir; do
  cwd="$d"; [ "$where" = subdir ] && cwd="$d/$SUBDIR"
  run_sn "$cwd"
  assert_eq "a corrupted index [from $where]: exits 0" 0 "$RC"
  assert_eq "a corrupted index [from $where]: the first line begins \`cannot compute the diff: \`" "$GF_PRE" "${FIRST:0:${#GF_PRE}}"
  assert_eq "a corrupted index [from $where]: the first line ends \`; defaulting to run\`" "$GF_SUF" \
    "$([ "${#FIRST}" -ge "${#GF_SUF}" ] && printf '%s' "${FIRST: -${#GF_SUF}}")"
  assert_eq "a corrupted index [from $where]: stdout is exactly one line" 1 "$NOUT"
done

describe "AC-1: a harness path with a non-ASCII name is seen, and named as the filesystem names it"

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
CAFE='.claude/tests/project-café.test.sh'
put "$CAFE" 'true'
assert_eq "precondition: the file exists under its UTF-8 name" "yes" "$([ -f "$d/$CAFE" ] && printf yes || printf no)"
expect "an UNTRACKED $CAFE answers run and names it unquoted" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): $CAFE" yes

# ---------------------------------------------------------------------------
# HARNESS-077: the wrong-way skips HARNESS-075's second diff review left open
# (findings 1-3). Each case has a harness change on the branch, so the only
# correct answers are `run` - and every one of them answers `skip` (or exits
# 1 silently) against the HARNESS-075 script except AC-2, which passes on
# arrival and is earned by the story's DV-2 mutation.
#
# gf_run <cwd> [env...]   Runs the fixture's script from <cwd>, with optional
# `VAR=value` words set for its environment only; sets RC, FIRST, NOUT, ERR as
# run_sn does. gf_assert <label> <where>   Asserts the fail-toward-run SHAPE:
# exit 0, GF_PRE prefix, GF_SUF suffix, one line. The reason text between them
# is the implementer's; stderr is asserted only by the AC-1 case.
gf_run() {   # <cwd> [env...]
  local cwd="$1" i; shift
  ( cd "$cwd" && env "$@" bash "$SN" ) >"$WORK/o" 2>"$WORK/e"
  RC=$?
  OL=(); mapfile -t OL < "$WORK/o"
  for i in "${!OL[@]}"; do OL[$i]="${OL[$i]%$'\r'}"; done
  NOUT="${#OL[@]}"; FIRST="${OL[0]-}"
  ERR=""; [ -s "$WORK/e" ] && ERR="$(cat "$WORK/e")"
}
gf_assert() {   # <label> <where>
  assert_eq "$1 [from $2]: exits 0" 0 "$RC"
  assert_eq "$1 [from $2]: the first line begins \`cannot compute the diff: \`" "$GF_PRE" "${FIRST:0:${#GF_PRE}}"
  assert_eq "$1 [from $2]: the first line ends \`; defaulting to run\`" "$GF_SUF" \
    "$([ "${#FIRST}" -ge "${#GF_SUF}" ] && printf '%s' "${FIRST: -${#GF_SUF}}")"
  assert_eq "$1 [from $2]: stdout is exactly one line" 1 "$NOUT"
}

describe "HARNESS-077 AC-1: a lib.sh that trips \`set -u\` when sourced answers run, and its error reaches stderr"

# The fixture's COPY of lib.sh is test data: a line reading an unset variable
# goes in as its line 2. Rewritten with awk, not `sed -i` (GNU-only).
new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put scripts/x.sh '#!/usr/bin/env bash'; commit_all "add x"
FLIB="$d/.claude/hooks/lib.sh"
awk 'NR == 2 { print "echo \"$NOPE_UNSET\"" } { print }' "$FLIB" > "$WORK/lib.sh" && cat "$WORK/lib.sh" > "$FLIB"
assert_eq "precondition: sourcing the fixture's lib.sh under \`set -u\` in a subshell fails" \
  "fails" "$( ( set -u; . "$FLIB" ) >/dev/null 2>&1 && printf loads || printf fails)"
for where in root subdir; do
  cwd="$d"; [ "$where" = subdir ] && cwd="$d/$SUBDIR"
  gf_run "$cwd"
  gf_assert "a lib.sh with an unbound variable on line 2" "$where"
  assert_eq "a lib.sh with an unbound variable on line 2 [from $where]: stderr is not empty" \
    "non-empty" "$([ -n "$ERR" ] && printf non-empty || printf empty)"
  assert_contains "a lib.sh with an unbound variable on line 2 [from $where]: stderr names the unbound variable" \
    "NOPE_UNSET" "$ERR"
done

describe "HARNESS-077 AC-2: a COMMITTED harness path with a non-ASCII name is seen, and named unquoted"

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put "$CAFE" 'true'; commit_all "café"
assert_eq "precondition: the file exists under its UTF-8 name" "yes" "$([ -f "$d/$CAFE" ] && printf yes || printf no)"
assert_eq "precondition: the commit holds it under its UTF-8 name, and nothing else is changed or untracked" \
  "$CAFE|" "$(gitc -c core.quotePath=false diff --name-only main HEAD 2>/dev/null)|$(gitc status --porcelain 2>/dev/null)"
expect "a COMMITTED $CAFE answers run and names it unquoted" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): $CAFE" yes

describe "HARNESS-077 AC-3(a): with paths.conf missing, a harness change answers run, not a misfiled skip"

new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put scripts/x.sh '#!/usr/bin/env bash'; commit_all "add x"
rm -f "$d/.claude/harness/paths.conf"
assert_eq "precondition: the fixture's .claude/harness/paths.conf is gone" \
  "gone" "$([ -e "$d/.claude/harness/paths.conf" ] && printf present || printf gone)"
assert_eq "precondition: without it, the fixture's classify.sh misfiles scripts/x.sh as source" \
  "source" "$(cd "$d" && bash scripts/classify.sh scripts/x.sh 2>/dev/null | awk -F'\t' '{ print $1 }')"
for where in root subdir; do
  cwd="$d"; [ "$where" = subdir ] && cwd="$d/$SUBDIR"
  gf_run "$cwd"
  gf_assert "paths.conf missing" "$where"
done

describe "HARNESS-077 AC-3(b): a classify pipeline that exits non-zero answers run, not skip"

# The contrivance, confined to the one invocation: a fake `awk` first on PATH,
# exiting 2. $WORK is a POSIX path (mktemp), so it holds no `:` to split PATH.
new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
put scripts/x.sh '#!/usr/bin/env bash'; commit_all "add x"
mkdir -p "$WORK/fakebin"
printf '#!/usr/bin/env bash\nexit 2\n' > "$WORK/fakebin/awk"; chmod +x "$WORK/fakebin/awk"
assert_eq "precondition: with the fake first on PATH, \`awk 'BEGIN{}'\` exits 2" \
  2 "$(PATH="$WORK/fakebin:$PATH" awk 'BEGIN{}' >/dev/null 2>&1; printf '%s' "$?")"
for where in root subdir; do
  cwd="$d"; [ "$where" = subdir ] && cwd="$d/$SUBDIR"
  gf_run "$cwd" PATH="$WORK/fakebin:$PATH"
  gf_assert "an awk that exits 2" "$where"
done

# ---------------------------------------------------------------------------
# HARNESS-078: the answer is one line whatever lib.sh prints while loading
# (AC-4), and a harness path git C-quotes under ANY core.quotePath is seen by
# its real name (AC-5). Both have a harness change on the story branch, so the
# only correct answer is the pinned `run` line, compared whole by `expect`.

describe "HARNESS-078 AC-4: a lib.sh that prints while it is sourced does not add a line to the answer"

# The fixture's COPY of lib.sh is test data: an `echo` goes in as its line 2,
# rewritten with awk, not `sed -i`. The rewrite is committed on main BEFORE
# the story branch, so lib.sh is not itself a changed path and the answer
# names exactly one: scripts/x.sh, committed on the story branch.
new_fixture; SN="$d/scripts/selftest-needed.sh"
FLIB="$d/.claude/hooks/lib.sh"
awk 'NR == 2 { print "echo lib-loaded-on-stdout" } { print }' "$FLIB" > "$WORK/lib.sh" && cat "$WORK/lib.sh" > "$FLIB"
commit_all "a lib.sh that prints on load"; story_branch
put scripts/x.sh '#!/usr/bin/env bash'; commit_all "add x"
assert_eq "precondition: sourcing the fixture's lib.sh prints exactly \`lib-loaded-on-stdout\` on stdout" \
  "lib-loaded-on-stdout" "$( (CLAUDE_PROJECT_DIR="$d"; . "$FLIB") 2>/dev/null)"
assert_eq "precondition: the only path changed against main is scripts/x.sh, and the tree is clean" \
  "scripts/x.sh|" "$(gitc diff --name-only main HEAD 2>/dev/null)|$(gitc status --porcelain 2>/dev/null)"
expect "a lib.sh that prints a line on load: the answer is still the one pinned run line" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): scripts/x.sh" yes

describe "HARNESS-078 AC-5: a harness path named with \`\"\`, \`\\\` or a tab is seen, and named byte for byte"

# git C-quotes `"`, `\` and a tab under core.quotePath=false too, so the
# quoted name classified `source` and the script answered skip - a wrong-way
# skip. Each name is run UNTRACKED (the `ls-files` listing) and COMMITTED (the
# `git diff` listing), because each listing needs its own `-z`. Decision 3:
# Git Bash cannot hold these names, so on MINGW/MSYS/CYGWIN the cases are not
# run and one stdout line says so; a skip is not counted as a pass. Everywhere
# else the fixture holding the name byte for byte is an assert_eq.
H78_TAB="$(printf '\t')"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    printf '    SKIP %s\n' "HARNESS-078 AC-5 (decision 3): the .claude/tests/a\"b.test.sh, .claude/tests/a\\b.test.sh and .claude/tests/a<TAB>b.test.sh cases, untracked and committed, are not run on $(uname -s): Git Bash maps \" and a tab to private-use code points and cannot create \\ at all; not counted as a pass"
    ;;
  *)
    for h78_name in '.claude/tests/a"b.test.sh' '.claude/tests/a\b.test.sh' ".claude/tests/a${H78_TAB}b.test.sh"; do
      h78_label="$(printf '%s' "$h78_name" | sed "s/$H78_TAB/<TAB>/")"

      new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
      mkdir -p "$d/.claude/tests"; printf 'true\n' > "$d/$h78_name"
      assert_eq "precondition: git lists $h78_label, and nothing else, as untracked, byte for byte" \
        "$h78_name" "$(gitc ls-files -z --others --exclude-standard 2>/dev/null | tr '\0' '\n')"
      expect "an UNTRACKED $h78_label answers run and names it byte for byte" 0 \
        "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): $h78_name" yes

      new_fixture; SN="$d/scripts/selftest-needed.sh"; story_branch
      mkdir -p "$d/.claude/tests"; printf 'true\n' > "$d/$h78_name"; commit_all "quoted name"
      assert_eq "precondition: the commit holds $h78_label, and nothing else, byte for byte, and the tree is clean" \
        "$h78_name|" "$(gitc diff -z --name-only main HEAD 2>/dev/null | tr '\0' '\n')|$(gitc status --porcelain 2>/dev/null)"
      expect "a COMMITTED $h78_label answers run and names it byte for byte" 0 \
        "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): $h78_name" yes
    done
    ;;
esac

# ===========================================================================
# HARNESS-094: `--suites [base-ref]` - WHICH suites the diff can break, one
# per line, or the single line `all`; exit 1 and nothing on stdout when no
# harness path changed. The rules (story, Contract): R1 a changed
# .claude/tests/<name>.test.sh selects <name>; R2 _lib.sh, _spawns.sh or
# scripts/selftest.sh selects `all`; R3 a suite whose SOURCE holds the path as
# a fixed string; R4 the five scanner rows; R5 a harness path no rule maps
# selects `all`. Amendment A-1 (RED): a rule contributes a name only when
# .claude/tests/<name>.test.sh exists in the tree - see the deleted-suite case.
# Amendments at GATES: AM-1 / A-4, R2 also names .claude/hooks/lib.sh; AM-2 /
# A-5, the *.sh scanner rows (lib, sigpipe, grep-count) ADD their suite but do
# not map a path, so a *.sh that only they match is R5's `all`.
#
# THE FIXTURE. suites_stubs writes nine throwaway suites into the fixture's
# .claude/tests and commits them on `main`, so every list below is read out,
# not derived: alpha and beta mention .claude/harness/m.conf, beta also
# .claude/harness/n.conf, alpha also the three shell files the AC-4 scanner
# cases change (scripts/probes/x.sh, .claude/hooks/x.sh, .claude/foo/x.sh -
# AM-2: a *.sh that only the *.sh rows match is `all`, so the cases that pin
# those rows need R3 to map the path), policy mentions
# .claude/skills/foo/SKILL.md, and gamma and the five scanner suites mention
# no path at all. The stubs are
# never executed - R3 reads source - so they are one comment line each. Every
# name is lowercase letters and at most one `-`, chosen so that `sort` gives
# the same order in the C locale and in en_US (gamma < grep-count, policy <
# profiles, shipped-docs < sigpipe either way).
#
# THE NEEDLES. stdout is compared WHOLE, with its line count, from the root
# and from src/. stderr's first line (the header) is compared whole where the
# fixture makes it deterministic; one per-suite line per rule kind is matched
# by reason_lines, which pins everything but the padding width between the
# name and the path (the Contract shows the shape, not a width).
#
# THE RED SHAPE. Today `--suites` is a `-`-prefixed argument, so every run
# exits 2 with the usage line and empty stdout. Every case runs regardless and
# every assertion is unconditional, so the executed count is the same in RED
# and GREEN. The usage cases and the run/skip-unchanged case pass on arrival;
# the handoff says what earns them.

SUITE_STUBS="alpha beta gamma grep-count lib policy profiles shipped-docs sigpipe"

# suites_stubs   Writes the nine stub suites into $d/.claude/tests and commits
# them on the current branch (main).
suites_stubs() {
  local s
  for s in $SUITE_STUBS; do put ".claude/tests/$s.test.sh" "# fixture suite $s"; done
  printf '# reads .claude/harness/m.conf\n' >> "$d/.claude/tests/alpha.test.sh"
  printf '# runs scripts/probes/x.sh, .claude/hooks/x.sh and .claude/foo/x.sh\n' >> "$d/.claude/tests/alpha.test.sh"
  printf '# reads .claude/harness/m.conf and .claude/harness/n.conf\n' >> "$d/.claude/tests/beta.test.sh"
  printf '# reads .claude/skills/foo/SKILL.md\n' >> "$d/.claude/tests/policy.test.sh"
  commit_all "stub suites"
}

# suites_fixture   d := a fresh fixture holding the stubs on main, checked out
# on a story branch with no change yet.
suites_fixture() {
  new_fixture; SN="$d/scripts/selftest-needed.sh"
  suites_stubs
  story_branch
}

# es_run <cwd> [args...]   run_sn, then OUTS := the whole stdout, its lines
# joined by newlines (CR stripped; "" when there is none), ERR with CR
# stripped, ERR1 := the first line of stderr.
es_run() {
  run_sn "$@"
  OUTS=""; [ "$NOUT" -gt 0 ] && OUTS="$(printf '%s\n' "${OL[@]}")"
  ERR="${ERR//$'\r'/}"; ERR1="${ERR%%$'\n'*}"
}

# nlines <text>   How many lines <text> holds: 0 for "", else newlines + 1.
nlines() {
  local t="$1" n=0
  [ -n "$t" ] || { printf 0; return; }
  n=1; t="${t//[!$'\n']/}"; printf '%s' $((n + ${#t}))
}

# expect_suites <label> <rc> <stdout> <errmode> <err> [args...]
# From the fixture root and from src/: the exit status, the WHOLE stdout and
# its line count, and stderr - <errmode> `whole`: stderr is exactly <err>;
# `first`: stderr's first line is exactly <err>. Four assertions per
# directory, eight per call, unconditionally.
expect_suites() {
  local label="$1" rc="$2" want="$3" mode="$4" werr="$5" where cwd
  shift 5
  for where in root subdir; do
    cwd="$d"; [ "$where" = subdir ] && cwd="$d/$SUBDIR"
    es_run "$cwd" "$@"
    assert_eq "$label [from $where]: exits $rc" "$rc" "$RC"
    assert_eq "$label [from $where]: stdout is exactly the pinned list" "$want" "$OUTS"
    assert_eq "$label [from $where]: stdout has exactly $(nlines "$want") line(s)" "$(nlines "$want")" "$NOUT"
    if [ "$mode" = whole ]; then
      assert_eq "$label [from $where]: stderr is exactly the pinned text" "$werr" "$ERR"
    else
      assert_eq "$label [from $where]: stderr's first line is exactly the pinned header" "$werr" "$ERR1"
    fi
  done
  return 0
}

# reason_lines <name> <path> <rule>   How many lines of the last run's stderr
# are `  <name>`, one or more spaces, then exactly `<path> (<rule>)`.
reason_lines() {
  awk -v n="$1" -v t="$2 ($3)" '
    substr($0, 1, 2 + length(n)) == "  " n {
      s = substr($0, 3 + length(n))
      if (s ~ /^ +/) { sub(/^ +/, "", s); if (s == t) c++ }
    }
    END { print c + 0 }' <<REASON_ERR
$ERR
REASON_ERR
}

# out_has <line>   How many lines of the last run's stdout are exactly <line>.
out_has() {
  awk -v l="$1" '$0 == l { c++ } END { print c + 0 }' <<OUT_LINES
$OUTS
OUT_LINES
}

# hdr <k> <m> <paths> [base]   The pinned --suites header for a list.
hdr() {
  local b="${4:-main}"
  printf 'selftest-needed: suites %s %s of %s selected from %s harness path(s) changed against %s (merge-base %s)' \
    "$D" "$1" "$2" "$3" "$b" "$(short "$b")"
}
SUITES_ALL="selftest-needed: suites $D all: "
SUITES_FB_PRE="${SUITES_ALL}cannot compute the diff: "
SUITES_FB_SUF="; defaulting to every suite"

# ---------------------------------------------------------------------------
describe "HARNESS-094 AC-1: --suites prints the suites whose source mentions a changed path"

suites_fixture
put .claude/harness/n.conf 'n'; commit_all "n.conf"
expect_suites "a committed .claude/harness/n.conf, mentioned only by beta, prints beta" 0 \
  "beta" first "$(hdr 1 9 1)" --suites
assert_eq "the control: alpha, whose source mentions m.conf but not n.conf, is not printed" 0 "$(out_has alpha)"
assert_eq "the control: gamma, whose source mentions no path, is not printed" 0 "$(out_has gamma)"

suites_fixture
put .claude/harness/m.conf 'm'; gitc add .claude/harness/m.conf >/dev/null 2>&1
put .claude/harness/n.conf 'n'
expect_suites "a STAGED m.conf and an UNTRACKED n.conf print alpha and beta, sorted, beta once" 0 \
  "alpha
beta" first "$(hdr 2 9 2)" --suites
assert_eq "stderr names alpha's first selecting path and the rule: (mentioned)" 1 \
  "$(reason_lines alpha .claude/harness/m.conf mentioned)"
assert_eq "stderr names beta's FIRST path in sort order, m.conf, not n.conf" 1 \
  "$(reason_lines beta .claude/harness/m.conf mentioned)"

# ---------------------------------------------------------------------------
describe "HARNESS-094 AC-2: a changed suite selects itself; _lib.sh, _spawns.sh, hooks/lib.sh and selftest.sh select all"

suites_fixture
put .claude/tests/gamma.test.sh '# fixture suite gamma, edited'
expect_suites "an edited .claude/tests/gamma.test.sh, mentioned by no suite, prints gamma (and the *.sh scanners)" 0 \
  "gamma
grep-count
sigpipe" first "$(hdr 3 9 1)" --suites
assert_eq "stderr names gamma's path and the rule: (itself)" 1 \
  "$(reason_lines gamma .claude/tests/gamma.test.sh itself)"

suites_fixture
put .claude/tests/delta.test.sh '# a new suite'
expect_suites "a NEW untracked .claude/tests/delta.test.sh prints delta, and the count of suites is the tree's (10)" 0 \
  "delta
grep-count
sigpipe" first "$(hdr 3 10 1)" --suites

suites_fixture
put .claude/tests/_lib.sh '# a library'; put .claude/harness/n.conf 'n'
expect_suites "a changed .claude/tests/_lib.sh beside a mapped n.conf prints all, and says why" 0 \
  "all" whole "${SUITES_ALL}.claude/tests/_lib.sh is read by every suite" --suites

suites_fixture
put .claude/tests/_spawns.sh '# a tracer'
expect_suites "a changed .claude/tests/_spawns.sh prints all, and says why" 0 \
  "all" whole "${SUITES_ALL}.claude/tests/_spawns.sh is read by every suite" --suites

suites_fixture
printf '# edited on the story branch\n' >> "$d/scripts/selftest.sh"
expect_suites "an edited scripts/selftest.sh prints all, and says why" 0 \
  "all" whole "${SUITES_ALL}scripts/selftest.sh is read by every suite" --suites

# AM-1 / Contract A-4: the harness library that 11 scripts source is R2's,
# not merely a scripts-or-hooks *.sh for the scanner rows (which gave 15 of 34
# on the real tree, `## Diff review` finding 1). The needle is the WHOLE
# stderr, so `... is mapped by no rule` (R5, the same stdout) does not pass.
suites_fixture
printf '# edited on the story branch\n' >> "$d/.claude/hooks/lib.sh"
expect_suites "AM-1: an edited .claude/hooks/lib.sh prints all, and says it is read by every suite" 0 \
  "all" whole "${SUITES_ALL}.claude/hooks/lib.sh is read by every suite" --suites

# ---------------------------------------------------------------------------
describe "HARNESS-094 AC-3: a path no rule maps, or a diff that cannot be computed, prints all"

suites_fixture
put .claude/harness/x.conf 'x'; put .claude/harness/m.conf 'm'
expect_suites "the control: a new .claude/harness/x.conf that no rule maps, beside a mapped m.conf, prints all and names x.conf" 0 \
  "all" whole "${SUITES_ALL}.claude/harness/x.conf is mapped by no rule; defaulting to every suite" --suites

suites_fixture
put .claude/harness/m.conf 'm'
expect_suites "the control for the control: m.conf alone, which R3 maps, prints the list, not all" 0 \
  "alpha
beta" first "$(hdr 2 9 1)" --suites

new_fixture; SN="$d/scripts/selftest-needed.sh"
gitc branch -M trunk >/dev/null 2>&1; story_branch
put .claude/harness/m.conf 'm'; commit_all "m"
expect_suites "neither origin/main nor main resolves: all, with the existing reason" 0 \
  "all" whole "${SUITES_FB_PRE}no origin/main or main to compare against${SUITES_FB_SUF}" --suites

new_fixture; SN="$d/scripts/selftest-needed.sh"
gitc branch -M story/T-1-fixture >/dev/null 2>&1
put .claude/harness/m.conf 'm'; commit_all "m"
empty_tree="$(gitc mktree </dev/null 2>/dev/null)"
unrelated="$(gitc commit-tree "$empty_tree" -m unrelated 2>/dev/null)"
gitc update-ref refs/heads/main "$unrelated" >/dev/null 2>&1
assert_eq "precondition: main exists and shares no history with the story branch" \
  "1:1" "$(gitc rev-parse --verify -q main >/dev/null 2>&1 && printf 1):$(gitc merge-base main HEAD >/dev/null 2>&1 || printf 1)"
expect_suites "main resolves but has no merge base: all, with the existing reason" 0 \
  "all" whole "${SUITES_FB_PRE}no merge base with main${SUITES_FB_SUF}" --suites

nd="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"; FIXES+=("$nd")
mkdir -p "$nd/.claude" "$nd/$SUBDIR"
cp -r "$REPO_ROOT/scripts" "$nd/scripts"
cp -r "$REPO_ROOT/.claude/hooks" "$nd/.claude/hooks"
cp -r "$REPO_ROOT/.claude/harness" "$nd/.claude/harness"
CEIL="$(dirname "$nd")"
assert_eq "precondition: the directory is not inside any git checkout" \
  "no" "$(cd "$nd" && GIT_CEILING_DIRECTORIES="$CEIL" git rev-parse --show-toplevel >/dev/null 2>&1 && printf yes || printf no)"
d="$nd"; SN="$d/scripts/selftest-needed.sh"
expect_suites "outside any git checkout: all, with the existing reason" 0 \
  "all" whole "${SUITES_FB_PRE}not a git checkout${SUITES_FB_SUF}" --suites
CEIL=""

# fb_lines   How many lines of the last run's stderr begin SUITES_FB_PRE and
# end SUITES_FB_SUF - the fallback's line, whatever reason sits between.
fb_lines() {
  awk -v p="$SUITES_FB_PRE" -v s="$SUITES_FB_SUF" '
    length($0) >= length(p) + length(s) && substr($0, 1, length(p)) == p &&
    substr($0, length($0) - length(s) + 1) == s { c++ }
    END { print c + 0 }' <<FB_ERR
$ERR
FB_ERR
}

suites_fixture
put .claude/harness/m.conf 'm'; commit_all "m"
FLIB="$d/.claude/hooks/lib.sh"
awk 'NR == 2 { print "echo \"$NOPE_UNSET\"" } { print }' "$FLIB" > "$WORK/lib.sh" && cat "$WORK/lib.sh" > "$FLIB"
assert_eq "precondition: sourcing the fixture's lib.sh under \`set -u\` in a subshell fails" \
  "fails" "$( ( set -u; . "$FLIB" ) >/dev/null 2>&1 && printf loads || printf fails)"
for where in root subdir; do
  cwd="$d"; [ "$where" = subdir ] && cwd="$d/$SUBDIR"
  es_run "$cwd" --suites
  assert_eq "a lib.sh that will not load [from $where]: exits 0" 0 "$RC"
  assert_eq "a lib.sh that will not load [from $where]: stdout is exactly all" "all" "$OUTS"
  assert_eq "a lib.sh that will not load [from $where]: stdout is exactly one line" 1 "$NOUT"
  assert_eq "a lib.sh that will not load [from $where]: stderr carries the fallback line once" 1 "$(fb_lines)"
done

suites_fixture
put .claude/harness/m.conf 'm'; commit_all "m"
rm -f "$d/.claude/harness/paths.conf"
assert_eq "precondition: the fixture's .claude/harness/paths.conf is gone" \
  "gone" "$([ -e "$d/.claude/harness/paths.conf" ] && printf present || printf gone)"
for where in root subdir; do
  cwd="$d"; [ "$where" = subdir ] && cwd="$d/$SUBDIR"
  es_run "$cwd" --suites
  assert_eq "paths.conf missing [from $where]: exits 0" 0 "$RC"
  assert_eq "paths.conf missing [from $where]: stdout is exactly all" "all" "$OUTS"
  assert_eq "paths.conf missing [from $where]: stdout is exactly one line" 1 "$NOUT"
  assert_eq "paths.conf missing [from $where]: stderr carries the fallback line once" 1 "$(fb_lines)"
done

# ---------------------------------------------------------------------------
describe "HARNESS-094 AC-4: the scanner rows select suites that read the tree by glob"

# AM-2 / Contract A-5: the *.sh rows are ADDITIVE. Each path below is
# mentioned by alpha (R3), which maps it; the rows add their suites beside it.
suites_fixture
put scripts/probes/x.sh '#!/usr/bin/env bash'
expect_suites "a new scripts/probes/x.sh (a deeper scripts/*.sh) that alpha mentions prints alpha, and grep-count, lib and sigpipe beside it" 0 \
  "alpha
grep-count
lib
sigpipe" first "$(hdr 4 9 1)" --suites
assert_eq "stderr names lib's path and the pattern that matched: (scans scripts/*.sh)" 1 \
  "$(reason_lines lib scripts/probes/x.sh 'scans scripts/*.sh')"

suites_fixture
put .claude/hooks/x.sh '#!/usr/bin/env bash'
expect_suites "a new .claude/hooks/x.sh that alpha mentions prints alpha, and grep-count, lib and sigpipe beside it" 0 \
  "alpha
grep-count
lib
sigpipe" first "$(hdr 4 9 1)" --suites

suites_fixture
put .claude/foo/x.sh '#!/usr/bin/env bash'
expect_suites "a new .claude/foo/x.sh that alpha mentions prints alpha, and grep-count and sigpipe beside it" 0 \
  "alpha
grep-count
sigpipe" first "$(hdr 3 9 1)" --suites
assert_eq "and not lib, whose rows are scripts/ and .claude/hooks/ only" 0 "$(out_has lib)"

# AM-2's control: a *.sh that ONLY the *.sh rows match is mapped by no rule.
# A helper suites source by relative name ("$HERE/_helpers.sh") is never
# mentioned by its repo path, so R3 cannot see it (`## Diff review` finding
# 2: 2 of 34 on the real tree, while _helpers.conf gave all). The needle is
# the WHOLE stderr, so R2's `is read by every suite` does not pass either.
# HARNESS-096 AC-3 renamed both fixtures to names no real file will take:
# a suite that names a path as test data maps it (R3), so a fixture named
# like a plausible real file kept that real file from R5 on the real tree.
suites_fixture
put .claude/tests/_h096_fixture_helper.sh 'helper() { :; }'
expect_suites "AM-2 control: an untracked .claude/tests/_h096_fixture_helper.sh that no suite mentions prints all, and names it as mapped by no rule" 0 \
  "all" whole "${SUITES_ALL}.claude/tests/_h096_fixture_helper.sh is mapped by no rule; defaulting to every suite" --suites

suites_fixture
put scripts/h096-fixture-tool.sh '#!/usr/bin/env bash'
expect_suites "AM-2: a new scripts/h096-fixture-tool.sh that no suite mentions prints all, though lib, sigpipe and grep-count scan it" 0 \
  "all" whole "${SUITES_ALL}scripts/h096-fixture-tool.sh is mapped by no rule; defaulting to every suite" --suites

suites_fixture
put .claude/skills/stack-profiles/reference/x.txt 'x'
expect_suites "a file under .claude/skills/stack-profiles/reference/ prints profiles" 0 \
  "profiles" first "$(hdr 1 9 1)" --suites

suites_fixture
put .claude/commands/x.md '# x'; put .claude/agents/x.md '# x'
expect_suites "a .md under .claude/commands/ and one under .claude/agents/ print shipped-docs, not all" 0 \
  "shipped-docs" first "$(hdr 1 9 2)" --suites

suites_fixture
put .claude/skills/bar/deep/notes.md '# notes'
expect_suites "the control: a .md two levels under .claude/skills/ that no suite mentions prints shipped-docs, not all" 0 \
  "shipped-docs" first "$(hdr 1 9 1)" --suites

suites_fixture
put .claude/skills/foo/SKILL.md '# a skill'
expect_suites "a .md under .claude/skills/ that policy mentions prints policy and shipped-docs" 0 \
  "policy
shipped-docs" first "$(hdr 2 9 1)" --suites

# ---------------------------------------------------------------------------
describe "HARNESS-094 AC-5: no harness path is exit 1 and nothing on stdout; a base ref is used; usage"

suites_fixture
put src/app.ts 'export const a = 1'; commit_all "source only"
expect_suites "a source-only diff: nothing on stdout, exit 1, the existing skip line on stderr" 1 \
  "" whole "selftest-needed: skip $D no harness path among 1 changed path(s) against main (merge-base $(short main))$CI_TAIL" --suites

# main has moved past `release` with a harness commit; the story branch adds a
# source file. Against release the harness commit is in the diff; against
# main it is not.
new_fixture; SN="$d/scripts/selftest-needed.sh"
suites_stubs
gitc branch release >/dev/null 2>&1
put .claude/harness/n.conf 'n'; commit_all "n.conf on main"
story_branch; put src/app.ts 'export const a = 1'; commit_all "source"
expect_suites "\`--suites release\` diffs against release and prints beta" 0 \
  "beta" first "$(hdr 1 9 1 release)" --suites release
expect_suites "control: \`--suites\` on the same fixture resolves main and selects nothing" 1 \
  "" whole "selftest-needed: skip $D no harness path among 1 changed path(s) against main (merge-base $(short main))$CI_TAIL" --suites

suites_fixture
for args in "--suites -x" "--suites main extra" "main --suites"; do
  es_run "$d" $args   # split on purpose: each string is an argument list
  assert_eq "\`$args\` exits 2" 2 "$RC"
  assert_eq "\`$args\` prints nothing on stdout" 0 "$NOUT"
  assert_eq "\`$args\` says why on stderr" yes "$([ -n "$ERR" ] && printf yes || printf no)"
done

suites_fixture
put .claude/harness/m.conf 'm'; commit_all "m"
expect "without --suites, a fixture holding suites still answers the unchanged run line" 0 \
  "selftest-needed: run $D 1 harness path(s) changed against main (merge-base $(short main)): .claude/harness/m.conf" yes

# ---------------------------------------------------------------------------
describe "HARNESS-094 A-1: a rule names a suite only when its file exists in the tree"

# gamma.test.sh deleted on the branch: R1 would name gamma, which can no
# longer run (selftest.sh --changed would say "No suites matched"). Under A-5
# (AM-2) the *.sh scanner rows no longer map a path, and no suite mentions
# gamma's, so nothing maps it: R5's `all`, naming it. Before A-5 this case
# expected `grep-count sigpipe` and a count of 8 suites.
suites_fixture
gitc rm -q .claude/tests/gamma.test.sh >/dev/null 2>&1; commit_all "drop gamma"
expect_suites "a DELETED .claude/tests/gamma.test.sh prints all, not gamma, and names it as mapped by no rule" 0 \
  "all" whole "${SUITES_ALL}.claude/tests/gamma.test.sh is mapped by no rule; defaulting to every suite" --suites

# ---------------------------------------------------------------------------
describe "HARNESS-094 AC-8: CLAUDE.md's command list names both, directly after the selftest-needed.sh line"

CM="$REPO_ROOT/CLAUDE.md"
CM_ANCHOR="bash scripts/selftest-needed.sh  # does this story's diff touch a harness path? exit 0 run / 1 skip"
CM_L1='bash scripts/selftest-needed.sh --suites   # which suites that diff can break, one per line, or `all`'
CM_L2='SELFTEST_JOBS=4 bash scripts/selftest.sh --changed   # run exactly those; the local self-test before a PR (HARNESS-095 switches the procedure to it)'
CM_TEXT="$(tr -d '\r' < "$CM")"
cm_count() {
  awk -v l="$1" '$0 == l { c++ } END { print c + 0 }' <<CM_LINES
$CM_TEXT
CM_LINES
}
assert_eq "precondition: CLAUDE.md holds the existing selftest-needed.sh line exactly once" 1 "$(cm_count "$CM_ANCHOR")"
assert_eq "the two lines directly after it are the --suites line, then the --changed line" "$CM_L1
$CM_L2" "$(awk -v a="$CM_ANCHOR" 'f && n < 2 { print; n++ } $0 == a { f = 1 }' <<CM_AFTER
$CM_TEXT
CM_AFTER
)"
assert_eq "the --suites line appears exactly once" 1 "$(cm_count "$CM_L1")"
assert_eq "the --changed line appears exactly once" 1 "$(cm_count "$CM_L2")"

# ---------------------------------------------------------------------------
# HARNESS-096. R3 counts a mention only where it ends where the path ends
# (story, Contract "R3, amended" and C-2): the character after the match is
# end of line, or is not in [A-Za-z0-9_/-] and is not a `.` followed by
# [A-Za-z0-9].
#
# THE RED SHAPE. Today R3 is a bare `index`, so a longer path starting with
# the changed one maps it: the two dirty-mention cases and AC-2 print a list
# where `all` is pinned, and AC-4's texts are absent. The clean-mention cases
# are CONTROLS - a clean mention is a substring too - and pass on arrival;
# they fail only if GREEN's boundary check refuses a terminator it must
# accept. Every stub line is appended to gamma, which names no path. A changed
# scripts/x.sh is a scripts/*.sh, so the scanner rows add grep-count, lib and
# sigpipe beside a mapping suite: the pinned list is four suites (Contract
# C-3 amended in RED: it said `hdr 1 9 1`).
describe "HARNESS-096 AC-1: a mention counts only where it ends where the path ends"

h096_fixture() {   # <line appended to gamma>   d := the fixture, on its branch
  new_fixture; SN="$d/scripts/selftest-needed.sh"
  suites_stubs
  printf '%s\n' "$1" >> "$d/.claude/tests/gamma.test.sh"
  commit_all "gamma names a path"
  story_branch
}

h096_fixture '# keeps scripts/x.sh.bak and runs scripts/xy.sh'
put scripts/x.sh '#!/usr/bin/env bash'
expect_suites "AC-1: gamma names scripts/x.sh.bak and scripts/xy.sh only, so an untracked scripts/x.sh is mapped by no rule and prints all" 0 \
  "all" whole "${SUITES_ALL}scripts/x.sh is mapped by no rule; defaulting to every suite" --suites

h096_fixture '# keeps scripts/x.sh-old, scripts/x.sh_old, scripts/x.sh/sub, scripts/x.sh.d and scripts/x.sh2'
put scripts/x.sh '#!/usr/bin/env bash'
expect_suites "AC-1: a mention continued by -, _, /, .<alnum> or a digit is a longer path, so scripts/x.sh still prints all" 0 \
  "all" whole "${SUITES_ALL}scripts/x.sh is mapped by no rule; defaulting to every suite" --suites

H096_MAPPED="gamma
grep-count
lib
sigpipe"
H096_TERMS=(" " '"' "'" '`' ")" ":" ",")
H096_NAMES=("a space" "a double quote" "a single quote" "a backtick" "a closing parenthesis" "a colon" "a comma")
for i in "${!H096_TERMS[@]}"; do
  h096_fixture "# runs scripts/x.sh${H096_TERMS[$i]} then stops"
  put scripts/x.sh '#!/usr/bin/env bash'
  expect_suites "AC-1 control: gamma names scripts/x.sh followed by ${H096_NAMES[$i]}, so scripts/x.sh maps to gamma" 0 \
    "$H096_MAPPED" first "$(hdr 4 9 1)" --suites
  assert_eq "AC-1 control (${H096_NAMES[$i]}): gamma is printed exactly once" 1 "$(out_has gamma)"
done

h096_fixture '# the last step runs scripts/x.sh.'
put scripts/x.sh '#!/usr/bin/env bash'
expect_suites "AC-1 control: gamma names scripts/x.sh followed by a sentence-ending . at end of line, so scripts/x.sh maps to gamma" 0 \
  "$H096_MAPPED" first "$(hdr 4 9 1)" --suites
assert_eq "AC-1 control (a sentence-ending .): gamma is printed exactly once" 1 "$(out_has gamma)"

h096_fixture '# keeps scripts/x.sh.bak then scripts/x.sh'
put scripts/x.sh '#!/usr/bin/env bash'
expect_suites "AC-1 control: a dirty mention THEN a clean one on the same line still maps scripts/x.sh to gamma" 0 \
  "$H096_MAPPED" first "$(hdr 4 9 1)" --suites
assert_eq "AC-1 control (dirty then clean): gamma is printed exactly once" 1 "$(out_has gamma)"

# ---------------------------------------------------------------------------
describe "HARNESS-096 AC-2: a path that is the prefix of a longer file name is not mentioned by it"

h096_fixture '# runs scripts/new-story.sh'
put scripts/new 'x'
expect_suites "AC-2: gamma names scripts/new-story.sh only, so an untracked scripts/new is mapped by no rule and prints all" 0 \
  "all" whole "${SUITES_ALL}scripts/new is mapped by no rule; defaulting to every suite" --suites

h096_fixture '# runs scripts/new then stops'
put scripts/new 'x'
expect_suites "AC-2 control: gamma names scripts/new followed by a space, so scripts/new maps to gamma alone" 0 \
  "gamma" first "$(hdr 1 9 1)" --suites
assert_eq "AC-2 control: gamma is printed exactly once" 1 "$(out_has gamma)"

# ---------------------------------------------------------------------------
describe "HARNESS-096 AC-3: this suite's R5 fixtures take names no real harness file will take"

# The old names are spelled in two halves, so this needle is not itself a
# mention of them in this file.
SN_TEST="$REPO_ROOT/.claude/tests/selftest-needed.test.sh"
SN_TEST_TEXT="$(tr -d '\r' < "$SN_TEST")"
h096_lines_holding() {   # <needle>   lines of this suite's source holding it
  awk -v n="$1" 'index($0, n) { c++ } END { print c + 0 }' <<H096_SRC
$SN_TEST_TEXT
H096_SRC
}
h096_lines_equal() {   # <line>   lines of this suite's source exactly <line>
  awk -v l="$1" '$0 == l { c++ } END { print c + 0 }' <<H096_SRC
$SN_TEST_TEXT
H096_SRC
}
H096_OLD_HELPER=".claude/tests/""_helpers.sh"
H096_OLD_TOOL="scripts/""newtool.sh"
assert_eq "this suite's source names the old helper fixture path on no line" 0 "$(h096_lines_holding "$H096_OLD_HELPER")"
assert_eq "this suite's source names the old tool fixture path on no line" 0 "$(h096_lines_holding "$H096_OLD_TOOL")"
assert_eq "the AM-2 control writes .claude/tests/_h096_fixture_helper.sh, on exactly one line" 1 \
  "$(h096_lines_equal "put .claude/tests/_h096_fixture_helper.sh 'helper() { :; }'")"
assert_eq "the AM-2 case writes scripts/h096-fixture-tool.sh, on exactly one line" 1 \
  "$(h096_lines_equal "put scripts/h096-fixture-tool.sh '#!/usr/bin/env bash'")"
assert_eq "classify.sh calls .claude/tests/_h096_fixture_helper.sh harness" \
  "harness	.claude/tests/_h096_fixture_helper.sh" \
  "$(cd "$REPO_ROOT" && bash scripts/classify.sh .claude/tests/_h096_fixture_helper.sh 2>/dev/null | tr -d '\r')"
assert_eq "classify.sh calls scripts/h096-fixture-tool.sh harness" \
  "harness	scripts/h096-fixture-tool.sh" \
  "$(cd "$REPO_ROOT" && bash scripts/classify.sh scripts/h096-fixture-tool.sh 2>/dev/null | tr -d '\r')"

# ---------------------------------------------------------------------------
describe "HARNESS-096 AC-4: the header and CLAUDE.md declare that a mention as test data maps a path"

SNH_TEXT="$(tr -d '\r' < "$REPO_ROOT/scripts/selftest-needed.sh")"
snh_count() {   # <line>   lines of selftest-needed.sh exactly <line>
  awk -v l="$1" '$0 == l { c++ } END { print c + 0 }' <<SNH_LINES
$SNH_TEXT
SNH_LINES
}
SNH_R2_TAIL='#                every suite: `all` (A-4)'
SNH_R4='#   R4 scans     a row of the SCANS table below; an `add` row adds its suite'
SNH_N1='#   R3 mentioned a suite whose source holds the path as a fixed substring'
SNH_N2='#                that ends where the path ends; comments and test data'
SNH_N3='#                count, so a path a suite names only as test data is'
SNH_N4='#                mapped by that mention and never reaches R5 (HARNESS-096)'
SNH_O1='#   R3 mentioned a suite whose source holds the path as a fixed substring,'
SNH_O2='#                comments included (over-selects, never under-selects)'
assert_eq "precondition: the header's R2 row ends on its one \`all\` (A-4) line" 1 "$(snh_count "$SNH_R2_TAIL")"
assert_eq "the header's new R3 line 1 appears exactly once" 1 "$(snh_count "$SNH_N1")"
assert_eq "the header's new R3 line 2 appears exactly once" 1 "$(snh_count "$SNH_N2")"
assert_eq "the header's new R3 line 3 appears exactly once" 1 "$(snh_count "$SNH_N3")"
assert_eq "the header's new R3 line 4 appears exactly once" 1 "$(snh_count "$SNH_N4")"
assert_eq "the four R3 lines sit, in order, between the R2 row and the R4 row" "$SNH_N1
$SNH_N2
$SNH_N3
$SNH_N4
$SNH_R4" "$(awk -v a="$SNH_R2_TAIL" 'f && n < 5 { print; n++ } $0 == a { f = 1 }' <<SNH_AFTER
$SNH_TEXT
SNH_AFTER
)"
assert_eq "the old R3 line (ending in a comma) is gone" 0 "$(snh_count "$SNH_O1")"
assert_eq "the old \`never under-selects\` line is gone" 0 "$(snh_count "$SNH_O2")"
assert_eq "no line of selftest-needed.sh still claims R3 never under-selects" 0 \
  "$(awk 'index($0, "never under-selects") { c++ } END { print c + 0 }' <<SNH_CLAIM
$SNH_TEXT
SNH_CLAIM
)"

# The third line is HARNESS-098's: it supersedes HARNESS-096 C-5's pin of
# `... is mapped by that mention and does not reach `all`.`, which is false
# for the R2 paths (suites name them and --suites still answers `all`).
CM_P1='`--suites` maps a changed path to every suite whose source names it, ending'
CM_P2='where the path ends, comments and test data included. A path a suite names'
CM_P3='only as test data counts as mentioned, never as unmapped (which gives `all`).'
CM_O3='only as test data is mapped by that mention and does not reach `all`.'
CM_GATES_HEAD='`gates.sh` judges the **code**'
assert_eq "CLAUDE.md's declaration line 1 appears exactly once" 1 "$(cm_count "$CM_P1")"
assert_eq "CLAUDE.md's declaration line 2 appears exactly once" 1 "$(cm_count "$CM_P2")"
assert_eq "CLAUDE.md's declaration line 3 appears exactly once" 1 "$(cm_count "$CM_P3")"
assert_eq "CLAUDE.md's old declaration line 3 (ending \`does not reach \`all\`.\`) is gone" 0 "$(cm_count "$CM_O3")"
assert_eq "no line of CLAUDE.md still claims a test-data mention does not reach \`all\`" 0 \
  "$(awk 'index($0, "does not reach `all`") { c++ } END { print c + 0 }' <<CM_CLAIM
$CM_TEXT
CM_CLAIM
)"
assert_eq "the declaration is its own paragraph directly before the one beginning \`gates.sh\` judges the **code**" "[]
[$CM_P1]
[$CM_P2]
[$CM_P3]
[]" "$(awk -v g="$CM_GATES_HEAD" '
    { b[NR] = $0 }
    substr($0, 1, length(g)) == g { for (i = NR - 5; i < NR; i++) print "[" b[i] "]"; exit }' <<CM_BEFORE
$CM_TEXT
CM_BEFORE
)"
assert_eq "the declaration sits in ## Running things" "## Running things" \
  "$(awk -v l="$CM_P1" '/^## / { h = $0 } $0 == l { print h; exit }' <<CM_HEAD
$CM_TEXT
CM_HEAD
)"
assert_eq "the code block holding --suites still closes directly into the \`mutate.sh\` exists paragraph" "
\`mutate.sh\` exists because" "$(awk -v a="$CM_L1" '
    f == 0 && $0 == a { f = 1; next }
    f == 1 && $0 == "```" { f = 2; next }
    f == 2 && n < 1 { print; n++; next }
    f == 2 { print substr($0, 1, 26); exit }' <<CM_FENCE
$CM_TEXT
CM_FENCE
)"
assert_eq "CLAUDE.md lines 160-162 are still the selftest-needed.sh, --suites and --changed lines, byte for byte" "$CM_ANCHOR
$CM_L1
$CM_L2" "$(awk 'NR >= 160 && NR <= 162' <<CM_LINENO
$CM_TEXT
CM_LINENO
)"

summary "selftest-needed"
