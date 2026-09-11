# Profile: python-uv

Python 3.12+ managed by `uv`. Suits services, CLIs, data and ML work.

## Gate commands for project.conf

    gate | format    | optional | . | uv run ruff format --check .
    gate | lint      | required | . | uv run ruff check .
    gate | typecheck | required | . | uv run mypy src
    gate | unit      | required | . | uv run pytest -q
    gate | coverage  | required | . | uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=100
    gate | build     | required | . | uv build
    gate | mutation  | optional | . | uv run mutmut run

    task | install | - | . | uv sync --all-extras
    task | dev     | - | . | uv run <entry point>
    task | test    | - | . | uv run pytest -q

Use `pyright` instead of `mypy` where the project leans on modern typing;
`ruff format` replaces `black`.

## Evidence of work

See the `evidence` format in `project.conf`; these assert that the tool did
work, not that it succeeded.

    # UNVERIFIED - uv was not installed when this was written. The bootstrap
    # story must run each gate and correct these against real output.
    evidence | unit      | [1-9][0-9]* passed
    evidence | coverage  | TOTAL +[0-9]+ +[0-9]+
    evidence | lint      | Checked [1-9][0-9]* files|All checks passed
    evidence | typecheck | Success: no issues found in [1-9][0-9]* source file
    evidence | build     | Successfully built

`pytest` exits 5 when it collects no tests, so the bare vacuous case is already
loud - **unless someone adds `--passWithNoTests` or an `addopts` that sets it**,
which converts a safe gate into an unsafe one. Do not. The `unit` regex is the
backstop for the subtler version: a `testpaths` or `-k` filter that stops
matching after a refactor.

`mypy` reports `Success: no issues found in 0 source files` when its target
resolves empty, and exits 0. That is the vacuous pass in this stack, and the
`[1-9]` in the typecheck regex is what catches it.

## What the runner can see

`doctor.sh` runs `discovery` lines; the gates do not. One per place tests are
expected to live, and one for every directory carrying a coverage threshold - a
`--cov=src` that no longer resolves to anything is satisfied silently.

    # UNVERIFIED - correct the grep targets against your own layout.
    discovery | tests | . | uv run pytest --collect-only -q | grep -q "tests/"
    discovery | src   | . | uv run pytest --collect-only -q | grep -qE "[1-9][0-9]* tests? collected"

`pytest --collect-only -q` prints the collected node ids and a count. A
`testpaths` entry that stopped matching, or a package that lost its `__init__`,
shows up here and nowhere else: the run still exits 0 with a smaller number.

## What `--fast` should leave out

    slow | build    | packaging a wheel and sdist, which RED and GREEN never use
    slow | mutation | mutmut re-runs the suite once per mutant

`coverage` stays in the fast subset deliberately, even though it is the slowest
of what remains. `pytest --cov` runs the same tests through `coverage.py`'s
tracer, and that instrumented run is the one that judges the story - keeping it
out of RED and GREEN is exactly how a suite reaches CI never having been
measured under it. Python has no default per-test timeout, so the failure mode
here is a slow *suite* rather than a timed-out test; if you add
`pytest-timeout`, set its value against the `--cov` run, not the plain one.

## Layout

    src/<package>/          production code
    tests/                  mirrors src/, test_*.py
    pyproject.toml          deps, tool config, pinned versions
    uv.lock                 committed

## paths.conf additions

Defaults already cover `tests/**`, `test_*.py` and `conftest.py`. Add nothing
unless you put tests beside the code, in which case add `src/**/test_*.py` to
the `test` section.

## Notes for the bootstrap story

- `uv init`, then pin every dependency in `pyproject.toml`; commit `uv.lock`.
- Configure `ruff`, `mypy` and `pytest` in `pyproject.toml`, not in scattered
  dotfiles - one place the next agent will find.
- Set `--cov-fail-under` in the gate command rather than in config, so the
  threshold is visible where it is enforced.
- For a service, add `httpx` and `pytest-asyncio` and prove one real request in
  the example test rather than a `test_imports` placeholder.
- Dockerfile: builder stage runs `uv sync --frozen --no-dev`, runtime stage is
  `python:3.12-slim` with only `src/` and the virtualenv.

## Testing notes

`pytest` fixtures over setup methods. `pytest.mark.parametrize` for the
zero/one/many and boundary cases. `hypothesis` where an invariant is easier to
state than the examples that check it. `freezegun` or an injected clock rather
than sleeping.

## Prerequisites

`uv` is the only thing you install globally; it manages Python itself.

    # Windows
    winget install --id astral-sh.uv
    # macOS / Linux
    curl -LsSf https://astral.sh/uv/install.sh | sh

Then, inside the project:

    uv python install 3.12
    uv sync --all-extras

Verify: `uv --version`, then `uv run python --version` prints 3.12.x.

**Windows note.** If `python` opens the Microsoft Store, that is the App
Execution Alias stub, not an interpreter. Ignore it - `uv run` does not use it.
Turn the aliases off under Settings, Apps, Advanced app settings, App execution
aliases if it gets in the way.

Optional: `uv tool install mutmut` for the mutation gate.
