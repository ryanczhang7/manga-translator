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

No transaction is opened: `write_cleaned` opens its own, and
`Project.transaction()` is not reentrant. No event is emitted: the runner's
`StageFinished(stage="clean")` is the whole of its progress.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mangatl.domain.region import RawRegion
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
        """Clean `ctx.page` from its stored regions and store the image."""
        regions = ctx.project.read_regions(ctx.page.ordinal)
        image_bytes = (ctx.project.chapter.source_dir / ctx.page.filename).read_bytes()
        cleaned = self.clean(image_bytes, regions) if regions else image_bytes
        ctx.project.write_cleaned(ctx.page.ordinal, cleaned)

    def is_done(self, ctx: PageContext) -> bool:
        """Whether a cleaned image is stored for this page, and nothing else."""
        return ctx.project.has_cleaned(ctx.page.ordinal)
