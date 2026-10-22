#!/usr/bin/env bash
# Consistency suite for the stack profiles in
# .claude/skills/stack-profiles/reference/.
#
# `new-profile.md` says what a profile must contain. Nothing enforced it, and
# the drift was immediate: the round that added the `--fast` requirement left
# four of the five shipped profiles violating it, and three profiles had been
# missing the `discovery` requirement since it was written. A profile is copied
# verbatim into a real project's project.conf, so a `slow` line naming a gate
# that does not exist, or a `floor` with nothing to measure, is not a
# documentation nit - it is a manifest error that arrives pre-installed.
#
# These are the same rules `gates.sh --audit` applies to a real project.conf,
# applied to the examples that teach people how to write one.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

PROFILE_DIR="$REPO_ROOT/.claude/skills/stack-profiles/reference"

# is_profile <file>   A reference file that CONFIGURES gates, as opposed to one
# that talks about them. Self-identifying, so a new reference page about, say,
# environments does not have to be added to an exclusion list here to avoid
# failing rules that were never meant for it.
is_profile() { [ -f "$1" ] && grep -qE '^[[:space:]]*gate[[:space:]]*\|' "$1"; }

# The field logic every reader of a profile line shares. ONE copy, prepended to
# each awk program below, so that profile_problems and mutation_regex cannot
# read the same line two ways (HARNESS-041 AC-3).
PROFILE_FIELDS='
    function t(s) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", s); return s }
    # Everything from field n on, rejoined: an evidence regex may contain `|`
    # as alternation, or `[|]` / `[^|]` as a bracket expression, and a
    # discovery line is a shell pipeline. gates.sh reads it the same way
    # (`rest 3`, "so that a regex containing `|` survives").
    function rest(n,   i, o) { o = $n; for (i = n + 1; i <= NF; i++) o = o "|" $i; return t(o) }
'

# profile_problems <file>   "<check><TAB><message>" per violation; silent when
# the profile is consistent.
profile_problems() {
  awk "$PROFILE_FIELDS"'
    BEGIN { FS = "|"; nreq = split("lint typecheck unit coverage build", REQ, " ") }

    /^[[:space:]]*gate[[:space:]]*\|/ {
      id = t($2)
      gates[id] = 1
      if (t($3) == "required") required[id] = 1
      if (rest(5) != "") configured[id] = 1
      next
    }
    # HARNESS-041 C-1: keep the regex, not only its presence - a `-` or an
    # empty regex is a declaration that there is nothing to match.
    /^[[:space:]]*evidence[[:space:]]*\|/  { ev[t($2)] = 1; evre[t($2)] = rest(3); next }
    /^[[:space:]]*floor[[:space:]]*\|/     { fl[t($2)] = 1; next }
    /^[[:space:]]*discovery[[:space:]]*\|/ { ndisc++; next }
    /^[[:space:]]*slow[[:space:]]*\|/      { id = t($2); slow[id] = 1; why[id] = rest(3); next }
    # HARNESS-015: `ondemand | <id> | <why>` marks a gate a full run leaves out
    # until somebody asks for it (--gate <id>, or the story frontmatter).
    # Parsed like `slow`, and judged by the same two rules: it must name a
    # gate the profile configures, and it must say why.
    /^[[:space:]]*ondemand[[:space:]]*\|/  { id = t($2); ondemand[id] = 1; owhy[id] = rest(3); next }
    # HARNESS-055: `no-count | <id> | <why>` declares that the evidence regex of
    # a gate proves liveness and measures nothing, so a floor on it compares
    # against a stopwatch. Parsed like `slow`; judged by the same two rules plus
    # the refusal of a floor beside it.
    /^[[:space:]]*no-count[[:space:]]*\|/  { id = t($2); nc[id] = 1; ncwhy[id] = rest(3); next }
    /What `--fast` should leave out/       { fastsec = 1 }

    END {
      for (i = 1; i <= nreq; i++)
        if (!(REQ[i] in gates))
          print "required-gates\tdoes not configure a `" REQ[i] "` gate at all"

      for (id in configured)
        if ((id in required) && !(id in ev))
          print "evidence\trequired gate `" id "` has a command but no evidence line, so a vacuous pass would go unnoticed"

      for (id in ev)   if (!(id in gates)) print "orphan\tevidence names `" id "`, which this profile does not configure"
      for (id in fl)   if (!(id in gates)) print "orphan\tfloor names `"    id "`, which this profile does not configure"
      for (id in slow) if (!(id in gates)) print "orphan\tslow names `"     id "`, which this profile does not configure"
      for (id in ondemand) if (!(id in gates)) print "orphan\tondemand names `" id "`, which this profile does not configure"
      for (id in nc)   if (!(id in gates)) print "orphan\tno-count names `" id "`, which this profile does not configure"

      for (id in fl)
        if (!(id in ev))
          print "floor\tfloor on `" id "` has no evidence line to measure it out of"

      # The same refusal gates.sh makes: a floor measured out of a regex that
      # was declared to measure nothing compares against a stopwatch.
      for (id in fl)
        if (id in nc)
          print "floor\tfloor on `" id "` is declared no-count, so there is no count to compare against"

      for (id in nc)
        if (ncwhy[id] == "")
          print "no-count\t`" id "` is marked no-count with no reason"

      for (id in slow)
        if (why[id] == "")
          print "slow\t`" id "` is marked slow with no reason"

      for (id in ondemand)
        if (owhy[id] == "")
          print "ondemand\t`" id "` is marked on request with no reason"

      # HARNESS-015 AC-3: a profile that configures a `mutation` gate marks it on
      # request. `slow` only keeps it out of --fast; without this line every full
      # gates.sh run - each GATES phase and each PR CI job - runs the mutation
      # tool, which is the per-story cost the story exists to remove.
      if (("mutation" in gates) && !("mutation" in ondemand))
        print "mutation-ondemand\tconfigures a `mutation` gate with no `ondemand | mutation | <why>` line, so every full run executes it"

      # HARNESS-041 AC-1: and it carries an evidence line with a real regex. A
      # mutation tool always prints a count, so `-` (nothing to match) is not
      # an honest declaration for it, and without a regex gates.sh reports a
      # runner that tested nothing as PASS. Keyed on the id `mutation` only,
      # the same limit as gates.sh --audit (HARNESS-039 AC-4b).
      if (("mutation" in gates) && (!("mutation" in ev) || evre["mutation"] == "-" || evre["mutation"] == ""))
        print "mutation-evidence\tconfigures a `mutation` gate with no `evidence | mutation | <regex>` line, so a runner that tests nothing passes it"

      if (!fastsec) print "fast-section\tno `## What --fast should leave out` section; new-profile.md requires one"
      if (ndisc == 0) print "discovery\tno `discovery` line; nothing asks the runner what it can actually see"
    }
  ' "$1"
}

# ---------------------------------------------------------------------------
# A suite that finds no profiles passes silently and proves nothing - the exact
# vacuous pass this harness exists to catch. Assert it found some first.
describe "the profiles are where the suite thinks they are"

found=0
for f in "$PROFILE_DIR"/*.md; do
  [ -e "$f" ] || continue
  is_profile "$f" && found=$((found + 1))
done
if [ "$found" -ge 4 ]; then
  _ok "found $found stack profiles"
else
  _bad "found $found stack profiles" "expected at least 4; has $PROFILE_DIR moved, or has the gate-line format changed?"
fi

# new-profile.md describes profiles rather than being one. If it ever starts
# matching, the heuristic above has stopped discriminating and every assertion
# below is being applied to a template full of placeholders.
if [ ! -f "$PROFILE_DIR/new-profile.md" ]; then
  _bad "new-profile.md is not itself a profile" "new-profile.md is missing; the rules these assertions enforce live there"
elif is_profile "$PROFILE_DIR/new-profile.md"; then
  _bad "new-profile.md is not itself a profile" "it now matches is_profile; the heuristic no longer discriminates"
else
  _ok "new-profile.md is not itself a profile"
fi

# ---------------------------------------------------------------------------
# has_mutation_gate <file>   Does this profile configure a `mutation` gate?
# The same line shape is_profile reads, narrowed to one id.
has_mutation_gate() { grep -qE '^[[:space:]]*gate[[:space:]]*\|[[:space:]]*mutation[[:space:]]*\|' "$1"; }

# ---------------------------------------------------------------------------
describe "the checker recognises an ondemand line (HARNESS-015, C-5)"

# The checker is this file's own instrument, so it is checked against fixtures
# before it is pointed at the profiles: an `ondemand` rule that never fires
# would leave every per-profile assertion below green and empty.
WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
ondemand_probs() { # <check id>   the checker's lines for one check, over $WORK/p.md
  profile_problems "$WORK/p.md" | awk -F'\t' -v c="$1" '$1 == c { print $2 }'
}
base_profile() { # a profile with a mutation gate and every other rule satisfied
  cat > "$WORK/p.md" <<'EOF'
    gate | lint      | required | . | x lint
    gate | typecheck | required | . | x check
    gate | unit      | required | . | x test
    gate | coverage  | required | . | x cov
    gate | build     | required | . | x build
    gate | mutation  | optional | . | x mutants
    evidence | lint | .
    evidence | typecheck | .
    evidence | unit | .
    evidence | coverage | .
    evidence | build | .
    discovery | unit | x list
## What `--fast` should leave out
    slow | build | slow
EOF
}
base_profile
assert_eq "a mutation gate with no ondemand line is reported" \
  "configures a \`mutation\` gate with no \`ondemand | mutation | <why>\` line, so every full run executes it" \
  "$(ondemand_probs mutation-ondemand)"
base_profile; printf '    ondemand | mutation | costs a full suite per mutant\n' >> "$WORK/p.md"
assert_eq "with the line, the checker is silent on every ondemand rule" "" \
  "$(profile_problems "$WORK/p.md" | awk -F'\t' '$1 == "mutation-ondemand" || $1 == "ondemand" || $1 == "orphan" { print }')"
base_profile; printf '    ondemand | mutatoin | a typo\n' >> "$WORK/p.md"
assert_eq "an ondemand line naming no gate is an orphan" \
  "ondemand names \`mutatoin\`, which this profile does not configure" "$(ondemand_probs orphan)"
base_profile; printf '    ondemand | mutation |\n' >> "$WORK/p.md"
assert_eq "an ondemand line with no reason is reported" \
  "\`mutation\` is marked on request with no reason" "$(ondemand_probs ondemand)"

# ---------------------------------------------------------------------------
describe "the checker requires a mutation gate's evidence line (HARNESS-041, AC-1)"

# A mutation tool always prints a count, so a `mutation` gate with no evidence
# line - or with `-`, the declaration that no output exists - is one a runner
# that tests nothing passes (issue #104: 85.79% from a vitest runner that ran no
# tests). The message is C-3's, byte for byte. Fixtures first, for the same
# reason as the ondemand block above: a rule that never fires would leave every
# per-profile assertion below green and empty.
MUT_EVIDENCE_MSG="configures a \`mutation\` gate with no \`evidence | mutation | <regex>\` line, so a runner that tests nothing passes it"
base_profile
assert_eq "AC-1: a mutation gate with no evidence line is reported, once, in C-3's words" \
  "$MUT_EVIDENCE_MSG" "$(ondemand_probs mutation-evidence)"
base_profile; printf '    evidence | mutation | -\n' >> "$WORK/p.md"
assert_eq "AC-1: an evidence line of '-' for the mutation gate is reported the same way" \
  "$MUT_EVIDENCE_MSG" "$(ondemand_probs mutation-evidence)"
base_profile; printf '    evidence | mutation |\n' >> "$WORK/p.md"
assert_eq "AC-1: an evidence line with an empty regex for the mutation gate is reported the same way" \
  "$MUT_EVIDENCE_MSG" "$(ondemand_probs mutation-evidence)"
base_profile; printf '    evidence | mutation | [1-9][0-9]* caught\n' >> "$WORK/p.md"
assert_eq "AC-1 control: with a killed-count regex the checker is silent on mutation-evidence" "" \
  "$(ondemand_probs mutation-evidence)"
# Control from the other side: the rule is keyed on a configured `mutation`
# gate, not on the absence of an evidence line in general.
base_profile; awk '!/gate \| mutation/' "$WORK/p.md" > "$WORK/q.md" && mv "$WORK/q.md" "$WORK/p.md"
assert_eq "AC-1 control: a profile with no mutation gate is silent on mutation-evidence" "" \
  "$(ondemand_probs mutation-evidence)"

# ---------------------------------------------------------------------------
describe "the checker recognises a no-count line (HARNESS-055, AC-8)"

# Fixtures first, for the same reason as the two blocks above: the per-profile
# `floor`, `orphan` and `no-count` checks below are silent on a profile that
# carries no no-count line, so a rule that never fires would leave every one of
# them green and empty. base_profile's build gate has evidence `.`.
nocount_rules() { # every floor, orphan and no-count line, over $WORK/p.md
  profile_problems "$WORK/p.md" | awk -F'\t' '$1 == "floor" || $1 == "orphan" || $1 == "no-count" { print }'
}
base_profile; printf '    no-count | build | seconds\n    floor | build | 5\n' >> "$WORK/p.md"
assert_eq "a floor on a gate declared no-count is a floor problem" \
  "floor on \`build\` is declared no-count, so there is no count to compare against" "$(ondemand_probs floor)"
base_profile; printf '    no-count | nope | why\n' >> "$WORK/p.md"
assert_eq "a no-count line naming no configured gate is an orphan" \
  "no-count names \`nope\`, which this profile does not configure" "$(ondemand_probs orphan)"
base_profile; printf '    no-count | build |\n' >> "$WORK/p.md"
assert_eq "a no-count line with no reason is a no-count problem" \
  "\`build\` is marked no-count with no reason" "$(ondemand_probs no-count)"
# Controls. A floor on a gate whose regex really counts is not refused, and a
# well-formed no-count line with no floor beside it is not a problem: without
# these, a checker that fired on every floor, or on every no-count line, would
# pass the three cases above.
base_profile; printf '    floor | unit | 40\n' >> "$WORK/p.md"
assert_eq "control: a floor on a counted gate with no no-count line yields no floor, orphan or no-count line" \
  "" "$(nocount_rules)"
base_profile; printf '    no-count | build | seconds\n' >> "$WORK/p.md"
assert_eq "control: a no-count line with a reason and no floor beside it yields no floor, orphan or no-count line" \
  "" "$(nocount_rules)"

# ---------------------------------------------------------------------------
describe "the profiles whose evidence regex counts nothing say so (HARNESS-055, AC-8)"

# nocount_ids <file>   The ids of its `no-count` lines, sorted, space-joined,
# read with the same field logic profile_problems uses. Without this, deleting
# every no-count line leaves the per-profile checks below green: "every
# no-count line carries a reason" is satisfied by a profile carrying none.
nocount_ids() {
  awk "$PROFILE_FIELDS"'
    BEGIN { FS = "|" }
    /^[[:space:]]*no-count[[:space:]]*\|/ { print t($2) }
  ' "$1" | sort | tr '\n' ' ' | sed 's/ $//'
}
assert_eq "rust-cargo.md declares no-count on exactly build, lint and typecheck (Finished .* profile is a stopwatch)" \
  "build lint typecheck" "$(nocount_ids "$PROFILE_DIR/rust-cargo.md")"
assert_eq "node-typescript.md declares no-count on exactly build (built in [0-9] is a stopwatch)" \
  "build" "$(nocount_ids "$PROFILE_DIR/node-typescript.md")"
assert_eq "python-uv.md declares no-count on exactly build (Successfully built is followed by a version)" \
  "build" "$(nocount_ids "$PROFILE_DIR/python-uv.md")"
assert_eq "web-static.md declares no-count on exactly build (built in is a stopwatch)" \
  "build" "$(nocount_ids "$PROFILE_DIR/web-static.md")"

# ---------------------------------------------------------------------------
describe "the profiles that configure a mutation gate are the ones expected (HARNESS-015, AC-3)"

# The per-profile assertion below is derived from the files, so a list that came
# back empty would assert nothing and pass. M-3 in the story names three.
lacking=""
for p in node-typescript.md python-uv.md rust-cargo.md; do
  has_mutation_gate "$PROFILE_DIR/$p" || lacking="$lacking $p"
done
assert_eq "node-typescript, python-uv and rust-cargo each configure a mutation gate" "" "$lacking"

# ---------------------------------------------------------------------------
describe "each profile's mutation evidence regex is read off the line, once (HARNESS-041, AC-3)"

# mutation_regex <file>   The `evidence | mutation` regex, read with the same
# field logic profile_problems uses. This is the ONLY place the suite obtains a
# mutation regex: AC-2 below feeds exactly this string to gates.sh, so loosening
# the real profile line is what goes red there (DV-1), not a private copy.
mutation_regex() {
  awk "$PROFILE_FIELDS"'
    BEGIN { FS = "|" }
    /^[[:space:]]*evidence[[:space:]]*\|/ && t($2) == "mutation" { print rest(3) }
  ' "$1"
}
# The line as grep sees it, with `evidence | mutation |` and the surrounding
# space taken off: the independent reading AC-3 compares against.
mutation_line_view() {
  grep -E '^[[:space:]]*evidence[[:space:]]*\|[[:space:]]*mutation[[:space:]]*\|' "$1" \
    | sed -E 's/^[[:space:]]*evidence[[:space:]]*\|[[:space:]]*mutation[[:space:]]*\|[[:space:]]*//; s/[[:space:]]+$//'
}
for p in node-typescript.md python-uv.md rust-cargo.md; do
  n="$(mutation_line_view "$PROFILE_DIR/$p" | awk 'END { print NR }')"
  assert_eq "AC-3: $p has exactly one evidence | mutation line" 1 "$n"
  got="$(mutation_regex "$PROFILE_DIR/$p")"
  assert_eq "AC-3: the regex the suite extracts from $p is byte-identical to the line" \
    "$(mutation_line_view "$PROFILE_DIR/$p")" "${got:-<nothing extracted>}"
done

# ---------------------------------------------------------------------------
describe "each profile's mutation regex requires a killed count, judged by the real gates.sh (HARNESS-041, AC-2)"

# One project fixture, one conf per verdict. The gate is `required` so that a
# non-match prints FAIL rather than an optional gate's WARN (C-2, measured at
# PLANNED). `printf '%s\n' '<line>'` keeps `|`, `*` and the emoji literal
# through gates.sh's eval. --gate runs the gate by name and records nothing.
# No `ondemand` line: gates.sh refuses a gate that is both on request and
# required ("an on-request gate cannot be required"), and --gate needs neither
# (C-2 as amended in RED).
MFIX="$(make_project_fixture)"
trap 'rm -rf "$WORK" "$MFIX"' EXIT

# mutation_gate_verdict <profile file> <canned line>   gates.sh's verdict line
# for the mutation gate, normalised to "<OUTCOME> mutation, <reason>" (the
# duration and a failing gate's " -> <kept log path>" dropped), or
# "<OUTCOME> mutation" when there is no reason; or a
# bracketed note when the profile has no regex to judge with.
mutation_gate_verdict() {
  local re q="'"
  re="$(mutation_regex "$1")"
  if [ -z "$re" ]; then printf '<no evidence | mutation regex in %s>' "$(basename "$1")"; return; fi
  printf '%s\n' \
    "gate     | mutation | required | . | printf ${q}%s\\n${q} ${q}$2${q}" \
    "evidence | mutation | $re" | write_conf "$MFIX"
  ( cd "$MFIX" && bash scripts/gates.sh --gate mutation 2>&1 ) \
    | awk '/^[A-Z][A-Z ]* +mutation( |$)/' \
    | sed -E -e 's/\) -> \.claude\/state\/gate-logs\/[^ ]*$/)/' \
             -e 's/^([A-Z]+) +mutation \([0-9]+s(, observed [0-9]+)?\)$/\1 mutation/' \
             -e '/^[A-Z]+ +mutation \([0-9]+s, /{' \
             -e 's/^([A-Z]+) +mutation \([0-9]+s, /\1 mutation, /' -e 's/\)$//' -e '}'
  # No `.*` over the reason: it quotes the regex, which for python-uv holds a
  # 4-byte emoji, and MSYS sed under LC_ALL=C.UTF-8 (16-bit wchar_t) would not
  # match `.` across it. Every pattern above touches ASCII only.
}
# expect_pass / expect_fail <profile> <label> <canned line>
expect_pass() {
  assert_eq "AC-2: $1: $2 passes the mutation gate" "PASS mutation" \
    "$(mutation_gate_verdict "$PROFILE_DIR/$1" "$3")"
}
expect_fail() {
  local re; re="$(mutation_regex "$PROFILE_DIR/$1")"
  assert_eq "AC-2: $1: $2 fails the mutation gate as no evidence of work" \
    "FAIL mutation, ran but produced no evidence of work: expected /${re:-<no regex>}/" \
    "$(mutation_gate_verdict "$PROFILE_DIR/$1" "$3")"
}

# C-4's lines, verbatim. The negatives are real shapes, not garbage: a regex
# that matched any line with a digit in it would pass every one of them.
# Stryker's clear-text score table, totals row: score, covered, # killed, ...
expect_pass node-typescript.md "the All files row with 156 killed" \
  'All files         |   85.79 |    85.79 |       156 |         0 |        27 |        0 |        0 |'
expect_fail node-typescript.md "the All files row with 0 killed (0 of 19, issue #104)" \
  'All files         |    0.00 |     0.00 |         0 |         0 |        19 |        0 |        0 |'
expect_fail node-typescript.md "the All files row of a run with nothing in it" \
  'All files | n/a | n/a | 0 | 0 | 0 | 0 | 0 |'

# cargo-mutants' summary line names only the non-zero outcomes.
expect_pass rust-cargo.md "4 caught (measured, cargo-mutants 27.1.0)" \
  '4 mutants tested in 4s: 4 caught'
expect_pass rust-cargo.md "3 caught among missed and unviable" \
  '6 mutants tested in 1m 2s: 2 missed, 3 caught, 1 unviable'
expect_fail rust-cargo.md "a summary with no caught outcome" \
  '3 mutants tested in 20s: 3 missed'
expect_fail rust-cargo.md "a verbose per-mutant 'caught in' line" \
  'src/a.rs:3:5: replace f -> u8 with 1 ... caught in 0.1s'

# mutmut 3's final status line; the killed count follows the party popper.
# Built from octal escapes so the needle is the same bytes under any locale and
# any editor: U+1F389 U+1FAE5 U+23F0 U+1F914 U+1F641 U+1F507 U+1F9D9.
E_KILL="$(printf '\360\237\216\211')"; E_NOTEST="$(printf '\360\237\253\245')"
E_TIME="$(printf '\342\217\260')";     E_SUSP="$(printf '\360\237\244\224')"
E_SURV="$(printf '\360\237\231\201')"; E_SKIP="$(printf '\360\237\224\207')"
E_TYPE="$(printf '\360\237\247\231')"
expect_pass python-uv.md "1000 killed of 1234" \
  "1234/1234  $E_KILL 1000 $E_NOTEST 0  $E_TIME 0  $E_SUSP 0  $E_SURV 234  $E_SKIP 0  $E_TYPE 0"
expect_fail python-uv.md "0 killed of 19" \
  "19/19  $E_KILL 0 $E_NOTEST 0  $E_TIME 0  $E_SUSP 0  $E_SURV 19  $E_SKIP 0  $E_TYPE 0"

# ---------------------------------------------------------------------------
for f in "$PROFILE_DIR"/*.md; do
  [ -e "$f" ] || continue
  is_profile "$f" || continue
  name="$(basename "$f")"
  probs="$(profile_problems "$f")"

  describe "$name"
  check() { # <check id> <label>
    local got
    got="$(printf '%s\n' "$probs" | awk -F'\t' -v c="$1" '$1 == c { print "- " $2 }')"
    assert_eq "$2" "" "$got"
  }
  check required-gates "configures every required gate"
  check evidence       "every required gate with a command has an evidence line"
  check orphan         "no evidence, floor, no-count, slow or ondemand line names an unconfigured gate"
  check floor          "every floor has an evidence line, and a count, to measure"
  check no-count       "every no-count line carries a reason"
  check slow           "every slow line carries a reason"
  check ondemand       "every ondemand line carries a reason"
  check fast-section   "says what --fast should leave out"
  check discovery      "has at least one discovery line"
  # AC-3: named with the profile so the failure reads "<profile>: its mutation
  # gate is on request", which is the control the criterion asks for.
  if has_mutation_gate "$f"; then
    check mutation-ondemand "$name: its mutation gate is on request"
    # HARNESS-041 AC-1, against the real line (DV-2 deletes it).
    check mutation-evidence "$name: its mutation gate has an evidence line"
  fi
done

# ---------------------------------------------------------------------------
# Prose needles (HARNESS-041 AC-4, AC-5). Matched per PARAGRAPH, not per line:
# a sentence that wraps differently is the same sentence, and a per-line
# `grep -c` would count one wrapped needle twice or miss it. A paragraph is a
# run of non-blank lines, joined with single spaces; a leading `#` on a joined
# line (a comment inside an indented block) is dropped with the newline.
paras() { # <text on stdin>   one paragraph per output line
  tr -d '\r' | awk 'BEGIN { RS = "" } { gsub(/\n[[:space:]]*(#[[:space:]]*)?/, " "); print }'
}
count_paras() { # <needle> <text>   how many paragraphs contain the needle
  printf '%s\n' "$2" | paras | awk -v n="$1" 'index($0, n) { c++ } END { print c + 0 }'
}
para_with() { # <needle> <text>   the first paragraph containing the needle
  printf '%s\n' "$2" | paras | awk -v n="$1" 'index($0, n) { print; exit }'
}
line_of() { # <ERE> <file>   the first line number matching, or 0
  awk -v re="$1" '$0 ~ re { print NR; f = 1; exit } END { if (!f) print 0 }' "$2"
}
section() { # <exact heading line> <file>   that section's body, to the next `## `
  tr -d '\r' < "$2" | awk -v h="$1" '$0 == h { on = 1; next } on && /^## / { exit } on'
}

NODE="$PROFILE_DIR/node-typescript.md"
RUST="$PROFILE_DIR/rust-cargo.md"
STACK_SKILL="$REPO_ROOT/.claude/skills/stack-profiles/SKILL.md"
TS7_HEADING='## The mutation gate on TypeScript 7 / Vitest 5'

# ---------------------------------------------------------------------------
describe "node-typescript says how stryker runs on TypeScript 7 / Vitest 5 (HARNESS-041, AC-4)"

# (a) A pointer within the ten lines after the gate line, naming both and
# pointing at the section by its title.
# line_of takes its ERE through `awk -v`, which processes escapes, so a literal
# `|` is written `[|]` rather than `\|` (C-4's reason, here too).
g="$(line_of '^[[:space:]]*gate[[:space:]]*[|][[:space:]]*mutation[[:space:]]*[|]' "$NODE")"
window="$(tr -d '\r' < "$NODE" | awk -v a="$((g + 1))" -v b="$((g + 10))" 'NR >= a && NR <= b')"
assert_eq "AC-4(a): within ten lines of its mutation gate, node-typescript points at the TypeScript 7 / Vitest 5 section, once" \
  1 "$(printf '%s\n' "$window" | tr '\n' ' ' | sed -E 's/ +#? */ /g' \
        | awk '{ print gsub(/The mutation gate on TypeScript 7 \/ Vitest 5/, "") }')"

# (b) The section exists once, in the place C-6(d) gives it, and carries the
# working configuration in ONE block.
assert_eq "AC-4(b): node-typescript has the heading '$TS7_HEADING', once" \
  1 "$(tr -d '\r' < "$NODE" | grep -cxF -- "$TS7_HEADING")"
h_fast="$(line_of '^## What `--fast` should leave out$' "$NODE")"
h_ts7="$(line_of '^## The mutation gate on TypeScript 7 / Vitest 5$' "$NODE")"
h_5000="$(line_of '^## The 5,000 ms default' "$NODE")"
if [ "$h_ts7" -gt "$h_fast" ] && [ "$h_ts7" -lt "$h_5000" ]; then
  _ok "AC-4(b): the section sits after 'What --fast should leave out' and before 'The 5,000 ms default'"
else
  _bad "AC-4(b): the section sits after 'What --fast should leave out' and before 'The 5,000 ms default'" \
    "heading lines: --fast $h_fast, TS7 $h_ts7 (0 = absent), 5,000 ms $h_5000"
fi
TS7_SECTION="$(section "$TS7_HEADING" "$NODE")"
# The first indented (4-space) or fenced block in the section that names
# testRunner; every other key must be in that same block.
config_block="$(printf '%s\n' "$TS7_SECTION" | awk '
  /^(```|~~~)/ { if (!fence) { b++ } fence = !fence; next }
  fence        { blk[b] = blk[b] $0 "\n"; next }
  /^    /      { if (!ind) b++; ind = 1; blk[b] = blk[b] $0 "\n"; next }
  /^[[:space:]]*$/ { next }
               { ind = 0 }
  END { for (i = 1; i <= b; i++) if (index(blk[i], "testRunner")) { printf "%s", blk[i]; exit } }')"
for key in testRunner commandRunner coverageAnalysis timeoutMS tsconfigFile plugins; do
  # The placeholder names no key: a placeholder containing one would satisfy
  # its own needle (it did, once, for testRunner).
  assert_contains "AC-4(b): the section's configuration block sets $key" "$key" "${config_block:-<no configuration block in the section>}"
done

# (c) Every number in it is the reporter's, and it says so.
assert_eq "AC-4(c): the section says 'not re-measured', once" 1 "$(count_paras 'not re-measured' "$TS7_SECTION")"
assert_contains "AC-4(c): the section attributes its measurements to issue #104" "issue #104" "$TS7_SECTION"

# (d) The sentence that read as a claim about the whole evidence block is gone,
# and its replacement says which lines were verified and which were not run.
NODE_TEXT="$(tr -d '\r' < "$NODE")"
assert_eq "AC-4(d): 'Verified against vitest 5 and typescript 5 on Windows.' no longer appears in that spelling" \
  0 "$(count_paras 'Verified against vitest 5 and typescript 5 on Windows.' "$NODE_TEXT")"
assert_eq "AC-4(d): one paragraph says the \`unit\` and \`coverage\` lines were verified" \
  1 "$(count_paras 'The `unit` and `coverage` lines were verified' "$NODE_TEXT")"
verified_para="$(para_with 'The `unit` and `coverage` lines were verified' "$NODE_TEXT")"
assert_contains "AC-4(d): and that the \`mutation\` line was not run" \
  '`mutation` line was not run' "${verified_para:-<no such paragraph>}"
assert_contains "AC-4(d): and that its shape is derived from the reporter source" \
  'reporter source' "${verified_para:-<no such paragraph>}"

# ---------------------------------------------------------------------------
describe "combining two profiles' mutation gates is written down (HARNESS-041, AC-5)"

# The Choosing section, from the "Mixed-stack projects are normal" paragraph to
# the next heading: the convention belongs there, after that sentence.
CHOOSING_TAIL="$(tr -d '\r' < "$STACK_SKILL" | awk '/^Mixed-stack projects are normal/ { on = 1 } on && /^## / { exit } on')"
for needle in 'rust-mutation' '--gate rust-mutation' 'HARNESS-039' 'judge the id `mutation` only'; do
  assert_eq "AC-5: one paragraph after 'Mixed-stack projects are normal' in Choosing names '$needle'" \
    1 "$(count_paras "$needle" "$CHOOSING_TAIL")"
done
combine_para="$(para_with '--gate rust-mutation' "$CHOOSING_TAIL")"
for word in 'evidence' 'slow' 'ondemand' '/audit-mutations' 'gates.sh --audit' 'profiles.test.sh'; do
  assert_contains "AC-5: the combining paragraph names $word" "$word" "${combine_para:-<no paragraph naming --gate rust-mutation>}"
done

# The pointer beside each combinable profile's `ondemand | mutation` line.
for f in "$NODE" "$RUST"; do
  p="$(basename "$f")"
  assert_eq "AC-5: $p says 'Combining this with', once" 1 "$(tr -d '\r' < "$f" | grep -cF -- 'Combining this with')"
  o="$(line_of '^[[:space:]]*ondemand[[:space:]]*[|][[:space:]]*mutation[[:space:]]*[|]' "$f")"
  c="$(line_of 'Combining this with' "$f")"
  d=$((c - o)); [ "$d" -lt 0 ] && d=$((-d))
  if [ "$c" -gt 0 ] && [ "$o" -gt 0 ] && [ "$d" -le 4 ]; then
    _ok "AC-5: $p's pointer sits beside its ondemand | mutation line"
  else
    _bad "AC-5: $p's pointer sits beside its ondemand | mutation line" \
      "ondemand | mutation at line $o, 'Combining this with' at line $c (0 = absent); expected within 4 lines"
  fi
done

# ---------------------------------------------------------------------------
describe "the rust profile runs every test binary on its test gates and warns off --ignore-run-fail (HARNESS-058, AC-1..AC-3)"

# The matchers, ONE copy, used on the shipped profile and on the heredoc
# fixtures alike, so a matcher that cannot fail is caught by the controls
# below rather than by a later story (C-2).
# gate_lines <id-ERE> <text>   every `gate | <id> |` line in the text. The id
# is matched whole, between bars, so `unit` does not also select `unit-x`.
# `[|]` rather than `\|` because awk -v processes escapes (C-4's reason).
gate_lines() {
  printf '%s\n' "$2" | tr -d '\r' \
    | awk -v re="^[[:space:]]*gate[[:space:]]*[|][[:space:]]*$1[[:space:]]*[|]" '$0 ~ re'
}
# word_count <flag> <text>   how many lines carry the flag as a WHOLE word:
# `--no-fail-fast-x` is not `--no-fail-fast`. grep -c prints 0 itself on no
# match; `|| true` swallows only its exit status.
word_count() {
  grep -cE -- "(^|[[:space:]])$1([[:space:]]|\$)" <<< "$2" || true
}
# nonblank <text>   how many non-blank lines.
nonblank() { grep -c . <<< "$1" || true; }
# prose_paras_with <needle> <text>   the paragraphs containing the needle that
# are PROSE: an indented (4-space) block is a configuration block, and a gate
# line carrying a flag is not a warning about it.
prose_paras_with() {
  printf '%s\n' "$2" | paras | awk -v n="$1" 'index($0, n) && $0 !~ /^    /'
}

RUST_GATES="$(section '## Gate commands for project.conf' "$RUST")"
RUST_TEXT="$(tr -d '\r' < "$RUST")"
rust_unit="$(gate_lines unit "$RUST_GATES")"
rust_cov="$(gate_lines coverage "$RUST_GATES")"

# Preconditions: each line found once, so a flag count of 0 below means the
# flag is missing, not that the section reader found nothing.
assert_eq "precondition: the Gate commands section has exactly one \`gate | unit\` line" \
  1 "$(nonblank "$rust_unit")"
assert_eq "precondition: the Gate commands section has exactly one \`gate | coverage\` line" \
  1 "$(nonblank "$rust_cov")"

# AC-1: both test gates run every test binary, and unit keeps --workspace.
assert_eq "AC-1: the rust \`unit\` gate runs every test binary (--no-fail-fast, as a whole word)" \
  1 "$(word_count --no-fail-fast "$rust_unit")"
assert_eq "AC-1: the rust \`unit\` gate still tests every workspace member (--workspace)" \
  1 "$(word_count --workspace "$rust_unit")"
assert_eq "AC-1: the rust \`coverage\` gate runs every test binary (--no-fail-fast, as a whole word)" \
  1 "$(word_count --no-fail-fast "$rust_cov")"

# AC-1 negative controls: the same matchers over a fixture, not over the file.
FIX_AC1="$(cat <<'FIXTURE'
## Gate commands for project.conf

    gate | unit      | required | . | cargo test --workspace
    gate | unit-x    | required | . | cargo test --workspace --no-fail-fast
    gate | coverage  | required | . | cargo llvm-cov --workspace --no-fail-fast-x --fail-under-lines 100
    # gate | unit | a comment that mentions --no-fail-fast

Prose that mentions --no-fail-fast is not a gate line.
FIXTURE
)"
assert_eq "AC-1 control: a \`unit\` line of plain \`cargo test --workspace\` is reported missing the flag" \
  0 "$(word_count --no-fail-fast "$(gate_lines unit "$FIX_AC1")")"
assert_eq "AC-1 control: \`--no-fail-fast-x\` on the coverage line is not the flag" \
  0 "$(word_count --no-fail-fast "$(gate_lines coverage "$FIX_AC1")")"
FIX_AC1_OK='    gate | unit      | required | . | cargo test --workspace --no-fail-fast'
assert_eq "AC-1 control: the matcher does find the flag on a unit line that carries it" \
  1 "$(word_count --no-fail-fast "$(gate_lines unit "$FIX_AC1_OK")")"

# AC-2 (guard, green on arrival; earned by DV-2): no gate line, anywhere in the
# profile, grades a failing test as a pass. The gate lines are counted first so
# that "none carries it" cannot be "none was read".
rust_all_gates="$(gate_lines '[^|]*' "$RUST_TEXT")"
if [ "$(nonblank "$rust_all_gates")" -ge 5 ]; then
  _ok "precondition: the AC-2 guard reads at least the five required gate lines"
else
  _bad "precondition: the AC-2 guard reads at least the five required gate lines" \
    "read $(nonblank "$rust_all_gates") gate lines"
fi
assert_eq "AC-2: no \`gate |\` line in the rust profile carries --ignore-run-fail" \
  0 "$(word_count --ignore-run-fail "$rust_all_gates")"
# AC-2 negative control.
FIX_AC2="$(cat <<'FIXTURE'
    gate | unit      | required | . | cargo test --workspace --no-fail-fast
    gate | coverage | required | . | cargo llvm-cov --workspace --ignore-run-fail
FIXTURE
)"
assert_eq "AC-2 control: a coverage gate carrying --ignore-run-fail is refused by the same matcher" \
  1 "$(word_count --ignore-run-fail "$(gate_lines '[^|]*' "$FIX_AC2")")"

# AC-2 (prose): the profile names --ignore-run-fail with the fact that it exits
# 0 when tests fail. Matched per paragraph, so the wrap and the bold markers of
# C-1's `**exits 0** when tests fail` do not matter.
ignore_para="$(prose_paras_with '--ignore-run-fail' "$RUST_TEXT" | awk 'index($0, "exits 0") && index($0, "tests fail")')"
assert_eq "AC-2: one prose paragraph names --ignore-run-fail and says it exits 0 when tests fail" \
  1 "$(nonblank "$ignore_para")"

# AC-3: the reason, after the --workspace paragraph and before Evidence of work.
WHY_WINDOW="$(tr -d '\r' < "$RUST" | awk '/^\*\*`--workspace` on every command/ { on = 1 } on && /^## Evidence of work$/ { exit } on')"
assert_contains "precondition: AC-3's window starts at the --workspace paragraph" \
  '`--workspace` on every command' "${WHY_WINDOW:-<no --workspace paragraph>}"
assert_eq "AC-3: between the --workspace paragraph and Evidence of work, one paragraph says cargo stops at the 'first test *binary*'" \
  1 "$(count_paras 'first test *binary*' "$WHY_WINDOW")"
why_para="$(para_with 'first test *binary*' "$WHY_WINDOW")"
assert_contains "AC-3: that paragraph says --no-fail-fast still exits non-zero" \
  'still exits non-zero' "${why_para:-<no paragraph naming first test *binary*>}"
assert_contains "AC-3: that paragraph says a passing run leaves evidence lines and floors unchanged" \
  'evidence lines and floors' "${why_para:-<no paragraph naming first test *binary*>}"

summary "profiles"
