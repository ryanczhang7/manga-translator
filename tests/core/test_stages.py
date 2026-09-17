"""`mangatl.pipeline.stages`: the stage list, built without a model in sight.

**AC-2.** MT-035 shipped `DetectStage` and MT-010 shipped `OcrStage`, both
correct and neither in any stage list. `build_stages` is the list, and the
reason it is a module of its own in `pipeline` rather than four lines of the
composition root is C-1: *the list is a pipeline fact, the sessions are not*.
That is what makes every assertion below runnable in `tests/core`, which three
required gates read, on a machine with no GPU and no weights.

Two conventions here are load-bearing rather than stylistic:

- **The order is asserted twice: once by name and once by behaviour.**
  `(DetectStage, OcrStage)` is a tuple comparison anyone can read, and it is
  also the weaker of the two: a list built in the wrong order is still a list of
  the right two things. `OcrStage.run` reads `ctx.project.read_regions(...)`, so
  the reversed order transcribes the *previous* run's regions on a resume and
  nothing at all on a fresh page - which is C-1's own justification and is
  visible only by running the built list over a real store. Both are here
  because only the second survives someone deciding the order is cosmetic.
- **The module's own imports are read out of its AST**, the idiom
  `tests/core/test_detect_stage.py` set for the same seam. "Asserted without
  loading a model" is a claim about what this module may import, and a
  `sys.modules` probe cannot make it: by the time any test runs, the import has
  already happened, and a sibling test file in this directory legitimately
  imports `mangatl.compose` and therefore `onnxruntime`.

What these tests do NOT constrain: whether `build_stages` is a function or a
callable object, whether the two stages are constructed positionally or by
keyword, and what `Stage`'s concrete implementations do beyond what MT-035 and
MT-010 already pinned. The return *type* is `tuple[Stage, ...]` by C-1, so a
third stage is a one-line change in GREEN's file and nothing here objects.
"""

from __future__ import annotations

import ast
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.detect_stage import DetectStage
from mangatl.pipeline.ocr_stage import OcrStage
from mangatl.pipeline.runner import RUN_FINISHED, run_chapter
from mangatl.pipeline.stages import build_stages
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
)

#: C-1 pins the two names the events carry. Spelled out here rather than read
#: off the classes, so a stage renamed in `detect_stage.py` shows up as a change
#: to the pipeline's vocabulary instead of agreeing with itself.
_DETECT = "detect"
_OCR = "ocr"


# -- doubles -------------------------------------------------------------------


def _mask(one_bit_png: Callable[..., bytes]) -> bytes:
    return one_bit_png(8, 8, [(0, 0, 4, 4)])


def _region(mask: bytes, x: int, y: int) -> RawRegion:
    """A closed-ring square region with its top-left corner at `(x, y)`."""
    ring = ((x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4), (x, y))
    return RawRegion(polygon=ring, mask=mask, confidence=1.0, kind="bubble")


class _Detector:
    """A `PageDetector`: page bytes in, a fixed pair of regions out."""

    def __init__(self, mask: bytes) -> None:
        self.mask = mask
        self.calls = 0

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        self.calls += 1
        return (_region(self.mask, 0, 0), _region(self.mask, 10, 10))


class _Transcriber:
    """A `PageTranscriber` that records how many regions it was handed.

    The recording is the whole point of the behavioural order test: a stage list
    that runs OCR first hands this zero regions on a fresh page, and a
    transcriber that never sees a region is indistinguishable from one that was
    never called unless somebody writes the number down.
    """

    def __init__(self) -> None:
        self.region_counts: list[int] = []

    def __call__(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
        self.region_counts.append(len(regions))
        return tuple(OcrResult(text=f"text-{index}") for index in range(len(regions)))


def _never() -> bool:
    return False


# -- helpers -------------------------------------------------------------------


def _build_source(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for filename, width, height in _SOURCE_PAGES:
        (source_dir / filename).write_bytes(png_bytes(width, height))
    return source_dir


def _new_project(source_dir: Path) -> Project:
    return create_project(read_chapter(source_dir), project_dir_for(source_dir))


def _raw(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    """Read the project file with a plain `sqlite3` connection.

    `test_pipeline.py`'s convention, for its reason: a write path and a read
    path that are wrong in the same direction cannot hide from an observer that
    shares neither's assumptions.
    """
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


# -- AC-2: the list itself ------------------------------------------------------


def test_the_stage_list_is_detect_then_ocr_and_holds_nothing_else(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-2's first clause: `(DetectStage, OcrStage)`, in that order."""
    detector = _Detector(_mask(one_bit_png))
    transcriber = _Transcriber()

    stages = build_stages(detector, transcriber)

    assert [type(stage) for stage in stages] == [DetectStage, OcrStage], (
        f"the stage list is {[type(stage).__name__ for stage in stages]};"
        " C-1 pins detect then OCR, and the order is semantic - OCR before"
        " detect reads the previous run's regions, or none at all"
    )


def test_the_stage_list_is_a_tuple_rather_than_a_mutable_sequence(
    one_bit_png: Callable[..., bytes],
) -> None:
    """C-1 says `tuple`, and a list here would let a caller append a stage to
    the pipeline's own definition after it was built."""
    stages = build_stages(_Detector(_mask(one_bit_png)), _Transcriber())

    assert type(stages) is tuple, f"build_stages returned a {type(stages).__name__}"


def test_each_stage_is_named_the_way_the_events_will_report_it(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-2's second clause. The names are what `StageFinished.stage` carries
    and what MT-018's progress readout will show a user."""
    stages = build_stages(_Detector(_mask(one_bit_png)), _Transcriber())

    assert [stage.name for stage in stages] == [_DETECT, _OCR]


def test_each_stage_holds_the_callable_it_was_given_and_not_the_other_one(
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-2's third clause, asserted by identity.

    Two *different* callables, and `is` rather than `==`: a builder that
    constructed its own detector, or that wired the transcriber into both
    stages, would satisfy a looser check.
    """
    detector = _Detector(_mask(one_bit_png))
    transcriber = _Transcriber()

    detect_stage, ocr_stage = build_stages(detector, transcriber)

    assert detect_stage.detect is detector
    assert ocr_stage.transcribe is transcriber


def test_every_stage_in_the_list_satisfies_the_stage_protocol(
    one_bit_png: Callable[..., bytes],
) -> None:
    """`Stage` is a `Protocol`, so there is no base class to assert against; the
    three members the runner calls are the whole of it."""
    stages = build_stages(_Detector(_mask(one_bit_png)), _Transcriber())

    assert len(stages) == 2
    for stage in stages:
        assert isinstance(stage.name, str) and stage.name
        assert callable(stage.run)
        assert callable(stage.is_done)


def test_the_module_exports_the_builder_and_nothing_else() -> None:
    import mangatl.pipeline.stages as module

    assert module.__all__ == ["build_stages"]


# -- AC-2: "without loading a model", as a property of the module's imports -----


def test_the_stage_list_module_imports_nothing_that_reaches_onnxruntime() -> None:
    """C-1's reason for this module existing, as a unit tripwire.

    `build_stages` lives in `pipeline` and may import `pipeline.detect_stage`
    and `pipeline.ocr_stage` and nothing heavier. Both of those already carry
    this tripwire of their own (MT-035, MT-010); this one is what stops the
    *list* from being the place someone reaches for `mangatl.detect` to spell a
    type - which would drag `onnxruntime` into `mangatl.pipeline` and break the
    contract three gates read, and would make AC-2's "without loading a model"
    false while every assertion above still passed.

    The module's own imports are read out of its AST, so the docstring may
    discuss `mangatl.detect` freely.
    """
    import mangatl.pipeline.stages as module

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
        for root in (
            "mangatl.detect",
            "mangatl.ocr",
            "mangatl.compose",
            "onnxruntime",
            "numpy",
            "PIL",
            "cv2",
        )
        if name == root or name.startswith(f"{root}.")
    )
    assert forbidden == [], (
        f"{forbidden} is imported by mangatl.pipeline.stages. Contract 5 forbids"
        " mangatl.pipeline from reaching onnxruntime even indirectly, and every"
        " module in mangatl.detect and mangatl.ocr reaches it. The stage list"
        " names its collaborators behind PageDetector and PageTranscriber; the"
        " sessions belong to mangatl.compose (C-1, C-2)."
    )


# -- AC-2: the order is semantic, not cosmetic ---------------------------------


def test_the_built_order_lets_ocr_transcribe_the_regions_detect_has_just_written(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> None:
    """C-1's justification for the order, run rather than asserted by name.

    A fresh page has no regions in the store. `OcrStage.run` reads
    `ctx.project.read_regions(...)`, so if the built list runs OCR first the
    transcriber is handed an empty sequence, writes nothing, and the `line`
    table stays empty while every name-and-type assertion above still passes.
    This is the test that fails on a reversed list, and it is the `tests/core`
    half of deferred verification DV-4's first mutation.
    """
    source_dir = _build_source(tmp_path, png_bytes)
    db_path = project_dir_for(source_dir) / "project.db"
    detector = _Detector(_mask(one_bit_png))
    transcriber = _Transcriber()

    with _new_project(source_dir) as project:
        outcome = run_chapter(
            project, build_stages(detector, transcriber), lambda event: None, _never
        )

    assert outcome.outcome == RUN_FINISHED
    assert detector.calls == len(_SOURCE_PAGES)
    assert transcriber.region_counts == [2, 2], (
        "the transcriber was handed"
        f" {transcriber.region_counts} regions per page instead of [2, 2]: OCR ran"
        " before the regions it reads out of the store had been written"
    )
    stored = _raw(
        db_path,
        "SELECT page.ordinal, region.reading_index, line.source_ja"
        " FROM line JOIN region ON region.id = line.region_id"
        " JOIN page ON page.id = region.page_id"
        " ORDER BY page.ordinal, region.reading_index",
    )
    assert stored == [
        (0, 0, "text-0"),
        (0, 1, "text-1"),
        (1, 0, "text-0"),
        (1, 1, "text-1"),
    ]
