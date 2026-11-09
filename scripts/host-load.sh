# shellcheck shell=bash
# scripts/host-load.sh - the host-load warning (HARNESS-074). Sourced, never
# executed, by scripts/selftest.sh, which calls host_load_warn once, before its
# first suite, and sends what it prints to stderr.
#
# WHAT IT LOOKS FOR. Other harness-shaped test runs on this host: a bash or sh
# whose script argument ends in selftest.sh, .test.sh or gates.sh, and which
# is not part of THIS run. This run is the process tree rooted at the
# outermost harness run (the run-lock holder, HARNESS_RUN_LOCK_PID, else $$)
# plus this process's own ancestors (a wrapper, ci-local.sh, an agent's tool
# shell). Sibling suites under SELFTEST_JOBS are descendants of that root and
# so are ours; a self-test in another worktree or another project is not.
#
# THE LISTING is `ps -ef`, which Git Bash, Linux and macOS all have and which
# prints each command with its arguments. The header differs - MSYS prints
# `UID PID PPID TTY STIME COMMAND`, Linux and macOS `UID PID PPID C STIME TTY
# TIME CMD` - so the columns are found by header name, never by position.
# HARNESS_PS_LISTING=<file> replaces `ps -ef` with that file's contents; the
# test library sets it to /dev/null so no fixture run depends on the host.
#
# A WARNING, NEVER A REFUSAL. host_load_warn always returns 0, never pauses,
# and prints nothing for an empty listing. When the listing cannot be had or
# its header cannot be parsed it says so in one line rather than reassure.
#
# A command holding a newline continues on lines of its own, and any row whose
# PID or PPID field is not all digits is skipped as one; a continuation line
# whose words 2 and 3 happen to be numbers is still read as a process.
# An MSYS process 24 hours old or more prints STIME as two words (`Oct 25`,
# `Oct  5`), which shifts the command one field: on each row whose header-named
# STIME column holds a month abbreviation followed by a one- or two-digit day,
# the command is read one field later (HARNESS-076).
# Known limits, not handled: a row whose UID holds a space moves PID out of
# its field and is skipped, or read with the wrong PID and command; either
# way it is not reported. Bash 3.2, awk and coreutils only.

HOST_LOAD_CANNOT="selftest: cannot list this host's processes; other test runs, if any, were not noticed."

# host_load_listing   The process listing on stdout. 1 if it cannot be had.
host_load_listing() {
  if [ -n "${HARNESS_PS_LISTING:-}" ]; then
    cat "$HARNESS_PS_LISTING" 2>/dev/null || return 1
  else
    command -v ps >/dev/null 2>&1 || return 1
    ps -ef 2>/dev/null || return 1
  fi
}

# host_load_others <self-pid> <root-pid> <listing-file>   `<pid><TAB><command>`
# for each test run in the listing that is not ours, in listing order. 1, with
# nothing printed, if the header lacks PID, PPID or COMMAND/CMD. An empty
# listing has no header to judge and prints nothing.
#
# Ours = {root} + root's descendants + self's ancestors + {self}. The two sets
# are built SEPARATELY: seeding self's ancestors into the descendant closure
# makes every child of pid 1 - another tree's run included - ours.
#
# A test run: the command starts with an interpreter path whose basename (after
# the last / or \) is bash, sh or bash.exe, and the word after that path ends
# in selftest.sh, .test.sh or gates.sh. When the first word holds a separator
# the path may run over several words (`C:\Program Files\...\bash.exe`): the
# smallest k whose k-th word has one of those basenames.
host_load_others() {
  awk -v self="$1" -v root="$2" '
    function interp(w) {
      gsub(/\\/, "/", w); sub(/.*\//, "", w)
      return w == "bash" || w == "sh" || w == "bash.exe"
    }
    NR == 1 {
      for (i = 1; i <= NF; i++) {
        if ($i == "PID") pc = i
        else if ($i == "PPID") ppc = i
        else if ($i == "COMMAND" || $i == "CMD") cc = i
        else if ($i == "STIME") stc = i  # optional
      }
      if (!pc || !ppc || !cc) { bad = 1; exit 1 }
      next
    }
    {
      if ($pc !~ /^[0-9]+$/ || $ppc !~ /^[0-9]+$/) next  # a continuation line of a multi-line command
      n++; pid[n] = $pc; ppid[n] = $ppc; par[$pc] = $ppc
      s = cc  # where the command starts; one later after a two-word STIME
      if (stc && $stc ~ /^[A-Z][a-z][a-z]$/ && $(stc + 1) ~ /^[0-9][0-9]?$/) s = cc + 1
      c = $s; for (i = s + 1; i <= NF; i++) c = c " " $i
      cmd[n] = c
      k = 0
      if (interp($s)) k = s
      else if (index($s, "/") || index($s, "\\")) {
        for (i = s + 1; i < NF; i++) if (interp($i)) { k = i; break }
      }
      run[n] = (k && k < NF && $(k + 1) ~ /(selftest\.sh|\.test\.sh|gates\.sh)$/)
    }
    END {
      if (bad) exit 1
      desc[root] = 1
      do { ch = 0; for (i = 1; i <= n; i++) if (!(pid[i] in desc) && (ppid[i] in desc)) { desc[pid[i]] = 1; ch = 1 } } while (ch)  # descendants of root are ours
      a = self; anc[a] = 1; hops = 0
      while ((a in par) && !(par[a] in anc) && hops < n) { a = par[a]; anc[a] = 1; hops++ }
      for (i = 1; i <= n; i++)
        if (run[i] && !(pid[i] in desc) && !(pid[i] in anc)) printf "%s\t%s\n", pid[i], cmd[i]
    }' "$3"
}

# host_load_warn <self-pid> <root-pid>   The warning, on STDOUT - the caller
# sends it to stderr. Always 0. Nothing for an empty listing; the one
# "cannot list" line for a listing that cannot be had or parsed; otherwise a
# count, up to five `pid <pid>: <command>` lines and `and <N-5> more`.
host_load_warn() {
  local found
  found="$(set -o pipefail; host_load_listing | host_load_others "$1" "$2" -)" || {
    printf '%s\n' "$HOST_LOAD_CANNOT"
    return 0
  }
  [ -n "$found" ] || return 0
  printf '%s\n' "$found" | awk '
    { t = index($0, "\t"); pid[NR] = substr($0, 1, t - 1); cmd[NR] = substr($0, t + 1) }
    END {
      printf "selftest: %d other test run(s) are on this host; expect this run to be slower, not wrong:\n", NR
      for (i = 1; i <= NR && i <= 5; i++) printf "selftest:   pid %s: %s\n", pid[i], cmd[i]
      if (NR > 5) printf "selftest:   and %d more\n", NR - 5
    }'
  return 0
}
