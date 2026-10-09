"""Which onnxruntime execution providers to request, given what is available.

**MT-024 C-2, PO-1.** The preference is CUDA, then CPU - never DirectML:
`onnxruntime-directml` cannot be installed beside the locked
`onnxruntime-gpu[cuda,cudnn]` (`architecture.md` D3's correction), so the
three-way chain was never one install. Requesting CUDA is not getting it;
`mangatl.detect.session.selected_provider` is the honest answer, after the fact.

A pure function over a list of names, so it is tested against fake
availability lists rather than against whatever this machine has.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["PROVIDER_PREFERENCE", "select_providers"]

_CPU = "CPUExecutionProvider"

#: CUDA first, CPU always last.
PROVIDER_PREFERENCE: tuple[str, ...] = ("CUDAExecutionProvider", _CPU)


def select_providers(available: Sequence[str]) -> tuple[str, ...]:
    """`PROVIDER_PREFERENCE` filtered by membership in `available`, in
    preference order, with the CPU appended when absent: never empty, always
    ending in `CPUExecutionProvider`, never naming a provider not preferred."""
    selected = tuple(name for name in PROVIDER_PREFERENCE if name in available)
    return selected if _CPU in selected else (*selected, _CPU)
