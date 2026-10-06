#!/usr/bin/env bash
# Tests for scripts/classify.sh - the path classifier, reachable from test code
# written in any language.
#
# Why this script exists. `classify` is a bash function in .claude/hooks/lib.sh,
# so the only consumer that could reach it was another bash script - which meant
# a project's own guards, written in the project's language, rolled their own
# idea of "a source module" in a private regex. One project ended up with FOUR
# private copies, two of which had drifted apart, and all four were returning
# deliberately-offending probe artifacts as production source. They had been
# doing that for six stories: the guards asserted their property over files
# written to violate a rule, and passed only because the rule violated was not
# the rule being asserted.
#
# So the contract here is narrow and the tests are about the contract: one
# answer, the same answer the phase lock would give, available to anything that
# can run a command and read a line.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
# HARNESS-031 builds its own fixtures (C-3: never append a rule to the shared FIX,
# or every later block inherits it); each is added here as it is made.
H031_FIXES=""
trap 'rm -rf "$FIX" $H031_FIXES' EXIT

cls() { ( cd "$FIX" && bash scripts/classify.sh "$@" 2>&1 ); }

# ---------------------------------------------------------------------------
describe "paths as arguments"

assert_eq "a source module" "source	src/main.ts"       "$(cls src/main.ts)"
assert_eq "a test file"     "test	tests/main.test.ts" "$(cls tests/main.test.ts)"
assert_eq "a doc"           "docs	docs/notes.md"      "$(cls docs/notes.md)"

# Several at once, in the order given - a guard classifying a whole tree wants
# one process, not one per file.
assert_eq "several, in order" "source	src/main.ts
test	tests/main.test.ts" "$(cls src/main.ts tests/main.test.ts)"

# ---------------------------------------------------------------------------
describe "paths on stdin"

# The form a scanner in another language reaches for: pipe it a file list.
got="$( cd "$FIX" && printf 'src/main.ts\ndocs/notes.md\n' | bash scripts/classify.sh 2>&1 )"
assert_eq "stdin, one path per line" "source	src/main.ts
docs	docs/notes.md" "$got"

# ---------------------------------------------------------------------------
describe "--only filters to one category"

# No category column here: the output is a file list, which is what the caller
# is going to iterate. Adding a column they have to strip is how a helper gets
# reimplemented.
assert_eq "--only source" "src/main.ts" "$(cls --only source src/main.ts tests/main.test.ts docs/notes.md)"
assert_eq "--only test"   "tests/main.test.ts" "$(cls --only test src/main.ts tests/main.test.ts)"
assert_eq "--only with no match is empty, not an error" "" "$(cls --only config src/main.ts)"

# ---------------------------------------------------------------------------
describe "--list enumerates the tree the way the lock sees it"

# The whole point: a guard asking "every source file under src/" gets the
# classifier's answer, not a fourth regex. It enumerates through git - tracked
# files AND untracked ones that are not ignored - so a module written five
# minutes ago is still seen. Probes are excluded by CLASSIFICATION, never by
# tracking status: a scanner that skipped untracked files would quietly stop
# checking every new module, which is the vacuous pass this repository keeps
# warning about.
printf 'export const y = 2\n' > "$FIX/src/other.ts"
got="$(cls --list source src)"
assert_contains "an untracked new module is still source" "src/other.ts" "$got"
assert_contains "and so is the tracked one"               "src/main.ts"  "$got"
case "$got" in
  *tests/*|*docs/*) _bad "--list source excludes other categories" "leaked: $got" ;;
  *) _ok "--list source excludes other categories" ;;
esac

# INSTALLED DEPENDENCIES ARE NOT THE TREE. The enumeration is
# `git ls-files --cached --others --exclude-standard`, and that last flag is the
# only thing keeping untracked-but-ignored files out of it. Dropping it left
# every assertion in this suite green while `--list` began handing callers
# `node_modules` - which is precisely the "a guard scanning the wrong file set"
# failure classify.sh exists to prevent, arriving through the tool built to
# prevent it.
#
# ASSERTED ON `--list vendor`, and the reason is the trap. A `node_modules`
# path classifies as `vendor`, never as `source`, so `--list source` cannot
# return one whether the flag is there or not - an assertion written against
# `source` passes for a reason that has nothing to do with what it claims, and
# survives the mutation it was written to kill. Measured before being believed:
#   classify node_modules/left-pad/index.js  -> vendor
#   --list vendor, with the flag             -> nothing
#   --list vendor, without it                -> node_modules/left-pad/index.js
mkdir -p "$FIX/node_modules/left-pad"
printf 'module.exports = 1\n' > "$FIX/node_modules/left-pad/index.js"
printf 'export const z = 3\n'  > "$FIX/src/fresh.ts"
case "$(cls --list vendor)" in
  *node_modules*) _bad "--list never returns an ignored dependency tree" "node_modules came back" ;;
  *) _ok "--list never returns an ignored dependency tree" ;;
esac
got="$(cls --list source)"
# THE CONTROL, and the reason the fix cannot be "skip untracked files": a module
# written five minutes ago and not yet committed is still source, and a scanner
# that quietly stopped seeing new modules would be the same defect pointing the
# other way.
assert_contains "while an untracked, non-ignored module still is" "src/fresh.ts" "$got"
rm -rf "$FIX/node_modules" "$FIX/src/fresh.ts"

# ---------------------------------------------------------------------------
describe "a probe artifact is not a source module"

# THE case this was built for. A guard that tests a lint RULE - rather than
# today's imports - has to write a deliberately offending module into the real
# tree, because path-scoped lint overrides mean a probe linted from a temp
# directory is linted under the wrong rules. So probes live under src/, and
# every tree-scanning guard must skip them. Name them per the convention and
# both the scanner and the phase lock agree, from one rule in paths.conf.
printf 'import "../core/nope"\n' > "$FIX/src/__import_guard_probe.ts"
assert_eq "a probe classifies as test" "test	src/__import_guard_probe.ts" \
  "$(cls src/__import_guard_probe.ts)"
got="$(cls --list source src)"
case "$got" in
  *__import_guard_probe*) _bad "--list source skips probes" "the probe came back as source: $got" ;;
  *) _ok "--list source skips probes" ;;
esac
# Both directions, because an exclusion that is too broad is the second-order
# trap: a real module is still source even when its name contains the word.
assert_contains "and a real module is still listed" "src/main.ts" "$got"
assert_eq "a module merely named 'probe' is source" "source	src/heat_probe.ts" \
  "$(cls src/heat_probe.ts)"

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
describe "the category list cannot drift from paths.conf"

# The bug this closes, found by a mutation audit: classify.sh printed `manifest`
# for Cargo.toml and then refused `--only manifest` as an unknown category. The
# whitelist was a hand-copied list, and when paths.conf gained `manifest` the
# copy did not. A script that contradicts itself in two lines is worse than one
# with no validation, because the validation is what you trust.
#
# So it is derived from paths.conf now, plus the four the classifier produces
# without a rule. Deriving is the fix; a longer copy would just drift later.
assert_eq "--only manifest is accepted" "Cargo.toml" "$(cls --only manifest Cargo.toml src/main.ts)"
printf "[package]
" > "$FIX/Cargo.toml"
assert_contains "and --list manifest" "Cargo.toml" "$(cls --list manifest .)"
assert_contains "the usage lists it too" "manifest" "$(cls --only 2>&1)"

# A category invented in paths.conf is accepted without touching this script.
printf 'weird | src/weird/**\n' >> "$FIX/.claude/harness/paths.conf"
mkdir -p "$FIX/src/weird" && printf 'x\n' > "$FIX/src/weird/thing.ts"
assert_eq "a category added to paths.conf needs no code change" "weird	src/weird/thing.ts" \
  "$(cls src/weird/thing.ts)"
assert_eq "and filters by it"  "src/weird/thing.ts" "$(cls --only weird src/weird/thing.ts src/main.ts)"

# Still refuses a real typo, which is the whole point of having a list: a
# mistyped --only returns nothing, and nothing reads exactly like "this tree has
# no such files".
out="$(cls --only sources src/main.ts 2>&1)"; rc=$?
assert_eq "a typo is still refused" 2 "$rc"
assert_contains "and named" "sources" "$out"
describe "it refuses what it cannot answer"

out="$(cls --only 2>&1)"; rc=$?
assert_eq "--only with no category is a usage error" 2 "$rc"
out="$(cls --nonsense src/main.ts 2>&1)"; rc=$?
assert_eq "an unknown option is a usage error" 2 "$rc"
assert_contains "and says so" "usage" "$(printf '%s' "$out" | tr 'A-Z' 'a-z')"


# ---------------------------------------------------------------------------
describe "HARNESS-011: a bare directory name classifies as its own category"

# A rule written `docs | docs/**` matches paths UNDER docs and never `docs`
# itself, so every bare directory name fell through to the documented `source`
# fallback. Measured at release 49, before the fix:
#
#   docs  tests  test  spec  __tests__  .claude  scripts  .github  -> source
#
# Wrong in both directions, in different phases. `source` is writable in GREEN
# and GATES, so a bare `tests` was writable in exactly the phases that freeze
# tests - `rm -rf tests` was PERMITTED in GREEN. And `source` is frozen in RED
# and REVIEW, so `rm -rf docs` and `rm -rf .claude` were REFUSED in RED, where
# both categories are writable.
#
# Vendor already carries both forms, under a comment in paths.conf saying
# exactly why. This is that treatment for the three categories that lacked it.
# The end-to-end half - the same paths through the real hook - is in
# phase-guard.test.sh; asserted here too because this is where the answer is
# DECIDED, and a classifier assertion says which rule was wrong.

assert_eq "bare docs is docs"       "docs	docs"       "$(cls docs)"
assert_eq "bare scripts is harness" "harness	scripts"    "$(cls scripts)"
assert_eq "bare .claude is harness" "harness	.claude"    "$(cls .claude)"
assert_eq "bare .github is harness" "harness	.github"    "$(cls .github)"
assert_eq "bare tests is test"      "test	tests"      "$(cls tests)"
assert_eq "bare test is test"       "test	test"       "$(cls test)"
assert_eq "bare spec is test"       "test	spec"       "$(cls spec)"
assert_eq "bare __tests__ is test"  "test	__tests__"  "$(cls __tests__)"

# Each bare form keeps its OWN rule's anchoring, because it sits inside its own
# category's block rather than in one collected block at the end. The test
# rules are `**/`-prefixed and reach a nested directory; the docs rule is
# root-anchored and does not.
assert_eq "a nested bare tests directory is still test" "test	packages/app/tests" \
  "$(cls packages/app/tests)"
assert_eq "but a nested 'docs' is not docs, as its rule is root-anchored" \
  "source	src/docs" "$(cls src/docs)"

# The precedent, asserted so that removing it is a failure rather than a
# silent regression. Vendor has had both forms since somebody first hit this.
assert_eq "vendor already had bare forms, and keeps them" "vendor	node_modules" \
  "$(cls node_modules)"
assert_eq "and so does target" "vendor	target" "$(cls target)"

# THE CONTROLS, and they matter as much as the positives: a fix that made
# every bare name match something would satisfy all eight assertions above and
# destroy the fallback that makes the phase lock fail closed. `src` is a real
# source directory; `wibble` matches no rule at all, and paths.conf's own
# header says that is the right answer for a file about to be authored.
assert_eq "the control: bare src is still source"    "source	src"    "$(cls src)"
assert_eq "the control: an invented name is still source" "source	wibble" "$(cls wibble)"

# THE ACCEPTED TRADE, asserted so it is a recorded decision rather than a
# surprise found later. `test | **/test` matches a FILE named `test` as well as
# a directory, because the classifier sees a string and not an inode - it is
# asked about paths that do not exist yet. Vendor has carried exactly this
# property since its bare forms were added (`**/node_modules` matches a file of
# that name). C-3 of HARNESS-011 says do not try to fix it here.
printf 'not a directory\n' > "$FIX/test"
assert_eq "a FILE named test classifies as test: the accepted trade" "test	test" \
  "$(cls test)"
rm -f "$FIX/test"

# ---------------------------------------------------------------------------
describe "HARNESS-031: a bare path no rule matches takes its slashed form's category"

# HARNESS-011 closed the bare-directory hole by writing every built-in rule
# twice (`docs/**` AND `docs`). A PROJECT's own rule gets no twin unless its
# author remembers one, and manga-translator's `test | fixtures/**` is exactly
# that case: bare `fixtures` fell to `source`. Even the built-in twins are
# incomplete - `**/.pytest_cache/**`, `**/.tox/**` and `**/.next/**` have no
# bare form. The settled fix (port audit, Decided 5): a bare path that matches
# NO rule is judged again with one trailing `/`, so any rule `X/**` covers `X`.
#
# Each extra-rule fixture is its own tree (C-3). Measured at 16c42a1, before
# the retry: `fixtures`, `pkg/golden`, `.pytest_cache` and `.tox` -> source,
# `.next` (gitignored as `.next/`) -> ignored.
H031A="$(make_project_fixture)"; H031_FIXES="$H031_FIXES $H031A"
printf '%s\n' 'test | fixtures/**' >> "$H031A/.claude/harness/paths.conf"
clsa() { ( cd "$H031A" && bash scripts/classify.sh "$@" 2>&1 ); }

# AC-3 - rule-driven, never child-driven. Nothing named `fixtures` exists on
# disk in this fixture: the retry reads rules, not the filesystem.
assert_eq "AC-3: bare fixtures takes the category of its fixtures/** rule" \
  "test	fixtures" "$(clsa fixtures)"
# THE CONTROLS. A retry that made every bare name match something would pass
# the positive above and destroy the fail-closed `source` fallback.
assert_eq "AC-3 control: bare src is still source"            "source	src"    "$(clsa src)"
assert_eq "AC-3 control: an invented bare name is still source" "source	wibble" "$(clsa wibble)"
# `fixtures/**` is root-anchored, and the retry keeps each rule's anchoring: it
# appends a slash to the PATH, it does not loosen the RULE.
assert_eq "AC-3 control: a nested lib/fixtures is not reached by a root-anchored rule" \
  "source	lib/fixtures" "$(clsa lib/fixtures)"
# A `**/`-prefixed project rule reaches a nested bare directory.
printf '%s\n' 'test | **/golden/**' >> "$H031A/.claude/harness/paths.conf"
assert_eq "AC-3: a nested bare pkg/golden takes the category of **/golden/**" \
  "test	pkg/golden" "$(clsa pkg/golden)"

# A built-in rule with no twin, against the REAL paths.conf - a fresh fixture,
# so no extra rule is in play. Neither name is gitignored in it.
H031R="$(make_project_fixture)"; H031_FIXES="$H031_FIXES $H031R"
clsr() { ( cd "$H031R" && bash scripts/classify.sh "$@" 2>&1 ); }
assert_eq "AC-3: bare .pytest_cache is vendor under the real paths.conf, with no twin" \
  "vendor	.pytest_cache" "$(clsr .pytest_cache)"
assert_eq "AC-3: bare .tox is vendor under the real paths.conf, with no twin" \
  "vendor	.tox" "$(clsr .tox)"

# AC-4 - an explicit rule for the bare form always wins. The retry fires when NO
# RULE matched, not when the answer happens to be `source`: here a rule says
# `source` for bare `gen`, and `gen/**` must not override it. Passes on
# arrival (no retry exists to get it wrong); DV-2 earns it by putting back
# downstream's `c == "source"` heuristic.
H031G="$(make_project_fixture)"; H031_FIXES="$H031_FIXES $H031G"
printf '%s\n' 'source | gen' 'test | gen/**' >> "$H031G/.claude/harness/paths.conf"
clsg() { ( cd "$H031G" && bash scripts/classify.sh "$@" 2>&1 ); }
assert_eq "AC-4: an explicit source rule for bare gen beats the retry onto gen/**" \
  "source	gen" "$(clsg gen)"
# The control that makes the line above mean something: the gen/** rule is
# live in this fixture, so the retry WOULD reach it if it fired.
assert_eq "AC-4 control: the gen/** rule is live (gen/x.ts is test)" \
  "test	gen/x.ts" "$(clsg gen/x.ts)"

# The order is rules on the bare form, rules on the slashed form, .gitignore,
# then source. `.next/` is gitignored here and `**/.next/**` is a rule: the
# rule wins, as it already does for `dist`.
printf '%s\n' '.next/' >> "$H031A/.gitignore"
git -C "$H031A" add -A >/dev/null 2>&1
if git -C "$H031A" check-ignore -q -- .next/ 2>/dev/null; then
  _ok "AC-4 control: .next/ is gitignored in the fixture (precondition)"
else _bad "AC-4 control: .next/ is gitignored in the fixture (precondition)" \
  "git check-ignore .next/ said not ignored - the assertion below would separate nothing"; fi
assert_eq "AC-4: a slashed-form rule beats .gitignore - bare .next is vendor, not ignored" \
  "vendor	.next" "$(clsa .next)"

# AC-5 - one implementation. classify_stdin itself, sourced against the
# fixture as spawns.test.sh does: every caller of it (the gate hash, the diff
# classifiers) gets the same answer as classify(). One output line per input
# line, in order, each path AS GIVEN - no `/` appended.
got="$( export CLAUDE_PROJECT_DIR="$H031A"
        . "$H031A/.claude/hooks/lib.sh"
        printf '%s\n' fixtures src fixtures/a.json .pytest_cache | classify_stdin )"
assert_eq "AC-5: classify_stdin retries per line, in order, printing each path as given" \
  "test	fixtures
source	src
test	fixtures/a.json
vendor	.pytest_cache" "$got"
got="$( export CLAUDE_PROJECT_DIR="$H031A"
        . "$H031A/.claude/hooks/lib.sh"
        printf '%s\n' fixtures/ | classify_stdin )"
assert_eq "AC-5 control: an already-slashed fixtures/ is one line, unchanged" \
  "test	fixtures/" "$got"
summary "classify"
