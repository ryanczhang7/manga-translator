# Every parallel cv2 call in one test process fails - MT-068

*Spike run 2026-10-05, 15:33-16:10 UTC, by the `lead-po` agent on Claude Opus 5.5
(`claude-opus-5-5`), dispatched for MT-068. Worktree `mystifying-bell-52c490`,
branch `story/MT-068-every-parallel-cv2-call-in-one-test-proc`, HEAD `43d4b2d`. No
source, test, gate or `project.conf` file was changed. Same machine and package
versions as `opencv-unknown-exception-2026-09-28.md` (MT-068 E-f).*

## Scope

**The question.** Why do all parallel cv2 calls in one gate process fail with
`cv2.error: Unknown C++ exception from OpenCV code`, and can that be reproduced on
demand?

**Inputs.** The two preserved failing logs of 2026-10-05, both checked by sha256
before use:

- `spikes/MT-068/logs/coverage.failed.2026-10-05T031008Z.log` (run 1, `9ba7e5af…0e80`)
- `spikes/MT-068/logs/unit.failed.run2.log` (run 2, `1c56c964…227e`)

The source read: CPython `v3.12.14` and the `3.13`, `3.14` and `main` branches of
`PC/_wmimodule.cpp`; OpenCV `5.0.0` `modules/core/src/parallel.cpp` and
`modules/imgproc/src/resize.cpp`; the Windows SDK 10.0.26100.0 `shared/ntstatus.h`
on this machine.

**Conditions.** Every probe ran on its own, sequentially, while nothing else heavy
was running. The orchestrator started nothing during the spike, and `tasklist`
showed no other python process before the full-suite runs. No probe applied memory
or CPU pressure, so no job object was needed. The only "load" in any probe is a
timing delay injected into one thread of the probe's own process (recipe B). Four
full-suite runs were made, one at a time, each with the `unit` gate's pytest
command plus a `-p` plugin and `-p no:cacheprovider`. No gate was run through
`gates.sh`.

**Out of scope, as the story says.** No production or test change. No version
change. No Linux or macOS.

## Decided

1. **The failing state is: the process's default Windows thread pool has lost its
   I/O completion port handle. In that state, every thread that makes its first
   parallel cv2 call after the loss fails on every parallel cv2 call, for the rest
   of the process.**
   - OpenCV 5.0.0's parallel backend is the MSVC Concurrency Runtime (ConcRT),
     statically linked (E2). The first parallel cv2 call on a thread attaches that
     thread to ConcRT, and the attach calls `SetThreadpoolWait` on the calling
     thread (E3).
   - With the port gone, `SetThreadpoolWait` raises `0xC000070A`
     `STATUS_THREADPOOL_HANDLE_EXCEPTION` (E1) on the calling thread (E4, E5).
     cv2's `catch (...)` turns it into "Unknown C++ exception" (E4). The attach
     never completes, so the next call tries again and fails again.
   - Serial cv2 calls (`fillPoly`, `getStructuringElement`, a same-size `resize`)
     never reach ConcRT, so they survive (E5, E9).
   - Inducing that state at session start reproduces both failing logs exactly:
     the same 135 failed, 2405 passed and 30 errors, the same 165 test ids, the
     same 176 faulthandler reports with the same seven innermost frames, and the
     same progress positions (E6).

   Rests on E1-E6.
2. **The trigger is a use-after-return in CPython 3.12.14's `_wmi` module, reached
   through `onnxruntime`'s import.**
   - `onnxruntime/capi/_pybind_state.py:14` calls `platform.system()`. On 3.12 that
     runs a WMI query on a worker thread. If the query is slow, the calling thread
     gives up after 100 ms + 100 ms and returns, but the worker keeps a pointer to
     a struct on the *returned* stack frame (E7).
   - When the worker finishes, it calls `CloseHandle(data->writePipe)` with whatever
     value now sits in that dead stack slot. In probes it read `0x20`, which is the
     default pool's completion port, and closed it (E8, E10). It also read `0x0`,
     the pseudo-handle `-2`, and its own correct pipe.
   - Upstream fixed exactly this in GH-134313 (gh-130727, merged to `main`
     2025-05-20) by copying the struct into the worker. The fix is in the `3.13`
     and `3.14` branches and not in `v3.12.14` (E7).

   That the 2026-10-05 incidents went this way is **[INFERRED]**, not
   observed: the logs cannot show which handle the worker closed. The inference
   rests on three things. Both logs open with a fault on that worker, during that
   query, while the main thread was still inside it (E-a, E11). The induced state
   matches every later line of both logs (E6). And the natural route to the state
   is demonstrated end to end (E8, E10). Why the query was slow (the
   `0x8007000e` the worker raised) is **unknown**.
3. **AC-3 is in state (a): reproduced.**
   - **Recipe A** (close the default pool's completion port, then call
     `cv2.dilate` on a 48x64 `uint8` array) fails 30 of 30 attempts in three
     pytest-driven batches of 10. Its negative control succeeds 30 of 30. Each batch
     of 10 takes about 3 s. It needs no GPU, no network and no load (E5).
   - **Recipe B** (the natural trigger, nudged only in timing) reaches the same
     state 3 of 3 times under `uv run` at a 300 ms delay. When driven from a pytest
     subprocess it does so only 1 to 3 times in 10, so it is a *causal
     demonstration, not a reproduction under AC-3's bar* (E8).
4. **Fix stories filed** (AC-4(a)). Both are `fix`, EPIC-01, PLANNED, and neither is
   started.
   - [[MT-069]] carries recipe A as its failing regression test. Layer:
     **production start-up**, meaning any process that imports the modules that
     call cv2. The test harness inherits the fix by importing them and needs no
     change of its own.
   - [[MT-070]] removes the trigger. Its regression test is the stable part of
     recipe B: "the abandoned `_wmi` worker closes a handle it does not own",
     seen in 21 of 21 runs on the `import onnxruntime` path (E8). Layer: **production start-up**, at the first `onnxruntime` import, *or*
     the interpreter pin that `stack.md` §2 owns. The story chooses, and a pin
     change needs `stack.md` amended.
   - **Order: MT-070 first.** It removes the stray `CloseHandle`, which can close
     *any* handle, not only the port (E10 shows the slot read three different
     values). MT-069 is defence in depth. Its planning must measure what it costs
     parallel cv2 throughput before RED. Dropping it after MT-070 lands is a PO
     decision, to be recorded in MT-069 if taken.

   The implementation is not chosen here. Two facts constrain it, and both are
   measured, not recommended:
   - `cv2.setNumThreads(0)` or `(1)` keeps OpenCV off ConcRT and survives the
     broken pool (E9).
   - Python 3.13+'s `_wmi` does not read the dead frame (E7).
5. **The shipped app is exposed [INFERRED]; how often is unknown.**
   - The app imports `onnxruntime` through `detect`, `ocr` and `clean`, on the same
     CPython 3.12.14, so it runs the same WMI query.
   - A pipeline run and a bake each start a fresh `threading.Thread`
     (`ui/run.py:84`, `ui/bake.py:69`). A thread first used after the port is lost
     fails every parallel cv2 call (E9: an already-attached thread survives, a new
     one does not).
   - A run would stop on its first page. The page's recorded reason would be
     `error: Unknown C++ exception from OpenCV code` (`pipeline/runner.py:191-193`
     formats `f"{type(error).__name__}: {error}"` **[READ]**).
   - A bake would emit `failed` with `Unknown C++ exception from OpenCV code`
     (`ui/bake.py:78-79` **[READ]**).
   - Both would repeat until the app restarts. How the UI renders those two
     messages was not checked.
   - The trigger needs a WMI connection slower than about 200 ms during start-up
     *and* the right stale value in the dead stack slot. Neither probability is
     known.
6. **Until MT-070 lands,** PO-2's interim rule in MT-068 stands. A gate failure
   with `Unknown C++ exception` and faulthandler `0xc000070a` is this bug: keep the
   log, re-run the gate alone, and cite MT-068.

## Evidence

E-a to E-g are the story's own evidence, from planning. E1 onward are this spike's.
Probes live in `spikes/MT-068/` (gitignored, unreviewed). Each is described well
enough to rewrite it.

- **E1 - what `0xC000070A` is [READ].**
  `C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared\ntstatus.h`
  (sha256 `34cdc350…d4cb`), lines 11070-11077: `MessageId:
  STATUS_THREADPOOL_HANDLE_EXCEPTION`, message text
  *"Status 0x%08x was returned, waiting on handle 0x%x for wait 0x%p, in waiter
  0x%p."*, `#define STATUS_THREADPOOL_HANDLE_EXCEPTION ((NTSTATUS)0xC000070AL)`.
  So the PO's recollection in E-b was right, and the text ties the code to a
  thread-pool *wait*.
- **E2 - OpenCV's parallel backend [READ] [MEASURED].**
  - `cv2.getBuildInformation()` in this venv: `Parallel framework: Concurrency`.
    It was built with MSVC 1944 and `/EHa` in the release C++ flags, so structured
    exceptions reach `catch (...)`.
  - The PE import table of `.venv/Lib/site-packages/cv2/cv2.pyd`
    (`probes/peimports.py`, a 60-line parser) imports no `concrt140.dll`. Its RTTI
    names include `Concurrency::scheduler_resource_allocation_error` and eight
    other ConcRT types: the runtime is statically linked.
  - It imports `CreateThreadpoolWait`, `SetThreadpoolWait`, `CloseThreadpoolWait`,
    `RegisterWaitForSingleObject`, `CreateThreadpoolTimer`, `SetThreadpoolTimer`,
    `CreateTimerQueueTimer` and `DuplicateHandle` from `KERNEL32`.
  - OpenCV 5.0.0 `parallel.cpp` (sha256 `261ddacb…26c8`): `HAVE_CONCURRENCY`
    dispatches through `Concurrency::parallel_for` (lines 608-612). It takes the
    parallel path only when `(numThreads < 0 || numThreads > 1) && range.end -
    range.start > 1` (line 551).
- **E3 - what ConcRT does on a thread's first parallel call [MEASURED].**
  - `probes/iathook.py` + `hookrun.py` redirect cv2.pyd's IAT slots for those
    imports to logging `ctypes` callbacks.
  - In a fresh process, `fillPoly` on 48x64 makes 0 calls. The first `cv2.dilate`
    of 48x64 (5x5 ellipse) makes, all **on the main thread**, `DuplicateHandle` x1,
    `CreateThreadpoolWait` x1, `SetThreadpoolWait` x1, `CreateThreadpoolTimer` x1
    and `SetThreadpoolTimer` x1. The second and third dilates make 0 calls.
  - A scaling `resize` of 1600x1125 makes 5 `CreateThread` calls. 50 x
    `connectedComponentsWithStats` of 240x320 make 7 `CreateThread` calls, on the
    main thread and on worker threads.
  - So every parallel call enters ConcRT, small ones included. A 48x64 dilate
    creates no thread (thread count 15 -> 15, `probes/dispatch.py`), but it still
    attaches the calling thread, and the attach registers a thread-pool wait.
- **E4 - an invalid wait handle gives the exact signature [MEASURED].**
  - `probes/thunk_wait.py` points cv2.pyd's `SetThreadpoolWait` slot at a 21-byte
    thunk (`mov rdx, 0x7FFC; mov rax, <real>; jmp rax`). The real function then
    receives a bogus handle, with no Python frame between it and ConcRT.
  - **always**: 3 x dilate, then a resize and a ccws, all fail with
    `cv2.error: Unknown C++ exception from OpenCV code`. faulthandler prints 6 x
    `Windows fatal exception: code 0xc000070a` under `Current thread` (the main
    thread). Interleaved `fillPoly` calls succeed, and the process lives.
  - **once** (slot restored after the first call): the first dilate fails and
    every later call succeeds.
  - So a one-off failure does not poison ConcRT. The failure persists only while
    its cause does.
  - Through a `ctypes` hook instead of the thunk, ctypes' own SEH guard catches the
    same `0xC000070A` as `OSError [WinError -1073740022]` (`tamper_wait.py`). That
    variant only proves the raise is synchronous on the calling thread.
- **E5 - recipe A: a closed pool port [MEASURED].**
  - `probes/handles.py` lists the process's handles by scanning values 4..0x8000
    with `NtQueryObject(ObjectTypeInformation)`.
  - `probes/close_one.py` closes the *n*-th handle of one type in a fresh process,
    after `import numpy, cv2`, then makes 3 dilates, a `fillPoly` and a ccws.
  - Of 15 handles tried (3 `IoCompletion`, 2 `TpWorkerFactory`, 6
    `WaitCompletionPacket`, 4 `IRTimer`), **only** the lowest-valued `IoCompletion`
    handle (`0x20`) gives the signature: 3 x `UNKNOWN`, `fillPoly` ok, ccws
    `UNKNOWN`, 4 x `0xc000070a`. Every other closure leaves cv2 working.
  - `spikes/MT-068/repro/test_repro.py` is two pytest tests, each running 10 fresh
    `sys.executable` subprocesses. One closes that handle and then dilates a 48x64
    `uint8` array; the other only dilates.
  - Three runs (`uv run pytest -q -s -p no:cacheprovider spikes/MT-068/repro/test_repro.py`):
    induced **10/10, 10/10, 10/10** `UNKNOWN`; control **10/10, 10/10, 10/10** ok.
    Each batch of 10 took 2.7-3.2 s.
  - That the handle is the *default* pool's port is **[INFERRED]**: it is the
    lowest-valued completion port, it exists from interpreter start, and it is the
    only one whose loss breaks `SetThreadpoolWait`.
- **E6 - the induced state reproduces both logs line for line [MEASURED].**
  - `plugins/closeport.py` is loaded with `-p` from outside the repo, with
    `PYTHONPATH` set to `spikes/MT-068/{plugins,probes}`. At load it closes that
    handle (`0x20`).
  - Command: `uv run pytest -q -p no:cacheprovider -p closeport tests/core tests/ui`,
    15:51-15:53 UTC. Result: **135 failed, 2405 passed, 30 errors** in 139 s.
  - The sorted 165 FAILED/ERROR ids are byte-identical to both incident logs'.
    There are **176** `Windows fatal exception: code 0xc000070a` reports, each under
    `Current thread`.
  - Their innermost-frame tally is identical to both logs' (72 `_bake_world.py:112`,
    38 `mask.py:61`, 22 `postprocess.py:164`, 20 `postprocess.py:340`, 20
    `inpaint.py:83`, 3 `postprocess.py:256`, 1 `test_clean_inpaint.py:187`).
  - The progress prefix before each report (the run of `.FE` characters) is
    identical in sequence too, beginning `............` (12 passes, then the first
    failure).
  - **The one difference:** this run has no opening `0x8007000e` report.
    Collection still ran the WMI query (onnxruntime's import), but nothing
    faulted in it.
- **E7 - the `_wmi` use-after-return [READ] [MEASURED].**
  - CPython `v3.12.14` `PC/_wmimodule.cpp` (sha256 `07d00d99…3727`):
    - `_wmi_exec_query_impl` keeps `struct _query_data data` on its own stack
      (line 249) and passes `&data` to `CreateThread` (275). It waits 1000 ms for
      `initEvent` and 100 ms for `connectEvent` (291, 293), then 100 ms for the
      thread (321).
    - On timeout it closes `initEvent` and `connectEvent` (345-346) and *returns*.
      The worker holds `struct _query_data *data` (line 60) and, after the main
      thread has gone, does `SetEvent(data->connectEvent)` (108) and finally
      `CloseHandle(data->writePipe)` (203).
  - `3.13` (sha256 `ea7fa4ff…`), and `3.14` and `main` (both `9141dd0d…`), have
    `_query_data data = *(struct _query_data*)param;` at line 60, which is a copy.
    `gh api` on python/cpython: commit `e4fbfb1288` *"GH-130727: Avoid race
    condition in _wmimodule by copying shared data (GH-134313)"*, merged to `main`
    2025-05-20T21:21Z. Issue gh-130727 is the flaky `test_wmi_query_error`.
  - `stack.md` §2 pins CPython 3.12 (`requires-python = ">=3.12,<3.13"`).
- **E8 - recipe B: the natural route, timing-nudged [MEASURED].**
  - `probes/wmi_ort.py` redirects `_wmi.pyd`'s IAT entries for `SetEvent` and
    `CloseHandle` to Python callbacks. The callbacks record, for each worker-thread
    `CloseHandle`, the handle's object type *before* closing it. On the worker's
    2nd `SetEvent` (`connectEvent`) the callback sleeps *D* ms, once, which stands
    in for a slow `ConnectServer`.
  - The script then runs `import onnxruntime`, which reaches the query through
    `_pybind_state.py:14`, as in E-a. It waits *D* + 1.5 s, then checks the port
    and one dilate.
  - Under `uv run`, 3 runs per *D*:

    | *D* (ms) | worker's stale `CloseHandle` | port closed, dilate `UNKNOWN` |
    |---|---|---|
    | 150 | own pipe (not abandoned) x3 | 0/3 |
    | 200 | `0x20` x1, own pipe x2 | 1/3 |
    | 250 | `0x20` x1, `0x0` x1, own pipe x1 | 1/3 |
    | 300 | `0x20` (IoCompletion) x3 | **3/3** |
    | 350 | `0x20` x2, `0x0` x1 | 2/3 |
    | 400, 450, 500, 1000 | `0x0` x12 | 0/12 |
  - `spikes/MT-068/repro/test_natural.py` runs the same script 10 times from pytest
    (`sys.executable`, not `uv run`). At *D* = 300 it gave 3/10, then 1/10. At 270
    it gave 1/10, and at 330 and 360, 0/10. The control (*D* = 0, hook installed)
    gave 10/10 ok.
  - So the stale value depends on what the main thread is executing when the
    worker wakes. That is deterministic enough to repeat under one launcher, and
    not reliable across launchers.
  - What is far more stable is whether the worker closes the *wrong* handle at
    all, as distinct from closing the port. When the query is reached through
    `import onnxruntime` and *D* ≥ 300, the abandoned worker closed a handle that
    was not its pipe in 21 of 21 runs: 18 under `wmi_ort.py` and 3 in E10. That is
    MT-070's regression signal.
  - It is not unconditional. In `probes/wmi_delay.py`, the main thread calls
    `_wmi.exec_query` directly and then does nothing. There the dead slot still
    held the correct pipe value (2 of 2, *D* = 400 and 1300). So the signal
    depends on the main thread's work after the timeout, and the test must
    include it.
- **E9 - containment and thread scope [MEASURED].**
  - `probes/port_then.py`: with the port closed, `cv2.setNumThreads(0)` or `(1)`
    before the calls makes dilate, resize and ccws all succeed with no fault
    report. This matches E2's line 551.
  - With the port closed, `_wmi.exec_query` returns `OSError(258)` (timeout) in
    104 ms. `platform.system()` and `import onnxruntime` still succeed, and cv2
    stays broken.
  - `probes/attach_first.py`: if the main thread attaches (one call of each kind)
    *before* the port is closed, its later calls succeed. A new `threading.Thread`
    started afterwards fails all three, with `0xc000070a` x4.
  - `probes/survivor.py`: in a fresh process, a same-size `resize`
    (512x1024 -> 1024x512) makes 0 ConcRT thread-pool calls. With the port closed,
    it succeeds while a scaling resize of the same page fails. OpenCV 5.0.0
    `resize.cpp:4247-4251` (sha256 `e4610736…26c8`) is `if (dsize == ssize) {
    src.copyTo(dst); return; }` **[READ]**.
- **E10 - the same trigger inside a real gate collection [MEASURED].**
  - `plugins/wmidelay.py` installs E8's hook in a real
    `pytest -q -p no:cacheprovider -p wmidelay tests/core tests/ui` collection. At
    `pytest_collection_finish` it waits, checks the port and one dilate, then calls
    `pytest.exit`. Three runs, 15:57-16:00 UTC:
    - `connectEvent` + 300 ms: the worker called `CloseHandle(0x20)` while it was
      still an `IoCompletion`, so the port was gone and dilate gave `UNKNOWN`. The
      same worker had first called `SetEvent(0x508)`, an event the main thread had
      closed and whose number had since been reused by a `File`.
    - `connectEvent` + 1000 ms: `CloseHandle(0x0)`, and `SetEvent` on a reused
      `Mutant` handle. The port survived.
    - `initEvent` + 1300 ms: `CloseHandle(0xfffffffffffffffe)` (the current-thread
      pseudo-handle), and `SetEvent` on a closed handle. The port survived.
- **E11 - reading of the preserved logs [MEASURED].**
  - Both logs have 177 `Windows fatal exception` lines: 1 x `0x8007000e` at line
    7, then 176 x `0xc000070a`.
  - The `0x8007000e` dump lists the main thread as `Thread 0x…` (not *Current*),
    with its stack in `platform._wmi_query` <- `_get_machine_win32` <- … <-
    `onnxruntime\capi\_pybind_state.py:14` <- `clean\session.py:30`. So the fault
    was on a thread with no Python state, the `_wmi` worker, while the main thread
    was still inside the query. This agrees with audit W1.
  - Every `0xc000070a` dump is `Current thread` with the main thread's id (`0x2e50`
    in run 1, `0x710c` in run 2).
  - The FAILED/ERROR id sets of the two runs are byte-identical (165 ids). Run 1
    took 687 s with concurrent load and run 2 took 317 s without, so load changed
    the timing but not the set.
- **E12 - AC-1, the W8 method [MEASURED].**
  - `plugins/cvraise.py` (`-p cvraise`, loaded from outside the repo) replaces
    `cv2.dilate`, `cv2.resize`, `cv2.connectedComponentsWithStats` and
    `cv2.connectedComponents` (the four functions E-b names) with wrappers that
    raise `cv2.error("Unknown C++ exception from OpenCV code")`.
  - Under the `unit` command, 15:37-15:40 UTC: **136 failed, 2404 passed,
    30 errors**. That is the incident's 165 ids plus exactly one,
    `test_detect_postprocess.py::test_a_page_wider_than_it_is_tall_is_padded_top_and_bottom`.
    That test's only cv2 call is the same-size resize of E9.
  - With the wrapper passing same-size resizes through (`CVRAISE_SKIP_IDENTITY=1`),
    16:04-16:06 UTC: **135 failed, 2405 passed, 30 errors**, with ids
    byte-identical to both logs.

## AC-1 - the failing set

- **The literal control (patch the four E-b functions) gives 136F/30E, not
  135F/30E [MEASURED, E12].** "Every call to these four functions fails" is
  therefore refuted, by exactly one test.
- **"Every call that dispatches to the parallel backend fails" holds.** Patching
  only the calls that reach ConcRT gives exactly 135F + 30E with the same ids
  (E12), and so does the induced state itself (E6).
- **The survivor set, for both 2026-10-05 runs, is one test:**
  `test_a_page_wider_than_it_is_tall_is_padded_top_and_bottom`. It survived because
  its page is already 1024 wide, so `letterbox`'s `cv2.resize` is same-size, and
  OpenCV copies instead of calling `parallel_for_` (E9).
- **2026-09-29 (34 = 35 - 1, audit W8):** that survivor is in
  `test_detect_postprocess.py`, so it is very likely the same test. This is
  **[INFERRED]**: that log is lost.
- **2026-09-28 and 2026-10-02:** logs lost, not checked.

## AC-2 - the readings

- `0xC000070A` is `STATUS_THREADPOOL_HANDLE_EXCEPTION` [READ, E1].
- The backend is the Concurrency Runtime, statically linked [READ, E2]
  (`Parallel framework: Concurrency`).
- It can raise that status. Its per-thread attach calls `SetThreadpoolWait` on the
  calling thread [MEASURED, E3], and `SetThreadpoolWait` raises `0xC000070A`
  synchronously when its wait cannot be armed [MEASURED, E4, E5].
- That this is the raise site in the incidents is [INFERRED] from E6's exact match.
  The exception record's parameters (status and handle, per E1's message text)
  were not captured in either log.

## Hypotheses

| | Verdict | Why |
|---|---|---|
| H1 broken pool/scheduler state for the process lifetime | **Stands, refined.** The state is the default pool's lost completion port, not a poisoned ConcRT. A single failed attach recovers (E4 *once*). | E4-E6 |
| H2 transient early fault, the running process breaks | **Stands.** The transient is a slow WMI connection during collection. It becomes permanent because it ends in a stray `CloseHandle`. | E7, E8, E10, E11 |
| H3 the `onnxruntime-gpu` import consumes or corrupts the resource | **Refuted as stated; ORT is only the caller.** Its import runs `platform.system()`, and any 3.12 process doing that is exposed. ORT's DLLs were not needed to break cv2 (E5 closes the port with ORT never imported). | E5, E8 |
| H4 machine-level state (AMSI, Game Bar) | **Not needed for the mechanism; untested as a cause of WMI slowness.** | - |
| H5 a specific earlier test leaves cv2 broken | **Refuted.** The state exists before the first test. Inducing it at plugin load reproduces the exact set. | E6, E11 |

## What would have to be true for this to be wrong

- That something other than the lost port made `SetThreadpoolWait` fail in the
  incidents, with the same per-thread persistence. E6 matches every line except the
  opening one, but the exception record's status and handle were never captured.
- That the stray close in the incidents came from somewhere other than the `_wmi`
  worker. Nothing else is known to close handles it does not own, but this was not
  searched for.
- That handle `0x20` being the pool's port is particular to these probe processes.
  It was `0x20` in every gate-shaped process observed (E6, E10) and `0x24` or
  `0x28` in a few probe processes (E8).

## What was not checked

- Why the WMI connection was slow, or what raised `0x8007000e` on the worker
  (audit W2-W4 tried commit pressure and never produced it).
- The frozen PyInstaller build: it should bundle the same `_wmi.pyd`, but that
  was not opened.
- How the app's UI renders the run reason and the bake `failed` message.
- What else in the app uses the default thread pool and would fail or hang
  without its port (COM, RPC and Qt were not probed).
- `0x8007000e`/`0xc000070a` on CI's `windows-latest`. The same interpreter is used
  there, so it is exposed [INFERRED]. Whether its WMI is ever slow enough is not
  known.
- The 2026-09-28 and 2026-10-02 incidents (logs lost).

## Spike code

`spikes/MT-068/` is gitignored, **unreviewed and not production code**. It holds
`probes/` (`peimports`, `iathook`, `hookrun`, `dispatch`, `tamper_wait`,
`thunk_wait`, `handles`, `close_one`, `port_then`, `attach_first`, `survivor`,
`wmi_delay`, `wmi_ort`), `plugins/` (`cvraise`, `closeport`, `wmidelay`),
`repro/` (`test_repro.py`, `test_natural.py`), `src/` (the fetched upstream
sources, with the sha256s above), `work/` (run logs, id lists, frame tallies) and
`logs/` (the preserved incident logs, untouched).

A later story may take the **recipes**, re-derived as tests:

- recipe A: close the lowest-valued `IoCompletion` handle, then make a parallel cv2
  call in a fresh subprocess;
- recipe B's stable signal: delay the `_wmi` worker past the main thread's
  timeouts, import `onnxruntime`, then check what the worker closes.

It must re-derive its own handle enumeration and IAT patching rather than copying
these files.

Known shortcuts:

- `iathook.py`'s ctypes callbacks swallow SEH, so tampering must use the thunk.
- `handles.py` scans handle values rather than enumerating handles.
- Every probe assumes x64 and `cv2.pyd`/`_wmi.pyd` module names.

## Stories filed

- [[MT-069]] - *Parallel cv2 calls survive a lost thread-pool completion port*
  (fix, EPIC-01): recipe A as the regression test, layer production start-up
  (Decided 1, 3, 4).
- [[MT-070]] - *An abandoned WMI query closes no handle it does not own* (fix,
  EPIC-01): the trigger, layer production start-up or the interpreter pin (Decided
  2, 4).
