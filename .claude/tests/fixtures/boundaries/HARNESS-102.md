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


### R-1 (diff review 1, finding 1: an unclosed comment opener or a one-line fence hides later entries)

- **Adjudicated R-1:** `fable` (resolved claude-fable-5-2), 2026-11-12, diff review round 1, finding 1.

No test was wrong; tests were missing. Block 3k's `adj_scan` drops everything after an HTML comment opener that never closes, and treats a line that opens and closes a code fence on the same line as opening a fence that never closes, so a new entry after either is never judged (the review reproduced it with a recorded R-1, a prose line quoting the opener, and an unrecorded R-2: the run said `ok`). Found by the GATES → REVIEW diff review. What the tests should assert: a section with content that holds an unclosed comment opener, or ends inside a fence, gets exactly one `FAIL` saying it cannot be read past that point, and the run exits non-zero; each with an accepted twin (the same entries without the stray opener or fence). The new assertions fail against today's block, which is their watched red; RED pastes it below.

**RED, return 1 (2026-11-12, test-developer, resolved claude-opus-5-5).** The
tests, in `.claude/tests/boundaries.test.sh` after the C-9 cases, under
"Return 1 (R-1, ...)": an unclosed comment opener quoted in inline code before
a new unrecorded R-2; the same opener between R-1 and its record; a one-line
fence before a new unrecorded R-2; an ordinary multi-line fence never closed,
with the R-2 head inside it; the comment and one-line-fence cases again in
`## Amendments` with AM-1 and AM-2. Each asserts exactly one FAIL in the whole
run, naming the story, the section and `unreadable`; a non-zero exit; and no
`ok` line for that section. Twins (green on arrival, they are the controls):
the same sections without the stray line and with R-2 or AM-2 recorded; an
opener quoted with its closer on the same line; a fence closed as the last
thing in the section; and an unreadable section identical to the base copy,
which says nothing (the new step comes after step 2). Contract C-4 gains step
2a, amended in place. Decided here: a section that ends inside an ordinary
unclosed multi-line fence is unreadable too, since "ends inside a fence" is the
rule whatever opened the fence.

The watched red, against today's block 3k (attest record `last: 1 of 1
harness suite(s) FAILED.`, log `.claude/state/attest-logs/20261112T180754Z.11317.log`,
`boundaries: 632 passed, 20 failed`; these 16 are the R-1 ones, and no
assertion outside this return fails):

```
    FAIL HARNESS-102 R-1: a prose line quoting an unclosed comment opener in inline code, then a new R-2 with no record: exactly one FAIL in the run, and it names the story, ## Regressions and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-1: a prose line quoting an unclosed comment opener in inline code, then a new R-2 with no record: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-1: a prose line quoting an unclosed comment opener in inline code, then a new R-2 with no record: and there is no ok line for ## Regressions
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-1: an unclosed comment opener between R-1 and its record: the refusal is the unreadable one, not a missing record: exactly one FAIL in the run, and it names the story, ## Regressions and says the section is unreadable
         expected: 1 1
         actual:   1 0
    FAIL HARNESS-102 R-1: a line that opens and closes a backtick fence on the same line, then a new R-2 with no record: exactly one FAIL in the run, and it names the story, ## Regressions and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-1: a line that opens and closes a backtick fence on the same line, then a new R-2 with no record: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-1: a line that opens and closes a backtick fence on the same line, then a new R-2 with no record: and there is no ok line for ## Regressions
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-1: a multi-line fence that is never closed, so the section ends inside it, with a new R-2 head after the opener: exactly one FAIL in the run, and it names the story, ## Regressions and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-1: a multi-line fence that is never closed, so the section ends inside it, with a new R-2 head after the opener: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-1: a multi-line fence that is never closed, so the section ends inside it, with a new R-2 head after the opener: and there is no ok line for ## Regressions
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-1: ## Amendments: AM-1 recorded, a prose line quoting an unclosed comment opener, then a new AM-2 with no record: exactly one FAIL in the run, and it names the story, ## Amendments and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-1: ## Amendments: AM-1 recorded, a prose line quoting an unclosed comment opener, then a new AM-2 with no record: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-1: ## Amendments: AM-1 recorded, a prose line quoting an unclosed comment opener, then a new AM-2 with no record: and there is no ok line for ## Amendments
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-1: ## Amendments: AM-1 recorded, a one-line fence, then a new AM-2 with no record: exactly one FAIL in the run, and it names the story, ## Amendments and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-1: ## Amendments: AM-1 recorded, a one-line fence, then a new AM-2 with no record: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-1: ## Amendments: AM-1 recorded, a one-line fence, then a new AM-2 with no record: and there is no ok line for ## Amendments
         expected: 0
         actual:   1
```

`actual: 0 0` with `exit 0` and the ok line present is the defect itself: the
hidden R-2 (or AM-2) is never judged. The `1 0` row is the reverse case: one
FAIL, but it is the missing-record one for R-1, not the unreadable one.

### R-2 (diff review 1, finding 4: a wrapped prose line that starts with an id is not an entry head)

- **Adjudicated R-2:** `fable` (resolved claude-fable-5-2), 2026-11-12, diff review round 1, finding 4.

No test was wrong; a test was missing. C-1's head pattern makes all three prefixes optional, so a wrapped prose line beginning `R-2 of HARNESS-094 ...` is read as a new entry and refused. Found by the same review. What the test should assert: such a line is not an entry head (no FAIL for that id), while `### R-2`, `**R-2 ...**` and `- **R-2 ...**` still are. C-1 is amended in place by RED to require one prefix. The new assertion fails against today's block; RED pastes it below.

**RED, return 1 (2026-11-12, test-developer, resolved claude-opus-5-5).** Two
tests in `.claude/tests/boundaries.test.sh`, under "Return 1 (R-2, ...)": a
`## Regressions` with a recorded `### R-1` and a prose line wrapping to begin
`R-2 of HARNESS-094 did the same ...` must give no FAIL for R-2, the ok line
and exit 0; the same in `## Amendments` with a wrapped line beginning
`AM-2 of`. The twin, that `### R-1`, `**R-1 (...).**`, `- **R-1 (...).**` and
a three-space-indented `### R-1` are still heads and still refused unrecorded,
is the existing AC-3 head-spelling loop, which stays green and is not
duplicated. Contract C-1 is amended in place with the pattern GREEN builds.

The watched red, from the same run (`.claude/state/attest-logs/20261112T180754Z.11317.log`):

```
    FAIL HARNESS-102 R-2: a prose line that wraps to begin `R-2 of HARNESS-094` is not an entry head: no FAIL for R-2
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-2: and the section, whose only entry R-1 is recorded, gets the ok line
         expected: 1
         actual:   0
    FAIL HARNESS-102 R-2: and the run exits 0
         expected: 0
         actual:   non-zero
    FAIL HARNESS-102 R-2: in ## Amendments, a wrapped line beginning `AM-2 of` is not an entry head: no FAIL for AM-2, exit 0
         expected: 0 0
         actual:   1 non-zero
```


### R-3 (diff review 2, finding 1: a pair of stray lines hides the entry between them)

- **Adjudicated R-3:** `fable` (resolved claude-fable-5-2), 2026-11-12, diff review round 2, finding 1.

No test was wrong; tests were missing. Step 2a judges the end of the section, so an even number of one-line fences, or a quoted opener with a later quoted closer or a later ordinary comment, hides a new unrecorded entry between them and the run says ok. Found by the review of the fix. What the tests should assert: in each of the three reproductions, the section is refused as unreadable (exactly one FAIL, non-zero, no ok line); each with a twin where nothing head-shaped is hidden (accepted). The new assertions fail against today's block; RED pastes the red below.

**RED, return 2 (2026-11-12, test-developer, resolved claude-opus-5-5).** The
tests, in `.claude/tests/boundaries.test.sh` after the R-2 cases, under
"Return 2 (R-3, ...)": each has a recorded `### R-1` and a new unrecorded
`### R-2` with the stray pair around it - two one-line fences; a prose line
quoting the opener and a later one quoting the closer; the quoted opener and a
later ordinary comment; the first again in `## Amendments` with AM-1 and AM-2;
and, decided here, a closed fence whose head-shaped line names an id that is
no head outside it. Each asserts what the R-1 cases assert (exactly one FAIL in
the run, naming the story, the section and `unreadable`; non-zero; no ok
line). Twins, green on arrival and the controls: each pair with only prose
between it and R-2 recorded after it; a closed fence whose head-shaped line
repeats a real head's id; heads only inside a fence and a comment, which keeps
step 3's headless FAIL and is not unreadable; and this section itself, read
verbatim from the file at run time, which gets the ok line. Contract C-4 step
2a is amended in place: the hidden-head test is added, the end-of-section
tests stay, and the remedy's third clause is corrected.

The watched red, against today's block 3k (plain run of
`bash scripts/selftest.sh boundaries`, `boundaries: 664 passed, 15 failed`;
these 15 are all the failures, and every one is R-3's; the attest record of
the same command on the final tree is in the handoff, Return 2):

```
    FAIL HARNESS-102 R-3: a one-line fence before a new unrecorded R-2 and another after it: exactly one FAIL in the run, and it names the story, ## Regressions and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-3: a one-line fence before a new unrecorded R-2 and another after it: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-3: a one-line fence before a new unrecorded R-2 and another after it: and there is no ok line for ## Regressions
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-3: a prose line quoting the comment opener before a new unrecorded R-2, and a later prose line quoting the closer: exactly one FAIL in the run, and it names the story, ## Regressions and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-3: a prose line quoting the comment opener before a new unrecorded R-2, and a later prose line quoting the closer: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-3: a prose line quoting the comment opener before a new unrecorded R-2, and a later prose line quoting the closer: and there is no ok line for ## Regressions
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-3: a prose line quoting the comment opener before a new unrecorded R-2, and a later ordinary complete comment: exactly one FAIL in the run, and it names the story, ## Regressions and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-3: a prose line quoting the comment opener before a new unrecorded R-2, and a later ordinary complete comment: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-3: a prose line quoting the comment opener before a new unrecorded R-2, and a later ordinary complete comment: and there is no ok line for ## Regressions
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-3: ## Amendments: AM-1 recorded, a one-line fence before a new unrecorded AM-2 and another after it: exactly one FAIL in the run, and it names the story, ## Amendments and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-3: ## Amendments: AM-1 recorded, a one-line fence before a new unrecorded AM-2 and another after it: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-3: ## Amendments: AM-1 recorded, a one-line fence before a new unrecorded AM-2 and another after it: and there is no ok line for ## Amendments
         expected: 0
         actual:   1
    FAIL HARNESS-102 R-3: a closed fence holding a head-shaped line whose id is no head outside it: exactly one FAIL in the run, and it names the story, ## Regressions and says the section is unreadable
         expected: 1 1
         actual:   0 0
    FAIL HARNESS-102 R-3: a closed fence holding a head-shaped line whose id is no head outside it: and the run exits non-zero
         expected: non-zero
         actual:   0
    FAIL HARNESS-102 R-3: a closed fence holding a head-shaped line whose id is no head outside it: and there is no ok line for ## Regressions
         expected: 0
         actual:   1
```

`actual: 0 0` with exit 0 and the ok line present is the defect: R-2 (or
AM-2) between the pair is never judged.

## Amendments

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

