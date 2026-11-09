#!/usr/bin/env bash
# attest.sh: a verification run is recorded against the tree it ran on, and the
# orchestrator checks the record instead of re-running it (HARNESS-084).
#
# Three things are under test, and the story's Contract pins each:
#
#   * scripts/attest.sh (C-1, C-3, C-4) - run, record, check. Driven in a
#     project fixture (make_project_fixture: the real scripts and hooks copied
#     in), with commands that are tiny scripts this suite writes under $WORK, so
#     a command's words are the same string on every run.
#   * work_tree_hash in .claude/hooks/lib.sh (C-2) - gate_tree_hash plus the
#     untracked gated files. Called by sourcing the FIXTURE's copy of lib.sh,
#     so what is judged is the lib.sh this tree ships.
#   * attest_problems <root> (C-5) - a structural guard over the prose that
#     tells the subagents to attest and the orchestrator to check. Prose has no
#     executable behaviour; this is `tdd-cycle`'s "grep for the shape", in the
#     pattern of procedure.test.sh and policy.test.sh: run over REPO_ROOT, where
#     it must be silent, and over fixtures compliant by construction with one
#     site regressed, where it must print exactly the one line C-5 pins. The
#     fixtures are what make the real-tree assertion mean anything.
#
# Fixture categories, confirmed with `bash scripts/classify.sh` in a
# make_project_fixture tree before any assertion relies on them (C-8):
#   src/main.ts, src/x.sh, src/new.ts     source
#   tests/new.test.ts                     test
#   tsconfig.json                         config
#   docs/notes.md                         docs
#   .claude/commands/new.md, CLAUDE.md,   harness markdown: in the WORK hash (C-2 as
#   .claude/agents/role.md               amended by A-2), not in gate_tree_hash
#   scratch/out.ts                        source by name, but gitignored in WFIX
#   dist/out.js                           vendor  (and gitignored)
#   .claude/state/*                       harness by paths.conf, gitignored here
#                                         as in the real .gitignore, and dropped
#                                         by gated_stdin's `.claude/state/` rule
#
# CLAUDE_PROJECT_DIR is exported as the REAL repository for the whole suite.
# gates.sh takes its root from its own location and exports it; attest.sh run
# from a fixture must judge the fixture whatever the session's variable says,
# and pinning the variable to a different tree is what makes that observable
# on every host rather than only on the ones that happen to set it.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

export CLAUDE_PROJECT_DIR="$REPO_ROOT"
# ATTEST_TAIL is unset for the same reason: the default-tail assertions must
# see attest.sh's default, not whatever an outer `ATTEST_TAIL=2 attest.sh --
# selftest.sh attest` exported. The one assertion that wants it sets it
# through ATT_ENV.
unset ATTEST_TAIL

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
FIX=""; WFIX=""
trap 'rm -rf "$WORK" "$FIX" "$WFIX"' EXIT

# --- instruments ----------------------------------------------------------------

# count_line <exact line> <text>   How many lines of <text> are EXACTLY <line>.
# A here-string, not a pipe (check-sigpipe.sh); grep -c prints 0 itself
# (check-grep-count.sh).
count_line() {
  grep -cxF -- "$1" <<COUNT_IN
$2
COUNT_IN
}

# is_hash <s>   A git object id: 40 hex (sha1) or 64 (sha256), nothing else.
is_hash() { [[ $1 =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]; }

# assert_hash_eq <what> <expected> <actual>   Equal AND a hash. Two empty
# strings are equal, which is exactly what a missing function produces on both
# sides; this refuses that.
assert_hash_eq() {
  if is_hash "$2" && [ "$2" = "$3" ]; then _ok "$1"
  else _bad "$1" "expected the hash: $2
actual:            $3"; fi
}

# assert_hash_ne <what> <a> <b>   Both hashes, and different.
assert_hash_ne() {
  if is_hash "$2" && is_hash "$3" && [ "$2" != "$3" ]; then _ok "$1"
  else _bad "$1" "expected two different hashes:
before: $2
after:  $3"; fi
}

# whash <root>   work_tree_hash as <root>'s own lib.sh defines it, judging
# <root>. stdout only; returns its exit status.
whash() {
  local r
  r="$( cd "$1" 2>/dev/null && . "$1/.claude/hooks/lib.sh" && set_harness_root "$1" && work_tree_hash 2>/dev/null )"
  WRC=$?
  printf '%s' "$r"
  return "$WRC"
}

# ghash <root>   gate_tree_hash, the same way. The settled function C-2 builds on.
ghash() {
  ( cd "$1" && . "$1/.claude/hooks/lib.sh" && set_harness_root "$1" && gate_tree_hash 2>/dev/null )
}

# att [args...]   scripts/attest.sh in FIX. OUT, ERR := its stdout and stderr,
# RC := its exit status. ATT_ENV, when set, is one NAME=value put in attest.sh's
# own environment (ATTEST_TAIL).
att() {
  if [ -n "${ATT_ENV:-}" ]; then
    ( cd "$FIX" && env "$ATT_ENV" bash scripts/attest.sh "$@" ) > "$WORK/out" 2> "$WORK/err"
  else
    ( cd "$FIX" && bash scripts/attest.sh "$@" ) > "$WORK/out" 2> "$WORK/err"
  fi
  RC=$?
  OUT="$(cat "$WORK/out")"; ERR="$(cat "$WORK/err")"
}

# assert_block_eq <what> <expected block> <actual>   Equal, and the expected
# block is a record (it has a `run:` line). Two empty strings are equal, which
# is what a missing attest.sh produces on both sides; this refuses that.
assert_block_eq() {
  case "$2" in
    run:*) assert_eq "$1" "$2" "$3" ;;
    *) _bad "$1" "no record to compare against: [$2]" ;;
  esac
}

# now_stamp   gates.sh's stamp format, read out (C-3: `date -u +%Y-%m-%dT%H:%M:%SZ`).
now_stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

ALOG_REL=".claude/state/attest.log"

# last_block <file>   The last blank-line-separated block of <file>; empty when
# the file is missing.
last_block() { [ -f "$1" ] && awk 'BEGIN { RS = "" } { b = $0 } END { if (b != "") print b }' "$1"; return 0; }

# field <block> <key>   The value of `<key>:` in <block>: everything after the
# colon and the run of spaces that pads it. Empty when absent.
field() {
  local l
  while IFS= read -r l; do
    case "$l" in
      "$2:"*) l="${l#"$2:"}"; l="${l#"${l%%[! ]*}"}"; printf '%s' "$l"; return 0 ;;
    esac
  done <<FIELD_IN
$1
FIELD_IN
  return 0
}

# keys <block>   The field names of <block>, in order, space-joined.
keys() {
  local l k=""
  while IFS= read -r l; do
    [[ $l =~ ^([a-z]+): ]] && k="$k${k:+ }${BASH_REMATCH[1]}"
  done <<KEYS_IN
$1
KEYS_IN
  printf '%s' "$k"
}

# printed_block <stdout>   The record attest.sh printed: from its first line
# beginning `run:` up to, not including, the first blank line or `--- last `.
printed_block() {
  awk '!on && /^run:/ { on = 1 } on && (/^$/ || /^--- last /) { exit } on { print }' <<PB_IN
$1
PB_IN
}

# after_header <stdout>   The lines after the `--- last ` header, trailing blank
# lines dropped.
after_header() {
  awk 'on { print } /^--- last / { on = 1 }' <<AH_IN | awk '{ a[NR] = $0 } END { n = NR; while (n > 0 && a[n] == "") n--; for (i = 1; i <= n; i++) print a[i] }'
$1
AH_IN
}

# header_line <stdout>   The first line beginning `--- last `.
header_line() { awk '/^--- last / { print; exit }' <<HL_IN
$1
HL_IN
}

# last_line <text>   Its last line.
last_line() { awk '{ l = $0 } END { print l }' <<LL_IN
$1
LL_IN
}

# all_but_last <text>   Every line but the last, trailing blank lines dropped.
all_but_last() { awk '{ a[NR] = $0 } END { n = NR - 1; while (n > 0 && a[n] == "") n--; for (i = 1; i <= n; i++) print a[i] }' <<AL_IN
$1
AL_IN
}

# sum <file>   A checksum, or `absent`.
sum() { if [ -f "$1" ]; then cksum < "$1"; else printf absent; fi; }

# --- the fixture -----------------------------------------------------------------

FIX="$(make_project_fixture)"
# The real .gitignore ignores .claude/state/*; the fixture's should too, so the
# record and its logs are what they are in a real tree: untracked and ignored.
printf '.claude/state/*\n' >> "$FIX/.gitignore"
printf 'echo x\n' > "$FIX/src/x.sh"
# Tracked harness markdown, for AC-2's A-2 cases: an edit to either makes a
# record stale.
mkdir -p "$FIX/.claude/agents"
printf '# role\n' > "$FIX/.claude/agents/role.md"
printf '# house rules\n' > "$FIX/CLAUDE.md"
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "attest fixture" >/dev/null 2>&1

C="$WORK/cmds"
mkdir -p "$C"
# two.sh: two lines - the first on stdout, the second on stderr - then a blank
# line, then exit 3. "combined output", "last NON-BLANK line".
cat > "$C/two.sh" <<'EOF'
printf 'first line\n'
printf 'second line\n' >&2
printf '\n'
exit 3
EOF
cat > "$C/env.sh" <<'EOF'
printf 'NAME=%s\n' "${ATTEST_PROBE:-<unset>}"
EOF
# args.sh: one bracketed line per argument, so a re-split or a glob shows.
cat > "$C/args.sh" <<'EOF'
for a in "$@"; do printf '[%s]\n' "$a"; done
EOF
cat > "$C/thirty.sh" <<'EOF'
i=1; while [ $i -le 30 ]; do printf 'line %d\n' $i; i=$((i + 1)); done
EOF
# edit.sh: appends to a TRACKED source file while it runs (AC-3).
cat > "$C/edit.sh" <<'EOF'
printf 'echo more\n' >> src/x.sh
printf 'edited\n'
exit 5
EOF
# state.sh: writes only under .claude/state/ (AC-3's control).
cat > "$C/state.sh" <<'EOF'
mkdir -p .claude/state/sub
printf 'x\n' > .claude/state/scratch.txt
printf 'y\n' > .claude/state/sub/y.txt
printf 'wrote state\n'
EOF
# mark.sh: a side effect outside the tree, so its absence is a fact (AC-4).
cat > "$C/mark.sh" <<EOF
printf 'ran\n' > "$WORK/ac4-ran"
printf 'marked\n'
EOF
# vars.sh: prints the variables an assignment word might aim at attest.sh's
# own shell (finding 3), and leaves a side effect outside the tree.
cat > "$C/vars.sh" <<EOF
printf 'ran\n' > "$WORK/vars-ran"
printf 'ROOT=%s\n' "\${ROOT:-<unset>}"
printf 'ALOG=%s\n' "\${ALOG:-<unset>}"
printf 'HARNESS_ROOT=%s\n' "\${HARNESS_ROOT:-<unset>}"
EOF
# cpd.sh: prints the CLAUDE_PROJECT_DIR the command was given, UNSET when it
# was given none (return 4).
cat > "$C/cpd.sh" <<'EOF'
printf 'cpd=[%s]\n' "${CLAUDE_PROJECT_DIR-UNSET}"
EOF
# side.sh: a side effect outside the tree, for the refused-word cases (finding 4).
cat > "$C/side.sh" <<EOF
printf 'ran\n' > "$WORK/side-ran"
EOF

ALOG="$FIX/$ALOG_REL"
LOGRE='^\.claude/state/attest-logs/([0-9]{8}T[0-9]{6}Z)\.([0-9]+)\.log$'

# ==============================================================================
describe "C-2  work_tree_hash: one hash, moving on gated content tracked, staged or untracked"
# ==============================================================================

WFIX="$(make_project_fixture)"
# scratch/ is an ignored path whose files classify `source` by name: the
# ignored-path case below, as distinct from vendor (dist/).
printf '.claude/state/*\nscratch/\n' >> "$WFIX/.gitignore"
git -C "$WFIX" add -A >/dev/null 2>&1
git -C "$WFIX" -c user.email=t@t -c user.name=t commit -qm "ignore state" >/dev/null 2>&1

g0="$(ghash "$WFIX")"
w0="$(whash "$WFIX")"; w0rc=$?
if is_hash "$w0"; then _ok "work_tree_hash prints one hash on a clean tree"
else _bad "work_tree_hash prints one hash on a clean tree" "printed: [$w0]"; fi
assert_eq "work_tree_hash returns 0 on a clean tree" 0 "$w0rc"
# Holds by construction only while the tree carries no harness markdown: the
# work hash covers it (C-2 as amended by A-2) and gate_tree_hash does not. This
# fixture tracks none (its one .md is docs/notes.md), and this block adds some
# only further down, after the listing-shape assertions.
assert_hash_eq "with nothing untracked and no harness markdown, it IS gate_tree_hash: the same listing" \
  "$(ghash "$WFIX")" "$w0"

# An untracked TEST file - the RED subagent's usual new file.
printf 'test("n", () => {})\n' > "$WFIX/tests/new.test.ts"
w1="$(whash "$WFIX")"
assert_hash_ne "an untracked test file moves the work hash" "$w0" "$w1"
# The reason the function exists, pinned against the settled one: gate_tree_hash
# does not see it (HARNESS-014). Green on arrival; see the handoff.
assert_hash_eq "control: gate_tree_hash does not see that untracked file" "$g0" "$(ghash "$WFIX")"
# The listing shape, read out rather than re-derived: an untracked file counts
# EXACTLY as it would once staged - `<blob>\t<path>`, blob from git hash-object,
# through _hash_blob_listing - so the hash equals gate_tree_hash after `git add`.
git -C "$WFIX" add -- tests/new.test.ts >/dev/null 2>&1
assert_hash_eq "an untracked file is hashed exactly as gate_tree_hash hashes it once staged" \
  "$(ghash "$WFIX")" "$w1"
assert_hash_eq "and staging it does not move the work hash" "$w1" "$(whash "$WFIX")"
git -C "$WFIX" rm -q --cached -- tests/new.test.ts >/dev/null 2>&1
printf 'test("n", () => { expect(1) })\n' > "$WFIX/tests/new.test.ts"
w2="$(whash "$WFIX")"
assert_hash_ne "a content change to the untracked test file moves it again" "$w1" "$w2"
rm -f "$WFIX/tests/new.test.ts"
assert_hash_eq "removing the untracked file returns it to the clean tree's hash" "$w0" "$(whash "$WFIX")"

printf 'export const n = 1\n' > "$WFIX/src/new.ts"
assert_hash_ne "an untracked source file moves it" "$w0" "$(whash "$WFIX")"
rm -f "$WFIX/src/new.ts"
printf '{}\n' > "$WFIX/tsconfig.json"
assert_hash_ne "an untracked config file moves it" "$w0" "$(whash "$WFIX")"
rm -f "$WFIX/tsconfig.json"
printf 'export const x = 2\n' > "$WFIX/src/main.ts"
assert_hash_ne "an unstaged edit to a tracked source file moves it" "$w0" "$(whash "$WFIX")"
git -C "$WFIX" checkout -q -- src/main.ts

# Harness markdown MOVES it (C-2 as amended by A-2): the harness's own suites
# read agent specs, commands, skills and CLAUDE.md, so a record made before an
# instructions edit must not stay fresh after it.
mkdir -p "$WFIX/.claude/commands" "$WFIX/.claude/agents" "$WFIX/.claude/skills/x"
printf '# a prompt\n' > "$WFIX/.claude/commands/new.md"
wm1="$(whash "$WFIX")"
assert_hash_ne "an untracked harness markdown file (.claude/commands/new.md) moves it" "$w0" "$wm1"
printf '# a prompt, reworded\n' > "$WFIX/.claude/commands/new.md"
assert_hash_ne "and a content change to it moves it again" "$wm1" "$(whash "$WFIX")"
rm -f "$WFIX/.claude/commands/new.md"
printf '# a skill\n' > "$WFIX/.claude/skills/x/SKILL.md"
assert_hash_ne "an untracked skill (.claude/skills/x/SKILL.md) moves it" "$w0" "$(whash "$WFIX")"
rm -rf "$WFIX/.claude/skills"
# Tracked harness markdown: commit an agent spec and a CLAUDE.md, then edit each.
printf '# role\n\n## Method\n\n1. Read the story.\n' > "$WFIX/.claude/agents/role.md"
printf '# house rules\n' > "$WFIX/CLAUDE.md"
git -C "$WFIX" add -A >/dev/null 2>&1
git -C "$WFIX" -c user.email=t@t -c user.name=t commit -qm "harness markdown" >/dev/null 2>&1
wt="$(whash "$WFIX")"
assert_hash_ne "committed harness markdown is part of the work hash (it moved from the clean tree's)" "$w0" "$wt"
# Green on arrival, and C-10's half of A-2: gate_tree_hash and gated_stdin are
# unchanged, so the same commit does not move the GATE hash.
assert_hash_eq "control: gate_tree_hash does not see committed harness markdown (C-10)" "$g0" "$(ghash "$WFIX")"
printf '# role\n\n## Method\n\n1. Read the story twice.\n' > "$WFIX/.claude/agents/role.md"
assert_hash_ne "an unstaged edit to a tracked .claude/agents/*.md moves it" "$wt" "$(whash "$WFIX")"
git -C "$WFIX" checkout -q -- .claude/agents/role.md
assert_hash_eq "and undoing it returns it" "$wt" "$(whash "$WFIX")"
printf '# house rules, amended\n' > "$WFIX/CLAUDE.md"
assert_hash_ne "an unstaged edit to a tracked CLAUDE.md moves it" "$wt" "$(whash "$WFIX")"
git -C "$WFIX" checkout -q -- CLAUDE.md

# What does NOT move it (C-2 as amended by A-2: docs, vendor, ignored and
# .claude/state/ only). Judged against $wt, the tree with harness markdown.
printf '# edited notes\n' > "$WFIX/docs/notes.md"
assert_hash_eq "a tracked docs edit does not move it" "$wt" "$(whash "$WFIX")"
printf '# new page\n' > "$WFIX/docs/new.md"
assert_hash_eq "an untracked docs file does not move it" "$wt" "$(whash "$WFIX")"
mkdir -p "$WFIX/dist"
printf 'built\n' > "$WFIX/dist/out.js"
assert_hash_eq "a vendor (ignored build output) file does not move it" "$wt" "$(whash "$WFIX")"
mkdir -p "$WFIX/scratch"
printf 'export const s = 1\n' > "$WFIX/scratch/out.ts"
assert_hash_eq "an ignored file (scratch/, source by name) does not move it" "$wt" "$(whash "$WFIX")"
# The ignored case's control: the same content, not ignored, does move it.
printf 'export const s = 1\n' > "$WFIX/src/scratch-out.ts"
assert_hash_ne "control: the same content at a non-ignored source path moves it" "$wt" "$(whash "$WFIX")"
rm -f "$WFIX/src/scratch-out.ts"
printf 'state\n' > "$WFIX/.claude/state/anything.txt"
printf '# state notes\n' > "$WFIX/.claude/state/notes.md"
assert_hash_eq "a file under .claude/state/ (markdown included) does not move it" "$wt" "$(whash "$WFIX")"

# Failure: not a git repository. gate_tree_hash prints `unavailable` there, and
# work_tree_hash must print it ONCE - not twice, not beside a hash.
NOGIT="$WORK/nogit"
mkdir -p "$NOGIT/.claude/hooks" "$NOGIT/.claude/harness"
cp "$WFIX/.claude/hooks/lib.sh" "$NOGIT/.claude/hooks/lib.sh"
cp "$WFIX/.claude/harness/paths.conf" "$NOGIT/.claude/harness/paths.conf"
u="$( cd "$NOGIT" && export GIT_CEILING_DIRECTORIES="$WORK" && . "$NOGIT/.claude/hooks/lib.sh" && set_harness_root "$NOGIT" && work_tree_hash 2>/dev/null )"; urc=$?
assert_eq "outside a repository work_tree_hash prints exactly \`unavailable\`" "unavailable" "$u"
assert_eq "and returns 1" 1 "$urc"

# ==============================================================================
describe "AC-1  attest.sh -- <command>: exit passed through, the record, then the tail"
# ==============================================================================

T0="$(whash "$FIX")"
s0="$(now_stamp)"
att -- bash "$C/two.sh" alpha beta
s1="$(now_stamp)"
CMD1="bash $C/two.sh alpha beta"
assert_eq "the command's exit status, 3, is attest.sh's" 3 "$RC"
B1="$(last_block "$ALOG")"
assert_eq "attest.log's last block has exactly C-3's fields, in C-3's order" \
  "run command tree after status exit duration last log" "$(keys "$B1")"
R1="$(field "$B1" run)"
if [[ $R1 =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] && [[ ! $R1 < $s0 ]] && [[ ! $R1 > $s1 ]]; then
  _ok "run: is a UTC stamp in gates.sh's format, taken during the call"
else _bad "run: is a UTC stamp in gates.sh's format, taken during the call" "run: [$R1], call between $s0 and $s1"; fi
assert_eq "command: is the words joined by one space" "$CMD1" "$(field "$B1" command)"
assert_hash_eq "tree: is the work hash before the command ran" "$T0" "$(field "$B1" tree)"
assert_hash_eq "after: is the work hash when it exited (unchanged tree)" "$T0" "$(field "$B1" after)"
assert_eq "status: ok" "ok" "$(field "$B1" status)"
assert_eq "exit: 3" "3" "$(field "$B1" exit)"
D1="$(field "$B1" duration)"
if [[ $D1 =~ ^[0-9]+s$ ]]; then _ok "duration: is whole seconds with an s"; else _bad "duration: is whole seconds with an s" "duration: [$D1]"; fi
assert_eq "last: is the last NON-BLANK line of the combined output (stderr's)" "second line" "$(field "$B1" last)"
L1="$(field "$B1" log)"
if [[ $L1 =~ $LOGRE ]] && [ "${BASH_REMATCH[1]}" = "${R1//[-:]/}" ]; then
  _ok "log: is .claude/state/attest-logs/<run, colon-free>.<pid>.log (C-3 as amended)"
else _bad "log: is .claude/state/attest-logs/<run, colon-free>.<pid>.log (C-3 as amended)" "log: [$L1], run: [$R1]"; fi
if [ -n "$L1" ] && [ -f "$FIX/$L1" ]; then
  assert_eq "the log file holds the command's full combined output" \
    "first line
second line" "$(cat "$FIX/$L1")"
else _bad "the log file holds the command's full combined output" "no file at [$L1]"; fi
assert_block_eq "stdout opens with the record it wrote, field for field" "$B1" "$(printed_block "$OUT")"
assert_eq "then a header naming the log" "--- last 20 lines of $L1 ---" "$(header_line "$OUT")"
assert_eq "then the log's last lines" "first line
second line" "$(after_header "$OUT")"
assert_eq "the output is printed once, from the log, not streamed as well" 1 "$(count_line 'first line' "$OUT")"
if [ -n "$L1" ] && [ -f "$FIX/$L1" ] && [ "$(count_line 'second line' "$(cat "$FIX/$L1")")" = 1 ] \
   && [ "$(count_line 'second line' "$ERR")" = 0 ]; then
  _ok "the command's stderr goes to the log, not to attest.sh's stderr"
else _bad "the command's stderr goes to the log, not to attest.sh's stderr" "log: [$L1]
attest.sh's stderr: $ERR"; fi

# The tail is a tail: 30 lines in, the last 20 out by default.
att -- bash "$C/thirty.sh"
L30="$(field "$(last_block "$ALOG")" log)"
assert_eq "exit 0 is passed through as 0" 0 "$RC"
assert_eq "a 30-line output prints a 20-line header by default" "--- last 20 lines of $L30 ---" "$(header_line "$OUT")"
assert_eq "and exactly lines 11..30" "$(i=11; while [ $i -le 30 ]; do printf 'line %d\n' $i; i=$((i + 1)); done)" "$(after_header "$OUT")"
if [ -n "$L30" ] && [ -f "$FIX/$L30" ]; then
  assert_eq "while the log keeps all 30" 30 "$(awk 'END { print NR }' "$FIX/$L30")"
else _bad "while the log keeps all 30" "no file at [$L30]"; fi
ATT_ENV=ATTEST_TAIL=5 att -- bash "$C/thirty.sh"
L5="$(field "$(last_block "$ALOG")" log)"
assert_eq "ATTEST_TAIL=5 prints a 5-line header" "--- last 5 lines of $L5 ---" "$(header_line "$OUT")"
assert_eq "and lines 26..30" "line 26
line 27
line 28
line 29
line 30" "$(after_header "$OUT")"

# The words are executed directly, never through a shell.
att -- bash "$C/args.sh" 'a b' '*'
B="$(last_block "$ALOG")"; L="$(field "$B" log)"
if [ -n "$L" ] && [ -f "$FIX/$L" ]; then
  assert_eq "a word with a space stays one word, and * is not globbed" "[a b]
[*]" "$(cat "$FIX/$L")"
else _bad "a word with a space stays one word, and * is not globbed" "no file at [$L]"; fi
assert_eq "and command: joins them with one space, as given" "bash $C/args.sh a b *" "$(field "$B" command)"

# Control: a leading NAME=value is exported to the command and kept in command:.
att -- ATTEST_PROBE=value bash "$C/env.sh"
B="$(last_block "$ALOG")"; L="$(field "$B" log)"
assert_eq "control: NAME=value is stripped from what is executed (exit 0, not 127)" 0 "$RC"
if [ -n "$L" ] && [ -f "$FIX/$L" ]; then
  assert_eq "control: and exported to the command, which printed it" "NAME=value" "$(cat "$FIX/$L")"
else _bad "control: and exported to the command, which printed it" "no file at [$L]"; fi
assert_eq "control: command: keeps the assignment" "ATTEST_PROBE=value bash $C/env.sh" "$(field "$B" command)"

# ==============================================================================
describe "C-1  usage errors exit 2 and record nothing"
# ==============================================================================

before="$(sum "$ALOG")"
att;                       assert_eq "no arguments: exit 2" 2 "$RC"
att --;                    assert_eq "nothing after --: exit 2" 2 "$RC"
att frob -- true;          assert_eq "an unknown first word: exit 2" 2 "$RC"
att check;                 assert_eq "check with no --: exit 2" 2 "$RC"
att check --;              assert_eq "check with nothing after --: exit 2" 2 "$RC"
att true;                  assert_eq "a command with no -- before it: exit 2" 2 "$RC"
after="$(sum "$ALOG")"
if [ "$before" != absent ] && [ "$before" = "$after" ]; then _ok "and none of them appended to attest.log"
else _bad "and none of them appended to attest.log" "before: $before
after:  $after"; fi

# ==============================================================================
describe "AC-2  check: fresh on the unchanged tree; none, stale, or still fresh on a docs edit"
# ==============================================================================

att check -- bash "$C/two.sh" alpha beta
assert_eq "same words, unchanged tree: the last line is fresh" "fresh" "$(last_line "$OUT")"
assert_eq "and exit 0" 0 "$RC"
assert_block_eq "and before it, the record" "$B1" "$(all_but_last "$OUT")"

att check -- bash "$C/other.sh"
assert_eq "a command never run: none" "none: no record for this command" "$(last_line "$OUT")"
assert_eq "none exits 1" 1 "$RC"
att check -- bash "$C/two.sh" beta alpha
assert_eq "the same words reordered: none" "none: no record for this command" "$(last_line "$OUT")"
assert_eq "reordered exits 1" 1 "$RC"
att check -- bash "$C/two.sh" alpha
assert_eq "a prefix of the words: none (equality, not containment)" "none: no record for this command" "$(last_line "$OUT")"
att check -- bash "$C/two.sh" alpha beta gamma
assert_eq "a superset of the words: none" "none: no record for this command" "$(last_line "$OUT")"
att check -- ATTEST_PROBE=value bash "$C/env.sh"
assert_eq "the assignment is part of the command: with it, fresh" "fresh" "$(last_line "$OUT")"
att check -- bash "$C/env.sh"
assert_eq "without it, none" "none: no record for this command" "$(last_line "$OUT")"

# Docs only: still fresh.
printf '# notes, reworded\n' > "$FIX/docs/notes.md"
att check -- bash "$C/two.sh" alpha beta
assert_eq "after a docs-only edit: still fresh" "fresh" "$(last_line "$OUT")"
assert_eq "after a docs-only edit: exit 0" 0 "$RC"
git -C "$FIX" checkout -q -- docs/notes.md

# Harness markdown is not docs (C-2 as amended by A-2): an edit to a tracked
# agent spec, or to CLAUDE.md, makes the record stale.
printf '# role, reworded\n' > "$FIX/.claude/agents/role.md"
Tm="$(whash "$FIX")"
att check -- bash "$C/two.sh" alpha beta
assert_eq "after a tracked .claude/agents/*.md edit: stale, naming the recorded and the current hash" \
  "stale: recorded on $T0 at $R1, the tree is now $Tm" "$(last_line "$OUT")"
assert_eq "and exits 1" 1 "$RC"
git -C "$FIX" checkout -q -- .claude/agents/role.md
printf '# house rules, amended\n' > "$FIX/CLAUDE.md"
Tc="$(whash "$FIX")"
att check -- bash "$C/two.sh" alpha beta
assert_eq "after a tracked CLAUDE.md edit: stale, naming the recorded and the current hash" \
  "stale: recorded on $T0 at $R1, the tree is now $Tc" "$(last_line "$OUT")"
assert_eq "and exits 1" 1 "$RC"
git -C "$FIX" checkout -q -- CLAUDE.md
att check -- bash "$C/two.sh" alpha beta
assert_eq "both edits undone: fresh again" "fresh" "$(last_line "$OUT")"

# A tracked source edit: stale, naming both hashes and the run.
printf 'export const x = 99\n' > "$FIX/src/main.ts"
Tn="$(whash "$FIX")"
att check -- bash "$C/two.sh" alpha beta
assert_hash_ne "precondition: the source edit moved the work hash" "$T0" "$Tn"
assert_eq "after a tracked source edit: stale, naming the recorded and the current hash" \
  "stale: recorded on $T0 at $R1, the tree is now $Tn" "$(last_line "$OUT")"
assert_eq "stale exits 1" 1 "$RC"
git -C "$FIX" checkout -q -- src/main.ts
att check -- bash "$C/two.sh" alpha beta
assert_eq "the edit undone: fresh again (content, not time)" "fresh" "$(last_line "$OUT")"

# An untracked, non-ignored test file: stale; and again when its content changes.
printf 'test("n", () => {})\n' > "$FIX/tests/new.test.ts"
Ta="$(whash "$FIX")"
att check -- bash "$C/two.sh" alpha beta
assert_eq "after an untracked test file appears: stale" \
  "stale: recorded on $T0 at $R1, the tree is now $Ta" "$(last_line "$OUT")"
assert_eq "and exits 1" 1 "$RC"
printf 'test("n", () => { expect(2) })\n' > "$FIX/tests/new.test.ts"
Tb="$(whash "$FIX")"
att check -- bash "$C/two.sh" alpha beta
assert_hash_ne "precondition: its content change moved the work hash again" "$Ta" "$Tb"
assert_eq "after its content changes: stale, naming the new hash" \
  "stale: recorded on $T0 at $R1, the tree is now $Tb" "$(last_line "$OUT")"
assert_eq "and exits 1" 1 "$RC"
rm -f "$FIX/tests/new.test.ts"

# ==============================================================================
describe "AC-3  a command that edits a tracked source file: void, exit passed through"
# ==============================================================================

Tv0="$(whash "$FIX")"
att -- bash "$C/edit.sh"
Tv1="$(whash "$FIX")"
BV="$(last_block "$ALOG")"
assert_eq "the command's exit status, 5, is passed through" 5 "$RC"
assert_eq "status: void: tree changed during the run" "void: tree changed during the run" "$(field "$BV" status)"
assert_hash_eq "tree: is the hash before" "$Tv0" "$(field "$BV" tree)"
assert_hash_eq "after: is the hash it exited on" "$Tv1" "$(field "$BV" after)"
assert_hash_ne "precondition: the edit moved the work hash" "$Tv0" "$Tv1"
assert_eq "exit: 5" "5" "$(field "$BV" exit)"
assert_block_eq "and the void record is printed" "$BV" "$(printed_block "$OUT")"
att check -- bash "$C/edit.sh"
assert_eq "check answers void, with the status text" "void: tree changed during the run" "$(last_line "$OUT")"
assert_eq "void exits 1" 1 "$RC"
# Void outranks the hash: put the file back, so the CURRENT tree equals the
# recorded tree: - a check that compared hashes first would now say fresh.
git -C "$FIX" checkout -q -- src/x.sh
att check -- bash "$C/edit.sh"
assert_eq "void even once the tree is back to the recorded tree:" "void: tree changed during the run" "$(last_line "$OUT")"

# Control: writing only under .claude/state/ is not a tree change.
Ts0="$(whash "$FIX")"
att -- bash "$C/state.sh"
BS="$(last_block "$ALOG")"
assert_eq "control: a command writing only under .claude/state/ records status: ok" "ok" "$(field "$BS" status)"
assert_eq "control: and exit 0" 0 "$RC"
assert_hash_eq "control: tree: and after: are the same hash" "$Ts0" "$(field "$BS" after)"
att check -- bash "$C/state.sh"
assert_eq "control: and check calls it fresh" "fresh" "$(last_line "$OUT")"

# ==============================================================================
describe "C-4  check reads the NEWEST block for the words"
# ==============================================================================

printf 'export const x = 7\n' > "$FIX/src/main.ts"
T2="$(whash "$FIX")"
att -- bash "$C/two.sh" alpha beta
R2="$(field "$(last_block "$ALOG")" run)"
att check -- bash "$C/two.sh" alpha beta
assert_eq "re-run on an edited tree: fresh" "fresh" "$(last_line "$OUT")"
git -C "$FIX" checkout -q -- src/main.ts
att check -- bash "$C/two.sh" alpha beta
assert_eq "tree put back: stale against the NEWEST record, though an older one matches" \
  "stale: recorded on $T2 at $R2, the tree is now $T0" "$(last_line "$OUT")"

# ==============================================================================
describe "AC-4  a stranded mutation: refused before running, mutate.sh's report, exit 2"
# ==============================================================================

MUT="$FIX/.claude/state/mutations"
mkdir -p "$MUT"
DEAD="$(bash -c 'echo $$')"
ACT="$MUT/src_main.ts.20261004T010203Z.$DEAD.active"
printf 'pid\t%s\nfile\t%s\npath\t%s\nbackup\t%s\nexpr\t%s\ncommand\t%s\nstarted\t%s\n' \
  "$DEAD" src/main.ts "$FIX/src/main.ts" "${ACT%.active}.bak" 's/1/-1/' 'bash scripts/gates.sh' 20261004T010203Z > "$ACT"
( cd "$FIX" && bash scripts/mutate.sh --check ) >/dev/null 2>&1; crc=$?
assert_eq "precondition: mutate.sh --check calls the planted sentinel stranded (exit 1)" 1 "$crc"
rm -f "$WORK/ac4-ran"
before="$(sum "$ALOG")"
att -- bash "$C/mark.sh"
assert_eq "attest.sh exits 2" 2 "$RC"
if [ -e "$WORK/ac4-ran" ]; then _bad "the command never ran (its side effect is absent)" "$WORK/ac4-ran exists"
else _ok "the command never ran (its side effect is absent)"; fi
assert_eq "it prints mutate.sh --check's report" 1 \
  "$(count_line 'mutate: a mutation is unaccounted for. The tree may not be the code you think.' "$OUT
$ERR")"
assert_eq "naming the stranded file" 1 "$(count_line '  src/main.ts' "$OUT
$ERR")"
after="$(sum "$ALOG")"
if [ "$before" != absent ] && [ "$before" = "$after" ]; then _ok "and records nothing"
else _bad "and records nothing" "attest.log before: $before, after: $after"; fi
rm -f "$ACT"
att -- bash "$C/mark.sh"
assert_eq "control: with the sentinel gone the same command runs (exit 0)" 0 "$RC"
if [ -e "$WORK/ac4-ran" ]; then _ok "control: and its side effect appears"
else _bad "control: and its side effect appears" "$WORK/ac4-ran is absent"; fi

# ==============================================================================
describe "C-1  a leading assignment reaches the command only, never attest.sh's own shell"
# ==============================================================================
# Diff review round 1, finding 3. attest.sh's own ROOT, ALOG and HARNESS_ROOT
# decide where the record and the log land, which tree is hashed and whether
# AC-4's refusal runs; an assignment word must change none of them.

SCR="$WORK/scratch-root"; mkdir -p "$SCR"
att -- "ROOT=$SCR" bash "$C/vars.sh"
B="$(last_block "$ALOG")"; L="$(field "$B" log)"
assert_eq "ROOT=<elsewhere>: exit 0" 0 "$RC"
assert_eq "ROOT=<elsewhere>: the record lands in this tree's attest.log" "ROOT=$SCR bash $C/vars.sh" "$(field "$B" command)"
if [ -n "$L" ] && [ -f "$FIX/$L" ]; then
  _ok "ROOT=<elsewhere>: the log it names is under this tree's .claude/state/"
  assert_eq "ROOT=<elsewhere>: and the command saw ROOT, which it printed" 1 "$(count_line "ROOT=$SCR" "$(cat "$FIX/$L")")"
else
  _bad "ROOT=<elsewhere>: the log it names is under this tree's .claude/state/" "no file at [$FIX/$L]"
  _bad "ROOT=<elsewhere>: and the command saw ROOT, which it printed" "no log to read"
fi
if [ -e "$SCR/.claude/state" ]; then _bad "ROOT=<elsewhere>: nothing is written under <elsewhere>" "$(find "$SCR" -type f)"
else _ok "ROOT=<elsewhere>: nothing is written under <elsewhere>"; fi

AE="$WORK/elsewhere-attest.log"
att -- "ALOG=$AE" bash "$C/vars.sh"
B="$(last_block "$ALOG")"; L="$(field "$B" log)"
assert_eq "ALOG=<elsewhere>: the record lands in this tree's attest.log" "ALOG=$AE bash $C/vars.sh" "$(field "$B" command)"
if [ -e "$AE" ]; then _bad "ALOG=<elsewhere>: nothing is appended to <elsewhere>" "$(cat "$AE")"
else _ok "ALOG=<elsewhere>: nothing is appended to <elsewhere>"; fi
if [ -n "$L" ] && [ -f "$FIX/$L" ]; then
  assert_eq "ALOG=<elsewhere>: and the command saw ALOG, which it printed" 1 "$(count_line "ALOG=$AE" "$(cat "$FIX/$L")")"
else _bad "ALOG=<elsewhere>: and the command saw ALOG, which it printed" "no file at [$FIX/$L]"; fi

SCR2="$WORK/scratch-harness"; mkdir -p "$SCR2"
Th="$(whash "$FIX")"
att -- "HARNESS_ROOT=$SCR2" bash "$C/vars.sh"
B="$(last_block "$ALOG")"
assert_eq "HARNESS_ROOT=<elsewhere>: status: ok (both hashes are of this tree)" "ok" "$(field "$B" status)"
assert_hash_eq "HARNESS_ROOT=<elsewhere>: after: is this tree's work hash" "$Th" "$(field "$B" after)"

# With a stranded mutation, an assignment cannot step around AC-4's refusal.
printf 'pid\t%s\nfile\t%s\npath\t%s\nbackup\t%s\nexpr\t%s\ncommand\t%s\nstarted\t%s\n' \
  "$DEAD" src/main.ts "$FIX/src/main.ts" "${ACT%.active}.bak" 's/1/-1/' 'bash scripts/gates.sh' 20261004T010203Z > "$ACT"
SCR3="$WORK/scratch-mut"; mkdir -p "$SCR3"
rm -f "$WORK/vars-ran"; before="$(sum "$ALOG")"
att -- "ROOT=$SCR3" bash "$C/vars.sh"
assert_eq "a stranded mutation and ROOT=<elsewhere>: still refused, exit 2" 2 "$RC"
if [ -e "$WORK/vars-ran" ]; then _bad "a stranded mutation and ROOT=<elsewhere>: the command never ran" "$WORK/vars-ran exists"
else _ok "a stranded mutation and ROOT=<elsewhere>: the command never ran"; fi
assert_eq "a stranded mutation and ROOT=<elsewhere>: nothing recorded" "$before" "$(sum "$ALOG")"
rm -f "$WORK/vars-ran"
att -- "ALOG=$WORK/scratch-mut.log" bash "$C/vars.sh"
assert_eq "a stranded mutation and ALOG=<elsewhere>: still refused, exit 2" 2 "$RC"
if [ -e "$WORK/vars-ran" ]; then _bad "a stranded mutation and ALOG=<elsewhere>: the command never ran" "$WORK/vars-ran exists"
else _ok "a stranded mutation and ALOG=<elsewhere>: the command never ran"; fi
rm -f "$ACT"

# ==============================================================================
describe "C-1  the command gets the caller's CLAUDE_PROJECT_DIR, not attest.sh's root"
# ==============================================================================
# Return 4 (GATES -> RED). attest.sh exports CLAUDE_PROJECT_DIR=$ROOT so its own
# lib.sh calls judge its own tree; that export reached the command too, so
# `attest.sh -- bash scripts/selftest.sh` ran the classify and selftest-needed
# suites in a different environment from the caller's, and failed 6 assertions
# that pass without attest.sh. The command's environment is the caller's plus
# the leading assignments, and nothing else. The suite exports the variable as
# REPO_ROOT, so each case below sets the caller's value explicitly.

# cpd_case <label> <expected cpd line> <attest.sh invocation prefix...>
#   Runs `<prefix> bash scripts/attest.sh -- [assign] bash $C/cpd.sh` in FIX and
#   asserts the record lands in FIX's attest.log with status ok, and that the
#   command's log holds exactly the expected cpd=[...] line.
cpd_case() {
  local label="$1" want="$2" cmdstr="$3"; shift 3
  ( cd "$FIX" && "$@" ) > "$WORK/out" 2> "$WORK/err"
  RC=$?
  B="$(last_block "$ALOG")"; L="$(field "$B" log)"
  assert_eq "$label: exit 0" 0 "$RC"
  assert_eq "$label: the record lands in this tree's attest.log" "$cmdstr" "$(field "$B" command)"
  assert_eq "$label: status: ok" "ok" "$(field "$B" status)"
  if [ -n "$L" ] && [ -f "$FIX/$L" ]; then
    if [ "$(count_line "$want" "$(cat "$FIX/$L")")" = 1 ]; then _ok "$label: the command printed exactly the line $want"
    else _bad "$label: the command printed exactly the line $want" "it printed: $(grep '^cpd=' "$FIX/$L")"; fi
  else _bad "$label: the command printed exactly the line $want" "no file at [$FIX/$L]"; fi
}

cpd_case "CLAUDE_PROJECT_DIR unset in the caller" "cpd=[UNSET]" "bash $C/cpd.sh" \
  env -u CLAUDE_PROJECT_DIR bash scripts/attest.sh -- bash "$C/cpd.sh"

CPDX="$WORK/caller-project-dir"; mkdir -p "$CPDX"
cpd_case "CLAUDE_PROJECT_DIR=<X> in the caller" "cpd=[$CPDX]" "bash $C/cpd.sh" \
  env "CLAUDE_PROJECT_DIR=$CPDX" bash scripts/attest.sh -- bash "$C/cpd.sh"
if [ -e "$CPDX/.claude" ]; then _bad "CLAUDE_PROJECT_DIR=<X> in the caller: nothing is written under <X>" "$(find "$CPDX" -type f)"
else _ok "CLAUDE_PROJECT_DIR=<X> in the caller: nothing is written under <X>"; fi

CPDY="$WORK/assigned-project-dir"; mkdir -p "$CPDY"
cpd_case "a leading CLAUDE_PROJECT_DIR=<Y> assignment over the caller's <X>" "cpd=[$CPDY]" "CLAUDE_PROJECT_DIR=$CPDY bash $C/cpd.sh" \
  env "CLAUDE_PROJECT_DIR=$CPDX" bash scripts/attest.sh -- "CLAUDE_PROJECT_DIR=$CPDY" bash "$C/cpd.sh"
if [ -e "$CPDY/.claude" ]; then _bad "a leading CLAUDE_PROJECT_DIR=<Y> assignment: nothing is written under <Y>" "$(find "$CPDY" -type f)"
else _ok "a leading CLAUDE_PROJECT_DIR=<Y> assignment: nothing is written under <Y>"; fi

# ==============================================================================
describe "C-1  a word holding a newline or a CR is a usage error, and forges nothing"
# ==============================================================================
# Diff review round 1, finding 4. A newline inside a word wrote extra lines into
# the record, so a `command:` line naming a command that never ran made `check`
# answer fresh for it. Refused before anything runs or is written.

FORGED='bash scripts/gates.sh --fast'
before="$(sum "$ALOG")"
rm -f "$WORK/side-ran"
att -- bash "$C/side.sh" "x
command: $FORGED"
assert_eq "a word containing a newline: exit 2" 2 "$RC"
if [ -e "$WORK/side-ran" ]; then _bad "a word containing a newline: the command never ran" "$WORK/side-ran exists"
else _ok "a word containing a newline: the command never ran"; fi
rm -f "$WORK/side-ran"
CR="$(printf '\r')"
att -- bash "$C/side.sh" "x${CR}command: $FORGED"
assert_eq "a word containing a CR: exit 2" 2 "$RC"
if [ -e "$WORK/side-ran" ]; then _bad "a word containing a CR: the command never ran" "$WORK/side-ran exists"
else _ok "a word containing a CR: the command never ran"; fi
rm -f "$WORK/side-ran"
att -- "P=a
command: $FORGED" bash "$C/side.sh"
assert_eq "a leading assignment containing a newline: exit 2" 2 "$RC"
if [ -e "$WORK/side-ran" ]; then _bad "a leading assignment containing a newline: the command never ran" "$WORK/side-ran exists"
else _ok "a leading assignment containing a newline: the command never ran"; fi
att check -- bash "$C/side.sh" "x
command: $FORGED"
assert_eq "check with a word containing a newline: exit 2" 2 "$RC"
assert_eq "none of them appended to attest.log" "$before" "$(sum "$ALOG")"
att check -- bash scripts/gates.sh --fast
assert_eq "the forged command has no record: check answers none" "none: no record for this command" "$(last_line "$OUT")"
assert_eq "and exits 1" 1 "$RC"

# ==============================================================================
# AC-5: the structural guard (C-5)
# ==============================================================================
#
# Region helpers COPIED from procedure.test.sh (load, blank, trim,
# allowed_tools, has_entry), not sourced: sourcing a suite runs it. has_entry's
# semantics are procedure's, read out: a comma-separated entry, trimmed, EQUAL
# to the needle.

load() {
  local i
  LN=(); mapfile -t LN < "$1"
  for i in "${!LN[@]}"; do LN[$i]="${LN[$i]%$'\r'}"; done
}
blank() { [ -z "${1//[[:space:]]/}" ]; }
trim() {
  T="$1"
  T="${T#"${T%%[![:space:]]*}"}"
  T="${T%"${T##*[![:space:]]}"}"
}
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

# The sites and needles (C-5, settled: read out byte for byte).
FD=".claude/agents/feature-developer.md"
TD=".claude/agents/test-developer.md"
ADVANCE=".claude/commands/advance-story.md"
COMPLETE=".claude/commands/complete-story.md"
LEADPO=".claude/agents/lead-po.md"
FULL_RUN='`bash scripts/gates.sh`'
ATTEST_FAST='bash scripts/attest.sh -- bash scripts/gates.sh --fast'
ATTEST_RUN='bash scripts/attest.sh --'
ATTEST_CHECK='bash scripts/attest.sh check'
RERUN='run the tests yourself'
TOOL_CHECK='Bash(bash scripts/attest.sh check:*)'   # required (A-1)
TOOL_ANY='Bash(bash scripts/attest.sh:*)'           # refused (A-1): runs any words

# method_list   ML := the numbered list under `## Method` in the loaded file,
# one array element per line. It starts at the first `^[0-9]+\. ` line after
# the heading, and takes step lines, indented continuation lines and blank
# lines, ending at the first other line - an unindented paragraph, or the next
# `## ` heading. HAS_METHOD := 1 when the heading exists.
method_list() {
  local l on=0 started=0 re='^[0-9]+\. '
  ML=(); HAS_METHOD=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "$l" = "## Method" ] && { on=1; HAS_METHOD=1; }
      continue
    fi
    [ "${l:0:3}" = "## " ] && break
    if [[ $l =~ $re ]]; then started=1; ML+=("$l"); continue; fi
    [ "$started" = 0 ] && continue
    if blank "$l" || [[ $l == [[:space:]]* ]]; then ML+=("$l"); continue; fi
    break
  done
  return 0
}

# list_has <needle>   Succeeds when some line of ML contains <needle>.
list_has() {
  local l
  for l in "${ML[@]}"; do case "$l" in *"$1"*) return 0 ;; esac; done
  return 1
}

# occurrences <needle> <text>   How many times <needle> occurs in <text>.
occurrences() {
  local t="$2" n=0
  while [[ $t == *"$1"* ]]; do t="${t#*"$1"}"; n=$((n + 1)); done
  printf '%s' "$n"
}

# phase_region <start>   RG := advance-story's paragraph from the line beginning
# <start> (`**X → Y.**`) to just before the next line beginning `**X → Y.**`
# for any X and Y, its lines joined by single spaces (so a phrase wrapped over
# two lines is still one phrase). HAS_RG := 1 when the start line exists. A
# bold line that is NOT a phase heading - `**Pin the `## Contract`.**` - does
# not end the region.
phase_region() {
  local l on=0 re='^\*\*[^*]+ → [^*]+\.\*\*'
  RG=""; HAS_RG=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#1}}" = "$1" ] && { on=1; HAS_RG=1; RG="$l"; }
      continue
    fi
    [[ $l =~ $re ]] && break
    RG="$RG $l"
  done
  return 0
}

# section_text <heading>   SX := the lines from the line EQUAL to <heading> to
# just before the next line beginning `## `, space-joined. HAS_SX := 1 when the
# heading exists.
section_text() {
  local l on=0
  SX=""; HAS_SX=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "$l" = "$1" ] && { on=1; HAS_SX=1; }
      continue
    fi
    [ "${l:0:3}" = "## " ] && break
    SX="$SX $l"
  done
  return 0
}

# body_lines   BODY := the loaded file's lines after its frontmatter: after the
# line `---` that closes a first line `---`. The whole file when it has no
# frontmatter (or an unclosed one).
body_lines() {
  local i n="${#LN[@]}" end=-1
  BODY=("${LN[@]}")
  [ "$n" -gt 0 ] && [ "${LN[0]}" = "---" ] || return 0
  for ((i = 1; i < n; i++)); do
    [ "${LN[$i]}" = "---" ] && { end=$i; break; }
  done
  [ "$end" -gt 0 ] && BODY=("${LN[@]:$((end + 1))}")
  return 0
}

# join_by <sep> <item>...   The items joined by <sep>, in a subshell so IFS
# stays the caller's.
join_by() { ( IFS="$1"; shift; printf '%s' "$*" ); }

# check_attest_tool <rel>   The allowed-tools entries, for the loaded file
# (C-5 as amended by A-1): an entry EQUAL to the check pattern, and no entry
# EQUAL to the bare prefix, which would auto-approve `attest.sh -- <anything>`.
# Absent check first, then the prefix; a file wrong both ways prints both.
check_attest_tool() {
  allowed_tools
  if [ "$HAS_AT" = 0 ]; then
    printf '%s: has no `allowed-tools:` line in its frontmatter\n' "$1"
  else
    has_entry "$TOOL_CHECK" || printf '%s: does not permit attest.sh check\n' "$1"
    has_entry "$TOOL_ANY" && printf '%s: permits attest.sh to run any command\n' "$1"
  fi
  return 0
}

# attest_problems <root>   One line `<path>: <reason>` per violation, in the
# order below; silent on a compliant tree. Always returns 0: the output is the
# verdict. Reasons are C-5's, byte for byte; the advance-story region name is
# the heading's text without its asterisks and period (C-5 as amended).
attest_problems() {
  local root="$1" f all fast name
  # feature-developer.md ## Method
  if [ ! -f "$root/$FD" ]; then printf '%s: file is missing\n' "$FD"
  else
    load "$root/$FD"; method_list
    if [ "$HAS_METHOD" = 0 ]; then printf '%s: has no `## Method` section\n' "$FD"
    else
      list_has "$FULL_RUN" && printf '%s: still runs the full gate run in GREEN\n' "$FD"
      list_has "$ATTEST_FAST" || printf '%s: does not run --fast through attest.sh\n' "$FD"
    fi
  fi
  # test-developer.md ## Method. Its tests step needs an attest.sh run OTHER
  # than the --fast one: `bash scripts/attest.sh --` is a prefix of the --fast
  # needle, so "a line contains it" is satisfied by the --fast line alone.
  if [ ! -f "$root/$TD" ]; then printf '%s: file is missing\n' "$TD"
  else
    load "$root/$TD"; method_list
    if [ "$HAS_METHOD" = 0 ]; then printf '%s: has no `## Method` section\n' "$TD"
    else
      all="$(join_by $'\n' "${ML[@]}")"
      [ "$(occurrences "$ATTEST_RUN" "$all")" -gt "$(occurrences "$ATTEST_FAST" "$all")" ] \
        || printf '%s: does not run its tests through attest.sh\n' "$TD"
      list_has "$ATTEST_FAST" || printf '%s: does not run --fast through attest.sh\n' "$TD"
    fi
  fi
  # advance-story.md: the tool, then each region.
  if [ ! -f "$root/$ADVANCE" ]; then printf '%s: file is missing\n' "$ADVANCE"
  else
    load "$root/$ADVANCE"; check_attest_tool "$ADVANCE"
    for name in "PLANNED → RED" "RED → GREEN"; do
      phase_region "**$name.**"
      if [ "$HAS_RG" = 0 ]; then printf '%s: has no `**%s.**` paragraph\n' "$ADVANCE" "$name"; continue; fi
      case "$RG" in *"$ATTEST_CHECK"*) ;; *) printf '%s: %s does not check the record\n' "$ADVANCE" "$name" ;; esac
      case "$RG" in *"$RERUN"*) printf '%s: %s still re-runs the tests\n' "$ADVANCE" "$name" ;; esac
    done
  fi
  # complete-story.md: the tool, then the BODY - the file after its frontmatter
  # (C-5 as amended on return 3). Since A-1 the frontmatter's allowed-tools
  # entry `Bash(bash scripts/attest.sh check:*)` itself contains the needle, so
  # judging the whole file would make "does not check the record" unfailable
  # while the entry stands.
  if [ ! -f "$root/$COMPLETE" ]; then printf '%s: file is missing\n' "$COMPLETE"
  else
    load "$root/$COMPLETE"; check_attest_tool "$COMPLETE"
    body_lines
    all="$(join_by ' ' "${BODY[@]}")"
    case "$all" in *"$ATTEST_CHECK"*) ;; *) printf '%s: does not check the record\n' "$COMPLETE" ;; esac
  fi
  # lead-po.md ## Orchestrating
  if [ ! -f "$root/$LEADPO" ]; then printf '%s: file is missing\n' "$LEADPO"
  else
    load "$root/$LEADPO"; section_text "## Orchestrating"
    if [ "$HAS_SX" = 0 ]; then printf '%s: has no `## Orchestrating` section\n' "$LEADPO"
    else
      case "$SX" in *"$ATTEST_CHECK"*) ;; *) printf '%s: does not check the record\n' "$LEADPO" ;; esac
    fi
  fi
  return 0
}

# --- a compliant tree, by construction --------------------------------------------
# Never copied from the real tree, which in RED is not compliant. The wording is
# nobody's contract; GREEN writes the real files (C-6). Each file also carries
# the near-misses the guard must NOT fire on, so silence here is a statement
# about them too:
#   * feature-developer: `bash scripts/gates.sh --fast` in backticks inside the
#     list; the full-run needle OUTSIDE ## Method.
#   * advance-story: a non-phase bold line inside PLANNED → RED before the check;
#     the allowed-tools entry with odd spacing.
#   * lead-po: `bash scripts/attest.sh check` split by nothing, inside the
#     section, after a sub-list.

# The check entry with odd spacing (trimmed, so equal), and a near-miss for the
# refused prefix: an entry that CONTAINS `Bash(bash scripts/attest.sh:*)` but is
# not equal to it, which has_entry's equality must not read as the prefix.
TOOLS_LINE='allowed-tools: Bash(bash scripts/phase.sh:*), Bash(bash scripts/gates.sh:*),   Bash(bash scripts/attest.sh check:*)  , Read, Task, NotBash(bash scripts/attest.sh:*)'

good_tree() { # <root>
  local r="$1"
  mkdir -p "$r/.claude/agents" "$r/.claude/commands"
  cat > "$r/$FD" <<'EOF'
---
name: feature-developer
---

## Method

1. Read the story.
2. Write the simplest thing.
3. Run the tests after each step.
4. Run the full suite.
5. Confirm every control.
6. Run `bash scripts/attest.sh -- bash scripts/gates.sh --fast` as soon as the
   tests are green; it is `bash scripts/gates.sh --fast`, recorded.
7. If this story changed a gate, probe it.

A GATES dispatch runs `scripts/gates.sh` without `--fast`.

## Reuse before you write

GATES runs `bash scripts/gates.sh`, not you.
EOF
  cat > "$r/$TD" <<'EOF'
---
name: test-developer
---

## Method

1. Read the story.
4. **Run them** as `bash scripts/attest.sh -- <test command>`.
7. Run `bash scripts/attest.sh -- bash scripts/gates.sh --fast` before you finish.

You may amend the contract.
EOF
  cat > "$r/$ADVANCE" <<EOF
---
description: x
$TOOLS_LINE
---

**PLANNED → RED.** Confirm the criteria.

**Pin the contract.** Paths and names.

When it returns, read the files it wrote, then run
\`bash scripts/attest.sh check -- <test command>\`; run it yourself only when the
answer is not \`fresh\`.

**RED → GREEN.** Check the handoff, then \`bash scripts/attest.sh check -- bash scripts/gates.sh --fast\`.

**GREEN → GATES.** Set the phase.

**GATES → REVIEW.** Review.
EOF
  cat > "$r/$COMPLETE" <<EOF
---
description: y
$TOOLS_LINE
---

- **RED and GREEN** each end with \`bash scripts/attest.sh check\`.
EOF
  cat > "$r/$LEADPO" <<'EOF'
---
name: lead-po
---

## Orchestrating

- the story id

- **A report of success is a claim;** `bash scripts/attest.sh check` is how you
  check it without paying for the run twice; `stale` means you run it.

## More than one worktree

Nothing.
EOF
}

# regress <name> <file> <awk program>   A compliant tree, then <file> rewritten
# by <awk program>. Echoes the tree's root.
regress() {
  local r="$WORK/ap-$1"
  rm -rf "$r"; good_tree "$r"
  awk "$3" "$r/$2" > "$r/$2.new" && mv "$r/$2.new" "$r/$2"
  printf '%s' "$r"
}

# expect_one <what> <root> <exact line>
expect_one() {
  assert_eq "$1" "$3" "$(attest_problems "$2")"
}

describe "AC-5  the guard is silent on the real tree"
real="$(attest_problems "$REPO_ROOT")"
assert_eq "attest_problems over REPO_ROOT prints nothing" "" "$real"

describe "AC-5  ...and on a tree compliant by construction, and fires once per regression"
good_tree "$WORK/ap-good"
assert_eq "a compliant tree: silent (near-misses included)" "" "$(attest_problems "$WORK/ap-good")"

R="$(regress fd-full "$FD" '{ print } /^5\. / { print "6. Run `bash scripts/gates.sh`. Fix what it reports." }')"
expect_one "feature-developer: a step running the full gate run" "$R" \
  ".claude/agents/feature-developer.md: still runs the full gate run in GREEN"
R="$(regress fd-full-cont "$FD" '{ print } /^5\. / { print "   Then run `bash scripts/gates.sh`." }')"
expect_one "feature-developer: the full run on a step's continuation line" "$R" \
  ".claude/agents/feature-developer.md: still runs the full gate run in GREEN"
R="$(regress fd-fast "$FD" '{ sub(/bash scripts\/attest\.sh -- bash scripts\/gates\.sh --fast/, "bash scripts/gates.sh --fast"); print }')"
expect_one "feature-developer: --fast run plainly, not through attest.sh" "$R" \
  ".claude/agents/feature-developer.md: does not run --fast through attest.sh"
R="$(regress fd-fast-out "$FD" '/^6\. / { print "6. Run the fast gates."; skip = 1; next } skip && /^   / { next } { skip = 0; print } /^## Reuse/ { print "Run `bash scripts/attest.sh -- bash scripts/gates.sh --fast`." }')"
expect_one "feature-developer: the attested --fast only outside ## Method" "$R" \
  ".claude/agents/feature-developer.md: does not run --fast through attest.sh"

R="$(regress td-tests "$TD" '/^4\. / { print "4. **Run them.** Record the output."; next } { print }')"
expect_one "test-developer: only the --fast line goes through attest.sh" "$R" \
  ".claude/agents/test-developer.md: does not run its tests through attest.sh"
R="$(regress td-fast "$TD" '/^7\. / { print "7. Run `bash scripts/gates.sh --fast` before you finish."; next } { print }')"
expect_one "test-developer: --fast run plainly" "$R" \
  ".claude/agents/test-developer.md: does not run --fast through attest.sh"

R="$(regress as-pr-check "$ADVANCE" '/attest\.sh check -- <test command>/ { print "`the test command`; read it."; next } { print }')"
expect_one "advance-story: PLANNED → RED does not name the check" "$R" \
  ".claude/commands/advance-story.md: PLANNED → RED does not check the record"
R="$(regress as-pr-rerun "$ADVANCE" '{ print } /^\*\*Pin the contract/ { print "Then run the tests yourself." }')"
expect_one "advance-story: PLANNED → RED re-runs the tests" "$R" \
  ".claude/commands/advance-story.md: PLANNED → RED still re-runs the tests"
R="$(regress as-pr-rerun-wrap "$ADVANCE" '{ print } /^\*\*Pin the contract/ { print "Then run the tests"; print "yourself." }')"
expect_one "advance-story: the re-run phrase wrapped over two lines is still found" "$R" \
  ".claude/commands/advance-story.md: PLANNED → RED still re-runs the tests"
R="$(regress as-rg-check "$ADVANCE" '/^\*\*RED → GREEN\.\*\*/ { print "**RED → GREEN.** Check the handoff."; next } /^\*\*GREEN → GATES\.\*\*/ { print "**GREEN → GATES.** Set the phase; `bash scripts/attest.sh check -- x`."; next } { print }')"
expect_one "advance-story: the check named only in the NEXT paragraph" "$R" \
  ".claude/commands/advance-story.md: RED → GREEN does not check the record"
R="$(regress as-rg-rerun "$ADVANCE" '{ print } /^\*\*RED → GREEN\.\*\*/ { print "When it returns, run the tests yourself." }')"
expect_one "advance-story: RED → GREEN re-runs the tests" "$R" \
  ".claude/commands/advance-story.md: RED → GREEN still re-runs the tests"
R="$(regress as-tool "$ADVANCE" '{ sub(/   Bash\(bash scripts\/attest\.sh check:\*\)  /, " XBash(bash scripts/attest.sh check:*)"); print }')"
expect_one "advance-story: an allowed-tools entry that CONTAINS the check pattern is not it" "$R" \
  ".claude/commands/advance-story.md: does not permit attest.sh check"
R="$(regress as-tool-any "$ADVANCE" '/^allowed-tools:/ { $0 = $0 ", Bash(bash scripts/attest.sh:*)" } { print }')"
expect_one "advance-story: the old prefix entry back beside the check entry (A-1)" "$R" \
  ".claude/commands/advance-story.md: permits attest.sh to run any command"
R="$(regress as-tool-old "$ADVANCE" '{ sub(/Bash\(bash scripts\/attest\.sh check:\*\)/, "Bash(bash scripts/attest.sh:*)"); print }')"
assert_eq "advance-story: the pre-A-1 entry alone is wrong both ways, one line each" \
  ".claude/commands/advance-story.md: does not permit attest.sh check
.claude/commands/advance-story.md: permits attest.sh to run any command" "$(attest_problems "$R")"
R="$(regress as-nopara "$ADVANCE" '{ sub(/^\*\*PLANNED → RED\.\*\*/, "**PLANNED.**"); print }')"
expect_one "advance-story: no PLANNED → RED paragraph at all" "$R" \
  '.claude/commands/advance-story.md: has no `**PLANNED → RED.**` paragraph'

R="$(regress cs-tool "$COMPLETE" '{ sub(/, +Bash\(bash scripts\/attest\.sh check:\*\) +/, ""); print }')"
expect_one "complete-story: allowed-tools without the check entry" "$R" \
  ".claude/commands/complete-story.md: does not permit attest.sh check"
R="$(regress cs-tool-any "$COMPLETE" '/^allowed-tools:/ { $0 = $0 ", Bash(bash scripts/attest.sh:*)" } { print }')"
expect_one "complete-story: the old prefix entry back beside the check entry (A-1)" "$R" \
  ".claude/commands/complete-story.md: permits attest.sh to run any command"
R="$(regress cs-check "$COMPLETE" '{ sub(/`bash scripts\/attest\.sh check`/, "`bash scripts/gates.sh --fast`"); print }')"
expect_one "complete-story: the check named only by the frontmatter's allowed-tools entry is not a check" "$R" \
  ".claude/commands/complete-story.md: does not check the record"

R="$(regress lp-check "$LEADPO" '/attest\.sh check/ { print "- **A report of success is a claim;** run it yourself."; next } { print } /^Nothing\./ { print "Use `bash scripts/attest.sh check` here." }')"
expect_one "lead-po: the check only outside ## Orchestrating" "$R" \
  ".claude/agents/lead-po.md: does not check the record"
R="$(regress lp-missing "$LEADPO" '0')"
expect_one "lead-po: an empty file has no ## Orchestrating" "$R" \
  '.claude/agents/lead-po.md: has no `## Orchestrating` section'

R="$WORK/ap-gone"; rm -rf "$R"; good_tree "$R"; rm -f "$R/$COMPLETE"
expect_one "a missing site is reported, once" "$R" ".claude/commands/complete-story.md: file is missing"

# ==============================================================================
describe "AC-6  the state README and settings.json carry the attest rows"
# ==============================================================================
# `rows` is COPIED from settings.test.sh, not sourced: the README table as that
# suite reads it. settings.test.sh then checks the rows and the deny rules
# against each other in both directions; this pins that the two rows exist.

TAB="$(printf '\t')"
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
RW="$(rows "$REPO_ROOT/.claude/state/README.md")"
assert_eq "README: attest.log is a row, hand-editable no" 1 "$(count_line "attest.log${TAB}no" "$RW")"
assert_eq "README: attest-logs/*.log is a row, hand-editable yes" 1 "$(count_line "attest-logs/*.log${TAB}yes" "$RW")"
DENY="$(awk '{ sub(/\r$/, ""); gsub(/^[ \t]+|[ \t,]+$/, ""); print }' "$REPO_ROOT/.claude/settings.json")"
assert_eq "settings.json denies Edit(./.claude/state/attest.log)" 1 \
  "$(count_line '"Edit(./.claude/state/attest.log)"' "$DENY")"

summary attest
