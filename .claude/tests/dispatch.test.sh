#!/usr/bin/env bash
# Dispatch guard: the two long runs of a story go to a feature-developer
# dispatch that returns a verdict, and the seconds-long check stays the
# orchestrator's own (HARNESS-085).
#
# The orchestrator ran on `fable` (on `opus` since HARNESS-101) and, before this story, ran the full
# `bash scripts/gates.sh` at GREEN -> GATES and `SELFTEST_JOBS=4 bash
# scripts/selftest.sh` at GATES -> REVIEW itself, waiting out a run that can
# take hours and then re-sending its whole context uncached. The user decided
# these two run in a feature-developer dispatch on the GATES row, which returns
# the attest record's fields, and that the orchestrator checks the verdict with
# `bash scripts/attest.sh check` (HARNESS-084) instead of running the command.
# `bash scripts/check-boundaries.sh` takes seconds and stays inline (AC-3).
#
# The sites are prose, so nothing executes them; this is the shape `tdd-cycle`
# calls "code no machine you have can execute: grep for the shape". It pins
# that the instruction is present where the orchestrator and the subagent read
# it - not that either follows it (story, "Every criterion can only be checked
# structurally").
#
# `dispatch_problems <root>` is run over REPO_ROOT, where it must print
# nothing, and over fixtures built compliant by construction with one thing
# regressed, where it must print exactly the one line the Contract pins (C-5,
# as amended in RED). The fixtures are what make the real-tree assertion mean
# anything: a guard that never fires is satisfied by the real tree whatever the
# tree says. DV-1 is the same probe against a REAL line, owned by GATES.
#
# Matching is pure bash (mapfile, case, [ = ]): no grep or awk fork per needle.
# HARNESS-023 measured 109 s against 10.6 s for the same output on Windows.
#
# The GATES -> REVIEW step parser (load, blank, trim, gates_steps, first_step,
# gates_bullet) is COPIED from procedure.test.sh rather than sourced. The two
# suites run under separate floors, and sourcing one suite from another would
# run its assertions twice and tie this floor to that file's count (story C-5).
# They must agree on what "a step" is; if procedure.test.sh's parser changes,
# change this copy in the same commit.
#
# HARNESS-095 moves the long run from the full self-test to HARNESS-094's
# `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`: the self-test step, the
# complete-story bullet and lead-po's long-run paragraph name the `--changed`
# run and its `attest.sh check`, and a step or paragraph still naming only the
# full run gets its own line saying it does not name the `--changed` command.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# --- the sites and needles (Contract C-2, C-5: settled, read out) ------------
ADVANCE=".claude/commands/advance-story.md"
COMPLETE=".claude/commands/complete-story.md"
LEADPO=".claude/agents/lead-po.md"
FEATDEV=".claude/agents/feature-developer.md"

# procedure.test.sh's needles, read out (C-2: untouched, same steps).
# HARNESS-095 moves STEP_SELFTEST to the `--changed` span, as procedure.test.sh
# does, and keeps the full-run span as STEP_FULL: a step that names only
# STEP_FULL is the HARNESS-094 text, reported as not naming `--changed`.
STEP_SELFTEST='`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`'
STEP_FULL='`SELFTEST_JOBS=4 bash scripts/selftest.sh`'
STEP_BOUNDARIES='`bash scripts/check-boundaries.sh`'
PARA_START='**GATES → REVIEW.**'
BULLET_START='- **GATES → REVIEW'

# AC-1 / C-5 row 1, as amended in RED: the region carries every C-2 needle
# AC-1 names, not only the three the first cut of C-5 listed. The three
# command needles (here and in SELFTEST_NEEDLES) end with the closing backtick
# of their code span, as procedure.test.sh's STEP_SELFTEST does: without it
# `bash scripts/attest.sh check -- bash scripts/gates.sh --fast` and a targeted
# `... selftest.sh dispatch` would satisfy them, and `attest.sh check` is keyed
# by the exact words, so those are different records (C-5 amendment, RED).
GG_START='**GREEN → GATES.**'
GG_NEEDLES=(
  'feature-developer'
  'GATES row'
  'bash scripts/attest.sh -- bash scripts/gates.sh`'
  'bash scripts/attest.sh check -- bash scripts/gates.sh`'
  'exit status'
  'last line'
  'duration'
  'log'
)
# AC-2 / C-5 row 2. HARNESS-095 (AC-1): the dispatch runs, and the check
# names, the `--changed` command; both spans end at their closing backtick,
# so the full-run spelling - a prefix of each - does not satisfy them.
RUN_CHANGED='bash scripts/attest.sh -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`'
CHECK_CHANGED='bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`'
SELFTEST_NEEDLES=(
  'feature-developer'
  'detached'
  'alone'
  'verdict'
  "$RUN_CHANGED"
  "$CHECK_CHANGED"
)
# AC-3 / C-5 row 3, and the commit-step order row added in RED.
DISPATCHED='feature-developer'
COMMIT_RE='^[0-9]+\. Commit'
# AC-4 / C-5 rows 4 and 5 (the attest-check clause added in RED). HARNESS-095
# (AC-3): the bullet also says `GATES row` and names the `--changed` check.
BULLET_NEEDLES=('feature-developer' 'verdict' 'GATES row' "$CHECK_CHANGED")
ORCH_HEAD='## Orchestrating'
# HARNESS-095 (AC-3): the long-run paragraph names the `--changed` span (both
# backticks: the check span contains it without the opening one), goes to a
# feature-developer on the GATES row, and names the `--changed` check.
LONG_RUN="$STEP_SELFTEST"
LONG_NEEDLES=("$LONG_RUN" 'feature-developer' 'GATES row' "$CHECK_CHANGED")
OLD_RUNG='every rung is something you run, not'
ATTEST_CHECK='bash scripts/attest.sh check'
# AC-5 / C-5 row 6 (`GATES rules` added in RED).
RUN_HEAD='## Run and report'
RUN_NEEDLES=(
  'bash scripts/attest.sh --'
  'exit:'
  'last:'
  'duration:'
  'log:'
  'change nothing'
  'alone'
  'GATES rules'
)

# The lines, as C-5 (amended) pins them: `<relative-path>: <reason>`.
L_GG="$ADVANCE: GREEN → GATES does not dispatch the full gate run"
L_SELFTEST="$ADVANCE: the self-test step does not dispatch the run"
L_BOUND="$ADVANCE: the check-boundaries step dispatches a run that takes seconds"
L_COMMIT="$ADVANCE: the check-boundaries step does not come after the commit step"
L_BULLET="$COMPLETE: its GATES → REVIEW bullet does not name the dispatch"
L_LONG="$LEADPO: does not dispatch long runs"
L_RUNG="$LEADPO: still runs every rung itself"
L_CHECK="$LEADPO: does not name \`bash scripts/attest.sh check\`"
L_NOHEAD="$FEATDEV: has no ## Run and report section"
l_runsay() { printf '%s: ## Run and report does not say `%s`' "$FEATDEV" "$1"; }
# HARNESS-095 (AC-4): a step, or a long-run paragraph, that names the full run
# and no `--changed` command at all is the HARNESS-094 text.
L_NOCHANGED="$ADVANCE: the self-test step does not name \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\`"
L_LONG_CHANGED="$LEADPO: its long-run paragraph does not name \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\`"

# --- pure-bash region helpers -------------------------------------------------
# load, blank, trim, gates_steps, first_step and gates_bullet are copied from
# procedure.test.sh (see the header for why they are not sourced).

# load <file>   LN := the file's lines, a trailing CR stripped from each so a
# CRLF checkout (core.autocrlf) reads the same as an LF one.
load() {
  local i
  LN=(); mapfile -t LN < "$1"
  for i in "${!LN[@]}"; do LN[$i]="${LN[$i]%$'\r'}"; done
}

# blank <line>   Empty or whitespace only.
blank() { [ -z "${1//[[:space:]]/}" ]; }

# trim <s>   T := <s> without leading and trailing whitespace.
trim() {
  T="$1"
  T="${T#"${T%%[![:space:]]*}"}"
  T="${T%"${T##*[![:space:]]}"}"
}

# gates_steps   (procedure.test.sh) advance-story's GATES -> REVIEW paragraph:
# from the first line beginning `**GATES → REVIEW.**` to just before the next
# line beginning `**`, or EOF. A line matching `^[0-9]+\. ` starts a step; the
# step continues over following non-blank lines that start with whitespace.
# SN[k] := the k-th step's number, ST[k] := its lines, newline-joined.
gates_steps() {
  local l on=0 k=-1 in_step=0 re='^([0-9]+)\. '
  HAS_PARA=0; SN=(); ST=()
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#PARA_START}}" = "$PARA_START" ] && { on=1; HAS_PARA=1; }
      continue
    fi
    [ "${l:0:2}" = "**" ] && break
    if [[ $l =~ $re ]]; then
      k=$((k + 1)); SN[$k]="${BASH_REMATCH[1]}"; ST[$k]="$l"; in_step=1
    elif [ "$in_step" = 1 ] && ! blank "$l" && [[ $l == [[:space:]]* ]]; then
      ST[$k]="${ST[$k]}"$'\n'"$l"
    else
      in_step=0
    fi
  done
  return 0
}

# first_step <needle>   (procedure.test.sh) K := the index of the first step
# containing <needle> as a fixed string, or -1.
first_step() {
  local k
  K=-1
  for k in "${!ST[@]}"; do
    case "${ST[$k]}" in *"$1"*) K=$k; return 0 ;; esac
  done
  return 0
}

# gates_bullet   (procedure.test.sh) R := complete-story's bullet: the first
# line beginning `- **GATES → REVIEW`, plus the lines after it up to, not
# including, the next line beginning `- ` or a blank line.
gates_bullet() {
  local l on=0
  R=""; HAS_BULLET=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#BULLET_START}}" = "$BULLET_START" ] && { on=1; HAS_BULLET=1; R="$l"; }
      continue
    fi
    if [ "${l:0:2}" = "- " ] || blank "$l"; then break; fi
    R="$R"$'\n'"$l"
  done
  return 0
}

# --- this suite's own helpers -------------------------------------------------

# flat <text>   F := <text>'s lines, each trimmed, joined by one space. A needle
# is matched against F, so prose reflowed across a line break still matches -
# and, for an ABSENCE needle, still counts as present: the old rung sentence
# wrapped after `run,` is the same sentence (fixture `rung-wrapped`).
flat() {
  local l; local -a xs
  F=""
  mapfile -t xs <<<"$1"
  for l in "${xs[@]}"; do
    trim "$l"
    [ -z "$T" ] && continue
    if [ -z "$F" ]; then F="$T"; else F="$F $T"; fi
  done
  return 0
}

# all_in <text> <needle>...   Succeeds when flat <text> contains every needle.
all_in() {
  local w
  flat "$1"; shift
  for w in "$@"; do
    case "$F" in *"$w"*) ;; *) return 1 ;; esac
  done
  return 0
}

# gg_region   G := advance-story's GREEN -> GATES region: from the first line
# beginning `**GREEN → GATES.**` to just before the next PARAGRAPH that begins
# `**` - a line beginning `**` whose previous line is blank - or EOF. A line
# beginning `**` in the middle of a paragraph (`**value** mutation`, which the
# real region has) does not end it. HAS_GG := 1 when the region exists.
gg_region() {
  local l on=0 prev_blank=0
  G=""; HAS_GG=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#GG_START}}" = "$GG_START" ] && { on=1; HAS_GG=1; G="$l"; }
      continue
    fi
    [ "$prev_blank" = 1 ] && [ "${l:0:2}" = "**" ] && break
    G="$G"$'\n'"$l"
    if blank "$l"; then prev_blank=1; else prev_blank=0; fi
  done
  return 0
}

# section <heading>   SEC := the lines after the line EQUAL to <heading>, up to
# the next line beginning `## ` or EOF, newline-joined. HAS_SEC := 1 when the
# heading exists. `## Run and report (dispatch)` is not `## Run and report`.
section() {
  local l on=0
  SEC=""; HAS_SEC=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "$l" = "$1" ] && { on=1; HAS_SEC=1; }
      continue
    fi
    [ "${l:0:3}" = "## " ] && break
    SEC="$SEC"$'\n'"$l"
  done
  return 0
}

# paragraphs <text>   PG := <text>'s paragraphs (maximal runs of non-blank
# lines), each flattened as `flat` does.
paragraphs() {
  local l cur=""; local -a xs
  PG=()
  mapfile -t xs <<<"$1"
  for l in "${xs[@]}" ""; do
    if blank "$l"; then
      [ -n "$cur" ] && PG+=("$cur")
      cur=""
    else
      trim "$l"
      if [ -z "$cur" ]; then cur="$T"; else cur="$cur $T"; fi
    fi
  done
  return 0
}

# --- the guard ----------------------------------------------------------------

# dispatch_problems <root>   One line `<relative-path>: <reason>` per
# violation (Contract C-5 as amended, byte for byte); silent when compliant.
# Always returns 0: the output is the verdict.
dispatch_problems() {
  local root="$1" ks kb kc k p long=0 full=0 rung=0 check=0 w
  # advance-story: GREEN -> GATES, the self-test step, the boundaries step.
  if [ ! -f "$root/$ADVANCE" ]; then
    printf '%s: file is missing\n' "$ADVANCE"
  else
    load "$root/$ADVANCE"
    gg_region
    if [ "$HAS_GG" = 0 ] || ! all_in "$G" "${GG_NEEDLES[@]}"; then
      printf '%s\n' "$L_GG"
    fi
    gates_steps
    first_step "$STEP_SELFTEST"; ks=$K
    if [ "$ks" = "-1" ]; then
      # HARNESS-095: a step naming the full run instead is the HARNESS-094
      # text, and says so; no self-test step at all is the old line.
      first_step "$STEP_FULL"
      if [ "$K" != "-1" ]; then printf '%s\n' "$L_NOCHANGED"; else printf '%s\n' "$L_SELFTEST"; fi
    elif ! all_in "${ST[$ks]}" "${SELFTEST_NEEDLES[@]}"; then
      printf '%s\n' "$L_SELFTEST"
    fi
    # The boundaries step: judged only when it exists. Its absence, and its
    # order against the phase step, are procedure.test.sh's to report.
    first_step "$STEP_BOUNDARIES"; kb=$K
    if [ "$kb" != "-1" ]; then
      flat "${ST[$kb]}"
      case "$F" in *"$DISPATCHED"*) printf '%s\n' "$L_BOUND" ;; esac
      kc=-1
      for k in "${!ST[@]}"; do
        [[ ${ST[$k]} =~ $COMMIT_RE ]] && { kc=$k; break; }
      done
      if [ "$kc" = "-1" ] || [ "${SN[$kc]}" -ge "${SN[$kb]}" ]; then
        printf '%s\n' "$L_COMMIT"
      fi
    fi
  fi
  # complete-story: the GATES -> REVIEW bullet.
  if [ ! -f "$root/$COMPLETE" ]; then
    printf '%s: file is missing\n' "$COMPLETE"
  else
    load "$root/$COMPLETE"
    gates_bullet
    if [ "$HAS_BULLET" = 0 ] || ! all_in "$R" "${BULLET_NEEDLES[@]}"; then
      printf '%s\n' "$L_BULLET"
    fi
  fi
  # lead-po: ## Orchestrating.
  if [ ! -f "$root/$LEADPO" ]; then
    printf '%s: file is missing\n' "$LEADPO"
  else
    load "$root/$LEADPO"
    section "$ORCH_HEAD"
    paragraphs "$SEC"
    for p in "${PG[@]}"; do
      all_in "$p" "${LONG_NEEDLES[@]}" && long=1
      # HARNESS-095: the HARNESS-094 paragraph - the full run, dispatched, and
      # no `--changed` anywhere in it.
      case "$p" in
        *"$STEP_FULL"*)
          case "$p" in *--changed*) ;; *"$DISPATCHED"*) full=1 ;; esac ;;
      esac
      case "$p" in *"$OLD_RUNG"*) rung=1 ;; esac
      case "$p" in *"$ATTEST_CHECK"*) check=1 ;; esac
    done
    if [ "$long" = 0 ]; then
      if [ "$full" = 1 ]; then printf '%s\n' "$L_LONG_CHANGED"; else printf '%s\n' "$L_LONG"; fi
    fi
    [ "$rung" = 0 ] || printf '%s\n' "$L_RUNG"
    [ "$check" = 1 ] || printf '%s\n' "$L_CHECK"
  fi
  # feature-developer: ## Run and report.
  if [ ! -f "$root/$FEATDEV" ]; then
    printf '%s: file is missing\n' "$FEATDEV"
  else
    load "$root/$FEATDEV"
    section "$RUN_HEAD"
    if [ "$HAS_SEC" = 0 ]; then
      printf '%s\n' "$L_NOHEAD"
    else
      flat "$SEC"
      for w in "${RUN_NEEDLES[@]}"; do
        case "$F" in *"$w"*) ;; *) l_runsay "$w"; printf '\n' ;; esac
      done
    fi
  fi
  return 0
}

# --- a compliant fixture, by construction -------------------------------------
# Never copied from the real tree, which in RED is not compliant. The wording
# is nobody's contract; GREEN writes the real files (C-2..C-4). Every needle
# appears exactly once in the piece that must carry it, so replacing it in that
# piece removes it.

# The GREEN -> GATES region. The `**value**` line sits MID-paragraph, before
# every needle, so a region that ended at any `**` line would lose them all and
# the compliant fixture would not be silent.
GG_GOOD="$(cat <<'EOF'
**GREEN → GATES.** Set the phase, then run the deferred verifications
that GATES owns, through `scripts/mutate.sh`; by default one
**value** mutation at most.

Then dispatch a `feature-developer` on the GATES row of `models.conf` to run
`bash scripts/attest.sh -- bash scripts/gates.sh` from the worktree; it returns
the exit status, the last line, the duration and the log path. Check it with
`bash scripts/attest.sh check -- bash scripts/gates.sh` and require `fresh`.
EOF
)"
# Today's region (advance-story.md:159): the orchestrator runs it. It names the
# feature-developer only as the route a failure takes.
GG_TODAY="$(cat <<'EOF'
**GREEN → GATES.** Set the phase, then run the deferred verifications
that GATES owns, through `scripts/mutate.sh`; by default one
**value** mutation at most.

Then run `bash scripts/gates.sh`. It writes
its own summary into the story's `## Gate results`; never paste or edit one.
On failure, dispatch the **feature-developer** to fix it, unless the failure
means a test is wrong.
EOF
)"
GG_AFTER='**The stamp covers tracked and staged files only.** Stage new files.'

# HARNESS-101 (C-3): step 1 in the new words - a lead-po dispatch on the
# DIFF-REVIEW row. dispatch_problems does not read step 1; row_problems below
# does, from its own fixtures.
S1='1. Review the change with the `diff-review` skill: a fresh `lead-po` dispatch on the DIFF-REVIEW row.'
# HARNESS-095: step 2 names the `--changed` run as a bare span, dispatches it
# through `attest.sh --` and checks it with `attest.sh check --`, each span
# once, so removing one removes only it.
S2_GOOD="$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; on skip, paste its line into `## Notes`.
   On run, `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`: dispatch a
   `feature-developer` to run
   `bash scripts/attest.sh -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`
   detached and alone on Windows beside other test runs; it returns its
   verdict, and you check it with
   `bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`.
EOF
)"
# HARNESS-095 (AC-4): the HARNESS-085-compliant step as it reads at HARNESS-094,
# the full-run spelling throughout. Reported as not naming `--changed`.
S2_FULL="${S2_GOOD//selftest.sh --changed/selftest.sh}"
# Today's step 2 before HARNESS-085: the orchestrator runs it; feature-developer
# is the failure route, and `alone` is in the history, but there is no verdict
# or check. HARNESS-095 moved its run to the `--changed` span so that it stays
# the "does not dispatch" control rather than becoming a "does not name" one.
S2_TODAY="$(cat <<'EOF'
2. `bash scripts/selftest-needed.sh`; on skip, paste its line into `## Notes`.
   On run, `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`. Run it detached on
   Windows beside other test runs; one run passed alone. Paste its exit
   status and last line. A failure takes GATES' routes: the feature-developer.
EOF
)"
S3='3. `bash scripts/phase.sh set $1 REVIEW`'
S4='4. Commit, with a message that names the story.'
S5_GOOD='5. `bash scripts/check-boundaries.sh` — run it yourself; it takes seconds.'
S6='6. Push the branch and open a PR.'

# write_advance <dir> <gg-region> <steps>
write_advance() {
  {
    printf -- '---\ndescription: Move one story forward\n---\n\nStory: $1\n\n'
    printf '%s\n\n%s\n\n' "$2" "$GG_AFTER"
    printf '%s Only when every required gate passes.\n\nThen, **in this order**:\n\n' "$PARA_START"
    printf '%s\n\n' "$3"
    printf '**REVIEW → DONE.** Only once the PR is merged.\n'
  } > "$1/$ADVANCE"
}

# steps <s2> <s5> [<s4>]   The six steps, with step 2, step 5 and step 4 given.
steps() { printf '%s\n%s\n%s\n%s\n%s\n%s' "$S1" "$1" "$S3" "${3:-$S4}" "$2" "$S6"; }

BULLET_GOOD="$(cat <<'EOF'
- **GATES → REVIEW opens with a `diff-review`**, then the full gates and the
  `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed` self-test each run in a
  feature-developer dispatch on the GATES row that returns a verdict, checked
  with `bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`.
EOF
)"
# HARNESS-095: the bullet as it reads at HARNESS-094 - the dispatch and its
# verdict, a bare `attest.sh check`, no GATES row and no `--changed` check.
BULLET_094="$(cat <<'EOF'
- **GATES → REVIEW opens with a `diff-review`**, then the full gates and the
  self-test each run in a feature-developer dispatch that returns a verdict,
  checked with `bash scripts/attest.sh check`.
EOF
)"
# Today's bullet: feature-developer names the review, `Verdict` is capital.
BULLET_TODAY="$(cat <<'EOF'
- **GATES → REVIEW opens with a review**, on a fresh feature-developer
  dispatch, and goes on only on `Verdict: Ship.`; then the full
  `SELFTEST_JOBS=4 bash scripts/selftest.sh` runs, detached and alone.
EOF
)"

# write_complete <dir> <bullet>
write_complete() {
  {
    printf -- '---\ndescription: Drive one story\n---\n\n'
    printf -- '- **RED and GREEN each end with `bash scripts/gates.sh --fast`.**\n'
    printf '%s\n' "$2"
    printf -- '- **A return to RED ends with pasted red.**\n\nThe end.\n'
  } > "$1/$COMPLETE"
}

# The three ## Orchestrating paragraphs that carry the needles.
RUNG_GOOD="$(cat <<'EOF'
Verification is a ladder, and every rung is something you run or have run
under `scripts/attest.sh` and check:
EOF
)"
RUNG_TODAY="$(cat <<'EOF'
Verification is a ladder, and every rung is something you run, not something
you are told:
EOF
)"
CHECK_GOOD='- `bash scripts/attest.sh check -- <the same words>` says whether it ran here.'
# HARNESS-095: the long-run paragraph names the `--changed` run, the full run
# as the option, the GATES row and the `--changed` check.
LONG_GOOD="$(cat <<'EOF'
The long runs, `bash scripts/gates.sh` and `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`
(or the full `SELFTEST_JOBS=4 bash scripts/selftest.sh` when /advance-story says so),
go to a `feature-developer` on the GATES row and come back as a verdict you
check with `bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`;
`bash scripts/check-boundaries.sh` stays yours.
EOF
)"
# HARNESS-095: the paragraph as it reads at HARNESS-094 (lead-po.md:41).
LONG_094="$(cat <<'EOF'
The two long runs, the full `bash scripts/gates.sh` and
`SELFTEST_JOBS=4 bash scripts/selftest.sh`, are not yours to wait on. Each goes
to a `feature-developer` on the GATES row and comes back as a verdict you check
with `bash scripts/attest.sh check`.
EOF
)"

# write_leadpo <dir> <rung> <check> <long> [<after-section>]
write_leadpo() {
  {
    printf -- '---\nname: lead-po\n---\n\n## Decomposing\n\nCut stories small.\n\n'
    printf '%s\n\nDispatch each specialist.\n\n%s\n\n%s\n\n%s\n\n' "$ORCH_HEAD" "$2" "$3" "$4"
    printf '## More than one worktree\n\nOne lock per tree.\n'
    [ -n "${5:-}" ] && printf '\n%s\n' "$5"
  } > "$1/$LEADPO"
}

RUN_GOOD="$(cat <<'EOF'
When the brief names one command and nothing to build, run it through
`bash scripts/attest.sh -- <command>` from the worktree named, alone: nothing
else in that tree while it runs. You change nothing - except a required gate
that fails under `bash scripts/gates.sh`, fixed under this file's GATES rules
and run again. Return the record's `exit:`, `last:`, `duration:` and `log:`
fields and the model you resolved to; never the whole output.
EOF
)"

# write_featdev <dir> <heading> <section-body> [<after>]
write_featdev() {
  {
    printf -- '---\nname: feature-developer\n---\n\n## Method\n\n1. Read the story.\n\n'
    printf '%s\n\n%s\n\n' "$2" "$3"
    printf '## Reuse before you write\n\nLook first.\n'
    [ -n "${4:-}" ] && printf '\n%s\n' "$4"
  } > "$1/$FEATDEV"
}

compliant_fixture() { # <dir>
  write_advance "$1" "$GG_GOOD" "$(steps "$S2_GOOD" "$S5_GOOD")"
  write_complete "$1" "$BULLET_GOOD"
  write_leadpo "$1" "$RUNG_GOOD" "$CHECK_GOOD" "$LONG_GOOD"
  write_featdev "$1" "$RUN_HEAD" "$RUN_GOOD"
}

# fresh_case <name>   d := a new compliant fixture's path. Sets d rather than
# echoing it, and makes both directories with one mkdir (a fork costs about a
# quarter of a second on Windows, HARNESS-068).
fresh_case() {
  d="$WORK/$1"
  [ -e "$d" ] && rm -rf "$d"
  mkdir -p "$d/.claude/commands" "$d/.claude/agents"
  compliant_fixture "$d"
}

# ---------------------------------------------------------------------------
describe "the real tree (AC-1 to AC-5)"

missing=""
for f in "$ADVANCE" "$COMPLETE" "$LEADPO" "$FEATDEV"; do
  [ -f "$REPO_ROOT/$f" ] || missing="$missing $f"
done
assert_eq "the four files this suite reads exist in this repository" "" "$missing"

assert_eq "dispatch_problems over the real tree prints nothing: GREEN → GATES and the self-test step dispatch a feature-developer and check its verdict with attest.sh check, check-boundaries stays the orchestrator's and comes after the commit, complete-story's bullet names the dispatch and its verdict, lead-po's ## Orchestrating dispatches the long runs and no longer says every rung is run by you, and feature-developer.md has ## Run and report; and (HARNESS-095) the self-test step, the bullet and lead-po's long-run paragraph name \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` and its \`attest.sh check\` on the GATES row" \
  "" "$(dispatch_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "the fixture: compliant by construction"

fresh_case compliant
assert_eq "the compliant fixture is silent" "" "$(dispatch_problems "$d")"

fresh_case wrapped
write_advance "$d" "${GG_GOOD//check -- bash/check --
  bash}" "$(steps "${S2_GOOD//check -- SELFTEST/check --
   SELFTEST}" "$S5_GOOD")"
write_featdev "$d" "$RUN_HEAD" "${RUN_GOOD//change nothing/change
nothing}"
assert_eq "a needle reflowed across a line break still counts: the fixture stays silent" \
  "" "$(dispatch_problems "$d")"

fresh_case crlf
for f in "$ADVANCE" "$COMPLETE" "$LEADPO" "$FEATDEV"; do
  c="$(cat "$d/$f")"; printf '%s\r\n' "${c//$'\n'/$'\r\n'}" > "$d/$f"
done
assert_eq "a CRLF checkout reads the same as an LF one: silent" "" "$(dispatch_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-1: the GREEN → GATES region dispatches the full gate run"

fresh_case gg-today
write_advance "$d" "$GG_TODAY" "$(steps "$S2_GOOD" "$S5_GOOD")"
assert_eq "control: the region as it reads today (\`Then run \`bash scripts/gates.sh\`.\`, no dispatch) gives exactly one line" \
  "$L_GG" "$(dispatch_problems "$d")"

for w in "${GG_NEEDLES[@]}"; do
  fresh_case "gg-without-$w"
  write_advance "$d" "${GG_GOOD//"$w"/elsewhere}" "$(steps "$S2_GOOD" "$S5_GOOD")"
  assert_eq "the region without \`$w\` gives exactly the one GREEN → GATES line" \
    "$L_GG" "$(dispatch_problems "$d")"
done

fresh_case gg-check-in-review
gg="${GG_GOOD//bash scripts\/attest.sh check -- bash scripts\/gates.sh/the record}"
write_advance "$d" "$gg" "$(steps "$S2_GOOD" "$S5_GOOD")"
printf '\n%s\n' 'Also check `bash scripts/attest.sh check -- bash scripts/gates.sh`.' >> "$d/$ADVANCE"
assert_eq "the check named only outside the region (after REVIEW → DONE) gives the one line" \
  "$L_GG" "$(dispatch_problems "$d")"

fresh_case gg-ends-at-bold-paragraph
gg="${GG_GOOD/$'\n''**value**'/$'\n\n''**value**'}"
write_advance "$d" "$gg" "$(steps "$S2_GOOD" "$S5_GOOD")"
assert_eq "a paragraph that BEGINS \`**\` ends the region, so the dispatch after it is not in it: one line" \
  "$L_GG" "$(dispatch_problems "$d")"

fresh_case gg-no-region
write_advance "$d" "${GG_GOOD//'**GREEN → GATES.**'/'**GREEN -> GATES.**'}" "$(steps "$S2_GOOD" "$S5_GOOD")"
assert_eq "no \`**GREEN → GATES.**\` line at all (an ascii arrow) gives the one line" \
  "$L_GG" "$(dispatch_problems "$d")"

fresh_case gg-check-fast
write_advance "$d" "${GG_GOOD//check -- bash scripts\/gates.sh\`/check -- bash scripts\/gates.sh --fast\`}" "$(steps "$S2_GOOD" "$S5_GOOD")"
assert_eq "a check of \`bash scripts/gates.sh --fast\` is not a check of the full run (a different record): one line" \
  "$L_GG" "$(dispatch_problems "$d")"

fresh_case gg-run-fast
write_advance "$d" "${GG_GOOD//attest.sh -- bash scripts\/gates.sh\`/attest.sh -- bash scripts\/gates.sh --fast\`}" "$(steps "$S2_GOOD" "$S5_GOOD")"
assert_eq "dispatching \`bash scripts/gates.sh --fast\` is not dispatching the full run: one line" \
  "$L_GG" "$(dispatch_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-2: the self-test step dispatches the run and checks its verdict"

fresh_case st-today
write_advance "$d" "$GG_GOOD" "$(steps "$S2_TODAY" "$S5_GOOD")"
assert_eq "control: the step as it reads today (the orchestrator runs it) gives exactly one line" \
  "$L_SELFTEST" "$(dispatch_problems "$d")"

for w in "${SELFTEST_NEEDLES[@]}"; do
  fresh_case "st-without-$w"
  write_advance "$d" "$GG_GOOD" "$(steps "${S2_GOOD//"$w"/elsewhere}" "$S5_GOOD")"
  assert_eq "the self-test step without \`$w\` gives exactly the one self-test line" \
    "$L_SELFTEST" "$(dispatch_problems "$d")"
done

fresh_case st-check-without-jobs
write_advance "$d" "$GG_GOOD" "$(steps "${S2_GOOD//check -- SELFTEST_JOBS=4 bash/check -- bash}" "$S5_GOOD")"
assert_eq "a check of \`bash scripts/selftest.sh\` without \`SELFTEST_JOBS=4\` is a different record (check is keyed by the exact words): one line" \
  "$L_SELFTEST" "$(dispatch_problems "$d")"

fresh_case st-check-targeted
write_advance "$d" "$GG_GOOD" "$(steps "${S2_GOOD//--changed\`./--changed dispatch\`.}" "$S5_GOOD")"
assert_eq "a check of a targeted \`... selftest.sh --changed dispatch\` is not a check of the \`--changed\` run: one line" \
  "$L_SELFTEST" "$(dispatch_problems "$d")"

fresh_case st-words-in-next-step
s2="2. \`bash scripts/selftest-needed.sh\`; on run, $STEP_SELFTEST on Windows beside other test runs; skip into \`## Notes\`."
s3="3. \`bash scripts/phase.sh set \$1 REVIEW\` once a \`feature-developer\` ran it detached and alone and its verdict passed \`bash scripts/attest.sh -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` and \`bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\`."
write_advance "$d" "$GG_GOOD" "$(printf '%s\n%s\n%s\n%s\n%s\n%s' "$S1" "$s2" "$s3" "$S4" "$S5_GOOD" "$S6")"
assert_eq "the dispatch words in a DIFFERENT step do not satisfy the self-test step: one line" \
  "$L_SELFTEST" "$(dispatch_problems "$d")"

fresh_case st-no-step
write_advance "$d" "$GG_GOOD" "$(steps "${S2_GOOD//"$STEP_SELFTEST"/the self-test}" "$S5_GOOD")"
assert_eq "no step holding \`SELFTEST_JOBS=4 bash scripts/selftest.sh\` gives the one self-test line" \
  "$L_SELFTEST" "$(dispatch_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-3: check-boundaries stays the orchestrator's own run, after the commit"

fresh_case bound-dispatched
write_advance "$d" "$GG_GOOD" "$(steps "$S2_GOOD" '5. `bash scripts/check-boundaries.sh` — dispatch a `feature-developer` to run it and check its verdict.')"
assert_eq "control: a step that dispatches check-boundaries to a feature-developer gives exactly one line" \
  "$L_BOUND" "$(dispatch_problems "$d")"

fresh_case bound-dispatched-continuation
write_advance "$d" "$GG_GOOD" "$(steps "$S2_GOOD" '5. `bash scripts/check-boundaries.sh`, run through a
   feature-developer dispatch.')"
assert_eq "the dispatch on the step's continuation line is in the step: one line" \
  "$L_BOUND" "$(dispatch_problems "$d")"

fresh_case bound-neighbour
write_advance "$d" "$GG_GOOD" "$(printf '%s\n%s\n%s\n%s\n%s\n%s' "$S1" "$S2_GOOD" "$S3" "$S4" "$S5_GOOD" '6. Push; a feature-developer may help with the PR body.')"
assert_eq "feature-developer in the NEXT step is not in the check-boundaries step: silent" \
  "" "$(dispatch_problems "$d")"

fresh_case bound-before-commit
write_advance "$d" "$GG_GOOD" "$(printf '%s\n%s\n%s\n%s\n%s\n%s' "$S1" "$S2_GOOD" "$S3" "4. ${S5_GOOD#5. }" "5. ${S4#4. }" "$S6")"
assert_eq "check-boundaries moved before the commit step gives exactly one line" \
  "$L_COMMIT" "$(dispatch_problems "$d")"

fresh_case bound-no-commit
write_advance "$d" "$GG_GOOD" "$(steps "$S2_GOOD" "$S5_GOOD" '4. Record the change.')"
assert_eq "no step beginning \`Commit\` gives the one commit-order line" \
  "$L_COMMIT" "$(dispatch_problems "$d")"

fresh_case bound-missing
write_advance "$d" "$GG_GOOD" "$(steps "$S2_GOOD" '5. Run the boundary check.')"
assert_eq "no check-boundaries step is procedure.test.sh's to report: this suite is silent" \
  "" "$(dispatch_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-4: complete-story's bullet and lead-po's ## Orchestrating"

fresh_case bullet-today
write_complete "$d" "$BULLET_TODAY"
assert_eq "control: the bullet as it reads today (feature-developer for the review, only a capital \`Verdict\`) gives exactly one line" \
  "$L_BULLET" "$(dispatch_problems "$d")"

for w in "${BULLET_NEEDLES[@]}"; do
  fresh_case "bullet-without-$w"
  write_complete "$d" "${BULLET_GOOD//"$w"/elsewhere}"
  assert_eq "the bullet without \`$w\` gives exactly one line" \
    "$L_BULLET" "$(dispatch_problems "$d")"
done

fresh_case bullet-next
write_complete "$d" "${BULLET_GOOD//verdict/result}
- The dispatch returns a verdict."
assert_eq "\`verdict\` only in the NEXT bullet is not in this one: one line" \
  "$L_BULLET" "$(dispatch_problems "$d")"

fresh_case bullet-none
write_complete "$d" '- **REVIEW → DONE** merges; a feature-developer returns a verdict.'
assert_eq "no \`- **GATES → REVIEW\` bullet gives the one line" \
  "$L_BULLET" "$(dispatch_problems "$d")"

fresh_case lead-today
write_leadpo "$d" "$RUNG_TODAY" "$CHECK_GOOD" 'Run the long runs yourself.'
assert_eq "lead-po as it reads today (the old rung sentence, no dispatch paragraph) gives the two lead-po lines, dispatch first" \
  "$L_LONG
$L_RUNG" "$(dispatch_problems "$d")"

fresh_case lead-rung
write_leadpo "$d" "$RUNG_TODAY" "$CHECK_GOOD" "$LONG_GOOD"
assert_eq "the old rung sentence still present gives exactly one line" \
  "$L_RUNG" "$(dispatch_problems "$d")"

fresh_case lead-rung-wrapped
write_leadpo "$d" 'Verification is a ladder, and every rung is something you run,
not something you are told:' "$CHECK_GOOD" "$LONG_GOOD"
assert_eq "the old rung sentence reflowed after \`run,\` is the same sentence: one line" \
  "$L_RUNG" "$(dispatch_problems "$d")"

fresh_case lead-no-fd
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" "${LONG_GOOD//"$DISPATCHED"/subagent}"
assert_eq "the long-run paragraph without \`feature-developer\` gives exactly one line" \
  "$L_LONG" "$(dispatch_problems "$d")"

fresh_case lead-no-selftest
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" "${LONG_GOOD//"$LONG_RUN"/the self-test}"
assert_eq "the long-run paragraph without the bare \`SELFTEST_JOBS=4 bash scripts/selftest.sh --changed\` span (its check still says \`--changed\`) gives exactly the dispatch line" \
  "$L_LONG" "$(dispatch_problems "$d")"

fresh_case lead-split-paragraphs
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" 'The long run is `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`.

It goes to a `feature-developer` on the GATES row, checked with `bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`.'
assert_eq "the two needles in DIFFERENT paragraphs of the section give exactly one line" \
  "$L_LONG" "$(dispatch_problems "$d")"

fresh_case lead-other-section
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" 'Run the long runs as the steps say.' \
  "$LONG_GOOD"
assert_eq "the long-run paragraph only in a LATER section gives exactly one line" \
  "$L_LONG" "$(dispatch_problems "$d")"

fresh_case lead-no-check
write_leadpo "$d" "$RUNG_GOOD" '- Read the record it left.' "${LONG_GOOD//"$CHECK_CHANGED"/the record\`}"
assert_eq "## Orchestrating without \`bash scripts/attest.sh check\` anywhere gives the check line; since HARNESS-095 the long-run paragraph must carry the \`--changed\` check, so removing it there gives the long-run line first" \
  "$L_LONG
$L_CHECK" "$(dispatch_problems "$d")"

fresh_case lead-no-check-elsewhere
write_leadpo "$d" "$RUNG_GOOD" '- Read the record it left.' "$LONG_GOOD"
assert_eq "the \`--changed\` check in the long-run paragraph is itself a \`bash scripts/attest.sh check\`: silent" \
  "" "$(dispatch_problems "$d")"

fresh_case lead-no-section
c="$(cat "$d/$LEADPO")"; printf '%s\n' "${c//"$ORCH_HEAD"/## Orchestration}" > "$d/$LEADPO"
assert_eq "no line exactly \`## Orchestrating\` gives the dispatch and check lines, and no rung line" \
  "$L_LONG
$L_CHECK" "$(dispatch_problems "$d")"

# ---------------------------------------------------------------------------
describe "AC-5: feature-developer.md has ## Run and report"

fresh_case fd-no-heading
write_featdev "$d" '## Running' "$RUN_GOOD"
assert_eq "control: no \`## Run and report\` heading gives exactly one line" \
  "$L_NOHEAD" "$(dispatch_problems "$d")"

fresh_case fd-no-change-nothing
write_featdev "$d" "$RUN_HEAD" "${RUN_GOOD//change nothing/may edit}"
assert_eq "control: the heading present and no \`change nothing\` gives exactly one line" \
  "$(l_runsay 'change nothing')" "$(dispatch_problems "$d")"

for w in "${RUN_NEEDLES[@]}"; do
  fresh_case "fd-without-$w"
  write_featdev "$d" "$RUN_HEAD" "${RUN_GOOD//"$w"/elsewhere}"
  assert_eq "## Run and report without \`$w\` gives exactly one line naming it" \
    "$(l_runsay "$w")" "$(dispatch_problems "$d")"
done

fresh_case fd-heading-suffixed
write_featdev "$d" '## Run and report (dispatch)' "$RUN_GOOD"
assert_eq "a heading that only BEGINS \`## Run and report\` is not it: one line" \
  "$L_NOHEAD" "$(dispatch_problems "$d")"

fresh_case fd-needle-after-section
write_featdev "$d" "$RUN_HEAD" "${RUN_GOOD//alone/by itself}" 'Run it alone.'
assert_eq "a needle only in the NEXT section is not in ## Run and report: one line" \
  "$(l_runsay alone)" "$(dispatch_problems "$d")"

fresh_case fd-all-gone
write_featdev "$d" "$RUN_HEAD" 'Run what you are told.'
assert_eq "an empty-of-needles section gives one line per needle, in C-5's order" \
  "$(for w in "${RUN_NEEDLES[@]}"; do l_runsay "$w"; printf '\n'; done)" "$(dispatch_problems "$d")"

# ---------------------------------------------------------------------------
describe "missing files, and the order of the lines"

for f in "$ADVANCE" "$COMPLETE" "$LEADPO" "$FEATDEV"; do
  fresh_case "missing-${f##*/}"
  rm -f "$d/$f"
  assert_eq "a missing $f gives only \`file is missing\`" \
    "$f: file is missing" "$(dispatch_problems "$d")"
done

fresh_case today
write_advance "$d" "$GG_TODAY" "$(steps "$S2_TODAY" "$S5_GOOD")"
write_complete "$d" "$BULLET_TODAY"
write_leadpo "$d" "$RUNG_TODAY" "$CHECK_GOOD" 'Run the long runs yourself.'
write_featdev "$d" '## Running' 'Run what you are told.'
assert_eq "a tree WITHOUT HARNESS-085's edits prints six lines: advance-story's two, complete-story's, lead-po's two, feature-developer's" \
  "$L_GG
$L_SELFTEST
$L_BULLET
$L_LONG
$L_RUNG
$L_NOHEAD" "$(dispatch_problems "$d")"

# ---------------------------------------------------------------------------
# HARNESS-095: the long run is `SELFTEST_JOBS=4 bash scripts/selftest.sh
# --changed`. Expected lines are written out literally where they are new.
describe "HARNESS-095 AC-4: the self-test step names the \`--changed\` run, and the full-run spelling does not"

fresh_case st-full-094
write_advance "$d" "$GG_GOOD" "$(steps "$S2_FULL" "$S5_GOOD")"
assert_eq "control: the HARNESS-085-compliant step with the full-run spelling throughout (\`--changed\` absent) gives exactly one line naming the file and the \`--changed\` command" \
  '.claude/commands/advance-story.md: the self-test step does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(dispatch_problems "$d")"

fresh_case st-bare-full
write_advance "$d" "$GG_GOOD" "$(steps "${S2_GOOD//"$STEP_SELFTEST"/$STEP_FULL}" "$S5_GOOD")"
assert_eq "only the bare run regressed to the full-run spelling (the attest spans still \`--changed\`) is a step with no \`--changed\` run named: one \"does not name\" line" \
  "$L_NOCHANGED" "$(dispatch_problems "$d")"

fresh_case st-run-full
write_advance "$d" "$GG_GOOD" "$(steps "${S2_GOOD//"$RUN_CHANGED"/bash scripts/attest.sh -- SELFTEST_JOBS=4 bash scripts/selftest.sh\`}" "$S5_GOOD")"
assert_eq "dispatching \`bash scripts/attest.sh -- SELFTEST_JOBS=4 bash scripts/selftest.sh\` (the full run) is not dispatching the \`--changed\` run: one line" \
  "$L_SELFTEST" "$(dispatch_problems "$d")"

fresh_case st-check-full
write_advance "$d" "$GG_GOOD" "$(steps "${S2_GOOD//"$CHECK_CHANGED"/bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh\`}" "$S5_GOOD")"
assert_eq "checking \`bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh\` is checking a different record from the \`--changed\` run: one line" \
  "$L_SELFTEST" "$(dispatch_problems "$d")"

describe "HARNESS-095 AC-3: complete-story's bullet and lead-po's long-run paragraph name the \`--changed\` run and its check"

fresh_case bullet-094
write_complete "$d" "$BULLET_094"
assert_eq "control: the bullet as it reads at HARNESS-094 (a bare \`attest.sh check\`, no GATES row) gives exactly one line" \
  "$L_BULLET" "$(dispatch_problems "$d")"

fresh_case bullet-check-full
write_complete "$d" "${BULLET_GOOD//"$CHECK_CHANGED"/bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh\`}"
assert_eq "a bullet checking the full run rather than the \`--changed\` run gives exactly one line" \
  "$L_BULLET" "$(dispatch_problems "$d")"

fresh_case lead-094
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" "$LONG_094"
assert_eq "control: the long-run paragraph as it reads at HARNESS-094 (the full run, dispatched, no \`--changed\`) gives exactly one line naming the file and the \`--changed\` command" \
  '.claude/agents/lead-po.md: its long-run paragraph does not name `SELFTEST_JOBS=4 bash scripts/selftest.sh --changed`' \
  "$(dispatch_problems "$d")"

fresh_case lead-regressed
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" "${LONG_GOOD//selftest.sh --changed/selftest.sh}"
assert_eq "control: the compliant paragraph with every \`--changed\` deleted (DV-1's mutation) gives exactly the \"does not name\" line" \
  "$L_LONG_CHANGED" "$(dispatch_problems "$d")"

fresh_case lead-check-full
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" "${LONG_GOOD//"$CHECK_CHANGED"/bash scripts/attest.sh check -- SELFTEST_JOBS=4 bash scripts/selftest.sh\`}"
assert_eq "a long-run paragraph that names the \`--changed\` run but checks the full run gives exactly the dispatch line" \
  "$L_LONG" "$(dispatch_problems "$d")"

fresh_case lead-no-gates-row
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" "${LONG_GOOD//GATES row/GATES phase}"
assert_eq "a long-run paragraph without \`GATES row\` gives exactly the dispatch line" \
  "$L_LONG" "$(dispatch_problems "$d")"

fresh_case lead-full-undispatched
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" "${LONG_094//"$DISPATCHED"/subagent}"
assert_eq "the HARNESS-094 paragraph without \`feature-developer\` is not dispatching at all: the dispatch line, not the \"does not name\" one" \
  "$L_LONG" "$(dispatch_problems "$d")"

describe "HARNESS-095 AC-4: the lines the tree at HARNESS-094 prints, in order"

fresh_case today-094
write_advance "$d" "$GG_GOOD" "$(steps "$S2_FULL" "$S5_GOOD")"
write_complete "$d" "$BULLET_094"
write_leadpo "$d" "$RUNG_GOOD" "$CHECK_GOOD" "$LONG_094"
assert_eq "the HARNESS-094 text in all three files gives three lines: advance-story's \"does not name\", complete-story's bullet, lead-po's \"does not name\"" \
  "$L_NOCHANGED
$L_BULLET
$L_LONG_CHANGED" "$(dispatch_problems "$d")"


# ===========================================================================
# HARNESS-101: who is dispatched on which row (AC-3, AC-4, AC-6) and the
# model split stated where the rules live (AC-7).
#
# The user's call of 2026-11-11: `/advance-story` and `/complete-story` run on
# `opus`, and `fable` is reached inside a story by DISPATCH - a `lead-po` on
# the PLANNED row for the PLANNED work, on the new DIFF-REVIEW row for the
# diff review that opens GATES -> REVIEW, and on the REVIEW row for feedback
# on the open PR. `lead-po` because it declares `fable`: a dispatch that loses
# its explicit model falls back to the agent's own, and a `feature-developer`
# would land a planned `fable` review on `opus` with nothing saying so (C-2).
#
# `row_problems <root>` is a SECOND guard beside dispatch_problems, not an
# extension of it: it reads three files dispatch_problems does not
# (diff-review's SKILL.md, rules.md, models.conf), and folding them in would
# put a `file is missing` line into every expected output above. Same
# pattern: silent over the real tree, silent over a fixture compliant by
# construction, exactly the pinned lines over a fixture with one thing
# regressed. The needles are C-3's table, read out, plus the RED amendments
# recorded in the story's Contract (the AC-6 region, two must-not needles in
# rules.md, the models.conf header).
#
# One collision is handled on purpose: `REVIEW row` is a substring of
# `DIFF-REVIEW row`, so in the REVIEW -> DONE region `REVIEW row` is matched
# only after every `DIFF-REVIEW row` has been taken out. Without that, a
# region naming only the diff review would satisfy AC-6 (case
# `rd-only-diff-review`).

SKILL=".claude/skills/diff-review/SKILL.md"
RULES=".claude/harness/rules.md"
MODELS=".claude/harness/models.conf"

PL_START='**PLANNED → RED.**'
RD_START='**REVIEW → DONE.**'
CB_PL_START='- **PLANNED → RED'
SK_WHO_HEAD='## Who runs it'
RU_HEAD='# The model each agent runs on'

PL_NEEDLES=('lead-po' 'PLANNED row')
# HARNESS-102 AC-9 (C-10): HARNESS-101 AC-3's read-before-commit sentence, a
# needle of each file's own - not a third member of PL_NEEDLES, which both
# files share. advance-story's region says `read what it returned`; the
# complete-story bullet that names the dispatch says `before you commit at
# PLANNED`. Without them that sentence could be deleted with every suite green.
PL_ADV_NEEDLES=('read what it returned')
CB_PL_READ='before you commit at PLANNED'
STEP1_NEEDLES=('lead-po' 'DIFF-REVIEW row' 'bash scripts/plan.sh models' 'Route' 'bash scripts/classify.sh')
STEP1_NOT=('GATES row')
# HARNESS-102 AC-10 (C-10): the PR-feedback dispatch reads its model as GATES
# -> REVIEW step 1 does, and says so in step 1's words. The same words in step
# 1 are outside this region and do not count.
RD_NEEDLES=('lead-po' 'REVIEW row' 'Route' 'records a departure for that row')
# AC-6: these stay the orchestrator's own, in the same region.
RD_KEEP=('bash scripts/phase.sh clear' 'bash scripts/plan.sh after' 'read the timings')
CB_GR_NEEDLES=('lead-po' 'DIFF-REVIEW row')
CB_GR_NOT=('fresh feature-developer')
SK_DESC_NEEDLES=('lead-po')
SK_DESC_NOT=('feature-developer')
SK_WHO_NEEDLES=('lead-po' 'DIFF-REVIEW row')
SK_WHO_NOT=('feature-developer' 'GATES row')
# HARNESS-102 AC-1 (C-7): the section's lists of `fable` rows gain ADJUDICATE.
RU_NEEDLES=('advance-story' 'complete-story' 'security-audit' 'DIFF-REVIEW' '2026-11-11' 'ADJUDICATE')
RU_NOT=('and the orchestrating commands' 'PLANNED and REVIEW on')
MC_NEEDLES=('DIFF-REVIEW')
MC_NOT=('The orchestrating commands and the planning agents')
LP_NEEDLES=('DIFF-REVIEW row')

# The lines, `<relative-path>: <reason>`.
L_PL_NONE="$ADVANCE: has no PLANNED → RED region"
L_STEP1_NONE="$ADVANCE: GATES → REVIEW has no step 1"
L_RD_NONE="$ADVANCE: has no REVIEW → DONE region"
L_CB_PL="$COMPLETE: no PLANNED → RED bullet says both \`lead-po\` and \`PLANNED row\`"
L_CB_GR_NONE="$COMPLETE: has no GATES → REVIEW bullet"
L_SK_DESC_NONE="$SKILL: has no description in its frontmatter"
L_SK_WHO_NONE="$SKILL: has no ## Who runs it section"
L_RU_NONE="$RULES: has no # The model each agent runs on section"
r_say() { printf '%s: %s does not say `%s`' "$1" "$2" "$3"; }
r_still() { printf '%s: %s still says `%s`' "$1" "$2" "$3"; }

# must_say <path> <label> <text> <needle>...   One r_say line per needle the
# flattened <text> lacks. `REVIEW row` is judged with `DIFF-REVIEW row` taken
# out first (see the header of this block).
must_say() {
  local p="$1" lab="$2" w G2
  flat "$3"; shift 3
  G2="${F//DIFF-REVIEW row/}"
  for w in "$@"; do
    if [ "$w" = 'REVIEW row' ]; then
      case "$G2" in *"$w"*) continue ;; esac
    else
      case "$F" in *"$w"*) continue ;; esac
    fi
    r_say "$p" "$lab" "$w"; printf '\n'
  done
  return 0
}

# must_not <path> <label> <text> <needle>...   One r_still line per needle the
# flattened <text> carries. Flattened, so a phrase reflowed across a line break
# is still present.
must_not() {
  local p="$1" lab="$2" w
  flat "$3"; shift 3
  for w in "$@"; do
    case "$F" in *"$w"*) r_still "$p" "$lab" "$w"; printf '\n' ;; esac
  done
  return 0
}

# marker_line <line>   Succeeds when <line> is a phase marker: it begins `**`,
# has ` → ` in it and `.**` after that - `**RED → GREEN.**`, not
# `**Pin the \`## Contract\`.**`.
marker_line() { [[ $1 == '**'*' → '*'.**'* ]]; }

# pl_region   G := from the line beginning `**PLANNED → RED.**` to just before
# the next marker line, or EOF (C-3 row 1). HAS_G := 1 when it exists.
pl_region() {
  local l on=0
  G=""; HAS_G=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#PL_START}}" = "$PL_START" ] && { on=1; HAS_G=1; G="$l"; }
      continue
    fi
    marker_line "$l" && break
    G="$G"$'\n'"$l"
  done
  return 0
}

# para_region <start>   G := gg_region's rule with another start: from the
# line beginning <start> to just before the next paragraph that begins `**`.
para_region() {
  local l on=0 prev_blank=0
  G=""; HAS_G=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#1}}" = "$1" ] && { on=1; HAS_G=1; G="$l"; }
      continue
    fi
    [ "$prev_blank" = 1 ] && [ "${l:0:2}" = "**" ] && break
    G="$G"$'\n'"$l"
    if blank "$l"; then prev_blank=1; else prev_blank=0; fi
  done
  return 0
}

# pl_bullets   PB := complete-story's bullets beginning `- **PLANNED → RED`,
# each to just before the next line beginning `- ` or a blank line.
pl_bullets() {
  local l on=0 cur=""
  PB=()
  for l in "${LN[@]}"; do
    if [ "$on" = 1 ]; then
      if [ "${l:0:2}" = "- " ] || blank "$l"; then PB+=("$cur"); on=0; cur=""
      else cur="$cur"$'\n'"$l"; continue
      fi
    fi
    [ "${l:0:${#CB_PL_START}}" = "$CB_PL_START" ] && { on=1; cur="$l"; }
  done
  [ "$on" = 1 ] && PB+=("$cur")
  return 0
}

# fm_value <key>   V := the text after `<key>` on the frontmatter line that
# begins with it (frontmatter: line 1 `---` to the next `---`); HAS_V := 1.
fm_value() {
  local i n="${#LN[@]}"
  V=""; HAS_V=0
  [ "$n" -gt 0 ] && [ "${LN[0]}" = "---" ] || return 0
  for ((i = 1; i < n; i++)); do
    [ "${LN[$i]}" = "---" ] && return 0
    case "${LN[$i]}" in "$1"*) V="${LN[$i]#"$1"}"; HAS_V=1; return 0 ;; esac
  done
  return 0
}

# h1_section <heading>   SEC := the lines after the line EQUAL to <heading> up
# to the next line beginning `# `; HAS_SEC := 1 when it exists.
h1_section() {
  local l on=0
  SEC=""; HAS_SEC=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "$l" = "$1" ] && { on=1; HAS_SEC=1; }
      continue
    fi
    [ "${l:0:2}" = "# " ] && break
    SEC="$SEC"$'\n'"$l"
  done
  return 0
}

# comment_text   CT := every line beginning `#`, with the `#` removed,
# newline-joined: models.conf's header and nothing of its rows, so a row
# carrying `DIFF-REVIEW` cannot stand in for the header.
comment_text() {
  local l
  CT=""
  for l in "${LN[@]}"; do
    case "$l" in '#'*) l="${l#\#}"; CT="$CT"$'\n'"$l" ;; esac
  done
  return 0
}

# row_problems <root>   Silent when compliant. Always returns 0.
row_problems() {
  local root="$1" k k1 ok b
  if [ ! -f "$root/$ADVANCE" ]; then
    printf '%s: file is missing\n' "$ADVANCE"
  else
    load "$root/$ADVANCE"
    pl_region
    if [ "$HAS_G" = 0 ]; then printf '%s\n' "$L_PL_NONE"
    else must_say "$ADVANCE" 'PLANNED → RED' "$G" "${PL_NEEDLES[@]}" "${PL_ADV_NEEDLES[@]}"
    fi
    gates_steps
    k1=-1
    for k in "${!SN[@]}"; do [ "${SN[$k]}" = 1 ] && { k1=$k; break; }; done
    if [ "$k1" = "-1" ]; then printf '%s\n' "$L_STEP1_NONE"
    else
      must_say "$ADVANCE" 'GATES → REVIEW step 1' "${ST[$k1]}" "${STEP1_NEEDLES[@]}"
      must_not "$ADVANCE" 'GATES → REVIEW step 1' "${ST[$k1]}" "${STEP1_NOT[@]}"
    fi
    para_region "$RD_START"
    if [ "$HAS_G" = 0 ]; then printf '%s\n' "$L_RD_NONE"
    else must_say "$ADVANCE" 'REVIEW → DONE' "$G" "${RD_NEEDLES[@]}" "${RD_KEEP[@]}"
    fi
  fi
  if [ ! -f "$root/$COMPLETE" ]; then
    printf '%s: file is missing\n' "$COMPLETE"
  else
    load "$root/$COMPLETE"
    pl_bullets
    ok=0
    for b in "${PB[@]}"; do all_in "$b" "${PL_NEEDLES[@]}" && ok=1; done
    [ "$ok" = 1 ] || printf '%s\n' "$L_CB_PL"
    # HARNESS-102 AC-9: a SECOND line, printed only when a dispatch bullet
    # exists, so a tree with no dispatch bullet still gives L_CB_PL alone.
    # The phrase has to be in a bullet that names the dispatch itself.
    if [ "$ok" = 1 ]; then
      ok=0
      for b in "${PB[@]}"; do all_in "$b" "${PL_NEEDLES[@]}" "$CB_PL_READ" && ok=1; done
      [ "$ok" = 1 ] || { r_say "$COMPLETE" 'its PLANNED → RED dispatch bullet' "$CB_PL_READ"; printf '\n'; }
    fi
    gates_bullet
    if [ "$HAS_BULLET" = 0 ]; then printf '%s\n' "$L_CB_GR_NONE"
    else
      must_say "$COMPLETE" 'its GATES → REVIEW bullet' "$R" "${CB_GR_NEEDLES[@]}"
      must_not "$COMPLETE" 'its GATES → REVIEW bullet' "$R" "${CB_GR_NOT[@]}"
    fi
  fi
  if [ ! -f "$root/$SKILL" ]; then
    printf '%s: file is missing\n' "$SKILL"
  else
    load "$root/$SKILL"
    fm_value 'description:'
    if [ "$HAS_V" = 0 ]; then printf '%s\n' "$L_SK_DESC_NONE"
    else
      must_say "$SKILL" 'its description' "$V" "${SK_DESC_NEEDLES[@]}"
      must_not "$SKILL" 'its description' "$V" "${SK_DESC_NOT[@]}"
    fi
    section "$SK_WHO_HEAD"
    if [ "$HAS_SEC" = 0 ]; then printf '%s\n' "$L_SK_WHO_NONE"
    else
      must_say "$SKILL" '## Who runs it' "$SEC" "${SK_WHO_NEEDLES[@]}"
      must_not "$SKILL" '## Who runs it' "$SEC" "${SK_WHO_NOT[@]}"
    fi
  fi
  if [ ! -f "$root/$RULES" ]; then
    printf '%s: file is missing\n' "$RULES"
  else
    load "$root/$RULES"
    h1_section "$RU_HEAD"
    if [ "$HAS_SEC" = 0 ]; then printf '%s\n' "$L_RU_NONE"
    else
      must_say "$RULES" "$RU_HEAD" "$SEC" "${RU_NEEDLES[@]}"
      must_not "$RULES" "$RU_HEAD" "$SEC" "${RU_NOT[@]}"
    fi
  fi
  if [ ! -f "$root/$MODELS" ]; then
    printf '%s: file is missing\n' "$MODELS"
  else
    load "$root/$MODELS"
    comment_text
    must_say "$MODELS" 'its header comment' "$CT" "${MC_NEEDLES[@]}"
    must_not "$MODELS" 'its header comment' "$CT" "${MC_NOT[@]}"
  fi
  if [ ! -f "$root/$LEADPO" ]; then
    printf '%s: file is missing\n' "$LEADPO"
  else
    load "$root/$LEADPO"
    must_say "$LEADPO" 'the file' "$(printf '%s\n' "${LN[@]}")" "${LP_NEEDLES[@]}"
  fi
  return 0
}

# --- HARNESS-101: a compliant fixture, by construction -----------------------
# Never copied from the real tree, which in RED is not compliant. Every needle
# appears exactly once in the region that must carry it. Each region is
# followed by text that carries its needles (or its forbidden words), so a
# region that ran on past its end would be seen.

R_PL_GOOD="$(cat <<'EOF'
**PLANNED → RED.** Confirm the acceptance criteria are testable.

**Pin the `## Contract`.** Module paths and exported names.

The PLANNED work above is done by a `lead-po` dispatch on the PLANNED row of
`models.conf`, not inline. It returns its questions, which you put to the
user; once it is back, read what it returned before you commit the story at
PLANNED.
EOF
)"
# Today's region, in its own words: no dispatch at all.
R_PL_TODAY="$(cat <<'EOF'
**PLANNED → RED.** Confirm the acceptance criteria are testable.

**Pin the `## Contract`.** Module paths and exported names.

Set the phase. Then dispatch the
**test-developer** subagent with the story path.
EOF
)"
# Carries HARNESS-102's `read what it returned`, so a PLANNED → RED region that
# ran on past this marker would be seen.
R_RG='**RED → GREEN.** Check the handoff is filled in; read what it returned.'
R_STEP1_GOOD="$(cat <<'EOF'
1. Review the story's diff and its callers with the `diff-review` skill:
   dispatch a fresh `lead-po` on the DIFF-REVIEW row, its model read from
   `bash scripts/plan.sh models $1`. Each finding carries a Route; the
   orchestrator follows the label, checked first with `bash scripts/classify.sh`.
   A code fix is made by a feature-developer dispatch.
EOF
)"
# Today's step 1 (advance-story.md at 9a10054), word for word.
R_STEP1_TODAY="$(cat <<'EOF'
1. Review the story's diff and its callers with the `diff-review` skill.
   Dispatch a **fresh** `feature-developer`, not the one that wrote the code,
   on the GATES row of `models.conf`; it changes no file and returns its
   report. Paste that report into a `## Diff review` section of the story,
   directly above `## Gate results`, and record the model the dispatch
   resolved to. A Must fix in the code is made in GATES by a feature-developer
   dispatch; the tree has changed, so `bash scripts/gates.sh` runs again and
   these steps start over, with a review of the fix. A finding that needs a
   test added or changed is a return to RED, with a `## Regressions` entry. A
   finding that an acceptance criterion is wrong is an `## Amendments` question
   for the user. Go on only once the report's last line is `Verdict: Ship.`.
   It comes before the self-test because a fix changes the tree, and a fix
   found after the self-test wastes that run.
EOF
)"
# Step 2 carries the long-run words on the GATES row, so a step 1 that ran
# on into step 2 would see `GATES row`.
R_STEP2='2. The self-test, dispatched to a `feature-developer` on the GATES row.'
R_RD_GOOD="$(cat <<'EOF'
**REVIEW → DONE.** Only once the PR is merged. Set the phase to DONE, clear the
lock with `bash scripts/phase.sh clear`, and relay `bash scripts/plan.sh after <id>`.

Feedback on the open PR that asks for a change is read against the contract by
a `lead-po` dispatch on the REVIEW row, which labels each item with a Route; its
model is the one `bash scripts/plan.sh models $1` prints, unless the story's
`## Model guidance` records a departure for that row.

Before you call the PR green, read the timings out of its first CI log.
EOF
)"
R_RD_TODAY="$(cat <<'EOF'
**REVIEW → DONE.** Only once the PR is merged. Set the phase to DONE, clear the
lock with `bash scripts/phase.sh clear`, and relay `bash scripts/plan.sh after <id>`.

Before you call the PR green, read the timings out of its first CI log.
EOF
)"
R_AFTER='**Returning to RED from GREEN or GATES.** A lead-po on the REVIEW row labels a Route, unless Model guidance records a departure for that row.'

# write_r_advance <dir> <pl> <step1> <rd>
write_r_advance() {
  {
    printf -- '---\ndescription: Move one story forward\n---\n\nStory: $1\n\n'
    printf '%s\n\n%s\n\n' "$2" "$R_RG"
    printf '%s Only when every required gate passes.\n\nThen, **in this order**:\n\n' "$PARA_START"
    printf '%s\n%s\n3. `bash scripts/phase.sh set $1 REVIEW`\n\n' "$3" "$R_STEP2"
    printf '%s\n\n%s\n' "$4" "$R_AFTER"
  } > "$1/$ADVANCE"
}

R_CB_PL_GOOD="$(cat <<'EOF'
- **PLANNED → RED pins the `## Contract`** and lists the callers.
- **PLANNED → RED is a dispatch**: a `lead-po` on the PLANNED row does the
  PLANNED work and returns its questions to you; read what it wrote before you
  commit at PLANNED.
EOF
)"
R_CB_PL_TODAY="$(cat <<'EOF'
- **PLANNED → RED pins the `## Contract` and lists the callers of every changed
  signature.** RED cannot find those callers itself.
- **PLANNED → RED names the required gate that would fail if the artifact
  broke.**
EOF
)"
R_CB_GR_GOOD="$(cat <<'EOF'
- **GATES → REVIEW opens with a review of the diff and its callers**, by the
  `diff-review` skill on a fresh `lead-po` dispatch on the DIFF-REVIEW row; the
  full gates and the self-test each run in a feature-developer dispatch.
EOF
)"
R_CB_GR_TODAY="$(cat <<'EOF'
- **GATES → REVIEW opens with a review of the diff and its callers**, by the
  `diff-review` skill on a fresh feature-developer dispatch, and goes on only
  on `Verdict: Ship.`.
EOF
)"
# write_r_complete <dir> <gates-bullet> <planned-bullets>
write_r_complete() {
  {
    printf -- '---\ndescription: Drive one story\n---\n\n'
    printf -- '- **RED and GREEN each end with `bash scripts/gates.sh --fast`.**\n'
    printf '%s\n%s\n' "$2" "$3"
    printf -- '\nA `lead-po` on the PLANNED row, after the bullets, before you commit at PLANNED; a fresh feature-developer.\n'
  } > "$1/$COMPLETE"
}

R_SK_DESC_GOOD='description: Review a whole diff before the PR opens. Use at the first step of GATES → REVIEW, as a fresh lead-po dispatch.'
R_SK_DESC_TODAY='description: Review a whole diff before the PR opens. Use at the first step of GATES → REVIEW, as a fresh feature-developer dispatch.'
R_SK_WHO_GOOD='A **fresh** `lead-po` dispatch on the DIFF-REVIEW row of `.claude/harness/models.conf`.'
R_SK_WHO_TODAY="$(cat <<'EOF'
A **fresh** `feature-developer` dispatch, not the one that wrote the code, on
the GATES row of `.claude/harness/models.conf`.
EOF
)"
# write_r_skill <dir> <description-line> <who-body>
write_r_skill() {
  [ -d "$1/.claude/skills/diff-review" ] || mkdir -p "$1/.claude/skills/diff-review"
  {
    printf -- '---\nname: diff-review\n%s\n---\n\n# Diff review\n\n' "$2"
    printf '%s\n\n%s\n\n' "$SK_WHO_HEAD" "$3"
    printf '## 5. What happens to a finding\n\nA code fix goes to a feature-developer on the GATES row; a lead-po relabels it on the DIFF-REVIEW row.\n'
  } > "$1/$SKILL"
}

R_RU_GOOD="$(cat <<'EOF'
Every definition declares `model:`. Since 2026-11-11 `/advance-story`,
`/complete-story` and `/security-audit` declare `opus`; `fable` is reached
inside a story by dispatch, on the PLANNED, DIFF-REVIEW, REVIEW and ADJUDICATE
rows.
EOF
)"
R_RU_TODAY="$(cat <<'EOF'
Every definition declares `model:`. The planning roles (`lead-po`,
`lead-designer`) and the orchestrating commands
declare `fable`. Its rows: PLANNED and REVIEW on `fable`, every phase
that writes or tests code on `opus`.
EOF
)"
# write_r_rules <dir> <section-body>   The section sits between two others,
# each of which carries the section's needles and its forbidden words.
write_r_rules() {
  [ -d "$1/.claude/harness" ] || mkdir -p "$1/.claude/harness"
  {
    printf '# Path ownership\n\nNot here: advance-story, complete-story, security-audit, DIFF-REVIEW, 2026-11-11, ADJUDICATE,\nand the orchestrating commands, PLANNED and REVIEW on.\n\n'
    printf '%s\n\n%s\n\n' "$RU_HEAD" "$2"
    printf '# Phase permissions\n\nAnd again: advance-story, complete-story, security-audit, DIFF-REVIEW, ADJUDICATE,\n2026-11-11, and the orchestrating commands, PLANNED and REVIEW on.\n'
  } > "$1/$RULES"
}

R_MC_GOOD="$(cat <<'EOF'
# Which model each phase runs on.
# The second field is a phase of phases.conf or a named step inside one:
# DIFF-REVIEW is the step that opens GATES -> REVIEW.
EOF
)"
R_MC_TODAY="$(cat <<'EOF'
# Which model each phase runs on.
#   fable  the judgement phases. The orchestrating commands and the planning agents
#          declare `fable` for the same reason.
EOF
)"
# write_r_models <dir> <header>   The header, then rows - one of them the
# DIFF-REVIEW row, which must not stand in for the header.
write_r_models() {
  [ -d "$1/.claude/harness" ] || mkdir -p "$1/.claude/harness"
  {
    printf '%s\n\n' "$2"
    printf 'model  | GATES       | feature-developer | opus  | gates\n'
    printf 'model  | DIFF-REVIEW | lead-po           | fable | The orchestrating commands and the planning agents\n'
  } > "$1/$MODELS"
}

R_LP_GOOD='The diff review reaches you as a dispatch on the DIFF-REVIEW row; you report back.'
# write_r_leadpo <dir> <paragraph>
write_r_leadpo() {
  printf -- '---\nname: lead-po\nmodel: fable\n---\n\n## Orchestrating\n\n%s\n' "$2" > "$1/$LEADPO"
}

r_compliant() { # <dir>
  write_r_advance "$1" "$R_PL_GOOD" "$R_STEP1_GOOD" "$R_RD_GOOD"
  write_r_complete "$1" "$R_CB_GR_GOOD" "$R_CB_PL_GOOD"
  write_r_skill "$1" "$R_SK_DESC_GOOD" "$R_SK_WHO_GOOD"
  write_r_rules "$1" "$R_RU_GOOD"
  write_r_models "$1" "$R_MC_GOOD"
  write_r_leadpo "$1" "$R_LP_GOOD"
}
r_case() { # <name>   d := a new compliant HARNESS-101 fixture.
  d="$WORK/rows-$1"
  [ -e "$d" ] && rm -rf "${d:?}"
  mkdir -p "$d/.claude/commands" "$d/.claude/agents" "$d/.claude/harness" "$d/.claude/skills/diff-review"
  r_compliant "$d"
}

# ---------------------------------------------------------------------------
describe "HARNESS-101 the real tree: who is dispatched on which row (AC-3, AC-4, AC-6, AC-7)"

assert_eq "HARNESS-101: row_problems over the real tree prints nothing: advance-story's PLANNED → RED dispatches a lead-po on the PLANNED row; GATES → REVIEW step 1 dispatches a lead-po on the DIFF-REVIEW row, read from \`bash scripts/plan.sh models\`, with a Route checked by \`bash scripts/classify.sh\`, and not on the GATES row; REVIEW → DONE has PR feedback read by a lead-po on the REVIEW row with a Route; complete-story's bullets say the same; diff-review's description and ## Who runs it name the lead-po on the DIFF-REVIEW row and no feature-developer; rules.md's model section states the 2026-11-11 split; models.conf's header names DIFF-REVIEW; lead-po.md names the DIFF-REVIEW row; and (HARNESS-102) advance-story's PLANNED → RED says \`read what it returned\`, complete-story's dispatch bullet says \`before you commit at PLANNED\`, the PR-feedback paragraph \`records a departure for that row\`, and rules.md's model section names ADJUDICATE" \
  "" "$(row_problems "$REPO_ROOT")"

# HARNESS-102 AC-9, AC-10: one assertion per carried item over the real tree,
# each a whole-line count of its own line, so a failure names the item. The
# AC-9 two are green on arrival (the sentences exist) and are earned in RED by
# the two mutate.sh runs in the story's Contract C-10; AC-10's is red until
# GREEN adds the clause to the PR-feedback paragraph.
RT_ROWS="$(row_problems "$REPO_ROOT")"
assert_eq "HARNESS-102 AC-9: advance-story's PLANNED → RED region, over the real tree, says \`read what it returned\` (HARNESS-101 AC-3's read-before-commit sentence)" \
  0 "$(grep -cxF -- "$(r_say "$ADVANCE" 'PLANNED → RED' 'read what it returned')" <<< "$RT_ROWS")"
assert_eq "HARNESS-102 AC-9: complete-story's PLANNED → RED dispatch bullet, over the real tree, names \`lead-po\` and \`PLANNED row\` and says \`before you commit at PLANNED\`" \
  "0 0" "$(grep -cxF -- "$L_CB_PL" <<< "$RT_ROWS") $(grep -cxF -- "$(r_say "$COMPLETE" 'its PLANNED → RED dispatch bullet' "$CB_PL_READ")" <<< "$RT_ROWS")"
assert_eq "HARNESS-102 AC-10: advance-story's REVIEW → DONE region, over the real tree, says the PR-feedback dispatch's model comes from plan.sh unless \`## Model guidance\` \`records a departure for that row\`" \
  0 "$(grep -cxF -- "$(r_say "$ADVANCE" 'REVIEW → DONE' 'records a departure for that row')" <<< "$RT_ROWS")"
assert_eq "HARNESS-102 AC-1: rules.md's # The model each agent runs on, over the real tree, names ADJUDICATE among the fable rows" \
  0 "$(grep -cxF -- "$(r_say "$RULES" "$RU_HEAD" 'ADJUDICATE')" <<< "$RT_ROWS")"

# ---------------------------------------------------------------------------
describe "HARNESS-101 the fixture: compliant by construction"

r_case compliant
assert_eq "HARNESS-101: the compliant fixture is silent" "" "$(row_problems "$d")"

r_case crlf
for f in "$ADVANCE" "$COMPLETE" "$SKILL" "$RULES" "$MODELS" "$LEADPO"; do
  c="$(cat "$d/$f")"; printf '%s\r\n' "${c//$'\n'/$'\r\n'}" > "$d/$f"
done
assert_eq "HARNESS-101: a CRLF checkout reads the same as an LF one: silent" "" "$(row_problems "$d")"

r_case wrapped
write_r_advance "$d" "${R_PL_GOOD//PLANNED row/PLANNED
row}" "${R_STEP1_GOOD//DIFF-REVIEW row/DIFF-REVIEW
   row}" "${R_RD_GOOD//the REVIEW row/the REVIEW
row}"
assert_eq "HARNESS-101: needles reflowed across a line break still count: silent" "" "$(row_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-101 AC-3: advance-story's PLANNED → RED is a lead-po dispatch on the PLANNED row"

r_case pl-today
write_r_advance "$d" "$R_PL_TODAY" "$R_STEP1_GOOD" "$R_RD_GOOD"
assert_eq "HARNESS-101 AC-3 control: the region as it reads today (the orchestrator does the work, no dispatch) gives the two lines, and HARNESS-102 AC-9's third (no \`read what it returned\`)" \
  "$(r_say "$ADVANCE" 'PLANNED → RED' 'lead-po')
$(r_say "$ADVANCE" 'PLANNED → RED' 'PLANNED row')
$(r_say "$ADVANCE" 'PLANNED → RED' 'read what it returned')" "$(row_problems "$d")"

for w in "${PL_NEEDLES[@]}" "${PL_ADV_NEEDLES[@]}"; do
  r_case "pl-without-${w// /_}"
  write_r_advance "$d" "${R_PL_GOOD//"$w"/elsewhere}" "$R_STEP1_GOOD" "$R_RD_GOOD"
  assert_eq "HARNESS-101 AC-3, HARNESS-102 AC-9: the PLANNED → RED region without \`$w\` gives exactly the one line naming it" \
    "$(r_say "$ADVANCE" 'PLANNED → RED' "$w")" "$(row_problems "$d")"
done

# HARNESS-102 AC-9: the sentence split across a line break, as the real one
# is ("read what it" / "returned."), still counts.
r_case pl-read-wrapped
write_r_advance "$d" "${R_PL_GOOD//read what it returned/read what it
returned}" "$R_STEP1_GOOD" "$R_RD_GOOD"
assert_eq "HARNESS-102 AC-9: \`read what it returned\` reflowed across a line break, as the real sentence is, still counts: silent" \
  "" "$(row_problems "$d")"

r_case pl-after-marker
write_r_advance "$d" "$R_PL_TODAY" "$R_STEP1_GOOD" "$R_RD_GOOD"
c="$(cat "$d/$ADVANCE")"
printf '%s\n' "${c/"$R_RG"/"$R_RG"$'\n\n'A \`lead-po\` on the PLANNED row does it.}" > "$d/$ADVANCE"
assert_eq "HARNESS-101 AC-3, HARNESS-102 AC-9: the dispatch, and \`read what it returned\`, named only after the next marker (\`**RED → GREEN.**\`) are not in the region: the three lines" \
  "$(r_say "$ADVANCE" 'PLANNED → RED' 'lead-po')
$(r_say "$ADVANCE" 'PLANNED → RED' 'PLANNED row')
$(r_say "$ADVANCE" 'PLANNED → RED' 'read what it returned')" "$(row_problems "$d")"

r_case pl-none
write_r_advance "$d" "${R_PL_GOOD//'**PLANNED → RED.**'/'**PLANNED -> RED.**'}" "$R_STEP1_GOOD" "$R_RD_GOOD"
assert_eq "HARNESS-101 AC-3: no \`**PLANNED → RED.**\` line (an ascii arrow) gives the one line" \
  "$L_PL_NONE" "$(row_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-101 AC-4: GATES → REVIEW step 1 is a lead-po dispatch on the DIFF-REVIEW row"

r_case step1-today
write_r_advance "$d" "$R_PL_GOOD" "$R_STEP1_TODAY" "$R_RD_GOOD"
assert_eq "HARNESS-101 AC-4 control: step 1 as it reads today (a fresh feature-developer on the GATES row) gives five \"does not say\" lines and the GATES row line" \
  "$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'lead-po')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'DIFF-REVIEW row')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'bash scripts/plan.sh models')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'Route')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'bash scripts/classify.sh')
$(r_still "$ADVANCE" 'GATES → REVIEW step 1' 'GATES row')" "$(row_problems "$d")"

for w in "${STEP1_NEEDLES[@]}"; do
  r_case "step1-without-${w//[^a-zA-Z]/_}"
  write_r_advance "$d" "$R_PL_GOOD" "${R_STEP1_GOOD//"$w"/elsewhere}" "$R_RD_GOOD"
  assert_eq "HARNESS-101 AC-4: step 1 without \`$w\` gives exactly the one line naming it" \
    "$(r_say "$ADVANCE" 'GATES → REVIEW step 1' "$w")" "$(row_problems "$d")"
done

r_case step1-gates-row
write_r_advance "$d" "$R_PL_GOOD" "${R_STEP1_GOOD//dispatch\./dispatch on the GATES row.}" "$R_RD_GOOD"
assert_eq "HARNESS-101 AC-4: a compliant step 1 that also says \`GATES row\` gives exactly that line" \
  "$(r_still "$ADVANCE" 'GATES → REVIEW step 1' 'GATES row')" "$(row_problems "$d")"

r_case step1-in-step2
write_r_advance "$d" "$R_PL_GOOD" '1. Review the story'"'"'s diff with the `diff-review` skill.
2. Dispatch a `lead-po` on the DIFF-REVIEW row, read from `bash scripts/plan.sh models $1`; a Route, checked with `bash scripts/classify.sh`.' "$R_RD_GOOD"
assert_eq "HARNESS-101 AC-4: the words in step 2 do not satisfy step 1: five lines" \
  "$(for w in "${STEP1_NEEDLES[@]}"; do r_say "$ADVANCE" 'GATES → REVIEW step 1' "$w"; printf '\n'; done)" "$(row_problems "$d")"

r_case step1-none
write_r_advance "$d" "$R_PL_GOOD" "${R_STEP1_GOOD/#1. /- }" "$R_RD_GOOD"
assert_eq "HARNESS-101 AC-4: no step numbered 1 gives the one line" \
  "$L_STEP1_NONE" "$(row_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-101 AC-6: PR feedback at REVIEW is read by a lead-po on the REVIEW row"

r_case rd-today
write_r_advance "$d" "$R_PL_GOOD" "$R_STEP1_GOOD" "$R_RD_TODAY"
assert_eq "HARNESS-101 AC-6 control: REVIEW → DONE as it reads today (no feedback dispatch) gives the three lines, and HARNESS-102 AC-10's fourth" \
  "$(r_say "$ADVANCE" 'REVIEW → DONE' 'lead-po')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'REVIEW row')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'Route')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'records a departure for that row')" "$(row_problems "$d")"

for w in "${RD_NEEDLES[@]}" "${RD_KEEP[@]}"; do
  r_case "rd-without-${w//[^a-zA-Z]/_}"
  write_r_advance "$d" "$R_PL_GOOD" "$R_STEP1_GOOD" "${R_RD_GOOD//"$w"/elsewhere}"
  assert_eq "HARNESS-101 AC-6: REVIEW → DONE without \`$w\` gives exactly the one line naming it" \
    "$(r_say "$ADVANCE" 'REVIEW → DONE' "$w")" "$(row_problems "$d")"
done

r_case rd-only-diff-review
write_r_advance "$d" "$R_PL_GOOD" "$R_STEP1_GOOD" "${R_RD_GOOD//the REVIEW row/the DIFF-REVIEW row}"
assert_eq "HARNESS-101 AC-6: \`DIFF-REVIEW row\` is not \`REVIEW row\`: the region naming only the diff review's row gives the REVIEW row line" \
  "$(r_say "$ADVANCE" 'REVIEW → DONE' 'REVIEW row')" "$(row_problems "$d")"

r_case rd-bold-paragraph
write_r_advance "$d" "$R_PL_GOOD" "$R_STEP1_GOOD" "${R_RD_GOOD//Feedback on the open PR/**At REVIEW.** Feedback on the open PR}"
assert_eq "HARNESS-101 AC-6: a statement in a paragraph that BEGINS \`**\` is past the region's end: the four lines (HARNESS-102 AC-10's among them), and the timings paragraph after it is lost too" \
  "$(r_say "$ADVANCE" 'REVIEW → DONE' 'lead-po')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'REVIEW row')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'Route')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'records a departure for that row')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'read the timings')" "$(row_problems "$d")"

r_case rd-none
write_r_advance "$d" "$R_PL_GOOD" "$R_STEP1_GOOD" "${R_RD_GOOD//'**REVIEW → DONE.**'/'**REVIEW -> DONE.**'}"
assert_eq "HARNESS-101 AC-6: no \`**REVIEW → DONE.**\` line gives the one line" \
  "$L_RD_NONE" "$(row_problems "$d")"

# HARNESS-102 AC-10: GATES → REVIEW step 1 carries the same words (it does in
# the real tree, at line 272). Step 1 is outside REVIEW → DONE, so a step 1
# saying them does not stand in for the PR-feedback paragraph: the one line.
r_case rd-departure-only-in-step1
dep_step1='Unless the story`s Model guidance records a departure for that row. A code fix'
write_r_advance "$d" "$R_PL_GOOD" "${R_STEP1_GOOD//A code fix/$dep_step1}" \
  "${R_RD_GOOD//records a departure for that row/elsewhere}"
assert_eq "HARNESS-102 AC-10: \`records a departure for that row\` in GATES → REVIEW step 1 only does not satisfy REVIEW → DONE: exactly the one line" \
  "$(r_say "$ADVANCE" 'REVIEW → DONE' 'records a departure for that row')" "$(row_problems "$d")"

r_case rd-departure-wrapped
write_r_advance "$d" "$R_PL_GOOD" "$R_STEP1_GOOD" "${R_RD_GOOD//records a departure for that row/records a departure
for that row}"
assert_eq "HARNESS-102 AC-10: \`records a departure for that row\` reflowed across a line break still counts: silent" \
  "" "$(row_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-101 AC-3, AC-4: complete-story's PLANNED → RED and GATES → REVIEW bullets"

r_case cb-pl-today
write_r_complete "$d" "$R_CB_GR_GOOD" "$R_CB_PL_TODAY"
assert_eq "HARNESS-101 AC-3 control: the PLANNED → RED bullets as they read today give the one line" \
  "$L_CB_PL" "$(row_problems "$d")"

r_case cb-pl-split
write_r_complete "$d" "$R_CB_GR_GOOD" '- **PLANNED → RED pins the contract**, on the PLANNED row.
- **PLANNED → RED is a dispatch** to a `lead-po`.'
assert_eq "HARNESS-101 AC-3: \`lead-po\` in one PLANNED → RED bullet and \`PLANNED row\` in the other is not a bullet saying both: one line" \
  "$L_CB_PL" "$(row_problems "$d")"

r_case cb-pl-next-bullet
write_r_complete "$d" "$R_CB_GR_GOOD" '- **PLANNED → RED is a dispatch.**
- A `lead-po` on the PLANNED row does it.'
assert_eq "HARNESS-101 AC-3: the words in the NEXT, non-PLANNED bullet do not count: one line" \
  "$L_CB_PL" "$(row_problems "$d")"

# HARNESS-102 AC-9: the dispatch bullet without the read-before-commit phrase.
# A SECOND line, distinct from L_CB_PL, which is kept for "no dispatch bullet".
L_CB_PL_READ="$(r_say "$COMPLETE" 'its PLANNED → RED dispatch bullet' "$CB_PL_READ")"
r_case cb-pl-no-read
write_r_complete "$d" "$R_CB_GR_GOOD" "${R_CB_PL_GOOD//before you
  commit at PLANNED/and move on}"
assert_eq "HARNESS-102 AC-9: complete-story's dispatch bullet (\`lead-po\`, \`PLANNED row\`) without \`before you commit at PLANNED\` gives exactly the one line" \
  "$L_CB_PL_READ" "$(row_problems "$d")"

r_case cb-pl-read-other-bullet
write_r_complete "$d" "$R_CB_GR_GOOD" '- **PLANNED → RED pins the `## Contract`** before you commit at PLANNED.
- **PLANNED → RED is a dispatch**: a `lead-po` on the PLANNED row does the
  PLANNED work and returns its questions to you, and you move on.'
assert_eq "HARNESS-102 AC-9: \`before you commit at PLANNED\` in a PLANNED → RED bullet that is not the dispatch bullet does not count: the one line" \
  "$L_CB_PL_READ" "$(row_problems "$d")"

r_case cb-gr-today
write_r_complete "$d" "$R_CB_GR_TODAY" "$R_CB_PL_GOOD"
assert_eq "HARNESS-101 AC-4 control: the GATES → REVIEW bullet as it reads today (a fresh feature-developer) gives three lines" \
  "$(r_say "$COMPLETE" 'its GATES → REVIEW bullet' 'lead-po')
$(r_say "$COMPLETE" 'its GATES → REVIEW bullet' 'DIFF-REVIEW row')
$(r_still "$COMPLETE" 'its GATES → REVIEW bullet' 'fresh feature-developer')" "$(row_problems "$d")"

for w in "${CB_GR_NEEDLES[@]}"; do
  r_case "cb-gr-without-${w//[^a-zA-Z]/_}"
  write_r_complete "$d" "${R_CB_GR_GOOD//"$w"/elsewhere}" "$R_CB_PL_GOOD"
  assert_eq "HARNESS-101 AC-4: the GATES → REVIEW bullet without \`$w\` gives exactly the one line" \
    "$(r_say "$COMPLETE" 'its GATES → REVIEW bullet' "$w")" "$(row_problems "$d")"
done

r_case cb-gr-fresh-wrapped
write_r_complete "$d" "${R_CB_GR_GOOD//full gates/full gates, never a fresh
  feature-developer review,}" "$R_CB_PL_GOOD"
assert_eq "HARNESS-101 AC-4: \`fresh feature-developer\` reflowed across a line break is still there: one line" \
  "$(r_still "$COMPLETE" 'its GATES → REVIEW bullet' 'fresh feature-developer')" "$(row_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-101 AC-4: diff-review's description and ## Who runs it"

r_case sk-today
write_r_skill "$d" "$R_SK_DESC_TODAY" "$R_SK_WHO_TODAY"
assert_eq "HARNESS-101 AC-4 control: the skill as it reads today gives the description's two lines and ## Who runs it's four" \
  "$(r_say "$SKILL" 'its description' 'lead-po')
$(r_still "$SKILL" 'its description' 'feature-developer')
$(r_say "$SKILL" '## Who runs it' 'lead-po')
$(r_say "$SKILL" '## Who runs it' 'DIFF-REVIEW row')
$(r_still "$SKILL" '## Who runs it' 'feature-developer')
$(r_still "$SKILL" '## Who runs it' 'GATES row')" "$(row_problems "$d")"

r_case sk-desc-body
write_r_skill "$d" 'description: Review a whole diff before the PR opens.' "$R_SK_WHO_GOOD"
assert_eq "HARNESS-101 AC-4: \`lead-po\` in the body but not in the description gives the one line" \
  "$(r_say "$SKILL" 'its description' 'lead-po')" "$(row_problems "$d")"

r_case sk-desc-fd
write_r_skill "$d" "${R_SK_DESC_GOOD//lead-po/lead-po or feature-developer}" "$R_SK_WHO_GOOD"
assert_eq "HARNESS-101 AC-4: a description naming \`feature-developer\` beside \`lead-po\` gives the one line" \
  "$(r_still "$SKILL" 'its description' 'feature-developer')" "$(row_problems "$d")"

r_case sk-desc-none
write_r_skill "$d" 'summary: Review a whole diff, as a fresh lead-po dispatch.' "$R_SK_WHO_GOOD"
assert_eq "HARNESS-101 AC-4: no \`description:\` line in the frontmatter gives the one line" \
  "$L_SK_DESC_NONE" "$(row_problems "$d")"

for w in "${SK_WHO_NEEDLES[@]}"; do
  r_case "sk-who-without-${w//[^a-zA-Z]/_}"
  write_r_skill "$d" "$R_SK_DESC_GOOD" "${R_SK_WHO_GOOD//"$w"/elsewhere}"
  assert_eq "HARNESS-101 AC-4: ## Who runs it without \`$w\` gives exactly the one line (the next section carries it)" \
    "$(r_say "$SKILL" '## Who runs it' "$w")" "$(row_problems "$d")"
done

for w in "${SK_WHO_NOT[@]}"; do
  r_case "sk-who-with-${w//[^a-zA-Z]/_}"
  write_r_skill "$d" "$R_SK_DESC_GOOD" "$R_SK_WHO_GOOD Not a $w."
  assert_eq "HARNESS-101 AC-4: ## Who runs it that also says \`$w\` gives exactly the one line" \
    "$(r_still "$SKILL" '## Who runs it' "$w")" "$(row_problems "$d")"
done

r_case sk-who-none
c="$(cat "$d/$SKILL")"; printf '%s\n' "${c//"$SK_WHO_HEAD"/## Who runs it, and why}" > "$d/$SKILL"
assert_eq "HARNESS-101 AC-4: a heading that only BEGINS \`## Who runs it\` is not it: one line" \
  "$L_SK_WHO_NONE" "$(row_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-101 AC-7: rules.md, models.conf's header and lead-po.md state the split"

r_case ru-today
write_r_rules "$d" "$R_RU_TODAY"
assert_eq "HARNESS-101 AC-7 control: the section as it reads today gives the five \"does not say\" lines and both old-split lines" \
  "$(for w in "${RU_NEEDLES[@]}"; do r_say "$RULES" "$RU_HEAD" "$w"; printf '\n'; done)
$(r_still "$RULES" "$RU_HEAD" 'and the orchestrating commands')
$(r_still "$RULES" "$RU_HEAD" 'PLANNED and REVIEW on')" "$(row_problems "$d")"

for w in "${RU_NEEDLES[@]}"; do
  r_case "ru-without-${w//[^a-zA-Z0-9]/_}"
  write_r_rules "$d" "${R_RU_GOOD//"$w"/elsewhere}"
  assert_eq "HARNESS-101 AC-7: the section without \`$w\` gives exactly the one line (the sections around it carry it)" \
    "$(r_say "$RULES" "$RU_HEAD" "$w")" "$(row_problems "$d")"
done

for w in "${RU_NOT[@]}"; do
  r_case "ru-with-${w//[^a-zA-Z]/_}"
  write_r_rules "$d" "$R_RU_GOOD Not: $w."
  assert_eq "HARNESS-101 AC-7: the section still saying \`$w\` gives exactly the one line" \
    "$(r_still "$RULES" "$RU_HEAD" "$w")" "$(row_problems "$d")"
done

r_case ru-none
c="$(cat "$d/$RULES")"; printf '%s\n' "${c//"$RU_HEAD"/## The model each agent runs on}" > "$d/$RULES"
assert_eq "HARNESS-101 AC-7: no line exactly \`# The model each agent runs on\` gives the one line" \
  "$L_RU_NONE" "$(row_problems "$d")"

r_case mc-today
write_r_models "$d" "$R_MC_TODAY"
assert_eq "HARNESS-101 AC-7 control: models.conf's header as it reads today gives two lines; the DIFF-REVIEW row does not stand in for the header" \
  "$(r_say "$MODELS" 'its header comment' 'DIFF-REVIEW')
$(r_still "$MODELS" 'its header comment' 'The orchestrating commands and the planning agents')" "$(row_problems "$d")"

r_case lp-without
write_r_leadpo "$d" 'The diff review reaches you as a dispatch on the GATES row.'
assert_eq "HARNESS-101 AC-7: lead-po.md without \`DIFF-REVIEW row\` gives the one line" \
  "$(r_say "$LEADPO" 'the file' 'DIFF-REVIEW row')" "$(row_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-101: missing files, and every line a tree at 9a10054 prints, in order"

for f in "$ADVANCE" "$COMPLETE" "$SKILL" "$RULES" "$MODELS" "$LEADPO"; do
  r_case "missing-${f##*/}"
  rm -f "${d:?}/${f:?}"
  assert_eq "HARNESS-101: a missing $f gives only \`file is missing\`" \
    "$f: file is missing" "$(row_problems "$d")"
done

r_case today
write_r_advance "$d" "$R_PL_TODAY" "$R_STEP1_TODAY" "$R_RD_TODAY"
write_r_complete "$d" "$R_CB_GR_TODAY" "$R_CB_PL_TODAY"
write_r_skill "$d" "$R_SK_DESC_TODAY" "$R_SK_WHO_TODAY"
write_r_rules "$d" "$R_RU_TODAY"
write_r_models "$d" "$R_MC_TODAY"
write_r_leadpo "$d" 'Long runs go to a feature-developer on the GATES row.'
assert_eq "HARNESS-101: a tree with today's wording in all six files prints all 34 lines (31 at HARNESS-101, three more for HARNESS-102 AC-9, AC-10 and the ADJUDICATE needle), file by file in C-3's order" \
  "$(r_say "$ADVANCE" 'PLANNED → RED' 'lead-po')
$(r_say "$ADVANCE" 'PLANNED → RED' 'PLANNED row')
$(r_say "$ADVANCE" 'PLANNED → RED' 'read what it returned')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'lead-po')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'DIFF-REVIEW row')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'bash scripts/plan.sh models')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'Route')
$(r_say "$ADVANCE" 'GATES → REVIEW step 1' 'bash scripts/classify.sh')
$(r_still "$ADVANCE" 'GATES → REVIEW step 1' 'GATES row')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'lead-po')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'REVIEW row')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'Route')
$(r_say "$ADVANCE" 'REVIEW → DONE' 'records a departure for that row')
$L_CB_PL
$(r_say "$COMPLETE" 'its GATES → REVIEW bullet' 'lead-po')
$(r_say "$COMPLETE" 'its GATES → REVIEW bullet' 'DIFF-REVIEW row')
$(r_still "$COMPLETE" 'its GATES → REVIEW bullet' 'fresh feature-developer')
$(r_say "$SKILL" 'its description' 'lead-po')
$(r_still "$SKILL" 'its description' 'feature-developer')
$(r_say "$SKILL" '## Who runs it' 'lead-po')
$(r_say "$SKILL" '## Who runs it' 'DIFF-REVIEW row')
$(r_still "$SKILL" '## Who runs it' 'feature-developer')
$(r_still "$SKILL" '## Who runs it' 'GATES row')
$(for w in "${RU_NEEDLES[@]}"; do r_say "$RULES" "$RU_HEAD" "$w"; printf '\n'; done)
$(r_still "$RULES" "$RU_HEAD" 'and the orchestrating commands')
$(r_still "$RULES" "$RU_HEAD" 'PLANNED and REVIEW on')
$(r_say "$MODELS" 'its header comment' 'DIFF-REVIEW')
$(r_still "$MODELS" 'its header comment' 'The orchestrating commands and the planning agents')
$(r_say "$LEADPO" 'the file' 'DIFF-REVIEW row')" "$(row_problems "$d")"


# ===========================================================================
# HARNESS-102 AC-1: a claim that the contract is wrong is adjudicated by a
# fresh lead-po dispatch on the ADJUDICATE row, not by the orchestrator.
#
# `adj_problems <root>` is a THIRD guard beside dispatch_problems and
# row_problems, for the reason row_problems gives for being a second: it reads
# regions neither of them reads (the three contract-is-wrong bullets, lead-po's
# dispatch section and description, diff-review's section 5), and folding them
# in would put lines into every pinned output above. Same pattern: silent over
# a fixture compliant by construction, exactly the pinned lines over a fixture
# with one thing regressed, and - in RED - red over the real tree.
#
# The needles are the story's Contract C-7, read out, plus the RED amendment
# recorded there: each of the three statements carries one needle per clause
# of AC-1 (who: `lead-po`, `ADJUDICATE row`; the answer: `upheld`,
# `rejected`; where it goes: `**Adjudicated`, `## Notes`; a Route'd entry:
# `AMEND`), and none keeps its own file's words for the orchestrator doing it.
#
# The three statements are found by their common opening words, `- **A claim
# that the contract`, not by line number and not by the rest of their bold
# lead, which GREEN rewrites in place. A bullet runs to just before the next
# line beginning `- `, a blank line, or a `#` heading.

CLAIM_START='- **A claim that the contract'
CLAIM_NEEDLES=('lead-po' 'ADJUDICATE row' 'upheld' 'rejected' '**Adjudicated' '## Notes' 'AMEND')
ADV_CLAIM_NOT=('you reproduce independently')
CB_CLAIM_NOT=('verify it yourself')
LP_CLAIM_NOT=('reproduce it on different inputs')
LP_DISP_HEAD='## When you are dispatched inside a story'
LP_DISP_NEEDLES=('ADJUDICATE row')
LP_DISP_NOT=('Three pieces of work')
LP_DESC_NEEDLES=('PLANNED' 'DIFF-REVIEW' 'ADJUDICATE')
SK5_HEAD='## 5. What happens to a finding'
SK5_NEEDLES=('**Adjudicated')

L_ADV_CLAIM_NONE="$ADVANCE: has no bullet beginning \`$CLAIM_START\`"
L_CB_CLAIM_NONE="$COMPLETE: has no bullet beginning \`$CLAIM_START\`"
L_LP_CLAIM_NONE="$LEADPO: has no bullet beginning \`$CLAIM_START\`"
L_LP_DESC_NONE="$LEADPO: has no description in its frontmatter"
L_LP_DISP_NONE="$LEADPO: has no $LP_DISP_HEAD section"
L_SK5_NONE="$SKILL: has no $SK5_HEAD section"
A_CLAIM='its contract-is-wrong bullet'

# claim_bullet   G := the first bullet beginning CLAIM_START, to just before
# the next line beginning `- `, a blank line or a `#` heading; HAS_G := 1.
claim_bullet() {
  local l on=0
  G=""; HAS_G=0
  for l in "${LN[@]}"; do
    if [ "$on" = 0 ]; then
      [ "${l:0:${#CLAIM_START}}" = "$CLAIM_START" ] && { on=1; HAS_G=1; G="$l"; }
      continue
    fi
    if [ "${l:0:2}" = "- " ] || [ "${l:0:1}" = "#" ] || blank "$l"; then break; fi
    G="$G"$'\n'"$l"
  done
  return 0
}

# adj_claim <path> <none-line> <not-needle>...   The bullet's lines, for the
# file already loaded.
adj_claim() {
  local p="$1" none="$2"; shift 2
  claim_bullet
  if [ "$HAS_G" = 0 ]; then printf '%s\n' "$none"; return 0; fi
  must_say "$p" "$A_CLAIM" "$G" "${CLAIM_NEEDLES[@]}"
  must_not "$p" "$A_CLAIM" "$G" "$@"
  return 0
}

# adj_problems <root>   Silent when compliant. Always returns 0. Order: the
# two commands, then lead-po.md in file order (description, dispatch section,
# the bullet), then diff-review's section 5.
adj_problems() {
  local root="$1"
  if [ ! -f "$root/$ADVANCE" ]; then printf '%s: file is missing\n' "$ADVANCE"
  else load "$root/$ADVANCE"; adj_claim "$ADVANCE" "$L_ADV_CLAIM_NONE" "${ADV_CLAIM_NOT[@]}"
  fi
  if [ ! -f "$root/$COMPLETE" ]; then printf '%s: file is missing\n' "$COMPLETE"
  else load "$root/$COMPLETE"; adj_claim "$COMPLETE" "$L_CB_CLAIM_NONE" "${CB_CLAIM_NOT[@]}"
  fi
  if [ ! -f "$root/$LEADPO" ]; then printf '%s: file is missing\n' "$LEADPO"
  else
    load "$root/$LEADPO"
    fm_value 'description:'
    if [ "$HAS_V" = 0 ]; then printf '%s\n' "$L_LP_DESC_NONE"
    else must_say "$LEADPO" 'its description' "$V" "${LP_DESC_NEEDLES[@]}"
    fi
    section "$LP_DISP_HEAD"
    if [ "$HAS_SEC" = 0 ]; then printf '%s\n' "$L_LP_DISP_NONE"
    else
      must_say "$LEADPO" "$LP_DISP_HEAD" "$SEC" "${LP_DISP_NEEDLES[@]}"
      must_not "$LEADPO" "$LP_DISP_HEAD" "$SEC" "${LP_DISP_NOT[@]}"
    fi
    adj_claim "$LEADPO" "$L_LP_CLAIM_NONE" "${LP_CLAIM_NOT[@]}"
  fi
  if [ ! -f "$root/$SKILL" ]; then printf '%s: file is missing\n' "$SKILL"
  else
    load "$root/$SKILL"
    section "$SK5_HEAD"
    if [ "$HAS_SEC" = 0 ]; then printf '%s\n' "$L_SK5_NONE"
    else must_say "$SKILL" "$SK5_HEAD" "$SEC" "${SK5_NEEDLES[@]}"
    fi
  fi
  return 0
}

# --- HARNESS-102: today's words, verbatim from the tree at b10546e ----------
# The three bullets, lead-po.md's dispatch section and its description line,
# copied byte for byte. Section 5 of diff-review is abridged to two of its
# sentences; what matters there is that it says nothing of a record.
A_ADV_TODAY="$(cat <<'TODAY'
- **A claim that the contract itself is wrong — an acceptance criterion, a
  threshold, a frozen test — you reproduce independently before accepting it:
  different inputs, and without reusing the subagent's own code.** Running its
  probe again is not verification. Record the reproduction in the story next to
  the `## Amendments` or `## Regressions` entry it justifies. This is the exact
  shape of claim an agent makes when it wants to stop failing — *the
  specification is wrong, not my work* — and it is also the shape of the two
  most valuable escalations this harness has seen. Independent reproduction is
  the only thing that separates them, and it is cheap: a fresh probe on
  different inputs, or reading the fixture and enumerating the cases the file
  asserts to show no rule satisfies all of them.
TODAY
)"
A_CB_TODAY="$(cat <<'TODAY'
- **A claim that the contract is wrong is reproduced before it is accepted.**
  When a subagent reports that an acceptance criterion, a threshold or a frozen
  test is wrong, verify it yourself on different inputs, without reusing the
  subagent's code, and record the reproduction in the story. Running unattended
  is exactly when this gets skipped, and it is the difference between a correct
  escalation and a plausible excuse for not failing.
TODAY
)"
A_LP_TODAY="$(cat <<'TODAY'
- **A claim that the contract is wrong is reproduced independently.** When a
  subagent reports that an acceptance criterion, a threshold or a frozen test
  is *wrong*, reproduce it on different inputs, without reusing its code, and
  record the reproduction beside the `## Amendments` or `## Regressions` entry
  it justifies. This is the shape of claim an agent makes when it wants to stop
  failing, and also the shape of the most valuable escalations there are; only
  the reproduction tells them apart. `story-authoring` carries the case where
  it was right.
TODAY
)"
A_LP_DISP_TODAY="$(cat <<'TODAY'

Since 2026-11-11 `/advance-story` and `/complete-story` declare `opus`: the
session that runs the story loop is on `opus`, and it reaches `fable` by
dispatching you. Three pieces of work arrive that way, each on its own row of
`.claude/harness/models.conf`:

- **Planning, on the PLANNED row.** The PLANNED → RED checklist in
  `/advance-story`, pasted as your brief: write the story's sections, then run
  `bash scripts/plan.sh write <id>` last.
- **The diff review, on the DIFF-REVIEW row.** The `diff-review` skill, as a
  fresh reviewer that changes no file; every finding carries a `**Route:**`.
- **PR feedback, on the REVIEW row.** A reviewer's comment or a CI failure on
  the open PR, read against the contract, each item that needs a change
  labelled with a `Route` as the `diff-review` skill defines it.

In those dispatches you report back and do not orchestrate: you dispatch no
agent, set no phase, commit nothing, and cannot ask the user anything - a
question for the user goes in your report, and the orchestrator puts it to
them. `## Orchestrating` below is the orchestrator's work: the session running
`/advance-story` or `/complete-story` acts as the lead-po orchestrator and
follows it, on `opus`.

TODAY
)"
A_LP_DESC_TODAY="$(cat <<'TODAY'
description: Product owner and planner. Interviews the user to produce a product brief, decomposes it into epics and stories with testable acceptance criteria, plans stories, reviews a story's whole diff and reads PR feedback against its contract. Use for /create-product, /plan-product and /plan-story, and when /advance-story or /complete-story dispatches it inside a story on the PLANNED, DIFF-REVIEW or REVIEW row of models.conf. Those two commands run in the user's session and orchestrate the story themselves; do not hand their whole orchestration to a lead-po subagent.
TODAY
)"
A_SK5_TODAY='The orchestrator follows the label; it does not choose the route. A finding that says an acceptance criterion is wrong (`AMEND`) is an `## Amendments` question for the user.'

# --- HARNESS-102: a compliant fixture, by construction ----------------------
# Never copied from the real tree, which in RED is not compliant. Every needle
# appears in the region that must carry it; the bullet after each region
# carries every needle AND every forbidden phrase, so a region that ran on past
# its end would be seen in both directions.
A_CLAIM_GOOD="$(cat <<'GOOD'
- **A claim that the contract is wrong is adjudicated, not reproduced by you.**
  A fresh `lead-po` on the ADJUDICATE row reproduces it on its own inputs and
  answers upheld or rejected. An upheld claim's entry carries its
  `**Adjudicated R-<n>:**` line; a rejected one gets a line in `## Notes` and
  no entry. An entry that follows a `RED` or `AMEND` Route is adjudicated by
  that dispatch, and its record names it.
GOOD
)"
A_NEXT='- **And it runs the other way.** lead-po, ADJUDICATE row, upheld, rejected, **Adjudicated, ## Notes, AMEND; you reproduce independently, verify it yourself, reproduce it on different inputs, Three pieces of work.'
A_LP_DESC_GOOD='description: Product owner. Dispatched inside a story on the PLANNED, DIFF-REVIEW, REVIEW or ADJUDICATE row of models.conf.'
A_LP_DISP_GOOD="$(cat <<'GOOD'
Four pieces of work arrive that way, each on its own row:

- **Planning, on the PLANNED row.**
- **Adjudication, on the ADJUDICATE row.** A claim that the contract is wrong.
GOOD
)"
A_SK5_GOOD='An entry that follows a `RED` or `AMEND` finding carries a `**Adjudicated <id>:**` record naming the review round and finding number, written by the orchestrator.'

# write_a_cmd <path> <bullet>   A command file: a bullet before, the claim
# bullet, then A_NEXT.
write_a_cmd() {
  {
    printf -- '---\ndescription: a command\n---\n\n## Rules for you as orchestrator\n\n'
    printf -- '- Change phase only with `bash scripts/phase.sh set`.\n%s\n%s\n' "$2" "$A_NEXT"
  } > "$1"
}
# write_a_leadpo <dir> <description-line> <dispatch-body> <bullet>
# ## Orchestrating after the dispatch section carries the section's needle and
# its forbidden phrase, so a section that ran on would be seen.
write_a_leadpo() {
  {
    printf -- '---\nname: lead-po\n%s\nmodel: fable\n---\n\n## Decomposing\n\nNot here: PLANNED, DIFF-REVIEW, ADJUDICATE.\n\n' "$2"
    printf '%s\n\n%s\n\n' "$LP_DISP_HEAD" "$3"
    printf '## Orchestrating\n\nThree pieces of work, on the ADJUDICATE row.\n\n'
    printf -- '- **Verify every claim.**\n%s\n%s\n' "$4" "$A_NEXT"
  } > "$1/$LEADPO"
}
# write_a_skill <dir> <section-5-body>   Section 4 before and 6 after both
# carry the needle, so only section 5 can satisfy it.
write_a_skill() {
  [ -d "$1/.claude/skills/diff-review" ] || mkdir -p "$1/.claude/skills/diff-review"
  {
    printf -- '---\nname: diff-review\ndescription: Review a diff.\n---\n\n## 4. Output\n\n**Adjudicated here does not count.\n\n'
    printf '%s\n\n%s\n\n' "$SK5_HEAD" "$2"
    printf '## 6. After\n\n**Adjudicated here does not count either.\n'
  } > "$1/$SKILL"
}
a_compliant() { # <dir>
  write_a_cmd "$1/$ADVANCE" "$A_CLAIM_GOOD"
  write_a_cmd "$1/$COMPLETE" "$A_CLAIM_GOOD"
  write_a_leadpo "$1" "$A_LP_DESC_GOOD" "$A_LP_DISP_GOOD" "$A_CLAIM_GOOD"
  write_a_skill "$1" "$A_SK5_GOOD"
}
a_case() { # <name>   d := a new compliant HARNESS-102 fixture.
  d="$WORK/adj-$1"
  [ -e "$d" ] && rm -rf "${d:?}"
  mkdir -p "$d/.claude/commands" "$d/.claude/agents" "$d/.claude/skills/diff-review"
  a_compliant "$d"
}
# a_claim <path> <bullet>   Replace one file's claim bullet in the fixture d.
a_claim() {
  if [ "$1" = "$LEADPO" ]; then write_a_leadpo "$d" "$A_LP_DESC_GOOD" "$A_LP_DISP_GOOD" "$2"
  else write_a_cmd "$d/$1" "$2"
  fi
}

# a_claim_lines <path> <not-needle>...   Every line today's wording of one
# claim bullet gives: all seven needles missing, and its own forbidden phrase.
a_claim_lines() {
  local p="$1" w; shift
  for w in "${CLAIM_NEEDLES[@]}"; do r_say "$p" "$A_CLAIM" "$w"; printf '\n'; done
  for w in "$@"; do r_still "$p" "$A_CLAIM" "$w"; printf '\n'; done
}

# ---------------------------------------------------------------------------
describe "HARNESS-102 AC-1 the real tree: a contract-is-wrong claim goes to a fresh lead-po on the ADJUDICATE row"

assert_eq "HARNESS-102 AC-1: adj_problems over the real tree prints nothing: advance-story, complete-story and lead-po.md each say a fresh lead-po on the ADJUDICATE row adjudicates the claim, upheld or rejected, with the record (\`**Adjudicated\`) in the entry, a rejected claim in ## Notes, and a Route'd RED or AMEND entry adjudicated by that dispatch, and none tells the orchestrator to reproduce it itself; lead-po.md's dispatch section and description name the ADJUDICATE row; diff-review's section 5 says a Route'd entry carries a \`**Adjudicated\` record" \
  "" "$(adj_problems "$REPO_ROOT")"

# ---------------------------------------------------------------------------
describe "HARNESS-102 AC-1 the fixture: compliant by construction, and today's words"

a_case compliant
assert_eq "HARNESS-102 AC-1: the compliant fixture is silent" "" "$(adj_problems "$d")"

a_case crlf
for f in "$ADVANCE" "$COMPLETE" "$LEADPO" "$SKILL"; do
  c="$(cat "$d/$f")"; printf '%s\r\n' "${c//$'\n'/$'\r\n'}" > "$d/$f"
done
assert_eq "HARNESS-102 AC-1: a CRLF checkout reads the same as an LF one: silent" "" "$(adj_problems "$d")"

a_case wrapped
wrapped="${A_CLAIM_GOOD//the ADJUDICATE row/the ADJUDICATE
  row}"
write_a_cmd "$d/$ADVANCE" "$wrapped"
write_a_cmd "$d/$COMPLETE" "$wrapped"
write_a_leadpo "$d" "$A_LP_DESC_GOOD" "${A_LP_DISP_GOOD//the ADJUDICATE row/the ADJUDICATE
row}" "$wrapped"
assert_eq "HARNESS-102 AC-1: needles reflowed across a line break still count: silent" "" "$(adj_problems "$d")"

a_case today
write_a_cmd "$d/$ADVANCE" "$A_ADV_TODAY"
write_a_cmd "$d/$COMPLETE" "$A_CB_TODAY"
write_a_leadpo "$d" "$A_LP_DESC_TODAY" "$A_LP_DISP_TODAY" "$A_LP_TODAY"
write_a_skill "$d" "$A_SK5_TODAY"
assert_eq "HARNESS-102 AC-1 control: today's words in all four files (verbatim at b10546e; section 5 abridged) print all 28 lines, file by file" \
  "$(a_claim_lines "$ADVANCE" "${ADV_CLAIM_NOT[@]}")
$(a_claim_lines "$COMPLETE" "${CB_CLAIM_NOT[@]}")
$(r_say "$LEADPO" 'its description' 'ADJUDICATE')
$(r_say "$LEADPO" "$LP_DISP_HEAD" 'ADJUDICATE row')
$(r_still "$LEADPO" "$LP_DISP_HEAD" 'Three pieces of work')
$(a_claim_lines "$LEADPO" "${LP_CLAIM_NOT[@]}")
$(r_say "$SKILL" "$SK5_HEAD" '**Adjudicated')" "$(adj_problems "$d")"

# ---------------------------------------------------------------------------
describe "HARNESS-102 AC-1: each of the three statements, one clause at a time"

for f in "$ADVANCE" "$COMPLETE" "$LEADPO"; do
  for w in "${CLAIM_NEEDLES[@]}"; do
    a_case "claim-${f##*/}-without-${w//[^a-zA-Z]/_}"
    a_claim "$f" "${A_CLAIM_GOOD//"$w"/elsewhere}"
    assert_eq "HARNESS-102 AC-1: $f's contract-is-wrong bullet without \`$w\` gives exactly the one line (the next bullet carries it)" \
      "$(r_say "$f" "$A_CLAIM" "$w")" "$(adj_problems "$d")"
  done
done

for pair in "$ADVANCE|${ADV_CLAIM_NOT[0]}" "$COMPLETE|${CB_CLAIM_NOT[0]}" "$LEADPO|${LP_CLAIM_NOT[0]}"; do
  f="${pair%%|*}"; w="${pair#*|}"
  a_case "claim-${f##*/}-still"
  a_claim "$f" "$A_CLAIM_GOOD
  The orchestrator is not told: $w."
  assert_eq "HARNESS-102 AC-1: $f's bullet that still says \`$w\` gives exactly the one line" \
    "$(r_still "$f" "$A_CLAIM" "$w")" "$(adj_problems "$d")"
done

# The forbidden phrase is per file: complete-story's words in advance-story's
# bullet are not advance-story's rule, so they do not fire there.
a_case claim-cross-not
a_claim "$ADVANCE" "$A_CLAIM_GOOD
  Do not verify it yourself."
assert_eq "HARNESS-102 AC-1: complete-story's forbidden phrase in advance-story's bullet is not advance-story's rule: silent" \
  "" "$(adj_problems "$d")"

a_case claim-next-bullet
a_claim "$COMPLETE" '- **A claim that the contract is wrong is adjudicated.**
- A fresh `lead-po` on the ADJUDICATE row answers upheld or rejected; `**Adjudicated`, `## Notes`, AMEND.'
assert_eq "HARNESS-102 AC-1: the words in the NEXT bullet do not count: seven lines" \
  "$(for w in "${CLAIM_NEEDLES[@]}"; do r_say "$COMPLETE" "$A_CLAIM" "$w"; printf '\n'; done)" "$(adj_problems "$d")"

a_case claim-after-blank
a_claim "$ADVANCE" '- **A claim that the contract is wrong is adjudicated.**

  A fresh `lead-po` on the ADJUDICATE row answers upheld or rejected; `**Adjudicated`, `## Notes`, AMEND.'
assert_eq "HARNESS-102 AC-1: the words after a blank line are past the bullet's end: seven lines" \
  "$(for w in "${CLAIM_NEEDLES[@]}"; do r_say "$ADVANCE" "$A_CLAIM" "$w"; printf '\n'; done)" "$(adj_problems "$d")"

A_CLAIM_NONE="${A_CLAIM_GOOD/#- \*\*A claim that the contract/- **A claim the contract}"
for pair in "$ADVANCE|$L_ADV_CLAIM_NONE" "$COMPLETE|$L_CB_CLAIM_NONE" "$LEADPO|$L_LP_CLAIM_NONE"; do
  f="${pair%%|*}"; want="${pair#*|}"
  a_case "claim-none-${f##*/}"
  a_claim "$f" "$A_CLAIM_NONE"
  assert_eq "HARNESS-102 AC-1: $f with no bullet beginning \`$CLAIM_START\` gives the one line" \
    "$want" "$(adj_problems "$d")"
done

# ---------------------------------------------------------------------------
describe "HARNESS-102 AC-1: lead-po.md's dispatch section and description, diff-review's section 5"

a_case lp-disp-without
write_a_leadpo "$d" "$A_LP_DESC_GOOD" "${A_LP_DISP_GOOD//ADJUDICATE row/elsewhere}" "$A_CLAIM_GOOD"
assert_eq "HARNESS-102 AC-1: lead-po.md's dispatch section without \`ADJUDICATE row\` gives exactly the one line (## Orchestrating after it carries it)" \
  "$(r_say "$LEADPO" "$LP_DISP_HEAD" 'ADJUDICATE row')" "$(adj_problems "$d")"

a_case lp-disp-three
write_a_leadpo "$d" "$A_LP_DESC_GOOD" "${A_LP_DISP_GOOD//Four pieces of work/Three pieces of work}" "$A_CLAIM_GOOD"
assert_eq "HARNESS-102 AC-1: lead-po.md's dispatch section still counting \`Three pieces of work\` gives exactly the one line" \
  "$(r_still "$LEADPO" "$LP_DISP_HEAD" 'Three pieces of work')" "$(adj_problems "$d")"

a_case lp-disp-none
c="$(cat "$d/$LEADPO")"; printf '%s\n' "${c//"$LP_DISP_HEAD"/## When you are dispatched}" > "$d/$LEADPO"
assert_eq "HARNESS-102 AC-1: no line exactly \`$LP_DISP_HEAD\` gives the one line" \
  "$L_LP_DISP_NONE" "$(adj_problems "$d")"

for w in "${LP_DESC_NEEDLES[@]}"; do
  a_case "lp-desc-without-${w//[^a-zA-Z]/_}"
  write_a_leadpo "$d" "${A_LP_DESC_GOOD//"$w"/elsewhere}" "$A_LP_DISP_GOOD" "$A_CLAIM_GOOD"
  assert_eq "HARNESS-102 AC-1: lead-po.md's description without \`$w\` gives exactly the one line (the body carries it)" \
    "$(r_say "$LEADPO" 'its description' "$w")" "$(adj_problems "$d")"
done

a_case lp-desc-none
write_a_leadpo "$d" 'summary: Product owner, on the PLANNED, DIFF-REVIEW and ADJUDICATE rows.' "$A_LP_DISP_GOOD" "$A_CLAIM_GOOD"
assert_eq "HARNESS-102 AC-1: no \`description:\` line in lead-po.md's frontmatter gives the one line" \
  "$L_LP_DESC_NONE" "$(adj_problems "$d")"

a_case sk5-without
write_a_skill "$d" "${A_SK5_GOOD//\*\*Adjudicated/an adjudication}"
assert_eq "HARNESS-102 AC-1: diff-review's section 5 without \`**Adjudicated\` gives exactly the one line (sections 4 and 6 carry it)" \
  "$(r_say "$SKILL" "$SK5_HEAD" '**Adjudicated')" "$(adj_problems "$d")"

a_case sk5-none
c="$(cat "$d/$SKILL")"; printf '%s\n' "${c//"$SK5_HEAD"/## 5. What happens next}" > "$d/$SKILL"
assert_eq "HARNESS-102 AC-1: no line exactly \`$SK5_HEAD\` gives the one line" \
  "$L_SK5_NONE" "$(adj_problems "$d")"

for f in "$ADVANCE" "$COMPLETE" "$LEADPO" "$SKILL"; do
  a_case "missing-${f##*/}"
  rm -f "${d:?}/${f:?}"
  assert_eq "HARNESS-102 AC-1: a missing $f gives only \`file is missing\`" \
    "$f: file is missing" "$(adj_problems "$d")"
done

summary "dispatch"
