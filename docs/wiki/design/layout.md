# Layout

A single resizable desktop window. No responsive grid, no mobile breakpoint —
"breakpoint" here means a window width at which the workspace reallocates space.

Layout comes from **Qt layout classes**, never from QSS: QSS has no flexbox, no
grid and no `calc()`. Every rule below is expressed as a `QSplitter` stretch
factor, a `QSizePolicy`, or a fixed `minimumWidth`.

---

## Window

| | |
|---|---|
| Minimum size | **1100 × 720** — enforced with `setMinimumSize`, not suggested |
| Default on first run | 1600 × 1000, or the work-area size if smaller |
| Remembered | size, position, maximised state, and the dragged column width — built by MT-088 (PO decisions 2026-10-22, below). The strip's user collapse is not built, so nothing remembers it yet |

**How remembering works (MT-088).** The review workspace alone remembers;
the intake window does not. The state is one JSON file,
`%APPDATA%\mangatl\workspace.json` (beside `settings.json`, so the frozen
build and a dev run agree, MT-024), written when the workspace closes and read
when `mangatl.app.open_folder` builds one. A `Workspace` built any other way
remembers nothing. What is remembered: the normal (un-maximised) size and
position, whether it was maximised, and the column width **only if the user
dragged it** (MT-048's flag) — an undragged column always takes the breakpoint
default. On reading: size is clamped to at least the minimum and at most the
work area, the top-left is moved inside the work area, the column to 280–560; a
missing, unreadable or wrong-version file is the first run, which opens at
1600 × 1000 or the work-area size if smaller, and never below the minimum. A
file that cannot be written never stops the window closing.

1100px is the narrowest width at which the page canvas still shows a full manga
page at a readable zoom beside a usable translation column. Below it the product
does not work, so it is not offered.

---

## Review workspace

Left to right:

| Region | Width | Policy |
|---|---|---|
| `PageStrip` | 96px fixed (72px thumbnail + `space.3` either side) at ≥ 1440; a 28px rail below (see the breakpoint) | fixed; collapsible to 0 by the user, remembered |
| `PageCanvas` | everything remaining | stretch 1; `minimumWidth` 520 |
| `TranslationColumn` | default per the breakpoint table (300 / 380), user-resizable 280–560 | fixed in the splitter, remembered |

Header 48px, footer 44px, both full width. The column's default is set by the
breakpoint and nothing else; the 280–560 clamp is the user's range and both
defaults lie inside it. (MT-015 shipped 340 as a single default with no
breakpoint; MT-048 replaces that, so 340 appears nowhere after it.)

**The canvas always wins.** Both side regions are fixed-width in the splitter and
the canvas carries the entire stretch factor, so enlarging the window enlarges the
art and nothing else. That is the brief's "the art is the largest thing on screen
at all times", expressed as a stretch factor.

### The one breakpoint — 1440px

> **Built by MT-048 — the reallocation only.** MT-015 shipped a single layout
> (strip 96, column 340) with no breakpoint, by the user's decision recorded as
> MT-015 PO-1. MT-048 builds the breakpoint: the two column defaults, the
> 28 ↔ 96 strip, and the chapter name in the header. It does **not** build what
> the strip shows *inside* those widths — neither page-status glyphs nor
> thumbnails exist yet (the strip is a list of filenames). Three follow-up
> stories, filed by PO decision 2026-10-14, add page-status glyphs on the strip
> (components.md §`PageStrip`'s seven-status table), thumbnails on the 96px
> strip, and remembered splitter positions. Until they land, the rail shows the
> page's 1-based index number only and the 96px strip keeps showing filenames.

| | < 1440 | ≥ 1440 |
|---|---|---|
| `TranslationColumn` default width | 300 | 380 |
| `PageStrip` | a 28px rail: the page's index number (`type.numeric`, `color.text.secondary`; `color.text.primary` on the current row), plus status glyphs once they exist — no thumbnails | full 96px: thumbnails once they exist, filenames until then |
| Header | page counter, reviewed counter, cost readout, zoom | the same plus the chapter name |

Nothing is *removed* at the narrow width and nothing becomes unreachable — the
strip's rail still selects pages, by click and by keyboard, and still carries
every status glyph that the full strip does, which is what A-10 requires of it.
Each row in the rail keeps the full strip's accessible name, so a screen reader
hears the same thing at either width.

#### How the breakpoint is judged

- **On the window width**, measured at the top-level window, not on any inner
  widget. 1440 is the first "wide" width: `width >= 1440` is wide, `width < 1440`
  is narrow. Judged on every resize of the window and once on first show.
- **A resize that stays on one side of 1440 reallocates nothing.** Both side
  regions keep their widths and the canvas takes the entire delta — the rule
  under "The canvas always wins" applies unchanged within each regime.
- **Crossing 1440 moves the strip 28 ↔ 96 and the column to the new default**,
  in both directions, 1439 → 1440 and 1440 → 1439 alike.
- **A dragged column survives the crossing.** If the user has dragged the
  splitter handle since the chapter was opened, the column keeps the dragged
  width (still clamped 280–560) and only the strip changes. The default is a
  default, not a correction: a width the user chose on purpose is never
  overwritten by a resize they made for another reason. Nothing resets the
  "dragged" state short of opening another chapter (remembering it across
  sessions is the follow-up story above).
- **The minimum stays 1100 × 720.** The narrow layout is therefore the one at
  minimum size. At 1100 the default fits with room (1100 − 28 − 300 leaves the
  canvas 772), and the canvas's `minimumWidth` 520 outranks the column's 560
  clamp when the two meet: a drag at 1100 stops the column at 552, not 560.
  That is the splitter's own arithmetic, unchanged from MT-015 (where the same
  limit was 484); no new rule is needed, only that the canvas minimum is never
  the thing that yields.

#### The chapter name in the header

Leading, left-aligned: the first thing in the header row, before the stretch
that pushes the `CostReadout` (and later the counters and `ZoomControl`) to the
right. `type.body-strong`, `color.text.primary`, one line, vertically centred in
the 48px header; `space.4` from the header's left edge like the readout from its
right. It is a `QLabel` whose text may shrink: if the header has no room, the
text elides with `Qt.ElideRight`, and the readout's size is never squeezed to
make room for it.

- **Text.** The product has no chapter title; the chapter *is* its source folder
  (`Chapter.source_dir`, the only naming field on `domain.page.Chapter`;
  `store.project.Project` adds none). The header shows
  `ui.intake.display_name(chapter.source_dir)` — the folder's base name, the
  path itself for a drive root, cut in the middle past 40 characters. One rule
  with the intake heading the user has just read it under (MT-057), so the
  same chapter is never called two things on consecutive screens. Elision on
  top of that cut is the fallback, not the norm: the cut name fits a 1440px
  header in every case the product supports.
- **Below 1440 it is hidden, not removed**: `setVisible(False)`, the widget
  still in the layout tree with its text set, so crossing back to wide shows the
  same name with no reload, and its accessible name is not reachable while
  hidden. Nothing else in the header moves when it hides; the readout stays at
  the right end.
- **Accessible name**: "Chapter *name*", so the label is not read as a bare
  word with no role.

### What never reflows

- The three regions keep their order and their roles at every width.
- The translation column never becomes an overlay, a drawer or a tab. It is the
  other half of the most important interaction in the product; hiding it behind a
  toggle would make the link intermittent.
- The canvas is never split or tabbed.

---

## Intake and run screens

Single centred column, `max-width` 720px, centred in the window, `space.8`
padding. They are transient and have no side regions.

The run screen keeps the `CostReadout` in the header at the same position it
occupies in the workspace header, so the eye does not have to relearn it between
screens.

---

## Density

One density. `space.2` (8px) vertical padding inside a `TranslationRow`,
`space.3` (12px) horizontal; rows size to their content and wrap, with a
`minimumHeight` of 36px. No compact mode: a second density doubles the states to
check and the brief gives no reason for one.

---

## Scrolling

- `TranslationColumn` scrolls vertically only. Long lines wrap; they never scroll
  horizontally.
- `PageStrip` scrolls vertically only.
- `PageCanvas` does not scroll — it pans. Scroll wheel zooms with `Ctrl` and pans
  vertically without it; `Shift`+wheel pans horizontally.
- The window itself never scrolls.

---

## Z-order

1. artwork
2. bubble markers (order within this tier in components.md §4.8)
3. badges
4. `OffscreenIndicator`
5. chrome
6. popovers and menus (`elevation.e2`)
7. modals
8. toasts
