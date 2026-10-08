# The benchmark ground truth

*Written 2026-10-08 by lead-po for MT-029. The format and the tools are that
story's; the chapter and the annotation are the user's (brief O1).*

The S1b headline divides accepted lines by **every text region that genuinely
exists on the benchmark chapter**, including the ones the detector misses. The
machine cannot supply that number — if it could enumerate the regions it misses,
it would not miss them — so a human marks them once, in a document the tool can
check but not write for them.

## The file

One JSON document per chapter, a sibling of the chapter folder:
`<chapter>.truth.json`. Human-editable, diffable, pinned to the exact bytes of
each scan by `sha256`. The schema is in `docs/backlog/stories/MT-029.md`
(Contract block 2). Each region carries its page, a polygon of three or more
vertices in page pixels, a `kind`, a `source` of `"seed"` or `"human"`, and a
free `note`.

## The three commands

```bash
uv run python -m mangatl.bench.seed  <chapter-folder>      # write a DRAFT from the detector's stored regions
uv run python -m mangatl.bench.truth <chapter-folder>      # validate the document against the chapter
```

Seeding refuses to overwrite an existing document. Validation prints every
error with the page and region it is about, and exits non-zero on any error.

## Read this before annotating — the seeding bias

Seeding from a detector pass biases the ground truth toward **what the detector
already finds**. A region the detector missed is simply absent from the seed,
and a person reviewing a seed is far likelier to fix a wrong polygon than to
notice a missing one — which is exactly the failure S1b exists to measure.

So the human pass has two jobs, and the second is the one that matters:

1. Correct every seed region that is wrong, and change its `source` to
   `"human"` once you have looked at it.
2. **Walk every page looking for text regions that are not in the document at
   all**, and add them (`source: "human"`).

The validator cannot check the second job. What it can do is warn when more
than `SEED_REVIEW_WARN_FRACTION` (10 %) of regions are still `"seed"` — the
signature of a rubber-stamped annotation. Treat that warning as a finding, not
a nag: a document that is mostly seed measures the detector against itself.

## `development_use`

Set it to `true` by hand if the chapter was used while building the tool. The
benchmark loader (`load_ground_truth(path)` in benchmark mode) then refuses the
document outright, so a contaminated chapter cannot produce a headline by
accident. It is per **document**: do not use it to quarantine a few pages — see
MT-029 `## Notes` on vol. 17 pp. 011–015, which were used during MT-002 and
should simply not be in the benchmark chapter.
