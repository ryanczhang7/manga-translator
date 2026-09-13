# Tokens

Values live in `tokens.toml`, which is the source of truth. This file says what
each group is for, why the values are what they are, and what a test may assert.
Where the two disagree: values from the TOML, reasons from here.

---

## 1. How tokens reach the code

QSS is a CSS subset with **no variables**. It cannot hold a token. So the token
set is authored once as data and compiled into two artefacts, because there are
two consumers and they are not interchangeable:

| Artefact | Generated from | Consumed by |
|---|---|---|
| `theme.qss` | `theme.qss.in` + `tokens.toml` | `QApplication.setStyleSheet` — all widget chrome |
| `tokens_gen.py` | `tokens.toml` | Python paint code |

**The second one is not optional.** QSS does not style `QGraphicsItem`s. Every
bubble marker, badge, leader line and focus ring drawn on the page canvas is
painted by Python with a `QPen`/`QBrush`, and those colours must come from the
same source as the chrome or the two will drift. This is the single biggest
consequence of the Qt choice for design.

**Placeholder syntax** in `theme.qss.in` is `@{dotted.token.name}`. `@` has no
meaning in QSS, so a template is still a readable stylesheet.

**Python constant name** = dotted path, uppercased, `.` and `-` both to `_`.
`color.text.on-accent` → `COLOR_TEXT_ON_ACCENT`. The module also exports
`TOKENS: dict[str, str]` keyed by the dotted name, so a test can iterate.

**Token name grammar:** `^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9-]*)*$`.

**What a test may assert about the generator:**

- every `@{...}` placeholder in the template resolves; an unresolved placeholder
  is a build failure, not a silent empty string
- every token in `tokens.toml` appears in `TOKENS`, and every constant matches
  the name grammar
- generation is deterministic: same input, byte-identical output
- the committed generated files match a fresh generation (a gate regenerates and
  diffs, so the checked-in copies cannot drift from the TOML)

---

## 2. Theme: dark only, one theme

**Decision: v1 ships exactly one theme, dark. No light theme, no follow-system.**

Why:

- The art is the content and it is black-on-white. Dark chrome makes the page the
  brightest object on screen without any deliberate emphasis, which is the whole
  of the brief's "the art is the largest thing on screen at all times".
- Every tool this user already lives in — Photoshop, Lightroom — defaults dark for
  the same reason.
- One theme is one contrast matrix, one QSS artefact, one set of screenshots to
  verify. For a single-user tool, a second theme doubles the accessibility
  surface and buys nothing measurable.

**The losing option, recorded.** A light theme has a real argument: white chrome
approximates the printed page, and a dark surround makes a white scan look
*higher* in contrast than it is (simultaneous contrast), which can lead a user to
under-estimate how grey a weak scan really is. That argument is why
`color.canvas.surround` is a mid grey rather than near-black (§4) — the cost is
paid there rather than by shipping two themes. If the user ever needs to judge
screentone density seriously, the follow-up is a *surround brightness* control,
not a light theme.

**Follow-system** is deferred, not rejected. If it lands, it is a third state
alongside two explicit choices, and the choice persists in app settings.

---

## 3. Chrome neutrals are achromatic

Every value under `color.surface.*`, `color.border.*` and `color.text.*` has
`R == G == B`. A blue-grey chrome — the default taste of most dark UIs — casts a
complementary tint onto adjacent greyscale, and the adjacent greyscale here is
the artwork the user is judging. The one exception is `color.surface.selected`,
which is chromatic on purpose: it is the selection ground, not chrome.

This is a checkable rule, not a preference. See accessibility.md **A-11**.

---

## 4. The canvas surround

`color.canvas.surround = #5F5F5F`, sRGB L* ≈ 40, achromatic, and **not derived
from the surface ramp** — it is its own token so that re-tinting the chrome can
never drag the mat with it.

It is the only chrome value lighter than the panels. That is deliberate: it reads
as a photographic mat around the page rather than as more application. The
alternative — a surround darker than the panels, as Photoshop does — was rejected
because near-black behind a white page produces exactly the simultaneous-contrast
exaggeration described in §2, and this app's entire job is letting a human judge
what is on a scan.

The reference point is the neutral grey surround that image-evaluation practice
puts around a displayed image (ISO 12646 specifies a neutral, roughly L*≈50,
background for soft-proofing). This app is not a colour-critical soft-proofing
environment — the source is B/W line art and the output is a PNG the user opens
in Photoshop afterwards — so L*≈40 is chosen as the closest value to that
convention that still reads as chrome rather than as a light theme. A *surround
brightness* setting is the named follow-up if this ever proves wrong.

Measured: `#5F5F5F` against a white page is 6.39:1 and against black art 3.29:1 —
neither is a glare boundary, and the page always reads as an object.

Two supporting tokens: `color.canvas.page-edge` (a 1px near-black line round the
page pixmap, so a white page has a defined edge against the mat) and
`color.canvas.frame` (a 1px `#7A7A7A` line where the mat meets chrome, 3.53:1
against `surface.raised`, so the viewport is a visible object).

---

## 5. Overlay colours over artwork — and why one colour cannot work

The markers are drawn over black-and-white line art plus screentone. The
arithmetic is unforgiving: clearing 3:1 against `#FFFFFF` requires relative
luminance ≤ 0.175, and clearing 3:1 against `#000000` requires ≥ 0.183. **No
single flat colour clears 3:1 against both.** A marker that is only a coloured
outline is therefore guaranteed to disappear somewhere on some page.

**The mechanism.** Every marker is stroked twice on the same path: a dark halo
(`overlay.halo`, `overlay.stroke.halo` px each side) and a light core (the state
colour, `overlay.stroke.core-*` px). Over light art the halo carries contrast;
over dark art the core does. The pair always clears the floor, and this is a
property of the *token pair*, so a unit test can check it without a screenshot.

**Verification — computed, not eyeballed.** WCAG 2.x relative luminance and
contrast ratio, computed for each core against the darkest art it can sit on and
for the halo against the lightest, plus a 50% screentone as the awkward middle:

| Token | vs `#000000` | vs `#1A1A1A` | vs `#808080` | vs `#FFFFFF` |
|---|---|---|---|---|
| `overlay.bubble.idle` `#D6DCE2` | 15.19 | — | 2.86 | 1.38 |
| `overlay.bubble.hover` `#A8E4FF` | 15.21 | — | 2.86 | — |
| `overlay.bubble.selected` `#4CC2FF` | 10.47 | 8.68 | 1.97 | — |
| `overlay.bubble.error` `#FF7A7A` | 8.32 | 6.89 | 1.56 | — |
| `overlay.halo` `#0B0B0B` | 1.07 | — | **4.98** | **19.68** |

Read it as the guarantee, not as a column each: the worst case for a core over
dark art is 6.89:1, and the worst case for the halo over light or mid art is
4.98:1. Every regime is covered by one of the two strokes.

**The assertable form** (accessibility.md A-06), which is what a story should
cite:

- for every `overlay.bubble.*` core C: `contrast(C, #000000) >= 3.0`
- `contrast(overlay.halo, #FFFFFF) >= 3.0` and `contrast(overlay.halo, #808080) >= 3.0`
- `overlay.stroke.halo >= 1` and every `overlay.stroke.core-* >= 2`

**What is NOT verified and needs a story to check:** that the halo is actually
painted for every marker in every state at every zoom, including the badge and
the leader line, and including the off-screen edge indicator. The token
arithmetic guarantees nothing if the paint code draws one stroke. A screenshot
test that samples the marker path over a synthetic all-white and an all-black
page is the honest check; it is named in accessibility.md A-06.

**Cosmetic pens.** `overlay.stroke.*` are device pixels and the pens are
cosmetic (`QPen.setCosmetic(True)`). A scene-width pen would vanish at 25% zoom
and swallow the bubble at 400%.

**Colour is never the only carrier.** Every marker also carries its reading-order
ordinal as a badge, and the selected state additionally changes stroke width and
dims its neighbours. See components.md §4.

---

## 6. Contrast of the chrome palette — measured

All computed with the WCAG 2.x formula. Body text floor 4.5:1, interactive
boundary floor 3:1.

| Pair | Ratio |
|---|---|
| `text.primary` on `surface.base` | 14.56 |
| `text.primary` on `surface.raised` | 12.93 |
| `text.primary` on `surface.overlay` | 11.60 |
| `text.primary` on `surface.selected` | 9.10 |
| `text.secondary` on `surface.raised` | 7.30 |
| `text.secondary` on `surface.selected` | 5.14 |
| `text.muted` on `surface.raised` | 4.99 |
| `text.muted` on `surface.base` | 5.62 |
| `text.disabled` on `surface.raised` | 3.19 |
| `border.interactive` on `surface.raised` | 3.53 |
| `border.interactive` on `surface.base` | 3.97 |
| `border.interactive` on `surface.overlay` | 3.16 |
| `accent.base` on `surface.base` | 8.50 |
| `accent.base` on `surface.selected` | 5.31 |
| `text.on-accent` on `accent.base` | 8.38 |
| `status.danger` on `surface.raised` | 5.99 |
| `status.warning` on `surface.raised` | 9.36 |
| `status.success` on `surface.raised` | 7.98 |
| `text.on-danger` on `status.danger` | 7.23 |
| `text.on-warning` on `status.warning` | 9.98 |
| `text.on-success` on `status.success` | 9.06 |
| `focus.ring` on `surface.base` | 17.04 |
| `focus.ring` on `canvas.surround` | 6.39 |
| `focus.ring` on `focus.halo` | 19.68 |

`border.subtle` (1.35) and `border.default` (1.58) are **decorative separation
only** and carry no floor. Any boundary of an interactive control uses
`border.interactive`. That distinction is why three border tokens exist rather
than two.

`surface.selected` against `surface.raised` is only 1.42:1 — the selected row is
**not** distinguished by its ground. The contrast-bearing element is a 3px
`accent.base` bar on the row's leading edge (5.31:1 against the selected ground,
7.54:1 against the unselected one) plus a filled ordinal badge. Recorded here so
nobody "fixes" the low ratio by brightening the ground and washing out the
editor text sitting on it.

---

## 7. Focus is white; selection is azure

They must be different, because both can be true at once: a row can be selected
while focus sits in the page strip, and focus can be on a row that is not the
selected one during keyboard traversal.

- **Selection** — `accent.base` azure: the 3px leading bar, the filled ordinal
  badge, the bubble's core stroke.
- **Focus** — `focus.ring` white, `focus.width` 2px at `focus.offset` 2px, with a
  1px `focus.halo` dark ring outside it wherever the ring may fall over artwork.
  White is chosen because it is the only value that clears 3:1 against every
  chrome surface *and* the mat without a second thought, and because it is
  unmistakably not the selection colour.

QSS cannot draw a reliable `outline` on every widget class. Focus rings on
widgets are drawn as a `border` in the `:focus` selector where the widget has a
spare border, and by a small painted-overlay helper where it does not. That is an
implementation note, but it belongs here because it constrains the token: the
ring is a **border-shaped** 2px value, not an outline with an outset.

---

## 8. Type

`type.family.ui` is the Windows system font (`Segoe UI Variable Text`, falling
back to `Segoe UI`). It is never bundled, so there is no licence question — the
lettering font is the only font this project ships, and it has its own document.

`type.editor` is 15px while `type.body` is 13px. The translation line is the
thing a human reads closely for hours; it gets the larger step, and it is the
only place in the chrome that does.

`type.numeric` and `type.numeric-lead` are `Consolas`, chosen over Segoe UI with
`tnum` because Consolas is present on every supported Windows and needs no
OpenType feature plumbing. Every figure the user might compare across a run —
cost, page counts, elapsed — uses them, so digits keep their columns.

---

## 9. Elevation without shadows

QSS has no `box-shadow`, and `QGraphicsDropShadowEffect` is a real per-frame cost
alongside a `QGraphicsView` that is already compositing a large pixmap and dozens
of overlay items. So elevation is **surface step + border**:

- `e0` flat chrome, no border
- `e1` raised panel: `surface.raised` + 1px `border.subtle`
- `e2` popover / menu / dialog: `surface.overlay` + 1px `border.default`, and
  **may** carry one drop shadow (blur 24, y-offset 4, `#00000073`). At most one
  on screen at a time, top-level popups only.

If a design ever seems to need a third elevation, the answer is a border, not a
shadow.

---

## 10. Motion

| Token | Value | Used for |
|---|---|---|
| `motion.duration.fast` | 120ms | hover/press feedback, badge highlight |
| `motion.duration.base` | 180ms | canvas pan-to-selection, panel expand/collapse |
| `motion.duration.slow` | 280ms | toast entry, run-panel state change |
| `motion.easing.standard` | `OutCubic` | everything positional |
| `motion.easing.emphasized` | `OutQuint` | pan-to-selection |
| `motion.easing.linear` | `Linear` | progress bar fill only |

**What animates, exhaustively:** the canvas pan when selection moves a bubble
into view; the translation column's scroll-into-view; progress bar fill; toast
entry and exit; the disclosure of the Japanese source text. **Nothing else.**
No hover transitions on rows (they fight a fast reader), no zoom animation (zoom
is user-owned and must feel direct), no bubble pulse.

**Reduced motion.** Qt exposes no cross-platform reduced-motion flag. On Windows
the setting is *Settings → Accessibility → Visual effects → Animation effects*,
readable through `SystemParametersInfo(SPI_GETCLIENTAREAANIMATION)` — a platform
call, not a Qt API. The app reads it once at startup and on
`WM_SETTINGCHANGE`, and exposes it as a single boolean. **When animations are
off, every `motion.duration.*` is treated as 0**: the canvas jumps, the list
jumps, the progress bar steps, the toast appears without sliding. Nothing is lost
because no meaning is carried by motion — see accessibility.md A-09. This is
named as an integration risk: if the platform call is not wired, the app must
default to *animations off*, never to on.

---

## 11. Typeset tokens are not chrome tokens

`[typeset]` describes lettering baked into the **output pages**. Its sizes are in
page pixels at the scan's own resolution, not device pixels, and it is consumed
by the render pipeline, not by the UI. It lives in the same file so that one
document is the source of truth for the product's appearance, but no chrome
component may read it and no typeset code may read a chrome token.

The font itself, its licence and the alternatives are in
[`typeset-font.md`](./typeset-font.md).

---

## 12. High Contrast resolution — what it does to the artefacts

*Added 2026-09-12, when the user decided a Windows contrast theme is supported.
The floor is `accessibility.md` **A-15**; the mapping and the reasoning are in
[`high-contrast.md`](./high-contrast.md). This section is only the consequence
for §1's generated artefacts, because that is a contract MT-025 has to carry.*

**The values above do not change.** `tokens.toml` gains `[hc]`, `[hc.map]` and
`[hc.override]`, which are **metadata about** the tokens, not tokens. Not one
existing value is edited, so the committed `theme.qss` is byte-identical and
MT-025's AC-5 is untouched. What changes is the **generator's** job.

### 12.1 Four artefacts, not two

| Artefact | Committed? | New? |
|---|---|---|
| `theme.qss` | yes | no — unchanged, the default (non-HC) sheet |
| `tokens_gen.py` | yes | gains two generated data structures (§12.2) |
| the placeholder template, copied into the package | yes | **new** |
| the High Contrast override template | yes | **new** |

The third exists because a contrast theme's colours are known only at runtime, so
the HC sheet **cannot be a committed file** — it is composed when the app starts,
from the template and the live palette. The template is currently the generator's
*input* and lives outside the package; the running app now needs it, and a
PyInstaller build ships only what the package carries (MT-024). Emitting it as an
artefact rather than reaching back at a source path is what keeps the installer
honest.

The fourth is the small **append-only** override sheet for the handful of HC
behaviours that are rule changes rather than value changes — hover becomes an
outline, a ghost button acquires a boundary, elevation stops using a surface
step, the focus ring takes the foreground of its ground. Its placeholders live in
their own namespace, `@{hc.RoleName}`, and each must name one of the five roles
in `[hc].roles`. **It may only override selectors the base template already
defines.** That restriction keeps one file authoritative for structure and is
mechanically checkable.

### 12.2 What `tokens_gen.py` gains — data, not logic

- `HC_PALETTE_ROLE: dict[str, str]` — token dotted name → a palette role, or the
  `@static` sentinel. **Total over the colour tokens**: a colour token with no
  `[hc.map]` entry is a generation failure, in the same shape as AC-4's orphan
  report. That totality is the whole anti-drift mechanism — adding a colour
  forces a decision about its High Contrast behaviour.
- `HC_OVERRIDE: dict[str, str | float]` — from `[hc.override]`. Keys must name an
  existing token.

**The resolution function is hand-written and does not live in the generated
module.** The generated module carries data only; logic in a generated file is
logic nobody reviews. Its shape is in high-contrast.md §4.3, and its palette
argument is a plain `dict[str, str]` rather than a `QPalette` — which is what
makes the whole resolution layer testable with no Qt, no display and no contrast
theme.

### 12.3 The generator must not mistake metadata for tokens

Every key under `[hc]` is excluded from the token set, from `TOKENS`, from the
constant-name mapping and from the orphan report. An `[hc.map]` key is a
*reference to* a token, not a declaration of one. Stated here because a generator
that flattens the document naively will emit `HC_MAP_COLOR_SURFACE_BASE` as a
token and every downstream assertion will then be counting the wrong things.
