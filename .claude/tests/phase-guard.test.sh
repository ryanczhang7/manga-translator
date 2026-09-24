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

# ===========================================================================
# MT-031: the extractors must read an OPERAND, not the last word.
#
# Two defects in the five extractors at .claude/hooks/phase-guard.sh:91-95,
# with five measured symptoms - two false positives and THREE bypasses that let
# a write to a frozen source file through during RED:
#
#   (a) a command NAME matches inside a masked span, so prose in a quoted
#       argument or a heredoc body is read as an invocation;
#   (b) `awk '{print $NF}'` takes the LAST WORD of the match - which is the
#       redirect target when the command has a trailing redirect, and a
#       fragment of the sed script when the match is truncated by `(`.
#
# Every assertion below names the reported PATH, never merely "it was blocked":
# a guard that refuses `sed -i 's|a|b|' src/main.ts` because it thinks the path
# is `s` is right by accident, and that accident is the defect.
# ===========================================================================

# ---------------------------------------------------------------------------
describe "MT-031 AC-1: prose in quoted data is not a command invocation"
set_phase "$FIX" RED

# The A/B pair from the field report: two `--dry-run --allow-empty` commits
# differing only in whether the message mentions the in-place editor. NEITHER
# WRITES ANYTHING, in any phase. Variant A is allowed today; variant B blocks
# on `path: sed -i hard-BLOCKED with its own expression reported as the`.
#
# The cases below deliberately do NOT reuse that one sentence. The contract
# being restored is CLAUDE.md's "quoted arguments and heredoc bodies are data,
# not syntax", and a fix that special-cases an observed phrase satisfies a
# single-sentence test while leaving the contract false. So: arbitrary prose,
# several unrelated sentences, and every one of the six command names.
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -F - <<'"'"'EOF'"'"'
a real in-place edit hard-BLOCKED with its own expression reported as the
EOF' 'variant A: the same shape, without the phrase'

assert_allowed "$FIX" 'git commit --dry-run --allow-empty -F - <<'"'"'EOF'"'"'
Never reach for sed -i on a file the phase has frozen.
EOF' 'heredoc prose naming the in-place flag'

assert_allowed "$FIX" 'git commit --dry-run --allow-empty -F - <<'"'"'EOF'"'"'
The reviewer asked why sed -i was mentioned in the handoff at all.
A second paragraph, so the body is more than one line.
EOF' 'a two-paragraph heredoc naming the in-place flag'

assert_allowed "$FIX" 'git commit --dry-run --allow-empty -m "do not reach for sed -i here"' \
  'a quoted argument naming the in-place flag'

# Defect (a) with NO mask character inside the match, so it cannot be fixed by
# widening a character class alone: `\bsed\b` matches the `sed` in `sed-i`, and
# `$NF` then reports a fragment of an English sentence as the path. Blocked
# today on `sed-i` and on `sed-i, ever`.
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -m "sed-i"' \
  'a hyphenated mention with no whitespace to mask'
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -m "never sed-i, ever"' \
  'a hyphenated mention inside a sentence'

# The other five command names, in prose. These are ALLOWED TODAY - the
# `tee`, `cp|mv` and `rm|touch` extractors require `[[:space:]]+` after the
# name, and a masked space is \006, which is not [[:space:]]. They are
# regression guards on a rewrite that replaces those classes, and they are
# earned by the mutation in DV-5.
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -F - <<'"'"'EOF'"'"'
We should cp the audit notes into the wiki before review.
EOF' 'heredoc prose naming cp'
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -F - <<'"'"'EOF'"'"'
Do not rm the gate logs while a story is open.
EOF' 'heredoc prose naming rm'
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -F - <<'"'"'EOF'"'"'
The plan was to mv the fixture helpers into a shared file.
EOF' 'heredoc prose naming mv'
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -F - <<'"'"'EOF'"'"'
Nothing in this change should touch the frozen tests at all.
EOF' 'heredoc prose naming touch'
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -F - <<'"'"'EOF'"'"'
We tee the gate output so the log survives a crash.
EOF' 'heredoc prose naming tee'
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -m "we cp docs into the wiki by hand"' \
  'a quoted argument naming cp'

# ---------------------------------------------------------------------------
describe "MT-031 AC-1b: the same defect through a write the phase PERMITS"
set_phase "$FIX" RED

# docs is writable in RED, so this command is entirely legitimate. Today it is
# hard-BLOCKED on `path: sed -i expression as the path argument. False
# positive, so` with `category: source`.
#
# BOTH halves are required. The softer exit of this defect is a decline, and a
# fix that turns the block into a decline has moved the noise rather than
# removed it - so the decline log must stay empty too.
rm -f "$FIX/.claude/state/phase-guard-declined.log"
assert_allowed "$FIX" 'cat >> docs/notes.md <<'"'"'EOF'"'"'
The guard took the sed -i expression as the path argument. False positive, so
it declined and logged it.
EOF' 'a permitted docs append whose prose names the in-place flag'
assert_eq "and nothing is appended to the decline log" "" \
  "$(cat "$FIX/.claude/state/phase-guard-declined.log" 2>/dev/null)"

# ---------------------------------------------------------------------------
describe "MT-031 AC-2 and C-3: a real in-place edit is blocked on its operand"
set_phase "$FIX" RED

# ALL OF THESE PASS TODAY (regression guards, earned by DV-1). They are the
# criterion that stops AC-1 being satisfied by deleting the `sed -i` heuristic:
# delete it and every assertion in this block goes red.
#
# The option spellings are C-3's pin, checked against real sed: with a bare
# script argument the files are every positional after it; with -e, --expression
# or -f there is no positional script, so every positional is a file.
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts"          src/main.ts 'sed -i on frozen source'
assert_blocked "$FIX" "sed -i.bak 's/a/b/' src/main.ts"      src/main.ts 'sed -i.bak on frozen source'
assert_blocked "$FIX" "sed --in-place 's/a/b/' src/main.ts"  src/main.ts 'sed --in-place on frozen source'
assert_blocked "$FIX" "sed -i -e 's/a/b/' src/main.ts"       src/main.ts 'sed -i -e EXPR'
assert_blocked "$FIX" 'sed -i --expression=s/a/b/ src/main.ts' src/main.ts 'sed -i --expression=EXPR'
assert_blocked "$FIX" 'sed -i -f script.sed src/main.ts'     src/main.ts 'sed -i -f SCRIPTFILE'

# C-3: EVERY operand, not the last one. `sed -i EXPR a b` writes both a and b -
# measured against real sed - so a frozen operand followed by a permitted one
# is a fourth bypass, and it is not in the story's symptom list: today
# `sed -i 's/a/b/' src/main.ts docs/notes.md` is ALLOWED, because `$NF` is the
# permitted file. The reverse order blocks, which is how it stayed hidden.
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts docs/notes.md" src/main.ts \
  'a frozen operand followed by a permitted one'
assert_blocked "$FIX" "sed -i 's/a/b/' docs/notes.md src/main.ts" src/main.ts \
  'a permitted operand followed by a frozen one'
assert_blocked "$FIX" "sed -i -e 's/a/b/' src/main.ts docs/notes.md" src/main.ts \
  'the -e form, frozen operand first'
assert_blocked "$FIX" 'rm src/main.ts docs/notes.md' src/main.ts \
  'rm with a frozen operand followed by a permitted one'

# ---------------------------------------------------------------------------
describe "MT-031 C-3: cp and mv judge the destination, not every operand"
set_phase "$FIX" RED

# ALL OF THESE PASS TODAY (regression guards, earned by re-running DV-4's M2 -
# see `## Regressions` R-1). They exist because the block above pins the
# OPPOSITE rule for `sed` and `rm` - every operand - and nothing pinned this
# half: `cp a b c` copies a AND b into c, so `b` is a READ and only the last
# argument is written. C-3's table says so, PO-11 measured it and told GREEN
# not to "fix" it, and GREEN's own scepticism list repeats it - three claims,
# zero assertions. Every cp/mv case in this suite had exactly two operands, so
# a guard that judged EVERY cp operand passed the whole suite untouched: at
# GATES the mutation `361s/lastop()/allops()/` on .claude/hooks/lib.sh, which
# is exactly that change, reddened 0 assertions where 1 was predicted. The
# `assert_allowed` case below is what it has to catch now (there were two; the
# `mv` one was corrected by MT-033 - see below).
#
# The trap being closed is a precision failure, not a strictness one. MT-031
# exists to make the guard precise; `cp a b c` is the one place the fix
# deliberately declines to block, and an unpinned precision claim is what the
# next rewrite breaks silently.
assert_allowed "$FIX" 'cp docs/notes.md src/main.ts docs/other.md' \
  'cp with three arguments: the frozen file in the middle is a READ'
# CORRECTED IN MT-033 RED, 2026-09-14 (MT-033 PO-1 / AC-5). This asserted
# ALLOWED, and that was wrong about the world: `mv f1 f2 d/` REMOVES both f1
# and f2, so the frozen file in the middle of an `mv` is destroyed, not read.
# Measured, GNU coreutils 8.32, 2026-09-14 - and `cp g1 g2 e/` removes neither,
# which is why the `cp` line above is unchanged and still correct. MT-031
# measured the `cp` half (its R-1 is explicit about `cp a b c`) and extended the
# rule to `mv` by symmetry without measuring `mv`. See MT-033 `## Regressions`.
# This is the ONLY MT-031 assertion MT-033 is authorised to change.
assert_blocked "$FIX" 'mv docs/notes.md src/main.ts docs/other.md' src/main.ts \
  'mv with three arguments: the frozen file in the middle is REMOVED by the move'

# The controls, aimed at the other way the two cases above could pass: the
# guard having stopped looking at cp/mv altogether, which would make them
# allowed for no reason at all. Two operands must still block on the
# destination, and so must three when the destination is the frozen one - so
# what is pinned is the POSITION of the operand, not the mere presence of a
# frozen path somewhere in the command.
assert_blocked "$FIX" 'cp docs/notes.md src/main.ts'               src/main.ts \
  'control: two-operand cp onto frozen source still blocks'
assert_blocked "$FIX" 'mv docs/notes.md src/main.ts'               src/main.ts \
  'control: two-operand mv onto frozen source still blocks'
assert_blocked "$FIX" 'cp docs/notes.md docs/other.md src/main.ts' src/main.ts \
  'control: three-operand cp whose DESTINATION is frozen still blocks'
assert_blocked "$FIX" 'mv docs/notes.md docs/other.md src/main.ts' src/main.ts \
  'control: three-operand mv whose DESTINATION is frozen still blocks'

# ---------------------------------------------------------------------------
describe "MT-031 AC-3: a metacharacter in the expression changes nothing"
set_phase "$FIX" RED

# The first five pass today. `(` `)` reports `s` - right by accident, on a
# fragment of the script - and `!` together with `(` `)` is ALLOWED OUTRIGHT,
# which is the plainest of the three bypasses: no redirect, no variable, just
# a capture group, which is the most ordinary thing a sed script contains.
assert_blocked "$FIX" "sed -i 's|a|b|' src/main.ts"             src/main.ts 'a pipe in the expression'
assert_blocked "$FIX" "sed -i 's/a/b&c/' src/main.ts"           src/main.ts 'an ampersand in the replacement'
assert_blocked "$FIX" "sed -i 's/a;b/c/' src/main.ts"           src/main.ts 'a semicolon in the expression'
assert_blocked "$FIX" "sed -i 's/a<b>c/d/' src/main.ts"         src/main.ts 'angle brackets in the expression'
assert_blocked "$FIX" "sed -i '/x/!s/a/b/' src/main.ts"         src/main.ts 'a negated address'
assert_blocked "$FIX" "sed -i 's/\\(a\\)/b/' src/main.ts"         src/main.ts 'a capture group'
assert_blocked "$FIX" "sed -i '/x/!s/\\(a\\)/b/' src/main.ts"     src/main.ts 'a negated address AND a capture group'
assert_blocked "$FIX" "sed -i '/x/!s/\\(a\\)|b;c<d>e&f/g/' src/main.ts" src/main.ts 'every one of them at once'

# The same defect seen from the false-positive side: a capture group in an
# expression against a path the phase PERMITS. Today this is blocked on `s`,
# so a legitimate docs edit is refused as `source`.
assert_allowed "$FIX" "sed -i 's/\\(a\\)/b/' docs/notes.md" \
  'a capture group in an expression writing docs'

# ---------------------------------------------------------------------------
describe "MT-031 AC-4: a target outside the repository root is nobody's business"
set_phase "$FIX" RED

# ALL FOUR PASS TODAY (regression guards, earned by DV-2). The scratchpad this
# harness tells agents to use is outside the tree, and a probe script written
# there is not the lock's business in any phase.
assert_allowed "$FIX" "sed -i 's/a/b/' /tmp/claude/scratch/sib.py" \
  'an MSYS absolute path outside the repository'
assert_allowed "$FIX" "sed -i 's/a/b/' 'C:/Users/x/AppData/Local/Temp/claude/sib.py'" \
  'a quoted C:/ path outside the repository'
assert_allowed "$FIX" 'sed -i '"'"'s/a/b/'"'"' "C:\Users\x\AppData\Local\Temp\claude\sib.py"' \
  'a double-quoted C:\ path outside the repository'
# `.py`, not `.md`: `../outside.md` classifies as `docs`, so it is permitted for
# a second reason and the case asserts nothing about being outside the tree.
# DV-2b found that by failing to redden it.
assert_allowed "$FIX" "sed -i 's/a/b/' ../outside.py" \
  'a relative climb out of the tree'

# ---------------------------------------------------------------------------
describe "MT-031 AC-5: Symptom B, reproduced - the expression is scanned, not the operand"
set_phase "$FIX" RED

# Filed as "observed once, does not currently reproduce" after ten variants.
# It reproduces deterministically against this fixture, in RED and in PLANNED
# alike, on the verbatim expression from the field report - which answers the
# story's open question: the active PHASE does not interact with candidate
# extraction at all.
#
# The trigger is Symptom D's, not a fourth mechanism: `(` in `min(` terminates
# the extractor's character class INSIDE the script, `$NF` returns the
# truncated fragment `s|        if a.ndim == 4 and min` - one field, because
# the spaces inside the quotes are masked - and that fragment carries an
# alphanumeric and no paren, so path_is_implausible believes it and the guard
# blocks on it.
B_EXPR="sed -i 's|        if a.ndim == 4 and min(a.shape[1], a.shape[3]) <= 8 ...|...|'"
assert_allowed "$FIX" "$B_EXPR /tmp/claude/scratch/sib.py" \
  'the field report verbatim, against a scratchpad path'
assert_blocked "$FIX" "$B_EXPR src/main.ts" src/main.ts \
  'the same expression against a frozen source file'

# ---------------------------------------------------------------------------
describe "MT-031 AC-6: a trailing redirect does not hide the operand"
set_phase "$FIX" RED

# The bypass. Two commands differing by one space: the control blocks, and
# `> /dev/null` is ALLOWED - the guard sees nothing, and a real source file in
# place of the probe's nonexistent one would have been edited during RED.
#
# The unspaced and `2>` forms block TODAY, but on the redirect rather than the
# file, so they must fail here on the reported path - a fix that preserves the
# accident while leaving the hole open does not pass. And the last two rows
# redirect to a path the phase PERMITS, which is a more ordinary thing to write
# than /dev/null and bypasses the guard identically: special-casing /dev/null
# closes nothing.
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts"                 src/main.ts 'control: no redirect'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts > /dev/null"     src/main.ts 'a spaced redirect to /dev/null'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts >/dev/null"      src/main.ts 'an unspaced redirect to /dev/null'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts 2>/dev/null"     src/main.ts 'a stderr redirect'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts > docs/log.txt"  src/main.ts 'a redirect to a path the phase permits'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts >> docs/log.txt" src/main.ts 'an appending redirect to a permitted path'

# ---------------------------------------------------------------------------
describe "MT-031 AC-7: every write-capable extractor, not only sed"
set_phase "$FIX" RED

# Three fail today and three pass. All six stay here: a rewrite of the
# extractor block is exactly what breaks the three that work, and the three
# that work are earned by the mutations in DV-3.
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts > /dev/null" src/main.ts 'sed -i with a trailing redirect'
assert_blocked "$FIX" 'cp docs/notes.md src/main.ts > /dev/null' src/main.ts 'cp with a trailing redirect'
assert_blocked "$FIX" 'mv docs/notes.md src/main.ts > /dev/null' src/main.ts 'mv with a trailing redirect'
assert_blocked "$FIX" 'rm src/main.ts > /dev/null'               src/main.ts 'rm with a trailing redirect'
assert_blocked "$FIX" 'touch src/new.ts > /dev/null'             src/new.ts  'touch with a trailing redirect'
assert_blocked "$FIX" 'echo x | tee src/main.ts > /dev/null'     src/main.ts 'tee with a trailing redirect'

# And the same six against a redirect the phase permits, so that no fix can
# pass this block by filtering /dev/null.
assert_blocked "$FIX" 'cp docs/notes.md src/main.ts > docs/log.txt' src/main.ts 'cp with a redirect to a permitted path'
assert_blocked "$FIX" 'mv docs/notes.md src/main.ts > docs/log.txt' src/main.ts 'mv with a redirect to a permitted path'
assert_blocked "$FIX" 'rm src/main.ts >> docs/log.txt'              src/main.ts 'rm with an appending redirect'

# tee's immunity comes from `[[:space:]]` in its terminating class, not from the
# `>` the class also excludes - so the unspaced form is where that `>` earns its
# place. Both pass today; DV-3(ii) and DV-3(iii) are aimed at exactly these two.
assert_blocked "$FIX" 'echo x | tee src/main.ts>/dev/null'    src/main.ts 'tee with an unspaced redirect'
assert_blocked "$FIX" 'echo x | tee -a src/main.ts>/dev/null' src/main.ts 'tee -a with an unspaced redirect'

# ---------------------------------------------------------------------------
describe "MT-031 AC-8: a zero-candidate write leaves a trace"
set_phase "$FIX" RED

# What made Symptom C invisible: after the bypass the decline log was empty,
# and after a permitted `echo x > docs/notes.md` it was also empty. The two
# outcomes - "the extractors found nothing to judge" and "they found candidates
# and every one was permitted" - were indistinguishable from outside.
#
# The discrimination this suite demands, and the shape RED chose for it (C-4,
# amended): a single line in .claude/state/phase-guard-declined.log carrying
# the marker `no-candidate`, the story, the phase and enough of the command to
# act on - and logged ONLY when one of the six write-capable command names
# appears at a real token boundary and no candidate survived. A redirect
# operator alone does not trigger it, because `cmd > /dev/null` is ubiquitous
# and its target is filtered on purpose; `git diff > /dev/null` must stay
# silent.
MT031_LOG="$FIX/.claude/state/phase-guard-declined.log"
mt031_log_of() { rm -f "$MT031_LOG"; guard_bash "$FIX" "$1" >/dev/null; cat "$MT031_LOG" 2>/dev/null; }

# POSITIVE. A write command whose operands the guard cannot see: `rm` at a real
# token boundary, no operand in the command string at all, zero candidates,
# ALLOWED - and it would delete source in RED. The operand parse cannot close
# this one, which is the whole reason a trace is wanted.
assert_allowed "$FIX" "find src -name '*.ts' | xargs rm" 'operands arriving from a pipe are unknowable'
mt031_l="$(mt031_log_of "find src -name '*.ts' | xargs rm")"
assert_contains "a write command with no visible operand is traced" 'no-candidate' "$mt031_l"
assert_contains "the trace names the story"                         'T-1'          "$mt031_l"
assert_contains "the trace names the phase"                         'RED'          "$mt031_l"
assert_contains "the trace quotes the command, so the log is actionable" 'xargs rm' "$mt031_l"
assert_eq "the trace is one line, not a transcript" 1 "$(printf '%s' "$mt031_l" | grep -c .)"

# Same shape through an input redirect, which is a READ of the list and gives
# the guard no operand either. It must stay allowed (C-5) AND be traced:
# "allowed" and "unexamined" are different facts and the log is where they part.
assert_allowed "$FIX" 'xargs touch < list' 'an input redirect is still a read'
assert_contains "an input-redirect operand list is traced too" 'no-candidate' \
  "$(mt031_log_of 'xargs touch < list')"

# NEGATIVE CONTROLS. Without these the log becomes a line per command and this
# criterion has bought nothing.
assert_eq "a candidate that was found and PERMITTED is not a zero-candidate trace" "" \
  "$(mt031_log_of 'echo x > docs/notes.md')"
assert_eq "a candidate that was found and DENIED is not one either" "" \
  "$(mt031_log_of 'echo x > src/main.ts')"
assert_eq "a read-only cat logs nothing" "" "$(mt031_log_of 'cat src/main.ts')"
assert_eq "a read-only grep logs nothing" "" "$(mt031_log_of 'grep -rn export src/')"
assert_eq "a read-only git diff logs nothing" "" "$(mt031_log_of 'git diff -- src/main.ts')"
assert_eq "a bare redirect to /dev/null is not a write-capable command" "" \
  "$(mt031_log_of 'git diff > /dev/null')"

# And the trace is distinguishable from the OTHER thing this log carries. An
# unresolvable candidate is a declined parse, not an absent one, and one event
# gets one line.
mt031_l="$(mt031_log_of "sed -i 's/a/b/' \"\$EXPORTED_ELSEWHERE\"")"
assert_contains "an unresolvable candidate still logs as an implausible target" \
  'implausible target' "$mt031_l"
assert_eq "and is not ALSO reported as a zero-candidate command" 0 \
  "$(printf '%s' "$mt031_l" | grep -c 'no-candidate')"

# Note on the Symptom C command, deliberately not asserted here: once AC-6 is
# satisfied, `sed -i 's/a/b/' src/main.ts > /dev/null` yields a candidate and
# is BLOCKED, so it is no longer a zero-candidate command and must not be
# traced. It is covered by AC-6 above, which is the stronger outcome.

# ---------------------------------------------------------------------------
describe "MT-031 C-5: the harness's own idioms must keep working"
set_phase "$FIX" RED

# Measured allowed today. A rewrite of the extractor block is the single most
# likely thing to break them, and three are idioms the harness itself pushes
# agents towards.
assert_allowed "$FIX" "sed -i 's/a/b/' docs/notes.md" 'sed -i on docs in RED'
assert_allowed "$FIX" 'sed -i "s|^a/$|a/\nb/|" .gitignore' 'sed -i on .gitignore in RED'
assert_allowed "$FIX" "bash scripts/mutate.sh src/main.ts 's/a/b/' -- true" \
  'the mutate.sh FILE exemption'
assert_allowed "$FIX" 'grep -n "sed -i" docs/notes.md' 'grepping docs for the flag'
assert_allowed "$FIX" "sed -i 's/a/b/' docs/notes.md > /dev/null" \
  'sed -i on docs with a trailing redirect'


# ===========================================================================
# MT-033 - `mv` removes its source, and the guard has never looked at it.
#
# MT-031 pinned "cp/mv judge the LAST non-option operand" and that is right for
# `cp` and wrong for `mv`. Measured, GNU coreutils 8.32, 2026-09-14:
#
#   echo a > f1; echo b > f2; mkdir d; mv f1 f2 d/   ->  f1 and f2 are GONE
#   echo c > g1; echo d > g2; mkdir e; cp g1 g2 e/   ->  g1 and g2 REMAIN
#
# That asymmetry is MT-033 C-3. So `mv` judges EVERY non-option operand - the
# last because it is created, the rest because they are removed - and `cp` is
# unchanged, because judging a `cp` source is a false positive, which is the
# failure mode MT-031 exists to prevent.
#
# Three helpers below. They exist because the denial text grows a line (C-5)
# and `_lib.sh`'s assert_blocked reads only the `path:` line; nothing in the
# suite could previously assert on WHICH operand was refused, which is AC-6.
# ---------------------------------------------------------------------------

# assert_role <fixture> <command> <expected operand: line> [label]
#   Blocked, the denial carries C-5's role line verbatim, and that line comes
#   AFTER `path:`. The ordering half is not decoration: assert_blocked matches
#   `path:     <p>` followed by a space or end-of-string, and 79 assertions in
#   this file depend on it, so a role line emitted before or inside `path:`
#   breaks the whole suite for a reason no single failure would explain.
#
#   The <fixture> argument is first, exactly as in assert_allowed and
#   assert_blocked. That is not decoration either: the first version of these
#   three helpers took the command first, so every call ran `guard_bash "$FIX"
#   "$FIX"` - the fixture DIRECTORY as the command - and all thirteen of them
#   failed with "not blocked at all", which reads exactly like an honest RED.
#   Caught by checking that the failure was the RIGHT failure; recorded in
#   MT-033 `## Regressions` R-2 so the next person adding a helper here knows
#   what it looked like.
assert_role() {
  local r before
  r="$(guard_bash "$1" "$2")"
  if [ -z "$r" ]; then
    _bad "role: ${4:-$2}" "not blocked at all, so there is no denial to read a role line from"
    return
  fi
  case "$r" in
    *"$3"*) ;;
    *) _bad "role: ${4:-$2}" "the denial carries no '$3' line: $r"; return ;;
  esac
  before="${r%%operand:*}"
  case "$before" in
    *"path:     "*) _ok "role: ${4:-$2}" ;;
    *) _bad "role: ${4:-$2}" "the operand: line comes BEFORE path:, which assert_blocked depends on: $r" ;;
  esac
}

# assert_no_role <fixture> <command> [label]
#   Blocked, and carrying NO role line. C-5's fourth row: redirects, rm, touch,
#   tee and sed -i have no ambiguous operand, and inventing a role for them is
#   churn. Without this, "add an operand: line to every denial" satisfies AC-6.
assert_no_role() {
  local r
  r="$(guard_bash "$1" "$2")"
  if [ -z "$r" ]; then
    _bad "no role: ${3:-$2}" "not blocked at all"
    return
  fi
  case "$r" in
    *'operand:'*) _bad "no role: ${3:-$2}" "carries a role line it should not: $r" ;;
    *) _ok "no role: ${3:-$2}" ;;
  esac
}

# assert_blocked_on_either <fixture> <command> <path A> <path B> [label]
#   For `mv FROZEN FROZEN`, where AC-3 asks only that the denial name "a frozen
#   path". BOTH operands are frozen and either is a correct answer; which one is
#   reported depends on the order candidates reach check_path, and no acceptance
#   criterion or contract clause pins that order (today it is whatever `sort -u`
#   in phase-guard.sh produces, which is an implementation detail this story
#   deliberately leaves to GREEN). Asserting one of the two would freeze it.
assert_blocked_on_either() {
  local r
  r="$(guard_bash "$1" "$2")"
  if [ -z "$r" ]; then
    _bad "blocks: ${5:-$2}" "not blocked at all"
    return
  fi
  case "$r" in
    *"path:     $3 "*|*"path:     $3"|*"path:     $4 "*|*"path:     $4")
      _ok "blocks: ${5:-$2}" ;;
    *) _bad "blocks: ${5:-$2}" "blocked, but on neither '$3' nor '$4': $r" ;;
  esac
}

# ---------------------------------------------------------------------------
describe "MT-033 AC-1: mv removes its source, so the source operand is judged"
set_phase "$FIX" RED

# EVERY ASSERTION IN THIS BLOCK IS RED ON ARRIVAL except the last one, which is
# marked. Measured against this fixture on main at b1583d5, 2026-09-14:
# `mv src/main.ts docs/gone.md` is ALLOWED, and src/main.ts is gone afterwards.
# write_candidates emits `W|docs/gone.md|` for it - the operand `mv` creates,
# and nothing at all about the one it destroys.
assert_blocked "$FIX" 'mv src/main.ts docs/gone.md' src/main.ts \
  'a frozen source moved to a permitted path'
assert_blocked "$FIX" "mv 'src/main.ts' docs/gone.md" src/main.ts \
  'a quoted frozen source'

# MT-031 Symptom C in the new direction: a trailing redirect must not hide the
# source operand any more than it hid the sed operand.
assert_blocked "$FIX" 'mv src/main.ts docs/gone.md > /dev/null' src/main.ts \
  'a frozen source with a trailing redirect to /dev/null'
assert_blocked "$FIX" 'mv src/main.ts docs/gone.md > docs/log.txt' src/main.ts \
  'a frozen source with a trailing redirect to a permitted path'

# The command has to be found wherever it sits in a list or a pipeline - the
# same "real token boundary in any word position" the parser already relies on.
assert_blocked "$FIX" 'mv src/main.ts docs/gone.md && echo done' src/main.ts \
  'a frozen source in the first command of an && list'
assert_blocked "$FIX" 'echo x | tee docs/log.md && mv src/main.ts docs/gone.md' src/main.ts \
  'a frozen source in the last command of a pipeline-and-list'

# A cwd-relative source. command_cwd already supplies the `cd src &&` prefix for
# destinations; the source has to be resolved through the same prefix or the
# candidate is the meaningless `main.ts`.
assert_blocked "$FIX" 'cd src && mv main.ts ../docs/gone.md' src/main.ts \
  'a cwd-relative frozen source, resolved through the cd prefix'

# A source held in a variable. MT-031 made `$` resolvable precisely because the
# harness pushes agents towards `F=...; <tool> "$F"`, and the mv source must go
# through resolve_vars like every other candidate.
assert_blocked "$FIX" 'F=src/main.ts; mv "$F" docs/gone.md' src/main.ts \
  'a frozen source held in a quoted variable'
assert_blocked "$FIX" 'F=src/main.ts; mv $F docs/gone.md' src/main.ts \
  'a frozen source held in an unquoted variable'

# An option must be skipped rather than judged, AND must not shift which operand
# is read. `-f` is exactly the flag an agent adds when a move is refused.
assert_blocked "$FIX" 'mv -f src/main.ts docs/gone.md' src/main.ts \
  'an option before a frozen source'

# Many sources: every one of them is removed, so the first frozen one denies.
assert_blocked "$FIX" 'mv src/main.ts docs/a.md docs/b/' src/main.ts \
  'a frozen source among several, moved into a directory'

# One operand. Real `mv` errors on this, but the guard does not consult the
# world and must not be made to: the single operand is still a candidate.
# PASSES TODAY (it is the last operand, so lastop() already emits it) - a
# regression guard against a fix that judges "every operand except the last".
assert_blocked "$FIX" 'mv src/main.ts' src/main.ts \
  'a single operand is still judged'

# ---------------------------------------------------------------------------
describe "MT-033 AC-1: a frozen TEST leaving its path during GREEN"
set_phase "$FIX" GREEN

# The most serious direction in this story, and the reason it is not cosmetic.
# GREEN freezes tests, and GREEN is the phase where an agent has a motive to
# make a failing test go away. `mv tests/main.test.ts docs/gone.md` is the same
# law-2 violation as editing the assertion, and it is ALLOWED today.
assert_blocked "$FIX" 'mv tests/main.test.ts docs/gone.md' tests/main.test.ts \
  'a frozen test moved out of the test path during GREEN'
assert_blocked "$FIX" 'mv tests/main.test.ts docs/gone.md > /dev/null' tests/main.test.ts \
  'the same, with a trailing redirect'
assert_blocked "$FIX" 'cd tests && mv main.test.ts ../docs/gone.md' tests/main.test.ts \
  'the same, cwd-relative'

# mutate.sh exempts its FILE argument and nothing else - the payload after `--`
# is judged like any other command (MT-031, and the existing `cp` payload case
# above). This is the shape the harness itself puts in front of an agent in
# GREEN, so a payload that moves a frozen test out of the way must be refused.
assert_blocked "$FIX" "bash scripts/mutate.sh src/main.ts 's/a/b/' -- mv tests/main.test.ts docs/gone.md" \
  tests/main.test.ts 'a mutate.sh payload moving a frozen test away'

# THE PRECISION SIDE, IN THE SAME PHASE. All three pass today. Without them,
# "block every mv in GREEN" satisfies the four assertions above.
assert_allowed "$FIX" 'cp tests/main.test.ts docs/copy.md' \
  'copying a frozen test is a READ of it, in GREEN too'
assert_allowed "$FIX" 'mv src/main.ts src/renamed.ts' \
  'moving SOURCE in GREEN is exactly what GREEN is for'
assert_allowed "$FIX" 'mv docs/notes.md docs/other.md' \
  'moving docs in GREEN'

# ---------------------------------------------------------------------------
describe "MT-033 AC-4: git mv is judged by the mv rule, not by a new command name"
set_phase "$FIX" RED

# The story as filed said `git mv` "is not in the extractor's command list at
# all, so it is unjudged in both directions". The first half is true and the
# second is false: write_candidates matches a command name in ANY word position
# - deliberately, because `xargs rm`, `echo x | tee f` and the mutate.sh `--`
# payload all depend on it - so `git mv a b` already parses as cmd=mv. Measured
# on main at b1583d5: `git mv docs/notes.md src/main.ts` BLOCKS on src/main.ts
# today, and `git mv src/main.ts docs/gone.md` is ALLOWED. So AC-4 is discharged
# by the mv rule alone, and `git` must NOT be added to isname(): it is not
# write-capable, and a `git` that starts a command context puts every
# `git commit -m` in the repository back in MT-031's false-positive territory.
assert_blocked "$FIX" 'git mv src/main.ts docs/gone.md' src/main.ts \
  'git mv out of a frozen path'
assert_blocked "$FIX" 'git mv docs/notes.md src/main.ts' src/main.ts \
  'git mv INTO a frozen path: blocked today, and it must stay blocked while the mv branch is rewritten'
assert_allowed "$FIX" 'git mv docs/notes.md docs/other.md' \
  'git mv between two permitted paths'

set_phase "$FIX" GREEN
assert_blocked "$FIX" 'git mv tests/main.test.ts docs/gone.md' tests/main.test.ts \
  'git mv a frozen test out of its path during GREEN'

# ---------------------------------------------------------------------------
describe "MT-033 AC-3: the existing destination rule survives"
set_phase "$FIX" RED

# `mv PERMITTED FROZEN` is covered several times over by MT-031's suite (the
# two-operand, three-operand and trailing-redirect cases above) and those stay
# green. What nothing pinned is `mv FROZEN FROZEN`: today it blocks only by
# accident, because the DESTINATION happens to be frozen too, never because the
# source was looked at. Either operand is a correct answer - see
# assert_blocked_on_either.
assert_blocked_on_either "$FIX" 'mv src/main.ts src/renamed.ts' src/main.ts src/renamed.ts \
  'a rename WITHIN a frozen category still blocks, on a frozen path'

set_phase "$FIX" GREEN
assert_blocked_on_either "$FIX" 'mv tests/main.test.ts tests/renamed.test.ts' \
  tests/main.test.ts tests/renamed.test.ts \
  'a rename within the frozen test path during GREEN'
assert_blocked "$FIX" 'mv docs/notes.md tests/main.test.ts' tests/main.test.ts \
  'mv ONTO a frozen test during GREEN: the destination rule, for tests'

# ---------------------------------------------------------------------------
describe "MT-033 AC-2 and AC-5: cp reads its sources, and must keep doing so"
set_phase "$FIX" RED

# ALL OF THESE PASS TODAY. They are the false-positive controls, and they are
# the whole reason AC-1 cannot be satisfied by "judge every operand of cp and mv
# alike". `cp g1 g2 e/` removes neither source - measured, GNU coreutils 8.32 -
# so every one of these is a pure read of a frozen file, which no phase forbids.
#
# EARNED, in RED, by DV-1: the mutation
#   bash scripts/mutate.sh .claude/hooks/lib.sh '361s/lastop()/allops()/' \
#     -- bash scripts/selftest.sh phase-guard
# makes the cp branch judge every operand, and every assertion in this block
# goes red. Output pasted in MT-033 `## Regressions`.
assert_allowed "$FIX" 'cp src/main.ts docs/copy.md' \
  'cp out of a frozen path is a READ'
assert_allowed "$FIX" 'cp src/main.ts docs/copy.md > /dev/null' \
  'cp out of a frozen path, with a trailing redirect'
assert_allowed "$FIX" 'cp src/main.ts docs/a.md docs/b/' \
  'cp with several frozen sources into a directory'
assert_allowed "$FIX" 'F=src/main.ts; cp "$F" docs/copy.md' \
  'a cp source held in a variable is still a READ'

# PO-3: `-t` inverts the operand order, so `cp -t src/ docs/notes.md` writes
# into src/ and is unjudged. That is a REAL hole and it is deliberately OUT OF
# SCOPE here - it belongs with `install`, `ln -f`, `rsync` and `dd` in a story
# with its own evidence. Pinned at its current, permissive behaviour so that
# GREEN cannot silently "fix" it on the way past, untested.
assert_allowed "$FIX" 'cp -t src/ docs/notes.md' \
  'cp -t writing into a frozen directory stays permitted (PO-3, out of scope)'

# ---------------------------------------------------------------------------
describe "MT-033 AC-6 and C-5: the denial says WHICH operand was refused"
set_phase "$FIX" RED

# RED ON ARRIVAL: there is no `operand:` line in the denial at all today.
# C-5 pins the vocabulary and the position - one line, immediately after
# `path:`, never before it and never inside it, because assert_blocked matches
# `path:     <p>` followed by a space or end-of-string.
assert_role "$FIX" 'mv src/main.ts docs/gone.md' \
  'operand:  source of mv (removed by the move)' \
  'a denial on an mv source says the source is removed by the move'
assert_role "$FIX" 'mv src/main.ts docs/a.md docs/b/' \
  'operand:  source of mv (removed by the move)' \
  'a non-final mv operand among several is a source'
assert_role "$FIX" 'mv docs/notes.md src/main.ts' \
  'operand:  destination of mv' \
  'a denial on an mv destination says destination of mv'

# The one that makes the role track POSITION rather than the command name: the
# same command, the same three operands, the frozen one at the END.
assert_role "$FIX" 'mv docs/notes.md docs/other.md src/main.ts' \
  'operand:  destination of mv' \
  'the FINAL operand of a three-argument mv is the destination'

assert_role "$FIX" 'cp docs/notes.md src/main.ts' \
  'operand:  destination of cp' \
  'a denial on a cp destination says destination of cp'

set_phase "$FIX" GREEN
assert_role "$FIX" 'mv tests/main.test.ts docs/gone.md' \
  'operand:  source of mv (removed by the move)' \
  'the GREEN/test direction is legible as a source denial too'
set_phase "$FIX" RED

# The `path:` line keeps its exact spelling AND its place, adjacent and first.
# This is the assertion that fails loudly if the role line is spliced into the
# path line instead of following it - which would take every other blocked
# assertion in this file down with it, for a reason none of them would explain.
# (guard() in _lib.sh flattens newlines to spaces, so the three spaces below are
# the newline plus the next line's two-space indent.)
assert_contains "the role line follows path: immediately, and path: is unchanged" \
  'path:     src/main.ts   operand:  source of mv (removed by the move)' \
  "$(guard_bash "$FIX" 'mv src/main.ts docs/gone.md')"

# C-5's fourth row: every other candidate keeps the message it has. A role line
# on all of them is churn, and it is also the cheapest way to make the six
# assertions above pass without implementing anything.
assert_no_role "$FIX" 'rm src/main.ts'                  'rm names no role'
assert_no_role "$FIX" 'echo x > src/main.ts'            'a redirect names no role'
assert_no_role "$FIX" "sed -i 's/a/b/' src/main.ts"     'sed -i names no role'
assert_no_role "$FIX" 'touch src/new.ts'                'touch names no role'
assert_no_role "$FIX" 'echo x | tee src/main.ts'        'tee names no role'

# ---------------------------------------------------------------------------
describe "MT-033 C-6: what the mv rule must not start refusing"
set_phase "$FIX" RED

# ALL OF THESE PASS TODAY. The mv rule widens what the guard judges, so this is
# where a widening becomes a false-positive machine. The first two are aimed
# squarely at C-5's stated hazard: the candidate filter in phase-guard.sh drops
# a line that is empty, starts with a dash, contains a glob, or starts with
# /dev/ - and every one of those anchors assumes the line IS the bare path. If
# candidates start carrying a role, a line that no longer begins with `/dev/`
# or `-` slips through, and `cmd > /dev/null` is the most common command shape
# in this repository.
assert_allowed "$FIX" 'echo x > /dev/null' \
  'the /dev/null filter still fires'
assert_allowed "$FIX" 'git diff > /dev/null' \
  'a read-only command with a /dev/null redirect'
assert_allowed "$FIX" 'mv -v docs/notes.md docs/other.md' \
  'an option is not a candidate'

assert_allowed "$FIX" 'mv docs/notes.md docs/other.md' \
  'mv between two permitted paths'
assert_allowed "$FIX" 'cd docs && mv notes.md other.md' \
  'a cwd-relative mv between permitted paths'
set_phase "$FIX" REVIEW
assert_allowed "$FIX" 'mv docs/notes.md docs/other.md' \
  'mv between two permitted paths in REVIEW'
assert_allowed "$FIX" 'mv docs/notes.md docs/other.md docs/b/' \
  'mv with several permitted sources into a permitted directory, in REVIEW'
set_phase "$FIX" RED

# An unresolvable source must stay a DECLINE, not become a block. This is the
# MT-031 Symptom A family: the classifier's default for an unrecognised string
# is the most restrictive category, so an unresolved variable reaching
# check_path is a hard block on a path that does not exist.
assert_allowed "$FIX" 'mv $UNSET_THING docs/gone.md' \
  'an unresolvable mv source is declined, not blocked'

# Prose, and a read. MT-031 AC-1: `mv` inside a quoted span is one masked token
# and can never be a command name. The second of these names a frozen path
# inside the prose, which is the sharper control now that mv judges more
# operands. C-6 lists the first as already asserted in this suite; it was not -
# only the `cp` spelling of it was (see the false-positives block above).
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -m "we mv the fixtures into a shared file"' \
  'prose mentioning mv in a commit message'
assert_allowed "$FIX" 'git commit --dry-run --allow-empty -m "mv src/main.ts to docs"' \
  'prose naming a frozen path after the word mv'
assert_allowed "$FIX" 'grep -n "mv src" docs/notes.md' \
  'grepping docs for the word mv'

# Zero operands: a write-capable name with nothing to judge stays allowed, and
# MT-031 AC-8's trace is what records it. A fix that manufactures a candidate
# out of an empty operand list would block on the empty string.
assert_allowed "$FIX" 'mv' \
  'mv with no operands at all'

# ---------------------------------------------------------------------------
describe "MT-033 AC-1/AC-6 and PO-8: mv -t inverts the operands, so it inverts the roles"
set_phase "$FIX" RED

# ADDED IN RED'S CORRECTIVE PASS, 2026-09-14. R-6 sent the story back from GREEN:
# mvops() labels operands by POSITION, and `-t DIR` / `--target-directory DIR`
# inverts what position means. Measured, GNU coreutils 8.32, in a scratch
# directory - all five spellings, each leaving the positional GONE from the cwd
# and present in DIR:
#
#   mkdir dest; echo a > f1; mv -t dest/ f1               -> dest/f1
#   mkdir d2;   echo b > f2; mv -td2/ f2                  -> d2/f2
#   mkdir d3;   echo c > f3; mv --target-directory=d3 f3  -> d3/f3
#   mkdir d4;   echo d > f4; mv --target-directory d4 f4  -> d4/f4
#   mkdir d5;   echo e > f5; mv -ft d5/ f5                -> d5/f5
#
# So with -t: DIR is the DESTINATION and EVERY positional is a SOURCE, whatever
# its position. That is the whole rule, and the glued -tDIR spelling is real -
# GNU mv accepts it, measured above, which is why it is asserted here.
#
# WHY THE PERMITTED DIRECTORY IS docs/backlog/ AND NOT docs/, WHICH IS WHAT R-6
# WROTE. A candidate loses its trailing slash in normalize_rel, and a top-level
# directory name has no `/` left for `docs/**` to match, so `docs` falls to the
# classifier's restrictive default and classifies `source`. That is PRE-EXISTING
# and has nothing to do with -t: on main at b1583d5, `mv src/main.ts docs/` is
# BLOCKED on `docs` and so is `cp docs/notes.md docs/`, while
# `mv docs/notes.md docs/sub/` is ALLOWED. With `docs/` as the -t argument the
# denial would name `docs` however mvops() is fixed - `docs` sorts before
# `src/main.ts` - so those rows could never report the source operand and would
# have bounced the story a second time. `docs/backlog/` classifies `docs`, exists
# in the fixture, and isolates the defect R-6 is actually about. Full evidence in
# MT-033 `## Regressions` R-7.

# --- DIR is the destination, so every positional is a source ----------------
# The PATH is already right today (the sole positional is also the last one, so
# position-labelling lands on it by luck); the ROLE is wrong in all five. Each
# path assertion is a false-negative control: without it, "stop parsing mv when
# -t is present" would satisfy every role assertion below by never denying.
assert_blocked "$FIX" 'mv -t docs/backlog/ src/main.ts' src/main.ts \
  'mv -t DIR: the positional is the source, and it is what the denial names'
assert_role "$FIX" 'mv -t docs/backlog/ src/main.ts' \
  'operand:  source of mv (removed by the move)' \
  'mv -t DIR: the positional is a SOURCE, not the destination'

assert_blocked "$FIX" 'mv -tdocs/backlog/ src/main.ts' src/main.ts \
  'mv -tDIR glued: the positional is still the source'
assert_role "$FIX" 'mv -tdocs/backlog/ src/main.ts' \
  'operand:  source of mv (removed by the move)' \
  'mv -tDIR glued: the positional is a SOURCE'

# R-6 calls this one the sharp one, and it is: src/main.ts IS the source, it IS
# the frozen operand, and the shipped denial calls it `destination of mv`. AC-6
# stated backwards is worse than AC-6 unstated.
assert_blocked "$FIX" 'mv --target-directory=docs/backlog src/main.ts' src/main.ts \
  'mv --target-directory=DIR: the positional is the source'
assert_role "$FIX" 'mv --target-directory=docs/backlog src/main.ts' \
  'operand:  source of mv (removed by the move)' \
  'mv --target-directory=DIR: the frozen operand is a SOURCE, and today it is named a destination'

assert_blocked "$FIX" 'mv --target-directory docs/backlog src/main.ts' src/main.ts \
  'mv --target-directory DIR: the positional is the source'
assert_role "$FIX" 'mv --target-directory docs/backlog src/main.ts' \
  'operand:  source of mv (removed by the move)' \
  'mv --target-directory DIR: the positional is a SOURCE'

# -t bundled with another short option. `-f` is exactly the flag an agent adds
# when a move is refused, and `-ft DIR` is how it ends up spelled.
assert_blocked "$FIX" 'mv -ft docs/backlog/ src/main.ts' src/main.ts \
  'mv -ft DIR: a bundled -t still makes the positional a source'
assert_role "$FIX" 'mv -ft docs/backlog/ src/main.ts' \
  'operand:  source of mv (removed by the move)' \
  'mv -ft DIR: the positional is a SOURCE'

# Bundled AND glued, which GNU mv also accepts - measured:
#   mkdir d6; echo f > f6; mv -ftd6/ f6   ->  d6/f6
# Asserted because a fix that recognises `-t` only as a whole token, or only at
# the start of a bundle, gets this one wrong - and an unasserted spelling is
# exactly what sent this story back from GREEN.
assert_blocked "$FIX" 'mv -ftdocs/backlog/ src/main.ts' src/main.ts \
  'mv -ftDIR bundled and glued: the positional is still the source'
assert_role "$FIX" 'mv -ftdocs/backlog/ src/main.ts' \
  'operand:  source of mv (removed by the move)' \
  'mv -ftDIR bundled and glued: the positional is a SOURCE'

# --- and DIR itself is the destination, so DIR is judged ---------------------
# The other direction, and the reason a fix cannot simply relabel every
# positional a source and ignore the option's argument: `mv -t src/ ...` WRITES
# INTO src/, which RED freezes. Two of these are ALLOWED today - the option's
# argument is not visible to the parser at all when it is glued or =-attached,
# so the write into src/ goes unjudged.
assert_blocked "$FIX" 'mv -t src/ docs/notes.md' src \
  'mv -t FROZENDIR: the option argument is the destination and it is judged'
assert_role "$FIX" 'mv -t src/ docs/notes.md' \
  'operand:  destination of mv' \
  'mv -t FROZENDIR: DIR is the DESTINATION, not a source'

assert_blocked "$FIX" 'mv -tsrc/ docs/notes.md' src \
  'mv -tFROZENDIR glued: the glued argument is still the destination'
assert_role "$FIX" 'mv -tsrc/ docs/notes.md' \
  'operand:  destination of mv' \
  'mv -tFROZENDIR glued: DIR is the DESTINATION'

assert_blocked "$FIX" 'mv --target-directory=src docs/notes.md' src \
  'mv --target-directory=FROZENDIR: the attached argument is the destination'
assert_role "$FIX" 'mv --target-directory=src docs/notes.md' \
  'operand:  destination of mv' \
  'mv --target-directory=FROZENDIR: DIR is the DESTINATION'

assert_blocked "$FIX" 'mv --target-directory src/ docs/notes.md' src \
  'mv --target-directory FROZENDIR: the separate argument is the destination'
assert_role "$FIX" 'mv --target-directory src/ docs/notes.md' \
  'operand:  destination of mv' \
  'mv --target-directory FROZENDIR: DIR is the DESTINATION'

assert_blocked "$FIX" 'mv -ft src/ docs/notes.md' src \
  'mv -ft FROZENDIR: a bundled -t still names a destination'
assert_role "$FIX" 'mv -ft src/ docs/notes.md' \
  'operand:  destination of mv' \
  'mv -ft FROZENDIR: DIR is the DESTINATION'

assert_blocked "$FIX" 'mv -ftsrc/ docs/notes.md' src \
  'mv -ftFROZENDIR bundled and glued: the argument is still the destination'
assert_role "$FIX" 'mv -ftsrc/ docs/notes.md' \
  'operand:  destination of mv' \
  'mv -ftFROZENDIR bundled and glued: DIR is the DESTINATION'

# --- the GREEN direction, verbatim from R-6 ---------------------------------
# `docs/` is harmless here: it classifies `source` for the reason in the comment
# above, and GREEN permits source. So this row reads exactly as R-6 wrote it, and
# it is the one that matters most - GREEN is the phase where an agent has a
# motive to make a frozen test go away, and `mv -t docs/ tests/main.test.ts` is
# the spelling that does it.
set_phase "$FIX" GREEN
assert_blocked "$FIX" 'mv -t docs/ tests/main.test.ts' tests/main.test.ts \
  'mv -t out of the frozen test path during GREEN'
assert_role "$FIX" 'mv -t docs/ tests/main.test.ts' \
  'operand:  source of mv (removed by the move)' \
  'mv -t in GREEN: the frozen TEST is a SOURCE, removed by the move'

# --- the two false-positive controls ----------------------------------------
# BOTH PASS ON ARRIVAL, and that is correct rather than convenient.
# The first: -t between two permitted paths must stay permitted, or the fix has
# turned `mv -t` into "block whenever -t is present".
set_phase "$FIX" REVIEW
assert_allowed "$FIX" 'mv -t docs/backlog/ docs/notes.md' \
  'mv -t between two permitted paths stays permitted, in REVIEW'

# The second: `cp -t` is OUT OF SCOPE and stays out of it. PO-8 amended PO-3 for
# `mv -t` ONLY, because only `mv -t` got worse; `cp -t src/ docs/notes.md` is an
# unjudged write into src/ on main too, so it is a hole rather than a regression
# and it belongs with install/ln -f/rsync/dd in a story of its own. Pinned here,
# a second time and next to its mv siblings, so that a fix which teaches the
# parser about -t cannot extend it to cp on the way past without a red test.
set_phase "$FIX" RED
assert_allowed "$FIX" 'cp -t src/ docs/notes.md' \
  'cp -t writing into a frozen directory stays permitted (PO-3/PO-8, out of scope)'

# ---------------------------------------------------------------------------
# MT-034: a directory-shaped path is classified, not guessed at
#
# Every paths.conf glob for a directory carries a `/`, so a BARE directory name
# matches none of them and takes classify()'s restrictive `source` default - and
# the trailing slash an agent actually types is stripped by normalize_rel before
# classify ever sees it. It fails in both directions from one cause, and only
# one of them was known before this story:
#
#   * a FALSE POSITIVE - `cp docs/notes.md docs/` refused in REVIEW, a phase in
#     which docs is explicitly writable, on a command that writes only into
#     docs. That is the denial most likely to teach an agent that denials are
#     noise, which is the instinct law 5 of CLAUDE.md exists to suppress.
#   * a BYPASS - `rm -rf tests/` PERMITTED in GREEN, the phase whose whole job
#     is freezing the test tree. `rm -rf tests/main.test.ts` is refused; the
#     shorter command is not.
#
# assert_blocked_as below is new, because AC-1, AC-3 and AC-3b all name a
# CATEGORY as well as a path, and _lib.sh's assert_blocked reads only `path:`.
# Without the category half, "block tests/ for any reason" satisfies AC-3 -
# including a fix that classified it `vendor`, or one that left it `source` and
# changed what GREEN permits, which is out of scope item 8.

# assert_blocked_as <fixture> <command> <expected path> <expected category> [label]
#   Blocked, on that path, AND reported as that category. One assertion, so that
#   AC-3's four commands are four assertions and DV-1's predicted count is
#   checkable. The path half repeats assert_blocked's matching exactly - a
#   trailing space or end-of-string - because the denial text is the same text
#   and 79 assertions already depend on that spelling.
assert_blocked_as() {
  local r; r="$(guard_bash "$1" "$2")"
  if [ -z "$r" ]; then
    _bad "blocks: ${5:-$2}" "not blocked at all"
    return
  fi
  case "$r" in
    *"path:     $3 "*|*"path:     $3") ;;
    *) _bad "blocks: ${5:-$2}" "blocked, but on the wrong path (wanted '$3'): $r"; return ;;
  esac
  case "$r" in
    *"category: $4"*) _ok "blocks: ${5:-$2}" ;;
    *) _bad "blocks: ${5:-$2}" "blocked on '$3' but with the wrong category (wanted '$4'): $r" ;;
  esac
}

# ---------------------------------------------------------------------------
describe "MT-034 AC-1: a directory-shaped path in a category the phase PERMITS"
set_phase "$FIX" REVIEW

# RED ON ARRIVAL: all four are BLOCKED today, on a path of `docs` and a category
# of `source`. Measured on main at b1583d5 through a git worktree and on the
# _lib.sh fixture; reproduced in RED before these were written.
assert_allowed "$FIX" 'cp docs/notes.md docs/' \
  'cp into docs/ during REVIEW, where docs is writable'
assert_allowed "$FIX" 'mv docs/notes.md docs/' \
  'mv into docs/ during REVIEW'
assert_allowed "$FIX" 'rm -rf docs/' \
  'rm -rf docs/ during REVIEW'
assert_allowed "$FIX" 'touch docs/' \
  'touch docs/ during REVIEW'

# The same criterion in the other phase that has a writable directory the guard
# currently refuses. RED permits `test`, and today a Test Developer cannot copy
# a file into the very tree the phase exists to let them write - it is refused
# on `tests`, category `source`. BOTH RED ON ARRIVAL.
set_phase "$FIX" RED
assert_allowed "$FIX" 'cp docs/notes.md tests/' \
  'cp into tests/ during RED, where test is writable'
assert_allowed "$FIX" 'rm -rf docs/' \
  'rm -rf docs/ during RED, where docs is writable'

# Direction 3, at the guard: the same write, two spellings, two verdicts. The
# absolute branch of check_path reaches classify through to_rel, which KEEPS the
# trailing slash; the relative branch goes through normalize_rel, which strips
# it. The absolute spelling is ALLOWED today and must stay allowed; the relative
# one above is refused today and must become allowed. What this pair pins is
# that the two agree.
#
# PASSES ON ARRIVAL, and it is earned by its partner above: a fix that made the
# two spellings agree by refusing BOTH would take that one red.
set_phase "$FIX" REVIEW
assert_allowed "$FIX" "cp docs/notes.md $FIX/docs/" \
  'the absolute spelling of the same permitted write'

# AC-1's control, verbatim: the criterion must not be satisfiable by making the
# guard quieter. BOTH PASS ON ARRIVAL. `src` is not a category directory and no
# paths.conf glob begins `src/`, so no retry can invent a category for it - see
# AC-4 in lib.test.sh, which is where that is asserted at the unit level.
assert_blocked_as "$FIX" 'cp docs/notes.md src/' src source \
  'cp into src/ stays refused in REVIEW'
assert_blocked_as "$FIX" 'cp docs/notes.md src/sub/' src/sub source \
  'cp one level inside src/ stays refused in REVIEW'

# ---------------------------------------------------------------------------
describe "MT-034 AC-2: mv into a permitted directory is judged on the operand it REMOVES"
set_phase "$FIX" RED

# RED ON ARRIVAL, and this is MT-033 AC-1 finally landing on the command shape
# MT-033 could not reach. Today `mv src/main.ts docs/` is blocked on `docs` -
# the WRONG operand, in a category RED permits, with the role line calling it a
# destination. The frozen file leaving its path is not mentioned at all.
#
# Once `docs` classifies `docs`, the destination candidate is permitted and the
# denial falls where it belongs: on `src/main.ts`, the source, removed by the
# move. The role string is MT-033 C-5's vocabulary verbatim (C-8: mechanical,
# pin exactly).
assert_blocked_as "$FIX" 'mv src/main.ts docs/' src/main.ts source \
  'mv of a frozen file into docs/ is refused on the file, not on docs'
assert_role "$FIX" 'mv src/main.ts docs/' \
  'operand:  source of mv (removed by the move)' \
  'and the denial calls it the source of the mv, not a destination'

# ---------------------------------------------------------------------------
describe "MT-034 AC-3 and AC-3b: GREEN freezes the test tree however the path is spelled"
set_phase "$FIX" GREEN

# ALL FOUR ALLOWED TODAY. `tests` classifies `source`, GREEN permits `source`,
# and so a write into the frozen test tree is permitted when the destination is
# named at the top level and refused one directory down. That is law 2 with a
# hole in it, reachable by a command SHORTER than the one that is caught.
#
# AC-3b - `rm -rf tests/` - is listed as its own criterion because it is the one
# instance whose consequence is unrecoverable: GREEN is precisely the phase in
# which an agent has a motive to make a failing test stop failing, and
# `rm -rf tests/main.test.ts` is refused while `rm -rf tests/` is not.
#
# Exactly four assertions, because AC-4's control predicts "4 red on AC-3".
assert_blocked_as "$FIX" 'cp docs/notes.md tests/' tests test \
  'cp into the frozen test tree during GREEN'
assert_blocked_as "$FIX" 'mv docs/notes.md tests/' tests test \
  'mv into the frozen test tree during GREEN'
assert_blocked_as "$FIX" 'touch tests/' tests test \
  'touch of the frozen test tree during GREEN'
assert_blocked_as "$FIX" 'rm -rf tests/' tests test \
  'AC-3b: rm -rf of the whole frozen test tree during GREEN'

# AC-3's control: the one-level-deeper form is blocked today and must stay
# blocked, and so must the named file. BOTH PASS ON ARRIVAL - they are what
# stops AC-3 being satisfied by widening the guard rather than by classifying
# the path, and what would go red if a fix reached green by changing which
# categories GREEN permits (out of scope item 8).
assert_blocked_as "$FIX" 'cp docs/notes.md tests/sub/' tests/sub test \
  'cp one level inside the frozen test tree stays refused'
assert_blocked_as "$FIX" 'rm -rf tests/main.test.ts' tests/main.test.ts test \
  'rm of a named frozen test stays refused'

# The mirror of AC-3b in the other direction, and AC-4's trap at the guard: a
# bare `src` must keep taking the restrictive default. BOTH PASS ON ARRIVAL;
# they go red under the same mutation that earns AC-4 - stop defaulting to
# source, and RED starts permitting the deletion of the whole source tree.
set_phase "$FIX" RED
assert_blocked_as "$FIX" 'rm -rf src/' src source \
  'rm -rf of the whole frozen source tree during RED stays refused'
assert_blocked_as "$FIX" 'touch src/' src source \
  'touch of the frozen source tree during RED stays refused'

# ---------------------------------------------------------------------------
describe "MT-034 C-6: what the directory rule must not start refusing"

# Already correct, measured, and listed in C-6 so that a fix cannot buy AC-1 by
# refusing more. BOTH PASS ON ARRIVAL. The other four C-6 rows - `rm -rf
# .vitest`, `rm -rf node_modules`, the mutate.sh FILE exemption and
# `git commit -m` prose - are already asserted above by MT-031 and MT-033 and
# are not duplicated here.
set_phase "$FIX" REVIEW
assert_allowed "$FIX" 'mv docs/notes.md docs/sub/' \
  'mv into a nested docs directory during REVIEW'
set_phase "$FIX" RED
assert_allowed "$FIX" 'cp docs/notes.md docs/backlog/' \
  'cp into docs/backlog/ during RED'

# ===========================================================================
# MT-041 - one guard invocation costs half the processes.
#
# ADDITIONS ONLY (AC-2): not one line above this block is changed by MT-041.
# The cost claims are measured on the REAL hook, traced, by the instrument in
# _spawns.sh - whose own negative control is in lib.test.sh. Everything else
# here passes on arrival and pins a verdict the rewrite must keep; MT-041
# `## Test plan` has the mutation that earned each.
. "$TESTS_DIR/_spawns.sh"
_t41="$(mktemp -d 2>/dev/null || mktemp -d -t mt041)"
_f41="$(make_fixture)"
_f41bs="$(printf '%s' "$_f41" | tr '/' '\134')"

# ---------------------------------------------------------------------------
describe "MT-041 AC-1: one guard invocation spawns at most 27 processes"
set_phase "$_f41" RED

# The invocation AC-1 names: `echo hi > src/main.ts`, phase RED, the real hook,
# the _lib.sh fixture. RED ON ARRIVAL - measured at 30bdc9a: 45 in total (the
# story's 44 plus the hook's own `cat` of stdin), of which tr -d '[:space:]' 7,
# tr '\134' '/' 5, tr -d with both quotes 4. The bound 27 is the story's, read
# out, not tuned here (C-6).
spawn_trace "$_f41" Bash command 'echo hi > src/main.ts' "$_t41/ac1"
_tally="$(spawn_tally "$_t41/ac1")"
_why="$(printf 'measured, one line per tool (count, tool):\n%s' "$_tally")"

# Vacuity controls: the bounds below are all "at most", so a trace that never
# reached the classification would satisfy them by counting nothing.
assert_contains "AC-1: the traced invocation still blocks src/main.ts (instrument control)" \
  '"permissionDecision":"deny"' "$(cat "$_t41/ac1.out")"
if [ "$(spawn_traced_calls "$_t41/ac1" classify)" -ge 1 ]; then
  _ok "AC-1: the trace reached classify (instrument control)"
else _bad "AC-1: the trace reached classify (instrument control)" "no classify call in the trace"; fi

_n="$(spawn_count "$_tally" TOTAL)"
if [ "$_n" -le 27 ]; then _ok "AC-1: at most 27 external processes for one guard invocation"
else _bad "AC-1: at most 27 external processes for one guard invocation" "spawned $_n
$_why"; fi
assert_eq "AC-1: no tr -d '[:space:]' is spawned" "0" "$(spawn_count "$_tally" tr:space)"
assert_eq "AC-1: no tr '\\134' '/' is spawned"    "0" "$(spawn_count "$_tally" tr:backslash)"
assert_eq "AC-1: no tr -d of the two quote characters is spawned" "0" "$(spawn_count "$_tally" tr:quotes)"

# ---------------------------------------------------------------------------
describe "MT-041 AC-4: one guard invocation, at most one git check-ignore"

# RED ON ARRIVAL: 2 in both - is_ignored asks `<p>`, then `<p>/`. The first is
# the AC-1 trace above (src/main.ts is tracked, so both spellings are asked);
# the second is decided by the SLASHED spelling alone.
_n="$(spawn_count "$_tally" 'git check-ignore')"
if [ "$_n" -le 1 ]; then _ok "AC-4: echo hi > src/main.ts spawns at most one git check-ignore"
else _bad "AC-4: echo hi > src/main.ts spawns at most one git check-ignore" "spawned $_n"; fi

spawn_trace "$_f41" Bash command 'rm -rf .vitest' "$_t41/ac4"
_n="$(spawn_count "$(spawn_tally "$_t41/ac4")" 'git check-ignore')"
assert_not_contains "AC-4: rm -rf .vitest is still allowed - ignored only as .vitest/" \
  '"permissionDecision":"deny"' "$(cat "$_t41/ac4.out")"
if [ "$(spawn_traced_calls "$_t41/ac4" is_ignored)" -lt 1 ]; then
  _bad "AC-4: rm -rf .vitest spawns at most one git check-ignore" "the trace never reached is_ignored"
elif [ "$_n" -le 1 ]; then _ok "AC-4: rm -rf .vitest spawns at most one git check-ignore"
else _bad "AC-4: rm -rf .vitest spawns at most one git check-ignore" "spawned $_n"; fi

# AC-4 as amended (A-1, PO-5 D-3): at most one per CLASSIFIED CANDIDATE. Three
# source candidates in GREEN, which permits source, so no denial ends the hook
# early and all three are classified. RED ON ARRIVAL: measured 6 at 30bdc9a.
set_phase "$_f41" GREEN
spawn_trace "$_f41" Bash command 'rm src/a.ts src/b.ts src/c.ts' "$_t41/ac4n"
_n="$(spawn_count "$(spawn_tally "$_t41/ac4n")" 'git check-ignore')"
_c="$(spawn_traced_calls "$_t41/ac4n" classify)"
if [ "$_c" -ne 3 ]; then
  _bad "AC-4: three candidates spawn at most three git check-ignore" "classify was called $_c times, not 3 (instrument control)"
elif [ "$_n" -le 3 ]; then _ok "AC-4: three candidates spawn at most three git check-ignore"
else _bad "AC-4: three candidates spawn at most three git check-ignore" "spawned $_n"; fi

# "Both spellings of every candidate are still submitted." The instrument sees
# argv, not stdin, so a `--stdin` implementation's input is invisible to it -
# this is proved by VERDICT instead, which holds whatever the mechanism. Three
# candidates in REVIEW, which refuses source, each ignored by a different
# spelling: `.vitest` and `playwright-report` only as `<p>/`, `bareonly` only as
# `<p>` (`!bareonly/` re-includes the slashed form). Allowed only if every
# candidate's deciding spelling reached git; drop either spelling and one of
# them falls to `source` and is refused. Also counted: at most three. RED ON
# ARRIVAL for the count (measured 5: 2 + 1 + 2); the verdict passes today.
_f41b="$(make_fixture)"
printf 'bareonly\n!bareonly/\n' >> "$_f41b/.gitignore"
set_phase "$_f41b" REVIEW
spawn_trace "$_f41b" Bash command 'rm -rf .vitest bareonly playwright-report' "$_t41/ac4s"
assert_not_contains "AC-4: both spellings of each of three candidates reach git (all three ignored, allowed in REVIEW)" \
  '"permissionDecision":"deny"' "$(cat "$_t41/ac4s.out")"
_n="$(spawn_count "$(spawn_tally "$_t41/ac4s")" 'git check-ignore')"
_c="$(spawn_traced_calls "$_t41/ac4s" classify)"
if [ "$_c" -ne 3 ]; then
  _bad "AC-4: three ignored candidates spawn at most three git check-ignore" "classify was called $_c times, not 3 (instrument control)"
elif [ "$_n" -le 3 ]; then _ok "AC-4: three ignored candidates spawn at most three git check-ignore"
else _bad "AC-4: three ignored candidates spawn at most three git check-ignore" "spawned $_n"; fi
rm -rf "$_f41b"

# ---------------------------------------------------------------------------
describe "MT-041 AC-5: the same verdicts through a backslash-spelled absolute path"

# The guard's whole path from a Windows spelling: masked, unquoted, judged
# absolute, placed by to_rel, classified. C-5 probe 2 - to_rel's backslash
# conversion made a no-op - is what turns every one of these, and they are the
# verdicts that move silently on the platform this repository is built on.
# One row per way a category is decided - by git, by a rule, by the source
# default, and a directory rule in the phase that freezes it. All eight rows of
# AC-5's table go through the same spelling in lib.test.sh; here each guard
# invocation costs seconds, in the suite this story exists to make cheaper.
set_phase "$_f41" RED
assert_allowed "$_f41" "rm -rf \"$_f41bs\\.vitest\"" \
  'AC-5: rm -rf <root>\.vitest in RED - ignored'
assert_allowed "$_f41" "rm -rf \"$_f41bs\\dist\"" \
  'AC-5: rm -rf <root>\dist in RED - vendor'
assert_blocked "$_f41" "rm -rf \"$_f41bs\\src\\mangatl\\ui\"" src/mangatl/ui \
  'AC-5: rm -rf <root>\src\mangatl\ui in RED - source'
set_phase "$_f41" GREEN
assert_blocked "$_f41" "rm -rf \"$_f41bs\\tests\"" tests \
  'AC-5: rm -rf <root>\tests in GREEN - test'

rm -rf "$_f41" "$_t41"

summary "phase-guard"
