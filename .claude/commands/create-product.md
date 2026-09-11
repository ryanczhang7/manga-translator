---
description: Interview the user and write the product brief
argument-hint: [one-line product idea]
---

Delegate to the **lead-po** subagent to produce `docs/wiki/product-brief.md`.

Starting idea from the user (may be empty): $ARGUMENTS

This is an interview, not a generation task. The Lead PO must talk to the user
and build the brief from their answers. Run it in the main conversation rather
than in a subagent if that is what it takes to actually ask questions and hear
the replies — the interview is the point.

Cover, asking follow-ups until each is genuinely answered:

1. **Problem** — what is painful today, and for whom. What do they do instead?
2. **Users** — who exactly, and what do they already know how to use?
3. **The first five minutes** — what does someone do the first time they open
   this, and what makes them come back?
4. **Core features** — the smallest set that makes v1 worth using. Push back on
   anything that is not load-bearing.
5. **Explicit non-goals** — what v1 deliberately will not do.
6. **Constraints** — platform, offline, performance, data, privacy, budget,
   deadline, anything the user already has strong opinions about.
7. **Success** — how we will know it worked, in observable terms.
8. **Look and feel** — tone, references, anything the Lead Designer needs.

Do not invent answers. If the user says "you decide", say what you would decide
and why, and get their agreement before writing it down as fact.

Write the brief with a short summary at the top, then a section per topic above,
and an open-questions section for anything still unresolved. Then tell the user
what to run next (`/plan-product`) and what it will produce.
