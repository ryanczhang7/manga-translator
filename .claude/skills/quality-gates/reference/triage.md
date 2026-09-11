# Triaging a failing gate

## format

Run the formatter. There is nothing to think about here; if the formatter and a
lint rule disagree, the formatter wins and the rule is wrong.

## lint

Fix the code. A suppression comment is legitimate only when the rule is
genuinely inapplicable at that site, and it must carry a reason on the same
line. Three suppressions of the same rule in one story means the rule is wrong
for this project - raise it, change the config deliberately, and note it in the
story rather than scattering exemptions.

## typecheck

Fix the types. Widening to a permissive type to silence the checker converts a
compile-time failure into a runtime one; that is a regression, not a fix. If an
external library has bad types, isolate the cast in one adapter with a comment
naming the library and version.

## unit

If a test you did not write is failing, you broke something the story did not
mention. Fix it, and consider whether the breakage deserves its own regression
test. If the test is genuinely wrong, stop: the story returns to RED.

Flaky failures are failures. A test that passes on retry is a test that will
fail in CI on the day it matters. Fix the nondeterminism - a real clock, an
unseeded random, an unawaited promise, an ordering assumption on an unordered
collection.

## coverage

A coverage failure names lines nothing exercises. Ask which of these it is:

- **Behaviour with no test** - the real case. Return to RED and cover it.
- **Code nobody asked for** - speculative generality. Delete it.
- **Genuinely unreachable** - a defensive branch that cannot occur. Either prove
  it can occur and test it, or remove it.

Do not chase the number with tests that execute code without asserting on it.
That raises coverage and lowers the value of the suite, which is worse than the
failure you started with.

## build

Usually a missing dependency, a path that works in dev and not in the bundle, or
an environment variable read at build time. Reproduce the production build
locally rather than reasoning about the difference.

## mutation

Surviving mutants are not gate failures in the same sense - they are findings.
File them as stories, ranked by what the un-caught change would do in
production, and fix them through the normal cycle.
