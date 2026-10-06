#!/usr/bin/env bash
# Copy a newer harness into a project that is already using one.
#
#   bash scripts/refresh-harness.sh ../agentic-dev-harness
#   bash scripts/refresh-harness.sh --dry-run ../agentic-dev-harness
#
# Run it FROM the project being refreshed, with the path to a checkout of the
# harness. It is the README's procedure, executable, and it exists because that
# procedure was prose and prose was followed wrongly on its first real outing -
# by the agent that had written it, a day earlier. Three separate ways:
#
#   * it recommended `rsync`, which is not present in Git Bash, the shell this
#     harness runs in on Windows;
#   * a wholesale replace of `.claude/skills` deletes a project's OWN stack
#     profile - the one in the way was 17 KB and cited by four documents, and
#     nothing would have said a word;
#   * it omitted `.claude/settings.json` and `.claude/state/README.md`, which are
#     upstream-owned and read as evidence by the settings suite.
#
# Each was a step somebody had to get right by reading carefully, which is a
# requirement this repository does not accept anywhere else.
#
# Three kinds of file, and the middle one is the reason this is not a `cp -r`:
#
#   REPLACED  upstream owns it outright
#   KEPT      inside a replaced directory, but upstream does not ship it, so it
#             is the project's and survives
#   LEFT      project-owned, or needs a human: project.conf, docs, .gitignore,
#             .github/workflows, and the two that must be MERGED rather than
#             copied - paths.conf and CLAUDE.md

set -uo pipefail

# This script replaces scripts/*.sh, and one of those is this file.
#
# Bash reads a script by byte offset as it executes it. Overwrite the file
# underneath and execution resumes at the old offset in the NEW bytes: mid-line,
# mid-block, as whatever that happens to parse as. The first real refresh to hit
# this printed `line 151: ------------: command not found` and ran its
# single-file block a second time; the fixture in refresh.test.sh, with
# different padding, gets a syntax error and dies half way through instead. The
# tree came out correct that once only because the re-entered block was
# idempotent `cp` calls. A few hundred bytes the other way is the `rm -rf` loop
# re-entered with different state, in the one script whose whole purpose is not
# destroying a project's files without saying so.
#
# So run from a private copy. Then the file being READ is never the file being
# WRITTEN, whatever the copy loop does to scripts/. `$0` stays a file with
# identical content, so `--help` still reads its own header out of it.
# The copy goes to a path this script NAMES, under the machine-local state
# directory the harness already owns - not to $TMPDIR and not through mktemp.
# That variable is unset in some of the shells this runs in, and the one place
# it mattered, a mutation backup, lost its backup to exactly that. lib.test.sh
# enforces the rule; .claude/state/README.md carries the row.
if [ -z "${REFRESH_SELF_COPY:-}" ]; then
  _self="$(pwd)/.claude/state/refresh-self.$$.sh"
  if mkdir -p "$(pwd)/.claude/state" 2>/dev/null && cp "$0" "$_self" 2>/dev/null; then
    REFRESH_SELF_COPY="$_self" exec bash "$_self" "$@"
  fi
  # Could not make the copy. Carry on in place rather than refusing: a refresh
  # that runs with this hazard beats one that cannot run at all, and the hazard
  # is only reachable once the copy loop is already underway.
  rm -f "$_self" 2>/dev/null
fi
[ -n "${REFRESH_SELF_COPY:-}" ] && trap 'rm -f "$REFRESH_SELF_COPY"' EXIT

PROJ="$(pwd)"
DRY=0
UP=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '3,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) printf 'refresh-harness: unknown option %s\n' "$a" >&2; exit 2 ;;
    *) UP="$a" ;;
  esac
done

die() { printf 'refresh-harness: %s\n' "$1" >&2; exit 2; }

[ -n "$UP" ] || die "give me the path to a harness checkout: refresh-harness.sh ../agentic-dev-harness"
[ -d "$UP/.claude/hooks" ] && [ -d "$UP/scripts" ] \
  || die "'$UP' does not look like a harness checkout (no .claude/hooks, no scripts)"

# THE PROCEDURE BELONGS TO THE RELEASE BEING INSTALLED, not to the one you are
# leaving. A refresh is normally driven by the project's own copy of this
# script, and that copy is one release behind BY CONSTRUCTION: a change to
# *what* gets copied only takes effect on the refresh AFTER the one that
# delivers it.
#
# Not hypothetical. `.claude/harness/models.conf` joined the single-file list in
# release 23, so a project on 22 running its own script received
# `scripts/plan.sh` without the policy file plan.sh reads - a script delivered
# without the thing it depends on, silently. Every future addition to that list
# has the same one-release delay, and "remember to run upstream's copy" is not a
# mechanism; it is a thing to forget.
#
# So hand over. Upstream's copy knows what upstream ships.
#
# IT TERMINATES ON THE COMPARISON ALONE, and there is deliberately no second
# guard. The script handed to reads `$0` as upstream's file - or as a self-copy
# of it - so `cmp` finds them identical and it takes the other branch. An
# environment flag was here first, and removing it left all 49 assertions green:
# a line nothing can fail is a line whose behaviour nobody has checked, and
# belt-and-braces that cannot be falsified is just braces nobody has looked at.
# What holds this up is the control in refresh.test.sh - identical copies hand
# over to nobody - which is the assertion that goes red if this comparison
# breaks.
#
# REFRESH_SELF_COPY is cleared so the new process makes its own, which matters
# only in the degenerate case where UP and PROJ are the same tree.
UP_SELF="$UP/scripts/refresh-harness.sh"
if [ -f "$UP_SELF" ] && ! cmp -s "$UP_SELF" "$0"; then
  printf 'refresh-harness: upstream ships a different refresh-harness.sh; running that one.\n'
  printf '  A change to WHAT this copies would otherwise take effect one release late.\n\n'
  [ -n "${REFRESH_SELF_COPY:-}" ] && rm -f "$REFRESH_SELF_COPY"
  REFRESH_SELF_COPY= exec bash "$UP_SELF" "$@"
fi

# Refusing rather than warning, on both counts below. A warning at the top of a
# wall of output is a warning nobody reads, and both of these end with a tree
# somebody has to reconstruct by hand.
if [ "$DRY" = 0 ] && git -C "$PROJ" rev-parse --git-dir >/dev/null 2>&1; then
  if [ -n "$(git -C "$PROJ" status --porcelain 2>/dev/null | grep -v '^??')" ]; then
    die "this tree has uncommitted changes. Commit or stash them first - this rewrites
  a lot of files at once, and you want a clean diff to read afterwards."
  fi
fi

# The procedure's own rule, enforced instead of requested: never mid-cycle. The
# hooks being replaced are the ones enforcing the phase the story is standing in.
STATE="$PROJ/.claude/state/current-story.env"
if [ "$DRY" = 0 ] && [ -f "$STATE" ]; then
  ph="$(sed -nE 's/^PHASE=//p' "$STATE" | head -1 | tr -d '[:space:]')"
  sid="$(sed -nE 's/^STORY_ID=//p' "$STATE" | head -1 | tr -d '[:space:]')"
  case "$ph" in
    ""|DONE) ;;
    *) die "story ${sid:-?} is in $ph. Refresh between stories, never mid-cycle: the hooks
  this replaces are the ones enforcing the phase that story is standing in.
  Finish it, or clear the lock with: bash scripts/phase.sh clear" ;;
  esac
fi

say() { printf '%s\n' "$1"; }
act() { [ "$DRY" = 1 ] || eval "$1"; }

upstream_version="$(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$UP/.claude/harness/VERSION" 2>/dev/null | head -1)"
current_version="$(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$PROJ/.claude/harness/VERSION" 2>/dev/null | head -1)"
say "refresh-harness${DRY:+}$([ "$DRY" = 1 ] && printf ' (dry run)')"
say "  from: $UP  (${upstream_version:-unstamped})"
say "  into: $PROJ  (${current_version:-unstamped - predates versioning})"

# --- is the source a RELEASE, or somebody's branch? --------------------------
#
# A CONSUMING PROJECT REFRESHED TO A FEATURE BRANCH AND STAMPED ITS VERSION.
# This repository's clone was left checked out on `harness/masked-lines-traps`,
# whose VERSION read 38 before any release 38 existed. The project read that,
# concluded 38 had shipped, refreshed, and stamped a version no upstream release
# carries - which is exactly the confusion the VERSION file exists to end, and
# would have made its lib.sh report LOCAL on every future refresh.
#
# It had examined the ref carefully - diffed it, confirmed comment-only, re-ran
# its checks against it - and never asked its STATUS. A ref can be fully
# examined and still not be a release, so this asks the question for the reader
# rather than leaving it to occur to them.
#
# Silent on the default branch, because a warning that always prints is not one.
# Skipped entirely when no default branch can be identified: unable to tell is
# not the same as "not a release", and this must not cry wolf at a project whose
# upstream is laid out differently.
src_branch=""; src_default=""
if git -C "$UP" rev-parse --git-dir >/dev/null 2>&1; then
  src_branch="$(git -C "$UP" symbolic-ref --short HEAD 2>/dev/null || true)"
  for cand in "$(git -C "$UP" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')" main master; do
    [ -n "$cand" ] || continue
    git -C "$UP" rev-parse --verify --quiet "$cand" >/dev/null 2>&1 || continue
    src_default="$cand"; break
  done
  if [ -n "$src_branch" ] && [ -n "$src_default" ] && [ "$src_branch" != "$src_default" ] \
     && ! git -C "$UP" merge-base --is-ancestor HEAD "$src_default" 2>/dev/null; then
    say "  NOTE  the source is on '$src_branch', which is not merged into '$src_default'."
    say "        That is not a release: the version above names a tree no release"
    say "        carries, and stamping it here makes your copy claim a version"
    say "        that does not exist. Refresh from '$src_default' unless you mean"
    say "        to vendor unreleased work."
  fi
fi
say ""

kept_any=0

# --- which of YOUR files this is about to overwrite --------------------------
#
# H26, from the field. A project vendors the harness, fixes a harness defect
# locally WITH TESTS, and the next refresh removes the fix and the assertions
# that pin it in one operation - because both live inside the replaced set. The
# selftest is green afterwards, since the tests that would have failed went with
# the code. Nothing reports anything, and that silence is what makes it
# dangerous rather than merely destructive.
#
# The report asked for one `cmp` per replaced file. That does not survive a real
# refresh: across fifteen releases nearly every harness file differs because
# UPSTREAM moved on, and a list of dozens says nothing. The useful question is
# not "does this differ" but "did YOU change it" - and those two need a third
# reference point to tell apart.
#
# Upstream is a git checkout, so there is one. Hash the downstream copy and ask
# whether that blob is REACHABLE from upstream's RELEASE LINE - HEAD, the
# default branch, and that branch's origin counterpart:
#
#   reachable -> this is some release of upstream's. You are BEHIND. Silent.
#   not       -> upstream has never shipped this content. Somebody here wrote it.
#
# The release line, not every ref. Release 51 asked `--all`, and every ref is
# not a release: a live stash, a fetched PR ref, or a tracking ref to a branch
# long deleted on origin - which any clone that never ran `fetch --prune` still
# holds - each vouched for content upstream never shipped (HARNESS-013). The
# default is the one the NOTE above resolved, `$src_default`, read rather than
# resolved again so the two cannot disagree; when there is none the set is HEAD
# alone, and the stash stays out. The `--` is not decoration: without it a file
# or directory named after the branch in upstream's tree makes the name
# ambiguous, rev-list exits 128, the set is empty, and every file reads LOCAL.
#
# Reachable, not merely present. Through release 50 this asked `cat-file -e` -
# does the object EXIST - and a deleted branch, a dropped stash or a fetched PR
# ref leaves its blobs in the store until `git gc`, so a local fix that once
# passed through upstream on a throwaway branch was judged shipped and the alarm
# stayed silent (HARNESS-012). Not `--reflog` either: a deleted branch's tip
# lives on in HEAD's reflog, which would bring the same case back. The set is
# built once and each lookup is a `case`, because on Git Bash a subprocess per
# file costs more than the whole membership test.
#
# A local edit that happens to collide with an unrelated upstream blob would be
# missed; that is a hash collision against real content and not worth guarding.
#
# THE QUIET HALF IS THE POINT. A warning that prints for every replaced file is
# not a warning, and a check that only tests the firing half is satisfied by
# `echo`. Both halves are asserted in refresh.test.sh.
# A SOURCE WITH NO PAST CANNOT ANSWER THIS. The question is whether a blob has
# EVER been upstream's, so it is asked of the object store and needs history,
# not merely the current tree. Against a source built by `git archive` plus
# `git init` - one commit - every file of ours that upstream shipped in an
# EARLIER release matches nothing and is reported as a local edit. Measured by
# a consuming project: five files named LOCAL where the truth was one, which
# teaches the alarm to cry wolf at precisely the moment it is right about the
# sixth.
#
# The branch below already refuses to read "not a git checkout" as clean. A
# shallow or single-commit checkout passes `rev-parse --git-dir` and sails past
# it, which is worse, because it produces a confident answer instead of an
# admission.
up_has_history=0
if git -C "$UP" rev-parse --git-dir >/dev/null 2>&1; then
  if [ "$(git -C "$UP" rev-parse --is-shallow-repository 2>/dev/null)" != "true" ] \
     && [ "$(git -C "$UP" rev-list --count -n 2 HEAD 2>/dev/null || echo 0)" -ge 2 ]; then
    up_has_history=1
  fi
fi

local_changes=""
if [ "$up_has_history" = 1 ]; then
  # Every object id reachable from the release line, one per line, padded with
  # a newline at each end so the `case` below matches whole lines, never a
  # prefix of an id.
  NL='
'
  up_starts=(HEAD)
  if [ -n "$src_default" ]; then
    up_starts+=("$src_default")
    git -C "$UP" rev-parse --verify --quiet "refs/remotes/origin/$src_default" >/dev/null 2>&1 \
      && up_starts+=("refs/remotes/origin/$src_default")
  fi
  up_reachable="$(git -C "$UP" rev-list --objects "${up_starts[@]}" -- 2>/dev/null | awk '{print $1}')"
  up_reachable_padded="$NL$up_reachable$NL"
  up_shipped() { case "$up_reachable_padded" in *"$NL$1$NL"*) return 0 ;; esac; return 1; }
  for d in agents commands skills hooks tests; do
    [ -d "$PROJ/.claude/$d" ] && [ -d "$UP/.claude/$d" ] || continue
    while IFS= read -r rel; do
      [ -n "$rel" ] || continue
      [ -e "$UP/.claude/$d/$rel" ] || continue      # yours alone: that is KEPT, above
      h="$(git -C "$PROJ" hash-object ".claude/$d/$rel" 2>/dev/null)" || continue
      [ -n "$h" ] || continue
      up_shipped "$h" && continue
      local_changes="$local_changes .claude/$d/$rel"
    done <<< "$(cd "$PROJ/.claude/$d" && find . -type f 2>/dev/null | sed 's|^\./||')"
  done
  # scripts/*.sh, WHERE THE PRODUCTION CODE IS. Omitted until release 39, and
  # the omission was the dangerous half of H26 rather than a gap at its edge:
  # `scripts/` is blanket REPLACED, so a project that fixed a harness DEFECT
  # there had the fix overwritten with nothing said, while the alarm named the
  # test file sitting beside it. A consuming project hit exactly that with its
  # local fix to check-sigpipe.sh - the guard reported, the code did not.
  #
  # Subdirectories are deliberately not walked: `scripts/*.sh` is what the copy
  # loop replaces, and a project's own `scripts/vitest/setup.ts` is untouched by
  # it, so naming it here would be a warning about something that is not going
  # to happen.
  for p in "$PROJ"/scripts/*.sh; do
    [ -f "$p" ] || continue
    b="$(basename "$p")"
    [ -f "$UP/scripts/$b" ] || continue            # yours alone: KEPT, not replaced
    h="$(git -C "$PROJ" hash-object "scripts/$b" 2>/dev/null)" || continue
    [ -n "$h" ] || continue
    up_shipped "$h" && continue
    local_changes="$local_changes scripts/$b"
  done
  for f in .claude/harness/phases.conf .claude/harness/models.conf \
           .claude/harness/rules.md .claude/settings.json .claude/state/README.md; do
    [ -f "$PROJ/$f" ] && [ -f "$UP/$f" ] || continue
    h="$(git -C "$PROJ" hash-object "$f" 2>/dev/null)" || continue
    [ -n "$h" ] && up_shipped "$h" && continue
    local_changes="$local_changes $f"
  done
else
  # A check that cannot run must not read as a clean result.
  local_unknown=1
fi

# Said BEFORE the KEPT/REPLACED report, and printed in a dry run, because the
# entire value is seeing it while the files are still there.
if [ -n "$local_changes" ]; then
  say "  LOCAL - upstream has never shipped your copy of these, so somebody here"
  say "          wrote them. A refresh REPLACES them, and any test that pinned"
  say "          the change goes with it:"
  for f in $local_changes; do say "    LOCAL     $f"; done
  say ""
  say "          If one is a harness fix, send it upstream before refreshing, or"
  say "          the next refresh takes the fix and its alarm together."
  say ""
elif [ -n "${local_unknown:-}" ]; then
  say "  note: '$UP' is not a git checkout, so this could not check which of your"
  say "        harness files you have changed. Anything you fixed locally in a"
  say "        replaced file will be overwritten without being named."
  say ""
fi

# --- directories upstream owns, except for what it does not ship -------------
for d in agents commands skills hooks tests; do
  src="$UP/.claude/$d"; dst="$PROJ/.claude/$d"
  [ -d "$src" ] || continue
  if [ -d "$dst" ]; then
    # Anything here that upstream does not ship belongs to the project. This is
    # the whole reason the script exists: a directory replace is silent about it.
    while IFS= read -r rel; do
      [ -n "$rel" ] || continue
      [ -e "$src/$rel" ] && continue
      say "  KEPT      .claude/$d/$rel  (upstream does not ship it - yours)"
      kept_any=1
    done <<< "$(cd "$dst" && find . -type f 2>/dev/null | sed 's|^\./||')"
  fi
done

# Preserve, replace, restore. Done in one pass per directory so that a failure
# leaves the project's own files somewhere findable rather than nowhere.
KEEP="$PROJ/.claude/.refresh-keep.$$"
if [ "$DRY" = 0 ]; then
  rm -rf "$KEEP"; mkdir -p "$KEEP"
  for d in agents commands skills hooks tests; do
    src="$UP/.claude/$d"; dst="$PROJ/.claude/$d"
    [ -d "$src" ] && [ -d "$dst" ] || continue
    while IFS= read -r rel; do
      [ -n "$rel" ] || continue
      [ -e "$src/$rel" ] && continue
      mkdir -p "$KEEP/$d/$(dirname "$rel")"
      cp "$dst/$rel" "$KEEP/$d/$rel"
    done <<< "$(cd "$dst" && find . -type f 2>/dev/null | sed 's|^\./||')"
  done
fi

# One loop decides and reports. It used to be two - a copy loop inside the
# dry-run guard, and a report loop outside it walking a second copy of the same
# list - with nothing tying them together, so shortening the copy loop left the
# report printing `REPLACED .claude/hooks/` over a hook that had not been
# touched. A refresh that silently skips the phase lock and then says it updated
# it is the worst thing this script can do. The report is now a side effect of
# the work rather than a second opinion about it.
replaced_dirs=""
for d in agents commands skills hooks tests; do
  [ -d "$UP/.claude/$d" ] || continue
  if [ "$DRY" = 0 ]; then
    rm -rf "$PROJ/.claude/$d"
    cp -r "$UP/.claude/$d" "$PROJ/.claude/$d"
  fi
  replaced_dirs="$replaced_dirs $d"
done

if [ "$DRY" = 0 ] && [ -d "$KEEP" ]; then
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    mkdir -p "$PROJ/.claude/$(dirname "$rel")"
    cp "$KEEP/$rel" "$PROJ/.claude/$rel"
  done <<< "$(cd "$KEEP" && find . -type f 2>/dev/null | sed 's|^\./||')"
  rm -rf "$KEEP"
fi

for d in $replaced_dirs; do say "  REPLACED  .claude/$d/"; done

# --- single files upstream owns ---------------------------------------------
for f in .claude/harness/phases.conf .claude/harness/models.conf \
         .claude/harness/rules.md .claude/harness/VERSION \
         .claude/settings.json .claude/state/README.md; do
  [ -f "$UP/$f" ] || continue
  act "mkdir -p \"$PROJ/$(dirname "$f")\" && cp \"$UP/$f\" \"$PROJ/$f\""
  say "  REPLACED  $f"
done

# scripts/*.sh only: a project legitimately adds its own scripts, and its own
# subdirectories, and a directory replace would take them.
for f in "$UP"/scripts/*.sh; do
  [ -e "$f" ] || continue
  b="$(basename "$f")"
  act "cp \"$f\" \"$PROJ/scripts/$b\""
done
say "  REPLACED  scripts/*.sh  (your own scripts and subdirectories untouched)"
say ""

# --- what a human still has to do -------------------------------------------
say "  LEFT for you to merge by hand - do not just copy these:"
say "    .claude/harness/paths.conf   upstream's rules PLUS your project's globs."
say "                                 Take upstream as the base and append yours,"
say "                                 so upstream wins on any overlap."
say "    CLAUDE.md                    mostly upstream's, but its tables describe"
say "                                 the template's own conventions. Read it"
say "                                 before keeping a row that is about the"
say "                                 harness repository rather than about you."
say ""
say "  LEFT untouched (project-owned): .claude/harness/project.conf, docs/**,"
say "    .gitignore, .github/workflows/**, and everything outside .claude and scripts."
say ""

if [ "$DRY" = 1 ]; then
  say "Dry run: nothing was written."
  exit 0
fi

say "Now, in this order:"
say "  bash scripts/selftest.sh        the machinery everything else depends on,"
say "                                  and the file set you just replaced"
say "  bash scripts/doctor.sh          also tells you whether CI runs these checks"
say "  bash scripts/gates.sh           your project, under the new harness"
[ "$kept_any" = 1 ] && say "" && say "Read the KEPT lines above before you commit: those files are yours, and a
directory replace would have deleted them without a word."
exit 0
