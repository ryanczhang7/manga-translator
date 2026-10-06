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

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
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

# ---------------------------------------------------------------------------
describe "the prompts a story cannot be written well without"

# A section heading being present is not the same as the template ASKING for the
# thing that goes in it, and the asks below are the ones a story goes quietly
# wrong without. They are prose, so nothing executes them - but the template
# ships to every project made from this harness, and a paragraph deleted here is
# a prompt every future story loses with no alarm anywhere. That is the shape
# `tdd-cycle` calls "code no machine you have can execute: grep for the shape".
#
# THE NEGATIVE CONTROL is the one this exists for. H6 in the field report, and
# the most generalisable thing the consuming project learned: an acceptance
# criterion specified a measurement STRUCTURALLY INCAPABLE of detecting the
# defect it existed to catch. Variance is a one-point statistic and "smearing" is
# a two-point property, so the metric separated a correct field from the exact
# defect it named by 9% against a 25% threshold - no discriminating power at all.
# It was testable, reviewed and approved. A criterion that is precise, measurable
# and blind is more dangerous than a vague one, because it survives review and
# produces a green tick.
assert_contains "an AC naming a statistic is asked for a negative control" \
  "NEGATIVE" "$(cat "$STORY")"
assert_contains "and told what one is" "deliberately broken input" "$(cat "$STORY")"

# H7: a story whose artifact is covered only by an OPTIONAL gate passes every
# required gate while proving nothing. The template asks for the gate that would
# fail, before RED, so that promoting one is a decision rather than a discovery.
assert_contains "and the story names the gate that would fail if it broke" \
  "REQUIRED gate that would fail" "$(cat "$STORY")"

# ---------------------------------------------------------------------------
describe "the deferred-verifications comment carries the mutation budget, not a count (HARNESS-015, AC-5)"

# The template used to close its `## Deferred verifications` comment with "Do
# THREE mutations rather than one", which made every new story carry a per-story
# count that rules.md never set. The budget now lives in one place - the
# `# Mutation work per story` section of rules.md - and the template names it,
# says what the default entry is, and sends exhaustive earning to
# /audit-mutations. Scoped to the section's own text, so a mention elsewhere in
# the story cannot satisfy it.
dv="$(awk '/^## Deferred verifications/ { on = 1; next } on && /^## / { exit } on { print }' "$STORY")"
assert_contains "names the rules.md section" "Mutation work per story" "$dv"
assert_contains "says the default is one \"defect put back\" entry for the central claim" "defect put back" "$dv"
assert_contains "and sends exhaustive earning to /audit-mutations" "/audit-mutations" "$dv"
# The old rule's tell, as a whole word and case-sensitive: `THREE` was how the
# template shouted it, and the story must be born without it.
assert_eq "the word THREE is absent from the generated story" 0 "$(grep -cw THREE "$STORY")"

# ---------------------------------------------------------------------------
describe "each pasted-result section says what shape a result must take (HARNESS-037, AC-4)"

# check-boundaries.sh accepts a result in ## Regressions, ## Gate probes and
# ## Deferred verifications only as a block - a fence line, or a line indented
# by exactly four spaces - and refuses prose, inline code and tabs. The template
# comment is where an author reads before writing, so each of the three says
# so, in the sentence the story's C-3 gives. Scoped to each section's own text,
# as the deferred-verifications block above is, so a mention in one section
# cannot satisfy another. Runs of whitespace are collapsed first: the sentence
# is wrapped to the comment's width, and a needle split by a line break and its
# comment indent is still the same words. Nothing else is normalised.
for sec in "Regressions" "Gate probes" "Deferred verifications"; do
  body="$(awk -v h="## $sec" 'index($0, h) == 1 { on = 1; next } on && /^## / { exit } on { print }' "$STORY" \
    | tr -s ' \t\n' '   ')"
  assert_contains "## $sec carries the rule sentence: \"three backticks\"" "three backticks" "$body"
  assert_contains "## $sec carries the rule sentence: \"exactly four spaces\"" "exactly four spaces" "$body"
  assert_contains "## $sec carries the rule sentence: \"inline code\"" "inline code" "$body"
done

# ---------------------------------------------------------------------------
describe "a new story declares the files it touches (HARNESS-006, AC-5)"

# `plan.sh conflicts` reads `touches:` from frontmatter to say which stories
# can run together, and it can only read what the template asked for. The key
# is born EMPTY - `[]`, which cmd_conflicts treats exactly like an absent key -
# with a comment saying what it is for, because the template is the only
# documentation most story authors read. The whole line is pinned, anchored:
# a comment that drifted into saying something else would still satisfy a
# floating "touches:" needle.
assert_eq "the frontmatter carries touches: [] with a comment naming plan.sh conflicts" 1 \
  "$(grep -cx 'touches: \[\] *# files this story expects to write; `plan.sh conflicts` reads it' "$STORY")"

# Between depends_on and required_gates, inside the frontmatter: the three
# machine-read lists together, before the closing `---`. A `touches:` line that
# landed in the body would be prose, and frontmatter_list would never see it.
order="$(awk '
  NR == 1 && /^---/ { next }
  /^---/ { exit }
  /^depends_on:/     { printf "depends_on " }
  /^touches:/        { printf "touches " }
  /^required_gates:/ { printf "required_gates " }
' "$STORY")"
assert_eq "and it sits between depends_on and required_gates" \
  "depends_on touches required_gates " "$order"

# ---------------------------------------------------------------------------
describe "the Contract asks for a **Writes:** line, and a new story declares none (HARNESS-016)"

# `plan.sh conflicts` prints DRIFT when a Contract's column-0 `**Writes:**` line
# names a file `touches:` does not, and is silent without one. The template is
# where an author learns the line exists, so its `## Contract` comment asks for
# it - and asks INSIDE the comment, because a `**Writes:**` line emitted into
# every fresh story would be a declaration nobody made.
#
# Both halves are read from the `## Contract` section alone, split by the same
# comment stripping plan.sh applies: what is inside `<!-- -->` and what is not.
contract="$(awk '/^## Contract/ { on = 1; next } on && /^## / { exit } on { print }' "$STORY")"
# uncommented   The section with every <!-- ... --> removed, across lines.
uncommented="$(awk '{ s = s $0 "\n" }
  END {
    while ((i = index(s, "<!--")) > 0) {
      r = substr(s, i); j = index(r, "-->")
      if (j == 0) { s = substr(s, 1, i - 1); break }
      s = substr(s, 1, i - 1) substr(r, j + 3)
    }
    printf "%s", s
  }' <<<"$contract")"
in_comment=$(( $(grep -cF '**Writes:**' <<<"$contract") - $(grep -cF '**Writes:**' <<<"$uncommented") ))
assert_eq "the Contract comment names the **Writes:** line" "yes" \
  "$([ "$in_comment" -ge 1 ] && printf yes || printf no)"
assert_contains "and says plan.sh conflicts compares it with touches:" \
  "plan.sh conflicts" "$contract"
# ONE ASSERTION FOR BOTH, so that neither half can pass alone: the template
# mentions `**Writes:**` inside the comment (fails today: no mention at all),
# AND no uncommented line of the section starts with it (fails if the example
# escapes the comment). A comment mention cannot satisfy the second half,
# because comments are stripped before it is counted.
assert_eq "a fresh story's Contract mentions **Writes:** only inside the comment, and declares no write" \
  "commented 0" \
  "$([ "$in_comment" -ge 1 ] && printf commented || printf absent) $(grep -c '^\*\*Writes:\*\*' <<<"$uncommented")"

summary "new-story"
