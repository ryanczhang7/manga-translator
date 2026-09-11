#!/usr/bin/env bash
# Tests for scripts/new-story.sh - the canonical story template.
#
# The template is the only place most of the harness's rules are read: an agent
# writing a story reads the comments in the file it was given, not the skills.
# So a template that quietly loses text is worse than a broken one, because
# nothing looks wrong.
#
# That is not hypothetical. The body was written into an UNQUOTED heredoc, so
# every backtick span in it was command substitution: the one phrase that names
# the mechanism the model-guidance section exists for - an agent definition's
# `model:` field - was executed as a command, printed "model:: command not
# found" to stderr, and landed in every generated story as "An agent
# definition's  field". The rule survived; the name of the thing it is about did
# not.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness)"
trap 'rm -rf "$WORK"' EXIT

SCRIPT="$REPO_ROOT/scripts/new-story.sh"

# Run the real script against a throwaway root, never this checkout: it writes
# into docs/backlog/stories, which is a real directory here.
mkdir -p "$WORK/scripts" "$WORK/docs/backlog/stories"
cp "$SCRIPT" "$WORK/scripts/new-story.sh"
( cd "$WORK" && bash scripts/new-story.sh WORLD-014 "Hex grid renders at 60fps" EPIC-03 feature \
    >"$WORK/out" 2>"$WORK/err" )
STORY="$WORK/docs/backlog/stories/WORLD-014.md"

# ---------------------------------------------------------------------------
describe "the template lands as written"

# stderr is the tell. A heredoc that expands its body reports every failed
# expansion here and then writes the file anyway, so the exit status is 0 and
# the story looks fine.
assert_eq "writes nothing to stderr" "" "$(cat "$WORK/err")"

# The load-bearing assertion: every backtick span the template CONTAINS also
# appears in what it PRODUCES. Command substitution eats these first, and they
# are where the template names files, fields and commands - the parts a reader
# cannot reconstruct from context.
missing=""
while IFS= read -r span; do
  [ -z "$span" ] && continue
  grep -qF -- "$span" "$STORY" || missing="$missing $span"
done <<< "$(sed -n '/^cat >/,$p' "$SCRIPT" | grep -oE '`[^`]+`' | sort -u)"
assert_eq "every backtick span in the template survives into the story" "" "$missing"

# The span check above is a symptom test, so pin the mechanism as well: the
# body's heredoc delimiter is QUOTED. A story template is prose about a shell
# harness - it will always be full of `$VAR`, `$(cmd)` and backticks - so the
# body can never safely be expanded, and the next person to add a section
# should not have to discover that from a mangled comment.
assert_contains "the body heredoc delimiter is quoted" "cat >> \"\$file\" <<'TEMPLATE'" "$(cat "$SCRIPT")"

# ---------------------------------------------------------------------------
describe "the frontmatter still interpolates"

# The fix for the above is to stop expanding the body - which must not stop
# expanding the frontmatter, where every value is an argument.
assert_contains "id"     "id: WORLD-014"                        "$(cat "$STORY")"
assert_contains "title"  "title: Hex grid renders at 60fps"     "$(cat "$STORY")"
assert_contains "slug"   "slug: hex-grid-renders-at-60fps"      "$(cat "$STORY")"
assert_contains "epic"   "epic: EPIC-03"                        "$(cat "$STORY")"
assert_contains "type"   "type: feature"                        "$(cat "$STORY")"
assert_contains "phase"  "phase: PLANNED"                       "$(cat "$STORY")"
assert_contains "branch" "branch: story/WORLD-014-hex-grid-renders-at-60fps" "$(cat "$STORY")"

# ---------------------------------------------------------------------------
describe "every section the harness reads by name is present"

# check-boundaries.sh, gates.sh and the hooks address these sections by
# heading. A template missing one produces stories the tooling cannot find its
# evidence in.
for h in "## Acceptance criteria" "## Contract" "## Deferred verifications" \
         "## Amendments" "## Model guidance" "## Test plan" \
         "## Handoff: RED -> GREEN" "## Regressions" "## Gate results" \
         "## Gate probes" "## Scaffold inventory" "## Notes"; do
  if grep -qF -- "$h" "$STORY"; then _ok "has $h"; else _bad "has $h" "not in the generated story"; fi
done

summary "new-story"
