---
id: EPIC-07
title: Knowing whether it worked, and getting it onto the machine
status: todo
stories: [MT-029, MT-022, MT-023, MT-024]
---

## Goal

Two things the product is not finished without. First, a repeatable measurement
of the brief's success criteria — S1 (acceptance rate), S2 (detection and
cleaning recall) and S5 (cost) — computed by a harness rather than argued about.
Second, an installer: one double-click, no Python environment, no model weights
to place, no GPU setup.

## Why now

Last, because the harness measures something that must already exist and the
installer packages something that must already work. But **not optional**: the
brief's section 7 makes every success signal a measured one, and section 6 makes
"installation must not require the user to manage Python environments, model
weights or GPU setup by hand" a hard constraint rather than a nicety.

## Done when

`bench` can be pointed at a benchmark chapter plus its ground truth and prints
**S1b** (the headline, against the ground-truth region count), S1a beside it as
a diagnostic, the recall and spurious counts, S2 and S5; the metric's own
negative controls pass; and a build of the app installs and runs on a clean
Windows 11 machine with nothing preinstalled.

## The benchmark chapter is a user input, and stays one

Open question O1 in the brief is the user's and is still open. These stories
build the **harness** and ship fixtures small enough to test it; none chooses the
held-out chapter, and none may quietly substitute a chapter used while building.
The harness must refuse to report against a chapter it can tell was used in
development — that is an acceptance criterion, not a convention.

**So is the annotation.** S1b's denominator is every text region that genuinely
exists on the benchmark chapter, *including the ones the detector misses* — and
if the machine could enumerate those it would not miss them. A human marks them
once, 150–250 regions across 20 pages. MT-029 gives that annotation a format, a
seeding tool and a validator; **the chapter and the labour are the user's**, and
nothing in this epic supplies either.

## Stories

- **MT-029** — the ground-truth format, the seeding command and the validator.
  First, because MT-022 and MT-023 both consume what it defines and neither can
  be demonstrated without it. It also owns `bench/matching.py`, the single
  definition of how a proposal is matched to a truth region.
- **MT-022** — acceptance rate: S1b as the headline, S1a beside it, with the five
  negative controls from `docs/wiki/stack.md` §5/O2 and the `S1b = S1a × recall`
  identity that makes the gap between them a diagnosis rather than a slogan.
- **MT-023** — detection and cleaning recall (S2): every text-bearing region
  found, no Japanese pixels surviving a cleaned region.
- **MT-024** — the Windows installer: frozen build, bundled weights with hash
  verification, and a test over the built tree proving the harness directories
  are absent from it.

## Deliberately not in this epic

S3 (time saved) and S4 (it reads naturally) are human judgements the brief marks
as such — timed once, honestly, and read once, by the user. No story automates
them, and no gate pretends to.
