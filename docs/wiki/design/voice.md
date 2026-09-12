# Voice

**Workmanlike and quiet.** One person uses this for hours at a stretch. The app
should read like a good tool's status bar, not like a product with opinions about
their day.

---

## Rules

- **Second person, present tense, active voice.** "Pages are processed in
  filename order." not "The application will process the pages."
- **No exclamation marks.** Anywhere. Including success messages.
- **No first person.** The app has no "I" and does not apologise. Not "Oops! I
  couldn't read that folder" — "Windows would not let this app read *folder*."
- **No cheerfulness at completion.** "Rendered 20 pages to *folder*." is the whole
  of it. "All done! 🎉" is a cost imposed on someone doing this for the twentieth
  time today.
- **Sentence case** for every label, heading, button and menu item. Never Title
  Case.
- **No terminal full stop on a button or a single-clause label.** Full stops in
  body copy.
- **Never name an internal concept the user did not choose.** No "inference", no
  "model", no "pipeline", no "region" in the interface — the user's words are
  *page*, *bubble*, *line*, *chapter*, *run*, *render*.

## Numbers

- Money always carries the symbol and two decimals: `$0.83`, never `0.83` or
  `83¢`. An estimate carries a range and the word *estimated*.
- **Never show `$0.00` for an unmeasured cost.** Unmeasured is `$—` with an
  explanation. A zero the user might act on is worse than an absence.
- Counts are "12 of 18", not "12/18", in prose; the numeric compact form
  ("Page 7 / 20") is allowed in the header where space is tight and it is set in
  `type.numeric`.
- Durations: "2 min 40 s elapsed". Estimates get a tilde: "~4 min remaining".
  No estimate is shown before three pages have completed.

## Errors

Every error message answers three questions in this order:

1. **What happened**, in the user's words.
2. **What survived** — this is the one most tools omit and the one this user needs
   most, because a run that half-finished is still worth an evening.
3. **What to do**, as an action they can take right now.

> **Run stopped at page 14 of 20 — the $2.00 budget was reached.**
> Pages 1–13 are translated and can be reviewed and rendered.
> `[ Review pages 1–13 ]` `[ Change budget… ]`

Never:

- a raw exception or a stack trace in the message (the reason string may quote an
  OS error verbatim; a traceback goes to the log)
- "An error occurred" — if the reason is genuinely unknown, say "This page could
  not be read, and the reason was not reported." and offer the log
- "Please try again" without saying what would be different

## Empty states

Every empty state names the emptiness **and** the next action. "No speech bubbles
found on this page." is half a message; "…The page will be copied to the output
folder unchanged." is the other half.

## Terms — use exactly these

| Use | Not |
|---|---|
| chapter | project, job, batch |
| page | image, frame, scan (in UI copy) |
| bubble | region, box, balloon, text area |
| line | translation, string, caption, text |
| proposal / the machine's proposal | suggestion, AI output, prediction |
| reviewed | checked, approved, confirmed, validated |
| run | process, translate job, execution |
| render | bake, export, generate, typeset (as a verb in UI copy) |
| budget | cost limit, cap, quota |

*Bake* is used in internal documents and in this repository; the interface says
**render**, because that is the word the user's existing tools use.
