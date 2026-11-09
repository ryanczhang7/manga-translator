#!/usr/bin/env bash
# Dispatch guard: the two long runs of a story go to a feature-developer
# dispatch that returns a verdict, and the seconds-long check stays the
# orchestrator's own (HARNESS-085).
#
# The orchestrator runs on `fable` and, before this story, ran the full
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

S1='1. Review the change with the `diff-review` skill.'
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

summary "dispatch"
