"""The stage that stores one page's cleaned image (MT-065 C-5).

MT-019 shipped the cleaning - `clean.mask.erase_mask`, `clean.inpaint.clean_page`
- and nothing called it. This is the step that puts it into a run, so that
MT-021's bake has a page with the Japanese erased to composite English onto.

**The cleaner is injected, bytes in and bytes out**, for `detect_stage.py`'s
reason: `pyproject.toml`'s onnxruntime contract is transitive and
`clean.inpaint` reaches `onnxruntime` through `clean.session`, so this module
imports nothing under `mangatl.clean` - and, like the detect and OCR stages, no
numpy, PIL or cv2. `mangatl.clean.page.clean_page_image` bound to a session in
`mangatl.compose` is the `PageCleaner`. `tests/core/test_clean_stage.py` reads
this module's AST.

**The regions come from the store**, in stored reading order, never from a
fresh detection - which is what `region.mask_blob` is kept for
(`architecture.md` §4): a resume cleans without re-detecting. **The source scan
is read and never written** (§5); OCR keeps reading the source scan, not this
stage's output, which has had its text erased.

**A page with no regions stores its own source bytes, verbatim** (PO-4), and the
cleaner is never called for it (AC-2): identical by construction, with no
re-encode and so no PIL here.

**An excluded region is never handed to the cleaner** (MT-119 C-2): it is left
as drawn. The stored image records the reading indices it *did* erase
(`write_cleaned(erased=...)`) - reading indices of the page, not positions in
the filtered tuple - so the bake knows where to paste the source back over a
region excluded after the clean, and the store knows which restore needs a
re-clean. A page whose every region is excluded takes the no-regions branch.

No transaction is opened: `write_cleaned` opens its own, and
`Project.transaction()` is not reentrant. No event is emitted: the runner's
`StageFinished(stage="clean")` is the whole of its progress.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mangatl.domain.region import RawRegion, included
from mangatl.pipeline.stage import PageContext

__all__ = ["CleanStage", "PageCleaner"]

#: One page's encoded source image and its stored regions in reading order in,
#: the cleaned page as encoded image bytes (PNG) out, the page's own size.
PageCleaner = Callable[[bytes, Sequence[RawRegion]], bytes]


@dataclass
class CleanStage:
    """Clean one page and store the result.

    Not `frozen=True`, for `DetectStage`'s reason (MT-035 R-1): `Stage.name` is
    an instance attribute.
    """

    clean: PageCleaner
    name: str = "clean"

    def run(self, ctx: PageContext) -> None:
        """Clean `ctx.page` from its stored, included regions and store the
        image with the reading indices it erased (MT-119 C-2)."""
        regions = ctx.project.read_regions(ctx.page.ordinal)
        kept = included(regions)
        image_bytes = (ctx.project.chapter.source_dir / ctx.page.filename).read_bytes()
        cleaned = self.clean(image_bytes, kept) if kept else image_bytes
        ctx.project.write_cleaned(
            ctx.page.ordinal,
            cleaned,
            erased=[i for i, region in enumerate(regions) if region.excluded is None],
        )

    def is_done(self, ctx: PageContext) -> bool:
        """Whether a cleaned image is stored for this page, and nothing else."""
        return ctx.project.has_cleaned(ctx.page.ordinal)
