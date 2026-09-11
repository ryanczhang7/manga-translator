# Audit: has the harness drifted, and does it hold up

**Date:** 2026-09-10
**Scope:** the whole repository at `1675194` (after PR #7), compared with the
founding commit `97d5fbf`. Three passes: purpose drift against the founding
documents; every document cross-checked against the code it describes; and a
hands-on verification of `scripts/*.sh` and `.claude/hooks/*.sh` - the full
selftest, `doctor.sh`, `gates.sh --audit`, both CI workflows on the
unbootstrapped template, an end-to-end story lifecycle on a throwaway fixture,
every documented failure path of `gates.sh` and `phase.sh`, and an adversarial
probe of the phase guard with commands the suite did not cover.
**Left out:** running anything on macOS or bash 3.2. Those findings come from
reading the code, and the selftest now greps for the constructs concerned.

## Decided

- **The purpose is retained.** Every structural commitment from the founding
  commit holds: the same seven commands and phase progression, the same five
  agents with the same path ownership, the phase lock as the enforcement
  mechanism, `project.conf` as the single stack indirection, bash and git as
  the only dependency. Nothing was reversed. Field-report rounds were applied
  additively, and that is the drift: rules restated at three altitudes, agent
  files carrying methodology the README says lives in skills, and consuming-
  project anecdotes (terrain, WebGL, vitest) as the primary illustration of
  rules that claim to serve Python, Rust and Godot equally.
- **The correction is editorial, not architectural.** This audit renumbers the
  laws, moves the Lead PO's methodology paragraphs back to pointers at the
  skills and `/advance-story`, and makes the load-bearing example in
  `tdd-cycle` stack-neutral. It does not add a rule.
- **"The code the gates judge" stays one predicate**, `gated_stdin` in
  `lib.sh`, shared by the Stop hook, the recorded hash and CI. Harness
  markdown is not in it. (PR #7.)
- **The phase guard fails open on what it cannot read and closed on what it
  can.** A parenthesis, a comment, a clobber redirect and a literal backslash
  are all things it can read, so they are now read. Command substitution,
  `bash -c '...'`, `$var` targets, `find -delete`, `git apply` and interpreter
  heredocs remain documented fail-open; enumerating them is the approach the
  field reports argued against.
- **`spike` may commit source without tests** if `## Scaffold inventory` names
  it. The script already allowed this; the docs now say so, rather than the
  script being narrowed.
- **The structural half of H7** (a `gates.sh` check that a story's changed
  paths are exercised by a required gate) needed a gate-to-path map
  `project.conf` did not have. It was deferred from this audit's first round
  and then built in the same PR, at the user's direction: a `covers | <gate>
  | <glob>` line, the paths.conf glob dialect through the same matcher. With
  any present and a story active, every run diffs the story branch against
  `main`, keeps the source paths, fails on one read only by optional gates and
  warns on one no gate claims. Silent with no lines; `--audit` says so.

## Evidence

Each claim was reproduced before it was acted on. The reproduction is what the
new selftest cases assert.

- **A double-quoted Windows path was denied as `source`.** `mask_shell_quotes`
  dropped every backslash inside double quotes; bash drops one before only
  `$`, backtick, `"`, `\` and newline. With a story in RED,
  `echo x > "C:\Users\...\Temp\claude\n.txt"` produced `path:
  C:UsersryancAppDataLocalTempclauden.txt   category: source`. That is the
  scratchpad the harness tells agents to use. Reproduced with hand-built JSON
  on this machine (Windows 11, bash 5.3); `lib.test.sh` "a backslash inside
  double quotes is usually a backslash" and `phase-guard.test.sh` "a
  double-quoted Windows path keeps its backslashes" were red, then green.
- **Three guard holes**, all found by probing with a fixture in RED:
  `(cd src && echo x > a.ts)` allowed (candidate `a.ts)` declined as
  implausible); a two-line command whose first line ends `# it's fine`
  allowed (the apostrophe opened a quote that never closed); `echo x >|
  src/main.ts` allowed. Plus one false positive: `xargs touch < list` denied
  on `list`. All four red in `phase-guard.test.sh` "three holes found by
  probing", then green.
- **`gate_tree_hash` diverged from CI under `core.autocrlf=true`.** Adding
  into an empty index renormalises a CRLF file the real commit never
  normalised. Reproduced in `lib.test.sh` "agrees with the committed tree
  whatever autocrlf says": a CRLF file committed under `autocrlf=false`, then
  `autocrlf=true`, working-tree hash `a317d4ee…` against HEAD hash
  `e8c11333…`. Latent in this repository (`.gitattributes` pins LF and no
  tracked file is CRLF), live for a consuming project with a CRLF file
  committed first. Seeding the temporary index from HEAD makes them agree.
- **`json_escape` emitted a backslash unchanged**, so a deny reason containing
  one was not JSON. `json_escape 'a\b'` printed `a\b`. The test helper
  `json_str` had the same defect, which meant two existing guard cases about
  backslashes could not have failed. Both rewritten in awk.
- **`phase.sh set T-11 'GREEN.'` succeeded**, wrote `PHASE=GREEN.` to the
  state file, and `phase_allows`, finding no such row, fell back to "unknown
  phase, do not block". Exact comparison now; `phase.test.sh` "a
  regex-matching phase name is refused".
- **`gates.sh --gate untt` printed "All required gates passed (0 ran)"**, exit
  0. Now exit 2 with the gate named; `gates.test.sh` "--gate names a gate that
  exists".
- **`${var,,}` at five sites in `lib.sh`** is bash 4. On macOS bash 3.2 it is
  a fatal "bad substitution" inside `to_rel`, after which `check_path` sees an
  empty path and returns allow: the lock silently off. Not executed here;
  read, replaced with `tr`, and pinned by a grep in `lib.test.sh`
  "portability". The same grep refuses GNU-only `sed -i`, which `phase.sh`
  used for every frontmatter write; on BSD sed it fails silently and the
  frontmatter and state file drift. Replaced with awk to a temp file.
- **Doc-versus-code mismatches**, each verified by reading both sides:
  `CLAUDE.md` laws in source order 1, 2, 3, 6, 4, 5; `rules.md` claiming CI
  checks role ownership (nothing does); three files saying the Feature
  Developer writes `## Gate results` while three others say only the tool
  does; `check-boundaries.sh` accepting a scaffold inventory from a `spike`
  that no doc mentioned; `/advance-story` ordering "run the tests yourself"
  without `task.sh` in its allowed tools; `inject-state.sh` labelling the
  denial prose as the list of writable categories; `sections.md` sending a
  return to RED to `## Notes`; "sixteen gates" quoted against a template that
  ships eight; the quality-gates skill describing the hash as covering every
  harness file after PR #7 stopped it covering harness markdown; the README
  layout tree missing `.github/`, `lib.sh` and `mcp-notes.md`.
- **Growth since founding**, `git show 97d5fbf:<path> | wc -l` against HEAD:
  `CLAUDE.md` 82 to 119 lines while saying "it stays short"; `lead-po.md` 69
  to 175 while the README says agents are short; `quality-gates` 50 to 305;
  tracked lines 3,384 to 8,662, of which the new selftest suites are a large,
  legitimate share.

## What would have to be true for this to be wrong

- The bash 3.2 and BSD findings assume macOS users run the stock shell. One
  who has installed bash 5 and GNU sed via Homebrew never hit either; the
  fixes cost nothing there.
- The CRLF finding assumes git's "do not renormalise a file whose index entry
  already has CRLF" rule. The test asserts the outcome, not the rule.
- The `#` comment rule assumes a `#` after whitespace, `;`, `&`, `|` or `(`
  starts a comment. In bash it does; inside `${var#pattern}` it does not, but
  that `#` follows `{`, which is not in the list.
- The drift judgement is a reading, not a measurement. Line counts are given
  so it can be argued with.

## What was not checked

- Nothing was run on macOS, Linux (other than CI, which passed on PR #7), or
  bash 3.2.
- `shellcheck` is not installed on this machine; the shell review was by hand.
- The guard was probed with about thirty command shapes. The documented
  fail-open set (`$(...)` targets, `bash -c`, interpreters fed by heredoc,
  `find -delete`, `git apply`, `install`, `dd`, `rsync`, `perl -pi`) was
  confirmed open and left open.
- Consuming projects were not re-run against the changed hash. A story in
  flight at the moment of upgrade will see its recorded hash go stale once,
  because harness markdown left the set in PR #7; a full gate run fixes it.
- `phase.sh set <id> DONE` skips the dependency and branch guard. The header
  says the guard applies "past PLANNED". Left as is: DONE is set after the
  merge, often from `main`, where the branch check would refuse it.

## Stories filed

None. This repository does its own work on `harness/*` branches; the fixes
above are on `harness/repo-audit-2026-09-10`, each new selftest case watched
failing before the change that made it pass. The stale copy of the third
field report at the repository root, `agenticdevharnessbrief.md`, is untracked
and is not part of this.
