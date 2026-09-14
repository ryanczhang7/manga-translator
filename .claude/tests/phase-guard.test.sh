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
# is exactly that change, reddened 0 assertions where 1 was predicted. The two
# `assert_allowed` cases below are what it has to catch now.
#
# The trap being closed is a precision failure, not a strictness one. MT-031
# exists to make the guard precise; `cp a b c` is the one place the fix
# deliberately declines to block, and an unpinned precision claim is what the
# next rewrite breaks silently.
assert_allowed "$FIX" 'cp docs/notes.md src/main.ts docs/other.md' \
  'cp with three arguments: the frozen file in the middle is a READ'
assert_allowed "$FIX" 'mv docs/notes.md src/main.ts docs/other.md' \
  'mv with three arguments: the frozen file in the middle is a READ'

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

summary "phase-guard"
