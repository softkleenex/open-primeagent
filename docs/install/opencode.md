# opencode

> 🚧 Adapter under investigation. Registering opa as an MCP **client** follows
> opencode's own MCP configuration; using opencode as a **child backend** needs
> its headless and session-resume interface confirmed first.

The adapter contract (`src/opa/rlm/adapters/base.py`) asks for exactly two things:

1. non-interactive execution from a single prompt
2. resume by session id

Once those are confirmed, the adapter is about thirty lines.
