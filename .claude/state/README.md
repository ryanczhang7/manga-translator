# Harness runtime state

Machine-local, gitignored. Written by the scripts and read by the hooks. Nothing
in here is ever committed; only this file and `.gitkeep` are tracked.

| File | Written by | Read by | Hand-editable |
|---|---|---|---|
| `current-story.env` | `scripts/phase.sh` | the phase guard, the status line | no |
| `last-gate-run` | `scripts/gates.sh` | the stop hook | no |
| `gate-logs/*.log` | `scripts/gates.sh` | you, when a gate fails | yes |
| `gate-logs/*.failed.log` | `scripts/gates.sh` | you, when a failure did not reproduce | yes |
| `mutations/*.bak` | `scripts/mutate.sh` | `scripts/mutate.sh`, to restore the file | yes |
| `mutations/*.new` | `scripts/mutate.sh` | nothing; scratch for the mutated text | yes |
| `mutations/log` | `scripts/mutate.sh` | you, and the story that quotes it | yes |
| `mutations/*.active` | `scripts/mutate.sh` | `mutate.sh --check`, and `gates.sh` through it | yes |
| `phase-guard-declined.log` | `.claude/hooks/phase-guard.sh` | you, when the guard looks noisy | yes |
| `refresh-self.<pid>.sh` | `scripts/refresh-harness.sh` | `bash`, as the script it is running | yes |
| `plan-write.<pid>.md` | `scripts/plan.sh write` | `awk`, while it splices the section | yes |
| `run.lock` | `scripts/gates.sh`, `scripts/selftest.sh` | `scripts/run-lock.sh`, in the next run | yes |
| `run.lock.<pid>` | `scripts/run-lock.sh` | `ln`, while it takes the lock | yes |
| `selftest.<pid>/*.out` | `scripts/selftest.sh`, with `SELFTEST_JOBS` above 1 | `scripts/selftest.sh`, to print each suite in order | yes |

## The `Hand-editable` column is enforced

`.claude/settings.json` denies `Write`, `Edit` and `MultiEdit` on exactly the `no`
rows, and `.claude/tests/settings.test.sh` checks the two against each other in
both directions: a `no` row without its rules fails, a `yes` row with rules fails,
and a rule for a path this table does not list fails. So a new state file cannot
be added without somebody deciding which it is.

The tool list lives in that suite as `TOOLS`, and it drives both directions of the
check — so adding a tool there makes every `no` row demand a rule for it. It is
not a list of every editing tool: `NotebookEdit` is deliberately absent, because it
refuses anything that is not a `.ipynb` before any permission check runs and
nothing in here is a notebook.

The rules are per file rather than a glob over the directory. The glob was right
about the two files below and wrong about everything else: it also covered this
document, so the page describing the directory could not be edited by the tools
it describes, and it covered tool exhaust, so a leftover `mutations/*.bak` could
not be cleaned up after being acted on. Per-file rules are more accurate and less
durable, which is what the test is for.

Verified by probe, because the runtime enforces these and nothing in this
repository does: a file-specific deny blocks a Bash append and a Bash `rm` of
that path, not just the `Write` and `Edit` tools.

**`current-story.env` — not hand-editable.** `scripts/phase.sh` writes it and the
story's frontmatter together, and the guarantee that those two cannot drift holds
only while nothing else writes it. `bash scripts/phase.sh set <id> <PHASE>` is the
supported path. No `current-story.env` means no active story, which means the
phase lock is off entirely.

**`last-gate-run` — not hand-editable.** It is evidence. The Stop hook reads
`RESULT=`, `FULL=` and this file's timestamp out of it to decide whether a phase's
gate obligation was met, so writing `RESULT=pass` by hand forges precisely what
law 3 exists to prevent. `bash scripts/gates.sh` is what writes it.

## The exhaust

The `yes` rows are all written by a tool and safe to delete; the next run
recreates what it needs.

`gate-logs/<id>.failed.log` is the last run of that gate that did not pass:
a six-line header (the gate, its outcome, when it started, the commit and the
gate tree hash) followed by that run's log, byte for byte. `<id>.log` is
overwritten by every run, so this is the copy the flake-checking re-run cannot
destroy. The next run that does not pass replaces it whole; a pass never
removes it, and neither does a run that skips the gate. Delete it by hand once
the cause is understood.

`mutations/` is `scripts/mutate.sh`'s working area, and the backup path is
explicit rather than `$TMPDIR` because that variable is unset in some of the
shells this harness runs in - a mutation whose backup went nowhere once left its
restore depending on the `sed` expression happening to be an exact inverse of a
single-occurrence match. **A `.bak` left behind means a restore failed.**
`mutate.sh` exits 90 and says so when that happens; on every other path it cleans
up after itself. Put the file back from the backup, check it with `cmp`, then
delete the backup. The mutated text is built in a `.new` beside the backup (sed
cannot read and write one path) and an `EXIT` trap removes it, with the `.diff`
the count is read from, on every path the script can still run code on. **A
`.new` left behind means the run was killed outright** - `SIGKILL`, or the machine
going away - which no trap can catch. It arrives with its `.bak`, and there is no
log line for that run: the source file may still be mutated, so check it against
the `.bak` with `cmp` before deleting either.

`mutations/*.active` is the mutation in flight: written immediately before the
file is touched, removed only after a restore verified with `cmp`. **One left
behind means a run was killed, or its restore failed**, so the file may still be
mutated. `bash scripts/mutate.sh --check` names each one and prints its remedy,
and `gates.sh` runs that first and refuses to judge the tree until it is clean.
It is `yes` because deleting it is that remedy; a deny rule would also block the
printed `rm`.

`plan-write.<pid>.md` holds the rendered `## Model guidance` block for the moment
it takes `awk` to splice it into the story, and is removed straight after. Same
reason as the two below for the explicit path rather than `$TMPDIR`. One left
behind means `plan.sh write` died between rendering and splicing; the story file
is untouched in that case, and re-running it is safe.

`refresh-self.<pid>.sh` exists only while a refresh is running, and for the same
reason `mutations/` has an explicit path rather than `$TMPDIR`. `refresh-harness.sh`
replaces `scripts/*.sh`, which includes itself, and bash reads a script by byte
offset as it executes it: overwrite the file underneath and execution resumes at
the old offset in the new bytes, mid-line. So the script copies itself here and
re-execs, and the file being read is then never a file the copy loop writes. An
`EXIT` trap removes it. One left behind means a refresh died outright rather than
finishing, and it is safe to delete.

`run.lock` is the run lock: `scripts/gates.sh` and `scripts/selftest.sh` each
take it before they run anything and release it on every exit they can still
run code on, so a second run in the same tree refuses with exit 2 instead of
running on top of the first. It records the holder's pid, when it started and
its command. **One left behind means a run was killed outright** - `SIGKILL`, or
the machine going away. The next run reclaims it, with one line saying so, when
the recorded pid is no longer running; if that pid has since been reused by a
live process, the next run refuses, and the refusal says to delete the file.
It is `yes` because deleting it is that remedy. `run.lock.<pid>` is the record
being written before `ln` puts it in place as `run.lock`, removed straight
after; one left behind is safe to delete.

`selftest.<pid>/` exists only during a run of `scripts/selftest.sh` with
`SELFTEST_JOBS` of 2 or more over two or more suites: each suite's output goes
to `<name>.out` there while it runs, and the script prints them in suite order.
`<pid>` is the run's own, the one `run.lock` records, so a run nested under
the lock holder gets a directory of its own. It is removed on every exit the
script can still run code on, after the last suite has exited and before the
lock is released. **One left behind means a run was killed outright**, and it
is safe to delete; the next run does not reclaim it.
