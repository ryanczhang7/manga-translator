"""The five import contracts of `architecture.md` §3, pinned as configuration.

These tests read `pyproject.toml` and `.claude/harness/project.conf` as data.
They deliberately do **not** shell out to `lint-imports`: whether a contract
actually rejects a boundary crossing is the `lint` gate's own job, discharged in
this story's `## Gate probes`, and `tests/core` is run by three gates (`unit`,
`coverage`, `coverage-core`), so anything expensive here is paid three times per
gate run.

What they catch that `floor | lint | 5` cannot: the count staying at five while
a module is quietly dropped from one contract's source list.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PROJECT_CONF = REPO_ROOT / ".claude" / "harness" / "project.conf"

LAYERS = "Imports go down the layers only"
DOMAIN = "domain is independent"
UI = "Nothing imports ui"
ANTHROPIC = "Only translate imports anthropic"
ONNX = "Only detect, ocr and clean import onnxruntime"

STAGE_LAYER = frozenset(
    {
        "mangatl.detect",
        "mangatl.ocr",
        "mangatl.translate",
        "mangatl.clean",
        "mangatl.typeset",
        "mangatl.bench",
    }
)


def _importlinter() -> dict[str, Any]:
    with PYPROJECT.open("rb") as handle:
        tool = tomllib.load(handle)["tool"]
    assert "importlinter" in tool, "pyproject.toml has no [tool.importlinter] section"
    section: dict[str, Any] = tool["importlinter"]
    return section


def _contracts() -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = _importlinter().get("contracts", [])
    return contracts


def _names() -> list[str]:
    return [contract.get("name", "<unnamed>") for contract in _contracts()]


def _contract(name: str) -> dict[str, Any]:
    found = [contract for contract in _contracts() if contract.get("name") == name]
    assert found, f"no import-linter contract named {name!r}; configured: {_names()}"
    assert len(found) == 1, f"{len(found)} import-linter contracts are named {name!r}"
    return found[0]


def _modules(contract: dict[str, Any], key: str) -> list[str]:
    value = contract.get(key)
    assert isinstance(value, list), f"contract {contract.get('name')!r} has no {key} list"
    assert len(set(value)) == len(value), f"{key} of {contract.get('name')!r} repeats an entry"
    return sorted(value)


def _layer(raw: str) -> tuple[frozenset[str], bool]:
    """Split one layer the way import-linter's `LayerField` does.

    Returns the modules of the layer and whether they are independent of each
    other. `|` separates siblings that may NOT import each other, `:` separates
    siblings that may, and a layer naming one module is independent by
    definition. Verified out-of-tree against import-linter 2.15 during RED: on a
    throwaway package where one sibling imports the other, `|` reports
    `siblings BROKEN` and `:` reports `siblings KEPT`.
    """
    mixed = "|" in raw and ":" in raw
    assert not mixed, f"layer {raw!r} mixes | and :, which import-linter refuses"
    delimiter = "|" if "|" in raw else ":"
    modules = frozenset(part.strip() for part in raw.split(delimiter))
    return modules, "|" in raw or ":" not in raw


def _manifest(kind: str, gate: str) -> list[str]:
    """The last field of every uncommented `<kind> | <gate> | ...` line."""
    values = []
    for line in PROJECT_CONF.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        fields = [field.strip() for field in line.split("|", 2)]
        if len(fields) == 3 and fields[0] == kind and fields[1] == gate:
            values.append(fields[2])
    return values


def test_all_five_boundaries_of_the_architecture_are_configured_as_contracts() -> None:
    assert _names() == [LAYERS, DOMAIN, UI, ANTHROPIC, ONNX]


def test_the_linter_analyses_the_mangatl_package() -> None:
    assert _importlinter().get("root_packages") == ["mangatl"]


def test_forbidding_a_third_party_package_requires_external_analysis() -> None:
    # Three of the five contracts forbid external modules. Without this line
    # import-linter refuses to run at all, with "The top level configuration
    # must have include_external_packages=True when there are external
    # forbidden modules." - so its absence is loud, not a vacuous pass.
    assert _importlinter().get("include_external_packages") is True


def test_the_layers_run_ui_over_pipeline_over_the_stages_over_store_over_domain() -> None:
    contract = _contract(LAYERS)
    assert contract.get("type") == "layers"
    layers = contract.get("layers")
    assert isinstance(layers, list), f"contract {LAYERS!r} has no layers list"
    assert [_layer(raw)[0] for raw in layers] == [
        frozenset({"mangatl.ui"}),
        frozenset({"mangatl.pipeline"}),
        STAGE_LAYER,
        frozenset({"mangatl.store"}),
        frozenset({"mangatl.domain"}),
    ]


def test_the_six_stage_packages_are_independent_of_each_other() -> None:
    # Decided by the user 2026-09-13 and recorded in architecture.md §3 clause
    # 1: `pipeline` is the orchestrator, so a stage importing a sibling makes
    # that layer decorative; contract 5's confinement of onnxruntime to
    # detect/ocr/clean leaks transitively the moment typeset or bench may import
    # detect; and coverage-core's 100% bar on bench is unreachable if bench can
    # pull in a stage that loads ONNX. `|` is import-linter's independent-sibling
    # delimiter and `:` the permissive one, so only `|` states that decision.
    layers = _contract(LAYERS).get("layers", [])
    stage_layers = [raw for raw in layers if _layer(raw)[0] == STAGE_LAYER]
    assert len(stage_layers) == 1, f"the six stage packages are not one layer: {layers}"
    assert _layer(stage_layers[0])[1] is True, (
        f"the stage layer {stage_layers[0]!r} lets siblings import each other; "
        "architecture.md §3 clause 1 makes them independent, which is `|` not `:`"
    )


def test_domain_imports_nothing_of_ours_and_no_third_party_library() -> None:
    contract = _contract(DOMAIN)
    assert contract.get("type") == "forbidden"
    assert _modules(contract, "source_modules") == ["mangatl.domain"]
    assert _modules(contract, "forbidden_modules") == [
        "PIL",
        "PySide6",
        "anthropic",
        "mangatl.*",
        "numpy",
        "onnxruntime",
    ]


def test_nothing_below_the_entry_point_imports_ui() -> None:
    contract = _contract(UI)
    assert contract.get("type") == "forbidden"
    assert _modules(contract, "forbidden_modules") == ["mangatl.ui"]
    assert _modules(contract, "source_modules") == [
        "mangatl.bench",
        "mangatl.clean",
        "mangatl.detect",
        "mangatl.domain",
        "mangatl.ocr",
        "mangatl.pipeline",
        "mangatl.store",
        "mangatl.translate",
        "mangatl.typeset",
    ]


def test_the_entry_point_may_still_open_the_window_it_exists_to_open() -> None:
    # src/mangatl/app.py line 9 is `from mangatl.ui.main_window import
    # MainWindow`. A contract phrased as "nothing at all imports ui" breaks
    # `bash scripts/task.sh dev`; §3's "nothing imports ui" means nothing below
    # the entry point.
    assert "mangatl.app" not in _contract(UI).get("source_modules", [])


def test_only_translate_may_import_anthropic() -> None:
    contract = _contract(ANTHROPIC)
    assert contract.get("type") == "forbidden"
    assert _modules(contract, "forbidden_modules") == ["anthropic"]
    assert _modules(contract, "source_modules") == [
        "mangatl.app",
        "mangatl.bench",
        "mangatl.clean",
        "mangatl.detect",
        "mangatl.domain",
        "mangatl.ocr",
        "mangatl.pipeline",
        "mangatl.store",
        "mangatl.typeset",
        "mangatl.ui",
    ]


def test_only_detect_ocr_and_clean_may_import_onnxruntime() -> None:
    contract = _contract(ONNX)
    assert contract.get("type") == "forbidden"
    assert _modules(contract, "forbidden_modules") == ["onnxruntime"]
    assert _modules(contract, "source_modules") == [
        "mangatl.app",
        "mangatl.bench",
        "mangatl.domain",
        "mangatl.pipeline",
        "mangatl.store",
        "mangatl.translate",
        "mangatl.typeset",
        "mangatl.ui",
    ]


def test_the_package_that_owns_a_dependency_is_not_forbidden_from_importing_it() -> None:
    # The inverse of the two contracts above: listing `translate` as a source
    # of the anthropic contract would forbid the one import the architecture
    # requires, and `lint-imports` would still report five contracts kept.
    assert "mangatl.translate" not in _contract(ANTHROPIC).get("source_modules", [])
    offenders = [
        stage
        for stage in ("mangatl.detect", "mangatl.ocr", "mangatl.clean")
        if stage in _contract(ONNX).get("source_modules", [])
    ]
    assert offenders == [], f"{offenders} may not be forbidden from importing onnxruntime"


def test_the_lint_gate_floors_the_contract_count_at_five() -> None:
    assert _manifest("floor", "lint") == ["5"]


def test_the_lint_gate_counts_the_contracts_import_linter_kept() -> None:
    # A floor is measured out of its gate's evidence match, so `floor | lint |
    # 5` asserts nothing without this line - and `gates.sh --audit` refuses a
    # floor that has no evidence line to measure it out of.
    assert _manifest("evidence", "lint") == ["Contracts: [1-9][0-9]* kept"]
