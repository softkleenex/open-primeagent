# Notes for agents working in this repository

## What this project is, in one line

An MCP server that brings Prime Agent's RLM to **the coding agent the user
already runs**, without replacing it.

## Read first

1. `TODO.md` — where things stand and what is next
2. `ARCHITECTURE.md` — why it is built this way
3. `ROADMAP.md` — the current phase's exit criteria

## Never break these

1. **Do not replace the host agent.** If you feel the urge to build a TUI, a
   session UI, a provider layer or OAuth, that is out of scope. Delegate to the
   host.
2. **Never exceed four MCP tools.** New capability is exposed as a Python symbol
   inside the kernel. More tools would pollute the host's tool list and
   contradict the whole thesis.
3. **Projection writes only inside the delimiter block.** Not one character of
   the user's own `CLAUDE.md` may change. This promise is the project's premise.
4. **`_ref/` is read-only reference.** It is not committed and no code is copied
   from it. This is an independent reimplementation, not a fork.

## How to work

- Verify phase exit criteria by **actually running them**. "It should work" does
  not count.
- Do not skip phase order. L2 is meaningless without L1.
- When you learn something new about a host CLI's real behavior, remove it from
  the investigation list in `TODO.md` and record it where it belongs.
- GitHub-facing content is written in **English**.

## Where to look upstream

| what | path |
|---|---|
| the whole rlm API surface (348 lines) | `_ref/prime-agent/prime-agent-runtime/src/rlm/__init__.py` |
| harness store schema | `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py` |
| upstream's 13 skills | `_ref/prime-agent/packages/coding-agent/skills/` |
