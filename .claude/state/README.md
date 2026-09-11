# Harness runtime state

Machine-local, gitignored. Written by the scripts and read by the hooks. Nothing
in here is ever committed; only this file and `.gitkeep` are tracked.

| File | Written by | Read by | Hand-editable |
|---|---|---|---|
| `current-story.env` | `scripts/phase.sh` | the phase guard, the status line | no |
| `last-gate-run` | `scripts/gates.sh` | the stop hook | no |
| `gate-logs/*.log` | `scripts/gates.sh` | you, when a gate fails | yes |
| `mutations/*.bak` | `scripts/mutate.sh` | `scripts/mutate.sh`, to restore the file | yes |
| `mutations/log` | `scripts/mutate.sh` | you, and the story that quotes it | yes |
| `phase-guard-declined.log` | `.claude/hooks/phase-guard.sh` | you, when the guard looks noisy | yes |

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

`mutations/` is `scripts/mutate.sh`'s working area, and the backup path is
explicit rather than `$TMPDIR` because that variable is unset in some of the
shells this harness runs in - a mutation whose backup went nowhere once left its
restore depending on the `sed` expression happening to be an exact inverse of a
single-occurrence match. **A `.bak` left behind means a restore failed.**
`mutate.sh` exits 90 and says so when that happens; on every other path it cleans
up after itself. Put the file back from the backup, check it with `cmp`, then
delete the backup.
