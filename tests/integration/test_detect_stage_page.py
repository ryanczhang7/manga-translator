"""AC-10: the real detector, through the real stage, into a real project store.

The only place in this story where the two halves are wired together for real -
`detect.page.detect_page_regions` bound to a session `detect.session` loaded onto
the GPU, injected into `pipeline.detect_stage.DetectStage` as a `PageDetector`.

**A test is the only place that assembly can happen today, and that is an open
architectural question rather than a shortcut** (MT-035 `## Out of scope`).
Import-linter contract 5 lists `app`, `cli`, `ui` *and* `pipeline` among its
`source_modules` with no `allow_indirect_imports`, and every module in
`mangatl.detect` reaches `onnxruntime` through `columns -> postprocess ->
session`. So as configured today no module in the shipped package may construct
a real detector. Tests are not part of the `mangatl` root package and no contract
governs them, which is why this file may do it. The first story that starts a
real run from the UI needs that resolved; this one does not.

**Marked `gpu` and never runs on CI** (MT-002 PO-1). The page and the weights
live under `spikes/**`, which `.gitignore` covers - a non-redistributable scan of
a commercial release and a GPL-3.0 model's weights - and a checkout without them
skips, exactly as `test_column_merge_pages.py` does through its own `_require`.
`required_gates: [integration]` in MT-035's frontmatter escalates this gate to
required on the machine running the loop, where it was measured executing 11
real tests before dispatch.

**The page is COPIED into `tmp_path` and never read in place.** `create_project`
writes `<source>.mtproj` as a sibling of the source folder (`architecture.md` §4,
D7), so intaking `spikes/MT-002/pages/` directly would create a project
directory inside the spike data. Copying one page also makes it a one-page
chapter, which is what AC-10 asks for.

**No region count is asserted, deliberately.** MT-008 measured 12 regions on
`011.jpg` before merging, on one run, which is evidence and not an oracle; a
number pinned here would be a measurement masquerading as a criterion
(MT-035 C-5, `## Out of scope`). What is asserted is `>= 1` region and that the
stored order is `sort_regions` of exactly what the detector returned - the two
facts the page can be asked about directly.

**Timings.** Building the session costs a few seconds once and one inference is
~30 ms (MT-007/MT-008 measurements), which is why the session is module-scoped.
`pytest-timeout` is not a dependency of this project and no per-test timeout
exists, so there is no budget in this file to size - if a later story adds one,
every hook here needs one too.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator, Sequence
from functools import partial
from pathlib import Path

import pytest

from mangatl.detect.page import detect_page_regions
from mangatl.detect.session import DetectorSession, load_detector
from mangatl.domain.reading_order import sort_regions
from mangatl.domain.region import RawRegion
from mangatl.pipeline.detect_stage import DetectStage
from mangatl.pipeline.stage import PageContext
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

pytestmark = pytest.mark.gpu

_SPIKES = Path(__file__).resolve().parents[2] / "spikes"
_MODEL = _SPIKES / "MT-002" / "models" / "comic-text-detector-onnx" / "comic-text-detector.onnx"
_PAGE = _SPIKES / "MT-002" / "pages" / "011.jpg"
_PROVIDERS = ("CUDAExecutionProvider", "CPUExecutionProvider")


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path} is not present: gitignored spike data, see the module docstring")


@pytest.fixture(scope="module")
def session() -> Iterator[DetectorSession]:
    _require(_MODEL)
    yield load_detector(_MODEL, _PROVIDERS)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    """`011.jpg` intaken as a one-page project under `tmp_path`."""
    _require(_PAGE)
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    shutil.copyfile(_PAGE, source_dir / _PAGE.name)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as opened:
        yield opened


class _Recording:
    """The real detector, wrapped so the test can see what it returned.

    Wrapping rather than re-running: the ordering claim compares the store
    against the detector's own output, and a second inference would let two
    different runs satisfy it.
    """

    def __init__(self, session: DetectorSession) -> None:
        self._detect = partial(detect_page_regions, session)
        self.returned: list[RawRegion] = []

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        self.returned = list(self._detect(image_bytes))
        return self.returned


def test_the_real_chain_reaches_the_store_in_reading_order(
    session: DetectorSession,
    project: Project,
) -> None:
    """AC-10. The production wiring C-2 names - `partial(detect_page_regions,
    load_detector(...))` behind a `PageDetector` - composed end to end.

    The last assertion is the one that carries the epic's sentence: what the
    store holds is `sort_regions` of exactly what the detector found, so the
    real chain's regions arrive right to left, top to bottom.
    """
    (page,) = project.pages()
    detector = _Recording(session)

    DetectStage(detect=detector).run(PageContext(project=project, page=page))

    stored = project.read_regions(page.ordinal)

    assert len(stored) >= 1, (
        f"the real detector found no text on {_PAGE.name}; no count is asserted here"
        " (MT-008's 12 is one run's measurement, not an oracle) but zero regions"
        " means the chain did not compose"
    )
    assert detector.returned, "the detector returned nothing, so the order claim is vacuous"
    assert list(stored) == sort_regions(detector.returned)
    # And the stored order is a fixed point of the ordering, which is what
    # "read_regions equals sort_regions of the same region set" says directly.
    assert sort_regions(list(stored)) == list(stored)
