---
id: EPIC-11
title: Running the chapter again - a stopped or invalidated run resumes from the workspace
status: todo
stories: [MT-124, MT-125, MT-127, MT-128, MT-129]
---

*Added 2026-10-30 by lead-po on Claude Fable 5.1, from two things the user hit.
First, a run that failed part-way (the API account ran out of credits) left the
chapter stuck: the window opened straight into the review workspace and there
was no way to run the rest. Second, EPIC-10's "left as drawn" decision (MT-119,
re-planned the same day) leaves one case waiting on a re-run: restoring a
region that was excluded when its page was cleaned invalidates that page's
cleaned image, and nothing in the app can re-clean it. Both are the same gap:
the pipeline resumes - `pipeline.runner` skips every stage whose `is_done` is
true (MT-006, MT-036), and `mangatl-run` on a folder with a project reopens and
resumes (`cli.py:156-160`) - but the window reaches `MainWindow._start` only
from a folder with **no** project. `create_project` refuses an existing one.*

## Goal

From the review workspace, the user runs the chapter again. Every stage picks
up where it is not done - pages a failed run never reached, a page whose
cleaned image was invalidated, a page the model returned nothing for - and
nothing already paid for is redone. Before it starts, the user is told what
will run and what it is expected to cost against the budget, in the figures
the guard itself uses; during it, the same progress panel, cost readout and
abort banners a first run shows; after it, the workspace shows the chapter as
it now is.

## Why now

The user has been stuck once already, with a real chapter and real spend
behind it. And EPIC-10 is about to ship a rule (MT-119 AC-5c) whose honest
outcome - "this page needs re-cleaning" - has no action the user can take.
The pipeline half exists; this epic is the window half, which `architecture.md`
§6 promised ("resume") and no story built.

## Decisions (the Lead PO's, 2026-10-30, open to the user)

- **PO-1 - Resume is the runner's, not the window's.** No new resume logic:
  the window builds the real stage list and hands it to `run_chapter` on the
  existing project, exactly as `mangatl-run` does. What a re-run redoes is
  whatever each stage's `is_done` says, and MT-124 states that *before* the
  run from the same `is_done` calls, so the preview and the run cannot
  disagree.
- **PO-2 - The estimate is the guard's figure.** `Budget.project(priced calls,
  pages to translate).remaining_chapter`, with the chapter's own priced calls
  as the samples when it has any, else the selected model's `page_estimate` -
  the number `TranslateStage` projects with (MT-044, MT-100). The guard still
  decides per call during the run; the dialog only says whether the whole
  looks like it fits, with the same inclusive comparison `CostEstimate` uses.
- **PO-3 - The re-run happens inside the workspace window.** The progress
  panel replaces the workspace body for the duration and the body comes back,
  reloaded, when the run ends. One window, one open project, no hand-over to
  the intake window, and no row can be edited while the worker writes.
- **PO-4 - "Retry line" is not this epic's.** The disconnected button on a
  `failed` row (MT-017 PO-4: `retryRequested`, nothing connected) asks for a
  per-line re-translation, and the pipeline has only a per-page call (D5).
  Wiring it means either re-translating the page - one call, which also
  replaces every untouched proposal on that page - or a line-only text call
  outside D5. That is a product decision (**Q-2**) and a story of its own,
  cut once it is answered. A chapter re-run already recovers a `failed` page
  whose translate stage is not done.

## Open questions for the user

- **Q-1** - Label and place of the action. The PO's draft (MT-125 `## Design
  notes`): **"Run again"**, a `secondary` button in the workspace header
  before the cost readout; the Lead Designer confirms before RED. The
  alternatives are the footer beside "Render pages", or a menu.
- **Q-2** - Retry line: re-translate the whole page (replaces untouched
  proposals on that page, one priced call) or a single-line text call outside
  D5? **Recommended default: leave the button as it is for now and cut the
  story after the answer**; a chapter re-run covers the page-level case.
- **Q-3** - Should a re-run first re-read the source folder
  (`refresh_from_source`), so a replaced scan is re-detected? `mangatl-run`
  does not. **Recommended default: not in MT-125**; one line to add later, and
  it changes which pages the preview counts.
- **Q-4** - A page the model answered for **partly** (some regions got no
  proposal) is "done" to `TranslateStage.is_done` (any proposal, MT-011 PO-10)
  and is not re-translated by a re-run. **Recommended default: accepted and
  recorded**; a per-line path is Q-2's.

## Done when

With the user's sample chapter open in the workspace after a run that stopped
part-way, "Run again" states how many pages are still to run and what the rest
is expected to cost against the budget, the user confirms, the pages already
done are skipped, the rest run under the same guard with the same panel, and
the workspace comes back showing the chapter translated - and the same action,
after restoring a region MT-119 says needs re-cleaning, re-cleans that one page
and nothing else.

## Stories

- **MT-124** - the preview: `pipeline.resume.rerun_preview(project, stages,
  page_estimate)` says, from each stage's own `is_done`, how many pages would
  run, how many each stage would redo, how many would be translated, and the
  guard's estimate against the spent total and the ceiling. Writes nothing.
  Headless; no UI.
- **MT-125** - the workspace: "Run again" (Lead Designer pass before RED),
  the confirm dialog built from MT-124's preview, the run on a worker with the
  progress panel in the workspace body, the body back and reloaded when it
  ends, and cancel-on-close. Depends on MT-124.
- **MT-128** - (filed by the EPIC-11 mutation audit, 2026-11-01) tests only:
  Run again and Render pages each refuse to start while the other is in
  flight - four guards in `workspace.py` no test pins, one reachable by a
  click during a bake. `docs/wiki/audits/EPIC-11-2026-11-01.md`.
- **MT-129** - (same audit) tests only: the run hand-over parks focus before
  hiding the body, a one-page chapter is announced singular, and a second
  Run again leaves one dialog. Lower priority than MT-128.

## Deliberately not in this epic

Retry line (PO-4, Q-2). Re-running **one page** on demand; the unit is the
chapter and resume decides the pages. A "Stop run" control on the panel
(`components.md` §8 designs one; today a run stops only when the window
closes) - its own story if wanted. Re-detecting pages whose scan changed
(Q-3). Changing any `is_done` rule, the budget guard, or the ledger. Batch
submission and collection (EPIC-09 MT-111..MT-113 own the Gemini batch path;
a re-run here is the synchronous per-page run). The command line, which
already resumes.
