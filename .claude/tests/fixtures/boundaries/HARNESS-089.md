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

### R-1 (planned, from GREEN, 2026-11-06): sigpipe's three line pins moved

**Which test, and what was wrong.** `.claude/tests/sigpipe.test.sh`, C-5
("the twelve status-discarded lines in this tree are excluded by the rule, not
by markers"). Its `DISCARDED` fixture pins three `scripts/check-boundaries.sh`
lines by line number: `:395:res=$(printf`, `:434:rec=$(printf`,
`:626:ph_at="$(git show`. GREEN (commit 0f6e391) added four lines above line
395, so all three moved down by four. The C-5 freshness check then failed as a
stale fixture. The assertion itself was correct. Only the line numbers were
stale. The Contract planned this return before RED began.

**How it was found.** GREEN's `bash scripts/selftest.sh sigpipe` run on the
tree as committed at 0f6e391. Reproduced by the Test Developer before the edit,
with the same tree and the same result (exit 1). The excerpt below is from the
full log of that reproduction:

```
    FAIL C-5 freshness: all twelve status-discarded lines are still where this suite says they are
         expected: 12 lines, none stale
         actual:   12 lines,
           scripts/check-boundaries.sh:395 no longer holds [res=$(printf] - it holds:     gr="$(section "$sfile" "Gate results")"
           scripts/check-boundaries.sh:434 no longer holds [rec=$(printf] - it holds:             fi
           scripts/check-boundaries.sh:626 no longer holds [ph_at="$(git show] - it holds: 

sigpipe: 90 passed, 1 failed
FAIL sigpipe  did 90 units of work, below the floor of 91 in .claude/tests/floors.conf

assertion floors: 0 of 1 suite(s) met their declared floor.
1 of 1 harness suite(s) FAILED.
```

**What it asserts now.** The same twelve lines. The only change is three line
numbers, each confirmed with `grep -n` on `scripts/check-boundaries.sh` before
the edit: `:399:res=$(printf`, `:438:rec=$(printf`, `:630:ph_at="$(git show`.
No other line of the test changed. The comment headers at 1127/1174/1202/1232
are prose and were left alone.

```
-DISCARDED='scripts/check-boundaries.sh:395:res=$(printf
-scripts/check-boundaries.sh:434:rec=$(printf
-scripts/check-boundaries.sh:626:ph_at="$(git show
+DISCARDED='scripts/check-boundaries.sh:399:res=$(printf
+scripts/check-boundaries.sh:438:rec=$(printf
+scripts/check-boundaries.sh:630:ph_at="$(git show
```

**What earns it.** The red above. The freshness check is its own probe. GREEN's
real edit moved the very lines it pins, and the check went red naming exactly
those three lines and what they now hold. The re-pin is the only change between
that red and the green below. No `mutate.sh` run was needed, because the
production change that the check guards against had already happened in the
tree.

**The green after.** `bash scripts/attest.sh -- bash scripts/selftest.sh sigpipe`
(local run, this host). `attest.sh check` on the same command reports `fresh`.

```
run:      2026-11-06T03:54:56Z
command:  bash scripts/selftest.sh sigpipe
tree:     27579728960540b5fb004a8abca017f0c15fe567
status:   ok
exit:     0
duration: 261s
last:     1 harness suite(s) passed.
log:      .claude/state/attest-logs/20261106T035456Z.512533.log

sigpipe: 91 passed, 0 failed
assertion floors: all 1 suite(s) met their declared floor (91 assertions executed, 91 declared).
```

**GREEN on re-entry.** Expected to be a no-op: no source file was touched in
this return. The orchestrator will verify that.

## Amendments

- **AM-1 (AC-2, the control's line count).**
  - **What it said:** "the script as it stands today is refused on exactly
    six lines (330, 336, 372, 1077, 1086, 1113)".
  - **What it says now:** "exactly seven lines (330, 336, 372, 373, 1077,
    1086, 1113; AM-1)". The rule is unchanged.
  - **Why:** AC-2's own rule refuses line 373, `<<< "$before"`, because
    `before` is also assigned from `git show` at line 637. Line 373's value
    is a section of a story copy, so refusing it is within the criterion's
    intent. The count was the PO's error at PLANNED. RED found it, and the
    orchestrator reproduced it (`## Notes`).
  - **Approved by** the user, "Yes, amend to seven", 2026-11-06.

<!-- Acceptance criteria are frozen once the story leaves PLANNED. If one turns
     out to be wrong or unsatisfiable, stop, put it to the product owner, and
     record the change here: which AC, what it said, what it says now, who
     approved it and why. check-boundaries.sh fails a PR whose criteria differ
     from their last committed PLANNED state (else the base branch) without an
     entry here. Omit the section if unused.
     Where the change came from a subagent's claim that the criterion was
     wrong, record the ORCHESTRATOR'S OWN reproduction of it - different
     inputs, not the subagent's code. That claim is also what an agent says
     when it wants to stop failing. -->

