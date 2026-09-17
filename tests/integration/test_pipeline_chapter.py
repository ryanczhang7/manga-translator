"""AC-4: `mangatl-run` over a real chapter, with the real weights.

**Why this criterion cannot be met anywhere else.** Everything else in MT-036
runs against callables in `tests/core` and is read by three required gates
(`architecture.md` §2). What no fake can show is the thing EPIC-03's done-when
actually promises: that *a command a user can type* walks a folder of scans
through the real detector and the real OCR export and leaves the chapter's text
in the store. MT-035 PO-1 predicted that a correct stage nothing invokes would
recur one stage later, and it did; this file is what makes the prediction
falsifiable for the composed pipeline.

**The subject is the pipeline, not OCR quality.** Every number here was settled
by MT-002 E5 or MT-010 and is read out rather than re-derived (C-7): five
fixture pages, nine regions on `014.jpg`, the nine transcriptions committed as
`_GROUND_TRUTH` in `test_ocr_session.py`, and `OCR_MIN_ACCURACY` exported by
`mangatl.ocr.page`. Nothing here chooses a threshold, and nothing here may lower
one - MT-010 owns OCR quality and a new threshold invented in this story would
be a re-litigation of MT-010's.

**The ground truth and the metric are imported from `test_ocr_session.py`, not
retyped.** Two copies of nine hand-annotated Japanese strings are two things to
keep in step, and a transcription error in the second copy would look exactly
like a pipeline defect. C-7 sanctions the import.

**The models directory is assembled here, not by `compose`.** The spike tree
does not have C-6's shape - the OCR graphs are under
`.../manga-ocr-base-ONNX/onnx/` and the vocabulary is in a sibling checkout - so
this file hard-links a conforming directory together exactly as
`test_ocr_session.py` already does, and adds the detector to it. Assembling it
is the integration test's job; MT-024 owns the real model manifest.

**The data is gitignored and these tests skip cleanly without it**, the same as
every other file in this directory.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size - the note
`test_ocr_session.py` and `test_detector_session.py` both carry. Every fixture
below is module-scoped, so the five pages are detected once and transcribed
once for the whole file. If a later story adds a timeout, every test *and every
hook* here needs one, sized from a CI log rather than from this machine.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_ocr_session import _GROUND_TRUTH, _accuracy, _normalised

from mangatl.cli import main
from mangatl.compose import DETECTOR_FILENAME, OCR_SUBDIR
from mangatl.domain.reading_order import sort_regions
from mangatl.ocr.page import OCR_MIN_ACCURACY
from mangatl.ocr.session import DECODER_FILENAME, ENCODER_FILENAME, VOCAB_FILENAME
from mangatl.store.project import open_project, project_dir_for

pytestmark = pytest.mark.gpu

_SPIKES = Path(__file__).resolve().parents[2] / "spikes"
_PAGES = _SPIKES / "MT-002" / "pages"
_DETECTOR_SRC = (
    _SPIKES / "MT-002" / "models" / "comic-text-detector-onnx" / "comic-text-detector.onnx"
)
_ONNX_DIR = _SPIKES / "MT-002" / "models" / "manga-ocr-base-ONNX" / "onnx"
_VOCAB_SRC = _SPIKES / "MT-002" / "models" / "manga-ocr-base" / "vocab.txt"

#: The chapter, in filename order - which `read_chapter` makes intake order, and
#: intake order is ordinal order. Five pages (C-7).
_CHAPTER: tuple[str, ...] = ("011.jpg", "012.jpg", "013.jpg", "014.jpg", "015.jpg")

#: The page `_GROUND_TRUTH` is keyed to. Its ordinal is **derived from the store**
#: below rather than written here as `3`: "the fourth page of the chapter" is a
#: fact about intake, and hard-coding it would make a re-ordered intake look like
#: an OCR failure (C-7).
_ANNOTATED_PAGE = "014.jpg"


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path} is not present: gitignored spike data, see the module docstring")


def _link_or_copy(source: Path, target: Path) -> None:
    """Hard link where the platform allows it; the encoder alone is 343 MB."""
    try:
        target.hardlink_to(source)
    except OSError:
        target.write_bytes(source.read_bytes())


@pytest.fixture(scope="module")
def models_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory laid out exactly the way C-6 draws it.

    `<models>/comic-text-detector.onnx` and `<models>/manga-ocr/{encoder,
    decoder,vocab}`. The four names come from `compose` and `ocr.session`'s own
    exported constants - re-spelling them here would let this test keep passing
    against a `build_pipeline` looking for something else.
    """
    for source in (_DETECTOR_SRC, _ONNX_DIR / ENCODER_FILENAME, _ONNX_DIR / DECODER_FILENAME):
        _require(source)
    _require(_VOCAB_SRC)

    directory = tmp_path_factory.mktemp("models")
    _link_or_copy(_DETECTOR_SRC, directory / DETECTOR_FILENAME)
    ocr_dir = directory / OCR_SUBDIR
    ocr_dir.mkdir()
    _link_or_copy(_ONNX_DIR / ENCODER_FILENAME, ocr_dir / ENCODER_FILENAME)
    _link_or_copy(_ONNX_DIR / DECODER_FILENAME, ocr_dir / DECODER_FILENAME)
    _link_or_copy(_VOCAB_SRC, ocr_dir / VOCAB_FILENAME)
    return directory


@pytest.fixture(scope="module")
def chapter_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The five fixture scans in a folder of their own.

    A folder *inside* the temporary root, so that `<folder>.mtproj` and
    `<folder>_en` - both siblings - also land inside it and the run leaves
    nothing outside its own directory. The scans themselves are never written
    to: `architecture.md` §5, and `test_cli.py` asserts it.
    """
    for filename in _CHAPTER:
        _require(_PAGES / filename)

    root = tmp_path_factory.mktemp("chapter")
    source_dir = root / "scans"
    source_dir.mkdir()
    for filename in _CHAPTER:
        _link_or_copy(_PAGES / filename, source_dir / filename)
    return source_dir


@pytest.fixture(scope="module")
def completed_run(chapter_dir: Path, models_dir: Path) -> int:
    """One `mangatl-run` over the chapter, once for the whole module.

    `main([...])` in process rather than the console script, for the reason
    `test_cli.py` gives: shelling out tests the installer. This is the only
    place in the suite where the whole thing runs - argument parsing, the
    composition root, real sessions, the runner, both stages and the store.
    """
    return main([str(chapter_dir), "--models", str(models_dir)])


def _db(chapter_dir: Path) -> Path:
    return project_dir_for(chapter_dir) / "project.db"


def _query(chapter_dir: Path, sql: str) -> list[tuple[object, ...]]:
    """Read the project file with a plain `sqlite3` connection.

    `test_pipeline.py`'s convention and for its reason: a write path and a read
    path that are wrong in the same direction cannot hide from an observer that
    shares neither's assumptions. The whole point of AC-4 is that a *stored*
    chapter is what the next stage and the user will see.
    """
    connection = sqlite3.connect(_db(chapter_dir))
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _ordinal_of(chapter_dir: Path, filename: str) -> int:
    rows = _query(chapter_dir, f"SELECT ordinal FROM page WHERE filename = '{filename}'")
    assert len(rows) == 1, f"{filename} is in the chapter {len(rows)} times"
    return int(rows[0][0])


# -- AC-4: the run completes ---------------------------------------------------


def test_a_run_over_the_real_chapter_completes_and_records_a_finished_run(
    completed_run: int, chapter_dir: Path
) -> None:
    """The precondition every assertion below rests on, asserted separately so
    that a run which aborted reads as "the run aborted" rather than as an empty
    table."""
    assert completed_run == 0, "mangatl-run over the fixture chapter did not exit 0"

    outcomes = [row[0] for row in _query(chapter_dir, "SELECT outcome FROM run ORDER BY id")]
    assert outcomes == ["finished"]
    assert len(_query(chapter_dir, "SELECT ordinal FROM page")) == len(_CHAPTER)


def test_the_chapter_is_the_five_fixture_pages_in_filename_order(
    completed_run: int, chapter_dir: Path
) -> None:
    """C-7's ordinal mapping, derived rather than assumed.

    Filename order is intake order is ordinal order, and `014.jpg` is the third
    of five counting from zero. Asserted here once so the tests below can ask
    the store for the ordinal instead of writing `3`.
    """
    filenames = [
        str(row[0]) for row in _query(chapter_dir, "SELECT filename FROM page ORDER BY ordinal")
    ]

    assert filenames == list(_CHAPTER)
    assert _ordinal_of(chapter_dir, _ANNOTATED_PAGE) == 3


# -- AC-4: every page has regions, every region has a line ---------------------


def test_every_page_has_regions_and_every_region_has_a_line(
    completed_run: int, chapter_dir: Path
) -> None:
    """**AC-4's first clause**, over all five pages rather than the annotated
    one.

    A page with no regions is a detect stage that ran and found nothing; a
    region with no line is an OCR stage that did not run, or ran on the wrong
    page. Either is what "the pipeline produces regions ... each carrying
    transcribed vertical Japanese" is false about, and neither is visible in an
    assertion about `014.jpg` alone.
    """
    per_page = {
        str(filename): (int(regions), int(lines))
        for filename, regions, lines in _query(
            chapter_dir,
            "SELECT page.filename, COUNT(region.id), COUNT(line.id)"
            " FROM page LEFT JOIN region ON region.page_id = page.id"
            " LEFT JOIN line ON line.region_id = region.id"
            " GROUP BY page.id ORDER BY page.ordinal",
        )
    }

    assert sorted(per_page) == sorted(_CHAPTER)
    pageless = sorted(name for name, (regions, _lines) in per_page.items() if regions == 0)
    assert pageless == [], f"{pageless} came out of the run with no regions at all"
    untranscribed = sorted(
        (name, regions - lines) for name, (regions, lines) in per_page.items() if lines != regions
    )
    assert untranscribed == [], (
        f"{untranscribed} - (page, regions with no line). Every region the detect"
        " stage stored must carry the OCR stage's transcription; a region without"
        " one is a stage that did not run over it."
    )


def test_every_pages_regions_are_stored_in_reading_order(
    completed_run: int, chapter_dir: Path
) -> None:
    """**AC-4's "in reading order" clause**, on all five pages.

    `reading_index` is a position, so it is an ordering by construction and
    counting rows says nothing about it. What can be false is whether that
    position *is* reading order: `sort_regions` is idempotent, so reading the
    page's regions back and sorting them again must be a no-op. A detect stage
    that stored the detector's own emission order, or reversed it, produces a
    full and plausible table with the right count, the right masks and the wrong
    `reading_index` - which is deferred verification DV-4's third mutation and
    the one that matters.
    """
    with open_project(project_dir_for(chapter_dir)) as project:
        out_of_order = [
            page.filename
            for page in project.pages()
            if tuple(sort_regions(project.read_regions(page.ordinal)))
            != project.read_regions(page.ordinal)
        ]

    assert out_of_order == [], (
        f"{out_of_order} have regions stored in an order that is not reading order:"
        " sorting the stored sequence again moved it. Reading order for Japanese"
        " runs right to left and top to bottom (MT-009), and position is its only"
        " carrier (MT-009 PO-1)."
    )


# -- AC-4: the chapter's stored text is MT-002 E5's nine transcriptions --------


def test_the_annotated_page_holds_the_nine_regions_the_annotation_is_keyed_to(
    completed_run: int, chapter_dir: Path
) -> None:
    """The control on the fixture, before any accuracy is computed.

    `_GROUND_TRUTH` is keyed by position in reading order, so if the detector
    moves, every string below is scored against the wrong region and AC-4 fails
    for a reason that has nothing to do with the pipeline. The nine boxes were
    measured by MT-002 E5, re-measured by MT-030, and re-measured a third time
    in MT-010 RED; this reads them out through the store.
    """
    ordinal = _ordinal_of(chapter_dir, _ANNOTATED_PAGE)
    with open_project(project_dir_for(chapter_dir)) as project:
        regions = project.read_regions(ordinal)

    boxes = tuple(
        (
            min(x for x, _ in region.polygon),
            min(y for _, y in region.polygon),
            max(x for x, _ in region.polygon),
            max(y for _, y in region.polygon),
        )
        for region in regions
    )

    assert len(regions) == 9, f"the detector stored {len(regions)} regions on {_ANNOTATED_PAGE}"
    assert boxes == tuple(box for box, _text in _GROUND_TRUTH)


def test_the_chapters_stored_text_is_mt002s_nine_transcriptions_in_reading_order(
    completed_run: int, chapter_dir: Path
) -> None:
    """**AC-4's last clause.** The nine strings, in the `line` table, in
    `reading_index` order, after one `mangatl-run`.

    Read through a plain `sqlite3` connection joining `line` to `region` and
    ordering by `reading_index`: that is what the review UI and the translate
    stage will read, and it is the only observation that catches a pipeline
    which transcribed the right crops and stored them against the wrong regions.

    The threshold is `OCR_MIN_ACCURACY`, exported by `mangatl.ocr.page` and
    settled by MT-010 (C-7). It is read out here and not chosen: MT-010 measured
    **1.0000 on all nine** through the shipped modules, and this story may not
    move the number in either direction.
    """
    ordinal = _ordinal_of(chapter_dir, _ANNOTATED_PAGE)
    stored = [
        (str(source_ja), bool(ocr_empty))
        for source_ja, ocr_empty in _query(
            chapter_dir,
            "SELECT line.source_ja, line.ocr_empty"
            " FROM line JOIN region ON region.id = line.region_id"
            " JOIN page ON page.id = region.page_id"
            f" WHERE page.ordinal = {ordinal} ORDER BY region.reading_index",
        )
    ]

    assert len(stored) == len(_GROUND_TRUTH), (
        f"{len(stored)} lines are stored against the nine regions of {_ANNOTATED_PAGE}"
    )
    scores = [
        (index, round(_accuracy(text, _normalised(expected)), 4), text)
        for index, ((text, _empty), (_box, expected)) in enumerate(
            zip(stored, _GROUND_TRUTH, strict=True)
        )
    ]
    below = [entry for entry in scores if entry[1] < OCR_MIN_ACCURACY]
    assert below == [], (
        f"{len(below)} of {len(_GROUND_TRUTH)} stored transcriptions on"
        f" {_ANNOTATED_PAGE} scored below OCR_MIN_ACCURACY ({OCR_MIN_ACCURACY}):"
        f" {below}. MT-010 measured 1.0000 on all nine through the same modules,"
        " so a failure here is the pipeline - the wrong page, the wrong regions,"
        " or the right text stored against the wrong reading_index - and not OCR"
        " quality, which MT-010 owns."
    )
    assert not any(empty for _text, empty in stored), (
        "a region on a page with nine speech bubbles was stored as ocr_empty"
    )
