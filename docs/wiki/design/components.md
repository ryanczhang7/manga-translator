# Component inventory

Every component v1 needs, the states each must support, and the token that drives
each state. Token names are dotted paths into `tokens.toml`.

**Out of scope — do not design or build:** typeset box dragging or resizing,
per-bubble font or size control, manual line-break control, a reader or viewer,
any publishing or upload surface, any source language but Japanese, any target
but English, overlay/layer output. (Brief §5.)

---

## Screens

| Screen | Component |
|---|---|
| Intake | `FolderDropTarget`, `ChapterSummary`, `CostEstimate`, `Button` |
| Run | `RunProgressPanel`, `PageStageStepper`, `CostReadout`, `ErrorBanner`, `Button` |
| Review workspace | `WorkspaceShell`, `PageCanvas`, `BubbleMarker`, `OffscreenIndicator`, `TranslationColumn`, `TranslationRow`, `LineEditor`, `SourceDisclosure`, `PageStrip`, `ZoomControl`, `CostReadout`, `ShortcutSheet` |
| Bake | `BakeConfirmDialog`, `RunProgressPanel`, `EmptyState`, `Toast` |

---

## 1. Buttons

Four variants, one state table. Minimum hit target 28×28 px, 32px preferred (see
accessibility.md A-05 for why 28 and not 24).

| Variant | Ground | Text | Border |
|---|---|---|---|
| `primary` | `color.accent.base` | `color.text.on-accent` | none |
| `secondary` | `color.surface.raised` | `color.text.primary` | 1px `color.border.interactive` |
| `ghost` | transparent | `color.text.secondary` | none |
| `destructive` | transparent | `color.status.danger` | 1px `color.status.danger` |

| State | Change |
|---|---|
| default | as above |
| hover | ground → `color.accent.hover` (primary) / `color.surface.hover` (others); no size change, no transition |
| focus-visible | 2px `color.focus.ring` border at `focus.offset`; **in addition to** any hover/selected styling, never instead of |
| active (pressed) | ground → `color.accent.pressed` / `color.surface.pressed` |
| disabled | ground `color.surface.disabled`, text `color.text.disabled`, border `color.border.default`; still focusable and still carries a tooltip saying *why* |
| loading | label replaced by an indeterminate 3-dot indicator at the same width (no reflow), control becomes non-activatable but keeps focus, accessible name gains ", working" |

Radius `radius.sm`. Padding `space.2` vertical, `space.3` horizontal. Label
`type.body`.

---

## 2. Chapter intake

### `FolderDropTarget`

A dashed region occupying the intake screen's centre column.

| State | Appearance | Copy |
|---|---|---|
| **empty** (default) | 2px dashed `color.border.interactive`, `radius.md`, ground `color.surface.base` | headline (`type.display`) "Drop a chapter folder here"; body (`type.body`, `color.text.secondary`) "Or choose a folder. Pages are processed in filename order."; a `primary` button "Choose folder…" |
| **hover-valid** (drag carrying exactly one local directory) | border 2px solid `color.accent.base`; ground tinted `overlay.fill.hover` | headline "Release to load"; body the folder's name; no affordance text |
| **hover-invalid** (drag carrying files, or more than one item) | border 2px solid `color.status.danger` | headline "Drop a folder, not files", or "Drop one folder" when every item is a folder; body says what was dragged; no affordance text |
| **loading** | border 1px `color.border.default`; indeterminate bar; the resolved path in `type.caption` | "Reading folder…" + a `ghost` "Cancel" |
| **error** | border 2px solid `color.status.danger`; a danger-coloured icon | headline + the specific reason + `secondary` "Choose a different folder" |
| **populated** | replaced by `ChapterSummary` | — |
| **disabled** | ground `color.surface.disabled`, border `color.border.default` | only while a run is in progress; body says "A run is in progress." |

**Drag copy** (settled 2026-09-30, MT-056 Q1). A *folder* is a local path that
is an existing directory when the drag enters; any other local path is a
*file*. "Several" means two or more.

| Drag | Headline | Body |
|---|---|---|
| one folder | "Release to load" | `{name}` |
| one file | "Drop a folder, not files" | "You are dragging a file: `{name}`." |
| several files | "Drop a folder, not files" | "You are dragging `{n}` files." |
| several folders | "Drop one folder" | "You are dragging `{n}` folders. Drop them one at a time." |
| files and folders | "Drop a folder, not files" | "You are dragging `{f}` file(s) and `{d}` folder(s)." — "1 file", "2 files", "1 folder", "2 folders" |

- `{name}` is the base name, never the full path. A name longer than 40
  characters shows its first 20, then `…` (U+2026), then its last 19 — 40 in
  all. Exactly 40 is shown whole. The cut counts characters, not pixels.
- Several items are counted, never listed.
- A drag carrying any non-local URL, or no URLs at all (plain text), is
  **ignored**: not accepted, and the target does not change.
- The accessible description is the headline and body joined by a newline; the
  accessible name stays "Choose chapter folder" throughout.
- When the drag leaves, or an invalid drag is dropped, headline, body,
  affordance and description return exactly to the previous state.

**The region itself is a focusable button**, role `Button`, accessible name
"Choose chapter folder", activated by Enter or Space. Drag-and-drop is never the
only path to any behaviour.

**Enumerated error reasons** — each gets its own message, never a generic one.
The reason is the error state's headline, verbatim, plain text, word-wrapped:

| Reason | Headline (character-exact) |
|---|---|
| no `.png`/`.jpg`/`.jpeg` files directly in the folder | `No page images in {folder}. This tool reads .png and .jpg files.` |
| folder cannot be listed | `Windows would not let this app read {folder}.` + `\n` + `{os_error}` |
| a page file that will not decode | `{filename} could not be opened as a page image. Remove or replace it, then choose the folder again.` |

- `{folder}` is the **resolved full path** (`Path.resolve()`), exactly as the
  existing MT-054/MT-055 texts print it - never the base name, never cut.
- `{os_error}` is the OS error's `strerror` when it has one, else `str(error)`.
  It follows the sentence **on its own line**: the two are joined by a single
  `\n`, nothing else.
- `{filename}` is the file's name as it is in the folder - base name only, never
  cut. With several undecodable files it is the **first in processing order**
  (`order_filenames`), which is `read_chapter`'s `UnreadablePage` rule. No
  summary is shown and nothing is skipped.
- The backticks around `.png`/`.jpg` in earlier drafts were formatting, not
  copy: the label is plain text and shows no backticks.
- more than 200 images → not an error. A warning in `ChapterSummary`: "That is
  more pages than a chapter. Estimated cost is *$x*." Nothing is blocked.
  (MT-058; it is the third line of `CostEstimate`, below.)

> **Amended 2026-09-30 (MT-057, PO-4 and PO-5).** This section used to say an
> undecodable image "loads anyway" and is listed in `ChapterSummary` as skipped,
> and gave the order warning a "Use natural order" toggle. Both are withdrawn by
> the user's decisions. **PO-4:** the store reads a chapter all-or-nothing -
> `read_chapter` raises `UnreadablePage` on the first undecodable file, because a
> skipped page would shift every later page's ordinal, and the ordinal is the
> page's identity for the rest of the product. So the folder is refused, naming
> the file, and the user fixes the folder. **PO-5:** the store has one order,
> natural (`order_filenames`), and page ordinals never change after intake; a
> toggle would need a store change for a hazard whose real harm - a *silently*
> wrong order - the notice already removes by listing both orders. The PO's
> draft sentence "…as an image. Remove or replace it and choose the folder
> again." became "…as a page image. Remove or replace it, then choose…": the
> interface says *page* (voice.md, Terms) and AC-2 already says "page images".

### `ChapterSummary`

The **populated** state of the intake screen: it replaces `FolderDropTarget`
when a chosen folder with no project reads as a chapter. Every figure in it
comes from `read_chapter` and `order_filenames` - the order shown is the order
the run uses, by construction.

The designed summary is: folder name, page count, first and last filename, a
scrolling row of thumbnails in processing order, and the `CostEstimate`, then a
`primary` "Start run". **MT-057 ships it without the thumbnail row, without
`CostEstimate` (MT-058) and without "Start run" (MT-059)**, and without the
loading state; those parts stand as designed for the stories that add them.
**MT-058 adds `CostEstimate` as part 5**, between the page facts and the order
notice (amended 2026-10-01; the notice and the button move down one number).

**Parts, top to bottom** (MT-057, MT-058). Every part is a plain-text `QLabel`
(`Qt.PlainText` set before the text: a folder or file named with `<` is not
markup), word-wrapped, selectable by mouse only, never a focus stop.

| # | Part | Copy (character-exact) | Token |
|---|---|---|---|
| 1 | heading | `{name}` | `type.title`, `color.text.primary` |
| 2 | page count | `1 page` when there is one page, else `{n} pages` | `type.body`, `color.text.primary` |
| 3 | first page | `First page: {first}` | `type.body`, `color.text.secondary` |
| 4 | last page | `Last page: {last}` | `type.body`, `color.text.secondary` |
| 5 | cost estimate | `CostEstimate`, below; always present (MT-058) | see `CostEstimate` |
| 6 | order notice | see below; present only when the orders differ | see below |
| 7 | leave | `secondary` button `Choose a different folder` | §1 |

*Why the estimate sits above the notice rather than at the foot, where the
original sketch had it:* the notice lists every filename twice, so for a long
chapter it is hundreds of names, and an estimate below it would be scrolled out
of sight on the one screen whose job is to show the cost before it happens. The
estimate is a fact about the page count (it is that count times a rate), so it
belongs beside it.

- `{name}` is the folder's **base name** (for a drive root, the path itself),
  with the **40-character middle cut** of "Drag copy" above (first 20, `…`,
  last 19). The heading's accessible name is the whole uncut base name.
- `{n}` is the page count in digits. `{first}` and `{last}` are the first and
  last entries of `order_filenames`, whole, never cut.
- **Exactly one page:** parts 3 and 4 are replaced by one line,
  `Only page: {first}`. No "Last page" line is shown.
- Spacing: `space.2` below the heading, `space.1` between parts 2-4, `space.4`
  above the cost estimate, `space.4` above the notice, `space.4` between the
  scroll area and the button.

**Filename-order warning** (part 6). Shown exactly when `sorted(names)` (plain
string order) differs from `order_filenames(names)`; not shown when they agree -
`p1 … p9` shows no notice, `p1 … p12` does. Three plain-text lines, in this
order:

| Line | Copy (character-exact) | Token |
|---|---|---|
| lead | `These filenames sort differently as numbers and as text. The run uses natural order.` | `type.body-strong`, `color.text.primary` |
| natural | `Natural order (used): {natural}` | `type.body`, `color.text.primary` |
| lexical | `Text order (not used): {lexical}` | `type.body`, `color.text.primary` |

- `{natural}` is every filename in `order_filenames` order; `{lexical}` every
  filename in `sorted()` order. Separator `", "` (comma, one space). **Every
  filename is listed, never elided** - 200 pages means 200 names in each line.
- The lines word-wrap at the column width; the notice grows; the summary scrolls
  (below). Nothing scrolls horizontally.
- Ground `color.surface.raised`, 1px border `color.status.warning`, `radius.sm`,
  padding `space.3`, lines `space.1` apart. No glyph: the lead sentence is the
  carrier (A-10), the border is emphasis only.
- There is **no control** in the notice (PO-5). Not dismissible, not role
  `Alert`, not a live announcement (A-12's list is closed; the summary appearing
  is the change, and it takes focus - below).

**Layout.** In the intake column (layout.md, "Intake and run screens"). Parts
1-6 sit in a `QScrollArea`: vertical scroll as needed, horizontal scroll **off**.
Part 7 is **outside** the scroll area, pinned at its foot, left-aligned, always
visible however long the lists are.

**Leaving the summary** (settled 2026-09-30, MT-057). MT-057 has no Start
button, so the only way on is `Choose a different folder`:

- Activating it opens the same folder dialog as the drop target
  (`choose_folder_dialog`, caption "Choose chapter folder").
- A folder chosen there goes down the **one** path every chosen folder takes
  (`MainWindow`'s hand-over, MT-056 C-2): a new summary, the drop target in its
  error state (which replaces the summary), or the workspace for a folder with a
  project.
- Dismissing the dialog changes nothing: the same summary, focus back on the
  button.
- **A folder dragged onto the summary is not accepted** in MT-057 - the summary
  does not accept drops, so the OS shows its no-drop cursor and nothing changes.
  Out of scope, recorded: the button is the keyboard path and the drop target
  is the drag path, and a drop onto the summary is a convenience for a later
  story. Drag-and-drop is still never the only path.

**Accessibility.**

- Focus order: the scroll area, then the button; `Tab`/`Shift+Tab` move between
  them. When the summary appears, **focus goes to the scroll area**. The scroll
  area takes `Up`/`Down`/`PageUp`/`PageDown`/`Home`/`End` to scroll, and shows
  the `color.focus.ring` per A-04. The button takes Enter and Space (§1 states;
  it has no disabled or loading state here).
- The scroll area's accessible name is `Chapter summary`; its accessible
  description is every visible line of parts 1-6 in order, joined by `\n`, with
  the heading's line as the whole uncut base name. A screen reader landing on it
  hears the summary, then the estimate's two or three lines, then the notice's
  three lines, each exactly as printed. *(MT-058 changes this description for
  every chapter, so the two MT-057 tests that pin it whole - in
  `tests/ui/test_chapter_summary.py`, the "described by its visible lines" and
  "one-page summary is described" cases - gain the estimate lines in MT-058's
  RED. They then fail against the MT-057 code, which is the right failure.)*
- The notice widget's accessible name is its three lines joined by `\n`.
- Contrast: `color.text.primary` and `.secondary` on `color.surface.base` and
  `color.surface.raised` clear A-01; `color.status.warning` border on
  `color.surface.base` clears A-02's 3:1.

- **empty** (folder had zero pages): handled by the drop target's error state, not here.
- **error**: none. A folder that cannot be read whole never reaches the summary
  (PO-4); its reason is the drop target's error state.

### `CostEstimate`

Shown **before** the run, as part 5 of `ChapterSummary`, because spend should be
observable before it happens as well as during (`CostReadout`, §8, is the
*during*).

> **Amended 2026-10-01 (MT-058, PO-1 and PO-2).** This section used to show a
> range in `type.numeric` with a `type.caption` qualifier - "Estimated for 20
> pages: **$1.10 – $1.90**. Budget $2.00." - and gave the component an `unknown`
> state, "No estimate yet — the first run of a chapter measures it". Both are
> **withdrawn for this screen** by the user's decision of 2026-09-30. **PO-1:**
> every chapter this screen shows is a folder with no project, so it is always on
> its first run: the `unknown` state would be the *only* state, and a range needs
> a rule nobody has stated. The domain has one number for a chapter nothing has
> been priced in - `BOOTSTRAP_PAGE_ESTIMATE` × pages, which is what the budget
> guard itself projects before the first call - and the screen and the guard must
> use **one number**, or they can disagree about whether a chapter fits. So the
> estimate is that single figure, labelled as an estimate. **PO-2:** the budget is
> `DEFAULT_CEILING`, $2.00, shown read-only; no budget setting exists yet (§8's
> "Change budget…" is the same gap). The `type.numeric`/`type.caption` split is
> withdrawn too: a plain-text label is one font, and this figure is read once in
> a sentence, not compared in a column or updated live, which is what
> `type.numeric`'s tabular digits are for. "Start run anyway" stays [[MT-059]]'s,
> read from the over-budget state below.

**Source of every figure.** The estimate `{x}` is
`Budget().project((), n).remaining_chapter` (`mangatl.domain.budget`), where `n`
is the page count; the budget `{b}` is `DEFAULT_CEILING`. Computed in `domain`,
formatted in `ui`. No money arithmetic in the widget, and no constant re-typed:
$0.06 and $2.00 are read from `budget.py`.

**Lines, top to bottom.** A `QFrame` holding two or three plain-text labels
(the `ChapterSummary` rules: `Qt.PlainText`, word-wrapped, selectable by mouse,
never a focus stop).

| # | Line | Shown | Copy (character-exact) | Token |
|---|---|---|---|---|
| 1 | estimate | always | `Estimated for {n} pages: {x}.` — for one page, `Estimated for 1 page: {x}.` | `type.body-strong`, `color.text.primary` |
| 2 | budget | **normal** state | `Budget {b}.` | `type.body`, `color.text.secondary` |
| 2 | budget | **over-budget** state | `Budget {b}. The estimate is over budget.` | `type.body`, `color.text.secondary` |
| 3 | page-count warning | `n > 200` only | `That is more pages than a chapter. Estimated cost is {x}.` | `type.body`, `color.text.primary` |

- `{n}` is the page count in digits, the same number as part 2's `{n} pages`.
  One page is `1 page`, as part 2 says it.
- Line 1 says *Estimated*; nothing on this screen presents the figure as a
  measured cost. Line 3 says *Estimated* again because it repeats the figure.

**Money format** (`{x}` and `{b}`):

- `$`, then the dollars in digits with a `,` every three digits from the right,
  then `.`, then **exactly two** decimals: `$0.06`, `$1.20`, `$12.06`,
  `$1,200.00`. Never `str(Usd)`, which prints four places; never `$1.2`.
- A value that is not a whole number of cents is rounded **up** (toward
  +infinity) to the next cent: $0.001 → `$0.01`, $1.141 → `$1.15`, $2.0001 →
  `$2.01`. Three reasons, all load-bearing: it is `budget.py`'s direction (an
  estimate that errs low lets a run start that it cannot finish); it makes the
  shown figure exceed `$2.00` **exactly when** the estimate exceeds the budget,
  so the figure and the over-budget state can never disagree (round-half-even
  would show `$2.00` for $2.004 and call it over budget); and it makes AC-5 hold
  by construction - any positive estimate shows at least `$0.01`.
- Today every `{x}` is a whole number of cents ($0.06 × `n`), so the rounding
  rule is observable only on the formatter itself; it is pinned there.
- **Never `$0.00` for a chapter of one or more pages** (§8's rule for
  `CostReadout`: an unmeasured cost shown as zero is a lie). A chapter of zero
  pages never reaches the summary (§2, `FolderDropTarget` errors).

**States.**

| State | Trigger | Appearance | Line 2 |
|---|---|---|---|
| **normal** | `{x} <= {b}` | 1px `color.border.subtle` border | `Budget {b}.` |
| **over-budget** | `{x} > {b}` | 1px `color.status.warning` border | `Budget {b}. The estimate is over budget.` |

- The comparison is on the **unrounded** `Usd` values and is **inclusive**, as
  `Budget.check`'s is: an estimate of exactly $2.00 is normal. With $0.06 and
  $2.00: 33 pages → `$1.98`, normal; 34 pages → `$2.04`, over-budget. (The
  boundary is 33.33 pages; tests read it from the two constants.)
- **Colour is not the only carrier** (`accessibility.md` A-10): the over-budget
  state is the sentence `The estimate is over budget.` The border is emphasis
  only. **No glyph** - the same choice as the order notice (part 6): the sentence
  carries it, and a font glyph in a plain-text label is font-dependent.
- The border is 1px in both states and the padding is the same, so the state
  changes nothing's position.
- The over-budget state is **queryable on the widget** as a boolean, not only
  readable as a colour: [[MT-059]] reads it to label its Start button "Start run
  anyway". Nothing is blocked in either state.
- **Line 3 does not set the state.** The page-count warning is text only. With
  today's constants every chapter over 200 pages is also over budget (201 pages →
  `$12.06`), so it shows all three lines in the over-budget frame - each line says
  one different thing (what it costs, how that compares with the budget, why the
  page count is unusual) and nothing is said twice except the figure, which line
  3's copy carries by design. Exactly 200 pages (`$12.00`) is over budget with
  no line 3.

**Worked examples** (lines joined by `\n`):

| Pages | State | Lines |
|---|---|---|
| 1 | normal | `Estimated for 1 page: $0.06.` / `Budget $2.00.` |
| 20 | normal | `Estimated for 20 pages: $1.20.` / `Budget $2.00.` |
| 33 | normal | `Estimated for 33 pages: $1.98.` / `Budget $2.00.` |
| 34 | over-budget | `Estimated for 34 pages: $2.04.` / `Budget $2.00. The estimate is over budget.` |
| 200 | over-budget | `Estimated for 200 pages: $12.00.` / `Budget $2.00. The estimate is over budget.` |
| 201 | over-budget | `Estimated for 201 pages: $12.06.` / `Budget $2.00. The estimate is over budget.` / `That is more pages than a chapter. Estimated cost is $12.06.` |

**Box.** Ground as the order notice (`color.surface.raised`, left to the
application palette while `theme.qss` is unapplied, as MT-057 records),
`radius.sm`, padding `space.3`, lines `space.1` apart, `space.4` above it (below
part 4) and `space.4` below it (above the notice, when there is one). It spans
the scroll area's width; every line word-wraps; nothing scrolls horizontally.
Identical at every window width.

**Accessibility.**

- Not a focus stop, no control, not role `Alert`, no live announcement: the
  summary appearing is the change, and focus goes to the scroll area
  (`ChapterSummary`, Accessibility).
- The frame's accessible name is its visible lines joined by `\n`, as the order
  notice's is.
- Its lines join the scroll area's accessible description **after part 4's lines
  and before the notice's**, exactly as printed. For a three-page chapter whose
  orders differ: `{name}` / `3 pages` / `First page: …` / `Last page: …` /
  `Estimated for 3 pages: $0.18.` / `Budget $2.00.` / the notice's three lines.
- Contrast: line text as parts 2-4 (A-01); the `color.status.warning` border on
  `color.surface.base` clears A-02's 3:1; `color.border.subtle` is decorative
  and carries nothing.

**Not states of this component on this screen:** `unknown` (withdrawn, above),
loading (the arithmetic is synchronous on a chapter already read), empty (zero
pages never reaches the summary), error (none: the figure cannot fail), hover /
focus-visible / active / disabled (not interactive). An estimate learnt from
earlier chapters, a range, and a budget field are out of scope (MT-058).

---

## 3. The page workspace

### `WorkspaceShell`

Three regions, all always present:

- **page strip** — left rail, `space.12` + thumb width
- **page canvas** — centre, takes all remaining width
- **translation column** — right dock, fixed width (see layout.md)

Plus a slim header carrying the chapter name, the page counter
(`type.numeric`, "Page 7 / 20"), the reviewed counter ("12 / 18 reviewed"), the
`CostReadout` and the `ZoomControl`, and a footer with the `primary` "Render
pages" and the reviewed-total.

### `PageCanvas` (`QGraphicsView` over a `QGraphicsScene`)

Ground `color.canvas.surround`. The page pixmap is drawn with a 1px
`color.canvas.page-edge` outline. A 1px `color.canvas.frame` line separates the
viewport from chrome.

| State | Appearance |
|---|---|
| empty (no chapter) | `EmptyState`: "No chapter loaded" + "Open a folder" |
| loading page | the mat, a centred indeterminate indicator, the page filename in `type.caption` |
| loaded | page + markers |
| panning | cursor `ClosedHand`; space-drag or middle-drag |
| zooming | Ctrl+wheel or the `ZoomControl`; zoom anchors on the cursor, or on the viewport centre for keyboard zoom |
| focus-visible | a 2px `color.focus.ring` inset border on the viewport, with a 1px `color.focus.halo` outside it |
| error (page will not decode) | the mat, a `color.status.danger` icon, the filename, and "This page could not be opened. It will be copied to the output folder unchanged." |

Zoom range 10%–800%. `Ctrl+0` fit page, `Ctrl+1` 100%, `Ctrl+9` fit the selected
bubble. Zoom is never changed by selection (§4).

### `PageStrip`

A vertical list of page thumbnails, one per page, in processing order. Each
carries its index and a status glyph:

| Page status | Glyph | Colour |
|---|---|---|
| pending | hollow circle | `color.text.muted` |
| running | half-filled circle, and the row is `color.accent.base` bordered | `color.accent.base` |
| translated, none reviewed | hollow circle | `color.text.secondary` |
| partly reviewed | half-filled check | `color.status.success` |
| fully reviewed | filled check | `color.status.success` |
| has a failed line | filled warning triangle | `color.status.danger` |
| skipped (undecodable) | filled dash | `color.text.disabled` |

States per row: default / hover (`color.surface.hover`) / focus-visible (ring) /
current (3px `color.accent.base` leading bar + `color.surface.selected`) /
disabled (during a run, non-current rows are not activatable but stay focusable).

Accessible name: "Page 7 of 20, *filename*, 12 of 18 lines reviewed".

### `ZoomControl`

`ghost` buttons − / fit / + with a `type.numeric` percentage between them.
States as §1. The percentage is also an editable field (Enter commits).

---

## 4. The bubble ↔ line link

**This is the product.** The review screen is the only place a human can catch a
bad translation, and an unclear link makes the review worthless. Everything below
is normative.

### 4.1 The model

- **Exactly one selection at a time.** App state is a single
  `selected_region_id: str | None`, scoped to the current page. There is no
  multi-select in v1.
- **Hover is separate state**, `hovered_region_id: str | None`. **Hover never
  changes selection**, and selection is never lost by moving the mouse.
- Both the canvas and the column render from that same state. Neither owns it.
- Changing page clears hover and sets selection to the new page's ordinal 1.

### 4.2 The ordinal is the primary carrier of the link

Every detected region on a page gets a **stable 1-based ordinal** from Japanese
reading order (right-to-left, top-to-bottom). The ordinal is rendered:

- on the art, as a filled `overlay.badge.size` circle at the region's **top-right**
  (reading order starts top-right), offset `overlay.badge.gap` from the outline
- in the column, as the leading element of the row

The link is therefore legible without any colour at all, which is what makes it
survive the accessibility floor's "colour is never the only carrier" rule and
makes it describable to a screen reader.

**Badge collision.** Badges never overlap each other. If a badge's circle would
intersect an already-placed badge, it slides along its own region's outline
(clockwise, in `overlay.badge.size / 2` steps) until it does not; if a full
circuit finds no free position, it is placed at the region's centroid. Placement
is deterministic in ordinal order, so the same page always produces the same
layout.

### 4.3 States on the art — `BubbleMarker`

Every marker is stroked twice: `overlay.halo` at `overlay.stroke.halo` px each
side, then the state core. See tokens.md §5 for why.

| State | Core colour | Core width | Fill | Badge |
|---|---|---|---|---|
| idle | `overlay.bubble.idle` | `overlay.stroke.core-idle` | none | outline badge, `overlay.bubble.idle` numeral |
| hover | `overlay.bubble.hover` | `overlay.stroke.core-hover` | `overlay.fill.hover` | outline badge |
| selected | `overlay.bubble.selected` | `overlay.stroke.core-selected` | `overlay.fill.selected` | **filled** badge, `color.text.on-accent` numeral |
| error (line failed) | `overlay.bubble.error` | `overlay.stroke.core-error` | `overlay.fill.error` | filled badge, warning glyph instead of a numeral |
| edited | core unchanged from its base state | — | — | a small pencil glyph appended beside the badge |
| dimmed | the state's own core at `overlay.dim.opacity` | unchanged | unchanged | dimmed with it |

**Dimming is the disambiguator.** While anything is selected, every *other*
marker drops to `overlay.dim.opacity`. On a dense page of eight overlapping
bubbles that is what makes the selected one unmistakable, and it costs nothing at
small zoom.

**Edited is a glyph, not a hue.** A fourth colour on artwork would compete with
the three that carry the selection model.

### 4.4 Hover behaviour

Bidirectional and purely visual.

- Hovering a marker → that marker takes `hover`, **and** the corresponding row
  takes its hover ground. **The column does not scroll.**
- Hovering a row → the marker takes `hover`. **The canvas does not pan or zoom.**
- Hover never dims other markers, never changes the selected marker's appearance,
  and never persists after the pointer leaves.

Scrolling or panning under a hover would move content out from under the user's
pointer. This restriction is deliberate; do not "improve" it.

### 4.5 Selection behaviour

Selecting is a click on a marker, a click on a row, or a keyboard move (§4.7).

**On the art.** The selected marker takes the `selected` state; all others dim.

**In the column.** The row takes `color.surface.selected` ground, a 3px
`color.accent.base` leading bar, and a filled badge. If the row is outside the
viewport, the column scrolls it into view with `space.4` of margin
(`motion.duration.base`, `motion.easing.standard`).

**The canvas pans, conditionally, and never zooms.** If the selected region's
bounding rect is not entirely inside the viewport, the canvas pans by the
**minimum** translation that brings it fully in with `space.6` of margin,
animated at `motion.duration.base` / `motion.easing.emphasized`. If the region
cannot fit at the current zoom, it is centred instead. **Zoom is never changed by
selection** — zoom belongs to the user; `Ctrl+9` is how they ask for it.

### 4.6 The selected bubble outside the visible region — `OffscreenIndicator`

If, after any pan, the selected region is still not fully visible (it did not
fit), or the user subsequently pans or zooms it out of view, an indicator
appears: a chevron plus the region's ordinal, pinned to the viewport edge nearest
the region's centre, drawn in `overlay.bubble.selected` **with the halo**, at the
same badge size.

- It appears only for the **selected** region, never for all of them.
- Clicking it, or pressing `Ctrl+9`, recentres the region.
- It has an accessible name: "Bubble 4 is off screen. Activate to show it."
- It disappears the moment the region is fully visible again.
- There is at most one.

### 4.7 Keyboard

The workspace is three focus stops in visual order: page strip → canvas →
translation column. `Tab` / `Shift+Tab` move between them; `F6` / `Shift+F6` do
the same (Windows pane convention). The focus ring always says which.

| Key | Where | Action |
|---|---|---|
| `Up` / `Down` | column or canvas | move selection to the previous / next ordinal on this page |
| `Home` / `End` | column or canvas | select ordinal 1 / the last ordinal |
| `Enter` | canvas | move focus to the selected row's editor and begin editing |
| `Enter` | column (row focused, not editing) | begin editing |
| `Enter` | column (editing) | commit and leave edit mode |
| `Esc` | column (editing) | cancel this edit session, restore the value the field had when editing began |
| `Ctrl+R` | column | revert the focused line to the machine proposal |
| `Ctrl+Enter` | column | mark the focused line **accepted** without editing |
| `Ctrl+J` | column or canvas | disclose / hide the Japanese source text for the selected line |
| `PageDown` / `PageUp` | anywhere not editing | next / previous page; selection lands on ordinal 1 |
| `Ctrl+0` / `Ctrl+1` / `Ctrl+9` | canvas | fit page / 100% / fit selected bubble |
| `Ctrl+=` / `Ctrl+-` | canvas | zoom in / out one step |
| `Space` + drag, or middle-drag | canvas | pan |
| `?` | anywhere not editing | open `ShortcutSheet` |

**`Enter` on the canvas is the keyboard expression of the link** and is the single
most important binding in the app: a user holding the keyboard can select a
bubble on the art and land in the right editor without touching the mouse.

Every action above is reachable without a pointer. Nothing is hover-only —
notably the **Revert** affordance, which is a visible control on an edited row,
not a hover reveal.

### 4.8 Overlapping regions

**Hit-testing.** A click picks, among all regions whose geometry contains the
point, the one with the **smallest area** — the innermost wins. Ties break to the
lowest ordinal. **Repeated clicks at the same point cycle** through every region
containing that point, in ascending ordinal order, wrapping. The point counts as
"the same" while the pointer stays within 3px of the first click.

**Draw order.** Bottom to top: dimmed idle, idle, hover, error, selected. Within
a tier, larger area first, so a small region is never buried by a large one. The
selected marker's core stroke is drawn last, so it is never clipped by a
neighbour's stroke. Badges are drawn above every outline.

### 4.9 Screen readers — what is promised and what is not

Qt bridges `QWidget` accessibility to Windows UI Automation. It does **not**
expose `QGraphicsItem`s: a `QGraphicsView` is a single accessible object and the
scene's contents are invisible to a screen reader. This is a real limit of the
toolkit and it is not worked around in v1.

**So the link is conveyed entirely through the list, and that is stated as the
promise:**

- the translation column is a real item view; each row has role `ListItem`, the
  `Selected` state, and a full accessible name (§5)
- the ordinal is inside the row's accessible name, so the correspondence to the
  art is describable
- a **live region** announces selection and page changes: "Bubble 4 of 12
  selected. Page 3 of 20."
- `PageCanvas` has role `Graphic` with accessible name "Page 3 of 20,
  *filename*" and a description "12 speech bubbles detected. Use the translation
  list to move between them."

**Not promised:** per-bubble screen-reader navigation of the canvas, spatial
description of the art, or reading order announced from the scene. If that
becomes a requirement, it needs a `QAccessibleInterface` implementation over the
scene and is a story of its own.

Qt has no ARIA-live equivalent. The live region is an off-screen `QLabel` whose
`accessibleName` is rewritten and then announced via
`QAccessible::updateAccessibility` with an `Alert` event.

---

## 5. `TranslationColumn` and `TranslationRow`

### Column states

| State | Appearance |
|---|---|
| loading | three skeleton rows, ground `color.surface.raised`, no spinner |
| populated | rows |
| empty (page has zero detected regions) | `EmptyState`: "No speech bubbles found on this page." + "The page will be copied to the output folder unchanged." + a `secondary` "Report this page" that copies the filename to the clipboard |
| error (the page's translation call failed entirely) | `ErrorBanner` above an empty list, with "Retry this page" |
| locked (a run or a bake is in progress) | rows read-only, text `color.text.secondary`, header states "Editing is locked while pages render." |

Column header: "Page 7 — 18 lines, 12 reviewed".

### `TranslationRow` anatomy

`[ status gutter ][ ordinal badge ][ line text / editor ][ actions ]`

| State | Ground | Leading bar | Gutter glyph | Glyph colour |
|---|---|---|---|---|
| default (`proposed`) | `color.surface.raised` | none | hollow circle | `color.text.muted` |
| hover | `color.surface.hover` | none | unchanged | unchanged |
| focus-visible | unchanged + 2px `color.focus.ring` inset border | unchanged | unchanged | unchanged |
| selected | `color.surface.selected` | 3px `color.accent.base` | unchanged | unchanged |
| `accepted` | per selection | per selection | filled check | `color.status.success` |
| `edited` | per selection | 2px `color.accent.base` even when unselected | filled pencil | `color.accent.base` |
| `reverted` | per selection | none | outlined pencil with a return arrow | `color.text.secondary` |
| `failed` | per selection + 1px `color.status.danger` border | none | filled warning triangle | `color.status.danger` |
| `overflow` (text will not fit the bubble at `typeset.size-min`) | per selection | none | filled "shrink" glyph | `color.status.warning` |
| disabled / locked | `color.surface.disabled`, text `color.text.secondary` | none | unchanged, dimmed | `color.text.disabled` |

A row may be `edited` **and** `overflow` at once: the gutter shows both glyphs,
in that order, and the accessible name mentions both.

`failed` rows additionally show the error text in `type.caption`
`color.status.danger` and a `secondary` "Retry line".

**Accessible name** (one string, in this order):

> "Bubble {n} of {total}. Japanese: {ocr, or 'not read'}. English: {text}.
> {status}." where status ∈ "machine proposal" | "accepted" | "edited" |
> "edited, then returned to the proposal" | "translation failed: {reason}" |
> "text will not fit the bubble".

### Row actions

Always visible on the row when applicable — **never hover-only**:

- `Revert` (`ghost`) — present whenever status is `edited`
- `Accept` (`ghost`, check glyph) — present whenever status is `proposed`
- `Retry line` (`secondary`) — present whenever status is `failed`

Hover-revealed actions were rejected: every one of these is a routine part of the
review loop, they must be keyboard-reachable, and one of them (Revert) discards
the user's typing.

---

## 6. `LineEditor`

An inline editor inside the selected row. `type.editor`, ground
`color.surface.sunken`, 1px `color.border.interactive`, `radius.sm`.

| State | Appearance |
|---|---|
| read-only (row not being edited) | no border, no ground; the text renders as a label |
| focus / editing | ground `color.surface.sunken`, 2px `color.accent.base` border, caret `color.text.primary` |
| dirty (uncommitted change) | as editing, plus a filled dot in the status gutter and the `Esc` hint in `type.caption` |
| committed → `edited` | border animates out over `motion.duration.fast`; row takes the `edited` state |
| committed → `reverted` | the text now equals the proposal exactly; row takes `reverted` |
| disabled / locked | ground `color.surface.disabled`, text `color.text.secondary`, not focusable for editing but the row stays focusable |
| error (commit failed to persist) | 2px `color.status.danger` border and a caption "Not saved: {reason}". The text is **kept in the field**; a failed save never silently discards typing. |

**One logical line.** The editor accepts a single line. `Shift+Enter` does
nothing; pasted newlines collapse to single spaces on paste. There is no way to
force a line break, because the brief forbids manual line-break control — the
typesetter chooses breaks. This is not a limitation to work around later; it is
the non-goal.

**Emphasis markers are literal text.** `*italic*` and `**bold**` appear as
written; the editor is plain, not rich. See typeset-font.md §7.

**Persistence.** A commit (Enter, or blur) writes to the chapter's working state
**on disk**, debounced 500ms. Edits must survive a crash: this user reviews for
hours and losing an hour of typing is the worst thing this app can do to them.
*(This has an architecture consequence — a per-chapter sidecar that is written
during review, not only at bake. Flagged to the Lead PO.)*

### `SourceDisclosure`

The Japanese OCR text for the selected line, collapsed by default, toggled by
`Ctrl+J` or a `ghost` disclosure control. `type.body`, `color.text.secondary`.
States: collapsed / expanded / unavailable ("OCR text not available for this
bubble"). Collapsed by default because the user reads English down the column and
the Japanese is a check, not the content.

---

## 7. Review status — what "looked at" means

**Decision: "looked at" is not inferred. It is an explicit act.**

Inferring review from scroll position or focus would mark lines reviewed that the
user skimmed past, and success measure S1 ("at least 80% of lines accepted
as-is") would then be measuring scrolling. So:

| Persisted status | How it is reached |
|---|---|
| `proposed` | the default; nothing has happened |
| `accepted` | the user pressed `Ctrl+Enter` or the Accept control — explicitly said "this is fine" |
| `edited` | the committed text differs from the machine proposal |
| `reverted` | the line was edited, and the committed text now equals the proposal exactly (via `Ctrl+R` or by retyping it) |
| `failed` | the pipeline could not produce a line |

**Reviewed** = `accepted | edited | reverted`. `reverted` counts as reviewed
because it was a deliberate act, and it is displayed distinctly from `proposed`
so the user can see they already looked.

Counters: per page in the column header and the page strip glyph; per chapter in
the workspace footer.

**Review does not gate the bake.** This is a first-pass tool; blocking render
until every line is ticked would fight the workflow the brief describes. Instead
`BakeConfirmDialog` states the number plainly: "6 of 340 lines were never
reviewed. Render anyway?" with the unreviewed lines listed by page.

---

## 8. Run progress

### `RunProgressPanel`

- **Overall**: determinate bar, `color.accent.base` fill on `color.surface.sunken`,
  `motion.easing.linear`, label "Page 7 of 20" in `type.numeric`.
- **Current page**: the page thumbnail with markers appearing as they are
  detected, beside a `PageStageStepper`.
- **Elapsed** and **estimated remaining**, `type.numeric`. The estimate appears
  only after **3** pages complete; before that, "estimating…". A confident wrong
  number is worse than none.
- **Completed pages**: a list, each with its own cost in `type.numeric`.
- **Stop run** (`destructive`). Its confirm dialog offers three choices, not two:
  "Finish the current page, then stop" (default) / "Stop now" / "Keep going".
  Pages already completed are always kept, and the dialog says so.

States: `idle` (hidden) / `running` / `paused` (not in v1) / `finished` /
`stopped-by-user` / `stopped-by-budget` / `failed`.

### `PageStageStepper`

Four labelled steps for the current page: **Detecting → Reading → Translating →
Done**. A single spinner over a 20-second-per-page operation tells the user
nothing. Step states: pending (`color.text.muted`) / active (`color.accent.base`,
with the only indeterminate indicator on screen) / done
(`color.status.success` check) / failed (`color.status.danger` triangle, and the
stepper stops advancing so the failure point is visible).

### `CostReadout`

Present during the run **and** in the workspace header afterwards. The $2/chapter
budget is a hard constraint and this is the component that makes it observable.

Anatomy, left to right:
`$0.83` (`type.numeric-lead`) · `of $2.00` (`type.caption`, `color.text.muted`) ·
a 4px meter bar · `~$1.18 projected` (`type.caption`).

| State | Trigger | Appearance | Copy |
|---|---|---|---|
| **unknown** | before the first priced call | figure reads `$—`, meter empty and `color.border.default` | "Cost appears after the first page." **Never shows `$0.00`** — an unmeasured cost displayed as zero is a lie the user would act on. |
| **normal** | spend < 75% of budget | figure `color.text.primary`, meter fill `color.text.muted` | projection shown once ≥ 2 pages are priced |
| **approaching** | spend ≥ 75% **or** projection ≥ 100% | meter fill `color.status.warning`, a warning triangle glyph beside the figure | "projected $2.34 — over budget". Announced once through the live region. |
| **exceeded** | spend ≥ 100% | figure and meter fill `color.status.danger`, filled warning glyph | — |
| **aborted** | the run stopped because the budget was reached | figure frozen, meter full and `color.status.danger` | accompanied by the banner below |
| **idle / post-run** | run finished | figure `color.text.primary`, meter `color.text.muted`, caption "final" | — |

Projection is `spend_so_far / pages_priced × total_pages`, shown only once
`pages_priced ≥ 2`.

**Colour is not the only carrier**: the figure, the budget and the projection are
always present as text, and `approaching`/`exceeded` add a glyph.

**Budget-abort banner.** An `ErrorBanner`, not a modal — the user must be able to
go straight to reviewing what did complete:

> **Run stopped at page 14 of 20 — the $2.00 budget was reached.**
> Pages 1–13 are translated and can be reviewed and rendered.
> `[ Review pages 1–13 ]` `[ Change budget… ]`

The budget is a **setting** with a default of $2.00, not a constant. "Change
budget…" is only an honest action if it exists.

---

## 9. Supporting components

### `EmptyState`

Icon (`color.text.muted`), headline `type.title`, body `type.body`
`color.text.secondary`, and **an action**. An empty state that only names the
emptiness is a missed instruction: every one in this app says what to do next.
Instances: no chapter loaded; no bubbles on this page; no pages reviewed yet.

### `ErrorBanner`

Full-width, ground `color.surface.raised`, 1px and a 3px leading bar in
`color.status.danger` (or `warning`), glyph, headline `type.body-strong`, body
`type.body`, up to two actions. Dismissible only when the condition is
recoverable. Role `Alert`, announced once.

### `Toast`

Bottom-right, `elevation.e2`, auto-dismiss after 6s, never carries the only copy
of anything, never carries the only action. Variants info / success / warning /
error. Enters with opacity + 8px rise (`motion.duration.slow`); under reduced
motion it appears without the rise. Focus is never stolen.

### `BakeConfirmDialog`

Modal, `elevation.e2`. States the output folder path, the page count, the
unreviewed-line count and the list of pages containing them, and any `overflow`
or `failed` lines. Primary "Render 20 pages", secondary "Cancel". Focus is
trapped while open and returned to the invoking control on close.

### `ShortcutSheet`

Opened with `?`. A read-only two-column list of every binding in §4.7. Closes
with `Esc`. It exists because the review loop is keyboard-first and there is no
other place the bindings are discoverable.

---

## 10. High Contrast deltas

*Added 2026-09-12. Every table above describes the default (dark) theme and is
unchanged. This section is the **delta** under a Windows contrast theme, so that
a story implementing §3–§9 can read its own component's HC behaviour in one
place. Floor: `accessibility.md` **A-15**. Reasoning and the full token mapping:
[`high-contrast.md`](./high-contrast.md).*

Two facts govern everything below:

- **Colour carries nothing under HC** beyond "selected" and "disabled" — every
  surface is `Window`, every foreground `WindowText`, selection is
  `Highlight`/`HighlightedText`. §1's four button variants become two
  appearances; the three status hues become one. **A-10** is what makes that
  survivable, and it is not re-openable here.
- **The HC boundary is the edge of the page pixmap.** Chrome follows the contrast
  theme. The artwork and everything painted on it does not.

### 10.1 `Button` (§1)

| Variant | HC |
|---|---|
| `primary` | `Highlight` ground, `HighlightedText` label, no border |
| `secondary` | `Window` ground, `WindowText` label, 1px `WindowText` border |
| `ghost` | **gains a 1px `WindowText` border.** Without a ground and without a border it is indistinguishable from a label, and A-02 requires every interactive control to have a visible boundary |
| `destructive` | `Window` ground, `WindowText` label, **2px** `WindowText` border |

`destructive` losing its red is a real loss and the 2px border is the whole
mitigation, alongside the label wording and the confirm dialogs that already
guard both destructive actions in the app (`Stop run`, `BakeConfirmDialog`).
Recorded as a cost rather than hidden.

- **hover** — a 1px `WindowText` outline, **never** a ground change (a ground
  change would make hover identical to selection).
- **pressed** — ground `Highlight`, label `HighlightedText`.
- **disabled** — label `DisabledText`, border `DisabledText`. Still focusable,
  still carries the tooltip saying why.
- **loading** — unchanged; the indicator is `WindowText`.

### 10.2 `WorkspaceShell`, `PageStrip`, panels (§3)

Every region's ground is `Window`, so the surface ramp no longer separates them.
**Borders do all of it:** 1px `WindowText` between page strip, canvas and
translation column, and around the header and footer; the splitter handle carries
a visible `WindowText` line. `elevation.e1` is `Window` + 1px `WindowText`; `e2`
is `Window` + 2px `WindowText` and **the drop shadow is not painted** — a blurred
translucent shadow on a flat maximum-contrast ground is invisible or noise.

Layout, the 1440px breakpoint, the minimum window size and every spacing value
are unchanged. High Contrast is not a layout change.

`PageStrip` rows: current → `Highlight` ground, `HighlightedText` text, leading
bar `HighlightedText`; hover → 1px `WindowText` outline; the seven page-status
glyphs all become `WindowText` and are distinguished by silhouette (A-15.7).

### 10.3 `PageCanvas` and `BubbleMarker` (§3, §4)

**The markers do not change.** Every `overlay.*` colour is exempt and keeps its
authored value, because a contrast theme cannot reach the user's scan and the
two-stroke halo-plus-core pair of **A-06** already clears 3:1 against both
extremes of the artwork — which no single HC colour can (`tokens.md` §5).
Substituting `WindowText` into a marker would replace the guarantee with exactly
the single flat colour §5 exists to rule out.

Three deltas, and only three:

1. **`overlay.dim.opacity` is 1.0** (A-15.6). Nothing is dimmed on purpose under
   a setting whose entire point is that nothing is low contrast on purpose. The
   selected marker is still unmistakable: 3px core against 2px, an
   `overlay.fill.selected` wash where idle has none, and a **filled** ordinal
   badge against an outline one — and per §4.2 the ordinal is the primary carrier
   of the link, with colour secondary. That is what actually carries the bubble ↔
   line link under a contrast theme.
2. **`color.canvas.frame` becomes `WindowText` at 2px.** It is the line that tells
   an HC user where the application stops and the artwork begins.
3. **The viewport focus ring** becomes `WindowText` at `focus.width`, keeping its
   halo (which becomes `Window`, so ring and halo are the guaranteed pair and one
   of the two always shows).

`color.canvas.surround` **stays `#5F5F5F`** — it is a viewing condition, not
chrome, and adopting a pure-black or pure-white `Window` would put an extreme of
the greyscale directly against a scan made of the same extremes, destroying the
page boundary an HC user needs most (high-contrast.md §6). Its L\*≈40, chosen for
unrelated reasons, is what licenses (2) and (3): white clears 6.39:1 against it
and black 3.29:1. A user-edited theme could still break that, so A-15.9 makes it
a runtime check with a fallback to the authored values, for the canvas boundary
only.

`color.canvas.page-edge` is likewise exempt. It is single-stroked and therefore
has no contrast against a scan with a black page border — a **pre-existing** A-06
gap, not one HC introduced, and raised separately.

`OffscreenIndicator`: unchanged, it is painted over artwork.

### 10.4 `TranslationRow` and status glyphs (§5, §7)

| State | HC |
|---|---|
| default (`proposed`) | ground `Window`, text `WindowText` |
| hover | **1px `WindowText` outline**, no ground change |
| focus-visible | 2px ring in the foreground of the ground it sits on — `WindowText` on `Window`, **`HighlightedText` on `Highlight`** (A-15.8) |
| selected | ground `Highlight`, text `HighlightedText`, 3px leading bar `HighlightedText` |
| `failed` | the 1px danger border becomes 2px `WindowText`; the error caption is `WindowText` |
| disabled / locked | text and glyph `DisabledText` |

Every gutter glyph becomes `WindowText`, so **the silhouette is the only carrier
of status**. Five of the six are already distinct in one colour. The sixth is
not:

> **`edited` (filled pencil) and `reverted` (outlined pencil with a return arrow)
> differ by fill and by a small appended arrow.** At 16px in one colour that is
> not a reliable distinction, and §7 makes it load-bearing — `reverted` means "I
> looked at this and put it back", and S1 depends on the two not being confused.
>
> **Under HC, `reverted` is a return arrow alone, no pencil.** Whether the dark
> theme should adopt the same single glyph set is an open decision for the
> product owner; it would amend §7 and MT-017.

A row that is both `edited` and `overflow` still shows both glyphs in that order,
and the accessible name still mentions both. Accessible names are unchanged in
every mode — they were never carrying colour.

### 10.5 `LineEditor` (§6)

Read-only is a label on `Window`. Editing: ground `Window`, **2px `WindowText`
border** (the `surface.sunken` well is gone with the ramp, so the border is the
whole affordance), caret `WindowText`. Dirty adds the gutter dot in `WindowText`.
The commit-failed state's danger border becomes 2px `WindowText` and **the text
is still kept in the field** — that rule is about data, not colour, and does not
change.

### 10.6 `CostReadout` (§8) — five states, none of them told apart by colour

The sharpest collapse in the app after the canvas: `approaching` leans on
`color.status.warning` and `exceeded` on `color.status.danger`, and under HC both
are `WindowText`. The budget is a hard product constraint, so the five states
must stay distinguishable. **Under HC the meter is decorative and the glyph and
the text carry the state:**

| State | Figure / caption | Glyph | Meter |
|---|---|---|---|
| `unknown` | `$—` + "Cost appears after the first page." | none | empty, 1px `WindowText` border |
| `normal` | `$0.83` + "of $2.00" | none | fill = spend / budget |
| `approaching` | figure + "projected $2.34 — over budget" | **outline** triangle | fill = spend / budget, 2px border |
| `exceeded` | figure + "over budget" | **filled** triangle | fill = full |
| `aborted` | figure frozen + "Run stopped — budget reached" | filled triangle | fill = full, 2px border |

The `(figure text, glyph, meter fill)` triple is unique across all five, which is
the assertable form (A-15.7). `unknown` still shows `$—` and **never `$0.00`** —
that rule was never about colour.

### 10.7 `ErrorBanner`, `Toast`, dialogs (§9)

`ErrorBanner`: ground `Window`, **2px `WindowText` border all round** plus the
3px `WindowText` leading bar, glyph and text `WindowText`. The danger and warning
variants are no longer distinguishable by colour, so the **glyph must differ** —
filled triangle for error, outline triangle for warning — and the headline
wording already does. Role `Alert`, announced once: unchanged.

`Toast`: `Window` + 2px `WindowText`, no shadow. The four variants are
distinguished by glyph and wording. It still never carries the only copy of
anything and never carries the only action, which is what makes the collapse
safe.

`BakeConfirmDialog`, `ShortcutSheet`: `Window` + 2px `WindowText`. Focus trap and
focus return unchanged.

### 10.8 A live change loses nothing

Switching a contrast theme on or off while the app runs re-composes and re-applies
the stylesheet and repaints the canvas, preserving the selected region, the
column's scroll position, the canvas zoom and pan, and **uncommitted text in an
open `LineEditor`** (A-15.10). Announced once through the live region; no notice,
banner or toast.

### 10.9 `ChapterSummary` and `CostEstimate` (§2)

*Added 2026-10-01 (MT-058).* Both bordered boxes in the summary - the order
notice and the cost estimate - lose their colour: `color.status.warning` and
`color.border.subtle` both resolve to `WindowText`, so under HC the estimate's
**normal** and **over-budget** borders are identical, and the order notice's
border looks like any other. Nothing is lost, because neither box was ever told
apart by colour: the over-budget state is the sentence `The estimate is over
budget.` on line 2, and the notice is its lead sentence (A-10). Text is
`WindowText` on `Window`; the copy, the lines and the layout are unchanged. No
glyph is added under HC, since there is none to distinguish.
