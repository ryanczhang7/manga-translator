# Mutation audit: the follow-up stories of the EPIC-04 and EPIC-07 audits - 2026-10-26

*Run 2026-10-26 by the `mutation-tester` agent on Claude Opus 5.5
(`claude-opus-5-5`). The agent definition declares `opus`, and no override was
visible in the dispatch. Checkout: `main` at `c32c689` ("MT-093: close as
DONE"), clean and in sync with origin. No story was active, so the phase lock
was off. No source, test or config file was changed. Every mutation went
through `scripts/mutate.sh`, which restored each file and `cmp`-verified it.
`bash scripts/mutate.sh --check` reported `no stranded mutation` at the end.*

## Scope

**The question.** Did the seven stories filed by the two earlier audits close
the survivors they were filed for, and are the assertions they added sharp?
This is a narrow scope chosen by the user: only what those stories added, not
the whole epics.

| Story | Filed by | Survivor(s) | Test files it added to (from `touches:` and its merge diff) | Merge |
|---|---|---|---|---|
| MT-082 | `EPIC-04-2026-10-13.md` | TS8, TS2 (L2a withdrawn, A-1) | `tests/core/test_budget_run.py` | #89 `91438a3` |
| MT-083 | same | SG3, SG9, SG2 | `tests/core/test_glossary_store.py` | #97 `e973d89` |
| MT-084 | same | CL2, P7, CL5 | `tests/core/test_translate_client.py`, `tests/core/test_translate_parse.py`, `tests/core/conftest.py` | #99 `484df9c` |
| MT-085 | same | PJ2, SC3 | `tests/core/test_proposed_store.py`, `tests/core/test_schema_v4.py` | #101 `77928ef` |
| MT-091 | `EPIC-07-2026-10-22.md` | RS17, RS13 | `tests/core/test_bench_residual.py`, `tests/core/test_bench_s2.py` | #108 `c0ce7da` |
| MT-092 | same | TR1, TR4, MA9 | `tests/core/test_bench_truth.py`, `tests/core/test_bench_matching.py` | #109 `69db71d` |
| MT-093 | same | FM4 | `tests/core/test_fetch_models.py` | #110 `59e9556` |

`git diff <merge>^1 <merge> --stat -- src tests` confirmed that each merge
changed tests only.

**Method, per story.**

1. Re-run each original survivor with the expression the source audit
   recorded, against the narrowest test file holding the new assertion.
2. Run two to five hand-picked **sibling** mutants of the same production
   behaviour that the story's handoff did not try.
3. Check each new assertion's needle, and prove any suspicion by mutation.
4. Spot-check the handoff's mutation table, at least one row per story.

The command shape for every row is

    bash scripts/mutate.sh FILE 'SED' -- uv run pytest -q -p no:cacheprovider <test files>

with no `-x`, so the full failure set could be compared with the handoff. The
exception is the three `tests/core`-wide reruns of survivors, which used `-x`.

**Tooling.** The `mutation` gate was not run. `uv run mutmut --version` gives
`error: Failed to spawn: mutmut` / `Caused by: program not found`, and
`project.conf` still carries `waiver | mutation | mutmut is not installed ...`.
All mutants were chosen by hand.

**Environment.** Windows 11 Home 10.0.26200, Python 3.13.15 (`uv run`),
pytest 8.4.2, `anthropic` 0.125.0, SQLite 3.53.1 (as recorded in MT-085).
`numpy`, Pillow and PySide6 were not re-queried; they are the versions in
`uv.lock` at `c32c689`.

**Deliberately left out.** Production code that none of the seven stories'
tests claim to pin. Re-running the source audits' killed mutants. The
`tests/ui` and `tests/integration` suites. MT-083's cv2 canary flake and
MT-084's Qt access violation, which both handoffs flagged as intermittents
outside their scope.

## Decided

1. **Every original survivor is now killed, and by the story's own new test.**
   That covers 15 runs: TS8, TS2, SG3, SG9, SG2, CL2, P7, CL5, PJ2, SC3, RS17
   at 0.02 and at 0.001, RS13, TR1, TR4, MA9 and FM4. In each run the failing
   test is the one the story added (or, for MA9, the `match=` the story added
   to the existing test). None is killed only by accident. Rests on E-1 and
   E-2.
2. **The added assertions are sharp. No theatre was found.** Needles are
   exact-value equalities, anchored regexes (`^reading index -1 is not on
   page 1:`), identity checks (`raised.value is sentinel`), or `match=` with
   both shapes named. Every story built a non-vacuity precondition into its
   tests: MT-082's estimate-would-permit check, MT-084's request-model-differs
   check, MT-085's truncation-really-is-one-low check, and MT-093's `.part`
   seen-while-streaming check. Rests on E-4.
3. **One survivor cluster per remaining gap. Two are filed.**
   - **S91-1 (LOW-MEDIUM, MT-094).** MT-091 pinned `RESIDUAL_INK_MAX` against
     doubling, but not tightly. Any value in [0.01, 0.0125) stays green: 0.012
     and 0.0124 were measured, and 0.0124 survives all of `tests/core`. That
     is a silent loosening of up to 24% in the S2 verdict the user reads. The
     fixture resolves one pixel in 1,600, so a 17-dot case pins the bar to
     within 0.000625.
   - **S93-1 and S93-2 (LOW, MT-095).** MT-093 pinned the `.part` clean-up for
     an `OSError` only. Narrowing `except BaseException:` to `except OSError:`
     survives all of `tests/core`. Narrowing it to `except Exception:`
     survives the fetch tests. Each narrowing reintroduces FM4 for a real
     interruption: `http.client.IncompleteRead` (not an `OSError`) and Ctrl-C
     (not an `Exception`). The impact is FM4's: a stray `.part` that never
     ships.
4. **Not filed.**
   - **S84-1, unreachable today.** A deny-list `first_text_block`
     (`type not in ("thinking", "redacted_thinking")`) survives all of
     `tests/core`. Its failure needs a leading tool or server-tool block, and
     the request declares no tools. If tools are ever added to the request,
     this mutant is the probe and the fix is a test with a leading `tool_use`
     block.
   - **S83-4a and S83-4b, equivalent.** They are the `<=` boundary variants of
     `_renamed`'s "touches the name" test. difflib never emits two adjacent
     non-`equal` opcodes, so neither mutant can change a verdict. Rests on the
     fuzz in E-3.
5. **Every handoff mutation claim re-run here held** (E-5). Two handoff notes
   are worth carrying forward:
   - MT-085's handoff said AC-1's "no row changes" half was unearned, because
     the raise fails first. It is now earned (S85-3, E-2).
   - MT-092's DV-1 count was correctly amended from 2 to 3.

## Evidence

### E-1: tallies

One row per distinct mutant, at its narrowest run. Originals are the source
audit's own expressions. One malformed attempt was discarded and is not
counted: S82-4 raised `NameError: name 'Usd' is not defined` (the name is not
imported in `translate_stage.py`), so it tested nothing.

| Story | Originals re-run | Siblings | Killed | Survived |
|---|---|---|---|---|
| MT-082 | 2 (TS8, TS2) | 2 (S82-1, S82-3) | 4 | 0 |
| MT-083 | 3 (SG3, SG9, SG2) | 3 (S83-3, S83-4a, S83-4b) | 4 | 2, both equivalent |
| MT-084 | 3 (CL2, P7, CL5) | 3 (S84-1, S84-3, S84-5) | 5 | 1 (S84-1, not filed) |
| MT-085 | 2 (PJ2, SC3) | 2 (S85-2, S85-3) | 4 | 0 |
| MT-091 | 3 (RS17 at 0.02, RS17 at 0.001, RS13) | 5 (S91-1a, -1b, -1c, S91-2, S91-3) | 6 | 2 (S91-1a, S91-1b -> MT-094) |
| MT-092 | 4 (TR1, TR4, MA9, MA9-axis0) | 3 (S92-1, S92-3, S92-6) | 7 | 0 |
| MT-093 | 1 (FM4) | 4 (S93-1, S93-2, S93-3, S93-5) | 3 | 2 (S93-1, S93-2 -> MT-095) |
| **Total** | **18** | **22** | **33** | **7** (4 filed in 2 stories, 2 equivalent, 1 unreachable) |

MA9-axis0 is counted as an original because it is the mutant that MT-092's
user-decided RED addition was written for.

### E-2: every run

Test-file abbreviations: `budget_run` = `tests/core/test_budget_run.py`, and
so on, always under `tests/core/`. "New" marks a test the story added.

| Id | File:line | Mutation | Tests run | Result | Failing test(s) |
|---|---|---|---|---|---|
| TS8 | `pipeline/translate_stage.py:213` | project from `()` | budget_run | 1 failed, 26 passed | new `test_a_chapter_costing_more_than_the_estimate_is_refused_on_its_observed_mean` |
| TS2 | `translate_stage.py:214` | guard reads `run_total` | budget_run | 1 failed, 26 passed | new `test_a_resumed_run_is_refused_on_what_the_chapter_spent_in_an_earlier_run` |
| S82-1 | `store/ledger.py:77` | samples filtered to the latest run: `WHERE run_id = (SELECT MAX(id) FROM run)` | budget_run | 1 failed, 26 passed | `test_chapter_call_costs_spans_every_run_of_the_chapter` (pre-existing reader test) |
| S82-3 | `translate_stage.py:213` | latest sample dropped (`chapter_call_costs(...)[:-1]`) | budget_run | 1 failed, 26 passed | new AC-1 test |
| SG3 | `store/glossary.py:123` | step 3 `if False:` | glossary_store | 1 failed, 29 passed | new `[two-names-swapped]` |
| SG9 | `glossary.py:145` | `range(len - width)` | glossary_store | 1 failed, 29 passed | new `[name-is-the-last-token]` |
| SG2 | `glossary.py:120` | `!= 1` -> `< 1` | glossary_store | 1 failed, 29 passed | new `[name-twice-in-proposed-both-renamed]` |
| S83-3 | `glossary.py:145` | start-of-line match missed: `range(1, ...)` | glossary_store | 7 failed | pre-existing rename tests |
| S83-4a | `glossary.py:130` | `opcode[1] < end` -> `<=` | glossary_store | **30 passed** | none, equivalent (E-3) |
| S83-4b | `glossary.py:130` | `start < opcode[2]` -> `<=` | glossary_store | **30 passed** | none, equivalent (E-3) |
| CL2 | `translate/client.py:97` | `model_id=request["model"]` | translate_client | 1 failed, 17 passed | new `test_the_call_records_the_model_that_served_the_response_not_the_one_requested` |
| P7 | `translate/parse.py:88` | `!= "thinking"` | translate_parse | 2 failed, 36 passed | new `[redacted-then-text]`, `[redacted-then-thinking-then-text]` |
| CL5 | `client.py:116` | cache write `or 1` | translate_client | 1 failed, 17 passed | new `test_cache_counts_the_response_left_absent_are_recorded_as_zero` |
| S84-1 | `parse.py:88` | deny-list `not in ("thinking", "redacted_thinking")` | translate_parse, translate_client, translate_terms, translate_fixtures | **78 passed**; then `tests/core` with `-x`: **2348 passed**, exit 0 | none (Decided 4) |
| S84-3 | `client.py:115` | cache read `or 1` | translate_client | 1 failed, 17 passed | new CL5 test (`absent cache reads recorded as 1`) |
| S84-5 | `client.py:97` | snapshot normalised to alias: `response.model.rsplit("-2", 1)[0]` | translate_client | 1 failed, 17 passed | new CL2 test |
| PJ2 | `store/project.py:892` | lower bound dropped | proposed_store | 1 failed, 15 passed | new `test_a_negative_index_is_refused_and_the_last_bubble_keeps_its_english` (`DID NOT RAISE`) |
| SC3 | `project.py:359` | `ROUND` dropped | schema_v4 | 3 failed, 13 passed | new `[2.01-2010000]`, `[2.09-2090000]`, `[4.18-4180000]` |
| S85-2 | `project.py:892` | `0 <=` -> `-1 <=` | proposed_store | 1 failed, 15 passed | new PJ2 test |
| S85-3 | `project.py:892` | write and **commit** the out-of-range row, then raise (below) | proposed_store | 3 failed, 13 passed | new PJ2 test **at its after-assertion** (`the last region's proposal became 'CLOBBERED'`); 2 pre-existing tests by `IndexError` |
| RS17 0.02 | `bench/residual.py:85` | `0.01` -> `0.02` | bench_residual, bench_s2 | 1 failed, 64 passed | new `test_mt091_ac1_a_region_left_with_one_and_a_quarter_percent_ink_fails_s2s_residual_half` |
| RS17 0.001 | `residual.py:85` | `0.01` -> `0.001` | same | 1 failed, 64 passed | new `test_mt091_ac1_a_region_left_with_exactly_one_percent_ink_passes_s2s_residual_half` |
| RS13 | `residual.py:161` | `if False:` | same | 2 failed, 63 passed | both new `test_mt091_ac2_*` |
| S91-1a | `residual.py:85` | `0.01` -> `0.012` | same | **65 passed** | none -> MT-094 |
| S91-1b | `residual.py:85` | `0.01` -> `0.0124` | same; then `tests/core` with `-x` | **65 passed**; **2348 passed**, exit 0 | none -> MT-094 |
| S91-1c | `residual.py:85` | `0.01` -> `0.0099` | same | 1 failed, 64 passed | new at-threshold test |
| S91-2 | `bench/s2.py:72` | `<=` -> `<` | same | 2 failed, 63 passed | new at-threshold test, `test_ac8_..._both-pass-at-the-threshold` |
| S91-3 | `residual.py:161` | `if not page.regions:` | same | 2 failed, 63 passed | both new AC-2 tests |
| TR1 | `bench/truth.py:157` | `isinstance` | bench_truth | 2 failed, 85 passed | new `[page-width-as-true]`, `[region-index-as-true]` |
| TR4 | `truth.py:226` | `!=` -> `>` | bench_truth | 2 failed, 85 passed | new `[schema-version-0]`, `[schema-version-minus-1]` |
| MA9 | `bench/matching.py:74` | `if False:` | bench_matching | 3 failed, 22 passed | existing test via new `match=`, new `[rows-differ]`, `[columns-differ]` |
| MA9-axis0 | `matching.py:74` | `a.shape[0] != b.shape[0]` | bench_matching | 1 failed, 24 passed | new `[columns-differ]` |
| S92-1 | `truth.py:157` | int fields untyped: `... and kind is not int` | bench_truth | 5 failed, 82 passed | includes new `[page-width-as-true]`, `[region-index-as-true]` |
| S92-3 | `matching.py:74` | compare `.size` | bench_matching | 1 failed, 24 passed | existing transposed-shape test, **only because of MT-092's `match=`** |
| S92-6 | `matching.py:75` | message names `b.shape` twice | bench_matching | 2 failed, 23 passed | both new broadcastable cases (`str(shape_a) in ...`) |
| FM4 | `packaging/fetch_models.py:68` | unlink -> `pass` | fetch_models | 1 failed, 17 passed | new `test_a_download_that_raises_mid_stream_propagates_and_leaves_no_part_behind` |
| S93-1 | `fetch_models.py:67` | `except OSError:` | fetch_models; then `tests/core` with `-x` | **18 passed**; **2348 passed**, exit 0 | none -> MT-095 |
| S93-2 | `fetch_models.py:67` | `except Exception:` | fetch_models | **18 passed** | none -> MT-095 |
| S93-3 | `fetch_models.py:69` | `raise` -> `continue` | fetch_models | 1 failed, 17 passed | new FM4 test |
| S93-5 | `fetch_models.py:69` | `raise` -> `raise OSError("download failed")` | fetch_models | 1 failed, 17 passed | new FM4 test (identity check) |

The non-obvious expressions, verbatim:

    # S82-1
    bash scripts/mutate.sh src/mangatl/store/ledger.py 's/^_SELECT_CALL_COSTS = "SELECT cost_micro_usd FROM llm_call ORDER BY id"/_SELECT_CALL_COSTS = "SELECT cost_micro_usd FROM llm_call WHERE run_id = (SELECT MAX(id) FROM run) ORDER BY id"/' -- uv run pytest -q -p no:cacheprovider tests/core/test_budget_run.py
    # S85-3: the condition commits a write before the raise runs
    bash scripts/mutate.sh src/mangatl/store/project.py 's/                if not 0 <= reading_index < len(region_ids):/                if not 0 <= reading_index < len(region_ids) and (cursor.execute(_UPDATE_PROPOSED, ("CLOBBERED", region_ids[reading_index])) and self._connection.commit() is None):/' -- uv run pytest -q -p no:cacheprovider tests/core/test_proposed_store.py
    # S91-1b
    bash scripts/mutate.sh src/mangatl/bench/residual.py 's/^RESIDUAL_INK_MAX: float = 0\.01/RESIDUAL_INK_MAX: float = 0.0124/' -- uv run pytest -q -x -p no:cacheprovider tests/core
    2348 passed in 122.89s (0:02:02)
    # S93-1
    bash scripts/mutate.sh packaging/fetch_models.py 's/^        except BaseException:$/        except OSError:/' -- uv run pytest -q -x -p no:cacheprovider tests/core
    2348 passed in 116.33s (0:01:56)
    === mutate: command exited 0; restored (verified byte-for-byte against /d/manga-translator/.claude/state/mutations/packaging_fetch_models.py.20261026T200126Z.25771.bak) ===
    # S84-1
    bash scripts/mutate.sh src/mangatl/translate/parse.py 's/        if block.type == "text":/        if block.type not in ("thinking", "redacted_thinking"):/' -- uv run pytest -q -x -p no:cacheprovider tests/core
    2348 passed in 148.14s (0:02:28)
    === mutate: command exited 0; restored (verified byte-for-byte against /d/manga-translator/.claude/state/mutations/src_mangatl_translate_parse.py.20261026T200324Z.33092.bak) ===

### E-3: the claims behind the filed and unfiled survivors

- **S91-1's survival range.**
  - *The claim:* no test fails for a bar in [0.01, 0.0125).
  - *Inputs:* the claim is measured at exactly three values, 0.012, 0.0124
    (both survive) and 0.0099 (killed). The range rests on those plus MT-091's
    own 0.0125 kill. It was not swept.
  - *Why the upper end holds:* the over-side test's literal is 0.0125, so any
    bar at or above 0.0125 fails it.
  - *Python facts relied on:* `17/1600 == 0.010625` is `True`, and
    `17/1600 <= 0.0124` is `True`
    (`uv run python -I -c "print(17/1600 == 0.010625, 17/1600 <= 0.01, 17/1600 <= 0.0124)"`
    printed `True False True`).
  - *What would make it unrepresentative:* a test outside `tests/core` that
    reads the constant. The `tests/ui` and `tests/integration` suites were not
    run.
- **S93-1 and S93-2 matter because of the exception hierarchy.**
  - *Inputs:* `uv run python -I -c "import http.client; print([c.__name__ for c in http.client.IncompleteRead.__mro__])"`
    printed `['IncompleteRead', 'HTTPException', 'Exception', 'BaseException', 'object']`,
    and `issubclass(KeyboardInterrupt, Exception)` printed `False`.
  - *Not checked:* that `urllib` really raises `IncompleteRead` from `read()`
    on a short body in this Python. That is documented CPython behaviour, but
    no truncated server was run here.
  - *Further gap:* S93-2 was run against `test_fetch_models.py` only, not
    against all of `tests/core`.
- **S84-1 is unreachable.**
  - *The union:* `anthropic` 0.125.0's `ContentBlock` union is `TextBlock,
    ThinkingBlock, RedactedThinkingBlock, ToolUseBlock, ServerToolUseBlock,
    WebSearchToolResultBlock, WebFetchToolResultBlock,
    CodeExecutionToolResultBlock, BashCodeExecutionToolResultBlock,
    TextEditorCodeExecutionToolResultBlock, ToolSearchToolResultBlock,
    ContainerUploadBlock`, printed with `typing.get_args`.
  - *The request:* `translate/prompt.py` has no `tools` key. The only match
    for `tools` in it is a comment on cache order, found by grep. Every block
    type beyond the first three needs a tool.
  - *Assumption:* the API sends no tool-result block to a request that
    declares no tools.
- **S83-4a and S83-4b are equivalent.**
  - *Tool and command:* the script `fuzz_opcodes.py` in the session
    scratchpad, run as `uv run python -I fuzz_opcodes.py <seed> 200000`. It
    reproduces step 4's selection on random token lists, using the shipped
    predicate and both mutated ones.
  - *Inputs:* vocabulary of 5 tokens, lists of length 1-7, a name of width
    1-2, three seeds: 1, 7, 42.
  - *Result:* `verdict_differs=0` on all 600,000 cases.
  - *The argument:* `get_opcodes` puts at most one non-`equal` opcode between
    two matching blocks, so the opcode next to a replace over the name is
    always `equal`.
  - *What would make it unrepresentative:* a different `SequenceMatcher`
    implementation, or names wider than 2 tokens. Widths above 2 were not
    fuzzed.

### E-4: needles and theatre

Each needle the stories added, with the mutant that proves it bites. Where no
mutant was run, the row says so.

- **MT-082.** `len(aborted) == 1`, then `reason == BUDGET`, `ordinal`,
  `translator.calls`, and the exact ledger rows. The closing
  `Budget(...).check(...).permitted is True` and `run_total(...) == 0`
  assertions are **fixture preconditions**, not production checks. They prove
  the fixture separates the two bases, and they are labelled as such in the
  test. Proven by TS8, TS2 and S82-3.
- **MT-083.** Each case compares the whole entry list for equality. Proven by
  SG3, SG9 and SG2, each failing on the exact `GlossaryEntry` diff.
- **MT-084.** Exact equality on `model_id`, guarded by a precondition that the
  request model differs. CL5's test pins both cache fields and the whole
  `TokenUsage`; S84-3 proves the read half, which the handoff did not run.
  - *A cosmetic flaw, not a needle defect:* the CL2 test's failure message
    hard-codes a diagnosis ("which is the model the request asked for").
    Under S84-5 that diagnosis is false: the value came from stripping the
    snapshot suffix, and only happens to equal the requested id. The assertion
    is right; the message can mislead whoever reads a future failure.
- **MT-085.**
  - The `match=` is anchored with `^` and names `-1` in the message's own
    wording, so a bare `1` (which "page 1" also carries) cannot satisfy it.
  - `after == before` had never been observed failing, because every lower
    bound mutant fails at `pytest.raises` first. S85-3 now earns it.
  - "Nothing written" rests on two mechanisms, the pre-check loop and
    `transaction()`'s rollback. Mutating either alone is unobservable, which
    is why S85-3 had to commit explicitly.
- **MT-091.** Fraction literals are asserted before the verdict, so the
  construction itself is pinned. S91-2 shows the at-threshold test also pins
  inclusivity (`<=`). The gap is resolution, not sharpness (S91-1).
- **MT-092.**
  - `match="different shapes"`, plus `str(shape_a)` and `str(shape_b)` in the
    message. S92-6 proves the shape half, and S92-3 shows the `match=` is what
    kills a size-only guard.
  - The truth-loader cases assert only `InvalidGroundTruth` and the path, not
    the reason. Each new case was shown to be refused *only* by the check it
    names, because its mutant gives `DID NOT RAISE` (TR1, TR1b in MT-092's
    GATES, TR4).
- **MT-093.** Identity (`is sentinel`), a non-vacuity check that the `.part`
  existed while streaming, and two existence checks. Proven by FM4, S93-3 and
  S93-5. The gap is exception breadth, not the needles (S93-1, S93-2).

**Theatre.** None found in the added tests. No assertion only checks that a
function was called, that a page rendered, or that a snapshot matched itself.

### E-5: handoff mutation tables, spot-checked

| Story | Row | Claimed | Re-run here | Holds? |
|---|---|---|---|---|
| MT-082 | DV-1 TS8 | 1 failed, 26 passed, AC-1 test | same | yes |
| MT-082 | DV-1 TS2 | 1 failed, 26 passed, AC-2 test | same | yes |
| MT-083 | step 4, SG3, SG9, SG2 | each 1 failed, 29 passed, its own case | same, the same cases | yes |
| MT-084 | CL2, P7, CL5 | 1/17, 2/36, 1/17 | same | yes |
| MT-085 | PJ2, SC3 | 1/15 `DID NOT RAISE`; 3/13 on the three hard ceilings | same | yes |
| MT-091 | runs 4, 5, 6 | 1/64, 1/64, 2 failed (residual only: 31 passed) | 1/64, 1/64, 2 failed / 63 passed over both files | yes (the larger pass count is the second file) |
| MT-092 | TR1, TR4, MA9 (amended to 3), axis-0 | 2/85, 2/85, 3/22, 1/24 | same | yes |
| MT-093 | FM4 | 1 failed, 17 passed | same | yes |

**How E-5 could be wrong.** Agreement was judged by test name and count. It
was also judged by the `E` line where one was printed. It was not judged
assertion line by assertion line.

## What would have to be true for this to be wrong

- That a single `sed` edit is a fair stand-in for a regression. In particular,
  S91-1's "silent 24% loosening" assumes someone re-tunes the constant without
  re-measuring.
- That `tests/core` holds every test that could kill S91-1b, S93-1 and S84-1.
  `tests/ui` and `tests/integration` were not run against them.
- That difflib's opcode contract (no two adjacent non-`equal` opcodes) holds
  beyond the fuzzed widths, for S83-4's equivalence.
- That the API never sends a tool block to a tool-less request, for S84-1.
- That `urllib` surfaces a truncated body as `IncompleteRead` from `read()`,
  for S93-1's relevance.

## What was not checked

- **No tool-generated mutant set.** `mutmut` is absent. This audit used 40
  hand-picked mutants, 22 of them siblings, aimed at each story's most
  load-bearing assertion. The production functions were not enumerated.
- **Only three survivors were widened to `tests/core`:** S91-1b, S93-1 and
  S84-1. S91-1a was run against the two bench files only, S93-2 against the
  fetch file only, and S83-4a and S83-4b against the glossary file only.
  Nothing was run against `tests/ui` or `tests/integration`.
- **Killed siblings were not inspected assertion by assertion** beyond the
  printed `E` lines.
- **Not re-run:**
  - MT-082's DV-2 (L2a already killed: 3 failed in `test_call_priced.py`);
  - MT-092's DV-2 (TR1b);
  - MT-093's `except ModelHashMismatch` probe;
  - every source-audit mutant that was already killed.
  The first three were read and judged plausible from their pasted output.
- **The `conftest.py` changes in MT-084** (`FakeUsage` widened to
  `int | None`, `FakeRedactedThinkingBlock`) were read, not mutated. A fake
  that silently gained a `text` attribute would make AC-2 vacuous. The test's
  own `not hasattr(first, "text")` precondition guards that, but this audit
  did not mutate the fake to prove it.
- **S91-1's range is three points, not a sweep** (E-3).
- **The intermittents** flagged by MT-083 (cv2 canary) and MT-084 (Qt access
  violation under coverage) did not recur in any run here. They were not
  investigated.
- **One machine** (Windows 11). Nothing ran on CI.

## Spike code

None committed. One throwaway probe, `fuzz_opcodes.py`, lived only in the
session scratchpad. It is unreviewed and not production code, and its
substance is restated in E-3. Nothing here is expected to be drawn on by a
later story.

## Stories filed

- **MT-094**, "S2's residual-ink bar is pinned to one pixel above its measured
  value". Survivor S91-1 (Decided 3; E-2, E-3). LOW-MEDIUM; file first.
- **MT-095**, "A model download interrupted by any exception leaves no part
  file behind". Survivors S93-1 and S93-2 (Decided 3; E-2, E-3). LOW.
