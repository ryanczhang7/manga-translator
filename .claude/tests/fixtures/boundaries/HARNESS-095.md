## Regressions

<!-- REQUIRED if this story ever returned to RED after GREEN or GATES; omit
     otherwise. A test that is wrong is never edited into passing, and the
     return is not a footnote - it is the story failing to be one clean cycle,
     and the next person needs to know why. One block per return:
       * which test, what it asserted, and what was wrong with it
       * how the defect was found
       * what it asserts now
       * what earns it, since "watched it fail" cannot apply once the
         implementation exists - the corrected assertion passes on its first
         run and every run after, whether or not it asserts anything: either a
         PROBE (mutate the specific behaviour the test pins, paste the red,
         confirm the revert) or, where the defect was cost rather than
         correctness, a BEFORE/AFTER measurement taken under the gate command -
         not the plain test command, which is the faster one.
         PASTE THE OUTPUT. check-boundaries.sh refuses a PR whose Regressions
         or Gate probes section describes a failure without showing one.
         A result counts only as a block: a line beginning with three
         backticks or three tildes (a fence), or a line indented by exactly
         four spaces. Prose does not count, nor inline code in backticks, nor
         a tab, nor anything inside an HTML comment
       * whether GREEN was a no-op, and the command output proving the source
         was untouched and still passes -->

**R-1 (from GATES, 2026-11-05): condition (a)'s needle cannot fail on the real tree.**

- **Which test:** `procedure.test.sh`, `full_option`, with
  `FULL_WHEN=('every suite' ...)`. It asserted that the text from the first
  full-run span onward says `every suite`.
- **What was wrong:** the step's closing sentence, "CI runs every suite on
  the PR either way", comes after that span. So the bare `every suite` is
  satisfied whether or not condition (a) exists. A needle that cannot fail is
  a test that cannot fail (`rules.md`).
- **How it was found:** finding 1 of the first diff review. The orchestrator
  reproduced it with a different edit, which rewrote line 318's
  `` `every suite`: the run already is the full one `` as
  `the selection was everything`:

      bash scripts/mutate.sh .claude/commands/advance-story.md '318s/`every suite`: the run already is the full one/the selection was everything/' -- bash scripts/selftest.sh procedure
      procedure: 149 passed, 0 failed
      === mutate: command exited 0; restored (verified byte-for-byte against /d/agentic-dev-harness/.claude/state/mutations/.claude_commands_advance-story.md.20261105T222525Z.11085.bak) ===

- **What it must assert now:** condition (a)'s needle is the backticked code
  span `` `every suite` ``. The closing sentence writes it without backticks,
  and a later reword of it will too. AM-1 also adds a needle for (c)'s route
  back, `` `bash scripts/phase.sh set $1 GATES` ``, read from the same region.
  That one fails on the real tree today, because GREEN has not written it.
- **What earns it:** the same mutation, run against the corrected test, must
  turn `procedure` red with the "does not say when" line for
  `` `every suite` ``. RED pastes it here.

RED (R-1) earned: line 318 was checked first (`sed -n 318p` gives
`` `every suite`: the run already is the full one, and there is nothing to ``),
so the line number stands. The corrected test, same mutation, `procedure`
red with the (a) line for advance-story.md. The AM-1 line beside it is
expected: GREEN has not written the route back yet. The floor line is the
same red seen as a count (153 passed against a floor of 154). Then
`mutate.sh --check` was clean:

    $ bash scripts/mutate.sh .claude/commands/advance-story.md '318s/`every suite`: the run already is the full one/the selection was everything/' -- bash scripts/selftest.sh procedure
    === mutate: .claude/commands/advance-story.md (1 line(s) changed by 318s/`every suite`: the run already is the full one/the selection was everything/) ===
    === mutate: running bash scripts/selftest.sh procedure ===
        FAIL procedure_problems over the real tree prints nothing: ...
             expected: 
             actual:   .claude/commands/advance-story.md: its full-run option does not say when: `every suite`
             .claude/commands/advance-story.md: its full-run option does not say how to get back: `bash scripts/phase.sh set $1 GATES`
    procedure: 153 passed, 1 failed
    FAIL procedure  did 153 units of work, below the floor of 154 in .claude/tests/floors.conf
    1 of 1 harness suite(s) FAILED.
    === mutate: command exited 1; restored (verified byte-for-byte against /d/agentic-dev-harness/.claude/state/mutations/.claude_commands_advance-story.md.20261105T223227Z.18262.bak) ===
    $ bash scripts/mutate.sh --check
    mutate: no stranded mutation; nothing of a previous run is in the tree.

Unmutated, the same suite reports only the AM-1 line (attested run in the
handoff's R-1 addendum), so the (a) line above comes from the mutation alone.
The fixture case `full-every-suite-only-in-closing` reproduces the defect
without the real tree: (a) reworded away, the closing sentence kept, exactly
the (a) line.

## Amendments

- **AM-1 (AC-2, case (c) says how to get back to the step).**
  - **What it said:** "(c) ... the fix round runs the full self-test before
    pushing again and records which suite the selection missed in
    `## Notes`. The control: ..."
  - **What it says now:** the same, plus "; that failure is seen at REVIEW,
    so (c) says how to get back to this step:
    `` `bash scripts/phase.sh set $1 GATES` ``".
  - **Why:** finding 2 of the first diff review (`## Diff review`). CI's
    failure is seen at REVIEW, and no step led back to step 2, so case (c)
    would have been skipped in exactly the situation it exists for. This was
    confirmed by reading advance-story's REVIEW → DONE paragraph.
  - **Approved by** the user, "Fix both", 2026-11-05.

