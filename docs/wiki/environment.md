# Environment

*What to install on a fresh machine to run this project's gates, and how to
verify it. Written by `/setup-environment` on 2026-09-12 against
`docs/wiki/stack.md` and the `python-uv-pyside6` stack profile.*

**Status: done on the development machine, 2026-09-12.** `uv` 0.12.13 and
CPython 3.12.14 are installed, and **since MT-001 landed the project itself is
installed too** — `uv sync --all-extras` resolves 35 packages against a committed
`uv.lock`. `scripts/doctor.sh` reports the project toolchain `ok` and four of
five *test discovery* checks passing.

**The fifth, `providers`, reports `MISSING` and is expected to.** It runs
`uv run python -c "import onnxruntime ..."`, and **no inference runtime is
pinned**: MT-001's sizing rule forbids adding a dependency nothing imports, and
the ONNX-versus-PyTorch question belongs to the MT-002 spike. The check is kept
rather than deleted so that it exists the moment the dependency does. **MT-002
owns turning it green.** Recorded as PO-2 in `docs/backlog/stories/MT-001.md`.

Everything the gates need beyond `uv` is installed *by* `uv`, into the project.
Nothing else goes on the system.

---

## 1. Required

The stack is Python 3.12 + `uv` + PySide6 + ONNX Runtime. Almost none of it is a
system install: every gate command in `.claude/harness/project.conf` begins
`uv run`, which resolves to the project's own virtual environment. So the
system-level requirement list is short.

| Tool | Version | Why — which gate or task needs it | Scope |
|---|---|---|---|
| `git` | any recent | the harness itself; `check-boundaries.sh` | system |
| `bash` | 5.x | every harness script | system (Git for Windows) |
| **`uv`** | **0.12.x** | **every gate and task** — `format`, `lint`, `typecheck`, `unit`, `coverage`, `coverage-core`, `integration`, `build`, and the `install`/`dev`/`test` tasks all invoke `uv run` | **system — the only thing you must install** |
| CPython | 3.12.x | the interpreter the project runs on | **project — installed and pinned by `uv`, not by you** |
| NVIDIA driver | ≥ 566 for Blackwell / sm_120 | the CUDA execution provider used by detection, OCR and inpainting (MT-002, MT-007, MT-010, MT-019) | system — **already present** |
| Everything else | per `uv.lock` | ruff, mypy, pytest, coverage, import-linter, PySide6, onnxruntime, PyInstaller | project — `uv sync` |

**Do not install Python system-wide.** `uv` downloads and manages its own
CPython, and that is deliberate here rather than incidental — see the Store-alias
note in §5. Installing a system Python is not harmful, but it is not needed and
it reintroduces a trap.

## 2. What is already present on this machine

Measured 2026-09-12 on the development machine (Windows 11 Home 10.0.26200,
Ryzen 5 7600X, 32 GB RAM):

| Check | Result |
|---|---|
| `git` | `/mingw64/bin/git` — present |
| `bash` | 5.3.15 — present |
| `winget` | present |
| **GPU** | **NVIDIA GeForce RTX 5070, 12227 MiB, driver 591.86** — comfortably above the sm_120 floor; no CUDA Toolkit install is needed, ONNX Runtime ships its own CUDA libraries |
| `uv` | **0.12.13** — installed 2026-09-12 via `winget`, at `AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe` |
| CPython | **3.12.14** — uv-managed, at `AppData\Roaming\uv\python\cpython-3.12.14-windows-x86_64-none\python.exe` |
| `python` / `python3` (system) | **not real** — the Microsoft Store alias shim only, and deliberately still that way; see §5 |
| `py` launcher | not present |
| `scoop` | not present |

## 3. Install

**One command.** *(Already run on the development machine on 2026-09-12, at the
user's request. This section is for the next machine.)*

```bash
winget install --id astral-sh.uv --exact --source winget
```

`astral-sh.uv` 0.12.13 is available from the `winget` source as of 2026-09-12.

Then **open a new shell** — see §5 on PATH — and let `uv` fetch the interpreter:

```bash
uv python install 3.12
```

That is the whole system-level setup. The project's own dependencies are
installed by:

```bash
uv sync --all-extras
```

…which is the `install` task (`bash scripts/task.sh install`). **Since MT-001 it
works**: `pyproject.toml` and a committed `uv.lock` exist, and the sync resolves
35 packages and installs the project itself in editable form. Measured
2026-09-12: 25 s cold, under a second warm.

## 4. Verify

Run each of these after installing. The expected output shape is what matters,
not the exact version.

```bash
uv --version
```
→ `uv 0.12.x (...)`. If this says "command not found", it is the PATH issue in §5.

```bash
uv python list --only-installed
```
→ at least one `cpython-3.12.*` entry with a real path under
`AppData\Roaming\uv\python\`. An empty list means `uv python install 3.12` has
not run.

```bash
nvidia-smi --query-gpu=name,driver_version --format=csv
```
→ `NVIDIA GeForce RTX 5070, 591.86`. Already true on this machine.

Then the harness's own check, which is the real gate:

```bash
bash scripts/doctor.sh
```

→ every line under *Project toolchain* reads `ok`. Since MT-001, four of the five
*Test discovery* lines read `ok` too. The fifth, `providers`, reads `MISSING`
and is **expected to until MT-002** — see the status note at the top of this
file. Do not "fix" it by installing an inference runtime; choosing one is the
spike's decision.

```bash
bash scripts/gates.sh --list
```

→ the nine gates from `stack.md` §"Gates", with the commands matching. This
lists them; it does not run them.

## 5. Notes — the things that will otherwise cost an hour

### The Windows Store Python alias — measured, not folklore

**Measured 2026-09-12 on this machine, in Git Bash:**

```
$ command -v python
/c/Users/ryanc/AppData/Local/Microsoft/WindowsApps/python
$ python --version
Python was not found; run without arguments to install from the Microsoft
Store, or disable this shortcut from Settings > Apps > Advanced app settings >
App execution aliases.
$ echo $?
49
```

There is no Python on this machine. `python` and `python3` both resolve to the
Microsoft Store *app execution alias* — a stub that prints that message and
exits **49** without running anything. It is on `PATH`, so `command -v python`
finds it, which is why a naive "is Python installed?" check passes on a machine
that has no Python.

**Why it does not bite the gates:** every gate command begins `uv run`, which
executes the project venv's interpreter by absolute path. The word `python`
appears in exactly one place that matters — the `providers` discovery check in
`doctor.sh`, as `uv run python -c "import onnxruntime ..."` — and that is `uv
run python`, the venv's, not the shim's.

**Where it will bite you:** typing `python`, `pip` or `python -m` by hand in a
shell. It will exit 49 and the message will suggest installing from the Store.
Do not. Use `uv run python` instead. If you would rather remove the trap
entirely, the aliases can be turned off at *Settings → Apps → Advanced app
settings → App execution aliases*; that is a preference, not a requirement, and
nothing in this project depends on it either way.

*(This is also why `.claude/harness/rules.md` forbids Python in harness scripts.
The rule is about harness scripts in bash; it does not constrain the project
stack, which is Python by choice.)*

### PATH after `winget install`

**Measured 2026-09-12, immediately after the install on this machine.** `winget`
reported `Path environment variable modified; restart your shell to use the new
value`, and that is exactly what happened — an already-open shell keeps the
environment it was started with, and so does every process that shell spawns:

```
$ command -v uv
(not found)
$ bash scripts/doctor.sh
  MISSING  uv           needed for: gate 'format'
```

…while a process started with the refreshed user `PATH` found it immediately:

```
$ export PATH="/c/Users/ryanc/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
$ uv --version
uv 0.12.13 (0ebbd9274 2026-09-10 x86_64-pc-windows-msvc)
$ bash scripts/doctor.sh
  ok       uv           .../astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uv
```

So: **after installing `uv`, restart the shell — and restart the editor or agent
session too**, because it hands its own stale environment to every command it
runs. `doctor.sh` reporting `MISSING uv` on a machine where `uv --version` works
in a fresh terminal means this and nothing else.

Note the location, which is not where the winget docs suggest: this install put
`uv.exe` in the **package** directory and added *that* to the user `PATH`, rather
than dropping a shim in `AppData\Local\Microsoft\WinGet\Links`. That directory
does not exist on this machine. Do not hard-code either path anywhere; use
`uv` from `PATH`.

**Measured again on 2026-09-12 during MT-001, and this is the shape it takes in
an agent session.** The persisted user `PATH` was already correct —

```
$ powershell -NoProfile -Command "(Get-ItemProperty HKCU:\Environment -Name Path).Path -split ';' | ? { $_ -like '*uv*' }"
C:\Users\ryanc\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe
```

— while every shell the session spawned still had the pre-install environment,
so `uv --version` said `command not found` and `doctor.sh` said `MISSING uv`. The
registry is the ground truth; a running session's environment is a snapshot of
when it started. **The fix is to restart the session.** The stop-gap MT-001 used
was prefixing each command with

```bash
export PATH="/c/Users/ryanc/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
```

which works because child processes inherit it — but it is a stop-gap for one
stale session and not a thing to write into a script. Nothing in the repository
hard-codes that path.

### `uv python install` reports an error that is not one

**Measured 2026-09-12.** `uv python install 3.12` downloaded CPython 3.12.14 and
then printed:

```
error: Missing expected target directory for Python minor version link at
  C:\Users\ryanc\AppData\Roaming\uv\python\cpython-3.12.14-windows-x86_64-none
warning: Failed to inspect Python interpreter from managed installations at
  `...\cpython-3.12-windows-x86_64-none\python.exe`
```

The interpreter itself installed correctly. What failed is the *minor-version
alias* — the `cpython-3.12-...` directory link that lets `3.12` resolve without a
patch number — which on Windows needs symlink privilege (Developer Mode, or an
elevated shell). Verified that nothing downstream is affected:

```
$ uv python find 3.12
C:\Users\ryanc\AppData\Roaming\uv\python\cpython-3.12.14-windows-x86_64-none\python.exe
$ uv venv --python 3.12 <scratch>
Using CPython 3.12.14 interpreter at: ...
$ <scratch>/Scripts/python.exe -c "import sys; print(sys.version)"
3.12.14 (main, Sep  1 2026, 14:17:39) [MSC v.1944 64 bit (AMD64)]
```

Resolution and venv creation both work, so `uv sync` and every `uv run` gate will
work. Treat this message as noise unless something downstream actually fails. If
it ever does, enabling Developer Mode (*Settings → System → For developers*) and
re-running `uv python install 3.12` is the fix — not tried here, because nothing
needed it.

### CUDA

No CUDA Toolkit install is required. `onnxruntime-gpu` ships the CUDA and cuDNN
libraries it needs in its wheel; what must come from the system is the **driver**,
and 591.86 is far newer than the sm_120 floor the RTX 5070 needs. If the CUDA
execution provider nevertheless fails to load during MT-002, the stack's
documented fallback order is CUDA → DirectML → CPU, and DirectML needs only a
DX12 GPU and no toolkit at all. Record what MT-002 actually measures; do not
amend this section from expectation.

### Headless / CI

PySide6 needs a display. On a machine or runner without one, set
`QT_QPA_PLATFORM=offscreen`. The `ui` tests are written to run under it; the
`integration` gate is marked optional precisely because it needs a GPU and a
network that CI does not have.

### The `integration` gate needs a checkout that has `spikes/`

The integration suite's inputs — the page scans and the model weights — live
under `spikes/**`, which `.gitignore` covers, deliberately and permanently: they
are a non-redistributable scan of a commercial release and a GPL-3.0 model's
weights. **A git worktree shares `.git` and not the ignored working files, so a
worktree never carries them** — and this harness dispatches its agents into
`.claude/worktrees/**`. So the default condition of an agent running
`bash scripts/gates.sh` here is that 25 of the suite's 26 tests skip at call
time. CI is in the same position, for the same reason.

That is no longer a silent `PASS`. Since MT-037, `integration` carries a
`floor` of 26 and a `skipped-when` line in `.claude/harness/project.conf`, so
such a run reports **`KNOWN`** (exit 0) when nothing is leaning on the gate and
**`BLOCKED`** (exit 3) when a story escalated it through `required_gates`. Read
either as *this checkout cannot answer that question* — it is a declared
non-result, not a failure and not a pass.

To actually get an answer, run the gate from a checkout that has `spikes/`
(normally the main checkout rather than a worktree):

```bash
bash scripts/gates.sh --gate integration   # expect: PASS integration (…, observed 26, floor 26)
```

Copying or symlinking `spikes/` into the worktree works too. What does not work
is committing it; see MT-037 `## Out of scope`. This is step 2 of the BLOCKED
playbook — supply what the environment lacks — and not step 3: quoting a CI log
would certify nothing here, because CI is the weaker machine.

### Installer signing

Not an environment prerequisite, but it lands in MT-024: an unsigned PyInstaller
`.exe` will raise a SmartScreen warning on first run, including on this machine.
Code signing is not currently budgeted or decided.

## 6. Optional

| Tool | Needed for | Skippable? |
|---|---|---|
| `mutmut` | the `mutation` gate and `/audit-mutations` | **Yes.** Optional gate, installed by `uv sync --all-extras` when it exists; never blocks a story |
| CUDA execution provider | the `integration` gate's `gpu`-marked tests, and real-speed inference | **Yes for the gates** — `integration` is optional and CI skips it. **No for actually using the app** at usable speed |
