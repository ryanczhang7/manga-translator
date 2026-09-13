# Design decisions — manga translator

*Produced by **lead-designer on Claude Opus 5 (`claude-opus-5`)**, dispatched by
lead-po on Claude Opus 5 (`claude-opus-5`), on 2026-09-12, during
`/plan-product`. No model override was applied to this dispatch.*

*Revised 2026-09-12 by **lead-designer on Claude Opus 5 (`claude-opus-5`)**,
dispatched by lead-po on Claude Opus 5 (`claude-opus-5`), no override — the user
decided that **Windows High Contrast is supported**, not detected and declined.
That closed open question 4, reversed `accessibility.md` **A-13.3**, added
**A-15**, and added [`high-contrast.md`](./high-contrast.md), `tokens.md` §12 and
`components.md` §10. Two new design-notes blocks are below.*

Source of truth for how the product looks and behaves. The product brief
(`docs/wiki/product-brief.md`) is the source of truth for scope; where this
contradicts the brief, the brief wins and this is wrong.

| File | Contents |
|---|---|
| [`tokens.toml`](./tokens.toml) | **the machine-readable token source** — values only |
| [`tokens.md`](./tokens.md) | what each token group is for and why the values are what they are |
| [`components.md`](./components.md) | every component v1 needs, with every state |
| [`layout.md`](./layout.md) | window, regions, the one breakpoint, z-order |
| [`accessibility.md`](./accessibility.md) | the floor, clause-numbered so stories can cite it |
| [`typeset-font.md`](./typeset-font.md) | **resolves O5** — the lettering font, its licence, the alternatives |
| [`high-contrast.md`](./high-contrast.md) | **resolves open question 4** — how a Windows contrast theme is supported, the full token mapping, and what is exempt |
| [`voice.md`](./voice.md) | tone, terms, error-message shape |

---

## The six decisions most worth arguing with

Recorded here so a reviewer can find them without reading everything, and so the
losing option is visible.

1. **Dark theme only.** One theme, no light, no follow-system. The losing argument
   — that a dark surround makes a white scan look higher in contrast than it is —
   is real, and is paid for in the canvas surround rather than by a second theme.
   tokens.md §2.
2. **The canvas surround is a mid grey (`#5F5F5F`), lighter than all chrome.** It
   reads as a photographic mat rather than as more application. The conventional
   alternative (surround darker than panels, as Photoshop does) was rejected.
   tokens.md §4.
3. **No single overlay colour can clear 3:1 against both black and white art**, so
   every marker is stroked twice — dark halo, light core. This is a mechanism,
   not a palette. tokens.md §5, accessibility.md A-06.
4. **"Looked at" is an explicit act, never inferred.** Review status is
   `proposed / accepted / edited / reverted / failed`, and success measure S1
   depends on it meaning something. Review does **not** gate the render.
   components.md §7.
5. **Per-bubble screen-reader navigation of the canvas is not promised**, because
   Qt does not expose `QGraphicsItem`s to UI Automation. The link is conveyed
   through the list and a live region instead. accessibility.md A-13.
6. **Under Windows High Contrast, the boundary is the edge of the page pixmap.**
   Chrome follows the user's contrast theme; the artwork and everything painted
   on it keeps its authored values, and nothing is dimmed. The losing option —
   making the markers and the mat follow the contrast theme too, which is what
   "supported" naively means — was rejected because a contrast theme offers one
   flat foreground per ground, and tokens.md §5 proves no single flat colour
   clears 3:1 against both black and white art. Applying HC to the canvas would
   *replace a guarantee with the exact failure it was designed to prevent.*
   accessibility.md A-15, high-contrast.md §6–§7.

---

## Design notes for the stories being written

Lift these into each story's `## Design notes`. Each names one thing a test can
actually assert. The first four were written during `/plan-product`; the last two
were added with the High Contrast revision, and my sizing view is that High
Contrast is **two** stories, not one — the seam is stated in the second block.

### Story: the page workspace shell

> The workspace is three regions in visual order — `PageStrip` (96px fixed),
> `PageCanvas` (all remaining width), `TranslationColumn` (340px, resizable
> 280–560) — plus a 48px header and a 44px footer. The canvas carries the entire
> splitter stretch factor so that enlarging the window enlarges only the art.
> Ground is `color.surface.base`; the canvas mat is `color.canvas.surround` with a
> 1px `color.canvas.frame` line where it meets chrome and a 1px
> `color.canvas.page-edge` outline round the page pixmap. Minimum window size
> 1100 × 720, enforced. States to cover: empty (no chapter), loading page, loaded,
> page-failed-to-decode. Theme values come from the generated artefacts, never
> from literals in the widget code. See layout.md and components.md §3.
>
> **Assertable:** resizing the window from 1100 to 1900 px increases
> `PageCanvas.width()` by the full delta while `PageStrip.width()` and
> `TranslationColumn.width()` are unchanged. Also: no colour literal appears in
> the workspace widget source — every colour resolves through `tokens_gen`.

### Story: the bubble ↔ line link

> One selection at a time, held as a single `selected_region_id`; hover is
> separate state and never changes selection. The primary carrier of the link is
> the reading-order ordinal, rendered as a badge on the art and as the leading
> element of the row — so the link survives without colour. Selected bubble:
> `overlay.bubble.selected` core at `overlay.stroke.core-selected` over an
> `overlay.halo` stroke, `overlay.fill.selected`, filled badge, **and every other
> marker dimmed to `overlay.dim.opacity`**. Selected row: `color.surface.selected`
> ground, 3px `color.accent.base` leading bar, filled badge. Hover highlights both
> sides but never scrolls the list and never pans the canvas. Selection pans the
> canvas by the minimum amount that brings the region fully into view with
> `space.6` margin, and **never changes zoom**. If the region still is not fully
> visible, the `OffscreenIndicator` appears at the nearest viewport edge. Pens are
> cosmetic. Overlapping regions: smallest-area-wins hit test, repeated clicks
> cycle. Keyboard: `Up`/`Down` move selection in either pane, `Enter` on the
> canvas moves focus into the selected row's editor. See components.md §4 and
> accessibility.md A-06, A-07, A-10.
>
> **Assertable:** selecting a row whose region lies outside the viewport pans the
> view so the region's bounding rect is fully contained with ≥ 24px margin, while
> `transform().m11()` (the zoom) is unchanged — and selecting a row whose region
> is already fully visible does not change the viewport at all.

### Story: editing and persisting a translation line

> The `LineEditor` is a plain single-logical-line field, `type.editor`, ground
> `color.surface.sunken`, 2px `color.accent.base` border while editing. It accepts
> no line breaks: `Shift+Enter` does nothing and pasted newlines collapse to
> spaces, because manual line-break control is a brief §5 non-goal. `*italic*` and
> `**bold**` are literal text the typesetter resolves later. `Enter` commits,
> `Esc` restores the value the field had when editing began, `Ctrl+R` reverts to
> the machine proposal, `Ctrl+Enter` marks the line accepted without editing.
> Status is one of `proposed / accepted / edited / reverted / failed`, each with a
> distinct gutter glyph as well as a colour, and `Revert` / `Accept` / `Retry` are
> always-visible controls on the row, never hover reveals. A commit writes to disk
> (debounced 500 ms); a failed save shows the reason and **keeps the text in the
> field**. See components.md §5–7, accessibility.md A-07, A-10.
>
> **Assertable:** typing into a line and pressing `Enter` moves its status to
> `edited` and the value is present on disk; pressing `Ctrl+R` afterwards restores
> the proposal text exactly and the status becomes `reverted`, not `proposed` —
> and the two are visually distinct.

### Story: run progress and the cost readout

> `RunProgressPanel` shows a determinate overall bar ("Page 7 of 20"), the current
> page thumbnail with markers appearing as they are found, and a four-step
> `PageStageStepper` (Detecting → Reading → Translating → Done) rather than a
> single spinner. Estimated remaining time appears only after three pages
> complete. `CostReadout` is in the header during the run and in the workspace
> header afterwards: `$0.83` in `type.numeric-lead`, "of $2.00" in `type.caption`,
> a 4px meter, and a projection once two pages are priced. Five states —
> `unknown` (shows `$—`, **never `$0.00`**), `normal`, `approaching` (≥ 75% spend
> or projection ≥ budget: `color.status.warning` meter plus a warning glyph),
> `exceeded`, `aborted`. A budget abort is an `ErrorBanner`, not a modal, and it
> names what survived and offers "Review pages 1–13" and "Change budget…"; the
> budget is a setting with a $2.00 default, not a constant. See components.md §8
> and voice.md.
>
> **Assertable:** with zero priced calls the readout renders `$—` and not
> `$0.00`; crossing 75% of the budget moves it to `approaching` and emits exactly
> one live-region announcement, and staying above 75% for further pages emits no
> further announcements.

---

### Story: High Contrast — token resolution *(MT-026, the first of two)*

> A Windows contrast theme offers **six** colours and guarantees only that each
> foreground is legible on its own paired background, so the 40 colour tokens
> collapse onto five palette roles — `Window`, `WindowText`, `Highlight`,
> `HighlightedText`, `DisabledText` — and colour stops carrying any distinction
> beyond "selected" and "disabled"; the app survives that only because
> accessibility.md **A-10** already put a glyph, a number or a word behind every
> colour signal. `tokens.toml` gains `[hc.map]`, `[hc.override]` and `[hc]`, which
> are **metadata about** tokens and must be excluded from `TOKENS` and from the
> orphan report, and `[hc.map]` must be **total** over the colour tokens so that
> adding a colour forces a decision about its High Contrast behaviour. Resolution
> is a hand-written pure function — `resolve(name, high_contrast, palette)` over a
> plain `dict[str, str]` palette, never a `QPalette` — that returns the authored
> value when the flag is false, the authored value for an exempt token, and
> **raises** on an unknown token or a role missing from the palette, because a
> silent fall-back is "High Contrast not supported" arrived at quietly. Every
> `overlay.*` colour plus `color.canvas.surround` and `color.canvas.page-edge` is
> exempt in every mode (A-15.5), `overlay.dim.opacity` resolves to 1.0 (A-15.6),
> and detection is one injectable boolean that defaults **off** when the platform
> call is not wired (A-15.4) — the offscreen platform never reports a contrast
> theme, so injectability is a requirement and not a convenience. See
> accessibility.md A-15.1–A-15.6 and A-15.9, tokens.md §12, high-contrast.md §3–§5.
>
> **Assertable:** with the flag injected true and a synthetic palette
> (`Window` `#000000`, `WindowText` `#FFFFFF`, `Highlight` `#1AEBFF`,
> `HighlightedText` `#000000`, `DisabledText` `#3FF23F`), every `color.*` token
> that is not exempt resolves to one of those five values, while **every**
> `overlay.*` token, `color.canvas.surround` and `color.canvas.page-edge` resolve
> byte-for-byte to `TOKENS[name]` and `overlay.dim.opacity` resolves to 1.0 — and
> with the flag false every token resolves to `TOKENS[name]`. Also: a palette
> missing `Highlight` raises rather than returning the dark value, and a colour
> token added with no `[hc.map]` entry fails generation.

### Story: High Contrast — applying it to the screen *(MT-028, the second of two)*

> The seam from MT-026: that one decides **what colour a token is**; this
> one decides **that the widgets and the scene actually use it** — the same seam as
> MT-025 (values) against MT-015/MT-016 (widgets). Under HC the stylesheet is
> composed at runtime from the generated placeholder template plus an append-only
> override template whose `@{hc.RoleName}` placeholders name one of the five roles
> and which may only override selectors the base template already defines; the
> committed `theme.qss` is unchanged and is still what ships for the default
> theme. The overrides carry the handful of behaviours that are **rule** changes
> rather than value changes: hover becomes a 1px `WindowText` outline and never a
> ground change (otherwise hover and selection are both `Highlight`), a `ghost`
> button gains a boundary, elevation drops the surface step and the `e2` drop
> shadow, and the focus ring takes the foreground of the ground it sits on —
> `WindowText` on `Window`, `HighlightedText` on `Highlight` (A-15.8). On the
> canvas exactly three things change and the markers are not among them: dimming
> stops, `color.canvas.frame` becomes `WindowText` at 2px, and the viewport focus
> ring follows HC — each falling back to its authored value if it fails 3:1
> against the `#5F5F5F` mat, which is the only place an HC colour meets a non-HC
> ground (A-15.9). See components.md §10 for the per-component deltas, especially
> §10.4 (the `edited` ↔ `reverted` glyph, which is **not** distinguishable in one
> colour and becomes a return arrow alone) and §10.6 (the five `CostReadout`
> states, which under HC are told apart by a unique `(figure text, glyph, meter
> fill)` triple and never by hue).
>
> **Assertable:** with the HC flag injected true and a synthetic palette, the
> composed stylesheet contains no authored token literal for any non-exempt
> colour — no `#1C1C1C`, no `#4CC2FF` — while `#0B0B0B` and every
> `overlay.bubble.*` value are still present for the scene; and toggling the flag
> at runtime re-applies the sheet while `selected_region_id`, the canvas
> `transform().m11()`, the column's scroll value and the uncommitted text in an
> open `LineEditor` are all unchanged (A-15.10).

---

## Open questions and flags for the Lead PO

1. ~~Edits must persist to disk during review, not only at render.~~
   **Satisfied by architecture.md D7** (SQLite project file). The design
   requirement stands and is restated here so it is not lost: a commit in the
   `LineEditor` must be durable within 500 ms, not held until render. This user
   reviews for hours and losing an hour of typing is the worst thing the app can
   do to them. components.md §6.
2. ~~The API budget must be a user setting.~~ **Satisfied** —
   `budget_ceiling_usd` in `settings.json` (architecture.md §Storage, D6). The
   budget-abort banner's "Change budget…" action is therefore honest. No open
   question remains.
3. ~~**An app-level "lettering font file" setting**~~ **RESOLVED — the user said
   yes on 2026-09-12.** Shantell Sans stays the default and still ships; one
   app-wide override is in scope, per-bubble control is not. The scope reading is
   recorded in the brief's §5; the story is **MT-027**. typeset-font.md §3.
4. ~~**Windows High Contrast mode is not supported in v1**, and the honest minimum
   is detecting it and saying so.~~ **RESOLVED — the user said support it, on
   2026-09-12.** A-13.3 is revised, **A-15** is the floor and
   [`high-contrast.md`](./high-contrast.md) carries the mapping and the
   reasoning. Stories: **MT-026** (resolution) and **MT-028** (application).
   *(These two list entries were struck by lead-po on Claude Opus 5
   (`claude-opus-5`) on 2026-09-12, to stop this index contradicting A-13.3 and
   A-15. The substantive High Contrast design in `accessibility.md` and
   `high-contrast.md` is the Lead Designer's own, same date and model.)*
5. **The font's glyph coverage is unverified** and is deliberately written as a
   test rather than an assertion. typeset-font.md §6.

*Raised by the High Contrast revision. Items 6 and 7 are the two follow-on
decisions High Contrast forces that are the user's or the PO's rather than mine;
8 and 9 are pre-existing gaps the work surfaced and which I deliberately did
**not** fold into it.*

6. **The `reverted` glyph — needs a decision, not a design.** `edited` (filled
   pencil) and `reverted` (outlined pencil with a return arrow) are not reliably
   distinguishable at 16px in a single colour, which is what High Contrast
   reduces every status glyph to, and components.md §7 makes the distinction
   load-bearing for S1. **Under HC, `reverted` is a return arrow alone** — that
   part I decided. Whether the **dark theme** adopts the same single glyph set is
   the PO's call: one glyph set is cheaper to build and to test than two, but it
   amends components.md §7 and MT-017. components.md §10.4, accessibility.md
   A-15.7.
7. **How far "supported" extends to a user-edited contrast theme.** The five roles
   are honoured whatever their values, and A-15.9 protects the one place a
   pathological value could hide the page. But the measured claims (6.39:1 and
   3.29:1 against the mat) hold for themes whose Text is at or near an extreme.
   Recommend promising the four shipped Windows themes and best-effort beyond,
   and saying so in the product brief rather than only in A-15.11.
8. **`color.canvas.page-edge` is single-stroked**, so a scan with a black page
   border has no visible edge against the mat. A **pre-existing gap in A-06's
   two-stroke mechanism**, not one High Contrast introduced. The fix is to draw
   the page edge as the same halo-plus-core pair every other marker uses. Worth
   its own small story; not folded into the HC work. high-contrast.md §7.2.
9. **`overlay.dim.opacity` 0.55 is not covered by A-06's arithmetic.** A-06's
   floors are stated on token *values*, not on the composited value of a *dimmed*
   marker: `overlay.halo` at 0.55 over a white page composites to about `#797979`,
   which clears 3:1 against white (≈4.4:1) but nowhere near it against a 50%
   screentone (≈1.1:1). Under High Contrast this is moot, because dimming stops
   (A-15.6) — in the **default** theme it is real and unverified. Raising it
   rather than quietly widening A-06, which would change what MT-016 must satisfy
   after MT-016 was already written.
