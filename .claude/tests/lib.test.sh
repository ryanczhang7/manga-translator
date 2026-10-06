#!/usr/bin/env bash
# Unit tests for .claude/hooks/lib.sh - the path classifier and the shell-quote
# masker the phase guard is built on.
#
# phase-guard.test.sh drives the hook end to end; this covers the pieces
# directly, so that a failure says which one broke.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_fixture)"
trap 'rm -rf "$FIX"' EXIT

export CLAUDE_PROJECT_DIR="$FIX"
. "$REPO_ROOT/.claude/hooks/lib.sh"

# ---------------------------------------------------------------------------
describe "classify: paths.conf rules"

for case in \
  "src/main.ts=source" \
  "src/deep/nested/thing.ts=source" \
  "tests/main.test.ts=test" \
  "src/main.test.ts=test" \
  "docs/backlog/stories/T-1.md=docs" \
  "README.md=docs" \
  ".claude/hooks/lib.sh=harness" \
  ".claude/tests/lib.test.sh=harness" \
  "scripts/gates.sh=harness" \
  ".github/workflows/gates.yml=harness" \
  "CLAUDE.md=harness" \
  ".gitignore=harness" \
  "src/ui/__import_guard_probe.ts=test" \
  "src/core/__probe_offending_import.ts=test" \
  "src/__probe_a.py=test" \
  "src/ui/heat_probe.ts=source" \
  "src/core/probe.ts=source" \
  "LICENSE=docs" \
  "LICENSE.md=docs" \
  "COPYING=docs" \
  "NOTICE=docs" \
  "AUTHORS=docs" \
  "CONTRIBUTORS=docs" \
  "CHANGELOG.md=docs" \
  "SECURITY.md=docs" \
  ".gitattributes=harness" \
  ".editorconfig=harness" \
  ".mailmap=harness" \
  "CODEOWNERS=harness" \
  "package.json=manifest" \
  "pyproject.toml=manifest" \
  "Cargo.toml=manifest" \
  "Cargo.lock=manifest" \
  "pnpm-lock.yaml=manifest" \
  "uv.lock=manifest" \
  "go.mod=config" \
  "requirements.txt=config" \
  "tsconfig.json=config" \
  "vite.config.ts=config" \
  "vitest.config.ts=test" \
  "node_modules/left-pad/index.js=vendor" \
  "node_modules=vendor" \
  "dist/bundle.js=vendor" \
  ; do
  assert_eq "classify ${case%%=*}" "${case#*=}" "$(classify "${case%%=*}")"
done

assert_eq "classify of nothing is outside" "outside" "$(classify "")"

# ---------------------------------------------------------------------------
describe "classify: git decides what is generated"

# In the fixture's .gitignore, matched by no paths.conf rule.
assert_eq "an ignored directory"        "ignored" "$(classify ".vitest")"
assert_eq "a file inside one"           "ignored" "$(classify ".vitest/screenshot.png")"
assert_eq "an ignored report directory" "ignored" "$(classify "playwright-report")"

# Tracked, so authored, whatever any rule says.
assert_eq "a tracked source file" "source" "$(classify "src/main.ts")"

# Not ignored and not matched: the conservative default.
assert_eq "an unknown new path" "source" "$(classify "src/brand-new.ts")"

# ---------------------------------------------------------------------------
describe "to_rel"

assert_eq "a relative path"        "src/main.ts" "$(to_rel "src/main.ts")"
assert_eq "a dot-relative path"    "src/main.ts" "$(to_rel "./src/main.ts")"
assert_eq "an absolute path"       "src/main.ts" "$(to_rel "$FIX/src/main.ts")"
assert_eq "a backslash path"       "src/main.ts" "$(to_rel "$(printf '%s' "$FIX" | tr '/' '\134')\\src\\main.ts")"
assert_eq "somewhere else on disk" ""            "$(to_rel "/somewhere/else/main.ts")"

# HARNESS-035 AC-5. One root, three drive spellings: MSYS `/d/p`, Windows `D:/p`
# and `D:\p`. to_rel used to tolerate the difference by asking whether the path
# contained `/<root's folder name>/`, which also took `/e/p` and
# `C:/elsewhere/p` for this repository and missed a worktree named anything
# else. Pure string work, so the roots need not exist.
for _root in '/d/p' 'D:/p' 'D:\p' 'd:/p/'; do
  for _path in 'D:\p\src\a.ts' 'D:/p/src/a.ts' '/d/p/src/a.ts' 'd:/P/src/a.ts'; do
    assert_eq "AC-5: root $_root, path $_path" "src/a.ts" "$(HARNESS_ROOT="$_root"; to_rel "$_path")"
  done
  assert_eq "AC-5 control: root $_root, /d/pp is a different folder"  "" "$(HARNESS_ROOT="$_root"; to_rel '/d/pp/src/a.ts')"
  assert_eq "AC-5 control: root $_root, /e/p is a different drive"    "" "$(HARNESS_ROOT="$_root"; to_rel '/e/p/src/a.ts')"
  assert_eq "AC-5 control: root $_root, C:/elsewhere/p is elsewhere"  "" "$(HARNESS_ROOT="$_root"; to_rel 'C:/elsewhere/p/src/a.ts')"
done
assert_eq "AC-5: /cygdrive/d/p is D:/p" "src/a.ts" "$(HARNESS_ROOT='D:/p'; to_rel '/cygdrive/d/p/src/a.ts')"

# ---------------------------------------------------------------------------
describe "mask_shell_quotes: operators inside quotes stop being operators"

mask() { printf '%s' "$1" | mask_shell_quotes; }
roundtrip() { printf '%s' "$1" | mask_shell_quotes | unmask_shell_quotes; }

# What the masker is for: no operator survives inside a quoted span.
#
# ONE awk, not `printf | grep -qE`. WORLD-086's guard reports that shape, and it
# reported this line: `grep -qE` leaves at its first match, the writer behind it
# can die of SIGPIPE, and `_lib.sh` puts this file under pipefail, so 141 would
# become the answer to "does this hold an operator". It is the very defect the
# masker below exists to make visible, sitting in the test that pins the masker.
#
# It escaped the guard's first port for a reason worth keeping: the body was
# split on `;` to find its last command, and the QUOTED `;` in the character
# class took the split with it. The guard now reads through mask_shell_quotes.
has_operator() { awk '/[|&;<>]/ { h = 1 } END { exit !h }' <<<"$1"; }

for cmd in \
  "sed -i 's|a|b|' f.txt" \
  "awk '/A -> B/' f.txt" \
  "grep -oE 'x>y' f.txt" \
  'git commit -m "fix: a > b"' \
  'echo "a && b; c"' \
  'git commit -m "$(printf "%s\n%s" "GATES -> REVIEW" "set the phase first")"' \
  ; do
  masked="$(mask "$cmd")"
  # Everything after the first quote is data; only the command word and the
  # options before it may still hold punctuation, and they hold none here.
  if has_operator "${masked#*[\'\"]}"; then
    _bad "masks operators in: $cmd" "still operator-bearing: $masked"
  else
    _ok "masks operators in: $cmd"
  fi
  assert_eq "round trip: $cmd" "$cmd" "$(roundtrip "$cmd")"
done

describe "mask_shell_quotes: structure outside quotes is preserved"

for cmd in \
  'echo hi > out.txt' \
  'cat a.txt | tee b.txt' \
  'rm -rf dist && mkdir dist' \
  'sed -i "s/a/b/" f.txt' \
  ; do
  assert_eq "round trip: $cmd" "$cmd" "$(roundtrip "$cmd")"
done

assert_contains "an unquoted redirect survives masking" ">" "$(mask 'echo hi > out.txt')"
assert_contains "an unquoted pipe survives masking"     "|" "$(mask 'cat a | tee b')"

describe "mask_shell_quotes: heredocs and escapes"

hd="$(mask "$(printf 'cat > notes.md <<%sEOF%s\nrun: cat > src/main.ts\nEOF\n' "'" "'")")"
assert_contains "the real redirect survives" "> notes.md" "$hd"
# awk over a here-string, not `printf | grep -q`. `grep -q` leaves at its first
# match, the printf behind it dies of SIGPIPE, and pipefail promotes 141 to the
# status this `if` reads - so a body's surviving redirect reads as "masked".
# The needle carries no regex metacharacter, so index() is the same test.
# WORLD-086 R-1.
if awk 'BEGIN { n = ARGV[1]; ARGV[1] = "" } index($0, n) { h = 1 } END { exit !h }' \
     '> src/main.ts' <<<"$hd"; then
  _bad "a heredoc body is masked" "the body's redirect survived: $hd"
else
  _ok "a heredoc body is masked"
fi

assert_eq "an escaped operator is masked" "0" \
  "$(mask 'echo a \> b' | grep -cE '>')"


describe "mask_shell_quotes: a here-string opens nothing"

# `<<<` is a HERE-STRING. The word after it is its DATA, and no heredoc body
# follows. The scanner used to walk past the first `<` and reach the SECOND,
# where the remaining text reads `<< WORD` - a perfect match for the heredoc
# opener - and take that word for a delimiter. Every following line was then
# masked as heredoc body, waiting for a line equal to it that never arrives.
#
# ONE-LINE COMMANDS WERE UNHARMED, which is why it survived: the false delimiter
# only takes effect from the NEXT line. So the assertion that matters is the
# multi-line one, and a fix tested only on one line would look correct.
hs="$(mask "$(printf 'grep x <<< "$data"\necho hi > src/main.ts\n')")"
assert_contains "a redirect on the line AFTER a here-string is still syntax" \
  "> src/main.ts" "$hs"

# The control that keeps it honest: a REAL heredoc still opens one, so the
# redirect in its body is still data. A fix that simply stopped opening
# heredocs would pass the assertion above and fail this.
rhd="$(mask "$(printf 'cat > notes.md <<%sEOF%s\necho hi > src/main.ts\nEOF\n' "'" "'")")"
if awk 'BEGIN { n = ARGV[1]; ARGV[1] = "" } index($0, n) { h = 1 } END { exit !h }' \
     '> src/main.ts' <<<"$rhd"; then
  _bad "a real heredoc body is still masked" "the body's redirect survived: $rhd"
else
  _ok "a real heredoc body is still masked"
fi

# And the here-string's own data is still data - the `>` here is a character in
# a string, not a redirect.
hsd="$(mask 'grep x <<< "a > b"')"
assert_eq "the here-string word itself is still masked" "0" \
  "$(printf '%s' "$hsd" | grep -cE '> b')"
describe "mask_shell_quotes: a backslash inside double quotes is usually a backslash"

# Bash escapes only five things inside double quotes: $ ` " \ and newline.
# Every other backslash is literal - which is every backslash in a Windows
# path. A masker that eats them turns the scratchpad this harness tells agents
# to use into `C:UsersryancAppDataLocalTempclaude`, which is not outside the
# repository as far as to_rel can tell, so it falls through to `source` and the
# write is denied. Observed on a Windows machine in RED.
for cmd in \
  'echo x > "C:\Users\ryanc\AppData\Local\Temp\claude\n.txt"' \
  'cd "C:\Users\ryanc\AppData\Local\Temp\claude" && rm -rf x' \
  'printf "%s\n" "a\tb"' \
  ; do
  assert_eq "round trip keeps literal backslashes: $cmd" "$cmd" "$(roundtrip "$cmd")"
done
# The ones that ARE escapes still are: the escaped quote does not end the
# string, so the arrow inside it is masked and only the real redirect is left.
assert_eq "an escaped quote does not end the string" "1" \
  "$(mask 'echo "a \" > b" > docs/notes.md' | tr -cd '>' | wc -c | tr -d ' ')"

describe "mask_shell_quotes: a comment is data to the end of the line"

# `# it's fine` - the apostrophe opens a single-quoted span that never closes,
# and everything after it, on every following line, is masked. A real redirect
# on the next line vanished. Observed by probe, not in the field, but the
# shape - a chatty comment, then the write - is an everyday one.
two="$(printf 'echo hi # it%ss fine\necho x > src/main.ts' "'")"
assert_contains "a redirect after a commented apostrophe survives" "> src/main.ts" "$(mask "$two")"
assert_eq "a # inside a word is not a comment" "echo a#b > out.txt" "$(mask 'echo a#b > out.txt' | unmask_shell_quotes)"
assert_contains "a # inside a word still leaves the redirect" ">" "$(mask 'echo a#b > out.txt')"

# ---------------------------------------------------------------------------
describe "json_escape: a backslash is escaped, not dropped"

# The deny reason is emitted as JSON. A backslash in it - a Windows path, a
# regex the guard quotes back - has to arrive doubled or the hook's output is
# not JSON at all.
assert_eq "a backslash"      'a\\b'     "$(json_escape 'a\b')"
assert_eq "a quote"          'a\"b'     "$(json_escape 'a"b')"
assert_eq "a newline"        'a\nb'     "$(json_escape "$(printf 'a\nb')")"
assert_eq "a tab"            'a\tb'     "$(json_escape "$(printf 'a\tb')")"
assert_eq "a carriage return is dropped" 'ab' "$(json_escape "$(printf 'a\rb')")"

# ---------------------------------------------------------------------------
describe "gate_tree_hash: agrees with the committed tree whatever autocrlf says"

# The hash is recorded from the working tree and recomputed by CI from the PR
# head commit. Adding into an EMPTY index treats every file as new, so git
# applies CRLF normalisation the real commit never had - and the two hashes
# disagree on any CRLF file committed before .gitattributes pinned LF. Then
# re-running the gates cannot fix it, because the working tree is not what is
# wrong.
HARNESS_ROOT="$FIX"
git -C "$FIX" config core.autocrlf false
printf 'export const crlf = 1\r\n' > "$FIX/src/crlf.ts"
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "crlf file" >/dev/null 2>&1
git -C "$FIX" config core.autocrlf true
assert_eq "working tree hash equals HEAD hash under autocrlf=true" \
  "$(gate_tree_hash_of HEAD)" "$(gate_tree_hash)"
git -C "$FIX" config core.autocrlf false

# ---------------------------------------------------------------------------
describe "portability: the harness runs on bash 3.2 and BSD tools"

# gates.sh names bash 3.2 as a target and macOS ships 3.2.57. `${var,,}`
# is a bash 4 feature; on 3.2 it is a "bad substitution" that kills to_rel,
# and a to_rel that dies makes check_path return "allow" - the lock silently
# off on every stock Mac. `sed -i` with no suffix is GNU-only; BSD sed reads
# the next argument as the backup suffix. Both are caught here by reading the
# code, because nothing else in this suite can run the other platform.
shipped="$(ls "$REPO_ROOT"/scripts/*.sh "$REPO_ROOT"/.claude/hooks/*.sh)"
hits="$(grep -nE '\$\{[A-Za-z_][A-Za-z0-9_]*(,,|\^\^)\}' $shipped || true)"
assert_eq "no \${var,,} or \${var^^} in shipped scripts" "" "$hits"
hits="$(grep -nE '(^|[[:space:]|;&(])sed[[:space:]]+(-[A-Za-z]*\s+)*-i([[:space:]]|$)' $shipped || true)"
assert_eq "no GNU-only sed -i in shipped scripts" "" "$hits"

# A fallback that cannot fire is not a fallback. Every suite opens with
# `mktemp -d 2>/dev/null || mktemp -d -t harness`, and GNU's -t wants X's in the
# template: `mktemp -d -t harness` is "too few X's in template". So on the only
# platform where the first half could fail, the second half fails too. Latent,
# because plain `mktemp -d` is universal - and exactly the kind of guard that
# reads as handled in review. Found by a consuming project pre-checking this
# repository's suites for Linux hazards before running them there.
#
# The failure MESSAGE carries two facts, and both are load-bearing for a reader
# who is not in this conversation. This check scans `.claude/tests/*.sh`, which
# in a vendored copy includes the PROJECT'S OWN suites - so an upstream
# portability rule can fail on a file the project wrote. That is deliberate: the
# hazard is identical wherever the idiom appears, and a rule that stops applying
# the moment it is vendored is one more check nothing has to listen to. But an
# agent with a fresh context sees an upstream rule failing on its own file and
# reads "the vendored suite is stale", which makes skipping it feel like the
# careful move. So the message says that project files are in scope on purpose,
# and gives the exact replacement rather than making the reader derive it.
hits="$(grep -rnE 'mktemp -d[^|)]*-t [A-Za-z0-9_.-]+' "$REPO_ROOT"/.claude/tests/*.sh "$REPO_ROOT"/scripts/*.sh 2>/dev/null \
  | grep -vE ':[0-9]+:[[:space:]]*#' | grep -v 'XXX' || true)"
if [ -z "$hits" ]; then
  _ok "no mktemp -t template without X's"
else
  # The example below is deliberately NOT written as a contiguous
  # 'mktemp' + '-d' + '-t name', because this message is itself inside a file
  # this check scans - writing the broken form here makes the message a hit and
  # the check report itself. It did, on the first run.
  _bad "no mktemp -t template without X's" "GNU's -t needs X's in the template: a -t given a bare name fails with
\"too few X's in template\", so the fallback cannot run on the one platform
where the plain create-a-temp-dir call before it could fail.

Fix each site by adding them:   -t name   ->   -t name.XXXXXX

PROJECT-OWNED SUITES ARE IN SCOPE ON PURPOSE. If one of the files below is
yours rather than the harness's, that is not a stale vendored suite and not a
reason to skip this - the idiom is broken wherever it appears, and this rule
reaching your files is the point of it. Fix it in place; it is one line.

$hits"
fi

# $TMPDIR is unset in some of the shells this harness runs in, and the one place
# that mattered - a mutation backup - lost its backup to exactly that, leaving
# the restore to depend on the sed expression happening to be an exact inverse.
# Nothing shipped may write to a temporary directory it did not name itself.
# Comments are allowed to mention it; code is not.
hits="$(grep -nE '\$\{?TMPDIR|\bmktemp\b' $shipped | grep -vE ':[[:space:]]*#' || true)"
assert_eq "no shipped script depends on \$TMPDIR or mktemp" "" "$hits"

# ---------------------------------------------------------------------------
describe "glob_matches: the paths.conf glob dialect, reusable"

# `covers` lines in project.conf use the same globs as paths.conf, through the
# same function, so a glob that classifies a path also covers it.
for pair in \
  'src/**=src/render/mesh.ts' \
  'src/**=src/a.ts' \
  'src/render/**=src/render/deep/x.ts' \
  '**/*.test.*=src/a.test.ts' \
  'src/*.ts=src/a.ts' \
  'SRC/**=src/a.ts' \
  ; do
  g="${pair%%=*}"; p="${pair#*=}"
  if glob_matches "$g" "$p"; then _ok "matches: $g ~ $p"; else _bad "matches: $g ~ $p" "no match"; fi
done
for pair in \
  'src/render/**=src/core/a.ts' \
  'src/*.ts=src/deep/a.ts' \
  'src/**=lib/src/a.ts' \
  'src/a.ts=src/a.tsx' \
  ; do
  g="${pair%%=*}"; p="${pair#*=}"
  if glob_matches "$g" "$p"; then _bad "does not match: $g ~ $p" "matched"; else _ok "does not match: $g ~ $p"; fi
done

# ---------------------------------------------------------------------------
describe "gate_tree_hash: covers what the gates judge, and only that"

# The hash is the identity of "the code the gates ran against". A change to a
# file no gate reads must not move it, or every prompt edit after the last run
# forces a re-run before the PR is acceptable - and it does have to move on a
# change to anything a gate does read, or the record proves nothing.
#
# EVERY FILE BELOW IS TRACKED BEFORE h0 IS TAKEN. HARNESS-014: the hash is the
# tree `git commit -a` would make, so an UNTRACKED file moves nothing whatever it
# classifies as. The first form of this block wrote the prompt, the hook and the
# docs file without committing them, which meant "a hook moves the hash" passed
# only because untracked files were hashed (the defect), and the two negatives
# would have passed against a hash that counted markdown - vacuous, by tracking
# status rather than by class. Committing first is what makes each assertion
# below discriminate by CLASS, which is the claim in its name.
HARNESS_ROOT="$FIX"
fix_commit() { # <message>   Everything in the fixture, tracked and committed.
  git -C "$FIX" add -A >/dev/null 2>&1
  git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "$1" >/dev/null 2>&1
}
mkdir -p "$FIX/.claude/commands" "$FIX/.claude/hooks"
printf '# advance\n' > "$FIX/.claude/commands/advance-story.md"
printf 'x() { :; }\n' > "$FIX/.claude/hooks/lib.sh"
fix_commit "a prompt and a hook, tracked"
h0="$(gate_tree_hash)"
printf '# advance, reworded\n' > "$FIX/.claude/commands/advance-story.md"
assert_eq "a command prompt does not move the hash" "$h0" "$(gate_tree_hash)"
printf '# a wiki page\n' > "$FIX/docs/notes.md"
assert_eq "a docs file does not move the hash"      "$h0" "$(gate_tree_hash)"
printf 'y() { :; }\n' > "$FIX/.claude/hooks/lib.sh"
h1="$(gate_tree_hash)"
if [ "$h1" = "$h0" ]; then _bad "a hook moves the hash" "unchanged: $h0"; else _ok "a hook moves the hash"; fi
printf 'export const x = 2\n' > "$FIX/src/main.ts"
h2="$(gate_tree_hash)"
if [ "$h2" = "$h1" ]; then _bad "source moves the hash" "unchanged: $h1"; else _ok "source moves the hash"; fi
# The discriminator for the rewrite above: the same class of file, UNTRACKED,
# moves nothing. Against the pre-HARNESS-014 hash this is red, because that hash
# folded every untracked non-ignored file in.
printf 'z() { :; }\n' > "$FIX/.claude/hooks/other.sh"
assert_eq "an untracked hook does not move the hash" "$h2" "$(gate_tree_hash)"
rm -f "$FIX/.claude/hooks/other.sh"

# ---------------------------------------------------------------------------
describe "gate_tree_hash: the tree the commit would have, not the working directory (HARNESS-014)"

# The stamp is recomputed by CI from the PR head commit, which contains no
# untracked file. Locally it was computed with `git add -A` over a HEAD-seeded
# index, so a stray `.patch` in the checkout moved it and CI refused a record
# that was correct for the code. The fix: seed from the REAL index and `add -u`
# - tracked files as they stand, plus whatever is staged, minus deletions.
fix_commit "everything tracked before the untracked cases"

# AC-1, positive. Two untracked gated files, one per class the specimen had:
# `handoff/x.patch` falls through paths.conf to `source`, exactly as
# handoff-world-080/*.patch does; the second classifies `test`.
mkdir -p "$FIX/handoff"
printf 'diff --git a/x b/x\n' > "$FIX/handoff/x.patch"
printf 'test("stray", () => {})\n' > "$FIX/tests/stray.test.ts"
assert_eq "fixture: the stray patch classifies as source" "source" "$(classify "handoff/x.patch")"
assert_eq "fixture: the stray test classifies as test"    "test"   "$(classify "tests/stray.test.ts")"
assert_eq "AC-1: an untracked gated file does not move the stamp off HEAD's" \
  "$(gate_tree_hash_of HEAD)" "$(gate_tree_hash)"

# AC-1, control. The working tree still counts for files git TRACKS: an
# unstaged edit to a tracked source file moves the hash off HEAD's. A fix that
# simply hashed HEAD passes the positive case and fails here.
printf 'export const x = 3\n' > "$FIX/src/main.ts"
before_status="$(git -C "$FIX" status --porcelain)"
before_cached="$(git -C "$FIX" diff --cached)"
if [ "$(gate_tree_hash)" = "$(gate_tree_hash_of HEAD)" ]; then
  _bad "AC-1 control: an unstaged edit to a TRACKED source file moves the stamp" "still equal to HEAD's: $(gate_tree_hash_of HEAD)"
else
  _ok "AC-1 control: an unstaged edit to a TRACKED source file moves the stamp"
fi

# C-1: the real index is never written. `git status` and the staged diff are
# byte-identical before and after that run - taken WITH the unstaged edit and
# the strays present, because that is the state in which a `git add -u` that
# leaked into the real index would have something to stage.
assert_eq "C-1: gate_tree_hash leaves git status --porcelain unchanged" \
  "$before_status" "$(git -C "$FIX" status --porcelain)"
assert_eq "C-1: and leaves the staged diff unchanged" \
  "$before_cached" "$(git -C "$FIX" diff --cached)"
git -C "$FIX" checkout -q -- src/main.ts 2>/dev/null
rm -rf "$FIX/handoff" "$FIX/tests/stray.test.ts"

# AC-3, positive: a file the story creates is covered once it is STAGED. The
# hash taken with the file staged equals CI's hash of the commit that follows.
printf 'export const staged = 1\n' > "$FIX/src/staged-module.ts"
git -C "$FIX" add src/staged-module.ts >/dev/null 2>&1
h_staged="$(gate_tree_hash)"
fix_commit "the staged module, committed"
assert_eq "AC-3: a staged new file is in the stamp, which equals the following commit's" \
  "$(gate_tree_hash_of HEAD)" "$h_staged"

# AC-3, control: the same file written but NOT staged is not in the stamp, so
# the stamp does not equal the commit that later contains it. This is exactly
# the file AC-4 exists to name; against the pre-HARNESS-014 hash it is red,
# because `add -A` folded the unstaged file in and the two hashes agreed.
printf 'export const unstaged = 1\n' > "$FIX/src/unstaged-module.ts"
h_unstaged="$(gate_tree_hash)"
fix_commit "the unstaged module, committed after the hash was taken"
if [ "$h_unstaged" = "$(gate_tree_hash_of HEAD)" ]; then
  _bad "AC-3 control: an UNSTAGED new file is not in the stamp, so it differs from the later commit's" \
    "the stamp already equalled the later commit's hash: $h_unstaged"
else
  _ok "AC-3 control: an UNSTAGED new file is not in the stamp, so it differs from the later commit's"
fi

# ---------------------------------------------------------------------------
describe "untracked_gated: the one definition of an untracked gated file (HARNESS-014, C-2)"

# gates.sh names what this prints and refuses to record while it is non-empty.
# It is `git ls-files --others --exclude-standard`, kept to what gated_stdin
# keeps: so `.gitignore` AND `.git/info/exclude` both count (AC-6), docs and
# harness markdown are never named, and nothing under .claude/state/ is.
fix_commit "clean before the listing cases"
out="$(untracked_gated 2>&1)"; rc=$?
assert_eq "with no untracked gated file it prints nothing" "" "$out"
assert_eq "and returns 0"                                  "0" "$rc"

mkdir -p "$FIX/handoff" "$FIX/.claude/commands" "$FIX/.claude/state"
printf 'diff --git a/x b/x\n' > "$FIX/handoff/x.patch"          # source
printf 'test("stray", () => {})\n' > "$FIX/tests/stray.test.ts"  # test
printf 'export const z = 1\n' > "$FIX/Zed.ts"                    # source; sorts FIRST under LC_ALL=C
printf '# stray notes\n' > "$FIX/notes.md"                       # docs: never named
printf '# a prompt\n' > "$FIX/.claude/commands/x.md"             # harness markdown: never named
printf 'STORY_ID=T-9\n' > "$FIX/.claude/state/current-story.env" # harness state: never named
out="$(untracked_gated 2>&1)"; rc=$?
assert_eq "lists every untracked gated file, repo-relative, LC_ALL=C sorted, one per line" \
  "$(printf 'Zed.ts\nhandoff/x.patch\ntests/stray.test.ts')" "$out"
assert_eq "and returns 0 when it printed something" "0" "$rc"
rm -f "$FIX/Zed.ts" "$FIX/notes.md" "$FIX/.claude/commands/x.md" "$FIX/.claude/state/current-story.env"

# AC-6: an untracked file that WOULD classify as source, but is ignored. Both
# ignore files, because .git/info/exclude is the remedy the refusal points a
# user to for a stray they mean to keep, so it has to actually work.
printf 'src/scratch-ignored.ts\n' >> "$FIX/.gitignore"
# Commit ONLY .gitignore (it is gated, so HEAD carries it). Not fix_commit: that
# is `add -A`, which would track handoff/x.patch and tests/stray.test.ts, and
# the three "is listed" assertions below read them as UNTRACKED (R-1a).
git -C "$FIX" add .gitignore >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "ignore rule for the scratch file" >/dev/null 2>&1
h_clean="$(gate_tree_hash_of HEAD)"
printf 'export const scratch = 1\n' > "$FIX/src/scratch-ignored.ts"
assert_eq "fixture: the .gitignore'd scratch file classifies as ignored" "ignored" "$(classify "src/scratch-ignored.ts")"
assert_eq "AC-6: a .gitignore'd file does not move the stamp" "$h_clean" "$(gate_tree_hash)"
assert_eq "AC-6: and is not listed by untracked_gated" \
  "$(printf 'handoff/x.patch\ntests/stray.test.ts')" "$(untracked_gated 2>&1)"

printf 'src/scratch-excluded.ts\n' >> "$FIX/.git/info/exclude"
printf 'export const excluded = 1\n' > "$FIX/src/scratch-excluded.ts"
assert_eq "AC-6: a file excluded through .git/info/exclude does not move the stamp" "$h_clean" "$(gate_tree_hash)"
assert_eq "AC-6: and is not listed by untracked_gated either" \
  "$(printf 'handoff/x.patch\ntests/stray.test.ts')" "$(untracked_gated 2>&1)"

# AC-6, control: with the exclude rule removed the same file IS an untracked
# gated file, and is listed. Without this, "list nothing" passes every AC-6
# assertion above.
grep -v 'src/scratch-excluded.ts' "$FIX/.git/info/exclude" > "$FIX/.git/info/exclude.new"
mv "$FIX/.git/info/exclude.new" "$FIX/.git/info/exclude"
assert_eq "AC-6 control: with the exclude rule removed the same file is listed" \
  "$(printf 'handoff/x.patch\nsrc/scratch-excluded.ts\ntests/stray.test.ts')" "$(untracked_gated 2>&1)"
assert_eq "AC-6 control: and it still does not move the stamp - untracked is untracked" "$h_clean" "$(gate_tree_hash)"

rm -rf "$FIX/handoff" "$FIX/tests/stray.test.ts" "$FIX/src/scratch-ignored.ts" "$FIX/src/scratch-excluded.ts"

# ---------------------------------------------------------------------------
describe "path_is_implausible: a failed parse is inconclusive, not a violation"

# The tokens on the left were all reported as the `path:` of a real denial, on
# commands that wrote nothing. None of them is a path; the guard declines to
# judge them rather than treating its own parse failure as evidence.
for t in '=' '[^' '--' '>' '' '`mktemp`' '$TMPDIR/x' 'a(b)'; do
  if path_is_implausible "$t"; then _ok "implausible: '$t'"
  else _bad "implausible: '$t'" "the guard believed this was a path"; fi
done

# The other half of the rule, and the one that keeps it honest: everything a
# real project actually names must still be judged. A bracketed route segment
# is a real path in more than one framework.
for t in 'src/main.ts' 'src/app/[id]/page.tsx' 'src/my file.ts' '.gitignore' \
         'a' 'docs/wiki/architecture.md' 'src/a-b_c.2.ts'; do
  if path_is_implausible "$t"; then _bad "plausible: '$t'" "the guard refused to judge a real path"
  else _ok "plausible: '$t'"; fi
done


# ---------------------------------------------------------------------------
describe "shell_assignments: what the command text says a variable holds"

m() { printf '%s' "$1" | mask_shell_quotes; }

assert_eq "a bare assignment" "F=src/main.ts" \
  "$(shell_assignments "$(m 'F=src/main.ts; rm "$F"')")"
assert_eq "a quoted value keeps its path, loses its quotes" "F=src/main.ts" \
  "$(shell_assignments "$(m 'F="src/main.ts"; rm "$F"')")"

# Longest name first, so that a rule for $F cannot eat $FILE.
assert_eq "longest name first" "FILE=src/a.ts
F=docs" \
  "$(shell_assignments "$(m 'F=docs; FILE=src/a.ts; rm "$FILE"')")"

# Inside quotes there is no assignment, only text. Masking is what makes this
# true without a second parser: the space before it is a control character by
# now, so the pattern cannot match.
assert_eq "an equals sign inside a commit message" "" \
  "$(shell_assignments "$(m 'git commit -m "note: A=b was wrong"')")"
assert_eq "an equals sign inside a quoted printf" "" \
  "$(shell_assignments "$(m "printf '%s' 'X=y'")")"

# ---------------------------------------------------------------------------
describe "resolve_vars: resolved, or left with its \$ for the decline to catch"

A="$(shell_assignments "$(m 'F=src/main.ts; D=src')")"
assert_eq "a plain expansion"  "src/main.ts" "$(resolve_vars '$F' "$A")"
assert_eq "a braced expansion" "src/main.ts" "$(resolve_vars '${F}' "$A")"
assert_eq "a variable plus a suffix" "src/main.ts" "$(resolve_vars '$D/main.ts' "$A")"
assert_eq "text with no variable is returned unchanged" "src/main.ts" \
  "$(resolve_vars 'src/main.ts' "$A")"

# The honest limit: the guard reads one command string, not the shell's
# environment. What it cannot resolve keeps its `$`, and path_is_implausible
# declines on it rather than pretending to have checked it.
assert_eq "an unknown name survives untouched" '$ELSEWHERE' \
  "$(resolve_vars '$ELSEWHERE' "$A")"
if path_is_implausible "$(resolve_vars '$ELSEWHERE' "$A")"; then
  _ok "and is then declined"
else _bad "and is then declined" "the guard believed an unresolved variable was a path"; fi

# ---------------------------------------------------------------------------
describe "mutate_targets: the one file a mutation is allowed to touch"

assert_eq "the FILE argument" "src/main.ts" \
  "$(mutate_targets "$(m "bash scripts/mutate.sh src/main.ts 's/a/b/' -- true")")"
assert_eq "quoted, with a | in the expression" "src/main.ts" \
  "$(mutate_targets "$(m "bash scripts/mutate.sh \"src/main.ts\" 's|a|b|' -- true")")"
assert_eq "nothing when mutate.sh is not involved" "" \
  "$(mutate_targets "$(m "sed -i 's/a/b/' src/main.ts")")"

# A file that merely happens to be called mutate.sh is not this script.
assert_eq "only scripts/mutate.sh" "" \
  "$(mutate_targets "$(m "bash tools/mutate.sh src/main.ts 's/a/b/' -- true")")"

# ---------------------------------------------------------------------------
# HARNESS-010. The reconciled write-target parser, asked directly.
#
# phase-guard.test.sh drives the same thing end to end through the hook; this
# section is the cheapest level that can falsify AC-2 and AC-3, because it can
# see the ROLE of every operand, while the hook only ever reports the role of
# the ONE candidate it happens to deny first.
#
# C-4: write_candidates() lives in lib.sh, takes MASKED command text, and emits
# a verdict line - `W` when the command names a write-capable tool at a real
# token boundary, `-` when it does not - followed by one line per candidate,
# either `TARGET` or `TARGET<TAB>ROLE`.
#
# wcand() renders that as one string so an assertion can be an EQUALITY on the
# whole answer rather than a containment in part of it. Three properties of the
# rendering are deliberate:
#
#   * the verdict is kept, and an absent function renders `<no output>`. That is
#     what stops every "yields no target" control from passing VACUOUSLY while
#     write_candidates does not exist: `-` is not `<no output>`, so the controls
#     go red in RED along with everything else rather than agreeing with a
#     function that is not there.
#   * the candidates are SORTED, so the assertions pin the SET and the roles and
#     not an emission order no clause of C-4 fixes. LC_ALL=C, because a locale
#     that ignores punctuation would order `/dev/null` against `src/main.ts`
#     differently on CI than here.
#   * one awk, no `grep -c`, no `head -1` under pipefail - check-sigpipe.sh and
#     check-grep-count.sh judge this file too.
wcand() {
  local masked out verdict rest
  masked="$(printf '%s' "$1" | mask_shell_quotes)"
  out="$(write_candidates "$masked" 2>/dev/null)"
  if [ -z "$out" ]; then printf '<no output>'; return 0; fi
  verdict="${out%%$'\n'*}"
  rest="${out#*$'\n'}"
  [ "$rest" = "$out" ] && rest=""
  printf '%s%s' "$verdict" \
    "$(printf '%s\n' "$rest" \
        | awk -F'\t' '$0 != "" { print (NF > 1 ? $1 " :: " $2 : $0) }' \
        | LC_ALL=C sort \
        | awk '{ printf " | %s", $0 }')" \
    | unmask_shell_quotes
}

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-6 and C-4: the parser is a named function of lib.sh"

# AC-6 says the parser lives in ONE place and every caller asks it rather than
# re-deriving - the rule rules.md already states for classify.sh. The criterion
# is marked "verified by review", and review is the right owner of "every
# caller"; this pins the half that is mechanical, so review reads a design
# question rather than checking whether a function exists.
assert_eq "write_candidates is a function, not an inline pipeline" "function" \
  "$(type -t write_candidates 2>/dev/null)"

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-2: sed in-place is decided per word"

# The nine forms AC-2 names. The first eight write in place; `-n` does not.
#
# `--i` is the live disagreement of C-1: upstream BLOCKS it, manga-translator
# ALLOWS it, and upstream is right - GNU getopt_long honours any unambiguous
# abbreviation and --in-place is the only long option of GNU sed 4.9 beginning
# `--i`. So the long option is a PREFIX test and never a literal match.
assert_eq "-i"                  "W | src/main.ts" "$(wcand "sed -i 's/a/b/' src/main.ts")"
assert_eq "-i.bak"              "W | src/main.ts" "$(wcand "sed -i.bak 's/a/b/' src/main.ts")"
assert_eq "-ni bundled"         "W | src/main.ts" "$(wcand "sed -ni 's/a/b/' src/main.ts")"
assert_eq "-Ei bundled"         "W | src/main.ts" "$(wcand "sed -Ei 's/a/b/' src/main.ts")"
assert_eq "-rin bundled"        "W | src/main.ts" "$(wcand "sed -rin 's/a/b/' src/main.ts")"
assert_eq "--i abbreviated"     "W | src/main.ts" "$(wcand "sed --i 's/a/b/' src/main.ts")"
assert_eq "--in-pl abbreviated" "W | src/main.ts" "$(wcand "sed --in-pl 's/a/b/' src/main.ts")"
assert_eq "--in-place"          "W | src/main.ts" "$(wcand "sed --in-place 's/a/b/' src/main.ts")"
assert_eq "--in-place=.bak"     "W | src/main.ts" "$(wcand "sed --in-place=.bak 's/a/b/' src/main.ts")"

# The read-only forms yield NO target, and the verdict says the command was
# never write-capable rather than write-capable-with-nothing-found.
assert_eq "-n is a read"               "-" "$(wcand "sed -n '1,5p' src/main.ts")"
assert_eq "no option at all is a read" "-" "$(wcand "sed 's/a/b/' src/main.ts")"

# AC-2's CONTROL, and the reason the per-word test exists at all: the real
# tests/guards/layer-imports.test.ts false positive. The FILENAME contains the
# two characters `-i`, and a substring test refused a pure read on the very file
# it was reading. A filename is not an option.
assert_eq "AC-2 control: an -i bearing FILENAME under sed -n yields no target" "-" \
  "$(wcand "sed -n '1,5p' tests/guards/layer-imports.test.ts")"
assert_eq "AC-2 control: the same shape at the repository root" "-" \
  "$(wcand "sed -n '1,5p' notes-inline.txt")"

# The hole that control must not open from the other end: an -i bearing path is
# not exempt from being WRITTEN. "Skip candidates whose name contains -i"
# satisfies every must-permit case above and deletes this protection entirely.
assert_eq "an -i bearing path is still the target of a real sed -i" \
  "W | src/lib/layer-imports.ts" "$(wcand "sed -i 's/a/b/' src/lib/layer-imports.ts")"

# --silent is GNU's long form of -n. It CONTAINS an i and writes nothing, which
# is why the long option is a prefix test of `in-place` rather than a search for
# the letter.
assert_eq "--silent contains an i and writes nothing" "-" \
  "$(wcand "sed --silent '1,5p' src/main.ts")"

# EVERY positional is judged, not the last word of the match. `sed -i EXPR a b`
# writes both, and an extractor ending in `awk '{print $NF}'` saw only `b` - the
# cross-run reddened exactly this as "a frozen operand followed by a permitted
# one".
assert_eq "both operands of a two-file in-place edit" \
  "W | docs/notes.md | src/main.ts" \
  "$(wcand "sed -i 's/a/b/' src/main.ts docs/notes.md")"

# With -e or -f supplying the script, the FIRST positional is a file too.
assert_eq "-e supplies the script, so the first positional is a file" \
  "W | src/main.ts" "$(wcand "sed -i -e 's/a/b/' src/main.ts")"
assert_eq "-f supplies the script, so the first positional is a file" \
  "W | src/main.ts" "$(wcand "sed -i -f script.sed src/main.ts")"

# A trailing redirect is the redirect rule's business and does not displace the
# operand. Both appear here; the hook drops /dev/null with its own filter.
assert_eq "a trailing redirect does not hide the operand" \
  "W | /dev/null | src/main.ts" \
  "$(wcand "sed -i 's/a/b/' src/main.ts > /dev/null")"

# A metacharacter in the expression is data. `(` used to terminate the
# extractor's character class INSIDE the script and return a fragment of it.
assert_eq "a capture group in the expression" "W | src/main.ts" \
  "$(wcand "sed -i 's/\\(a\\)/b/' src/main.ts")"
assert_eq "a negated address and a capture group" "W | src/main.ts" \
  "$(wcand "sed -i '/x/!s/\\(a\\)/b/' src/main.ts")"
assert_eq "a pipe delimiter" "W | src/main.ts" \
  "$(wcand "sed -i 's|a|b|' src/main.ts")"

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-3: every mv operand carries the role it plays"

# AC-3's CONTROL, and the whole point of the section: THE SAME TOKEN is a
# destination in one form and a source in the other. Nothing differs between
# these two commands except operand order, the hook denies on src/main.ts
# either way, and only the role tells them apart - which is what makes the role
# assertion independent of the verdict rather than a second copy of it.
assert_eq "mv DEST last: src/main.ts is the destination" \
  "W | docs/notes.md :: source of mv (removed by the move) | src/main.ts :: destination of mv" \
  "$(wcand "mv docs/notes.md src/main.ts")"
assert_eq "AC-3 control: the same token is a SOURCE when it comes first" \
  "W | docs/notes.md :: destination of mv | src/main.ts :: source of mv (removed by the move)" \
  "$(wcand "mv src/main.ts docs/notes.md")"

# `mv a b DEST`: the final positional is created, the rest are REMOVED. That
# asymmetry with cp is why mv emits every operand - `mv f1 f2 d/` leaves neither
# f1 nor f2 where it was, while `cp g1 g2 e/` leaves both.
assert_eq "mv a b DEST: two sources and a destination" \
  "W | docs/a.md :: source of mv (removed by the move) | docs/b.md :: source of mv (removed by the move) | src/main.ts :: destination of mv" \
  "$(wcand "mv docs/a.md docs/b.md src/main.ts")"

# `mv X d/`.
assert_eq "mv X d/: a directory destination is still the last positional" \
  "W | docs/ :: destination of mv | src/main.ts :: source of mv (removed by the move)" \
  "$(wcand "mv src/main.ts docs/")"

# -t / --target-directory INVERTS which operand is the destination: DIR is the
# destination and EVERY positional is a source, whatever its position. All six
# spellings, because three of them glue or attach the argument, and a parser
# that merely SKIPS a `-` token whole leaves `mv -tsrc/ docs/notes.md` an
# entirely unjudged write into frozen source.
assert_eq "-t DIR separate" \
  "W | docs/notes.md :: source of mv (removed by the move) | src/ :: destination of mv" \
  "$(wcand "mv -t src/ docs/notes.md")"
assert_eq "-tDIR glued" \
  "W | docs/notes.md :: source of mv (removed by the move) | src/ :: destination of mv" \
  "$(wcand "mv -tsrc/ docs/notes.md")"
assert_eq "--target-directory DIR separate" \
  "W | docs/notes.md :: source of mv (removed by the move) | src/ :: destination of mv" \
  "$(wcand "mv --target-directory src/ docs/notes.md")"
assert_eq "--target-directory=DIR attached" \
  "W | docs/notes.md :: source of mv (removed by the move) | src/ :: destination of mv" \
  "$(wcand "mv --target-directory=src/ docs/notes.md")"
assert_eq "-ft DIR bundled" \
  "W | docs/notes.md :: source of mv (removed by the move) | src/ :: destination of mv" \
  "$(wcand "mv -ft src/ docs/notes.md")"
assert_eq "-ftDIR bundled and glued" \
  "W | docs/notes.md :: source of mv (removed by the move) | src/ :: destination of mv" \
  "$(wcand "mv -ftsrc/ docs/notes.md")"

# The control again, through the option rather than through position: these two
# tokens keep the same roles while SWAPPING position. A parser reading position
# only gets this exactly backwards and still blocks, which is why the verdict
# cannot be the thing under test.
assert_eq "-t: the positional is a source however late it appears" \
  "W | docs/ :: destination of mv | src/main.ts :: source of mv (removed by the move)" \
  "$(wcand "mv -t docs/ src/main.ts")"

# The option TOKEN itself must never become a candidate.
assert_eq "an option is not an operand" \
  "W | docs/a.md :: source of mv (removed by the move) | docs/b.md :: destination of mv" \
  "$(wcand "mv -f docs/a.md docs/b.md")"
assert_eq "-v is not an operand either" \
  "W | docs/a.md :: source of mv (removed by the move) | docs/b.md :: destination of mv" \
  "$(wcand "mv -v docs/a.md docs/b.md")"

# ---------------------------------------------------------------------------
describe "HARNESS-010 C-3 and PO-5: cp is NOT given mv's treatment"

# cp READS its sources and leaves them where they are, so only the destination
# is a write target. Judging every operand would be a false positive, not a fix.
assert_eq "cp judges the destination only" \
  "W | src/main.ts :: destination of cp" \
  "$(wcand "cp docs/notes.md src/main.ts")"
assert_eq "cp with three operands still judges only the last" \
  "W | src/main.ts :: destination of cp" \
  "$(wcand "cp docs/a.md docs/b.md src/main.ts")"

# `cp -t` is one of C-1's three BOTH WRONG rows: a real write into frozen source
# that both parsers permit, because the destination is behind the option and the
# parser names docs/notes.md instead. C-3 and PO-5 say it is a FINDING and not a
# criterion - widening the rule set inside a reconciliation makes it impossible
# to attribute a behaviour change to either cause. So this assertion pins the
# hole OPEN on purpose. Closing it should break this line and require a story.
assert_eq "C-3: cp -t stays unhandled, deliberately" \
  "W | docs/notes.md :: destination of cp" \
  "$(wcand "cp -t src/ docs/notes.md")"

# ---------------------------------------------------------------------------
describe "HARNESS-010: an option's ARGUMENT is not the file being written"

# The cross-run's xA half. manga-translator's parser emits every non-option
# token, so `touch -t 202601010000 docs/a.md` produced the TIMESTAMP as a
# candidate and `touch -r src/main.ts docs/a.md` produced a file `-r` only
# READS. A wrong denial naming a real path is the most convincing kind, and the
# reconciled parser must not inherit it.
assert_eq "touch -t: the timestamp is not a path" "W | docs/a.md" \
  "$(wcand "touch -t 202601010000 docs/a.md")"
assert_eq "touch -d: the date is not a path" "W | docs/a.md" \
  "$(wcand "touch -d 2026-01-01 docs/a.md")"
assert_eq "touch -r: the reference is only read" "W | docs/a.md" \
  "$(wcand "touch -r src/main.ts docs/a.md")"
assert_eq "touch --date: the long form too" "W | docs/a.md" \
  "$(wcand "touch --date 2026-01-01 docs/a.md")"
assert_eq "touch --reference: the long form too" "W | docs/a.md" \
  "$(wcand "touch --reference src/main.ts docs/a.md")"
assert_eq "touch --date=: an attached argument consumes no next word" "W | docs/a.md" \
  "$(wcand "touch --date=2026-01-01 docs/a.md")"

# And the control that keeps the skip honest: the file BEHIND the option is
# still judged. A rule skipping one word too many satisfies every assertion
# above and stops guarding anything.
assert_eq "the real target behind -t is still a target" "W | src/main.ts" \
  "$(wcand "touch -t 202601010000 src/main.ts")"
assert_eq "the real target behind -r is still a target" "W | src/main.ts" \
  "$(wcand "touch -r docs/notes.md src/main.ts")"

# rm, touch and tee take every remaining operand.
assert_eq "rm -f takes both operands" "W | src/a.ts | src/b.ts" \
  "$(wcand "rm -f src/a.ts src/b.ts")"
assert_eq "tee takes its operand" "W | src/main.ts" \
  "$(wcand "tee src/main.ts < docs/notes.md")"
assert_eq "tee -a takes its operand" "W | src/main.ts" \
  "$(wcand "tee -a src/main.ts < docs/notes.md")"

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-4: the verdict separates 'nothing to find' from 'found nothing'"

# AC-4 rests on this line. A command that NAMES a write-capable tool and yields
# no target is a different fact from a command that was never a write, and while
# the two were indistinguishable from outside a bypass stayed invisible: after
# it the log was empty, and after a permitted write the log was empty too.
assert_eq "operands arriving from a pipe are unknowable, but rm was named" "W" \
  "$(wcand "find src -name '*.ts' | xargs rm")"
assert_eq "an input redirect gives no operand either" "W" \
  "$(wcand "xargs touch < list")"

# The negative controls. Without these, "always print W" satisfies both lines
# above and AC-4's log becomes one entry per command.
assert_eq "a read-only cat is not write-capable"      "-" "$(wcand "cat src/main.ts")"
assert_eq "a read-only grep is not write-capable"     "-" "$(wcand "grep -rn export src/")"
assert_eq "a read-only git diff is not write-capable" "-" "$(wcand "git diff -- src/main.ts")"

# A redirect ALONE does not make a command write-capable: `cmd > /dev/null` is
# ubiquitous and its target is dropped on purpose, so tracing it would drown the
# log this trace exists to make readable. The candidate is still emitted - the
# verdict and the candidate list are separate answers.
assert_eq "a bare redirect emits a candidate but is not a write-capable command" \
  "- | /dev/null" "$(wcand "git diff > /dev/null")"
assert_eq "a redirect into docs is a candidate without a write-capable name" \
  "- | docs/notes.md" "$(wcand "echo x > docs/notes.md")"

# Prose in quoted data is one token and can never be a command name. Widening a
# character class does not buy this: `\bsed\b` matches the `sed` inside the
# unmasked token `sed-i`.
assert_eq "the harness's own vocabulary in a commit message is not a command" "-" \
  "$(wcand 'git commit -m "fix the sed -i extractor"')"

summary "lib"
