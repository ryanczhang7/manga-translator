#!/usr/bin/env bash
# Every docs/ path the harness tells an agent to read is either delivered by the
# refresh or declared to be one the project writes (HARNESS-040, AC-5).
#
# Issue #104, Symptom A. `/audit-mutations` and the mutation-tester agent name
# docs/wiki/audits/TEMPLATE.md; the refresh left all of docs/** alone; a project
# vendored before the template existed never received it, and nothing said so.
# The refresh now ADDS what .claude/harness/docs-shipped.conf lists as `ship`.
# This suite is what stops the NEXT template from repeating the defect: a
# command, agent or skill that names a docs/ path the conf neither ships nor
# declares `written` is reported here, by file and by path.
#
# The sites are prose, so nothing executes them - the shape `tdd-cycle` calls
# "code no machine you have can execute: grep for the shape". A static check is
# the correct instrument, not a substitute for a test that could have been
# written instead. Modelled on policy.test.sh: `shipped_docs_problems <root>` is
# run over REPO_ROOT, where it must print nothing, and over a fixture built
# compliant by construction with one site regressed, where it must print exactly
# one line naming it. The second is what makes the first mean anything. DV-3 in
# the story is the same probe against a REAL line of the tree, owned by GATES.
#
# What a literal reference is (the story's Contract, C-6): every token matching
# the ERE `docs/[A-Za-z0-9_./-]*` with one trailing `.` stripped; a token ending
# in `/` is a PATTERN (`docs/wiki/audits/<scope>-<date>.md`, `docs/wiki/design/**`,
# `docs/backlog/stories/*.md` and `docs/wiki/` all stop at the slash) and is
# skipped. A reference is counted once per (file, path) pair: a file naming the
# same path twice is one reference and, if uncovered, one problem line.
#
# Written limit, asserted below as AC-5(d): a path under a `written` DIRECTORY
# entry is covered whatever its basename, so a template dropped under
# docs/backlog/epics/ or docs/backlog/stories/ is invisible to this rule.
#
# Portable awk only (CI runs mawk): no gensub, no --re-interval, no \<.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

CONF=".claude/harness/docs-shipped.conf"

# --- the rule ----------------------------------------------------------------

# scanned_files <root>   The files whose docs/ references are judged, relative
# to <root>, sorted: .claude/commands/*.md, .claude/agents/*.md and every .md
# under .claude/skills. README.md and CLAUDE.md describe the harness rather than
# instruct an agent, and are deliberately not scanned.
scanned_files() {
  local root="$1" f
  {
    for f in "$root"/.claude/commands/*.md "$root"/.claude/agents/*.md; do
      [ -f "$f" ] && printf '%s\n' "${f#"$root"/}"
    done
    if [ -d "$root/.claude/skills" ]; then
      ( cd "$root" && find .claude/skills -type f -name '*.md' )
    fi
  } | LC_ALL=C sort
}

# literal_refs <root>   One line `<file> <path>` per distinct literal reference
# (C-6), in scanned-file order.
literal_refs() {
  local root="$1" f
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    grep -oE 'docs/[A-Za-z0-9_./-]*' "$root/$f" 2>/dev/null \
      | awk -v file="$f" '{ sub(/\.$/, ""); if ($0 ~ /\/$/) next; if (!seen[$0]++) print file " " $0 }'
  done <<SCANNED
$(scanned_files "$root")
SCANNED
}

# conf_entries <root>   The conf as `<lineno> <kind> <path>` lines: comments
# and blank lines dropped, fields `|`-separated, leading and trailing space
# trimmed - floors.conf's grammar.
conf_entries() {
  awk -F'|' '
    { line = $0; sub(/^[ \t]+/, "", line) }
    line == "" || substr(line, 1, 1) == "#" { next }
    {
      k = $1; p = $2
      gsub(/^[ \t]+|[ \t\r]+$/, "", k); gsub(/^[ \t]+|[ \t\r]+$/, "", p)
      print NR " " k " " p
    }
  ' "$1/$CONF"
}

# shipped_docs_problems <root>   One line `<relative-path>: <reason>` per
# violation; silent when the tree under <root> is compliant. Always returns 0:
# the output is the verdict, so a caller compares it against the empty string.
#   R1  every `ship` path is a regular file under <root>
#   R2  every literal reference equals a `ship` path, equals a `written` file,
#       or lies under a `written` directory (an entry ending in `/`)
#   R3  no `ship` path lies under a `written` directory
#   R4  a kind other than `ship` or `written` is reported, naming the line
shipped_docs_problems() {
  local root="$1" entries ships written n k p f r d covered
  if [ ! -f "$root/$CONF" ]; then
    printf '%s: file is missing\n' "$CONF"
    return 0
  fi
  entries="$(conf_entries "$root")"
  ships=""; written=""
  while read -r n k p; do
    [ -n "$n" ] || continue
    case "$k" in
      ship)    ships="$ships$p
" ;;
      written) written="$written$p
" ;;
      *) printf '%s: line %s: unknown kind `%s` (expected ship or written)\n' "$CONF" "$n" "$k" ;;
    esac
  done <<ENTRIES
$entries
ENTRIES

  while IFS= read -r p; do
    [ -n "$p" ] || continue
    [ -f "$root/$p" ] || printf '%s: ship path %s does not exist\n' "$CONF" "$p"
    while IFS= read -r d; do
      case "$d" in
        */) case "$p" in "$d"*) printf '%s: ship path %s lies under written directory %s\n' "$CONF" "$p" "$d" ;; esac ;;
      esac
    done <<WRITTEN
$written
WRITTEN
  done <<SHIPS
$ships
SHIPS

  while read -r f r; do
    [ -n "$f" ] || continue
    covered=""
    while IFS= read -r p; do
      [ "$p" = "$r" ] && covered=1
    done <<SHIPS
$ships
SHIPS
    while IFS= read -r d; do
      [ -n "$d" ] || continue
      case "$d" in
        */) case "$r" in "$d"*) covered=1 ;; esac ;;
        *)  [ "$d" = "$r" ] && covered=1 ;;
      esac
    done <<WRITTEN
$written
WRITTEN
    [ -n "$covered" ] \
      || printf '%s: names %s, which docs-shipped.conf neither ships nor declares written\n' "$f" "$r"
  done <<REFS
$(literal_refs "$root")
REFS
  return 0
}

# --- a compliant fixture, by construction ------------------------------------
# One command, one agent, one skill (and a skill reference file one level
# down), and a conf. Their wording is nobody's contract. Every extraction edge
# C-6 names is present and covered, so that silence here means the edges are
# handled: a trailing full stop, a path named twice, a `<scope>` pattern, a
# `*` pattern, a `**` pattern, a bare directory, and a file under a `written`
# directory entry.
#
# The fixture's `ship` file is docs/wiki/templates/audit.md, NOT the real
# tree's docs/wiki/audits/TEMPLATE.md, on purpose: AC-5(d) adds a `written`
# directory covering docs/wiki/audits/, and with the ship file inside it R3
# (ship under written) would fire and the limit case could not print nothing.
AUDIT_CMD=".claude/commands/audit-mutations.md"
compliant_fixture() { # <dir>
  local d="$1"
  mkdir -p "$d/.claude/commands" "$d/.claude/agents" "$d/.claude/harness" \
           "$d/.claude/skills/story-authoring/reference" "$d/docs/wiki/templates"
  printf 'Write the audit to the structure in `docs/wiki/templates/audit.md`.\n' > "$d/$AUDIT_CMD"
  printf 'Save it as docs/wiki/audits/<scope>-<date>.md, beside docs/wiki/.\n' >> "$d/$AUDIT_CMD"
  printf 'Read docs/wiki/product-brief.md. Then docs/wiki/stack.md.\nAgain: docs/wiki/stack.md\n' \
    > "$d/.claude/agents/lead-po.md"
  printf 'Stories live at docs/backlog/stories/*.md; design at docs/wiki/design/**.\n' \
    > "$d/.claude/skills/story-authoring/SKILL.md"
  printf 'For example `docs/backlog/epics/EPIC-03.md`.\n' \
    > "$d/.claude/skills/story-authoring/reference/epics.md"
  printf 'upstream audit template\n' > "$d/docs/wiki/templates/audit.md"
  cat > "$d/$CONF" <<'FIXTURE_CONF'
# a fixture docs-shipped.conf
ship    | docs/wiki/templates/audit.md
written | docs/wiki/product-brief.md
  written|docs/wiki/stack.md
written | docs/backlog/epics/
FIXTURE_CONF
}

# fresh_case <name>   A new compliant fixture; echoes its path.
fresh_case() { local d="$WORK/$1"; rm -rf "$d"; compliant_fixture "$d"; printf '%s' "$d"; }

# ---------------------------------------------------------------------------
describe "the real tree (AC-5(a))"

# The needle is live: the extraction finds the references C-6 measured on this
# tree (24 distinct file-and-path pairs at release 83). A floor, because a later
# command may add one; an extraction that matched nothing would otherwise make
# the next assertion pass vacuously.
n_refs="$(literal_refs "$REPO_ROOT" | awk 'END { print NR }')"
if [ "$n_refs" -ge 24 ]; then
  _ok "the rule extracts at least 24 literal docs/ references from this tree"
else
  _bad "the rule extracts at least 24 literal docs/ references from this tree" "extracted $n_refs"
fi
assert_eq "shipped_docs_problems over the real tree prints nothing: every docs/ path a command, agent or skill names is shipped or declared written" \
  "" "$(shipped_docs_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "the fixture: compliant by construction, then one site regressed (AC-5(b))"

d="$(fresh_case compliant)"
assert_eq "the compliant fixture is silent" "" "$(shipped_docs_problems "$d")"
assert_eq "and its extraction is exactly the literal references, once per file, patterns skipped" \
  ".claude/agents/lead-po.md docs/wiki/product-brief.md
.claude/agents/lead-po.md docs/wiki/stack.md
.claude/commands/audit-mutations.md docs/wiki/templates/audit.md
.claude/skills/story-authoring/reference/epics.md docs/backlog/epics/EPIC-03.md" \
  "$(literal_refs "$d")"

d="$(fresh_case regressed-one)"
printf 'Score each mutant against `docs/wiki/audits/CHECKLIST.md`.\n' >> "$d/$AUDIT_CMD"
assert_eq "a command naming a path on neither list prints exactly one line, naming that file and that path" \
  "$AUDIT_CMD: names docs/wiki/audits/CHECKLIST.md, which docs-shipped.conf neither ships nor declares written" \
  "$(shipped_docs_problems "$d")"

d="$(fresh_case regressed-twice)"
printf 'See docs/wiki/audits/CHECKLIST.md, and docs/wiki/audits/CHECKLIST.md again.\n' >> "$d/$AUDIT_CMD"
assert_eq "naming it twice in one file is still one line" \
  "$AUDIT_CMD: names docs/wiki/audits/CHECKLIST.md, which docs-shipped.conf neither ships nor declares written" \
  "$(shipped_docs_problems "$d")"

d="$(fresh_case regressed-agent)"
printf 'Follow docs/wiki/audits/CHECKLIST.md.\n' >> "$d/.claude/agents/lead-po.md"
assert_eq "an agent file is scanned" \
  ".claude/agents/lead-po.md: names docs/wiki/audits/CHECKLIST.md, which docs-shipped.conf neither ships nor declares written" \
  "$(shipped_docs_problems "$d")"

d="$(fresh_case regressed-skill)"
printf 'Copy docs/wiki/design/tokens.md.\n' >> "$d/.claude/skills/story-authoring/reference/epics.md"
assert_eq "a skill reference file two levels down is scanned" \
  ".claude/skills/story-authoring/reference/epics.md: names docs/wiki/design/tokens.md, which docs-shipped.conf neither ships nor declares written" \
  "$(shipped_docs_problems "$d")"

# Out of scope, pinned cheaply: README.md and CLAUDE.md describe the harness and
# are not scanned.
d="$(fresh_case readme-not-scanned)"
printf 'See docs/wiki/audits/CHECKLIST.md.\n' > "$d/README.md"
printf 'See docs/wiki/audits/CHECKLIST.md.\n' > "$d/CLAUDE.md"
assert_eq "README.md and CLAUDE.md are not scanned" "" "$(shipped_docs_problems "$d")"

# ---------------------------------------------------------------------------
describe "the conf contradicting the tree, or itself (AC-5(c), R3, R4)"

d="$(fresh_case ghost-ship)"
rm -f "$d/docs/wiki/templates/audit.md"
assert_eq "a ship entry whose file is deleted prints exactly one line, naming the conf and the missing path" \
  "$CONF: ship path docs/wiki/templates/audit.md does not exist" "$(shipped_docs_problems "$d")"

d="$(fresh_case ship-under-written)"
mkdir -p "$d/docs/backlog/epics"
printf 'template\n' > "$d/docs/backlog/epics/TEMPLATE.md"
printf 'ship | docs/backlog/epics/TEMPLATE.md\n' >> "$d/$CONF"
assert_eq "a ship path under a written directory is the conf contradicting itself" \
  "$CONF: ship path docs/backlog/epics/TEMPLATE.md lies under written directory docs/backlog/epics/" \
  "$(shipped_docs_problems "$d")"

d="$(fresh_case unknown-kind)"
printf 'shipped | docs/wiki/templates/audit.md\n' >> "$d/$CONF"
assert_eq "an unknown kind is reported, naming its line" \
  "$CONF: line 6: unknown kind \`shipped\` (expected ship or written)" "$(shipped_docs_problems "$d")"

d="$(fresh_case no-conf)"
rm -f "$d/$CONF"
assert_eq "a tree with no conf at all says so in one line" \
  "$CONF: file is missing" "$(shipped_docs_problems "$d")"

# ---------------------------------------------------------------------------
describe "the written limit, recorded rather than hidden (AC-5(d))"

# The regressed command from AC-5(b), plus a `written` DIRECTORY entry covering
# its directory: a file under a written directory is covered whatever its name,
# so this prints nothing. That is the rule's limit (C-5), and this assertion is
# where it is written down. If a later story narrows directory entries, this is
# the line that must change - deliberately.
d="$(fresh_case written-limit)"
printf 'Score each mutant against `docs/wiki/audits/CHECKLIST.md`.\n' >> "$d/$AUDIT_CMD"
printf 'written | docs/wiki/audits/\n' >> "$d/$CONF"
assert_eq "a path under a written directory is covered whatever its basename: the limit" \
  "" "$(shipped_docs_problems "$d")"

summary "shipped-docs"
