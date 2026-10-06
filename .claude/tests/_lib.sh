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
# THE FORMAT STRING BELOW IS LOAD BEARING OUTSIDE THIS FILE. scripts/selftest.sh
# reads the `N` of `<name>: N passed, M failed` back out of each suite's stdout
# and compares it against that suite's floor in .claude/tests/floors.conf - so
# this is the count a suite declares it did, and not merely something printed
# for a human. It is matched anchored and by name,
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
  d="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
  mkdir -p "$d/.claude/harness" "$d/.claude/state" "$d/src" "$d/src/lib" \
           "$d/tests" "$d/tests/guards" "$d/docs/backlog/stories"
  cp "$REPO_ROOT/.claude/harness/paths.conf"  "$d/.claude/harness/paths.conf"
  cp "$REPO_ROOT/.claude/harness/phases.conf" "$d/.claude/harness/phases.conf"
  cp "$REPO_ROOT/.claude/harness/models.conf" "$d/.claude/harness/models.conf" 2>/dev/null
  # The real stamp, for the same reason the confs are the real ones: a fixture
  # carrying a made-up version would let doctor.sh print anything and pass.
  cp "$REPO_ROOT/.claude/harness/VERSION"     "$d/.claude/harness/VERSION" 2>/dev/null
  printf 'export const x = 1\n' > "$d/src/main.ts"
  printf 'test("x", () => {})\n' > "$d/tests/main.test.ts"
  printf '# notes\n' > "$d/docs/notes.md"
  # Paths whose NAME contains the two-character sequence `-i`. WORLD-080: the
  # guard's `sed -i` extractor matched that substring anywhere after the word
  # `sed`, so `sed -n '1,5p' tests/guards/layer-imports.test.ts` - a pure read -
  # was refused as an in-place write, on the file it was reading. No path in
  # this fixture contained `-i`, which is the whole reason the suite passed
  # over the defect. One per category the classifier can reach:
  #   src/lib/layer-imports.ts        -> source
  #   tests/guards/layer-imports.test.ts -> test  (frozen in DONE, NOT in RED)
  #   notes-inline.txt                -> source, via the paths.conf fallback
  printf 'export const y = 2\n'  > "$d/src/lib/layer-imports.ts"
  printf 'test("y", () => {})\n' > "$d/tests/guards/layer-imports.test.ts"
  printf 'inline notes\n'        > "$d/notes-inline.txt"
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

# hook_cwd_field   `"cwd":"<GUARD_CWD>",` when GUARD_CWD is set, else nothing.
# The host sends the session's working directory in every hook input. It is
# placed ahead of tool_name, as the host places it (HARNESS-035).
hook_cwd_field() {
  [ -n "${GUARD_CWD:-}" ] && printf '"cwd":"%s",' "$(json_str "$GUARD_CWD")"
  return 0
}

# guard <fixture> <tool> <key> <value>   Runs the real phase-guard hook and
# echoes the denial reason, or nothing when the write was allowed. With
# GUARD_CWD set, the input carries that `cwd` (HARNESS-035).
guard() {
  local out r BS
  out="$(printf '{%s"tool_name":"%s","tool_input":{"%s":"%s"}}' "$(hook_cwd_field)" "$2" "$3" "$(json_str "$4")" \
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

# --- the manifest parser (HARNESS-024) -----------------------------------------
#
# gates.sh, doctor.sh and task.sh each parsed project.conf with a `sed` trim()
# and a `cut -d'|'` per field. These helpers are the instruments that judge the
# rewrite: a synthetic manifest and its goldens, a trace counter, and the trim
# oracle. Ported in shape from manga-translator MT-040 (d668336); the fixture
# is NOT downstream's - it is upstream-owned and synthetic, because an
# assertion about a real project's manifest values fails in every other tree.

# MANIFEST_FIXTURES   project.conf (well-formed, --audit rc 0), broken.conf (one
# of every --audit failure, rc 1), and the goldens captured from the scripts as
# they stood BEFORE the rewrite (ea0fba0). The story's handoff records how each
# golden was captured and its sha256. The directory's own .gitattributes keeps
# git from normalising the carriage returns some goldens contain.
MANIFEST_FIXTURES="$TESTS_DIR/fixtures/manifest"

# The shipped trim() body before HARNESS-024: the ORACLE for trim equivalence,
# and the needle AC-6 searches the three scripts for. A heredoc, so no quoting
# is lost on the way in.
TRIM_SED_BODY="$(cat <<'BODY'
sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
BODY
)"

# extract_fn <script> <name>   The source text of a function as the script
# defines it: from `<name>()` to the line where its braces balance. So a test
# exercises the definition the script SHIPS, not a copy pasted into the test.
# Empty when the script defines no such function.
extract_fn() {
  awk -v n="$2" '
    !on && $0 ~ ("^[[:space:]]*" n "[[:space:]]*[(][)]") { on = 1 }
    on {
      print
      o = gsub(/\{/, "{"); c = gsub(/\}/, "}"); d += o - c
      if (o + c > 0 && d <= 0) exit
    }' "$1"
}

# manifest_fixture   A project fixture (the real scripts and hooks copied in)
# whose project.conf is the synthetic well-formed manifest, committed, with no
# active story. Echoes its path. The goldens were captured through this same
# function, so the tree they describe is the tree the tests rebuild.
manifest_fixture() {
  local d
  d="$(make_project_fixture)"
  cp "$MANIFEST_FIXTURES/project.conf" "$d/.claude/harness/project.conf"
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@t -c user.name=t commit -qm "manifest fixture" >/dev/null 2>&1
  printf '%s' "$d"
}

# use_manifest <fixture> <conf>   Make <conf> the fixture's project.conf.
use_manifest() { cp "$2" "$1/.claude/harness/project.conf"; }

# crlf_copy <in> <out>   The same manifest with every line ending CRLF.
crlf_copy() { awk '{ printf "%s\r\n", $0 }' "$1" > "$2"; }

# pad_manifest <in> <out>   The same manifest with exactly 100 comment and blank
# lines interleaved through it, deterministically: before input line i, padding
# is emitted until int(100 * i / N) lines have been written, so it is spread
# over the whole file and the LAST line has padding before it. Five shapes in
# rotation - a `#` comment, a blank line, a TAB-indented comment, a
# whitespace-only line, and a commented-out gate line full of pipes - none of
# which any parser may read as data.
pad_manifest() {
  awk 'NR == FNR { n = FNR; next }
       {
         want = int(100 * FNR / n)
         while (p < want) {
           k = p % 5
           if      (k == 0) printf "# padding comment %d\n", p
           else if (k == 1) printf "\n"
           else if (k == 2) printf "\t# tab-indented padding %d\n", p
           else if (k == 3) printf " \t  \n"
           else             printf "#\tgate | pad%d | required | . | exit 1\n", p
           p++
         }
         print
       }' "$1" "$1" > "$2"
}

# gates_golden <fixture> <list|audit|run>   gates.sh's output in that mode,
# stdout and stderr, then `rc=<status>`. In `run` mode the duration field
# `(<N>s` is normalised to `(Ns` - the ONE normalisation AC-3 allows - and
# nothing else is touched.
gates_golden() {
  local out rc
  case "$2" in
    list)  out="$( cd "$1" && bash scripts/gates.sh --list 2>&1 )"; rc=$? ;;
    audit) out="$( cd "$1" && bash scripts/gates.sh --audit 2>&1 )"; rc=$? ;;
    run)   out="$( cd "$1" && bash scripts/gates.sh 2>&1 )"; rc=$?
           out="$(printf '%s\n' "$out" | sed -E 's/\(([0-9]+)s([,)])/(Ns\2/g')" ;;
  esac
  printf '%s\nrc=%s\n' "$out" "$rc"
}

# doctor_golden <fixture>   The `Project toolchain` and `Test discovery`
# sections of doctor.sh's output, each from its heading to the next unindented
# line. The other sections carry this machine's paths and versions.
doctor_golden() {
  ( cd "$1" && bash scripts/doctor.sh 2>&1 ) \
    | awk '/^[^ ]/ { on = ($0 ~ /^Project toolchain/ || $0 ~ /^Test discovery$/) } on'
}

# MANIFEST_TASKS   Every task id in the synthetic manifest, plus one it lacks.
MANIFEST_TASKS="pipes where idle nope"

# task_golden <fixture> [nolist]   task.sh with no argument, then `task.sh <id>
# extra` for each of MANIFEST_TASKS, each block headed by the command and
# closed by its exit status. `nolist` leaves out the no-argument listing, which
# the CRLF golden must: that listing is one `awk` (out of scope, unchanged by
# the story), and what it prints for a CRLF manifest is the PLATFORM's, not the
# script's - MSYS awk reads in text mode and drops the carriage return, Linux
# awk keeps it in the last field. No single golden for it can hold on both.
task_golden() {
  local id out rc
  if [ "${2:-}" != nolist ]; then
    out="$( cd "$1" && bash scripts/task.sh 2>&1 )"; rc=$?
    printf '$ task.sh\n%s\nrc=%s\n' "$out" "$rc"
  fi
  for id in $MANIFEST_TASKS; do
    out="$( cd "$1" && bash scripts/task.sh "$id" extra 2>&1 )"; rc=$?
    printf '$ task.sh %s extra\n%s\nrc=%s\n' "$id" "$out" "$rc"
  done
}

# golden_check <what> <golden file> <actual file>   Byte-for-byte, with the
# first differing lines as the failure detail.
golden_check() {
  if cmp -s "$2" "$3"; then
    _ok "$1"
  else
    _bad "$1" "$(diff "$2" "$3" 2>&1 | awk 'NR <= 20')"
  fi
}

# trim_inputs <file>   AC-5's input set, one per line: every line of the
# synthetic manifest, then the six edge cases AC-5 names. Their line numbers
# are TRIM_EDGE+1 .. TRIM_EDGE+6, in this order; it sets TRIM_EDGE, the
# manifest's line count.
trim_inputs() {
  TRIM_EDGE="$(awk 'END { print NR }' "$MANIFEST_FIXTURES/project.conf")"
  { cat "$MANIFEST_FIXTURES/project.conf"
    printf '\n'                                   # +1 empty
    printf ' \t  \t \n'                           # +2 all whitespace
    printf '   inner  spaces   survive   \n'      # +3 multi-space around inner spaces
    printf '\ttab-padded value\t\t\n'             # +4 tab-padded
    printf 'no-surrounding-space\n'               # +5 no surrounding space
    printf ' crlf value \r\n'                     # +6 trailing carriage return
  } > "$1"
}

# trim_oracle <inputs> <out>   The shipped sed form, applied ONCE over the whole
# file: sed is line-oriented, so this is the per-line trim of every input
# without one process per line.
trim_oracle() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$1" > "$2"; }

# apply_trim <script> <inputs> <out> [print|assign]   Every input through the
# trim() the script defines. `print` (the default) calls it as `$(trim "$x")`,
# the form doctor.sh's release_of() keeps; `assign` as `trim "$x" var`, the
# form every parse-loop call site uses (C-1). The variable is preset to a
# sentinel, so a trim that ignores its second argument is seen to.
apply_trim() {
  local fn; fn="$(extract_fn "$1" trim)"
  ( eval "$fn"
    while IFS= read -r l || [ -n "$l" ]; do
      if [ "${4:-print}" = assign ]; then
        _trimmed="<unassigned>"; trim "$l" _trimmed >/dev/null; printf '%s\n' "$_trimmed"
      else
        printf '%s\n' "$(trim "$l")"
      fi
    done < "$2"
  ) > "$3" 2>/dev/null
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

# line_of <n> <file>   Line n of a file, for the trim controls.
line_of() { awk -v n="$1" 'NR == n { print; exit }' "$2"; }

# trace_externals <trace> <script>...   AC-1's and AC-2's instrument. One
# "<count> <name>" line per external command found in a `bash -x` trace, then
# "<total> TOTAL".
#
# What it counts: every trace line (one or more `+`, then a space - the depth
# marks subshells and command substitutions) whose FIRST WORD, after stripping
# the quotes bash -x adds (`'['`), is a program on PATH and is neither a bash
# builtin or keyword nor a function defined in the named scripts. Pure
# assignments (`+ kind=gate`) are skipped. One such line is one exec'd process:
# bash -x traces each element of a pipeline, and each command substitution's
# commands, on a line of its own.
#
# What it does not count: forks that exec nothing (a `$(...)` whose body is all
# builtins). The criteria are about external processes, which is what the
# baseline counted. Process counts read from a trace, never wall clock, so the
# number is the same on CI and on a slow host.
trace_externals() {
  local trace="$1" funcs n w t total=0; shift
  funcs=" $(awk '/^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*\(\)/ {
      sub(/^[[:space:]]*/, ""); sub(/[[:space:]]*\(.*/, ""); printf "%s ", $0 }' "$@") "
  while read -r n w; do
    [ -n "$w" ] || continue
    case "$funcs" in *" $w "*) continue ;; esac
    t=" $(type -at -- "$w" 2>/dev/null | tr '\n' ' ') "
    case "$t" in *" builtin "*|*" keyword "*) continue ;; *" file "*) ;; *) continue ;; esac
    printf '%s %s\n' "$n" "$w"; total=$((total+n))
  done <<EOT
$(awk '
    /^\++ / {
      sub(/^\++ /, "")
      w = $1
      if (w ~ /^[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=/) next
      gsub(/^\047|\047$/, "", w)
      if (w != "") n[w]++
    }
    END { for (w in n) print n[w], w }' "$trace")
EOT
  printf '%s TOTAL\n' "$total"
}

# ext_count <counts> <name>   One name's count out of trace_externals' output;
# 0 when the name is absent.
ext_count() { printf '%s\n' "$1" | awk -v w="$2" '$2 == w { print $1; f = 1 } END { if (!f) print 0 }'; }

# trace_script <fixture> <out-prefix> <script> [args...]   Runs scripts/<script>
# in the fixture under `bash -x`: the trace to <out-prefix>.trace, stdout to
# <out-prefix>.out, the exit status to <out-prefix>.rc. Prints trace_externals'
# table for it, not counting functions defined in that script or in the hooks'
# lib.sh it may source. `-x` writes nothing to stdout, so <out-prefix>.out is
# the script's ordinary output - except inside a subshell whose stderr the
# script itself sends to stdout, as gates.sh does for a gate command.
trace_script() {
  local fix="$1" pre="$2" s="$3"; shift 3
  ( cd "$fix" && bash -x "scripts/$s" "$@" > "$pre.out" 2> "$pre.trace" )
  printf '%s\n' "$?" > "$pre.rc"
  trace_externals "$pre.trace" "$fix/scripts/$s" "$fix/.claude/hooks/lib.sh"
}

# same_count <what> <counts over the plain manifest> <counts over the padded>
# AC-2's assertion: the two TOTALs are equal. On failure, both tables, so the
# report names the command whose count grew with the manifest.
same_count() {
  local a b
  a="$(ext_count "$2" TOTAL)"; b="$(ext_count "$3" TOTAL)"
  if [ -n "$a" ] && [ "$a" = "$b" ]; then
    _ok "$1"
  else
    _bad "$1" "plain manifest: $a processes; padded (+100 comment/blank lines): $b
by command, plain:
$2
by command, padded:
$3"
  fi
}
