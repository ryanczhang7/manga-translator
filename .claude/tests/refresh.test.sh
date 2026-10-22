#!/usr/bin/env bash
# Tests for scripts/refresh-harness.sh - copying a newer harness into a project
# that is already using one.
#
# This exists because the procedure was prose, and prose was followed wrongly on
# its first real outing by the agent that wrote it. Three ways:
#
#   * it recommended `rsync`, which is not present in Git Bash - the shell this
#     harness runs in on Windows;
#   * a wholesale replace of `.claude/skills` deletes a project's OWN stack
#     profile, and the one in the way was 17 KB and cited by four documents;
#   * it omitted `.claude/settings.json` and `.claude/state/README.md`, which
#     are upstream-owned and read as evidence by `settings.test.sh`.
#
# Every one of those is a step somebody has to get right by reading carefully,
# which is the kind of requirement this repository does not otherwise accept
# anywhere. So the steps became a script, and the script reports what it did.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# A stand-in upstream: the real script and hooks, plus marker files we can
# follow through the copy.
UP="$WORK/upstream"; PROJ="$WORK/project"
mkdir -p "$UP/.claude/harness" "$UP/.claude/skills/stack-profiles/reference" "$UP/.claude/hooks" \
         "$UP/.claude/agents" "$UP/.claude/tests" "$UP/.claude/state" "$UP/scripts" \
         "$UP/.claude/commands" "$UP/.github/workflows"
printf 'upstream hook\n'       > "$UP/.claude/hooks/phase-guard.sh"
cp "$REPO_ROOT/scripts/refresh-harness.sh" "$UP/scripts/" 2>/dev/null
printf 'upstream agent\n'      > "$UP/.claude/agents/lead-po.md"
printf 'upstream command\n'    > "$UP/.claude/commands/advance-story.md"
printf 'upstream profile\n'    > "$UP/.claude/skills/stack-profiles/reference/python-uv.md"
printf 'upstream suite\n'      > "$UP/.claude/tests/lib.test.sh"
printf '2026-09-17\n'          > "$UP/.claude/harness/VERSION"
printf 'upstream phases\n'     > "$UP/.claude/harness/phases.conf"
printf 'upstream rules\n'      > "$UP/.claude/harness/rules.md"
printf 'upstream settings\n'   > "$UP/.claude/settings.json"
printf 'upstream state doc\n'  > "$UP/.claude/state/README.md"
printf 'upstream paths\n'      > "$UP/.claude/harness/paths.conf"
printf 'upstream claude md\n'  > "$UP/CLAUDE.md"
printf 'echo new\n'            > "$UP/scripts/brand-new.sh"
# HARNESS-040, C-8. Upstream ships one file under docs/ that its own commands
# name - the audit template - and holds two more it must NOT deliver: a page an
# agent writes (product-brief.md, declared `written`) and a README nothing lists.
# The conf is the fixture's own, never the real tree's: the real one is GREEN's.
mkdir -p "$UP/docs/wiki/audits"
printf 'upstream audit template\n'     > "$UP/docs/wiki/audits/TEMPLATE.md"
printf 'upstream brief, NOT shipped\n' > "$UP/docs/wiki/product-brief.md"
printf 'upstream wiki readme\n'        > "$UP/docs/wiki/README.md"
printf '# fixture docs-shipped.conf\nship    | docs/wiki/audits/TEMPLATE.md\nwritten | docs/wiki/product-brief.md\n' \
  > "$UP/.claude/harness/docs-shipped.conf"

# The upstream fixture is a REPOSITORY, not a directory of files, because the
# question "has upstream ever had this content?" is answered out of its object
# store. Two commits, so an older version of a file genuinely exists there.
#
# Its default branch is PINNED to `master` (HARNESS-013, C-4). Since release 52
# the name of the default branch decides what counts as shipped, and the script
# finds it by trying origin/HEAD, main, master. A machine whose
# init.defaultBranch says `trunk` would otherwise send the whole suite down the
# no-default path and make it pass or fail for reasons unrelated to any story.
( cd "$UP" && git init -q -b master 2>/dev/null \
    && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "upstream, one release ago" >/dev/null 2>&1 )
printf 'upstream agent, a release later\n' > "$UP/.claude/agents/lead-po.md"
( cd "$UP" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "upstream moves on" >/dev/null 2>&1 )

new_project() {
  rm -rf "$PROJ"; mkdir -p "$PROJ/.claude/harness" "$PROJ/.claude/skills/stack-profiles/reference" \
                           "$PROJ/.claude/agents" "$PROJ/.claude/state" "$PROJ/scripts/vitest" "$PROJ/docs/wiki" \
                           "$PROJ/.claude/commands" "$PROJ/.claude/hooks" "$PROJ/.claude/tests" "$PROJ/.github/workflows"
  printf 'OLD agent\n'          > "$PROJ/.claude/agents/lead-po.md"
  # One stale marker per replaced directory. Without these, the staleness grep
  # below has nothing to find in hooks/tests/commands and passes for the reason
  # that the directory was empty - which is what a vacuous assertion looks like.
  printf 'OLD command\n'        > "$PROJ/.claude/commands/advance-story.md"
  printf 'OLD HOOK\n'           > "$PROJ/.claude/hooks/phase-guard.sh"
  printf 'OLD suite\n'          > "$PROJ/.claude/tests/lib.test.sh"
  printf 'OLD profile\n'        > "$PROJ/.claude/skills/stack-profiles/reference/python-uv.md"
  # The project's OWN profile: upstream does not ship it and must not remove it.
  printf 'PROJECT profile\n'    > "$PROJ/.claude/skills/stack-profiles/reference/tauri-react-webgl.md"
  printf 'OLD settings\n'       > "$PROJ/.claude/settings.json"
  printf 'OLD state doc\n'      > "$PROJ/.claude/state/README.md"
  printf 'OLD paths\n'          > "$PROJ/.claude/harness/paths.conf"
  printf 'OLD claude md\n'      > "$PROJ/CLAUDE.md"
  # Project-owned, must survive untouched.
  printf 'BOOTSTRAPPED=yes\n'   > "$PROJ/.claude/harness/project.conf"
  printf 'project notes\n'      > "$PROJ/docs/wiki/stack.md"
  printf 'node_modules/\n'      > "$PROJ/.gitignore"
  printf 'project workflow\n'   > "$PROJ/.github/workflows/gates.yml"
  printf 'project bench\n'      > "$PROJ/scripts/bench.mjs"
  printf 'project helper\n'     > "$PROJ/scripts/vitest/setup.ts"
  ( cd "$PROJ" && git init -q 2>/dev/null && git add -A >/dev/null 2>&1 \
      && git -c user.email=t@t -c user.name=t commit -qm base >/dev/null 2>&1 )
}

refresh() { ( cd "$PROJ" && bash "$REPO_ROOT/scripts/refresh-harness.sh" "$@" 2>&1 ); }

# ---------------------------------------------------------------------------
describe "it refuses to run when running would be unsafe"

new_project
printf 'uncommitted\n' >> "$PROJ/docs/wiki/stack.md"
out="$(refresh "$UP")"; rc=$?
assert_eq "a dirty tree stops it" 2 "$rc"
assert_contains "and says why" "uncommitted" "$out"
( cd "$PROJ" && git checkout -q -- . )

# The procedure's own rule, enforced rather than requested: never mid-cycle,
# because the hooks being replaced are the ones enforcing the phase the story is
# standing in.
new_project
printf 'STORY_ID=W-1\nPHASE=GATES\n' > "$PROJ/.claude/state/current-story.env"
out="$(refresh "$UP")"; rc=$?
assert_eq "an active story stops it" 2 "$rc"
assert_contains "and names the phase" "GATES" "$out"
rm -f "$PROJ/.claude/state/current-story.env"

out="$(refresh /nowhere/at/all)"; rc=$?
assert_eq "a bad upstream path stops it" 2 "$rc"

# Both halves are required of an upstream checkout, and each was unasserted: a
# directory with `scripts` but no `.claude/hooks` is not a harness, and neither
# is the reverse. Copying from one would produce a project missing its lock.
mkdir -p "$WORK/half-a/scripts" "$WORK/half-b/.claude/hooks"
out="$(refresh "$WORK/half-a")"; rc=$?
assert_eq "an upstream with no .claude/hooks is refused" 2 "$rc"
out="$(refresh "$WORK/half-b")"; rc=$?
assert_eq "an upstream with no scripts is refused" 2 "$rc"

# THE false-positive case, and the one that matters most: a DONE story must NOT
# block a refresh. `phase.sh set <id> DONE` leaves PHASE=DONE in the state file
# and only `phase.sh clear` removes it, so DONE is the ordinary between-stories
# state - exactly the window the procedure tells you to refresh in. A refusal
# here would refuse the correct moment and teach people to delete the lock file.
new_project
printf 'STORY_ID=W-1\nPHASE=DONE\n' > "$PROJ/.claude/state/current-story.env"
out="$(refresh "$UP")"; rc=$?
assert_eq "a DONE story does not block a refresh" 0 "$rc"
rm -f "$PROJ/.claude/state/current-story.env"

# ---------------------------------------------------------------------------
describe "what it replaces, and what it refuses to touch"

new_project
out="$(refresh "$UP")"; rc=$?
assert_eq "it succeeds on a clean tree between stories" 0 "$rc"

assert_eq "an upstream-owned file is replaced" "upstream agent, a release later" "$(cat "$PROJ/.claude/agents/lead-po.md")"
assert_eq "so is a shipped profile"            "upstream profile" "$(cat "$PROJ/.claude/skills/stack-profiles/reference/python-uv.md")"
assert_eq "settings.json is copied"            "upstream settings" "$(cat "$PROJ/.claude/settings.json")"
assert_eq "and the state README"               "upstream state doc" "$(cat "$PROJ/.claude/state/README.md")"
assert_eq "a new upstream script arrives"      "echo new" "$(cat "$PROJ/scripts/brand-new.sh")"
assert_eq "a new suite arrives"                "upstream suite" "$(cat "$PROJ/.claude/tests/lib.test.sh")"

# THE case the prose got wrong. Upstream does not ship this file; a wholesale
# directory replace deletes it and says nothing.
assert_eq "the project's own profile survives" "PROJECT profile" \
  "$(cat "$PROJ/.claude/skills/stack-profiles/reference/tauri-react-webgl.md" 2>/dev/null)"
assert_contains "and the report says it was kept" "tauri-react-webgl.md" "$out"

# Project-owned, every one of them.
assert_eq "project.conf untouched"  "BOOTSTRAPPED=yes" "$(cat "$PROJ/.claude/harness/project.conf")"
assert_eq "docs untouched"          "project notes"    "$(cat "$PROJ/docs/wiki/stack.md")"
assert_eq ".gitignore untouched"    "node_modules/"    "$(cat "$PROJ/.gitignore")"
assert_eq "workflows untouched"     "project workflow" "$(cat "$PROJ/.github/workflows/gates.yml")"
assert_eq "a project script survives" "project bench"  "$(cat "$PROJ/scripts/bench.mjs")"
assert_eq "and a project script directory" "project helper" "$(cat "$PROJ/scripts/vitest/setup.ts")"

# EVERY directory the report calls REPLACED has actually been replaced, checked
# by content rather than by the report's own text. The report and the copy used
# to come from two separate loops over two separate lists, and nothing compared
# them: shortening the copy loop left all 28 assertions green while the report
# still printed `REPLACED .claude/hooks/` over a hook that still held OLD HOOK.
# A refresh that silently skips the phase lock and says it updated it is the
# worst thing this script can do, and the assertions above only happened to
# cover `agents`.
for d in agents commands skills hooks tests; do
  case "$out" in
    *"REPLACED  .claude/$d/"*) ;;
    *) _bad "report names .claude/$d" "not in the report"; continue ;;
  esac
  stale="$(grep -rl 'OLD ' "$PROJ/.claude/$d" 2>/dev/null | head -1)"
  if [ -n "$stale" ]; then
    _bad "REPLACED .claude/$d is true" "reported replaced, but $stale still holds the project's old content"
  else
    _ok "REPLACED .claude/$d is true"
  fi
done

# The two that need a human. Copying them blind loses project rules; the script
# leaves them alone and says so rather than pretending it merged them.
assert_eq "paths.conf is NOT overwritten" "OLD paths" "$(cat "$PROJ/.claude/harness/paths.conf")"
assert_eq "CLAUDE.md is NOT overwritten"  "OLD claude md" "$(cat "$PROJ/CLAUDE.md")"
assert_contains "and both are named for review" "paths.conf" "$out"
assert_contains "CLAUDE.md too"                 "CLAUDE.md"  "$out"

# ---------------------------------------------------------------------------
describe "it reports before it acts"

new_project
# Every file the script can write, fingerprinted before and after. The old
# assertion checked one file - `.claude/agents/lead-po.md` - which is protected
# by a DIFFERENT guard (`if [ "$DRY" = 0 ]` around the copy block), so making
# `act()` eval unconditionally left every assertion green while a dry run
# overwrote settings.json, state/README.md, three harness files and every
# scripts/*.sh. docs/ joined the list in HARNESS-040 (AC-4), once the refresh
# could write there.
before="$(find "$PROJ/.claude" "$PROJ/scripts" "$PROJ/CLAUDE.md" "$PROJ/docs" -type f -exec cksum {} \; 2>/dev/null | sort)"
out="$(refresh --dry-run "$UP")"; rc=$?
after="$(find "$PROJ/.claude" "$PROJ/scripts" "$PROJ/CLAUDE.md" "$PROJ/docs" -type f -exec cksum {} \; 2>/dev/null | sort)"
assert_eq "--dry-run succeeds" 0 "$rc"
assert_eq "and writes nothing at all" "$before" "$after"
assert_eq "and changes nothing" "OLD agent" "$(cat "$PROJ/.claude/agents/lead-po.md")"

# A dry run is a report, so it must work on the trees a report is most wanted
# on - including a dirty one, where the real run correctly refuses.
printf 'uncommitted\n' >> "$PROJ/docs/wiki/stack.md"
out="$(refresh --dry-run "$UP")"; rc=$?
assert_eq "--dry-run works on a dirty tree" 0 "$rc"
( cd "$PROJ" && git checkout -q -- . 2>/dev/null )
assert_contains "while still naming what it would keep" "tauri-react-webgl.md" "$out"
assert_contains "and the version it would move to" "2026-09-17" "$out"

# ===========================================================================
# HARNESS-040: the refresh ADDS a docs/ file upstream's docs-shipped.conf lists
# as `ship` when the project has none, and never overwrites one it has.
#
# Issue #104, Symptom A: `/audit-mutations` and the mutation-tester agent name
# docs/wiki/audits/TEMPLATE.md, the refresh left all of docs/** alone, and a
# project vendored before the template existed never received it - two
# re-vendors, nothing reported. Every needle below is a WHOLE LINE (`grep -cxF`)
# pinned byte for byte by the story's Contract, C-3, because a floating `ADDED`
# is satisfied by the KEPT line's neighbour and `KEPT` by the project-floors
# line. Files are compared with `cmp`, never through `$(cat)`, which strips the
# trailing bytes that make "byte-identical" mean anything.
# ===========================================================================

T_DOC="docs/wiki/audits/TEMPLATE.md"
ADDED_T="  ADDED     $T_DOC  (upstream ships it and you had no copy)"
KEPT_T="  KEPT      $T_DOC  (yours; upstream never overwrites docs/)"

# whole_line_count <line> <haystack>   Whole-line matches. A here-doc, not a
# pipe, for check-sigpipe.sh; no `|| printf 0`, for check-grep-count.sh -
# grep -c prints 0 itself.
whole_line_count() { grep -cxF -- "$1" <<WHOLE_HAY
$2
WHOLE_HAY
}

# report_lines_naming <needle> <haystack>   How many ADDED or KEPT report lines
# contain <needle>. The negative controls ask "is this path delivered or
# claimed in ANY wording", so the needle is the path and the line is restricted
# to the two report words - a whole-line needle there would pass on a line that
# names the path in different words.
report_lines_naming() {
  awk -v p="$1" '(index($0, "  ADDED ") == 1 || index($0, "  KEPT ") == 1) && index($0, p) { n++ }
                 END { print n + 0 }' <<REPORT_HAY
$2
REPORT_HAY
}

# added_lines_naming <path> <haystack>   How many ADDED lines contain <path>,
# whatever their padding or parenthesis: "never ADDED" is about the word.
added_lines_naming() {
  awk -v p="$1" 'index($0, "  ADDED ") == 1 && index($0, p) { n++ } END { print n + 0 }' <<ADDED_HAY
$2
ADDED_HAY
}

# docs_fingerprint   Every file under the project's docs/, with its checksum.
docs_fingerprint() { find "$PROJ/docs" -type f -exec cksum {} \; 2>/dev/null | sort; }

# ---------------------------------------------------------------------------
describe "HARNESS-040 AC-1  a docs file upstream ships and the project lacks is ADDED"

new_project
assert_eq "fixture: the project has docs/wiki/ and no audit template" "yes no" \
  "$([ -d "$PROJ/docs/wiki" ] && echo yes || echo no) $([ -e "$PROJ/$T_DOC" ] && echo yes || echo no)"
out="$(refresh "$UP")"; rc=$?
assert_eq "AC-1: the refresh exits 0" 0 "$rc"
if cmp -s "$UP/$T_DOC" "$PROJ/$T_DOC"; then
  _ok "AC-1: the project's missing audit template is added, byte-identical to upstream's"
else
  _bad "AC-1: the project's missing audit template is added, byte-identical to upstream's" \
    "$( [ -e "$PROJ/$T_DOC" ] && echo 'it exists but its bytes differ from upstream' || echo "$T_DOC was not created" )"
fi
assert_eq "AC-1: the ADDED line for it is printed exactly once" 1 "$(whole_line_count "$ADDED_T" "$out")"
assert_eq "AC-1 control: and no KEPT line for a file the project did not have" 0 "$(whole_line_count "$KEPT_T" "$out")"

# AC-3, first half, in the same run: upstream HOLDS these two, and its conf
# does not list either as `ship` (product-brief.md is `written`). Only the list
# is delivered.
if [ -e "$PROJ/docs/wiki/product-brief.md" ]; then
  _bad "AC-3: a page upstream holds but declares written is NOT created" "docs/wiki/product-brief.md was created"
else
  _ok "AC-3: a page upstream holds but declares written is NOT created"
fi
if [ -e "$PROJ/docs/wiki/README.md" ]; then
  _bad "AC-3: a docs file upstream holds but does not list is NOT created" "docs/wiki/README.md was created"
else
  _ok "AC-3: a docs file upstream holds but does not list is NOT created"
fi
assert_eq "AC-3: no ADDED or KEPT line names the written page" 0 \
  "$(report_lines_naming "docs/wiki/product-brief.md" "$out")"
assert_eq "AC-3: no ADDED or KEPT line names the unlisted file" 0 \
  "$(report_lines_naming "docs/wiki/README.md" "$out")"
assert_eq "AC-3: the project's own docs are untouched" "project notes" "$(cat "$PROJ/docs/wiki/stack.md")"

# ---------------------------------------------------------------------------
describe "HARNESS-040 AC-2  a copy the project already has is KEPT, never overwritten"

# Content a sloppy copy would not reproduce: no final newline.
new_project
mkdir -p "$PROJ/docs/wiki/audits"
printf '# our audit template\nedited for this project' > "$PROJ/$T_DOC"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a project-edited template" >/dev/null 2>&1 )
cp "$PROJ/$T_DOC" "$WORK/template.before"
out="$(refresh "$UP")"; rc=$?
assert_eq "AC-2: the refresh exits 0" 0 "$rc"
if cmp -s "$WORK/template.before" "$PROJ/$T_DOC"; then
  _ok "AC-2: an edited project template survives byte-identical"
else
  _bad "AC-2: an edited project template survives byte-identical" \
    "$( cmp -s "$UP/$T_DOC" "$PROJ/$T_DOC" && echo "it was overwritten with upstream's" || echo 'its bytes changed' )"
fi
assert_eq "AC-2: the KEPT line for it is printed exactly once" 1 "$(whole_line_count "$KEPT_T" "$out")"
assert_eq "AC-2: and no ADDED line names it" 0 "$(added_lines_naming "$T_DOC" "$out")"

# The same holds when the project's copy is upstream's own bytes: KEPT, never
# ADDED - "have a copy" is the test, not "have a different copy".
new_project
mkdir -p "$PROJ/docs/wiki/audits"
cp "$UP/$T_DOC" "$PROJ/$T_DOC"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "upstream's template, already here" >/dev/null 2>&1 )
out="$(refresh "$UP")"; rc=$?
assert_eq "AC-2 identical: the refresh exits 0" 0 "$rc"
if cmp -s "$UP/$T_DOC" "$PROJ/$T_DOC"; then
  _ok "AC-2 identical: the project's copy is still upstream's bytes"
else
  _bad "AC-2 identical: the project's copy is still upstream's bytes" "it changed"
fi
assert_eq "AC-2 identical: an identical copy is reported KEPT, once" 1 "$(whole_line_count "$KEPT_T" "$out")"
assert_eq "AC-2 identical: and never ADDED" 0 "$(added_lines_naming "$T_DOC" "$out")"

# ---------------------------------------------------------------------------
describe "HARNESS-040 AC-3  an upstream that ships no docs-shipped.conf adds nothing"

# A COPY of $UP with the conf removed and committed away, as the half-a/half-b
# trees are built - never a mutation of $UP, which later blocks reuse. It still
# HOLDS the template, so the only thing missing is the list: a refresh that
# delivered docs/ files without reading a list would add it here.
NOCONF="$WORK/upstream-noconf"
rm -rf "$NOCONF"; cp -r "$UP" "$NOCONF"
rm -f "$NOCONF/.claude/harness/docs-shipped.conf"
( cd "$NOCONF" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "an upstream from before the list" >/dev/null 2>&1 )
assert_eq "fixture: the no-conf upstream still holds the template, and no conf" "yes no" \
  "$([ -f "$NOCONF/$T_DOC" ] && echo yes || echo no) $([ -e "$NOCONF/.claude/harness/docs-shipped.conf" ] && echo yes || echo no)"
new_project
before="$(docs_fingerprint)"
out="$(refresh "$NOCONF")"; rc=$?
after="$(docs_fingerprint)"
assert_eq "AC-3 no conf: the refresh exits 0" 0 "$rc"
assert_eq "AC-3 no conf: no ADDED or KEPT line names a docs/ path" 0 "$(report_lines_naming "docs/" "$out")"
assert_eq "AC-3 no conf: nothing under the project's docs/ is created or changed" "$before" "$after"

# ---------------------------------------------------------------------------
describe "HARNESS-040 AC-4  a dry run reports the ADDED line and writes nothing"

new_project
before="$(docs_fingerprint)"
out="$(refresh --dry-run "$UP")"; rc=$?
after="$(docs_fingerprint)"
assert_eq "AC-4: the dry run exits 0" 0 "$rc"
assert_eq "AC-4: the dry run prints the ADDED line exactly once" 1 "$(whole_line_count "$ADDED_T" "$out")"
assert_eq "AC-4: and says it wrote nothing" 1 "$(whole_line_count "Dry run: nothing was written." "$out")"
if [ -e "$PROJ/$T_DOC" ]; then
  _bad "AC-4: the template it would add still does not exist" "$T_DOC was created by a dry run"
else
  _ok "AC-4: the template it would add still does not exist"
fi
assert_eq "AC-4: every file under docs/ is unchanged" "$before" "$after"

new_project
mkdir -p "$PROJ/docs/wiki/audits"
printf '# our audit template\nedited for this project' > "$PROJ/$T_DOC"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a project-edited template" >/dev/null 2>&1 )
out="$(refresh --dry-run "$UP")"; rc=$?
assert_eq "AC-4 with a copy: the dry run prints the KEPT line exactly once" 1 "$(whole_line_count "$KEPT_T" "$out")"
assert_eq "AC-4 with a copy: and no ADDED line names it" 0 "$(added_lines_naming "$T_DOC" "$out")"

# ---------------------------------------------------------------------------
describe "it names the files of yours it is about to overwrite"

# H26, from the field. A project vendors the harness, fixes a harness defect
# locally WITH TESTS, and the next refresh removes the fix and the assertions
# that pin it in one operation - because both live inside the replaced set. The
# selftest is green afterwards, since the tests that would have failed went with
# the code. Nothing reports anything.
#
# The report asks for one `cmp` per replaced file. That does not survive contact
# with a real refresh: going 13 -> 28 here, nearly every harness file differs
# because UPSTREAM moved on, and a list of dozens means nothing. The useful
# question is not "does this differ" but "did YOU change it", and those need a
# third reference point.
#
# Upstream is a git checkout, so there is one: hash the downstream copy and ask
# whether that blob has ever existed in upstream's object store. Present means
# the project is simply BEHIND - the ordinary case, and silent. Absent means the
# content was never upstream's, so somebody here wrote it.
new_project
# Behind: the project holds the previous release's version of an upstream file.
printf 'upstream agent\n'    > "$PROJ/.claude/agents/lead-po.md"
# Changed: content upstream has never shipped, in a file upstream owns.
printf 'upstream hook\n# a local fix this project made\n' > "$PROJ/.claude/hooks/phase-guard.sh"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a local harness fix" >/dev/null 2>&1 )

out="$(refresh --dry-run "$UP")"
locals="$(printf '%s\n' "$out" | grep 'LOCAL' || true)"
assert_contains "a file you changed is named before it is replaced" "phase-guard.sh" "$locals"
# THE OTHER HALF, and the one that makes it a signal rather than a wall of text.
# A warning that always prints is not a warning.
case "$locals" in
  *lead-po.md*) _bad "while merely being behind is silent" "being behind was reported: $locals" ;;
  *) _ok "while merely being behind is silent" ;;
esac

# Said in the DRY RUN, because the whole value is seeing it before the files go.
case "$out" in
  *"Dry run: nothing was written"*) _ok "and said before anything is written" ;;
  *) _bad "and said before anything is written" "not a dry run: $out" ;;
esac

# Nothing local at all: completely quiet. Without this a check that prints the
# same line for every replaced file passes the assertions above.
new_project
for f in .claude/agents/lead-po.md .claude/commands/advance-story.md \
         .claude/hooks/phase-guard.sh .claude/tests/lib.test.sh \
         .claude/skills/stack-profiles/reference/python-uv.md \
         .claude/settings.json .claude/state/README.md \
         .claude/harness/phases.conf .claude/harness/rules.md; do
  mkdir -p "$PROJ/$(dirname "$f")"; cp "$UP/$f" "$PROJ/$f"
done
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "exactly what upstream ships" >/dev/null 2>&1 )
out="$(refresh --dry-run "$UP")"
assert_eq "a project holding upstream's own files is told nothing" "" \
  "$(printf '%s\n' "$out" | grep 'LOCAL' || true)"

# An upstream that is not a repository cannot answer the question, and a check
# that cannot run must not read as a clean result.
out="$(refresh --dry-run "$WORK/half-b-full")" 2>/dev/null
mkdir -p "$WORK/half-b-full/.claude/hooks" "$WORK/half-b-full/scripts"
printf 'x\n' > "$WORK/half-b-full/.claude/hooks/phase-guard.sh"
out="$(refresh --dry-run "$WORK/half-b-full")"
assert_contains "an upstream with no history says it could not check" "could not check" "$out"


# ---------------------------------------------------------------------------
describe "LOCAL covers scripts/, where the production code lives"

# The blind spot, reported by a consuming project mid-refresh. The LOCAL loop
# walked .claude/{agents,commands,skills,hooks,tests} and five named
# .claude/harness files. `scripts/*.sh` was blanket REPLACED with no check at
# all - so a project that fixed a harness DEFECT in scripts/ had the fix
# overwritten without ever being named, while the alarm cheerfully named the
# test file beside it.
#
# That is the H26 case with the halves swapped: the test was reported and the
# CODE was not. WORLD-090's production fix to check-sigpipe.sh was in exactly
# that position when they noticed.
new_project
printf 'upstream sigpipe\n# a local fix to the GUARD, not to its test\n' \
  > "$PROJ/scripts/check-sigpipe.sh"
printf 'upstream sigpipe\n' > "$UP/scripts/check-sigpipe.sh"
( cd "$UP" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "upstream ships the guard" >/dev/null 2>&1 )
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a local fix in scripts" >/dev/null 2>&1 )

out="$(refresh --dry-run "$UP")"
assert_contains "a local fix under scripts/ is named before it is replaced" \
  "scripts/check-sigpipe.sh" "$(printf '%s\n' "$out" | grep 'LOCAL' || true)"

# The quiet half, same rule as above: a scripts/ file that merely matches
# upstream must stay silent, or the check is a wall of text rather than a
# warning.
printf 'upstream sigpipe\n' > "$PROJ/scripts/check-sigpipe.sh"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "match upstream" >/dev/null 2>&1 )
out="$(refresh --dry-run "$UP")"
case "$(printf '%s\n' "$out" | grep 'LOCAL' || true)" in
  *check-sigpipe*) _bad "while a scripts/ file matching upstream is silent" \
                        "reported anyway: $out" ;;
  *) _ok "while a scripts/ file matching upstream is silent" ;;
esac

# ---------------------------------------------------------------------------
describe "LOCAL asks whether upstream ever SHIPPED the blob, not whether its store holds it"

# HARNESS-012. The check hashes the downstream file and asked upstream's object
# store `git cat-file -e <blob>`. That answers "does this object EXIST", not
# "is it REACHABLE from a ref" - and the two differ for every blob that entered
# the store off a branch that was later deleted: an experiment, a dropped
# stash, an abandoned rebase, a fetched PR ref. The blob survives the branch
# until a gc that may not run for weeks, so the alarm concludes upstream
# shipped the content and stays silent for precisely the files it exists to
# name. Measured on this repository at release 50: nine dangling blobs, four
# of a consuming project's local fixes suppressed by them - and HARNESS-010's
# own RED phase put the blobs there, on a throwaway branch it correctly
# deleted afterwards.
#
# So a dangling blob is MADE here, one per walk the check performs, because
# AC-3 says all three call sites must ask the corrected question and a fixture
# at one walk cannot tell a fix at one walk from a fix at three:
#
#   walk 1   .claude/{agents,commands,skills,hooks,tests}   -> .claude/hooks/phase-guard.sh
#   walk 2   scripts/*.sh                                   -> scripts/gates.sh
#   walk 3   the five named files                           -> .claude/harness/rules.md
#
# The recipe: commit the downstream content on a throwaway branch of upstream,
# switch back, delete the branch. `cat-file -e` still says YES; `rev-list
# --objects --all` says NO. The fixture IS the probe, and both answers are
# asserted below before the report is read, so that a git which pruned the
# blob on branch delete would fail HERE rather than let the AC-1 assertion pass
# for the ordinary reason.
#
# THE NEEDLE. The report's explanatory paragraph contains the word LOCAL
# (`  LOCAL - upstream has never shipped your copy`), so `grep LOCAL` matches
# whether or not any file was listed, and the KEPT/REPLACED report names the
# same filenames. Every assertion here reads the per-file line shape
# `    LOCAL     <path>` - four spaces, LOCAL, five spaces, the path - and
# matches it whole, so a file is either on its own line in the block or it is
# not. `grep -cx` prints 0 and exits 1 on no match; the count is what is
# compared and the status is discarded, which is the fallback-free shape the
# grep-count guard permits.
local_line_count() { printf '%s\n' "$2" | grep -cx "    LOCAL     $1"; }

# THE RELEASE SET, COMPUTED BY HAND (HARNESS-013, C-1). Since release 52 the
# script counts a blob as shipped when it is reachable from HEAD, from the
# default branch, or from `refs/remotes/origin/<default>` when that ref exists -
# and from nothing else. Every fixture below that injects a ref proves, before
# it reads the report, that its blob IS reachable from the injected ref and is
# NOT reachable from this set. Without that proof a red could come from a
# fixture that did not arrange what it claims, and a green from one that
# arranged too much. None of these helpers read the script: they are the
# suite's own reading of the Contract, so a mutation of the script's set cannot
# move them.
release_ids() { # <repo> <default branch, or "">: object ids C-1's set reaches
  starts="HEAD"
  [ -n "$2" ] && starts="$starts $2"
  [ -n "$2" ] && git -C "$1" rev-parse --verify --quiet "refs/remotes/origin/$2" >/dev/null 2>&1 \
    && starts="$starts refs/remotes/origin/$2"
  # shellcheck disable=SC2086  # a word list of ref names chosen above, never user data
  git -C "$1" rev-list --objects $starts 2>/dev/null | awk '{print $1}'
}
ref_ids()  { git -C "$1" rev-list --objects "$2" 2>/dev/null | awk '{print $1}'; }  # <repo> <ref>
count_id() { printf '%s\n' "$1" | grep -cx "$2"; }                                  # <id list> <id>

# Upstream ships a scripts/ file for walk 2 to compare against. (rules.md and
# phase-guard.sh are already committed above, in the fixture's first release.)
printf 'upstream gates\n' > "$UP/scripts/gates.sh"
( cd "$UP" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "upstream ships gates.sh" >/dev/null 2>&1 )

# The project: one local fix per walk, plus a file it is merely BEHIND on.
FIX1='upstream hook
# a local fix, once pushed to a throwaway branch upstream'
FIX2='upstream gates
# a local fix, once pushed to a throwaway branch upstream'
FIX3='upstream rules
# a local fix, once pushed to a throwaway branch upstream'
new_project
printf '%s\n' "$FIX1" > "$PROJ/.claude/hooks/phase-guard.sh"
printf '%s\n' "$FIX2" > "$PROJ/scripts/gates.sh"
printf '%s\n' "$FIX3" > "$PROJ/.claude/harness/rules.md"
printf 'upstream agent\n'  > "$PROJ/.claude/agents/lead-po.md"    # one release behind, AC-2
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "three local harness fixes" >/dev/null 2>&1 )

# Put the same three blobs into upstream's store on a branch, then delete the
# branch. `checkout -` returns to the default branch, so HEAD's tree is exactly
# what it was and the later "not a release" block sees the same source.
( cd "$UP" && git checkout -q -b throwaway 2>/dev/null \
    && printf '%s\n' "$FIX1" > .claude/hooks/phase-guard.sh \
    && printf '%s\n' "$FIX2" > scripts/gates.sh \
    && printf '%s\n' "$FIX3" > .claude/harness/rules.md \
    && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "an experiment, later deleted" >/dev/null 2>&1 \
    && git checkout -q - 2>/dev/null && git branch -qD throwaway 2>/dev/null )

# The fixture must reproduce the defect's precondition, or the assertion after
# it is testing the ordinary never-shipped path and would pass against the
# unfixed script for the wrong reason. Hashed FROM the project, the way the
# script hashes them, so line-ending conversion is the same on both sides.
up_reachable_ids="$(git -C "$UP" rev-list --objects --all | awk '{print $1}')"
for f in .claude/hooks/phase-guard.sh scripts/gates.sh .claude/harness/rules.md; do
  h="$(git -C "$PROJ" hash-object "$f")"
  git -C "$UP" cat-file -e "$h" 2>/dev/null; rc=$?
  assert_eq "fixture: $f exists in upstream's store, so the old question says shipped" 0 "$rc"
  assert_eq "fixture: and no ref of upstream reaches it, so the new question says never" 0 \
    "$(printf '%s\n' "$up_reachable_ids" | grep -cx "$h")"
done

out="$(refresh --dry-run "$UP")"
# AC-1 and AC-3: one assertion per walk. A fix at one call site leaves the
# other two of these red, which is what makes them the AC-3 control.
assert_eq "a local fix whose blob dangles in upstream is named LOCAL - walk 1, .claude/hooks" 1 \
  "$(local_line_count .claude/hooks/phase-guard.sh "$out")"
assert_eq "and at walk 2, scripts/*.sh, which asks the same question of its own blob" 1 \
  "$(local_line_count scripts/gates.sh "$out")"
assert_eq "and at walk 3, the named files, whose line has its own copy of the test" 1 \
  "$(local_line_count .claude/harness/rules.md "$out")"
# AC-2, in the same run: reachable from an older commit is BEHIND, and silent.
# A fix that reads reachability off anything narrower than upstream's history
# turns every behind-by-a-release file into an alarm nobody reads.
assert_eq "while a file from an older release, in the same run, is still not named" 0 \
  "$(local_line_count .claude/agents/lead-po.md "$out")"

# HARNESS-013, AC-5: the same content on a LOCAL BRANCH THAT SURVIVES, never
# merged into the default branch. Through release 51 this fixture asserted the
# opposite - a surviving ref of any name silenced the alarm, because `--all`
# counts every ref as a release. That is the HARNESS-010 incident before its
# push: the throwaway branch existed in this very clone, and a dry run from it
# would have been silent about the four files HARNESS-012 was written to name.
# Under Option B (PO-1) a release is the default branch, its origin
# counterpart, and HEAD; an unmerged local branch is none of those, so the
# three files stay LOCAL. The fixture proves both halves of its precondition
# first: reachable from `survives`, and from nothing in the release set.
( cd "$UP" && git checkout -q -b survives 2>/dev/null \
    && printf '%s\n' "$FIX1" > .claude/hooks/phase-guard.sh \
    && printf '%s\n' "$FIX2" > scripts/gates.sh \
    && printf '%s\n' "$FIX3" > .claude/harness/rules.md \
    && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "on a side branch, never merged" >/dev/null 2>&1 \
    && git checkout -q - 2>/dev/null )
survives_ids="$(ref_ids "$UP" survives)"; release_set="$(release_ids "$UP" master)"
for f in .claude/hooks/phase-guard.sh scripts/gates.sh .claude/harness/rules.md; do
  h="$(git -C "$PROJ" hash-object "$f")"
  assert_eq "fixture: $f is reachable from the unmerged local branch 'survives'" 1 "$(count_id "$survives_ids" "$h")"
  assert_eq "fixture: and from nothing in the release set (HEAD, master)" 0 "$(count_id "$release_set" "$h")"
done
out="$(refresh --dry-run "$UP")"
assert_eq "an unmerged local branch is not a release: its content is LOCAL - walk 1, .claude/hooks" 1 \
  "$(local_line_count .claude/hooks/phase-guard.sh "$out")"
assert_eq "and at walk 2, scripts/*.sh" 1 "$(local_line_count scripts/gates.sh "$out")"
assert_eq "and at walk 3, the named files" 1 "$(local_line_count .claude/harness/rules.md "$out")"

# AC-5's control, which is also HARNESS-012's AC-1 control kept under the new
# definition: merge `survives` into the default branch and the same three fall
# silent. HEAD is DETACHED at the pre-merge commit while the report is read, so
# that `master` is the ONLY member of the release set that reaches the blobs.
# From a checkout sitting on master, HEAD reaches everything master does and a
# set that dropped `$src_default` would be invisible; from here it is not
# (DV-3). Detached, so the "not a release" NOTE has no branch name to print.
# Green against release 51 too, since `--all` reaches a merged commit either
# way; what earns it is the "drop $src_default" mutation in the handoff.
( cd "$UP" && git -c user.email=t@t -c user.name=t merge -q --no-ff --no-edit survives >/dev/null 2>&1 \
    && git checkout -q --detach master~1 2>/dev/null )
head_ids="$(ref_ids "$UP" HEAD)"; master_ids="$(ref_ids "$UP" master)"
assert_eq "fixture: HEAD is detached off the default branch for this report" "" \
  "$(git -C "$UP" symbolic-ref -q HEAD 2>/dev/null || true)"
for f in .claude/hooks/phase-guard.sh scripts/gates.sh .claude/harness/rules.md; do
  h="$(git -C "$PROJ" hash-object "$f")"
  assert_eq "fixture: $f is reachable from master once 'survives' is merged" 1 "$(count_id "$master_ids" "$h")"
  assert_eq "fixture: and not from the detached HEAD, so only the default branch vouches for it" 0 "$(count_id "$head_ids" "$h")"
done
out="$(refresh --dry-run "$UP")"
assert_eq "once the branch is merged into the default branch, walk 1 is silent" 0 \
  "$(local_line_count .claude/hooks/phase-guard.sh "$out")"
assert_eq "and walk 2" 0 "$(local_line_count scripts/gates.sh "$out")"
assert_eq "and walk 3" 0 "$(local_line_count .claude/harness/rules.md "$out")"
( cd "$UP" && git checkout -q master 2>/dev/null )

# ---------------------------------------------------------------------------
describe "LOCAL counts only the release line as shipped: HEAD, the default branch, and its origin counterpart"

# HARNESS-013. Release 51 asked `rev-list --objects --all`, and `--all` is
# every ref plus HEAD - so every ref was a release. A live stash, a fetched PR
# kept as a ref, and a stale remote-tracking branch each silenced the alarm for
# exactly the files it exists to name. The third is the one that bit: any clone
# that fetched while HARNESS-010's throwaway branch existed on origin, and has
# not run `git fetch --prune` since, still holds
# `refs/remotes/origin/xcompare/HARNESS-010`, and against that clone the four
# files HARNESS-012 brought back drop out of the report again (17 -> 13,
# reproduced with the real commit; story, M-3). Pruning is not something a
# refresh can rely on: this repository's own clone held 40 stale tracking refs.
#
# The user's decision (PO-1, Option B): a release is the default branch, its
# `origin` counterpart, and whatever is checked out. Nothing else. The fixtures
# have no remote, so each ref is made with `update-ref` - which is what the
# real case is too: a ref the clone holds. Every injected ref is proved to
# reach its blob, and the release set (release_ids, above) proved NOT to, before
# any report is read.
#
# One run carries all three positives together with the quiet half (AC-4): a
# file at an OLDER release of the default branch, and a file committed on it,
# both silent in the SAME report that names the other three. A set narrowed to
# tip trees, or to nothing, fails here beside the assertion it was written for.

# A commit on top of master whose only ref is <ref>. The working tree and
# master are left exactly as found.
side_commit() { # <ref> <file> <content>
  ( cd "$UP" && git checkout -q -b _side master 2>/dev/null \
      && printf '%s\n' "$3" > "$2" && git add -A >/dev/null 2>&1 \
      && git -c user.email=t@t -c user.name=t commit -qm "$1" >/dev/null 2>&1 \
      && git update-ref "$1" HEAD \
      && git checkout -q master 2>/dev/null && git branch -qD _side >/dev/null 2>&1 )
}

STASHED='upstream hook
# a fix sitting in a stash of the upstream checkout, never committed'
STALE='upstream gates
# pushed to a throwaway branch, deleted on origin, never pruned in this clone'
PULLED='upstream rules
# a pull request fetched as a ref and never merged'

new_project
printf '%s\n' "$STASHED" > "$PROJ/.claude/hooks/phase-guard.sh"   # AC-1, walk 1
printf '%s\n' "$STALE"   > "$PROJ/scripts/gates.sh"               # AC-2, walk 2
printf '%s\n' "$PULLED"  > "$PROJ/.claude/harness/rules.md"       # AC-3, walk 3
printf 'upstream suite\n' > "$PROJ/.claude/tests/lib.test.sh"     # AC-1 control: on master since the first release
printf 'upstream agent\n' > "$PROJ/.claude/agents/lead-po.md"     # AC-4: an OLDER release, not the tip
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "three local fixes upstream once saw, off its release line" >/dev/null 2>&1 )

# AC-1: the stash. Written into the tracked file on master and stashed, so the
# working tree is back to master's and `refs/stash` alone reaches the blob.
( cd "$UP" && printf '%s\n' "$STASHED" > .claude/hooks/phase-guard.sh \
    && git -c user.email=t@t -c user.name=t stash -q >/dev/null 2>&1 )
# AC-2: the stale tracking branch, the sharp case.
side_commit refs/remotes/origin/xcompare/exp scripts/gates.sh "$STALE"
# AC-3: the fetched PR.
side_commit refs/pull/7/head .claude/harness/rules.md "$PULLED"

release_set="$(release_ids "$UP" master)"
for spec in "refs/stash|.claude/hooks/phase-guard.sh" \
            "refs/remotes/origin/xcompare/exp|scripts/gates.sh" \
            "refs/pull/7/head|.claude/harness/rules.md"; do
  ref="${spec%%|*}"; f="${spec#*|}"
  h="$(git -C "$PROJ" hash-object "$f")"
  assert_eq "fixture: $f is reachable from $ref" 1 "$(count_id "$(ref_ids "$UP" "$ref")" "$h")"
  assert_eq "fixture: and from nothing in the release set (HEAD, master)" 0 "$(count_id "$release_set" "$h")"
done

out="$(refresh --dry-run "$UP")"
assert_eq "fixture: the run answered rather than refusing to check" 0 \
  "$(printf '%s\n' "$out" | grep -c 'could not check')"
assert_eq "a live stash is not a release: content reachable only from refs/stash is LOCAL" 1 \
  "$(local_line_count .claude/hooks/phase-guard.sh "$out")"
assert_eq "while a file committed on the default branch, in the same run, is not" 0 \
  "$(local_line_count .claude/tests/lib.test.sh "$out")"
assert_eq "a stale remote-tracking branch is not a release: content reachable only from origin/xcompare/exp is LOCAL" 1 \
  "$(local_line_count scripts/gates.sh "$out")"
assert_eq "a fetched PR ref is not a release: content reachable only from refs/pull/7/head is LOCAL" 1 \
  "$(local_line_count .claude/harness/rules.md "$out")"
assert_eq "while a file from an OLDER release of the default branch, in the same run, is still not named" 0 \
  "$(local_line_count .claude/agents/lead-po.md "$out")"

# AC-3's control: the PR merged into the default branch. HEAD detached at the
# pre-merge commit for the same reason as the AC-5 control above - master must
# be the only member of the set that vouches for the blob, or the mutation
# that drops it is invisible. The stash is still there and still LOCAL in the
# same report, so the silence is specific to the merged file and not a mute.
( cd "$UP" && git -c user.email=t@t -c user.name=t merge -q --no-ff --no-edit refs/pull/7/head >/dev/null 2>&1 \
    && git checkout -q --detach master~1 2>/dev/null )
h="$(git -C "$PROJ" hash-object .claude/harness/rules.md)"
assert_eq "fixture: HEAD is detached off the default branch for this report" "" \
  "$(git -C "$UP" symbolic-ref -q HEAD 2>/dev/null || true)"
assert_eq "fixture: the PR's content is reachable from master once merged" 1 "$(count_id "$(ref_ids "$UP" master)" "$h")"
assert_eq "fixture: and not from the detached HEAD" 0 "$(count_id "$(ref_ids "$UP" HEAD)" "$h")"
out="$(refresh --dry-run "$UP")"
assert_eq "once the PR is merged into the default branch, the same content is not listed" 0 \
  "$(local_line_count .claude/harness/rules.md "$out")"
assert_eq "while the stash, in the same run, is still LOCAL" 1 \
  "$(local_line_count .claude/hooks/phase-guard.sh "$out")"
( cd "$UP" && git checkout -q master 2>/dev/null )

# AC-2's control, and the quiet-half case that rules out every set without
# `origin/<default>`: the local default branch is BEHIND its origin, and the
# file's content is on the commit it has not merged yet. That is a project
# refreshed from a newer clone and now checked against an older one; measured
# on real trees, dropping this ref costs four false alarms (story, M-5). The
# fixture is not a clone, so origin/HEAD does not exist and the script resolves
# the default through its `master` candidate - the same path a real checkout
# with no origin/HEAD takes, which is common.
BEHIND='upstream command
# shipped in a release this checkout has fetched but not yet merged'
printf '%s\n' "$BEHIND" > "$PROJ/.claude/commands/advance-story.md"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a file from a release the upstream checkout has not merged" >/dev/null 2>&1 )
( cd "$UP" && printf '%s\n' "$BEHIND" > .claude/commands/advance-story.md \
    && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a release the local branch has not merged" >/dev/null 2>&1 \
    && git update-ref refs/remotes/origin/master HEAD \
    && git reset -q --hard HEAD~1 >/dev/null 2>&1 )
h="$(git -C "$PROJ" hash-object .claude/commands/advance-story.md)"
assert_eq "fixture: master is an ancestor of origin/master, i.e. behind it" 0 \
  "$(git -C "$UP" merge-base --is-ancestor master refs/remotes/origin/master; echo $?)"
assert_eq "fixture: the content is reachable from refs/remotes/origin/master" 1 \
  "$(count_id "$(ref_ids "$UP" refs/remotes/origin/master)" "$h")"
assert_eq "fixture: and from neither HEAD nor master" 0 \
  "$(count_id "$(git -C "$UP" rev-list --objects HEAD master | awk '{print $1}')" "$h")"
out="$(refresh --dry-run "$UP")"
assert_eq "a local default branch behind its origin: content reachable only from origin/master is not listed" 0 \
  "$(local_line_count .claude/commands/advance-story.md "$out")"
assert_eq "while the stash, in the same run, is still LOCAL" 1 \
  "$(local_line_count .claude/hooks/phase-guard.sh "$out")"
# Bring master back level with its origin for the blocks below; the refs made
# here (stash, xcompare/exp, pull/7, origin/master) are deliberately left in
# place, since every later block runs against a checkout that holds them.
( cd "$UP" && git merge -q --ff-only refs/remotes/origin/master >/dev/null 2>&1 )

# AC-6: an upstream whose default branch cannot be identified. No origin/HEAD,
# no main, no master - the script's NOTE already declines to classify such a
# checkout, and the alarm follows the same rule: the set is HEAD alone. Unable
# to tell is not evidence that content was never released, so a file from the
# checked-out branch's history is silent. The stash is still excluded, because
# excluding it never depended on finding a default branch. Two commits, so the
# history guard does not answer first and turn this into an AC-7 case.
UP2="$WORK/upstream-trunk"
rm -rf "$UP2"; mkdir -p "$UP2/.claude/hooks" "$UP2/.claude/tests" "$UP2/.claude/harness" "$UP2/scripts"
printf 'trunk hook\n'    > "$UP2/.claude/hooks/phase-guard.sh"
printf 'trunk suite\n'   > "$UP2/.claude/tests/lib.test.sh"
printf 'echo trunk\n'    > "$UP2/scripts/brand-new.sh"
printf '2026-09-24\n'    > "$UP2/.claude/harness/VERSION"
( cd "$UP2" && git init -q -b trunk 2>/dev/null && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "trunk, one release ago" >/dev/null 2>&1 \
    && printf 'trunk hook\n# a release later\n' > .claude/hooks/phase-guard.sh \
    && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "trunk moves on" >/dev/null 2>&1 \
    && printf 'trunk suite\n# left in a stash\n' > .claude/tests/lib.test.sh \
    && git -c user.email=t@t -c user.name=t stash -q >/dev/null 2>&1 )
new_project
printf 'trunk hook\n'                   > "$PROJ/.claude/hooks/phase-guard.sh"  # trunk's older release
printf 'trunk suite\n# left in a stash\n' > "$PROJ/.claude/tests/lib.test.sh"    # the stash
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "from an upstream with no nameable default" >/dev/null 2>&1 )
nameable=0
for cand in main master; do
  git -C "$UP2" rev-parse --verify --quiet "$cand" >/dev/null 2>&1 && nameable=$((nameable+1))
done
git -C "$UP2" symbolic-ref -q refs/remotes/origin/HEAD >/dev/null 2>&1 && nameable=$((nameable+1))
assert_eq "fixture: no origin/HEAD, no main, no master - the script cannot name a default branch" 0 "$nameable"
assert_eq "fixture: and two commits, so the history guard does not answer first" 2 \
  "$(git -C "$UP2" rev-list --count HEAD)"
hook_h="$(git -C "$PROJ" hash-object .claude/hooks/phase-guard.sh)"
stash_h="$(git -C "$PROJ" hash-object .claude/tests/lib.test.sh)"
head2_ids="$(ref_ids "$UP2" HEAD)"
assert_eq "fixture: the hook's content is reachable from the checked-out branch" 1 "$(count_id "$head2_ids" "$hook_h")"
assert_eq "fixture: the stashed content is reachable from refs/stash" 1 "$(count_id "$(ref_ids "$UP2" refs/stash)" "$stash_h")"
assert_eq "fixture: and not from the checked-out branch" 0 "$(count_id "$head2_ids" "$stash_h")"
out="$(refresh --dry-run "$UP2")"
assert_eq "fixture: the run answered rather than refusing to check" 0 \
  "$(printf '%s\n' "$out" | grep -c 'could not check')"
assert_eq "with no nameable default branch, content from the checked-out branch is not listed" 0 \
  "$(local_line_count .claude/hooks/phase-guard.sh "$out")"
assert_eq "while content reachable only from refs/stash, in the same fixture, is LOCAL" 1 \
  "$(local_line_count .claude/tests/lib.test.sh "$out")"

# ---------------------------------------------------------------------------
describe "LOCAL refuses to answer from a source with no usable history"

# The check asks whether upstream's OBJECT STORE holds a blob matching ours. It
# therefore needs upstream's HISTORY, not merely its current tree. Against a
# source built by `git archive` + `git init` - one commit, no past - every file
# of ours that upstream shipped in an EARLIER release matches nothing, and the
# report becomes confident nonsense.
#
# Measured upstream: five files reported LOCAL where the truth was one.
#
# The existing `else` branch already refuses to read "not a git checkout at all"
# as a clean result. A one-commit checkout passes `rev-parse --git-dir` and so
# sails past it, which is the worse failure of the two: it answers.
SHALLOW="$WORK/shallow-upstream"
rm -rf "$SHALLOW"; mkdir -p "$SHALLOW"
( cd "$UP" && git archive HEAD ) | ( cd "$SHALLOW" && tar -x )
( cd "$SHALLOW" && git init -q . && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "one commit, no past" >/dev/null 2>&1 )

new_project
out="$(refresh --dry-run "$SHALLOW")"
assert_contains "a source with a single commit says it could not check" \
  "could not check" "$out"

# And the control: the ordinary two-commit fixture still answers, so the guard
# above cannot be satisfied by refusing to check everywhere.
out="$(refresh --dry-run "$UP")"
case "$out" in
  *"could not check"*) _bad "while a source with real history still answers" \
                            "refused to check against a normal upstream: $out" ;;
  *) _ok "while a source with real history still answers" ;;
esac

# ---------------------------------------------------------------------------
describe "the source ref is named when it is not a release"

# The error this prevents, and it happened: this repository's clone was left
# checked out on a FEATURE BRANCH whose VERSION said 38. A consuming project
# read that, concluded release 38 had shipped, refreshed to it, and stamped a
# version no upstream release carries - which is precisely the confusion the
# VERSION file exists to end.
#
# It had examined the ref thoroughly - diffed it, confirmed comment-only, re-ran
# its apply checks - and never asked its STATUS. A ref can be fully examined and
# still not be a release, so the refresh says so rather than leaving it to the
# reader to think of the question.
( cd "$UP" && git checkout -q -b some-feature 2>/dev/null
  printf '99\n' > "$UP/.claude/harness/VERSION"
  git add -A >/dev/null 2>&1
  git -c user.email=t@t -c user.name=t commit -qm "unreleased work" >/dev/null 2>&1 )

new_project
out="$(refresh --dry-run "$UP")"
assert_contains "an unmerged source branch is named as unreleased" "not a release" "$out"
assert_contains "and the branch is named, so it can be checked" "some-feature" "$out"

# The control that stops this becoming a permanent banner: back on the default
# branch it says nothing of the kind.
( cd "$UP" && git checkout -q - 2>/dev/null )
out="$(refresh --dry-run "$UP")"
case "$out" in
  *"not a release"*) _bad "while a source on its default branch is silent" \
                          "warned anyway: $out" ;;
  *) _ok "while a source on its default branch is silent" ;;
esac
# ---------------------------------------------------------------------------
describe "the procedure belongs to the release being installed"

# A refresh is normally driven by the project's OWN copy of this script, and
# that copy is one release behind BY CONSTRUCTION: a change to *what* gets
# copied only takes effect on the refresh AFTER the one that delivers it.
#
# Not hypothetical. `models.conf` joined the single-file list in release 23, so
# a project on 22 running its own script received `scripts/plan.sh` without the
# policy file plan.sh reads - a script delivered without the thing it depends
# on, and nothing said a word. Every future addition to that list has the same
# one-release delay, and "remember to run upstream's copy" is not a mechanism.
new_project
# A project copy that differs from upstream's, which is what being a release
# behind looks like from here.
{ printf '#!/usr/bin/env bash\n# An older release of this script.\n'
  tail -n +2 "$REPO_ROOT/scripts/refresh-harness.sh"; } > "$PROJ/scripts/refresh-harness.sh"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "the harness it already has" >/dev/null 2>&1 )
out="$( cd "$PROJ" && bash scripts/refresh-harness.sh "$UP" 2>&1 )"; rc=$?
assert_eq "an older project copy hands over to upstream's" 0 "$rc"
assert_contains "and says that it did" "upstream ships a different" "$out"
# It has to actually finish the work, not merely announce the handover - and
# exactly once, because a handover that re-entered the script would double it.
assert_eq "and does the refresh once" 1 \
  "$(printf '%s\n' "$out" | grep -c 'REPLACED  .claude/settings.json')"
assert_eq "having replaced the scripts" "echo new" "$(cat "$PROJ/scripts/brand-new.sh" 2>/dev/null)"

# THE CONTROL, and the thing that stops this becoming an infinite hand-over:
# when the two copies agree there is nothing to hand over to, and upstream's own
# script - which is what runs after a hand-over - must take this branch.
new_project
cp "$REPO_ROOT/scripts/refresh-harness.sh" "$PROJ/scripts/refresh-harness.sh"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm same >/dev/null 2>&1 )
out="$( cd "$PROJ" && bash scripts/refresh-harness.sh "$UP" 2>&1 )"; rc=$?
assert_eq "an identical copy just runs" 0 "$rc"
case "$out" in
  *"upstream ships a different"*) _bad "and hands over to nobody" "it handed over anyway: $out" ;;
  *) _ok "and hands over to nobody" ;;
esac

# HARNESS-040 AC-6, on the same run: the summary says what happens under docs/
# (C-4, lines one, three and four whole), and the list itself travels as a
# single upstream-owned file, so a consumer's shipped-docs suite reads the list
# its refresh used. Line one is unchanged by the story; it is asserted so that
# the rewrite cannot drop `docs/**` from the project-owned list.
assert_eq "AC-6: the summary still names docs/** as project-owned" 1 \
  "$(whole_line_count "  LEFT untouched (project-owned): .claude/harness/project.conf, docs/**," "$out")"
assert_eq "AC-6: the summary says the files docs-shipped.conf lists are ADDED" 1 \
  "$(whole_line_count "    Under docs/, the files .claude/harness/docs-shipped.conf lists are ADDED" "$out")"
assert_eq "AC-6: when missing, KEPT when present, and never overwritten" 1 \
  "$(whole_line_count "    when you have no copy and KEPT when you do - never overwritten." "$out")"
assert_eq "AC-6: docs-shipped.conf is REPLACED as an upstream-owned file, once" 1 \
  "$(whole_line_count "  REPLACED  .claude/harness/docs-shipped.conf" "$out")"

# The hand-over happens BEFORE the dirty-tree and mid-cycle refusals, so the
# process that refuses is the one handed TO rather than the one invoked. Same
# answer, different process - and worth its own case, because "it refuses" and
# "it still refuses after handing over" are different claims and every existing
# refusal test runs on a project whose script matches upstream's, so none of
# them reaches this path.
new_project
{ printf '#!/usr/bin/env bash\n# An older release of this script.\n'
  tail -n +2 "$REPO_ROOT/scripts/refresh-harness.sh"; } > "$PROJ/scripts/refresh-harness.sh"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "an older harness" >/dev/null 2>&1 )
printf 'STORY_ID=W-1\nPHASE=GATES\n' > "$PROJ/.claude/state/current-story.env"
out="$( cd "$PROJ" && bash scripts/refresh-harness.sh "$UP" 2>&1 )"; rc=$?
assert_eq "a mid-cycle tree is refused THROUGH the hand-over" 2 "$rc"
assert_contains "and the refusal still names the phase" "GATES" "$out"
rm -f "$PROJ/.claude/state/current-story.env"

# ---------------------------------------------------------------------------
describe "it survives replacing the file it is being read from"

# Every case above runs $REPO_ROOT's copy of the script against a project that
# happens to hold another copy - two different files - so the suite never once
# exercised the arrangement EVERY real refresh uses. The header says to run it
# as `bash scripts/refresh-harness.sh` from inside the project, and
# `scripts/*.sh` is one of the things it replaces. The file being read is the
# file being written.
#
# Bash reads a script by byte offset as it executes. Overwrite it underneath and
# execution resumes at the old offset in the NEW bytes - mid-line, mid-block,
# with whatever that parses as. The first real refresh to hit this printed
#   refresh-harness.sh: line 151: ------------: command not found
# and ran its single-file block twice. The tree came out correct ONLY because
# the re-entered block was idempotent `cp` calls; a few hundred bytes either way
# is the `rm -rf` loop re-entered with different state, in the one script whose
# whole job is not silently destroying a project's files.
#
# The project's copy is padded so its byte offsets differ from upstream's, which
# is the real situation - an older release is always a different length - and
# without which overwriting a file with its own bytes changes nothing and the
# bug does not reproduce.
new_project
{ printf '#!/usr/bin/env bash\n'
  printf '# An older release of this script. The padding is the point: it puts\n'
  printf '# every byte offset in this file somewhere else than the new one has\n'
  printf '# them, which is what an older release does for free.\n'
  printf '#\n%s' "$(for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
      printf '# offset padding line %s, carrying no meaning whatsoever\n' "$i"; done)"
  tail -n +2 "$REPO_ROOT/scripts/refresh-harness.sh"
} > "$PROJ/scripts/refresh-harness.sh"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "the harness it already has" >/dev/null 2>&1 )

out="$( cd "$PROJ" && bash scripts/refresh-harness.sh "$UP" 2>&1 )"; rc=$?
assert_eq "run the documented way, it still exits 0" 0 "$rc"
case "$out" in
  *"command not found"*|*"syntax error"*|*"unexpected"*)
    _bad "and bash never resumes inside the new bytes" "it did: $out" ;;
  *) _ok "and bash never resumes inside the new bytes" ;;
esac
# Once each. Re-entering the file mid-block printed the single-file section a
# second time, which is the only reason anybody noticed.
assert_eq "and reports each replacement once" 1 \
  "$(printf '%s\n' "$out" | grep -c 'REPLACED  .claude/settings.json')"
# And it still did the work: the point of the fix is that the copy loop runs to
# completion, not that the script exits quietly before reaching it.
assert_eq "having actually replaced the scripts" "echo new" \
  "$(cat "$PROJ/scripts/brand-new.sh" 2>/dev/null)"
assert_eq "and itself, with the new release" \
  "$(cat "$REPO_ROOT/scripts/refresh-harness.sh")" \
  "$(cat "$PROJ/scripts/refresh-harness.sh" 2>/dev/null)"

# ---------------------------------------------------------------------------
describe "HARNESS-020 AC-5  a project's project-floors.conf is KEPT, and floors.conf is replaced"

# HARNESS-020. A consuming project's own suites declare their floors in
# .claude/tests/project-floors.conf, which upstream never ships - so the
# refresh has to keep it the way it keeps project-*.test.sh, and report it as
# KEPT rather than LOCAL. The control is upstream's floors.conf in the same
# directory, in the same run: it is upstream's, and it is replaced.
#
# Upstream gains a floors.conf here, committed so that it is SHIPPED. This
# block is the last to touch $UP.
printf 'floor | lib | 1\n' > "$UP/.claude/tests/floors.conf"
( cd "$UP" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "upstream ships floors.conf" >/dev/null 2>&1 )

new_project
# Content a sloppy copy would not reproduce: a comment, trailing space, a blank
# line, and no final newline. Compared with cmp, never via $(cat), which would
# strip exactly the trailing bytes that make byte-identical mean anything.
printf '# FWB own floors\nfloor | project-ci | 28   \n\nfloor | project-handoff | 12' \
  > "$PROJ/.claude/tests/project-floors.conf"
printf '# a project suite, also KEPT\n' > "$PROJ/.claude/tests/project-ci.test.sh"
printf 'OLD floors\n' > "$PROJ/.claude/tests/floors.conf"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "a project with its own floors" >/dev/null 2>&1 )
cp "$PROJ/.claude/tests/project-floors.conf" "$WORK/project-floors.expected"

KEPT_PF="  KEPT      .claude/tests/project-floors.conf  (upstream does not ship it - yours)"
LOCAL_PF="    LOCAL     .claude/tests/project-floors.conf"
# exact_count <line> <haystack>   Whole-line matches; grep -c prints 0 itself.
exact_count() { grep -cxF -- "$1" <<EXACT_HAY
$2
EXACT_HAY
}

out="$(refresh --dry-run "$UP")"; rc=$?
assert_eq "dry run: it succeeds" 0 "$rc"
assert_eq "dry run: project-floors.conf is reported KEPT, once" 1 "$(exact_count "$KEPT_PF" "$out")"
assert_eq "dry run: and is NOT reported LOCAL" 0 "$(exact_count "$LOCAL_PF" "$out")"
if cmp -s "$WORK/project-floors.expected" "$PROJ/.claude/tests/project-floors.conf"; then
  _ok "dry run: project-floors.conf is untouched"
else
  _bad "dry run: project-floors.conf is untouched" "it changed"
fi

out="$(refresh "$UP")"; rc=$?
assert_eq "real run: it succeeds" 0 "$rc"
assert_eq "real run: project-floors.conf is reported KEPT, once" 1 "$(exact_count "$KEPT_PF" "$out")"
assert_eq "real run: and is NOT reported LOCAL" 0 "$(exact_count "$LOCAL_PF" "$out")"
if cmp -s "$WORK/project-floors.expected" "$PROJ/.claude/tests/project-floors.conf"; then
  _ok "real run: project-floors.conf survives byte-identical"
else
  _bad "real run: project-floors.conf survives byte-identical" \
    "$( [ -f "$PROJ/.claude/tests/project-floors.conf" ] && echo 'its bytes changed' || echo 'it was deleted' )"
fi
# The control, in the same run: the upstream-owned file beside it IS replaced.
# Without it, a refresh that skipped .claude/tests altogether passes every
# assertion above.
if cmp -s "$UP/.claude/tests/floors.conf" "$PROJ/.claude/tests/floors.conf"; then
  _ok "control: upstream's floors.conf, in the same refresh, is replaced"
else
  _bad "control: upstream's floors.conf, in the same refresh, is replaced" \
    "it still holds: $(cat "$PROJ/.claude/tests/floors.conf" 2>/dev/null)"
fi
assert_eq "control: and floors.conf is not reported KEPT" 0 \
  "$(exact_count "  KEPT      .claude/tests/floors.conf  (upstream does not ship it - yours)" "$out")"

# ===========================================================================
# HARNESS-049: the refresh names each NEW file a project's own linters,
# formatters and test runners will read.
#
# From the field (fantasy-world-builder, release 64 -> 88): the refresh brought
# in .claude/skills/security-audit/ - .cjs validators, .test.cjs suites, a
# .json schema - under one line, `REPLACED  .claude/skills/`, which reads as
# "the same as before". The project's biome config included "**", and its
# required lint, unit and coverage gates went red on main. Nothing in the report
# pointed at the files.
#
# Every needle is a WHOLE LINE pinned byte for byte by the story's Contract
# (exact_count / whole_line_count, here-docs, never a pipe into grep -c). The
# negative controls ask "is this path named NEW in ANY wording", so they count
# lines that START with `  NEW ` and contain the path (new_lines_naming), the
# shape added_lines_naming uses for ADDED. No assertion depends on the order of
# two NEW lines: Git Bash `find` and Linux `find` walk in different orders.
#
# This block is the last to touch $UP.
# ===========================================================================

NEW_DIR=".claude/skills/lint-me"
N_CJS="  NEW       $NEW_DIR/validate.cjs  (a .cjs file your linters and formatters will read)"
N_TCJS="  NEW       $NEW_DIR/validate.test.cjs  (a .cjs file your linters and formatters will read)"
N_JSON="  NEW       $NEW_DIR/schema.json  (a .json file your linters and formatters will read)"
NOTE1="            Your project's own linters, formatters and test runners will read"
NOTE2="            these files unless their configuration excludes .claude."
UNCHANGED=".claude/skills/stack-profiles/check.cjs"

# new_lines_naming <path> <haystack>   How many NEW lines contain <path>,
# whatever their padding or parenthesis: "never named NEW" is about the word.
new_lines_naming() {
  awk -v p="$1" 'index($0, "  NEW ") == 1 && index($0, p) { n++ } END { print n + 0 }' <<NEWN_HAY
$2
NEWN_HAY
}

# new_lines_of <haystack>   Every NEW line, sorted bytewise, so two runs (or a
# run and the expected set) compare without depending on `find` order.
new_lines_of() {
  awk 'index($0, "  NEW ") == 1' <<NEWL_HAY | LC_ALL=C sort
$1
NEWL_HAY
}

# A NEW skill directory upstream ships: two lintable kinds (AC-1), plus a .md
# and a .sh beside them (AC-2's non-code controls). One .cjs in a directory the
# consumer already has, which new_project gives it at upstream's bytes below
# (AC-2's unchanged control - it is not LOCAL either, since its blob is on
# upstream's release line). And one .mjs under scripts/, which the refresh never
# delivers - it copies scripts/*.sh only - so naming it NEW would be a claim
# about a file that is not going to arrive.
mkdir -p "$UP/$NEW_DIR"
printf 'module.exports = 1;\n'      > "$UP/$NEW_DIR/validate.cjs"
printf 'require("./validate.cjs");\n' > "$UP/$NEW_DIR/validate.test.cjs"
printf '{ "type": "object" }\n'      > "$UP/$NEW_DIR/schema.json"
printf '# lint-me\n'                 > "$UP/$NEW_DIR/SKILL.md"
printf 'echo lint-me\n'              > "$UP/$NEW_DIR/run.sh"
printf 'module.exports = 2;\n'       > "$UP/$UNCHANGED"
printf 'export default 3;\n'         > "$UP/scripts/helper.mjs"
( cd "$UP" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "upstream ships a skill with code in it" >/dev/null 2>&1 )

# ---------------------------------------------------------------------------
describe "HARNESS-049 AC-1  a new file a project's tools will read is named NEW, dry run and real run"

new_project
cp "$UP/$UNCHANGED" "$PROJ/$UNCHANGED"
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "already has upstream's check.cjs" >/dev/null 2>&1 )
assert_eq "fixture: the consumer lacks $NEW_DIR and holds $UNCHANGED" "no yes" \
  "$([ -e "$PROJ/$NEW_DIR" ] && echo yes || echo no) $([ -f "$PROJ/$UNCHANGED" ] && echo yes || echo no)"
assert_eq "fixture: and the consumer's tree is committed, so the real run will not refuse" "" \
  "$(git -C "$PROJ" status --porcelain 2>/dev/null)"

EXPECTED_NEW="$(printf '%s\n' "$N_CJS" "$N_TCJS" "$N_JSON" | LC_ALL=C sort)"

dry="$(refresh --dry-run "$UP")"; rc=$?
assert_eq "AC-1 dry run: it exits 0" 0 "$rc"
assert_eq "AC-1 dry run: the new .cjs is named NEW, once" 1 "$(exact_count "$N_CJS" "$dry")"
assert_eq "AC-1 dry run: the new .test.cjs is named NEW as a .cjs file, once" 1 "$(exact_count "$N_TCJS" "$dry")"
assert_eq "AC-1 dry run: the new .json is named NEW, once" 1 "$(exact_count "$N_JSON" "$dry")"
assert_eq "AC-1 dry run: the note's first line is printed once" 1 "$(exact_count "$NOTE1" "$dry")"
assert_eq "AC-1 dry run: the note's second line, which says to exclude .claude, is printed once" 1 \
  "$(exact_count "$NOTE2" "$dry")"
assert_eq "AC-1 dry run: the NEW lines are exactly the three new lintable files, nothing else" \
  "$EXPECTED_NEW" "$(new_lines_of "$dry")"
assert_eq "AC-1 dry run: and it still says it wrote nothing" 1 \
  "$(exact_count "Dry run: nothing was written." "$dry")"
if [ -e "$PROJ/$NEW_DIR" ]; then
  _bad "AC-1 dry run: $NEW_DIR still does not exist" "a dry run created it"
else
  _ok "AC-1 dry run: $NEW_DIR still does not exist"
fi
# LOCAL judges the consumer's files, and these are absent from the consumer.
assert_eq "AC-1 dry run: no LOCAL line names the new skill directory" 0 \
  "$(awk -v p="$NEW_DIR/" 'index($0, "    LOCAL ") == 1 && index($0, p) { n++ } END { print n + 0 }' <<LOCAL_HAY
$dry
LOCAL_HAY
)"

real="$(refresh "$UP")"; rc=$?
assert_eq "AC-1 real run: it still exits 0 - naming the files is not a refusal" 0 "$rc"
assert_eq "AC-1 real run: the new .cjs is named NEW, once" 1 "$(exact_count "$N_CJS" "$real")"
assert_eq "AC-1 real run: the new .test.cjs is named NEW, once" 1 "$(exact_count "$N_TCJS" "$real")"
assert_eq "AC-1 real run: the new .json is named NEW, once" 1 "$(exact_count "$N_JSON" "$real")"
assert_eq "AC-1 real run: the note's first line is printed once" 1 "$(exact_count "$NOTE1" "$real")"
assert_eq "AC-1 real run: the note's second line is printed once" 1 "$(exact_count "$NOTE2" "$real")"
assert_eq "AC-1 real run: the NEW lines are the same set the dry run printed" \
  "$EXPECTED_NEW" "$(new_lines_of "$real")"
# Judged before the copy: a comparison made after it finds every file present
# and names nothing, which is the defect a real-run-only check would miss.
missing=""
for f in validate.cjs validate.test.cjs schema.json SKILL.md run.sh; do
  cmp -s "$UP/$NEW_DIR/$f" "$PROJ/$NEW_DIR/$f" || missing="$missing $f"
done
assert_eq "AC-1 real run: and every file of the new skill is delivered, byte-identical" "" "$missing"

# ---------------------------------------------------------------------------
describe "HARNESS-049 AC-2  an unchanged file, a non-code file and an undelivered file are not named"

# Read off the same two runs as AC-1, so a NEW line that fires for everything
# fails here beside the assertions that make it fire at all.
for spec in "$UNCHANGED|a file the consumer already has at the same path" \
            "$NEW_DIR/SKILL.md|a new .md file" \
            "$NEW_DIR/run.sh|a new .sh file" \
            "scripts/helper.mjs|a .mjs under scripts/, which the refresh does not deliver"; do
  p="${spec%%|*}"; why="${spec#*|}"
  assert_eq "AC-2 dry run: no NEW line names $why ($p)" 0 "$(new_lines_naming "$p" "$dry")"
  assert_eq "AC-2 real run: no NEW line names $why ($p)" 0 "$(new_lines_naming "$p" "$real")"
done
if [ -e "$PROJ/scripts/helper.mjs" ]; then
  _bad "AC-2 fixture: scripts/helper.mjs is indeed not delivered" "it was copied - the control's premise is wrong"
else
  _ok "AC-2 fixture: scripts/helper.mjs is indeed not delivered"
fi

# THE CONTROL: a refresh in which nothing is new. Every upstream file under the
# five replaced directories is put in the consumer first, at upstream's bytes,
# and the fixture proves both halves of that before the report is read: nothing
# is missing, and there ARE lintable files on both sides - so a NEW line that
# ignores whether the consumer has the file fires here, and silence means
# something.
new_project
for d in agents commands skills hooks tests; do
  cp -r "$UP/.claude/$d/." "$PROJ/.claude/$d/"
done
( cd "$PROJ" && git add -A >/dev/null 2>&1 \
    && git -c user.email=t@t -c user.name=t commit -qm "every upstream file already here" >/dev/null 2>&1 )
absent=0; lintable=0
for d in agents commands skills hooks tests; do
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    [ -e "$PROJ/.claude/$d/$rel" ] || absent=$((absent+1))
    case "$rel" in *.cjs|*.json) lintable=$((lintable+1)) ;; esac
  done <<CTL_LIST
$(cd "$UP/.claude/$d" && find . -type f 2>/dev/null | sed 's|^\./||')
CTL_LIST
done
assert_eq "control fixture: no upstream file under the replaced directories is absent from the consumer" 0 "$absent"
assert_eq "control fixture: and four lintable files exist on both sides" 4 "$lintable"
out="$(refresh --dry-run "$UP")"; rc=$?
assert_eq "AC-2 control: a refresh between identical trees exits 0" 0 "$rc"
assert_eq "AC-2 control: and prints no NEW line at all" "" "$(new_lines_of "$out")"
assert_eq "AC-2 control: and not the note's first line" 0 "$(exact_count "$NOTE1" "$out")"
assert_eq "AC-2 control: nor its second" 0 "$(exact_count "$NOTE2" "$out")"

# ---------------------------------------------------------------------------
describe "HARNESS-049 AC-3  the extensions a project's tools read are written once"

# A static read of the script, and the right instrument for the claim: "defined
# in one place" is a property of the TEXT, which no run of the script can see.
# The spelling is the Contract's: one column-0 assignment of LINTABLE_EXT to a
# space-separated list of bare extensions.
RS="$REPO_ROOT/scripts/refresh-harness.sh"
assert_eq "AC-3: exactly one column-0 assignment LINTABLE_EXT=\"...\"" 1 \
  "$(grep -cE '^LINTABLE_EXT="[^"]*"[[:space:]]*(#.*)?$' "$RS")"
assert_eq "AC-3: and no second assignment to it anywhere (local, readonly, +=)" 1 \
  "$(grep -cE '(^|[^A-Za-z0-9_$])LINTABLE_EXT\+?=' "$RS")"
ext_line="$(sed -nE 's/^LINTABLE_EXT="([^"]*)".*$/\1/p' "$RS")"
for e in js cjs mjs ts tsx json jsonc py; do
  case " $ext_line " in
    *" $e "*) _ok "AC-3: the set names $e" ;;
    *) _bad "AC-3: the set names $e" "LINTABLE_EXT is \"$ext_line\"" ;;
  esac
done
used="$(grep -cE '\$\{?LINTABLE_EXT' "$RS")"
assert_eq "AC-3: the script reads the variable rather than only declaring it" yes \
  "$([ "$used" -ge 1 ] && echo yes || echo no)"
# Written ONCE: an extension the set names appears on no other code line. A
# second hard-coded `case` pattern is the drift this criterion exists to stop.
for e in cjs mjs tsx jsonc; do
  assert_eq "AC-3: .$e appears on no code line but the assignment" 1 \
    "$(awk -v e="$e" '/^[[:space:]]*#/ { next }
         { s = $0; while ((i = index(s, e)) > 0) {
             pre = (i == 1) ? "" : substr(s, i - 1, 1); post = substr(s, i + length(e), 1)
             if (pre !~ /[A-Za-z0-9_]/ && post !~ /[A-Za-z0-9_]/) { n++; break }
             s = substr(s, i + length(e)) } }
         END { print n + 0 }' "$RS")"
done

summary "refresh"
