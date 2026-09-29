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
