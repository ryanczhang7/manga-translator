# Wiki

Durable knowledge about the product. Written by the Lead PO and Lead Designer,
read by everyone.

| File | Written by | Contents |
|---|---|---|
| `product-brief.md` | `/create-product` | the problem, the users, the scope, the constraints |
| `stack.md` | `/plan-product` | pinned technology choices, each tied to a constraint |
| `environment.md` | `/setup-environment` | what to install on a fresh machine, and how to verify it |
| `architecture.md` | `/plan-product` | components, data model, decisions and their alternatives |
| `design/` | Lead Designer | tokens, components, layout, accessibility floor, voice |
| `audits/` | Mutation Tester, or anyone auditing the harness | test-quality and harness audits. Structure from `audits/TEMPLATE.md`, which keeps what was **decided** apart from what was **measured** |

Keep these at the altitude where they stay true for months. Anything that
changes per story belongs in the story file, not here.

When requirements change, edit `product-brief.md` and re-run `/plan-product` -
it diffs against what exists rather than starting over.
