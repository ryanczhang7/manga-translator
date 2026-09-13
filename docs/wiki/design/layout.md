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
| Remembered | size, position, maximised state, and the splitter positions |

1100px is the narrowest width at which the page canvas still shows a full manga
page at a readable zoom beside a usable translation column. Below it the product
does not work, so it is not offered.

---

## Review workspace

Left to right:

| Region | Width | Policy |
|---|---|---|
| `PageStrip` | 96px fixed (72px thumbnail + `space.3` either side) | fixed; collapsible to 0 by the user, remembered |
| `PageCanvas` | everything remaining | stretch 1; `minimumWidth` 520 |
| `TranslationColumn` | 340px, user-resizable 280–560 | fixed in the splitter, remembered |

Header 48px, footer 44px, both full width.

**The canvas always wins.** Both side regions are fixed-width in the splitter and
the canvas carries the entire stretch factor, so enlarging the window enlarges the
art and nothing else. That is the brief's "the art is the largest thing on screen
at all times", expressed as a stretch factor.

### The one breakpoint — 1440px

| | < 1440 | ≥ 1440 |
|---|---|---|
| `TranslationColumn` default width | 300 | 380 |
| `PageStrip` | collapsed to a 28px rail of status glyphs and index numbers, no thumbnails | full 96px with thumbnails |
| Header | page counter, reviewed counter, cost readout, zoom | the same plus the chapter name |

Nothing is *removed* at the narrow width and nothing becomes unreachable — the
strip's rail still selects pages and still carries every status glyph, which is
what A-10 requires of it.

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
