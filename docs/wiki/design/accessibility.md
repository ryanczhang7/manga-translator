# The accessibility floor

Not a feature and not a story. The measurable floor every user-facing story is
measured against, phrased so acceptance criteria can cite a clause by number and
a test can check it.

This is a single-user Windows desktop tool, so the floor is proportionate: there
is no touch target rule, no mobile breakpoint, no internationalisation clause.
Two things are **not** discounted, because the product fails without them — the
bubble ↔ line link (the only place a human catches an error) and the cost readout
(the only place a hard budget is observable).

---

## A-01 — Text contrast

All body and label text ≥ **4.5:1** against its actual ground. Text at
`type.display` or at `type.title` weight 600 ≥ **3:1** (WCAG large-text
threshold). Disabled text ≥ **3:1** — formally exempt, but held to it anyway so a
disabled control is still readable enough to explain itself.

Measured values for every shipped pair are in tokens.md §6.

*Testable as:* iterate `TOKENS`, compute the WCAG ratio for each declared
foreground/background pair in a fixture table, assert the floor. No screenshot
needed.

## A-02 — Non-text contrast

The boundary of any interactive control, and any graphical object needed to
understand the interface, ≥ **3:1** against its adjacent ground.
`color.border.interactive` is the token for control boundaries;
`color.border.subtle` and `color.border.default` are decorative and must never be
a control's only boundary.

## A-03 — The selected row

`color.surface.selected` is only 1.42:1 against `color.surface.raised`, so the
ground is **not** the carrier. Selection is carried by a 3px `color.accent.base`
leading bar (≥ 3:1 against both grounds) **and** a filled ordinal badge. A story
that removes either must replace it with something that clears 3:1.

## A-04 — Focus visibility

Every focusable element has a `:focus-visible` treatment: 2px `color.focus.ring`
at `focus.offset`, with a 1px `color.focus.halo` outside it wherever the ring may
fall over artwork. Ring against ground ≥ **3:1** everywhere (measured: 17.04 on
`surface.base`, 6.39 on `canvas.surround`).

Focus styling is **additive**. It is never substituted for hover or selected
styling, and a selected-and-focused row shows both.

Focus order follows visual order: page strip → canvas → translation column →
footer. Focus is trapped only in a modal, and a modal returns focus to the
control that opened it.

*Testable as:* for each widget class, set focus programmatically and assert the
focus style is applied; assert `QWidget.focusPolicy` is not `NoFocus` for every
interactive widget; assert tab order matches a declared list.

## A-05 — Target size

Minimum **28 × 28 px** for any pointer target; 32 preferred. Not the 24px web
minimum and not the 44px touch minimum: this is a mouse-and-keyboard desktop tool
where 28px matches the Windows 11 control rhythm and leaves the chrome compact
enough that the art stays dominant.

**Exempt:** bubble markers on the canvas, whose size is the artwork's. The
keyboard path (`Up`/`Down` between ordinals) is the guaranteed way to reach a
small bubble, and the ordinal badge — `overlay.badge.size` = 18px — is **not** the
hit target; the whole region outline and interior is.

## A-06 — Contrast over artwork

The app draws over content it did not author. No single flat colour clears 3:1
against both `#FFFFFF` and `#000000`, so the guarantee is a mechanism, not a
colour:

> Every overlay marker — outline, badge, leader line and off-screen indicator —
> is stroked with `overlay.halo` before its core colour, `overlay.stroke.halo` px
> on each side.

**Floors, assertable from tokens alone:**

- for every `overlay.bubble.*` core C: `contrast(C, #000000) ≥ 3.0`
- `contrast(overlay.halo, #FFFFFF) ≥ 3.0`
- `contrast(overlay.halo, #808080) ≥ 3.0`
- `overlay.stroke.halo ≥ 1`; every `overlay.stroke.core-* ≥ 2`

**Floor that tokens cannot prove, and that a story must check:** that the halo is
actually painted, in every state, at every zoom, for every marker part. The check
is a render test — draw a page that is uniformly `#FFFFFF` and one that is
uniformly `#000000`, place a region, render each marker state, and sample pixels
along the marker path asserting that at least one stroke pixel clears 3:1 against
the page. Test the mechanism, not a screenshot of a real scan.

## A-07 — Keyboard operability

**Every action in the review loop is reachable and operable from the keyboard
alone.** The bindings are normative and listed in components.md §4.7; the ones
that must never regress:

| Requirement | Binding |
|---|---|
| move between lines | `Up` / `Down` |
| begin editing | `Enter` |
| cancel an edit | `Esc` |
| commit an edit | `Enter` |
| revert to the proposal | `Ctrl+R` |
| accept without editing | `Ctrl+Enter` |
| move between pages | `PageUp` / `PageDown` |
| move between panes | `Tab` / `Shift+Tab`, and `F6` / `Shift+F6` |
| jump from a bubble to its line | `Enter` on the canvas |
| bring the selected bubble into view | `Ctrl+9` |
| show the bindings | `?` |

**No action is hover-only.** Revert, Accept and Retry are visible controls on the
row, not hover reveals — Revert in particular discards the user's typing, and a
destructive action behind hover is unreachable without a pointer.

*Testable as:* synthesise the key event on the focused widget and assert the state
change, for each row of the table.

## A-08 — Accessible names and roles

Every control has an accessible name that says what it does. Icon-only controls
carry a label. Decorative graphics carry none.

Required names (exact wording in components.md):

- `TranslationRow` → role `ListItem`, `Selected` state, name including the
  ordinal, the Japanese, the English and the status
- `PageCanvas` → role `Graphic`, name "Page {n} of {total}, {filename}",
  description naming the bubble count and pointing at the list
- `PageStrip` row → name "Page {n} of {total}, {filename}, {k} of {m} lines reviewed"
- `FolderDropTarget` → role `Button`, name "Choose chapter folder"
- `CostReadout` → name "Run cost {x} of {budget} budget, {state}"
- `OffscreenIndicator` → name "Bubble {n} is off screen. Activate to show it."

*Testable as:* query the widget's `QAccessible` interface by role and name and
assert the string, so a broken label fails a test rather than degrading silently.

## A-09 — Motion

Qt exposes no cross-platform reduced-motion flag. On Windows the user's setting
is *Accessibility → Visual effects → Animation effects*, read via
`SystemParametersInfo(SPI_GETCLIENTAREAANIMATION)` and refreshed on
`WM_SETTINGCHANGE`.

When animations are off, **every `motion.duration.*` is treated as 0**: the
canvas jumps to the selection, the list jumps, the progress bar steps, the toast
appears without rising. No meaning is carried by motion anywhere in the app, so
nothing is lost.

**If the platform call is not wired, the app defaults to animations off**, never
to on.

*Testable as:* inject the preference as a boolean and assert every animation
duration resolves to 0.

## A-10 — Colour is never the only carrier

Every state that is signalled with colour also carries a glyph, a number, a
shape change or text:

| Signalled by colour | Also carried by |
|---|---|
| bubble selection | the ordinal badge fills, the stroke widens, every other marker dims |
| row status | a distinct gutter glyph per status (hollow circle / check / pencil / pencil-with-return / triangle / shrink) |
| page status in the strip | a distinct glyph per status |
| cost state | the figure, the budget and the projection as text, plus a warning glyph |
| run stage | the step's label and a check or triangle |
| drop-target validity | the headline changes wording |

## A-11 — Chrome neutrals are achromatic

Every value under `color.surface.*` (except `selected`), `color.border.*` and
`color.text.*` has R = G = B. A chrome colour cast tints the greyscale artwork
the user is judging.

*Testable as:* iterate `TOKENS`, parse each matching name, assert the three
channels are equal.

## A-12 — Live announcements

Anything that changes without a navigation announces itself. Qt has no ARIA-live
equivalent; the app keeps an off-screen `QLabel` whose `accessibleName` is
rewritten and then announced with `QAccessible::updateAccessibility` and an
`Alert` event.

Announced, and nothing else:

- selection change — "Bubble 4 of 12 selected. Page 3 of 20."
- page change — "Page 4 of 20, {filename}, 12 bubbles."
- run progress at 25 / 50 / 75 / 100% — not per page, which would be 20 interruptions
- cost state entering `approaching` or `exceeded` — **once each**, not repeatedly
- run stopped, by the user or by the budget
- bake complete, with the output folder

## A-13 — What Qt genuinely cannot promise

Recorded honestly rather than asserted away:

1. **`QGraphicsItem`s are not exposed to UI Automation.** A `QGraphicsView` is one
   accessible object; the scene's bubbles, badges and indicators are invisible to
   a screen reader. The link is therefore conveyed through the list and the live
   region only (components.md §4.9). **Per-bubble screen-reader navigation is not
   promised in v1.** Providing it means implementing `QAccessibleInterface` over
   the scene, which is a story of its own.
2. **QSS has no reliable `outline`.** Focus rings are drawn as borders, or as a
   painted overlay where a widget has no spare border. A story that cannot
   achieve A-04 on some widget class must say so rather than skip the ring.
3. **Windows High Contrast mode is supported.** *(Revised 2026-09-12 — see the
   note at the foot of this file. This clause previously read "v1 does not claim
   High Contrast support; the honest minimum is detecting it and saying so".)*
   The limit Qt imposes is real and is unchanged: `QApplication.setStyleSheet`
   wins over `QPalette`, so a fully QSS-themed app keeps painting its own
   colours while a contrast theme is active. That is treated as a **bug to fix**
   rather than as a reason to decline — the app re-resolves its own token values
   from the system palette under High Contrast instead of dropping or ignoring
   the stylesheet. What is promised, what is exempt, and what remains a genuine
   toolkit limit are all in **A-15**; the mapping and the reasoning are in
   [`high-contrast.md`](./high-contrast.md).
4. **Screen magnifier tracking** of the canvas depends on the same accessibility
   bridge as (1) and will not follow the selected bubble. Not claimed.

## A-14 — Scaling

The app must remain usable at Windows display scaling **100 % through 200 %**
without clipped text or overlapping controls, and at the minimum window size in
layout.md. Qt handles the scale factor; what must be checked is that no fixed
pixel width in the QSS clips a scaled label.

*Testable as:* instantiate each panel at 100 %, 150 % and 200 % and assert no
child's `sizeHint` exceeds its allocated geometry.

## A-15 — Windows High Contrast

The user decided on 2026-09-12 that a contrast theme is **supported**, not
detected and declined. This clause is the floor; the mapping, the alternatives
and the reasoning are in [`high-contrast.md`](./high-contrast.md). Sub-clauses
are numbered so a story can cite one line.

Read **A-15.1** first: it is what makes the rest achievable, and it is a
restatement of A-10 rather than a new requirement.

### A-15.1 — Six colours, and why the app survives them

A Windows contrast theme offers **six** user-set colours, and guarantees that
each foreground is legible **on its own paired background** — not that any six
are mutually distinguishable. `tokens.toml` declares 40 colour tokens. Under a
contrast theme they collapse onto five roles (A-15.2), so **colour carries no
distinction under HC beyond "selected" and "disabled"**.

Every place that collapse would destroy a distinction, **A-10** has already put a
glyph, a number, a shape or a word. A-15 is therefore not a licence to re-open
A-10: a story that adds a state distinguished only by hue fails A-10 first and
A-15 as a consequence.

### A-15.2 — Five roles, and no others

Under HC every non-exempt colour token resolves to exactly one of `Window`,
`WindowText`, `Highlight`, `HighlightedText`, `DisabledText`. `Button`,
`ButtonText` and `Link` are **not used**: Windows guarantees the pairs
(`WindowText` on `Window`, `HighlightedText` on `Highlight`), not the cross
products, so restricting to two pairs plus one disabled foreground means every
combination the app can produce is one the OS has promised.

*Testable as:* assert the set of distinct roles in the HC map is a subset of
those five, and that `resolve` never returns a value not present in the injected
palette or in `TOKENS`.

### A-15.3 — Resolution is total, and never silently falls back

`resolve(name, high_contrast, palette)` returns the authored value when
`high_contrast` is false; when true it returns the authored value for an exempt
token and the palette value otherwise. **An unknown token, or a mapped role
absent from the palette, raises.** A silent fall-back to the authored value is
"High Contrast not supported", arrived at quietly, and is forbidden.

Every colour token in `tokens.toml` **must** carry an HC mapping. A colour token
with no mapping is a generation failure, not a default — so adding a colour
forces a decision about its HC behaviour.

*Testable as:* a pure function, no Qt and no display. Assert totality over
`TOKENS`; assert the raise on a missing role; assert a colour token with no
mapping fails generation.

### A-15.4 — Detection is injectable, and defaults to off

High Contrast reaches the app as **one boolean**, read from
`SystemParametersInfo(SPI_GETHIGHCONTRAST)` and refreshed on `WM_SETTINGCHANGE`,
behind an interface that a test can substitute. The offscreen platform does not
report a contrast theme, so **injectability is a requirement, not a convenience**:
without it nothing below is testable on CI.

**When the platform call is not wired, fails, or the platform is not Windows, the
flag is off.** This is the opposite polarity from A-09 and the reason is in
high-contrast.md §3: falling back to the authored theme is a failure of respect,
which is recoverable; falling forward into an unpopulated palette is a failure of
legibility, which is not.

### A-15.5 — The artwork and everything painted on it is exempt

**The High Contrast boundary is the edge of the page pixmap.** Chrome follows the
contrast theme; the page and everything drawn over it keeps its authored values.

Every `overlay.*` colour, plus `color.canvas.surround` and
`color.canvas.page-edge`, resolves to its authored value in **every** mode. A
contrast theme cannot reach the user's scan, so the contrast problem on the
canvas is identical with the setting on and off — and the two-stroke mechanism
of **A-06** already solves it against both extremes of the artwork, which no
single HC colour can (`tokens.md` §5). Applying HC to the markers would replace a
guarantee with a single flat colour and break A-06.

*Testable as:* for every token whose name starts with `overlay.`, and for
`color.canvas.surround` and `color.canvas.page-edge`, assert
`resolve(name, high_contrast=True, palette=P) == TOKENS[name]` for any `P`.

### A-15.6 — Under HC nothing is dimmed on purpose

`overlay.dim.opacity` resolves to **1.0** under High Contrast. Dimming
non-selected markers is the one place the app deliberately reduces contrast, and
a contrast theme is a request not to. The link survives on stroke width, the
region fill and the **filled ordinal badge** — and per `components.md` §4.2 the
ordinal, not colour, is the primary carrier of the bubble ↔ line link.

*Testable as:* with HC injected true, no marker is painted at an opacity below
1.0 while a region is selected; with HC false, non-selected markers are at 0.55.

### A-15.7 — Every status glyph is distinguishable in one colour

The six review-status glyphs, and the five `CostReadout` states, must each be
distinguishable from every other **by silhouette and text alone**, at 16px, in a
single colour — because under HC they are all `WindowText`.

`edited` (filled pencil) and `reverted` (outlined pencil with a return arrow)
**do not currently satisfy this**. Under HC, `reverted` is rendered as a **return
arrow alone**, no pencil. *(Whether the dark theme adopts the same single glyph
set is an open decision for the product owner — high-contrast.md §5.)*

*Testable as:* enumerate the six statuses and assert the glyph identifier is
unique per status in each mode; enumerate the five cost states and assert the
`(figure text, glyph, meter fill)` triple is unique.

### A-15.8 — Focus takes the foreground of the ground it sits on

Under HC, the focus ring is `WindowText` on a `Window` ground and
`HighlightedText` on a `Highlight` ground, at `focus.width` 2px. Selection is a
ground inversion and focus is an outline, so **A-04**'s requirement that the two
be simultaneously legible holds without a second colour. Hover under HC is a 1px
`WindowText` **outline**, never a ground change — otherwise hover and selection
would both be `Highlight`.

### A-15.9 — Where an HC colour meets the mat, it is checked at runtime

The canvas frame and the canvas focus ring are the only HC-resolved colours ever
painted against the non-HC `color.canvas.surround`. Both pure white (6.39:1) and
pure black (3.29:1) clear A-04's 3:1 against `#5F5F5F`.

A user-edited contrast theme can still break that. **If the resolved value fails
3:1 against `color.canvas.surround`, the app uses the authored
`color.canvas.frame` / `color.focus.ring` for the canvas boundary only.**

*Testable as:* a pure function of two colours. Assert the fallback triggers for a
mid-grey `WindowText` and does not for `#FFFFFF` or `#000000`.

### A-15.10 — A live change loses nothing

Switching a contrast theme on or off while the app is running re-composes and
re-applies the stylesheet and repaints the canvas, and preserves the selected
region, the translation column's scroll position, the canvas zoom and pan, and
**uncommitted text in an open `LineEditor`**. The change is announced once
through the live region (**A-12**); no notice, banner or toast is shown.

### A-15.11 — What is still not promised

- **Per-bubble screen-reader navigation** — unchanged, see A-13.1. High Contrast
  does not affect it either way.
- **A fully user-customised contrast theme** is supported on a best-effort basis:
  the five roles are honoured whatever their values, and A-15.9 protects the one
  place a pathological value could hide the page. The measured claims in this
  clause are made for contrast themes whose Text colour is at or near either
  extreme.
- **That Qt populates `QPalette` from the contrast theme at all** is researched,
  not observed (high-contrast.md §2.2). The story must read the real palette and
  record the six values; the bounded fallback is to read the Windows colours
  directly through `ctypes`, which changes the source of the five-key dict and
  nothing else.

---

## How a story cites this

> Acceptance criterion: the selected bubble marker satisfies **A-06** — rendered
> over a uniformly white page and over a uniformly black page, at 25 % and 400 %
> zoom, at least one stroke of the marker clears 3:1 against the page.

Cite the clause number. If a story needs to depart from a clause, that is an
amendment to this document, made before RED, not a note in the story.

---

## Revisions

| Date | Change | By |
|---|---|---|
| 2026-09-12 | Original, during `/plan-product`. | **lead-designer on Claude Opus 5 (`claude-opus-5`)**, dispatched by lead-po on Claude Opus 5 (`claude-opus-5`). No override. |
| 2026-09-12 | **A-13.3 revised** from "Windows High Contrast is not supported in v1; the honest minimum is detecting it and saying so" to a support commitment, and **A-15** added with sub-clauses A-15.1 – A-15.11. New companion file [`high-contrast.md`](./high-contrast.md). The user decided that High Contrast is supported rather than detected and declined. | **lead-designer on Claude Opus 5 (`claude-opus-5`)**, dispatched by lead-po on Claude Opus 5 (`claude-opus-5`). No override was applied to this dispatch. |
