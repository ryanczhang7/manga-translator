---
id: EPIC-02
title: A chapter goes in and a chapter comes out
status: todo
stories: [MT-004, MT-005, MT-006]
---

## Goal

The walking skeleton, end to end: the user points the app at a folder of page
scans, it reads them in filename order, records the chapter as a resumable
project, walks every page emitting progress, and writes a sibling output folder
with the same filenames in the same order. No detection, no translation, no
typesetting — the pages come out unchanged. What exists at the end of this epic
is the *spine* every later stage plugs into.

## Why now

Brief section 3 steps 1, 2 and 5 are this epic, and every later story needs
somewhere to put its output. Building the spine first means detection,
translation and typesetting each arrive as one stage in a pipeline that already
runs, reports and resumes — rather than each inventing its own orchestration.

Resumability in particular cannot be retrofitted cheaply, and it is not
decoration: a 20-page run costs real money (`architecture.md` D6, D7), so a
crash on page 18 must not re-buy pages 1–17.

## Done when

The user can point the app at a folder of 20 scans and get a sibling folder of
20 identically named files, with per-page progress reported while it happens;
killing the process halfway and starting again resumes rather than restarting;
and replacing one input scan invalidates only that page.

## Stories

- **MT-004** — intake: a folder becomes an ordered page list; filename order;
  `.png`/`.jpg` only; the input folder is never written to.
- **MT-005** — the project store: create, reopen, resume, and per-page
  invalidation on content change.
- **MT-006** — the pipeline: stages run per page, a typed progress event stream
  comes out, the sibling output folder is written atomically per page, and a
  headless CLI entry point makes the three stories above something the user can
  actually run.

## Amendment, 2026-09-15 — the done-when had no entry point

Caught by the PLANNED → RED check on MT-006. The goal and the done-when above
both promise that *"the user points the app at a folder"*, but MT-004, MT-005
and MT-006 as written build only library code: `src/mangatl/app.py` opens a
`MainWindow` and takes no path, and MT-006's own `## Out of scope` defers the
wiring to **MT-015**, which is in `EPIC-05`. So this epic could not satisfy its
own done-when, and would have closed green over a skeleton that does not walk.

Put to the user before MT-006 left PLANNED, and decided by them: **MT-006 gains
a headless CLI entry point** (`mangatl-run <folder>`), recorded as that story's
**AC-10** and **PO-1**. A CLI rather than a window, because it satisfies MT-006's
AC-9 headless boundary instead of fighting it and takes nothing from MT-015's
workspace scope.

Unchanged by this: *"killing the process halfway and starting again resumes"* is
delivered by MT-006's AC-4 composed with AC-5, and MT-006's PO-6 requires a test
of the composition rather than of each half alone.

## Deliberately not in this epic

Anything that looks at what is *on* the page. No detection, no OCR, no
translation, no cleaning, no typesetting, no UI beyond whatever MT-006 needs to
prove the event stream is drivable headlessly. Archive formats (CBZ, PDF) are a
brief non-goal and never enter this epic or any other.
