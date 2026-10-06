#!/usr/bin/env bash
# What to run a story with, and on which model.
#
#   bash scripts/plan.sh <id>           both answers, for a human
#   bash scripts/plan.sh models <id>    PHASE<TAB>agent<TAB>model<TAB>why
#   bash scripts/plan.sh next <id>      the command to drive it with, and why
#   bash scripts/plan.sh waves          startable stories grouped to run together
#   bash scripts/plan.sh after [<id>]   what to run next, and what can run alongside it
#
# Two questions that used to be asked of a person every time. A question asked
# every time stops being answered and starts being habit, and the model question
# in particular has a rule about it: `rules.md` says a model choice with no
# recorded verdict is folklore. The policy is in `.claude/harness/models.conf`
# with a reason per row; this reads it and applies it to one story.
#
# It RECOMMENDS. Neither answer is enforced anywhere, and neither should be:
# the story's own `## Model guidance` outranks the policy file, and a human who
# wants the other command has better information than a threshold does. What
# this removes is not the decision, it is having to reconstruct the reasoning
# from scratch on every story.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export CLAUDE_PROJECT_DIR="$ROOT"
. "$ROOT/.claude/hooks/lib.sh"

CONF="$ROOT/.claude/harness/models.conf"
PHASES="$ROOT/.claude/harness/phases.conf"
STORIES="$ROOT/docs/backlog/stories"

die() { printf 'plan: %s\n' "$1" >&2; exit 2; }

story_file() {
  local f="$STORIES/$1.md"
  [ -f "$f" ] || die "no story at docs/backlog/stories/$1.md"
  printf '%s' "$f"
}


# section <file> <heading-prefix>   Body of "## <prefix>..." up to the next "## ".
section() {
  awk -v h="## $2" 'index($0, h) == 1 { on=1; next } on && /^## / { exit } on { print }' "$1"
}

# Comments are the template; what matters is whether a person wrote anything.
strip_comments() {
  awk '{ s = s $0 "\n" }
       END {
         while ((i = index(s, "<!--")) > 0) {
           r = substr(s, i); j = index(r, "-->")
           if (j == 0) { s = substr(s, 1, i - 1); break }
           s = substr(s, 1, i - 1) substr(r, j + 3)
         }
         printf "%s", s
       }'
}
# ONE awk, not `strip_comments | grep -q`. This helper was lifted from
# check-boundaries.sh when this script was written, and its defect came with it:
# an awk that buffers to END feeding a grep that exits at the first match, so the
# writer dies of SIGPIPE and `pipefail` turns 141 into "no content". 50,000 bytes
# passed; 200,000 did not.
#
# The consequence here is quieter than a refused PR and worse for it. A thorough
# contract - the kind the RED row exists to reward - reads as ABSENT, the
# no-contract exception fires, and RED silently moves to the stronger model.
# Nothing fails; the story just runs on a model nobody chose.
has_content() {
  awk '{ s = s $0 "\n" }
       END {
         while ((i = index(s, "<!--")) > 0) {
           r = substr(s, i); j = index(r, "-->")
           if (j == 0) { s = substr(s, 1, i - 1); break }
           s = substr(s, 1, i - 1) substr(r, j + 3)
         }
         exit (s ~ /[^[:space:]]/) ? 0 : 1
       }'
}

conf_rows() { grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$CONF"; }
field() { printf '%s' "$1" | awk -F'|' -v n="$2" '{ gsub(/^[[:space:]]+|[[:space:]]+$/, "", $n); print $n }'; }

# --- the model plan ---------------------------------------------------------

# True when the contract names paths and EVERY one of them is a path the lock
# will not freeze. `harness` is in every phase's allowed list in phases.conf, and
# `.claude/tests/*`, `scripts/*` and `.claude/hooks/*` all classify as `harness`
# - so for a story that maintains the harness itself, RED may write the
# mechanism and GREEN may rewrite the frozen tests with nothing to stop either.
#
# That changes what the RED row rests on. Everywhere else the contract is an aid
# to the model and the LOCK is the enforcement; here the contract is the
# enforcement, the only one there is. Reported from a consuming project, which
# measured gates.sh --fast at 13/13 with identical counts across a GREEN that
# added a script, a config file and 25 assertions.
#
# One source path is enough for the lock to bite, so this needs ALL of them:
# otherwise every story that touches a helper script would trip it.
# contract_paths <file>   The paths a story's `## Contract` declares, one per
# line, sorted and unique. Empty when it declares none.
#
# FACTORED OUT RATHER THAN COPIED. contract_unenforced has read these since
# release 23 to decide the RED model, and cmd_conflicts now reads the same list
# to decide whether two stories would fight. rules.md: a test that needs this
# answer asks for it. Two extractors would eventually disagree about what a
# story touches, and the one that mattered would be whichever ran last.
#
# strip_comments FIRST, and it is load-bearing. The story TEMPLATE explains
# test-only dependencies using `go.mod`, `requirements.txt` and `*.csproj` as
# examples, inside an HTML comment. Read without stripping, every story in a
# fresh backlog declares those three paths and every pair collides. Measured on
# this repository's own five stories: all five "declared" go.mod and
# requirements.txt, and all five actually declare nothing.
#
# A `**Writes:**` LINE OUTRANKS THE PROSE (HARNESS-016). When the Contract has
# one, this returns exactly contract_writes, so the pair table and the RED model
# judge what the story says it writes rather than every file its prose cites.
# The prose extraction below is the fallback for a Contract that declares
# nothing better, and it drops four shapes that are never repository paths:
#   1. anything containing `..`                      AC-1..AC
#   2. anything ending in `/`, a directory prefix    .claude/skills/x/reference/
#   3. anything ending in a dot and only digits      1.2, 4.9
#   4. no `/` and a one-character stem before the first dot   e.g, i.bak, 0.139s
# Every other token stays, bare basenames included: `plan.sh` in prose is often
# the only name a pre-016 story gives a file it writes, and dropping it would
# turn a real CONFLICT into `clear` with nothing saying so. One awk over the
# grep's whole output, so nothing downstream exits early on a pipefail writer.
contract_paths() { # <file>
  local w; w="$(contract_writes "$1")"
  if [ -n "$w" ]; then printf '%s\n' "$w"; return 0; fi
  section "$1" "Contract" | strip_comments \
    | grep -oE '\.claude/[A-Za-z0-9_./-]+|[A-Za-z0-9_][A-Za-z0-9_./-]*\.[A-Za-z0-9]+' \
    | awk '/\.\./ { next }
           /\/$/ { next }
           /\.[0-9]+$/ { next }
           !/\// && /^[^.]\./ { next }
           { print }' \
    | sort -u
}

# contract_writes <file>   The paths on the `**Writes:**` lines of a story's
# `## Contract`: every backticked token on a line that starts, at column 0,
# with `**Writes:**`. Several lines union. One per line, sorted and unique;
# empty when the Contract has no such line.
#
# This is the Contract's COMMITMENT to what it writes, and it exists because
# prose cannot say that: HARNESS-009 writes "No change to `phase.sh`" and no
# extractor reading prose can tell the promise from a write. Only the author
# knows, so the author says, on a line a reader can find.
#
# strip_comments first, as above: the new-story.sh template carries its own
# example `**Writes:**` inside the Contract comment, and a fresh story that
# declared it would drift on a file nobody meant to write.
contract_writes() { # <file>
  section "$1" "Contract" | strip_comments \
    | awk 'index($0, "**Writes:**") == 1 {
             n = split($0, part, "`")
             for (k = 2; k < n; k += 2) if (part[k] != "") print part[k]
           }' \
    | sort -u
}

# story_touches <file>   The paths a story's `touches:` frontmatter declares,
# one per line, sorted and unique. Empty when the key is absent OR the list is
# empty: `touches: []` is what new-story.sh writes into every story, so reading
# it as "touches no file" would call every fresh story `clear` against
# everything - UNKNOWN reported as clear, by default.
#
# frontmatter_list is the reader depends_on uses; a second YAML reader here
# would be the private copy rules.md warns about.
story_touches() { # <file>
  frontmatter_list "$1" touches | sort -u
}

contract_unenforced() { # <file>
  local paths p found=0 enforced=0
  paths="$(contract_paths "$1")"
  [ -n "$paths" ] || return 1
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    found=1
    case "$(classify "$p")" in
      harness|docs|ignored) ;;
      *) enforced=1 ;;
    esac
  done <<< "$paths"
  [ "$found" = 1 ] && [ "$enforced" = 0 ]
}

cmd_models() {
  local file id; id="$1"; file="$(story_file "$id")"
  local type contract_has=0 unenforced=0
  type="$(frontmatter_value "$file" type)"; [ -n "$type" ] || type=feature
  section "$file" "Contract" | has_content && contract_has=1
  contract_unenforced "$file" && unenforced=1

  local row ph agent model why
  while IFS= read -r row; do
    case "$(field "$row" 1)" in model) ;; *) continue ;; esac
    ph="$(field "$row" 2)"; agent="$(field "$row" 3)"
    model="$(field "$row" 4)"; why="$(field "$row" 5)"

    # Exceptions first, first match wins.
    local erow econd emodel ewhy
    while IFS= read -r erow; do
      case "$(field "$erow" 1)" in except) ;; *) continue ;; esac
      [ "$(field "$erow" 2)" = "$ph" ] || continue
      econd="$(field "$erow" 3)"; emodel="$(field "$erow" 4)"; ewhy="$(field "$erow" 5)"
      case "$econd" in
        no-contract) [ "$contract_has" = 0 ] || continue ;;
        unenforced)  [ "$unenforced" = 1 ] || continue ;;
        type=*)      [ "$type" = "${econd#type=}" ] || continue ;;
        *)           continue ;;
      esac
      model="$emodel"; why="$ewhy"
      break
    done <<< "$(conf_rows)"

    printf '%s\t%s\t%s\t%s\n' "$ph" "$agent" "$model" "$why"
  done <<< "$(conf_rows)"
}

# --- which command to drive it with -----------------------------------------

# The next phase after <phase>, read from phases.conf's own order so that a
# phase inserted there does not have to be inserted here as well.
next_phase() {
  awk -F'|' -v cur="$1" '
    !/^#|^[[:space:]]*$/ { gsub(/ /, "", $1)
      if ($1 == "IDLE" || $1 == "SCAFFOLD") next
      order[++n] = $1 }
    END { for (i = 1; i <= n; i++) if (order[i] == cur && i < n) { print order[i+1]; exit } }
  ' "$PHASES"
}

AC_MANY=6   # the crudest signal, and the last one consulted

# unmet_deps <file>   Each `depends_on` entry that is not DONE, in the order
# listed: `dep<TAB>PHASE`, or `dep<TAB>missing` when it has no story file.
# The one answer to "what is this story waiting on": `cmd_next` decides blocked
# from it, and `waves` names it on the BLOCKED line.
unmet_deps() { # <file>
  local dep dfile dph
  for dep in $(frontmatter_list "$1" depends_on); do
    [ -n "$dep" ] || continue
    dfile="$STORIES/$dep.md"
    if [ ! -f "$dfile" ]; then printf '%s\tmissing\n' "$dep"; continue; fi
    dph="$(frontmatter_value "$dfile" phase)"
    [ "$dph" = "DONE" ] || printf '%s\t%s\n' "$dep" "${dph:-PLANNED}"
  done
}

cmd_next() {
  local file id; id="$1"; file="$(story_file "$id")"
  local type phase acs deferred
  type="$(frontmatter_value "$file" type)"; [ -n "$type" ] || type=feature
  phase="$(frontmatter_value "$file" phase)"; [ -n "$phase" ] || phase=PLANNED

  # A dependency that is not DONE. Recommending either command here sends
  # somebody into a refusal from `phase.sh set`, which is a worse answer than
  # naming the thing they are waiting on.
  local dep dph blocked=""
  while IFS="$(printf '\t')" read -r dep dph; do
    [ -n "$dep" ] || continue
    if [ "$dph" = missing ]; then blocked="$blocked $dep(missing)"; else blocked="$blocked $dep"; fi
  done <<< "$(unmet_deps "$file")"
  if [ -n "$blocked" ]; then
    printf 'blocked\t%s is blocked: depends_on is not DONE —%s. Finish it first, or drop the dependency.\n' \
      "$id" "$blocked"
    return 0
  fi

  if [ "$phase" = "DONE" ]; then
    printf 'none\t%s is DONE. Nothing to drive; start the next story.\n' "$id"
    return 0
  fi

  # Already in flight. The question is not how to run the cycle, it is what the
  # next phase is - and complete-story is never the answer to that.
  if [ "$phase" != "PLANNED" ]; then
    local nxt; nxt="$(next_phase "$phase")"
    printf 'advance-story\t%s is already in %s; advance it to %s. complete-story drives a cycle from the start.\n' \
      "$id" "$phase" "${nxt:-the next phase}"
    return 0
  fi

  # From PLANNED, the question is whether anything in this story wants a human
  # between the phases. Each of these is a reason to stop and look.
  if [ "$type" = "bootstrap" ]; then
    printf 'advance-story\t%s is a bootstrap story: SCAFFOLD writes source, tests and config with no failing test in front of any of it. Drive it a phase at a time.\n' "$id"
    return 0
  fi
  if section "$file" "Deferred verifications" | has_content; then
    printf 'advance-story\t%s carries a Deferred verification, which names a control and the phase that must run it. Something has to stop in that phase and look.\n' "$id"
    return 0
  fi
  acs="$(grep -cE '^[[:space:]]*-[[:space:]]*\*\*AC-' "$file" 2>/dev/null || true)"
  [ -n "$acs" ] || acs=0
  if [ "$acs" -ge "$AC_MANY" ]; then
    printf 'advance-story\t%s has %s acceptance criteria (%s or more). Size is the crudest signal here, but a cycle this wide is worth seeing between phases.\n' \
      "$id" "$acs" "$AC_MANY"
    return 0
  fi

  printf 'complete-story\t%s is an ordinary cycle: a contract to work from, %s criteria, nothing deferred, no dependency waiting. Run it end to end.\n' \
    "$id" "$acs"
}

# --- both, for a human ------------------------------------------------------

cmd_both() {
  local id="$1" nxt cmd why
  nxt="$(cmd_next "$id")"
  cmd="$(printf '%s' "$nxt" | cut -f1)"; why="$(printf '%s' "$nxt" | cut -f2-)"
  printf 'Story %s\n\n' "$id"
  case "$cmd" in
    blocked|none) printf '  %s\n' "$why" ;;
    *)            printf '  Recommended:  /%s %s\n  Because:      %s\n' "$cmd" "$id" "$why" ;;
  esac
  printf '\n  Model plan (from .claude/harness/models.conf — a plan, not a record;\n'
  printf '  write down what each dispatch RESOLVED to, in ## Model guidance):\n\n'
  cmd_models "$id" | while IFS="$(printf '\t')" read -r ph agent model why; do
    printf '    %-9s %-18s %-6s %s\n' "$ph" "$agent" "$model" "$why"
  done
}

# --- writing the plan into the story ----------------------------------------

# Run at the END of PLANNED, once the contract exists. Not at creation: the
# no-contract exception would be baked in before anybody had a chance to write
# one, and a plan that is wrong the moment it is written is worse than none.
#
# It replaces the section rather than appending to it, because the orchestrator
# re-runs this after amending the contract and a section that grew a copy each
# time would be read as a history of decisions nobody made.
#
# THE SUCCESS LINE IS A CLAIM ABOUT THE FILE, so nothing prints it until the
# file that is about to be written has been checked against the plan that was
# rendered. WORLD-097: this used to splice and then report success
# unconditionally, so a story that arrived WITHOUT the heading - WORLD-072 was
# split out of WORLD-012 by hand, and `new-story.sh`'s template is not the only
# route a story arrives by - passed through byte-identical while the tool said
# it had written the plan. `rules.md` says a model choice with no recorded
# verdict is folklore; this said the verdict was recorded when it was not.
#
# Three things follow from that, and none is decoration:
#
#   * THE STORY FILE IS TESTED HERE, not left to `story_file`'s `die`. That die
#     runs inside `file="$(story_file "$id")"` - a command substitution - so it
#     kills only the subshell, and `cmd_write` used to carry on with `$file`
#     empty: the awk read STDIN, `> "$file.new"` dropped a `.new` in the project
#     root, and the success line printed anyway. `|| exit $?` is what makes the
#     die reach this script, and it keeps the message to one line.
#   * THE SECTION IS APPENDED WHEN THE HEADING IS ABSENT rather than refused.
#     Refusing would be honest and would leave the rule unsatisfied; appending
#     satisfies it, and is idempotent because the appended section is an
#     ordinary section on the next run. End of file is where it goes; nothing
#     depends on that.
#   * THE CANDIDATE IS CHECKED BEFORE IT REPLACES THE STORY. Checking after the
#     `mv` would leave the damage behind an honest exit code, and the damage is
#     real: with a regular file sitting at `.claude/state` the render produces
#     nothing, `getline` from it returns nothing, and the splice DELETES the
#     section. `set -uo pipefail` has no `-e`, so a failed command here does not
#     stop the function - every failure path below is spelled out.
cmd_write() {
  local id="$1" file
  file="$(story_file "$id")" || exit $?

  local tmp="$ROOT/.claude/state/plan-write.$$.md"
  mkdir -p "$ROOT/.claude/state"

  {
    printf '## Model guidance\n\n'
    printf 'Planned by `bash scripts/plan.sh write %s` from `.claude/harness/models.conf`.\n' "$id"
    printf 'A PLAN, not a record: a session setting or an explicit override can beat both\n'
    printf 'this and the agent'"'"'s own `model:` field, and nothing here can see which won.\n'
    printf 'The orchestrator still writes down the model each dispatch **resolved** to, by\n'
    printf 'name, below the table.\n\n'
    printf '| Phase | Agent | Planned | Why |\n|---|---|---|---|\n'
    cmd_models "$id" | while IFS="$(printf '\t')" read -r ph agent model why; do
      printf '| %s | `%s` | `%s` | %s |\n' "$ph" "$agent" "$model" "$why"
    done
    printf '\n**Resolved:**\n\n'
    printf -- '<!-- One line per dispatch, as it happened: phase, agent, the model that\n'
    printf -- '     actually ran, and — if a phase was planned for one model and ran on\n'
    printf -- '     another — what that changed. A choice with no verdict is folklore. -->\n'
  } > "$tmp"

  # The render can fail with nothing to stop it: `mkdir` refused because a
  # regular file sits at `.claude/state`, the redirect refused for the same
  # reason, and there is no `-e`. ONE gate decides, below, and it is a
  # statement about the FILE rather than about any tool's exit status - an
  # early "the temp file is non-empty" check would be a proxy for that
  # statement, and a second place to get the cleanup wrong.
  local plan_body
  plan_body="$(tail -n +2 "$tmp" 2>/dev/null)"

  # Replace the section where the heading exists; append it where it does not.
  local new="$file.new"
  awk -v planfile="$tmp" '
    /^## Model guidance/ { while ((getline line < planfile) > 0) print line; skip = 1; matched = 1; next }
    skip && /^## / { skip = 0 }
    !skip { print }
    END { if (!matched) { print ""; while ((getline line < planfile) > 0) print line } }
  ' "$file" > "$new"

  # The post-condition, read off the CANDIDATE: exactly one `## Model guidance`
  # line (whole line, so `### Model guidance` is not one and neither is a second
  # copy), and the body beneath it is the plan just rendered, byte for byte.
  #
  # awk rather than `grep -cx`: that prints 0 AND exits 1 on no match, so it
  # needs a status-swallowing fallback beside it - the idiom
  # check-grep-count.sh exists to police, and whose live instances
  # .claude/tests/grep-count.test.sh counts as a census over the real tree.
  # (That census reads raw text, so it counts a mention in a COMMENT too: this
  # paragraph deliberately does not spell the two halves on one line.) One awk
  # needs neither the fallback nor a second process.
  local found body
  found="$(awk '$0 == "## Model guidance" { n++ } END { print n + 0 }' "$new" 2>/dev/null)"
  body="$(awk '/^## Model guidance$/ { on = 1; next } on && /^## / { exit } on { print }' "$new" 2>/dev/null)"
  if [ "$found" != 1 ] || [ "$body" != "$plan_body" ]; then
    rm -f "$new" "$tmp"
    die "refusing to report a write: docs/backlog/stories/$id.md would not hold the rendered plan"
  fi

  mv "$new" "$file" || { rm -f "$new" "$tmp"; die "could not write docs/backlog/stories/$id.md"; }
  rm -f "$tmp"
  printf 'wrote the model plan into %s\n' "docs/backlog/stories/$id.md"
}


# cmd_conflicts   Which startable stories would fight over the same file.
#
# RUNNING TWO STORIES AT ONCE NEEDS TWO THINGS TO BE TRUE: neither is blocked,
# and they do not write the same files. `depends_on` has always answered the
# first - `cmd_next` returns `blocked` and the board shows it. Nothing answered
# the second, so two ready stories could both be started and the collision found
# at merge, after both had gone green separately.
#
# THREE DISPOSITIONS, and the third is the point:
#   CONFLICT  both declare a path, and they share one. Named, with the path.
#   clear     both declare paths, and none is shared.
#   UNKNOWN   at least one declares nothing, so there is no basis to judge.
#
# UNKNOWN IS NOT CLEAR. A `## Contract` is written before RED, so every story in
# a backlog that has not started yet declares nothing - all five in this
# repository, today. Calling that "no conflicts" would be answering a question
# with no information, which is the failure refresh-harness.sh has a branch for
# and check-sigpipe.sh has a census line for.
#
# IT EXITS NON-ZERO ONLY ON CONFLICT. Unknown is the ordinary state of a fresh
# backlog, and a command that fails every time is one nobody runs.
#
# WHERE A STORY'S PATHS COME FROM: `touches:` first, the Contract otherwise.
# The Contract is written before RED, which is after planning - so judged on
# the Contract alone, every pair in a backlog being planned was UNKNOWN, ten of
# ten on this repository. `touches:` is written when the story is cut, which is
# when the planner can still act on the answer.
#
# DRIFT: when a story declares both, a path on its Contract's `**Writes:**`
# line that `touches:` neither names nor matches as a glob is printed as a
# warning. `touches:` is the planner's guess at cut time, `**Writes:**` is the
# Contract's commitment, and DRIFT is the disagreement between the two. It
# reads contract_writes, NOT contract_paths: until HARNESS-016 it read the
# prose, and every file the prose merely cited - a helper called, a script
# promised untouched - was a DRIFT line, 15 of 15 false on this repository. A
# Contract with no `**Writes:**` line has said nothing to disagree with, so it
# drifts on nothing. A story that turned out to touch more than it said should
# say so rather than be silently overruled either way. A warning, so it never
# changes the exit status - and it is judged per story, so it runs before the
# "fewer than two" return rather than being skipped by it.
story_paths() { # <file>
  local t; t="$(story_touches "$1")"
  if [ -n "$t" ]; then printf '%s\n' "$t"; else contract_paths "$1"; fi
}

# story_drift <file>   `**Writes:**` paths not covered by touches:, one per
# line. `case $p in $g` as well as equality, so `src/ui/*.tsx` covers
# `src/ui/panel.tsx`. No basename matching: a `**Writes:**` entry is a
# repository-relative path, and a bare `plan.sh` there is itself the drift.
# Read line by line: an unquoted `for g in $t` would expand the globs against
# this checkout.
story_drift() { # <file>
  local t c p g hit
  t="$(story_touches "$1")"; [ -n "$t" ] || return 0
  c="$(contract_writes "$1")"; [ -n "$c" ] || return 0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    hit=0
    while IFS= read -r g; do
      [ "$p" = "$g" ] && { hit=1; break; }
      # shellcheck disable=SC2254  # the glob is the point
      case "$p" in $g) hit=1; break ;; esac
    done <<< "$t"
    [ "$hit" = 1 ] || printf '%s\n' "$p"
  done <<< "$c"
}

# story_walk   Every story that is not DONE, one per line, in the order
# `"$STORIES"/*.md` yields them: `blocked<TAB>id<TAB>file` when `cmd_next`
# says blocked, `candidate<TAB>id<TAB>file` otherwise.
#
# ONE WALK FOR `conflicts` AND `waves`. Both answer "which stories could be
# started now", and two walks would one day disagree about it. DONE is decided
# FIRST, before `cmd_next` is asked: `cmd_next` checks depends_on before the
# story's own phase, so a DONE story whose dependency is not DONE would read as
# blocked, and a finished story is not waiting on anything.
story_walk() {
  local f id ph nxt
  for f in "$STORIES"/*.md; do
    [ -e "$f" ] || continue
    id="$(frontmatter_value "$f" id)"
    [ -n "$id" ] || continue
    ph="$(frontmatter_value "$f" phase)"
    [ "$ph" = DONE ] && continue
    nxt="$(cmd_next "$id" 2>/dev/null | cut -f1)"
    if [ "$nxt" = blocked ]; then
      printf 'blocked\t%s\t%s\n' "$id" "$f"
    else
      printf 'candidate\t%s\t%s\n' "$id" "$f"
    fi
  done
}

# shared_paths <paths-a> <paths-b>   The lines the two newline-separated lists
# have in common, compared as whole strings, space-joined (a trailing space when
# non-empty, nothing when they share none). This IS the collision test: `conflicts`
# prints it and `waves` places by it, so there is one answer to "do these collide".
# One awk over a here-string: no pipe into an early-exit reader, and nothing here
# reads the status of one. WORLD-086's house rule.
shared_paths() {
  awk -v other="$2" '
    BEGIN { n = split(other, o, "\n"); for (k = 1; k <= n; k++) if (o[k] != "") a[o[k]] = 1 }
    ($0 in a) { print }' <<<"$1" | tr '\n' ' '
}

# cmd_conflicts [table|pairs]   The table above, or with `pairs` the same
# judgement as `<id>\t<id>` lines, one per `clear` pair and nothing else.
#
# `--pairs` IS FOR AN ORCHESTRATOR. lead-po picks which two stories may run in
# two worktrees at once from the `clear` rows, and a table with padded columns,
# a header, DRIFT lines and a footer is one reformat away from being misparsed
# into the wrong pair. So the pairs mode prints only what may be selected: no
# CONFLICT, no UNKNOWN - unknown is not permission - and no blocked story,
# which story_walk never makes a candidate in the first place.
#
# ONE LOOP, TWO RENDERINGS. Each pair is judged exactly once, below, and the
# mode decides only how that verdict is printed. A second loop that decided
# `clear` for itself would one day disagree with the table about what clear is.
#
# `--pairs` EXITS 0 WHENEVER IT RAN. Empty stdout means "nothing may pair",
# which is an answer, and `p="$(plan.sh conflicts --pairs)"` under `set -e`
# must not die on the ordinary case. The table keeps its CONFLICT status.
cmd_conflicts() {
  local mode="${1:-table}"
  local files=() ids=() kind id f
  while IFS="$(printf '\t')" read -r kind id f; do
    [ "$kind" = candidate ] || continue
    ids+=("$id"); files+=("$f")
  done <<< "$(story_walk)"

  # Drift first: it is per story, and the early return below must not skip it.
  local n=${#ids[@]} k p drift=0 drift_lines=""
  k=0
  while [ "$k" -lt "$n" ]; do
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      drift_lines="$drift_lines$(printf '%-9s %-13s %s' DRIFT "${ids[$k]}" \
        "contract names $p, touches: does not")"$'\n'
      drift=$((drift + 1))
    done <<< "$(story_drift "${files[$k]}")"
    k=$((k + 1))
  done

  if [ "$n" -lt 2 ]; then
    [ "$mode" = pairs ] && return 0
    printf 'fewer than two startable stories; nothing to compare\n'
    [ "$drift" -gt 0 ] && printf '\n%s\n%d drift warning(s).\n' "$drift_lines" "$drift"
    return 0
  fi

  local i j pa pb shared verdict detail conflicts=0 unknowns=0
  if [ "$mode" = table ]; then
    printf '%-9s %-25s %s\n' STATUS PAIR DETAIL
    printf '%-9s %-25s %s\n' --------- ------------------------- ------------------------
  fi
  i=0
  while [ "$i" -lt "$n" ]; do
    j=$((i + 1))
    while [ "$j" -lt "$n" ]; do
      # The judgement: decided here, once, for both renderings.
      pa="$(story_paths "${files[$i]}")"
      pb="$(story_paths "${files[$j]}")"
      if [ -z "$pa" ] || [ -z "$pb" ]; then
        verdict=UNKNOWN; detail="declares neither touches: nor Contract paths - cannot judge"
        unknowns=$((unknowns + 1))
      else
        shared="$(shared_paths "$pa" "$pb")"
        if [ -n "${shared// /}" ]; then
          verdict=CONFLICT; detail="$shared"
          conflicts=$((conflicts + 1))
        else
          verdict=clear; detail="no shared path"
        fi
      fi
      # The rendering.
      if [ "$mode" = pairs ]; then
        [ "$verdict" = clear ] && printf '%s\t%s\n' "${ids[$i]}" "${ids[$j]}"
      else
        printf '%-9s %-25s %s\n' "$verdict" "${ids[$i]} + ${ids[$j]}" "$detail"
      fi
      j=$((j + 1))
    done
    i=$((i + 1))
  done

  [ "$mode" = pairs ] && return 0
  [ "$drift" -gt 0 ] && printf '\n%s' "$drift_lines"
  printf '\n%d conflict(s), %d pair(s) that could not be judged, %d drift warning(s).\n' \
    "$conflicts" "$unknowns" "$drift"
  [ "$unknowns" -gt 0 ] && printf 'UNKNOWN is not clear: a story that declares neither touches: nor Contract\npaths gives no basis to judge. Judge those pairs by hand, or fill touches:.\n'
  [ "$conflicts" -eq 0 ]
}

# cmd_waves   The startable stories grouped into waves that could run together.
#
# `conflicts` answers in pairs; a planner thinks in groups. This is the same
# pairwise answer - story_walk for the candidates, story_paths for what each
# declares, shared_paths for whether two collide - arranged as waves: within a
# wave EVERY pair is clear. A wave is a set of mutually disjoint stories, so a
# candidate is checked against every member already placed, not only the last.
#
# GREEDY FIRST FIT, AND NOT MINIMAL. Candidates are walked in id order; each
# goes into the first wave where it collides with no member, else opens a new
# one. That can use more waves than necessary - the fewest is minimal graph
# colouring, which is NP-hard. The input is a backlog of tens, and a planner
# wants a defensible, reproducible grouping rather than an optimal one, so this
# does not search and does not claim the count is the least possible.
#
# Ordering is decided before collision: a blocked story is listed as BLOCKED
# (naming each dependency that is not DONE) and never placed, even when it also
# declares nothing. A candidate that declares nothing is UNKNOWN and never
# compared, so it cannot land in wave 1 by default.
#
# Exit 0 when there is at least one wave, 1 when there are none - an empty,
# all-DONE or all-undeclared backlog is not a success.
cmd_waves() {
  local kind id f dep dph deps
  local ids=() paths=() blocked_lines=() unknown_lines=()
  while IFS="$(printf '\t')" read -r kind id f; do
    case "$kind" in
      blocked)
        deps=""
        while IFS="$(printf '\t')" read -r dep dph; do
          [ -n "$dep" ] || continue
          deps="${deps:+$deps, }$dep ($dph)"
        done <<< "$(unmet_deps "$f")"
        blocked_lines+=("$(printf '%-9s%s' BLOCKED "$id  depends_on $deps")") ;;
      candidate)
        local p; p="$(story_paths "$f")"
        if [ -z "$p" ]; then
          unknown_lines+=("$(printf '%-9s%s' UNKNOWN "$id  declares no paths - cannot be placed")")
        else
          ids+=("$id"); paths+=("$p")
        fi ;;
    esac
  done <<< "$(story_walk)"

  # waves[w] holds the candidate indices placed in wave w, space-separated.
  local waves=() i w m fits placed
  i=0
  while [ "$i" -lt "${#ids[@]}" ]; do
    placed=0; w=0
    while [ "$w" -lt "${#waves[@]}" ]; do
      fits=1
      for m in ${waves[$w]}; do
        if [ -n "$(shared_paths "${paths[$i]}" "${paths[$m]}")" ]; then fits=0; break; fi
      done
      if [ "$fits" = 1 ]; then waves[$w]="${waves[$w]} $i"; placed=1; break; fi
      w=$((w + 1))
    done
    [ "$placed" = 1 ] || waves+=("$i")
    i=$((i + 1))
  done

  local line members
  w=0
  while [ "$w" -lt "${#waves[@]}" ]; do
    members=""
    for m in ${waves[$w]}; do members="${members:+$members  }${ids[$m]}"; done
    printf '%-9s%s\n' "WAVE $((w + 1))" "$members"
    w=$((w + 1))
  done
  for line in ${blocked_lines[@]+"${blocked_lines[@]}"}; do printf '%s\n' "$line"; done
  for line in ${unknown_lines[@]+"${unknown_lines[@]}"}; do printf '%s\n' "$line"; done
  printf '\n%d wave(s), %d blocked, %d unplaceable.\n' \
    "${#waves[@]}" "${#blocked_lines[@]}" "${#unknown_lines[@]}"
  [ "${#waves[@]}" -ge 1 ]
}

# cmd_after [<closed-id>]   What to run next, and what can run alongside it.
#
# THE CLOSING REPORT (HARNESS-018). Every time a story closed, the answer to
# "what next" was rebuilt by hand from `next`, `waves`, `conflicts --pairs`,
# the epic rule in advance-story.md and the worktree recipe in CLAUDE.md, and
# came out different each time. This is that answer in one report, and
# `phase.sh set <id> DONE` prints it.
#
# IT REUSES, IT DOES NOT REIMPLEMENT: story_walk decides candidate vs blocked,
# cmd_next the command and reason, unmet_deps the blocked detail, story_paths
# and shared_paths the collision. A second answer to any of those would one day
# disagree with `waves` or `conflicts` about what is clear.
#
# ALONGSIDE IS GREEDY FIRST FIT, like `waves`. The members start as the Next
# story plus every story in flight; each other startable story, in backlog
# order, joins when it shares no path with any member. Neither DONE nor blocked
# stories are members. A member that declares no paths makes every judgement
# against it UNKNOWN, so then nothing is listed - UNKNOWN is not clear.
#
# ALWAYS EXITS 0, STDOUT ONLY. An empty backlog is an answer, and an id that
# names no story still gets the report, without the header and the epic check.
cmd_after() {
  local closed="${1:-}" cfile=""
  [ -n "$closed" ] && [ -f "$STORIES/$closed.md" ] && cfile="$STORIES/$closed.md"

  local IND='           ' LST='             '
  local kind id f ph dep dph deps
  local start_ids=() start_files=() fly_ids=() fly_files=() fly_phases=() blocked_lines=()
  while IFS="$(printf '\t')" read -r kind id f; do
    case "$kind" in
      blocked)
        deps=""
        while IFS="$(printf '\t')" read -r dep dph; do
          [ -n "$dep" ] || continue
          deps="${deps:+$deps, }$dep ($dph)"
        done <<< "$(unmet_deps "$f")"
        blocked_lines+=("$id  depends_on $deps") ;;
      candidate)
        ph="$(frontmatter_value "$f" phase)"; [ -n "$ph" ] || ph=PLANNED
        if [ "$ph" = PLANNED ]; then
          start_ids+=("$id"); start_files+=("$f")
        else
          fly_ids+=("$id"); fly_files+=("$f"); fly_phases+=("$ph")
        fi ;;
    esac
  done <<< "$(story_walk)"

  # Blocks are collected, then joined by one blank line: a block with nothing to
  # say is simply never added, and there is no trailing blank line.
  local blocks=() b nxt cmd why

  # Next.
  if [ "${#start_ids[@]}" -gt 0 ]; then
    nxt="$(cmd_next "${start_ids[0]}")"
    cmd="$(printf '%s' "$nxt" | cut -f1)"; why="$(printf '%s' "$nxt" | cut -f2-)"
    blocks+=("$(printf '%-11s/%s %s\n%s%s' 'Next:' "$cmd" "${start_ids[0]}" "$IND" "$why")")
  else
    b="$(printf '%-11s%s' 'Next:' 'no new story is startable.')"
    [ "${#fly_ids[@]}" -eq 0 ] && b="$b"$'\n'"${IND}Add work with /plan-story."
    blocks+=("$b")
  fi

  # Alongside.
  if [ "${#start_ids[@]}" -gt 0 ]; then
    local m_ids=() m_paths=() k p s hit unjudged="" reasons="" listed="" trees=""
    m_ids+=("${start_ids[0]}"); m_paths+=("$(story_paths "${start_files[0]}")")
    k=0
    while [ "$k" -lt "${#fly_ids[@]}" ]; do
      m_ids+=("${fly_ids[$k]}"); m_paths+=("$(story_paths "${fly_files[$k]}")")
      k=$((k + 1))
    done
    k=0
    while [ "$k" -lt "${#m_ids[@]}" ]; do
      [ -n "${m_paths[$k]}" ] || { unjudged="${m_ids[$k]}"; break; }
      k=$((k + 1))
    done

    if [ -n "$unjudged" ]; then
      blocks+=("$(printf '%-11snothing - %s declares no paths, so nothing can be judged against it.' \
        'Alongside:' "$unjudged")")
    else
      local i repo; repo="$(basename "$ROOT")"
      i=1
      while [ "$i" -lt "${#start_ids[@]}" ]; do
        id="${start_ids[$i]}"; f="${start_files[$i]}"
        p="$(story_paths "$f")"
        if [ -z "$p" ]; then
          reasons="$reasons"$'\n'"${IND}$id declares no paths, so it cannot be judged - UNKNOWN is not clear"
        else
          hit=""
          k=0
          while [ "$k" -lt "${#m_ids[@]}" ]; do
            s="$(shared_paths "$p" "${m_paths[$k]}")"
            if [ -n "${s// /}" ]; then hit="${m_ids[$k]}"; break; fi
            k=$((k + 1))
          done
          if [ -n "$hit" ]; then
            reasons="$reasons"$'\n'"${IND}$id shares ${s% } with $hit"
          else
            m_ids+=("$id"); m_paths+=("$p")
            cmd="$(cmd_next "$id" | cut -f1)"
            listed="$listed"$'\n'"${LST}/$cmd $id"
            trees="$trees"$'\n'"${LST}git worktree add ../$repo-$id -b $(frontmatter_value "$f" branch)"
          fi
        fi
        i=$((i + 1))
      done
      if [ -n "$listed" ]; then
        blocks+=("$(printf '%-11scan start now, in parallel with %s - no two of these, and no story in flight, declare a shared path:' \
          'Alongside:' "${start_ids[0]}")$listed"$'\n'"${IND}To run them together, give each its own worktree (one worktree, one story):$trees"$'\n'"${IND}then run its command from inside that worktree.$reasons")
      else
        blocks+=("$(printf '%-11snothing - run one story at a time.' 'Alongside:')$reasons")
      fi
    fi
  fi

  # In flight.
  if [ "${#fly_ids[@]}" -gt 0 ]; then
    b=""; k=0
    while [ "$k" -lt "${#fly_ids[@]}" ]; do
      if [ "$k" = 0 ]; then b="$(printf '%-11s' 'In flight:')"; else b="$b"$'\n'"$IND"; fi
      b="$b${fly_ids[$k]} (${fly_phases[$k]})  /advance-story ${fly_ids[$k]}"
      k=$((k + 1))
    done
    blocks+=("$b")
  fi

  # Blocked.
  if [ "${#blocked_lines[@]}" -gt 0 ]; then
    b=""; k=0
    while [ "$k" -lt "${#blocked_lines[@]}" ]; do
      if [ "$k" = 0 ]; then b="$(printf '%-11s' 'Blocked:')"; else b="$b"$'\n'"$IND"; fi
      b="$b${blocked_lines[$k]}"
      k=$((k + 1))
    done
    blocks+=("$b")
  fi

  # Epic: whole-string equality, and every story in it DONE - the closed one too.
  if [ -n "$cfile" ]; then
    local epic open=0 g
    epic="$(frontmatter_value "$cfile" epic)"
    if [ -n "$epic" ]; then
      for g in "$STORIES"/*.md; do
        [ -e "$g" ] || continue
        [ "$(frontmatter_value "$g" epic)" = "$epic" ] || continue
        [ "$(frontmatter_value "$g" phase)" = DONE ] || { open=1; break; }
      done
      [ "$open" = 0 ] && blocks+=("$(printf '%-11s%s has no open story left - /audit-mutations %s is recommended; nothing runs it automatically.' \
        'Epic:' "$epic" "$epic")")
    fi
  fi

  [ -n "$cfile" ] && printf 'After %s:\n\n' "$closed"
  k=0
  while [ "$k" -lt "${#blocks[@]}" ]; do
    [ "$k" = 0 ] || printf '\n'
    printf '%s\n' "${blocks[$k]}"
    k=$((k + 1))
  done
  return 0
}

case "${1:-}" in
  after)  cmd_after "${2:-}" ;;
  models) [ -n "${2:-}" ] || die "usage: plan.sh models <story-id>"; cmd_models "$2" ;;
  write)  [ -n "${2:-}" ] || die "usage: plan.sh write <story-id>";  cmd_write "$2" ;;
  next)   [ -n "${2:-}" ] || die "usage: plan.sh next <story-id>";   cmd_next "$2" ;;
  conflicts)
    case "${2-}" in
      "")      [ "$#" -lt 2 ] || die "usage: plan.sh conflicts [--pairs]"; cmd_conflicts table ;;
      --pairs) cmd_conflicts pairs ;;
      *)       die "usage: plan.sh conflicts [--pairs]  (got '$2')" ;;
    esac ;;
  waves)     cmd_waves ;;
  -h|--help|"") sed -n '3,8p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)      cmd_both "$1" ;;
esac
