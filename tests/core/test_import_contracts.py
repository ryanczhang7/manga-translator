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
    # `mangatl.cli` was added to this list by MT-006 (`## Contract` PO-5). It is
    # the contract that earns its place there: it turns "the CLI is headless"
    # from a claim a test makes into a fact the `lint` gate checks, and AC-9's
    # boundary is the whole reason MT-006's entry point is a CLI and not a
    # window. `mangatl.app` stays out, for the reason the test below gives.
    # MT-036 added `mangatl.compose` (C-5, PO-3). The composition root is the
    # one module exempted from contract 5, and the exemption must not become a
    # back door out of this one: `cli` stays listed and the new module that does
    # the constructing is listed beside it, so neither the entry point nor the
    # composition root can reach a widget. Eleven entries.
    contract = _contract(UI)
    assert contract.get("type") == "forbidden"
    assert _modules(contract, "forbidden_modules") == ["mangatl.ui"]
    assert _modules(contract, "source_modules") == [
        "mangatl.bench",
        "mangatl.clean",
        "mangatl.cli",
        "mangatl.compose",
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
    # MT-044 PO-1: **ten** entries, `mangatl.cli` removed and nothing else.
    # `compose.build_pipeline` must construct the `Anthropic` client to bind
    # `partial(translate_page, client)` into the stage list (C-13).
    # `mangatl.compose` is already absent from this list - but `mangatl.cli`
    # imports `compose`, and this contract carries no `allow_indirect_imports`,
    # so import-linter reports the chain. Measured before dispatch, with a
    # throwaway `mangatl/_probe_client_in_compose.py` imported from
    # `compose.py`:
    #
    #     Only translate imports anthropic BROKEN
    #     mangatl.cli is not allowed to import anthropic:
    #     -   mangatl.cli -> mangatl.compose (l.34)
    #         mangatl.compose -> mangatl._probe_client_in_compose (l.151)
    #         mangatl._probe_client_in_compose -> anthropic (l.2)
    #
    # Removing that one name returned `Contracts: 5 kept, 0 broken` with the
    # probe still in place. This mirrors
    # `test_the_composition_root_is_exempt_from_onnx_and_the_window_entry_point_is_not`
    # exactly: MT-036 made the identical move for the onnxruntime contract, and
    # `architecture.md` §3 rule 5's composition-root exception is the precedent.
    #
    # `allow_indirect_imports = true` was rejected: it would weaken the contract
    # for all eleven modules, `mangatl.pipeline` included, and the chain
    # `pipeline -> translate -> anthropic` is the one MT-011 C-1 exists to stop.
    # The test below keeps `mangatl.pipeline` listed, which is that confinement.
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
    assert "allow_indirect_imports" not in contract, (
        "allow_indirect_imports would stop import-linter reporting the chain"
        " pipeline -> translate.client -> anthropic, which is the whole of what"
        " MT-011 C-1 is built around; MT-044 PO-1 dropped one module instead"
    )


def test_the_composition_root_is_exempt_from_anthropic_and_the_pipeline_is_not() -> None:
    """MT-044 PO-1, stated as the decision rather than as one list.

    Only the module that *constructs* the client, and the entry point that
    imports it, come out of this contract: `mangatl.compose` was already absent
    and `mangatl.cli` joins it. `mangatl.app` stays listed for MT-036 PO-2's
    reason - `app.py` imports `mangatl.ui.main_window` and nothing else, so it
    needs no exemption and will not be given one in advance.

    What is lost, stated honestly: `mangatl.cli` may now import
    `mangatl.translate` directly and this contract will not complain. What is
    kept is the confinement that matters, measured on 2026-09-21 with the
    ten-entry list in place -

        mangatl.pipeline is not allowed to import anthropic:
        -   mangatl.pipeline._probe_chain -> mangatl.translate.client (l.2)
            mangatl.translate.client -> anthropic (l.43, l.44)

    and `mangatl.compose` is in the *"Nothing imports ui"* contract, so this
    does not become a back door out of that one either.
    """
    confined = _contract(ANTHROPIC).get("source_modules", [])

    assert "mangatl.compose" not in confined
    assert "mangatl.cli" not in confined
    assert "mangatl.pipeline" in confined, (
        "mangatl.pipeline was exempted from the anthropic confinement; that chain"
        " is the one MT-011 C-1 and MT-044 PO-1 both exist to keep reportable"
    )
    assert "mangatl.app" in confined, (
        "mangatl.app was exempted from the anthropic confinement without a story"
        " that needed it (MT-036 PO-2's rule, applied to this contract)"
    )
    assert "mangatl.compose" in _contract(UI).get("source_modules", []), (
        "the composition root's exemption from the anthropic contract must not"
        " become a back door out of 'Nothing imports ui' (MT-036 C-5, PO-3)"
    )


def test_only_detect_ocr_and_clean_may_import_onnxruntime() -> None:
    # MT-036 AC-1: **eight** entries, `mangatl.cli` removed and nothing else.
    # `architecture.md` §3's "composition-root exception to rule 5" carries the
    # measurement - one top-level import in `cli.py` breaks this contract and
    # removing that single name returns `5 kept, 0 broken` with the import still
    # in place. `allow_indirect_imports` is deliberately NOT added: it would
    # weaken the rule for all eight of the modules still listed here.
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
    assert "allow_indirect_imports" not in contract, (
        "allow_indirect_imports would stop import-linter reporting the chain"
        " pipeline -> detect.columns -> detect.postprocess -> detect.session ->"
        " onnxruntime, which is the whole of what this contract catches"
    )


def test_the_composition_root_is_exempt_from_onnx_and_the_window_entry_point_is_not() -> None:
    """MT-036 AC-1 and PO-2, stated as the decision rather than as two lists.

    Only the two modules that *construct* sessions come out of contract 5:
    `mangatl.compose`, which is the composition root, and `mangatl.cli`, which
    imports it. `mangatl.app` stays listed - nothing in it needs a session, and
    MT-015 amends this again if and when it does, having to say why `compose`
    was not enough. An exemption is earned by a gate that fails, not
    anticipated.
    """
    confined = _contract(ONNX).get("source_modules", [])

    assert "mangatl.compose" not in confined
    assert "mangatl.cli" not in confined
    assert "mangatl.app" in confined, (
        "mangatl.app was exempted from the onnxruntime confinement without a story"
        " that needed it (MT-036 PO-2)"
    )


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
