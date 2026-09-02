# Codex

In `~/.codex/config.toml`:

```toml
[mcp_servers.opa]
command = "uvx"
args = ["open-primeagent"]
```

From a local checkout:

```toml
[mcp_servers.opa]
command = "uv"
args = ["run", "--directory", "/path/to/open_primeagent", "opa"]
```

## Codex as a child

Codex also works as a **child** backend, so a Claude Code parent can drive Codex
children:

```python
await rlm("refactor this module", name="refactorer", adapter="codex", model="gpt-5.4")
```

Model choice is delegated to the host CLI, which is why mixed setups work at all.

Two things the adapter handles for you, both found by running it:

- stdin is closed; left open as a pipe, `codex exec` waits on stdin forever
- `--skip-git-repo-check` is always passed, since codex refuses to run outside a
  git repository
- children run under `--sandbox workspace-write` unless dangerous mode is opted into

## The push channel does not work under codex's sandbox

A child can normally report progress mid-run with `can_message_parent=True`. On
codex that only works when the sandbox is given up entirely.

Measured 2026-08-28: in headless `codex exec`, an MCP tool call comes back as
`user cancelled MCP tool call`. `approval_policy`, `mcp_servers.<name>.trust`
and `mcp_servers.<name>.enabled` make no difference — the approval policy governs
shell commands, not MCP tools, and a headless run has no channel to approve on.
With `--dangerously-bypass-approvals-and-sandbox` the same call completes.

So the codex adapter attaches the push server **only** when dangerous mode is
already on. Otherwise the child would be handed a tool that always fails, paying
for its schema and getting a confusing cancellation back.

Claude Code has no such restriction: scoping `--allowedTools` to the push tool is
enough, and the child keeps its ordinary tools.

## Known gap: a codex child still inherits your configured MCP servers

The claude adapter passes `--strict-mcp-config`, so a child starts from no MCP
servers and gets only what we hand it. codex has no per-invocation equivalent:
its servers come from `$CODEX_HOME/config.toml`, and the only lever is
`--ignore-user-config`, which would also discard the model and provider settings
a user relies on.

So a codex child can reach every MCP server you have configured. We have not
shipped `--ignore-user-config` for children because the trade is real and we
could not verify the result here — the codex login on this machine is expired.
If that matters to you, run codex children under a separate `CODEX_HOME`.
