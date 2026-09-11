#!/usr/bin/env bash
# Shared helpers for the harness hooks.
#
# Design rules:
#   * Zero dependencies beyond bash + coreutils (no jq, no python, no node).
#   * Fail OPEN. A bug in a hook must never wedge the session: on any internal
#     error we allow the action. Correctness is defended in depth by the gates
#     and by CI; the hook exists to catch the honest mistake, not the attacker.

HARNESS_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
HARNESS_DIR="$HARNESS_ROOT/.claude/harness"
STATE_FILE="$HARNESS_ROOT/.claude/state/current-story.env"
GATE_STAMP="$HARNESS_ROOT/.claude/state/last-gate-run"

# First line of the block gates.sh writes into a story's ## Gate results.
# check-boundaries.sh looks for it to tell a tool-written record from a pasted
# one.
GATE_MARKER='<!-- gates.sh: written by bash scripts/gates.sh; do not edit or paste by hand -->'

# --- JSON -------------------------------------------------------------------

# json_get_string <key>   reads $HOOK_INPUT, prints the first string value for
# <key> anywhere in the document. Handles backslash escapes.
json_get_string() {
  JKEY="$1" printf '%s' "$HOOK_INPUT" | JKEY="$1" awk '
    { s = s $0 "\n" }
    END {
      key = ENVIRON["JKEY"]
      pat = "\"" key "\"[ \t\r\n]*:[ \t\r\n]*\""
      if (match(s, pat) == 0) exit 1
      i = RSTART + RLENGTH
      out = ""
      while (i <= length(s)) {
        c = substr(s, i, 1)
        if (c == "\\") {
          n = substr(s, i + 1, 1)
          if (n == "n")      out = out "\n"
          else if (n == "t") out = out "\t"
          else if (n == "r") out = out "\r"
          else if (n == "u") { out = out " "; i += 4 }
          else               out = out n
          i += 2
          continue
        }
        if (c == "\"") break
        out = out c
        i++
      }
      printf "%s", out
    }'
}

# json_is_true <key>   exit 0 if "key": true appears in $HOOK_INPUT
json_is_true() {
  printf '%s' "$HOOK_INPUT" | grep -qE "\"$1\"[[:space:]]*:[[:space:]]*true"
}


# --- Shell command text -----------------------------------------------------
#
# The Bash branch of the phase guard extracts write targets from a command
# STRING, with grep and awk, which know nothing about shell quoting. Left to
# themselves they read the inside of a quoted argument as syntax: the `|`
# delimiters in `sed -i 's|a|b|' f.txt` truncate the match so the target looks
# like `s`, and the `>` in `awk '/RED -> GREEN/' story.md` looks like a
# redirect. Both were observed blocking correct commands, one of which wrote
# nothing at all. A lock with false positives teaches the agent that blocks are
# noise, which is the exact instinct the lock exists to suppress.
#
# mask_shell_quotes rewrites every operator and whitespace character that is
# inside a quoted span, inside a heredoc body, or escaped by a backslash, into
# a control character. Such a span then survives extraction as one opaque token
# containing no operators, so the extractors see the command's structure and
# not its data. The mapping is reversible: a candidate that genuinely came from
# a quoted argument - `> "my file.ts"` - is restored by unmask_shell_quotes
# before it is classified.
#
#   |  -> \001   &  -> \002   ;  -> \003   >  -> \004
#   <  -> \005   SP -> \006   TAB-> \007   LF -> \010
#
# Control characters are used because no real command line contains them, so
# the round trip cannot corrupt a path that had one of them already.

mask_shell_quotes() {
  awk '
    function maskchar(c) {
      if (c == "|")  return "\001"
      if (c == "&")  return "\002"
      if (c == ";")  return "\003"
      if (c == ">")  return "\004"
      if (c == "<")  return "\005"
      if (c == " ")  return "\006"
      if (c == "\t") return "\007"
      return c
    }
    function maskstr(t,   k, o) {
      o = ""
      for (k = 1; k <= length(t); k++) o = o maskchar(substr(t, k, 1))
      return o
    }
    BEGIN {
      Q  = sprintf("%c", 39)     # a single quote, without writing one here
      BS = sprintf("%c", 92)     # a backslash, for the same reason
      # <<WORD, <<-WORD, <<"WORD", <<\x27WORD\x27 - the heredoc opener.
      HD = "^<<-?[ \t]*(\"[^\"]+\"|" Q "[^" Q "]+" Q "|[A-Za-z_][A-Za-z0-9_.-]*)"
    }
    { line[NR] = $0 }
    END {
      state = "none"; delim = ""; out = ""
      for (i = 1; i <= NR; i++) {
        s = line[i]

        # Inside a heredoc body: everything is data until the delimiter line.
        if (delim != "") {
          t = s; gsub(/^[ \t]+|[ \t]+$/, "", t)
          if (t == delim) { out = out s; delim = "" } else out = out maskstr(s)
          if (i < NR) out = out "\n"
          continue
        }

        pending = ""; cont = 0
        j = 1; n = length(s)
        while (j <= n) {
          c = substr(s, j, 1)

          if (state == "single") {
            if (c == Q) { out = out c; state = "none" } else out = out maskchar(c)
            j++; continue
          }
          if (state == "double") {
            if (c == BS) {
              if (j == n) { cont = 1; j++; continue }
              # Inside double quotes bash removes a backslash before exactly
              # four characters ($ ` " \) and a newline. Every other backslash
              # is literal - which is every backslash in a Windows path. Eating
              # them turned C:\Users\...\Temp\claude into a word to_rel could
              # not place outside the repository, so a write to the scratchpad
              # this harness tells agents to use was denied as `source`.
              nx = substr(s, j + 1, 1)
              if (nx == "$" || nx == "`" || nx == "\"" || nx == BS) {
                out = out maskchar(nx); j += 2; continue
              }
              out = out c; j++; continue
            }
            # "$( ... )" opens a nested context in which a double quote does
            # NOT close the string: `-m "$(printf "%s" "a -> b")"` is one
            # argument. Read naively, the inner quotes toggle the state and the
            # arrow leaks out as a redirect into a file called `b"`. Everything
            # up to the matching paren is data to the command outside it - a
            # redirect in there is masked too, which fails open, as the guard
            # already does for any target with a `$` in it.
            if (c == "$" && substr(s, j + 1, 1) == "(") {
              out = out c "("; state = "subst"; depth = 1; j += 2; continue
            }
            if (c == "\"") { out = out c; state = "none" } else out = out maskchar(c)
            j++; continue
          }
          if (state == "subst") {
            if (c == "(") depth++
            else if (c == ")") {
              depth--
              if (depth == 0) { out = out c; state = "double"; j++; continue }
            }
            out = out maskchar(c); j++; continue
          }

          # Unquoted. A comment runs to the end of the line and is data: an
          # apostrophe in a comment (`# that is Bob`s`) is not a quote, and
          # treating it as one masked a real redirect on the line after it.
          # (No apostrophe in THIS comment either: it sits inside the single
          # quotes that delimit the awk program.)
          if (c == "#" && (j == 1 || index(" \t;&|(", substr(s, j - 1, 1)) > 0)) {
            out = out maskstr(substr(s, j)); j = n + 1; continue
          }
          if (c == BS) {
            if (j == n) { cont = 1; j++; continue }     # line continuation
            out = out maskchar(substr(s, j + 1, 1)); j += 2; continue
          }
          if (c == Q)    { out = out c; state = "single"; j++; continue }
          if (c == "\"") { out = out c; state = "double"; j++; continue }
          if (c == "<" && substr(s, j + 1, 1) == "<") {
            rest = substr(s, j)
            if (match(rest, HD)) {
              w = substr(rest, RSTART, RLENGTH)
              out = out w
              sub(/^<<-?[ \t]*/, "", w)
              gsub("[\"" Q "]", "", w)
              pending = w
              j += RLENGTH
              continue
            }
          }
          out = out c; j++
        }
        if (pending != "") delim = pending
        # A newline inside an unterminated quote, or after a continuation, is
        # part of one token rather than a command separator.
        if (i < NR) out = out ((state == "none" && cont == 0) ? "\n" : "\010")
      }
      printf "%s", out
    }'
}

unmask_shell_quotes() {
  tr '\001\002\003\004\005\006\007\010' '|&;>< \t\n'
}

# --- Variables in a command string ------------------------------------------
#
# The guard used to discard any write target containing a `$`, silently, on the
# grounds that it could not know what the variable held. That was the one hole
# an agent could not help finding, because the harness's own rules push it
# there: a corrected test has to be earned by mutating the production file it
# pins, in RED, where production source is frozen. `sed -i 's/a/b/' "$F"` was
# how three source files were mutated in one corrective pass. The lock did not
# fail open on them; it was open.
#
# So `$` is no longer a reason to look away. It is resolved where the command
# text says what it holds, and declined - logged, allowed, on H1's terms - where
# it does not. `scripts/mutate.sh` is the sanctioned way to do the thing the
# loophole was serving.

# shell_assignments <masked-command>   NAME=VALUE for every simple assignment
# the command text makes, longest name first so that `$FILE` is not eaten by a
# rule for `$F`.
#
# Only assignments outside quotes count, and masking gives that for free: inside
# a quoted span the preceding space is a control character, so `git commit -m
# "fix: A=b"` does not look like one.
shell_assignments() {
  printf '%s' "$1" \
    | grep -oE '(^|[;&|]|[[:space:]])[A-Za-z_][A-Za-z0-9_]*=[^[:space:];&|<>()]*' \
    | sed -E 's/^[^A-Za-z_]+//' \
    | tr -d '"'"'" \
    | awk -F= 'length($1) > 0 { print length($1) "\t" $0 }' \
    | sort -rn | cut -f2-
}

# resolve_vars <text> <assignments>   Substitutes $NAME and ${NAME} using what
# shell_assignments found. A `$` that survives is one the guard cannot account
# for, and path_is_implausible declines on it.
resolve_vars() {
  local text="$1" line name val
  case "$text" in *'$'*) ;; *) printf '%s' "$text"; return 0 ;; esac
  while IFS= read -r line; do
    case "$line" in *=*) ;; *) continue ;; esac
    name="${line%%=*}"; val="${line#*=}"
    text="${text//\$\{$name\}/$val}"
    text="${text//\$$name/$val}"
  done <<< "$2"
  printf '%s' "$text"
}

# mutate_targets <masked-command>   The FILE argument of every
# `scripts/mutate.sh` invocation in the command.
#
# That file is not a write the lock has to judge, in any phase: mutate.sh backs
# it up to an explicit path, applies the expression, runs the command, restores
# it and verifies the restore with cmp - and exits 90, loudly, if it cannot. The
# exemption is the FILE argument and NOTHING else, so a `--` payload that writes
# somewhere the phase forbids is judged like any other command. mutate.sh is not
# an escape hatch with a flag in front of it.
mutate_targets() {
  printf '%s' "$1" \
    | grep -oE 'scripts[/\\]mutate\.sh[[:space:]]+[^[:space:]|&;<>()]+' \
    | awk '{ print $NF }' \
    | tr -d '"'"'"
}

# --- Paths ------------------------------------------------------------------

# lower <text>   Lower-cased with tr, not with the bash 4 case-conversion
# expansion: macOS ships bash 3.2, where that expansion is a "bad
# substitution" that kills to_rel - after which check_path sees an empty path
# and allows the write. The lock silently off on every stock Mac. The selftest
# greps the shipped scripts for it.
lower() { printf '%s' "$1" | tr 'A-Z' 'a-z'; }

# to_rel <path>   Repo-relative, forward slashes. Empty output means "outside
# this repository", and therefore not the harness's business.
to_rel() {
  local p root lp lr base
  p=$(printf '%s' "$1" | tr '\134' '/')
  root=$(printf '%s' "$HARNESS_ROOT" | tr '\134' '/')
  root="${root%/}"
  lp="$(lower "$p")"
  lr="$(lower "$root")"

  if [[ "$lp" == "$lr"/* ]]; then
    printf '%s' "${p:${#root}+1}"
    return
  fi

  # Absolute path elsewhere on disk (scratchpad, /tmp, another checkout).
  if [[ "$p" == /* || "$p" == ?:/* ]]; then
    # Tolerate C:/ vs /c/ drive spellings by matching the repo folder name.
    base="${root##*/}"
    if [[ "$lp" == */"$(lower "$base")"/* ]]; then
      printf '%s' "${p#*/$base/}"
      return
    fi
    printf '%s' ""
    return
  fi

  printf '%s' "${p#./}"
}

# path_is_implausible <masked candidate>   True when the token an extractor
# produced cannot be a filesystem path at all.
#
# The Bash branch of the guard parses a command STRING with grep and awk. When
# that parse goes wrong it does not fail loudly: it yields a fragment, the
# fragment is classified, and a fragment classifies as `source`, because
# `source` is what classify() falls back to. Denials reported from the field
# have named `=`, `[^` and a backquoted word as the path they were protecting;
# every one of those commands wrote nothing at all.
#
# So a failed parse must be INCONCLUSIVE rather than positive. A guard that
# cannot say what it is looking at is not protecting anything - it is guessing,
# and law 5 ("never work around the phase lock") only holds while a block means
# something. This is the fail-open rule the rest of this file follows, applied
# to the parser's own output rather than to its crashes.
#
# Two rules, deliberately blunt:
#
#   * No alphanumeric character anywhere. `=`, `[^`, `--` and `>` are
#     operators or regex fragments; nobody keeps production code in a file
#     whose name is pure punctuation.
#   * A shell metacharacter that cannot reach a redirect target unquoted. The
#     candidate is tested while still MASKED, so one that was genuinely quoted
#     - `> "src/a>b.ts"` - is a control character by this point and does not
#     trip the rule; one still visible was leaked by the parse.
#
# Both are chosen to have no plausible false negative: `src/app/[id]/page.tsx`
# is a real path in more than one framework, and passes, because it has letters
# in it.
path_is_implausible() {
  local t="${1:-}"
  [ -z "$t" ] && return 0
  case "$t" in
    *'`'*|*'$'*|*'('*|*')'*) return 0 ;;
  esac
  printf '%s' "$t" | grep -q '[[:alnum:]]' || return 0
  return 1
}

# path_is_absolute <path>   True for /x and for C:/x or C:\x.
path_is_absolute() {
  case "$(printf '%s' "$1" | tr '\134' '/')" in
    /*|?:/*) return 0 ;;
    *) return 1 ;;
  esac
}

# normalize_rel <relpath>   Collapse "." and ".." segments. Returns 1, printing
# nothing, when the path climbs above the repository root - which means it is
# not a repo path and not the lock's business.
normalize_rel() {
  local p seg out="" oldIFS
  p="$(printf '%s' "$1" | tr '\134' '/')"
  oldIFS="$IFS"; IFS='/'
  # shellcheck disable=SC2086
  set -- $p
  IFS="$oldIFS"
  for seg in "$@"; do
    case "$seg" in
      ''|.) continue ;;
      ..)
        [ -z "$out" ] && return 1
        case "$out" in */*) out="${out%/*}" ;; *) out="" ;; esac ;;
      *) out="${out:+$out/}$seg" ;;
    esac
  done
  printf '%s' "$out"
  return 0
}

# command_cwd <masked command>   The repo-relative directory that command's
# RELATIVE paths resolve against - "" for the repo root. Returns 1 when the
# command changes directory somewhere the guard cannot account for: another
# checkout, a scratch directory, $HOME, a variable, an option it does not
# understand.
#
# Without this the guard resolves every relative path against the repo root
# regardless of where the shell actually is, and `cd /tmp/scratch && rm -rf
# gate-logs` is reported as deleting production code. That was observed in the
# field, and a false positive is expensive here: law 5 of CLAUDE.md tells
# agents never to route around a block, which only holds while blocks mean
# something.
#
# It cuts the other way too. `cd src && echo x > main.ts` used to be measured
# against the root, where `main.ts` classifies as source only by luck; now it
# is `src/main.ts`, which is what the shell will actually write.
#
# Fail open, as ever: returning 1 means relative candidates are skipped, not
# that they are blocked.
command_cwd() {
  local masked="$1" tgt cur="" rel joined lp lr
  # A bare `cd` goes home. Nothing after it is a repo path.
  printf '%s\n' "$masked" | grep -qE '(^|[|&;(])[[:space:]]*cd[[:space:]]*($|[|&;)])' && return 1
  lr="$(lower "$(printf '%s' "${HARNESS_ROOT%/}" | tr '\134' '/')")"
  while IFS= read -r tgt; do
    [ -z "$tgt" ] && continue
    tgt="$(printf '%s' "$tgt" | unmask_shell_quotes)"
    case "$tgt" in
      *$'\n'*) return 1 ;;   # not a directory name
      -*)      return 1 ;;   # `cd -`, `cd -P dir`, `cd --`
      '~'|'~/'*) return 1 ;;
      *'$'*)   return 1 ;;   # a variable the guard cannot expand
    esac
    if path_is_absolute "$tgt"; then
      lp="$(lower "$(printf '%s' "${tgt%/}" | tr '\134' '/')")"
      if [ "$lp" = "$lr" ]; then cur=""; continue; fi
      rel="$(to_rel "$tgt")"
      if [ -z "$rel" ]; then cur="OUTSIDE"; else cur="$rel"; fi
      continue
    fi
    [ "$cur" = "OUTSIDE" ] && continue
    joined="$(normalize_rel "${cur:+$cur/}$tgt")" || { cur="OUTSIDE"; continue; }
    cur="$joined"
  done <<< "$(printf '%s\n' "$masked" \
    | grep -oE '(^|[|&;(]|[[:space:]])cd[[:space:]]+[^|&;><[:space:]]+' \
    | sed -E 's/.*[[:space:]]cd[[:space:]]+|^cd[[:space:]]+|.*[|&;(]cd[[:space:]]+//' \
    | tr -d '"'"'")"
  [ "$cur" = "OUTSIDE" ] && return 1
  printf '%s' "$cur"
  return 0
}

# classify <relpath>   -> vendor | harness | docs | test | config | ignored | source
#
# One path. Delegates the rule matching to classify_stdin so that the rules
# have exactly one implementation, and so that a single call costs one process
# rather than one per rule in paths.conf - which, at ninety-odd rules, cost
# whole seconds per checked path on Windows and made the guard feel like a
# hang.
classify() {
  local rel="$1" cat
  [ -z "$rel" ] && { printf 'outside'; return; }
  cat="$(printf '%s\n' "$rel" | classify_stdin | awk -F'\t' 'NR == 1 { print $1 }')"
  [ -z "$cat" ] && cat=source
  [ "$cat" = "source" ] && is_ignored "$rel" && cat=ignored
  printf '%s' "$cat"
}

# is_ignored <relpath>   True when the project's own .gitignore covers it.
#
# A path git ignores is generated rather than authored: a test runner's scratch
# directory, a report, a build artefact. Deleting one is not a phase violation,
# and consulting git covers every future tool's scratch directory without a new
# rule in paths.conf. `check-ignore` consults the index, so a TRACKED file is
# never reported as ignored even when a rule would match it.
#
# The trailing-slash retry is not decoration: a directory rule (`.vitest/`)
# does not match the path `.vitest` unless that directory already exists, and
# the case that matters - `rm -rf .vitest` - is exactly the one where the agent
# may be naming a directory git has never seen.
is_ignored() {
  [ -n "${1:-}" ] || return 1
  git -C "$HARNESS_ROOT" check-ignore -q -- "$1"  2>/dev/null && return 0
  git -C "$HARNESS_ROOT" check-ignore -q -- "$1/" 2>/dev/null && return 0
  return 1
}

# classify_stdin   One repo-relative path per input line -> "<category>\t<path>"
# per output line. THE implementation of the paths.conf rules; classify() is a
# single-path wrapper around it. One awk process for any number of paths,
# because spawning one per rule cost whole seconds on Windows.
#
# It does NOT consult git for the `ignored` category, and does not need to: its
# callers feed it paths that git already tracks (a diff, a tree listing, an
# index), and a tracked path is never ignored. classify() adds that check.
#
# The glob-to-regex conversion is a character scan rather than sed, because sed
# bracket expressions are a minefield here (POSIX treats "[." and "[]" as
# collating-symbol openers). ENVIRON rather than -v for the conf path: -v
# processes backslashes.
# The paths.conf glob dialect as an awk function: `**` any number of path
# segments, `*` within one segment, `?` one character, everything else
# literal. One definition, shared by classify_stdin and glob_matches, so that
# a `covers` glob in project.conf means exactly what a paths.conf glob means.
_G2R_AWK='
    function g2r(s,   out, i, n, c) {
      out = ""; i = 1; n = length(s)
      while (i <= n) {
        c = substr(s, i, 1)
        if (c == "*") {
          if (substr(s, i, 3) == "**/") { out = out "(.*/)?"; i += 3; continue }
          if (substr(s, i, 2) == "**")  { out = out ".*";     i += 2; continue }
          out = out "[^/]*"; i++; continue
        }
        if (c == "?") { out = out "[^/]"; i++; continue }
        if (index(".^$+(){}|[]\\", c) > 0) { out = out "\\" c; i++; continue }
        out = out c; i++
      }
      return out
    }'

# glob_matches <glob> <path>   True if the path matches the glob, relative to
# the repository root and case-insensitively, as classify_stdin would judge
# it. ENVIRON rather than -v: -v interprets backslashes.
glob_matches() {
  G="$1" P="$2" awk "$_G2R_AWK"'
    BEGIN {
      p = ENVIRON["P"]; sub(/^\.\//, "", p)
      exit !(tolower(p) ~ ("^" tolower(g2r(ENVIRON["G"])) "$"))
    }'
}

classify_stdin() {
  PATHS_CONF="$HARNESS_DIR/paths.conf" awk "$_G2R_AWK"'
    BEGIN {
      n = 0; conf = ENVIRON["PATHS_CONF"]
      while ((getline line < conf) > 0) {
        sub(/\r$/, "", line)
        if (line ~ /^[[:space:]]*(#|$)/) continue
        if (index(line, "|") == 0) continue
        cat = line; sub(/\|.*/, "", cat); gsub(/[[:space:]]/, "", cat)
        glob = line; sub(/^[^|]*\|/, "", glob)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", glob)
        if (cat == "" || glob == "") continue
        n++; rc[n] = cat; rr[n] = "^" tolower(g2r(glob)) "$"
      }
      close(conf)
    }
    {
      path = $0; sub(/\r$/, "", path); sub(/^\.\//, "", path)
      if (path == "") next
      lp = tolower(path); c = "source"
      for (i = 1; i <= n; i++) if (lp ~ rr[i]) { c = rc[i]; break }
      print c "\t" path
    }'
}

# --- Staleness --------------------------------------------------------------

# code_changed_since <stamp file>   The first path modified after <stamp> that
# the gates would have hashed, or nothing. Used by the Stop hook to tell "the
# gates are stale" from "the gates ran and then something regenerated".
#
# The naive version - `find -newer` over the worktree - counts the gates' own
# exhaust as a change. A coverage report, a build directory, a bundler cache:
# all of them are written BY the gate run, all of them are gitignored, and any
# ad-hoc verification run afterwards recreates them. The Stop hook then blocks
# on `coverage/base.css` with a clean `git status`, which punishes exactly the
# extra verification the harness spends the rest of its documentation asking
# for. Observed in the field, twice.
#
# The set that matters is already defined: it is the one gate_tree_hash covers
# - see gated_stdin - never docs, vendor or ignored. So the question this asks
# is precisely "would the recorded gate hash still match", and the two answers
# cannot drift apart.
#
# Ignored TOP-LEVEL directories are pruned before the walk rather than filtered
# after it, because `src-tauri/target` holds six figures of files and a Stop
# hook has twenty seconds. Everything deeper is filtered by git, one batch call
# for all candidates.
code_changed_since() {
  local stamp="$1" d rel
  [ -f "$stamp" ] || return 0
  set -- "$HARNESS_ROOT" \
    -path "$HARNESS_ROOT/.git" -prune -o \
    -path "$HARNESS_ROOT/.claude/state" -prune -o \
    -path "$HARNESS_ROOT/node_modules" -prune -o \
    -path "$HARNESS_ROOT/docs" -prune -o
  for d in "$HARNESS_ROOT"/*/ "$HARNESS_ROOT"/.*/; do
    [ -d "$d" ] || continue
    rel="${d%/}"; rel="${rel##*/}"
    case "$rel" in .|..|.git|.claude|docs|node_modules) continue ;; esac
    is_ignored "$rel" || continue
    set -- "$@" -path "$HARNESS_ROOT/$rel" -prune -o
  done
  local cands kept out rc
  cands="$(find "$@" -type f -newer "$stamp" -print 2>/dev/null \
    | while IFS= read -r d; do printf '%s\n' "${d#"$HARNESS_ROOT"/}"; done)"
  [ -n "$cands" ] || return 0
  # One batch call, and the only reading of .gitignore anywhere in here. Exit 1
  # just means nothing was ignored; anything above that is git failing, and a
  # Stop hook that cannot reach git must keep blocking rather than quietly
  # stop watching.
  out="$(printf '%s\n' "$cands" \
    | git -C "$HARNESS_ROOT" check-ignore --stdin --verbose --non-matching 2>/dev/null)"
  rc=$?
  if [ "$rc" -gt 1 ]; then
    kept="$cands"
  else
    kept="$(printf '%s\n' "$out" | awk -F'\t' '$1 == "::" && $2 != "" { print $2 }')"
  fi
  [ -n "$kept" ] || return 0
  printf '%s\n' "$kept" | classify_stdin | gated_stdin \
    | awk -F'\t' '{ print $2; exit }'
  return 0
}

# --- What the gates judge ---------------------------------------------------
#
# gated_stdin   Reads "<category>\t<path>" lines, as classify_stdin prints
# them, and keeps the ones some gate could actually read. This is the ONE
# definition of "the code the gates ran against": gate_tree_hash records it,
# check-boundaries.sh recomputes it, and the Stop hook asks whether it moved.
# Three readers of one predicate cannot disagree; three predicates would.
#
# Kept: source, test, config, and harness - the hooks, the scripts, the gate
# manifest, the CI workflow. Dropped: docs (the story file that records the
# hash cannot be part of it), vendor, ignored, harness runtime state, and
# harness MARKDOWN. That last one is deliberate. A command file, an agent
# spec, a skill and CLAUDE.md classify as harness because they live under
# .claude/, but they are prompts: no lint, no test and no build reads them.
# Counting them meant rewording /advance-story cost a full gate run while
# editing a wiki page one directory over cost nothing, and it meant a
# recorded gate hash went stale on a change the gates could not have judged.
gated_stdin() {
  awk -F'\t' '
    ($1 == "source" || $1 == "test" || $1 == "config" || $1 == "harness") \
      && !($1 == "harness" && $2 ~ /\.md$/) \
      && index($2, ".claude/state/") != 1 { print }'
}

# --- Gate tree hash ---------------------------------------------------------
#
# One id for "the code the gates ran against". gates.sh records it in the
# story's ## Gate results; check-boundaries.sh recomputes it and refuses a PR
# whose recorded gate run does not match the code being merged.
#
# Covers exactly what gated_stdin keeps. Blob ids are of LF-normalised
# content, so a Windows working tree and a Linux checkout of the same content
# agree.

# Reads "blob\tpath" lines; prints the hash.
_hash_blob_listing() {
  local listing
  listing="$(cat)"
  [ -n "$listing" ] || { printf 'unavailable'; return 1; }
  {
    printf '%s\n' "$listing" | awk -F'\t' '{ print "B\t" $1 "\t" $2 }'
    printf '%s\n' "$listing" | cut -f2- | classify_stdin | gated_stdin | awk -F'\t' '{ print "C\t" $2 }'
  } | awk -F'\t' '
      $1 == "B" { blob[$3] = $2; next }
      $1 == "C" { gated[$2] = 1 }
      END {
        for (p in blob) {
          if (!(p in gated)) continue
          print blob[p] "  " p
        }
      }' | LC_ALL=C sort | git hash-object --stdin
}

# gate_tree_hash   The working tree as it is right now, tracked or not.
gate_tree_hash() {
  local idx
  idx="$HARNESS_ROOT/.claude/state/.tree-index.$$"
  mkdir -p "$HARNESS_ROOT/.claude/state"; rm -f "$idx"
  # Start from HEAD's index, not an empty one. Into an empty index every file
  # is new, so git applies CRLF normalisation the real commit never had, and
  # the hash recorded here disagrees with the one CI recomputes from the PR
  # head on any CRLF file committed before .gitattributes pinned LF. Then no
  # amount of re-running the gates can make them match. Seeded with HEAD,
  # `add -A` treats those files exactly as a real commit would.
  ( cd "$HARNESS_ROOT" \
      && { GIT_INDEX_FILE="$idx" git read-tree HEAD >/dev/null 2>&1 || :; } \
      && GIT_INDEX_FILE="$idx" git add -A . >/dev/null 2>&1 \
      && GIT_INDEX_FILE="$idx" git ls-files -s ) \
    | awk -F'\t' '{ split($1, a, " "); print a[2] "\t" $2 }' \
    | _hash_blob_listing
  local rc=$?
  rm -f "$idx"
  return $rc
}

# gate_tree_hash_of <commit>   The same hash for a committed tree - what CI
# uses, where the checkout may be a merge commit rather than the PR head.
gate_tree_hash_of() {
  git -C "$HARNESS_ROOT" ls-tree -r "$1" 2>/dev/null \
    | awk -F'\t' '{ split($1, a, " "); if (a[2] == "blob") print a[3] "\t" $2 }' \
    | _hash_blob_listing
}

# --- Story frontmatter ------------------------------------------------------
#
# One reader, used by phase.sh, gates.sh and check-boundaries.sh. Three
# implementations of "read a key out of the frontmatter" is how the three come
# to disagree about what a story says.

# frontmatter_value <file> <key>   The scalar value, trailing comment stripped.
frontmatter_value() {
  awk -v k="$2" '
    NR == 1 && $0 ~ /^---/ { inf = 1; next }
    inf && /^---/ { exit }
    inf {
      if (index($0, k ":") == 1) {
        sub(/^[^:]*:[[:space:]]*/, ""); sub(/[[:space:]]*#.*/, ""); print; exit
      }
    }
  ' "$1"
}

# frontmatter_list <file> <key>   The values, one per line. Accepts both the
# inline form the story template writes (`[A-1, A-2]`) and a YAML block list.
frontmatter_list() {
  awk -v k="$2" '
    NR == 1 && /^---/ { inf = 1; next }
    inf && /^---/ { exit }
    inf && index($0, k ":") == 1 {
      inlist = 1; v = $0
      sub(/^[^:]*:[[:space:]]*/, "", v); sub(/#.*/, "", v)
      gsub(/[][,]/, " ", v); acc = acc " " v; next
    }
    inlist && /^[[:space:]]*-[[:space:]]*/ {
      v = $0; sub(/^[[:space:]]*-[[:space:]]*/, "", v); sub(/#.*/, "", v)
      acc = acc " " v; next
    }
    inlist { inlist = 0 }
    END {
      n = split(acc, a, /[ \t]+/)
      for (i = 1; i <= n; i++) if (a[i] != "") print a[i]
    }
  ' "$1"
}

# --- Story state ------------------------------------------------------------

# load_state   sets STORY_ID, STORY_SLUG, PHASE, STORY_TYPE, BRANCH.
# PHASE is IDLE when no story is active.
load_state() {
  STORY_ID=""; STORY_SLUG=""; PHASE="IDLE"; STORY_TYPE=""; BRANCH=""
  [ -f "$STATE_FILE" ] || return 0
  local line k v
  while IFS= read -r line; do
    line="${line%%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    k="${line%%=*}"; v="${line#*=}"
    v="${v%\"}"; v="${v#\"}"
    case "$k" in
      STORY_ID)   STORY_ID="$v" ;;
      STORY_SLUG) STORY_SLUG="$v" ;;
      PHASE)      PHASE="$v" ;;
      STORY_TYPE) STORY_TYPE="$v" ;;
      BRANCH)     BRANCH="$v" ;;
    esac
  done < "$STATE_FILE"
  [ -z "$PHASE" ] && PHASE="IDLE"
  return 0
}

# phase_allows <category>   exit 0 if the current PHASE may write <category>
phase_allows() {
  local want="$1" line ph cats
  [ "$want" = "outside" ] && return 0
  while IFS= read -r line; do
    line="${line%%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    ph="$(printf '%s' "${line%%|*}" | tr -d '[:space:]')"
    [ "$ph" = "$PHASE" ] || continue
    cats="${line#*|}"; cats="${cats%%|*}"
    cats="$(printf '%s' "$cats" | tr -d '[:space:]')"
    case ",$cats," in *",$want,"*) return 0 ;; esac
    return 1
  done < "$HARNESS_DIR/phases.conf"
  # Unknown phase: don't block.
  return 0
}

# phase_categories   The categories the current phase may write - field 2 of
# its phases.conf row. inject-state.sh used to print phase_message under the
# label "Writes allowed this phase", which is the denial prose, not the list.
phase_categories() {
  awk -F'|' -v p="$PHASE" '
    /^[[:space:]]*(#|$)/ { next }
    { t = $1; gsub(/^[ \t]+|[ \t]+$/, "", t)
      if (t == p) { c = $2; gsub(/^[ \t]+|[ \t]+$/, "", c); print c; exit } }' \
    "$HARNESS_DIR/phases.conf"
}

phase_message() {
  local line ph msg
  while IFS= read -r line; do
    line="${line%%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    ph="$(printf '%s' "${line%%|*}" | tr -d '[:space:]')"
    [ "$ph" = "$PHASE" ] || continue
    msg="${line#*|}"; msg="${msg#*|}"
    printf '%s' "$(printf '%s' "$msg" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    return
  done < "$HARNESS_DIR/phases.conf"
}

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$(json_escape "$1")"
  exit 0
}

# json_escape <string>   Pure bash. Deliberately contains no backslash literals:
# the escape character is built with printf, which keeps this readable and
# immune to quoting accidents across shells and editors.
json_escape() {
  # awk, not `${s//\\/\\\\}`: doubling a backslash by parameter expansion is
  # not reliable across bash versions, and this used to emit the backslash
  # unchanged - so a deny reason quoting a Windows path was not JSON.
  printf '%s' "$1" | tr -d '\r' | awk 'BEGIN { ORS = "" }
    { gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); gsub(/\t/, "\\t")
      if (NR > 1) printf "\\n"
      printf "%s", $0 }'
}
