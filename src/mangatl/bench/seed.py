"""A DRAFT ground truth, seeded from the detector's stored regions.

MT-029 AC-7, `## Contract` block 3. Hand-drawing 150-250 polygons is hours of
work, and a tool nobody uses measures nothing, so a chapter's annotation may
start from a detector pass. Every region it writes is `source: "seed"`.

**The bias this introduces, and why the reminder is printed here.** A seed is
biased toward what the detector already finds: a region it missed is absent
from the draft, and a reviewer is far likelier to correct a wrong region than
to notice a missing one - which is exactly the failure S1b measures. The
format records `source` per region and `bench.truth` warns on a mostly-seed
document (AC-8); the rest is telling the user, at the moment the draft is
written, that the human pass must look for missed regions (PO-5,
`docs/wiki/benchmark-ground-truth.md`).

**It never overwrites.** An existing document may hold hours of annotation, so
`seed_ground_truth` refuses before it reads anything from the project.

`python -m mangatl.bench.seed FOLDER [--out PATH]` (PO-4).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from mangatl.bench.truth import (
    TRUTH_SCHEMA_VERSION,
    GroundTruth,
    TruthPage,
    TruthRegion,
    dump_ground_truth,
    truth_path_for,
)
from mangatl.store.project import Project, SchemaTooNew, open_project, project_dir_for

__all__ = ["GroundTruthExists", "main", "seed_ground_truth"]

_PROG = "python -m mangatl.bench.seed"
_OK = 0
_FAILED = 1


class GroundTruthExists(Exception):
    """A ground-truth document is already at the path, and it may be hours of work."""


def seed_ground_truth(project: Project, out: Path) -> GroundTruth:
    """Write a draft document for `project`'s chapter to `out` and return it.

    One `TruthRegion` per stored region, in stored order, with the closed
    ring's repeated vertex dropped. Raises `GroundTruthExists` if `out` exists,
    before reading anything from `project`.
    """
    if out.exists():
        raise GroundTruthExists(f"refusing to overwrite the ground truth already at {out}")

    chapter = project.chapter
    pages = tuple(
        TruthPage(
            ordinal=page.ordinal,
            filename=page.filename,
            width=page.width,
            height=page.height,
            sha256=page.sha256,
            regions=tuple(
                TruthRegion(
                    page_ordinal=page.ordinal,
                    index=index,
                    polygon=region.polygon[:-1],
                    kind=region.kind,
                    source="seed",
                    note="",
                )
                for index, region in enumerate(project.read_regions(page.ordinal))
            ),
        )
        for page in sorted(chapter.pages, key=lambda page: page.ordinal)
    )
    truth = GroundTruth(
        schema_version=TRUTH_SCHEMA_VERSION,
        chapter_name=chapter.source_dir.name,
        development_use=False,
        pages=pages,
    )
    out.write_text(dump_ground_truth(truth), encoding="utf-8", newline="\n")
    return truth


def main(argv: Sequence[str] | None = None) -> int:
    """Seed a draft document for a chapter folder. `0` written, `1` refused."""
    parser = argparse.ArgumentParser(
        prog=_PROG, description="Seed a draft benchmark ground truth from stored detections."
    )
    parser.add_argument("folder", type=Path, help="the chapter's folder of page scans")
    parser.add_argument(
        "--out", type=Path, default=None, help="where to write (default: <folder>.truth.json)"
    )
    arguments = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    folder: Path = arguments.folder
    out: Path = arguments.out or truth_path_for(folder)

    try:
        project = open_project(project_dir_for(folder))
    except (FileNotFoundError, SchemaTooNew) as error:
        return _fail(str(error))
    with project:
        try:
            truth = seed_ground_truth(project, out)
        except GroundTruthExists as error:
            return _fail(str(error))

    for page in truth.pages:
        print(f"page {page.ordinal} ({page.filename}): {len(page.regions)} region(s)")
        if not page.regions:
            print(
                f"warning: page {page.ordinal} ({page.filename}) has no stored regions"
                " - has detection run?"
            )
    print(f"wrote {out}")
    print(
        "Every region in it is unreviewed seed: the human pass must correct them AND add"
        " every text region the detector missed."
    )
    return _OK


def _fail(message: str) -> int:
    print(f"{_PROG}: {message}", file=sys.stderr)
    return _FAILED


if __name__ == "__main__":
    raise SystemExit(main())
