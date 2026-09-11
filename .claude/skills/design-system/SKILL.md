---
name: design-system
description: How the Lead Designer records visual and interaction decisions so they can be implemented and tested - tokens, component states, accessibility floor, and how to review a built screen against them. Use when planning a user-facing product, writing design notes on a story, or reviewing an implemented screen.
---

# Design decisions that survive the handoff

A design decision is only real if someone with no memory of the conversation can
implement it and a test can check it. That is the bar every file in
`docs/wiki/design/` has to clear.

## What gets recorded

| File | Contents |
|---|---|
| `docs/wiki/design/tokens.md` | colour roles, type scale, spacing, radii, elevation, motion - with values, light and dark |
| `docs/wiki/design/components.md` | the inventory, and the states each component must support |
| `docs/wiki/design/layout.md` | breakpoints, grid, what reflows where |
| `docs/wiki/design/accessibility.md` | the floor: contrast, focus, targets, keyboard paths |
| `docs/wiki/design/voice.md` | tone, naming, error-message style |

See `reference/tokens.md` and `reference/accessibility.md` for what each needs.

## Every component, every state

Specify all of: default, hover, focus-visible, active, disabled, loading, empty,
error. The states that get skipped are the ones users hit on their worst day:
empty and error. An empty state that says "No results" is a missed opportunity;
an empty state that says what to do next is the product working.

## Design notes on a story

Short and specific. Which components, which states, which tokens, what must be
keyboard-reachable, and anything the tests should assert. If a criterion forces
an interaction that cannot work - a destructive action behind hover, a control
unreachable by keyboard - say so before RED, not after.

## Reviewing

When the app runs, look at it rather than imagining it. If a browser tool is
available, drive the real screen: tab through it, check contrast, resize to the
narrow breakpoint, trigger the error and empty states. Report findings as
concrete diffs against the recorded decisions, and hand anything that needs code
to the Lead PO as a story.

## For games and generative interfaces

Readability rules still apply, and one more: the interface must remain legible
over content it does not control. Specify the contrast floor against the worst
background the generator can produce, not against the mockup's background.
