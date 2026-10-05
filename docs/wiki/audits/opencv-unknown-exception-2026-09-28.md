# `cv2.error: Unknown C++ exception` in coverage-core — 2026-09-28

*Investigation run 2026-09-28 by Claude Opus 5.5 (`claude-opus-5-5`) in an
interactive session, not a dispatched agent. No story; no source or test file
was changed.*

## Scope

**The report.** `bash scripts/gates.sh --fast` in the main checkout, on branch
`story/MT-025-...`, failed the `coverage-core` gate with 34 failures attributed
to `tests/core/test_detect_postprocess.py`. Every one was
`cv2.error: Unknown C++ exception from OpenCV code` at
`src/mangatl/detect/postprocess.py:340`, the
`cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)` call
in `_components_above_floor`. An immediate re-run of the gate passed (776), and
the file on its own passes (33).

**Audited at** `a752a3f` (main, MT-025 closed), in worktree
`quizzical-sanderson-f9d214`. `test_detect_postprocess.py` is identical in test
count (33) at `0ed0cca`, the MT-025 commit the failure was reported against.
The failing log itself is gone: `gates.sh` overwrites
`.claude/state/gate-logs/coverage-core.log` on each run, and the passing re-run
replaced it. `.pytest_cache/v/cache/lastfailed` was likewise cleared by the
re-run.

**Environment.** Windows 11, 12 logical CPUs, 32 GB RAM, CPython 3.12.14 (uv),
`opencv-python-headless 5.0.0.93` (parallel framework: **Concurrency**, i.e.
the MSVC Concurrency Runtime, statically linked — no `concrt140.dll` is
loaded), `numpy 2.5.3`, `onnxruntime-gpu 1.30.0`.

## Decided

1. **The failure is not a defect in `postprocess.py` or in its tests, and no
   story is filed to change either.** Nothing reproduces it in 37 runs that exercise the file (15 of the
   file alone, 18 of the gate, 4 of wider suites; E1–E3, E8), and 17,526 direct calls across every
   input shape the tests use, at 1–12 threads, all succeeded (E4).
2. **"Unknown C++ exception" means a Windows structured exception, not an
   OpenCV error.** The binding's `catch (...)` is reached only by something that
   is neither `cv::Exception` nor `std::exception`; OpenCV's MSVC build uses
   `/EHa`, so hardware exceptions land there. Two concrete triggers reproduce
   the exact message (E5, E6): an **access violation** inside the call, and the
   **inexact floating-point exception being unmasked** on the calling thread.
   Rests on E5–E6.
3. **Memory pressure and thread contention are ruled out as causes.** Out of
   memory, OpenCV reports `Insufficient memory` or `bad allocation`, never
   "Unknown" (E7). Running the gate alongside three copies of the `coverage`
   gate did not reproduce it (E2), and `gates.sh` runs gates sequentially
   anyway (`( cd … && eval "$cmd" ) 2>&1 | tee` at `scripts/gates.sh:515`, no
   background jobs), so unit/coverage/coverage-core never overlapped within the
   one `--fast` run. Rests on E2, E7.
4. **The repository does not set the FP control word.** Nothing in `src/`,
   `tests/` or `scripts/` calls `_controlfp` or an equivalent, and the control
   word stays at the default `0x8001F` (all exceptions masked) across all 776
   `tests/core` tests (E8). Rests on E8.
5. **Best explanation [INFERRED]: a transient, process-external fault.** Every
   `connectedComponentsWithStats` call in one window of about 1.5 s failed, and
   the next process was clean. That pattern fits process state changed briefly
   from outside the test code more than a bug in the code under test. The
   candidates are FP-control-word state set by a DLL injected into the process
   (overlay, capture or AV hooks are the usual ones), or an access violation /
   in-page fault on a mapped page. **Which one it was is not known**, because
   the only evidence was overwritten.

## Evidence

All **[MEASURED]** on 2026-09-28 on the machine above. Scratch scripts were in
the session scratchpad and are not kept. Each is described fully enough to
rewrite it.

- **E1 — the file alone, 15 runs.**
  `uv run pytest -q -p no:randomly tests/core/test_detect_postprocess.py` × 15:
  15/15 `33 passed` (0.64–0.89 s). (`-p no:randomly` was a no-op; that plugin
  is not installed and test order is deterministic.)
- **E2 — the gate under load.** The coverage-core command
  (`uv run pytest -q tests/core --cov=src/mangatl/domain --cov=src/mangatl/typeset --cov=src/mangatl/bench --cov-fail-under=100`)
  × 6, while `uv run pytest -q tests/core tests/ui --cov=src/mangatl` ran × 3
  back to back in parallel: 6/6 `776 passed`, 3/3 `913 passed`, no
  `Unknown C++` in any log.
- **E3 — gate soak.** The same coverage-core command × 12 more, sequentially:
  12/12 `776 passed` (35.96–40.16 s), no `Unknown C++` in any log.
- **E4 — direct stress.** 90 s of `cv2.connectedComponentsWithStats(m, connectivity=8)`
  on random `uint8` masks (densities 0.001/0.05/0.5/0.9), shapes
  `(240,320) (1600,1125) (512,512) (64,64) (1,1) (3,5) (1125,1600)`, cycling
  `cv2.setNumThreads` through 12, 8, 3, 2, 1, -1: 17,526 calls, 0 errors.
- **E5 — access violation ⇒ exact message.** A `1600×1125` `uint8` array backed
  by `VirtualAlloc` memory, with one page in the middle set to `PAGE_NOACCESS`
  via `VirtualProtect`: 3/3 calls raise
  `cv2.error: Unknown C++ exception from OpenCV code`, at 12 threads and at 1.
  After the page is restored, the next call succeeds and the process lives on.
- **E6 — unmasked inexact FP exception ⇒ exact message.** `ucrtbase._controlfp`
  on the calling thread, mask `_MCW_EM`, `240×320` mask with two components:
  - all masked (`0x8001F`): ok, `count=3`
  - invalid + zero-divide unmasked: ok, `count=3`
  - inexact unmasked: `Unknown C++ exception from OpenCV code`

  Same at 12 threads and at 1. The failure persists for as long as the control
  word stays changed, and restoring the word ends it.
- **E7 — memory exhaustion gives different messages.** The process assigned
  itself to a Windows job object with `ProcessMemoryLimit = 600 MiB` (so the
  experiment could not pressure the rest of the machine). It then filled that
  limit in shrinking chunks down to 4 KiB, released a reserve of *H* KiB, and
  made 34 calls on a `1600×1125` mask. Sweeping *H* from 7000 to 8152 in steps
  of 64, both with the thread pool cold and warmed first, gave only
  `(-4:Insufficient memory) Failed to allocate 7200000 bytes` and
  `bad allocation` (`std::bad_alloc`). "Unknown" never appeared. A coarser
  sweep (0–16000 KiB, 12 and 1 threads) gave only `Insufficient memory` or ok.
  After release, every call succeeded.
- **E8 — control word over a real run.** A pytest plugin loaded from outside
  the repo with `-p`, which reads `_controlfp(0,0) & 0x8001F` at every test's
  setup and teardown, over `uv run pytest -q -p no:cacheprovider tests/core`:
  776 passed, one reading (`0x8001f`) and no change. `mangatl.compose` imports
  `onnxruntime` (the GPU build) inside that run, so onnxruntime does not unmask
  FP exceptions when it is imported.
- **E9 — no venv churn.** Main checkout
  `.venv/Lib/site-packages/cv2/cv2.pyd` was last written 2026-09-12 (hardlink
  count 5, shared with the uv cache). `opencv`, `numpy` and `onnxruntime` were
  last installed 2026-09-16. The only change on 2026-09-28 is `ruff`, at 17:13
  local time. No mutation of `detect/` appears in `.claude/state/mutations/log`
  after 2026-09-16.

## What would have to be true for this to be wrong

- That OpenCV 5.0.0's parallel connected-components code has a real race,
  rare enough to miss 17,526 direct calls and 37 suite runs. (It would then need
  34 losses in a row inside one 1.5 s window, which a race makes unlikely.)
- That something in the coverage-core process *before* this file sets the FP
  control word on a nondeterministic path. E8 saw no change on one run, not
  on every run.
- That the 34 failures were not all in one window. The count does not match
  the file's 33 tests, so at least one failure was elsewhere or was miscounted,
  and the lost log is the only record.

## What was not checked

- The actual structured-exception code. The binding discards it, and the
  failing process is gone.
- Which third-party DLLs are injected into processes on this machine
  (overlays, capture tools, endpoint protection). Tools like Process Explorer
  would show them; nothing was installed to look.
- System-wide commit exhaustion. E7 capped one process with a job object, which
  exercises the same allocation paths, but it did not exhaust the machine's
  commit charge, because that would have affected every other process running.
- Whether the same fault can hit `cv2.dilate`, `cv2.resize` or other calls. The
  report named only line 340, and nothing here suggests that call is special.

## Recommendations

- **If it happens again, keep the log first.** Copy
  `.claude/state/gate-logs/coverage-core.log` before re-running. The re-run
  overwrites it, and that is what made this investigation inconclusive. A
  harness change that keeps the last *failing* log for each gate would make
  this automatic. Filed as the harness chore [[MT-046]]
  (`docs/backlog/stories/MT-046.md`): `gates.sh` keeps
  `.claude/state/gate-logs/<gate>.failed.log`, stamped with time, commit and
  tree hash, and a passing re-run leaves it alone. Until MT-046 is DONE, copy
  the log by hand.
- **A cheap discriminator for next time:** run
  `uv run python -c "import ctypes; c=ctypes.CDLL('ucrtbase'); print(hex(c._controlfp(0,0)&0x8001F))"`.
  It shows only that process's state, though. To pin the FP hypothesis, the
  reading has to be taken inside the failing process: add an E8-style plugin
  to the gate's pytest invocation via `-p`, run from outside the repo.

## Stories filed

- [[MT-046]] - *A failing gate's log survives the passing re-run* (chore,
  EPIC-01, harness only). There is still no defect in production or test code
  to fix; the second recommendation above remains unfiled.

## Addendum — recurrence on 2026-09-29 (unit gate, MT-050 RED)

Recorded by the Lead PO while running `gates.sh --fast` at the end of MT-050's RED.
Not investigated further: MT-050 touches nothing under `src/mangatl/detect/`.

- **Gate:** `unit` (`uv run pytest -q tests/core tests/ui`), not `coverage-core`.
  The `coverage` gate, run straight after in a fresh process over the same tests,
  had no detect failures, and a direct re-run of
  `tests/core/test_detect_postprocess.py tests/core/test_detect_page.py` gave
  `43 passed`.
- **Count:** 34 × `cv2.error: Unknown C++ exception from OpenCV code` — 25 in
  `test_detect_postprocess.py`, 9 in `test_detect_page.py`; the same count as the
  2026-09-28 incident. First at `src\mangatl\detect\postprocess.py:164`
  (`cv2.resize` inside `letterbox`).
- **New evidence the first incident lacked:** the failing log (kept by MT-046 as
  `.claude/state/gate-logs/unit.failed.log`) **opens** with faulthandler reporting
  `Windows fatal exception: code 0x8007000e` (E_OUTOFMEMORY as an HRESULT) on the
  main thread, during collection, at:

  ```
  platform.py:327 in _wmi_query
  platform.py:776 in _get_machine_win32
  platform.py:923 in uname
  platform.py:987 in system
  onnxruntime\capi\_pybind_state.py:14 in <module>
  src\mangatl\detect\session.py:32 in <module>
  src\mangatl\detect\postprocess.py:56 in <module>
  ```

  That is, CPython 3.12's WMI-based `platform.system()`, called by the
  `onnxruntime` import, raised a structured exception that was handled (the run
  continued) in the same process whose later `cv2` calls all failed. This fits
  "Decided" point 2 (a Windows structured exception, not a C++ one) and names a
  concrete candidate for the process-state change: the WMI/COM query at import.
  It is a lead, not a root cause; the discriminator under "Recommendations" still
  applies.

## Addendum — the WMI lead investigated (2026-09-29)

*Run 2026-09-29, 21:30–22:40 local, by Claude Opus 5.5 (`claude-opus-5-5`), in an
interactive session, not a dispatched agent. Audited at `bfeac64` (main, MT-051
closed), worktree `angry-sanderson-b090dd`. No story; no source, test or harness
file was changed. Same machine and versions as above. Scratch scripts were in the
session scratchpad and are not kept; each is described fully enough to rewrite
it. W-numbers are this addendum's evidence, and E-numbers are the original's.*

**The question.** Does the WMI/COM query that `onnxruntime` triggers at import
change process state, for example the FP control word, so that later `cv2` calls
fail?

### Decided

1. **No. The WMI query does not change the main thread's FP control word, and no
   FP-control-word state produces the 2026-09-29 pattern.** The query runs on a
   thread of its own (W1). Across 55 fresh processes the main thread's word never
   left `0x8001f` (W5, W9). The only FP state that makes `cv2` say "Unknown"
   (E6: inexact unmasked) instead kills a pytest process outright, whether it is
   set on the main thread or only on OpenCV's worker threads (W6). The incident's
   process ran to the end and reported 1031 passes. "Decided" point 5's FP
   candidate is therefore refuted for this incident. Rests on W1, W5, W6, W9.
2. **The `0x8007000e` report is a co-symptom, not a demonstrated cause
   [INFERRED].** Its reading: an `E_OUTOFMEMORY` raised as a first-chance
   structured exception on CPython's WMI worker thread. faulthandler printed it,
   COM handled it, and `platform` fell back. So something in that process made
   an allocation inside COM fail during collection, and the same process's `cv2`
   calls then failed until it exited, sparing one test (W8). Both point to one
   process-state fault that was in place by collection time, lasted the whole
   process, and was absent from the next one. What that fault was remains
   unknown. Rests on W1, W4, W8.
3. **It was not commit exhaustion, of the machine or of the process.** The
   machine never came near its commit limit (W4). Capping the process and
   exhausting commit at every stage (cv2 import, onnxruntime import, the WMI query
   itself, the first cv2 calls) produced only clean errors or an outright
   process death. It never produced "Unknown C++ exception", and it never left
   cv2 broken once the pressure was released (W3). This extends E7 from "during
   calls" to "during import and during the WMI query".
4. **No fix is identified, so no fix story is filed.** Caching `platform.uname()`
   before the import, or keeping `onnxruntime` out of `postprocess.py`'s import
   graph, would remove the one line of the log where the fault became visible.
   It would not remove the fault. Nothing reproduces the failure, so there is no
   failing test to demand such a change (law 1), and the next recurrence would be
   harder to read. The same holds for every gate-side mitigation.

### Evidence

- **W0 — the kept log is gone [MEASURED].** `.claude/state/gate-logs/unit.failed.log`
  in the main checkout now holds MT-051's RED run (`run: 2026-09-30T01:52:14Z`,
  `commit: c00177e`), which failed on `ZeroDivisionError` in `ui/badges.py`. It
  replaced the MT-050 log about four hours after the addendum above was written.
  No file under `.claude/state/` contains `0x8007000e` or `Unknown C++`. MT-046
  keeps **one** failing log per gate, and every story's RED run of
  `gates.sh --fast` fails `unit` by design, so an intermittent's log lasts only
  until the next story reaches RED. Everything below about the incident's log
  rests on the addendum's description of it.
- **W1 — where the query runs [READ].** CPython v3.12.14 `PC/_wmimodule.cpp`,
  `_wmi_exec_query_impl`: the query runs on a thread made by `CreateThread`
  (`_query_thread`: `CoInitializeEx(STA)`, `CoInitializeSecurity`,
  `ConnectServer`, `ExecQuery`), and results come back over a pipe. The calling
  thread releases the GIL, waits up to 1000 ms for COM init and 100 ms for the
  connection, then 100 ms for the thread to exit, and on timeout it
  *abandons* the thread. There is no `TerminateThread`. The FP control word and
  MXCSR are per-thread state, so nothing on that thread can change the main
  thread's word. faulthandler, which pytest enables, reports every first-chance
  exception with the high bit set except MSVC C++ (`0xE06D7363`) and CLR
  (`0xE0434352`) ones, handled or not. On a thread with no Python state it
  prints the Python threads' stacks, which is why a fault on the WMI worker
  appears under a traceback that ends in `platform._wmi_query`.
- **W2 — the log signature, reproduced [MEASURED].** A process assigned to a job
  object (`ProcessMemoryLimit` 3 GiB) imported `numpy`, filled its commit to
  leave 4096 KiB of headroom, and ran `import cv2; import onnxruntime`.
  faulthandler printed `Windows fatal exception: stack overflow` /
  `Thread 0x… (most recent call first)` over the stack `_wmi_query` ←
  `_win32_ver` ← `win32_ver` ← `uname` ← `system` ← `onnxruntime\capi\_pybind_state.py:14`.
  That is the incident's shape, with a different code (`0xC00000FD`, not
  `0x8007000E`) and a different outcome: the process died, where the incident's
  process continued.
- **W3 — commit exhaustion at each stage [MEASURED].** Same job-object harness,
  one fresh process per point. Headroom *H* was reserved first and released
  after the fill, then the stage ran and the fill was freed. The process then
  made 34 × (`resize` INTER_AREA of `1600×1125×3`, `connectedComponentsWithStats`
  of `240×320`, `dilate`), with inputs allocated before the pressure.
  - `import cv2`, *H* = 512–65536 KiB (2048–4096 in steps of 128; 25 runs):
    `DLL load failed … paging file is too small`, `Failed to register type`,
    `MemoryError`, `SystemError`, or ok.
  - `import cv2, onnxruntime`, *H* = 512–65536 KiB (36 runs): the same, plus
    `DLL load failed while importing onnxruntime_pybind11_state` and
    `bad allocation`. Two processes died: W2 at 4096, and a delay-load failure
    (`0xC06D007E`) at 15360.
  - `platform._wmi_query` alone, *H* = 0–6144 KiB (20 runs): `WinError 1455`,
    `WinError 258` (the 1000 ms timeout, worker abandoned), one stack-overflow
    death, otherwise ok. Never `0x8007000E`.
  - cv2 calls under pressure, thread pool cold and warm, *H* = 0–7936 KiB in
    steps of 256 (64 runs): only `(-4:Insufficient memory)` and `bad allocation`.
    With a cold pool at 1024–2048 KiB, five processes died of stack overflow on
    OpenCV's worker threads.
  - Every process that survived its stage made all 34 × 3 calls without error
    once the pressure was released, and read `0x8001f`.
- **W4 — the machine was never short of commit [MEASURED].** Commit limit
  63.0 GB (32 GB RAM, 29 GB pagefile). Pagefile peak usage since boot
  (2026-09-28 11:22) was 1314 MB. The System log has no event 2004
  (Resource-Exhaustion-Detector, low virtual memory) in 14 days. The
  `Microsoft-Windows-WMI-Activity/Operational` log holds 836 × event 5858 over
  three days. All of those under this user are `0x80041032` (call cancelled)
  from other clients' queries, and none is `0x8007000E` or CPython's
  `Win32_Processor`/`Win32_OperatingSystem` query. The incident's
  `E_OUTOFMEMORY` never reached the WMI service, so it was raised inside the
  pytest process.
- **W5 — the minimal repro [MEASURED].** 40 fresh processes, 20 with
  `platform.uname()` called before any import and 20 without. Each ran `import
  cv2` then `import onnxruntime` (47–126 ms), then 2000 × (`resize` +
  `connectedComponentsWithStats`). Result: 0 errors, and the main thread's
  `_controlfp(0,0)` read `0x8001f` at every step. A thread created after the
  import also starts at `0x8001f`.
- **W6 — what FP state does to a pytest run [MEASURED].** A plugin loaded with
  `-p` from outside the repo unmasked one exception on the main thread at
  `pytest_collection_finish` and left it unmasked, under the `unit` command:
  - inexact: the process died at its first inexact operation, in Python code
    rather than cv2, with `0xC000008F` and rc 3, before reporting any result
  - underflow, overflow, zero-divide, invalid: `1176 passed` each, no `Unknown`

  Unmasking inexact only *around* each cv2 call also killed the process, at the
  first `letterbox`. Clearing the precision mask in MXCSR on only the 12 threads
  that cv2's first parallel call created (`SetThreadContext`, `0x1F80` →
  `0x0F80`) killed the process as well, over the two detect files together.
  None of these gives "run completes, only cv2 tests fail".
- **W7 — what the query leaves loaded [MEASURED].** `platform.uname()` adds
  `amsi.dll` and `mpoav.dll` (Microsoft Defender's AMSI provider), plus
  `clbcatq`, `kernel.appcore`, `uxtheme`, `userenv`, `profapi` and `iphlpapi`,
  and they stay loaded. The `onnxruntime` import adds `dxgi`, `dxcore`,
  `directxdatabasehelper`, `setupapi`, `cfgmgr32`, `devobj`, `wintrust`,
  `crypt32`, `dbghelp`, `powrprof`, `umpdc`, `msvcp140`, `msvcp140_1` and
  `onnxruntime_providers_shared`. This happens in every run, passing ones
  included. Defender's in-process provider is a concrete instance of the "AV
  hooks" candidate, but its presence alone does not tell good runs from bad.
- **W8 — 34 is 35 minus one [MEASURED].** A plugin that makes `cv2.resize`,
  `connectedComponentsWithStats`, `dilate` and `findContours` all raise gives
  35 failures under `unit`: 26 in `test_detect_postprocess.py` and 9 in
  `test_detect_page.py`. The incident had 25 + 9. Neither test file nor
  `postprocess.py` has changed since `e9ccfb6` (2026-09-16). In the failing
  process, then, exactly **one** cv2-reaching test in `test_detect_postprocess.py`
  passed, and the lost log was the only record of which. The six
  `resize`-only tests call `postprocess.py:164` or `:256` and never line 340.
  That makes the 2026-09-28 report ("every one at line 340", 34 failures in a
  33-test file) internally inconsistent, so its details carry less weight than
  the 2026-09-29 ones.
- **W9 — soak [MEASURED].** `uv run pytest -q -p fpwatch -p no:cacheprovider tests/core tests/ui`
  × 15 sequentially (21:59–22:12), with a plugin that logs the main thread's
  `_controlfp(0,0)` whenever it differs from the last reading at session start,
  collection end, and every test's setup and teardown. Result: 15/15
  `1176 passed` (46–56 s), no `Unknown C++`, no faulthandler output, and exactly
  one reading per process (`0x8001f`).
- **W10 — faulthandler sees SEH inside cv2 [MEASURED].** E5 rerun under
  `faulthandler.enable()` (a `PAGE_NOACCESS` page in a `1600×1125` mask). Each
  `cv2.error: Unknown C++ exception` came with several
  `Windows fatal exception: access violation` reports, one per thread that hit
  the page. W6's FP faults print `code 0xc000008f`. So if the incident's 34
  failures were access violations or FP faults, the failing log held dozens of
  faulthandler reports **after** the WMI one. If it held none, the thing cv2's
  `catch (...)` caught was an exception faulthandler ignores. The likeliest
  such exception is an MSVC C++ exception of a type derived from neither
  `cv::Exception` nor `std::exception`. The addendum above says only what the
  log *opened* with.
- **W11 — a coincidence, recorded as one [MEASURED].** The System log has DCOM
  event 10029 (activation of `Windows.Media.Capture.Internal.AppCaptureShell`
  timed out waiting for `BcastDVRUserService` to stop) about every 4 minutes in
  three windows since boot: 09-28 17:03–19:38, 09-29 15:15–16:21 and 09-29
  21:03–22:00. The first incident (MT-025 branch, 16:58–18:50) falls in the
  first window. The second (MT-050 RED, between 16:15 and 16:44) falls at the
  end of the second. The third window held clean gate runs (MT-051,
  21:09–21:14) and the start of W9. Low weight; it is here because capture
  overlays are among the candidates, and Game Bar capture is one.

### What would have to be true for this to be wrong

- That the WMI query's failure itself broke `cv2`, through a path that a job
  object cap does not model. For example, a COM allocator returning a bad
  pointer instead of failing, and `cv2` later touching memory COM had freed.
  W10's reports would then have shown access violations.
- That the process's FP state was changed on a thread W6 did not cover, in a way
  that fails only `cv2` and nothing else. W6 covered the main thread and the
  threads OpenCV's pool had at the end of collection.

### What was not checked

- The rest of the lost log: whether faulthandler reported anything after the WMI
  line (W10), and which test was the survivor (W8). Both would narrow the
  mechanism at once.
- Python 3.13+, whose `platform` and `_wmi` differ, and any `onnxruntime` build
  other than 1.30.0 GPU.
- Which third-party DLLs are injected at the moment of failure. W7 lists what is
  loaded in a healthy process, and nothing has observed a failing one.

### Recommendations

- **Retention is the blocker.** W0 is the second time the one log that mattered
  was overwritten, this time *with* MT-046 in place. A harness chore could
  keep a failing log that contains an unexplained signature
  (`Windows fatal exception`, `Unknown C++ exception`) under a timestamped name
  that no later run replaces. Alternatively it could keep the last *N* failing
  logs per gate instead of one. This changes what `gates.sh` *keeps*, not what it
  judges. Filed by the Lead PO as the harness chore [[MT-053]]
  (`docs/backlog/stories/MT-053.md`). It uses signature-triggered retention:
  `keep-when` lines in `project.conf` name the signatures, a matching failing
  log is kept under `.claude/state/gate-logs/kept/` with MT-046's stamp plus the
  signature, and at most 5 are kept per gate. Last-*N* was considered and
  declined; the story's PO-2 gives the reason. Until MT-053 is DONE, copy the
  log by hand.
- **On the next recurrence, before anything else,** copy the failing log out of
  `.claude/state/`, then read three things from it:
  - how many `Windows fatal exception` reports follow the first one, and their
    codes (W10)
  - which cv2-reaching test in `test_detect_postprocess.py` passed (W8)
  - the System log around the run: `Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=…}`
    for 10029 and 2004 (W4, W11)
- **The first audit's in-process FP discriminator is no longer needed:** W6
  shows FP state cannot produce this pattern. The in-process evidence worth
  having now is W10's faulthandler output, which the gate log already captures
  when it survives.

### Stories filed

- [[MT-053]] - *A failing log with an unexplained signature outlives later
  failures* (chore, EPIC-01, harness only), filed by the Lead PO from the
  retention recommendation above. No fix story: no fix was identified.

## Addendum - mechanism found (MT-068, 2026-10-05)

The 2026-10-05 recurrence kept its log, and the MT-068 spike reproduced it. See
[[MT-068-cv2-parallel-failure]] (`docs/wiki/audits/MT-068-cv2-parallel-failure.md`),
which supersedes this audit's Decided 5 ("best explanation") and the first
addendum's Decided 2 ("what that fault was remains unknown").

The structured exception is `0xC000070A` (`STATUS_THREADPOOL_HANDLE_EXCEPTION`).
`SetThreadpoolWait` raises it when ConcRT attaches a thread to a process whose
default thread pool has lost its I/O completion port. In the probes, the stray
`CloseHandle` that closed the port came from CPython 3.12's `_wmi` worker thread,
abandoned by a slow query during `onnxruntime`'s import, reading a handle from a
dead stack frame. That this is what happened in the incidents is inferred, not
observed.

This audit's E7/W3 (memory pressure never gives "Unknown") and W6 (FP state is not
the cause) stand. W10's question is answered: faulthandler did show the SEH, 176
times.

The fix stories are MT-069 and MT-070.
