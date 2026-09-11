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

      for (id in fl)
        if (!(id in ev))
          print "floor\tfloor on `" id "` has no evidence line to measure it out of"

      for (id in slow)
        if (why[id] == "")
          print "slow\t`" id "` is marked slow with no reason"

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
  check orphan         "no evidence, floor or slow line names an unconfigured gate"
  check floor          "every floor has an evidence line to measure"
  check slow           "every slow line carries a reason"
  check fast-section   "says what --fast should leave out"
  check discovery      "has at least one discovery line"
done

summary "profiles"
