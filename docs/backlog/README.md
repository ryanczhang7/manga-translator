# Backlog

The unit of work is a story: one behaviour, one RED to GREEN cycle.

    docs/backlog/epics/EPIC-01.md      a coherent slice of user value
    docs/backlog/stories/PROJ-014.md   one behaviour, testable in isolation

## Lifecycle

    PLANNED -> RED -> GREEN -> GATES -> REVIEW -> DONE

`PLANNED` the story is written but not started. `RED` failing tests exist and
production code is frozen. `GREEN` production code is being written and the
tests are frozen. `GATES` the full suite is being driven to green. `REVIEW` a PR
is open. `DONE` merged.

`SCAFFOLD` replaces RED and GREEN for `bootstrap` and `chore` stories, where
there is no behaviour to specify first.

## Commands

    bash scripts/phase.sh board              every story at a glance
    bash scripts/new-story.sh ID "Title"     create one
    /advance-story ID                        move it one phase
    /complete-story ID                       drive it to a PR

Change phase only through `scripts/phase.sh` - it keeps the story frontmatter
and the harness lock in agreement.

## The story file is the protocol

Agents do not share a context. Everything the next one needs must be written
into the story file before the current phase ends, especially the
`## Handoff: RED -> GREEN` section. The story file is not documentation of the
work; it is the medium the work travels through.
