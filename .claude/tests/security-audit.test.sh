#!/usr/bin/env bash
# /security-audit and Cloudflare's vendored skill behind it (HARNESS-043).
#
# Three things are pinned here, all mechanical (the story's C-8: nothing here is
# an oracle-free judgement):
#
#   AC-1  .claude/skills/security-audit/ is a copy of one upstream commit,
#         complete and unmodified: UPSTREAM names the commit, every file it
#         lists exists with exactly the listed git blob, and nothing else is
#         there. `vendor_problems <dir>` prints one `<path>: <reason>` line per
#         violation and nothing when clean.
#   AC-2  .claude/commands/security-audit.md carries C-3's needles - the
#         harness's defaults and its three honesty statements - byte for byte.
#         `command_problems <file>` prints one line per missing needle.
#   AC-4  scripts/refresh-harness.sh delivers both into a project, through the
#         existing `.claude/skills` and `.claude/commands` replace.
#
# (AC-3 lives in reporting.test.sh and shipped-docs.test.sh: the existing tree
# rules over the new command.)
#
# Each rule runs twice over, as in shipped-docs.test.sh: against REPO_ROOT, where
# it must print nothing, and against fixtures BUILT compliant by construction
# with exactly one defect, where it must print exactly the one line naming it.
# The second is what makes the first mean anything - a rule that never fires is
# satisfied by any tree. The fixtures are written here, byte by byte, and their
# blob SHAs computed with `git hash-object` over what was written: no upstream
# content is copied into a fixture.
#
# The settled data below is READ OUT of the story (C-1, C-2, C-3), never
# re-derived. A GREEN that vendored a different commit with a self-consistent
# UPSTREAM would satisfy `vendor_problems` - that rule only checks that the
# directory agrees with its own pin record - so the pin record itself is
# compared against C-1 separately, as data.
#
# Portable: bash, awk, git. No sha256sum (absent on some hosts) - blob SHAs come
# from `git hash-object <path>`, run from inside the directory so the repository's
# .gitattributes (`* text=auto eol=lf`) applies, exactly as it does to a commit.
# No pipe into an early-exit reader whose status is read (check-sigpipe.sh).

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

SKILL_REL=".claude/skills/security-audit"
CMD_REL=".claude/commands/security-audit.md"
REAL_DIR="$REPO_ROOT/$SKILL_REL"
REAL_CMD="$REPO_ROOT/$CMD_REL"

# --- settled values (story Contract: read out, not re-derived) ---------------

# C-2: the first line of UPSTREAM, exactly.
UPSTREAM_FIRST='# cloudflare/security-audit-skill @ c1c8a8c1471069fb0e188eeaff69b8e8db6564a8 (2026-09-14, MIT) - git blob SHAs; verify with `git hash-object`'

# C-1: upstream's `git ls-tree -r` at c1c8a8c1471069fb0e188eeaff69b8e8db6564a8,
# the 21 vendored blobs, `skills/security-audit/` dropped (C-2's line format).
# Upstream's README.md is the 22nd blob and is NOT vendored.
SETTLED_LISTING='6dbc9ecb3a5b9080e95b962869e8c7ab16cfdc20  LICENSE
02ba9039eca4cec811fefc77bce0d7349b379aae  AI-AND-LLM.md
18a2beb4dbb554fb52b0a0293b8bd9108207f8fa  ATTACK-CLASSES.md
8ba673e9e7e3d02f5518aa0219bcbeec7957531b  CLIENT-SIDE.md
5569f76c7740744aa3f60aaa89eaefe275f2e6c9  CLOUD-AND-DEPLOYMENT.md
0cba1fa463b62c9b0caba710a201e29c1eecd0ec  DATA-ISOLATION-AND-LIFECYCLE.md
d6230098651bff6348d3868c11f566bfb1306e7f  DESKTOP-MOBILE-AND-LOCAL-IPC.md
377d4dcfbe88a049379448cd7892717185401597  HUNTING.md
86ff4920752661fc4a31a35ca4f962ace5dd5f48  MEMORY-SAFETY-AND-BINARY.md
b04ab88f852224838fdc9683d9fcccd858b0778a  PROTOCOLS-RPC-AND-MESSAGING.md
1a170a93ab76b93dc5ac268a5b690beb423a8aa9  RECONNAISSANCE.md
6cbbd1e2cfa482068c8279c2f7da9db43d3f54b8  RESOURCE-EXHAUSTION-AND-AVAILABILITY.md
92178dad304d3f63e37582a297026a7874e12c62  SKILL.md
bf96aed0803bc07471483ab129dea86759c3e305  SUPPLY-CHAIN-AND-RELEASE.md
5e200d7387e665e53e0e4190fa4a5814c334c507  VALIDATION-AND-REPORTING.md
1a099fa575cf52a61e9a627f91b61015120fa517  WEB-PROTOCOL-AND-AUTH.md
55815a3687a45fff63d8ebf20068611bd6ad6d9a  report-schema.json
0ef58657bef18b26a92321df6c8e3d31bc8e6659  validate-coverage-ledger.cjs
b1444f57e1b021a61175733b8c356171861c8701  validate-coverage-ledger.test.cjs
2843feceddb7e30bf10d6e4f7bbe6640e4c57799  validate-findings.cjs
8d245b226bbe2fdf28b46b3203b99c2824039d2d  validate-findings.test.cjs'

# C-3: the command's needles, `<kind><TAB><needle>`, one per line.
#   F  fixed string, anywhere in the file (`grep -F`, so within one line)
#   E  extended regex, anywhere in the file, within one line
#   L  fixed string, in the file's LAST PARAGRAPH
# The E row is C-3's Defaults line with the number left free, so DV-1 can set
# the measured budget and drop the "provisional" clause without touching this
# file; scope and profile stay pinned (see the C-3 amendment in the story).
TAB="$(printf '\t')"
NEEDLES="$(cat <<'NEEDLES'
F	description: Audit the code for security defects with Cloudflare's vendored security-audit skill (optional, on request)
F	model: fable
F	argument-hint: [path | subsystem | <ref>..<ref>]
F	Runs in the session that reads this file, not in a subagent
F	Load `.claude/skills/security-audit/SKILL.md` in full audit mode
E	Defaults: scope repo-wide; profile `quick`; budget [0-9]+ agent invocations \(strict
F	hunters, critics and verifiers: `subagent_type: general-purpose`, `model: opus`
F	`research` agents: `subagent_type: Explore`, `model: opus`
F	this environment has no OS-enforced sandbox, so the skill executes no target code; every finding is source-traced and anything that needs execution stays `needs_validation`
F	validators not run
F	nothing found this run
F	never a gate, and nothing in the story loop runs it
F	~/security-audit-skill/<repo>/run-<N>
F	docs/wiki/audits/<scope>-<date>.md
F	docs/wiki/audits/TEMPLATE.md
F	bash scripts/new-story.sh
L	Report as `rules.md`, "Reporting to the user" says
L	bash scripts/plan.sh after
NEEDLES
)"
# The literal line C-3 gives GREEN for the E row; the fixtures carry it.
DEFAULTS_LINE='Defaults: scope repo-wide; profile `quick`; budget 16 agent invocations (strict, provisional until HARNESS-043 DV-1)'

# --- AC-1: the vendored directory --------------------------------------------

# vendor_listed <dir>   UPSTREAM's listing lines, `<sha>  <path>`, in file
# order: comments (`#`) and blank lines dropped, CR stripped. Malformed lines
# are passed through as they are; vendor_problems reports them.
vendor_listed() {
  [ -f "$1/UPSTREAM" ] || return 0
  awk '{ sub(/\r$/, "") } /^#/ || /^[ \t]*$/ { next } { print }' "$1/UPSTREAM"
}

# vendor_problems <dir>   One `<path>: <reason>` line per violation of AC-1's
# (a)-(c), paths relative to <dir>; silent when compliant. Always returns 0: the
# output is the verdict, so a caller compares it against the empty string.
#   (a) UPSTREAM exists; its first line names cloudflare/security-audit-skill
#       and a 40-hex commit; every other non-comment, non-blank line is
#       `<40 hex>  <path>` (C-2)
#   (b) every listed path exists, and `git hash-object` of it is the listed SHA
#   (c) every file in <dir>, at any depth, is listed - UPSTREAM itself excepted
vendor_problems() {
  local dir="$1" first n line sha path got listed f
  if [ ! -d "$dir" ]; then
    printf './: directory does not exist\n'
    return 0
  fi
  if [ ! -f "$dir/UPSTREAM" ]; then
    printf 'UPSTREAM: file is missing\n'
    return 0
  fi
  # (a): `# cloudflare/security-audit-skill @ ` then exactly 40 lowercase hex,
  # then end of line or a non-hex character.
  first="$(awk 'NR == 1 { sub(/\r$/, ""); print; exit }' "$dir/UPSTREAM")"
  sha=""
  case "$first" in
    "# cloudflare/security-audit-skill @ "*) sha="${first#"# cloudflare/security-audit-skill @ "}" ;;
  esac
  path="${sha:40:1}"; sha="${sha:0:40}"
  if [ "${#sha}" != 40 ] || [ -n "${sha//[0-9a-f]/}" ] || [ -n "${path//[!0-9a-f]/}" ]; then
    printf 'UPSTREAM: first line does not name cloudflare/security-audit-skill and a 40-hex commit\n'
  fi

  listed=""
  n=0
  while IFS= read -r line; do
    n=$((n + 1))
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    [ "$n" = 1 ] && continue
    sha="${line%%  *}"; path="${line#*  }"
    if [ "$sha" = "$line" ] || [ "${#sha}" != 40 ] || [ -n "${sha//[0-9a-f]/}" ] || [ -z "$path" ]; then
      printf "UPSTREAM: line %s is not '<40 hex>  <path>'\n" "$n"
      continue
    fi
    listed="$listed$path"$'\n'
    if [ ! -f "$dir/$path" ]; then
      printf '%s: listed in UPSTREAM but does not exist\n' "$path"
      continue
    fi
    got="$(cd "$dir" && git hash-object -- "$path" 2>/dev/null)"
    [ "$got" = "$sha" ] \
      || printf "%s: blob %s does not match UPSTREAM's %s\n" "$path" "${got:-<none>}" "$sha"
  done < "$dir/UPSTREAM"

  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ "$f" = UPSTREAM ] && continue
    case $'\n'"$listed" in *$'\n'"$f"$'\n'*) continue ;; esac
    printf '%s: not listed in UPSTREAM\n' "$f"
  done <<FILES
$(cd "$dir" && find . -type f 2>/dev/null | sed 's|^\./||' | LC_ALL=C sort)
FILES
  return 0
}

# vendor_fixture <dir>   A compliant vendored directory, by construction: four
# files written here, UPSTREAM generated from their own blob SHAs. Nobody's
# content - only the shape is C-2's.
vendor_fixture() {
  local d="$1" f
  rm -rf "$d"; mkdir -p "$d"
  printf 'MIT License\n\nCopyright (c) fixture\n' > "$d/LICENSE"
  printf -- '---\nname: security-audit\n---\n\n# A fixture skill\n' > "$d/SKILL.md"
  printf '# Hunting, a fixture\n\nRead the code.\n' > "$d/HUNTING.md"
  printf "'use strict';\nprocess.exit(0);\n" > "$d/validate-findings.cjs"
  {
    printf '%s\n' "$UPSTREAM_FIRST"
    for f in LICENSE SKILL.md HUNTING.md validate-findings.cjs; do
      printf '%s  %s\n' "$(cd "$d" && git hash-object -- "$f")" "$f"
    done
  } > "$d/UPSTREAM"
}

# blob <dir> <file>   The file's blob SHA as vendor_problems computes it.
blob() { ( cd "$1" && git hash-object -- "$2" ); }

# ---------------------------------------------------------------------------
describe "AC-1 the rule itself: a compliant fixture, then exactly one defect each"

V="$WORK/vendor"
vendor_fixture "$V"
assert_eq "a fixture built compliant by construction is silent" "" "$(vendor_problems "$V")"
assert_eq "and vendor_listed reads its four listing lines, the header skipped" 4 \
  "$(vendor_listed "$V" | awk 'END { print NR }')"

vendor_fixture "$V"
want_sha="$(blob "$V" SKILL.md)"
printf -- '---\nname: security-audit\n---\n\n# A fixture skilL\n' > "$V/SKILL.md"
assert_eq "one byte of one listed file changed prints exactly one line, naming that file" \
  "SKILL.md: blob $(blob "$V" SKILL.md) does not match UPSTREAM's $want_sha" \
  "$(vendor_problems "$V")"

vendor_fixture "$V"
want_sha="$(blob "$V" LICENSE)"
: > "$V/LICENSE"
assert_eq "LICENSE emptied prints exactly one line, naming LICENSE" \
  "LICENSE: blob e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 does not match UPSTREAM's $want_sha" \
  "$(vendor_problems "$V")"

vendor_fixture "$V"
printf 'not upstream\n' > "$V/NOTES.md"
assert_eq "an extra file dropped in prints exactly one line, naming it" \
  "NOTES.md: not listed in UPSTREAM" "$(vendor_problems "$V")"

vendor_fixture "$V"
mkdir -p "$V/reference"; printf 'not upstream\n' > "$V/reference/extra.md"
assert_eq "an extra file one directory down is found too" \
  "reference/extra.md: not listed in UPSTREAM" "$(vendor_problems "$V")"

vendor_fixture "$V"
rm -f "$V/HUNTING.md"
assert_eq "a listed file deleted prints exactly one line, naming it" \
  "HUNTING.md: listed in UPSTREAM but does not exist" "$(vendor_problems "$V")"

vendor_fixture "$V"
rm -f "$V/UPSTREAM"
assert_eq "no UPSTREAM at all is one line, not one per unlisted file" \
  "UPSTREAM: file is missing" "$(vendor_problems "$V")"

vendor_fixture "$V"
{ printf '# someone-else/security-audit-skill @ c1c8a8c1471069fb0e188eeaff69b8e8db6564a8\n'
  tail -n +2 "$V/UPSTREAM"; } > "$V/UPSTREAM.new" && mv "$V/UPSTREAM.new" "$V/UPSTREAM"
assert_eq "a first line naming another repository is reported" \
  "UPSTREAM: first line does not name cloudflare/security-audit-skill and a 40-hex commit" \
  "$(vendor_problems "$V")"

vendor_fixture "$V"
{ printf '# cloudflare/security-audit-skill @ c1c8a8c1471069fb0e188eeaff69b8e8db6564a (39 hex)\n'
  tail -n +2 "$V/UPSTREAM"; } > "$V/UPSTREAM.new" && mv "$V/UPSTREAM.new" "$V/UPSTREAM"
assert_eq "a first line whose commit is 39 hex is reported" \
  "UPSTREAM: first line does not name cloudflare/security-audit-skill and a 40-hex commit" \
  "$(vendor_problems "$V")"

vendor_fixture "$V"
awk '/  HUNTING\.md$/ { sub(/  /, " ") } { print }' "$V/UPSTREAM" > "$V/UPSTREAM.new" && mv "$V/UPSTREAM.new" "$V/UPSTREAM"
assert_eq "a listing line with one space is malformed, and the file it meant is then unlisted" \
  "UPSTREAM: line 4 is not '<40 hex>  <path>'
HUNTING.md: not listed in UPSTREAM" "$(vendor_problems "$V")"

assert_eq "a directory that does not exist is one line" \
  "./: directory does not exist" "$(vendor_problems "$WORK/no-such-dir")"

# ---------------------------------------------------------------------------
describe "AC-1 the real tree: $SKILL_REL is C-1's commit, complete and unmodified"

assert_eq "vendor_problems over the real directory prints nothing" "" "$(vendor_problems "$REAL_DIR")"
assert_eq "UPSTREAM's first line is exactly C-2's" \
  "$UPSTREAM_FIRST" "$(awk 'NR == 1 { sub(/\r$/, ""); print; exit }' "$REAL_DIR/UPSTREAM" 2>/dev/null)"
# Sorted on both sides: the pin is the SET of (blob, path) pairs, not the order.
assert_eq "UPSTREAM lists exactly C-1's 21 blobs - so a self-consistent copy of another commit is still red" \
  "$(printf '%s\n' "$SETTLED_LISTING" | LC_ALL=C sort)" \
  "$(vendor_listed "$REAL_DIR" | LC_ALL=C sort)"

# --- AC-2: the command --------------------------------------------------------

# last_paragraph <file>   The lines after the last blank (whitespace-only) line,
# trailing blank lines dropped first - reporting.test.sh's definition.
last_paragraph() {
  awk '
    { sub(/\r$/, "") }
    /^[ \t]*$/ { if (have) gap = 1; next }
    { if (gap) { p = ""; gap = 0 } p = p $0 "\n"; have = 1 }
    END { printf "%s", p }
  ' "$1"
}

# command_problems <file>   One line per C-3 needle the file does not carry, in
# NEEDLES order; silent when it carries them all. Always returns 0.
#
# Fork-free apart from the one awk: on Windows a fork costs tens of
# milliseconds, and this suite calls it two dozen times. The
# semantics are `grep -F` / `grep -E` per line: a fixed needle holds no newline,
# so containment in the whole text is containment within one line, and the
# regex is tried line by line with bash's own ERE.
command_problems() {
  local file="$1" name kind needle para text l hit
  local -a lines
  name="${file##*/}"
  if [ ! -f "$file" ]; then
    printf '%s: file is missing\n' "$name"
    return 0
  fi
  para="$(last_paragraph "$file")"
  mapfile -t lines < "$file"
  text="$(printf '%s\n' "${lines[@]%$'\r'}")"
  while IFS="$TAB" read -r kind needle; do
    [ -n "$kind" ] || continue
    case "$kind" in
      F) case "$text" in
           *"$needle"*) ;;
           *) printf '%s: does not carry `%s`\n' "$name" "$needle" ;;
         esac ;;
      E) hit=""
         for l in "${lines[@]}"; do [[ "$l" =~ $needle ]] && { hit=1; break; }; done
         [ -n "$hit" ] || printf '%s: has no line matching /%s/\n' "$name" "$needle" ;;
      L) case "$para" in
           *"$needle"*) ;;
           *) printf '%s: its last paragraph does not carry `%s`\n' "$name" "$needle" ;;
         esac ;;
    esac
  done <<ROWS
$NEEDLES
ROWS
  return 0
}

# missing_line <file> <kind> <needle>   The one line command_problems prints for
# that needle.
missing_line() {
  case "$2" in
    F) printf '%s: does not carry `%s`' "${1##*/}" "$3" ;;
    E) printf '%s: has no line matching /%s/' "${1##*/}" "$3" ;;
    L) printf '%s: its last paragraph does not carry `%s`' "${1##*/}" "$3" ;;
  esac
}

# command_fixture <file> [skip]   A command carrying every needle, by
# construction: frontmatter, a heading, one body paragraph per needle, and a
# last paragraph holding the two L needles. With <skip> = N, the N-th NEEDLES
# row is left out. The E row is written as C-3's literal DEFAULTS_LINE.
command_fixture() {
  local file="$1" skip="${2:-0}" i=0 kind needle front="" body="" last=""
  while IFS="$TAB" read -r kind needle; do
    [ -n "$kind" ] || continue
    i=$((i + 1))
    [ "$i" = "$skip" ] && continue
    case "$kind" in
      F) case "$needle" in
           description:*|model:*|argument-hint:*) front="$front$needle"$'\n' ;;
           *) body="$body"$'\n'"Fixture prose: $needle."$'\n' ;;
         esac ;;
      E) body="$body"$'\n'"$DEFAULTS_LINE"$'\n' ;;
      L) last="$last$needle"$'\n' ;;
    esac
  done <<ROWS
$NEEDLES
ROWS
  { printf -- '---\n%s---\n\n# Security audit (fixture)\n%s\n%s\n' "$front" "$body" "$last"; } > "$file"
}

# ---------------------------------------------------------------------------
describe "AC-2 the rule itself: every needle present, then each one removed in turn"

C="$WORK/cmd/security-audit.md"; mkdir -p "$WORK/cmd"
command_fixture "$C"
assert_eq "a command fixture carrying every C-3 needle is silent" "" "$(command_problems "$C")"
assert_eq "there are 18 needles: 15 fixed, the budget regex, and 2 in the last paragraph" 18 \
  "$(printf '%s\n' "$NEEDLES" | awk 'NF { n++ } END { print n }')"

# Any one needle removed prints exactly the one line naming it. A loop, one
# assertion per needle, so a needle the rule cannot see fails by name.
i=0
while IFS="$TAB" read -r kind needle; do
  [ -n "$kind" ] || continue
  i=$((i + 1))
  command_fixture "$C" "$i"
  assert_eq "with needle $i removed, exactly one line names it: $needle" \
    "$(missing_line "$C" "$kind" "$needle")" "$(command_problems "$C")"
done <<ROWS
$NEEDLES
ROWS

E_NEEDLE="$(printf '%s\n' "$NEEDLES" | awk -F'\t' '$1 == "E" { print $2 }')"

command_fixture "$C"
awk -v old="$DEFAULTS_LINE" '$0 == old { $0 = "Defaults: scope repo-wide; profile `quick`; budget 23 agent invocations (strict)" } { print }' \
  "$C" > "$C.new" && mv "$C.new" "$C"
assert_eq "the budget at another whole number with no provisional clause still passes - DV-1 sets it" \
  "" "$(command_problems "$C")"

command_fixture "$C"
awk -v old="$DEFAULTS_LINE" '$0 == old { $0 = "Defaults: scope repo-wide; profile `quick`; budget sixteen agent invocations (strict)" } { print }' \
  "$C" > "$C.new" && mv "$C.new" "$C"
assert_eq "a budget that is not a whole number is reported" \
  "$(missing_line "$C" E "$E_NEEDLE")" "$(command_problems "$C")"

command_fixture "$C"
awk -v old="$DEFAULTS_LINE" '$0 == old { $0 = "Defaults: scope the current diff; profile `quick`; budget 16 agent invocations (strict)" } { print }' \
  "$C" > "$C.new" && mv "$C.new" "$C"
assert_eq "a default scope other than repo-wide is reported" \
  "$(missing_line "$C" E "$E_NEEDLE")" "$(command_problems "$C")"

command_fixture "$C"
awk -v old="$DEFAULTS_LINE" '$0 == old { $0 = "Defaults: scope repo-wide; profile `standard`; budget 16 agent invocations (strict)" } { print }' \
  "$C" > "$C.new" && mv "$C.new" "$C"
assert_eq "a default profile other than quick is reported" \
  "$(missing_line "$C" E "$E_NEEDLE")" "$(command_problems "$C")"

# Present elsewhere is not present: the two L needles moved up into the body,
# with a different last paragraph after them.
command_fixture "$C"
awk '$0 == "bash scripts/plan.sh after" { next } { print }' "$C" > "$C.new" && mv "$C.new" "$C"
awk 'NR == 6 { print "Earlier: bash scripts/plan.sh after"; print "" } { print }' "$C" > "$C.new" && mv "$C.new" "$C"
assert_eq "the next-action needle in an earlier paragraph only is reported as missing from the last" \
  "$(missing_line "$C" L "bash scripts/plan.sh after")" "$(command_problems "$C")"

command_fixture "$C"
printf '\nA closing paragraph that names neither.\n\n\n' >> "$C"
assert_eq "a later paragraph pushing both L needles out of the last one is reported twice, trailing blanks ignored" \
  "$(missing_line "$C" L 'Report as `rules.md`, "Reporting to the user" says')
$(missing_line "$C" L "bash scripts/plan.sh after")" "$(command_problems "$C")"

assert_eq "a command file that does not exist is one line" \
  "nope.md: file is missing" "$(command_problems "$WORK/cmd/nope.md")"

# ---------------------------------------------------------------------------
describe "AC-2 the real tree: $CMD_REL carries every C-3 needle"

assert_eq "command_problems over the real command prints nothing" "" "$(command_problems "$REAL_CMD")"

# --- AC-4: the refresh ships it ---------------------------------------------

PROJ="$WORK/project"

# new_project   refresh.test.sh's shape, cut to what a refresh needs: a
# committed project with the replaced directories and no security-audit
# anywhere, and no active story.
new_project() {
  rm -rf "$PROJ"
  mkdir -p "$PROJ/.claude/harness" "$PROJ/.claude/skills/stack-profiles/reference" \
           "$PROJ/.claude/agents" "$PROJ/.claude/state" "$PROJ/.claude/commands" \
           "$PROJ/.claude/hooks" "$PROJ/.claude/tests" "$PROJ/scripts" "$PROJ/docs/wiki"
  printf 'OLD agent\n'           > "$PROJ/.claude/agents/lead-po.md"
  printf 'OLD command\n'         > "$PROJ/.claude/commands/advance-story.md"
  printf 'OLD HOOK\n'            > "$PROJ/.claude/hooks/phase-guard.sh"
  printf 'OLD suite\n'           > "$PROJ/.claude/tests/lib.test.sh"
  printf 'PROJECT profile\n'     > "$PROJ/.claude/skills/stack-profiles/reference/own.md"
  printf 'BOOTSTRAPPED=yes\n'    > "$PROJ/.claude/harness/project.conf"
  printf 'project notes\n'       > "$PROJ/docs/wiki/stack.md"
  ( cd "$PROJ" && git init -q 2>/dev/null && git add -A >/dev/null 2>&1 \
      && git -c user.email=t@t -c user.name=t commit -qm base >/dev/null 2>&1 )
}

# refresh_from <upstream>   Run the real script from inside the project, the
# documented way round: `bash <script> <upstream>`, cwd the project.
refresh_from() { ( cd "$PROJ" && bash "$REPO_ROOT/scripts/refresh-harness.sh" "$1" 2>&1 ); }

# ---------------------------------------------------------------------------
describe "AC-4 control: an upstream without the skill does not grow one"

# A stand-in upstream holding the real refresh script and one skill, and no
# security-audit. The skill marker arriving is what shows the refresh ran its
# copy at all; the security-audit directory NOT arriving is what shows it comes
# from upstream rather than from the script.
UP0="$WORK/upstream-without"
mkdir -p "$UP0/.claude/hooks" "$UP0/.claude/skills/tdd-cycle" "$UP0/.claude/commands" "$UP0/scripts"
printf 'upstream hook\n'     > "$UP0/.claude/hooks/phase-guard.sh"
printf 'upstream skill\n'    > "$UP0/.claude/skills/tdd-cycle/SKILL.md"
printf 'upstream command\n'  > "$UP0/.claude/commands/advance-story.md"
cp "$REPO_ROOT/scripts/refresh-harness.sh" "$UP0/scripts/"

new_project
out="$(refresh_from "$UP0")"; rc=$?
assert_eq "the refresh from it exits 0" 0 "$rc"
assert_eq "and it did copy the skills it holds" "upstream skill" \
  "$(cat "$PROJ/.claude/skills/tdd-cycle/SKILL.md" 2>/dev/null)"
if [ -e "$PROJ/$SKILL_REL" ]; then
  _bad "but the project has no $SKILL_REL afterwards" "it does: $(ls -A "$PROJ/$SKILL_REL" 2>&1)"
else
  _ok "but the project has no $SKILL_REL afterwards"
fi
if [ -e "$PROJ/$CMD_REL" ]; then
  _bad "and no $CMD_REL" "it does"
else
  _ok "and no $CMD_REL"
fi

# ---------------------------------------------------------------------------
describe "AC-4 the refresh from this checkout delivers the command and the skill"

# UP is this checkout. The script copies upstream's WORKING TREE (`cp -r` of
# .claude/<dir>), not its git objects, so what arrives is what is on disk here,
# committed or not (measured in RED: see the story's handoff).
new_project
out="$(refresh_from "$REPO_ROOT")"; rc=$?
assert_eq "the refresh from this checkout exits 0" 0 "$rc"
if [ -f "$PROJ/$CMD_REL" ] && [ -f "$REAL_CMD" ] && cmp -s "$REAL_CMD" "$PROJ/$CMD_REL"; then
  _ok "the project now has $CMD_REL, byte-identical to this checkout's"
else
  _bad "the project now has $CMD_REL, byte-identical to this checkout's" \
    "project copy: $([ -f "$PROJ/$CMD_REL" ] && echo present || echo absent); this checkout's: $([ -f "$REAL_CMD" ] && echo present || echo absent)"
fi
assert_eq "and vendor_problems over the project's copy of the skill prints nothing" \
  "" "$(vendor_problems "$PROJ/$SKILL_REL")"
assert_eq "and the project's UPSTREAM is still C-1's 21 blobs" \
  "$(printf '%s\n' "$SETTLED_LISTING" | LC_ALL=C sort)" \
  "$(vendor_listed "$PROJ/$SKILL_REL" | LC_ALL=C sort)"

summary "security-audit"
