"""The stage that writes one page's regions, in reading order (MT-035).

MT-007 produced regions, MT-008 merged the columns of one utterance and MT-009
ordered them; this is the step that puts the result in the store, which is what
EPIC-03's done-when sentence is about. It is four lines of work and three of the
four are load-bearing in a way worth writing down.

**The detector is injected, and that is forced by a gate rather than chosen for
taste** (MT-035 C-1, measured twice before this module was written).
`pyproject.toml`'s contract *"Only detect, ocr and clean import onnxruntime"* is
a `forbidden` contract that lists `mangatl.pipeline` among its `source_modules`
and sets no `allow_indirect_imports`, so import-linter reports **indirect**
chains - and every module in `mangatl.detect` reaches `onnxruntime` through
`columns -> postprocess -> session`. So this module may not import
`mangatl.detect` at all, **not even the `DetectorSession` protocol**: that
protocol lives in the very file that does the import. It names its detector
behind `PageDetector` instead, whose two halves are stdlib and `domain`, and
`mangatl.detect.page.detect_page_regions` bound to a session is one.
`tests/core/test_detect_stage.py` reads this module's own AST, so reaching for
`numpy`, `PIL`, `cv2` or `mangatl.detect` is reported by name in `unit` before
`lint` sees it.

**`sort_regions`, not `order_regions`.** Position is the only carrier of reading
order (MT-009 PO-1): `Project.write_regions` derives each row's
`reading_index` from its position in the sequence it is handed, and a
`RawRegion` carries no index of its own.

**No transaction is opened here.** `write_regions` opens its own and
`Project.transaction()` is deliberately not reentrant (MT-005 PO-5), so a stage
that wrapped the write would turn it into a `RuntimeError`.

**One write, at the end, and never a clearing write first.** `write_regions` is
a page-level replace that deletes rows at `reading_index >= len(regions)`
(MT-007 amendment A-11), so a re-run finding fewer regions already leaves no
stragglers. A stage that opened by clearing the page would satisfy every other
criterion of MT-035 and destroy a page's regions - and, once MT-010 lands, the
`line` rows cascading off them - every time an inference failed. MT-035 AC-6 is
the one test that catches it.

**`is_done` is "this page has regions"** (MT-035 C-6). Regions are the only
thing this stage writes, so they are the only honest thing it can read back. The
consequence, pinned as MT-035 AC-5: a page the detector genuinely finds no text
on is re-detected on every run. That is accepted for v1 - re-detecting is
idempotent and costs one local inference, no API spend and no data loss -
whereas a per-stage completion marker is a schema change and `page.status` is
per page and already the runner's (`architecture.md` §5).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mangatl.domain.reading_order import sort_regions
from mangatl.domain.region import RawRegion
from mangatl.pipeline.stage import PageContext

__all__ = ["DetectStage", "PageDetector"]

#: Page image bytes in, regions out, in any order. The narrowest type this
#: module can name: `bytes` is stdlib and `RawRegion` is `domain`, so naming the
#: detector costs `pipeline` no import of `mangatl.detect` (C-1). A `Callable`
#: rather than a `Protocol` because any callable will do - a bound
#: `partial(detect_page_regions, session)`, a class with `__call__`, a function.
PageDetector = Callable[[bytes], Sequence[RawRegion]]


@dataclass
class DetectStage:
    """Detect one page's regions and store them in reading order.

    Not `frozen=True` (MT-035 amendment R-1, reproduced twice). `Stage.name` is
    declared `name: str`, an instance attribute, and mypy holds an
    implementation to that: a frozen field is a *read-only* attribute
    (`expected settable variable, got read-only attribute`) and a `ClassVar` is
    a *class* variable (`expected instance variable, got class variable`), so
    neither spelling of a frozen dataclass satisfies the protocol. A plain
    `@dataclass` does, and it matches `PassThroughStage`, the only precedent in
    `stage.py`.

    Consequence recorded rather than solved (MT-035 C-3): a non-frozen
    dataclass with `eq=True` has `__hash__ = None`, so a `DetectStage` cannot be
    a `set` member or a `dict` key. Nothing hashes a stage - `run_chapter` only
    iterates its `Sequence` - and `eq=False` would restore identity hashing if a
    later story needs it.
    """

    detect: PageDetector
    name: str = "detect"

    def run(self, ctx: PageContext) -> None:
        """Detect `ctx.page` and replace its stored regions with the result.

        The scans are read-only to this app (`architecture.md` §5): the page
        file is read and nothing beside it is written.
        """
        image_bytes = (ctx.project.chapter.source_dir / ctx.page.filename).read_bytes()
        regions = self.detect(image_bytes)
        ordered = sort_regions(regions)
        ctx.project.write_regions(ctx.page.ordinal, ordered)

    def is_done(self, ctx: PageContext) -> bool:
        """Whether this page already has regions in the store."""
        return bool(ctx.project.read_regions(ctx.page.ordinal))
