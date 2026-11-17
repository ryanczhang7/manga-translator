# shellcheck shell=bash
# scripts/run-lock.sh - the run lock (HARNESS-034). Sourced, never executed, by
# scripts/gates.sh and scripts/selftest.sh, so that two harness runs cannot run
# on top of each other in one tree. The field case (issue #97, finding C): a
# self-test run beside gates.sh in one worktree hung for over 30 minutes, and
# passed alone.
#
# THE LOCK is <root>/.claude/state/run.lock, one per tree and so one per
# worktree, keyed to the running script's own root - never $PWD. Three
# TAB-separated lines, the convention of mutate.sh's .active sentinel:
#
#   pid<TAB><the taking script's $$>
#   started<TAB><UTC, to the second>
#   command<TAB>scripts/gates.sh --gate unit
#
# Created atomically: the record is written to run.lock.<pid> and hard-linked
# into place with `ln` (no -f), which fails when run.lock exists - on MSYS and
# Linux alike - so exactly one contender wins, and nobody can read a record
# half-written.
#
# REFUSE, NEVER WAIT. A held lock is exit 2, "nothing ran". Waiting is what
# turned finding C into an hour-long stall, and a refusal cannot deadlock.
#
# STALE LOCKS are reclaimed by pid: a lock whose pid is not running, or which
# records no pid at all, is removed - with one line saying so - and taken
# again exactly once. A second failure means a contender won, and is refused.
# run_lock_alive errs the cautious way: a recycled pid reads running (a
# refusal whose message says how to clear it), and a live process of the same
# user never reads gone.
#
# A RUN NESTED IN THE SAME TREE - a gate command that runs selftest.sh - would
# be refused by its own parent. Taking the lock exports HARNESS_RUN_LOCK (the
# lock's absolute path) and HARNESS_RUN_LOCK_PID ($$). A run whose own lock
# path equals the first, whose lock records the second, and whose holder is
# alive proceeds without taking, releasing or printing anything. The path is
# what stops a fixture tree adopting the lock of the outer run it inherited
# the variables from; the pid is what stops a stale or hand-set variable being
# a bypass.
#
# THE MACHINE-WIDE QUEUE (HARNESS-108) is joined here, not by the callers: on
# every path that has just TAKEN the run lock, a run that queues
# (run_lock_queues: a full run, or selftest.sh --changed, HARNESS-111) with
# HARNESS_RUN_QUEUE not `off` sources scripts/run-queue.sh beside this file and
# waits there for any other such run on the machine. run_lock_release leaves
# it last. The run lock is still never waited on: lock order is run lock, then
# queue, and the queue is the only thing that waits. scripts/run-queue.sh's
# header has the rest.
#
# Silent on an uncontended take and release: whole-run goldens depend on it.
# Bash 3.2, awk and coreutils only.

RUN_LOCK_HELD=0
RUN_LOCK_FILE=""

# run_lock_alive <pid>   0 if <pid> is running. One line, exactly: DV-1's sed
# expression targets it.
run_lock_alive() { kill -0 "$1" 2>/dev/null; }

# run_lock_field <file> <key>   The value of one key<TAB>value line, verbatim.
run_lock_field() {
  awk -v k="$2" 'index($0, k "\t") == 1 { print substr($0, length(k) + 2); exit }' "$1" 2>/dev/null
}

# run_lock_link <tmp> <lock>   0 if <tmp> is now also <lock>.
run_lock_link() { ln "$1" "$2" 2>/dev/null; }

# run_lock_refuse <self> <lock>   C-2's three refusal lines, from the lock.
run_lock_refuse() {
  local pid started command
  pid="$(run_lock_field "$2" pid)"
  started="$(run_lock_field "$2" started)"
  command="$(run_lock_field "$2" command)"
  printf "run-lock: refusing to start %s: another harness run holds this worktree's lock.\n" "$1" >&2
  printf 'run-lock:   pid %s, started %s: %s\n' "$pid" "$started" "$command" >&2
  printf 'run-lock: wait for it to finish. If pid %s is not that run, delete .claude/state/run.lock and run again.\n' "$pid" >&2
}

run_lock_cannot() {
  printf 'run-lock: cannot create .claude/state/run.lock; nothing was run.\n' >&2
}

run_lock_taken() {
  rm -f "$2"
  RUN_LOCK_HELD=1
  RUN_LOCK_FILE="$1"
  HARNESS_RUN_LOCK="$1"
  HARNESS_RUN_LOCK_PID="$$"
  export HARNESS_RUN_LOCK HARNESS_RUN_LOCK_PID
}

# run_lock_full <command>   0 if <command> is a FULL run, 1 otherwise
# (HARNESS-108, C-5): scripts/gates.sh with none of --fast, --gate, --skip,
# --required, --list, --audit among its words (a --story value cannot be one:
# valid_story_id wants a letter or digit first), or exactly
# scripts/selftest.sh. Every full run joins the machine-wide queue, and so does
# selftest.sh --changed, which is not full (run_lock_queues). Words are
# matched in a case over the space-padded string, so no globbing happens. The
# opening line stays alone on its line: DV-3's sed expression targets it.
run_lock_full() {
  case "$1" in
    scripts/selftest.sh) return 0 ;;
    scripts/gates.sh|'scripts/gates.sh '*)
      case " ${1#scripts/gates.sh} " in
        *' --fast '*|*' --gate '*|*' --skip '*|*' --required '*|*' --list '*|*' --audit '*) return 1 ;;
      esac
      return 0 ;;
  esac
  return 1
}

# run_lock_queues <command>   0 if <command> joins the machine-wide queue, 1
# otherwise (HARNESS-111, C-2): every full run (run_lock_full), and every
# scripts/selftest.sh --changed, with or without a base ref, whatever it
# resolved to. The size of a --changed run is not known here and is not the
# count of its suites, so it queues as a whole. A --changed that is not the
# first argument, a named-suite run and every other non-full run do not. The
# opening line stays alone on its line: the suite pins it.
run_lock_queues() {
  run_lock_full "$1" && return 0
  case "$1" in
    "scripts/selftest.sh --changed"|"scripts/selftest.sh --changed "*) return 0 ;;
  esac
  return 1
}

# run_lock_join <root> <command>   Joins the machine-wide queue
# (scripts/run-queue.sh) once the run lock is taken, and only for a run that
# queues (run_lock_queues: a full run, or selftest.sh --changed). Off and a
# run that does not queue are decided before the file is looked for, so neither
# reads nor writes anything outside the tree. run-queue.sh is this file's
# sibling, not the caller's $PWD's nor <root>'s. Never refuses: 0 always.
run_lock_join() {
  local q
  [ "${HARNESS_RUN_QUEUE:-}" = off ] && return 0
  run_lock_queues "$2" || return 0
  case "${BASH_SOURCE[0]}" in */*) q="${BASH_SOURCE[0]%/*}/run-queue.sh" ;; *) q="run-queue.sh" ;; esac
  if [ ! -f "$q" ] || ! . "$q"; then
    printf 'run-queue: scripts/run-queue.sh is missing; %s runs without the machine-wide queue.\n' "$2" >&2
    return 0
  fi
  run_queue_acquire "$1" "$2"
  return 0
}

# run_lock_acquire <root> <command>   0: this process may run - it took the
# lock, or it is nested under the holder. 2: refused, or the lock cannot be
# created; the message has been printed.
run_lock_acquire() {
  local root="$1" self="$2" dir lock tmp pid command
  dir="$root/.claude/state"
  lock="$dir/run.lock"

  # (1) Nested under the holder, in this same tree.
  if [ -n "${HARNESS_RUN_LOCK:-}" ] && [ "$HARNESS_RUN_LOCK" = "$lock" ] && [ -f "$lock" ]; then
    pid="$(run_lock_field "$lock" pid)"
    if [ -n "$pid" ] && [ "$pid" = "${HARNESS_RUN_LOCK_PID:-}" ] && run_lock_alive "$pid"; then
      return 0
    fi
  fi

  # (2) Take it.
  mkdir -p "$dir" 2>/dev/null
  tmp="$dir/run.lock.$$"
  if ! printf 'pid\t%s\nstarted\t%s\ncommand\t%s\n' \
      "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$self" > "$tmp" 2>/dev/null; then
    rm -f "$tmp" 2>/dev/null
    run_lock_cannot; return 2
  fi
  if run_lock_link "$tmp" "$lock"; then run_lock_taken "$lock" "$tmp"; run_lock_join "$root" "$self"; return 0; fi

  # (5) ln failed, and not because another run holds the lock. A holder that
  # released in the instant between the two is given one more try.
  if [ ! -e "$lock" ]; then
    if run_lock_link "$tmp" "$lock"; then run_lock_taken "$lock" "$tmp"; run_lock_join "$root" "$self"; return 0; fi
    rm -f "$tmp"
    if [ -e "$lock" ]; then run_lock_refuse "$self" "$lock"; else run_lock_cannot; fi
    return 2
  fi

  # (3) Held by a live run: refuse.
  pid="$(run_lock_field "$lock" pid)"
  case "$pid" in
    ''|*[!0-9]*) pid="" ;;
  esac
  if [ -n "$pid" ] && run_lock_alive "$pid"; then
    rm -f "$tmp"
    run_lock_refuse "$self" "$lock"
    return 2
  fi

  # (4) Stale or unreadable: reclaim, and try exactly once more.
  if [ -n "$pid" ]; then
    command="$(run_lock_field "$lock" command)"
    printf 'run-lock: reclaimed a stale lock from pid %s (%s); that process is no longer running.\n' "$pid" "$command" >&2
  else
    printf 'run-lock: reclaimed an unreadable lock (no pid recorded in .claude/state/run.lock).\n' >&2
  fi
  rm -f "$lock"
  if run_lock_link "$tmp" "$lock"; then run_lock_taken "$lock" "$tmp"; run_lock_join "$root" "$self"; return 0; fi
  rm -f "$tmp"
  if [ -e "$lock" ]; then run_lock_refuse "$self" "$lock"; else run_lock_cannot; fi
  return 2
}

# run_lock_release   Removes the lock iff this process took it and it still
# records $$. A no-op otherwise, including in a subshell; never fails.
run_lock_release() {
  [ "$RUN_LOCK_HELD" = 1 ] || return 0
  [ "${BASHPID:-$$}" = "$$" ] || return 0
  RUN_LOCK_HELD=0
  if [ "$(run_lock_field "$RUN_LOCK_FILE" pid)" = "$$" ]; then rm -f "$RUN_LOCK_FILE"; fi
  rm -f "$RUN_LOCK_FILE.$$" 2>/dev/null
  # The queue goes last, so the next run starts only once nothing is held.
  if declare -F run_queue_release >/dev/null; then run_queue_release; fi
  return 0
}
