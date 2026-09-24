#!/usr/bin/env bash
# Shared helpers for the harness's own tests.
#
# These test the harness, not a project built with it: the hooks, the path
# classifier and the phase lock. They need nothing but bash, git and coreutils,
# which is deliberate - they must run on a machine where no stack has been
# chosen yet.
#
# Every test runs against a FIXTURE repository in a temp directory, never
# against this checkout: a test that writes to the real tree, or that reads the
# real .claude/state, would be both dangerous and dependent on whatever story
# happens to be active.

set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/../.." && pwd)"

_pass=0; _fail=0; _current=""

# --- reporting ---------------------------------------------------------------

describe() { _current="$1"; printf '\n  %s\n' "$1"; }

_ok()  { _pass=$((_pass+1)); [ -n "${VERBOSE:-}" ] && printf '    ok   %s\n' "$1"; return 0; }
_bad() {
  _fail=$((_fail+1))
  printf '    FAIL %s\n' "$1"
  printf '%s\n' "$2" | sed -e 's/^/         /'
}

# summary <suite name>
#
# THE FORMAT STRING BELOW IS LOAD BEARING OUTSIDE THIS FILE. Since MT-039,
# scripts/selftest.sh reads the `N` of `<name>: N passed, M failed` back out of
# each suite's stdout and compares it against that suite's floor in
# .claude/tests/floors.conf - so this is the count a suite declares it did, and
# not merely something printed for a human. It is matched anchored and by name,
# `^<name>: ([0-9]+) passed, ([0-9]+) failed$`, and the LAST match wins.
#
# Change the wording and every floor stops being read. `.claude/tests/
# selftest.test.sh` pins the string at the other end so that cannot happen
# quietly; if you are here to reword it, change that suite in the same commit.
summary() { # <suite name>
  printf '\n%s: %d passed, %d failed\n' "$1" "$_pass" "$_fail"
  [ "$_fail" -eq 0 ] || return 1
  return 0
}

assert_eq() { # <what> <expected> <actual>
  if [ "$2" = "$3" ]; then _ok "$1"; else _bad "$1" "expected: $2
actual:   $3"; fi
}

assert_contains() { # <what> <needle> <haystack>
  case "$3" in
    *"$2"*) _ok "$1" ;;
    *) _bad "$1" "expected to contain: $2
actual:               $3" ;;
  esac
}

# assert_not_contains <what> <needle> <haystack>   The negative control's
# assertion. "It reports X" is satisfied by a run that reports X AND the wrong
# thing beside it, so a criterion phrased as "something other than PASS" needs
# this rather than a second assert_contains.
assert_not_contains() { # <what> <needle> <haystack>
  case "$3" in
    *"$2"*) _bad "$1" "expected NOT to contain: $2
actual:                   $3" ;;
    *) _ok "$1" ;;
  esac
}

# --- fixture -----------------------------------------------------------------

# make_fixture   Creates a throwaway repository that looks enough like a project
# for the hooks to work on, and echoes its path. paths.conf and phases.conf are
# COPIES OF THE REAL ONES: the classification rules under test are the ones
# this repository actually ships.
make_fixture() {
  local d
  d="$(mktemp -d 2>/dev/null || mktemp -d -t harness)"
  mkdir -p "$d/.claude/harness" "$d/.claude/state" "$d/src" "$d/tests" "$d/docs/backlog/stories"
  cp "$REPO_ROOT/.claude/harness/paths.conf"  "$d/.claude/harness/paths.conf"
  cp "$REPO_ROOT/.claude/harness/phases.conf" "$d/.claude/harness/phases.conf"
  # The real stamp, for the same reason the confs are the real ones: a fixture
  # carrying a made-up version would let doctor.sh print anything and pass.
  cp "$REPO_ROOT/.claude/harness/VERSION"     "$d/.claude/harness/VERSION" 2>/dev/null
  printf 'export const x = 1\n' > "$d/src/main.ts"
  printf 'test("x", () => {})\n' > "$d/tests/main.test.ts"
  printf '# notes\n' > "$d/docs/notes.md"
  cat > "$d/.gitignore" <<'EOF'
node_modules/
dist/
.vitest/
playwright-report/
EOF
  git -C "$d" init -q 2>/dev/null
  git -C "$d" add -A >/dev/null 2>&1
  printf '%s' "$d"
}

# make_project_fixture   A fixture that can RUN the harness, not merely be
# classified by it: the real scripts and hooks copied in, so that gates.sh,
# phase.sh and doctor.sh execute against a throwaway project.conf. Echoes its
# path. The gate commands a suite writes into that conf should be `printf`s -
# these tests are about the gate machinery, not about any real toolchain.
make_project_fixture() {
  local d
  d="$(make_fixture)"
  cp -r "$REPO_ROOT/scripts"        "$d/scripts"
  cp -r "$REPO_ROOT/.claude/hooks"  "$d/.claude/hooks"
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@t -c user.name=t commit -qm fixture >/dev/null 2>&1
  printf '%s' "$d"
}

# write_conf <fixture>   project.conf body on stdin, with BOOTSTRAPPED=yes so
# the fixture behaves like a project whose stack is real.
write_conf() {
  { printf 'BOOTSTRAPPED=yes\n'; cat; } > "$1/.claude/harness/project.conf"
}

# story <fixture> <id> <phase>   A minimal story file, plus any extra
# frontmatter lines on stdin.
story() {
  local extra; extra="$(cat)"
  mkdir -p "$1/docs/backlog/stories"
  {
    printf -- '---\nid: %s\ntitle: Fixture story\nslug: fixture\ntype: feature\nstatus: todo\nphase: %s\nbranch: story/%s-fixture\n' "$2" "$3" "$2"
    [ -n "$extra" ] && printf '%s\n' "$extra"
    printf -- '---\n\n## Acceptance criteria\n\n- **AC-1** - it works.\n\n## Gate results\n\n## Notes\n'
  } > "$1/docs/backlog/stories/$2.md"
}

# set_phase <fixture> <PHASE>   Activates a story in the fixture. An empty
# phase clears it, which is how "no active story" is tested.
set_phase() {
  if [ -z "${2:-}" ]; then
    rm -f "$1/.claude/state/current-story.env"
  else
    printf 'STORY_ID=T-1\nSTORY_SLUG=fixture\nSTORY_TYPE=feature\nPHASE=%s\nBRANCH=story/T-1-fixture\n' "$2" \
      > "$1/.claude/state/current-story.env"
  fi
}

# --- driving the hook --------------------------------------------------------

# json_str <text>   The text as a JSON string body. awk, not parameter
# expansion: `${s//\\/\\\\}` is not a reliable way to double a backslash in
# bash, and a helper that silently drops every backslash before the hook runs
# makes a test about backslashes assert nothing. That is exactly what happened
# to the "escaped redirect inside a string" case for a while.
json_str() {
  printf '%s' "$1" | awk 'BEGIN { ORS = "" }
    { gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); gsub(/\t/, "\\t")
      if (NR > 1) printf "\\n"
      printf "%s", $0 }'
}

# guard <fixture> <tool> <key> <value>   Runs the real phase-guard hook and
# echoes the denial reason, or nothing when the write was allowed.
guard() {
  local out r BS
  out="$(printf '{"tool_name":"%s","tool_input":{"%s":"%s"}}' "$2" "$3" "$(json_str "$4")" \
    | CLAUDE_PROJECT_DIR="$1" bash "$REPO_ROOT/.claude/hooks/phase-guard.sh" 2>&1)"
  case "$out" in
    *'"permissionDecision":"deny"'*) ;;
    *) printf ''; return 0 ;;
  esac
  # The reason, unescaped enough to assert on. Parameter expansion rather than
  # sed: a suite about backslashes should not route its own assertions through
  # a tool whose handling of them varies by platform.
  BS=$(printf '\134')
  r="${out#*permissionDecisionReason\":\"}"
  r="${r%\"\}\}*}"
  # Quoted, so that the backslash is matched literally rather than read as the
  # pattern's own escape character - unquoted, this deletes every letter n.
  r="${r//"${BS}n"/ }"
  r="${r//"${BS}t"/ }"
  printf '%s' "$r"
}

guard_bash() { guard "$1" Bash command "$2"; }

# assert_allowed <fixture> <command> [label]
assert_allowed() {
  local r; r="$(guard_bash "$1" "$2")"
  if [ -z "$r" ]; then _ok "allows: ${3:-$2}"
  else _bad "allows: ${3:-$2}" "blocked with: $r"; fi
}

# assert_blocked <fixture> <command> <expected path> [label]
assert_blocked() {
  local r; r="$(guard_bash "$1" "$2")"
  if [ -z "$r" ]; then
    _bad "blocks: ${4:-$2}" "not blocked at all"
  else
    case "$r" in
      *"path:     $3 "*|*"path:     $3") _ok "blocks: ${4:-$2}" ;;
      *) _bad "blocks: ${4:-$2}" "blocked, but on the wrong path (wanted '$3'): $r" ;;
    esac
  fi
}

# --- the manifest parser (MT-040) ---------------------------------------------

# MANIFEST_SNAPSHOT   A byte-for-byte copy of .claude/harness/project.conf as it
# stood at 76ed934, the 629-line manifest MT-040's criteria are stated against.
# A copy rather than the live file so that a later story editing project.conf
# does not break a byte-identity test whose oracle was captured from this one.
MANIFEST_FIXTURES="$TESTS_DIR/fixtures/manifest-parse"
MANIFEST_SNAPSHOT="$MANIFEST_FIXTURES/project.conf"

# The shipped trim() body before MT-040, as the ORACLE for trim equivalence and
# as the needle AC-5 searches for. Read from a heredoc so no quoting is lost.
TRIM_SED_BODY="$(cat <<'BODY'
sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
BODY
)"

# extract_fn <script> <name>   The source text of a function as the script
# defines it: from `<name>()` to the line where its braces balance. So a test
# exercises the definition the script SHIPS, not a copy pasted into the test.
extract_fn() {
  awk -v n="$2" '
    !on && $0 ~ ("^[[:space:]]*" n "[[:space:]]*[(][)]") { on = 1 }
    on {
      print
      o = gsub(/\{/, "{"); c = gsub(/\}/, "}"); d += o - c
      if (o + c > 0 && d <= 0) exit
    }' "$1"
}

# trim_inputs <file>   AC-4's input set, one per line: every line of the
# manifest snapshot, then the five edge cases AC-4 names, then a sixth for the
# carriage return doctor.sh and task.sh rely on trim() to remove (neither
# strips `\r` itself). Line numbers of the edge cases are fixed: 630..635.
trim_inputs() {
  { cat "$MANIFEST_SNAPSHOT"
    printf '\n'                                   # 630 empty string
    printf ' \t  \t \n'                           # 631 all whitespace
    printf '   inner  spaces   survive   \n'      # 632 multi-space around inner spaces
    printf '\ttab-padded value\t\t\n'             # 633 tab-padded
    printf 'no-surrounding-space\n'               # 634 no surrounding space
    printf ' crlf value \r\n'                     # 635 carriage return
  } > "$1"
}

# trim_oracle <inputs> <out>   The shipped sed form, applied ONCE over the whole
# file: sed is line-oriented, so this is the per-line trim of every input
# without spawning one process per line.
trim_oracle() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$1" > "$2"; }

# apply_trim <script> <inputs> <out>   Every input through the trim() the
# script defines, called the way its call sites call it: `$(trim "$x")`.
apply_trim() {
  local fn; fn="$(extract_fn "$1" trim)"
  ( eval "$fn"
    while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "$(trim "$l")"; done < "$2"
  ) > "$3"
}

# disagreements <expected> <actual>   "<count>" then up to three
# "line N: expected [..] got [..]" lines. A differing line count is itself a
# disagreement on every missing line.
disagreements() {
  awk 'NR == FNR { e[FNR] = $0; ne = FNR; next }
       { a[FNR] = $0; na = FNR }
       END {
         n = (ne > na ? ne : na); bad = 0; out = ""
         for (i = 1; i <= n; i++) if (!(i in e) || !(i in a) || e[i] != a[i]) {
           bad++
           if (bad <= 3) out = out sprintf("line %d: expected [%s] got [%s]\n", i, e[i], a[i])
         }
         printf "%d\n%s", bad, out
       }' "$1" "$2"
}
