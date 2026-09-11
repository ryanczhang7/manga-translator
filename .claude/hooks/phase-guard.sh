#!/usr/bin/env bash
# PreToolUse hook: enforce the RED -> GREEN phase lock.
#
# While a story is active, this refuses writes that would violate the current
# phase — production code during RED, test edits during GREEN. When no story is
# active it does nothing at all.
#
# It inspects Write/Edit/MultiEdit/NotebookEdit targets directly, and Bash
# commands heuristically (redirects, tee, sed -i, cp/mv, rm, touch), because an
# agent that cannot use Edit will happily reach for `cat > file`.

set -uo pipefail
HOOK_INPUT="$(cat)"
# shellcheck source=lib.sh
# No ERR trap: without set -e bash already continues past failures, so the
# hook degrades to "allow" on any internal problem, which is what we want.
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh" 2>/dev/null || exit 0


load_state
[ "$PHASE" = "IDLE" ] && exit 0
[ -f "$HARNESS_DIR/paths.conf" ] || exit 0

TOOL="$(json_get_string tool_name || true)"

check_path() {
  local raw="$1" rel cat
  [ -z "$raw" ] && return 0
  rel="$(to_rel "$raw")"
  [ -z "$rel" ] && return 0
  cat="$(classify "$rel")"
  if ! phase_allows "$cat"; then
    deny "BLOCKED by the harness phase lock.

  story:    ${STORY_ID:-unknown}
  phase:    $PHASE
  path:     $rel
  category: $cat

$(phase_message)

If this write is genuinely correct, change the phase deliberately rather than
working around the lock:  bash scripts/phase.sh set ${STORY_ID:-<id>} <PHASE>"
  fi
  return 0
}

# decline <token>   A parse the guard does not believe. It notes the token in
# .claude/state/phase-guard-declined.log and allows the command: a denial
# nobody can act on costs more than the write it might have caught, and the
# note is what turns "the guard is noisy" into a bug report with a token in it.
# Machine-local, like the rest of .claude/state, and never fatal - a hook that
# cannot write its own note still has to let the session continue.
decline() {
  printf 'declined %s in %s: implausible target %s\n' "${STORY_ID:-none}" "$PHASE" "$1" \
    >> "$HARNESS_ROOT/.claude/state/phase-guard-declined.log" 2>/dev/null || true
  return 0
}

case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    check_path "$(json_get_string file_path || true)"
    check_path "$(json_get_string notebook_path || true)"
    ;;
  Bash)
    CMD="$(json_get_string command || true)"
    [ -z "$CMD" ] && exit 0
    # Quoted spans, heredoc bodies and backslash escapes are DATA, not shell
    # syntax. Masking them first is what stops a sed script's `|` or an arrow
    # inside an awk program from being read as an operator; see lib.sh. The
    # extractors below run against the masked text, and each candidate is
    # unmasked again before it is classified.
    MASKED="$(printf '%s' "$CMD" | mask_shell_quotes)"
    # Candidate write targets. Deliberately conservative: we only look at
    # constructs that unambiguously name a destination file.
    #
    # Not by leading command. Exempting `grep`, `awk` and friends as "read-only"
    # is tempting after a run of false positives on them, and it is wrong:
    # `grep -r export src > src/index.ts` writes, and so does every read-only
    # tool on the left of a redirect. What those false positives had in common
    # was quoting, which masking handles, and unparseable output, which
    # path_is_implausible handles. Neither is a property of the command name.
    #
    # Parentheses terminate a target like `;` does: `(cd src && echo x > a.ts)`
    # used to yield `a.ts)`, which the guard declined as unreadable - a hole
    # in the shape of a subshell. `>|` is a redirect too. And `<` ends the
    # rm/touch operand list, because `xargs touch < list` reads `list`.
    CANDIDATES="$(
      {
        printf '%s\n' "$MASKED" | grep -oE '>(>|\|)?[[:space:]]*[^|&;><()[:space:]]+'  | sed -E 's/^>(>|\|)?[[:space:]]*//'
        printf '%s\n' "$MASKED" | grep -oE '\btee\b([[:space:]]+-a)?[[:space:]]+[^|&;><()[:space:]]+' | awk '{print $NF}'
        printf '%s\n' "$MASKED" | grep -oE '\bsed\b[^|&;()]*-i[^|&;()]*'              | awk '{print $NF}'
        printf '%s\n' "$MASKED" | grep -oE '\b(cp|mv)\b[[:space:]]+[^|&;()]+'         | awk '{print $NF}'
        printf '%s\n' "$MASKED" | grep -oE '\b(rm|touch)\b[[:space:]]+[^|&;<>()]+'    | tr ' ' '\n' | grep -vE '^(rm|touch|-.*)$'
      } 2>/dev/null | tr -d '"'"'" | grep -vE '^\s*$|^-|\*|^/dev/' | sort -u
    )"
    # `$` is no longer filtered out here. It was, silently, which made the ONE
    # recipe the harness pushes an agent towards in RED - mutate the production
    # file, watch the corrected test fail, revert - pass unchecked. A candidate
    # whose variable the command text assigns is resolved; one it does not is
    # declined and logged, which is what the guard already does with every other
    # parse it cannot believe. See lib.sh.
    ASSIGNMENTS="$(shell_assignments "$MASKED")"
    # The FILE argument of a scripts/mutate.sh invocation, resolved the same way
    # so that `mutate.sh "$F"` is exempt for the same reason `mutate.sh src/a.ts`
    # is. Only that argument: the payload after `--` is judged normally.
    EXEMPT=""
    while IFS= read -r m; do
      [ -n "$m" ] || continue
      EXEMPT="$EXEMPT
$(resolve_vars "$m" "$ASSIGNMENTS")"
    done <<< "$(mutate_targets "$MASKED")"
    # Where the shell will actually be when those targets are written. A
    # relative path means nothing without it: `cd /tmp/scratch && rm -rf
    # gate-logs` names no repo path at all. An unaccountable cwd skips relative
    # candidates rather than blocking them - fail open.
    CWD_PREFIX=""; CWD_KNOWN=1
    CWD_PREFIX="$(command_cwd "$MASKED")" || CWD_KNOWN=0
    while IFS= read -r target; do
      [ -z "$target" ] && continue
      # Resolved before it is judged, so that `"$F"` is either a real path or an
      # honest decline. Still masked at this point, so a value carrying a quoted
      # space survives as one token.
      target="$(resolve_vars "$target" "$ASSIGNMENTS")"
      case "
$EXEMPT" in *"
$target"*) continue ;; esac
      # Judged while still masked: a metacharacter that survives to here was
      # leaked by the parse rather than quoted by the author. An implausible
      # token means the parse failed, and a failed parse is inconclusive, not
      # a violation - see path_is_implausible in lib.sh.
      if path_is_implausible "$target"; then decline "$target"; continue; fi
      target="$(printf '%s' "$target" | unmask_shell_quotes)"
      # A restored candidate spanning a newline is not a filename; a guard that
      # cannot say what it is looking at does not block. Fail open, as ever.
      case "$target" in *$'\n'*) continue ;; esac
      if path_is_absolute "$target"; then
        check_path "$target"
      elif [ "$CWD_KNOWN" = 1 ]; then
        target="$(normalize_rel "${CWD_PREFIX:+$CWD_PREFIX/}$target")" || continue
        check_path "$target"
      fi
    done <<< "$CANDIDATES"
    ;;
esac

exit 0
