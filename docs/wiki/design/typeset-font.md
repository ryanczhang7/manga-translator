# O5 — the typeset lettering font

*Resolves open question O5 from the product brief. Owner: Lead Designer.*

**Decision: Shantell Sans, version 1.011, SIL Open Font License 1.1.**

---

## 1. The filter

The brief and the packaging constraint give three hard requirements, in order of
how many candidates they kill:

1. **Redistributable inside a shipped Windows installer.** The app is a frozen
   Windows build; the font file ships inside it. This is a licence question with
   a legal answer, not a taste question.
2. **A real bold and a real italic.** Not a synthesised oblique applied at render
   time. Manga lettering uses italic for internal thought and off-panel dialogue
   and bold for shouting, on nearly every page; a slanted comic face reads as a
   mistake in a bubble.
3. **The punctuation English manga lettering actually uses** — ellipsis, em dash,
   en dash, curly quotes, and the ability to set `?!`.

---

## 2. The choice

| | |
|---|---|
| Family | **Shantell Sans** |
| Version | 1.011 (released 2024-06-01) |
| Licence | **SIL Open Font License 1.1** |
| Designers | Stephen Nixon / Arrow Type; concept and creative direction Shantell Martin; Cyrillic by Anya Danilova |
| Obtained from | `https://github.com/arrowtype/shantell-sans` — the release archive, not a font aggregator |
| Styles used | the static instances: Regular, Italic, Bold, Bold Italic |

**Why it clears the filter.**

- **Licence.** OFL 1.1 is the licence the upstream repository itself declares. OFL
  1.1 expressly permits bundling and redistribution of the font, including inside
  and with software, provided the font files are not sold on their own and the
  copyright and licence travel with them. Both obligations are mechanical and are
  written up in §5 below.
- **Real italic.** Shantell Sans carries an **Italic axis with drawn letterforms**
  — the upstream documentation describes glyphs *redrawn* for the italic rather
  than slanted. This is the requirement that eliminated the runner-up.
- **Real bold.** The Weight axis runs 300–800, so there is genuine weight to reach
  for, and an ExtraBold available later for shouting without faking it.
- **Coverage.** Upstream claims 380+ characters across 380+ Latin and Cyrillic
  languages, with extensive diacritics. That is comfortably more than English
  lettering needs.
- **Fit.** It is a monolinear marker hand, which is what hand lettering is. At
  Bounce = 0 and Informality = 0 it sets as a calm, even comic body face.

**Ship the static instances, not the variable font.** The variable font needs
FreeType variation support in whatever rasteriser the render pipeline uses, and
that is an avoidable dependency on a build flag. The static instances are in the
same release. The exact filenames in the release archive must be recorded in the
architecture document by the story that vendors the font — the names in
`tokens.toml` (`ShantellSans-Regular` etc.) are the *style requirement*, and the
intake test in §6 is what pins the real files.

---

## 3. What it costs us, stated plainly

Shantell Sans is **not** Wild Words, and the baked pages will not be
indistinguishable from a Comicraft-lettered release. It is a marker hand rather
than the slightly irregular pen hand of the scanlation default; it is a touch
more contemporary and a touch less "comic book". Someone who letters manga will
notice.

That is accepted, because the alternative is an installer that redistributes a
font it has no right to. The brief's bar is "looks like a normal English
release", and a clean, correctly-weighted marker hand set with real italics and
real bolds clears that bar; a pirated Wild Words would clear it more precisely
and would be indefensible.

**The escape hatch, proposed to the Lead PO as a scope question.** Because
`typeset.font.family` is a token, a single **app-level** setting — "lettering
font file" — would let a user who *owns* a Wild Words licence point the app at
their own file and get exactly the house look. This does not violate the brief's
non-goal, which forbids *per-bubble* font pickers, not one application setting.
It is not designed here; it is named as a v1-or-v1.1 decision for the Lead PO.

---

## 4. Alternatives, and why they lost

| Candidate | Licence position | Verdict |
|---|---|---|
| **Wild Words / CC Wild Words** (Comicraft) | Commercial, per-seat, sold through the foundry and MyFonts. Not redistributable. | **Out on licence.** This is the de facto scanlation standard and the reason "standard scanlation style" is ambiguous at all. Note for anyone who searches: several aggregator sites claim a "CC Wild Words Roman" exists under OFL. That claim is not credible — "CC" is Comicraft's own family prefix — and it must not be relied on. |
| **Anime Ace, Manga Master, Digital Strip** (Blambot) | Blambot's own terms: the Pro fonts may never be redistributed, and *embedding* a font in third-party software requires a paid perpetual licence. The free tier is for independent comic creation, not for bundling in a product. | **Out on licence**, despite Anime Ace being what most open-source manga tools ship. Those tools are not a licence opinion. |
| **Komika family** (Apostrophic Labs) | Freeware of uncertain provenance; the foundry is long defunct and the embedded licence text is ambiguous. | **Out.** Ambiguity is disqualifying when the file goes into an installer. |
| **SF Cartoonist Hand** (ShyFoundry) | Freeware; redistribution terms not clearly stated upstream. | **Out**, same reason. |
| **Comic Neue** 2.x (Craig Rozynski) — OFL 1.1 | Licence is fine: OFL 1.1, confirmed upstream. | **Out on requirement 2.** Its "italics" are **obliques** — the family and its Angular sibling ship light/regular/bold with slanted equivalents at ~12°, not drawn italics. It also inherits Comic Sans's letter shapes, which is a liability rather than a neutral in comic lettering. This was the runner-up and is the fallback if Shantell Sans is rejected on looks. |
| **Comic Relief** — OFL | Licence fine. | **Out on requirement 2**: Regular and Bold only, no italic at all. |
| Single-weight OFL hands (Patrick Hand, Caveat, Gloria Hallelujah, Permanent Marker, Architects Daughter) | Licence fine. | **Out on requirement 2**: no bold, no italic, or neither. |

---

## 5. Licence obligations this project must actually perform

OFL 1.1 is permissive but it is not "do nothing". Three mechanical duties, all of
which a story can implement and a test can check:

1. **`OFL.txt` ships alongside the font files** inside the installer, in the same
   directory as the `.ttf`s, unmodified.
2. **The copyright and licence notice is reproduced** in the app's About/Licences
   screen along with the designer credit.
3. **The font files are never sold separately and are never renamed** in a way
   that implies a different origin. If the project ever subsets or modifies the
   font, the Reserved Font Name rule applies and the modified file must not keep
   the name "Shantell Sans" — so **v1 does not subset the font.**

---

## 6. Confidence, and the check that replaces guessing

**Licence confidence: high.** OFL 1.1 is declared by the upstream project
repository itself, which is the primary source; it is not inferred from an
aggregator, and every aggregator claim encountered while researching this was
either restating that or — in the Wild Words case — visibly wrong.

**Coverage confidence: not verified, and deliberately not asserted here.** I have
not inspected the font's `cmap`. Rather than guess, the requirement becomes a
test the font-vendoring story must carry:

> Load each shipped face and assert its character map covers, at minimum:
> `U+0020`–`U+007E` (ASCII), `U+2018 U+2019 U+201C U+201D` (curly quotes),
> `U+2013 U+2014` (en and em dash), `U+2026` (ellipsis), `U+00A0`,
> `U+00E9 U+00FC U+00F1` (representative diacritics for transliterated names).
> Assert the four faces report distinct `OS/2` style bits — that Bold is bold and
> Italic is italic in the file, not at render time.

`U+203D` (interrobang) is **not** on that list. Scanlation convention sets `?!`
as two glyphs, which is what the typesetter will emit, and demanding a glyph the
convention does not use would fail a font for no reason. If the interrobang is
present, nothing uses it.

---

## 7. Lettering rules that come with the font

These are typesetting decisions, and they belong with the font choice.

- **Sentence case, not all caps.** American comics letter in caps; manga
  scanlation does not, and Wild Words-style releases are mixed case. Matching the
  convention the user already produces matters more than matching comics
  generally.
- **Centred horizontally and vertically** in the bubble's inscribed area, with
  `typeset.padding-ratio` (0.12 of the bubble's short axis) of clearance.
- **Line breaking**: break on spaces only; never hyphenate; never break a word;
  prefer a break after terminal punctuation; among candidate break sets, choose
  the one minimising the difference between the longest and shortest line, so the
  block sets as the rough diamond conventional lettering uses. There is **no
  manual line-break control** — brief §5 forbids it.
- **Fit**: shrink from `typeset.size-max` toward `typeset.size-min` in
  `typeset.size-step` page-pixel steps until the block fits. If it does not fit at
  `size-min`, set it at `size-min` anyway and **flag the bubble as `overflow` on
  the review screen** so the human sees the problem before baking rather than
  after. Silently shrinking past legibility is the failure mode this rule exists
  to prevent.
- **Emphasis contract.** The stored English line is plain text that may carry
  `*italic*` and `**bold**` markers. The line editor shows those markers
  literally — the editor stays a plain single-line field, which keeps it
  keyboard-simple and diffable — and the typesetter resolves them to the real
  Italic and Bold faces. A literal asterisk is escaped `\*`. Nested or unbalanced
  markers are rendered literally rather than guessed at.
- **Line height** `typeset.line-height` = 1.08. Comic lettering sets tight.
