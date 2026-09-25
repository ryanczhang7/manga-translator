#!/usr/bin/env bash
# The process-count instrument - MT-041 AC-1 and AC-4.
#
# Sourced by a suite AFTER _lib.sh (it uses json_str and REPO_ROOT). It counts
# the EXTERNAL processes one run of the real phase-guard hook spawns, read off
# a `bash -x` trace, which is how MT-041's baseline of 44 was measured.
#
# What counts as a spawn: a traced simple command whose name is neither a bash
# builtin nor a keyword and resolves to an executable on PATH. Functions
# (classify, to_rel, ...) never resolve on PATH, so they are not counted; a
# `$( )` subshell that runs only builtins forks but execs nothing, and is not
# counted either - the story's 44 is a count of tools, not of forks.
#
# Two keys are refined because the criteria name them:
#
#   git <subcommand>    so that `git check-ignore` is its own line (AC-4)
#   tr:<form>           the SEMANTIC form of a tr call, decided on its argv
#                       rather than on how xtrace happened to quote it:
#                         tr:space      tr -d '[:space:]'
#                         tr:backslash  tr '\134' '/'
#                         tr:quotes     tr -d with the two-character set "'
#                         tr:lower      tr 'A-Z' 'a-z'
#                         tr:other      anything else (the argv is appended)
#
# Nothing here imports from .claude/hooks: the instrument must not share the
# assumptions of the code it measures.

# The PS4 marker. bash repeats its FIRST character once per nesting level, so a
# traced command line is `^\++<marker>`; a continuation line of a multi-line
# trace (an awk program, a heredoc value) never starts with it.
SPAWN_PS4='+|xt| '

# spawn_trace <fixture> <tool> <key> <value> <trace-file>   Runs the REAL hook,
# as _lib.sh's guard() does, with xtrace on from its first line, and writes the
# trace to the file; the hook's stdout (its verdict) goes to <trace-file>.out.
#
# PS4 is set INSIDE the traced shell rather than passed in the environment: bash
# declines to import PS4 from the environment in some configurations, and a
# trace with no marker would count zero spawns and pass every "at most" below.
# `set -x` then `.` is `bash -x` for this script - it reads its own directory
# from BASH_SOURCE, which a sourced file sets exactly as an executed one does.
spawn_trace() {
  printf '{"tool_name":"%s","tool_input":{"%s":"%s"}}' "$2" "$3" "$(json_str "$4")" \
    | CLAUDE_PROJECT_DIR="$1" \
      bash -c 'PS4="$0"; set -x; . "$1"' "$SPAWN_PS4" "$REPO_ROOT/.claude/hooks/phase-guard.sh" \
      >"$5.out" 2>"$5"
}

# spawn_trace_fn <fixture> <trace-file> <shell text>   The same instrument around
# an arbitrary snippet run with lib.sh sourced - for a single classify call.
spawn_trace_fn() {
  CLAUDE_PROJECT_DIR="$1" \
    bash -c '. "$1/.claude/hooks/lib.sh"; PS4="$0"; set -x; eval "$2"' \
      "$SPAWN_PS4" "$REPO_ROOT" "$3" >"$2.out" 2>"$2"
}

# spawn_traced_calls <trace-file> <function>   How many times the trace shows
# <function> being called. The vacuity control: an "at most N" over a trace
# that never reached the code under test is satisfied by nothing happening.
spawn_traced_calls() {
  _spawn_commands "$1" | awk -F'\t' -v f="$2" '$1 == f { n++ } END { print n + 0 }'
}

# _spawn_commands <trace-file>   "<name>\t<rest of the traced line>" for every
# traced simple command, leading NAME=value assignments removed. Quote-aware for
# xtrace's own quoting: '...' and $'...'.
_spawn_commands() {
  awk -v M="${SPAWN_PS4#+}" '
    function value(   c) {
      # consume one shell word starting at S[i]; stops at a literal space
      while (i <= n) {
        c = substr(S, i, 1)
        if (c == " ") return 1
        if (c == Q) {
          j = index(substr(S, i + 1), Q); if (j == 0) return 0
          i += j + 1; continue
        }
        if (c == "$" && substr(S, i + 1, 1) == Q) {
          i += 2
          while (i <= n && substr(S, i, 1) != Q) { if (substr(S, i, 1) == "\\") i++; i++ }
          if (i > n) return 0
          i++; continue
        }
        # A backslash OUTSIDE quotes escapes the next character. xtrace spells
        # an embedded single quote as '\'' - without this, that escaped quote
        # opened a span and the word after it became a "command" (MT-041 R-1).
        if (c == "\\") { i += 2; continue }
        i++
      }
      return 1
    }
    BEGIN { Q = sprintf("%c", 39) }
    {
      k = match($0, /^\++/); if (k == 0) next
      if (substr($0, RLENGTH + 1, length(M)) != M) next
      S = substr($0, RLENGTH + 1 + length(M)); n = length(S); i = 1
      # leading assignments
      while (match(substr(S, i), /^[A-Za-z_][A-Za-z0-9_]*=/)) {
        i += RLENGTH
        if (!value()) { i = n + 1; break }   # an unclosed multi-line value
        while (substr(S, i, 1) == " ") i++
      }
      if (i > n) next
      s0 = i
      if (!value()) next
      w = substr(S, s0, i - s0)
      gsub(Q, "", w)
      print w "\t" substr(S, i + 1)
    }' "$1"
}

# spawn_tally <trace-file>   "<count>\t<key>" per key, then "<total>\tTOTAL".
spawn_tally() {
  local builtins name rest key sub
  builtins=" $(compgen -b | tr '\n' ' ') $(compgen -k | tr '\n' ' ') "
  _spawn_commands "$1" | while IFS=$'\t' read -r name rest; do
    [ -n "$name" ] || continue
    case "$builtins" in *" $name "*) continue ;; esac
    type -P -- "$name" >/dev/null 2>&1 || continue
    key="$name"
    case "$name" in
      git)
        # the first argument that is not an option or an option's value
        sub="$(eval "set -- $rest"; while [ $# -gt 0 ]; do
                 case "$1" in -C|-c) shift 2 ;; -*) shift ;; *) printf '%s' "$1"; break ;; esac
               done)"
        key="git $sub" ;;
      tr)
        key="$(eval "set -- $rest"
               if   [ "$#" = 2 ] && [ "$1" = -d ] && [ "$2" = '[:space:]' ]; then printf 'tr:space'
               elif [ "$#" = 2 ] && [ "$1" = '\134' ] && [ "$2" = / ];        then printf 'tr:backslash'
               elif [ "$#" = 2 ] && [ "$1" = -d ] && [ "$2" = "\"'" ];        then printf 'tr:quotes'
               elif [ "$#" = 2 ] && [ "$1" = A-Z ] && [ "$2" = a-z ];         then printf 'tr:lower'
               else printf 'tr:other %s' "$rest"; fi)" ;;
    esac
    printf '%s\n' "$key"
  done | sort | uniq -c | awk '{ c = $1; $1 = ""; sub(/^ /, ""); t += c; print c "\t" $0 }
                              END { print t + 0 "\tTOTAL" }'
}

# spawn_count <tally> <key>   The count for one key, 0 when absent. A key that
# ends in `*` is a prefix: `tr:other*` sums every unrecognised tr form.
spawn_count() {
  printf '%s\n' "$1" | awk -F'\t' -v k="$2" '
    { if (substr(k, length(k)) == "*") { if (index($2, substr(k, 1, length(k) - 1)) == 1) t += $1 }
      else if ($2 == k) t += $1 }
    END { print t + 0 }'
}
