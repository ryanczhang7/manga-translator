#!/usr/bin/env bash
# Run the project's quality gates as declared in .claude/harness/project.conf.
#
#   bash scripts/gates.sh                  run every gate; record the result in the active story
#   bash scripts/gates.sh --story WORLD-3  ... and record it in that story instead
#   bash scripts/gates.sh --list           show what is configured
#   bash scripts/gates.sh --gate unit      run one gate, `ondemand` or not  (not recorded: a partial run is not evidence)
#   bash scripts/gates.sh --required       required gates only  (not recorded)
#   bash scripts/gates.sh --fast           every gate not marked `slow`  (not recorded)
#   bash scripts/gates.sh --audit          check the manifest itself, run nothing
#
# The gate NAMES are stable across every project ("the coverage gate"); the
# COMMANDS behind them are per-stack. That indirection is what lets the same
# agents drive a Python service, a TypeScript app or a Godot game.
#
# Exit 0 is not proof that a gate did any work: a test runner that discovers no
# tests, or a linter pointed at an empty directory, exits 0 with nothing to say.
# `evidence` lines assert that work was OBSERVED, not that it succeeded.
# `floor` lines go further and assert HOW MUCH: the number the evidence regex
# matched must not fall below a recorded minimum, so a suite that quietly
# shrinks from 47 tests to 3 fails instead of passing faster. `waiver` lines
# name an optional gate that is known to fail, and why, so that WARN in the
# summary always means something changed. All three are described in the
# quality-gates skill.
#
# A gate can also be neither: BLOCKED, where the environment would not let the
# process start at all. That exits 3, stamps RESULT=blocked, and is a decision
# rather than a defect - see the quality-gates skill, and `blocked-when` in
# project.conf for a runner that words a launch failure its own way.
#
# `slow` lines name the gates a --fast run leaves out. --fast exists so that RED
# and GREEN can ask the gates whether the tests are even ADMISSIBLE - lint, types,
# and the instrumented test command they will actually be judged by - without
# paying for a release bundle on every loop. A gate is fast unless something says
# otherwise, so the subset is right by default and wrong only where someone said
# so out loud. A --fast run is never recorded: it is not a full run.
#
# `ondemand` lines name the gates NO run executes unless asked: `--gate <id>`,
# or a story that names the gate in `required_gates`. `slow` alone still let a
# mutation tool run on every full run - every story's GATES, every PR's CI job.
# A run that leaves one out prints `ON REQUEST   <id> (not run: <why>; ...)`
# and counts it in nothing. --audit refuses one on a required gate.
#
# A full run writes its own summary into the story's ## Gate results, stamped
# with the commit and a hash of the code it ran against. Nobody pastes it.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$ROOT/.claude/harness/project.conf"
LOGDIR="$ROOT/.claude/state/gate-logs"
STAMP="$ROOT/.claude/state/last-gate-run"

# THE MANIFEST MUST NOT CHANGE UNDER THE RUN.
# PORTED from manga-translator (MT-032), reported there off a --fast run.
#
# This script parses project.conf into its evidence/floor/waiver/slow tables
# ONCE at start-up and runs the gate commands afterwards. Anything that edits
# the file in between produces a summary whose numbers are each real and whose
# PAIRING never existed - `PASS lint (0s, observed 5, floor 1)` printed as a
# clean pass while the file on disk says `floor | lint | 5`.
#
# It is cheap to detect: fingerprint the file at parse time and again before the
# summary. `cksum` rather than a hash tool, for the same reason the rest of this
# harness stays in coreutils.
conf_fingerprint() { cksum 2>/dev/null < "$CONF" || printf 'unreadable'; }
CONF_AT_PARSE="$(conf_fingerprint)"

export CLAUDE_PROJECT_DIR="$ROOT"
. "$ROOT/.claude/hooks/lib.sh"

[ -f "$CONF" ] || { printf 'error: missing %s\n' "$CONF" >&2; exit 1; }
mkdir -p "$LOGDIR"

BOOTSTRAPPED="$(grep -E '^BOOTSTRAPPED=' "$CONF" | head -1)"
BOOTSTRAPPED="${BOOTSTRAPPED#*=}"; BOOTSTRAPPED="${BOOTSTRAPPED//[[:space:]]/}"
[ -z "$BOOTSTRAPPED" ] && BOOTSTRAPPED=no

RUN_LOCK_SELF="scripts/gates.sh${*:+ $*}"   # what the run lock records; the loop below shifts $@ away
ONLY=""; REQUIRED_ONLY=0; LIST=0; AUDIT=0; STORY=""; FAST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --list) LIST=1 ;;
    --gate) shift; ONLY="${1:-}" ;;
    --required) REQUIRED_ONLY=1 ;;
    --fast) FAST=1 ;;
    --audit) AUDIT=1 ;;
    --story) shift; STORY="${1:-}" ;;
    -h|--help) sed -n '2,42p' "$0"; exit 0 ;;
    *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

# --- parsing project.conf without a process per field -----------------------
# Both loops below walk the whole manifest, so whatever runs per field runs once
# per line or more. It used to be a `sed` inside a `$(...)` around a `cut`
# inside another: hundreds of processes to print --list, minutes on a host
# where a spawn costs a fifth of a second. Everything here is parameter
# expansion and builtins, and assigns into a variable rather than printing,
# because a `$(...)` forks even when its body is all builtins.
#
# The same four definitions are in scripts/doctor.sh and scripts/task.sh,
# copied rather than shared (doctor.sh must run when lib.sh is missing), and
# the test suite holds the three copies byte-identical.
#
# trim <string> [var]   <string> without leading or trailing [:space:] (tabs
# and carriage returns included, not only spaces). Printed, or assigned to
# <var> when one is named. Self-contained: the suite evaluates it on its own.
trim() { local _t="$1"; _t="${_t#"${_t%%[![:space:]]*}"}"; _t="${_t%"${_t##*[![:space:]]}"}"; if [ $# -gt 1 ]; then printf -v "$2" '%s' "$_t"; else printf '%s' "$_t"; fi; }
# from_field <n> <string> <var>   Field <n> of a `|`-separated string and
# everything after it, the later `|`s INCLUDED, untrimmed: cut's `-f<n>-`.
# `IFS='|' read` is not a substitute - it drops the delimiters it consumed, so a
# command or regex containing `|` would be cut at its first one. Like cut, a
# string with no `|` is returned whole, and one with fewer than <n> fields
# gives ''.
# rest <n> <string> <var>    trimmed `-f<n>-`: a value that may contain `|`.
# field <n> <string> <var>   trimmed `-f<n>`: one field.
# Never name `_t`, `_r`, `_i` or `_v` as <var>: bash scopes `local`
# dynamically, so the result would land in the helper's own local and vanish.
from_field() {
  local _r="$2" _i=1
  case "$_r" in
    *'|'*)
      while [ "$_i" -lt "$1" ]; do
        case "$_r" in *'|'*) _r="${_r#*|}" ;; *) _r=""; break ;; esac
        _i=$((_i+1))
      done ;;
  esac
  printf -v "$3" '%s' "$_r"
}
rest()  { local _v; from_field "$1" "$2" _v; trim "$_v" "$3"; }
field() { local _v; from_field "$1" "$2" _v; trim "${_v%%|*}" "$3"; }

TAB=$(printf '\t')
ESC=$(printf '\033')

# --- evidence, floor, waiver, slow and ondemand tables ----------------------
# Read up front, so that --gate <id> still finds its own lines. Stored as
# "<id><TAB><value>" lines; no associative arrays, for bash 3.2.
EVIDENCE=""; WAIVERS=""; FLOORS=""; SLOWS=""; ONDEMANDS=""; CIFACTORS=""; COVERS=""; BLOCKEDWHEN=""; SKIPPEDWHEN=""; GATE_IDS=""
GATE_REQ=""   # "<id><TAB>required|optional" per gate, after any story escalation
while IFS= read -r line; do
  line="${line%%$'\r'}"
  trim "$line" tline
  case "$tline" in ''|'#'*) continue ;; esac
  case "$line" in *'|'*) ;; *) continue ;; esac
  field 1 "$line" kind
  field 2 "$line" tid
  # Every gate id, so that --audit can tell a `slow` line naming a real gate
  # from one naming a typo. That distinction matters more here than for the
  # other tables: a misspelt `evidence` id makes its gate report "no evidence
  # line", and a misspelt `floor` id fails the audit outright, but a misspelt
  # `slow` id is silent - the gate it meant to exclude simply stays in --fast.
  [ "$kind" = "gate" ] && { GATE_IDS="$GATE_IDS $tid"; continue; }
  case "$kind" in evidence|waiver|floor|slow|ondemand|ci-factor|covers|blocked-when|skipped-when) ;; *) continue ;; esac
  # rest, not field, so that a regex containing `|` (alternation) survives.
  rest 3 "$line" tval
  [ -n "$tid" ] || continue
  case "$kind" in
    evidence) EVIDENCE="$EVIDENCE$tid$TAB$tval
" ;;
    waiver)   WAIVERS="$WAIVERS$tid$TAB$tval
" ;;
    floor)    FLOORS="$FLOORS$tid$TAB$tval
" ;;
    slow)     SLOWS="$SLOWS$tid$TAB$tval
" ;;
    ondemand) ONDEMANDS="$ONDEMANDS$tid$TAB$tval
" ;;
    ci-factor) CIFACTORS="$CIFACTORS$tid$TAB$tval
" ;;
    covers)   COVERS="$COVERS$tid$TAB$tval
" ;;
    blocked-when) BLOCKEDWHEN="$BLOCKEDWHEN$tid$TAB$tval
" ;;
    skipped-when) SKIPPEDWHEN="$SKIPPEDWHEN$tid$TAB$tval
" ;;
  esac
done < "$CONF"

# --- BLOCKED: the environment would not let the gate run --------------------
# A gate's result used to be a boolean derived from an exit code, and there is a
# third state that is neither. A required gate failed eight consecutive runs on
# one machine with `could not execute process ... (never executed) ... An
# Application Control policy has blocked this file. (os error 4551)` - Windows
# Smart App Control refusing an unsigned, locally built executable by
# reputation. Nothing about it was a test failure: the crate was untouched and
# the same command passed on CI three times the same day. The runner reported
# FAIL, the Stop hook then refused every report with "fix it or move the story
# back to RED", and neither applied. An hour and a user decision went into
# inventing a third path the harness had no word for.
#
# These patterns describe a process that never STARTED. They are deliberately
# not "anything that looks environmental": a compile error, a missing module, a
# failing assertion are all the gate doing its job. A project whose runner
# reports a launch failure differently adds its own:
#
#     blocked-when | integration | emulator device offline
#
# BLOCKED is not a pass. The run still exits non-zero (3, distinct from 1) and
# still needs a decision - it just names the decision correctly. That also
# bounds the cost of a misclassification: a real failure mistaken for a block
# still stops the story.
BLOCKED_DEFAULT='could not execute process|\(never executed\)|os error 4551|Application Control policy has blocked|cannot execute binary file|error while loading shared libraries|command not found|[^[:space:]]+/[^[:space:]:]+: Permission denied'

# A typo in --gate ran nothing and reported "All required gates passed (0
# ran)", exit 0. Nothing to run is not a pass.
if [ -n "$ONLY" ]; then
  case " $GATE_IDS " in
    *" $ONLY "*) ;;
    *) printf "error: no gate named '%s' in project.conf; see --list\n" "$ONLY" >&2; exit 2 ;;
  esac
fi

# IS THE TREE THE CODE? (HARNESS-030) Everything below judges the working tree
# and records the verdict as evidence. mutate.sh puts its file back on every path
# it can still run code on, but a kill is a path where it cannot, and a failed
# restore one where it could not; its `.active` sentinel survives both, and
# `mutate.sh --check` reads them. Refused before any gate runs - a run behind a
# stranded mutation is minutes producing a number that must be thrown away -
# and with 2, the existing "nothing ran" code. Detection, not a lock: nothing
# here waits. The mutation this run is itself the command of is not counted
# (--check honours HARNESS_MUTATION), so a gate probe still runs; whether such a
# run may be RECORDED is decided at the refusal block below. --list and --audit
# read the manifest, never the tree, and must not be gagged. Inert on CI, where
# .claude/state is gitignored and no sentinel can exist.
if [ "$LIST" = 0 ] && [ "$AUDIT" = 0 ] && [ -f "$ROOT/scripts/mutate.sh" ]; then
  if ! mutation_report="$(bash "$ROOT/scripts/mutate.sh" --check 2>&1)"; then
    printf '%s\n' "$mutation_report" >&2
    printf 'gates: refusing to run. The gates judge the working tree, and the tree may hold a mutation nobody restored.\n' >&2
    printf 'Resolve each mutation above, then run the gates again.\n' >&2
    exit 2
  fi
fi

# THE RUN LOCK (HARNESS-034). Two harness runs in one tree - this and a
# self-test, or two of either - starve each other: issue #97 measured a hang
# past 30 minutes that passed alone. scripts/run-lock.sh takes
# .claude/state/run.lock or refuses with 2, before any gate runs and before
# last-gate-run is written; it never waits. --list and --audit read the
# manifest, not the tree, and keep working beside a run in flight. The traps go
# in BEFORE the take, so no signal can strand a lock; trapped, a TERM or INT
# waits for the running gate command instead of orphaning it, and EXIT releases.
if [ "$LIST" = 0 ] && [ "$AUDIT" = 0 ]; then
  . "$ROOT/scripts/run-lock.sh" || { printf 'run-lock: scripts/run-lock.sh is missing; nothing was run.\n' >&2; exit 2; }
  trap run_lock_release EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  run_lock_acquire "$ROOT" "$RUN_LOCK_SELF" || exit 2
fi

# table_lookup <table> <id>   Echoes the value. Exact string comparison, never
# a regex match: a gate id containing `.` or `*` must not silently adopt a
# different gate's line. Returns 1 when the id has no line.
table_lookup() {
  local eid ere
  while IFS="$TAB" read -r eid ere; do
    if [ "$eid" = "$2" ]; then printf '%s' "$ere"; return 0; fi
  done <<< "$1"
  return 1
}

# A gate's log as the regex should see it: no ANSI colour, no CR.
clean_log() {
  sed -e "s/${ESC}\[[0-9;]*[a-zA-Z]//g" -e 's/\r$//' "$1"
}

# work_count <log> <evidence regex>   How much work the gate was observed doing:
# the first run of digits at or after the start of the first evidence match.
#
# The evidence regex is the measurement, rather than a second regex, because
# there should be one description per gate of what "having done something"
# looks like. The consequence is that a regex which stops mid-number - the
# `[1-9]` in `test result: ok\. [1-9]` - measures a truncated count; widen it
# to cover the whole number if you want a floor on that gate.
# Parenthesised, so that an evidence regex using top-level alternation
# (`a|b`) does not bind the trailing `.*` to its last branch alone.
work_count() {
  clean_log "$1" | awk 'BEGIN { re = ARGV[1]; ARGV[1] = "" }
    !seen && match($0, re) { seen = 1; m = substr($0, RSTART, RLENGTH); if (match(m, /[0-9]+/)) out = substr(m, RSTART, RLENGTH) }
    END { if (out != "") print out; exit (out == "") ? 1 : 0 }' "($2).*"
}

# --- recording ----------------------------------------------------------------
# The short commit the gates ran against, with a note when the working tree
# (outside docs/) had uncommitted changes. Shared by record_in_story and the
# kept failing log, so the two can never describe one run differently.
commit_with_note() {
  local commit dirty=""
  commit="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || printf 'no commit')"
  [ -z "$(git -C "$ROOT" status --porcelain -- . ':!docs' 2>/dev/null)" ] || dirty=" (working tree had uncommitted changes)"
  printf '%s%s' "$commit" "$dirty"
}

# Replace the body of the story's "## Gate results" section with a block this
# script wrote: the marker check-boundaries.sh looks for, the UTC time, the
# commit, the tree hash of the code the gates saw, and the summary. If the
# section is missing (an older story file) it is appended.
record_in_story() { # <story-file> <result-text> <summary-lines>
  local f="$1" res="$2" body="$3" commit tree block
  commit="$(commit_with_note)"
  tree="$(gate_tree_hash)"
  block="$(printf '%s\n' \
    "$GATE_MARKER" \
    "" \
    "    run:    $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "    commit: $commit" \
    "    tree:   $tree" \
    "    result: $res" \
    "" \
    "$(printf '%s\n' "$body" | sed -e '/^[[:space:]]*$/d' -e 's/^/    /')")"
  grep -q '^## Gate results' "$f" || printf '\n## Gate results\n' >> "$f"
  # ENVIRON rather than -v: the block contains regexes with backslashes.
  BLK="$block" awk '
    /^## Gate results/ { print; print ""; print ENVIRON["BLK"]; print ""; skip=1; next }
    skip && /^## / { skip=0 }
    !skip { print }
  ' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
}

# --- gates this story requires of itself ------------------------------------
# `integration` is optional for the repo because it needs a browser, and a busy
# laptop should not block unrelated stories on it. But a story whose central
# claims are only ever checked there - "the canvas draws a non-blank first
# frame" - can pass every required gate while its evidence went unrun. So a
# story may escalate a gate for itself, in its frontmatter:
#
#     required_gates: [integration]
#
# Optional for the repo, binding for the story that depends on it.
if [ -z "$STORY" ]; then load_state; STORY="$STORY_ID"; fi
STORY_FILE="$ROOT/docs/backlog/stories/$STORY.md"
STORY_REQUIRES=""
if [ -n "$STORY" ] && [ -f "$STORY_FILE" ]; then
  STORY_REQUIRES=" $(frontmatter_list "$STORY_FILE" required_gates) "
fi

fails=0; warns=0; known=0; unconfigured=0; ran=0; noevidence=0; blocked=0; skipped=""
results=""

while IFS= read -r line; do
  line="${line%%$'\r'}"
  trim "$line" tline
  case "$tline" in ''|'#'*) continue ;; esac
  case "$line" in *'|'*) ;; *) continue ;; esac

  field 1 "$line" kind
  [ "$kind" = "gate" ] || continue
  field 2 "$line" id
  field 3 "$line" req
  field 4 "$line" cwd
  rest  5 "$line" cmd
  [ -z "$cwd" ] && cwd="."

  # An escalation makes the gate required for everything below, and says so
  # wherever the gate is reported, so nobody has to wonder why `integration`
  # blocked this story and not the last one.
  escalated=""; story_asked=0
  confreq="$req"   # what project.conf says, before any story escalation
  case "$STORY_REQUIRES" in
    *" $id "*)
      [ "$req" = "required" ] || escalated=" (required by story $STORY)"
      req=required; story_asked=1 ;;
  esac

  # Recorded before any filter skips the gate: the changes check below needs
  # to know whether `integration` is required even on a run that did not
  # execute it.
  GATE_REQ="$GATE_REQ$id$TAB$req
"

  [ -n "$ONLY" ] && [ "$ONLY" != "$id" ] && continue
  [ "$REQUIRED_ONLY" = 1 ] && [ "$req" != "required" ] && continue

  # An `ondemand` gate runs only when asked for: by name (--gate), or by a
  # story that escalated it. Decided before --fast's `slow` check, so it is
  # reported once, as on request, and not again in `skipped:`; and before
  # configured-ness, so one with no command is ON REQUEST, not UNCONFIGURED.
  # It is counted in none of ran, unconfigured or known. A line with no reason,
  # or on a gate project.conf itself requires, is a manifest fault - a required
  # gate no full run executes is a hole shaped like a gate.
  ondwhy=$(table_lookup "$ONDEMANDS" "$id"); is_ondemand=$?
  if [ "$LIST" = 0 ] && [ "$is_ondemand" = 0 ]; then
    ond_broken=""
    if [ -z "$ondwhy" ]; then
      ond_broken="marked on-request with no reason; say why it is not run per story"
    elif [ "$confreq" = "required" ]; then
      ond_broken="an on-request gate cannot be required: no full run would ever judge it"
    fi
    if [ -n "$ond_broken" ]; then
      if [ "$AUDIT" = 1 ]; then
        printf 'FAIL %-12s %s\n' "$id" "$ond_broken"
      else
        results="$results\nFAIL         $id ($ond_broken)"
      fi
      fails=$((fails+1)); continue
    fi
    if [ "$AUDIT" = 0 ] && [ "$ONLY" != "$id" ] && [ "$story_asked" = 0 ]; then
      results="$results\nON REQUEST   $id (not run: $ondwhy; bash scripts/gates.sh --gate $id)"
      continue
    fi
  fi

  # --fast leaves out the gates a `slow` line names. It is a deliberate subset,
  # not a cheaper full run: it is never recorded, and a gate the story escalated
  # is skipped here like any other. The full run before REVIEW is what judges
  # the story; --fast only answers whether the tests are admissible to it.
  if [ "$FAST" = 1 ] && [ "$LIST" = 0 ] && [ "$AUDIT" = 0 ] \
     && table_lookup "$SLOWS" "$id" >/dev/null; then
    skipped="$skipped $id"; continue
  fi

  exp=$(table_lookup "$EVIDENCE" "$id") || exp="<none>"
  waiver=$(table_lookup "$WAIVERS" "$id") || waiver=""
  slowwhy=$(table_lookup "$SLOWS" "$id"); is_slow=$?
  floor=$(table_lookup "$FLOORS" "$id") || floor=""
  skippat=$(table_lookup "$SKIPPEDWHEN" "$id") || skippat=""
  cifactor=$(table_lookup "$CIFACTORS" "$id") || cifactor=""
  logrel=".claude/state/gate-logs/$id.log"

  if [ "$LIST" = 1 ]; then
    printf '%-12s %-9s %-6s %s\n' "$id" "$req" "$cwd" "${cmd:-<unconfigured>}"
    printf '%-12s %-9s %-6s evidence: %s\n' "" "" "" "$exp"
    [ -n "$floor" ]  && printf '%-12s %-9s %-6s floor:    %s\n' "" "" "" "$floor"
    [ -n "$cifactor" ] && printf '%-12s %-9s %-6s ci-factor: %s\n' "" "" "" "$cifactor"
    while IFS="$TAB" read -r cid cglob; do
      [ "$cid" = "$id" ] && printf '%-12s %-9s %-6s covers:   %s\n' "" "" "" "$cglob"
    done <<< "$COVERS"
    [ -n "$waiver" ] && printf '%-12s %-9s %-6s waiver:   %s\n' "" "" "" "$waiver"
    while IFS="$TAB" read -r bid bpat; do
      [ "$bid" = "$id" ] && printf '%-12s %-9s %-6s blocked-when: %s\n' "" "" "" "$bpat"
    done <<< "$BLOCKEDWHEN"
    while IFS="$TAB" read -r kid kpat; do
      [ "$kid" = "$id" ] && printf '%-12s %-9s %-6s skipped-when: %s\n' "" "" "" "$kpat"
    done <<< "$SKIPPEDWHEN"
    [ "$is_slow" = 0 ] && printf '%-12s %-9s %-6s slow:     %s (left out of --fast)\n' "" "" "" "${slowwhy:-no reason given}"
    [ "$is_ondemand" = 0 ] && printf '%-12s %-9s %-6s on-request: %s (run with --gate %s)\n' "" "" "" "${ondwhy:-no reason given}" "$id"
    [ -n "$escalated" ] && printf '%-12s %-9s %-6s optional for the repo,%s\n' "" "" "" "$escalated"
    continue
  fi

  # A `slow` line with no reason is how a gate quietly leaves the fast subset
  # and nobody remembers why. The reason is the whole value of the line.
  if [ "$is_slow" = 0 ] && [ -z "$slowwhy" ]; then
    if [ "$AUDIT" = 1 ]; then
      printf 'FAIL %-12s marked slow with no reason; say what makes it too slow for --fast\n' "$id"
    else
      results="$results\nFAIL         $id (marked slow with no reason in project.conf)"
    fi
    fails=$((fails+1)); continue
  fi

  # A floor is measured out of the evidence match, so it needs one, and it has
  # to be a number. Both are checked before anything runs: a floor that cannot
  # be evaluated would otherwise sit in project.conf looking like protection.
  floor_broken=""
  if [ -n "$floor" ]; then
    case "$floor" in
      ''|*[!0-9]*) floor_broken="floor '$floor' is not a number" ;;
    esac
    if [ -z "$floor_broken" ] && { [ "$exp" = "<none>" ] || [ "$exp" = "-" ]; }; then
      floor_broken="floor needs an evidence regex to measure, and $id has none"
    fi
  fi
  if [ -n "$floor_broken" ]; then
    if [ "$AUDIT" = 1 ]; then
      printf 'FAIL %-12s %s\n' "$id" "$floor_broken"
    else
      results="$results\nFAIL         $id ($floor_broken)"
    fi
    fails=$((fails+1)); continue
  fi

  # A ci-factor is a measurement, so it carries the number AND where the number
  # came from. Without the second half nobody can tell a figure read off a CI
  # log from one somebody assumed, and an assumed factor is worse than none: it
  # is acted on. The whole-gate ratio is the wrong number here and reads
  # plausible - 14x for a coverage gate whose per-test compute factor is 3.4x -
  # so a story can spend a day optimising a test that was already fine.
  cifactor_broken=""
  if [ -n "$cifactor" ]; then
    field 1 "$cifactor" cif_n
    # rest, like cut, returns the whole value when the delimiter is absent,
    # which would read a missing source as a source repeating the number.
    case "$cifactor" in
      *'|'*) rest 2 "$cifactor" cif_src ;;
      *)     cif_src="" ;;
    esac
    case "$cif_n" in
      ''|*[!0-9.]*|*.*.*|.|.*|*.) cifactor_broken="ci-factor '$cif_n' is not a number" ;;
    esac
    [ -z "$cifactor_broken" ] && [ -z "$cif_src" ] \
      && cifactor_broken="ci-factor has no source; say which CI run it was measured from"
  fi
  if [ -n "$cifactor_broken" ]; then
    if [ "$AUDIT" = 1 ]; then
      printf 'FAIL %-12s %s\n' "$id" "$cifactor_broken"
    else
      results="$results\nFAIL         $id ($cifactor_broken)"
    fi
    fails=$((fails+1)); continue
  fi

  # A waiver on a required gate is a bypass, not a waiver - including when the
  # story is what made it required.
  if [ -n "$waiver" ] && [ "$req" = "required" ]; then
    if [ "$AUDIT" = 1 ]; then
      printf 'FAIL %-12s has a waiver but is required%s; waivers are for optional gates only\n' "$id" "$escalated"
    else
      results="$results\nFAIL         $id (has a waiver but is required$escalated; waivers are for optional gates only)"
    fi
    fails=$((fails+1)); continue
  fi

  if [ "$AUDIT" = 1 ]; then
    if [ -z "$cmd" ]; then
      if [ "$req" = "required" ] && [ "$BOOTSTRAPPED" = "yes" ]; then
        printf 'FAIL %-12s no command\n' "$id"; fails=$((fails+1))
      else
        printf 'ok   %-12s (unconfigured)\n' "$id"
      fi
      continue
    fi
    if [ ! -d "$ROOT/$cwd" ]; then
      printf 'FAIL %-12s cwd does not exist: %s\n' "$id" "$cwd"; fails=$((fails+1)); continue
    fi
    if [ "$exp" = "<none>" ]; then
      printf 'WARN %-12s no evidence line; a vacuous pass would go unnoticed\n' "$id"
      [ "$req" = "required" ] && noevidence=$((noevidence+1)); continue
    fi
    if [ "$exp" = "-" ]; then
      printf 'ok   %-12s (liveness declared unassertable)\n' "$id"
    else
      printf 'ok   %-12s evidence: %s\n' "$id" "$exp"
    fi
    [ -n "$floor" ]  && printf '     %-12s floor:  %s\n' "" "$floor"
    [ -n "$skippat" ] && printf '     %-12s skipped-when: %s\n' "" "$skippat"
    [ -n "$cifactor" ] && printf '     %-12s ci-factor: %s\n' "" "$cifactor"
    [ "$is_slow" = 0 ] && printf '     %-12s slow:   %s\n' "" "$slowwhy"
    [ "$is_ondemand" = 0 ] && printf '     %-12s on-request: %s\n' "" "$ondwhy"
    [ -n "$waiver" ] && printf '     %-12s waiver: %s\n' "" "$waiver"
    continue
  fi

  if [ -z "$cmd" ]; then
    if [ "$req" = "required" ] && [ "$BOOTSTRAPPED" = "yes" ]; then
      results="$results\nFAIL         $id (required gate has no command in project.conf)"
      fails=$((fails+1))
    else
      results="$results\nUNCONFIGURED $id"
      unconfigured=$((unconfigured+1))
    fi
    continue
  fi

  printf '\n=== gate: %s (%s%s) ===\n%s\n' "$id" "$req" "$escalated" "$cmd"
  log="$LOGDIR/$id.log"
  started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  start=$(date +%s)
  ( cd "$ROOT/$cwd" && eval "$cmd" ) 2>&1 | tee "$log"
  rc=${PIPESTATUS[0]}
  dur=$(( $(date +%s) - start ))
  ran=$((ran+1))

  # Three outcomes. Liveness is only ever consulted for a gate that already
  # exited 0: success is the exit code's job, and this asks the separate
  # question of whether the command had anything to do. A gate that fails keeps
  # failing for its own reason, with its own message.
  outcome=pass; why=""; observed=""
  if [ "$rc" -ne 0 ]; then
    outcome=fail
    # Did it fail, or did it never start? Asked only of a gate that already
    # exited non-zero, and only against patterns describing a process that
    # could not be launched.
    blockpat="$BLOCKED_DEFAULT"
    extra=$(table_lookup "$BLOCKEDWHEN" "$id") || extra=""
    [ -n "$extra" ] && blockpat="$blockpat|$extra"
    if clean_log "$log" | awk 'BEGIN{r=ARGV[1];ARGV[1]=""} $0~r{h=1} END{exit !h}' "$blockpat"; then
      outcome=blocked
      why="could not launch: $(clean_log "$log" | grep -Eom1 -- "$blockpat" | head -1)"
    fi
  elif [ "$exp" != "<none>" ] && [ "$exp" != "-" ] && ! clean_log "$log" | awk 'BEGIN{r=ARGV[1];ARGV[1]=""} $0~r{h=1} END{exit !h}' "$exp"; then
    outcome=noevidence
    why="ran but produced no evidence of work: expected /$exp/"
  elif [ "$exp" != "<none>" ] && [ "$exp" != "-" ]; then
    # The gate did work. How much, and is that less than it used to be? A suite
    # that shrinks from 47 tests to 3 exits 0 and matches its evidence regex
    # just as happily as one that grew.
    observed="$(work_count "$log" "$exp")"
    if [ -n "$floor" ]; then
      if [ -z "$observed" ]; then
        outcome=noevidence
        why="floor of $floor declared, but no number was found in the evidence match, so the work could not be measured"
      elif [ "$observed" -lt "$floor" ]; then
        outcome=noevidence
        why="did $observed units of work, below the floor of $floor in project.conf"
        # Lost, or never supplied? A `skipped-when` pattern classifies the
        # shortfall just measured; it never excuses one. One awk engine both
        # detects and extracts, and reads all of its input, so no SIGPIPE.
        if [ -n "$skippat" ] && clean_log "$log" | awk 'BEGIN{r=ARGV[1];ARGV[1]=""} $0~r{h=1} END{exit !h}' "$skippat"; then
          skipmatch="$(clean_log "$log" | awk 'BEGIN{r=ARGV[1];ARGV[1]=""} !s && match($0, r){s=1; m=substr($0, RSTART, RLENGTH)} END{printf "%s", m}' "$skippat")"
          outcome=environment
          why="$why; the log says $skipmatch, so the work was skipped rather than lost: the environment did not supply it"
        fi
      fi
    fi
  fi

  case "$outcome" in
    pass)
      seen=""
      [ -n "$observed" ] && seen=", observed $observed"
      [ -n "$observed" ] && [ -n "$floor" ] && seen=", observed $observed, floor $floor"
      if [ -n "$waiver" ]; then
        results="$results\nPASS         $id (${dur}s$seen) -- waiver no longer needed, remove it: $waiver"
      elif [ "$exp" = "<none>" ] && [ "$BOOTSTRAPPED" = "yes" ] && [ "$req" = "required" ]; then
        results="$results\nPASS         $id (${dur}s) -- no evidence line: a vacuous pass would go unnoticed"
        noevidence=$((noevidence+1))
      else
        results="$results\nPASS         $id (${dur}s$seen)"
      fi ;;
    noevidence)
      if [ "$req" = "required" ]; then
        results="$results\nFAIL         $id$escalated (${dur}s, $why) -> $logrel"; fails=$((fails+1))
      elif [ -n "$waiver" ]; then
        results="$results\nKNOWN        $id (${dur}s, $why; $waiver)"; known=$((known+1))
      else
        results="$results\nWARN         $id (${dur}s, $why, optional)"; warns=$((warns+1))
      fi ;;
    fail)
      if [ "$req" = "required" ]; then
        results="$results\nFAIL         $id$escalated (${dur}s, exit $rc) -> $logrel"; fails=$((fails+1))
      elif [ -n "$waiver" ]; then
        results="$results\nKNOWN        $id (${dur}s, exit $rc; $waiver) -> $logrel"; known=$((known+1))
      else
        results="$results\nWARN         $id (${dur}s, exit $rc, optional) -> $logrel"; warns=$((warns+1))
      fi ;;
    blocked)
      # An OPTIONAL gate the environment blocked is nobody's decision: it was
      # never going to stop the story. Only a required one opens the third path.
      if [ "$req" = "required" ]; then
        results="$results\nBLOCKED      $id$escalated (${dur}s, exit $rc, $why) -> $logrel"
        blocked=$((blocked+1))
      elif [ -n "$waiver" ]; then
        results="$results\nKNOWN        $id (${dur}s, $why; $waiver) -> $logrel"; known=$((known+1))
      else
        results="$results\nWARN         $id (${dur}s, $why, optional) -> $logrel"; warns=$((warns+1))
      fi ;;
    environment)
      # Ran, exited 0, did less than its floor, and its `skipped-when` pattern
      # says the inputs were never here. A story leaning on it has no verdict
      # from this machine (BLOCKED, exit 3); nobody leaning on it is a declared
      # non-result (KNOWN), not a WARN: nothing changed, this checkout just
      # cannot answer the question.
      if [ "$req" = "required" ]; then
        results="$results\nBLOCKED      $id$escalated (${dur}s, $why) -> $logrel"
        blocked=$((blocked+1))
      elif [ -n "$waiver" ]; then
        results="$results\nKNOWN        $id (${dur}s, $why; $waiver) -> $logrel"; known=$((known+1))
      else
        results="$results\nKNOWN        $id (${dur}s, $why) -> $logrel"; known=$((known+1))
      fi ;;
  esac

  # <id>.log is overwritten by every run, so the re-run someone starts to see
  # whether a failure was a flake destroys the only copy of it. Keep the last
  # run that did not pass, stamped, in <id>.failed.log: one per gate, replaced
  # whole, never removed. Not added to $results: the gate record is unchanged.
  if [ "$outcome" != pass ]; then
    { printf '%s\n' \
        "# gates.sh: last failing run of gate '$id'" \
        "# outcome: $outcome" \
        "# run:     $started" \
        "# commit:  $(commit_with_note)" \
        "# tree:    $(gate_tree_hash)" \
        "# ----"
      cat "$log"
    } > "$LOGDIR/$id.failed.log"
    printf 'failing log kept: .claude/state/gate-logs/%s.failed.log\n' "$id"
  fi
done < "$CONF"

[ "$LIST" = 1 ] && exit 0

if [ "$AUDIT" = 1 ]; then
  # A `slow` line naming a gate that does not exist excludes nothing, silently.
  while IFS="$TAB" read -r sid _; do
    [ -n "$sid" ] || continue
    case " $GATE_IDS " in
      *" $sid "*) ;;
      *) printf 'FAIL %-12s a `slow` line names no configured gate\n' "$sid"; fails=$((fails+1)) ;;
    esac
  done <<< "$SLOWS"
  # And an `ondemand` line naming no gate is worse than silent: the gate it
  # meant stays on every full run, which is the cost the line exists to stop.
  while IFS="$TAB" read -r oid _; do
    [ -n "$oid" ] || continue
    case " $GATE_IDS " in
      *" $oid "*) ;;
      *) printf 'FAIL %-12s an `ondemand` line names no configured gate\n' "$oid"; fails=$((fails+1)) ;;
    esac
  done <<< "$ONDEMANDS"
  # Same for a ci-factor: a measurement filed against a gate that does not
  # exist is a number nobody will ever find when they need it.
  while IFS="$TAB" read -r cid _; do
    [ -n "$cid" ] || continue
    case " $GATE_IDS " in
      *" $cid "*) ;;
      *) printf 'FAIL %-12s a `ci-factor` line names no configured gate\n' "$cid"; fails=$((fails+1)) ;;
    esac
  done <<< "$CIFACTORS"
  # A blocked-when line is what makes BLOCKED reachable for a runner whose
  # launch failures the built-in patterns do not describe. One naming no gate
  # never fires; one with no pattern would match every line of every log and
  # turn every failure into a block, which is the opposite of the point.
  while IFS="$TAB" read -r bid bpat; do
    [ -n "$bid" ] || continue
    case " $GATE_IDS " in
      *" $bid "*) ;;
      *) printf 'FAIL %-12s a `blocked-when` line names no configured gate\n' "$bid"; fails=$((fails+1)); continue ;;
    esac
    [ -n "$bpat" ] || { printf 'FAIL %-12s a `blocked-when` line has no pattern\n' "$bid"; fails=$((fails+1)); }
  done <<< "$BLOCKEDWHEN"
  # A skipped-when line classifies a shortfall a floor measured. One naming no
  # gate fires on nothing; one with no pattern matches every log and would turn
  # every shortfall into a block; one on a gate with no floor has no
  # measurement to classify, so it can never fire - and each of the three sits
  # in the manifest looking like protection.
  while IFS="$TAB" read -r kid kpat; do
    [ -n "$kid" ] || continue
    case " $GATE_IDS " in
      *" $kid "*) ;;
      *) printf 'FAIL %-12s a `skipped-when` line names no configured gate\n' "$kid"; fails=$((fails+1)); continue ;;
    esac
    [ -n "$kpat" ] || { printf 'FAIL %-12s a `skipped-when` line has no pattern\n' "$kid"; fails=$((fails+1)); continue; }
    table_lookup "$FLOORS" "$kid" >/dev/null || {
      printf 'FAIL %-12s a `skipped-when` line names a gate with no `floor` line: there is nothing to measure the shortfall it would classify\n' "$kid"
      fails=$((fails+1))
    }
  done <<< "$SKIPPEDWHEN"
  # A covers line naming no gate covers nothing; an empty glob covers nothing
  # while looking like it covers everything.
  while IFS="$TAB" read -r cid cglob; do
    [ -n "$cid" ] || continue
    case " $GATE_IDS " in
      *" $cid "*) ;;
      *) printf 'FAIL %-12s a `covers` line names no configured gate\n' "$cid"; fails=$((fails+1)); continue ;;
    esac
    [ -n "$cglob" ] || { printf 'FAIL %-12s a `covers` line has no glob\n' "$cid"; fails=$((fails+1)); }
  done <<< "$COVERS"
  if [ -z "$COVERS" ]; then
    printf 'note         no `covers` lines: gates.sh cannot tell whether a story'"'"'s changed source\n'
    printf '             paths are exercised by any required gate. Add one per gate, e.g.\n'
    printf '               covers | unit | src/**\n'
  fi
  if [ "$noevidence" -gt 0 ]; then
    printf '\n%d required gate(s) have no evidence line. Add one per gate:\n' "$noevidence"
    printf '  evidence | <id> | <regex proving the tool did work>\n'
    printf 'Use `evidence | <id> | -` only where no such output exists, and say why in the story.\n'
  fi
  if [ "$fails" -gt 0 ]; then
    printf '\n%d manifest problem(s).\n' "$fails"; exit 1
  fi
  printf '\nManifest audit passed.\n'
  exit 0
fi

# --- what this story changed ------------------------------------------------
# "All required gates passed" is true and meaningless when the gates that
# passed never read the story's artifact. That happened: a renderer's tests in
# a browser-only project, that project in an `optional` gate, the coverage
# include skipping the same directory - three sound decisions that between
# them put every test of the story where nothing could block on it. Nothing
# in the manifest said which paths a gate reads, so nothing could notice.
#
# `covers` lines say. With any present and a story active, the story's changed
# SOURCE paths - the diff against main, committed or not - are matched against
# them. A path only optional gates read fails the run: the fix is the story's,
# `required_gates`, and is meant to be made at RED rather than found here. A
# path no gate claims warns: the manifest may be incomplete, or the file may
# be genuinely ungated, and a person has to say which. Tests are not the
# artifact and are not checked. Runs on --fast too, because GREEN ends with
# --fast and GREEN is where the source first exists.
changes_note=""; chwarn=0
if [ -n "$COVERS" ] && [ -n "$STORY" ] && [ -f "$STORY_FILE" ]; then
  base=""
  for b in origin/main main; do
    if git -C "$ROOT" rev-parse --verify -q "$b" >/dev/null 2>&1; then base="$b"; break; fi
  done
  if [ -z "$base" ]; then
    changes_note="(changes not checked: no main branch to compare against)"
  else
    mb="$(git -C "$ROOT" merge-base "$base" HEAD 2>/dev/null || printf '%s' "$base")"
    changed="$( { git -C "$ROOT" diff --name-only "$mb" 2>/dev/null
                  git -C "$ROOT" ls-files --others --exclude-standard 2>/dev/null; } \
                | sort -u | classify_stdin | awk -F'\t' '$1 == "source" { print $2 }')"
    total=0; covered=0
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      [ -e "$ROOT/$path" ] || continue        # deleted: nothing left to exercise
      total=$((total+1))
      reqs=""; opts=""
      while IFS="$TAB" read -r cid cglob; do
        [ -n "$cid" ] && [ -n "$cglob" ] || continue
        glob_matches "$cglob" "$path" || continue
        creq="$(table_lookup "$GATE_REQ" "$cid")" || creq=""
        case " $reqs $opts " in *" $cid "*) continue ;; esac
        if [ "$creq" = "required" ]; then reqs="$reqs $cid"; else opts="$opts $cid"; fi
      done <<< "$COVERS"
      if [ -n "$reqs" ]; then
        covered=$((covered+1))
      elif [ -n "$opts" ]; then
        results="$results\nFAIL         changes: $path is exercised only by optional gate(s):$opts - add required_gates: [$(printf '%s' "${opts# }" | sed 's/ /, /g')] to the story, or a covers line for a required gate"
        fails=$((fails+1))
      else
        results="$results\nWARN         changes: $path is exercised by no gate with a covers line"
        chwarn=$((chwarn+1))
      fi
    done <<< "$changed"
    if [ "$total" -gt 0 ]; then
      if [ "$covered" -eq "$total" ]; then
        changes_note="$total changed source path(s), all exercised by a required gate"
      else
        changes_note="$total changed source path(s), $covered exercised by a required gate"
      fi
    fi
  fi
fi

# Folded into `results` rather than reported as a separate early exit, which is
# deliberate: that lands it INSIDE the summary block, so the exit status, the
# RESULT=fail stamp, the "N required gate(s) failed" line and --fast's own
# caveats all follow without a separate exit that would take them with it. Runs
# in every mode that runs a gate command, --fast included, because --fast is the
# mode this was reported on. --list and --audit run no gate command and have
# already exited above.
CONF_CHANGED=0
if [ "$(conf_fingerprint)" != "$CONF_AT_PARSE" ]; then
  CONF_CHANGED=1
  results="$results\nFAIL         config: .claude/harness/project.conf changed while the gates were running"
  fails=$((fails+1))
fi

printf '\n--- gate summary ---%b\n' "$results"
if [ "$CONF_CHANGED" = 1 ]; then
  printf '\nThe evidence, floor, waiver and slow tables above were read from\n'
  printf '.claude/harness/project.conf before the gates ran, and the file on disk is no\n'
  printf 'longer the file that was read. Each number above is real on its own, but the\n'
  printf 'pairings in this summary may not correspond to any single state of that file -\n'
  printf 'a floor read at start-up can be printed beside an observation counted after it\n'
  printf 'changed, which is a pass that never existed. This is not a verdict on the code.\n'
  printf 'Find what is writing the manifest - another session, a subagent, a script - and\n'
  printf 'run the gates again on a tree nothing else is editing.\n'
fi
[ -n "$changes_note" ] && printf '\nchanges: %s\n' "$changes_note"
if [ "$chwarn" -gt 0 ]; then
  printf '\n%d changed source path(s) match no covers line. Either the manifest is missing\n' "$chwarn"
  printf 'a line for the gate that reads them, or the file is genuinely ungated - say which\n'
  printf 'in the story. A path no gate reads is a path no gate can fail on.\n'
fi

if [ "$BOOTSTRAPPED" != "yes" ]; then
  printf '\nNote: project.conf is not bootstrapped yet (BOOTSTRAPPED=no), so unconfigured\n'
  printf 'required gates are warnings. The bootstrap story must fill them in and flip the flag.\n'
fi

if [ "$noevidence" -gt 0 ]; then
  printf '\nWarning: %d required gate(s) ran without an evidence line, so a command that\n' "$noevidence"
  printf 'did no work at all would still have been recorded as PASS. Add to project.conf:\n'
  printf '  evidence | <id> | <regex proving the tool did work>\n'
fi

if [ "$warns" -gt 0 ]; then
  printf '\n%d optional gate(s) WARNed. A WARN means something changed since the last run:\n' "$warns"
  printf 'read it. A failure that is known and permanent belongs in a waiver, so that the\n'
  printf 'next WARN is not buried next to it:\n'
  printf '  waiver | <id> | <why this optional gate is expected to fail, and where that is recorded>\n'
fi

# UNTRACKED GATED FILES ARE NOT IN THE STAMP (HARNESS-014). The recorded tree is
# the one `git commit -a` would make, which is what CI recomputes from the
# commit; an untracked file that some gate read is in neither. Name every one,
# in every mode that runs a gate, so a file the story created and never staged
# is seen before it is missing from the commit rather than after.
untracked="$(untracked_gated)"
untracked_n=0
if [ -n "$untracked" ]; then
  untracked_n="$(printf '%s\n' "$untracked" | awk 'END { print NR }')"
  printf '\nuntracked: %d gated file(s) are not part of the recorded tree:\n' "$untracked_n"
  printf '%s\n' "$untracked" | awk '{ print "    UNTRACKED  " $0 }'
  printf 'Stage them (git add) if they belong to the story, or exclude them\n'
  printf '(.git/info/exclude) or move them if they do not.\n'
fi

# FULL says whether this was a whole run. The Stop hook decides from this stamp
# whether a phase's gate obligation has been met, and `--fast`, `--gate` and
# `--required` all write it too - so without the line a `--gate unit` could
# discharge GATES, whose entire job is the full suite.
FULLRUN=yes
{ [ -n "$ONLY" ] || [ "$REQUIRED_ONLY" = 1 ] || [ "$FAST" = 1 ]; } && FULLRUN=no

# A full run with a story to record into refuses to record while anything is
# named above: the stamp would describe a tree that is not the one about to be
# committed. With no active story (CI, ci-local.sh) there is nothing to refuse,
# and the exit status stays the gates' own. A refused run did not discharge the
# full run, so its stamp says FULL=no.
REFUSED=0; REFUSED_WHY=""
# Never record a run made inside a mutation of this tree (HARNESS-030): a gate
# probe may run the gates under its own mutation, but a verdict on mutated code
# is not evidence. Checked first, ahead of the branch: the mutation is the more
# fundamental reason. The directory comparison is load-bearing - a fixture copy
# of this script, run by a suite that is itself under a mutation of the REAL
# tree, inherits HARNESS_MUTATION and must not take that mutation for its own.
if [ "$FULLRUN" = yes ] && [ -n "${HARNESS_MUTATION:-}" ] && [ -f "$HARNESS_MUTATION" ] \
   && [ "${HARNESS_MUTATION%/*}" = "$ROOT/.claude/state/mutations" ]; then
  REFUSED=1; FULLRUN=no
  REFUSED_WHY="this run is inside mutate.sh's mutation of $(awk -F'\t' '$1 == "file" { print $2; exit }' "$HARNESS_MUTATION"); a verdict on mutated code is not evidence"
fi
# Refuse to record into a story from a checkout on another branch: the record
# would stamp another branch's tree into this story, which gate-reminder.sh
# tells the agent cannot happen. The branch is the story file's own `branch:`,
# not current-story.env's, because the story file is what is written to. A
# story with no `branch:`, or a detached HEAD, cannot be judged, so it fails
# open, as gate-reminder.sh does. Checked before the untracked files: a count means
# nothing for a tree that belongs to another story.
if [ "$FULLRUN" = yes ] && [ -n "$STORY" ] && [ -f "$STORY_FILE" ]; then
  checkout_branch="$(git -C "$ROOT" branch --show-current 2>/dev/null || printf '')"
  story_branch="$(frontmatter_value "$STORY_FILE" branch)"
  if [ -n "$checkout_branch" ] && [ -n "$story_branch" ] && [ "$checkout_branch" != "$story_branch" ]; then
    REFUSED=1
    FULLRUN=no
    REFUSED_WHY="the checkout is on '$checkout_branch' but story $STORY belongs on '$story_branch'; check out '$story_branch' and run again"
  fi
fi
if [ "$FULLRUN" = yes ] && [ "$untracked_n" -gt 0 ] && [ -n "$STORY" ] && [ -f "$STORY_FILE" ]; then
  REFUSED=1
  FULLRUN=no
  REFUSED_WHY="$untracked_n untracked gated file(s) are not in the tree this run would stamp; stage them (git add) or exclude them (.git/info/exclude) or move them, then run again"
fi

if [ "$fails" -gt 0 ]; then
  result="fail ($fails required gate(s) failed$([ "$blocked" -gt 0 ] && printf ', %d blocked' "$blocked"))"
  printf 'RESULT=fail\nWHEN=%s\nFULL=%s\nBLOCKED=%d\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FULLRUN" "$blocked" > "$STAMP"
elif [ "$blocked" -gt 0 ]; then
  # Not a pass and not a failure: the machine refused to run a required gate,
  # so the story has no verdict on it and needs one from somewhere else.
  result="blocked ($blocked required gate(s) could not run; $ran ran, $unconfigured unconfigured, $known known)"
  printf 'RESULT=blocked\nWHEN=%s\nFULL=%s\nBLOCKED=%d\nRAN=%d\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FULLRUN" "$blocked" "$ran" > "$STAMP"
else
  result="pass ($ran ran, $unconfigured unconfigured, $known known)"
  printf 'RESULT=pass\nWHEN=%s\nFULL=%s\nRAN=%d\nUNCONFIGURED=%d\nNOEVIDENCE=%d\nKNOWN=%d\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FULLRUN" "$ran" "$unconfigured" "$noevidence" "$known" > "$STAMP"
fi

if [ "$FAST" = 1 ]; then
  if [ -n "$skipped" ]; then
    printf '\n--fast skipped:%s\n' "$skipped"
  else
    printf '\n--fast skipped nothing: no gate carries a `slow` line, so this was a full run\n'
    printf 'in everything but the record. Mark the expensive gates:\n'
    printf '  slow | <id> | <why it is too slow to run every loop>\n'
  fi
  printf 'This is a subset, not a verdict. The full run before REVIEW is what judges the story.\n'
fi

# --- record -----------------------------------------------------------------
# Only a full run is evidence. `--gate unit` passing says nothing about lint.
if [ -n "$ONLY" ] || [ "$REQUIRED_ONLY" = 1 ] || [ "$FAST" = 1 ]; then
  printf '\n(not recorded in the story: a partial run is not evidence of anything)\n'
else
  if [ -z "$STORY" ]; then
    printf '\n(not recorded: no active story; use --story <id> to record it in one)\n'
  elif [ ! -f "$STORY_FILE" ]; then
    printf '\n(not recorded: no story file at docs/backlog/stories/%s.md)\n' "$STORY"
  elif [ "$REFUSED" = 1 ]; then
    printf '\n(not recorded: %s)\n' "$REFUSED_WHY"
  else
    record_in_story "$STORY_FILE" "$result" "$(printf '%b' "$results")"
    printf '\nrecorded in docs/backlog/stories/%s.md (## Gate results)\n' "$STORY"
  fi
fi

if [ "$blocked" -gt 0 ]; then
  printf '\n%d required gate(s) could not run: the environment refused to launch them.\n' "$blocked"
  printf 'This is not a failure and not a pass. Do not retry on a hunch and do not\n'
  printf 'treat it as a code defect - read the log, then take the third path:\n'
  printf '  1. Record it in the story as a PO decision: which gate, the quoted log line,\n'
  printf '     and what makes this the environment rather than the code.\n'
  printf '  2. The story may reach REVIEW with that gate marked *pending CI*.\n'
  printf '  3. It may not reach DONE until the PR CI log for that gate is quoted in\n'
  printf '     ## Gate results. CI is a different machine; that is the whole point.\n'
  printf 'If the block is a missing tool rather than a policy, bash scripts/doctor.sh\n'
  printf 'and docs/wiki/environment.md are where that gets fixed and written down.\n'
fi

if [ "$fails" -gt 0 ]; then
  printf '\n%d required gate(s) failed.\n' "$fails"
  exit 1
fi
# A refused BLOCKED run exits 1, not 3: nothing was recorded for a PO decision
# about the blocked gate to stand on.
if [ "$blocked" -gt 0 ]; then
  [ "$REFUSED" = 1 ] && exit 1
  exit 3
fi
printf '\nAll required gates passed (%d ran, %d unconfigured, %d known).\n' "$ran" "$unconfigured" "$known"
# The verdict above is about the code; the refusal is about the record.
[ "$REFUSED" = 1 ] && exit 1
if [ "$FAST" = 0 ] && [ -z "$ONLY" ] && [ "$REQUIRED_ONLY" = 0 ]; then
  printf 'CI runs one more script that this does not: bash scripts/check-boundaries.sh\n'
  printf 'It is not a gate because it judges the COMMIT rather than the code - the phase in\n'
  printf 'the committed frontmatter, the criteria against the base branch, and whether this\n'
  printf 'very record still matches the tree. Run it after committing, before the PR.\n'
fi
