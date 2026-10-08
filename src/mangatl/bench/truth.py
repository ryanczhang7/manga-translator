"""The benchmark ground truth: its document, its loader and its validator.

MT-029 `## Contract` block 2. A human marks every text region of the benchmark
chapter once, and that annotation is an **input** to S1b (MT-022) and S2
(MT-023) - the denominator neither can produce, because a detector that could
enumerate the regions it misses would not miss them. The argument, and the
seeding bias it guards against, is `docs/wiki/benchmark-ground-truth.md`.

**One JSON document per chapter**, `<chapter>.truth.json`, a sibling of the
chapter folder: human-editable, diffable, and independent of the project
schema. The loader checks shape and type and nothing that needs the chapter;
`validate` checks the document against the chapter and is pure over the two
(PO-3), so AC-6's "scan on disk" is `Chapter.pages[*].sha256`.

**One threshold.** AC-4 asks whether two truth regions are ambiguous *to the
matcher*, so the IoU it compares against is the matcher's own, imported rather
than restated - a second copy could drift and the validator would then check a
different question from the one it claims to.

`python -m mangatl.bench.truth FOLDER [--truth PATH]` validates from the shell
(PO-4). It loads with `benchmark=False`, because a document still being
annotated - or one flagged as used in development - must remain checkable.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from mangatl.bench.matching import IOU_MATCH_THRESHOLD, Polygon, iou, polygon_mask
from mangatl.domain.page import Chapter, Page
from mangatl.store.intake import NoPagesFound, UnreadablePage, read_chapter

__all__ = [
    "SEED_REVIEW_WARN_FRACTION",
    "TRUTH_SCHEMA_VERSION",
    "TRUTH_SUFFIX",
    "BenchmarkChapterUsedInDevelopment",
    "GroundTruth",
    "InvalidGroundTruth",
    "TruthPage",
    "TruthRegion",
    "ValidationReport",
    "dump_ground_truth",
    "load_ground_truth",
    "main",
    "truth_path_for",
    "validate",
]

#: Above this fraction of `source: "seed"` regions, validation warns (AC-8). A
#: warning threshold, not a gate: only a human can say a seed region was
#: reviewed and found correct.
SEED_REVIEW_WARN_FRACTION: float = 0.10

TRUTH_SCHEMA_VERSION: int = 1

TRUTH_SUFFIX: str = ".truth.json"

_KINDS = ("bubble", "box")
_SOURCES = ("seed", "human")

_PROG = "python -m mangatl.bench.truth"
_OK = 0
_INVALID = 1
_UNREADABLE = 2


def truth_path_for(source_dir: Path) -> Path:
    """The ground-truth document for a chapter folder: `<folder>.truth.json`."""
    return source_dir.with_name(source_dir.name + TRUTH_SUFFIX)


@dataclass(frozen=True)
class TruthRegion:
    """One human-marked text region. `index` is its 0-based position on its page."""

    page_ordinal: int
    index: int
    polygon: Polygon
    kind: Literal["bubble", "box"]
    source: Literal["seed", "human"]
    note: str


@dataclass(frozen=True)
class TruthPage:
    """One page of the document, pinned to the scan by `sha256`; regions by index."""

    ordinal: int
    filename: str
    width: int
    height: int
    sha256: str
    regions: tuple[TruthRegion, ...]


@dataclass(frozen=True)
class GroundTruth:
    """A loaded document, pages by ordinal."""

    schema_version: int
    chapter_name: str
    development_use: bool
    pages: tuple[TruthPage, ...]

    @property
    def regions(self) -> tuple[TruthRegion, ...]:
        """Every page's regions, in page order and then index order."""
        return tuple(region for page in self.pages for region in page.regions)


@dataclass(frozen=True)
class ValidationReport:
    """What `validate` found. Warnings never make a document invalid."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


class InvalidGroundTruth(Exception):
    """The document is malformed. The message names its path and what is wrong."""


class BenchmarkChapterUsedInDevelopment(Exception):
    """A document flagged `development_use` was loaded as a benchmark (AC-10)."""


class _Malformed(Exception):
    """Raised inside the parser; `load_ground_truth` prefixes the path."""


# -- loading ------------------------------------------------------------------


def _get[T](obj: dict[str, Any], key: str, kind: type[T], where: str) -> T:
    """`obj[key]`, which must be present and of exactly `kind`.

    `type(...) is`, not `isinstance`: `True` is an `int` and `0` must not pass
    for a `bool`, and JSON only ever yields the exact types.
    """
    if key not in obj:
        raise _Malformed(f"{where} has no {key!r}")
    return _typed(obj[key], kind, f"{where}: {key!r}")


def _typed[T](value: object, kind: type[T], what: str) -> T:
    if type(value) is not kind:
        raise _Malformed(f"{what} must be a JSON {kind.__name__}, got {value!r}")
    return value


def _one_of(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise _Malformed(f"{what} must be one of {allowed}, got {value!r}")
    return value


def _vertex(value: object, what: str) -> tuple[int, int]:
    vertex = _typed(value, list, what)
    if len(vertex) != 2 or any(type(coordinate) is not int for coordinate in vertex):
        raise _Malformed(f"{what} must be a pair of integers [x, y], got {vertex!r}")
    return (vertex[0], vertex[1])


def _region(raw: object, ordinal: int, position: int) -> TruthRegion:
    where = f"page {ordinal}, region at position {position}"
    obj = _typed(raw, dict, where)
    index = _get(obj, "index", int, where)
    polygon = tuple(
        _vertex(vertex, f"{where}: vertex {n}")
        for n, vertex in enumerate(_get(obj, "polygon", list, where))
    )
    kind = _one_of(_get(obj, "kind", str, where), _KINDS, f"{where}: 'kind'")
    source = _one_of(_get(obj, "source", str, where), _SOURCES, f"{where}: 'source'")
    note = _typed(obj.get("note", ""), str, f"{where}: 'note'")
    return TruthRegion(
        page_ordinal=ordinal,
        index=index,
        polygon=polygon,
        kind=cast(Literal["bubble", "box"], kind),
        source=cast(Literal["seed", "human"], source),
        note=note,
    )


def _page(raw: object, position: int) -> TruthPage:
    where = f"page at position {position}"
    obj = _typed(raw, dict, where)
    ordinal = _get(obj, "ordinal", int, where)
    where = f"page {ordinal}"
    filename = _get(obj, "filename", str, where)
    width = _get(obj, "width", int, where)
    height = _get(obj, "height", int, where)
    sha256 = _get(obj, "sha256", str, where)
    regions = sorted(
        (_region(region, ordinal, n) for n, region in enumerate(_get(obj, "regions", list, where))),
        key=lambda region: region.index,
    )
    found = [region.index for region in regions]
    if found != list(range(len(regions))):
        raise _Malformed(
            f"page {ordinal} ({filename}): region indices must be exactly 0..n-1 once sorted,"
            f" got {found}"
        )
    return TruthPage(ordinal, filename, width, height, sha256, tuple(regions))


def _parse(data: bytes) -> GroundTruth:
    try:
        raw = json.loads(data.decode("utf-8"))
    except ValueError as error:
        raise _Malformed(f"not UTF-8 JSON ({error})") from error
    obj = _typed(raw, dict, "the document")
    where = "the document"
    version = _get(obj, "schema_version", int, where)
    if version != TRUTH_SCHEMA_VERSION:
        raise _Malformed(
            f"schema_version {version} is not the supported version {TRUTH_SCHEMA_VERSION}"
        )
    chapter_name = _get(obj, "chapter_name", str, where)
    development_use = _get(obj, "development_use", bool, where)
    pages = sorted(
        (_page(page, n) for n, page in enumerate(_get(obj, "pages", list, where))),
        key=lambda page: page.ordinal,
    )
    ordinals = [page.ordinal for page in pages]
    if len(set(ordinals)) != len(ordinals):
        raise _Malformed(f"page ordinals are not unique: {ordinals}")
    return GroundTruth(version, chapter_name, development_use, tuple(pages))


def load_ground_truth(path: Path, *, benchmark: bool = True) -> GroundTruth:
    """Load the document at `path`, sorted by page ordinal and region index.

    Raises `InvalidGroundTruth` for a malformed document, and - when
    `benchmark` is true, which is what the measurements call -
    `BenchmarkChapterUsedInDevelopment` for one flagged `development_use`.
    Nothing here needs the chapter; that is `validate`.
    """
    try:
        truth = _parse(path.read_bytes())
    except _Malformed as error:
        raise InvalidGroundTruth(f"{path}: {error}") from None
    if benchmark and truth.development_use:
        raise BenchmarkChapterUsedInDevelopment(
            f"{path}: chapter {truth.chapter_name!r} is flagged development_use, so it"
            " is not held out and cannot be a benchmark"
        )
    return truth


def dump_ground_truth(truth: GroundTruth) -> str:
    """The document as JSON text - keys in contract order - that loads back `==`."""
    document = {
        "schema_version": truth.schema_version,
        "chapter_name": truth.chapter_name,
        "development_use": truth.development_use,
        "pages": [
            {
                "ordinal": page.ordinal,
                "filename": page.filename,
                "width": page.width,
                "height": page.height,
                "sha256": page.sha256,
                "regions": [
                    {
                        "index": region.index,
                        "polygon": [list(vertex) for vertex in region.polygon],
                        "kind": region.kind,
                        "source": region.source,
                        "note": region.note,
                    }
                    for region in page.regions
                ],
            }
            for page in truth.pages
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


# -- validating ---------------------------------------------------------------


def _label(page: TruthPage | Page) -> str:
    return f"page {page.ordinal} ({page.filename})"


def _page_errors(page: TruthPage, scan: Page) -> list[str]:
    """AC-6: the page as annotated is the page on disk, byte for byte."""
    errors = []
    if page.sha256 != scan.sha256:
        errors.append(
            f"{_label(page)}: the document records sha256 {page.sha256} but the scan on"
            f" disk is {scan.sha256}; the annotation was made against different bytes"
        )
    if (page.width, page.height) != (scan.width, scan.height):
        errors.append(
            f"{_label(page)}: the document records a {page.width} x {page.height} page but"
            f" the scan is {scan.width} x {scan.height}"
        )
    return errors


def _region_errors(page: TruthPage) -> list[str]:
    """AC-5, then AC-4 over the regions that passed AC-5 only."""
    errors = []
    drawable = []
    for region in page.regions:
        outside = [
            (x, y)
            for x, y in region.polygon
            if not (0 <= x <= page.width and 0 <= y <= page.height)
        ]
        if len(region.polygon) < 3:
            errors.append(
                f"{_label(page)}: region {region.index} has {len(region.polygon)} vertices;"
                " a region needs at least three"
            )
        elif outside:
            errors.append(
                f"{_label(page)}: region {region.index} has a vertex at {outside[0]}, outside"
                f" the {page.width} x {page.height} page"
            )
        else:
            drawable.append(region)

    masks = [polygon_mask(region.polygon, page.width, page.height) for region in drawable]
    for a in range(len(drawable)):
        for b in range(a + 1, len(drawable)):
            value = iou(masks[a], masks[b])
            if value >= IOU_MATCH_THRESHOLD:
                errors.append(
                    f"{_label(page)}: regions {drawable[a].index} and {drawable[b].index}"
                    f" overlap at IoU {value:.2f}, at or above the matching threshold, so a"
                    " single proposal could match either"
                )
    return errors


def _seed_warnings(truth: GroundTruth) -> list[str]:
    """AC-8, and the zero-region case where there is no fraction to state."""
    total = len(truth.regions)
    if total == 0:
        return ["WARNING: the document holds no regions at all; nothing can be measured against it"]
    seeded = sum(region.source == "seed" for region in truth.regions)
    if seeded / total <= SEED_REVIEW_WARN_FRACTION:
        return []
    return [
        f"WARNING: {round(100 * seeded / total)}% of regions are unreviewed seed"
        f" ({seeded} of {total}). The human pass must look for absent regions - text"
        " the detector missed - as well as correct the ones present."
    ]


def validate(truth: GroundTruth, chapter: Chapter) -> ValidationReport:
    """Check `truth` against `chapter`. Returns a report; never raises.

    Every error names its subject - page ordinal and filename, region indices -
    so a human can act on it across a chapter of regions.
    """
    scans = {page.ordinal: page for page in chapter.pages}
    annotated = {page.ordinal for page in truth.pages}
    errors = [
        f"{_label(scan)}: in the chapter but absent from the document; its regions would"
        " silently leave the denominator"
        for scan in chapter.pages
        if scan.ordinal not in annotated
    ]
    for page in truth.pages:
        scan = scans.get(page.ordinal)
        if scan is None:
            errors.append(f"{_label(page)}: in the document but not in the chapter")
        else:
            errors.extend(_page_errors(page, scan))
        errors.extend(_region_errors(page))
    return ValidationReport(errors=tuple(errors), warnings=tuple(_seed_warnings(truth)))


# -- the command --------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Validate a chapter's ground truth. `0` ok, `1` invalid, `2` unreadable input."""
    parser = argparse.ArgumentParser(
        prog=_PROG, description="Validate a chapter's benchmark ground truth."
    )
    parser.add_argument("folder", type=Path, help="the chapter's folder of page scans")
    parser.add_argument(
        "--truth", type=Path, default=None, help="the document (default: <folder>.truth.json)"
    )
    arguments = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    folder: Path = arguments.folder
    path: Path = arguments.truth or truth_path_for(folder)

    if not folder.is_dir():
        return _fail(f"no such folder: {folder}")
    try:
        chapter = read_chapter(folder)
    except (NoPagesFound, UnreadablePage) as error:
        return _fail(str(error))
    if not path.is_file():
        return _fail(f"no ground-truth document at {path}")
    try:
        truth = load_ground_truth(path, benchmark=False)
    except InvalidGroundTruth as error:
        return _fail(str(error))

    report = validate(truth, chapter)
    for line in (*report.errors, *report.warnings):
        print(line)
    if not report.ok:
        print(f"invalid: {len(report.errors)} error(s)")
        return _INVALID
    print(f"ok: {len(truth.pages)} pages, {len(truth.regions)} regions")
    return _OK


def _fail(message: str) -> int:
    print(f"{_PROG}: {message}", file=sys.stderr)
    return _UNREADABLE


if __name__ == "__main__":
    raise SystemExit(main())
