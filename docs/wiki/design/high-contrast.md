# Windows High Contrast

*Revision, 2026-09-12, by **lead-designer on Claude Opus 5 (`claude-opus-5`)**,
dispatched by lead-po on Claude Opus 5 (`claude-opus-5`). No override was applied
to this dispatch. This file did not exist before this revision; it is the reason
`accessibility.md` **A-13.3** changed from "not supported in v1" to the promise in
**A-15**. The user decided that High Contrast is supported, not merely detected
and declined.*

`accessibility.md` **A-15** is the clause-numbered floor a story cites. This file
is the reasoning and the full mapping. Where the two disagree, A-15 wins and this
file is wrong.

---

## 1. What High Contrast actually is, and the one number that decides the design

Windows 11 calls it a **contrast theme** (*Settings → Accessibility → Contrast
themes*; Aquatic, Desert, Dusk, Night sky, plus user-edited variants). A contrast
theme is not a dark theme and not a palette tweak. It is a promise the operating
system makes to the user:

> Nothing on your screen is low contrast on purpose.

A contrast theme lets the user set **six** colours: Text, Hyperlinks, Disabled
Text, Selected Text (a foreground *and* a background), Button Text (a foreground
*and* a background), and Background. What the OS guarantees is not that any six
values are distinguishable from each other — it is that each **pair** is
distinguishable: foreground-on-its-own-background.

That number, six, is the whole design problem. `tokens.toml` declares **40 colour
tokens**. Under a contrast theme they must collapse onto a handful of system
values, and *colour stops being able to carry any distinction at all* beyond
"this is a selected thing" and "this is disabled".

**This app can survive that collapse only because it already never leans on
colour alone.** `accessibility.md` **A-10** is not a nicety here; it is the
precondition that makes High Contrast support a week of work rather than a
redesign. Every place the collapse would destroy a distinction, A-10 has already
put a glyph, a number, a shape or a word there. Section 5 walks each one and says
whether A-10's existing carrier is actually sufficient — twice, it is not, and
those are recorded as findings rather than waved past.

---

## 2. The mechanism: which of the three options, and why

Three ways to make a QSS-themed Qt app respect a contrast theme:

| Option | What it does | Verdict |
|---|---|---|
| **(a) Drop the stylesheet** | `setStyleSheet("")` under HC; let the native style paint from the system palette | **Rejected.** It discards padding, radii, border widths and the row's leading bar along with the colours, and it does nothing for the canvas, which is custom painting either way. The app's information architecture is carried by structure as much as by colour; throwing the structure away to fix the colour is a bad trade. |
| **(b) Re-render the stylesheet from the system palette** | Same template, colour placeholders resolve to palette values instead of authored ones | **Chosen.** Structure survives; colour follows the user. |
| **(c) Hand-maintain a second stylesheet** | A parallel `theme-hc.qss` with literal values | **Rejected.** Two sources of structure drift, and literal values cannot honour a *user-edited* contrast theme, which is the majority of the ones that matter. |

**Chosen: (b), plus a small append-only override sheet.**

Option (b) alone is not quite enough, because a few HC behaviours are *rule*
changes rather than *value* changes — hover must stop being a ground swap, a
ghost button must acquire a boundary, elevation must stop using a surface step.
Those live in a second, short template that is **appended** to the first under HC
and is never used otherwise. It may only override selectors the base template
already defines; it may not introduce new ones. That restriction is checkable and
keeps one file authoritative for structure.

### 2.1 Why a stylesheet overriding the palette is the bug to fix

Qt populates `QPalette` from the system, and the native Windows style paints from
that palette. But `QApplication.setStyleSheet` wins over the palette for every
property a rule touches. A fully QSS-themed app therefore keeps painting its own
colours while the user's contrast theme is active — the app looks like it is
ignoring the setting, because it is. Option (b) fixes this at the source: under
HC, the stylesheet's colour values *are* the palette's.

### 2.2 What is not certain, and must be verified rather than assumed

Stated plainly so the story checks rather than trusts:

1. **Whether Qt 6.8 populates `QPalette` from a Windows contrast theme at all**,
   and with which roles. Researched, not observed. The story must read
   `QApplication.palette()` on a machine with a contrast theme active and record
   the six values in its handoff. **If Qt does not populate them**, the bounded
   fallback is to read the Windows colours directly through `ctypes`
   (`GetSysColor`, and the contrast theme's own colours) — a different source for
   the same five-key dict, not a different design. Everything downstream of
   §3 is written against a `dict[str, str]`, precisely so that this can change
   without touching anything else.
2. **Whether the palette is populated before the app's first `setStyleSheet`**,
   and whether Qt re-emits it on `WM_SETTINGCHANGE` / `QEvent.PaletteChange`.
3. **Whether re-applying the stylesheet re-polishes every widget**, including
   ones with a custom `paintEvent`. It should; it is not proven.

None of these change the design. All three change the *implementation*, and all
three are cheap to observe. Writing them here rather than asserting a mechanism
is the honest form.

---

## 3. Detection, and the fail-closed default

The same shape as the reduced-motion flag in **A-09**, deliberately, so there is
one pattern for "a Windows setting Qt does not expose":

- `SystemParametersInfo(SPI_GETHIGHCONTRAST)` → the `HIGHCONTRAST` struct's
  `dwFlags & HCF_HIGHCONTRASTON`. A `ctypes` call; no new dependency.
- Read once at startup, refreshed on `WM_SETTINGCHANGE`.
- Exposed to the rest of the app as **one injectable boolean**. Nothing below the
  adapter knows what Windows is.

**Default when the call is not wired, fails, or the platform is not Windows:
High Contrast OFF.**

This is the opposite polarity from A-09, which defaults animations *off*, and the
difference is deliberate rather than an inconsistency:

- A-09's unsafe state is animation the user did not want. Off is safe.
- Here, the unsafe state is applying an HC mapping against an **unpopulated or
  partial palette** — which produces black on black, an app the user cannot read
  at all. The authored dark theme is not a guess: every pair in it is measured in
  `tokens.md` §6 and clears 4.5:1. Falling back to it is a failure of *respect*,
  which is recoverable; falling forward into an unverified palette is a failure of
  *legibility*, which is not.

So: when in doubt, the measured theme. Recorded here because the two defaults
look contradictory and are not.

---

## 4. The resolution model

### 4.1 Five roles, and only five

Under HC every colour token resolves to one of:

| Key | Qt `QPalette` role | Windows contrast-theme colour |
|---|---|---|
| `Window` | `Window` | Background |
| `WindowText` | `WindowText` | Text |
| `Highlight` | `Highlight` | Selected Text (background) |
| `HighlightedText` | `HighlightedText` | Selected Text (foreground) |
| `DisabledText` | `Disabled` group's `WindowText` | Disabled Text |

**`Button`, `ButtonText` and `Link` are deliberately not used.** Windows
guarantees the *pairs*, not the cross products: `WindowText` on `Window` and
`HighlightedText` on `Highlight` are contractually legible; `WindowText` on
`Highlight` is not, and `ButtonText` on `Window` is not. Restricting the app to
two foreground/background pairs plus one disabled foreground means **every colour
combination the app can produce under HC is one the OS has promised**. Using more
roles would buy variety at the cost of pairs nobody has guaranteed, which is the
usual way HC support is implemented and the usual way it is wrong.

The cost is real and is accepted: under HC the four button variants
(`primary` / `secondary` / `ghost` / `destructive`) collapse to two appearances,
and status hues collapse to one. §5 says what carries each of those instead.

### 4.2 Exempt tokens: the `@static` sentinel

A token mapped to `@static` keeps its authored value in **every** mode. Three
groups are exempt, each for a stated reason (§6 and §7):

- every `overlay.*` colour — painted onto the user's artwork, which HC cannot
  reach
- `color.canvas.surround` and `color.canvas.page-edge` — a viewing condition and
  a boundary against the artwork, not chrome
- every non-colour token except `overlay.dim.opacity`

### 4.3 The resolution function

```
resolve(name, *, high_contrast: bool, palette: Mapping[str, str]) -> str
```

- `high_contrast=False` → the authored value. Always. No exceptions, no partial
  HC.
- `high_contrast=True` → the authored value if the token maps to `@static`,
  otherwise `palette[role]`.
- An unknown token name, or a mapped role missing from `palette`, **raises**.

That last rule is the one that matters. A silent fall-back to the authored dark
value when a palette role is missing *is* "High Contrast not supported", arrived
at quietly, which is exactly what this revision exists to stop. It must fail
loudly at composition time, where a test can see it, rather than produce a
half-HC screen at runtime where nobody can.

`palette` is a plain `dict[str, str]` of `#RRGGBB` strings keyed by the five
names in §4.1 — **not** a `QPalette`. That makes the whole resolution layer pure:
it is testable with no display, no Qt, and no contrast theme, by passing a
synthetic palette. Snapshotting a real `QPalette` into that dict is a separate,
thin adapter with nothing to decide.

`resolve` is **hand-written, and does not live in the generated module.** The
generated module carries data only (`TOKENS`, `HC_PALETTE_ROLE`); logic in a
generated file is logic nobody reviews.

---

## 5. The mapping, and what each collapse costs

`@static` means the authored value is used unchanged under HC.

### Surfaces — the ramp collapses to one ground

| Token | HC |
|---|---|
| `color.surface.base` | `Window` |
| `color.surface.raised` | `Window` |
| `color.surface.sunken` | `Window` |
| `color.surface.overlay` | `Window` |
| `color.surface.hover` | `Window` |
| `color.surface.pressed` | `Window` |
| `color.surface.disabled` | `Window` |
| `color.surface.selected` | `Highlight` |

**What this costs:** the seven-step surface ramp is the app's entire elevation
model (`tokens.md` §9: elevation = surface step + border) and its entire hover
model. Both are gone.

**What carries it instead:** `tokens.md` §9 already says "if a design ever seems
to need a third elevation, the answer is a border, not a shadow" — under HC the
border does *all* of it. Every panel that was distinguished by `surface.raised`
against `surface.base` is distinguished by a 1px `WindowText` boundary; `e2`
popovers take a 2px one, and **the `e2` drop shadow is not painted under HC** (a
blurred translucent shadow on a flat maximum-contrast ground is either invisible
or noise, and it is the one place the design uses a soft edge).

Hover needs a different answer, because `surface.hover` and `surface.selected`
would otherwise both be `Highlight` and a hovered row would be
indistinguishable from a selected one. **Under HC, hover is a 1px `WindowText`
outline and never a ground change.** That is an override-sheet rule, not a token
value.

### Text

| Token | HC |
|---|---|
| `color.text.primary` | `WindowText` |
| `color.text.secondary` | `WindowText` |
| `color.text.muted` | `WindowText` |
| `color.text.disabled` | `DisabledText` |
| `color.text.on-accent` | `HighlightedText` |
| `color.text.on-danger` | `Window` |
| `color.text.on-warning` | `Window` |
| `color.text.on-success` | `Window` |

Three text weights collapse to one. That is correct: a contrast theme's user has
asked for every string to be maximally legible, and de-emphasis by hue is
precisely what they turned off. Hierarchy is still carried by the type scale
(`type.title` 16/600 vs `type.body` 13/400 vs `type.caption` 11/400), which HC
does not touch.

`text.on-*` are foregrounds for the rare filled status ground; under HC a filled
ground is `WindowText`, so its text is `Window` — the guaranteed pair, inverted.

### Accent, borders, focus

| Token | HC |
|---|---|
| `color.accent.base` | `Highlight` |
| `color.accent.hover` | `Highlight` |
| `color.accent.pressed` | `Highlight` |
| `color.accent.subtle` | `Highlight` |
| `color.border.subtle` | `WindowText` |
| `color.border.default` | `WindowText` |
| `color.border.interactive` | `WindowText` |
| `color.border.focus` | `WindowText` |
| `color.focus.ring` | `WindowText` |
| `color.focus.halo` | `Window` |

`border.subtle` was decorative-only (`tokens.md` §6 gives it no contrast floor).
Under HC it becomes structural, because it is now the only thing separating two
panels that used to differ by ground. That is a promotion, not a loss.

**Focus and selection must stay distinguishable, and they do** — for the reason
`tokens.md` §7 gives: both can be true at once. Under HC selection is a *ground
inversion* (`Highlight` + `HighlightedText`) and focus is a *2px outline*
(`WindowText`). Different mechanisms, so no collision. One consequence:

> **The HC focus ring takes the foreground role of the ground it sits on.**
> `WindowText` on a `Window` ground; `HighlightedText` on a `Highlight` ground.

A focused *and* selected row would otherwise draw `WindowText` on `Highlight` —
a pair nobody guaranteed. This is an override-sheet rule, not a second token.

`focus.halo` → `Window` is quietly elegant: ring and halo become the two halves
of the guaranteed pair, so wherever the ring falls, one of the two shows. It is
the same two-stroke idea as the canvas markers, for free.

### Status — three hues become one, and the glyph does all the work

| Token | HC |
|---|---|
| `color.status.danger` | `WindowText` |
| `color.status.warning` | `WindowText` |
| `color.status.success` | `WindowText` |

This is the largest single collapse in the app and the place **A-10** earns its
keep. Every status in the product already carries a distinct glyph:
hollow circle (`proposed`), filled check (`accepted`), filled pencil (`edited`),
outlined pencil-with-return (`reverted`), filled warning triangle (`failed`),
filled shrink glyph (`overflow`).

**Finding — two of those six are not sufficient in one colour.** `edited` (filled
pencil) and `reverted` (outlined pencil with a return arrow) differ by *fill* and
by a small appended arrow. At 16px, in a single colour, that is not a reliable
distinction, and `tokens.md`/`components.md` §7 make the `edited` ↔ `reverted`
distinction load-bearing: `reverted` means "I looked at this and put it back",
and success measure S1 depends on the two not being confused.

Recorded as **A-15.7** and resolved, under HC, by giving `reverted` a distinct
silhouette: a **return arrow alone**, no pencil. Whether the dark theme should
adopt the same single glyph set is a decision for the product owner and the user,
not for me — it would amend `components.md` §7 and MT-017. Flagged, not decided.

### Canvas

| Token | HC |
|---|---|
| `color.canvas.surround` | `@static` |
| `color.canvas.page-edge` | `@static` |
| `color.canvas.frame` | `WindowText` |

See §6 and §7.

### Overlay — every token exempt

| Token | HC |
|---|---|
| `overlay.halo` | `@static` |
| `overlay.bubble.idle` / `.hover` / `.selected` / `.error` | `@static` |
| `overlay.fill.hover` / `.selected` / `.error` | `@static` |
| `overlay.dim.opacity` | **overridden to `1.0`** |

See §7.

---

## 6. The canvas surround stays a mid grey

**Decision: `color.canvas.surround` does not follow High Contrast.**

The mat is not chrome and it is not a control. It is a **viewing condition** —
the neutral surround that image-evaluation practice puts around a displayed
image, and the reason `tokens.md` §4 chose L\*≈40 rather than the near-black a
photo editor uses. A contrast theme's `Window` is (in the shipped themes) pure
black or pure white. Adopting it would put one of the two extremes of the
greyscale directly against a scan that is made of those same two extremes, and
destroy the very boundary an HC user needs most: where the page stops.

Put bluntly: making the mat follow HC would make the *page harder to see*, which
is the opposite of what the setting was turned on for.

**What does change is the boundary.** `color.canvas.frame` — the line where the
mat meets chrome — becomes `WindowText` at `border-width.emphasis` (2px, up from
1px `#7A7A7A`). That is the line that tells an HC user where the application
stops and the artwork begins, and it is the only place an HC-resolved colour is
ever painted against a non-HC ground.

**So that one meeting point is checked, and it is the arithmetic that licenses
the whole decision:**

| HC `WindowText` | vs `color.canvas.surround` `#5F5F5F` |
|---|---|
| `#FFFFFF` | **6.39 : 1** |
| `#000000` | **3.29 : 1** |

Both clear A-04's 3:1. The mat's L\*≈40 — chosen for simultaneous-contrast
reasons that had nothing to do with HC — turns out to be exactly what makes it
safe to let an HC colour touch it. A darker mat would fail against black text; a
lighter one would fail against white.

**A user-edited contrast theme can still break this**, by setting Text to a mid
grey. So the rule is stated as a runtime check rather than as a claim about
Microsoft's four themes:

> If the resolved HC value for the canvas frame or the canvas focus ring fails
> 3:1 against `color.canvas.surround`, the app uses the authored
> `color.canvas.frame` / `color.focus.ring` for the canvas boundary only, and
> nothing else changes.

That is a pure function of two colours, so it is assertable without a display and
without a contrast theme.

---

## 7. The canvas markers do not change, and that is the decision

**Decision: the two-stroke mechanism is unchanged under High Contrast. Every
`overlay.*` colour is `@static`.**

This is the part most likely to be "fixed" later by someone who has not read
this, so the reasoning is written out.

High Contrast reaches application-drawn grounds. **It does not reach the user's
scan**, and the scan is what the markers are drawn on. The contrast problem the
markers solve is therefore *identical* with the setting on and with it off:
black-and-white line art plus screentone, a ground the app does not author and
cannot change.

Substituting HC colours into the markers would make that problem **worse, not
better**, and the arithmetic in `tokens.md` §5 is exactly the proof:

- Clearing 3:1 against `#FFFFFF` needs relative luminance ≤ 0.175; clearing 3:1
  against `#000000` needs ≥ 0.183. **No single flat colour clears both.**
- An HC palette offers exactly one foreground per ground — a single flat colour.
  Painting a marker in `WindowText` alone is precisely the failure mode §5 was
  written to rule out. Under Night sky the marker would be white and vanish into
  a white bubble interior; under Desert it would be black and vanish into the
  linework.
- The authored pair is already derived *specifically* to clear the floor against
  both extremes: worst case 6.89:1 for a core over near-black art, 4.98:1 for the
  halo over 50% screentone.

So the honest statement is not "the canvas is exempt from HC because it is hard".
It is: **the canvas already implements, against artwork, the same guarantee HC
implements against chrome — and it implements it better, because it was designed
for a ground HC cannot see.** Exempting the overlay tokens preserves that
guarantee; applying HC to them would destroy it.

### 7.1 What does change on the canvas: dimming stops

**`overlay.dim.opacity` resolves to `1.0` under HC.**

`components.md` §4.3 dims every non-selected marker to 0.55 while something is
selected, and calls dimming "the disambiguator". It is also the one place in the
app that **deliberately reduces contrast**, which is the exact thing a contrast
theme is a request not to do. A user who turned HC on to be able to see things
has not asked for eleven of twelve bubbles to be faded.

The link survives without it, because dimming was never the only carrier. With
dim at 1.0 the selected marker still differs from every other by **three**
simultaneous non-hue signals:

1. core stroke width — `overlay.stroke.core-selected` 3px vs `core-idle` 2px
2. an `overlay.fill.selected` wash inside the region, where idle has no fill
3. a **filled** ordinal badge with an `on-accent` numeral, where idle has an
   outline badge

Two of those three are shape and fill rather than colour. And per
`README.md` decision 2 and `components.md` §4.2, **the ordinal is the primary
carrier of the link and colour is secondary** — which is doing more work here
than the colours are. The ordinal badge is unchanged, on the art and in the row,
and it is what actually links a bubble to a line under a contrast theme.

### 7.2 The page edge — an honest limit, not an HC one

`color.canvas.page-edge` is a single 1px near-black line round the page pixmap.
It is `@static` for the same reason the markers are: it is drawn against the
user's page.

It is also **single-stroked**, so on a scan with a black gutter or a black page
border it has no contrast at all. That is a **pre-existing gap in A-06's
mechanism**, not something High Contrast introduced, and it is out of scope for
the High Contrast work. Recorded here so it is not lost, and raised separately
with the product owner. The fix, when it is written, is to draw the page edge as
the same halo-plus-core pair every other marker uses.

---

## 8. Live changes

A contrast theme can be switched on or off while the app is running, and a user
who is struggling to see the screen is exactly the user who will do so.

**On a mode change the app re-composes and re-applies the stylesheet and repaints
the canvas, and loses nothing**: not the selected region, not the scroll position
of the translation column, not the canvas zoom or pan, and — the one that would
actually hurt — **not uncommitted text in an open `LineEditor`**.

The change is announced once through the live region (**A-12**): "High contrast
on." / "High contrast off." Nothing else is announced, and no notice, banner or
toast is shown. The old A-13.3 proposed a one-line notice saying the app's own
theme was in use; under real support there is nothing to apologise for and a
notice would be an interruption.
