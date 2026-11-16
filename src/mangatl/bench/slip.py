"""Slips: neighbouring regions given identical English from different Japanese.

MT-150 `## Contract` C-1 and C-2. A slip is the shape a misaligned answer
leaves behind: one region's English repeated on its neighbour, whose Japanese
says something else. Repeated dialogue (equal Japanese) is not a slip.

Only the pipeline's output is read - `proposed_en`, never `final_en` or the
status - so a slip the reviewer fixed by hand is still counted (AC-6). Lines
are compared in O2's normalised form, each with its successor on the same
page, after skipping regions with no line, excluded regions, regions with no
proposal and regions MT-149 flagged misaligned (D-3: their English is left
over from an earlier run).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from mangatl.domain.line import Line, normalise
from mangatl.store.lines import read_review_lines
from mangatl.store.project import Project

__all__ = ["SlipReport", "count_slips", "render"]

_HEADING = "slips (identical English, different Japanese)"

#: A compared line: its reading index, normalised English, normalised Japanese.
_Compared = tuple[int, str, str]


@dataclass(frozen=True)
class SlipReport:
    """Every slip, as `(page ordinal, first reading index, second reading index)`."""

    pairs: tuple[tuple[int, int, int], ...]


def count_slips(project: Project) -> SlipReport:
    """Every pair of neighbouring compared lines, per page, that is a slip."""
    pairs: list[tuple[int, int, int]] = []
    for page in project.pages():
        previous: _Compared | None = None
        for current in _compared(read_review_lines(project, page.ordinal)):
            if previous is not None and _is_slip(previous, current):
                pairs.append((page.ordinal, previous[0], current[0]))
            previous = current
    return SlipReport(pairs=tuple(pairs))


def render(report: SlipReport) -> list[str]:
    """The count line, then - when there are slips - every pair on one line."""
    lines = [f"{_HEADING}  {len(report.pairs)}"]
    if report.pairs:
        lines.append(", ".join(f"page {p} regions {i}/{j}" for p, i, j in report.pairs))
    return lines


def _compared(lines: Sequence[Line | None]) -> Iterator[_Compared]:
    """The lines a slip is judged over, in reading order."""
    for line in lines:
        if line is None:
            continue
        if line.excluded is not None:
            continue
        if line.proposed_en is None:
            continue
        if line.misaligned:
            continue
        yield line.reading_index, normalise(line.proposed_en), normalise(line.source_ja)


def _is_slip(first: _Compared, second: _Compared) -> bool:
    """Equal, non-empty English from different Japanese."""
    return first[1] == second[1] != "" and first[2] != second[2]
