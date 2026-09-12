# Profile: python-uv-pyside6

Python 3.12+ managed by `uv`, with a PySide6 (Qt 6) desktop interface and
optional local ONNX Runtime inference. For Windows desktop applications that
ship as a frozen binary.

It **extends `python-uv`** — read that file too; what it says about
`pyproject.toml`, fixtures and `hypothesis` all still applies. What is added
here is the part it does not cover: a Qt GUI under test, a frozen-binary build
gate, and local GPU inference that CI cannot run. The gate table below is
complete, so this file can be copied into a `project.conf` on its own.

Written for the manga-translator project; `docs/wiki/stack.md` there is the
worked instance.

**UNVERIFIED.** Nothing here has been executed. The bootstrap story runs each
command, observes it fail on purpose, and corrects this file.

## Gate commands for project.conf

    gate | format        | optional | . | uv run ruff format --check .
    gate | lint          | required | . | uv run ruff check . && uv run lint-imports
    gate | typecheck     | required | . | uv run mypy src
    gate | unit          | required | . | uv run pytest -q tests/core tests/ui
    gate | coverage      | required | . | uv run pytest -q tests/core tests/ui --cov=src/<pkg> --cov-report=term-missing --cov-fail-under=90
    gate | coverage-core | required | . | uv run pytest -q tests/core --cov=src/<pkg>/domain --cov-report=term-missing --cov-fail-under=100
    gate | integration   | optional | . | uv run pytest -q tests/integration -m "gpu or network"
    gate | build         | required | . | uv run pyinstaller --noconfirm packaging/<app>.spec
    gate | mutation      | optional | . | uv run mutmut run

    task | install | - | . | uv sync --all-extras
    task | dev     | - | . | uv run python -m <pkg>.app
    task | test    | - | . | uv run pytest -q tests/core tests/ui

**Two coverage gates, deliberately.** The pure packages — the ones holding the
product's rules rather than Qt event plumbing and ONNX session setup — have no
excuse for an untested line and carry 100%; the rest carries 90%. The
alternative, one gate at 100% with liberal `# pragma: no cover`, was rejected
because a pragma is invisible in the gate output and a second gate is not.

## Evidence of work

    # UNVERIFIED - correct these against real output in the bootstrap story.
    evidence | format        | [1-9][0-9]* files? (already formatted|would be reformatted)
    evidence | lint          | Contracts: [1-9][0-9]* kept
    evidence | typecheck     | Success: no issues found in [1-9][0-9]* source file
    evidence | unit          | [1-9][0-9]* passed
    evidence | coverage      | [1-9][0-9]* passed
    evidence | coverage-core | [1-9][0-9]* passed
    evidence | integration   | [1-9][0-9]* passed
    evidence | build         | Building EXE from|completed successfully

**One honest gap, and do not close it by deleting the requirement.** The `lint`
regex proves *import-linter* did work. It proves nothing about `ruff`, which
prints `All checks passed!` and exits 0 over an empty tree — the canonical
vacuous pass — and has no reliable clean-run file count on stdout. Close it with
the `discovery` line in §5, not by hoping.

## What `--fast` should leave out

    slow | build       | PyInstaller freezes an interpreter and the bundled data; minutes
    slow | integration | loads real .onnx models onto the GPU and may call a paid API
    slow | mutation    | mutmut re-runs the suite once per mutant

Both coverage gates stay **in** the fast subset. The instrumented run is the one
that judges the story; keeping it out of RED and GREEN is exactly how a suite
reaches CI never having been measured under it.

## 1. Every command goes through `uv run`

This is the whole Windows story and it is not optional.

A bare `python`, `python3` or `pytest` on Windows hits the Microsoft Store App
Execution Alias, which exits 49 without running anything. Gate commands from
`project.conf` execute through bash, so the shim is one bare word away — in a
gate command, in a `discovery` line, in a CI step, and inside a pipe.

    uv run python -c "import onnxruntime"     # correct
    python -c "import onnxruntime"            # exits 49, silently

`uv` is a standalone binary on `PATH` and `uv run` resolves the project venv's
interpreter directly. `py -3` is also correct on Windows but does not exist on
a Linux CI runner, so do not use it in anything CI runs.

## 2. Testing a Qt GUI

    QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui

`pytest-qt` drives widgets; the `offscreen` platform plugin means no display is
needed, so GUI tests run on CI like any other. Set it in `pyproject.toml` under
`[tool.pytest.ini_options] env` (via `pytest-env`) rather than in every command,
so an agent running `pytest` by hand gets the same behaviour as the gate.

Two rules that keep the GUI gate honest:

- **Assert on the model, not the pixels.** A screenshot comparison is a gate
  that fails on a font-rendering change and passes on a logic bug. Assert widget
  state, selection state, accessible names, and the events the widget emits.
- **The pipeline must be drivable with no widgets at all.** If a test of run
  progress needs a window, the boundary between `ui` and `pipeline` is wrong.

Qt object lifetime is the usual source of flake: keep a reference to every
widget under test for the duration of the test (`qtbot.addWidget`), and never
rely on garbage-collection order.

## 3. The build gate is a frozen binary

The command and its `slow` line are in the tables above.

Evidence: PyInstaller prints `Building EXE from ...` and
`Building ... completed successfully`. A spec file pointing at a moved entry
point still exits 0 in some versions, so assert on the build lines, not on the
exit code alone.

What the build gate is *for*, in this stack, is not "does it compile" — Python
has no compile step worth gating. It is **"does the frozen tree still contain
what it must and exclude what it must not"**: a hidden import that PyInstaller
cannot see statically fails at the user's first launch and nowhere earlier. So
the packaging story adds a test over the *built* tree — bundled data present,
`.claude/`, `docs/`, `scripts/` and `.github/` absent — rather than a comment in
the spec.

## 4. Local inference that CI cannot run

The trap here is the one `quality-gates` describes, reached by three sensible
decisions: inference needs a GPU, so its tests need a GPU, so its gate is
optional, so nothing required exercises them.

**Split every model adapter in two.**

- *Logic* — pre-processing, thresholding, post-processing, region merging —
  takes an **injected session object** with a narrow `run(inputs) -> outputs`
  interface, and is tested against a fake one in `tests/core/`. No GPU, no
  model file, no network. A **required** gate reads this, and it is where the
  acceptance criteria go.
- *Session* — loading a real `.onnx`, choosing an execution provider — gets a
  thin smoke test in `tests/integration/`, marked `gpu`, gate optional.

Then say so in `project.conf`, so `gates.sh` can check it:

    covers | unit        | src/<pkg>/detect/**
    covers | integration | src/<pkg>/detect/**

A story whose central claim genuinely can only run on a GPU declares
`required_gates: [integration]`. That should be rare; if it is common, the split
above has not been done.

Provider fallback is a runtime decision (CUDA → DirectML → CPU) and therefore a
behaviour with a test: assert the chain's *selection* logic against a fake
provider list in `tests/core/`, and smoke-test the real chain in
`tests/integration/`.

    discovery | providers | . | uv run python -c "import onnxruntime as o; print(o.get_available_providers())" | grep -qE "CUDA|Dml|CPU"

A machine with no GPU cannot start this gate's work, which is BLOCKED, not
FAIL:

    blocked-when | integration | (CUDAExecutionProvider is not in available provider names|Failed to load library .*onnxruntime_providers_cuda|no CUDA-capable device)

Do **not** widen that pattern to cover an inference error. A model that loads
and returns garbage is the gate doing its job.

## 5. Architectural boundaries as a gate

A GUI project accrues `from ...ui import` in its core within a month unless
something refuses it. `import-linter` is the tool:

    gate     | lint | required | . | uv run ruff check . && uv run lint-imports
    evidence | lint | Contracts: [1-9][0-9]* kept
    floor    | lint | <number of contracts>

Note the gap this creates and close it: that regex proves *import-linter* did
work, not that `ruff` saw any files. `ruff check` on an empty tree prints
`All checks passed!` and exits 0 — the canonical vacuous pass. Add a
`discovery` line that makes `ruff`'s reach visible, rather than trusting the
combined exit code.

When probing an import contract, write the violation in **both** forms —
`from mangatl.ui import X` *and* `from ...ui import X`. A contract that catches
the absolute import and misses the relative one catches the deliberate crossing
and misses the accidental one. That has happened.

## 6. Extra dependencies over `python-uv`

    PySide6            the GUI
    pytest-qt          drives it in tests
    pytest-env         sets QT_QPA_PLATFORM for every run
    import-linter      the boundary gate
    pyinstaller        the build gate
    onnxruntime-gpu    local inference (plus onnxruntime-directml as fallback)
    opencv-python-headless   NOT opencv-python — the non-headless wheel bundles
                             a second, conflicting Qt

## 7. Prerequisites

As `python-uv`, plus:

- Nothing extra for the GUI: PySide6 ships Qt in its wheel.
- For the CUDA execution provider, an NVIDIA driver new enough for the ORT build
  (and CUDA 12.8+ for Blackwell / sm_120 cards). The DirectML provider needs
  only a DX12 GPU and no toolkit, which is why it is the fallback.
- On CI: no GPU, no display. `QT_QPA_PLATFORM=offscreen` covers the display;
  the adapter split above covers the GPU.
