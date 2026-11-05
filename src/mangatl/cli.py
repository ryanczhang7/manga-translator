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

**MT-036: the stages are real, and where the weights live is now an argument.**
`mangatl.compose` is the composition root - the one module that constructs ONNX
sessions - and this module asks it for the stage list by the name it imported,
which is the seam a test replaces to walk the whole entry point with no weights
on the machine (C-3). `--models`, then `$MANGATL_MODELS`, then a sentence: PO-4
decided there is no silent default, and accepted that `mangatl-run` now fails on
a machine with no weights where it used to write an empty translation.

**MT-044: the run translates, so `--no-translate` is the way to run without
paying for it.** The flag asks the composition root for a detect, clean and OCR
stage list (MT-065 PO-1: cleaning is local and free, so the flag keeps it),
and with it no API client is constructed and nothing is billed. It is an
opt-out the user types, because a run that quietly did not translate is the
failure mode EPIC-04's budget work exists to make visible (A-1).

**MT-078: the provider is the one whose key is set.** Without the flag, the run
selects a provider before it reads or creates anything - `--provider`, else
`MANGATL_PROVIDER`, else the one key set - and a machine with no key, or with
several and no choice, gets one line and exit 1 with nothing loaded and nothing
left behind.

**MT-107: the context mode.** `--context`, else `MANGATL_CONTEXT_MODE`, else
`rolling`; the flag beats the variable as `--provider` does. A bad flag is
argparse's usage error; a bad variable is one line and exit 1, decided before
the provider is selected, so nothing is loaded or left behind.

**MT-112: a pending batch is collected, not run.** When the folder's project
holds batch jobs still `submitted`, the run builds no stage, loads no weights
and submits nothing: it collects each job in page order through one
`build_batch_collector(selection)` and `collect_volume` (both called by the
names imported here, the seams the tests replace, as `build_pipeline` is), and
prints one line. A pending batch needs the Gemini key that submitted it, so
without a Gemini selection it is one line and exit 1. `--sync` is the per-page
run (PO-4): with a job pending it refuses, naming the first, rather than
translate those pages twice; with none it is today's run, unchanged.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from mangatl.app_paths import bundled_models_dir
from mangatl.compose import (
    MODELS_ENV,
    ModelsNotFound,
    build_batch_collector,
    build_pipeline,
    resolve_models_dir,
)
from mangatl.domain.batch import BatchJob
from mangatl.domain.budget import page_estimate
from mangatl.domain.events import (
    BatchCollected,
    PageSkipped,
    PageStarted,
    PassStarted,
    RunEvent,
)
from mangatl.domain.glossary import (
    CONTEXT_MODE_VAR,
    CONTEXT_MODES,
    ContextMode,
    UnknownContextMode,
    context_mode,
)
from mangatl.pipeline.bake import bake_chapter
from mangatl.pipeline.batch import collect_volume
from mangatl.pipeline.runner import READING, RUN_FINISHED, TRANSLATING, run_chapter
from mangatl.store.batch import pending_jobs
from mangatl.store.intake import NoPagesFound, UnreadablePage, read_chapter
from mangatl.store.project import (
    Project,
    ProjectExists,
    create_project,
    open_project,
    project_dir_for,
)
from mangatl.translate.provider import (
    KEY_VARS,
    PROVIDER_VAR,
    PROVIDERS,
    ProviderError,
    Selection,
    model_for,
    select_provider,
)

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
    parser.add_argument(
        "--models",
        type=Path,
        default=None,
        help=f"directory holding the model weights (or set {MODELS_ENV})",
    )
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="detect, clean and transcribe only; make no API calls and spend nothing",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        default=None,
        help=f"the translation provider, when more than one API key is set (or set {PROVIDER_VAR})",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help=(
            "run page by page, never a batch; refused while a batch job for the"
            " folder is still pending"
        ),
    )
    parser.add_argument(
        "--context",
        choices=CONTEXT_MODES,
        default=None,
        help=(
            "what each page's request is given from its neighbours: the previous"
            " page's English (rolling, the default) or the adjacent pages' Japanese"
            f" (or set {CONTEXT_MODE_VAR})"
        ),
    )
    arguments = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    source_dir: Path = arguments.folder

    try:
        # Before `read_chapter`, so a run with nowhere to load the weights from
        # fails in one line and leaves nothing behind for the user to delete
        # (MT-036 C-3). The real environment, read at call time: `$MANGATL_MODELS`
        # is a working branch of PO-4's resolution order, not documentation.
        # The bundled weights come last (MT-024 AC-9), asked for now.
        models_dir = resolve_models_dir(arguments.models, os.environ, bundled_models_dir())
    except ModelsNotFound as error:
        return _fail(str(error))

    # MT-078 C-3: which provider translates, decided before anything is read
    # or created, so a keyless or ambiguous run fails in one line and leaves
    # nothing behind. The flag beats the variable; an empty variable is no
    # choice (PO-7). `--no-translate` makes no selection at all.
    # MT-107: the context mode, decided first of the two, so a bad variable is
    # its own one line whether or not a key is set. The flag beats the
    # variable; unset or empty is `rolling`. `--no-translate` resolves nothing.
    mode: ContextMode = "rolling"
    selection: Selection | None = None
    if not arguments.no_translate:
        try:
            mode = context_mode(arguments.context or os.environ.get(CONTEXT_MODE_VAR))
        except UnknownContextMode as error:
            return _fail(str(error))
        try:
            selection = select_provider(
                arguments.provider or os.environ.get(PROVIDER_VAR) or None, os.environ
            )
        except ProviderError as error:
            return _fail(str(error))

    if not source_dir.is_dir():
        return _fail(f"no such folder: {source_dir}")
    try:
        chapter = read_chapter(source_dir)
    except (NoPagesFound, UnreadablePage) as error:
        # Both carry the folder or the file they are about, which is the only
        # thing the user can act on.
        return _fail(str(error))

    # MT-112 AC-6: a project left with pending batch jobs is collected, not
    # run - before the stage list is asked for, because a collection loads no
    # weights - and `--sync` refuses rather than translate those pages twice.
    # A project with nothing pending falls through to today's run, unchanged.
    try:
        existing = open_project(project_dir_for(source_dir))
    except FileNotFoundError:
        pass  # a first run: nothing can be pending
    else:
        with existing:
            pending = pending_jobs(existing)
            if pending:
                return _collect_pending(existing, pending, selection, sync=arguments.sync)

    # The stage list is the composition root's, asked for after the chapter is
    # read - a folder with nothing to translate should not pay for the ONNX
    # sessions - and before the project is created (MT-078 C-3, A-2): the
    # builder can still refuse (`ProviderUnavailable`, a provider with no
    # translator yet), and it does so before any weight loads, so a refusal
    # is one line and leaves no `.mtproj` behind. The window builds before it
    # creates for the same reason (A-1).
    #
    # `translate=` is passed on every call, flagged or not (MT-044 C-14): what
    # the tool does with a user's money is a decision this entry point makes
    # out loud, not one it leaves to whatever the builder's default happens to
    # be on the day someone changes it. `context_mode=` likewise (MT-107 R-A1).
    try:
        pipeline = build_pipeline(
            models_dir,
            translate=not arguments.no_translate,
            selection=selection,
            context_mode=mode,
        )
    except ProviderError as error:
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
        outcome = run_chapter(
            project,
            pipeline.stages,
            _reporter(filenames),
            _never,
            prelude=pipeline.prelude,
            after_prelude=pipeline.after_prelude,
        )
        if outcome.outcome != RUN_FINISHED:
            return _fail(f"run aborted: {outcome.aborted_reason}")
        report = bake_chapter(project, output_dir)

    # MT-021 C-7: one line, the report's counts, and no page filename in it.
    print(
        f"{report.pages_written} pages written to {output_dir};"
        f" {report.regions_empty} regions left empty;"
        f" {report.unreviewed_lines} lines unreviewed;"
        f" {report.pages_uncleaned} pages not cleaned"
    )
    # MT-027 PO-2: a font folder in settings that could not be used is said
    # once, last, on stdout - the bake itself still succeeded.
    if report.font_fallback != "none":
        print(f"font override not used: {report.font_detail}; lettered in {report.font_family}")
    return _OK


def _collect_pending(
    project: Project, pending: Sequence[BatchJob], selection: Selection | None, *, sync: bool
) -> int:
    """MT-112 AC-6: collect every pending job, in page order, and say so in one
    line; or refuse in one.

    `--sync` with a job pending is refused, naming the first one, because the
    per-page run would translate - and bill - pages the batch already holds. A
    pending batch needs the key that submitted it, so a run with no Gemini
    selection (another provider's key, or `--no-translate`, which selects
    nothing) is refused too, with every job left pending. Otherwise ONE
    collector is built and each job goes through `collect_volume` at the
    batch-tier page estimate. Nothing is baked: the pages are proposals now,
    and the next plain run writes the output.

    The line counts pages off each `BatchCollected` and `{still}` is the jobs
    left `submitted` afterwards; a job that answered `failed`, `cancelled` or
    `expired` is in none of the three numbers - its pages were never written
    and are not pending any more.
    """
    if sync:
        return _fail(
            f"batch job {pending[0].provider_job_id} is still pending; collect it first"
            " (run without --sync)"
        )
    unkeyed = (
        f"batch job {pending[0].provider_job_id} is still pending, and collecting it"
        f" needs the Gemini key that submitted it: set {KEY_VARS['gemini']} and select gemini"
    )
    if selection is None:
        return _fail(f"{unkeyed} (--no-translate selects no provider)")
    try:
        collector = build_batch_collector(selection)
    except ProviderError:
        collector = None  # a provider with no adapter has no batch either
    if collector is None:
        return _fail(unkeyed)

    collected: list[BatchCollected] = []

    def tally(event: RunEvent) -> None:
        if isinstance(event, BatchCollected):
            collected.append(event)

    estimate = page_estimate(model_for(selection.provider), pricing="batch")
    for job in pending:
        collect_volume(project, job, collector, estimate, tally)
    done = sum(event.pages_done for event in collected)
    failed = sum(event.pages_failed for event in collected)
    still = len(pending_jobs(project))
    print(f"batch: {done} pages collected, {failed} failed, {still} jobs still pending")
    return _OK


def _reporter(filenames: dict[int, str]) -> Callable[[RunEvent], None]:
    """One line of progress per page, naming the page by the file the user sees.

    A page the run skipped because it was already done is progress too - it is
    what "resumes rather than restarts" looks like from the outside - so it gets
    a line of its own and says why. A two-pass run (MT-130 C-5) announces each
    pass once, and its page lines then appear once per pass.
    """
    total = len(filenames)
    passes = {READING: f"Reading {total} pages", TRANSLATING: f"Translating {total} pages"}

    def report(event: RunEvent) -> None:
        if isinstance(event, PassStarted):
            print(passes[event.name])
        elif isinstance(event, PageStarted):
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
