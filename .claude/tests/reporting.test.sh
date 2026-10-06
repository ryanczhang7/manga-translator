#!/usr/bin/env bash
# Reporting guard: every site that speaks to the user carries the reporting
# rule, and names where the one next action comes from (HARNESS-023).
#
# The sites are prose - rules.md, CLAUDE.md, the command files, lead-po.md - so
# nothing executes them and nothing goes red when one quietly loses the rule.
# This is the shape `tdd-cycle` calls "code no machine you have can execute:
# grep for the shape". It pins that the instruction is PRESENT where the
# orchestrator will read it; it cannot pin that a model FOLLOWS it, and does not
# pretend to (story, Context).
#
# Every needle is a fixed string matched against an EXTRACTED REGION - a
# section, a bullet, a paragraph - never the whole file. That is the point of
# each "present elsewhere" control below: a whole-file grep passes all of them.
# Heading counts are whole-line fixed matches (`grep -cxF`).
#
# `reporting_problems <root>` runs twice over: against REPO_ROOT, where it must
# print nothing, and against fixtures compliant by construction with one site
# regressed, where it must print exactly the one line naming that site. The
# second is what makes the first mean anything - a guard that never fires is
# satisfied by the real tree whatever the real tree says. DV-1 in the story is
# the same probe against a REAL line of the tree, owned by GATES.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# --- the settled values (story Contract: read out, not re-derived) -----------
RULES=".claude/harness/rules.md"
CLAUDE_MD="CLAUDE.md"
LEAD_PO=".claude/agents/lead-po.md"
CMD_DIR=".claude/commands"

RULES_HEADING='# Reporting to the user'
CLAUDE_HEADING='## Reporting to the user'
ORCH_HEADING='## Orchestrating'
REF='`rules.md`, "Reporting to the user"'
CLAUDE_CAP=6

LABELS='Lead with the outcome.
One next action, last.
Plain words.
Working notes stay in the story.
Evidence, not a diagnosis.
Five items, then offer the rest.
Agent-to-agent artefacts are exempt.'

NEXT_LABEL='One next action, last.'
NEXT_NEEDLES='bash scripts/plan.sh after <id>
bash scripts/plan.sh <id>'
EXEMPT_LABEL='Agent-to-agent artefacts are exempt.'
EXEMPT_NEEDLES='## Handoff
## Regressions
docs/wiki/audits/'

# The next-action table, `<command>|<needle>[|<needle>...]`. Quoted delimiter:
# `$1` is a literal two characters here, as it is in the command files.
NEXT_TABLE="$(cat <<'TABLE'
advance-story|bash scripts/plan.sh $1|bash scripts/plan.sh after $1
complete-story|bash scripts/plan.sh after $1
plan-story|bash scripts/plan.sh <id>
status|bash scripts/phase.sh board
audit-mutations|bash scripts/plan.sh after
create-product|/plan-product
plan-product|/setup-environment
setup-environment|bash scripts/plan.sh after
TABLE
)"

# --- region extraction (story Contract, "Region definitions") ----------------
#
# Pure bash: each helper reads the global array LN (one element per line of the
# file, loaded by `load`) and leaves its region in the global R, newline-joined.
# No fork per call. An awk-and-grep version of this file took 109 s on Windows,
# where a fork costs tens of milliseconds and that version made a few thousand
# of them. The matching semantics are the Contract's, unchanged (see its
# amendment note in the story).

# load <file>   LN := the file's lines. mapfile is a builtin.
load() { LN=(); mapfile -t LN < "$1"; }

# blank <line>   Empty or whitespace only.
blank() { [ -z "${1//[[:space:]]/}" ]; }

# exact_count <line>   N := how many lines of LN are exactly <line>: the
# whole-line fixed-string match `grep -cxF` makes, without the fork.
exact_count() {
  local l
  N=0
  for l in "${LN[@]}"; do [ "$l" = "$1" ] && N=$((N + 1)); done
  return 0
}

# rules_section   R := from the line exactly `# Reporting to the user` up to,
# not including, the next column-0 line starting `# ` that is OUTSIDE a ```
# fence, or EOF. Inside a fence `# ` is a shell comment, not a heading. A fence
# line is one whose first non-blank characters are three backticks.
rules_section() {
  local l on=0 fence=0 t tick='```'
  R=""
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "$l" = "$RULES_HEADING" ] && { on=1; R="$l"; }
      continue
    fi
    t="${l#"${l%%[![:space:]]*}"}"
    if [ "${t:0:3}" = "$tick" ]; then
      fence=$((1 - fence)); R="$R"$'\n'"$l"; continue
    fi
    if [ "$fence" = 0 ] && [ "${l:0:2}" = "# " ]; then break; fi
    R="$R"$'\n'"$l"
  done
}

# label_count <label> <region>   N := how many lines of <region> begin
# `- **<label>**`.
label_count() {
  local l p="- **$1**"
  N=0
  while IFS= read -r l; do
    [ "${l:0:${#p}}" = "$p" ] && N=$((N + 1))
  done <<REGION
$2
REGION
  return 0
}

# bullet <label> <region>   R := the FIRST line of <region> starting
# `- **<label>**`, plus the lines after it up to, not including, the next line
# starting `- ` or the next blank line. Empty when there is no such line.
bullet() {
  local l on=0 p="- **$1**"
  R=""
  while IFS= read -r l; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#p}}" = "$p" ] && { on=1; R="$l"; }
      continue
    fi
    [ "${l:0:2}" = "- " ] && break
    blank "$l" && break
    R="$R"$'\n'"$l"
  done <<REGION
$2
REGION
  return 0
}

# h2_section <heading>   R := from the line of LN exactly <heading> up to, not
# including, the next line starting `## `. The heading line is included; empty
# when there is no such line.
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

# last_paragraph   R := drop LN's trailing blank lines, then the lines after
# the last blank line.
last_paragraph() {
  local n=${#LN[@]} s i
  while [ "$n" -gt 0 ] && blank "${LN[n-1]}"; do n=$((n - 1)); done
  s=$n
  while [ "$s" -gt 0 ] && ! blank "${LN[s-1]}"; do s=$((s - 1)); done
  R=""
  for ((i = s; i < n; i++)); do R="$R${R:+$'\n'}${LN[i]}"; done
  return 0
}

# has <needle> <region>   Fixed-string containment. The needle is quoted inside
# the pattern, so nothing in it is a glob; it holds no newline, so a match is
# always within one line of the region - the per-line `grep -F` semantics.
has() {
  case "$2" in *"$1"*) return 0 ;; esac
  return 1
}

# --- the guard ---------------------------------------------------------------

# reporting_problems <root>   One line `<relative-path>: <reason>` per
# violation; silent when the tree under <root> is compliant. Always returns 0:
# the output is the verdict, so a caller compares it against the empty string.
reporting_problems() {
  local root="$1" sec label needle f name row rest line k
  # AC-1, AC-2: rules.md
  if [ ! -f "$root/$RULES" ]; then
    printf '%s: file is missing\n' "$RULES"
  else
    load "$root/$RULES"
    exact_count "$RULES_HEADING"
    if [ "$N" != 1 ]; then
      printf '%s: has %s lines exactly `%s`, wants exactly 1\n' "$RULES" "$N" "$RULES_HEADING"
    else
      rules_section; sec="$R"
      while IFS= read -r label; do
        label_count "$label" "$sec"
        [ "$N" = 1 ] || printf '%s: `%s` has %s bullets beginning `- **%s**`, wants exactly 1\n' \
          "$RULES" "$RULES_HEADING" "$N" "$label"
      done <<LABEL_LIST
$LABELS
LABEL_LIST
      for label in "$NEXT_LABEL" "$EXEMPT_LABEL"; do
        bullet "$label" "$sec"
        [ -n "$R" ] || continue            # already reported as a missing label
        if [ "$label" = "$NEXT_LABEL" ]; then rest="$NEXT_NEEDLES"; else rest="$EXEMPT_NEEDLES"; fi
        while IFS= read -r needle; do
          has "$needle" "$R" \
            || printf '%s: the `- **%s**` bullet does not name `%s`\n' "$RULES" "$label" "$needle"
        done <<NEEDLES
$rest
NEEDLES
      done
    fi
  fi

  # AC-3: CLAUDE.md
  if [ ! -f "$root/$CLAUDE_MD" ]; then
    printf '%s: file is missing\n' "$CLAUDE_MD"
  else
    load "$root/$CLAUDE_MD"
    exact_count "$CLAUDE_HEADING"
    if [ "$N" != 1 ]; then
      printf '%s: has %s lines exactly `%s`, wants exactly 1\n' "$CLAUDE_MD" "$N" "$CLAUDE_HEADING"
    else
      h2_section "$CLAUDE_HEADING"
      case "$R" in *$'\n'*) sec="${R#*$'\n'}" ;; *) sec="" ;; esac   # the body: after the heading
      k=0
      while IFS= read -r line; do blank "$line" || k=$((k + 1)); done <<BODY
$sec
BODY
      [ "$k" -le "$CLAUDE_CAP" ] \
        || printf '%s: `%s` has %s non-blank lines, wants at most %s\n' "$CLAUDE_MD" "$CLAUDE_HEADING" "$k" "$CLAUDE_CAP"
      has "$REF" "$sec" \
        || printf '%s: `%s` does not carry the reference: %s\n' "$CLAUDE_MD" "$CLAUDE_HEADING" "$REF"
    fi
  fi

  # AC-4: every command file, read from the directory, against the table
  for f in "$root/$CMD_DIR"/*.md; do
    [ -f "$f" ] || continue
    name="${f##*/}"; name="${name%.md}"
    row=""
    while IFS= read -r line; do
      [ "${line%%|*}" = "$name" ] && row="$line"
    done <<TABLE
$NEXT_TABLE
TABLE
    if [ -z "$row" ]; then
      printf '%s: has no row in the next-action table\n' "$CMD_DIR/$name.md"
      continue
    fi
    load "$f"; last_paragraph
    has "$REF" "$R" \
      || printf '%s: its last paragraph does not carry the reference: %s\n' "$CMD_DIR/$name.md" "$REF"
    rest="${row#*|}"
    while [ -n "$rest" ]; do
      needle="${rest%%|*}"
      case "$rest" in *'|'*) rest="${rest#*|}" ;; *) rest="" ;; esac
      has "$needle" "$R" \
        || printf '%s: its last paragraph does not name `%s`\n' "$CMD_DIR/$name.md" "$needle"
    done
  done
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    name="${line%%|*}"
    [ -f "$root/$CMD_DIR/$name.md" ] \
      || printf '%s: is in the next-action table but does not exist\n' "$CMD_DIR/$name.md"
  done <<TABLE
$NEXT_TABLE
TABLE

  # AC-5: lead-po.md's ## Orchestrating section
  if [ ! -f "$root/$LEAD_PO" ]; then
    printf '%s: file is missing\n' "$LEAD_PO"
  else
    load "$root/$LEAD_PO"
    h2_section "$ORCH_HEADING"
    if [ -z "$R" ]; then
      printf '%s: has no line exactly `%s`\n' "$LEAD_PO" "$ORCH_HEADING"
    else
      has "$REF" "$R" \
        || printf '%s: its `%s` section does not carry the reference: %s\n' "$LEAD_PO" "$ORCH_HEADING" "$REF"
    fi
  fi
  return 0
}

# --- a compliant fixture, by construction ------------------------------------
# Minimal files that satisfy every rule above. Their wording is nobody's
# contract: GREEN writes the real sites. What matters is that the guard is
# silent on them, so that the single regression each case makes is the ONLY
# thing it can be reporting. Built, not copied: in RED the real tree is what is
# not compliant yet.
#
# Deliberate shapes, each pinning a region rule:
#   - rules.md's section has a ``` fence holding a `# ` comment BEFORE its last
#     bullet, and another `# ` section after it: the section ends at the
#     heading, not at the comment.
#   - CLAUDE.md's section is followed by another `## ` section, and its body is
#     exactly the cap, one line of it whitespace-only.
#   - every command file ends with trailing blank lines, and has an earlier
#     paragraph.
compliant_fixture() { # <dir>
  local d="$1" line name rest
  mkdir -p "$d/.claude/harness" "$d/.claude/agents" "$d/$CMD_DIR"
  cat > "$d/$RULES" <<'EOF'
# Non-negotiables

- A rule about something else.

# Reporting to the user

Messages to the user in chat.

- **Lead with the outcome.** The first line says what is now true.
- **One next action, last.** End with one thing, taken from
  `bash scripts/plan.sh after <id>` once a story closes, or
  `bash scripts/plan.sh <id>` while it is in flight.
- **Plain words.** Say it the way the user would.
- **Working notes stay in the story.** Not in chat.
- **Evidence, not a diagnosis.** Point at the evidence.
- **Five items, then offer the rest.** About five.

```bash
# a shell comment inside a fence, not a heading
bash scripts/plan.sh board
```

- **Agent-to-agent artefacts are exempt.** Story files (`## Handoff`,
  `## Regressions`), audits under `docs/wiki/audits/`, are complete.

# A later section

- Something else.
EOF
  # Body: exactly 6 non-blank lines (the cap), one whitespace-only line that
  # must not count, then a following section that must not be read.
  {
    printf '# Harness\n\n## Context discipline\n\nOther audience.\n\n'
    printf '%s\n\n' "$CLAUDE_HEADING"
    printf 'Lead with what is now true.\n'
    printf 'End with the one next action.\n'
    printf '   \n'
    printf 'Keep notes in the story.\n'
    printf 'Point at the evidence.\n'
    printf 'Never invent a cause.\n'
    printf 'The full rule is %s.\n\n' "$REF"
    printf '## Afterwards\n\nA following section.\nWith lines.\nMany lines.\n'
  } > "$d/$CLAUDE_MD"
  {
    printf -- '---\nname: lead-po\n---\n\n## Interviewing\n\nAsk things.\n\n'
    printf '%s\n\nDispatch.\n\nMessages to the user follow %s.\n\n' "$ORCH_HEADING" "$REF"
    printf '## When you are blocked\n\nSay so.\n'
  } > "$d/$LEAD_PO"
  while IFS= read -r line; do
    name="${line%%|*}"; rest="${line#*|}"
    {
      printf -- '---\ndescription: %s\n---\n\nAn earlier paragraph.\n\n' "$name"
      printf 'Finish by reporting as %s says. Next:\n' "$REF"
      while [ -n "$rest" ]; do
        printf '`%s`\n' "${rest%%|*}"
        case "$rest" in *'|'*) rest="${rest#*|}" ;; *) rest="" ;; esac
      done
      printf '\n\n'
    } > "$d/$CMD_DIR/$name.md"
  done <<TABLE
$NEXT_TABLE
TABLE
}

# fresh_case <name>   A new compliant fixture; echoes its path.
fresh_case() { local d="$WORK/$1"; rm -rf "$d"; compliant_fixture "$d"; printf '%s' "$d"; }

# subst <file> <from> <to>   Replace every fixed-string occurrence. Quoted
# inside the expansion, so neither string is read as a pattern; and no
# `sed -i`, which is GNU-only. <to> may hold a newline, to insert a line.
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

# ---------------------------------------------------------------------------
describe "the real tree"

missing=""
for f in "$RULES" "$CLAUDE_MD" "$LEAD_PO" "$CMD_DIR/advance-story.md"; do
  [ -f "$REPO_ROOT/$f" ] || missing="$missing $f"
done
assert_eq "every file the guard reads exists in this repository" "" "$missing"

assert_eq "reporting_problems over the real tree prints nothing: every site that speaks to the user carries the reporting rule" \
  "" "$(reporting_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "the fixture: compliant by construction"

d="$(fresh_case compliant)"
assert_eq "the compliant fixture is silent (fence comment, following sections, trailing blanks and a cap-sized body all tolerated)" \
  "" "$(reporting_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-1  rules.md: one section, each of the seven labels begins one bullet in it"

d="$(fresh_case ac1-label-deleted)"
drop "$d/$RULES" '- **Plain words.**'
assert_eq "a label deleted from the section is reported, naming rules.md and the label" \
  "$RULES: \`$RULES_HEADING\` has 0 bullets beginning \`- **Plain words.**\`, wants exactly 1" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac1-label-outside)"
drop "$d/$RULES" '- **Evidence, not a diagnosis.**'
subst "$d/$RULES" '- Something else.' '- **Evidence, not a diagnosis.** In the wrong section.'
assert_eq "a label present only in the following # section is reported: the section ends at the next heading" \
  "$RULES: \`$RULES_HEADING\` has 0 bullets beginning \`- **Evidence, not a diagnosis.**\`, wants exactly 1" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac1-label-twice)"
subst "$d/$RULES" '- **Plain words.** Say it the way the user would.' \
  '- **Plain words.** Say it the way the user would.
- **Plain words.** And again.'
assert_eq "a label beginning two bullets is reported: exactly one, not at least one" \
  "$RULES: \`$RULES_HEADING\` has 2 bullets beginning \`- **Plain words.**\`, wants exactly 1" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac1-fence-unfenced)"
drop "$d/$RULES" '```'
assert_eq "with the fence markers removed, the \`# \` comment IS a heading and the last bullet falls outside the section" \
  "$RULES: \`$RULES_HEADING\` has 0 bullets beginning \`- **$EXEMPT_LABEL**\`, wants exactly 1" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac1-heading-missing)"
subst "$d/$RULES" "$RULES_HEADING" '## Reporting to the user'
assert_eq "rules.md without the exact top-level heading is one line, not one per label" \
  "$RULES: has 0 lines exactly \`$RULES_HEADING\`, wants exactly 1" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac1-heading-twice)"
subst "$d/$RULES" '# A later section' "$RULES_HEADING"
assert_eq "rules.md with the heading twice is reported" \
  "$RULES: has 2 lines exactly \`$RULES_HEADING\`, wants exactly 1" \
  "$(reporting_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-2  rules.md: the two bullets name their needles, in the bullet itself"

# Each needle is moved, not deleted: it stays in the file, so a whole-file grep
# would pass every one of these.
d="$(fresh_case ac2-after-moved)"
subst "$d/$RULES" '`bash scripts/plan.sh after <id>` once a story closes, or' 'once a story closes, or'
subst "$d/$RULES" 'Say it the way the user would.' 'Say it the way the user would, `bash scripts/plan.sh after <id>`.'
assert_eq "\`bash scripts/plan.sh after <id>\` in another bullet, not the next-action one, is reported" \
  "$RULES: the \`- **$NEXT_LABEL**\` bullet does not name \`bash scripts/plan.sh after <id>\`" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac2-id-moved)"
subst "$d/$RULES" '`bash scripts/plan.sh <id>` while it is in flight.' 'while it is in flight.'
subst "$d/$RULES" 'Messages to the user in chat.' 'Messages to the user in chat, after `bash scripts/plan.sh <id>`.'
assert_eq "\`bash scripts/plan.sh <id>\` only in the intro is reported (and is not satisfied by the \`after <id>\` needle beside it)" \
  "$RULES: the \`- **$NEXT_LABEL**\` bullet does not name \`bash scripts/plan.sh <id>\`" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac2-id-after-blank)"
subst "$d/$RULES" '  `bash scripts/plan.sh <id>` while it is in flight.' '
  `bash scripts/plan.sh <id>` while it is in flight.'
assert_eq "a needle after a blank line is outside the bullet: a bullet ends at the first blank line" \
  "$RULES: the \`- **$NEXT_LABEL**\` bullet does not name \`bash scripts/plan.sh <id>\`" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac2-handoff-moved)"
subst "$d/$RULES" 'Story files (`## Handoff`,' 'Story files ('
subst "$d/$RULES" 'Point at the evidence.' 'Point at the evidence, as in `## Handoff`.'
assert_eq "\`## Handoff\` in another bullet, not the exemption one, is reported" \
  "$RULES: the \`- **$EXEMPT_LABEL**\` bullet does not name \`## Handoff\`" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac2-regressions-moved)"
subst "$d/$RULES" '  `## Regressions`), audits' '  ), audits'
subst "$d/$RULES" 'A rule about something else.' 'A rule about something else, `## Regressions`.'
assert_eq "\`## Regressions\` only in another # section is reported" \
  "$RULES: the \`- **$EXEMPT_LABEL**\` bullet does not name \`## Regressions\`" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac2-audits-moved)"
subst "$d/$RULES" 'audits under `docs/wiki/audits/`, are complete.' 'audits are complete.'
subst "$d/$RULES" '- Something else.' '- Something else, under `docs/wiki/audits/`.'
assert_eq "\`docs/wiki/audits/\` only after the section is reported" \
  "$RULES: the \`- **$EXEMPT_LABEL**\` bullet does not name \`docs/wiki/audits/\`" \
  "$(reporting_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3  CLAUDE.md: one short section that points at rules.md"

d="$(fresh_case ac3-seven-lines)"
subst "$d/$CLAUDE_MD" 'Never invent a cause.' 'Never invent a cause.
And one sentence too many.'
assert_eq "a 7-line body is reported with its count" \
  "$CLAUDE_MD: \`$CLAUDE_HEADING\` has 7 non-blank lines, wants at most $CLAUDE_CAP" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac3-no-reference)"
drop "$d/$CLAUDE_MD" "$REF"
subst "$d/$CLAUDE_MD" 'A following section.' "A following section, $REF."
assert_eq "a body without the reference is reported, though the next section carries it" \
  "$CLAUDE_MD: \`$CLAUDE_HEADING\` does not carry the reference: $REF" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac3-heading-missing)"
subst "$d/$CLAUDE_MD" "$CLAUDE_HEADING" '### Reporting to the user'
assert_eq "CLAUDE.md without the exact heading is one line" \
  "$CLAUDE_MD: has 0 lines exactly \`$CLAUDE_HEADING\`, wants exactly 1" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac3-heading-twice)"
subst "$d/$CLAUDE_MD" '## Afterwards' "$CLAUDE_HEADING"
assert_eq "CLAUDE.md with the heading twice is reported" \
  "$CLAUDE_MD: has 2 lines exactly \`$CLAUDE_HEADING\`, wants exactly 1" \
  "$(reporting_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-4  every command's last paragraph carries the reference and its next-action needles"

d="$(fresh_case ac4-needle-earlier)"
F="$d/$CMD_DIR/complete-story.md"
drop "$F" 'bash scripts/plan.sh after $1'
subst "$F" 'An earlier paragraph.' 'An earlier paragraph, `bash scripts/plan.sh after $1`.'
assert_eq "a needle only in an earlier paragraph is reported" \
  "$CMD_DIR/complete-story.md: its last paragraph does not name \`bash scripts/plan.sh after \$1\`" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac4-reference-earlier)"
F="$d/$CMD_DIR/status.md"
subst "$F" "Finish by reporting as $REF says. Next:" 'Finish by reporting. Next:'
subst "$F" 'An earlier paragraph.' "An earlier paragraph, $REF."
assert_eq "the reference only in an earlier paragraph is reported" \
  "$CMD_DIR/status.md: its last paragraph does not carry the reference: $REF" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac4-advance-independent)"
F="$d/$CMD_DIR/advance-story.md"
drop "$F" '`bash scripts/plan.sh $1`'
assert_eq "advance-story's two needles are independent: \`plan.sh after \$1\` alone does not satisfy \`plan.sh \$1\`" \
  "$CMD_DIR/advance-story.md: its last paragraph does not name \`bash scripts/plan.sh \$1\`" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac4-no-row)"
printf 'A new command.\n\nReport as %s says.\n' "$REF" > "$d/$CMD_DIR/deploy.md"
assert_eq "a command file with no table row is reported, naming it: the set is read from the directory" \
  "$CMD_DIR/deploy.md: has no row in the next-action table" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac4-no-file)"
rm -f "$d/$CMD_DIR/status.md"
assert_eq "a table row with no command file is reported, naming it" \
  "$CMD_DIR/status.md: is in the next-action table but does not exist" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac4-no-trailing-blank)"
F="$d/$CMD_DIR/plan-story.md"
printf 'Intro.\n\nFirst paragraph `bash scripts/plan.sh <id>`.\n\nReport as %s says.' "$REF" > "$F"
assert_eq "with no trailing newline the last paragraph is still the last one, and the needle above it does not count" \
  "$CMD_DIR/plan-story.md: its last paragraph does not name \`bash scripts/plan.sh <id>\`" \
  "$(reporting_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-5  lead-po.md's ## Orchestrating section carries the reference"

d="$(fresh_case ac5-other-section)"
drop "$d/$LEAD_PO" "$REF"
subst "$d/$LEAD_PO" 'Say so.' "Say so, as $REF says."
assert_eq "the reference only in another section is reported" \
  "$LEAD_PO: its \`$ORCH_HEADING\` section does not carry the reference: $REF" \
  "$(reporting_problems "$d")"

d="$(fresh_case ac5-no-section)"
subst "$d/$LEAD_PO" "$ORCH_HEADING" '## Orchestration'
assert_eq "a lead-po.md with no \`## Orchestrating\` section is reported" \
  "$LEAD_PO: has no line exactly \`$ORCH_HEADING\`" \
  "$(reporting_problems "$d")"

summary "reporting"
