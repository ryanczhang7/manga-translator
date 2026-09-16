"""`mangatl-run`: point the tool at a folder of scans and get a translated one.

EPIC-02's done-when, made runnable. The user names a folder; this creates the
chapter project beside it, walks every page through the pipeline, reports one
line of progress per page and writes `<folder>_en/`. A second invocation on the
same folder reopens the project and resumes rather than starting over.

**Headless on purpose** (`## Contract` PO-1, PO-5). Not a window: the window
entry point is `mangatl.app` and MT-015 still owns it. This module is named in
`lint-imports` contract 3 ("Nothing imports ui"), so "the CLI is headless" is a
fact the `lint` gate checks rather than a claim a test makes - and that is what
lets the whole walking skeleton run with no display, no GPU and no network.

Nothing here decides anything the pipeline decides: it is argument parsing, the
create-or-reopen choice, a `print` per event and an exit code.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from mangatl.domain.events import PageSkipped, PageStarted, RunEvent
from mangatl.pipeline.export import write_output_folder
from mangatl.pipeline.runner import RUN_FINISHED, run_chapter
from mangatl.pipeline.stage import PassThroughStage
from mangatl.store.intake import NoPagesFound, UnreadablePage, read_chapter
from mangatl.store.project import ProjectExists, create_project, open_project, project_dir_for

__all__ = ["main"]

_PROG = "mangatl-run"

#: `<source>_en`, the literal path AC-6 and AC-10 promise the user, and the same
#: value `create_project` records in `chapter.output_dir`.
_OUTPUT_SUFFIX = "_en"

_OK = 0
_FAILED = 1


def main(argv: Sequence[str] | None = None) -> int:
    """Translate one folder of scans. Returns the process exit code.

    `0` when every page of the chapter is complete and the output folder has
    been written; non-zero, with a message and no traceback, when there is
    nothing to translate or the run did not finish. A traceback is a bug report
    aimed at the wrong person.
    """
    parser = argparse.ArgumentParser(prog=_PROG, description="Translate a folder of page scans.")
    parser.add_argument("folder", type=Path, help="the folder of page scans to translate")
    source_dir: Path = parser.parse_args(list(sys.argv[1:] if argv is None else argv)).folder

    if not source_dir.is_dir():
        return _fail(f"no such folder: {source_dir}")
    try:
        chapter = read_chapter(source_dir)
    except (NoPagesFound, UnreadablePage) as error:
        # Both carry the folder or the file they are about, which is the only
        # thing the user can act on.
        return _fail(str(error))

    try:
        project = create_project(chapter, project_dir_for(source_dir))
    except ProjectExists:
        # The resume path: a project already there may hold hours of work, and
        # `create_project` refuses to clobber it rather than asking.
        project = open_project(project_dir_for(source_dir))

    output_dir = source_dir.with_name(source_dir.name + _OUTPUT_SUFFIX)
    with project:
        filenames = {page.ordinal: page.filename for page in project.pages()}
        outcome = run_chapter(project, [PassThroughStage()], _reporter(filenames), _never)
        if outcome.outcome != RUN_FINISHED:
            return _fail(f"run aborted: {outcome.aborted_reason}")
        write_output_folder(project, output_dir)

    print(f"{len(filenames)} pages written to {output_dir}")
    return _OK


def _reporter(filenames: dict[int, str]) -> Callable[[RunEvent], None]:
    """One line of progress per page, naming the page by the file the user sees.

    A page the run skipped because it was already done is progress too - it is
    what "resumes rather than restarts" looks like from the outside - so it gets
    a line of its own and says why.
    """
    total = len(filenames)

    def report(event: RunEvent) -> None:
        if isinstance(event, PageStarted):
            print(f"[{event.ordinal + 1}/{total}] {filenames[event.ordinal]}")
        elif isinstance(event, PageSkipped):
            print(f"[{event.ordinal + 1}/{total}] {filenames[event.ordinal]} ({event.reason})")

    return report


def _never() -> bool:
    """The CLI has no cancel button. The UI is where `cancelled` gets a meaning."""
    return False


def _fail(message: str) -> int:
    print(f"{_PROG}: {message}", file=sys.stderr)
    return _FAILED
