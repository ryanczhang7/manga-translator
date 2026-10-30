"""The region the detector emits: a polygon, a page-sized 1-bit mask, a
confidence and a kind.

**Why `mask` is `bytes` and not an array.** `architecture.md` §3 contract 2
forbids `domain` from importing `numpy`, `PIL`, `PySide6`, `onnxruntime` or
`anthropic`, and the `lint` gate enforces it through import-linter. The encoding
therefore happens in `mangatl.detect` and the domain carries the encoded bytes -
a PNG of bit depth 1 and colour type 0, the size of the page (MT-007 C-7/A-10).

**Why `confidence` is the mean and not the max.** The `seg` head's measured range
on `spikes/MT-002/pages/012.jpg` is exactly [0.0, 1.0] and almost every region
touches the top of it, so the max carries no information. The mean does.

**Why the validation is here.** `__post_init__` refuses a malformed region at the
point it is built rather than two stories later in code that did not cause it.
The `int` check in particular is not pedantry: contours come out of the array
library as `numpy.int32`, which is *not* a subclass of `int`, and `json.dumps`
refuses those - and `store.project.write_regions` writes the polygon as JSON.
Caught here it names the field; caught there it is a `TypeError` two layers away
from its cause (MT-007 amendment A-9).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

__all__ = ["EXCLUSION_REASONS", "ExclusionReason", "RawRegion", "included"]

#: Why a region is out of translation, cleaning and typesetting (MT-118 C-1).
#: `watermark` is the detector's rule (MT-121), `user` the workspace's (MT-120).
#: A plain assignment, not a PEP 695 `type` statement: `typing.get_args` sees
#: through this spelling and returns `()` for the other.
ExclusionReason = Literal["watermark", "user"]

#: The values `RawRegion.excluded` may take besides `None`, in this order. The
#: domain validation and `store.project.Project.set_excluded` both check against
#: it, and `store/schema.py`'s CHECK spells the same two.
EXCLUSION_REASONS: tuple[ExclusionReason, ...] = ("watermark", "user")

#: The 8 bytes every PNG file begins with. A mask that does not start with them
#: is not an image, whatever else it may be.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: The two values `region.kind` may take. `bubble` is the class-1 box of the
#: detector's box head - a speech bubble - and `box` is class 0, which measured
#: on `011-015.jpg` is free-floating text on art (MT-007 amendment A-4).
_KINDS = ("bubble", "box")


@dataclass(frozen=True)
class RawRegion:
    """One text region, before reading order and before furigana merging.

    `polygon` is a **closed ring** in page pixel coordinates: at least four
    vertices, the last repeating the first. `mask` is the region's own pixels,
    PNG-encoded at bit depth 1 over the whole page. `confidence` is the mean
    probability inside the mask. `kind` is the class of the box that fenced it.
    """

    polygon: tuple[tuple[int, int], ...]
    mask: bytes
    confidence: float
    kind: Literal["bubble", "box"]
    #: Which regions of the sequence handed to `detect.columns.merge_columns`
    #: this one absorbed, ascending; `()` when it absorbed nothing (MT-008 C-2).
    #: Indices rather than identifiers, because regions have no database
    #: identity until they are written and the merge is computed before the
    #: write. It is **last** so that MT-007's positional construction sites keep
    #: working, and it has a default so that they need not mention it at all.
    merged_from: tuple[int, ...] = ()
    #: Why this region is out of translation, cleaning and typesetting; None
    #: is "included". `watermark` is the detector's rule (MT-121), `user` the
    #: workspace's (MT-120). LAST and defaulted, for merged_from's reason.
    excluded: ExclusionReason | None = None

    def __post_init__(self) -> None:
        if len(self.polygon) < 4 or self.polygon[0] != self.polygon[-1]:
            raise ValueError(
                "polygon must be a closed ring of at least four vertices, the last"
                f" repeating the first; got {self.polygon!r}"
            )
        if any(
            not isinstance(value, int) or value < 0 for point in self.polygon for value in point
        ):
            raise ValueError(
                "polygon coordinates must be non-negative ints - a numpy.int32 is"
                f" not an int and json.dumps refuses it; got {self.polygon!r}"
            )
        if self.mask[:8] != _PNG_SIGNATURE:
            raise ValueError("mask must be PNG-encoded: it does not begin with the PNG signature")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence is a mean probability in [0.0, 1.0]; got {self.confidence!r}"
            )
        if self.kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}; got {self.kind!r}")
        if any(not isinstance(index, int) for index in self.merged_from):
            raise ValueError(
                "merged_from indices must be ints - a numpy.int32 is not an int and"
                " json.dumps refuses it, and this field is JSON on its way to the"
                f" store; got {self.merged_from!r}"
            )
        if any(index < 0 for index in self.merged_from):
            raise ValueError(
                "merged_from indices are positions in the sequence that was merged, so"
                f" none of them is negative; got {self.merged_from!r}"
            )
        if len(set(self.merged_from)) != len(self.merged_from):
            raise ValueError(
                "merged_from indices must be distinct - a region absorbed twice means"
                f" the merge walked one input twice; got {self.merged_from!r}"
            )
        if self.excluded is not None and self.excluded not in EXCLUSION_REASONS:
            raise ValueError(
                f"excluded must be None or one of {EXCLUSION_REASONS}; got {self.excluded!r}"
            )


def included(regions: Sequence[RawRegion]) -> tuple[RawRegion, ...]:
    """The regions the pipeline treats as text to translate, clean and
    typeset: those whose `excluded is None`, in the order given (MT-119 C-1).

    Here rather than in `pipeline` because both `clean_stage.py` and `bake.py`
    filter by it, and `clean_stage.py` may import nothing `bake.py` does."""
    return tuple(region for region in regions if region.excluded is None)
