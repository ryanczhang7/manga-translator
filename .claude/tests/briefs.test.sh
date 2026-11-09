#!/usr/bin/env bash
# Briefs guard: the GREEN brief carries the reuse ladder, and the RED brief
# does not (HARNESS-067).
#
# `.claude/agents/feature-developer.md` gains a `## Reuse before you write`
# section: a five-rung "smallest complete change" ladder and five rules that
# bound it, adapted from ponytail (github.com/DietrichGebert/ponytail, MIT).
# Its first rung, "does it need to exist?", is the right question for
# production code and the wrong one for a test, and ponytail's own test rules
# ("one small test", "trivial changes need none") contradict laws 1 and 4. So
# this suite pins the ladder's PRESENCE in the GREEN brief and its ABSENCE from
# `test-developer.md` and `tdd-cycle/SKILL.md`, which both reach RED.
#
# The sites are prose, so nothing executes them; this is the shape `tdd-cycle`
# calls "code no machine you have can execute: grep for the shape" - a static
# check is the correct instrument here, not a substitute for a test. What it
# cannot pin is that GREEN FOLLOWS the ladder (story, Out of scope). The
# absence half has a known limit: any other spelling of the same idea
# satisfies it. The presence checks are the strong half; the absence needles
# catch the copy-paste route.
#
# `brief_problems <root>` is run over REPO_ROOT, where it must print nothing,
# and over fixtures built compliant by construction with one thing regressed,
# where it must print exactly the one line the Contract pins (C-4). The
# fixtures are what make the real-tree assertion mean anything: a guard that
# never fires is satisfied by the real tree whatever the tree says. DV-1 and
# DV-2 in the story are the same probe against REAL lines, owned by GATES.
#
# Matching is pure bash (mapfile, case, [ = ]): no grep or awk fork per needle.
# HARNESS-023 measured 109 s against 10.6 s for the same output on Windows.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# --- the sites and needles (Contract C-2, C-3: settled, read out) ------------
F=".claude/agents/feature-developer.md"
TD=".claude/agents/test-developer.md"
SK=".claude/skills/tdd-cycle/SKILL.md"

SECTION='## Reuse before you write'
POINTER='Reuse before you write'
METHOD='## Method'

RUNGS=(
  '**Does it need to exist?**'
  '**Already in this codebase?**'
  '**The standard library or the platform?**'
  '**A dependency already installed?**'
  '**Only then, the minimum new code.**'
)
RULES=(
  '- **The tests decide what must exist.**'
  '- **Before a bug fix, grep every caller.**'
  '- **Lazy about the solution, never about completeness.**'
  '- **Moved or merged code keeps its checks.**'
  '- **Never cut:**'
)
NEVER_CUT='- **Never cut:**'
WORDS=(
  'validation at trust boundaries'
  'error handling that prevents data loss'
  'security'
  'accessibility'
)
PONYTAIL=('one small test' 'need none')

# Ladder needles (C-3): the pointer, the five rung labels, and the five rule
# labels without their leading `- `.
LADDER=("$POINTER" "${RUNGS[@]}")
for r in "${RULES[@]}"; do LADDER+=("${r#- }"); done

# --- pure-bash region helpers -------------------------------------------------

# load <file>   LN := the file's lines, a trailing CR stripped from each so a
# CRLF checkout (core.autocrlf) reads the same as an LF one.
load() {
  local i
  LN=(); mapfile -t LN < "$1"
  for i in "${!LN[@]}"; do LN[$i]="${LN[$i]%$'\r'}"; done
}

# blank <line>   Empty or whitespace only.
blank() { [ -z "${1//[[:space:]]/}" ]; }

# starts <s> <prefix>   Succeeds when <s> begins with <prefix>, as fixed text.
starts() { [ "${1:0:${#2}}" = "$2" ]; }

# section <heading>   SEC := the lines of LN from the first line EXACTLY
# <heading> (exclusive) up to, not including, the next line beginning `## `,
# or EOF. HAS_SEC := 1 when the heading exists.
section() {
  local l on=0
  SEC=(); HAS_SEC=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "$l" = "$1" ] && { on=1; HAS_SEC=1; }
      continue
    fi
    starts "$l" '## ' && break
    SEC+=("$l")
  done
  return 0
}

# items   Reads SEC. A line matching `^[0-9]+\. ` starts item n, n being that
# integer. IN[k] := the k-th item's number, IT[k] := its first line after the
# `N. ` prefix.
items() {
  local l k=-1 re='^([0-9]+)\. (.*)$'
  IN=(); IT=()
  for l in "${SEC[@]}"; do
    if [[ $l =~ $re ]]; then
      k=$((k + 1)); IN[$k]="${BASH_REMATCH[1]}"; IT[$k]="${BASH_REMATCH[2]}"
    fi
  done
  return 0
}

# bullets   Reads SEC. A line beginning `- ` starts a bullet; it continues over
# the following non-blank lines that begin with whitespace. BT[k] := the k-th
# bullet's lines, newline-joined, first line first.
bullets() {
  local l k=-1 in_b=0
  BT=()
  for l in "${SEC[@]}"; do
    if starts "$l" '- '; then
      k=$((k + 1)); BT[$k]="$l"; in_b=1
    elif [ "$in_b" = 1 ] && ! blank "$l" && [[ $l == [[:space:]]* ]]; then
      BT[$k]="${BT[$k]}"$'\n'"$l"
    else
      in_b=0
    fi
  done
  return 0
}

# step_two   Reads SEC (the Method section). S2 := the first line beginning
# `2. ` plus its continuation lines (non-blank, beginning with whitespace).
# HAS_S2 := 1 when there is one.
step_two() {
  local l on=0
  S2=""; HAS_S2=0
  for l in "${SEC[@]}"; do
    if [ "$on" = 0 ]; then
      starts "$l" '2. ' && { on=1; HAS_S2=1; S2="$l"; }
      continue
    fi
    if ! blank "$l" && [[ $l == [[:space:]]* ]]; then
      S2="$S2"$'\n'"$l"
    else
      break
    fi
  done
  return 0
}

# whole   W := LN newline-joined, for a fixed-string match anywhere in the file.
whole() {
  local IFS=$'\n'
  W="${LN[*]}"
}

# --- the guard ----------------------------------------------------------------

# check_ponytail <rel>   C-3's ponytail needles over the loaded file.
check_ponytail() {
  local n
  whole
  for n in "${PONYTAIL[@]}"; do
    case "$W" in
      *"$n"*) printf "%s: carries ponytail's test-minimising \`%s\`\n" "$1" "$n" ;;
    esac
  done
  return 0
}

# check_feature   The GREEN brief, loaded: section, rungs, rules, words, step
# 2, ponytail needles, in that order (C-4).
check_feature() {
  local k j n b found nc
  section "$SECTION"
  if [ "$HAS_SEC" = 0 ]; then
    printf '%s: has no `%s` section\n' "$F" "$SECTION"
  else
    items
    for k in 1 2 3 4 5; do
      found=-1
      for j in "${!IT[@]}"; do
        starts "${IT[$j]}" "${RUNGS[$((k - 1))]}" && { found=$j; break; }
      done
      if [ "$found" = -1 ]; then
        printf '%s: its reuse ladder has no rung %s: `%s`\n' "$F" "$k" "${RUNGS[$((k - 1))]}"
      elif [ "${IN[$found]}" != "$k" ]; then
        printf '%s: rung %s `%s` is item %s of its reuse ladder, not item %s\n' \
          "$F" "$k" "${RUNGS[$((k - 1))]}" "${IN[$found]}" "$k"
      fi
    done
    bullets
    nc=-1
    for n in "${RULES[@]}"; do
      found=-1
      for j in "${!BT[@]}"; do
        starts "${BT[$j]}" "$n" && { found=$j; break; }
      done
      [ "$found" = -1 ] && printf '%s: its reuse section has no `%s` rule\n' "$F" "$n"
      [ "$n" = "$NEVER_CUT" ] && nc=$found
    done
    # The words are judged only when the rule exists: an absent rule has
    # already said so, and four "does not name" lines would repeat it.
    if [ "$nc" != -1 ]; then
      b="${BT[$nc]}"
      for n in "${WORDS[@]}"; do
        case "$b" in
          *"$n"*) ;;
          *) printf '%s: its `%s` rule does not name `%s`\n' "$F" "$NEVER_CUT" "$n" ;;
        esac
      done
    fi
  fi
  section "$METHOD"
  step_two
  case "$S2" in
    *"$POINTER"*) ;;
    *) printf '%s: its Method step 2 does not name `%s`\n' "$F" "$POINTER" ;;
  esac
  check_ponytail "$F"
}

# check_red <rel>   A brief that reaches RED, loaded: ladder needles in C-3
# order, then ponytail needles.
check_red() {
  local n
  whole
  for n in "${LADDER[@]}"; do
    case "$W" in
      *"$n"*) printf "%s: carries the GREEN reuse ladder's \`%s\`\n" "$1" "$n" ;;
    esac
  done
  check_ponytail "$1"
}

# brief_problems <root>   One line `<relative-path>: <reason>` per violation
# (Contract C-4, byte for byte); silent when compliant. Always returns 0: the
# output is the verdict.
brief_problems() {
  local root="$1" f
  if [ ! -f "$root/$F" ]; then
    printf '%s: file is missing\n' "$F"
  else
    load "$root/$F"; check_feature
  fi
  for f in "$TD" "$SK"; do
    if [ ! -f "$root/$f" ]; then
      printf '%s: file is missing\n' "$f"
    else
      load "$root/$f"; check_red "$f"
    fi
  done
  return 0
}

# --- a compliant fixture, by construction -------------------------------------
# Never copied from the real tree, which in RED is not compliant. The wording
# beyond the C-2 labels is nobody's contract; GREEN writes the real section
# (Contract C-5).

GOOD_STEP2="$(cat <<'EOF'
2. Write the simplest thing that could make them pass, choosing it by
   `## Reuse before you write` below. Resist building for stories not written.
EOF
)"

# The ladder. Rung 5 sits on a line whose text continues, so "begins with" is
# exercised rather than "equals".
GOOD_LADDER="$(cat <<'EOF'
1. **Does it need to exist?** If a frozen test demands it, yes.
2. **Already in this codebase?** Use it the way the surrounding code does.
3. **The standard library or the platform?** Use that.
4. **A dependency already installed?** Use it; never add one for a few lines.
5. **Only then, the minimum new code.** And no more.
EOF
)"

# The rules. The Never cut bullet spreads its four words over continuation
# lines, so the compliant fixture already proves continuation lines count.
GOOD_RULES="$(cat <<'EOF'
- **The tests decide what must exist.** The ladder chooses how, never whether.
- **Before a bug fix, grep every caller.** Fix the shared code once.
- **Lazy about the solution, never about completeness.** Finish every caller.
- **Moved or merged code keeps its checks.** Its validation, its errors.
- **Never cut:** validation at trust boundaries,
  error handling that prevents data loss,
  security, or accessibility.
EOF
)"

# write_feature <dir> <section-heading> <ladder> <rules> <step2> [<tail>]
write_feature() {
  mkdir -p "$1/.claude/agents"
  {
    printf -- '---\nname: feature-developer\nmodel: opus\n---\n\nYou are the Feature Developer.\n\n'
    printf '%s\n\n' "$METHOD"
    printf '1. Read the story and its handoff first.\n%s\n3. Run the tests after each step.\n\n' "$5"
    printf '%s\n\nTake the first that works.\n\n%s\n\n%s\n\n' "$2" "$3" "$4"
    printf 'Adapted from ponytail (github.com/DietrichGebert/ponytail, MIT).\n\n'
    printf '## When the brief tells you *how*\n\nFollow it.\n'
    [ -n "${6:-}" ] && printf '\n%s\n' "$6"
    return 0
  } > "$1/$F"
}

# write_plain <dir> <rel> [<extra line>]   A RED-side brief carrying none of
# the C-3 needles.
write_plain() {
  mkdir -p "$1/$(dirname "$2")"
  {
    printf -- '# A brief\n\nWrite the failing test first and watch it fail.\n'
    printf 'Every acceptance criterion has a test that fails when it breaks.\n'
    [ -n "${3:-}" ] && printf '%s\n' "$3"
    return 0
  } > "$1/$2"
}

compliant_fixture() { # <dir>
  write_feature "$1" "$SECTION" "$GOOD_LADDER" "$GOOD_RULES" "$GOOD_STEP2"
  write_plain "$1" "$TD"
  write_plain "$1" "$SK"
}

# fresh_case <name>   A new compliant fixture; echoes its path.
fresh_case() { local d="$WORK/$1"; rm -rf "$d"; compliant_fixture "$d"; printf '%s' "$d"; }

# Fault lines, as C-4 pins them.
no_section()  { printf '%s: has no `%s` section' "$F" "$SECTION"; }
no_rung()     { printf '%s: its reuse ladder has no rung %s: `%s`' "$F" "$1" "${RUNGS[$(($1 - 1))]}"; }
misplaced()   { printf '%s: rung %s `%s` is item %s of its reuse ladder, not item %s' "$F" "$1" "${RUNGS[$(($1 - 1))]}" "$2" "$1"; }
no_rule()     { printf '%s: its reuse section has no `%s` rule' "$F" "$1"; }
no_word()     { printf '%s: its `- **Never cut:**` rule does not name `%s`' "$F" "$1"; }
no_step2()    { printf '%s: its Method step 2 does not name `Reuse before you write`' "$F"; }
carries()     { printf "%s: carries the GREEN reuse ladder's \`%s\`" "$1" "$2"; }
ponytail()    { printf "%s: carries ponytail's test-minimising \`%s\`" "$1" "$2"; }

# ---------------------------------------------------------------------------
describe "the real tree (AC-1 to AC-4)"

missing=""
for f in "$F" "$TD" "$SK"; do [ -f "$REPO_ROOT/$f" ] || missing="$missing $f"; done
assert_eq "all three briefs the guard judges exist in this repository" "" "$missing"

assert_eq "brief_problems over the real tree prints nothing: feature-developer.md carries the reuse ladder and its rules, step 2 points at it, and neither RED-side brief carries the ladder or ponytail's test rules" \
  "" "$(brief_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "the fixture: compliant by construction"

d="$(fresh_case compliant)"
assert_eq "the compliant fixture is silent" "" "$(brief_problems "$d")"

d="$(fresh_case crlf)"
for f in "$F" "$TD" "$SK"; do
  mapfile -t L < "$d/$f"; printf '%s\r\n' "${L[@]}" > "$d/$f"
done
assert_eq "a CRLF checkout of the compliant fixture is silent too" "" "$(brief_problems "$d")"

for f in "$F" "$TD" "$SK"; do
  d="$(fresh_case "missing-${f//\//_}")"
  rm -f "$d/$f"
  assert_eq "a missing $f gives only \`file is missing\` for it" \
    "$f: file is missing" "$(brief_problems "$d")"
done

# ---------------------------------------------------------------------------
describe "AC-1: the ladder is in the GREEN brief, in order"

d="$(fresh_case rung3-deleted)"
write_feature "$d" "$SECTION" "$(printf '%s\n' "$GOOD_LADDER" | { mapfile -t L; printf '%s\n' "${L[0]}" "${L[1]}" "${L[3]}" "${L[4]}"; })" "$GOOD_RULES" "$GOOD_STEP2" \
  'Outside the section: 3. **The standard library or the platform?**'
assert_eq "rung 3 deleted from the ladder, though its label is elsewhere in the file, gives exactly the \"has no rung 3\" line" \
  "$(no_rung 3)" "$(brief_problems "$d")"

d="$(fresh_case rungs-2-3-swapped)"
write_feature "$d" "$SECTION" "$(cat <<'EOF'
1. **Does it need to exist?** If a frozen test demands it, yes.
2. **The standard library or the platform?** Use that.
3. **Already in this codebase?** Use it the way the surrounding code does.
4. **A dependency already installed?** Use it; never add one for a few lines.
5. **Only then, the minimum new code.** And no more.
EOF
)" "$GOOD_RULES" "$GOOD_STEP2"
assert_eq "rungs 2 and 3 swapped give exactly the two \"is not item\" lines, rung 2 first" \
  "$(misplaced 2 3)
$(misplaced 3 2)" "$(brief_problems "$d")"

d="$(fresh_case heading-changed)"
write_feature "$d" '## Reuse first' "$GOOD_LADDER" "$GOOD_RULES" "$GOOD_STEP2"
assert_eq "the rung labels present but the heading changed to \`## Reuse first\` gives exactly the \"has no section\" line, and no rung lines" \
  "$(no_section)" "$(brief_problems "$d")"

d="$(fresh_case heading-trailing-text)"
write_feature "$d" '## Reuse before you write, mostly' "$GOOD_LADDER" "$GOOD_RULES" "$GOOD_STEP2"
assert_eq "a heading that only BEGINS with the section heading is not it" \
  "$(no_section)" "$(brief_problems "$d")"

d="$(fresh_case rung-label-not-at-start)"
write_feature "$d" "$SECTION" "$(cat <<'EOF'
1. **Does it need to exist?** If a frozen test demands it, yes.
2. **Already in this codebase?** Use it the way the surrounding code does.
3. Then ask: **The standard library or the platform?** Use that.
4. **A dependency already installed?** Use it; never add one for a few lines.
5. **Only then, the minimum new code.** And no more.
EOF
)" "$GOOD_RULES" "$GOOD_STEP2"
assert_eq "a rung label inside item 3's text but not at its start is no rung 3" \
  "$(no_rung 3)" "$(brief_problems "$d")"

d="$(fresh_case rung-as-bullet)"
write_feature "$d" "$SECTION" "$(cat <<'EOF'
1. **Does it need to exist?** If a frozen test demands it, yes.
2. **Already in this codebase?** Use it the way the surrounding code does.
- **The standard library or the platform?** Use that.
4. **A dependency already installed?** Use it; never add one for a few lines.
5. **Only then, the minimum new code.** And no more.
EOF
)" "$GOOD_RULES" "$GOOD_STEP2"
assert_eq "a rung label on a bullet rather than a numbered item is no rung" \
  "$(no_rung 3)" "$(brief_problems "$d")"

d="$(fresh_case ladder-after-next-heading)"
write_feature "$d" "$SECTION" "## Interlude" "$GOOD_RULES" "$GOOD_STEP2" "$GOOD_LADDER"
assert_eq "a ladder below the next \`## \` heading is outside the section: all five rungs and all five rules are missing" \
  "$(no_rung 1)
$(no_rung 2)
$(no_rung 3)
$(no_rung 4)
$(no_rung 5)
$(no_rule "${RULES[0]}")
$(no_rule "${RULES[1]}")
$(no_rule "${RULES[2]}")
$(no_rule "${RULES[3]}")
$(no_rule "${RULES[4]}")" "$(brief_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-2: the rules that bound \"lazy\" are in that section"

d="$(fresh_case no-bug-fix-rule)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "${GOOD_RULES//"- **Before a bug fix, grep every caller.** Fix the shared code once."/}" "$GOOD_STEP2"
assert_eq "the \`Before a bug fix\` bullet removed gives exactly its one \"has no rule\" line" \
  "$(no_rule "${RULES[1]}")" "$(brief_problems "$d")"

d="$(fresh_case no-accessibility)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "${GOOD_RULES//accessibility/usability}" "$GOOD_STEP2" \
  'Elsewhere in the file: accessibility matters.'
assert_eq "the \`Never cut\` bullet without \`accessibility\`, though the file names it elsewhere, gives exactly the one \"does not name\" line" \
  "$(no_word accessibility)" "$(brief_problems "$d")"

d="$(fresh_case never-cut-moved-out)"
rules_head="${GOOD_RULES%%"$NEVER_CUT"*}"
rules_tail="$NEVER_CUT${GOOD_RULES#*"$NEVER_CUT"}"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "$rules_head" "$GOOD_STEP2" "$rules_tail"
assert_eq "the \`Never cut\` bullet moved below the next \`## \` heading gives its \"has no rule\" line, and no word lines" \
  "$(no_rule "$NEVER_CUT")" "$(brief_problems "$d")"

d="$(fresh_case word-after-blank)"
LAST_LINE=$'\n''  security, or accessibility.'
write_feature "$d" "$SECTION" "$GOOD_LADDER" "${GOOD_RULES//"$LAST_LINE"/$'\n'"$LAST_LINE"}" "$GOOD_STEP2"
assert_eq "the \`Never cut\` bullet ends at a blank line: words on an indented line after it are not in the bullet" \
  "$(no_word security)
$(no_word accessibility)" "$(brief_problems "$d")"

d="$(fresh_case word-in-next-bullet)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "${GOOD_RULES//"$LAST_LINE"/$'\n''- Also security, or accessibility.'}" "$GOOD_STEP2"
assert_eq "the \`Never cut\` bullet ends at the next \`- \` line: words in the next bullet are not in it" \
  "$(no_word security)
$(no_word accessibility)" "$(brief_problems "$d")"

d="$(fresh_case all-words-missing)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "${GOOD_RULES%%"$NEVER_CUT"*}$NEVER_CUT nothing at all." "$GOOD_STEP2"
assert_eq "a \`Never cut\` bullet naming none of the four words gives four lines, in C-2 order" \
  "$(no_word "${WORDS[0]}")
$(no_word "${WORDS[1]}")
$(no_word "${WORDS[2]}")
$(no_word "${WORDS[3]}")" "$(brief_problems "$d")"

d="$(fresh_case rule-label-not-at-start)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "${GOOD_RULES//"- **Moved or merged"/"- Also, **Moved or merged"}" "$GOOD_STEP2"
assert_eq "a rule label inside a bullet but not at its start is no rule" \
  "$(no_rule "${RULES[3]}")" "$(brief_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3: Method step 2 points at the section"

d="$(fresh_case step2-current-text)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "$GOOD_RULES" "$(cat <<'EOF'
2. Write the simplest thing that could make them pass. Resist building for
   stories that have not been written yet; the backlog will come back to you.
EOF
)"
assert_eq "step 2 as today's text, \"Write the simplest thing that could make them pass.\", gives exactly the step-2 line" \
  "$(no_step2)" "$(brief_problems "$d")"

d="$(fresh_case pointer-in-step3)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "$GOOD_RULES" "$(cat <<'EOF'
2. Write the simplest thing that could make them pass.
3a. Choose it by `Reuse before you write`.
EOF
)"
assert_eq "the pointer on a line that is not step 2 or its continuation does not count" \
  "$(no_step2)" "$(brief_problems "$d")"

d="$(fresh_case pointer-after-blank)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "$GOOD_RULES" "$(cat <<'EOF'
2. Write the simplest thing that could make them pass.

   Choose it by `Reuse before you write`.
EOF
)"
assert_eq "step 2 ends at a blank line: the pointer on an indented line after it is not in step 2" \
  "$(no_step2)" "$(brief_problems "$d")"

d="$(fresh_case no-method)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "$GOOD_RULES" "$GOOD_STEP2"
mapfile -t L < "$d/$F"; for i in "${!L[@]}"; do [ "${L[$i]}" = "$METHOD" ] && L[$i]='## Steps'; done
printf '%s\n' "${L[@]}" > "$d/$F"
assert_eq "a step 2 outside any \`## Method\` section does not count" \
  "$(no_step2)" "$(brief_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-4: the ladder does not reach the test-writing brief"

d="$(fresh_case td-gains-rung1)"
write_plain "$d" "$TD" '1. **Does it need to exist?** Skip it.'
assert_eq "test-developer.md gaining \`1. **Does it need to exist?** Skip it.\` gives exactly one \"carries the GREEN reuse ladder\" line naming that file and needle" \
  "$(carries "$TD" "${RUNGS[0]}")" "$(brief_problems "$d")"

d="$(fresh_case sk-gains-need-none)"
write_plain "$d" "$SK" 'Trivial changes need none.'
assert_eq "tdd-cycle/SKILL.md gaining \"Trivial changes need none.\" gives exactly one \"carries ponytail's\" line" \
  "$(ponytail "$SK" 'need none')" "$(brief_problems "$d")"

d="$(fresh_case f-gains-one-small-test)"
write_feature "$d" "$SECTION" "$GOOD_LADDER" "$GOOD_RULES" "$GOOD_STEP2" \
  'New logic leaves one small test, not coverage.'
assert_eq "feature-developer.md is judged for ponytail's needles too" \
  "$(ponytail "$F" 'one small test')" "$(brief_problems "$d")"

d="$(fresh_case sk-gains-pointer-and-rule)"
write_plain "$d" "$SK" 'See Reuse before you write: **Before a bug fix, grep every caller.**'
assert_eq "the pointer and a rule label without its \`- \` are ladder needles, reported in C-3 order" \
  "$(carries "$SK" "$POINTER")
$(carries "$SK" "${RULES[1]#- }")" "$(brief_problems "$d")"

d="$(fresh_case every-ladder-needle)"
write_plain "$d" "$TD" "$(printf '%s\n' "${LADDER[@]}")"
expect=""
for n in "${LADDER[@]}"; do expect="$expect$(carries "$TD" "$n")"$'\n'; done
assert_eq "every one of the eleven ladder needles is caught in test-developer.md, in C-3 order" \
  "${expect%$'\n'}" "$(brief_problems "$d")"

d="$(fresh_case both-red-files)"
write_plain "$d" "$TD" 'One small test is enough. one small test. need none.'
write_plain "$d" "$SK" '**Only then, the minimum new code.**'
assert_eq "both RED-side files regressed report test-developer.md first, then tdd-cycle; ponytail needles are case-sensitive" \
  "$(ponytail "$TD" 'one small test')
$(ponytail "$TD" 'need none')
$(carries "$SK" "${RUNGS[4]}")" "$(brief_problems "$d")"

summary "briefs"
