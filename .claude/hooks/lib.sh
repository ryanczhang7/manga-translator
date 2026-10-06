#!/usr/bin/env bash
# Shared helpers for the harness hooks.
#
# Design rules:
#   * Zero dependencies beyond bash + coreutils (no jq, no python, no node).
#   * Fail OPEN. A bug in a hook must never wedge the session: on any internal
#     error we allow the action. Correctness is defended in depth by the gates
#     and by CI; the hook exists to catch the honest mistake, not the attacker.

# set_harness_root <dir>   Points every per-tree global at <dir>. The guard
# uses it to judge a write by the lock of another worktree and then to restore
# its own, so all four always move together.
#
# The root is kept in FORWARD SLASHES (HARNESS-035). The host spells
# CLAUDE_PROJECT_DIR with backslashes on Windows. Every comparison already
# slashed both sides, but a glob over the root reads a backslash as an escape,
# and on every platform but Windows a backslashed path is no path at all. Git
# Bash, git and every coreutil take `D:/x` for `D:\x`. Spelled inline, as
# _to_slashes is, because that function is defined further down this file.
set_harness_root() {
  HARNESS_ROOT=${1//\\//}
  HARNESS_DIR="$HARNESS_ROOT/.claude/harness"
  STATE_FILE="$HARNESS_ROOT/.claude/state/current-story.env"
  GATE_STAMP="$HARNESS_ROOT/.claude/state/last-gate-run"
}

# The tree whose lock, confs and state the hooks read. This is a DEFAULT: a hook
# input carrying `cwd` moves it to the harness tree the session is actually in,
# at the bottom of this file (HARNESS-035, see _session_root).
set_harness_root "${CLAUDE_PROJECT_DIR:-$PWD}"
# The session's working directory, slashed, from the hook input's `cwd`; empty
# when there is none (every script that sources this file outside a hook).
SESSION_CWD=""

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
          # `<<<` is a HERE-STRING. It opens nothing: the word after it is its
          # DATA, not a delimiter. This case must come first, because the
          # scanner would otherwise walk on to the SECOND `<`, where the
          # remaining text reads `<< WORD` - a perfect match for the heredoc
          # opener below - and take the word belonging to the here-string as a delimiter.
          # Every following line was then masked as heredoc body, waiting for a
          # line equal to it that never arrives.
          #
          # One-line commands were unharmed, since the false delimiter only
          # takes effect from the NEXT line, which is why this survived so long.
          # A MULTI-LINE command opened the lock: `grep x <<< "$d"` on one line
          # and `echo hi > src/main.ts` on the next left the guard with no write
          # target at all. phase-guard.test.sh pins both, plus a real heredoc.
          if (c == "<" && substr(s, j + 1, 1) == "<" && substr(s, j + 2, 1) == "<") {
            out = out "<<<"; j += 3; continue
          }
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

# masked_lines <file>   The file's text with every operator inside a quoted,
# escaped or heredoc span mapped to a control character - AND the newlines the
# masker folds away put back, so line N of the output is line N of the file.
#
# THE SECOND HALF IS NOT OPTIONAL AND IS NOT OBVIOUS. mask_shell_quotes joins a
# backslash-continued line, encoding the newline as \010 (its own operator set;
# unmask_shell_quotes maps \010 back to a newline). Measured on this tree:
# lib.test.sh is 405 lines and masks to 348 carrying 57 of them;
# check-boundaries.sh, 570 to 526 with 44. masked + \010 == the original exactly,
# so nothing is lost - but every line number after the first continuation is
# wrong by the running total. A guard that REPORTS line numbers and masks
# without this sends its reader to an innocent line, which is worse than saying
# nothing. check-sigpipe.sh did exactly that for one commit.
#
# The BACKSLASH goes back too, not just the newline, so a caller folding logical
# lines still sees the continuation marker.
#
# It lives here rather than in either guard because there are now two of them -
# check-sigpipe.sh and check-grep-count.sh - and rules.md is explicit about what
# happens to a rule that gets a private copy per caller.
#
# TWO TRAPS FOR CONSUMERS, both found by a consuming project reading masked text
# as if it were source. They are recorded here rather than in one guard because
# centralising this helper made its edge cases everybody's - which was the cost
# of the move, and is worth stating where the move is.
#
# 1. A BARE `#` IN THE OUTPUT IS NOT NECESSARILY A COMMENT. An escaped `\#` is
#    data, so the backslash is consumed and a bare `#` is emitted - with LIVE
#    CODE after it. A real comment is masked to the end of the line. Compare:
#
#      k() { echo a \# b | grep -m1 c; }   ->  k() { echo a # b | grep -m1 c; }
#      k() { echo a  # b | grep -m1 c; }   ->  k() { echo a #\006b\006\001\006grep...
#
#    TELL THEM APART BY THE TAIL, NOT BY THE `#`. A rule that strips from the
#    first `#` unconditionally deletes real code in the first case. fantasy-
#    world-builder's WORLD-090 hit this building a brace-recognition rule and
#    resolved it by reading the comment boundary off this output and falling
#    back to the raw line - in that order, because a comment ending in a brace
#    (`# see {braces}`) defeats raw-first.
#
# 2. `"$( ... )"` IS BLANKED WHOLESALE; A BARE `$( ... )` IS NOT.
#
#      x="$(grep -c p f || printf 0)"  ->  x="$(grep\006-c\006p\006f\006\001\001...
#      y=$(grep -c p f || printf 0)    ->  unchanged
#
#    Deliberate: for the phase lock the text inside a quoted substitution is
#    data to the command outside it, and a redirect hidden in there should fail
#    open. For a guard reading SOURCE it is code that runs, and the difference
#    is invisible unless you look for it - check-grep-count.sh missed the
#    commonest spelling of its own defect this way and unwraps those quotes
#    before masking. The worked example is contract block C-11 of that project's
#    refresh story.
#
#    THE DISCRIMINATOR IS THE QUOTING, NOT THE SUBSTITUTION - the sentence the
#    next consumer wants. A rule tested only against the bare spelling passes
#    its own suite and ships broken, because the shape it fails on is the one
#    nobody wrote a fixture for. check-grep-count.sh did precisely that: its
#    probe corpus was `y=$(...)` throughout, every assertion was green, and the
#    guard could not see `x="$(...)"` - which is how the real tree spells it.
#
masked_lines() {
  # A FILE ARGUMENT OR STDIN. check-grep-count.sh pre-processes the text
  # before masking, so it needs the stream form.
  if [ "$#" -gt 0 ]; then mask_shell_quotes < "$1" 2>/dev/null
  else mask_shell_quotes 2>/dev/null
  fi \
    | awk '
    BEGIN { BS = sprintf("%c", 92); H = sprintf("%c", 8) }
    { n = split($0, p, H); out = p[1]
      for (i = 2; i <= n; i++) out = out BS "\n" p[i]
      print out }'
}

# harness_shell_files [pathspec...]   Every harness *.sh that classify.sh lists,
# one per line, optionally narrowed to a pathspec.
#
# THROUGH classify.sh, not a private tree walk - rules.md, "a test that needs
# this answer asks for it". classify enumerates through git, so a file written
# five minutes ago and never committed is still returned and build output is
# not. Note `.claude/tests/**` classifies as HARNESS, not test: a guard written
# against the `test` category scans zero files and passes forever.
harness_shell_files() {
  bash "$CLAUDE_PROJECT_DIR/scripts/classify.sh" --list harness "$@" 2>/dev/null \
    | awk '/\.sh$/ { print }'
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
    | sed -E -e 's/^[^A-Za-z_]+//' -e 's/["'"'"']//g' \
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
    | awk '{ f = $NF; gsub(/["'"'"']/, "", f); print f }'
}

# --- Write targets ----------------------------------------------------------

# _WC_AWK   The operand half of write_candidates, as one awk program.
#
# It reads REDIRECT-STRIPPED masked command text, one shell line per record,
# and prints a verdict line followed by one line per candidate. See
# write_candidates below for the contract; this is the part that understands
# the tools.
#
# THE TOKENIZER IS THE REASON THIS IS NOT FIVE greps. Every rule the inline
# pipeline it replaces used took `awk '{print $NF}'` off a `grep -oE` match, and
# three families of defect follow from that shape alone: the last word of a
# match is not an operand (`sed -i EXPR frozen.ts permitted.md` judged only the
# second file), a character class that stops at `(` returns a FRAGMENT of a sed
# script as a path, and an option's ARGUMENT is indistinguishable from an
# operand. So: split each line into words - masking already turned every space
# inside a quoted span into a control character, so a quoted path is ONE word -
# split each word at the shell operators that are still operators, which is
# decidable here because the quote characters themselves survive masking, and
# hand each command its own operand list.
_WC_AWK='
    function isname(w) {
      return (w == "sed" || w == "tee" || w == "cp" || w == "mv" || w == "rm" || w == "touch")
    }
    function out(s)      { BUF = BUF s "\n" }
    function emit(t)     { if (t != "") out(t) }
    function emitr(t, r) { if (t != "") out(t "\t" r) }

    # optarg(word, letters)   Does this single-dash cluster take an argument?
    # Returns 1 when the argument is GLUED to it (-tsrc/, -ftsrc/), 2 when it
    # is the next word (-t src/, -ft src/), 0 when no letter of <letters>
    # appears. A parser that merely SKIPS a `-` word whole leaves
    # `mv -tsrc/ docs/notes.md` an entirely unjudged write into frozen source,
    # and one that always skips the NEXT word reports a timestamp as a path.
    function optarg(w, set,   c, k, ch) {
      c = substr(w, 2)
      for (k = 1; k <= length(c); k++) {
        ch = substr(c, k, 1)
        if (index(set, ch) > 0) { GLUED = substr(c, k + 1); return (GLUED == "") ? 2 : 1 }
      }
      return 0
    }
    function islong(w)  { return (substr(w, 1, 2) == "--" && length(w) > 2) }
    function isshort(w) { return (substr(w, 1, 1) == "-" && length(w) > 1) }
    # The long option name, minus any =VALUE. LONGVAL carries the value and
    # LONGHAS says whether there was one.
    function longname(w,   o) {
      o = w; LONGVAL = ""; LONGHAS = 0
      if (index(w, "=") > 0) { LONGVAL = w; sub(/^[^=]*=/, "", LONGVAL); LONGHAS = 1; sub(/=.*$/, "", o) }
      sub(/^--/, "", o)
      return o
    }

    # sed. In-place is decided PER WORD, which is the sharper of the two
    # parsers this reconciles: a single-dash word writes in place when the run
    # of letters after its `-` includes an i (-i, -i.bak, -ni, -Ei, -rin), and
    # the long option is a PREFIX test of in-place, never a literal match - GNU
    # getopt_long honours any unambiguous abbreviation, so `sed --i` and
    # `sed --in-pl` genuinely write. A substring test for -i refused a pure read
    # of tests/guards/layer-imports.test.ts on the file it was READING and
    # missed -ni entirely: the same bug from two ends. Then EVERY file operand
    # is a target rather than the last word, and the FIRST positional is the
    # script unless -e or -f supplied one.
    function do_sed(a, b,   k, w, o, c, letters, inplace, scripted, np, p, start, r) {
      inplace = 0; scripted = 0; np = 0; split("", SP)
      k = a
      while (k <= b) {
        w = tok[k]
        if (islong(w)) {
          o = longname(w)
          if (index("in-place", o) == 1) inplace = 1
          if (index("expression", o) == 1 || index("file", o) == 1) {
            scripted = 1
            if (!LONGHAS) k++
          }
          k++; continue
        }
        if (isshort(w)) {
          c = substr(w, 2)
          if (match(c, /^[A-Za-z]+/)) letters = substr(c, 1, RLENGTH); else letters = ""
          if (letters ~ /i/) inplace = 1
          r = optarg(w, "ef")
          if (r > 0) { scripted = 1; if (r == 2) k++ }
          else if (optarg(w, "l") == 2) k++
          k++; continue
        }
        np++; SP[np] = w
        k++
      }
      if (!inplace) return
      WRITE = 1
      start = scripted ? 1 : 2
      for (p = start; p <= np; p++) emit(SP[p])
    }

    # mv REMOVES its source, so every operand is judged and each carries the
    # part it played - and -t/--target-directory INVERTS which one is the
    # destination, in all six spellings, three of which glue or attach the
    # argument.
    function do_mv(a, b,   k, w, o, tdir, np, p, r) {
      tdir = ""; np = 0; split("", MP)
      k = a
      while (k <= b) {
        w = tok[k]
        if (islong(w)) {
          o = longname(w)
          if (index("target-directory", o) == 1) {
            if (LONGHAS) tdir = LONGVAL
            else { k++; if (k <= b) tdir = tok[k] }
          }
          k++; continue
        }
        if (isshort(w)) {
          r = optarg(w, "t")
          if (r == 1) tdir = GLUED
          else if (r == 2) { k++; if (k <= b) tdir = tok[k] }
          k++; continue
        }
        np++; MP[np] = w; k++
      }
      if (tdir != "") {
        emitr(tdir, "destination of mv")
        for (p = 1; p <= np; p++) emitr(MP[p], "source of mv (removed by the move)")
        return
      }
      for (p = 1; p < np; p++) emitr(MP[p], "source of mv (removed by the move)")
      if (np > 0) emitr(MP[np], "destination of mv")
    }

    # cp READS its sources and leaves them where they are, so only the
    # destination is a write target: judging every operand would be a false
    # positive, not a fix. Its own -t is deliberately NOT read - it is one of
    # C-1s three BOTH WRONG rows, this is a reconciliation, and C-3/PO-5 make a
    # new shape a finding rather than a criterion. lib.test.sh pins the wrong
    # answer it gives today, so closing it takes a story.
    function do_cp(a, b,   k, w, np) {
      np = 0; split("", CP)
      for (k = a; k <= b; k++) {
        w = tok[k]
        if (isshort(w)) continue
        np++; CP[np] = w
      }
      if (np > 0) emitr(CP[np], "destination of cp")
    }

    # touch. Every operand is a target, but -t/-d/-r and their long forms take
    # an ARGUMENT: a timestamp is not a path, and the -r reference file is only
    # READ. A wrong denial naming a real file it never writes is the most
    # convincing kind, because the message looks right.
    function do_touch(a, b,   k, w, o) {
      k = a
      while (k <= b) {
        w = tok[k]
        if (islong(w)) {
          o = longname(w)
          if (!LONGHAS && (index("date", o) == 1 || index("reference", o) == 1 || index("time", o) == 1)) k++
          k++; continue
        }
        if (isshort(w)) { if (optarg(w, "tdr") == 2) k++; k++; continue }
        emit(w); k++
      }
    }

    # rm and tee take every remaining operand, with no role: there is nothing
    # ambiguous about them, and inventing a role for one is the churn AC-5s own
    # control forbids.
    function do_plain(a, b,   k, w) {
      for (k = a; k <= b; k++) { w = tok[k]; if (isshort(w)) continue; emit(w) }
    }

    function dispatch(name, a, b) {
      if (name == "sed") { do_sed(a, b); return }
      WRITE = 1
      if (name == "tee" || name == "rm") { do_plain(a, b); return }
      if (name == "touch") { do_touch(a, b); return }
      if (name == "cp")    { do_cp(a, b);    return }
      if (name == "mv")    { do_mv(a, b);    return }
    }

    # One word into tokens. A quoted span is DATA: the masker has already
    # rewritten the operators inside it, but it leaves the quote characters
    # themselves, so a `(` that survives into a sed script is still recognisable
    # as data here. Everything else splits at the operator.
    function tokenize(w,   q, cur, k, c) {
      q = ""; cur = ""
      for (k = 1; k <= length(w); k++) {
        c = substr(w, k, 1)
        if (q != "") { cur = cur c; if (c == q) q = ""; continue }
        if (c == SQ || c == DQ) { q = c; cur = cur c; continue }
        if (index(SEPS, c) > 0) {
          if (cur != "") { ntok++; tok[ntok] = cur; sep[ntok] = 0; cur = "" }
          ntok++; tok[ntok] = c; sep[ntok] = 1
          continue
        }
        cur = cur c
      }
      if (cur != "") { ntok++; tok[ntok] = cur; sep[ntok] = 0 }
    }

    BEGIN { SQ = sprintf("%c", 39); DQ = sprintf("%c", 34); SEPS = "|&;()<"; WRITE = 0; BUF = "" }
    {
      # A newline IS a command separator: the masker encodes the ones folded
      # into a continued line as \010, so every record boundary here is real.
      ntok = 0
      for (i = 1; i <= NF; i++) tokenize($i)
      i = 1
      while (i <= ntok) {
        while (i <= ntok && sep[i]) i++
        s = i
        while (i <= ntok && !sep[i]) i++
        e = i - 1
        for (j = s; j <= e; j++) if (isname(tok[j])) { dispatch(tok[j], j + 1, e); break }
      }
    }
    END { gsub(SQ, "", BUF); gsub(DQ, "", BUF)
          print (WRITE ? "W" : "-"); printf "%s", BUF }'

# write_candidates <masked command>   Which paths this command would WRITE.
#
# THE phase lock's decision procedure, and the one place it lives - the rule
# rules.md already states for classify.sh: a caller that needs this answer asks
# for it rather than carrying a second copy of the rules. Input is
# mask_shell_quotes output, so a quoted span has already become data. Nothing
# here consults the filesystem: a file being created does not exist yet.
#
# Output, on stdout:
#
#     <verdict>              `W` or `-`, ALWAYS present, always the first line
#     <target>[\t<role>]     zero or more, in no particular order
#
# THE VERDICT answers a question an empty candidate list cannot: `W` says the
# command was a WRITE - an in-place sed, or tee/cp/mv/rm/touch named at a real
# token boundary - so a caller can tell "this was never a write" from "this was
# a write and no target could be parsed out of it". While those two were
# indistinguishable a bypass was invisible, because the record was empty either
# way. A redirect operator ALONE does not set it: `cmd > /dev/null` is
# ubiquitous, and tracing it would drown the record that distinction exists to
# make readable.
#
# THE ROLE is the operand's part - `destination of mv`, `source of mv (removed
# by the move)`, `destination of cp` - so a denial can say WHICH operand it
# refused rather than naming a path with no account of why. A tool whose operand
# has no ambiguous part carries none.
#
# THE TARGET COMES FIRST on every line, before the tab, because every caller
# filters and anchors on the path.
write_candidates() { # <masked command>
  local masked="$1" noredir
  # Strip redirect clauses ONCE, so every rule after the first reads text with
  # no `>` in it. Enumerating the shapes a redirect can be glued to is how one
  # false positive survived nine of them: `cp a b 2>/dev/null` was refused on
  # `2>/dev/null` and `rm a 2>/dev/null` on `2`, a different token, because that
  # rule's character class truncated at the `>`. A quoted `>` is already a
  # control character by now, so only real operators match.
  noredir="$(printf '%s' "$masked" | sed -E 's/[0-9]*>>?[[:space:]]*[^|&;()[:space:]]*//g')"
  {
    printf '%s\n' "$noredir" | awk "$_WC_AWK"
    # A redirect is the FIRST rule's business and no other rule's. `>|` is a
    # redirect too.
    printf '%s\n' "$masked" | grep -oE '>(>|\|)?[[:space:]]*[^|&;><()[:space:]]+' \
      | sed -E -e 's/^>(>|\|)?[[:space:]]*//' -e 's/["'"'"']//g'
  } 2>/dev/null
  # Both quote characters are stripped from every line both branches print -
  # the awk in _WC_AWK's END, the sed by its second expression - rather than by
  # a `tr -d` over the group: one process fewer per guard call (HARNESS-025).
  return 0
}

# --- Paths ------------------------------------------------------------------

# lower <text>   Lower-cased with tr, not with the bash 4 case-conversion
# expansion: macOS ships bash 3.2, where that expansion is a "bad
# substitution" that kills to_rel - after which check_path sees an empty path
# and allows the write. The lock silently off on every stock Mac. The selftest
# greps the shipped scripts for it.
lower() { printf '%s' "$1" | tr 'A-Z' 'a-z'; }

# _to_slashes <text>   Sets __lib_fs to <text> with every backslash turned into
# a forward slash and any trailing newlines dropped - exactly what
# `$(printf '%s' "$1" | tr '\134' '/')` produced, without spawning tr
# (manga-translator MT-041; upstream HARNESS-025). The pattern is spelled
# unquoted in an assignment, where `\\` is one literal backslash on every bash
# from 2.x on; no quoting rule of any version is in play. A variable, not a
# `$( )`, because the subshell is the cost being cut.
#
# One platform difference, measured in HARNESS-025's RED: on MSYS/Cygwin bash
# `$( )` also deletes every carriage return, mid-line included, so the old form
# dropped a `\r` inside a path there and nowhere else. This keeps it, as Linux
# and macOS always did. A path with an embedded CR is not a real input.
_to_slashes() {
  __lib_fs=${1//\\//}
  while [[ "$__lib_fs" == *$'\n' ]]; do __lib_fs=${__lib_fs%$'\n'}; done
}

# _drive_form <path>   Sets __lib_fs to _to_slashes' result with an MSYS or
# Cygwin drive prefix (`/d/...`, `/cygdrive/d/...`) rewritten as `d:/...`, so
# that the spellings of one Windows directory compare equal. Case is left
# alone: callers lower-case both sides themselves. Length-preserving for the
# `/d/` form, which is what lets to_rel cut the suffix by the root's length.
_drive_form() {
  _to_slashes "$1"
  case "$__lib_fs" in
    /cygdrive/[A-Za-z]|/cygdrive/[A-Za-z]/*) __lib_fs="${__lib_fs:10:1}:/${__lib_fs:12}" ;;
    /[A-Za-z]|/[A-Za-z]/*) __lib_fs="${__lib_fs:1:1}:/${__lib_fs:3}" ;;
  esac
}

# abs_norm <absolute path>   Sets __lib_abs to the path slashed, with `.` and
# `..` collapsed and no trailing slash. `..` never climbs above the `/` or `X:/`
# it starts from. Returns 1 for a relative path.
abs_norm() {
  local p pre seg out="" oldIFS
  _to_slashes "$1"; p=$__lib_fs
  case "$p" in
    [A-Za-z]:/*) pre="${p:0:3}"; p="${p:3}" ;;
    /*)          pre="/";        p="${p:1}" ;;
    *) return 1 ;;
  esac
  oldIFS="$IFS"; IFS='/'
  # shellcheck disable=SC2086
  set -- $p
  IFS="$oldIFS"
  for seg in "$@"; do
    case "$seg" in
      ''|.) continue ;;
      ..) case "$out" in */*) out="${out%/*}" ;; *) out="" ;; esac ;;
      *) out="${out:+$out/}$seg" ;;
    esac
  done
  __lib_abs="$pre$out"
  return 0
}

# --- Worktrees (HARNESS-035) ------------------------------------------------
#
# "One worktree, one story, one lock" (CLAUDE.md) held only while a session
# never left the tree it started in. The host runs these hooks with
# CLAUDE_PROJECT_DIR fixed at the FIRST tree, so a session the desktop app moved
# into a linked worktree read the main checkout's story on every hook, and an
# absolute path into the worktree was "outside" and never judged
# (fantasy-world-builder WORLD-113, D-7). Three rules now, all pure bash - no
# process, and no `git rev-parse`, which would cost one per judged path:
#
#   * the session's tree is the harness tree holding the hook input's `cwd`;
#   * a write is judged by the lock of the worktree that OWNS it, when that is
#     another worktree of the same repository;
#   * anything else outside the root is still outside, as it always was.

# worktree_top <absolute path>   Sets __lib_wt to the nearest of the path and
# its ancestors that holds `.git` (a directory in a main checkout, a file in a
# linked worktree), slashed. Returns 1, with __lib_wt empty, when there is none.
# The path itself need not exist: a file about to be created has a parent that
# does.
worktree_top() {
  local d
  __lib_wt=""
  _to_slashes "$1"; d="${__lib_fs%/}"
  while [ -n "$d" ]; do
    if [ -e "$d/.git" ]; then __lib_wt="$d"; return 0; fi
    case "$d" in */*) d="${d%/*}" ;; *) return 1 ;; esac
  done
  return 1
}

# git_common_dir <tree>   Sets __lib_gcd to the tree's common git directory:
# `<tree>/.git` when that is a directory, else the `gitdir:` its `.git` file
# names, followed through that directory's `commondir`. Returns 1 when the tree
# has no readable `.git`. Read with `read`, as git writes it, never with git.
# The tree is slashed FIRST: the host spells CLAUDE_PROJECT_DIR with
# backslashes on Windows, and the result is globbed by any_active_worktree,
# where a backslash is an escape - `D:\proj/.git/worktrees/*` matched nothing,
# and an IDLE root waved through every write into its worktrees.
git_common_dir() {
  local t line="" g c=""
  _to_slashes "${1%/}"; t="${__lib_fs%/}"
  __lib_gcd=""
  if [ -d "$t/.git" ]; then __lib_gcd="$t/.git"; return 0; fi
  [ -f "$t/.git" ] || return 1
  IFS= read -r line < "$t/.git" || [ -n "$line" ] || return 1
  line="${line%$'\r'}"
  g="${line#gitdir: }"
  [ "$g" != "$line" ] && [ -n "$g" ] || return 1
  _to_slashes "$g"; g=$__lib_fs
  path_is_absolute "$g" || g="$t/$g"
  if [ -f "$g/commondir" ]; then
    IFS= read -r c < "$g/commondir" || [ -n "$c" ]
    c="${c%$'\r'}"
    if [ -n "$c" ]; then
      _to_slashes "$c"; c=$__lib_fs
      path_is_absolute "$c" || c="$g/$c"
      g="$c"
    fi
  fi
  abs_norm "$g" || return 1
  __lib_gcd=$__lib_abs
  return 0
}

# is_root <dir>   True when <dir> is HARNESS_ROOT. The string comparison is the
# ordinary path and costs nothing; `-ef` (same device and inode, a test builtin)
# catches every other spelling of the same directory - a drive letter, an MSYS
# mount, /tmp against the Windows temp path it maps to - without a process.
is_root() {
  local d="${1%/}"
  _to_slashes "${HARNESS_ROOT%/}"
  [ "$d" = "$__lib_fs" ] && return 0
  [ -n "$d" ] && [ "$d" -ef "$HARNESS_ROOT" ]
}

# same_repo <tree> <tree>   True when both are worktrees of one repository: their
# common git directories are the same directory. `-ef` again, because git
# writes Windows spellings into a linked worktree's `.git` file while a hook may
# know the same directory by its MSYS one.
same_repo() {
  local a
  git_common_dir "$1" || return 1; a=$__lib_gcd
  git_common_dir "$2" || return 1
  [ "$a" = "$__lib_gcd" ] || [ "$a" -ef "$__lib_gcd" ]
}

# any_active_worktree   True when some OTHER worktree of the root's repository
# has a story active - a `current-story.env` - so that a root which is itself
# IDLE still has writes to judge. Reads `<common>/worktrees/*/gitdir` and the
# main checkout; a stale entry whose tree is gone has no state file and counts
# for nothing.
any_active_worktree() {
  local common g wt line
  git_common_dir "$HARNESS_ROOT" || return 1
  common=$__lib_gcd
  case "$common" in
    */.git)
      wt="${common%/.git}"
      if ! is_root "$wt" && [ -f "$wt/.claude/state/current-story.env" ]; then return 0; fi ;;
  esac
  for g in "$common"/worktrees/*/gitdir; do
    [ -f "$g" ] || continue
    line=""
    IFS= read -r line < "$g" || [ -n "$line" ] || continue
    line="${line%$'\r'}"
    _to_slashes "$line"; wt="${__lib_fs%/.git}"
    is_root "$wt" && continue
    [ -f "$wt/.claude/state/current-story.env" ] && return 0
  done
  return 1
}

# to_rel <path>   Repo-relative, forward slashes. Empty output means "outside
# this repository", and therefore not the harness's business.
#
# Drive spellings are one root: `/d/p`, `/cygdrive/d/p`, `D:/p` and `D:\p` all
# name the same directory (_drive_form). This used to be approximated by asking
# whether the path contained `/<root's folder name>/`, which judged an unrelated
# `C:/elsewhere/<same name>/src` as this repository and missed a linked worktree
# named anything else - every absolute write into `D:/fwb-WORLD-113` from a
# session rooted at `D:/fantasy-world-builder` went unjudged (HARNESS-035).
to_rel() {
  local p root lp lr
  _drive_form "$1"; p=$__lib_fs
  _drive_form "$HARNESS_ROOT"; root="${__lib_fs%/}"
  lp="$(lower "$p")"
  lr="$(lower "$root")"

  if [[ "$lp" == "$lr"/* ]]; then
    printf '%s' "${p:${#root}+1}"
    return
  fi

  # Absolute path elsewhere on disk (scratchpad, /tmp, another checkout).
  if [[ "$p" == /* || "$p" == ?:/* ]]; then
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
# A SPACE RULE HERE WOULD BE DEAD CODE, and the field report proposes one - so
# the measurement is written down rather than left to be redone. The report's
# last open item asks for "a candidate containing spaces is a leaked parse", and
# warns that it would break the live assertion that
# `echo x > "src/my file.ts"` blocks on that path.
#
# Neither half holds. This runs while the candidate is STILL MASKED, and masking
# replaces the spaces inside a quoted or escaped span, so a quoted path arrives
# as ONE token with no real space in it. Every extractor takes a single `awk`
# field, which cannot contain one either. Ten shapes were tried - quoted and
# escaped, through the redirect, rm, touch, tee, cp and mv extractors - and none
# produced a candidate carrying a real space. The rule would not break the
# assertion; it would never fire.
#
# What is left of that item is a limit rather than a defect: `sed -i option`
# yields the candidate `option`, and `option` is a perfectly plausible relative
# path. Telling it from a real new file needs existence, and this guard
# deliberately does not check that - a file being created does not exist yet.
# phase-guard.test.sh pins the masking through every extractor, which is the
# property that whole conclusion rests on.
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
  _to_slashes "$1"
  case "$__lib_fs" in
    /*|?:/*) return 0 ;;
    *) return 1 ;;
  esac
}

# normalize_rel <relpath>   Collapse "." and ".." segments. Returns 1, printing
# nothing, when the path climbs above the repository root - which means it is
# not a repo path and not the lock's business.
normalize_rel() {
  local p seg out="" oldIFS
  _to_slashes "$1"; p=$__lib_fs
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
#
# HARNESS-035: <start>, when given, is the absolute directory the shell starts
# in - the session's `cwd` - rather than the root. And a directory OUTSIDE the
# root that the guard can name is no longer a dead end: it is printed as an
# absolute path, so `cd <linked worktree> && echo x > src/a.ts` reaches the
# guard as `<linked worktree>/src/a.ts` and is judged by that worktree's lock.
# Return 1 is kept for what it always meant: a directory nobody can name.
command_cwd() {
  local masked="$1" start="${2:-}" tgt cur="" out="" rel joined lp lr r
  # A bare `cd` goes home. Nothing after it is a repo path.
  printf '%s\n' "$masked" | grep -qE '(^|[|&;(])[[:space:]]*cd[[:space:]]*($|[|&;)])' && return 1
  _drive_form "${HARNESS_ROOT%/}"; lr="$(lower "$__lib_fs")"
  # The start directory. Spelled exactly as the root, or under it - the ordinary
  # case, since the root was found by walking up from it - this costs nothing;
  # any other spelling goes through the absolute branch below.
  if [ -n "$start" ]; then
    _to_slashes "${start%/}"; start=$__lib_fs
    _to_slashes "${HARNESS_ROOT%/}"; r=$__lib_fs
    if [ "$start" = "$r" ]; then
      start=""
    elif [[ "$start" == "$r"/* ]] && joined="$(normalize_rel "${start#"$r"/}")"; then
      cur="$joined"; start=""
    fi
  fi
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
      _drive_form "${tgt%/}"; lp="$(lower "$__lib_fs")"
      if [ "$lp" = "$lr" ]; then cur=""; continue; fi
      rel="$(to_rel "$tgt")"
      if [ -z "$rel" ]; then
        abs_norm "$tgt" || return 1
        cur="OUTSIDE"; out=$__lib_abs
      else cur="$rel"; fi
      continue
    fi
    if [ "$cur" = "OUTSIDE" ]; then
      abs_norm "$out/$tgt" || return 1
      out=$__lib_abs
      continue
    fi
    if joined="$(normalize_rel "${cur:+$cur/}$tgt")"; then
      cur="$joined"
    else
      # Climbed above the root: `cd ../sibling-worktree`. Still nameable.
      abs_norm "$HARNESS_ROOT/${cur:+$cur/}$tgt" || return 1
      cur="OUTSIDE"; out=$__lib_abs
    fi
  done <<< "$( [ -n "$start" ] && printf '%s\n' "$start"
    printf '%s\n' "$masked" \
    | grep -oE '(^|[|&;(]|[[:space:]])cd[[:space:]]+[^|&;><[:space:]]+' \
    | sed -E -e 's/.*[[:space:]]cd[[:space:]]+|^cd[[:space:]]+|.*[|&;(]cd[[:space:]]+//' \
             -e 's/["'"'"']//g')"
  if [ "$cur" = "OUTSIDE" ]; then printf '%s' "$out"; return 0; fi
  printf '%s' "$cur"
  return 0
}

# classify <relpath>   -> vendor | harness | docs | test | config | ignored | source
#
# One path. Delegates the rule matching to classify_stdin so that the rules
# have exactly one implementation, and so that a single call costs one process
# rather than one per rule in paths.conf - which, at ninety-odd rules, cost
# whole seconds per checked path on Windows and made the guard feel like a
# hang. The bare-path retry (`x/**` covers bare `x`) lives in classify_stdin,
# so the order is: rules on the bare form, rules on the slashed form, then
# .gitignore, then source.
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
#
# Both spellings go to ONE git process as argv (manga-translator MT-041;
# upstream HARNESS-025): exit 0 when at least one of them is ignored, 1 when
# neither, 128 on a fatal error, which is read as "not ignored" exactly as the
# two-call form read it. Argv rather than `--stdin`, because a path may contain
# a newline, and non-verbose output never reports a negated match, so there is
# no output to parse. NOT `-q`: git refuses `--quiet` with more than one path
# (exit 128), which would silently answer "not ignored" for everything - hence
# the redirect instead.
is_ignored() {
  [ -n "${1:-}" ] || return 1
  git -C "$HARNESS_ROOT" check-ignore -- "$1" "$1/" >/dev/null 2>&1
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
# THE BARE-PATH RETRY (manga-translator MT-034; upstream HARNESS-031). A
# directory rule is a glob ending in `/**`, which matches paths UNDER the
# directory and never the directory itself, so a bare `fixtures` under a
# project's `test | fixtures/**` fell through to `source`: deletable in GREEN,
# refused in RED. So a path that NO rule matches, and that does not already end
# in `/`, is judged once more with one trailing `/` appended, and takes the
# category of the first rule that matches that form. Three points:
#   - a matched FLAG decides the retry, never a `source` answer: a project may
#     write `source | gen`, and that explicit bare rule must beat `gen/**`;
#   - one output line per input line, with the path AS GIVEN (no `/` added):
#     every caller keys on the path it fed in;
#   - only a glob ending in `**` (or written ending in `/`) can match `x/`,
#     since `*` and `?` never cross a `/`, and each rule keeps its anchoring:
#     root-anchored `fixtures/**` covers `fixtures`, never `lib/fixtures`.
# Nothing consults the filesystem: bare `x` classifies the same whether or not
# the directory exists, and a FILE whose whole path equals such a prefix takes
# the directory rule's category too (paths.conf, "BOTH FORMS"). The retry runs
# inside this awk, so it costs no process, and it reaches every caller -
# classify(), the diff and tree listings, the gate hash - so they cannot
# disagree.
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
      lp = tolower(path); c = "source"; m = 0
      for (i = 1; i <= n; i++) if (lp ~ rr[i]) { c = rc[i]; m = 1; break }
      if (!m && substr(lp, length(lp), 1) != "/")
        for (i = 1; i <= n; i++) if ((lp "/") ~ rr[i]) { c = rc[i]; break }
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
# - see gated_stdin - never docs, vendor or ignored. For TRACKED files the
# question this asks is precisely "would the recorded gate hash still match".
# For UNTRACKED files it is not: gate_tree_hash leaves them out (HARNESS-014),
# but this walk still sees them, so editing an untracked gated file after a
# gate run asks for a re-run the stamp does not need. That false alarm errs on
# the safe side and is left as it is; making the two predicates agree again is
# its own story if anyone ever hits it.
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

# gate_tree_hash   The tree `git commit -a` would make right now: tracked files
# as they are in the working tree, plus whatever is staged (new files
# included), minus tracked deletions. UNTRACKED FILES CONTRIBUTE NOTHING,
# whatever they classify as - a commit contains none of them, so a hash that
# counted them could never match what CI recomputes from the commit
# (gate_tree_hash_of). A file the story created counts once it is `git add`-ed;
# gates.sh names the ones that are not (untracked_gated) and refuses to record
# while there are any.
#
# Computed in a temporary index seeded from a COPY of the real one (the
# worktree's own, via `git rev-parse --git-path index`), then `add -u`. The
# real index is never written. Seeding from the index rather than an empty one
# matters for CRLF: into an empty index every file is new, so git applies
# normalisation the real commit never had, and on any CRLF file committed
# before .gitattributes pinned LF the hash would disagree with CI's. With no
# real index at all (a fresh clone that never populated one), HEAD's tree is
# the seed instead.
gate_tree_hash() {
  local idx real
  idx="$HARNESS_ROOT/.claude/state/.tree-index.$$"
  mkdir -p "$HARNESS_ROOT/.claude/state"; rm -f "$idx"
  real="$(cd "$HARNESS_ROOT" && git rev-parse --git-path index 2>/dev/null)"
  case "$real" in ''|/*|[A-Za-z]:*) ;; *) real="$HARNESS_ROOT/$real" ;; esac
  ( cd "$HARNESS_ROOT" \
      && { { [ -n "$real" ] && [ -f "$real" ] && cp "$real" "$idx"; } \
           || { GIT_INDEX_FILE="$idx" git read-tree HEAD >/dev/null 2>&1 || :; }; } \
      && GIT_INDEX_FILE="$idx" git add -u . >/dev/null 2>&1 \
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

# untracked_gated   Every untracked, non-ignored file some gate could read -
# the files gate_tree_hash leaves out and a commit would not contain.
# Repo-relative, LC_ALL=C sorted, one per line; nothing when there are none.
# Returns 0 either way. --exclude-standard is what makes .gitignore AND
# .git/info/exclude count. This is the ONE definition: gates.sh calls it.
untracked_gated() {
  git -C "$HARNESS_ROOT" ls-files --others --exclude-standard 2>/dev/null \
    | classify_stdin | gated_stdin | cut -f2- | LC_ALL=C sort
  return 0
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
  # An empty PHASE means one of two different things, and collapsing them to
  # IDLE turned the second into "no lock". With no STORY_ID either, the file
  # declares no story and IDLE is right. With a STORY_ID, a story IS active and
  # only its phase is missing - a truncated write, a hand-edit, a stale copy -
  # and that is a corrupt state rather than an idle one. It gets a name that
  # matches no row in phases.conf, so phase_allows refuses it and the denial
  # says what it could not read.
  if [ -z "$PHASE" ]; then
    if [ -n "$STORY_ID" ]; then PHASE="<unset>"; else PHASE="IDLE"; fi
  fi
  return 0
}

# phase_allows <category>   exit 0 if the current PHASE may write <category>
phase_allows() {
  local want="$1" line ph cats
  [ "$want" = "outside" ] && return 0
  while IFS= read -r line; do
    line="${line%%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    # Whitespace deleted by pattern substitution (bash 2+), not `tr -d`: no
    # process per phases.conf row (HARNESS-025).
    ph=${line%%|*}; ph=${ph//[[:space:]]/}
    [ "$ph" = "$PHASE" ] || continue
    cats="${line#*|}"; cats="${cats%%|*}"
    cats=${cats//[[:space:]]/}
    case ",$cats," in *",$want,"*) return 0 ;; esac
    return 1
  done < "$HARNESS_DIR/phases.conf"
  # A phase this table does not list. REFUSE, rather than the `return 0` that
  # stood here: a lock whose failure mode is opening is not a lock, and the
  # condition that reaches this line is a state file carrying something no
  # phase.sh would write - a typo, a truncated write, a stale copy restored by
  # hand. Measured before the change: PHASE=RED refused a source write while
  # GREE, ZZZ, GREEN. and empty all allowed it, so `phase.sh set`'s validation
  # was the only thing between a mistyped phase and a silently disabled lock.
  # `GREEN.` is not hypothetical - it is the production defect the comment above
  # valid_phase records.
  #
  # NOT the same as "no active story", which still means no lock: the guard
  # exits on PHASE=IDLE before it ever calls this, and IDLE is a row in
  # phases.conf. An unrecognised phase is not an absent one.
  return 1
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
    ph=${line%%|*}; ph=${ph//[[:space:]]/}
    [ "$ph" = "$PHASE" ] || continue
    msg="${line#*|}"; msg="${msg#*|}"
    # Trimmed in-process (bash 2+ expansions, no sed): leading, then trailing.
    msg="${msg#"${msg%%[![:space:]]*}"}"
    msg="${msg%"${msg##*[![:space:]]}"}"
    printf '%s' "$msg"
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
  # Carriage returns are deleted by parameter expansion rather than a `tr -d`
  # stage in front of the awk: one process fewer on every denial (HARNESS-025).
  # It has to happen BEFORE awk splits records, not as a gsub inside it: a
  # value ending in a lone `\r` after its last newline is a second record to
  # Linux awk (one extra `\n` in the JSON), while MSYS awk drops it - so the
  # in-awk form passed every local run and failed only on CI.
  printf '%s' "${1//$'\r'/}" | awk 'BEGIN { ORS = "" }
    { gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); gsub(/\t/, "\\t")
      if (NR > 1) printf "\\n"
      printf "%s", $0 }'
}

# --- Which tree this session is in (HARNESS-035) ----------------------------

# _session_root   When the hook input carries `cwd`, sets SESSION_CWD to it and
# moves HARNESS_ROOT to the harness tree that holds it - the tree the session is
# standing in, which is not CLAUDE_PROJECT_DIR once the session has moved. The
# host fixes that variable when the session starts; `cwd` it keeps current.
#
# Read by parameter expansion, not json_get_string: that is an awk process on
# every hook call, and HARNESS-025's bound has no room for one. Not by a bash
# regex either: what a backslash inside a bracket expression means differs
# between regex libraries, and an escaped Windows path - the field's only
# shape - is all backslashes. The value ends at the first `"`: no Windows path,
# and no sane POSIX one, contains one. A JSON string's `\\` and `\/` both
# become `/` once backslashes are slashes and doubled slashes collapse, which is
# all a path needs. A `cwd` outside every harness tree - a scratch directory -
# leaves the root where it was; SESSION_CWD is still set, so a relative write
# there resolves against the scratch directory and not against the root.
_session_root() {
  local v
  case "${HOOK_INPUT:-}" in *'"cwd"'*) ;; *) return 0 ;; esac
  v="${HOOK_INPUT#*\"cwd\"}"
  v="${v#"${v%%[![:space:]]*}"}"
  [ "${v:0:1}" = ":" ] || return 0
  v="${v:1}"; v="${v#"${v%%[![:space:]]*}"}"
  [ "${v:0:1}" = '"' ] || return 0
  v="${v:1}"; v="${v%%\"*}"
  _to_slashes "$v"; v=$__lib_fs
  while [[ "$v" == *//* ]]; do v="${v%%//*}/${v#*//}"; done
  path_is_absolute "$v" || return 0
  SESSION_CWD="${v%/}"
  worktree_top "$SESSION_CWD" || return 0
  [ -f "$__lib_wt/.claude/harness/phases.conf" ] || return 0
  set_harness_root "$__lib_wt"
}
_session_root
