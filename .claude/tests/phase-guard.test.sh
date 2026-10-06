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
# HARNESS-031 builds its own fixture (C-3: never append a rule to the shared FIX,
# or every later block inherits it) and adds it here.
H031_FIXES=""
trap 'rm -rf "$FIX" $H031_FIXES' EXIT

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

# ---------------------------------------------------------------------------
describe "RED: a here-string does not open a heredoc"

# `<<<` is a HERE-STRING. It opens nothing, and the word after it is its data,
# not a delimiter. mask_shell_quotes read the SECOND `<` of `<<<` as the start
# of a heredoc - from there, `<< "$paths"` matches the opener pattern - and took
# `$paths` for a delimiter. Every following line was then masked as heredoc
# body, waiting for a line equal to `$paths` that never arrives.
#
# On a one-line command nothing was lost, because the false delimiter only takes
# effect from the NEXT line. On a multi-line command it opened the lock: the
# redirect below arrived as `\004` and the guard saw no write target at all.
#
# Found while building scripts/check-grep-count.sh, which reads source through
# the same masker and was silently scanning a fraction of every file that uses
# a here-string - `scripts/plan.sh` from line 108 on, and nineteen suites.
assert_blocked "$FIX" 'grep x <<< "$data"
echo hi > src/main.ts' src/main.ts 'a redirect on the line after a here-string'

# The same shape with the here-string on the same line, which always worked -
# so a fix that only handles the multi-line case cannot pass both.
assert_blocked "$FIX" 'grep x <<< "$data" > src/main.ts' src/main.ts \
  'a redirect after a here-string on one line'

# And the control that keeps the fix honest: a REAL heredoc still opens one, so
# its body is still data. `>` in the body is prose, not a redirect.
assert_allowed "$FIX" 'cat > docs/notes.md <<'"'"'EOF'"'"'
echo hi > src/main.ts
EOF' 'a real heredoc body is still data, not syntax'

# The one the misparse was hiding: the target is the file, not the sed script.
assert_blocked "$FIX" "sed -i 's|a|b|' src/main.ts"     src/main.ts 'sed -i with | delimiter, writing source'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts"     src/main.ts 'sed -i with / delimiter, writing source'

# A quoted target keeps its spaces instead of being split into fragments.
assert_blocked "$FIX" 'echo x > "src/my file.ts"'       'src/my file.ts' 'quoted target containing a space'

# THE SAME PROPERTY THROUGH EVERY OTHER EXTRACTOR, and it is load-bearing for a
# finding rather than decoration.
#
# The field report's last open item says `path_is_implausible` accepts a
# candidate containing spaces, so a mis-parse is denied as a phase violation
# naming a file that does not exist - and warns that the obvious fix, "a space
# means the parse leaked", would break the assertion above.
#
# Measured, and neither half survives. The predicate is called while the
# candidate is STILL MASKED, and masking replaces the spaces inside a quoted or
# escaped span - so a quoted path arrives as one token with no real space in it,
# and every extractor takes a single `awk` field, which cannot contain one
# either. Ten shapes were tried and none produced a candidate carrying a real
# space. The rule would not break these; it would have no input at all.
#
# That conclusion rests entirely on masking holding through EVERY extractor, and
# only the redirect one was pinned. These are the others. If masking ever stops
# holding, a quoted path splits into fields and these go red - which is the
# alarm the finding needs and did not have.
assert_blocked "$FIX" 'rm -rf "src/a b"'                'src/a b'        'rm, a quoted path with a space'
assert_blocked "$FIX" 'touch "src/c d.ts"'              'src/c d.ts'     'touch, the same'
assert_blocked "$FIX" 'tee "src/x y.ts"'                'src/x y.ts'     'tee, the same'
assert_blocked "$FIX" 'cp docs/notes.md "src/e f.ts"'   'src/e f.ts'     'cp, on its destination'
assert_blocked "$FIX" 'mv docs/notes.md "src/g h.ts"'   'src/g h.ts'     'mv, the same'
# A BACKSLASH-ESCAPED space is the other spelling, and the masker knows it too.
assert_blocked "$FIX" 'touch src/my\ file.ts'           'src/my file.ts' 'an escaped space, not a quoted one'
assert_blocked "$FIX" 'cp docs/notes.md src/i\ j.ts'    'src/i j.ts'     'and through cp'

assert_blocked "$FIX" 'echo x > src/main.ts' src/main.ts 'redirect into source (Bash)'
r="$(guard "$FIX" Write file_path src/main.ts)"
assert_contains "Write tool is blocked in RED" "category: source" "$r"
r="$(guard "$FIX" Edit file_path "$FIX/src/main.ts")"
assert_contains "Edit tool is blocked on an absolute path" "category: source" "$r"

# The other two tool names CLAUDE.md promises the lock covers. Neither string
# appeared anywhere in this suite, so narrowing the case to `Write|Edit)` -
# which switches the lock OFF for both - passed 145 of 145. MultiEdit is the
# ordinary tool for a multi-hunk edit, so that is not the lock failing on an
# exotic path; it is the lock failing on the routine one.
r="$(guard "$FIX" MultiEdit file_path src/main.ts)"
assert_contains "MultiEdit is blocked in RED" "category: source" "$r"
assert_contains "and names the path it refused" "path:     src/main.ts" "$r"

# NotebookEdit names its target in `notebook_path`, never in `file_path`, so it
# needs its own check_path call - and deleting that call passed 145 of 145 too.
r="$(guard "$FIX" NotebookEdit notebook_path src/analysis.ipynb)"
assert_contains "NotebookEdit is blocked on notebook_path" "category: source" "$r"
assert_contains "and names the notebook" "path:     src/analysis.ipynb" "$r"


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
describe "RED may declare what its tests need, and nothing else"

# H22. RED writes the failing test; a failing test routinely needs a test-only
# dependency - a temp-directory crate, an async pytest plugin, a snapshot
# matcher - and in every ecosystem that is declared in the same manifest as the
# production dependencies. The lock classified the whole manifest as `config`,
# froze it in RED, and left the agent a refusal with no sanctioned next step,
# which is the condition under which agents invent one.
#
# Note the asymmetry that made it more than an inconvenience: GREEN could add
# ANY dependency it liked, because config is writable there. The phase forbidden
# from touching production code was the only one that could not say what its
# tests needed.
set_phase "$FIX" RED
assert_allowed "$FIX" 'echo x >> Cargo.toml'      'RED may write Cargo.toml'
assert_allowed "$FIX" 'echo x >> package.json'    'RED may write package.json'
assert_allowed "$FIX" 'echo x >> pyproject.toml'  'RED may write pyproject.toml'
# The lockfile too, or the install that follows the declaration cannot complete.
assert_allowed "$FIX" 'echo x >> Cargo.lock'      'RED may write the lockfile'
assert_allowed "$FIX" 'echo x >> pnpm-lock.yaml'  'RED may write pnpm-lock.yaml'

# What the manifest permission is NOT. Splitting manifests out of `config` must
# not hand RED the rest of the configuration: a build config, a container
# definition or a tsconfig is production surface and stays frozen.
assert_blocked "$FIX" 'echo x >> tsconfig.json'   tsconfig.json   'tsconfig is still config'
assert_blocked "$FIX" 'echo x >> vite.config.ts'  vite.config.ts  'a build config is still config'
assert_blocked "$FIX" 'echo x >> Dockerfile'      Dockerfile      'a Dockerfile is still config'
assert_blocked "$FIX" 'echo x >> go.mod'          go.mod          'go.mod has no dev section, so it stays config'

# And the phases that could always write these still can.
set_phase "$FIX" GREEN
assert_allowed "$FIX" 'echo x >> Cargo.toml'   'GREEN may still write a manifest'
assert_allowed "$FIX" 'echo x >> tsconfig.json' 'GREEN may still write config'
set_phase "$FIX" REVIEW
assert_blocked "$FIX" 'echo x >> Cargo.toml'   Cargo.toml 'REVIEW may not write a manifest'
set_phase "$FIX" RED

# ---------------------------------------------------------------------------
describe "a redirect belongs to the redirect rule and to no other"
set_phase "$FIX" RED

# H1 again, in the shipped harness, found by a consuming project re-verifying
# the field report against the version it had just vendored.
#
# Every rule except the redirect one takes a word off the end of its match, and
# none of them knew a redirect could be attached. So `cp a b 2>/dev/null` was
# refused on a path of `2>/dev/null`, and `rm a 2>/dev/null` on a path of `2` -
# a different token, because THAT rule's character class excludes `>` and so
# truncates at it, leaving the bare file descriptor behind as the candidate.
#
# The two shapes matter to keep separate. A fix that only declines candidates
# containing `>` cures cp and mv and leaves rm and touch refusing on `2`, which
# is this finding's standing warning arriving on schedule: do not enumerate
# shapes, because the next one is already out there.
assert_allowed "$FIX" 'cp docs/notes.md docs/copy.md 2>/dev/null'    'cp with stderr redirected'
assert_allowed "$FIX" 'cp docs/notes.md docs/copy.md >/dev/null'     'cp with stdout redirected'
assert_allowed "$FIX" 'cp docs/notes.md docs/copy.md 1>/dev/null'    'cp with an explicit fd'
assert_allowed "$FIX" 'mv docs/notes.md docs/copy.md 2>/dev/null'    'mv with stderr redirected'
assert_allowed "$FIX" 'rm docs/notes.md 2>/dev/null'                 'rm with stderr redirected'
assert_allowed "$FIX" 'touch docs/notes.md 2>/dev/null'              'touch with stderr redirected'
assert_allowed "$FIX" 'cat docs/notes.md | tee docs/copy.md > /dev/null' 'tee whose output is discarded'
assert_allowed "$FIX" "sed -i 's/a/b/' .gitignore 2>/dev/null"       'sed -i with stderr redirected'

# The controls, and they are the point: a real write does not become invisible
# by having a redirect attached to it. Each must still be refused, and refused
# on the FILE - a guard that blocks the right command on the wrong path is
# right by accident and will be wrong next time.
assert_blocked "$FIX" 'cp docs/notes.md src/main.ts 2>/dev/null'  src/main.ts 'a real cp, stderr redirected'
assert_blocked "$FIX" 'mv docs/notes.md src/main.ts 2>/dev/null'  src/main.ts 'a real mv, stderr redirected'
assert_blocked "$FIX" 'rm src/main.ts 2>/dev/null'                src/main.ts 'a real rm, stderr redirected'
assert_blocked "$FIX" 'touch src/new.ts 2>/dev/null'              src/new.ts  'a real touch, stderr redirected'
assert_blocked "$FIX" 'echo x | tee src/main.ts > /dev/null'      src/main.ts 'a real tee whose output is discarded'
assert_blocked "$FIX" 'echo x > src/main.ts 2>/dev/null'          src/main.ts 'a real redirect, with stderr also redirected'

# TWO clauses, not one. `>/dev/null 2>&1` is the commonest redirect idiom in
# shell, and every fixture above uses a single clause - so dropping the `g` from
# the NOREDIR sed leaves all of them green while turning each of these into a
# denial on a path of `2` or `2>`. One character, no assertion, and H1 reopened
# after three field reports and two audits closed it.
assert_allowed "$FIX" 'rm docs/notes.md >/dev/null 2>&1'              'rm, stdout and stderr both redirected'
assert_allowed "$FIX" 'cp docs/notes.md docs/copy.md >/dev/null 2>&1' 'cp, two clauses'
assert_allowed "$FIX" 'mv docs/notes.md docs/copy.md >/dev/null 2>&1' 'mv, two clauses'
assert_allowed "$FIX" 'touch docs/notes.md >/dev/null 2>&1'           'touch, two clauses'
assert_allowed "$FIX" 'rm -rf dist 1>/dev/null 2>/dev/null'           'two clauses, both with explicit fds'

# The controls: a strip greedy enough to swallow a second clause is also greedy
# enough to swallow the target, and that failure looks identical from outside.
assert_blocked "$FIX" 'cp docs/notes.md src/main.ts >/dev/null 2>&1' src/main.ts 'a real cp behind two clauses'
assert_blocked "$FIX" 'rm src/main.ts >/dev/null 2>&1'               src/main.ts 'a real rm behind two clauses'

# ---------------------------------------------------------------------------
describe "an option's argument is not the file being written"
set_phase "$FIX" RED

# H1's tenth shape, found by the second mutation audit. The rm/touch rule splits
# its match into words and drops anything starting with `-`, but never the WORD
# AFTER an option that takes one. So a timestamp became the write target:
#
#   touch -t 202601010000 docs/notes.md   refused, path: 202601010000
#   touch -d 2026-01-01   docs/notes.md   refused, path: 2026-01-01
#
# The third case is the one that matters most, because it is not a nonsense
# path - it is a real file, and a READ of it:
#
#   touch -r src/main.ts docs/a.md        refused, path: src/main.ts
#
# `-r` names the reference file whose timestamp is copied FROM. Refusing on it
# denies a legitimate command by pointing at a file it only reads, which is
# the most convincing kind of wrong denial: the path is real, so the message
# looks correct.
assert_allowed "$FIX" 'touch -t 202601010000 docs/notes.md' 'touch -t, timestamp is not a path'
assert_allowed "$FIX" 'touch -d 2026-01-01 docs/notes.md'   'touch -d, date is not a path'
assert_allowed "$FIX" 'touch -r src/main.ts docs/a.md'      'touch -r, the reference is only read'
assert_allowed "$FIX" 'touch --reference=src/main.ts docs/a.md' 'touch --reference=, attached form'
assert_allowed "$FIX" 'rm -f docs/notes.md'                 'rm -f still fine'

# And the controls, because an option-skipping rule that skips one word too many
# stops seeing the target. Each of these must still be refused, on the FILE.
assert_blocked "$FIX" 'touch -t 202601010000 src/main.ts' src/main.ts 'a real touch behind -t'
assert_blocked "$FIX" 'touch -d 2026-01-01 src/main.ts'   src/main.ts 'a real touch behind -d'
assert_blocked "$FIX" 'touch -r docs/notes.md src/main.ts' src/main.ts 'the TARGET of -r is still judged'
assert_blocked "$FIX" 'rm -rf src/main.ts'                src/main.ts 'rm -rf still refused'
assert_blocked "$FIX" 'touch src/new.ts'                  src/new.ts  'plain touch still refused'
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

# The control for the two assertions added in RED above, and it has to run in
# BOTH directions to be worth anything. "Deny whenever the tool is MultiEdit"
# satisfies a denial-only test perfectly well; what distinguishes a real lock is
# that the same tool in the same phase gets opposite verdicts from the CATEGORY.
r="$(guard "$FIX" MultiEdit file_path tests/main.test.ts)"
assert_contains "MultiEdit to a test is blocked in GREEN" "category: test" "$r"
r="$(guard "$FIX" MultiEdit file_path src/main.ts)"
assert_eq "but MultiEdit to source is allowed in GREEN" "" "$r"
r="$(guard "$FIX" NotebookEdit notebook_path tests/explore.ipynb)"
assert_contains "NotebookEdit to a test notebook is blocked in GREEN" "category: test" "$r"

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

# ---------------------------------------------------------------------------
describe "a phase the table does not list is refused, not waved through"

# phase_allows used to end `# Unknown phase: don't block. return 0`, and that
# fallback is a lock that opens on a typo. Measured on the real hook before this
# was written: PHASE=RED refused a source write; GREE, ZZZ, GREEN. and empty all
# ALLOWED it. `phase.sh set` validates its argument, so the state file should
# never carry one of these - but "should never" is the whole of the defence, and
# the state file is a file: hand-edited, half-written, restored from a stale
# copy, or produced by a phase.sh whose own validation regressed.
#
# `no active story` is a DIFFERENT condition and still means no lock: the guard
# exits on PHASE=IDLE before reaching here, and IDLE is a row in phases.conf.
# An unrecognised phase is not an absent one.
unknown_phase() { # <phase>
  printf 'STORY_ID=T-1\nSTORY_SLUG=fixture\nSTORY_TYPE=feature\nPHASE=%s\nBRANCH=story/T-1-fixture\n' \
    "$1" > "$FIX/.claude/state/current-story.env"
}

for ph in GREE ZZZ 'GREEN.'; do
  unknown_phase "$ph"
  r="$(guard "$FIX" Write file_path src/main.ts)"
  if [ -z "$r" ]; then
    _bad "PHASE=$ph refuses a source write" "it was allowed - the lock is off on a typo"
  else
    case "$r" in
      *"$ph"*) _ok "PHASE=$ph refuses a source write" ;;
      *) _bad "PHASE=$ph refuses a source write" "refused, but the reason never names the phase: $r" ;;
    esac
  fi
done

# Empty is its own case: it is what a truncated or half-written state file
# leaves behind, and it is not IDLE.
printf 'STORY_ID=T-1\nSTORY_SLUG=fixture\nSTORY_TYPE=feature\nPHASE=\nBRANCH=story/T-1-fixture\n' \
  > "$FIX/.claude/state/current-story.env"
r="$(guard "$FIX" Write file_path src/main.ts)"
if [ -z "$r" ]; then
  _bad "an empty PHASE refuses a source write" "it was allowed"
else
  _ok "an empty PHASE refuses a source write"
fi

# THE CONTROL. Without it, "refuse everything" passes all four above and the
# fix has simply frozen the tree.
set_phase "$FIX" GREEN
r="$(guard "$FIX" Write file_path src/main.ts)"
assert_eq "while a phase the table DOES list still allows it" "" "$r"
set_phase "$FIX" ""
# The lock protects a cycle in flight; it is not a general permission system,
# and that has to hold for every tool it covers rather than for the two that
# happened to be tested.
r="$(guard "$FIX" MultiEdit file_path src/main.ts)"
assert_eq "MultiEdit with no story" "" "$r"
r="$(guard "$FIX" NotebookEdit notebook_path src/analysis.ipynb)"
assert_eq "NotebookEdit with no story" "" "$r"

# ---------------------------------------------------------------------------
describe "WORLD-080: a filename containing -i is not the sed -i option"

# The report: `sed -n '1,5p' tests/guards/layer-imports.test.ts` - a pure read
# that writes nothing - refused with a message about frozen production code.
# The extractor matched `-i` as a BARE SUBSTRING anywhere after the word `sed`,
# the substring occurs inside `layer-imports`, and `awk '{print $NF}'` then took
# the file being READ as the write target. Sibling files in the same directory
# were allowed because their names contain no `-i`. The file's CONTENTS are
# irrelevant - the guard never opens it.
#
# The phase of each case is chosen from the category it has to freeze, which is
# the trap the original report fell into: `test` is WRITABLE in RED, so a
# misparsed read of a test path cannot block in RED however badly it is parsed.
# AC-1 therefore runs in DONE.

# The controls first, because they are what stops every "must be permitted"
# case below from passing vacuously. If notes-inline.txt classified as docs, or
# src/lib/layer-imports.ts as test, those reads would be permitted for a reason
# with nothing to do with this defect.
set_phase "$FIX" RED
assert_blocked "$FIX" 'echo x > src/lib/layer-imports.ts' src/lib/layer-imports.ts \
  'control: the -i bearing SOURCE path is frozen in RED'
assert_blocked "$FIX" 'echo x > notes-inline.txt' notes-inline.txt \
  'control: the -i bearing ROOT path is frozen in RED, via the paths.conf fallback'
set_phase "$FIX" DONE
assert_blocked "$FIX" 'echo x > tests/guards/layer-imports.test.ts' tests/guards/layer-imports.test.ts \
  'control: the -i bearing TEST path is frozen in DONE'

# AC-1. The literal command from the report, in a phase that freezes `test`.
assert_allowed "$FIX" "sed -n '1,5p' tests/guards/layer-imports.test.ts" \
  'AC-1: sed -n read of an -i bearing test path, in DONE'

set_phase "$FIX" RED
# AC-2. The same misparse on a source path, in the phase that freezes source.
assert_allowed "$FIX" "sed -n '1,5p' src/lib/layer-imports.ts" \
  'AC-2: sed -n read of an -i bearing source path, in RED'

# AC-3. Unquoted, so masking cannot help: there is nothing quoted to mask.
assert_allowed "$FIX" 'sed -n 1,5p notes-inline.txt' \
  'AC-3: an unquoted -i bearing token in a sed read'

# AC-4. Other short options, none of them i.
assert_allowed "$FIX" "sed -En '1,5p' src/main.ts" \
  'AC-4: sed -En read of frozen source'

# Three shapes beyond the enumerated criteria, found by probing the guard
# rather than by reading it.
#
# A read naming TWO input files, the first -i bearing. `$NF` is the second, so
# the guard refused this on src/main.ts - a real file it only reads, which is
# the most convincing kind of wrong denial. A fix that merely exempts the word
# containing `-i` still fails here.
assert_allowed "$FIX" "sed -n '1,5p' src/lib/layer-imports.ts src/main.ts" \
  'a two-file sed read whose first file is -i bearing'

# A read whose sed SCRIPT contains the literal text `-i` - which is what an
# agent auditing this very defect types. Masking does not save it: the masker
# rewrites operators and whitespace inside quotes, not letters, so a quoted
# `-i` reaches the extractor intact.
assert_allowed "$FIX" "sed -n '/sed -i/p' src/main.ts" \
  'a sed read whose script mentions -i'

# A long option that merely CONTAINS the letter i and is not --in-place.
# `--silent` is GNU sed's long form of -n, so this writes nothing; the obvious
# wrong fix - "a word starting with - and containing i" - refuses it.
assert_allowed "$FIX" "sed --silent '1,5p' src/main.ts" \
  'sed --silent, a long option containing i that is not --in-place'

# --- and the writes that must STILL be refused ------------------------------
# These matter more than everything above. Deleting the rule cures every false
# positive and removes the only thing stopping an agent from editing frozen
# source with sed -i. AC-5 (the / and | delimiters) and AC-9 (a target held in
# a variable) are asserted where they have always been - at the top of this
# file and under "RED: a path in a variable is still a path" - and are
# deliberately not repeated here.

# AC-6. A backup suffix attached to the option.
assert_blocked "$FIX" "sed -i.bak 's/a/b/' src/main.ts" src/main.ts \
  'AC-6: sed -i.bak writing frozen source'

# AC-7. The long option, bare and with a suffix.
assert_blocked "$FIX" "sed --in-place 's/a/b/' src/main.ts" src/main.ts \
  'AC-7: sed --in-place writing frozen source'
assert_blocked "$FIX" "sed --in-place=.bak 's/a/b/' src/main.ts" src/main.ts \
  'AC-7: sed --in-place=.bak writing frozen source'

# AC-8. A bundled short-option cluster whose letters include i. These were NOT
# already caught: `-ni` and `-Ei` contain no `-i` substring, so the extractor
# never matched them, and both of these in-place writes to frozen source were
# PERMITTED before this story. The false positive and a live hole are the same
# bug read from two ends.
assert_blocked "$FIX" "sed -ni 's/a/b/' src/main.ts" src/main.ts \
  'AC-8: sed -ni writing frozen source'
assert_blocked "$FIX" "sed -Ei 's/a/b/' src/main.ts" src/main.ts \
  'AC-8: sed -Ei writing frozen source'

# GNU getopt_long accepts any unambiguous abbreviation, and --in-place is the
# only long option of GNU sed 4.9 that begins `--i`: `sed --i 's/a/b/' f`
# rewrites f in place, verified against the sed this harness runs on. The
# current extractor catches it only by accident, because `--i` happens to
# contain the substring `-i`. A fix matching the literal `--in-place` cures the
# false positives and opens this hole.
assert_blocked "$FIX" "sed --i 's/a/b/' src/main.ts" src/main.ts \
  'sed --i, an abbreviated --in-place, writing frozen source'

# And the pair that guards the fix's own mechanism: an -i bearing filename is
# not exempt from being written. "Skip candidates whose name contains -i"
# satisfies every must-permit case above and deletes the protection for these.
assert_blocked "$FIX" "sed -i 's/a/b/' src/lib/layer-imports.ts" src/lib/layer-imports.ts \
  'a real sed -i onto the -i bearing source path is still refused'
assert_blocked "$FIX" "sed -i 's/a/b/' notes-inline.txt" notes-inline.txt \
  'a real sed -i onto the -i bearing root path is still refused'

# AC-11. The redirect scanner is a different rule and this story must not
# disturb it.
assert_blocked "$FIX" 'echo x > src/main.ts' src/main.ts \
  'AC-11: a redirect into frozen source is untouched by this fix'


# ===========================================================================
# HARNESS-010. The reconciliation of the two write-target parsers.
#
# lib.test.sh asks write_candidates() directly, which is where the ROLE of
# EVERY operand is visible. This half drives the whole hook, which is where the
# things a criterion is actually about live: the verdict, the path named in the
# denial, the role line in the message, and the decline log.
#
# Three helpers, taken from manga-translator's suite because its corpus is half
# of this story's specification and a helper rewritten is a corpus not ported.
# The <fixture> argument comes FIRST, exactly as in assert_allowed and
# assert_blocked: downstream's first version took the command first, so all
# thirteen calls ran the fixture DIRECTORY as the command and failed with "not
# blocked at all", which reads exactly like an honest RED.

# assert_role <fixture> <command> <role line> [label]
#   Blocked, carrying that role, with the role AFTER path: - because
#   assert_blocked anchors on `path:     <p>` followed by a space or end of
#   string, and a role line inserted before it would silently stop 99
#   assertions from matching what they think they match.
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
#   Blocked, carrying NO role line. AC-5's own control: a redirect, an rm, a
#   touch, a tee and a sed -i have no ambiguous operand, and inventing a role
#   for them is churn. Without this, "put an operand: line on every denial"
#   satisfies AC-5.
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
#   For a command where BOTH candidates are frozen and either is a correct
#   answer. Which one is reported depends on the order candidates reach
#   check_path, and no criterion or contract clause pins that order. Asserting
#   one of the two would freeze an implementation detail.
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
describe "HARNESS-010 AC-1: C-1's twenty-two commands under the union rule"
set_phase "$FIX" RED

# C-1 is a SETTLED measurement: twenty-two commands driven through the real
# hook against upstream release 48 and against manga-translator's parser, with
# the instrument shown to BLOCK a frozen-source write and ALLOW a docs write on
# both before a single row was believed. RED re-ran it on CI before depending
# on it and reproduced all twenty-two rows exactly, four DIFFER rows included.
#
# C-2's union rule: the reconciled parser BLOCKS every command either parser
# blocks today. So each row below is the MAXIMUM of the two measured verdicts -
# except the three marked BOTH WRONG, which C-3 and PO-5 hold at ALLOW.

# Agreed BLOCK, both parsers. The union rule must not LOSE any of these.
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts"        src/main.ts 'C-1 r1: sed -i'
assert_blocked "$FIX" "sed -i.bak 's/a/b/' src/main.ts"    src/main.ts 'C-1 r2: sed -i.bak'
assert_blocked "$FIX" "sed -ni 's/a/b/' src/main.ts"       src/main.ts 'C-1 r3: sed -ni'
assert_blocked "$FIX" "sed -Ei 's/a/b/' src/main.ts"       src/main.ts 'C-1 r4: sed -Ei'
assert_blocked "$FIX" "sed --in-place 's/a/b/' src/main.ts" src/main.ts 'C-1 r5: sed --in-place'
assert_blocked "$FIX" 'mv docs/notes.md src/main.ts'       src/main.ts 'C-1 r9: mv onto source'
assert_blocked "$FIX" 'cp docs/notes.md src/main.ts'       src/main.ts 'C-1 r14: cp onto source'
assert_blocked "$FIX" 'rm src/main.ts'                     src/main.ts 'C-1 r16: rm source'
assert_blocked "$FIX" 'rm -f src/a.ts src/b.ts'            src/a.ts    'C-1 r17: rm -f two sources'
assert_blocked "$FIX" 'touch src/main.ts'                  src/main.ts 'C-1 r18: touch source'
assert_blocked "$FIX" 'tee src/main.ts < docs/notes.md'    src/main.ts 'C-1 r19: tee into source'
assert_blocked "$FIX" 'tee -a src/main.ts < docs/notes.md' src/main.ts 'C-1 r20: tee -a into source'

# Agreed ALLOW, both parsers, and they must stay allowed.
assert_allowed "$FIX" 'sed -n 1,5p tests/guards/layer-imports.test.ts' \
  'C-1 r7: an -i bearing filename under sed -n'
assert_allowed "$FIX" 'sed -n 1,5p src/main.ts' 'C-1 r8: sed -n reading source'

# THE FOUR DIFFER ROWS. Each is a hole in one parser, with a direction.
#
# r6: upstream is right. GNU getopt_long honours any unambiguous abbreviation
# and --in-place is the only long option of GNU sed 4.9 beginning `--i`, so
# `sed --i` genuinely writes in place. Downstream permits it.
assert_blocked "$FIX" "sed --i 's/a/b/' src/main.ts" src/main.ts \
  'C-1 r6 DIFFER: sed --i, which downstream permits'
# r10: downstream is right. mv REMOVES its source, so moving a frozen file away
# is a write to the frozen path, and upstream permits it.
assert_blocked "$FIX" 'mv src/main.ts docs/notes.md' src/main.ts \
  'C-1 r10 DIFFER: mv a frozen source away, which upstream permits'
# r11 and r12: downstream is right. -t and --target-directory INVERT which
# operand is the destination; upstream reads position only, so it permits a move
# INTO a frozen directory.
assert_blocked "$FIX" 'mv -t src docs/notes.md' src \
  'C-1 r11 DIFFER: mv -t into frozen source, which upstream permits'
assert_blocked "$FIX" 'mv --target-directory=src docs/notes.md' src \
  'C-1 r12 DIFFER: mv --target-directory= into frozen source'

# r13. Both parsers BLOCK this today, and C-2 notes upstream does so for the
# WRONG reason - on the positional, not on understanding -t. It is asserted
# with assert_blocked_on_either, and that is not slack: bare `docs` classifies
# as SOURCE in this repository, because only `docs/` with its trailing slash
# matches the docs rule. Which of the two paths the denial names therefore turns
# on a directory-shaped-path gap in classify that `## Out of scope` puts outside
# this story. Pinning either spelling here would freeze that gap into a test.
# The sharp form of the same command, with the slash, is two lines below.
assert_blocked_on_either "$FIX" 'mv -t docs src/main.ts' docs src/main.ts \
  'C-1 r13: mv -t docs, blocked on one of its two operands'
assert_blocked "$FIX" 'mv -t docs/ src/main.ts' src/main.ts \
  'C-1 r13 sharpened: with the slash, docs/ is writable and the SOURCE is refused'

# THE THREE BOTH WRONG ROWS. All three are real writes into frozen source that
# both parsers permit today, and C-3 and PO-5 make them findings rather than
# criteria: widening the rule set inside a reconciliation makes it impossible to
# attribute a behaviour change to either cause. These assertions pin the holes
# OPEN. A run that quietly closes one has changed the rule set as well as
# reconciling it, which is the one thing this story must not do without saying
# so - and it will say so here, by going red.
assert_allowed "$FIX" 'cp -t src docs/notes.md' \
  'C-1 r15 BOTH WRONG, held open: cp -t is not given mv -t treatment'
assert_allowed "$FIX" 'truncate -s 0 src/main.ts' \
  'C-1 r21 BOTH WRONG, held open: truncate is not a write-capable name'
assert_allowed "$FIX" 'install -m 644 docs/notes.md src/main.ts' \
  'C-1 r22 BOTH WRONG, held open: install is not a write-capable name'

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-3: mv removes its source, so the source operand is judged"
set_phase "$FIX" RED

# Upstream's extractor ends in `awk '{print $NF}'`, so it judged the operand mv
# CREATES and said nothing about the ones it DESTROYS: a frozen file could leave
# its path in any phase. Every shape below was red in the cross-run.
assert_blocked "$FIX" 'mv src/main.ts docs/notes.md' src/main.ts \
  'a frozen source moved to a permitted path'
assert_blocked "$FIX" 'mv "src/main.ts" docs/notes.md' src/main.ts \
  'a quoted frozen source'
assert_blocked "$FIX" 'mv src/main.ts docs/notes.md > /dev/null' src/main.ts \
  'a trailing redirect to /dev/null does not hide the source'
assert_blocked "$FIX" 'mv src/main.ts docs/notes.md > docs/log.txt' src/main.ts \
  'a trailing redirect to a permitted path does not hide it either'
assert_blocked "$FIX" 'git status && mv src/main.ts docs/notes.md' src/main.ts \
  'the last command of an && list'
assert_blocked "$FIX" 'mv -f src/main.ts docs/notes.md' src/main.ts \
  'an option before a frozen source'
assert_blocked "$FIX" 'mv docs/a.md src/main.ts docs/b.md' src/main.ts \
  'three operands: the frozen file in the MIDDLE is removed by the move'
assert_blocked "$FIX" 'cd docs && mv ../src/main.ts notes2.md' src/main.ts \
  'a cwd-relative frozen source, resolved through the cd prefix'
assert_blocked "$FIX" 'F=src/main.ts; mv "$F" docs/notes.md' src/main.ts \
  'a frozen source held in a variable the command itself assigns'
assert_blocked "$FIX" 'git mv src/main.ts docs/notes.md' src/main.ts \
  'git mv is judged by the mv rule, not by a new command name'

set_phase "$FIX" GREEN
assert_blocked "$FIX" 'mv tests/main.test.ts docs/notes.md' tests/main.test.ts \
  'a frozen TEST leaving its path during GREEN'
assert_blocked "$FIX" 'git mv tests/main.test.ts docs/notes.md' tests/main.test.ts \
  'git mv a frozen test out of its path during GREEN'

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-3: -t and --target-directory invert the destination"
set_phase "$FIX" RED

# All six spellings, because three of them glue or attach the argument. A parser
# that drops a `-` token whole leaves `mv -tsrc/ docs/notes.md` an entirely
# unjudged write INTO frozen source - the argument has to be READ, not skipped.
assert_blocked "$FIX" 'mv -t src/ docs/notes.md'                  src/ '-t DIR separate'
assert_blocked "$FIX" 'mv -tsrc/ docs/notes.md'                   src/ '-tDIR glued'
assert_blocked "$FIX" 'mv --target-directory src/ docs/notes.md'  src/ '--target-directory DIR separate'
assert_blocked "$FIX" 'mv --target-directory=src/ docs/notes.md'  src/ '--target-directory=DIR attached'
assert_blocked "$FIX" 'mv -ft src/ docs/notes.md'                 src/ '-ft DIR bundled'
assert_blocked "$FIX" 'mv -ftsrc/ docs/notes.md'                  src/ '-ftDIR bundled and glued'

# And the inverse direction: with -t, the POSITIONAL is a source however late it
# appears, so a frozen positional is refused even though the destination is
# writable.
assert_blocked "$FIX" 'mv -t docs/ src/main.ts'    src/main.ts '-t: the positional is still a source'
assert_blocked "$FIX" 'mv -tdocs/ src/main.ts'     src/main.ts '-tDIR glued: the positional is still a source'
assert_blocked "$FIX" 'mv --target-directory=docs/ src/main.ts' src/main.ts \
  '--target-directory=: the positional is still a source'

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-2: every operand of an in-place edit, not the last word"
set_phase "$FIX" RED

assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts docs/notes.md" src/main.ts \
  'a frozen operand followed by a permitted one'
assert_blocked "$FIX" "sed -i -e 's/a/b/' src/main.ts docs/notes.md" src/main.ts \
  'the -e form, frozen operand first'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts > /dev/null" src/main.ts \
  'a trailing redirect to /dev/null does not hide the operand'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts 2>/dev/null" src/main.ts \
  'a stderr redirect is a file descriptor, not an operand'
assert_blocked "$FIX" "sed -i 's/a/b/' src/main.ts > docs/log.txt" src/main.ts \
  'a redirect to a permitted path does not hide it either'

# A metacharacter in the expression is data. `(` used to terminate the
# extractor's character class INSIDE the script, so the candidate was a fragment
# of the sed program - `s` - which is a block on a nonsense path, and with `!`
# in front of it the command was allowed outright.
assert_blocked "$FIX" "sed -i 's/\\(a\\)/b/' src/main.ts"         src/main.ts 'a capture group'
assert_blocked "$FIX" "sed -i '/x/!s/\\(a\\)/b/' src/main.ts"     src/main.ts 'a negated address AND a capture group'
assert_blocked "$FIX" "sed -i '/x/!s/\\(a\\)|b;c<d>e&f/g/' src/main.ts" src/main.ts 'every one of them at once'
assert_allowed "$FIX" "sed -i 's/\\(a\\)/b/' docs/notes.md" \
  'the same defect from the false-positive side: a capture group writing docs'

# The field report verbatim: `(` in `min(` truncated the match inside the
# script and the fragment carried an alphanumeric and no paren, so
# path_is_implausible believed it and the guard blocked on it.
H010_B="sed -i 's|        if a.ndim == 4 and min(a.shape[1], a.shape[3]) <= 8 ...|...|'"
assert_allowed "$FIX" "$H010_B /tmp/claude/scratch/sib.py" \
  'the field report verbatim, against a path outside the repository'
assert_blocked "$FIX" "$H010_B src/main.ts" src/main.ts \
  'the same expression against a frozen source file'

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-4: a write that parsed to no target leaves a trace"
set_phase "$FIX" RED

# AC-4. A command that NAMES a write-capable tool and yields no target the guard
# can judge is ALLOWED, as it must be, and says so. Until that line existed the
# two outcomes - "the extractors found nothing to judge" and "they found
# candidates and every one was permitted" - were indistinguishable from outside,
# which is how a bypass stays invisible: the log is empty either way.
H010_LOG="$FIX/.claude/state/phase-guard-declined.log"
h010_log_of() { rm -f "$H010_LOG"; guard_bash "$FIX" "$1" >/dev/null; cat "$H010_LOG" 2>/dev/null; }
h010_lines() { printf '%s' "$1" | awk 'NF { n++ } END { print n + 0 }'; }

assert_allowed "$FIX" "find src -name '*.ts' | xargs rm" \
  'operands arriving from a pipe are unknowable'
h010_l="$(h010_log_of "find src -name '*.ts' | xargs rm")"
assert_contains "a write command with no visible operand is traced" 'no-candidate' "$h010_l"
assert_contains "the trace names the story"                         'T-1'          "$h010_l"
assert_contains "the trace names the phase"                         'RED'          "$h010_l"
assert_contains "the trace quotes the command, so the log is actionable" 'xargs rm' "$h010_l"
assert_eq "the trace is one line, not a transcript" 1 "$(h010_lines "$h010_l")"

assert_allowed "$FIX" 'xargs touch < list' 'an input redirect is still a read'
assert_contains "an input-redirect operand list is traced too" 'no-candidate' \
  "$(h010_log_of 'xargs touch < list')"

# AC-4's CONTROL: a command from which targets ARE derived writes nothing to
# that log. Without these the log becomes a line per command and AC-4 has bought
# nothing at all.
assert_eq "a candidate that was found and PERMITTED is not a zero-candidate trace" "" \
  "$(h010_log_of 'echo x > docs/notes.md')"
assert_eq "a candidate that was found and DENIED is not one either" "" \
  "$(h010_log_of 'echo x > src/main.ts')"
assert_eq "a read-only cat logs nothing"      "" "$(h010_log_of 'cat src/main.ts')"
assert_eq "a read-only grep logs nothing"     "" "$(h010_log_of 'grep -rn export src/')"
assert_eq "a read-only git diff logs nothing" "" "$(h010_log_of 'git diff -- src/main.ts')"
assert_eq "a bare redirect to /dev/null is not a write-capable command" "" \
  "$(h010_log_of 'git diff > /dev/null')"

# And the trace is distinguishable from the OTHER thing this log carries. An
# unresolvable candidate is a parse the guard could not BELIEVE, not one it
# could not FIND, and one event gets one line.
h010_l="$(h010_log_of "sed -i 's/a/b/' \"\$EXPORTED_ELSEWHERE\"")"
assert_contains "an unresolvable candidate still logs as an implausible target" \
  'implausible target' "$h010_l"
assert_not_contains "and is not ALSO reported as a zero-candidate command" \
  'no-candidate' "$h010_l"

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-5: the denial names the operand's role"
set_phase "$FIX" RED

# AC-5 is the criterion with no settled oracle, and `## Deferred verifications`
# records why: the PLANNED probe measured BLOCK/ALLOW only and never parsed a
# message body, so no measurement of what a denial SAYS existed before this
# suite. It also names the trap - "a role assertion that fails only when the
# verdict ALSO flips is not testing the role, it is testing the verdict a second
# time".
#
# So the metric is this PAIR, and it is built to be independent of the verdict:
# the two commands differ only in operand order, BOTH are denied, BOTH are
# denied ON THE SAME PATH, and the only thing that distinguishes them is the
# role. A parser that reported one fixed role for every mv operand would satisfy
# one line and fail the other while leaving every verdict in this file green.
assert_role "$FIX" 'mv src/main.ts docs/notes.md' \
  'operand:  source of mv (removed by the move)' \
  'src/main.ts moved AWAY is a source, removed by the move'
assert_role "$FIX" 'mv docs/notes.md src/main.ts' \
  'operand:  destination of mv' \
  'the SAME path moved ONTO is a destination - same verdict, same path, other role'

# The same independence through the option, where position is no guide at all:
# `-t` makes the late operand a source and the early one a destination.
assert_role "$FIX" 'mv -t docs/ src/main.ts' \
  'operand:  source of mv (removed by the move)' \
  '-t: the positional is a source however late it appears'
assert_role "$FIX" 'mv -t src/ docs/notes.md' \
  'operand:  destination of mv' \
  '-t: DIR is the destination however early it appears'

# cp has its own destination role, and a three-operand mv still names its last.
assert_role "$FIX" 'cp docs/notes.md src/main.ts' \
  'operand:  destination of cp' 'a cp destination says so'
assert_role "$FIX" 'mv docs/a.md docs/b.md src/main.ts' \
  'operand:  destination of mv' 'the FINAL operand of a three-argument mv'
assert_role "$FIX" 'mv docs/a.md src/main.ts docs/b.md' \
  'operand:  source of mv (removed by the move)' \
  'a non-final operand among several is a source'

# The role line comes AFTER path:, and path: keeps its exact spelling and
# indent, because every assert_blocked in this file anchors on it.
assert_contains "the role line follows path: immediately, and path: is unchanged" \
  'path:     src/main.ts   operand:  source of mv (removed by the move)' \
  "$(guard_bash "$FIX" 'mv src/main.ts docs/notes.md')"

# AC-5's OWN CONTROL: a denial for a path with no meaningful role does not
# invent one. Without these, "put an operand: line on every denial" satisfies
# every assertion above.
assert_no_role "$FIX" 'echo x > src/main.ts'          'a redirect target has no ambiguous role'
assert_no_role "$FIX" 'rm src/main.ts'                'an rm operand has no ambiguous role'
assert_no_role "$FIX" 'touch src/main.ts'             'a touch operand has no ambiguous role'
assert_no_role "$FIX" "sed -i 's/a/b/' src/main.ts"   'a sed -i operand has no ambiguous role'
assert_no_role "$FIX" 'echo x | tee src/main.ts'      'a tee operand has no ambiguous role'

set_phase "$FIX" GREEN
assert_role "$FIX" 'mv tests/main.test.ts docs/notes.md' \
  'operand:  source of mv (removed by the move)' \
  'the GREEN/test direction is legible as a source denial too'

# ---------------------------------------------------------------------------
describe "HARNESS-010 AC-6 and C-4: the hook asks lib.sh rather than re-deriving"
set_phase "$FIX" RED

# C-4 and AC-6. The parser is a named function of lib.sh that the hook ASKS -
# the rule rules.md already states for classify.sh - and C-5 checked the callers
# against the tree: `grep -rn CANDIDATES .claude/ scripts/` returns two lines,
# both in phase-guard.sh, and nothing else reads them. RED re-checked that and
# it still holds.
#
# This is the mechanical half of a criterion marked "verified by review"; review
# still owns "every caller asks it", which is a design question a grep cannot
# settle.
assert_contains "lib.sh defines write_candidates" 'write_candidates()' \
  "$(cat "$REPO_ROOT/.claude/hooks/lib.sh")"
assert_contains "phase-guard.sh calls it" 'write_candidates ' \
  "$(cat "$REPO_ROOT/.claude/hooks/phase-guard.sh")"

# And the other half: the inline pipeline it replaces is gone. The needle is the
# `grep -oE` extractor chain, not the word CANDIDATES - that variable survives
# the refactor as the name of the parser's ANSWER, so asserting its absence
# would be an assertion that cannot hold, and asserting its presence would be
# satisfied by the code this story exists to remove.
assert_not_contains "the hook no longer carries its own extractor pipeline" \
  "grep -oE '\\bsed\\b" "$(cat "$REPO_ROOT/.claude/hooks/phase-guard.sh")"

# ---------------------------------------------------------------------------
describe "HARNESS-010 C-6: what the reconciled parser must NOT start refusing"
set_phase "$FIX" RED

# A lock with false positives teaches the agent that blocks are noise, which is
# the instinct law 5 exists to suppress. Both halves of the reconciliation add
# refusals, so this is where the cost of getting it wrong shows up.
#
# The first five are the xA half of the cross-run: manga-translator's parser
# emits every non-option token, so it refused the TIMESTAMP of a touch -t and
# the REFERENCE FILE of a touch -r - a wrong denial naming a real file the
# command never writes, which is the most convincing kind.
assert_allowed "$FIX" 'touch -t 202601010000 docs/a.md' 'touch -t: a timestamp is not a path'
assert_allowed "$FIX" 'touch -d 2026-01-01 docs/a.md'   'touch -d: a date is not a path'
assert_allowed "$FIX" 'touch -r src/main.ts docs/a.md'  'touch -r: the reference is only read'
assert_allowed "$FIX" 'touch --reference src/main.ts docs/a.md' 'touch --reference, the long form'
assert_allowed "$FIX" 'touch --date 2026-01-01 docs/a.md'       'touch --date, the long form'

# cp READS its sources and leaves them where they are. The mv rule must not
# spread to it, or every `cp src/x docs/` a review does becomes a refusal.
assert_allowed "$FIX" 'cp src/main.ts docs/copy.md' 'cp leaves its source where it was'
assert_allowed "$FIX" 'cp docs/a.md docs/b.md'      'cp between permitted paths'

# Ordinary moves inside a permitted category, in every -t spelling.
assert_allowed "$FIX" 'mv docs/a.md docs/b.md'                 'mv between permitted paths'
assert_allowed "$FIX" 'mv -f docs/a.md docs/b.md'              'an option before permitted operands'
assert_allowed "$FIX" 'mv -t docs/ docs/a.md'                  'mv -t into a permitted directory'
assert_allowed "$FIX" 'mv --target-directory=docs/ docs/a.md'  'the attached form, permitted'

# And two frozen operands: either path is a correct answer and no clause pins
# which, but SOMETHING must be refused.
assert_blocked_on_either "$FIX" 'mv src/a.ts src/b.ts' src/a.ts src/b.ts \
  'both operands frozen: one of them is named'


# ---------------------------------------------------------------------------
describe "HARNESS-011 AC-2: GREEN freezes the tests DIRECTORY, not only the files"
set_phase "$FIX" GREEN

# In GREEN, deleting one frozen test was refused and deleting all of them was
# permitted. The cause is not in this hook: `paths.conf` wrote its rules as
# `**/tests/**`, which matches paths UNDER tests and never `tests` itself, so
# the bare directory fell through to the `source` fallback - and source is
# writable in GREEN. Law 2 says tests are frozen during GREEN; the lock
# enforced that per file and not for the directory that holds them.
#
# THE CONTROLS ARE THE POINT of this block. Both of them were ALREADY refused
# at release 49 and must stay refused, because the criterion is about the
# DIRECTORY closing a hole the FILE never had. Without them, "the lock refuses
# something under tests/" proves nothing new.
assert_blocked "$FIX" 'rm -rf tests/main.test.ts' tests/main.test.ts \
  'the control: one test file was always refused'
assert_blocked "$FIX" 'rm -rf tests/' tests/ \
  'the control: a trailing-slash directory, closed by HARNESS-010'

# THE HOLE.
assert_blocked "$FIX" 'rm -rf tests' tests 'the bare tests directory in GREEN'

# ...and refused AS A TEST. A denial alone would be satisfied by a rule that
# swallowed the path into any frozen category; what the story claims is that
# the classifier now gives the bare name its own category.
r="$(guard_bash "$FIX" 'rm -rf tests')"
assert_contains "and refused because it is test, not incidentally" "category: test" "$r"

# THE COUNTER-CONTROL, in the other direction: source is WRITABLE in GREEN and
# must stay so. A fix that reached too far - one over-broad bare rule - would
# freeze src here, and the failure would be silent in the classifier.
assert_allowed "$FIX" 'rm -rf src' 'the control: bare src is still writable in GREEN'

# ---------------------------------------------------------------------------
describe "HARNESS-011 AC-3: RED may write the bare directories RED owns"
set_phase "$FIX" RED

# The same defect pointing the other way. `source` is frozen in RED, so every
# bare directory name that should have been harness, docs or test was REFUSED
# in the phase that may write all three. Measured at release 49: `rm -rf docs`,
# `rm -rf .claude`, `rm -rf scripts`, `rm -rf .github` and `rm -rf tests` were
# all BLOCKED in RED, each one reported as `category: source`.
assert_allowed "$FIX" 'rm -rf docs'    'the bare docs directory in RED'
assert_allowed "$FIX" 'rm -rf scripts' 'the bare scripts directory in RED'
assert_allowed "$FIX" 'rm -rf .claude' 'the bare .claude directory in RED'
assert_allowed "$FIX" 'rm -rf .github' 'the bare .github directory in RED'
assert_allowed "$FIX" 'rm -rf tests'   'the bare tests directory in RED'

# THE CONTROLS. `src` is a real source directory and there is no rule that
# should make it anything else; `wibble` matches no rule at all, and the
# documented fallback to `source` is what makes the lock FAIL CLOSED on a path
# nobody has classified. Eight new rules, three of them `**/`-prefixed, are
# eight chances to swallow a path they were never meant to reach - and a path
# wrongly classified as test or harness is WRITABLE here, where source is
# frozen. These two assertions are what notices.
assert_blocked "$FIX" 'rm -rf src'    src    'the control: bare src is still frozen in RED'
assert_blocked "$FIX" 'rm -rf wibble' wibble 'the control: an unclassified bare name still falls through to source'

# ---------------------------------------------------------------------------
describe "HARNESS-031: a project rule X/** covers bare X, through the guard"

# HARNESS-011 gave the BUILT-IN directory rules bare twins. A project's own
# rule gets none unless its author writes one, and manga-translator's
# `test | fixtures/**` had none. Measured at 16c42a1 through this hook, in a
# fixture with that one line appended:
#
#   GREEN  rm -rf fixtures              ALLOW   <- the frozen test dir is deletable
#   GREEN  rm -rf fixtures/             DENY    the slashed form was always right
#   RED    rm -rf fixtures              DENY    category: source
#   RED    cp docs/notes.md fixtures    DENY    category: source
#   RED    rm -rf .pytest_cache         DENY    category: source (a built-in rule, no twin)
#
# The end-to-end half of the classify.test.sh block. Its own fixture (C-3).
H031="$(make_fixture)"; H031_FIXES="$H031_FIXES $H031"
printf '%s\n' 'test | fixtures/**' >> "$H031/.claude/harness/paths.conf"

# AC-1, GREEN: the hole.
set_phase "$H031" GREEN
assert_blocked "$H031" 'rm -rf fixtures' fixtures \
  'AC-1: the bare fixtures directory in GREEN, under a project rule with no twin'
r="$(guard_bash "$H031" 'rm -rf fixtures')"
assert_contains "AC-1: and refused because it is test, not incidentally" "category: test" "$r"
# Controls: the slashed form was always refused (HARNESS-010), and source stays
# writable in GREEN - a retry that reached too far would freeze src here.
assert_blocked "$H031" 'rm -rf fixtures/' fixtures/ \
  'AC-1 control: the trailing-slash fixtures/ is still refused in GREEN'
assert_allowed "$H031" 'rm -rf src' 'AC-1 control: bare src is still writable in GREEN'

# AC-1 and AC-2, RED: the false positives.
set_phase "$H031" RED
assert_allowed "$H031" 'rm -rf fixtures' 'AC-1: the bare fixtures directory in RED'
assert_blocked "$H031" 'rm -rf src' src 'AC-1 control: bare src is still frozen in RED'
assert_allowed "$H031" 'cp docs/notes.md fixtures' \
  'AC-2: cp into a bare project test directory in RED'

# AC-3, through the guard, against the REAL paths.conf (the shared FIX carries
# no extra rule): a built-in rule with no twin.
set_phase "$FIX" RED
assert_allowed "$FIX" 'rm -rf .pytest_cache' \
  'AC-3: the bare .pytest_cache in RED, a built-in vendor rule with no twin'

# AC-2, REVIEW: what is already right stays right. The slashed operand is kept
# by HARNESS-010 and matches `docs/**`. Passes on arrival; DV-3 earns it by
# deleting that rule. The paired control proves an allow cannot come from the
# guard failing to see a cp target at all.
set_phase "$FIX" REVIEW
assert_allowed "$FIX" 'cp docs/notes.md docs/' 'AC-2: cp into docs/ in REVIEW'
assert_blocked "$FIX" 'cp docs/notes.md src/' src/ \
  'AC-2 control: cp into src/ in REVIEW is refused, on src/'

# ---------------------------------------------------------------------------
# HARNESS-035 - the lock of the worktree that owns the file.
#
# Field report: fantasy-world-builder WORLD-113, D-7. A desktop session started
# in the main checkout moved into a linked worktree. CLAUDE_PROJECT_DIR kept
# naming the main checkout, so every hook read ITS story; and an absolute path
# into the worktree came back from to_rel as "outside", so a Write there was
# never judged at all.
#
# REAL WORKTREES, as in worktree.test.sh: the claim is about what git does with
# `.git`, and a copied directory would pass while proving nothing. A is the main
# checkout and is what CLAUDE_PROJECT_DIR names in every case below, as it did
# in the field. B is a linked worktree in a directory with a DIFFERENT folder
# name, which is the shape to_rel's folder-name fallback could not see. W is a
# linked worktree nested under A, where Claude Code puts its own. C is a
# separate repository, not a worktree of A's at all.
H035_A="$(make_fixture)"
H035_WT="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
H035_C="$(make_fixture)"
H035_FIXES="$H035_A $H035_WT $H035_C"
trap 'rm -rf "$FIX" $H031_FIXES $H035_FIXES' EXIT
H035_B="$H035_WT/b-tree"
H035_W="$H035_A/.claude/worktrees/w"
printf '.claude/state/*\n.claude/worktrees/\n' >> "$H035_A/.gitignore"
git -C "$H035_A" add -A >/dev/null 2>&1
git -C "$H035_A" -c user.email=t@t -c user.name=t commit -qm fixture >/dev/null 2>&1
git -C "$H035_A" worktree add -q -b story/T-B "$H035_B" HEAD >/dev/null 2>&1
git -C "$H035_A" worktree add -q -b story/T-W "$H035_W" HEAD >/dev/null 2>&1
mkdir -p "$H035_B/.claude/state" "$H035_W/.claude/state"

# h035_state <tree> <id> <phase>   A story in that tree's own state file. An
# empty phase clears it. Each tree gets its own id so a denial can be traced to
# the lock that issued it.
h035_state() {
  if [ -z "${3:-}" ]; then rm -f "$1/.claude/state/current-story.env"; return 0; fi
  printf 'STORY_ID=%s\nSTORY_SLUG=fixture\nSTORY_TYPE=feature\nPHASE=%s\nBRANCH=story/%s\n' "$2" "$3" "$2" \
    > "$1/.claude/state/current-story.env"
}

# h035_reason <tool> <key> <value>   The denial reason with CLAUDE_PROJECT_DIR=A,
# and GUARD_CWD as the caller sets it.
h035_reason() { guard "$H035_A" "$1" "$2" "$3"; }

describe "HARNESS-035 premise: B and W are linked worktrees of A, C is not"

_common() { (cd "$1" && cd "$(git rev-parse --git-common-dir)" && pwd); }
# _same_dir <a> <b>   One directory, under whatever spelling: a string match or
# `-ef`, exactly as same_repo in lib.sh compares. A linked worktree's side is
# reached through the path git wrote into its `.git` file - Windows form under
# Git for Windows - while A's is reached through the path mktemp returned, and
# on windows-latest those two spellings of ONE directory do not come back from
# `pwd` the same (HARNESS-038). A string compare alone fails the premise there.
_same_dir() { [ "$1" = "$2" ] || [ "$1" -ef "$2" ]; }
h035_ga="$(_common "$H035_A")"
# h035_shares <label> <tree>   The premise for one linked tree, with the same
# expected/actual report assert_eq gives.
h035_shares() {
  local g; g="$(_common "$2")"
  if _same_dir "$h035_ga" "$g"; then _ok "$1"
  else _bad "$1" "expected: $h035_ga
actual:   $g"; fi
}
h035_shares "B shares A's .git" "$H035_B"
h035_shares "W shares A's .git" "$H035_W"
h035_gt="$(_common "$H035_C")"
if _same_dir "$h035_ga" "$h035_gt"; then
  _bad "C is a separate repository" "C shares A's .git: $h035_gt is $h035_ga"
else _ok "C is a separate repository"; fi
assert_eq "B's folder name is not A's" "no" "$([ "${H035_B##*/}" = "${H035_A##*/}" ] && echo yes || echo no)"

describe "HARNESS-035 AC-1: the session's tree follows the hook input's cwd"

h035_state "$H035_A" T-A RED
h035_state "$H035_B" T-B GREEN
r="$(GUARD_CWD="$H035_B" h035_reason Bash command 'echo x > src/main.ts')"
assert_eq "AC-1: in B (GREEN) a relative source write is allowed although A is in RED" "" "$r"
r="$(GUARD_CWD="$H035_B" h035_reason Bash command 'echo x > tests/main.test.ts')"
assert_contains "AC-1: in B a relative test write is refused" "path:     tests/main.test.ts" "$r"
assert_contains "AC-1: by B's story" "story:    T-B" "$r"
assert_contains "AC-1: in B's phase" "phase:    GREEN" "$r"
r="$(GUARD_CWD="$H035_B" h035_reason Write file_path "$H035_B/tests/main.test.ts")"
assert_contains "AC-1: Write into B's tests with cwd B is refused by B's story" "story:    T-B" "$r"

# The prompt hook: what the field saw report WORLD-018 from inside WORLD-113.
r="$(printf '{"cwd":"%s","hook_event_name":"UserPromptSubmit","prompt":"x"}' "$(json_str "$H035_B")" \
  | CLAUDE_PROJECT_DIR="$H035_A" bash "$REPO_ROOT/.claude/hooks/inject-state.sh" 2>&1)"
assert_contains "AC-1: the prompt hook reports B's story" "Active story: T-B" "$r"
assert_not_contains "AC-1: and not A's" "T-A" "$r"

# A IDLE: the root used to be read as A, found idle, and the guard exited
# before judging anything.
h035_state "$H035_A" T-A ""
r="$(GUARD_CWD="$H035_B" h035_reason Bash command 'echo x > tests/main.test.ts')"
assert_contains "AC-1: with A IDLE, B's GREEN still refuses a test write" "story:    T-B" "$r"

# The field's spelling. The host sends Windows paths, so `cwd` arrives as a
# JSON string full of escaped backslashes. Spelled here by turning the fixture's
# slashes into backslashes, which slash back to the same path on every platform
# (as lib.test.sh's "a backslash path" does). Added on returning to RED: every
# case above passed while a real `"cwd":"D:\\adh-HARNESS-035"` was not read at
# all - see ## Regressions.
H035_BBS="$(printf '%s' "$H035_B" | tr '/' '\134')"
H035_ABS="$(printf '%s' "$H035_A" | tr '/' '\134')"
h035_state "$H035_A" T-A RED
r="$(printf '{"cwd":"%s","hook_event_name":"UserPromptSubmit","prompt":"x"}' "$(json_str "$H035_BBS")" \
  | CLAUDE_PROJECT_DIR="$H035_A" bash "$REPO_ROOT/.claude/hooks/inject-state.sh" 2>&1)"
assert_contains "AC-1: a backslash-spelled cwd is read: the prompt hook reports B's story" "Active story: T-B" "$r"
r="$(GUARD_CWD="$H035_BBS" h035_reason Bash command 'echo x > src/main.ts')"
assert_eq "AC-1: with a backslash-spelled cwd, B (GREEN) allows a relative source write" "" "$r"

# Control: no cwd in the input is today's behaviour - A's lock.
h035_state "$H035_A" T-A RED
r="$(h035_reason Bash command 'echo x > src/main.ts')"
assert_contains "AC-1 control: without cwd the root is CLAUDE_PROJECT_DIR (A refuses)" "story:    T-A" "$r"

describe "HARNESS-035 AC-2: an absolute path into a sibling worktree is judged by its lock"

h035_state "$H035_A" T-A RED
h035_state "$H035_B" T-B RED
for tool in Write Edit; do
  r="$(h035_reason "$tool" file_path "$H035_B/src/main.ts")"
  assert_contains "AC-2: $tool <B>/src/main.ts from A is refused, on B's relative path" "path:     src/main.ts" "$r"
  assert_contains "AC-2: $tool names B's story" "story:    T-B" "$r"
  assert_contains "AC-2: $tool names B as the worktree" "worktree: $H035_B" "$r"
done
r="$(h035_reason Bash command "echo x > $H035_B/src/main.ts")"
assert_contains "AC-2: a Bash redirect to <B>/src/main.ts is refused by B" "story:    T-B" "$r"
r="$(h035_reason Bash command ": >> $H035_B/src/main.ts")"
assert_contains "AC-2: the field's own probe, : >>, by absolute path" "story:    T-B" "$r"
r="$(h035_reason Bash command "cd $H035_B && echo x > src/main.ts")"
assert_contains "AC-2: cd <B> && echo x > src/main.ts is refused by B" "story:    T-B" "$r"
assert_contains "AC-2: on B's relative path" "path:     src/main.ts" "$r"

# A IDLE: the guard must still look, because B is not.
h035_state "$H035_A" T-A ""
r="$(h035_reason Write file_path "$H035_B/src/main.ts")"
assert_contains "AC-2: with A IDLE, Write <B>/src/main.ts is refused by B" "story:    T-B" "$r"
r="$(h035_reason Bash command "echo x > $H035_B/src/main.ts")"
assert_contains "AC-2: with A IDLE, a Bash redirect into B is refused by B" "story:    T-B" "$r"
# CLAUDE_PROJECT_DIR as the host spells it on Windows, with backslashes. Added
# on returning to RED: the IDLE root's worktree listing globbed through a
# backslash, which a glob reads as an escape, and found no worktree at all.
r="$(guard "$H035_ABS" Write file_path "$H035_B/src/main.ts")"
assert_contains "AC-2: with A IDLE and spelled with backslashes, Write <B>/src/main.ts is refused by B" "story:    T-B" "$r"

# Controls: B's lock, not a blanket refusal.
h035_state "$H035_A" T-A RED
h035_state "$H035_B" T-B ""
assert_eq "AC-2 control: B IDLE allows <B>/src/main.ts though A is in RED" "" \
  "$(h035_reason Write file_path "$H035_B/src/main.ts")"
h035_state "$H035_B" T-B GREEN
assert_eq "AC-2 control: B GREEN allows <B>/src/main.ts though A is in RED" "" \
  "$(h035_reason Write file_path "$H035_B/src/main.ts")"
r="$(h035_reason Write file_path "$H035_B/tests/main.test.ts")"
assert_contains "AC-2 control: and B GREEN refuses <B>/tests/main.test.ts, as GREEN" "phase:    GREEN" "$r"
# And A's own lock is untouched by all of this.
r="$(h035_reason Write file_path "$H035_A/src/main.ts")"
assert_contains "AC-2 control: <A>/src/main.ts is still refused by A" "story:    T-A" "$r"
assert_not_contains "AC-2 control: with no worktree line for the session's own tree" "worktree:" "$r"

describe "HARNESS-035 AC-3: a worktree nested under the root is its own tree"

h035_state "$H035_A" T-A GREEN
h035_state "$H035_W" T-W RED
r="$(h035_reason Write file_path "$H035_W/src/main.ts")"
assert_contains "AC-3: Write <A>/.claude/worktrees/w/src/main.ts is refused by W" "story:    T-W" "$r"
assert_contains "AC-3: on W's relative path" "path:     src/main.ts" "$r"
r="$(h035_reason Bash command 'cd .claude/worktrees/w && echo x > src/main.ts')"
assert_contains "AC-3: cd .claude/worktrees/w && echo x > src/main.ts is refused by W" "story:    T-W" "$r"
h035_state "$H035_W" T-W GREEN
h035_state "$H035_A" T-A RED
assert_eq "AC-3 control: W GREEN allows its src/main.ts though A is in RED" "" \
  "$(h035_reason Write file_path "$H035_W/src/main.ts")"

describe "HARNESS-035 AC-4: another repository, or a same-named folder, is still outside"

h035_state "$H035_A" T-A RED
h035_state "$H035_C" T-C RED
assert_eq "AC-4: Write into a separate repository's src from A is allowed" "" \
  "$(h035_reason Write file_path "$H035_C/src/main.ts")"
assert_eq "AC-4: so is a Bash redirect into it" "" \
  "$(h035_reason Bash command "echo x > $H035_C/src/main.ts")"
# The folder-name fallback: a directory elsewhere that merely shares A's name.
assert_eq "AC-4: C:\\elsewhere\\<A's name>\\src\\main.ts is not A's src" "" \
  "$(h035_reason Write file_path "C:\\elsewhere\\${H035_A##*/}\\src\\main.ts")"
summary "phase-guard"
