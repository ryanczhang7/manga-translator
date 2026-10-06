#!/usr/bin/env bash
# Check that this machine can actually run the harness and this project.
#
#   bash scripts/doctor.sh
#
# Two layers:
#   1. The harness itself - needs only git and bash.
#   2. The project - every executable named by a gate or task in
#      .claude/harness/project.conf must be on PATH.
#
# Run it after cloning, after picking a stack, and any time a gate fails with
# "command not found".
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$ROOT/.claude/harness/project.conf"
missing=0
# Parsing project.conf with builtins only: a process per field (sed, cut, and
# the fork of every `$(...)`) cost minutes per manifest walk on a slow-spawning
# host. The same four helpers as scripts/gates.sh, copied rather than shared:
# this script reports a missing lib.sh, so it cannot depend on one. See
# gates.sh for the full account.
#
# trim <string> [var]   <string> without leading or trailing [:space:] - the
# carriage return of a CRLF manifest included, which this script relies on.
# Printed, or assigned to <var>.
# from_field <n> <string> <var>   cut's `-f<n>-`, untrimmed: the later `|`s
# kept, a string with no `|` returned whole, too few fields giving ''.
# rest <n> <string> <var>    trimmed `-f<n>-`.
# field <n> <string> <var>   trimmed `-f<n>`.
# Never name `_t`, `_r`, `_i` or `_v` as <var> (bash's dynamic `local`).
trim() { local _t="$1"; _t="${_t#"${_t%%[![:space:]]*}"}"; _t="${_t%"${_t##*[![:space:]]}"}"; if [ $# -gt 1 ]; then printf -v "$2" '%s' "$_t"; else printf '%s' "$_t"; fi; }
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

check() { # <executable> <what it is for>
  if command -v "$1" >/dev/null 2>&1; then
    printf '  ok       %-12s %s\n' "$1" "$(command -v "$1")"
  else
    printf '  MISSING  %-12s needed for: %s\n' "$1" "$2"
    missing=$((missing+1))
  fi
}

printf 'Harness prerequisites\n'
check git  "everything"
check bash "the hooks and these scripts"
printf '  ok       %-12s %s\n' "bash ver" "${BASH_VERSION%%(*}"

# Which harness this is. Printed here rather than anywhere else because this is
# the output a project quotes into environment.md and a field report quotes back
# upstream - and the question "which harness did you measure" has now gone
# unanswered twice, at the cost of re-verifying findings that were already fixed.
# An absent stamp is not a blank field: it is a copy from before stamping, which
# is older than every stamped version.
release_of() { # <tree> - its harness stamp: first non-comment, non-blank line
  local v
  v="$(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$1/.claude/harness/VERSION" 2>/dev/null | head -1)"
  trim "${v:-}"
}
hv="$(release_of "$ROOT")"
printf '  ok       %-12s %s\n' "harness ver" "${hv:-unstamped (predates versioning; older than any release)}"

# Which worktree this is, and whether its harness agrees with the main
# checkout's.
#
# A git worktree has its own working directory, and `.claude/state/*` is
# gitignored, so every worktree already carries its own phase lock, its own gate
# stamp and its own copy of the harness. That is what makes two stories in
# flight possible. It is also how two trees end up on DIFFERENT harness
# releases: refresh-harness.sh refreshes the tree it is run in and leaves its
# neighbours alone - correctly - and until this row existed nothing reported the
# result. A worktree quietly one release behind runs different hooks and
# different gates from the tree beside it.
#
# Detection: `--git-dir` and `--git-common-dir` are equal in the main checkout
# and differ in a linked worktree, where the common dir is the main checkout's
# `.git` and the git dir is a subdirectory of it. Measured on git
# 2.55.0.windows.5: both print the bare string `.git` in the main checkout and
# absolute paths in a linked worktree, so a plain string compare answers both
# real cases and `--path-format=absolute` (which needs git >= 2.31) is not
# needed. The `cd "$ROOT"` matters: a relative `.git` resolves against the
# caller's directory otherwise, and doctor is run from anywhere.
#
# Printed here, above the early `project.conf has no commands` exit, so that an
# unbootstrapped tree gets the row too. Not a git repository at all - a
# harness unpacked into a plain directory - prints nothing and counts nothing.
wt_gitdir="$(cd "$ROOT" && git rev-parse --git-dir 2>/dev/null)"
wt_common="$(cd "$ROOT" && git rev-parse --git-common-dir 2>/dev/null)"
if [ -n "$wt_gitdir" ] && [ -n "$wt_common" ]; then
  if [ "$wt_gitdir" = "$wt_common" ]; then
    printf '  ok       %-12s main checkout, harness %s\n' \
      "worktree" "${hv:-unstamped}"
  else
    main_tree="$(cd "$ROOT" && cd "$wt_common/.." 2>/dev/null && pwd)"
    main_hv="$(release_of "${main_tree:-$ROOT}")"
    if [ "$hv" = "$main_hv" ]; then
      printf '  ok       %-12s linked worktree of %s, harness %s\n' \
        "worktree" "${main_tree:-$wt_common}" "${hv:-unstamped}"
    else
      printf '  MISSING  %-12s linked worktree, harness %s - main checkout is %s\n' \
        "worktree" "${hv:-unstamped}" "${main_hv:-unstamped}"
      printf '  %-10s   the main checkout is %s\n' "" "${main_tree:-$wt_common}"
      printf '  %-10s   refresh-harness.sh updates the tree it is run in; the\n' ""
      printf '  %-10s   others keep their own release until refreshed too\n' ""
      missing=$((missing+1))
    fi
  fi
fi

printf '\nHarness integrity\n'
for f in phase-guard.sh inject-state.sh gate-reminder.sh statusline.sh lib.sh; do
  if [ -f "$ROOT/.claude/hooks/$f" ]; then
    if bash -n "$ROOT/.claude/hooks/$f" 2>/dev/null; then
      printf '  ok       %s\n' ".claude/hooks/$f"
    else
      printf '  BROKEN   %s (syntax error)\n' ".claude/hooks/$f"; missing=$((missing+1))
    fi
  else
    printf '  MISSING  %s\n' ".claude/hooks/$f"; missing=$((missing+1))
  fi
done
for f in paths.conf phases.conf models.conf project.conf; do
  [ -f "$ROOT/.claude/harness/$f" ] \
    && printf '  ok       %s\n' ".claude/harness/$f" \
    || { printf '  MISSING  %s\n' ".claude/harness/$f"; missing=$((missing+1)); }
done

printf '\nProject toolchain (from project.conf)\n'
BOOTSTRAPPED="$(grep -E '^BOOTSTRAPPED=' "$CONF" 2>/dev/null | head -1)"
BOOTSTRAPPED="${BOOTSTRAPPED#*=}"; BOOTSTRAPPED="${BOOTSTRAPPED//[[:space:]]/}"
seen=""
found_any=0
while IFS= read -r line; do
  trim "$line" tline
  case "$tline" in ''|'#'*) continue ;; esac
  case "$line" in *'|'*) ;; *) continue ;; esac
  field 1 "$line" kind
  case "$kind" in gate|task) ;; *) continue ;; esac
  field 2 "$line" id
  rest  5 "$line" cmd
  [ -z "$cmd" ] && continue
  found_any=1
  exe=$(printf '%s' "$cmd" | awk '{print $1}')
  case " $seen " in *" $exe "*) continue ;; esac
  seen="$seen $exe"
  check "$exe" "$kind '$id'"
done < "$CONF"

# --- does CI run the harness's own checks? ----------------------------------
#
# .github/workflows/** is PROJECT-owned: a refresh never touches it, correctly,
# because a project adds its toolchain setup there. The consequence is that the
# template's workflow and the project's diverge from bootstrap onward with
# nothing comparing them - and one real project's CI ran gates.sh but never
# selftest.sh, so the harness's own tests had not executed there once. That is
# how a re-vendor went green with two suites failing.
#
# This lives in doctor rather than in the selftest on purpose: a check that only
# runs inside the suite CI is not running cannot report that CI is not running
# it. doctor is run by hand, at setup, and after a refresh.
#
# It asks only for what the harness cannot do without, and is satisfied by any
# workflow file, because splitting jobs across files is a legitimate layout.
WFDIR="$ROOT/.github/workflows"
if [ -d "$WFDIR" ] && ls "$WFDIR"/*.yml >/dev/null 2>&1; then
  printf 'Continuous integration\n'
  wf_all="$(cat "$WFDIR"/*.yml 2>/dev/null)"
  ci_missing=0
  for want in selftest.sh gates.sh check-boundaries.sh check-sigpipe.sh check-grep-count.sh; do
    case "$wf_all" in
      *"scripts/$want"*) ;;
      *)
        printf '  MISSING  %-12s no workflow runs scripts/%s\n' "ci" "$want"
        ci_missing=$((ci_missing+1)) ;;
    esac
  done
  if [ "$ci_missing" -gt 0 ]; then
    printf '  %-10s   those checks are never run on a machine that is not yours\n' ""
    printf '  %-10s   .github/workflows/** is project-owned, so a harness refresh\n' ""
    printf '  %-10s   cannot add them for you - add the steps from the template\n' ""
    missing=$((missing+ci_missing))
  else
    printf '  ok       %-12s runs the self-test, the gates, the boundaries check and the SIGPIPE guard\n' "ci"
  fi
  printf '\n'
fi

if [ "$found_any" = 0 ] && ! grep -qE '^[[:space:]]*discovery[[:space:]]*\|' "$CONF"; then
  printf '  (nothing configured yet)\n'
  printf '\nproject.conf has no commands, so there is no toolchain to check.\n'
  printf 'This is expected before /plan-product has chosen a stack.\n'
  printf 'Next: /create-product, then /plan-product, then /setup-environment.\n'
  exit 0
fi

printf '\n'
printf '\nProject dependencies\n'
# A global toolchain on PATH is not the same as this project's libraries being
# installed. Checked by manifest: if the manifest exists, its install directory
# must too. Only Node and Python are checked - cargo fetches on build, and Godot
# addons are committed with the project.
#
# Limitation: a monorepo with per-workspace node_modules is not detected here.
dep_found=0
dep_check() { # <manifest> <install dir> <label>
  [ -e "$ROOT/$1" ] || return 0
  dep_found=1
  if [ -e "$ROOT/$2" ]; then
    printf '  ok       %-10s %s present\n' "$3" "$2"
  else
    printf '  MISSING  %-10s %s exists but %s/ is not installed\n' "$3" "$1" "$2"
    printf '  %-10s install them: bash scripts/task.sh install, if project.conf defines that task\n' ""
    missing=$((missing+1))
  fi
}
dep_check package.json      node_modules node
dep_check pyproject.toml    .venv        python
dep_check requirements.txt  .venv        python
[ "$dep_found" = 0 ] && printf '  (no dependency manifests found yet)\n'

printf '\nTest discovery\n'
# A test runner discovers files by glob, and a glob that stops matching says
# nothing: a coverage threshold on a directory no project includes is satisfied
# vacuously, a workspace member dropped from the include list takes its whole
# suite with it, and both look exactly like a clean run. A real instance cost a
# project a directory whose every test was silently never executed.
#
# The rule that catches it: a claim about what a runner DISCOVERS is verified by
# running the runner, never by reading its configuration - reading the config is
# how it stayed invisible. Each `discovery` line in project.conf is such a
# command, and it must exit 0.
disc_found=0
while IFS= read -r line; do
  trim "$line" tline
  case "$tline" in ''|'#'*) continue ;; esac
  case "$line" in *'|'*) ;; *) continue ;; esac
  field 1 "$line" kind
  [ "$kind" = "discovery" ] || continue
  field 2 "$line" id
  field 3 "$line" cwd; [ -z "$cwd" ] && cwd="."
  rest  4 "$line" cmd
  [ -n "$cmd" ] || continue
  disc_found=1
  # `pipefail` is OFF for a discovery command, and only for a discovery command.
  #
  # These lines end in a matcher by nature - `... | grep -q "src/ui/"` - and
  # `grep -q` exits on its first match. The producer is still writing, takes
  # SIGPIPE, and dies 141; under pipefail that corpse becomes the pipeline's
  # status, and doctor reports "nothing discovered" about a tree where
  # everything is discovered. It is size-dependent, so it passes on a small
  # project and on every fixture in the suite, and starts failing later.
  #
  # A discovery line asks one question - does this find anything - and the
  # matcher's own status is the answer. That is not true of a GATE command,
  # whose status means "did the tool succeed", so gates.sh keeps pipefail: there,
  # a failing test runner whose output still matched would be a vacuous pass.
  if ( set +o pipefail; cd "$ROOT/$cwd" 2>/dev/null && eval "$cmd" ) >/dev/null 2>&1; then
    printf '  ok       %-12s discovered\n' "$id"
  else
    printf '  MISSING  %-12s nothing discovered by: %s\n' "$id" "$cmd"
    printf '  %-10s   tests under it would be committed and never run\n' ""
    missing=$((missing+1))
  fi
done < "$CONF"
[ "$disc_found" = 0 ] && printf '  (none declared; see the discovery format in project.conf)\n'
printf '
'


if [ "$missing" -gt 0 ]; then
  printf '%d thing(s) missing.\n' "$missing"
  [ -f "$ROOT/docs/wiki/environment.md" ] \
    && printf 'Install instructions for this project: docs/wiki/environment.md\n' \
    || printf 'No docs/wiki/environment.md yet. Run /setup-environment to write one.\n'
  exit 1
fi

printf 'Everything this project needs is installed.'
[ "$BOOTSTRAPPED" = "yes" ] || printf ' (project.conf is not bootstrapped yet.)'
printf '\n'
