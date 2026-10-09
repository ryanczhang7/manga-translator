"""MT-024 AC-6 (selection) and C-2: `mangatl.models.providers`.

`select_providers(available)` is `PROVIDER_PREFERENCE` filtered by membership
in `available`, in preference order, with `CPUExecutionProvider` appended when
absent - so the result is never empty, always ends in CPU, and never names a
provider the preference does not. A pure function over fake availability
lists: nothing here asks this machine which providers it has (the story's
Model guidance: *not* a comment saying it was checked on the developer's
machine).

`PROVIDER_PREFERENCE` is **CUDA then CPU** - PO-1, the user's decision, and
`architecture.md` D3's correction - read out of the story, never re-decided.
DV-3 reorders it and both the pinned results below and the `inference
provider:` log assertion in `test_compose.py` must change.

RED: `mangatl.models.providers` does not exist; each test imports it in its
body, so the file collects and fails test by test.

The import-boundary tests at the bottom read the two modules' source with
`ast`: C-2 says neither imports `onnxruntime`, `PySide6`, or anything of ours
outside `mangatl.models`, so the startup check and the build's fetch can both
run without the inference runtime. `lint-imports` pins the same clause as a
contract (`test_import_contracts.py`); this is the cheap unit tripwire beside it.
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given
from hypothesis import strategies as st

CUDA = "CUDAExecutionProvider"
CPU = "CPUExecutionProvider"


def _providers() -> ModuleType:
    return importlib.import_module("mangatl.models.providers")


def test_the_preference_is_cuda_then_cpu_and_nothing_else() -> None:
    preference = _providers().PROVIDER_PREFERENCE
    assert preference == (CUDA, CPU)
    assert type(preference) is tuple


def test_the_composition_root_re_exports_the_same_preference_object() -> None:
    """C-2: `mangatl.compose` imports the constant from here, so
    `test_compose.py:174` holds at the same name and the two cannot drift."""
    import mangatl.compose as compose

    assert compose.PROVIDER_PREFERENCE is _providers().PROVIDER_PREFERENCE


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        ([CPU, CUDA], (CUDA, CPU)),
        ([CUDA, CPU], (CUDA, CPU)),
        ([CPU], (CPU,)),
        ([], (CPU,)),
        ([CUDA], (CUDA, CPU)),
        (["DmlExecutionProvider", CPU], (CPU,)),
        (["TensorrtExecutionProvider", CUDA, "AzureExecutionProvider", CPU], (CUDA, CPU)),
        (["DmlExecutionProvider"], (CPU,)),
        ([CUDA, CUDA, CPU, CPU], (CUDA, CPU)),
    ],
    ids=[
        "cpu listed before cuda",
        "cuda and cpu",
        "cpu only",
        "nothing available",
        "cuda without cpu",
        "directml is never requested",
        "tensorrt and azure are never requested",
        "an unknown provider alone",
        "duplicates",
    ],
)
def test_the_selection_is_the_preference_filtered_by_what_is_available(
    available: list[str], expected: tuple[str, ...]
) -> None:
    selected = _providers().select_providers(available)

    assert selected == expected, f"select_providers({available!r}) == {selected!r}"
    assert type(selected) is tuple, f"select_providers returned a {type(selected).__name__}"


def test_the_selection_accepts_any_sequence_and_does_not_mutate_it() -> None:
    available = (CPU, CUDA)
    assert _providers().select_providers(available) == (CUDA, CPU)
    names = [CPU]
    _providers().select_providers(names)
    assert names == [CPU]


_NAMES = st.one_of(
    st.sampled_from(
        [
            CUDA,
            CPU,
            "DmlExecutionProvider",
            "TensorrtExecutionProvider",
            "AzureExecutionProvider",
            "OpenVINOExecutionProvider",
        ]
    ),
    st.text(max_size=24),
)


@given(st.lists(_NAMES, max_size=8))
def test_any_selection_is_a_cpu_terminated_subsequence_of_the_preference(
    available: Sequence[str],
) -> None:
    module = _providers()
    preference = module.PROVIDER_PREFERENCE
    selected = module.select_providers(available)

    assert type(selected) is tuple
    assert selected, "the selection is never empty"
    assert selected[-1] == CPU, f"{selected!r} does not end in CPU"
    assert len(set(selected)) == len(selected), f"{selected!r} repeats a provider"
    assert all(name in preference for name in selected), f"{selected!r} names an unknown"
    assert list(selected) == [name for name in preference if name in selected], (
        f"{selected!r} is not in preference order"
    )
    assert (CUDA in selected) == (CUDA in available)


# -- C-2's import boundary -----------------------------------------------------


def _imports_of(module: ModuleType) -> set[str]:
    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            imported.add(node.module)
    return imported


def _forbidden(imported: set[str]) -> list[str]:
    return sorted(
        name
        for name in imported
        if name.split(".")[0] in {"onnxruntime", "PySide6"}
        or (name.startswith("mangatl") and not name.startswith("mangatl.models"))
    )


@pytest.mark.parametrize("name", ["mangatl.models.manifest", "mangatl.models.providers"])
def test_the_models_package_needs_neither_the_runtime_nor_the_window(name: str) -> None:
    module = importlib.import_module(name)

    assert _forbidden(_imports_of(module)) == [], (
        f"{name} imports {_forbidden(_imports_of(module))}; C-2 says the startup check"
        " and the build's fetch must import it without onnxruntime, PySide6 or the"
        " rest of mangatl"
    )


def test_the_boundary_check_would_see_a_forbidden_import() -> None:
    """Negative control for the helper above: a probe source that imports all
    three forbidden kinds is reported, and the permitted ones are not."""
    tree = {"onnxruntime", "PySide6.QtWidgets", "mangatl.compose", "mangatl.models.manifest"}
    assert _forbidden(tree | {"hashlib", "json"}) == [
        "PySide6.QtWidgets",
        "mangatl.compose",
        "onnxruntime",
    ]
