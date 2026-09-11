#!/usr/bin/env bash
# Regression suite for .claude/hooks/phase-guard.sh.
#
# Two halves, and the first is the one that matters:
#
#   * Commands that must NOT be blocked. A lock with false positives teaches
#     the agent that blocks are noise, which is precisely the instinct law 5
#     of CLAUDE.md exists to suppress. Every case here was a real block
#     observed in a real session, or is one quoting away from being one.
#   * Commands that MUST be blocked, asserted on the path the guard reports -
#     not merely on the fact that something was blocked. A guard that refuses
#     `sed -i 's|a|b|' src/main.ts` because it thinks the path is `s` is
#     right by accident and will be wrong the next time.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_fixture)"
trap 'rm -rf "$FIX"' EXIT

# ---------------------------------------------------------------------------
describe "RED: quoted arguments are not shell syntax"
set_phase "$FIX" RED

# A sed script whose delimiter is `|`. The command writes .gitignore (harness,
# allowed in RED); the sed script must not be mistaken for the target.
assert_allowed "$FIX" 'sed -i "s|^a/$|a/\nb/|" .gitignore' 'sed -i with | delimiter, writing harness'

# An arrow inside a quoted awk program is not a redirect. This one is a READ:
# the old extractor blocked a pipeline that wrote nothing at all.
assert_allowed "$FIX" "awk '/^## Handoff: RED -> GREEN/,/^## Gate results/' docs/notes.md" 'arrow inside a quoted awk program'

# An operator inside a quoted grep pattern, reading a source file in RED.
assert_allowed "$FIX" "grep -oE 'x>y' src/main.ts" 'operator inside a quoted grep pattern'

# An operator inside a commit message.
assert_allowed "$FIX" 'git commit -m "fix: a > b"' 'operator inside a commit message'

# Four more shapes, all observed blocking correct commands in one story. They
# are here because they are the ones a story actually reaches for while proving
# a test discriminates, and each was reported on a nonsense path - `0)`, `0`,
# `s`, `turnPx` - which is how a false positive teaches an agent to stop
# reading denials.
#
# A numeric comparison inside an awk program is not a redirect.
assert_allowed "$FIX" "awk 'BEGIN { while ((getline line < f) > 0) n++ }' src/main.ts" 'awk getline compared against 0'

# A docs append whose TEXT mentions the operator. The note recording the
# previous trip was itself blocked, on the path `0`.
assert_allowed "$FIX" "printf '%s\n' 'the > operator, in prose' >> docs/notes.md" 'prose quoting an operator, appended to docs'

# A word boundary in a grep pattern. Reads source; writes nothing.
assert_allowed "$FIX" "grep -n 'foo\\b' src/main.ts" 'word boundary in a grep pattern'

# A heredoc body is data, not shell. The only real target here is docs/notes.md.
assert_allowed "$FIX" 'cat > docs/notes.md <<'"'"'EOF'"'"'
to write it by hand: cat > src/main.ts
EOF' 'heredoc body containing a redirect'

# An escaped operator outside quotes is not an operator either.
assert_allowed "$FIX" 'echo "a \> b" > docs/notes.md' 'escaped redirect inside a string'

# Plain reads.
assert_allowed "$FIX" 'cat src/main.ts' 'reading source'
assert_allowed "$FIX" 'grep -rn "export" src/' 'grepping source'
assert_allowed "$FIX" 'git diff -- src/main.ts' 'diffing source'

# ---------------------------------------------------------------------------
describe "RED: real writes to source are still blocked"

assert_blocked "$FIX" 'echo x > src/main.ts'            src/main.ts 'redirect into source'
assert_blocked "$FIX" 'echo x >> src/main.ts'           src/main.ts 'append into source'
assert_blocked "$FIX" 'echo x | tee src/main.ts'        src/main.ts 'tee into source'
assert_blocked "$FIX" 'cp docs/notes.md src/main.ts'    src/main.ts 'cp onto source'
assert_blocked "$FIX" 'mv docs/notes.md src/main.ts'    src/main.ts 'mv onto source'
assert_blocked "$FIX" 'rm src/main.ts'                  src/main.ts 'rm source'
assert_blocked "$FIX" 'touch src/new.ts'                src/new.ts  'touch new source'

# The one the misparse was hiding: the target is the file, not the sed script.
assert_blocked "$FIX" "sed -i 's|a|b|' src/main.ts"     src/main.ts 'sed -i with | delimiter, writing source'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts"     src/main.ts 'sed -i with / delimiter, writing source'

# A quoted target keeps its spaces instead of being split into fragments.
assert_blocked "$FIX" 'echo x > "src/my file.ts"'       'src/my file.ts' 'quoted target containing a space'

assert_blocked "$FIX" 'echo x > src/main.ts' src/main.ts 'redirect into source (Bash)'
r="$(guard "$FIX" Write file_path src/main.ts)"
assert_contains "Write tool is blocked in RED" "category: source" "$r"
r="$(guard "$FIX" Edit file_path "$FIX/src/main.ts")"
assert_contains "Edit tool is blocked on an absolute path" "category: source" "$r"


# ---------------------------------------------------------------------------
describe "RED: a path in a variable is still a path"

# The loophole every agent found. The guard used to discard any candidate
# containing `$`, silently, so the ONE recipe the harness's own rules push an
# agent towards in RED - mutate the production file, watch the corrected test
# fail, revert - went through unchecked. Three source files were mutated this
# way in one corrective RED pass, on written instruction, because nothing else
# in the harness permitted touching them. The lock did not fail open here; it
# was open.
#
# An assignment in the same command is what the guard can see, so it is what it
# resolves. Anything else declines and says so in the log.
assert_blocked "$FIX" 'F=src/main.ts; sed -i '"'"'s/a/b/'"'"' "$F"'   src/main.ts 'sed -i on a path held in a variable'
assert_blocked "$FIX" 'F=src/main.ts; sed -i '"'"'s/a|b/c/'"'"' "$F"' src/main.ts 'the sed delimiter is not the target, even via a variable'
assert_blocked "$FIX" 'F=src/main.ts; sed -i '"'"'s/a;b/c/'"'"' "$F"' src/main.ts 'a semicolon inside the expression is not a separator'
assert_blocked "$FIX" 'OUT="src/main.ts"; echo x > "$OUT"'            src/main.ts 'redirect into a path held in a variable'
assert_blocked "$FIX" 'D=src; rm "$D/main.ts"'                        src/main.ts 'variable holding a directory'
assert_blocked "$FIX" 'F=src/main.ts; sed -i '"'"'s/a/b/'"'"' "${F}"' src/main.ts 'braced expansion'

# Not every `$` can be resolved: the guard reads one command string and has no
# access to the shell's environment. An unresolvable target is inconclusive,
# so it declines and logs the token - the same contract as any other parse the
# guard does not believe. It must not pretend to have checked it.
assert_allowed "$FIX" 'sed -i '"'"'s/a/b/'"'"' "$EXPORTED_ELSEWHERE"' 'a variable assigned in an earlier command'
rm -f "$FIX/.claude/state/phase-guard-declined.log"
guard_bash "$FIX" 'sed -i '"'"'s/a/b/'"'"' "$EXPORTED_ELSEWHERE"' >/dev/null
assert_contains "and the decline is logged with its token" 'EXPORTED_ELSEWHERE' \
  "$(cat "$FIX/.claude/state/phase-guard-declined.log" 2>/dev/null)"

# A longer name must not be eaten by a shorter one that prefixes it.
assert_blocked "$FIX" 'F=docs; FILE=src/main.ts; rm "$FILE"' src/main.ts 'the longest matching name wins'

# ---------------------------------------------------------------------------
describe "scripts/mutate.sh is the sanctioned way to mutate a frozen file"

# H14: the harness requires a diagnostic mutation of production source in RED
# (watch a corrected test fail against the behaviour it claims to pin) and in
# GREEN (verify a handoff's mutation table). mutate.sh backs the file up,
# applies the expression, runs a command, restores and verifies - so the file
# it names is not a write the lock has to care about, in any phase.
assert_allowed "$FIX" "bash scripts/mutate.sh src/main.ts 's/a/b/' -- true" 'mutate.sh naming a source file in RED'
assert_allowed "$FIX" "bash scripts/mutate.sh src/main.ts 's|a|b|' -- pnpm exec vitest run" 'mutate.sh with a | delimiter'

# The exemption is the FILE argument and nothing else. A payload that writes
# somewhere the phase forbids is judged like any other command: mutate.sh is not
# a phase escape hatch with a `--` in front of it.
#
# It is not a sandbox either, and the boundary is the same one the guard has
# everywhere else: what is inside `sh -c '...'` is a quoted string, so it is
# data, and the guard does not read it - with or without mutate.sh in front. That
# fails open by design; mutate.sh adds no hole that a bare `sh -c` did not
# already have.
set_phase "$FIX" GREEN
assert_blocked "$FIX" "bash scripts/mutate.sh src/main.ts 's/a/b/' -- cp docs/notes.md tests/main.test.ts" \
  tests/main.test.ts 'a payload writing a frozen test is still blocked'
assert_allowed "$FIX" "bash scripts/mutate.sh src/main.ts 's/a/b/' -- cp docs/notes.md src/other.ts" \
  'a payload writing source in GREEN is allowed, like any other'
set_phase "$FIX" RED

# ---------------------------------------------------------------------------
describe "RED: the seven false positives reported from the field"
set_phase "$FIX" RED

# Every one of these was blocked in a single real story, across three agents.
# Three of them contain the harness's OWN phase vocabulary, which is exactly
# what the loop asks agents to grep for; a lock that fires on its own idiom is
# the fastest way to teach agents that blocks are noise.
assert_allowed "$FIX" "sed -n '/## Handoff: RED -> GREEN/,/## Gate results/p' docs/notes.md" \
  'sed -n over a phase-named range'
assert_allowed "$FIX" 'grep -n "GATES -> REVIEW" -A 6 docs/notes.md' \
  'grep for a phase transition'
assert_allowed "$FIX" "awk 'NR>=55 && NR<=80' docs/notes.md" \
  'awk line range with >='
assert_allowed "$FIX" 'cat > docs/notes.md <<'"'"'EOF'"'"'
s = (Math.imul(s, 1664525) + 1013904223) >>> 0
EOF' 'heredoc containing a shift operator'
assert_allowed "$FIX" 'cat > docs/notes.md <<'"'"'EOF'"'"'
// a vertex of degree >= 3
EOF' 'heredoc containing a comparison in a comment'
assert_allowed "$FIX" 'cat > docs/notes.md <<'"'"'EOF'"'"'
const kept = adjacency.filter((path) => !isDeferred(path))
EOF' 'heredoc containing an arrow function'
assert_allowed "$FIX" 'cd /tmp/harness-scratch-xyz && rm -rf gate-logs' \
  'rm of a relative path after cd out of the repo'

# ---------------------------------------------------------------------------
describe "RED: four more false positives, all of them read-only commands"
set_phase "$FIX" RED

# A second field report, a second story, four more denials - and every one of
# these commands only READ. The running total is eleven, which is the reason
# the guard now declines a parse it cannot believe instead of denying on it.
assert_allowed "$FIX" 'node --input-type=module <<'"'"'JS'"'"'
const p = process.argv[2]
console.log(p.length > 3)
JS' 'a heredoc-fed interpreter with no redirect anywhere in it'
assert_allowed "$FIX" 'grep -oE "> [^>]+ [0-9]+ms$" docs/notes.md' \
  'a grep pattern containing a redirect and a bracket expression'
assert_allowed "$FIX" 'grep -o "class=\"strong\">[^<]*" docs/notes.md' \
  'a grep pattern with an embedded double quote'

# The self-referential one: a heredoc writing a DOCS file was blocked because
# the prose inside it quoted the character the guard reads as a redirect. The
# guard classified a docs write as `source` on the strength of the file's own
# contents - while that file was documenting this very bug.
assert_allowed "$FIX" 'cat >> docs/notes.md <<'"'"'MARKDOWN'"'"'
The guard reported `path: >` for a command with no redirect in it.
Prose that quotes `>` or `>>` is data, not syntax.
MARKDOWN' 'a docs heredoc whose prose quotes the redirect character'


# ---------------------------------------------------------------------------
describe "A read-only command with no write in it, in any phase"
set_phase "$FIX" RED

# Two more field reports, and a kind no earlier case covers: every shape above
# was at least a command that wrote SOMETHING somewhere, so a guard that
# guessed the wrong target was still refusing a write. These write nothing
# under any parse. `node -e` counting characters in a file was refused on a
# path of `1`; an arrow function on a path of `n`; an awk program printing a
# string containing the operator on a path of `b`. The guard was not choosing
# the wrong target - it was inventing one.
assert_allowed "$FIX" "node -e 'console.log([1,2].filter(function(n){ return n > 1 }))'" \
  'a numeric comparison inside node -e'
assert_allowed "$FIX" "node -e 'console.log([1,2].filter(n => n === 1))'" \
  'an arrow function inside node -e'
assert_allowed "$FIX" "awk 'BEGIN{ print \"a>b\" }'" \
  'the operator inside a printed string literal'
assert_allowed "$FIX" "node -e 'console.log([\"x\"].filter(c => !(c.codePointAt(0) > 127)))'" \
  'an arrow function whose body negates a comparison'
assert_allowed "$FIX" "awk 'FNR>=791' docs/notes.md" \
  'a comparison operator inside an awk pattern'

# And the reason this block does not live under a phase heading. The bogus
# token falls through paths.conf to the fallback category, which is `source`,
# which every phase but SCAFFOLD freezes - so the defect is phase-independent
# and these fired in REVIEW, where a story is only meant to be answering
# review comments. A suite that only ever asserted in RED would have called
# this fixed while it still refused the same commands three phases later.
set_phase "$FIX" REVIEW
assert_allowed "$FIX" "node -e 'console.log([1,2].filter(function(n){ return n > 1 }))'" \
  'a numeric comparison inside node -e, in REVIEW'
assert_allowed "$FIX" "node -e 'console.log([1,2].filter(n => n === 1))'" \
  'an arrow function inside node -e, in REVIEW'
assert_allowed "$FIX" "awk 'BEGIN{ print \"a>b\" }'" \
  'the operator inside a printed string literal, in REVIEW'

# The easy wrong fix for all of the above is a scanner that gives up on any
# command it finds hard, which deletes the protection the guard exists for.
# These two pin what must survive it: a plain redirect, and - because case 4
# of the field report is "a heredoc BODY is data" - a real redirect on a line
# that also opens a heredoc. Meeting the heredoc rule by skipping heredoc
# commands wholesale fails here.
set_phase "$FIX" RED
assert_blocked "$FIX" 'echo x > src/main.ts' src/main.ts \
  'a plain redirect is still a write'
assert_blocked "$FIX" 'cat > src/main.ts <<'"'"'EOF'"'"'
export const x = 2
EOF' src/main.ts 'a real redirect on the same line as a heredoc'
# ---------------------------------------------------------------------------
describe "RED: the harness's own vocabulary in a commit message"
set_phase "$FIX" RED

# Third field report. A consuming project fixed the GATES -> REVIEW ordering in
# /advance-story, then wrote a commit message saying so - and the vendored
# guard read the arrow as a redirect into a file named REVIEW, classified it
# as source, and refused the commit. The message documenting the arrow-ordering
# fix was blocked by the arrow-parsing bug. Every story here names its handoff
# `RED -> GREEN` and every phase change is an arrow, so a commit message is
# not an unlucky input: it is the input.
assert_allowed "$FIX" 'git commit -m "WORLD-006: set the phase before committing at GATES -> REVIEW"' \
  'a commit message naming a phase transition'
assert_allowed "$FIX" 'git commit -am "advance-story: RED -> GREEN handoff must carry control values"' \
  'a commit message naming the handoff section'
assert_allowed "$FIX" 'git commit -F - <<'"'"'MSG'"'"'
Reorder GATES -> REVIEW

check-boundaries.sh reads the phase out of the committed frontmatter, so
`phase.sh set <id> REVIEW` has to run before the commit, not after it.
MSG' 'a multi-line commit message fed by heredoc'
assert_allowed "$FIX" 'git commit -m "$(printf "%s\n\n%s" "Fix GATES -> REVIEW" "Set the phase first.")"' \
  'a commit message built by command substitution'

# And the same words are still an operator when they are one.
assert_blocked "$FIX" 'echo "GATES -> REVIEW" > src/main.ts' src/main.ts \
  'the vocabulary quoted, the redirect not'

# ---------------------------------------------------------------------------
describe "RED: a double-quoted Windows path keeps its backslashes"
set_phase "$FIX" RED

# The scratchpad this harness tells agents to use is
# C:\Users\<you>\AppData\Local\Temp\claude\..., and an agent quotes it. The
# masker ate the backslashes, to_rel could not place the result outside the
# repository, and the guard denied a write to the scratchpad as `source`.
# Observed on a Windows machine during an audit of this very repository.
assert_allowed "$FIX" 'echo x > "C:\Users\ryanc\AppData\Local\Temp\claude\n.txt"' \
  'a double-quoted Windows path outside the repository'
assert_allowed "$FIX" 'cd "C:\Users\ryanc\AppData\Local\Temp\claude" && rm -rf x' \
  'cd into a double-quoted Windows path, then rm'
# And the same spelling INSIDE the repository is judged on the real path,
# not on a string with the separators removed.
FIXBS="$(printf '%s' "$FIX" | tr '/' '\134')"
assert_blocked "$FIX" "echo x > \"$FIXBS\\src\\main.ts\"" src/main.ts \
  'a double-quoted backslash path inside the repository'

# ---------------------------------------------------------------------------
describe "RED: three holes found by probing, closed"
set_phase "$FIX" RED

# A subshell's closing paren was glued onto the target, `a.ts)`, which the
# guard then declined as implausible. Declining is for tokens it cannot read;
# this one it could, once the paren is treated as the terminator it is.
assert_blocked "$FIX" '(cd src && echo x > a.ts)'      src/a.ts 'redirect inside a subshell'
assert_blocked "$FIX" 'cd src && (echo x > a.ts)'      src/a.ts 'subshell after a cd'
assert_blocked "$FIX" '(echo x > src/main.ts)'         src/main.ts 'parenthesised redirect'
# An apostrophe in a comment opened a quote that never closed, and masked a
# real redirect on the following line.
assert_blocked "$FIX" "$(printf 'echo hi # it%ss fine\necho x > src/main.ts' "'")" \
  src/main.ts 'a redirect after a commented apostrophe'
# The clobber form.
assert_blocked "$FIX" 'echo x >| src/main.ts'          src/main.ts 'clobber redirect'
# And a false positive from the same probe: an input redirect is a READ.
assert_allowed "$FIX" 'xargs touch < list'             'touch fed by an input redirect'

# ---------------------------------------------------------------------------
describe "RED: a parse the guard cannot believe declines rather than denies"
set_phase "$FIX" RED

# Backticks are not masked - the masker knows quotes and heredocs, not command
# substitution - so this extracts the token `\`mktemp\``, which has no
# extension and therefore classified as source and blocked. It names no file in
# this repository and the guard now says so by allowing it.
assert_allowed "$FIX" 'printf x > `mktemp`' 'a target the parse could not resolve'

# Fail-open has a floor: it applies to what the guard cannot read, never to
# what it can.
assert_blocked "$FIX" 'printf x > src/main.ts' src/main.ts 'a target it can read is still judged'

# ---------------------------------------------------------------------------
describe "RED: relative paths resolve against the command's own cwd"

# Out of the repo: nothing relative afterwards is a repo path.
assert_allowed "$FIX" 'cd /tmp/harness-scratch-xyz && echo x > main.ts' 'redirect after cd outside'
assert_allowed "$FIX" 'cd /tmp/scratch; touch src/main.ts'              'touch after cd outside'
assert_allowed "$FIX" 'cd "$TMPDIR" && rm -rf src'                      'cd to a variable is unaccountable'
assert_allowed "$FIX" 'cd - && rm -rf src'                              'cd - is unaccountable'
assert_allowed "$FIX" 'cd && rm -rf src'                                'bare cd goes home'
assert_allowed "$FIX" 'cd ~/scratch && rm -rf src'                      'cd into home is unaccountable'
assert_allowed "$FIX" 'cd .. && rm -rf src'              'cd above the repo root'
assert_allowed "$FIX" 'cd src/../.. && touch main.ts'    'a relative cd that climbs out'

# Still in the repo: the cwd makes the guard SHARPER, not looser. Measured
# against the root, `main.ts` is a path the classifier has never heard of;
# measured against src/, it is the source file the shell will really write.
assert_blocked "$FIX" 'cd src && echo x > main.ts'        src/main.ts 'redirect after cd into src'
assert_blocked "$FIX" 'cd ./src && touch new.ts'          src/new.ts  'touch after cd into ./src'
assert_blocked "$FIX" 'cd docs && rm ../src/main.ts'      src/main.ts 'relative path climbing back to source'
assert_blocked "$FIX" 'cd src && cd ../docs && cd ../src && rm main.ts' src/main.ts 'cd walked back and forth'

# An absolute path is unaffected by any of it.
assert_blocked "$FIX" "cd /tmp/scratch && rm $FIX/src/main.ts" src/main.ts 'absolute target after cd outside'

# A quoted directory name is still a directory name; the quote marks must not
# survive into the resolved path.
assert_blocked "$FIX" 'cd "src" && rm main.ts'      src/main.ts 'cd into a double-quoted directory'
assert_blocked "$FIX" "cd 'src' && rm main.ts"      src/main.ts 'cd into a single-quoted directory'
assert_allowed "$FIX" 'cd "/tmp/scratch" && rm -rf gate-logs' 'cd into a quoted path outside the repo'

# ---------------------------------------------------------------------------
describe "GREEN: tests are frozen, source is not"
set_phase "$FIX" GREEN

assert_allowed "$FIX" 'echo x > src/main.ts' 'writing source in GREEN'
assert_blocked "$FIX" 'echo x > tests/main.test.ts' tests/main.test.ts 'writing a test in GREEN'
r="$(guard "$FIX" Write file_path tests/main.test.ts)"
assert_contains "Write to a test is blocked in GREEN" "category: test" "$r"

# ---------------------------------------------------------------------------
describe "Generated output is not source"
set_phase "$FIX" RED

# Ignored by the fixture's .gitignore, so not authored, so not the lock's
# business - in any phase.
assert_allowed "$FIX" 'rm -rf .vitest'           'rm an ignored tool directory'
assert_allowed "$FIX" 'rm -rf playwright-report' 'rm an ignored report directory'
assert_allowed "$FIX" 'rm -rf node_modules'      'rm a vendor directory'
assert_allowed "$FIX" 'rm -rf dist'              'rm a build directory'

# An ignored path that does not exist yet still classifies from the rules.
assert_allowed "$FIX" 'echo x > .vitest/log.txt' 'writing inside an ignored directory'

# A TRACKED file is never "ignored", even if a rule would otherwise match it:
# git check-ignore consults the index, and so this stays source.
assert_blocked "$FIX" 'echo x > src/main.ts' src/main.ts 'tracked source is still source'

# ---------------------------------------------------------------------------
describe "No active story means no lock"
set_phase "$FIX" ""

assert_allowed "$FIX" 'echo x > src/main.ts' 'writing source with no story'
r="$(guard "$FIX" Write file_path src/main.ts)"
assert_eq "Write tool with no story" "" "$r"

summary "phase-guard"
