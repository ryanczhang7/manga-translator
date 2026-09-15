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

# --- Write targets in a command string ---------------------------------------
#
# write_candidates <masked-command>   One write target per line, preceded by a
# single verdict line: `W` when the command names a write-capable command at a
# REAL token boundary, `-` when it does not. (The verdict is what tells "the
# extractors found nothing to judge" from "there was nothing to find" - see
# phase-guard.sh and MT-031 AC-8.)
#
# A candidate line is the bare target, OR the target, a TAB, and the ROLE the
# operand played in its command (MT-033 C-5, AC-6): a denial on the source of an
# `mv` has to be legible as such rather than reading like a denial on the
# destination. Only `cp` and `mv` operands carry a role; every other candidate -
# redirects, `rm`, `touch`, `tee`, `sed -i` - is emitted bare, because its role
# is not ambiguous and inventing one for it is churn.
#
# The role is a SUFFIX, not a prefix, and that is load-bearing. phase-guard.sh
# filters candidates with `grep -vE '^\s*$|^-|\*|^/dev/'` and every one of those
# anchors assumes the line STARTS with the path; a leading role would silently
# turn `^-` off, and an option must never become a candidate. The caller splits
# the line on the tab BEFORE resolve_vars and before the `$EXEMPT` membership
# test, which compares the candidate for exact equality against the resolved
# `scripts/mutate.sh` FILE argument - a role left on the string there would
# silently un-exempt the one diagnostic the harness itself requires in RED.
# A TAB is safe as the separator: the scanner splits tokens on literal tabs and
# readword() stops at one, so no emitted token can contain one, while a tab
# inside a quoted span is already \007 at this point.
#
# This replaces five greps whose last stage was `awk '{print $NF}'`. The last
# word of a match is not an operand. It is the redirect target when the command
# ends in one - `sed -i EXPR src/main.ts > /dev/null` yielded /dev/null, which
# the candidate filter then dropped, so a source file was writable during RED.
# It is a fragment of a sed script when `(` truncated the match inside the
# expression. And it is the wrong file whenever a command takes more than one
# operand: `sed -i EXPR frozen.ts permitted.md` writes both and only the last
# was judged. Five symptoms, four bypasses, one cause.
#
# The input is mask_shell_quotes output, so every operator and every space
# inside a quoted span or a heredoc body is already a control character in
# \001-\010. That is what makes a boundary "real": this scanner splits only on
# LITERAL whitespace and on literal | & ; ( ) < >, so prose mentioning `sed -i`
# is one token and can never be a command name. Widening a character class does
# not do that - `\bsed\b` matches the `sed` in the unmasked token `sed-i`, so
# `git commit -m "sed-i"` was blocked on a path of `sed-i` with no mask
# character anywhere in the match.
#
# Per-command operand semantics (MT-031 C-3, measured against real sed):
#
#   sed, in-place only  every positional, minus the first when no
#                       -e/--expression/-f/--file supplied the script
#   tee, rm, touch      every non-option argument
#   cp                  the LAST non-option argument - the destination. With
#                       three arguments `cp a b c` reads b; judging every
#                       operand would be a false positive, not a fix.
#   mv                  EVERY non-option argument (MT-033 C-3): the last
#                       because it is created, the rest because they are
#                       REMOVED. `mv f1 f2 d/` leaves neither f1 nor f2 where
#                       it was, while `cp g1 g2 e/` leaves both - measured, GNU
#                       coreutils 8.32. That asymmetry is the whole reason this
#                       row and the `cp` row above are not one row: the guard
#                       used to judge the operand `mv` creates and say nothing
#                       about the ones it destroys, so a frozen file could
#                       leave its path in any phase.
#   > >> >|             the word that follows it
#   < <<                a READ. `xargs touch < list` names no write target.
#
# An IO number glued to a redirect (`2>`) is a file descriptor, not an operand:
# it used to be reported as the path `2>/dev/null`, which is a block for the
# wrong reason and would have survived a narrower fix.
#
# Nothing here consults the filesystem: `sed -i -f script.sed src/main.ts` must
# judge src/main.ts whether or not script.sed exists.
write_candidates() {
  printf '%s' "$1" | awk '
    function isname(w) {
      return (w == "sed" || w == "tee" || w == "cp" || w == "mv" || w == "rm" || w == "touch")
    }
    function emit(t) { if (t != "") OUT = OUT t "\n" }
    # A target and the role it played, tab-separated. See the header: the role
    # is a suffix so that the candidate filter in phase-guard.sh keeps anchoring
    # on the path.
    function emitr(t, r) { if (t != "") OUT = OUT t "\t" r "\n" }
    function allops(   k) {
      for (k = 1; k <= na; k++) if (substr(A[k], 1, 1) != "-") emit(A[k])
    }
    function lastop(r,   k, last) {
      last = ""
      for (k = 1; k <= na; k++) if (substr(A[k], 1, 1) != "-") last = A[k]
      emitr(last, r)
    }
    # Every non-option operand of an `mv`, each labelled by the role it plays.
    #
    # Without a target-directory option the roles follow POSITION: the final
    # positional is created, the rest are removed. The role tracks position
    # because that is what the denial has to say - the same token is a source in
    # `mv X d/` and a destination in `mv a b X`.
    #
    # `-t DIR` / `--target-directory DIR` INVERTS that (MT-033 PO-8, R-6/R-7):
    # DIR is the destination and EVERY positional is a source, whatever its
    # position. Measured, GNU coreutils 8.32 - each of these leaves the
    # positional gone from the cwd and present in DIR:
    #
    #   mv -t dest/ f1     mv -td2/ f2     mv --target-directory=d3 f3
    #   mv --target-directory d4 f4        mv -ft d5/ f5     mv -ftd6/ f6
    #
    # So the argument of the option has to be READ, not merely skipped: three of
    # those six spellings glue or attach it, and while the parser dropped every
    # `-` token whole, `mv -tsrc/ docs/notes.md` was an entirely unjudged write
    # INTO src/. Reading it is why this is a scan like sedops() and not a
    # one-line position test. The option TOKEN itself must still never become a
    # candidate - `mv -f`, `mv -v` and `cp -t` are asserted against that.
    #
    # `cp -t` is deliberately NOT given the same treatment: PO-8 amended PO-3
    # for `mv -t` only, because only `mv -t` regressed, and
    # `cp -t src/ docs/notes.md` is pinned permissive by two assertions. It is a
    # real hole, with `install`, `ln -f`, `rsync` and `dd`, and it is a story of
    # its own. So is `--target=DIR`: GNU getopt_long takes any unambiguous
    # abbreviation (measured: `mv --target=d8 f8` moves f8 into d8), and pinning
    # every abbreviation has no criterion behind it - see MT-033 R-7.
    function mvops(   k, j, a, rest, ch, dir, hasdir, skip, np, M) {
      hasdir = 0; skip = 0; np = 0; dir = ""
      for (k = 1; k <= na; k++) {
        a = A[k]
        if (skip) { skip = 0; continue }        # consumed as the -t argument
        if (substr(a, 1, 2) == "--") {
          if (a == "--target-directory") {
            hasdir = 1
            if (k < na) { dir = A[k + 1]; skip = 1 }
          } else if (substr(a, 1, 19) == "--target-directory=") {
            hasdir = 1; dir = substr(a, 20)
          }
          continue
        }
        if (substr(a, 1, 1) == "-") {
          rest = substr(a, 2)
          for (j = 1; j <= length(rest); j++) {
            ch = substr(rest, j, 1)
            # -t takes an argument, so everything after it in the bundle IS
            # that argument rather than more flags: -tDIR and -ftDIR, like
            # the -i.bak of sedops above.
            if (ch == "t") {
              hasdir = 1
              if (j == length(rest)) { if (k < na) { dir = A[k + 1]; skip = 1 } }
              else dir = substr(rest, j + 1)
              break
            }
          }
          continue
        }
        np++; M[np] = a
      }
      if (hasdir) {
        emitr(dir, R_MV_DST)
        for (k = 1; k <= np; k++) emitr(M[k], R_MV_SRC)
        return
      }
      for (k = 1; k <= np; k++) emitr(M[k], (k == np ? R_MV_DST : R_MV_SRC))
    }
    function sedops(   k, j, a, rest, ch, inplace, hasscript, skip, np) {
      inplace = 0; hasscript = 0; skip = 0; np = 0
      for (k = 1; k <= na; k++) {
        a = A[k]
        if (skip) { skip = 0; continue }
        if (substr(a, 1, 2) == "--") {
          if (a == "--in-place" || substr(a, 1, 11) == "--in-place=") inplace = 1
          else if (a == "--expression" || a == "--file") { hasscript = 1; skip = 1 }
          else if (substr(a, 1, 13) == "--expression=" || substr(a, 1, 7) == "--file=") hasscript = 1
          continue
        }
        if (substr(a, 1, 1) == "-" && length(a) > 1) {
          rest = substr(a, 2)
          for (j = 1; j <= length(rest); j++) {
            ch = substr(rest, j, 1)
            # -i takes an OPTIONAL suffix, so everything after it is the
            # backup extension rather than more flags: -i.bak, not -i -. -b -a -k.
            if (ch == "i") { inplace = 1; break }
            if (ch == "e" || ch == "f") {
              hasscript = 1
              if (j == length(rest)) skip = 1
              break
            }
          }
          continue
        }
        np++; P[np] = a
      }
      if (!inplace) return
      FLAG = 1
      for (k = (hasscript ? 1 : 2); k <= np; k++) emit(P[k])
    }
    function flushcmd() {
      if (cmd == "sed") sedops()
      else if (cmd == "cp") { FLAG = 1; lastop(R_CP_DST) }
      else if (cmd == "mv") { FLAG = 1; mvops() }
      else if (cmd != "") { FLAG = 1; allops() }
      cmd = ""; na = 0
    }
    function endtok() {
      if (tok == "") return
      if (isname(tok)) { flushcmd(); cmd = tok }
      else if (cmd != "") { na++; A[na] = tok }
      tok = ""
    }
    # The word a redirect operator points at. Quote-aware, because a redirect
    # target may be quoted, and stops at every real operator so that `>&2`
    # yields nothing rather than swallowing the next command.
    function readword(   w, ch, q) {
      w = ""; q = ""
      while (i <= n) {
        ch = substr(S, i, 1)
        if (ch == "\n") break
        if (q != "") { w = w ch; if (ch == q) q = ""; i++; continue }
        if (ch == "\"" || ch == Q) { q = ch; w = w ch; i++; continue }
        if (index(" \t\n|&;()<>", ch) > 0) break
        w = w ch; i++
      }
      return w
    }
    # The role vocabulary, MT-033 C-5. These three strings are the only ones any
    # assertion accepts and they are reproduced verbatim in the denial.
    BEGIN {
      Q = sprintf("%c", 39); OUT = ""; FLAG = 0
      R_MV_SRC = "source of mv (removed by the move)"
      R_MV_DST = "destination of mv"
      R_CP_DST = "destination of cp"
    }
    { S = (NR > 1 ? S "\n" $0 : $0) }
    END {
      n = length(S); i = 1; tok = ""; q = ""; cmd = ""; na = 0
      while (i <= n) {
        c = substr(S, i, 1)
        # A LITERAL newline is always a command boundary and never inside a
        # quote: the masker emits \010 for a newline that a quote spans. So it
        # also closes a span this scanner only thinks is open - a comment or a
        # heredoc body carries its apostrophes through masking unchanged
        # (`# it` + `s fine`), and without this line the redirect on the NEXT
        # line is swallowed as quoted data and a real write to source goes
        # unjudged.
        if (c == "\n") { q = ""; endtok(); flushcmd(); i++; continue }
        # A quoted span is one token whatever is inside it. The masker leaves
        # the quote characters themselves in place, which is what lets the
        # scanner see the span without re-parsing the shell.
        if (q != "") { tok = tok c; if (c == q) q = ""; i++; continue }
        if (c == "\"" || c == Q) { q = c; tok = tok c; i++; continue }
        if (c == " " || c == "\t") { endtok(); i++; continue }
        if (c == ";" || c == "|" || c == "&" || c == "(" || c == ")") {
          endtok(); flushcmd(); i++; continue
        }
        if (c == ">" || c == "<") {
          if (tok ~ /^[0-9]+$/) tok = ""     # an IO number, not an operand
          endtok()
          i++
          if (substr(S, i, 1) == c) i++                                  # >> <<
          else if (c == ">" && substr(S, i, 1) == "|") i++               # >|
          if (c == "<" && substr(S, i, 1) == "-") i++                    # <<-
          while (i <= n && (substr(S, i, 1) == " " || substr(S, i, 1) == "\t")) i++
          w = readword()
          if (c == ">") emit(w)
          continue
        }
        tok = tok c; i++
      }
      endtok(); flushcmd()
      printf "%s\n%s", (FLAG ? "W" : "-"), OUT
    }'
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
#
# The trailing-slash retry (MT-034 C-3). Every paths.conf glob for a directory
# carries a `/` - `docs/**`, `**/tests/**`, `scripts/**` - so a BARE directory
# name matches none of them and takes the `source` default, which is the right
# default for a file about to be authored and the wrong one for a directory.
# `normalize_rel` strips the slash the author actually typed, so `mv x docs/`
# arrives here as `docs`. So: when the bare form matches no rule, the same path
# is judged again with a single `/` appended, and the slashed form's rule wins
# if there is one.
#
# Three things about that, each of which a test pins:
#
#   * It is RULE-driven, never child-driven. No paths.conf glob begins `src/`,
#     so no retry can invent a category for `src`, and `classify src` stays
#     `source` - which is correct, because `src` is not a category directory.
#   * The order is rules on the bare form -> rules on the slashed form ->
#     is_ignored -> source, so an explicit rule still beats .gitignore (`dist`
#     is vendor, not ignored).
#   * Both spellings go into ONE classify_stdin process, so the retry costs no
#     extra fork. classify runs once per candidate under a 15 s PreToolUse
#     budget, and a hook that times out fails OPEN.
#
# "No rule matched" is read off the `source` answer because paths.conf has no
# rule whose category IS `source`; the default is the only way to get one. A
# path that already ends in `/` is its own slashed form and is not retried.
# Nothing here consults the filesystem (C-5): a bare `fixtures` classifies the
# same whether or not the directory exists.
classify() {
  local rel="$1" cat probe=""
  [ -z "$rel" ] && { printf 'outside'; return; }
  case "$rel" in */) ;; *) probe="$rel/" ;; esac
  cat="$(printf '%s\n%s\n' "$rel" "$probe" | classify_stdin | awk -F'\t' '
    NR == 1                  { c = $1 }
    NR == 2 && c == "source" { c = $1 }
    END                      { print c }')"
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
