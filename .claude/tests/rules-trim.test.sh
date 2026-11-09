#!/usr/bin/env bash
# rules.md keeps every rule and moves its worked cases out (HARNESS-087).
#
# rules.md is imported into every turn by CLAUDE.md, so every line of it is
# paid for on every turn. The worked cases - the anecdotes that are the
# evidence for a rule, not the rule - move to
# .claude/skills/tdd-cycle/reference/cases.md, which is loaded by the phase it
# is about, and the rule that cited each one points at it by path.
#
# The sites are prose, so nothing executes them: the shape `tdd-cycle` calls
# "code no machine you have can execute: grep for the shape". It pins that the
# rules are PRESENT (by their opening lines, read out of the file - C-1), that
# the cases MOVED (by needle - C-2), and that the line count is under the cap
# (a number settled by decision - C-5). It cannot pin that a reflowed rule kept
# every sentence; the reviewer judges that half (C-1).
#
# `rules_trim_problems <root>` prints one line per violation, in the story's
# C-4 shapes, and is silent on a compliant tree. It runs over REPO_ROOT, which
# is what is red until GREEN moves the text, and over fixtures built compliant
# by construction with one site regressed at a time, where it must print
# exactly the one line naming that site. The fixtures are what make the
# real-tree assertions mean anything. DV-1 in the story is the same probe
# against a REAL line of rules.md, owned by GATES.
#
# Pure bash over the files (mapfile, whole-line and prefix compares, as
# reporting.test.sh does): no fork per check.
#
# Matching semantics, each pinned by a control below:
#   - a heading or table header is a WHOLE line; every other C-1 entry is a
#     PREFIX at column 0 (an indented copy does not count);
#   - "still carries" is judged over rules.md JOINED (each line trimmed, joined
#     with one space), so a needle reflowed across two lines is still seen;
#   - "present in cases.md" is judged PER LINE, and only after a line starting
#     `## ` outside a ``` fence (a `### ` heading does not count);
#   - a `# ` section runs to the next column-0 `# ` line outside a ``` fence;
#     its pointer is the fixed string `reference/cases.md` anywhere in it. A
#     section whose heading is missing is reported once, as the missing
#     heading, not again as a missing pointer;
#   - SKILL.md's entry is a line beginning "- `reference/cases.md`" inside its
#     `## Details` section (to the next `## ` line), the shape of the three
#     entries already there.
#
# HARNESS-092: every pointer NAMES a heading. The fixed string above says a
# section points at cases.md; it never read WHICH case, so a renamed heading
# or a mistyped pointer resolved to nothing and nothing said so.
#   - a pointer is read from rules.md JOINED (the same J as "still carries"):
#     each occurrence of "`reference/cases.md`, \"" opens one, and its text
#     runs to the first `")` after it, exclusive. Inner `"` and `$` are
#     ordinary characters of the text; the terminator is two characters
#     because no heading contains `")`. An opener with no `")` after it ends
#     the scan (nothing on the real tree is shaped so; AC-6 would see it);
#   - a pointer written in any other shape is not a pointer to this check
#     (story C-4: the syntax is not changed, and that is accepted);
#   - a text RESOLVES when some line of cases.md outside a ``` fence is exactly
#     `## ` and the text: a whole-line compare, so a prefix, a suffix and a
#     case difference all fail. A failing pointer is reported once per
#     occurrence, after the rules.md lines and before the cases.md ones;
#   - POINTERS below is the settled list of the real tree (story C-1), and the
#     real-tree extraction must equal it, so the "resolves" assertion cannot
#     pass by finding nothing. Pure bash string ops over J, no grep or sed.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# --- the settled values (story Contract: read out, not re-derived) -----------

# AC-1 / C-5. Settled by decision, not measured: rules.md was 399 lines on
# 2026-10-31 (release 101), and still 399 on 2026-11-03 (release 105). The
# planner's estimate of 280 was wrong: GREEN measured 369 on 2026-11-03 with
# every C-2 case moved, and the user set 370 (Amendments, A-1). Raising it
# later is this one line.
CAP=370

RULES=".claude/harness/rules.md"
CASES=".claude/skills/tdd-cycle/reference/cases.md"
SKILL=".claude/skills/tdd-cycle/SKILL.md"
POINTER='reference/cases.md'
SKILL_ENTRY='- `reference/cases.md`'
DETAILS='## Details'

# C-1, whole lines: the six headings and the two table header lines.
WHOLE='# Path ownership
# The model each agent runs on
# Phase permissions
# Non-negotiables
# Mutation work per story
# Reporting to the user
| Agent | Writes | Never writes |
| Phase | May write | Meaning |'

# C-1, line prefixes at column 0. Each was read out of rules.md at release 105
# and begins exactly one line of it there.
PREFIXES='**The bootstrap exception.**
**`.gitignore` has no single owner.**
**Portability.**
**A test that needs this answer asks for it; it does not reimplement it.**
**The per-phase plan is `.claude/harness/models.conf`, not a judgement made
**RED may declare a test dependency, and only a test dependency.**
**When RED needs something the manifest cannot carry, it stops and says so.**
**A gate failure whose only legal fix is a write the current phase forbids is a
- **Lockfiles are permitted unchecked.**
- **Some ecosystems have no in-file split at all**
- **That is a property of the assertion, not of the phase or the run.**
- **An assertion'"'"'s needle is part of the assertion, and a needle that cannot
- **A rule is probed against the tree it judges, not only against fixtures you
- **Narrowing an input domain can be correct; loosening a comparison is always a
- **Required per story.**
- **How a mutation runs.**
- **Not per story.**
- **Lead with the outcome.**
- **One next action, last.**
- **Plain words.**
- **Working notes stay in the story.**
- **Evidence, not a diagnosis.**
- **Five items, then offer the rest.**
- **Agent-to-agent artefacts are exempt.**
- A test that has never been observed to fail is not a test.
- A gate that has never been observed to fail is not a gate.
- Do not weaken an assertion, add a `skip`, widen a tolerance, or delete a
- Acceptance criteria are frozen once a story leaves PLANNED, for the same
- `## Gate results` is written by `scripts/gates.sh`, never by hand.
- `depends_on` and `branch` in a story'"'"'s frontmatter are enforced by
- Do not commit `.claude/state/**`.
- Agentic scaffolding (`.claude/`, `docs/`, `scripts/`, `.github/`) never ships'

# C-2, the case needles. Each occurs exactly once in rules.md at release 105.
NEEDLES='four private copies in one project drifted apart
compared "the default model" against a stronger one
"a lockfile is permitted unchecked"
IMPLAUSIBLE: sed -i option
ci-local: 15 passed, 0 failed
`check-grep-count.sh` was probed with
read a here-string as a heredoc opener
written into `lib.sh` in release 38
keeping `-0` out of the coordinate generator
on HARNESS-014 the
The backup path is explicit rather than `$TMPDIR`'

# AC-3: the sections a case moved out of, and the budget section.
POINTED='Path ownership
The model each agent runs on
Non-negotiables
Mutation work per story'

# HARNESS-092 C-1: the eight pointer texts of rules.md, in file order, read out
# of it at release 113 (lines 67-68, 101, 208, 226-227, 246-247, 269-270,
# 299-300, 308). 4 and 5 name one heading twice.
OPEN='`reference/cases.md`, "'
CLOSE='")'
POINTERS='Four private copies of "a source module"
"The default model" against itself
Four needles that could not fail
Three guards green over a tree they could not see
Three guards green over a tree they could not see
Negative zero: narrow the generator, not the comparison
A backup that went to an unset $TMPDIR
HARNESS-014: eighteen mutations, no defect'

# --- reading -----------------------------------------------------------------

# load <file>   LN := the file's lines, a trailing CR dropped from each; empty
# when the file does not exist.
load() {
  local i
  LN=()
  [ -f "$1" ] || return 0
  mapfile -t LN < "$1"
  for i in "${!LN[@]}"; do LN[i]="${LN[i]%$'\r'}"; done
}

# has <needle> <text>   Fixed-string containment; nothing in the needle is a
# glob.
has() {
  case "$2" in *"$1"*) return 0 ;; esac
  return 1
}

# is_fence <line>   Its first non-blank characters are three backticks.
is_fence() {
  local t="${1#"${1%%[![:space:]]*}"}" tick='```'
  [ "${t:0:3}" = "$tick" ]
}

# whole_count <line>   N := how many lines of LN are exactly <line>.
whole_count() {
  local l
  N=0
  for l in "${LN[@]}"; do [ "$l" = "$1" ] && N=$((N + 1)); done
  return 0
}

# prefix_count <prefix>   N := how many lines of LN begin with <prefix>, at
# column 0.
prefix_count() {
  local l
  N=0
  for l in "${LN[@]}"; do [ "${l:0:${#1}}" = "$1" ] && N=$((N + 1)); done
  return 0
}

# joined   J := LN, each line trimmed of leading and trailing white space,
# joined with one space.
joined() {
  local l t
  J=""
  for l in "${LN[@]}"; do
    t="${l#"${l%%[![:space:]]*}"}"
    t="${t%"${t##*[![:space:]]}"}"
    J="$J $t"
  done
}

# h1_section <heading>   R := from the line of LN exactly <heading> up to, not
# including, the next column-0 line starting `# ` outside a ``` fence, or EOF.
h1_section() {
  local l on=0 fence=0
  R=""
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "$l" = "$1" ] && { on=1; R="$l"; }
      continue
    fi
    if is_fence "$l"; then fence=$((1 - fence)); R="$R"$'\n'"$l"; continue; fi
    if [ "$fence" = 0 ] && [ "${l:0:2}" = "# " ]; then break; fi
    R="$R"$'\n'"$l"
  done
  return 0
}

# h2_section <heading>   R := from the line of LN exactly <heading> up to, not
# including, the next line starting `## `.
h2_section() {
  local l on=0
  R=""
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "$l" = "$1" ] && { on=1; R="$l"; }
      continue
    fi
    [ "${l:0:3}" = "## " ] && break
    R="$R"$'\n'"$l"
  done
  return 0
}

# placed <needle>   S := where <needle> stands in LN: `under` when some line
# holding it follows a `## ` line outside a ``` fence, `above` when it occurs
# only before any such line, `missing` when no line holds it.
placed() {
  local l h2=0 fence=0
  S=missing
  for l in "${LN[@]}"; do
    if is_fence "$l"; then fence=$((1 - fence)); fi
    if [ "$fence" = 0 ] && [ "${l:0:3}" = "## " ]; then h2=1; fi
    if has "$1" "$l"; then
      if [ "$h2" = 1 ]; then S=under; return 0; fi
      S=above
    fi
  done
  return 0
}

# pointer_texts   P := the pointer texts of J, in order (HARNESS-092 C-1).
pointer_texts() {
  local rest="$J"
  P=()
  while has "$OPEN" "$rest"; do
    rest="${rest#*"$OPEN"}"
    has "$CLOSE" "$rest" || break
    P+=("${rest%%'")'*}")
    rest="${rest#*'")'}"
  done
  return 0
}

# h2_headings   H := the text after `## ` of every line of LN that starts `## `
# outside a ``` fence (the toggle `placed` uses).
h2_headings() {
  local l fence=0
  H=()
  for l in "${LN[@]}"; do
    if is_fence "$l"; then fence=$((1 - fence)); fi
    if [ "$fence" = 0 ] && [ "${l:0:3}" = "## " ]; then H+=("${l:3}"); fi
  done
  return 0
}

# resolves <text>   Some entry of H is exactly <text>.
resolves() {
  local h
  for h in "${H[@]}"; do [ "$h" = "$1" ] && return 0; done
  return 1
}

# pointer_list <root>   The pointer texts of <root>'s rules.md, one per line.
pointer_list() {
  local p out=""
  load "$1/$RULES"; joined; pointer_texts
  for p in "${P[@]}"; do out="$out${out:+$'\n'}$p"; done
  printf '%s' "$out"
}

# --- the guard ---------------------------------------------------------------

# rules_trim_problems <root>   One line per violation, in the C-4 shapes;
# silent when the tree under <root> is compliant. Always returns 0: the output
# is the verdict, so a caller compares it against the empty string.
rules_trim_problems() {
  local root="$1" line needle sec
  # AC-1, AC-2, AC-3 (rules.md half)
  load "$root/$RULES"
  [ "${#LN[@]}" -gt "$CAP" ] && printf 'rules.md: %d lines, the cap is %d\n' "${#LN[@]}" "$CAP"
  while IFS= read -r line; do
    whole_count "$line"
    [ "$N" -ge 1 ] || printf 'rules.md: missing line "%s"\n' "$line"
  done <<LIST
$WHOLE
LIST
  while IFS= read -r line; do
    prefix_count "$line"
    [ "$N" -ge 1 ] || printf 'rules.md: missing line "%s"\n' "$line"
  done <<LIST
$PREFIXES
LIST
  joined
  while IFS= read -r needle; do
    has "$needle" "$J" && printf 'rules.md: still carries "%s"\n' "$needle"
  done <<LIST
$NEEDLES
LIST
  while IFS= read -r sec; do
    whole_count "# $sec"
    [ "$N" -ge 1 ] || continue           # reported above as a missing line
    h1_section "# $sec"
    has "$POINTER" "$R" || printf 'rules.md: %s does not point at %s\n' "$sec" "$POINTER"
  done <<LIST
$POINTED
LIST
  # HARNESS-092: every pointer's text is a ## heading of cases.md
  pointer_texts
  load "$root/$CASES"
  h2_headings
  local p
  for p in "${P[@]}"; do
    resolves "$p" || printf 'rules.md: points at "%s", not a ## heading of cases.md\n' "$p"
  done

  # AC-3 (cases.md half)
  load "$root/$CASES"
  while IFS= read -r needle; do
    placed "$needle"
    case "$S" in
      missing) printf 'cases.md: missing "%s"\n' "$needle" ;;
      above)   printf 'cases.md: "%s" is not under a ## heading\n' "$needle" ;;
    esac
  done <<LIST
$NEEDLES
LIST

  # AC-4
  load "$root/$SKILL"
  h2_section "$DETAILS"
  local found=0
  while IFS= read -r line; do
    [ "${line:0:${#SKILL_ENTRY}}" = "$SKILL_ENTRY" ] && found=1
  done <<REGION
$R
REGION
  [ "$found" = 1 ] || printf 'SKILL.md: does not list %s\n' "$POINTER"
  return 0
}

# only <prefix> <text>   The lines of <text> beginning <prefix>.
only() {
  local l out=""
  while IFS= read -r l; do
    [ "${l:0:${#1}}" = "$1" ] && out="$out${out:+$'\n'}$l"
  done <<TEXT
$2
TEXT
  printf '%s' "$out"
}

# count_lines <text>   How many non-empty lines.
count_lines() {
  local l n=0
  while IFS= read -r l; do [ -n "$l" ] && n=$((n + 1)); done <<TEXT
$1
TEXT
  printf '%d' "$n"
}

# --- a compliant fixture, by construction ------------------------------------
# Minimal files that satisfy every rule above, written out literally rather
# than generated from the lists, so a typo in a list makes the compliant
# fixture report it. Their wording is nobody's contract: GREEN writes the real
# files. Built, not copied: in RED the real tree is what is not compliant.
#
# Deliberate shapes, each pinning a region rule:
#   - `# Path ownership` holds a ``` fence with a `# ` shell comment BEFORE its
#     pointer: the section ends at the next heading, not at the comment;
#   - the needles in cases.md sit under `## ` headings, after a preamble that
#     names none of them, with a fence holding a `## ` comment in one section.
compliant_fixture() { # <dir>
  local d="$1"
  mkdir -p "$d/.claude/harness" "$d/.claude/skills/tdd-cycle/reference"
  cat > "$d/$RULES" <<'EOF'
# Path ownership

| Agent | Writes | Never writes |
|---|---|---|
| **Lead PO** | docs | source |

**The bootstrap exception.** A bootstrap story writes everything.

**`.gitignore` has no single owner.** Whoever adds a tool.

**Portability.** Bash, awk and coreutils.

```bash
# a shell comment inside a fence, not a heading
bash scripts/classify.sh --list source src
```

**A test that needs this answer asks for it; it does not reimplement it.**
Ask classify.sh (the case: `tdd-cycle`, `reference/cases.md`, "Four private
copies of "a source module"").

# The model each agent runs on

**The per-phase plan is `.claude/harness/models.conf`, not a judgement made
fresh each story.** Record what each dispatch resolved to (the case:
`tdd-cycle`, `reference/cases.md`, ""The default model" against itself").

# Phase permissions

| Phase | May write | Meaning |
|---|---|---|
| `RED` | test | failing tests only |

**RED may declare a test dependency, and only a test dependency.** Dev block
(the case: `reference/cases.md`, ""The default model" against itself").

- **Lockfiles are permitted unchecked.** No split to read.
- **Some ecosystems have no in-file split at all** - go.mod.

**When RED needs something the manifest cannot carry, it stops and says so.**

**A gate failure whose only legal fix is a write the current phase forbids is a
return to RED.**

# Non-negotiables

- A test that has never been observed to fail is not a test.
- **That is a property of the assertion, not of the phase or the run.** Earn it.
- A gate that has never been observed to fail is not a gate.
- **An assertion's needle is part of the assertion, and a needle that cannot
  fail is a test that cannot fail.** Anchor it (the case: `tdd-cycle`,
  `reference/cases.md`, "Four needles that could not fail").
- **A rule is probed against the tree it judges, not only against fixtures you
  wrote.** Mutate a real line.
- Do not weaken an assertion, add a `skip`, widen a tolerance, or delete a
  case to reach green.
- **Narrowing an input domain can be correct; loosening a comparison is always a
  weakening.** Name the design clause.
- Acceptance criteria are frozen once a story leaves PLANNED, for the same
  reason tests are frozen.
- `## Gate results` is written by `scripts/gates.sh`, never by hand.
- `depends_on` and `branch` in a story's frontmatter are enforced by
  `phase.sh set`.
- Do not commit `.claude/state/**`. A `.bak` means a failed restore (the
  case: `tdd-cycle`, `reference/cases.md`,
  "A backup that went to an unset $TMPDIR").
- Agentic scaffolding (`.claude/`, `docs/`, `scripts/`, `.github/`) never ships
  in a production image.

# Mutation work per story

The budget (the case: `tdd-cycle`, `reference/cases.md`, "HARNESS-014: eighteen mutations, no defect").

- **Required per story.** One earning mutation.
- **How a mutation runs.** Through mutate.sh.
- **Not per story.** Exhaustive earning.

# Reporting to the user

- **Lead with the outcome.** What is now true.
- **One next action, last.** One thing.
- **Plain words.** Say it plainly.
- **Working notes stay in the story.** Not in chat.
- **Evidence, not a diagnosis.** Point at it.
- **Five items, then offer the rest.** About five.
- **Agent-to-agent artefacts are exempt.** Complete, not short.
EOF
  cat > "$d/$CASES" <<'EOF'
# Cases

The evidence behind rules in rules.md, moved here.

## Four private copies of "a source module"

Four private copies in one project... four private copies in one project drifted apart.

## "The default model" against itself

Two stories once
compared "the default model" against a stronger one, and neither could say.

## Four needles that could not fail

- `"a lockfile is permitted unchecked"` asserted an absence.
- `IMPLAUSIBLE: sed -i option` satisfied the needle.

```bash
## a fenced comment, not a heading
grep '^ci-local:'
```

- matched `ci-local: 15 passed, 0 failed` - the suite's line.

## Three guards green over a tree they could not see

- `check-grep-count.sh` was probed with one shape.
- `check-sigpipe.sh` read a here-string as a heredoc opener and went blind.
- The warning was written into `lib.sh` in release 38.

## Negative zero: narrow the generator, not the comparison

Fixed by keeping `-0` out of the coordinate generator.

## HARNESS-014: eighteen mutations, no defect

Nothing bounded it: on HARNESS-014 the mutation work was 18 mutations.

## A backup that went to an unset $TMPDIR

The backup path is explicit rather than `$TMPDIR` because that variable is unset.
EOF
  cat > "$d/$SKILL" <<'EOF'
# The RED to GREEN cycle

## Details

- `reference/red-phase.md` - choosing the test level
- `reference/cases.md` - the worked cases behind rules.md
- `reference/handoff.md` - what crosses the context boundary

## Why the lock exists

Because.
EOF
}

# HARNESS-092 C-3: the compliant fixture's six pointers, in file order. Each
# quotes a fixture heading whole: the first wraps at column 0, the fifth wraps
# twice and indented (its opener ends one line, the way rules.md 299-300
# does), the second and third name one heading twice, and three of them carry
# an inner `"` or a `$`.
FIX_POINTERS='Four private copies of "a source module"
"The default model" against itself
"The default model" against itself
Four needles that could not fail
A backup that went to an unset $TMPDIR
HARNESS-014: eighteen mutations, no defect'

# fresh_case <name>   A new compliant fixture; echoes its path.
fresh_case() { local d="$WORK/$1"; rm -rf "$d"; compliant_fixture "$d"; printf '%s' "$d"; }

# subst <file> <from> <to>   Replace every fixed-string occurrence, line by
# line. <to> may hold a newline, to split a line. No `sed -i` (GNU-only).
subst() {
  local l out=""
  load "$1"
  for l in "${LN[@]}"; do out="$out${l//"$2"/"$3"}"$'\n'; done
  printf '%s' "$out" > "$1"
}

# drop <file> <fixed>   Delete every line containing <fixed>.
drop() {
  local l out=""
  load "$1"
  for l in "${LN[@]}"; do has "$2" "$l" || out="$out$l"$'\n'; done
  printf '%s' "$out" > "$1"
}

# pad_to <file> <n>   Append filler lines until the file has exactly <n>.
pad_to() {
  local have
  load "$1"; have=${#LN[@]}
  while [ "$have" -lt "$2" ]; do printf 'filler\n' >> "$1"; have=$((have + 1)); done
}

# ---------------------------------------------------------------------------
describe "the pinned lists are the Contract's, whole"

n_whole="$(count_lines "$WHOLE")"; n_pref="$(count_lines "$PREFIXES")"
n_need="$(count_lines "$NEEDLES")"; n_ptr="$(count_lines "$POINTED")"; n_ptrs="$(count_lines "$POINTERS")"
assert_eq "C-1: 8 whole lines (6 headings, 2 table headers) and 32 prefixes; C-2: 11 needles; AC-3: 4 pointed sections; HARNESS-092 C-1: 8 pointer texts" \
  "8 32 11 4 8" "$n_whole $n_pref $n_need $n_ptr $n_ptrs"

# ---------------------------------------------------------------------------
describe "the real tree (red until GREEN moves the cases)"

OUT="$(rules_trim_problems "$REPO_ROOT")"
assert_eq "AC-1: rules.md is at most $CAP lines" \
  "" "$(while IFS= read -r l; do case "$l" in 'rules.md: '*' lines, the cap is '*) printf '%s\n' "$l" ;; esac; done <<< "$OUT")"
assert_eq "AC-2: rules.md keeps every C-1 heading, table header and rule opener" \
  "" "$(only 'rules.md: missing line ' "$OUT")"
assert_eq "AC-3: rules.md no longer carries any C-2 case needle" \
  "" "$(only 'rules.md: still carries ' "$OUT")"
assert_eq "AC-3: cases.md carries every C-2 case needle, each under a ## heading" \
  "" "$(only 'cases.md: ' "$OUT")"
assert_eq "AC-3: each of the four sections a case left points at reference/cases.md" \
  "" "$(while IFS= read -r l; do case "$l" in *' does not point at '*) printf '%s\n' "$l" ;; esac; done <<< "$OUT")"
assert_eq "AC-4: tdd-cycle's SKILL.md lists reference/cases.md under ## Details" \
  "" "$(only 'SKILL.md: ' "$OUT")"
assert_eq "HARNESS-092 AC-6: the pointer texts of rules.md are exactly C-1's eight, in file order" \
  "$POINTERS" "$(pointer_list "$REPO_ROOT")"
assert_eq "HARNESS-092 AC-1: every pointer in rules.md names a ## heading of cases.md" \
  "" "$(only 'rules.md: points at ' "$OUT")"
assert_eq "rules_trim_problems over the real tree prints nothing: every rule kept, every case moved and pointed at" \
  "" "$OUT"

# ---------------------------------------------------------------------------
describe "the fixture: compliant by construction"

d="$(fresh_case compliant)"
assert_eq "the compliant fixture is silent (a fence holding a # comment inside a section, needles under ## headings after a preamble)" \
  "" "$(rules_trim_problems "$d")"
assert_eq "HARNESS-092 C-3: the compliant fixture's six pointers are extracted whole, in order, the wrapped ones joined by one space" \
  "$FIX_POINTERS" "$(pointer_list "$d")"

# ---------------------------------------------------------------------------
describe "AC-1  the cap"

d="$(fresh_case at-cap)"; pad_to "$d/$RULES" "$CAP"
assert_eq "a rules.md of exactly $CAP lines is within the cap" "" "$(rules_trim_problems "$d")"
d="$(fresh_case over-cap)"; pad_to "$d/$RULES" "$((CAP + 1))"
assert_eq "a rules.md one line over the cap is reported with its count" \
  "rules.md: $((CAP + 1)) lines, the cap is $CAP" "$(rules_trim_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-2  every rule opener stays, exactly"

d="$(fresh_case h-demoted)"; subst "$d/$RULES" '# Phase permissions' '## Phase permissions'
assert_eq "a heading demoted to ## is a missing heading" \
  'rules.md: missing line "# Phase permissions"' "$(rules_trim_problems "$d")"

d="$(fresh_case h-suffixed)"; subst "$d/$RULES" '# Non-negotiables' '# Non-negotiables, and more'
assert_eq "a heading is a whole line: a longer line beginning with it does not count, and its pointer is not reported twice" \
  'rules.md: missing line "# Non-negotiables"' "$(rules_trim_problems "$d")"

d="$(fresh_case bold)"; subst "$d/$RULES" '**Portability.**' '**Portable.**'
assert_eq "a reworded bold paragraph opener is reported, naming it" \
  'rules.md: missing line "**Portability.**"' "$(rules_trim_problems "$d")"

d="$(fresh_case bold-rewrapped)"
subst "$d/$RULES" 'not a judgement made' 'not a'$'\n''judgement made'
assert_eq "a wrapped opener whose first line is broken differently is reported: GREEN keeps today's break" \
  'rules.md: missing line "**The per-phase plan is `.claude/harness/models.conf`, not a judgement made"' \
  "$(rules_trim_problems "$d")"

d="$(fresh_case labelled-indented)"; subst "$d/$RULES" '- **Plain words.**' '  - **Plain words.**'
assert_eq "a labelled bullet opener is pinned at column 0: an indented copy does not count" \
  'rules.md: missing line "- **Plain words.**"' "$(rules_trim_problems "$d")"

d="$(fresh_case unlabelled)"; drop "$d/$RULES" '- Do not commit `.claude/state/**`.'
assert_eq "a deleted unlabelled bullet is reported, naming its first line" \
  'rules.md: missing line "- Do not commit `.claude/state/**`."' "$(rules_trim_problems "$d")"

d="$(fresh_case table)"; subst "$d/$RULES" '| Agent | Writes | Never writes |' '| Agent | Writes | Never writes | Notes |'
assert_eq "a table header is a whole line: a changed header is reported" \
  'rules.md: missing line "| Agent | Writes | Never writes |"' "$(rules_trim_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3  every case moves to cases.md, under a heading, and is pointed at"

d="$(fresh_case still-carries)"
subst "$d/$RULES" '  weakening.** Name the design clause.' '  weakening.** IMPLAUSIBLE: sed -i option is the opposite.'
assert_eq "a rules.md still carrying one needle is reported with exactly one line" \
  'rules.md: still carries "IMPLAUSIBLE: sed -i option"' "$(rules_trim_problems "$d")"

d="$(fresh_case still-carries-wrapped)"
subst "$d/$RULES" '- **How a mutation runs.** Through mutate.sh.' '- **How a mutation runs.** As on HARNESS-014'$'\n''  the work was large.'
assert_eq "a needle reflowed across two lines of rules.md is still seen" \
  'rules.md: still carries "on HARNESS-014 the"' "$(rules_trim_problems "$d")"

d="$(fresh_case cases-missing-one)"; drop "$d/$CASES" 'keeping `-0` out of the coordinate generator'
assert_eq "a needle missing from cases.md is reported, naming it" \
  'cases.md: missing "keeping `-0` out of the coordinate generator"' "$(rules_trim_problems "$d")"

d="$(fresh_case cases-preamble)"
drop "$d/$CASES" 'The backup path is explicit rather than'
subst "$d/$CASES" 'The evidence behind rules in rules.md, moved here.' \
  'The evidence behind rules. The backup path is explicit rather than `$TMPDIR` here.'
assert_eq "a needle only in the preamble, before any ## heading, is reported as not under one" \
  'cases.md: "The backup path is explicit rather than `$TMPDIR`" is not under a ## heading' "$(rules_trim_problems "$d")"

d="$(fresh_case cases-h3)"
{ printf '# Cases\n\n### A sub-heading only\n\nfour private copies in one project drifted apart.\n\n'; cat "$d/$CASES"; } > "$WORK/cases-h3.md"
drop "$WORK/cases-h3.md" 'Four private copies in one project...'
cp "$WORK/cases-h3.md" "$d/$CASES"
assert_eq "a ### heading is not a ## heading" \
  'cases.md: "four private copies in one project drifted apart" is not under a ## heading' "$(rules_trim_problems "$d")"

d="$(fresh_case cases-fenced-h2)"
{ printf '# Cases\n\n```bash\n## a comment, not a heading\n```\n\nfour private copies in one project drifted apart.\n\n'; cat "$d/$CASES"; } > "$WORK/cases-f.md"
drop "$WORK/cases-f.md" 'Four private copies in one project...'
cp "$WORK/cases-f.md" "$d/$CASES"
assert_eq "a ## line inside a fence is not a heading" \
  'cases.md: "four private copies in one project drifted apart" is not under a ## heading' "$(rules_trim_problems "$d")"

d="$(fresh_case cases-absent)"; rm -f "$d/$CASES"
want=""
while IFS= read -r nd; do want="$want${want:+$'\n'}rules.md: points at \"$nd\", not a ## heading of cases.md"; done <<LIST
$FIX_POINTERS
LIST
while IFS= read -r nd; do want="$want${want:+$'\n'}cases.md: missing \"$nd\""; done <<LIST
$NEEDLES
LIST
assert_eq "with no cases.md, each of the fixture's 6 pointers is reported, then each of the 11 needles missing, in Contract order" \
  "$want" "$(rules_trim_problems "$d")"

d="$(fresh_case pointer-moved)"
subst "$d/$RULES" '`tdd-cycle`, `reference/cases.md`, ""The default model" against itself").' '`tdd-cycle`).'
subst "$d/$RULES" '- **Some ecosystems have no in-file split at all** - go.mod.' \
  '- **Some ecosystems have no in-file split at all** - go.mod (`reference/cases.md`).'
assert_eq "a section whose pointer moved to the next section is reported, naming the section" \
  'rules.md: The model each agent runs on does not point at reference/cases.md' "$(rules_trim_problems "$d")"

d="$(fresh_case pointer-bare)"
subst "$d/$RULES" 'The budget (the case: `tdd-cycle`, `reference/cases.md`, "HARNESS-014: eighteen mutations, no defect").' 'The budget (the case: `cases.md`).'
assert_eq "a pointer that names cases.md without reference/ is not the path" \
  'rules.md: Mutation work per story does not point at reference/cases.md' "$(rules_trim_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-4  SKILL.md lists cases.md under ## Details"

d="$(fresh_case skill-elsewhere)"
drop "$d/$SKILL" '- `reference/cases.md`'
printf -- '- `reference/cases.md` - listed in the wrong section\n' >> "$d/$SKILL"
assert_eq "an entry outside ## Details does not count" \
  'SKILL.md: does not list reference/cases.md' "$(rules_trim_problems "$d")"

d="$(fresh_case skill-prose)"
subst "$d/$SKILL" '- `reference/cases.md` - the worked cases behind rules.md' 'See reference/cases.md for the cases.'
assert_eq "a mention in ## Details that is not a list entry does not count" \
  'SKILL.md: does not list reference/cases.md' "$(rules_trim_problems "$d")"

d="$(fresh_case skill-absent)"; rm -f "$d/$SKILL"
assert_eq "a missing SKILL.md is reported once" \
  'SKILL.md: does not list reference/cases.md' "$(rules_trim_problems "$d")"

# ---------------------------------------------------------------------------
# HARNESS-092: every pointer names a heading. Each case is the compliant
# fixture with one site changed, one fault, and the whole report compared.

# pt <text>   The one line the guard prints for a pointer that does not resolve.
pt() { printf 'rules.md: points at "%s", not a ## heading of cases.md' "$1"; }

describe "HARNESS-092 AC-2  a pointer's text is exactly a ## heading"

d="$(fresh_case ptr-typo)"
subst "$d/$RULES" '"Four needles that could not fail")' '"Four needles that could not fial")'
assert_eq "AC-2: a mistyped pointer is reported as one line, quoting its text verbatim" \
  "$(pt 'Four needles that could not fial')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-prefix)"
subst "$d/$RULES" '"Four needles that could not fail")' '"Four needles")'
assert_eq "AC-2: a pointer quoting a strict prefix of a heading does not resolve" \
  "$(pt 'Four needles')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-suffix)"
subst "$d/$RULES" '"Four needles that could not fail")' '"needles that could not fail")'
assert_eq "AC-2: a pointer quoting a strict suffix of a heading does not resolve" \
  "$(pt 'needles that could not fail')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-case)"
subst "$d/$RULES" '"Four needles that could not fail")' '"four needles that could not fail")'
assert_eq "AC-2: a pointer differing from its heading in case only does not resolve" \
  "$(pt 'four needles that could not fail')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-twice)"
subst "$d/$RULES" '"The default model" against itself")' '"The default model" against itselves")'
assert_eq "AC-2: a failing text pointed at twice is reported once per occurrence" \
  "$(pt '"The default model" against itselves')"$'\n'"$(pt '"The default model" against itselves')" \
  "$(rules_trim_problems "$d")"

d="$(fresh_case heading-renamed)"
subst "$d/$CASES" '## Four needles that could not fail' '## Four needles that could not fall'
assert_eq "AC-2: a heading renamed in cases.md leaves its pointer reported, and the needles under it still placed" \
  "$(pt 'Four needles that could not fail')" "$(rules_trim_problems "$d")"

describe "HARNESS-092 AC-3  a wrapped pointer is read joined"

d="$(fresh_case ptr-unwrapped)"
drop "$d/$RULES" 'copies of "a source module"").'
subst "$d/$RULES" '`reference/cases.md`, "Four private' '`reference/cases.md`, "Four private copies of "a source module"").'
assert_eq "AC-3 control: the wrapped pointer's text on one line resolves too" \
  "" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-wrapped-indented)"
subst "$d/$RULES" 'copies of "a source module"").' '    copies of "a source module"").'
assert_eq "AC-3: a wrapped pointer whose second line is indented resolves: lines are trimmed before they are joined" \
  "" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-wrapped-bad)"
subst "$d/$RULES" 'copies of "a source module"").' 'copies of "a source modules"").'
assert_eq "AC-3: a wrapped pointer that does not resolve is one line, its text joined by a single space" \
  "$(pt 'Four private copies of "a source modules"')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-oneline-bad)"
drop "$d/$RULES" 'copies of "a source module"").'
subst "$d/$RULES" '`reference/cases.md`, "Four private' '`reference/cases.md`, "Four private copies of "a source modules"").'
assert_eq "AC-3 control: the same failing text on one line is reported identically" \
  "$(pt 'Four private copies of "a source modules"')" "$(rules_trim_problems "$d")"

describe "HARNESS-092 AC-4  inner quotes and \$ are part of the text"

d="$(fresh_case ptr-inner-open)"
subst "$d/$RULES" '`tdd-cycle`, `reference/cases.md`, ""The default model" against itself")' \
  '`tdd-cycle`, `reference/cases.md`, "The default model" against itself")'
assert_eq "AC-4 control: a pointer that drops the inner opening quote is reported with that exact text" \
  "$(pt 'The default model" against itself')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-inner-close)"
subst "$d/$RULES" 'copies of "a source module"").' 'copies of "a source module").'
assert_eq "AC-4 control: a pointer that drops the inner closing quote ends at the first \") and is reported" \
  "$(pt 'Four private copies of "a source module')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-dollar)"
subst "$d/$RULES" '"A backup that went to an unset $TMPDIR")' '"A backup that went to an unset TMPDIR")'
assert_eq "AC-4 control: the \$ is a character of the heading: a pointer without it does not resolve" \
  "$(pt 'A backup that went to an unset TMPDIR')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-other-var)"
subst "$d/$RULES" '"A backup that went to an unset $TMPDIR")' '"A backup that went to an unset $HOME")'
assert_eq "AC-4 control: a \$ in a pointer is never expanded: \$HOME is reported as written" \
  "$(pt 'A backup that went to an unset $HOME')" "$(rules_trim_problems "$d")"

describe "HARNESS-092 AC-5  a ## line inside a fence is not a heading"

d="$(fresh_case ptr-fenced)"
subst "$d/$RULES" '"Four needles that could not fail")' '"a fenced comment, not a heading")'
assert_eq "AC-5: a pointer naming a ## line inside a fence of cases.md is reported" \
  "$(pt 'a fenced comment, not a heading')" "$(rules_trim_problems "$d")"

d="$(fresh_case ptr-unfenced)"
subst "$d/$RULES" '"Four needles that could not fail")' '"a fenced comment, not a heading")'
subst "$d/$CASES" '```bash' ''
subst "$d/$CASES" '```' ''
assert_eq "AC-5 control: the same ## line with the fence removed resolves" \
  "" "$(rules_trim_problems "$d")"

describe "HARNESS-092 C-2  where the pointer lines stand in a report"

d="$(fresh_case ptr-order)"
subst "$d/$RULES" '  weakening.** Name the design clause.' '  weakening.** IMPLAUSIBLE: sed -i option is the opposite.'
subst "$d/$RULES" '"Four needles that could not fail")' '"Four needles")'
drop "$d/$CASES" 'keeping `-0` out of the coordinate generator'
assert_eq "C-2: a pointer line comes after the rules.md lines and before the cases.md ones" \
  'rules.md: still carries "IMPLAUSIBLE: sed -i option"'$'\n'"$(pt 'Four needles')"$'\n''cases.md: missing "keeping `-0` out of the coordinate generator"' \
  "$(rules_trim_problems "$d")"

summary "rules-trim"
