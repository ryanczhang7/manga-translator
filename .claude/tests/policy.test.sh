#!/usr/bin/env bash
# Policy guard: the per-story mutation budget is stated ONCE, in rules.md, and
# every other site defers to it (HARNESS-015, AC-4 and AC-6).
#
# The sites are prose - command files, skills, the story template - so nothing
# executes them and nothing goes red when one of them quietly grows a second,
# contradicting budget. That is how "Do three mutations" came to live in five
# files at once while rules.md set no per-story count at all. This suite is the
# shape `tdd-cycle` calls "code no machine you have can execute: grep for the
# shape": a static check IS the correct instrument here, not a substitute for a
# test that could have been written instead.
#
# The needles are whole-line or fixed-string, never a bare word (`rules.md`, "an
# assertion's needle is part of the assertion"), and the count rule uses
# `grep -Eiw`, whose word boundaries are pinned by fixture below so that a later
# reader knows exactly what does and does not trip it.
#
# `policy_problems <root>` is run twice: over REPO_ROOT, where it must print
# nothing, and over a fixture built compliant by construction with one site
# regressed, where it must print exactly one line naming that file. The second
# is what makes the first mean anything - a guard that never fires is satisfied
# by the real tree whatever the real tree says. DV-1 in the story is the same
# probe against a REAL line of the tree, owned by GATES.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# --- the rules ---------------------------------------------------------------
# The six sites that must defer to rules.md, and must not carry a count.
SITES=".claude/commands/advance-story.md
.claude/commands/complete-story.md
.claude/skills/story-authoring/SKILL.md
.claude/skills/story-authoring/reference/sections.md
.claude/skills/tdd-cycle/SKILL.md
scripts/new-story.sh"
RULES=".claude/harness/rules.md"
AUDIT=".claude/commands/audit-mutations.md"
ADVANCE=".claude/commands/advance-story.md"
COMPLETE=".claude/commands/complete-story.md"

SECTION_NAME='Mutation work per story'
HEADING='# Mutation work per story'
COUNT_RE='(three|two) mutations'

# review_done_section <file>   The lines of /advance-story's REVIEW -> DONE
# paragraph: from the line that begins `**REVIEW → DONE.**` up to, not
# including, the next line that begins `**` (the next phase paragraph). Empty
# when the file has no such paragraph.
review_done_section() {
  awk '
    index($0, "**REVIEW → DONE.**") == 1 { on = 1; print; next }
    on && /^\*\*/ { exit }
    on { print }
  ' "$1"
}

# policy_problems <root>   One line `<relative-path>: <reason>` per violation;
# silent when the tree under <root> is compliant. Always returns 0: the output
# is the verdict, so a caller compares it against the empty string.
policy_problems() {
  local root="$1" f sec
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if [ ! -f "$root/$f" ]; then printf '%s: file is missing\n' "$f"; continue; fi
    grep -qF -- "$SECTION_NAME" "$root/$f" \
      || printf '%s: does not name the `%s` section of rules.md\n' "$f" "$SECTION_NAME"
    if grep -qEiw -- "$COUNT_RE" "$root/$f"; then
      printf '%s: still prescribes a per-story mutation count (matches `%s`)\n' "$f" "$COUNT_RE"
    fi
  done <<SITE_LIST
$SITES
SITE_LIST

  if [ ! -f "$root/$RULES" ]; then
    printf '%s: file is missing\n' "$RULES"
  else
    grep -qxF -- "$HEADING" "$root/$RULES" \
      || printf '%s: has no line exactly `%s`\n' "$RULES" "$HEADING"
    if grep -qEiw -- "$COUNT_RE" "$root/$RULES"; then
      printf '%s: still prescribes a per-story mutation count (matches `%s`)\n' "$RULES" "$COUNT_RE"
    fi
  fi

  if [ ! -f "$root/$AUDIT" ]; then
    printf '%s: file is missing\n' "$AUDIT"
  else
    grep -qF -- 'on request' "$root/$AUDIT" \
      || printf '%s: does not say it runs `on request`\n' "$AUDIT"
    grep -qF -- 'bash scripts/gates.sh --gate mutation' "$root/$AUDIT" \
      || printf '%s: does not run `bash scripts/gates.sh --gate mutation`\n' "$AUDIT"
  fi

  for f in "$ADVANCE" "$COMPLETE"; do
    [ -f "$root/$f" ] || continue          # already reported above
    grep -qF -- 'mutation-tester' "$root/$f" \
      && printf '%s: dispatches `mutation-tester`; only /audit-mutations may\n' "$f"
    grep -qF -- '--gate mutation' "$root/$f" \
      && printf '%s: runs `--gate mutation`; only /audit-mutations may\n' "$f"
  done

  if [ -f "$root/$ADVANCE" ]; then
    sec="$(review_done_section "$root/$ADVANCE")"
    if [ -z "$sec" ]; then
      printf '%s: has no `**REVIEW → DONE.**` paragraph\n' "$ADVANCE"
    else
      case "$sec" in
        *'/audit-mutations'*) ;;
        *) printf '%s: its REVIEW → DONE paragraph does not recommend `/audit-mutations`\n' "$ADVANCE" ;;
      esac
    fi
  fi
  return 0
}

# --- a compliant fixture, by construction ------------------------------------
# Minimal files that satisfy every rule above. Their wording is nobody's
# contract: GREEN writes the real sites. What matters is that policy_problems
# is silent on them, so that a single regression below is the ONLY thing it can
# be reporting.
compliant_fixture() { # <dir>
  local d="$1" f
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    mkdir -p "$d/$(dirname "$f")"
    printf 'The per-story budget is `%s` in rules.md; follow it.\n' "$SECTION_NAME" > "$d/$f"
  done <<SITE_LIST
$SITES
SITE_LIST
  mkdir -p "$d/.claude/harness" "$d/.claude/commands"
  printf '# Non-negotiables\n\n- a rule\n\n%s\n\nOne earning mutation per test written against existing code.\n' "$HEADING" > "$d/$RULES"
  printf 'Runs on request. Where a `mutation` gate is configured it runs\n`bash scripts/gates.sh --gate mutation`; otherwise it reasons by hand.\n' > "$d/$AUDIT"
  {
    printf '**GATES → REVIEW.** Only when every required gate passes.\n\n'
    printf '**REVIEW → DONE.** Only once the PR is merged. When the closed story was the\n'
    printf 'last open story of its epic, recommend `/audit-mutations <epic>`; never run it.\n\n'
    printf '**Returning to RED from GREEN or GATES.** The budget is `%s`.\n' "$SECTION_NAME"
  } > "$d/$ADVANCE"
}

# fresh_case <name>   A new compliant fixture; echoes its path.
fresh_case() { local d="$WORK/$1"; rm -rf "$d"; compliant_fixture "$d"; printf '%s' "$d"; }

# ---------------------------------------------------------------------------
describe "the real tree (AC-4, AC-6)"

# Premise first: the guard judges files that exist. A rule pointed at a path
# that has moved reports "file is missing" - which is a violation, and the right
# one, but it is worth seeing on its own line.
missing=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ -f "$REPO_ROOT/$f" ] || missing="$missing $f"
done <<SITE_LIST
$SITES
$RULES
$AUDIT
SITE_LIST
assert_eq "every file the policy names exists in this repository" "" "$missing"

assert_eq "policy_problems over the real tree prints nothing: one budget, in rules.md, and every site defers to it" \
  "" "$(policy_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "the fixture: compliant by construction, then one site regressed (AC-4 control)"

d="$(fresh_case compliant)"
assert_eq "the compliant fixture is silent" "" "$(policy_problems "$d")"

d="$(fresh_case regressed-one)"
printf 'Do three mutations rather than one where the entry is about a codec.\n' >> "$d/$ADVANCE"
assert_eq "restoring the old sentence in ONE site prints exactly one line, naming that file" \
  "$ADVANCE: still prescribes a per-story mutation count (matches \`$COUNT_RE\`)" \
  "$(policy_problems "$d")"

# ---------------------------------------------------------------------------
describe "each rule fires on its own file, and on nothing else"

d="$(fresh_case rules-heading)"
printf '# Non-negotiables\n\n- a rule\n\n## Mutation work per story\n' > "$d/$RULES"   # wrong level
assert_eq "rules.md without the exact top-level heading" \
  "$RULES: has no line exactly \`$HEADING\`" "$(policy_problems "$d")"

d="$(fresh_case rules-count)"
printf 'Two mutations, one run each, is enough.\n' >> "$d/$RULES"
assert_eq "rules.md carrying a count of its own" \
  "$RULES: still prescribes a per-story mutation count (matches \`$COUNT_RE\`)" "$(policy_problems "$d")"

d="$(fresh_case site-no-reference)"
printf 'Earn every assertion you can.\n' > "$d/.claude/skills/story-authoring/reference/sections.md"
assert_eq "a site that no longer names the rules.md section" \
  ".claude/skills/story-authoring/reference/sections.md: does not name the \`$SECTION_NAME\` section of rules.md" \
  "$(policy_problems "$d")"

d="$(fresh_case audit-not-on-request)"
printf 'Runs every story. It runs `bash scripts/gates.sh --gate mutation`.\n' > "$d/$AUDIT"
assert_eq "/audit-mutations that does not say on request" \
  "$AUDIT: does not say it runs \`on request\`" "$(policy_problems "$d")"

d="$(fresh_case audit-no-gate)"
printf 'Runs on request. Reason through the mutants by hand.\n' > "$d/$AUDIT"
assert_eq "/audit-mutations that does not run the mutation gate" \
  "$AUDIT: does not run \`bash scripts/gates.sh --gate mutation\`" "$(policy_problems "$d")"

d="$(fresh_case advance-dispatches)"
printf 'Then dispatch the **mutation-tester** subagent.\n' >> "$d/$ADVANCE"
assert_eq "/advance-story dispatching mutation-tester" \
  "$ADVANCE: dispatches \`mutation-tester\`; only /audit-mutations may" "$(policy_problems "$d")"

d="$(fresh_case complete-runs-gate)"
printf 'Then run `bash scripts/gates.sh --gate mutation` before the PR.\n' >> "$d/$COMPLETE"
assert_eq "/complete-story running the mutation gate" \
  "$COMPLETE: runs \`--gate mutation\`; only /audit-mutations may" "$(policy_problems "$d")"

# Section-scoped, not file-scoped: the recommendation has to be in the
# REVIEW -> DONE paragraph. Here `/audit-mutations` is present in the file, in
# the wrong paragraph, and the guard must still fire.
d="$(fresh_case advance-wrong-paragraph)"
{
  printf '**GATES → REVIEW.** Only when every required gate passes. Consider `/audit-mutations`.\n\n'
  printf '**REVIEW → DONE.** Only once the PR is merged. Set the phase to DONE.\n\n'
  printf '**Returning to RED from GREEN or GATES.** The budget is `%s`.\n' "$SECTION_NAME"
} > "$d/$ADVANCE"
assert_eq "/advance-story recommending /audit-mutations outside REVIEW → DONE" \
  "$ADVANCE: its REVIEW → DONE paragraph does not recommend \`/audit-mutations\`" "$(policy_problems "$d")"

d="$(fresh_case advance-no-paragraph)"
printf '**GATES → REVIEW.** Only when every required gate passes. `%s`.\n' "$SECTION_NAME" > "$d/$ADVANCE"
assert_eq "/advance-story with no REVIEW → DONE paragraph at all" \
  "$ADVANCE: has no \`**REVIEW → DONE.**\` paragraph" "$(policy_problems "$d")"

# ---------------------------------------------------------------------------
describe "the count rule's word boundaries are pinned"

# `grep -Eiw '(three|two) mutations'`: the match must be a whole word on both
# sides. These four say exactly where that line falls, so that a later reader
# does not have to guess whether a rewording trips it.
S=".claude/skills/story-authoring/reference/sections.md"
d="$(fresh_case w-embedded)"
printf 'Across twentythree mutations of one codec nothing survived.\n' >> "$d/$S"
assert_eq "\`twentythree mutations\` is not a count: -w refuses a match inside a word" "" "$(policy_problems "$d")"

d="$(fresh_case w-singular)"
printf 'Three mutation runs were logged.\n' >> "$d/$S"
assert_eq "\`three mutation\` (singular) is not a count" "" "$(policy_problems "$d")"

d="$(fresh_case w-capital)"
printf 'Three mutations beat one.\n' >> "$d/$S"
assert_eq "\`Three mutations beat one\` is a count, whatever its case" \
  "$S: still prescribes a per-story mutation count (matches \`$COUNT_RE\`)" "$(policy_problems "$d")"

d="$(fresh_case w-two)"
printf 'Two mutations, one run each, is enough.\n' >> "$d/$S"
assert_eq "\`Two mutations, one run each\` is a count" \
  "$S: still prescribes a per-story mutation count (matches \`$COUNT_RE\`)" "$(policy_problems "$d")"

summary "policy"
