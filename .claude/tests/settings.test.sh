#!/usr/bin/env bash
# Do the deny rules in .claude/settings.json still match what the state
# directory actually holds?
#
# `.claude/state/` used to be denied wholesale - `Write(./.claude/state/**)` -
# which was right about the two files that carry evidence and wrong about
# everything else in there. It also covered the two TRACKED documents, so the
# README describing the directory could not be edited by the tools it describes,
# and it covered tool exhaust, so a leftover `mutations/*.bak` - which the
# harness itself treats as a "the restore failed, go and look" signal - could not
# be cleaned up after being acted on.
#
# The rules are now per file, which is more accurate and less durable: a state
# file added later gets no protection until somebody remembers a line, and that
# is a worse failure than the one the narrowing fixed. So it is not left to
# discipline. `.claude/state/README.md` carries a `Hand-editable` column and this
# suite checks the two against each other in BOTH directions.
#
# The checks are a function over a (settings, README) PAIR rather than statements
# about the live files, for one reason: the live files are the only ones a suite
# like this is tempted to assert against, and then every assertion in it passes on
# its first run and forever, whether or not it checks anything. Mutating the real
# settings.json to earn them is not an option either - the runtime reads
# permissions and hooks live, so a suite that edits them mid-run is changing the
# rules it is running under. So `problems` takes a pair, the real pair must produce
# none, and each way of getting it wrong is a fixture that must produce a specific
# one.
#
# WHICH RULE PROTECTS A FILE. An `Edit(path)` rule is the only file deny rule
# the runtime matches, and it covers every file-editing tool - Write, Edit,
# MultiEdit and NotebookEdit alike. A `Write(path)` or `MultiEdit(path)` rule is
# not matched at all: the CLI prints a startup warning naming it ("is not matched
# by file permission checks - only Edit(path) rules are") and discards it. This
# suite used to DEMAND a Write, an Edit and a MultiEdit rule per protected file,
# so it was green while requiring two rules in three that did nothing - a rule
# probed only against fixtures its author wrote. Now each `no` row demands its
# one `Edit` rule, and a `Write`/`MultiEdit`/`NotebookEdit` rule under the state
# directory is reported as DEAD, whatever the README says about its path, so
# removing one is never mistaken for dropping protection. That the Edit rule
# really refuses the Write tool comes from the CLI's own warning text, not from
# anything this repository can run; HARNESS-050's DV-2 is the observation that
# backs it.
#
# Verified separately by probe, since the rules are enforced by the runtime and
# not by anything in this repository: a file-specific deny blocks a Bash append
# and a Bash `rm` of that exact path, not merely the file-editing tools. The
# narrowing gave up nothing on the two files that matter.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

TAB="$(printf '\t')"

# rows <readme>   "<path><TAB><yes|no>" per table row.
rows() {
  awk -F'|' '
    /^[[:space:]]*\|/ {
      p = $2; e = $(NF - 1)
      gsub(/^[ \t`]+|[ \t`]+$/, "", p)
      gsub(/^[ \t]+|[ \t]+$/, "", e)
      if (p == "" || p ~ /^-+$/ || tolower(p) == "file") next
      print p "\t" tolower(e)
    }' "$1"
}

# problems <settings> <readme>   One line per disagreement; silence means they
# agree. Every check in this suite is this function on some pair.
problems() {
  local settings="$1" readme="$2" r path editable rule has d row denied
  r="$(rows "$readme")"
  [ -n "$r" ] || { printf 'no parseable table in %s\n' "$readme"; return 0; }

  # 1. Every row answers the question. A blank cell is a state file added
  #    without anybody deciding whether hand edits to it are a problem.
  while IFS="$TAB" read -r path editable; do
    [ -n "$path" ] || continue
    case "$editable" in
      yes|no) ;;
      *) printf "%s: hand-editable says '%s'; it must say yes or no\n" "$path" "$editable" ;;
    esac
  done <<< "$r"

  # 2. Forwards: a `no` row has its `Edit` rule, a `yes` row has none.
  while IFS="$TAB" read -r path editable; do
    [ -n "$path" ] || continue
    rule="\"Edit(./.claude/state/$path)\""
    if grep -qF -- "$rule" "$settings"; then has=1; else has=0; fi
    if [ "$editable" = "no" ] && [ "$has" = 0 ]; then
      printf '%s: not hand-editable, but settings.json has no %s\n' "$path" "$rule"
    elif [ "$editable" = "yes" ] && [ "$has" = 1 ]; then
      printf '%s: hand-editable, but settings.json denies it with %s\n' "$path" "$rule"
    fi
  done <<< "$r"

  # 3. Dead rules: a file deny rule the runtime does not match. Exactly these
  #    three tool names - `Read(...)` and `Bash(...)` rules ARE matched, and are
  #    not this check's business. It does not consult the README, so a dead rule
  #    on a `yes` row, or on a path the table never mentions, is still only dead.
  grep -oE '"(Write|MultiEdit|NotebookEdit)\(\./\.claude/state/[^)]*\)"' "$settings" \
    | while IFS= read -r d; do
        printf '%s is dead: only Edit(path) rules are matched by file permission checks\n' "$d"
      done

  # 4. Backwards, and this is the one that catches a re-widened glob: an `Edit`
  #    rule naming `**`, or a path the README never mentions, is a rule whose
  #    reason has been lost. That is how the directory came to be denied
  #    wholesale. `Edit` only: any other file rule is dead, and said so above.
  denied="$(grep -oE '"Edit\(\./\.claude/state/[^)]*\)"' "$settings" \
    | sed -E 's/^"Edit\(\.\/\.claude\/state\///; s/\)"$//' | sort -u)"
  [ -n "$denied" ] || printf 'settings.json denies nothing under .claude/state/\n'
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    row="$(printf '%s\n' "$r" | awk -F'\t' -v p="$d" '$1 == p { print $2; exit }')"
    case "$row" in
      no) ;;
      yes) printf "denied path '%s' is listed as hand-editable\n" "$d" ;;
      *)   printf "denied path '%s' is not in the README table\n" "$d" ;;
    esac
  done <<< "$denied"
  return 0
}

# HARNESS-047. `git log` and `git diff` are allow-listed as read-only, and both
# take `--output=<file>`, which writes anywhere the user can. The user chose to
# keep the two allows and deny `--output` beside them (deny is evaluated before
# allow). The checker below pins that text, mechanically: which entries, in
# which array, spelled how. It is invisible to `problems` - neither direction
# there sees a `Bash(...)` rule - and `problems` is invisible to it.
#
# The `:*` spelling is wrong mid-pattern: the platform recognises `:*` only at
# the END of a rule, so `Bash(git log:*--output*)` is a rule that looks like a
# deny and matches nothing. That is why every match here is anchored and whole.
GIT_OUTPUT_DENY='Bash(git log *--output*)
Bash(git diff *--output*)'
GIT_OUTPUT_ALLOW='Bash(git diff:*)
Bash(git log:*)'

# array_lines <block> <settings>   Each element of the `"<block>": [` array, one
# per line, trimmed and with its trailing comma removed: the text between the
# line that opens the array and the next line that is only a `]`. No JSON
# parser (rules.md, "Portability"); the file is read as lines, as `problems`
# reads it.
array_lines() {
  awk -v k="\"$1\": [" '
    { sub(/\r$/, "") }
    f && /^[[:space:]]*\]/ { f = 0; next }
    f { s = $0; sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s)
        sub(/,$/, "", s); print s; next }
    index($0, k) { f = 1 }' "$2"
}

# git_output_rules <settings>   One line per disagreement with HARNESS-047's
# Contract C-1; silence means the deny array carries both `--output` rules and
# the allow array still carries both git prefixes.
git_output_rules() {
  local settings="$1" deny allow rule n
  deny="$(array_lines deny "$settings")"
  allow="$(array_lines allow "$settings")"
  while IFS= read -r rule; do
    n="$(grep -cxF -- "\"$rule\"" <<< "$deny" || true)"
    [ "${n:-0}" -gt 0 ] || printf 'deny has no "%s"\n' "$rule"
  done <<< "$GIT_OUTPUT_DENY"
  while IFS= read -r rule; do
    n="$(grep -cxF -- "\"$rule\"" <<< "$allow" || true)"
    [ "${n:-0}" -gt 0 ] || printf 'allow has no "%s"\n' "$rule"
  done <<< "$GIT_OUTPUT_ALLOW"
  return 0
}

# json_shape <file>   One line per structural defect; silence means the
# brackets balance, no string is left open, no element is followed by a comma
# and then a closing bracket, and no two values sit side by side without one.
# Not a JSON parser (rules.md, "Portability") - the defects it reads are the
# ones a hand edit to a deny array makes: a comma left on the new last element,
# or a comma not added to the old one.
json_shape() {
  tr -d '\r' < "$1" | awk '
    { n = length($0)
      for (i = 1; i <= n; i++) {
        c = substr($0, i, 1)
        if (s) {
          if (esc) esc = 0
          else if (c == "\\") esc = 1
          else if (c == "\"") { s = 0; prev = "\"" }
          continue
        }
        if (c == " " || c == "\t") continue
        if (c == "\"" || c == "{" || c == "[")
          if (prev == "\"" || prev == "}" || prev == "]") print "missing comma before line " NR
        if (c == "\"") { s = 1; continue }
        if (c == "{" || c == "[") d++
        if (c == "}" || c == "]") {
          if (prev == ",") print "trailing comma before line " NR
          d--
          if (d < 0) print "unbalanced close on line " NR
        }
        prev = c
      }
    }
    END { if (s) print "unterminated string"; if (d != 0) print "unbalanced brackets: depth " d " at end" }'
}

SETTINGS="$REPO_ROOT/.claude/settings.json"
README="$REPO_ROOT/.claude/state/README.md"

FIX="$(make_fixture)"
trap 'rm -rf "$FIX"' EXIT

# ---------------------------------------------------------------------------
describe "the shipped pair agrees with itself"

assert_eq "no disagreements" "" "$(problems "$SETTINGS" "$README")"

# ---------------------------------------------------------------------------
describe "HARNESS-027 AC-7: the kept failing log has its own row"

# `gate-logs/*.log` already matches `*.failed.log` as a glob, so the check above
# is satisfied without a row. The row says what the file is and who writes it,
# so it is asserted by its own first two cells and its last, as a whole line.
# grep -E rather than downstream's awk reader: no gsub/field-splitting dialect
# to differ between gawk and mawk (HARNESS-025), and no interval expressions.
# failed_row <readme> <path cell>   How many table rows have that path, written
# by scripts/gates.sh, hand-editable yes.
failed_row() {
  local p; p="$(printf '%s' "$2" | sed 's/[.*]/\\&/g')"
  tr -d '\r' < "$1" | grep -cE -- "^\\| \`$p\` +\\| \`scripts/gates\\.sh\` +\\|.*\\| yes +\\|\$"
}
assert_eq "AC-7: README has one gate-logs/*.failed.log row, written by scripts/gates.sh, hand-editable yes" \
  1 "$(failed_row "$README" 'gate-logs/*.failed.log')"
# Control: the same reader finds the row it knows is there, so a miss above is
# the README's and not the reader's.
assert_eq "AC-7 control: the same reader finds the existing gate-logs/*.log row" \
  1 "$(failed_row "$README" 'gate-logs/*.log')"

# ---------------------------------------------------------------------------
describe "HARNESS-069 AC-11: the logs kept for a signature have their own row"

# `gate-logs/*.log` does not reach into a subdirectory, so kept/ needs a row of
# its own, read by the same whole-row reader as HARNESS-027's line above (whose
# control shows the reader finds a row that is there). Ported from
# manga-translator MT-053.
assert_eq "AC-11: README has one gate-logs/kept/*.log row, written by scripts/gates.sh, hand-editable yes" \
  1 "$(failed_row "$README" 'gate-logs/kept/*.log')"

# ---------------------------------------------------------------------------
describe "the two files that carry evidence stay denied"

# Stated independently of the README, so that widening the column and the rules
# together still fails. current-story.env is written by phase.sh alongside the
# story frontmatter, and the guarantee that those cannot drift holds only while
# nothing else writes it. last-gate-run is what the Stop hook reads to decide
# whether a phase's gate obligation was met, so hand-writing RESULT=pass into it
# forges exactly what law 3 exists to prevent.
#
# HARNESS-050 AC-1. Every match is against the deny array's elements, trimmed
# (`array_lines`), as whole lines.
DENY="$(array_lines deny "$SETTINGS")"
for f in current-story.env last-gate-run; do
  n="$(grep -cxF -- "\"Edit(./.claude/state/$f)\"" <<< "$DENY" || true)"
  if [ "${n:-0}" -eq 1 ]; then
    _ok "Edit(./.claude/state/$f) is denied"
  else
    _bad "Edit(./.claude/state/$f) is denied" "deny holds it $n time(s); settings.json must hold it once"
  fi
  n="$(grep -cF -- "(./.claude/state/$f)" <<< "$DENY" || true)"
  assert_eq "AC-1: exactly one deny rule names ./.claude/state/$f" 1 "${n:-0}"
done
for tool in Write MultiEdit NotebookEdit; do
  n="$(grep -cE -- "^\"$tool\\(\\./\\.claude/state/" <<< "$DENY" || true)"
  assert_eq "AC-1: no $tool(...) deny rule names a path under ./.claude/state/" 0 "${n:-0}"
done
assert_eq "AC-1: the first three deny elements are the three Read denies, unchanged" \
  '"Read(./.env)"
"Read(./.env.*)"
"Read(./**/secrets/**)"' "$(head -n 3 <<< "$DENY")"
assert_eq "AC-1: HARNESS-047's two Bash denies are still the last two deny elements" \
  '"Bash(git log *--output*)"
"Bash(git diff *--output*)"' "$(tail -n 2 <<< "$DENY")"
# Contract C-1, read out: the whole array, in order.
assert_eq "AC-1/C-1: the deny array is exactly the seven C-1 rules, in order" \
  '"Read(./.env)"
"Read(./.env.*)"
"Read(./**/secrets/**)"
"Edit(./.claude/state/current-story.env)"
"Edit(./.claude/state/last-gate-run)"
"Bash(git log *--output*)"
"Bash(git diff *--output*)"' "$DENY"
assert_eq "AC-1: settings.json is well-formed JSON by bracket and comma shape" "" "$(json_shape "$SETTINGS")"
# Controls: the shape reader fires on the two defects a hand edit to the deny
# array makes, on copies of the live file - so silence above is the file's.
tr -d '\r' < "$SETTINGS" | sed 's/^\([[:space:]]*"Bash(git diff \*--output\*)"\)$/\1,/' > "$FIX/trailing.json"
assert_contains "AC-1 control: a comma left on the last deny element is reported" \
  "trailing comma before line" "$(json_shape "$FIX/trailing.json")"
tr -d '\r' < "$SETTINGS" | sed 's/^\([[:space:]]*"Read(\.\/\.env)"\),$/\1/' > "$FIX/nocomma.json"
assert_contains "AC-1 control: a comma missing after the first deny element is reported" \
  "missing comma before line" "$(json_shape "$FIX/nocomma.json")"

# ---------------------------------------------------------------------------
describe "each way of getting it wrong produces its own complaint"

# The baseline pair: small, correct, and the thing each case below breaks by one
# edit.
#
# good_settings   A deny block protecting both files with exactly their two
# `Edit` rules, and nothing else.
good_settings() {
  printf '{ "permissions": { "deny": [\n  "Edit(./.claude/state/current-story.env)",\n  "Edit(./.claude/state/last-gate-run)"\n] } }\n' \
    > "$FIX/settings.json"
}

# deny_also <rule>   One more deny entry on top of whatever is there, so a case
# says "the baseline, plus this one wrong thing".
deny_also() {
  awk -v r="$1" '
    /^\] \} \}$/ { print ",\n  \"" r "\""; print; next }
    { print }' "$FIX/settings.json" > "$FIX/s.tmp" && mv "$FIX/s.tmp" "$FIX/settings.json"
}
good_readme() {
  cat > "$FIX/README.md" <<'EOF'
| File | Written by | Read by | Hand-editable |
|---|---|---|---|
| `current-story.env` | `scripts/phase.sh` | the phase guard | no |
| `last-gate-run` | `scripts/gates.sh` | the stop hook | no |
| `gate-logs/*.log` | `scripts/gates.sh` | you, when a gate fails | yes |
EOF
}
p() { problems "$FIX/settings.json" "$FIX/README.md"; }

DEAD=' is dead: only Edit(path) rules are matched by file permission checks'

good_settings; good_readme
assert_eq "AC-2: the baseline pair - both Edit rules and no other state rule - agrees" "" "$(p)"

# A state file added, with nobody deciding what it is.
good_settings; good_readme
printf -- '| `new-thing` | `scripts/x.sh` | somebody | |\n' >> "$FIX/README.md"
assert_contains "an unanswered column" "new-thing: hand-editable says ''" "$(p)"

# A file declared protected, with no rule behind the declaration. This is the
# drift the per-file rules invite, and the reason this suite exists.
good_settings; good_readme
printf -- '| `secrets.env` | `scripts/x.sh` | the hooks | no |\n' >> "$FIX/README.md"
assert_eq "a no row with no rule demands its Edit rule, and only that" \
  'secrets.env: not hand-editable, but settings.json has no "Edit(./.claude/state/secrets.env)"' "$(p)"

# AC-2: a rule dropped from under a file that still says it is protected.
good_readme
good_settings
awk '!/Edit\(\.\/\.claude\/state\/last-gate-run\)/' "$FIX/settings.json" > "$FIX/s.tmp" && mv "$FIX/s.tmp" "$FIX/settings.json"
assert_eq "AC-2: a dropped Edit rule is named exactly, and nothing else" \
  'last-gate-run: not hand-editable, but settings.json has no "Edit(./.claude/state/last-gate-run)"' "$(p)"

# AC-4: a rule nobody can explain, on a file the README says is fine to touch.
# Both directions see it: the forwards line, then the backwards one.
good_settings; good_readme
deny_also 'Edit(./.claude/state/gate-logs/*.log)'
assert_eq "AC-4: a yes row denied by an Edit rule is named from both directions" \
  'gate-logs/*.log: hand-editable, but settings.json denies it with "Edit(./.claude/state/gate-logs/*.log)"
denied path '\''gate-logs/*.log'\'' is listed as hand-editable' "$(p)"

# AC-4: the glob, back. This is what the narrowing undid, and nothing else in
# the suite would notice it returning: `**` satisfies no row, so it is caught by
# the backwards check rather than the forwards one.
good_settings; good_readme
deny_also 'Edit(./.claude/state/**)'
assert_eq "AC-4: a re-widened Edit glob" "denied path '**' is not in the README table" "$(p)"

# AC-4: an Edit rule for a path the README never mentions.
good_settings; good_readme
deny_also 'Edit(./.claude/state/mystery)'
assert_eq "AC-4: an Edit rule for an undocumented path" "denied path 'mystery' is not in the README table" "$(p)"

# AC-4: nothing protected at all - one line per `no` row, then the summary.
good_readme
printf '{ "permissions": { "deny": [ "Read(./.env)" ] } }\n' > "$FIX/settings.json"
assert_eq "AC-4: no Edit rule at all names every no row and says nothing is denied" \
  'current-story.env: not hand-editable, but settings.json has no "Edit(./.claude/state/current-story.env)"
last-gate-run: not hand-editable, but settings.json has no "Edit(./.claude/state/last-gate-run)"
settings.json denies nothing under .claude/state/' "$(p)"

# A table that is not a table.
good_settings
printf 'There used to be a table here.\n' > "$FIX/README.md"
assert_contains "an unparseable README" "no parseable table" "$(p)"

# AC-3: a dead rule is a complaint, one per rule, with its own text in the
# line. Each case has a control: the same fixture with the rule spelled
# `Edit(...)`. On a `no` row that is the rule already there, so the control
# prints nothing; on the `yes` row it is AC-4's row complaint and NOT a dead
# line - so a checker that flagged every tool, Edit included, fails a control.
good_settings; good_readme
deny_also 'Write(./.claude/state/last-gate-run)'
assert_eq "AC-3: a Write rule on a no row is dead, and that is all" \
  "\"Write(./.claude/state/last-gate-run)\"$DEAD" "$(p)"
good_settings; good_readme
deny_also 'Edit(./.claude/state/last-gate-run)'
assert_eq "AC-3 control: the same rule spelled Edit prints nothing" "" "$(p)"

good_settings; good_readme
deny_also 'MultiEdit(./.claude/state/current-story.env)'
assert_eq "AC-3: a MultiEdit rule on a no row is dead, and that is all" \
  "\"MultiEdit(./.claude/state/current-story.env)\"$DEAD" "$(p)"
good_settings; good_readme
deny_also 'Edit(./.claude/state/current-story.env)'
assert_eq "AC-3 control: the MultiEdit fixture spelled Edit prints nothing" "" "$(p)"

good_settings; good_readme
deny_also 'NotebookEdit(./.claude/state/current-story.env)'
assert_eq "AC-3: a NotebookEdit rule on a no row is dead, and that is all" \
  "\"NotebookEdit(./.claude/state/current-story.env)\"$DEAD" "$(p)"
# (The control for this fixture is the MultiEdit one's, verbatim: the same
# baseline plus Edit(./.claude/state/current-story.env). Repeated so each dead
# case has its control beside it.)
good_settings; good_readme
deny_also 'Edit(./.claude/state/current-story.env)'
assert_eq "AC-3 control: the NotebookEdit fixture spelled Edit prints nothing" "" "$(p)"

# A dead rule on a `yes` row is dead and nothing else: removing it must never
# read as dropping protection, and the row is not consulted.
good_settings; good_readme
deny_also 'Write(./.claude/state/gate-logs/*.log)'
assert_eq "AC-3: a Write rule on a yes row is dead, and says nothing about the row" \
  "\"Write(./.claude/state/gate-logs/*.log)\"$DEAD" "$(p)"
good_settings; good_readme
deny_also 'Edit(./.claude/state/gate-logs/*.log)'
assert_not_contains "AC-3 control: the yes-row fixture spelled Edit is a row complaint, not a dead rule" \
  "is dead" "$(p)"

# Nor on a path the README never lists, a glob included.
good_settings; good_readme
deny_also 'Write(./.claude/state/**)'
assert_eq "AC-3: a dead Write glob is dead, and not an undocumented path" \
  "\"Write(./.claude/state/**)\"$DEAD" "$(p)"

# Exactly three tool names: a Read rule under the state directory is matched by
# the runtime, so it is not dead - and it is not an Edit rule, so the backwards
# check does not see it either.
good_settings; good_readme
deny_also 'Read(./.claude/state/last-gate-run)'
assert_eq "AC-3: a Read rule under the state directory is not dead" "" "$(p)"

# Many: the shape the live file had before HARNESS-050 - Write, Edit and
# MultiEdit per file - is four dead lines, in file order, and nothing else.
printf '{ "permissions": { "deny": [\n  "Write(./.claude/state/current-story.env)",\n  "Edit(./.claude/state/current-story.env)",\n  "MultiEdit(./.claude/state/current-story.env)",\n  "Write(./.claude/state/last-gate-run)",\n  "Edit(./.claude/state/last-gate-run)",\n  "MultiEdit(./.claude/state/last-gate-run)"\n] } }\n' \
  > "$FIX/settings.json"
good_readme
assert_eq "AC-3: the old three-tools-per-file shape is four dead rules, in order" \
  "\"Write(./.claude/state/current-story.env)\"$DEAD
\"MultiEdit(./.claude/state/current-story.env)\"$DEAD
\"Write(./.claude/state/last-gate-run)\"$DEAD
\"MultiEdit(./.claude/state/last-gate-run)\"$DEAD" "$(p)"

# ---------------------------------------------------------------------------
describe "HARNESS-050 AC-5: the documents say Edit, and name no tool list"

# readme_section <readme>   The section headed "## The `Hand-editable` column
# is enforced", up to the next `## ` heading, one line per line.
readme_section() {
  awk '{ sub(/\r$/, "") }
       f && /^## / { f = 0 }
       $0 == "## The `Hand-editable` column is enforced" { f = 1 }
       f { print }' "$1"
}
# state_bullet <rules.md>   The Non-negotiables bullet beginning "- Do not
# commit `.claude/state/**`", joined onto one line with runs of white space
# collapsed, so a phrase the text wraps is still one string.
state_bullet() {
  awk '{ sub(/\r$/, "") }
       f && (/^- / || /^#/ || /^$/) { f = 0 }
       index($0, "- Do not commit `.claude/state/**`") == 1 { f = 1 }
       f { printf "%s ", $0 }' "$1" | tr -s ' \t' '  '
}
SECTION="$(readme_section "$README")"
BULLET="$(state_bullet "$REPO_ROOT/.claude/harness/rules.md")"

# Controls: each reader found its text, so an absence below is the document's
# and not an empty extraction. The probe paragraph stands (C-3), and the
# bullet's list of state files is unchanged.
assert_contains "AC-5 control: the README section is found, probe paragraph and all" \
  "Verified by probe" "$SECTION"
assert_contains "AC-5 control: the rules.md state bullet is found, and runs past its first line" \
  "phase-guard-declined.log" "$BULLET"

n="$(grep -cF -- 'An `Edit(path)` rule is the only file deny rule the runtime matches, and it covers every file-editing tool.' <<< "$SECTION" || true)"
if [ "${n:-0}" -ge 1 ]; then
  _ok "AC-5: the README section says, on one line, that Edit(path) is the only file deny rule matched"
else
  _bad "AC-5: the README section says, on one line, that Edit(path) is the only file deny rule matched" \
    "no line of the section holds the sentence"
fi
# excerpt <needle> <text>   Each line of <text> holding <needle>, cut to the
# needle and 40 characters either side, so a failure names the offending
# phrase rather than printing a whole section.
excerpt() {
  awk -v n="$1" '{ i = index($0, n); if (i) { s = i > 40 ? i - 40 : 1
                   print "..." substr($0, s, length(n) + 80) "..." } }' <<< "$2"
}
# no_needle <what> <needle> <text>
no_needle() {
  local hits; hits="$(excerpt "$2" "$3")"
  if [ -z "$hits" ]; then _ok "$1"; else _bad "$1" "holds \"$2\" at: $hits"; fi
}
# The first four needles are AC-5's, verbatim. The fifth is the backticked
# spelling the two documents actually use today ("`Write`, `Edit` and
# `MultiEdit`"): AC-5's own `Write, Edit` cannot match that text, so without it
# nothing here would see the rules.md bullet's wrong claim.
for needle in 'TOOLS' 'Write(' 'MultiEdit(' 'Write, Edit' '`Write`, `Edit`'; do
  no_needle "AC-5: the README section does not say $needle" "$needle" "$SECTION"
  no_needle "AC-5: the rules.md state bullet does not say $needle" "$needle" "$BULLET"
done
# Contract C-3's replacement wording for the bullet, read out.
C3='denied to `Edit` in `settings.json` - the one file deny rule the runtime matches, and it covers `Write` and `MultiEdit` too'
case "$BULLET" in
  *"$C3"*) _ok "AC-5/C-3: the rules.md state bullet says the two are denied to Edit, which covers Write and MultiEdit" ;;
  *) _bad "AC-5/C-3: the rules.md state bullet says the two are denied to Edit, which covers Write and MultiEdit" \
       "expected: $C3
actual:   $(excerpt 'denied to' "$BULLET")" ;;
esac

# ---------------------------------------------------------------------------
describe "HARNESS-050 AC-6: the suite has no tool list"

# The needle is built from two halves so that this file's own text never holds
# it - a literal here would be the one definition the check always finds.
v='TOOL'; v="${v}S"
SELF="${BASH_SOURCE[0]}"
n="$(grep -cE -- "(^|[^A-Za-z0-9_])${v}=" "$SELF" || true)"
assert_eq "AC-6: settings.test.sh defines no variable named the tool list" 0 "${n:-0}"
n="$(grep -cE -- "\\\$\\{?${v}([^A-Za-z0-9_]|\$)" "$SELF" || true)"
assert_eq "AC-6: settings.test.sh reads no variable named the tool list" 0 "${n:-0}"
# Control: the same two readers find the definition and the read in the shape
# the suite used to have.
printf '%s="Write Edit MultiEdit"\nfor tool in $%s; do :; done\n' "$v" "$v" > "$FIX/old-suite.sh"
d1="$(grep -cE -- "(^|[^A-Za-z0-9_])${v}=" "$FIX/old-suite.sh" || true)"
d2="$(grep -cE -- "\\\$\\{?${v}([^A-Za-z0-9_]|\$)" "$FIX/old-suite.sh" || true)"
assert_eq "AC-6 control: both readers find the old suite's definition and read" "1 1" "${d1:-0} ${d2:-0}"

# ---------------------------------------------------------------------------
describe "HARNESS-029 AC-6: a surviving mutations/*.new has a row, and the paragraph says what it means"

# mutate.sh builds the mutated text in a `.new` beside the backup. After
# HARNESS-029 it removes it on every path it can run code on, so one that
# survives means the run was killed outright - and it arrives with its `.bak`.
# The row is matched whole, like AC-7's above: path, writer, a read-by cell
# that says nothing reads it, hand-editable yes. grep -E, no interval
# expressions (HARNESS-025: CI's awk and grep dialects differ from this host's).
# new_row <readme>   How many table rows say that.
new_row() {
  tr -d '\r' < "$1" | grep -cE -- '^\| `mutations/\*\.new` +\| `scripts/mutate\.sh` +\| nothing[^|]*\| yes +\|$'
}
assert_eq "AC-6: README has one mutations/*.new row, written by scripts/mutate.sh, read by nothing, hand-editable yes" \
  1 "$(new_row "$README")"
# Control: the reader finds the row it is looking for in a table that has it,
# so a miss above is the README's and not a mis-escaped pattern.
printf -- '| File | Written by | Read by | Hand-editable |\n|---|---|---|---|\n| `mutations/*.new` | `scripts/mutate.sh` | nothing | yes |\n' > "$FIX/new-row.md"
assert_eq "AC-6 control: the same reader finds a row written to the AC" 1 "$(new_row "$FIX/new-row.md")"

# mutations_para <readme>   The paragraph that opens "`mutations/` is", joined
# onto one line. No `exit` in the awk: it reads to the end rather than leave a
# writer behind it.
mutations_para() {
  awk '{ sub(/\r$/, "") }
       f == 1 && /^$/ { f = 2 }
       f == 0 && /^`mutations\/` is/ { f = 1 }
       f == 1 { printf "%s ", $0 }' "$1"
}
para="$(mutations_para "$README")"
assert_contains "AC-6: the mutations/ paragraph is found" '`mutations/` is' "$para"
assert_contains "AC-6: the mutations/ paragraph names a surviving .new" ".new" "$para"
assert_contains "AC-6: and says it means the run was killed outright" "killed outright" "$para"

# ---------------------------------------------------------------------------
describe "HARNESS-047: git log and git diff stay allowed, and their --output is denied"

# AC-1 and AC-2 on the live file. Red until GREEN appends the two C-1 lines to
# the deny array: today it prints the two `deny has no` lines.
assert_eq "AC-1/AC-2: the live settings.json denies git log/diff --output and still allows git log/diff" \
  "" "$(git_output_rules "$SETTINGS")"

# AC-3: fixture copies OF THE LIVE FILE, never hand-written, so that every
# other line in them is the shipped one. Before GREEN the live file lacks the
# C-1 lines, so a compliant copy is built by inserting them; after GREEN it
# already has them. `edit_array` therefore first DROPS both and then ADDS what
# a case wants, which yields the same text either side of GREEN.
#
# edit_array <file> <block> add|drop <rule>   In place. `add` appends "<rule>"
# as the last element of that array, giving the element before it a comma;
# `drop` removes the element that is exactly "<rule>", and the element left
# last loses its comma. Indented six spaces, as the live file's elements are.
edit_array() {
  awk -v k="\"$2\": [" -v op="$3" -v r="\"$4\"" '
    { sub(/\r$/, "") }
    f && /^[[:space:]]*\]/ {
      if (op == "add") {
        if (last != "") { if (last !~ /,$/) last = last ","; print last }
        print "      " r
      } else if (last != "") { sub(/,$/, "", last); print last }
      last = ""; f = 0; print; next
    }
    f {
      t = $0; sub(/^[[:space:]]+/, "", t); sub(/[[:space:]]+$/, "", t); sub(/,$/, "", t)
      if (op == "drop" && t == r) next
      if (last != "") { if (last !~ /,$/) last = last ","; print last }
      last = $0; next
    }
    index($0, k) { f = 1 }
    { print }' "$1" > "$1.tmp" && mv "$1.tmp" "$1"
}
# without_c1   $FIX/live.json: the live file with neither C-1 line.
without_c1() {
  tr -d '\r' < "$SETTINGS" > "$FIX/live.json"
  edit_array "$FIX/live.json" deny drop 'Bash(git log *--output*)'
  edit_array "$FIX/live.json" deny drop 'Bash(git diff *--output*)'
}
# compliant   $FIX/live.json: the live file as C-1 says it must end up.
compliant() {
  without_c1
  edit_array "$FIX/live.json" deny add 'Bash(git log *--output*)'
  edit_array "$FIX/live.json" deny add 'Bash(git diff *--output*)'
}
g() { git_output_rules "$FIX/live.json"; }

# Controls first: the checker is silent on the copy C-1 describes, and so on
# the shape GREEN must produce. Passes today, as a fixture.
compliant
assert_eq "AC-3 control: a copy with both C-1 lines appended to deny produces nothing" "" "$(g)"
# The same copy with CRLF line endings: a checkout that converts them must not
# turn every anchored match into a miss.
sed 's/$/\r/' "$FIX/live.json" > "$FIX/crlf.json"
assert_eq "AC-3 control: the same copy with CRLF endings produces nothing" \
  "" "$(git_output_rules "$FIX/crlf.json")"
# The copy with neither line is what the live file is today: both complaints,
# deny log first, and nothing about allow.
without_c1
assert_eq "AC-1 control: a copy with neither C-1 line names both, and nothing else" \
  'deny has no "Bash(git log *--output*)"
deny has no "Bash(git diff *--output*)"' "$(g)"

# (a) one deny line removed, each way round.
compliant
edit_array "$FIX/live.json" deny drop 'Bash(git diff *--output*)'
assert_eq "AC-3a: a copy missing the git diff deny names exactly that rule" \
  'deny has no "Bash(git diff *--output*)"' "$(g)"
compliant
edit_array "$FIX/live.json" deny drop 'Bash(git log *--output*)'
assert_eq "AC-3a: a copy missing the git log deny names exactly that rule" \
  'deny has no "Bash(git log *--output*)"' "$(g)"

# (b) the `:*` spelling, which the docs recognise only at the end of a rule.
without_c1
edit_array "$FIX/live.json" deny add 'Bash(git log:*--output*)'
edit_array "$FIX/live.json" deny add 'Bash(git diff *--output*)'
assert_eq "AC-3b: a deny spelled Bash(git log:*--output*) is a miss, named once" \
  'deny has no "Bash(git log *--output*)"' "$(g)"

# (c) the right strings in the wrong array: an allow is not a deny.
without_c1
edit_array "$FIX/live.json" allow add 'Bash(git log *--output*)'
edit_array "$FIX/live.json" allow add 'Bash(git diff *--output*)'
assert_eq "AC-3c: both deny strings moved into allow name both, and nothing else" \
  'deny has no "Bash(git log *--output*)"
deny has no "Bash(git diff *--output*)"' "$(g)"

# AC-2's half: option B keeps the allows. Removing either is option A, and the
# checker names it - so a checker that never read the allow array fails here.
compliant
edit_array "$FIX/live.json" allow drop 'Bash(git diff:*)'
assert_eq "AC-2: a copy without the git diff allow names exactly that rule" \
  'allow has no "Bash(git diff:*)"' "$(g)"
compliant
edit_array "$FIX/live.json" allow drop 'Bash(git log:*)'
assert_eq "AC-2: a copy without the git log allow names exactly that rule" \
  'allow has no "Bash(git log:*)"' "$(g)"
# ...and an allow moved into deny is still missing from allow.
compliant
edit_array "$FIX/live.json" allow drop 'Bash(git log:*)'
edit_array "$FIX/live.json" deny add 'Bash(git log:*)'
assert_eq "AC-2: the git log allow moved into deny is still named as missing from allow" \
  'allow has no "Bash(git log:*)"' "$(g)"

# C-1's placement, byte for byte: the two lines are the LAST two elements of
# deny, after the state-file Edit entries, six-space indent, comma on the line before
# and none after - which is also what keeps the JSON valid, and nothing else
# here could tell. Red until GREEN.
compliant
if tr -d '\r' < "$SETTINGS" | cmp -s - "$FIX/live.json"; then
  _ok "C-1: settings.json is the live file with exactly the two lines appended to deny"
else
  _bad "C-1: settings.json is the live file with exactly the two lines appended to deny" \
    "$(tr -d '\r' < "$SETTINGS" | diff - "$FIX/live.json")"
fi

summary "settings"
