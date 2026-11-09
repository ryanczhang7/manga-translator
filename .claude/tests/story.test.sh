#!/usr/bin/env bash
# The orchestrator reads a story by section (HARNESS-086).
#
# A story file grows as it runs (HARNESS-083 reached 1,760 lines) and both
# orchestrating commands opened with "Read docs/backlog/stories/$1.md first",
# re-sending all of it every turn. `scripts/story.sh` prints one named section,
# the section list, or the frontmatter, and the commands read through it.
#
# THE READING OF "A SECTION" IS SETTLED, NOT DESIGNED HERE (story C-5): it is
# check-boundaries.sh's `section()` - from the line beginning `## <name>` to the
# line before the next column-0 `## `, heading excluded, fences NOT special. So
# this suite reads `section()` out of scripts/check-boundaries.sh itself and
# checks the literal bodies it pins against it, on a fixture that includes the
# fence case: a `## ` line inside a fenced block ends the section, in both
# readings. The one tightening (C-2) is that story.sh matches the WHOLE heading,
# where `section()` matches a prefix; the `Handoff` control pins it, and the
# suite shows `section()` itself DOES match that prefix on this fixture, so the
# control discriminates between the two readings rather than passing on both.
#
# Every byte-for-byte comparison captures stdout with a sentinel (`printf x`
# after the command), because `$(...)` strips trailing newlines and a reading
# that dropped a section's trailing blank lines would otherwise compare equal.
#
# AC-3 is a structural guard, `story_problems <root>`, in procedure_problems'
# shape (procedure.test.sh, dispatch.test.sh): run over REPO_ROOT it must print
# nothing; over fixtures compliant by construction with one site regressed it
# must print exactly the one line C-4 pins. Every comparison is a whole-output
# assert_eq, never a needle. The sites are prose, so this pins that the
# instruction is present, not that a model follows it.
#
# Matching in the guard is pure bash (mapfile, case, [ = ]), no fork per
# needle (HARNESS-023). No pipelines, for check-sigpipe.sh.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK" "${FIX:-}"' EXIT

# --- the settled reading, read out of check-boundaries.sh --------------------
#
# `section()` is copied out of the file CI runs and eval'd here, so the oracle is
# the function itself and not this suite's paraphrase of it. If it is ever
# converged onto lib.sh's story_section (the follow-up in the story's Notes),
# lib.sh is sourced first so the copy still resolves.
CB_SECTION="$(awk '/^section\(\) \{/ { on = 1 } on { print } on && /^\}/ { exit }' \
  "$REPO_ROOT/scripts/check-boundaries.sh")"
assert_contains "check-boundaries.sh still defines section() for this suite to read the settled reading out of" \
  'section() {' "$CB_SECTION"
eval "cb_$CB_SECTION"

# fence_aware_section <file> <name>   The reading this story REJECTS: a `## `
# line inside a ``` fence does not end the section. Used only as a control, to
# show the fixture's fence case actually separates the two readings.
fence_aware_section() {
  awk -v h="## $2" '
    index($0, h) == 1 && !on { on = 1; next }
    on && /^```/ { fence = !fence }
    on && !fence && /^## / { exit }
    on { print }' "$1"
}

# --- the fixture story --------------------------------------------------------

FIX="$(make_project_fixture)"
ID="T-1"
STORY_REL="docs/backlog/stories/$ID.md"
STORY="$FIX/$STORY_REL"

# Short sections; one (Handoff) holds a fenced block whose `## ` line ENDS it.
# Context carries two lines that look like headings and are not (no space after
# `##`; not in column 0). Acceptance criteria carries a third `---` line, which
# `frontmatter` must not read past the second. `Empty` has no body at all.
# The `Notes` heading has trailing spaces, which the whole-heading match trims.
# The last line has a trailing space, which the body keeps.
# Both trailing spaces are written as `<SP>` and substituted after the here-doc,
# because editors strip trailing whitespace from a source line.
STORY_TEXT="$(cat <<'EOF'
---
id: T-1
title: Fixture story
phase: RED
---

## Context

Context line.
##not a heading, no space
  ## indented, not a heading

## Acceptance criteria

- **AC-1** - it works.
---

## Handoff: RED -> GREEN

Run it:

```bash
bash scripts/run.sh
## a heading-shaped line inside a fence
still inside the fence
```

## Empty
## Notes<SP><SP><SP>

<!-- a comment the reader keeps -->
last line<SP>
EOF
)"
printf '%s\n' "${STORY_TEXT//<SP>/ }" > "$STORY"

# The bodies, literal (C-5: settled; each is checked against cb_section below).
B_CONTEXT=$'\nContext line.\n##not a heading, no space\n  ## indented, not a heading\n\n'
B_AC=$'\n- **AC-1** - it works.\n---\n\n'
B_HANDOFF=$'\nRun it:\n\n```bash\nbash scripts/run.sh\n'
B_FENCED=$'still inside the fence\n```\n\n'
B_NOTES=$'\n<!-- a comment the reader keeps -->\nlast line \n'
N_FENCED='a heading-shaped line inside a fence'
SECTIONS_OUT=$'Context\t5\nAcceptance criteria\t4\nHandoff: RED -> GREEN\t5\n'"$N_FENCED"$'\t3\nEmpty\t0\nNotes\t3\n'
FRONT_OUT=$'id: T-1\ntitle: Fixture story\nphase: RED\n'
NAMES_TAIL=$'  Context\n  Acceptance criteria\n  Handoff: RED -> GREEN\n'"  $N_FENCED"$'\n  Empty\n  Notes'
REFUSAL="error: story id '../X' is not one path component: an id is letters, digits, '.', '_' or '-', and starts with a letter or digit"

# cap <cmd...>   OUT := the command's stdout byte for byte (sentinel-protected),
# RC := its exit status, ERR := its stderr (trailing newlines stripped).
cap() {
  OUT="$("$@" 2>"$WORK/err"; r=$?; printf x; exit "$r")"; RC=$?
  OUT="${OUT%x}"
  ERR="$(<"$WORK/err")"
}

# st <args...>   Runs the fixture's scripts/story.sh from the fixture root. The
# cd happens inside cap's command substitution, so it moves nothing here.
_in_fix() { cd "$FIX" && bash scripts/story.sh "$@"; }
_in_src() { cd "$FIX/src" && bash ../scripts/story.sh "$@"; }
st() { cap _in_fix "$@"; }

# lines_of <text>   N := how many newline characters <text> holds.
lines_of() { local s="${1//[!$'\n']/}"; N=${#s}; }

# ---------------------------------------------------------------------------
describe "the oracle: the fixture's literal bodies are check-boundaries.sh's section() reading"

mapfile -t FIXLINES < "$STORY"
assert_eq "the fixture's Notes heading carries its three trailing spaces, so the trim is exercised" \
  "## Notes   " "${FIXLINES[28]}"
cap cb_section "$STORY" "Context"
assert_eq "section() gives Context's literal body, the two heading-shaped lines kept" "$B_CONTEXT" "$OUT"
cap cb_section "$STORY" "Handoff: RED -> GREEN"
assert_eq "section() ends Handoff at the \`## \` line inside the fence: fences are not special" "$B_HANDOFF" "$OUT"
cap cb_section "$STORY" "$N_FENCED"
assert_eq "section() reads the fenced \`## \` line as a heading of its own" "$B_FENCED" "$OUT"
cap cb_section "$STORY" "Notes"
assert_eq "section() gives Notes to end of file, comment and trailing space kept" "$B_NOTES" "$OUT"

# Controls: the fixture separates the readings it is meant to separate.
cap fence_aware_section "$STORY" "Handoff: RED -> GREEN"
lines_of "$OUT"
assert_eq "control: a fence-aware reading of Handoff differs from section()'s, so the fence case discriminates (it would read 9 lines, not 5)" \
  "9" "$N"
cap cb_section "$STORY" "Handoff"
assert_eq "control: section() DOES match the prefix \`Handoff\` on this fixture, so the whole-heading control below discriminates" \
  "$B_HANDOFF" "$OUT"

# ---------------------------------------------------------------------------
describe "AC-1: story.sh section prints the body of one named section"

st section "$ID" "Handoff: RED -> GREEN"
assert_eq "section Handoff: RED -> GREEN exits 0" 0 "$RC"
assert_eq "section Handoff: RED -> GREEN prints its body byte for byte, ending at the fenced \`## \` line, heading excluded" \
  "$B_HANDOFF" "$OUT"
assert_eq "section Handoff: RED -> GREEN writes nothing to stderr" "" "$ERR"
cap cb_section "$STORY" "Handoff: RED -> GREEN"
B_CB="$OUT"
st section "$ID" "Handoff: RED -> GREEN"
assert_eq "section Handoff: RED -> GREEN is byte for byte what check-boundaries.sh's section() gives" "$B_CB" "$OUT"

st section "$ID" "Context"
assert_eq "section Context keeps \`##not\` and an indented \`  ## \` line: only column-0 \`## \` ends a section" \
  "$B_CONTEXT" "$OUT"
st section "$ID" "Acceptance criteria"
assert_eq "section Acceptance criteria prints its body, a \`---\` line included" "$B_AC" "$OUT"
st section "$ID" "$N_FENCED"
assert_eq "section names the fenced \`## \` line as a heading and prints from after it to the next heading" \
  "$B_FENCED" "$OUT"
st section "$ID" "Notes"
assert_eq "section Notes matches a heading with trailing spaces and runs to end of file, HTML comment and trailing space kept" \
  "$B_NOTES" "$OUT"
assert_eq "section Notes exits 0" 0 "$RC"
st section "$ID" "Empty"
assert_eq "section Empty, a heading with no body, exits 0 (present, not absent)" 0 "$RC"
assert_eq "section Empty prints nothing" "" "$OUT"

cap _in_src section "$ID" "Context"
assert_eq "section run from a subdirectory resolves the story under the repository root, not the working directory" \
  "$B_CONTEXT" "$OUT"

describe "AC-1 controls: an absent name, a prefix, a bad id"

st section "$ID" "Gate results"
assert_eq "an absent name exits 1" 1 "$RC"
assert_eq "an absent name prints nothing on stdout" "" "$OUT"
assert_eq "an absent name says so on stderr, with the path, then the names the story has, two-space indented, in file order" \
  "no section \"Gate results\" in $STORY_REL"$'\n'"$NAMES_TAIL" "$ERR"

st section "$ID" "Handoff"
assert_eq "the prefix \`Handoff\` does not match \`Handoff: RED -> GREEN\`: exit 1" 1 "$RC"
assert_eq "the prefix \`Handoff\` prints nothing on stdout" "" "$OUT"
assert_eq "the prefix \`Handoff\` is reported as an absent name" \
  "no section \"Handoff\" in $STORY_REL"$'\n'"$NAMES_TAIL" "$ERR"

st section "$ID" "Handoff: RED -> GREEN extra"
assert_eq "a name LONGER than a heading does not match either: exit 1" 1 "$RC"
st section "$ID" "notes"
assert_eq "the match is case-sensitive: \`notes\` exits 1" 1 "$RC"

st section "../X" "Context"
assert_eq "the id \`../X\` exits 2" 2 "$RC"
assert_eq "the id \`../X\` prints the refusal its callers print, on stderr" "$REFUSAL" "$ERR"
assert_eq "the id \`../X\` prints nothing on stdout" "" "$OUT"

st section "T-9" "Context"
assert_eq "a valid id with no story file exits 1" 1 "$RC"
assert_eq "a valid id with no story file names the path it looked for" \
  "no story file at docs/backlog/stories/T-9.md" "$ERR"

describe "AC-1: lib.sh's story_section is the extractor story.sh calls (C-2)"

cap bash -c '. "$1" && story_section "$2" "Handoff: RED -> GREEN"' _ "$REPO_ROOT/.claude/hooks/lib.sh" "$STORY"
assert_eq "story_section <file> \"Handoff: RED -> GREEN\" returns 0" 0 "$RC"
assert_eq "story_section prints the same body story.sh does" "$B_HANDOFF" "$OUT"
cap bash -c '. "$1" && story_section "$2" "Handoff"' _ "$REPO_ROOT/.claude/hooks/lib.sh" "$STORY"
assert_eq "story_section with the prefix \`Handoff\` returns 1" 1 "$RC"
assert_eq "story_section with the prefix \`Handoff\` prints nothing" "" "$OUT"

# ---------------------------------------------------------------------------
describe "AC-2: story.sh sections and frontmatter"

st sections "$ID"
assert_eq "sections exits 0" 0 "$RC"
assert_eq "sections prints <name>TAB<body line count> per \`## \` heading in file order, the fenced one included, names trimmed" \
  "$SECTIONS_OUT" "$OUT"

st frontmatter "$ID"
assert_eq "frontmatter exits 0" 0 "$RC"
assert_eq "frontmatter prints the lines between the first two \`---\` lines, exclusive, and not past the second" \
  "$FRONT_OUT" "$OUT"

printf '# A story with no frontmatter\n\n## Context\n\n---\n\nbody\n\n---\n' > "$FIX/docs/backlog/stories/T-2.md"
st frontmatter "T-2"
assert_eq "control: a story with no frontmatter exits 1, though its body holds two \`---\` lines" 1 "$RC"
assert_eq "control: a story with no frontmatter prints nothing on stdout" "" "$OUT"
assert_eq "control: a story with no frontmatter says so on stderr" \
  "no frontmatter in docs/backlog/stories/T-2.md" "$ERR"

printf -- '---\nid: T-3\n\n## Context\n\nbody\n' > "$FIX/docs/backlog/stories/T-3.md"
st frontmatter "T-3"
assert_eq "control: a frontmatter opened and never closed exits 1" 1 "$RC"

printf 'just prose\n' > "$FIX/docs/backlog/stories/T-4.md"
st sections "T-4"
assert_eq "sections on a story with no \`## \` heading exits 0" 0 "$RC"
assert_eq "sections on a story with no \`## \` heading prints nothing" "" "$OUT"

st sections "../X"
assert_eq "sections refuses \`../X\` with exit 2" 2 "$RC"
assert_eq "sections prints the refusal on stderr" "$REFUSAL" "$ERR"
st frontmatter "../X"
assert_eq "frontmatter refuses \`../X\` with exit 2" 2 "$RC"
assert_eq "frontmatter prints the refusal on stderr" "$REFUSAL" "$ERR"

describe "C-1: usage"

for args in "" "bogus T-1" "section T-1" "section" "sections" "frontmatter"; do
  # shellcheck disable=SC2086  # word-splitting the case is the point
  st $args
  assert_eq "\`story.sh $args\` exits 2 with a usage line" "2|usage" "$RC|$( case "$ERR" in *usage:*) printf usage ;; esac )"
  assert_eq "\`story.sh $args\` prints nothing on stdout" "" "$OUT"
done

# ===========================================================================
# AC-3: the structural guard (C-4)
# ===========================================================================

ADVANCE=".claude/commands/advance-story.md"
COMPLETE=".claude/commands/complete-story.md"
LEADPO=".claude/agents/lead-po.md"
CLAUDEMD="CLAUDE.md"

# The needles, read out of C-4 and AC-3 (settled).
OLD_READ='Read `docs/backlog/stories/$1.md` first.'
ROW_FIRST='| PLANNED → RED |'
ROW_LAST='| GATES → REVIEW |'
BY_SECTION='bash scripts/story.sh section'
TOOL_STORY='Bash(bash scripts/story.sh:*)'
RUN_LINE='bash scripts/story.sh section ID NAME'
RUN_HEADING='## Running things'

# load <file>   LN := the file's lines, a trailing CR stripped from each.
load() {
  local i
  LN=(); mapfile -t LN < "$1"
  for i in "${!LN[@]}"; do LN[$i]="${LN[$i]%$'\r'}"; done
}

# joined   TXT := the loaded lines, newline-joined.
joined() { local IFS=$'\n'; TXT="${LN[*]}"; }

# trim <s>   T := <s> without leading and trailing whitespace.
trim() {
  T="$1"
  T="${T#"${T%%[![:space:]]*}"}"
  T="${T%"${T##*[![:space:]]}"}"
}

# has_line_beginning <prefix>   A loaded line begins with <prefix>.
has_line_beginning() {
  local l
  for l in "${LN[@]}"; do
    case "$l" in "$1"*) return 0 ;; esac
  done
  return 1
}

# permits_story   The loaded file's frontmatter (line 1 exactly `---` to the
# next line exactly `---`) has an `allowed-tools:` line with a comma-separated,
# trimmed entry EQUAL to TOOL_STORY. Containing it is not enough.
permits_story() {
  local i n="${#LN[@]}" end=-1 e
  local -a parts
  [ "$n" -gt 0 ] && [ "${LN[0]}" = "---" ] || return 1
  for ((i = 1; i < n; i++)); do
    [ "${LN[$i]}" = "---" ] && { end=$i; break; }
  done
  [ "$end" -gt 0 ] || return 1
  for ((i = 1; i < end; i++)); do
    case "${LN[$i]}" in
      'allowed-tools:'*)
        IFS=',' read -r -a parts <<<"${LN[$i]#allowed-tools:}"
        for e in "${parts[@]}"; do
          trim "$e"
          [ "$T" = "$TOOL_STORY" ] && return 0
        done
        return 1 ;;
    esac
  done
  return 1
}

# running_things_lists   The loaded file has a column-0 line EXACTLY
# `## Running things` (trailing space trimmed), and inside the FIRST fenced
# block after it - from the first line beginning ``` to the next line beginning
# ``` - before any later column-0 `## ` heading, a line beginning RUN_LINE.
running_things_lists() {
  local l state=0
  for l in "${LN[@]}"; do
    case "$state" in
      0) trim "$l"; [ "$T" = "$RUN_HEADING" ] && [ "${l:0:3}" = "## " ] && state=1 ;;
      1) case "$l" in
           '```'*) state=2 ;;
           '## '*) return 1 ;;
         esac ;;
      2) case "$l" in
           '```'*) return 1 ;;
           "$RUN_LINE"*) return 0 ;;
         esac ;;
    esac
  done
  return 1
}

# story_problems <root>   One line `<relative-path>: <reason>` per violation, in
# the C-4 table's order, file by file; silent when compliant. Always returns 0.
story_problems() {
  local root="$1" f
  if [ ! -f "$root/$ADVANCE" ]; then
    printf '%s: file is missing\n' "$ADVANCE"
  else
    load "$root/$ADVANCE"; joined
    case "$TXT" in *"$OLD_READ"*) printf '%s: still reads the whole story file first\n' "$ADVANCE" ;; esac
    { has_line_beginning "$ROW_FIRST" && has_line_beginning "$ROW_LAST"; } \
      || printf '%s: has no per-phase section table\n' "$ADVANCE"
    case "$TXT" in *"$BY_SECTION"*) ;; *) printf '%s: does not read the story by section\n' "$ADVANCE" ;; esac
    permits_story || printf '%s: does not permit story.sh\n' "$ADVANCE"
  fi
  if [ ! -f "$root/$COMPLETE" ]; then
    printf '%s: file is missing\n' "$COMPLETE"
  else
    load "$root/$COMPLETE"; joined
    case "$TXT" in *"$BY_SECTION"*) ;; *) printf '%s: does not read the story by section\n' "$COMPLETE" ;; esac
    permits_story || printf '%s: does not permit story.sh\n' "$COMPLETE"
  fi
  if [ ! -f "$root/$LEADPO" ]; then
    printf '%s: file is missing\n' "$LEADPO"
  else
    load "$root/$LEADPO"; joined
    case "$TXT" in *"$BY_SECTION"*) ;; *) printf '%s: does not read the story by section\n' "$LEADPO" ;; esac
  fi
  if [ ! -f "$root/$CLAUDEMD" ]; then
    printf '%s: file is missing\n' "$CLAUDEMD"
  else
    load "$root/$CLAUDEMD"
    running_things_lists || printf '%s: Running things does not list story.sh\n' "$CLAUDEMD"
  fi
  return 0
}

# --- a compliant fixture, by construction -------------------------------------
# Never copied from the real tree, which in RED is not compliant. The wording is
# nobody's contract; GREEN writes the real files (C-3).

GOOD_TOOLS='allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/story.sh:*), Bash(git:*), Read, Task'

# The table, in C-3's exact shape.
TABLE="$(cat <<'EOF'
| Phase | Read with `bash scripts/story.sh section $1 <name>` |
|---|---|
| PLANNED → RED | Context, Acceptance criteria, Contract, Deferred verifications, Model guidance, Out of scope |
| RED → GREEN | Acceptance criteria, Contract, Handoff: RED -> GREEN, Deferred verifications, Regressions, Model guidance |
| GREEN → GATES | Deferred verifications, Gate results, Gate probes, Notes |
| GATES → REVIEW | Diff review, Gate results, Deferred verifications, Notes |
| REVIEW → DONE | Notes |
EOF
)"
ADV_INTRO='Read the frontmatter with `bash scripts/story.sh frontmatter $1`, then each section its phase needs with `bash scripts/story.sh section $1 <name>`:'

# write_advance <dir> <tools-line> <intro> <table> [<tail>]
write_advance() {
  {
    printf -- '---\ndescription: Move one story forward\n%s\n---\n\nStory: $1\n\n' "$2"
    printf '%s\n\n%s\n\n' "$3" "$4"
    printf 'A dispatch prompt is built from those sections, pasted.\n\n'
    [ -n "${5:-}" ] && printf '%s\n\n' "$5"
    printf '**PLANNED → RED.** Create and switch to the story'"'"'s branch.\n'
  } > "$1/$ADVANCE"
}

# write_complete <dir> <tools-line> <body>
write_complete() {
  printf -- '---\ndescription: Drive one story\n%s\n---\n\nStory: $1\n\n%s\n' "$2" "$3" > "$1/$COMPLETE"
}
GOOD_COMPLETE_BODY='Each phase reads only the sections it needs, with `bash scripts/story.sh section $1 <name>`.'

# write_leadpo <dir> <body>
write_leadpo() {
  printf -- '---\nname: lead-po\nmodel: fable\n---\n\n## Orchestrating\n\n%s\n' "$2" > "$1/$LEADPO"
}
GOOD_LEADPO='- the story id, and each section below, taken with `bash scripts/story.sh section`'

# write_claude <dir> <running-things-block-lines> [<after-block prose>] [<heading>]
write_claude() {
  {
    printf '# Harness\n\n## The loop\n\n```\n/advance-story ID\n```\n\n'
    printf '%s\n\nNever guess a build command.\n\n```bash\n' "${4:-$RUN_HEADING}"
    printf 'bash scripts/doctor.sh           # is the toolchain installed?\n'
    [ -n "$2" ] && printf '%s\n' "$2"
    printf 'bash scripts/gates.sh            # all gates\n```\n\n'
    [ -n "${3:-}" ] && printf '%s\n\n' "$3"
    printf '## Context discipline\n\nWrite it down.\n'
  } > "$1/$CLAUDEMD"
}
GOOD_RUN='bash scripts/story.sh section ID NAME   # one section of a story, as check-boundaries reads it'

# fresh_case <name>   d := a new compliant fixture's path.
fresh_case() {
  d="$WORK/$1"
  [ -e "$d" ] && rm -rf "$d"
  mkdir -p "$d/.claude/commands" "$d/.claude/agents"
  write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "$TABLE"
  write_complete "$d" "$GOOD_TOOLS" "$GOOD_COMPLETE_BODY"
  write_leadpo "$d" "$GOOD_LEADPO"
  write_claude "$d" "$GOOD_RUN"
}

# The fault lines, as C-4 pins them (`<path>: <reason>`).
L_READS="$ADVANCE: still reads the whole story file first"
L_TABLE="$ADVANCE: has no per-phase section table"
L_ADV_SECTION="$ADVANCE: does not read the story by section"
L_ADV_TOOL="$ADVANCE: does not permit story.sh"
L_CMP_SECTION="$COMPLETE: does not read the story by section"
L_CMP_TOOL="$COMPLETE: does not permit story.sh"
L_PO_SECTION="$LEADPO: does not read the story by section"
L_RUN="$CLAUDEMD: Running things does not list story.sh"

# ---------------------------------------------------------------------------
describe "AC-3: the real tree"

assert_eq "story_problems over the real tree prints nothing: advance-story reads by section through a per-phase table and no longer reads the whole file first, complete-story and lead-po name \`bash scripts/story.sh section\`, both commands permit story.sh, and CLAUDE.md's Running things block lists it" \
  "" "$(story_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "AC-3: the fixture, compliant by construction"

fresh_case compliant
assert_eq "the compliant fixture is silent" "" "$(story_problems "$d")"

fresh_case spaced-entries
write_advance "$d" 'allowed-tools:Read ,   Bash(bash scripts/story.sh:*)  ,Task' "$ADV_INTRO" "$TABLE"
assert_eq "allowed-tools entries are trimmed: spaces around a comma, none after the colon, still permit" \
  "" "$(story_problems "$d")"

fresh_case crlf
for f in "$ADVANCE" "$COMPLETE" "$LEADPO" "$CLAUDEMD"; do
  load "$d/$f"; printf '%s\r\n' "${LN[@]}" > "$d/$f"
done
assert_eq "a CRLF checkout of the compliant fixture is silent too" "" "$(story_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3: advance-story.md, one site regressed at a time"

fresh_case reads-whole-file
write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "$TABLE" "$OLD_READ Then, based on its current phase:"
assert_eq "the sentence \`Read \`docs/backlog/stories/\$1.md\` first.\` put back gives exactly one line" \
  "$L_READS" "$(story_problems "$d")"

fresh_case reads-whole-file-mid-line
write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "$TABLE" "Never: $OLD_READ"
assert_eq "the sentence anywhere in the file, not only at a line's start, gives the line" \
  "$L_READS" "$(story_problems "$d")"

fresh_case reads-other-sentence
write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "$TABLE" 'Read `docs/backlog/stories/$1.md` by section, never whole.'
assert_eq "control: a different sentence about the same path is not the old one, and is silent" \
  "" "$(story_problems "$d")"

fresh_case no-first-row
write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "${TABLE//"$ROW_FIRST"/| PLANNED -> RED |}"
assert_eq "a table without a line beginning \`| PLANNED → RED |\` gives exactly one line" \
  "$L_TABLE" "$(story_problems "$d")"

fresh_case no-last-row
write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "${TABLE//"$ROW_LAST"/| GATES TO REVIEW |}"
assert_eq "a table without a line beginning \`| GATES → REVIEW |\` gives exactly one line" \
  "$L_TABLE" "$(story_problems "$d")"

fresh_case row-indented
write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "${TABLE//"$ROW_FIRST"/  $ROW_FIRST}"
assert_eq "the row indented, not beginning its line, does not count" \
  "$L_TABLE" "$(story_problems "$d")"

fresh_case row-in-prose
write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "${TABLE//"$ROW_FIRST"/| PLANNED -> RED |}" "The row $ROW_FIRST is gone."
assert_eq "the row's text inside a prose line does not count" \
  "$L_TABLE" "$(story_problems "$d")"

fresh_case no-table
write_advance "$d" "$GOOD_TOOLS" "$ADV_INTRO" "(no table)"
assert_eq "no table at all gives exactly one line" \
  "$L_TABLE" "$(story_problems "$d")"

fresh_case adv-no-section
write_advance "$d" "$GOOD_TOOLS" 'Read the frontmatter, then the sections its phase needs:' "${TABLE//"$BY_SECTION"/bash scripts/story.sh get}"
assert_eq "advance-story naming \`bash scripts/story.sh section\` nowhere gives exactly one line" \
  "$L_ADV_SECTION" "$(story_problems "$d")"

fresh_case adv-no-tool
write_advance "$d" 'allowed-tools: Bash(bash scripts/phase.sh:*), Read' "$ADV_INTRO" "$TABLE"
assert_eq "advance-story's allowed-tools without the entry gives exactly one line" \
  "$L_ADV_TOOL" "$(story_problems "$d")"

fresh_case adv-tool-no-star
write_advance "$d" "${GOOD_TOOLS//"$TOOL_STORY"/Bash(bash scripts/story.sh)}" "$ADV_INTRO" "$TABLE"
assert_eq "the entry spelled without \`:*\` does not count" \
  "$L_ADV_TOOL" "$(story_problems "$d")"

fresh_case adv-tool-narrower
write_advance "$d" "${GOOD_TOOLS//"$TOOL_STORY"/Bash(bash scripts/story.sh section:*)}" "$ADV_INTRO" "$TABLE"
assert_eq "a narrower entry containing the script's name is not EQUAL to the entry, and does not count" \
  "$L_ADV_TOOL" "$(story_problems "$d")"

fresh_case adv-tool-in-body
write_advance "$d" 'allowed-tools: Read' "$ADV_INTRO" "$TABLE" "It may run $TOOL_STORY."
assert_eq "the entry only in the body, not the allowed-tools line, does not count" \
  "$L_ADV_TOOL" "$(story_problems "$d")"

fresh_case adv-no-frontmatter
{ printf 'Story: $1\n\n%s\n\n%s\n' "$ADV_INTRO" "$TABLE"; printf '%s\n' "$GOOD_TOOLS"; } > "$d/$ADVANCE"
assert_eq "an allowed-tools line outside any frontmatter does not count" \
  "$L_ADV_TOOL" "$(story_problems "$d")"

fresh_case adv-missing
rm -f "$d/$ADVANCE"
assert_eq "advance-story.md missing gives one line naming it" \
  "$ADVANCE: file is missing" "$(story_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3: complete-story.md and lead-po.md"

fresh_case cmp-no-section
write_complete "$d" "$GOOD_TOOLS" 'Each phase reads the whole story file.'
assert_eq "complete-story naming \`bash scripts/story.sh section\` nowhere gives exactly one line" \
  "$L_CMP_SECTION" "$(story_problems "$d")"

fresh_case cmp-sections-only
write_complete "$d" "$GOOD_TOOLS" 'Each phase lists them with `bash scripts/story.sh sections $1`.'
assert_eq "documented limit: \`bash scripts/story.sh sections\` CONTAINS C-4's needle and is accepted - C-4 says \"contain\", and a trailing-space needle would refuse C-3's own \`...section\`+backtick wording" \
  "" "$(story_problems "$d")"

fresh_case cmp-no-tool
write_complete "$d" 'allowed-tools: Read, Task' "$GOOD_COMPLETE_BODY"
assert_eq "complete-story's allowed-tools without the entry gives exactly one line" \
  "$L_CMP_TOOL" "$(story_problems "$d")"

fresh_case cmp-missing
rm -f "$d/$COMPLETE"
assert_eq "complete-story.md missing gives one line naming it" \
  "$COMPLETE: file is missing" "$(story_problems "$d")"

fresh_case po-no-section
write_leadpo "$d" '- the story id and file path'
assert_eq "lead-po naming \`bash scripts/story.sh section\` nowhere gives exactly one line" \
  "$L_PO_SECTION" "$(story_problems "$d")"

fresh_case po-missing
rm -f "$d/$LEADPO"
assert_eq "lead-po.md missing gives one line naming it" \
  "$LEADPO: file is missing" "$(story_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3: CLAUDE.md's Running things block"

fresh_case run-missing
write_claude "$d" ""
assert_eq "the block without the line gives exactly one line" \
  "$L_RUN" "$(story_problems "$d")"

fresh_case run-in-prose
write_claude "$d" "" "$GOOD_RUN"
assert_eq "the line in prose after the block, not inside the fence, does not count" \
  "$L_RUN" "$(story_problems "$d")"

fresh_case run-indented
write_claude "$d" "  $GOOD_RUN"
assert_eq "the line indented inside the fence does not begin with the needle, and does not count" \
  "$L_RUN" "$(story_problems "$d")"

fresh_case run-sections
write_claude "$d" 'bash scripts/story.sh sections ID       # the sections of a story'
assert_eq "\`bash scripts/story.sh sections ID\` is not \`section ID NAME\`, and does not count" \
  "$L_RUN" "$(story_problems "$d")"

fresh_case run-other-section
write_claude "$d" "" "" "## Running other things"
{ printf '\n## Running things\n\nSee above.\n\n## Commands\n\n```bash\n%s\n```\n' "$GOOD_RUN"; } >> "$d/$CLAUDEMD"
assert_eq "the line in a fenced block under a DIFFERENT heading, after a Running things section with no fence, does not count" \
  "$L_RUN" "$(story_problems "$d")"

fresh_case run-second-fence
write_claude "$d" ""
# Put a second fence INSIDE the Running things section, after the first.
load "$d/$CLAUDEMD"
{
  for l in "${LN[@]}"; do
    [ "$l" = "## Context discipline" ] && printf '```bash\n%s\n```\n\n' "$GOOD_RUN"
    printf '%s\n' "$l"
  done
} > "$d/$CLAUDEMD"
assert_eq "the line in a SECOND fence of the section, not the block, does not count" \
  "$L_RUN" "$(story_problems "$d")"

fresh_case run-heading-prefix
write_claude "$d" "$GOOD_RUN" "" "## Running things, later"
assert_eq "a heading that only BEGINS \`## Running things\` is not the section" \
  "$L_RUN" "$(story_problems "$d")"

fresh_case claude-missing
rm -f "$d/$CLAUDEMD"
assert_eq "CLAUDE.md missing gives one line naming it" \
  "$CLAUDEMD: file is missing" "$(story_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3: every site regressed at once, in the C-4 order"

fresh_case all
write_advance "$d" 'allowed-tools: Read' 'Story file:' "(no table)" "$OLD_READ Then, based on its current phase:"
write_complete "$d" 'allowed-tools: Read' 'Each phase reads the whole file.'
write_leadpo "$d" '- the story id and file path'
write_claude "$d" ""
assert_eq "a tree without this story's edits prints eight lines: advance-story's four, complete-story's two, lead-po's, CLAUDE.md's" \
  "$L_READS
$L_TABLE
$L_ADV_SECTION
$L_ADV_TOOL
$L_CMP_SECTION
$L_CMP_TOOL
$L_PO_SECTION
$L_RUN" "$(story_problems "$d")"

summary "story"
