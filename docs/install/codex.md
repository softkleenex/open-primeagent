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
