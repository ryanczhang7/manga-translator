# Qt access violation under the `coverage` gate - 2026-10-21

**Finding: not reproduced in 51 runs; cause not established.** The crash
reported at `tests/ui/test_cost_estimate.py:550` is not specific to that file.
It is the third kept instance of one intermittent native crash that MT-073 met
first, and every instance dies inside a Qt event flush in whichever UI test next
pumps events. Nothing below shows what is being freed or touched.

## What the kept logs show

`.claude/state/gate-logs/kept/` in the main checkout holds three crash logs,
all from gate `coverage`, none from `unit`, `coverage-core` or `integration`.
All four of those gates keep `Windows fatal exception` logs (`project.conf`,
`keep-when`):

| Kept log | Tree | Innermost Python frame |
|---|---|---|
| `coverage.000001.20261016T155521Z.log` | `c506a2f` (MT-073 GREEN) | `tests/ui/test_canvas_keys.py:70` `_settle` → `processEvents` |
| `coverage.000002.20261016T160241Z.log` | `c506a2f` (MT-073 GREEN) | `pytestqt/plugin.py:220` `_process_events`, in `pytest_runtest_setup` |
| `coverage.000003.20261020T172143Z.log` | `d697dfb` (MT-084 RED) | `tests/ui/test_cost_estimate.py:550` `_painted_cost_frame` → the first `QApplication.processEvents()` after `waitExposed` |

Each is `Windows fatal exception: access violation` followed by
`Segmentation fault` (exit 139), with no Python frame above the event flush.
So the fault is in C++ code that runs during event processing (a paint, a
deferred delete, a timer), not in test code that reads a deleted object. The
site moves between files: MT-073 also saw `test_chapter_summary` and
`test_folder_intake`, and a `Fatal Python error: Aborted` (exit 3). Every site
sorts after `tests/ui/test_canvas_high_contrast.py`.

`_painted_cost_frame` itself does nothing unusual: it builds a window, holds a
strong reference (the caller keeps `_window`), shows it, flushes events twice
and calls `window.grab()`. It opens no `QPainter`, and no widget is torn down
before the flush that crashed. The crash happened before the grab.

## Prior measurement (MT-073, `## Notes`)

- GREEN: the full `coverage` command crashed **4 of 10**, while the `unit`
  command passed 4 of 4. Configurations that ran the `stage` tests'
  `QScreen.grabWindow` (in `test_canvas_high_contrast.py`, `_on_screen`, the
  only `grabWindow` in `tests/` or `src/`) crashed about 40%. Configurations
  without them crashed **0 of 13**. This was recorded as a reading, not a
  proof.
- PO-6 and GATES then ran it clean 12 times in a row (3 full runs, 8 narrowed
  runs, and the GATES run). MT-084 then hit the third instance on 2026-10-20.

## Repro attempts, this audit

Worktree `kind-visvesvaraya-2d46f1` at `484df9c`, fresh `uv sync`, each run a
separate process with `-p no:cacheprovider`, using the gate's `--cov` flags,
run back to back on one machine. Script and results are in the session
scratchpad (`repro.sh`, `runs/results.tsv`), not committed.

| Configuration | Runs | Crashed |
|---|---|---|
| `tests/ui/test_cost_estimate.py` alone, under `--cov` | 20 | 0 |
| `test_canvas_high_contrast`, `test_canvas_keys`, `test_chapter_summary`, `test_cost_estimate`, under `--cov` | 15 | 0 |
| the gate's exact command, `tests/core tests/ui` (3820 passed) | 8 | 0 |
| the same, `--ignore=tests/ui/test_canvas_high_contrast.py` (3763 passed) | 8 | 0 |

The two subset runs exit 1 only on `--cov-fail-under=90` over a partial suite.
All 55 and 205 tests passed every time. The full runs alternated with and
without the high-contrast file, to spread drift over both arms.

**0 crashes in 51.** At MT-073's measured 40%, 8 clean full runs would happen
by chance about 1 time in 60 (0.6^8), so the rate today is very likely lower. Its
cumulative record since then is 1 crash in roughly 30 known full coverage runs.
Thirty is a floor on the denominator, since ordinary gate passes are not
counted anywhere. With no crash in either arm, these runs cannot confirm or
refute the `grabWindow` reading.

## What the evidence does and does not support

- **Supported:** one recurring native fault inside Qt event processing, seen
  only under `--cov`, only with `tests/core` running first (MT-073: `tests/ui`
  alone passed 3 of 3), and at a site that moves. The test named in the report,
  `test_cost_estimate.py`, is where the crash surfaced, not shown to be its
  source.
- **Not supported:** any specific cause. That includes the `grabWindow`
  instrument, GC timing under the coverage tracer, and paint-time teardown.
  faulthandler gives only Python frames, and every frame here ends at the
  boundary where the interesting part begins.

## Recommended next step

No fix story yet: a fix chosen now would be a guess. The cheapest step that
turns the next occurrence into evidence is a **native crash dump**:

1. Enable Windows Error Reporting LocalDumps for `python.exe`
   (`HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\python.exe`,
   `DumpType=2`, `DumpFolder` somewhere outside the repo). This is a machine
   setting, so the user makes it, not an agent.
2. On the next `Windows fatal exception: access violation` in a kept coverage
   log, open the dump with PySide6/Qt symbols and read the faulting C++ frame
   (`QWidgetRepaintManager`, `QCoreApplication::sendPostedEvents`/
   `DeferredDelete`, the offscreen platform's backing store, and so on). That
   frame tells you which object was freed, and what kind of story to write.
3. Until then, a crash with this signature is a rerun, as it is today. The
   `keep-when` retention already keeps every instance.

If someone wants a fix without a dump, the only lead with any measurement
behind it is MT-073's `grabWindow` reading. A story could replace
`_on_screen`'s `QScreen.grabWindow` with a backing-store read that does not go
through the platform screen. Its success condition would have to be a crash
rate measured over enough full runs to tell 1-in-30 from zero, which is
roughly 100. That costs about 7 hours of machine time, so the dump comes first.
