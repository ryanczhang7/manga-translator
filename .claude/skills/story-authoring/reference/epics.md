# Epics

An epic is a coherent slice of user value, large enough to be worth naming and
small enough to finish. It is not a layer, a sprint, or a component.

Good: "A world can be created, saved and reopened". "Regions can be drawn and
edited". "A world can be exported to a shareable file".

Bad: "Backend". "Database work". "Phase 2".

## Format

Store as `docs/backlog/epics/EPIC-03.md` with frontmatter carrying `id`,
`title`, `status` and `stories` (a list of story ids). Then:

- **Goal** - the user-visible outcome, in one paragraph.
- **Why now** - what it unblocks, or which brief constraint it serves.
- **Done when** - the observable state that means the epic is finished. Not a
  checklist of stories; a description of what the user can then do.
- **Stories** - the ordered list, one line each.
- **Deliberately not in this epic** - the adjacent work people will otherwise
  assume is included.

## Ordering

Order epics so each one leaves the product in a demonstrable state. Within an
epic, order stories so every story is buildable when reached: the walking
skeleton first, then the behaviour that makes it useful, then the edges.

If two stories both need a third thing that does not exist, that thing is a
story, not a shared assumption.
