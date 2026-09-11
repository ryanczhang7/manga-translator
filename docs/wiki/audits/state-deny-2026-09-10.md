# Audit: narrowing the `.claude/state/` deny rules

**Date:** 2026-09-10
**Scope:** the `deny` block of `.claude/settings.json` at `7591188` (after
PR #10), and what it stops an agent doing to `.claude/state/`. Prompted by two
things the previous round could not finish: `.claude/state/README.md` could not
be updated to document `mutations/`, and a stray `.bak` left by an aborted probe
could not be deleted.
**Left out:** every other rule in the block. The three `Read(...)` denies on
`.env` and `secrets/**` were not touched and were not examined.

## Decided

- **The deny is per file, not a glob over the directory.** `current-story.env`
  and `last-gate-run` are denied for `Write` and `Edit`; nothing else under
  `.claude/state/` is. Those two are the only files in there whose *contents* are
  read as evidence, and they are the whole reason the rule existed.
- **The glob was wrong in two directions, not one.** It covered the two tracked
  documents (`README.md`, `.gitkeep`), which nothing reads at runtime - so the
  page describing the directory could not be edited by the tools it describes.
  And it covered tool exhaust, so a leftover `mutations/*.bak` could not be
  removed after being acted on, which is the one thing the harness explicitly
  tells you to do about one.
- **Per-file rules are less durable, so the durability is a test.** A state file
  added later would get no protection until somebody remembered a line, and that
  is a worse failure than the one being fixed. `.claude/state/README.md` now
  carries a `Hand-editable` column and `.claude/tests/settings.test.sh` checks it
  against `settings.json` in both directions. A `no` row without its rules fails,
  a `yes` row with rules fails, a rule for a path the table does not list fails,
  and a table with an unanswered cell fails.
- **The suite's checks are a function over a supplied (settings, README) pair**,
  not statements about the live files. That is not tidiness: a suite that asserts
  only against the real pair has every assertion pass on its first run and
  forever, whether or not it checks anything, and the usual way to earn those -
  mutate the thing under test - is unavailable here, because the runtime reads
  permissions and hooks live and a suite that edits them is changing the rules it
  runs under. So the real pair must produce no complaints, and each way of
  getting it wrong is a fixture that must produce a specific one.
- **The two protected files keep a second, independent assertion** naming them
  directly, so that widening the column and the rules together still fails.

## Evidence

- **A file-specific deny covers Bash, not just the Write and Edit tools.** This
  was the open question when the change was proposed, and the answer decides
  whether the narrowing gave anything up. Measured by probe against the live
  rules after they were applied: `printf '' >> .claude/state/last-gate-run` and
  `rm -f .claude/state/last-gate-run`, both by absolute path, were both refused.
  A `Write(<path>)` deny is therefore a deny on writing that path, however the
  write is spelled.
- **The enforcement is path-based and comes from these rules.** There is no
  `.claude/settings.local.json` and no user-level `~/.claude/settings.json` on
  this machine, so the project's block is the only source. Measured before the
  change: a Bash write and a Bash `rm` at the repository root both succeeded,
  while the same two under `.claude/state/` were refused - so the boundary was
  the path, and `settings.json` was the lever.
- **The narrowing did what it was for.** The two stray probe files from the
  previous round were deleted with a plain `rm` immediately after the change, and
  `.claude/state/README.md` was rewritten with the `Hand-editable` column and the
  `mutations/` rows. Both were refused before it.
- **Each of the suite's three checks was probed through `scripts/mutate.sh`**,
  one mutation per check, one run each, every restore `cmp`-verified:
  - neutering the unanswered-column check → `an unanswered column` fails, alone;
  - neutering the forwards check → `a no row with no rule`, `a dropped rule` and
    `and it says which files wanted it` fail, and nothing else;
  - neutering the backwards check → `a re-widened glob` fails, alone. That is the
    check that catches the glob returning, and no other check would notice it,
    because `**` satisfies no row rather than contradicting one.
  - The independent floor was earned by pointing `SETTINGS` at a file with no
    deny rules: all four of its assertions fail, plus `no disagreements`.
- **Full selftest:** 10 suites, 436 assertions, 0 failures. New this round:
  `settings` (14).

## Update, same day: the `MultiEdit` gap is closed

`MultiEdit(./.claude/state/current-story.env)` and
`MultiEdit(./.claude/state/last-gate-run)` were added to the deny block, and
`TOOLS` in `settings.test.sh` became `Write Edit MultiEdit`, so the suite now
enforces them in both directions. The section below is left as written; this is
what changed about it.

The flip behaved as the migration case predicted, which is the part worth
recording. Before it, the suite was **green with the new rules already in place
and not enforcing them** - the backwards check's alternation came from `TOOLS`, so
`MultiEdit` lines were invisible to it, and the forwards check did not ask for
them. After it, the live pair passed immediately and **two fixtures failed**: the
baseline pair, which hardcoded `Write`/`Edit` rules and was therefore no longer
the "small, correct" pair it claimed to be, and the assertion `and the shipped
list does not demand it yet`, which had gone false the moment the rules landed.

Both were the fix, not collateral:

- The fixtures are now generated from `$TOOLS` (`settings_for <tool>...`, with
  `good_settings` calling it with the shipped list) plus a `deny_also <rule>`
  helper, so a case reads as "the baseline, plus this one wrong thing" and the
  next tool added cannot leave every fixture quietly wrong.
- The migration assertion was restated without naming the shipped list: **a tool
  in the list demands rules for it, a tool absent from the list demands nothing.**
  That is true whatever `TOOLS` becomes, where the old form was true for exactly
  one day. A test that has to be edited by the change it is meant to police is
  not policing it.

Earned through `scripts/mutate.sh`, one mutation and one verified restore each:
hardcoding `good_settings` to `Write Edit` fails `the baseline pair agrees`;
neutering `deny_also` fails the three cases built on it; dropping the `TOOLS`
override fails `a tool absent from the list demands nothing`.

Still not probed: whether a `MultiEdit(...)` deny is actually enforced. `MultiEdit`
does not exist in this build, so there is nothing here to refuse. A rule naming a
tool a build does not have is inert; a missing rule on a build that has the tool
is a hole - which is why the rules are in even though the probe is not possible.

## Which tools the rules cover — the finding this round opened

The rules name `Write` and `Edit`, as the glob did before them. Probing that:

- **`NotebookEdit` cannot reach these files, so no rule is wanted.** It refuses
  anything that is not a `.ipynb` *before* any permission check runs - measured by
  pointing it at `.claude/state/last-gate-run`, which returned "File must be a
  Jupyter notebook". Inconclusive about permissions and conclusive about reach:
  nothing under `.claude/state/` is a notebook, because `phase.sh`, `gates.sh`,
  `mutate.sh` and the guard all write plain text. A rule for it would be dead
  weight, and a rule nobody can justify is one somebody widens back to a glob.
- **`MultiEdit` is a real gap and it is still open.** It does not exist in this
  build - `ToolSearch` resolves `NotebookEdit` and not `MultiEdit` - so it could
  not be probed here at all. But it edits arbitrary text files where it does
  exist, and `settings.json`'s own `PreToolUse` matcher already lists it, so the
  harness expects builds that have it. **Two rules would close it** - one per
  protected file - and they were not added because the permissions block cannot be
  edited from here. (They were, later the same day; see the Update above.)
- **The phase lock is not a fallback for either.** `paths.conf` classifies
  `.claude/state/**` as `harness` on its first matching rule (`.claude/**`), and
  `phases.conf` lets every phase write `harness`. So the lock permits these files
  in every phase by design, and `settings.json` is the *only* thing protecting
  them. That is what makes the tool list worth being exact about rather than
  approximately right.

The suite carries this as a live migration rather than a comment: `TOOLS="Write
Edit"` at the top of `settings.test.sh` drives both directions of the check, and a
case asserts that setting it to `Write Edit MultiEdit` **fails** today with
`settings.json has no "MultiEdit(...)"` for both protected files. So the day the
rules are added, putting the tool in that list starts enforcing them, and doing it
early fails loudly instead of passing quietly.

## What would have to be true for this to be wrong

- A deny rule's path glob is matched against the path a Bash command writes, and
  a rule naming a literal file therefore also covers `rm` of it. Probed above on
  this runtime; not guaranteed by anything in this repository, which is why the
  README says the supported writer is still `phase.sh` and `gates.sh`.
- `current-story.env` and `last-gate-run` are the only files under
  `.claude/state/` whose contents anything reads as evidence. If a hook later
  reads a third, the test catches the missing rule only once the README lists the
  file - the table is the source of truth, so a file nobody documents is a file
  nobody protects.
- The README's table stays a markdown table with the path first and
  `Hand-editable` last. The parser is positional (`$2` and `$(NF - 1)`); a column
  inserted after `Hand-editable` would silently read the wrong cell. The
  `yes|no` check limits the damage to a loud failure rather than a quiet pass.

## What was not checked

- **Whether a `MultiEdit(...)` deny is enforced.** The rules are now in and the
  suite enforces their presence, but `MultiEdit` does not exist in this build, so
  there is nothing here to refuse and the probe that settled `Write` and `Edit`
  cannot be run for it. Inert where the tool is absent; the point is the builds
  where it is not.
- **`.gitkeep`.** It is tracked, empty, and now editable. Nothing reads it; no
  row was added for it, so the table does not mention it and no rule names it.
  Consistent, but it means the table is not an inventory of the directory - only
  of the files a tool writes.
- **The three `Read(...)` denies.** Out of scope and untouched.
- **Any platform but this one.** The probes were run on Windows under Git Bash.

## Stories filed

None; the harness records its own rounds in this directory rather than in
`docs/backlog/`, which ships to consumers.
