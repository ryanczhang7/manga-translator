#!/usr/bin/env bash
# Procedure guard: the full self-test runs before a story reaches REVIEW
# (HARNESS-032, audit manga-translator-port-2026-10-02, Decided item 6 A).
#
# In the field a story raised a floor in GATES, an upstream suite pinned the old
# value, every local gate passed, and CI's self-test failed - because the
# GATES -> REVIEW steps in /advance-story ran gates.sh and check-boundaries.sh
# and never the self-test, and neither command was even permitted to run it.
# The sites are prose, so nothing executes them; this suite is the shape
# `tdd-cycle` calls "code no machine you have can execute: grep for the shape".
# What it CAN pin: both commands permit the two scripts, advance-story's
# numbered steps put the FULL self-test before the phase change, and
# complete-story's summary names it. What it cannot pin is that an
# orchestrator follows the steps (story, Context).
#
# `procedure_problems <root>` is run over REPO_ROOT, where it must print
# nothing, and over fixtures built compliant by construction with one thing
# regressed, where it must print exactly the one line the Contract pins (C-4).
# The fixtures are what make the real-tree assertion mean anything: a guard
# that never fires is satisfied by the real tree whatever the tree says. DV-1
# and DV-2 in the story are the same probe against REAL lines, owned by GATES.
#
# Matching is pure bash (mapfile, case, [ = ]): no grep or awk fork per needle.
# HARNESS-023 measured 109 s against 10.6 s for the same output on Windows.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# --- the sites and needles (Contract C-2, C-3: settled, read out) ------------
ADVANCE=".claude/commands/advance-story.md"
COMPLETE=".claude/commands/complete-story.md"

TOOL_SELFTEST='Bash(bash scripts/selftest.sh:*)'
TOOL_CILOCAL='Bash(bash scripts/ci-local.sh:*)'
STEP_SELFTEST='`bash scripts/selftest.sh`'
STEP_PHASE='`bash scripts/phase.sh set $1 REVIEW`'
STEP_BOUNDARIES='`bash scripts/check-boundaries.sh`'
STEP_WORDS=('detached' 'Windows' '## Notes')

PARA_START='**GATES → REVIEW.**'
BULLET_START='- **GATES → REVIEW'

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

# trim <s>   T := <s> without leading and trailing whitespace.
trim() {
  T="$1"
  T="${T#"${T%%[![:space:]]*}"}"
  T="${T%"${T##*[![:space:]]}"}"
}

# allowed_tools   AT := the text after `allowed-tools:` on the frontmatter line
# that begins with it; HAS_AT := 1 when there is one. The frontmatter is line 1
# exactly `---` up to the next line exactly `---`. No frontmatter, or one never
# closed, has no allowed-tools line.
allowed_tools() {
  local i n="${#LN[@]}" end=-1
  AT=""; HAS_AT=0
  [ "$n" -gt 0 ] && [ "${LN[0]}" = "---" ] || return 0
  for ((i = 1; i < n; i++)); do
    [ "${LN[$i]}" = "---" ] && { end=$i; break; }
  done
  [ "$end" -gt 0 ] || return 0
  for ((i = 1; i < end; i++)); do
    case "${LN[$i]}" in
      'allowed-tools:'*) AT="${LN[$i]#allowed-tools:}"; HAS_AT=1; return 0 ;;
    esac
  done
  return 0
}

# has_entry <needle>   Succeeds when one comma-separated, trimmed entry of AT
# is EQUAL to <needle>. Containing it is not enough.
has_entry() {
  local e
  local -a parts
  IFS=',' read -r -a parts <<<"$AT"
  for e in "${parts[@]}"; do
    trim "$e"
    [ "$T" = "$1" ] && return 0
  done
  return 1
}

# gates_steps   Reads advance-story's GATES -> REVIEW paragraph out of LN:
# from the first line beginning `**GATES → REVIEW.**` to just before the next
# line beginning `**`, or EOF. HAS_PARA := 1 when it exists. Inside it, a line
# matching `^[0-9]+\. ` starts a step numbered by that integer; the step
# continues over following non-blank lines that start with whitespace, and ends
# at a blank line, a line not starting with whitespace, or the next step.
# SN[k] := the k-th step's number, ST[k] := its lines, newline-joined.
gates_steps() {
  local l on=0 k=-1 in_step=0 re='^([0-9]+)\. '
  HAS_PARA=0; SN=(); ST=()
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#PARA_START}}" = "$PARA_START" ] && { on=1; HAS_PARA=1; }
      continue
    fi
    [ "${l:0:2}" = "**" ] && break
    if [[ $l =~ $re ]]; then
      k=$((k + 1)); SN[$k]="${BASH_REMATCH[1]}"; ST[$k]="$l"; in_step=1
    elif [ "$in_step" = 1 ] && ! blank "$l" && [[ $l == [[:space:]]* ]]; then
      ST[$k]="${ST[$k]}"$'\n'"$l"
    else
      in_step=0
    fi
  done
  return 0
}

# first_step <needle>   K := the index of the first step containing <needle>
# as a fixed string, or -1.
first_step() {
  local k
  K=-1
  for k in "${!ST[@]}"; do
    case "${ST[$k]}" in *"$1"*) K=$k; return 0 ;; esac
  done
  return 0
}

# gates_bullet   R := complete-story's bullet: the first line beginning
# `- **GATES → REVIEW`, plus the lines after it up to, not including, the next
# line beginning `- ` or a blank line. HAS_BULLET := 1 when it exists.
gates_bullet() {
  local l on=0
  R=""; HAS_BULLET=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#BULLET_START}}" = "$BULLET_START" ] && { on=1; HAS_BULLET=1; R="$l"; }
      continue
    fi
    if [ "${l:0:2}" = "- " ] || blank "$l"; then break; fi
    R="$R"$'\n'"$l"
  done
  return 0
}

# --- the guard ----------------------------------------------------------------

# check_tools <rel>   The two allowed-tools lines for the loaded file.
check_tools() {
  local f="$1" t
  allowed_tools
  if [ "$HAS_AT" = 0 ]; then
    printf '%s: has no `allowed-tools:` line in its frontmatter\n' "$f"
    return 0
  fi
  for t in "$TOOL_SELFTEST" "$TOOL_CILOCAL"; do
    has_entry "$t" || printf '%s: its allowed-tools do not permit `%s`\n' "$f" "$t"
  done
  return 0
}

# procedure_problems <root>   One line `<relative-path>: <reason>` per
# violation (Contract C-4, byte for byte); silent when compliant. Always
# returns 0: the output is the verdict.
procedure_problems() {
  local root="$1" n ks kp kb w missing
  # advance-story: tools, step needles, order, words.
  if [ ! -f "$root/$ADVANCE" ]; then
    printf '%s: file is missing\n' "$ADVANCE"
  else
    load "$root/$ADVANCE"
    check_tools "$ADVANCE"
    gates_steps
    if [ "$HAS_PARA" = 0 ]; then
      printf '%s: has no `**GATES → REVIEW.**` paragraph\n' "$ADVANCE"
    else
      missing=0
      first_step "$STEP_SELFTEST"; ks=$K
      first_step "$STEP_PHASE"; kp=$K
      first_step "$STEP_BOUNDARIES"; kb=$K
      for n in "$ks:$STEP_SELFTEST" "$kp:$STEP_PHASE" "$kb:$STEP_BOUNDARIES"; do
        if [ "${n%%:*}" = "-1" ]; then
          printf '%s: its GATES → REVIEW steps do not name %s\n' "$ADVANCE" "${n#*:}"
          missing=1
        fi
      done
      if [ "$missing" = 0 ]; then
        [ "${SN[$ks]}" -lt "${SN[$kp]}" ] || printf '%s: its GATES → REVIEW steps are out of order: %s is step %s, %s is step %s\n' \
          "$ADVANCE" "$STEP_SELFTEST" "${SN[$ks]}" "$STEP_PHASE" "${SN[$kp]}"
        [ "${SN[$kp]}" -lt "${SN[$kb]}" ] || printf '%s: its GATES → REVIEW steps are out of order: %s is step %s, %s is step %s\n' \
          "$ADVANCE" "$STEP_PHASE" "${SN[$kp]}" "$STEP_BOUNDARIES" "${SN[$kb]}"
      fi
      if [ "$ks" != "-1" ]; then
        for w in "${STEP_WORDS[@]}"; do
          case "${ST[$ks]}" in
            *"$w"*) ;;
            *) printf '%s: its `bash scripts/selftest.sh` step does not say `%s`\n' "$ADVANCE" "$w" ;;
          esac
        done
      fi
    fi
  fi
  # complete-story: tools, bullet.
  if [ ! -f "$root/$COMPLETE" ]; then
    printf '%s: file is missing\n' "$COMPLETE"
  else
    load "$root/$COMPLETE"
    check_tools "$COMPLETE"
    gates_bullet
    if [ "$HAS_BULLET" = 0 ]; then
      printf '%s: has no `- **GATES → REVIEW` bullet\n' "$COMPLETE"
    else
      case "$R" in
        *"$STEP_SELFTEST"*) ;;
        *) printf '%s: its GATES → REVIEW bullet does not name `bash scripts/selftest.sh`\n' "$COMPLETE" ;;
      esac
    fi
  fi
  return 0
}

# --- a compliant fixture, by construction -------------------------------------
# Never copied from the real tree, which in RED is not compliant. The wording
# is nobody's contract; GREEN writes the real files (Contract C-6).

GOOD_TOOLS='allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/gates.sh:*), Bash(bash scripts/check-boundaries.sh:*), Bash(bash scripts/selftest.sh:*), Bash(bash scripts/ci-local.sh:*), Bash(git:*), Read, Task'

# The GATES -> REVIEW step list. Step 1's words sit on its continuation lines,
# so the compliant fixture already proves continuation lines count.
GOOD_STEPS="$(cat <<'EOF'
1. `bash scripts/selftest.sh` — the whole self-test, every suite, while the
   story is still at GATES. Run it detached; on a Windows host it is slow.
   Paste its last line into `## Notes`.
2. `bash scripts/phase.sh set $1 REVIEW`
3. Commit.
4. `bash scripts/check-boundaries.sh` — the second script CI runs.
   Fix anything it reports.
5. Push and open the PR.
EOF
)"

GOOD_BULLET="$(cat <<'EOF'
- **GATES → REVIEW runs the full `bash scripts/selftest.sh` first**, detached
  and alone, then sets the phase before committing.
EOF
)"

# write_advance <dir> <tools-line> <steps> [<prose-after-steps>]
write_advance() {
  mkdir -p "$1/.claude/commands"
  {
    printf -- '---\ndescription: Move one story forward\n%s\n---\n\nStory: $1\n\n' "$2"
    printf '%s Only when every required gate passes.\n\nThen, **in this order**:\n\n' "$PARA_START"
    printf '%s\n\n' "$3"
    [ -n "${4:-}" ] && printf '%s\n\n' "$4"
    printf '**REVIEW → DONE.** Only once the PR is merged.\n'
  } > "$1/$ADVANCE"
}

# write_complete <dir> <tools-line> <bullet> [<tail>]
write_complete() {
  mkdir -p "$1/.claude/commands"
  {
    printf -- '---\ndescription: Drive one story\n%s\n---\n\nStory: $1\n\n' "$2"
    printf -- '- **RED and GREEN each end with `bash scripts/gates.sh --fast`.**\n'
    printf '%s\n' "$3"
    printf -- '- **A return to RED ends with pasted red.**\n\n'
    [ -n "${4:-}" ] && printf '%s\n' "$4"
    printf 'The end.\n'
  } > "$1/$COMPLETE"
}

compliant_fixture() { # <dir>
  write_advance "$1" "$GOOD_TOOLS" "$GOOD_STEPS"
  write_complete "$1" "$GOOD_TOOLS" "$GOOD_BULLET"
}

# fresh_case <name>   A new compliant fixture; echoes its path.
fresh_case() { local d="$WORK/$1"; rm -rf "$d"; compliant_fixture "$d"; printf '%s' "$d"; }

# Fault lines, as C-4 pins them.
A="$ADVANCE"; C="$COMPLETE"
no_tool()   { printf '%s: its allowed-tools do not permit `%s`' "$1" "$2"; }
no_step()   { printf '%s: its GATES → REVIEW steps do not name %s' "$ADVANCE" "$1"; }
disorder()  { printf '%s: its GATES → REVIEW steps are out of order: %s is step %s, %s is step %s' "$ADVANCE" "$1" "$2" "$3" "$4"; }
no_word()   { printf '%s: its `bash scripts/selftest.sh` step does not say `%s`' "$ADVANCE" "$1"; }
NO_BULLET_NEEDLE="$C: its GATES → REVIEW bullet does not name \`bash scripts/selftest.sh\`"

# ---------------------------------------------------------------------------
describe "the real tree (AC-1 to AC-4)"

missing=""
for f in "$ADVANCE" "$COMPLETE"; do [ -f "$REPO_ROOT/$f" ] || missing="$missing $f"; done
assert_eq "both commands that reach REVIEW exist in this repository" "" "$missing"

assert_eq "procedure_problems over the real tree prints nothing: both commands permit selftest.sh and ci-local.sh, and the full self-test is a GATES → REVIEW step before the phase change" \
  "" "$(procedure_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "the fixture: compliant by construction"

d="$(fresh_case compliant)"
assert_eq "the compliant fixture is silent" "" "$(procedure_problems "$d")"

d="$(fresh_case spaced-entries)"
write_advance "$d" 'allowed-tools:Bash(bash scripts/selftest.sh:*) ,   Bash(bash scripts/ci-local.sh:*)  ,Read' "$GOOD_STEPS"
assert_eq "entries are trimmed: extra spaces around a comma, and none after the colon, still permit" \
  "" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-1: both commands permit both scripts in allowed-tools"

d="$(fresh_case tool-missing)"
write_advance "$d" 'allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/ci-local.sh:*), Read' "$GOOD_STEPS"
assert_eq "advance-story without the selftest.sh entry gives one line naming the file and the entry" \
  "$(no_tool "$A" "$TOOL_SELFTEST")" "$(procedure_problems "$d")"

d="$(fresh_case tool-no-star)"
write_complete "$d" 'allowed-tools: Bash(bash scripts/selftest.sh:*), Bash(bash scripts/ci-local.sh), Read' "$GOOD_BULLET"
assert_eq "complete-story spelling the ci-local.sh entry without \`:*\` gives the same line" \
  "$(no_tool "$C" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

d="$(fresh_case tool-in-body)"
write_advance "$d" 'allowed-tools: Bash(bash scripts/selftest.sh:*), Read' "$GOOD_STEPS" \
  'It may also run Bash(bash scripts/ci-local.sh:*) once the commit exists.'
assert_eq "an entry that appears only in the body, not the allowed-tools line, gives the same line" \
  "$(no_tool "$A" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

d="$(fresh_case tool-in-other-frontmatter-key)"
write_complete "$d" 'allowed-tools: Bash(bash scripts/selftest.sh:*), Read
notes: Bash(bash scripts/ci-local.sh:*)' "$GOOD_BULLET"
assert_eq "an entry on another frontmatter key does not count" \
  "$(no_tool "$C" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

d="$(fresh_case tool-merged)"
write_advance "$d" 'allowed-tools: Bash(bash scripts/selftest.sh:*) Bash(bash scripts/ci-local.sh:*), Read' "$GOOD_STEPS"
assert_eq "an entry that only CONTAINS a needle is not equal to it: a missing comma loses both" \
  "$(no_tool "$A" "$TOOL_SELFTEST")
$(no_tool "$A" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

d="$(fresh_case tool-both-missing-both-files)"
write_advance "$d" 'allowed-tools: Read' "$GOOD_STEPS"
write_complete "$d" 'allowed-tools: Read' "$GOOD_BULLET"
assert_eq "both entries missing from both files gives four lines, advance-story first" \
  "$(no_tool "$A" "$TOOL_SELFTEST")
$(no_tool "$A" "$TOOL_CILOCAL")
$(no_tool "$C" "$TOOL_SELFTEST")
$(no_tool "$C" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

d="$(fresh_case no-allowed-tools)"
write_complete "$d" 'description2: nothing here' "$GOOD_BULLET"
assert_eq "a frontmatter with no allowed-tools line gives that line only, never the two \"do not permit\" lines" \
  "$C: has no \`allowed-tools:\` line in its frontmatter" "$(procedure_problems "$d")"

d="$(fresh_case no-frontmatter)"
{ printf '%s\n\n' "$GOOD_TOOLS"; printf '%s\n' "$GOOD_BULLET"; } > "$d/$COMPLETE"
assert_eq "an allowed-tools line with no frontmatter around it is not in a frontmatter" \
  "$C: has no \`allowed-tools:\` line in its frontmatter" "$(procedure_problems "$d")"

d="$(fresh_case allowed-tools-after-frontmatter)"
{ printf -- '---\ndescription: x\n---\n\n%s\n\n' "$GOOD_TOOLS"; printf '%s\n' "$GOOD_BULLET"; } > "$d/$COMPLETE"
assert_eq "an allowed-tools line after the frontmatter closes does not count" \
  "$C: has no \`allowed-tools:\` line in its frontmatter" "$(procedure_problems "$d")"

d="$(fresh_case advance-missing)"
rm -f "$d/$ADVANCE"
assert_eq "a missing command file gives only \`file is missing\`" \
  "$A: file is missing" "$(procedure_problems "$d")"

d="$(fresh_case complete-missing)"
rm -f "$d/$COMPLETE"
assert_eq "a missing complete-story gives only \`file is missing\`" \
  "$C: file is missing" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-2: the full self-test is a numbered step before the phase change, and check-boundaries after it"

d="$(fresh_case selftest-after-phase)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/phase.sh set $1 REVIEW`
2. `bash scripts/selftest.sh`, detached, slow on Windows; paste into `## Notes`.
3. Commit.
4. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "the self-test step after the phase step gives one out-of-order line" \
  "$(disorder "$STEP_SELFTEST" 2 "$STEP_PHASE" 1)" "$(procedure_problems "$d")"

d="$(fresh_case selftest-in-prose)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
Run `bash scripts/selftest.sh` first, detached, slow on Windows; see `## Notes`.

1. `bash scripts/phase.sh set $1 REVIEW`
2. Commit.
3. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "the self-test named only in the paragraph's prose, in no numbered step, gives one \"do not name\" line" \
  "$(no_step "$STEP_SELFTEST")" "$(procedure_problems "$d")"

d="$(fresh_case selftest-targeted)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/selftest.sh reporting` — detached, slow on Windows; `## Notes`.
2. `bash scripts/phase.sh set $1 REVIEW`
3. Commit.
4. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "a targeted \`bash scripts/selftest.sh reporting\` is not the full run: one \"do not name\" line" \
  "$(no_step "$STEP_SELFTEST")" "$(procedure_problems "$d")"

d="$(fresh_case selftest-other-paragraph)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/phase.sh set $1 REVIEW`
2. Commit.
3. `bash scripts/check-boundaries.sh`

**REVIEW → DONE.** Before closing:

1. `bash scripts/selftest.sh` — detached, slow on Windows; paste into `## Notes`.
EOF
)"
assert_eq "the self-test step present only in the REVIEW → DONE paragraph gives one \"do not name\" line" \
  "$(no_step "$STEP_SELFTEST")" "$(procedure_problems "$d")"

d="$(fresh_case boundaries-before-phase)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/selftest.sh` — detached, slow on Windows; paste into `## Notes`.
2. `bash scripts/check-boundaries.sh`
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
EOF
)"
assert_eq "the check-boundaries step moved before the phase step gives one out-of-order line" \
  "$(disorder "$STEP_PHASE" 3 "$STEP_BOUNDARIES" 2)" "$(procedure_problems "$d")"

d="$(fresh_case same-step)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/selftest.sh`, then `bash scripts/phase.sh set $1 REVIEW` —
   detached, slow on Windows; paste into `## Notes`.
2. Commit.
3. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "two needles in the same step count as out of order" \
  "$(disorder "$STEP_SELFTEST" 1 "$STEP_PHASE" 1)" "$(procedure_problems "$d")"

d="$(fresh_case first-step-wins)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/phase.sh set $1 REVIEW`
2. `bash scripts/selftest.sh` — detached, slow on Windows; paste into `## Notes`.
3. `bash scripts/check-boundaries.sh`
4. If that failed, `bash scripts/phase.sh set $1 REVIEW` again.
EOF
)"
assert_eq "a needle in more than one step is judged by its FIRST step" \
  "$(disorder "$STEP_SELFTEST" 2 "$STEP_PHASE" 1)" "$(procedure_problems "$d")"

d="$(fresh_case phase-missing)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/selftest.sh` — detached, slow on Windows; paste into `## Notes`.
2. Commit.
3. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "the phase step missing gives its own \"do not name\" line, and the order check is suppressed" \
  "$(no_step "$STEP_PHASE")" "$(procedure_problems "$d")"

d="$(fresh_case boundaries-missing)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/selftest.sh` — detached, slow on Windows; paste into `## Notes`.
2. `bash scripts/phase.sh set $1 REVIEW`
3. Commit.
EOF
)"
assert_eq "the check-boundaries step missing gives its own \"do not name\" line" \
  "$(no_step "$STEP_BOUNDARIES")" "$(procedure_problems "$d")"

d="$(fresh_case continuation-counts)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. The whole harness self-test, every suite:
   `bash scripts/selftest.sh` — detached, slow on Windows; paste into `## Notes`.
2. `bash scripts/phase.sh set $1 REVIEW`
3. Commit, then run
   `bash scripts/check-boundaries.sh`.
EOF
)"
assert_eq "a needle on an indented continuation line is in that step" \
  "" "$(procedure_problems "$d")"

d="$(fresh_case indented-after-blank)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. The whole harness self-test, every suite.

   `bash scripts/selftest.sh` — detached, slow on Windows; paste into `## Notes`.
2. `bash scripts/phase.sh set $1 REVIEW`
3. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "an indented line after a blank line has left the step: the needle is in no step" \
  "$(no_step "$STEP_SELFTEST")" "$(procedure_problems "$d")"

d="$(fresh_case star-line-ends-region)"
write_advance "$d" "$GOOD_TOOLS" "**Note.** The steps follow.

$GOOD_STEPS"
assert_eq "a line beginning \`**\` inside the paragraph ends it early, so the steps after it are not read" \
  "$(no_step "$STEP_SELFTEST")
$(no_step "$STEP_PHASE")
$(no_step "$STEP_BOUNDARIES")" "$(procedure_problems "$d")"

d="$(fresh_case no-paragraph)"
{ printf -- '---\n%s\n---\n\n' "$GOOD_TOOLS"; printf '**GATES -> REVIEW.** ascii arrow.\n\n%s\n' "$GOOD_STEPS"; } > "$d/$ADVANCE"
assert_eq "advance-story with no \`**GATES → REVIEW.**\` paragraph gives that line only" \
  "$A: has no \`**GATES → REVIEW.**\` paragraph" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3: the self-test step says detached, Windows and ## Notes"

for w in 'detached' 'Windows' '## Notes'; do
  d="$(fresh_case "word-$w")"
  steps="${GOOD_STEPS//"$w"/elsewhere}"
  write_advance "$d" "$GOOD_TOOLS" "$steps" "Prose outside the steps says $w."
  assert_eq "\`$w\` missing from the self-test step but present elsewhere in the file gives one line naming it" \
    "$(no_word "$w")" "$(procedure_problems "$d")"
done

d="$(fresh_case words-in-next-step)"
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. `bash scripts/selftest.sh`
2. `bash scripts/phase.sh set $1 REVIEW` — detached, slow on Windows; `## Notes`.
3. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "the three words in a DIFFERENT step do not satisfy the self-test step" \
  "$(no_word detached)
$(no_word Windows)
$(no_word '## Notes')" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-4: complete-story's GATES → REVIEW bullet names the full self-test"

d="$(fresh_case bullet-without)"
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW sets the phase before committing**, then pushes.' \
  'Elsewhere: run `bash scripts/selftest.sh` at some point.'
assert_eq "the needle present elsewhere in the file but not in that bullet gives one line" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

d="$(fresh_case bullet-targeted)"
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest.sh procedure` first.**'
assert_eq "a targeted run in the bullet is not the full self-test" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

d="$(fresh_case bullet-after-blank)"
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW sets the phase before committing.**

  Then `bash scripts/selftest.sh`.'
assert_eq "the bullet ends at a blank line: the needle after it is not in the bullet" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

d="$(fresh_case bullet-next-bullet)"
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW sets the phase before committing.**
- Then `bash scripts/selftest.sh`.'
assert_eq "the bullet ends at the next \`- \` line: the needle in the next bullet is not in it" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

d="$(fresh_case no-bullet)"
write_complete "$d" "$GOOD_TOOLS" '- **REVIEW → DONE** merges.'
assert_eq "complete-story with no \`- **GATES → REVIEW\` bullet gives that line only" \
  "$C: has no \`- **GATES → REVIEW\` bullet" "$(procedure_problems "$d")"

summary "procedure"
