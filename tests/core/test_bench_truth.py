"""`mangatl.bench.truth`: the ground-truth document, its loader and its validator.

MT-029 AC-1 .. AC-6 and AC-8 .. AC-10, `## Contract` block 2. AC-7 (seeding) is
`test_bench_seed.py`; the matcher AC-4 is defined against is
`test_bench_matching.py`.

**Every fixture is one deliberate edit of one valid document** (block 4). The
chapter is three real PNGs in `tmp_path`, read with `store.intake.read_chapter`,
so every `sha256` in a document is the hash of bytes actually on disk:

    ordinal  filename  width x height  regions in the base document
    0        001.png   120 x 100       4
    1        002.png   130 x 110       6
    2        003.png   140 x 120       6      -> 16 regions, all "human"

Region `i` of the base document is an 8x8 square at `x = 10 + 12 * i`,
`y = 10` - so every coordinate is a number >= 10, and no two squares touch.

**Why the number needles look the way they do.** Each error must *name* its
subject (`## Model guidance`, success condition). The contract pins substrings,
not sentences, so a test looks for the ordinal and index as standalone
integers. To keep those needles from matching by accident, the fixtures put the
offending region at an (ordinal, index) whose digits appear nowhere else in a
plausible message: never `2` for a two-vertex polygon ("2 vertices"), never
`1` beside a `y = -1`, and every coordinate two digits or more. `_names` also
refuses a digit that is part of a longer number or of a decimal like `0.75`.

**IoU values (AC-4, DV-2).** Pillow's `ImageDraw.polygon(fill=1)` sets the
INCLUSIVE pixel range of an axis-aligned rectangle; measured in RED on Pillow
12.3.0 and pinned by `test_bench_matching.py`. So on page 2:

    region 3: (10,40)-(49,79) inclusive  = 40 x 40 = 1600 px
    region 4: (10,40)-(49,69) inclusive  = 40 x 30 = 1200 px -> IoU 1200/1600 = 0.75
              (10,40)-(49,59)            = 40 x 20 =  800 px -> IoU  800/1600 = 0.50
              (10,40)-(49,58)            = 40 x 19 =  760 px -> IoU  760/1600 = 0.475

0.75 sits between the threshold and 0.99, which is what DV-2's `> 0.99`
mutation needs in order to be caught.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any

import pytest

import mangatl.bench.truth as truth_module
from mangatl.bench.truth import (
    SEED_REVIEW_WARN_FRACTION,
    TRUTH_SCHEMA_VERSION,
    TRUTH_SUFFIX,
    BenchmarkChapterUsedInDevelopment,
    GroundTruth,
    InvalidGroundTruth,
    TruthPage,
    TruthRegion,
    ValidationReport,
    dump_ground_truth,
    load_ground_truth,
    main,
    truth_path_for,
    validate,
)
from mangatl.domain.page import Chapter
from mangatl.store.intake import read_chapter

_PAGES = (("001.png", 120, 100), ("002.png", 130, 110), ("003.png", 140, 120))
_BASE_COUNTS = (4, 6, 6)
_BASE_TOTAL = 16


# -- fixtures and helpers -----------------------------------------------------


@pytest.fixture
def folder(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    source = tmp_path / "scans"
    source.mkdir()
    for filename, width, height in _PAGES:
        (source / filename).write_bytes(png_bytes(width, height))
    return source


@pytest.fixture
def chapter(folder: Path) -> Chapter:
    return read_chapter(folder)


def _square(index: int) -> list[list[int]]:
    x = 10 + 12 * index
    return [[x, 10], [x + 8, 10], [x + 8, 18], [x, 18]]


def _rect(x0: int, y0: int, x1: int, y1: int) -> list[list[int]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _document(
    chapter: Chapter,
    counts: tuple[int, ...] = _BASE_COUNTS,
    seed: frozenset[tuple[int, int]] = frozenset(),
    *,
    chapter_name: str = "scans",
    development_use: bool = False,
) -> dict[str, Any]:
    """A valid document over `chapter`: `counts[o]` squares on page `o`.

    `seed` holds the `(ordinal, index)` pairs marked `source: "seed"`; every
    other region is `"human"`. Kinds alternate bubble, box.
    """
    return {
        "schema_version": 1,
        "chapter_name": chapter_name,
        "development_use": development_use,
        "pages": [
            {
                "ordinal": page.ordinal,
                "filename": page.filename,
                "width": page.width,
                "height": page.height,
                "sha256": page.sha256,
                "regions": [
                    {
                        "index": index,
                        "polygon": _square(index),
                        "kind": "bubble" if index % 2 == 0 else "box",
                        "source": "seed" if (page.ordinal, index) in seed else "human",
                        "note": "",
                    }
                    for index in range(counts[page.ordinal])
                ],
            }
            for page in chapter.pages
        ],
    }


def _write(path: Path, document: dict[str, Any] | str) -> Path:
    text = document if isinstance(document, str) else json.dumps(document)
    path.write_text(text, encoding="utf-8")
    return path


def _report(tmp_path: Path, chapter: Chapter, document: dict[str, Any]) -> ValidationReport:
    """Write `document`, load it as the benchmark does, and validate it."""
    return validate(load_ground_truth(_write(tmp_path / "doc.truth.json", document)), chapter)


def _names(message: str, *numbers: int) -> bool:
    """Whether every one of `numbers` appears in `message` as a whole integer.

    Not as a digit of a longer number (`12`, `003.png`) or of a decimal (`0.75`).
    """
    return all(
        re.search(rf"(?<![\w.]){number}(?!\w|\.\d)", message) is not None for number in numbers
    )


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


# -- constants and shapes -----------------------------------------------------


def test_the_constants_are_the_pinned_ones() -> None:
    assert SEED_REVIEW_WARN_FRACTION == 0.10
    assert TRUTH_SCHEMA_VERSION == 1
    assert TRUTH_SUFFIX == ".truth.json"


def test_the_document_for_a_chapter_folder_is_its_sibling_named_after_it(tmp_path: Path) -> None:
    assert truth_path_for(tmp_path / "vol17-ch3") == tmp_path / "vol17-ch3.truth.json"


@pytest.mark.parametrize(
    ("cls", "names"),
    [
        (TruthRegion, ["page_ordinal", "index", "polygon", "kind", "source", "note"]),
        (TruthPage, ["ordinal", "filename", "width", "height", "sha256", "regions"]),
        (GroundTruth, ["schema_version", "chapter_name", "development_use", "pages"]),
        (ValidationReport, ["errors", "warnings"]),
    ],
    ids=["TruthRegion", "TruthPage", "GroundTruth", "ValidationReport"],
)
def test_each_record_carries_exactly_the_contracted_fields_in_order(
    cls: type, names: list[str]
) -> None:
    assert [field.name for field in fields(cls)] == names


def test_a_loaded_ground_truth_is_frozen(tmp_path: Path, chapter: Chapter) -> None:
    truth = load_ground_truth(_write(tmp_path / "doc.truth.json", _document(chapter)))

    with pytest.raises(FrozenInstanceError):
        truth.chapter_name = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        truth.pages[0].regions[0].source = "human"  # type: ignore[misc]


def test_a_report_is_ok_exactly_when_it_has_no_errors_whatever_its_warnings() -> None:
    assert ValidationReport(errors=(), warnings=()).ok is True
    assert ValidationReport(errors=(), warnings=("WARNING: something",)).ok is True
    assert ValidationReport(errors=("page 0 (001.png): wrong",), warnings=()).ok is False


# -- AC-1: what a loaded region carries --------------------------------------


def test_ac1_loading_gives_every_region_its_page_polygon_kind_source_and_note(
    tmp_path: Path, chapter: Chapter
) -> None:
    document = _document(chapter, counts=(2, 0, 1), seed=frozenset({(0, 1)}))
    document["pages"][0]["regions"][0]["note"] = "吹き出し - furigana above"
    del document["pages"][0]["regions"][1]["note"]  # absent in the file -> ""

    truth = load_ground_truth(_write(tmp_path / "doc.truth.json", document))

    page0, page1, page2 = chapter.pages
    region00 = TruthRegion(
        page_ordinal=0,
        index=0,
        polygon=((10, 10), (18, 10), (18, 18), (10, 18)),
        kind="bubble",
        source="human",
        note="吹き出し - furigana above",
    )
    region01 = TruthRegion(
        page_ordinal=0,
        index=1,
        polygon=((22, 10), (30, 10), (30, 18), (22, 18)),
        kind="box",
        source="seed",
        note="",
    )
    region20 = TruthRegion(
        page_ordinal=2,
        index=0,
        polygon=((10, 10), (18, 10), (18, 18), (10, 18)),
        kind="bubble",
        source="human",
        note="",
    )
    assert truth == GroundTruth(
        schema_version=1,
        chapter_name="scans",
        development_use=False,
        pages=(
            TruthPage(0, "001.png", 120, 100, page0.sha256, (region00, region01)),
            TruthPage(1, "002.png", 130, 110, page1.sha256, ()),
            TruthPage(2, "003.png", 140, 120, page2.sha256, (region20,)),
        ),
    )
    assert truth.regions == (region00, region01, region20)


def test_ac1_a_polygon_loads_as_a_tuple_of_integer_pairs_with_the_first_vertex_not_repeated(
    tmp_path: Path, chapter: Chapter
) -> None:
    truth = load_ground_truth(_write(tmp_path / "doc.truth.json", _document(chapter)))

    polygon = truth.pages[1].regions[5].polygon
    assert polygon == ((70, 10), (78, 10), (78, 18), (70, 18))
    assert type(polygon) is tuple
    assert all(type(vertex) is tuple and len(vertex) == 2 for vertex in polygon)
    assert all(type(value) is int for vertex in polygon for value in vertex)
    assert len(truth.regions) == _BASE_TOTAL


# -- a valid document ---------------------------------------------------------


def test_a_valid_all_human_document_validates_with_no_errors_and_no_warnings(
    tmp_path: Path, chapter: Chapter
) -> None:
    report = _report(tmp_path, chapter, _document(chapter))

    assert report == ValidationReport(errors=(), warnings=())
    assert report.ok


# -- AC-2: a chapter page missing from the document ---------------------------


def test_ac2_a_chapter_page_absent_from_the_document_fails_naming_its_ordinal_and_filename(
    tmp_path: Path, chapter: Chapter
) -> None:
    document = _document(chapter)
    del document["pages"][1]  # ordinal 1, 002.png

    report = _report(tmp_path, chapter, document)

    assert not report.ok
    assert len(report.errors) == 1, report.errors
    assert "002.png" in report.errors[0]
    assert _names(report.errors[0], 1), report.errors[0]


# -- AC-3: a document page that is not in the chapter -------------------------


def test_ac3_a_document_page_absent_from_the_chapter_fails_naming_its_ordinal_and_filename(
    tmp_path: Path, chapter: Chapter
) -> None:
    document = _document(chapter)
    document["pages"].append(
        {
            "ordinal": 7,
            "filename": "phantom.png",
            "width": 120,
            "height": 100,
            "sha256": "ab" * 32,
            "regions": [],
        }
    )

    report = _report(tmp_path, chapter, document)

    assert not report.ok
    assert len(report.errors) == 1, report.errors
    assert "phantom.png" in report.errors[0]
    assert _names(report.errors[0], 7), report.errors[0]


# -- AC-4: two regions a single proposal could match either of ----------------


@pytest.mark.parametrize(
    ("bottom", "iou_text"),
    [(69, "0.75"), (59, "0.50")],
    ids=["iou-0.75-between-threshold-and-0.99", "iou-exactly-0.50-at-threshold"],
)
def test_ac4_two_regions_overlapping_at_or_above_the_threshold_fail_naming_page_both_and_iou(
    tmp_path: Path, chapter: Chapter, bottom: int, iou_text: str
) -> None:
    document = _document(chapter)
    regions = document["pages"][2]["regions"]
    regions[3]["polygon"] = _rect(10, 40, 49, 79)  # 1600 px
    regions[4]["polygon"] = _rect(10, 40, 49, bottom)  # 1200 px or 800 px, inside it

    report = _report(tmp_path, chapter, document)

    assert not report.ok
    assert len(report.errors) == 1, report.errors
    error = report.errors[0]
    assert _names(error, 2, 3, 4), error
    assert iou_text in error


def test_ac4_two_regions_overlapping_just_below_the_threshold_pass(
    tmp_path: Path, chapter: Chapter
) -> None:
    document = _document(chapter)
    regions = document["pages"][2]["regions"]
    regions[3]["polygon"] = _rect(10, 40, 49, 79)  # 1600 px
    regions[4]["polygon"] = _rect(10, 40, 49, 58)  # 760 px: IoU 0.475

    report = _report(tmp_path, chapter, document)

    assert report == ValidationReport(errors=(), warnings=())


def test_ac4_the_overlap_threshold_is_imported_from_the_matcher_not_restated() -> None:
    """One definition, or the validator checks a different question (Contract).

    A source check, because the property is about where the number comes from:
    a validator with its own `0.5` passes every behavioural test above today and
    silently drifts the day the matcher's value changes.
    """
    tree = ast.parse(Path(inspect.getfile(truth_module)).read_text("utf-8"))

    imported = any(
        isinstance(node, ast.ImportFrom)
        and (
            node.module == "mangatl.bench.matching"
            or (node.level == 1 and node.module == "matching")
        )
        and any(alias.name == "IOU_MATCH_THRESHOLD" for alias in node.names)
        for node in ast.walk(tree)
    ) or any(
        isinstance(node, ast.Attribute) and node.attr == "IOU_MATCH_THRESHOLD"
        for node in ast.walk(tree)
    )
    restated = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float) and node.value == 0.5
    ]
    assert imported, "truth.py does not take IOU_MATCH_THRESHOLD from mangatl.bench.matching"
    assert restated == [], "truth.py restates the matching threshold as a literal 0.5"


# -- AC-5: a polygon that is not a region of its page -------------------------


@pytest.mark.parametrize(
    ("ordinal", "index", "polygon"),
    [
        (1, 5, [[70, 10], [78, 18]]),
        # Region 5's square plus a zero-area spike along y = 18 out to x = 141 on a
        # 140-wide page. Rasterised (Pillow clips it) this is 142 px against
        # region 5's 81 px: IoU 81/142 = 0.570 - so a validator that ALSO ran
        # AC-4 on the offending region would report a second error at 0.57.
        (2, 4, [[70, 10], [78, 10], [78, 18], [141, 18], [70, 18]]),
        (2, 5, [[70, -1], [78, 10], [78, 18], [70, 18]]),
    ],
    ids=["two-vertices", "x-is-width-plus-one", "y-is-minus-one"],
)
def test_ac5_a_region_that_is_too_short_or_off_its_page_fails_naming_page_and_region(
    tmp_path: Path, chapter: Chapter, ordinal: int, index: int, polygon: list[list[int]]
) -> None:
    document = _document(chapter)
    document["pages"][ordinal]["regions"][index]["polygon"] = polygon

    report = _report(tmp_path, chapter, document)

    assert not report.ok
    # Once: a region that fails AC-5 is not also an AC-4 finding (block 2).
    assert len(report.errors) == 1, report.errors
    assert _names(report.errors[0], ordinal, index), report.errors[0]


def test_ac5_a_vertex_exactly_on_the_right_and_bottom_edges_is_inside_the_page(
    tmp_path: Path, chapter: Chapter
) -> None:
    document = _document(chapter)
    document["pages"][0]["regions"][3]["polygon"] = _rect(100, 80, 120, 100)  # 120 x 100 page

    report = _report(tmp_path, chapter, document)

    assert report == ValidationReport(errors=(), warnings=())


def test_ac5_a_vertex_exactly_on_the_left_and_top_edges_is_inside_the_page(
    tmp_path: Path, chapter: Chapter
) -> None:
    document = _document(chapter)
    document["pages"][0]["regions"][3]["polygon"] = _rect(0, 0, 5, 5)

    report = _report(tmp_path, chapter, document)

    assert report == ValidationReport(errors=(), warnings=())


# -- AC-6: the annotation is pinned to the exact scan -------------------------


def test_ac6_a_page_whose_hash_differs_from_the_scan_fails_naming_page_and_both_hashes(
    tmp_path: Path, chapter: Chapter
) -> None:
    stale = "0f" * 32
    document = _document(chapter)
    document["pages"][2]["sha256"] = stale

    report = _report(tmp_path, chapter, document)

    assert not report.ok
    assert len(report.errors) == 1, report.errors
    error = report.errors[0]
    assert "003.png" in error
    assert _names(error, 2), error
    assert stale in error
    assert chapter.pages[2].sha256 in error


@pytest.mark.parametrize("field", ["width", "height"])
def test_ac6_a_page_whose_size_differs_from_the_scan_fails_naming_the_page(
    tmp_path: Path, chapter: Chapter, field: str
) -> None:
    document = _document(chapter)
    document["pages"][1][field] += 10  # larger, so no vertex leaves either size

    report = _report(tmp_path, chapter, document)

    assert not report.ok
    assert any("002.png" in error and _names(error, 1) for error in report.errors), report.errors


def test_validate_reports_every_kind_of_fault_at_once_and_never_raises(
    tmp_path: Path, chapter: Chapter
) -> None:
    document = _document(chapter)
    document["pages"][0]["sha256"] = "0f" * 32  # AC-6
    document["pages"][2]["regions"][3]["polygon"] = _rect(10, 40, 49, 79)  # AC-4
    document["pages"][2]["regions"][4]["polygon"] = _rect(10, 40, 49, 69)
    document["pages"][2]["regions"][5]["polygon"] = [[70, 10], [78, 18]]  # AC-5
    del document["pages"][1]  # AC-2
    document["pages"].append(  # AC-3
        {
            "ordinal": 7,
            "filename": "phantom.png",
            "width": 120,
            "height": 100,
            "sha256": "ab" * 32,
            "regions": [
                {"index": 0, "polygon": [[1, 1], [2, 2]], "kind": "box", "source": "human"}
            ],
        }
    )

    report = _report(tmp_path, chapter, document)

    assert not report.ok
    assert len(report.errors) >= 5, report.errors


# -- AC-8: a mostly-seed document is a loud warning, never an error -----------


@pytest.mark.parametrize(
    ("counts", "seed", "percent", "n_seed", "n_total"),
    [
        (
            _BASE_COUNTS,
            frozenset((o, i) for o, n in enumerate(_BASE_COUNTS) for i in range(n)),
            100,
            16,
            16,
        ),
        ((3, 3, 3), frozenset({(0, 0)}), 11, 1, 9),
        ((1, 1, 1), frozenset({(0, 0), (2, 0)}), 67, 2, 3),
    ],
    ids=["all-seed-16-of-16", "one-of-nine-is-11-percent", "two-of-three-rounds-to-67"],
)
def test_ac8_more_than_a_tenth_seed_warns_with_the_fraction_and_counts_but_stays_valid(
    tmp_path: Path,
    chapter: Chapter,
    counts: tuple[int, ...],
    seed: frozenset[tuple[int, int]],
    percent: int,
    n_seed: int,
    n_total: int,
) -> None:
    report = _report(tmp_path, chapter, _document(chapter, counts=counts, seed=seed))

    assert report.ok
    assert report.errors == ()
    assert len(report.warnings) == 1, report.warnings
    warning = report.warnings[0]
    assert warning.startswith("WARNING:"), warning
    assert re.search(rf"(?<![\w.]){percent} ?%", warning), warning
    assert _names(warning, n_seed, n_total), warning
    assert "absent" in warning.lower(), warning


def test_ac8_exactly_a_tenth_seed_is_not_more_than_the_fraction_and_does_not_warn(
    tmp_path: Path, chapter: Chapter
) -> None:
    # 1 of 10: 1 / 10 == SEED_REVIEW_WARN_FRACTION, and the rule is strictly greater.
    report = _report(
        tmp_path, chapter, _document(chapter, counts=(4, 3, 3), seed=frozenset({(0, 0)}))
    )

    assert report == ValidationReport(errors=(), warnings=())


def test_a_document_with_no_regions_is_valid_with_one_warning_and_no_seed_fraction(
    tmp_path: Path, chapter: Chapter
) -> None:
    report = _report(tmp_path, chapter, _document(chapter, counts=(0, 0, 0)))

    assert report.ok
    assert report.errors == ()
    assert len(report.warnings) == 1, report.warnings
    assert "no regions" in report.warnings[0].lower(), report.warnings
    assert "%" not in report.warnings[0], report.warnings


# -- AC-9: a stable input -----------------------------------------------------


def test_ac9_loading_the_same_file_twice_gives_equal_ground_truths(
    tmp_path: Path, chapter: Chapter
) -> None:
    path = _write(tmp_path / "doc.truth.json", _document(chapter, seed=frozenset({(1, 2)})))

    assert load_ground_truth(path) == load_ground_truth(path)


def test_ac9_pages_and_regions_written_out_of_order_load_sorted_by_ordinal_and_index(
    tmp_path: Path, chapter: Chapter
) -> None:
    in_order = _document(chapter)
    shuffled = copy.deepcopy(in_order)
    shuffled["pages"] = [shuffled["pages"][2], shuffled["pages"][0], shuffled["pages"][1]]
    for page in shuffled["pages"]:
        page["regions"].reverse()

    expected = load_ground_truth(_write(tmp_path / "a.truth.json", in_order))
    loaded = load_ground_truth(_write(tmp_path / "b.truth.json", shuffled))

    assert loaded == expected
    assert [page.ordinal for page in loaded.pages] == [0, 1, 2]
    assert [(r.page_ordinal, r.index) for r in loaded.regions] == [
        (o, i) for o, n in enumerate(_BASE_COUNTS) for i in range(n)
    ]
    assert loaded.pages[1].regions[0].polygon == ((10, 10), (18, 10), (18, 18), (10, 18))


@pytest.mark.parametrize(
    "indices",
    [[0, 2], [1, 2], [0, 0], [-1, 0]],
    ids=["gap", "starts-at-one", "duplicate", "negative"],
)
def test_ac9_region_indices_that_are_not_exactly_zero_to_n_minus_one_are_refused_naming_the_page(
    tmp_path: Path, chapter: Chapter, indices: list[int]
) -> None:
    # The offending page is ordinal 7, so the needle cannot be satisfied by the
    # index list a message might quote. The loader never consults the chapter
    # (block 2), so a page the chapter lacks is no obstacle to reaching this check.
    document = _document(chapter)
    document["pages"].append(
        {
            "ordinal": 7,
            "filename": "extra.png",
            "width": 120,
            "height": 100,
            "sha256": "ab" * 32,
            "regions": [
                {"index": index, "polygon": _square(n), "kind": "box", "source": "human"}
                for n, index in enumerate(indices)
            ],
        }
    )
    path = _write(tmp_path / "doc.truth.json", document)

    with pytest.raises(InvalidGroundTruth) as raised:
        load_ground_truth(path, benchmark=False)

    message = str(raised.value)
    assert str(path) in message
    assert _names(message.replace(str(path), ""), 7), message


# -- AC-10: a development chapter is not a benchmark --------------------------


def test_ac10_a_development_document_refuses_to_load_in_benchmark_mode_naming_path_and_chapter(
    tmp_path: Path, chapter: Chapter
) -> None:
    path = _write(
        tmp_path / "doc.truth.json",
        _document(chapter, chapter_name="vol17-ch2", development_use=True),
    )

    for load in (lambda: load_ground_truth(path), lambda: load_ground_truth(path, benchmark=True)):
        with pytest.raises(BenchmarkChapterUsedInDevelopment) as raised:
            load()
        assert str(path) in str(raised.value)
        assert "vol17-ch2" in str(raised.value)


def test_ac10_a_development_document_loads_outside_benchmark_mode(
    tmp_path: Path, chapter: Chapter
) -> None:
    path = _write(tmp_path / "doc.truth.json", _document(chapter, development_use=True))

    truth = load_ground_truth(path, benchmark=False)

    assert truth.development_use is True
    assert len(truth.regions) == _BASE_TOTAL


# -- the loader's refusals ----------------------------------------------------

Edit = Callable[[dict[str, Any]], dict[str, Any] | str]


def _set(path: tuple[Any, ...], value: Any) -> Edit:
    def edit(document: dict[str, Any]) -> dict[str, Any]:
        target: Any = document
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return document

    return edit


def _drop(path: tuple[Any, ...]) -> Edit:
    def edit(document: dict[str, Any]) -> dict[str, Any]:
        target: Any = document
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
        return document

    return edit


_REGION = ("pages", 1, "regions", 2)

_MALFORMED: list[tuple[str, Edit]] = [
    ("unparseable-json", lambda d: '{"schema_version": 1, "pages": ['),
    ("top-level-is-an-array", lambda d: json.dumps([d])),
    ("schema-version-2", _set(("schema_version",), 2)),
    ("schema-version-as-string", _set(("schema_version",), "1")),
    ("missing-schema-version", _drop(("schema_version",))),
    ("missing-chapter-name", _drop(("chapter_name",))),
    ("chapter-name-as-number", _set(("chapter_name",), 17)),
    ("missing-development-use", _drop(("development_use",))),
    ("development-use-as-string", _set(("development_use",), "false")),
    ("development-use-as-int", _set(("development_use",), 0)),
    ("missing-pages", _drop(("pages",))),
    ("pages-not-a-list", _set(("pages",), {})),
    ("missing-page-ordinal", _drop(("pages", 1, "ordinal"))),
    ("missing-page-filename", _drop(("pages", 1, "filename"))),
    ("missing-page-sha256", _drop(("pages", 1, "sha256"))),
    ("missing-page-regions", _drop(("pages", 1, "regions"))),
    ("page-width-as-string", _set(("pages", 1, "width"), "130")),
    ("page-height-as-float", _set(("pages", 1, "height"), 110.5)),
    ("page-regions-not-a-list", _set(("pages", 1, "regions"), {})),
    ("missing-region-index", _drop((*_REGION, "index"))),
    ("missing-region-polygon", _drop((*_REGION, "polygon"))),
    ("missing-region-kind", _drop((*_REGION, "kind"))),
    ("missing-region-source", _drop((*_REGION, "source"))),
    ("region-index-as-string", _set((*_REGION, "index"), "2")),
    ("polygon-not-a-list", _set((*_REGION, "polygon"), "34,10 42,10 42,18")),
    ("vertex-with-a-float", _set((*_REGION, "polygon"), [[34.5, 10], [42, 10], [42, 18]])),
    ("vertex-with-three-numbers", _set((*_REGION, "polygon"), [[34, 10, 0], [42, 10], [42, 18]])),
    ("kind-outside-its-literal", _set((*_REGION, "kind"), "speech")),
    ("source-outside-its-literal", _set((*_REGION, "source"), "machine")),
    ("note-as-number", _set((*_REGION, "note"), 5)),
    ("duplicate-page-ordinal", _set(("pages", 1, "ordinal"), 0)),
]


@pytest.mark.parametrize("edit", [edit for _, edit in _MALFORMED], ids=[n for n, _ in _MALFORMED])
def test_a_malformed_document_is_refused_with_a_message_naming_its_path(
    tmp_path: Path, chapter: Chapter, edit: Edit
) -> None:
    path = _write(tmp_path / "doc.truth.json", edit(_document(chapter)))

    with pytest.raises(InvalidGroundTruth) as raised:
        load_ground_truth(path, benchmark=False)

    assert str(path) in str(raised.value)


def test_a_two_vertex_polygon_is_a_validation_finding_not_a_load_failure(
    tmp_path: Path, chapter: Chapter
) -> None:
    """The loader checks shape and type; whether a region is a region of its page
    is `validate`'s (block 2), so AC-5's fixture must load."""
    document = _document(chapter)
    document["pages"][1]["regions"][5]["polygon"] = [[70, 10], [78, 18]]

    truth = load_ground_truth(_write(tmp_path / "doc.truth.json", document))

    assert truth.pages[1].regions[5].polygon == ((70, 10), (78, 18))


# -- dump_ground_truth --------------------------------------------------------


def test_dump_writes_the_contracted_json_layout_and_round_trips_through_the_loader(
    tmp_path: Path, chapter: Chapter
) -> None:
    document = _document(chapter, counts=(2, 0, 1), seed=frozenset({(0, 0)}))
    document["pages"][2]["regions"][0]["note"] = "吹き出し"
    truth = load_ground_truth(_write(tmp_path / "a.truth.json", document))

    text = dump_ground_truth(truth)

    # Keys in contract order, pages by ordinal, regions by index, indent 2, and
    # non-ASCII written as itself. `_document` already builds keys in that order.
    assert text.rstrip("\n") == json.dumps(document, indent=2, ensure_ascii=False)
    assert "吹き出し" in text
    assert load_ground_truth(_write(tmp_path / "b.truth.json", text)) == truth


# -- main: python -m mangatl.bench.truth FOLDER [--truth PATH] ----------------


def test_main_on_a_valid_document_prints_ok_with_page_and_region_counts_and_returns_zero(
    folder: Path, chapter: Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(folder.parent / "scans.truth.json", _document(chapter))

    status = main([str(folder)])

    out = capsys.readouterr().out
    assert status == 0
    assert _lines(out) == ["ok: 3 pages, 16 regions"]


def test_main_prints_each_error_on_its_own_line_then_invalid_with_the_count_and_returns_one(
    tmp_path: Path, folder: Path, chapter: Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _document(chapter)
    del document["pages"][1]
    expected = _report(tmp_path, chapter, document)
    _write(folder.parent / "scans.truth.json", document)

    status = main([str(folder)])

    captured = capsys.readouterr()
    assert status == 1
    assert _lines(captured.out)[-1] == "invalid: 1 error(s)"
    lines = _lines(captured.out + captured.err)
    assert all(error in lines for error in expected.errors), (expected.errors, lines)


def test_main_prints_the_seed_warning_and_still_returns_zero(
    tmp_path: Path, folder: Path, chapter: Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    every = frozenset((o, i) for o, n in enumerate(_BASE_COUNTS) for i in range(n))
    document = _document(chapter, seed=every)
    expected = _report(tmp_path, chapter, document)
    _write(folder.parent / "scans.truth.json", document)

    status = main([str(folder)])

    captured = capsys.readouterr()
    assert status == 0
    assert _lines(captured.out)[-1] == "ok: 3 pages, 16 regions"
    assert expected.warnings[0] in _lines(captured.out + captured.err)


def test_main_validates_a_development_document_because_it_does_not_load_in_benchmark_mode(
    folder: Path, chapter: Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(folder.parent / "scans.truth.json", _document(chapter, development_use=True))

    status = main([str(folder)])

    assert status == 0
    assert _lines(capsys.readouterr().out)[-1] == "ok: 3 pages, 16 regions"


def test_main_reads_the_document_named_by_the_truth_option_instead_of_the_sibling(
    tmp_path: Path, folder: Path, chapter: Chapter, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = _write(elsewhere / "annotation.json", _document(chapter, counts=(1, 1, 1)))
    assert not (folder.parent / "scans.truth.json").exists()

    status = main([str(folder), "--truth", str(path)])

    assert status == 0
    assert _lines(capsys.readouterr().out)[-1] == "ok: 3 pages, 3 regions"


def _no_pages(tmp_path: Path, folder: Path, chapter: Chapter) -> list[str]:
    empty = tmp_path / "empty"
    empty.mkdir()
    return [str(empty)]


def _no_folder(tmp_path: Path, folder: Path, chapter: Chapter) -> list[str]:
    return [str(tmp_path / "never-existed")]


def _no_document(tmp_path: Path, folder: Path, chapter: Chapter) -> list[str]:
    return [str(folder)]


def _unparseable_document(tmp_path: Path, folder: Path, chapter: Chapter) -> list[str]:
    _write(folder.parent / "scans.truth.json", '{"schema_version": 1, "pages": [')
    return [str(folder)]


@pytest.mark.parametrize(
    "arrange",
    [_no_pages, _no_folder, _no_document, _unparseable_document],
    ids=["folder-with-no-pages", "no-such-folder", "no-document", "unparseable-document"],
)
def test_main_returns_two_with_one_sentence_and_no_traceback_when_it_cannot_read_its_inputs(
    tmp_path: Path,
    folder: Path,
    chapter: Chapter,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[Path, Path, Chapter], list[str]],
) -> None:
    argv = arrange(tmp_path, folder, chapter)

    status = main(argv)

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert status == 2
    assert len(_lines(combined)) == 1, combined
    assert "Traceback" not in combined


def test_main_names_the_missing_document_it_looked_for(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = main([str(folder)])

    captured = capsys.readouterr()
    assert status == 2
    assert str(folder.parent / "scans.truth.json") in captured.out + captured.err
