# Tokens

Name colours by role, never by appearance. `--color-danger` survives a rebrand;
`--color-red` becomes a lie the first time danger turns orange.

## The minimum set

**Colour roles** - surface, surface-raised, text, text-muted, border, primary,
primary-contrast, danger, warning, success, plus whatever the product genuinely
needs. Give every role a value for light and for dark. Define the light palette
as the default and override only what changes in dark; a token defined solely
inside a dark-mode block will be missing in light.

**Type scale** - a named ramp with size, line height and weight for each step.
Four or five steps is usually enough. Body line height around 1.5; headings
tighter.

**Spacing** - one rhythm, used everywhere. A 4px base with a 4/8/12/16/24/32/48
ramp covers almost everything. Arbitrary values are how layouts drift.

**Radii, borders, elevation** - two or three of each. More is not a system.

**Motion** - durations (fast/base/slow) and easings, plus what happens under
`prefers-reduced-motion: reduce`: transforms and parallax stop, opacity may
remain.

## Recording them

Write the actual values in `docs/wiki/design/tokens.md` in a table, and have the
bootstrap or first UI story emit them as real variables in the codebase. Tokens
that live only in a document get re-invented by the third story.

## Dark mode

Three states, not two: an explicit light choice, an explicit dark choice, and
the default that follows the system. Say which the product supports and how the
choice persists.

## For generated or user-supplied content

If the product renders content it did not author - generated maps, user themes,
imported art - specify the contrast floor against the *worst* case that content
can produce, and the mechanism that guarantees it: a scrim, a border, an
enforced overlay. "It looks fine on the mockup" is not a decision.
