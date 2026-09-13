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
  comes out, and the sibling output folder is written atomically per page.

## Deliberately not in this epic

Anything that looks at what is *on* the page. No detection, no OCR, no
translation, no cleaning, no typesetting, no UI beyond whatever MT-006 needs to
prove the event stream is drivable headlessly. Archive formats (CBZ, PDF) are a
brief non-goal and never enter this epic or any other.
