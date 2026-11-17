# shellcheck shell=bash
# scripts/run-queue.sh - the machine-wide run queue (HARNESS-108). Sourced,
# never executed, by scripts/run-lock.sh, which joins it on taking a tree's
# run lock and leaves it on releasing that lock. Neither gates.sh nor
# selftest.sh calls it directly.
#
# WHY. Two full harness runs on one machine starve each other: two refresh
# self-tests beside another session's runs took over three hours, where the
# same self-test takes three to four minutes on CI with the machine to itself.
# The run lock (run-lock.sh) stops two runs in ONE tree; this stops two FULL
# runs anywhere on the machine, by making the second wait.
#
# WHICH RUNS. A full run - gates.sh with none of --fast, --gate, --skip,
# --required, --list, --audit, and selftest.sh with no argument at all - and
# every selftest.sh --changed [base-ref] that gets as far as the run lock,
# whatever it resolved to (HARNESS-111). run_lock_queues, in run-lock.sh,
# decides it from the command string before this file is even looked for, so
# a run that does not queue neither reads nor writes the queue. A --changed
# run that selects no suite exits before the run lock and never waits.
# A queued --changed run runs the selection it computed when it was started,
# not when it gets through: one that waits an hour runs the suites its diff
# selected an hour ago, against the tree as it is when it starts. It holds
# that tree's run.lock while it waits, so no other harness run starts there;
# editing the tree meanwhile is not detected.
#
# WHERE. One lock per user per machine, outside every repository:
#
#   ${HARNESS_RUN_QUEUE_DIR:-$HOME/.cache/agentic-harness}/run-queue.lock
#
# $HOME, not $TMPDIR: a temp directory can differ between two sessions of one
# user, or be unset, and two runs that resolve different directories do not
# queue at all. The directory is made with mkdir -p on first use. With neither
# variable set, a directory that cannot be created or written, or a lock path
# that is there and is not a regular file, the run proceeds without the queue
# and says so in one line. HARNESS_RUN_QUEUE=off
# switches the queue off (any other value, and CI=true, leave it on); the
# harness's own suites set it, in .claude/tests/_lib.sh.
#
# THE RECORD is four TAB-separated lines, the run lock's convention plus root:
#
#   pid<TAB><the taking script's $$>
#   started<TAB><UTC, to the second>
#   command<TAB>scripts/gates.sh
#   root<TAB><the tree root, absolute>
#
# Taken as the run lock is taken: the record goes to run-queue.lock.<pid> and
# is hard-linked into place with `ln` (no -f), which fails when the lock
# exists, so exactly one contender wins and nobody reads a half-written record.
#
# WAIT, NEVER REFUSE. Where the run lock refuses, this waits: it removes its
# temporary record, sleeps HARNESS_RUN_QUEUE_POLL seconds (default 5) and tries
# again, for as long as it takes - there is no maximum wait. It says once that
# it is queued and behind what, prints a `still queued` line every
# HARNESS_RUN_QUEUE_HEARTBEAT seconds (default 60), and one `starting` line
# when it gets through. Waiters are not first-come-first-served: whichever
# attempts first after a release wins. The temporary record exists only during
# one attempt, so a waiter killed between attempts leaves nothing behind.
#
# STALE LOCKS are reclaimed by pid: a lock whose pid is not running (kill -0),
# or which records no numeric pid, is removed with one line saying so, and
# taken. The record is read again just before removing it, and removed only if
# it still names the same pid. Two waiters reclaiming one dead holder in the
# same instant can still both run; that window is recorded, not closed.
#
# THE LIMITS OF kill -0. A recycled pid reads alive: the run waits behind a
# process that is not a harness run, and the queued message names the file to
# delete. A holder in a different pid namespace - WSL, a container, another
# MSYS runtime sharing $HOME - reads gone and is reclaimed: the queue does not
# span them.
#
# NESTING. A run in the holder's process tree passes through: taking exports
# HARNESS_RUN_QUEUE_LOCK (the lock's path) and HARNESS_RUN_QUEUE_PID ($$), and
# a run whose own lock path equals the first, whose lock records the second,
# and whose holder is alive proceeds without taking, releasing or printing.
# That covers a gate command running selftest.sh in its own tree and in
# another. A gate command that scrubs its environment (env -i) and then runs a
# harness script in another tree waits on its own ancestor for ever, with the
# heartbeat naming it: not detected.
#
# LOCK ORDER. The tree's run lock first, then the queue. Nothing waits while
# holding a lock it is trying to take a second of, so it cannot deadlock. One
# consequence: a run waiting in the queue already holds its own tree's
# run.lock, so a third run started in that tree is refused, naming the waiter.
#
# Silent on an uncontended take and on every release: whole-run goldens depend
# on it. Bash 3.2, awk and coreutils only.

RUN_QUEUE_HELD=0
RUN_QUEUE_FILE=""
RUN_QUEUE_TMP=""

# run_queue_alive <pid>   0 if <pid> is running. One line, exactly: DV-1's sed
# expression targets it.
run_queue_alive() { kill -0 "$1" 2>/dev/null; }

# run_queue_span <seconds>   <M>m<SS>s: whole minutes, two-digit seconds.
run_queue_span() {
  printf '%dm%02ds' "$(( $1 / 60 ))" "$(( $1 % 60 ))"
}

# run_queue_field <file> <key>   The value of one key<TAB>value line, verbatim.
run_queue_field() {
  awk -v k="$2" 'index($0, k "\t") == 1 { print substr($0, length(k) + 2); exit }' "$1" 2>/dev/null
}

# run_queue_pid <file>   The recorded pid if it is numeric, else nothing.
run_queue_pid() {
  local p
  p="$(run_queue_field "$1" pid)"
  case "$p" in ''|*[!0-9]*) p="" ;; esac
  printf '%s' "$p"
}

# run_queue_without <reason> <self>   C-3's line for proceeding without it.
run_queue_without() {
  printf 'run-queue: %s; %s runs without the machine-wide queue.\n' "$1" "$2" >&2
}

# run_queue_link <tmp> <lock> <self> <root>   One attempt: write the record to
# <tmp> and hard-link it into place. 0: taken. 1: the lock is there. 2: the
# directory cannot be used. <tmp> never outlives the call.
run_queue_link() {
  local n=0
  while [ "$n" -lt 2 ]; do
    n=$((n+1))
    # A lock path that is there and is not a regular file - a directory, say -
    # is unusable: GNU ln would link the record INTO a directory and report
    # success. Refused before the record is written, so nothing is left in it.
    if [ -e "$2" ] && [ ! -f "$2" ]; then return 2; fi
    RUN_QUEUE_TMP="$1"
    if ! printf 'pid\t%s\nstarted\t%s\ncommand\t%s\nroot\t%s\n' \
        "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" "$4" > "$1" 2>/dev/null; then
      rm -f "$1" 2>/dev/null; RUN_QUEUE_TMP=""
      return 2
    fi
    if ln "$1" "$2" 2>/dev/null; then rm -f "$1"; RUN_QUEUE_TMP=""; return 0; fi
    rm -f "$1"; RUN_QUEUE_TMP=""
    [ -e "$2" ] && return 1
    # ln failed and no lock is there: a holder released in that instant, or
    # the directory takes no links. One more try tells them apart.
  done
  return 2
}

# run_queue_took <lock>
run_queue_took() {
  RUN_QUEUE_HELD=1
  RUN_QUEUE_FILE="$1"
  HARNESS_RUN_QUEUE_LOCK="$1"
  HARNESS_RUN_QUEUE_PID="$$"
  export HARNESS_RUN_QUEUE_LOCK HARNESS_RUN_QUEUE_PID
}

# run_queue_acquire <root> <command>   Always 0: it took the queue, is nested
# under the holder, or proceeds without it. Waits while a live run holds it.
run_queue_acquire() {
  local root="$1" self="$2" dir lock tmp pid queued=0 t0 last command started where
  local poll="${HARNESS_RUN_QUEUE_POLL:-5}" beat="${HARNESS_RUN_QUEUE_HEARTBEAT:-60}"

  if [ -n "${HARNESS_RUN_QUEUE_DIR:-}" ]; then
    dir="$HARNESS_RUN_QUEUE_DIR"
  elif [ -n "${HOME:-}" ]; then
    dir="$HOME/.cache/agentic-harness"
  else
    run_queue_without 'neither HARNESS_RUN_QUEUE_DIR nor HOME is set' "$self"
    return 0
  fi
  lock="$dir/run-queue.lock"

  # Nested under the holder, in its process tree: pass through.
  if [ -n "${HARNESS_RUN_QUEUE_LOCK:-}" ] && [ "$HARNESS_RUN_QUEUE_LOCK" = "$lock" ] && [ -f "$lock" ]; then
    pid="$(run_queue_pid "$lock")"
    if [ -n "$pid" ] && [ "$pid" = "${HARNESS_RUN_QUEUE_PID:-}" ] && run_queue_alive "$pid"; then
      return 0
    fi
  fi

  if ! mkdir -p "$dir" 2>/dev/null; then
    run_queue_without "cannot use $dir" "$self"
    return 0
  fi
  tmp="$lock.$$"
  t0=$SECONDS
  last=$SECONDS

  while :; do
    run_queue_link "$tmp" "$lock" "$self" "$root"
    case $? in
      0) run_queue_took "$lock"
         if [ "$queued" = 1 ]; then
           printf 'run-queue: starting %s after waiting %s.\n' "$self" "$(run_queue_span $(( SECONDS - t0 )))" >&2
         fi
         return 0 ;;
      2) run_queue_without "cannot use $dir" "$self"
         return 0 ;;
    esac

    # Held. By a live run: wait.
    pid="$(run_queue_pid "$lock")"
    if [ -n "$pid" ] && run_queue_alive "$pid"; then
      started="$(run_queue_field "$lock" started)"
      command="$(run_queue_field "$lock" command)"
      where="$(run_queue_field "$lock" root)"
      if [ "$queued" = 0 ]; then
        queued=1
        printf 'run-queue: queued: %s waits for another harness run on this machine to finish.\n' "$self" >&2
        printf 'run-queue:   behind pid %s, started %s, in %s: %s\n' "$pid" "$started" "$where" "$command" >&2
        printf 'run-queue: this is waiting, not hanging: it starts by itself when that run ends. If pid %s is not that run, delete %s and it starts.\n' "$pid" "$lock" >&2
        last=$SECONDS
      elif [ $(( SECONDS - last )) -ge "$beat" ]; then
        printf 'run-queue: still queued behind pid %s in %s: %s (waited %s)\n' \
          "$pid" "$where" "$command" "$(run_queue_span $(( SECONDS - t0 )))" >&2
        last=$SECONDS
      fi
      sleep "$poll"
      continue
    fi

    # Stale or unreadable: reclaim it, if it is still the one just read.
    command="$(run_queue_field "$lock" command)"
    where="$(run_queue_field "$lock" root)"
    [ -e "$lock" ] && [ "$(run_queue_pid "$lock")" = "$pid" ] || continue
    if [ -n "$pid" ]; then
      printf 'run-queue: reclaimed a stale queue lock from pid %s (%s, in %s); that process is no longer running.\n' "$pid" "$command" "$where" >&2
    else
      printf 'run-queue: reclaimed an unreadable queue lock (no pid recorded in %s).\n' "$lock" >&2
    fi
    rm -f "$lock" 2>/dev/null
    if [ -e "$lock" ] && [ "$(run_queue_pid "$lock")" = "$pid" ]; then
      # It could not be removed; trying again would print that line for ever.
      run_queue_without "cannot use $dir" "$self"
      return 0
    fi
  done
}

# run_queue_release   Removes the lock iff this process took it and it still
# records $$. A no-op otherwise, including in a subshell; never fails.
run_queue_release() {
  [ "${BASHPID:-$$}" = "$$" ] || return 0
  if [ -n "$RUN_QUEUE_TMP" ]; then rm -f "$RUN_QUEUE_TMP" 2>/dev/null; RUN_QUEUE_TMP=""; fi
  [ "$RUN_QUEUE_HELD" = 1 ] || return 0
  RUN_QUEUE_HELD=0
  if [ "$(run_queue_field "$RUN_QUEUE_FILE" pid)" = "$$" ]; then rm -f "$RUN_QUEUE_FILE"; fi
  return 0
}
