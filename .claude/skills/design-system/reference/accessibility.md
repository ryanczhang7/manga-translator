# The accessibility floor

Not a feature and not a story. A floor every user-facing story is measured
against, written down once so it can be asserted in tests.

## The floor

- **Contrast** - 4.5:1 for body text, 3:1 for large text and for the boundary of
  any interactive control. Check against the real background, including the
  worst case the product can generate.
- **Focus** - every interactive element has a visible `:focus-visible` style that
  meets 3:1 against its surroundings. Focus order follows visual order. Focus is
  never trapped except in a modal, which returns it on close.
- **Keyboard** - every action is reachable and operable from the keyboard alone.
  Custom controls carry the roles and keys their native counterparts have.
- **Targets** - 24px minimum, 44px for anything touched on a phone.
- **Names** - every control has an accessible name that describes what it does.
  Icon-only buttons carry a label; decorative images carry none.
- **Motion** - `prefers-reduced-motion: reduce` removes transform-based motion.
- **Colour** - never the only carrier of meaning. Pair it with text, shape or
  an icon.
- **Live regions** - anything that changes without a navigation announces
  itself: validation errors, toasts, async results.

## Making it testable

The point of writing this down is that tests can assert it:

- Query by role and accessible name in component tests, so a broken label fails
  the test rather than silently degrading.
- Assert keyboard paths directly: tab to the control, press Enter, check the
  outcome.
- Run an automated audit (axe, or the equivalent in your stack) as part of the
  integration gate. It catches perhaps a third of real problems, which is worth
  having and is not a substitute for the manual pass.
- For contrast against generated content, test the guarantee mechanism - the
  scrim, the enforced overlay - not a sampled screenshot.

## Reviewing a built screen

Tab through it. Zoom to 200%. Turn on reduced motion. Trigger the error state
and the empty state. Narrow the window to the smallest supported breakpoint.
Most accessibility failures are visible in under two minutes if you actually
look; almost none are visible from reading the diff.
