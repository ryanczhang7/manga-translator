# MCP servers

`.mcp.json` is project-scoped and shared with the team; it is gitignored here so
that the harness does not force a broken server on a machine without Node.

Copy `.mcp.json.example` to `.mcp.json` when you want it. What it is for:

**playwright** - gives the Lead Designer real eyes. With it, the designer can
open the running app, screenshot states, tab through the interface, and check
contrast and reflow against `docs/wiki/design/`, instead of writing opinions
about screens nobody has looked at. It also lets the Test Developer write real
end-to-end tests against a real browser. Requires Node.

Add others as the project needs them - a database server for a data-heavy
project, a GitHub server if you want richer PR interaction than `gh` gives.
Prefer few: every server costs context on every turn it is listed.
