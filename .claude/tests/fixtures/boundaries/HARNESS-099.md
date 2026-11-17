## Regressions

- **R-1 (2026-11-08, found at GATES → REVIEW by the fresh diff review).**
  - **What is wrong:** `boot69`'s assertions (a) and (b) compare `kw69`
    (live keep-when lines in file order) with `kwlist69` (lines in
    `gates.sh --list` order). `--list` groups lines by gate, so on any
    manifest whose keep-when lines alternate between gates, (a) and (b) fail
    on a correct manifest. manga-translator's real manifest is that shape: 16
    lines alternating unit / coverage / coverage-core / integration. The
    reviewer predicted `gates: 996 passed, 2 failed` there, which still blocks
    the refresh this story exists to unblock.
  - **How it was missed:** no fixture alternates between gates (`boot.conf`
    has one `unit` line, then one `cov` line). DV-2's bootstrapped clone had
    no live keep-when line, so (a) and (b) compared empty with empty.
  - **What it should assert instead (AM-1):** both sides are stably sorted
    by gate id before comparing, so ids and patterns agree in file order
    within each gate. A new fixture with lines alternating between gates
    (for example unit, cov, unit) pins it, and must fail against the current
    comparison. DV-2 is strengthened to run with manga-translator's real
    manifest copied in (DV-3).
  - **Earning it:** the corrected comparison passes on arrival against an
    alternating fixture only if it is right. RED shows the new fixture's (a)
    and (b) red against the current unsorted comparison, then green after the
    sort. RED also runs one `mutate.sh` mutation removing the sort and
    watches the alternating fixture's assertion go red. The output is pasted
    here.
  - **Earned (test-developer, return to RED, 2026-11-08, Windows host,
    local).** Fixture `alt.conf` (live keep-when lines unit, cov, unit) and
    its count pin added first, against the UNSORTED comparison - the defect
    reproduced, (a) and (b) for the new fixture red, nothing else:

        FAIL AC-7 (alternating-fixture): gates.sh --list attributes every live keep-when line to the gate it names, in manifest order
             expected: unit
             cov
             unit
             actual:   unit
             unit
             cov
        FAIL AC-7 (alternating-fixture): and prints every live keep-when pattern verbatim
             expected: Windows fatal exception
             Unknown C\+\+ exception
             Segmentation fault
             actual:   Windows fatal exception
             Segmentation fault
             Unknown C\+\+ exception
        gates: 1000 passed, 2 failed

    Then both sides stably sorted by gate id (`LC_ALL=C sort -s -t"$_t"
    -k1,1`): `gates: 1002 passed, 0 failed`, floor 1002 met. Then the sort
    removed by mutation, the corrected file restored and verified:

        === mutate: .claude/tests/gates.test.sh (1 line(s) changed by s/ | LC_ALL=C sort -s -t"\$_t" -k1,1//g) ===
        === mutate: running bash scripts/selftest.sh gates ===
            FAIL AC-7 (alternating-fixture): gates.sh --list attributes every live keep-when line to the gate it names, in manifest order within each gate
                 expected: unit
                 cov
                 unit
                 actual:   unit
                 unit
                 cov
            FAIL AC-7 (alternating-fixture): and prints every live keep-when pattern verbatim
                 expected: Windows fatal exception
                 Unknown C\+\+ exception
                 Segmentation fault
                 actual:   Windows fatal exception
                 Segmentation fault
                 Unknown C\+\+ exception
        gates: 1000 passed, 2 failed
        FAIL gates  did 1000 units of work, below the floor of 1002 in .claude/tests/floors.conf
        assertion floors: 0 of 1 suite(s) met their declared floor.
        === mutate: command exited 1; restored (verified byte-for-byte against /d/agentic-dev-harness/.claude/state/mutations/.claude_tests_gates.test.sh.20261108T234612Z.1422539.bak) ===
        mutate: no stranded mutation; nothing of a previous run is in the tree.

- **R-1 before side, whole suite (orchestrator, 2026-11-08):** a
  `--no-hardlinks` clone at `e1500a6` with `D:\mt-harness-refresh`'s
  `project.conf` copied in (read-only), `bash scripts/selftest.sh gates`. It
  confirms the reviewer's prediction exactly, and it is DV-3's before side:

        FAIL AC-7: gates.sh --list attributes every live keep-when line to the gate it names, in manifest order
        FAIL AC-7: and prints every live keep-when pattern verbatim
    gates: 996 passed, 2 failed
    FAIL gates  did 996 units of work, below the floor of 998 in .claude/tests/floors.conf

- **R-1 RED verified by the orchestrator (2026-11-09):** `attest.sh check`
  said `fresh` for `bash scripts/selftest.sh gates` (exit 0,
  `gates: 1002 passed, 0 failed`, no FAIL line, log
  `20261108T235714Z.1446620.log`) and for `bash scripts/gates.sh --fast`
  (exit 0). Diff read: `boot69` sorts both sides stably by gate id (title (a)
  now ends "within each gate"), plus the new `alt.conf` fixture and its count
  pin. Floors 998 → 1002 in both files. `mutate.sh --check` is clean, and the
  Earned block is pasted above.

## Amendments

- **AM-1 (2026-11-08, AC-3(a), approved by the user in chat: "Yes, amend
  it").**
  - **Was:** "... prints one `keep-when: <pattern>` line per live line, under
    the gate the line names, in manifest order - the ids agree".
  - **Is:** "... under the gate the line names, in manifest order within each
    gate (`--list` groups the lines by gate, in `gate`-line order) - the ids
    agree".
  - **Why:** found by the GATES diff review and reproduced by the
    orchestrator (below). `scripts/gates.sh` 634-636 prints keep-when lines
    under each gate, looping over gates in `gate`-line order. So a manifest
    whose keep-when lines alternate between gates is printed grouped, not in
    file order. That is manga-translator's shape, and changing `gates.sh` is
    out of scope. Within one gate `--list` does keep file order, which is the
    order the first-match rule (346-357) depends on. As written, AC-3(a) was
    false of `gates.sh` for the consumer this story exists to unblock.
  - **Orchestrator's reproduction, independent of the reviewer's code:** a
    `--no-hardlinks` clone at `e1500a6`, with `D:\mt-harness-refresh`'s
    `project.conf` copied in. The live keep-when ids are listed in file order
    by an awk over the conf, and in `--list` order by an awk over `gate`
    rows and `keep-when:` lines:

        == MT file order (ids):
        unit unit coverage coverage coverage-core coverage-core integration integration unit unit coverage coverage coverage-core coverage-core integration integration
        == --list order (ids):
        unit unit unit unit coverage coverage coverage coverage coverage-core coverage-core coverage-core coverage-core integration integration integration integration

