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

# profile_problems <file>   "<check><TAB><message>" per violation; silent when
# the profile is consistent.
profile_problems() {
  awk '
    function t(s) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", s); return s }
    # Everything from field n on, rejoined: an evidence regex may contain `|`
    # as alternation and a discovery line is a shell pipeline.
    function rest(n,   i, o) { o = $n; for (i = n + 1; i <= NF; i++) o = o "|" $i; return t(o) }
    BEGIN { FS = "|"; nreq = split("lint typecheck unit coverage build", REQ, " ") }

    /^[[:space:]]*gate[[:space:]]*\|/ {
      id = t($2)
      gates[id] = 1
      if (t($3) == "required") required[id] = 1
      if (rest(5) != "") configured[id] = 1
      next
    }
    /^[[:space:]]*evidence[[:space:]]*\|/  { ev[t($2)] = 1; next }
    /^[[:space:]]*floor[[:space:]]*\|/     { fl[t($2)] = 1; next }
    /^[[:space:]]*discovery[[:space:]]*\|/ { ndisc++; next }
    /^[[:space:]]*slow[[:space:]]*\|/      { id = t($2); slow[id] = 1; why[id] = rest(3); next }
    # HARNESS-015: `ondemand | <id> | <why>` marks a gate a full run leaves out
    # until somebody asks for it (--gate <id>, or the story frontmatter).
    # Parsed like `slow`, and judged by the same two rules: it must name a
    # gate the profile configures, and it must say why.
    /^[[:space:]]*ondemand[[:space:]]*\|/  { id = t($2); ondemand[id] = 1; owhy[id] = rest(3); next }
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

      for (id in fl)
        if (!(id in ev))
          print "floor\tfloor on `" id "` has no evidence line to measure it out of"

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
describe "the profiles that configure a mutation gate are the ones expected (HARNESS-015, AC-3)"

# The per-profile assertion below is derived from the files, so a list that came
# back empty would assert nothing and pass. M-3 in the story names three.
lacking=""
for p in node-typescript.md python-uv.md rust-cargo.md; do
  has_mutation_gate "$PROFILE_DIR/$p" || lacking="$lacking $p"
done
assert_eq "node-typescript, python-uv and rust-cargo each configure a mutation gate" "" "$lacking"

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
  check orphan         "no evidence, floor, slow or ondemand line names an unconfigured gate"
  check floor          "every floor has an evidence line to measure"
  check slow           "every slow line carries a reason"
  check ondemand       "every ondemand line carries a reason"
  check fast-section   "says what --fast should leave out"
  check discovery      "has at least one discovery line"
  # AC-3: named with the profile so the failure reads "<profile>: its mutation
  # gate is on request", which is the control the criterion asks for.
  if has_mutation_gate "$f"; then
    check mutation-ondemand "$name: its mutation gate is on request"
  fi
done

summary "profiles"
