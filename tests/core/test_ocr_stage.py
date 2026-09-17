"""`mangatl.pipeline.ocr_stage`: the stage that writes a page's lines.

Covers **AC-9** in full: one line per region written positionally against
`reading_index`, in **one** write at the end, with `is_done` true only for a page
that already has lines.

**The module is `pipeline/ocr_stage.py` and not `ocr/stage.py`, and that is
forced by a required gate rather than chosen for taste** (C-1, measured in
PLANNED and re-checked in RED against `pyproject.toml`). Two contracts bite:

* the `layers` contract puts `mangatl.ocr` *below* `mangatl.pipeline`, so a stage
  living in `mangatl.ocr` may not import `PageContext` at all -

      mangatl.ocr is not allowed to import mangatl.pipeline:
      - mangatl.ocr._probe_layers -> mangatl.pipeline.stage (l.2)

* and the `forbidden` contract *"Only detect, ocr and clean import onnxruntime"*
  lists `mangatl.pipeline` among its `source_modules` with no
  `allow_indirect_imports`, while `ocr.page` reaches `onnxruntime` through
  `ocr.session`. So the stage may not import `mangatl.ocr` **either**, not even
  under `TYPE_CHECKING`, and not inside a function body - import-linter reports
  those too (PO-4 measured it on `cli.py`).

`OcrStage` therefore names its collaborator behind `PageTranscriber`, a plain
`Callable` whose three halves are stdlib, `domain` and `domain` - exactly as
`DetectStage` names `PageDetector` (MT-035 C-1/C-3).
`test_the_stage_module_imports_nothing_the_two_contracts_forbid` is the `unit`
tripwire for it, so the constraint is falsifiable before `lint` sees it.

**This file mirrors `tests/core/test_detect_stage.py` deliberately**, including
its AST read of the module's own imports and its choice of a target page that is
**not ordinal 0**. Both were paid for once already and the reasons have not
changed.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. The dominant cost is `conftest._one_bit_png`
(MT-009: 281 ms page-sized, 7 ms small), so the fixture pages are 30-50 px wide.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args, get_origin

import pytest

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.ocr_stage import OcrStage, PageTranscriber
from mangatl.pipeline.stage import PageContext
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

# -- the fixture chapter -------------------------------------------------------

#: Three pages at three distinct sizes, so every page's bytes differ and "the
#: page's OWN bytes" is a claim with something to be false about.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

#: The page every criterion runs against, and it is **not ordinal 0**, for the
#: reason MT-035 DV-3 records: GATES mutates `write_lines(ctx.page.ordinal, ...)`
#: to `write_lines(0, ...)` - one token, a plausible typo, nothing omitted - and
#: the test can only catch it if the page under test sits somewhere other than 0.
_TARGET_ORDINAL = 1
_PAGE_WIDTH, _PAGE_HEIGHT = _SOURCE_PAGES[_TARGET_ORDINAL][1], _SOURCE_PAGES[_TARGET_ORDINAL][2]

#: `OcrStage.name`, pinned as a literal because the event stream carries it and
#: `architecture.md` §5's stage list names it.
_OCR = "ocr"


class _TranscriberExploded(Exception):
    """AC-9's injected inference failure.

    A bespoke type, so the test cannot pass by catching a real error raised
    somewhere else for another reason.
    """


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@dataclass(frozen=True)
class _Fixture:
    source_dir: Path
    project: Project
    mask: bytes

    @property
    def context(self) -> PageContext:
        return self.page_context(_TARGET_ORDINAL)

    def page_context(self, ordinal: int) -> PageContext:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return PageContext(project=self.project, page=page)

    @property
    def regions(self) -> tuple[RawRegion, ...]:
        """Three regions **already in reading order**, as the detect stage left
        them.

        Ordering is MT-009's and MT-035's; this stage inherits it from the store
        and must not re-derive it. Three distinct rectangles so the store's
        `reading_index` has something to be wrong about.
        """
        return (
            RawRegion(polygon=_ring(20, 2, 30, 8), mask=self.mask, confidence=0.5, kind="bubble"),
            RawRegion(polygon=_ring(2, 2, 12, 8), mask=self.mask, confidence=0.75, kind="bubble"),
            RawRegion(polygon=_ring(2, 20, 12, 28), mask=self.mask, confidence=0.25, kind="box"),
        )

    def seed_regions(self, ordinal: int = _TARGET_ORDINAL) -> tuple[RawRegion, ...]:
        self.project.write_regions(ordinal, self.regions)
        return self.regions


#: Three results whose texts are distinct, in no sorted order, and one of which
#: is the `ocr_empty` case - so AC-9's positional claim, AC-4's flag and the
#: store's NOT NULL `source_ja` are all exercised by one write.
_RESULTS: tuple[OcrResult, ...] = (
    OcrResult(text="醜鬼が人間の言う通りに動いたりね"),
    OcrResult(text="", ocr_empty=True),
    OcrResult(text="……なるほど"),
)


@pytest.fixture
def fixture(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> Iterator[_Fixture]:
    """A three-page project on `tmp_path`, scans in a `scans/` subfolder.

    A subfolder rather than `tmp_path` itself, so `<source>.mtproj` and
    `<source>_en` are also inside `tmp_path` and the test leaves nothing outside
    its own directory - `test_detect_stage.py` and `test_pipeline.py` both make
    the same choice.
    """
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _Fixture(
            source_dir=source_dir,
            project=project,
            mask=one_bit_png(_PAGE_WIDTH, _PAGE_HEIGHT, [(0, 0, 4, 4)]),
        )


class _FakeTranscriber:
    """A `PageTranscriber`: page bytes and regions in, results out.

    Records every call, because AC-9 is a claim about the call count, about the
    exact bytes and about the exact regions - and, in the `is_done` case, that
    there was no call at all.
    """

    def __init__(
        self,
        results: Sequence[OcrResult] = (),
        *,
        explode: bool = False,
    ) -> None:
        self._results = list(results)
        self._explode = explode
        self.seen: list[tuple[bytes, tuple[RawRegion, ...]]] = []

    @property
    def calls(self) -> int:
        return len(self.seen)

    def __call__(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
        self.seen.append((image_bytes, tuple(regions)))
        if self._explode:
            raise _TranscriberExploded("boom-in-the-transcriber")
        return list(self._results)


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of contents, or None for a directory.

    Directories are included, over `rglob("*")`, so a scratch folder appearing
    beside the scans fails as loudly as an edited file would.
    """
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


# -- the module's shape --------------------------------------------------------


def test_the_stage_is_exported_from_mangatl_pipeline_ocr_stage_under_that_name(
    fixture: _Fixture,
) -> None:
    """C-1's module path, `__all__`, field name and stage name, pinned exactly.

    The module path is the criterion here, not decoration: `src/mangatl/ocr/
    stage.py` was what the story was filed with and it **cannot exist** (see the
    module docstring). An import error from this line is the first thing GREEN
    should read.
    """
    import mangatl.pipeline.ocr_stage as module

    assert module.__all__ == ["OcrStage", "PageTranscriber"]

    transcriber = _FakeTranscriber()
    stage = OcrStage(transcribe=transcriber)

    assert stage.name == _OCR
    assert stage.transcribe is transcriber
    assert callable(stage.run)
    assert callable(stage.is_done)
    assert isinstance(stage.is_done(fixture.context), bool)


def test_the_stage_name_is_a_settable_instance_attribute_as_the_protocol_requires() -> None:
    """`Stage.name: str` is a settable protocol member and mypy holds a class to
    it (MT-035 amendment R-1, measured twice there):

        Protocol member Stage.name expected settable variable,
        got read-only attribute        # @dataclass(frozen=True), name: str
        Protocol member Stage.name expected instance variable,
        got class variable             # @dataclass(frozen=True), name: ClassVar[str]

    So `OcrStage` must be a plain `@dataclass`, as C-1 writes it and as
    `DetectStage` is. Assignment is the one runtime-visible consequence of
    "settable"; nothing should ever rename a live stage, the point is that it
    could.
    """
    stage = OcrStage(transcribe=_FakeTranscriber())

    stage.name = "renamed"

    assert stage.name == "renamed"


def test_the_page_transcriber_alias_is_bytes_and_regions_in_and_results_out() -> None:
    """C-1's `PageTranscriber`, introspected rather than trusted.

    This is the type that keeps `pipeline` clean: `bytes` is stdlib and both
    `RawRegion` and `OcrResult` are `domain`, so naming the transcriber costs
    `pipeline` no import of `mangatl.ocr` and therefore none of `onnxruntime`.

    Asserted through `get_origin`/`get_args` so the claim is about the alias's
    meaning and not about which module `Sequence` and `Callable` were imported
    from - `typing.Sequence[X]` and `collections.abc.Sequence[X]` are unequal
    objects that answer these questions identically (`test_detect_stage.py`
    verified that in MT-035 RED).
    """
    assert get_origin(PageTranscriber) is Callable

    parameters, returned = get_args(PageTranscriber)

    assert len(parameters) == 2
    assert parameters[0] is bytes
    assert get_origin(parameters[1]) is Sequence
    assert get_args(parameters[1]) == (RawRegion,)
    assert get_origin(returned) is Sequence
    assert get_args(returned) == (OcrResult,)


def test_the_stage_module_imports_nothing_the_two_contracts_forbid() -> None:
    """C-1's seam, as a `unit` tripwire rather than only as two `lint` contracts.

    The failure this prevents is cheap to make and expensive to diagnose: an
    implementer reaching for `mangatl.ocr.page.transcribe_page_regions` to build
    a default, or for `OcrSession` to type a parameter, gets told which import
    broke the seam by name, in the phase that added it - rather than a four-line
    indirect chain from `lint-imports` two phases later.

    The module's own imports are read out of its AST, so the docstring may
    discuss `mangatl.ocr` freely - which C-1 requires it to.
    """
    import mangatl.pipeline.ocr_stage as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    forbidden = sorted(
        name
        for name in imported
        for root in ("mangatl.ocr", "numpy", "PIL", "cv2", "onnxruntime", "jaconv")
        if name == root or name.startswith(f"{root}.")
    )
    assert forbidden == [], (
        f"{forbidden} is imported by mangatl.pipeline.ocr_stage. The layers contract"
        " puts mangatl.ocr BELOW mangatl.pipeline, and contract 5 forbids"
        " mangatl.pipeline from reaching onnxruntime even indirectly - which"
        " mangatl.ocr.page does, through mangatl.ocr.session. If the stage wants one"
        " of these, the seam is in the wrong place; see MT-010 C-1."
    )


# -- AC-9: one line per region, positionally against reading_index -------------


def test_each_regions_text_is_written_against_its_own_reading_index(
    fixture: _Fixture,
) -> None:
    """AC-9's first clause, read back through the store.

    Position is the only carrier: `results[i]` belongs to the region at
    `reading_index == i`, because a `RawRegion` holds no id of its own (MT-009
    PO-1) and `write_lines` derives the index from the position it was handed.
    The three results are distinct and in no sorted order, so a stage that
    reversed them, sorted them or wrote one of them three times fails on content.

    Also pins C-1's "the stage opens no transaction": `write_lines` opens its own
    and `Project.transaction()` is deliberately not reentrant (MT-005 PO-5), so a
    stage that wrapped the write raises `RuntimeError` here.
    """
    fixture.seed_regions()
    transcriber = _FakeTranscriber(_RESULTS)

    OcrStage(transcribe=transcriber).run(fixture.context)

    stored = fixture.project.read_lines(_TARGET_ORDINAL)

    assert list(stored) == list(_RESULTS)
    assert stored[0].text == "醜鬼が人間の言う通りに動いたりね"
    assert stored[1] == OcrResult(text="", ocr_empty=True)
    assert stored[2].text == "……なるほど"
    # Per page, not per chapter: the other two pages have no regions and no lines.
    assert fixture.project.read_lines(0) == ()
    assert fixture.project.read_lines(2) == ()


def test_the_transcriber_is_called_once_with_the_pages_own_bytes_and_stored_regions(
    fixture: _Fixture,
) -> None:
    """AC-9's second clause. One call per page, on the file the page names, with
    the regions **the store holds** rather than a freshly detected set.

    That last part is the seam between this stage and MT-035's: OCR runs over
    what detection already wrote, in the order it was written, so a resumed run
    transcribes the same regions the user will see highlighted. A stage that
    re-detected would need a detector, and would put `onnxruntime` back inside
    `pipeline`.

    The "not another page's bytes" assertion is what makes it a claim about
    *this* page: a stage that read `pages()[0]` every time passes on a one-page
    chapter and on any chapter whose pages happen to be equal.
    """
    regions = fixture.seed_regions()
    transcriber = _FakeTranscriber(_RESULTS)
    context = fixture.context

    OcrStage(transcribe=transcriber).run(context)

    expected_bytes = (fixture.source_dir / context.page.filename).read_bytes()
    assert transcriber.calls == 1, f"the transcriber ran {transcriber.calls} times, not once"
    seen_bytes, seen_regions = transcriber.seen[0]
    assert seen_bytes == expected_bytes
    assert seen_regions == regions
    others = {
        page.filename: (fixture.source_dir / page.filename).read_bytes()
        for page in fixture.project.pages()
        if page.ordinal != _TARGET_ORDINAL
    }
    assert seen_bytes not in others.values(), (
        f"the transcriber was handed some other page's bytes; page {_TARGET_ORDINAL} is"
        f" {context.page.filename}, and the chapter also holds {sorted(others)}"
    )


def test_running_the_stage_leaves_the_users_scans_byte_for_byte_unchanged(
    fixture: _Fixture,
) -> None:
    """`architecture.md` §5: the source folder is read-only to this app, always -
    and that is the promise a user's only copy of a scan depends on.

    Inherited from MT-035 AC-2 rather than restated as a new criterion, because
    this stage reads the same file the same way and the guarantee is the one a
    user cares about most.
    """
    fixture.seed_regions()
    before = _snapshot(fixture.source_dir)
    assert before, "the snapshot is empty, so it cannot detect a change"

    OcrStage(transcribe=_FakeTranscriber(_RESULTS)).run(fixture.context)

    assert _snapshot(fixture.source_dir) == before


# -- AC-9: one write, at the end -----------------------------------------------


def test_a_transcriber_that_raises_leaves_the_pages_stored_lines_untouched(
    fixture: _Fixture,
) -> None:
    """AC-9's "in one write at the end", and the only criterion that catches a
    stage which clears first.

    A stage that opened with `write_lines(ordinal, ())` - or that wrote each
    result as it arrived - would satisfy every other assertion in this file and
    destroy a page's translations every time an inference failed. OCR runs after
    detection and before translation, so by the time a user re-runs a chapter
    those `line` rows may carry `proposed_en` and `final_en` that cost real money
    (`architecture.md` §4/§6).

    The propagation is asserted and nothing more: `run_chapter` emitting
    `RunAborted` naming the page is MT-006 AC-4's.
    """
    fixture.seed_regions()
    OcrStage(transcribe=_FakeTranscriber(_RESULTS)).run(fixture.context)
    before = fixture.project.read_lines(_TARGET_ORDINAL)
    assert len(before) == 3, "the fixture must already hold a previous run's lines"

    exploding = _FakeTranscriber(explode=True)
    with pytest.raises(_TranscriberExploded):
        OcrStage(transcribe=exploding).run(fixture.context)

    assert exploding.calls == 1
    assert fixture.project.read_lines(_TARGET_ORDINAL) == before


def test_a_rerun_replaces_the_pages_lines_rather_than_doubling_them(
    fixture: _Fixture,
) -> None:
    """AC-9 under a resume, which is the case the store's UNIQUE key makes sharp.

    `line.region_id` is `UNIQUE`, so a stage that appended would raise
    `IntegrityError` on the second run of any page - turning "re-run this
    chapter" into a crash. The second run's text is what survives, because it is
    the more recent read of the page.
    """
    fixture.seed_regions()
    OcrStage(transcribe=_FakeTranscriber(_RESULTS)).run(fixture.context)

    second = (OcrResult(text="一"), OcrResult(text="二"), OcrResult(text="三"))
    OcrStage(transcribe=_FakeTranscriber(second)).run(fixture.context)

    stored = fixture.project.read_lines(_TARGET_ORDINAL)

    assert list(stored) == list(second)
    assert len(stored) == 3


# -- AC-9: is_done ---------------------------------------------------------------


def test_is_done_is_true_only_for_a_page_that_already_has_lines(
    fixture: _Fixture,
) -> None:
    """AC-9's third clause, as a truth table on one page so nothing else differs.

    "Has lines" and not "has regions": regions are what the *detect* stage writes
    and `DetectStage.is_done` already reads (MT-035 C-6). A page with regions and
    no lines is exactly the state a resumed run must pick up at, and a stage that
    confused the two would skip every page detection had reached and never OCR
    anything.
    """
    stage = OcrStage(transcribe=_FakeTranscriber(_RESULTS))
    context = fixture.context

    assert stage.is_done(context) is False, "a page with nothing stored is not done"

    fixture.seed_regions()

    assert stage.is_done(context) is False, (
        "a page with regions but no lines reads as done, so a resumed run would"
        " skip every page detection reached and never transcribe anything"
    )

    stage.run(context)

    assert stage.is_done(context) is True, "a page whose lines are in the store is done"
    # And it is per page, not per chapter.
    assert stage.is_done(fixture.page_context(0)) is False
    assert stage.is_done(fixture.page_context(2)) is False


def test_a_page_whose_regions_all_read_empty_is_still_done(fixture: _Fixture) -> None:
    """The boundary between AC-4 and AC-9, and the reason `ocr_empty` is stored.

    Three regions the model emitted nothing for still produce three `line` rows,
    so the page is done and is not re-transcribed on every run. Contrast MT-035
    AC-5, where a page with **no regions** is deliberately never done: there the
    stage writes nothing at all, so there is nothing to read back. Here the stage
    does write, and the flag is what distinguishes "read nothing" from "not yet
    read" (C-5, PO-3).
    """
    fixture.seed_regions()
    empties = (OcrResult(text="", ocr_empty=True),) * 3
    stage = OcrStage(transcribe=_FakeTranscriber(empties))

    stage.run(fixture.context)

    assert list(fixture.project.read_lines(_TARGET_ORDINAL)) == list(empties)
    assert stage.is_done(fixture.context) is True, (
        "a page every region of which read empty is not done, so it would be"
        " re-transcribed on every run - and ocr_empty would carry no information"
    )


def test_a_page_with_no_regions_writes_no_lines_and_stays_not_done(
    fixture: _Fixture,
) -> None:
    """The empty boundary, and it is a real page: MT-035 AC-5 ships the case of a
    page the detector genuinely finds no text on.

    Two things must hold and only one of them is obvious. No lines, clearly. But
    also **not done** - so the page is re-considered on the next run, matching
    `DetectStage`'s own decision for the same page (MT-035 C-6). A stage that
    reported such a page done would freeze a detector miss permanently: the
    detector would keep re-running the page, find text after a later fix, and OCR
    would never look at it again.

    Whether the transcriber is called at all with an empty sequence is left to
    GREEN - `transcribe_page_regions` over no regions performs no inference
    either way (`test_ocr_page.py` pins that), so there is nothing here worth
    forcing a branch for. What is pinned is that it is not handed some *other*
    page's regions.
    """
    transcriber = _FakeTranscriber(())
    stage = OcrStage(transcribe=transcriber)
    context = fixture.context
    assert fixture.project.read_regions(_TARGET_ORDINAL) == ()

    stage.run(context)

    assert fixture.project.read_lines(_TARGET_ORDINAL) == ()
    assert stage.is_done(context) is False
    assert all(regions == () for _bytes, regions in transcriber.seen), (
        f"a page with no stored regions handed the transcriber {transcriber.seen}"
    )
