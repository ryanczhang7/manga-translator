# Worked cases behind the rules

These are the evidence behind rules in `.claude/harness/rules.md`. That file is
imported into every turn, so it keeps each rule's statement and points here for
the incident that taught it; the incidents live in this skill, which is loaded
by the phase they are about. Each section names the rule it supports. Nothing
here is a rule of its own: where this file and `rules.md` disagree, `rules.md`
wins.

## Four private copies of "a source module"

Supports `# Path ownership`, "A test that needs this answer asks for it; it does
not reimplement it."

The alternative to asking `scripts/classify.sh` is each guard carrying its own
regex for "a source module", and that is not hypothetical:
four private copies in one project drifted apart and spent six
stories returning **probe artifacts** as production source - deliberately
offending files a guard writes to test a lint rule - asserting real properties
over files written to violate a rule, and passing only because the rule violated
was not the rule being asserted.

## "The default model" against itself

Supports `# The model each agent runs on`: a role's model is declared, and the
resolved model of every dispatch is recorded by name.

A session setting or an explicit override can still win, and the orchestrator
cannot see which did. Two stories once
compared "the default model" against a stronger one, and neither could say what
"default" had resolved to - so the comparison may have been the stronger model
against itself.

## Four needles that could not fail

Supports `# Non-negotiables`, "An assertion's needle is part of the assertion,
and a needle that cannot fail is a test that cannot fail." Four in one day,
across two repositories:

- `"a lockfile is permitted unchecked"` asserted the **absence** of one
  message, so a lockfile refused with a *different* message satisfied it.
- `"the base ref expression is resolved"` was satisfied by the skip note
  **announcing that resolution had failed** - the note quotes the unresolved
  command, so the needle appeared precisely because the substitution broke.
- a needle of `PLAUSIBLE: sed -i option` is satisfied by
  `IMPLAUSIBLE: sed -i option` - the string that means the opposite.
- `grep '^ci-local:'`, used to detect a CI run finishing, matched
  `ci-local: 15 passed, 0 failed` - that **suite's** result inside the run,
  not the **script's** verdict. It was one line of shell in a waiting loop
  and its failure mode was to report a run green.

The rule's three defences, cheapest first - anchor the match, prefer a needle
whose negation is not also a match, probe it by mutating the thing it claims to
pin - map onto these: only the third catches the third case.

## Three guards green over a tree they could not see

Supports `# Non-negotiables`, "A rule is probed against the tree it judges, not
only against fixtures you wrote." Three in one round, in this repository, all
in guards whose suites were green:

- `check-grep-count.sh` was probed with `y=$(grep -c …)` throughout, because
  that is the shape its header explains. It could not see
  `x="$(grep -c …)"` - which is how every real instance in the tree is
  written - and the suite had nothing to say about it.
- the same guard could not see `cat f | grep -c x || printf 0`, judging `cat`
  rather than the grep. A consuming project had wired it into CI where all
  three uses are pipelines: the run was green and meant nothing.
- `check-sigpipe.sh` read a here-string as a heredoc opener and went blind
  from that line to the end of the file - past line 108 of `plan.sh`, and in
  18 of this tree's 38 harness shell files. Its census line kept reporting
  the honest file count while the coverage behind it was partial.

None of the three was reachable from the fixtures, and all three were found by
mutating a real line of the tree with `scripts/mutate.sh`.

Why this is law rather than a comment beside the mechanism: the warning about
it was written into `lib.sh` in release 38, next
to the helper it was about - and its author then committed the same defect in
release 40, in the guard that note describes.

## Negative zero: narrow the generator, not the comparison

Supports `# Non-negotiables`, "Narrowing an input domain can be correct;
loosening a comparison is always a weakening." The full worked case, with the
three things a narrowing carries, is in `SKILL.md` under "A generator is part of the specification";
this is the short form.

The two moves are one line each and look identical in a diff: a round-trip
property failing on a negative zero is fixed either by
keeping `-0` out of the coordinate generator (correct -
JSON cannot carry it) or by making the comparison treat `-0` and `0` as equal
(which stops it distinguishing values for **every number in the document**, and
is easier, because it is a one-line edit in the file the failure is reported
in).

## HARNESS-014: eighteen mutations, no defect

Supports `# Mutation work per story`: why the per-story mutation budget is
stated at all.

Nothing else bounded mutation work per story: on HARNESS-014 the
mutation work was 18 mutations, about 27 full-suite runs and 2h20 of a 7.5h
story, and none of the 18 found a defect.

## A backup that went to an unset $TMPDIR

Supports `# Non-negotiables`, the `.claude/state/**` bullet: `mutate.sh` backs
a file up to an explicit path under `.claude/state/mutations/`.

The backup path is explicit rather than `$TMPDIR` because that variable is
unset in some of the shells this harness runs in, and a mutation whose backup
went nowhere once left its restore depending on the `sed` expression happening
to be an exact inverse of a single-occurrence match.
