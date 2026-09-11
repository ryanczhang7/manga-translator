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
  "package.json=config" \
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

# ---------------------------------------------------------------------------
describe "mask_shell_quotes: operators inside quotes stop being operators"

mask() { printf '%s' "$1" | mask_shell_quotes; }
roundtrip() { printf '%s' "$1" | mask_shell_quotes | unmask_shell_quotes; }

# What the masker is for: no operator survives inside a quoted span.
has_operator() { printf '%s' "$1" | grep -qE '[|&;<>]'; }

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
if printf '%s' "$hd" | grep -q '> src/main.ts'; then
  _bad "a heredoc body is masked" "the body's redirect survived: $hd"
else
  _ok "a heredoc body is masked"
fi

assert_eq "an escaped operator is masked" "0" \
  "$(mask 'echo a \> b' | grep -cE '>')"

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
HARNESS_ROOT="$FIX"
mkdir -p "$FIX/.claude/commands" "$FIX/.claude/hooks"
printf '# advance\n' > "$FIX/.claude/commands/advance-story.md"
printf 'x() { :; }\n' > "$FIX/.claude/hooks/lib.sh"
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

summary "lib"
