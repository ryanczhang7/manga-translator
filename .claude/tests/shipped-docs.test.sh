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

# --- what a suite may read (HARNESS-106) -------------------------------------
# docs/ is the project's own, never the harness's: docs-shipped.conf declares
# docs/backlog/stories/ written, and a refresh ships no story. A suite that
# reads under the real checkout's docs/ therefore reads, in a consumer, a file
# that is absent or is somebody else's (HARNESS-106 Context: boundaries read
# four upstream story files and failed four assertions in a consumer). A
# fixture a suite needs lives under .claude/tests/fixtures/, which ships.
#
# suite_docs_files <root>   The scanned files, relative to <root>, in LC_ALL=C
# name order: every <root>/.claude/tests/*.sh, top level only (the suites,
# _lib.sh, _spawns.sh), except a file whose whole name is project-*.test.sh
# (HARNESS-109). That is a consuming project's own suite: upstream does not
# ship it, a refresh keeps it, and it may read its own project's docs/. A
# project-*.sh that is not a .test.sh, and a suite merely containing the word
# (my-project-x.test.sh), are still scanned.
#
# suite_docs_reads <root>   One line `<file>:<line number>` per line of a
# scanned file that is not a whole-line comment (first non-blank character `#`)
# and matches SDR_RE: one of the two names _lib.sh gives the real checkout,
# REPO_ROOT or TESTS_DIR/../.., then optionally `%/` (the root with one
# trailing slash stripped, still the root; nothing else may follow the `%`),
# then any of `}` and `"` (so the braced and the quoted-root spellings count),
# then one or more `/` (the shell collapses a doubled slash), then docs as a
# whole path component: followed by end of line or by a character that cannot
# continue a file name - anything but a letter, a digit, `_`, `.` or `-` - so
# an unquoted $(ls ...docs) ends at `)` as a quoted one ends at `"`, and
# docs-shipped.conf, docsy/, docs_old/ and docs.bak/ never match (HARNESS-107).
# Silent when nothing reads there.
# No exception for a `ship` entry either: docs/wiki/audits/TEMPLATE.md is added
# only where the project has none, so in a consumer it is the consumer's.
#
# Written limit: the rule reads text, not data flow. A path built in a variable
# first (d="$REPO_ROOT", then "$d/docs/..."), a cd "$REPO_ROOT" followed by a
# relative docs/..., and git -C "$REPO_ROOT" show HEAD:docs/... are not seen.
# And it trusts the name: an upstream suite named project-*.test.sh would
# escape it, and nothing checks that upstream ships none (HARNESS-109, C-1).
# Nor is every direct spelling seen. Among those that are not: an expansion of
# the root other than `%/` ("${REPO_ROOT:?}/docs/x"), a `/./` between the root
# and docs ("$REPO_ROOT/./docs/a"), and a docs quoted on its own
# ("$REPO_ROOT"/"docs"/a). None occurs in the tree. The assertion headed
# HARNESS-110 below pins these three, so widening the pattern means moving its
# line and correcting this sentence (HARNESS-110, D-1).
#
# This suite is one of the files it scans, and its fixtures below hold
# offending lines as data. So the two root names are spelled in pieces
# wherever /docs follows them, here and in the fixtures; no upstream file is
# exempted by name, this suite included. The real-tree assertion is the check
# that this was done.
# [.] rather than \. because awk -v processes backslash escapes.
SDR_RE='(REPO''_ROOT|TESTS''_DIR/[.][.]/[.][.])(%/)?[}"]*/+docs([^A-Za-z0-9_.-]|$)'
suite_docs_files() {
  local root="$1" f
  for f in "$root"/.claude/tests/*.sh; do
    [ -f "$f" ] || continue
    case "${f##*/}" in project-*.test.sh) continue ;; esac
    printf '%s\n' "${f#"$root"/}"
  done | LC_ALL=C sort
}
suite_docs_reads() {
  local root="$1" f
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    awk -v file="$f" -v re="$SDR_RE" '
      { l = $0; sub(/^[ \t]+/, "", l) }
      substr(l, 1, 1) == "#" { next }
      $0 ~ re { print file ":" FNR }
    ' "$root/$f"
  done <<SUITES
$(suite_docs_files "$root")
SUITES
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

# ---------------------------------------------------------------------------
describe "no suite reads under the real checkout's docs/ (HARNESS-106 AC-3)"

assert_eq "HARNESS-106 AC-3: suite_docs_reads over the real tree prints nothing: no suite line reads the project's own docs, which a consumer does not share" \
  "" "$(suite_docs_reads "$REPO_ROOT")"
n_suites="$(suite_docs_files "$REPO_ROOT" | awk 'END { print NR }')"
if [ "$n_suites" -ge 30 ]; then
  _ok "HARNESS-106 AC-3: the rule scans at least 30 shell files of the real tree's .claude/tests"
else
  _bad "HARNESS-106 AC-3: the rule scans at least 30 shell files of the real tree's .claude/tests" "scanned $n_suites"
fi

# The fixture of C-5. The root names are held in pieces (see SDR_RE above), so
# no line of this suite is itself an offending line.
SDR_R='REPO''_ROOT'; SDR_T='TESTS''_DIR'
g="$WORK/suite-reads"; mkdir -p "$g/.claude/tests"
printf '%s\n' "X=\"\$$SDR_R/docs\"" > "$g/.claude/tests/_lib.sh"
{
  printf '%s\n' '#!/usr/bin/env bash'
  printf '%s\n' "# cat \"\$$SDR_R/docs/backlog/stories/T-1.md\""
  printf '%s\n' "cat \"\$$SDR_R/docs/backlog/stories/T-1.md\""
  printf '%s\n' "f=\"\${$SDR_R}/docs/wiki/architecture.md\""
  printf '%s\n' "ls \"\$$SDR_R\"/docs/backlog"
  printf '%s\n' 'cat "$FIX/docs/backlog/stories/T-1.md" "$root/docs/wiki/stack.md"'
  printf '%s\n' "cat \"\$$SDR_R/.claude/harness/docs-shipped.conf\""
  printf '%s\n' "cat \"\$$SDR_T/../../docs/backlog/README.md\""
  printf '%s\n' "n=\$(ls \$$SDR_R/docs)"
  printf '%s\n' "f=\"\${$SDR_R%/}/docs/a\""
  printf '%s\n' "f=\"\$$SDR_R//docs/a\""
  printf '%s\n' "cat \"\$$SDR_R/docs-shipped.conf\""
  printf '%s\n' "ls \"\$$SDR_R/docsy/a\""
  printf '%s\n' "ls \"\$$SDR_R/docs_old/a\""
  printf '%s\n' "ls \"\$$SDR_R/docs.bak/a\""
} > "$g/.claude/tests/a.test.sh"
assert_eq "HARNESS-106 AC-3, HARNESS-107 AC-3: a fixture holding each spelling, in a suite and in _lib.sh, gets one file-and-line per reading line - the unquoted command substitution, the %/-stripped root and the doubled slash included - and none for the comment, the other roots, docs-shipped.conf or a docs-prefixed name" \
  ".claude/tests/_lib.sh:1
.claude/tests/a.test.sh:3
.claude/tests/a.test.sh:4
.claude/tests/a.test.sh:5
.claude/tests/a.test.sh:8
.claude/tests/a.test.sh:9
.claude/tests/a.test.sh:10
.claude/tests/a.test.sh:11" "$(suite_docs_reads "$g")"
: > "$g/.claude/tests/_lib.sh"
awk 'NR != 3 && NR != 4 && NR != 5 && NR != 8 && NR != 9 && NR != 10 && NR != 11' "$g/.claude/tests/a.test.sh" > "$g/a.tmp" \
  && mv "$g/a.tmp" "$g/.claude/tests/a.test.sh"
assert_eq "HARNESS-106 AC-3, HARNESS-107 AC-3: twin: the same fixture with only the comment, the other roots, docs-shipped.conf and the docs-prefixed names left prints nothing" \
  "" "$(suite_docs_reads "$g")"

# ---------------------------------------------------------------------------
describe "a project's own suites are not scanned (HARNESS-109)"

# Each fixture file holds the two shapes of the consumer's reading lines (the
# story's Context), as lines 2 and 3. The root name is spelled in pieces with
# $SDR_R from the block above, so no line of this suite is an offending line.
p="$WORK/project-suites"; mkdir -p "$p/.claude/tests"
{
  printf '%s\n' '#!/usr/bin/env bash'
  printf '%s\n' "DOC=\"\$$SDR_R/docs/wiki/x.md\""
  printf '%s\n' "HANDOFF=\"\$$SDR_R/docs/wiki/handoff\""
} > "$p/.claude/tests/project-x.test.sh"
assert_eq "HARNESS-109 AC-1: a consumer's own project-x.test.sh reading its project's docs/ is not reported" \
  "" "$(suite_docs_reads "$p")"
for n in x.test.sh project-x.sh my-project-x.test.sh; do
  cp "$p/.claude/tests/project-x.test.sh" "$p/.claude/tests/$n"
done
assert_eq "HARNESS-109 AC-2: the same lines in an upstream-named suite, a project- helper without .test.sh and a suite with project- not at the start are each still reported, and project-x.test.sh still is not" \
  ".claude/tests/my-project-x.test.sh:2
.claude/tests/my-project-x.test.sh:3
.claude/tests/project-x.sh:2
.claude/tests/project-x.sh:3
.claude/tests/x.test.sh:2
.claude/tests/x.test.sh:3" "$(suite_docs_reads "$p")"
assert_eq "HARNESS-109 AC-1, AC-2: suite_docs_files lists the three neighbours and leaves out only the top-level project-x.test.sh" \
  ".claude/tests/my-project-x.test.sh
.claude/tests/project-x.sh
.claude/tests/x.test.sh" "$(suite_docs_files "$p")"

# ---------------------------------------------------------------------------
describe "the written limit: direct spellings the rule does not see (HARNESS-110)"

# The three direct spellings the "Written limit" paragraph above SDR_RE names,
# as lines 2-4, and one plain read as line 5, so the same output shows the file
# was scanned and the rule fired. The root name is spelled in pieces with $SDR_R
# from the HARNESS-106 block, so no line of this suite is an offending line. A
# story that widens SDR_RE to see one of lines 2-4 turns this red: move that
# line to the reads fixture above and correct the paragraph.
q="$WORK/suite-limit"; mkdir -p "$q/.claude/tests"
{
  printf '%s\n' '#!/usr/bin/env bash'
  printf '%s\n' "rm -rf \"\${$SDR_R:?}/docs/x\""
  printf '%s\n' "cat \"\$$SDR_R/./docs/a\""
  printf '%s\n' "cat \"\$$SDR_R\"/\"docs\"/a"
  printf '%s\n' "cat \"\$$SDR_R/docs/a\""
} > "$q/.claude/tests/b.test.sh"
assert_eq "HARNESS-110 AC-1: the written limit: an expansion of the root other than %/, a /./ before docs and a separately quoted docs are not reported, while the plain read beside them in the same file is" \
  ".claude/tests/b.test.sh:5" "$(suite_docs_reads "$q")"

summary "shipped-docs"
