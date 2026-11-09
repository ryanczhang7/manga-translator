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
# HARNESS-068 extends it: a diff review, run through the `diff-review` skill, is
# the FIRST GATES -> REVIEW step (before the self-test), the step says how a
# finding routes, complete-story's bullet names the review before the
# self-test, and the skill file carries the review's rules. Same pattern: the
# real tree must be silent, fixtures regress one thing each (story C-1..C-4).
#
# HARNESS-072 moves the step's needle to `SELFTEST_JOBS=4 bash scripts/selftest.sh`
# and adds `other test runs` to its words. Every earlier case moved to the new
# token with its verdict unchanged; the old spelling is now a control.
#
# HARNESS-075 puts `bash scripts/selftest-needed.sh` in front of the self-test
# in step 2 (it decides run or skip), adds `skip` to the step's words, a
# `Bash(bash scripts/selftest-needed.sh:*)` entry to both allowed-tools lines,
# and the call to complete-story's bullet before the self-test. Every earlier
# fixture that has a self-test step or bullet now carries the call, so its
# verdict - the exact lines it expects - is unchanged.
#
# HARNESS-095 moves the step's needle to `SELFTEST_JOBS=4 bash scripts/selftest.sh
# --changed` (HARNESS-094's selected run) and keeps the full run as an explicit
# option, `SELFTEST_JOBS=4 bash scripts/selftest.sh`, required in the same step
# with the three conditions under which it is taken. The full-run span is a
# PREFIX of the new one, so both needles carry their closing backtick: the
# full-run spelling does not name the `--changed` command, and the `--changed`
# span does not name the full run. The step must also say the `--changed`
# header line goes into `## Notes`, and both commands' allowed-tools carry the
# `--changed` pattern beside the full-run one. Earlier fixtures that wrote the
# old full-run step now write `{{SELFTEST}}`, which write_advance expands to a
# compliant `--changed` clause (full option, conditions and header included)
# and write_complete to the bare `--changed` span, so each keeps its verdict.
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
# HARNESS-072 (Contract "The needle": settled, read out). The step runs the
# self-test at SELFTEST_JOBS=4; the old spelling `bash scripts/selftest.sh` is
# not this token (it lacks `SELFTEST_JOBS=4 `), and is AC-1's and AC-2's
# control. TOOL_SELFTEST is a tool pattern, not the step's text: unchanged.
# HARNESS-095 (Contract "procedure.test.sh": settled, read out) moves it to the
# `--changed` span, closing backtick included, and adds the explicit full run
# (STEP_FULL), its three conditions (FULL_WHEN) and the tool patterns.
STEP_SELFTEST='`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`'
STEP_FULL='`SELFTEST_JOBS=4 bash scripts/selftest.sh`'
#
# R-1 (return to RED from GATES): condition (a)'s needle is the backticked
# code span `` `every suite` ``, backticks included. The bare words were
# satisfied by the step's closing sentence "CI runs every suite on the PR
# either way", which comes after the full-run span, so (a) could be deleted
# and the guard stayed silent. The fault line still prints `every suite`
# once-backticked, as before. AM-1 adds STEP_BACK, (c)'s route back to this
# step from REVIEW, read from the same region. It is not one of AC-2's "three
# conditions", so it is its own needle with its own line, not a FULL_WHEN entry.
FULL_WHEN=('`every suite`' 'cannot name the suite' 'had not selected')
STEP_BACK='`bash scripts/phase.sh set $1 GATES`'
TOOL_FULL='Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh:*)'
TOOL_CHANGED='Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh --changed:*)'
STEP_PHASE='`bash scripts/phase.sh set $1 REVIEW`'
STEP_BOUNDARIES='`bash scripts/check-boundaries.sh`'
# HARNESS-075 appends `skip`: the step says a `skip` is pasted into `## Notes`.
# HARNESS-095 (AC-1) appends the `--changed` header, which is pasted there too.
STEP_WORDS=('detached' 'Windows' '## Notes' 'other test runs' 'skip' 'selftest: --changed —')
# HARNESS-075 (Contract "procedure.test.sh": settled, read out). The step 2
# needle, which must come BEFORE STEP_SELFTEST in the same step, and the tool
# pattern both commands' allowed-tools must carry.
STEP_NEEDED='`bash scripts/selftest-needed.sh`'
TOOL_NEEDED='Bash(bash scripts/selftest-needed.sh:*)'

PARA_START='**GATES → REVIEW.**'
BULLET_START='- **GATES → REVIEW'

# HARNESS-068 (Contract C-2, C-3: settled, read out byte for byte).
SKILL=".claude/skills/diff-review/SKILL.md"
STEP_REVIEW='the `diff-review` skill'
BULLET_REVIEW='`diff-review`'
REVIEW_WORDS=('## Diff review' 'Must fix' 'bash scripts/gates.sh' 'Verdict: Ship.')
SKILL_NAME='name: diff-review'
SKILL_NEEDLES=(
  'callers of every changed function'
  'No case, no finding.'
  '**Must fix:**'
  '**Should fix:**'
  '**Nice to have:**'
  'Number findings across all groups'
  '**What this is:**'
  '**Problem:**'
  '**Fix:**'
  '**If we skip it:**'
  'Verdict: Ship.'
  'Verdict: fix '
  'bash scripts/gates.sh'
  '`bash scripts/phase.sh set <id> RED`'
  '## Regressions'
  '## Amendments'
  'changes no file'
)
PONYTAIL_NEEDLES=('One good test, not coverage' 'one small test')

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

# frontmatter_line <exact>   Succeeds when the loaded file's frontmatter (line
# 1 exactly `---` up to the next line exactly `---`) has a line EQUAL to
# <exact>. No frontmatter, or one never closed, has no such line.
frontmatter_line() {
  local i n="${#LN[@]}" end=-1
  [ "$n" -gt 0 ] && [ "${LN[0]}" = "---" ] || return 1
  for ((i = 1; i < n; i++)); do
    [ "${LN[$i]}" = "---" ] && { end=$i; break; }
  done
  [ "$end" -gt 0 ] || return 1
  for ((i = 1; i < end; i++)); do
    [ "${LN[$i]}" = "$1" ] && return 0
  done
  return 1
}

# joined   TXT := the loaded file's lines, newline-joined (no fork).
joined() { local IFS=$'\n'; TXT="${LN[*]}"; }

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
  # HARNESS-075: its own line, in the Contract's wording.
  has_entry "$TOOL_NEEDED" || printf '%s: allowed-tools lacks `%s`\n' "$f" "$TOOL_NEEDED"
  # HARNESS-095 (AC-3): the full-run pattern stays, the `--changed` one joins.
  for t in "$TOOL_FULL" "$TOOL_CHANGED"; do
    has_entry "$t" || printf '%s: allowed-tools lacks `%s`\n' "$f" "$t"
  done
  return 0
}

# squash <text>   Q := <text> with every run of whitespace, newlines included,
# made one space (no fork). HARNESS-095's condition needles are read through it,
# so a condition reflowed across a continuation line still counts.
squash() {
  Q="${1//$'\n'/ }"; Q="${Q//$'\t'/ }"
  while [ "${Q//  /}" != "$Q" ]; do Q="${Q//  / }"; done
}

# full_option <step-text> <file>   HARNESS-095 (AC-2): the self-test step names
# the full run STEP_FULL as an option, and the text from its FIRST occurrence
# on says each FULL_WHEN condition. Reading from the full-run span on, not the
# whole step, is what lets `every suite` fail: the `--changed` description
# before it says `every suite` too (when a path cannot be placed).
full_option() {
  local c n post
  case "$1" in
    *"$STEP_FULL"*) ;;
    *) printf '%s: its step 2 does not name the full run %s as an option\n' "$2" "$STEP_FULL"; return 0 ;;
  esac
  post="${1#*"$STEP_FULL"}"
  squash "$post"
  for c in "${FULL_WHEN[@]}"; do
    case "$Q" in
      *"$c"*) ;;
      *) n="${c#\`}"; n="${n%\`}"
         printf '%s: its full-run option does not say when: `%s`\n' "$2" "$n" ;;
    esac
  done
  # AM-1: case (c) is seen at REVIEW, so the option says how to get back.
  case "$Q" in
    *"$STEP_BACK"*) ;;
    *) printf '%s: its full-run option does not say how to get back: %s\n' "$2" "$STEP_BACK" ;;
  esac
  return 0
}

# needed_before <text> <file>   HARNESS-075: within one text, the FIRST
# STEP_NEEDED must come before the FIRST STEP_SELFTEST. Prints the "names ...
# after" line for <file> when it does not; the caller has already established
# that <text> contains both.
needed_before() {
  local pn ps
  pn="${1%%"$STEP_NEEDED"*}"; ps="${1%%"$STEP_SELFTEST"*}"
  [ "${#pn}" -lt "${#ps}" ] || printf '%s: names `bash scripts/selftest-needed.sh` after `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`\n' "$2"
  return 0
}

# procedure_problems <root>   One line `<relative-path>: <reason>` per
# violation (Contract C-4, byte for byte); silent when compliant. Always
# returns 0: the output is the verdict.
procedure_problems() {
  local root="$1" n ks kp kb kr w missing pr pt
  # advance-story: tools, step needles, order, words; then the review step.
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
          # HARNESS-095: the self-test's line is the Contract's "step 2" line.
          if [ "${n#*:}" = "$STEP_SELFTEST" ]; then
            printf '%s: its step 2 does not name %s\n' "$ADVANCE" "$STEP_SELFTEST"
          else
            printf '%s: its GATES → REVIEW steps do not name %s\n' "$ADVANCE" "${n#*:}"
          fi
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
            *) printf '%s: its `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` step does not say `%s`\n' "$ADVANCE" "$w" ;;
          esac
        done
        # HARNESS-075: the self-test step names selftest-needed.sh before the
        # self-test. Named only in a LATER step is "after"; in no step, or only
        # in an earlier one, is "does not name" (AC-4: "in the same step").
        case "${ST[$ks]}" in
          *"$STEP_NEEDED"*) needed_before "${ST[$ks]}" "$ADVANCE" ;;
          *)
            first_step "$STEP_NEEDED"
            if [ "$K" != "-1" ] && [ "${SN[$K]}" -gt "${SN[$ks]}" ]; then
              printf '%s: names `bash scripts/selftest-needed.sh` after `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`\n' "$ADVANCE"
            else
              printf '%s: its step 2 does not name `bash scripts/selftest-needed.sh`\n' "$ADVANCE"
            fi
            ;;
        esac
        # HARNESS-095 (AC-2): the full run, and when, in the same step.
        full_option "${ST[$ks]}" "$ADVANCE"
      fi
      # HARNESS-068: the review step, after every existing check (C-4 order).
      first_step "$STEP_REVIEW"; kr=$K
      if [ "$kr" = "-1" ]; then
        printf '%s: its GATES → REVIEW steps do not name %s\n' "$ADVANCE" "$STEP_REVIEW"
      else
        if [ "$ks" != "-1" ]; then
          [ "${SN[$kr]}" -lt "${SN[$ks]}" ] || printf '%s: its GATES → REVIEW steps are out of order: %s is step %s, %s is step %s\n' \
            "$ADVANCE" "$STEP_REVIEW" "${SN[$kr]}" "$STEP_SELFTEST" "${SN[$ks]}"
        fi
        for w in "${REVIEW_WORDS[@]}"; do
          case "${ST[$kr]}" in
            *"$w"*) ;;
            *) printf '%s: its `diff-review` step does not say `%s`\n' "$ADVANCE" "$w" ;;
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
        *) printf '%s: its GATES → REVIEW bullet does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`\n' "$COMPLETE" ;;
      esac
      # HARNESS-068: the review, named before the first self-test (C-2).
      case "$R" in
        *"$BULLET_REVIEW"*)
          case "$R" in
            *"$STEP_SELFTEST"*)
              pr="${R%%"$BULLET_REVIEW"*}"; pt="${R%%"$STEP_SELFTEST"*}"
              [ "${#pr}" -lt "${#pt}" ] || printf '%s: its GATES → REVIEW bullet names `diff-review` after `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`\n' "$COMPLETE"
              ;;
          esac
          ;;
        *) printf '%s: its GATES → REVIEW bullet does not name `diff-review`\n' "$COMPLETE" ;;
      esac
      # HARNESS-075: selftest-needed.sh, named before the first self-test.
      # Judged only when the bullet names the self-test at all: without it the
      # "does not name `SELFTEST_JOBS=4 ...`" line above already reports it.
      case "$R" in
        *"$STEP_SELFTEST"*)
          case "$R" in
            *"$STEP_NEEDED"*) needed_before "$R" "$COMPLETE" ;;
            *) printf '%s: its GATES → REVIEW bullet does not name `bash scripts/selftest-needed.sh`\n' "$COMPLETE" ;;
          esac
          ;;
      esac
    fi
  fi
  # the diff-review skill: missing, frontmatter, needles, ponytail needles.
  if [ ! -f "$root/$SKILL" ]; then
    printf '%s: file is missing\n' "$SKILL"
  else
    load "$root/$SKILL"
    frontmatter_line "$SKILL_NAME" || printf '%s: has no `%s` line in its frontmatter\n' "$SKILL" "$SKILL_NAME"
    joined
    for w in "${SKILL_NEEDLES[@]}"; do
      case "$TXT" in
        *"$w"*) ;;
        *) printf '%s: does not say `%s`\n' "$SKILL" "$w" ;;
      esac
    done
    for w in "${PONYTAIL_NEEDLES[@]}"; do
      case "$TXT" in
        *"$w"*) printf "%s: carries ponytail's \`%s\`\n" "$SKILL" "$w" ;;
      esac
    done
  fi
  return 0
}

# --- a compliant fixture, by construction -------------------------------------
# Never copied from the real tree, which in RED is not compliant. The wording
# is nobody's contract; GREEN writes the real files (Contract C-6).

# HARNESS-095 adds the full-run pattern (which the real files already carry)
# and the `--changed` pattern, as the last two entries.
GOOD_TOOLS='allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/gates.sh:*), Bash(bash scripts/check-boundaries.sh:*), Bash(bash scripts/selftest.sh:*), Bash(bash scripts/selftest-needed.sh:*), Bash(bash scripts/ci-local.sh:*), Bash(git:*), Read, Task, Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh:*), Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh --changed:*)'
# NEW_TOOLS   The two HARNESS-095 entries, appended to the hand-written
# allowed-tools lines of the earlier cases so each keeps its exact verdict.
NEW_TOOLS=", $TOOL_FULL, $TOOL_CHANGED"

# The review step (HARNESS-068), step 1. Its routing words sit on its
# continuation lines, so the compliant fixture proves continuation lines count
# for the review step too. It names neither the backticked self-test needle
# nor any of the self-test step's words or conditions, so it cannot satisfy
# them.
RV="$(cat <<'EOF'
1. Review the change with the `diff-review` skill: a fresh dispatch reads the
   diff and its callers, and its report goes into `## Diff review`. A Must fix
   finding is fixed, `bash scripts/gates.sh` runs again and these steps start
   over. Go on only once the report's last line is `Verdict: Ship.`.
EOF
)"

# with_review <steps>   RV, then <steps> (which number from 2).
with_review() { printf '%s\n%s' "$RV" "$1"; }

# The GATES -> REVIEW step list after the review. Step 2's words sit on its
# continuation lines, so the compliant fixture already proves continuation
# lines count. HARNESS-068 renumbered these from 1..5 to 2..6. HARNESS-072
# moved the needle to `SELFTEST_JOBS=4 bash scripts/selftest.sh` and added the
# fourth word, `other test runs`, on the last continuation line. HARNESS-075
# put `bash scripts/selftest-needed.sh` in front of the self-test and `skip`
# on a continuation line; `skip` appears nowhere else in the fixture.
# HARNESS-095 moved the run to the `--changed` span, added the header line and
# the full run with its three conditions, all inside step 2 with no blank line
# (a blank line ends a step). `every suite` appears twice on purpose: once in
# the `--changed` description BEFORE the full-run span, once as condition (a)
# after it; only the second may satisfy the condition. `cannot name the suite`
# is reflowed across a line break, so a condition read without squashing would
# miss it. R-1 adds the real step's closing sentence, "CI runs every suite on
# the PR either way", AFTER the full-run span and without backticks: it is the
# text that satisfied the bare needle when (a) was gone. AM-1 adds (c)'s route
# back, `bash scripts/phase.sh set $1 GATES`, after the full-run span too.
REST="$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh` — on `run` (a harness path changed),
   `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` — the suites the diff
   can break, every suite when a path cannot be placed, while the story is
   still at GATES; on skip, paste its line and go on. Run it detached; on a
   Windows host it is slow. Paste its last line and its header line
   `selftest: --changed — ...` into `## Notes`. When other test runs
   share the host it is slower, not wrong. The full
   `SELFTEST_JOBS=4 bash scripts/selftest.sh` runs instead when the header
   says `every suite`, when you cannot name
   the suite that exercises a changed script's caller, or when CI failed a
   suite the local run had not selected.
   That last is seen at REVIEW; `bash scripts/phase.sh set $1 GATES`
   brings you back here.
   CI runs every suite on the PR either way.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
5. `bash scripts/check-boundaries.sh` — the second script CI runs.
   Fix anything it reports.
6. Push and open the PR.
EOF
)"
GOOD_STEPS="$(with_review "$REST")"

GOOD_BULLET="$(cat <<'EOF'
- **GATES → REVIEW runs a `diff-review` of the change, then
  `bash scripts/selftest-needed.sh` decides whether
  `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`** runs, detached and alone, then sets
  the phase before committing.
EOF
)"

# CLAUSE   What `{{SELFTEST}}` becomes in a step written by write_advance: the
# `--changed` span, the header word and the full run with its three conditions,
# and none of the other STEP_WORDS, so a case that removes one of those still
# removes it. A bullet written by write_complete gets the bare span.
PH='{{SELFTEST}}'
CLAUSE="$STEP_SELFTEST (paste the header \`selftest: --changed — ...\`; the full $STEP_FULL instead when the header says \`every suite\`, when you cannot name the suite, or when CI failed a suite it had not selected, then \`bash scripts/phase.sh set \$1 GATES\` to come back)"

# The skill (HARNESS-068). Every C-3 needle appears exactly once, and no needle
# is a substring of another's occurrence, so removing one removes only it.
GOOD_SKILL="$(cat <<'EOF'
---
name: diff-review
description: Review a story's diff, and the code connected to it, before the PR opens.
---

# Diff review

Read the diff, then the callers of every changed function and what it calls.

Every finding needs a concrete case. No case, no finding.

Group findings as **Must fix:**, **Should fix:** and **Nice to have:**.
Number findings across all groups. Each finding has four parts:
**What this is:**, **Problem:**, **Fix:** and **If we skip it:**.

End with `Verdict: Ship.` or `Verdict: fix 1 and 2 first.`

A code finding is fixed in GATES, then `bash scripts/gates.sh` runs again. A
finding that needs a test is `bash scripts/phase.sh set <id> RED` with a
`## Regressions` entry. A wrong criterion is an `## Amendments` question.

The reviewer changes no file.
EOF
)"

# write_skill <dir> <content>
write_skill() {
  [ -d "$1/.claude/skills/diff-review" ] || mkdir -p "$1/.claude/skills/diff-review"
  printf '%s\n' "$2" > "$1/$SKILL"
}

# write_advance <dir> <tools-line> <steps> [<prose-after-steps>]
# `{{SELFTEST}}` in <steps> or <prose> becomes CLAUSE (HARNESS-095).
write_advance() {
  local s="${3//"$PH"/"$CLAUSE"}" p="${4:-}"
  p="${p//"$PH"/"$CLAUSE"}"
  [ -d "$1/.claude/commands" ] || mkdir -p "$1/.claude/commands"
  {
    printf -- '---\ndescription: Move one story forward\n%s\n---\n\nStory: $1\n\n' "$2"
    printf '%s Only when every required gate passes.\n\nThen, **in this order**:\n\n' "$PARA_START"
    printf '%s\n\n' "$s"
    [ -n "$p" ] && printf '%s\n\n' "$p"
    printf '**REVIEW → DONE.** Only once the PR is merged.\n'
  } > "$1/$ADVANCE"
}

# write_complete <dir> <tools-line> <bullet> [<tail>]
# `{{SELFTEST}}` in <bullet> or <tail> becomes the bare STEP_SELFTEST.
write_complete() {
  local b="${3//"$PH"/"$STEP_SELFTEST"}" t="${4:-}"
  t="${t//"$PH"/"$STEP_SELFTEST"}"
  [ -d "$1/.claude/commands" ] || mkdir -p "$1/.claude/commands"
  {
    printf -- '---\ndescription: Drive one story\n%s\n---\n\nStory: $1\n\n' "$2"
    printf -- '- **RED and GREEN each end with `bash scripts/gates.sh --fast`.**\n'
    printf '%s\n' "$b"
    printf -- '- **A return to RED ends with pasted red.**\n\n'
    [ -n "$t" ] && printf '%s\n' "$t"
    printf 'The end.\n'
  } > "$1/$COMPLETE"
}

compliant_fixture() { # <dir>
  write_advance "$1" "$GOOD_TOOLS" "$GOOD_STEPS"
  write_complete "$1" "$GOOD_TOOLS" "$GOOD_BULLET"
  write_skill "$1" "$GOOD_SKILL"
}

# fresh_case <name>   d := a new compliant fixture's path. Sets d rather than
# echoing it, and makes both directories with one mkdir, because on Windows
# each fork costs about a quarter of a second (HARNESS-068 measured it).
fresh_case() {
  d="$WORK/$1"
  [ -e "$d" ] && rm -rf "$d"
  mkdir -p "$d/.claude/commands" "$d/.claude/skills/diff-review"
  compliant_fixture "$d"
}

# Fault lines, as C-4 pins them.
A="$ADVANCE"; C="$COMPLETE"
no_tool()   { printf '%s: its allowed-tools do not permit `%s`' "$1" "$2"; }
no_step()   { printf '%s: its GATES → REVIEW steps do not name %s' "$ADVANCE" "$1"; }
disorder()  { printf '%s: its GATES → REVIEW steps are out of order: %s is step %s, %s is step %s' "$ADVANCE" "$1" "$2" "$3" "$4"; }
no_word()   { printf '%s: its `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` step does not say `%s`' "$ADVANCE" "$1"; }
NO_BULLET_NEEDLE="$C: its GATES → REVIEW bullet does not name \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\`"
# HARNESS-095: the self-test step's own "does not name" line (Contract).
NO_CHANGED_STEP="$A: its step 2 does not name \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\`"
# HARNESS-068 (C-4).
S="$SKILL"
no_rword()  { printf '%s: its `diff-review` step does not say `%s`' "$ADVANCE" "$1"; }
NO_BULLET_REVIEW="$C: its GATES → REVIEW bullet does not name \`diff-review\`"
BULLET_REVIEW_AFTER="$C: its GATES → REVIEW bullet names \`diff-review\` after \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\`"
no_say()    { printf '%s: does not say `%s`' "$SKILL" "$1"; }
ponytail()  { printf "%s: carries ponytail's \`%s\`" "$SKILL" "$1"; }
NO_NAME="$S: has no \`name: diff-review\` line in its frontmatter"

# ---------------------------------------------------------------------------
describe "the real tree (AC-1 to AC-4)"

missing=""
for f in "$ADVANCE" "$COMPLETE"; do [ -f "$REPO_ROOT/$f" ] || missing="$missing $f"; done
assert_eq "both commands that reach REVIEW exist in this repository" "" "$missing"

assert_eq "the diff-review skill exists in this repository (HARNESS-068 AC-4)" \
  "" "$([ -f "$REPO_ROOT/$SKILL" ] || printf '%s' "$SKILL")"

assert_eq "procedure_problems over the real tree prints nothing: both commands permit selftest.sh and ci-local.sh, the diff-review step comes before the full self-test, which comes before the phase change, complete-story names the review before the self-test, and the diff-review skill carries its rules; and (HARNESS-075 AC-4) both commands permit selftest-needed.sh, step 2 names it before the self-test and says \`skip\`, and complete-story's bullet names it before the self-test; and (HARNESS-095) step 2 and the bullet name the \`--changed\` run, step 2 names the full run with its three conditions, the backticked \`every suite\` (R-1) and its route back \`bash scripts/phase.sh set \$1 GATES\` (AM-1) and the header line, and both commands permit the \`--changed\` pattern beside the full-run one" \
  "" "$(procedure_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "the fixture: compliant by construction"

fresh_case compliant
assert_eq "the compliant fixture is silent" "" "$(procedure_problems "$d")"

fresh_case spaced-entries
write_advance "$d" 'allowed-tools:Bash(bash scripts/selftest.sh:*) ,   Bash(bash scripts/ci-local.sh:*)  ,Read,Bash(bash scripts/selftest-needed.sh:*)  '"$NEW_TOOLS" "$GOOD_STEPS"
assert_eq "entries are trimmed: extra spaces around a comma, and none after the colon, still permit" \
  "" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-1: both commands permit both scripts in allowed-tools"

fresh_case tool-missing
write_advance "$d" 'allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/ci-local.sh:*), Bash(bash scripts/selftest-needed.sh:*), Read'"$NEW_TOOLS" "$GOOD_STEPS"
assert_eq "advance-story without the selftest.sh entry gives one line naming the file and the entry" \
  "$(no_tool "$A" "$TOOL_SELFTEST")" "$(procedure_problems "$d")"

fresh_case tool-no-star
write_complete "$d" 'allowed-tools: Bash(bash scripts/selftest.sh:*), Bash(bash scripts/selftest-needed.sh:*), Bash(bash scripts/ci-local.sh), Read'"$NEW_TOOLS" "$GOOD_BULLET"
assert_eq "complete-story spelling the ci-local.sh entry without \`:*\` gives the same line" \
  "$(no_tool "$C" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

fresh_case tool-in-body
write_advance "$d" 'allowed-tools: Bash(bash scripts/selftest.sh:*), Bash(bash scripts/selftest-needed.sh:*), Read'"$NEW_TOOLS" "$GOOD_STEPS" \
  'It may also run Bash(bash scripts/ci-local.sh:*) once the commit exists.'
assert_eq "an entry that appears only in the body, not the allowed-tools line, gives the same line" \
  "$(no_tool "$A" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

fresh_case tool-in-other-frontmatter-key
write_complete "$d" 'allowed-tools: Bash(bash scripts/selftest.sh:*), Bash(bash scripts/selftest-needed.sh:*), Read'"$NEW_TOOLS"'
notes: Bash(bash scripts/ci-local.sh:*)' "$GOOD_BULLET"
assert_eq "an entry on another frontmatter key does not count" \
  "$(no_tool "$C" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

fresh_case tool-merged
write_advance "$d" 'allowed-tools: Bash(bash scripts/selftest.sh:*) Bash(bash scripts/ci-local.sh:*), Bash(bash scripts/selftest-needed.sh:*), Read'"$NEW_TOOLS" "$GOOD_STEPS"
assert_eq "an entry that only CONTAINS a needle is not equal to it: a missing comma loses both" \
  "$(no_tool "$A" "$TOOL_SELFTEST")
$(no_tool "$A" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

fresh_case tool-both-missing-both-files
write_advance "$d" 'allowed-tools: Read, Bash(bash scripts/selftest-needed.sh:*)'"$NEW_TOOLS" "$GOOD_STEPS"
write_complete "$d" 'allowed-tools: Read, Bash(bash scripts/selftest-needed.sh:*)'"$NEW_TOOLS" "$GOOD_BULLET"
assert_eq "both entries missing from both files gives four lines, advance-story first" \
  "$(no_tool "$A" "$TOOL_SELFTEST")
$(no_tool "$A" "$TOOL_CILOCAL")
$(no_tool "$C" "$TOOL_SELFTEST")
$(no_tool "$C" "$TOOL_CILOCAL")" "$(procedure_problems "$d")"

fresh_case no-allowed-tools
write_complete "$d" 'description2: nothing here' "$GOOD_BULLET"
assert_eq "a frontmatter with no allowed-tools line gives that line only, never the two \"do not permit\" lines" \
  "$C: has no \`allowed-tools:\` line in its frontmatter" "$(procedure_problems "$d")"

fresh_case no-frontmatter
{ printf '%s\n\n' "$GOOD_TOOLS"; printf '%s\n' "$GOOD_BULLET"; } > "$d/$COMPLETE"
assert_eq "an allowed-tools line with no frontmatter around it is not in a frontmatter" \
  "$C: has no \`allowed-tools:\` line in its frontmatter" "$(procedure_problems "$d")"

fresh_case allowed-tools-after-frontmatter
{ printf -- '---\ndescription: x\n---\n\n%s\n\n' "$GOOD_TOOLS"; printf '%s\n' "$GOOD_BULLET"; } > "$d/$COMPLETE"
assert_eq "an allowed-tools line after the frontmatter closes does not count" \
  "$C: has no \`allowed-tools:\` line in its frontmatter" "$(procedure_problems "$d")"

fresh_case advance-missing
rm -f "$d/$ADVANCE"
assert_eq "a missing command file gives only \`file is missing\`" \
  "$A: file is missing" "$(procedure_problems "$d")"

fresh_case complete-missing
rm -f "$d/$COMPLETE"
assert_eq "a missing complete-story gives only \`file is missing\`" \
  "$C: file is missing" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-2: the full self-test is a numbered step before the phase change, and check-boundaries after it"

fresh_case selftest-after-phase
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/phase.sh set $1 REVIEW`
3. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}}, detached, slow on Windows or beside other test runs; paste into `## Notes`.
4. Commit.
5. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "the self-test step after the phase step gives one out-of-order line" \
  "$(disorder "$STEP_SELFTEST" 3 "$STEP_PHASE" 2)" "$(procedure_problems "$d")"

fresh_case selftest-in-prose
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
Run {{SELFTEST}} first, detached, slow on Windows or beside other test runs; see `## Notes`.

2. `bash scripts/phase.sh set $1 REVIEW`
3. Commit.
4. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "the self-test named only in the paragraph's prose, in no numbered step, gives one \"do not name\" line" \
  "$NO_CHANGED_STEP" "$(procedure_problems "$d")"

fresh_case selftest-targeted
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `SELFTEST_JOBS=4 bash scripts/selftest.sh reporting` — detached, slow on Windows or beside other test runs; `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
5. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "a targeted \`SELFTEST_JOBS=4 bash scripts/selftest.sh reporting\` is not the full run: one \"do not name\" line" \
  "$NO_CHANGED_STEP" "$(procedure_problems "$d")"

fresh_case selftest-other-paragraph
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/phase.sh set $1 REVIEW`
3. Commit.
4. `bash scripts/check-boundaries.sh`

**REVIEW → DONE.** Before closing:

1. {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into `## Notes`.
EOF
)")"
assert_eq "the self-test step present only in the REVIEW → DONE paragraph gives one \"do not name\" line" \
  "$NO_CHANGED_STEP" "$(procedure_problems "$d")"

fresh_case boundaries-before-phase
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into `## Notes`.
3. `bash scripts/check-boundaries.sh`
4. `bash scripts/phase.sh set $1 REVIEW`
5. Commit.
EOF
)")"
assert_eq "the check-boundaries step moved before the phase step gives one out-of-order line" \
  "$(disorder "$STEP_PHASE" 4 "$STEP_BOUNDARIES" 3)" "$(procedure_problems "$d")"

fresh_case same-step
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}}, then `bash scripts/phase.sh set $1 REVIEW` —
   detached, slow on Windows or beside other test runs; paste into `## Notes`.
3. Commit.
4. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "two needles in the same step count as out of order" \
  "$(disorder "$STEP_SELFTEST" 2 "$STEP_PHASE" 2)" "$(procedure_problems "$d")"

fresh_case first-step-wins
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/phase.sh set $1 REVIEW`
3. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into `## Notes`.
4. `bash scripts/check-boundaries.sh`
5. If that failed, `bash scripts/phase.sh set $1 REVIEW` again.
EOF
)")"
assert_eq "a needle in more than one step is judged by its FIRST step" \
  "$(disorder "$STEP_SELFTEST" 3 "$STEP_PHASE" 2)" "$(procedure_problems "$d")"

fresh_case phase-missing
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into `## Notes`.
3. Commit.
4. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "the phase step missing gives its own \"do not name\" line, and the order check is suppressed" \
  "$(no_step "$STEP_PHASE")" "$(procedure_problems "$d")"

fresh_case boundaries-missing
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
EOF
)")"
assert_eq "the check-boundaries step missing gives its own \"do not name\" line" \
  "$(no_step "$STEP_BOUNDARIES")" "$(procedure_problems "$d")"

fresh_case continuation-counts
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. The whole harness self-test, every suite:
   `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit, then run
   `bash scripts/check-boundaries.sh`.
EOF
)")"
assert_eq "a needle on an indented continuation line is in that step" \
  "" "$(procedure_problems "$d")"

fresh_case indented-after-blank
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. The whole harness self-test, every suite.

   `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW`
4. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "an indented line after a blank line has left the step: the needle is in no step" \
  "$NO_CHANGED_STEP" "$(procedure_problems "$d")"

fresh_case star-line-ends-region
write_advance "$d" "$GOOD_TOOLS" "**Note.** The steps follow.

$GOOD_STEPS"
assert_eq "a line beginning \`**\` inside the paragraph ends it early, so the steps after it are not read" \
  "$NO_CHANGED_STEP
$(no_step "$STEP_PHASE")
$(no_step "$STEP_BOUNDARIES")
$(no_step "$STEP_REVIEW")" "$(procedure_problems "$d")"

fresh_case no-paragraph
{ printf -- '---\n%s\n---\n\n' "$GOOD_TOOLS"; printf '**GATES -> REVIEW.** ascii arrow.\n\n%s\n' "$GOOD_STEPS"; } > "$d/$ADVANCE"
assert_eq "advance-story with no \`**GATES → REVIEW.**\` paragraph gives that line only" \
  "$A: has no \`**GATES → REVIEW.**\` paragraph" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3: the self-test step says detached, Windows and ## Notes"

for w in 'detached' 'Windows' '## Notes'; do
  fresh_case "word-$w"
  steps="${GOOD_STEPS//"$w"/elsewhere}"
  write_advance "$d" "$GOOD_TOOLS" "$steps" "Prose outside the steps says $w."
  assert_eq "\`$w\` missing from the self-test step but present elsewhere in the file gives one line naming it" \
    "$(no_word "$w")" "$(procedure_problems "$d")"
done

fresh_case words-in-next-step
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}}, slower beside other test runs.
3. `bash scripts/phase.sh set $1 REVIEW` — detached, slow on Windows; `## Notes`.
4. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "the three words in a DIFFERENT step do not satisfy the self-test step" \
  "$(no_word detached)
$(no_word Windows)
$(no_word '## Notes')" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-4: complete-story's GATES → REVIEW bullet names the full self-test"

fresh_case bullet-without
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a `diff-review`, sets the phase before committing**, then pushes.' \
  'Elsewhere: run {{SELFTEST}} at some point.'
assert_eq "the needle present elsewhere in the file but not in that bullet gives one line" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

fresh_case bullet-targeted
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a `diff-review`, then `SELFTEST_JOBS=4 bash scripts/selftest.sh procedure`.**'
assert_eq "a targeted run in the bullet is not the full self-test" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

fresh_case bullet-after-blank
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a `diff-review`, sets the phase before committing.**

  Then {{SELFTEST}}.'
assert_eq "the bullet ends at a blank line: the needle after it is not in the bullet" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

fresh_case bullet-next-bullet
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a `diff-review`, sets the phase before committing.**
- Then {{SELFTEST}}.'
assert_eq "the bullet ends at the next \`- \` line: the needle in the next bullet is not in it" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

fresh_case no-bullet
write_complete "$d" "$GOOD_TOOLS" '- **REVIEW → DONE** merges.'
assert_eq "complete-story with no \`- **GATES → REVIEW\` bullet gives that line only" \
  "$C: has no \`- **GATES → REVIEW\` bullet" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-068 AC-1: the diff review is a numbered GATES → REVIEW step, before the self-test"

fresh_case review-after-selftest
write_advance "$d" "$GOOD_TOOLS" "$(cat <<EOF
1. \`bash scripts/selftest-needed.sh\`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into \`## Notes\`.
2. ${RV#1. }
3. \`bash scripts/phase.sh set \$1 REVIEW\`
4. Commit.
5. \`bash scripts/check-boundaries.sh\`
EOF
)"
assert_eq "the review step after the self-test step gives one out-of-order line naming both step numbers" \
  "$(disorder "$STEP_REVIEW" 2 "$STEP_SELFTEST" 1)" "$(procedure_problems "$d")"

fresh_case review-in-prose
write_advance "$d" "$GOOD_TOOLS" "Run the \`diff-review\` skill first: its report goes into \`## Diff review\`; a Must fix finding means \`bash scripts/gates.sh\` again; go on at \`Verdict: Ship.\`.

$REST"
assert_eq "the review named only in the paragraph's prose, in no numbered step, gives one \"do not name\" line" \
  "$(no_step "$STEP_REVIEW")" "$(procedure_problems "$d")"

fresh_case review-missing
write_advance "$d" "$GOOD_TOOLS" "$REST"
assert_eq "no review step at all gives one \"do not name\" line, and the review's order and word checks are suppressed" \
  "$(no_step "$STEP_REVIEW")" "$(procedure_problems "$d")"

fresh_case review-other-paragraph
write_advance "$d" "$GOOD_TOOLS" "$REST

**REVIEW → DONE.** Before closing:

$RV"
assert_eq "the review step present only in the REVIEW → DONE paragraph gives one \"do not name\" line" \
  "$(no_step "$STEP_REVIEW")" "$(procedure_problems "$d")"

fresh_case review-unquoted
steps="${GOOD_STEPS//"$STEP_REVIEW"/the diff-review skill}"
write_advance "$d" "$GOOD_TOOLS" "$steps"
assert_eq "a step naming the diff-review skill without the backticked needle does not name it" \
  "$(no_step "$STEP_REVIEW")" "$(procedure_problems "$d")"

fresh_case review-same-step-as-selftest
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. Run the `diff-review` skill, then `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached,
   slow on Windows or beside other test runs; `## Notes`. Report into `## Diff review`; a Must fix
   means `bash scripts/gates.sh` again; go on at `Verdict: Ship.`.
2. `bash scripts/phase.sh set $1 REVIEW`
3. Commit.
4. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "the review and the self-test in the same step count as out of order" \
  "$(disorder "$STEP_REVIEW" 1 "$STEP_SELFTEST" 1)" "$(procedure_problems "$d")"

fresh_case review-without-selftest
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/phase.sh set $1 REVIEW`
3. Commit.
4. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "with no self-test step the review's order check is suppressed: only the self-test's \"do not name\" line" \
  "$NO_CHANGED_STEP" "$(procedure_problems "$d")"

fresh_case review-lines-after-existing
write_advance "$d" "$GOOD_TOOLS" "${REST//detached/elsewhere}"
assert_eq "the existing checks print before the review line: the self-test word line, then the review's \"do not name\" line" \
  "$(no_word detached)
$(no_step "$STEP_REVIEW")" "$(procedure_problems "$d")"

fresh_case review-order-before-words
write_advance "$d" "$GOOD_TOOLS" "$(cat <<EOF
1. \`bash scripts/selftest-needed.sh\`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; paste into \`## Notes\`.
2. ${RV#1. }
3. \`bash scripts/phase.sh set \$1 REVIEW\`
4. Commit.
5. \`bash scripts/check-boundaries.sh\`
EOF
)"
steps="$(cat "$d/$ADVANCE")"
printf '%s\n' "${steps//Must fix/elsewhere}" > "$d/$ADVANCE"
assert_eq "the review's out-of-order line prints before its routing-word lines" \
  "$(disorder "$STEP_REVIEW" 2 "$STEP_SELFTEST" 1)
$(no_rword 'Must fix')" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-068 AC-2: the review step says how a finding routes"

for w in "${REVIEW_WORDS[@]}"; do
  fresh_case "rword-${w//[^a-zA-Z]/_}"
  steps="${GOOD_STEPS//"$w"/elsewhere}"
  write_advance "$d" "$GOOD_TOOLS" "$steps" "Prose outside the steps says $w."
  assert_eq "\`$w\` missing from the review step but present elsewhere in the file gives one line naming it" \
    "$(no_rword "$w")" "$(procedure_problems "$d")"
done

fresh_case rword-verdict-negated
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//Verdict: Ship./Verdict: fix 1 first.}"
assert_eq "the negated verdict \`Verdict: fix 1 first.\` does not satisfy \`Verdict: Ship.\`" \
  "$(no_rword 'Verdict: Ship.')" "$(procedure_problems "$d")"

fresh_case rword-verdict-no-stop
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//Verdict: Ship./Verdict: Ship}"
assert_eq "\`Verdict: Ship\` without its full stop does not satisfy the needle" \
  "$(no_rword 'Verdict: Ship.')" "$(procedure_problems "$d")"

fresh_case rwords-in-next-step
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. Review the change with the `diff-review` skill.
2. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow on Windows or beside other test runs; `## Notes`. Paste
   the review into `## Diff review`; a Must fix means `bash scripts/gates.sh`
   again; go on at `Verdict: Ship.`.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
5. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "the four routing words in a DIFFERENT step do not satisfy the review step" \
  "$(no_rword '## Diff review')
$(no_rword 'Must fix')
$(no_rword 'bash scripts/gates.sh')
$(no_rword 'Verdict: Ship.')" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-068 AC-3: complete-story's bullet names the review before the self-test"

fresh_case bullet-no-review
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest-needed.sh`, the full {{SELFTEST}}**, then sets the phase.'
assert_eq "a bullet naming the self-test but not \`diff-review\` gives one \"does not name\" line" \
  "$NO_BULLET_REVIEW" "$(procedure_problems "$d")"

fresh_case bullet-review-after
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest-needed.sh`, the full {{SELFTEST}}**, then a `diff-review`.'
assert_eq "a bullet naming \`diff-review\` only after the self-test gives one \"names … after\" line" \
  "$BULLET_REVIEW_AFTER" "$(procedure_problems "$d")"

fresh_case bullet-review-after-next-line
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest-needed.sh`, the full {{SELFTEST}}**, then
  a `diff-review` on a continuation line.'
assert_eq "\`diff-review\` on a later line of the bullet, after the self-test, is still after it" \
  "$BULLET_REVIEW_AFTER" "$(procedure_problems "$d")"

fresh_case bullet-review-elsewhere
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest-needed.sh`, the full {{SELFTEST}}**, then sets the phase.' \
  'Elsewhere: run a `diff-review` at some point.'
assert_eq "\`diff-review\` present elsewhere in the file but not in that bullet gives one \"does not name\" line" \
  "$NO_BULLET_REVIEW" "$(procedure_problems "$d")"

fresh_case bullet-review-next-bullet
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest-needed.sh`, the full {{SELFTEST}}**, then sets the phase.
- Then a `diff-review`.'
assert_eq "\`diff-review\` in the next bullet is not in the GATES → REVIEW bullet" \
  "$NO_BULLET_REVIEW" "$(procedure_problems "$d")"

fresh_case bullet-review-unquoted
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a diff-review, then `bash scripts/selftest-needed.sh` and the full {{SELFTEST}}**.'
assert_eq "diff-review without its backticks is not the needle" \
  "$NO_BULLET_REVIEW" "$(procedure_problems "$d")"

fresh_case bullet-first-review-wins
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a `diff-review`, then `bash scripts/selftest-needed.sh` and the full {{SELFTEST}}**, and a second `diff-review` of any fix.'
assert_eq "the FIRST \`diff-review\` is judged: before the self-test, a later mention does not matter" \
  "" "$(procedure_problems "$d")"

fresh_case bullet-first-selftest-wins
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest-needed.sh`, the full {{SELFTEST}}**, a `diff-review`, then {{SELFTEST}} again.'
assert_eq "the FIRST self-test is judged: a \`diff-review\` before only its second mention is still after" \
  "$BULLET_REVIEW_AFTER" "$(procedure_problems "$d")"

fresh_case bullet-neither
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW sets the phase before committing.**'
assert_eq "a bullet naming neither gives the self-test line, then the review line" \
  "$NO_BULLET_NEEDLE
$NO_BULLET_REVIEW" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-068 AC-4: the diff-review skill carries the review's rules"

fresh_case skill-missing
rm -f "$d/$SKILL"
assert_eq "a missing skill file gives only \`file is missing\`" \
  "$S: file is missing" "$(procedure_problems "$d")"

for w in "${SKILL_NEEDLES[@]}"; do
  fresh_case "skill-needle-${w//[^a-zA-Z]/_}"
  write_skill "$d" "${GOOD_SKILL//"$w"/elsewhere}"
  assert_eq "the skill without \`$w\` gives one \"does not say\" line naming it" \
    "$(no_say "$w")" "$(procedure_problems "$d")"
done

for w in "${PONYTAIL_NEEDLES[@]}"; do
  fresh_case "skill-ponytail-${w//[^a-zA-Z]/_}"
  write_skill "$d" "$GOOD_SKILL

$w is enough."
  assert_eq "the skill carrying \`$w\` gives one \"carries ponytail's\" line" \
    "$(ponytail "$w")" "$(procedure_problems "$d")"
done

fresh_case skill-no-name
write_skill "$d" "${GOOD_SKILL//"$SKILL_NAME"/title: diff-review}"
assert_eq "a frontmatter with no \`name: diff-review\` line gives that line only" \
  "$NO_NAME" "$(procedure_problems "$d")"

fresh_case skill-name-in-body
write_skill "$d" "${GOOD_SKILL//"$SKILL_NAME"/title: diff-review}

$SKILL_NAME"
assert_eq "\`name: diff-review\` in the body, not the frontmatter, does not count" \
  "$NO_NAME" "$(procedure_problems "$d")"

fresh_case skill-name-longer
write_skill "$d" "${GOOD_SKILL//"$SKILL_NAME"/name: diff-review-v2}"
assert_eq "a frontmatter line that only CONTAINS \`name: diff-review\` is not equal to it" \
  "$NO_NAME" "$(procedure_problems "$d")"

fresh_case skill-no-frontmatter
write_skill "$d" "${GOOD_SKILL//---/}"
assert_eq "a \`name: diff-review\` line with no frontmatter around it is not in a frontmatter" \
  "$NO_NAME" "$(procedure_problems "$d")"

fresh_case skill-crlf
write_skill "$d" "${GOOD_SKILL//$'\n'/$'\r\n'}"
assert_eq "a CRLF skill file reads the same as an LF one" \
  "" "$(procedure_problems "$d")"

fresh_case skill-order
s="${GOOD_SKILL//"$SKILL_NAME"/title: diff-review}"
s="${s//No case, no finding./elsewhere}"
write_skill "$d" "$s

one small test will do."
assert_eq "the skill's lines print in C-4 order: frontmatter, then needles, then ponytail needles" \
  "$NO_NAME
$(no_say 'No case, no finding.')
$(ponytail 'one small test')" "$(procedure_problems "$d")"

fresh_case all-three-files
rm -f "$d/$SKILL"
write_advance "$d" "$GOOD_TOOLS" "$REST"
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest-needed.sh`, the full {{SELFTEST}}**, then sets the phase.'
assert_eq "the three files are judged in order: advance-story, complete-story, then the skill" \
  "$(no_step "$STEP_REVIEW")
$NO_BULLET_REVIEW
$S: file is missing" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
# HARNESS-072: the step runs the self-test at SELFTEST_JOBS=4. The expected
# lines in this block are the ACs' own text, written out literally rather than
# built from the helpers above, so a helper that drifted from the AC is caught.
OLD_SELFTEST='`bash scripts/selftest.sh`'

describe "HARNESS-072 AC-1: advance-story's step names \`SELFTEST_JOBS=4 bash scripts/selftest.sh\`"

fresh_case old-spelling-step
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_SELFTEST"/$OLD_SELFTEST}"
assert_eq "a step reading the old spelling \`bash scripts/selftest.sh\`, everything else compliant, gives exactly the AC-1 line" \
  '.claude/commands/advance-story.md: its step 2 does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(procedure_problems "$d")"

fresh_case other-value-step
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//SELFTEST_JOBS=4/SELFTEST_JOBS=1}"
assert_eq "a step running \`SELFTEST_JOBS=1 bash scripts/selftest.sh\` does not name the token: the value is part of it" \
  '.claude/commands/advance-story.md: its step 2 does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(procedure_problems "$d")"

fresh_case tool-pattern-unchanged
write_advance "$d" "${GOOD_TOOLS//"$TOOL_SELFTEST"/Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh:*)}" "$GOOD_STEPS"
assert_eq "the allowed-tools entry is still \`Bash(bash scripts/selftest.sh:*)\`: an entry carrying the variable does not permit it" \
  "$(no_tool "$A" 'Bash(bash scripts/selftest.sh:*)')" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-072 AC-2: complete-story's bullet names the same token, after \`diff-review\`"

fresh_case old-spelling-bullet
write_complete "$d" "$GOOD_TOOLS" "${GOOD_BULLET//"$STEP_SELFTEST"/$OLD_SELFTEST}"
assert_eq "a bullet reading \`the full \`bash scripts/selftest.sh\`\` (old spelling) gives exactly the AC-2 line" \
  '.claude/commands/complete-story.md: its GATES → REVIEW bullet does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(procedure_problems "$d")"

fresh_case other-value-bullet
write_complete "$d" "$GOOD_TOOLS" "${GOOD_BULLET//SELFTEST_JOBS=4/SELFTEST_JOBS=1}"
assert_eq "a bullet running \`SELFTEST_JOBS=1 bash scripts/selftest.sh\` does not name the token" \
  '.claude/commands/complete-story.md: its GATES → REVIEW bullet does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-072 AC-3: the self-test step says \`other test runs\`"

fresh_case word-other-test-runs
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//other test runs/elsewhere}" \
  "Prose outside the steps says other test runs."
assert_eq "\`other test runs\` missing from the self-test step but present elsewhere in the file gives exactly the AC-3 line" \
  '.claude/commands/advance-story.md: its `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` step does not say `other test runs`' \
  "$(procedure_problems "$d")"

fresh_case other-test-runs-in-next-step
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow on Windows; `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW` — slower while other test runs share the host.
4. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "\`other test runs\` in a DIFFERENT step does not satisfy the self-test step" \
  '.claude/commands/advance-story.md: its `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` step does not say `other test runs`' \
  "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-072 AC-4: a single suite under the new spelling is not the full run"

fresh_case targeted-new-spelling
targeted='`SELFTEST_JOBS=4 bash scripts/selftest.sh reporting`'
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_SELFTEST"/$targeted}"
assert_eq "a step naming \`SELFTEST_JOBS=4 bash scripts/selftest.sh reporting\`, everything else compliant, gives exactly one \"do not name\" line" \
  '.claude/commands/advance-story.md: its step 2 does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
# HARNESS-075: `bash scripts/selftest-needed.sh` decides whether step 2 runs the
# self-test. As in the HARNESS-072 block, every expected line is the
# Contract's own text written out literally, not built from a helper.
NEEDED_NO_STEP='.claude/commands/advance-story.md: its step 2 does not name `bash scripts/selftest-needed.sh`'
NEEDED_AFTER_A='.claude/commands/advance-story.md: names `bash scripts/selftest-needed.sh` after `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`'
NEEDED_AFTER_C='.claude/commands/complete-story.md: names `bash scripts/selftest-needed.sh` after `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`'
NEEDED_NO_BULLET='.claude/commands/complete-story.md: its GATES → REVIEW bullet does not name `bash scripts/selftest-needed.sh`'
LACKS_A='.claude/commands/advance-story.md: allowed-tools lacks `Bash(bash scripts/selftest-needed.sh:*)`'
LACKS_C='.claude/commands/complete-story.md: allowed-tools lacks `Bash(bash scripts/selftest-needed.sh:*)`'
NO_SKIP='.claude/commands/advance-story.md: its `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` step does not say `skip`'

describe "HARNESS-075 AC-4: step 2 names \`bash scripts/selftest-needed.sh\` before the self-test"

fresh_case needed-missing
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_NEEDED"/the check}"
assert_eq "control: a step 2 that runs the self-test with no selftest-needed call, everything else compliant, gives exactly one \"does not name\" line" \
  "$NEEDED_NO_STEP" "$(procedure_problems "$d")"

fresh_case needed-later-step
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. {{SELFTEST}} — detached, slow on Windows or beside other test runs; on skip, paste into `## Notes`.
3. `bash scripts/selftest-needed.sh`, to see whether that was needed.
4. `bash scripts/phase.sh set $1 REVIEW`
5. Commit.
6. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "control: selftest-needed.sh named in a LATER step than the self-test gives exactly one \"names … after\" line" \
  "$NEEDED_AFTER_A" "$(procedure_problems "$d")"

fresh_case needed-after-same-step
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. {{SELFTEST}} — detached, slow on Windows or beside other test runs; then
   `bash scripts/selftest-needed.sh`; on skip, paste into `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
5. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "selftest-needed.sh after the self-test within the same step (on a continuation line) gives exactly one \"names … after\" line" \
  "$NEEDED_AFTER_A" "$(procedure_problems "$d")"

fresh_case needed-earlier-step
write_advance "$d" "$GOOD_TOOLS" "$(cat <<'EOF'
1. Review the change with the `diff-review` skill, then run `bash scripts/selftest-needed.sh`: a fresh dispatch reads the
   diff and its callers, and its report goes into `## Diff review`. A Must fix
   finding is fixed, `bash scripts/gates.sh` runs again and these steps start
   over. Go on only once the report's last line is `Verdict: Ship.`.
2. {{SELFTEST}} — detached, slow on Windows or beside other test runs; on skip, paste into `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
5. `bash scripts/check-boundaries.sh`
EOF
)"
assert_eq "selftest-needed.sh named only in an EARLIER step is not in the self-test's step: one \"does not name\" line" \
  "$NEEDED_NO_STEP" "$(procedure_problems "$d")"

fresh_case needed-in-prose
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_NEEDED"/the check}" \
  "Prose outside the steps says to run $STEP_NEEDED first."
assert_eq "selftest-needed.sh named only in prose after the steps gives one \"does not name\" line" \
  "$NEEDED_NO_STEP" "$(procedure_problems "$d")"

fresh_case needed-unquoted
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_NEEDED"/bash scripts/selftest-needed.sh}"
assert_eq "selftest-needed.sh without its backticks is not the needle: one \"does not name\" line" \
  "$NEEDED_NO_STEP" "$(procedure_problems "$d")"

fresh_case needed-other-script
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_NEEDED"/\`bash scripts/selftest-needed.sh origin/main\`}"
assert_eq "\`bash scripts/selftest-needed.sh origin/main\` is not the bare call the needle names: one \"does not name\" line" \
  "$NEEDED_NO_STEP" "$(procedure_problems "$d")"

fresh_case needed-first-wins
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; unless it says skip, {{SELFTEST}} — detached, slow
   on Windows or beside other test runs; paste into `## Notes`. Then `bash scripts/selftest-needed.sh` again.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
5. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "the FIRST selftest-needed.sh in the step is judged: before the self-test, a later mention does not matter" \
  "" "$(procedure_problems "$d")"

describe "HARNESS-075 AC-4: step 2 says \`skip\` is pasted into \`## Notes\`"

fresh_case word-skip
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//skip/elsewhere}" "Prose outside the steps says skip."
assert_eq "\`skip\` missing from the self-test step but present elsewhere in the file gives exactly one \"does not say\" line" \
  "$NO_SKIP" "$(procedure_problems "$d")"

fresh_case skip-in-next-step
write_advance "$d" "$GOOD_TOOLS" "$(with_review "$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`, then {{SELFTEST}} — detached, slow on Windows or beside other test runs; `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW` — after a skip too.
4. `bash scripts/check-boundaries.sh`
EOF
)")"
assert_eq "\`skip\` in a DIFFERENT step does not satisfy the self-test step" \
  "$NO_SKIP" "$(procedure_problems "$d")"

describe "HARNESS-075 AC-4: both commands' allowed-tools carry \`Bash(bash scripts/selftest-needed.sh:*)\`"

fresh_case needed-tool-advance
write_advance "$d" "${GOOD_TOOLS//", $TOOL_NEEDED"/}" "$GOOD_STEPS"
assert_eq "control: advance-story's allowed-tools without the entry gives exactly one line naming the file and the entry" \
  "$LACKS_A" "$(procedure_problems "$d")"

fresh_case needed-tool-complete
write_complete "$d" "${GOOD_TOOLS//", $TOOL_NEEDED"/}" "$GOOD_BULLET"
assert_eq "control: complete-story's allowed-tools without the entry gives exactly one line naming the file and the entry" \
  "$LACKS_C" "$(procedure_problems "$d")"

fresh_case needed-tool-no-star
write_advance "$d" "${GOOD_TOOLS//"$TOOL_NEEDED"/Bash(bash scripts/selftest-needed.sh)}" "$GOOD_STEPS"
assert_eq "the entry spelled without \`:*\` does not count" \
  "$LACKS_A" "$(procedure_problems "$d")"

fresh_case needed-tool-in-body
write_complete "$d" "${GOOD_TOOLS//", $TOOL_NEEDED"/}" "$GOOD_BULLET" \
  "It may also run $TOOL_NEEDED."
assert_eq "the entry only in the body, not the allowed-tools line, does not count" \
  "$LACKS_C" "$(procedure_problems "$d")"

fresh_case needed-tool-lines-after-existing
write_advance "$d" 'allowed-tools: Read'"$NEW_TOOLS" "$GOOD_STEPS"
assert_eq "the lacks line prints after the two existing \"do not permit\" lines" \
  "$(no_tool "$A" "$TOOL_SELFTEST")
$(no_tool "$A" "$TOOL_CILOCAL")
$LACKS_A" "$(procedure_problems "$d")"

describe "HARNESS-075 AC-4: complete-story's bullet names \`bash scripts/selftest-needed.sh\` before the full self-test"

fresh_case needed-bullet-missing
write_complete "$d" "$GOOD_TOOLS" "${GOOD_BULLET//"$STEP_NEEDED"/a check}"
assert_eq "a bullet naming the self-test but not selftest-needed.sh gives exactly one \"does not name\" line" \
  "$NEEDED_NO_BULLET" "$(procedure_problems "$d")"

fresh_case needed-bullet-after
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a `diff-review`, the full {{SELFTEST}}**, then
  `bash scripts/selftest-needed.sh` to see whether it was needed.'
assert_eq "a bullet naming selftest-needed.sh only after the self-test gives exactly one \"names … after\" line" \
  "$NEEDED_AFTER_C" "$(procedure_problems "$d")"

fresh_case needed-bullet-elsewhere
write_complete "$d" "$GOOD_TOOLS" "${GOOD_BULLET//"$STEP_NEEDED"/a check}" \
  "Elsewhere: run $STEP_NEEDED at some point."
assert_eq "selftest-needed.sh present elsewhere in the file but not in that bullet gives one \"does not name\" line" \
  "$NEEDED_NO_BULLET" "$(procedure_problems "$d")"

fresh_case needed-bullet-no-selftest
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a `diff-review`, sets the phase before committing.**'
assert_eq "a bullet with no self-test at all gives only the existing self-test line: the selftest-needed check is about the self-test clause" \
  "$NO_BULLET_NEEDLE" "$(procedure_problems "$d")"

describe "HARNESS-075 AC-4: the lines a tree WITHOUT this story's edits prints, in order"

fresh_case needed-all-absent
write_advance "$d" "${GOOD_TOOLS//", $TOOL_NEEDED"/}" "$(s="${GOOD_STEPS//"$STEP_NEEDED"/the check}"; printf '%s' "${s//skip/elsewhere}")"
write_complete "$d" "${GOOD_TOOLS//", $TOOL_NEEDED"/}" "${GOOD_BULLET//"$STEP_NEEDED"/a check}"
assert_eq "no entry, no call, no \`skip\` in either command gives five lines: advance-story's lacks, skip and step-2 lines, then complete-story's lacks and bullet lines" \
  "$LACKS_A
$NO_SKIP
$NEEDED_NO_STEP
$LACKS_C
$NEEDED_NO_BULLET" "$(procedure_problems "$d")"

# ---------------------------------------------------------------------------
# HARNESS-095: step 2 runs `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`
# and keeps the full run as an option with three conditions. As in the
# HARNESS-072 and -075 blocks, every expected line is the Contract's own text
# written out literally, not built from a helper.
CH_NO_STEP='.claude/commands/advance-story.md: its step 2 does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`'
CH_NO_BULLET='.claude/commands/complete-story.md: its GATES → REVIEW bullet does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`'
CH_NO_FULL='.claude/commands/advance-story.md: its step 2 does not name the full run `SELFTEST_JOBS=4 bash scripts/selftest.sh` as an option'
CH_WHEN_A='.claude/commands/advance-story.md: its full-run option does not say when: `every suite`'
CH_WHEN_B='.claude/commands/advance-story.md: its full-run option does not say when: `cannot name the suite`'
CH_WHEN_C='.claude/commands/advance-story.md: its full-run option does not say when: `had not selected`'
CH_NO_HEADER='.claude/commands/advance-story.md: its `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` step does not say `selftest: --changed —`'
CH_LACKS_A='.claude/commands/advance-story.md: allowed-tools lacks `Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh --changed:*)`'
CH_LACKS_C='.claude/commands/complete-story.md: allowed-tools lacks `Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh --changed:*)`'
FULL_LACKS_A='.claude/commands/advance-story.md: allowed-tools lacks `Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh:*)`'
FULL_LACKS_C='.claude/commands/complete-story.md: allowed-tools lacks `Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh:*)`'

describe "HARNESS-095 AC-4: the full-run spelling does not name the \`--changed\` command"

fresh_case changed-regressed-step
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_SELFTEST"/$STEP_FULL}"
assert_eq "control: the compliant step with its run regressed to the full-run spelling (\`--changed\` absent), everything else compliant, gives exactly one line naming the file and the \`--changed\` command" \
  "$CH_NO_STEP" "$(procedure_problems "$d")"

fresh_case changed-regressed-bullet
write_complete "$d" "$GOOD_TOOLS" "${GOOD_BULLET//"$STEP_SELFTEST"/$STEP_FULL}"
assert_eq "control: the compliant bullet with its run regressed to the full-run spelling gives exactly one line naming the file and the \`--changed\` command" \
  "$CH_NO_BULLET" "$(procedure_problems "$d")"

fresh_case changed-unclosed
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_SELFTEST"/\`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed origin/main\`}"
assert_eq "\`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed origin/main\` is not the span: the needle ends at its closing backtick" \
  "$CH_NO_STEP" "$(procedure_problems "$d")"

fresh_case changed-only-in-attest
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_SELFTEST"/\`bash scripts/attest.sh -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\`}"
assert_eq "the \`--changed\` command only inside an \`attest.sh --\` span is not the step naming it: the needle begins at its opening backtick" \
  "$CH_NO_STEP" "$(procedure_problems "$d")"

fresh_case changed-in-prose
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_SELFTEST"/$STEP_FULL}" "Prose outside the steps runs $STEP_SELFTEST."
assert_eq "the \`--changed\` command only in prose after the steps gives the one \"does not name\" line" \
  "$CH_NO_STEP" "$(procedure_problems "$d")"

fresh_case changed-in-later-step
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_SELFTEST"/$STEP_FULL}
7. Afterwards, $STEP_SELFTEST."
assert_eq "the \`--changed\` command only in a step after the phase change is out of order, not missing; selftest-needed.sh (named only in an earlier step), the words and the full run are judged against THAT step" \
  ".claude/commands/advance-story.md: its GATES → REVIEW steps are out of order: \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` is step 7, \`bash scripts/phase.sh set \$1 REVIEW\` is step 3
.claude/commands/advance-story.md: its \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` step does not say \`detached\`
.claude/commands/advance-story.md: its \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` step does not say \`Windows\`
.claude/commands/advance-story.md: its \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` step does not say \`## Notes\`
.claude/commands/advance-story.md: its \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` step does not say \`other test runs\`
.claude/commands/advance-story.md: its \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` step does not say \`skip\`
.claude/commands/advance-story.md: its \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` step does not say \`selftest: --changed —\`
.claude/commands/advance-story.md: its step 2 does not name \`bash scripts/selftest-needed.sh\`
$CH_NO_FULL" "$(procedure_problems "$d")"

describe "HARNESS-095 AC-1: step 2 says the \`--changed\` header goes into \`## Notes\`"

fresh_case changed-no-header
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//selftest: --changed —/the header}" "Prose outside the steps says selftest: --changed — ..."
assert_eq "control: the header line missing from the step but present elsewhere in the file gives exactly one \"does not say\" line" \
  "$CH_NO_HEADER" "$(procedure_problems "$d")"

fresh_case changed-header-no-dash
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//selftest: --changed —/selftest: --changed}"
assert_eq "\`selftest: --changed\` without the em dash the header really prints is not the header" \
  "$CH_NO_HEADER" "$(procedure_problems "$d")"

describe "HARNESS-095 AC-2: step 2 names the full run as an option, and says when"

fresh_case full-missing
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_FULL"/the full self-test}"
assert_eq "control: a step that names no full-run option gives exactly the one \"full run\" line, and its conditions are not judged" \
  "$CH_NO_FULL" "$(procedure_problems "$d")"

fresh_case full-other-step
write_advance "$d" "$GOOD_TOOLS" "$(s="${GOOD_STEPS//"$STEP_FULL"/the full self-test}"; printf '%s\n7. If in doubt, %s when the header says every suite, when you cannot name the suite, or for a suite it had not selected.' "$s" "$STEP_FULL")"
assert_eq "the full run and its conditions in a DIFFERENT step do not satisfy step 2" \
  "$CH_NO_FULL" "$(procedure_problems "$d")"

fresh_case full-in-prose
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_FULL"/the full self-test}" \
  "Prose outside the steps: run $STEP_FULL when the header says every suite, when you cannot name the suite, or for a suite it had not selected."
assert_eq "the full run and its conditions only in prose after the steps do not satisfy step 2" \
  "$CH_NO_FULL" "$(procedure_problems "$d")"

fresh_case full-targeted
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_FULL"/\`SELFTEST_JOBS=4 bash scripts/selftest.sh procedure\`}"
assert_eq "a targeted \`SELFTEST_JOBS=4 bash scripts/selftest.sh procedure\` is not the full run" \
  "$CH_NO_FULL" "$(procedure_problems "$d")"

fresh_case full-no-condition
s="${GOOD_STEPS//"$STEP_FULL runs instead when the header"/$STEP_FULL is always available.}"
s="${s//"says \`every suite\`, when you cannot name"/That is all.}"
s="${s//"the suite that exercises a changed script's caller, or when CI failed a"/Nothing else.}"
s="${s//"suite the local run had not selected."/End.}"
write_advance "$d" "$GOOD_TOOLS" "$s"
assert_eq "control: a step naming the full run with NO condition gives exactly three lines, one per condition, in order" \
  "$CH_WHEN_A
$CH_WHEN_B
$CH_WHEN_C" "$(procedure_problems "$d")"

fresh_case full-reworded
s="${GOOD_STEPS//"says \`every suite\`, when you cannot name"/selects all of them, when you do not know}"
s="${s//"the suite that exercises a changed script's caller, or when CI failed a"/which suite covers a caller, or when CI failed a}"
s="${s//"suite the local run had not selected."/suite the local run skipped.}"
write_advance "$d" "$GOOD_TOOLS" "$s"
assert_eq "control: the three conditions reworded away give exactly three lines" \
  "$CH_WHEN_A
$CH_WHEN_B
$CH_WHEN_C" "$(procedure_problems "$d")"

i=0
for c in "${FULL_WHEN[@]}"; do
  i=$((i + 1))
  fresh_case "full-without-$i"
  # Unwrap `cannot name the suite` first, so removing the needle removes it.
  s="${GOOD_STEPS//$'\n'"   the suite that"/ the suite that}"
  write_advance "$d" "$GOOD_TOOLS" "${s//"$c"/elsewhere}" "Prose outside the steps says $c."
  case $i in 1) want="$CH_WHEN_A" ;; 2) want="$CH_WHEN_B" ;; *) want="$CH_WHEN_C" ;; esac
  assert_eq "the full-run option without \`$c\`, present elsewhere in the file, gives exactly one line naming it" \
    "$want" "$(procedure_problems "$d")"
done

fresh_case full-every-suite-before-only
s="${GOOD_STEPS//"says \`every suite\`, when"/says so, when}"
write_advance "$d" "$GOOD_TOOLS" "$s"
assert_eq "\`every suite\` only BEFORE the full-run span (in the \`--changed\` description) does not say when to take the full run: one line" \
  "$CH_WHEN_A" "$(procedure_problems "$d")"

CH_BACK='.claude/commands/advance-story.md: its full-run option does not say how to get back: `bash scripts/phase.sh set $1 GATES`'

describe "HARNESS-095 R-1: condition (a) is the backticked \`every suite\`, not the closing sentence's bare words"

fresh_case full-every-suite-only-in-closing
s="${GOOD_STEPS//"says \`every suite\`, when"/selects all of them, when}"
assert_eq "precondition: the reworded step still carries the bare closing sentence after the full-run span" \
  "kept" "$(case "${s#*"$STEP_FULL"}" in *"CI runs every suite on the PR either way."*) printf kept ;; esac)"
write_advance "$d" "$GOOD_TOOLS" "$s"
assert_eq "control (R-1, the defect): condition (a) reworded away, \"CI runs every suite on the PR either way\" kept after the full-run span, gives exactly the (a) line" \
  "$CH_WHEN_A" "$(procedure_problems "$d")"

describe "HARNESS-095 AM-1: the full-run option says how to get back to this step"

fresh_case full-no-route-back
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_BACK"/the phase command}" "Prose outside the steps: $STEP_BACK."
assert_eq "control (AM-1): the full-run option without \`bash scripts/phase.sh set \$1 GATES\`, present elsewhere in the file, gives exactly the one \"how to get back\" line" \
  "$CH_BACK" "$(procedure_problems "$d")"

fresh_case full-route-back-before-only
s="${GOOD_STEPS//"$STEP_BACK"/the phase command}"
s="${s//"can break, every suite when"/can break (from REVIEW, $STEP_BACK), every suite when}"
write_advance "$d" "$GOOD_TOOLS" "$s"
assert_eq "\`bash scripts/phase.sh set \$1 GATES\` only BEFORE the full-run span is not the full-run option's route back: one line" \
  "$CH_BACK" "$(procedure_problems "$d")"

fresh_case full-route-back-expanded
write_advance "$d" "$GOOD_TOOLS" "${GOOD_STEPS//"$STEP_BACK"/\`bash scripts/phase.sh set HARNESS-095 GATES\`}"
assert_eq "an expanded id (\`bash scripts/phase.sh set HARNESS-095 GATES\`) is not the literal \`\$1\` span: one line" \
  "$CH_BACK" "$(procedure_problems "$d")"

fresh_case full-condition-next-step
s="${GOOD_STEPS//"suite the local run had not selected."/suite the local run skipped.}"
s="${s//"3. \`bash scripts/phase.sh set \$1 REVIEW\`"/3. \`bash scripts/phase.sh set \$1 REVIEW\` once you have run any suite the run had not selected}"
write_advance "$d" "$GOOD_TOOLS" "$s"
assert_eq "a condition in the NEXT step is not in the full-run option: one line" \
  "$CH_WHEN_C" "$(procedure_problems "$d")"

fresh_case full-condition-wrapped
assert_eq "the compliant fixture reflows \`cannot name the suite\` across a line break, and it still counts: silent" \
  "" "$(procedure_problems "$d")"

describe "HARNESS-095 AC-3: both commands' allowed-tools carry the \`--changed\` pattern beside the full-run one"

fresh_case changed-tool-advance
write_advance "$d" "${GOOD_TOOLS//", $TOOL_CHANGED"/}" "$GOOD_STEPS"
assert_eq "control: advance-story's allowed-tools without the \`--changed\` entry gives exactly one line" \
  "$CH_LACKS_A" "$(procedure_problems "$d")"

fresh_case changed-tool-complete
write_complete "$d" "${GOOD_TOOLS//", $TOOL_CHANGED"/}" "$GOOD_BULLET"
assert_eq "control: complete-story's allowed-tools without the \`--changed\` entry gives exactly one line" \
  "$CH_LACKS_C" "$(procedure_problems "$d")"

fresh_case changed-tool-no-star
write_advance "$d" "${GOOD_TOOLS//"$TOOL_CHANGED"/Bash(SELFTEST_JOBS=4 bash scripts/selftest.sh --changed)}" "$GOOD_STEPS"
assert_eq "the \`--changed\` entry spelled without \`:*\` does not count" \
  "$CH_LACKS_A" "$(procedure_problems "$d")"

fresh_case changed-tool-in-body
write_complete "$d" "${GOOD_TOOLS//", $TOOL_CHANGED"/}" "$GOOD_BULLET" "It may also run $TOOL_CHANGED."
assert_eq "the \`--changed\` entry only in the body does not count" \
  "$CH_LACKS_C" "$(procedure_problems "$d")"

fresh_case full-tool-advance
write_advance "$d" "${GOOD_TOOLS//", $TOOL_FULL"/}" "$GOOD_STEPS"
assert_eq "the full-run entry stays: advance-story without it gives exactly one line" \
  "$FULL_LACKS_A" "$(procedure_problems "$d")"

fresh_case full-tool-complete
write_complete "$d" "${GOOD_TOOLS//", $TOOL_FULL"/}" "$GOOD_BULLET"
assert_eq "the full-run entry stays: complete-story without it gives exactly one line" \
  "$FULL_LACKS_C" "$(procedure_problems "$d")"

fresh_case changed-tool-replaces-full
write_advance "$d" "${GOOD_TOOLS//", $TOOL_FULL"/}" "$GOOD_STEPS"
write_complete "$d" "${GOOD_TOOLS//", $TOOL_FULL"/}" "$GOOD_BULLET"
assert_eq "the \`--changed\` entry REPLACING the full-run one, in both commands, gives the two full-run lines" \
  "$FULL_LACKS_A
$FULL_LACKS_C" "$(procedure_problems "$d")"

describe "HARNESS-095 AC-3: complete-story's bullet keeps \`diff-review\` and \`selftest-needed.sh\` before the \`--changed\` run"

fresh_case changed-bullet-review-after
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs `bash scripts/selftest-needed.sh`, then `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`**, then a `diff-review`.'
assert_eq "\`diff-review\` after the \`--changed\` run gives exactly one \"names … after\" line" \
  '.claude/commands/complete-story.md: its GATES → REVIEW bullet names `diff-review` after `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(procedure_problems "$d")"

fresh_case changed-bullet-needed-after
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs a `diff-review`, then `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`**, then
  `bash scripts/selftest-needed.sh` to see whether it was needed.'
assert_eq "\`selftest-needed.sh\` after the \`--changed\` run gives exactly one \"names … after\" line" \
  '.claude/commands/complete-story.md: names `bash scripts/selftest-needed.sh` after `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(procedure_problems "$d")"

fresh_case changed-bullet-full-before
write_complete "$d" "$GOOD_TOOLS" '- **GATES → REVIEW runs the full `SELFTEST_JOBS=4 bash scripts/selftest.sh` if in doubt, a `diff-review`, then `bash scripts/selftest-needed.sh` decides whether `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`** runs.'
assert_eq "a full-run mention before \`diff-review\` is not the \`--changed\` run: the order is judged against the \`--changed\` span, silent" \
  "" "$(procedure_problems "$d")"

describe "HARNESS-095 AC-4: the lines the tree WITHOUT this story's edits prints, in order"

fresh_case changed-all-absent
write_advance "$d" "${GOOD_TOOLS//", $TOOL_CHANGED"/}" "$(cat <<'EOF'
1. Review the change with the `diff-review` skill: a fresh dispatch reads the
   diff and its callers, and its report goes into `## Diff review`. A Must fix
   finding is fixed, `bash scripts/gates.sh` runs again and these steps start
   over. Go on only once the report's last line is `Verdict: Ship.`.
2. `bash scripts/selftest-needed.sh` — on `run`,
   `SELFTEST_JOBS=4 bash scripts/selftest.sh` — the whole harness self-test,
   every suite; on skip, paste its line. Dispatch it detached and alone on a
   Windows host, slower when other test runs share it, and check it with
   `bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh`;
   paste `exit:`, `last:` and `duration:` into `## Notes`.
3. `bash scripts/phase.sh set $1 REVIEW`
4. Commit.
5. `bash scripts/check-boundaries.sh`
EOF
)"
write_complete "$d" "${GOOD_TOOLS//", $TOOL_CHANGED"/}" '- **GATES → REVIEW runs a `diff-review`, then `bash scripts/selftest-needed.sh` decides whether the full
  `SELFTEST_JOBS=4 bash scripts/selftest.sh` runs**, detached and alone.'
assert_eq "the HARNESS-094 text (full run only, no \`--changed\` entry) gives four lines: advance-story's lacks and step-2 lines, then complete-story's lacks and bullet lines" \
  "$CH_LACKS_A
$CH_NO_STEP
$CH_LACKS_C
$CH_NO_BULLET" "$(procedure_problems "$d")"

summary "procedure"
