"""What a stage is, and the identity element that proves the runner sequences.

A stage is a protocol, not a base class: `architecture.md` §2 puts each real
stage behind an adapter with its own dependencies, and inheritance would drag
the orchestrator's imports into every one of them.

`PageContext` carries the `Project` because `is_done` must consult the store -
that is the whole of AC-5 - and because a stage writes its results through
`ctx.project.transaction()`. It carries the `Page` rather than the ordinal so a
stage that needs the filename or the dimensions does not have to re-query.

**`Project.transaction()` is not reentrant** (MT-005 PO-5), so the runner never
holds one open across a call into `run` or `is_done`: the stage owns its
transaction, one per page per stage (§6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mangatl.domain.page import Page
from mangatl.store.project import PAGE_DONE, Project

__all__ = ["PageContext", "PassThroughStage", "Stage"]


@dataclass(frozen=True)
class PageContext:
    """Everything a stage is given about the page it is working on."""

    project: Project
    page: Page


class Stage(Protocol):
    """One step of the pipeline for one page.

    `is_done` is what makes resume work, and it is per stage per page rather
    than per page: a page that has regions but no translations resumes at
    translation.
    """

    name: str

    def run(self, ctx: PageContext) -> None: ...

    def is_done(self, ctx: PageContext) -> bool: ...


class PassThroughStage:
    """The identity element: a stage that does nothing, correctly.

    Not a placeholder to be deleted when the real stages land. It is what lets
    the runner be exercised with a one-stage list as well as a zero-stage one,
    and it is what AC-5's skip logic has to skip.

    `run` writes nothing at all, so the only question it could answer about
    done-ness is the one the *runner* records: `page.status`. That mirroring is
    the runner's job (`architecture.md` §5), not this stage's.
    """

    name = "passthrough"

    def run(self, ctx: PageContext) -> None:
        """Nothing. A no-op is the whole behaviour of the identity element."""

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE
